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
