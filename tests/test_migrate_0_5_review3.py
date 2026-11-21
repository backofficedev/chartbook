"""The mover after its third review (2026-11-20): each thing found, as a test of the rule that came of it, and what was attacked and held.

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout". By rule:

- **Q1** a store of 0.5 that shows a sign of a move and has no journal of
  this machine is told, before the question, to wait for a sync;
- **Q2** the move removes a file of its own with the store's own remover,
  which touches a file's mode only where the removal is refused without it;
- **Q3** a moved store that still has the move's own folder of
  temporaries has something for the command to do;
- **Q4** the last lines go by what the journal carries, and a count that
  went with a journal is left out, not said as 0;
- **Q5** the end of a move asks the disk about a file once;
- **Q6** files are said by the folders they are under, with counts.
"""

import builtins
import errno
import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import config, migrate_0_5
from chartbook import store as store_module
from chartbook.cli import main
from tests.fixtures import needs_symlinks
from tests.found_store_of_0_5 import facts_by_folder, reads_after
from tests.rich_store_of_0_5 import Stop, empty_store, folder_of, not_its_own, put, record, rich, rmtree, strictly_not_its_own, tree_of, watch

K = b"k" * 400
A = b"a" * 100
B = b"b" * 200
ASIDE = "_chartbook/left-by-0.5"

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


def clear() -> None:
    store_module._read_records.clear()
    store_module._found_whole.clear()


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def names_of(root: Path) -> list:
    """Every name under a store, files, folders and links, as it is."""
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def two_pins(root: Path, data: bytes = K, name: str = "k.parquet") -> tuple:
    """Two snapshots a pin made that share one file, kept in the older one's folder: the move renames it once and copies it once. The two folders."""
    q1 = folder_of("2025-10-01", "e")
    put(root, "acme+q", q1, f"_data/{name}", data)
    record(root, "acme/q", "2025-10-01", "e", [(f"_data/{name}", data, None, None)], made_by="pin")
    q2 = record(root, "acme/q", "2025-11-01", "f", [(f"_data/{name}", data, q1, None)], made_by="pin")
    clear()
    return q1, q2


def mode_of(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def _killed_before_the_copy_is_put_in_place(monkeypatch, root, target) -> Path:
    """Run a move and kill it once the copy for *target* is written under its temporary name; the temporary it left."""
    left = migrate_0_5._temporary_of(root, target)
    real = migrate_0_5.replace_when_free

    def killed(source, to):
        if Path(source) == left:
            raise Stop()
        return real(source, to)

    with monkeypatch.context() as patch:
        patch.setattr(migrate_0_5, "replace_when_free", killed)
        with pytest.raises(Stop):
            migrate_0_5.run(root)
    assert left.is_file() and not os.path.lexists(target)
    clear()
    return left


def _as_another_users(monkeypatch, theirs: set) -> None:
    """Make ``chmod`` answer as POSIX does for a file this user does not own: EPERM. (Unlinking it is allowed: the folder is this user's to write.)

    It is the file that is another user's, not its name: once it is
    removed, a file this user writes under the same name is this user's.
    """
    real, real_remove = os.chmod, os.remove

    def chmod(path, mode, *args, **kwargs):
        if Path(os.fspath(path)) in theirs:
            raise PermissionError(errno.EPERM, "Operation not permitted", os.fspath(path))
        return real(path, mode, *args, **kwargs)

    def remove(path, *args, **kwargs):
        real_remove(path, *args, **kwargs)
        theirs.discard(Path(os.fspath(path)))

    monkeypatch.setattr(os, "chmod", chmod)
    monkeypatch.setattr(os, "remove", remove)


class TestALeftoverThatIsAnotherUsers:
    """In a store two users share, one user's move is cut short and the other goes on with it. A temporary the first left is the first's file: the second may unlink it (the folder is writable) and may not change its mode."""

    def test_a_temporary_another_users_run_left_does_not_stop_the_move_half_way(self, work, monkeypatch):
        """Rule 1: nothing that is true before a move stops it half way. The first user's run was killed while it copied; the second runs the command.

        What POSIX answers for the first user's file is stood in for by a
        patch of ``os.chmod`` (EPERM for that one file), since a test has
        one user. The move must end, or ``check`` must say so before the
        first step.
        """
        root = empty_store(work)
        q1, q2 = two_pins(root)
        target = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet"
        left = _killed_before_the_copy_is_put_in_place(monkeypatch, root, target)
        (root / migrate_0_5.JOURNAL).unlink()  # the second user takes the move over, as the message says to
        _as_another_users(monkeypatch, {left})
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        before = names_of(root)
        first = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        if first.exit_code != 0 and names_of(root) == before and "The move stopped" not in first.output:
            return  # refused before anything moved, with what to do: that is the rule kept
        clear()
        second = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert first.exit_code == 0 or second.exit_code == 0, (
            "the move stops at the same step however often it is run again:\n" + first.output[-400:] + "\n--- again ---\n" + second.output[-400:]
        )
        assert reads_after(root)[("acme+q", q2, "_data/k.parquet")][0] == sha(K)

    def test_a_temporary_another_users_run_left_does_not_keep_the_move_from_ending(self, work, monkeypatch):
        """And one of no step of this plan, met when the folder is emptied at the end: the store is moved, ``store.json`` says so, and the journal stays, so that every command says a move is under way, each time."""
        root = empty_store(work)
        q1, q2 = two_pins(root)
        own = root / migrate_0_5.MOVING
        own.mkdir(parents=True)
        left = own / ("0" * 24)
        left.write_bytes(b"what another user's run left, of a step this plan does not have")
        _as_another_users(monkeypatch, {left})
        ended = []
        for _ in range(2):
            clear()
            try:
                migrate_0_5.run(root)
                ended.append("ended")
            except PermissionError as error:
                ended.append(f"stopped: {error}")
        assert "ended" in ended, ended
        assert not (root / migrate_0_5.JOURNAL).exists()


class TestWhatIsInTheMovesFolderThatIsNotAFileOfItsOwn:
    """What the end of a move removes from ``_chartbook/moving/``, and what it touches outside the store."""

    def _one(self, work):
        root = empty_store(work)
        two_pins(root)
        own = root / migrate_0_5.MOVING
        own.mkdir(parents=True)
        return root, own

    def test_a_second_name_of_a_file_outside_the_store_does_not_change_that_file(self, work):
        """A hard link there to a read-only file outside the store (what a tool that links equal files makes of a temporary and the file it is a copy of). The name goes; the file outside keeps its bytes and its mode."""
        root, own = self._one(work)
        outside = work / "outside.bin"
        outside.write_bytes(b"somebody's, read-only")
        os.chmod(outside, 0o444)
        try:
            os.link(outside, own / "a-second-name")
        except (OSError, NotImplementedError):
            pytest.skip("this disk makes no hard link")
        migrate_0_5.run(root)
        assert outside.read_bytes() == b"somebody's, read-only"
        assert mode_of(outside) == 0o444, f"the file outside the store is {oct(mode_of(outside))} now"

    @needs_symlinks
    def test_links_there_to_a_folder_and_a_file_outside_the_store_go_and_what_they_lead_to_is_as_it_was(self, work):
        root, own = self._one(work)
        folder = work / "outside-folder"
        folder.mkdir()
        (folder / "kept.txt").write_bytes(b"kept")
        file = work / "outside.bin"
        file.write_bytes(b"read-only, outside")
        os.chmod(file, 0o444)
        os.symlink(folder, own / "to-a-folder", target_is_directory=True)
        os.symlink(file, own / "to-a-file")
        os.symlink(work / "nothing-there", own / "to-nothing")
        migrate_0_5.run(root)
        assert (folder / "kept.txt").read_bytes() == b"kept" and file.read_bytes() == b"read-only, outside" and mode_of(file) == 0o444
        assert not os.path.lexists(own) and not (root / migrate_0_5.JOURNAL).exists()

    def test_a_file_of_another_name_and_a_read_only_one_go_and_a_folder_stays_with_what_is_in_it(self, work):
        root, own = self._one(work)
        (own / "notes of mine.txt").write_bytes(b"in the move's own folder")
        read_only = own / "locked-by-mode"
        read_only.write_bytes(b"x")
        os.chmod(read_only, stat.S_IREAD)
        (own / "a folder" / "deeper").mkdir(parents=True)
        (own / "a folder" / "deeper" / "kept.txt").write_bytes(b"kept")
        done = migrate_0_5.run(root)
        assert sorted(path.relative_to(own).as_posix() for path in own.rglob("*")) == ["a folder", "a folder/deeper", "a folder/deeper/kept.txt"]
        assert not (root / migrate_0_5.JOURNAL).exists() and done.missing == []
        # And the store is one every command reads: nothing takes the folder that stayed for a move under way
        clear()
        assert not migrate_0_5.to_move(root)
        from chartbook.store import FolderStore

        assert FolderStore(root).verify() == [] and len(FolderStore(root).records()) == 2

    @needs_symlinks
    @pytest.mark.parametrize("what", ["the folder of temporaries, to a folder outside", "the folder of temporaries, to a folder of the store", "the folder of temporaries, to nothing", "_chartbook, to a folder outside"])
    def test_a_link_where_the_moves_own_folder_goes_is_found_before_the_first_step(self, work, what):
        root = empty_store(work)
        two_pins(root)
        outside = work / "outside-folder"
        outside.mkdir()
        (outside / "kept.txt").write_bytes(b"kept")
        if what.startswith("_chartbook"):
            os.symlink(outside, root / "_chartbook", target_is_directory=True)
        else:
            (root / "_chartbook").mkdir()
            leads_to = {"a folder outside": outside, "a folder of the store": root / "pipelines" / "acme+q", "nothing": work / "nothing-there"}[what.rpartition("to ")[2]]
            os.symlink(leads_to, root / migrate_0_5.MOVING, target_is_directory=True)
        before, outside_before = names_of(root), names_of(outside)
        with pytest.raises(migrate_0_5.MoveError, match="is a file, or a link, where the move makes a folder"):
            migrate_0_5.run(root)
        assert names_of(root) == before and names_of(outside) == outside_before

    @needs_symlinks
    def test_a_link_that_takes_the_place_of_the_folder_while_a_move_is_cut_short_is_found_before_the_next_step(self, work, monkeypatch):
        """Half way: the folder of temporaries of a move cut short is replaced by a link to a folder outside. The next run stops before it writes anything through the link, and removes nothing through it."""
        root = empty_store(work)
        q1, q2 = two_pins(root)
        target = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet"
        left = _killed_before_the_copy_is_put_in_place(monkeypatch, root, target)
        outside = work / "outside-folder"
        outside.mkdir()
        (outside / left.name).write_bytes(b"a file outside, under the very name of a temporary")
        rmtree(root / migrate_0_5.MOVING)
        os.symlink(outside, root / migrate_0_5.MOVING, target_is_directory=True)
        before = names_of(root)
        with pytest.raises(migrate_0_5.MoveError, match="is a file, or a link, where the move makes a folder"):
            migrate_0_5.run(root)
        assert names_of(root) == before and (outside / left.name).read_bytes() == b"a file outside, under the very name of a temporary"


class TestATemporaryIsTheSameByWhateverPathTheStoreIsReached:
    """The name of a temporary is made from where its file goes under the store's top, so a move cut short by one path to the store and taken up by another finds what it left."""

    @needs_symlinks
    def test_cut_short_by_one_path_and_run_again_by_another_no_second_temporary_piles_up(self, work, monkeypatch):
        (work / "deep" / "er").mkdir(parents=True)
        root = empty_store(work / "deep" / "er")
        q1, q2 = two_pins(root)
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        clear()
        os.symlink(work / "deep", work / "alias", target_is_directory=True)
        by_alias = work / "alias" / "er" / "store"
        assert by_alias != root and by_alias.resolve() == root
        target = Path("snapshots") / "acme+q" / q2 / "_data" / "k.parquet"
        left = _killed_before_the_copy_is_put_in_place(monkeypatch, root, root / target)
        assert migrate_0_5._temporary_of(by_alias, by_alias / target).name == left.name
        seen_there = []
        real = migrate_0_5.replace_when_free

        def looked(source, to):
            if Path(source).parent.name == "moving":
                seen_there.append(sorted(path.name for path in (by_alias / migrate_0_5.MOVING).iterdir()))
            return real(source, to)

        monkeypatch.setattr(migrate_0_5, "replace_when_free", looked)
        migrate_0_5.run(by_alias)
        # The renames out of the folder were seen at all, and the copy's own among them, under the name of the one left:
        # without these two the next line holds of nothing, or of the records' temporaries alone
        assert seen_there, "no rename out of the folder of temporaries was seen: the test watched nothing"
        assert [left.name] in seen_there, (left.name, seen_there)
        assert all(len(names) == 1 for names in seen_there), seen_there  # never two at once: the one left was taken up
        assert tree_of(root) == tree_of(whole) and not os.path.lexists(root / migrate_0_5.MOVING)

    def test_the_name_is_made_of_the_records_own_words_whatever_form_the_disk_has_the_name_in(self, work):
        """A record's path is hashed as the record writes it: the same on a disk that keeps the name in the other of Unicode's forms, or in other letter case."""
        import unicodedata

        root = empty_store(work)
        name = "café-ñandú.parquet"
        composed, decomposed = unicodedata.normalize("NFC", name), unicodedata.normalize("NFD", name)
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, f"_data/{decomposed}", K)  # as a sync from another system wrote it
        record(root, "acme/q", "2025-10-01", "e", [(f"_data/{composed}", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [(f"_data/{composed}", K, q1, None)], made_by="pin")
        clear()
        copies = [step for step in migrate_0_5.plan(root).steps if step.op == "copy"]
        assert [step.target for step in copies] == [f"snapshots/acme+q/{q2}/_data/{composed}"]
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == 1 else None)
        clear()
        again = [step for step in migrate_0_5.plan(root).steps if step.op == "copy"]
        assert [step.target for step in again] == [step.target for step in copies]
        migrate_0_5.run(root)
        assert reads_after(root)[("acme+q", q2, f"_data/{composed}")][0] == sha(K) and not os.path.lexists(root / migrate_0_5.MOVING)


class _DiesWriting:
    """A file opened for writing that takes so many bytes and then is killed."""

    def __init__(self, file, after: int):
        self.file, self.after = file, after

    def write(self, block):
        part = block[: self.after]
        self.file.write(part)
        self.file.flush()
        self.after -= len(part)
        if len(part) < len(block) or self.after == 0:
            raise Stop()
        return len(block)

    def __getattr__(self, name):
        return getattr(self.file, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.file.close()
        return False


BIG = bytes(range(256)) * 10240 + b"the end of it"  # 2.5 MB: three blocks of a copy


class TestACopyKilledWhileItIsWritten:
    """A temporary that holds part of a file is never put in place for the file."""

    @pytest.mark.parametrize("after", [0, 1, 1 << 20, (1 << 20) + 5, len(BIG) - 1, len(BIG)], ids=["no byte", "one byte", "one block", "a block and five bytes", "all but one byte", "every byte, before it is flushed"])
    @pytest.mark.parametrize("journal", ["kept", "deleted"])
    def test_run_again_the_file_in_place_has_the_bytes_of_the_file(self, work, monkeypatch, after, journal):
        root = empty_store(work)
        q1, q2 = two_pins(root, BIG, "big.parquet")
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        clear()
        target = root / "snapshots" / "acme+q" / q2 / "_data" / "big.parquet"
        left = migrate_0_5._temporary_of(root, target)
        real_open = builtins.open

        def dying(file, mode="r", *args, **kwargs):
            opened = real_open(file, mode, *args, **kwargs)
            if mode == "wb" and Path(os.fspath(file)) == left:
                return _DiesWriting(opened, after)
            return opened

        with monkeypatch.context() as patch:
            patch.setattr(migrate_0_5, "open", dying, raising=False)
            with pytest.raises(Stop):
                migrate_0_5.run(root)
        assert left.stat().st_size == after and not os.path.lexists(target)
        if journal == "deleted":
            (root / migrate_0_5.JOURNAL).unlink()
        clear()
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == hashlib.sha256(BIG).hexdigest()
        assert strictly_not_its_own(gone, root) == [] and tree_of(root) == tree_of(whole)
        assert not os.path.lexists(root / migrate_0_5.MOVING)

    def test_a_temporary_of_the_files_own_size_and_other_bytes_is_not_put_in_place(self, work):
        """What a sync that sets a file's length first has brought of another machine's temporary: the size of the file, and no byte of it."""
        root = empty_store(work)
        q1, q2 = two_pins(root)
        target = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet"
        left = migrate_0_5._temporary_of(root, target)
        left.parent.mkdir(parents=True)
        left.write_bytes(bytes(len(K)))
        done = migrate_0_5.run(root)
        assert target.read_bytes() == K and done.copied_as_is == [] and not os.path.lexists(root / migrate_0_5.MOVING)


def _last_lines(output: str) -> list:
    return output[output.index("has this version's layout"):].splitlines()[1:]


class TestKilledBetweenTheLastStepsOfAMove:
    """The old folder goes aside, ``store.json`` says the new layout, the folder of temporaries goes, and the journal goes last. Killed between any two and run again: the same tree, nothing left, and the same last lines."""

    KILLS = ["the old folder is aside", "store.json is written and not yet in place", "store.json is in place", "before the temporaries go", "the temporaries are gone and the journal is not"]

    def _kill(self, monkeypatch, root, where: str) -> None:
        steps = len(migrate_0_5.plan(root).steps)
        clear()
        with monkeypatch.context() as patch:
            after_step = lambda done: None  # noqa: E731
            if where == "the old folder is aside":
                after_step = lambda done: (_ for _ in ()).throw(Stop()) if done == steps else None  # noqa: E731
            elif where.startswith("store.json"):
                real = migrate_0_5.replace_when_let

                def killed(source, target):
                    if Path(target) == root / "store.json":
                        if "not yet" not in where:
                            real(source, target)
                        raise Stop()
                    return real(source, target)

                patch.setattr(migrate_0_5, "replace_when_let", killed)
            else:
                real_clear = migrate_0_5._clear_temporaries

                def killed_clearing(of):
                    if where.startswith("the temporaries are gone"):
                        real_clear(of)
                    raise Stop()

                patch.setattr(migrate_0_5, "_clear_temporaries", killed_clearing)
            with pytest.raises(Stop):
                migrate_0_5.run(root, after_step=after_step)
        clear()

    @pytest.mark.parametrize("journal", ["kept", "deleted"])
    @pytest.mark.parametrize("where", KILLS)
    def test_it_ends_in_the_tree_of_an_uninterrupted_move_with_nothing_left(self, work, monkeypatch, where, journal):
        root = empty_store(work)
        rich(root)
        (root / migrate_0_5.MOVING).mkdir(parents=True)
        (root / migrate_0_5.MOVING / ("0" * 24)).write_bytes(b"left by a run before, of no step of this plan")
        whole = work / "whole"
        shutil.copytree(root, whole)
        clear()
        migrate_0_5.run(whole)
        self._kill(monkeypatch, root, where)
        if journal == "deleted" and (root / migrate_0_5.JOURNAL).is_file():
            (root / migrate_0_5.JOURNAL).unlink()
        if not migrate_0_5.to_move(root):
            # The command has nothing to do here: the store is moved, and no journal says a move is under way
            assert journal == "deleted" and migrate_0_5.marker_of(root) == "chartbook/store/v3"
            left = [name for name in names_of(root) if name.startswith(migrate_0_5.MOVING)]
            assert left == [], f"the store is moved, the command says there is nothing to move, and these stay for good: {left}"
            return
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert strictly_not_its_own(gone, root) == []
        assert tree_of(root) == tree_of(whole)
        assert not os.path.lexists(root / migrate_0_5.MOVING) and not os.path.lexists(root / migrate_0_5.JOURNAL)

    @pytest.mark.parametrize("where", KILLS)
    def test_with_its_journal_the_last_lines_are_those_of_an_uninterrupted_move(self, work, monkeypatch, where):
        """What the whole move came to is carried in the journal: the lines a person reads at the end are the same, whichever of the last steps the first run was killed at."""
        root = empty_store(work)
        rich(root)
        whole = work / "whole"
        shutil.copytree(root, whole)
        clear()
        monkeypatch.setenv(config.STORE_ENV_VAR, str(whole))
        uninterrupted = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert uninterrupted.exit_code == 0, uninterrupted.output
        wanted = [line.replace(str(whole), "STORE") for line in _last_lines(uninterrupted.output)]
        self._kill(monkeypatch, root, where)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        again = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert again.exit_code == 0, again.output
        said = [line.replace(str(root), "STORE") for line in _last_lines(again.output)]
        assert len(said) == len(set(said)), "a line is said twice"
        assert said == wanted, "\n".join(["", "--- uninterrupted ---", *wanted, "--- killed and run again ---", *said])


class TestAFileNamedAsTheOldTemporariesWere:
    """Before this round a temporary was ``<name>.moving`` beside where its file goes. A file of such a name is anyone's now: it is moved, or goes aside, or stays; it is never removed."""

    def test_one_no_record_names_in_a_snapshots_folder_goes_aside_as_it_is(self, work, monkeypatch):
        root = empty_store(work)
        q1, q2 = two_pins(root)
        put(root, "acme+q", q1, "_data/k.parquet.moving", b"a pipeline's own file of this name")
        put(root, "acme+q", q1, "_chartbook/snapshot.json.moving", b"and one beside the record")
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert strictly_not_its_own(gone, root) == [] and not_its_own(gone) == []
        aside = root / ASIDE / "pipelines" / "acme+q" / q1
        assert (aside / "_data" / "k.parquet.moving").read_bytes() == b"a pipeline's own file of this name"
        assert (aside / "_chartbook" / "snapshot.json.moving").read_bytes() == b"and one beside the record"

    def test_what_the_mover_of_before_left_in_the_new_trees_is_not_removed_and_not_taken_for_the_file(self, work, monkeypatch):
        """A move by the mover of before this round was killed while it copied: half a file is at ``<target>.moving`` in the new tree, and its journal's temporary beside the journal. This mover goes on from the folders: the copy is made whole, and what was left stays as it is (nobody's to remove)."""
        root = empty_store(work)
        q1, q2 = two_pins(root)
        steps = migrate_0_5.plan(root).steps
        renamed = next(number for number, step in enumerate(steps, 1) if step.op == "rename")
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == renamed else None)
        rmtree(root / migrate_0_5.MOVING) if (root / migrate_0_5.MOVING).exists() else None
        old = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet.moving"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(K[:150])
        (root / "_chartbook" / "move-to-v3.jsonl.moving").write_bytes(b"half a journal")
        clear()
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert strictly_not_its_own(gone, root) == []
        assert (root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet").read_bytes() == K
        assert old.read_bytes() == K[:150] and (root / "_chartbook" / "move-to-v3.jsonl.moving").read_bytes() == b"half a journal"


class TestWhatTheWatchTakesForTheMovesOwn:
    """``tests.rich_store_of_0_5.not_its_own`` takes everything under ``_chartbook/moving`` for the move's own. Read more narrowly (a file directly in it, and nothing outside the store), every step of a move of the rich store still removes nothing of anyone's."""

    def test_stopped_after_every_step_a_move_of_the_rich_store_removes_nothing_by_the_narrower_reading(self, work, monkeypatch):
        root = empty_store(work)
        rich(root)
        clear()
        steps = len(migrate_0_5.plan(root).steps)
        wrong = []
        for number in range(1, steps + 2):
            cut = work / "cut"
            shutil.copytree(root, cut, symlinks=True)
            clear()
            gone: list = []
            with monkeypatch.context() as patch:
                watch(patch, cut, gone)
                try:
                    migrate_0_5.run(cut, after_step=lambda done, number=number: (_ for _ in ()).throw(Stop()) if done == number else None)
                except Stop:
                    pass
                clear()
                migrate_0_5.run(cut)
            if strictly_not_its_own(gone, cut):
                wrong.append((number, strictly_not_its_own(gone, cut)[:4]))
            rmtree(cut)
        assert wrong == []

    def test_the_narrower_reading_tells_a_removal_beside_the_folder_and_below_it(self, work):
        root = work / "store"
        gone = [
            ("unlink", "_chartbook/moving/" + "a" * 24), ("rmdir", "_chartbook/moving"), ("unlink", "_chartbook/moving.txt"),
            ("unlink", "_chartbook/moving/somebody's/note.txt"), ("unlink", str(work / "outside.bin")), ("replace onto", "store.json"),
        ]
        assert set(strictly_not_its_own(gone, root)) == {("unlink", "_chartbook/moving.txt"), ("unlink", "_chartbook/moving/somebody's/note.txt"), ("unlink", str(work / "outside.bin"))}
        # The suite's own reading passes over the two that are not beside the folder
        assert not_its_own(gone) == [("unlink", "_chartbook/moving.txt")]


class TestAMovedStoreThatStillHasTheMovesOwnFolder:
    """Q3. Killed once ``store.json`` said the new layout, and its journal then removed: the store is moved, no journal says a move is under way, and the folder of temporaries stayed for good, the command saying there was nothing to move."""

    def _left(self, store, monkeypatch, with_a_file: bool) -> Path:
        two_pins(store)
        own = store / migrate_0_5.MOVING
        if with_a_file:
            own.mkdir(parents=True)
            (own / ("0" * 24)).write_bytes(b"left by a run before, of no step of this plan")
        real = migrate_0_5._clear_temporaries
        with monkeypatch.context() as patch:
            patch.setattr(migrate_0_5, "_clear_temporaries", lambda root: (_ for _ in ()).throw(Stop()))
            with pytest.raises(Stop):
                migrate_0_5.run(store)
        assert migrate_0_5._clear_temporaries is real
        (store / migrate_0_5.JOURNAL).unlink()
        clear()
        assert migrate_0_5.marker_of(store) == "chartbook/store/v3" and own.is_dir() and not migrate_0_5.old_left(store)
        return own

    @pytest.mark.parametrize("with_a_file", [False, True], ids=["the folder alone", "a file in it"])
    def test_the_command_has_something_to_do_and_removes_it_without_a_question(self, store, monkeypatch, with_a_file):
        own = self._left(store, monkeypatch, with_a_file)
        assert migrate_0_5.to_move(store) and migrate_0_5.temporaries_left(store)
        before = names_of(store)
        dry = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        assert dry.exit_code == 0 and names_of(store) == before
        assert dry.output.splitlines() == [
            f"The store at {store_module.FolderStore(store)} has this version's layout, and the folder a move keeps its own temporary files in is still there "
            f"(_chartbook/moving/): a move was cut short as it ended. It would be removed: nothing in it is a file of the store's.",
            "Nothing was moved.",
        ]
        result = CliRunner().invoke(main, ["store", "migrate"])  # no answer is given: none is asked for
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [dry.output.splitlines()[0].replace("It would be removed", "It is removed")]
        assert not os.path.lexists(own) and sorted(set(before) - set(names_of(store))) == sorted(name for name in before if name.startswith(migrate_0_5.MOVING))
        clear()
        assert not migrate_0_5.to_move(store) and store_module.FolderStore(store).verify() == []
        again = CliRunner().invoke(main, ["store", "migrate"])
        assert again.exit_code == 0 and "nothing to move" in again.output

    def test_a_folder_somebody_made_in_it_is_nothing_for_the_command_to_do(self, store, monkeypatch):
        """No file the move wrote: it stays, and the command does not say each time that it removes what it leaves."""
        own = self._left(store, monkeypatch, with_a_file=False)
        (own / "somebody's").mkdir()
        (own / "somebody's" / "note.txt").write_bytes(b"kept")
        assert not migrate_0_5.temporaries_left(store) and not migrate_0_5.to_move(store)
        result = CliRunner().invoke(main, ["store", "migrate"])
        assert result.exit_code == 0 and "nothing to move" in result.output and (own / "somebody's" / "note.txt").read_bytes() == b"kept"

    @needs_symlinks
    def test_a_link_where_the_folder_was_is_nothing_of_the_moves(self, store, monkeypatch, work):
        own = self._left(store, monkeypatch, with_a_file=False)
        outside = work / "outside-folder"
        outside.mkdir()
        (outside / "kept.txt").write_bytes(b"kept")
        os.rmdir(own)
        os.symlink(outside, own, target_is_directory=True)
        assert not migrate_0_5.temporaries_left(store) and not migrate_0_5.to_move(store)
        assert (outside / "kept.txt").read_bytes() == b"kept"


WAIT = "If another machine moved it, a sync may still be bringing the rest: wait for the sync to finish, and move nothing here."


def _moved_elsewhere(store, work, data_too: bool) -> tuple:
    """A store of 0.5, whole here, that another machine has moved and finished. The sync has brought here: the new trees' folders, records and notes (with *data_too*, their files as well), and the folder that machine put aside. Not yet: ``store.json``; and it has not taken ``pipelines/`` away."""
    s1 = folder_of("2025-10-01", "a")
    put(store, "acme+p", s1, "_data/a.parquet", A)
    record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
    s2 = folder_of("2025-11-01", "b")
    put(store, "acme+p", s2, "_data/b.parquet", B)
    record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, s1, None), ("_data/b.parquet", B, None, None)])
    theirs = work / "theirs"
    shutil.copytree(store, theirs)
    clear()
    migrate_0_5.run(theirs)
    for tree in ("snapshots", "increments"):
        for path in sorted((theirs / tree).rglob("*")):
            target = store / path.relative_to(theirs)
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif data_too or "_chartbook" in path.parts or path.name == "README.txt":
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    shutil.copytree(theirs / "_chartbook" / "left-by-0.5", store / "_chartbook" / "left-by-0.5")
    clear()
    assert migrate_0_5.marker_of(store) == "chartbook/store/v2" and not (store / migrate_0_5.JOURNAL).exists() and migrate_0_5.new_there(store)
    return s1, s2


class TestAStoreOf05WithASignOfAMoveAndNoJournalOfThisMachine:
    """Q1. Another machine moved the store and finished: no journal. Here the sync has brought the new trees and what that machine put aside, ``_chartbook/left-by-0.5/pipelines/`` (the last thing its move renamed, and a folder, which a sync makes before it has the files); not yet ``store.json``, and it has not taken ``pipelines/`` away.

    The command took such a store for one whose own move was cut short
    at its end, said "it is finished now", and asked. It says now what
    every other command says: wait for the sync.
    """

    @pytest.mark.parametrize("data_too", [False, True], ids=["its records have come and its files have not", "its files have come too"])
    def test_with_what_the_other_machine_put_aside_brought_too_it_is_still_told_to_wait_for_the_sync(self, store, work, data_too):
        _moved_elsewhere(store, work, data_too)
        with pytest.raises(store_module.StoreError):
            store_module.FolderStore(store).records()  # no other command uses the store as it is
        before = tree_of(store)
        for words, answer in ((["--dry-run"], None), ([], "n\n")):
            clear()
            result = CliRunner().invoke(main, ["store", "migrate", *words], input=answer)
            assert result.exit_code == 0, result.output
            assert tree_of(store) == before
            first = result.output.splitlines()[0]
            assert first == (
                f"The store at {store_module.FolderStore(store)} has the layout of ChartBook 0.5, and what a move to this version's layout puts aside "
                f"is there already (_chartbook/left-by-0.5/), with no journal of a move on this machine. {WAIT} If a move on this machine was "
                f"cut short at its end, this finishes it. What ChartBook 0.5 keeps at a store's top is there (pipelines/, roots/): a yes moves its "
                f"notes under _chartbook/ and puts pipelines/ aside whole. Nothing under it is moved in, and a file there that a snapshot lacks "
                f"does not reach it."
            )
            assert "it is finished now" not in result.output and result.output.splitlines()[-1] == "Nothing was moved."

    @pytest.mark.parametrize("aside", ["its folders alone, no file yet", "nothing of it"], ids=["the folders of what went aside", "nothing of what went aside"])
    def test_how_little_of_what_the_other_machine_put_aside_makes_the_store_one_whose_move_ended(self, store, work, aside):
        """With nothing of what went aside the store is the one that "looks half moved"; with its folders alone (a sync makes folders before it has their files) it is taken for one whose old folder is aside. Either way it is told to wait, before the question."""
        _moved_elsewhere(store, work, data_too=False)
        theirs_aside = work / "theirs" / "_chartbook" / "left-by-0.5"
        ours_aside = store / "_chartbook" / "left-by-0.5"
        rmtree(ours_aside)
        if aside.startswith("its folders"):
            for path in sorted(theirs_aside.rglob("*")):
                if path.is_dir():
                    (ours_aside / path.relative_to(theirs_aside)).mkdir(parents=True, exist_ok=True)
            assert any(path.is_dir() for path in (ours_aside / "pipelines").iterdir()) and not any(path.is_file() for path in ours_aside.rglob("*"))
        clear()
        result = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        assert result.exit_code == 0, result.output
        first = result.output.splitlines()[0]
        assert ("looks half moved" in first) == (aside == "nothing of it") and migrate_0_5.is_moved(store) == (aside != "nothing of it")
        assert WAIT in first and "it is finished now" not in result.output

    def test_what_a_yes_there_does_is_said_before_the_question_and_after_it_and_nothing_is_removed(self, store, work):
        """Known, and left: the store read whole to 0.5 on this machine, and a yes against the warning puts this machine's ``pipelines/`` aside, with every file; the snapshots are then the records the sync has brought so far, until it brings their files.

        Nothing under a ``pipelines/`` that is there once the old folder is
        aside is moved in (the third rule of the move): a rule that moved
        this machine's files in here would move a late snapshot in where a
        machine still on 0.5 wrote one, which is the case that rule is
        for, and the folders do not tell the two apart. What is held: the
        lines say it before the question and name the files after it, and
        every file is still in the store.
        """
        s1, s2 = _moved_elsewhere(store, work, data_too=False)
        before = facts_by_folder(store)
        assert len(before) == 3 and all(at_place for _, _, at_place, _, _ in before.values())
        said = CliRunner().invoke(main, ["store", "migrate", "--dry-run"]).output
        assert "  2 file(s) arrived for a snapshot that is moved already, and go aside" in said
        result = CliRunner().invoke(main, ["store", "migrate"], input="y\n")
        assert result.exit_code == 0, result.output
        last = result.output[result.output.index("has this version's layout"):]
        assert "  2 file(s) arrived for a snapshot that is moved already, and went aside" in last
        held = {hashlib.sha256(path.read_bytes()).hexdigest() for path in store.rglob("*") if path.is_file()}
        assert {hashlib.sha256(data).hexdigest() for data in (A, B)} <= held
        assert (store / ASIDE / "pipelines (2)" / "acme+p" / s1 / "_data" / "a.parquet").read_bytes() == A

    def test_with_this_machines_journal_it_is_what_it_was_said_to_be_and_no_question_is_asked(self, store):
        """This machine's own move, killed between the old folder going aside and ``store.json``: its journal says whose it is."""
        rich(store)
        clear()
        steps = len(migrate_0_5.plan(store).steps)
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == steps else None)
        clear()
        assert migrate_0_5.is_moved(store) and (store / migrate_0_5.JOURNAL).is_file()
        result = CliRunner().invoke(main, ["store", "migrate"])  # no answer is given: none is asked for
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0] == (
            f"A move of the store at {store_module.FolderStore(store)} to this version's layout was cut short at its end, its old folder aside already: it is finished now."
        )
        assert "sync may still be bringing" not in result.output.splitlines()[0] and migrate_0_5.marker_of(store) == "chartbook/store/v3"


class TestWhatWentWithAJournalThatIsGone:
    """Q4. What the whole move came to is carried in its journal. Removed by hand, as two of the command's own messages say to, it takes the counts with it: the last lines leave them out, and do not say 0."""

    def test_cut_short_at_its_end_and_its_journal_removed_the_last_lines_do_not_say_that_nothing_was_renamed(self, store):
        rich(store)
        clear()
        steps = len(migrate_0_5.plan(store).steps)
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=lambda done: (_ for _ in ()).throw(Stop()) if done == steps else None)
        (store / migrate_0_5.JOURNAL).unlink()
        clear()
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0, result.output
        first = result.output.splitlines()[0]
        assert "was cut short at its end" in first and WAIT in first and "it is finished now" not in first
        last = result.output[result.output.index("has this version's layout"):].splitlines()
        renamed = sum(1 for path in (store / "snapshots").rglob("*.parquet")) + sum(1 for path in (store / "increments").rglob("*.parquet"))
        assert renamed > 0
        assert not any(" 0 file(s)" in line for line in last), last
        # What the folders say is said; what went with the journal is said to have gone with it, with where the old folder is
        assert last[0].endswith("has this version's layout: 3 pipeline(s), 10 snapshot(s).")
        assert "  7 snapshot(s) became complete (5 of them made by a pin), 3 became increments on the newest of their pipeline." in last
        assert last[-2] == (
            "  How many files the move renamed, copied and put aside went with its journal, which is gone. The old folder is under "
            "_chartbook/left-by-0.5/: it may be removed once the move has been checked. 2 file(s) are missing, and one may be in that folder "
            "(in a second copy of its snapshot's folder, as a sync names one: `<name> 2`): look there first."
        )
        assert last[-1] == "In a synced folder, let the sync finish before another machine uses the store."


class TestTheHelpersFindAFileAsTheStoresReaderDoes:
    """Q7a. A file whose name the disk has in the other of Unicode's forms than its record writes. On a disk that tells the two apart (NTFS, most of Linux) the helpers of these tests asked for it by the record's name, found nothing, and expected it among the missing; the mover finds it, as the store's reader does, and was right.

    This Mac's disk does not tell the forms apart, so such a disk is
    stood in for: a path whose name is not ASCII is there only where
    its folder lists that name letter for letter.
    """

    def _a_disk_exact_about_names(self, monkeypatch) -> None:
        def listed(path: Path) -> bool:
            try:
                return path.name in os.listdir(path.parent)
            except OSError:
                return False

        for question in ("exists", "is_file", "is_dir", "is_symlink"):
            real = getattr(Path, question)
            monkeypatch.setattr(Path, question, lambda self, real=real: (self.name.isascii() or listed(self)) and real(self))

    def test_on_a_disk_that_tells_the_two_forms_apart_the_file_is_at_its_place_to_the_helpers_as_it_is_to_the_move(self, work, monkeypatch):
        import unicodedata

        from tests.found_store_of_0_5 import _holds, facts_before

        root = empty_store(work)
        composed, decomposed = (unicodedata.normalize(form, "café-ñandú.parquet") for form in ("NFC", "NFD"))
        s = folder_of("2025-10-01", "a")
        put(root, "acme+p", s, f"_data/{decomposed}", K)  # as a sync from another system wrote it
        record(root, "acme/p", "2025-10-01", "a", [(f"_data/{composed}", K, None, None)])
        there = os.listdir(root / "pipelines" / "acme+p" / s / "_data")
        if there != [decomposed]:
            pytest.skip("this disk does not keep a name in the form it was written in")
        self._a_disk_exact_about_names(monkeypatch)
        by_the_records_name = root / "pipelines" / "acme+p" / s / "_data" / composed
        # The stand-in holds: nothing is there by the name the record writes, which is what the helpers asked by
        assert not by_the_records_name.exists() and not _holds(by_the_records_name, (sha(K), len(K)))
        key = ("acme+p", s, f"_data/{composed}")
        facts = facts_by_folder(root)
        assert facts[key][2:4] == (True, True) and facts[key][4] == f"pipelines/acme+p/{s}/_data/{decomposed}"
        assert facts_before(root)[("acme/p", s, f"_data/{composed}")][1:] == (True, True)
        # And so what a test expects of the move is what the move finds: nothing is missing
        found = migrate_0_5.plan(root)
        assert found.missing == [] and found.missing_in == [] and found.renamed == 1
        done = migrate_0_5.run(root)
        assert done.missing == [] and reads_after(root)[key][0] == sha(K)

    @pytest.mark.parametrize("seed", [2, 7])
    def test_the_two_drawn_stores_that_failed_on_such_a_disk_hold_on_the_stand_in(self, work, monkeypatch, seed):
        """``test_every_number_of_the_plan_is_true_of_the_tree_before_and_after[2-2]`` and ``[7-2]`` failed on NTFS at what the helpers expected to be missing: the same two stores, with two pipelines, on the stand-in."""
        from tests.found_store_of_0_5 import drawn_store
        from tests.test_migrate_0_5_review2 import test_every_number_of_the_plan_is_true_of_the_tree_before_and_after as held

        probe = empty_store(work, "probe")
        assert "other form" in drawn_store(probe, seed, 2, in_the_new_trees=False)["shapes"]  # the store has such a file
        rmtree(probe)
        clear()
        self._a_disk_exact_about_names(monkeypatch)
        held(work, seed, 2)
