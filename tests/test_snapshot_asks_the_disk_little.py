"""A snapshot of a table of many small files asks the store little for each file.

A store may be a folder a sync service keeps, where each question to the
disk (is this file there, how large is it, open it) costs a thousand times
what it costs on a disk of one's own. A table kept as a folder of small
files, one a day, is thousands of files, and a snapshot of it that adds
twenty of them is kept as an increment: twenty files are copied. What it
asks of the store must not grow with the files it does not copy, beyond
one look at each to know that the snapshot it builds on still has it.

Measured on 2026-11-20, before the rules these tests hold, the second
snapshot of such a table asked the store 26 questions for each file of the
table, and read every one of them back from it.

The second snapshot is counted here by wrappers that count and call
through, for two sizes of table, so that what grows with the table shows.
Before it is made, what the process remembers of the first is forgotten:
a second ``chartbook snapshot`` is another process.
"""

from __future__ import annotations

import builtins
import glob as glob_module
import io
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import rowhash
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import _git, kept_out_of_home, remove_tree

#: The wrappers count calls of ``os.stat`` and the like. Before Python 3.12 ``pathlib`` asks the disk through
#: functions it bound when it was imported, which a patch of ``os.stat`` does not reach: nothing is counted there
counted = pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="a patch of os.stat does not reach pathlib's own methods before Python 3.12, so the questions cannot be counted",
)

#: The files of the table at the first snapshot, for the two tables counted, and the files added before the second.
SIZES = (40, 100)
NEW = 20

FIRST_DAY = date(2019, 1, 1)

MANIFEST = {
    "project": {"id": "acme/daily", "name": "Daily"},
    "dataframes": {
        "daily": {"path": "./_data/parts/**/*.parquet", "date_col": "ds", "docs": "One file a day."},
        "codes": {"path": "./_data/codes.parquet", "docs": "Codes."},
    },
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "codes", "docs": "The curve."}},
}


# --- A pipeline whose table is a file a day -----------------------------------------


def _write_days(folder: Path, first: int, count: int) -> None:
    """Write *count* days of the table from day *first*, each a file of three rows in the folder of its month."""
    for number in range(first, first + count):
        day = FIRST_DAY + timedelta(days=number)
        file = folder / "_data" / "parts" / day.strftime("%Y-%m") / f"{day.isoformat()}.parquet"
        file.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            {"ds": [day] * 3, "unique_id": ["T0", "T1", "T2"], "y": [4.0 + number * 0.01 + i for i in range(3)]}
        ).write_parquet(file)


def _pipeline(folder: Path, files: int) -> Path:
    """A pipeline in a repository of its own, built: the table in *files* parts, a small table, a chart and a README."""
    (folder / "_data").mkdir(parents=True)
    (folder / "chartbook.toml").write_text(tomli_w.dumps(MANIFEST), encoding="utf-8", newline="\n")
    (folder / "README.md").write_text("# Daily\n\nOne file a day.\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("_data/\n_output/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    _write_days(folder, 0, files)
    pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]}).write_parquet(folder / "_data" / "codes.parquet")
    (folder / "_output").mkdir()
    (folder / "_output" / "curve.html").write_text("<html><body>curve</body></html>", encoding="utf-8", newline="\n")
    _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Work")
    return folder


#: What a module of ChartBook remembers for as long as its process lives, by the name it keeps it under.
REMEMBERED = (
    "_read_records", "_found_whole", "_hashed_once", "_compared", "_raw_manifest_cache", "_lock_cache", "_snapshot_cache",
    "_ids_cache", "_tried", "_git_remote_cache", "_git_top_cache", "_project_root_cache", "_read_snapshots",
)


def _as_another_process() -> None:
    """Forget what this process remembers of the store and of the folder: the next command is another process's."""
    for name, module in list(sys.modules.items()):
        if name == "chartbook" or name.startswith("chartbook."):
            for held in REMEMBERED:
                if isinstance(getattr(module, held, None), (dict, set)):
                    getattr(module, held).clear()


# --- Counting what is asked ----------------------------------------------------------


@dataclass
class Asked:
    """What the second snapshot of one table asked, and said.

    Attributes:
        files: How many files the table has at the second snapshot.
        store: Each kind of question asked of the store, with how many times.
        sweeps: How many times a pipeline's folder was swept.
        note_lines: Each line written to the note of the snapshot being made.
        note_times: How many times the note's time was set.
        looks: For each file of the snapshot built on, how many times it was asked whether it is whole.
        records: For each record opened to be read, by who read it, how many times.
        table_reads: Each read of a file of the table in the store, by what read it.
        output: What the command printed.
        built_on: The folder of the complete snapshot, relative to the store.
    """

    files: int
    store: Counter = field(default_factory=Counter)
    sweeps: int = 0
    note_lines: list = field(default_factory=list)
    note_times: int = 0
    looks: Counter = field(default_factory=Counter)
    records: Counter = field(default_factory=Counter)
    table_reads: Counter = field(default_factory=Counter)
    output: str = ""
    built_on: str = ""

    def of_the_store(self) -> int:
        """Every question asked of the store, of whatever kind."""
        return sum(self.store.values())


def _reader(depth: int = 2) -> str:
    """The function of ChartBook nearest the call, as ``module.function``."""
    frame = sys._getframe(depth)
    marker = os.sep + os.path.join("chartbook", "")
    while frame is not None:
        name = frame.f_code.co_filename
        if marker in name and os.sep + "tests" + os.sep not in name:
            return f"{os.path.basename(name)[:-3]}.{frame.f_code.co_name}"
        frame = frame.f_back
    return ""


def _counting(patch: pytest.MonkeyPatch, asked: Asked, root: Path) -> None:
    """Wrap what asks the disk, so that each question of the store is counted; each wrapper calls through."""
    store = str(root)

    def in_store(path) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fsdecode(os.fspath(path))
        except TypeError:
            return False
        if not os.path.isabs(text):
            text = os.path.join(os.getcwd(), text)
        return text == store or text.startswith(store + os.sep)

    def of_the_table(path) -> bool:
        return in_store(path) and os.sep + "parts" + os.sep in os.fsdecode(os.fspath(path))

    def wrapped(original, what, place=0, name="path"):
        def wrapper(*args, **kwargs):
            path = args[place] if len(args) > place else kwargs.get(name, ".")
            if in_store(path):
                asked.store[what] += 1
            return original(*args, **kwargs)
        return wrapper

    resolving = [0]
    stat, lstat, realpath = os.stat, os.lstat, os.path.realpath

    def counted_stat(path, *args, **kwargs):
        if not resolving[0] and in_store(path):
            asked.store["stat" if kwargs.get("follow_symlinks", True) else "lstat"] += 1
        return stat(path, *args, **kwargs)

    def counted_lstat(path, *args, **kwargs):
        if not resolving[0] and in_store(path):
            asked.store["lstat"] += 1
        return lstat(path, *args, **kwargs)

    def counted_realpath(filename, *args, **kwargs):
        # One question, however a system answers it: on POSIX it looks at each folder down the path
        if in_store(filename):
            asked.store["realpath"] += 1
        resolving[0] += 1
        try:
            return realpath(filename, *args, **kwargs)
        finally:
            resolving[0] -= 1

    patch.setattr(os, "stat", counted_stat)
    patch.setattr(os, "lstat", counted_lstat)
    patch.setattr(os.path, "realpath", counted_realpath)
    scandir = wrapped(os.scandir, "list")
    patch.setattr(os, "scandir", scandir)
    patch.setattr(os, "listdir", wrapped(os.listdir, "list"))
    globber = getattr(glob_module, "_StringGlobber", None)  # pathlib's glob keeps the two it uses
    if globber is not None:
        patch.setattr(globber, "scandir", staticmethod(scandir))
        patch.setattr(globber, "lstat", staticmethod(counted_lstat))

    opened = builtins.open

    def counted_open(file, mode="r", *args, **kwargs):
        if in_store(file):
            writes = any(letter in mode for letter in "wxa+")
            asked.store["open to write" if writes else "open to read"] += 1
            if not writes and os.path.basename(os.fspath(file)) == "snapshot.json":
                asked.records[(os.path.relpath(os.fspath(file), store), _reader())] += 1
            if not writes and of_the_table(file):
                asked.table_reads[_reader()] += 1
        return opened(file, mode, *args, **kwargs)

    patch.setattr(builtins, "open", counted_open)
    patch.setattr(io, "open", counted_open)
    patch.setattr(os, "open", wrapped(os.open, "open"))

    utime = os.utime

    def counted_utime(path, *args, **kwargs):
        if in_store(path):
            asked.store["utime"] += 1
            if str(path).endswith(store_module.PENDING_SUFFIX):
                asked.note_times += 1
        return utime(path, *args, **kwargs)

    patch.setattr(os, "utime", counted_utime)
    for name in ("mkdir", "unlink", "remove", "rmdir", "chmod", "readlink"):
        patch.setattr(os, name, wrapped(getattr(os, name), "other"))
    for name in ("replace", "rename", "link", "symlink"):
        patch.setattr(os, name, wrapped(getattr(os, name), "other", place=1, name="dst"))

    # What the wrappers above do not see: a file pyarrow or polars opens itself
    import pyarrow.parquet as pq

    def read_by(original, what, place=0, name="file"):
        def wrapper(*args, **kwargs):
            source = args[place] if len(args) > place else kwargs.get(name)
            first = source[0] if isinstance(source, (list, tuple)) and source else source
            if of_the_table(first):
                asked.store["opened by pyarrow or polars"] += 1
                asked.table_reads[what] += 1
            return original(*args, **kwargs)
        return wrapper

    patch.setattr(rowhash, "_parquet_batches", read_by(rowhash._parquet_batches, "rowhash._parquet_batches"))
    patch.setattr(pq, "ParquetFile", read_by(pq.ParquetFile, "pyarrow.parquet.ParquetFile", name="source"))
    patch.setattr(pl, "scan_parquet", read_by(pl.scan_parquet, "polars.scan_parquet", name="source"))

    sweep = FolderStore.sweep

    def counted_sweep(self, *args, **kwargs):
        asked.sweeps += 1
        return sweep(self, *args, **kwargs)

    patch.setattr(FolderStore, "sweep", counted_sweep)

    note_line = store_module._FolderPending._note_line

    def counted_note_line(self, line):
        asked.note_lines.append(line)
        return note_line(self, line)

    patch.setattr(store_module._FolderPending, "_note_line", counted_note_line)

    is_whole = store_module._is_whole

    def counted_is_whole(file, pipeline_folder):
        asked.looks[os.path.relpath(str(file.location), store)] += 1
        return is_whole(file, pipeline_folder)

    patch.setattr(store_module, "_is_whole", counted_is_whole)


def _second_snapshot(scratch: Path, files: int) -> Asked:
    """Make a first snapshot of a table of *files* files, add :data:`NEW` days, and count what the second asks, made by the command."""
    from chartbook import snapshot

    root = Path(os.environ["CHARTBOOK_STORE"])
    project = _pipeline(scratch / "project", files)
    first = snapshot.make(project)
    assert first.made and not first.kept.increment
    _write_days(project, files, NEW)
    _as_another_process()
    asked = Asked(files + NEW, built_on=first.kept.folder.relative_to(root).as_posix())
    with pytest.MonkeyPatch.context() as patch:
        _counting(patch, asked, root)
        result = CliRunner().invoke(main, ["snapshot", "--as-is", "--project-dir", str(project)])
    assert result.exit_code == 0, result.output
    asked.output = result.output
    assert f"Snapshot made, kept as an increment: {NEW + 1} of " in result.output, result.output
    return asked


@pytest.fixture(scope="module")
def asked(tmp_path_factory) -> dict:
    """What the second snapshot asked, for a table of each of :data:`SIZES`: counted once, and held against each rule below."""
    found = {}
    for files in SIZES:
        scratch = tmp_path_factory.mktemp(f"asks_the_disk_little_{files}").resolve()
        try:
            with kept_out_of_home(scratch / "home"):
                found[files] = _second_snapshot(scratch, files)
        finally:
            try:
                remove_tree(scratch)
            except OSError:
                pass
    return found


# --- The reminder of `store gc` sweeps nothing ---------------------------------------


@counted
class TestTheReminderSweepsNothing:
    """The line a snapshot ends with is made from a plan of `store gc`, which swept every pipeline's folder for what no snapshot uses: a question about each file of every snapshot in the store, at each snapshot of any pipeline, for a list the line says nothing of."""

    def test_no_folder_is_swept_for_the_line_a_snapshot_ends_with(self, asked):
        assert [found.sweeps for found in asked.values()] == [0, 0]


COMMIT = "a" * 40
LONG_AGO = "2026-01-01T00:{:02d}:00.000000Z"


class TestTheNotesTimeIsSetOnceAMinute:
    """A snapshot being made says by its note's time that it still is, and said it once for each file put and once more for each before the record: two questions of the disk a file, for a note that counts for a day."""

    @counted
    def test_a_snapshot_made_within_the_minute_sets_it_once_at_most(self, asked):
        assert all(found.note_times <= 1 for found in asked.values()), [found.note_times for found in asked.values()]

    def test_however_many_files_it_is_asked_for(self, tmp_path, monkeypatch):
        import time

        store = FolderStore(tmp_path / "store")
        pending = store.begin("acme/sized", COMMIT, LONG_AGO.format(0), undecided=True)
        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        touched = []
        real = os.utime
        monkeypatch.setattr(os, "utime", lambda path, *args, **kwargs: (touched.append(Path(path).name), real(path, *args, **kwargs))[1])
        pending._alive()
        assert touched == []  # nothing is noted yet: there is no note to speak of
        pending._note_line(store_module.FOLDER_MARK + "snapshots/acme+sized/2026-01-01T000000Z_aaaaaaaaaaaa")
        note = pending._note.name
        for _ in range(500):
            pending._alive()
        assert touched == []  # a line written a moment ago has said it
        clock[0] += store_module.ALIVE_SECONDS
        for _ in range(500):
            pending._alive()
        assert touched == [note]
        clock[0] += store_module.ALIVE_SECONDS - 1
        pending._alive()
        assert touched == [note]
        clock[0] += 1
        pending._alive()
        assert touched == [note, note]
        pending.discard()

    def test_a_minute_is_well_within_what_a_note_counts_for(self):
        assert store_module.ALIVE_SECONDS * 60 <= store_module.PENDING_FOLDER_SECONDS


def _chart(project: Path, text: str) -> None:
    """The pipeline draws its chart again: one file of it changes, and its index with it."""
    (project / "_output" / "curve.html").write_text(f"<html><body>{text}</body></html>", encoding="utf-8", newline="\n")


def _files_of(folder: Path) -> set:
    """Every file under a snapshot's folder, by its path in it."""
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def _gc(root: Path):
    """Plan a `store gc` of a store and carry it out, sparing nothing for being new."""
    from chartbook import lock

    return lock.carry_out_gc(lock.plan_gc(FolderStore(root), recent_seconds=0), FolderStore(root))


def _one_gc_may_remove(project: Path, root: Path) -> tuple:
    """A store in which the snapshot the next one builds on is one `store gc` may remove; its three snapshots.

    A complete snapshot; a second complete one that a sync had not brought
    whole when the third was made, so that the third is an increment on the
    first; and then the second is whole after all. The next snapshot builds
    on the second, which is neither the newest nor built on yet, and all
    three are long past.
    """
    from chartbook import snapshot

    first = snapshot.make(project, store=FolderStore(root), made_at=LONG_AGO.format(0))
    _chart(project, "two")
    second = snapshot.make(project, store=FolderStore(root), made_at=LONG_AGO.format(1), complete=True)
    table, aside = second.kept.folder / "_data" / "codes.parquet", root.parent / "not-synced-yet.parquet"
    os.rename(table, aside)
    store_module._found_whole.clear()
    _chart(project, "three")
    third = snapshot.make(project, store=FolderStore(root), made_at=LONG_AGO.format(2))
    assert third.kept.increment and third.kept.builds_on == first.kept.folder.name
    os.rename(aside, table)  # the sync brings it
    store_module._found_whole.clear()
    store_module._read_records.clear()
    return first, second, third


class TestOneNoteForTheFolderItTakesFilesFrom:
    """A snapshot being made noted each file of an earlier snapshot it used, a line a file, twice: an open, a write and a close of the note for each. It notes the folder of the snapshot that keeps them, once.

    What the notes keep `store gc` from, on this machine, while a snapshot
    is being made. Before: the plan of a gc never read them, so it could
    take the record of a snapshot the writer was using; its sweep then
    removed every file of that folder but the ones the note listed. Now:
    the record can go as it could, and the sweep removes nothing at all
    from a folder the note names, until the note has gone (the snapshot
    written, or let go) or is a day old. So the note keeps more, never
    less.
    """

    @counted
    def test_the_note_has_a_line_for_each_folder_and_none_for_a_file(self, asked):
        for found in asked.values():
            mark = store_module.FOLDER_MARK
            assert all(line.startswith(mark) for line in found.note_lines), found.note_lines
            folders = [line[len(mark):] for line in found.note_lines]
            # The one it builds on, once; and its own, under increments/ (the next second's name too, where
            # the first snapshot was made in the same second and has the name)
            assert folders.count(found.built_on) == 1 and len(set(folders)) == len(folders), folders
            own = [folder for folder in folders if folder != found.built_on]
            assert 1 <= len(own) <= 2 and all(folder.startswith("increments/acme+daily/") for folder in own), folders

    def test_a_gc_while_the_note_is_fresh_removes_nothing_from_the_folder(self, tmp_path, store, monkeypatch):
        """`store gc` is carried out as the increment's own files come into its folder, and may remove the snapshot it builds on. It takes that one's record, as it always could; of its folder it removes nothing, where it used to leave only the files the increment keeps there."""
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", 3)
        first, second, third = _one_gc_may_remove(project, store.root)
        _chart(project, "four")
        before = _files_of(second.kept.folder)
        assert {"_output/curve.html", "_chartbook/index.json", "_data/codes.parquet", "README.md"} <= before
        noted, real = [], store_module._FolderPending._complete

        def completing(self):
            if self.builds_on is not None:
                noted.extend(self._note.read_text(encoding="utf-8").splitlines())
                _gc(self.store.root)
            return real(self)

        with monkeypatch.context() as patched:
            patched.setattr(store_module._FolderPending, "_complete", completing)
            with pytest.raises(store_module.StoreError, match="went from the store as this snapshot was being written"):
                snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(3))
        # The note named the folder it builds on, each folder once, and no file
        built_on = second.kept.folder.relative_to(store.root).as_posix()
        assert store_module.FOLDER_MARK + built_on in noted and len(set(noted)) == len(noted)
        assert all(line.startswith(store_module.FOLDER_MARK) for line in noted), noted
        # The record went: no note ever kept one. Every file of the folder is there, the chart and the index too,
        # which the increment does not keep there and which a line for each file it does keep left to the sweep
        after = _files_of(second.kept.folder)
        assert "_chartbook/snapshot.json" not in after
        assert after == (before - {"_chartbook/snapshot.json"}) | {"_chartbook/CLEARED.txt"}
        # Its note has gone with the snapshot that was let go: the next gc takes the folder whole
        assert not list((store.root / "_chartbook" / "tmp").glob("*" + store_module.PENDING_SUFFIX))
        _gc(store.root)
        assert not second.kept.folder.exists()
        # Made again, it is decided on what is there now, and is whole
        store_module._read_records.clear()
        again = snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(4))
        assert again.made and FolderStore(store.root).verify() == []

    def test_a_line_for_a_file_still_keeps_that_file_alone(self, tmp_path, store):
        """As a migrate's writer notes one, and as a note written before this did: the file it names stays, and the rest of a cleared folder goes."""
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", 3)
        first, second, third = _one_gc_may_remove(project, store.root)
        tmp = store.root / "_chartbook" / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        kept = second.kept.folder / "_data" / "codes.parquet"
        (tmp / "aaaaaaaaaaaa.pending").write_text(kept.relative_to(store.root).as_posix() + "\n", encoding="utf-8", newline="\n")
        _gc(store.root)
        assert _files_of(second.kept.folder) == {"_data/codes.parquet", "_chartbook/CLEARED.txt"}
        assert snapshot.all_snapshots(FolderStore(store.root)) and FolderStore(store.root).verify() == []


def _lose(path: Path, to: bytes = None) -> None:
    """A file of the store goes, as one a sync lost; or is of another size, as one a sync has brought part of."""
    os.chmod(path, 0o600)  # what a store keeps is read-only
    path.unlink() if to is None else path.write_bytes(to)
    store_module._found_whole.clear()


def _put(pending, scratch: Path, name: str, content: bytes):
    """Give one file of acme/sized to a snapshot being made, as ``data/<name>.bin``; what the store handed back, and the file given."""
    scratch.mkdir(exist_ok=True)
    source = scratch / f"{name}.bin"
    source.write_bytes(content)
    return pending.put(source, place=f"data/{name}.bin"), source


def _written(store: FolderStore, pending, puts: dict, number: int, complete: bool = False) -> Path:
    """Decide how a snapshot of acme/sized is kept, as :func:`chartbook.snapshot.make` does once every file is put, and write its record; the record."""
    from chartbook import snapshot
    from chartbook.refs import AssetRef

    assets, held = {}, {}
    for name, put in puts.items():
        local = AssetRef(kind="dataframe", name=name)
        assets[str(local)] = snapshot.asset_record(local.in_pipeline("acme/sized"), "acme/sized", f"./data/{name}.bin", put, True)
        held[str(local)] = put.stored
    taken = snapshot.Snapshot("acme/sized", COMMIT, "", LONG_AGO.format(number), assets, stored={"records": held})
    decided = snapshot.to_be_kept(store, taken, complete)
    if decided.increment:
        pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
    return pending.write(taken.to_document())


def _sized(store: FolderStore, scratch: Path, files: dict, number: int, complete: bool = False) -> Path:
    """Write one snapshot of acme/sized of *files*, each a name with its bytes; its record."""
    pending = store.begin("acme/sized", COMMIT, LONG_AGO.format(number), undecided=True)
    try:
        return _written(store, pending, {name: _put(pending, scratch, name, content)[0] for name, content in files.items()}, number, complete)
    except BaseException:
        pending.discard()
        raise


class TestNoLookAtAFileAsItIsPut:
    """The store was asked whether a file of an earlier snapshot is there, whole, three times over: as each file was put, as the rule of adding up asked of the snapshot to build on, and before the record. When a file is put, the records now say whether the store has its bytes, and the disk is not asked.

    The two looks that are left are a moment apart, and both stay. The
    first decides which snapshot is built on, and passes over one that has
    lost a file for the one before it. The second is the last before the
    record, and is what finds a file lost between the two
    (``tests/test_snapshot_decides.py``, ``TestThePromise``): it could take
    what the first was told, which :meth:`FolderStore.holes_of` hands on,
    and that instant would then go unseen.

    What going by the records leaves to find later, bytes a record names
    that the store has lost, is found by those looks while the file given
    is still at hand.
    """

    @counted
    def test_a_file_of_the_snapshot_it_builds_on_is_asked_about_twice_and_not_as_it_is_put(self, asked):
        for found in asked.values():
            assert all(location.startswith(found.built_on + "/") for location in found.looks)
            kept_there = [location for location in found.looks if "/parts/" in location]
            # Each file of the table that the snapshot it builds on has: as the kind is decided, and before the record
            assert len(kept_there) == found.files - NEW and {found.looks[location] for location in kept_there} == {2}
            assert max(found.looks.values()) == 2, found.looks.most_common(3)

    @pytest.fixture
    def daily(self, tmp_path, store):
        """A pipeline with a first, complete snapshot of a table of five files."""
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", 5)
        first = snapshot.make(project, store=store, made_at=LONG_AGO.format(0))
        assert first.made and not first.kept.increment
        return project, first

    def _whole_and_complete(self, store, report, files: int) -> None:
        """The snapshot is written complete: every file of it in its own folder, each what its record says."""
        assert report.made and not report.kept.increment
        fresh = FolderStore(store.root)
        assert fresh.builds_on(report.snapshot.path) is None and fresh.verify_snapshot(report.snapshot.path) == []
        assert len([name for name in _files_of(report.kept.folder) if "/parts/" in name]) == files
        assert report.kept.folder.parent.parent.name == "snapshots"

    def test_with_nothing_lost_it_is_an_increment(self, daily, store):
        from chartbook import snapshot

        project, first = daily
        _write_days(project, 5, 1)
        second = snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.made and second.kept.increment and second.kept.builds_on == first.kept.folder.name
        assert FolderStore(store.root).verify_snapshot(second.snapshot.path) == []

    @pytest.mark.parametrize("to", [None, b"part of it"], ids=["lost", "of another size"])
    def test_a_file_lost_before_the_snapshot_is_begun_leaves_it_complete(self, daily, store, to):
        from chartbook import snapshot

        project, first = daily
        _lose(first.kept.folder / "_data" / "parts" / "2019-01" / "2019-01-02.parquet", to)
        _write_days(project, 5, 1)
        _as_another_process()
        self._whole_and_complete(store, snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(1)), 6)

    @pytest.mark.parametrize("to", [None, b"part of it"], ids=["lost", "of another size"])
    def test_a_file_lost_once_every_file_is_put_leaves_it_complete(self, daily, store, monkeypatch, to):
        """Lost between the last file put and the moment the kind is decided: when it was put the records said the store had it, and the look that is left finds that it has not."""
        from chartbook import snapshot

        project, first = daily
        _write_days(project, 5, 1)
        real, lost = snapshot.to_be_kept, []

        def deciding(*args, **kwargs):
            if not lost:
                lost.append(_lose(first.kept.folder / "_data" / "parts" / "2019-01" / "2019-01-02.parquet", to))
            return real(*args, **kwargs)

        monkeypatch.setattr(snapshot, "to_be_kept", deciding)
        self._whole_and_complete(store, snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(1)), 6)
        assert lost

    @pytest.mark.parametrize("to", [None, b"part of it"], ids=["lost", "of another size"])
    def test_a_file_lost_once_its_kind_is_decided_leaves_it_complete(self, daily, store, monkeypatch, to):
        """Lost between the look that decided on an increment and the record: the look before the record finds it, which is why that look stays."""
        from chartbook import snapshot

        project, first = daily
        _write_days(project, 5, 1)
        real, decided = snapshot.to_be_kept, []

        def deciding(*args, **kwargs):
            kept = real(*args, **kwargs)
            if not decided:
                _lose(first.kept.folder / "_data" / "parts" / "2019-01" / "2019-01-02.parquet", to)
            decided.append(kept.increment)
            return kept

        monkeypatch.setattr(snapshot, "to_be_kept", deciding)
        self._whole_and_complete(store, snapshot.make(project, store=FolderStore(store.root), made_at=LONG_AGO.format(1)), 6)
        assert decided == [True]  # by the rule it was an increment, and the file went after that was said

    def test_bytes_the_store_lacks_are_written_aside_as_they_are_put_and_bytes_it_has_lost_stay_at_hand(self, tmp_path, store):
        """Room for one table at a time: a file no record names is written into the store when it is put, and the file given need not stay. One a record names waits for the record, with the file given at hand; if the store has lost it, the look before the record finds that, and it is written from the file given."""
        scratch = tmp_path / "files"
        first = _sized(store, scratch, {"big": b"B" * 100, "small": b"s" * 10}, 0)
        _lose(first.parent.parent / "data" / "big.bin")
        second = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(1), undecided=True)
        new, given_new = _put(second, scratch, "new", b"n" * 5)
        assert second.placed and second.at_hand() == set()  # the store lacked it: written aside, and not wanted at hand
        aside = [path for path in (store.root / "_chartbook" / "tmp").iterdir() if path.suffix == ".part"]
        assert [path.read_bytes() for path in aside] == [b"n" * 5]
        big, given_big = _put(second, scratch, "big", b"B" * 100)
        small, given_small = _put(second, scratch, "small", b"s" * 10)
        # A record names both, so neither is written yet, and both files given are wanted until the record is
        assert second.at_hand() == {os.path.realpath(given_big), os.path.realpath(given_small)}
        assert len([path for path in (store.root / "_chartbook" / "tmp").iterdir() if path.suffix == ".part"]) == 1
        record = _written(FolderStore(store.root), second, {"new": new, "big": big, "small": small}, 1)
        kept = store_module.read_kept_record(record)
        # The one it would build on has lost a file: it is complete, and the lost bytes came from the file given
        assert kept.complete and not kept.increment and record.parent.parent.parent.parent.name == "snapshots"
        assert (record.parent.parent / "data" / "big.bin").read_bytes() == b"B" * 100
        assert FolderStore(store.root).verify_snapshot(record) == []

    def test_a_gc_between_a_put_and_the_record_leaves_the_folder_it_was_to_copy_from(self, tmp_path, store):
        """The file given goes meanwhile (its pipeline is building again), and `store gc` clears the only snapshot that has its bytes. The folder was noted when the file was put, by the records and with no look at the disk, so its files are there to copy when the record is written."""
        scratch = tmp_path / "files"
        first = _sized(store, scratch, {"big": b"B" * 100, "small": b"s" * 10}, 0)
        _sized(FolderStore(store.root), scratch, {"big": b"C" * 100, "small": b"t" * 10}, 1)
        third = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(2), undecided=True)
        big, given = _put(third, scratch, "big", b"B" * 100)
        assert not third.placed
        given.unlink()
        _gc(store.root)
        assert not first.exists() and (first.parent.parent / "data" / "big.bin").read_bytes() == b"B" * 100
        record = _written(FolderStore(store.root), third, {"big": big}, 2)
        assert (record.parent.parent / "data" / "big.bin").read_bytes() == b"B" * 100
        assert FolderStore(store.root).verify_snapshot(record) == []
        _gc(store.root)
        assert not first.parent.parent.exists()  # its note gone, the cleared folder goes whole


class TestARecordIsReadOnce:
    """A snapshot's record lists every file of the snapshot: 280 bytes a file, 36 MB for a table of 127,000 files. One `chartbook snapshot` read each record of its pipeline ten times over, twelve with the reminder, whole each time: once to put each in order beside another made in the same second, for a time the snapshot in hand already says.

    Each of the two readers of a record now reads it once in a process, by
    its path, its time and its size: the store, for where its files are
    (:func:`chartbook.store.read_kept_record`, as before), and
    :func:`chartbook.snapshot.read`, for what the snapshot is. The two do
    not share one reading: what the first keeps of a record is small, and
    keeping the whole of every record it reads for the second would hold
    every pipeline's in memory at each read of a table.
    """

    @counted
    def test_each_record_is_opened_once_by_each_of_its_two_readers(self, asked):
        for found in asked.values():
            assert set(found.records.values()) == {1}, found.records
            # By the store, for where its files are; and as a snapshot. Never to put snapshots in order
            assert {reader for _, reader in found.records} == {"store.read_kept_record", "snapshot._read"}, found.records
            # The complete snapshot's and the increment's: each by each
            assert len(found.records) == 4 and len({record for record, _ in found.records}) == 2

    @pytest.fixture
    def taken(self, tmp_path, store):
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", 3)
        return snapshot.make(project, store=store, made_at=LONG_AGO.format(0)).snapshot

    def _opens(self, monkeypatch) -> list:
        """Each record opened from here on, by its snapshot's folder."""
        opened, real = [], builtins.open

        def counting(file, *args, **kwargs):
            if not isinstance(file, int) and os.path.basename(os.fspath(file)) == "snapshot.json":
                opened.append(Path(os.fspath(file)).parent.parent.name)
            return real(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", counting)
        monkeypatch.setattr(io, "open", counting)
        return opened

    def test_a_snapshot_read_again_is_the_one_read_before(self, taken, store, monkeypatch):
        from chartbook import snapshot

        _as_another_process()
        opened = self._opens(monkeypatch)
        first = snapshot.read(taken.path)
        assert snapshot.read(taken.path) is first and snapshot.read(str(taken.path)) is first
        assert snapshot.find(FolderStore(store.root), taken.commit) == [first]
        assert snapshot.all_snapshots(FolderStore(store.root)) == [first]
        assert opened == [taken.path.parent.parent.name] * 2  # as a snapshot; and by the store, which finds it for find
        assert first.content() == taken.content() and first.path == taken.path and first.made_at == taken.made_at

    def test_putting_snapshots_in_order_opens_no_record(self, taken, monkeypatch):
        from chartbook import snapshot

        opened = self._opens(monkeypatch)
        assert snapshot._count(taken.path, taken.made_at) == 1
        # The second of two made in one second has the next second's name: told from its name and its time
        later = taken.path.parent.parent.parent / "2026-01-01T000001Z_aaaaaaaaaaaa" / "_chartbook" / "snapshot.json"
        assert snapshot._count(later, taken.made_at) == 2
        assert opened == []
        assert snapshot._count(taken.path) == 1 and opened == [taken.path.parent.parent.name]  # with no time given, as before

    def test_a_record_that_has_changed_is_read_again(self, taken, monkeypatch):
        """A record is never rewritten by a store. One that is, by hand or by a sync that brings the rest of it, has another time or size, and is read as it is now."""
        import json

        from chartbook import snapshot

        first = snapshot.read(taken.path)
        document = json.loads(taken.path.read_text(encoding="utf-8"))
        document["tags"] = ["v1.0"]
        os.chmod(taken.path, 0o600)
        taken.path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        again = snapshot.read(taken.path)
        assert again is not first and again.tags == ["v1.0"] and first.tags == []
        assert snapshot.read(taken.path) is again

    def test_a_record_that_cannot_be_read_is_not_remembered(self, taken, monkeypatch):
        """Half of it there, as a sync leaves one: it is refused each time it is asked for, and read once the rest has come."""
        from chartbook import snapshot

        whole = taken.path.read_bytes()
        os.chmod(taken.path, 0o600)
        taken.path.write_bytes(whole[: len(whole) // 2])
        for _ in range(2):
            with pytest.raises(snapshot.SnapshotError, match="Cannot read the snapshot"):
                snapshot.read(taken.path)
        taken.path.write_bytes(whole)
        assert snapshot.read(taken.path).content() == taken.content()


@pytest.fixture
def store(tmp_path, monkeypatch) -> FolderStore:
    """A store of this test's own, which the commands of the test write to."""
    from chartbook import config

    monkeypatch.setenv(config.STORE_ENV_VAR, str(tmp_path.resolve() / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(tmp_path.resolve() / "cache"))
    return FolderStore(tmp_path.resolve() / "store")


class TestTheLineIsAsItWas:
    """What the line says is the plan's snapshots and objects, as before; and a store a sweep refuses still has no plan."""

    @pytest.fixture
    def one_to_clear(self, tmp_path, store) -> Path:
        """A pipeline with two complete snapshots, the first long past; and, beside a file of the second, a copy a sync service left."""
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", 3)
        old = snapshot.make(project, store=store, made_at="2026-01-01T00:00:00.000000Z")
        _write_days(project, 3, 1)
        new = snapshot.make(project, store=store, complete=True)
        assert old.made and new.made and not new.kept.increment
        (new.kept.folder / "_data" / "codes (1).parquet").write_bytes(b"a copy a sync service made")
        return project

    def test_the_line_is_what_a_plan_with_its_sweep_gives(self, one_to_clear, store, monkeypatch):
        import time

        from chartbook import lock
        from chartbook.cli import _format_bytes, _what_gc_would_clear

        # Two hours on: a sweep leaves what is beside a snapshot's files for an hour
        later = time.time() + 2 * store_module.PENDING_SECONDS
        monkeypatch.setattr(time, "time", lambda: later)
        swept = lock.plan_gc(FolderStore(store.root))
        (unused,) = [name for name, _ in swept.unused]
        assert unused.startswith("snapshots/acme+daily/") and unused.endswith("/_data/codes (1).parquet")
        plain = lock.plan_gc(FolderStore(store.root), sweep=False)
        assert plain.unused == []
        for plan in (swept, plain):
            assert len(plan.snapshots_delete) == 1 and not plan.pinned_delete
        assert (plain.freed_bytes, plain.delete, plain.copies) == (swept.freed_bytes, swept.delete, swept.copies)
        assert _what_gc_would_clear(FolderStore(store.root)) == (
            f"`chartbook store gc` would clear 1 snapshot(s), freeing {_format_bytes(swept.freed_bytes)}: older than "
            f"{swept.keep_days:g} days, and neither pinned nor the newest of their pipeline."
        )

    def test_the_command_ends_with_it(self, one_to_clear, store):
        _write_days(one_to_clear, 4, 1)
        result = CliRunner().invoke(main, ["snapshot", "--as-is", "--project-dir", str(one_to_clear)])
        assert result.exit_code == 0, result.output
        assert "`chartbook store gc` would clear 1 snapshot(s), freeing " in result.output.splitlines()[-1]
        assert result.output.splitlines()[-1].endswith(
            " Nothing is removed unless you ask (`--no-gc-reminder` silences this line)."
        )

    def test_a_store_a_migrate_has_not_finished_moving_has_no_plan(self, one_to_clear, store, monkeypatch):
        """What a sweep asks before it looks at anything, the plan without one asks too (:meth:`FolderStore.check_tidy`)."""
        from chartbook import lock
        from chartbook.cli import _what_gc_would_clear

        def not_moved(self):
            raise store_module.StoreError("The store has not finished moving.")

        monkeypatch.setattr(FolderStore, "_check_migrated", not_moved)
        for sweep in (True, False):
            with pytest.raises(store_module.StoreError, match="has not finished moving"):
                lock.plan_gc(FolderStore(store.root), sweep=sweep)
        assert _what_gc_would_clear(FolderStore(store.root)) is None

    def test_a_store_of_0_5_has_no_plan(self, one_to_clear, store):
        from chartbook import lock
        from chartbook.cli import _what_gc_would_clear
        from tests.store_of_0_5 import laid_out_as_0_5

        old = laid_out_as_0_5(store.root)
        for sweep in (True, False):
            with pytest.raises(store_module.EarlierLayoutError):
                lock.plan_gc(FolderStore(old.root), sweep=sweep)
        assert _what_gc_would_clear(FolderStore(old.root)) is None

    def test_several_stores_read_as_one_have_no_plan(self, one_to_clear, store):
        """As before: for several stores the sweep is what refused, and the line is made of each store by itself."""
        from chartbook import lock
        from chartbook.multi_store import NamedStore, Stores

        several = Stores([NamedStore("mine", str(store.root), FolderStore(store.root))])
        for sweep in (True, False):
            with pytest.raises(ValueError, match="Select one store"):
                lock.plan_gc(several, sweep=sweep)
