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

Three backends are built. ``parquet`` is what a file-backed dataframe has
always been: it reads the file, parquet, CSV, JSON lines or Arrow IPC
(:mod:`chartbook.formats`), and in SQL it is DuckDB's reader of its format,
``read_parquet('…')``, ``read_csv('…', …)`` or ``read_json('…', …)``.
``duckdb`` is the local engine: a file, or ``:memory:``, that holds tables
and runs any SQL that mentions them, and reads those files too, so a
query can join a table of one source with a file of this pipeline.
``databricks`` is a SQL warehouse (:mod:`chartbook.backends.databricks`),
whose driver ``pip install chartbook[databricks]`` installs. A source's
backend is found by its name: ``duckdb`` here, any other in the entry-point
group ``chartbook.backends``, as a kind of store is in ``chartbook.stores``.
What a backend does for ChartBook is :class:`Backend`. A manifest that
names a backend nothing provides is refused, so that the message can say so.

**Credentials never enter a manifest.** A source's ``url`` is the public
part. The machine supplies the rest (:func:`source_url`): an environment
variable ``CHARTBOOK_SOURCE_<NAME>_URL`` holding a complete URL, then a
``url`` for the source in ``~/.chartbook/sources.toml``, then the manifest's
URL alone, which is all a DuckDB file needs. A manifest URL that carries a
user name or a password is refused when the manifest loads, and so is a
machine URL for a different engine than the manifest's backend. A
warehouse's backend may take its credentials from the engine's own
environment variables too, and sends them only to a host the machine names.

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

import functools
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Optional, Union
from urllib.parse import urlsplit

import tomli

from chartbook.config import get_global_config_dir
from chartbook.identity import strip_url_credentials

if TYPE_CHECKING:  # pragma: no cover
    from chartbook.resolve import FileLocation, Location

#: The entry-point group a backend is found in by its name: an entry named
#: as ``[sources.x] backend`` says, whose value is a :class:`Backend` class.
BACKEND_PLUGIN_GROUP = "chartbook.backends"

#: What installs the driver of each backend ChartBook brings, for a message.
EXTRAS = {"databricks": "pip install chartbook[databricks]"}

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


def machine_source_url(name: str) -> Optional[str]:
    """The URL this machine gives a source, credentials and all; None if it gives none.

    The environment variable :func:`source_env_var` names, then ``url``
    under ``[<name>]`` in ``~/.chartbook/sources.toml``.

    In a build of files from a store, none: such a build reaches no engine,
    and has no use for this machine's credentials.

    :param name: The source's name in ``[sources]``.
    :raises chartbook.backends.BackendError: If ``sources.toml`` is there and cannot be read.
    """
    from chartbook.config import untrusted_source

    if untrusted_source():
        return None
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
    return None


def source_url(name: str, manifest_url: str) -> str:
    """The URL a source is opened with, credentials and all.

    In order: the environment variable :func:`source_env_var` gives;
    ``url`` under ``[<name>]`` in ``~/.chartbook/sources.toml``; the
    manifest's own URL, which is enough for a DuckDB file.

    :param name: The source's name in ``[sources]``.
    :param manifest_url: Its ``url`` as the manifest has it.
    """
    return machine_source_url(name) or manifest_url


def backend_names() -> list[str]:
    """Every backend a source may name here: ``duckdb``, and each one a plugin provides."""
    from importlib.metadata import entry_points

    return sorted({"duckdb"} | {entry.name for entry in entry_points(group=BACKEND_PLUGIN_GROUP)})


@functools.lru_cache(maxsize=None)
def backend_class(name: str) -> Optional[type]:
    """The :class:`Backend` class a source's ``backend`` names; None if nothing provides it.

    ``duckdb`` is built in. Another name is looked up once per process in the
    entry-point group ``chartbook.backends``; the first entry with the name
    wins. A plugin whose driver is not installed still loads: the driver is
    imported when the backend connects, and the message then names the extra.

    :raises ValueError: If the plugin is there and cannot be loaded, naming it.
    """
    from importlib.metadata import entry_points

    if name == "duckdb":
        return DuckDBBackend
    for entry in entry_points(group=BACKEND_PLUGIN_GROUP):
        if entry.name == name:
            try:
                return entry.load()
            except Exception as error:  # noqa: BLE001 - whatever the plugin's import raised
                raise ValueError(f"The backend plugin {entry.value!r} for {name!r} cannot be loaded: {error}") from None
    return None


def check_backend(name: str, where: str) -> None:
    """Refuse a backend nothing provides, and say which there are.

    :param where: The manifest table, for the message.
    """
    if backend_class(name) is None:
        raise ValueError(
            f"{where}: backend {name!r} is not one ChartBook knows. The backends are: "
            f"{', '.join(backend_names())}. Another engine is a plugin, a package with "
            f"a {BACKEND_PLUGIN_GROUP!r} entry point named for it; a manifest that names "
            f"one nothing provides is refused, so that nothing guesses.{_reinstall(name)}"
        )


def _reinstall(name: str) -> str:
    """For a backend ChartBook brings and this install does not list: an install made before it did."""
    if name not in EXTRAS:
        return ""
    return (
        f" ChartBook brings {name}: an install made before it did lacks its entry point, and "
        f"reinstalling ChartBook ({EXTRAS[name]}) adds it."
    )


def scheme_of(url: str) -> str:
    """The scheme of a URL, lower-cased; empty when it has none."""
    return url.split("://", 1)[0].lower() if "://" in url else ""


def check_url(url: str, backend: str, where: str) -> None:
    """Refuse a source URL that carries credentials or the wrong scheme.

    Then what the backend itself refuses (:meth:`Backend.check_url`): for a
    DuckDB URL, one with a host, a user, connection options or a fragment,
    ``duckdb:///<file>`` and nothing else.
    """
    if strip_url_credentials(url) != url:
        raise ValueError(
            f"{where}: the url carries a user name or a password. A manifest is "
            f"committed, so it holds the public part only; the machine supplies "
            f"the rest in {SOURCE_ENV_PREFIX}<NAME>_URL or ~/.chartbook/{SOURCES_FILE}."
        )
    if scheme_of(url) != backend:
        # The url is not repeated: what is written where a scheme should be may be a credential
        raise ValueError(
            f"{where}: the url does not begin with {backend}://, which is "
            f"what a {backend} source takes."
        )
    try:
        backend_class(backend).check_url(url)
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
            f"the url has a host or a user, and a "
            f"DuckDB file has neither. Write duckdb:///./file.duckdb, with "
            f"three slashes, for a file beside the manifest."
        )
    if parts.query or parts.fragment:
        raise ValueError(
            f"the url has connection options after the file. ChartBook "
            f"passes none to the engine: a DuckDB file is opened read-only, "
            f"and that is all. Name the file alone."
        )
    rest = parts.path
    if rest.startswith("/"):
        rest = rest[1:]
    if rest in ("", ":memory:"):
        return ":memory:"
    return os.path.normpath(Path(manifest_dir) / rest) if not rest.startswith("/") else rest


def quote_identifier(identifier: str, quote: str = '"') -> str:
    """Quote a one-to-three-part identifier for DuckDB: ``"a"."b"."c"``.

    With a backtick for *quote*, as Databricks quotes one, each part is
    between backticks instead, and a backtick inside it is doubled.

    A part is quoted with double quotes, and a double quote inside it is
    doubled. What is between the dots is the user's; nothing is guessed.
    """
    parts = identifier.split(".")
    return ".".join(quote + part.replace(quote, quote * 2) + quote for part in parts)


def quote_literal(text: str) -> str:
    """Quote a string for SQL: ``'…'`` with a quote inside doubled."""
    return "'" + text.replace("'", "''") + "'"


#: A string quoted in dollars opens with ``$$`` or ``$tag$``, and closes with the same.
_DOLLAR_QUOTE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _ends_in(sql: str) -> tuple:
    """What the end of some SQL is inside of, and where a line comment there began.

    The text is read once, as DuckDB and Databricks read it: ``'…'`` is a
    string, in which a backslash is literal (DuckDB's rule; Databricks
    escapes with one, which at worst leaves the end inside a string here);
    ``E'…'`` a string with backslash escapes; ``$$…$$`` or ``$tag$…$tag$``
    a string quoted in dollars; ``"…"`` or `` `…` `` a quoted identifier;
    ``--`` a comment to the end of its line; ``/* … */`` a comment to its
    close. A ``;`` or a ``--`` inside any of them is part of it.

    :returns: ``"code"``, ``"string"``, ``"identifier"``, ``"line_comment"``
        or ``"block_comment"``; and, for a line comment, the index of its
        ``--`` (None otherwise).
    """
    state, began, closer, escapes = "code", None, "", False
    i = 0
    while i < len(sql):
        c = sql[i]
        if state == "code":
            if c == "'":
                state, closer, escapes = "string", "'", False
            elif c in "eE" and sql.startswith("'", i + 1) and not (i and (sql[i - 1].isalnum() or sql[i - 1] == "_")):
                state, closer, escapes = "string", "'", True
                i += 1  # onto the opening quote
            elif c == "$" and _DOLLAR_QUOTE.match(sql, i):
                state, closer, escapes = "string", _DOLLAR_QUOTE.match(sql, i).group(0), False
                i += len(closer) - 1
            elif c in "\"`":
                state, closer, escapes = "identifier", c, False
            elif sql.startswith("--", i):
                state, began = "line_comment", i
                i += 1
            elif sql.startswith("/*", i):
                state = "block_comment"
                i += 1
        elif state in ("string", "identifier"):
            if escapes and c == "\\":
                i += 1  # the character it escapes, whatever it is
            elif sql.startswith(closer, i):
                state = "code"  # a doubled quote closes and reopens, which comes to the same
                i += len(closer) - 1
        elif state == "line_comment":
            if c == "\n":
                state, began = "code", None
        elif state == "block_comment" and sql.startswith("*/", i):
            state = "code"
            i += 1
        i += 1
    return state, began


def subselect(sql: str) -> str:
    """A query as a table expression: ``(…)`` on its own lines.

    Two things are dropped from the end of the text, each as many times as
    one is left there, so that a query that ends with ``;``, with a ``--``
    comment, or with both (``select … from t; -- note``) still stands where
    a table would: a semicolon that is the last character; and a ``--``
    comment that runs to the end, when its ``--`` is outside every string
    (``'…'``, ``E'…'``, ``$$…$$``), quoted identifier (``"…"``, `` `…` ``)
    and block comment, as :func:`_ends_in` reads them. Nothing else
    changes: a ``;`` or a ``--`` inside quotes stays, and a comment after a
    quote the scanner takes as left open stays too, which the engine reads
    as the comment it is. The parenthesis closes on a new line.
    """
    text = sql.strip()
    while True:
        while text.endswith(";"):
            text = text[:-1].rstrip()
        state, began = _ends_in(text)
        if state != "line_comment":
            break
        text = text[:began].rstrip()
    return f"(\n{text}\n)"


def refuse_in_an_untrusted_build() -> None:
    """Refuse to reach an engine in a build of files from a store.

    Anyone who can write the store may have written its manifest: a query
    can read any file of the machine, and a warehouse's URL could send this
    machine's credentials elsewhere.

    :raises chartbook.backends.BackendError: In such a build.
    """
    from chartbook.config import untrusted_source

    if untrusted_source():
        raise BackendError(
            "A table or a query is not read in a build of files from a store, nor of a folder you have "
            "not trusted: a version's snapshot holds its rows as parquet, and `chartbook trust` in a "
            "folder trusts the pipeline there."
        )


class Backend:
    """An engine behind a source: what ChartBook asks of one.

    ``name`` is what ``[sources.x] backend`` says. A backend is made from a
    source's public URL, as its location carries it, and the source's name,
    by which the machine's own URL and credentials are found; it connects
    only when asked. Every call that reaches the engine raises
    :class:`BackendError` with the engine's own message when it fails; an
    error found only when a lazy frame is collected comes as Polars'
    ``ComputeError`` with the engine's message in it, or as the
    :class:`BackendError` itself, by Polars version.

    ``reads_files`` says whether SQL run in it may name a file of this
    machine as :class:`ParquetBackend` writes one, ``read_parquet('…')`` say:
    so whether :func:`chartbook.data.sql` may join this engine's tables
    with a pipeline's files in one query.
    """

    name: ClassVar[str]
    reads_files: ClassVar[bool] = False

    def __init__(self, url: str, source: Optional[str] = None):
        self.url = url
        self.source = source

    @staticmethod
    def check_url(url: str) -> None:
        """Refuse a manifest URL this backend cannot open, with what to write instead.

        Credentials and the scheme are checked before this (:func:`check_url`).

        :raises ValueError: Saying what is wrong with it.
        """

    def connect(self):
        """The engine's own connection, for :func:`chartbook.data.connect`."""
        raise NotImplementedError

    def engine(self) -> tuple:
        """What tells one engine from another: two locations with the same run in one query.

        By default the backend, its URL and the source's name, since the
        machine may give each source its own place to connect to.
        """
        return (self.name, self.url, self.source)

    def ref(self, location: "Location") -> str:
        """A table as a quoted identifier; a query as a sub-select: what stands for it in SQL here."""
        raise NotImplementedError

    def sql(self, query: str, arrow: Optional[dict] = None):
        """Run SQL in this engine and return a Polars LazyFrame.

        The engine binds the query here, so a name it does not know is
        refused at once; collecting the frame runs it. *arrow* is Arrow
        data the query names, by the name it goes by, for an engine that
        reads files (``reads_files``) and can scan Arrow data: an Arrow IPC
        file, which DuckDB has no reader of its own for. A backend whose
        ``sql()`` takes no such argument is handed none, and a query naming
        such a file is refused before it reaches it.
        """
        raise NotImplementedError

    def scan(self, location: "Location"):
        """A table or a query, as a Polars LazyFrame."""
        return self.sql(f"select * from {self.ref(location)}")

    def describe(self, location: "Location") -> tuple[list[dict], int]:
        """A dataframe's columns, with the engine's type names, and its row count."""
        raise NotImplementedError

    def span(self, location: "Location", column: str) -> tuple:
        """The first and last date in one column, read as timestamps; a value that is not one is left out."""
        raise NotImplementedError


class ParquetBackend:
    """What a file-backed dataframe has always been, in any format it is stored in.

    It reads through :mod:`chartbook.formats`, as everything that reads a
    file does. In SQL a file is DuckDB's reader of its format:
    ``read_parquet('…')``, which DuckDB reads as a table, partitions and
    all; ``read_csv('…', …)``; or ``read_json('…', …)``.
    """

    name = "parquet"

    @staticmethod
    def ref(location: "FileLocation") -> str:
        """The file as a DuckDB table expression."""
        from chartbook import formats

        return formats.sql(location)

    @staticmethod
    def scan(location: "FileLocation"):
        from chartbook import formats

        return formats.scan_location(location)


class DuckDBBackend(Backend):
    """A DuckDB file, opened read-only for each use, or an in-memory engine.

    A file is opened afresh by every :meth:`connect`, so nothing in the
    process keeps a stale handle: a frame handed out keeps its own
    connection for as long as it lives, and no longer. The in-memory engine
    of a ``:memory:`` source is one connection for the life of the process,
    since what is put in it through ``data.connect()`` is all it holds.
    """

    name = "duckdb"
    reads_files = True
    _memory: dict = {}

    def __init__(self, url: str, source: Optional[str] = None, connection=None):
        super().__init__(url, source)
        self._connection = connection

    @staticmethod
    def check_url(url: str) -> None:
        duckdb_path(url, ".")

    def engine(self) -> tuple:
        # A DuckDB file is its URL, whatever source names it
        return (self.name, self.url)

    @classmethod
    def scratch(cls) -> "DuckDBBackend":
        """A fresh in-memory engine of its own, for SQL over files alone.

        Nothing put into any source's connection is visible in it.
        """
        import duckdb

        return cls(MEMORY_URL, connection=duckdb.connect(":memory:"))

    def connect(self):
        """The raw ``duckdb`` connection.

        :raises chartbook.backends.BackendError: If the file is not there, or cannot be opened;
            or if this is a build of files from a store, whose manifest
            anyone who can write the store may have written: such a build
            runs no table and no query (a query can read any file of the
            machine), and says so on the page.
        """
        import duckdb

        refuse_in_an_untrusted_build()
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

    def ref(self, location: "Location") -> str:
        """A table as a quoted identifier; a query as a sub-select."""
        if location.kind == "table":
            return quote_identifier(location.identifier)
        if location.kind == "query":
            return subselect(location.sql)
        return ParquetBackend.ref(location)

    def sql(self, query: str, arrow: Optional[dict] = None):
        """Run SQL in this engine and return a Polars LazyFrame.

        The engine binds the query here, so a name it does not know or SQL
        it cannot parse is refused at once. Collecting the frame runs it;
        an error that only running can find, such as a cast that fails on
        a value, is raised then with DuckDB's message: as Polars'
        ``ComputeError`` or as DuckDB's own exception, by Polars version.

        :param arrow: Arrow data the query names, by the name it goes by:
            an Arrow IPC file, which DuckDB has no reader of its own for
            (:func:`chartbook.formats.arrow_dataset`). It is registered with
            the connection the query runs in, for as long as that lives.
        :raises chartbook.backends.BackendError: If DuckDB refuses the query. The message is
            DuckDB's own; the SQL is the user's.
        """
        import duckdb

        try:
            connection = self.connect()
            for name, table in (arrow or {}).items():
                connection.register(name, table)
            return connection.sql(query).pl(lazy=True)
        except duckdb.Error as error:
            raise BackendError(str(error)) from None

    def describe(self, location: "Location") -> tuple[list[dict], int]:
        """A dataframe's columns, with DuckDB's type names, and its row count."""
        import duckdb

        try:
            connection = self.connect()
            # Fetched whole: a relation has no fetchone from DuckDB 2.0, and a result read only in part keeps the connection busy
            described = connection.sql(f"describe select * from {self.ref(location)}").fetchall()
            ((rows,),) = connection.sql(f"select count(*) from {self.ref(location)}").fetchall()
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
            ).fetchall()[0]
        except duckdb.Error as error:
            raise BackendError(str(error)) from None


def backend_for(location: "Location"):
    """The backend that reads a location: parquet for a file, else the source's.

    :raises NotImplementedError: For a kind of location nothing here reads.
    :raises chartbook.backends.BackendError: For a source whose backend nothing provides here,
        as a location read from another pipeline's record may name.
    """
    if location.kind == "file":
        return ParquetBackend()
    if location.kind in ("table", "query"):
        return open_backend(location.backend, location.url, location.source)
    raise NotImplementedError(
        f"A {location.kind}-backed dataframe cannot be read: no backend reads "
        f"that kind of location."
    )


def open_backend(name: str, url: str, source: Optional[str] = None) -> Backend:
    """The backend a source names, made from its public URL and its name.

    :raises chartbook.backends.BackendError: If nothing here provides it: a record from
        another machine may name a backend this one has no plugin for.
    """
    try:
        found = backend_class(name)
    except ValueError as error:
        raise BackendError(str(error)) from None
    if found is None:
        raise BackendError(
            f"The source {source!r} is in a {name} engine, and nothing here provides one. "
            f"The backends are: {', '.join(backend_names())}.{_reinstall(name)}"
        )
    return found(url, source)
