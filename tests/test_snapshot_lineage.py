"""A snapshot carries its lineage: it is made only when the pipeline's pins account for every
dependency (docs_src/design/reading-other-pipelines.md, decision 6)."""

import shutil
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import lock, snapshot
from chartbook.cli import main
from chartbook.store import default_store
from tests.test_model_versions import _commit, _git


@pytest.fixture
def two(tmp_path):
    """``rates``, built and snapshotted, and ``forecast``, which depends on it and has built its own data."""
    work = tmp_path.resolve()
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "dataframes": {
                    "treasury": {"path": "./_data/treasury.parquet", "docs": "A file."},
                    "later": {"path": "./_data/later.parquet", "docs": "Not built yet."},
                },
            }
        )
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/forecast"},
                "dependencies": {"rates": {"path": "../rates"}},
                "dataframes": {"outlook": {"path": "./_data/outlook.parquet", "docs": "Its output."}},
            }
        )
    )
    pl.DataFrame({"d": ["2024-02-01"], "f": [4.2]}).write_parquet(forecast / "_data" / "outlook.parquet")
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(work)
    snapshot.make(rates)
    return rates, forecast


class TestASnapshotCarriesItsLineage:
    def test_no_lockfile(self, two):
        rates, forecast = two
        with pytest.raises(snapshot.SnapshotError, match="cannot have a snapshot: its pins do not account") as raised:
            snapshot.make(forecast)
        assert "does not exist" in str(raised.value) and "chartbook pin" in str(raised.value)

    def test_a_dependency_the_lockfile_does_not_list(self, two):
        rates, forecast = two
        lock.pin(forecast)
        other = forecast.parent / "other"
        shutil.copytree(rates, other)
        manifest = (forecast / "chartbook.toml").read_text()
        (forecast / "chartbook.toml").write_text(manifest.replace('[dependencies.rates]\npath = "../rates"', '[dependencies.rates]\npath = "../rates"\n\n[dependencies.other]\npath = "../other"'))
        _commit(forecast.parent)
        with pytest.raises(snapshot.SnapshotError, match="other: is in \\[dependencies\\] and not in the lockfile"):
            snapshot.make(forecast)

    def test_a_pin_from_a_working_folder(self, two):
        rates, forecast = two
        lock.pin(forecast, from_folder=True)
        with pytest.raises(snapshot.SnapshotError, match="rates: is pinned from its working folder"):
            snapshot.make(forecast)

    def test_a_pin_the_store_does_not_have(self, two):
        rates, forecast = two
        lock.pin(forecast)
        pinned = next(
            record["content_hash"] for record in lock.read_lock(forecast / lock.LOCK_FILE).assets.values()
            if record.get("content_hash")
        )
        assert default_store().delete(pinned)
        with pytest.raises(snapshot.SnapshotError, match="the store at .* does not have it"):
            snapshot.make(forecast)

    def test_full_lineage_is_a_snapshot_and_records_it(self, two):
        rates, forecast = two
        lock.pin(forecast)
        taken = snapshot.make(forecast).snapshot
        (entry,) = taken.inputs
        assert entry["id"] == "rates" and entry["location"]["commit"] and entry.get("pinned_hash")

    def test_an_upstream_asset_not_built_does_not_stop_it(self, two):
        rates, forecast = two
        lock.pin(forecast)
        records = lock.read_lock(forecast / lock.LOCK_FILE).assets
        assert any(record_id.endswith(":later") and not record.get("content_hash") for record_id, record in records.items())
        assert snapshot.make(forecast).snapshot.assets["outlook"]["content_hash"]

    def test_a_pipeline_with_no_dependencies_is_as_before(self, two):
        rates, forecast = two
        assert snapshot.make(rates).snapshot.pipeline == "acme/rates"

    def test_the_command_says_what_to_run(self, two, monkeypatch):
        rates, forecast = two
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["snapshot"])
        assert result.exit_code == 1
        assert "its pins do not account for every dependency" in result.output
        assert "Run `chartbook pin`" in result.output
