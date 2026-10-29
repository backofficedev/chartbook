"""A table or query in a DuckDB file, read from another pipeline: written out as parquet by the snapshot."""

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import data, index, lock, snapshot
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.manifest import load_manifest
from tests.test_model_versions import _commit, _git


@pytest.fixture
def work(tmp_path):
    """``rates`` has a parquet dataframe, a DuckDB table and a query over it; ``forecast`` depends on it."""
    work = tmp_path.resolve() / "work"
    rates, forecast = work / "rates", work / "forecast"
    for directory in (rates, forecast):
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# A pipeline\n", encoding="utf-8", newline="\n")
    (rates / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                "dataframes": {
                    "treasury": {"path": "./_data/treasury.parquet", "docs": "A file."},
                    "curve": {"source": "local", "table": "curve", "docs": "A table.", "date_col": "d"},
                    "slopes": {"source": "local", "query": "select d, y10 - y02 as slope from curve order by d", "docs": "A query."},
                },
            }
        ), encoding="utf-8", newline="\n"
    )
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(rates / "_data" / "treasury.parquet")
    con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
    con.sql("create table curve as select * from (values (date '2024-01-01', 1.0, 4.0), (date '2024-01-02', 1.1, 4.3)) t(d, y02, y10)")
    con.close()
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/forecast"},
                "dependencies": {"rates": {"path": "../rates"}},
                "models": {"m": {"path": "./_models/m.json", "trained_on": ["rates:curve", "rates:slopes"], "docs": "A model."}},
            }
        ), encoding="utf-8", newline="\n"
    )
    (forecast / "_models").mkdir()
    (forecast / "_models" / "m.json").write_bytes(b"weights-1")
    # The repository first, then the ignore file: `_commit` writes one of its
    # own into a folder that is not a repository yet, and it lacks `_data/`
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\n_models/\n_output/\n_docs*/\ndocs/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    _commit(work)
    return rates, forecast


class TestTheSnapshotWritesTablesOut:
    def test_a_table_and_a_query_get_a_record_with_the_parquets_hash(self, work):
        rates, _ = work
        report = snapshot.make(rates)
        assets = report.snapshot.assets
        assert set(assets) == {"treasury", "curve", "slopes"}
        assert assets["curve"]["location"] == {
            "kind": "table", "source": "local", "backend": "duckdb", "url": "duckdb:///./_data/local.duckdb", "identifier": "curve",
        }
        assert assets["slopes"]["location"]["kind"] == "query" and "sql" in assets["slopes"]["location"]
        for name in ("curve", "slopes"):
            assert assets[name]["content_hash"].startswith("sha256:") and assets[name]["size_bytes"] > 0
            assert "path" not in assets[name]["location"]
        assert report.not_built == []
        # The parquet is in the store under the table's name, and holds the table
        held = Path(snapshot.default_store().get(assets["curve"]["content_hash"], name="curve.parquet")) / "curve.parquet"
        assert pl.read_parquet(held).shape == (2, 3)
        # Nothing changed: the next snapshot is the same one
        assert snapshot.make(rates).made is False

    def test_a_table_the_machine_cannot_read_is_recorded_as_not_built(self, work):
        rates, _ = work
        import tomli

        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["sources"]["memory"] = {"backend": "duckdb", "url": "duckdb:///:memory:"}
        config["dataframes"]["gone"] = {"source": "local", "table": "nope", "docs": "Not there."}
        config["dataframes"]["fleeting"] = {"source": "memory", "table": "t", "docs": "In memory."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        report = snapshot.make(rates)
        reasons = dict(report.not_built)
        assert "could not be read" in reasons["acme/rates:gone"]
        assert "only a table in a DuckDB file" in reasons["acme/rates:fleeting"]
        assert "content_hash" not in report.snapshot.assets["gone"]
        assert report.snapshot.assets["curve"]["content_hash"]


class TestAnotherPipelineReadsThem:
    def test_pin_then_load_by_name(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        report = lock.pin(forecast)
        assert {e.status for e in report.events if e.asset} == {"pinned"}
        monkeypatch.chdir(forecast)
        curve = data.load("rates:curve").collect()
        assert curve.shape == (2, 3) and curve.columns == ["d", "y02", "y10"]
        slopes = data.load("rates:slopes", format="polars_eager")
        assert [float(v) for v in slopes["slope"].to_list()] == pytest.approx([3.0, 3.2])
        assert data.path("rates:curve").name == "curve.parquet"
        # The pinned copy, not the live database: the table moves, the copy does not
        con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
        con.sql("insert into curve values (date '2024-01-03', 1.2, 4.6)")
        con.close()
        assert data.load("rates:curve").collect().shape == (2, 3)

    def test_a_model_trained_on_a_table_records_its_hash_and_goes_stale(self, work, monkeypatch):
        rates, forecast = work
        snapshot.make(rates)
        lock.pin(forecast)
        _commit(forecast.parent)
        taken = snapshot.make(forecast).snapshot
        locked = lock.read_lock(forecast / lock.LOCK_FILE)
        assert taken.assets["model/m"]["trained_on"] == {
            "rates:curve": locked.assets["rates:curve"]["content_hash"],
            "rates:slopes": locked.assets["rates:slopes"]["content_hash"],
        }
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["id"] == "acme/forecast:model/m"]
        assert set(record["pinned_inputs"]) == {"rates:curve", "rates:slopes"}
        assert record["stale_inputs"] == []
        # The table moves and the pin follows: the model is out of date on it
        con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
        con.sql("insert into curve values (date '2024-01-03', 1.2, 4.6)")
        con.close()
        snapshot.make(rates)
        lock.update(forecast)
        built = index.build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r["id"] == "acme/forecast:model/m"]
        assert record["stale_inputs"] == ["rates:curve", "rates:slopes"]

    def test_pinned_before_the_table_existed_says_what_to_do(self, work, monkeypatch):
        import tomli

        rates, forecast = work
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        curve = config["dataframes"].pop("curve")
        config["dataframes"].pop("slopes")
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        snapshot.make(rates)
        lock.pin(forecast)
        config["dataframes"]["curve"] = curve
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="`chartbook snapshot` in that pipeline's folder writes it out"):
            data.load("rates:curve")

    def test_the_commands_say_it(self, work, monkeypatch):
        rates, forecast = work
        monkeypatch.chdir(rates)
        made = CliRunner().invoke(main, ["snapshot"])
        assert made.exit_code == 0, made.output
        assert "3 asset(s) in the store" in made.output
        monkeypatch.chdir(forecast)
        pinned = CliRunner().invoke(main, ["pin"])
        assert pinned.exit_code == 0, pinned.output
        assert "rates: 3 pinned" in pinned.output
        shown = CliRunner().invoke(main, ["path", "rates:slopes"])
        assert shown.exit_code == 0 and shown.output.strip().endswith("slopes.parquet")
        locked = json.loads((forecast / "chartbook.lock").read_text(encoding="utf-8"))
        (record,) = [r for r in locked["records"] if r["id"] == "rates:curve"]
        assert record["location"]["kind"] == "table" and record["content_hash"]


class TestWhatTheReviewFound:
    def test_a_query_without_order_by_gives_the_same_bytes_every_time(self, work):
        """Found by a reviewer: a hash aggregate's rows came out in a different order on each
        snapshot, so every snapshot was new and every pin moved. The rows are written sorted."""
        import tomli

        rates, _ = work
        con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
        con.sql("create table big as select (i % 7) as k, i as v from range(200000) t(i)")
        con.close()
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["dataframes"]["agg"] = {"source": "local", "query": "select k, sum(v) as s from big group by k", "docs": "Grouped."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        first = snapshot.make(rates)
        assert first.made and first.snapshot.assets["agg"]["content_hash"]
        for _ in range(3):
            again = snapshot.make(rates)
            assert again.made is False
            assert again.snapshot.assets["agg"]["content_hash"] == first.snapshot.assets["agg"]["content_hash"]
        held = Path(snapshot.default_store().get(first.snapshot.assets["agg"]["content_hash"], name="agg.parquet")) / "agg.parquet"
        assert pl.read_parquet(held)["k"].to_list() == list(range(7))  # sorted on every column

    def test_a_column_polars_cannot_import_does_not_stop_the_snapshot(self, work):
        """Found by a reviewer: an INTERVAL column made Polars panic, which is not an Exception,
        and the whole snapshot died with it. The table is recorded as not built, with the reason."""
        import tomli

        rates, _ = work
        con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
        con.sql("create table spans as select interval '1 day' as span, 1 as n")
        con.close()
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["dataframes"]["spans"] = {"source": "local", "table": "spans", "docs": "Intervals."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        report = snapshot.make(rates)
        reasons = dict(report.not_built)
        assert "acme/rates:spans" in reasons and "could not be read" in reasons["acme/rates:spans"]
        assert "content_hash" not in report.snapshot.assets["spans"]
        assert report.snapshot.assets["curve"]["content_hash"]  # the rest is there

    def test_a_table_that_could_not_be_written_out_says_so_when_read(self, work, monkeypatch):
        """Found by a reviewer: the advice was "build it there", and building cannot help."""
        import tomli

        rates, forecast = work
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["sources"]["memory"] = {"backend": "duckdb", "url": "duckdb:///:memory:"}
        config["dataframes"]["fleeting"] = {"source": "memory", "table": "t", "docs": "In memory."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="has no pinned copy") as caught:
            data.load("rates:fleeting")
        assert caught.value.reason == "not_built"


    def test_a_floating_point_aggregate_gives_the_same_bytes_run_after_run(self, work):
        """Found by a reviewer: a parallel sum of doubles differs in its last bits between two
        runs, so a sorted result still hashed differently. The file is read on one thread."""
        import tomli

        rates, _ = work
        con = duckdb.connect(str(rates / "_data" / "local.duckdb"))
        con.sql("create table noise as select (i % 13) as k, random() * 1e6 as v from range(400000) t(i)")
        con.close()
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["dataframes"]["sums"] = {"source": "local", "query": "select k, sum(v) as s, avg(v) as m from noise group by k", "docs": "Sums."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        first = snapshot.make(rates).snapshot.assets["sums"]["content_hash"]
        for _ in range(3):
            again = snapshot.make(rates)
            assert again.made is False and again.snapshot.assets["sums"]["content_hash"] == first

    def test_a_query_the_author_ordered_keeps_that_order(self, work, monkeypatch):
        """Found by a reviewer: sorting on every column overrode the author's ORDER BY, so the
        pinned copy read in another order than the live query. Only an unordered query is sorted."""
        import tomli

        rates, forecast = work
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["dataframes"]["latest_first"] = {"source": "local", "query": "select y10, d from curve order by d desc", "docs": "Newest first."}
        config["dataframes"]["top"] = {"source": "local", "query": "select d, y10 from curve order by y10 desc limit 1", "docs": "The top."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        snapshot.make(rates)
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        pinned = data.load("rates:latest_first").collect()
        assert [str(d) for d in pinned["d"].to_list()] == ["2024-01-02", "2024-01-01"]
        assert data.load("rates:top").collect().shape == (1, 2)
        (record,) = [r for r in lock.read_lock(forecast / lock.LOCK_FILE).assets.values() if r["id"] == "rates:latest_first"]
        assert record["location"]["sql"] == "select y10, d from curve order by d desc"  # the author's SQL, not the engine's

    def test_a_query_the_parser_refuses_is_reported_on_the_authors_text(self, work):
        """Found by a reviewer: the error showed ChartBook's sort wrapper around the SQL."""
        import tomli

        rates, _ = work
        config = tomli.loads((rates / "chartbook.toml").read_text(encoding="utf-8"))
        config["dataframes"]["typo"] = {"source": "local", "query": "selec d from curve", "docs": "A typo."}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(config), encoding="utf-8", newline="\n")
        _commit(rates.parent)
        reasons = dict(snapshot.make(rates).not_built)
        assert "could not be read" in reasons["acme/rates:typo"]
        assert "order by all" not in reasons["acme/rates:typo"]
