"""The S3 store: a bucket laid out as a folder store, read through a cache on this machine.

`tests/test_store_contract.py` has what every store must do; this file
has what is particular to a remote one: the URL, the cache, the check of
what was downloaded, a store that is read-only, and two machines on one
store.
"""

import json
import os
import sys
from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import config, data, lock, snapshot
from chartbook import store as store_module
from chartbook.store import FolderStore, ObjectNotFoundError, ReadOnlyStoreError, StoreError, StoreUnreachableError
from tests.mocked_s3 import BUCKET, URL, mocked_s3
from tests.test_model_versions import _commit, _git

pytest.importorskip("boto3")
pytest.importorskip("moto")

from chartbook.stores.s3 import S3Store, _parse_url  # noqa: E402

COMMIT = "b" * 40


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def client(monkeypatch):
    with mocked_s3(monkeypatch) as client:
        yield client


@pytest.fixture
def store(work, client):
    return S3Store(URL, cache=work / "cache", client=client)


@pytest.fixture
def a_file(work):
    path = work / "_data" / "rates.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"rates-1")
    return path


def _keys(client, prefix=""):
    found = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return sorted(entry["Key"] for entry in found.get("Contents", ()))


class TestTheUrl:
    def test_bucket_prefix_and_options(self):
        assert _parse_url("s3://bkt/p/q/") == ("bkt", "p/q", {})
        assert _parse_url("s3://bkt") == ("bkt", "", {})
        assert _parse_url("s3://bkt/p?endpoint=http://localhost:9000&region=eu-west-1") == (
            "bkt", "p", {"endpoint": "http://localhost:9000", "region": "eu-west-1"}
        )

    def test_what_is_refused(self):
        with pytest.raises(ValueError, match="not an S3 URL"):
            _parse_url("s3:///no-bucket")
        with pytest.raises(ValueError, match="Credentials never go in the URL"):
            _parse_url("s3://key:secret@bucket/p")
        with pytest.raises(ValueError, match="query key 'profile' this store does not read; the keys are: endpoint, region"):
            _parse_url("s3://bkt/p?profile=prod")
        for bad in ("s3://bkt/../../x", "s3://bkt/p//q", "s3://bkt/./p"):
            with pytest.raises(ValueError, match="empty, '.' or '..' segment"):
                _parse_url(bad)
        with pytest.raises(ValueError, match="names a bucket S3 would not"):
            _parse_url("s3://Bucket_Name/p")

    def test_str_is_the_place_without_the_options(self, work, client):
        store = S3Store("s3://chartbook-test/stores/one/?region=us-east-1", cache=work / "c", client=client)
        assert str(store) == "s3://chartbook-test/stores/one"
        assert repr(store) == "S3Store('s3://chartbook-test/stores/one')"
        assert store.options == {"region": "us-east-1"}

    def test_the_options_reach_the_client(self, work, monkeypatch):
        made = {}

        class FakeBoto3:
            @staticmethod
            def client(service, **arguments):
                made.update(arguments, service=service)
                return object()

        monkeypatch.setitem(sys.modules, "boto3", FakeBoto3)
        S3Store("s3://bkt/p?endpoint=http://localhost:9000&region=eu-west-1", cache=work / "c")
        assert made["service"] == "s3"
        assert made["endpoint_url"] == "http://localhost:9000" and made["region_name"] == "eu-west-1"

    def test_without_boto3_the_message_names_the_extra(self, work, monkeypatch):
        monkeypatch.setitem(sys.modules, "boto3", None)
        with pytest.raises(ValueError, match=r"needs boto3, which is not installed: pip install chartbook\[s3\]"):
            S3Store("s3://bkt/p", cache=work / "c")

    def test_the_cache_folder_follows_the_settings(self, work, client, monkeypatch):
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "elsewhere"))
        store = S3Store("s3://chartbook-test/a/b", client=client)
        assert store.cache == work / "elsewhere" / "s3" / "chartbook-test" / "a" / "b"
        monkeypatch.delenv(config.CACHE_ENV_VAR)
        monkeypatch.setattr(config, "read_settings", lambda: {})
        assert config.get_cache_path() == config.get_global_config_dir() / "cache"
        monkeypatch.setattr(config, "read_settings", lambda: {"cache": {"path": str(work / "from-settings")}})
        assert config.get_cache_path() == work / "from-settings"


class TestTheBucketIsAFolderStore:
    """The keys are the folder store's paths, so a synced folder is the same store."""

    def test_the_layout(self, store, client, a_file):
        stored = store.put(a_file)
        digest = stored.content_hash.split(":")[1]
        assert _keys(client) == [
            f"stores/one/objects/sha256/{digest[:2]}/{digest[2:]}/rates.parquet",
            "stores/one/store.json",
        ]
        assert json.loads(client.get_object(Bucket=BUCKET, Key="stores/one/store.json")["Body"].read()) == {"schema": store_module.SCHEMA}
        store.add_root(Path("/somewhere/chartbook.lock"), [stored.content_hash])
        store.write_snapshot(COMMIT, "_top", "20261016T000000Z", {"a": 1})
        store.note_origin(COMMIT, "_top", "/somewhere")
        assert [k for k in _keys(client) if "/objects/" not in k] == [
            f"stores/one/roots/{FolderStore(store.cache)._root_file('/somewhere/chartbook.lock').name}",
            f"stores/one/snapshots/{COMMIT}/_top/20261016T000000Z.json",
            f"stores/one/snapshots/{COMMIT}/_top/origins",
            "stores/one/store.json",
        ]

    def test_a_folder_store_synced_into_the_bucket_is_read(self, work, client, a_file):
        folder = FolderStore(work / "folder")
        stored = folder.put(a_file)
        folder.write_snapshot(COMMIT, "_top", "20261016T000000Z", {"root": "acme/rates"})
        for file in sorted(p for p in folder.root.rglob("*") if p.is_file()):
            client.put_object(Bucket=BUCKET, Key="synced/" + file.relative_to(folder.root).as_posix(), Body=file.read_bytes())
        store = S3Store(f"s3://{BUCKET}/synced", cache=work / "cache", client=client)
        assert store.has(stored.content_hash)
        assert (store.get(stored.content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert list(store.hashes()) == [stored.content_hash]
        assert json.loads(store.snapshot_files(COMMIT, "_top")[0].read_text())["root"] == "acme/rates"
        assert store.snapshot_commits() == {COMMIT}

    def test_a_store_with_another_layout_is_refused(self, work, client):
        client.put_object(Bucket=BUCKET, Key="stores/one/store.json", Body=b'{"schema": "chartbook/store/v9"}')
        store = S3Store(URL, cache=work / "cache", client=client)
        with pytest.raises(StoreError, match="has the layout 'chartbook/store/v9'"):
            store.has("sha256:" + "0" * 64)


class TestTheCache:
    def test_a_second_machine_downloads_once(self, work, client, a_file, monkeypatch):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        stored = first.put(a_file)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        downloads = []
        original = second._download
        monkeypatch.setattr(second, "_download", lambda key, target: (downloads.append(key), original(key, target)))
        held = second.get(stored.content_hash)
        assert held == second.cache / "objects" / "sha256" / stored.content_hash[7:9] / stored.content_hash[9:]
        assert (held / "rates.parquet").read_bytes() == b"rates-1"
        assert not os.access(held / "rates.parquet", os.W_OK)
        assert second.get(stored.content_hash) == held
        assert len(downloads) == 1

    def test_a_name_added_later_is_fetched(self, work, client, a_file):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        stored = first.put(a_file)
        assert sorted(p.name for p in second.get(stored.content_hash).iterdir()) == ["rates.parquet"]
        other = work / "other.parquet"
        other.write_bytes(b"rates-1")
        assert first.put(other).created is False
        assert sorted(p.name for p in second.get(stored.content_hash).iterdir()) == ["other.parquet", "rates.parquet"]

    def test_what_was_downloaded_must_hash_to_its_name(self, store, client, a_file):
        stored = store.put(a_file)
        fresh = S3Store(URL, cache=store.cache.parent / "fresh", client=client)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        client.put_object(Bucket=BUCKET, Key=key, Body=b"rates-2")
        with pytest.raises(StoreError, match="is not what its name says: its content is no longer what its name says"):
            fresh.get(stored.content_hash)
        assert not fresh._cache.has(stored.content_hash)
        (problem,) = fresh.verify()
        assert problem.content_hash == stored.content_hash and "no longer what its name says" in problem.message
        # The machine that put it has a good copy and never re-reads a file of the right size
        assert (store.get(stored.content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        (problem,) = store.verify()  # verify downloads again, into a scratch folder, and so finds it
        assert problem.content_hash == stored.content_hash
        assert problem.path == store.cache / "objects" / "sha256" / stored.content_hash[7:9] / stored.content_hash[9:]
        assert (store.get(stored.content_hash) / "rates.parquet").read_bytes() == b"rates-1"  # the good copy stays
        assert not any((store.cache / "tmp").iterdir())

    def test_a_record_removed_elsewhere_goes_from_the_cache(self, work, client):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        written = first.write_snapshot(COMMIT, "_top", "20261016T000000Z", {"a": 1})
        (seen,) = second.snapshot_files(COMMIT, "_top")
        assert seen.is_file()
        assert first.remove_snapshot(written) is True
        assert second.snapshot_files(COMMIT, "_top") == [] and not seen.exists()
        assert second.all_snapshot_files() == []

    def test_a_copy_under_another_name(self, store, client, a_file):
        """A folder store synced into a bucket may bring a sync service's copies: `<stamp> (1).json`.

        A copy of a record is passed over; a copy of a note is read, as a note
        only ever adds to what is kept, and one that cannot be read is an error."""
        stored = store.put(a_file)
        store.add_root(Path("/somewhere/chartbook.lock"), [stored.content_hash])
        written = store.write_snapshot(COMMIT, "_top", "20261016T000000Z", {"a": 1})
        store.note_origin(COMMIT, "_top", "/somewhere")
        (note,) = [k for k in _keys(client) if "/roots/" in k]
        body = client.get_object(Bucket=BUCKET, Key=note)["Body"].read()
        client.put_object(Bucket=BUCKET, Key=note.replace(".json", " (1).json"), Body=body)
        record = f"stores/one/snapshots/{COMMIT}/_top/20261016T000000Z"
        client.put_object(Bucket=BUCKET, Key=f"{record} (1).json", Body=b'{"a": 1}')
        assert sorted((str(root.lockfile), root.copy) for root in store.roots()) == [
            (str(Path("/somewhere/chartbook.lock")), False), (str(Path("/somewhere/chartbook.lock")), True)
        ]
        client.put_object(Bucket=BUCKET, Key=note.replace(".json", " (2).json"), Body=b'{"lock')
        with pytest.raises(StoreError, match="if it is a copy nobody needs"):
            store.roots()  # half a copy: what it keeps cannot be said
        client.delete_object(Bucket=BUCKET, Key=note.replace(".json", " (2).json"))
        assert store.snapshot_files(COMMIT, "_top") == [written] and store.all_snapshot_files() == [written]
        assert store.remove_snapshot(written) is True
        assert f"stores/one/snapshots/{COMMIT}/_top/origins" not in _keys(client)

    def test_a_path_outside_the_cache_is_not_a_record(self, store, work):
        with pytest.raises(ValueError, match="is not a snapshot record of the store"):
            store.remove_snapshot(work / "elsewhere.json")

    def test_age_and_size_come_from_the_bucket(self, store, a_file):
        stored = store.put(a_file)
        assert store.size_of(stored.content_hash) == 7
        assert 0 <= store.age_of(stored.content_hash) < 60
        with pytest.raises(ObjectNotFoundError):
            store.age_of("sha256:" + "0" * 64)

    def test_delete_takes_the_cached_copy_too(self, store, a_file):
        stored = store.put(a_file)
        assert store._cache.has(stored.content_hash)
        assert store.delete(stored.content_hash) is True
        assert not store._cache.has(stored.content_hash) and not store.has(stored.content_hash)

    def test_offline_an_object_read_before_is_served(self, work, client, a_file, monkeypatch):
        import botocore.exceptions

        store = S3Store(URL, cache=work / "cache", client=client)
        stored = store.put(a_file)
        other = S3Store(URL, cache=work / "other", client=client)
        unread = other.put(work / "x.parquet") if (work / "x.parquet").write_bytes(b"x") else None
        held = store.get(stored.content_hash)

        def offline(*args, **kwargs):
            raise botocore.exceptions.EndpointConnectionError(endpoint_url="https://s3.amazonaws.com")

        monkeypatch.setattr(client, "get_paginator", offline)
        assert store.get(stored.content_hash) == held  # read and checked before: served from the cache
        with pytest.raises(StoreUnreachableError, match="cannot be reached to list"):
            store.get(unread.content_hash)  # never read here: nothing to serve
        with pytest.raises(StoreUnreachableError):
            store.has(stored.content_hash)

    def test_a_file_that_is_not_the_objects_is_removed_from_the_cache(self, store, a_file):
        stored = store.put(a_file)
        held = store.get(stored.content_hash)
        (held / "stray.parquet").write_bytes(b"not in the bucket")
        assert sorted(p.name for p in store.get(stored.content_hash).iterdir()) == ["rates.parquet"]
        assert store.get(stored.content_hash) == held

    def test_downloads_land_outside_the_object_folder(self, work, client, a_file, monkeypatch):
        first = S3Store(URL, cache=work / "a", client=client)
        stored = first.put(a_file)
        second = S3Store(URL, cache=work / "b", client=client)
        seen = []
        original = second._client.download_file
        monkeypatch.setattr(second._client, "download_file", lambda bucket, key, filename: (seen.append(Path(filename)), original(bucket, key, filename)))
        second.get(stored.content_hash)
        assert seen and all(p.parent == second.cache / "tmp" for p in seen)

    def test_a_half_uploaded_object_is_named_for_what_it_is(self, work, client):
        folder = work / "_models" / "m"
        folder.mkdir(parents=True)
        (folder / "a.bin").write_bytes(b"a" * 10)
        (folder / "b.bin").write_bytes(b"b" * 10)
        owner = S3Store(URL, cache=work / "owner", client=client)
        stored = owner.put(folder)
        (key,) = [k for k in _keys(client) if k.endswith("/b.bin")]
        client.delete_object(Bucket=BUCKET, Key=key)
        fresh = S3Store(URL, cache=work / "fresh", client=client)
        assert fresh.has(stored.content_hash)  # a listing cannot tell a partial object
        with pytest.raises(StoreError, match="interrupted while uploading it; making the snapshot again completes it"):
            fresh.get(stored.content_hash)
        again = owner.put(folder)  # uploads what is missing, and only that
        assert again.created is False and again.content_hash == stored.content_hash
        assert sorted(p.name for p in fresh.get(stored.content_hash).iterdir()) == ["a.bin", "b.bin"]

    def test_putting_an_object_the_bucket_has_counts_as_storing_it_now(self, store, a_file, monkeypatch):
        stored = store.put(a_file)
        touched = []
        monkeypatch.setattr(store, "_touch", lambda key: touched.append(key))
        again = store.put(a_file)
        assert again.created is False and touched == [k for k in _keys(store._client) if k.endswith("rates.parquet")]

    def test_links_are_read_for_their_errors(self, store, a_file):
        with pytest.raises(ValueError, match="Unknown link kind"):
            store.put(a_file, links=())
        with pytest.raises(ValueError, match="Unknown link kind"):
            store.put(a_file, links=("teleport",))

    def test_remove_snapshot_takes_only_a_record(self, store, a_file):
        stored = store.put(a_file)
        held = store.get(stored.content_hash)
        with pytest.raises(ValueError, match="is not a snapshot record of the store"):
            store.remove_snapshot(held / "rates.parquet")
        assert store.has(stored.content_hash)


def _refusing(client):
    """The real client, for a machine the bucket is read-only to: the service refuses every write.

    The refusals are planted where the service answers, so that an upload
    still goes through boto3's transfer manager, which wraps the service's
    error in its own, as it does in life.
    """
    import botocore.exceptions

    def refused(operation):
        def call(*args, **kwargs):
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, operation
            )

        return call

    for name in ("put_object", "delete_objects", "delete_object", "copy_object", "create_multipart_upload"):
        setattr(client, name, refused(name))
    return client


class TestReadOnly:
    def test_reads_work_and_writes_say_so(self, work, client, a_file):
        owner = S3Store(URL, cache=work / "owner", client=client)
        stored = owner.put(a_file)
        reader = S3Store(URL, cache=work / "reader", client=_refusing(client))
        assert reader.has(stored.content_hash)
        assert (reader.get(stored.content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert list(reader.hashes()) == [stored.content_hash]
        (work / "other.parquet").write_bytes(b"new")
        with pytest.raises(ReadOnlyStoreError, match="refused to upload .*: AccessDenied. If this store is read-only for you"):
            reader.put(work / "other.parquet")
        with pytest.raises(ReadOnlyStoreError, match="refused to write .*roots"):
            reader.add_root(work / "chartbook.lock", [stored.content_hash])
        assert lock.is_read_only(ReadOnlyStoreError("x"))

    def test_the_refusal_reaches_the_command_as_one_line(self, work, client, a_file):
        from chartbook.cli import _explain_os_error

        reader = S3Store(URL, cache=work / "reader", client=_refusing(client))
        with pytest.raises(ReadOnlyStoreError) as caught:
            reader.add_root(work / "chartbook.lock", [])
        explained = _explain_os_error(caught.value)
        assert explained.startswith(f"The store {URL} refused to write") and "use --frozen" in explained

    def test_a_bucket_that_is_not_there(self, work, client):
        store = S3Store("s3://no-such-bucket/p", cache=work / "c", client=client)
        with pytest.raises(StoreError, match="bucket that does not exist"):
            store.has("sha256:" + "0" * 64)


@pytest.fixture
def pipelines(work):
    """``rates`` and ``forecast``, which depends on it, in one repository."""
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "A file."}}})
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}})
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(work)
    return rates, forecast


class TestTwoPipelinesOnAnS3Store:
    """The headline: the store in the settings is a bucket, and nothing else changes."""

    def test_snapshot_pin_load_and_frozen_from_another_machine(self, work, client, pipelines, monkeypatch):
        rates, forecast = pipelines
        store_module._plugin_store_class.cache_clear()
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-a"))
        made = snapshot.make(rates)
        assert made.snapshot.assets["treasury"]["content_hash"].startswith("sha256:")
        assert any(k.endswith("/treasury.parquet") for k in _keys(client))

        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        monkeypatch.chdir(forecast)
        assert data.load("rates:treasury").collect().shape == (1, 2)
        assert data.path("rates:treasury") == work / "machine-a" / "s3" / BUCKET / "stores" / "one" / "objects" / "sha256" / made.snapshot.assets["treasury"]["content_hash"][7:9] / made.snapshot.assets["treasury"]["content_hash"][9:] / "treasury.parquet"
        assert lock.verify(forecast).problems == [] and lock.verify(forecast).pins == 1

        # Another machine, with nothing downloaded yet, and the store read-only for it
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-b"))
        monkeypatch.setattr(S3Store, "_make_client", lambda self, url: _refusing(client))
        assert lock.verify(forecast).problems == [] and lock.verify(forecast).pins == 1
        assert data.load("rates:treasury").collect().shape == (1, 2)
        assert data.path("rates:treasury").is_relative_to(work / "machine-b")
        # It can pin afresh too: the pins are in the store, only the note for gc is not left
        (forecast / lock.LOCK_FILE).unlink()
        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        assert report.unrooted and "refused to write" in report.unrooted
        assert (forecast / lock.LOCK_FILE).is_file()


class TestKeysThatLeaveTheCache:
    """Anyone who can write to the bucket chooses its keys; a reader never makes a file outside its cache."""

    PLANTED = ("../../../../../OUTSIDE.txt", "../../../../../../OUTSIDE2.txt", "a//b.txt", "./d.txt") + (
        ("a\\..\\..\\x.txt", "c:x.txt") if os.name == "nt" else ()
    )

    def _outside(self, work: Path) -> list:
        return [p for p in work.rglob("*") if p.name.startswith(("OUTSIDE", "ABS", "evil"))]

    def test_an_objects_keys(self, work, client, a_file):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        stored = first.put(a_file)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        prefix = key[: -len("rates.parquet")]
        for planted in (*self.PLANTED, str(work / "ABS.txt")):
            client.put_object(Bucket=BUCKET, Key=prefix + planted, Body=b"planted")
        second = S3Store(URL, cache=work / "machine-b", client=client)
        held = second.get(stored.content_hash)
        # The object is its own files; nothing else was written anywhere
        assert sorted(p.name for p in held.iterdir()) == ["rates.parquet"]
        assert self._outside(work) == [] and not (work.parent / "OUTSIDE2.txt").exists()
        assert second.verify() == []
        # Deleting the object takes every key under it, planted ones too
        assert first.delete(stored.content_hash) is True
        assert _keys(client, prefix) == []

    def test_a_snapshot_records_keys(self, work, client):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        written = first.write_snapshot(COMMIT, "_top", "20261016T000000Z", {"a": 1})
        (key,) = [k for k in _keys(client) if "/snapshots/" in k or k.startswith("snapshots/")]
        root = key[: key.index("snapshots/") + len("snapshots/")]
        for planted in ("../../evil.json", "../x/evil2.json", f"{COMMIT}/_top/../../../evil3.json", "a//b/evil4.json"):
            client.put_object(Bucket=BUCKET, Key=root + planted, Body=b"{}")
        second = S3Store(URL, cache=work / "machine-b", client=client)
        seen = second.all_snapshot_files()
        assert [p.name for p in seen] == [written.name]
        assert self._outside(work) == [p for p in self._outside(work) if p.is_relative_to(work / "machine-b" / "snapshots")] == []

    def test_a_key_is_never_made_a_path_out_of_the_cache(self, store):
        with pytest.raises(StoreError, match="not a plain path"):
            store._local(store.prefix + "/../x.json" if store.prefix else "../x.json")


class TestWhatTheFourthReviewFound:
    @pytest.mark.skipif(os.name == "nt", reason="Windows has no file named with a colon or a backslash")
    def test_a_file_named_with_a_colon_or_a_backslash_is_read_back(self, work, client):
        folder = work / "_data" / "daily"
        folder.mkdir(parents=True)
        (folder / "2024-01-01T00:00:00.csv").write_bytes(b"a")
        (folder / "a\\b.csv").write_bytes(b"b")
        first = S3Store(URL, cache=work / "machine-a", client=client)
        stored = first.put(folder)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        held = second.get(stored.content_hash)
        assert sorted(p.name for p in held.iterdir()) == ["2024-01-01T00:00:00.csv", "a\\b.csv"]
        assert second.verify() == []
        assert first.put(folder).created is False

    def test_an_object_of_keys_that_are_no_files_is_removed_by_gc(self, work, client, a_file):
        store = S3Store(URL, cache=work / "machine-a", client=client)
        stored = store.put(a_file)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        prefix = key[: -len("rates.parquet")]
        other = prefix.replace(stored.content_hash[9:], "f" * 62)
        client.put_object(Bucket=BUCKET, Key=other + "../x", Body=b"planted")
        client.put_object(Bucket=BUCKET, Key=prefix, Body=b"")  # a folder marker, as the S3 console makes
        planted = "sha256:" + other.rstrip("/").split("/")[-2] + other.rstrip("/").split("/")[-1]
        assert planted in set(store.hashes()) and not store.has(planted)
        assert store.size_of(planted) == len(b"planted") and store.age_of(planted) >= 0
        plan = lock.plan_gc(store=store, recent_seconds=0)
        assert planted in [content_hash for content_hash, _ in plan.delete]
        assert store.delete(planted) is True and _keys(client, other) == []
        assert store.delete(stored.content_hash) is True and _keys(client, prefix) == []

    @pytest.mark.parametrize(
        "named", ["notes.txt", "//host/share/chartbook.lock", r"\\host\share\chartbook.lock", "relative/chartbook.lock"]
    )
    def test_gc_reads_only_a_lockfile_on_this_machine(self, work, a_file, monkeypatch, named):
        store = FolderStore(work / "store")
        stored = store.put(a_file)
        store.add_root(work / "chartbook.lock", [stored.content_hash])
        # The note as anyone who can write to the store could write it
        target = str(work / named) if named == "notes.txt" else named
        if named == "notes.txt":
            Path(target).write_text("not a lockfile")
        (note,) = (work / "store" / "roots").glob("*.json")
        note.write_text(json.dumps({**json.loads(note.read_text()), "lockfile": target, "hashes": [stored.content_hash]}))
        assert [str(root.lockfile) for root in store.roots()] == [str(Path(target))]
        read = []
        original = lock.read_lock
        monkeypatch.setattr(lock, "read_lock", lambda path: (read.append(str(path)), original(path))[1])
        plan = lock.plan_gc(store=store, recent_seconds=0)
        assert read == []
        # Not read, so taken as a lockfile that cannot be found: what it names is kept
        assert stored.content_hash not in [content_hash for content_hash, _ in plan.delete]

    @pytest.mark.parametrize("named", [r"\\server\share\proj\chartbook.lock", "//server/share/proj/chartbook.lock"])
    def test_a_lockfile_not_read_is_never_forgotten(self, work, a_file, named):
        """A project on a network drive has its lockfile noted by a network path: gc does not read it,
        and does not take it as gone either, even with --forget-missing."""
        store = FolderStore(work / "store")
        stored = store.put(a_file)
        store.add_root(work / "chartbook.lock", [stored.content_hash])
        (note,) = (work / "store" / "roots").glob("*.json")
        note.write_text(json.dumps({**json.loads(note.read_text()), "lockfile": named, "hashes": [stored.content_hash]}))
        plan = lock.plan_gc(store=store, forget_missing=True, recent_seconds=0)
        assert [str(p) for p in plan.not_read] == [str(Path(named))] and plan.forget == []
        assert stored.content_hash not in [content_hash for content_hash, _ in plan.delete]


class TestAnotherMachineWithoutTheUpstreamFolder:
    """A pipeline cloned on another machine reads what its lockfile pins from a shared store,
    with the pipeline it depends on neither there nor built (docs: "A store in a synced folder")."""

    def _machine_two(self, rates, forecast, monkeypatch):
        import shutil

        shutil.rmtree(rates)
        monkeypatch.chdir(forecast)
        checked = lock.verify(forecast)
        assert checked.problems == [] and checked.pins == 1
        assert data.load("rates:treasury").collect().shape == (1, 2)
        assert {e.status for e in lock.pin(forecast).events if e.asset} == {"kept"}

    def test_a_folder_store(self, work, pipelines, monkeypatch):
        rates, forecast = pipelines
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "synced" / "store"))
        snapshot.make(rates)
        lock.pin(forecast)
        self._machine_two(rates, forecast, monkeypatch)

    def test_an_s3_store(self, work, client, pipelines, monkeypatch):
        rates, forecast = pipelines
        store_module._plugin_store_class.cache_clear()
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-a"))
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-b"))
        self._machine_two(rates, forecast, monkeypatch)
