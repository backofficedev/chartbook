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
user name or a password is refused when the manifest loads.

**No writes.** A connection to a DuckDB file is opened read-only.
ChartBook never creates, loads or alters a table; ``table`` and ``query``
describe what the pipeline's own tools have already made.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

import tomli

from chartbook.config import get_global_config_dir
from chartbook.identity import strip_url_credentials

if TYPE_CHECKING:  # pragma: no cover
    from chartbook.resolve import FileLocation, Location, QueryLocation, TableLocation

#: The backends that are built. A manifest naming another is refused.
BACKENDS = ("duckdb",)

#: Where a machine keeps what a manifest may not: ``[<source>] url = "…"``.
SOURCES_FILE = "sources.toml"

#: The environment variable that gives a source its complete URL:
#: ``CHARTBOOK_SOURCE_WAREHOUSE_URL`` for a source called ``warehouse``.
SOURCE_ENV_PREFIX = "CHARTBOOK_SOURCE_"


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


def check_url(url: str, backend: str, where: str) -> None:
    """Refuse a source URL that carries credentials or the wrong scheme."""
    if strip_url_credentials(url) != url:
        raise ValueError(
            f"{where}: the url carries a user name or a password. A manifest is "
            f"committed, so it holds the public part only; the machine supplies "
            f"the rest in {source_env_var('<name>')} or ~/.chartbook/{SOURCES_FILE}."
        )
    scheme = url.split("://", 1)[0].lower() if "://" in url else ""
    if scheme != backend:
        raise ValueError(
            f"{where}: the url {url!r} does not begin with {backend}://, which is "
            f"what a {backend} source takes."
        )


def duckdb_path(url: str, manifest_dir: Union[str, Path]) -> str:
    """The file a ``duckdb://`` URL names, absolute; or ``:memory:``.

    Follows the SQLAlchemy convention: ``duckdb:///relative.db`` is relative
    to the pipeline's directory, ``duckdb:////abs/path.db`` is absolute, and
    ``duckdb:///:memory:`` is nothing on disk.
    """
    rest = url.split("://", 1)[1]
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
    """A DuckDB file, opened read-only, or an in-memory engine.

    One connection per URL, kept for the life of the process, so that a
    lazy frame handed out stays readable.
    """

    name = "duckdb"
    _connections: dict = {}

    def __init__(self, url: str):
        self.url = url

    def connect(self):
        """The raw ``duckdb`` connection, opened on first use.

        :raises BackendError: If the file is not there, or cannot be opened.
        """
        import duckdb

        if self.url in self._connections:
            return self._connections[self.url]
        path = duckdb_path(self.url, Path.cwd())
        if path == ":memory:":
            connection = duckdb.connect(":memory:")
        else:
            if not Path(path).is_file():
                raise BackendError(
                    f"The DuckDB file {path} is not there. The pipeline builds it; "
                    f"run its build first."
                )
            try:
                connection = duckdb.connect(path, read_only=True)
            except duckdb.Error as error:
                raise BackendError(f"Cannot open {path}: {error}") from None
        self._connections[self.url] = connection
        return connection

    @staticmethod
    def ref(location: "Location") -> str:
        """A table as a quoted identifier; a query as a sub-select."""
        if location.kind == "table":
            return quote_identifier(location.identifier)
        if location.kind == "query":
            return f"({location.sql})"
        return ParquetBackend.ref(location)

    def sql(self, query: str):
        """Run SQL in this engine and return a Polars LazyFrame.

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


def connection_for(location: "Location", manifest_dir: Optional[Path] = None):
    """A DuckDB connection for a table or query location."""
    return DuckDBBackend(location.url).connect()
