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
