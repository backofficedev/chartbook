"""Notes of every branch and tag; a one-pipeline gc reminder; forgetting one note.

Step 6 of docs_src/design/snapshots-and-increments.md: the store's note of a
lockfile names what every local branch and tag pins; ``chartbook snapshot``
says what gc could remove of this pipeline; ``store gc`` says which note
holds a pin and can forget one.
"""

import json
import shutil
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lock, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore, root_name
from tests.test_dependencies_by_id import _commit, _forecast, _rates
from tests.test_model_versions import _git

LONG_AGO = "2020-01-01T00:00:00.000000Z"
ALSO_AGO = "2020-02-01T00:00:00.000000Z"


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "store"
    monkeypatch.setenv("CHARTBOOK_STORE", str(root))
    return FolderStore(root)


def _pin_lockfile(folder: Path, dependency: str, taken: snapshot.Snapshot) -> None:
    """Write a lockfile that pins *taken* of *dependency*, as ``chartbook pin`` would."""
    locked = lock.Lock(root=folder.name)
    locked.dependencies = [{
        "id": dependency,
        "via": "store",
        "location": {
            "kind": "store",
            "pipeline": dependency,
            "commit": taken.commit,
            "first_commit": taken.first_commit or taken.commit,
        },
        "snapshot": taken.made_at,
    }]
    asset = taken.assets.get("treasury") or next(iter(taken.assets.values()))
    locked.assets = {
        f"{dependency}:treasury": {
            "id": f"{dependency}:treasury",
            "kind": "Dataframe",
            "pipeline": dependency,
            "content_hash": asset["content_hash"],
            "path": asset.get("path", "./_data/treasury.parquet"),
        }
    }
    lock.write_lock(locked, folder / lock.LOCK_FILE)


class TestNotesOfEveryBranchAndTag:
    def test_two_branches_keep_both_pins(self, store, tmp_path):
        """Different pins on two branches: the note keeps both; gc keeps both snapshots."""
        work = tmp_path.resolve()
        rates = work / "rates"
        _rates(rates, 4.1)
        _git(rates, "init", "--quiet", "-b", "main")
        (rates / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _commit(rates)
        first = snapshot.make(rates, store=store, made_at=LONG_AGO).snapshot
        _rates(rates, 4.2)
        (rates / "notes.txt").write_text("second\n", encoding="utf-8", newline="\n")
        _commit(rates, "Second")
        second = snapshot.make(rates, store=store, made_at=ALSO_AGO, complete=True).snapshot

        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        _git(forecast, "init", "--quiet", "-b", "main")
        (forecast / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _pin_lockfile(forecast, "acme/rates", first)
        _commit(forecast, "Pin first")
        _git(forecast, "checkout", "-b", "other")
        _pin_lockfile(forecast, "acme/rates", second)
        _commit(forecast, "Pin second")
        _git(forecast, "checkout", "main")

        assert lock.note_this_machine(forecast / lock.LOCK_FILE, lock.read_lock(forecast), store)[0]
        (note,) = store.roots()
        moments = {(commit, made_at) for _, commit, made_at in note.snapshots}
        assert moments == {(first.commit, first.made_at), (second.commit, second.made_at)}
        assert all(pipeline == "acme/rates" for pipeline, _, _ in note.snapshots)

        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        kept = {(taken.commit, taken.made_at) for taken, _ in plan.snapshots_kept}
        assert (first.commit, first.made_at) in kept and (second.commit, second.made_at) in kept
        assert plan.noted_by[(first.commit, first.made_at)] == note.note

    def test_partial_git_failure_merges_and_does_not_drop_pins(self, store, tmp_path, monkeypatch):
        """When a tip fails, the note merges: prior pins stay."""
        work = tmp_path.resolve()
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        rates = work / "rates"
        _rates(rates, 4.1)
        _git(rates, "init", "--quiet", "-b", "main")
        (rates / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _commit(rates)
        first = snapshot.make(rates, store=store, made_at=LONG_AGO).snapshot
        _rates(rates, 4.2)
        (rates / "notes.txt").write_text("second\n", encoding="utf-8", newline="\n")
        _commit(rates, "Second")
        second = snapshot.make(rates, store=store, made_at=ALSO_AGO, complete=True).snapshot

        _git(forecast, "init", "--quiet", "-b", "main")
        (forecast / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _pin_lockfile(forecast, "acme/rates", first)
        _commit(forecast)
        store.add_root(
            forecast / lock.LOCK_FILE,
            lock.read_lock(forecast).hashes(),
            {("acme/rates", first.commit, first.made_at), ("acme/rates", second.commit, second.made_at)},
        )
        before = set(store.roots()[0].snapshots)

        monkeypatch.setattr(lock, "_lockfile_at_tip", lambda *a, **k: (None, "failed"))
        _pin_lockfile(forecast, "acme/rates", first)  # checkout still pins first only
        pins = lock.pins_for_note(forecast / lock.LOCK_FILE, lock.read_lock(forecast))
        assert pins.complete is False
        # A partial answer merges: nothing is dropped
        lock.note_this_machine(forecast / lock.LOCK_FILE, lock.read_lock(forecast), store)
        after = set(store.roots()[0].snapshots)
        assert before <= after

    def test_tag_only_tip(self, store, tmp_path):
        """A tag that is not the current branch still puts its pin in the note."""
        work = tmp_path.resolve()
        rates = work / "rates"
        _rates(rates, 4.1)
        _git(rates, "init", "--quiet", "-b", "main")
        (rates / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _commit(rates)
        first = snapshot.make(rates, store=store, made_at=LONG_AGO).snapshot
        _rates(rates, 4.2)
        (rates / "notes.txt").write_text("second\n", encoding="utf-8", newline="\n")
        _commit(rates, "Second")
        second = snapshot.make(rates, store=store, made_at=ALSO_AGO, complete=True).snapshot

        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        _git(forecast, "init", "--quiet", "-b", "main")
        (forecast / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _pin_lockfile(forecast, "acme/rates", first)
        _commit(forecast, "Pin first")
        _git(forecast, "tag", "v1")
        _pin_lockfile(forecast, "acme/rates", second)
        _commit(forecast, "Pin second on main")

        assert lock.note_this_machine(forecast / lock.LOCK_FILE, lock.read_lock(forecast), store)[0]
        moments = {(commit, made_at) for _, commit, made_at in store.roots()[0].snapshots}
        assert moments == {(first.commit, first.made_at), (second.commit, second.made_at)}

    def test_old_notes_without_pipeline_still_read(self, store, tmp_path):
        """A note written before notes recorded the pipeline is still read."""
        work = tmp_path.resolve()
        rates = work / "rates"
        _rates(rates, 4.1)
        _git(rates, "init", "--quiet", "-b", "main")
        (rates / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _commit(rates)
        taken = snapshot.make(rates, store=store, made_at=LONG_AGO).snapshot
        lockfile = work / "forecast" / lock.LOCK_FILE
        lockfile.parent.mkdir(parents=True)
        document = {
            "lockfile": str(lockfile.resolve()),
            "machine": "",
            "host": "old",
            "node": "",
            "hashes": sorted(taken.hashes()),
            "snapshots": [{"commit": taken.commit, "made_at": taken.made_at}],
        }
        note = store.roots_path() / root_name(lockfile)
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
        (root,) = store.roots()
        assert root.snapshots == (("", taken.commit, taken.made_at),)
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert taken.made_at not in [t.made_at for t, _ in plan.snapshots_delete]


class TestOnePipelineReminder:
    def test_reminder_of_pipeline_a_does_not_list_b(self, store, tmp_path):
        """After a snapshot of A, the reminder does not list B's clearable snapshots."""
        from chartbook.cli import _what_gc_would_clear

        work = tmp_path.resolve()
        for name, pipeline, when in (
            ("rates", "acme/rates", LONG_AGO),
            ("news", "acme/news", LONG_AGO),
        ):
            folder = work / name
            _rates(folder, 1.0)
            (folder / "chartbook.toml").write_text(
                tomli_w.dumps({"project": {"id": pipeline}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "x"}}}),
                encoding="utf-8", newline="\n",
            )
            _git(folder, "init", "--quiet", "-b", "main")
            (folder / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
            _commit(folder)
            snapshot.make(folder, store=store, made_at=when)
            pl.DataFrame({"d": ["2024-01-02"], "r": [2.0]}).write_parquet(folder / "_data" / "treasury.parquet")
            (folder / "bump.txt").write_text("n\n", encoding="utf-8", newline="\n")
            _commit(folder, "Bump")
            snapshot.make(folder, store=store, complete=True)

        whole = _what_gc_would_clear(store)
        assert whole and "2 snapshot(s)" in whole
        only_rates = _what_gc_would_clear(store, pipeline="acme/rates")
        assert only_rates and "1 snapshot(s) of acme/rates" in only_rates
        assert "acme/news" not in only_rates
        only_news = _what_gc_would_clear(store, pipeline="acme/news")
        assert only_news and "1 snapshot(s) of acme/news" in only_news


class TestForgetOneNote:
    def test_forget_note_then_dry_run_no_longer_keeps_its_pins(self, store, tmp_path):
        """After --forget-note, a dry-run no longer keeps that note's pins."""
        work = tmp_path.resolve()
        rates = work / "rates"
        _rates(rates, 4.1)
        _git(rates, "init", "--quiet", "-b", "main")
        (rates / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        _commit(rates)
        old = snapshot.make(rates, store=store, made_at=LONG_AGO).snapshot
        _rates(rates, 4.2)
        (rates / "notes.txt").write_text("n\n", encoding="utf-8", newline="\n")
        _commit(rates, "Second")
        snapshot.make(rates, store=store, made_at=ALSO_AGO, complete=True)

        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": old.commit[:7]}})
        assert lock.pin(forecast, store).problems == []
        (note,) = store.roots()
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert old.made_at not in [t.made_at for t, _ in plan.snapshots_delete]

        # Remove the live lockfile so only the note keeps the old pin
        shutil.rmtree(forecast)
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert old.made_at not in [t.made_at for t, _ in plan.snapshots_delete]

        result = CliRunner().invoke(main, ["store", "gc", "--forget-note", note.note, "--dry-run", "--keep-days", "0"])
        assert result.exit_code == 0, result.output
        assert "Would forget note" in result.output and note.note in result.output
        assert "Forgot note" not in result.output
        assert "Would remove" in result.output
        # A dry run leaves the note, so a fresh plan still keeps the pin
        assert store.roots()
        plan = lock.plan_gc(store, recent_seconds=0, keep_days=0)
        assert old.made_at not in [t.made_at for t, _ in plan.snapshots_delete]

        declined = CliRunner().invoke(
            main, ["store", "gc", "--forget-note", note.note, "--keep-days", "0"], input="n\n",
        )
        assert declined.exit_code == 0, declined.output
        assert "Nothing was removed." in declined.output
        assert store.roots()

        gone = CliRunner().invoke(main, ["store", "gc", "--forget-note", note.note, "--yes", "--keep-days", "0"])
        assert gone.exit_code == 0, gone.output
        assert "Forgot note" in gone.output
        assert store.roots() == []
        assert not any(record.made_at == old.made_at for record in store.records())

    def test_refuses_another_machines_note(self, store, tmp_path):
        """Another machine's note is refused; remove its file by hand."""
        lockfile = tmp_path / "other" / lock.LOCK_FILE
        lockfile.parent.mkdir(parents=True)
        store.add_root(lockfile, [], [("acme/rates", "a" * 40, LONG_AGO)], machine="other-machine")
        (note,) = [root for root in store.roots() if root.machine == "other-machine"]
        result = CliRunner().invoke(main, ["store", "gc", "--forget-note", note.note, "--dry-run"])
        assert result.exit_code == 1
        assert "another machine's note" in result.output and "by hand" in result.output
