"""The formats a dataframe's file can be in, and the one reader of them.

A dataframe that is a file is stored as parquet, CSV (or TSV), JSON lines
(NDJSON, gzipped or not) or Arrow IPC (Feather). Its entry may say which::

    [dataframes.releases]
    path = "./_data/releases/*.jsonl.gz"
    format = "jsonl"                                # else the path's ending says
    read_options = { schema_overrides = { id = "String" } }

With no ``format``, the ending of the path says it (:data:`ENDINGS`), and a
path whose ending names none, a folder among them, is parquet. A glob is
read as its ending says, and a folder as the files in it of its format.
``read_options`` go to the reader of a CSV or JSON lines file, by polars'
names; :data:`READ_OPTIONS` lists the ones taken, each of which DuckDB is
given too, under its own name and so that it means the same, so that
``data.sql()`` reads a file as ``data.load()`` does.

This module is where a file becomes a table. ``data.load()`` in every
``format=`` it offers, ``data.sql()`` and ``data.ref()``, the dataframe's
page, the data glimpses and the data dictionary all read through it, so
each reads a file as the others do. Hashing, snapshots and pins do not come
into it: they keep bytes, whatever the bytes are.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Union

import polars as pl

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

#: How many rows of a CSV file, or objects of a JSON lines one, its types
#: are inferred from, by polars and by DuckDB alike, unless
#: ``infer_schema_length`` says otherwise. It is DuckDB's own; polars' is 100,
#: and the two would read a column whose values change kind late otherwise.
SAMPLE_ROWS = 20480

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
    "skip_lines": ("a whole number, 0 or more", "2"),
    "null_values": ("a string, or a list of strings", '["NA", "-"]'),
    "decimal_comma": ("true or false", "true"),
    "schema_overrides": ("a table of columns and their types", '{ zip = "String" }'),
    "infer_schema_length": ("a whole number of rows, 1 or more", "100000"),
}

#: The ``read_options`` each format takes, by polars' names. DuckDB is given
#: each as well, under its own name and so that it means the same
#: (:func:`sql`), which is why this is a short list and not all of polars':
#: what ``data.load()`` is given, ``data.sql()`` is given too. A parquet or
#: Arrow IPC file keeps its own schema, and takes none.
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
    "skip": "skip_lines",
    "skiprows": "skip_lines",
    "nullstr": "null_values",
    "na_values": "null_values",
    "dtype": "schema_overrides",
    "dtypes": "schema_overrides",
    "types": "schema_overrides",
    "sample_size": "infer_schema_length",
}

#: Options of polars' that are left out because DuckDB reads them otherwise.
_NOT_ALIKE = {
    "comment_prefix": (
        "Polars skips a line that begins with it, and DuckDB cuts every line at it, so the "
        "two would read the file otherwise. skip_lines skips lines at the top."
    ),
    "skip_rows": (
        "Polars counts rows as it parses them, quotes and all, and DuckDB skips lines. "
        "skip_lines skips lines in both."
    ),
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
    return Reading(found, _checked(Reading(found, said_by=said_by), path, read_options, where), said_by)


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
            why = f" {_NOT_ALIKE[name]}" if name in _NOT_ALIKE and read.format == "csv" else ""
            raise ValueError(
                f"{where}: read_options has {name!r}, which is not one ChartBook passes to a reader.{called}{why} "
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
    if name in ("separator", "quote_char"):
        return isinstance(value, str) and len(value) == 1
    if name in ("has_header", "decimal_comma"):
        return isinstance(value, bool)
    if name in ("skip_lines", "infer_schema_length"):
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


def kept(location) -> dict:
    """How a pin is read, from its record's location: what :func:`declared` kept, else what its path's ending says.

    The store holds a folder under a name of its own, with no ending, so a
    folder declared as ``prices.csv`` is read as CSV by the ending of the
    path its record keeps.
    """
    said = declared(location)
    if "format" not in said and isinstance(location, Mapping):
        named = format_of_name(Path(str(location.get("path") or "")).name)
        if named and named != "parquet":
            said["format"] = named
    return said


def reading_of(location, where: Optional[str] = None) -> Reading:
    """How a file location is read (:class:`chartbook.resolve.FileLocation`)."""
    return reading(location.path, getattr(location, "format", None), getattr(location, "read_options", None), where)


# --- What a read opens ----------------------------------------------------


def _visible(parts) -> bool:
    """Whether a file in a folder is one a read takes: not one named as an engine passes over, ``.`` or ``_``."""
    return not any(part.startswith((".", "_")) for part in parts)


#: What a folder holds beside its data that is plainly not a table: a file
#: with one of these endings, or named one of these (``README.txt``, ``schema.json``).
_DOCUMENTS = (".md", ".rst", ".html", ".htm", ".pdf", ".log", ".crc", ".yaml", ".yml", ".toml", ".xml")
_DOCUMENT_NAMES = ("readme", "license", "licence", "notice", "changelog", "manifest", "schema")


def _a_document(name: str) -> bool:
    """Whether a file of a folder is plainly not one of its tables, by its name."""
    last = name.rsplit("/", 1)[-1].lower()
    return last.endswith(_DOCUMENTS) or last.split(".", 1)[0] in _DOCUMENT_NAMES


def _chosen(read: Reading, names: list[str]) -> list[str]:
    """The files of a folder, by their path in it, that a read of its format takes.

    Those its format's endings name. When there are none and the entry
    names the format itself, those with the ending most of its other files
    have, none plainly not a table: a folder of ``.dat`` or ``.json`` files
    is read as CSV or JSON lines when its entry says so, and the
    ``README.txt`` or ``schema.json`` beside them is passed over.
    """
    visible = [name for name in names if _visible(name.split("/"))]
    chosen = [name for name in visible if name.lower().endswith(ENDINGS[read.format])]
    if chosen or read.said_by != "format":
        return chosen
    candidates = [name for name in visible if format_of_name(name) is None and not _a_document(name)]
    endings = [Path(name).suffix.lower() for name in candidates]
    most = max((endings.count(ending) for ending in endings), default=0)
    return [name for name, ending in zip(candidates, endings) if endings.count(ending) == most]


def _sources(path: Path, read: Reading, files=(), listed=()) -> tuple:
    """What the reader opens, and the folder it is in when it is a folder's.

    A file or a glob is opened as it is. A folder pinned from another
    pipeline is read as the files its record lists, *listed* (for parquet,
    the ones :func:`chartbook.resolve._held` found to be tables, *files*); a
    folder here, as the files in it of its format. A folder of parquet that
    holds nothing else is handed to polars whole, as it always was.

    :returns: The path, or the files, as text; and the folder, or None.
    :raises UnreadableTableError: For a folder with no file of its format.
    """
    path = Path(path)
    is_folder = not is_glob_pattern(str(path)) and path.is_dir()
    if read.format == "parquet":
        if files:
            return [str(file) for file in files], path
        if listed:
            raise UnreadableTableError(path, read.format, _nothing(path, listed, read, pinned=True))
        if is_folder:
            from chartbook.utils import directory_tables

            found = directory_tables(path)
            if not found:
                raise UnreadableTableError(path, read.format, _nothing(path, _names(path), read))
            if _whole(path, found):
                return str(path), path
            return [str(file) for file in found], path
        return str(path), None
    if listed:
        from chartbook.store import on_disk, plain_parts

        plain = {relative: plain_parts(relative) for relative in listed}
        chosen = _chosen(read, sorted(relative for relative, parts in plain.items() if parts))
        if not chosen:
            raise UnreadableTableError(path, read.format, _nothing(path, listed, read, pinned=True))
        return [str(on_disk(path, plain[relative])) for relative in chosen], path
    if is_folder:
        names = _names(path)
        chosen = _chosen(read, names)
        if not chosen:
            raise UnreadableTableError(path, read.format, _nothing(path, names, read))
        return [str(path.joinpath(*name.split("/"))) for name in chosen], path
    return str(path), None


def _whole(folder: Path, tables: list) -> bool:
    """Whether polars, handed a folder, opens just its tables: it holds nothing else, and they share an ending."""
    every = [Path(root, name) for root, _, names in os.walk(folder) for name in names]
    return len(every) == len(tables) and len({file.suffix for file in every}) == 1


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


def _files(sources) -> list[str]:
    """The files a glob matches, in order; a list or a file as they are."""
    if isinstance(sources, list):
        return sources
    if is_glob_pattern(sources):
        return sorted(match for match in glob.glob(sources, recursive=True) if os.path.isfile(match))
    return [sources]


def files_of(path: Union[str, Path], read: Reading, files=(), listed=()) -> list[Path]:
    """The files a read of a path opens: the file, the glob's matches, or a folder's files of its format.

    Empty when there are none yet: nothing built, or a folder with no file
    of its format.
    """
    try:
        sources, folder = _sources(Path(path), read, files, listed)
    except UnreadableTableError:
        return []
    if isinstance(sources, str) and folder is not None:
        from chartbook.utils import directory_tables

        return directory_tables(folder)
    return [Path(file) for file in _files(sources) if os.path.isfile(file)]


# --- Reading ----------------------------------------------------------------


#: The column a read of a folder's files names each row's file in, for a moment.
_FILE = "__chartbook_file__"


def _partitions(files: list[str], folder: Path) -> dict:
    """The Hive keys of a folder's files, from the folders below it and none above: ``year`` of ``year=2024/a.parquet``.

    A key is one every file's path has, as polars reads a folder whose
    files are at one depth. Its type is inferred as polars infers it:
    whole numbers (``007`` is 7), then numbers, ``true`` and ``false``,
    dates, times of day with a date, else text; a value is URL-decoded, and
    ``__HIVE_DEFAULT_PARTITION__`` is null.

    :returns: ``{key: (polars type, {file: value})}``, in the order the keys come.
    """
    from urllib.parse import unquote

    raw: dict = {}
    for file in files:
        for part in Path(file).relative_to(folder).parent.parts:
            if "=" in part and not part.startswith("="):
                key, value = part.split("=", 1)
                raw.setdefault(key, {})[file] = None if value == "__HIVE_DEFAULT_PARTITION__" else unquote(value)
    found = {}
    for key, values in raw.items():
        if len(values) < len(files):
            continue
        kind, parse = _hive_type([value for value in values.values() if value is not None])
        found[key] = (kind, {file: None if values[file] is None else parse(values[file]) for file in files})
    return found


def _hive_type(values: list[str]):
    """The polars type of a Hive key's values, and how one is read as it."""
    from datetime import date, datetime

    def every(test) -> bool:
        try:
            return bool(values) and all(test(value) is not None for value in values)
        except ValueError:
            return False

    if every(lambda v: re.fullmatch(r"[+-]?\d+", v)):
        return pl.Int64, int
    if every(float):
        return pl.Float64, float
    if all(value in ("true", "false") for value in values) and values:
        return pl.Boolean, lambda v: v == "true"
    if every(lambda v: re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and date.fromisoformat(v)):
        return pl.Date, date.fromisoformat
    if every(lambda v: re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?", v) and datetime.fromisoformat(v)):
        return pl.Datetime("us"), datetime.fromisoformat
    return pl.String, str


def _hive(scan, files: list[str], folder: Path):
    """A scan of a folder's files with its Hive keys as columns: those below the folder, and none above it.

    Polars, handed files and not their folder, takes a ``key=value`` part
    anywhere in a path for a column, above the folder as well as below it,
    and in place of a file's own column of that name: a folder declared as
    ``./_data/prices/year=2024`` would gain ``year``. So the files are read
    with no keys, and the keys below the folder (:func:`_partitions`) are
    put on by each row's file, as a read of the folder itself has them. A
    file's own column of a key's name is kept as it is.
    """
    keys = _partitions(files, folder)
    if not keys:
        return scan(files, hive_partitioning=False)
    frame = scan(files, hive_partitioning=False, include_file_paths=_FILE)
    own = set(frame.collect_schema().names())
    put = [
        pl.col(_FILE).replace_strict(values, default=None, return_dtype=kind).alias(key)
        for key, (kind, values) in keys.items()
        if key not in own
    ]
    return frame.with_columns(put).drop(_FILE)


def _csv_options(read: Reading, sources) -> dict:
    """The ``read_options`` of a CSV file as polars takes them, with a sample as DuckDB's and a TSV split on tabs."""
    options = dict(read.options)
    if "schema_overrides" in options:
        options["schema_overrides"] = _overrides(read)
    if "separator" not in options and _tab_separated(sources):
        options["separator"] = "\t"
    options.setdefault("infer_schema_length", SAMPLE_ROWS)
    return options


def _overrides(read: Reading) -> dict:
    """``schema_overrides`` as polars' own types."""
    return {column: getattr(pl, _type(name)) for column, name in (read.options.get("schema_overrides") or {}).items()}


def _tab_separated(sources) -> bool:
    """Whether every file a CSV read opens is named as a TSV is."""
    names = [sources] if isinstance(sources, str) else list(sources)
    return bool(names) and all(str(name).lower().endswith(_TAB_ENDINGS) for name in names)


def _scan(read: Reading, sources, folder: Optional[Path]):
    """The polars scan of a format's files, unchecked; a JSON lines file's columns not given their types yet."""
    if read.format == "parquet":
        if isinstance(sources, list) and folder is not None:
            return _hive(pl.scan_parquet, sources, folder)
        # A file, a glob, or a folder handed whole: as parquet always was
        return pl.scan_parquet(sources, hive_partitioning=True)
    if read.format == "ipc":
        # A glob's or a folder's keys, below it, as DuckDB is given them
        # (arrow_dataset); a file's path gives none
        if isinstance(sources, str) and is_glob_pattern(sources):
            from chartbook import hashing

            return _hive(pl.scan_ipc, _files(sources), hashing.glob_root(sources))
        if isinstance(sources, list) and folder is not None:
            return _hive(pl.scan_ipc, sources, folder)
        return pl.scan_ipc(sources, hive_partitioning=False)
    if read.format == "csv":
        frame, (polars_names, names) = _csv(read, sources)
        return frame.rename(dict(zip(polars_names, names))) if polars_names != names else frame
    # Each file's types inferred from its own lines, and the files read as
    # one under all of their columns, as DuckDB's union_by_name reads them:
    # polars infers a glob's from its first file alone, and a field the
    # later files bring would be lost
    length = read.options.get("infer_schema_length", SAMPLE_ROWS)
    files = _files(sources)
    if len(files) == 1:
        return pl.scan_ndjson(files[0], infer_schema_length=length)
    schemas = [pl.scan_ndjson(file, infer_schema_length=length).collect_schema() for file in files]
    merged = pl.concat([pl.DataFrame(schema=schema) for schema in schemas], how="diagonal_relaxed").schema
    return pl.scan_ndjson(files, schema=merged)


def _csv(read: Reading, sources) -> tuple:
    """A CSV file's scan, and its columns' names: as polars gives them, and as both engines are to give them.

    A file with no header has its columns named ``column_1``, ``column_2``
    and so on, which polars names otherwise by version and DuckDB names
    otherwise again; an empty name in a header is named so too, which
    DuckDB will not take. ``schema_overrides`` name the columns so.
    """
    options = _csv_options(read, sources)
    overrides = options.pop("schema_overrides", None) or {}
    polars_names = pl.scan_csv(sources, **{**options, "infer_schema_length": 0}).collect_schema().names()
    if options.get("has_header", True):
        names = [name if name != "" else f"column_{i}" for i, name in enumerate(polars_names, start=1)]
    else:
        names = [f"column_{i}" for i in range(1, len(polars_names) + 1)]
    named = dict(zip(names, polars_names))
    # True or false is read as text and then as one of the words DuckDB
    # takes for one (yes, t, 1...), where polars would take true and false alone
    truths = [named.get(column, column) for column, kind in overrides.items() if kind == pl.Boolean]
    if overrides:
        options["schema_overrides"] = {
            named.get(column, column): pl.String if kind == pl.Boolean else kind for column, kind in overrides.items()
        }
    frame = pl.scan_csv(sources, **options)
    if truths:
        frame = frame.with_columns(
            pl.col(column).str.to_lowercase().replace_strict(_BOOLEANS, return_dtype=pl.Boolean) for column in truths
        )
    return frame, (polars_names, names)


#: What a read raises when the bytes are not what they are taken to be. A
#: panic in polars is a BaseException, which no caller's `except Exception` takes.
READ_ERRORS = (pl.exceptions.PolarsError, OSError, pl.exceptions.PanicException)


def scan(
    path: Union[str, Path],
    format: Optional[str] = None,
    read_options: Optional[Mapping] = None,
    *,
    files=(),
    listed=(),
    where: Optional[str] = None,
    public: bool = False,
):
    """A dataframe's file as a polars LazyFrame, read as its format is.

    Parquet with ``pl.scan_parquet``, CSV with ``pl.scan_csv``, JSON lines
    with ``pl.scan_ndjson`` and Arrow IPC with ``pl.scan_ipc``; a glob or a
    folder as one frame. Hive's ``key=value`` folders are columns for
    parquet and Arrow IPC, those below a folder and not above it; polars
    reads no such columns from CSV or JSON lines, and DuckDB is told not to
    either. The types of a CSV or JSON lines file are inferred from its
    first :data:`SAMPLE_ROWS` rows, as DuckDB infers them, or
    ``infer_schema_length``; each JSON lines file of a glob or a folder from
    its own, so that a field the later ones bring is kept. A CSV file's
    ``schema_overrides`` are the types it is parsed as, in DuckDB too; a
    JSON lines file's are cast to after it is read (:func:`_cast`), and
    DuckDB is handed what is read here (:func:`handed`). A CSV file with no
    header has its columns named ``column_1``, ``column_2``, …

    The schema is read here, so that a file that is not of its format is
    said now, by name: the footer of a parquet or Arrow IPC file, the first
    rows of a CSV or JSON lines one. A gzipped file is decompressed whole,
    in memory, each time it is read, here included.

    :param path: The file, glob or folder.
    :param format: The entry's ``format``, if it has one.
    :param read_options: The entry's ``read_options``, if it has them.
    :param files: For a folder pinned from another pipeline, the parquet
        files its record lists (:class:`chartbook.resolve.FileLocation`).
    :param listed: And every file it lists, by its path in the folder.
    :param where: What a message names first: ``"Dataframe 'rates'"``.
    :param public: Whether a message is for a page, which names the file by
        its name alone: a machine's paths belong on no page.
    :raises FileNotFoundError: If the file is not there, or a glob matches no file.
    :raises UnreadableTableError: If it cannot be read as its format, a
        folder holds no file of it, or ``schema_overrides`` names a column
        the file does not have.
    :raises ValueError: If the format or an option is not one ChartBook reads.
    """
    read = reading(path, format, read_options, where)
    sources, folder = _sources(Path(path), read, files, listed)
    shown = Path(str(path)).name if public else str(path)
    shown = f"{where}: {shown}" if where else shown
    if isinstance(sources, str) and is_glob_pattern(sources) and not _files(sources):
        raise FileNotFoundError(f"{shown} matches no file yet.")
    try:
        frame = _scan(read, sources, folder)
        schema = frame.collect_schema()
    except FileNotFoundError:
        raise
    except READ_ERRORS as error:
        said = _unreadable(shown, path, read, sources, _reason(error, path if public else None))
        raise UnreadableTableError(path, read.format, said) from error
    overrides = read.options.get("schema_overrides") or {}
    missing = [column for column in overrides if column not in schema]
    if missing:
        # Polars passes over such a column, and DuckDB refuses it: refused here, so both do
        raise UnreadableTableError(
            path,
            read.format,
            f"{shown}: read_options.schema_overrides names {', '.join(map(repr, missing))}, which it has no "
            f"column of. Its columns are: {', '.join(schema.names()[:12])}{', ...' if len(schema) > 12 else ''}.",
        )
    if read.format == "jsonl" and overrides:
        frame = _cast(frame, schema, _overrides(read), shown, path)
    return frame


#: The words a cast of text to Boolean takes, whatever their capitals.
_BOOLEANS = {
    "true": True, "false": False, "t": True, "f": False, "yes": True, "no": False,
    "y": True, "n": False, "1": True, "0": False,
}


def _cast(frame, schema, overrides: dict, shown: str, path):
    """A JSON lines file's columns given their types after the read.

    This is the one meaning they have: ``data.sql()`` is handed the frame
    read here (:func:`handed`), as DuckDB's own casts round, trim and parse
    otherwise than polars' do. Text is trimmed; a number in it is read
    whole or refused; a date is ``YYYY-MM-DD``, as both engines write one,
    and not a guess between day and month; a time with a date is ISO 8601,
    an offset made UTC; true or false is one of :data:`_BOOLEANS`. A struct
    or a list is no one type, and is refused.
    """
    given = []
    for column, kind in overrides.items():
        value, was = pl.col(column), schema[column]
        if was.is_nested():
            raise UnreadableTableError(
                path,
                "jsonl",
                f"{shown}: read_options.schema_overrides gives {column!r} a type, and it is a "
                f"{was}, which is read as it is. Select or unnest its fields in polars or SQL.",
            )
        if was == pl.String:
            value = value.str.strip_chars()
            if kind == pl.Date:
                value = value.str.to_date("%Y-%m-%d")
            elif kind == pl.Datetime:
                value = value.str.to_datetime(time_unit="us", time_zone="UTC").dt.replace_time_zone(None)
            elif kind == pl.Time:
                value = value.str.to_time()
            elif kind == pl.Boolean:
                value = value.str.to_lowercase().replace_strict(_BOOLEANS, return_dtype=pl.Boolean)
            else:
                value = value.cast(kind)
        else:
            value = value.cast(kind)
        given.append(value.alias(column))
    return frame.with_columns(given)


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
    Hive keys, from below it, as categories, and the folder as the parts
    :func:`scan` reads of it. Everything else, a glob among them, is read as
    :func:`scan` reads it and collected.
    """
    frame = scan_location(location, where)  # says now if it cannot be read
    read = reading_of(location, where)
    if read.format != "parquet" or is_glob_pattern(str(location.path)):
        return frame.collect().to_pandas()
    sources, folder = _sources(Path(location.path), read, location.files, location.listed)
    if isinstance(sources, list):
        import pyarrow.dataset as ds

        # As pandas reads a folder: hive partitions as categories
        partitioning = ds.HivePartitioning.discover(infer_dictionary=True)
        return ds.dataset(sources, format="parquet", partitioning=partitioning, partition_base_dir=str(folder)).to_table().to_pandas()
    import pandas as pd

    return pd.read_parquet(location.path)


def _reason(error: BaseException, path=None) -> str:
    """The reader's own reason, in one line; with no absolute path in it when *path* is given."""
    text = (str(error).strip().splitlines() or [type(error).__name__])[0].strip()
    if path is not None:
        for absolute in (str(Path(str(path)).parent), str(Path(str(path)).parent.resolve())):
            text = text.replace(absolute + os.sep, "")
        # And the end of a path polars cuts short: "...chartbook/x.parquet"
        text = re.sub(r"\.\.\.\S*/([^/\s]+)", r"\1", text)
    return text[:300] or type(error).__name__


def _unreadable(shown: str, path, read: Reading, sources, reason: str) -> str:
    """What to say of a file that cannot be read as its format."""
    text = f"{shown} could not be read as {NAMES[read.format]}, {_said(read, path)}. The reader said: {reason}."
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


def _identifier(name: str) -> str:
    """A column's name as one quoted identifier, dots and all."""
    return '"' + name.replace('"', '""') + '"'


#: DuckDB's name of each polars type a Hive key can have.
_DUCKDB_KEYS = {"Int64": "BIGINT", "Float64": "DOUBLE", "Boolean": "BOOLEAN", "Date": "DATE", "Datetime": "TIMESTAMP", "String": "VARCHAR"}


def _literal(value, kind) -> str:
    """A Hive key's value as a DuckDB literal of its type."""
    from chartbook.backends import quote_literal

    name = _DUCKDB_KEYS[kind.base_type().__name__]
    if value is None:
        return f"NULL::{name}"
    if name == "BOOLEAN":
        return "true" if value else "false"
    if name == "DATE":
        return f"DATE {quote_literal(value.isoformat())}"
    if name == "TIMESTAMP":
        return f"TIMESTAMP {quote_literal(value.isoformat(sep=' '))}"
    if name == "VARCHAR":
        return quote_literal(value)
    return f"{value!r}::{name}"


def _with_keys(read_parquet: str, tables: list[str], folder: Path) -> str:
    """A read of a folder's files with its Hive keys below it put on by each row's file, as :func:`_hive` puts them on.

    DuckDB, like polars, takes a ``key=value`` part anywhere in a path, and
    gives a key above and below a folder the value above, in every row. Its
    types are its own too (``007`` is text to it). So it reads the files
    with no keys, and is given each file's.
    """
    from chartbook.backends import quote_literal

    keys = _partitions(tables, folder)
    own = set(pl.scan_parquet(tables[0], hive_partitioning=False).collect_schema().names()) if keys else set()
    keys = {key: kind_values for key, kind_values in keys.items() if key not in own}
    if not keys:
        return read_parquet
    rows = ", ".join(
        "(" + ", ".join([quote_literal(Path(file).as_posix())] + [_literal(values[file], kind) for kind, values in keys.values()]) + ")"
        for file in tables
    )
    columns = ", ".join([_FILE] + [_identifier(key) for key in keys])
    return (
        f"(select * exclude ({_FILE}) from {read_parquet[:-1]}, filename = '{_FILE}') "
        f"join (values {rows}) as chartbook_keys({columns}) using ({_FILE}))"
    )


def sql(location) -> str:
    """A file as DuckDB reads it in SQL: ``read_parquet('…')``, ``read_csv('…', …)`` or ``read_json('…', …)``.

    A folder of parquet is its parts, with the Hive keys below it as polars
    reads them. A CSV or JSON lines file is given its ``read_options`` under
    DuckDB's names, and what DuckDB would otherwise guess is said as polars
    reads it: the separator, the header, the columns' names where polars'
    are not DuckDB's, the quote and its escape, an empty field as null and a
    quoted empty one as empty, and the rows its types are inferred from
    (:data:`SAMPLE_ROWS`). It has no Hive columns, as polars reads none, and
    the files of a JSON lines glob or folder are joined by name. What is
    left to inference is DuckDB's: it finds dates in text, where polars
    leaves text.

    :raises ValueError: For a file DuckDB is handed rather than given a
        reader of (:func:`handed`): an Arrow IPC file, which DuckDB has no
        reader of its own for, or a JSON lines file with
        ``schema_overrides``; or a folder with no file of its format.
    """
    from chartbook.backends import quote_literal

    read = reading_of(location)
    path = Path(location.path)
    if read.format == "ipc" or (read.format == "jsonl" and read.options.get("schema_overrides")):
        what = (
            "an Arrow IPC file, which DuckDB reads with no function of its own"
            if read.format == "ipc"
            else "a JSON lines file with schema_overrides, which polars applies and DuckDB is handed"
        )
        raise ValueError(
            f"{path.name} is {what}, so there is no text to stand for it in SQL. data.sql() hands "
            f"DuckDB what data.load() reads."
        )
    if read.format == "parquet":
        # With / on every system: DuckDB reads it so on Windows too, and SQL
        # with a path in it reads the same wherever it is pasted
        text = path.as_posix()
        if is_glob_pattern(text):
            return f"read_parquet({quote_literal(text)}, hive_partitioning = true)"
        sources, folder = _sources(path, read, location.files, location.listed)
        if folder is None:
            return f"read_parquet({quote_literal(text)})"
        # A folder, as its tables: handed the folder, DuckDB takes only its
        # files named .parquet (not Hive's 000000_0)
        tables = sources if isinstance(sources, list) else [str(file) for file in files_of(path, read)]
        listed = ", ".join(quote_literal(Path(file).as_posix()) for file in tables)
        return _with_keys(f"read_parquet([{listed}], hive_partitioning = false)", tables, folder)
    sources, folder = _sources(path, read, location.files, location.listed)
    many = isinstance(sources, list) or is_glob_pattern(sources)
    if isinstance(sources, list):
        text = "[" + ", ".join(quote_literal(Path(source).as_posix()) for source in sources) + "]"
    else:
        text = quote_literal(Path(sources).as_posix())
    options = read.options
    sample = options.get("infer_schema_length", SAMPLE_ROWS)
    if read.format == "jsonl":
        given = ["format = 'newline_delimited'", f"sample_size = {sample}", "hive_partitioning = false"]
        if many:
            given.append("union_by_name = true")
        return f"read_json({text}, {', '.join(given)})"
    # As polars reads it, which says now what it cannot read: a glob whose
    # files have other columns, say, which DuckDB would read as the first's
    scan(path, read.format, read.options, files=location.files, listed=location.listed)
    _, (polars_names, names) = _csv(read, sources)
    quote = options.get("quote_char", '"')
    nulls = options.get("null_values", [])
    nulls = [""] + [n for n in ([nulls] if isinstance(nulls, str) else nulls) if n != ""]
    given = [
        f"delim = {quote_literal(options.get('separator', chr(9) if _tab_separated(sources) else ','))}",
        f"header = {'true' if options.get('has_header', True) else 'false'}",
        f"quote = {quote_literal(quote)}",
        f"escape = {quote_literal(quote)}",
        "nullstr = [" + ", ".join(quote_literal(n) for n in nulls) + "]",
        "allow_quoted_nulls = false",
        f"sample_size = {sample}",
    ]
    if names != polars_names or not options.get("has_header", True) or any("_duplicated_" in name for name in names):
        # The names as polars gives them, which DuckDB gives otherwise
        given.append("names = [" + ", ".join(quote_literal(name) for name in names) + "]")
    overrides = {column: TYPES[_type(name)] for column, name in (options.get("schema_overrides") or {}).items()}
    if overrides:
        given.append("types = {" + ", ".join(f"{quote_literal(c)}: {quote_literal(t)}" for c, t in overrides.items()) + "}")
    if "skip_lines" in options:
        given.append(f"skip = {options['skip_lines']}")
    if options.get("decimal_comma"):
        given.append("decimal_separator = ','")
    given.append("hive_partitioning = false")
    return f"read_csv({text}, {', '.join(given)})"


def handed(location):
    """What DuckDB is handed of a file it is given no reader of, or None: what ``data.sql()`` registers in its place.

    An Arrow IPC file, which DuckDB has no reader of its own for, is a
    pyarrow dataset (:func:`arrow_dataset`). A JSON lines file with
    ``schema_overrides`` is the frame polars reads of it: DuckDB's casts
    round, trim and parse text otherwise than polars', and its reader finds
    dates in text that an override to String would then give back
    rewritten, so it is handed the values ``data.load()`` gives.
    """
    read = reading_of(location)
    if read.format == "ipc":
        return arrow_dataset(location)
    if read.format == "jsonl" and read.options.get("schema_overrides"):
        return scan_location(location)
    return None


def handed_name(location) -> str:
    """The name what DuckDB is handed of a file goes by in SQL.

    One per file and its reading, the same each call, so that a source's
    engine keeps one view of it and not one a call.
    """
    import hashlib
    import json

    read = reading_of(location)
    files = [str(file) for file in files_of(location.path, read, location.files, location.listed)]
    said = json.dumps([read.format, read.options, sorted(files)], sort_keys=True, default=str)
    return f"chartbook_{read.format}_" + hashlib.sha256(said.encode("utf-8")).hexdigest()[:16]


def arrow_dataset(location):
    """An Arrow IPC file, glob or folder as a pyarrow dataset, for DuckDB to scan.

    DuckDB has no reader of Arrow IPC files of its own; it reads a dataset
    lazily, as it would a file, taking only the columns and rows a query
    asks for. A glob's or a folder's Hive keys below it are columns, of the
    types polars gives them (:func:`_partitions`); a file's path gives none.
    Text is plain ``string``, a dictionary's too: polars writes
    ``string_view``, and the filter DuckDB hands a dataset in a join has no
    kernel for it.

    :raises FileNotFoundError: If there is no file to read.
    """
    import pyarrow as pa
    import pyarrow.dataset as ds

    from chartbook import hashing

    read = reading_of(location)
    found = [str(file) for file in files_of(location.path, read, location.files, location.listed)]
    if not found:
        raise FileNotFoundError(f"{location.path}: no Arrow IPC file is there yet.")
    path = Path(location.path)
    root = hashing.glob_root(path) if is_glob_pattern(str(path)) else path if path.is_dir() else None
    given = {}
    if root is not None:
        own = set(ds.dataset(found[:1], format="ipc").schema.names)
        keys = [(key, kind) for key, (kind, _) in _partitions(found, Path(root)).items() if key not in own]
        if keys:
            arrow = {"Int64": pa.int64(), "Float64": pa.float64(), "Boolean": pa.bool_(), "Date": pa.date32(), "Datetime": pa.timestamp("us"), "String": pa.string()}
            fields = pa.schema([(key, arrow[kind.base_type().__name__]) for key, kind in keys])
            given = {"partitioning": ds.partitioning(fields, flavor="hive"), "partition_base_dir": str(root)}
    schema = ds.dataset(found, format="ipc", **given).schema
    plain = pa.schema([column.with_type(_plain(column.type)) for column in schema], metadata=schema.metadata)
    return ds.dataset(found, format="ipc", schema=plain, **given)


def _plain(kind):
    """An Arrow type with its views and large kinds as their plain ones, all the way down, a dictionary's values too."""
    import pyarrow as pa

    types = pa.types
    if types.is_string_view(kind) or types.is_large_string(kind):
        return pa.string()
    if types.is_binary_view(kind) or types.is_large_binary(kind):
        return pa.binary()
    if types.is_dictionary(kind):
        return pa.dictionary(kind.index_type, _plain(kind.value_type), kind.ordered)
    if types.is_struct(kind):
        return pa.struct([child.with_type(_plain(child.type)) for child in kind])
    if types.is_fixed_size_list(kind):
        return pa.list_(kind.value_field.with_type(_plain(kind.value_type)), kind.list_size)
    if types.is_list(kind) or types.is_large_list(kind) or _is_list_view(kind):
        return pa.list_(kind.value_field.with_type(_plain(kind.value_type)))
    if types.is_map(kind):
        return pa.map_(_plain(kind.key_type), _plain(kind.item_type))
    return kind


def _is_list_view(kind) -> bool:
    """Whether a type is a list view, in a pyarrow that has them."""
    import pyarrow as pa

    return any(getattr(pa.types, check, lambda _: False)(kind) for check in ("is_list_view", "is_large_list_view"))
