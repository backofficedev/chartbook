"""The store's layout on disk: ``snapshots/`` and ``_chartbook/``, a complete snapshot's folder, and a store of ChartBook 0.5 read as it is.

``docs_src/design/snapshots-and-increments.md``: "The layout", "What the
store promises" and "Moving a store to this layout". This was the first
half of step 2 of its order of work, when every snapshot was written
complete. A store now keeps a later snapshot as an increment where little
changed (``tests/test_snapshot_decides.py``, ``tests/test_increments.py``),
so a test here that is of a complete snapshot as such asks for one. A
store of 0.5 is read, its notes of lockfiles are written, and nothing else
is written to it or removed from it.

The pipeline is the one of the design's example: ``acme/rates``, a table, a
chart and a README. A store of 0.5 is laid out by hand
(``tests/store_of_0_5.py``).
"""

import json
import os
import shutil
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, snapshot
from chartbook import store as store_module
from chartbook.cli import _format_bytes, main
from chartbook.store import EarlierLayoutError, FolderStore, StoreError
from tests.fixtures import _git
from tests.store_of_0_5 import cleared_as_0_5, laid_out_as_0_5

FIRST, SECOND, THIRD = "2026-11-16T09:15:00.000000Z", "2026-11-19T14:02:00.000000Z", "2026-11-20T10:00:00.000000Z"

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


def _where(store, taken, asset: str, name: str = None) -> Path:
    """Where the store keeps the one file of a snapshot's asset, asked of the store: the snapshot's own folder, or, for one kept as an increment, the complete snapshot it builds on."""
    held = FolderStore(store.root).files(taken.content()[asset], taken.pipeline, name=name, snapshot=(taken.commit, taken.made_at))
    return held.one.location


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

    def test_the_readme_at_the_top_names_every_folder_a_person_finds_there_and_is_written_once(self, rates, store):
        """`increments/` is at the top of the store once a second snapshot is made, and the README there, which is for whoever opens the folder, says what it is."""
        snapshot.make(rates, store=store, made_at=FIRST)
        note = store.root / "README.txt"
        text = note.read_text(encoding="utf-8")
        assert text.splitlines()[0] == (
            "This folder is a ChartBook store: the snapshots of pipelines, kept for other pipelines to read."
        )
        assert "\nsnapshots/   One folder for each pipeline" in text and "\n_chartbook/  ChartBook's own notes." in text
        assert "\nincrements/  Snapshots kept in less room" in text and "_chartbook/INCREMENT.txt in each says\n" in text
        # Complete is said of a folder under snapshots/, and of no other
        assert "Each snapshot's folder here is complete" in text and "A folder here is not the whole snapshot by itself." in text
        assert text.splitlines()[-1] == "Remove a snapshot with `chartbook store gc`, not by hand."
        note.write_text(text + "A note of my own.\n", encoding="utf-8", newline="\n")
        _table(rates, 4)
        assert snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND).kept.increment
        assert note.read_text(encoding="utf-8").endswith("A note of my own.\n")  # nothing in the store is rewritten
        # Every name at the top of the store is in it
        at_the_top = sorted(path.name for path in store.root.iterdir())
        assert at_the_top == ["README.txt", "_chartbook", "increments", "snapshots", "store.json"]
        assert all(name in text for name in ("snapshots/", "increments/", "_chartbook/", "store.json"))
        # And the two notes beside it read rightly with it: one in each pipeline's folder, under each of the two
        assert (store.root / "snapshots" / "acme+rates" / "README.txt").read_text(encoding="utf-8") == store_module.PIPELINE_README
        assert (store.root / "increments" / "acme+rates" / "README.txt").read_text(encoding="utf-8") == store_module.INCREMENTS_README

    def test_the_readme_of_a_pipelines_folder_says_each_folder_is_complete(self, rates, store):
        snapshot.make(rates, store=store, made_at=FIRST)
        text = (store.root / "snapshots" / "acme+rates" / "README.txt").read_text(encoding="utf-8")
        assert "Each folder here is one complete snapshot" in text
        assert "A snapshot's folder can be read or copied as it is." in text
        # Not by hand: gc keeps what a lockfile pins, and a snapshot that an increment builds on
        assert text.splitlines()[-3:] == [
            "Remove one with `chartbook store gc`, not by hand: gc keeps what a lockfile pins, and a snapshot",
            "that an increment builds on (increments/, beside snapshots/, keeps the files such a one has and",
            "this folder's snapshot does not; the rest of its files are read from here).",
        ]
        assert "shared" not in text and "standalone" not in text


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
        # Complete: this is of a complete snapshot as such, which repeats what the one before it has
        second = snapshot.make(rates, store=store, made_at=SECOND, complete=True).snapshot
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
        with pytest.raises(StoreError, match="went from the store.*Run the command again"):
            third.write(_record(third, "c" * 40, rates=put))
        third.discard()
        assert sorted(_folders(store.pipeline_path("acme/rates"))) == sorted([first.name, second.name])


class TestThePathOfAPinnedFile:
    """Which copy a read is handed, of the pipeline's own snapshots that hold the asset whole, and never another pipeline's.

    The snapshot the lockfile names, by its commit and when it was made; for
    a ``git`` dependency, whose entry names its commit alone, the newest of
    that commit; and otherwise the newest, which is the one ``store gc``
    keeps (a version of a model read by its hash or its label). So the
    path of a file read through a pin stays while the pinned snapshot is in
    the store and whole.
    """

    @pytest.mark.parametrize("complete", [False, True], ids=["kept as the store chooses", "kept complete"])
    def test_it_stays_where_it_is_while_neither_the_pin_nor_the_bytes_move(self, rates, reader, store, complete):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, store).problems == []
        before = data.path("acme/rates:treasury", project_dir=reader)
        assert before == _folder_of(first) / "_data" / "treasury.parquet"
        _chart(rates, "the chart alone is drawn again")  # the table's bytes do not change, and the reader does not pin again
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND, complete=complete).snapshot
        # The later one has the table too: in its own folder where it is complete, and in the first one's where it is an increment
        kept = _where(store, second, "treasury", "treasury.parquet")
        assert second.path != first.path and kept.is_file() and (kept != before) is complete
        assert data.path("acme/rates:treasury", project_dir=reader) == before
        result = CliRunner().invoke(main, ["path", "acme/rates:treasury", "--project-dir", str(reader)])
        assert result.exit_code == 0 and result.output.splitlines() == [str(before)]

    def test_another_snapshots_copy_is_read_where_the_pinned_one_has_lost_its_own(self, rates, reader, store):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, store).problems == []
        _chart(rates, "the chart alone is drawn again")
        # Complete: another snapshot's own copy of the table is what this is about (an increment's is the first one's)
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=SECOND, complete=True).snapshot
        own = _folder_of(first) / "_data" / "treasury.parquet"
        own.chmod(0o644)
        own.unlink()
        assert data.path("acme/rates:treasury", project_dir=reader) == _folder_of(second) / "_data" / "treasury.parquet"
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)
        # Where the pinned one has lost it, the newest of the pipeline that has it whole: the one `store gc` keeps.
        # Complete, so that the newest has a copy of its own to be handed: an increment's would be the second one's file again
        _chart(rates, "and again")
        third = snapshot.make(rates, store=FolderStore(store.root), made_at=THIRD, complete=True).snapshot
        its_own = _folder_of(third) / "_data" / "treasury.parquet"
        assert its_own.is_file() and its_own != _folder_of(second) / "_data" / "treasury.parquet"
        assert data.path("acme/rates:treasury", project_dir=reader) == its_own == _where(store, third, "treasury", "treasury.parquet")

    @pytest.fixture
    def with_parts(self, rates):
        """``acme/rates`` with a folder dataset of a file a year beside its table, committed again."""
        for year, rows in ((2020, [4.0]), (2021, [4.1, 4.2])):
            (rates / "_data" / "parts" / f"year={year}").mkdir(parents=True)
            pl.DataFrame({"rate": rows}).write_parquet(rates / "_data" / "parts" / f"year={year}" / "part-0.parquet")
        manifest = {
            "project": {"id": "acme/rates"},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "parts": {"path": "./_data/parts", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }
        (rates / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        _git(rates, "add", "-A")
        _git(rates, "commit", "--quiet", "-m", "A dataset of a file a year")
        return rates

    def test_every_way_of_reading_a_pin_gets_the_pinned_snapshots_own_copy(self, with_parts, reader, store):
        from chartbook import assets

        first = snapshot.make(with_parts, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        _chart(with_parts, "the chart alone is drawn again")
        second = snapshot.make(with_parts, store=FolderStore(store.root), made_at=SECOND).snapshot
        assert second.path != first.path
        own = _folder_of(first)
        assert data.path("acme/rates:treasury", project_dir=reader) == own / "_data" / "treasury.parquet"
        assert assets.path("acme/rates:dataframe/treasury", project_dir=reader) == own / "_data" / "treasury.parquet"
        assert [Path(path) for path in data.files("acme/rates:parts", project_dir=reader)] == [
            own / "_data" / "parts" / "year=2020" / "part-0.parquet", own / "_data" / "parts" / "year=2021" / "part-0.parquet",
        ]
        said = CliRunner().invoke(main, ["path", "acme/rates:treasury", "--project-dir", str(reader)])
        assert said.output.splitlines() == [str(own / "_data" / "treasury.parquet")]
        assert data.load("acme/rates:parts", project_dir=reader).collect().shape[0] == 3

    def test_a_dataset_the_pinned_snapshot_has_lost_a_file_of_is_read_whole_from_one_other_folder(self, with_parts, reader, store):
        first = snapshot.make(with_parts, store=store, made_at=FIRST).snapshot
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        _chart(with_parts, "the chart alone is drawn again")
        # Complete: one other folder that holds the whole dataset is what this is about (an increment's parts are the first one's)
        second = snapshot.make(with_parts, store=FolderStore(store.root), made_at=SECOND, complete=True).snapshot
        lost = _folder_of(first) / "_data" / "parts" / "year=2021" / "part-0.parquet"
        lost.chmod(0o644)
        lost.unlink()
        assert data.load("acme/rates:parts", project_dir=reader).collect().shape[0] == 3
        # One folder for the whole asset, not a file from each
        assert [Path(path) for path in data.files("acme/rates:parts", project_dir=reader)] == [
            _folder_of(second) / "_data" / "parts" / f"year={year}" / "part-0.parquet" for year in (2020, 2021)
        ]

    def test_one_pinned_from_a_repository_stays_where_it_is_when_another_project_pins_a_later_commit(self, work, store):
        """A ``git`` dependency's entry names a commit and no time: the read gets the earliest-made snapshot at that commit."""
        from chartbook.gitcache import GitCache

        upstream = work / "upstream"
        (upstream / "data").mkdir(parents=True)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/upstream"}, "dataframes": {
                "steady": {"path": "./data/steady.parquet", "docs": "d"},
                "moving": {"path": "./data/moving.parquet", "docs": "d"},
            }}),
            encoding="utf-8", newline="\n",
        )
        pl.DataFrame({"day": [0, 1, 2]}).write_parquet(upstream / "data" / "steady.parquet")
        pl.DataFrame({"day": [0]}).write_parquet(upstream / "data" / "moving.parquet")
        _git(upstream, "init", "--quiet", "-b", "main")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "--quiet", "-m", "One")
        one, two = work / "one", work / "two"
        for folder in (one, two):
            folder.mkdir()
            (folder / "chartbook.toml").write_text(
                tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
                encoding="utf-8", newline="\n",
            )
        cache = GitCache(work / "gitcache")
        assert lock.pin(one, FolderStore(store.root), git_cache=cache).problems == []
        (entry,) = lock.read_lock(one).dependencies
        assert entry["location"]["commit"] and "snapshot" not in entry  # a commit, and no snapshot's time
        before = data.path("acme/upstream:steady", project_dir=one)
        (made_by_the_pin,) = (store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json")
        assert Path(before) == made_by_the_pin.parent.parent / "data" / "steady.parquet"
        # Upstream changes its other table and commits; another project pins that commit. `one` pins nothing again
        pl.DataFrame({"day": [0, 1]}).write_parquet(upstream / "data" / "moving.parquet")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "--quiet", "-m", "Two")
        assert lock.pin(two, FolderStore(store.root), git_cache=cache).problems == []
        assert len(list((store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json"))) == 2
        assert data.path("acme/upstream:steady", project_dir=one) == before

    def test_a_version_of_a_model_read_by_its_hash_is_in_the_newest_snapshot_that_holds_it(self, work, store):
        """`models.path("m@<hash>")`: the copy `store gc` keeps, so the path changes when a later snapshot holds the version too."""
        from chartbook import models

        folder = work / "forecast"
        (folder / "_output").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/forecast"},
                "models": {"m": {"path": "./_output/m.json"}},
                "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_output/\n", encoding="utf-8", newline="\n")
        (folder / "_output" / "m.json").write_text('{"weights": [1, 2, 3]}\n', encoding="utf-8", newline="\n")
        (folder / "_output" / "curve.html").write_text("<p>one</p>\n", encoding="utf-8", newline="\n")
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
        first = snapshot.make(folder, store=store, made_at=FIRST).snapshot
        version = first.content()["model/m"].split(":", 1)[1][:12]
        assert models.path(f"m@{version}", project_dir=folder) == _folder_of(first) / "_output" / "m.json"
        made = [first]
        for text, made_at in (("two", SECOND), ("three", THIRD)):
            (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n", encoding="utf-8", newline="\n")
            made.append(snapshot.make(folder, store=FolderStore(store.root), made_at=made_at).snapshot)
            # Where the newest keeps it: its own folder, or, kept as an increment, the complete one it builds on
            assert models.path(f"m@{version}", project_dir=folder) == _where(store, made[-1], "model/m", "m.json")
        # Here the two later ones are increments on the first, since the chart alone was drawn again: the model is
        # kept once, in the first one's folder, which the newest builds on
        assert [FolderStore(store.root).builds_on(taken.path) is not None for taken in made] == [False, True, True]
        # And that is the copy gc keeps: with nothing kept for being new, the second goes, the first stays for
        # the newest, and the path stays
        before = models.path(f"m@{version}", project_dir=folder)
        assert before == _folder_of(first) / "_output" / "m.json"
        plan = lock.plan_gc(FolderStore(store.root), keep_days=0)
        assert sorted(taken.made_at for taken, _ in plan.snapshots_delete) == [SECOND]
        lock.run_gc(plan, FolderStore(store.root))
        assert before.is_file() and models.path(f"m@{version}", project_dir=folder) == before

    def test_a_version_of_a_model_is_read_from_the_newest_complete_snapshot_that_holds_it(self, work, store):
        """The same, where each snapshot is complete and has its own copy: the path moves to the newest, and that is the one gc keeps."""
        from chartbook import models

        folder = work / "forecast"
        (folder / "_output").mkdir(parents=True)
        (folder / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/forecast"},
                "models": {"m": {"path": "./_output/m.json"}},
                "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (folder / ".gitignore").write_text("/_output/\n", encoding="utf-8", newline="\n")
        (folder / "_output" / "m.json").write_text('{"weights": [1, 2, 3]}\n', encoding="utf-8", newline="\n")
        _git(folder, "init", "--quiet", "-b", "main")
        _git(folder, "add", "-A")
        _git(folder, "commit", "--quiet", "-m", "Work")
        version, made = None, []
        for text, made_at in (("one", FIRST), ("two", SECOND), ("three", THIRD)):
            (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n", encoding="utf-8", newline="\n")
            # Complete: each then has its own copy of the model, which is what this is about
            made.append(snapshot.make(folder, store=FolderStore(store.root), made_at=made_at, complete=True).snapshot)
            version = version or made[0].content()["model/m"].split(":", 1)[1][:12]
            assert models.path(f"m@{version}", project_dir=folder) == _folder_of(made[-1]) / "_output" / "m.json"
        before = models.path(f"m@{version}", project_dir=folder)
        plan = lock.plan_gc(FolderStore(store.root), keep_days=0)
        assert sorted(taken.made_at for taken, _ in plan.snapshots_delete) == [FIRST, SECOND]
        lock.run_gc(plan, FolderStore(store.root))
        assert before.is_file() and models.path(f"m@{version}", project_dir=folder) == before

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
        """Two snapshots of ``acme/rates``: the first old enough to go, the second the newest, with the same table.

        Both complete: these are of a complete snapshot's whole folder
        going, and one that an increment builds on stays
        (``tests/test_increments.py``).
        """
        first = snapshot.make(rates, store=store, made_at="2026-01-01T00:00:00.000000Z").snapshot
        _chart(rates, "the curve, drawn again")
        second = snapshot.make(rates, store=store, complete=True).snapshot
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
        # Complete: this is of the line of a complete snapshot (tests/test_increments.py has an increment's)
        second = snapshot.make(rates, store=store, made_at=SECOND, complete=True).snapshot
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
            "A complete snapshot's folder holds every file of its version; an increment's holds what the one it builds on does not.",
        ]


class TestExportAndImport:
    def test_an_export_is_laid_out_as_a_store_and_is_taken_in_by_another(self, rates, store, work, monkeypatch):
        first = snapshot.make(rates, store=store, made_at=FIRST).snapshot
        _chart(rates, "the curve on the 19th")
        # Complete: this is of an export of complete snapshots (tests/test_increments.py has one that keeps an increment's form)
        second = snapshot.make(rates, store=store, made_at=SECOND, complete=True).snapshot
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

    def test_store_ls_lists_it_as_complete_or_increment(self, of_0_5):
        old, second, cleared = of_0_5
        folder = _folder_of(second)
        own = (folder / "_chartbook" / "index.json").stat().st_size + (folder / "_output" / "curve.html").stat().st_size
        result = CliRunner().invoke(main, ["store", "ls"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/rates (1 snapshot(s))",
            f"  {folder.name}  2026-11-19 14:02 UTC  {second.commit[:7]}  increment  {_format_bytes(own)} here, 3 file(s) in other folders",
            "A complete snapshot's folder holds every file of its version; an increment's holds what the one it builds on does not.",
        ]

    def test_store_info_and_store_verify_read_it(self, of_0_5):
        old, second, cleared = of_0_5
        info = CliRunner().invoke(main, ["store", "info"])
        assert info.exit_code == 0, info.output
        assert info.output.splitlines()[0] == f"Store: {old}" and "store gc" not in info.output  # nothing is removed from it
        verify = CliRunner().invoke(main, ["store", "verify"])
        assert verify.exit_code == 0, verify.output
        assert verify.output.splitlines() == [f"{old}: OK ({len(second.hashes())} object(s))"]

    def test_store_verify_counts_a_file_missing_from_a_folder_that_has_no_record(self, of_0_5):
        """Found by review: a store of 0.5 keeps each file once, often in the folder of a snapshot its `store gc` has cleared since. A file missing from such a folder had its line, "(the snapshot <the cleared folder>)", and the count ahead of the lines left it out, since the folder has no record.

        The first line counts every line of a file below it, each under
        the folder the file is missing from: here the cleared one, whose
        pipeline its folder says.

        And that folder is said to be what it is. Found on a real store:
        each file's line ended "(the snapshot <the cleared folder>)" and
        the count listed that folder as a snapshot, while `store ls`
        named the snapshot whose record names the files. Two snapshots
        were named for the same files, and one of them is none."""
        old, second, cleared = of_0_5
        lost = cleared / "_data" / "treasury.parquet"
        lost.chmod(0o644)
        lost.unlink()
        store_module._read_records.clear()
        store_module._found_whole.clear()
        listed = CliRunner().invoke(main, ["store", "ls"]).output.splitlines()
        assert [line for line in listed if ", lacks " in line] == [line for line in listed if line.split()[:1] == [_folder_of(second).name]]
        verify = CliRunner().invoke(main, ["store", "verify"])
        assert verify.exit_code == 1 and verify.output.splitlines()[:4] == [
            "1 file(s) of 1 snapshot(s) are missing or are not what their records say. By snapshot, and then each file:",
            f"  acme/rates  {cleared.name} (a folder with no record)  1 file(s)",
            f"{second.content()['treasury']}: _data/treasury.parquet is not in the store (the folder {cleared.name}, which has no record)",
            "",
        ]
        # A file missing from a folder that has its record is of that snapshot, as it was
        own = _folder_of(second) / "_output" / "curve.html"
        own.chmod(0o644)
        own.unlink()
        store_module._found_whole.clear()
        lines = CliRunner().invoke(main, ["store", "verify"]).output.splitlines()
        assert lines[:3] == [
            "2 file(s) of 2 snapshot(s) are missing or are not what their records say. By snapshot, and then each file:",
            f"  acme/rates  {cleared.name} (a folder with no record)  1 file(s)",
            f"  acme/rates  {_folder_of(second).name}  1 file(s)",
        ]
        assert lines[4].endswith(f": _output/curve.html is not in the store (the snapshot {_folder_of(second).name})")

    def test_store_verify_names_a_record_it_cannot_read(self, of_0_5):
        """Found by review: `chartbook store migrate` refuses a store for a record it cannot follow and says "`chartbook store verify` says more", and verify passed such a record over without a word. It names the record, as the store shows it, and why it is not read; and ends 1."""
        old, second, cleared = of_0_5
        record = Path(second.path)
        whole = record.read_text(encoding="utf-8")
        record.chmod(0o644)
        record.write_text(whole[:200], encoding="utf-8", newline="\n")  # as a sync that has not finished leaves it
        store_module._read_records.clear()
        store_module._found_whole.clear()
        verify = CliRunner().invoke(main, ["store", "verify"])
        lines = verify.output.splitlines()
        assert verify.exit_code == 1 and len(lines) == 3, verify.output
        assert lines[0].startswith(f"The snapshot record {record} cannot be read: it is not JSON (")
        assert lines[0].endswith("), as a file is that a sync has brought part of. Nothing of its snapshot is checked.")
        assert lines[1:] == ["", f"1 snapshot record(s) in {old} cannot be read."]

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
        result = CliRunner().invoke(main, ["snapshot", "--as-is", "--project-dir", str(rates)])
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
        result = CliRunner().invoke(main, ["snapshot", "--as-is", "--project-dir", str(rates)])
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
    def test_a_run_builds_as_anywhere_since_it_makes_no_snapshot(self, demo, store):
        """A plain run puts nothing of what it built in any store, so how this one is laid out is nothing to it. The snapshot it names says so."""
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/demo: build",
            "Ran build in 1 pipeline(s).",
            "acme/demo: built.",
            "  For other pipelines and the catalog: commit, then `chartbook snapshot`.",
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
        result = CliRunner().invoke(main, ["snapshot", "--as-is"])
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

    def test_a_store_of_0_5_is_what_it_moves_and_a_dry_run_or_a_no_moves_nothing(self, of_0_5):
        """The move itself is in tests/test_migrate_0_5.py."""
        old, second, cleared = of_0_5
        before = _tree(old.root)
        for arguments, typed in ((["store", "migrate"], "n\n"), (["store", "migrate", "--dry-run"], None)):
            result = CliRunner().invoke(main, arguments, input=typed)
            assert result.exit_code == 0, result.output
            lines = result.output.splitlines()
            assert lines[0] == f"The store at {old} has the layout of ChartBook 0.5: 1 pipeline(s), 1 snapshot(s)."
            assert lines[-1] == "Nothing was moved."
        assert _tree(old.root) == before

    def test_its_help_is_for_whoever_comes_from_0_5_and_says_of_0_2_only_that_it_takes_two_runs(self):
        """Found by a person upgrading: after the paragraph on a store of 0.5 came four on the move from 0.2 to 0.3, "Upgrade every machine … to ChartBook 0.3 first" among them."""
        result = CliRunner().invoke(main, ["store", "migrate", "--help"])
        assert result.exit_code == 0, result.output
        paragraphs = [" ".join(paragraph.split()) for paragraph in result.output.split("\n\n")]
        assert paragraphs[1] == "Move a store to this version's layout: one that ChartBook 0.5 laid out, or one made by 0.2."
        assert paragraphs[2].startswith("A store of 0.5 (`pipelines/` at its top) is read as it is and not written. This moves it, once, on one machine: ")
        of_0_2 = "A store made by ChartBook 0.2 is moved to the layout of 0.5 by the first run of this command, and on to this version's by a second."
        assert paragraphs[3] == of_0_2
        said = " ".join(paragraphs)
        assert said.count("0.2") == 2 and "0.3" not in said and "Upgrade every machine" not in said
        # And the reference page says the same of it, in the same words
        page = (Path(__file__).parent.parent / "docs_src" / "reference" / "cli.md").read_text(encoding="utf-8")
        section = page.partition("\n### store migrate\n")[2].partition("\n### ")[0]
        assert of_0_2.replace("A store made by ChartBook 0.2 is", "**A store made by ChartBook 0.2** is") in section
        assert "Upgrade every machine first" not in section and "ChartBook 0.3" not in section.replace("plan-0.3.0", "")


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

    def test_no_data_is_written_to_it_and_the_message_says_what_was_found_and_the_way_out(self, unmarked, work):
        """Its own words, which send nobody to `store migrate`: that moves a store that has a store.json."""
        store, second, cleared = unmarked
        before = _tree(store.root)
        (work / "new.bin").write_bytes(b"new")
        said = (
            f"The store at {store} has no store.json, and holds a pipelines/ folder with snapshots or objects in it: "
            f"what a store of ChartBook 0.5 holds, whose store.json may not have arrived yet (a sync that has not "
            f"finished). Until it has, the folder is read as that store, and no data is written to it or removed from "
            f"it. If it is no store of ChartBook 0.5 any more, remove pipelines/ from it and try again. If it is one whose store.json is lost "
            f'for good, put one back that holds {{"schema": "chartbook/store/v2"}}.'
        )
        for write in (
            lambda: store.begin("acme/rates", "c" * 40, "2026-11-20T00:00:00.000000Z", base=work),
            lambda: store.put(work / "new.bin"),
            lambda: store.note_origin("c" * 40, "_top", "/somewhere/else"),
            lambda: store.tidy(),
            lambda: store.remove_snapshot(second.path),
        ):
            with pytest.raises(StoreError) as refused:
                write()
            assert str(refused.value) == said and not isinstance(refused.value, EarlierLayoutError)
        assert _tree(store.root) == before
        assert not (store.root / "store.json").exists() and not (store.root / "snapshots").exists()
        assert not (store.root / "_chartbook").exists() and not (store.root / "README.txt").exists()
        # Once its store.json has arrived it says what any store of 0.5 says
        (store.root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        with pytest.raises(EarlierLayoutError) as refused:
            FolderStore(store.root).put(work / "new.bin")
        assert str(refused.value) == refusal(store)

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
        with pytest.raises(StoreError, match=r"has no store.json, and holds a pipelines/ folder with snapshots or objects in it"):
            snapshot.make(rates, store=store)
        assert _tree(arriving) == [] and not (arriving / "snapshots").exists() and not (arriving / "_chartbook").exists()

    def test_one_snapshots_folder_with_nothing_in_it_is_enough(self, work):
        root = work / "left"
        (root / "pipelines" / "acme+rates" / "2026-11-16T091500Z_aaaaaaaaaaaa").mkdir(parents=True)
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert store.earlier_layout()
        with pytest.raises(StoreError, match="remove pipelines/ from it and try again"):
            store.put(work / "new.bin")
        assert _tree(root) == []

    def test_a_roots_folder_with_notes_is_enough_and_removing_it_is_the_way_out(self, rates, work, monkeypatch):
        """What is left once a person has removed pipelines/ and store.json of a store of 0.5 to start again."""
        root = work / "fresh"
        (root / "roots").mkdir(parents=True)
        (root / "roots" / ("ab" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        store = FolderStore(root)
        assert store.earlier_layout()
        with pytest.raises(StoreError) as refused:
            snapshot.make(rates, store=store, made_at=SECOND)
        assert str(refused.value) == (
            f"The store at {store} has no store.json, and holds a roots/ folder with notes in it: what a store of "
            f"ChartBook 0.5 holds, whose store.json may not have arrived yet (a sync that has not finished). Until it "
            f"has, the folder is read as that store, and no data is written to it or removed from it. If it is no "
            f"store of ChartBook 0.5 any more, remove roots/ from it and try again. If it is one whose store.json is lost for "
            f'good, put one back that holds {{"schema": "chartbook/store/v2"}}.'
        )
        assert "migrate" not in str(refused.value)
        assert _tree(root) == [f"roots/{'ab' * 16}.json"]
        # The command it does not send to moves nothing of it either: its store.json is not there to say what it is
        migrate = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert migrate.exit_code == 1 and migrate.output.splitlines() == [
            f"Error: The store at {root} has no store.json that says 'chartbook/store/v2', the layout of ChartBook 0.5, so it "
            f"is not moved. If a sync is still bringing the file, wait for it; if it is lost for good, put one back that "
            f'holds {{"schema": "chartbook/store/v2"}}, and run this again.'
        ]
        # The way out, as written: what was named is removed, and the snapshot is made
        (root / "roots" / ("ab" * 16 + ".json")).unlink()
        (root / "roots").rmdir()
        taken = snapshot.make(rates, store=FolderStore(root), made_at=SECOND)
        assert taken.made and json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}

    def test_both_are_named_where_both_are_found(self, unmarked, reader, work):
        store, second, cleared = unmarked
        assert lock.pin(reader, store).problems == []  # its note goes under roots/
        (work / "new.bin").write_bytes(b"new")
        with pytest.raises(StoreError) as refused:
            FolderStore(store.root).put(work / "new.bin")
        assert "holds a pipelines/ folder with snapshots or objects in it and a roots/ folder with notes in it:" in str(refused.value)
        assert "remove pipelines/ and roots/ from it and try again. If it is one whose store.json is lost for good" in str(refused.value)

    def test_an_object_no_pipeline_owned_is_enough(self, work):
        root = work / "objects-only"
        held = root / "pipelines" / "+unowned" / ("7" * 64)
        held.mkdir(parents=True)
        (held / "rates.parquet").write_bytes(b"rates")
        (work / "new.bin").write_bytes(b"new")
        store = FolderStore(root)
        assert store.earlier_layout() and store.unowned_hashes() == ["sha256:" + "7" * 64]
        with pytest.raises(StoreError, match="holds a pipelines/ folder with snapshots or objects in it"):
            store.put(work / "new.bin")
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


#: The end of what a store.json of 0.5 over this version's trees says: what a move renamed is under them and nowhere else
GOES_ON = (
    "It is neither read nor written as it is. If a move may still be arriving by a sync, wait for the sync to finish. "
    "Then run `chartbook store migrate`, which goes on from the folders as they are."
)


class TestAFolderWithBothLayoutsInIt:
    """A store of 0.5 that this version wrote into before its ``store.json`` had arrived: ``pipelines/`` and ``snapshots/``, and one ``store.json``.

    Whichever layout the ``store.json`` says, the snapshots of the other
    would be passed over without a word: so it is refused whole, and the
    message says to run `chartbook store migrate`.
    """

    @pytest.fixture
    def mixed(self, rates, reader, store, work):
        """Two snapshots of 0.5 that a pipeline is pinned to, and one of this layout beside them; the folder, and the snapshots' folders' names."""
        snapshot.make(rates, store=store, made_at=FIRST)
        _chart(rates, "the curve on the 19th")
        snapshot.make(rates, store=store, made_at=SECOND)
        old = laid_out_as_0_5(store.root)
        assert lock.pin(reader, old).problems == []  # its note is under roots/
        other = FolderStore(work / "written-meanwhile")
        _chart(rates, "the curve on the 20th")
        third = snapshot.make(rates, store=other, made_at=THIRD).snapshot
        shutil.copytree(other.root / "snapshots", old.root / "snapshots")
        shutil.copytree(other.root / "_chartbook", old.root / "_chartbook")
        shutil.copy(other.root / "store.json", old.root / "store.json")
        of_0_5 = sorted(p.name for p in (old.root / "pipelines" / "acme+rates").iterdir() if p.is_dir())
        return old.root, of_0_5, _folder_of(third).name

    @staticmethod
    def _said(root: Path, of_0_5: list, of_this: str, marker: str) -> str:
        store = FolderStore(root)
        if marker == "chartbook/store/v3":
            return (
                f"The store at {store} has this version's layout, and at its top what ChartBook 0.5 keeps there "
                f"(pipelines/, roots/, origins/, tmp/): a machine that had not been brought the move wrote it, or a move on another machine is "
                f"still arriving by a sync. It is neither read nor written as it is. If a move may still be arriving, "
                f"wait for the sync to finish. Then run `chartbook store migrate`, which moves it in."
            )
        return (
            f"The store at {store} has a store.json that says 'chartbook/store/v2', the layout of ChartBook 0.5, and "
            f"folders laid out as this version lays them out ({root / 'snapshots' / 'acme+rates' / of_this}): a move to "
            f"this version's layout that was cut short, or one on another machine that a sync is still bringing. {GOES_ON}"
        )

    @pytest.mark.parametrize("marker", ["chartbook/store/v3", "chartbook/store/v2"])
    def test_it_is_neither_read_nor_written_whichever_layout_its_store_json_says(self, mixed, work, marker):
        root, of_0_5, of_this = mixed
        (root / "store.json").write_text(json.dumps({"schema": marker}) + "\n", encoding="utf-8", newline="\n")
        before = _tree(root)
        (work / "new.bin").write_bytes(b"new")
        for use in (
            lambda: FolderStore(root).records(),
            lambda: FolderStore(root).has("sha256:" + "0" * 64),
            lambda: FolderStore(root).verify(),
            lambda: FolderStore(root).put(work / "new.bin"),
            lambda: FolderStore(root).begin("acme/rates", "c" * 40, "2026-11-21T00:00:00.000000Z", base=work),
            lambda: FolderStore(root).add_root(work / "chartbook.lock", []),
            lambda: lock.plan_gc(FolderStore(root)),
        ):
            with pytest.raises(StoreError) as refused:
                use()
            assert str(refused.value) == self._said(root, of_0_5, of_this, marker)
        assert _tree(root) == before

    def test_a_store_of_this_layout_whose_store_json_says_0_5_is_no_empty_store(self, rates, store):
        """The mirror with nothing of 0.5 in it but its store.json, which a sync brought first and wrote over this one's."""
        taken = snapshot.make(rates, store=store, made_at=SECOND).snapshot
        (store.root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        with pytest.raises(StoreError, match=r"and folders laid out as this version lays them out"):
            FolderStore(store.root).records()
        for arguments in (["store", "verify"], ["store", "info"], ["store", "ls"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 1, (arguments, result.output)
            assert f"snapshots/acme+rates/{_folder_of(taken).name}".replace("/", os.sep) in result.output, arguments

    @pytest.mark.parametrize("marker", ["chartbook/store/v3", "chartbook/store/v2"])
    def test_every_command_says_it_and_none_ends_in_a_traceback(self, mixed, reader, rates, work, marker):
        """Not `OK (0 object(s))`, not `No snapshots.`, and not "the layout of this version already"."""
        root, of_0_5, of_this = mixed
        (root / "store.json").write_text(json.dumps({"schema": marker}) + "\n", encoding="utf-8", newline="\n")
        before = _tree(root)
        # (`store migrate` is the one command that does not refuse it: it is the remedy, tests/test_migrate_0_5.py)
        both = "at its top what ChartBook 0.5 keeps there (pipelines/" if marker.endswith("v3") else "and folders laid out as this version lays them out"
        for arguments in (
            ["store", "verify"], ["store", "info"], ["store", "ls"], ["store", "gc", "--dry-run"],
            ["pin", "--project-dir", str(reader)], ["snapshot", "--as-is", "--project-dir", str(rates)],
            ["path", "acme/rates:treasury", "--project-dir", str(reader)], ["lineage", "--project-dir", str(reader)],
            ["store", "export", "acme/rates", "--to", str(work / "out")],  # (`restore` here has nothing to restore, and asks the store nothing)
        ):
            result = CliRunner().invoke(main, arguments)
            assert result.exception is None or isinstance(result.exception, SystemExit), (arguments, repr(result.exception))
            assert both in result.output, (arguments, result.output)
            assert "of this version already" not in result.output and "OK (" not in result.output
        assert _tree(root) == before

    def test_the_remedy_carried_out_with_a_store_json_of_0_5_the_move_goes_on_around_what_is_there(self, mixed, reader, monkeypatch):
        """`chartbook store migrate`, as the message says: the two snapshots of 0.5 are moved in beside the one of this layout, and the pin reads."""
        root, of_0_5, of_this = mixed
        (root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and "looks half moved, and the move goes on from the folders as they are" in result.output.replace("\n", " "), result.output
        store_module._read_records.clear()
        moved = FolderStore(root)
        assert not moved.earlier_layout() and moved.verify() == []
        assert sorted(record.folder.name for record in moved.records()) == sorted(of_0_5 + [of_this])
        assert data.load("acme/rates:treasury", project_dir=reader).collect().shape == (3, 2)
        assert [root_.lockfile for root_ in moved.roots()] == [reader / "chartbook.lock"]

    def test_the_remedy_carried_out_with_a_store_json_of_this_layout_the_folder_of_0_5_goes_aside_whole(self, mixed, monkeypatch):
        """`chartbook store migrate`, as the message says: nothing under pipelines/ is moved in, and its snapshots are named."""
        root, of_0_5, of_this = mixed
        (root / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8", newline="\n")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        said = result.output.replace("\n", " ")
        assert result.exit_code == 0 and f"2 snapshot(s) went aside without being moved in: acme+rates/{of_0_5[0]}, acme+rates/{of_0_5[1]}." in said, result.output
        store_module._read_records.clear()
        moved = FolderStore(root)
        assert moved.verify() == [] and [record.folder.name for record in moved.records()] == [of_this]
        assert sorted(p.name for p in (root / "_chartbook" / "left-by-0.5" / "pipelines" / "acme+rates").iterdir() if p.is_dir()) == of_0_5


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
        # Complete, so that nothing builds on the first and gc has a snapshot to remove
        second = snapshot.make(folder, store=FolderStore(store.root), made_at=SECOND, complete=True).snapshot
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
        # Complete: what follows clears the first of the two by hand, which gc never does to a snapshot an increment
        # builds on. (Left to the store, this one is an increment on that first, the one of the two whose folder
        # holds every file of it: tests/test_snapshot_decides.py)
        third = snapshot.make(rates, store=FolderStore(new.root), made_at=SECOND, complete=True).snapshot
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
