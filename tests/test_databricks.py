"""Tests for the Databricks backend: ``chartbook.backends.databricks``.

A source in a Databricks SQL warehouse, read through the Databricks SQL
connector. The connector here is a stand-in over DuckDB
(``tests/mocked_databricks.py``) that takes the arguments the real one
documents, so these tests say what is sent where: above all, that this
machine's token goes to no host but the one this machine names.
"""

import sys
import warnings
from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import backends, data, index
from chartbook.backends import BackendError, open_backend
from chartbook.backends.databricks import DatabricksBackend, connection_for, parse_url
from chartbook.manifest import load_manifest, validate_sources
from chartbook.resolve import QueryLocation, TableLocation
from tests import mocked_databricks
from tests.mocked_databricks import Warehouse

HOST = "dbc-test.cloud.databricks.com"
HTTP_PATH = "/sql/1.0/warehouses/abc"
TOKEN = "dapi-test"
PUBLIC_URL = f"databricks://{HOST}?http_path={HTTP_PATH}&catalog=workspace"


@pytest.fixture(autouse=True)
def _no_databricks_settings(monkeypatch):
    """Nothing of the machine running the tests: no workspace, no token, no machine URL."""
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_HTTP_PATH", "CHARTBOOK_SOURCE_WAREHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def warehouse(monkeypatch):
    """A warehouse with one table, ``workspace.rates.curve``, and the connector installed to reach it."""
    found = Warehouse(host=HOST, http_path=HTTP_PATH, token=TOKEN)
    found.table(
        "workspace.rates.curve",
        "select d, y02::double as y02, y10::double as y10 from (values (date '2024-01-01', 1.0, 4.0), "
        "(date '2024-01-02', 1.1, 4.3), (date '2024-01-03', 1.2, 4.1)) t(d, y02, y10)",
    )
    return mocked_databricks.install(monkeypatch, found)


@pytest.fixture
def signed_in(monkeypatch):
    """This machine names the workspace and has a token for it."""
    monkeypatch.setenv("DATABRICKS_HOST", f"https://{HOST}/")
    monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)


def _pipeline(directory: Path, url: str = PUBLIC_URL) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "acme/rates"},
                "sources": {"warehouse": {"backend": "databricks", "url": url}},
                "dataframes": {
                    "rates": {"path": "./_data/rates.parquet", "docs": "A file."},
                    "curve": {"source": "warehouse", "table": "workspace.rates.curve", "docs": "A table."},
                    "slopes": {
                        "source": "warehouse",
                        "query": "select d, y10 - y02 as slope from workspace.rates.curve order by d",
                        "docs": "A query.",
                    },
                },
            }
        ), encoding="utf-8", newline="\n"
    )
    (directory / "README.md").write_text("# A pipeline\n", encoding="utf-8", newline="\n")
    (directory / "_data").mkdir(exist_ok=True)
    pl.DataFrame({"d": ["2024-01-01"], "r": [4.1]}).write_parquet(directory / "_data" / "rates.parquet")
    return directory


@pytest.fixture
def pipeline(tmp_path):
    return _pipeline(tmp_path.resolve() / "rates")


def _table(url=PUBLIC_URL, source="warehouse"):
    return TableLocation(source, "databricks", url, "workspace.rates.curve")


class TestTheURL:
    def test_its_parts(self):
        parsed = parse_url(f"databricks://{HOST.upper()}?http_path={HTTP_PATH}&catalog=main&schema=rates&auth=oauth")
        assert (parsed.host, parsed.http_path, parsed.catalog, parsed.schema, parsed.auth) == (
            HOST, HTTP_PATH, "main", "rates", "oauth"
        )
        assert parse_url("databricks://").host == ""
        assert parse_url(f"databricks://token:{TOKEN}@{HOST}").token == TOKEN
        assert TOKEN not in repr(parse_url(f"databricks://token:{TOKEN}@{HOST}"))

    @pytest.mark.parametrize(
        "url, says",
        [
            (f"databricks://{HOST}/sql/1.0/warehouses/abc", "goes after ?"),
            (f"databricks://{HOST}:443?http_path=x", "without a port"),
            (f"databricks://{HOST}?warehouse=x", "and nothing else"),
            ("databricks://localhost?http_path=x", "is a host name"),
            (f"databricks://{HOST}?catalog=a&catalog=b", "more than once"),
            (f"databricks://{HOST}?http_path=x#y", "nothing after #"),
            (f"databricks://{HOST}?auth=password", "auth is token or oauth"),
            ("databricks://dbc_x\x1b.example.com?http_path=x", "is a host name"),
            ("databricks://dbc[x.example.com?http_path=x", "not a url"),
            ("duckdb:///x.duckdb", "begins with databricks://"),
        ],
    )
    def test_what_it_refuses(self, url, says):
        with pytest.raises(ValueError, match=says):
            parse_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "databricks://dapiSECRET/@host.example.com?http_path=/x",
            "databricks://host.example.com?dapiSECRET=1",
            "databricks://host.example.com?auth=dapiSECRET",
            "databricks://host.example.com/dapiSECRET",
        ],
    )
    def test_a_message_repeats_nothing_of_the_url(self, url, tmp_path):
        with pytest.raises(ValueError) as error:
            validate_sources({"warehouse": {"backend": "databricks", "url": url}}, tmp_path)
        assert "dapiSECRET" not in str(error.value)

    @pytest.mark.parametrize(
        "url", [" databricks://dapiSECRET@host.example.com", "databricks:/dapiSECRET@host.example.com", "databricks:dapiSECRET@h"]
    )
    def test_a_url_that_does_not_begin_as_one_is_not_repeated(self, url, tmp_path):
        with pytest.raises(ValueError) as error:
            validate_sources({"warehouse": {"backend": "databricks", "url": url}}, tmp_path)
        assert "dapiSECRET" not in str(error.value)

    @pytest.mark.parametrize("written", ["https:dbc-x.cloud.databricks.com", "https//dbc-x.cloud.databricks.com", "dbc-x.cloud.databricks.com:abc", "my_ws.internal", "localhost"])
    def test_what_is_not_a_workspaces_address(self, written):
        from chartbook.backends.databricks import host_of

        assert host_of(written) == ""

    def test_a_manifest_with_a_token_in_its_url_does_not_load(self, tmp_path):
        with pytest.raises(ValueError, match="carries a user name or a password"):
            validate_sources(
                {"warehouse": {"backend": "databricks", "url": f"databricks://token:{TOKEN}@{HOST}"}}, tmp_path
            )

    def test_a_manifest_url_it_cannot_read_does_not_load(self, tmp_path):
        with pytest.raises(ValueError, match=r"\[sources.warehouse\]: a Databricks url names the host without a port"):
            validate_sources({"warehouse": {"backend": "databricks", "url": f"databricks://{HOST}:8443"}}, tmp_path)

    def test_the_manifest_url_is_what_a_location_carries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token:{TOKEN}@{HOST}?http_path={HTTP_PATH}")
        sources = validate_sources({"warehouse": {"backend": "databricks", "url": PUBLIC_URL}}, tmp_path)
        assert sources["warehouse"]["_resolved_url"] == PUBLIC_URL

    def test_a_machine_url_for_another_engine_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", "duckdb:///x.duckdb")
        with pytest.raises(ValueError, match="begins with duckdb://"):
            validate_sources({"warehouse": {"backend": "databricks", "url": PUBLIC_URL}}, tmp_path)


class TestWhereTheTokenGoes:
    def test_the_engines_own_variables(self, signed_in):
        connection = connection_for("warehouse", PUBLIC_URL)
        assert (connection.host, connection.http_path, connection.catalog, connection.token) == (
            HOST, HTTP_PATH, "workspace", TOKEN
        )
        assert TOKEN not in repr(connection)

    def test_a_manifest_naming_another_host_never_gets_the_token(self, signed_in, warehouse):
        backend = DatabricksBackend(f"databricks://evil.example.com?http_path={HTTP_PATH}", "warehouse")
        with pytest.raises(BackendError) as error:
            backend.connect()
        assert "names the workspace evil.example.com" in str(error.value)
        assert f"this machine's, from DATABRICKS_HOST, is {HOST}" in str(error.value)
        assert TOKEN not in str(error.value)
        assert warehouse.connections == []

    def test_with_no_host_of_its_own_the_manifests_is_not_taken(self, monkeypatch, warehouse):
        monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)
        with pytest.raises(BackendError, match=f"names no workspace \\({HOST}\\). Set DATABRICKS_HOST"):
            DatabricksBackend(PUBLIC_URL, "warehouse").connect()
        assert warehouse.connections == []

    def test_the_machines_url_for_the_source(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token:{TOKEN}@{HOST}?http_path=/other")
        connection = connection_for("warehouse", PUBLIC_URL)
        assert (connection.host, connection.http_path, connection.token) == (HOST, "/other", TOKEN)

    def test_the_machines_url_from_sources_toml(self, tmp_path):
        settings = backends.get_global_config_dir() / backends.SOURCES_FILE
        assert not settings.is_relative_to(Path.home() / ".chartbook")  # not the real one; a temporary folder may be under home (Windows)
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(tomli_w.dumps({"warehouse": {"url": f"databricks://token:{TOKEN}@{HOST}"}}), encoding="utf-8", newline="\n")
        connection = connection_for("warehouse", PUBLIC_URL)
        assert (connection.host, connection.http_path, connection.token) == (HOST, HTTP_PATH, TOKEN)

    def test_a_machine_url_for_another_host_than_the_manifests_is_refused(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token:{TOKEN}@other.example.com")
        with pytest.raises(BackendError, match="from CHARTBOOK_SOURCE_WAREHOUSE_URL or ~/.chartbook/sources.toml, is other.example.com"):
            connection_for("warehouse", PUBLIC_URL)

    def test_a_host_the_machine_writes_wrong_keeps_its_token_to_itself(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "https://my_ws.internal")
        monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://{HOST}?http_path={HTTP_PATH}")
        with pytest.raises(BackendError, match="has no token"):
            connection_for("warehouse", PUBLIC_URL)

    def test_the_environments_token_is_not_sent_to_another_host_the_machine_names(self, monkeypatch, signed_in):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://other.example.com?http_path={HTTP_PATH}")
        with pytest.raises(BackendError, match="has no token"):
            connection_for("warehouse", f"databricks://?http_path={HTTP_PATH}")

    def test_a_token_in_the_manifest_or_a_record_is_never_used(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", HOST)
        with pytest.raises(BackendError, match="has no token"):
            connection_for("warehouse", f"databricks://token:planted@{HOST}?http_path={HTTP_PATH}")

    def test_no_token_says_how_to_give_one(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", HOST)
        with pytest.raises(BackendError) as error:
            connection_for("warehouse", PUBLIC_URL)
        for said in ("DATABRICKS_TOKEN", "Access tokens", "CHARTBOOK_SOURCE_WAREHOUSE_URL", "auth=oauth"):
            assert said in str(error.value)

    def test_no_warehouse_says_where_to_find_it(self, signed_in, monkeypatch):
        with pytest.raises(BackendError, match="names no SQL warehouse"):
            connection_for("warehouse", f"databricks://{HOST}")
        monkeypatch.setenv("DATABRICKS_HTTP_PATH", HTTP_PATH)
        assert connection_for("warehouse", f"databricks://{HOST}").http_path == HTTP_PATH

    def test_oauth_signs_in_through_the_browser_once_for_the_process(self, monkeypatch, warehouse):
        monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)  # the machine's url says otherwise, and wins
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://{HOST}?auth=oauth")
        DatabricksBackend(PUBLIC_URL, "warehouse").connect().close()
        DatabricksBackend(PUBLIC_URL, "warehouse").connect().close()
        first, second = warehouse.connections
        assert first.arguments["auth_type"] == "databricks-oauth"
        assert first.arguments["access_token"] is None
        # One store of sign-ins for the process: the browser is asked once
        assert first.arguments["experimental_oauth_persistence"] is second.arguments["experimental_oauth_persistence"]

    def test_a_manifest_does_not_say_how_to_sign_in(self, tmp_path):
        with pytest.raises(ValueError, match="the machine's to say: put auth=oauth in CHARTBOOK_SOURCE_<NAME>_URL"):
            validate_sources({"warehouse": {"backend": "databricks", "url": PUBLIC_URL + "&auth=oauth"}}, tmp_path)

    def test_a_record_saying_oauth_does_not_override_the_machines_token(self, signed_in, warehouse):
        DatabricksBackend(PUBLIC_URL + "&auth=oauth", "warehouse").connect().close()
        (connection,) = warehouse.connections
        assert connection.arguments["access_token"] == TOKEN
        assert "auth_type" not in connection.arguments

    @pytest.mark.parametrize(
        "written", [HOST, f"https://{HOST}", f"https://{HOST}/", f"{HOST}:443", f"https://{HOST}/?o=123", HOST.upper() + "."]
    )
    def test_the_ways_a_workspaces_address_is_written(self, monkeypatch, written):
        monkeypatch.setenv("DATABRICKS_HOST", written)
        monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)
        assert connection_for("warehouse", PUBLIC_URL).host == HOST

    def test_a_host_that_is_not_one_is_said(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "https://exa mple.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)
        with pytest.raises(BackendError, match="DATABRICKS_HOST is not a workspace's address"):
            connection_for("warehouse", PUBLIC_URL)

    @pytest.mark.parametrize(
        "url",
        [
            f"databricks://dapiLEAKED0123@{HOST}?http_path={HTTP_PATH}",
            f"databricks://token:dapiLEAKED0123@{HOST}?http_path={HTTP_PATH}",
            f"databricks://evil.com\\@{HOST}?http_path={HTTP_PATH}",
        ],
    )
    def test_a_manifest_url_naming_a_user_does_not_load_and_is_not_repeated(self, tmp_path, url):
        with pytest.raises(ValueError) as error:
            validate_sources({"warehouse": {"backend": "databricks", "url": url}}, tmp_path)
        assert "user" in str(error.value)
        assert "dapiLEAKED0123" not in str(error.value)

    def test_a_machine_url_the_parser_refuses_is_not_repeated(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token\uff1adapiSECRET123@{HOST}?http_path=/x")
        with pytest.raises(BackendError) as error:
            connection_for("warehouse", PUBLIC_URL)
        assert "not a url ChartBook can read" in str(error.value)
        assert "dapiSECRET123" not in str(error.value)

    def test_the_connectors_error_never_carries_the_token(self, signed_in, monkeypatch):
        def refuse(**arguments):
            raise RuntimeError(f"refused {arguments['access_token']}")

        sql = type(sys)("databricks.sql")
        sql.connect = refuse
        package = type(sys)("databricks")
        package.sql = sql
        monkeypatch.setitem(sys.modules, "databricks", package)
        monkeypatch.setitem(sys.modules, "databricks.sql", sql)
        with pytest.raises(BackendError) as error:
            DatabricksBackend(PUBLIC_URL, "warehouse").connect()
        assert TOKEN not in str(error.value) and "refused <token>" in str(error.value)
        # Nor is the connector's error, which holds it, carried along
        assert error.value.__context__ is None and error.value.__cause__ is None

    def test_what_the_connector_is_given(self, signed_in, warehouse):
        DatabricksBackend(PUBLIC_URL, "warehouse").connect().close()
        (connection,) = warehouse.connections
        assert connection.arguments == {
            "server_hostname": HOST,
            "http_path": HTTP_PATH,
            "access_token": TOKEN,
            "catalog": "workspace",
            "user_agent_entry": "chartbook",
        }

    def test_a_wrong_token_is_the_warehouses_message(self, monkeypatch, warehouse):
        monkeypatch.setenv("DATABRICKS_HOST", HOST)
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-wrong")
        with pytest.raises(BackendError, match=f"Cannot connect to the Databricks workspace {HOST}: Invalid access token"):
            DatabricksBackend(PUBLIC_URL, "warehouse").connect()


class TestTheDriver:
    def test_without_it_the_message_names_the_extra(self, signed_in, monkeypatch):
        monkeypatch.setitem(sys.modules, "databricks", None)
        with pytest.raises(BackendError, match=r"pip install chartbook\[databricks\]"):
            DatabricksBackend(PUBLIC_URL, "warehouse").connect()

    def test_it_is_a_backend_a_manifest_may_name(self):
        assert backends.backend_class("databricks") is DatabricksBackend
        assert "databricks" in backends.backend_names()

    def test_a_backend_nothing_provides_lists_the_ones_there_are(self, tmp_path):
        with pytest.raises(ValueError, match="The backends are: databricks, duckdb"):
            validate_sources({"wh": {"backend": "snowflake", "url": "snowflake://acct"}}, tmp_path)

    def test_a_record_naming_a_backend_nothing_provides_is_a_backend_error(self):
        with pytest.raises(BackendError, match="in a snowflake engine, and nothing here provides one"):
            open_backend("snowflake", "snowflake://acct", "wh")

    def test_an_install_without_the_entry_point_is_told_to_reinstall(self, monkeypatch, tmp_path):
        monkeypatch.setattr(backends, "backend_class", lambda name: None)
        with pytest.raises(BackendError, match=r"reinstalling ChartBook \(pip install chartbook\[databricks\]\)"):
            open_backend("databricks", PUBLIC_URL, "warehouse")
        with pytest.raises(ValueError, match=r"reinstalling ChartBook \(pip install chartbook\[databricks\]\)"):
            validate_sources({"warehouse": {"backend": "databricks", "url": PUBLIC_URL}}, tmp_path)

    def test_a_build_of_files_from_a_store_reads_no_machine_url(self, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_SOURCE_WAREHOUSE_URL", f"databricks://token:{TOKEN}@{HOST}")
        assert backends.machine_source_url("warehouse")
        monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
        assert backends.machine_source_url("warehouse") is None

    def test_a_build_of_files_from_a_store_gets_no_credentials(self, monkeypatch):
        from chartbook.versions import _without_credentials

        kept = _without_credentials(
            {"DATABRICKS_TOKEN": "t", "DATABRICKS_HOST": "h", "CHARTBOOK_SOURCE_W_URL": "u", "PATH": "/bin", "CHARTBOOK_STORE": "s"}
        )
        assert kept == {"PATH": "/bin", "CHARTBOOK_STORE": "s"}

    def test_not_in_a_build_of_files_from_a_store(self, signed_in, warehouse, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
        with pytest.raises(BackendError, match="not read in a build of files from a store"):
            DatabricksBackend(PUBLIC_URL, "warehouse").connect()
        assert warehouse.connections == []


class TestReading:
    def test_a_table(self, pipeline, signed_in, warehouse):
        frame = data.load("curve", project_dir=pipeline)
        assert isinstance(frame, pl.LazyFrame)
        assert frame.collect()["y10"].to_list() == [4.0, 4.3, 4.1]
        assert warehouse.queries[0] == "select * from (\nselect * from `workspace`.`rates`.`curve`\n) limit 0"
        assert warehouse.open(encoding="utf-8") == []

    def test_nothing_is_read_until_it_is_collected(self, pipeline, signed_in, warehouse):
        frame = data.load("curve", project_dir=pipeline)
        assert len(warehouse.queries) == 1  # the columns, and no rows
        assert frame.collect_schema().names() == ["d", "y02", "y10"]
        frame.collect()
        assert warehouse.queries[-1] == "select * from `workspace`.`rates`.`curve`"

    def test_a_head_asks_for_that_many_rows(self, pipeline, signed_in, warehouse):
        assert data.load("curve", project_dir=pipeline).head(2).collect().height == 2
        assert warehouse.queries[-1].endswith(") limit 2")

    def test_a_head_of_a_filter_is_the_filtered_rows(self, pipeline, signed_in, warehouse):
        frame = data.load("curve", project_dir=pipeline).filter(pl.col("y10") > 4.05).head(1)
        assert frame.collect()["y10"].to_list() == [4.3]
        assert "limit" not in warehouse.queries[-1]

    def test_an_error_only_running_finds_carries_the_warehouses_message(self, pipeline, signed_in, warehouse, monkeypatch):
        frame = data.load("curve", project_dir=pipeline)
        warehouse.duck.execute("drop table workspace.rates.curve")
        # Polars' ComputeError, or the BackendError itself, by Polars version
        with pytest.raises((pl.exceptions.ComputeError, BackendError)) as error:
            frame.collect()
        assert "Catalog Error" in str(error.value) and "curve" in str(error.value)
        assert warehouse.open(encoding="utf-8") == []

    def test_an_empty_result_without_its_schema_asks_for_a_row(self, pipeline, signed_in, warehouse):
        warehouse.empty_without_schema = True
        frame = data.load("curve", project_dir=pipeline)
        assert frame.collect_schema().names() == ["d", "y02", "y10"]
        assert frame.select("y10").collect()["y10"].to_list() == [4.0, 4.3, 4.1]
        assert warehouse.queries[1].endswith(") limit 1")

    def test_an_empty_result_without_its_schema_takes_the_types_the_warehouse_names(self, pipeline, signed_in, warehouse):
        warehouse.empty_without_schema = True
        frame = data.sql("select d, y10 from {curve} where y10 > 100", project_dir=pipeline)
        assert dict(frame.collect_schema()) == {"d": pl.Date, "y10": pl.Float64}
        assert frame.collect().height == 0

    def test_two_sources_are_two_engines_even_with_one_public_url(self, tmp_path, monkeypatch):
        prod = Warehouse(host="prod.cloud.databricks.com", http_path=HTTP_PATH, token="p")
        dev = Warehouse(host="dev.cloud.databricks.com", http_path=HTTP_PATH, token="d")
        for found in (prod, dev):
            found.table("workspace.rates.curve", "select 1 as a")
        mocked_databricks.install(monkeypatch, prod, dev)
        monkeypatch.setenv("CHARTBOOK_SOURCE_PROD_URL", f"databricks://token:p@{prod.host}?http_path={HTTP_PATH}")
        monkeypatch.setenv("CHARTBOOK_SOURCE_DEV_URL", f"databricks://token:d@{dev.host}?http_path={HTTP_PATH}")
        directory = tmp_path / "two"
        directory.mkdir()
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/two"},
                    "sources": {"prod": {"backend": "databricks", "url": "databricks://"}, "dev": {"backend": "databricks", "url": "databricks://"}},
                    "dataframes": {
                        "a": {"source": "prod", "table": "workspace.rates.curve", "docs": "d"},
                        "b": {"source": "dev", "table": "workspace.rates.curve", "docs": "d"},
                    },
                }
            ), encoding="utf-8", newline="\n"
        )
        with pytest.raises(ValueError, match="names dataframes in 2 sources, dev, prod"):
            data.sql("select * from {a} cross join {b}", project_dir=directory)
        assert data.sql("select count(*) as n from {a}", project_dir=directory).collect()["n"].to_list() == [1]
        assert prod.connections and not dev.connections

    def test_a_projection(self, pipeline, signed_in, warehouse):
        assert data.load("curve", project_dir=pipeline).select("y02").collect().columns == ["y02"]

    def test_a_query(self, pipeline, signed_in, warehouse):
        assert data.load("slopes", project_dir=pipeline, format="polars_eager")["slope"].round(2).to_list() == [3.0, 3.2, 2.9]

    def test_eager_and_pandas(self, pipeline, signed_in, warehouse):
        assert data.load("curve", project_dir=pipeline, format="pandas").shape == (3, 3)

    def test_a_table_that_is_not_there_is_refused_when_loaded(self, pipeline, signed_in, warehouse):
        manifest = (pipeline / "chartbook.toml").read_text(encoding="utf-8").replace("workspace.rates.curve\"", "workspace.rates.nope\"", 1)
        (pipeline / "chartbook.toml").write_text(manifest, encoding="utf-8", newline="\n")
        with pytest.raises(BackendError, match="nope"):
            data.load("curve", project_dir=pipeline)
        assert warehouse.open(encoding="utf-8") == []

    def test_sql_runs_in_the_warehouse(self, pipeline, signed_in, warehouse):
        frame = data.sql("select max(y10) as top from {curve}", project_dir=pipeline)
        assert frame.collect()["top"].to_list() == [4.3]
        assert warehouse.queries[-1] == "select max(y10) as top from `workspace`.`rates`.`curve`"

    def test_sql_naming_a_file_too_is_refused(self, pipeline, signed_in, warehouse):
        with pytest.raises(ValueError, match="names rates, a file of this machine, and dataframes in the source 'warehouse', a databricks engine"):
            data.sql("select * from {curve} join {rates} using (d)", project_dir=pipeline)
        assert warehouse.connections == []

    def test_ref_is_the_quoted_name(self, pipeline):
        assert data.ref("curve", project_dir=pipeline) == "`workspace`.`rates`.`curve`"

    def test_connect_is_the_connectors_connection(self, pipeline, signed_in, warehouse):
        connection = data.connect("warehouse", project_dir=pipeline)
        cursor = connection.cursor()
        cursor.execute("select count(*) from workspace.rates.curve")
        assert cursor.fetchone() == (3,)
        connection.close()

    def test_a_backtick_in_a_name_is_doubled(self):
        location = TableLocation("warehouse", "databricks", PUBLIC_URL, "a`b.c.d")
        assert DatabricksBackend(PUBLIC_URL, "warehouse").ref(location) == "`a``b`.`c`.`d`"


class TestDescribing:
    def test_columns_and_rows(self, signed_in, warehouse):
        columns, rows = DatabricksBackend(PUBLIC_URL, "warehouse").describe(_table())
        assert columns == [{"name": "d", "dtype": "date"}, {"name": "y02", "dtype": "double"}, {"name": "y10", "dtype": "double"}]
        assert rows == 3
        assert warehouse.open(encoding="utf-8") == []

    def test_span(self, signed_in, warehouse):
        first, last = DatabricksBackend(PUBLIC_URL, "warehouse").span(_table(), "d")
        assert (str(first)[:10], str(last)[:10]) == ("2024-01-01", "2024-01-03")

    def test_a_query_is_described_too(self, signed_in, warehouse):
        location = QueryLocation("warehouse", "databricks", PUBLIC_URL, "select d from workspace.rates.curve;")
        columns, rows = DatabricksBackend(PUBLIC_URL, "warehouse").describe(location)
        assert (columns, rows) == ([{"name": "d", "dtype": "date"}], 3)

    def test_the_index_records_the_columns(self, pipeline, signed_in, warehouse):
        records = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"]}
        curve = records["acme/rates:curve"]
        assert curve["location"] == {
            "kind": "table",
            "source": "warehouse",
            "backend": "databricks",
            "url": PUBLIC_URL,
            "identifier": "workspace.rates.curve",
        }
        assert [c["name"] for c in curve["columns"]] == ["d", "y02", "y10"]

    def test_with_no_token_the_index_is_built_without_columns(self, pipeline, warehouse, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", HOST)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            records = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"]}
        assert "columns" not in records["acme/rates:curve"]
        assert any("has no token" in str(w.message) for w in caught)
        assert all(TOKEN not in str(w.message) for w in caught)

    def test_the_page_shows_the_first_rows(self, pipeline, signed_in, warehouse):
        from chartbook.writers.sphinx import _source_glimpse

        record = {r["id"]: r for r in index.build_index(load_manifest(pipeline))["records"]}["acme/rates:curve"]
        glimpse = _source_glimpse(record, pipeline)
        assert glimpse.startswith("A table workspace.rates.curve in source 'warehouse' (databricks): 3 rows, 3 columns.")
        assert "First rows:" in glimpse
        assert warehouse.queries[-1].endswith(") limit 5")


class TestSnapshot:
    def test_a_warehouse_table_is_recorded_and_not_copied(self, pipeline, signed_in, warehouse, tmp_path):
        from chartbook.resolve import _read_raw_manifest
        from chartbook.snapshot import materialize_in_source
        from chartbook.store import FolderStore

        raw = _read_raw_manifest(pipeline / "chartbook.toml")
        found = {str(local): (record, reason) for local, record, reason in materialize_in_source(pipeline, "acme/rates", raw, FolderStore(tmp_path / "store"))}
        record, reason = found["curve"]
        assert "content_hash" not in record
        assert record["location"]["backend"] == "databricks"
        assert "is read where it is" in reason
        assert warehouse.connections == []
