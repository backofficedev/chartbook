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
import subprocess
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
            "each build draws them anew" in result.output
        )

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
        assert "a chart is drawn anew by every build" in said and "not pinned" in said
        assert f"has no snapshot of acme/rates at {entry['location']['commit'][:7]}" in said
        assert "`chartbook snapshot`" in said

    def test_a_snapshot_of_another_commit_is_not_read(self, pinned, rates, work, monkeypatch):
        own = FolderStore(work / "student")
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# a later commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)
        snapshot.make(rates, store=own)
        with pytest.raises(AssetNotPinnedError, match="has no snapshot of acme/rates at"):
            assets.path("acme/rates:chart/curve", project_dir=pinned)

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
            "and 2 files are not checked, since no rebuild gives their bytes again. `chartbook pin` writes it "
            "again in the new form." in result.output
        )
        assert "2 pin(s) of 1 dependency, all in the store. Nothing written." in result.output

    def test_pin_writes_it_again_once_and_says_so(self, pinned, store):
        _as_version_1(pinned, store)
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(pinned)])
        assert result.exit_code == 0, result.output
        assert (
            "chartbook.lock was in an earlier form, which pinned every asset. It is written again without its "
            "1 chart, 1 notebook, 1 note and 2 files: each build draws them anew, so they are read from the "
            "snapshot the lockfile names, and not pinned." in result.output
        )
        assert "Wrote " in result.output
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
    """Pinned from a clean copy of a commit: what the lockfile does not hold of it is kept with the pin, for a read to find."""

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

    def test_the_lockfile_holds_what_code_reads(self, reader):
        locked = lock.read_lock(reader)
        assert set(locked.assets) == IN
        assert locked.assets["acme/rates:file/parameters"]["lock"] is True

    def test_what_it_does_not_hold_is_read_from_the_pins_snapshot(self, reader):
        assert assets.path("acme/rates:chart/curve", project_dir=reader).read_bytes() == b"<html>curve</html>"
        assert assets.path("acme/rates:file/raw", project_dir=reader).read_bytes() == b"raw"

    def test_pinning_again_changes_nothing(self, reader, store):
        before = (reader / lock.LOCK_FILE).read_bytes()
        records = sorted(str(path) for path in store.pinned_snapshot_files())
        found = lock.pin(reader, store)
        assert not found.written and (reader / lock.LOCK_FILE).read_bytes() == before
        assert sorted(str(path) for path in store.pinned_snapshot_files()) == records

    def test_the_check_passes(self, reader, store):
        checked = lock.verify(reader, store)
        assert checked.problems == [] and checked.pins == 3
