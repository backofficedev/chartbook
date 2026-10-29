"""The formats a dataframe's file can be in, and the one reader of them.

A dataframe that is a file is stored as parquet, CSV (or TSV), JSON lines
(NDJSON, gzipped or not) or Arrow IPC (Feather). Its entry may say which::

    [dataframes.releases]
    path = "./_data/releases/*.jsonl.gz"
    format = "jsonl"                                # else the path's ending says
    read_options = { infer_schema_length = 10000 }

With no ``format``, the ending of the path says it (:data:`ENDINGS`), and a
path whose ending names none, a folder among them, is parquet. A glob is
read as its ending says, and a folder as the files in it of its format.
``read_options`` go to the reader of a CSV or JSON lines file, by polars'
names; :data:`READ_OPTIONS` lists the ones taken, and DuckDB is given each
under its own name, so that ``data.sql()`` reads a file as ``data.load()``
does.

This module is where a file becomes a table. ``data.load()`` in every
``format=`` it offers, ``data.sql()`` and ``data.ref()``, the dataframe's
page, the data glimpses and the data dictionary all read through it, so
each reads a file as the others do. Hashing, snapshots and pins do not come
into it: they keep bytes, whatever the bytes are.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Union

from chartbook.errors import UnreadableTableError
from chartbook.utils import is_glob_pattern

#: The formats a dataframe's file is read in, as ``format`` names them.
FORMATS = ("parquet", "csv", "jsonl", "ipc")

#: What each is called in a sentence.
NAMES = {"parquet": "parquet", "csv": "CSV", "jsonl": "JSON lines", "ipc": "Arrow IPC"}

#: The endings of a file's name that say its format. A gzipped CSV or JSON
#: lines file is read as it is: polars and DuckDB both undo the gzip.
ENDINGS = {
    "parquet": (".parquet",),
    "csv": (".csv", ".tsv", ".csv.gz", ".tsv.gz"),
    "jsonl": (".jsonl", ".ndjson", ".jsonl.gz", ".ndjson.gz"),
    "ipc": (".arrow", ".feather", ".ipc"),
}

#: A CSV file with one of these endings is split on tabs, unless its
#: ``read_options`` give a separator.
_TAB_ENDINGS = (".tsv", ".tsv.gz")

#: The types ``schema_overrides`` may give a column, as polars names them,
#: and DuckDB's name for each.
TYPES = {
    "String": "VARCHAR",
    "Boolean": "BOOLEAN",
    "Int8": "TINYINT",
    "Int16": "SMALLINT",
    "Int32": "INTEGER",
    "Int64": "BIGINT",
    "UInt8": "UTINYINT",
    "UInt16": "USMALLINT",
    "UInt32": "UINTEGER",
    "UInt64": "UBIGINT",
    "Float32": "FLOAT",
    "Float64": "DOUBLE",
    "Date": "DATE",
    "Datetime": "TIMESTAMP",
    "Time": "TIME",
}

#: Every option a reader may be given: what it must be, and an example.
_OPTIONS = {
    "separator": ("one character", '";"'),
    "has_header": ("true or false", "false"),
    "quote_char": ("one character", "\"'\""),
    "comment_prefix": ("one character", '"#"'),
    "skip_rows": ("a whole number, 0 or more", "2"),
    "null_values": ("a string, or a list of strings", '["NA", ""]'),
    "decimal_comma": ("true or false", "true"),
    "schema_overrides": ("a table of columns and their types", '{ zip = "String" }'),
    "infer_schema_length": ("a whole number of rows, 1 or more", "10000"),
}

#: The ``read_options`` each format takes, by polars' names. Each has a
#: DuckDB name too (:func:`sql`), which is why this is a short list and not
#: all of polars': what ``data.load()`` is given, ``data.sql()`` is given as
#: well. A parquet or Arrow IPC file keeps its own schema, and takes none.
READ_OPTIONS = {
    "parquet": (),
    "csv": tuple(_OPTIONS),
    "jsonl": ("schema_overrides", "infer_schema_length"),
    "ipc": (),
}

#: What pandas and DuckDB call some of them, for a message to give polars' name.
_OTHER_NAMES = {
    "delimiter": "separator",
    "delim": "separator",
    "sep": "separator",
    "header": "has_header",
    "quote": "quote_char",
    "quotechar": "quote_char",
    "comment": "comment_prefix",
    "skip": "skip_rows",
    "skiprows": "skip_rows",
    "nullstr": "null_values",
    "na_values": "null_values",
    "dtype": "schema_overrides",
    "dtypes": "schema_overrides",
    "types": "schema_overrides",
    "sample_size": "infer_schema_length",
}


@dataclass(frozen=True)
class Reading:
    """How a dataframe's file is read.

    Attributes:
        format: One of :data:`FORMATS`.
        options: Its ``read_options``, checked, as the entry gives them.
        said_by: What gave the format: ``"format"`` (the entry's key),
            ``"ending"`` (the path's), or ``"default"`` (nothing did, so
            parquet).
    """

    format: str
    options: Mapping = field(default_factory=dict, compare=False)
    said_by: str = "default"


def ending_of(name: Union[str, Path]) -> Optional[str]:
    """The ending of a file's name that says its format, ``.csv.gz`` say; None if it has none."""
    lowered = str(name).lower()
    for endings in ENDINGS.values():
        for ending in endings:
            if lowered.endswith(ending):
                return ending
    return None


def format_of_name(name: Union[str, Path]) -> Optional[str]:
    """The format a file's name says by its ending, or None."""
    ending = ending_of(name)
    return next((fmt for fmt, endings in ENDINGS.items() if ending in endings), None)


def format_of(path: Union[str, Path], declared=None) -> str:
    """The format a path is read in: *declared*, else its ending's, else parquet. Nothing is checked."""
    if declared in FORMATS:
        return declared
    return format_of_name(Path(str(path)).name) or "parquet"


def reading(
    path: Union[str, Path],
    format: Optional[str] = None,
    read_options: Optional[Mapping] = None,
    where: Optional[str] = None,
) -> Reading:
    """How a dataframe's file is read, from its path and what its entry says.

    :param path: Its ``path``: a file, a glob or a folder.
    :param format: Its ``format``, if it has one.
    :param read_options: Its ``read_options``, if it has them.
    :param where: What a message names: the entry, ``[dataframes.x]``; the path by default.
    :raises ValueError: If the format is not one of :data:`FORMATS`, or an
        option is not one the format takes, or not of its type.
    """
    where = where or str(path)
    if format is not None:
        if format not in FORMATS:
            raise ValueError(
                f"{where}: format = {format!r} is not a format a dataframe is read in. A dataframe's "
                f'file is "parquet", "csv" (CSV or TSV), "jsonl" (JSON lines) or "ipc" (Arrow IPC, '
                f"Feather). A file that is not a table is declared under [files], not [dataframes]."
            )
        found, said_by = format, "format"
    else:
        named = format_of_name(Path(str(path)).name)
        found, said_by = (named, "ending") if named else ("parquet", "default")
    read = Reading(found, {}, said_by)
    return Reading(found, _checked(read, path, read_options, where), said_by)


def _said(read: Reading, path) -> str:
    """What gave a path its format, as the end of a sentence."""
    if read.said_by == "format":
        return "the format its entry gives"
    if read.said_by == "ending":
        return f"the format its ending, {ending_of(Path(str(path)).name)}, says"
    return "the format of a path whose ending names none"


def _checked(read: Reading, path, options, where: str) -> dict:
    """A format's ``read_options``, each one it takes and of its type."""
    if options is None:
        return {}
    if not isinstance(options, Mapping):
        raise ValueError(
            f'{where}: read_options must be a table of the reader\'s options, e.g. read_options = {{ separator = ";" }}.'
        )
    taken = READ_OPTIONS[read.format]
    if options and not taken:
        raise ValueError(
            f"{where}: read_options are for a CSV or JSON lines file, and this one is read as "
            f"{NAMES[read.format]} ({_said(read, path)}), which keeps its own schema and takes none. "
            f'If it is CSV or JSON lines, say so: format = "csv" or "jsonl".'
        )
    for name, value in options.items():
        if name not in taken:
            known = _OTHER_NAMES.get(name)
            called = f" Polars calls it {known!r}." if known in taken else ""
            raise ValueError(
                f"{where}: read_options has {name!r}, which is not one ChartBook passes to a reader.{called} "
                f"It gives the same options to polars and to DuckDB, and for a {NAMES[read.format]} "
                f"file they are: {', '.join(taken)}."
            )
        if not _valid(name, value):
            must, example = _OPTIONS[name]
            raise ValueError(f"{where}: read_options.{name} must be {must}, e.g. {name} = {example}.")
        if name == "schema_overrides":
            for column, type_name in value.items():
                if _type(type_name) is None:
                    raise ValueError(
                        f"{where}: read_options.schema_overrides gives {column!r} the type "
                        f"{type_name!r}, which is not one ChartBook knows. The types are: "
                        f"{', '.join(TYPES)}."
                    )
    return dict(options)


def _valid(name: str, value) -> bool:
    """Whether a value is of the type its option takes."""
    if name in ("separator", "quote_char", "comment_prefix"):
        return isinstance(value, str) and len(value) == 1
    if name in ("has_header", "decimal_comma"):
        return isinstance(value, bool)
    if name in ("skip_rows", "infer_schema_length"):
        least = 1 if name == "infer_schema_length" else 0
        return isinstance(value, int) and not isinstance(value, bool) and value >= least
    if name == "null_values":
        return isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))
    if name == "schema_overrides":
        return isinstance(value, Mapping) and all(isinstance(v, str) for v in value.values())
    return False


def _type(name: str) -> Optional[str]:
    """A type's name as :data:`TYPES` has it, whatever its capitals; None for one it lacks."""
    return next((known for known in TYPES if known.lower() == str(name).lower()), None)


def check_entry(entry: Mapping, where: str) -> None:
    """Refuse a dataframe's ``format`` or ``read_options`` that cannot be read, before anything reads them.

    They go with a ``path``: a table or a query in a source is read by its
    engine. The format is the entry's, else its path's ending's, as
    :func:`reading` has it.

    :param entry: The ``[dataframes.<name>]`` table.
    :param where: The entry, for the message.
    :raises ValueError: Saying what is wrong and what to write.
    """
    given = [key for key in ("format", "read_options") if key in entry]
    if not given:
        return
    if "table" in entry or "query" in entry:
        kind = "table" if "table" in entry else "query"
        raise ValueError(
            f"{where} has {' and '.join(given)}, and is a {kind} in a source. They are for a "
            f"file; a source's engine reads its own tables."
        )
    reading(entry.get("path") or "", entry.get("format"), entry.get("read_options"), where)


def declared(entry) -> dict:
    """An entry's ``format`` and ``read_options``, as it gives them: what a record of its location keeps.

    A pipeline that reads another's pin has none of the owner's manifest to
    look in, and reads the bytes as their owner said to.
    """
    if not isinstance(entry, Mapping):
        return {}
    return {key: entry[key] for key in ("format", "read_options") if key in entry}


def reading_of(location, where: Optional[str] = None) -> Reading:
    """How a file location is read (:class:`chartbook.resolve.FileLocation`)."""
    return reading(location.path, getattr(location, "format", None), getattr(location, "read_options", None), where)


# --- What a read opens ----------------------------------------------------


def _visible(parts) -> bool:
    """Whether a file in a folder is one a read takes: not one named as an engine passes over, ``.`` or ``_``."""
    return not any(part.startswith((".", "_")) for part in parts)


def _sources(path: Path, read: Reading, files=(), listed=()) -> Union[str, list[str]]:
    """What the reader opens: a file or a glob as it is, or the files of a folder that are of its format.

    A folder pinned from another pipeline is read as the files its record
    lists, *listed* (for parquet, the ones :func:`chartbook.resolve._held`
    found to be tables, *files*); a folder here, as the files in it.

    :raises UnreadableTableError: For a folder with no file of its format.
    """
    path = Path(path)
    is_folder = not is_glob_pattern(str(path)) and path.is_dir()
    if read.format == "parquet":
        if files:
            return [str(file) for file in files]
        if listed:
            raise UnreadableTableError(path, read.format, _nothing(path, listed, read, pinned=True))
        if is_folder:
            from chartbook.utils import directory_tables

            found = directory_tables(path)
            if not found:
                raise UnreadableTableError(path, read.format, _nothing(path, _names(path), read))
            return [str(file) for file in found]
        return str(path)
    endings = ENDINGS[read.format]
    if listed:
        from chartbook.store import on_disk, plain_parts

        chosen = []
        for relative in listed:
            parts = plain_parts(relative)
            if parts and _visible(parts) and parts[-1].lower().endswith(endings):
                chosen.append(str(on_disk(path, parts)))
        if not chosen:
            raise UnreadableTableError(path, read.format, _nothing(path, listed, read, pinned=True))
        return sorted(chosen)
    if is_folder:
        names = _names(path)
        chosen = [str(path.joinpath(*name.split("/"))) for name in names if name.lower().endswith(endings)]
        if not chosen:
            raise UnreadableTableError(path, read.format, _nothing(path, names, read))
        return chosen
    return str(path)


def _names(folder: Path) -> list[str]:
    """The files of a folder a read may take, by their path in it with ``/``, in order."""
    from chartbook import hashing

    relative = (file.relative_to(folder) for file in hashing.directory_files(folder))
    return sorted(part.as_posix() for part in relative if _visible(part.parts))


def _nothing(path: Path, names, read: Reading, pinned: bool = False) -> str:
    """Why a folder has nothing to read in its format, and what to say if its files are of another."""
    others = sorted({format_of_name(name) for name in names} - {None, read.format})
    hint = ""
    if others:
        kinds = " and ".join(NAMES[fmt] for fmt in others)
        keys = " or ".join('format = "' + fmt + '"' for fmt in others)
        hint = f" It holds {kinds} files: if they are the table, its entry in [dataframes] says so with {keys}."
    if pinned and read.format == "parquet":
        from chartbook.resolve import FileLocation, nothing_to_read

        return (nothing_to_read(FileLocation(path, (), listed=tuple(names))) or "") + hint
    unless = ", and a folder is read as parquet unless its entry's format says otherwise" if read.said_by == "default" else ""
    return f"The folder {path.name!r} holds no {NAMES[read.format]} file{unless}.{hint}"


def files_of(path: Union[str, Path], read: Reading, files=(), listed=()) -> list[Path]:
    """The files a read of a path opens: the file, the glob's matches, or a folder's files of its format.

    Empty when there are none yet: nothing built, or a folder with no file
    of its format.
    """
    try:
        sources = _sources(Path(path), read, files, listed)
    except UnreadableTableError:
        return []
    if isinstance(sources, list):
        return [Path(source) for source in sources]
    if is_glob_pattern(sources):
        return sorted(Path(match) for match in glob.glob(sources, recursive=True) if os.path.isfile(match))
    return [Path(sources)] if os.path.isfile(sources) else []


# --- Reading ----------------------------------------------------------------


def _polars_options(read: Reading, sources) -> dict:
    """The ``read_options`` as polars takes them: types as polars' own, and a TSV split on tabs."""
    import polars as pl

    options = dict(read.options)
    if "schema_overrides" in options:
        options["schema_overrides"] = {
            column: getattr(pl, _type(type_name)) for column, type_name in options["schema_overrides"].items()
        }
    if read.format == "csv" and "separator" not in options and _tab_separated(sources):
        options["separator"] = "\t"
    return options


def _tab_separated(sources) -> bool:
    """Whether every file a CSV read opens is named as a TSV is."""
    names = [sources] if isinstance(sources, str) else list(sources)
    return bool(names) and all(str(name).lower().endswith(_TAB_ENDINGS) for name in names)


def _scan(read: Reading, sources):
    """The polars scan of a format's files, unchecked."""
    import polars as pl

    if read.format == "parquet":
        return pl.scan_parquet(sources, hive_partitioning=True)
    if read.format == "ipc":
        return pl.scan_ipc(sources, hive_partitioning=True)
    if read.format == "csv":
        return pl.scan_csv(sources, **_polars_options(read, sources))
    return pl.scan_ndjson(sources, **_polars_options(read, sources))


def scan(
    path: Union[str, Path],
    format: Optional[str] = None,
    read_options: Optional[Mapping] = None,
    *,
    files=(),
    listed=(),
    where: Optional[str] = None,
):
    """A dataframe's file as a polars LazyFrame, read as its format is.

    Parquet with ``pl.scan_parquet``, CSV with ``pl.scan_csv``, JSON lines
    with ``pl.scan_ndjson`` and Arrow IPC with ``pl.scan_ipc``; a glob or a
    folder as one frame, with Hive's ``key=value`` folders as columns for
    parquet and Arrow IPC (polars reads no such columns from CSV or JSON
    lines, and DuckDB is told not to either). The schema is read here, so
    that a file that is not of its format is said now, by name: the footer
    of a parquet or Arrow IPC file, the first rows of a CSV or JSON lines
    one (``infer_schema_length`` of them, 100 by default). A gzipped file is
    decompressed whole, in memory, each time it is read, here included.

    :param path: The file, glob or folder.
    :param format: The entry's ``format``, if it has one.
    :param read_options: The entry's ``read_options``, if it has them.
    :param files: For a folder pinned from another pipeline, the parquet
        files its record lists (:class:`chartbook.resolve.FileLocation`).
    :param listed: And every file it lists, by its path in the folder.
    :param where: What a message names first: ``"Dataframe 'rates'"``.
    :raises FileNotFoundError: If the file is not there, or a glob matches no file.
    :raises UnreadableTableError: If it cannot be read as its format, or a
        folder holds no file of it.
    :raises ValueError: If the format or an option is not one ChartBook reads.
    """
    import polars as pl

    read = reading(path, format, read_options, where)
    sources = _sources(Path(path), read, files, listed)
    try:
        frame = _scan(read, sources)
        frame.collect_schema()
    except FileNotFoundError:
        raise
    except (pl.exceptions.PolarsError, OSError) as error:
        shown = f"{where}: {path}" if where else str(path)
        if isinstance(sources, str) and is_glob_pattern(sources) and not files_of(sources, read):
            raise FileNotFoundError(f"{shown} matches no file yet.") from None
        raise UnreadableTableError(path, read.format, _unreadable(shown, path, read, sources)) from error
    return frame


def scan_location(location, where: Optional[str] = None):
    """A file location as a polars LazyFrame (:func:`scan`)."""
    return scan(
        location.path,
        getattr(location, "format", None),
        getattr(location, "read_options", None),
        files=location.files,
        listed=location.listed,
        where=where,
    )


def to_pandas(location, where: Optional[str] = None):
    """A file location as a pandas DataFrame.

    A parquet file or folder is read as pandas reads one, with a folder's
    Hive keys as categories, and the folder as the parts :func:`scan` reads
    of it. Everything else, a glob among them, is read as :func:`scan` reads
    it and collected.
    """
    frame = scan_location(location, where)  # says now if it cannot be read
    read = reading_of(location, where)
    if read.format != "parquet" or is_glob_pattern(str(location.path)):
        return frame.collect().to_pandas()
    sources = _sources(Path(location.path), read, location.files, location.listed)
    if isinstance(sources, list):
        import pyarrow.dataset as ds

        # As pandas reads a folder: hive partitions as categories
        partitioning = ds.HivePartitioning.discover(infer_dictionary=True)
        return ds.dataset(sources, format="parquet", partitioning=partitioning, partition_base_dir=str(location.path)).to_table().to_pandas()
    import pandas as pd

    return pd.read_parquet(location.path)


def _unreadable(shown: str, path, read: Reading, sources) -> str:
    """What to say of a file that cannot be read as its format."""
    text = f"{shown} could not be read as {NAMES[read.format]}, {_said(read, path)}."
    begins = _begins_as(sources) if isinstance(sources, str) and not is_glob_pattern(sources) else None
    if begins and begins != read.format:
        article = "an" if NAMES[begins][0] in "AEIOU" else "a"
        text += (
            f' It begins as {article} {NAMES[begins]} file does: if that is what it is, its entry '
            f'in [dataframes] says so with format = "{begins}".'
        )
    else:
        text += (
            ' If it is a table stored another way, its entry in [dataframes] says which with '
            'format = "parquet", "csv", "jsonl" or "ipc".'
        )
    return text + " A file that is not a table is declared under [files], not [dataframes]."


def _begins_as(file: str) -> Optional[str]:
    """The format a file's first bytes say, for the two that mark their files: parquet and Arrow IPC."""
    try:
        with open(file, "rb") as f:
            head = f.read(6)
    except OSError:
        return None
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"ARROW1"):
        return "ipc"
    return None


# --- In SQL -----------------------------------------------------------------


def sql(location) -> str:
    """A file as DuckDB reads it in SQL: ``read_parquet('…')``, ``read_csv('…', …)`` or ``read_json('…', …)``.

    The options DuckDB is given are the entry's ``read_options`` under
    DuckDB's names, with its separator and header said always, so that it
    does not guess them otherwise than polars does. A CSV or JSON lines file
    has no Hive columns, as polars reads none. Each engine infers what it is
    not told in its own way (DuckDB finds dates in text, polars does not);
    ``schema_overrides`` gives a column one type in both.

    :raises ValueError: For an Arrow IPC file, which DuckDB has no reader of
        its own for (``data.sql()`` hands it the file itself,
        :func:`arrow_dataset`); or a folder with no file of its format.
    """
    from chartbook.backends import quote_literal

    read = reading_of(location)
    path = Path(location.path)
    if read.format == "ipc":
        raise ValueError(
            f"{path.name} is an Arrow IPC file, which DuckDB reads with no function of its own, so "
            f"there is no text to stand for it in SQL. data.sql() hands DuckDB the file itself, and "
            f"data.load() reads it."
        )
    sources = _sources(path, read, location.files, location.listed)
    if isinstance(sources, list):
        # With / on every system: DuckDB reads it so on Windows too, and SQL
        # with a path in it reads the same wherever it is pasted
        text = "[" + ", ".join(quote_literal(Path(source).as_posix()) for source in sources) + "]"
    else:
        text = quote_literal(Path(sources).as_posix())
    if read.format == "parquet":
        if isinstance(sources, list) or is_glob_pattern(text):
            return f"read_parquet({text}, hive_partitioning = true)"
        return f"read_parquet({text})"
    options = read.options
    overrides = {column: TYPES[_type(type_name)] for column, type_name in (options.get("schema_overrides") or {}).items()}
    if read.format == "csv":
        separator = options.get("separator", "\t" if _tab_separated(sources) else ",")
        given = [f"delim = {quote_literal(separator)}", f"header = {'true' if options.get('has_header', True) else 'false'}"]
        if overrides:
            given.append("types = {" + ", ".join(f"{quote_literal(c)}: {quote_literal(t)}" for c, t in overrides.items()) + "}")
        if "infer_schema_length" in options:
            given.append(f"sample_size = {options['infer_schema_length']}")
        if "null_values" in options:
            nulls = options["null_values"]
            nulls = [nulls] if isinstance(nulls, str) else nulls
            given.append("nullstr = [" + ", ".join(quote_literal(n) for n in nulls) + "]")
        if "skip_rows" in options:
            given.append(f"skip = {options['skip_rows']}")
        if "quote_char" in options:
            given.append(f"quote = {quote_literal(options['quote_char'])}")
        if "comment_prefix" in options:
            given.append(f"comment = {quote_literal(options['comment_prefix'])}")
        if options.get("decimal_comma"):
            given.append("decimal_separator = ','")
        given.append("hive_partitioning = false")
        return f"read_csv({text}, {', '.join(given)})"
    given = ["format = 'newline_delimited'", "hive_partitioning = false"]
    if "infer_schema_length" in options:
        given.append(f"sample_size = {options['infer_schema_length']}")
    read_json = f"read_json({text}, {', '.join(given)})"
    if not overrides:
        return read_json
    # DuckDB's JSON reader takes a whole schema or none: a column is given
    # its type after the read instead
    from chartbook.backends import quote_identifier

    casts = ", ".join(f"cast({quote_identifier(c)} as {t}) as {quote_identifier(c)}" for c, t in overrides.items())
    return f"(select * replace ({casts}) from {read_json})"


def arrow_dataset(location):
    """An Arrow IPC file, glob or folder as a pyarrow dataset, for DuckDB to scan.

    DuckDB has no reader of Arrow IPC files of its own; it reads a dataset
    lazily, as it would a file, taking only the columns and rows a query
    asks for. A glob's or a folder's Hive keys are columns, as polars reads
    them.

    :raises FileNotFoundError: If there is no file to read.
    """
    import pyarrow.dataset as ds

    from chartbook import hashing

    read = reading_of(location)
    found = files_of(location.path, read, location.files, location.listed)
    if not found:
        raise FileNotFoundError(f"{location.path}: no Arrow IPC file is there yet.")
    path = Path(location.path)
    if is_glob_pattern(str(path)):
        root = hashing.glob_root(path)
    elif path.is_dir():
        root = path
    else:
        return ds.dataset([str(file) for file in found], format="ipc")
    partitioning = ds.HivePartitioning.discover()
    return ds.dataset([str(file) for file in found], format="ipc", partitioning=partitioning, partition_base_dir=str(root))
