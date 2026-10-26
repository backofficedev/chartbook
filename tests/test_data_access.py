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
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8")
    (directory / "README.md").write_text("# A pipeline\n", encoding="utf-8")
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
            ({"wh": {"backend": "snowflake", "url": "snowflake://acct/db"}}, "backend 'snowflake' is not one ChartBook knows"),
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

    @pytest.mark.parametrize(
        "entry, message",
        [
            ({"path": "", "source": "local"}, "has both path and source"),
            ({"table": "", "source": "local"}, "'table' must be a string, and not empty"),
            ({"source": "local"}, "has a source and neither table nor query"),
        ],
    )
    def test_an_empty_value_is_not_an_absent_one(self, entry, message):
        """Found by a reviewer: truthiness let `path = ""` with a source through."""
        with pytest.raises(ValueError, match=message):
            validate_dataframe_location(entry, "x", {"local": {}})

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
            ), encoding="utf-8"
        )
        with pytest.raises(ValueError, match=r"a catalog has no \[sources\]"):
            load_manifest(tmp_path)

    @pytest.mark.parametrize(
        "url, message",
        [
            ("duckdb://host/x.duckdb", "has a host or a user, and"),
            ("duckdb://user@/x.duckdb", "has a host or a user, and"),
            ("duckdb:///x.duckdb?access_mode=read_only", "has connection options after the file"),
            ("duckdb:///:memory:?x=1", "has connection options after the file"),
            ("duckdb:///x.duckdb#frag", "has connection options after the file"),
        ],
    )
    def test_a_duckdb_url_is_a_file_and_nothing_else(self, url, message):
        """Found by a reviewer: a host became a folder, options became part of
        the file's name, and a user name passed."""
        with pytest.raises(ValueError, match=message):
            validate_sources({"local": {"backend": "duckdb", "url": url}}, Path("/p"))

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


    def test_an_error_only_running_can_find_is_polars_and_the_page_survives(self, pipeline):
        """Found by a reviewer: DESCRIBE binds, count(*) prunes the cast, and
        the cast fails when the first rows are collected. The site is still
        built, and the page says what happened."""
        from chartbook import index
        from chartbook.writers.sphinx import _source_glimpse

        broken = {**RATES}
        broken["dataframes"] = {
            **RATES["dataframes"],
            "bad": {"source": "local", "query": "select cast(d as int) as di from curve", "docs": "d"},
        }
        _manifest(pipeline, broken)
        frame = data.load("bad", project_dir=pipeline)  # binds: no error yet
        # Polars wraps it as ComputeError on some versions and lets DuckDB's own
        # exception through on others; the message is DuckDB's either way
        with pytest.raises((pl.exceptions.ComputeError, duckdb.Error), match="Conversion Error"):
            frame.collect()
        built = index.build_index(load_manifest(pipeline))
        record = next(r for r in built["records"] if r["id"] == "acme/rates:bad")
        glimpse = _source_glimpse(record, pipeline)
        assert glimpse.startswith("A query in source 'local' (duckdb). It could not be read when the site was built:")
        assert "Conversion" in glimpse

    def test_a_rebuilt_file_is_seen_and_a_dropped_frame_lets_a_writer_in(self, pipeline):
        """Found by a reviewer: a connection kept for the process read stale data
        and held the file's lock. Now each load opens the file afresh, and the
        frame it returns keeps its own connection only while it lives."""
        import gc

        first = data.load("curve", project_dir=pipeline).collect()
        assert first.height == 2
        gc.collect()
        writer = duckdb.connect(str(pipeline / "_data" / "local.duckdb"))
        writer.sql("insert into curve values ('2024-01-03', 1.2, 4.4)")
        writer.close()
        assert data.load("curve", project_dir=pipeline).collect().height == 3


class TestRef:
    def test_a_file_a_table_and_a_query(self, pipeline):
        assert data.ref("rates", project_dir=pipeline) == (
            f"read_parquet('{pipeline / '_data' / 'rates.parquet'}')"
        )
        assert data.ref("curve", project_dir=pipeline) == '"curve"'
        assert data.ref("slopes", project_dir=pipeline) == (
            "(\nselect d, y10 - y02 as slope from curve order by d\n)"
        )

    def test_a_query_that_ends_with_a_semicolon_or_a_comment_still_loads(self, pipeline):
        """Found by a reviewer: spliced as `(sql)`, a trailing `;` or `--` broke load(); then both at once did."""
        with_more = {**RATES}
        with_more["dataframes"] = {
            **RATES["dataframes"],
            "semi": {"source": "local", "query": "select d from curve; ", "docs": "d"},
            "noted": {"source": "local", "query": "select d from curve -- the dates", "docs": "d"},
            "both": {"source": "local", "query": "select d from curve; -- the dates", "docs": "d"},
            "quoted": {"source": "local", "query": "select d, 'a;b -- kept' as s from curve; -- a note; and more", "docs": "d"},
            # Found by a second reviewer: DuckDB's other quotes
            "dollars": {"source": "local", "query": "select d, $$ -- x; $$ as s from curve", "docs": "d"},
            "dollars_semi": {"source": "local", "query": "select d, $$it's$$ as s from curve;", "docs": "d"},
            "tagged": {"source": "local", "query": "select d, $q$ a; -- b $q$ as s from curve; -- note", "docs": "d"},
            "escaped": {"source": "local", "query": "select d, e'don\\'t' as s from curve;", "docs": "d"},
        }
        _manifest(pipeline, with_more)
        for name in ("semi", "noted", "both", "quoted", "dollars", "dollars_semi", "tagged", "escaped"):
            assert data.load(name, project_dir=pipeline).collect().height == 2, name
            assert data.sql(f"select count(*) n from {{{name}}}", project_dir=pipeline).collect()["n"][0] == 2, name
        assert data.ref("semi", project_dir=pipeline) == "(\nselect d from curve\n)"
        assert data.ref("both", project_dir=pipeline) == "(\nselect d from curve\n)"
        first = {name: data.load(name, project_dir=pipeline).collect()["s"][0] for name in ("quoted", "dollars", "dollars_semi", "tagged", "escaped")}
        assert first == {"quoted": "a;b -- kept", "dollars": " -- x; ", "dollars_semi": "it's", "tagged": " a; -- b ", "escaped": "don't"}

    @pytest.mark.parametrize(
        ("query", "inside"),
        [
            ("select 1;", "select 1"),
            ("select 1 -- a comment", "select 1"),
            ("select 1; -- a comment", "select 1"),
            ("select 1 -- a comment\n;", "select 1"),
            ("select 1; -- one\n-- two", "select 1"),
            ("select 'a;b' from t;", "select 'a;b' from t"),
            ("select '--x' from t;", "select '--x' from t"),
            ('select "a;b" from t; -- c', 'select "a;b" from t'),
            ("select 1 /* ; */;", "select 1 /* ; */"),
            ("select 'open; -- x", "select 'open; -- x"),  # a string left open: the comment stays, and the engine says so
            ("select 'open; -- x;", "select 'open; -- x"),  # the semicolon goes whatever the scanner makes of the rest
            # DuckDB's other quotes, found by a second reviewer
            ("select $$ -- x $$ as s", "select $$ -- x $$ as s"),
            ("select $$it's$$ as s;", "select $$it's$$ as s"),
            ("select $q$ a; -- b $q$ as s; -- note", "select $q$ a; -- b $q$ as s"),
            ("select e'don\\'t' as s;", "select e'don\\'t' as s"),
            ("select E'a\\\\' -- c", "select E'a\\\\'"),  # an escaped backslash, then a comment
            ("select e'a\\' -- c'", "select e'a\\' -- c'"),  # an escaped quote: the comment is inside the string
            ("select 1 where e='x' -- c", "select 1 where e='x'"),  # an e before a quote is a letter when a word ends in it
            # Databricks: a backslash escapes a quote, and backticks quote an identifier
            ("select 'don\\'t' as s;", "select 'don\\'t' as s"),
            ("select 'don\\'t' as s -- note", "select 'don\\'t' as s -- note"),  # left in place: the engine reads it as the comment it is
            ("select `a;b` from t; -- c", "select `a;b` from t"),
            ("select `a -- b` from t;", "select `a -- b` from t"),
        ],
    )
    def test_a_sub_select_drops_what_ends_a_query_and_keeps_what_is_quoted(self, query, inside):
        assert backends.subselect(query) == f"(\n{inside}\n)"

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

    def test_a_literal_brace_is_written_twice(self, pipeline):
        """Found by a reviewer: DuckDB's own {'a': 1} syntax, and braces in
        strings, collided with the reference grammar."""
        got = data.sql(
            "select {{'a': 1}} as s, '{{x}}' as t, count(*) as n from {curve}", project_dir=pipeline
        ).collect()
        assert got["s"][0] == {"a": 1} and got["t"][0] == "{x}" and got["n"][0] == 2
        with pytest.raises(ValueError, match="A doubled brace"):
            data.sql("select {{'a': 1}} as s", project_dir=pipeline)

    def test_sql_over_files_runs_in_an_engine_of_its_own(self, pipeline):
        """Found by a reviewer: files-only SQL shared the one in-memory
        connection with every :memory: source, so a table a user made there
        showed up in it."""
        with_memory = {**RATES}
        with_memory["sources"] = {**RATES["sources"], "mem": {"backend": "duckdb", "url": "duckdb:///:memory:"}}
        with_memory["dataframes"] = {
            **RATES["dataframes"],
            "answer": {"source": "mem", "table": "t", "docs": "What was put in the memory source."},
        }
        _manifest(pipeline, with_memory)
        data.connect("mem", project_dir=pipeline).sql("create table t as select 42 as answer")
        # A :memory: source holds what is put in it, for the process
        assert data.load("answer", project_dir=pipeline).collect()["answer"][0] == 42
        # ...and SQL over files alone does not see it
        with pytest.raises(BackendError, match="Table with name t does not exist"):
            data.sql("select answer from t, {rates}", project_dir=pipeline)
        assert DuckDBBackend.scratch().connect() is not DuckDBBackend.scratch().connect()

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

    @staticmethod
    def _other_file(directory: Path, label: str) -> Path:
        other = directory / f"{label}.duckdb"
        con = duckdb.connect(str(other))
        con.sql(f"create table curve as select '{label}' as d, 0.0 as y02, 0.0 as y10")
        con.close()
        return other

    def test_the_machine_url_is_what_opens_the_source(self, pipeline, tmp_path, monkeypatch):
        """Found by a reviewer: the chain was documented and never called."""
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path / "home")
        (tmp_path / "home").mkdir()
        from_file = self._other_file(tmp_path, "FROM-FILE")
        (tmp_path / "home" / "sources.toml").write_text(f'[local]\nurl = "duckdb:///{from_file}"\n', encoding="utf-8")
        assert data.load("curve", project_dir=pipeline).collect()["d"].to_list() == ["FROM-FILE"]
        assert data.connect("local", project_dir=pipeline).sql("select d from curve").fetchone() == ("FROM-FILE",)
        from_env = self._other_file(tmp_path, "FROM-ENV")
        monkeypatch.setenv("CHARTBOOK_SOURCE_LOCAL_URL", f"duckdb:///{from_env}")
        assert data.load("curve", project_dir=pipeline).collect()["d"].to_list() == ["FROM-ENV"]
        assert resolve("curve", start_dirs=[pipeline]).url == f"duckdb:///{from_env}"
        # The index describes what the machine opens, and records the manifest's url
        record = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"]}["acme/rates:curve"]
        assert record["row_count"] == 1 and "FROM-ENV" not in json.dumps(record)

    def test_a_machine_url_for_another_engine_is_refused(self, pipeline, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_LOCAL_URL", "postgres://warehouse/db")
        with pytest.raises(ValueError, match="begins with postgres:// and the backend is duckdb"):
            load_manifest(pipeline)

    def test_the_hint_names_the_variable_as_a_person_would_write_it(self):
        with pytest.raises(ValueError, match=r"CHARTBOOK_SOURCE_<NAME>_URL"):
            backends.check_url("duckdb://user:pw@host/x", "duckdb", "[sources.x]")

    def test_the_environment_wins(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WARE_HOUSE_URL", "duckdb:///from-env.db")
        assert backends.source_url("ware-house", "duckdb:///manifest.db") == "duckdb:///from-env.db"
        assert backends.source_env_var("ware-house") == "CHARTBOOK_SOURCE_WARE_HOUSE_URL"

    def test_then_sources_toml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        (tmp_path / "sources.toml").write_text('[local]\nurl = "duckdb:///from-file.db"\n', encoding="utf-8")
        assert backends.source_url("local", "duckdb:///manifest.db") == "duckdb:///from-file.db"
        assert backends.source_url("other", "duckdb:///manifest.db") == "duckdb:///manifest.db"

    def test_then_the_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        assert backends.source_url("local", "duckdb:///manifest.db") == "duckdb:///manifest.db"

    def test_a_sources_file_that_cannot_be_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: tmp_path)
        (tmp_path / "sources.toml").write_text("not = toml =", encoding="utf-8")
        with pytest.raises(BackendError, match="Cannot read"):
            backends.source_url("local", "duckdb:///manifest.db")


class TestIndexAndSite:
    def test_the_records_say_where_each_dataframe_is(self, pipeline):
        built = index.build_index(load_manifest(pipeline))
        records = {r["id"]: r for r in built["records"] if r["kind"] == "Dataframe"}
        table = records["acme/rates:curve"]
        assert {k: v for k, v in table["location"].items() if k != "modified_at"} == {
            "kind": "table", "source": "local", "backend": "duckdb", "identifier": "curve",
            "url": "duckdb:///./_data/local.duckdb",  # the manifest's public url, for a reader to open the engine
        }
        assert table["location"]["modified_at"].endswith("Z")  # the DuckDB file is a file
        assert "content_hash" not in table and table["definition_hash"].startswith("sha256:")
        assert table["row_count"] == 2 and [c["name"] for c in table["columns"]] == ["d", "y02", "y10"]
        assert table["columns"][1]["dtype"] == "DECIMAL(2,1)"  # DuckDB's name, as the engine has it
        query = records["acme/rates:slopes"]
        assert query["location"]["kind"] == "query" and query["location"]["sql"].startswith("select d,")
        assert "source" not in query and "query" not in query  # in the location, not beside it
        file = records["acme/rates:rates"]
        assert file["location"]["kind"] == "file" and file["content_hash"].startswith("sha256:")
        schema = json.loads(index.schema_path("Dataframe").read_text(encoding="utf-8"))
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

    def test_a_table_that_is_not_there_is_said_so_when_the_index_is_built(self, pipeline):
        """Found by a reviewer: a typo in `table` left the record silently bare."""
        typo = {**RATES}
        typo["dataframes"] = {**RATES["dataframes"], "curve": {"source": "local", "table": "curv", "docs": "d"}}
        _manifest(pipeline, typo)
        with pytest.warns(UserWarning, match=r"\[dataframes.curve\]: the engine could not describe it.*curv"):
            built = index.build_index(load_manifest(pipeline))
        (record,) = [r for r in built["records"] if r["id"] == "acme/rates:curve"]
        assert "columns" not in record

    def test_the_same_table_in_two_sources_has_two_definition_hashes(self, pipeline, tmp_path):
        """Found by a reviewer: the hash left out where the table is."""
        other = tmp_path / "other.duckdb"
        con = duckdb.connect(str(other))
        con.sql("create table curve as select '2020-01-01' as d, 0.0 as y02, 0.0 as y10")
        con.close()
        two = {**RATES}
        two["sources"] = {**RATES["sources"], "other": {"backend": "duckdb", "url": f"duckdb:///{other}"}}
        two["dataframes"] = {
            **RATES["dataframes"],
            "curve_elsewhere": {"source": "other", "table": "curve", "docs": "d"},
        }
        _manifest(pipeline, two)
        records = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"]}
        assert records["acme/rates:curve"]["definition_hash"] != records["acme/rates:curve_elsewhere"]["definition_hash"]

    def test_the_page_dates_the_data_and_shows_a_long_query_whole(self, pipeline, monkeypatch):
        """Found by a reviewer: the dates were None, and a query with a newline
        or a pipe broke the table it was printed in."""
        dated = {**RATES}
        dated["dataframes"] = {
            **RATES["dataframes"],
            "slopes": {
                "source": "local",
                "query": "select d,\n  y10 || '-' || y02 as pair\nfrom curve",
                "date_col": "d",
                "docs": "A query.",
            },
        }
        _manifest(pipeline, dated)
        monkeypatch.chdir(pipeline)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        page = (pipeline / "_docs" / "cb" / "dataframes" / "acme--rates" / "slopes.md").read_text(encoding="utf-8")
        assert "| Data available up to (min)     | 2024-01-01" in page
        assert "| Data available up to (max)     | 2024-01-02" in page
        assert "| Query                          | in source `local`; the SQL is below" in page
        assert "```sql\nselect d,\n  y10 || '-' || y02 as pair\nfrom curve\n```" in page

    def test_a_source_that_is_not_built_yet_has_no_columns(self, pipeline):
        (pipeline / "_data" / "local.duckdb").unlink()
        with pytest.warns(UserWarning, match=r"\[dataframes.curve\]: the engine could not describe it"):
            built = index.build_index(load_manifest(pipeline))
        (table,) = [r for r in built["records"] if r["id"] == "acme/rates:curve"]
        assert "columns" not in table and "definition_hash" not in table
        assert table["location"]["kind"] == "table"

    def test_the_page_describes_the_table(self, pipeline, monkeypatch):
        monkeypatch.chdir(pipeline)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        page = (pipeline / "_docs" / "cb" / "dataframes" / "acme--rates" / "slopes.md").read_text(encoding="utf-8")
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
    def test_a_table_pinned_from_a_repository_is_not_there_and_says_what_writes_it_out(self, pipeline, tmp_path):
        """A pin from a repository takes the files it commits, and a table has none;
        a snapshot writes it out as parquet, and the pin, `--frozen` and a reference to it say so."""
        from chartbook import lock
        from chartbook.errors import AssetNotPinnedError
        from chartbook.resolve import FileLocation, declared_files
        from tests.test_model_versions import _commit

        assert [str(ref) for ref, _, _ in declared_files(pipeline)] == ["rates"]
        _commit(pipeline)  # its data with it
        downstream = _manifest(
            tmp_path / "down",
            {"project": {"id": "acme/down"}, "dependencies": {"rates": {"git": str(pipeline)}}},
        )
        report = lock.pin(downstream)
        said = [e for e in report.events if e.status == "not_built" and e.asset == "rates:curve"]
        assert said and "is not taken from a repository; `chartbook snapshot` there writes it out" in said[0].detail
        assert any("has no pinned copy: a pin from a repository" in p.message for p in lock.verify(downstream).problems)
        assert isinstance(resolve("rates:rates", start_dirs=[downstream]), FileLocation)
        with pytest.raises(AssetNotPinnedError, match="is a table in a source of the pipeline 'rates' and has no pinned copy: a pin from a repository takes no table") as e:
            resolve("rates:curve", start_dirs=[downstream])
        assert e.value.reason == "not_built"
        with pytest.raises(AssetNotPinnedError, match="is a query in a source"):
            resolve("rates:slopes", start_dirs=[downstream])
        with pytest.raises(AssetNotPinnedError, match="had no dataframe named 'nope'"):
            resolve("rates:nope", start_dirs=[downstream])

    def test_a_tables_pin_from_a_snapshot_stays_when_the_dependency_becomes_a_repository(self, pipeline, tmp_path):
        """A repository has no table to take: the pin a snapshot wrote out is kept, not dropped."""
        from chartbook import lock, snapshot
        from tests.test_model_versions import _commit

        _commit(pipeline)
        snapshot.make(pipeline)
        downstream = _manifest(
            tmp_path / "down",
            {"project": {"id": "acme/down"}, "dependencies": {"rates": {"path": "../rates"}}},
        )
        lock.pin(downstream)
        table = lock.read_lock(downstream).assets["rates:curve"]
        assert table["content_hash"]
        _manifest(downstream, {"project": {"id": "acme/down"}, "dependencies": {"rates": {"git": str(pipeline)}}})
        report = lock.update(downstream)
        assert lock.read_lock(downstream).assets["rates:curve"] == table
        assert ("rates:curve", "kept") in [(e.asset, e.status) for e in report.events]

    def test_a_catalog_reaches_a_table_of_a_pipeline_it_lists(self, pipeline, tmp_path):
        """Found by a reviewer: the catalog path blamed a missing `path`."""
        (tmp_path / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"acme/rates": {"path": "rates"}}}), encoding="utf-8"
        )
        location = resolve("curve", pipeline="acme/rates", catalog_path=tmp_path / "chartbook.toml")
        assert isinstance(location, TableLocation) and location.identifier == "curve"
        frame = data.load("acme/rates", "slopes", catalog_path=tmp_path / "chartbook.toml")
        assert frame.collect().height == 2
