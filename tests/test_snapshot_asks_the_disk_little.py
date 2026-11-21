"""A snapshot of a table of many small files asks the store little for each file.

A store may be a folder a sync service keeps, where each question to the
disk (is this file there, how large is it, open it) takes the better part
of a millisecond: hundreds of times what it takes on a disk of one's own.
A table kept as a folder of small files, one a day, is thousands of files,
and a snapshot of it that adds twenty of them is kept as an increment:
twenty files are copied. What it asks of the store must not grow with the
files it does not copy, beyond a look at each to know that the snapshot it
builds on still has it.

Measured on 2026-11-20, before the six rules these tests hold, the second
snapshot of such a table asked the store 26 questions for each file of the
table, and read every one of them back from it. It asks 4: whether the
file is a link and how large it is, as the snapshot's kind is decided and
once more before its record. Each rule has a class below, with what it
saves and what it must not lose.

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

#: The wrappers count calls of ``os.stat`` and the like. On Python 3.10 ``pathlib`` asks the disk through
#: functions it bound when it was imported, which a patch of ``os.stat`` does not reach: nothing is counted there
counted = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="a patch of os.stat does not reach pathlib's own methods on Python 3.10, so the questions cannot be counted",
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


def _day_frame(number: int, revised: float = 0.0) -> pl.DataFrame:
    """One day of the table: three rows; with *revised*, the same rows with other values."""
    day = FIRST_DAY + timedelta(days=number)
    return pl.DataFrame(
        {"ds": [day] * 3, "unique_id": ["T0", "T1", "T2"], "y": [4.0 + number * 0.01 + i + revised for i in range(3)]}
    )


def _day_file(folder: Path, number: int) -> Path:
    """The file of one day, in the folder of its month."""
    day = FIRST_DAY + timedelta(days=number)
    return folder / "_data" / "parts" / day.strftime("%Y-%m") / f"{day.isoformat()}.parquet"


def _write_days(folder: Path, first: int, count: int, revised: float = 0.0) -> None:
    """Write *count* days of the table from day *first*, each a file of three rows in the folder of its month.

    Not packed, so that a day written again with other values is a file
    of the size it was.
    """
    for number in range(first, first + count):
        file = _day_file(folder, number)
        file.parent.mkdir(parents=True, exist_ok=True)
        _day_frame(number, revised).write_parquet(file, compression="uncompressed")


def _pipeline(folder: Path, files: int, manifest: dict = None) -> Path:
    """A pipeline in a repository of its own, built: the table in *files* parts, a small table, a chart and a README."""
    (folder / "_data").mkdir(parents=True)
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest or MANIFEST), encoding="utf-8", newline="\n")
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
    """Wrap what asks the disk, so that each question of the store is counted; each wrapper calls through.

    What it sees (``TestWhatTheCountSees`` holds each): a call of ``os``
    that names a path of the store; a file opened by Python; a file handed
    to pyarrow or polars by one of the ways in that are wrapped by name,
    where a call handed several files, a folder or a pattern is as many
    questions as it has files; and a listing of a folder, with one question
    more for each entry that is then asked for its size and time.

    What it does not see: a way into a library that is not wrapped here,
    and one a module of ChartBook took by name when it was loaded (``from
    polars import read_parquet``). On Python 3.10 pathlib asks through its
    own accessor, and nothing that counts is run there (:data:`counted`).
    """
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
            if not quiet[0] and in_store(path):
                asked.store[what] += 1
            return original(*args, **kwargs)
        return wrapper

    quiet = [0]  # while realpath looks at each folder down a path, and while the count itself looks: not the command's questions
    stat, lstat, realpath = os.stat, os.lstat, os.path.realpath

    def counted_stat(path, *args, **kwargs):
        if not quiet[0] and in_store(path):
            asked.store["stat" if kwargs.get("follow_symlinks", True) else "lstat"] += 1
        return stat(path, *args, **kwargs)

    def counted_lstat(path, *args, **kwargs):
        if not quiet[0] and in_store(path):
            asked.store["lstat"] += 1
        return lstat(path, *args, **kwargs)

    def counted_realpath(filename, *args, **kwargs):
        # One question, however a system answers it: on POSIX it looks at each folder down the path
        if not quiet[0] and in_store(filename):
            asked.store["realpath"] += 1
        quiet[0] += 1
        try:
            return realpath(filename, *args, **kwargs)
        finally:
            quiet[0] -= 1

    patch.setattr(os, "stat", counted_stat)
    patch.setattr(os, "lstat", counted_lstat)
    patch.setattr(os.path, "realpath", counted_realpath)

    class Listed:
        """One entry of a listing of the store, as :class:`os.DirEntry` gives it. Asked for its size and time, it asks the disk on every system but Windows: a question a file, which a count of the listings alone took for one a folder. Counted once an entry."""

        def __init__(self, entry):
            self._entry, self._asked = entry, False

        def __getattr__(self, name):
            return getattr(self._entry, name)

        def __fspath__(self):
            return self._entry.path

        def __repr__(self):
            return repr(self._entry)

        def stat(self, *, follow_symlinks=True):
            if not self._asked and not quiet[0]:
                self._asked = True
                asked.store["stat of a listed file"] += 1
            return self._entry.stat(follow_symlinks=follow_symlinks)

    class Listing:
        """A listing of a folder of the store, which hands out each entry as :class:`Listed`."""

        def __init__(self, listing):
            self._listing = listing

        def __iter__(self):
            return self

        def __next__(self):
            return Listed(next(self._listing))

        def __enter__(self):
            return self

        def __exit__(self, *error):
            self._listing.close()

        def close(self):
            self._listing.close()

    listing_of = os.scandir

    def scandir(path="."):
        if quiet[0] or not in_store(path):
            return listing_of(path)
        asked.store["list"] += 1
        return Listing(listing_of(path))

    patch.setattr(os, "scandir", scandir)
    patch.setattr(os, "listdir", wrapped(os.listdir, "list"))
    globber = getattr(glob_module, "_StringGlobber", None)  # pathlib's glob keeps the two it uses
    if globber is not None:
        patch.setattr(globber, "scandir", staticmethod(scandir))
        patch.setattr(globber, "lstat", staticmethod(counted_lstat))

    opened = builtins.open

    def counted_open(file, mode="r", *args, **kwargs):
        if not quiet[0] and in_store(file):
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

    # What the wrappers above do not see: a file pyarrow or polars opens itself. Each way into them that takes a
    # file is wrapped by its name, as ChartBook calls it (`pq.read_table`, `pl.scan_parquet`); what one of them
    # calls inside its own library is not seen again
    import pyarrow.dataset as pads
    import pyarrow.parquet as pq

    def files_handed(source) -> list:
        """Each file of the store that one call is handed: every one of a list, and every file that a folder or a pattern stands for."""
        handed = []
        for one in source if isinstance(source, (list, tuple)) else [source]:
            if not in_store(one):
                continue
            text = os.fsdecode(os.fspath(one))
            quiet[0] += 1  # the count's own looks
            try:
                if glob_module.has_magic(text):
                    handed += [found for found in glob_module.glob(text, recursive=True) if os.path.isfile(found)]
                elif os.path.isdir(text):
                    handed += [os.path.join(folder, name) for folder, _, names in os.walk(text) for name in names]
                else:
                    handed.append(text)
            finally:
                quiet[0] -= 1
        return handed

    inside = [0]  # within one of the ways in: what it calls of another (read_table of dataset) is the same read

    def read_by(original, what):
        def wrapper(*args, **kwargs):
            named = (kwargs[name] for name in ("source", "file", "where", "path_or_paths", "path") if name in kwargs)
            for file in files_handed(args[0] if args else next(named, None)) if not inside[0] else ():
                asked.store["opened by pyarrow or polars"] += 1
                if of_the_table(file):
                    asked.table_reads[what] += 1
            inside[0] += 1
            try:
                return original(*args, **kwargs)
            finally:
                inside[0] -= 1
        return wrapper

    patch.setattr(rowhash, "_parquet_batches", read_by(rowhash._parquet_batches, "rowhash._parquet_batches"))
    ways_in = (
        (pq, "pyarrow.parquet", ("ParquetFile", "ParquetDataset", "read_table", "read_pandas", "read_metadata", "read_schema")),
        (pads, "pyarrow.dataset", ("dataset",)),
        (pl, "polars", (
            "scan_parquet", "read_parquet", "read_parquet_schema", "read_parquet_metadata", "scan_csv", "read_csv",
            "scan_ndjson", "read_ndjson", "scan_ipc", "read_ipc", "read_ipc_schema", "read_ipc_stream",
        )),
    )
    for module, said, names in ways_in:
        for name in names:
            if hasattr(module, name):
                patch.setattr(module, name, read_by(getattr(module, name), f"{said}.{name}"))

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


# --- What it comes to ----------------------------------------------------------------


@counted
class TestWhatAFileMoreOfTheTableAsksOfTheStore:
    """Twenty new files either way: what the larger table asks beyond the smaller is asked for the files that were not copied."""

    def test_it_is_four_questions_where_it_was_twenty_six(self, asked):
        """Whether it is a link and how large it is, twice: as the kind is decided, and before the record."""
        small, large = (asked[files] for files in SIZES)
        more = large.files - small.files
        added = {what: (large.store[what] - small.store[what]) / more for what in sorted(set(small.store) | set(large.store))}
        said = f"{sorted(small.store.items())} then {sorted(large.store.items())}"
        assert sum(added.values()) <= 4.1, said
        # Nothing is opened, listed, written or resolved for a file that is not copied, and no file's time is set
        assert {what for what, a_file in added.items() if abs(a_file) > 0.05} <= {"stat", "lstat"}, said
        assert added.get("stat", 0) <= 2.1 and added.get("lstat", 0) <= 2.1, said

    def test_and_the_rest_does_not_grow_with_the_table(self, asked):
        """What is asked whatever the table's size: the records, the note, the twenty files copied and the record written. Measured at 465."""
        for found in asked.values():
            assert found.of_the_store() - 4 * found.files <= 600, sorted(found.store.items())


@counted
class TestWhatTheCountSees:
    """The bound above holds a change back only if the count sees what the change asks (found by review, 2026-11-21).

    A table's files in a store are read, and looked at, in ways a later
    change might well use. The count saw calls of ``os``, of ``open`` and
    of three named ways into pyarrow and polars: a file read by
    ``pyarrow.parquet.read_table`` or ``polars.read_parquet`` was not seen
    at all, every file handed to one call was one question, and a look at
    each file through a listing of its folder was one question a folder.
    """

    FILES = 12

    @pytest.fixture
    def table(self, tmp_path, store) -> list:
        """The files of a table of twelve days, where a store keeps them."""
        from chartbook import snapshot

        project = _pipeline(tmp_path.resolve() / "project", self.FILES)
        first = snapshot.make(project, store=store, made_at=LONG_AGO.format(0))
        files = sorted(path for path in first.kept.folder.rglob("*.parquet") if "parts" in path.parts)
        assert len(files) == self.FILES
        return files

    def _counted(self, monkeypatch, root: Path, what) -> Asked:
        asked = Asked(self.FILES)
        with monkeypatch.context() as patch:
            _counting(patch, asked, root)
            what()
        return asked

    def test_a_file_opened_by_python(self, table, store, monkeypatch):
        asked = self._counted(monkeypatch, store.root, lambda: [open(file, "rb").close() for file in table])
        assert sum(asked.table_reads.values()) == self.FILES and asked.store["open to read"] == self.FILES

    def test_a_table_read_file_by_file_by_pyarrow_itself(self, table, store, monkeypatch):
        import pyarrow.parquet as pq

        asked = self._counted(monkeypatch, store.root, lambda: [pq.read_table(str(file)) for file in table])
        assert asked.table_reads == {"pyarrow.parquet.read_table": self.FILES}, dict(asked.table_reads)
        assert asked.store["opened by pyarrow or polars"] == self.FILES

    def test_a_table_read_file_by_file_by_polars_itself(self, table, store, monkeypatch):
        asked = self._counted(monkeypatch, store.root, lambda: [pl.read_parquet(str(file)) for file in table])
        assert asked.table_reads == {"polars.read_parquet": self.FILES}, dict(asked.table_reads)
        assert asked.store["opened by pyarrow or polars"] == self.FILES

    def test_a_call_handed_several_files_is_as_many_questions(self, table, store, monkeypatch):
        asked = self._counted(monkeypatch, store.root, lambda: pl.scan_parquet([str(file) for file in table]).collect())
        assert asked.table_reads == {"polars.scan_parquet": self.FILES} and asked.of_the_store() >= self.FILES, dict(asked.store)

    def test_and_so_is_one_handed_a_folder_or_a_pattern(self, table, store, monkeypatch):
        parts = next(folder for folder in table[0].parents if folder.name == "parts")
        for handed in (str(parts / "**" / "*.parquet"), str(parts)):
            asked = self._counted(monkeypatch, store.root, lambda: pl.scan_parquet(handed).collect())
            assert asked.table_reads == {"polars.scan_parquet": self.FILES}, (handed, dict(asked.table_reads))
            # The count's own look at what the folder or the pattern stands for is not the command's
            assert asked.of_the_store() == self.FILES, (handed, dict(asked.store))

    def test_every_file_looked_at_through_a_listing_of_its_folder(self, table, store, monkeypatch):
        """A look at each file through `os.scandir` is, on a disk that is not Windows', a question a file."""
        def looked() -> int:
            seen = 0
            for folder in sorted({os.path.dirname(file) for file in table}):
                with os.scandir(folder) as listing:
                    for entry in listing:
                        seen += entry.stat().st_size > 0
                        seen += entry.stat().st_size > 0  # asked again, an entry answers from what it was told: no question
            return seen

        asked = self._counted(monkeypatch, store.root, looked)
        folders = len({os.path.dirname(file) for file in table})
        assert asked.store == {"list": folders, "stat of a listed file": self.FILES}, dict(asked.store)

    def test_a_listing_whose_entries_are_asked_only_their_names_is_one_question(self, table, store, monkeypatch):
        def listed() -> list:
            return [entry.name for folder in sorted({os.path.dirname(file) for file in table}) for entry in os.scandir(folder) if entry.is_file()]

        asked = self._counted(monkeypatch, store.root, listed)
        assert asked.store == {"list": len({os.path.dirname(file) for file in table})}, dict(asked.store)


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
        clock = [time.time()]
        monkeypatch.setattr(time, "time", lambda: clock[0])
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
        clock[0] -= 3600  # the time of day is set back: the minute is no longer known to be running, so it is said again
        pending._alive()
        pending._alive()
        assert touched == [note, note, note]
        pending.discard()

    def test_a_minute_is_well_within_what_a_note_counts_for(self):
        assert store_module.ALIVE_SECONDS * 60 <= store_module.PENDING_FOLDER_SECONDS


class _Clock:
    """The time of day and the process's own clock, moved by hand; the note's time is set by the time of day, as the disk sets it."""

    def __init__(self, monkeypatch):
        import time

        self.now, self.own = time.time(), 1000.0
        real_utime, real_line = os.utime, store_module._FolderPending._note_line
        clock = self

        def utime(path, times=None, **options):
            if times is None and not options:
                return real_utime(path, (clock.now, clock.now))
            return real_utime(path, times, **options)

        def note_line(self, line):
            real_line(self, line)
            real_utime(self._note, (clock.now, clock.now))  # a line written sets the file's time, by the time of day

        monkeypatch.setattr(time, "time", lambda: clock.now)
        monkeypatch.setattr(time, "monotonic", lambda: clock.own)
        monkeypatch.setattr(os, "utime", utime)
        monkeypatch.setattr(store_module._FolderPending, "_note_line", note_line)

    def passes(self, seconds: float, asleep: bool = False) -> None:
        """Time passes; *asleep*, the machine is suspended meanwhile, and the process's own clock stands still (macOS, Linux)."""
        self.now += seconds
        if not asleep:
            self.own += seconds


class TestTheNotesMinuteIsOfTheTimeOfDay:
    """The minute between two touches of the note is counted on the clock the note's age is judged by: the time of day (found by review, 2026-11-21).

    `store gc` takes a note for one given up by the time of day
    (``time.time()`` beside the note's own time). The minute was counted on
    the process's own clock (``time.monotonic()``), which stands still
    while a laptop sleeps: a snapshot that slept for more than a day in
    the middle did not bring its note up to date at its next file, for up
    to a minute more, and a `store gc` on the machine in that minute went
    by no note.
    """

    A, S, T = b"a" * 100, b"s" * 10, b"t" * 7

    def _counts(self, root: Path, folder: Path, location: Path) -> bool:
        folders, files = FolderStore(root)._notes()
        return str(folder) in folders or str(location) in files

    @pytest.fixture
    def writing(self, tmp_path, store, monkeypatch):
        """A snapshot being made that has taken one file from the first snapshot's folder; the clock, and what must stay noted."""
        scratch = tmp_path / "files"
        first = _sized(FolderStore(store.root), scratch, {"a": self.A, "s": self.S, "t": self.T}, 0)
        clock = _Clock(monkeypatch)
        pending = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(1), undecided=True)
        _put(pending, scratch / "given", "a", self.A)
        return clock, pending, scratch, first.parent.parent, first.parent.parent / "data" / "a.bin"

    def test_a_slow_snapshot_that_puts_a_file_now_and_then_is_noted_all_along(self, writing, store):
        """More than a minute, more than an hour, more than a day in all: each file put brings the note's time up to date."""
        clock, pending, scratch, folder, location = writing
        assert self._counts(store.root, folder, location)
        for step, seconds in enumerate([90, 2 * 3600, 23 * 3600, 23 * 3600, 23 * 3600]):
            clock.passes(seconds)
            _put(pending, scratch / "given", "s" if step % 2 else "t", self.S if step % 2 else self.T)
            assert self._counts(store.root, folder, location), f"after step {step}"
        pending.discard()

    def test_a_writer_silent_for_a_day_is_taken_for_one_given_up_as_before(self, writing, store):
        clock, pending, scratch, folder, location = writing
        clock.passes(store_module.PENDING_FOLDER_SECONDS + 60)
        assert not self._counts(store.root, folder, location)
        pending.discard()

    def test_after_the_machine_slept_for_a_day_the_next_file_put_says_it_is_still_being_made(self, writing, store):
        clock, pending, scratch, folder, location = writing
        clock.passes(store_module.PENDING_FOLDER_SECONDS + 3600, asleep=True)
        clock.passes(1)  # awake again, and at work
        _put(pending, scratch / "given", "s", self.S)
        assert self._counts(store.root, folder, location)
        pending.discard()

    def test_and_a_gc_then_leaves_the_folder_it_takes_files_from(self, writing, store):
        clock, pending, scratch, folder, location = writing
        _sized(FolderStore(store.root), scratch, {"q": b"q" * 50}, 2, complete=True)  # a newer one, so that the first may go
        clock.passes(store_module.PENDING_FOLDER_SECONDS + 3600, asleep=True)
        clock.passes(1)
        _put(pending, scratch / "given", "s", self.S)
        _gc(store.root)
        assert location.is_file()
        pending.discard()

    def test_asleep_as_its_own_files_come_into_its_folder(self, tmp_path, store, monkeypatch):
        """At its worst: the machine sleeps for more than a day while the snapshot's own files are coming into its folder, wakes, and the snapshot goes on to its next file; a `store gc` then found no note that counted and a folder in which nothing had changed for a day, and took the files already in it. The snapshot was then written, and said it was made."""
        scratch = tmp_path / "files"
        clock = _Clock(monkeypatch)
        files = {"x": b"x" * 100, "y": b"y" * 100, "z": b"z" * 100}
        pending = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(0), undecided=True)
        puts = {name: _put(pending, scratch, name, content)[0] for name, content in files.items()}
        moved, real = [], store_module._FolderPending._moved_in

        def moving(self, temporary, target, *arguments):
            if len(moved) == 1:
                _gc(self.store.root)  # the snapshot is at its second file: a gc on this machine, now
            real(self, temporary, target, *arguments)
            moved.append(target)
            if len(moved) == 1:
                clock.passes(store_module.PENDING_FOLDER_SECONDS + 3600, asleep=True)  # the lid is closed on the first file
                clock.passes(1)

        monkeypatch.setattr(store_module._FolderPending, "_moved_in", moving)
        record = _written(FolderStore(store.root), pending, puts, 0)
        assert len(moved) == 3
        store_module._found_whole.clear()
        assert FolderStore(store.root).holes_of(record) == [] and FolderStore(store.root).verify_snapshot(record) == []
        assert {name: (record.parent.parent / "data" / f"{name}.bin").read_bytes() for name in files} == files


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

    def test_before_it_stops_for_want_of_bytes_every_copy_the_records_name_is_tried(self, tmp_path, store):
        """Found by review, 2026-11-21. The store has the bytes whole in an older snapshot; the newest record that names them, which was gone by as the file was put, has lost them; and the file given goes once it is put. A complete snapshot asked for stopped. It is written from the older copy."""
        scratch = tmp_path / "files"
        first = _sized(store, scratch, {"big": b"B" * 100, "small": b"s" * 10}, 0)
        second = _sized(FolderStore(store.root), scratch, {"big": b"B" * 100, "small": b"t" * 10}, 1, complete=True)
        _lose(second.parent.parent / "data" / "big.bin")
        third = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(2), undecided=True)
        big, given_big = _put(third, scratch / "given", "big", b"B" * 100)
        small, given_small = _put(third, scratch / "given", "small", b"u" * 10)
        assert third.at_hand() == {os.path.realpath(given_big)}
        given_big.unlink(), given_small.unlink()
        record = _written(FolderStore(store.root), third, {"big": big, "small": small}, 2, complete=True)
        assert (record.parent.parent / "data" / "big.bin").read_bytes() == b"B" * 100
        assert (record.parent.parent / "data" / "small.bin").read_bytes() == b"u" * 10
        store_module._found_whole.clear()
        assert FolderStore(store.root).holes_of(record) == [] and FolderStore(store.root).verify_snapshot(record) == []
        assert (first.parent.parent / "data" / "big.bin").read_bytes() == b"B" * 100  # the older copy is where it was

    def test_with_no_whole_copy_in_the_store_and_the_file_given_gone_it_stops_and_says_to_run_the_command_again(self, tmp_path, store):
        """The price of going by the records as a file is put: bytes a record names are not written aside then. Where the store has lost them and the file given has gone by the time of the record (its pipeline building again), there is nowhere to take them from. The snapshot stops, nothing of it is left, and the command run again makes it.

        Before, the look as the file was put found the store's copy gone
        and took the bytes then, so this snapshot was written.
        """
        scratch = tmp_path / "files"
        first = _sized(store, scratch, {"big": b"B" * 100, "small": b"s" * 10}, 0)
        _lose(first.parent.parent / "data" / "big.bin")
        second = FolderStore(store.root).begin("acme/sized", COMMIT, LONG_AGO.format(1), undecided=True)
        big, given = _put(second, scratch / "given", "big", b"B" * 100)
        new, _ = _put(second, scratch / "given", "new", b"n" * 5)
        given.unlink()
        with pytest.raises(store_module.StoreError, match="went from the store.*is not there to take it from, or has changed.*Run the command again"):
            try:
                _written(FolderStore(store.root), second, {"big": big, "new": new}, 1)
            except BaseException:
                second.discard()  # as whatever makes a snapshot lets it go
                raise
        # Nothing of it is left: no record but the first's, no folder of its own, nothing aside
        assert [kept.folder for kept in FolderStore(store.root).records()] == [first.parent.parent]
        assert sorted(path.name for path in first.parent.parent.parent.iterdir() if path.is_dir()) == [first.parent.parent.name]
        tmp = store.root / "_chartbook" / "tmp"
        assert not tmp.is_dir() or list(tmp.iterdir()) == []
        # Run again, with the file there: it is made, complete, and whole
        record = _sized(FolderStore(store.root), scratch / "again", {"big": b"B" * 100, "new": b"n" * 5}, 2)
        kept = store_module.read_kept_record(record)
        assert kept.complete and not kept.increment and FolderStore(store.root).verify_snapshot(record) == []


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
        read_text = Path.read_text  # what read the record for its time; on Python 3.10 it opens through no `open` a test can wrap
        monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: (opened.append(self.name), read_text(self, *args, **kwargs))[1])
        assert snapshot._count(taken.path, taken.made_at) == 1
        # The second of two made in one second has the next second's name: told from its name and its time,
        # with no record there to open
        later = taken.path.parent.parent.parent / "2026-01-01T000001Z_aaaaaaaaaaaa" / "_chartbook" / "snapshot.json"
        assert snapshot._count(later, taken.made_at) == 2
        assert opened == []
        assert snapshot._count(taken.path) == 1 and opened  # with no time given, the record is read for it, as before

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


class TestWhatReadRemembersIsSmall:
    """`snapshot.read` kept every snapshot it had read until the process ended, each with an entry for every file of its snapshot: a process that reads every record of a store (a catalog built, a `store gc` planned) held them all (found by review, 2026-11-21).

    It keeps the few one command reads again and again: the eight read
    last, the least recently read going first. And a record its store
    removes is forgotten, as the store's own reader forgets it.
    """

    @pytest.fixture
    def records(self, tmp_path, store) -> list:
        """Ten complete snapshots of one pipeline, by their records, with nothing remembered of them."""
        from chartbook import snapshot

        assert snapshot.READ_KEPT == 8
        scratch = tmp_path / "files"
        made = [_sized(FolderStore(store.root), scratch, {"a": bytes([65 + number]) * 10}, number, complete=True) for number in range(10)]
        snapshot._read_snapshots.clear()
        return made

    def _remembered(self) -> list:
        from chartbook import snapshot

        return [Path(record).parent.parent.name for record in snapshot._read_snapshots]

    def test_the_ninth_record_read_pushes_the_first_out(self, records):
        from chartbook import snapshot

        read = [snapshot.read(record) for record in records[:8]]
        assert self._remembered() == [record.parent.parent.name for record in records[:8]]
        assert all(snapshot.read(record) is taken for record, taken in zip(reversed(records[:8]), reversed(read)))
        snapshot._read_snapshots.clear()
        for record in records[:9]:
            snapshot.read(record)
        assert self._remembered() == [record.parent.parent.name for record in records[1:9]]
        again = snapshot.read(records[0])  # read again, as it is now, and the second goes for it
        assert again.made_at == LONG_AGO.format(0)
        assert self._remembered() == [record.parent.parent.name for record in [*records[2:9], records[0]]]

    def test_one_read_again_is_not_the_next_to_go(self, records):
        from chartbook import snapshot

        first = snapshot.read(records[0])
        for record in records[1:8]:
            snapshot.read(record)
        assert snapshot.read(records[0]) is first  # the least recently read is now the second
        snapshot.read(records[8])
        assert records[1].parent.parent.name not in self._remembered()
        assert snapshot.read(records[0]) is first and len(self._remembered()) == 8

    def test_however_many_records_a_process_reads_it_holds_eight(self, records):
        from chartbook import snapshot

        for _ in range(3):
            for record in records:
                snapshot.read(record)
                assert len(snapshot._read_snapshots) <= 8
        assert len(snapshot._read_snapshots) == 8
        assert snapshot.all_snapshots(FolderStore(records[0].parents[4])) and len(snapshot._read_snapshots) == 8

    def test_a_record_the_store_removes_is_forgotten(self, tmp_path, store):
        from chartbook import snapshot

        scratch = tmp_path / "files"
        first = _sized(FolderStore(store.root), scratch, {"a": b"a" * 100}, 0)
        _sized(FolderStore(store.root), scratch, {"b": b"b" * 100}, 1, complete=True)
        snapshot.read(first), store_module.read_kept_record(first)
        assert str(first) in snapshot._read_snapshots and str(first) in store_module._read_records
        _gc(store.root)
        assert not first.exists()
        assert str(first) not in store_module._read_records and str(first) not in snapshot._read_snapshots

    def test_a_record_that_has_gone_is_forgotten_when_it_is_asked_for(self, records):
        """Removed by other hands than the store's: asked for again, it is refused, and nothing of it is held."""
        from chartbook import snapshot

        snapshot.read(records[0])
        os.chmod(records[0], 0o600)
        records[0].unlink()
        with pytest.raises(snapshot.SnapshotError):
            snapshot.read(records[0])
        assert self._remembered() == []


class TestTheRowsLineReadsTheFolder:
    """The line a snapshot says of a dataframe's rows beside the snapshot before it (``60 new rows, through 2019-04-30; earlier rows unchanged``) was told by reading the new table back from the store: every file of it asked about and opened there, though the same bytes had been read and hashed in the pipeline's folder a moment before. It is told from the folder.

    From the folder only while each of its files has the size and the time
    it had when it was put, and the folder has gained and lost none. Where
    the folder has changed since, the line is what the store's copy gives,
    as before.

    What is read in the folder is said and is not remembered (found by
    review, 2026-11-21). A file's size and time do not say that its bytes
    are the snapshot's, and what a comparison finds is remembered under
    the snapshot's hash, for a later `pin --update` and a later check of a
    pin to take as what the snapshot's file gives. Only what the store's
    copy gave is remembered.
    """

    @counted
    def test_no_file_of_the_table_is_read_from_the_store(self, asked):
        for found in asked.values():
            assert found.table_reads == Counter(), found.table_reads
            last = FIRST_DAY + timedelta(days=found.files - 1)
            said = f"    acme/daily:daily: {3 * NEW} new rows, through {last.isoformat()}; earlier rows unchanged"
            assert said in found.output.splitlines(), found.output

    #: What the second snapshot says of the table: seven days where there were five
    SAID = {"acme/daily:daily": "6 new rows, through 2019-01-07; earlier rows unchanged"}

    @pytest.fixture
    def daily(self, tmp_path, store):
        """A pipeline with a first snapshot of five days, and two days more in its folder."""
        from chartbook import snapshot, standins

        project = _pipeline(tmp_path.resolve() / "project", 5)
        assert snapshot.make(project, store=store, made_at=LONG_AGO.format(0)).made
        _write_days(project, 5, 2)
        standins._compared.clear()  # what this process has compared: each test is a process of its own
        return project

    @pytest.fixture
    def read(self, daily, monkeypatch) -> list:
        """Where each table hashed for a line is read: ``folder``, the pipeline's own, or ``store``."""
        found, real = [], rowhash.hash_in

        def hashing_in(table, *arguments, **options):
            found.append("folder" if str(table.path).startswith(str(daily)) else "store")
            return real(table, *arguments, **options)

        monkeypatch.setattr(rowhash, "hash_in", hashing_in)
        return found

    def _remembered(self, store) -> list:
        """The comparisons this machine remembers."""
        return sorted((store.root.parent / "cache" / "rows" / "met").glob("*.json"))

    def _before_the_line(self, monkeypatch, change) -> None:
        """Do *change* once the snapshot's record is written, before its rows are told."""
        from chartbook import snapshot

        real = snapshot._rows_since

        def telling(*arguments, **options):
            change()
            return real(*arguments, **options)

        monkeypatch.setattr(snapshot, "_rows_since", telling)

    def test_the_table_is_read_in_the_folder_and_what_is_found_is_not_remembered(self, daily, store, read):
        from chartbook import snapshot, standins

        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.rows_said == list(self.SAID.items()) and read == ["folder"]
        assert self._remembered(store) == [] and standins._compared == {}

    def test_it_is_the_line_the_stores_copy_gives_which_is_what_is_remembered(self, daily, store, read):
        """The next to ask, a `pin --update` say, finds nothing remembered, reads the store's copy, and remembers that."""
        from chartbook import snapshot, standins

        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        before, after = second.rows_beside.assets["daily"], second.snapshot.assets["daily"]
        assert standins.since(before, after, second.snapshot, FolderStore(store.root)) == self.SAID["acme/daily:daily"]
        assert read == ["folder", "store"] and len(self._remembered(store)) == 1
        standins._compared.clear()  # and the one after that, in another process, reads nothing
        assert standins.since(before, after, second.snapshot, FolderStore(store.root)) == self.SAID["acme/daily:daily"]
        assert read == ["folder", "store"]

    @staticmethod
    def _back_as_it_was(file: Path, frame: pl.DataFrame) -> None:
        """Write a file again with other rows, and put it back at the size and the time it had: nothing the disk says of it has changed."""
        seen = file.stat()
        frame.write_parquet(file, compression="uncompressed")
        assert file.stat().st_size == seen.st_size, "the test needs the two files to be of one size"
        os.utime(file, ns=(seen.st_atime_ns, seen.st_mtime_ns))

    def test_nothing_is_remembered_of_a_folder_that_shows_no_sign_of_its_change(self, daily, store, read, monkeypatch):
        """The folder's first day is written again with other values, at the size and the time it had, once the snapshot has its bytes.

        Nothing the disk says tells that file from the one that was put,
        so the folder is read for the line, and the line printed may be of
        the folder: here it says the earlier rows changed, where the
        snapshot's are as they were. That is the limit of a look at sizes
        and times, and it is a line of output. What must hold is that
        nothing remembered is of the folder: whoever asks later reads the
        store's copy and is told what the snapshot's rows are.
        """
        from chartbook import snapshot, standins

        self._before_the_line(monkeypatch, lambda: self._back_as_it_was(_day_file(daily, 0), _day_frame(0, 5.0)))
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.made and read == ["folder"]
        assert FolderStore(store.root).verify_snapshot(second.snapshot.path) == []
        assert self._remembered(store) == [] and standins._compared == {}
        before, after = self._the_one_before(daily, store, second).assets["daily"], second.snapshot.assets["daily"]
        assert standins.since(before, after, second.snapshot, FolderStore(store.root)) == self.SAID["acme/daily:daily"]
        assert read == ["folder", "store"]

    @staticmethod
    def _the_one_before(project: Path, store, report):
        """The snapshot of the pipeline before the one a report is of."""
        from chartbook import snapshot

        return [one for one in snapshot.history(project, FolderStore(store.root)) if one.made_at < report.snapshot.made_at][-1]

    def test_what_is_remembered_is_of_the_snapshots_bytes(self, daily, store, monkeypatch):
        """The other way about, which is the one that matters later: the snapshot holds a revised first day, and the folder has the unrevised one back, at the same size and time, when the line is told.

        What the line printed says is not held here, for the reason the
        test above gives. What is remembered, and so what a later command
        is told, is that the snapshot's earlier rows are not the first
        snapshot's.
        """
        from chartbook import snapshot, standins

        _write_days(daily, 0, 1, revised=5.0)  # the build revised the first day, and the snapshot is of that
        self._before_the_line(monkeypatch, lambda: self._back_as_it_was(_day_file(daily, 0), _day_frame(0)))
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        first = self._the_one_before(daily, store, second)
        assert FolderStore(store.root).verify_snapshot(second.snapshot.path) == []
        # As another process asks later, of the same two records: a pin of the first one's rows beside the second one's file
        standins._compared.clear()
        asked_later = standins.rows_compared(first.assets["daily"], second.snapshot.assets["daily"], second.snapshot, FolderStore(store.root))
        for file in self._remembered(store):
            file.unlink()
        standins._compared.clear()
        read_again = standins.rows_compared(first.assets["daily"], second.snapshot.assets["daily"], second.snapshot, FolderStore(store.root))
        assert not read_again.same  # the snapshot's first day is not the first snapshot's
        assert asked_later.same == read_again.same and list(asked_later.differ) == list(read_again.differ)

    def test_pin_update_in_a_pipeline_that_pins_it_says_what_the_snapshots_rows_are(self, daily, store, monkeypatch, tmp_path):
        """The same, as the next command meets it on this machine: a pipeline pinned to the first snapshot runs `chartbook pin --update`, which says of the table it moves to what the snapshot's rows are, and not what the folder had when the snapshot's line was told."""
        from chartbook import lock, snapshot, standins

        report = tmp_path.resolve() / "report"
        report.mkdir()
        (report / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/report"}, "dependencies": {"acme/daily": {"path": "../project"}}}),
            encoding="utf-8", newline="\n",
        )
        assert not lock.pin(report, FolderStore(store.root)).problems
        _write_days(daily, 0, 1, revised=5.0)  # the build revised the first day, and the snapshot is of that
        self._before_the_line(monkeypatch, lambda: self._back_as_it_was(_day_file(daily, 0), _day_frame(0)))
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.made and FolderStore(store.root).verify_snapshot(second.snapshot.path) == []
        standins._compared.clear()  # the update is another process
        updated = lock.update(report, store=FolderStore(store.root))
        assert not updated.problems
        assert "earlier rows changed" in updated.rows_said["acme/daily:daily"], updated.rows_said

    def _revised(self, project: Path) -> None:
        """The first day's file is written again with other values, as a build under way would: read, it would say that earlier rows changed."""
        day = project / "_data" / "parts" / "2019-01" / "2019-01-01.parquet"
        seen = day.stat()
        pl.DataFrame({"ds": [FIRST_DAY] * 3, "unique_id": ["T0", "T1", "T2"], "y": [9.0, 9.0, 9.0]}).write_parquet(day)
        os.utime(day, ns=(seen.st_atime_ns, seen.st_mtime_ns + 5_000_000_000))  # whatever the disk's clock is good for

    @pytest.mark.parametrize("change", ["a file written again", "a day more", "a day gone"])
    def test_a_folder_that_has_changed_since_the_put_is_not_read_for_it(self, daily, store, read, monkeypatch, change):
        """A build is under way again while the snapshot is made. The line is of the snapshot's bytes, which the store has: the store's copy is read for it, as it used to be."""
        from chartbook import snapshot

        changes = {
            "a file written again": lambda: self._revised(daily),
            "a day more": lambda: _write_days(daily, 7, 1),
            "a day gone": lambda: (daily / "_data" / "parts" / "2019-01" / "2019-01-02.parquet").unlink(),
        }
        self._before_the_line(monkeypatch, changes[change])
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.made and second.rows_said == list(self.SAID.items())
        assert read == ["store"]

    def test_a_folder_that_changes_while_it_is_read_is_read_for_nothing(self, daily, store, monkeypatch):
        """Looked at before it is read and again after: what was read of a folder that changed meanwhile is not the snapshot's, is not said and is not remembered."""
        from chartbook import snapshot

        read, real = [], rowhash.hash_in

        def hashing_in(table, *arguments, **options):
            where = "folder" if str(table.path).startswith(str(daily)) else "store"
            read.append(where)
            if where == "folder":
                self._revised(daily)  # as it is read
            return real(table, *arguments, **options)

        monkeypatch.setattr(rowhash, "hash_in", hashing_in)
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.rows_said == list(self.SAID.items()) and read == ["folder", "store"]
        assert len(self._remembered(store)) == 1  # what the store's copy gave

    def test_where_the_two_records_say_it_all_nothing_is_read(self, daily, store, read):
        """The same rows in other bytes: every period has the hash it had, and no table is read, in the folder or in the store."""
        from chartbook import snapshot

        for file in sorted((daily / "_data" / "parts").rglob("*.parquet"))[5:]:
            file.unlink()  # the five days of the first snapshot
        first_day = daily / "_data" / "parts" / "2019-01" / "2019-01-01.parquet"
        pl.read_parquet(first_day).reverse().write_parquet(first_day, compression="uncompressed")
        second = snapshot.make(daily, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        assert second.made and second.rows_said == [("acme/daily:daily", "the same rows, in other bytes")]
        assert read == []


def _yields(days: int, revised: date = None) -> pl.DataFrame:
    """Two series a day from 2025-12-01; *revised* changes one value on that day."""
    when = [date(2025, 12, 1) + timedelta(days=i) for i in range(days) for _ in range(2)]
    frame = pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("T{}", pl.int_range(pl.len()) % 2),
        y=(4.0 + pl.int_range(pl.len()) * 0.01),
    )
    if revised is not None:
        frame = frame.with_columns(
            pl.when((pl.col("ds") == revised) & (pl.col("unique_id") == "T1")).then(pl.col("y") + 0.5).otherwise(pl.col("y")).alias("y")
        )
    return frame


class TestAPinMetByABuildOfYours:
    """What the rows line remembered is what a check of a pin takes a build's rows to be (found by review, 2026-11-21).

    A class with no shared store: the author pins a snapshot of an
    upstream, and a student builds that upstream at the pinned commit. A
    build of theirs with the pinned rows stands in for the pin, and one
    with a revised value does not. The check reads what is remembered of
    a build's rows beside the pin's, under the build's hash; remembered
    from a folder that had the unrevised table back when the build's line
    was told, it took the revised build for the pinned rows, and a read
    through the pin handed out rows that were never pinned.
    """

    @pytest.fixture
    def work(self, tmp_path):
        return tmp_path.resolve()

    @pytest.fixture
    def rates(self, work):
        from tests.fixtures import commit_pipeline

        directory = work / "rates"
        (directory / "_data").mkdir(parents=True)
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/rates"},
                "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "date_col": "ds", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        _yields(40).write_parquet(directory / "_data" / "treasury.parquet")
        commit_pipeline(directory)
        return directory

    @pytest.fixture
    def report(self, work, rates, monkeypatch):
        """A report that depends on it, pinned by its author in the author's own store."""
        from chartbook import config, lock, snapshot

        directory = work / "report"
        directory.mkdir()
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}}),
            encoding="utf-8", newline="\n",
        )
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "author-cache"))
        author = FolderStore(work / "author")
        snapshot.make(rates, store=author, made_at="2026-02-01T00:00:00.000000Z")
        assert not lock.pin(directory, author).problems
        return directory

    @pytest.fixture
    def student(self, work, report, monkeypatch):
        """The student's machine: another store, with nothing of the author's in it."""
        from chartbook import config, standins
        from chartbook import resolve as resolve_module

        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "student-cache"))
        resolve_module._said_stand_ins.clear()
        standins._compared.clear()
        return FolderStore(work / "student")

    def _builds(self, rates: Path, student, monkeypatch, put_back: bool):
        """The student's two builds at the pinned commit: one with the pinned rows in other bytes; then one with eight days more and a value of 2025-12-10 revised."""
        from chartbook import snapshot, standins
        from chartbook import resolve as resolve_module

        file = rates / "_data" / "treasury.parquet"
        _yields(40).write_parquet(file, compression="uncompressed")
        good = snapshot.make(rates, store=student, made_at="2026-02-02T00:00:00.000000Z")
        _yields(48, revised=date(2025, 12, 10)).write_parquet(file, compression="uncompressed")

        def unrevised_again():
            # Once the snapshot has the revised file: the folder has the unrevised one, at the size and time the revised one had
            seen = file.stat()
            _yields(48).write_parquet(file, compression="uncompressed")
            assert file.stat().st_size == seen.st_size, "the test needs the two files to be of one size"
            os.utime(file, ns=(seen.st_atime_ns, seen.st_mtime_ns))

        if put_back:
            real = snapshot._rows_since
            monkeypatch.setattr(snapshot, "_rows_since", lambda *arguments, **options: (unrevised_again(), real(*arguments, **options))[1])
        revised = snapshot.make(rates, store=FolderStore(student.root), made_at="2026-02-03T00:00:00.000000Z")
        assert good.made and revised.made
        assert FolderStore(student.root).verify_snapshot(revised.snapshot.path) == []
        standins._compared.clear()  # the check is another process
        resolve_module._said_stand_ins.clear()
        return good, revised

    def _the_pin_is_met_by_the_build_with_the_pinned_rows(self, report: Path, student, good) -> None:
        from chartbook import assets, lock

        checked = lock.verify(report, FolderStore(student.root))
        stood = checked.stood_in.get("acme/rates")
        assert stood is not None and stood.snapshot is not None
        # The newest build has a revised value on 2025-12-10: it does not meet the pin, and the one before it does
        assert stood.snapshot.made_at == good.snapshot.made_at, (
            f"the pin is said to be met by the build made {stood.snapshot.made_at}, whose table has a value of 2025-12-10 that the pin does not"
        )
        read = pl.read_parquet(assets.path("acme/rates:treasury", project_dir=report))
        pinned = _yields(40)
        assert read.filter(pl.col("ds") <= date(2026, 1, 9)).sort(["ds", "unique_id"]).equals(pinned.sort(["ds", "unique_id"]).select(read.columns))

    def test_a_revised_build_does_not_stand_in(self, report, rates, student, monkeypatch):
        good, _ = self._builds(rates, student, monkeypatch, put_back=False)
        self._the_pin_is_met_by_the_build_with_the_pinned_rows(report, student, good)

    def test_nor_where_the_folder_had_the_unrevised_table_back_when_its_line_was_told(self, report, rates, student, monkeypatch):
        good, _ = self._builds(rates, student, monkeypatch, put_back=True)
        self._the_pin_is_met_by_the_build_with_the_pinned_rows(report, student, good)


class TestTheRecordsOwnRows:
    """The rows a record says are hashed in the pipeline's folder once its files are put, and are said only where the folder still holds those files (found by review, 2026-11-21; it was so before this change too).

    A build that wrote the table again between the put and the hashing of
    its rows gave the record the rows of a file the snapshot does not
    hold. The review asked that the record then say the rows of the file
    it does hold, read from the store's copy. That half is not built:
    before the record, the store has the files under other names, or in an
    earlier snapshot's folder that nothing has looked at. What is built is
    the look: the record says nothing of the rows this time, the command
    says why, and a snapshot of the same bytes made again says them.
    """

    @pytest.fixture
    def one_file(self, tmp_path) -> Path:
        """A pipeline whose table is one file, of five days."""
        table = {"path": "./_data/daily.parquet", "date_col": "ds", "docs": "One file."}
        project = _pipeline(tmp_path.resolve() / "project", 1, dict(MANIFEST, dataframes=dict(MANIFEST["dataframes"], daily=table)))
        self._days(5).write_parquet(project / "_data" / "daily.parquet")
        return project

    def _days(self, count: int) -> pl.DataFrame:
        return pl.concat([_day_frame(number) for number in range(count)])

    def test_a_table_as_it_was_put_has_its_rows_said(self, one_file, store):
        from chartbook import snapshot

        first = snapshot.make(one_file, store=store, made_at=LONG_AGO.format(0))
        record = first.snapshot.assets["daily"]
        assert first.made and first.not_hashed_now == []
        assert (record.get("row_count"), record.get("as_of")) == (15, "2019-01-05")

    def test_one_written_again_as_its_rows_are_hashed_has_none_said_this_time(self, one_file, store, monkeypatch):
        from chartbook import snapshot

        file = one_file / "_data" / "daily.parquet"
        real, done = snapshot._rows_of, []

        def a_build_writes_it_again(name, *arguments, **options):
            if name == "daily" and not done:
                done.append(self._days(9).write_parquet(file))  # between the put and the hashing of its rows
            return real(name, *arguments, **options)

        monkeypatch.setattr(snapshot, "_rows_of", a_build_writes_it_again)
        first = snapshot.make(one_file, store=store, made_at=LONG_AGO.format(0))
        assert done and first.made
        record = first.snapshot.assets["daily"]
        held = pl.read_parquet(FolderStore(store.root).files(record["content_hash"], "acme/daily").one.location)
        assert held.height == 15, "the snapshot holds the file that was put"
        # The rows hashed were those of nine days, which the snapshot does not hold: the record says none
        assert not any(key in record for key in rowhash.FIELDS)
        assert first.not_hashed_now == [("acme/daily:daily", "its files in the pipeline's folder changed while the snapshot was made")]

        # The same bytes built again, and a snapshot made again: it is made for what the first does not say
        self._days(5).write_parquet(file)
        again = snapshot.make(one_file, store=FolderStore(store.root), made_at=LONG_AGO.format(1))
        said = again.snapshot.assets["daily"]
        assert again.made and again.not_hashed_now == [] and said["content_hash"] == record["content_hash"]
        assert (said.get("row_count"), said.get("as_of")) == (15, "2019-01-05")

    def test_the_command_says_why(self, one_file, store, monkeypatch):
        from chartbook import snapshot

        file = one_file / "_data" / "daily.parquet"
        real, done = snapshot._rows_of, []

        def a_build_writes_it_again(name, *arguments, **options):
            if name == "daily" and not done:
                done.append(self._days(9).write_parquet(file))
            return real(name, *arguments, **options)

        monkeypatch.setattr(snapshot, "_rows_of", a_build_writes_it_again)
        result = CliRunner().invoke(main, ["snapshot", "--as-is", "--project-dir", str(one_file)])
        assert result.exit_code == 0, result.output
        assert (
            "rows not hashed this time: acme/daily:daily (its files in the pipeline's folder changed while the snapshot was made). "
            "Its bytes are in the snapshot; `chartbook snapshot` again hashes its rows." in result.output
        )


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
