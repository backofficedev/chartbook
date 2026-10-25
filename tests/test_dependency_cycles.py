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


def _repository(work: Path) -> None:
    """Make *work* a repository with everything committed; built data, lockfiles and logs ignored."""
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n*.log\n")
    _commit(work)


def _built(work: Path) -> list:
    log = work / "order.log"
    return log.read_text().split() if log.exists() else []


def _snapshot_of(pipeline: str):
    found, _ = snapshot.readable_snapshots(default_store())
    return max((t for t in found if t.pipeline == pipeline), key=lambda t: t.made_at)


def _rewrite(taken, change) -> None:
    """Change a snapshot's record on disk, as anyone who can write to a store could."""
    os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
    document = json.loads(taken.path.read_text())
    change(document)
    taken.path.write_text(json.dumps(document))


def _around(found) -> list:
    return [(edge.pipeline, edge.dependency) for edge in found.edges]


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def chain(work):
    """``fred`` <- ``rates`` <- ``forecast``, by path, in one repository: fred and rates snapshotted, each pinned by the next."""
    fred = _pipeline(work / "fred", "acme/fred", "series")
    rates = _pipeline(work / "rates", "acme/rates", "treasury", {"fred": {"path": "../fred"}})
    forecast = _pipeline(work / "forecast", "acme/forecast", "outlook", {"rates": {"path": "../rates"}})
    _repository(work)
    snapshot.make(fred)
    lock.pin(rates)
    snapshot.make(rates)
    lock.pin(forecast)
    return fred, rates, forecast


@pytest.fixture
def diamond(work):
    """``r`` depends on ``a`` and ``b`` by path; ``a`` and ``b`` both pin ``c``'s one snapshot, whose record says ``c`` was pinned to an older ``b``.

    So b -> c -> b is a cycle among what r depends on, and c is met twice
    on the walk from r: first from a, where nothing above it is reachable
    from it, then from b, where b is.
    """
    b = _pipeline(work / "b", "acme/b", "bills")
    c = _pipeline(work / "c", "acme/c", "curve", {"acme/b": {}})
    _pipeline(work / "a", "acme/a", "alpha", {"acme/c": {}})
    r = _pipeline(work / "r", "acme/r", "report", {"a": {"path": "../a"}, "b": {"path": "../b"}})
    _repository(work)
    snapshot.make(b)
    lock.pin(c)
    snapshot.make(c)
    _declare(b, {"acme/c": {}})
    lock.pin(b)
    lock.pin(work / "a")
    snapshot.make(work / "a")  # so that r has something of a to pin
    return r


class TestTheWalk:
    def test_a_chain_has_no_cycle(self, chain):
        fred, rates, forecast = chain
        assert lineage.cycle(forecast) is None and lineage.cycle(rates) is None and lineage.cycle(fred) is None

    def test_a_diamond_is_not_a_cycle(self, work):
        """``top`` depends on ``left`` and ``right``, which both depend on ``base``."""
        _pipeline(work / "base", "acme/base", "b")
        _pipeline(work / "left", "acme/left", "l", {"base": {"path": "../base"}})
        _pipeline(work / "right", "acme/right", "r", {"base": {"path": "../base"}})
        top = _pipeline(
            work / "top", "acme/top", "t", {"left": {"path": "../left"}, "right": {"path": "../right"}}
        )
        assert lineage.cycle(top) is None

    def test_two_folders_that_declare_each_other(self, chain):
        """fred comes to depend on forecast: found in the folders, before anything is pinned or snapshotted."""
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        found = lineage.cycle(forecast)
        assert [(edge.pipeline, edge.dependency, edge.key) for edge in found.edges] == [
            ("acme/forecast", "acme/rates", "rates"),
            ("acme/rates", "acme/fred", "fred"),
            ("acme/fred", "acme/forecast", "forecast"),
        ]
        assert found.way_in == []
        assert found.edges[0].where == f"declared in {forecast / 'chartbook.toml'}"
        assert found.edges[2].where == f"declared in {fred / 'chartbook.toml'}"
        # The same cycle, from wherever it is looked at
        assert [edge.pipeline for edge in lineage.cycle(fred).edges] == ["acme/fred", "acme/forecast", "acme/rates"]
        assert lineage.cycle_lead(found) == "these pipelines depend on each other"

    def test_a_pipeline_that_depends_on_itself(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"me": {"path": "."}})
        found = lineage.cycle(fred)
        (edge,) = found.edges
        assert (edge.pipeline, edge.dependency, edge.key) == ("acme/fred", "acme/fred", "me")
        assert lineage.cycle_lead(found) == "it depends on itself"

    def test_a_cycle_among_what_it_depends_on(self, chain):
        """fred depends on itself; forecast, above it, is told the way to it."""
        fred, rates, forecast = chain
        _declare(fred, {"me": {"path": "."}})
        found = lineage.cycle(forecast)
        assert _around(found) == [("acme/fred", "acme/fred")]
        assert [(edge.pipeline, edge.dependency) for edge in found.way_in] == [
            ("acme/forecast", "acme/rates"),
            ("acme/rates", "acme/fred"),
        ]
        assert lineage.cycle_lead(found) == "a pipeline it depends on depends on itself"

    def test_through_the_store(self, chain):
        """fred names forecast by its ID: no folder of it is looked at, so the cycle is in the snapshots."""
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        found = lineage.cycle(fred)
        assert [(edge.pipeline, edge.dependency, edge.key) for edge in found.edges] == [
            ("acme/fred", "acme/forecast", "acme/forecast"),
            ("acme/forecast", "acme/rates", "rates"),
            ("acme/rates", "acme/fred", "fred"),
        ]
        assert found.edges[0].where == f"declared in {fred / 'chartbook.toml'}"
        assert found.edges[1].where == (
            f"recorded by the snapshot of acme/forecast at {_snapshot_of('acme/forecast').commit[:7]}, "
            f"made {_snapshot_of('acme/forecast').made_at[:10]}"
        )
        assert found.edges[2].where.startswith("recorded by the snapshot of acme/rates at ")
        # A walk that may not read the store does not see it
        assert lineage.cycle(fred, follow_pins=False) is None

    def test_a_snapshot_met_twice_is_walked_again_when_something_above_is_reachable_from_it(self, diamond):
        found = lineage.cycle(diamond)
        assert _around(found) == [("acme/b", "acme/c"), ("acme/c", "acme/b")]
        assert [(edge.pipeline, edge.dependency) for edge in found.way_in] == [("acme/r", "acme/b")]
        assert found.edges[1].where.startswith("recorded by the snapshot of acme/c at ")
        assert lineage.cycle_lead(found) == "pipelines it depends on depend on each other"

    def test_a_dependency_under_a_shorter_key(self, chain):
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"fc": {"id": "acme/forecast"}})
        lock.pin(fred)
        found = lineage.cycle(fred)
        assert (found.edges[0].dependency, found.edges[0].key) == ("acme/forecast", "fc")
        assert lineage.explain_cycle(found).splitlines()[0] == (
            f"  acme/fred depends on acme/forecast (as 'fc'): declared in {fred / 'chartbook.toml'}"
        )

    def test_an_input_pinned_from_a_clone_is_known_by_its_key(self, chain):
        """A snapshot's input of kind git names no snapshot; the key it was declared under is a pipeline ID."""
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        _rewrite(
            _snapshot_of("acme/forecast"),
            lambda d: d.update(inputs=[{"id": "acme/fred", "location": {"kind": "git", "url": "https://example.org/acme/fred"}}]),
        )
        assert _around(lineage.cycle(fred)) == [("acme/fred", "acme/forecast"), ("acme/forecast", "acme/fred")]

    def test_the_pipeline_walked_from_may_be_named(self, chain):
        """As `chartbook run` names a git dependency's working copy by its key."""
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        found = lineage.cycle(forecast, pipeline="copy-of-forecast")
        assert [edge.pipeline for edge in found.way_in] == ["copy-of-forecast"]
        assert [edge.pipeline for edge in found.edges] == ["acme/rates", "acme/fred", "acme/forecast"]

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


class TestWhatCannotBeRead:
    def test_a_record_not_as_written_is_passed_over(self, chain):
        fred, rates, forecast = chain
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        _rewrite(
            _snapshot_of("acme/forecast"),
            lambda d: d.update(inputs=[5, {"id": 7}, {"id": "rates", "location": "nowhere", "snapshot": 3}, "x"]),
        )
        assert lineage.cycle(fred) is None

    def test_a_dependency_with_nothing_here_is_passed_over(self, chain):
        """A folder not on this machine and not pinned, and an ID with no snapshot: nothing is known of them."""
        fred, rates, forecast = chain
        _declare(fred, {"elsewhere": {"path": "../not_here"}, "acme/nobody": {}})
        assert lineage.cycle(forecast) is None

    def test_a_dependency_whose_manifest_is_broken_does_not_hide_the_others(self, chain):
        """forecast comes to depend on a folder with a broken manifest too: the cycle through rates is still found."""
        fred, rates, forecast = chain
        broken = forecast.parent / "broken"
        broken.mkdir()
        (broken / "chartbook.toml").write_text("not = [toml\n")
        _declare(forecast, {"broken": {"path": "../broken"}, "rates": {"path": "../rates"}})
        _declare(fred, {"forecast": {"path": "../forecast"}})
        assert [edge.dependency for edge in lineage.cycle(forecast).edges] == ["acme/rates", "acme/fred", "acme/forecast"]

    def test_a_dependency_folder_that_is_a_catalog_is_passed_over(self, chain):
        fred, rates, forecast = chain
        catalog = forecast.parent / "everything"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"fred": {"path": "../fred"}}})
        )
        _declare(fred, {"all": {"path": "../everything"}})
        assert lineage.cycle(forecast) is None


def _lockfile(folder: Path):
    """The bytes of a pipeline's lockfile, or None if it has none."""
    path = folder / "chartbook.lock"
    return path.read_bytes() if path.exists() else None


@pytest.fixture
def would_be(chain):
    """forecast is snapshotted, and fred comes to name it by its ID with nothing of it pinned yet.

    No folder and no pin says anything of a cycle yet; pinning forecast's
    newest snapshot, which was made from rates, which was made from fred,
    would make one.
    """
    fred, rates, forecast = chain
    snapshot.make(forecast)
    _declare(fred, {"acme/forecast": {}})
    return chain


@posix
class TestTheCommands:
    def test_run_stops_before_anything_is_pinned_or_built(self, chain, work):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        before = _lockfile(forecast)
        with pytest.raises(run.RunError) as raised:
            run.run(forecast, echo=lambda line: None)
        said = str(raised.value)
        assert said.startswith(
            "acme/forecast: these pipelines depend on each other, so there is no order to build in.\n"
            f"  acme/forecast depends on acme/rates (as 'rates'): declared in {forecast / 'chartbook.toml'}\n"
        )
        assert f"acme/fred depends on acme/forecast (as 'forecast'): declared in {fred / 'chartbook.toml'}" in said
        assert said.endswith("\nNothing was built.")
        assert _lockfile(forecast) == before and _built(work) == []

    def test_run_at_the_terminal(self, chain, work, monkeypatch):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1, result.output
        assert result.output.startswith(
            "Error: acme/forecast: these pipelines depend on each other, so there is no order to build in."
        )
        assert "Take one of these out of its [dependencies]" in result.output
        assert result.output.rstrip().endswith("Nothing was built.")
        assert "pinning" not in result.output and _built(work) == []

    def test_a_pin_that_would_make_a_cycle_is_not_written(self, would_be, work):
        fred, rates, forecast = would_be
        assert lineage.cycle(fred) is None  # nothing pinned says so yet
        pinned = []
        report = run.run(fred, echo=lambda line: None, on_pin=lambda step, pins: pinned.append(pins))
        assert report.failed.id == "acme/fred" and report.exit_code == 1
        assert report.reason.startswith(
            "pinning what it depends on would make a cycle: these pipelines depend on each other, so there "
            "is no order to build in.\n"
            f"  acme/fred depends on acme/forecast: declared in {fred / 'chartbook.toml'}\n"
            "  acme/forecast depends on acme/rates (as 'rates'): recorded by the snapshot of acme/forecast at "
        )
        assert report.reason.endswith("\nNothing was pinned, and it was not built")
        assert pinned == [] and _built(work) == []
        assert _lockfile(fred) is None
        assert default_store().root_of(fred / "chartbook.lock", machine=lock._noted_as()) is None

    def test_a_pin_that_would_make_a_cycle_at_the_terminal(self, would_be, work, monkeypatch):
        fred, rates, forecast = would_be
        monkeypatch.chdir(fred)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1, result.output
        assert result.output.startswith("Error: acme/fred: pinning what it depends on would make a cycle: ")
        assert result.output.rstrip().endswith("Nothing was pinned, and it was not built. Nothing after it was run.")
        assert "Wrote chartbook.lock" not in result.output and _lockfile(fred) is None

    def test_a_catalog_builds_nothing_when_one_of_its_pipelines_is_in_a_cycle(self, would_be, work):
        """apart comes first and has nothing to do with the cycle: it is not built either."""
        fred, rates, forecast = would_be
        lock.pin(fred)  # a pin made before, by `chartbook pin`, which does not refuse it
        _pipeline(work / "apart", "acme/apart", "a")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"apart": {"path": "apart"}, "fred": {"path": "fred"}}})
        )
        with pytest.raises(run.RunError, match=r"^acme/fred: these pipelines depend on each other"):
            run.run(work, echo=lambda line: None)
        assert _built(work) == []

    def test_run_says_when_the_cycle_is_among_what_it_depends_on(self, diamond, work):
        with pytest.raises(run.RunError) as raised:
            run.run(diamond, echo=lambda line: None)
        assert str(raised.value).startswith(
            "acme/r: pipelines it depends on depend on each other, so there is no order to build in.\n"
            f"  acme/r depends on acme/b (as 'b'): declared in {diamond / 'chartbook.toml'}\n"
            "  acme/b depends on acme/c: declared in "
        )
        assert _lockfile(diamond) is None and _built(work) == []

    def test_a_pipeline_in_the_cycle_and_one_above_it_are_both_refused(self, chain, work):
        """rates and fred come to depend on each other; forecast, above them, is refused, and so is fred."""
        fred, rates, forecast = chain
        _declare(fred, {"rates": {"path": "../rates"}})
        with pytest.raises(run.RunError, match="^acme/forecast: pipelines it depends on depend on each other"):
            run.run(forecast, echo=lambda line: None)
        with pytest.raises(run.RunError, match="^acme/fred: these pipelines depend on each other"):
            run.run(fred, echo=lambda line: None)
        assert _built(work) == []

    def test_run_frozen_refuses_a_cycle_through_the_store(self, would_be, work):
        fred, rates, forecast = would_be
        lock.pin(fred)
        before = _lockfile(fred)
        with pytest.raises(run.RunError, match="^acme/fred: these pipelines depend on each other"):
            run.run(fred, frozen=True, echo=lambda line: None)
        assert _lockfile(fred) == before and _built(work) == []

    def test_build_stops_before_anything_is_pinned_or_built(self, chain, work, monkeypatch):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        before = _lockfile(forecast)
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["build", "-f"])
        assert result.exit_code == 1, result.output
        assert "Error: acme/forecast: these pipelines depend on each other" in result.output
        assert result.output.rstrip().endswith("Nothing was built.")
        assert _lockfile(forecast) == before and _built(work) == []
        assert not (forecast / "_docs").exists()

    def test_snapshot_refuses(self, chain, work):
        fred, rates, forecast = chain
        _declare(fred, {"forecast": {"path": "../forecast"}})
        _commit(work)
        with pytest.raises(snapshot.SnapshotError) as raised:
            snapshot.make(forecast)
        assert str(raised.value).startswith(
            "acme/forecast cannot have a snapshot: these pipelines depend on each other, so its lineage "
            "would carry a cycle.\n  acme/forecast depends on acme/rates"
        )

    def test_build_with_no_build_script_stops_before_rendering(self, work, monkeypatch):
        a = _pipeline(work / "a", "acme/a", "x", {"b": {"path": "../b"}}, build=None)
        _pipeline(work / "b", "acme/b", "y", {"a": {"path": "../a"}}, build=None)
        monkeypatch.chdir(a)
        result = CliRunner().invoke(main, ["build", "-f"])
        assert result.exit_code == 1, result.output
        assert "No `build` script here, so only the site is rendered." in result.output
        assert "Error: acme/a: these pipelines depend on each other, so there is no order to build in." in result.output
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
            "other, so there is no order to build in. Take one of these out of its [dependencies]"
        )

    def test_check_addresses_a_cycle_among_what_it_depends_on_to_the_way_in(self, diamond):
        (problem,) = [p for p in run_checks(load_manifest(diamond), diamond) if "depend on each other" in p.message]
        assert (problem.file, problem.table, problem.field) == (diamond / "chartbook.toml", "dependencies.b", "path")
        assert problem.message == (
            "acme/b -> acme/c -> acme/b: pipelines this one depends on depend on each other, so there is "
            "no order to build in. Take one of these out of its [dependencies]"
        )

    def test_check_reports_a_self_dependency_upstream(self, chain):
        fred, rates, forecast = chain
        _declare(fred, {"me": {"path": "."}})
        (problem,) = [p for p in run_checks(load_manifest(forecast), forecast) if p.table.startswith("dependencies")]
        assert problem.table == "dependencies.rates"
        assert problem.message.startswith("acme/fred -> acme/fred: a pipeline this one depends on depends on itself, ")

    def test_check_says_a_pipelines_own_self_dependency_once(self, chain):
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


class TestThePinGuard:
    def test_a_refused_lockfile_is_not_written(self, would_be):
        fred, rates, forecast = would_be
        seen = []

        def refuse(would_be_written):
            seen.append(would_be_written)
            return "not today"

        report = lock.pin(fred, before_writing=refuse)
        assert report.refused == "not today" and not report.written
        assert [entry["id"] for entry in seen[0].dependencies] == ["acme/forecast"]
        assert _lockfile(fred) is None
        assert default_store().root_of(fred / "chartbook.lock", machine=lock._noted_as()) is None

    def test_one_let_through_is_written(self, would_be):
        fred, rates, forecast = would_be
        report = lock.pin(fred, before_writing=lambda would_be_written: None)
        assert report.refused == "" and report.written and _lockfile(fred) is not None

    def test_it_is_not_asked_when_nothing_would_change(self, chain):
        fred, rates, forecast = chain
        asked = []
        report = lock.pin(forecast, before_writing=lambda would_be_written: asked.append(1))
        assert asked == [] and not report.written
