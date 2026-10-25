"""Dependencies between pipelines form a directed acyclic graph.

A pipeline that depends, through what it depends on, on itself has no order to be built in, and
its snapshot would carry itself in its lineage. ``chartbook run``, ``chartbook build`` and
``chartbook snapshot`` refuse one, and ``chartbook check`` reports it
(:func:`chartbook.lineage.cycle`).
"""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import lineage, lock, run, snapshot
from chartbook.check import run_checks
from chartbook.cli import main
from chartbook.manifest import load_manifest
from chartbook.store import default_store
from tests.test_model_versions import _commit, _git

posix = pytest.mark.skipif(os.name == "nt", reason="the build scripts here are POSIX shell")

#: Appends the pipeline's folder name to one shared file, so a test can see what was built
LOG = 'echo "$(basename "$PWD")" >> ../order.log'


def _pipeline(folder: Path, pipeline_id: str, name: str, dependencies=None, build=LOG) -> Path:
    (folder / "_data").mkdir(parents=True, exist_ok=True)
    manifest = {
        "project": {"id": pipeline_id},
        "dataframes": {name: {"path": f"./_data/{name}.parquet", "docs": "A file."}},
    }
    if build is not None:
        manifest["scripts"] = {"build": build}
    if dependencies:
        manifest["dependencies"] = dependencies
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    pl.DataFrame({"d": ["2024-01-01"], name: [1.0]}).write_parquet(folder / "_data" / f"{name}.parquet")
    return folder


def _declare(folder: Path, dependencies: dict) -> None:
    """Set a pipeline's ``[dependencies]``."""
    manifest = tomli.loads((folder / "chartbook.toml").read_text())
    manifest["dependencies"] = dependencies
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))


def _built(work: Path) -> list:
    log = work / "order.log"
    return log.read_text().split() if log.exists() else []


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def chain(work):
    """``fred`` <- ``rates`` <- ``forecast``, by path, in one repository: fred and rates snapshotted, each pinned by the next."""
    fred = _pipeline(work / "fred", "acme/fred", "series")
    rates = _pipeline(work / "rates", "acme/rates", "treasury", {"fred": {"path": "../fred"}})
    forecast = _pipeline(work / "forecast", "acme/forecast", "outlook", {"rates": {"path": "../rates"}})
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n*.log\n")
    _commit(work)
    snapshot.make(fred)
    lock.pin(rates)
    snapshot.make(rates)
    lock.pin(forecast)
    return fred, rates, forecast


def _snapshot_of(pipeline: str):
    found, _ = snapshot.readable_snapshots(default_store())
    return max((t for t in found if t.pipeline == pipeline), key=lambda t: t.made_at)


class TestTheWalk:
    def test_a_chain_has_no_cycle(self, chain):
        fred, rates, forecast = chain
        assert lineage.cycle(forecast) == [] and lineage.cycle(rates) == [] and lineage.cycle(fred) == []

    def test_a_diamond_is_not_a_cycle(self, work):
        """``top`` depends on ``left`` and ``right``, which both depend on ``base``."""
        _pipeline(work / "base", "acme/base", "b")
        _pipeline(work / "left", "acme/left", "l", {"base": {"path": "../base"}})
        _pipeline(work / "right", "acme/right", "r", {"base": {"path": "../base"}})
        top = _pipeline(
            work / "top", "acme/top", "t", {"left": {"path": "../left"}, "right": {"path": "../right"}}
        )
        assert lineage.cycle(top) == []

    def test_two_folders_that_declare_each_other(self, chain):
        """fred comes to depend on forecast: found in the folders, before anything is pinned or snapshotted."""
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        found = lineage.cycle(forecast)
        assert [(edge.pipeline, edge.dependency, edge.key) for edge in found] == [
            ("acme/forecast", "acme/rates", "rates"),
            ("acme/rates", "acme/fred", "fred"),
            ("acme/fred", "acme/forecast", "forecast"),
        ]
        assert found[0].where == f"declared in {forecast / 'chartbook.toml'}"
        assert found[2].where == f"declared in {fred / 'chartbook.toml'}"
        # The same cycle, from wherever it is looked at
        assert [edge.pipeline for edge in lineage.cycle(fred)] == ["acme/fred", "acme/forecast", "acme/rates"]
        assert lineage.cycle_lead(found) == "these pipelines depend on each other"

    def test_a_pipeline_that_depends_on_itself(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"me": {"path": "."}})
        (edge,) = lineage.cycle(fred)
        assert (edge.pipeline, edge.dependency, edge.key) == ("acme/fred", "acme/fred", "me")
        assert lineage.cycle_lead([edge]) == "acme/fred depends on itself"

    def test_through_the_store(self, chain):
        """fred names forecast by its ID: no folder of it is looked at, so the cycle is in the snapshots."""
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        found = lineage.cycle(fred)
        assert [(edge.pipeline, edge.dependency, edge.key) for edge in found] == [
            ("acme/fred", "acme/forecast", "acme/forecast"),
            ("acme/forecast", "acme/rates", "rates"),
            ("acme/rates", "acme/fred", "fred"),
        ]
        assert found[0].where == f"declared in {fred / 'chartbook.toml'}"
        assert found[1].where == (
            f"recorded by the snapshot of acme/forecast at {_snapshot_of('acme/forecast').commit[:7]}, "
            f"made {_snapshot_of('acme/forecast').made_at[:10]}"
        )
        assert found[2].where.startswith("recorded by the snapshot of acme/rates at ")
        # A walk that may not read the store does not see it
        assert lineage.cycle(fred, follow_pins=False) == []

    def test_what_is_said_of_the_cycle(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        said = lineage.explain_cycle(lineage.cycle(forecast))
        assert said.splitlines()[:3] == [
            f"  acme/forecast depends on acme/rates (as 'rates'): declared in {forecast / 'chartbook.toml'}",
            f"  acme/rates depends on acme/fred (as 'fred'): declared in {rates / 'chartbook.toml'}",
            f"  acme/fred depends on acme/forecast (as 'forecast'): declared in {fred / 'chartbook.toml'}",
        ]
        assert said.splitlines()[3].startswith("Dependencies between pipelines must form a graph with no cycles.")

    def test_a_record_not_as_written_is_passed_over(self, chain):
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        taken = _snapshot_of("acme/forecast")
        os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
        document = json.loads(taken.path.read_text())
        document["inputs"] = [5, {"id": 7}, {"id": "rates", "location": "nowhere", "snapshot": 3}, "x"]
        taken.path.write_text(json.dumps(document))
        assert lineage.cycle(fred) == []

    def test_a_dependency_with_nothing_here_is_passed_over(self, chain):
        """A folder not on this machine and not pinned, and an ID with no snapshot: nothing is known of them."""
        fred, rates, forecast = chain
        _declare(fred, {"elsewhere": {"path": "../not_here"}, "acme/nobody": {}})
        assert lineage.cycle(forecast) == []


@posix
class TestTheCommands:
    def test_run_stops_before_the_build(self, chain, work):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        report = run.run(forecast, echo=lambda line: None)
        assert report.failed.id == "acme/forecast" and report.exit_code == 1
        assert report.reason.startswith(
            "these pipelines depend on each other, so there is no order to build them in, and it was not built:\n"
        )
        assert f"acme/fred depends on acme/forecast (as 'forecast'): declared in {fred / 'chartbook.toml'}" in report.reason
        assert _built(work) == []

    def test_run_at_the_terminal(self, chain, work, monkeypatch):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1, result.output
        assert "Error: acme/forecast: these pipelines depend on each other, so there is no order to build them in" in result.output
        assert "Take one of these out of its [dependencies]" in result.output
        assert result.output.rstrip().endswith("Nothing after it was run.")
        assert _built(work) == []

    def test_a_pipeline_outside_the_cycle_still_builds(self, chain, work):
        """rates and fred come to depend on each other; forecast, above them, is refused, but fred's own build is not about forecast."""
        fred, rates, forecast = chain
        _declare(fred, {"rates": {"path": "../rates"}})
        assert run.run(forecast, echo=lambda line: None).failed.id == "acme/forecast"
        assert run.run(fred, echo=lambda line: None).failed.id == "acme/fred"
        assert _built(work) == []

    def test_snapshot_refuses(self, chain, work):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        _commit(work)
        with pytest.raises(snapshot.SnapshotError) as raised:
            snapshot.make(forecast)
        assert str(raised.value).startswith(
            "acme/forecast cannot have a snapshot: these pipelines depend on each other, so its lineage "
            "would lead back to itself.\n  acme/forecast depends on acme/rates"
        )

    def test_build_with_no_build_script_stops_before_rendering(self, work, monkeypatch):
        a = _pipeline(work / "a", "acme/a", "x", {"b": {"path": "../b"}}, build=None)
        _pipeline(work / "b", "acme/b", "y", {"a": {"path": "../a"}}, build=None)
        monkeypatch.chdir(a)
        result = CliRunner().invoke(main, ["build", "-f"])
        assert result.exit_code == 1, result.output
        assert "No `build` script here, so only the site is rendered." in result.output
        assert "Error: acme/a: these pipelines depend on each other, so there is no order to build them in." in result.output
        assert f"acme/b depends on acme/a (as 'a'): declared in {work / 'b' / 'chartbook.toml'}" in result.output
        assert result.output.rstrip().endswith("Nothing was rendered.")
        assert not (a / "_docs").exists()

    def test_check_reports_it(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        (problem,) = [p for p in run_checks(load_manifest(forecast), forecast) if "depend on each other" in p.message]
        assert (problem.file, problem.table, problem.field) == (forecast / "chartbook.toml", "dependencies.rates", "path")
        assert problem.message == (
            "acme/forecast -> acme/rates -> acme/fred -> acme/forecast: these pipelines depend on each "
            "other, so there is no order to build them in. Take one of these out of its [dependencies]"
        )

    def test_check_says_a_self_dependency_once(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"me": {"path": "."}})
        problems = [p for p in run_checks(load_manifest(fred), fred) if p.table.startswith("dependencies")]
        assert len(problems) == 1 and "cannot depend on itself" in problems[0].message

    def test_check_sees_a_cycle_in_a_folder_store(self, chain):
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        (problem,) = [p for p in run_checks(load_manifest(fred), fred) if "depend on each other" in p.message]
        assert problem.table == 'dependencies."acme/forecast"' and problem.field == "id"
        assert problem.message.startswith("acme/fred -> acme/forecast -> acme/rates -> acme/fred: ")
