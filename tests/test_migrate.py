"""`chartbook store migrate`: a store of ChartBook 0.2 moved to the layout of 0.3.

The store of 0.2 is laid out here by hand, as 0.2 laid one out: each asset
an object, a folder named by its hash under objects/, and each record under
its commit, snapshots/<commit>/<name>/<time>.json.
"""

import dis
import json
import os
import shutil
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from chartbook import hashing, migrate, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.refs import AssetRef
from chartbook.store import FolderStore, StoreError, holds_v1

FIRST, SECOND, OTHER = "a" * 40, "b" * 40, "c" * 40


def _object(root: Path, path: Path, single: bool, name: str = "") -> hashing.ContentHash:
    """Put what *path* names in a 0.2 store as 0.2 did: a folder named by its hash, holding its files."""
    content = hashing.hash_file(path) if single else hashing.hash_directory(path)
    digest = content.content_hash.split(":", 1)[1]
    folder = root / "objects" / "sha256" / digest[:2] / digest[2:]
    if single:
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / (name or path.name)).exists():
            shutil.copyfile(path, folder / (name or path.name))
    elif not folder.exists():
        shutil.copytree(path, folder)
    return content


def _record(pipeline: str, kind: str, name: str, declared: str, content, single: bool) -> dict:
    ref = AssetRef(kind=kind, name=name).in_pipeline(pipeline)
    return snapshot.asset_record(ref, pipeline, declared, SimpleNamespace(
        content_hash=content.content_hash, size_bytes=content.size_bytes, entries=content.files,
    ), single)


def _write_record(root: Path, commit: str, made_at: str, document: dict) -> Path:
    stamp = made_at.replace("-", "").replace(":", "")
    path = root / "snapshots" / commit / "_top" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "chartbook/snapshot/v1", "code": {"commit": commit}, "made_at": made_at, **document}), encoding="utf-8")
    return path


@pytest.fixture
def old_store(tmp_path):
    """A store of 0.2: two snapshots of acme/rates, one of acme/other with bytes rates has too, and an object only a lockfile named."""
    root = tmp_path.resolve() / "store"
    root.mkdir()
    (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v1"}) + "\n", encoding="utf-8")
    work = tmp_path.resolve() / "work"
    (work / "_data" / "parts").mkdir(parents=True)
    (work / "_data" / "rates.parquet").write_bytes(b"rates-1")
    (work / "_data" / "parts" / "a.txt").write_bytes(b"a")
    (work / "_data" / "parts" / "b.txt").write_bytes(b"b")
    (work / "glob").mkdir()
    (work / "glob" / "t_2025.txt").write_bytes(b"2025")
    (work / "glob" / "t_2026.txt").write_bytes(b"2026")
    (work / "docs").mkdir()
    (work / "docs" / "chartbook.toml").write_text("[project]\nid = 'acme/rates'\n", encoding="utf-8")
    (work / "docs" / "README.md").write_text("# Rates\n", encoding="utf-8")

    rates = _object(root, work / "_data" / "rates.parquet", True)
    parts = _object(root, work / "_data" / "parts", False)
    globbed = _object(root, work / "glob", False)
    documents = _object(root, work / "docs", False)
    first = _write_record(root, FIRST, "2026-10-01T10:00:00.000000Z", {
        "root": "acme/rates",
        "documents": {"content_hash": documents.content_hash, "size_bytes": documents.size_bytes, "files": ["README.md", "chartbook.toml"]},
        "records": [
            _record("acme/rates", "dataframe", "parts", "./_data/parts", parts, False),
            _record("acme/rates", "dataframe", "rates", "./_data/rates.parquet", rates, True),
            _record("acme/rates", "dataframe", "years", "./_data/t_*.txt", globbed, False),
        ],
    })
    (first.parent / "origins").write_text("/home/x/rates\n", encoding="utf-8")

    (work / "_data" / "rates.parquet").write_bytes(b"rates-2")
    (work / "_data" / "parts" / "c.txt").write_bytes(b"c")
    rates_2 = _object(root, work / "_data" / "rates.parquet", True)
    parts_2 = _object(root, work / "_data" / "parts", False)
    _write_record(root, SECOND, "2026-10-02T10:00:00.000000Z", {
        "root": "acme/rates",
        "records": [
            _record("acme/rates", "dataframe", "parts", "./_data/parts", parts_2, False),
            _record("acme/rates", "dataframe", "rates", "./_data/rates.parquet", rates_2, True),
        ],
    })

    # Another pipeline's snapshot of the same bytes as rates' first, under another name
    (work / "same.parquet").write_bytes(b"rates-1")
    _object(root, work / "same.parquet", True)
    _write_record(root, OTHER, "2026-10-03T10:00:00.000000Z", {
        "root": "acme/other",
        "records": [_record("acme/other", "dataframe", "same", "./same.parquet", rates, True)],
    })

    # What only a lockfile named: a git dependency's pin
    (work / "pinned.parquet").write_bytes(b"pinned")
    pinned = _object(root, work / "pinned.parquet", True)
    (root / "roots").mkdir()
    (root / "roots" / ("0" * 32 + ".json")).write_text(json.dumps({"lockfile": str(work / "chartbook.lock"), "hashes": [pinned.content_hash]}), encoding="utf-8")
    hashes = {"rates": rates, "parts": parts, "years": globbed, "documents": documents, "rates_2": rates_2, "parts_2": parts_2, "pinned": pinned}
    return root, {name: content.content_hash for name, content in hashes.items()}


class TestMigrate:
    def test_a_store_of_0_2_is_refused_until_it_is_moved(self, old_store):
        root, hashes = old_store
        with pytest.raises(StoreError, match=r"layout of ChartBook 0\.2.*chartbook store migrate"):
            FolderStore(root).has(hashes["rates"])

    def test_the_plan_says_what_it_would_move_and_moves_nothing(self, old_store):
        root, hashes = old_store
        found = migrate.plan(root)
        assert found.needed and len(found.records) == 3 and found.objects == 7 and found.done == 0
        assert found.unowned == [hashes["pinned"]]
        assert found.to_read > 0  # the glob's and the documents' files
        assert (root / "objects").is_dir() and not (root / "pipelines").exists()

    def test_each_snapshot_is_a_folder_and_each_file_is_kept_once(self, old_store):
        root, hashes = old_store
        migrate.run(root)
        store = FolderStore(root)
        rates = root / "pipelines" / "acme+rates"
        first, second = rates / "2026-10-01T100000Z_aaaaaaaaaaaa", rates / "2026-10-02T100000Z_bbbbbbbbbbbb"
        assert sorted(p.name for p in rates.iterdir()) == [first.name, second.name]
        # The first holds everything it had, at its place in the pipeline
        assert (first / "_data" / "rates.parquet").read_bytes() == b"rates-1"
        assert sorted(p.name for p in (first / "_data" / "parts").iterdir()) == ["a.txt", "b.txt"]
        assert (first / "_data" / "t_2025.txt").read_bytes() == b"2025"
        assert (first / "README.md").is_file() and (first / "chartbook.toml").is_file()
        # The second only what is new
        assert sorted(p.relative_to(second).as_posix() for p in second.rglob("*") if p.is_file()) == [
            "_chartbook/snapshot.json", "_data/parts/c.txt", "_data/rates.parquet",
        ]
        # Every asset is read as it was, by its hash
        for name in ("parts", "years", "documents", "parts_2"):
            assert store.has(hashes[name])
        assert (Path(store.get(hashes["rates"], name="rates.parquet")) / "rates.parquet").read_bytes() == b"rates-1"
        assert sorted(p.name for p in Path(store.get(hashes["parts_2"])).iterdir()) == ["a.txt", "b.txt", "c.txt"]
        assert store.verify() == []
        # Every record reads as a snapshot of this version
        found, unreadable = snapshot.readable_snapshots(store)
        assert unreadable == [] and [t.pipeline for t in found] == ["acme/rates", "acme/rates", "acme/other"]

    def test_bytes_two_pipelines_share_are_copied_for_the_second(self, old_store):
        root, hashes = old_store
        migrate.run(root)
        other = root / "pipelines" / "acme+other" / "2026-10-03T100000Z_cccccccccccc"
        assert (other / "same.parquet").read_bytes() == b"rates-1"
        assert (root / "pipelines" / "acme+rates" / "2026-10-01T100000Z_aaaaaaaaaaaa" / "_data" / "rates.parquet").is_file()

    def test_what_no_record_names_is_an_object_no_pipeline_owns(self, old_store):
        root, hashes = old_store
        migrate.run(root)
        store = FolderStore(root)
        assert store.unowned_hashes() == [hashes["pinned"]]
        assert (Path(store.get(hashes["pinned"])) / "pinned.parquet").read_bytes() == b"pinned"
        assert [root.hashes for root in store.roots()] == [(hashes["pinned"],)]  # its lockfile's note stays

    def test_the_old_folders_go_and_0_2_is_left_a_record_it_cannot_read(self, old_store):
        root, hashes = old_store
        migrate.run(root)
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v2"}
        assert not (root / "objects").exists()
        (sentinel,) = (root / "snapshots").rglob("*.json")
        assert json.loads(sentinel.read_text(encoding="utf-8"))["schema"] != "chartbook/snapshot/v1"
        assert snapshot.readable_snapshots(FolderStore(root))[1] == []  # 0.3 does not look there
        assert FolderStore(root).origins(FIRST, "_top") == ["/home/x/rates"]
        assert not migrate.plan(root).needed

    def test_one_cut_short_goes_on_where_it_stopped(self, old_store, monkeypatch):
        root, hashes = old_store
        moved = migrate._move_record

        def once(store, journal, path, document, prepared):
            moved(store, journal, path, document, prepared)
            if document["root"] == "acme/rates" and document["code"]["commit"] == SECOND:
                raise KeyboardInterrupt

        monkeypatch.setattr(migrate, "_move_record", once)
        with pytest.raises(KeyboardInterrupt):
            migrate.run(root)
        monkeypatch.setattr(migrate, "_move_record", moved)
        assert migrate.plan(root).done == 2
        migrate.run(root)
        store = FolderStore(root)
        assert store.verify() == [] and len(snapshot.readable_snapshots(store)[0]) == 3

    def test_a_record_that_cannot_be_read_moves_nothing(self, old_store):
        root, hashes = old_store
        broken = root / "snapshots" / FIRST / "_top" / "20261005T000000.000000Z.json"
        broken.write_text("{", encoding="utf-8")
        with pytest.raises(migrate.MigrateError, match="Cannot read the snapshot record.*Nothing was moved"):
            migrate.run(root)
        assert (root / "objects").is_dir() and not (root / "pipelines").exists()

    def test_the_command(self, old_store, monkeypatch):
        root, hashes = old_store
        monkeypatch.setenv("CHARTBOOK_STORE", str(root))
        said = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        assert said.exit_code == 0 and "Would move 3 snapshot(s) of 3" in said.output and "Nothing was moved" in said.output
        said = CliRunner().invoke(main, ["store", "migrate"], input="n\n")
        assert "Nothing was moved." in said.output and (root / "objects").is_dir()
        said = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert said.exit_code == 0, said.output
        assert "Moved." in said.output and FolderStore(root).verify() == []
        again = CliRunner().invoke(main, ["store", "migrate"])
        assert again.exit_code == 0 and "nothing to move" in again.output


class TestWhatTheReviewFound:
    """Each of a review's reproductions against stores made by 0.2.0."""

    def _every_byte(self, root: Path) -> dict:
        return {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file() and "objects" in p.parts}

    def test_cut_short_just_after_a_file_is_moved_loses_nothing(self, old_store, monkeypatch):
        root, hashes = old_store
        moves = []
        rename = os.rename

        def then_stop(source, target):
            rename(source, target)
            moves.append(target)
            if len(moves) == 3:
                raise KeyboardInterrupt  # between the move and anything after it

        monkeypatch.setattr(migrate.os, "rename", then_stop)
        with pytest.raises(KeyboardInterrupt):
            migrate.run(root)
        monkeypatch.setattr(migrate.os, "rename", rename)
        assert all(Path(target).is_file() for target in moves)  # never taken back
        migrate.run(root)
        store = FolderStore(root)
        assert store.verify() == []
        for name in ("rates", "parts", "years", "documents", "rates_2", "parts_2", "pinned"):
            assert store.has(hashes[name]), name

    def test_an_object_not_whole_moves_nothing(self, old_store):
        root, hashes = old_store
        digest = hashes["parts"].split(":", 1)[1]
        (root / "objects" / "sha256" / digest[:2] / digest[2:] / "b.txt").unlink()  # a sync not finished
        with pytest.raises(migrate.MigrateError, match="(?s)does not have b.txt.*Nothing was moved"):
            migrate.run(root)
        assert not (root / "pipelines").exists() and (root / "objects").is_dir()

    def test_a_sync_services_copy_in_a_globs_object_is_left_out(self, old_store):
        root, hashes = old_store
        digest = hashes["years"].split(":", 1)[1]
        (root / "objects" / "sha256" / digest[:2] / digest[2:] / "t_2026 (1).txt").write_bytes(b"2026")
        migrate.run(root)
        store = FolderStore(root)
        assert sorted(p.name for p in Path(store.get(hashes["years"])).iterdir()) == ["t_2025.txt", "t_2026.txt"]
        assert store.verify() == []

    def test_a_record_written_to_climb_out_moves_nothing(self, old_store, tmp_path):
        root, hashes = old_store
        forged = root / "snapshots" / FIRST / "_top" / "20261001T100000.000000Z.json"
        document = json.loads(forged.read_text(encoding="utf-8"))
        document["records"][1]["location"]["path"] = "./" + "../" * 20 + str(tmp_path / "escaped.parquet").lstrip("/")
        forged.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(migrate.MigrateError, match="not a plain path"):
            migrate.run(root)
        assert not (tmp_path / "escaped.parquet").exists() and not (root / "pipelines").exists()

    def test_cut_short_after_a_record_is_written_makes_it_once(self, old_store, monkeypatch):
        root, hashes = old_store
        wrote = migrate._Journal.wrote

        def lost_it(self, record, into):
            raise KeyboardInterrupt  # the record is written; the journal never hears

        monkeypatch.setattr(migrate._Journal, "wrote", lost_it)
        with pytest.raises(KeyboardInterrupt):
            migrate.run(root)
        monkeypatch.setattr(migrate._Journal, "wrote", wrote)
        migrate.run(root)
        assert len(snapshot.readable_snapshots(FolderStore(root))[0]) == 3

    def test_cut_short_while_the_old_folders_go_is_finished_next_time(self, old_store, monkeypatch):
        root, hashes = old_store
        remove = migrate._remove_tree
        monkeypatch.setattr(migrate, "_remove_tree", lambda path: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            migrate.run(root)
        monkeypatch.setattr(migrate, "_remove_tree", remove)
        found = migrate.plan(root)
        assert found.needed and found.unfinished
        migrate.run(root)
        assert not (root / "objects").exists() and FolderStore(root).verify() == []


class TestWhatTheSecondReviewFound:
    def test_a_marker_over_a_stores_old_folders_loses_nothing_and_a_dry_run_moves_nothing(self, old_store):
        """store.json said v2 over a store of 0.2's (its store.json lost to a sync): a dry run once removed objects/."""
        root, hashes = old_store
        (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v2"}) + "\n", encoding="utf-8")
        before = sorted(p.relative_to(root).as_posix() for p in (root / "objects").rglob("*") if p.is_file())
        said = CliRunner().invoke(main, ["store", "migrate", "--dry-run"], env={"CHARTBOOK_STORE": str(root)})
        assert said.exit_code == 0 and "holds 0.2's folders too" in said.output and "Nothing was moved" in said.output
        assert sorted(p.relative_to(root).as_posix() for p in (root / "objects").rglob("*") if p.is_file()) == before
        migrate.run(root)
        store = FolderStore(root)
        assert store.verify() == [] and len(snapshot.readable_snapshots(store)[0]) == 3

    def test_no_marker_is_written_over_a_stores_old_folders(self, old_store):
        root, hashes = old_store
        (root / "store.json").unlink()
        with pytest.raises(StoreError, match="no store.json, and holds the folders of a store of ChartBook 0.2"):
            FolderStore(root).put(root / "objects" / "sha256" / hashes["rates"][7:9] / hashes["rates"][9:] / "rates.parquet")
        assert not (root / "store.json").exists()


class TestWhatTheThirdReviewFound:
    def test_a_marker_over_a_stores_old_folders_cut_short_at_a_move_loses_nothing(self, old_store, monkeypatch):
        """Found by a review: the journal alone was taken for a switch cut short, and what was not moved yet went."""
        root, hashes = old_store
        (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v2"}) + "\n", encoding="utf-8")
        moves = []
        rename = os.rename

        def then_stop(source, target):
            rename(source, target)
            moves.append(target)
            if len(moves) == 3:
                raise KeyboardInterrupt

        monkeypatch.setattr(migrate.os, "rename", then_stop)
        with pytest.raises(KeyboardInterrupt):
            migrate.run(root)
        monkeypatch.setattr(migrate.os, "rename", rename)
        found = migrate.plan(root)
        assert found.needed and not found.unfinished
        migrate.run(root)
        store = FolderStore(root)
        assert store.verify() == [] and len(snapshot.readable_snapshots(store)[0]) == 3
        for name in ("rates", "parts", "years", "documents", "rates_2", "parts_2", "pinned"):
            assert store.has(hashes[name]), name

    def test_a_store_moved_whose_store_json_is_lost_is_not_refused(self, old_store, tmp_path):
        """Found by a review: the record left for 0.2 was taken for 0.2's folders, and nothing could write."""
        root, hashes = old_store
        migrate.run(root)
        (root / "store.json").unlink()  # a sync that has not brought it yet
        (tmp_path / "new.txt").write_bytes(b"new")
        FolderStore(root).put(tmp_path / "new.txt")
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v2"}
        assert not migrate.plan(root).needed


def _cut_short_at_a_move(root: Path, monkeypatch) -> list:
    """Run a migrate that stops just after its third move; the files it moved."""
    moves = []
    rename = os.rename

    def then_stop(source, target):
        rename(source, target)
        moves.append(target)
        if len(moves) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(migrate.os, "rename", then_stop)
    with pytest.raises(KeyboardInterrupt):
        migrate.run(root)
    monkeypatch.setattr(migrate.os, "rename", rename)
    return moves


def _days_on(monkeypatch, days: float) -> None:
    """The store's clock, *days* on from now."""
    later = time.time() + days * 86400
    clock = types.SimpleNamespace(**{name: getattr(time, name) for name in dir(time) if not name.startswith("_")})
    clock.time = lambda: later
    monkeypatch.setattr(store_module, "time", clock)


def _all_there(root: Path, hashes: dict) -> None:
    store = FolderStore(root)
    assert store.verify() == [] and len(snapshot.readable_snapshots(store)[0]) == 3
    for name, content_hash in hashes.items():
        assert store.has(content_hash), name
    assert not (root / "objects").exists() and not (root / "tmp" / "migrate.jsonl").exists()


class TestWhatTheFourthReviewFound:
    @pytest.mark.parametrize("marker", ["v2", None])
    def test_gc_between_a_migrate_cut_short_and_its_rerun_removes_nothing(self, old_store, monkeypatch, marker):
        """Found by a review: what the migrate had moved had no record yet, and gc took it a day on."""
        root, hashes = old_store
        if marker:
            (root / "store.json").write_text(json.dumps({"schema": f"chartbook/store/{marker}"}) + "\n", encoding="utf-8")
        else:
            (root / "store.json").unlink()
        moves = _cut_short_at_a_move(root, monkeypatch)
        _days_on(monkeypatch, 2)
        with pytest.raises(StoreError, match="has not finished moving.*chartbook store migrate"):
            FolderStore(root).tidy()
        with pytest.raises(StoreError, match="has not finished moving"):
            FolderStore(root).tidy(dry_run=True)
        assert all(Path(target).is_file() for target in moves)
        monkeypatch.setattr(store_module, "time", time)
        migrate.run(root)
        _all_there(root, hashes)

    def test_store_gc_says_so_and_removes_nothing(self, old_store, monkeypatch):
        root, hashes = old_store
        (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v2"}) + "\n", encoding="utf-8")
        moves = _cut_short_at_a_move(root, monkeypatch)
        _days_on(monkeypatch, 2)
        said = CliRunner().invoke(main, ["store", "gc", "--yes"], env={"CHARTBOOK_STORE": str(root)})
        assert said.exit_code != 0 and "has not finished moving" in said.output
        assert all(Path(target).is_file() for target in moves)

    def test_a_0_2_record_come_after_a_switch_is_moved_not_removed(self, old_store, tmp_path, monkeypatch):
        """Found by a review: a journal left behind said "switched", and the record a 0.2 machine wrote since went with the old folders."""
        root, hashes = old_store
        unlink = Path.unlink

        def busy(self, *args, **kwargs):
            if self.name == "migrate.jsonl":
                raise PermissionError("busy")
            return unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", busy)
        migrate.run(root)
        monkeypatch.setattr(Path, "unlink", unlink)
        assert (root / "tmp" / "migrate.jsonl").exists()
        with pytest.raises(StoreError, match="has not finished moving"):
            FolderStore(root).tidy()  # nor is a journal left behind taken by gc
        work = tmp_path / "late"
        work.mkdir()
        (work / "late.parquet").write_bytes(b"late")
        late = _object(root, work / "late.parquet", True)
        _write_record(root, "d" * 40, "2026-10-20T10:00:00.000000Z", {
            "root": "acme/late",
            "records": [_record("acme/late", "dataframe", "late", "./late.parquet", late, True)],
        })
        assert not migrate.plan(root).unfinished
        migrate.run(root)
        store = FolderStore(root)
        assert store.has(late.content_hash) and store.verify() == []
        assert not (root / "tmp" / "migrate.jsonl").exists()

    def test_a_journal_a_sync_brought_before_the_moves_moves_and_removes_nothing(self, old_store, tmp_path, monkeypatch):
        """Found by a review: another machine had the journal that says "switched", and not yet what was moved."""
        root, hashes = old_store
        there = tmp_path / "there"
        shutil.copytree(root, there, symlinks=True)  # another machine's copy, before the moves arrive
        unlink = Path.unlink
        monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: None if self.name == "migrate.jsonl" else unlink(self, *a, **k))
        migrate.run(root)
        monkeypatch.setattr(Path, "unlink", unlink)
        # What the sync brought first: store.json and the journal
        shutil.copy(root / "store.json", there / "store.json")
        (there / "tmp").mkdir(exist_ok=True)
        shutil.copy(root / "tmp" / "migrate.jsonl", there / "tmp" / "migrate.jsonl")
        before = sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file())
        with pytest.raises(migrate.MigrateError, match="(?s)not there.*Wait for the sync"):
            migrate.run(there)
        assert sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file()) == before

    @pytest.mark.parametrize("over_v2", [False, True])
    def test_cut_short_at_any_line_of_the_switch_it_is_finished_next_time(self, old_store, tmp_path, over_v2):
        root, hashes = old_store
        if over_v2:
            (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v2"}) + "\n", encoding="utf-8")
        pristine = tmp_path / "pristine"
        shutil.copytree(root, pristine, symlinks=True)
        code = migrate._switch.__code__
        lines = sorted({line for _, line in dis.findlinestarts(code) if line and line > code.co_firstlineno})
        stopped = 0
        for line in lines:
            shutil.rmtree(root)
            shutil.copytree(pristine, root, symlinks=True)

            def tracer(frame, event, arg, line=line):
                if frame.f_code is not code:
                    return None

                def at(frame, event, arg):
                    if event == "line" and frame.f_lineno == line:
                        raise KeyboardInterrupt
                    return at

                return at

            sys.settrace(tracer)
            try:
                migrate.run(root)
            except KeyboardInterrupt:
                stopped += 1
            finally:
                sys.settrace(None)
            migrate.run(root)
            _all_there(root, hashes)
        assert stopped >= 10


class TestWhatTheFifthReviewFound:
    """gc refuses a store a migrate has not finished: what it refuses, a migrate must be able to clear."""

    @staticmethod
    def _store(root: Path, *args: str):
        return CliRunner().invoke(main, ["store", *args], env={"CHARTBOOK_STORE": str(root)})

    @pytest.mark.parametrize("left", [
        "objects/",
        "objects/.DS_Store",
        "objects/desktop.ini",
        "objects/sha256/ab/",
        "snapshots/" + "a" * 40 + "/",
        "snapshots/" + "a" * 40 + "/_top/.DS_Store",
        "snapshots/" + "a" * 40 + "/_top/20261001T100000.000000Z (1).json",
    ])
    def test_what_a_sync_leaves_of_the_old_folders_never_stops_gc_for_good(self, old_store, left):
        root, hashes = old_store
        migrate.run(root)
        target = root / left
        if left.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        if self._store(root, "gc", "--dry-run").exit_code != 0:
            said = self._store(root, "migrate", "--yes")
            assert said.exit_code == 0, said.output
        said = self._store(root, "gc", "--dry-run")
        assert said.exit_code == 0, said.output
        store = FolderStore(root)
        assert store.verify() == [] and all(store.has(content_hash) for content_hash in hashes.values())

    def test_what_a_desktop_leaves_in_a_new_store_is_not_0_2s(self, tmp_path):
        root = tmp_path / "store"
        (tmp_path / "x.txt").write_text("x", encoding="utf-8")
        FolderStore(root).put(tmp_path / "x.txt")
        for left in ("desktop.ini", ".DS_Store", "snapshots/desktop.ini", "objects/.DS_Store", "objects (1)/x",
                     "snapshots/" + "0" * 40 + " (1)/x", "snapshots/" + "a" * 40 + "/Thumbs.db"):
            (root / left).parent.mkdir(parents=True, exist_ok=True)
            (root / left).write_text("x", encoding="utf-8")
        assert not holds_v1(root)
        FolderStore(root).tidy(dry_run=True)

    def test_a_journal_left_with_nothing_of_0_2s_is_cleared_by_a_migrate(self, old_store):
        root, hashes = old_store
        migrate.run(root)
        (root / "tmp" / "migrate.jsonl").write_text('{"from": "objects/x", "to": "pipelines/y"}\n', encoding="utf-8")
        assert self._store(root, "gc", "--dry-run").exit_code != 0
        found = migrate.plan(root)
        assert found.needed and found.unfinished
        migrate.run(root)
        assert self._store(root, "gc", "--dry-run").exit_code == 0
        _all_there(root, hashes)

    def test_a_0_2_object_come_after_a_switch_is_moved_not_removed(self, old_store, tmp_path, monkeypatch):
        """Found by a review: a 0.2 machine's pin (an object, no record) went with the old folders when a journal was left."""
        root, hashes = old_store
        unlink = Path.unlink
        monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: None if self.name == "migrate.jsonl" else unlink(self, *a, **k))
        migrate.run(root)
        monkeypatch.setattr(Path, "unlink", unlink)
        work = tmp_path / "late"
        work.mkdir()
        (work / "pin.parquet").write_bytes(b"late pin")
        late = _object(root, work / "pin.parquet", True)
        (root / "roots" / ("1" * 32 + ".json")).write_text(
            json.dumps({"lockfile": str(work / "chartbook.lock"), "hashes": [late.content_hash]}), encoding="utf-8"
        )
        assert not migrate.plan(root).unfinished
        migrate.run(root)
        store = FolderStore(root)
        assert store.has(late.content_hash) and store.verify() == []
