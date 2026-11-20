"""A folder store reads snapshots kept as increments (``docs_src/design/snapshots-and-increments.md``).

An increment is a snapshot of its pipeline like any other: its folder is
``increments/<pipeline>/<snapshot>/``, it holds the files that one complete
snapshot of the pipeline does not have, and its record says where each of
its files is, in one of the two folders. Nothing in ordinary use makes one
yet; ``tests/increments.py`` writes what ``chartbook store migrate`` will.

Each thing here is asked of a store in both shapes: an older complete
snapshot with later increments on it, and the newest complete with the
older ones increments on it.
"""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.store import FolderStore
from tests.fixtures import _git
from tests.increments import with_increments

OLDER, OLD, OLDISH = "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z", "2026-02-01T09:15:00.000000Z"
SHAPES = ("oldest", "newest")


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _commit(folder: Path, message: str = "Work") -> None:
    if not (folder / ".git").exists():
        _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", message)


def _table(folder: Path, days: int) -> None:
    pl.DataFrame({"day": list(range(days)), "rate": [4.0 + day / 10 for day in range(days)]}).write_parquet(
        folder / "_data" / "treasury.parquet"
    )


def _part(folder: Path, year: int) -> None:
    (folder / "_data" / "parts").mkdir(exist_ok=True)
    pl.DataFrame({"year": [year], "rate": [float(year)]}).write_parquet(folder / "_data" / "parts" / f"{year}.parquet")


def _chart(folder: Path, text: str) -> None:
    (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n", encoding="utf-8", newline="\n")


def _folder_of(taken) -> Path:
    return Path(taken.path).parent.parent


def _lose(path: Path) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()
    then = path.parent.stat().st_mtime - 2 * 3600
    os.utime(path.parent, (then, then))
    store_module._found_whole.clear()


@pytest.fixture
def rates(work, store):
    """A pipeline with a table, a dataset in parts and a chart, which git ignores, and a README it tracks."""
    folder = work / "rates"
    (folder / "_data").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "acme/rates"},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "parts": {"path": "./_data/parts/", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text("# acme/rates\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _table(folder, 3)
    _part(folder, 2020)
    _chart(folder, "one")
    _commit(folder)
    return folder


def _reader(folder: Path) -> Path:
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": {"acme/rates": {"path": "../rates"}}}),
        encoding="utf-8", newline="\n",
    )
    return folder


@pytest.fixture
def three(rates, work, store):
    """Three snapshots of rates, each with a part more and another chart; a reader pinned to each of them. The snapshots, oldest first, and the readers."""
    taken, readers = [], []
    for number, (made_at, year, text) in enumerate(((OLDER, 2020, "one"), (OLD, 2021, "two"), (OLDISH, 2022, "three"))):
        _part(rates, year)
        _chart(rates, text)
        taken.append(snapshot.make(rates, store=FolderStore(store.root), made_at=made_at).snapshot)
        readers.append(_reader(work / f"reader{number}"))
        assert lock.pin(readers[-1], FolderStore(store.root)).problems == []
    return taken, readers


@pytest.fixture(params=SHAPES)
def kept(request, three, store):
    """The same store with all but one snapshot of rates kept as increments, in one of the two shapes: the complete one's folder, the increments' folders, the snapshots and the readers."""
    taken, readers = three
    complete, increments = with_increments(store.root, request.param)["acme+rates"]
    return complete, increments, taken, readers


class TestWhatAnIncrementIs:
    def test_its_folder_its_record_and_its_line_for_a_person(self, kept, store):
        complete, increments, taken, _ = kept
        assert len(increments) == 2 and all(folder.parent == store.root / "increments" / "acme+rates" for folder in increments)
        for folder in increments:
            document = json.loads((folder / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
            assert document["stored"] == {"builds_on": complete.name}
            assert (folder / "_chartbook" / "INCREMENT.txt").read_text(encoding="utf-8") == (
                f"The rest of this snapshot's files are in snapshots/acme+rates/{complete.name}\n"
            )
            kept_in = {entry["kept_in"] for part in document["records"] for entry in part["stored"]["files"]}
            assert kept_in == {folder.name, complete.name}
            assert not (folder / "_data" / "treasury.parquet").exists()  # the table never changed: kept once, in the complete one
        records = FolderStore(store.root).records()
        assert [(record.folder.name, record.increment, record.builds_on) for record in records] == sorted(
            [(complete.name, False, "")] + [(folder.name, True, complete.name) for folder in increments]
        )
        assert {(record.pipeline, record.made_at) for record in records} == {("acme/rates", one.made_at) for one in taken}

    def test_every_snapshot_is_whole_and_verifies(self, kept, store):
        complete, increments, taken, _ = kept
        fresh = FolderStore(store.root)
        for record in fresh.records():
            assert fresh.holes_of(record.path) == [] and fresh.verify_snapshot(record.path) == []
        assert fresh.verify() == []
        result = CliRunner().invoke(main, ["store", "verify"])
        assert result.exit_code == 0, result.output


class TestReads:
    def test_each_pin_is_read_where_its_files_are(self, kept, store):
        complete, increments, taken, readers = kept
        folders = {folder.name: folder for folder in [complete, *increments]}
        for one, reader in zip(taken, readers):
            folder = folders[_folder_of(one).name]
            assert lock.verify(reader, FolderStore(store.root), note=False).problems == []
            # The table is in the complete one's folder whichever snapshot is read; the chart is in the snapshot's own
            assert Path(data.path("acme/rates:treasury", project_dir=reader)) == complete / "_data" / "treasury.parquet"
            parts = [Path(path) for path in data.files("acme/rates:parts", project_dir=reader)]
            assert [path.name for path in parts] == sorted(f"{year}.parquet" for year in (2020, 2021, 2022))[: taken.index(one) + 1]
            assert all(path.is_file() and path.parents[2] in (folder, complete) for path in parts)
            assert data.load("acme/rates:parts", project_dir=reader).collect().height == taken.index(one) + 1


@pytest.fixture
def unpinned(rates, store):
    """Three snapshots of rates that nothing pins, each with a part more and another chart, all older than a week; oldest first."""
    taken = []
    for made_at, year, text in ((OLDER, 2020, "one"), (OLD, 2021, "two"), (OLDISH, 2022, "three")):
        _part(rates, year)
        _chart(rates, text)
        taken.append(snapshot.make(rates, store=FolderStore(store.root), made_at=made_at).snapshot)
    return taken


def _files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


class TestGc:
    """An increment that goes, goes whole and takes nothing of the one it builds on; a complete one stays while an increment that stays builds on it."""

    @pytest.mark.parametrize("arguments", [[], ["--aggressive"], ["--keep-lineage"]])
    def test_the_oldest_complete_stays_for_the_newest_which_builds_on_it(self, unpinned, store, arguments):
        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        middle, newest = increments
        before = _files(complete)
        dry = CliRunner().invoke(main, ["store", "gc", "--dry-run", *arguments])
        assert dry.exit_code == 0 and "Would remove 1 snapshot(s)" in dry.output, dry.output
        assert "1 because an increment that stays builds on it" in dry.output, dry.output
        result = CliRunner().invoke(main, ["store", "gc", "--yes", *arguments])
        assert result.exit_code == 0 and result.output.splitlines()[-1].startswith("Removed 1 snapshot(s) and "), result.output
        assert not middle.exists() and newest.is_dir() and _files(complete) == before
        fresh = FolderStore(store.root)
        assert [record.folder for record in fresh.records()] == [complete, newest] and fresh.verify() == []
        assert CliRunner().invoke(main, ["store", "gc", "--yes", *arguments]).output.splitlines()[-1] == "Nothing to remove."

    def test_with_the_newest_complete_the_older_increments_go_and_it_stays_whole(self, unpinned, store):
        complete, increments = with_increments(store.root, "newest")["acme+rates"]
        before = _files(complete)
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and result.output.splitlines()[-1].startswith("Removed 2 snapshot(s) and "), result.output
        assert not any(folder.exists() for folder in increments) and _files(complete) == before
        fresh = FolderStore(store.root)
        assert [record.folder for record in fresh.records()] == [complete] and fresh.verify() == []

    def test_what_it_says_it_frees_is_what_goes(self, unpinned, store):
        from chartbook.cli import _format_bytes

        complete, increments = with_increments(store.root, "newest")["acme+rates"]
        size = sum(path.stat().st_size for folder in increments for path in folder.rglob("*") if path.is_file() and path.name not in ("snapshot.json", "INCREMENT.txt"))
        plan = lock.plan_gc(FolderStore(store.root))
        assert plan.freed_bytes == size
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.output.splitlines()[-1].endswith(f", {_format_bytes(size)}."), result.output


class TestStoreLs:
    def test_it_says_complete_or_increment_of_each(self, kept, store):
        from chartbook.cli import _format_bytes

        complete, increments, taken, _ = kept
        result = CliRunner().invoke(main, ["store", "ls"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == "acme/rates (3 snapshot(s))"
        kinds = {line.split()[0]: line.split()[5] for line in lines[1:4]}
        assert kinds == {complete.name: "complete", **{folder.name: "increment" for folder in increments}}
        for folder in increments:
            own = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and p.name not in ("snapshot.json", "INCREMENT.txt"))
            (line,) = [line for line in lines if line.split()[:1] == [folder.name]]
            assert f"  increment  {_format_bytes(own)} here, " in line and line.endswith(f" file(s) in {complete.name}"), line
        assert lines[4:] == [
            "A complete snapshot's folder holds every file of its version, and can be read or copied as it is. "
            "Remove snapshots with `chartbook store gc`, never by hand.",
            "An increment's folder holds the files that the complete snapshot it builds on does not have; the rest are "
            "in that one's folder (in a store that ChartBook 0.5 laid out, in other snapshots' folders), which "
            "`chartbook store gc` keeps while a snapshot uses them. Remove snapshots with gc, never by hand.",
        ]


class TestForAPersonWhoOpensTheFolders:
    def test_each_pipelines_folder_says_what_it_holds(self, kept, store):
        complete, increments, _, _ = kept
        under_snapshots = (complete.parent / "README.txt").read_text(encoding="utf-8")
        assert "one complete snapshot" in under_snapshots and "a snapshot\nthat an increment builds on" in under_snapshots
        under_increments = (increments[0].parent / "README.txt").read_text(encoding="utf-8")
        assert under_increments == store_module.INCREMENTS_README and "_chartbook/INCREMENT.txt says which one" in under_increments


class TestTheSameSnapshotInBothFolders:
    def test_the_complete_one_is_the_snapshot_and_verify_names_the_other(self, unpinned, work, store):
        import shutil

        shutil.copytree(store.root, work / "copy")  # the same store, with every snapshot complete
        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        doubled = increments[0]
        shutil.copytree(work / "copy" / "snapshots" / "acme+rates" / doubled.name, complete.parent / doubled.name)
        store_module._read_records.clear()
        fresh = FolderStore(store.root)
        assert [(record.folder.parent.parent.name, record.folder.name) for record in fresh.records()] == sorted(
            [("snapshots", complete.name), ("snapshots", doubled.name), ("increments", increments[1].name)], key=lambda pair: pair[1]
        )
        assert [problem.message for problem in fresh.verify()] == [
            f"increments/acme+rates/{doubled.name} is of a snapshot that snapshots/acme+rates/ keeps complete: the "
            f"complete one is the snapshot, and this folder is not read"
        ]
        result = CliRunner().invoke(main, ["store", "verify"])
        assert result.exit_code == 1 and f"increments/acme+rates/{doubled.name} is of a snapshot that" in result.output


class TestDamaged:
    """What a person sees, where an increment has lost a file in one of its two folders."""

    def test_a_file_missing_from_its_own_folder(self, kept, store):
        complete, increments, taken, readers = kept
        holed = increments[0]
        (index,) = [i for i, one in enumerate(taken) if _folder_of(one).name == holed.name]
        _lose(holed / "_output" / "curve.html")
        fresh = FolderStore(store.root)
        assert fresh.holes_of(holed / "_chartbook" / "snapshot.json") == ["_output/curve.html"]
        assert [problem.message for problem in fresh.verify()] == [f"_output/curve.html is not in the store (the snapshot {holed.name})"]
        # The rest of it is still read, from both folders
        assert Path(data.path("acme/rates:treasury", project_dir=readers[index])).is_file()
        assert data.load("acme/rates:parts", project_dir=readers[index]).collect().height == index + 1

    def test_a_file_missing_from_the_one_it_builds_on(self, kept, store):
        complete, increments, taken, readers = kept
        _lose(complete / "_data" / "treasury.parquet")
        fresh = FolderStore(store.root)
        for folder in (complete, *increments):  # a hole of each snapshot that keeps the table there
            assert fresh.holes_of(folder / "_chartbook" / "snapshot.json") == ["_data/treasury.parquet"]
        assert [problem.message for problem in fresh.verify()] == [f"_data/treasury.parquet is not in the store (the snapshot {complete.name})"]
        for reader in readers:
            with pytest.raises(AssetNotPinnedError) as refused:
                data.path("acme/rates:treasury", project_dir=reader)
            assert "does not have it" in str(refused.value) or "not fully synced" in str(refused.value)

    def test_the_one_it_builds_on_gone(self, kept, store):
        import shutil

        complete, increments, taken, readers = kept

        def writable(function, path, _):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)

        shutil.rmtree(complete, onerror=writable)
        store_module._read_records.clear()
        store_module._found_whole.clear()
        fresh = FolderStore(store.root)
        assert [record.folder for record in fresh.records()] == sorted(increments)
        for folder in increments:
            holes = fresh.holes_of(folder / "_chartbook" / "snapshot.json")
            assert "_data/treasury.parquet" in holes and "_output/curve.html" not in holes  # what it kept there; its own is here
        (index,) = [i for i, one in enumerate(taken) if _folder_of(one).name == increments[0].name]
        with pytest.raises(AssetNotPinnedError):
            data.path("acme/rates:treasury", project_dir=readers[index])
        result = CliRunner().invoke(main, ["store", "verify"])
        assert result.exit_code == 1 and "_data/treasury.parquet is not in the store (the snapshot " in result.output

    def test_a_file_there_at_its_size_with_other_bytes(self, kept, store):
        complete, increments, taken, readers = kept
        damaged = complete / "_data" / "treasury.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        store_module._found_whole.clear()
        fresh = FolderStore(store.root)
        assert all(fresh.holes_of(folder / "_chartbook" / "snapshot.json") == [] for folder in (complete, *increments))  # no size tells
        for folder in (complete, *increments):  # and each snapshot that keeps it there is found by reading it
            (problem,) = fresh.verify_snapshot(folder / "_chartbook" / "snapshot.json")
            assert problem.message.startswith("_data/treasury.parquet is no longer what its record says")
        (said,) = [problem.message for problem in fresh.verify()]
        assert said.startswith("_data/treasury.parquet is no longer what its record says") and said.endswith(f"(the snapshot {complete.name})")


def _form(root: Path) -> list:
    """Each snapshot of a store as it is kept: its folder's name, whether it is an increment, and what it builds on."""
    store_module._read_records.clear()
    return [(record.folder.name, record.increment, record.builds_on) for record in FolderStore(root).records()]


class TestCopiesKeepTheirForm:
    """`store move`, `store export` and `store import`: each complete snapshot, then the increments on it."""

    @pytest.fixture(params=SHAPES)
    def shaped(self, request, unpinned, store):
        complete, increments = with_increments(store.root, request.param)["acme+rates"]
        return request.param, complete, increments, _form(store.root)

    def test_store_move(self, shaped, work, store):
        from chartbook import transfer
        from chartbook.multi_store import NamedStore, Stores

        _, complete, increments, form = shaped
        target = work / "target"
        stores = Stores([
            NamedStore("here", str(store.root), FolderStore(store.root)),
            NamedStore("there", str(target), FolderStore(target), create=True),
        ])
        transfer.move("acme/rates", stores, "there", keep=False, route=False)
        assert _form(target) == form and FolderStore(target).verify() == []
        moved = target / "increments" / "acme+rates" / increments[0].name
        assert json.loads((moved / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))["stored"] == {"builds_on": complete.name}
        assert (moved / "_chartbook" / "INCREMENT.txt").read_text(encoding="utf-8") == (
            f"The rest of this snapshot's files are in snapshots/acme+rates/{complete.name}\n"
        )
        assert (moved.parent / "README.txt").read_text(encoding="utf-8") == store_module.INCREMENTS_README
        assert not (moved / "_data" / "treasury.parquet").exists()  # kept once, in the one it builds on
        assert _form(store.root) == [] and not complete.exists() and not any(folder.exists() for folder in increments)

    def test_export_and_import(self, shaped, work, store):
        from chartbook import sharing

        _, complete, increments, form = shaped
        out = work / "out"
        done = sharing.export(FolderStore(store.root), "acme/rates", out, None)
        assert len(done.copied) == 3 and done.refused == []
        assert _form(out) == form and FolderStore(out).verify() == []
        other = work / "other"
        done = sharing.import_snapshots(FolderStore(other), out)
        assert len(done.copied) == 3 and done.refused == []
        assert _form(other) == form and FolderStore(other).verify() == []
        # Again: each is there already, whole, and nothing is written
        again = sharing.import_snapshots(FolderStore(other), out)
        assert len(again.there) == 3 and again.copied == [] and again.refused == []

    def test_export_latest_is_one_complete_snapshot(self, shaped, work, store):
        from chartbook import sharing

        shape, complete, increments, form = shaped
        newest = max(name for name, _, _ in form)
        out = work / "out"
        done = sharing.export(FolderStore(store.root), "acme/rates", out, "latest")
        assert len(done.copied) == 1
        assert _form(out) == [(newest, False, "")] and FolderStore(out).verify() == []
        assert (out / "snapshots" / "acme+rates" / newest / "_data" / "treasury.parquet").is_file()
        assert not (out / "increments").exists()
        assert "stored" not in json.loads((out / "snapshots" / "acme+rates" / newest / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))

    def test_an_increment_alone_is_imported_complete(self, shaped, work, store):
        """What it builds on is not among what is copied, and is not in the store it goes to: every file is at hand, and it is written complete."""
        from chartbook import sharing

        _, complete, increments, form = shaped
        out = work / "out"
        one = increments[0].name
        commit = json.loads((increments[0] / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))["code"]["commit"]
        made_at = json.loads((increments[0] / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))["made_at"]
        done = sharing.export(FolderStore(store.root), "acme/rates", out, [f"{commit}@{made_at}"])
        assert len(done.copied) == 1 and _form(out) == [(one, False, "")] and FolderStore(out).verify() == []

    def test_store_move_stops_at_a_file_with_other_bytes_in_the_one_an_increment_builds_on(self, shaped, work, store):
        from chartbook import transfer
        from chartbook.multi_store import NamedStore, Stores
        from chartbook.store import StoreError

        _, complete, increments, form = shaped
        damaged = complete / "_data" / "treasury.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        target = work / "target"
        stores = Stores([
            NamedStore("here", str(store.root), FolderStore(store.root)),
            NamedStore("there", str(target), FolderStore(target), create=True),
        ])
        with pytest.raises(StoreError):
            transfer.move("acme/rates", stores, "there", keep=False, route=False)
        assert _form(store.root) == form  # nothing was removed from where it came from
