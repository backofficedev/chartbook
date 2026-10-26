"""`chartbook run --upstream`: an upstream pipeline with no snapshot to pin is built and snapshotted first.

A `path` dependency is its owner's to build and snapshot. With `--upstream`, one on this machine
that has no snapshot a pin would take, and is not pinned yet, is built first, its own upstreams
before it, and snapshotted after its build succeeds, so that what depends on it can pin it. Each
must be trusted to run and fully committed, and the first failure stops the run.
"""

import os

import pytest
from click.testing import CliRunner

from chartbook import config, lock, run, snapshot
from chartbook.cli import main
from chartbook.run import RunError
from chartbook.store import default_store
from tests.test_run import LOG, _commit, _order, _pipeline, _with_data, work  # noqa: F401

posix = pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")


def _snapshots_of(pipeline: str) -> list:
    return [taken for taken in snapshot.readable_snapshots(default_store())[0] if taken.pipeline == pipeline]


@pytest.fixture
def pair(work):
    """`down` depends on `up` by path, in one repository; nothing is snapshotted."""
    up = _with_data(work / "up", {"build": LOG})
    down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
    _commit(work)
    return up, down


@posix
class TestUpstream:
    def test_without_it_the_run_stops_and_says_who_makes_the_snapshot(self, pair, work):
        up, down = pair
        report = run.run(down, echo=lambda line: None)
        assert report.failed.id == "down" and report.reason == "what it depends on could not be pinned"
        assert _order(work) == []

    def test_an_upstream_with_no_snapshot_is_built_and_snapshotted_first(self, pair, work):
        up, down = pair
        said = []
        report = run.run(down, upstream=True, echo=said.append)
        assert report.failed is None, report.reason
        assert _order(work) == ["up", "down"]
        assert said[:2] == ["Upstream with no snapshot to pin, built and snapshotted first:", f"  up    in {up}"]
        (taken,) = _snapshots_of("up")
        assert taken.built_by_run
        (entry,) = lock.read_lock(down).dependencies
        assert entry["snapshot"] == taken.made_at  # and down pinned it
        assert _snapshots_of("down") == []  # down itself is snapshotted only with --snapshot

    def test_with_snapshot_both_are_snapshotted(self, pair, work):
        up, down = pair
        assert run.run(down, upstream=True, snapshot=True, echo=lambda line: None).failed is None
        assert len(_snapshots_of("up")) == 1 and len(_snapshots_of("down")) == 1

    def test_upstreams_of_upstreams_come_first(self, work):
        _with_data(work / "c", {"build": LOG})
        _with_data(work / "b", {"build": LOG}, {"c": {"path": "../c"}})
        a = _with_data(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _commit(work)
        assert run.run(a, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["c", "b", "a"]
        assert len(_snapshots_of("c")) == 1 and len(_snapshots_of("b")) == 1

    def test_an_upstream_with_a_snapshot_is_not_built_again(self, pair, work):
        up, down = pair
        snapshot.make(up)
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["down"] and len(_snapshots_of("up")) == 1

    def test_an_upstream_already_pinned_is_not_built_again(self, pair, work):
        up, down = pair
        snapshot.make(up)
        lock.pin(down)
        taken = _snapshots_of("up")[0]
        os.chmod(taken.path, 0o600)
        taken.path.unlink()  # the store no longer has it; the pin stays
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["down"]

    def test_an_upstream_with_changes_not_committed_stops_the_run_before_anything(self, pair, work):
        up, down = pair
        (up / "notes.txt").write_text("half done")
        with pytest.raises(RunError, match=r"(?s)^up has changes that are not committed:.*Nothing was built\.$") as raised:
            run.run(down, upstream=True, echo=lambda line: None)
        assert "notes.txt" in str(raised.value)
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_this_user_has_not_trusted_is_not_run(self, pair, work, monkeypatch):
        up, down = pair
        monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
        monkeypatch.delenv("CI", raising=False)
        config.record_trust(down, "run")
        with pytest.raises(RunError) as raised:
            run.run(down, upstream=True, echo=lambda line: None)
        assert f"  up: {up} (not trusted, an upstream --upstream would build)" in str(raised.value)
        assert "`chartbook trust` in a folder trusts that one" in str(raised.value)
        assert _order(work) == []
        config.record_trust(up, "run")
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["up", "down"]

    def test_an_upstream_build_that_fails_stops_the_run(self, work):
        up = _with_data(work / "up", {"build": "exit 3"})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and report.exit_code == 3
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_build_that_changes_committed_files_is_not_snapshotted(self, work):
        up = _with_data(work / "up", {"build": "echo changed > x.parquet"})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and "changes that are not committed" in report.reason
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_with_no_build_script(self, work):
        _with_data(work / "up")
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        with pytest.raises(RunError, match="has no snapshot to pin and no `build` script"):
            run.run(down, upstream=True, echo=lambda line: None)
        assert _order(work) == []

    def test_what_it_is_refused_with(self, pair):
        up, down = pair
        with pytest.raises(RunError, match="--frozen writes nothing"):
            run.run(down, upstream=True, frozen=True, echo=lambda line: None)
        with pytest.raises(RunError, match="--upstream builds what `build` pins"):
            run.run(down, "test", upstream=True, echo=lambda line: None)

    def test_an_upstream_in_a_cycle_is_refused_before_anything(self, work):
        up = _with_data(work / "up", {"build": LOG}, {"down": {"path": "../down"}})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        with pytest.raises(RunError, match="depend on each other"):
            run.run(down, upstream=True, echo=lambda line: None)
        assert _order(work) == []

    def test_the_command(self, pair, work, monkeypatch):
        up, down = pair
        monkeypatch.chdir(down)
        result = CliRunner().invoke(main, ["run", "--upstream"])
        assert result.exit_code == 0, result.output
        assert "Upstream with no snapshot to pin, built and snapshotted first:" in result.output
        assert result.output.splitlines()[-1] == "Ran build in 2 pipeline(s)."
        assert _order(work) == ["up", "down"]
