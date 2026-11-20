"""The mover on a richer store of 0.5 (``tests/rich_store_of_0_5.py``), and what its eighth review found.

Stopped after every step and at every rename of the disk, a move ends in
the tree an uninterrupted one makes. And eight rules, each with the case
that broke it: the snapshot the others build on does not change once a
move has begun; nothing is renamed onto a file that is there; the aside
folder may have been removed; a file already where a rename goes is said;
a part the reader passes over is passed over; a file where the move makes
a folder is found before the first step; what is missing is said after
the move too; and no line says to take the new folders out of the store.
"""

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, migrate_0_5
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.store import StoreError
from tests.rich_store_of_0_5 import (
    COMMIT,
    OWN,
    D,
    Stop,
    contents,
    empty_store,
    folder_of,
    not_its_own,
    fresh,
    put,
    read_through,
    record,
    rich,
    rmtree,
    stop_after,
    tree_of,
    watch,
)

ASIDE = "_chartbook/left-by-0.5"


@pytest.fixture
def v2(tmp_path, monkeypatch):
    """The richer store of 0.5, as the store of the commands typed; and its snapshots' folder names."""
    root = empty_store(tmp_path)
    names = rich(root)
    monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
    return root, names


@pytest.fixture
def moved(v2, tmp_path):
    """The same store once moved; a copy of it as it was; and the names."""
    root, names = v2
    was = tmp_path / "was"
    shutil.copytree(root, was)
    migrate_0_5.run(root)
    store_module._read_records.clear()
    return root, was, names


def typed(*words, input=None):
    result = CliRunner().invoke(main, list(words), input=input)
    assert result.exception is None or isinstance(result.exception, SystemExit), (words, repr(result.exception))
    return result, result.output.replace("\n", " ")


def cut_at(root: Path, wanted) -> None:
    """Run a move and stop it after the last step that *wanted* picks."""
    steps = migrate_0_5.plan(root).steps
    at = max(number for number, step in enumerate(steps, 1) if wanted(step))
    with pytest.raises(Stop):
        migrate_0_5.run(root, after_step=stop_after(at))
    store_module._read_records.clear()


class TestTheRicherStoreMovedWhole:
    def test_every_asset_reads_as_before_and_each_snapshot_has_its_kind(self, v2, tmp_path):
        root, names = v2
        before = read_through(root)
        assert sorted(value for value in before.values() if len(value) != 64) == ["FileNotFoundError"] * 2  # the two missing files
        migrate_0_5.run(root)
        assert read_through(root) == before
        kinds = {
            (kept.pipeline, kept.folder.name): "increment" if kept.increment else ("pin" if kept.made_by == "pin" else "complete")
            for kept in fresh(root).records()
        }
        assert kinds == {
            ("acme/p", names["s1"]): "increment", ("acme/p", names["s2"]): "increment", ("acme/p", names["s3"]): "complete",
            ("acme/p", names["p4"]): "pin", ("acme/p", names["p5"]): "pin",
            ("acme/q", names["q1"]): "pin", ("acme/q", names["q2"]): "pin",
            ("acme/r", names["r1"]): "pin", ("acme/r", names["r2"]): "increment", ("acme/r", names["r3"]): "complete",
        }
        # Nothing a record names is aside; the mark the move from 0.2 left is, with all else that was not moved in
        aside = sorted(p.relative_to(root).as_posix() for p in (root / ASIDE).rglob("*") if p.is_file())
        assert not [name for name in aside if name.endswith((".parquet", ".zmeta"))], aside
        assert f"{ASIDE}/snapshots/{'0' * 40}/MOVED.txt" in aside and f"{ASIDE}/README.txt" in aside
        assert not (root / "snapshots" / ("0" * 40)).exists()


class TestStoppedAnywhereTheRicherStoreEndsAsTheUninterruptedOne:
    @pytest.fixture
    def store(self, tmp_path):
        root = empty_store(tmp_path)
        rich(root)
        whole = tmp_path / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        return root, whole

    def test_after_every_step_with_the_journal_kept_and_with_it_deleted(self, store, tmp_path):
        root, whole = store
        wanted, before = tree_of(whole), read_through(root)
        wrong = []
        for number in range(1, len(migrate_0_5.plan(root).steps) + 2):
            cut = tmp_path / "cut"
            shutil.copytree(root, cut)
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=stop_after(number))
            for journal in (True, False):
                again = tmp_path / "again"
                shutil.copytree(cut, again)
                if not journal and (again / migrate_0_5.JOURNAL).is_file():
                    (again / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                migrate_0_5.run(again)
                if tree_of(again) != wanted:
                    wrong.append((number, journal, sorted(set(tree_of(again).items()) ^ set(wanted.items()))[:6]))
                elif read_through(again) != before:
                    wrong.append((number, journal, "reads differ"))
                rmtree(again)
            rmtree(cut)
        assert not wrong, json.dumps(wrong, indent=1)

    @pytest.mark.parametrize("when", ["before", "after"])
    def test_killed_at_every_rename_the_disk_is_asked_for(self, store, tmp_path, monkeypatch, when):
        """Finer than a step: the process dies just before, or just after, each os.replace of a move (its journal's too)."""
        root, whole = store
        wanted, before = tree_of(whole), read_through(root)
        real = os.replace
        counted = tmp_path / "counted"
        shutil.copytree(root, counted)
        calls = []
        monkeypatch.setattr(os, "replace", lambda a, b: (calls.append(1), real(a, b))[1])
        migrate_0_5.run(counted)
        monkeypatch.setattr(os, "replace", real)
        rmtree(counted)
        wrong = []
        for number in range(1, len(calls) + 1):
            for journal in (True, False):
                cut = tmp_path / "cut"
                shutil.copytree(root, cut)
                seen = []

                def dying(a, b, number=number, seen=seen):
                    seen.append(1)
                    if len(seen) == number and when == "before":
                        raise Stop()
                    real(a, b)
                    if len(seen) == number and when == "after":
                        raise Stop()

                store_module._read_records.clear()
                monkeypatch.setattr(os, "replace", dying)
                try:
                    with pytest.raises(Stop):
                        migrate_0_5.run(cut)
                finally:
                    monkeypatch.setattr(os, "replace", real)
                if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                    (cut / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                migrate_0_5.run(cut)
                if tree_of(cut) != wanted:
                    wrong.append((number, journal, sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
                elif read_through(cut) != before:
                    wrong.append((number, journal, "reads differ"))
                rmtree(cut)
        assert not wrong, f"{len(wrong)} of {2 * len(calls)}: " + json.dumps(wrong[:8], indent=1)


class TestTheOneTheOthersBuildOnDoesNotChangeOnceAMoveHasBegun:
    def test_a_newer_snapshot_that_arrives_after_a_cut_is_an_increment_on_it_and_nothing_read_before_is_lost(self, tmp_path, monkeypatch):
        root = empty_store(tmp_path)
        a, b, c = b"a" * 500, b"b" * 600, b"c" * 700
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/a.parquet", a)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", a, None, None)])
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/b.parquet", b)
        record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", a, s1, None), ("_data/b.parquet", b, None, None)])
        before = read_through(root)
        cut_at(root, lambda step: step.op == "rename")  # every rename done, and no record written yet
        assert (root / "snapshots" / "acme+p" / s2).is_dir() and not (root / "snapshots" / "acme+p" / s2 / "_chartbook").exists()
        # A machine still on 0.5, which the sync has not brought the journal, makes the next snapshot of the pipeline
        s3 = folder_of("2025-12-01", "c")
        put(root, "acme+p", s3, "_data/c.parquet", c)
        record(root, "acme/p", "2025-12-01", "c", [("_data/a.parquet", a, s1, None), ("_data/c.parquet", c, None, None)])
        assert migrate_0_5.plan(root).missing == []
        done = migrate_0_5.run(root)
        after = read_through(root)
        assert {key: after.get(key) for key in before} == before and done.missing == []
        kept = {record.folder.name: record for record in fresh(root).records()}
        assert not kept[s2].increment and kept[s1].builds_on == s2 and kept[s3].builds_on == s2  # the one that arrived, like any other
        assert after[("acme/p", s3, "_data/c.parquet")] == hashlib.sha256(c).hexdigest() and after[("acme/p", s3, "_data/a.parquet")] == hashlib.sha256(a).hexdigest()
        # No file of the store is left under a folder with no record, for `store gc` to remove two days on
        stranded = [p for tree in ("snapshots", "increments") for p in (root / tree).rglob("*.parquet") if not (p.parents[1] / "_chartbook" / "snapshot.json").is_file()]
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 2 * 86400)
        assert stranded == [] and fresh(root).tidy(dry_run=True) == [] and fresh(root).verify() == []


class TestACopyIsMadeFromWhereTheFileIs:
    """A plan made after a cut may put another place first for a file than the plan that renamed it: the file is not called missing, it is copied from where it is."""

    def _two(self, tmp_path):
        root = empty_store(tmp_path)
        x, b = b"x" * 300, b"b" * 600
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/x.parquet", x)
        record(root, "acme/p", "2025-10-01", "a", [("_data/x.parquet", x, None, None)])
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/b.parquet", b)
        record(root, "acme/p", "2025-11-01", "b", [("_data/b.parquet", b, None, None)])
        return root, x, s1, s2

    def test_the_record_of_an_older_snapshot_that_a_sync_brings_after_a_cut(self, tmp_path):
        root, x, s1, s2 = self._two(tmp_path)
        before = read_through(root)
        cut_at(root, lambda step: step.op == "rename")
        assert (root / "increments" / "acme+p" / s1 / "_data" / "x.parquet").is_file()
        s0 = record(root, "acme/p", "2025-09-01", "c", [("_data/x.parquet", x, s1, None)])  # it shares the file, and sorts before its holder
        assert migrate_0_5.plan(root).missing == []
        done = migrate_0_5.run(root)
        after = read_through(root)
        assert done.missing == [] and {key: after[key] for key in before} == before
        assert after[("acme/p", s0, "_data/x.parquet")] == hashlib.sha256(x).hexdigest() and fresh(root).verify() == []

    def test_a_newer_snapshot_that_arrives_before_the_one_the_others_build_on_has_a_folder(self, tmp_path):
        """Cut after one rename into increments/, and none yet into snapshots/: the one that arrived is the newest, and is complete."""
        root, x, s1, s2 = self._two(tmp_path)
        before = read_through(root)
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=stop_after(1))
        store_module._read_records.clear()
        assert (root / "increments" / "acme+p" / s1 / "_data" / "x.parquet").is_file() and not (root / "snapshots" / "acme+p").exists()
        c = b"c" * 700
        s3 = folder_of("2025-12-01", "c")
        put(root, "acme+p", s3, "_data/c.parquet", c)
        record(root, "acme/p", "2025-12-01", "c", [("_data/x.parquet", x, s1, None), ("_data/c.parquet", c, None, None)])
        assert migrate_0_5.plan(root).missing == []
        done = migrate_0_5.run(root)
        after = read_through(root)
        assert done.missing == [] and {key: after[key] for key in before} == before
        kept = {record.folder.name: record for record in fresh(root).records()}
        assert not kept[s3].increment and kept[s1].builds_on == s3 and kept[s2].builds_on == s3
        assert after[("acme/p", s3, "_data/x.parquet")] == hashlib.sha256(x).hexdigest() and fresh(root).verify() == []


class TestNothingIsRenamedOntoAFileThatIsThere:
    def test_on_a_moved_store_a_late_object_no_pipeline_owns_goes_aside_with_pipelines_and_the_stores_own_stays(self, moved):
        root, _, _ = moved
        only = b"an object no pipeline owns, which a lockfile pins: these bytes are nowhere else" * 20
        name = hashlib.sha256(only).hexdigest()
        kept = root / "_chartbook" / "unowned" / name / "pinned.parquet"
        kept.parent.mkdir(parents=True)
        kept.write_bytes(only)
        os.utime(kept, (time.time() - 86400, time.time() - 86400))
        other = hashlib.sha256(b"other").hexdigest()
        for late, data in ((f"{name}/pinned.parquet", only[:17]), (f"{other}/o.bin", b"other")):  # one the store has, half synced; one it has not
            (root / "pipelines" / "+unowned" / late).parent.mkdir(parents=True)
            (root / "pipelines" / "+unowned" / late).write_bytes(data)
        before = contents(root)
        dry, said_dry = typed("store", "migrate", "--dry-run")
        assert "and 2 file(s) that no record names" in said_dry and contents(root) == before
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0, result.output
        assert kept.read_bytes() == only and not [paths for key, paths in before.items() if key not in contents(root)]
        # Nothing under a late pipelines/ is moved in, an object neither: both are aside, whole
        assert not (root / "_chartbook" / "unowned" / other).exists()
        assert (root / ASIDE / "pipelines (2)" / "+unowned" / name / "pinned.parquet").read_bytes() == only[:17]
        assert (root / ASIDE / "pipelines (2)" / "+unowned" / other / "o.bin").read_bytes() == b"other"
        assert f"is kept at {ASIDE}/pipelines (2)" in said

    def test_in_a_first_move_gone_on_with_a_late_object_does_not_take_the_place_of_the_one_moved_in(self, tmp_path):
        """Cut short after +unowned went under _chartbook/; a machine of 0.5 then puts the object again, half synced."""
        root = empty_store(tmp_path)
        rich(root)
        planned = migrate_0_5.plan(root).aside
        cut_at(root, lambda step: step.op == "movedir" and step.source == "pipelines/+unowned")
        name = hashlib.sha256(D).hexdigest()
        kept = root / "_chartbook" / "unowned" / name / "q.parquet"
        late = root / "pipelines" / "+unowned" / name / "q.parquet"
        late.parent.mkdir(parents=True)
        late.write_bytes(D[:17])
        os.utime(late, (time.time() + 5, time.time() + 5))
        before = contents(root)
        assert migrate_0_5.plan(root).aside == planned + 1  # the late object, which will not be moved in, is counted with what goes aside
        done = migrate_0_5.run(root)
        lost = [paths for key, paths in before.items() if key not in contents(root) and not any(p in OWN for p in paths)]
        assert kept.read_bytes() == D and not lost, lost
        assert done.kept == f"{ASIDE}/pipelines" and (root / done.kept / "+unowned" / name / "q.parquet").read_bytes() == D[:17]

    @pytest.mark.parametrize("late_is", ["later", "earlier"])
    def test_of_two_notes_of_one_lockfile_the_store_keeps_the_later_and_the_other_is_aside(self, moved, late_is):
        root, _, _ = moved
        name = "ab" * 16 + ".json"
        there = root / "_chartbook" / "roots" / name
        there.write_text('{"the stores": "own, written after the move"}\n', encoding="utf-8", newline="\n")
        os.utime(there, (time.time() - 100, time.time() - 100))
        (root / "roots").mkdir()
        late = root / "roots" / name
        late.write_text('{"late": "from a machine of 0.5"}\n', encoding="utf-8", newline="\n")
        if late_is == "earlier":
            os.utime(late, (time.time() - 7200, time.time() - 7200))
        own, of_0_5 = there.read_bytes(), late.read_bytes()
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and not (root / "roots").exists(), result.output
        if late_is == "later":
            assert there.read_bytes() == of_0_5 and (root / ASIDE / "_chartbook" / "roots" / name).read_bytes() == own
        else:
            assert there.read_bytes() == own and (root / ASIDE / "roots" / name).read_bytes() == of_0_5
        assert {p.read_bytes() for p in root.rglob(name)} == {own, of_0_5}  # neither is destroyed
        assert fresh(root).verify() is not None

    def test_the_other_note_goes_aside_before_the_later_one_is_moved_in(self, moved, monkeypatch):
        root, _, _ = moved
        name = "ab" * 16 + ".json"
        os.utime(root / "_chartbook" / "roots" / name, (time.time() - 100, time.time() - 100))
        (root / "roots").mkdir()
        (root / "roots" / name).write_text('{"late": 1}\n', encoding="utf-8", newline="\n")
        made, real = [], os.replace
        monkeypatch.setattr(os, "replace", lambda a, b: (made.append((Path(a).relative_to(root).as_posix(), Path(b).relative_to(root).as_posix())), real(a, b))[1])
        migrate_0_5.run(root)
        moves = [pair for pair in made if name in pair[0]]
        assert moves == [(f"_chartbook/roots/{name}", f"{ASIDE}/_chartbook/roots/{name}"), (f"roots/{name}", f"_chartbook/roots/{name}")]

    def test_an_origin_that_is_there_stays_and_the_late_one_goes_aside(self, moved):
        root, _, _ = moved
        there = root / "_chartbook" / "origins" / COMMIT["a"] / "acme+p.txt"
        late = root / "origins" / COMMIT["a"] / "acme+p.txt"
        late.parent.mkdir(parents=True)
        late.write_text("/elsewhere\n", encoding="utf-8", newline="\n")
        os.utime(late, (time.time() + 60, time.time() + 60))  # later, and an origin all the same
        new = root / "origins" / COMMIT["b"] / "acme+p.txt"
        new.parent.mkdir(parents=True)
        new.write_text("/new\n", encoding="utf-8", newline="\n")
        migrate_0_5.run(root)
        assert there.read_text(encoding="utf-8") == "/somewhere\n"
        assert (root / ASIDE / "origins" / COMMIT["a"] / "acme+p.txt").read_text(encoding="utf-8") == "/elsewhere\n"
        assert (root / "_chartbook" / "origins" / COMMIT["b"] / "acme+p.txt").read_text(encoding="utf-8") == "/new\n"  # one the store had not is moved in


    def test_a_record_of_an_earlier_plan_is_put_aside_before_the_one_of_this_plan_is_written(self, v2, tmp_path):
        """A file the base and an increment both name is not there when the move begins, and arrives after a cut: the increment's record changes, and the earlier one is not written over."""
        root, names = v2
        before = read_through(root)
        late = root / "pipelines" / "acme+r" / names["r1"] / "_data" / "f.parquet"
        os.replace(late, tmp_path / "not-synced-yet")
        cut_at(root, lambda step: step.op == "write")
        record_of = root / "increments" / "acme+r" / names["r2"] / "_chartbook" / "snapshot.json"
        earlier = record_of.read_bytes()
        os.replace(tmp_path / "not-synced-yet", late)
        made, real = [], os.replace
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(os, "replace", lambda a, b: (made.append((os.path.lexists(b), Path(b).relative_to(root).as_posix())), real(a, b))[1])
            migrate_0_5.run(root)
        assert [place for there, place in made if there and place not in OWN] == []  # no rename onto a path that is there
        assert record_of.read_bytes() != earlier and (root / ASIDE / "increments" / "acme+r" / names["r2"] / "_chartbook" / "snapshot.json").read_bytes() == earlier
        assert read_through(root) == before and not [problem for problem in fresh(root).verify() if "acme/r" in problem.format()]

class TestNothingIsRemovedOrWrittenOver:
    """Every remover, every rename onto a path that is there and every file opened for writing over one, across a move: only the journal, the marker and the move's own temporary files."""

    def test_in_a_first_move(self, v2, monkeypatch):
        root, _ = v2
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert not_its_own(gone) == [] and ("unlink", "_chartbook/move-to-v3.jsonl") in gone

    def test_in_a_move_cut_short_and_gone_on_with(self, v2, tmp_path, monkeypatch):
        root, _ = v2
        found = {}
        for number in range(1, len(migrate_0_5.plan(root).steps) + 2, 3):
            cut = tmp_path / "cut"
            shutil.copytree(root, cut)
            gone: list = []
            with monkeypatch.context() as patch:
                watch(patch, cut, gone)
                with pytest.raises(Stop):
                    migrate_0_5.run(cut, after_step=stop_after(number))
                store_module._read_records.clear()
                migrate_0_5.run(cut)
            if not_its_own(gone):
                found[number] = not_its_own(gone)  # a record written already is not written again, so not even those
            rmtree(cut)
        assert not found, found

    def test_on_a_moved_store_with_late_folders_at_its_top(self, moved, monkeypatch):
        root, _, _ = moved
        later = time.time() + 30
        name = hashlib.sha256(D).hexdigest()
        # A note of a lockfile, a note of an origin and an object no pipeline owns: each under a name the store has
        for late, there, data in (
            (root / "roots" / ("ab" * 16 + ".json"), root / "_chartbook" / "roots" / ("ab" * 16 + ".json"), b'{"late": 1}\n'),
            (root / "origins" / COMMIT["a"] / "acme+p.txt", root / "_chartbook" / "origins" / COMMIT["a"] / "acme+p.txt", b"/elsewhere\n"),
            (root / "pipelines" / "+unowned" / name / "q.parquet", root / "_chartbook" / "unowned" / name / "q.parquet", D[:9]),
        ):
            assert there.is_file(), there
            late.parent.mkdir(parents=True, exist_ok=True)
            late.write_bytes(data)
            os.utime(late, (later, later))
        before = contents(root)
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert not_its_own(gone) == []
        assert not [paths for key, paths in before.items() if key not in contents(root)]


class TestTheAsideFolderMayHaveBeenRemovedAsTheLastLineAllows:
    @pytest.mark.parametrize("removed", [ASIDE, f"{ASIDE}/pipelines"])
    @pytest.mark.parametrize("late", ["roots", "tmp", "pipelines/+unowned"])
    def test_the_command_run_again_finishes_and_twice(self, moved, removed, late):
        root, _, _ = moved
        rmtree(root / removed)  # "it may be removed once the move has been checked"
        if late == "pipelines/+unowned":
            other = root / late / hashlib.sha256(b"other").hexdigest()
            other.mkdir(parents=True)
            (other / "o.bin").write_bytes(b"other")
        else:
            (root / late).mkdir()
            (root / late / ("cd" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
            os.utime(root / late / ("cd" * 16 + ".json"), (time.time() - 7200, time.time() - 7200))
        first, said = typed("store", "migrate", "--yes")
        assert first.exit_code == 0 and not (root / late.split("/")[0]).exists(), said
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0 and "nothing to move" in said
        assert fresh(root).verify() is not None  # and the store opens


class TestAFileAlreadyWhereARenameGoes:
    """A move on another machine half arrived, or a sync put a file back at its old place: the rename is not made, and that is said."""

    @pytest.mark.parametrize("size", ["the same size", "another size"])
    def test_what_is_in_place_stays_the_one_at_the_old_place_goes_aside_and_both_are_said(self, tmp_path, monkeypatch, size):
        root = empty_store(tmp_path)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        f = b"f" * 2000
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/f.parquet", f)
        record(root, "acme/p", "2025-10-01", "a", [("_data/f.parquet", f, None, None)])
        other = b"?" * (2000 if size == "the same size" else 400)
        put(root, "acme+p", s1, "_data/f.parquet", other, tree="snapshots")
        place, old = f"snapshots/acme+p/{s1}/_data/f.parquet", f"{ASIDE}/pipelines/acme+p/{s1}/_data/f.parquet"
        found = migrate_0_5.plan(root)
        assert found.in_place == [(old, place, 2000, len(other))] and found.late == [old] and found.missing == []
        sizes = "" if size == "the same size" else " (400 bytes in place, 2.0 KB at the old place)"
        line = (
            f"1 file(s) a record names {{are}} not moved, a file being where each goes already: {place}{sizes}. What is in "
            f"place stays, and the file at the old place {{goes}} aside with the old folder. `chartbook store verify` says "
            f"whether what is in place is right."
        )
        dry, said = typed("store", "migrate", "--dry-run")
        assert dry.exit_code == 0 and line.format(are="are", goes="goes") in said and "arrived for a snapshot" not in said, said
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and line.format(are="were", goes="went") in said, said  # it does not stop the move
        assert (root / place).read_bytes() == other and (root / old).read_bytes() == f
        problems = [problem.format() for problem in fresh(root).verify()]
        assert len(problems) == 1 and "_data/f.parquet" in problems[0], problems  # and `store verify` says what is in place is not right

    def test_one_that_arrives_at_its_old_place_while_the_move_runs_is_said_too(self, v2):
        """A sync puts a file back where 0.5 kept it, after its rename: found in the last look before the old folder goes aside."""
        root, names = v2
        steps = migrate_0_5.plan(root).steps
        rename = next(step for step in steps if step.op == "rename" and step.source.endswith("new.parquet"))
        after = max(number for number, step in enumerate(steps, 1) if step.op in ("write", "note"))

        def arrives(done: int) -> None:
            if done == after:
                (root / rename.source).write_bytes(b"the same file, put back by a sync")

        done = migrate_0_5.run(root, after_step=arrives)
        old = f"{done.kept}/{rename.source.split('/', 1)[1]}"
        assert done.in_place == [(old, rename.target, 33, 300)] and old in done.late
        assert (root / old).read_bytes() == b"the same file, put back by a sync"


class TestAPartTheReaderPassesOver:
    @pytest.mark.parametrize("said", [["sha256:" + "0" * 64], {"sha256": "0" * 64}])
    def test_a_hash_that_is_a_list_or_a_table_is_passed_over_as_the_stores_reader_passes_it_over(self, tmp_path, monkeypatch, said):
        root = empty_store(tmp_path)
        data = b"x" * 10
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/f.parquet", data)
        record(root, "acme/p", "2025-10-01", "a", [("_data/f.parquet", data, None, None)])
        file = root / "pipelines" / "acme+p" / s1 / "_chartbook" / "snapshot.json"
        document = json.loads(file.read_text(encoding="utf-8"))
        document["records"].append({"id": "acme/p:dataframe:other", "kind": "dataframe", "content_hash": said, "size_bytes": 10})
        file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        assert fresh(root).verify() == []  # the store reads this record, and passes over that part
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        result, _ = typed("store", "migrate", "--yes")
        assert result.exit_code == 0, result.output
        moved = json.loads((root / "snapshots" / "acme+p" / s1 / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
        assert moved["records"][1] == document["records"][1] and fresh(root).verify() == []  # carried as it was


class TestAFileWhereTheMoveMakesAFolder:
    @pytest.mark.parametrize("in_the_way", [ASIDE, "increments", "snapshots/acme+p", "_chartbook", f"increments/acme+p/{folder_of('2025-10-01', 'a')}"])
    @pytest.mark.parametrize("as_what", ["a file", "a link"])
    def test_it_is_found_before_the_first_step_and_said_with_what_to_do(self, v2, tmp_path, in_the_way, as_what):
        root, _ = v2
        (root / in_the_way).parent.mkdir(parents=True, exist_ok=True)
        if as_what == "a file":
            (root / in_the_way).write_text("a file, not a folder\n", encoding="utf-8", newline="\n")
        else:
            (tmp_path / "elsewhere").mkdir()
            try:
                os.symlink(tmp_path / "elsewhere", root / in_the_way, target_is_directory=True)
            except OSError:
                pytest.skip("this user may not make a link here")
        before = tree_of(root)
        with pytest.raises(migrate_0_5.MoveError) as stopped:
            migrate_0_5.run(root)
        assert str(stopped.value) == (
            f"{root / in_the_way} is a file, or a link, where the move makes a folder: the store is not moved. Move it out "
            f"of the store, and run this again."
        )
        assert tree_of(root) == before and not (root / migrate_0_5.JOURNAL).is_file()
        for words in (["store", "migrate", "--dry-run"], ["store", "migrate", "--yes"]):
            result, said = typed(*words)
            assert result.exit_code == 1 and "where the move makes a folder" in said and tree_of(root) == before
        # The way out, carried out
        os.replace(root / in_the_way, tmp_path / "moved-out")
        assert typed("store", "migrate", "--yes")[0].exit_code == 0 and len(fresh(root).verify()) == 2  # the two files missing as before


class TestWhatIsMissingIsSaidAfterTheMoveToo:
    MISSING = "2 file(s) a record names are missing or of another size, as before the move: "

    def _line(self, said: str) -> str:
        return said[said.index(self.MISSING):].split(". ")[0]

    def test_the_last_lines_name_the_missing_files_as_the_dry_run_does(self, v2):
        root, names = v2
        found = migrate_0_5.plan(root)
        assert found.missing == [(names["s1"], "_data/lost.parquet"), (names["s3"], "_data/gone.parquet")]
        dry, said_dry = typed("store", "migrate", "--dry-run")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and self._line(said) == self._line(said_dry)
        assert self._line(said) == f"{self.MISSING}_data/lost.parquet ({names['s1']}), _data/gone.parquet ({names['s3']})"
        assert "If a sync is still bringing them, wait and run again." in said_dry
        assert "`chartbook store verify` names each. One that a sync brings later is not moved in: it goes aside with the rest when `chartbook store migrate` is run again." in said

    @pytest.mark.parametrize("journal", ["kept", "deleted"])
    def test_and_after_a_move_cut_short_and_gone_on_with(self, v2, journal):
        root, names = v2
        said_dry = typed("store", "migrate", "--dry-run")[1]
        cut_at(root, lambda step: step.op == "write")
        if journal == "deleted":
            (root / migrate_0_5.JOURNAL).unlink()
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and self._line(said) == self._line(said_dry), said

    def test_and_after_one_cut_short_just_before_the_marker_whose_journal_was_deleted(self, v2):
        root, names = v2
        wanted = migrate_0_5.plan(root).missing
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=stop_after(len(migrate_0_5.plan(root).steps)))  # the old folder is aside; store.json still says 0.5
        (root / migrate_0_5.JOURNAL).unlink()
        store_module._read_records.clear()
        assert migrate_0_5.run(root).missing == wanted

    def test_a_file_that_arrives_before_the_old_folder_goes_aside_is_not_called_missing_and_a_wrong_copy_of_it_is_named(self, v2, tmp_path):
        """The file two pins share is not there when the move is planned, and arrives with other bytes of its size: put in place in the last look, copied as it is, and named."""
        root, names = v2
        shared = root / "pipelines" / "acme+q" / names["q1"] / "_data" / "q.parquet"
        os.replace(shared, tmp_path / "not-synced-yet")
        found = migrate_0_5.plan(root)
        assert len(found.missing) == 4 and found.copied_as_is == []  # the two as before, and the one file of the two pins
        after = max(number for number, step in enumerate(found.steps, 1) if step.op in ("write", "note"))

        def arrives(done: int) -> None:
            if done == after:
                shared.write_bytes(b"?" * len(D))

        done = migrate_0_5.run(root, after_step=arrives)
        assert done.missing == [(names["s1"], "_data/lost.parquet"), (names["s3"], "_data/gone.parquet")]
        assert done.copied_as_is == [f"snapshots/acme+q/{names['q2']}/_data/q.parquet"]
        assert (root / "snapshots" / "acme+q" / names["q1"] / "_data" / "q.parquet").read_bytes() == b"?" * len(D)


class TestAMoveCutShortWhoseJournalWasRemoved:
    """A store.json that says 0.5, no journal, and both trees: what a move renamed is under the new ones and nowhere else."""

    GOES_ON = "Then run `chartbook store migrate`, which goes on from the folders as they are."

    @pytest.fixture
    def reader(self, tmp_path, monkeypatch):
        folder = tmp_path / "reader"
        folder.mkdir()
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"acme/p": {}}}), encoding="utf-8", newline="\n"
        )
        monkeypatch.chdir(folder)

    def test_every_other_command_says_to_wait_for_a_sync_and_run_the_move_which_then_finishes(self, v2, reader, tmp_path):
        root, _ = v2
        whole = tmp_path / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        cut_at(root, lambda step: step.op == "write")
        (root / migrate_0_5.JOURNAL).unlink()  # as the mover's own line says may be done
        before = tree_of(root)
        for words in (["store", "verify"], ["store", "info"], ["pin"], ["store", "gc", "--dry-run"], ["store", "ls"], ["ls", "versions"]):
            result, said = typed(*words)
            assert result.exit_code == 1 and self.GOES_ON in said, (words, said)
            assert "If a move may still be arriving by a sync, wait for the sync to finish." in said
            assert "out of it" not in said and "move snapshots/" not in said and "_chartbook/ out" not in said, (words, said)
        assert tree_of(root) == before
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and tree_of(root) == tree_of(whole), said

    def test_folders_under_increments_alone_say_the_same(self, v2):
        root, names = v2
        (root / "increments" / "acme+p" / names["s1"] / "_data").mkdir(parents=True)  # a move's first rename went there
        with pytest.raises(StoreError) as refused:
            fresh(root).records()
        assert str(refused.value) == (
            f"The store at {root} has a store.json that says 'chartbook/store/v2', the layout of ChartBook 0.5, and folders "
            f"laid out as this version lays them out ({root / 'increments' / 'acme+p' / names['s1']}): a move to this "
            f"version's layout that was cut short, or one on another machine that a sync is still bringing. It is neither "
            f"read nor written as it is. If a move may still be arriving by a sync, wait for the sync to finish. {self.GOES_ON}"
        )

    def test_with_no_store_json_either_it_says_to_put_one_back_and_run_the_move_which_then_finishes(self, v2, tmp_path):
        root, _ = v2
        whole = tmp_path / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        cut_at(root, lambda step: step.op == "write")
        (root / migrate_0_5.JOURNAL).unlink()
        (root / "store.json").unlink()
        for words in (["store", "verify"], ["store", "migrate", "--yes"]):
            result, said = typed(*words)
            assert result.exit_code == 1 and "has no store.json, and holds snapshots of both layouts" in said, (words, said)
            assert (
                "If the store, or a move of it to this version's layout, may still be arriving by a sync, wait for the sync to "
                'finish. If its store.json is lost for good, put one back that holds {"schema": "chartbook/store/v2"}. '
                + self.GOES_ON
            ) in said and "out of it" not in said
        # The way out, carried out
        (root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and tree_of(root) == tree_of(whole), said

    def test_no_line_of_the_store_or_the_mover_says_to_move_the_new_folders_out(self):
        import inspect

        for module in (store_module, migrate_0_5):
            source = inspect.getsource(module)
            assert "_chartbook/ out" not in source and "{OWN_DIR}/ out of it" not in source and "To part the two" not in source
