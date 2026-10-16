"""What every kind of store must do: the contract behind `chartbook.store.Store`.

Run against each implementation; the folder store is the only one built,
and a plugin's store should pass this file unchanged.
"""

import json
from pathlib import Path

import pytest

from chartbook import store as store_module
from chartbook.store import FolderStore, Store

IMPLEMENTATIONS = {"folder": lambda work: FolderStore(work / "store")}


@pytest.fixture(params=sorted(IMPLEMENTATIONS))
def store(request, tmp_path) -> Store:
    return IMPLEMENTATIONS[request.param](tmp_path.resolve())


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


class TestRoots:
    def test_a_lockfile_keeps_objects(self, store, a_file, tmp_path):
        stored = store.put(a_file)
        lockfile = tmp_path / "chartbook.lock"
        store.add_root(lockfile, [stored.content_hash])
        (root,) = store.roots()
        assert root.lockfile == lockfile and root.hashes == (stored.content_hash,)
        assert store.remove_root(lockfile) is True and store.roots() == []
        assert store.remove_root(lockfile) is False


class TestSnapshotRecords:
    def test_write_find_remove(self, store):
        assert store.snapshot_commits() == set()
        assert store.snapshot_files(COMMIT, "_top") == []
        document = {"schema": "chartbook/snapshot/v1", "root": "acme/rates", "made_at": "2026-10-16T01:02:03Z", "records": []}
        written = store.write_snapshot(COMMIT, "_top", "20261016T010203Z", document)
        assert json.loads(Path(written).read_text())["root"] == "acme/rates"
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


class TestWhereItIs:
    def test_str_says_where(self, store):
        # A place, for a message: the folder store says its folder, and a
        # plugin must override the base's fallback to its repr
        assert str(store) == (str(store.root) if isinstance(store, FolderStore) else str(store))
        assert not str(store).startswith(type(store).__name__ + "(")


class TestTheFactory:
    def test_a_folder_url_gives_a_folder_store(self, tmp_path):
        store = store_module.store_for_url(str(tmp_path / "s"))
        assert isinstance(store, FolderStore) and store.root == (tmp_path / "s").resolve()
        assert isinstance(store_module.store_for_url("file://" + str(tmp_path / "s")), FolderStore)

    def test_another_kind_needs_a_plugin(self):
        with pytest.raises(ValueError, match="is a s3:// store, and nothing provides one.*entry point named 's3'"):
            store_module.store_for_url("s3://bucket/prefix")

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
