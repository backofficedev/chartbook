"""The mover after its second review (2026-11-20): each thing found, as a test of the rule that came of it, and what was attacked and held.

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout". The reviewer moved 1,600 drawn stores without interruption and
lost nothing readable; what it found is here, by rule:

- **P1** the move's temporaries are in a folder of its own, and nothing
  in a pipeline's folder is ever taken for one;
- **P2** a copy is made from the old place where the whole file is there;
- **P3** a file a copy must read that this user may not read is found
  before the first step;
- **P4** a missing file is told by its pipeline, its snapshot and its path;
- **P6** a file that is in place already is not counted as renamed, and a
  store that looks half moved with no journal is told to wait for a sync.
"""

import hashlib
import os
import random
import shutil
import stat
import string

import pytest
from click.testing import CliRunner

from chartbook import config, migrate_0_5
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.identity import validate_pipeline_id
from chartbook.store import pipeline_folder
from tests.fixtures import needs_symlinks
from tests.found_store_of_0_5 import facts_by_folder, reads_after, record_at, wide_store
from tests.rich_store_of_0_5 import Stop, empty_store, folder_of, not_its_own, put, record, rmtree, tree_of, watch

ASIDE = "_chartbook/left-by-0.5"
A, B, K, M, X = b"a" * 100, b"b" * 200, b"k" * 400, b"m" * 120, b"x" * 300

#: Where the modes of files keep nobody out: Windows, and any system for root
MODES_KEEP_NOBODY_OUT = os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0)


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    root = empty_store(work)
    monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
    return root


def typed(*words):
    result = CliRunner().invoke(main, list(words))
    assert result.exception is None or isinstance(result.exception, SystemExit), (words, repr(result.exception))
    return result


def _clear():
    store_module._read_records.clear()
    store_module._found_whole.clear()


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _removed_from_a_snapshot(gone: list) -> list:
    return [(how, path) for how, path in gone if path.startswith(("snapshots/", "increments/")) and how in ("unlink", "remove")]


class TestTheMovesTemporariesAreInAFolderOfItsOwn:
    """P1. A copy and a record were written first as ``<name>.moving`` beside where they go, and whatever was at that name was removed as a temporary the move had left."""

    def test_the_only_copy_of_a_file_a_record_names_is_not_removed_for_having_the_name_of_the_movers_temporary(self, work, monkeypatch):
        """A pipeline has ``_data/x.parquet`` and ``_data/x.parquet.moving``, in a store as 0.5 left it, whole.

        A folder that ``store gc`` cleared still keeps the one, for the
        newer of two snapshots a pin made; the older of the two was the
        first to have the other, and the newer names it there. The move
        renamed ``x.parquet.moving`` into the newer one's folder, the only
        copy of those bytes, and then copied ``x.parquet`` there under the
        name ``x.parquet.moving`` first: it removed the file, and the
        bytes were nowhere in the store.
        """
        root = empty_store(work)
        c0 = folder_of("2025-09-01", "h")
        put(root, "acme+q", c0, "_data/x.parquet.moving", M)
        cleared = root / "pipelines" / "acme+q" / c0 / "_chartbook" / "CLEARED.txt"
        cleared.parent.mkdir(parents=True)
        cleared.write_text("Cleared by `chartbook store gc`.\n", encoding="utf-8", newline="\n")
        q0 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q0, "_data/x.parquet", X)
        record(root, "acme/q", "2025-10-01", "e", [("_data/x.parquet", X, None, None)], made_by="pin")
        q = record(root, "acme/q", "2025-11-01", "f", [("_data/x.parquet.moving", M, c0, None), ("_data/x.parquet", X, q0, None)], made_by="pin")
        before = facts_by_folder(root)
        assert len(before) == 3 and all(at_place for _, _, at_place, _, _ in before.values())  # whole, to 0.5
        assert migrate_0_5.plan(root).missing == []
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            done = migrate_0_5.run(root)
        reads = reads_after(root)
        assert {key: got[0] for key, got in reads.items()} == {key: said[0] for key, said in before.items()}
        assert reads[("acme+q", q, "_data/x.parquet.moving")][0] == sha(M) and done.missing == []
        assert _removed_from_a_snapshot(gone) == [] and not_its_own(gone) == []
        assert not (root / migrate_0_5.MOVING).exists()

    def test_a_copy_of_a_file_a_record_names_is_not_removed_for_having_the_name_of_the_movers_temporary(self, work, monkeypatch):
        """The same, where the file removed was a copy the move had made a moment before.

        As 0.5 kept them: the oldest snapshot was the first to have the
        one file, the next the first to have the other, and a pin's
        snapshot names both there. The pin's folder is given a copy of each.
        """
        root = empty_store(work)
        s0 = folder_of("2025-09-01", "a")
        put(root, "acme+p", s0, "_data/x.parquet.moving", M)
        record(root, "acme/p", "2025-09-01", "a", [("_data/x.parquet.moving", M, None, None)])
        s1 = folder_of("2025-10-01", "b")
        put(root, "acme+p", s1, "_data/x.parquet", X)
        record(root, "acme/p", "2025-10-01", "b", [("_data/x.parquet.moving", M, s0, None), ("_data/x.parquet", X, None, None)])
        record(root, "acme/p", "2025-11-01", "c", [("_data/x.parquet.moving", M, s0, None), ("_data/x.parquet", X, s1, None)], made_by="pin")
        before = facts_by_folder(root)
        assert len(before) == 5 and all(at_place for _, _, at_place, _, _ in before.values())
        assert migrate_0_5.plan(root).missing == []
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            done = migrate_0_5.run(root)
        reads = reads_after(root)
        assert {key: got[0] for key, got in reads.items()} == {key: said[0] for key, said in before.items()} and done.missing == []
        assert _removed_from_a_snapshot(gone) == [] and not_its_own(gone) == []

    def test_a_file_named_as_the_old_temporaries_were_is_anyones_wherever_it_is(self, work, monkeypatch):
        """Beside a record, beside the store's marker and beside the journal: a file named ``<name>.moving`` is not the move's, and is as it was afterwards (aside with its folder, or where it was)."""
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        put(root, "acme+p", s, "_chartbook/snapshot.json.moving", b"somebody's")
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        (root / "store.json.moving").write_bytes(b"somebody's too")
        (root / "_chartbook").mkdir()
        (root / "_chartbook" / "move-to-v3.jsonl.moving").write_bytes(b"and this")
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert not_its_own(gone) == []
        assert (root / "store.json.moving").read_bytes() == b"somebody's too" and (root / "_chartbook" / "move-to-v3.jsonl.moving").read_bytes() == b"and this"
        assert (root / ASIDE / "pipelines" / "acme+p" / s / "_chartbook" / "snapshot.json.moving").read_bytes() == b"somebody's"

    def test_a_temporary_of_a_copy_cut_short_does_not_stay_once_the_file_has_come_by_itself(self, work, monkeypatch):
        """A move is killed while it copies a file (its temporary is written, not yet put in place). Before it is run again a sync brings the file itself to where the copy goes: the copy is found done, and what the first run left goes."""
        root = empty_store(work)
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, "_data/k.parquet", K)
        record(root, "acme/q", "2025-10-01", "e", [("_data/k.parquet", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [("_data/k.parquet", K, q1, None)], made_by="pin")
        target = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet"
        left = migrate_0_5._temporary_of(root, target)
        real = migrate_0_5.replace_when_free

        def killed_before_the_copy_is_put_in_place(source, to):
            if source == left:
                raise Stop()
            return real(source, to)

        with monkeypatch.context() as patch:
            patch.setattr(migrate_0_5, "replace_when_free", killed_before_the_copy_is_put_in_place)
            with pytest.raises(Stop):
                migrate_0_5.run(root)
        assert left.read_bytes() == K and not target.exists()
        target.write_bytes(K)  # the sync brings it
        _clear()
        steps = migrate_0_5.plan(root).steps
        copy = next(number for number, step in enumerate(steps, 1) if step.op == "copy" and root / step.target == target)
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == copy else None)
        assert not left.exists()  # gone when its step was found done, and not only at the end
        _clear()
        migrate_0_5.run(root)
        assert reads_after(root)[("acme+q", q2, "_data/k.parquet")][0] == sha(K)
        assert not (root / migrate_0_5.MOVING).exists() and list(root.rglob("*.moving")) == []

    def test_whatever_is_left_in_the_moves_own_folder_goes_when_the_move_ends(self, work):
        """A leftover there is a move's, whoever's run wrote it: one of a step of this plan, one of none (another machine's move, of a file since removed), and a read-only one."""
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        own = root / migrate_0_5.MOVING
        own.mkdir(parents=True)
        (own / ("0" * 24)).write_bytes(b"of no step of this plan")
        read_only = own / ("f" * 24)
        read_only.write_bytes(b"half a copy")
        os.chmod(read_only, stat.S_IREAD)
        migrate_0_5.run(root)
        assert not own.exists() and not (root / migrate_0_5.JOURNAL).exists()
        assert reads_after(root) == {("acme+p", s, "_data/a.parquet"): (sha(A), f"snapshots/acme+p/{s}/_data/a.parquet")}

    def test_cut_short_between_the_last_of_its_folder_and_its_journal_it_is_still_told_to_run_again(self, work, monkeypatch):
        """The folder of temporaries goes before the journal: a run killed between the two leaves the journal, which every command stops at, and the next run ends with neither."""
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        with monkeypatch.context() as patch:
            patch.setattr(migrate_0_5, "_clear_temporaries", lambda root: (_ for _ in ()).throw(Stop()))
            with pytest.raises(Stop):
                migrate_0_5.run(root)
        assert (root / migrate_0_5.JOURNAL).is_file() and migrate_0_5.to_move(root)
        _clear()
        migrate_0_5.run(root)
        assert not (root / migrate_0_5.JOURNAL).exists() and not (root / migrate_0_5.MOVING).exists()

    def test_the_temporary_of_a_copy_fits_wherever_the_copy_itself_fits(self, work, monkeypatch):
        """A file that two snapshots must each hold, whose path in the moved store is as long as this machine takes and no longer. Its temporary was the name and ``.moving``, seven characters past the limit, and ``check`` refused the store for them.

        Windows' rule stands in by the one name the mover asks it by, with
        the limit put at the longest path the moved store has.
        """
        root = empty_store(work)
        name = "k" * 60 + ".parquet"
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, f"_data/{name}", K)
        record(root, "acme/q", "2025-10-01", "e", [(f"_data/{name}", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [(f"_data/{name}", K, q1, None)], made_by="pin")
        longest = max(len(str(root / step.target)) for step in migrate_0_5.plan(root).steps if step.target)
        assert longest == len(str(root / "snapshots" / "acme+q" / q2 / "_data" / name))
        monkeypatch.setattr(migrate_0_5, "too_long", lambda path, folder=False: f"{path} is {len(str(path))} characters long, and Windows refuses it" if len(str(path)) > longest else None)
        migrate_0_5.run(root)
        assert reads_after(root)[("acme+q", q2, f"_data/{name}")][0] == sha(K)

    def test_a_temporary_is_shorter_than_the_path_of_any_file_of_a_snapshot(self, work):
        """So it fits wherever the moved store does: 42 characters under the store's top, against 45 for a file with a name of one letter in a pipeline with an ID of one."""
        root = empty_store(work)
        shortest = root / "snapshots" / "a" / folder_of("2025-10-01", "a") / "x"
        temporary = migrate_0_5._temporary_of(root, shortest)
        assert len(temporary.relative_to(root).as_posix()) == 42 < len(shortest.relative_to(root).as_posix()) == 45

    def test_a_file_where_the_moves_own_folder_goes_is_found_before_the_first_step(self, work):
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        (root / "_chartbook").mkdir()
        (root / migrate_0_5.MOVING).write_bytes(b"a file of this name, somebody's")
        before = tree_of(root)
        with pytest.raises(migrate_0_5.MoveError, match="is a file, or a link, where the move makes a folder"):
            migrate_0_5.run(root)
        assert tree_of(root) == before

    def test_two_long_names_in_one_folder_each_have_a_temporary_of_their_own_and_one_left_by_a_kill_goes(self, work, monkeypatch):
        """Two files with names of 251 characters, in one folder, that two snapshots must each hold. Killed before either copy is put in place, the move is run again: both files are there, and no temporary is."""
        root = empty_store(work)
        names = ["k" * 243 + ".parquet", "k" * 242 + "j.parquet"]
        q1 = folder_of("2025-10-01", "e")
        try:
            for index, name in enumerate(names):
                put(root, "acme+q", q1, f"_data/{name}", K + bytes([index]))
        except OSError:
            pytest.skip("this disk does not take a name of 251 characters")
        entries = [(f"_data/{name}", K + bytes([index]), None, None) for index, name in enumerate(names)]
        record(root, "acme/q", "2025-10-01", "e", entries, made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [(path, data, q1, None) for path, data, _, _ in entries], made_by="pin")
        folder = root / "snapshots" / "acme+q" / q2 / "_data"
        temporaries = {migrate_0_5._temporary_of(root, folder / name) for name in names}
        assert len(temporaries) == 2
        real = migrate_0_5.replace_when_free
        for kill_at in (1, 2):
            cut = work / f"cut-{kill_at}"
            shutil.copytree(root, cut)
            seen = []

            def killed(source, target, kill_at=kill_at, seen=seen, cut=cut):
                if source.parent == cut / migrate_0_5.MOVING and "_data" in target.parts:
                    seen.append(1)
                    if len(seen) == kill_at:
                        raise Stop()
                return real(source, target)

            _clear()
            with monkeypatch.context() as patch:
                patch.setattr(migrate_0_5, "replace_when_free", killed)
                with pytest.raises(Stop):
                    migrate_0_5.run(cut)
            left = [path for path in (cut / migrate_0_5.MOVING).iterdir() if path.stat().st_size == len(K) + 1]
            assert len(left) == 1
            _clear()
            migrate_0_5.run(cut)
            assert not (cut / migrate_0_5.MOVING).exists()
            there = cut / "snapshots" / "acme+q" / q2 / "_data"
            assert [(there / name).read_bytes() for name in names] == [K + b"\x00", K + b"\x01"]
            rmtree(cut)


class TestACopyIsMadeFromTheOldPlaceWhereTheWholeFileIsThere:
    """P2. A file that has taken the place a record's file goes to stays; and a copy was made from it, whatever its bytes, while the whole file was at the old place."""

    def _store(self, work, in_place: bytes):
        root = empty_store(work)
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        p3 = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, s2, None)], made_by="pin")
        put(root, "acme+p", s2, "_data/k.parquet", in_place, tree="snapshots")
        return root, s2, p3

    def test_a_copy_is_not_made_from_other_bytes_in_the_new_tree_while_the_old_place_holds_the_file(self, work):
        """The newest snapshot keeps K at its old place, whole, and a pin's snapshot names it there: 0.5 read both. Where the newest one's file goes there is a file of K's size and other bytes already (what a sync or a copy by hand leaves of a move made on another machine).

        What is in place stays, by the rule. The pin's copy is made from
        the whole file at the old place, which then goes aside.
        """
        root, s2, p3 = self._store(work, bytes(len(K)))
        before = facts_by_folder(root)
        assert all(at_place for _, _, at_place, _, _ in before.values())
        copy = next(step for step in migrate_0_5.plan(root).steps if step.op == "copy")
        assert copy.source == f"pipelines/acme+p/{s2}/_data/k.parquet"
        done = migrate_0_5.run(root)
        reads = reads_after(root)
        assert (root / ASIDE / "pipelines" / "acme+p" / s2 / "_data" / "k.parquet").read_bytes() == K  # the whole file, aside
        assert reads[("acme+p", p3, "_data/k.parquet")][0] == sha(K) and done.copied_as_is == [] and done.copied == 1
        # And what was in place is as it was, and said
        assert (root / "snapshots" / "acme+p" / s2 / "_data" / "k.parquet").read_bytes() == bytes(len(K)) and len(done.in_place) == 1

    @pytest.mark.parametrize("in_place", [K, K[:100], K + b"more"], ids=["the whole file", "part of it", "a longer one"])
    def test_whatever_is_in_place_the_copy_is_of_the_file_at_the_old_place(self, work, in_place):
        root, s2, p3 = self._store(work, in_place)
        migrate_0_5.run(root)
        assert reads_after(root)[("acme+p", p3, "_data/k.parquet")][0] == sha(K)
        assert (root / "snapshots" / "acme+p" / s2 / "_data" / "k.parquet").read_bytes() == in_place

    def test_stopped_after_any_step_it_ends_in_the_same_tree(self, work):
        root, s2, p3 = self._store(work, bytes(len(K)))
        assert _stopped_after_each_step(root, work) == []

    def test_where_the_old_place_does_not_hold_the_file_the_copy_is_from_the_new_tree(self, work):
        """The file was renamed by a run that was cut short: it is in the new tree and nowhere else, and the pin's copy is made from there, as before."""
        root = empty_store(work)
        s2 = folder_of("2025-11-01", "b")
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        p3 = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, s2, None)], made_by="pin")
        put(root, "acme+p", s2, "_data/k.parquet", K, tree="snapshots")
        copy = next(step for step in migrate_0_5.plan(root).steps if step.op == "copy")
        assert copy.source == f"snapshots/acme+p/{s2}/_data/k.parquet"
        done = migrate_0_5.run(root)
        assert reads_after(root)[("acme+p", p3, "_data/k.parquet")][0] == sha(K) and done.missing == []


def _stopped_after_each_step(root, work) -> list:
    """A move of a copy of *root* stopped after each step, journal kept and deleted, and run again: each ``(step, journal kept, what differs from the uninterrupted move's tree)`` that differs."""
    whole = work / "whole"
    shutil.copytree(root, whole)
    _clear()
    steps = len(migrate_0_5.plan(root).steps)
    migrate_0_5.run(whole)
    wanted = tree_of(whole)
    differ = []
    for number in range(1, steps + 2):
        for journal in (True, False):
            cut = work / "cut"
            shutil.copytree(root, cut)
            _clear()
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=lambda done, number=number: (_ for _ in ()).throw(Stop()) if done == number else None)
            if not journal:
                (cut / migrate_0_5.JOURNAL).unlink()
            _clear()
            migrate_0_5.run(cut)
            now = tree_of(cut)
            if now != wanted:
                differ.append((number, journal, sorted(path for path in set(now) | set(wanted) if now.get(path) != wanted.get(path))))
            rmtree(cut)
    rmtree(whole)
    return differ


@pytest.mark.skipif(MODES_KEEP_NOBODY_OUT, reason="the mode of a file keeps nobody from reading it here (Windows, or root)")
class TestAFileThisUserMayNotReadThatMustBeCopied:
    """P3. ``check`` asked whether each folder may be written and whether a file is locked, and not whether a file a copy reads may be read: the file was renamed, and the copy of it stopped the move half way, each time it was run again."""

    def _two_pins(self, root, mode_of=None):
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, "_data/a.parquet", A)
        unreadable = put(root, "acme+q", q1, "_data/k.parquet", K)
        record(root, "acme/q", "2025-10-01", "e", [("_data/a.parquet", A, None, None), ("_data/k.parquet", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [("_data/a.parquet", A, q1, None), ("_data/k.parquet", K, q1, None)], made_by="pin")
        return q1, q2, unreadable

    def test_it_is_found_before_the_first_step(self, work):
        """Two snapshots a pin made share a file this user may not read (another user's, in a shared store)."""
        root = empty_store(work)
        q1, q2, unreadable = self._two_pins(root)
        os.chmod(unreadable, 0)
        try:
            listing = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            with pytest.raises(migrate_0_5.MoveError) as stopped:
                migrate_0_5.run(root)
            assert str(stopped.value) == (
                f"{unreadable} is a file this user may not read, and the move has to copy it (two snapshots must each hold it): the store "
                f"is not moved. It is moved by whoever may read all of it; or let this user read that file, and run this again."
            )
            assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == listing
        finally:
            os.chmod(unreadable, stat.S_IRUSR | stat.S_IWUSR)
        _clear()
        migrate_0_5.run(root)  # the way out, carried out
        assert {key: got[0] for key, got in reads_after(root).items()} == {
            ("acme+q", q1, "_data/a.parquet"): sha(A), ("acme+q", q1, "_data/k.parquet"): sha(K),
            ("acme+q", q2, "_data/a.parquet"): sha(A), ("acme+q", q2, "_data/k.parquet"): sha(K),
        }

    def test_one_that_is_only_renamed_is_moved_as_it_is(self, work):
        """A rename reads nothing: a file one snapshot alone holds changes folder whoever may read it."""
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        unreadable = put(root, "acme+p", s, "_data/k.parquet", K)
        record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None)])
        os.chmod(unreadable, 0)
        moved = root / "snapshots" / "acme+p" / s / "_data" / "k.parquet"
        try:
            done = migrate_0_5.run(root)
            assert done.renamed == 1 and done.missing == [] and moved.stat().st_size == len(K)
        finally:
            os.chmod(moved if moved.exists() else unreadable, stat.S_IRUSR | stat.S_IWUSR)

    def test_one_that_a_run_cut_short_has_renamed_already_is_found_where_it_is_now(self, work):
        """The copy reads the file where the rename put it: asked there, once the rename is made."""
        root = empty_store(work)
        q1, q2, unreadable = self._two_pins(root)
        steps = migrate_0_5.plan(root).steps
        renamed = next(number for number, step in enumerate(steps, 1) if step.op == "rename" and step.target.endswith("k.parquet"))
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == renamed else None)
        now = root / steps[renamed - 1].target
        os.chmod(now, 0)
        try:
            _clear()
            before = tree_of_names(root)
            with pytest.raises(migrate_0_5.MoveError, match="is a file this user may not read"):
                migrate_0_5.run(root)
            assert tree_of_names(root) == before
        finally:
            os.chmod(now, stat.S_IRUSR | stat.S_IWUSR)


def tree_of_names(root) -> list:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
