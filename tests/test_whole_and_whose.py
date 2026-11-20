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

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, models, sharing, snapshot, transfer
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
    def test_a_hole_in_the_second_stores_copy_is_said_in_its_own_words(self, rates, work, store):
        """Which store, which snapshot, which file, and the way out: not `store move`'s words, nor "rerun to finish"."""
        there = work / "there"
        first = snapshot.make(rates, store=_two_stores(store, there), store_names=["here", "there"], made_at=NOW)
        assert first.made
        (copy,) = snapshot.all_snapshots(FolderStore(there))
        _lose(_folder_of(copy) / "_data" / "treasury.parquet")
        before = sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file())
        for made_at in (LATER, LAST):
            with pytest.raises(snapshot.NotInEveryStore) as said:
                snapshot.make(rates, store=_two_stores(store, there), store_names=["here", "there"], made_at=made_at)
            assert str(said.value) == (
                f"The store at {FolderStore(there)} has the snapshot of acme/rates made {NOW} already, in "
                f"{_folder_of(copy).name}, and not whole: _data/treasury.parquet is not in the store. The snapshot in "
                f"{FolderStore(store.root)} is whole. If a sync is still bringing the file there, it arrives with the "
                f"sync. If it is lost for good, that store's copy stays as it is until a later snapshot of acme/rates "
                f"is sent there, and then goes with `chartbook store gc` there once nothing keeps it."
            )
        assert sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file()) == before
        # The way out, carried out: the pipeline changes, a later snapshot goes to both, whole
        _table(rates, 4)
        later = snapshot.make(rates, store=_two_stores(store, there), store_names=["here", "there"], made_at=LAST)
        assert later.made and len(snapshot.all_snapshots(FolderStore(there))) == 2


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

    @pytest.mark.parametrize("why, way", [
        ("a lockfile pins it", "once no lockfile pins it"),
        ("a lockfile that cannot be found pins it", "--forget-missing"),
        ("a lockfile not read here, another machine's, pins it", "that machine's lockfile"),
        ("it is the newest of its pipeline", "`chartbook run` in its folder"),
        ("a label points at a version in it", "--aggressive"),
        ("it holds a version of embeddings, which is kept (`keep = true` in its chartbook.toml)", "no longer marked `keep = true`"),
        ("it was made in the last 7 days", "once it is older than that"),
        ("it says which repository the kept snapshots are of", "once that is no longer so"),
    ])
    def test_each_reason_has_its_own(self, why, way):
        from chartbook.cli import _when_it_goes

        assert way in _when_it_goes(why)


class TestWhatGcSaysItFreed:
    def test_a_folder_a_pin_made_is_counted_when_it_goes(self, work, store):
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
        held = sum(p.stat().st_size for p in first.rglob("*") if p.is_file() and p.name != "snapshot.json")
        fresh = FolderStore(store.root)
        plan = lock.plan_gc(fresh, recent_seconds=0)
        assert [_folder_of(taken) for taken, _ in plan.pinned_delete] == [first] and plan.snapshots_delete == []
        assert plan.freed_bytes == held  # said before the question
        done = lock.carry_out_gc(plan, fresh)
        assert not first.exists() and (second / "data" / "steady.parquet").is_file()
        assert done.freed_bytes == held  # and after: a whole folder went, with its own copy of the table that did not change

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
    def test_it_is_not_said_to_be_there_and_nothing_is_imported_over_it(self, rates, work, store):
        taken = snapshot.make(rates, store=store, made_at=NOW).snapshot
        out = work / "for-me"
        sharing.export(FolderStore(store.root), "acme/rates", out, None)
        _lose(_folder_of(taken) / "_data" / "treasury.parquet")
        done = sharing.import_snapshots(FolderStore(store.root), out)
        assert done.there == [] and done.copied == []
        ((what, why),) = done.refused
        assert what == f"acme/rates at {taken.commit[:7]}, made {NOW}"
        assert why == (
            f"the store has it already, in {_folder_of(taken).name}, and not whole: _data/treasury.parquet is not in the "
            f"store. Nothing was imported over it. If a sync is still bringing it, wait for the sync to finish; a "
            f"snapshot that has lost a file for good goes with `chartbook store gc` once nothing keeps it, and can be "
            f"imported then"
        )
        assert not (_folder_of(taken) / "_data" / "treasury.parquet").exists()
        result = CliRunner().invoke(main, ["store", "import", str(out)])
        assert result.exit_code == 1 and "and not whole: _data/treasury.parquet is not in the store" in result.output


class TestAFolderWithBothLayoutsAndNoStoreJson:
    def test_it_is_refused_as_any_folder_with_both_is(self, rates, store):
        taken = snapshot.make(rates, store=store, made_at=NOW).snapshot
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
        for arguments in (["store", "verify"], ["store", "ls"], ["store", "info"], ["store", "gc", "--dry-run"], ["ls", "versions"]):
            result = CliRunner().invoke(main, arguments)
            assert result.exception is None or isinstance(result.exception, SystemExit), (arguments, repr(result.exception))
            assert result.exit_code == 1 and "holds snapshots of both layouts" in result.output, (arguments, result.output)


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
