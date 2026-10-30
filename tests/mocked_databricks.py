"""A stand-in for the Databricks SQL connector, over DuckDB, for tests.

:func:`install` puts modules ``databricks`` and ``databricks.sql`` in
``sys.modules``, whose ``connect()`` takes the arguments the real connector
documents and opens a connection to a :class:`Warehouse`: a DuckDB in
memory, with the tables a test makes in it, under catalogs DuckDB attaches.
Backticks become double quotes on the way in, which is all the SQL these
tests send needs. Each connection, and each query, is kept, so a test can
say what was sent where, and that every connection was closed.

What the real connector does that this does not: talk to a server. The
call shapes follow its documentation (version 4): ``connect(server_hostname,
http_path, access_token=…, auth_type=…, catalog=…, schema=…,
user_agent_entry=…)``, ``cursor()``, ``execute(operation)``,
``fetchall_arrow()``, ``fetchmany_arrow(size)``, ``fetchone()``,
``description`` as seven-item tuples with the type's name second.
"""

import sys
import types

import duckdb
import pyarrow as pa

#: The keyword arguments the real ``databricks.sql.connect`` documents.
CONNECT_ARGUMENTS = {
    "access_token", "auth_type", "credentials_provider", "password", "username",
    "session_configuration", "http_headers", "catalog", "schema", "use_cloud_fetch",
    "user_agent_entry", "query_tags", "staging_allowed_local_path", "use_kernel",
    "enable_telemetry", "experimental_oauth_persistence",
}


class Error(Exception):
    """``databricks.sql.exc.Error``."""


class ServerOperationError(Error):
    """``databricks.sql.exc.ServerOperationError``: the warehouse refused a statement."""


class RequestError(Error):
    """``databricks.sql.exc.RequestError``: the request failed, as a wrong token does."""


def _type_name(arrow_type) -> str:
    """The name Databricks gives a column of this Arrow type, as ``description`` has it."""
    if pa.types.is_int32(arrow_type):
        return "int"
    if pa.types.is_int64(arrow_type):
        return "bigint"
    if pa.types.is_floating(arrow_type):
        return "double"
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_timestamp(arrow_type):
        return "timestamp"
    if pa.types.is_boolean(arrow_type):
        return "boolean"
    if pa.types.is_decimal(arrow_type):
        return "decimal"
    return str(arrow_type)


class Warehouse:
    """One workspace's SQL warehouse: its host, its HTTP path, the token it takes, its tables."""

    def __init__(self, host="dbc-test.cloud.databricks.com", http_path="/sql/1.0/warehouses/abc", token="dapi-test"):
        self.host = host
        self.http_path = http_path
        self.token = token
        self.duck = duckdb.connect(":memory:")
        self.connections = []
        self.queries = []
        #: As a connector may: an empty result with no columns, its schema not sent
        self.empty_without_schema = False

    def table(self, identifier: str, sql: str) -> None:
        """Make a table, ``catalog.schema.name``, from a DuckDB ``select``."""
        catalog, schema, _ = identifier.split(".")
        if catalog not in {row[0] for row in self.duck.execute("select database_name from duckdb_databases()").fetchall()}:
            self.duck.execute(f"attach ':memory:' as {catalog}")
        self.duck.execute(f"create schema if not exists {catalog}.{schema}")
        self.duck.execute(f"create or replace table {identifier} as {sql}")

    def open(self):
        """Connections not yet closed."""
        return [c for c in self.connections if not c.closed]


class Connection:
    def __init__(self, warehouse, arguments):
        self.warehouse = warehouse
        self.arguments = arguments
        self.closed = False
        self.duck = warehouse.duck.cursor()
        if arguments.get("catalog"):
            target = arguments["catalog"] + ("." + arguments["schema"] if arguments.get("schema") else "")
            self.duck.execute(f"use {target}")
        elif arguments.get("schema"):
            self.duck.execute(f"use {arguments['schema']}")

    def cursor(self):
        if self.closed:
            raise Error("the connection is closed")
        return Cursor(self)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self._table = None
        self._at = 0
        self.closed = False

    def execute(self, operation, parameters=None):
        warehouse = self.connection.warehouse
        warehouse.queries.append(operation)
        try:
            # A relation's arrow table, on every DuckDB: from 2.0 a connection has none after execute
            relation = self.connection.duck.sql(operation.replace("`", '"'))
            self._table = relation.fetch_arrow_table() if relation is not None else pa.table({})
        except duckdb.Error as error:
            raise ServerOperationError(str(error)) from None
        self._at = 0
        self.description = [
            (field.name, _type_name(field.type), None, None, None, None, True) for field in self._table.schema
        ]
        return self

    def fetchall_arrow(self):
        rest = self._table.slice(self._at)
        self._at = self._table.num_rows
        if rest.num_rows == 0 and self.connection.warehouse.empty_without_schema:
            return pa.table({})
        return rest

    def fetchmany_arrow(self, size):
        batch = self._table.slice(self._at, size)
        self._at += batch.num_rows
        return batch

    def fetchone(self):
        if self._at >= self._table.num_rows:
            return None
        row = tuple(column[self._at].as_py() for column in self._table.columns)
        self._at += 1
        return row

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def install(monkeypatch, warehouse: Warehouse, *others: Warehouse):
    """Make ``from databricks import sql`` give a connector that reaches *warehouse*, and *others*, by host."""
    by_host = {w.host: w for w in (warehouse, *others)}

    def connect(server_hostname, http_path, access_token=None, **kwargs):
        unknown = set(kwargs) - CONNECT_ARGUMENTS
        if unknown:
            raise TypeError(f"connect() got unexpected keyword arguments {sorted(unknown)}")
        warehouse = by_host.get(server_hostname)
        if warehouse is None or http_path != warehouse.http_path:
            raise RequestError(f"no warehouse at {server_hostname}{http_path}")
        if kwargs.get("auth_type") != "databricks-oauth" and access_token != warehouse.token:
            raise RequestError("Invalid access token")
        connection = Connection(warehouse, {"server_hostname": server_hostname, "http_path": http_path,
                                            "access_token": access_token, **kwargs})
        warehouse.connections.append(connection)
        return connection

    sql = types.ModuleType("databricks.sql")
    sql.connect = connect
    exc = types.ModuleType("databricks.sql.exc")
    exc.Error, exc.ServerOperationError, exc.RequestError = Error, ServerOperationError, RequestError
    sql.exc = exc
    package = types.ModuleType("databricks")
    package.__path__ = []
    package.sql = sql
    monkeypatch.setitem(sys.modules, "databricks", package)
    monkeypatch.setitem(sys.modules, "databricks.sql", sql)
    monkeypatch.setitem(sys.modules, "databricks.sql.exc", exc)
    return warehouse
