"""A snapshot's folder stays whole: what the writer, ``store verify`` and ``store gc`` do when one has lost a file of its own.

In a store of this layout each snapshot holds its own copy of every file
(``docs_src/design/snapshots-and-increments.md``), so the same bytes sit in
several folders, and one folder can lose a file that another still has: a
sync that has not brought it, a file removed by hand, a disk's fault.

Found by a review of the layout (2026-11-19). ``store verify`` said OK of a
store with such a hole, since another snapshot had the bytes; a run did
not fill it, since another snapshot had the bytes; and ``store gc`` then
removed that other snapshot, and with it the last whole copy of what a
snapshot it kept names. And a copy an earlier snapshot had damaged stopped
every later snapshot of the pipeline.
"""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, hashing, lock, snapshot
from chartbook.cli import _format_bytes, main
from chartbook.store import FolderStore
from tests.fixtures import _git

OLDER, OLD, NOW, LATER = (
    "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z", "2026-11-19T14:02:00.000000Z", "2026-11-19T15:02:00.000000Z",
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
    _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Work")
    return folder


def _folder_of(taken) -> Path:
    return Path(taken.path).parent.parent


def _files(folder: Path) -> list:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _writable(path: Path) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def _lose(path: Path) -> None:
    """Take one file out of the store, as a hand or a sync does."""
    _writable(path)
    path.unlink()


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
        import duckdb

        folder = work / "warehouse"
        (folder / "_data").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/warehouse"},
                "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                "dataframes": {"rates": {"source": "local", "table": "rates", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_data/\n", encoding="utf-8", newline="\n")
        connection = duckdb.connect(str(folder / "_data" / "local.duckdb"))
        connection.sql("create table rates as select 1 as day, 4.0 as rate")
        connection.close()
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
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


class TestAHoleInASnapshot:
    """The newest snapshot has lost a file that an older one still has."""

    @pytest.fixture
    def holed(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        lost = _folder_of(second) / "_data" / "treasury.parquet"
        _lose(lost)
        return first, second, lost

    def test_store_verify_says_which_snapshot_lacks_which_file(self, holed, store):
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

    def test_a_run_of_the_same_files_puts_the_file_back(self, holed, rates, store):
        first, second, lost = holed
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert not again.made and again.snapshot.path == second.path
        assert lost.read_bytes() == (rates / "_data" / "treasury.parquet").read_bytes()
        assert FolderStore(store.root).verify() == []
        _whole(second)

    def test_a_hole_is_filled_in_every_snapshot_that_has_one(self, holed, rates, store):
        first, second, lost = holed
        older = _folder_of(first) / "_data" / "treasury.parquet"
        _lose(older)
        snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert lost.is_file() and older.is_file() and FolderStore(store.root).verify() == []

    def test_a_run_does_not_say_no_new_snapshot_over_a_hole_it_cannot_reach(self, holed, rates, store):
        """A document the newest snapshot has lost is not put again before a run decides: so the run makes a snapshot, which is whole."""
        first, second, lost = holed
        _lose(_folder_of(second) / "README.md")
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert again.made and again.snapshot.path != second.path
        _whole(again.snapshot)
        # And the one that had lost them has them back, from the same run
        assert FolderStore(store.root).verify() == []

    def test_gc_keeps_the_snapshot_that_has_the_only_whole_copy_and_says_so(self, holed, store):
        first, second, lost = holed
        table = second.content()["treasury"]
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.snapshots_delete == []
        assert (first, "a snapshot that stays has lost a file that this one has whole") in plan.snapshots_kept
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert "1 because a snapshot that stays has lost a file that this one has whole" in result.output
        assert result.output.splitlines()[-1] == "Nothing to remove."
        fresh = FolderStore(store.root)
        assert fresh.has(table) and fresh.verify([table]) == []
        assert (_folder_of(first) / "_data" / "treasury.parquet").is_file()

    def test_gc_after_a_run_that_filled_it_removes_the_older_one_and_leaves_the_store_whole(self, holed, rates, store):
        first, second, lost = holed
        snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)  # a run in between, which had the file at hand
        table = second.content()["treasury"]
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        fresh = FolderStore(store.root)
        assert not _folder_of(first).exists()
        assert fresh.has(table) and fresh.verify() == []
        _whole(second)

    def test_one_kept_for_this_stays_and_what_it_has_lost_keeps_another(self, rates, store):
        """The newest has lost the table, which the second has; the second has lost its chart, which only the first has."""
        first = snapshot.make(rates, store=store, made_at=OLDER).snapshot
        (rates / "README.md").write_text("# Rates, again\n", encoding="utf-8", newline="\n")
        _git(rates, "add", "-A")
        _git(rates, "commit", "--quiet", "-m", "A word more")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        _chart(rates, "the curve, drawn again")
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        assert len({first.path, second.path, third.path}) == 3
        _lose(_folder_of(third) / "_data" / "treasury.parquet")
        _lose(_folder_of(second) / "_output" / "curve.html")
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.snapshots_delete == []
        why = "a snapshot that stays has lost a file that this one has whole"
        assert (second, why) in plan.snapshots_kept and (first, why) in plan.snapshots_kept
        # Without the second hole, the first has nothing a kept snapshot lacks, and goes
        _chart(rates, "the curve on the 16th")
        (_folder_of(second) / "_output").mkdir(exist_ok=True)
        (_folder_of(second) / "_output" / "curve.html").write_bytes((rates / "_output" / "curve.html").read_bytes())
        plan = lock.plan_gc(FolderStore(store.root))
        assert [taken for taken, _ in plan.snapshots_delete] == [first] and (second, why) in plan.snapshots_kept

    def test_a_file_of_the_wrong_size_is_not_counted_as_a_copy_that_stays(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        short = _folder_of(second) / "_data" / "treasury.parquet"
        _writable(short)
        short.write_bytes(short.read_bytes()[:10])  # a sync that has brought the first bytes of it
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.snapshots_delete == [] and first in [taken for taken, _ in plan.snapshots_kept]


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
    """One number, of what goes: in the dry run, before the question, and in the last line."""

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
        monkeypatch.setattr(lock, "run_gc", lambda plan, store=None: (1, 0))
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
