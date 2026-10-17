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

A table made with :meth:`Warehouse.table` is a Delta table: each write is a
new version, kept as a DuckDB table of its own, ``describe detail`` gives
its format and id, ``describe history … limit 1`` its newest version, and
``… VERSION AS OF n`` reads version ``n`` until :meth:`Warehouse.vacuum`
drops it. :meth:`Warehouse.view` and ``delta=False`` make what has no
versions; :meth:`Warehouse.replace` drops a table and makes it again, with a
new id and its versions from 0; :meth:`Warehouse.rebuild` makes it again as
``create or replace`` does, with a new id and its history kept. A name in one
or two parts is found in the connection's catalog and schema.
:meth:`Warehouse.fail` makes the next statement that matches fail.
"""

import re
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

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
        #: Statements that fail once, by a pattern of their text, with a message
        self.failures = []
        #: Each table by its full name: its id, its format, and its versions, (number, when, DuckDB table)
        self.tables = {}
        self.views = set()
        self._clock = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def _schema(self, identifier: str) -> None:
        catalog, schema, _ = identifier.split(".")
        if catalog not in {row[0] for row in self.duck.execute("select database_name from duckdb_databases()").fetchall()}:
            self.duck.execute(f"attach ':memory:' as {catalog}")
        self.duck.execute(f"create schema if not exists {catalog}.{schema}")

    def table(self, identifier: str, sql: str, delta: bool = True) -> None:
        """Make a table, ``catalog.schema.name``, from a DuckDB ``select``; again, a new version of it."""
        self._schema(identifier)
        found = self.tables.setdefault(
            identifier, {"id": str(uuid.uuid4()), "format": "delta" if delta else "parquet", "versions": []}
        )
        number = found["versions"][-1][0] + 1 if found["versions"] else 0
        self._clock += timedelta(hours=1)
        held = f"{identifier}__v{number}"
        self.duck.execute(f"create table {held} as {sql}")
        found["versions"].append((number, self._clock, held))
        self.duck.execute(f"create or replace view {identifier} as select * from {held}")

    def view(self, identifier: str, sql: str) -> None:
        """Make a view: it has no versions, and ``describe detail`` refuses it."""
        self._schema(identifier)
        self.duck.execute(f"create or replace view {identifier} as {sql}")
        self.views.add(identifier)

    def rebuild(self, identifier: str, sql: str) -> None:
        """Make a table again as ``create or replace`` does: a new id, and its history kept."""
        self.tables[identifier]["id"] = str(uuid.uuid4())
        self.table(identifier, sql)

    def fail(self, pattern: str, message: str) -> None:
        """Make the next statement whose text matches *pattern* fail with *message*."""
        self.failures.append((pattern, message))

    def replace(self, identifier: str, sql: str) -> None:
        """Drop a table and make it again: a new id, and its versions start again at 0."""
        for _, _, held in self.tables.pop(identifier)["versions"]:
            self.duck.execute(f"drop table if exists {held}")
        self.table(identifier, sql)

    def vacuum(self, identifier: str, keep_from: int) -> None:
        """Drop the versions of a table older than *keep_from*, as VACUUM after the retention period does."""
        found = self.tables[identifier]
        for number, _, held in found["versions"]:
            if number < keep_from:
                self.duck.execute(f"drop table if exists {held}")
        found["versions"] = [v for v in found["versions"] if v[0] >= keep_from]

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
        for failure in list(warehouse.failures):
            if re.search(failure[0], operation, re.IGNORECASE):
                warehouse.failures.remove(failure)
                raise ServerOperationError(failure[1])
        text = operation.replace("`", '"')
        special = _describe(self.connection, text)
        if special is not None:
            self._table = special
        else:
            try:
                self._table = self.connection.duck.execute(_at_versions(self.connection, text)).fetch_arrow_table()
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

    def fetchall(self):
        rows = []
        while (row := self.fetchone()) is not None:
            rows.append(row)
        return rows

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


#: A name as the statements have it: one to three parts, each quoted or plain.
_NAME = r'((?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+)){0,2})'


def _plain(name: str, connection) -> str:
    """A name in full, ``catalog.schema.table``, as the connection's catalog and schema complete it."""
    parts = name.replace('"', "").split(".")
    catalog = connection.arguments.get("catalog") or "hive_metastore"
    schema = connection.arguments.get("schema") or "default"
    return ".".join([catalog, schema][: 3 - len(parts)] + parts)


def _describe(connection, text: str):
    """What ``describe detail`` and ``describe history`` give, as Arrow; None for any other statement."""
    detail = re.fullmatch(rf"\s*describe\s+detail\s+{_NAME}\s*", text, re.IGNORECASE)
    history = re.fullmatch(rf"\s*describe\s+history\s+{_NAME}(\s+limit\s+(\d+))?\s*", text, re.IGNORECASE)
    if detail is None and history is None:
        return None
    warehouse = connection.warehouse
    name = _plain((detail or history).group(1), connection)
    if name in warehouse.views:
        command = "DESCRIBE DETAIL" if detail is not None else "DESCRIBE HISTORY"
        raise ServerOperationError(
            f"[EXPECT_TABLE_NOT_VIEW.NO_ALTERNATIVE] '{command}' expects a table but `{name}` is a view."
        )
    found = warehouse.tables.get(name)
    if found is None:
        raise ServerOperationError(f"[TABLE_OR_VIEW_NOT_FOUND] The table or view `{name}` cannot be found.")
    if detail is not None:
        return pa.table({"format": [found["format"]], "id": [found["id"]], "name": [name]})
    if found["format"] != "delta":
        raise ServerOperationError(f"[DELTA_TABLE_NOT_FOUND] `{name}` is not a Delta table.")
    newest_first = list(reversed(found["versions"]))
    if history.group(3):
        newest_first = newest_first[: int(history.group(3))]
    return pa.table(
        {
            "version": pa.array([v[0] for v in newest_first], pa.int64()),
            "timestamp": pa.array([v[1] for v in newest_first], pa.timestamp("us", tz="UTC")),
            "operation": ["WRITE"] * len(newest_first),
        }
    )


def _at_versions(connection, text: str) -> str:
    """``name VERSION AS OF n`` as the DuckDB table that holds version n; an error if it is not kept."""
    warehouse = connection.warehouse

    def held(match):
        name, number = _plain(match.group(1), connection), int(match.group(2))
        found = warehouse.tables.get(name)
        if found is None or found["format"] != "delta":
            raise ServerOperationError(f"[DELTA_TABLE_NOT_FOUND] `{name}` is not a Delta table.")
        for kept, _, table in found["versions"]:
            if kept == number:
                return table
        raise ServerOperationError(
            f"[DELTA_UNSUPPORTED_TIME_TRAVEL_BEYOND_DELETED_FILE_RETENTION_DURATION] Cannot time travel "
            f"`{name}` to version {number}: its files were removed."
        )

    return re.sub(rf"{_NAME}\s+VERSION\s+AS\s+OF\s+(\d+)", held, text, flags=re.IGNORECASE)


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
