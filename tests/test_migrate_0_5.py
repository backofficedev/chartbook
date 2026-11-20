"""`chartbook store migrate` moves a folder store of ChartBook 0.5 to this version's layout.

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout": per pipeline, the newest snapshot its owner made becomes complete
under ``snapshots/``, every other one its owner made an increment on it
under ``increments/``, and every one a pin made complete too. Files change
folder by rename and are not read; only the copies the result needs are.
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

from chartbook import config, data, lock, migrate_0_5, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.gitcache import GitCache
from chartbook.store import FolderStore, StoreError
from tests.fixtures import _git
from tests.store_of_0_5 import cleared_as_0_5, laid_out_as_0_5

TIMES = ("2025-10-01T09:15:00.000000Z", "2025-11-01T09:15:00.000000Z", "2025-12-01T09:15:00.000000Z", "2026-01-01T09:15:00.000000Z")


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


def _pipeline(folder: Path, pipeline: str, tracked: bool = False) -> Path:
    """A pipeline with a table, a dataset in parts and a chart; its data in git only where a `git` dependency is to pin it."""
    (folder / "_data" / "parts").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": pipeline},
            "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "d"},
                "parts": {"path": "./_data/parts/", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (folder / "README.md").write_text(f"# {pipeline}\n", encoding="utf-8", newline="\n")
    if not tracked:
        (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    pl.DataFrame({"day": [0, 1, 2], "of": [pipeline] * 3}).write_parquet(folder / "_data" / "treasury.parquet")
    pl.DataFrame({"year": [2020]}).write_parquet(folder / "_data" / "parts" / "2020.parquet")
    (folder / "_output" / "curve.html").write_text("<p>one</p>\n", encoding="utf-8", newline="\n")
    _commit(folder)
    return folder


def _reader(folder: Path, reads: dict) -> Path:
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": reads}), encoding="utf-8", newline="\n"
    )
    return folder


@pytest.fixture
def of_0_5(work, store):
    """A store of 0.5 with every shape a real one has (the maintainer's own was counted, 2026-11-20).

    - ``acme/rates``: four snapshots its owner made, each with a part more
      and another chart, the oldest then cleared by the ``store gc`` of 0.5:
      a folder with ``CLEARED.txt`` and no record, which still holds the
      table and a part that the later records name;
    - ``acme/once``: one snapshot;
    - ``acme/upstream``: one its owner made and one a pin made from its
      repository, in the same tree;
    - ``acme/pinned``: only a snapshot a pin made;
    - readers that pin each, so ``roots/`` has their notes; ``origins/``;
      an empty ``tmp/``; the mark of the move from 0.2; a ``README.txt`` in
      each pipeline's folder; and a ``.DS_Store`` at the top, in
      ``pipelines/``, in a pipeline's folder, in a snapshot's folder and in
      a snapshot's ``_chartbook/``.

    :returns: The store's folder, and the readers by what they read.
    """
    rates = _pipeline(work / "rates", "acme/rates")
    readers = {}
    for number, made_at in enumerate(TIMES):
        pl.DataFrame({"year": [2020 + number]}).write_parquet(rates / "_data" / "parts" / f"{2020 + number}.parquet")
        (rates / "_output" / "curve.html").write_text(f"<p>{number}</p>\n", encoding="utf-8", newline="\n")
        snapshot.make(rates, store=FolderStore(store.root), made_at=made_at)
        if number in (1, 3):
            readers[f"rates{number}"] = _reader(work / f"reads-rates-{number}", {"acme/rates": {"path": "../rates"}})
            assert lock.pin(readers[f"rates{number}"], FolderStore(store.root)).problems == []
    snapshot.make(_pipeline(work / "once", "acme/once"), store=FolderStore(store.root), made_at=TIMES[0])
    cache = GitCache(work / "gitcache")
    for name in ("upstream", "pinned"):
        _pipeline(work / name, f"acme/{name}", tracked=True)
        readers[name] = _reader(work / f"reads-{name}", {f"acme/{name}": {"git": f"../{name}"}})
        assert lock.pin(readers[name], FolderStore(store.root), git_cache=cache).problems == []
    (work / "upstream" / "README.md").write_text("# acme/upstream, on\n", encoding="utf-8", newline="\n")
    _commit(work / "upstream")
    snapshot.make(work / "upstream", store=FolderStore(store.root), made_at=TIMES[2])
    old = laid_out_as_0_5(store.root)
    oldest = min((taken for taken in snapshot.all_snapshots(old) if taken.pipeline == "acme/rates"), key=lambda taken: taken.made_at)
    cleared_as_0_5(oldest.path)
    root = store.root
    (root / "tmp").mkdir(exist_ok=True)
    (root / "snapshots" / ("0" * 40)).mkdir(parents=True)
    (root / "snapshots" / ("0" * 40) / "MOVED.txt").write_text("moved\n", encoding="utf-8", newline="\n")
    newest = max(p for p in (root / "pipelines" / "acme+rates").iterdir() if (p / "_chartbook" / "snapshot.json").is_file())
    for place in (root, root / "pipelines", root / "pipelines" / "acme+rates", newest, newest / "_chartbook"):
        (place / ".DS_Store").write_bytes(b"\x00Bud1")
    store_module._read_records.clear()
    store_module._found_whole.clear()
    return root, readers


def _tree(root: Path) -> dict:
    """Every file under a folder, by its path, with the hash of its bytes."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _read_through(root: Path) -> dict:
    """Every asset of every record, as the store hands its files out: by pipeline, time and file, the hash of its bytes."""
    store_module._read_records.clear()
    store_module._found_whole.clear()
    fresh, found = FolderStore(root), {}
    for record in fresh.records():
        assert record.readable, record.path
        for asset in record.assets:
            for file in asset.files:
                found[(record.pipeline, record.made_at, file.path)] = hashlib.sha256(file.location.read_bytes()).hexdigest()
    return found


class TestTheFixtureIsAStoreOf05WithEveryShape:
    def test_shape_by_shape(self, of_0_5):
        root, _ = of_0_5
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v2"}
        assert sorted(p.name for p in root.iterdir()) == [".DS_Store", "origins", "pipelines", "roots", "snapshots", "store.json", "tmp"]
        assert list((root / "tmp").iterdir()) == [] and (root / "snapshots" / ("0" * 40)).is_dir()
        assert len(list((root / "roots").iterdir())) == 4 and any((root / "origins").rglob("*.txt"))
        folders = {p.parent.name: sorted(q.name for q in p.parent.iterdir() if q.is_dir()) for p in (root / "pipelines").glob("*/README.txt")}
        assert sorted(folders) == ["acme+once", "acme+pinned", "acme+rates", "acme+upstream"]
        records = {name: [json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "pipelines" / name).glob("*/_chartbook/snapshot.json"))] for name in folders}
        assert {name: [record.get("made_by", "owner") for record in found] for name, found in records.items()} == {
            "acme+once": ["owner"], "acme+pinned": ["pin"], "acme+rates": ["owner"] * 3, "acme+upstream": ["owner", "pin"] or ["pin", "owner"],
        } or sorted(records["acme+upstream"][i].get("made_by", "owner") for i in (0, 1)) == ["owner", "pin"]
        cleared = [p.parent.parent for p in (root / "pipelines" / "acme+rates").glob("*/_chartbook/CLEARED.txt")]
        assert len(cleared) == 1 and not (cleared[0] / "_chartbook" / "snapshot.json").exists()
        assert (cleared[0] / "_data" / "treasury.parquet").is_file()  # which the later records name
        entries = [entry for found in records.values() for record in found for part in migrate_0_5._parts(record) for entry in part["stored"]["files"]]
        assert all("kept_in" in entry for entry in entries) and any(entry["kept_in"] == cleared[0].name for entry in entries)
        assert all(set(part["stored"]) in ({"at", "single", "files"}, {"at", "files"}) for found in records.values() for record in found for part in migrate_0_5._parts(record))
        assert all(record["schema"] == "chartbook/snapshot/v2" for found in records.values() for record in found)
        assert len(list(root.rglob(".DS_Store"))) == 5
        # And it is whole as 0.5 left it: no file a record names is missing
        assert FolderStore(root).verify() == []


class TestAfterAMove:
    def test_the_layout_and_every_asset_read_as_the_same_bytes(self, of_0_5):
        root, readers = of_0_5
        before = _read_through(root)
        documents = {p.parent.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in root.glob("pipelines/*/*/_chartbook/snapshot.json")}
        done = migrate_0_5.run(root)
        assert json.loads((root / "store.json").read_text(encoding="utf-8")) == {"schema": "chartbook/store/v3"}
        assert not any((root / name).exists() for name in ("pipelines", "roots", "origins", "tmp")) and not (root / migrate_0_5.JOURNAL).exists()
        assert not (root / "snapshots" / ("0" * 40)).exists()
        assert _read_through(root) == before
        fresh = FolderStore(root)
        records = fresh.records()
        assert all(fresh.holes_of(record.path) == [] for record in records) and fresh.verify() == []
        # Per pipeline: the newest its owner made is complete, the others it made are increments on it, a pin's is complete
        rates = [record for record in records if record.pipeline == "acme/rates"]
        newest = max(rates, key=lambda record: record.made_at)
        assert [(record.increment, record.builds_on) for record in rates] == [(True, newest.folder.name), (True, newest.folder.name), (False, "")]
        assert sorted((record.pipeline, record.made_by, record.increment) for record in records if record.pipeline != "acme/rates") == [
            ("acme/once", "snapshot", False), ("acme/pinned", "pin", False), ("acme/upstream", "pin", False), ("acme/upstream", "snapshot", False),
        ]
        assert (done.pipelines, done.snapshots, done.complete, done.by_pins, done.increments, done.folders_gone) == (4, 7, 5, 2, 2, 1)
        # A record is rewritten only in `stored`
        for record in records:
            now = json.loads(record.path.read_text(encoding="utf-8"))
            was = documents[record.folder.name]
            strip = lambda document: {k: ({n: v for n, v in part.items() if n != "stored"} if isinstance(part, dict) else [{n: v for n, v in one.items() if n != "stored"} for one in part] if k == "records" else part) for k, part in document.items() if k != "stored"}  # noqa: E731
            assert strip(now) == strip(was), record.path
        # What no record names is not removed: it is aside, at its old path
        aside = sorted(p.relative_to(root / "_chartbook" / "left-by-0.5").as_posix() for p in (root / "_chartbook" / "left-by-0.5").rglob("*") if p.is_file())
        assert len(aside) == 4 and all(path.endswith(".DS_Store") and path.startswith("pipelines") for path in aside) and done.aside == 4
        assert (root / ".DS_Store").is_file()

    def test_the_readers_the_checks_and_gc_say_what_they_said_before(self, of_0_5, monkeypatch):
        root, readers = of_0_5

        def said() -> dict:
            store_module._read_records.clear()
            store_module._found_whole.clear()
            found = {}
            for name, reader in readers.items():
                monkeypatch.chdir(reader)
                result = CliRunner().invoke(main, ["pin", "--check"])
                found[name] = (result.exit_code, result.output.replace(str(root), "STORE"))
            return found

        before = said()
        assert all(code == 0 for code, _ in before.values()), before
        migrate_0_5.run(root)
        assert said() == before
        # gc keeps, by name, what a lockfile pins and the newest of each pipeline, as before the move; the one
        # old snapshot of rates that nothing pins is the one it would remove
        plan = lock.plan_gc(FolderStore(root))
        kept = {(taken.pipeline, taken.made_at) for taken, _ in plan.snapshots_kept}
        pinned = {moment for reader in readers.values() for moment in lock.read_lock(reader).snapshots()}
        assert {made_at for _, made_at in pinned} <= {made_at for _, made_at in kept} | {taken.made_at for taken, _ in plan.pinned_kept}
        assert {("acme/rates", TIMES[1]), ("acme/rates", TIMES[3]), ("acme/once", TIMES[0]), ("acme/upstream", TIMES[2])} <= kept
        assert [(taken.pipeline, taken.made_at) for taken, _ in plan.snapshots_delete] == [("acme/rates", TIMES[2])]
        for typed in (["store", "gc", "--dry-run"], ["store", "verify"], ["store", "ls"], ["snapshot"]):
            monkeypatch.chdir(readers["rates3"].parent / "rates")
            result = CliRunner().invoke(main, typed)
            assert result.exit_code == 0 and "has the layout of ChartBook 0.5" not in result.output, (typed, result.output)


class TestRenamesNotCopies:
    def test_only_the_copies_the_result_needs_are_opened_for_reading(self, of_0_5, monkeypatch):
        root, _ = of_0_5
        found = migrate_0_5.plan(root)
        copies = sorted(step.source for step in found.steps if step.op == "copy")
        assert found.renamed > 20 and 0 < found.copied == len(copies) < found.renamed
        opened: list = []
        real = open

        def counting(file, mode="r", *args, **kwargs):
            if "b" in mode and "r" in mode:
                opened.append(Path(file).relative_to(root).as_posix())
            return real(file, mode, *args, **kwargs)

        monkeypatch.setattr(migrate_0_5, "open", counting, raising=False)
        done = migrate_0_5.run(root)
        assert sorted(opened) == copies and done.copied == len(copies)
        assert (done.renamed, done.renamed_bytes, done.copied_bytes) == (found.renamed, found.renamed_bytes, found.copied_bytes)


class TestCutShortAndRunAgain:
    def test_stopped_after_any_step_a_second_run_ends_in_the_same_tree(self, of_0_5, work):
        import shutil

        root, _ = of_0_5
        shutil.copytree(root, work / "whole")
        migrate_0_5.run(work / "whole")
        wanted = _tree(work / "whole")
        steps = len(migrate_0_5.plan(root).steps) + len(migrate_0_5._top(root)) + 1

        class Stop(Exception):
            pass

        def stop_at(number: int):
            def after(done: int) -> None:
                if done == number:
                    raise Stop()
            return after

        for number in range(1, steps + 1):
            copy = work / f"cut-{number}"
            shutil.copytree(root, copy)
            with pytest.raises(Stop):
                migrate_0_5.run(copy, after_step=stop_at(number))
            assert (copy / migrate_0_5.JOURNAL).is_file() or number == steps
            migrate_0_5.run(copy)
            assert _tree(copy) == wanted, number
            shutil.rmtree(copy, onerror=lambda function, path, _: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), function(path)))

    def test_while_a_journal_is_there_every_other_command_stops_and_says_to_run_it_again(self, of_0_5, monkeypatch):
        root, readers = of_0_5

        class Stop(Exception):
            pass

        def after(done: int) -> None:
            if done == 5:
                raise Stop()

        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=after)
        said = (
            f"A move of the store at {root} to this version's layout was cut short, or is still running. Run `chartbook "
            f"store migrate` again and let it finish; nothing else uses the store until it has."
        )
        with pytest.raises(StoreError) as refused:
            FolderStore(root).records()
        assert str(refused.value) == said
        monkeypatch.chdir(readers["rates3"])
        for typed in (["pin", "--check"], ["store", "ls"], ["store", "verify"], ["store", "gc", "--dry-run"], ["ls", "versions"]):
            result = CliRunner().invoke(main, typed)
            assert result.exit_code == 1 and "was cut short, or is still running" in result.output, (typed, result.output)
        with pytest.raises(Exception) as read:
            data.path("acme/rates:treasury", project_dir=readers["rates3"])
        assert "was cut short" in str(read.value)
        # And the command goes on
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and "was cut short: it goes on where it stopped." in result.output, result.output
        assert FolderStore(root).verify() == [] and data.path("acme/rates:treasury", project_dir=readers["rates3"])

    def test_a_journal_another_machine_started_stops_this_ones_move(self, of_0_5, monkeypatch):
        root, _ = of_0_5

        class Stop(Exception):
            pass

        def after(done: int) -> None:
            if done == 3:
                raise Stop()

        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=after)
        monkeypatch.setattr(migrate_0_5.socket, "gethostname", lambda: "another-laptop")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and "was started on " in result.output and "two machines must never both move a store" in result.output
        assert _tree(root) == before


class TestBeforeAnythingMoves:
    def test_a_record_that_cannot_be_read_stops_it(self, of_0_5):
        root, _ = of_0_5
        record = next(root.glob("pipelines/acme+once/*/_chartbook/snapshot.json"))
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text("{not json", encoding="utf-8", newline="\n")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and f"The snapshot record {record} cannot be read" in result.output and _tree(root) == before

    def test_a_snapshot_being_made_stops_it(self, of_0_5):
        root, _ = of_0_5
        (root / "tmp" / "abc.pending").write_text("a note\n", encoding="utf-8", newline="\n")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and "A snapshot is being made in the store" in result.output and _tree(root) == before

    def test_too_little_room_for_the_copies_stops_it(self, of_0_5, monkeypatch):
        root, _ = of_0_5
        monkeypatch.setattr(migrate_0_5.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 10})())
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and "the copies need " in result.output and "its disk has 10 free" in result.output and _tree(root) == before

    def test_a_path_that_would_be_too_long_stops_it(self, of_0_5, monkeypatch):
        root, _ = of_0_5
        monkeypatch.setattr(migrate_0_5, "too_long", lambda path: f"{path} is too long" if "increments" in str(path) else None)
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and "The store is not moved: " in result.output and "is too long" in result.output and _tree(root) == before

    def test_a_file_a_record_names_that_is_missing_does_not(self, of_0_5):
        root, _ = of_0_5
        lost = next(root.glob("pipelines/acme+once/*/_output/curve.html"))
        os.chmod(lost, stat.S_IWRITE | stat.S_IREAD)
        lost.unlink()
        dry = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        assert dry.exit_code == 0 and "1 file(s) a record names are missing or of another size, as before the move: _output/curve.html (" in dry.output
        assert "If a sync is still bringing them, wait and run again." in dry.output
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0, result.output
        (problem,) = FolderStore(root).verify()  # its record goes on naming it
        assert problem.message.startswith("_output/curve.html is not in the store")


class TestTheQuestion:
    def test_what_the_dry_run_says_is_what_is_then_done(self, of_0_5):
        root, _ = of_0_5
        before = _tree(root)
        dry = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        assert dry.exit_code == 0 and dry.output.splitlines()[-1] == "Nothing was moved." and _tree(root) == before
        said = dry.output.splitlines()[:-1]
        assert said[0] == f"The store at {FolderStore(root)} has the layout of ChartBook 0.5: 4 pipeline(s), 7 snapshot(s)."
        assert said[1] == "  5 snapshot(s) become complete (2 of them made by a pin), 2 become increments on the newest of their pipeline."
        assert "moved inside the store by rename: nothing is copied or uploaded again for these." in said[2]
        assert said[4] == "  1 folder(s) that are no snapshot any more go; 4 file(s) that no record names are moved aside, under _chartbook/left-by-0.5/."
        no = CliRunner().invoke(main, ["store", "migrate"], input="n\n")
        assert no.exit_code == 0 and no.output.splitlines()[-1] == "Nothing was moved." and _tree(root) == before
        asked = no.output.splitlines()
        assert asked[5:8] == [
            "Nothing else may use the store while this runs, on this machine or another.",
            "Afterwards every machine that uses it needs this ChartBook: an earlier one will not read it.",
            "In a synced folder, let the sync finish before another machine uses the store.",
        ]
        yes = CliRunner().invoke(main, ["store", "migrate"], input="y\n")
        assert yes.exit_code == 0, yes.output
        done = yes.output.splitlines()
        # The same counts, in the past, and the last of the three again
        assert [line.replace(" became ", " become ").replace(" were ", " are ") for line in done[-5:-1]] == said[1:5]
        assert done[-1] == "In a synced folder, let the sync finish before another machine uses the store."
        again = CliRunner().invoke(main, ["store", "migrate"])
        assert again.exit_code == 0 and "has the layout of this version already: nothing to move." in again.output


class TestItLooksOnceMore:
    def test_what_arrived_during_the_move_is_moved_by_the_same_rules_and_the_base_stays(self, of_0_5, work):
        """A machine still on 0.5 writes a snapshot while the move runs: it is an increment on the base the pipeline has by then."""
        import shutil

        root, _ = of_0_5
        late = work / "late"
        shutil.copytree(root / "pipelines" / "acme+once", late)
        (snapshot_folder,) = [p for p in late.iterdir() if p.is_dir()]
        arrived = snapshot_folder.with_name("2026-06-01T091500Z_" + snapshot_folder.name.split("_")[1])
        snapshot_folder.rename(arrived)
        record = arrived / "_chartbook" / "snapshot.json"
        document = json.loads(record.read_text(encoding="utf-8"))
        document["made_at"] = "2026-06-01T09:15:00.000000Z"
        for part in migrate_0_5._parts(document):
            for entry in part["stored"]["files"]:
                entry["kept_in"] = arrived.name
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        total = len(migrate_0_5.plan(root).steps) + len(migrate_0_5._top(root))

        def arrives(done: int) -> None:
            if done == total:  # everything planned is moved, and the marker is not switched yet
                (root / "pipelines" / "acme+once").mkdir(parents=True)
                shutil.copytree(arrived, root / "pipelines" / "acme+once" / arrived.name)

        migrate_0_5.run(root, after_step=arrives)
        assert not (root / "pipelines").exists() and FolderStore(root).verify() == []
        once = [record for record in FolderStore(root).records() if record.pipeline == "acme/once"]
        assert [(record.increment, bool(record.builds_on)) for record in once] == [(False, False), (True, True)]
        assert once[1].folder.name == arrived.name and once[1].builds_on == once[0].folder.name
