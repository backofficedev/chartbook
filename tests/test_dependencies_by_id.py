"""A dependency named by its pipeline ID alone, pinned from its snapshots in the store, with no folder
of it and no clone (docs_src/design/reading-other-pipelines.md, decision 1a)."""

import json
import shutil
import sys
import warnings
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w

from chartbook import data, lineage, lock, snapshot
from chartbook.index import SCHEMAS_DIR, build_index
from chartbook.manifest import load_manifest
from tests.test_model_versions import _git


def _commit(repository: Path, message: str = "Work") -> None:
    _git(repository, "add", "-A")
    _git(repository, "commit", "--quiet", "-m", message)


def _rates(folder: Path, value: float) -> None:
    (folder / "_data").mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."}}})
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(folder / "_data" / "treasury.parquet")


def _forecast(folder: Path, dependencies: dict, scripts=None) -> Path:
    (folder / "_data").mkdir(parents=True, exist_ok=True)
    manifest = {
        "project": {"id": "acme/forecast"},
        "dependencies": dependencies,
        "dataframes": {"outlook": {"path": "./_data/outlook.parquet", "docs": "Its output."}},
    }
    if scripts:
        manifest["scripts"] = scripts
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    pl.DataFrame({"d": ["2024-02-01"], "f": [1.0]}).write_parquet(folder / "_data" / "outlook.parquet")
    return folder


@pytest.fixture
def elsewhere(tmp_path):
    """`acme/rates` snapshotted twice, at two commits, on "machine 1"; then its folder gone."""
    work = tmp_path.resolve()
    machine_one = work / "machine-one"
    rates = machine_one / "rates"
    _rates(rates, 4.1)
    _git(machine_one, "init", "--quiet", "-b", "main")
    (machine_one / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(machine_one)
    first = snapshot.make(rates).snapshot
    _rates(rates, 4.2)
    (rates / "notes.txt").write_text("a second commit\n")
    _commit(machine_one, "Second")
    second = snapshot.make(rates).snapshot
    shutil.rmtree(machine_one)
    return work, first, second


def _pinned(forecast: Path) -> dict:
    (entry,) = lock.read_lock(forecast / lock.LOCK_FILE).dependencies
    return entry


class TestPinnedFromTheStore:
    def test_the_newest_snapshot_with_no_folder_and_no_clone(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        entry = _pinned(forecast)
        assert entry["via"] == "store" and entry["location"] == {
            "kind": "store", "pipeline": "acme/rates", "commit": second.commit, "first_commit": second.first_commit,
        }
        assert entry["snapshot"] == second.made_at
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]
        assert lock.verify(forecast).problems == []

    def test_commit_narrows_it(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": first.commit[:7]}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == first.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]

    def test_a_short_local_name(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("rates:treasury").collect()["r"].to_list() == [4.2]

    def test_pin_keeps_and_update_moves(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": first.commit[:7]}})
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {}})  # the manifest now takes the newest
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == first.commit  # pin never moves a pin
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit

    def test_one_with_no_snapshot_says_what_to_do(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/other": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "no_snapshot"]
        assert "has no snapshot of acme/other" in event.detail and "chartbook snapshot" in event.detail


class TestTheRestOfChartBookKnowsIt:
    def test_its_snapshot_carries_its_lineage(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        _git(forecast, "init", "--quiet", "-b", "main")
        (forecast / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(forecast)
        with pytest.raises(snapshot.SnapshotError, match="its pins do not account"):
            snapshot.make(forecast)
        lock.pin(forecast)
        taken = snapshot.make(forecast).snapshot
        assert taken.inputs[0]["location"]["kind"] == "store"
        (node,) = lineage.walk(forecast).root.children
        assert (node.label, node.pipeline, node.commit) == ("acme/rates", "acme/rates", second.commit)
        assert lineage.walk(forecast).gaps() == []

    def test_check_says_it_is_not_pinned_and_then_nothing(self, elsewhere):
        from chartbook.check import check_dependencies

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        with pytest.warns(UserWarning, match="not pinned"):
            assert check_dependencies(load_manifest(forecast), forecast) == []
        lock.pin(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert check_dependencies(load_manifest(forecast), forecast) == []

    def test_the_index_records_it(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"commit": second.commit[:9]}})
        lock.pin(forecast)
        built = build_index(load_manifest(forecast))
        record = next(r for r in built["records"] if r["kind"] == "Pipeline")
        (dependency,) = record["dependencies"]
        assert dependency["via"] == "store"
        assert dependency["location"] == {"kind": "store", "pipeline": "acme/rates", "at": second.commit[:9], "commit": second.commit}
        schema = json.loads((Path(SCHEMAS_DIR) / "v1" / "Pipeline.json").read_text())
        jsonschema.validate(record, schema)

    def test_run_pins_it_and_builds_only_this_pipeline(self, elsewhere):
        from chartbook import run

        work, first, second = elsewhere
        script = f"{sys.executable} -c \"open('_data/built', 'w').close()\""
        forecast = _forecast(work / "forecast", {"acme/rates": {}}, scripts={"build": script})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/forecast"]
        assert (forecast / "_data" / "built").exists() and _pinned(forecast)["location"]["commit"] == second.commit


class TestAdd:
    def test_the_text_keeps_everything_else(self):
        from chartbook.manifest import with_dependency

        text = '# a pipeline\n[project]\nid = "acme/forecast"  # its ID\n\n[dependencies]\n# from the store\n"acme/yields" = {}\n'
        changed = with_dependency(text, "acme/rates", {})
        assert changed == text.replace('[dependencies]\n', '[dependencies]\n"acme/rates" = {}\n')
        changed = with_dependency("[project]\nname = 'x'\n", "rates", {"id": "acme/rates", "commit": "3f2a9c1"})
        assert changed.endswith('\n[dependencies]\n"rates" = { id = "acme/rates", commit = "3f2a9c1" }\n')
        with pytest.raises(ValueError, match="has 'acme/yields' already"):
            with_dependency(text, "acme/yields", {})
        with pytest.raises(ValueError, match="Add the entry there yourself"):
            with_dependency('dependencies = { "a/b" = {} }\n', "acme/rates", {})

    def test_the_command_declares_and_pins(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        (forecast / "chartbook.toml").write_text("# my notes\n" + (forecast / "chartbook.toml").read_text())
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/rates", "--as", "rates"])
        assert result.exit_code == 0, result.output
        assert 'Added to [dependencies]' in result.output and '"rates" = { id = "acme/rates" }' in result.output
        assert (forecast / "chartbook.toml").read_text().startswith("# my notes\n")
        assert data.load("rates:treasury").collect()["r"].to_list() == [4.2]
        again = CliRunner().invoke(main, ["add", "acme/rates", "--as", "rates"])
        assert again.exit_code == 1 and "already" in again.output

    def test_a_bad_commit_writes_nothing(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        before = (forecast / "chartbook.toml").read_text()
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/rates", "--commit", "zzz"])
        assert result.exit_code == 1 and "is not the start of a commit" in result.output
        assert (forecast / "chartbook.toml").read_text() == before


class TestAPathDependency:
    def test_in_another_repository_it_says_to_name_it_by_its_id(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        upstream = work / "theirs" / "rates"
        _rates(upstream, 4.0)
        _git(work / "theirs", "init", "--quiet", "-b", "main")
        _commit(work / "theirs")
        forecast = _forecast(work / "mine" / "forecast", {"acme/rates": {"path": "../../theirs/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match='is in another git repository.*"acme/rates" = {}'):
            check_dependencies(load_manifest(forecast), forecast)

    def test_in_the_same_repository_it_says_nothing_of_it(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        with warnings.catch_warnings(record=True) as said:
            warnings.simplefilter("always")
            check_dependencies(load_manifest(forecast), forecast)
        assert not [w for w in said if "another git repository" in str(w.message)]


def _another(work: Path, name: str, value: float, remote=None, made_at=None):
    """A pipeline in a repository of its own that also calls itself `acme/rates`, snapshotted."""
    repository = work / name
    folder = repository / "rates"
    _rates(folder, value)
    _git(repository, "init", "--quiet", "-b", "main")
    if remote:
        _git(repository, "remote", "add", "origin", remote)
    (repository / ".gitignore").write_text("_data/\nchartbook.lock\n")
    (repository / "README.md").write_text(f"{name}\n")  # its own history, from its first commit
    _commit(repository)
    return snapshot.make(folder, made_at=made_at).snapshot


class TestWhatTheReviewFound:
    def test_a_snapshot_dated_after_now_is_never_the_newest(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forged = _another(work, "forger", 666.0, made_at="2099-01-01T00:00:00.000000Z")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]
        from chartbook.store import default_store

        plan = snapshot.plan_removals(default_store(), set(), set(), keep_days=7)
        assert (forged.path, "nothing pins it, and it is dated more than 7 days after now, so it is not taken as made") in [
            (t.path, w) for t, w in plan.remove
        ]
        assert any(t.commit == second.commit and w == "it is the newest of its pipeline" for t, w in plan.keep)

    def test_two_repositories_claiming_one_id_are_not_pinned_until_one_is_named(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates.git")
        assert real.repository == "https://github.com/acme/rates"
        _another(work, "collision", 9.0, remote="git@github.com:someone/rates.git")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "no_snapshot"]
        assert "2 repositories claim the ID acme/rates" in event.detail and 'repository = "..."' in event.detail
        _forecast(forecast, {"acme/rates": {"repository": "git@github.com:acme/rates.git"}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_an_update_keeps_to_the_repository_first_pinned(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        _another(work, "later", 9.0, remote="https://github.com/someone/rates")  # newer, from elsewhere
        lock.pin(forecast)  # a pin that moves nothing keeps the repository it was pinned from
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        report = lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == real.commit
        assert not [e for e in report.events if e.status == "moved"]

    def test_a_pipeline_cannot_depend_on_itself_by_id(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.check import check_dependencies
        from chartbook.cli import main

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/forecast": {}})
        report = lock.pin(forecast)
        assert any("cannot depend on itself" in (e.detail or "") for e in report.events)
        problems = check_dependencies(load_manifest(forecast), forecast)
        assert problems and "cannot depend on itself" in problems[0].message
        _forecast(forecast, {})
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["add", "acme/forecast"])
        assert result.exit_code == 1 and "cannot depend on itself" in result.output

    def test_a_short_name_still_answers_to_the_full_id(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"rates": {"id": "acme/rates", "commit": first.commit[:7]}})
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.1]
        _forecast(forecast, {"rates": {"id": "acme/rates"}})
        lock.update(forecast, ["acme/rates"])
        assert _pinned(forecast)["location"]["commit"] == second.commit

    def test_a_kept_pin_keeps_how_it_was_pinned(self, tmp_path):
        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(work)
        snapshot.make(work / "rates")
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {}})
        lock.pin(forecast)
        entry = _pinned(forecast)
        assert entry["via"] == "path" and entry["location"]["kind"] == "path"
        assert any("pinned from" in p.message for p in lock.verify(forecast).problems)


class TestWhatTheSecondReviewFound:
    def test_a_repository_with_no_remote_is_kept_to_by_its_first_commit(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        assert second.repository == "" and second.first_commit and second.first_commit == first.first_commit
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["first_commit"] == second.first_commit
        copy = _another(work, "copy", 666.0)  # a copy of the project, newer, with no remote either
        assert copy.first_commit != second.first_commit
        report = lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit
        assert not [e for e in report.events if e.status == "moved"]
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.2]

    def test_snapshots_naming_no_repository_do_not_block_a_first_pin(self, tmp_path, monkeypatch):
        import dataclasses

        from chartbook.store import default_store

        work = tmp_path.resolve()
        older = _another(work, "before", 1.0, made_at="2026-01-01T00:00:00.000000Z")
        # As a snapshot made before snapshots recorded their repository
        snapshot._write(dataclasses.replace(older, repository="", first_commit=""), default_store())
        (older.path).unlink()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == real.commit
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_a_failed_update_does_not_record_the_repository_it_was_told(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _forecast(forecast, {"acme/rates": {"repository": "https://github.com/wrong/rates"}})
        lock.update(forecast)
        assert _pinned(forecast)["location"]["repository"] == "https://github.com/acme/rates"
        # The line is taken out again, and the owner makes a newer snapshot: update takes it
        _forecast(forecast, {"acme/rates": {}})
        _rates(work / "real" / "rates", 5.0)
        (work / "real" / "rates" / "more.txt").write_text("more\n")
        _commit(work / "real", "Newer")
        newer = snapshot.make(work / "real" / "rates").snapshot
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newer.commit

    def test_two_ways_of_writing_one_address_are_one_repository(self, tmp_path):
        from chartbook.identity import repository_key

        assert len({
            repository_key(address) for address in (
                "git@github.com:Acme/Rates.git", "https://github.com/acme/rates/", "http://GitHub.com:443/acme/rates",
                "ssh://git@github.com/acme/rates.git", "https://user:token@github.com/acme/rates",
            )
        }) == 1
        assert repository_key("https://gitlab.internal/Acme/Rates") != repository_key("https://gitlab.internal/acme/rates")
        assert repository_key("/a/path/on/disk") == "" and repository_key(None) == ""
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        # Its owner changes how the remote is written; a newer snapshot is the same repository
        _git(work / "real", "remote", "set-url", "origin", "git@github.com:Acme/Rates.git")
        from chartbook.identity import clear_git_remote_cache

        clear_git_remote_cache()
        (work / "real" / "rates" / "more.txt").write_text("more\n")
        _commit(work / "real", "Newer")
        newer = snapshot.make(work / "real" / "rates").snapshot
        assert newer.repository == "https://github.com/Acme/Rates"
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newer.commit

    def test_a_record_dated_ahead_does_not_stop_a_new_snapshot_of_its_commit(self, tmp_path):
        import dataclasses

        from chartbook.store import default_store

        work = tmp_path.resolve()
        taken = _another(work, "real", 4.0)
        snapshot._write(dataclasses.replace(taken, made_at="2099-01-01T00:00:00.000000Z"), default_store())
        report = snapshot.make(work / "real" / "rates")
        assert not report.made and report.snapshot.made_at == taken.made_at  # the real one, not the one dated ahead
        taken.path.unlink()
        report = snapshot.make(work / "real" / "rates")
        assert report.made and not report.snapshot.made_at.startswith("2099")

    def test_a_label_is_resolved_among_its_own_repositorys_snapshots(self, tmp_path):
        import dataclasses

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        held = real.assets["treasury"]["content_hash"]
        start = held.split(":", 1)[1][:12]
        newest = dataclasses.replace(real, labels={"treasury": {"best": start}})
        # Another repository's record of the ID, holding a version with the same start
        other = dataclasses.replace(
            real, repository="https://github.com/someone/rates", first_commit="f" * 40, made_at="2026-01-01T00:00:00.000000Z",
            assets={"treasury": {**real.assets["treasury"], "content_hash": held[:-1] + ("0" if held[-1] != "0" else "1")}},
        )
        from chartbook.store import default_store

        records, unresolved = snapshot.label_records(newest, "acme/rates", default_store(), found=[other, newest])
        assert unresolved == [] and list(records) == ["acme/rates:treasury@best"]


def _again(repository: Path, value: float, message: str, made_at=None):
    """Another commit of a repository `_another` made, snapshotted."""
    _rates(repository / "rates", value)
    (repository / "rates" / "notes.txt").write_text(f"{message}\n")
    _commit(repository, message)
    return snapshot.make(repository / "rates", made_at=made_at).snapshot


class TestWhatTheThirdReviewFound:
    def test_an_unreadable_record_does_not_stop_a_pin(self, elsewhere):
        from chartbook.store import default_store

        work, first, second = elsewhere
        newer = default_store().root / "snapshots" / ("e" * 40) / "_root"
        newer.mkdir(parents=True)
        (newer / "20260101T000000.000000Z.json").write_text(json.dumps({"schema": "chartbook/snapshot/v9"}))
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit

    def test_one_with_no_first_commit_does_not_take_a_pin_from_a_repository_with_no_remote(self, elsewhere):
        import dataclasses

        from chartbook.store import default_store

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        other = _another(work, "shallow", 666.0, remote="https://github.com/someone-else/rates")
        # As a shallow clone records it: an address, and no first commit
        other.path.unlink()
        snapshot._write(dataclasses.replace(other, first_commit=""), default_store())
        report = lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == second.commit
        assert _pinned(forecast)["location"]["first_commit"] == second.first_commit
        assert any(e.status == "passed_over" and "someone-else/rates" in e.detail for e in report.events)

    def test_a_rewritten_history_at_the_same_address_is_followed(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        # The owner starts the history again, as filter-repo would
        _git(work / "real", "checkout", "--quiet", "--orphan", "fresh")
        rewritten = _again(work / "real", 5.0, "Fresh start")
        assert rewritten.first_commit != _pinned(forecast)["location"]["first_commit"]
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == rewritten.commit
        assert _pinned(forecast)["location"]["first_commit"] == rewritten.first_commit

    def test_a_label_survives_a_new_address(self, tmp_path):
        from chartbook.identity import clear_git_remote_cache

        work = tmp_path.resolve()
        repository = work / "model"
        folder = repository / "model"
        (folder / "_output").mkdir(parents=True)
        manifest = {"project": {"id": "acme/model"}, "models": {"m": {"path": "./_output/m.json"}}}
        (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        (folder / "_output" / "m.json").write_text("v1")
        _git(repository, "init", "--quiet", "-b", "main")
        _git(repository, "remote", "add", "origin", "https://github.com/oldorg/model")
        (repository / ".gitignore").write_text("_output/\nchartbook.lock\n")
        _commit(repository)
        v1 = snapshot.make(folder, made_at="2026-01-01T00:00:00.000000Z").snapshot
        start = v1.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        _git(repository, "remote", "set-url", "origin", "https://github.com/neworg/model")
        clear_git_remote_cache()
        manifest["models"]["m"]["aliases"] = {"champion": start}
        (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        (folder / "_output" / "m.json").write_text("v2")
        _commit(repository, "Champion")
        snapshot.make(folder)
        forecast = _forecast(work / "forecast", {"acme/model": {}})
        report = lock.pin(forecast)
        assert [e.status for e in report.events if e.asset == "acme/model:model/m@champion"] == ["pinned"]

    def test_a_clone_with_a_path_remote_is_its_repository(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _git(work, "clone", "--quiet", str(work / "real"), str(work / "agent"))
        by_the_agent = _again(work / "agent", 6.0, "From an agent's clone")
        assert by_the_agent.repository == "" and by_the_agent.first_commit
        lock.update(forecast)
        entry = _pinned(forecast)
        assert entry["location"]["commit"] == by_the_agent.commit
        assert entry["location"]["repository"] == "https://github.com/acme/rates"  # what its repository is known as

    def test_the_main_checkout_makes_its_own_snapshot_of_a_commit_a_clone_snapshotted(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        _git(work, "clone", "--quiet", str(work / "real"), str(work / "agent"))
        by_the_agent = _again(work / "agent", 6.0, "Shared")
        _git(work / "real", "pull", "--quiet", str(work / "agent"), "main")
        _rates(work / "real" / "rates", 6.0)
        report = snapshot.make(work / "real" / "rates")
        assert report.made and report.snapshot.commit == by_the_agent.commit
        assert report.snapshot.repository == "https://github.com/acme/rates"

    def test_gc_keeps_within_each_repository(self, tmp_path):
        from chartbook.store import default_store

        work = tmp_path.resolve()
        older = _another(work, "real", 4.0, remote="https://github.com/acme/rates", made_at="2026-01-01T00:00:00.000000Z")
        newest = _again(work / "real", 4.5, "Second", made_at="2026-01-02T00:00:00.000000Z")
        copy = _another(work, "copy", 9.0)  # newer, another repository with the same ID
        for taken in (older, newest, copy):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        plan = snapshot.plan_removals(default_store(), set(), set(), keep_days=7)
        kept = {t.commit for t, why in plan.keep if why == "it is the newest of its pipeline"}
        assert kept == {newest.commit, copy.commit}

    def test_an_empty_repository_in_the_lockfile_is_none(self, tmp_path):
        """As a hand edit or a merge might leave it."""
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        document = json.loads(path.read_text())
        (pipeline,) = [record for record in document["records"] if record.get("kind") == "Pipeline"]
        location = pipeline["dependencies"][0]["location"]
        location["repository"] = ""
        del location["first_commit"]
        path.write_text(json.dumps(document))
        newer = _again(work / "real", 5.0, "Newer")
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newer.commit != real.commit

    def test_a_failed_first_pin_is_not_said_to_be_pinned_from_elsewhere(self, elsewhere):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {"repository": "https://github.com/acme/rates-new"}})
        lock.pin(forecast)
        messages = [p.message for p in lock.verify(forecast).problems]
        assert messages and not any("is pinned from" in m for m in messages)


def _record(taken, **changes):
    """A copy of a snapshot's record, written to the store as another clone or ChartBook would have."""
    import dataclasses

    from chartbook.store import default_store

    snapshot._write(dataclasses.replace(taken, **changes), default_store())


A = "https://github.com/acme/rates"


class TestWhatTheFourthReviewFound:
    def test_gc_keeps_what_joins_a_repository(self, tmp_path):
        from datetime import datetime, timezone

        from chartbook.store import default_store

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        _record(real, made_at="2026-09-01T00:00:00.000000Z")  # the main checkout: address and first commit
        _record(real, made_at="2026-10-01T00:00:00.000000Z", first_commit="")  # a shallow CI clone
        _record(real, made_at="2026-10-15T00:00:00.000000Z", repository="")  # an agent's clone, a path remote
        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        ci = (real.commit, "2026-10-01T00:00:00.000000Z")
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        plan = snapshot.plan_removals(store, {ci}, set(), keep_days=7, now=now)
        assert ("2026-09-01T00:00:00.000000Z", "it names its repository's address and first commit together, which joins its snapshots") in [
            (t.made_at, why) for t, why in plan.keep
        ]
        for taken, _ in plan.remove:
            taken.path.unlink()
        groups, unnamed = snapshot.repository_groups(snapshot.all_snapshots(store))
        assert len(groups) == 1 and unnamed == []

    def test_a_pin_never_loses_the_address_it_was_matched_by(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        # The main checkout's record goes; a shallow clone's and an agent's clone's are left
        real.path.unlink()
        _record(real, made_at="2026-10-01T00:00:00.000000Z", first_commit="")
        _record(real, made_at="2099-01-01T00:00:00.000000Z", repository="")  # dated ahead: never taken
        later = _again(work / "real", 5.0, "Later")
        later.path.unlink()
        _record(later, repository="")  # the agent's clone made it
        lock.update(forecast)
        assert _pinned(forecast)["location"] == {
            "kind": "store", "pipeline": "acme/rates", "commit": later.commit, "repository": A, "first_commit": real.first_commit,
        }
        newest = _again(work / "real", 6.0, "Newest")
        newest.path.unlink()
        _record(newest, first_commit="")  # CI's shallow clone made the newest
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == newest.commit

    def test_two_clones_taking_turns_at_one_commit_make_two_records(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        _git(work, "clone", "--quiet", str(work / "real"), str(work / "agent"))
        (work / "agent" / "rates" / "_data").mkdir()
        shutil.copy(work / "real" / "rates" / "_data" / "treasury.parquet", work / "agent" / "rates" / "_data")
        made = [snapshot.make(work / where / "rates").made for where in ("agent", "real") * 3]
        assert made == [True, True, False, False, False, False]

    def test_a_label_on_a_version_from_before_repositories_were_recorded(self, tmp_path):
        from chartbook.store import default_store

        work = tmp_path.resolve()
        repository = work / "model"
        folder = repository / "model"
        (folder / "_output").mkdir(parents=True)
        manifest = {"project": {"id": "acme/model"}, "models": {"m": {"path": "./_output/m.json"}}}
        (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        (folder / "_output" / "m.json").write_text("v1")
        _git(repository, "init", "--quiet", "-b", "main")
        _git(repository, "remote", "add", "origin", "https://github.com/acme/model")
        (repository / ".gitignore").write_text("_output/\nchartbook.lock\n")
        _commit(repository)
        v1 = snapshot.make(folder, made_at="2026-01-01T00:00:00.000000Z").snapshot
        v1.path.unlink()
        _record(v1, repository="", first_commit="")  # as an older ChartBook wrote it
        start = v1.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        manifest["models"]["m"]["aliases"] = {"champion": start}
        (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        (folder / "_output" / "m.json").write_text("v2")
        _commit(repository, "Champion")
        v2 = snapshot.make(folder).snapshot
        # Another repository claims the ID
        _record(v2, repository="https://github.com/someone/model", first_commit="f" * 40, made_at="2026-02-01T00:00:00.000000Z", labels={})
        forecast = _forecast(work / "forecast", {"acme/model": {"repository": "https://github.com/acme/model"}})
        report = lock.pin(forecast)
        assert [e.status for e in report.events if e.asset == "acme/model:model/m@champion"] == ["pinned"]
        # gc keeps it, with a newer snapshot that names no repository either
        (folder / "_output" / "m.json").write_text("v1b")
        _record(dataclasses_replace_assets(v1, "v1b"), repository="", first_commit="", made_at="2026-01-02T00:00:00.000000Z")
        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        plan = snapshot.plan_removals(store, set(), set(), keep_days=7)
        assert ("2026-01-01T00:00:00.000000Z", "a label points at a version in it") in [(t.made_at, w) for t, w in plan.keep]

    def test_a_newer_snapshot_from_elsewhere_is_said_when_the_choice_is_made(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote=A)
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _another(work, "copy", 9.0, remote="https://github.com/someone/rates")
        for _ in range(2):
            assert not [e for e in lock.pin(forecast).events if e.status == "passed_over"]
        (event,) = [e for e in lock.update(forecast).events if e.status == "passed_over"]
        assert "someone/rates" in event.detail
        assert lock._made_in(dataclasses_replace_identity()) == "a ChartBook that did not record its repository"


class TestWhatTheFifthReviewFound:
    def test_a_checkouts_own_snapshot_is_not_lost_to_a_clones_newer_one(self, tmp_path):
        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote=A)
        _git(work, "clone", "--quiet", str(work / "real"), str(work / "agent"))
        _rates(work / "agent" / "rates", 7.0)  # the agent's clone builds other bytes at the same commit
        snapshot.make(work / "agent" / "rates")
        report = snapshot.make(work / "real" / "rates")  # the main checkout declares its own again
        assert report.made
        newest, _ = snapshot.newest_for(work / "real" / "rates", __import__("chartbook.store", fromlist=["x"]).default_store())
        assert newest.made_at == report.snapshot.made_at

    def test_gc_keeps_the_newest_that_names_its_repository(self, tmp_path):
        from datetime import datetime, timezone

        from chartbook.store import default_store

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        _record(real, made_at="2026-09-01T00:00:00.000000Z", first_commit="")  # CI, a shallow clone
        _record(real, made_at="2026-09-20T00:00:00.000000Z", repository="", first_commit="")  # an older ChartBook
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _pinned(forecast)["location"]["repository"] == A
        later = _again(work / "real", 5.0, "Later")
        later.path.unlink()
        _record(later, made_at="2026-10-10T00:00:00.000000Z", repository="", first_commit="")
        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        plan = snapshot.plan_removals(store, set(), set(), keep_days=7, now=datetime(2026, 10, 16, tzinfo=timezone.utc))
        assert ("2026-09-01T00:00:00.000000Z", "it is the newest that names its repository") in [(t.made_at, w) for t, w in plan.keep]
        for taken, _ in plan.remove:
            taken.path.unlink()
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == later.commit

    def test_a_pin_that_recorded_its_repository_takes_unnamed_snapshots_when_none_is_named(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        real.path.unlink()
        later = _again(work / "real", 5.0, "Later")
        later.path.unlink()
        _record(later, repository="", first_commit="")  # only an older ChartBook's snapshot is left
        lock.update(forecast)
        assert _pinned(forecast)["location"]["commit"] == later.commit

    def test_old_addresses_keep_nothing_when_nothing_would_split(self, tmp_path):
        from chartbook.store import default_store

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        for day, address in enumerate(("acme/rates", "acme/rates-old2", "forker/rates", "acme/rates-now", "acme/rates-now"), 1):
            _record(real, made_at=f"2026-09-0{day}T00:00:00.000000Z", repository=f"https://github.com/{address}")
        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        plan = snapshot.plan_removals(store, set(), set(), keep_days=0, aggressive=True)
        assert [(t.made_at, w) for t, w in plan.keep] == [("2026-09-05T00:00:00.000000Z", "it is the newest of its pipeline")]

    def test_a_joining_snapshot_dated_a_little_ahead_is_kept(self, tmp_path):
        from datetime import datetime, timedelta, timezone

        from chartbook.store import default_store

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        ahead = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        _record(real, made_at=ahead)  # the main checkout, its clock 30 minutes ahead
        _record(real, made_at="2026-10-01T00:00:00.000000Z", first_commit="")  # CI, pinned
        _record(real, made_at="2026-10-15T00:00:00.000000Z", repository="")  # an agent's clone
        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        plan = snapshot.plan_removals(
            store, {(real.commit, "2026-10-01T00:00:00.000000Z")}, set(), keep_days=0, aggressive=True, now=now
        )
        assert ahead in [t.made_at for t, _ in plan.keep]


class TestWhatTheSixthReviewFound:
    def _gone(self, work):
        from chartbook.store import default_store

        store = default_store()
        for taken in snapshot.all_snapshots(store):
            (taken.path.parent / "origins").write_text(str(work / "gone") + "\n")
        return store

    def test_a_named_pin_on_a_clones_snapshot_keeps_what_names_its_address(self, tmp_path):
        from datetime import datetime, timezone

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        _record(real, made_at="2026-09-01T00:00:00.000000Z")  # the main checkout
        agent = "2026-10-01T00:00:00.000000Z"
        _record(real, made_at=agent, repository="")  # an agent's clone, a path remote
        forecast = _forecast(work / "forecast", {"acme/rates": {"repository": A}})
        lock.pin(forecast)
        assert _pinned(forecast)["snapshot"] == agent
        store = self._gone(work)
        plan = snapshot.plan_removals(store, {(real.commit, agent)}, set(), keep_days=7, now=datetime(2026, 10, 16, tzinfo=timezone.utc))
        assert ("2026-09-01T00:00:00.000000Z", "it names the address of a kept snapshot's first commit") in [(t.made_at, w) for t, w in plan.keep]
        for taken, _ in plan.remove:
            taken.path.unlink()
        assert not lock.update(forecast).problems

    def test_where_only_unnamed_are_kept_every_address_and_first_commit_stays(self, tmp_path):
        from datetime import datetime, timezone

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        _record(real, made_at="2026-09-01T00:00:00.000000Z")  # the main checkout
        _record(real, made_at="2026-09-10T00:00:00.000000Z", repository="")  # an agent's clone
        _record(real, made_at="2026-10-01T00:00:00.000000Z", repository="", first_commit="")  # an older ChartBook
        store = self._gone(work)
        plan = snapshot.plan_removals(store, set(), set(), keep_days=7, now=datetime(2026, 10, 16, tzinfo=timezone.utc))
        assert ("2026-09-01T00:00:00.000000Z", "it is the newest that names its repository") in [(t.made_at, w) for t, w in plan.keep]
        for taken, _ in plan.remove:
            taken.path.unlink()
        forecast = _forecast(work / "forecast", {"acme/rates": {"repository": A}})
        assert not lock.pin(forecast).problems

    def test_keep_lineage_covers_what_keeps_a_repository_whole(self, tmp_path):
        from datetime import datetime, timezone

        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        real.path.unlink()
        fred = ("f" * 40, "2026-08-01T00:00:00.000000Z")
        _record(real, pipeline="acme/fred", commit=fred[0], made_at=fred[1])
        made_from = [{"id": "acme/fred", "via": "store", "location": {"kind": "store", "pipeline": "acme/fred", "commit": fred[0]}, "snapshot": fred[1]}]
        _record(real, made_at="2026-09-01T00:00:00.000000Z", inputs=made_from)  # the main checkout
        _record(real, made_at="2026-10-01T00:00:00.000000Z", first_commit="")  # CI, pinned
        _record(real, made_at="2026-10-15T00:00:00.000000Z", repository="")  # an agent's clone
        _record(real, pipeline="acme/fred", commit=fred[0], made_at="2026-10-14T00:00:00.000000Z")  # fred's newest
        store = self._gone(work)
        plan = snapshot.plan_removals(
            store, {(real.commit, "2026-10-01T00:00:00.000000Z")}, set(), keep_days=7, keep_lineage=True,
            now=datetime(2026, 10, 16, tzinfo=timezone.utc),
        )
        assert fred in [(t.commit, t.made_at) for t, _ in plan.keep]

    def test_a_pin_that_takes_an_unnamed_snapshot_says_so(self, tmp_path):
        work = tmp_path.resolve()
        real = _another(work, "real", 4.0, remote=A)
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        real.path.unlink()
        later = _again(work / "real", 5.0, "Later")
        later.path.unlink()
        _record(later, repository="", first_commit="")
        (event,) = [e for e in lock.update(forecast).events if e.status == "unchecked"]
        assert "names no repository" in event.detail


def dataclasses_replace_assets(taken, marker: str):
    """A copy of a snapshot holding another version of its model, as if built again."""
    import dataclasses

    record = dict(taken.assets["model/m"])
    record["content_hash"] = "sha256:" + ("a" * 63) + marker[-1:].encode().hex()[:1]
    return dataclasses.replace(taken, assets={**taken.assets, "model/m": record})


def dataclasses_replace_identity():
    from chartbook.snapshot import Snapshot

    return Snapshot("acme/rates", "0" * 40, "", "2026-01-01T00:00:00.000000Z")


class TestTheManifestEdit:
    def test_a_header_inside_a_string_is_not_written_into(self):
        from chartbook.manifest import with_dependency

        text = '[project]\ndescription = """\n[dependencies]\n"""\n\n[dependencies]\n"a/b" = {}\n'
        changed = with_dependency(text, "acme/rates", {})
        assert changed.count('"acme/rates" = {}') == 1
        assert changed.index('"acme/rates" = {}') > changed.index('"""\n\n[dependencies]')

    def test_line_endings_are_kept(self, elsewhere, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main
        from chartbook.manifest import with_dependency

        crlf = '[project]\r\nid = "acme/forecast"\r\n\r\n[dependencies]\r\n'
        assert with_dependency(crlf, "acme/rates", {}) == crlf + '"acme/rates" = {}\r\n'
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        raw = (forecast / "chartbook.toml").read_bytes().replace(b"\n", b"\r\n")
        (forecast / "chartbook.toml").write_bytes(raw)
        monkeypatch.chdir(forecast)
        assert CliRunner().invoke(main, ["add", "acme/rates"]).exit_code == 0
        written = (forecast / "chartbook.toml").read_bytes()
        assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")

    def test_a_manifest_with_nan_in_it_is_still_written_into(self):
        from chartbook.manifest import with_dependency

        text = '[project]\nid = "acme/forecast"\n\n[tool.x]\nmissing = nan\n\n[dependencies]\n'
        assert '"acme/rates" = {}' in with_dependency(text, "acme/rates", {})

    def test_other_forms_say_what_to_add(self):
        from chartbook.manifest import with_dependency

        for text in ('["dependencies"]\n"a/b" = {}\n', 'dependencies."a/b" = {}\n', 'dependencies = { "a/b" = {} }\n'):
            with pytest.raises(ValueError, match='Add the entry there yourself: "acme/rates" = {}'):
                with_dependency(text, "acme/rates", {})
        assert '"acme/rates" = {}' in with_dependency('[dependencies."a/b"]\npath = "../b"\n', "acme/rates", {})


class TestTheRepositoryWarning:
    def test_a_short_key_is_kept_in_the_hint(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "theirs" / "rates", 4.0)
        _git(work / "theirs", "init", "--quiet", "-b", "main")
        _commit(work / "theirs")
        forecast = _forecast(work / "mine" / "forecast", {"rates": {"path": "../../theirs/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match=r'"rates" = \{ id = "acme/rates" \}'):
            check_dependencies(load_manifest(forecast), forecast)

    def test_a_folder_in_no_repository_is_said_too(self, tmp_path):
        from chartbook.check import check_dependencies

        work = tmp_path.resolve()
        _rates(work / "loose" / "rates", 4.0)  # in no git repository
        forecast = _forecast(work / "mine" / "forecast", {"acme/rates": {"path": "../../loose/rates"}})
        _git(work / "mine", "init", "--quiet", "-b", "main")
        _commit(work / "mine")
        with pytest.warns(UserWarning, match="is in no git repository"):
            check_dependencies(load_manifest(forecast), forecast)
