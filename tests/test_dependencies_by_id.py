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
        assert entry["via"] == "store" and entry["location"] == {"kind": "store", "pipeline": "acme/rates", "commit": second.commit}
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
        with pytest.raises(ValueError, match="written inline"):
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
