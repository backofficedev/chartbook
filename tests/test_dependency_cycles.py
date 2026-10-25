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
        assert found.edges[0].where == (
            f"declared in {fred / 'chartbook.toml'}; pinned to its snapshot at {_snapshot_of('acme/forecast').commit[:7]}"
        )
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
            f"  acme/fred depends on acme/forecast (as 'fc'): declared in {fred / 'chartbook.toml'}; "
            f"pinned to its snapshot at {_snapshot_of('acme/forecast').commit[:7]}"
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


def _store_state():
    """Every file in the store, by path, with a hash of its bytes: objects, snapshots and notes."""
    import hashlib

    root = Path(os.environ["CHARTBOOK_STORE"])
    if not root.exists():
        return {}
    return {
        str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob("*") if f.is_file()
    }


def _git_repository(folder: Path, pipeline_id: str, name: str, dependencies=None, build=None) -> Path:
    """A pipeline in a repository of its own, its data and lockfile committed."""
    _pipeline(folder, pipeline_id, name, dependencies, build=build)
    if dependencies:
        lock.pin(folder)
    (folder / ".gitignore").write_text("")
    _git(folder, "init", "--quiet", "-b", "main")
    _commit(folder)
    return folder


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
        assert said.endswith("\nNothing was pinned or built.")
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
        assert result.output.rstrip().endswith("Nothing was pinned or built.")
        assert "pinning" not in result.output and _built(work) == []

    def test_a_cycle_a_pin_would_close_is_found_before_anything_is_written(self, would_be, work):
        fred, rates, forecast = would_be
        assert lineage.cycle(fred) is None  # nothing pinned says so yet
        before = _store_state()
        pinned = []
        with pytest.raises(run.RunError) as raised:
            run.run(fred, echo=lambda line: None, on_pin=lambda step, pins: pinned.append(pins))
        taken = _snapshot_of("acme/forecast")
        assert str(raised.value).startswith(
            "acme/fred: these pipelines depend on each other, so there is no order to build in.\n"
            f"  acme/fred depends on acme/forecast: declared in {fred / 'chartbook.toml'}; this run would pin "
            f"its snapshot at {taken.commit[:7]}\n"
            "  acme/forecast depends on acme/rates (as 'rates'): recorded by the snapshot of acme/forecast at "
        )
        assert str(raised.value).endswith("\nNothing was pinned or built.")
        assert pinned == [] and _built(work) == []
        assert _lockfile(fred) is None and _store_state() == before

    def test_at_the_terminal(self, would_be, work, monkeypatch):
        fred, rates, forecast = would_be
        monkeypatch.chdir(fred)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1, result.output
        assert result.output.startswith("Error: acme/fred: these pipelines depend on each other")
        assert result.output.rstrip().endswith("Nothing was pinned or built.")
        assert "Wrote chartbook.lock" not in result.output and _lockfile(fred) is None

    def test_a_pin_that_would_close_one_when_its_turn_comes_is_not_written(self, would_be, work, monkeypatch):
        """Had the run not seen it coming (a build earlier in the run changes what a pin takes), the pin itself refuses."""
        fred, rates, forecast = would_be
        monkeypatch.setattr(lock, "would_pin", lambda *arguments, **keywords: None)
        before = _store_state()
        pinned = []
        report = run.run(fred, echo=lambda line: None, on_pin=lambda step, pins: pinned.append(pins))
        assert report.failed.id == "acme/fred" and report.exit_code == 1
        assert report.reason.startswith(
            "pinning what it depends on would close a cycle: these pipelines depend on each other, so there "
            "is no order to build in.\n"
        )
        assert report.reason.endswith("\nIts lockfile was left as it was, and it was not built")
        assert pinned == [] and _built(work) == []
        assert _lockfile(fred) is None and _store_state() == before

    @pytest.mark.parametrize("pinned_before", [True, False], ids=["pinned-before", "a-pin-would-close-it"])
    def test_a_catalog_builds_nothing_when_one_of_its_pipelines_is_in_a_cycle(self, would_be, work, pinned_before):
        """apart comes first and has nothing to do with the cycle: it is not built either."""
        fred, rates, forecast = would_be
        if pinned_before:
            lock.pin(fred)  # by `chartbook pin`, which does not refuse it
        _pipeline(work / "apart", "acme/apart", "a", {"acme/rates": {}})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"apart": {"path": "apart"}, "fred": {"path": "fred"}}})
        )
        before = (_lockfile(work / "apart"), _lockfile(fred), _store_state())
        with pytest.raises(run.RunError, match=r"^acme/fred: these pipelines depend on each other"):
            run.run(work, echo=lambda line: None)
        assert _built(work) == []
        assert (_lockfile(work / "apart"), _lockfile(fred), _store_state()) == before

    def test_a_cycle_another_pipelines_new_pin_closes(self, work):
        """In one catalog, b depends on a by path and is pinned; a comes to name x, which was made from an older b.

        b's own lockfile does not change, and a's walk does not lead back to
        a: the cycle b -> a -> x -> b is seen only with a's pin as it would
        be written.
        """
        b = _pipeline(work / "b", "acme/b", "bills")
        x = _pipeline(work / "x", "acme/x", "xs", {"acme/b": {}})
        a = _pipeline(work / "a", "acme/a", "alpha")
        _repository(work)
        snapshot.make(b)
        lock.pin(x)
        snapshot.make(x)
        snapshot.make(a)
        _declare(b, {"a": {"path": "../a"}})
        lock.pin(b)
        _declare(a, {"acme/x": {}})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"a": {"path": "a"}, "b": {"path": "b"}}})
        )
        before = (_lockfile(a), _lockfile(b), _store_state())
        with pytest.raises(run.RunError) as raised:
            run.run(work, echo=lambda line: None)
        assert str(raised.value).startswith("acme/b: these pipelines depend on each other")
        assert "acme/x depends on acme/b: recorded by the snapshot of acme/x at " in str(raised.value)
        assert _built(work) == [] and (_lockfile(a), _lockfile(b), _store_state()) == before

    def test_a_cycle_through_a_git_dependency_not_pinned_yet(self, tmp_path):
        """p takes g from its repository; g's committed lockfile pins x, whose snapshot was made from p."""
        work, elsewhere = (tmp_path / "work").resolve(), (tmp_path / "g").resolve()
        work.mkdir()
        p = _pipeline(work / "p", "acme/p", "prices")
        x = _pipeline(work / "x", "acme/x", "xs", {"acme/p": {}})
        _repository(work)
        snapshot.make(p)
        lock.pin(x)
        snapshot.make(x)
        g = _pipeline(elsewhere, "acme/g", "gold", {"acme/x": {}}, build=f"echo built >> {work / 'g.log'}")
        lock.pin(g)
        (g / ".gitignore").write_text("_data/\n")
        _git(g, "init", "--quiet", "-b", "main")
        _commit(g)
        _declare(p, {"acme/g": {"git": str(g)}})
        before = (_lockfile(p), _store_state())
        with pytest.raises(run.RunError) as raised:
            run.run(p, echo=lambda line: None)
        assert str(raised.value).startswith("acme/p: these pipelines depend on each other")
        assert "acme/p depends on acme/g: declared in " in str(raised.value)
        assert not (work / "g.log").exists() and _built(work) == []
        assert (_lockfile(p), _store_state()) == before

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
        assert result.output.rstrip().endswith("Nothing was pinned or built.")
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

        before = _store_state()
        report = lock.pin(fred, before_writing=refuse)
        assert report.refused == "not today" and not report.written
        assert [entry["id"] for entry in seen[0].dependencies] == ["acme/forecast"]
        assert _lockfile(fred) is None and _store_state() == before

    def test_a_refused_lockfile_that_is_there_is_left_as_it_was(self, chain):
        fred, rates, forecast = chain
        _declare(forecast, {"rates": {"path": "../rates"}, "acme/fred": {}})
        before = (_lockfile(forecast), _store_state())
        assert lock.pin(forecast, before_writing=lambda would_be_written: "no").refused == "no"
        assert (_lockfile(forecast), _store_state()) == before

    def test_one_let_through_is_written(self, would_be):
        fred, rates, forecast = would_be
        report = lock.pin(fred, before_writing=lambda would_be_written: None)
        assert report.refused == "" and report.written and _lockfile(fred) is not None

    def test_it_is_asked_even_when_nothing_would_change(self, chain):
        """Another pipeline's new pin may close a cycle through this one, whose lockfile stays as it is."""
        fred, rates, forecast = chain
        before = _lockfile(forecast)
        assert lock.pin(forecast, before_writing=lambda would_be_written: "no").refused == "no"
        assert _lockfile(forecast) == before


class TestWorkingOutAPin:
    def test_it_writes_nothing(self, would_be):
        fred, rates, forecast = would_be
        before = _store_state()
        after = lock.would_pin(fred)
        assert [entry["id"] for entry in after.dependencies] == ["acme/forecast"]
        assert after.dependencies[0]["snapshot"] == _snapshot_of("acme/forecast").made_at
        assert _lockfile(fred) is None and _store_state() == before

    def test_nothing_to_work_out_when_everything_is_pinned(self, chain):
        fred, rates, forecast = chain
        assert lock.would_pin(forecast) is None and lock.would_pin(fred) is None

    def test_what_a_pin_would_put_in_the_store_is_not_read(self, chain, tmp_path):
        """A git dependency's files are put in the store when pinned; worked out, they are not even read."""
        fred, rates, forecast = chain
        repository = _git_repository(tmp_path / "ref", "acme/ref", "table")
        _declare(fred, {"acme/ref": {"git": str(repository)}})
        before = _store_state()
        after = lock.would_pin(fred)
        (entry,) = after.dependencies
        assert entry["location"]["commit"] == _git(repository, "rev-parse", "HEAD")
        (record,) = after.assets.values()
        assert not record.get("content_hash") and _store_state() == before
        assert lock.pin(fred).written
        (pinned,) = lock.read_lock(fred).assets.values()
        assert default_store().has(pinned["content_hash"])

    def test_a_pin_with_no_bytes_is_worked_out_again(self, chain):
        """As `pin` takes the newest snapshot again for an entry that names a snapshot and holds no hash."""
        fred, rates, forecast = chain
        path = forecast / "chartbook.lock"
        document = json.loads(path.read_text())
        for record in document["records"]:
            record.pop("content_hash", None)
        path.write_text(json.dumps(document))
        assert [entry["id"] for entry in lock.would_pin(forecast).dependencies] == ["rates"]


@posix
class TestWhatTheSecondReviewFound:
    def test_a_member_named_by_its_id_is_walked_through_its_folder(self, work):
        """d names m by its ID; m comes to name x, whose snapshot was made from d. With --snapshot, m would be built and snapshotted first."""
        d = _pipeline(work / "d", "acme/d", "ds")
        x = _pipeline(work / "x", "acme/x", "xs", {"acme/d": {}})
        m = _pipeline(work / "m", "acme/m", "ms")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"d": {"path": "d"}, "m": {"path": "m"}}})
        )
        _repository(work)
        snapshot.make(d)
        lock.pin(x)
        snapshot.make(x)
        snapshot.make(m)
        _declare(d, {"acme/m": {}})
        lock.pin(d)
        _declare(m, {"acme/x": {}})
        _commit(work)
        before = (_lockfile(d), _lockfile(m), _store_state())
        for snapshot_too in (True, False):
            with pytest.raises(run.RunError) as raised:
                run.run(work, snapshot=snapshot_too, echo=lambda line: None)
            assert "these pipelines depend on each other" in str(raised.value)
            assert f"depends on acme/m: declared in {d / 'chartbook.toml'}" in str(raised.value)
            assert _built(work) == [] and (_lockfile(d), _lockfile(m), _store_state()) == before

    def test_a_refused_pin_puts_no_object_in_the_store(self, would_be, work, tmp_path, monkeypatch):
        """fred also takes a git dependency in the same pin: its files are held, and not put, when the pin is refused."""
        fred, rates, forecast = would_be
        repository = _git_repository(tmp_path / "ref", "acme/ref", "table")
        _declare(fred, {"acme/forecast": {}, "acme/ref": {"git": str(repository)}})
        monkeypatch.setattr(lock, "would_pin", lambda *arguments, **keywords: None)
        before = _store_state()
        report = run.run(fred, echo=lambda line: None)
        assert report.reason.startswith("pinning what it depends on would close a cycle: ")
        assert _lockfile(fred) is None and _store_state() == before

    def test_a_pin_that_cannot_be_worked_out_stops_the_run_before_anything_is_built(self, would_be, work, monkeypatch):
        fred, rates, forecast = would_be
        _pipeline(work / "apart", "acme/apart", "a", {"acme/rates": {}})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"apart": {"path": "apart"}, "fred": {"path": "fred"}}})
        )

        def unreachable(folder, *arguments, **keywords):
            if Path(folder).name == "fred":
                raise lock.LockError("the store cannot be reached")
            return None

        monkeypatch.setattr(lock, "would_pin", unreachable)
        with pytest.raises(run.RunError, match=r"^acme/fred: the store cannot be reached\nNothing was pinned or built\.$"):
            run.run(work, echo=lambda line: None)
        assert _built(work) == [] and _lockfile(work / "apart") is None

    def test_a_cycle_among_members_without_a_build_script(self, work):
        """apart builds; b and c have no build script. c depends on b, b on x, and x was made from c."""
        c = _pipeline(work / "c", "acme/c", "cs", build=None)
        x = _pipeline(work / "x", "acme/x", "xs", {"acme/c": {}})
        b = _pipeline(work / "b", "acme/b", "bs", {"acme/x": {}}, build=None)
        _pipeline(work / "apart", "acme/apart", "a")
        _repository(work)
        snapshot.make(c)
        lock.pin(x)
        snapshot.make(x)
        lock.pin(b)
        _declare(c, {"b": {"path": "../b"}})
        (work / "chartbook.toml").write_text(
            tomli_w.dumps(
                {"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in ("apart", "b", "c")}}
            )
        )
        with pytest.raises(run.RunError, match="these pipelines depend on each other"):
            run.run(work, echo=lambda line: None)
        assert _built(work) == []


@posix
class TestWhatTheThirdReviewFound:
    @pytest.mark.parametrize("named_by", ["id", "path"])
    def test_a_pinned_snapshot_that_still_carries_a_dependency_the_folder_dropped(self, work, named_by):
        """a pins b's snapshot, which was made from c, which was made from a; b's folder has since dropped c.

        `pin` does not move a pin, so a is built from that snapshot: the cycle is there whatever b's folder says.
        """
        a = _pipeline(work / "a", "acme/a", "as")
        b = _pipeline(work / "b", "acme/b", "bs")
        c = _pipeline(work / "c", "acme/c", "cs")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"a": {"path": "a"}, "b": {"path": "b"}}})
        )
        _repository(work)
        snapshot.make(a)
        _declare(c, {"acme/a": {}})
        lock.pin(c)
        _commit(work)
        snapshot.make(c)
        _declare(b, {"acme/c": {}})
        lock.pin(b)
        _commit(work)
        snapshot.make(b)
        _declare(a, {"acme/b": {}} if named_by == "id" else {"b": {"path": "../b"}})
        lock.pin(a)
        _declare(b, {})
        _commit(work)
        before = (_lockfile(a), _lockfile(b), _store_state())
        for snapshot_too in (False, True):
            with pytest.raises(run.RunError) as raised:
                run.run(work, snapshot=snapshot_too, echo=lambda line: None)
            assert str(raised.value).startswith("acme/a: these pipelines depend on each other")
            assert f"; pinned to its snapshot at {_snapshot_of('acme/b').commit[:7]}" in str(raised.value)
            assert _built(work) == [] and (_lockfile(a), _lockfile(b), _store_state()) == before
        (problem,) = [p for p in run_checks(load_manifest(work), work) if "depend on each other" in p.message]
        assert problem.file == a / "chartbook.toml"

    def test_a_dependency_got_from_its_repository_is_walked_through_its_clone(self, work, tmp_path, monkeypatch):
        """fred names ref by its ID; the store has no snapshot of it, so it is cloned from the default host. ref pins x, and x was made from fred."""
        from chartbook import config

        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user" / ".chartbook")
        config.get_global_settings_path().parent.mkdir(parents=True)
        config.get_global_settings_path().write_text(tomli_w.dumps({"resolve": {"default_host": str(tmp_path / "host")}}))
        fred = _pipeline(work / "fred", "acme/fred", "series")
        x = _pipeline(work / "x", "acme/x", "xs", {"acme/fred": {}})
        _repository(work)
        snapshot.make(fred)
        lock.pin(x)
        snapshot.make(x)
        _git_repository(tmp_path / "host" / "acme" / "ref", "acme/ref", "table", {"acme/x": {}})
        _declare(fred, {"acme/ref": {}})
        lock.pin(fred)
        (entry,) = lock.read_lock(fred).dependencies
        assert entry["location"]["kind"] == "git"  # got from its repository
        found = lineage.cycle(fred)
        assert _around(found) == [("acme/fred", "acme/ref"), ("acme/ref", "acme/x"), ("acme/x", "acme/fred")]
        with pytest.raises(run.RunError, match="^acme/fred: these pipelines depend on each other"):
            run.run(fred, echo=lambda line: None)

    def test_what_pin_keeps_of_a_dependency_got_from_its_repository(self):
        clone = {"location": {"kind": "git", "pipeline": "acme/rates", "commit": "a" * 40}}
        by_id, by_git = {"_store": "acme/rates"}, {"git": "https://example.org/acme/rates"}
        held = {"acme/rates:x": {"content_hash": "sha256:" + "1" * 64}}
        assert lock._has_a_pin(clone, held, by_id) and lock._has_a_pin(clone, {}, by_git)
        # Nothing of it pinned with its bytes, or another pipeline's repository: `pin` looks again
        assert not lock._has_a_pin(clone, {}, by_id)
        assert not lock._has_a_pin(clone, held, {"_store": "acme/other"})

    def test_a_guarded_pin_reads_a_git_dependencys_files_once_and_writes_what_an_unguarded_one_does(self, chain, tmp_path, monkeypatch):
        from chartbook import hashing

        fred, rates, forecast = chain
        repository = _git_repository(tmp_path / "ref", "acme/ref", "table")
        _declare(fred, {"acme/ref": {"git": str(repository)}})
        read = []
        original = hashing._file_hex
        monkeypatch.setattr(hashing, "_file_hex", lambda path: read.append(Path(path).name) or original(path))
        assert lock.pin(fred, before_writing=lambda would_be_written: None).written
        assert read.count("table.parquet") == 1
        guarded = _lockfile(fred)
        (fred / "chartbook.lock").unlink()
        lock.pin(fred)
        assert _lockfile(fred) == guarded
        (record,) = lock.read_lock(fred).assets.values()
        assert default_store().has(record["content_hash"])


@posix
class TestWhatTheFourthReviewFound:
    @pytest.mark.parametrize("named_by", ["id", "path"])
    def test_a_member_whose_old_snapshot_leads_back_is_snapshotted_first(self, work, named_by):
        """q's snapshot in the store was made when it depended on p; q now depends on r, and p comes to depend on q.

        The run checks a pin against the snapshot the store has now, even
        when --snapshot would make a newer one first: it cannot know which
        one the pin will take. It says so, and once q's new snapshot is
        made, the run goes through.
        """
        p = _pipeline(work / "p", "acme/p", "ps")
        q = _pipeline(work / "q", "acme/q", "qs")
        r = _pipeline(work / "r", "acme/r", "rs")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in "pqr"}})
        )
        _repository(work)
        snapshot.make(p)
        snapshot.make(r)
        _declare(q, {"acme/p": {}})
        lock.pin(q)
        _commit(work)
        snapshot.make(q)
        _declare(q, {"acme/r": {}})
        _declare(p, {"acme/q": {}} if named_by == "id" else {"q": {"path": "../q"}})
        _commit(work)
        before = (_lockfile(p), _lockfile(q), _store_state())
        with pytest.raises(run.RunError) as raised:
            run.run(work, snapshot=True, echo=lambda line: None)
        assert str(raised.value).startswith("acme/p: these pipelines depend on each other")
        assert (
            f"The pin of acme/q is of the snapshot the store has of it now, which this run would replace with "
            f"--snapshot. If acme/q no longer depends on what leads back here, make its new snapshot first "
            f"(`chartbook run --snapshot --project-dir {q}`), and run this again."
        ) in str(raised.value)
        assert _built(work) == [] and (_lockfile(p), _lockfile(q), _store_state()) == before
        assert run.run(q, snapshot=True, echo=lambda line: None).failed is None
        report = run.run(work, snapshot=True, echo=lambda line: None)
        assert report.failed is None, report.reason
        assert lineage.cycle(p) is None

    def test_the_pin_at_its_turn_is_walked_as_it_is(self, would_be, work, monkeypatch):
        """The pins' own walks pass over nothing: what a pin takes is what is walked."""
        fred, rates, forecast = would_be
        monkeypatch.setattr(lock, "would_pin", lambda *arguments, **keywords: None)
        report = run.run(fred, snapshot=False, echo=lambda line: None)
        assert report.reason.startswith("pinning what it depends on would close a cycle: ")
        assert _lockfile(fred) is None and _built(work) == []

    def test_the_store_is_read_once_for_every_walk_of_a_command(self, chain, work, monkeypatch):
        fred, rates, forecast = chain
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {n: {"path": n} for n in ("fred", "rates", "forecast")}})
        )
        reads = []
        original = lineage._Finder._read
        monkeypatch.setattr(lineage._Finder, "_read", lambda self: reads.append(1) or original(self))
        run_checks(load_manifest(work), work)
        assert len(reads) == 1
        reads.clear()
        assert run.run(work, echo=lambda line: None).failed is None
        assert len(reads) == 1

    def test_a_snapshots_input_got_from_a_clone_is_walked_through_it(self, work, tmp_path):
        """forecast takes ref from its repository; ref pins fred; fred comes to name forecast by its ID."""
        fred = _pipeline(work / "fred", "acme/fred", "series")
        forecast = _pipeline(work / "forecast", "acme/forecast", "outlook")
        _repository(work)
        snapshot.make(fred)
        ref = _git_repository(tmp_path / "ref", "acme/ref", "table", {"acme/fred": {}})
        _declare(forecast, {"acme/ref": {"git": str(ref)}})
        lock.pin(forecast)
        _commit(work)
        snapshot.make(forecast)
        _declare(fred, {"acme/forecast": {}})
        lock.pin(fred)
        found = lineage.cycle(fred)
        assert _around(found) == [("acme/fred", "acme/forecast"), ("acme/forecast", "acme/ref"), ("acme/ref", "acme/fred")]
        assert found.edges[1].where.startswith("recorded by the snapshot of acme/forecast at ")

    def test_a_refused_pin_reports_no_stand_in(self, chain, tmp_path):
        fred, rates, forecast = chain
        repository = _git_repository(tmp_path / "ref", "acme/ref", "table")
        _declare(fred, {"acme/ref": {"git": str(repository)}})
        report = lock.pin(fred, before_writing=lambda would_be_written: "no")
        assert report.refused == "no" and report.events
        assert not any(str(event.new or "").startswith("held:") for event in report.events)


@posix
class TestWhatTheFifthReviewFound:
    def _p_q_r(self, work):
        """p, q and r in one catalog: q's snapshot in the store was made when q depended on p; q now depends on r."""
        p = _pipeline(work / "p", "acme/p", "ps")
        q = _pipeline(work / "q", "acme/q", "qs")
        r = _pipeline(work / "r", "acme/r", "rs")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in "pqr"}})
        )
        _repository(work)
        snapshot.make(p)
        snapshot.make(r)
        _declare(q, {"acme/p": {}})
        lock.pin(q)
        _commit(work)
        old = snapshot.make(q).snapshot.commit
        _declare(q, {"acme/r": {}})
        return p, q, r, old

    def test_a_pin_narrowed_to_an_old_commit_takes_the_old_snapshot(self, work):
        p, q, r, old = self._p_q_r(work)
        _declare(p, {"acme/q": {"commit": old}})
        _commit(work)
        before = (_lockfile(p), _lockfile(q), _store_state())
        with pytest.raises(run.RunError, match="^acme/p: these pipelines depend on each other"):
            run.run(work, snapshot=True, echo=lambda line: None)
        assert _built(work) == [] and (_lockfile(p), _lockfile(q), _store_state()) == before

    def test_a_snapshot_that_is_given_back_is_walked(self, work, tmp_path):
        """q has a snapshot at its commit already; a run that changes nothing of it gets that one back, which was pinned to y's snapshot made from p."""
        p = _pipeline(work / "p", "acme/p", "ps")
        q = _pipeline(work / "q", "acme/q", "qs")
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in "pq"}})
        )
        _repository(work)
        snapshot.make(p)
        y = _pipeline(tmp_path / "y", "acme/y", "ys", {"acme/p": {}})
        lock.pin(y)
        (y / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _git(y, "init", "--quiet", "-b", "main")
        _commit(y)
        snapshot.make(y)
        _declare(q, {"acme/y": {}})
        lock.pin(q)
        _declare(p, {"acme/q": {}})
        _commit(work)
        snapshot.make(q, built_by_run=True)  # at the commit the run will be at
        _declare(y, {})
        lock.pin(y)
        _commit(y)
        snapshot.make(y)  # y no longer depends on p
        lock.update(q)  # q's lockfile now pins it; nothing committed changes
        before = (_lockfile(p), _lockfile(q), _store_state())
        with pytest.raises(run.RunError, match="^acme/p: these pipelines depend on each other"):
            run.run(work, snapshot=True, echo=lambda line: None)
        assert _built(work) == [] and (_lockfile(p), _lockfile(q), _store_state()) == before

    def test_a_pin_the_store_lacks_is_looked_for_once_per_command(self, chain, work, monkeypatch):
        fred, rates, forecast = chain
        path = forecast / "chartbook.lock"
        document = json.loads(path.read_text())
        for record in document["records"]:
            for entry in record.get("dependencies") or []:
                entry["snapshot"] = "2001-01-01T00:00:00.000000Z"  # gone from the store
        path.write_text(json.dumps(document))
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {n: {"path": n} for n in ("fred", "rates", "forecast")}})
        )
        reads = []
        original = lineage._Finder._read
        monkeypatch.setattr(lineage._Finder, "_read", lambda self: reads.append(1) or original(self))
        run_checks(load_manifest(work), work)
        assert len(reads) == 1
