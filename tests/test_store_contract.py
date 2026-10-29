"""What every kind of store must do: the contract behind `chartbook.store.Store`.

Run against each implementation: the folder store, and the S3 store in a
mocked bucket. A plugin's store should pass this file unchanged.
"""

import json
from pathlib import Path

import pytest

from chartbook import hashing
from chartbook import store as store_module
from chartbook.store import FolderStore, Store
from tests.mocked_s3 import URL, mocked_s3

IMPLEMENTATIONS = ("folder", "s3")


@pytest.fixture(params=IMPLEMENTATIONS)
def store(request, tmp_path, monkeypatch) -> Store:
    work = tmp_path.resolve()
    if request.param == "folder":
        yield FolderStore(work / "store")
        return
    from chartbook.stores.s3 import S3Store

    with mocked_s3(monkeypatch) as client:
        yield S3Store(URL, cache=work / "cache", client=client)


@pytest.fixture
def a_file(tmp_path) -> Path:
    path = tmp_path.resolve() / "_data" / "rates.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"rates-1")
    return path


COMMIT = "a" * 40


class TestObjects:
    def test_put_has_get_delete(self, store, a_file):
        stored = store.put(a_file)
        assert stored.content_hash.startswith("sha256:") and stored.size_bytes == 7
        assert store.has(stored.content_hash)
        held = store.get(stored.content_hash)
        assert (Path(held) / "rates.parquet").read_bytes() == b"rates-1"
        assert list(store.hashes()) == [stored.content_hash]
        assert store.size_of(stored.content_hash) == 7
        assert store.age_of(stored.content_hash) >= 0
        assert store.verify() == []
        assert store.delete(stored.content_hash) is True
        assert not store.has(stored.content_hash) and store.delete(stored.content_hash) is False

    def test_the_same_bytes_are_one_object(self, store, a_file, tmp_path):
        other = tmp_path / "other.parquet"
        other.write_bytes(b"rates-1")
        first, second = store.put(a_file), store.put(other)
        assert first.content_hash == second.content_hash
        assert sorted(p.name for p in Path(store.get(first.content_hash)).iterdir()) == ["other.parquet", "rates.parquet"]

    def test_a_missing_object_is_said(self, store):
        assert not store.has("sha256:" + "0" * 64)
        with pytest.raises(store_module.ObjectNotFoundError):
            store.get("sha256:" + "0" * 64)
        # Gone since it was listed (another gc at the same time, a put replacing it): the same error
        with pytest.raises(store_module.ObjectNotFoundError, match="has no object sha256:0000"):
            store.age_of("sha256:" + "0" * 64)


class TestRoots:
    def test_a_lockfile_keeps_objects(self, store, a_file, tmp_path):
        stored = store.put(a_file)
        lockfile = tmp_path / "chartbook.lock"
        store.add_root(lockfile, [stored.content_hash])
        (root,) = store.roots()
        assert root.lockfile == lockfile and root.hashes == (stored.content_hash,)
        assert store.remove_root(lockfile) is True and store.roots() == []
        assert store.remove_root(lockfile) is False

    def test_a_lockfile_pins_versions_by_label(self, store, a_file, tmp_path):
        """A note records the model versions its lockfile pins by label, each with the moment it was pinned from."""
        stored = store.put(a_file)
        lockfile = tmp_path / "chartbook.lock"
        moment = (COMMIT, "2026-10-16T00:00:00.000000Z")
        labelled = {(*moment, "model/m", stored.content_hash), ("", "", "model/n", stored.content_hash)}
        store.add_root(lockfile, [stored.content_hash], [moment], labelled=labelled)
        (root,) = store.roots()
        assert root.snapshots == (moment,) and set(root.labelled) == labelled
        assert store.root_of(lockfile).labelled == root.labelled
        store.add_root(lockfile, [stored.content_hash])
        assert store.roots()[0].labelled == ()


class TestSnapshotRecords:
    def test_write_find_remove(self, store):
        assert store.snapshot_commits() == set()
        assert store.snapshot_files(COMMIT, "_top") == []
        document = {
            "schema": "chartbook/snapshot/v2", "root": "acme/rates", "code": {"commit": COMMIT},
            "made_at": "2026-10-16T01:02:03Z", "records": [],
        }
        written = store.write_snapshot(COMMIT, "_top", "20261016T010203Z", document)
        assert json.loads(Path(written).read_text(encoding="utf-8"))["root"] == "acme/rates"
        again = store.write_snapshot(COMMIT, "_top", "20261016T010203Z", document)
        assert again != written  # the same moment twice is two records
        assert store.snapshot_commits() == {COMMIT}
        assert store.snapshot_files(COMMIT, "_top") == sorted([Path(written), Path(again)])
        assert store.all_snapshot_files() == sorted([Path(written), Path(again)])
        assert store.remove_snapshot(written) is True and store.remove_snapshot(written) is False
        assert store.snapshot_files(COMMIT, "_top") == [Path(again)]
        assert store.remove_snapshot(again) is True
        assert store.snapshot_commits() == set()

    def test_origins_are_noted_once_each(self, store, tmp_path):
        store.note_origin(COMMIT, "_top", str(tmp_path / "a"))
        store.note_origin(COMMIT, "_top", str(tmp_path / "a"))
        store.note_origin(COMMIT, "_top", str(tmp_path / "b"))
        assert store.origins(COMMIT, "_top") == [str(tmp_path / "a"), str(tmp_path / "b")]
        assert store.origins(COMMIT, "elsewhere") == []

    def test_a_commit_must_be_full(self, store):
        with pytest.raises(ValueError, match="not a full commit hash"):
            store.snapshot_files("abc123", "_top")


class TestSnapshotFolders:
    """A snapshot is a folder in its pipeline's folder: its files at their places, each kept once, its record last."""

    @staticmethod
    def _pipeline(tmp_path, files: dict) -> Path:
        folder = tmp_path.resolve() / "rates"
        for name, data in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
        return folder

    @staticmethod
    def _record(pending, commit: str, **stored) -> dict:
        return {
            "schema": "chartbook/snapshot/v2",
            "root": "acme/rates",
            "code": {"commit": commit},
            "made_at": pending.made_at,
            "records": [
                {"id": f"acme/rates:{name}", "content_hash": put.content_hash, "size_bytes": put.size_bytes, "stored": put.stored}
                for name, put in sorted(stored.items())
            ],
        }

    def test_its_files_are_in_their_places(self, store, tmp_path):
        folder = self._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1", "_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        one = pending.put(folder / "_data" / "rates.parquet")
        many = pending.put(folder / "_data" / "parts")
        assert one.content_hash == hashing.hash_path(folder / "_data" / "rates.parquet").content_hash
        assert many.content_hash == hashing.hash_path(folder / "_data" / "parts").content_hash
        assert not store.has(one.content_hash)  # a snapshot once its record is written, not before
        record = pending.write(self._record(pending, COMMIT, rates=one, parts=many))
        assert store.all_snapshot_files() == [Path(record)] and store.snapshot_commits() == {COMMIT}
        here = "pipelines/acme+rates/2026-10-16T010203Z_aaaaaaaaaaaa"
        assert store.files_of(one.content_hash) == [(f"{here}/_data/rates.parquet", 7)]
        assert store.has(one.content_hash) and store.has(many.content_hash)
        assert (Path(store.get(one.content_hash)) / "rates.parquet").read_bytes() == b"rates-1"
        assert sorted(p.name for p in Path(store.get(many.content_hash)).iterdir()) == ["a.txt", "b.txt"]
        assert store.incomplete(one.content_hash, 7) is None and store.incomplete(many.content_hash, 2) is None
        assert store.verify() == []

    def test_each_file_is_kept_once(self, store, tmp_path):
        folder = self._pipeline(tmp_path, {"_data/parts/a.txt": b"a", "_data/parts/b.txt": b"b"})
        first = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = first.put(folder / "_data" / "parts")
        first.write(self._record(first, COMMIT, parts=put))
        (folder / "_data" / "parts" / "c.txt").write_bytes(b"c")
        later = "b" * 40
        second = store.begin("acme/rates", later, "2026-10-17T01:02:03.000000Z", base=folder)
        again = second.put(folder / "_data" / "parts")
        assert [entry.get("kept_in") for entry in again.stored["files"]] == [
            "2026-10-16T010203Z_aaaaaaaaaaaa", "2026-10-16T010203Z_aaaaaaaaaaaa", "2026-10-17T010203Z_bbbbbbbbbbbb",
        ]
        second.write(self._record(second, later, parts=again))
        assert {name for name, _ in store.files_of(again.content_hash)} == {
            "pipelines/acme+rates/2026-10-16T010203Z_aaaaaaaaaaaa/_data/parts/a.txt",
            "pipelines/acme+rates/2026-10-16T010203Z_aaaaaaaaaaaa/_data/parts/b.txt",
            "pipelines/acme+rates/2026-10-17T010203Z_bbbbbbbbbbbb/_data/parts/c.txt",
        }
        # Gathered for a reader, from the two folders that keep them
        gathered = Path(store.get(again.content_hash))
        assert {p.name: p.read_bytes() for p in gathered.iterdir()} == {"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"}
        assert store.verify() == []

    def test_one_not_written_leaves_nothing(self, store, tmp_path):
        folder = self._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = pending.put(folder / "_data" / "rates.parquet")
        pending.discard()
        assert not store.has(put.content_hash) and store.all_snapshot_files() == [] and list(store.hashes()) == []

    def test_clearing_one_keeps_what_a_later_one_uses(self, store, tmp_path):
        folder = self._pipeline(tmp_path, {"_data/parts/a.txt": b"a", "_data/one.txt": b"only the first"})
        first = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        parts, one = first.put(folder / "_data" / "parts"), first.put(folder / "_data" / "one.txt")
        record = first.write(self._record(first, COMMIT, parts=parts, one=one))
        second = store.begin("acme/rates", "b" * 40, "2026-10-17T01:02:03.000000Z", base=folder)
        again = second.put(folder / "_data" / "parts")
        second.write(self._record(second, "b" * 40, parts=again))
        assert store.remove_snapshot(record) is True
        assert not store.has(one.content_hash)
        assert store.has(parts.content_hash) and (Path(store.get(parts.content_hash)) / "a.txt").read_bytes() == b"a"
        assert store.verify() == []

    def test_one_whose_record_was_written_is_kept_by_a_discard(self, store, tmp_path):
        """Found by a review: a record written, its answer lost (a connection cut, a Ctrl-C), and its files then discarded."""
        folder = self._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = pending.put(folder / "_data" / "rates.parquet")
        pending.write(self._record(pending, COMMIT, rates=put))
        pending._written = False  # what wrote it never heard back
        pending.discard()
        store._forget()
        assert store.has(put.content_hash) and len(store.all_snapshot_files()) == 1 and store.verify() == []

    def test_one_a_pin_made_is_not_an_owners(self, store, tmp_path):
        folder = self._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder, made_by="pin")
        put = pending.put(folder / "_data" / "rates.parquet")
        record = pending.write(self._record(pending, COMMIT, rates=put))
        assert json.loads(Path(record).read_text(encoding="utf-8"))["made_by"] == "pin"
        assert store.all_snapshot_files() == [] and store.snapshot_commits() == set()
        assert store.pinned_snapshot_files() == [Path(record)] and store.has(put.content_hash)


class TestWhereItIs:
    def test_str_says_where(self, store):
        # A place, for a message: the folder store says its folder, the S3
        # store its URL, and a plugin must override the base's fallback to its repr
        assert str(store) == (str(store.root) if isinstance(store, FolderStore) else URL)
        assert not str(store).startswith(type(store).__name__ + "(")


class TestTheFactory:
    def test_a_folder_url_gives_a_folder_store(self, tmp_path):
        store = store_module.store_for_url(str(tmp_path / "s"))
        assert isinstance(store, FolderStore) and store.root == (tmp_path / "s").resolve()
        assert isinstance(store_module.store_for_url("file://" + str(tmp_path / "s")), FolderStore)

    def test_another_kind_needs_a_plugin(self):
        with pytest.raises(ValueError, match="is a gs:// store, and nothing provides one.*entry point named 'gs'"):
            store_module.store_for_url("gs://bucket/prefix")

    def test_the_s3_store_is_found_by_its_entry_point(self, tmp_path, monkeypatch):
        pytest.importorskip("boto3")
        from chartbook.stores.s3 import S3Store

        store_module._plugin_store_class.cache_clear()
        monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "cache"))
        with mocked_s3(monkeypatch):
            found = store_module.store_for_url("s3://chartbook-test/anywhere")
        assert isinstance(found, S3Store) and str(found) == "s3://chartbook-test/anywhere"
        assert found.cache == tmp_path / "cache" / "s3" / "chartbook-test" / "anywhere"

    def test_a_plugin_is_found_by_its_scheme(self, monkeypatch):
        class Fake:
            def __init__(self, url):
                self.url = url

        class Entry:
            name = "fake"

            @staticmethod
            def load():
                return Fake

        import importlib.metadata

        store_module._plugin_store_class.cache_clear()

        monkeypatch.setattr(importlib.metadata, "entry_points", lambda group=None: [Entry()] if group == store_module.STORE_PLUGIN_GROUP else [])
        found = store_module.store_for_url("fake://anywhere")
        assert isinstance(found, Fake) and found.url == "fake://anywhere"

    def test_a_plugin_that_cannot_be_loaded_is_named(self, monkeypatch):
        class Entry:
            name = "broken"
            value = "nowhere.plugin:Store"

            @staticmethod
            def load():
                raise ImportError("no module named nowhere")

        import importlib.metadata

        store_module._plugin_store_class.cache_clear()
        monkeypatch.setattr(importlib.metadata, "entry_points", lambda group=None: [Entry()])
        with pytest.raises(ValueError, match="plugin 'nowhere.plugin:Store' for broken:// stores cannot be loaded: no module named nowhere"):
            store_module.store_for_url("broken://x")
        store_module._plugin_store_class.cache_clear()


class TestWhatTheThirdReviewFound:
    """The folder store's gc and a snapshot being made, met at once."""

    def test_a_folder_made_just_now_is_not_removed_for_being_empty(self, tmp_path):
        store = FolderStore(tmp_path.resolve() / "store")
        folder = TestSnapshotFolders._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        made = pending._claim() / "_data" / "deep"
        made.mkdir(parents=True)  # a snapshot about to write a file into it
        store.tidy()
        assert made.is_dir()

    def test_two_snapshots_putting_back_one_file_both_succeed(self, tmp_path):
        store = FolderStore(tmp_path.resolve() / "store")
        folder = TestSnapshotFolders._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        first = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = first.put(folder / "_data" / "rates.parquet")
        first.write(TestSnapshotFolders._record(first, COMMIT, rates=put))
        ((name, _),) = store.files_of(put.content_hash)
        (store.root / name).chmod(0o644)
        (store.root / name).unlink()  # lost; two snapshots now put it back at once
        a = store.begin("acme/rates", "b" * 40, "2026-10-17T01:02:03.000000Z", base=folder)
        b = store.begin("acme/rates", "c" * 40, "2026-10-18T01:02:03.000000Z", base=folder)
        a.put(folder / "_data" / "rates.parquet")
        (store.root / name).chmod(0o644)
        (store.root / name).unlink()
        b.put(folder / "_data" / "rates.parquet")
        assert (store.root / name).read_bytes() == b"rates-1"
        written = a._write_file(str(folder / "_data" / "rates.parquet"), store.root / name, ("copy",), expect=put.content_hash)
        assert written[0] == put.content_hash  # the other put it back: no error

    def test_a_record_this_machine_cannot_follow_is_said_and_nothing_goes(self, tmp_path):
        import warnings

        store = FolderStore(tmp_path.resolve() / "store")
        folder = TestSnapshotFolders._pipeline(tmp_path, {"_data/rates.parquet": b"rates-1"})
        first = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = first.put(folder / "_data" / "rates.parquet")
        document = TestSnapshotFolders._record(first, COMMIT, rates=put)
        document["records"][0]["stored"]["files"][0]["kept_as"] = "../escape.parquet"  # one it does not follow
        first.write(document)
        stray = first._claim() / "stray.txt"
        stray.write_text("x", encoding="utf-8")
        with warnings.catch_warnings(record=True) as said:
            warnings.simplefilter("always")
            store.tidy(keep=())
        assert any("Nothing in" in str(w.message) for w in said)
        assert stray.exists()

    def test_what_a_writer_that_died_left_in_tmp_goes_two_days_on(self, tmp_path, monkeypatch):
        import os
        import time
        import types

        store = FolderStore(tmp_path.resolve() / "store")
        store._check_layout(create=True)
        tmp = store.root / "tmp"
        tmp.mkdir()
        old, new = tmp / "aaaaaaaaaaaa.pending", tmp / "bbbbbbbbbbbb.pending"
        for path in (old, new):
            path.write_text("folder x\n", encoding="utf-8")
        then = time.time() - 3 * 86400
        os.utime(old, (then, then))  # a clone keeps its source's time; it was made now
        store.tidy()
        assert old.exists()
        later = time.time() + 3 * 86400
        os.utime(new, (later, later))  # touched by a writer still at work, as the clock will then read
        clock = types.SimpleNamespace(**{name: getattr(time, name) for name in dir(time) if not name.startswith("_")})
        clock.time = lambda: later
        monkeypatch.setattr(store_module, "time", clock)
        store.tidy()
        assert not old.exists() and new.exists()
        journal = tmp / "migrate.jsonl"
        journal.write_text("{}\n", encoding="utf-8")
        os.utime(journal, (0, 0))
        store._tidy_tmp()  # gc itself refuses a store with one
        assert journal.exists()  # a migrate's, however old

    def test_a_cleared_snapshots_empty_folders_go_at_once(self, tmp_path):
        """Found by a review: the folders the sweep had just emptied looked made just now, and stayed."""
        store = FolderStore(tmp_path.resolve() / "store")
        folder = TestSnapshotFolders._pipeline(tmp_path, {"_data/deep/one.txt": b"one"})
        pending = store.begin("acme/rates", COMMIT, "2026-10-16T01:02:03.000000Z", base=folder)
        put = pending.put(folder / "_data" / "deep" / "one.txt")
        record = pending.write(TestSnapshotFolders._record(pending, COMMIT, one=put))
        assert store.remove_snapshot(record) is True
        store.tidy()
        assert list((store.root / "pipelines" / "acme+rates").iterdir()) == []
