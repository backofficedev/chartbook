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

from chartbook import config, data, lock, snapshot
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
        # What the operating system calls the machine: its own for each
        monkeypatch.setattr(config, "_os_machine_identity", lambda: f"test:{letter}")
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
        assert unsynced_part(tmp_path, 10, {"b.parquet": 10}) == ("has 0 bytes of b.parquet where its record says 10", True)
        # A name not there, beside files of other sizes: a directory pinned before records listed its files
        assert unsynced_part(tmp_path, 10, {"c.parquet": 10}) is None
        assert unsynced_part(tmp_path, 20, {"c.parquet": 20}) == ("has 10 bytes where its record says 20", True)

    def test_a_files_own_name_not_there_yet(self, tmp_path):
        """The same bytes under another name only: this name is on its way, and the folder is not read instead."""
        (tmp_path / "a.csv").write_bytes(b"x" * 10)
        assert unsynced_part(tmp_path, 10, {"b.csv": 10}) == ("does not have b.csv yet", True)

    def test_a_file_whatever_it_is_called(self, tmp_path):
        (tmp_path / "._x").write_bytes(b"x" * 10)  # a name a directory's hash passes over
        assert unsynced_part(tmp_path, 10, {"._x": 10}) is None

    def test_a_folder_with_a_file_not_there_yet(self, tmp_path):
        (tmp_path / "year=2024").mkdir()
        (tmp_path / "year=2024" / "part-0.parquet").write_bytes(b"x" * 10)
        listed = {"year=2024/part-0.parquet": 10, "year=2025/part-0.parquet": 15}
        assert unsynced_part(tmp_path, 25, listed, every=True) == ("does not have year=2025/part-0.parquet yet", True)
        assert unsynced_part(tmp_path, 25) == ("has 10 bytes where its record says 25", True)  # a glob's, summed
        (tmp_path / "year=2025").mkdir()
        (tmp_path / "year=2025" / "part-0.parquet").write_bytes(b"x" * 15)
        assert unsynced_part(tmp_path, 25, listed, every=True) is None and unsynced_part(tmp_path, 25) is None

    def test_a_folder_with_a_file_its_record_does_not_list(self, tmp_path):
        """A sync service's copy inside a directory's object, which a reader would read as data."""
        (tmp_path / "part-0.parquet").write_bytes(b"x" * 10)
        (tmp_path / "part-0 (1).parquet").write_bytes(b"x" * 10)
        assert unsynced_part(tmp_path, 10, {"part-0.parquet": 10}, every=True) == (
            "holds part-0 (1).parquet, which its record does not list", False
        )
        assert unsynced_part(tmp_path, 10, {"part-0.parquet": 10}) is None  # one file's other names are other pins'

    def test_a_link_is_not_judged(self, tmp_path):
        (tmp_path / "elsewhere.txt").write_bytes(b"x" * 3)
        (tmp_path / "object").mkdir()
        (tmp_path / "object" / "a.txt").symlink_to(tmp_path / "elsewhere.txt")
        assert unsynced_part(tmp_path / "object", 10, {"a.txt": 10}) is None
        assert unsynced_part(tmp_path / "object", 10) is None

    def test_an_empty_folder_is_not_whole(self, tmp_path):
        assert unsynced_part(tmp_path, 0) == ("has none of its files yet", True)

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

    def test_a_copy_of_a_note_of_a_lockfile_keeps_what_it_recorded(self, drive):
        """The other side of a conflict over a note: a note only ever adds to what is kept."""
        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        new = _snapshot_again(rates, 4.2)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        copy = note.with_name(f"{note.stem} (1).json")
        shutil.copy(note, copy)  # the service kept the other side as a copy
        stored = json.loads(note.read_text())
        note.write_text(json.dumps({**stored, "hashes": sorted(new.asset_hashes())}))
        shutil.rmtree(project)  # on a drive that is not plugged in, say
        plan = lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0)
        assert old.made_at not in [taken.made_at for taken, _ in plan.snapshots_delete]
        assert [root.note for root in plan.elsewhere] == [copy.name] and plan.forget == [project / lock.LOCK_FILE]
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--forget-missing"])
        assert f"(a sync service's copy of a note: what it recorded at its last pin is kept; note {store.root}/roots/{copy.name})" in result.output

    def test_a_copy_that_is_no_note_is_passed_over_with_a_warning(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        note.with_name(f"{note.stem} (1).json").write_text('{"lock')  # half a copy
        with pytest.warns(UserWarning, match="is not read: it is not a note the store wrote, and not a copy of one"):
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

    def test_a_home_copied_to_another_machine_does_not_bring_its_name(self, drive):
        """A migration, a restored backup, a cloned virtual machine: both homes hold one machine-id file."""
        from chartbook.config import get_machine_id

        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        _snapshot_again(rates, 4.2)
        project = work / "projects" / "forecast"
        on_a = get_machine_id()
        machine("b")
        (work / "home-b" / ".chartbook").mkdir(parents=True)
        shutil.copy(work / "home-a" / ".chartbook" / "machine-id", work / "home-b" / ".chartbook" / "machine-id")
        assert get_machine_id() != on_a  # another machine: a name of its own beside the copied one
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        on_b = (project / lock.LOCK_FILE).read_bytes()

        machine("a")
        assert get_machine_id() == on_a
        _forecast(project, {"acme/rates": {}})
        (project / lock.LOCK_FILE).unlink()
        assert lock.pin(project).problems == []
        store = default_store()
        assert len(store.roots()) == 2
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert old.made_at not in [taken.made_at for taken, _ in plan.snapshots_delete]
        lock.run_gc(plan, store)
        machine("b")
        (project / lock.LOCK_FILE).write_bytes(on_b)
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.verify(project).problems == []

    def test_gc_reads_this_machines_lockfile_under_an_old_note(self, drive):
        """A note from before notes named their machine, and the lockfile changed since by a pull: both keep."""
        from chartbook.store import root_name

        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        mid = _snapshot_again(rates, 4.15, made_at="2020-06-01T00:00:00.000000Z")
        _snapshot_again(rates, 4.2)
        store = default_store()
        colleague = _forecast(work / "a" / "colleague", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(colleague).problems == []
        pulled = (colleague / lock.LOCK_FILE).read_bytes()  # what a colleague committed
        store.remove_root(colleague / lock.LOCK_FILE)
        shutil.rmtree(colleague)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": mid.commit[:7]}})
        assert lock.pin(forecast).problems == []
        (note,) = (store.root / "roots").glob("*.json")
        stored = json.loads(note.read_text())
        note.unlink()  # as an older ChartBook wrote it: named by the path alone
        (store.root / "roots" / root_name(forecast / lock.LOCK_FILE)).write_text(
            json.dumps({"lockfile": stored["lockfile"], "hashes": stored["hashes"]})
        )
        _forecast(forecast, {"acme/rates": {"commit": old.commit[:7]}})  # git pull
        (forecast / lock.LOCK_FILE).write_bytes(pulled)
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        deleted = [taken.made_at for taken, _ in plan.snapshots_delete]
        assert old.made_at not in deleted and mid.made_at not in deleted
        assert plan.read_here == [forecast / lock.LOCK_FILE]
        lock.run_gc(plan, store)
        assert lock.verify(forecast).problems == []

    def test_an_old_note_stays_however_this_machine_pins(self, drive):
        """It may be the other machine's, at the same path: this machine pinning the same, then moving on, does not let it go."""
        from chartbook.store import root_name

        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        _snapshot_again(rates, 4.2)
        project = work / "projects" / "forecast"
        machine("b")
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        stored = json.loads(note.read_text())
        note.unlink()  # B pinned with an older ChartBook
        older = store.root / "roots" / root_name(project / lock.LOCK_FILE)
        older.write_text(json.dumps({"lockfile": stored["lockfile"], "hashes": stored["hashes"]}))
        machine("a")
        (project / lock.LOCK_FILE).unlink()
        assert lock.pin(project).problems == []  # A pins the old one too
        _forecast(project, {"acme/rates": {}})
        lock.update(project)  # and moves on
        assert older.is_file()
        plan = lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0)
        assert old.made_at not in [taken.made_at for taken, _ in plan.snapshots_delete]
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert f"(noted before notes named their machine, so perhaps another machine's: what it recorded at its last pin is kept; the lockfile here at that path is read as well; note {store.root}/roots/{older.name})" in result.output

    def test_gc_says_whose_it_is(self, drive, monkeypatch):
        import socket

        work, machine, rates = drive
        snapshot.make(rates)
        machine("b")
        monkeypatch.setattr(socket, "gethostname", lambda: "machine-b.local")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        machine("a")
        monkeypatch.setattr(socket, "gethostname", lambda: "machine-a.local")
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 0
        assert f"{forecast / lock.LOCK_FILE}  (on another machine, machine-b.local: what it recorded at its last pin is kept;" in result.output
        assert f"note {default_store().root}/roots/" in result.output
        monkeypatch.setattr(socket, "gethostname", lambda: "machine-b.local")  # a machine named as the other is
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert "(noted by machine-b.local under another machine name than this one's now: " in result.output

    def test_the_name_of_this_machine_is_kept(self, drive):
        from chartbook.config import get_machine_id

        work, machine, rates = drive
        first = get_machine_id()
        assert first == get_machine_id() and len(first) == 32
        machine("b")
        assert get_machine_id() != first

    def test_with_no_home_folder_a_name_is_still_given(self, drive, monkeypatch):
        from chartbook.config import get_machine_id

        def no_home():
            raise RuntimeError("Could not determine home directory.")

        monkeypatch.setattr(config, "get_global_config_dir", no_home)
        assert len(get_machine_id()) == 32 and get_machine_id() == get_machine_id(create=False)


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

    def test_no_user_name_or_password_is_printed(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_STORE", "s3://bucket/p?endpoint=https://user:s3cr3t@minio.example.org")
        result = CliRunner().invoke(main, ["store", "info"])
        assert "Store: s3://bucket/p?endpoint=https://minio.example.org" in result.output and "s3cr3t" not in result.output
        monkeypatch.setenv("CHARTBOOK_STORE", "https://user:tok@example.org/store")
        result = CliRunner().invoke(main, ["store", "info"])
        assert "Store: https://example.org/store" in result.output and "tok@" not in result.output

    def test_an_endpoint_with_a_password_is_refused_without_showing_it(self):
        pytest.importorskip("boto3")
        from chartbook.stores.s3 import _parse_url

        with pytest.raises(ValueError, match="has an endpoint with a user name in it") as raised:
            _parse_url("s3://bucket/p?endpoint=https://user:s3cr3t@minio.example.org")
        assert "s3cr3t" not in str(raised.value)
        with pytest.raises(ValueError, match="Credentials never go in the URL") as raised:
            _parse_url("s3://key:s3cr3t@bucket/p")
        assert "s3cr3t" not in str(raised.value)

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
        (warning,) = [w for w in said if "on this machine (another machine's folder, or one that has moved)" in str(w.message)]
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

    def test_check_says_a_store_it_cannot_open(self, cloned, monkeypatch):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        for url in ("s3://Bad_Bucket/x", "gs://bucket/x"):
            monkeypatch.setenv("CHARTBOOK_STORE", url)
            (problem,) = check_dependencies(load_manifest(cloned), cloned)
            assert "the store cannot be opened" in problem.message
            assert "does not have all that the lockfile pins" not in problem.message

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


class TestAVersionsSite:
    def test_is_built_again_once_the_store_has_it(self, drive):
        """A catalog's site of a version whose object had not synced is not kept as failed for good."""
        from chartbook import versions

        work, machine, rates = drive
        taken = snapshot.make(rates).snapshot
        store = default_store()
        assert store.delete(taken.assets["treasury"]["content_hash"])  # not synced here yet
        first = versions.render(taken, store)
        assert not first.built
        store.put(rates / "_data" / "treasury.parquet", links=("copy",))  # the sync finishes
        second = versions.render(taken, store)
        # Laid out from the store this time; whatever its build said is kept now
        assert second.now and "not all in the store yet" not in second.why
        assert "not all in the store yet" in first.why
        assert not versions.render(taken, store).now

    def test_a_file_not_whole_is_not_laid_out(self, drive, tmp_path):
        work, machine, rates = drive
        taken = snapshot.make(rates).snapshot
        held = _object_file(taken)
        held.write_bytes(held.read_bytes()[:10])
        with pytest.raises(snapshot.StoreNotReadyError, match="not fully synced yet"):
            snapshot.materialize(taken, tmp_path / "laid", default_store())
        assert not (tmp_path / "laid" / "_data" / "treasury.parquet").exists()


class TestAFileADirectorysRecordDoesNotList:
    def test_is_said_by_frozen_and_by_a_read(self, drive, monkeypatch):
        """A sync service's copy inside a directory's object would be read as more rows."""
        import polars as pl

        work, machine, rates = drive
        (rates / "_data" / "parts").mkdir()
        pl.DataFrame({"a": [1, 2]}).write_parquet(rates / "_data" / "parts" / "part-0.parquet")
        (rates / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
            "treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."},
            "parts": {"path": "./_data/parts", "docs": "Parts."},
        }}))
        _commit(rates, "Parts")
        taken = snapshot.make(rates).snapshot
        machine("b")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        held = default_store().get(taken.assets["parts"]["content_hash"])
        os.chmod(held, stat.S_IRWXU)
        shutil.copy(held / "part-0.parquet", held / "part-0 (1).parquet")
        (problem,) = lock.verify(forecast).problems
        assert "holds part-0 (1).parquet, which its record does not list" in problem.message
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="Remove that file from the object's folder"):
            data.load("acme/rates:parts")


class TestAFilesOwnNameNotThereYet:
    def test_the_folder_is_not_read_in_its_place(self, tmp_path):
        from chartbook.resolve import _held

        store = FolderStore(tmp_path / "store")
        (tmp_path / "a.csv").write_text("x,y\n1,2\n")
        (tmp_path / "b.csv").write_text("x,y\n1,2\n")
        stored = store.put(tmp_path / "a.csv", links=("copy",))
        assert store.put(tmp_path / "b.csv", links=("copy",)).content_hash == stored.content_hash
        held = store.get(stored.content_hash)
        os.chmod(held, stat.S_IRWXU)
        (held / "b.csv").unlink()  # this name not synced yet
        record = {
            "id": "acme/x:b", "content_hash": stored.content_hash, "size_bytes": stored.size_bytes,
            "location": {"kind": "file", "path": "./_data/b.csv"},
        }
        with pytest.raises(AssetNotPinnedError, match="does not have b.csv yet"):
            _held(store, record)
