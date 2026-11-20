"""Two things that are no longer one: "the store has these bytes" and "this snapshot has its file".

Each snapshot holds its own copy of every file
(``docs_src/design/snapshots-and-increments.md``), so the same bytes sit in
several folders, and in several pipelines'. Two principles settle what
every question of the store means, after three reviews of the layout:

- Whole is a snapshot's own files, each where its record says it is. Where
  being wrong could lose or hide data it is asked of one snapshot and one
  asset whole, never file by file across snapshots, and by hash where the
  bytes are read anyway (``store move``, ``store import``).
- An asset of a pipeline is read from that pipeline's own snapshots alone:
  the one named, where it is in the store and whole, and the newest that is
  whole otherwise. ``store gc`` counts the same holders, so a read is
  handed the copy gc keeps.

Found by the third review (2026-11-20), each test here failed before.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lineage, lock, models, sharing, snapshot, transfer
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.gitcache import GitCache
from chartbook.multi_store import NamedStore, Stores
from chartbook.store import FolderStore, StoreError
from tests.fixtures import _git

OLDER, OLD, OLDISH, NOW, LATER, LAST = (
    "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z", "2026-02-01T09:15:00.000000Z",
    "2026-11-19T14:02:00.000000Z", "2026-11-19T15:02:00.000000Z", "2026-11-19T16:02:00.000000Z",
)


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


def _chart(folder: Path, text: str) -> None:
    (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n", encoding="utf-8", newline="\n")


def _pipeline(folder: Path, pipeline: str) -> Path:
    """A pipeline with a table and a chart that git ignores and a README it tracks; built and committed."""
    (folder / "_data").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": pipeline},
            "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text(f"# {pipeline}\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _table(folder, 3)
    _chart(folder, "one")
    _commit(folder)
    return folder


@pytest.fixture
def rates(work, store):
    return _pipeline(work / "rates", "acme/rates")


def _reader(folder: Path, key: str, path: str) -> Path:
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": {key: {"path": path}}}),
        encoding="utf-8", newline="\n",
    )
    return folder


def _folder_of(taken) -> Path:
    return Path(taken.path).parent.parent


def _lose(path: Path) -> None:
    """Take one file out of the store, more than an hour ago by its folder's time."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()
    then = path.parent.stat().st_mtime - 2 * 3600
    os.utime(path.parent, (then, then))
    store_module._found_whole.clear()


def _two_stores(store, there: Path) -> Stores:
    return Stores([
        NamedStore("here", str(store.root), FolderStore(store.root), create=True),
        NamedStore("there", str(there), FolderStore(there), create=True),
    ])


class TestAPinFromACloneThatWouldAddNothing:
    """It adds nothing only where one recorded snapshot of the pipeline holds every asset put, whole."""

    def test_a_complete_snapshot_is_written_where_each_file_is_whole_only_in_some_snapshot_or_other(self, work, store):
        upstream = work / "upstream"
        (upstream / "data" / "parts").mkdir(parents=True)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/upstream"}, "dataframes": {"parts": {"path": "./data/parts/", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        for year in (2020, 2021):
            pl.DataFrame({"year": [year]}).write_parquet(upstream / "data" / "parts" / f"{year}.parquet")
        _commit(upstream, "Two years")
        downstream = work / "downstream"
        downstream.mkdir()
        (downstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/downstream"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
            encoding="utf-8", newline="\n",
        )
        cache = GitCache(work / "gitcache")
        assert lock.pin(downstream, FolderStore(store.root), git_cache=cache).problems == []
        pl.DataFrame({"year": [2022]}).write_parquet(upstream / "data" / "parts" / "2022.parquet")
        _commit(upstream, "A third year")
        assert lock.update(downstream, store=FolderStore(store.root), git_cache=cache).problems == []
        made = sorted((store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json"))
        (newer,) = [record.parent.parent for record in made if (record.parent.parent / "data" / "parts" / "2022.parquet").is_file()]
        _lose(newer / "data" / "parts" / "2020.parquet")  # the newer loses a file the older still has
        # Upstream commits something that is no data, and the pin is moved again: the clone has every byte,
        # and each file is whole in one snapshot or the other, though no snapshot has the dataset whole
        (upstream / "README.md").write_text("# Upstream\n", encoding="utf-8", newline="\n")
        _commit(upstream, "A README")
        assert lock.update(downstream, store=FolderStore(store.root), git_cache=cache).problems == []
        store_module._found_whole.clear()
        (record,) = [r for r in lock.read_lock(downstream).assets.values() if r["id"].endswith(":parts")]
        fresh = FolderStore(store.root)
        assert fresh.holds_whole("acme/upstream", [record["content_hash"]])
        assert fresh.incomplete(record["content_hash"], record.get("size_bytes"), every=True, pipeline="acme/upstream") is None
        assert len(list((store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json"))) == 3
        files = [Path(path) for path in data.files("acme/upstream:parts", project_dir=downstream)]
        assert [path.name for path in files] == ["2020.parquet", "2021.parquet", "2022.parquet"]
        assert len({path.parents[2] for path in files}) == 1 and all(path.is_file() for path in files)
        # And gc is not held back for good: the one with the hole is itself to go once it is an hour old
        plan = lock.plan_gc(FolderStore(store.root), recent_seconds=0)
        assert plan.held_back == {} and newer in [_folder_of(taken) for taken, _ in plan.pinned_delete]


class TestStoreMoveWhereTheTargetsOwnCopyIsDamagedAtItsSize:
    def test_the_source_keeps_its_good_copy_and_the_move_says_which_file(self, rates, work, store):
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
        damaged = _folder_of(copies[OLD]) / "_data" / "treasury.parquet"
        good = damaged.read_bytes()
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(len(good)))  # the same size, other bytes: a sync cut short, a disk's fault
        with pytest.raises(StoreError) as stopped:
            transfer.move("acme/rates", stores(), "there", keep=False, route=False)
        said = str(stopped.value)
        assert said.startswith(
            f"The store at {FolderStore(target)} has the snapshot of acme/rates made {OLD} already, in "
            f"{_folder_of(copies[OLD]).name}, and not whole: _data/treasury.parquet is no longer what its record says"
        )
        assert said.endswith(
            "Nothing was removed from where it came from. If a sync is still bringing it, wait for the sync to finish "
            "and move again; `chartbook store verify` there lists everything missing or damaged."
        )
        assert (_folder_of(first) / "_data" / "treasury.parquet").read_bytes() == good
        assert len(snapshot.all_snapshots(FolderStore(store.root))) == 2


class TestAReadStopsAtItsPipeline:
    """An asset of a pipeline is never read from another pipeline's copy, whatever its bytes: gc does not keep that copy for it."""

    def test_the_same_table_in_another_pipeline_is_not_what_a_pinned_read_is_handed(self, rates, work, store):
        pinned = snapshot.make(rates, store=store, made_at=NOW).snapshot
        reader = _reader(work / "reader", "acme/rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        mirror = _pipeline(work / "mirror", "acme/mirror")  # publishes the same table, and later another
        assert (mirror / "_data" / "treasury.parquet").read_bytes() == (rates / "_data" / "treasury.parquet").read_bytes()
        old = snapshot.make(mirror, store=FolderStore(store.root), made_at=OLD).snapshot
        _table(mirror, 5)
        snapshot.make(mirror, store=FolderStore(store.root), made_at=NOW)
        assert data.path("acme/rates:treasury", project_dir=reader) == _folder_of(pinned) / "_data" / "treasury.parquet"
        _lose(_folder_of(pinned) / "_data" / "treasury.parquet")
        table = pinned.content()["treasury"]
        fresh = FolderStore(store.root)
        assert fresh.has(table) and not fresh.has(table, "acme/rates") and fresh.has(table, "acme/mirror")
        # Before gc and after it, the same answer: not in the store, which is true of the pipeline it is pinned from
        for _ in range(2):
            with pytest.raises(AssetNotPinnedError) as refused:
                data.path("acme/rates:treasury", project_dir=reader)
            assert "does not have it" in str(refused.value)
            assert CliRunner().invoke(main, ["store", "gc", "--yes"]).exit_code == 0
            store_module._found_whole.clear()
        # (gc keeps the other pipeline's old snapshot all the same: a note names bytes, not whose they are, so the
        # newest holder in each pipeline is kept. More than is needed, and never less.)
        assert _folder_of(old).is_dir()


class TestAVersionPinnedByItsLabel:
    """gc keeps, for a label a lockfile pins, the newest snapshot of the pipeline holding the version: the copy the read is handed."""

    def test_the_read_is_handed_the_copy_gc_keeps_for_it(self, work, store):
        forecast = work / "forecast"
        (forecast / "_models").mkdir(parents=True)
        (forecast / "README.md").write_text("# Forecast\n", encoding="utf-8", newline="\n")
        (forecast / ".gitignore").write_text("/_models/\n/chartbook.lock\n", encoding="utf-8", newline="\n")

        def manifest(aliases=None) -> None:
            model = {"path": "./_models/m.json", "docs": "A small model."}
            if aliases is not None:
                model["aliases"] = aliases
            (forecast / "chartbook.toml").write_text(
                tomli_w.dumps({"project": {"id": "acme/forecast"}, "models": {"m": model}}), encoding="utf-8", newline="\n"
            )

        manifest()
        (forecast / "_models" / "m.json").write_bytes(b"weights-1")
        _commit(forecast)
        first = snapshot.make(forecast, store=store, made_at=OLDER)
        ((_, version),) = first.new_versions
        (forecast / "README.md").write_text("# Forecast, a word more\n", encoding="utf-8", newline="\n")
        _commit(forecast)
        second = snapshot.make(forecast, store=FolderStore(store.root), made_at=OLD)  # holds the first version again
        (forecast / "_models" / "m.json").write_bytes(b"weights-2")
        manifest({"champion": version})
        _commit(forecast)
        third = snapshot.make(forecast, store=FolderStore(store.root), made_at=OLDISH)
        serve = _reader(work / "serve", "forecast", "../forecast")
        assert lock.pin(serve, FolderStore(store.root)).problems == []
        ((_, challenger),) = third.new_versions
        manifest({"champion": challenger})  # the owner moves the label on; the pipeline that serves it has not pinned again
        _commit(forecast)
        assert snapshot.make(forecast, store=FolderStore(store.root), made_at=NOW).made
        before = models.path("forecast:m@champion", project_dir=serve)
        assert before == _folder_of(second.snapshot) / "_models" / "m.json" and before.read_bytes() == b"weights-1"
        assert models.path(f"forecast:m@{version}", project_dir=serve) == before
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert not _folder_of(first.snapshot).exists()  # the older holder went
        assert before.exists() and models.path("forecast:m@champion", project_dir=serve) == before


class TestASnapshotSentToTwoStores:
    """The snapshot a run stands on is whole in every store the run sends it to: a hole in another store's copy is a hole."""

    @staticmethod
    def _both(store, there):
        return {"store": _two_stores(store, there), "store_names": ["here", "there"]}

    @pytest.fixture
    def holed(self, rates, work, store):
        """A snapshot in two stores, whose copy in the second has lost its table for good: that copy, and the second store's folder."""
        there = work / "there"
        assert snapshot.make(rates, **self._both(store, there), made_at=NOW).made
        (copy,) = snapshot.all_snapshots(FolderStore(there))
        _lose(_folder_of(copy) / "_data" / "treasury.parquet")
        return copy, there

    def test_a_hole_in_the_second_stores_copy_makes_a_new_snapshot_that_both_hold_whole(self, rates, store, holed):
        copy, there = holed
        again = snapshot.make(rates, **self._both(store, there), made_at=LATER)
        assert again.made and again.snapshot.made_at == LATER
        lacking, files, where = again.not_whole
        assert (Path(lacking.path), files, str(where)) == (Path(copy.path), ["_data/treasury.parquet"], str(FolderStore(there)))
        for root in (store.root, there):
            (new,) = [taken for taken in snapshot.all_snapshots(FolderStore(root)) if taken.made_at == LATER]
            assert FolderStore(root).verify_snapshot(new.path) == []  # each of its own files read and hashed
        assert not (_folder_of(copy) / "_data" / "treasury.parquet").exists()  # and that one is left as it is

    def test_the_run_after_that_stands_on_the_new_one_and_none_fails(self, rates, store, holed):
        """The case the third review brought: nothing changes in the pipeline, and no run stops, at once or for ever."""
        _, there = holed
        made = [snapshot.make(rates, **self._both(store, there), made_at=made_at) for made_at in (LATER, LAST)]
        assert [report.made for report in made] == [True, False]
        assert made[1].snapshot.made_at == LATER and made[1].not_whole is None
        assert [len(snapshot.all_snapshots(FolderStore(root))) for root in (store.root, there)] == [2, 2]

    def test_a_store_with_no_record_of_it_is_sent_it_whole_and_no_new_one_is_made(self, rates, work, store):
        """A store added to the catalog later: the snapshot stood on is written there, as before."""
        first = snapshot.make(rates, store=store, made_at=NOW).snapshot
        there = work / "there"
        report = snapshot.make(rates, **self._both(store, there), made_at=LATER)
        assert not report.made and Path(report.snapshot.path) == Path(first.path) and report.not_whole is None
        (copy,) = snapshot.all_snapshots(FolderStore(there))
        assert copy.made_at == NOW and FolderStore(there).verify_snapshot(copy.path) == []

    def test_an_older_one_whole_in_both_is_stood_on(self, rates, work, store):
        there = work / "there"
        old = snapshot.make(rates, **self._both(store, there), made_at=OLD).snapshot
        table = _folder_of(old) / "_data" / "treasury.parquet"
        kept = table.read_bytes()
        _lose(table)  # the first store's copy lacks its table, so the next run makes a new one, whole in both
        assert snapshot.make(rates, **self._both(store, there), made_at=NOW).made
        table.write_bytes(kept)  # the sync brings it after all: the older one is whole in both again
        store_module._found_whole.clear()
        (newer,) = [taken for taken in snapshot.all_snapshots(FolderStore(there)) if taken.made_at == NOW]
        _lose(_folder_of(newer) / "_data" / "treasury.parquet")  # and the newer one loses its table in the second
        report = snapshot.make(rates, **self._both(store, there), made_at=LATER)
        assert not report.made and report.snapshot.made_at == OLD and report.not_whole is None
        assert [len(snapshot.all_snapshots(FolderStore(root))) for root in (store.root, there)] == [2, 2]

    def test_only_a_store_the_run_writes_to_is_asked_and_once(self, rates, store, holed, monkeypatch):
        """With one store nothing else is asked; each other store costs one `find` and one `holes_of`."""
        _, there = holed
        asked: list = []
        find, holes_of = snapshot.find, FolderStore.holes_of

        def finding(where, *args, **kwargs):
            asked.append(("find", str(where)))
            return find(where, *args, **kwargs)

        def asking(self, record):
            asked.append(("holes_of", str(self)))
            return holes_of(self, record)

        monkeypatch.setattr(snapshot, "find", finding)
        monkeypatch.setattr(FolderStore, "holes_of", asking)
        here, second = str(FolderStore(store.root)), str(FolderStore(there))
        # One store, given as it is, or as the one store of a catalog that the run writes to
        for one in ({"store": FolderStore(store.root)}, {"store": _two_stores(store, there), "store_names": ["here"]}):
            asked.clear()
            assert not snapshot.make(rates, **one, made_at=LATER).made
            assert asked.count(("holes_of", here)) == 1 and not [what for what, where in asked if where == second]
        asked.clear()
        assert snapshot.make(rates, **self._both(store, there), made_at=LATER).made
        assert [what for what, where in asked if where == second] == ["find", "holes_of"]

    def test_the_line_names_the_other_store_and_the_file(self, rates, work, store, monkeypatch):
        from chartbook.cli import _when

        there = work / "there"
        for root in (store.root, there):
            root.mkdir()
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        home = config.get_global_config_dir()
        home.mkdir(parents=True, exist_ok=True)
        (home / "catalog.toml").write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {"here": {"url": str(store.root)}, "there": {"url": str(there)}}}),
            encoding="utf-8", newline="\n",
        )
        monkeypatch.chdir(rates)
        typed = ["snapshot", "--store", "here", "--store", "there"]
        first = CliRunner().invoke(main, typed)
        assert first.exit_code == 0, first.output
        (copy,) = snapshot.all_snapshots(FolderStore(there))
        _lose(_folder_of(copy) / "_data" / "treasury.parquet")
        again = CliRunner().invoke(main, typed)
        assert again.exit_code == 0, again.output
        assert (
            f"  The same files as the snapshot made {_when(copy.made_at)} ({_folder_of(copy).name}), which lacks "
            f"_data/treasury.parquet in the store at {FolderStore(there)}: this one is whole, and that one is left as it is."
        ) in again.output.splitlines()
        third = CliRunner().invoke(main, typed)
        assert third.exit_code == 0 and "No new snapshot" in third.output and "which lacks" not in third.output, third.output

    def test_a_copy_there_with_other_bytes_at_its_size_is_said_and_nothing_is_written_over_it(self, rates, store, work):
        """What a size cannot tell is found when the copy is read and hashed: which store, which snapshot, which file, and the way out."""
        there = work / "there"
        assert snapshot.make(rates, **self._both(store, there), made_at=NOW).made
        (copy,) = snapshot.all_snapshots(FolderStore(there))
        damaged = _folder_of(copy) / "_data" / "treasury.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        before = sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file())
        with pytest.raises(snapshot.NotInEveryStore) as said:
            snapshot.make(rates, **self._both(store, there), made_at=LATER)
        assert str(said.value).startswith(
            f"The store at {FolderStore(there)} has the snapshot of acme/rates made {NOW} already, in "
            f"{_folder_of(copy).name}, and not whole: _data/treasury.parquet is no longer what its record says"
        )
        assert str(said.value).endswith(
            f"The snapshot in {FolderStore(store.root)} is whole. If a sync is still bringing the file there, it arrives "
            f"with the sync. If it is lost for good, that store's copy stays as it is until a later snapshot of "
            f"acme/rates is sent there, and then goes with `chartbook store gc` there once nothing keeps it."
        )
        assert sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file()) == before


class TestTheNewestWholeMatchIsStoodOn:
    """"No new snapshot" stands on the newest snapshot of the same files that is whole; a new one is made only if none is."""

    def test_one_dated_a_little_ahead_and_holed_does_not_make_every_run_a_new_snapshot(self, rates, store):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        def at(minutes: float) -> str:
            return (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        theirs = snapshot.make(rates, store=store, made_at=at(5)).snapshot  # made on a machine whose clock is ahead
        _lose(_folder_of(theirs) / "_data" / "treasury.parquet")  # its sync has not brought the table yet
        made = [snapshot.make(rates, store=FolderStore(store.root), made_at=at(minutes)).made for minutes in (0, 1, 2, 3)]
        assert made == [True, False, False, False]

    def test_an_older_whole_one_of_the_same_files_is_stood_on(self, rates, store):
        """This machine's own snapshot is whole; a colleague's of the same files is arriving. No third copy of everything."""
        mine = snapshot.make(rates, store=store, made_at=OLD).snapshot
        theirs = json.loads(Path(mine.path).read_text(encoding="utf-8"))
        pending = FolderStore(store.root).begin("acme/rates", mine.commit, NOW, base=rates)
        theirs["made_at"] = NOW
        parts = [*theirs["records"], theirs["index"], theirs["documents"]]
        for part in parts:
            for entry in part["stored"]["files"]:
                pending.put(_folder_of(mine).joinpath(*entry["path"].split("/")), place=entry["path"])
                entry["kept_in"] = pending.name
        record = pending.write(theirs)
        _lose(Path(record).parent.parent / "_data" / "treasury.parquet")
        report = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert not report.made and report.snapshot.path == mine.path and report.not_whole is None


class TestWhatTheNewWholeOneSaysOfItsBuild:
    def test_it_still_says_a_run_built_these_bytes(self, rates, store):
        """The one that lacks a file was made by a run; `chartbook snapshot` then makes the whole one of the same bytes and pins."""
        built = snapshot.make(rates, store=store, made_at=NOW, built_by_run=True).snapshot
        assert built.built_by_run
        _lose(_folder_of(built) / "_data" / "treasury.parquet")
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=LATER)
        assert again.made and again.not_whole is not None and again.snapshot.built_by_run


class TestTheWayOutGcNames:
    """Of the snapshot that lacks a file: the plan's own reason for keeping it, and the way out for that reason."""

    def test_one_a_tag_keeps_is_not_said_to_be_pinned(self, rates, store):
        snapshot.make(rates, store=store, made_at=OLDER)
        _chart(rates, "two")
        tagged = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        _git(rates, "tag", "v1")
        (rates / "README.md").write_text("# Rates, on\n", encoding="utf-8", newline="\n")
        _commit(rates)
        _table(rates, 4)
        snapshot.make(rates, store=FolderStore(store.root), made_at=NOW)
        _lose(_folder_of(tagged) / "_data" / "treasury.parquet")
        result = CliRunner().invoke(main, ["store", "gc", "--yes", "--forget-missing"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        said = (
            f"Nothing of acme/rates is removed: its snapshot {_folder_of(tagged).name} lacks _data/treasury.parquet, and "
            f"stays because it is the newest a branch or tag can pin from."
        )
        assert said in lines and lines[lines.index(said) + 1] == (
            "  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists everything "
            "missing. If it is lost for good, that snapshot goes once a newer snapshot takes its place for that name, or "
            "with `chartbook store gc --aggressive`, which lets names keep nothing."
        )
        assert "pins it" not in result.output
        # And that way out works: with names keeping nothing, it is itself to go, and holds nothing back
        result = CliRunner().invoke(main, ["store", "gc", "--yes", "--aggressive"])
        assert result.exit_code == 0 and not _folder_of(tagged).exists(), result.output

    def test_every_reason_the_plan_gives_has_a_way_out_of_its_own(self):
        """The reasons are taken from the plan's source, so that one added later with no way out fails here."""
        import inspect
        import re

        from chartbook.cli import _when_it_goes

        source = "".join(inspect.getsource(function) for function in (
            snapshot.plan_removals, snapshot._keep_lineage, snapshot._keep_repositories_whole, snapshot._holding_labelled,
            lock._plan_gc, lock._keep_what_only_they_hold, lock._plan_pinned,
        ))
        found = {lock.HELD_BACK, lock.HELD_BACK_OTHER_BYTES, lock.BUILT_ON}
        for pattern in (
            r'\bwhy = f?"([^"]+)"',
            r'keep_noted\(root, "([^"]+)"',
            r'\.append\(\(\w+, f?"([^"]+)"\)\)',
            r'setdefault\([^,]+, f?"([^"]+)"\)',
            r'\bkeep\(\S+, "([^"]+)"\)',
        ):
            found.update(re.findall(pattern, source))
        # What a plan says of one that goes is no reason to stay
        reasons = sorted(re.sub(r"\{[^}]*\}", "7", why) for why in found if not why.startswith(("nothing pins", "no lockfile pins")))
        ways = {
            "a lockfile pins it": "once no lockfile pins it",
            "a lockfile that cannot be found pins it": "--forget-missing",
            "a lockfile not read here, another machine's, pins it": "that machine's lockfile",
            "it is the newest of its pipeline": "`chartbook run` in its folder",
            "it is the newest a branch or tag can pin from": "--aggressive",
            "a label points at a version in it": "--aggressive",
            "it holds a version of 7, which is kept (`keep = true` in its chartbook.toml)": "no longer marked `keep = true`",
            "it was made in the last 7 days": "once it is older than that",
            "a snapshot that is kept was made from it": "without `--keep-lineage`",
            "a snapshot that is kept was made from a label pointing at a version in it": "without `--keep-lineage`",
            "it names its repository's address and first commit together, which joins its snapshots": "ties to their repository",
            "it names the address of a kept snapshot's first commit": "ties to their repository",
            "it is the newest that names its repository": "once a newer snapshot of its pipeline names its repository",
            lock.HELD_BACK: "is whole again, or has gone",
            lock.BUILT_ON: "once the increments that build on it have gone",
        }
        assert set(ways) <= set(reasons) and len(reasons) >= 20, reasons
        for why, way in ways.items():
            assert way in _when_it_goes(why), why
        assert [why for why in reasons if _when_it_goes(why) == _when_it_goes("")] == []

    @pytest.fixture
    def pinned_and_holed(self, rates, work, store):
        """Three snapshots of rates: one old enough to go, one a reader pins, which has lost its table for good, and a newer one."""
        snapshot.make(rates, store=store, made_at=OLDER)
        _chart(rates, "two")
        pinned = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        reader = _reader(work / "reader", "acme/rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        _chart(rates, "three")
        snapshot.make(rates, store=FolderStore(store.root), made_at=OLDISH)
        _lose(_folder_of(pinned) / "_data" / "treasury.parquet")
        return pinned, reader

    @staticmethod
    def _said(result, pinned, why: str, way: str) -> None:
        assert result.exit_code == 0 and _folder_of(pinned).is_dir(), result.output
        lines = result.output.splitlines()
        first = f"Nothing of acme/rates is removed: its snapshot {_folder_of(pinned).name} lacks _data/treasury.parquet, and stays because {why}."
        assert first in lines and lines[lines.index(first) + 1].endswith(f"If it is lost for good, that snapshot goes {way}."), result.output

    def test_one_a_lockfile_pins_goes_once_the_pin_is_moved(self, pinned_and_holed, store):
        pinned, reader = pinned_and_holed
        self._said(
            CliRunner().invoke(main, ["store", "gc", "--yes"]), pinned, "a lockfile pins it",
            "once no lockfile pins it: `chartbook pin --update` in the pipeline that does moves its pin to a newer snapshot",
        )
        assert lock.update(reader, store=FolderStore(store.root)).problems == []  # the way out, carried out
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and not _folder_of(pinned).exists() and "Nothing of" not in result.output, result.output

    def test_one_a_lost_lockfile_pins_goes_with_forget_missing(self, pinned_and_holed, store):
        import shutil

        pinned, reader = pinned_and_holed
        shutil.rmtree(reader)
        self._said(
            CliRunner().invoke(main, ["store", "gc", "--yes"]), pinned, "a lockfile that cannot be found pins it",
            "with `chartbook store gc --forget-missing`, which lets go of what a lockfile that cannot be found pinned",
        )
        result = CliRunner().invoke(main, ["store", "gc", "--yes", "--forget-missing"])
        assert result.exit_code == 0 and not _folder_of(pinned).exists(), result.output

    def test_the_newest_goes_once_a_newer_one_is_made(self, rates, store):
        snapshot.make(rates, store=store, made_at=OLDER)
        _chart(rates, "two")
        newest = snapshot.make(rates, store=FolderStore(store.root), made_at=OLD).snapshot
        _lose(_folder_of(newest) / "_data" / "treasury.parquet")
        self._said(
            CliRunner().invoke(main, ["store", "gc", "--yes"]), newest, "it is the newest of its pipeline",
            "once a newer snapshot of its pipeline is made (`chartbook run` in its folder) and nothing else keeps it",
        )
        _table(rates, 4)
        assert snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).made  # the way out, carried out
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and not _folder_of(newest).exists() and "Nothing of" not in result.output, result.output


class TestWhatGcSaysItFreed:
    def test_a_snapshot_a_pin_made_is_listed_asked_about_and_counted(self, work, store, monkeypatch):
        """Only a snapshot a pin made goes: the dry run lists it, "n" removes nothing, "y" removes it, and the last line agrees with the disk."""
        from chartbook.cli import _format_bytes, _what_gc_would_clear

        upstream = work / "upstream"
        (upstream / "data").mkdir(parents=True)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/upstream"}, "dataframes": {
                "steady": {"path": "./data/steady.parquet", "docs": "d"},
                "moving": {"path": "./data/moving.parquet", "docs": "d"},
            }}),
            encoding="utf-8", newline="\n",
        )
        pl.DataFrame({"day": list(range(5000))}).write_parquet(upstream / "data" / "steady.parquet")
        pl.DataFrame({"day": [0]}).write_parquet(upstream / "data" / "moving.parquet")
        _commit(upstream, "One")
        one = work / "one"
        one.mkdir()
        (one / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/one"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
            encoding="utf-8", newline="\n",
        )
        cache = GitCache(work / "gitcache")
        assert lock.pin(one, FolderStore(store.root), git_cache=cache).problems == []
        pl.DataFrame({"day": [0, 1]}).write_parquet(upstream / "data" / "moving.parquet")
        _commit(upstream, "Two")
        assert lock.update(one, store=FolderStore(store.root), git_cache=cache).problems == []
        both = [p.parent.parent for p in (store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json")]
        first, second = sorted(both, key=lambda folder: (folder / "data" / "moving.parquet").stat().st_size)
        freed = _format_bytes(sum(p.stat().st_size for p in first.rglob("*") if p.is_file() and p.name != "snapshot.json"))
        _an_hour_on(monkeypatch)
        # The line a snapshot ends with says it too
        assert _what_gc_would_clear(FolderStore(store.root)) == (
            f"`chartbook store gc` would clear 1 snapshot(s) a pin made from a repository, whose files no lockfile needs "
            f"from them, freeing {freed}."
        )
        dry = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert dry.exit_code == 0 and first.exists(), dry.output
        lines = dry.output.splitlines()
        assert f"Would remove 1 snapshot(s) a pin made from a repository and 1 object(s) that nothing names, {freed}:" in lines
        (listed,) = [line for line in lines if line.startswith("  acme/upstream at ")]
        assert ", which a pin made " in listed and listed.endswith(": no lockfile pins what it alone holds")
        no = CliRunner().invoke(main, ["store", "gc"], input="n\n")
        assert no.exit_code == 0 and listed in no.output.splitlines() and "Remove them?" in no.output, no.output
        assert no.output.splitlines()[-1] == "Nothing was removed." and first.exists()
        yes = CliRunner().invoke(main, ["store", "gc"], input="y\n")
        assert yes.exit_code == 0 and not first.exists() and (second / "data" / "steady.parquet").is_file(), yes.output
        assert yes.output.splitlines()[-1] == (
            f"Removed 0 snapshot(s), 1 snapshot(s) a pin made from a repository and 1 object(s), {freed}."
        )
        assert CliRunner().invoke(main, ["store", "gc"]).output.splitlines()[-1] == "Nothing to remove."

    def test_an_object_whose_file_was_not_there_is_not_said_to_be_kept(self, rates, store):
        """A snapshot that is to go has lost a file only it had. Its folder goes, and nothing names or uses that object."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        (rates / "README.md").write_text("# Rates, on\n", encoding="utf-8", newline="\n")
        _commit(rates, "A README")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=NOW).snapshot
        _lose(_folder_of(first) / "_chartbook" / "index.json")  # the first's own index: no other snapshot has it
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0, result.output
        assert not _folder_of(first).exists() and _folder_of(second).is_dir()
        assert "Kept after all" not in result.output and result.output.splitlines()[-1].startswith("Removed 1 snapshot(s) and ")


class TestStoreImportWhereTheStoresOwnSnapshotLacksAFile:
    @pytest.fixture
    def exported(self, rates, work, store):
        """The only snapshot of rates, pinned by a reader and exported whole; then its table is lost from the store for good."""
        taken = snapshot.make(rates, store=store, made_at=OLD).snapshot
        reader = _reader(work / "reader", "acme/rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        out = work / "for-me"
        sharing.export(FolderStore(store.root), "acme/rates", out, None)
        good = (_folder_of(taken) / "_data" / "treasury.parquet").read_bytes()
        _lose(_folder_of(taken) / "_data" / "treasury.parquet")
        return taken, reader, out, good

    def test_it_is_not_said_to_be_there_and_nothing_is_imported_over_it(self, exported, store):
        taken, _, out, _ = exported
        done = sharing.import_snapshots(FolderStore(store.root), out)
        assert done.there == [] and done.copied == []
        ((what, why),) = done.refused
        assert what == f"acme/rates at {taken.commit[:7]}, made {OLD}"
        assert why == (
            f"the store has it already, in {_folder_of(taken).name}, and not whole: _data/treasury.parquet is not in the "
            f"store. Nothing was imported over it. If a sync is still bringing the file, import again when it has. If the "
            f"file is lost, remove that snapshot's folder, {_folder_of(taken)}, and import again: what is imported holds "
            f"it whole"
        )
        assert not (_folder_of(taken) / "_data" / "treasury.parquet").exists()
        result = CliRunner().invoke(main, ["store", "import", str(out)])
        assert result.exit_code == 1 and f"Refused: {what}: {why}" in result.output.replace("\n", "")

    def test_the_way_out_it_names_can_be_carried_out(self, exported, store, monkeypatch):
        """`store gc` never removes the newest snapshot of a pipeline: the folder is removed as a person would, and the import brings it whole."""
        import shutil

        taken, reader, out, good = exported
        for typed in (["store", "gc", "--yes"], ["store", "gc", "--yes", "--aggressive", "--keep-days", "0", "--forget-missing"]):
            assert CliRunner().invoke(main, typed).exit_code == 0 and _folder_of(taken).is_dir()  # no gc lets go of it

        def writable(function, path, _):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)  # what a store keeps is read-only
            function(path)

        shutil.rmtree(_folder_of(taken), onerror=writable)
        store_module._found_whole.clear()
        done = sharing.import_snapshots(FolderStore(store.root), out)
        assert done.refused == [] and done.copied == [("acme/rates", taken.commit, OLD)]
        # And the store is as it was before the file was lost: every snapshot whole, the pin read, nothing for gc to say
        assert FolderStore(store.root).verify() == []
        handed = Path(data.path("acme/rates:treasury", project_dir=reader))
        assert handed == _folder_of(taken) / "_data" / "treasury.parquet" and handed.read_bytes() == good
        monkeypatch.chdir(reader)
        for typed in (["pin", "--check"], ["store", "verify"], ["store", "gc", "--dry-run"]):
            result = CliRunner().invoke(main, typed)
            assert result.exit_code == 0 and "Nothing of" not in result.output, (typed, result.output)


class TestAFolderWithBothLayoutsAndNoStoreJson:
    def test_it_is_refused_as_any_folder_with_both_is(self, rates, work, store, monkeypatch):
        taken = snapshot.make(rates, store=store, made_at=NOW).snapshot
        reader = _reader(work / "reader", "acme/rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        monkeypatch.chdir(reader)
        (store.root / "store.json").unlink()
        of_0_5 = store.root / "pipelines" / "acme+other" / "2026-11-16T091500Z_aaaaaaaaaaaa"
        of_0_5.mkdir(parents=True)
        with pytest.raises(StoreError) as refused:
            FolderStore(store.root).records()
        assert str(refused.value) == (
            f"The store at {store} has no store.json, and holds snapshots of both layouts: laid out as ChartBook 0.5 "
            f"laid them out under pipelines/ ({of_0_5}), and as this version lays them out under snapshots/ "
            f"({_folder_of(taken)}). It is neither read nor written as it is. To part the two, the store of 0.5 staying "
            f"here, where every machine expects it: move snapshots/ and _chartbook/ out of it into a folder of their "
            f'own, beside a store.json that holds {{"schema": "chartbook/store/v3"}}, which is then a store of this '
            f'version\'s layout; and see that the store.json here holds {{"schema": "chartbook/store/v2"}}.'
        )
        for arguments in (["store", "verify"], ["store", "ls"], ["store", "info"], ["store", "gc", "--dry-run"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exception is None or isinstance(result.exception, SystemExit), (arguments, repr(result.exception))
            assert result.exit_code == 1 and "holds snapshots of both layouts" in result.output, (arguments, result.output)
        # Every listing of `chartbook ls`, as click lists them, so that one added later is covered: none ends in a
        # traceback, and each that reads the store says the plain error and exits 1
        listings = [["ls"], ["ls", "--json"]] + [["ls", name] for name in sorted(main.commands["ls"].commands)]
        assert {"pipelines", "dataframes", "charts", "stores", "versions"} <= {arguments[-1] for arguments in listings}
        said = []
        for arguments in listings:
            result = CliRunner().invoke(main, arguments)
            assert result.exception is None or isinstance(result.exception, SystemExit), (arguments, repr(result.exception))
            assert result.exit_code in (0, 1), (arguments, result.output)
            if result.exit_code:
                assert "Error: " in result.output and "holds snapshots of both layouts" in result.output, (arguments, result.output)
                said.append(arguments[-1])
        assert {"ls", "--json", "pipelines", "dataframes", "charts", "versions"} <= set(said), said


class TestAStoreThatIsRefusedAmongSeveral:
    def test_store_info_exits_1_and_ls_versions_says_it_plainly(self, rates, work, store, monkeypatch):
        """One of a catalog's stores has a store.json of another layout over its snapshots: said, with exit 1, and no traceback."""
        snapshot.make(rates, store=store, made_at=NOW)
        (store.root / "store.json").write_text('{"schema": "chartbook/store/v2"}\n', encoding="utf-8", newline="\n")
        other = work / "other"
        other.mkdir()
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        home = config.get_global_config_dir()
        home.mkdir(parents=True, exist_ok=True)
        (home / "catalog.toml").write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {"other": {"url": str(other)}, "mixed": {"url": str(store.root)}}}),
            encoding="utf-8", newline="\n",
        )
        info = CliRunner().invoke(main, ["store", "info"])
        assert info.exit_code == 1 and "  Not read: The store at" in info.output and "a snapshots/ folder that holds" in info.output
        listed = CliRunner().invoke(main, ["ls", "versions"])
        assert listed.exception is None or isinstance(listed.exception, SystemExit), repr(listed.exception)
        assert listed.exit_code == 1 and listed.output.startswith("Error: The store at") and "a snapshots/ folder that holds" in listed.output


class TestWhatLineageCountsAsThere:
    """`chartbook lineage` asks each snapshot's own pipeline: another pipeline's copy of the same bytes is not what a read is handed."""

    @pytest.fixture
    def pinned(self, rates, work, store):
        """rates, pinned by a reader, and a mirror that publishes the same table: the pinned snapshot, and the reader's folder."""
        taken = snapshot.make(rates, store=store, made_at=NOW).snapshot
        reader = _reader(work / "reader", "acme/rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        snapshot.make(_pipeline(work / "mirror", "acme/mirror"), store=FolderStore(store.root), made_at=NOW)
        assert lineage.walk(reader, FolderStore(store.root), rehash=True).gaps() == []
        return taken, reader

    def test_a_file_lost_from_its_pipeline_is_a_gap_though_another_pipeline_has_the_bytes(self, pinned, store):
        taken, reader = pinned
        _lose(_folder_of(taken) / "_data" / "treasury.parquet")
        table = taken.content()["treasury"]
        assert FolderStore(store.root).has(table) and not FolderStore(store.root).has(table, "acme/rates")
        gaps = [(node.pipeline, said) for node, said in lineage.walk(reader, FolderStore(store.root)).gaps()]
        assert ("acme/rates", f"holds {table[:19]}…, which the store does not have") in gaps, gaps

    def test_a_damaged_copy_is_found_though_another_pipeline_has_the_bytes_intact(self, pinned, store):
        taken, reader = pinned
        damaged = _folder_of(taken) / "_data" / "treasury.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))  # the same size, other bytes
        store_module._found_whole.clear()
        assert lineage.walk(reader, FolderStore(store.root)).gaps() == []  # nothing is read without --rehash
        ((node, said),) = lineage.walk(reader, FolderStore(store.root), rehash=True).gaps()
        assert node.pipeline == "acme/rates" and "which is not what its name says" in said


def _an_hour_on(monkeypatch) -> None:
    """Everything in the store was put there two hours ago, as `store gc` asks it: nothing is spared for being new."""
    monkeypatch.setattr(FolderStore, "age_of", lambda self, content_hash, now=None: 2.0 * lock.RECENT_SECONDS)


class TestGcReadsTheCopyAReadIsLeftWith:
    """A snapshot that holds a pinned asset goes only when one of its pipeline that stays holds that asset intact, read and hashed."""

    @pytest.fixture
    def pinned_then_owned(self, work, store, monkeypatch):
        """A `git` dependency pinned from its clone; then its owner, on this machine, commits a README and snapshots the same table."""
        upstream = work / "upstream"
        (upstream / "data").mkdir(parents=True)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/upstream"}, "dataframes": {"steady": {"path": "./data/steady.parquet", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        pl.DataFrame({"day": list(range(5000))}).write_parquet(upstream / "data" / "steady.parquet")
        _commit(upstream, "One")
        one = work / "one"
        one.mkdir()
        (one / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/one"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
            encoding="utf-8", newline="\n",
        )
        assert lock.pin(one, FolderStore(store.root), git_cache=GitCache(work / "gitcache")).problems == []
        (pinned,) = [p.parent.parent for p in (store.root / "snapshots" / "acme+upstream").glob("*/_chartbook/snapshot.json")]
        (upstream / "README.md").write_text("# Upstream\n", encoding="utf-8", newline="\n")
        _commit(upstream, "A README")
        owners = snapshot.make(upstream, store=FolderStore(store.root), made_at=OLD).snapshot
        _an_hour_on(monkeypatch)
        return one, pinned, owners, (upstream / "data" / "steady.parquet").read_bytes()

    def test_the_pin_made_copy_stays_while_the_owners_has_other_bytes_at_its_size(self, pinned_then_owned, store):
        one, pinned, owners, good = pinned_then_owned
        assert Path(data.path("acme/upstream:steady", project_dir=one)) == pinned / "data" / "steady.parquet"
        damaged = _folder_of(owners) / "data" / "steady.parquet"
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(len(good)))  # the same size, other bytes: no size tells
        store_module._found_whole.clear()
        said = [
            f"Nothing of acme/upstream is removed: in its snapshot {_folder_of(owners).name}, data/steady.parquet is no "
            f"longer what its record says (now sha256:{hashlib.sha256(bytes(len(good))).hexdigest()}), and it stays because "
            f"it is the newest of its pipeline.",
            "  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists everything "
            "missing. If it is lost for good, that snapshot goes once a newer snapshot of its pipeline is made "
            "(`chartbook run` in its folder) and nothing else keeps it.",
        ]
        for typed in (["store", "gc", "--dry-run"], ["store", "gc", "--yes"]):
            result = CliRunner().invoke(main, typed)
            assert result.exit_code == 0 and pinned.is_dir(), result.output
            lines = result.output.splitlines()
            assert lines[lines.index(said[0]):][:2] == said and lines[-1] == "Nothing to remove.", result.output
        store_module._found_whole.clear()
        assert Path(data.path("acme/upstream:steady", project_dir=one)).read_bytes() == good

    def test_with_the_owners_copy_intact_it_goes_and_the_read_is_handed_the_owners(self, pinned_then_owned, store):
        one, pinned, owners, good = pinned_then_owned
        result = CliRunner().invoke(main, ["store", "gc", "--yes"])
        assert result.exit_code == 0 and not pinned.exists() and "Nothing of" not in result.output, result.output
        store_module._found_whole.clear()
        after = Path(data.path("acme/upstream:steady", project_dir=one))
        assert after == _folder_of(owners) / "data" / "steady.parquet" and after.read_bytes() == good

    def test_only_a_plan_that_can_remove_reads_and_each_copy_once(self, pinned_then_owned, store, monkeypatch):
        """The line a snapshot ends with makes a plan of the whole store, and reads nothing."""
        from chartbook.cli import _what_gc_would_clear

        one, pinned, owners, _ = pinned_then_owned
        read: list = []
        verify = FolderStore.verify_snapshot

        def reading(self, record, content_hashes=(), only=False):
            read.append((Path(record), list(content_hashes), only))
            return verify(self, record, content_hashes, only)

        monkeypatch.setattr(FolderStore, "verify_snapshot", reading)
        monkeypatch.setattr(store_module, "what_is_wrong_in", lambda *a, **k: read.append("hashed") or [])
        plan = lock.plan_gc(FolderStore(store.root))
        assert [_folder_of(taken) for taken, _ in plan.pinned_delete] == [pinned] and not plan.hashed
        assert _what_gc_would_clear(FolderStore(store.root)) is not None and read == []
        plan = lock.plan_gc(FolderStore(store.root), hashed=True)
        table = owners.content()["steady"]
        assert read == [(Path(owners.path), [table], True), "hashed"]
        assert [_folder_of(taken) for taken, _ in plan.pinned_delete] == [pinned] and plan.not_intact == set()


class TestARecordThatNamesWhatItGivesNoPlaceFor:
    """A snapshot is not whole by what its record passes over: a hash it names with no place this machine follows is a hole."""

    @staticmethod
    def _stores(store, target):
        return Stores([
            NamedStore("here", str(store.root), FolderStore(store.root)),
            NamedStore("there", str(target), FolderStore(target), create=True),
        ])

    @pytest.fixture
    def moved(self, rates, work, store):
        """rates in two stores; the target's record says nothing of where the table is, and the table is not in its folder."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        target = work / "target"
        transfer.move("acme/rates", self._stores(store, target), "there", keep=True, route=False)
        (copy,) = snapshot.all_snapshots(FolderStore(target))
        record = Path(copy.path)
        document = json.loads(record.read_text(encoding="utf-8"))
        (table,) = [part for part in document["records"] if part["id"].endswith("treasury")]
        del table["stored"]  # as another version might write it, or a hand
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        _lose(_folder_of(copy) / "_data" / "treasury.parquet")
        store_module._read_records.clear()
        return first, copy, target

    def test_it_is_a_hole_for_every_question_of_whole(self, moved):
        first, copy, target = moved
        table = first.content()["treasury"]
        there = FolderStore(target)
        assert there.holes_of(copy.path) == [f"{table[:19]}… (its record does not say where it is)"]
        assert not there.holds_whole("acme/rates", [table]) and not there.has(table, "acme/rates")
        (problem,) = there.verify_snapshot(copy.path, first.hashes())
        assert problem.content_hash == table and problem.message == f"its record does not say where {table[:19]}… is"
        # A hash the record does not name at all is no asset of it
        other = "sha256:" + "0" * 64
        assert [p.message for p in there.verify_snapshot(copy.path, [other], only=True)] == [f"its record does not say where {other[:19]}… is"]

    def test_store_move_removes_nothing_from_the_source(self, moved, store):
        first, copy, target = moved
        with pytest.raises(StoreError) as stopped:
            transfer.move("acme/rates", self._stores(store, target), "there", keep=False, route=False)
        assert "and not whole: its record does not say where" in str(stopped.value)
        assert str(stopped.value).count("Nothing was removed from where it came from.") == 1
        assert (_folder_of(first) / "_data" / "treasury.parquet").is_file()

    def test_a_run_that_writes_to_both_does_not_stand_on_it(self, rates, moved, store):
        first, copy, target = moved
        report = snapshot.make(rates, store=_two_stores(store, target), store_names=["here", "there"], made_at=NOW)
        assert report.made and str(report.not_whole[2]) == str(FolderStore(target))

    def test_store_move_asks_the_target_by_hash_before_it_removes(self, rates, work, store, monkeypatch):
        """After the copies and before anything goes: every asset, as a read of the pipeline finds it in the target."""
        first = snapshot.make(rates, store=store, made_at=OLD).snapshot
        target = work / "target"
        monkeypatch.setattr(transfer, "copy_snapshot", lambda taken, source, into: None)  # a copy that wrote nothing
        with pytest.raises(StoreError) as stopped:
            transfer.move("acme/rates", self._stores(store, target), "there", keep=False, route=False)
        assert f"The store at {FolderStore(target)} does not hold acme/rates whole after the copy: " in str(stopped.value)
        assert str(stopped.value).endswith("not in the store. Nothing was removed from where it came from.")
        assert (_folder_of(first) / "_data" / "treasury.parquet").is_file() and len(snapshot.all_snapshots(FolderStore(store.root))) == 1


class TestALockfileEntryThatNamesNoPipeline:
    """Written before 0.3.0: every question by hash is asked of the whole store, never of a pipeline guessed from the folder."""

    def test_a_read_and_the_check_agree_when_the_folders_id_has_changed_since(self, work, store):
        from chartbook import identity

        rates = work / "rates"
        (rates / "_data").mkdir(parents=True)
        (rates / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        (rates / ".gitignore").write_text("/_data/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
        _table(rates, 3)
        _commit(rates)
        assert snapshot.pipeline_in(rates) == "rates"  # no [project] id, no remote: its ID is its folder's name
        snapshot.make(rates, store=store, made_at=NOW)
        reader = _reader(work / "reader", "rates", "../rates")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        path = reader / "chartbook.lock"
        document = json.loads(path.read_text(encoding="utf-8"))

        def as_before_0_3_0(node):  # as one written before entries said whose pins they are
            if isinstance(node, dict):
                node.pop("pinned_from", None)
                if isinstance(node.get("location"), dict):
                    node["location"].pop("pipeline", None)
            for value in node.values() if isinstance(node, dict) else node if isinstance(node, list) else ():
                as_before_0_3_0(value)

        as_before_0_3_0(document)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        (entry,) = lock.read_lock(reader).dependencies
        assert lock.pinned_pipeline(entry) is None and lock.pinned_pipeline(entry, rates) == "rates"
        good = Path(data.path("rates:treasury", project_dir=reader))
        assert good.is_file() and lock.verify(reader, FolderStore(store.root), note=False).problems == []
        # Its owner pushes it to GitHub: the folder's ID is the remote's from now on, and the snapshot is under the old one
        _git(rates, "remote", "add", "origin", "https://github.com/acme/rates.git")
        identity._git_remote_cache.clear()  # the next command is another process
        assert snapshot.pipeline_in(rates) == "acme/rates" and lock.pinned_pipeline(entry, rates) == "acme/rates"
        store_module._found_whole.clear()
        assert Path(data.path("rates:treasury", project_dir=reader)) == good
        assert lock.verify(reader, FolderStore(store.root), note=False).problems == []
