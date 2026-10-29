"""The S3 store: a bucket laid out as a folder store, read through a cache on this machine.

`tests/test_store_contract.py` has what every store must do; this file
has what is particular to a remote one: the URL, the keys, the cache and
the check of what was downloaded, half a snapshot in the bucket, two
machines making snapshots in it at once, what gc may remove, a store that
is read-only or cannot be reached, and what a question costs.
"""

import json
import os
import sys
import time
import types
import unicodedata
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
    PENDING_FOLDER_SECONDS,
    PENDING_SECONDS,
    FolderStore,
    ObjectNotFoundError,
    ReadOnlyStoreError,
    StoreError,
    StoreUnreachableError,
    TidyError,
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
FOLDER = "2026-10-16T010203Z_bbbbbbbbbbbb"
HERE = f"stores/one/pipelines/acme+rates/{FOLDER}"
NAME = HERE[len("stores/one/"):]  # its name in the store


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


def _behind_its_back(*stores) -> None:
    """The bucket changed by another hand: what these stores listed a moment ago, and found whole, is old."""
    for store in stores:
        store._forget()
    store_module._found_whole.clear()


def _later(monkeypatch, seconds: float) -> None:
    """The S3 store's clock, *seconds* on from now."""
    then = time.time() + seconds
    monkeypatch.setattr(s3, "time", types.SimpleNamespace(time=lambda: then, monotonic=time.monotonic, gmtime=time.gmtime, strftime=time.strftime))


def _pipeline(work: Path, files: dict, name: str = "rates") -> Path:
    """A pipeline's folder holding these files, by their paths in it."""
    folder = work / name
    for path, body in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(body)
    return folder


def _record(pending, put: dict) -> dict:
    """The record of a snapshot being made, of what was put in it, each asset by its name."""
    return {
        "schema": "chartbook/snapshot/v2",
        "root": pending.pipeline,
        "code": {"commit": pending.commit},
        "made_at": pending.made_at,
        "records": [
            {"id": f"{pending.pipeline}:{name}", "content_hash": stored.content_hash, "size_bytes": stored.size_bytes, "stored": stored.stored}
            for name, stored in sorted(put.items())
        ],
    }


def _snapshot(store, folder: Path, assets: dict, commit: str = COMMIT, made_at: str = FIRST, made_by: str = "snapshot", pipeline: str = "acme/rates"):
    """A snapshot of a pipeline: each asset by its name and its path in the pipeline's folder. Its record, and what was put."""
    pending = store.begin(pipeline, commit, made_at, base=folder, made_by=made_by)
    put = {name: pending.put(folder / path) for name, path in assets.items()}
    return pending.write(_record(pending, put)), put


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

    def test_two_services_with_one_bucket_name_have_a_cache_each(self, work, client, monkeypatch):
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "c"))
        caches = [
            S3Store(url, client=client).cache
            for url in ("s3://chartbook-test/p", "s3://chartbook-test/p?endpoint=http://localhost:9000", "s3://chartbook-test/p?endpoint=https://minio.example.org")
        ]
        assert caches[0] == work / "c" / "s3" / "chartbook-test" / "p"
        assert len(set(caches)) == 3 and all(cache.parent.name.startswith("chartbook-test~") for cache in caches[1:])


class TestTheBucketIsAFolderStore:
    """The keys are the folder store's paths, so a synced folder is the same store."""

    def test_the_layout(self, store, client, work, a_file):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/parts/a.txt": b"a"})
        _snapshot(store, folder, {"rates": "_data/rates.parquet", "parts": "_data/parts"})
        unowned = store.put(a_file)
        store.add_root(Path("/somewhere/chartbook.lock"), [unowned.content_hash])
        store.note_origin(COMMIT, "_top", "/somewhere")
        # The claim of the folder and the note of the snapshot being made are gone with the record written
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
        content_hash = put["rates"].content_hash
        second = S3Store(URL, cache=work / "machine-b", client=client)
        downloads = []
        original = second._download
        monkeypatch.setattr(second, "_download", lambda key, target, content_hash=None: (downloads.append((key, content_hash)), original(key, target, content_hash))[1])
        held = second.get(content_hash)
        assert held == second.views / content_hash[7:]
        assert (held / "rates.parquet").read_bytes() == b"rates-1" and not os.access(held / "rates.parquet", os.W_OK)
        # Kept in the cache by its hash, against which it was checked as it came
        checked = second.cache / "files" / content_hash[7:9] / content_hash[9:]
        assert checked.read_bytes() == b"rates-1" and not os.access(checked, os.W_OK)
        assert second.get(content_hash) == held
        assert downloads == [(f"{HERE}/_data/rates.parquet", content_hash)]  # once, against its hash

    def test_the_machine_that_made_it_downloads_nothing(self, store, work, monkeypatch):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        _, put = _snapshot(store, folder, {"parts": "_data/parts"})
        monkeypatch.setattr(store, "_download", lambda *a, **k: pytest.fail("downloaded what it put"))
        gathered = store.get(put["parts"].content_hash)
        assert gathered == store.views / put["parts"].content_hash[7:]
        assert {p.name: p.read_bytes() for p in gathered.iterdir()} == {"a.txt": b"a", "b.txt": b"b"}

    def test_a_record_is_read_in_one_request(self, work, client, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _snapshot(S3Store(URL, cache=work / "a", client=client), folder, {"rates": "_data/rates.parquet"})
        reader = S3Store(URL, cache=work / "b", client=client)
        asked = []
        for name in ("get_object", "head_object", "download_file"):
            original = getattr(client, name)
            monkeypatch.setattr(client, name, lambda *a, _name=name, _original=original, **k: (asked.append(_name), _original(*a, **k))[1])
        reader.all_snapshot_files()
        assert asked == ["get_object", "get_object"]  # the marker, and the record
        asked.clear()
        reader.all_snapshot_files()
        assert asked == []  # the cache's copy, at the bucket's time and size

    def test_a_file_that_is_not_what_its_record_says_is_not_kept(self, work, client):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        owner = S3Store(URL, cache=work / "machine-a", client=client)
        _, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet"})
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_data/rates.parquet", Body=b"rates-2")  # the same size, other bytes
        fresh = S3Store(URL, cache=work / "machine-b", client=client)
        with pytest.raises(StoreError, match=r"_data/rates.parquet of sha256:.* is not what its snapshot's record says"):
            fresh.get(put["rates"].content_hash)
        assert not (fresh.cache / "files").exists() or not any((fresh.cache / "files").rglob("*.*"))
        (problem,) = fresh.verify()
        assert problem.content_hash == put["rates"].content_hash and "no longer what its record says" in problem.message
        # The machine that put it has its own copy, checked as it went; verify downloads again, and so finds it
        assert (owner.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        (problem,) = owner.verify()
        assert problem.content_hash == put["rates"].content_hash
        assert (owner.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert not any((owner.cache / "tmp").iterdir())

    def test_a_file_cached_is_read_only_for_the_hash_it_was_checked_against(self, work, client):
        """A snapshot's folder cleared and named again holds other bytes at the same path, of the same size."""
        owner = S3Store(URL, cache=work / "owner", client=client)
        reader = S3Store(URL, cache=work / "reader", client=client)
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        record, put = _snapshot(owner, folder, {"rates": "_data/rates.parquet"})
        assert (reader.get(put["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-1"
        assert owner.remove_snapshot(record) is True and owner.tidy()
        assert _keys(client, HERE) == []
        (folder / "_data" / "rates.parquet").write_bytes(b"rates-2")
        elsewhere = S3Store(URL, cache=work / "elsewhere", client=client)  # a process that never claimed that name
        _, again = _snapshot(elsewhere, folder, {"rates": "_data/rates.parquet"})
        assert again["rates"].content_hash != put["rates"].content_hash and _keys(client, HERE)  # the same folder, named again
        _behind_its_back(reader)
        assert (reader.get(again["rates"].content_hash) / "rates.parquet").read_bytes() == b"rates-2"
        with pytest.raises(ObjectNotFoundError):
            reader.get(put["rates"].content_hash)

    def test_the_next_copy_is_read_when_one_is_not_what_its_record_says(self, work, client):
        owner = S3Store(URL, cache=work / "owner", client=client)
        rates = _pipeline(work, {"_data/x.parquet": b"same"})
        other = _pipeline(work, {"_data/x.parquet": b"same"}, name="other")
        _, put = _snapshot(owner, rates, {"x": "_data/x.parquet"})
        _snapshot(owner, other, {"x": "_data/x.parquet"}, made_at=SECOND, pipeline="acme/other")
        content_hash = put["x"].content_hash
        assert [name for name, _ in owner.files_of(content_hash)] == [
            "pipelines/acme+other/2026-10-17T010203Z_bbbbbbbbbbbb/_data/x.parquet", f"{NAME}/_data/x.parquet",
        ]  # every copy any record names
        # The newer copy is written over; the reader passes over it to the other
        client.put_object(Bucket=BUCKET, Key="stores/one/pipelines/acme+other/2026-10-17T010203Z_bbbbbbbbbbbb/_data/x.parquet", Body=b"evil")
        reader = S3Store(URL, cache=work / "reader", client=client)
        assert (reader.get(content_hash) / "x.parquet").read_bytes() == b"same"
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_data/x.parquet", Body=b"evil")
        fresh = S3Store(URL, cache=work / "fresh", client=client)
        with pytest.raises(StoreError, match="is not what its snapshot's record says"):
            fresh.get(content_hash)

    def test_a_copy_whose_sizes_are_not_its_records_is_passed_over(self, work, client):
        owner = S3Store(URL, cache=work / "owner", client=client)
        _snapshot(owner, _pipeline(work, {"_data/x.parquet": b"same"}), {"x": "_data/x.parquet"})
        _, put = _snapshot(owner, _pipeline(work, {"_data/x.parquet": b"same"}, name="other"), {"x": "_data/x.parquet"}, made_at=SECOND, pipeline="acme/other")
        client.put_object(Bucket=BUCKET, Key="stores/one/pipelines/acme+other/2026-10-17T010203Z_bbbbbbbbbbbb/_data/x.parquet", Body=b"sam")
        reader = S3Store(URL, cache=work / "reader", client=client)
        assert (reader.get(put["x"].content_hash, pipeline="acme/other") / "x.parquet").read_bytes() == b"same"

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
        _behind_its_back(second)
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
        _behind_its_back(second)
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
        _behind_its_back(store)
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
        held = store.get(put["rates"].content_hash)
        stored = store.put(a_file)
        cached = store.get(stored.content_hash)
        assert store.delete(put["rates"].content_hash) is True and store.delete(stored.content_hash) is True
        assert not held.exists() and not cached.exists() and not any((store.cache / "files").rglob("*.*"))
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

    for name in ("get_paginator", "get_object", "head_object", "download_file"):
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
        assert store.has(put["parts"].content_hash) and store.has(stored.content_hash)
        assert store.incomplete(put["parts"].content_hash, 2) is None
        with pytest.raises(StoreUnreachableError, match="cannot be reached"):
            store.get(unread.content_hash)  # never read here: nothing to serve
        with pytest.raises(StoreUnreachableError):
            store.has(unread.content_hash)  # nor to say it is there
        with pytest.raises(StoreUnreachableError):
            store.incomplete(unread.content_hash, 1, {"a.txt": 1})


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
        assert store.tidy() == []  # being made, as its note says
        _later(monkeypatch, PENDING_SECONDS + 1)
        assert store.tidy() == []  # its note too old to say so, but a day is given to one uploaded slowly
        _later(monkeypatch, PENDING_FOLDER_SECONDS + 1)
        assert sorted(name for name, _ in store.tidy()) == [
            f"{NAME}/_chartbook/CLAIMED.txt", f"{NAME}/_data/one.txt", f"{NAME}/_data/rates.parquet",
        ]
        assert _keys(client, "stores/one/pipelines/") == []

    def test_a_record_without_all_its_files_is_said_to_be_on_its_way(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a" * 10, "_data/parts/b.txt": b"b" * 20})
        _, put = _snapshot(store, folder, {"parts": "_data/parts"})
        parts = put["parts"].content_hash
        assert store.incomplete(parts, 30) is None
        client.delete_object(Bucket=BUCKET, Key=f"{HERE}/_data/parts/b.txt")
        _behind_its_back(store)
        fresh = S3Store(URL, cache=work / "fresh", client=client)
        assert fresh.has(parts)  # one of its files is there
        said = fresh.incomplete(parts, 30)
        assert "does not have _data/parts/b.txt yet: it is not fully uploaded yet" in said
        with pytest.raises(StoreError, match=r"does not have _data/parts/b.txt yet of sha256:\w+.*not fully uploaded yet"):
            fresh.get(parts)
        client.delete_object(Bucket=BUCKET, Key=f"{HERE}/_data/parts/a.txt")
        _behind_its_back(fresh)
        assert not fresh.has(parts)  # none of its files is there: as a store that lost it
        # Making the snapshot again puts back what is missing, where its record says
        again = store.begin("acme/rates", COMMIT, SECOND, base=folder)
        assert again.put(folder / "_data" / "parts").content_hash == parts and not again.placed
        again.discard()
        _behind_its_back(fresh)
        assert fresh.incomplete(parts, 30) is None
        assert {p.name: p.read_bytes() for p in fresh.get(parts).iterdir()} == {"a.txt": b"a" * 10, "b.txt": b"b" * 20}

    def test_a_key_written_over_is_not_on_its_way(self, store, client, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_data/rates.parquet", Body=b"rates")
        _behind_its_back(store)
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


class TestTwoMachinesAtOnce:
    """A bucket has no folder made whole or not at all: a snapshot's folder and its record are each written only if nothing is there."""

    def test_two_never_take_one_folder(self, work, client, monkeypatch):
        folder = _pipeline(work, {"_data/a.txt": b"a", "_data/b.txt": b"b"})
        one, two = S3Store(URL, cache=work / "one", client=client), S3Store(URL, cache=work / "two", client=client)
        first = one.begin("acme/rates", COMMIT, FIRST, base=folder)
        a = first.put(folder / "_data" / "a.txt")
        second = two.begin("acme/rates", COMMIT, FIRST, base=folder)
        monkeypatch.setattr(second, "_taken", lambda: set())  # it listed the folders before the first claimed its own
        b = second.put(folder / "_data" / "b.txt")
        assert (first.name, second.name) == (FOLDER, "2026-10-16T010204Z_bbbbbbbbbbbb")
        first.write(_record(first, {"a": a}))
        second.write(_record(second, {"b": b}))
        _behind_its_back(one)
        assert [Path(path).parent.parent.name for path in one.all_snapshot_files()] == [FOLDER, "2026-10-16T010204Z_bbbbbbbbbbbb"]
        assert one.verify() == [] and _keys(client, "stores/one/tmp/") == []

    def test_a_record_with_no_files_of_its_own_takes_the_next_second_too(self, work, client, monkeypatch):
        store = S3Store(URL, cache=work / "one", client=client)
        document = {"schema": "chartbook/snapshot/v2", "root": "acme/rates", "code": {"commit": COMMIT}, "made_at": FIRST, "records": []}
        written = store.write_snapshot(COMMIT, "_top", "20261016T010203Z", document)
        monkeypatch.setattr(s3._S3Pending, "_taken", lambda self: set())
        again = store.write_snapshot(COMMIT, "_top", "20261016T010203Z", document)
        assert (Path(written).parent.parent.name, Path(again).parent.parent.name) == (FOLDER, "2026-10-16T010204Z_bbbbbbbbbbbb")

    def test_a_record_is_never_written_over(self, store, client, work):
        folder = _pipeline(work, {"_data/a.txt": b"a"})
        pending = store.begin("acme/rates", COMMIT, FIRST, base=folder)
        put = pending.put(folder / "_data" / "a.txt")
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/snapshot.json", Body=b'{"by": "another"}')
        with pytest.raises(StoreError, match="has a record already, though this snapshot claimed the folder"):
            pending.write(_record(pending, {"a": put}))
        assert client.get_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/snapshot.json")["Body"].read() == b'{"by": "another"}'


class TestASnapshotBeingMade:
    """What `store gc` keeps of a snapshot being made, and what the snapshot does about a gc meanwhile."""

    def test_its_folder_is_noted_before_it_is_claimed(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/a.txt": b"a"})
        written = []
        for name in ("_write", "_put_new"):
            original = getattr(store, name)
            monkeypatch.setattr(store, name, lambda key, body, _original=original: (written.append(key), _original(key, body))[1])
        upload = store._upload
        monkeypatch.setattr(store, "_upload", lambda file, key: (written.append(key), upload(file, key))[1])
        pending = store.begin("acme/rates", COMMIT, FIRST, base=folder)
        pending.put(folder / "_data" / "a.txt")
        (note,) = _keys(client, "stores/one/tmp/")
        assert client.get_object(Bucket=BUCKET, Key=note)["Body"].read().decode() == f"folder {NAME}\n"
        assert [key.rpartition("/")[2] for key in written[-3:]] == [note.rpartition("/")[2], "CLAIMED.txt", "a.txt"]

    def test_a_folder_a_note_names_is_kept_and_one_given_up_goes(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/a.txt": b"a"})
        pending = store.begin("acme/rates", COMMIT, FIRST, base=folder)
        pending.put(folder / "_data" / "a.txt")
        monkeypatch.setattr(s3, "PENDING_FOLDER_SECONDS", 0)  # as if a day had gone by with nothing written there
        assert store.tidy() == []  # its note keeps it
        pending._drop_note()  # the machine making it gave up
        assert sorted(name for name, _ in store.tidy()) == [f"{NAME}/_chartbook/CLAIMED.txt", f"{NAME}/_data/a.txt"]

    def test_a_slow_one_writes_its_note_again(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/a.txt": b"a", "_data/b.txt": b"b"})
        pending = store.begin("acme/rates", COMMIT, FIRST, base=folder)
        pending.put(folder / "_data" / "a.txt")
        notes = []
        original = pending._note_line
        monkeypatch.setattr(pending, "_note_line", lambda *lines: (notes.append(lines), original(*lines))[1])
        pending.put(folder / "_data" / "b.txt")
        assert notes == []  # written a moment ago
        monkeypatch.setattr(s3, "ALIVE_SECONDS", 0)
        pending.put(folder / "_data" / "a.txt")
        assert notes  # written again, so that gc sees it is still going

    def test_gc_reads_the_notes_again_before_it_removes(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts"})
        pending = store.begin("acme/rates", LATER, SECOND, base=folder)
        put = pending.put(folder / "_data" / "parts")  # uses a.txt where the first keeps it
        assert put.stored["files"][0]["kept_in"] == FOLDER
        assert store.remove_snapshot(record) is True
        original, seen = store._notes, []
        # Read once before the snapshot being made noted a.txt, and once after
        monkeypatch.setattr(store, "_notes", lambda: (seen.append(1), (set(), set()) if len(seen) == 1 else original())[1])
        assert store.tidy() == [] and len(seen) == 2
        assert f"{HERE}/_data/parts/a.txt" in _keys(client)
        pending.write(_record(pending, {"parts": put}))
        assert (store.get(put.content_hash) / "a.txt").read_bytes() == b"a" and store.verify() == []

    def test_a_file_whose_record_went_is_not_taken(self, store, client, work):
        """Found by a review: a snapshot took a file of an earlier one whose record a gc had just cleared, and the gc then removed it."""
        folder = _pipeline(work, {"_data/parts/a.txt": b"a"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts"})
        pending = store.begin("acme/rates", LATER, SECOND, base=folder)
        pending._kept_files()  # what it saw before
        assert store.remove_snapshot(record) is True  # a gc: the record goes first, its files after
        put = pending.put(folder / "_data" / "parts")
        assert put.stored["files"][0]["kept_in"] == pending.name != FOLDER  # uploaded into its own folder
        pending.write(_record(pending, {"parts": put}))
        assert sorted(name for name, _ in store.tidy()) == [f"{NAME}/_data/parts/a.txt"]
        assert (store.get(put.content_hash) / "a.txt").read_bytes() == b"a" and store.verify() == []

    def test_what_it_took_and_a_gc_removed_meanwhile_is_put_back(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts"})
        pending = store.begin("acme/rates", LATER, SECOND, base=folder)
        put = pending.put(folder / "_data" / "parts")
        # A gc that did not see the note: the record, then the file
        store.remove_snapshot(record)
        client.delete_object(Bucket=BUCKET, Key=f"{HERE}/_data/parts/a.txt")
        _behind_its_back(store)
        pending.write(_record(pending, {"parts": put}))
        assert f"{HERE}/_data/parts/a.txt" in _keys(client)
        _behind_its_back(store)
        assert (store.get(put.content_hash) / "a.txt").read_bytes() == b"a" and store.verify() == []


class TestWhatGcRemoves:
    def test_a_cleared_snapshot_keeps_what_a_later_one_uses(self, store, client, work):
        folder = _pipeline(work, {"_data/parts/a.txt": b"a", "_data/one.txt": b"only the first"})
        record, _ = _snapshot(store, folder, {"parts": "_data/parts", "one": "_data/one.txt"})
        later, put = _snapshot(store, folder, {"parts": "_data/parts"}, commit=LATER, made_at=SECOND)
        assert store.remove_snapshot(record) is True and store.remove_snapshot(record) is False
        assert "used by later snapshots" in client.get_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/CLEARED.txt")["Body"].read().decode()
        assert store.tidy(dry_run=True) == [(f"{NAME}/_data/one.txt", 14)] and f"{HERE}/_data/one.txt" in _keys(client)
        assert store.tidy() == [(f"{NAME}/_data/one.txt", 14)]
        assert [k for k in _keys(client) if k.startswith(HERE)] == [f"{HERE}/_chartbook/CLEARED.txt", f"{HERE}/_data/parts/a.txt"]
        assert store.remove_snapshot(later) is True
        assert sorted(name for name, _ in store.tidy(keep=[f"{NAME}/_data/parts/a.txt"])) == []  # spared for being new
        assert len(store.tidy()) == 1
        assert _keys(client, "stores/one/pipelines/") == []

    def test_a_refusal_in_the_answer_leaves_the_record_as_it_was(self, store, client, work, monkeypatch):
        """Found by a review: a refused delete comes in the answer, not as an error, and CLEARED.txt was written beside the record."""
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        record, _ = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        monkeypatch.setattr(client, "delete_objects", lambda **kwargs: {
            "Errors": [{"Key": item["Key"], "Code": "AccessDenied", "Message": "Access Denied"} for item in kwargs["Delete"]["Objects"]]
        })
        with pytest.raises(ReadOnlyStoreError, match="refused to delete .*snapshot.json: AccessDenied"):
            store.remove_snapshot(record)
        assert [k for k in _keys(client) if k.startswith(HERE)] == [f"{HERE}/_chartbook/snapshot.json", f"{HERE}/_data/rates.parquet"]

    def test_what_it_could_not_remove_is_said(self, store, client, work, monkeypatch):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        record, _ = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        store.remove_snapshot(record)
        monkeypatch.setattr(client, "delete_objects", lambda **kwargs: {
            "Errors": [{"Key": item["Key"], "Code": "AccessDenied", "Message": "Access Denied"} for item in kwargs["Delete"]["Objects"]]
        })
        with pytest.raises(TidyError, match=r"Cannot remove .*_data/rates.parquet, which no snapshot uses: AccessDenied") as raised:
            store.tidy()
        assert raised.value.removed == [] and [name for name, _ in raised.value.failed] == [f"{NAME}/_data/rates.parquet"]

    def test_a_record_in_another_pipelines_folder_or_commits_is_unreadable_and_stops_gc_there(self, store, client, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        record, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        body = Path(record).read_bytes()
        for planted in ("acme+other/2026-10-16T010203Z_bbbbbbbbbbbb", "acme+rates/2026-10-18T010203Z_cccccccccccc"):
            client.put_object(Bucket=BUCKET, Key=f"stores/one/pipelines/{planted}/_chartbook/snapshot.json", Body=body)
            client.put_object(Bucket=BUCKET, Key=f"stores/one/pipelines/{planted}/_data/stray.parquet", Body=b"x")
        store.remove_snapshot(record)
        _behind_its_back(store)
        found = {Path(path).parent.parent.name: snapshot.read for path in store.all_snapshot_files()}
        assert set(found) == {"2026-10-16T010203Z_bbbbbbbbbbbb", "2026-10-18T010203Z_cccccccccccc"}
        assert not store.has(put["rates"].content_hash)  # neither is read as a record of it
        with pytest.raises(TidyError, match="a record there cannot be read"):
            store.tidy()
        assert f"{HERE}/_data/rates.parquet" in _keys(client) and "stores/one/pipelines/acme+other/2026-10-16T010203Z_bbbbbbbbbbbb/_data/stray.parquet" in _keys(client)

    def test_a_record_of_names_this_machine_does_not_follow_stops_gc_there(self, store, client, work):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1", "_data/x.parquet": b"x"})
        record, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        cleared, _ = _snapshot(store, folder, {"x": "_data/x.parquet"}, commit=LATER, made_at=SECOND)
        document = json.loads(Path(record).read_text(encoding="utf-8"))
        document["records"][0]["stored"]["files"][0]["kept_as"] = "_data//rates.parquet"  # no plain path here
        client.put_object(Bucket=BUCKET, Key=f"{HERE}/_chartbook/snapshot.json", Body=json.dumps(document).encode())
        store.remove_snapshot(cleared)
        _behind_its_back(store)
        with pytest.raises(TidyError, match="names files this machine does not follow"):
            store.tidy()
        assert "stores/one/pipelines/acme+rates/2026-10-17T010203Z_cccccccccccc/_data/x.parquet" in _keys(client)

    def test_a_name_in_another_form_is_the_file_its_record_names(self, store, client, work):
        """A sync from macOS may bring a name in Unicode's other form: gc does not take it for a file no record names."""
        folder = _pipeline(work, {"_data/caf\u00e9.txt": b"cafe"})
        _, put = _snapshot(store, folder, {"cafe": "_data/caf\u00e9.txt"})
        key = f"{HERE}/_data/caf\u00e9.txt"
        other = unicodedata.normalize("NFD", key)
        client.copy_object(Bucket=BUCKET, Key=other, CopySource={"Bucket": BUCKET, "Key": key})
        client.delete_object(Bucket=BUCKET, Key=key)
        _behind_its_back(store)
        assert store.tidy() == [] and other in _keys(client)

    def test_gc_removes_by_its_hash_only_an_object_no_pipeline_owns(self, store, client, work, a_file):
        folder = _pipeline(work, {"_data/rates.parquet": b"rates-1"})
        _, put = _snapshot(store, folder, {"rates": "_data/rates.parquet"})
        stored = store.put(a_file)
        assert store.delete_unowned(put["rates"].content_hash) is False and f"{HERE}/_data/rates.parquet" in _keys(client)
        assert store.delete_unowned(stored.content_hash) is True and store.delete_unowned(stored.content_hash) is False
        assert _keys(client, "stores/one/pipelines/+unowned/") == []


class TestWhatAQuestionCosts:
    def _listed(self, store, monkeypatch) -> list:
        listed = []
        original = store._list
        monkeypatch.setattr(store, "_list", lambda prefix, delimiter=None: (listed.append(prefix), original(prefix, delimiter))[1])
        return listed

    def test_a_read_is_one_listing(self, work, client, monkeypatch):
        _, put = _snapshot(S3Store(URL, cache=work / "a", client=client), _pipeline(work, {"_data/parts/a.txt": b"a"}), {"parts": "_data/parts"})
        store = S3Store(URL, cache=work / "b", client=client)
        listed = self._listed(store, monkeypatch)
        content_hash = put["parts"].content_hash
        assert store.has(content_hash) and store.incomplete(content_hash, 1) is None and store.get(content_hash)
        assert listed == ["stores/one/pipelines/"]

    def test_a_pipeline_named_is_its_folder_listed(self, work, client, monkeypatch):
        owner = S3Store(URL, cache=work / "a", client=client)
        _, put = _snapshot(owner, _pipeline(work, {"_data/x.parquet": b"x"}), {"x": "_data/x.parquet"})
        _snapshot(owner, _pipeline(work, {"_data/y.parquet": b"y"}, name="other"), {"y": "_data/y.parquet"}, pipeline="acme/other")
        store = S3Store(URL, cache=work / "b", client=client)
        listed = self._listed(store, monkeypatch)
        assert store.has(put["x"].content_hash, pipeline="acme/rates") and store.get(put["x"].content_hash, pipeline="acme/rates")
        assert listed == ["stores/one/pipelines/acme+rates/"]
        assert store.has(put["x"].content_hash, pipeline="acme/other")  # not in that one's folder: then every pipeline's
        assert listed[1:] == ["stores/one/pipelines/acme+other/", "stores/one/pipelines/"]

    def test_within_reading_one_listing_answers_all_but_what_it_writes(self, store, work, a_file, monkeypatch):
        _, put = _snapshot(store, _pipeline(work, {"_data/x.parquet": b"x"}), {"x": "_data/x.parquet"})
        listed = self._listed(store, monkeypatch)
        with store.reading():
            time.sleep(s3.LISTING_SECONDS)
            content_hash = put["x"].content_hash
            assert store.has(content_hash) and store.files_of(content_hash) and store.size_of(content_hash) == 1
            assert list(store.hashes()) == [content_hash] and store.age_of(content_hash) >= 0
            assert listed == ["stores/one/pipelines/"]
            stored = store.put(a_file)  # a write of its own: listed again after
            assert store.has(stored.content_hash) and listed.count("stores/one/pipelines/") == 2

    def test_a_key_too_big_to_copy_at_once_is_copied_in_parts(self, store, client, a_file, monkeypatch):
        stored = store.put(a_file)
        (key,) = [k for k in _keys(client) if k.endswith("rates.parquet")]
        copied = []
        monkeypatch.setattr(client, "copy_object", lambda **kwargs: copied.append(("copy_object", kwargs["Key"])))
        monkeypatch.setattr(client, "copy", lambda source, bucket, key, **kwargs: copied.append(("copy", key)))
        store._touch(key, s3.COPY_LIMIT + 1)
        store._touch(key, 7)
        assert copied == [("copy", key), ("copy_object", key)]
        other = a_file.with_name("other.parquet")
        other.write_bytes(b"unowned")
        store.put(other)
        copied.clear()
        store.put(a_file)  # the bytes the bucket has, under both names: one key written again
        assert len(copied) == 1 and stored.created


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
        with pytest.raises(ReadOnlyStoreError, match=r"refused to write .*/tmp/\w+\.pending: AccessDenied. If this store is read-only for you"):
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
        assert f"{HERE}/_chartbook/snapshot.json" in _keys(client) and f"{HERE}/_chartbook/CLEARED.txt" not in _keys(client)

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
        content_hash = made.snapshot.assets["treasury"]["content_hash"]
        folder = Path(made.snapshot.path).parent.parent
        cache = work / "machine-a" / "s3" / BUCKET / "stores" / "one"
        assert folder.parent == cache / "pipelines" / "acme+rates"
        assert f"stores/one/pipelines/acme+rates/{folder.name}/_data/treasury.parquet" in _keys(client)

        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        monkeypatch.chdir(forecast)
        assert data.load("rates:treasury").collect().shape == (1, 2)
        assert data.path("rates:treasury") == cache / "views" / content_hash[7:] / "treasury.parquet"
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

        # And offline, what it read before: `pin --frozen` and a read
        _offline(client, monkeypatch)
        store_module._found_whole.clear()
        assert lock.verify(forecast).problems == []
        assert data.load("rates:treasury").collect().shape == (1, 2)


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
        for planted in (f"../../evil/{FOLDER}/_chartbook/snapshot.json", "acme+rates/../x/_chartbook/snapshot.json",
                        f"acme+rates//{FOLDER}/_chartbook/snapshot.json"):
            client.put_object(Bucket=BUCKET, Key=root + planted, Body=json.dumps(record).encode())
        # A record whose files lead out of its pipeline's folder is not followed
        leading = dict(record, records=[dict(record["records"][0], content_hash="sha256:" + "e" * 64, stored={
            "at": "_data", "single": True,
            "files": [{"path": "_data/x.parquet", "content_hash": "sha256:" + "e" * 64, "size_bytes": 7, "kept_in": "../../../evil"}],
        })])
        client.put_object(Bucket=BUCKET, Key=f"{root}acme+rates/2026-10-18T010203Z_bbbbbbbbbbbb/_chartbook/snapshot.json", Body=json.dumps(leading).encode())
        second = S3Store(URL, cache=work / "machine-b", client=client)
        assert [p.parent.parent.name for p in second.all_snapshot_files()] == [FOLDER, "2026-10-18T010203Z_bbbbbbbbbbbb"]
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
        _behind_its_back(store)
        planted = "sha256:" + "f" * 64
        assert planted in set(store.hashes()) and not store.has(planted)
        assert store.size_of(planted) == len(b"planted") and store.age_of(planted) >= 0
        plan = lock.plan_gc(store=store, recent_seconds=0)
        assert planted in [content_hash for content_hash, _ in plan.delete]
        assert lock.run_gc(plan, store=store)[1] == 2  # the planted object, and the one put
        assert _keys(client, other) == [] and _keys(client, prefix) == []

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
        _behind_its_back(store)
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
        (key,) = [k for k in _keys(client) if k.endswith("/b.bin")]
        client.delete_object(Bucket=BUCKET, Key=key)
        _behind_its_back(store)
        assert "does not have b.bin yet: it is not fully uploaded yet" in store.incomplete(stored.content_hash, 30, files, every=True)
        assert "has 10 bytes where its record says 30: it is not fully uploaded yet" in store.incomplete(stored.content_hash, 30, None)
        # A key written over holds other bytes: no upload mends that
        client.put_object(Bucket=BUCKET, Key=key, Body=b"b" * 5)
        _behind_its_back(store)
        said = store.incomplete(stored.content_hash, 30, files, every=True)
        assert "has 5 bytes of b.bin where its record says 20" in said and "not fully uploaded" not in said and "store verify" in said
        client.put_object(Bucket=BUCKET, Key=key, Body=b"b" * 20)
        # A key the record does not list, which a reader of the folder would read
        client.put_object(Bucket=BUCKET, Key=key.replace("b.bin", "b (1).bin"), Body=b"b" * 20)
        _behind_its_back(store)
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
