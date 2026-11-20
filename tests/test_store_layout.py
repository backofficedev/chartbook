"""The store's layout on disk: ``snapshots/`` and ``_chartbook/``, every snapshot complete, and a store of ChartBook 0.5 read as it is.

``docs_src/design/snapshots-and-increments.md``: "The layout", "What the
store promises" and "Moving a store to this layout". This is the first half
of step 2 of its order of work: every snapshot is written complete, and a
store of 0.5 is not moved yet. It is read, its notes of lockfiles are
written, and nothing else is written to it or removed from it.

The pipeline is the one of the design's example: ``acme/rates``, a table, a
chart and a README. A store of 0.5 is laid out by hand
(``tests/store_of_0_5.py``).
"""

import json
import os
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, snapshot
from chartbook.cli import _format_bytes, main
from chartbook.store import EarlierLayoutError, FolderStore, StoreError
from tests.fixtures import _git
from tests.store_of_0_5 import cleared_as_0_5, laid_out_as_0_5

FIRST, SECOND = "2026-11-16T09:15:00.000000Z", "2026-11-19T14:02:00.000000Z"

posix = pytest.mark.skipif(os.name == "nt", reason="the build script here is POSIX shell")


def refusal(store) -> str:
    """What a store of 0.5 says when it is asked to take or to let go of anything: the words of the design, exactly."""
    return (
        f"The store at {store} has the layout of ChartBook 0.5, which this ChartBook reads and does not write. "
        f"`chartbook store migrate` moves it to this version's; an earlier ChartBook will not read it afterwards."
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
    """``acme/rates`` in a repository of its own, built and committed: a table and a chart that git ignores, a README it tracks."""
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


def _tree(root: Path) -> list:
    """Every file under a folder, by its path in it, sorted."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _folders(root: Path) -> list:
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _folder_of(taken) -> Path:
    return Path(taken.path).parent.parent


def _entries(taken) -> list:
    """Every file a snapshot's record says where it keeps, as the record's own entries."""
    document = json.loads(Path(taken.path).read_text(encoding="utf-8"))
    parts = [*document["records"], document["index"], document["documents"]]
    return [entry for part in parts for entry in part["stored"]["files"]]


class TestTheTreeOfANewStore:
    def test_every_path_of_the_designs_example(self, rates, store):
        taken = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        commit = _git(rates, "rev-parse", "HEAD")
        made = f"snapshots/acme+rates/2026-11-16T091500Z_{commit[:12]}"
        assert _folder_of(taken) == store.root / made
        assert _tree(store.root) == sorted([
            "README.txt",
            "store.json",
            f"_chartbook/origins/{commit}/_top.txt",
            "snapshots/acme+rates/README.txt",
            f"{made}/_data/treasury.parquet",
            f"{made}/_output/curve.html",
            f"{made}/README.md",
            f"{made}/chartbook.toml",
            f"{made}/_chartbook/index.json",
            f"{made}/_chartbook/snapshot.json",
        ])
        # Two names at the top for a person, the marker, and one folder of ChartBook's own: nothing else, and no increments/
        assert sorted(p.name for p in store.root.iterdir()) == ["README.txt", "_chartbook", "snapshots", "store.json"]
        assert _folders(store.root / "_chartbook") == ["origins", "tmp"]
        assert list((store.root / "_chartbook" / "tmp").iterdir()) == []
        assert json.loads((store.root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}
        assert store.layout() == "chartbook/store/v3"

    def test_the_notes_of_lockfiles_and_an_object_no_pipeline_owns_are_under_chartbooks_own_folder(self, rates, reader, store, work):
        snapshot.make(rates, store=store, made_at=FIRST)
        assert lock.pin(reader, store).problems == []
        (note,) = (store.root / "_chartbook" / "roots").iterdir()
        assert json.loads(note.read_text(encoding="utf-8"))["lockfile"] == str(reader / "chartbook.lock")
        (work / "stray.bin").write_bytes(b"stray")
        put = store.put(work / "stray.bin")
        digest = put.content_hash.split(":", 1)[1]
        assert put.path == store.root / "_chartbook" / "unowned" / digest
        assert (put.path / "stray.bin").read_bytes() == b"stray"
        assert _folders(store.root) == ["_chartbook", "snapshots"]
        assert _folders(store.root / "_chartbook") == ["origins", "roots", "tmp", "unowned"]
        assert _folders(store.root / "snapshots") == ["acme+rates"]

    def test_the_readme_at_the_top_says_what_the_two_folders_are_and_is_written_once(self, rates, store):
        snapshot.make(rates, store=store, made_at=FIRST)
        note = store.root / "README.txt"
        text = note.read_text(encoding="utf-8")
        assert text.splitlines()[0] == (
            "This folder is a ChartBook store: the snapshots of pipelines, kept for other pipelines to read."
        )
        assert "\nsnapshots/   One folder for each pipeline" in text and "\n_chartbook/  ChartBook's own notes." in text
        assert text.splitlines()[-1] == "Remove a snapshot with `chartbook store gc`, not by hand."
        assert "increment" not in text
        note.write_text(text + "A note of my own.\n", encoding="utf-8", newline="\n")
        _table(rates, 4)
        snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND)
        assert note.read_text(encoding="utf-8").endswith("A note of my own.\n")  # nothing in the store is rewritten

    def test_the_readme_of_a_pipelines_folder_says_each_folder_is_complete(self, rates, store):
        snapshot.make(rates, store=store, made_at=FIRST)
        text = (store.root / "snapshots" / "acme+rates" / "README.txt").read_text(encoding="utf-8")
        assert "Each folder here is one complete snapshot" in text
        assert "A snapshot's folder can be read or copied as it is." in text
        assert text.splitlines()[-1] == "Remove one with `chartbook store gc`, not by hand: gc keeps what a lockfile pins."
        assert "shared" not in text and "standalone" not in text and "increment" not in text


class TestEverySnapshotIsComplete:
    def test_every_file_of_it_is_in_its_own_folder(self, rates, store):
        taken = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        folder = _folder_of(taken)
        entries = _entries(taken)
        assert sorted(entry["path"] for entry in entries) == [
            "README.md", "_chartbook/index.json", "_data/treasury.parquet", "_output/curve.html", "chartbook.toml",
        ]
        for entry in entries:
            assert entry["kept_in"] == folder.name and "kept_as" not in entry
            assert folder.joinpath(*entry["path"].split("/")).stat().st_size == entry["size_bytes"]
        assert json.loads(Path(taken.path).read_text(encoding="utf-8"))["schema"] == "chartbook/snapshot/v2"
        for content_hash in taken.hashes():
            kept = store.files(content_hash)
            assert kept.in_place() and all(file.location.is_relative_to(folder) for file in kept.files)
        assert store.verify() == []

    def test_a_second_snapshot_repeats_the_file_that_did_not_change(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        _chart(rates, "the curve on the 19th")  # the chart is drawn again, and the table is the same file
        second = snapshot.make(rates, store=store, made_at=SECOND).snapshot
        assert second.path != first.path and second.content()["treasury"] == first.content()["treasury"]
        table = Path("_data") / "treasury.parquet"
        assert (_folder_of(second) / table).read_bytes() == (_folder_of(first) / table).read_bytes() == (rates / table).read_bytes()
        assert sorted(p.relative_to(_folder_of(second)).as_posix() for p in _folder_of(second).rglob("*") if p.is_file()) == [
            "README.md", "_chartbook/index.json", "_chartbook/snapshot.json", "_data/treasury.parquet",
            "_output/curve.html", "chartbook.toml",
        ]
        assert {entry["kept_in"] for entry in _entries(second)} == {_folder_of(second).name}
        assert not any("kept_as" in entry for entry in _entries(second))
        # Each has its own copy, whole in one folder, and a read is handed the copy of the snapshot it
        # names: the newest's where it names none
        asset = second.content()["treasury"]
        assert store.files(asset, "acme/rates", name="treasury.parquet").one.location == _folder_of(second) / table
        for taken in (first, second):
            kept = store.files(asset, "acme/rates", name="treasury.parquet", snapshot=(taken.commit, taken.made_at))
            assert kept.one.location == _folder_of(taken) / table
        assert store.verify() == []
        assert not (store.root / "_chartbook" / "tmp").exists() or list((store.root / "_chartbook" / "tmp").iterdir()) == []

    def test_two_files_of_one_snapshot_with_the_same_bytes_are_both_written(self, work, store):
        folder = work / "twins"
        (folder / "_data").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/twins"},
                "dataframes": {
                    "one": {"path": "./_data/one.csv", "docs": "d"},
                    "two": {"path": "./_data/two.csv", "docs": "d"},
                },
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_data/\n", encoding="utf-8", newline="\n")
        for name in ("one.csv", "two.csv"):
            (folder / "_data" / name).write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
        taken = snapshot.make(folder, store=store, made_at=FIRST).snapshot
        assert taken.content()["one"] == taken.content()["two"]
        kept = _folder_of(taken) / "_data"
        assert (kept / "one.csv").read_bytes() == (kept / "two.csv").read_bytes() == b"a,b\n1,2\n"
        by_path = {entry["path"]: entry for entry in _entries(taken)}
        assert by_path["_data/one.csv"]["kept_in"] == by_path["_data/two.csv"]["kept_in"] == _folder_of(taken).name
        assert "kept_as" not in by_path["_data/one.csv"] and "kept_as" not in by_path["_data/two.csv"]
        # Each is read under its own name, from its own file
        assert store.files(taken.content()["two"], "acme/twins", name="two.csv").one.location == kept / "two.csv"
        assert store.files(taken.content()["one"], "acme/twins", name="one.csv").one.location == kept / "one.csv"

    def test_the_same_files_again_make_no_second_snapshot_and_copy_nothing(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=FIRST)
        again = snapshot.make(rates, store=store, made_at=SECOND)
        assert first.made and not again.made and again.snapshot.path == first.snapshot.path
        assert _folders(store.root / "snapshots" / "acme+rates") == [_folder_of(first.snapshot).name]

    def test_one_a_pin_makes_is_complete_too(self, work, store):
        """A snapshot a pin makes from a clone holds a file its owner's snapshot has, and one it has not: both are in its own folder."""
        source = work / "clone"
        (source / "_data").mkdir(parents=True)
        (source / "_data" / "old.csv").write_bytes(b"old")
        (source / "_data" / "new.csv").write_bytes(b"new")
        owners = store.begin("acme/rates", "a" * 40, FIRST, base=source)
        old = owners.put(source / "_data" / "old.csv")
        owners.write(_record(owners, "a" * 40, old=old))
        pinned = store.begin("acme/rates", "b" * 40, SECOND, base=source, made_by="pin")
        again, new = pinned.put(source / "_data" / "old.csv"), pinned.put(source / "_data" / "new.csv")
        assert pinned.placed  # the store lacked one of them
        record = pinned.write(_record(pinned, "b" * 40, old=again, new=new))
        folder = Path(record).parent.parent
        assert json.loads(Path(record).read_text(encoding="utf-8"))["made_by"] == "pin"
        assert (folder / "_data" / "old.csv").read_bytes() == b"old" and (folder / "_data" / "new.csv").read_bytes() == b"new"
        assert [entry["kept_in"] for put in (again, new) for entry in put.stored["files"]] == [folder.name, folder.name]
        assert store.pinned_snapshot_files() == [Path(record)] and store.verify() == []

    def test_a_file_an_earlier_snapshot_has_is_copied_when_the_record_is_written_and_not_before(self, work, store):
        source = work / "pipeline"
        (source / "_data").mkdir(parents=True)
        (source / "_data" / "rates.csv").write_bytes(b"rates-1")
        first = store.begin("acme/rates", "a" * 40, FIRST, base=source)
        first.write(_record(first, "a" * 40, rates=first.put(source / "_data" / "rates.csv")))
        second = store.begin("acme/rates", "b" * 40, SECOND, base=source)
        put = second.put(source / "_data" / "rates.csv")
        own = store.pipeline_path("acme/rates") / second.name / "_data" / "rates.csv"
        assert not second.placed and not own.exists()  # the store has these bytes: nothing is copied yet
        assert put.stored["files"][0]["kept_in"] == second.name
        second.write(_record(second, "b" * 40, rates=put))
        assert own.read_bytes() == b"rates-1"

    def test_one_not_written_after_all_leaves_no_folder(self, work, store):
        source = work / "pipeline"
        (source / "_data").mkdir(parents=True)
        (source / "_data" / "rates.csv").write_bytes(b"rates-1")
        first = store.begin("acme/rates", "a" * 40, FIRST, base=source)
        first.write(_record(first, "a" * 40, rates=first.put(source / "_data" / "rates.csv")))
        second = store.begin("acme/rates", "b" * 40, SECOND, base=source)
        second.put(source / "_data" / "rates.csv")
        second.discard()
        assert _folders(store.pipeline_path("acme/rates")) == [first.name]
        assert list((store.root / "_chartbook" / "tmp").iterdir()) == []

    def test_the_copy_is_taken_from_the_pipeline_when_the_earlier_snapshots_file_has_gone(self, work, store):
        source = work / "pipeline"
        (source / "_data").mkdir(parents=True)
        (source / "_data" / "rates.csv").write_bytes(b"rates-1")
        first = store.begin("acme/rates", "a" * 40, FIRST, base=source)
        first.write(_record(first, "a" * 40, rates=first.put(source / "_data" / "rates.csv")))
        theirs = store.pipeline_path("acme/rates") / first.name / "_data" / "rates.csv"
        second = store.begin("acme/rates", "b" * 40, SECOND, base=source)
        put = second.put(source / "_data" / "rates.csv")
        theirs.chmod(0o644)
        theirs.unlink()  # gone between the put and the record: removed by hand, or by a gc elsewhere
        second.write(_record(second, "b" * 40, rates=put))
        assert (store.pipeline_path("acme/rates") / second.name / "_data" / "rates.csv").read_bytes() == b"rates-1"
        # And where the pipeline's own file has gone as well, the snapshot is not written
        third = store.begin("acme/rates", "c" * 40, "2026-11-20T00:00:00.000000Z", base=source)
        put = third.put(source / "_data" / "rates.csv")
        mine = store.pipeline_path("acme/rates") / second.name / "_data" / "rates.csv"
        mine.chmod(0o644)
        mine.unlink()
        (source / "_data" / "rates.csv").unlink()
        with pytest.raises(StoreError, match="went from the store.*Make the snapshot again"):
            third.write(_record(third, "c" * 40, rates=put))
        third.discard()
        assert sorted(_folders(store.pipeline_path("acme/rates"))) == sorted([first.name, second.name])


class TestThePathOfAPinnedFile:
    """A read through a pin is handed the pinned snapshot's own copy: `chartbook path` says that copy stays as it is until `chartbook pin --update`."""

    def test_it_stays_where_it_is_while_neither_the_pin_nor_the_bytes_move(self, rates, reader, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, store).problems == []
        before = data.path("acme/rates:treasury", project_dir=reader)
        assert before == _folder_of(first) / "_data" / "treasury.parquet"
        _chart(rates, "the chart alone is drawn again")  # the table's bytes do not change, and the reader does not pin again
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND).snapshot
        assert second.path != first.path and (_folder_of(second) / "_data" / "treasury.parquet").is_file()
        assert data.path("acme/rates:treasury", project_dir=reader) == before
        result = CliRunner().invoke(main, ["path", "acme/rates:treasury", "--project-dir", str(reader)])
        assert result.exit_code == 0 and result.output.splitlines() == [str(before)]

    def test_another_snapshots_copy_is_read_where_the_pinned_one_has_lost_its_own(self, rates, reader, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, store).problems == []
        _chart(rates, "the chart alone is drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND).snapshot
        own = _folder_of(first) / "_data" / "treasury.parquet"
        own.chmod(0o644)
        own.unlink()
        assert data.path("acme/rates:treasury", project_dir=reader) == _folder_of(second) / "_data" / "treasury.parquet"
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)

    def test_a_store_of_0_5_has_one_place_for_it_whichever_snapshot_is_named(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        _chart(rates, "the chart alone is drawn again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND).snapshot
        old = laid_out_as_0_5(store.root)
        asset = second.content()["treasury"]
        kept = old.root / "pipelines" / "acme+rates" / _folder_of(first).name / "_data" / "treasury.parquet"
        for taken in (first, second):
            found = old.files(asset, "acme/rates", name="treasury.parquet", snapshot=(taken.commit, taken.made_at))
            assert found.one.location == kept


def _record(pending, commit: str, **stored) -> dict:
    """A record of what was put in a snapshot being written, as a store reads one."""
    return {
        "schema": "chartbook/snapshot/v2",
        "root": "acme/rates",
        "code": {"commit": commit},
        "made_at": pending.made_at,
        "records": [
            {"id": f"acme/rates:{name}", "content_hash": put.content_hash, "size_bytes": put.size_bytes, "stored": put.stored}
            for name, put in sorted(stored.items())
        ],
    }


class TestRemovingASnapshot:
    @pytest.fixture
    def two(self, rates, store):
        """Two snapshots of ``acme/rates``: the first old enough to go, the second the newest, with the same table."""
        first = snapshot.make(rates, store=store, made_at="2026-01-01T00:00:00.000000Z").snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=store).snapshot
        return first, second

    def test_gc_removes_its_whole_folder(self, two, store):
        first, second = two
        gone = _folder_of(first)
        own = sum(p.stat().st_size for p in gone.rglob("*") if p.is_file() and p.name != "snapshot.json")
        only_its = (first.hashes() - second.hashes())
        plan = lock.plan_gc(store)
        assert [taken for taken, _ in plan.snapshots_delete] == [first]
        # What only it holds goes with it, new as its files are; and its own copy of the table the second has too
        assert {content_hash for content_hash, _ in plan.delete} == only_its and plan.recent == []
        assert plan.freed_bytes == own and plan.copies_bytes > 0
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == f"Removed 1 snapshot(s) and {len(only_its)} object(s), {_format_bytes(own)}."
        assert not gone.exists()
        assert _folders(store.root / "snapshots" / "acme+rates") == [_folder_of(second).name]
        assert not list(store.root.rglob("CLEARED.txt"))
        assert FolderStore(store.root).verify() == [] and snapshot.all_snapshots(FolderStore(store.root)) == [second]

    def test_the_reminder_says_what_its_folder_holds(self, two, store):
        first, second = two
        own = sum(p.stat().st_size for p in _folder_of(first).rglob("*") if p.is_file() and p.name != "snapshot.json")
        result = CliRunner().invoke(main, ["store", "info"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == (
            f"`chartbook store gc` would clear 1 snapshot(s), freeing {_format_bytes(own)}: "
            f"older than 7 days, and neither pinned nor the newest of their pipeline."
        )

    def test_a_removal_cut_short_is_finished_by_the_next_gc(self, two, store):
        first, second = two
        assert store.remove_snapshot(first.path) is True  # and then nothing: the command was stopped
        left = _folder_of(first)
        assert (left / "_chartbook" / "CLEARED.txt").read_text(encoding="utf-8").splitlines()[1:] == [
            "This folder is no snapshot any more. `chartbook store gc` removes what is left of it once no",
            "snapshot uses a file in it: one being made, or one whose _chartbook/snapshot.json names it.",
        ]
        assert (left / "_data" / "treasury.parquet").is_file()
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert not left.exists() and (_folder_of(second) / "_data" / "treasury.parquet").is_file()

    def test_the_last_one_of_a_pipeline_leaves_nothing_in_the_pipelines_folder(self, rates, store):
        """Its folder goes whole, and the README with it. The pipeline's own folder, empty, goes an hour on: one made just now may be a snapshot's about to be written."""
        taken = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        assert store.remove_snapshot(taken.path) is True
        store.tidy_pipeline("acme/rates")
        assert list((store.root / "snapshots" / "acme+rates").iterdir()) == []

    def test_a_move_to_another_store_leaves_no_folder_behind(self, rates, work, monkeypatch):
        from chartbook.multi_store import Stores
        from chartbook.transfer import move

        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        here, there = FolderStore(work / "here"), FolderStore(work / "there")
        there.root.mkdir()  # a store named in a catalog is there before anything is moved into it
        first = snapshot.make(rates, store=here, made_at=FIRST).snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=here, made_at=SECOND).snapshot
        catalog = work / "catalog.toml"
        catalog.write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {"here": {"url": str(here.root)}, "there": {"url": str(there.root)}}}),
            encoding="utf-8", newline="\n",
        )
        count, _ = move("acme/rates", Stores.configured(catalog), "there")
        assert count == 2
        # No file of the pipeline is left where it came from, and no folder of a snapshot
        assert _tree(here.root / "snapshots") == [] and list((here.root / "snapshots" / "acme+rates").iterdir()) == []
        moved = FolderStore(there.root)
        assert sorted((t.commit, t.made_at) for t in snapshot.all_snapshots(moved)) == [(first.commit, FIRST), (second.commit, SECOND)]
        for folder in (there.root / "snapshots" / "acme+rates").iterdir():
            if folder.is_dir():  # each complete where it went, as it was where it came from
                assert (folder / "_data" / "treasury.parquet").is_file() and (folder / "_output" / "curve.html").is_file()
        assert moved.verify() == [] and json.loads((there.root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}


class TestStoreLs:
    def test_every_snapshot_is_listed_as_complete(self, rates, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        _chart(rates, "the curve on the 19th")
        second = snapshot.make(rates, store=store, made_at=SECOND).snapshot
        result = CliRunner().invoke(main, ["store", "ls", "acme/rates"])
        assert result.exit_code == 0, result.output

        def line(taken, made: str) -> str:
            folder = _folder_of(taken)
            own = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and p.name != "snapshot.json")
            return f"  {folder.name}  {made}  {taken.commit[:7]}  complete   {_format_bytes(own)} here"

        assert result.output.splitlines() == [
            "acme/rates (2 snapshot(s))",
            line(first, "2026-11-16 09:15 UTC"),
            line(second, "2026-11-19 14:02 UTC"),
            "A complete snapshot's folder holds every file of its version, and can be read or copied as it is. "
            "Remove snapshots with `chartbook store gc`, never by hand.",
        ]


class TestExportAndImport:
    def test_an_export_is_laid_out_as_a_store_and_is_taken_in_by_another(self, rates, store, work, monkeypatch):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        _chart(rates, "the curve on the 19th")
        second = snapshot.make(rates, store=store, made_at=SECOND).snapshot
        out = work / "for-alice"
        result = CliRunner().invoke(main, ["store", "export", "acme/rates", "--to", str(out)])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == f"Send {out / 'snapshots'}; `chartbook store import` there takes it in."
        assert sorted(p.name for p in out.iterdir()) == ["README.txt", "_chartbook", "snapshots", "store.json"]
        assert json.loads((out / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}
        exported = out / "snapshots" / "acme+rates"
        assert _folders(exported) == [_folder_of(first).name, _folder_of(second).name]
        for name in _folders(exported):  # each complete: the table is in both
            assert (exported / name / "_data" / "treasury.parquet").is_file()
        # Taken in whole, from the export, from the store it is laid out as, or from the pipeline's folder alone
        for number, source in enumerate((out, out / "snapshots", exported)):
            theirs = work / f"theirs-{number}"
            monkeypatch.setenv(config.STORE_ENV_VAR, str(theirs))
            result = CliRunner().invoke(main, ["store", "import", str(source)])
            assert result.exit_code == 0, result.output
            assert "Imported 2 snapshot(s)" in result.output
            taken = FolderStore(theirs)
            assert _folders(theirs / "snapshots" / "acme+rates") == _folders(exported)
            assert taken.verify() == [] and len(snapshot.all_snapshots(taken)) == 2
            for name in _folders(exported):
                assert (theirs / "snapshots" / "acme+rates" / name / "_data" / "treasury.parquet").is_file()

    def test_the_latest_alone(self, rates, store, work):
        snapshot.make(rates, store=store, made_at=FIRST)
        _chart(rates, "the curve on the 19th")
        second = snapshot.make(rates, store=store, made_at=SECOND).snapshot
        out = work / "latest"
        result = CliRunner().invoke(main, ["store", "export", "acme/rates", "--latest", "--to", str(out)])
        assert result.exit_code == 0, result.output
        assert _folders(out / "snapshots" / "acme+rates") == [_folder_of(second).name]
        assert (out / "snapshots" / "acme+rates" / _folder_of(second).name / "_data" / "treasury.parquet").is_file()


@pytest.fixture
def of_0_5(rates, store):
    """A store as ChartBook 0.5 left it, with ``acme/rates`` in it: one snapshot cleared, whose folder keeps the table for the one after it.

    The first snapshot was cleared by 0.5's ``store gc``; the second is
    shared, its table and its documents kept in the first one's folder.

    :returns: The store, opened again; the second snapshot; and the first one's folder.
    """
    first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
    _chart(rates, "the curve on the 19th")
    snapshot.make(rates, store=store, made_at=SECOND)
    old = laid_out_as_0_5(store.root)
    cleared = cleared_as_0_5(old.root / "pipelines" / "acme+rates" / _folder_of(first).name / "_chartbook" / "snapshot.json")
    (second,) = snapshot.all_snapshots(old)
    return old, second, cleared


class TestAStoreOf05IsReadAsItIs:
    def test_what_the_helper_laid_out_is_a_store_of_0_5(self, of_0_5):
        old, second, cleared = of_0_5
        folder = _folder_of(second)
        assert sorted(p.name for p in old.root.iterdir()) == ["origins", "pipelines", "store.json", "tmp"]
        assert json.loads((old.root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v2"}
        # The cleared folder keeps what the second snapshot uses, and the second holds only what was new
        assert sorted(p.relative_to(cleared).as_posix() for p in cleared.rglob("*") if p.is_file()) == [
            "README.md", "_chartbook/CLEARED.txt", "_data/treasury.parquet", "chartbook.toml",
        ]
        assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
            "_chartbook/index.json", "_chartbook/snapshot.json", "_output/curve.html",
        ]
        by_path = {entry["path"]: entry for entry in _entries(second)}
        assert by_path["_data/treasury.parquet"]["kept_in"] == cleared.name
        assert by_path["_output/curve.html"]["kept_in"] == folder.name

    def test_of_two_files_of_one_snapshot_with_the_same_bytes_the_helper_keeps_the_first_one_put(self, work, store):
        """As 0.5 did: a dataframe is put before a chart, though a record lists the chart first."""
        folder = work / "twins"
        (folder / "_data").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/twins"},
                "dataframes": {"zeta": {"path": "./_data/zeta.csv", "docs": "d"}},
                "charts": {"alpha": {"path": "./_data/alpha.html", "dataframe": "zeta", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_data/\n", encoding="utf-8", newline="\n")
        for name in ("zeta.csv", "alpha.html"):
            (folder / "_data" / name).write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
        taken = snapshot.make(folder, store=store, made_at=FIRST).snapshot
        document = json.loads(Path(taken.path).read_text(encoding="utf-8"))
        assert [record["id"] for record in document["records"]] == ["acme/twins:chart/alpha", "acme/twins:zeta"]
        old = laid_out_as_0_5(store.root)
        (taken,) = snapshot.all_snapshots(old)
        kept = _folder_of(taken) / "_data"
        assert (kept / "zeta.csv").is_file() and not (kept / "alpha.html").exists()
        by_path = {entry["path"]: entry for entry in _entries(taken)}
        assert "kept_as" not in by_path["_data/zeta.csv"]
        assert by_path["_data/alpha.html"]["kept_as"] == "_data/zeta.csv" and by_path["_data/alpha.html"]["kept_in"] == _folder_of(taken).name
        # And each is read under its own name, from the one file
        for name in ("zeta.csv", "alpha.html"):
            found = old.files(by_path[f"_data/{name}"]["content_hash"], "acme/twins", name=name)
            assert found.one.location == kept / "zeta.csv" and found.one.relative == name
        assert old.verify() == []

    def test_its_snapshots_and_their_files_are_read_where_it_keeps_them(self, of_0_5):
        old, second, cleared = of_0_5
        assert old.layout() == "chartbook/store/v2" and old.earlier_layout()
        (record,) = old.records()
        assert record.readable and record.path == second.path and record.pipeline == "acme/rates"
        table = second.content()["treasury"]
        assert old.has(table) and old.incomplete(table, None) is None
        kept = old.files(table, "acme/rates", name="treasury.parquet")
        assert kept.one.location == cleared / "_data" / "treasury.parquet"
        assert pl.read_parquet(kept.one.location).shape == (3, 2)
        documents = old.files(second.documents["content_hash"], "acme/rates")
        assert {file.relative: file.location.parent for file in documents.files} == {"README.md": cleared, "chartbook.toml": cleared}
        assert not documents.in_place()
        assert old.files_of(table) == [(f"pipelines/acme+rates/{cleared.name}/_data/treasury.parquet", kept.one.size_bytes)]
        assert old.verify() == [] and set(old.hashes()) == second.hashes()
        assert old.origins(second.commit, "_top") != []

    def test_store_ls_lists_it_in_its_own_words(self, of_0_5):
        old, second, cleared = of_0_5
        folder = _folder_of(second)
        own = (folder / "_chartbook" / "index.json").stat().st_size + (folder / "_output" / "curve.html").stat().st_size
        result = CliRunner().invoke(main, ["store", "ls"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/rates (1 snapshot(s))",
            f"  {folder.name}  2026-11-19 14:02 UTC  {second.commit[:7]}  shared     {_format_bytes(own)} here, 3 file(s) in other folders",
            "A shared snapshot's folder holds only what changed; the rest of its files are in other snapshots' folders, "
            "which `chartbook store gc` keeps while a snapshot uses them. Remove snapshots with gc, never by hand.",
        ]

    def test_store_info_and_store_verify_read_it(self, of_0_5):
        old, second, cleared = of_0_5
        info = CliRunner().invoke(main, ["store", "info"])
        assert info.exit_code == 0, info.output
        assert info.output.splitlines()[0] == f"Store: {old}" and "store gc" not in info.output  # nothing is removed from it
        verify = CliRunner().invoke(main, ["store", "verify"])
        assert verify.exit_code == 0, verify.output
        assert verify.output.splitlines() == [f"{old}: OK ({len(second.hashes())} object(s))"]

    def test_a_pipeline_pins_from_it_and_reads_through_the_pin(self, of_0_5, reader):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        report = lock.pin(reader, old)
        assert report.problems == [] and report.written
        # Its note is where 0.5 keeps the notes of lockfiles, and in 0.5's form
        (note,) = (old.root / "roots").iterdir()
        noted = json.loads(note.read_text(encoding="utf-8"))
        assert noted["lockfile"] == str(reader / "chartbook.lock") and noted["hashes"] == [second.content()["treasury"]]
        assert noted["snapshots"] == [{"commit": second.commit, "made_at": SECOND}]
        assert [root.lockfile for root in FolderStore(old.root).roots()] == [reader / "chartbook.lock"]
        frame = data.load("acme/rates:treasury", project_dir=reader).collect()
        assert frame.shape == (3, 2)
        assert data.path("acme/rates:treasury", project_dir=reader) == cleared / "_data" / "treasury.parquet"
        assert lock.verify(reader, FolderStore(old.root)).problems == []
        # Nothing but the note was written, and nothing of this version's layout was made
        assert _tree(old.root) == sorted([*before, f"roots/{note.name}"])
        assert not (old.root / "snapshots").exists() and not (old.root / "_chartbook").exists()
        assert not (old.root / "README.txt").exists()

    def test_a_catalog_lists_its_snapshots(self, of_0_5):
        old, second, cleared = of_0_5
        found, unreadable = snapshot.readable_snapshots(FolderStore(old.root))
        assert found == [second] and unreadable == []
        result = CliRunner().invoke(main, ["ls", "versions"])
        assert result.exit_code == 0, result.output
        assert f"acme/rates {second.commit[:12]} {SECOND} default" in result.output.splitlines()

    def test_it_is_exported_from_and_taken_in_complete(self, of_0_5, work, monkeypatch):
        """What 0.5 kept once is written whole where it goes: an export of it, and a store of this version that takes its folder in."""
        old, second, cleared = of_0_5
        out = work / "out"
        result = CliRunner().invoke(main, ["store", "export", "acme/rates", "--to", str(out)])
        assert result.exit_code == 0, result.output
        exported = out / "snapshots" / "acme+rates" / _folder_of(second).name
        assert (exported / "_data" / "treasury.parquet").is_file() and (exported / "README.md").is_file()
        mine = work / "mine"
        monkeypatch.setenv(config.STORE_ENV_VAR, str(mine))
        result = CliRunner().invoke(main, ["store", "import", str(old.root / "pipelines" / "acme+rates")])
        assert result.exit_code == 0, result.output
        taken = mine / "snapshots" / "acme+rates" / _folder_of(second).name
        assert (taken / "_data" / "treasury.parquet").is_file() and FolderStore(mine).verify() == []
        assert json.loads((mine / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}


class TestAStoreOf05IsNotWritten:
    """Each thing this ChartBook does not do in a store of 0.5, with the words it says."""

    def test_no_snapshot_is_made_in_it_and_no_object_put(self, of_0_5, work):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        (work / "new.bin").write_bytes(b"new")
        with pytest.raises(EarlierLayoutError) as begun:
            old.begin("acme/rates", "c" * 40, "2026-11-20T00:00:00.000000Z", base=work)
        assert str(begun.value) == refusal(old) and begun.value.store == str(old)
        with pytest.raises(EarlierLayoutError) as put:
            old.put(work / "new.bin")
        assert str(put.value) == refusal(old)
        with pytest.raises(EarlierLayoutError) as written:
            old.write_snapshot("c" * 40, "_top", "x", {"root": "acme/rates", "made_at": "2026-11-20T00:00:00.000000Z"})
        assert str(written.value) == refusal(old)
        assert _tree(old.root) == before

    def test_no_folder_a_snapshot_was_made_from_is_noted_in_it(self, of_0_5):
        """The note of origins is a snapshot's, and no snapshot is made here: nothing is written under origins/."""
        old, second, cleared = of_0_5
        before = _tree(old.root)
        with pytest.raises(EarlierLayoutError) as noted:
            old.note_origin("c" * 40, "_top", "/somewhere/else")
        assert str(noted.value) == refusal(old)
        with pytest.raises(EarlierLayoutError):
            old.note_origin(second.commit, "_top", "/somewhere/else")  # nor added to a note that is there
        assert _tree(old.root) == before and old.origins("c" * 40, "_top") == []

    def test_a_git_dependency_pinned_into_it_is_refused_whole(self, work, store):
        """A pin from a repository puts the dependency's files in the store: in a store of 0.5 it writes no lockfile and no file."""
        from chartbook.gitcache import GitCache

        upstream = work / "upstream"
        (upstream / "data").mkdir(parents=True)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "upstream"}, "dataframes": {"committed": {"path": "./data/committed.parquet", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        (upstream / "data" / "committed.parquet").write_bytes(b"hello")
        _git(upstream, "init", "--quiet", "-b", "main")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "--quiet", "-m", "One")
        downstream = work / "downstream"
        downstream.mkdir()
        (downstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "downstream"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
            encoding="utf-8", newline="\n",
        )
        store.root.mkdir()
        (store.root / "pipelines").mkdir()
        (store.root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        before = _tree(store.root)
        with pytest.raises(EarlierLayoutError) as refused:
            lock.pin(downstream, FolderStore(store.root), git_cache=GitCache(work / "gitcache"))
        assert str(refused.value) == refusal(store)
        assert _tree(store.root) == before and not (downstream / "chartbook.lock").exists()

    def test_nothing_is_removed_from_it(self, of_0_5):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        table = second.content()["treasury"]
        for remove in (
            lambda: old.remove_snapshot(second.path),
            lambda: old.delete(table),
            lambda: old.delete_unowned(table),
            lambda: old.tidy(),
            lambda: old.tidy(dry_run=True),
            lambda: old.tidy_pipeline("acme/rates"),
            lambda: old.sweep(old.pipeline_path("acme/rates")),
            lambda: lock.plan_gc(old),
        ):
            with pytest.raises(EarlierLayoutError) as refused:
                remove()
            assert str(refused.value) == refusal(old)
        assert _tree(old.root) == before and (cleared / "_chartbook" / "CLEARED.txt").is_file()

    def test_store_gc_stops_with_those_words(self, of_0_5):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        for arguments in (["store", "gc", "--yes"], ["store", "gc", "--dry-run"], ["store", "gc", "--yes", "--keep-days", "0"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 1
            assert result.output.splitlines() == [f"Error: {refusal(old)}", "Nothing was removed."]
        assert _tree(old.root) == before

    def test_chartbook_snapshot_stops_with_those_words(self, of_0_5, rates):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        _chart(rates, "the curve on the 20th")
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates)])
        assert result.exit_code == 1
        assert result.output.splitlines() == [f"Error: {refusal(old)}"]
        assert _tree(old.root) == before

    def test_a_snapshot_a_catalog_sends_to_it_and_to_another_store_is_written_to_neither(self, of_0_5, rates, work, monkeypatch):
        """Found out before the first store is written: no snapshot is left in one store and missing from the other."""
        old, second, cleared = of_0_5
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        new = work / "new"
        new.mkdir()
        home = config.get_global_config_dir()
        home.mkdir(parents=True, exist_ok=True)
        (home / "catalog.toml").write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {
                "new": {"url": str(new), "pipelines": ["acme/rates"]},
                "old": {"url": str(old.root), "pipelines": ["acme/rates"]},
            }}),
            encoding="utf-8", newline="\n",
        )
        _chart(rates, "the curve on the 22nd")
        before = _tree(old.root)
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates)])
        assert result.exit_code == 1
        assert result.output.splitlines() == [f"Error: {refusal(old)}"]
        assert _tree(old.root) == before and list(new.iterdir()) == []

    def test_nothing_moves_out_of_it_or_into_it(self, of_0_5, rates, work, monkeypatch):
        from chartbook.multi_store import Stores
        from chartbook.transfer import move

        old, second, cleared = of_0_5
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        new = FolderStore(work / "new")
        new.root.mkdir()  # a store named in a catalog is there before anything is moved into it
        catalog = work / "catalog.toml"
        catalog.write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {"old": {"url": str(old.root)}, "new": {"url": str(new.root)}}}),
            encoding="utf-8", newline="\n",
        )
        before = _tree(old.root)
        with pytest.raises(EarlierLayoutError) as out:
            move("acme/rates", Stores.configured(catalog), "new")
        assert str(out.value) == refusal(old)
        assert _tree(old.root) == before and list(new.root.iterdir()) == []  # found out before anything was copied
        with pytest.raises(EarlierLayoutError) as dry:
            move("acme/rates", Stores.configured(catalog), "new", dry_run=True)
        assert str(dry.value) == refusal(old)
        # A copy leaves the store as it is, so it is made: complete, where it goes
        count, _ = move("acme/rates", Stores.configured(catalog), "new", keep=True, route=False)
        assert count == 1 and _tree(old.root) == before
        copied = new.root / "snapshots" / "acme+rates" / _folder_of(second).name
        assert (copied / "_data" / "treasury.parquet").is_file() and FolderStore(new.root).verify() == []
        # And nothing is moved into one
        _chart(rates, "the curve on the 21st")
        snapshot.make(rates, store=FolderStore(new.root))
        held = _tree(new.root)
        with pytest.raises(EarlierLayoutError) as into:
            move("acme/rates", Stores.configured(catalog), "old")
        assert str(into.value) == refusal(old)
        assert _tree(old.root) == before and _tree(new.root) == held

    def test_store_import_into_it_stops_with_those_words(self, of_0_5, rates, work, monkeypatch):
        old, second, cleared = of_0_5
        other = FolderStore(work / "other")
        _chart(rates, "the curve on the 21st")
        snapshot.make(rates, store=other)
        before = _tree(old.root)
        result = CliRunner().invoke(main, ["store", "import", str(other.root)])
        assert result.exit_code == 1
        assert result.output.splitlines() == [f"Error: {refusal(old)}"]
        assert _tree(old.root) == before

    def test_an_export_is_not_written_into_a_folder_0_5_laid_out(self, of_0_5, rates, work, monkeypatch):
        old, second, cleared = of_0_5
        mine = FolderStore(work / "mine")
        snapshot.make(rates, store=mine)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(mine.root))
        before = _tree(old.root)
        result = CliRunner().invoke(main, ["store", "export", "acme/rates", "--to", str(old.root)])
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            f"Error: {old.root} holds a store or an export of ChartBook 0.5 (pipelines/): export into another folder."
        ]
        assert _tree(old.root) == before


#: A build that writes the one table the manifest declares, the same bytes every time
DEMO = {
    "project": {"id": "acme/demo"},
    "scripts": {"build": "echo a,b > out.csv"},
    "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
}


@pytest.fixture
def demo(work, store, monkeypatch):
    """A pipeline with a build, everything committed, a branch checked out; and its store, laid out as 0.5 laid one out. Commands are run in it."""
    folder = work / "demo"
    folder.mkdir()
    (folder / "chartbook.toml").write_text(tomli_w.dumps(DEMO), encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/out.csv\n", encoding="utf-8", newline="\n")
    _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "-m", "Work")
    store.root.mkdir()
    (store.root / "pipelines").mkdir()
    (store.root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
    monkeypatch.chdir(folder)
    return folder


@posix
class TestARunWhoseStoreIsOf05:
    def test_a_run_builds_and_says_why_there_is_no_snapshot(self, demo, store):
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/demo: build",
            "Ran build in 1 pipeline(s).",
            f"acme/demo: not snapshotted: the store at {store} has the layout of ChartBook 0.5.",
            "  `chartbook store migrate` moves it. An earlier ChartBook will not read it afterwards.",
        ]
        assert (demo / "out.csv").read_text(encoding="utf-8") == "a,b\n"
        assert _tree(store.root) == ["store.json"]

    def test_run_snapshot_stops_with_the_stores_words_before_it_builds(self, demo, store):
        """As it does for work that is not committed: found out now, and not after an hour of building."""
        result = CliRunner().invoke(main, ["run", "--snapshot"])
        assert result.exit_code == 1
        assert result.output.splitlines() == [f"Error: {refusal(store)} Nothing was built."]
        assert not (demo / "out.csv").exists() and not (demo / "chartbook.lock").exists()
        assert _tree(store.root) == ["store.json"]

    def test_chartbook_snapshot_stops_with_the_stores_words(self, demo, store):
        (demo / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 1
        assert result.output.splitlines() == [f"Error: {refusal(store)}"]
        assert _tree(store.root) == ["store.json"]


class TestStoreMigrateStillMovesAStoreOf02Alone:
    """The move of a store of 0.5 to this layout is the next step: until it is there, the command says what it finds and moves nothing."""

    def test_a_store_of_this_layout_has_nothing_to_move(self, rates, store):
        snapshot.make(rates, store=store, made_at=FIRST)
        before = _tree(store.root)
        for arguments in (["store", "migrate"], ["store", "migrate", "--dry-run"], ["store", "migrate", "--yes"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 0, result.output
            assert result.output.splitlines() == [f"The store at {store} has the layout of this version already: nothing to move."]
        assert _tree(store.root) == before and FolderStore(store.root).verify() == []

    def test_a_store_of_0_5_is_left_as_it_is(self, of_0_5):
        old, second, cleared = of_0_5
        before = _tree(old.root)
        for arguments in (["store", "migrate"], ["store", "migrate", "--dry-run"], ["store", "migrate", "--yes"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 0, result.output
            assert result.output.splitlines() == [
                f"The store at {old} has the layout of ChartBook 0.5: there is nothing to move from 0.2."
            ]
        assert _tree(old.root) == before


class TestAFolderWithPipelinesAndNoMarker:
    """A store of 0.5 whose ``store.json`` has not arrived, or was removed: a store of 0.5 for every purpose, and no empty folder to make a store of this layout in."""

    @pytest.fixture
    def unmarked(self, of_0_5):
        old, second, cleared = of_0_5
        (old.root / "store.json").unlink()
        return FolderStore(old.root), second, cleared

    def test_it_is_read_as_the_store_of_0_5_it_is(self, unmarked):
        store, second, cleared = unmarked
        assert store.layout() is None and store.earlier_layout()
        assert [record.path for record in store.records()] == [second.path]
        kept = store.files(second.content()["treasury"], "acme/rates", name="treasury.parquet")
        assert kept.one.location == cleared / "_data" / "treasury.parquet"
        assert snapshot.readable_snapshots(store)[0] == [second]

    def test_no_data_is_written_to_it_and_it_is_given_no_marker(self, unmarked, work):
        """What any store of 0.5 says, in the same words: its store.json may arrive at any moment, and says the same."""
        store, second, cleared = unmarked
        before = _tree(store.root)
        (work / "new.bin").write_bytes(b"new")
        for write in (
            lambda: store.begin("acme/rates", "c" * 40, "2026-11-20T00:00:00.000000Z", base=work),
            lambda: store.put(work / "new.bin"),
            lambda: store.note_origin("c" * 40, "_top", "/somewhere/else"),
            lambda: store.tidy(),
            lambda: store.remove_snapshot(second.path),
        ):
            with pytest.raises(EarlierLayoutError) as refused:
                write()
            assert str(refused.value) == refusal(store)
        assert _tree(store.root) == before
        assert not (store.root / "store.json").exists() and not (store.root / "snapshots").exists()
        assert not (store.root / "_chartbook").exists() and not (store.root / "README.txt").exists()

    def test_a_pin_there_writes_the_lockfile_and_its_note_where_0_5_kept_them(self, unmarked, reader):
        store, second, cleared = unmarked
        before = _tree(store.root)
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(reader)])
        assert result.exit_code == 0, result.output
        assert "Error" not in result.output and (reader / "chartbook.lock").is_file()
        (note,) = (store.root / "roots").iterdir()
        noted = json.loads(note.read_text(encoding="utf-8"))
        assert noted["lockfile"] == str(reader / "chartbook.lock") and noted["hashes"] == [second.content()["treasury"]]
        assert _tree(store.root) == sorted([*before, f"roots/{note.name}"])
        assert not (store.root / "store.json").exists() and not (store.root / "_chartbook").exists()
        assert not (store.root / "README.txt").exists()

    def test_a_read_through_a_lockfile_pinned_before_still_reads(self, of_0_5, reader):
        old, second, cleared = of_0_5
        assert lock.pin(reader, old).problems == []
        (old.root / "store.json").unlink()
        before = _tree(old.root)
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)
        assert data.path("acme/rates:treasury", project_dir=reader) == cleared / "_data" / "treasury.parquet"
        assert _tree(old.root) == before and not (old.root / "store.json").exists()

    def test_its_folders_are_enough_before_a_sync_has_brought_a_file(self, of_0_5, rates, work):
        """A sync brings folders before the files in them: the tree of a store of 0.5 with no file in it yet takes no snapshot, and no marker of this layout."""
        old, second, cleared = of_0_5
        arriving = work / "arriving"
        for directory, _, _ in os.walk(old.root):
            (arriving / Path(directory).relative_to(old.root)).mkdir(parents=True, exist_ok=True)
        assert _tree(arriving) == []
        store = FolderStore(arriving)
        assert store.earlier_layout()
        _chart(rates, "the curve on the 20th")
        with pytest.raises(EarlierLayoutError) as refused:
            snapshot.make(rates, store=store)
        assert str(refused.value) == refusal(store)
        assert _tree(arriving) == [] and not (arriving / "snapshots").exists() and not (arriving / "_chartbook").exists()

    def test_one_snapshots_folder_with_nothing_in_it_is_enough(self, work):
        root = work / "left"
        (root / "pipelines" / "acme+rates" / "2026-11-16T091500Z_aaaaaaaaaaaa").mkdir(parents=True)
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert store.earlier_layout()
        with pytest.raises(EarlierLayoutError):
            store.put(work / "new.bin")
        assert _tree(root) == []

    def test_a_note_of_a_lockfile_is_enough(self, work):
        root = work / "noted"
        (root / "roots").mkdir(parents=True)
        (root / "roots" / ("ab" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert store.earlier_layout()
        with pytest.raises(EarlierLayoutError):
            store.put(work / "new.bin")
        assert _tree(root) == [f"roots/{'ab' * 16}.json"]

    def test_an_object_no_pipeline_owned_is_enough(self, work):
        root = work / "objects-only"
        held = root / "pipelines" / "+unowned" / ("7" * 64)
        held.mkdir(parents=True)
        (held / "rates.parquet").write_bytes(b"rates")
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert store.earlier_layout() and store.unowned_hashes() == ["sha256:" + "7" * 64]
        with pytest.raises(EarlierLayoutError) as refused:
            store.put(work / "new.bin")
        assert str(refused.value) == refusal(store)
        assert not (root / "store.json").exists()

    def test_a_pipelines_folder_with_no_snapshots_folder_in_it_is_no_store_of_0_5(self, work):
        """Only a folder named as a snapshot's is, or as an object's is, says a store of 0.5: an empty pipelines/, a pipeline's empty folder, or what a desktop left there, does not, and a store of this layout is made."""
        root = work / "left"
        (root / "pipelines" / "acme+rates" / "notes").mkdir(parents=True)
        (root / "pipelines" / "acme+rates" / ".DS_Store").write_bytes(b"x")
        (root / "pipelines" / "+unowned").mkdir()
        (root / "roots").mkdir()
        (root / "roots" / ".DS_Store").write_bytes(b"x")
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert not store.earlier_layout()
        store.put(work / "new.bin")
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}
        assert (root / "_chartbook" / "unowned").is_dir()


class TestAPinWhoseNoteTheStoreDidNotTake:
    def test_what_the_store_said_ends_once(self, rates, reader, store, monkeypatch):
        """The store's words end with a full stop, and the sentence they are quoted in adds none: not `today.. The pins`."""
        snapshot.make(rates, store=store, made_at=FIRST)

        def refused(self, *arguments, **options):
            raise StoreError("The store takes no note today.")

        monkeypatch.setattr(FolderStore, "add_root", refused)
        with pytest.raises(lock.LockError) as failed:
            lock.pin(reader, FolderStore(store.root))
        assert str(failed.value) == (
            f"{reader / 'chartbook.lock'} was written, and the store's note of it for `gc` could not be: The store "
            f"takes no note today. The pins are in the store and the lockfile names them; `chartbook pin` again, once "
            f"the store can be written, leaves the note."
        )
        assert (reader / "chartbook.lock").is_file()


class TestAStoreMarkedAsThisLayoutThatHoldsSnapshotsOf05:
    """This version's ``store.json`` over the ``pipelines/`` of a store of 0.5: what a first write that raced a sync left. It is refused, not read as an empty store."""

    @pytest.fixture
    def mixed(self, rates, store):
        snapshot.make(rates, store=store, made_at=FIRST)
        _chart(rates, "the curve on the 19th")
        snapshot.make(rates, store=store, made_at=SECOND)
        old = laid_out_as_0_5(store.root)
        (old.root / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8", newline="\n")
        return FolderStore(old.root)

    def test_it_is_neither_read_nor_written_and_the_message_names_both(self, mixed, work):
        before = _tree(mixed.root)
        first = sorted(p.name for p in (mixed.root / "pipelines" / "acme+rates").iterdir() if p.is_dir())[0]
        said = (
            f"The store at {mixed} has a store.json that says 'chartbook/store/v3', this version's layout, and a "
            f"pipelines/ folder that holds snapshots laid out as ChartBook 0.5 laid them out "
            f"({mixed.root / 'pipelines' / 'acme+rates' / first}): most likely a store of 0.5 that this ChartBook wrote "
            f"into before its store.json had arrived. It is neither read nor written as it is, since what is under "
            f"pipelines/ would be passed over. Move pipelines/ out of it, with roots/ and origins/ if they are there, "
            f"into a folder of their own, beside a store.json that holds {{\"schema\": \"chartbook/store/v2\"}}: that "
            f"folder is then the store of 0.5, which this ChartBook reads, and this one a store of this version's layout."
        )
        (work / "new.bin").write_bytes(b"new")
        for use in (
            lambda: mixed.records(),
            lambda: mixed.has("sha256:" + "0" * 64),
            lambda: FolderStore(mixed.root).verify(),
            lambda: FolderStore(mixed.root).put(work / "new.bin"),
            lambda: FolderStore(mixed.root).begin("acme/rates", "c" * 40, "2026-11-20T00:00:00.000000Z", base=work),
            lambda: FolderStore(mixed.root).add_root(work / "chartbook.lock", []),
            lambda: lock.plan_gc(FolderStore(mixed.root)),
        ):
            with pytest.raises(StoreError) as refused:
                use()
            assert str(refused.value) == said
        assert _tree(mixed.root) == before

    def test_the_commands_that_look_at_a_store_say_so(self, mixed):
        """Not `OK (0 object(s))` and not `No snapshots.`"""
        before = _tree(mixed.root)
        for arguments in (["store", "verify"], ["store", "ls"], ["store", "gc", "--dry-run"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 1, (arguments, result.output)
            assert "a pipelines/ folder that holds snapshots laid out as ChartBook 0.5 laid them out" in result.output, arguments
        assert _tree(mixed.root) == before

    def test_parted_as_the_message_says_both_are_stores(self, mixed, work):
        """The remedy in the message, carried out: the folders of 0.5 in a folder of their own, beside the store.json of 0.5."""
        parted = work / "of-0-5"
        parted.mkdir()
        for name in ("pipelines", "roots", "origins"):
            if (mixed.root / name).exists():
                (mixed.root / name).rename(parted / name)
        (parted / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        old, new = FolderStore(parted), FolderStore(mixed.root)
        assert old.earlier_layout() and len(snapshot.all_snapshots(old)) == 2 and old.verify() == []
        assert not new.earlier_layout() and new.records() == [] and new.verify() == []


class TestAPipelineNamedAsACommitIs:
    def test_gc_works_in_a_store_that_holds_it(self, work, store):
        """Forty hex digits under snapshots/ were a commit's folder in a store of 0.2: here they are a pipeline's, and the store is not taken for one half moved."""
        name = "deadbeef" * 5
        folder = work / "hexy"
        (folder / "_data").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": name}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_data/\n", encoding="utf-8", newline="\n")
        _table(folder, 3)
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
        first = snapshot.make(folder, store=store, made_at="2026-01-01T00:00:00.000000Z").snapshot
        _table(folder, 4)
        second = snapshot.make(folder, store=FolderStore(store.root), made_at=SECOND).snapshot
        assert _folder_of(first).parent == store.root / "snapshots" / name
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1].startswith("Removed 1 snapshot(s) and ")
        assert snapshot.all_snapshots(FolderStore(store.root)) == [second]

    def test_a_store_of_0_2_is_still_asked(self, work):
        """With no store.json, or one of another layout, the folders of 0.2 still stop a removal."""
        root = work / "old"
        (root / "snapshots" / ("a" * 40) / "_top").mkdir(parents=True)
        (root / "snapshots" / ("a" * 40) / "_top" / "20260101T000000.000000Z.json").write_text("{}\n", encoding="utf-8", newline="\n")
        with pytest.raises(StoreError, match="has not finished moving to the layout of ChartBook 0.3"):
            FolderStore(root).tidy()


class TestAPipelineOf05CopiedByHandIntoAStoreOfThisLayout:
    """One pipeline's folder out of a store of 0.5, copied under ``snapshots/`` of a store of this layout: its snapshots keep each file once, among the complete ones."""

    def test_it_is_read_a_new_snapshot_is_complete_and_gc_leaves_the_store_whole(self, rates, store, work, monkeypatch):
        import shutil

        snapshot.make(rates, store=store, made_at="2025-12-01T09:15:00.000000Z")
        _chart(rates, "the curve on the 1st")
        snapshot.make(rates, store=store, made_at="2026-01-01T09:15:00.000000Z")
        old = laid_out_as_0_5(store.root)
        new = FolderStore(work / "new")
        (new.root / "snapshots").mkdir(parents=True)
        (new.root / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8", newline="\n")
        shutil.copytree(old.root / "pipelines" / "acme+rates", new.root / "snapshots" / "acme+rates")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(new.root))
        assert len(snapshot.all_snapshots(FolderStore(new.root))) == 2 and FolderStore(new.root).verify() == []
        _chart(rates, "the curve today")
        third = snapshot.make(rates, store=FolderStore(new.root), made_at=SECOND).snapshot
        folder = _folder_of(third)
        assert _tree(folder) == [
            "README.md", "_chartbook/index.json", "_chartbook/snapshot.json", "_data/treasury.parquet", "_output/curve.html",
            "chartbook.toml",
        ]
        assert {entry["kept_in"] for entry in _entries(third)} == {folder.name}
        # The first of the two keeps the table for the second: cleared alone, its folder stays for as long
        # as the second is a snapshot, and its note says so in words that are true of it
        first, second = sorted(p for p in folder.parent.iterdir() if p.is_dir() and p != folder)
        fresh = FolderStore(new.root)
        assert fresh.remove_snapshot(first / "_chartbook" / "snapshot.json") is True
        fresh.tidy_pipeline("acme/rates")
        assert (first / "_data" / "treasury.parquet").is_file() and (first / "_chartbook" / "CLEARED.txt").is_file()
        assert "once no\nsnapshot uses a file in it" in (first / "_chartbook" / "CLEARED.txt").read_text(encoding="utf-8")
        assert FolderStore(new.root).verify() == []
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        fresh = FolderStore(new.root)
        assert fresh.verify() == [] and snapshot.all_snapshots(fresh) == [third]
        assert sorted(p.name for p in folder.parent.iterdir()) == sorted(["README.txt", folder.name])
