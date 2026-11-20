"""A folder store reads snapshots kept as increments (``docs_src/design/snapshots-and-increments.md``).

An increment is a snapshot of its pipeline like any other: its folder is
``increments/<pipeline>/<snapshot>/``, it holds the files that one complete
snapshot of the pipeline does not have, and its record says where each of
its files is, in one of the two folders. ``chartbook snapshot`` makes one
where little changed (``tests/test_snapshot_decides.py``), on a complete
snapshot older than itself; ``chartbook store migrate`` leaves them on a
newer one. Here the snapshots are made complete, and
``tests/increments.py`` keeps them in the one shape or the other.

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
    """Three snapshots of rates, each with a part more and another chart; a reader pinned to each of them. The snapshots, oldest first, and the readers.

    Each complete: ``tests/increments.py`` then keeps all but one as
    increments, in the shape a test asks for, and the shape a migrate
    leaves (the newest complete) is one that making snapshots never gives.
    """
    taken, readers = [], []
    for number, (made_at, year, text) in enumerate(((OLDER, 2020, "one"), (OLD, 2021, "two"), (OLDISH, 2022, "three"))):
        _part(rates, year)
        _chart(rates, text)
        taken.append(snapshot.make(rates, store=FolderStore(store.root), made_at=made_at, complete=True).snapshot)
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
    """Three snapshots of rates that nothing pins, each with a part more and another chart, all older than a week; oldest first. Each complete, for ``tests/increments.py`` to keep in one shape or the other (see ``three``)."""
    taken = []
    for made_at, year, text in ((OLDER, 2020, "one"), (OLD, 2021, "two"), (OLDISH, 2022, "three")):
        _part(rates, year)
        _chart(rates, text)
        taken.append(snapshot.make(rates, store=FolderStore(store.root), made_at=made_at, complete=True).snapshot)
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

    @pytest.mark.parametrize("shape", SHAPES)
    def test_what_it_says_it_frees_is_what_goes_with_each_increments_line_for_a_person(self, unpinned, store, shape):
        from chartbook.cli import _format_bytes

        complete, increments = with_increments(store.root, shape)["acme+rates"]
        plan = lock.plan_gc(FolderStore(store.root))
        going = [_folder_of(taken) for taken, _ in plan.snapshots_delete]
        assert going and all(folder in increments for folder in going) and all((folder / "_chartbook" / "INCREMENT.txt").is_file() for folder in going)
        # Every file of each folder that goes, its INCREMENT.txt among them, and not its record
        size = sum(path.stat().st_size for folder in going for path in folder.rglob("*") if path.is_file() and path.name != "snapshot.json")
        assert plan.freed_bytes == size
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.output.splitlines()[-1].endswith(f", {_format_bytes(size)}."), result.output
        assert not any(folder.exists() for folder in going)


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
            "A complete snapshot's folder holds every file of its version; an increment's holds what the one it builds on does not.",
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


class TestTheRestOfWhatReadsTheStore:
    """A pin, a check, lineage, the listing of versions and a run take an increment as the snapshot of its pipeline that it is."""

    def test_lineage_the_checks_and_the_listings(self, kept, store, monkeypatch):
        from chartbook import lineage

        complete, increments, taken, readers = kept
        for reader in readers:
            assert lineage.walk(reader, FolderStore(store.root), rehash=True).gaps() == []
            monkeypatch.chdir(reader)
            for typed in (["pin", "--check"], ["pin"], ["lineage"]):
                result = CliRunner().invoke(main, typed)
                assert result.exit_code == 0, (typed, result.output)
        listed = CliRunner().invoke(main, ["ls", "versions"])
        assert listed.exit_code == 0 and all(one.commit[:7] in listed.output for one in taken), listed.output
        assert CliRunner().invoke(main, ["store", "info"]).exit_code == 0

    def test_a_new_pin_takes_the_newest_whichever_kind_it_is(self, kept, work, store):
        complete, increments, taken, _ = kept
        reader = _reader(work / "late")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        assert lock.read_lock(reader).snapshots() == {(taken[-1].commit, taken[-1].made_at)}
        assert data.load("acme/rates:parts", project_dir=reader).collect().height == 3

    def test_a_run_with_nothing_changed_stands_on_the_newest_and_writes_nothing(self, kept, rates, store):
        complete, increments, taken, _ = kept
        before = _files(store.root)
        report = snapshot.make(rates, store=FolderStore(store.root), made_at="2026-03-01T09:15:00.000000Z")
        assert not report.made and report.snapshot.made_at == taken[-1].made_at and report.not_whole is None
        assert _files(store.root) == before  # nothing is written into a recorded snapshot of either kind

    def test_where_the_newest_lacks_a_file_a_run_makes_a_new_snapshot_that_is_whole(self, kept, rates, store):
        """Rule A, unchanged: the one with the hole is left as it is, and a new one is made, whole. Which kind it is, the rule of adding up says."""
        complete, increments, taken, _ = kept
        newest = _folder_of(taken[-1])
        newest = next(folder for folder in (complete, *increments) if folder.name == newest.name)
        _lose(newest / "_output" / "curve.html")
        report = snapshot.make(rates, store=FolderStore(store.root), made_at="2026-03-01T09:15:00.000000Z")
        assert report.made and report.not_whole[1] == ["_output/curve.html"]
        made = _folder_of(report.snapshot)
        assert not (newest / "_output" / "curve.html").exists()
        fresh = FolderStore(store.root)
        assert fresh.holes_of(report.snapshot.path) == [] and fresh.verify_snapshot(report.snapshot.path) == []
        if newest == complete:
            # The complete one is the one with the hole, and is not built on: the new one is complete, under snapshots/
            assert made.parent == store.root / "snapshots" / "acme+rates" and not fresh.builds_on(report.snapshot.path)
            assert (made / "_data" / "treasury.parquet").is_file()
        else:
            # An increment has the hole, and the complete one is whole: the new one is an increment on it, with a chart of its own
            assert made.parent == store.root / "increments" / "acme+rates" and (made / "_output" / "curve.html").is_file()
            assert fresh.builds_on(report.snapshot.path) == complete / "_chartbook" / "snapshot.json"


class TestGcOnWhatAnIncrementKeeps:
    def test_rule_b_through_the_command_with_an_increment_holed(self, unpinned, store):
        """An increment that stays and lacks a file of its own holds its pipeline back, with its folder and the file named."""
        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        middle, newest = increments
        _lose(newest / "_output" / "curve.html")
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and middle.is_dir(), result.output
        assert (
            f"Nothing of acme/rates is removed: its snapshot {newest.name} lacks _output/curve.html, and stays because it is "
            f"the newest of its pipeline."
        ) in result.output.splitlines(), result.output

    def test_the_check_by_hash_reads_a_file_two_increments_name_once_where_it_is(self, three, work, store, monkeypatch):
        """Something that goes holds a pinned table; the increments that stay keep it in the one they build on: read there, once."""
        taken, readers = three
        monkeypatch.setattr(FolderStore, "age_of", lambda self, content_hash, now=None: 2.0 * lock.RECENT_SECONDS)
        # A fourth snapshot of the same commit that nothing pins and is old: it goes, and holds the table the readers pin
        _chart(work / "rates", "four")
        snapshot.make(work / "rates", store=FolderStore(store.root), made_at="2025-11-01T09:15:00.000000Z", complete=True)  # as the three
        complete, increments = with_increments(store.root, "newest")["acme+rates"]
        opened: list = []
        real = store_module.hashing.HashCache.file_hex

        def counting(self, path, *args, **kwargs):
            opened.append(Path(path))
            return real(self, path, *args, **kwargs)

        monkeypatch.setattr(store_module.hashing.HashCache, "file_hex", counting)
        plan = lock.plan_gc(FolderStore(store.root), hashed=True)
        assert len(plan.snapshots_delete) == 1 and plan.not_intact == set()
        table = complete / "_data" / "treasury.parquet"
        assert opened.count(table) == 1 and all(path.is_relative_to(store.root) for path in opened)
        # And with other bytes there, at its size: every snapshot that keeps it there is held back with the pipeline
        opened.clear()
        os.chmod(table, stat.S_IWRITE | stat.S_IREAD)
        table.write_bytes(bytes(table.stat().st_size))
        store_module._found_whole.clear()
        plan = lock.plan_gc(FolderStore(store.root), hashed=True)
        assert plan.not_intact == {"acme/rates"} and plan.snapshots_delete == [] and opened.count(table) == 1


class TestARunThatWritesToTwoStores:
    def test_an_increment_with_a_hole_in_the_second_store_is_not_stood_on(self, unpinned, work, store):
        """The two-store rule asks an increment's holes like any other's: a new snapshot is made, whole in both, and each store keeps it as it decides."""
        import shutil

        from chartbook.multi_store import NamedStore, Stores

        there = work / "there"
        shutil.copytree(store.root, there)
        complete, increments = with_increments(there, "oldest")["acme+rates"]
        newest = increments[-1]
        _lose(newest / "_output" / "curve.html")
        both = Stores([
            NamedStore("here", str(store.root), FolderStore(store.root)),
            NamedStore("there", str(there), FolderStore(there)),
        ])
        report = snapshot.make(work / "rates", store=both, store_names=["here", "there"], made_at="2026-03-01T09:15:00.000000Z")
        assert report.made and report.not_whole[1] == ["_output/curve.html"] and str(report.not_whole[2]) == str(FolderStore(there))
        (new,) = [record for record in FolderStore(there).records() if record.made_at == "2026-03-01T09:15:00.000000Z"]
        # There it is an increment on the one complete snapshot, with a chart of its own; the one with the hole is as it was
        assert new.increment and new.builds_on == complete.name and (new.folder / "_output" / "curve.html").is_file()
        assert FolderStore(there).verify_snapshot(new.path) == [] and not (newest / "_output" / "curve.html").exists()
        assert FolderStore(store.root).verify_snapshot(report.snapshot.path) == []


class TestAPathUnderIncrementsThatIsTooLong:
    def test_the_writer_checks_it_before_anything_is_written(self, work, monkeypatch):
        """A path is one character longer under increments/ than under snapshots/ (two than under pipelines/): what fits there by one does not fit here."""
        commit, place = "a" * 40, "d/" + "f" * 40 + ".bin"
        target = FolderStore(work / "o")
        source = work / "file.bin"
        source.write_bytes(b"x")
        name = store_module.snapshot_folder_name(OLD, commit)
        under_snapshots = target.root / "snapshots" / "acme+rates" / name / place
        under_increments = target.root / "increments" / "acme+rates" / name / place
        assert len(str(under_increments)) == len(str(under_snapshots)) + 1
        # As on Windows without long paths, with the limit at that path's own length
        monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
        monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
        monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", len(str(under_increments)))
        monkeypatch.setattr(store_module, "WINDOWS_FOLDER_LIMIT", len(str(under_increments)) + 100)
        complete = target.begin("acme/rates", commit, OLD)
        complete.put(source, place=place)  # fits, by one character
        complete.discard()
        increment = target.begin("acme/rates", commit, OLD, builds_on=name)
        with pytest.raises(store_module.PathTooLongError) as refused:
            increment.put(source, place=place)
        assert "characters long, and Windows refuses a path of" in str(refused.value)
        increment.discard()
        assert not any(path.is_file() for path in (target.root / "increments").rglob("*")) if (target.root / "increments").exists() else True


class TestRestore:
    def test_a_file_and_a_dataset_in_parts_are_put_back_from_an_increments_two_folders(self, kept, rates, store, monkeypatch):
        """`chartbook restore` takes the newest snapshot that holds the asset, whichever kind it is, and reads each file where it is kept."""
        import shutil

        complete, increments, taken, _ = kept
        table = (rates / "_data" / "treasury.parquet").read_bytes()
        parts = {path.name: path.read_bytes() for path in (rates / "_data" / "parts").iterdir()}
        (rates / "_data" / "treasury.parquet").unlink()
        shutil.rmtree(rates / "_data" / "parts")
        monkeypatch.chdir(rates)
        result = CliRunner().invoke(main, ["restore", "treasury", "parts"])
        assert result.exit_code == 0, result.output
        assert (rates / "_data" / "treasury.parquet").read_bytes() == table
        assert {path.name: path.read_bytes() for path in (rates / "_data" / "parts").iterdir()} == parts


def _aged(root: Path) -> None:
    """Every file under a folder was last changed two hours ago: nothing is spared for being new."""
    then = __import__("time").time() - 7200
    for path in sorted(root.rglob("*")):
        os.utime(path, (then, then), follow_symlinks=False)


class TestAfterTheReviewOfIncrements:
    """What the sixth review found of increments (2026-11-20), each under the rule it broke."""

    def test_a_folder_an_increment_builds_on_that_is_a_link_is_not_read_from(self, unpinned, work, store):
        """The folder a file is read from is checked, whichever of the two it is: an import takes nothing through a link."""
        import shutil

        from chartbook import sharing

        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        out = work / "out"
        sharing.export(FolderStore(store.root), "acme/rates", out, None)
        real = out / "snapshots" / "acme+rates"
        shutil.move(str(real), str(work / "elsewhere"))
        real.symlink_to(work / "elsewhere", target_is_directory=True)
        done = sharing.import_snapshots(FolderStore(work / "other"), out)
        assert done.copied == [] and len(done.refused) == 3
        assert all(why == "its record, or a folder holding it or the snapshot it builds on, is a link" for _, why in done.refused), done.refused
        assert not any(p.is_file() and p.name != "store.json" and p.name != "README.txt" for p in (work / "other").rglob("*"))

    def test_a_snapshots_folder_name_is_its_own_in_its_pipeline_across_both_trees(self, work):
        target = FolderStore(work / "s")
        commit, source = "a" * 40, work / "f.bin"
        source.write_bytes(b"x")
        first = target.begin("acme/rates", commit, OLD)
        first.put(source, place="d/f.bin")
        record = first.write({"schema": "chartbook/snapshot/v2", "root": "acme/rates", "made_at": OLD, "code": {"commit": commit}, "records": []})
        name = Path(record).parent.parent.name
        second = target.begin("acme/rates", commit, OLD, builds_on=name)
        second.put(source, place="d/f.bin")
        assert second.name is not None and second.name != name  # the next free second: never the name of the one it builds on
        second.discard()
        with pytest.raises(store_module.StoreError) as refused:
            target.begin("acme/rates", commit, OLD, builds_on="not a snapshot's folder")
        assert "cannot be kept as an increment on" in str(refused.value)
        assert store_module.is_snapshot_folder(name) and not store_module.is_snapshot_folder(name + "\n")

    def test_an_increment_that_says_it_builds_on_its_own_name_is_not_followed(self, unpinned, store):
        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        record = increments[0] / "_chartbook" / "snapshot.json"
        document = json.loads(record.read_text(encoding="utf-8"))
        document["stored"] = {"builds_on": increments[0].name}
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        store_module._read_records.clear()
        fresh = FolderStore(store.root)
        (kept,) = [one for one in fresh.records() if one.folder == increments[0]]
        assert kept.builds_on == "" and fresh.holes_of(kept.path) != [] and fresh.verify() != []

    def test_an_increment_is_built_only_on_a_complete_snapshot_read_and_hashed_in_this_run(self, unpinned, work, store):
        """The target has the complete one with other bytes at the right size: it is refused, and the increments are written complete from what was sent."""
        from chartbook import sharing

        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        out, other = work / "out", work / "other"
        sharing.export(FolderStore(store.root), "acme/rates", out, [json.loads((complete / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))["code"]["commit"] + "@" + OLDER])
        sharing.import_snapshots(FolderStore(other), out)
        damaged = other / "snapshots" / "acme+rates" / complete.name / "_data" / "treasury.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        store_module._read_records.clear()
        store_module._found_whole.clear()
        whole = work / "whole"
        sharing.export(FolderStore(store.root), "acme/rates", whole, None)
        done = sharing.import_snapshots(FolderStore(other), whole)
        assert len(done.refused) == 1 and len(done.copied) == 2  # the complete one is not whole here; the two others are copied
        fresh = FolderStore(other)
        for record in fresh.records():
            if record.folder.name != complete.name:
                assert not record.increment and fresh.verify_snapshot(record.path) == []  # complete, every file its own

    def test_increments_sent_without_their_complete_one_keep_their_form_where_the_store_has_it_whole(self, unpinned, work, store):
        import shutil

        from chartbook import sharing

        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        out, other = work / "out", work / "other"
        sharing.export(FolderStore(store.root), "acme/rates", out, None)
        sharing.import_snapshots(FolderStore(other), out)
        for folder in (other / "increments" / "acme+rates").iterdir():  # the store has the complete one alone
            if folder.is_dir():
                shutil.rmtree(folder, onerror=lambda function, path, _: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), function(path)))
        shutil.rmtree(out / "snapshots", onerror=lambda function, path, _: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), function(path)))
        store_module._read_records.clear()
        done = sharing.import_snapshots(FolderStore(other), out)
        assert done.refused == [] and len(done.copied) == 2
        assert _form(other) == _form(store.root) and FolderStore(other).verify() == []
        own = sum(p.stat().st_size for folder in increments for p in folder.rglob("*") if p.is_file() and p.name not in ("snapshot.json", "INCREMENT.txt"))
        assert done.size_bytes == own  # each file counted once

    def test_gc_an_hour_on_leaves_every_increments_line_for_a_person(self, kept, store):
        complete, increments, _, _ = kept
        _aged(store.root)
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert all((folder / "_chartbook" / "INCREMENT.txt").is_file() for folder in increments)

    def test_the_same_snapshot_in_both_folders_is_left_alone_by_gc_and_the_complete_one_is_read(self, three, work, store):
        import shutil

        taken, readers = three
        shutil.copytree(store.root, work / "copy")
        complete, increments = with_increments(store.root, "oldest")["acme+rates"]
        doubled = increments[0]
        shutil.copytree(work / "copy" / "snapshots" / "acme+rates" / doubled.name, complete.parent / doubled.name)
        store_module._read_records.clear()
        before = _files(doubled)
        _aged(store.root)
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and _files(doubled) == before, result.output  # its files count as used: a person decides
        (index,) = [i for i, one in enumerate(taken) if _folder_of(one).name == doubled.name]
        assert Path(data.path("acme/rates:treasury", project_dir=readers[index])).is_relative_to(complete.parent / doubled.name)

    def test_store_ls_says_increment_of_one_none_of_whose_files_is_in_the_complete_one(self, rates, store):
        snapshot.make(rates, store=FolderStore(store.root), made_at=OLDER)
        _table(rates, 9)
        _part(rates, 2020)
        pl.DataFrame({"year": [1999], "rate": [1.0]}).write_parquet(rates / "_data" / "parts" / "2020.parquet")
        _chart(rates, "two")
        (rates / "README.md").write_text("# acme/rates, again\n", encoding="utf-8", newline="\n")
        manifest = rates / "chartbook.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n# a word more\n", encoding="utf-8", newline="\n")
        _commit(rates)
        assert snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).made
        complete, (increment,) = with_increments(store.root, "newest")["acme+rates"]
        (record,) = [one for one in FolderStore(store.root).records() if one.folder == increment]
        assert record.increment and all(file.location.is_relative_to(increment) for asset in record.assets for file in asset.files)
        result = CliRunner().invoke(main, ["store", "ls"])
        (line,) = [line for line in result.output.splitlines() if line.split()[:1] == [increment.name]]
        assert line.split()[5] == "increment", line
