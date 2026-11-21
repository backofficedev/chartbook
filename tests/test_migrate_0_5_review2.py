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


class TestAMissingFileIsToldByItsPipelineItsSnapshotAndItsPath:
    """P4. Two pipelines of one repository, snapshots of one commit made in one second: their folders have one name. Each lacks the file of the same path, and the two were counted as one."""

    def _two_pipelines(self, store) -> str:
        for identity in ("acme/p", "acme/q"):
            snapshot = folder_of("2025-10-01", "a")
            put(store, identity.replace("/", "+"), snapshot, "_data/a.parquet", A)
            record(store, identity, "2025-10-01", "a", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        return snapshot

    def test_the_number_of_missing_files_is_the_sum_of_the_lines_under_it(self, store):
        snapshot = self._two_pipelines(store)
        found = migrate_0_5.plan(store)
        assert found.missing == [("acme+p", snapshot, "_data/b.parquet"), ("acme+q", snapshot, "_data/b.parquet")]
        assert [lacks[2:] for lacks in found.missing_in] == [(1, 2), (1, 2)]
        said = typed("store", "migrate", "--dry-run").output.splitlines()
        assert said[1] == "  2 file(s) that a record names are missing or of another size, as before the move, in 2 snapshot(s):"
        assert said[2:6] == [
            f"    acme+p/{snapshot}: 1 of 2 file(s)", f"    acme+q/{snapshot}: 1 of 2 file(s)",
            "    the first: _data/b.parquet", "               _data/b.parquet",
        ]

    def test_the_last_lines_count_the_missing_files_of_two_pipelines_too(self, store):
        """And the last line says how many "are missing" to look for in what went aside."""
        snapshot = self._two_pipelines(store)
        result = typed("store", "migrate", "--yes")
        assert result.exit_code == 0
        last = result.output[result.output.index("has this version's layout"):]
        _clear()
        assert len(store_module.FolderStore(store).verify()) == 2  # `store verify` lists every one: two
        assert "  2 file(s) that a record names are missing or of another size" in last and " 2 file(s) are missing, and one may be in that folder" in last, last[:900]

    def test_the_first_names_are_those_of_the_snapshots_that_lack_most_whichever_pipeline_they_are_of(self, store):
        """The lines by snapshot are in the order of how many each lacks, and the three names under them follow that order, by pipeline and snapshot."""
        snapshot = folder_of("2025-10-01", "a")
        record(store, "acme/p", "2025-10-01", "a", [("_data/p.parquet", A, None, None)])
        record(store, "acme/q", "2025-10-01", "a", [("_data/q1.parquet", A, None, None), ("_data/q2.parquet", B, None, None)])
        said = typed("store", "migrate", "--dry-run").output.splitlines()
        assert said[1].startswith("  3 file(s) that a record names are missing")
        assert said[2:7] == [
            f"    acme+q/{snapshot}: 2 of 2 file(s)", f"    acme+p/{snapshot}: 1 of 1 file(s)",
            "    the first: _data/q1.parquet", "               _data/q2.parquet", "               _data/p.parquet",
        ]


class TestWhatIsCountedAsMovedByRename:
    """P6. A file at its old place and where it goes already (brought by a sync of a move made elsewhere) was said "not moved, a file being where each goes already", which is so, and counted in the line above among the files "moved inside the store by rename"."""

    def test_a_file_that_is_in_place_already_is_not_counted_as_moved_by_rename_too(self, store):
        s = folder_of("2025-10-01", "a")
        put(store, "acme+p", s, "_data/a.parquet", A)
        record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        put(store, "acme+p", s, "_data/a.parquet", A, tree="snapshots")
        said = typed("store", "migrate", "--dry-run").output
        assert "  1 file(s) a record names are not moved, a file being where each goes already: " in said
        assert "  0 file(s), 0 bytes, are moved inside the store by rename" in said, [line for line in said.splitlines() if "by rename" in line]
        done = typed("store", "migrate", "--yes").output
        assert "  0 file(s), 0 bytes, were moved inside the store by rename" in done, [line for line in done.splitlines() if "by rename" in line]
        assert "  1 file(s) a record names were not moved, a file being where each goes already: " in done

    def test_one_that_a_run_cut_short_renamed_is_counted_whatever_became_of_the_journal(self, work):
        """The count is of the whole move: a file that is where it goes and no longer at the old place was renamed there, by this run or by the one before it."""
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        put(root, "acme+p", s, "_data/b.parquet", B)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        assert (migrate_0_5.plan(root).renamed, migrate_0_5.plan(root).renamed_bytes) == (2, 300)
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == 1 else None)
        (root / migrate_0_5.JOURNAL).unlink()
        _clear()
        again = migrate_0_5.plan(root)
        assert (again.renamed, again.renamed_bytes, again.in_place) == (2, 300, [])
        done = migrate_0_5.run(root)
        assert (done.renamed, done.renamed_bytes, done.in_place) == (2, 300, [])

    def test_of_two_files_one_in_place_and_one_to_rename_the_one_is_counted(self, store):
        s = folder_of("2025-10-01", "a")
        put(store, "acme+p", s, "_data/a.parquet", A)
        put(store, "acme+p", s, "_data/b.parquet", B)
        record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        put(store, "acme+p", s, "_data/a.parquet", A, tree="snapshots")
        found = migrate_0_5.plan(store)
        assert (found.renamed, found.renamed_bytes, len(found.in_place), found.missing) == (1, 200, 1, [])
        done = migrate_0_5.run(store)
        assert (done.renamed, done.renamed_bytes, len(done.in_place), done.missing) == (1, 200, 1, [])


class TestAStoreThatLooksHalfMovedAndHasNoJournal:
    """P6. Another machine moved the store and finished: its journal is gone. Here the sync has brought the new trees, and not yet ``store.json`` nor taken ``pipelines/`` away. Two machines would then move one store, which the journal is there to prevent and cannot once the first has finished."""

    def test_a_store_that_another_machine_has_moved_and_a_sync_is_still_bringing_is_told_to_wait_before_the_question(self, store, work):
        s1 = folder_of("2025-10-01", "a")
        put(store, "acme+p", s1, "_data/a.parquet", A)
        record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        put(store, "acme+p", folder_of("2025-11-01", "b"), "_data/b.parquet", B)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, s1, None), ("_data/b.parquet", B, None, None)])
        theirs = work / "theirs"
        shutil.copytree(store, theirs)
        migrate_0_5.run(theirs)
        for tree in ("snapshots", "increments"):
            shutil.copytree(theirs / tree, store / tree)
        _clear()
        with pytest.raises(store_module.StoreError, match="wait for the sync to finish"):
            store_module.FolderStore(store).records()  # what every other command says
        before = tree_of(store)
        for words, answer in ((["--dry-run"], None), ([], "n\n")):
            result = CliRunner().invoke(main, ["store", "migrate", *words], input=answer)
            assert result.exit_code == 0, result.output
            first = result.output.splitlines()[0]
            assert first == (
                f"The store at {store_module.FolderStore(store)} has the layout of ChartBook 0.5, and folders of this version's beside it: it looks "
                f"half moved, and the move goes on from the folders as they are. If another machine moved it, a sync may still be bringing "
                f"the rest: wait for the sync to finish, and move nothing here. 1 pipeline(s), 2 snapshot(s)."
            )
            assert result.output.splitlines()[-1] == "Nothing was moved." and tree_of(store) == before

    def test_one_whose_own_journal_is_there_is_not_told_so(self, store):
        """This machine's journal says whose move it is: it goes on, and no question is asked."""
        s = folder_of("2025-10-01", "a")
        put(store, "acme+p", s, "_data/a.parquet", A)
        record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == 1 else None)
        _clear()
        result = typed("store", "migrate")
        assert result.exit_code == 0 and "was cut short: it goes on where it stopped." in result.output.splitlines()[0] and "sync may still be bringing" not in result.output.splitlines()[0]


class TestStoppedWhereFilesWereAlreadyInTheNewTrees:
    """P7. In a store a sync has part brought from a move made elsewhere, a move stopped and run again ended in another tree than an uninterrupted one, both whole (6 of 150 drawn stores)."""

    def test_stopped_after_a_copy_an_increment_names_the_same_file_of_the_one_it_builds_on(self, work):
        """The newest snapshot names the same bytes twice (``k.parquet``, ``kb.parquet``), and neither file is at its old place (an upload that never finished). A pin's snapshot names them too, and its file is in the new tree already.

        The newest is given a copy of each from the pin's. An older
        snapshot then names the bytes in the newest: which of the two
        files its record said depended on where the move was stopped. It
        is the first in the newest one's record that the move makes
        whole, by rename or by copy alike.
        """
        root = empty_store(work)
        c0 = folder_of("2025-09-01", "h")
        older = record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, c0, None)])
        newest = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, c0, None), ("_data/kb.parquet", K, None, None)])
        pin = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, c0, None)], made_by="pin")
        put(root, "acme+p", pin, "_data/k.parquet", K, tree="snapshots")
        differ = _stopped_after_each_step(root, work)
        assert differ == [], f"{len(differ)} of the moves that were stopped ended in another tree; the first: {differ[0]}"
        _clear()
        migrate_0_5.run(root)
        assert reads_after(root)[("acme+p", older, "_data/k.parquet")] == (sha(K), f"snapshots/acme+p/{newest}/_data/k.parquet")

    def test_stopped_after_a_rename_a_file_that_was_to_go_aside_is_not_taken_instead(self, work):
        """A pin's snapshot has its file at its old place and in the new tree already, so the one at the old place goes aside, and is said. The newest snapshot names the same bytes twice, at its own place.

        Stopped once the newest one's file was renamed, and run again, the
        second name of the newest was no longer copied from the first: the
        pin's file at the old place was renamed there instead, and did not
        go aside. A file at its old place whose own place is taken is
        copied from, and goes aside: it is never renamed into another
        snapshot.
        """
        root = empty_store(work)
        pin = folder_of("2025-10-15", "i")
        put(root, "acme+p", pin, "_data/k.parquet", K)
        record(root, "acme/p", "2025-10-15", "i", [("_data/k.parquet", K, None, None)], made_by="pin")
        newest = folder_of("2025-11-01", "b")
        put(root, "acme+p", newest, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None), ("_data/kb.parquet", K, None, "_data/k.parquet")])
        put(root, "acme+p", pin, "_data/k.parquet", K, tree="snapshots")
        differ = _stopped_after_each_step(root, work)
        assert differ == [], f"{len(differ)} of the moves that were stopped ended in another tree; the first: {differ[0]}"
        _clear()
        done = migrate_0_5.run(root)
        assert (root / ASIDE / "pipelines" / "acme+p" / pin / "_data" / "k.parquet").read_bytes() == K and len(done.in_place) == 1


# Stores drawn from seeds with the second review's shapes (``tests.found_store_of_0_5.drawn_store``). The reviewer ran
# 300 of them; a few are kept, and ``MOVER_SEEDS=0-149`` runs a range


def _seeds(default):
    asked = os.environ.get("MOVER_SEEDS", "")
    if not asked:
        return default
    first, _, last = asked.partition("-")
    return tuple(range(int(first), int(last or first) + 1))


SEEDS = _seeds((0, 1, 2, 3, 4, 5, 6, 7))

#: The seeds of 0 to 149 whose stores, with files brought of a move made elsewhere, ended in another tree when stopped,
#: one of each kind: one file more or fewer was aside (16), and the record of an increment named another of two files
#: of the same bytes (136). The small cases of each are in ``TestStoppedWhereFilesWereAlreadyInTheNewTrees``
FOUND = (16, 136)


def _worse(before: dict, reads: dict, placed: dict) -> tuple:
    """The files that read before and do not now; but one whose own place in the new trees held other bytes before the move (what is in place stays, and is said).

    And but one that reads a copy of a file of its size and other bytes
    that was in the new trees, where the place its bytes were to be taken
    from did not hold them. The move goes by sizes and reads nothing, so
    such a file is not told from one that a move cut short put there, and
    is taken for the bytes: the copy is hashed as it is written and the
    last lines name it, and nothing is removed
    (``TestWhatIsInTheNewTreesIsTakenByItsSize``). Where the old place
    holds the whole file the copy is made from there (P2).
    """
    lost, not_taken = [], []
    other_bytes = set(placed.values())
    for key, (content_hash, _, at_place, anywhere, _) in sorted(before.items()):
        now, where = reads.get(key, ("nothing", ""))
        if now == content_hash or placed.get(where, content_hash) != content_hash or now in other_bytes:
            continue
        if at_place:
            lost.append((key, now, where))
        elif anywhere:
            not_taken.append((key, now, where))
    return lost, not_taken


@pytest.mark.parametrize("brought", [True, "of a move made elsewhere"], ids=["at any place a step writes to", "of a move made elsewhere"])
@pytest.mark.parametrize("pipelines", [1, 2])
@pytest.mark.parametrize("seed", SEEDS)
def test_a_move_of_a_store_drawn_with_the_second_reviews_shapes_makes_nothing_worse_and_removes_nothing(work, seed, pipelines, brought, monkeypatch):
    from tests.found_store_of_0_5 import drawn_store
    from tests.rich_store_of_0_5 import OWN, contents

    root = empty_store(work)
    drawn = drawn_store(root, seed, pipelines, in_the_new_trees=brought)
    before, held, tree = facts_by_folder(root), contents(root), tree_of(root)
    _clear()
    gone: list = []
    try:
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
    except migrate_0_5.MoveError as refused:
        assert tree_of(root) == tree, f"refused ({refused}), and the store is not as it was"
        pytest.skip(f"refused before anything moved: {str(refused)[:160]}")
    lost, not_taken = _worse(before, reads_after(root), drawn["placed"])
    assert lost == [], f"{drawn['shapes']}: at their stated place before, and not read now: {lost[:4]}"
    assert not_taken == [], f"{drawn['shapes']}: held at a place a record of the pipeline names, and not read now: {not_taken[:4]}"
    assert not_its_own(gone) == [], drawn["shapes"]
    after = contents(root)
    assert [paths for key, paths in held.items() if key not in after and not any(path in OWN for path in paths)] == [], drawn["shapes"]
    assert not (root / migrate_0_5.MOVING).exists()
    # Every file of data that was in the new trees before the move is as it was (a record of other words goes aside, by
    # the rule; its bytes are among those looked for above)
    now = tree_of(root)
    for target, content_hash in drawn["placed"].items():
        if "/_chartbook/" not in target and not target.endswith("README.txt"):
            assert "sha256:" + now.get(target, "gone") == content_hash, target


def _stopped(work, seed, brought):
    """Stop a move of the store of a seed after each step, journal kept and deleted, some of them twice, and go on: what was drawn, each end that differs from the uninterrupted move, and how many ends there were."""
    from tests.found_store_of_0_5 import drawn_store
    from tests.rich_store_of_0_5 import stop_after

    root = empty_store(work)
    drawn = drawn_store(root, seed, 1 + seed % 2, in_the_new_trees=brought)
    whole = work / "whole"
    shutil.copytree(root, whole)
    _clear()
    try:
        migrate_0_5.run(whole)
    except migrate_0_5.MoveError as refused:
        pytest.skip(f"refused before anything moved: {str(refused)[:160]}")
    wanted = tree_of(whole)
    reads = reads_after(whole)
    chosen = random.Random(seed)
    _clear()
    steps = len(migrate_0_5.plan(root).steps)
    wrong = []
    for first in range(1, steps + 2):
        for journal in (True, False):
            cut = work / "cut"
            shutil.copytree(root, cut)
            _clear()
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=stop_after(first))
            if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                (cut / migrate_0_5.JOURNAL).unlink()
            _clear()
            second = None
            if chosen.random() < 0.3:
                second = chosen.randint(1, max(1, len(migrate_0_5.plan(cut).steps)))
                try:
                    migrate_0_5.run(cut, after_step=stop_after(second))
                except Stop:
                    pass
                if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                    (cut / migrate_0_5.JOURNAL).unlink()
                _clear()
            migrate_0_5.run(cut)
            if tree_of(cut) != wanted:
                wrong.append((first, second, journal, sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
            elif reads_after(cut) != reads:
                wrong.append((first, second, journal, "reads differ"))
            rmtree(cut)
    return drawn["shapes"], wrong, 2 * (steps + 1)


@pytest.mark.parametrize("brought", [False, "of a move made elsewhere"], ids=["nothing in the new trees", "files brought of a move made elsewhere"])
@pytest.mark.parametrize("seed", SEEDS)
def test_stopped_after_any_step_and_stopped_twice_a_drawn_store_ends_in_the_tree_of_an_uninterrupted_move(work, seed, brought):
    import json

    shapes, wrong, ends = _stopped(work, seed, brought)
    assert not wrong, f"{shapes}: {len(wrong)} of {ends}: " + json.dumps(wrong[:3], indent=1)


@pytest.mark.parametrize("seed", FOUND if not os.environ.get("MOVER_SEEDS") else ())
def test_the_seeds_found_end_in_the_tree_of_an_uninterrupted_move_too(work, seed):
    import json

    shapes, wrong, ends = _stopped(work, seed, "of a move made elsewhere")
    assert not wrong, f"{shapes}: {len(wrong)} of {ends}: " + json.dumps(wrong[:2], indent=1)


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("seed", SEEDS[:4])
def test_killed_around_every_rename_a_drawn_store_ends_in_the_tree_of_an_uninterrupted_move(work, seed, when, monkeypatch):
    import json

    from tests.found_store_of_0_5 import drawn_store

    root = empty_store(work)
    drawn = drawn_store(root, seed, 1, in_the_new_trees="of a move made elsewhere")
    whole = work / "whole"
    shutil.copytree(root, whole)
    _clear()
    real = os.replace
    calls = []
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.append(1), real(a, b))[1])
    try:
        migrate_0_5.run(whole)
    except migrate_0_5.MoveError as refused:
        pytest.skip(f"refused before anything moved: {str(refused)[:160]}")
    finally:
        monkeypatch.setattr(os, "replace", real)
    wanted, reads = tree_of(whole), reads_after(whole)
    wrong = []
    for number in range(1, len(calls) + 1):
        for journal in (True, False):
            cut = work / "cut"
            shutil.copytree(root, cut)
            seen = []

            def dying(a, b, number=number, seen=seen):
                seen.append(1)
                if len(seen) == number and when == "before":
                    raise Stop()
                real(a, b)
                if len(seen) == number and when == "after":
                    raise Stop()

            _clear()
            monkeypatch.setattr(os, "replace", dying)
            try:
                with pytest.raises(Stop):
                    migrate_0_5.run(cut)
            finally:
                monkeypatch.setattr(os, "replace", real)
            if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                (cut / migrate_0_5.JOURNAL).unlink()
            _clear()
            migrate_0_5.run(cut)
            if tree_of(cut) != wanted:
                wrong.append((number, journal, sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
            elif reads_after(cut) != reads:
                wrong.append((number, journal, "reads differ"))
            rmtree(cut)
    assert not wrong, f"{drawn['shapes']}: {len(wrong)} of {2 * len(calls)}: " + json.dumps(wrong[:3], indent=1)


@pytest.mark.parametrize("pipelines", [1, 2])
@pytest.mark.parametrize("seed", SEEDS)
def test_every_number_of_the_plan_is_true_of_the_tree_before_and_after(work, seed, pipelines):
    """On a store with nothing in the new trees yet: what the dry run counts, against the folders."""
    import unicodedata

    from tests.found_store_of_0_5 import _parts, drawn_store, records_0_5_read

    root = empty_store(work)
    drawn = drawn_store(root, seed, pipelines, in_the_new_trees=False)
    before = facts_by_folder(root)
    takes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink())
    said = set()
    names_of: dict = {}
    for pipeline, snapshot, document in records_0_5_read(root):
        for part in _parts(document):
            for entry in part["stored"]["files"]:
                said.add(f"pipelines/{pipeline}/{entry.get('kept_in', snapshot)}/{entry.get('kept_as', entry['path'])}")
                names_of.setdefault((pipeline, snapshot), set()).add(entry["path"])
    _clear()
    try:
        planned = migrate_0_5.plan(root)
        migrate_0_5.check(root, planned)
        done = migrate_0_5.run(root)
    except migrate_0_5.MoveError as refused:
        pytest.skip(f"refused before anything moved: {str(refused)[:160]}")
    shapes = drawn["shapes"]
    # What is missing: what no stated place of the pipeline held, by pipeline and snapshot
    lacks: dict = {}
    for (pipeline, snapshot, path), (_, _, _, anywhere, _) in before.items():
        if not anywhere:
            lacks.setdefault((pipeline, snapshot), set()).add(path)
    expected_in = sorted(((pipeline, snapshot, len(paths), len(names_of[(pipeline, snapshot)])) for (pipeline, snapshot), paths in lacks.items()), key=lambda one: (-one[2], one[:2]))
    assert planned.missing_in == expected_in, shapes
    assert done.missing_in == expected_in, shapes
    # The first line's number is the sum of the lines under it, for two pipelines with the same folder names too
    assert len(planned.missing) == sum(one[2] for one in planned.missing_in), shapes
    assert len(done.missing) == sum(one[2] for one in done.missing_in), shapes
    # What is moved in, and what goes aside
    moved_in = [path for tree in ("snapshots", "increments") for path in (root / tree).rglob("*") if path.is_file() and "_chartbook" not in path.parts and path.name != "README.txt"]
    assert planned.renamed + planned.copied == len(moved_in) == done.renamed + done.copied, shapes
    assert planned.renamed_bytes + planned.copied_bytes == sum(path.stat().st_size for path in moved_in), shapes
    aside = [path.relative_to(root / ASIDE).as_posix() for path in (root / ASIDE).rglob("*") if path.is_file() and path.name not in ("snapshot.json", "CLEARED.txt", "README.txt")]
    named = [path for path in aside if unicodedata.normalize("NFC", path) in said]  # as the disk tells names apart: the name may be there in the other form
    assert (done.doubled, done.aside) == (len(named), len(aside) - len(named)) == (planned.doubled, planned.aside), shapes
    # The copies, and what the store takes
    assert sum(one[2] for one in planned.copied_into) == planned.copied and sum(one[3] for one in planned.copied_into) == planned.copied_bytes, shapes
    if planned.copied:
        assert (planned.store_bytes, planned.store_after) == (takes, takes + planned.copied_bytes), shapes
    # The files that were not where their record says and read now
    reads = reads_after(root)
    elsewhere = [key for key, (content_hash, _, at_place, anywhere, _) in before.items() if not at_place and anywhere and reads.get(key, ("",))[0] == content_hash]
    assert planned.elsewhere == len(elsewhere) == done.elsewhere, shapes


# What the second review attacked and found sound, kept as it tested it


EDGES = [
    "a", "A", "z9", "0", "-", "_", "...", "a.", "A.", ".a", "..a", "a..", "a.b", "a-b", "a_b", "A-b_C.d",
    "con", "CON", "con.txt", "Con.TXT", "nul", "aux", "prn", "com1", "COM9.dat", "lpt0", "lpt9.x.y",
    "acme/p", "Acme/P", "acme/P", "ACME/p", "a.b/c.d", "-/-", "_/_", "./a", "a/...", "nul/x", "x/aux", "con/con", "localhost",
    "x" * 100, "X" * 60 + "/" + "y" * 60, "a.b-c_d/e.f-g_h", "9/9", "a/b.", "a./b", "A./B.",
]


@pytest.mark.parametrize("identity", EDGES)
def test_a_pipeline_of_any_id_the_grammar_takes_is_moved_and_never_passed_over(work, identity):
    """The worst a test of names could do is pass a real pipeline's folder over: it would go aside whole. Each ID at an edge of what ``validate_pipeline_id`` takes, in the folder ``pipeline_folder`` gives it."""
    if identity.startswith("./"):
        with pytest.raises(ValueError):
            validate_pipeline_id(identity)  # "." is no component: not an ID, and so no folder of a store
        return
    validate_pipeline_id(identity)
    root = empty_store(work)
    folder = pipeline_folder(identity)
    snapshot = folder_of("2025-10-01", "a")
    try:
        put(root, folder, snapshot, "_data/a.parquet", A)
    except OSError:
        pytest.skip("this disk does not take a folder of this name")
    record_at(root, folder, identity, "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
    older = record_at(root, folder, identity, "2025-09-01", "b", [("_data/a.parquet", A, snapshot, None)], made_by="pin")
    found = migrate_0_5.plan(root)
    assert found.not_pipelines == [] and (found.pipelines, found.snapshots, found.set_aside) == (1, 2, [])
    done = migrate_0_5.run(root)
    assert done.not_pipelines == [] and done.set_aside == [] and done.missing == []
    assert {key: got[0] for key, got in reads_after(root).items()} == {(folder, snapshot, "_data/a.parquet"): sha(A), (folder, older, "_data/a.parquet"): sha(A)}


def test_the_folder_of_any_id_drawn_is_named_as_a_pipelines_folder_is():
    """Widely: 20,000 IDs drawn from the grammar's letters, with the names Windows keeps and dots at the ends among them."""
    drawn = random.Random(20261120)
    letters = string.ascii_letters + string.digits + "._-"
    special = ["con", "CON", "nul", "aux", "prn", "com1", "lpt9", "a.", ".", "..", "...", "Con.x"]

    def component() -> str:
        if drawn.random() < 0.15:
            return drawn.choice(special)
        return "".join(drawn.choice(letters) for _ in range(drawn.randint(1, 12)))

    passed_over = []
    for _ in range(20000):
        identity = component() if drawn.random() < 0.4 else f"{component()}/{component()}"
        try:
            validate_pipeline_id(identity)
        except ValueError:
            continue
        if not migrate_0_5._is_pipeline_folder(pipeline_folder(identity)):
            passed_over.append(identity)
    assert passed_over == []


def test_a_first_move_that_put_only_a_note_aside_did_not_make_the_store_a_moved_one(work):
    """The sign of a moved store is a folder in what went aside under the old folder's name. A person's README put aside, the mark of the move from 0.2, and a note of a lockfile put aside are none."""
    root = empty_store(work)
    s = folder_of("2025-10-01", "a")
    put(root, "acme+p", s, "_data/a.parquet", A)
    record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
    (root / "README.txt").write_text("Ours. Ask Dana.\n", encoding="utf-8", newline="\n")
    (root / "snapshots" / ("0" * 40)).mkdir(parents=True)
    (root / "snapshots" / ("0" * 40) / "MOVED.txt").write_text("moved\n", encoding="utf-8", newline="\n")
    (root / "roots" / ("ab" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
    steps = migrate_0_5.plan(root).steps
    last_before_the_old_folder = max(number for number, step in enumerate(steps, 1) if step.op != "aside" or step.source != "pipelines")
    with pytest.raises(Stop):
        migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == last_before_the_old_folder else None)
    (root / migrate_0_5.JOURNAL).unlink()
    assert (root / ASIDE / "README.txt").is_file() and (root / ASIDE / "snapshots").is_dir() and not migrate_0_5.is_moved(root)
    # And what arrives now is moved in, as on any store of 0.5
    put(root, "acme+p", folder_of("2025-11-01", "b"), "_data/b.parquet", B)
    newer = record(root, "acme/p", "2025-11-01", "b", [("_data/b.parquet", B, None, None), ("_data/a.parquet", A, s, None)])
    _clear()
    done = migrate_0_5.run(root)
    _clear()
    assert done.set_aside == [] and {key[1] for key in reads_after(root)} == {s, newer} and store_module.FolderStore(root).verify() == []


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_what_a_machine_still_on_0_5_writes_again_into_a_moved_store_goes_aside_and_nothing_in_the_store_changes(work, seed, monkeypatch):
    """A store is moved; a machine that had not been brought the move then syncs its own copy of ``pipelines/`` back, whole, with a snapshot more. The second run puts it aside, removes nothing, and names only the new snapshot to be made again."""
    root = empty_store(work)
    wide_store(root, seed, 2)
    stale = work / "stale"
    shutil.copytree(root / "pipelines", stale)
    migrate_0_5.run(root)
    moved = {path: value for path, value in tree_of(root).items() if path.startswith(("snapshots/", "increments/"))}
    shutil.copytree(stale, root / "pipelines")
    put(root, "acme+p", folder_of("2025-12-24", "k"), "_data/new.parquet", B)
    newer = record(root, "acme/p", "2025-12-24", "k", [("_data/new.parquet", B, None, None)])
    _clear()
    records = len(list((root / "pipelines").glob("*/*/_chartbook/snapshot.json")))
    gone: list = []
    with monkeypatch.context() as patch:
        watch(patch, root, gone)
        done = migrate_0_5.run(root)
    assert not_its_own(gone) == [] and not (root / "pipelines").exists()
    assert {path: value for path, value in tree_of(root).items() if path.startswith(("snapshots/", "increments/"))} == moved
    assert done.set_aside == [("acme+p", newer)] and len(done.second) == records - 1
    assert (root / ASIDE / "pipelines (2)" / "acme+p" / newer / "_data" / "new.parquet").read_bytes() == B


def test_a_hard_link_is_a_file(work):
    """A file of the store that is a hard link to one outside it is a plain file: it is renamed, and the other name keeps its bytes."""
    root = empty_store(work)
    outside = work / "outside.parquet"
    outside.write_bytes(K)
    s = folder_of("2025-10-01", "a")
    (root / "pipelines" / "acme+p" / s / "_data").mkdir(parents=True)
    try:
        os.link(outside, root / "pipelines" / "acme+p" / s / "_data" / "k.parquet")
    except (OSError, NotImplementedError):
        pytest.skip("this disk makes no hard link")
    record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None)])
    pin = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, s, None)], made_by="pin")
    done = migrate_0_5.run(root)
    assert done.missing == [] and outside.read_bytes() == K
    assert {key: got[0] for key, got in reads_after(root).items()} == {("acme+p", s, "_data/k.parquet"): sha(K), ("acme+p", pin, "_data/k.parquet"): sha(K)}


@needs_symlinks
def test_a_link_to_another_folder_of_the_store_stops_the_move_like_one_that_leads_outside(work):
    """A snapshot's folder that is a link to another snapshot's folder of the same store."""
    root = empty_store(work)
    s = folder_of("2025-10-01", "a")
    put(root, "acme+p", s, "_data/k.parquet", K)
    record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None)])
    os.symlink(root / "pipelines" / "acme+p" / s, root / "pipelines" / "acme+p" / folder_of("2025-09-01", "h"), target_is_directory=True)
    record(root, "acme/p", "2025-12-01", "c", [("_data/k.parquet", K, folder_of("2025-09-01", "h"), None)])
    before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
    with pytest.raises(migrate_0_5.MoveError, match="is a link to another place"):
        migrate_0_5.run(root)
    assert sorted(path.relative_to(root).as_posix() for path in root.rglob("*")) == before


class TestWhatIsInTheNewTreesIsTakenByItsSize:
    """Known, and left: the move reads nothing, so a file of the right size in the new trees is the file to it, as one that a move cut short put there is. Where its bytes are others (a copy that set the file's length first and stopped), what the move does with it is said, and nothing is removed."""

    def test_a_copy_of_other_bytes_is_named_and_the_right_bytes_are_still_in_the_store(self, work):
        """An older snapshot has K in its own folder. The newest and a pin's name K in a folder that does not hold it, and where the pin's file goes there is a file of K's size and other bytes.

        The newest is given a copy of that file, which is hashed as it is
        written and named in the last lines; the older one's K goes aside
        with the old folder, where the last lines say to look.
        """
        root = empty_store(work)
        c0 = folder_of("2025-09-01", "h")
        older = folder_of("2025-10-01", "a")
        put(root, "acme+p", older, "_data/k.parquet", K)
        record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None)])
        newest = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, c0, None)])
        pin = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, c0, None)], made_by="pin")
        put(root, "acme+p", pin, "_data/k.parquet", bytes(len(K)), tree="snapshots")
        done = migrate_0_5.run(root)
        assert done.copied_as_is == [f"snapshots/acme+p/{newest}/_data/k.parquet"]
        held = {hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
        assert hashlib.sha256(K).hexdigest() in held  # nothing is removed: aside, or in the older one's own folder
        _clear()
        assert len(store_module.FolderStore(root).verify()) >= 2  # and `store verify` says which files are not what their records say


class TestTheMovesOwnFolderAtTheEnd:
    """P1, at the end of a move: the folder goes with what is in it; on Windows what holds a file just renamed out of it holds the folder for a moment."""

    def _one(self, work):
        root = empty_store(work)
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, "_data/a.parquet", A)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        return root

    def test_a_removal_that_windows_refuses_for_a_moment_is_tried_again(self, work, monkeypatch):
        import types

        root = self._one(work)
        real, refused = os.rmdir, []

        def held_once(path, *args, **kwargs):
            if os.fspath(path) == str(root / migrate_0_5.MOVING) and not refused:
                refused.append(path)
                raise PermissionError(13, "Access is denied", os.fspath(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(os, "rmdir", held_once)
        monkeypatch.setattr(migrate_0_5, "sys", types.SimpleNamespace(platform="win32"))
        monkeypatch.setattr(migrate_0_5, "_EMPTY_WAIT_SECONDS", 0)
        migrate_0_5.run(root)
        assert refused and not (root / migrate_0_5.MOVING).exists() and not (root / migrate_0_5.JOURNAL).exists()

    def test_a_folder_somebody_made_in_it_is_left_and_the_move_ends(self, work):
        """No file the move wrote: it stays, with the folder, and nothing waits for it on a system that says at once what is in the way."""
        root = self._one(work)
        theirs = root / migrate_0_5.MOVING / "somebody's"
        theirs.mkdir(parents=True)
        (theirs / "note.txt").write_bytes(b"kept")
        done = migrate_0_5.run(root)
        assert (theirs / "note.txt").read_bytes() == b"kept" and not (root / migrate_0_5.JOURNAL).exists() and done.missing == []
        assert migrate_0_5.marker_of(root) == "chartbook/store/v3"
