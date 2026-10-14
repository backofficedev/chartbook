"""Tests for data in a database: ``[sources]``, ``table``, ``query``,
``data.sql()``, ``data.ref()`` and ``data.connect()``.

This is step 5 of ``docs_src/design/overview.md`` and the whole of
``docs_src/design/data-access.md``. The rule: a name resolves to a
location, the backend runs the query, Arrow comes back, Polars wraps it.
ChartBook never parses or rewrites SQL.

The one engine built is DuckDB. Every test here makes its own DuckDB file.
"""

import json
import os
from pathlib import Path

import duckdb
import jsonschema
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import backends, data, index
from chartbook.backends import BackendError, DuckDBBackend, ParquetBackend, duckdb_path
from chartbook.cli import main
from chartbook.manifest import load_manifest, validate_dataframe_location, validate_sources
from chartbook.resolve import QueryLocation, TableLocation, resolve


def _manifest(directory: Path, table: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table))
    (directory / "README.md").write_text("# A pipeline\n")
    return directory


RATES = {
    "project": {"id": "acme/rates"},
    "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
    "dataframes": {
        "rates": {"path": "./_data/rates.parquet", "docs": "A file."},
        "curve": {"source": "local", "table": "curve", "docs": "A table."},
        "slopes": {
            "source": "local",
            "query": "select d, y10 - y02 as slope from curve order by d",
            "docs": "A query.",
        },
    },
}


@pytest.fixture
def pipeline(tmp_path):
    """A pipeline with a file, a table and a query, all built."""
    directory = _manifest(tmp_path.resolve() / "rates", RATES)
    (directory / "_data").mkdir()
    pl.DataFrame({"d": ["2024-01-01", "2024-01-02"], "r": [4.1, 4.2]}).write_parquet(
        directory / "_data" / "rates.parquet"
    )
    con = duckdb.connect(str(directory / "_data" / "local.duckdb"))
    con.sql(
        "create table curve as select * from (values ('2024-01-01', 1.0, 4.0), "
        "('2024-01-02', 1.1, 4.3)) t(d, y02, y10)"
    )
    con.close()
    return directory


class TestManifest:
    def test_a_source_is_a_backend_and_a_url(self, tmp_path):
        sources = validate_sources(
            {"local": {"backend": "duckdb", "url": "duckdb:///./_data/x.duckdb"}}, tmp_path
        )
        assert sources["local"]["backend"] == "duckdb"
        assert sources["local"]["_resolved_url"] == f"duckdb:///{tmp_path / '_data' / 'x.duckdb'}"

    @pytest.mark.parametrize(
        "sources, message",
        [
            ("duckdb", "must be a table of tables"),
            ({"local": "duckdb"}, "must be a table with 'backend' and 'url'"),
            ({"my source": {"backend": "duckdb", "url": "duckdb:///x"}}, "not a legal source name"),
            ({"local": {"backend": "duckdb"}}, "needs 'url'"),
            ({"local": {"url": "duckdb:///x"}}, "needs 'backend'"),
            ({"local": {"backend": "duckdb", "url": "duckdb:///x", "password": "x"}}, "has 'password'"),
            ({"wh": {"backend": "snowflake", "url": "snowflake://acct/db"}}, "backend 'snowflake' is not built"),
            ({"local": {"backend": "duckdb", "url": "postgresql://h/db"}}, "does not begin with duckdb://"),
            ({"local": {"backend": "duckdb", "url": "duckdb://user:pw@h/db"}}, "carries a user name or a password"),
        ],
    )
    def test_a_malformed_source_is_refused(self, tmp_path, sources, message):
        with pytest.raises(ValueError, match=message):
            validate_sources(sources, tmp_path)

    def test_a_dataframe_is_in_one_place(self):
        sources = {"local": {"backend": "duckdb", "url": "duckdb:///x"}}
        assert validate_dataframe_location({"path": "./x.parquet"}, "x", sources) == "file"
        assert validate_dataframe_location({"source": "local", "table": "t"}, "x", sources) == "table"
        assert validate_dataframe_location({"source": "local", "query": "select 1"}, "x", sources) == "query"
        assert validate_dataframe_location({"docs": "declared only"}, "x", sources) == "file"

    @pytest.mark.parametrize(
        "entry, message",
        [
            ({"path": "./x", "table": "t", "source": "local"}, "has path and table"),
            ({"table": "t", "query": "q", "source": "local"}, "has table and query"),
            ({"path": "./x", "source": "local"}, "both path and source"),
            ({"table": "t"}, "has 'table' and no source"),
            ({"query": "select 1", "source": "nope"}, "source 'nope' is not declared"),
            ({"table": 3, "source": "local"}, "'table' must be a string"),
        ],
    )
    def test_a_dataframe_in_two_places_or_none_is_refused(self, entry, message):
        sources = {"local": {"backend": "duckdb", "url": "duckdb:///x"}}
        with pytest.raises(ValueError, match=message):
            validate_dataframe_location(entry, "x", sources)

    def test_the_loader_reads_them_and_names_the_file(self, pipeline):
        loaded = load_manifest(pipeline)
        assert loaded["sources"]["local"]["backend"] == "duckdb"
        assert loaded["dataframes"]["curve"]["_location_kind"] == "table"
        assert loaded["dataframes"]["slopes"]["_location_kind"] == "query"
        assert loaded["dataframes"]["rates"]["_location_kind"] == "file"
        assert loaded["dataframes"]["curve"]["_source"]["backend"] == "duckdb"
        broken = {**RATES, "dataframes": {"x": {"source": "nope", "table": "t", "docs": "d"}}}
        _manifest(pipeline, broken)
        with pytest.raises(ValueError) as e:
            load_manifest(pipeline)
        assert str(pipeline / "chartbook.toml") in str(e.value)

    def test_a_catalog_has_no_sources(self, tmp_path):
        _manifest(tmp_path / "p", {"project": {"id": "p"}})
        (tmp_path / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"type": "catalog"},
                    "pipelines": {"p": {"path": "p"}},
                    "sources": {"local": {"backend": "duckdb", "url": "duckdb:///x"}},
                }
            )
        )
        with pytest.raises(ValueError, match=r"a catalog has no \[sources\]"):
            load_manifest(tmp_path)

    def test_the_duckdb_url_convention(self, tmp_path):
        assert duckdb_path("duckdb:///rel.db", tmp_path) == str(tmp_path / "rel.db")
        assert duckdb_path("duckdb:///./_data/x.db", tmp_path) == str(tmp_path / "_data" / "x.db")
        assert duckdb_path("duckdb:////abs/x.db", tmp_path) == "/abs/x.db"
        assert duckdb_path("duckdb:///:memory:", tmp_path) == ":memory:"
        assert duckdb_path("duckdb://", tmp_path) == ":memory:"


class TestResolving:
    def test_a_table_and_a_query_resolve_to_their_source(self, pipeline):
        table = resolve("curve", start_dirs=[pipeline])
        assert isinstance(table, TableLocation)
        assert (table.source, table.backend, table.identifier) == ("local", "duckdb", "curve")
        assert table.url == f"duckdb:///{pipeline / '_data' / 'local.duckdb'}"
        query = resolve("slopes", start_dirs=[pipeline])
        assert isinstance(query, QueryLocation) and query.sql.startswith("select d,")

    def test_a_table_has_no_path(self, pipeline):
        with pytest.raises(TypeError) as e:
            data.path("curve", project_dir=pipeline)
        assert "table-backed, so it has no file path" in str(e.value)
        assert "data.sql()" in str(e.value) and "data.ref()" in str(e.value)
        result = CliRunner().invoke(main, ["path", "curve", "--project-dir", str(pipeline)])
        assert result.exit_code == 1 and "table-backed" in result.output


class TestLoading:
    def test_a_table(self, pipeline):
        frame = data.load("curve", project_dir=pipeline)
        assert isinstance(frame, pl.LazyFrame)
        assert frame.collect().shape == (2, 3)
        assert sorted(frame.collect_schema().names()) == ["d", "y02", "y10"]

    def test_a_query(self, pipeline):
        slopes = data.load("slopes", project_dir=pipeline).collect()["slope"].to_list()
        assert [float(s) for s in slopes] == [3.0, 3.2]  # DuckDB's DECIMAL, as the engine has it
        eager = data.load("slopes", format="polars_eager", project_dir=pipeline)
        assert isinstance(eager, pl.DataFrame)
        as_pandas = data.load("slopes", format="pandas", project_dir=pipeline)
        assert list(as_pandas.columns) == ["d", "slope"]
        with pytest.raises(ValueError, match="Invalid format"):
            data.load("slopes", format="arrow", project_dir=pipeline)

    def test_a_file_still_loads_as_before(self, pipeline):
        assert data.load("rates", project_dir=pipeline).collect().shape == (2, 2)

    def test_a_source_whose_file_is_not_built_yet(self, pipeline):
        (pipeline / "_data" / "local.duckdb").unlink()
        DuckDBBackend._connections.clear()
        with pytest.raises(BackendError, match="is not there. The pipeline builds it"):
            data.load("curve", project_dir=pipeline).collect()

    def test_a_query_the_engine_refuses(self, pipeline):
        broken = {**RATES}
        broken["dataframes"] = {
            **RATES["dataframes"],
            "bad": {"source": "local", "query": "select nope from curve", "docs": "d"},
        }
        _manifest(pipeline, broken)
        with pytest.raises(BackendError, match="nope"):
            data.load("bad", project_dir=pipeline).collect()


class TestRef:
    def test_a_file_a_table_and_a_query(self, pipeline):
        assert data.ref("rates", project_dir=pipeline) == (
            f"read_parquet('{pipeline / '_data' / 'rates.parquet'}')"
        )
        assert data.ref("curve", project_dir=pipeline) == '"curve"'
        assert data.ref("slopes", project_dir=pipeline) == (
            "(select d, y10 - y02 as slope from curve order by d)"
        )

    def test_identifiers_are_quoted_part_by_part(self):
        assert backends.quote_identifier("a.b.c") == '"a"."b"."c"'
        assert backends.quote_identifier('we"ird') == '"we""ird"'
        assert backends.quote_literal("it's") == "'it''s'"

    def test_a_partitioned_file(self, tmp_path):
        from chartbook.resolve import FileLocation

        text = ParquetBackend.ref(FileLocation(Path("/data/year=*/part-*.parquet")))
        assert text == "read_parquet('/data/year=*/part-*.parquet', hive_partitioning = true)"


class TestSql:
    def test_references_in_braces_are_the_only_thing_changed(self, pipeline):
        frame = data.sql(
            "select r.d, r.r, c.y10 from {rates} r join {curve} c on r.d = c.d order by 1",
            project_dir=pipeline,
        )
        assert isinstance(frame, pl.LazyFrame)
        rows = frame.collect().to_dicts()
        assert [row["d"] for row in rows] == ["2024-01-01", "2024-01-02"]
        assert rows[0]["y10"] == 4.0

    def test_a_query_dataframe_stands_where_a_table_would(self, pipeline):
        got = data.sql("select max(slope) as m from {slopes}", project_dir=pipeline).collect()
        assert [float(m) for m in got["m"].to_list()] == [3.2]

    def test_files_alone_run_in_memory(self, pipeline):
        assert data.sql("select count(*) as n from {rates}", project_dir=pipeline).collect().item() == 2

    def test_a_query_with_no_reference_is_refused(self, pipeline):
        with pytest.raises(ValueError, match="This query has none"):
            data.sql("select 1", project_dir=pipeline)

    def test_two_sources_at_once_are_refused(self, pipeline):
        two = {**RATES}
        two["sources"] = {
            **RATES["sources"],
            "other": {"backend": "duckdb", "url": "duckdb:///./_data/other.duckdb"},
        }
        two["dataframes"] = {**RATES["dataframes"], "o": {"source": "other", "table": "t", "docs": "d"}}
        _manifest(pipeline, two)
        with pytest.raises(ValueError, match="names dataframes in 2 sources, local, other"):
            data.sql("select * from {curve} join {o} using (d)", project_dir=pipeline)

    def test_a_reference_that_is_not_a_dataframe_is_refused(self, pipeline):
        from chartbook.errors import AssetNotDeclaredError

        with pytest.raises(AssetNotDeclaredError):
            data.sql("select * from {nope}", project_dir=pipeline)

    def test_sql_the_engine_refuses_says_so(self, pipeline):
        with pytest.raises(BackendError, match="nope"):
            data.sql("select nope from {curve}", project_dir=pipeline).collect()

    def test_the_same_reference_twice(self, pipeline):
        got = data.sql(
            "select a.d from {curve} a join {curve} b on a.d = b.d", project_dir=pipeline
        ).collect()
        assert got.height == 2


class TestConnect:
    def test_the_raw_connection_is_read_only(self, pipeline):
        con = data.connect("local", project_dir=pipeline)
        assert con.sql("select count(*) from curve").fetchone() == (2,)
        with pytest.raises(duckdb.Error):
            con.sql("create table x as select 1")

    def test_no_such_source(self, pipeline):
        with pytest.raises(LookupError, match="No source named 'nope'.*Its sources are: local"):
            data.connect("nope", project_dir=pipeline)


class TestCredentials:
    """The manifest holds the public part. The machine supplies the rest."""

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WARE_HOUSE_URL", "duckdb:///from-env.db")
        assert backends.source_url("ware-house", "duckdb:///manifest.db") == "duckdb:///from-env.db"
        assert backends.source_env_var("ware-house") == "CHARTBOOK_SOURCE_WARE_HOUSE_URL"

    def test_then_sources_toml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        (tmp_path / "sources.toml").write_text('[local]\nurl = "duckdb:///from-file.db"\n')
        assert backends.source_url("local", "duckdb:///manifest.db") == "duckdb:///from-file.db"
        assert backends.source_url("other", "duckdb:///manifest.db") == "duckdb:///manifest.db"

    def test_then_the_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        assert backends.source_url("local", "duckdb:///manifest.db") == "duckdb:///manifest.db"

    def test_a_sources_file_that_cannot_be_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        (tmp_path / "sources.toml").write_text("not = toml =")
        with pytest.raises(BackendError, match="Cannot read"):
            backends.source_url("local", "duckdb:///manifest.db")


class TestIndexAndSite:
    def test_the_records_say_where_each_dataframe_is(self, pipeline):
        built = index.build_index(load_manifest(pipeline))
        records = {r["id"]: r for r in built["records"] if r["kind"] == "Dataframe"}
        table = records["acme/rates:curve"]
        assert table["location"] == {"kind": "table", "source": "local", "backend": "duckdb", "identifier": "curve"}
        assert "content_hash" not in table and table["definition_hash"].startswith("sha256:")
        assert table["row_count"] == 2 and [c["name"] for c in table["columns"]] == ["d", "y02", "y10"]
        assert table["columns"][1]["dtype"] in ("DECIMAL(2,1)", "DOUBLE", "DECIMAL(3,1)")
        query = records["acme/rates:slopes"]
        assert query["location"]["kind"] == "query" and query["location"]["sql"].startswith("select d,")
        assert "source" not in query and "query" not in query  # in the location, not beside it
        file = records["acme/rates:rates"]
        assert file["location"]["kind"] == "file" and file["content_hash"].startswith("sha256:")
        schema = json.loads(index.schema_path("Dataframe").read_text())
        for record in index.published(built)["records"]:
            if record["kind"] == "Dataframe":
                jsonschema.validate(record, schema)

    def test_a_definition_hash_moves_with_the_definition_and_the_columns(self, pipeline):
        before = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"] if r["kind"] == "Dataframe"}
        changed = {**RATES}
        changed["dataframes"] = {**RATES["dataframes"], "slopes": {"source": "local", "query": "select d, y10 from curve", "docs": "d"}}
        _manifest(pipeline, changed)
        after = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"] if r["kind"] == "Dataframe"}
        assert before["acme/rates:slopes"]["definition_hash"] != after["acme/rates:slopes"]["definition_hash"]
        assert before["acme/rates:curve"]["definition_hash"] == after["acme/rates:curve"]["definition_hash"]

    def test_a_source_that_is_not_built_yet_has_no_columns(self, pipeline):
        (pipeline / "_data" / "local.duckdb").unlink()
        DuckDBBackend._connections.clear()
        built = index.build_index(load_manifest(pipeline))
        (table,) = [r for r in built["records"] if r["id"] == "acme/rates:curve"]
        assert "columns" not in table and "definition_hash" not in table
        assert table["location"]["kind"] == "table"

    def test_the_page_describes_the_table(self, pipeline, monkeypatch):
        monkeypatch.chdir(pipeline)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        page = (pipeline / "_docs" / "cb" / "dataframes" / "acme--rates" / "slopes.md").read_text()
        assert "A query in source 'local' (duckdb): 2 rows, 2 columns." in page
        assert "slope: DECIMAL" in page
        assert "| Query " in page and "in source `local`" in page
        assert (pipeline / "docs" / "index.html").exists()

    def test_check_passes_and_reports_a_missing_duckdb_file(self, pipeline):
        result = CliRunner().invoke(main, ["check", "--project-dir", str(pipeline)])
        assert "path: required" not in result.output  # a table has no path, and need none
        (pipeline / "_data" / "local.duckdb").unlink()
        result = CliRunner().invoke(main, ["check", "--project-dir", str(pipeline)])
        assert "[sources.local] url: the DuckDB file is not there" in result.output
        skipped = CliRunner().invoke(main, ["check", "--skip-outputs", "--project-dir", str(pipeline)])
        assert "DuckDB file is not there" not in skipped.output


class TestNotPinnedAcrossPipelines:
    def test_a_table_of_another_pipeline_is_not_in_a_snapshot(self, pipeline, tmp_path):
        """A snapshot holds files. A table has none, so it is not pinned, and
        a reference to it from another pipeline says so."""
        from chartbook.resolve import declared_files

        assert [str(ref) for ref, _, _ in declared_files(pipeline)] == ["rates"]
