"""A table in Databricks, read from another pipeline: pinned by its Delta version.

A snapshot of the pipeline that names the table records the table's version,
not a copy; a pipeline that pins the snapshot reads the table at that
version, after checking it is still the table pinned. A query, a view or a
table with no versions is written out as parquet, as a DuckDB one is. The
warehouse is the stand-in of ``tests/mocked_databricks.py``.
"""

import json

import polars as pl
import pytest
import tomli
import tomli_w

from chartbook import data, lock, snapshot
from chartbook.backends import BackendError
from chartbook.errors import AssetNotPinnedError
from tests import mocked_databricks
from tests.mocked_databricks import Warehouse
from tests.test_model_versions import _commit, _git

HOST = "dbc-test.cloud.databricks.com"
HTTP_PATH = "/sql/1.0/warehouses/abc"
TOKEN = "dapi-test"
URL = f"databricks://{HOST}?http_path={HTTP_PATH}"
CURVE = "workspace.rates.curve"
FIRST = "select * from (values (date '2024-01-01', 4.0), (date '2024-01-02', 4.3)) t(d, y10)"
SECOND = "select * from (values (date '2024-01-01', 4.0), (date '2024-01-02', 4.3), (date '2024-01-03', 4.6)) t(d, y10)"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    for name in ("DATABRICKS_HTTP_PATH", "CHARTBOOK_SOURCE_WAREHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABRICKS_HOST", HOST)
    monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)


@pytest.fixture
def warehouse(monkeypatch):
    found = Warehouse(host=HOST, http_path=HTTP_PATH, token=TOKEN)
    found.table(CURVE, FIRST)
    found.view("workspace.rates.recent", f"select * from {CURVE} where d >= date '2024-01-02'")
    found.table("workspace.rates.plain", "select 1 as a", delta=False)
    return mocked_databricks.install(monkeypatch, found)


@pytest.fixture
def work(tmp_path, warehouse):
    """``rates`` names a Delta table, a view, a table with no versions and a query; ``forecast`` depends on it."""
    work = tmp_path.resolve() / "work"
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# A pipeline\n")
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "sources": {"warehouse": {"backend": "databricks", "url": URL}},
                "dataframes": {
                    "treasury": {"path": "./_data/treasury.parquet", "docs": "A file."},
                    "curve": {"source": "warehouse", "table": CURVE, "docs": "A Delta table."},
                    "recent": {"source": "warehouse", "table": "workspace.rates.recent", "docs": "A view."},
                    "plain": {"source": "warehouse", "table": "workspace.rates.plain", "docs": "No versions."},
                    "top": {"source": "warehouse", "query": f"select max(y10) as top from {CURVE}", "docs": "A query."},
                },
            }
        )
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}})
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\n_models/\n_output/\n_docs*/\ndocs/\nchartbook.lock\n")
    _commit(work)
    return rates, forecast


class TestTheSnapshot:
    def test_a_delta_table_is_kept_by_its_version(self, work, warehouse):
        rates, _ = work
        taken = snapshot.make(rates).snapshot
        curve = taken.assets["curve"]
        table_id = warehouse.tables[CURVE]["id"]
        assert curve["table_version"] == {"version": 0, "table_id": table_id, "written_at": "2026-10-01T01:00:00+00:00"}
        held = snapshot.default_store().object_path(curve["content_hash"])
        assert sorted(p.name for p in held.iterdir()) == ["curve.version.json"]
        assert json.loads((held / "curve.version.json").read_text()) == {
            "backend": "databricks", "identifier": CURVE, "table_id": table_id, "version": 0,
        }
        # No row was read for it
        assert not any(q.startswith("select * from `workspace`.`rates`.`curve` order by all") for q in warehouse.queries)

    def test_what_has_no_versions_is_written_out_as_parquet(self, work):
        rates, _ = work
        report = snapshot.make(rates)
        assets = report.snapshot.assets
        assert report.not_built == []
        store = snapshot.default_store()
        for name, rows in (("recent", 1), ("plain", 1), ("top", 1)):
            assert "table_version" not in assets[name]
            held = store.object_path(assets[name]["content_hash"]) / f"{name}.parquet"
            assert pl.read_parquet(held).height == rows

    def test_an_unchanged_table_is_the_same_snapshot(self, work):
        rates, _ = work
        assert snapshot.make(rates).made is True
        assert snapshot.make(rates).made is False

    def test_a_new_version_is_a_new_snapshot(self, work, warehouse):
        rates, _ = work
        first = snapshot.make(rates).snapshot.assets["curve"]
        warehouse.table(CURVE, SECOND)
        second = snapshot.make(rates)
        assert second.made is True
        assert second.snapshot.assets["curve"]["table_version"]["version"] == 1
        assert second.snapshot.assets["curve"]["content_hash"] != first["content_hash"]

    def test_with_no_token_it_is_recorded_as_not_built_and_says_why(self, work, monkeypatch):
        rates, _ = work
        monkeypatch.delenv("DATABRICKS_TOKEN")
        report = snapshot.make(rates)
        reasons = dict(report.not_built)
        assert "has no token" in reasons["acme/rates:curve"]
        assert "content_hash" not in report.snapshot.assets["curve"]
        assert report.snapshot.assets["treasury"]["content_hash"]


class TestAnotherPipelineReadsIt:
    def test_pin_then_load_at_the_pinned_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 2
        assert warehouse.queries[-1] == "select * from `workspace`.`rates`.`curve` VERSION AS OF 0"
        # The table moves on; the pin does not
        warehouse.table(CURVE, SECOND)
        assert data.load("rates:curve").collect().height == 2
        # A view is the copy the snapshot wrote out
        assert data.load("rates:recent").collect().height == 1

    def test_update_moves_to_the_new_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.table(CURVE, SECOND)
        snapshot.make(rates)
        assert any(e.status == "stale" and e.asset == "rates:curve" for e in lock.pin(forecast).events)
        report = lock.update(forecast)
        assert any(e.status == "moved" and e.asset == "rates:curve" for e in report.events)
        monkeypatch.chdir(forecast)
        assert data.load("rates:curve").collect().height == 3

    def test_sql_names_the_version(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.ref("rates:curve") == "`workspace`.`rates`.`curve` VERSION AS OF 0"
        assert data.sql("select count(*) as n from {rates:curve}").collect()["n"].to_list() == [2]

    def test_it_has_no_path(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        with pytest.raises(Exception, match="table"):
            data.path("rates:curve")
        assert data.path("rates:recent").name == "recent.parquet"

    def test_frozen_and_the_lineage_check_pass(self, work):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        assert lock.verify(forecast).problems == []
        assert snapshot.lineage_gaps(forecast) == []

    def test_a_version_the_table_no_longer_keeps_says_what_to_do(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.table(CURVE, SECOND)
        warehouse.vacuum(CURVE, keep_from=1)
        monkeypatch.chdir(forecast)
        with pytest.raises(BackendError) as error:
            data.load("rates:curve")
        for said in ("Cannot time travel", "pinned at version 0", "`chartbook update`", "delta.deletedFileRetentionDuration"):
            assert said in str(error.value)
        assert warehouse.open() == []

    def test_a_table_made_again_under_the_same_name_is_not_read_as_the_one_pinned(self, work, warehouse, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        warehouse.replace(CURVE, SECOND)
        monkeypatch.chdir(forecast)
        with pytest.raises(BackendError, match="is not the table that was pinned"):
            data.load("rates:curve")

    def test_reading_needs_this_machines_own_settings(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        monkeypatch.setenv("DATABRICKS_HOST", "other.example.com")
        with pytest.raises(BackendError, match=f"names the workspace {HOST}, and this machine's, from DATABRICKS_HOST, is other.example.com"):
            data.load("rates:curve")


class TestAPinFileFromAStoreIsChecked:
    @pytest.mark.parametrize(
        "change",
        [
            {"version": "0; drop table x"},
            {"version": -1},
            {"version": True},
            {"identifier": "a\nb"},
            {"identifier": "a.b.c.d"},
            {"table_id": "x' or 1=1"},
            {"backend": "duckdb"},
        ],
    )
    def test_one_ChartBook_did_not_write_is_refused(self, work, monkeypatch, change):
        rates, forecast = work
        taken = snapshot.make(rates).snapshot
        lock.pin(forecast)
        held = snapshot.default_store().object_path(taken.assets["curve"]["content_hash"]) / "curve.version.json"
        pinned = {**json.loads(held.read_text()), **change}
        held.chmod(0o644)
        held.write_text(json.dumps(pinned))
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="is not one ChartBook wrote"):
            data.load("rates:curve")
