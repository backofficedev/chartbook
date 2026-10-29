"""The S3 store: a bucket laid out as a folder store, read through a cache on this machine.

`tests/test_store_contract.py` has what every store must do; this file
has what is particular to a remote one: the URL, the keys, the cache and
the check of what was downloaded, half a snapshot in the bucket, a store
that is read-only or cannot be reached, and two machines on one store.
"""

import json
import os
import sys
import time
import types
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.store import (
    PENDING_SECONDS,
    FolderStore,
    ObjectNotFoundError,
    ReadOnlyStoreError,
    StoreError,
    StoreUnreachableError,
)
from tests.mocked_s3 import BUCKET, URL, mocked_s3
from tests.test_model_versions import _commit, _git

pytest.importorskip("boto3")
pytest.importorskip("moto")

from chartbook.stores import s3  # noqa: E402
from chartbook.stores.s3 import S3Store, _parse_url  # noqa: E402
from tests.fixtures import remove_tree  # noqa: E402

COMMIT = "b" * 40
LATER = "c" * 40
FIRST = "2026-10-16T01:02:03.000000Z"
SECOND = "2026-10-17T01:02:03.000000Z"
HERE = "stores/one/pipelines/acme+rates/2026-10-16T010203Z_bbbbbbbbbbbb"


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
    path.write_bytes(b"unowned")
    return path


def _keys(client, prefix=""):
    found = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return sorted(entry["Key"] for entry in found.get("Contents", ()))


def _pipeline(work: Path, files: dict) -> Path:
    """A pipeline's folder holding these files, by their paths in it."""
    folder = work / "rates"
    for name, body in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(body)
    return folder


def _snapshot(store, folder: Path, assets: dict, commit: str = COMMIT, made_at: str = FIRST, made_by: str = "snapshot"):
    """A snapshot of ``acme/rates``: each asset by its name and its path in the pipeline's folder. Its record, and what was put."""
    pending = store.begin("acme/rates", commit, made_at, base=folder, made_by=made_by)
    put = {name: pending.put(folder / path) for name, path in assets.items()}
    record = pending.write({
        "schema": "chartbook/snapshot/v2",
        "root": "acme/rates",
        "code": {"commit": commit},
        "made_at": made_at,
        "records": [
            {"id": f"acme/rates:{name}", "content_hash": stored.content_hash, "size_bytes": stored.size_bytes, "stored": stored.stored}
            for name, stored in sorted(put.items())
        ],
    })
    return record, put


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

    def test_the_layout(self, store, client, work, a_file):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/parts/a.txt": b"a"})
        _snapshot(store, folder, {"rates": "_data/rates.parquet", "parts": "_data/parts"})
        unowned = store.put(a_file)
        store.add_root(Path("/somewhere/chartbook.lock"), [unowned.content_hash])
        store.note_origin(COMMIT, "_top", "/somewhere")
        assert _keys(client) == [
            f"stores/one/origins/{COMMIT}/_top.txt",
            f"stores/one/pipelines/+unowned/{unowned.content_hash[7:]}/rates.parquet",
            f"{HERE}/_chartbook/snapshot.json",
            f"{HERE}/_data/parts/a.txt",
            f"{HERE}/_data/rates.parquet",
            f"stores/one/roots/{store_module.root_name('/somewhere/chartbook.lock', store_module.this_machine())}",
            "stores/one/store.json",
        ]
        assert json.loads(client.get_object(Bucket=BUCKET, Key="stores/one/store.json")["Body"].read()) == {"schema": store_module.SCHEMA}

    def test_a_folder_store_synced_into_the_bucket_is_read(self, work, client):
        local = FolderStore(work / "folder")
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        record, put = _snapshot(local, folder, {"rates": "_data/rates.parquet", "parts": "_data/parts"})
        for file in sorted(p for p in local.root.rglob("*") if p.is_file()):
            client.put_object(Bucket=BUCKET, Key="synced/" + file.relative_to(local.root).as_posix(), Body=file.read_bytes())
        bucket = S3Store(f"s3://{BUCKET}/synced", cache=work / "cache", client=client)
        assert bucket.snapshot_commits() == {COMMIT}
        (seen,) = bucket.all_snapshot_files()
        assert json.loads(seen.read_text(encoding="utf-8")) == json.loads(Path(record).read_text(encoding="utf-8"))
        assert sorted(bucket.hashes()) == sorted(local.hashes())
        assert (bucket.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert sorted(p.name for p in bucket.get(put["parts"].content_hash).iterdir()) == ["a.txt", "b.txt"]
        assert bucket.verify() == []

    def test_a_bucket_of_the_layout_before_is_refused_until_it_is_moved(self, work, client):
        client.put_object(Bucket=BUCKET, Key="stores/one/store.json", Body=b'{"schema": "chartbook/store/v1"}')
        store = S3Store(URL, cache=work / "cache", client=client)
        for asking in (lambda: store.has("sha256:" + "0" * 64), store.all_snapshot_files, lambda: store.begin("acme/rates", COMMIT, FIRST)):
            with pytest.raises(StoreError, match=r"layout of ChartBook 0\.2 .*run `chartbook store migrate`"):
                asking()
        assert _keys(client) == ["stores/one/store.json"]  # nothing written beside it

    def test_a_store_with_another_layout_is_refused(self, work, client):
        client.put_object(Bucket=BUCKET, Key="stores/one/store.json", Body=b'{"schema": "chartbook/store/v9"}')
        store = S3Store(URL, cache=work / "cache", client=client)
        with pytest.raises(StoreError, match="has the layout 'chartbook/store/v9'"):
            store.has("sha256:" + "0" * 64)


class TestTheCache:
    def test_a_file_is_downloaded_once_and_checked(self, work, client, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        owner = S3Store(URL, cache=work / "machine-a", client=client)
        _, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet"})
        second = S3Store(URL, cache=work / "machine-b", client=client)
        downloads = []
        original = second._download
        monkeypatch.setattr(second, "_download", lambda key, target, content_hash=None: (downloads.append((key, content_hash)), original(key, target, content_hash))[1])
        held = second.get(put["rates"].content_hash)
        # The file's own folder, as the bucket has it, in the cache
        assert held == second.cache / "pipelines" / "acme+rates" / "2026-10-16T010203Z_bbbbbbbbbbbb" / "_data"
        assert (held / "rates.parquet").read_bytes() == b"rates-1" and not os.access(held / "rates.parquet", os.W_OK)
        assert second.get(put["rates"].content_hash) == held
        files = [(key, content_hash) for key, content_hash in downloads if not key.endswith("snapshot.json")]
        assert files == [(f"{HERE}/_data/rates.parquet", put["rates"].content_hash)]  # once, against its hash

    def test_the_machine_that_made_it_downloads_nothing(self, store, work, monkeypatch):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        _, put = _snapshot(store, folder, {"parts": "_data/parts"})
        monkeypatch.setattr(store, "_download", lambda *a, **k: pytest.fail("downloaded what it put"))
        gathered = store.get(put["parts"].content_hash)
        assert gathered == store.views / put["parts"].content_hash[7:]
        assert {p.name: p.read_bytes() for p in gathered.iterdir()} == {"a.txt": b"a", "b.txt": b"b"}

    def test_a_file_that_is_not_what_its_record_says_is_not_kept(self, work, client):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        owner = S3Store(URL, cache=work / "machine-a", client=client)
        _, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet"})
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_data/rates.parquet", Body=b"rates-2")  # the same size, other bytes
        fresh = S3Store(URL, cache=work / "machine-b", client=client)
        with pytest.raises(StoreError, match=r"_data/rates.parquet of sha256:.* is not what its snapshot's record says"):
            fresh.get(put["rates"].content_hash)
        assert not (fresh.cache / "pipelines" / "acme+rates" / "2026-10-16T010203Z_bbbbbbbbbbbb" / "_data").exists()
        (problem,) = fresh.verify()
        assert problem.content_hash == put["rates"].content_hash and "no longer what its record says" in problem.message
        # The machine that put it has its own copy, checked as it went; verify downloads again, and so finds it
        assert (owner.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        (problem,) = owner.verify()
        assert problem.content_hash == put["rates"].content_hash
        assert (owner.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert not any((owner.cache / "tmp").iterdir())

    def test_an_object_no_pipeline_owns_must_hash_to_its_name(self, store, client, a_file):
        stored = store.put(a_file)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        client.put_object(Bucket=BUCKET, Key=key, Body=b"rates-2")
        fresh = S3Store(URL, cache=store.cache.parent / "fresh", client=client)
        with pytest.raises(StoreError, match="is not what its name says: its content is no longer what its name says"):
            fresh.get(stored.content_hash)
        assert not (fresh.cache / "pipelines" / "+unowned").exists() or not any((fresh.cache / "pipelines" / "+unowned").iterdir())
        assert [problem.content_hash for problem in fresh.verify()] == [stored.content_hash]

    def test_a_name_added_later_is_fetched_and_a_stray_file_goes(self, work, client, a_file):
        first = S3Store(URL, cache=work / "machine-a", client=client)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        stored = first.put(a_file)
        held = second.get(stored.content_hash)
        assert sorted(p.name for p in held.iterdir()) == ["rates.parquet"]
        other = work / "other.parquet"
        other.write_bytes(b"unowned")
        assert first.put(other).created is False
        assert sorted(p.name for p in second.get(stored.content_hash).iterdir()) == ["other.parquet", "rates.parquet"]
        os.chmod(held, 0o755)
        (held / "stray.parquet").write_bytes(b"not in the bucket")
        assert sorted(p.name for p in second.get(stored.content_hash).iterdir()) == ["other.parquet", "rates.parquet"]
        assert second.get(stored.content_hash) == held

    def test_the_same_bytes_under_two_names_are_read_by_each(self, work, client):
        """Kept once, under the first one's path; a reader of the other is handed a folder with its own name."""
        folder = _pipeline(work, {"_data/committed.parquet": b"hello", "_data/twin.parquet": b"hello"})
        owner = S3Store(URL, cache=work / "machine-a", client=client)
        _, put = _snapshot(owner, folder, {"committed": "_data/committed.parquet", "twin": "_data/twin.parquet"})
        assert put["committed"].content_hash == put["twin"].content_hash
        assert [k for k in _keys(client) if k.endswith(".parquet")] == [f"{HERE}/_data/committed.parquet"]
        reader = S3Store(URL, cache=work / "machine-b", client=client)
        content_hash = put["twin"].content_hash
        assert (reader.get(content_hash, name="committed.parquet") / "committed.parquet").read_bytes() == b"hello"
        assert (reader.get(content_hash, name="twin.parquet") / "twin.parquet").read_bytes() == b"hello"

    def test_a_record_removed_elsewhere_goes_from_the_cache(self, work, client):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        first = S3Store(URL, cache=work / "machine-a", client=client)
        second = S3Store(URL, cache=work / "machine-b", client=client)
        written, _ = _snapshot(first, folder, {"rates": "_data/rates.parquet"})
        (seen,) = second.snapshot_files(COMMIT, "_top")
        assert seen.is_file()
        assert first.remove_snapshot(written) is True
        assert second.snapshot_files(COMMIT, "_top") == [] and not seen.exists()
        assert second.all_snapshot_files() == []

    def test_a_copy_under_another_name(self, store, client, work, a_file):
        """A folder store synced into a bucket may bring a sync service's copies: `snapshot (1).json`.

        A copy of a record is passed over; a copy of a note is read, as a note
        only ever adds to what is kept, and one that cannot be read is an error."""
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        written, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        store.add_root(Path("/somewhere/chartbook.lock"), [put["rates"].content_hash])
        (note,) = [k for k in _keys(client) if "/roots/" in k]
        body = client.get_object(Bucket=BUCKET, Key=note)["Body"].read()
        client.put_object(Bucket=BUCKET, Key=note.replace(".json", " (1).json"), Body=body)
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/snapshot (1).json", Body=Path(written).read_bytes())
        assert sorted((str(root.lockfile), root.copy) for root in store.roots()) == [
            (os.path.abspath("/somewhere/chartbook.lock"), False), (os.path.abspath("/somewhere/chartbook.lock"), True)  # with a drive on Windows
        ]
        client.put_object(Bucket=BUCKET, Key=note.replace(".json", " (2).json"), Body=b'{"lock')
        with pytest.raises(StoreError, match="if it is a copy nobody needs"):
            store.roots()  # half a copy: what it keeps cannot be said
        assert store.snapshot_files(COMMIT, "_top") == [written] and store.all_snapshot_files() == [written]

    def test_a_path_outside_the_cache_is_not_a_record(self, store, work):
        with pytest.raises(ValueError, match="is not a snapshot record of the store"):
            store.remove_snapshot(work / "elsewhere.json")

    def test_remove_snapshot_takes_only_a_record(self, store, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        held = store.get(put["rates"].content_hash)
        with pytest.raises(ValueError, match="is not a snapshot record of the store"):
            store.remove_snapshot(held / "rates.parquet")
        assert store.has(put["rates"].content_hash)

    def test_age_and_size_come_from_the_bucket(self, store, work, a_file):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a" * 10, "_data/parts/b.txt": b"b" * 20})
        _, put = _snapshot(store, folder, {"parts": "_data/parts"})
        stored = store.put(a_file)
        assert store.size_of(put["parts"].content_hash) == 30 and store.size_of(stored.content_hash) == 7
        assert 0 <= store.age_of(put["parts"].content_hash) < 60 and 0 <= store.age_of(stored.content_hash) < 60
        with pytest.raises(ObjectNotFoundError):
            store.age_of("sha256:" + "0" * 64)

    def test_delete_takes_the_cached_copy_too(self, store, client, work, a_file):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        held = store.get(put["rates"].content_hash) / "rates.parquet"
        stored = store.put(a_file)
        cached = store.get(stored.content_hash)
        assert store.delete(put["rates"].content_hash) is True and store.delete(stored.content_hash) is True
        assert not held.exists() and not cached.exists()
        assert [k for k in _keys(client) if k.endswith(".parquet")] == []
        # Its record names it still, without holding it, as a store that lost it would
        assert not store.has(put["rates"].content_hash) and not store.has(stored.content_hash)

    def test_downloads_land_outside_the_folders_a_reader_opens(self, work, client, a_file, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        first = S3Store(URL, cache=work / "a", client=client)
        _, put = _snapshot(first, folder, {"rates": "_data/rates.parquet"})
        stored = first.put(a_file)
        second = S3Store(URL, cache=work / "b", client=client)
        seen = []
        original = second._client.download_file
        monkeypatch.setattr(second._client, "download_file", lambda bucket, key, filename: (seen.append(Path(filename)), original(bucket, key, filename)))
        second.get(put["rates"].content_hash)
        second.get(stored.content_hash)
        assert seen and all(p.parent == second.cache / "tmp" for p in seen)

    def test_links_are_read_for_their_errors(self, store, a_file):
        with pytest.raises(ValueError, match="Unknown link kind"):
            store.put(a_file, links=())
        with pytest.raises(ValueError, match="Unknown link kind"):
            store.put(a_file, links=("teleport",))


def _offline(client, monkeypatch):
    """The bucket out of reach from now on: no listing, no read."""
    import botocore.exceptions

    def offline(*args, **kwargs):
        raise botocore.exceptions.EndpointConnectionError(endpoint_url="https://s3.amazonaws.com")

    for name in ("get_paginator", "get_object", "head_object"):
        monkeypatch.setattr(client, name, offline)


class TestOffline:
    def test_what_was_read_before_is_served_from_the_cache(self, work, client, a_file, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        owner = S3Store(URL, cache=work / "owner", client=client)
        _, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet", "parts": "_data/parts"})
        stored, unread = owner.put(a_file), owner.put(folder / "_data" / "parts" / "a.txt")
        store = S3Store(URL, cache=work / "cache", client=client)
        held = {name: store.get(put[name].content_hash) for name in ("rates", "parts")}
        kept = store.get(stored.content_hash)
        store_module._found_whole.clear()
        store = S3Store(URL, cache=work / "cache", client=client)  # a new process, as it were
        _offline(client, monkeypatch)
        assert {name: store.get(put[name].content_hash) for name in ("rates", "parts")} == held
        assert store.get(stored.content_hash) == kept
        assert store.incomplete(put["parts"].content_hash, 2) is None
        with pytest.raises(StoreUnreachableError, match="cannot be reached"):
            store.get(unread.content_hash)  # never read here: nothing to serve
        with pytest.raises(StoreUnreachableError):
            store.incomplete(unread.content_hash, 1, {"a.txt": 1})
        with pytest.raises(StoreUnreachableError):
            store.has(put["rates"].content_hash)


class TestHalfASnapshot:
    """Files are uploaded one by one and the record last; either half can be there without the other."""

    def test_files_without_a_record_are_no_snapshot(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/one.txt": b"one"})
        pending = store.begin("acme/rates", COMMIT, FIRST, base=folder)
        put = pending.put(folder / "_data" / "rates.parquet")
        pending.put(folder / "_data" / "one.txt")
        # Interrupted here: the files are in the bucket, and no record
        assert f"{HERE}/_data/rates.parquet" in _keys(client)
        assert not store.has(put.content_hash) and store.all_snapshot_files() == [] and list(store.hashes()) == []
        with pytest.raises(ObjectNotFoundError):
            store.get(put.content_hash)
        assert store.tidy() == []  # one being made, as far as anyone can tell, for an hour
        later = time.time() + PENDING_SECONDS + 1
        monkeypatch.setattr(s3, "time", types.SimpleNamespace(time=lambda: later, gmtime=time.gmtime, strftime=time.strftime))
        assert sorted(name for name, _ in store.tidy()) == [
            f"{HERE[len('stores/one/'):]}/_data/one.txt", f"{HERE[len('stores/one/'):]}/_data/rates.parquet",
        ]
        assert _keys(client, "stores/one/pipelines/") == []

    def test_a_record_without_all_its_files_is_said_to_be_on_its_way(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a" * 10, "_data/parts/b.txt": b"b" * 20})
        _, put = _snapshot(store, folder, {"parts": "_data/parts"})
        parts = put["parts"].content_hash
        assert store.incomplete(parts, 30) is None
        store_module._found_whole.clear()
        client.delete_object(Bucket=BUCKET, Key=f"{HERE}/_data/parts/b.txt")
        fresh = S3Store(URL, cache=work / "fresh", client=client)
        assert fresh.has(parts)  # one of its files is there
        said = fresh.incomplete(parts, 30)
        assert "does not have _data/parts/b.txt yet: it is not fully uploaded yet" in said
        with pytest.raises(StoreError, match=r"does not have _data/parts/b.txt of sha256:\w+ yet.*not fully uploaded yet"):
            fresh.get(parts)
        client.delete_object(Bucket=BUCKET, Key=f"{HERE}/_data/parts/a.txt")
        assert not fresh.has(parts)  # none of its files is there: as a store that lost it
        # Making the snapshot again puts back what is missing, where its record says
        again = store.begin("acme/rates", COMMIT, SECOND, base=folder)
        assert again.put(folder / "_data" / "parts").content_hash == parts and not again.placed
        again.discard()
        store_module._found_whole.clear()
        assert fresh.incomplete(parts, 30) is None
        assert {p.name: p.read_bytes() for p in fresh.get(parts).iterdir()} == {"a.txt": b"a" * 10, "b.txt": b"b" * 20}

    def test_a_key_written_over_is_not_on_its_way(self, store, client, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_data/rates.parquet", Body=b"rates")
        store_module._found_whole.clear()
        said = store.incomplete(put["rates"].content_hash, 7)
        assert "has 5 bytes of _data/rates.parquet where its record says 7" in said
        assert "not fully uploaded" not in said and "store verify" in said

    def test_a_snapshot_not_written_takes_what_it_uploaded(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a"})
        _snapshot(store, folder, {"parts": "_data/parts"})
        (folder / "_data" / "parts" / "b.txt").write_bytes(b"b")
        pending = store.begin("acme/rates", LATER, SECOND, base=folder)
        pending.put(folder / "_data" / "parts")
        assert any(k.startswith("stores/one/tmp/") and k.endswith(".pending") for k in _keys(client))  # a.txt, noted for gc
        pending.discard()
        assert _keys(client, "stores/one/tmp/") == []
        assert [k for k in _keys(client) if "2026-10-17" in k] == []
        assert f"{HERE}/_data/parts/a.txt" in _keys(client)


class TestClearing:
    def test_a_cleared_snapshot_keeps_what_a_later_one_uses(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a", "_data/one.txt": b"only the first"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts", "one": "_data/one.txt"})
        later, put = _snapshot(store, folder, {"parts": "_data/parts"}, commit=LATER, made_at=SECOND)
        assert store.remove_snapshot(record) is True and store.remove_snapshot(record) is False
        assert [k for k in _keys(client) if k.startswith(HERE)] == [f"{HERE}/_chartbook/CLEARED.txt", f"{HERE}/_data/parts/a.txt"]
        assert "used by later snapshots" in client.get_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/CLEARED.txt")["Body"].read().decode()
        assert store.remove_snapshot(later) is True
        # The first's folder is no other's to sweep: `store gc` clears it after, as it clears every folder
        assert [k for k in _keys(client) if k.startswith(HERE)] == [f"{HERE}/_chartbook/CLEARED.txt", f"{HERE}/_data/parts/a.txt"]
        assert store.tidy() == [(f"{HERE[len('stores/one/'):]}/_data/parts/a.txt", 1)]
        assert _keys(client, "stores/one/pipelines/") == []

    def test_what_a_snapshot_being_made_uses_is_kept(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts"})
        pending = store.begin("acme/rates", LATER, SECOND, base=folder)
        put = pending.put(folder / "_data" / "parts")  # uses a.txt, which the first keeps
        assert store.remove_snapshot(record) is True  # a gc meanwhile
        assert f"{HERE}/_data/parts/a.txt" in _keys(client)
        pending.write({"schema": "chartbook/snapshot/v2", "root": "acme/rates", "code": {"commit": LATER}, "made_at": SECOND,
                       "records": [{"id": "acme/rates:parts", "content_hash": put.content_hash, "size_bytes": 1, "stored": put.stored}]})
        assert (store.get(put.content_hash) / "a.txt").read_bytes() == b"a" and store.verify() == []

    def test_the_last_at_a_commit_takes_its_origins(self, store, client, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        record, _ = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        store.note_origin(COMMIT, "_top", "/somewhere")
        assert store.remove_snapshot(record) is True
        assert store.origins(COMMIT, "_top") == [] and _keys(client, "stores/one/origins/") == []


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
    def test_reads_work_and_writes_say_what_was_refused(self, work, client, a_file):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        owner = S3Store(URL, cache=work / "owner", client=client)
        record, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet"})
        stored = owner.put(a_file)
        reader = S3Store(URL, cache=work / "reader", client=_refusing(client))
        assert reader.has(put["rates"].content_hash) and reader.incomplete(put["rates"].content_hash, 7) is None
        assert (reader.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert (reader.get(stored.content_hash) / "rates.parquet").read_bytes() == b"unowned"
        assert sorted(reader.hashes()) == sorted([put["rates"].content_hash, stored.content_hash]) and reader.verify() == []
        (folder / "_data" / "new.parquet").write_bytes(b"new")
        pending = reader.begin("acme/rates", LATER, SECOND, base=folder)
        with pytest.raises(ReadOnlyStoreError, match=r"refused to upload .*/_data/new.parquet: AccessDenied. If this store is read-only for you"):
            pending.put(folder / "_data" / "new.parquet")
        with pytest.raises(ReadOnlyStoreError, match=r"refused to write .*/_chartbook/snapshot.json"):
            pending.write({"root": "acme/rates", "code": {"commit": LATER}, "made_at": SECOND, "records": []})
        with pytest.raises(ReadOnlyStoreError, match="refused to upload"):
            reader.put(folder / "_data" / "new.parquet")
        with pytest.raises(ReadOnlyStoreError, match="refused to write .*roots"):
            reader.add_root(work / "chartbook.lock", [stored.content_hash])
        (seen,) = reader.all_snapshot_files()
        with pytest.raises(ReadOnlyStoreError, match="refused to delete .*snapshot.json"):
            reader.remove_snapshot(seen)
        assert lock.is_read_only(ReadOnlyStoreError("x"))
        assert f"{HERE}/_chartbook/snapshot.json" in _keys(client)

    def test_the_refusal_reaches_the_command_as_one_line(self, work, client):
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
        tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "A file."}}}), encoding="utf-8", newline="\n"
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}}), encoding="utf-8", newline="\n"
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8", newline="\n")
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
        folder = Path(made.snapshot.path).parent.parent
        assert folder.parent == work / "machine-a" / "s3" / BUCKET / "stores" / "one" / "pipelines" / "acme+rates"
        assert f"stores/one/pipelines/acme+rates/{folder.name}/_data/treasury.parquet" in _keys(client)

        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        monkeypatch.chdir(forecast)
        assert data.load("rates:treasury").collect().shape == (1, 2)
        assert data.path("rates:treasury") == folder / "_data" / "treasury.parquet"
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

    def test_an_unowned_objects_keys(self, work, client, a_file):
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

    def test_planted_records(self, work, client):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        first = S3Store(URL, cache=work / "machine-a", client=client)
        written, put = _snapshot(first, folder, {"rates": "_data/rates.parquet"})
        record = json.loads(Path(written).read_text(encoding="utf-8"))
        root = "stores/one/pipelines/"
        for planted in ("../../evil/2026-10-16T010203Z_bbbbbbbbbbbb/_chartbook/snapshot.json", "acme+rates/../x/_chartbook/snapshot.json",
                        "acme+rates//2026-10-16T010203Z_bbbbbbbbbbbb/_chartbook/snapshot.json"):
            client.put_object(Bucket=BUCKET, Key=root + planted, Body=json.dumps(record).encode())
        # A record whose files lead out of its pipeline's folder is not followed
        leading = dict(record, records=[dict(record["records"][0], content_hash="sha256:" + "e" * 64, stored={
            "at": "_data", "single": True,
            "files": [{"path": "_data/x.parquet", "content_hash": "sha256:" + "e" * 64, "size_bytes": 7, "kept_in": "../../../evil"}],
        })])
        client.put_object(Bucket=BUCKET, Key=f"{root}acme+rates/2026-10-18T010203Z_bbbbbbbbbbbb/_chartbook/snapshot.json", Body=json.dumps(leading).encode())
        second = S3Store(URL, cache=work / "machine-b", client=client)
        assert [p.parent.parent.name for p in second.all_snapshot_files()] == ["2026-10-16T010203Z_bbbbbbbbbbbb", "2026-10-18T010203Z_bbbbbbbbbbbb"]
        assert not second.has("sha256:" + "e" * 64)
        assert (second.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert self._outside(work) == []

    def test_a_key_is_never_made_a_path_out_of_the_cache(self, store):
        with pytest.raises(StoreError, match="not a plain path"):
            store._local(store.prefix + "/../x.json" if store.prefix else "../x.json")


class TestWhatTheFourthReviewFound:
    @pytest.mark.skipif(os.name == "nt", reason="Windows has no file named with a colon or a backslash")
    def test_a_file_named_with_a_colon_or_a_backslash_is_read_back(self, work, client):
        folder = _pipeline(work, {"_data/daily/2024-01-01T00:00:00.csv": b"a", "_data/daily/a\\b.csv": b"b"})
        first = S3Store(URL, cache=work / "machine-a", client=client)
        _, put = _snapshot(first, folder, {"daily": "_data/daily"})
        second = S3Store(URL, cache=work / "machine-b", client=client)
        held = second.get(put["daily"].content_hash)
        assert sorted(p.name for p in held.iterdir()) == ["2024-01-01T00:00:00.csv", "a\\b.csv"]
        assert second.verify() == []
        assert first.put(folder / "_data" / "daily").content_hash == put["daily"].content_hash

    def test_an_object_of_keys_that_are_no_files_is_removed_by_gc(self, work, client, a_file):
        store = S3Store(URL, cache=work / "machine-a", client=client)
        stored = store.put(a_file)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        prefix = key[: -len("rates.parquet")]
        other = prefix.replace(stored.content_hash[7:], "f" * 64)
        client.put_object(Bucket=BUCKET, Key=other + "../x", Body=b"planted")
        client.put_object(Bucket=BUCKET, Key=prefix, Body=b"")  # a folder marker, as the S3 console makes
        planted = "sha256:" + "f" * 64
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
            Path(target).write_text("not a lockfile", encoding="utf-8", newline="\n")
        (note,) = (work / "store" / "roots").glob("*.json")
        note.write_text(json.dumps({**json.loads(note.read_text(encoding="utf-8")), "lockfile": target, "hashes": [stored.content_hash]}), encoding="utf-8", newline="\n")
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
        note.write_text(json.dumps({**json.loads(note.read_text(encoding="utf-8")), "lockfile": named, "hashes": [stored.content_hash]}), encoding="utf-8", newline="\n")
        plan = lock.plan_gc(store=store, forget_missing=True, recent_seconds=0)
        assert [str(p) for p in plan.not_read] == [str(Path(named))] and plan.forget == []
        assert stored.content_hash not in [content_hash for content_hash, _ in plan.delete]


class TestAnotherMachineWithoutTheUpstreamFolder:
    """A pipeline cloned on another machine reads what its lockfile pins from a shared store,
    with the pipeline it depends on neither there nor built (docs: "A store in a synced folder")."""

    def _machine_two(self, rates, forecast, monkeypatch):
        remove_tree(rates)
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


def _pinned_commit(forecast: Path) -> str:
    (entry,) = lock.read_lock(forecast).dependencies
    return entry["location"]["commit"]


class TestASnapshotHalfUploaded:
    """A record whose files are not all in the bucket: `pin`, `update`, `pin --frozen` and a read
    all say it is not fully uploaded yet, as they say of a half-synced folder, and making the
    snapshot again puts back what is missing."""

    @pytest.fixture
    def half(self, work, client, monkeypatch):
        """`forecast` pinned `rates`'s first snapshot of a two-file directory; a second snapshot was made."""
        store_module._plugin_store_class.cache_clear()
        monkeypatch.setenv(config.STORE_ENV_VAR, URL)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "machine-a"))
        rates, forecast = work / "rates", work / "forecast"
        parts = rates / "_data" / "parts"
        parts.mkdir(parents=True)
        forecast.mkdir()
        (rates / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"parts": {"path": "./_data/parts", "docs": "Parts."}}}), encoding="utf-8", newline="\n"
        )
        (forecast / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}}), encoding="utf-8", newline="\n"
        )
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8", newline="\n")

        def build(value: int):
            pl.DataFrame({"a": [1]}).write_parquet(parts / "part-0.parquet")
            pl.DataFrame({"a": [value]}).write_parquet(parts / "part-1.parquet")
            (rates / "notes.txt").write_text(f"{value}\n", encoding="utf-8", newline="\n")
            _commit(work)
            return snapshot.make(rates).snapshot

        first = build(2)
        assert lock.pin(forecast).problems == []
        second = build(3)
        return rates, forecast, first, second

    def _lose(self, client, taken) -> str:
        """Take the second snapshot's own part-1 away, as a copy into the bucket that has not finished leaves it."""
        folder = Path(taken.path).parent.parent.name
        (key,) = [k for k in _keys(client) if f"/{folder}/" in k and k.endswith("/part-1.parquet")]
        client.delete_object(Bucket=BUCKET, Key=key)
        store_module._found_whole.clear()  # this process may have found it whole before
        return key

    def test_update_does_not_move_to_it_and_says_what_to_do(self, half, client):
        rates, forecast, first, second = half
        self._lose(client, second)
        report = lock.update(forecast)
        (problem,) = report.problems
        assert problem.status == "unsynced" and problem.asset == "rates:parts"
        assert "does not have _data/parts/part-1.parquet yet: it is not fully uploaded yet" in problem.detail
        assert "making the snapshot again puts it back" in problem.detail
        assert _pinned_commit(forecast) == first.commit  # nothing moved
        assert snapshot.make(rates).made is False  # the same snapshot, its file put back
        store_module._found_whole.clear()
        assert lock.update(forecast).problems == []
        assert _pinned_commit(forecast) == second.commit

    def test_pin_frozen_and_a_read_say_it_too(self, half, client, monkeypatch):
        rates, forecast, first, second = half
        assert lock.update(forecast).problems == []
        self._lose(client, second)
        (problem,) = lock.verify(forecast).problems
        assert "does not have _data/parts/part-1.parquet yet: it is not fully uploaded yet" in problem.message
        assert {e.status for e in lock.pin(forecast).problems} == {"unsynced"}
        frozen = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(forecast)])
        assert frozen.exit_code == 1 and "not fully uploaded yet" in frozen.output
        updated = CliRunner().invoke(main, ["update", "--project-dir", str(forecast)])
        assert updated.exit_code == 1 and "not fully synced: rates:parts" in updated.output
        monkeypatch.chdir(forecast)
        with pytest.raises((AssetNotPinnedError, StoreError), match="not fully uploaded yet"):
            data.load("rates:parts").collect()
        snapshot.make(rates)
        store_module._found_whole.clear()
        assert lock.verify(forecast).problems == []
        assert data.load("rates:parts").collect().height == 2

    def test_a_first_read_says_it_and_pins_nothing(self, half, client, monkeypatch):
        rates, forecast, first, second = half
        self._lose(client, second)
        (forecast / lock.LOCK_FILE).unlink()  # a fresh clone of it, before any pin
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="cannot be pinned yet: .*not fully uploaded yet") as raised:
            data.load("rates:parts")
        assert raised.value.reason == "not_synced"
        assert not (forecast / lock.LOCK_FILE).exists()


class TestWhatTheListingTells:
    """`incomplete` of an object no pipeline owns, by the keys under it and their sizes, as the folder store judges its folder."""

    def test_a_key_not_there_yet(self, store, client, a_file, work):
        stored = store.put(a_file)
        assert store.incomplete(stored.content_hash, 7, {"rates.parquet": 7}) is None
        other = work / "other.parquet"
        other.write_bytes(b"unowned")
        assert store.put(other).created is False  # the same bytes under another name
        (key,) = [k for k in _keys(client) if k.endswith("/rates.parquet")]
        client.delete_object(Bucket=BUCKET, Key=key)
        store_module._found_whole.clear()
        # This pin's name is on its way; the other name, whole, is another pin's business
        assert "does not have rates.parquet yet: it is not fully uploaded yet" in store.incomplete(stored.content_hash, 7, {"rates.parquet": 7})
        assert store.incomplete(stored.content_hash, 7, {"other.parquet": 7}) is None
        assert store.incomplete(stored.content_hash, 7, None) is None  # a glob's record: the sizes summed

    def test_a_directorys_keys(self, store, client, work):
        folder = work / "_models" / "m"
        folder.mkdir(parents=True)
        (folder / "a.bin").write_bytes(b"a" * 10)
        (folder / "b.bin").write_bytes(b"b" * 20)
        stored = store.put(folder)
        files = {"a.bin": 10, "b.bin": 20}
        assert store.incomplete(stored.content_hash, 30, files, every=True) is None
        store_module._found_whole.clear()
        (key,) = [k for k in _keys(client) if k.endswith("/b.bin")]
        client.delete_object(Bucket=BUCKET, Key=key)
        assert "does not have b.bin yet: it is not fully uploaded yet" in store.incomplete(stored.content_hash, 30, files, every=True)
        assert "has 10 bytes where its record says 30: it is not fully uploaded yet" in store.incomplete(stored.content_hash, 30, None)
        # A key written over holds other bytes: no upload mends that
        client.put_object(Bucket=BUCKET, Key=key, Body=b"b" * 5)
        said = store.incomplete(stored.content_hash, 30, files, every=True)
        assert "has 5 bytes of b.bin where its record says 20" in said and "not fully uploaded" not in said and "store verify" in said
        client.put_object(Bucket=BUCKET, Key=key, Body=b"b" * 20)
        # A key the record does not list, which a reader of the folder would read
        client.put_object(Bucket=BUCKET, Key=key.replace("b.bin", "b (1).bin"), Body=b"b" * 20)
        said = store.incomplete(stored.content_hash, 30, files, every=True)
        assert "holds b (1).bin, which its record does not list" in said and "remove it from the bucket" in said
        assert "has 50 bytes where its record says 30" in store.incomplete(stored.content_hash, 30, None)
        assert store.incomplete(stored.content_hash, 30, files) is None  # not every: a reader opens the listed files

    def test_what_is_not_judged(self, store, a_file):
        stored = store.put(a_file)
        assert store.incomplete(stored.content_hash, None, {"rates.parquet": 7}) is None  # a record with no size
        assert store.incomplete("sha256:" + "0" * 64, 7, {"x": 7}) is None  # not there at all, which `has` says

    def test_an_object_gone_while_planning_is_passed_over(self, store, a_file, monkeypatch):
        """Two gc at once: an object listed, then removed before its age is asked."""
        stored = store.put(a_file)
        phantom = "sha256:" + "f" * 64
        monkeypatch.setattr(store, "hashes", lambda: iter([stored.content_hash, phantom]))
        plan = lock.plan_gc(store, recent_seconds=0)
        assert [h for h, _ in plan.delete] == [stored.content_hash] and plan.recent == []


class TestWhatAnObjectLacks:
    def test_a_key_the_object_lacks(self, store, work, a_file):
        stored = store.put(a_file)
        assert not store.lacks(stored.content_hash, ["rates.parquet"])
        assert store.lacks(stored.content_hash, ["twin.parquet"])
        assert not store.lacks("sha256:" + "0" * 64, ["rates.parquet"])  # no object: nothing to add a name to
        folder = _pipeline(work, {"_data/x.parquet": b"x"})
        _, put = _snapshot(store, folder, {"x": "_data/x.parquet"})
        assert not store.lacks(put["x"].content_hash, ["twin.parquet"])  # a record names each of its files
