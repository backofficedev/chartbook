"""Tests for what a lockfile holds, by kind (``docs_src/design/pins-and-rebuilds.md``, step 2).

A lockfile is about what code reads: a dataframe and a model are always in
it. A chart, a notebook, a note or a plain file is drawn anew by every
build, so it is in it only when its owner's manifest says ``lock = true``.
What is not in it is still read: from the snapshot the lockfile names,
when a store has that snapshot, and otherwise from your own snapshot of
that pipeline at that commit.

The story these serve: a class with no shared store. Each student builds
every upstream at the commit the report's lockfile names, and no rebuild
gives a chart's or a notebook's bytes again.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, config, lineage, lock, snapshot
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.manifest import load_manifest
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline, pin_from_snapshots, snapshot_dependencies, update_from_snapshots


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _git(directory: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *arguments],
        cwd=directory, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace",
    )
    return done.stdout.strip()


UPSTREAM = {
    "project": {"id": "acme/rates"},
    "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
    "notebooks": {"analysis": {"path": "./_output/analysis.html", "name": "Analysis", "docs": "d"}},
    "notes": {"method": {"path": "./docs_src/method.md"}},
    "models": {"ar1": {"path": "./_models/ar1.joblib"}},
    "files": {
        "raw": {"path": "./_data/raw.txt", "docs": "d"},
        "parameters": {"path": "./_data/parameters.xlsx", "docs": "d", "lock": True},
    },
}

BUILT = {
    "_data/treasury.parquet": b"rows",
    "_output/curve.html": b"<html>curve</html>",
    "_output/analysis.html": b"<html>analysis</html>",
    "docs_src/method.md": b"# Method\n",
    "_models/ar1.joblib": b"weights",
    "_data/raw.txt": b"raw",
    "_data/parameters.xlsx": b"parameters",
}

#: What a lockfile holds of that pipeline, and what it does not
IN = {"acme/rates:treasury", "acme/rates:model/ar1", "acme/rates:file/parameters"}
OUT = {"chart/curve", "notebook/analysis", "note/method", "file/raw"}


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    """This test's store. A read uses the user's, so that is pointed here."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return FolderStore(work / "store")


@pytest.fixture
def rates(work):
    """An upstream with an asset of every kind, all built, and one plain file marked ``lock = true``."""
    directory = work / "rates"
    _write_manifest(directory, UPSTREAM)
    for relative, content in BUILT.items():
        _write(directory / relative, content)
    return directory


@pytest.fixture
def report(work, rates):
    """A pipeline that depends on it, by its folder."""
    directory = work / "report"
    _write_manifest(directory, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    return directory


@pytest.fixture
def pinned(report, store):
    pin_from_snapshots(report, store)
    return report


def _document(folder: Path) -> dict:
    return json.loads((folder / lock.LOCK_FILE).read_text(encoding="utf-8"))


def _as_version_1(folder: Path, store) -> dict:
    """Write a pinned pipeline's lockfile as ChartBook 0.5 wrote it: a record for every asset of the snapshot, and the hash over all of them."""
    document = _document(folder)
    (entry,) = document["records"][0]["dependencies"]
    (taken,) = [t for t in snapshot.all_snapshots(store) if t.same_moment(entry["location"]["commit"], entry["snapshot"])]
    records = [
        {k: v for k, v in snapshot.renamed(taken.assets[name], entry["id"]).items() if k not in ("trained_on", "keep", "lock")}
        for name in sorted(taken.assets)
    ]
    entry["pinned_hash"] = lock.pinned_hash(records)
    document["schema"] = "chartbook/lock/v1"
    document["records"] = [document["records"][0], *sorted(records, key=lambda record: record["id"])]
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    (folder / lock.LOCK_FILE).write_text(text, encoding="utf-8", newline="\n")
    return document


class TestTheKey:
    """``lock = true`` on an asset in its owner's manifest: the one key, and the one value it takes."""

    @pytest.mark.parametrize("value", [False, "yes", 1])
    def test_only_true_is_taken(self, rates, value):
        table = json.loads(json.dumps(UPSTREAM))
        table["files"]["raw"]["lock"] = value
        _write_manifest(rates, table)
        with pytest.raises(ValueError, match=r"\[files\.raw\]: lock = .* lock is true, or left out"):
            load_manifest(base_dir=rates)

    def test_it_goes_on_any_kind(self, rates):
        table = json.loads(json.dumps(UPSTREAM))
        for kind in ("dataframes", "charts", "notebooks", "notes", "models", "files"):
            for entry in table[kind].values():
                entry["lock"] = True
        _write_manifest(rates, table)
        load_manifest(base_dir=rates)

    def test_a_snapshot_records_it(self, rates, store):
        commit_pipeline(rates)
        taken = snapshot.make(rates, store=store).snapshot
        assert taken.assets["file/parameters"]["lock"] is True
        assert all("lock" not in record for name, record in taken.assets.items() if name != "file/parameters")
        document = json.loads(taken.path.read_text(encoding="utf-8"))
        jsonschema.validate(document, json.loads(snapshot.schema_path().read_text(encoding="utf-8")))

    def test_what_is_in_a_lockfile(self):
        def record(kind, **more):
            return {"ref": {"kind": kind, "name": "x"}, **more}

        assert lock.in_lockfile(record("dataframe")) and lock.in_lockfile(record("model"))
        for kind in ("chart", "notebook", "note", "file"):
            assert not lock.in_lockfile(record(kind))
            assert lock.in_lockfile(record(kind, lock=True))
            assert not lock.in_lockfile(record(kind, lock="true"))  # only true itself
        assert not lock.in_lockfile({})


class TestWhatAPinHolds:

    def test_dataframes_and_models_and_what_its_owner_locks(self, pinned):
        document = _document(pinned)
        assert document["schema"] == "chartbook/lock/v2" == lock.SCHEMA
        assert {record["id"] for record in document["records"][1:]} == IN
        by_id = {record["id"]: record for record in document["records"][1:]}
        assert by_id["acme/rates:file/parameters"]["lock"] is True
        assert "lock" not in by_id["acme/rates:treasury"]
        jsonschema.validate(document, json.loads(lock.schema_path().read_text(encoding="utf-8")))

    def test_the_one_hash_is_over_what_it_holds(self, pinned):
        locked = lock.read_lock(pinned)
        (entry,) = locked.dependencies
        assert entry["pinned_hash"] == lock.pinned_hash(locked.assets.values())

    def test_a_model_that_is_not_built_is_still_recorded(self, rates, report, store):
        (rates / "_models" / "ar1.joblib").unlink()
        pin_from_snapshots(report, store)
        record = lock.read_lock(report).assets["acme/rates:model/ar1"]
        assert "content_hash" not in record

    def test_the_report_says_what_is_not_pinned(self, rates, report, store):
        found = pin_from_snapshots(report, store)
        unlocked = {event.asset.split(":", 1)[1]: event.detail for event in found.events if event.status == "unlocked"}
        assert unlocked == {"chart/curve": "chart", "notebook/analysis": "notebook", "note/method": "note", "file/raw": "file"}
        assert found.count("pinned") == 3 and not found.problems

    def test_pin_prints_it_in_one_line(self, rates, report, store):
        snapshot_dependencies(report, store)
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        assert (
            "acme/rates: 3 pinned. Its 1 chart, 1 notebook, 1 note and 1 file are not pinned: "
            "they are read from its snapshot" in result.output
        )

    def test_charts_and_notebooks_are_said_for_what_they_are(self, rates, report, store):
        table = json.loads(json.dumps(UPSTREAM))
        del table["notes"], table["files"]["raw"]
        _write_manifest(rates, table)
        snapshot_dependencies(report, store)
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert "acme/rates: 3 pinned. Its 1 chart and 1 notebook are not pinned: each build draws them anew" in result.output

    def test_one_that_is_not_built_is_said_so(self, rates, report, store):
        """As any asset is: that it is not in the lockfile does not make it built."""
        (rates / "_output" / "curve.html").unlink()
        found = pin_from_snapshots(report, store)
        statuses = {event.asset.split(":", 1)[1]: event.status for event in found.events if event.asset}
        assert statuses["chart/curve"] == "not_built" and statuses["notebook/analysis"] == "unlocked"
        result = CliRunner().invoke(main, ["update", "--project-dir", str(report)])
        assert "  not built: acme/rates:chart/curve (./_output/curve.html)" in result.output

    def test_update_says_what_its_owner_no_longer_declares(self, rates, pinned, store):
        table = json.loads(json.dumps(UPSTREAM))
        del table["notebooks"]
        _write_manifest(rates, table)
        found = update_from_snapshots(pinned, store=store)
        dropped = [event.asset for event in found.events if event.status == "dropped"]
        assert dropped == ["acme/rates:notebook/analysis"]

    def test_a_snapshot_is_taken_whole_or_not_at_all(self, rates, report, store):
        """The store has lost a chart's bytes: nothing of that snapshot is pinned, in the lockfile or out of it."""
        (taken,) = [made.snapshot for made in snapshot_dependencies(report, store)]
        held = store.files(taken.assets["chart/curve"]["content_hash"]).one.location
        held.chmod(0o644)
        held.unlink()
        found = lock.pin(report, store)
        locked = lock.read_lock(report)
        assert [event.status for event in found.problems] == ["lost"]
        assert locked.assets == {} and not lock.names_a_snapshot(locked.dependencies[0])

    def test_one_that_stops_being_locked_leaves_the_lockfile_on_update(self, rates, pinned, store):
        table = json.loads(json.dumps(UPSTREAM))
        del table["files"]["parameters"]["lock"]
        _write_manifest(rates, table)
        found = update_from_snapshots(pinned, store=store)
        assert "acme/rates:file/parameters" not in lock.read_lock(pinned).assets
        statuses = {event.asset: event.status for event in found.events if event.asset}
        assert statuses["acme/rates:file/parameters"] == "unlocked"

    def test_a_pin_does_not_move_for_it(self, rates, pinned, store):
        """`pin` never moves a pin: the owner's new mark is taken by `update`."""
        table = json.loads(json.dumps(UPSTREAM))
        table["charts"]["curve"]["lock"] = True
        _write_manifest(rates, table)
        before = (pinned / lock.LOCK_FILE).read_bytes()
        pin_from_snapshots(pinned, store)
        assert (pinned / lock.LOCK_FILE).read_bytes() == before
        update_from_snapshots(pinned, store=store)
        assert lock.read_lock(pinned).assets["acme/rates:chart/curve"]["lock"] is True


class TestReadingWhatIsNotInIt:
    """Through the snapshot the lockfile names; else your own build at that commit."""

    def test_a_team_that_shares_a_store_reads_the_same_chart(self, pinned, rates):
        chart = assets.path("acme/rates:chart/curve", project_dir=pinned)
        assert chart.read_bytes() == b"<html>curve</html>" and chart.name == "curve.html"
        assert rates not in chart.parents  # the store's copy, never the folder
        assert assets.path("acme/rates:notebook/analysis", project_dir=pinned).read_bytes() == b"<html>analysis</html>"
        assert assets.path("acme/rates:note/method", project_dir=pinned).read_bytes() == b"# Method\n"
        assert assets.path("acme/rates:file/raw", project_dir=pinned).read_bytes() == b"raw"

    def test_it_is_the_named_snapshot_not_a_newer_one_at_that_commit(self, pinned, rates, store):
        _write(rates / "_output" / "curve.html", b"<html>drawn again</html>")
        snapshot.make(rates, store=store)  # the same commit, another build
        assert len(snapshot.all_snapshots(store)) == 2
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>curve</html>"

    def test_a_student_reads_their_own_build(self, pinned, rates, work, monkeypatch):
        """No shared store: the lockfile names the author's snapshot, and the student's store has their own of that commit."""
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>the student's</html>")
        taken = snapshot.make(rates, store=own).snapshot
        (entry,) = lock.read_lock(pinned).dependencies
        assert taken.commit == entry["location"]["commit"] and taken.made_at != entry["snapshot"]
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>the student's</html>"
        # And the check passes: the dataframe, the model and the locked file came out the same
        checked = lock.verify(pinned, own)
        assert checked.problems == [] and checked.pins == 3

    def test_the_newest_of_their_builds(self, pinned, rates, work, monkeypatch):
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        for content in (b"first", b"second"):
            _write(rates / "_output" / "curve.html", content)
            snapshot.make(rates, store=own)
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"second"

    def test_with_no_snapshot_at_that_commit_it_says_what_to_build(self, pinned, work, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "empty"))
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:chart/curve", project_dir=pinned)
        said = str(raised.value)
        (entry,) = lock.read_lock(pinned).dependencies
        assert raised.value.reason == "not_in_store"
        assert "'acme/rates:chart/curve' is not in " in said and "chartbook.lock: a chart is drawn anew by every build. " in said
        assert f"It is read from a snapshot of acme/rates at {entry['location']['commit'][:7]}, the commit the lockfile names, and the store at " in said
        assert f" has none. Where a store is shared, wait for its sync. Otherwise build that commit yourself: in its folder, ../rates, at {entry['location']['commit'][:7]}, `chartbook run --snapshot`." in said

    def test_a_plain_file_is_said_for_what_it_is(self, pinned, work, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "empty"))
        with pytest.raises(AssetNotPinnedError, match="a plain file is pinned only when its owner marks it lock = true"):
            assets.path("acme/rates:file/raw", project_dir=pinned)
        with pytest.raises(AssetNotPinnedError, match="a note is pinned only when its owner marks it lock = true"):
            assets.path("acme/rates:note/method", project_dir=pinned)

    def test_a_snapshot_of_another_commit_is_not_read(self, pinned, rates, work, monkeypatch):
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# a later commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)
        snapshot.make(rates, store=own)
        with pytest.raises(AssetNotPinnedError, match="the commit the lockfile names, and the store at .* has none"):
            assets.path("acme/rates:chart/curve", project_dir=pinned)

    def test_a_snapshot_dated_after_now_is_not_read(self, pinned, rates, work, monkeypatch):
        """As `pin` never takes one: it would stand for that commit for as long as its date says."""
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"today's")
        snapshot.make(rates, store=own)
        _write(rates / "_output" / "curve.html", b"dated 2099")
        snapshot.make(rates, store=own, made_at="2099-01-01T00:00:00.000000Z")
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"today's"

    def test_the_snapshot_the_lockfile_names_is_read_whatever_its_date(self, rates, report, work, monkeypatch):
        """A team's store, and a pin made on a machine whose clock is ahead of this one's: the named snapshot is the pin itself."""
        team = FolderStore(work / "team")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "team"))
        commit_pipeline(rates)
        ahead = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        taken = snapshot.make(rates, store=team, made_at=ahead).snapshot
        document = lock.Lock(root="acme/report")
        document.dependencies = [
            {
                "id": "acme/rates", "via": "path", "location": {"kind": "path", "path": "../rates", "commit": taken.commit},
                "snapshot": taken.made_at, "pinned_from": "acme/rates",
            }
        ]
        document.assets = {
            record["id"]: record for record in (snapshot.renamed(taken.assets[name], "acme/rates") for name in taken.assets)
            if lock.in_lockfile(record)
        }
        lock.write_lock(document, report / lock.LOCK_FILE)
        assert snapshot.made_in_the_future(taken)
        assert assets.path("acme/rates:treasury", project_dir=report).read_bytes() == b"rows"
        assert assets.path("acme/rates:chart/curve", project_dir=report).read_bytes() == b"<html>curve</html>"

    def test_an_older_build_that_holds_it_is_read_when_the_newest_does_not(self, pinned, rates, work, monkeypatch):
        """A later, partial build of that commit: what is asked for is read from the newest build that has it, and gc keeps that one too."""
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>the student's</html>")
        first = snapshot.make(rates, store=own, made_at="2026-01-05T00:00:00.000000Z").snapshot
        (rates / "_output" / "curve.html").unlink()
        second = snapshot.make(rates, store=own, made_at="2026-01-06T00:00:00.000000Z").snapshot
        assert second.commit == first.commit and not second.assets["chart/curve"].get("content_hash")
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>the student's</html>"
        plan = lock.plan_gc(own, keep_days=0, recent_seconds=0)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert set(kept) == {first.made_at, second.made_at}
        assert kept[first.made_at] == "a lockfile pins a snapshot of its commit that this store does not have, and it stands in"
        lock.run_gc(plan, own)
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>the student's</html>"

    def test_never_another_pipelines_snapshot_of_that_commit(self, work, store):
        """Two pipelines in one repository are at one commit, and each has a chart of one name."""
        for name in ("rates", "other"):
            _write_manifest(
                work / "repo" / name,
                {"project": {"id": f"acme/{name}"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}},
            )
            _write(work / "repo" / name / "_output" / "curve.html", name.encode())
        (work / "repo" / ".gitignore").write_text("_output/\n", encoding="utf-8", newline="\n")
        _git(work / "repo", "init", "--quiet", "-b", "main")
        _git(work / "repo", "add", "-A")
        _git(work / "repo", "commit", "--quiet", "-m", "Two pipelines")
        reader = work / "repo" / "reader"
        _write_manifest(reader, {"project": {"id": "acme/reader"}, "dependencies": {"rates": {"path": "../rates"}}})
        snapshot.make(work / "repo" / "rates", store=store)
        assert not lock.pin(reader, store).problems
        # A lockfile from before entries said which pipeline their pins came from, on a machine with its own builds
        path = reader / lock.LOCK_FILE
        document = _document(reader)
        del document["records"][0]["dependencies"][0]["pinned_from"]
        document["records"][0]["dependencies"][0]["snapshot"] = "2026-01-01T00:00:00.000000Z"
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        snapshot.make(work / "repo" / "other", store=store)  # the newer of that commit, and another pipeline's
        assert assets.path("rates:chart/curve", project_dir=reader).read_bytes() == b"rates"
        # With no folder of it here to say which pipeline it is, the read stops and says so
        shutil.rmtree(work / "repo" / "rates")
        with pytest.raises(AssetNotPinnedError, match="does not say which pipeline that is: `chartbook update rates`"):
            assets.path("rates:chart/curve", project_dir=reader)

    def test_a_name_that_is_no_asset_of_it(self, pinned):
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:chart/curv", project_dir=pinned)
        said = str(raised.value)
        assert raised.value.reason == "not_in_lockfile"
        assert "had no chart named 'curv' when it was pinned. Did you mean 'curve'?" in said
        assert "are: curve." in said

    def test_one_not_built_in_it(self, rates, report, store):
        (rates / "_output" / "curve.html").unlink()
        pin_from_snapshots(report, store)
        with pytest.raises(AssetNotPinnedError, match="did not build chart/curve"):
            assets.path("acme/rates:chart/curve", project_dir=report)

    def test_a_locked_file_is_read_by_its_pin(self, pinned, rates, store):
        _write(rates / "_data" / "parameters.xlsx", b"changed since")
        snapshot.make(rates, store=store)
        assert assets.path("acme/rates:file/parameters", project_dir=pinned).read_bytes() == b"parameters"

    def test_a_dataframe_that_is_not_in_it_is_still_an_error(self, pinned):
        with pytest.raises(AssetNotPinnedError, match="had no dataframe named 'gdp' when it was pinned"):
            assets.path("acme/rates:gdp", project_dir=pinned)


class TestADependencyOfChartsOnly:
    """None of its assets is in the lockfile: its entry, naming its snapshot, is the pin."""

    @pytest.fixture
    def charts(self, work):
        directory = work / "charts"
        _write_manifest(
            directory,
            {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}},
        )
        _write(directory / "_output" / "curve.html", b"one")
        return directory

    @pytest.fixture
    def reader(self, work, charts, store):
        directory = work / "reader"
        _write_manifest(directory, {"project": {"id": "acme/reader"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        pin_from_snapshots(directory, store)
        return directory

    def test_its_entry_is_all_the_lockfile_has(self, reader):
        locked = lock.read_lock(reader)
        (entry,) = locked.dependencies
        assert locked.assets == {} and "pinned_hash" not in entry
        assert lock.names_a_snapshot(entry)

    def test_the_check_passes_and_a_read_works(self, reader, store):
        checked = lock.verify(reader, store)
        assert checked.problems == [] and checked.pins == 0
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"

    def test_pin_does_not_move_it(self, reader, charts, store):
        _write(charts / "_output" / "curve.html", b"two")
        before = (reader / lock.LOCK_FILE).read_bytes()
        found = pin_from_snapshots(reader, store)
        assert (reader / lock.LOCK_FILE).read_bytes() == before and not found.written
        assert [(event.status, event.asset) for event in found.events] == [("at_snapshot", None)]
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"
        assert lock.would_pin(reader, store) is None

    def test_update_moves_it(self, reader, charts, store):
        _write(charts / "_output" / "curve.html", b"two")
        found = update_from_snapshots(reader, store=store)
        assert found.written
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"two"

    def test_pin_says_where_it_stays(self, reader, store):
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(reader)])
        assert result.exit_code == 0, result.output
        (entry,) = lock.read_lock(reader).dependencies
        assert (
            f"acme/charts: pinned to its snapshot at {entry['location']['commit'][:7]}; "
            f"none of its assets is in the lockfile" in result.output
        )
        assert "chartbook.lock is unchanged." in result.output

    def test_gc_keeps_the_snapshot_it_names(self, reader, charts, store):
        """The store's note of the lockfile names the snapshot, though it names no object."""
        (note,) = store.roots()
        assert note.hashes == frozenset() or not note.hashes
        (entry,) = lock.read_lock(reader).dependencies
        assert (entry["location"]["commit"], entry["snapshot"]) in set(note.snapshots)
        _write(charts / "_output" / "curve.html", b"two")
        snapshot.make(charts, store=store)
        plan = lock.plan_gc(store, keep_days=0, recent_seconds=0)
        kept = {(taken.commit, taken.made_at) for taken, _ in plan.snapshots_kept}
        assert (entry["location"]["commit"], entry["snapshot"]) in kept

    def test_the_first_read_pins_it(self, work, charts, store, capsys):
        directory = work / "first"
        _write_manifest(directory, {"project": {"id": "acme/first"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        commit_pipeline(charts)
        snapshot.make(charts, store=store)
        assert assets.path("acme/charts:chart/curve", project_dir=directory).read_bytes() == b"one"
        assert "acme/charts: pinned to its newest snapshot" in capsys.readouterr().err
        assert lock.names_a_snapshot(lock.read_lock(directory).dependencies[0])

    def test_lineage_walks_through_it(self, reader, store):
        walked = lineage.walk(reader, store)
        (node,) = walked.root.children
        assert node.kind == "snapshot" and node.pipeline == "acme/charts"


class TestALockfileOfVersion1:
    """One written by ChartBook 0.5 and before, with a record for every asset: read as this version would have it, and written again once."""

    def test_it_is_read_without_what_is_no_longer_pinned(self, pinned, store):
        old = _as_version_1(pinned, store)
        assert len(old["records"]) == 8
        locked = lock.read_lock(pinned)
        assert locked.read_as == "chartbook/lock/v1"
        # The file its owner locks had no mark in a version 1 record: it is let go with the rest until an update
        assert set(locked.assets) == {"acme/rates:treasury", "acme/rates:model/ar1"}
        assert locked.left_out == {"charts": 1, "notebooks": 1, "notes": 1, "files": 2}
        (entry,) = locked.dependencies
        assert entry["pinned_hash"] == lock.pinned_hash(locked.assets.values())
        assert entry["pinned_hash"] != old["records"][0]["dependencies"][0]["pinned_hash"]

    def test_reading_writes_nothing(self, pinned, store):
        _as_version_1(pinned, store)
        before = (pinned / lock.LOCK_FILE).read_bytes()
        assert assets.path("acme/rates:treasury", project_dir=pinned).read_bytes() == b"rows"
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>curve</html>"
        assert lock.verify(pinned, store).problems == []
        assert (pinned / lock.LOCK_FILE).read_bytes() == before

    def test_the_students_check_passes_on_it(self, pinned, rates, store, work, monkeypatch):
        """The failure this ends: 17 of 34 pins were charts and notebooks, which no rebuild gives again."""
        _as_version_1(pinned, store)
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>another random id</html>")
        _write(rates / "_output" / "analysis.html", b"<html>another time for each cell</html>")
        snapshot.make(rates, store=own)
        checked = lock.verify(pinned, own)
        assert checked.problems == [] and checked.pins == 2
        assert checked.earlier == "chartbook/lock/v1" and checked.left_out["charts"] == 1
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(pinned)])
        assert result.exit_code == 0, result.output
        assert (
            "chartbook.lock is in an earlier form, which pinned every asset: its 1 chart, 1 notebook, 1 note "
            "and 2 files are not checked, since they are no longer pinned. `chartbook pin` writes it "
            "again in the new form." in result.output
        )
        assert "2 pin(s) of 1 dependency, all in the store. Nothing written." in result.output

    def test_pin_writes_it_again_once_and_says_so(self, pinned, store):
        _as_version_1(pinned, store)
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(pinned)])
        assert result.exit_code == 0, result.output
        assert (
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again without its "
            "1 chart, 1 notebook, 1 note and 2 files: they are not pinned, and are read from the snapshot the lockfile names, or from your own build of that commit where the store does not have that snapshot." in result.output
        )
        assert "stays pinned" not in result.output and "Wrote " in result.output
        document = _document(pinned)
        assert document["schema"] == lock.SCHEMA
        assert {record["id"] for record in document["records"][1:]} == {"acme/rates:treasury", "acme/rates:model/ar1"}
        again = CliRunner().invoke(main, ["pin", "--project-dir", str(pinned)])
        assert again.exit_code == 0 and "earlier form" not in again.output and "is unchanged" in again.output

    def test_the_pin_does_not_move(self, pinned, rates, store):
        """Written again in the new form, it still names the snapshot it named."""
        old = _as_version_1(pinned, store)
        _write(rates / "_data" / "treasury.parquet", b"newer rows")
        found = pin_from_snapshots(pinned, store)
        assert found.written and found.earlier == "chartbook/lock/v1"
        (entry,) = lock.read_lock(pinned).dependencies
        (was,) = old["records"][0]["dependencies"]
        assert (entry["location"]["commit"], entry["snapshot"]) == (was["location"]["commit"], was["snapshot"])
        assert assets.path("acme/rates:treasury", project_dir=pinned).read_bytes() == b"rows"

    def test_update_takes_what_its_owner_locks(self, pinned, store):
        _as_version_1(pinned, store)
        update_from_snapshots(pinned, store=store)
        assert set(lock.read_lock(pinned).assets) == IN

    def test_a_later_version_is_refused(self, pinned):
        document = _document(pinned)
        document["schema"] = "chartbook/lock/v3"
        (pinned / lock.LOCK_FILE).write_text(json.dumps(document), encoding="utf-8", newline="\n")
        with pytest.raises(lock.LockError, match="reads 'chartbook/lock/v2'"):
            lock.read_lock(pinned)

    def test_lineage_still_matches_a_snapshot_made_from_one(self, pinned, store, work):
        """A snapshot of the report made while its lockfile was version 1 recorded the hash over every asset."""
        _as_version_1(pinned, store)
        commit_pipeline(pinned)
        _git(pinned, "add", "-f", "chartbook.lock")
        _git(pinned, "commit", "--quiet", "-m", "Pin")
        _write_manifest(
            pinned,
            {
                "project": {"id": "acme/report"},
                "dependencies": {"acme/rates": {"path": "../rates"}},
                "dataframes": {"summary": {"path": "./_data/summary.parquet", "docs": "d"}},
            },
        )
        _write(pinned / "_data" / "summary.parquet", b"summary")
        commit_pipeline(pinned)
        made = snapshot.make(pinned, store=store).snapshot
        (recorded,) = made.inputs
        assert recorded["pinned_hash"] != lock.read_lock(pinned).dependencies[0]["pinned_hash"]
        reader = work / "reader"
        _write_manifest(reader, {"project": {"id": "acme/reader"}, "dependencies": {"acme/report": {"path": "../report"}}})
        lock.pin(reader, store)
        walked = lineage.walk(reader, store)
        assert walked.gaps() == [], walked.gaps()


class TestAGitDependency:
    """Pinned from a clean copy of a commit, and pinned whole, as it always was: its bytes are its commit's, the same for everyone, and only the lockfile names them."""

    @pytest.fixture
    def repository(self, work):
        directory = work / "published"
        _write_manifest(directory, UPSTREAM)
        for relative, content in BUILT.items():
            _write(directory / relative, content)
        _git(directory, "init", "--quiet", "-b", "main")
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "Data and charts, committed")
        return directory

    @pytest.fixture
    def reader(self, work, repository, store):
        directory = work / "reader"
        _write_manifest(directory, {"project": {"id": "acme/reader"}, "dependencies": {"acme/rates": {"git": str(repository)}}})
        found = lock.pin(directory, store)
        assert not found.problems, [(event.status, event.asset, event.detail) for event in found.problems]
        return directory

    def test_the_lockfile_holds_every_asset_of_it(self, reader):
        locked = lock.read_lock(reader)
        assert set(locked.assets) == IN | {f"acme/rates:{name}" for name in OUT}
        assert all(record.get("content_hash") for record in locked.assets.values())
        # `lock = true` changes nothing for a repository, and is not written: an update that moves no pin leaves the file
        assert not any("lock" in record for record in locked.assets.values())
        before = (reader / lock.LOCK_FILE).read_bytes()
        assert not lock.update(reader).written and (reader / lock.LOCK_FILE).read_bytes() == before

    def test_a_chart_is_read_from_the_store_by_its_pin(self, reader, repository, store):
        chart = assets.path("acme/rates:chart/curve", project_dir=reader)
        assert chart.read_bytes() == b"<html>curve</html>" and store.root in chart.parents
        assert store.has(lock.read_lock(reader).assets["acme/rates:chart/curve"]["content_hash"])

    def test_on_a_machine_that_never_fetched_the_repository(self, reader, work, store, monkeypatch):
        """CI, a teammate: the same lockfile and store, and no copy of the repository. The check passes, and so does the read."""
        monkeypatch.setenv(config.GIT_CACHE_ENV_VAR, str(work / "another-machine"))
        checked = lock.verify(reader, store)
        assert checked.problems == [] and checked.pins == 7
        assert assets.path("acme/rates:chart/curve", project_dir=reader).read_bytes() == b"<html>curve</html>"
        assert assets.path("acme/rates:treasury", project_dir=reader).read_bytes() == b"rows"

    def test_pinning_again_changes_nothing(self, reader, store):
        before = (reader / lock.LOCK_FILE).read_bytes()
        records = sorted(str(path) for path in store.pinned_snapshot_files())
        found = lock.pin(reader, store)
        assert not found.written and (reader / lock.LOCK_FILE).read_bytes() == before
        assert sorted(str(path) for path in store.pinned_snapshot_files()) == records

    @pytest.mark.skipif(os.name == "nt", reason="chmod does not make a folder read-only on Windows")
    def test_pin_writes_nothing_to_a_store_this_user_may_only_read(self, reader, store):
        """A team's store: everything is pinned and in it, so nothing has to be put there."""
        folders = [store.root, *(path for path in store.root.rglob("*") if path.is_dir())]
        for folder in folders:
            folder.chmod(0o555)
        try:
            result = CliRunner().invoke(main, ["pin", "--project-dir", str(reader)])
        finally:
            for folder in folders:
                folder.chmod(0o755)
        assert result.exit_code == 0, result.output
        assert "acme/rates: 7 already pinned" in result.output and "not pinned" not in result.output

    def test_one_the_repository_does_not_commit_is_said_to_be_not_built(self, work, repository, store):
        _git(repository, "rm", "--quiet", "_output/curve.html")
        _git(repository, "commit", "--quiet", "-m", "The chart is built, not committed")
        directory = work / "second"
        _write_manifest(directory, {"project": {"id": "acme/second"}, "dependencies": {"acme/rates": {"git": str(repository)}}})
        found = lock.pin(directory, store)
        assert {event.asset: event.status for event in found.events if event.asset}["acme/rates:chart/curve"] == "not_built"
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:chart/curve", project_dir=directory)
        assert raised.value.reason == "not_built"

    def test_a_name_that_is_no_asset_of_it(self, reader):
        with pytest.raises(AssetNotPinnedError, match="had no chart named 'curv' when it was pinned. Did you mean 'curve'"):
            assets.path("acme/rates:chart/curv", project_dir=reader)

    def test_one_of_charts_only_is_pinned_by_its_chart(self, work, store):
        directory = work / "charts-only"
        _write_manifest(directory, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(directory / "_output" / "curve.html", b"one")
        _git(directory, "init", "--quiet", "-b", "main")
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "A chart")
        reader = work / "reads-charts"
        _write_manifest(reader, {"project": {"id": "acme/reads"}, "dependencies": {"acme/charts": {"git": str(directory)}}})
        assert not lock.pin(reader, store).problems
        locked = lock.read_lock(reader)
        assert set(locked.assets) == {"acme/charts:chart/curve"} and lock.holds_a_pin(locked.dependencies[0], locked.assets)
        assert lock.verify(reader, store).problems == []
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"
        _write(directory / "_output" / "curve.html", b"two")
        _git(directory, "commit", "--quiet", "-am", "Another")
        before = (reader / lock.LOCK_FILE).read_bytes()
        assert not lock.pin(reader, store).written and (reader / lock.LOCK_FILE).read_bytes() == before
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"
        lock.update(reader, store=store)
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"two"

    def test_a_lockfile_of_version_1_keeps_every_record_of_it(self, reader, store):
        """Nothing of a repository is left out of an old lockfile: it reads as it did, and is written again with all of it."""
        document = _document(reader)
        document["schema"] = "chartbook/lock/v1"
        (reader / lock.LOCK_FILE).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        locked = lock.read_lock(reader)
        assert locked.read_as == "chartbook/lock/v1" and locked.earlier == {} and len(locked.assets) == 7
        assert assets.path("acme/rates:chart/curve", project_dir=reader).read_bytes() == b"<html>curve</html>"
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(reader)])
        assert result.exit_code == 0, result.output
        assert "was in an earlier form, which pinned every asset. It is written again." in result.output
        assert _document(reader)["schema"] == lock.SCHEMA and len(_document(reader)["records"]) == 8


class TestAnOldLockfileInAStoreWithNoRecordOfItsSnapshot:
    """A store migrated from ChartBook 0.2: a snapshot's record cleared, its bytes kept because a lockfile named them. Nothing fails for the lockfile's age."""

    @pytest.fixture
    def migrated(self, pinned, store):
        from tests.fixtures import clear_keeping_its_bytes

        _as_version_1(pinned, store)
        (taken,) = snapshot.all_snapshots(store)
        clear_keeping_its_bytes(store, taken)
        assert snapshot.all_snapshots(store) == []
        return pinned

    def test_a_chart_is_still_read_by_what_the_old_lockfile_names(self, migrated):
        assert assets.path("acme/rates:chart/curve", project_dir=migrated).read_bytes() == b"<html>curve</html>"
        assert assets.path("acme/rates:file/raw", project_dir=migrated).read_bytes() == b"raw"

    def test_gc_keeps_what_it_names_while_it_is_the_old_form(self, migrated, store):
        assert lock.verify(migrated, store, note=True).problems == []
        plan = lock.plan_gc(store, keep_days=0, recent_seconds=0)
        assert plan.delete == [] and len(lock.read_lock(migrated).earlier) == 5

    def test_the_check_counts_them_as_the_pins_they_stay(self, migrated, store):
        locked = lock.read_lock(migrated)
        assert set(locked.earlier) == {f"acme/rates:{name}" for name in OUT} | {"acme/rates:file/parameters"}
        assert not set(locked.earlier) & set(locked.assets)
        checked = lock.verify(migrated, store)
        assert checked.problems == [] and checked.pins == 7 and checked.kept_earlier == 5 and checked.left_out == {}
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(migrated)])
        assert result.exit_code == 0, result.output
        assert (
            "chartbook.lock is in an earlier form, which pinned every asset; 5 of its records of charts, notebooks, "
            "notes and files are checked all the same, the store having their bytes and no snapshot to read them from. "
            "`chartbook pin` writes it again in the new form." in result.output
        )

    def test_written_again_it_keeps_them_and_reads_as_it_did(self, migrated, store):
        """What the review found: the first `chartbook pin` after upgrading made a readable chart unreadable, and gc then removed the only copy."""
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(migrated)])
        assert result.exit_code == 0, result.output
        assert (
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again. 5 of its records of "
            "charts, notebooks, notes and files stay pinned as they were: the store has their bytes, and no snapshot "
            "there to read them from." in result.output
        )
        locked = lock.read_lock(migrated)
        assert locked.read_as == lock.SCHEMA and len(locked.assets) == 7 and locked.earlier == {}
        assert assets.path("acme/rates:chart/curve", project_dir=migrated).read_bytes() == b"<html>curve</html>"
        assert assets.path("acme/rates:file/raw", project_dir=migrated).read_bytes() == b"raw"
        assert lock.verify(migrated, store, note=True).problems == []
        assert lock.plan_gc(store, keep_days=0, recent_seconds=0).delete == []
        # And a second pin finds nothing to say
        again = CliRunner().invoke(main, ["pin", "--project-dir", str(migrated)])
        assert again.exit_code == 0 and "earlier form" not in again.output and "is unchanged" in again.output

    def test_an_update_lets_them_go(self, migrated, rates, store):
        """The pin moves to a snapshot, which names what it holds: the lockfile is by kind from then on."""
        update_from_snapshots(migrated, store=store)
        assert set(lock.read_lock(migrated).assets) == IN
        assert assets.path("acme/rates:chart/curve", project_dir=migrated).read_bytes() == b"<html>curve</html>"

    def test_a_build_script_that_reads_a_chart_still_runs(self, migrated, store):
        """`chartbook run` writes the lockfile again before it builds: the build then reads what it read before."""
        import sys

        _write_manifest(
            migrated,
            {
                "project": {"id": "acme/report"},
                "scripts": {"build": f'{sys.executable} -c "from chartbook import assets; print(assets.path(\'acme/rates:chart/curve\').read_bytes())"'},
                "dependencies": {"acme/rates": {"path": "../rates"}},
            },
        )
        result = CliRunner().invoke(main, ["run", "--project-dir", str(migrated)])
        assert result.exit_code == 0, result.output
        assert CliRunner().invoke(main, ["run", "--frozen", "--project-dir", str(migrated)]).exit_code == 0


    def test_a_first_read_of_another_dependency_keeps_them_too(self, migrated, work, store, capsys):
        """A read that pins one dependency writes the lockfile for all of them: what it held of the others stays."""
        other = work / "other"
        _write_manifest(other, {"project": {"id": "acme/other"}, "dataframes": {"gdp": {"path": "./_data/gdp.parquet", "docs": "d"}}})
        _write(other / "_data" / "gdp.parquet", b"gdp")
        commit_pipeline(other)
        snapshot.make(other, store=store)
        _write_manifest(
            migrated,
            {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}, "acme/other": {"path": "../other"}}},
        )
        assert assets.path("acme/other:gdp", project_dir=migrated).read_bytes() == b"gdp"
        locked = lock.read_lock(migrated)
        assert locked.read_as == lock.SCHEMA and len(locked.assets_of("acme/rates")) == 7
        assert assets.path("acme/rates:chart/curve", project_dir=migrated).read_bytes() == b"<html>curve</html>"
        assert "5 of its records of charts, notebooks, notes and files stay pinned as they were" in capsys.readouterr().err

    def test_one_no_longer_declared_keeps_them_while_a_read_pins_another(self, migrated, work, store):
        """A pin of one dependency alone leaves the rest of the lockfile as it was, the entry of one the manifest has dropped too."""
        other = work / "other"
        _write_manifest(other, {"project": {"id": "acme/other"}, "dataframes": {"gdp": {"path": "./_data/gdp.parquet", "docs": "d"}}})
        _write(other / "_data" / "gdp.parquet", b"gdp")
        commit_pipeline(other)
        snapshot.make(other, store=store)
        _write_manifest(migrated, {"project": {"id": "acme/report"}, "dependencies": {"acme/other": {"path": "../other"}}})
        assert assets.path("acme/other:gdp", project_dir=migrated).read_bytes() == b"gdp"
        assert len(lock.read_lock(migrated).assets_of("acme/rates")) == 7

    def test_on_another_machine_what_was_kept_is_no_pin(self, migrated, rates, store, work, monkeypatch):
        """The lockfile, written again here with five records kept, and committed. A student who built that commit themselves reads their own chart, and the check passes: a record kept is a pin only where its bytes are."""
        assert CliRunner().invoke(main, ["pin", "--project-dir", str(migrated)]).exit_code == 0
        kept = (migrated / lock.LOCK_FILE).read_bytes()
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>the student's</html>")
        _write(rates / "_output" / "analysis.html", b"<html>the student's notebook</html>")
        snapshot.make(rates, store=own)
        checked = lock.verify(migrated, own)
        assert checked.problems == [], [problem.message for problem in checked.problems]
        assert checked.passed_over == 2 and checked.pins == 5  # the chart and the notebook; the rest came out in the same bytes
        assert assets.path("acme/rates:chart/curve", project_dir=migrated).read_bytes() == b"<html>the student's</html>"
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(migrated)])
        assert result.exit_code == 0, result.output
        assert "lost" not in result.output and "changed upstream" not in result.output
        assert (migrated / lock.LOCK_FILE).read_bytes() == kept


class TestAnOldLockfileWhoseEntryNamesNoSnapshot:
    """Pinned before a pin named its snapshot: the records are all that names what was pinned, so none of them is let go."""

    @pytest.fixture
    def charts(self, work):
        directory = work / "charts"
        _write_manifest(directory, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(directory / "_output" / "curve.html", b"one")
        return directory

    @pytest.fixture
    def old(self, work, charts, store):
        directory = work / "reads-charts"
        _write_manifest(directory, {"project": {"id": "acme/reads"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        pin_from_snapshots(directory, store)
        document = _as_version_1(directory, store)
        (entry,) = document["records"][0]["dependencies"]
        del entry["location"]["commit"], entry["snapshot"]
        (directory / lock.LOCK_FILE).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return directory

    def test_the_check_passes_on_it_as_it_is(self, old, store):
        checked = lock.verify(old, store)
        assert checked.problems == [] and checked.pins == 1 and checked.kept_earlier == 1

    def test_neither_a_read_nor_pin_moves_it_when_its_owner_makes_a_newer_snapshot(self, old, charts, store, capsys):
        _write(charts / "_output" / "curve.html", b"two")
        _write_manifest(charts, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d", "caption": "newer"}}})
        from tests.fixtures import snapshot_dependencies

        snapshot_dependencies(old, store)
        before = (old / lock.LOCK_FILE).read_bytes()
        assert assets.path("acme/charts:chart/curve", project_dir=old).read_bytes() == b"one"
        assert (old / lock.LOCK_FILE).read_bytes() == before  # a read wrote nothing
        found = lock.pin(old, store)
        assert not found.problems and found.kept_earlier == 1
        locked = lock.read_lock(old)
        assert locked.read_as == lock.SCHEMA and set(locked.assets) == {"acme/charts:chart/curve"}
        assert assets.path("acme/charts:chart/curve", project_dir=old).read_bytes() == b"one"

    def test_in_a_batch_run_it_is_read_too(self, old, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        assert assets.path("acme/charts:chart/curve", project_dir=old).read_bytes() == b"one"


class TestAnOldLockfileThatDoesNotSayWhichPipeline:
    """Written before 0.3.0: an entry with no ``pinned_from``. For a dependency named by its folder, the pipeline is the one that folder holds: one answer for a read, the checks and what is kept."""

    @pytest.fixture
    def old(self, pinned, store):
        document = _as_version_1(pinned, store)
        (entry,) = document["records"][0]["dependencies"]
        entry.pop("pinned_from", None)
        entry["location"].pop("pipeline", None)
        (pinned / lock.LOCK_FILE).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return pinned

    def test_where_the_store_has_the_named_snapshot_nothing_is_kept(self, old, store):
        checked = lock.verify(old, store)
        assert checked.problems == [] and checked.pins == 2 and checked.kept_earlier == 0
        assert CliRunner().invoke(main, ["pin", "--project-dir", str(old)]).exit_code == 0
        assert set(lock.read_lock(old).assets) == {"acme/rates:treasury", "acme/rates:model/ar1"}

    def test_a_team_and_a_student_write_the_same_file(self, old, rates, store, work, monkeypatch):
        before = (old / lock.LOCK_FILE).read_bytes()
        assert CliRunner().invoke(main, ["pin", "--project-dir", str(old)]).exit_code == 0
        teams = (old / lock.LOCK_FILE).read_bytes()
        (old / lock.LOCK_FILE).write_bytes(before)
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>the student's</html>")
        snapshot.make(rates, store=own)
        assert lock.verify(old, own).problems == []
        assert CliRunner().invoke(main, ["pin", "--project-dir", str(old)]).exit_code == 0
        assert (old / lock.LOCK_FILE).read_bytes() == teams

    def test_the_check_and_a_read_agree_for_one_of_charts_only(self, work, store, monkeypatch):
        charts = work / "charts"
        _write_manifest(charts, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(charts / "_output" / "curve.html", b"one")
        reader = work / "reads-charts"
        _write_manifest(reader, {"project": {"id": "acme/reads"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        pin_from_snapshots(reader, store)
        document = _document(reader)
        document["records"][0]["dependencies"][0].pop("pinned_from", None)
        (reader / lock.LOCK_FILE).write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(charts / "_output" / "curve.html", b"the student's")
        snapshot.make(charts, store=own)
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"the student's"
        checked = lock.verify(reader, own)
        assert checked.problems == [] and checked.by_entry == 1


class TestTheSnapshotALockfileNamesIsTakenWhole:
    """Where the store has the snapshot a lockfile names, an asset is read from it and from no other: a later build of that commit is another snapshot, and `chartbook update` moves to it."""

    def test_an_asset_it_did_not_build_is_not_read_from_a_later_build_of_that_commit(self, rates, report, store):
        (rates / "_output" / "curve.html").unlink()
        pin_from_snapshots(report, store)
        _write(rates / "_output" / "curve.html", b"<html>built later, same commit</html>")
        later = snapshot.make(rates, store=store)
        assert later.made
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:chart/curve", project_dir=report)
        assert raised.value.reason == "not_built"
        assert "It is read from the snapshot the lockfile names" in str(raised.value)
        assert "then `chartbook update acme/rates` in " in str(raised.value)
        # So gc, which keeps the named snapshot and not the later build for this lockfile, takes no read away
        lock.verify(report, store, note=True)
        lock.run_gc(lock.plan_gc(store, keep_days=0, recent_seconds=0), store)
        with pytest.raises(AssetNotPinnedError) as again:
            assets.path("acme/rates:chart/curve", project_dir=report)
        assert again.value.reason == "not_built"
        update_from_snapshots(report, store=store)
        assert assets.path("acme/rates:chart/curve", project_dir=report).read_bytes() == b"<html>built later, same commit</html>"


class TestWhatStaysOfAnOldLockfileIsWhatCannotBeReadOtherwise:

    def test_a_build_whose_bytes_the_store_has_lost_reads_nothing(self, pinned, rates, store, work, monkeypatch):
        """Your build names the chart, and the store has lost that file; it still has the bytes the old lockfile named. The record stays."""
        from tests.fixtures import clear_keeping_its_bytes

        _as_version_1(pinned, store)
        old = lock.read_lock(pinned).earlier["acme/rates:chart/curve"]["content_hash"]
        (named,) = snapshot.all_snapshots(store)
        clear_keeping_its_bytes(store, named)
        _write(rates / "_output" / "curve.html", b"<html>built again</html>")
        again = snapshot.make(rates, store=store).snapshot
        store.delete(again.assets["chart/curve"]["content_hash"])
        assert store.has(old)
        kept = lock.still_pinned(lock.read_lock(pinned).earlier_of("acme/rates"), lock.read_lock(pinned).dependencies[0], store, lambda: snapshot.readable_snapshots(store)[0])
        assert "acme/rates:chart/curve" in kept and "acme/rates:notebook/analysis" not in kept
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>curve</html>"


class TestAFirstReadThroughAnOldLockfile:

    def test_it_says_that_it_wrote_the_lockfile_again(self, pinned, rates, work, store, capsys):
        """A newly declared dependency is pinned by its first read, which writes the lockfile: in the new form, and said."""
        _as_version_1(pinned, store)
        other = work / "other"
        _write_manifest(other, {"project": {"id": "acme/other"}, "dataframes": {"gdp": {"path": "./_data/gdp.parquet", "docs": "d"}}})
        _write(other / "_data" / "gdp.parquet", b"gdp")
        commit_pipeline(other)
        snapshot.make(other, store=store)
        _write_manifest(
            pinned,
            {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}, "acme/other": {"path": "../other"}}},
        )
        assert assets.path("acme/other:gdp", project_dir=pinned).read_bytes() == b"gdp"
        said = capsys.readouterr().err
        assert "acme/other: pinned to its newest snapshot" in said
        assert (
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again without its "
            "1 chart, 1 notebook, 1 note and 2 files: they are not pinned, and are read from the snapshot the lockfile names, or from your own build of that commit where the store does not have that snapshot." in said
        )
        assert _document(pinned)["schema"] == lock.SCHEMA


class TestWhatKeepsASnapshotThatStandsIn:

    def test_gc_keeps_your_build_of_a_commit_whose_pinned_snapshot_you_do_not_have(self, pinned, rates, work, monkeypatch):
        """The lockfile names its author's snapshot. Yours of that commit is what is read, and is not the newest of its pipeline for long."""
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        _write(rates / "_output" / "curve.html", b"<html>the student's</html>")
        standing = snapshot.make(rates, store=own, made_at="2026-01-05T00:00:00.000000Z").snapshot
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>the student's</html>"  # leaves the note
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# a later commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)
        newest = snapshot.make(rates, store=own).snapshot
        plan = lock.plan_gc(own, keep_days=0, recent_seconds=0)
        kept = {taken.made_at: why for taken, why in plan.snapshots_kept}
        assert set(kept) == {standing.made_at, newest.made_at}
        assert kept[standing.made_at] == "a lockfile pins a snapshot of its commit that this store does not have, and it stands in"
        lock.run_gc(plan, own)
        assert assets.path("acme/rates:chart/curve", project_dir=pinned).read_bytes() == b"<html>the student's</html>"

    def test_a_reader_of_charts_only_leaves_its_note(self, work, store):
        """A machine that only reads: the note names the snapshot, though the lockfile names no bytes."""
        charts = work / "charts"
        _write_manifest(charts, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(charts / "_output" / "curve.html", b"one")
        reader = work / "reader"
        _write_manifest(reader, {"project": {"id": "acme/reader"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        pin_from_snapshots(reader, store)
        for note in store.roots():
            store.remove_root(note.lockfile, machine=note.machine)
        assert store.roots() == []
        wrote, why = lock.note_this_machine(reader / lock.LOCK_FILE, lock.read_lock(reader), store)
        assert wrote and not why
        (note,) = store.roots()
        assert not note.hashes and len(note.snapshots) == 1


class TestTheCheckOfADependencyOfChartsOnly:

    @pytest.fixture
    def reader(self, work, store):
        charts = work / "charts"
        _write_manifest(charts, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(charts / "_output" / "curve.html", b"one")
        reader = work / "reader"
        _write_manifest(reader, {"project": {"id": "acme/reader"}, "dependencies": {"acme/charts": {"path": "../charts"}}})
        pin_from_snapshots(reader, store)
        return reader

    def test_it_says_how_it_is_pinned(self, reader):
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(reader)])
        assert result.exit_code == 0, result.output
        assert (
            "0 pin(s) of 1 dependency, all in the store; 1 dependency is pinned by its snapshot alone, which the "
            "store has a build of. Nothing written." in result.output
        )

    def test_a_store_with_no_snapshot_of_that_commit_cannot_build_it(self, reader, work, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "empty"))
        (problem,) = lock.verify(reader, FolderStore(work / "empty")).problems
        assert "with none of its assets in the lockfile" in problem.message and "has no snapshot of it at that commit" in problem.message
        assert "`chartbook run --snapshot`" in problem.message

    def test_chartbook_check_does_not_say_it_builds_without_its_folder(self, reader, work, monkeypatch):
        from chartbook import check

        entry = {"path": "../charts", "_resolved_path": str(work / "nowhere")}
        said, builds = check._not_on_this_machine(reader, "acme/charts", entry, work / "nowhere")
        assert builds and "so this pipeline builds here" in said
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "empty"))
        (work / "empty").mkdir()
        said, builds = check._not_on_this_machine(reader, "acme/charts", entry, work / "nowhere")
        assert not builds and "the store does not have all that the lockfile pins of it" in said

    @pytest.mark.parametrize("what", ["another pipeline's snapshot of that commit", "one of its own dated after now"])
    def test_the_checks_take_only_a_snapshot_a_read_takes(self, reader, work, monkeypatch, what):
        """Whether it builds is asked of the same snapshots a read is given: of that pipeline, and not dated after now."""
        from chartbook import check

        charts = work / "charts"
        other = FolderStore(work / "other-store")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "other-store"))
        if what.startswith("another"):
            _write_manifest(charts, {"project": {"id": "acme/other"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
            _git(charts, "update-index", "--assume-unchanged", "chartbook.toml")  # the same commit, as two pipelines of one repository are
            made = snapshot.make(charts, store=other).snapshot
            assert made.pipeline == "acme/other"
        else:
            made = snapshot.make(charts, store=other, made_at="2099-01-01T00:00:00.000000Z").snapshot
        (entry,) = lock.read_lock(reader).dependencies
        assert made.commit == entry["location"]["commit"]
        with pytest.raises(AssetNotPinnedError):
            assets.path("acme/charts:chart/curve", project_dir=reader)
        (problem,) = lock.verify(reader, other).problems
        assert "has no snapshot of it at that commit" in problem.message
        declared = {"path": "../charts", "_resolved_path": str(work / "nowhere")}
        said, builds = check._not_on_this_machine(reader, "acme/charts", declared, work / "nowhere")
        assert not builds

    def test_lineage_through_a_snapshot_that_was_pinned_to_it(self, reader, store, work):
        """The reader's own snapshot records that it was pinned to a snapshot of charts only: the walk goes through it."""
        _write_manifest(
            reader,
            {
                "project": {"id": "acme/reader"}, "dependencies": {"acme/charts": {"path": "../charts"}},
                "dataframes": {"table": {"path": "./_data/table.parquet", "docs": "d"}},
            },
        )
        _write(reader / "_data" / "table.parquet", b"table")
        commit_pipeline(reader)
        _git(reader, "add", "-f", "chartbook.lock")
        _git(reader, "commit", "--quiet", "-m", "Pin")
        made = snapshot.make(reader, store=store).snapshot
        assert made.inputs[0]["id"] == "acme/charts" and "pinned_hash" not in made.inputs[0]
        above = work / "above"
        _write_manifest(above, {"project": {"id": "acme/above"}, "dependencies": {"acme/reader": {"path": "../reader"}}})
        lock.pin(above, store)
        walked = lineage.walk(above, store)
        (node,) = walked.root.children
        (inner,) = node.children
        assert (inner.kind, inner.pipeline) == ("snapshot", "acme/charts") and walked.gaps() == []


class TestADependencyNamedByItsIdAndGotFromItsRepository:
    """`"acme/charts" = {}`, with a default host and no snapshot in the store: cloned, and pinned by its commit."""

    def test_pin_does_not_move_one_of_charts_only_when_the_store_gets_a_snapshot(self, work, store, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: work / "user" / ".chartbook")
        settings = config.get_global_settings_path()
        assert not settings.is_relative_to(Path.home() / ".chartbook")
        settings.parent.mkdir(parents=True)
        settings.write_text(tomli_w.dumps({"resolve": {"default_host": str(work / "host")}}), encoding="utf-8", newline="\n")
        repository = work / "host" / "acme" / "charts"
        _write_manifest(repository, {"project": {"id": "acme/charts"}, "charts": {"curve": {"path": "./_output/curve.html", "docs": "d"}}})
        _write(repository / "_output" / "curve.html", b"one")
        _git(repository, "init", "--quiet", "-b", "main")
        _git(repository, "add", "-A")
        _git(repository, "commit", "--quiet", "-m", "A chart")
        reader = work / "reader"
        _write_manifest(reader, {"project": {"id": "acme/reader"}, "dependencies": {"acme/charts": {}}})
        assert not lock.pin(reader, store).problems
        (entry,) = lock.read_lock(reader).dependencies
        # Got from its repository, so pinned whole: its chart is its pin
        assert entry["location"]["kind"] == "git" and set(lock.read_lock(reader).assets) == {"acme/charts:chart/curve"}
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"
        # Its owner snapshots a newer commit into the store: `pin` stays where it is, and `update` looks again
        _write(repository / "_output" / "curve.html", b"two")
        _git(repository, "commit", "--quiet", "-am", "Another")
        snapshot.make(repository, store=store)
        before = (reader / lock.LOCK_FILE).read_bytes()
        assert not lock.pin(reader, store).written and (reader / lock.LOCK_FILE).read_bytes() == before
        assert lock.would_pin(reader, store) is None
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"one"
        lock.update(reader, store=store)
        assert lock.read_lock(reader).dependencies[0]["location"]["kind"] == "store"
        assert assets.path("acme/charts:chart/curve", project_dir=reader).read_bytes() == b"two"
