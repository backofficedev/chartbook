"""`chartbook lineage`: every snapshot upstream of a pipeline, walked through the pins, and checked."""

import json
import os
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lineage, lock, snapshot
from chartbook.cli import main
from chartbook.store import default_store
from tests.test_model_versions import _commit, _git


def _pipeline(folder: Path, pipeline_id: str, name: str, dependencies: dict) -> None:
    (folder / "_data").mkdir(parents=True)
    manifest = {
        "project": {"id": pipeline_id},
        "dataframes": {name: {"path": f"./_data/{name}.parquet", "docs": "A file."}},
    }
    if dependencies:
        manifest["dependencies"] = {key: {"path": f"../{path}"} for key, path in dependencies.items()}
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    pl.DataFrame({"d": ["2024-01-01"], name: [1.0]}).write_parquet(folder / "_data" / f"{name}.parquet")


@pytest.fixture
def chain(tmp_path):
    """``fred`` <- ``rates`` <- ``forecast``: fred and rates snapshotted, each pinned by the next."""
    work = tmp_path.resolve()
    fred, rates, forecast = work / "fred", work / "rates", work / "forecast"
    _pipeline(fred, "acme/fred", "series", {})
    _pipeline(rates, "acme/rates", "treasury", {"fred": "fred"})
    _pipeline(forecast, "acme/forecast", "outlook", {"rates": "rates"})
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(work)
    snapshot.make(fred)
    lock.pin(rates)
    snapshot.make(rates)
    lock.pin(forecast)
    return fred, rates, forecast


def _snapshot_of(pipeline: str):
    found, _ = snapshot.readable_snapshots(default_store())
    (taken,) = [t for t in found if t.pipeline == pipeline]
    return taken


def _rewrite(taken, change) -> None:
    os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
    document = json.loads(taken.path.read_text())
    change(document)
    taken.path.write_text(json.dumps(document))


class TestTheWalk:
    def test_a_whole_chain_has_no_gaps(self, chain):
        fred, rates, forecast = chain
        found = lineage.walk(forecast)
        assert found.gaps() == [] and found.snapshots == 2
        (rates_node,) = found.root.children
        assert (rates_node.label, rates_node.pipeline, rates_node.kind) == ("rates", "acme/rates", "snapshot")
        (fred_node,) = rates_node.children
        assert (fred_node.label, fred_node.pipeline) == ("fred", "acme/fred")

    def test_a_snapshot_made_before_pins_were_checked(self, chain):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].pipeline == "acme/rates" and "declares the dependency 'fred'" in gap[1]

    def test_a_recorded_hash_that_does_not_match(self, chain):
        fred, rates, forecast = chain

        def tamper(document):
            document["inputs"][0]["pinned_hash"] = "sha256:" + "0" * 64

        _rewrite(_snapshot_of("acme/rates"), tamper)
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].label == "fred" and "that snapshot gives another" in gap[1]

    def test_an_upstream_snapshot_gone(self, chain):
        fred, rates, forecast = chain
        taken = _snapshot_of("acme/fred")
        os.chmod(taken.path, stat.S_IRUSR | stat.S_IWUSR)
        taken.path.unlink()
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].label == "fred" and "is not in the store" in gap[1]

    def test_an_object_gone_and_one_changed(self, chain):
        fred, rates, forecast = chain
        store = default_store()
        series = _snapshot_of("acme/fred").assets["series"]["content_hash"]
        held = Path(store.get(series))
        for file in held.rglob("*"):
            os.chmod(file, stat.S_IRUSR | stat.S_IWUSR)
            file.write_bytes(b"changed")
        assert lineage.walk(forecast).gaps() == []  # present, and not read again
        (gap,) = lineage.walk(forecast, rehash=True).gaps()
        assert "is not what its name says" in gap[1]
        assert store.delete(series)
        (gap,) = lineage.walk(forecast).gaps()
        assert gap[0].pipeline == "acme/fred" and "which the store does not have" in gap[1]

    def test_a_snapshot_met_twice_is_walked_once(self, chain):
        fred, rates, forecast = chain
        manifest = (forecast / "chartbook.toml").read_text()
        (forecast / "chartbook.toml").write_text(manifest + '\n[dependencies.fred]\npath = "../fred"\n')
        _commit(forecast.parent)
        lock.pin(forecast)
        found = lineage.walk(forecast)
        assert found.gaps() == [] and found.snapshots == 2
        seen = [n for n in found.root.children if n.label == "fred"] + [
            n for c in found.root.children for n in c.children if n.label == "fred"
        ]
        assert sorted(n.seen for n in seen) == [False, True]


class TestDeepSnapshots:
    def test_deep_refuses_what_upstream_lacks_and_shallow_does_not(self, chain):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        with pytest.raises(snapshot.SnapshotError, match="with --deep: a snapshot upstream has a gap"):
            snapshot.make(forecast, deep=True)
        assert snapshot.make(forecast).snapshot.pipeline == "acme/forecast"


class TestTheCommand:
    def test_it_draws_the_graph(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["lineage"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == "acme/forecast (this folder)"
        assert lines[1].startswith("└── rates: acme/rates ") and lines[2].startswith("    └── fred: acme/fred ")
        assert lines[-1] == "2 snapshot(s) upstream; no gaps."

    def test_check_fails_on_a_gap_and_json_says_it(self, chain, monkeypatch):
        fred, rates, forecast = chain
        _rewrite(_snapshot_of("acme/rates"), lambda d: d.pop("inputs", None))
        monkeypatch.chdir(forecast)
        assert CliRunner().invoke(main, ["lineage"]).exit_code == 0
        checked = CliRunner().invoke(main, ["lineage", "--check"])
        assert checked.exit_code == 1 and "gap: its manifest declares the dependency 'fred'" in checked.output
        shown = json.loads(CliRunner().invoke(main, ["lineage", "--json"]).output)
        assert shown["gaps"] == 1 and shown["root"]["children"][0]["gaps"]

    def test_rehash_says_how_many(self, chain, monkeypatch):
        fred, rates, forecast = chain
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["lineage", "--rehash"])
        assert result.exit_code == 0 and "object(s) hashed again; no gaps." in result.output
