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
import types
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, lock, migrate_0_5, replacing, snapshot
from chartbook import store as store_module
from chartbook.cli import main
from chartbook.gitcache import GitCache
from chartbook.store import FolderStore, StoreError
from tests.fixtures import _git, needs_symlinks, symlinks_work
from tests.rich_store_of_0_5 import not_its_own, watch
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
    (folder / "_data" / "parts" / ".zmeta").write_text('{"format": 2}\n', encoding="utf-8", newline="\n")  # a hidden file is content
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


def _parts(document: dict) -> list:
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict)]


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
        entries = [entry for found in records.values() for record in found for part in _parts(record) for entry in part["stored"]["files"]]
        assert all("kept_in" in entry for entry in entries) and any(entry["kept_in"] == cleared[0].name for entry in entries)
        assert all(set(part["stored"]) in ({"at", "single", "files"}, {"at", "files"}) for found in records.values() for record in found for part in _parts(record))
        assert all(record["schema"] == "chartbook/snapshot/v2" for found in records.values() for record in found)
        assert len(list(root.rglob(".DS_Store"))) == 5
        # And it is whole as 0.5 left it: no file a record names is missing
        assert FolderStore(root).verify() == []


class TestAfterAMove:
    def test_the_layout_and_every_asset_read_as_the_same_bytes(self, of_0_5):
        root, readers = of_0_5
        before = _read_through(root)
        documents = {p.parent.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in root.glob("pipelines/*/*/_chartbook/snapshot.json")}
        old_records = {p.relative_to(root / "pipelines").as_posix(): p.read_bytes() for p in root.glob("pipelines/*/*/_chartbook/snapshot.json")}
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
        assert (done.pipelines, done.snapshots, done.complete, done.by_pins, done.increments) == (4, 7, 5, 2, 2)
        # A record is rewritten only in `stored`
        for record in records:
            now = json.loads(record.path.read_text(encoding="utf-8"))
            was = documents[record.folder.name]
            strip = lambda document: {k: ({n: v for n, v in part.items() if n != "stored"} if isinstance(part, dict) else [{n: v for n, v in one.items() if n != "stored"} for one in part] if k == "records" else part) for k, part in document.items() if k != "stored"}  # noqa: E731
            assert strip(now) == strip(was), record.path
        # What is left of the old folder is aside, whole: every old record byte for byte, the notes, and what no record names
        aside = root / "_chartbook" / "left-by-0.5" / "pipelines"
        assert done.kept == "_chartbook/left-by-0.5/pipelines" and done.aside == 4
        assert {p.relative_to(aside).as_posix(): p.read_bytes() for p in aside.glob("*/*/_chartbook/snapshot.json")} == old_records
        assert len(list(aside.rglob(".DS_Store"))) == 4 and len(list(aside.glob("*/*/_chartbook/CLEARED.txt"))) == 1
        assert len(list(aside.glob("*/README.txt"))) == 4
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
        steps = len(migrate_0_5.plan(root).steps) + 1

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

    def test_with_the_journal_removed_every_other_command_says_to_run_it_and_none_to_take_the_new_folders_out(self, of_0_5, monkeypatch):
        """A store.json of 0.5 over both trees, and no journal: what the move renamed is under the new trees and nowhere else."""
        root, readers = of_0_5
        last_write = max(number for number, step in enumerate(migrate_0_5.plan(root).steps, 1) if step.op == "write")
        with pytest.raises(_Stop):
            migrate_0_5.run(root, after_step=_stop_after(last_write))
        (root / migrate_0_5.JOURNAL).unlink()
        store_module._read_records.clear()
        monkeypatch.chdir(readers["rates3"])
        for typed in (["pin", "--check"], ["store", "ls"], ["store", "verify"], ["store", "info"], ["store", "gc", "--dry-run"], ["ls", "versions"]):
            result = CliRunner().invoke(main, typed)
            said = result.output.replace("\n", " ")
            assert result.exit_code == 1 and "Then run `chartbook store migrate`, which goes on from the folders as they are." in said, (typed, said)
            assert "out of it" not in said and "move snapshots/" not in said, (typed, said)
        with pytest.raises(Exception) as read:
            data.path("acme/rates:treasury", project_dir=readers["rates3"])
        assert "which goes on from the folders as they are" in str(read.value)
        assert CliRunner().invoke(main, ["store", "migrate", "--yes"]).exit_code == 0
        store_module._read_records.clear()
        assert FolderStore(root).verify() == [] and CliRunner().invoke(main, ["pin", "--check"]).exit_code == 0
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
        monkeypatch.setattr(migrate_0_5, "this_machine", lambda create=True: "another-machine")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and "was started on another machine (" in result.output and "two machines must never both move a store" in result.output
        assert f"take the move over here: remove {root / migrate_0_5.JOURNAL} and run this again." in result.output.replace("\n", "")
        assert _tree(root) == before


class TestBeforeAnythingMoves:
    def test_a_record_that_cannot_be_read_stops_it(self, of_0_5):
        root, _ = of_0_5
        record = next(root.glob("pipelines/acme+once/*/_chartbook/snapshot.json"))
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text("{not json", encoding="utf-8", newline="\n")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and f"The snapshot record {record} cannot be followed" in result.output and _tree(root) == before

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
        said = dry.output.splitlines()
        # Said first, by snapshot, with what to ask oneself before saying yes
        assert dry.exit_code == 0 and said[1] == "  1 file(s) that a record names are missing or of another size, as before the move, in 1 snapshot(s):"
        assert said[2].startswith("    acme+once/") and said[2].endswith(": 1 of 7 file(s)") and said[3] == "    the first: _output/curve.html"
        assert said[4] == (
            "  If a sync may still be bringing these files, wait for it to finish before the move: a file that arrives afterwards "
            "goes aside, and does not reach its snapshot. `chartbook store verify` lists every one."
        )
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
        left = "  What is left of pipelines/ goes aside whole, under _chartbook/left-by-0.5/: its old records and notes, and 4 file(s) that no record names. Nothing is removed."
        advice = "  A snapshot that is removed before the move is not copied: `chartbook store gc` of ChartBook 0.5 removes old ones (this version removes nothing from a store of 0.5)."
        assert said[0] == f"The store at {FolderStore(root)} has the layout of ChartBook 0.5: 4 pipeline(s), 7 snapshot(s)."
        assert said[1] == "  5 snapshot(s) become complete (2 of them made by a pin), 2 become increments on the newest of their pipeline."
        assert "moved inside the store by rename: nothing is copied or uploaded again for these." in said[2]
        assert said[3].endswith("are copied: each is in two folders that must each hold it. In a synced folder every copied byte is uploaded again.")
        # The copies are more than a hundredth of this small store: what it will take, and which snapshots are given them
        assert said[4].startswith("  The store takes ") and " now, and will take " in said[4] and said[4].endswith(" snapshot(s), the largest first:")
        assert said[-2:] == [advice, left] and all(line.startswith("    acme+") and " file(s)" in line for line in said[5:-2]) and len(said) > 7
        no = CliRunner().invoke(main, ["store", "migrate"], input="n\n")
        assert no.exit_code == 0 and no.output.splitlines()[-1] == "Nothing was moved." and _tree(root) == before
        asked = no.output.splitlines()
        assert asked[: len(said)] == said and asked[len(said):len(said) + 3] == [
            "Nothing else may use the store while this runs, on this machine or another.",
            "Afterwards every machine that uses it needs this ChartBook: an earlier one will not read it.",
            "In a synced folder, let the sync finish before another machine uses the store.",
        ]
        yes = CliRunner().invoke(main, ["store", "migrate"], input="y\n")
        assert yes.exit_code == 0, yes.output
        done = yes.output.splitlines()
        # The same counts, in the past, but for the one line that was to be acted on before; and the last of the three again
        past = lambda line: (  # noqa: E731
            line.replace(" became ", " become ").replace(" were ", " are ").replace(" went aside ", " goes aside ").replace(" went to ", " go to ")
            .replace("The store took ", "The store takes ").replace(" before the move, and takes ", " now, and will take ").replace(" now. The copies", ". The copies")
        )
        last = done[done.index(f"The store at {FolderStore(root)} has this version's layout: 4 pipeline(s), 7 snapshot(s).") + 1:-2]
        assert [past(line) for line in last] == [line for line in said[1:] if line != advice] and advice not in done[len(asked):]
        assert done[-2] == "The old folder, with its records, is kept at _chartbook/left-by-0.5/pipelines: it may be removed once the move has been checked."
        assert done[-1] == "In a synced folder, let the sync finish before another machine uses the store."
        again = CliRunner().invoke(main, ["store", "migrate"])
        assert again.exit_code == 0 and "has the layout of this version already: nothing to move." in again.output



def _listing(root: Path) -> dict:
    """Every file and folder under a store, with its size and its mode: what "untouched" is held against."""
    return {path.relative_to(root).as_posix(): (path.lstat().st_size if path.is_file() else -1, path.lstat().st_mode) for path in sorted(root.rglob("*"))}


class _Stop(Exception):
    pass


def _stop_after(number: int):
    def after(done: int) -> None:
        if done == number:
            raise _Stop()
    return after


def _rmtree(folder: Path) -> None:
    import shutil

    shutil.rmtree(folder, onerror=lambda function, path, _: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), function(path)))


class TestTheFoldersAreTheTruth:
    """Rule 2: every plan is made from the store as it is, and the journal only says a move is under way and whose."""

    def test_stopped_after_any_step_and_the_journal_deleted_a_second_run_ends_in_the_same_tree(self, of_0_5, work):
        import shutil

        root, _ = of_0_5
        shutil.copytree(root, work / "whole")
        migrate_0_5.run(work / "whole")
        wanted = _tree(work / "whole")
        steps = len(migrate_0_5.plan(root).steps) + 1
        for number in range(1, steps + 1):
            copy = work / f"cut-{number}"
            shutil.copytree(root, copy)
            with pytest.raises(_Stop):
                migrate_0_5.run(copy, after_step=_stop_after(number))
            journal = copy / migrate_0_5.JOURNAL
            if journal.is_file():
                journal.unlink()  # the way out for a journal that says nothing: the folders say where the move is
            migrate_0_5.run(copy)
            assert _tree(copy) == wanted, number
            store_module._read_records.clear()
            assert FolderStore(copy).verify() == [], number
            _rmtree(copy)

    def test_a_journal_that_cannot_be_read_stops_the_command_with_both_ways_out_and_removing_it_is_one(self, of_0_5):
        root, _ = of_0_5
        with pytest.raises(_Stop):
            migrate_0_5.run(root, after_step=_stop_after(7))
        journal = root / migrate_0_5.JOURNAL
        journal.write_text("", encoding="utf-8", newline="\n")
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and _tree(root) == before, result.output
        said = result.output.replace("\n", "")
        assert f"the journal of a move to this version's layout, {journal}, and it cannot be read" in said
        assert "If the move was started on another machine, wait for the sync to bring the file whole." in said
        assert "If it was started here and cut short, remove that file and run `chartbook store migrate` again" in said
        journal.unlink()
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and "it looks half moved, and the move goes on from the folders as they are." in result.output.replace("\n", " "), result.output
        store_module._read_records.clear()
        assert FolderStore(root).verify() == [] and not (root / "pipelines").exists()

    def test_a_move_gone_on_with_says_what_the_whole_move_came_to(self, of_0_5):
        root, _ = of_0_5
        whole = migrate_0_5.plan(root)
        with pytest.raises(_Stop):
            migrate_0_5.run(root, after_step=_stop_after(40))
        done = migrate_0_5.run(root)
        assert (done.pipelines, done.snapshots, done.complete, done.by_pins, done.increments) == (4, 7, 5, 2, 2)
        assert (done.renamed, done.copied) == (whole.renamed, whole.copied) and done.renamed > 0

    def test_the_machine_that_began_it_is_told_by_the_stores_own_name_for_it_not_by_its_host_name(self, of_0_5, monkeypatch):
        import socket

        root, _ = of_0_5
        with pytest.raises(_Stop):
            migrate_0_5.run(root, after_step=_stop_after(3))
        monkeypatch.setattr(socket, "gethostname", lambda: "renamed-since")
        assert CliRunner().invoke(main, ["store", "migrate", "--yes"]).exit_code == 0  # the same machine, under another host name


class TestFoundBeforeAnythingMoves:
    """Rule 1: whatever was true before a move and would stop it half way is found first, the tree is untouched, and its way out lets the move run."""

    def _refused(self, root: Path, said: str) -> None:
        before = _listing(root)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 1 and said in result.output.replace("\n", ""), result.output
        assert _listing(root) == before

    def _moves(self, root: Path) -> None:
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0, result.output
        store_module._read_records.clear()
        assert not (root / "pipelines").exists() and FolderStore(root).verify() == []

    def test_a_record_that_names_a_file_outside_its_pipelines_folder(self, of_0_5, work):
        root, _ = of_0_5
        record = next(root.glob("pipelines/acme+once/*/_chartbook/snapshot.json"))
        kept = record.read_text(encoding="utf-8")
        document = json.loads(kept)
        _parts(document)[0]["stored"]["files"][0]["kept_as"] = "../../../../outside.bin"
        (work / "outside.bin").write_bytes(b"not the store's")
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        self._refused(root, f"The snapshot record {record} cannot be followed")
        assert (work / "outside.bin").read_bytes() == b"not the store's"
        record.write_text(kept, encoding="utf-8", newline="\n")  # the way out: the record put right
        self._moves(root)

    def test_a_folder_this_user_may_not_write(self, of_0_5):
        root, _ = of_0_5
        if os.name == "nt" or os.geteuid() == 0:
            pytest.skip("a folder's mode keeps nobody out here")
        locked = next(root.glob("pipelines/acme+once/*/_data"))
        os.chmod(locked, stat.S_IREAD | stat.S_IEXEC)
        try:
            self._refused(root, f"The folder {locked} is not one this user may write")
        finally:
            os.chmod(locked, stat.S_IRWXU)
        self._moves(root)

    @needs_symlinks
    def test_a_pipelines_folder_that_is_a_link(self, of_0_5, work):
        root, _ = of_0_5
        real = root / "pipelines" / "acme+once"
        real.rename(work / "elsewhere")
        real.symlink_to(work / "elsewhere", target_is_directory=True)
        self._refused(root, f"{real} is a link to another place, and a move does not follow one")
        real.unlink()
        (work / "elsewhere").rename(real)
        self._moves(root)

    def test_two_names_this_disk_does_not_tell_apart(self, of_0_5, monkeypatch):
        root, _ = of_0_5
        monkeypatch.setattr(migrate_0_5, "_tells_case_apart", lambda folder: False)
        found = migrate_0_5.plan(root)
        first = next(step for step in found.steps if step.op == "rename")
        found.steps.append(migrate_0_5.Step("rename", first.source + "-other", first.target.upper()))
        with pytest.raises(migrate_0_5.MoveError) as refused:
            migrate_0_5.check(root, found)
        assert "this disk does not tell their names apart" in str(refused.value)


class TestWhatDoesNotStopAMove:
    def test_a_folder_with_files_and_no_record_is_taken_as_a_cleared_one_and_counted_and_named(self, of_0_5):
        """It stopped the move, which said to move the folder out, until a real store had one that a later record kept its files in (2026-11-20): tests/test_migrate_0_5_found.py."""
        root, _ = of_0_5
        arriving = root / "pipelines" / "acme+once" / "2026-06-01T091500Z_aaaaaaaaaaaa"
        (arriving / "_data").mkdir(parents=True)
        (arriving / "_data" / "t.parquet").write_bytes(b"a sync brings the record last")
        before = _listing(root)
        dry = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        said = dry.output.replace("\n", " ")
        assert dry.exit_code == 0 and _listing(root) == before, dry.output
        # The one folder: the one `store gc` cleared, which has no record either, is not named
        assert f"  1 folder(s) hold files and have no record: acme+once/{arriving.name} (1 file(s)). The files in such a folder that a record names are moved with that record, and the rest goes aside." in said
        assert "If a sync may still be bringing a folder's record, wait for it and run this again: a record that arrives after the move goes aside, and that snapshot has to be made again." in said
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and f"  1 folder(s) held files and had no record: acme+once/{arriving.name} (1 file(s))." in result.output, result.output
        assert (root / "_chartbook" / "left-by-0.5" / "pipelines" / "acme+once" / arriving.name / "_data" / "t.parquet").read_bytes() == b"a sync brings the record last"
        store_module._read_records.clear()
        assert not (root / "pipelines").exists() and FolderStore(root).verify() == []

    def test_a_file_that_was_missing_and_arrives_before_its_step_is_put_where_its_record_names_it(self, of_0_5):
        root, _ = of_0_5
        late = next(root.glob("pipelines/acme+once/*/_output/curve.html"))
        kept = late.read_bytes()
        os.chmod(late, stat.S_IWRITE | stat.S_IREAD)
        late.unlink()
        found = migrate_0_5.plan(root)
        assert len(found.missing) == 1 and any(step.op == "rename" and step.source.endswith("acme+once/" + late.parent.parent.name + "/_output/curve.html") for step in found.steps)

        def arrives(done: int) -> None:
            if done == 1:
                late.write_bytes(kept)  # the sync brings it once the move is under way

        migrate_0_5.run(root, after_step=arrives)
        store_module._read_records.clear()
        assert FolderStore(root).verify() == []

    def test_a_file_to_be_copied_whose_bytes_are_not_what_its_record_says_is_copied_as_it_is_and_named(self, of_0_5):
        root, _ = of_0_5
        copy = next(step for step in migrate_0_5.plan(root).steps if step.op == "copy")
        renamed_from = next(step.source for step in migrate_0_5.plan(root).steps if step.op == "rename" and step.target == copy.source)
        damaged = root / renamed_from
        os.chmod(damaged, stat.S_IWRITE | stat.S_IREAD)
        damaged.write_bytes(bytes(damaged.stat().st_size))
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and not (root / "pipelines").exists(), result.output
        assert (root / copy.target).read_bytes() == (root / copy.source).read_bytes()
        assert f"file(s) were copied as they are, though their bytes are not what their records say: {copy.target}" in result.output
        assert "`chartbook store verify` says more." in result.output

    def test_a_desktops_own_file_is_never_in_the_way(self, of_0_5):
        """Left again in tmp/, where a file moved aside is to go, and in a folder that is to go: none stops the move."""
        root, _ = of_0_5
        (root / "tmp" / ".DS_Store").write_bytes(b"\x00Bud1")
        taken = root / "_chartbook" / "left-by-0.5" / "pipelines" / ".DS_Store"
        taken.parent.mkdir(parents=True)
        taken.write_bytes(b"\x00Bud1")
        cleared = next(root.glob("pipelines/acme+rates/*/_chartbook/CLEARED.txt")).parent.parent

        def left_again(done: int) -> None:
            if done == 2 and cleared.is_dir():
                (cleared / "desktop.ini").write_bytes(b"[.ShellClassInfo]")

        migrate_0_5.run(root, after_step=left_again)
        assert not (root / "pipelines").exists() and not (root / "tmp").exists()

    def test_a_readme_a_person_wrote_is_moved_aside_and_one_chartbook_wrote_is_replaced(self, of_0_5):
        root, _ = of_0_5
        (root / "README.txt").write_text("Our team's store. Ask Dana before touching it.\n", encoding="utf-8", newline="\n")
        theirs = root / "pipelines" / "acme+once" / "README.txt"
        os.chmod(theirs, stat.S_IWRITE | stat.S_IREAD)
        theirs.write_text("Dana's notes on this pipeline.\n", encoding="utf-8", newline="\n")
        migrate_0_5.run(root)
        aside = root / "_chartbook" / "left-by-0.5"
        assert (aside / "README.txt").read_text(encoding="utf-8").startswith("Our team's store.")
        assert (aside / "pipelines" / "acme+once" / "README.txt").read_text(encoding="utf-8") == "Dana's notes on this pipeline.\n"
        assert (root / "README.txt").read_text(encoding="utf-8") == store_module.STORE_README
        assert (root / "snapshots" / "acme+rates" / "README.txt").read_text(encoding="utf-8") == store_module.PIPELINE_README

    def test_a_copy_has_the_mode_of_the_file_it_was_copied_from(self, of_0_5):
        root, _ = of_0_5
        copies = [step for step in migrate_0_5.plan(root).steps if step.op == "copy"]
        migrate_0_5.run(root)
        assert copies and all(stat.S_IMODE((root / step.target).stat().st_mode) == stat.S_IMODE((root / step.source).stat().st_mode) for step in copies)


class TestAStoreOf02SaysToRunItOnceMore:
    def test_the_first_run_ends_by_saying_so(self):
        import inspect

        from chartbook import cli

        assert "Run `chartbook store migrate` once more to move it on to this version's layout." in inspect.getsource(cli.store_migrate.callback)


class TestTheMoverRemovesNothingOfAnyones:
    """It renames, copies, writes its own files, merges the top's folders and, last, moves what is left of pipelines/ aside in one rename."""

    def test_nothing_is_removed_or_written_over_but_what_chartbook_itself_wrote(self, of_0_5, monkeypatch):
        """Every remover, every rename onto a path that is there, every file opened for writing over one: its journal, the marker, its own temporary files."""
        root, _ = of_0_5
        (root / "pipelines" / "acme+once" / "README.txt").write_text("Dana's notes.\n", encoding="utf-8", newline="\n")
        mark = root / "snapshots" / ("0" * 40) / "MOVED.txt"
        was = mark.read_bytes()
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            done = migrate_0_5.run(root)
        assert not_its_own(gone) == [] and ("unlink", "_chartbook/move-to-v3.jsonl") in gone
        assert (root / done.kept / "acme+once" / "README.txt").read_text(encoding="utf-8") == "Dana's notes.\n"
        # The mark the move from 0.2 left is aside with all else, not removed
        assert not mark.exists() and (root / "_chartbook" / "left-by-0.5" / "snapshots" / ("0" * 40) / "MOVED.txt").read_bytes() == was

    def test_the_steps_are_of_six_kinds_and_the_last_is_one_rename_of_what_is_left(self, of_0_5):
        root, _ = of_0_5
        steps = migrate_0_5.plan(root).steps
        assert {step.op for step in steps} == {"rename", "copy", "write", "note", "movedir", "aside"}
        assert (steps[-1].op, steps[-1].source, steps[-1].target) == ("aside", "pipelines", "_chartbook/left-by-0.5/pipelines")

    def test_a_read_only_temporary_left_by_a_copy_cut_short_is_chartbooks_to_replace(self, of_0_5):
        root, _ = of_0_5
        copy = next(step for step in migrate_0_5.plan(root).steps if step.op == "copy")
        left = root / (copy.target + ".moving")
        left.parent.mkdir(parents=True)
        left.write_bytes(b"half")
        os.chmod(left, stat.S_IREAD)
        migrate_0_5.run(root)
        store_module._read_records.clear()
        assert not left.exists() and FolderStore(root).verify() == []


class TestOnlyWhatTheStoresReaderTookIsFollowed:
    @pytest.mark.parametrize("said", [None, 7, "md5:abc"])
    def test_a_part_the_reader_passes_over_is_not_followed_out_of_the_store(self, of_0_5, work, said):
        root, _ = of_0_5
        record = next(root.glob("pipelines/acme+once/*/_chartbook/snapshot.json"))
        document = json.loads(record.read_text(encoding="utf-8"))
        real = next(entry for part in _parts(document) for entry in part["stored"]["files"])
        document["records"].append({
            "id": "acme/once:dataframe:other", "kind": "dataframe", "content_hash": said, "size_bytes": real["size_bytes"],
            "stored": {"at": "", "single": True, "files": [{**real, "path": "../../../../climbed-out.bin"}]},
        })
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        store_module._read_records.clear()
        assert FolderStore(root).verify() == []  # the store reads this record, and follows only what it took
        migrate_0_5.run(root)
        store_module._read_records.clear()
        assert not (work / "climbed-out.bin").exists() and not list(work.rglob("climbed-out.bin")) and FolderStore(root).verify() == []


class TestAHiddenFileIsContent:
    def test_one_a_record_names_that_arrives_while_the_move_runs_is_put_where_its_record_names_it(self, of_0_5):
        root, _ = of_0_5
        late = next(root.glob("pipelines/acme+once/*/_data/parts/.zmeta"))
        kept = late.read_bytes()
        os.chmod(late, stat.S_IWRITE | stat.S_IREAD)
        late.unlink()
        steps = migrate_0_5.plan(root).steps
        after = max(number for number, step in enumerate(steps, 1) if step.op == "rename")  # every rename is done, and the old folder is still there

        def arrives(done: int) -> None:
            if done == after:
                late.write_bytes(kept)

        migrate_0_5.run(root, after_step=arrives)
        store_module._read_records.clear()
        assert FolderStore(root).verify() == [] and [p for p in (root / "snapshots").rglob(".zmeta") if p.read_bytes() == kept]


class TestTheWaysOutNeverSayToRemoveWhatARecordMayName:
    def test_a_folder_with_files_and_no_record_is_never_to_be_moved_out_and_a_link_is_waited_for_or_moved_out(self, of_0_5, work):
        """A later record may keep files in a folder with no record, so no line says to take one out of the store: it stops nothing, and is named (tests/test_migrate_0_5_found.py)."""
        root, _ = of_0_5
        arriving = root / "pipelines" / "acme+once" / "2026-06-01T091500Z_aaaaaaaaaaaa"
        (arriving / "_data").mkdir(parents=True)
        (arriving / "_data" / "t.parquet").write_bytes(b"x")
        result = CliRunner().invoke(main, ["store", "migrate", "--dry-run"])
        said = result.output.replace("\n", " ")
        assert result.exit_code == 0 and f"1 folder(s) hold files and have no record: acme+once/{arriving.name} (1 file(s))." in said
        assert "out of the store" not in said and "move that folder" not in said and "wait for it and run this again" in said
        if symlinks_work():  # a link is this user's to make: not so on Windows without Developer Mode
            link = root / "pipelines" / "acme+linked"
            link.symlink_to(work, target_is_directory=True)
            said = CliRunner().invoke(main, ["store", "migrate", "--yes"]).output.replace("\n", " ")
            assert "is a link to another place" in said and "put that folder itself where the link is, and run this again" in said
            assert "remove" not in said and "move the link out" not in said and "is then missing" not in said
            link.rename(work / "the-link")  # it led to no folder of the store
        assert CliRunner().invoke(main, ["store", "migrate", "--yes"]).exit_code == 0
        assert (root / "_chartbook" / "left-by-0.5" / "pipelines" / "acme+once" / arriving.name / "_data" / "t.parquet").read_bytes() == b"x"


class TestTheQuestionIsSkippedOnlyForThisMachinesJournal:
    def test_a_store_half_moved_with_no_journal_shows_the_counts_and_asks(self, of_0_5):
        root, _ = of_0_5
        with pytest.raises(_Stop):
            migrate_0_5.run(root, after_step=_stop_after(9))
        (root / migrate_0_5.JOURNAL).unlink()
        before = _tree(root)
        result = CliRunner().invoke(main, ["store", "migrate"], input="n\n")
        assert result.exit_code == 0 and "it looks half moved, and the move goes on from the folders as they are." in result.output.replace("\n", " ")
        assert "Move it?" in result.output and result.output.splitlines()[-1] == "Nothing was moved." and _tree(root) == before
        assert "snapshot(s) become complete" in result.output


class TestWhatGoesAsideIsSaid:
    @pytest.mark.parametrize("arrival", ["another snapshot", "the same snapshot under another name"])
    def test_a_record_that_arrives_during_the_move_goes_aside_with_the_old_folder_and_is_named(self, of_0_5, work, arrival):
        """To be made again, where the store has no snapshot of its pipeline, commit and time; as a second record of one that was moved in, where it has."""
        import shutil

        root, _ = of_0_5
        source = next(root.glob("pipelines/acme+once/*/_chartbook/snapshot.json")).parent.parent
        shutil.copytree(source, work / "arrival")
        name = "2026-06-01T091500Z_" + source.name.split("_")[1]
        if arrival == "another snapshot":
            record = work / "arrival" / "_chartbook" / "snapshot.json"
            document = json.loads(record.read_text(encoding="utf-8"))
            document["made_at"] = "2026-06-01T09:15:00.000000Z"  # made when its folder's name says
            os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
            record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        steps = migrate_0_5.plan(root).steps
        after = max(number for number, step in enumerate(steps, 1) if step.op in ("write", "note"))

        def arrives(done: int) -> None:
            if done == after:  # a machine still on 0.5 writes a snapshot while the move runs
                shutil.copytree(work / "arrival", root / "pipelines" / "acme+once" / name)

        done = migrate_0_5.run(root, after_step=arrives)
        named, not_named = (done.set_aside, done.second) if arrival == "another snapshot" else (done.second, done.set_aside)
        assert named == [("acme+once", name)] and not_named == []
        assert (root / done.kept / "acme+once" / name / "_chartbook" / "snapshot.json").is_file()
        store_module._read_records.clear()
        assert [record.folder.name for record in FolderStore(root).records() if record.pipeline == "acme/once"] == [source.name]


class TestOnAMovedStore:
    """Run again where a machine that had not been brought the move wrote at the top: the notes are merged, and pipelines/ goes aside whole."""

    @pytest.fixture
    def moved(self, of_0_5, work):
        import shutil

        root, readers = of_0_5
        shutil.copytree(root, work / "was")
        migrate_0_5.run(root)
        store_module._read_records.clear()
        return root, work / "was", readers

    def test_every_other_command_refuses_it_and_names_this_one(self, moved, monkeypatch):
        root, was, readers = moved
        (root / "roots").mkdir()
        monkeypatch.chdir(readers["rates3"])
        for typed in (["pin", "--check"], ["store", "gc", "--dry-run"], ["store", "verify"], ["ls", "versions"]):
            result = CliRunner().invoke(main, typed)
            assert result.exit_code == 1 and "Then run `chartbook store migrate`, which moves it in." in result.output.replace("\n", ""), typed

    def test_nothing_under_a_late_pipelines_is_moved_in_and_twice_gives_two_folders_each_whole(self, moved):
        import shutil

        root, was, _ = moved
        late = was / "pipelines" / "acme+once"
        records_before = {p: p.read_bytes() for p in root.glob("snapshots/*/*/_chartbook/snapshot.json")}
        for number in (1, 2):
            shutil.copytree(late, root / "pipelines" / "acme+once")  # a snapshot under a name that is moved already
            listing = _tree(root / "pipelines")
            result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
            assert result.exit_code == 0 and "pipelines/ goes aside whole: nothing under it is moved in." in result.output.replace("\n", " "), result.output
            # The store has that snapshot: its record under pipelines/ is a second one, and nothing is to be made again
            assert "1 second record(s) of a snapshot that was moved in went aside: acme+once/" in result.output
            assert "without being moved in" not in result.output and "Run that pipeline again" not in result.output
            kept = root / "_chartbook" / "left-by-0.5" / ("pipelines" if number == 1 and not (root / "_chartbook" / "left-by-0.5" / "pipelines (2)").exists() else "pipelines (3)" if number == 2 else "pipelines (2)")
        aside = sorted(p.name for p in (root / "_chartbook" / "left-by-0.5").iterdir() if p.name.startswith("pipelines"))
        assert aside == ["pipelines", "pipelines (2)", "pipelines (3)"]  # the first move's, and one for each run again
        for name in aside[1:]:
            assert _tree(root / "_chartbook" / "left-by-0.5" / name) == listing
        assert {p: p.read_bytes() for p in root.glob("snapshots/*/*/_chartbook/snapshot.json")} == records_before  # the moved one's record is untouched
        store_module._read_records.clear()
        assert FolderStore(root).verify() == []

    def test_a_late_note_is_merged_with_the_moved_note_still_there_and_the_later_one_wins(self, moved):
        import shutil
        import time

        root, was, _ = moved
        there = sorted((root / "_chartbook" / "roots").iterdir())
        older, newer = there[0], there[1]
        (root / "roots").mkdir()
        shutil.copyfile(was / "roots" / older.name, root / "roots" / older.name)
        os.utime(root / "roots" / older.name, (time.time() - 86400, time.time() - 86400))  # the store has a later one
        (root / "roots" / newer.name).write_text('{"late": true}\n', encoding="utf-8", newline="\n")
        os.utime(root / "roots" / newer.name, (time.time() + 60, time.time() + 60))  # written since
        kept = older.read_bytes()
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0 and not (root / "roots").exists(), result.output
        assert older.read_bytes() == kept and newer.read_text(encoding="utf-8") == '{"late": true}\n'
        assert (root / "_chartbook" / "left-by-0.5" / "roots" / older.name).is_file()  # the earlier one is aside, not removed

    def test_a_file_that_arrives_late_for_a_snapshot_already_moved_is_named_with_where_it_is(self, moved):
        root, was, _ = moved
        snapshot_folder = next(p for p in sorted(root.glob("snapshots/acme+once/*")) if p.is_dir())
        late = root / "pipelines" / "acme+once" / snapshot_folder.name / "_output" / "curve.html"
        late.parent.mkdir(parents=True)
        late.write_bytes(b"late")
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0, result.output
        said = result.output.replace("\n", " ")
        # Where it is: the old folder of this run, beside the one the first move left
        where = f"_chartbook/left-by-0.5/pipelines (2)/acme+once/{snapshot_folder.name}/_output/curve.html"
        assert f"1 file(s) arrived for a snapshot that is moved already, and went aside: {where}." in said and (root / where).read_bytes() == b"late"
        assert "`chartbook store verify` names the snapshot that lacks each." in said

    def test_a_persons_readme_on_a_moved_store_is_never_touched(self, moved):
        root, _, _ = moved
        (root / "README.txt").write_text("Ours. Ask Dana.\n", encoding="utf-8", newline="\n")
        (root / "tmp").mkdir()
        assert CliRunner().invoke(main, ["store", "migrate", "--yes"]).exit_code == 0
        assert (root / "README.txt").read_text(encoding="utf-8") == "Ours. Ask Dana.\n" and not (root / "tmp").exists()


class TestARenameWindowsRefusesForAMoment:
    def test_every_rename_of_a_move_is_tried_again(self, of_0_5, monkeypatch):
        """On Windows a virus scanner, the indexer or a sync client holds a file or a folder for a moment, and a rename is refused meanwhile (found on Windows 11, 2026-11-20: the move stopped part way, to be run again).

        Every rename of the move is refused once here, as Windows refuses
        one, and the move goes through in one run.
        """
        root, _ = of_0_5
        refused: set = set()

        def held_once(source, target):
            if str(source) not in refused:
                refused.add(str(source))
                raise PermissionError(13, "Access is denied", str(source))
            return os.replace(source, target)

        # Only where the move renames (chartbook.replacing): this machine is not said to be Windows anywhere else
        monkeypatch.setattr(replacing, "sys", types.SimpleNamespace(platform="win32"))
        monkeypatch.setattr(replacing, "os", types.SimpleNamespace(replace=held_once))
        monkeypatch.setattr(replacing, "_WAIT_SECONDS", 0)
        result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
        assert result.exit_code == 0, result.output
        kinds = {Path(source).name for source in refused}
        # Files, the notes' folders, the old folder put aside, the journal and the marker: every kind of rename it makes
        assert len(refused) > 20 and {"pipelines", "roots", "origins", "store.json.moving"} <= kinds, sorted(kinds)
        store_module._read_records.clear()
        assert not (root / "pipelines").exists() and FolderStore(root).verify() == []

    def test_one_that_stays_refused_is_said_as_before(self, of_0_5, monkeypatch):
        """A folder that may not be written is refused for good: said after the two seconds, and the move is taken up by running it again."""
        root, _ = of_0_5

        def refused(source, target):
            raise PermissionError(13, "Access is denied", str(source))

        with monkeypatch.context() as patched:
            patched.setattr(replacing, "sys", types.SimpleNamespace(platform="win32"))
            patched.setattr(replacing, "os", types.SimpleNamespace(replace=refused))
            patched.setattr(replacing, "_WAIT_SECONDS", 0)
            result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
            assert result.exit_code == 1 and "Access is denied" in result.output, result.output
        assert CliRunner().invoke(main, ["store", "migrate", "--yes"]).exit_code == 0
        store_module._read_records.clear()
        assert not (root / "pipelines").exists() and FolderStore(root).verify() == []
