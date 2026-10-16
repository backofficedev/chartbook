"""Backends: the engines behind a pipeline's ``[sources]``.

A dataframe is a file, or it is a table or a query in a **source**: a named,
configured instance of a backend, declared in the manifest::

    [sources.local]
    backend = "duckdb"
    url = "duckdb:///./_data/local.duckdb"

    [dataframes.slopes]
    source = "local"
    query = "select Date, SVENY10 - SVENY02 as slope from fed_yield_curve"

The rule, from ``docs_src/design/data-access.md``: **a name resolves to a
location; the backend runs the query; Arrow comes back; Polars wraps it.**
ChartBook never parses, plans or rewrites SQL. It knows where a name lives
and which dialect lives there, and it substitutes identifiers. The SQL is
the user's (:func:`chartbook.data.sql`).

Two backends are built in. ``parquet`` is what a file-backed dataframe has
always been: it reads the file, and in SQL it is ``read_parquet('…')``.
``duckdb`` is the local engine: a file, or ``:memory:``, that holds tables
and runs any SQL that mentions them, and reads parquet files too, so a
query can join a table of one source with a file of this pipeline. Other
engines (Snowflake, Databricks, Postgres) are not built; a manifest that
names one is refused, so that the message can say so. The asset graph's
rule holds: no plugin seam before a third implementation exists.

**Credentials never enter a manifest.** A source's ``url`` is the public
part. The machine supplies the rest (:func:`source_url`): an environment
variable ``CHARTBOOK_SOURCE_<NAME>_URL`` holding a complete URL, then a
``url`` for the source in ``~/.chartbook/sources.toml``, then the manifest's
URL alone, which is all a DuckDB file needs. A manifest URL that carries a
user name or a password is refused when the manifest loads, and so is a
machine URL for a different engine than the manifest's backend.

**No writes.** A connection to a DuckDB file is opened read-only.
ChartBook never creates, loads or alters a table; ``table`` and ``query``
describe what the pipeline's own tools have already made. A ``:memory:``
source is the exception by nature: it holds nothing until something is put
in it through :func:`chartbook.data.connect`, so it is one writable
connection for the life of the process.

**Connections are not kept.** A DuckDB file is opened afresh for each
load, so a rebuilt file is seen on the next call. A lazy frame handed out
keeps its own connection alive for as long as it lives, and DuckDB locks
the file against writers for that long; drop the frame before rebuilding
the file in the same process.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union
from urllib.parse import urlsplit

import tomli

from chartbook.config import get_global_config_dir
from chartbook.identity import strip_url_credentials

if TYPE_CHECKING:  # pragma: no cover
    from chartbook.resolve import FileLocation, Location

#: The backends that are built. A manifest naming another is refused.
BACKENDS = ("duckdb",)

#: Where a machine keeps what a manifest may not: ``[<source>] url = "…"``.
SOURCES_FILE = "sources.toml"

#: The environment variable that gives a source its complete URL:
#: ``CHARTBOOK_SOURCE_WAREHOUSE_URL`` for a source called ``warehouse``.
SOURCE_ENV_PREFIX = "CHARTBOOK_SOURCE_"

#: The in-memory DuckDB URL, as a manifest and the resolver spell it.
MEMORY_URL = "duckdb:///:memory:"


class BackendError(Exception):
    """Raised when a source cannot be opened or a query cannot be run."""


def source_env_var(name: str) -> str:
    """The environment variable that may hold a source's URL."""
    return SOURCE_ENV_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_URL"


def source_url(name: str, manifest_url: str) -> str:
    """The URL a source is opened with, credentials and all.

    In order: the environment variable :func:`source_env_var` gives;
    ``url`` under ``[<name>]`` in ``~/.chartbook/sources.toml``; the
    manifest's own URL, which is enough for a DuckDB file.

    :param name: The source's name in ``[sources]``.
    :param manifest_url: Its ``url`` as the manifest has it.
    """
    from_environment = os.environ.get(source_env_var(name))
    if from_environment:
        return from_environment
    settings = get_global_config_dir() / SOURCES_FILE
    try:
        with open(settings, "rb") as f:
            table = tomli.load(f).get(name)
    except FileNotFoundError:
        table = None
    except (OSError, ValueError) as error:
        raise BackendError(f"Cannot read {settings}: {error}") from None
    if isinstance(table, dict) and isinstance(table.get("url"), str):
        return table["url"]
    return manifest_url


def check_backend(name: str, where: str) -> None:
    """Refuse a backend that is not built, and say which are.

    :param where: The manifest table, for the message.
    """
    if name not in BACKENDS:
        raise ValueError(
            f"{where}: backend {name!r} is not built. The backends are: "
            f"{', '.join(BACKENDS)}. Other engines arrive as plugins later; a "
            f"manifest that names one is refused until then, so that nothing "
            f"guesses."
        )


def scheme_of(url: str) -> str:
    """The scheme of a URL, lower-cased; empty when it has none."""
    return url.split("://", 1)[0].lower() if "://" in url else ""


def check_url(url: str, backend: str, where: str) -> None:
    """Refuse a source URL that carries credentials or the wrong scheme.

    For a DuckDB URL, also one with a host, a user, connection options or
    a fragment: ``duckdb:///<file>`` and nothing else.
    """
    if strip_url_credentials(url) != url:
        raise ValueError(
            f"{where}: the url carries a user name or a password. A manifest is "
            f"committed, so it holds the public part only; the machine supplies "
            f"the rest in {SOURCE_ENV_PREFIX}<NAME>_URL or ~/.chartbook/{SOURCES_FILE}."
        )
    if scheme_of(url) != backend:
        raise ValueError(
            f"{where}: the url {url!r} does not begin with {backend}://, which is "
            f"what a {backend} source takes."
        )
    if backend == "duckdb":
        try:
            duckdb_path(url, ".")
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None


def duckdb_path(url: str, manifest_dir: Union[str, Path]) -> str:
    """The file a ``duckdb://`` URL names, absolute; or ``:memory:``.

    Follows the SQLAlchemy convention: ``duckdb:///relative.db`` is relative
    to the pipeline's directory, ``duckdb:////abs/path.db`` is absolute, and
    ``duckdb:///:memory:`` is nothing on disk.

    :raises ValueError: If the URL has a host or a user (``duckdb://x/f``),
        connection options (``?access_mode=…``) or a fragment. ChartBook
        passes none of those to the engine, so it refuses to look as if it
        did.
    """
    parts = urlsplit(url)
    if parts.netloc:
        raise ValueError(
            f"the url {url!r} has a host or a user, {parts.netloc!r}, and a "
            f"DuckDB file has neither. Write duckdb:///./file.duckdb, with "
            f"three slashes, for a file beside the manifest."
        )
    if parts.query or parts.fragment:
        raise ValueError(
            f"the url {url!r} has connection options after the file. ChartBook "
            f"passes none to the engine: a DuckDB file is opened read-only, "
            f"and that is all. Name the file alone."
        )
    rest = parts.path
    if rest.startswith("/"):
        rest = rest[1:]
    if rest in ("", ":memory:"):
        return ":memory:"
    return os.path.normpath(Path(manifest_dir) / rest) if not rest.startswith("/") else rest


def quote_identifier(identifier: str) -> str:
    """Quote a one-to-three-part identifier for DuckDB: ``"a"."b"."c"``.

    A part is quoted with double quotes, and a double quote inside it is
    doubled. What is between the dots is the user's; nothing is guessed.
    """
    parts = identifier.split(".")
    return ".".join('"' + part.replace('"', '""') + '"' for part in parts)


def quote_literal(text: str) -> str:
    """Quote a string for SQL: ``'…'`` with a quote inside doubled."""
    return "'" + text.replace("'", "''") + "'"


def subselect(sql: str) -> str:
    """A query as a table expression: ``(…)`` on its own lines.

    A trailing semicolon is dropped and the parenthesis closes on a new
    line, so that a query that ends with ``;`` or with a ``--`` comment
    still stands where a table would.
    """
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return f"(\n{text}\n)"


class ParquetBackend:
    """What a file-backed dataframe has always been.

    In SQL a file is ``read_parquet('…')``, which DuckDB reads as a table,
    partitions and all.
    """

    name = "parquet"

    @staticmethod
    def ref(location: "FileLocation") -> str:
        """The file as a DuckDB table expression."""
        from chartbook.utils import is_glob_pattern

        text = str(location.path)
        if is_glob_pattern(text):
            return f"read_parquet({quote_literal(text)}, hive_partitioning = true)"
        return f"read_parquet({quote_literal(text)})"

    @staticmethod
    def scan(location: "FileLocation"):
        import polars as pl

        return pl.scan_parquet(location.path, hive_partitioning=True)


class DuckDBBackend:
    """A DuckDB file, opened read-only for each use, or an in-memory engine.

    A file is opened afresh by every :meth:`connect`, so nothing in the
    process keeps a stale handle: a frame handed out keeps its own
    connection for as long as it lives, and no longer. The in-memory engine
    of a ``:memory:`` source is one connection for the life of the process,
    since what is put in it through ``data.connect()`` is all it holds.
    """

    name = "duckdb"
    _memory: dict = {}

    def __init__(self, url: str, connection=None):
        self.url = url
        self._connection = connection

    @classmethod
    def scratch(cls) -> "DuckDBBackend":
        """A fresh in-memory engine of its own, for SQL over files alone.

        Nothing put into any source's connection is visible in it.
        """
        import duckdb

        return cls(MEMORY_URL, connection=duckdb.connect(":memory:"))

    def connect(self):
        """The raw ``duckdb`` connection.

        :raises BackendError: If the file is not there, or cannot be opened;
            or if this is a build of files from a store, whose manifest
            anyone who can write the store may have written: such a build
            runs no table and no query (a query can read any file of the
            machine), and says so on the page.
        """
        import duckdb

        from chartbook.config import untrusted_source

        if untrusted_source():
            raise BackendError(
                "A table or a query is not read in a build of files from a store; the snapshot "
                "holds its rows as parquet."
            )
        if self._connection is not None:
            return self._connection
        path = duckdb_path(self.url, Path.cwd())
        if path == ":memory:":
            if self.url not in self._memory:
                self._memory[self.url] = duckdb.connect(":memory:")
            return self._memory[self.url]
        if not Path(path).is_file():
            raise BackendError(
                f"The DuckDB file {path} is not there. The pipeline builds it; "
                f"run its build first."
            )
        try:
            return duckdb.connect(path, read_only=True)
        except duckdb.Error as error:
            raise BackendError(f"Cannot open {path}: {error}") from None

    @staticmethod
    def ref(location: "Location") -> str:
        """A table as a quoted identifier; a query as a sub-select."""
        if location.kind == "table":
            return quote_identifier(location.identifier)
        if location.kind == "query":
            return subselect(location.sql)
        return ParquetBackend.ref(location)

    def sql(self, query: str):
        """Run SQL in this engine and return a Polars LazyFrame.

        The engine binds the query here, so a name it does not know or SQL
        it cannot parse is refused at once. Collecting the frame runs it;
        an error that only running can find, such as a cast that fails on
        a value, is raised then with DuckDB's message: as Polars'
        ``ComputeError`` or as DuckDB's own exception, by Polars version.

        :raises BackendError: If DuckDB refuses the query. The message is
            DuckDB's own; the SQL is the user's.
        """
        import duckdb

        try:
            return self.connect().sql(query).pl(lazy=True)
        except duckdb.Error as error:
            raise BackendError(str(error)) from None

    def scan(self, location: "Location"):
        return self.sql(f"select * from {self.ref(location)}")

    def describe(self, location: "Location") -> tuple[list[dict], int]:
        """A dataframe's columns, with DuckDB's type names, and its row count."""
        import duckdb

        try:
            connection = self.connect()
            described = connection.sql(f"describe select * from {self.ref(location)}").fetchall()
            (rows,) = connection.sql(f"select count(*) from {self.ref(location)}").fetchone()
        except duckdb.Error as error:
            raise BackendError(str(error)) from None
        return [{"name": row[0], "dtype": row[1]} for row in described], int(rows)

    def span(self, location: "Location", column: str) -> tuple:
        """The first and last date in one column, read as timestamps.

        ``try_cast(col as timestamp)``: a date or timestamp column is itself,
        a text column is parsed where it can be, and anything else is null.
        """
        import duckdb

        name = '"' + column.replace('"', '""') + '"'
        try:
            return self.connect().sql(
                f"select min(try_cast({name} as timestamp)), max(try_cast({name} as timestamp)) "
                f"from {self.ref(location)}"
            ).fetchone()
        except duckdb.Error as error:
            raise BackendError(str(error)) from None


def backend_for(location: "Location"):
    """The backend that reads a location: parquet for a file, else the source's.

    :raises NotImplementedError: For a kind of location nothing here reads.
    """
    if location.kind == "file":
        return ParquetBackend()
    if location.kind in ("table", "query"):
        return DuckDBBackend(location.url)
    raise NotImplementedError(
        f"A {location.kind}-backed dataframe cannot be read: no backend reads "
        f"that kind of location."
    )
