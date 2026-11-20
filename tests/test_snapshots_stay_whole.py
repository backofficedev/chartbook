"""A snapshot that has lost a file of its own: what the writer, ``store verify``, ``store gc`` and ``store move`` do.

In a store of this layout each snapshot holds its own copy of every file
(``docs_src/design/snapshots-and-increments.md``), so the same bytes sit in
several folders, and one folder can lose a file that another still has: a
sync that has not brought it, a file removed by hand, a disk's fault.

Three rules, each the plainest that holds, after two reviews of the layout
(2026-11-19 and 2026-11-20):

- A snapshot's folder is not changed once its record is written. No run
  puts a file back into one. Before a run says "No new snapshot" it asks
  whether the snapshot it would stand on is whole, one question for each of
  that snapshot's files; if not, it makes a new one from the files at hand,
  and says which file the other lacks.
- While a snapshot that stays lacks a file of its own, ``store gc`` removes
  no snapshot of its pipeline, and says which snapshot and which file.
- ``store verify`` reads every file of every snapshot where its record says
  it is, and names every one that is missing or damaged.
"""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, hashing, lock, snapshot, transfer
from chartbook import store as store_module
from chartbook.cli import _format_bytes, main
from chartbook.multi_store import NamedStore, Stores
from chartbook.store import FolderStore, StoreError
from tests.fixtures import _git

OLDER, OLD, NOW, LATER, LAST = (
    "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z", "2026-11-19T14:02:00.000000Z",
    "2026-11-19T15:02:00.000000Z", "2026-11-19T16:02:00.000000Z",
)
#: When a snapshot gc keeps as the newest of its pipeline goes, and one a lockfile pins: the way out gc names for each
NEWEST = "once a newer snapshot of its pipeline is made (`chartbook run` in its folder) and nothing else keeps it"
PINNED = "once no lockfile pins it: `chartbook pin --update` in the pipeline that does moves its pin to a newer snapshot"


def what_to_do(way: str) -> str:
    """What gc says to do where it holds a pipeline back, with the way out for the reason the snapshot is kept."""
    return (
        "  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists everything missing. "
        f"If it is lost for good, that snapshot goes {way}."
    )


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _table(folder: Path, days: int) -> None:
    pl.DataFrame({"day": list(range(days)), "rate": [4.0 + day / 10 for day in range(days)]}).write_parquet(
        folder / "_data" / "treasury.parquet"
    )


def _chart(folder: Path, text: str) -> None:
    (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n", encoding="utf-8", newline="\n")


def _commit(folder: Path) -> None:
    _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Work")


@pytest.fixture
def rates(work, store):
    """``acme/rates``: a table and a chart that git ignores, a README it tracks; built and committed."""
    folder = work / "rates"
    (folder / "_data").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "acme/rates"},
            "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text("# Rates\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _table(folder, 3)
    _chart(folder, "the curve on the 16th")
    _commit(folder)
    return folder


@pytest.fixture
def reader(work, rates):
    """A pipeline that depends on ``acme/rates`` by its folder."""
    folder = work / "reader"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"acme/rates": {"path": "../rates"}}}),
        encoding="utf-8", newline="\n",
    )
    return folder


def _parted(folder: Path, pipeline: str, years: tuple) -> Path:
    """A pipeline whose one dataframe is a folder of a file a year, and a chart; built and committed."""
    for year in years:
        (folder / "_data" / "parts" / f"year={year}").mkdir(parents=True)
        pl.DataFrame({"rate": [float(year)]}).write_parquet(folder / "_data" / "parts" / f"year={year}" / "part-0.parquet")
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": pipeline},
            "dataframes": {"parts": {"path": "./_data/parts", "docs": "d"}},
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "parts", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _chart(folder, "one")
    _commit(folder)
    return folder


def _folder_of(taken) -> Path:
    return Path(taken.path).parent.parent


def _files(folder: Path) -> list:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _state(folder: Path) -> dict:
    """Every file under a folder with its bytes: what must be the same before and after."""
    return {name: (folder / name).read_bytes() for name in _files(folder)}


def _writable(path: Path) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def _lose(path: Path, long_ago: bool = False) -> None:
    """Take one file out of the store, as a hand or a sync does.

    :param long_ago: More than an hour ago, by the time of the folder it
        was in: ``store gc`` leaves an empty folder that changed in the
        last hour for its next run, as one a snapshot may be about to
        write into, so a test that looks for a folder gone says so.
    """
    _writable(path)
    path.unlink()
    if long_ago:
        then = path.parent.stat().st_mtime - 2 * 3600
        os.utime(path.parent, (then, then))


def _whole(taken) -> None:
    """See that a snapshot's own folder holds every file its record names, each with the bytes the record says."""
    folder = _folder_of(taken)
    document = json.loads(Path(taken.path).read_text(encoding="utf-8"))
    parts = [*document["records"], document["index"], document["documents"]]
    entries = [entry for part in parts for entry in part["stored"]["files"]]
    assert entries
    for entry in entries:
        assert entry["kept_in"] == folder.name and "kept_as" not in entry
        own = folder.joinpath(*entry["path"].split("/"))
        assert own.is_file(), f"{folder.name} has lost {entry['path']}"
        assert hashing.hash_file(own).content_hash == entry["content_hash"], f"{entry['path']} in {folder.name}"


def _counted(monkeypatch, name: str) -> list:
    """Count the calls of one of the store module's functions."""
    calls: list = []
    real = getattr(store_module, name)

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module, name, counting)
    return calls


class TestAnEarlierCopyThatIsDamaged:
    """The newest snapshot's copy of a file has other bytes of the same size: a sync cut short, a disk's fault."""

    def _damaged(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        readme = _folder_of(first) / "README.md"
        _writable(readme)
        readme.write_bytes(b"# Ratez\n")
        _chart(rates, "the curve, drawn again")
        return first

    def test_the_next_snapshot_is_made_with_the_documents_as_the_pipeline_has_them(self, rates, store):
        """A document is put from a folder staged for the snapshot, which is still there when the record is written."""
        self._damaged(rates, store)
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        assert second.made
        assert (_folder_of(second.snapshot) / "README.md").read_bytes() == b"# Rates\n"
        _whole(second.snapshot)

    def test_and_so_is_the_one_after_it(self, rates, store):
        self._damaged(rates, store)
        made = [snapshot.make(rates, store=FolderStore(store.root), made_at=made_at) for made_at in (NOW, LATER)]
        assert made[0].made and not made[1].made  # the same files again: the one just made, whole
        assert made[1].snapshot.path == made[0].snapshot.path

    @pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs a file this user cannot read")
    def test_a_copy_that_cannot_be_read_is_taken_from_the_pipelines_own_file(self, rates, store):
        """There, of the right size, and not to be read: the earlier copy is tried, and then the file the snapshot was given."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        theirs = _folder_of(first) / "_data" / "treasury.parquet"
        os.chmod(theirs, 0)
        try:
            _chart(rates, "the curve, drawn again")
            second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        finally:
            os.chmod(theirs, 0o444)
        assert second.made
        assert (_folder_of(second.snapshot) / "_data" / "treasury.parquet").read_bytes() == (rates / "_data" / "treasury.parquet").read_bytes()

    def test_a_table_written_out_for_the_snapshot_is_at_hand_too(self, work, store):
        """A table in a DuckDB file is written out as parquet into a folder staged for the snapshot: its second origin."""
        folder = _warehouse(work / "warehouse", ("rates",))
        first = snapshot.make(folder, store=store, made_at=OLD).snapshot
        (written,) = (_folder_of(first) / "_chartbook" / "tables").iterdir()
        was = written.read_bytes()
        _writable(written)
        written.write_bytes(bytes(len(was)))  # the same size, other bytes
        (folder / "README.md").write_text("# Warehouse\n", encoding="utf-8", newline="\n")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "A README")
        second = snapshot.make(folder, store=FolderStore(store.root), made_at=NOW)
        assert second.made
        assert (_folder_of(second.snapshot) / "_chartbook" / "tables" / written.name).read_bytes() == was


def _warehouse(folder: Path, tables: tuple) -> Path:
    """A pipeline whose dataframes are tables in a DuckDB file, which a snapshot writes out as parquet; committed."""
    import duckdb

    (folder / "_data").mkdir(parents=True)
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "acme/warehouse"},
            "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
            "dataframes": {name: {"source": "local", "table": name, "docs": "d"} for name in tables},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / ".gitignore").write_text("/_data/\n", encoding="utf-8", newline="\n")
    connection = duckdb.connect(str(folder / "_data" / "local.duckdb"))
    for number, name in enumerate(tables):
        connection.sql(f"create table {name} as select {number} as day, 4.0 as rate")
    connection.close()
    _commit(folder)
    return folder


@pytest.fixture
def holed(rates, store):
    """Two snapshots of ``acme/rates`` with the same table, the older old enough to go; the newer has lost its copy of the table."""
    first = snapshot.make(rates, store=store, made_at=OLD).snapshot
    _chart(rates, "the curve, drawn again")
    second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
    lost = _folder_of(second) / "_data" / "treasury.parquet"
    _lose(lost)
    return first, second, lost


class TestASnapshotsFolderIsNotChangedOnceItsRecordIsWritten:
    """No run writes into a snapshot that is there. One that lacks a file is not stood on: a new one is made, whole."""

    def test_a_run_over_a_hole_in_the_newest_makes_a_new_whole_one_and_leaves_that_one_as_it_is(self, holed, rates, store):
        first, second, lost = holed
        before = _state(_folder_of(first)), _state(_folder_of(second))
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert again.made and again.snapshot.path not in (first.path, second.path)
        assert again.not_whole == (second, ["_data/treasury.parquet"])
        _whole(again.snapshot)
        assert not lost.exists() and (_state(_folder_of(first)), _state(_folder_of(second))) == before

    def test_the_command_says_in_one_line_which_snapshot_lacks_which_file(self, holed, rates, store):
        first, second, lost = holed
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates)])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == f"acme/rates at {second.commit[:7]}: 2 asset(s) in the store"
        assert lines[1] == (
            f"  The same files as the snapshot made 2026-11-19 14:02 UTC ({_folder_of(second).name}), which lacks "
            f"_data/treasury.parquet in the store: this one is whole, and that one is left as it is."
        )
        assert "Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`." in lines
        assert not lost.exists()

    def test_the_run_after_it_stands_on_the_new_one(self, holed, rates, store):
        first, second, lost = holed
        made = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LAST)
        assert made.made and not again.made and again.snapshot.path == made.snapshot.path and again.not_whole is None

    def test_a_document_the_newest_has_lost_is_reason_enough(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=NOW).snapshot
        _lose(_folder_of(first) / "README.md")
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert again.made and again.not_whole == (first, ["README.md"])
        _whole(again.snapshot)
        assert not (_folder_of(first) / "README.md").exists()

    def test_a_file_of_another_size_in_the_newest_is_reason_enough_and_is_left(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=NOW).snapshot
        short = _folder_of(first) / "_data" / "treasury.parquet"
        _writable(short)
        short.write_bytes(b"other")  # a sync that has brought the first bytes of it
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert again.made and again.not_whole == (first, ["_data/treasury.parquet"])
        assert short.read_bytes() == b"other"
        _whole(again.snapshot)

    def test_a_hole_in_an_older_snapshot_is_left_and_costs_no_copy(self, rates, store, monkeypatch):
        """The run stands on the newest, which is whole: nothing is copied to find out, run after run."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        lost = _folder_of(first) / "_data" / "treasury.parquet"
        _lose(lost)
        before = _state(_folder_of(first))
        copied = _counted(monkeypatch, "_link")
        for made_at in (LATER, LAST):
            report = snapshot.make(rates, store=FolderStore(store.root), made_at=made_at)
            assert not report.made and report.snapshot.path == second.path
        assert copied == [] and not lost.exists() and _state(_folder_of(first)) == before

    def test_a_file_at_another_size_in_an_older_snapshot_is_left_and_the_run_still_ends(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        short = _folder_of(first) / "_data" / "treasury.parquet"
        _writable(short)
        short.write_bytes(b"other")
        report = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert not report.made and short.read_bytes() == b"other"

    def test_the_bytes_an_older_snapshot_has_lost_go_into_the_new_one_alone(self, rates, store):
        """The pipeline's table is again what only an older snapshot had, which has lost it: the new one holds it, and the older is left."""
        table = rates / "_data" / "treasury.parquet"
        was = table.read_bytes()
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _table(rates, 4)
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        lost = _folder_of(first) / "_data" / "treasury.parquet"
        _lose(lost)
        assert not snapshot.make(rates, store=FolderStore(store.root), made_at=LATER).made and not lost.exists()
        table.write_bytes(was)
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=LAST)
        assert third.made and third.not_whole is None  # other bytes than the newest: a snapshot as any, not one in a holed one's place
        assert (_folder_of(third.snapshot) / "_data" / "treasury.parquet").read_bytes() == was
        assert not lost.exists()


class TestWhatAnUnchangedRunAsksOfTheDisk:
    """No hole anywhere: a run that changes nothing asks about each file it was given, and each file of the snapshot it stands on."""

    @pytest.mark.parametrize("twins, snapshots", [(20, 2), (20, 4), (40, 4)])
    def test_it_grows_with_the_files_and_not_with_the_snapshots(self, work, store, monkeypatch, twins, snapshots):
        """Partitions that hold the same bytes (the key's column is not in the file), which every snapshot repeats."""
        folder = work / "parts"
        (folder / "_output").mkdir(parents=True)
        frame = pl.DataFrame({"rate": [4.0, 4.1, 4.2]})
        for year in range(twins):
            (folder / "_data" / "parts" / f"year={2000 + year}").mkdir(parents=True)
            frame.write_parquet(folder / "_data" / "parts" / f"year={2000 + year}" / "part-0.parquet")
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/parts"},
                "dataframes": {"parts": {"path": "./_data/parts", "docs": "d"}},
                "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "parts", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_data/\n/_output/\n", encoding="utf-8", newline="\n")
        _chart(folder, "first")
        _commit(folder)
        for number in range(snapshots):
            _chart(folder, f"drawn {number}")
            assert snapshot.make(folder, store=FolderStore(store.root), made_at=f"2026-11-{number + 1:02d}T09:15:00.000000Z").made
        asked = _counted(monkeypatch, "_is_whole")
        copied = _counted(monkeypatch, "_link")
        again = snapshot.make(folder, store=FolderStore(store.root), made_at=LAST)
        assert not again.made and copied == []
        files = twins + 3  # the partitions, the chart, the manifest among its documents, the index
        assert len(asked) <= 2 * files, f"{len(asked)} questions for {files} files in {snapshots} snapshots"


class TestStoreVerify:
    def test_it_says_which_snapshot_lacks_which_file(self, holed, store):
        first, second, lost = holed
        table = second.content()["treasury"]
        (problem,) = FolderStore(store.root).verify()
        assert problem.content_hash == table and problem.path == _folder_of(second)
        assert problem.message == f"_data/treasury.parquet is not in the store (the snapshot {_folder_of(second).name})"
        result = CliRunner().invoke(main, ["store", "verify"])
        assert result.exit_code == 1
        assert result.output.splitlines()[0] == f"{table}: {problem.message}"
        assert result.output.splitlines()[-1] == f"1 of {len(first.hashes() | second.hashes())} object(s) in {store} are not what their names say."
        # Asked of the bytes alone, the store has them: a read is handed the older snapshot's copy
        assert FolderStore(store.root).verify([table]) == []

    def test_it_names_every_file_that_is_missing_or_damaged_a_snapshots_together(self, work, store):
        """Not the first bad file of an asset alone: both files of the dataset the newer has lost, and the one the older holds damaged."""
        folder = _parted(work / "parted", "acme/parted", (2020, 2021))
        first = snapshot.make(folder, store=store, made_at=OLD).snapshot
        _chart(folder, "two")
        second = snapshot.make(folder, store=FolderStore(store.root), made_at=NOW).snapshot
        parts = first.content()["parts"]
        for year in (2020, 2021):
            _lose(_folder_of(second) / "_data" / "parts" / f"year={year}" / "part-0.parquet")
        damaged = _folder_of(first) / "_data" / "parts" / "year=2021" / "part-0.parquet"
        _writable(damaged)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        now = hashing.hash_file(damaged).content_hash
        problems = FolderStore(store.root).verify()
        assert [(problem.content_hash, problem.path, problem.message) for problem in problems] == [
            (parts, _folder_of(first), f"_data/parts/year=2021/part-0.parquet is no longer what its record says (now {now}) (the snapshot {_folder_of(first).name})"),
            (parts, _folder_of(second), f"_data/parts/year=2020/part-0.parquet is not in the store (the snapshot {_folder_of(second).name})"),
            (parts, _folder_of(second), f"_data/parts/year=2021/part-0.parquet is not in the store (the snapshot {_folder_of(second).name})"),
        ]
        result = CliRunner().invoke(main, ["store", "verify"])
        assert result.exit_code == 1
        assert result.output.splitlines()[:3] == [problem.format() for problem in problems]
        assert result.output.splitlines()[-1].startswith("1 of ")  # one object, three files of it


class TestGcWhereASnapshotThatStaysLacksAFile:
    """No snapshot of its pipeline is removed, and gc says which snapshot lacks which file."""

    def test_nothing_of_the_pipeline_is_removed_and_gc_says_why(self, holed, store):
        first, second, lost = holed
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.snapshots_delete == [] and (first, lock.HELD_BACK) in plan.snapshots_kept
        assert plan.held_back == {"acme/rates": (second.path, "_data/treasury.parquet", 1)}
        for arguments in (["store", "gc", "--yes"], ["store", "gc", "--dry-run"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 0, result.output
            assert result.output.splitlines()[-4:] == [
                f"Kept: 2 snapshot(s), naming {len(first.hashes() | second.hashes())} object(s): 1 because it is the newest of "
                f"its pipeline, 1 because a snapshot of its pipeline that stays has lost a file",
                f"Nothing of acme/rates is removed: its snapshot {_folder_of(second).name} lacks _data/treasury.parquet, and stays because it is the newest of its pipeline.",
                what_to_do(NEWEST),
                "Nothing to remove.",
            ]
        assert _files(_folder_of(first)) and (_folder_of(first) / "_data" / "treasury.parquet").is_file()

    def test_a_file_of_the_wrong_size_is_lacking_too_and_the_first_of_several_is_named(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        short = _folder_of(second) / "_data" / "treasury.parquet"
        _writable(short)
        short.write_bytes(short.read_bytes()[:10])  # a sync that has brought the first bytes of it
        _lose(_folder_of(second) / "README.md")
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.snapshots_delete == [] and plan.held_back == {"acme/rates": (second.path, "README.md", 2)}
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert f"Nothing of acme/rates is removed: its snapshot {_folder_of(second).name} lacks README.md and 1 more, and stays because it is the newest of its pipeline." in result.output.splitlines()

    def test_one_that_is_itself_to_go_holds_nothing_back(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        _lose(_folder_of(first) / "_data" / "treasury.parquet", long_ago=True)
        plan = lock.plan_gc(FolderStore(store.root))
        assert [taken for taken, _ in plan.snapshots_delete] == [first] and plan.held_back == {}
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1].startswith("Removed 1 snapshot(s) and ")
        fresh = FolderStore(store.root)
        assert not _folder_of(first).exists() and snapshot.all_snapshots(fresh) == [second] and fresh.verify() == []

    def test_another_pipelines_snapshots_go_as_usual(self, holed, work, store):
        other = _parted(work / "parted", "acme/parted", (2020,))
        old = snapshot.make(other, store=FolderStore(store.root), made_at=OLD).snapshot
        _chart(other, "two")
        new = snapshot.make(other, store=FolderStore(store.root), made_at=NOW).snapshot
        plan = lock.plan_gc(FolderStore(store.root))
        assert [taken for taken, _ in plan.snapshots_delete] == [old] and list(plan.held_back) == ["acme/rates"]
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert not _folder_of(old).exists() and _folder_of(new).is_dir() and _folder_of(holed[0]).is_dir()

    def test_the_same_bytes_in_another_pipeline_never_count(self, rates, reader, work, store):
        """Another pipeline keeps the pinned table's bytes as one file of a folder dataset: no copy a read of the pin is handed."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        assert lock.pin(reader, FolderStore(store.root)).problems == []  # pins the second
        bundle = _parted(work / "bundle", "acme/bundle", (2021,))
        (bundle / "_data" / "parts" / "year=2020").mkdir()
        (bundle / "_data" / "parts" / "year=2020" / "part-0.parquet").write_bytes((rates / "_data" / "treasury.parquet").read_bytes())
        snapshot.make(bundle, store=FolderStore(store.root), made_at=NOW)
        _lose(_folder_of(second) / "_data" / "treasury.parquet")
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)  # from the first's copy
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert _folder_of(first).is_dir()
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)

    def test_three_snapshots_of_a_folder_dataset_with_holes_in_two(self, work, store):
        """The newest has lost one file of the dataset, the one before it the other; the oldest is whole, and is what a read is handed."""
        folder = _parted(work / "parted", "acme/parted", (2020, 2021))
        reads = work / "reads-parted"
        reads.mkdir()
        (reads / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/reads"}, "dependencies": {"acme/parted": {"path": "../parted"}}}),
            encoding="utf-8", newline="\n",
        )
        first = snapshot.make(folder, store=store, made_at=OLDER).snapshot
        _chart(folder, "two")
        second = snapshot.make(folder, store=FolderStore(store.root), made_at=OLD).snapshot
        _chart(folder, "three")
        third = snapshot.make(folder, store=FolderStore(store.root), made_at=NOW).snapshot
        assert lock.pin(reads, FolderStore(store.root)).problems == []  # pins the third
        _lose(_folder_of(third) / "_data" / "parts" / "year=2020" / "part-0.parquet")
        _lose(_folder_of(second) / "_data" / "parts" / "year=2021" / "part-0.parquet")
        assert data.load("acme/parted:parts", project_dir=reads).collect().shape[0] == 2
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert f"Nothing of acme/parted is removed: its snapshot {_folder_of(third).name} lacks _data/parts/year=2020/part-0.parquet, and stays because a lockfile pins it." in result.output.splitlines()
        assert sorted(taken.made_at for taken in snapshot.all_snapshots(FolderStore(store.root))) == [OLDER, OLD, NOW]
        assert data.load("acme/parted:parts", project_dir=reads).collect().shape[0] == 2


class TestAHoleNoRunCanFill:
    """A pinned snapshot has lost its table; the pipeline has moved on, and its runs make another table now."""

    @pytest.fixture
    def stuck(self, rates, reader, store):
        first = snapshot.make(rates, store=store, made_at=OLDER).snapshot
        _chart(rates, "drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        assert lock.pin(reader, FolderStore(store.root)).problems == []  # the reader pins the second
        _table(rates, 4)
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        assert len({first.path, second.path, third.path}) == 3
        _lose(_folder_of(second) / "_data" / "treasury.parquet", long_ago=True)
        return first, second, third

    def test_gc_says_which_snapshot_lacks_which_file_and_removes_nothing_of_the_pipeline(self, stuck, rates, store):
        first, second, third = stuck
        for made_at in (LATER, LAST):
            snapshot.make(rates, store=FolderStore(store.root), made_at=made_at)  # runs in between mend nothing, and are said to mend nothing
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert f"Nothing of acme/rates is removed: its snapshot {_folder_of(second).name} lacks _data/treasury.parquet, and stays because a lockfile pins it." in lines
        assert what_to_do(PINNED) in lines and lines[-1] == "Nothing to remove."
        assert "puts it back" not in result.output and "puts it back" not in CliRunner().invoke(main, ["store", "gc", "--help"]).output
        assert _folder_of(first).is_dir()

    def test_the_reader_still_reads_before_gc_and_after(self, stuck, reader, store):
        first, second, third = stuck
        for _ in range(2):
            assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)
            assert data.path("acme/rates:treasury", project_dir=reader) == _folder_of(first) / "_data" / "treasury.parquet"
            assert CliRunner().invoke(main, ["store", "gc", "--yes"]).exit_code == 0

    def test_it_goes_once_nothing_pins_it_any_more(self, stuck, reader, store):
        """What gc says of a snapshot that has lost a file for good, carried out: the pin is let go, and the snapshot is one to remove like any."""
        first, second, third = stuck
        (reader / "chartbook.lock").unlink()
        result = CliRunner().invoke(main, ["store", "gc", "--yes", "--forget-missing"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1].startswith("Removed 2 snapshot(s) and ")
        fresh = FolderStore(store.root)
        assert snapshot.all_snapshots(fresh) == [third] and fresh.verify() == []
        assert not _folder_of(first).exists() and not _folder_of(second).exists()


class TestWhatGcSaysAfterTheYes:
    """What was removed and freed, and what was kept after all with why: never "pinned" of what was not."""

    def test_a_hole_that_appears_between_the_plan_and_the_yes(self, rates, store, monkeypatch):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        only_its = len(first.hashes() - second.hashes())
        real = lock.carry_out_gc

        def after_the_yes(plan, the_store=None):
            _lose(_folder_of(second) / "_data" / "treasury.parquet")  # a sync, a hand: between the plan and the yes
            return real(plan, the_store)

        monkeypatch.setattr(lock, "carry_out_gc", after_the_yes)
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert _state(_folder_of(first)) and (_folder_of(first) / "_data" / "treasury.parquet").is_file()
        assert result.output.splitlines()[-5:] == [
            f"Kept after all: acme/rates at {first.commit[:7]}, made 2026-01-01 09:15 UTC: a snapshot of its pipeline that stays has lost a file",
            f"Kept after all: {only_its} object(s), which a lockfile or a snapshot names or uses now",
            f"Nothing of acme/rates is removed: its snapshot {_folder_of(second).name} lacks _data/treasury.parquet, and stays because it is the newest of its pipeline.",
            what_to_do(NEWEST),
            "Removed 0 snapshot(s) and 0 object(s), 0 bytes.",
        ]
        assert "pinned" not in "\n".join(result.output.splitlines()[-5:])

    def test_one_pinned_while_the_question_stood_is_said_to_be_pinned(self, rates, reader, store, monkeypatch):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        assert lock.pin(reader, FolderStore(store.root)).problems == []  # pins the first
        lockfile = (reader / "chartbook.lock").read_bytes()
        (reader / "chartbook.lock").unlink()
        _chart(rates, "again")
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        real = lock.carry_out_gc

        def after_the_yes(plan, the_store=None):
            (reader / "chartbook.lock").write_bytes(lockfile)  # the lockfile is back: a branch switched, a drive plugged in
            return real(plan, the_store)

        monkeypatch.setattr(lock, "carry_out_gc", after_the_yes)
        result = CliRunner().invoke(main, ["store", "gc", "--yes", "--forget-missing"])
        assert result.exit_code == 0, result.output
        assert f"Kept after all: acme/rates at {first.commit[:7]}, made 2026-01-01 09:15 UTC: a lockfile pins it" in result.output.splitlines()
        assert result.output.splitlines()[-1] == "Removed 0 snapshot(s) and 0 object(s), 0 bytes."
        assert _folder_of(first).is_dir()


class TestEachKeptSnapshotsOwnFilesAfterAGc:
    def test_every_file_a_kept_snapshots_record_names_is_in_its_own_folder(self, rates, store):
        """Three snapshots with the same table; gc removes the two older ones, and the newest still holds every file of it."""
        snapshot.make(rates, store=store, made_at=OLDER)
        _chart(rates, "the curve, drawn again")
        snapshot.make(rates, store=FolderStore(store.root), made_at=OLD)
        _chart(rates, "and again")
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Removed 2 snapshot(s)" in result.output.splitlines()[-1]
        fresh = FolderStore(store.root)
        assert snapshot.all_snapshots(fresh) == [third]
        _whole(third)
        assert sorted(p.name for p in store.pipeline_path("acme/rates").iterdir()) == sorted(["README.txt", _folder_of(third).name])
        assert fresh.verify() == []


class TestGcWhileASnapshotIsBeingMade:
    def test_the_snapshot_being_made_is_written_whole_and_the_next_gc_leaves_no_folder(self, rates, store):
        """A file only an old snapshot has is taken up again by one being made while gc removes the old one."""
        table = rates / "_data" / "treasury.parquet"
        was = table.read_bytes()
        first = snapshot.make(rates, store=store, made_at=OLDER).snapshot
        _table(rates, 4)
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        _chart(rates, "again")
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        assert len({first.path, second.path, third.path}) == 3
        # The table goes back to what only the first snapshot had, and a fourth snapshot is begun
        table.write_bytes(was)
        fourth = FolderStore(store.root).begin("acme/rates", "d" * 40, LATER, base=rates)
        put = fourth.put(table)
        assert not fourth.placed and put.content_hash == first.content()["treasury"]
        table.unlink()  # the pipeline's own file is being rebuilt meanwhile: only the store has these bytes now
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Removed 2 snapshot(s)" in result.output, result.output
        document = json.loads(Path(third.path).read_text(encoding="utf-8"))
        document["code"]["commit"], document["made_at"] = "d" * 40, LATER
        document["records"] = [
            dict(r, stored=put.stored, content_hash=put.content_hash) for r in document["records"] if r["id"].endswith(":treasury")
        ]
        document.pop("index", None), document.pop("documents", None)
        record = fourth.write(document)
        assert (Path(record).parent.parent / "_data" / "treasury.parquet").read_bytes() == was
        left = _folder_of(first)
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert not left.exists(), (_files(left), result.output)
        assert FolderStore(store.root).verify() == []


class TestWhatGcSaysBeforeItAsks:
    """The size of what goes, in the dry run and before the question: with the removed snapshots' own copies of what stays."""

    def test_a_snapshot_whose_files_a_kept_one_has_too(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        own = _format_bytes(sum(p.stat().st_size for p in _folder_of(first).rglob("*") if p.is_file() and p.name != "snapshot.json"))
        only_its = len(first.hashes() - second.hashes())
        header = f"Would remove 1 snapshot(s) and {only_its} object(s) that nothing names, {own}:"
        listed = (
            f"  acme/rates at {first.commit[:7]}, made 2026-01-01 09:15 UTC: nothing pins it, it is not the newest, "
            f"and it is older than 7 days"
        )
        dry = CliRunner().invoke(main, ["store", "gc", "--dry-run"]).output.splitlines()
        assert header in dry and dry[dry.index(header) + 1] == listed
        # The dry run lists each object too, and what else goes with the folder: the sizes add up to the one said
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.copies_bytes and plan.freed_bytes == plan.size_bytes + plan.copies_bytes
        assert dry[dry.index(header) + 2:] == [
            *(f"  {content_hash}  {_format_bytes(size)}" for content_hash, size in plan.delete),
            f"  and the removed snapshots' own copies of files a kept snapshot has too  {_format_bytes(plan.copies_bytes)}",
        ]
        asked = CliRunner().invoke(main, ["store", "gc"], input="n\n").output.splitlines()
        assert asked[-4:-1] == [header, listed, "Remove them? [y/N]: n"] and asked[-1] == "Nothing was removed."
        done = CliRunner().invoke(main, ["store", "gc", "--yes"]).output.splitlines()
        assert header in done and done[-1] == f"Removed 1 snapshot(s) and {only_its} object(s), {own}."

    def test_snapshots_that_alone_name_nothing_say_what_their_folders_hold(self, rates, store, monkeypatch):
        """Every object of the snapshot that goes is one a kept snapshot has too: no object goes, and its own copies do.

        A plan made by hand, since a real snapshot always has an index of its own.
        """
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        plan = lock.GcPlan(snapshots_delete=[(first, "nothing pins it")], copies={"snapshots/acme+rates/x/_data/treasury.parquet": 2048})
        assert plan.size_bytes == 0 and plan.copies_bytes == plan.freed_bytes == 2048
        monkeypatch.setattr(lock, "plan_gc", lambda *arguments, **options: plan)
        monkeypatch.setattr(lock, "carry_out_gc", lambda plan, store=None: lock.GcDone(1, 0, 2048))
        listed = f"  acme/rates at {first.commit[:7]}, made 2026-01-01 09:15 UTC: nothing pins it"
        dry = CliRunner().invoke(main, ["store", "gc", "--dry-run"]).output.splitlines()
        assert dry[-2:] == ["Would remove 1 snapshot(s), 2.0 KB:", listed]
        asked = CliRunner().invoke(main, ["store", "gc"], input="y\n").output.splitlines()
        assert asked[-4:] == [
            "Would remove 1 snapshot(s), 2.0 KB:", listed, "Remove them? [y/N]: y", "Removed 1 snapshot(s) and 0 object(s), 2.0 KB.",
        ]

    def test_what_could_not_all_be_removed_says_what_was(self, rates, store, monkeypatch):
        """Where something stayed, the line says what went: the objects, and the removed snapshots' own copies."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        own = sum(p.stat().st_size for p in _folder_of(first).rglob("*") if p.is_file() and p.name != "snapshot.json")
        fresh = FolderStore(store.root)
        plan = lock.plan_gc(fresh)
        forget = FolderStore.remove_root

        def refused(self, lockfile, machine=None):
            raise OSError("not this time")

        plan.forget.append(Path("/nowhere/chartbook.lock"))  # one more thing to do, which fails
        monkeypatch.setattr(lock, "plan_gc", lambda *arguments, **options: plan)
        monkeypatch.setattr(FolderStore, "remove_root", refused)
        with pytest.raises(lock.GcError) as failed:
            lock.run_gc(plan, fresh)
        monkeypatch.setattr(FolderStore, "remove_root", forget)
        assert failed.value.removed_snapshots == 1 and failed.value.size_bytes == own == plan.freed_bytes


class TestStoreMoveWhereTheTargetsOwnSnapshotLacksAFile:
    def test_the_move_stops_before_anything_is_removed_and_says_which_file(self, rates, work, store):
        """The target has both snapshots already, so another of its snapshots has the bytes; its own copy of one has lost them."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "again")
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        target = work / "target"

        def stores():
            return Stores([
                NamedStore("here", str(store.root), FolderStore(store.root)),
                NamedStore("there", str(target), FolderStore(target), create=True),
            ])

        transfer.move("acme/rates", stores(), "there", keep=True, route=False)
        copies = {taken.made_at: taken for taken in snapshot.all_snapshots(FolderStore(target))}
        assert len(copies) == 2 and FolderStore(target).verify() == []
        _lose(_folder_of(copies[OLD]) / "_data" / "treasury.parquet")  # a sync that has not brought it
        here = _state(store.root)
        with pytest.raises(StoreError) as stopped:
            transfer.move("acme/rates", stores(), "there", keep=False, route=False)
        assert str(stopped.value) == (
            f"The store at {FolderStore(target)} has the snapshot of acme/rates made {OLD} already, in "
            f"{_folder_of(copies[OLD]).name}, and not whole: _data/treasury.parquet is not in the store. Nothing was removed "
            f"from where it came from. If a sync is still bringing it, wait for the sync to finish and move again; "
            f"`chartbook store verify` there lists everything missing or damaged."
        )
        assert _state(store.root) == here and len(snapshot.all_snapshots(FolderStore(store.root))) == 2
        assert (_folder_of(first) / "_data" / "treasury.parquet").is_file()


class TestWhatIsStagedForASnapshot:
    """A file staged for a snapshot goes as soon as the snapshot has it in its own folder; one whose copy waits for the record stays until then."""

    @pytest.fixture
    def temporary(self, work, monkeypatch):
        import tempfile

        scratch = work / "tmp-of-the-system"
        scratch.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(scratch))
        return scratch

    @staticmethod
    def _at_the_record(temporary, monkeypatch) -> list:
        """What is staged at the moment each snapshot's record is written, by its path in the staging folder."""
        seen: list = []
        write = store_module._FolderPending.write

        def looked(self, document):
            seen.append(sorted(p.relative_to(temporary).as_posix().split("/", 1)[1] for p in temporary.rglob("*") if p.is_file()))
            return write(self, document)

        monkeypatch.setattr(store_module._FolderPending, "write", looked)
        return seen

    def test_only_what_waits_for_the_record_is_kept_until_then(self, rates, store, temporary, monkeypatch):
        seen = self._at_the_record(temporary, monkeypatch)
        assert snapshot.make(rates, store=store, made_at=OLD).made
        _chart(rates, "again")
        assert snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).made
        # The first has everything in its own folder as soon as it is put; the second repeats its documents, and has a new index
        assert seen == [[], ["documents/README.md", "documents/chartbook.toml"]]
        assert list(temporary.iterdir()) == []

    def test_a_table_written_out_is_not_kept_while_the_next_is(self, work, store, temporary, monkeypatch):
        """Room for one table at a time where the store had none of them: not for their sum."""
        folder = _warehouse(work / "warehouse", ("a", "b", "c"))
        staged: list = []
        put = store_module._FolderPending.put

        def looked(self, path, place=None, links=("reflink", "copy")):
            staged.append(sorted(p.name for p in (temporary.rglob("tables/*"))))
            return put(self, path, place, links)

        monkeypatch.setattr(store_module._FolderPending, "put", looked)
        assert snapshot.make(folder, store=store, made_at=OLD).made
        assert [names for names in staged if names] == [["a.parquet"], ["b.parquet"], ["c.parquet"]]
        assert list(temporary.iterdir()) == []

    def test_nothing_is_left_after_a_snapshot_one_that_is_not_made_and_one_that_is_stopped(self, rates, store, temporary, monkeypatch):
        assert snapshot.make(rates, store=store, made_at=OLD).made
        assert list(temporary.iterdir()) == []
        assert not snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).made
        assert list(temporary.iterdir()) == []
        _chart(rates, "again")

        def stopped(self, document):
            raise KeyboardInterrupt

        monkeypatch.setattr(store_module._FolderPending, "write", stopped)
        with pytest.raises(KeyboardInterrupt):
            snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert list(temporary.iterdir()) == []
        tmp = store.root / "_chartbook" / "tmp"
        assert not tmp.is_dir() or list(tmp.iterdir()) == []
