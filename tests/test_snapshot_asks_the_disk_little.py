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
