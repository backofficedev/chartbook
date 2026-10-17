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
nothing but ``select`` on its own account; the SQL a person runs through
``data.sql()`` or ``data.connect()`` is between them and the warehouse.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from chartbook.backends import (
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

#: A workspace's host: letters, digits, dots and hyphens, and nothing a message could carry besides.
_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")


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
        name = urlsplit(text if "://" in text else "https://" + text).hostname or ""
    except ValueError:
        return ""
    name = name.rstrip(".").lower()
    return name if _HOST.fullmatch(name) else ""


def parse_url(url: str) -> DatabricksURL:
    """Read a ``databricks://[token:<token>@]<host>?http_path=…&catalog=…&schema=…&auth=…`` URL.

    :raises ValueError: If it is not one: another scheme, a host that is
        not a host name, a path after the host, a port, an option that is
        not one of :data:`URL_OPTIONS`, an option given twice, a fragment,
        or an ``auth`` that is not ``token`` or ``oauth``. The message
        never repeats a token.
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
            f"a Databricks url names the host and nothing after it; the warehouse's HTTP path "
            f"goes after ?, as databricks://{parts.hostname or '<host>'}?http_path={parts.path}"
        )
    try:
        port = parts.port
    except ValueError:
        port = -1
    if port is not None:
        raise ValueError("a Databricks url names the host without a port: the workspace is reached on 443")
    options = parse_qs(parts.query, keep_blank_values=True)
    unknown = sorted(set(options) - set(URL_OPTIONS))
    if unknown:
        raise ValueError(
            f"a Databricks url takes {', '.join(URL_OPTIONS)} after ?, and not {', '.join(unknown)}"
        )
    twice = sorted(key for key, values in options.items() if len(values) > 1)
    if twice:
        raise ValueError(f"a Databricks url gives {', '.join(twice)} more than once")
    found = {key: values[0].strip() for key, values in options.items()}
    if found.get("auth") and found["auth"] not in AUTH:
        raise ValueError(f"auth is token or oauth, not {found['auth']!r}")
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
    if not token and host_of(os.environ.get("DATABRICKS_HOST", "")) in ("", host):
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

        The message never repeats what was before the ``@``.
        """
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
            raise BackendError(f"Cannot connect to the Databricks workspace {connection.host}: {said}") from None

    def ref(self, location: "Location") -> str:
        """A table as a quoted identifier, each part between backticks; a query as a sub-select.

        :raises chartbook.backends.BackendError: For a file, which the warehouse cannot read.
        """
        if location.kind == "table":
            return quote_identifier(location.identifier, "`")
        if location.kind == "query":
            return subselect(location.sql)
        raise BackendError(
            f"A Databricks warehouse cannot read a file of this machine, {getattr(location, 'path', location)}."
        )

    def _run(self, query: str, answer):
        """Run *query* on a connection of its own and return ``answer(cursor)``; the engine's errors as BackendError."""
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
            raise BackendError(str(error)) from None
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - closed already, or the session timed out
                pass

    def sql(self, query: str):
        """Run SQL in the warehouse, as a Polars LazyFrame.

        The warehouse binds it now (``select * from (…) limit 0``), so a name
        it does not know is refused at once, and its columns are the
        frame's schema; should the connector give an empty result no
        columns, one row is asked for instead. Collecting the frame runs
        it, and each batch is checked against that schema. An error found
        while collecting comes as Polars' ``ComputeError``, with the
        warehouse's message in it.

        :raises chartbook.backends.BackendError: If the warehouse refuses the query, with its message.
        """
        import polars as pl
        from polars.io.plugins import register_io_source

        def columns(cursor):
            return cursor.fetchall_arrow(), [column[0] for column in cursor.description or []]

        empty, names = self._run(f"select * from {subselect(query)} limit 0", columns)
        if list(empty.column_names) != names:
            empty, names = self._run(f"select * from {subselect(query)} limit 1", columns)
            if list(empty.column_names) != names:
                raise BackendError(
                    f"The warehouse gave the query's columns as {', '.join(names) or 'none'} and its rows "
                    f"with {', '.join(empty.column_names) or 'none'}, so the frame's schema is not known."
                )
        try:
            schema = pl.from_arrow(empty.slice(0, 0)).schema
        except Exception as error:  # noqa: BLE001 - a type Polars cannot take
            raise BackendError(f"Polars cannot take the query's columns: {error}") from None

        def batches(with_columns, predicate, n_rows, batch_size):
            # Rows are asked for a batch at a time; a head with nothing
            # filtered asks the warehouse for that many and no more
            text = query if n_rows is None or predicate is not None else f"select * from {subselect(query)} limit {int(n_rows)}"
            left = n_rows
            connection = self.connect()
            try:
                cursor = connection.cursor()
                try:
                    try:
                        cursor.execute(text)
                    except Exception as error:  # noqa: BLE001 - the warehouse's own message
                        raise BackendError(str(error)) from None
                    while left is None or left > 0:
                        try:
                            batch = cursor.fetchmany_arrow(batch_size or BATCH_ROWS)
                        except Exception as error:  # noqa: BLE001
                            raise BackendError(str(error)) from None
                        if batch.num_rows == 0:
                            return
                        frame = pl.from_arrow(batch)
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

        return register_io_source(batches, schema=schema, validate_schema=True)

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
