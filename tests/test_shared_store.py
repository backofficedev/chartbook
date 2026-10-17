"""A store that two machines share through a synced folder (Google Drive, Dropbox, OneDrive).

Two machines are two home folders, and two working folders, with one store
folder between them, as a sync service keeps it on each. What the service
leaves in it: a file there before all of its bytes, an object not there
yet, and a copy of a file changed in two places under a name of its own.
And one person's two machines can have a lockfile at the same path.
"""

import json
import os
import re
import shutil
import socket
import stat
import uuid
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
    monkeypatch.delenv("CI", raising=False)  # these are people's machines, whatever runs the tests

    def machine(letter: str) -> Path:
        home = work / f"home-{letter}"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        # What the operating system calls the machine: its own for each
        monkeypatch.setattr(config, "_os_machine_identity", lambda: f"test:{letter}")
        monkeypatch.setattr(socket, "gethostname", lambda: f"machine-{letter}.local")
        # And the hardware address of a network interface: a machine's own (a universal, unicast one)
        monkeypatch.setattr(uuid, "getnode", lambda: 0x0C0000000000 + sum(map(ord, letter)))
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


def _forget_whole() -> None:
    """This process forgets the objects it found whole: a test changes one after, as no store does."""
    from chartbook import store as store_module

    store_module._found_whole.clear()


def _cut(held: Path, data: bytes) -> None:
    """Write part of an object's file, as a sync in progress leaves it."""
    held.write_bytes(data)
    _forget_whole()


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
        _cut(held, whole[: len(whole) // 2])  # as a sync in progress leaves it
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
        _cut(held, whole[:100])  # the same pin, read on a machine whose sync is behind
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
        _cut(held, whole[:10])
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
        _cut(held, b"")  # the name this pin reads, made and not filled yet
        (problem,) = lock.verify(forecast).problems
        assert "has 0 bytes of treasury.parquet where its record says" in problem.message

    def test_update_at_the_snapshot_it_is_pinned_to_says_it_once(self, half):
        forecast, first, second, held, whole = half
        held.write_bytes(whole)
        lock.update(forecast)
        _cut(held, whole[:10])
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
        from chartbook.hashing import hash_file

        (tmp_path / "a.csv").write_bytes(b"x" * 10)
        content_hash = hash_file(tmp_path / "a.csv").content_hash
        assert unsynced_part(tmp_path, 10, {"b.csv": 10}, content_hash=content_hash) == ("does not have b.csv yet", True)

    def test_a_directory_pinned_before_its_files_were_listed_with_one_file(self, tmp_path):
        """One file of the directory's size, which is not the asset's bytes under another name: read as the folder."""
        (tmp_path / "part-0.parquet").write_bytes(b"x" * 10)
        assert unsynced_part(tmp_path, 10, {"parts": 10}, content_hash="sha256:" + "0" * 64) is None

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
        what, waiting = unsynced_part(tmp_path, 10, {"part-0.parquet": 10}, every=True)
        assert what.startswith("holds part-0 (1).parquet, which its record does not list") and not waiting
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

    def test_a_copy_that_cannot_be_read_stops_gc_and_names_itself(self, drive):
        """Half a copy may be the only record of the other side's pins: nothing is removed until it is read or gone."""
        from chartbook.store import StoreError

        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        copy = note.with_name(f"{note.stem} (1).json")
        copy.write_text('{"lock')  # half a copy
        with pytest.raises(StoreError, match=rf"remove roots/{re.escape(copy.name)} if it is a copy nobody needs"):
            lock.plan_gc(store)
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 1 and "Nothing was removed." in result.output


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
            assert kept[old.made_at] == "a lockfile not read here, another machine's, pins it"
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
        assert "Store: s3://bucket/p?endpoint=…" in result.output and "s3cr3t" not in result.output
        monkeypatch.setenv("CHARTBOOK_STORE", "https://user:tok@example.org/store")
        result = CliRunner().invoke(main, ["store", "info"])
        assert "Store: https://example.org/store" in result.output and "tok@" not in result.output

    def test_an_endpoint_with_a_password_is_refused_without_showing_it(self):
        pytest.importorskip("boto3")
        from chartbook.stores.s3 import _parse_url

        with pytest.raises(ValueError, match="has an '@' in it") as raised:
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
        _cut(held, b"PAR1")  # not synced to this machine yet
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
        _forget_whole()
        (problem,) = lock.verify(forecast).problems
        assert "holds part-0 (1).parquet, which its record does not list" in problem.message
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="remove that file from the object's folder"):
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


class TestAMachineThatOnlyReads:
    """B clones the project and only reads: `--frozen`, `data.load`. A moves on and clears the store."""

    @pytest.fixture
    def reader(self, drive):
        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        machine("b")
        clone = work / "b" / "forecast"
        shutil.copytree(project, clone)
        return work, machine, rates, old, project, clone

    def _a_moves_on_and_clears(self, machine, rates, project) -> None:
        machine("a")
        _snapshot_again(rates, 4.2)
        assert lock.update(project).problems == []
        store = default_store()
        lock.run_gc(lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0), store)

    def test_frozen_keeps_its_pins(self, reader):
        work, machine, rates, old, project, clone = reader
        result = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(clone)])
        assert result.exit_code == 0
        assert "Nothing written but the store's note that this machine reads these pins." in result.output
        again = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(clone)])
        assert "all in the store. Nothing written." in again.output  # the note names it all already
        self._a_moves_on_and_clears(machine, rates, project)
        machine("b")
        assert lock.verify(clone).problems == []

    def test_a_read_keeps_its_pins(self, reader, monkeypatch):
        work, machine, rates, old, project, clone = reader
        monkeypatch.chdir(clone)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        self._a_moves_on_and_clears(machine, rates, project)
        machine("b")
        assert lock.verify(clone).problems == []

    def test_frozen_says_when_the_note_cannot_be_written(self, reader):
        work, machine, rates, old, project, clone = reader
        roots = default_store().root / "roots"
        roots.chmod(0o555)  # a store this machine may only read
        try:
            result = CliRunner().invoke(main, ["pin", "--frozen", "--project-dir", str(clone)])
        finally:
            roots.chmod(0o755)
        assert result.exit_code == 0
        assert "the store's note that this machine reads these pins could not be written" in result.output


class TestACloneThatKeptItsIdentity:
    def test_one_that_kept_its_identity_has_the_same_name(self, drive, monkeypatch):
        """A cloned virtual machine with a copied home and the operating system's identity cloned too: one
        name, not told apart, as the docs say; each lasting machine needs its own identity or CHARTBOOK_MACHINE_ID."""
        from chartbook.config import get_machine_id

        work, machine, rates = drive
        on_a = get_machine_id()
        machine("b")
        monkeypatch.setattr(config, "_os_machine_identity", lambda: "test:a")
        (work / "home-b" / ".chartbook").mkdir(parents=True)
        shutil.copy(work / "home-a" / ".chartbook" / "machine-id", work / "home-b" / ".chartbook" / "machine-id")
        assert get_machine_id() == on_a
        monkeypatch.setenv("CHARTBOOK_MACHINE_ID", "machine-b")
        assert get_machine_id() == "machine-b"

    def test_an_identity_that_is_none_is_not_taken(self):
        assert not config._an_identity("uninitialized")
        assert not config._an_identity("0" * 32)
        assert not config._an_identity("")
        assert config._an_identity("4c4c4544-0042-3510-8051-b4c04f4d4e32")
        assert config._an_identity("0f1e2d3c4b5a69788796a5b4c3d2e1f0")

    def test_ioreg_by_its_full_path(self, monkeypatch):
        import subprocess
        import sys

        asked = []

        class Ran:
            stdout = '"IOPlatformUUID" = "4C4C4544-0042-3510-8051-B4C04F4D4E32"'

        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "run", lambda args, **kw: (asked.append(args), Ran())[1])
        assert config._os_machine_identity.__wrapped__() == "darwin:4c4c4544-0042-3510-8051-b4c04f4d4e32"
        assert asked[0][0] == "/usr/sbin/ioreg"

    def test_the_name_is_worked_out_once_a_process(self, drive):
        from chartbook.config import get_machine_id
        from chartbook.store import root_name

        work, machine, rates = drive
        snapshot.make(rates)
        first = get_machine_id()
        machine_id = work / "home-a" / ".chartbook" / "machine-id"
        machine_id.write_text(json.dumps({"machines": {"x": "f" * 32}}))  # changed under a running process
        assert get_machine_id() == first
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        (note,) = (default_store().root / "roots").glob("*.json")
        assert note.name == root_name(forecast / lock.LOCK_FILE, json.loads(note.read_text())["machine"])


class TestTheStoreShrinks:
    @staticmethod
    def _rates(rates: Path, value: float, when) -> snapshot.Snapshot:
        import polars as pl

        pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(rates / "_data" / "treasury.parquet")
        pl.DataFrame({"k": ["static"]}).write_parquet(rates / "_data" / "codes.parquet")
        (rates / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
            "treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."},
            "codes": {"path": "./_data/codes.parquet", "docs": "Codes that never change."},
        }}))
        (rates / "notes.txt").write_text(f"{value}\n")
        _commit(rates, f"At {value}")
        return snapshot.make(rates, made_at=when).snapshot

    def test_an_asset_that_never_changes_keeps_no_old_snapshot(self, drive):
        work, machine, rates = drive
        s1 = self._rates(rates, 1.0, "2020-01-01T00:00:00.000000Z")
        s2 = self._rates(rates, 2.0, "2020-02-01T00:00:00.000000Z")
        s3 = self._rates(rates, 3.0, "2020-03-01T00:00:00.000000Z")
        machine("b")
        assert lock.pin(_forecast(work / "b" / "forecast", {"acme/rates": {}})).problems == []  # B pins s3
        machine("a")
        self._rates(rates, 4.0, None)
        assert lock.pin(_forecast(work / "a" / "forecast", {"acme/rates": {}})).problems == []  # A pins s4
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert sorted(t.made_at for t, _ in plan.snapshots_delete) == [s1.made_at, s2.made_at]
        assert dict((t.made_at, why) for t, why in plan.snapshots_kept)[s3.made_at] == (
            "a lockfile not read here, another machine's, pins it"
        )

    def test_a_note_that_names_no_snapshots_keeps_the_newest_holding_each_object(self, drive):
        from chartbook.store import root_name

        work, machine, rates = drive
        s1 = self._rates(rates, 1.0, "2020-01-01T00:00:00.000000Z")
        s2 = self._rates(rates, 2.0, "2020-02-01T00:00:00.000000Z")
        s3 = self._rates(rates, 3.0, "2020-03-01T00:00:00.000000Z")
        self._rates(rates, 4.0, None)
        store = default_store()
        old_note = store.root / "roots" / root_name("/gone/chartbook.lock")
        old_note.parent.mkdir(parents=True, exist_ok=True)
        old_note.write_text(json.dumps({"lockfile": "/gone/chartbook.lock", "hashes": sorted(s2.asset_hashes())}))
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert sorted(t.made_at for t, _ in plan.snapshots_delete) == [s1.made_at, s3.made_at]

    def test_the_commit_left_keeps_the_snapshot_its_note_names(self, drive):
        """Checked out at an older commit and not pinned since: the note keeps what the commit left pinned."""
        work, machine, rates = drive
        s1 = snapshot.make(rates, made_at=LONG_AGO).snapshot
        (rates / "notes.txt").write_text("only the code changed\n")
        _commit(rates, "Code only")
        s2 = snapshot.make(rates, made_at="2020-02-01T00:00:00.000000Z").snapshot  # the same bytes as s1
        _snapshot_again(rates, 4.2)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": s2.commit[:7]}})
        assert lock.pin(project).problems == []
        at_s2 = (project / lock.LOCK_FILE).read_bytes()
        other = _forecast(work / "a" / "other", {"acme/rates": {"commit": s1.commit[:7]}})
        assert lock.pin(other).problems == []
        default_store().remove_root(other / lock.LOCK_FILE)
        _forecast(project, {"acme/rates": {"commit": s1.commit[:7]}})
        (project / lock.LOCK_FILE).write_bytes((other / lock.LOCK_FILE).read_bytes())  # git checkout
        shutil.rmtree(other)
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert s2.made_at not in [t.made_at for t, _ in plan.snapshots_delete]
        lock.run_gc(plan, default_store())
        _forecast(project, {"acme/rates": {"commit": s2.commit[:7]}})
        (project / lock.LOCK_FILE).write_bytes(at_s2)  # back
        assert lock.verify(project).problems == []


class TestWhatADirectorysReaderReads:
    def test_only_the_files_its_record_lists(self, drive, monkeypatch):
        """Finder's .DS_Store, Windows' Thumbs.db: in a directory's object, they break a read of the folder."""
        import polars as pl

        work, machine, rates = drive
        (rates / "_data" / "parts").mkdir()
        for i in range(2):
            pl.DataFrame({"a": [i]}).write_parquet(rates / "_data" / "parts" / f"part-{i}.parquet")
        (rates / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
            "treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."},
            "parts": {"path": "./_data/parts", "docs": "Parts."},
        }}))
        _commit(rates, "Parts")
        taken = snapshot.make(rates).snapshot
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        held = default_store().get(taken.assets["parts"]["content_hash"])
        os.chmod(held, stat.S_IRWXU)
        (held / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1" + b"\x00" * 600)
        (held / "Thumbs.db").write_bytes(b"x" * 10)
        monkeypatch.chdir(forecast)
        assert lock.verify(forecast).problems == []
        assert sorted(data.load("acme/rates:parts").collect()["a"].to_list()) == [0, 1]
        assert sorted(data.load("acme/rates:parts", format="pandas")["a"].to_list()) == [0, 1]
        assert sorted(data.sql("select a from {acme/rates:parts}").collect()["a"].to_list()) == [0, 1]


class TestNoUserNameOrPasswordIsShown:
    @pytest.mark.parametrize("url, secret", [
        ("s3://AKIAEXAMPLE:wJal/K7MDENG/bPxRfi@bucket/p", "wJal"),
        ("s3://bucket/p?endpoint=https://minioadmin:pa/ss@minio.example.org", "pa/ss"),
        ("s3://bucket/p?endpoint=user:s3cr3t@minio.example.org", "s3cr3t"),
        ("//user:pw0rd@host/share", "pw0rd"),
        ("s3://AKIAEXAMPLE:pa#ss@bucket/p", "pa#ss"),
        ("https://user:t0k/en@example.org/store", "t0k"),
    ])
    def test_in_a_url_shown(self, url, secret):
        assert secret not in config.shown_store_url(url)

    def test_a_folder_with_an_at_sign_is_as_it_is(self):
        path = "/Users/x/Library/CloudStorage/GoogleDrive-me@example.org/My Drive/store"
        assert config.shown_store_url(path) == path

    @pytest.mark.parametrize("url", [
        "s3://AKIAEXAMPLE:wJal/K7MDENG@bucket/p",
        "s3://bucket/p?endpoint=user:s3cr3t@minio.example.org",
        "s3://bucket/p?endpoint=https://minioadmin:pa/ss@minio.example.org",
    ])
    def test_refused_by_the_s3_store_without_showing_it(self, url):
        pytest.importorskip("boto3")
        from chartbook.stores.s3 import _parse_url

        with pytest.raises(ValueError) as raised:
            _parse_url(url)
        assert not any(secret in str(raised.value) for secret in ("wJal", "s3cr3t", "pa/ss"))

    def test_in_what_an_sdk_says(self):
        said = "Could not connect to the endpoint URL: \"https://minioadmin:pa/ss@minio.example.org/b\""
        assert "pa/ss" not in config.without_credentials(said) and "minio.example.org/b" in config.without_credentials(said)


class TestGcAfterTheYes:
    def test_a_lockfile_back_before_the_yes_is_not_forgotten(self, drive):
        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        _snapshot_again(rates, 4.2)
        away = work / "a" / "away"
        shutil.move(project, away)  # its drive unplugged
        store = default_store()
        plan = lock.plan_gc(store, forget_missing=True, recent_seconds=0, keep_days=0)
        assert plan.forget == [project / lock.LOCK_FILE]
        shutil.move(away, project)  # plugged back in before the yes
        lock.run_gc(plan, store)
        assert len(store.roots()) == 1
        lock.run_gc(lock.plan_gc(store, recent_seconds=0, keep_days=0), store)
        assert lock.verify(project).problems == []


class TestWhatGcReadsAndPrints:
    def test_another_machines_path_is_never_opened(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        machine("b")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        machine("a")
        opened = []
        original = lock.read_lock
        try:
            lock.read_lock = lambda path: (opened.append(str(path)), original(path))[1]
            plan = lock.plan_gc(default_store())
        finally:
            lock.read_lock = original
        assert opened == [] and plan.read_here == []

    def test_a_notes_words_are_printed_without_control_characters(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        machine("b")
        forecast = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        (note,) = (default_store().root / "roots").glob("*.json")
        stored = json.loads(note.read_text())
        note.write_text(json.dumps({**stored, "host": "evil\x1b[2J\nhost", "lockfile": stored["lockfile"] + "\x07"}))
        machine("a")
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert "\x1b" not in result.output and "\x07" not in result.output and "evil?[2J?host" in result.output


def _parts(rates: Path, writer) -> Path:
    """acme/rates with a directory dataframe, `parts`, written by *writer*, and committed."""
    parts = rates / "_data" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    writer(parts)
    (rates / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {
        "treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."},
        "parts": {"path": "./_data/parts", "docs": "Parts."},
    }}))
    _commit(rates, "Parts")
    return parts


class TestADirectorysListedFiles:
    @pytest.mark.parametrize("side", ["_SUCCESS", ".part-0.parquet.crc", "_common_metadata"])
    def test_side_files_are_not_read_as_data(self, drive, monkeypatch, side):
        """Spark's _SUCCESS, Hadoop's .crc: listed with the directory's files, and passed over as a folder scan does."""
        import polars as pl

        work, machine, rates = drive

        def writer(parts):
            pl.DataFrame({"a": [1, 2]}).write_parquet(parts / "part-0.parquet")
            (parts / side).write_bytes(b"" if side == "_SUCCESS" else b"crc\x00\x01")

        _parts(rates, writer)
        taken = snapshot.make(rates).snapshot
        assert side in [entry["path"] for entry in taken.assets["parts"]["files"]]
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:parts").collect().height == 2
        assert len(data.load("acme/rates:parts", format="pandas")) == 2
        assert data.sql("select count(*) as n from {acme/rates:parts}").collect()["n"][0] == 2

    def test_a_name_with_a_colon_is_read(self, drive, monkeypatch):
        import polars as pl

        work, machine, rates = drive

        def writer(parts):
            pl.DataFrame({"a": [1]}).write_parquet(parts / "part-2024-01-01T00:00:00.parquet")
            pl.DataFrame({"a": [2]}).write_parquet(parts / "part-plain.parquet")

        _parts(rates, writer)
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        monkeypatch.chdir(forecast)
        assert sorted(data.load("acme/rates:parts").collect()["a"].to_list()) == [1, 2]

    def test_a_listed_path_that_is_no_path_in_the_object_is_refused(self, drive, monkeypatch):
        from chartbook.resolve import _held
        from chartbook.store import StoreError

        work, machine, rates = drive
        store = default_store()
        (work / "x").mkdir()
        (work / "x" / "a.parquet").write_bytes(b"x" * 3)
        stored = store.put(work / "x")
        record = {
            "id": "acme/x:d", "content_hash": stored.content_hash, "size_bytes": 3,
            "location": {"kind": "file", "path": "./_data/x"},
            "files": [{"path": "../../a.parquet", "size_bytes": 3, "content_hash": "sha256:" + "0" * 64}],
        }
        record_ok = {**record, "files": [{"path": "a.parquet", "size_bytes": 3, "content_hash": "sha256:" + "0" * 64}]}
        assert _held(store, record_ok).files == (store.get(stored.content_hash) / "a.parquet",)
        with pytest.raises((StoreError, AssetNotPinnedError), match="not a plain path"):
            _held(store, record)

    def test_an_old_record_with_one_file_is_hashed_once(self, drive, monkeypatch):
        import polars as pl

        from chartbook import hashing

        work, machine, rates = drive
        _parts(rates, lambda parts: pl.DataFrame({"a": [1, 2]}).write_parquet(parts / "part-0.parquet"))
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        lockfile = forecast / lock.LOCK_FILE
        document = json.loads(lockfile.read_text())
        for record in document["records"]:
            if (record.get("location") or {}).get("path", "").endswith("parts"):
                del record["files"]  # as pinned before records listed a directory's files
        lockfile.write_text(json.dumps(document, indent=1))
        hashed = []
        real = hashing.hash_file
        monkeypatch.setattr(hashing, "hash_file", lambda *a, **k: (hashed.append(a[0]), real(*a, **k))[1])
        monkeypatch.chdir(forecast)
        for _ in range(3):
            assert data.load("acme/rates:parts").collect().height == 2
        assert len(hashed) <= 1


class TestAReadersNote:
    def test_follows_the_lockfile_and_lets_go_of_what_it_no_longer_pins(self, drive):
        work, machine, rates = drive
        s1 = snapshot.make(rates, made_at="2020-01-01T00:00:00.000000Z").snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        clone = work / "b" / "forecast"
        for week, value in enumerate([2.0, 3.0]):
            machine("b")
            shutil.rmtree(clone, ignore_errors=True)
            shutil.copytree(project, clone)  # git pull on B
            assert lock.verify(clone, note=True).problems == []  # B reads
            machine("a")
            _snapshot_again(rates, value, made_at=f"2020-0{week + 2}-01T00:00:00.000000Z")
            assert lock.update(project).problems == []
        machine("b")
        shutil.rmtree(clone)
        shutil.copytree(project, clone)
        assert lock.verify(clone, note=True).problems == []
        (note,) = [r for r in default_store().roots() if r.lockfile == clone / lock.LOCK_FILE]
        assert [made_at for _, made_at in note.snapshots] == ["2020-03-01T00:00:00.000000Z"]
        machine("a")
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert len(plan.snapshots_kept) == 1 and s1.made_at in [t.made_at for t, _ in plan.snapshots_delete]

    def test_ci_leaves_none(self, drive, monkeypatch):
        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        machine("runner")
        monkeypatch.setenv("CI", "true")
        ci = work / "runner" / "forecast"
        shutil.copytree(project, ci)
        report = lock.verify(ci, note=True)
        assert report.problems == [] and not report.noted and report.unrooted == ""
        monkeypatch.chdir(ci)
        data.load("acme/rates:treasury").collect()
        assert [r.lockfile for r in default_store().roots()] == [project / lock.LOCK_FILE]
        monkeypatch.setenv("CHARTBOOK_MACHINE_ID", "the-runner")  # a name for it: then it leaves its note
        assert lock.verify(ci, note=True).noted

    def test_a_pull_between_the_read_and_the_note_is_noted_as_read(self, drive, monkeypatch):
        """What is noted is what was read: a later version of the lockfile is not taken as noted."""
        from chartbook import resolve

        work, machine, rates = drive
        snapshot.make(rates, made_at="2020-01-01T00:00:00.000000Z")
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        first = (project / lock.LOCK_FILE).read_bytes()
        _snapshot_again(rates, 2.0, made_at="2020-02-01T00:00:00.000000Z")
        assert lock.update(project).problems == []
        second = (project / lock.LOCK_FILE).read_bytes()
        machine("b")
        clone = work / "b" / "forecast"
        shutil.copytree(project, clone)
        (clone / lock.LOCK_FILE).write_bytes(first)
        monkeypatch.chdir(clone)
        real = resolve._note_the_read
        pulled = []

        def pull_then_note(lock_path, locked, store):
            if not pulled:
                (clone / lock.LOCK_FILE).write_bytes(second)  # git pull lands here
                os.utime(clone / lock.LOCK_FILE, ns=(1_800_000_000_000_000_000,) * 2)
                pulled.append(1)
            return real(lock_path, locked, store)

        monkeypatch.setattr(resolve, "_note_the_read", pull_then_note)
        data.load("acme/rates:treasury").collect()  # reads the first, notes it
        data.load("acme/rates:treasury").collect()  # reads the second: noted too
        (note,) = [r for r in default_store().roots() if r.lockfile == clone / lock.LOCK_FILE]
        assert [made_at for _, made_at in note.snapshots] == ["2020-02-01T00:00:00.000000Z"]

    def test_a_read_never_fails_for_its_note(self, drive, monkeypatch):
        """A store of another make whose add_root takes the old arguments."""
        from chartbook.store import FolderStore

        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []

        def old_add_root(self, lockfile, hashes):
            raise TypeError("add_root() takes 3 positional arguments but 4 were given")

        default_store().remove_root(project / lock.LOCK_FILE)  # so that the read has a note to write
        monkeypatch.setattr(FolderStore, "add_root", old_add_root)
        monkeypatch.chdir(project)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]

    def test_a_short_commit_names_no_snapshot_and_stops_no_gc(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        machine("b")
        other = _forecast(work / "b" / "forecast", {"acme/rates": {}})
        commit = lock.read_lock(project).dependencies[0]["location"]["commit"]
        (other / lock.LOCK_FILE).write_text((project / lock.LOCK_FILE).read_text().replace(commit, commit[:12]))
        lock.verify(other, note=True)
        machine("a")
        lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)  # reads every note
        note = {"lockfile": "/x/chartbook.lock", "hashes": [], "snapshots": [{"commit": "ABC", "made_at": "x"}]}
        from chartbook.store import read_root

        assert read_root(note).snapshots == ()


class TestOneMachineWhoseHostNameMoves:
    def test_its_notes_stay_its_own(self, drive, monkeypatch):
        """A laptop whose host name follows the network: the same machine, by its hardware address."""
        work, machine, rates = drive
        s1 = snapshot.make(rates, made_at="2020-01-01T00:00:00.000000Z").snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        scratch = _forecast(work / "a" / "scratch", {"acme/rates": {}})
        assert lock.pin(project).problems == [] and lock.pin(scratch).problems == []
        _snapshot_again(rates, 4.2, made_at="2020-02-01T00:00:00.000000Z")
        monkeypatch.setattr(socket, "gethostname", lambda: "dhcp-10-1-2-3.corp.example.com")  # at the office
        assert lock.update(project).problems == []
        shutil.rmtree(scratch)  # the scratch project is deleted
        store = default_store()
        assert len(store.roots()) == 2
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0, forget_missing=True)
        assert plan.elsewhere == [] and plan.forget == [scratch / lock.LOCK_FILE]
        assert s1.made_at in [t.made_at for t, _ in plan.snapshots_delete]


class TestNoPasswordInWhatIsPrinted:
    @pytest.mark.parametrize("url, secret", [
        ("//u:pw0rd@host/share", "pw0rd"),
        ("file://u:pw0rd@host/srv/store", "pw0rd"),
        ("s3://AKIAEXAMPLE:se?cr3t@bucket/p", "cr3t"),
        ("s3://bucket/p?endpoint=https://u:pa&ss0@minio.example.org", "ss0"),
        ("s3://bucket/p?endpoint=https://u:pa#ss0@minio.example.org", "ss0"),
        ("s3://bucket/p?endpoint=https%3A%2F%2Fu%3Apw0rd%40minio.example.org", "pw0rd"),
    ])
    def test_by_store_info_and_gc(self, monkeypatch, url, secret):
        monkeypatch.setenv("CHARTBOOK_STORE", url)
        for args in (["store", "info"], ["store", "gc", "--dry-run"], ["store", "verify"]):
            result = CliRunner().invoke(main, args)
            assert secret not in result.output, (args, result.output)

    def test_a_hash_sign_is_refused_by_the_s3_store(self):
        pytest.importorskip("boto3")
        from chartbook.stores.s3 import _parse_url

        with pytest.raises(ValueError, match="has a '#' in it"):
            _parse_url("s3://bucket/p?endpoint=https://minio.example.org#x")


class TestOneMachineWhoseHardwareAddressMoves:
    """Linux picks the first interface with an address (wired, then Wi-Fi); WSL2's changes on a restart; a dock's."""

    def test_its_notes_stay_its_own_and_gc_reads_its_lockfile(self, drive, monkeypatch):
        from chartbook.config import get_machine_id

        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        at_old = (project / lock.LOCK_FILE).read_bytes()
        _snapshot_again(rates, 4.2)
        _forecast(project, {"acme/rates": {}})
        assert lock.update(project).problems == []
        name = get_machine_id()
        monkeypatch.setattr(uuid, "getnode", lambda: 0x0C00000000FF)  # the next process sees another interface
        _forecast(project, {"acme/rates": {"commit": old.commit[:7]}})
        (project / lock.LOCK_FILE).write_bytes(at_old)  # git checkout of the older commit, no pin
        monkeypatch.chdir(project)
        data.load("acme/rates:treasury").collect()  # a read on it
        assert get_machine_id() == name  # the machine is never renamed
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert plan.elsewhere == [] and plan.lockfiles == [(project / lock.LOCK_FILE, True)]
        assert old.made_at not in [t.made_at for t, _ in plan.snapshots_delete]
        (note,) = default_store().roots()
        assert note.host == "machine-a.local" and note.node == "0c00000000ff"  # for a person to read


class TestRunnersThatShareAName:
    def test_replace_their_note(self, drive, monkeypatch):
        """Each run a fresh runner, with a hardware address of its own, builds a newer commit of the project."""
        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        checkout = work / "runner" / "forecast"
        for run in range(3):
            machine("a")
            monkeypatch.delenv("CI", raising=False)
            monkeypatch.delenv("CHARTBOOK_MACHINE_ID", raising=False)
            taken = _snapshot_again(rates, 5.0 + run)
            assert lock.update(project).problems == []  # the developer moves to it
            machine(f"ci{run}")  # a fresh runner
            monkeypatch.setenv("CI", "true")
            monkeypatch.setenv("CHARTBOOK_MACHINE_ID", "ci-runners")
            shutil.rmtree(checkout, ignore_errors=True)
            shutil.copytree(project, checkout)
            assert lock.verify(checkout, note=True).problems == []
        notes = [r for r in default_store().roots() if r.lockfile == checkout / lock.LOCK_FILE]
        assert len(notes) == 1 and notes[0].machine == "ci-runners"
        assert [made_at for _, made_at in notes[0].snapshots] == [taken.made_at]  # the last run's

    def test_a_note_not_written_is_said_for_what_it_is(self, drive):
        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        roots = default_store().root / "roots"
        roots.mkdir(parents=True, exist_ok=True)
        roots.chmod(0o555)
        try:
            result = CliRunner().invoke(main, ["pin", "--project-dir", str(project)])
        finally:
            roots.chmod(0o755)
        assert "The store's note of this lockfile, for `store gc`, could not be written" in result.output
        assert "read-only for you, so its note" not in result.output


class TestAnOldNoteInThisUsersOwnStore:
    """After the upgrade: notes from before notes named their machine, in the store under ~/.chartbook."""

    @pytest.fixture
    def own(self, drive, monkeypatch):
        work, machine, rates = drive
        monkeypatch.delenv("CHARTBOOK_STORE")  # the default store, under ~/.chartbook
        assert str(default_store().root).startswith(str(config.get_global_config_dir()))
        return work, machine, rates

    def _old_note(self, project: Path) -> Path:
        from chartbook.store import root_name

        store = default_store()
        (note,) = (store.root / "roots").glob("*.json")
        stored = json.loads(note.read_text())
        note.unlink()
        older = store.root / "roots" / root_name(project / lock.LOCK_FILE)
        older.write_text(json.dumps({"lockfile": stored["lockfile"], "hashes": stored["hashes"]}))
        return older

    def test_is_this_machines_and_forgotten_when_its_lockfile_is_gone(self, own):
        work, machine, rates = own
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        _snapshot_again(rates, 4.2)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        older = self._old_note(project)
        assert lock.plan_gc(default_store()).lockfiles == [(project / lock.LOCK_FILE, True)]
        shutil.rmtree(project)  # the project is deleted
        plan = lock.plan_gc(default_store(), forget_missing=True, recent_seconds=0, keep_days=0)
        assert plan.elsewhere == [] and plan.forget_old == [project / lock.LOCK_FILE]
        assert old.made_at in [t.made_at for t, _ in plan.snapshots_delete]
        lock.run_gc(plan, default_store())
        assert not older.exists()

    def test_elsewhere_it_is_kept_with_care(self, drive):
        """In a store a team shares, it may be any machine's."""
        work, machine, rates = drive
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        _snapshot_again(rates, 4.2)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        self._old_note(project)
        shutil.rmtree(project)
        plan = lock.plan_gc(default_store(), forget_missing=True, recent_seconds=0, keep_days=0)
        assert [r.machine for r in plan.elsewhere] == [""] and plan.forget_old == []
        assert old.made_at not in [t.made_at for t, _ in plan.snapshots_delete]


class TestAStoreAtAPathWithAPassword:
    def test_no_command_prints_it(self, drive, monkeypatch):
        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        _git(rates, "commit", "--allow-empty", "--quiet", "-m", "Again")
        monkeypatch.setenv("CHARTBOOK_STORE", "//alice:s3cr3tpw@fileserver/share/store")
        for args in (
            ["pin", "--project-dir", str(project)],
            ["pin", "--frozen", "--project-dir", str(project)],
            ["update", "--project-dir", str(project)],
            ["snapshot", "--project-dir", str(rates)],
            ["store", "info"],
            ["store", "gc", "--dry-run"],
        ):
            result = CliRunner().invoke(main, args)
            assert "s3cr3tpw" not in result.output, (args, result.output)

    def test_an_endpoint_password_that_holds_an_option(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_STORE", "s3://b/p?endpoint=https://u:S3CRET?pw&x=1@minio.example.org")
        for args in (["store", "info"], ["store", "gc", "--dry-run"]):
            result = CliRunner().invoke(main, args)
            assert "S3CRET" not in result.output and "pw&x" not in result.output, (args, result.output)


class TestAReadOnOneMachine:
    def test_an_object_found_whole_is_not_looked_at_again(self, drive, monkeypatch):
        from chartbook import store as store_module

        work, machine, rates = drive
        snapshot.make(rates)
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        monkeypatch.chdir(project)
        data.load("acme/rates:treasury").collect()

        def looked(*args, **kwargs):
            raise AssertionError("an object found whole was looked at again")

        from chartbook import resolve

        whole_check = store_module.unsynced_part
        monkeypatch.setattr(store_module, "unsynced_part", looked)
        for _ in range(3):
            assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        # Nor is the hardware address asked by the next process's read, whose
        # note says what the lockfile pins already. Counted, not raised: a note
        # is best effort, and what writing one raises is passed over
        monkeypatch.setattr(store_module, "unsynced_part", whole_check)
        resolve._noted_reads.clear()
        _forget_whole()
        asked = []
        monkeypatch.setattr(uuid, "getnode", lambda: asked.append(1) or 0x0C0000000001)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        assert asked == []


class TestAnOldNoteGivesWay:
    """In this user's own store, a note from before notes named their machine is this machine's, and gives way to its note."""

    @pytest.fixture
    def own(self, drive, monkeypatch):
        work, machine, rates = drive
        monkeypatch.delenv("CHARTBOOK_STORE")  # the default store, under ~/.chartbook
        return work, machine, rates

    @staticmethod
    def _old_note(lockfile: Path, hashes) -> Path:
        from chartbook.store import root_name

        older = default_store().root / "roots" / root_name(lockfile)
        older.write_text(json.dumps({"lockfile": str(lockfile), "hashes": sorted(hashes)}))
        return older

    def test_a_pin_writes_this_machines_note_in_its_place(self, own):
        from chartbook.config import get_machine_id

        work, machine, rates = own
        taken = snapshot.make(rates).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        default_store().remove_root(project / lock.LOCK_FILE)
        older = self._old_note(project / lock.LOCK_FILE, taken.asset_hashes())  # as an older ChartBook left it
        assert lock.pin(project).problems == []
        assert not older.exists()
        assert [root.machine for root in default_store().roots()] == [get_machine_id()]

    def test_while_its_lockfile_is_there_it_keeps_only_what_the_lockfile_pins(self, own):
        work, machine, rates = own
        old = snapshot.make(rates, made_at=LONG_AGO).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(project).problems == []
        _snapshot_again(rates, 4.2)
        _forecast(project, {"acme/rates": {}})
        assert lock.update(project).problems == []
        default_store().remove_root(project / lock.LOCK_FILE)
        self._old_note(project / lock.LOCK_FILE, old.asset_hashes())  # written at the older pin, before notes named machines
        plan = lock.plan_gc(default_store(), recent_seconds=0, keep_days=0)
        assert plan.lockfiles == [(project / lock.LOCK_FILE, True)] and plan.elsewhere == []
        assert old.made_at in [t.made_at for t, _ in plan.snapshots_delete]

    def test_gc_lists_the_lockfile_once_and_names_the_old_notes_file(self, own):
        from chartbook.store import root_name

        work, machine, rates = own
        taken = snapshot.make(rates).snapshot
        project = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        older = self._old_note(project / lock.LOCK_FILE, taken.asset_hashes())  # beside this machine's note
        result = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert result.output.count(str(project / lock.LOCK_FILE)) == 1, result.output
        assert f"roots/{root_name(project / lock.LOCK_FILE)}" in result.output
        lock.run_gc(lock.plan_gc(default_store()), default_store())
        assert not older.exists() and len(default_store().roots()) == 1


class TestARunnerWithNoName:
    def test_a_pin_or_an_update_leaves_no_note(self, drive, monkeypatch):
        """Under CI, with no CHARTBOOK_MACHINE_ID: a runner with a fresh home would leave a note under a new name each run."""
        work, machine, rates = drive
        snapshot.make(rates)
        machine("ci")
        monkeypatch.setenv("CI", "true")
        project = _forecast(work / "runner" / "forecast", {"acme/rates": {}})
        assert lock.pin(project).problems == []
        _snapshot_again(rates, 4.2)
        assert lock.update(project).problems == []
        assert default_store().roots() == []


class TestADirectoryWithFilesThatAreNotTables:
    @pytest.mark.parametrize("side", ["README.txt", "schema.json"])
    def test_only_its_parquet_files_are_read(self, drive, monkeypatch, side):
        """As DuckDB reads a folder, and as every engine read the folder before records listed its files."""
        import polars as pl

        work, machine, rates = drive

        def writer(parts):
            pl.DataFrame({"a": [1, 2]}).write_parquet(parts / "part-0.parquet")
            (parts / side).write_text("About these parts.\n")

        _parts(rates, writer)
        taken = snapshot.make(rates).snapshot
        assert side in [entry["path"] for entry in taken.assets["parts"]["files"]]
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:parts").collect().height == 2
        assert len(data.load("acme/rates:parts", format="pandas")) == 2
        assert data.sql("select count(*) as n from {acme/rates:parts}").collect()["n"][0] == 2

    def test_parquet_files_with_no_ending_are_read(self, drive, monkeypatch):
        import polars as pl

        work, machine, rates = drive

        def writer(parts):
            pl.DataFrame({"a": [1]}).write_parquet(parts / "part-0")
            pl.DataFrame({"a": [2]}).write_parquet(parts / "part-1")

        _parts(rates, writer)
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"acme/rates": {}})
        assert lock.pin(forecast).problems == []
        monkeypatch.chdir(forecast)
        assert sorted(data.load("acme/rates:parts").collect()["a"].to_list()) == [1, 2]


class TestWhatIsNotASyncServicesCopy:
    def test_a_name_in_unicodes_other_form(self, tmp_path):
        """A sync between macOS and Linux may write a listed name decomposed: the same file, never one to remove."""
        import unicodedata

        held = tmp_path / "object"
        (held / unicodedata.normalize("NFD", "city=Zürich")).mkdir(parents=True)
        (held / unicodedata.normalize("NFD", "city=Zürich") / "part-0.parquet").write_bytes(b"x" * 10)
        files = {unicodedata.normalize("NFC", "city=Zürich") + "/part-0.parquet": 10}
        assert unsynced_part(held, 10, files, every=True) is None

    def test_a_dot_file_a_sync_service_writes(self, tmp_path):
        """Syncthing's temporary file, beside a file on its way: no reader reads a name starting '.'."""
        held = tmp_path / "object"
        held.mkdir()
        (held / "part-0.parquet").write_bytes(b"x" * 10)
        (held / ".syncthing.part-1.parquet.tmp").write_bytes(b"y" * 5)
        assert unsynced_part(held, 10, {"part-0.parquet": 10}, every=True) is None


class TestTheAgeOfAnObject:
    def test_one_that_came_just_now_with_an_old_time_is_recent(self, drive, tmp_path):
        """A sync service may give an object the time it had where it was made; its record may not have come yet."""
        import time

        store = default_store()
        made = tmp_path / "made.parquet"
        made.write_bytes(b"x" * 10)
        stored = store.put(made)
        long_ago = time.time() - 30 * 86400
        os.utime(store.object_path(stored.content_hash), (long_ago, long_ago))
        plan = lock.plan_gc(store)
        assert stored.content_hash in plan.recent and plan.delete == []


class TestNoPasswordOfAStoreAtAPath:
    def test_in_store_infos_cache_line(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_CACHE", "//alice:s3cr3tpw@fileserver/share/cache")
        result = CliRunner().invoke(main, ["store", "info"])
        assert result.exit_code == 0 and "s3cr3tpw" not in result.output and "fileserver/share/cache" in result.output

    def test_in_what_windows_makes_of_the_path(self):
        assert "s3cr3tpw" not in config.shown_store_url("\\\\alice:s3cr3tpw@fileserver\\share\\store")
        said = "[WinError 53] The network path was not found: '\\\\\\\\alice:s3cr3tpw@fileserver\\\\share\\\\store'"
        assert "s3cr3tpw" not in config.without_credentials(said) and "fileserver" in config.without_credentials(said)
        drive = "[Errno 2] No such file or directory: 'C:\\\\Users\\\\me@example.org\\\\store'"
        assert config.without_credentials(drive) == drive  # a drive's path is no address

    def test_in_what_check_says_of_a_store_it_cannot_read(self, drive, monkeypatch):
        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        work, machine, rates = drive
        snapshot.make(rates)
        forecast = _forecast(work / "a" / "forecast", {"rates": {"path": "../rates"}})
        assert lock.pin(forecast).problems == []
        machine("b")
        clone = work / "b" / "forecast"
        shutil.copytree(forecast, clone)
        monkeypatch.setenv("CHARTBOOK_STORE", "//alice:s3cr3tpw@fileserver/share/store")

        def unreadable(self, content_hash):
            raise PermissionError(13, "Permission denied", str(self.root / "objects"))

        monkeypatch.setattr(FolderStore, "has", unreadable)
        with warnings.catch_warnings(record=True) as said:
            warnings.simplefilter("always")
            problems = check_dependencies(load_manifest(clone), clone)
        told = [problem.message for problem in problems] + [str(warning.message) for warning in said]
        assert any("the store cannot be read" in text for text in told), told
        assert not any("s3cr3tpw" in text for text in told), told
