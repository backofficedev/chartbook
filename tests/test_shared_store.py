"""A store that two machines share through a synced folder (Google Drive, Dropbox, OneDrive).

Two machines are two home folders, and two working folders, with one store
folder between them, as a sync service keeps it on each. What the service
leaves in it: a file there before all of its bytes, an object not there
yet, and a copy of a file changed in two places under a name of its own.
And one person's two machines can have a lockfile at the same path.
"""

import json
import os
import shutil
import stat
import warnings
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import data, lock, snapshot
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.store import FolderStore, default_store, is_record_name, unsynced_part
from tests.test_dependencies_by_id import _commit, _forecast, _rates
from tests.test_model_versions import _git

LONG_AGO = "2020-01-01T00:00:00.000000Z"


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """Machine A makes snapshots of acme/rates into a store in a synced folder; machine B reads them.

    :returns: The work folder, and a function that moves to a machine by its letter.
    """
    work = tmp_path.resolve()
    monkeypatch.setenv("CHARTBOOK_STORE", str(work / "Google Drive" / "chartbook-store"))
    monkeypatch.delenv("CHARTBOOK_MACHINE_ID")  # each home its own machine

    def machine(letter: str) -> Path:
        home = work / f"home-{letter}"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        return work / letter

    machine("a")
    rates = work / "a" / "rates"
    _rates(rates, 4.1)
    _git(rates, "init", "--quiet", "-b", "main")
    (rates / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(rates)
    return work, machine, rates


def _snapshot_again(rates: Path, value: float, made_at=None) -> snapshot.Snapshot:
    _rates(rates, value)
    (rates / "notes.txt").write_text(f"{value}\n")
    _commit(rates, f"At {value}")
    return snapshot.make(rates, made_at=made_at).snapshot


def _object_file(taken: snapshot.Snapshot) -> Path:
    """The treasury file of a snapshot's object, writable, as a sync service would write it."""
    held = default_store().get(taken.assets["treasury"]["content_hash"]) / "treasury.parquet"
    os.chmod(held, stat.S_IRUSR | stat.S_IWUSR)
    return held


def _pinned_commit(forecast: Path) -> str:
    (entry,) = lock.read_lock(forecast).dependencies
    return entry["location"]["commit"]


class TestAFileThereBeforeAllOfItsBytes:
    @pytest.fixture
    def half(self, drive):
        """B pinned the first snapshot; A made a second, whose file B has only half of so far."""
        work, machine, rates = drive
        first = snapshot.make(rates).snapshot
        second_folder = machine("b")
        forecast = _forecast(second_folder / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        machine("a")
        second = _snapshot_again(rates, 4.2)
        machine("b")
        held = _object_file(second)
        whole = held.read_bytes()
        held.write_bytes(whole[: len(whole) // 2])  # as a sync in progress leaves it
        return forecast, first, second, held, whole

    def test_update_does_not_move_to_it_and_says_to_wait(self, half):
        forecast, first, second, held, whole = half
        report = lock.update(forecast)
        (problem,) = report.problems
        assert problem.status == "unsynced" and problem.asset == "acme/rates:treasury"
        assert "not fully synced yet" in problem.detail and "Wait for the sync to finish" in problem.detail
        assert _pinned_commit(forecast) == first.commit  # nothing moved
        held.write_bytes(whole)  # the sync finishes
        assert lock.update(forecast).problems == []
        assert _pinned_commit(forecast) == second.commit

    def test_pin_frozen_and_a_read_say_it_too(self, half, monkeypatch):
        forecast, first, second, held, whole = half
        held.write_bytes(whole)
        lock.update(forecast)
        held.write_bytes(whole[:100])  # the same pin, read on a machine whose sync is behind
        (problem,) = lock.verify(forecast).problems
        assert "not fully synced yet" in problem.message
        assert {e.status for e in lock.pin(forecast).problems} == {"unsynced"}
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="not fully synced yet") as raised:
            data.load("acme/rates:treasury").collect()
        assert raised.value.reason == "not_synced"

    def test_a_first_read_says_it_and_writes_nothing(self, half, monkeypatch):
        forecast, first, second, held, whole = half
        (forecast / lock.LOCK_FILE).unlink()  # a fresh clone of it, before any pin
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="cannot be pinned yet: .*not fully synced yet") as raised:
            data.load("acme/rates:treasury")
        assert raised.value.reason == "not_synced"
        assert not (forecast / lock.LOCK_FILE).exists()

    def test_the_commands_say_it(self, half):
        forecast, first, second, held, whole = half
        updated = CliRunner().invoke(main, ["update", "--project-dir", str(forecast)])
        assert updated.exit_code == 1
        assert "not fully synced: acme/rates:treasury: nothing was moved" in updated.output
        frozen = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(forecast)])
        assert frozen.exit_code == 0  # still pinned to the first snapshot, which is whole
        held.write_bytes(whole)
        lock.update(forecast)
        held.write_bytes(whole[:10])
        frozen = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(forecast)])
        assert frozen.exit_code == 1 and "not fully synced yet" in frozen.output


    def test_the_name_a_pin_reads_is_the_one_judged(self, half, tmp_path):
        """Another pipeline stored the same bytes under another name; the sync has the other name whole."""
        forecast, first, second, held, whole = half
        held.write_bytes(whole)
        lock.update(forecast)
        (tmp_path / "copy.parquet").write_bytes(whole)
        default_store().put(tmp_path / "copy.parquet")
        assert (held.parent / "copy.parquet").is_file()
        held.write_bytes(b"")  # the name this pin reads, made and not filled yet
        (problem,) = lock.verify(forecast).problems
        assert "has 0 bytes of treasury.parquet where its record says" in problem.message

    def test_update_at_the_snapshot_it_is_pinned_to_says_it_once(self, half):
        forecast, first, second, held, whole = half
        held.write_bytes(whole)
        lock.update(forecast)
        held.write_bytes(whole[:10])
        (problem,) = lock.update(forecast).problems
        assert problem.status == "unsynced" and "nothing was moved" not in problem.detail
        result = CliRunner().invoke(main, ["update", "--project-dir", str(forecast)])
        assert "acme/rates: 1 not fully synced\n" in result.output and "1 thing(s) could not be pinned" in result.output


class TestTheSizesOfAnObject:
    def test_a_file_is_judged_by_its_own_name(self, tmp_path):
        """One file's bytes may be in its object under two names, as two pipelines named it; a sync may deliver one."""
        (tmp_path / "a.parquet").write_bytes(b"x" * 10)
        (tmp_path / "b.parquet").write_bytes(b"")  # a name the sync has made and not filled yet
        assert unsynced_part(tmp_path, 10, {"a.parquet": 10}) is None
        assert unsynced_part(tmp_path, 10, {"b.parquet": 10}) == "has 0 bytes of b.parquet where its record says 10"
        assert unsynced_part(tmp_path, 10, {"c.parquet": 10}) is None  # read as the folder, which has its bytes
        assert unsynced_part(tmp_path, 20, {"c.parquet": 20}) == "has 10 bytes where its record says 20"

    def test_a_file_whatever_it_is_called(self, tmp_path):
        (tmp_path / "._x").write_bytes(b"x" * 10)  # a name a directory's hash passes over
        assert unsynced_part(tmp_path, 10, {"._x": 10}) is None

    def test_a_folder_with_a_file_not_there_yet(self, tmp_path):
        (tmp_path / "year=2024").mkdir()
        (tmp_path / "year=2024" / "part-0.parquet").write_bytes(b"x" * 10)
        listed = {"year=2024/part-0.parquet": 10, "year=2025/part-0.parquet": 15}
        assert unsynced_part(tmp_path, 25, listed) == "does not have year=2025/part-0.parquet yet"
        assert unsynced_part(tmp_path, 25) == "has 10 bytes where its record says 25"  # a glob's, summed
        (tmp_path / "year=2025").mkdir()
        (tmp_path / "year=2025" / "part-0.parquet").write_bytes(b"x" * 15)
        assert unsynced_part(tmp_path, 25, listed) is None and unsynced_part(tmp_path, 25) is None

    def test_an_empty_folder_is_not_whole(self, tmp_path):
        assert unsynced_part(tmp_path, 0) == "has none of its files yet"

    def test_what_a_record_says_is_read(self, drive):
        work, machine, rates = drive
        (rates / "_data" / "parts").mkdir()
        (rates / "_data" / "parts" / "a.csv").write_text("1\n")
        (rates / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
                "treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."},
                "parts": {"path": "./_data/parts", "docs": "Parts."},
            }})
        )
        _commit(rates, "Parts")
        taken = snapshot.make(rates).snapshot
        assert snapshot.files_read(taken.assets["treasury"]) == {"treasury.parquet": taken.assets["treasury"]["size_bytes"]}
        assert snapshot.files_read(taken.assets["parts"]) == {"a.csv": 2}

    def test_a_record_with_no_size_is_not_judged(self, tmp_path):
        store = FolderStore(tmp_path / "store")
        (tmp_path / "x.txt").write_bytes(b"hello")
        stored = store.put(tmp_path / "x.txt")
        assert store.incomplete(stored.content_hash, None) is None
        assert store.incomplete(stored.content_hash, 5) is None
        assert "has 5 bytes where its record says 9" in store.incomplete(stored.content_hash, 9)
        assert "has 5 bytes of x.txt where its record says 9" in store.incomplete(stored.content_hash, 9, {"x.txt": 9})


class TestAnObjectNotThereYet:
    def test_update_says_what_to_do_on_each_side(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        machine("b")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        machine("a")
        second = _snapshot_again(rates, 4.2)
        machine("b")
        default_store().delete(second.assets["treasury"]["content_hash"])  # not synced to B at all
        result = CliRunner().invoke(main, ["update", "--project-dir", str(forecast)])
        assert result.exit_code == 1
        assert "lost: acme/rates:treasury: the snapshot at" in result.output
        assert "(None)" not in result.output
        assert "a sync that has not finished" in result.output
        assert "on the machine that put it in the store, see that its sync has sent everything" in result.output
        assert "Making the snapshot again" not in result.output


class TestASyncServicesCopies:
    def test_a_copy_of_a_record_and_of_origins_is_passed_over(self, drive):
        work, machine, rates = drive
        first = snapshot.make(rates).snapshot
        second = _snapshot_again(rates, 4.2)
        folder = second.path.parent
        shutil.copy(second.path, folder / f"{second.path.stem} (1).json")
        shutil.copy(folder / "origins", folder / "origins (1)")
        store = default_store()
        assert [taken.made_at for taken in snapshot.readable_snapshots(store)[0]] == [first.made_at, second.made_at]
        assert len(snapshot.all_snapshots(store)) == 2
        plan = lock.plan_gc(store, keep_days=0)
        assert len(plan.snapshots_kept) + len(plan.snapshots_delete) == 2
        assert not is_record_name(f"{second.path.stem} (1).json") and is_record_name(second.path.name)

    def test_the_catalog_lists_a_version_once(self, drive):
        from chartbook import versions

        work, machine, rates = drive
        taken = snapshot.make(rates).snapshot
        shutil.copy(taken.path, taken.path.with_name(f"{taken.path.stem} (1).json"))
        listed = [t for t in snapshot.readable_snapshots(default_store())[0] if t.pipeline == "acme/rates"]
        assert len(listed) == 1
        assert versions  # the Versions page lists what readable_snapshots gives

    def test_a_copy_of_a_note_of_a_lockfile_is_passed_over(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        copy = note.with_name(f"{note.stem} (1).json")
        copy.write_text(json.dumps({"lockfile": "/elsewhere/chartbook.lock", "hashes": ["sha256:" + "0" * 64]}))
        assert [str(root.lockfile) for root in store.roots()] == [str(forecast / lock.LOCK_FILE)]


class TestOnePersonsTwoMachines:
    def test_gc_on_one_keeps_what_the_others_lockfile_at_the_same_path_pins(self, drive):
        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        new = _snapshot_again(rates, 4.2)
        project = work / "projects" / "forecast"  # the same path on both machines

        machine("b")  # B's lockfile pins the old snapshot
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        on_b = (project / lock.LOCK_FILE).read_bytes()

        machine("a")  # A's, at the same path on A, the newest
        _forecast(project, {"acme/rates": {}})
        (project / lock.LOCK_FILE).unlink()
        assert lock.pin(project).problems == []
        assert _pinned_commit(project) == new.commit

        store = default_store()
        for forget_missing in (False, True):
            # gc on A: what B's lockfile pins is kept, the old snapshot and its bytes
            plan = lock.plan_gc(store, forget_missing=forget_missing, recent_seconds=0, keep_days=0)
            assert [taken.made_at for taken, _ in plan.snapshots_delete] == []
            assert old.assets["treasury"]["content_hash"] not in {h for h, _ in plan.delete}
            assert [root.lockfile for root in plan.elsewhere] == [project / lock.LOCK_FILE]
            kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
            assert kept[old.made_at] == "a lockfile not read here, another machine's, named what it holds"
        assert len(store.roots()) == 2  # one note for each machine
        lock.run_gc(lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0), store)

        machine("b")
        (project / lock.LOCK_FILE).write_bytes(on_b)
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.verify(project).problems == []

    def test_gc_says_whose_it_is(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        machine("b")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        machine("a")
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 0
        assert f"{forecast / lock.LOCK_FILE}  (on another machine, " in result.output
        assert "not read here; its pins are kept)" in result.output

    def test_a_note_from_before_notes_named_their_machine(self, drive):
        """It may be another machine's, at the same path: its pins are kept, even with --forget-missing,
        until this machine's own note names all of them."""
        from chartbook.store import root_name

        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        _snapshot_again(rates, 4.2)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        stored = json.loads(note.read_text())
        assert stored["machine"] and stored["host"]
        older = store.root / "roots" / root_name(forecast / lock.LOCK_FILE)
        older.write_text(json.dumps({"lockfile": stored["lockfile"], "hashes": sorted(old.asset_hashes())}))
        (forecast / lock.LOCK_FILE).unlink()  # the project is gone from this machine
        plan = lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0)
        assert [root.machine for root in plan.elsewhere] == [""]
        assert old.made_at not in [taken.made_at for taken, _ in plan.snapshots_delete] and plan.forget == [forecast / lock.LOCK_FILE]
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert "(noted before notes named their machine, so perhaps another machine's: not read here" in result.output
        lock.pin(forecast)
        assert older.is_file()  # this machine pins something else
        older.write_text(json.dumps({"lockfile": stored["lockfile"], "hashes": stored["hashes"]}))
        lock.update(forecast)
        assert [path.name for path in (store.root / "roots").glob("*.json")] == [note.name]

    def test_the_name_of_this_machine_is_kept(self, drive):
        from chartbook.config import get_machine_id

        work, machine, rates = drive
        first = get_machine_id()
        assert first == get_machine_id() and len(first) == 32
        machine("b")
        assert get_machine_id() != first


class TestStoreInfo:
    def test_it_says_which_store_and_what_set_it(self, drive, monkeypatch):
        work, machine, rates = drive
        result = CliRunner().invoke(main, ["store", "info"])
        assert result.exit_code == 0
        assert f"Store: {work / 'Google Drive' / 'chartbook-store'}" in result.output
        assert "set by CHARTBOOK_STORE" in result.output
        assert "Cache: " in result.output

    def test_from_each_layer(self, drive, monkeypatch, tmp_path):
        from chartbook import config

        work, machine, rates = drive
        monkeypatch.delenv("CHARTBOOK_STORE")
        result = CliRunner().invoke(main, ["store", "info"])
        assert f"Store: {config.get_global_config_dir() / 'store'}" in result.output
        assert "the default" in result.output and "nothing is there yet" in result.output
        system = tmp_path / "system.toml"
        system.write_text(tomli_w.dumps({"store": {"url": str(work / "org-store")}}))
        monkeypatch.setenv("CHARTBOOK_SYSTEM_SETTINGS", str(system))
        result = CliRunner().invoke(main, ["store", "info"])
        assert f"Store: {work / 'org-store'}" in result.output and f"in {system}, the organization's" in result.output
        user = config.get_global_settings_path()
        user.parent.mkdir(parents=True, exist_ok=True)
        user.write_text(tomli_w.dumps({"store": {"url": str(work / "my-store")}}))
        result = CliRunner().invoke(main, ["store", "info"])
        assert f"Store: {work / 'my-store'}" in result.output and f"in {user}, your settings" in result.output

    def test_the_group_does_not_call_it_the_local_folder(self):
        result = CliRunner().invoke(main, ["store", "--help"])
        assert "local folder" not in result.output and "info" in result.output


class TestAPathDependencyOnAnotherMachine:
    @pytest.fixture
    def cloned(self, drive):
        """On A, acme/forecast depends on ../rates and is pinned; B has a clone of forecast and no rates folder."""
        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"rates": {"path": "../rates"}})
        assert lock.pin(forecast).problems == []
        machine("b")
        clone = work / "b" / "forecast"
        shutil.copytree(forecast, clone)
        return clone

    def test_check_warns_and_names_the_entry_by_its_id(self, cloned):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        with warnings.catch_warnings(record=True) as said:
            warnings.simplefilter("always")
            problems = check_dependencies(load_manifest(cloned), cloned)
        assert problems == []
        (warning,) = [w for w in said if "is not on this machine" in str(w.message)]
        assert 'named by its ID' in str(warning.message)
        assert '"rates" = { id = "acme/rates" }' in str(warning.message)
        assert lock.verify(cloned).problems == []

    def test_check_fails_when_nothing_of_it_is_pinned(self, cloned):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        (cloned / lock.LOCK_FILE).unlink()
        (problem,) = check_dependencies(load_manifest(cloned), cloned)
        assert "directory not found" in problem.message and "Nothing of it is pinned" in problem.message
        assert '"rates" = { id = "<its ID>" }' in problem.message

    def test_check_fails_when_the_store_lacks_a_pin(self, cloned):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        (record,) = [r for r in lock.read_lock(cloned).assets.values() if r.get("content_hash")]
        held = default_store().get(record["content_hash"]) / "treasury.parquet"
        os.chmod(held, stat.S_IRUSR | stat.S_IWUSR)
        held.write_bytes(b"PAR1")  # not synced to this machine yet
        (problem,) = check_dependencies(load_manifest(cloned), cloned)
        assert "the store does not have all that the lockfile pins of it" in problem.message
        default_store().delete(record["content_hash"])
        (problem,) = check_dependencies(load_manifest(cloned), cloned)
        assert "the store does not have all that the lockfile pins of it" in problem.message

    def test_check_says_a_store_it_cannot_read(self, cloned):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        (default_store().root / "store.json").write_text('{"sch')  # half synced
        (problem,) = check_dependencies(load_manifest(cloned), cloned)
        assert "the store cannot be read" in problem.message

    def test_a_path_that_is_a_file_is_not_another_machines_folder(self, cloned):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        (cloned.parent / "rates").write_text("not a folder")
        (problem,) = check_dependencies(load_manifest(cloned), cloned)
        assert problem.message.startswith("directory not found") and "named by its ID" not in problem.message

    def test_update_names_the_entry_by_its_id(self, cloned):
        report = lock.update(cloned)
        (problem,) = report.problems
        assert problem.status == "no_snapshot" and "there is no folder at" in problem.detail
        assert '"rates" = { id = "acme/rates" }' in problem.detail


class TestAFirstReadThatPinsNothing:
    def test_writes_no_lockfile(self, drive, monkeypatch):
        work, machine, rates = drive
        forecast = _forecast(work / "a" / "forecast", {"acme/nothing": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/nothing:treasury")
        assert not (forecast / lock.LOCK_FILE).exists()

    def test_one_that_pins_writes_it(self, drive, monkeypatch):
        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        assert (forecast / lock.LOCK_FILE).is_file()
