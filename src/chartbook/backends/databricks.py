"""Databricks: a source in a Databricks SQL warehouse.

::

    [sources.warehouse]
    backend = "databricks"
    url = "databricks://dbc-a1b2c3d4-e5f6.cloud.databricks.com?http_path=/sql/1.0/warehouses/abc123&catalog=main"

    [dataframes.curve]
    source = "warehouse"
    table = "main.rates.curve"

The URL names the workspace's host, the warehouse's HTTP path (its
"Connection details" show both), and optionally the catalog and schema a
name without them is found in. Every part is optional in a manifest, since
the machine may supply it; a manifest's URL names no user, no token and no
way of signing in. The driver is the Databricks SQL connector, which
``pip install chartbook[databricks]`` installs.

**The host comes from the machine, and so does the token.** A token is sent
only to a host this machine names: the host of the machine's URL for the
source (``CHARTBOOK_SOURCE_<NAME>_URL`` or ``~/.chartbook/sources.toml``,
``databricks://token:<token>@<host>?http_path=…``), or else
``DATABRICKS_HOST``, with ``DATABRICKS_TOKEN``, the engine's own variables.
A manifest's host, or the host in another pipeline's record, is checked
against it and never used in its place: a manifest or a store anyone can
write must not be able to send this machine's token somewhere else. The
HTTP path is the machine URL's, else the manifest's, else
``DATABRICKS_HTTP_PATH``. ``auth=oauth`` in the machine's URL signs in
through the browser instead of a token, once for the life of the process.

A pipeline's SQL runs with this machine's credentials in this machine's
workspace: building a pipeline someone else wrote runs their queries as
you, as running their code does.

**Reading.** :meth:`DatabricksBackend.sql` asks the warehouse for the
query's columns at once, so a name it does not know is refused then, and
returns a lazy frame that runs the query when it is collected, a batch at a
time; ``head(n)`` with nothing filtered asks for ``n`` rows. ChartBook runs
nothing but ``select`` and ``describe`` on its own account; the SQL a person
runs through ``data.sql()`` or ``data.connect()`` is between them and the
warehouse.

**Pinned by version.** A Delta table keeps its history, so a snapshot
records the table's version (:meth:`DatabricksBackend.version_of`) rather
than a copy, and a pipeline that pins it reads ``VERSION AS OF`` that
version, after checking that the table is still the one pinned
(:meth:`DatabricksBackend.check_pin`). Delta keeps old versions for 7 days
by default; a version the table no longer keeps cannot be read, and the
message says what to do. Nothing else in a warehouse is pinned, and
nothing is copied out of one: its rows stay under the warehouse's own
grants.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from chartbook.backends import (
    TABLE_IDENTIFIER,
    Backend,
    BackendError,
    machine_source_url,
    quote_identifier,
    refuse_in_an_untrusted_build,
    scheme_of,
    source_env_var,
    subselect,
)

if TYPE_CHECKING:  # pragma: no cover
    from chartbook.resolve import Location

#: What a Databricks URL may say after ``?``.
URL_OPTIONS = ("http_path", "catalog", "schema", "auth")

#: How a connection may sign in: a token, or the browser.
AUTH = ("token", "oauth")

#: Rows asked of the warehouse at a time when a frame is collected.
BATCH_ROWS = 100_000

#: What moves a pin to the version a table has now: a new snapshot upstream, then an update.
REPIN = (
    "The pipeline that names the table records the version it has now in a new snapshot "
    "(`chartbook snapshot` there), and `chartbook update` here pins that."
)

#: What a read of a version the table no longer keeps adds to the warehouse's message.
GONE = (
    "{identifier} is pinned at version {version}, and the warehouse could not read it. If the "
    "table no longer keeps that version (Delta keeps 7 days by default, and VACUUM removes what "
    "is older): " + REPIN + " Its owner can keep versions longer with the table properties "
    "delta.deletedFileRetentionDuration and delta.logRetentionDuration."
)

#: The error classes by which the warehouse says a thing has no versions a pin can name, and
#: nothing else: a view where a table was expected, time travel a table does not support (a row
#: filter or a column mask on it), time travel on a view. A class may be one of these or one of
#: their subclasses. A version the table no longer keeps is not among them: that is one version.
NO_VERSIONS_CLASSES = (
    "EXPECT_TABLE_NOT_VIEW",
    "FGAC_TIME_TRAVEL_NOT_SUPPORTED",
    "UNSUPPORTED_FEATURE.TIME_TRAVEL",
    "DELTA_UNSUPPORTED_TIME_TRAVEL_VIEWS",
)

#: An error's class, as the warehouse's message begins with it: ``[CLASS.SUBCLASS]``.
_ERROR_CLASS = re.compile(r"\s*\[([A-Z][A-Z0-9_]*(?:\.[A-Z0-9_]+)*)\]")

#: An error's SQLSTATE, as the warehouse's message ends with it.
_SQLSTATE = re.compile(r"SQLSTATE:\s*([0-9A-Z]{5})\W*$")

#: How many versions of history a check of a table made again reads back, at most.
HISTORY_LIMIT = 10_000

#: Tables made again whose history was found to have a pinned version, as written, this process:
#: (name, the table's id now, version, written_at). One look at a long history is enough.
_HISTORY_CHECKED: set = set()

#: A workspace's host: letters, digits, dots and hyphens, with a dot in it (a workspace's host
#: is never one label), and nothing a message could carry besides.
_HOST = re.compile(r"[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)+")


class _SignedIn:
    """The OAuth sign-ins of this process, in memory, by host: one sign-in in the browser serves every connection.

    What the connector's ``experimental_oauth_persistence`` takes. Nothing
    is written to disk.
    """

    def __init__(self):
        self._tokens: dict = {}

    def persist(self, hostname, oauth_token) -> None:
        self._tokens[hostname] = oauth_token

    def read(self, hostname):
        return self._tokens.get(hostname)


_SIGNED_IN = _SignedIn()


@dataclass(frozen=True)
class DatabricksURL:
    """The parts of a ``databricks://`` URL; each is empty when the URL does not say it."""

    host: str = ""
    http_path: str = ""
    catalog: str = ""
    schema: str = ""
    auth: str = ""
    token: str = field(default="", repr=False)


def host_of(text: str) -> str:
    """A workspace's host as it is compared, the host name alone in lower case; empty if *text* gives none.

    ``host``, ``https://host/``, ``host:443`` and ``https://host/?o=123``, as
    a workspace's address is written, all give ``host``.
    """
    text = text.strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text if "://" in text else "https://" + text)
        parts.port  # noqa: B018 - a port that does not parse is not an address
    except ValueError:
        return ""
    name = (parts.hostname or "").rstrip(".").lower()
    return name if _HOST.fullmatch(name) else ""


def parse_url(url: str) -> DatabricksURL:
    """Read a ``databricks://[token:<token>@]<host>?http_path=…&catalog=…&schema=…&auth=…`` URL.

    :raises ValueError: If it is not one: another scheme, a host that is
        not a host name, a path after the host, a port, an option that is
        not one of :data:`URL_OPTIONS`, an option given twice, a fragment,
        or an ``auth`` that is not ``token`` or ``oauth``. The message
        repeats nothing of the url, which may hold a token anywhere.
    """
    if scheme_of(url) != "databricks":
        raise ValueError("a Databricks url begins with databricks://")
    try:
        parts = urlsplit(url)
    except ValueError:
        # Never the parser's message: it repeats the url, token and all
        raise ValueError("not a url ChartBook can read") from None
    if parts.fragment:
        raise ValueError("a Databricks url has nothing after #")
    if parts.path not in ("", "/"):
        raise ValueError(
            "a Databricks url names the host and nothing after it; the warehouse's HTTP path "
            "goes after ?, as databricks://<host>?http_path=/sql/1.0/warehouses/<id>"
        )
    try:
        port = parts.port
    except ValueError:
        port = -1
    if port is not None:
        raise ValueError("a Databricks url names the host without a port: the workspace is reached on 443")
    options = parse_qs(parts.query, keep_blank_values=True)
    if set(options) - set(URL_OPTIONS):
        raise ValueError(f"a Databricks url takes {', '.join(URL_OPTIONS)} after ?, and nothing else")
    twice = sorted(key for key, values in options.items() if len(values) > 1)
    if twice:
        raise ValueError(f"a Databricks url gives {', '.join(twice)} more than once")
    found = {key: values[0].strip() for key, values in options.items()}
    if found.get("auth") and found["auth"] not in AUTH:
        raise ValueError("auth is token or oauth")
    host = (parts.hostname or "").rstrip(".").lower()
    if host and not _HOST.fullmatch(host):
        raise ValueError("a Databricks url's host is a host name: letters, digits, dots and hyphens")
    return DatabricksURL(
        host=host,
        http_path=found.get("http_path", ""),
        catalog=found.get("catalog", ""),
        schema=found.get("schema", ""),
        auth=found.get("auth", ""),
        token=unquote(parts.password or ""),
    )


@dataclass(frozen=True)
class Connection:
    """What a connection is opened with. ``token`` is empty when it signs in through the browser."""

    host: str
    http_path: str
    catalog: str
    schema: str
    oauth: bool
    token: str

    def __repr__(self) -> str:  # never the token
        return f"Connection(host={self.host!r}, http_path={self.http_path!r}, oauth={self.oauth})"


def connection_for(source: Optional[str], public_url: str) -> Connection:
    """How a source is reached from this machine; see the module's text for the rules.

    :param source: The source's name, by which the machine's URL is found.
    :param public_url: Its URL as the manifest, or another pipeline's
        record, has it. Its host is a check; a user or a password in it is
        never used.
    :raises chartbook.backends.BackendError: If this machine does not say enough to connect,
        or names another host than the manifest. The message never holds a
        token.
    """
    try:
        public = parse_url(public_url)
    except ValueError as error:
        raise BackendError(f"The source {source!r} has a url ChartBook cannot read: {error}.") from None
    variable = source_env_var(source) if source else None
    machine_text = machine_source_url(source) if source else None
    machine = None
    if machine_text:
        where = f"{variable} or ~/.chartbook/sources.toml"
        try:
            machine = parse_url(machine_text)
        except ValueError as error:
            raise BackendError(f"The machine's url for the source {source!r}, from {where}: {error}.") from None
        if not machine.host:
            raise BackendError(f"The machine's url for the source {source!r}, from {where}, names no host.")
        host = machine.host
    else:
        where = "DATABRICKS_HOST"
        host = host_of(os.environ.get("DATABRICKS_HOST", ""))
        if os.environ.get("DATABRICKS_HOST", "").strip() and not host:
            raise BackendError(
                "DATABRICKS_HOST is not a workspace's address: it is the host, as "
                "dbc-a1b2c3d4-e5f6.cloud.databricks.com or https://adb-123.azuredatabricks.net/."
            )
        if not host:
            named = f" ({public.host})" if public.host else ""
            raise BackendError(
                f"The source {source!r} is in Databricks, and this machine names no workspace{named}. "
                f"Set DATABRICKS_HOST to the workspace's host and DATABRICKS_TOKEN to an access token, "
                f"or give the whole url in {variable or 'CHARTBOOK_SOURCE_<NAME>_URL'}: "
                f"databricks://token:<token>@<host>?http_path=<the warehouse's HTTP path>."
            )
    if public.host and public.host != host:
        raise BackendError(
            f"The source {source!r} names the workspace {public.host}, and this machine's, from {where}, "
            f"is {host}. A token is sent only to the workspace this machine names: point {where} at "
            f"{public.host}, or change the url the pipeline names."
        )
    token = machine.token if machine else ""
    named = os.environ.get("DATABRICKS_HOST", "").strip()
    if not token and (not named or host_of(named) == host):
        # DATABRICKS_TOKEN is for DATABRICKS_HOST's workspace, or for whichever this machine names
        token = os.environ.get("DATABRICKS_TOKEN", "").strip()
    # How to sign in is the machine's to say, never a manifest's or a record's
    oauth = bool(machine and machine.auth == "oauth")
    if not oauth and not token:
        raise BackendError(
            f"The source {source!r} is in the Databricks workspace {host}, and this machine has no token "
            f"for it. Set DATABRICKS_TOKEN to an access token (in the workspace: your user name, "
            f"Settings, Developer, Access tokens), or put it in {variable or 'CHARTBOOK_SOURCE_<NAME>_URL'} "
            f"as databricks://token:<token>@{host}?http_path=…; or, to sign in through the browser, set "
            f"{variable or 'CHARTBOOK_SOURCE_<NAME>_URL'} to databricks://{host}?auth=oauth."
        )
    http_path = (machine.http_path if machine else "") or public.http_path or os.environ.get("DATABRICKS_HTTP_PATH", "").strip()
    if not http_path:
        raise BackendError(
            f"The source {source!r} names no SQL warehouse. Add http_path=<the warehouse's HTTP path> to "
            f"its url, or set DATABRICKS_HTTP_PATH; the warehouse's Connection details show it."
        )
    return Connection(
        host=host,
        http_path=http_path,
        catalog=(machine.catalog if machine else "") or public.catalog,
        schema=(machine.schema if machine else "") or public.schema,
        oauth=oauth,
        token="" if oauth else token,
    )


class DatabricksBackend(Backend):
    """A Databricks SQL warehouse, reached with the Databricks SQL connector.

    A connection is opened for each thing asked and closed after it; a lazy
    frame opens its own when it is collected.
    """

    name = "databricks"

    @staticmethod
    def check_url(url: str) -> None:
        """A manifest's URL: what :func:`parse_url` takes, with no user, no token, and no way of signing in.

        The message never repeats what was before the ``@``, which is
        looked for before the url is read at all.
        """
        before_options = url.split("?", 1)[0].split("#", 1)[0]
        if "@" in before_options or "\\" in before_options:
            raise ValueError(
                "the url names a user or a token before the host. A manifest is committed, so its url "
                "holds the public part only; the machine supplies the token, in DATABRICKS_TOKEN, "
                "CHARTBOOK_SOURCE_<NAME>_URL or ~/.chartbook/sources.toml."
            )
        parsed = parse_url(url)
        netloc = urlsplit(url).netloc
        if "@" in netloc or "\\" in netloc:
            raise ValueError(
                "the url names a user or a token before the host. A manifest is committed, so its url "
                "holds the public part only; the machine supplies the token, in DATABRICKS_TOKEN, "
                "CHARTBOOK_SOURCE_<NAME>_URL or ~/.chartbook/sources.toml."
            )
        if parsed.auth:
            raise ValueError(
                "the url says how to sign in, and that is the machine's to say: put auth=oauth in "
                "CHARTBOOK_SOURCE_<NAME>_URL or ~/.chartbook/sources.toml."
            )

    def engine(self) -> tuple:
        # The machine's URL for the source names the workspace, so two
        # sources are two engines even when their public URLs are the same
        return (self.name, self.url, self.source)

    def connect(self):
        """A connection of the Databricks SQL connector, signed in as this machine says.

        :raises chartbook.backends.BackendError: If the connector is not installed, this
            machine does not say enough, this is a build of files from a
            store, or the warehouse refuses.
        """
        refuse_in_an_untrusted_build()
        try:
            from databricks import sql as databricks_sql
        except ImportError:
            raise BackendError(
                f"The source {self.source!r} is in Databricks, and the Databricks SQL connector is not "
                f"installed: `pip install chartbook[databricks]` installs it."
            ) from None
        connection = connection_for(self.source, self.url)
        try:
            # The arguments are made in a function of their own, so that no
            # frame here holds the token for a traceback to show
            return databricks_sql.connect(**_arguments(connection))
        except Exception as error:  # noqa: BLE001 - the connector's own errors, whatever they are
            said = str(error).replace(connection.token, "<token>") if connection.token else str(error)
        # Raised out here, so that the connector's error, which may hold the
        # token, is not carried along as the context of this one
        raise BackendError(f"Cannot connect to the Databricks workspace {connection.host}: {said}")

    def ref(self, location: "Location") -> str:
        """A table as a quoted identifier, each part between backticks; a query as a sub-select.

        :raises chartbook.backends.BackendError: For a file, which the warehouse cannot read.
        """
        if location.kind == "table":
            if getattr(location, "version", None) is not None:
                return f"{quote_identifier(location.identifier, '`')} VERSION AS OF {int(location.version)}"
            return quote_identifier(location.identifier, "`")
        if location.kind == "query":
            return subselect(location.sql)
        raise BackendError(
            f"A Databricks warehouse cannot read a file of this machine, {getattr(location, 'path', location)}."
        )

    def _run(self, query: str, answer, note: str = ""):
        """Run *query* on a connection of its own and return ``answer(cursor)``; the engine's errors as BackendError.

        *note* is added to an error of the statements, not to one of connecting.
        """
        connection = self.connect()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(query)
                return answer(cursor)
            finally:
                cursor.close()
        except BackendError:
            raise
        except Exception as error:  # noqa: BLE001 - the warehouse's own message
            raise BackendError(f"{error}\n{note}" if note else str(error)) from None
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - closed already, or the session timed out
                pass

    def scan(self, location: "Location"):
        """A table or a query, as a Polars LazyFrame; a pinned version after :meth:`check_pin`."""
        version = getattr(location, "version", None)
        if version is None:
            return self.sql(f"select * from {self.ref(location)}")
        self.check_pin(location)
        note = GONE.format(identifier=location.identifier, version=version)
        try:
            # Checked again when the frame is collected, which may be much later
            return self.sql(f"select * from {self.ref(location)}", note=note, recheck=(location,))
        except BackendError as error:
            raise BackendError(f"{error}\n{note}") from None

    def check_pin(self, location: "Location") -> None:
        """Refuse a pinned version that is not of the table that was pinned.

        The table's id (``describe detail``) is the one pinned; or, where it
        is not, the table's history still has the pinned version, written
        when the pin says. So a table made again with its history kept, as
        ``create or replace`` makes one, still serves its pins, and a table
        dropped and made again under the same name does not, whatever
        versions it has reached since. The history is read back from the
        newest version to the pinned one and no further.

        :raises chartbook.backends.BackendError: If it is not, or the warehouse cannot say.
        """
        if getattr(location, "version", None) is None:
            return
        name = quote_identifier(location.identifier, "`")

        def answer(cursor):
            now = _table_id(cursor)
            if now == location.table_id:
                return True
            seen = (location.identifier, now, location.version, location.written_at)
            if seen in _HISTORY_CHECKED:
                return True
            cursor.execute(f"describe history {name} limit 1")
            newest = _first_row(cursor).get("version")
            if not isinstance(newest, int) or isinstance(newest, bool) or newest < location.version:
                return False
            if newest - location.version >= HISTORY_LIMIT:
                raise BackendError(
                    f"{location.identifier} was made again since it was pinned at version {location.version}, "
                    f"and {newest - location.version} versions have been written since: too many to look "
                    f"through for the one pinned. {REPIN}"
                )
            cursor.execute(f"describe history {name} limit {newest - location.version + 1}")
            columns = [column[0] for column in cursor.description or []]
            for row in reversed(cursor.fetchall()):  # the oldest is last
                entry = dict(zip(columns, row))
                if entry.get("version") == location.version:
                    same = bool(location.written_at) and _when(entry.get("timestamp")) == location.written_at
                    if same:
                        _HISTORY_CHECKED.add(seen)
                    return same
            return False

        pinned = f"{location.identifier} is pinned at version {location.version}."
        if not self._run(f"describe detail {name}", answer, note=f"{pinned} {REPIN}"):
            raise BackendError(
                f"{location.identifier} is not the table that was pinned at version {location.version}: its id "
                f"has changed, and its history does not have that version as it was (it was dropped and made "
                f"again, or its history no longer reaches back that far). {REPIN}"
            )

    def version_of(self, location: "Location") -> Optional[dict]:
        """A Delta table's current version: its number, the table's id and full name, when it was written.

        ``describe detail`` gives the format, the id and the full name, so a
        name declared in one or two parts is pinned in three, whatever
        catalog the reader's connection starts in (from the session's
        catalog and schema, where it does not give one); ``describe
        history`` with ``limit 1`` gives the newest version; and that
        version is read once, with no rows. None for a view, a table that
        is not Delta, a materialized view, a streaming table or a table
        with a row filter, as the warehouse says: by its format, or by an
        error whose class or SQLSTATE says the feature is not supported
        (:func:`_has_no_versions`). An error in connecting is never that.

        :raises chartbook.backends.BackendError: For any other failure: the
            warehouse cannot be reached, the table is not there, or this
            user may not read its history.
        """
        if location.kind != "table":
            return None
        name = quote_identifier(location.identifier, "`")
        connection = self.connect()  # an error here is said as it is, never "no versions"
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(f"describe detail {name}")
                detail = _first_row(cursor)
                if str(detail.get("format") or "").lower() != "delta" or not detail.get("id"):
                    return None
                cursor.execute(f"describe history {name} limit 1")
                history = _first_row(cursor)
                version = history.get("version")
                if not isinstance(version, int) or isinstance(version, bool):
                    return None
                cursor.execute(f"select * from {name} VERSION AS OF {version} limit 0")
                cursor.fetchall_arrow()
                full = str(detail.get("name") or "")
                if not (TABLE_IDENTIFIER.fullmatch(full) and "`" not in full and full.count(".") == 2):
                    full = _in_full(cursor, location.identifier)
                return {
                    "version": version,
                    "table_id": str(detail["id"]),
                    "name": full,
                    "written_at": _when(history.get("timestamp")),
                }
            finally:
                cursor.close()
        except BackendError:
            raise
        except Exception as error:  # noqa: BLE001 - the warehouse's own message
            if _has_no_versions(str(error)):
                return None
            raise BackendError(str(error)) from None
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass

    def sql(self, query: str, note: str = "", recheck=()):
        """Run SQL in the warehouse, as a Polars LazyFrame; *note* is added to an error found while collecting.

        *recheck*, the locations pinned by a version that the query reads,
        are checked again (:meth:`check_pin`) each time the frame is
        collected, which may be long after it was made.

        The warehouse binds it now (``select * from (…) limit 0``), so a name
        it does not know is refused at once, and its columns are the
        frame's schema; should the connector give an empty result no
        columns, one row is asked for instead, and failing that the schema
        is read from the type names the warehouse gives. Collecting the
        frame runs it, and each batch is checked against that schema. An
        error found while collecting comes as Polars' ``ComputeError``
        with the warehouse's message in it, or as the
        :class:`~chartbook.backends.BackendError` itself, by Polars version.

        :raises chartbook.backends.BackendError: If the warehouse refuses the query, with its message.
        """
        import polars as pl
        from polars.io.plugins import register_io_source

        def columns(cursor):
            return cursor.fetchall_arrow(), list(cursor.description or [])

        empty, described = self._run(f"select * from {subselect(query)} limit 0", columns)
        names = [column[0] for column in described]
        if list(empty.column_names) != names:
            empty, described = self._run(f"select * from {subselect(query)} limit 1", columns)
            names = [column[0] for column in described]
        if list(empty.column_names) == names:
            try:
                schema = pl.from_arrow(empty.slice(0, 0)).schema
            except Exception as error:  # noqa: BLE001 - a type Polars cannot take
                raise BackendError(f"Polars cannot take the query's columns: {error}") from None
        else:
            # The result is empty and the connector sent no columns with it
            schema = pl.Schema({column[0]: _polars_type(column) for column in described})

        def checked(frame, wanted):
            """A batch as the schema says it is; else what differs, said, rather than a frame mistyped."""
            if frame.schema != wanted:
                got = dict(frame.schema)
                differ = [name for name in wanted if got.get(name) != wanted[name]] or list(got)
                raise BackendError(
                    f"The warehouse sent {differ[0]} as {got.get(differ[0])}, and gave its type as "
                    f"{wanted.get(differ[0])} when the query was bound."
                )
            return frame

        def batches(with_columns, predicate, n_rows, batch_size):
            # Rows are asked for a batch at a time; a head with nothing
            # filtered asks the warehouse for that many and no more
            text = query if n_rows is None or predicate is not None else f"select * from {subselect(query)} limit {int(n_rows)}"
            left = n_rows
            for location in recheck:
                self.check_pin(location)
            connection = self.connect()
            try:
                cursor = connection.cursor()
                try:
                    try:
                        cursor.execute(text)
                    except Exception as error:  # noqa: BLE001 - the warehouse's own message
                        raise BackendError(f"{error}\n{note}" if note else str(error)) from None
                    while left is None or left > 0:
                        try:
                            batch = cursor.fetchmany_arrow(batch_size or BATCH_ROWS)
                        except Exception as error:  # noqa: BLE001
                            raise BackendError(f"{error}\n{note}" if note else str(error)) from None
                        if batch.num_rows == 0:
                            return
                        frame = checked(pl.from_arrow(batch), schema)
                        if predicate is not None:
                            frame = frame.filter(predicate)
                        if with_columns is not None:
                            frame = frame.select(with_columns)
                        if left is not None:
                            frame = frame.head(left)
                            left -= frame.height
                        yield frame
                finally:
                    cursor.close()
            finally:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001
                    pass

        # Each batch is checked in `checked`: validate_schema= came only in Polars 1.25
        return register_io_source(batches, schema=schema)

    def describe(self, location: "Location") -> tuple[list[dict], int]:
        """A dataframe's columns, with the warehouse's type names (``int``, ``string``, ``timestamp``), and its row count."""
        ref = self.ref(location)

        def answer(cursor):
            columns = [{"name": column[0], "dtype": str(column[1])} for column in cursor.description or []]
            cursor.fetchall_arrow()
            cursor.execute(f"select count(*) from {ref}")
            (rows,) = cursor.fetchone()
            return columns, int(rows)

        return self._run(f"select * from {ref} limit 0", answer)

    def span(self, location: "Location", column: str) -> tuple:
        """The first and last date in one column: ``try_cast(col as timestamp)``, so what is not one is null."""
        name = "`" + column.replace("`", "``") + "`"
        ref = self.ref(location)
        return self._run(
            f"select min(try_cast({name} as timestamp)), max(try_cast({name} as timestamp)) from {ref}",
            lambda cursor: tuple(cursor.fetchone()),
        )


def _arguments(connection: Connection) -> dict:
    """What the connector's ``connect()`` is given for a connection."""
    arguments = {
        "server_hostname": connection.host,
        "http_path": connection.http_path,
        "user_agent_entry": "chartbook",
    }
    if connection.oauth:
        arguments["auth_type"] = "databricks-oauth"
        arguments["experimental_oauth_persistence"] = _SIGNED_IN
    else:
        arguments["access_token"] = connection.token
    if connection.catalog:
        arguments["catalog"] = connection.catalog
    if connection.schema:
        arguments["schema"] = connection.schema
    return arguments


#: The Polars type of a column of each Databricks type a schema can be read from by name.
_TYPES = {
    "tinyint": "Int8", "byte": "Int8", "smallint": "Int16", "short": "Int16", "int": "Int32", "integer": "Int32",
    "bigint": "Int64", "long": "Int64", "float": "Float32", "double": "Float64", "string": "String",
    "boolean": "Boolean", "date": "Date", "binary": "Binary", "void": "Null",
}


def _polars_type(column):
    """The Polars type of a column from what ``cursor.description`` says of it.

    For an empty result the connector sent no columns with. A type that
    cannot be read from its name (an array, a map, a struct, an interval)
    is refused, naming the column.

    :raises chartbook.backends.BackendError: For such a type.
    """
    import polars as pl

    name, kind = column[0], str(column[1] or "").lower()
    if kind in _TYPES:
        return getattr(pl, _TYPES[kind])
    if kind == "timestamp":
        return pl.Datetime("us", "UTC")
    if kind == "timestamp_ntz":
        return pl.Datetime("us")
    if kind == "decimal" and isinstance(column[4], int) and isinstance(column[5], int):
        return pl.Decimal(column[4], column[5])
    raise BackendError(
        f"The query's result is empty, the warehouse sent no columns with it, and the type of "
        f"{name}, {kind or 'not given'}, cannot be read from its name."
    )


def _table_id(cursor) -> str:
    """The ``id`` column of what ``describe detail`` gave."""
    columns = [column[0] for column in cursor.description or []]
    row = cursor.fetchone()
    return str(dict(zip(columns, row or ())).get("id") or "")


def _first_row(cursor) -> dict:
    """The first row of what was run, by column name; empty if there is none."""
    columns = [column[0] for column in cursor.description or []]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row is not None else {}


def _when(value) -> str:
    """When a version was written, as text: in UTC when the warehouse says the zone, else as it says it."""
    from datetime import timezone

    if hasattr(value, "astimezone") and getattr(value, "tzinfo", None) is not None:
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _has_no_versions(message: str) -> bool:
    """Whether the warehouse's error says the thing has no versions a pin can name.

    By the class the message begins with, which must be one of
    :data:`NO_VERSIONS_CLASSES` or a subclass of one; where the message
    begins with no class, by the SQLSTATE it ends with, ``0A000`` (not
    supported) or ``42809`` (the wrong kind of object). Never by words
    elsewhere in the message, which may name a table or a schema, and
    never by a class or state that is not supported on one warehouse and
    is on another.
    """
    found = _ERROR_CLASS.match(message)
    if found:
        name = found.group(1)
        return any(name == known or name.startswith(known + ".") for known in NO_VERSIONS_CLASSES)
    state = _SQLSTATE.search(message.strip())
    return bool(state) and state.group(1) in ("0A000", "42809")


def _in_full(cursor, identifier: str) -> str:
    """A table's name in three parts: as declared if it has them, else in the session's catalog and schema.

    :raises chartbook.backends.BackendError: If the session does not say them.
    """
    from chartbook.backends import TABLE_IDENTIFIER

    parts = identifier.split(".")
    if len(parts) == 3:
        return identifier
    cursor.execute("select current_catalog(), current_schema()")
    row = cursor.fetchone() or (None, None)
    full = ".".join([str(part) for part in row if part][: 3 - len(parts)] + parts)
    if full.count(".") != 2 or not TABLE_IDENTIFIER.fullmatch(full) or "`" in full:
        raise BackendError(f"The warehouse did not say which catalog and schema {identifier} is in.")
    return full
