"""The index: one JSON description of everything a build contains.

``chartbook docs`` produces a website and, beside it, ``index.json``: the
resolved, composed view of the manifests, as a flat list of self-describing
records. Every pipeline and every asset is in it once, with a fully
qualified ID, a content hash, and what it was made from. A renderer, a
search box, an exporter or a diff of two builds can read that one file and
need nothing else.

The format is specified in ``docs_src/design/index-schema.md``. This module
writes ``Catalog``, ``Pipeline``, ``Dataframe``, ``Series``, ``Chart``,
``Notebook``, ``Note`` and ``Model`` records, and each pipeline's declared
``dependencies``, with what ``chartbook.lock`` pins of them. ``Build``
records come with the part of the asset graph that produces them.

Two forms of the same index are written:

- the **full** index, in the build directory, in which each ``location``
  also has the absolute ``resolved_path`` on this machine;
- the **published** index, beside the HTML, with every machine-specific
  path removed (:func:`published`), since it goes wherever the site goes.

::

    from chartbook import index
    from chartbook.manifest import load_manifest

    idx = index.build_index(load_manifest("."))
    index.write_index(index.published(idx), "docs/index.json")

The index schema is singular by design: there is one writer, this one.
"""

from __future__ import annotations

import copy
import json
import os
import warnings
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union

from chartbook import hashing
from chartbook.__about__ import __version__
from chartbook.identity import ID_COMPONENT_PATTERN, strip_url_credentials
from chartbook.manifest import (
    get_pipeline_dirs,
    get_pipeline_ids,
    get_pipeline_manifest,
)
from chartbook.refs import KIND_TABLES, AssetRef, parse_asset_ref
from chartbook.resolve import known_as, locate_pipeline

#: The version of the file's envelope.
SCHEMA = "chartbook/index/v1"

#: The version every record written by this module carries.
RECORD_VERSION = "chartbook/v1"

#: The file's name, in the build directory and beside the HTML.
INDEX_FILE = "index.json"

#: Where the JSON Schemas for the envelope and for each record kind live.
SCHEMAS_DIR = Path(__file__).parent / "schemas" / "chartbook"

#: The kinds of asset this module writes records for, in the order a
#: pipeline's assets are listed.
ASSET_KINDS = ("dataframe", "chart", "notebook", "note", "model")

# Manifest keys that the index states in another form, or not at all
#: Manifest keys that become a record's structure (its location, its
#: write-up, its inputs) rather than declared metadata carried as it is.
#: A dataframe's ``series`` become Series records and are skipped where
#: that happens; a chart's ``series`` is metadata (the series it shows).
_STRUCTURAL_KEYS = frozenset(
    {"path", "docs", "docs_path", "dataframe", "linked_charts", "source", "table", "query"}
)


def record_kind(kind: str) -> str:
    """The record kind for an asset kind: ``chart`` is recorded as ``Chart``."""
    return kind.capitalize()


def schema_path(name: str) -> Path:
    """The JSON Schema file for a record kind, or for the envelope.

    :param name: A record kind (``"Dataframe"``), or ``"index"`` for the
        file's envelope.
    """
    if name == "index":
        return SCHEMAS_DIR / "index" / "v1.json"
    return SCHEMAS_DIR / "v1" / f"{name}.json"


def dtype_name(dtype: Any) -> str:
    """Name a column's type the way the index writes it.

    The name is the Polars type, lower-cased, with its parameters in square
    brackets: ``float64``, ``int32``, ``string``, ``boolean``, ``date``,
    ``datetime[ns]``, ``datetime[us, UTC]``, ``duration[ms]``,
    ``decimal[10,2]``, ``list[int64]``, ``categorical``, ``struct``. Polars
    is what ``data.load()`` returns, so this is the type a reader gets.
    """
    import polars as pl

    base = dtype.base_type().__name__.lower()
    if isinstance(dtype, pl.Datetime):
        zone = f", {dtype.time_zone}" if dtype.time_zone else ""
        return f"{base}[{dtype.time_unit}{zone}]"
    if isinstance(dtype, pl.Duration):
        return f"{base}[{dtype.time_unit}]"
    if isinstance(dtype, pl.Decimal):
        return f"{base}[{dtype.precision},{dtype.scale}]"
    if isinstance(dtype, (pl.List, pl.Array)):
        return f"{base}[{dtype_name(dtype.inner)}]"
    return base


def _jsonable(value: Any) -> Any:
    """Turn a manifest value into something JSON can hold.

    TOML has dates and JSON does not; they become ISO strings.
    """
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _declared_fields(entry: dict, skip: Iterable[str] = ()) -> dict:
    """The metadata an entry declares, as it is: absent stays absent.

    Keys are sorted, so that reordering a ``chartbook.toml`` does not
    reorder the index.
    """
    skip = _STRUCTURAL_KEYS | set(skip)
    return {
        key: _jsonable(entry[key])
        for key in sorted(entry)
        if not key.startswith("_") and key not in skip
    }


def _docs(entry: dict, base_dir: Optional[Path] = None, cache: Optional[hashing.HashCache] = None) -> Optional[dict]:
    """An entry's write-up: the file it is in, or the text itself if inline.

    With *base_dir*, the write-up's content hash too, so that a build says
    which text it showed and a diff says the write-up changed. Write-ups
    are not pinned; the commit holds them, and the hash names the version.
    """
    if entry.get("docs_path"):
        docs = {"path": entry["docs_path"]}
        if base_dir is not None:
            try:
                docs["content_hash"] = hashing.hash_file(Path(base_dir) / entry["docs_path"], cache).content_hash
            except OSError:
                pass  # a write-up that is not there: `chartbook check` reports it
        return docs
    if entry.get("docs"):
        import hashlib

        return {
            "text": entry["docs"],
            "content_hash": hashing.format_hash(hashlib.sha256(entry["docs"].encode("utf-8")).hexdigest()),
        }
    return None


def _modified_at(resolved: str) -> Optional[str]:
    """When a file, or the newest file a glob names, was last written, in UTC."""
    import glob as globbing

    from chartbook.utils import is_glob_pattern

    if is_glob_pattern(resolved):
        paths = globbing.glob(resolved, recursive=True)
    elif os.path.isdir(resolved):
        # A directory's own time moves only when an entry is added or
        # removed; the newest file inside says when it was last written.
        # The files that count are the ones its hash counts; a directory
        # with none has not been written
        paths = [str(path) for path in hashing.directory_files(resolved)]
    else:
        paths = [resolved]
    stamps = []
    for path in paths:
        try:
            stamps.append(os.stat(path).st_mtime)
        except OSError:
            continue
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_range(resolved: str, date_col: str) -> Optional[dict]:
    """The first and last value of a dataframe's date column, in ISO 8601.

    A date or datetime column is read as it is. A text column is parsed as
    dates first, since its least and greatest text need not be its first
    and last date; what does not parse is left out, and a column with no
    date in it gives nothing. One column is read, lazily, so a large file
    costs one column and not the whole. None when the column is not there,
    holds no dates, or cannot be read.
    """
    import polars as pl

    try:
        frame = pl.scan_parquet(resolved, hive_partitioning=True)
        schema = frame.collect_schema()
        if date_col not in schema.names():
            return None
        column = pl.col(date_col)
        if schema[date_col] == pl.String:
            column = column.str.to_datetime(strict=False)
        elif not schema[date_col].is_temporal():
            return None
        first, last = (
            frame.select(column.min().alias("first"), column.max().alias("last")).collect().row(0)
        )
    except Exception:  # noqa: BLE001 - polars raises many types for "not readable"
        return None
    return _span_as_text(first, last)


def _span_as_text(first, last) -> Optional[dict]:
    """A first and last date or datetime as ISO 8601 text; None for anything else."""
    import datetime as dt

    if not isinstance(first, (dt.date, dt.datetime)) or not isinstance(last, (dt.date, dt.datetime)):
        return None
    return {"first": first.isoformat(), "last": last.isoformat()}


def _file_facts(
    base_dir: Path,
    declared_path: Any,
    cache: Optional[hashing.HashCache],
    list_files: bool = False,
) -> dict:
    """Where a declared file is, and its hash and size if it is there.

    :param list_files: If True and the path is a directory, also list the
        files in it, each with its own size and hash.
    """
    if not isinstance(declared_path, str) or not declared_path.strip():
        return {}
    resolved = os.path.normpath(base_dir / declared_path)
    facts: dict = {
        "location": {
            "kind": "file",
            "path": declared_path,
            "resolved_path": resolved,
        }
    }
    try:
        content = hashing.hash_path(resolved, cache)
    except OSError as error:
        warnings.warn(f"Could not hash {resolved}: {error}", stacklevel=2)
        content = None
    if content is not None:
        facts["content_hash"] = content.content_hash
        facts["size_bytes"] = content.size_bytes
        modified = _modified_at(resolved)
        if modified:
            facts["location"]["modified_at"] = modified
        if list_files and os.path.isdir(resolved):
            facts["files"] = [
                {
                    "path": file.path,
                    "size_bytes": file.size_bytes,
                    "content_hash": file.content_hash,
                }
                for file in content.files
            ]
    return facts


def _source_facts(entry: dict) -> dict:
    """The location of a dataframe that is a table or a query in a source."""
    source = entry.get("_source") or {}
    location = {
        "kind": "table" if entry.get("table") else "query",
        "source": entry.get("source"),
        "backend": source.get("backend"),
        # The manifest's public url, never the machine's: a reader opens
        # the engine through chartbook.backends.source_url() from it
        "url": source.get("url"),
    }
    if entry.get("table"):
        location["identifier"] = entry["table"]
    else:
        location["sql"] = entry["query"]
    # A DuckDB file is a file: when it was last written is a fact about it
    resolved_url = source.get("_resolved_url") or ""
    if resolved_url.startswith("duckdb://"):
        from chartbook.backends import duckdb_path

        try:
            path = duckdb_path(resolved_url, ".")
        except ValueError:
            path = ":memory:"
        if path != ":memory:":
            modified = _modified_at(path)
            if modified:
                location["modified_at"] = modified
    return {"location": location}


def _describe_in_source(entry: dict, where: str) -> Optional[tuple[list[dict], int]]:
    """A table or query's columns and row count, asked of its engine.

    None, with a warning, when the engine cannot answer: the DuckDB file is
    not built yet (which ``chartbook check`` also reports), the table is
    not there, or the query does not bind.
    """
    from chartbook.backends import BackendError, DuckDBBackend
    from chartbook.resolve import QueryLocation, TableLocation

    source = entry.get("_source") or {}
    url = source.get("_resolved_url")
    if not url:
        return None
    if entry.get("table"):
        location = TableLocation(entry["source"], source["backend"], url, entry["table"])
    else:
        location = QueryLocation(entry["source"], source["backend"], url, entry["query"])
    try:
        return DuckDBBackend(url).describe(location)
    except (BackendError, OSError) as error:
        warnings.warn(
            f"{where}: the engine could not describe it, so the index has no "
            f"columns for it. {error}",
            stacklevel=2,
        )
        return None


def _describe_span_in_source(entry: dict, date_col: str) -> Optional[dict]:
    """The first and last date of a table or query, asked of its engine."""
    from chartbook.backends import BackendError, DuckDBBackend
    from chartbook.resolve import QueryLocation, TableLocation

    source = entry.get("_source") or {}
    url = source.get("_resolved_url")
    if not url:
        return None
    if entry.get("table"):
        location = TableLocation(entry["source"], source["backend"], url, entry["table"])
    else:
        location = QueryLocation(entry["source"], source["backend"], url, entry["query"])
    try:
        first, last = DuckDBBackend(url).span(location, date_col)
    except (BackendError, OSError, ValueError):
        return None
    return _span_as_text(first, last)


def _definition_hash(location: dict, columns: list[dict], url: Optional[str]) -> str:
    """A hash of what defines a table or query dataframe, with its schema.

    A warehouse table cannot be content-hashed cheaply, and a query is not
    bytes at all. What can be hashed is the definition, where it is (the
    source, its backend and the manifest's url for it) and the described
    columns; what cannot is recorded as absent.
    """
    import hashlib

    definition = location.get("identifier") or location.get("sql") or ""
    text = json.dumps(
        {
            "kind": location["kind"],
            "source": location.get("source"),
            "backend": location.get("backend"),
            "url": url,
            "definition": definition,
            "columns": columns,
        },
        sort_keys=True,
    )
    return hashing.format_hash(hashlib.sha256(text.encode("utf-8")).hexdigest())


def _describe_parquet(resolved_path: str) -> Optional[tuple[list[dict], int]]:
    """A dataframe's columns and row count, read the way ``data.load()`` reads it.

    Only the parquet footers are read. Returns None when there is nothing
    readable there, which includes "not built yet".
    """
    import polars as pl

    try:
        frame = pl.scan_parquet(resolved_path, hive_partitioning=True)
        schema = frame.collect_schema()
        rows = frame.select(pl.len()).collect().item()
    except Exception:  # noqa: BLE001 - polars raises many types for "not readable"
        return None
    columns = [
        {"name": name, "dtype": dtype_name(dtype)} for name, dtype in schema.items()
    ]
    return columns, int(rows)


def _head(kind: str, ref: AssetRef, pipeline_id: str, entry: dict) -> dict:
    """The fields every asset record starts with, in their fixed order."""
    record = {
        "kind": record_kind(kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": pipeline_id,
    }
    for key in ("name", "description"):
        if key in entry:
            record[key] = _jsonable(entry[key])
    return record


def _finish(
    record: dict,
    entry: dict,
    skip: Iterable[str] = (),
    base_dir: Optional[Path] = None,
    cache: Optional[hashing.HashCache] = None,
) -> dict:
    """Add an entry's remaining declared metadata, then its write-up, last."""
    for key, value in _declared_fields(entry, skip=skip).items():
        record.setdefault(key, value)
    docs = _docs(entry, base_dir, cache)
    if docs is not None:
        record["docs"] = docs
    return record


def _series_records(
    dataframe_ref: AssetRef,
    entry: dict,
    columns: Optional[list[dict]],
    where: str,
) -> list[dict]:
    """One record per series of a dataframe: every column but the date.

    A column documented by a ``[dataframes.x.series.y]`` table is addressed
    by that table's key and marked ``declared``. Any other column is
    addressed by its own name, if its name can be part of an address.
    """
    declared = entry.get("series") or {}
    key_of_column = {table.get("column", key): key for key, table in declared.items()}
    records = []

    def record(key: str, column: str, table: Optional[dict]) -> dict:
        ref = AssetRef(**{**dataframe_ref.to_dict(), "part": key})
        made = {
            "kind": "Series",
            "version": RECORD_VERSION,
            "id": str(ref),
            "ref": ref.to_dict(),
            "dataframe": str(dataframe_ref),
            "column": column,
            "declared": table is not None,
        }
        if table is not None:
            for field in ("name", "description"):
                if field in table:
                    made[field] = _jsonable(table[field])
            _finish(made, table, skip=("column",))
        return made

    seen = set()
    for column in [c["name"] for c in columns or []]:
        if column == entry.get("date_col"):
            continue
        if column in key_of_column:
            key = key_of_column[column]
            seen.add(key)
            records.append(record(key, column, declared[key]))
        elif ID_COMPONENT_PATTERN.match(column) and column not in declared:
            records.append(record(column, column, None))
        # Otherwise the column's name cannot be part of an address. It is
        # still listed in the dataframe's `columns`; a series table that
        # names it with `column = "..."` gives it one.

    for key in sorted(set(declared) - seen):
        table = declared[key]
        column = table.get("column", key)
        if columns is not None:
            warnings.warn(
                f"{where}: series {key!r} names the column {column!r}, which "
                f"the dataframe does not have.",
                stacklevel=3,
            )
        records.append(record(key, column, table))
    return records


def _input_id(
    reference: AssetRef,
    pipeline_id: str,
    dependencies: Mapping[str, dict],
    known_pipelines: Mapping[str, Path],
) -> str:
    """The ID of an asset that another one was made from.

    A local reference belongs to the pipeline that states it. One that
    names another pipeline is written by the ID that pipeline has in this
    build, if it is in it (a catalog knows ``rates`` as ``ftsfr/rates``);
    otherwise by the name ``[dependencies]`` declares it under; and as
    stated if nothing knows it.
    """
    if reference.is_local:
        return str(reference.in_pipeline(pipeline_id))
    try:
        location = locate_pipeline(
            reference.pipeline_id, dependencies=dependencies, catalog=known_pipelines
        )
    except (KeyError, ValueError):
        return str(reference)
    return str(reference.in_pipeline(known_as(location, known_pipelines)))


def _read_lock(base_dir: Path):
    """A pipeline's lockfile, or None if it has none or it cannot be read.

    The index says what is pinned when it can. A lockfile that cannot be
    read is a matter for ``chartbook pin``, not a reason to fail a build.
    """
    from chartbook import lock

    try:
        return lock.read_lock(base_dir)
    except lock.LockError as error:
        warnings.warn(f"{error} What is pinned is left out of the index.", stacklevel=2)
        return None


def _dependency_records(
    dependencies: Mapping[str, dict],
    known_pipelines: Mapping[str, Path],
    locked=None,
) -> list[dict]:
    """A pipeline's declared dependencies, as its record lists them.

    Each is named by the ID it has in this build when it is one of the
    build's pipelines, and by its key in ``[dependencies]`` otherwise. One
    that the lockfile pins has its ``pinned_hash`` and the commit it is
    pinned at, and a directory pinned from a snapshot has the snapshot's
    time.

    :param locked: The pipeline's lockfile, if it has one.
    """
    in_lock = {
        entry["id"]: entry
        for entry in (locked.dependencies if locked is not None else [])
    }
    pinned = {key: entry.get("pinned_hash") for key, entry in in_lock.items()}
    records = []
    for key, entry in dependencies.items():
        location = locate_pipeline(key, dependencies={key: entry})
        if location.kind == "store" and in_lock.get(key, {}).get("location", {}).get("kind") == "git":
            # Named by its ID, and pinned from its repository: as the lockfile says
            from_repository = in_lock[key]["location"]
            where = {"kind": "git", "pipeline": location.pipeline}
            for name in ("rev", "commit"):
                if from_repository.get(name):
                    where[name] = from_repository[name]
            via = "rev"
        elif location.kind == "store":
            where = {"kind": "store", "pipeline": location.pipeline}
            if entry.get("commit"):
                where["at"] = entry["commit"]
            if entry.get("rev"):
                where["rev"] = entry["rev"]
            commit = in_lock.get(key, {}).get("location", {}).get("commit")
            if commit:
                # The commit of the snapshot the lockfile pins it at
                where["commit"] = commit
            via = "store"
        elif location.kind == "git":
            # The index is published; a token in the manifest's URL is not
            where = {"kind": "git", "url": strip_url_credentials(location.url)}
            if location.rev:
                where["rev"] = location.rev
            commit = in_lock.get(key, {}).get("location", {}).get("commit")
            if commit:
                # The commit the lockfile pins it at, whatever `rev` is now
                where["commit"] = commit
            via = "rev"
        else:
            where = {
                "kind": "path",
                "path": entry["path"],
                "value": location.path.as_posix(),
            }
            commit = in_lock.get(key, {}).get("location", {}).get("commit")
            if commit:
                # The commit of the snapshot the lockfile pins it at
                where["commit"] = commit
            via = "path"
        record = {
            "id": known_as(location, known_pipelines),
            "via": via,
            "location": where,
        }
        if record["id"] != key:
            # The name the pipeline knows it by, which its lockfile and
            # snapshots use, when it is not its ID in this build
            record["key"] = key
        if in_lock.get(key, {}).get("snapshot"):
            record["snapshot"] = in_lock[key]["snapshot"]
        if pinned.get(key):
            record["pinned_hash"] = pinned[key]
        records.append(record)
    return sorted(records, key=lambda record: record["id"])


def _pinned_inputs(
    references: Iterable[AssetRef],
    dependencies: Mapping[str, dict],
    known_pipelines: Mapping[str, Path],
    locked,
) -> dict:
    """The content hash the lockfile pins each cross-pipeline input at.

    Keyed by the input's ID as ``inputs`` writes it. An input of this
    pipeline's own, and one that is not pinned, is not in it.

    This says what is pinned, which is what code that asks for the input
    is given. It is not a record of what one particular training run read;
    that comes with build records.
    """
    if locked is None:
        return {}
    pinned = {}
    for reference in references:
        if reference.is_local:
            continue
        try:
            location = locate_pipeline(reference.pipeline_id, dependencies=dependencies)
        except (KeyError, ValueError):
            continue
        record = locked.assets.get(str(reference.in_pipeline(location.id)))
        if record and record.get("content_hash"):
            written_as = reference.in_pipeline(known_as(location, known_pipelines))
            pinned[str(written_as)] = record["content_hash"]
    return pinned


def _asset_records(
    kind: str,
    name: str,
    entry: dict,
    pipeline_id: str,
    base_dir: Path,
    cache: Optional[hashing.HashCache],
    dependencies: Mapping[str, dict],
    known_pipelines: Mapping[str, Path],
    locked=None,
) -> list[dict]:
    """The record for one asset, followed by its series if it is a dataframe."""
    ref = AssetRef(kind=kind, name=name).in_pipeline(pipeline_id)
    record = _head(kind, ref, pipeline_id, entry)
    facts = _file_facts(
        base_dir, entry.get("path"), cache, list_files=(kind == "model")
    )
    record.update(facts)
    series: list[dict] = []
    skip: tuple = ()

    if kind == "dataframe":
        skip = ("series",)  # they become Series records below
        described = None
        if entry.get("table") or entry.get("query"):
            # In a source: no file, so no content hash. The definition is
            # hashed instead, and the engine describes the columns.
            record.update(_source_facts(entry))
            described = _describe_in_source(entry, f"{base_dir / 'chartbook.toml'}: [dataframes.{name}]")
            if described is not None:
                record["definition_hash"] = _definition_hash(
                    record["location"], described[0], (entry.get("_source") or {}).get("url")
                )
        elif "content_hash" in facts:
            described = _describe_parquet(facts["location"]["resolved_path"])
        columns = None
        where = f"{base_dir / 'chartbook.toml'}: [dataframes.{name}]"
        if described is not None:
            columns, record["row_count"] = described
            record["columns"] = columns
            date_col = entry.get("date_col")
            if date_col and date_col not in {c["name"] for c in columns}:
                warnings.warn(
                    f"{where}: date_col is {date_col!r}, which the dataframe "
                    f"does not have. Its columns are: "
                    f"{', '.join(c['name'] for c in columns[:12])}"
                    f"{', ...' if len(columns) > 12 else ''}.",
                    stacklevel=2,
                )
        series = _series_records(ref, entry, columns, where)
        date_col = entry.get("date_col")
        if date_col and "content_hash" in facts and columns and date_col in {c["name"] for c in columns}:
            span = _date_range(facts["location"]["resolved_path"], date_col)
            if span:
                record["date_range"] = span
        elif date_col and record.get("location", {}).get("kind") in ("table", "query") and columns:
            span = _describe_span_in_source(entry, date_col)
            if span:
                record["date_range"] = span
    elif kind == "chart" and entry.get("dataframe"):
        source = parse_asset_ref(entry["dataframe"], kind="dataframe")
        if source.is_local:
            source = source.in_pipeline(pipeline_id)
        record["inputs"] = [str(source)]
    elif kind == "note" and entry.get("path") and "docs" not in entry:
        # A note is its own write-up
        entry = {**entry, "docs_path": entry["path"]}
    elif kind == "model":
        # trained_on is this record's inputs; metrics_path stays as declared
        # (where the scores come from), and metrics holds what it said
        skip = ("trained_on",)
        if "trained_on" in entry:
            record["inputs"] = [
                _input_id(reference, pipeline_id, dependencies, known_pipelines)
                for reference in entry.get("_trained_on", [])
            ]
            pinned = _pinned_inputs(
                entry.get("_trained_on", []), dependencies, known_pipelines, locked
            )
            if pinned:
                record["pinned_inputs"] = pinned
        metrics = _model_metrics(base_dir, name, entry)
        if metrics is not None:
            record["metrics"] = metrics
        versions = _model_versions(base_dir, name, entry)
        if versions:
            record["versions"] = versions
        stale = _model_staleness(base_dir, name, entry)
        if stale is not None:
            # Then, now, and the comparison: keyed alike, so a reader of the
            # record needs nothing else to say which input moved from what
            record["trained_with"] = stale.trained_with
            record["inputs_now"] = stale.now
            record["stale_inputs"] = stale.stale

    return [_finish(record, entry, skip=skip, base_dir=base_dir, cache=cache), *series]


def _model_staleness(base_dir: Path, name: str, entry: dict):
    """Whether the model file was trained on what its inputs are now; None if nothing can be said."""
    from chartbook.models import staleness

    return staleness(base_dir, name, entry)


def _model_versions(base_dir: Path, name: str, entry: dict) -> list[dict]:
    """A model's versions, oldest first: what the snapshots on this machine kept."""
    from chartbook.models import versions_in

    aliases = entry.get("aliases") if isinstance(entry.get("aliases"), dict) else {}
    return [version.to_dict() for version in versions_in(base_dir, name, aliases)]


def _model_metrics(base_dir: Path, name: str, entry: dict) -> Optional[dict]:
    """A model's scores, read from its metrics file if that is there and well formed."""
    from chartbook.models import read_metrics

    declared = entry.get("metrics_path")
    if not declared:
        return None
    metrics_file = base_dir / declared
    if not metrics_file.is_file():
        return None
    try:
        return read_metrics(metrics_file)
    except (OSError, ValueError) as error:
        warnings.warn(
            f"{base_dir / 'chartbook.toml'}: [models.{name}]: its metrics are "
            f"left out of the index: {error}",
            stacklevel=3,
        )
        return None


def pipeline_records(
    pipeline_id: str,
    pipeline_manifest: dict,
    cache: Optional[hashing.HashCache] = None,
    known_pipelines: Optional[Mapping[str, Path]] = None,
) -> list[dict]:
    """The records for one pipeline: itself, then its assets.

    Assets come in the order dataframes, charts, notebooks, notes, models,
    each by name, and each dataframe is followed by its series.

    :param pipeline_id: The pipeline's ID in this build (a catalog's key).
    :param pipeline_manifest: Its loaded manifest.
    :param cache: A hash cache, so unchanged files are not read again.
    :param known_pipelines: Every pipeline in this build, each ID and its
        directory (:func:`chartbook.manifest.get_pipeline_dirs`), so that
        another one of them is written by the ID it has here.
    """
    base_dir = Path(pipeline_manifest["pipeline_base_dir"])
    known_pipelines = dict(known_pipelines or {})
    dependencies = pipeline_manifest.get("dependencies") or {}
    locked = _read_lock(base_dir) if dependencies else None
    project = pipeline_manifest["project"]

    assets: list[dict] = []
    for kind in ASSET_KINDS:
        table = KIND_TABLES[kind]
        entries = pipeline_manifest.get(table) or {}
        for name in sorted(entries):
            try:
                assets += _asset_records(
                    kind,
                    name,
                    entries[name],
                    pipeline_id,
                    base_dir,
                    cache,
                    dependencies,
                    known_pipelines,
                    locked,
                )
            except ValueError as error:
                # A key that cannot be written as an address has no ID
                warnings.warn(
                    f"{base_dir / 'chartbook.toml'}: [{table}.{name}] is left "
                    f"out of the index: {error}",
                    stacklevel=2,
                )

    record: dict = {
        "kind": "Pipeline",
        "version": RECORD_VERSION,
        "id": pipeline_id,
        "name": project["name"],
    }
    for key in ("description", "maintainer", "contributors", "repo_url", "site_url", "copyright", "logo", "favicon"):
        if project.get(key):
            record[key] = _jsonable(project[key])
    compatibility = project.get("os_compatibility")
    if compatibility:
        record["os_compatibility"] = (
            [compatibility] if isinstance(compatibility, str) else list(compatibility)
        )
    record["location"] = {"kind": "path", "value": base_dir.as_posix()}
    scripts = pipeline_manifest.get("scripts") or {}
    if not scripts and project.get("build"):
        scripts = {"build": project["build"]}
    if scripts:
        record["scripts"] = {name: scripts[name] for name in sorted(scripts)}
    if "dependencies" in pipeline_manifest:
        # Absent when the manifest has no [dependencies]; empty when it has
        # the table and nothing in it
        record["dependencies"] = _dependency_records(
            dependencies, known_pipelines, locked
        )
    record["assets"] = [a["id"] for a in assets if a["kind"] != "Series"]
    record["docs"] = _docs({"docs_path": project.get("readme") or "./README.md"}, base_dir, cache)
    site = _site_pages(project, base_dir)
    if site is not None:
        record["site_dir"], record["site_pages"] = site
    changed = code_changed_at(pipeline_manifest)
    if changed:
        record["code_changed_at"] = changed
    from chartbook.identity import read_version_file

    laid_out = read_version_file(base_dir)
    if isinstance(laid_out.get("commit"), str) and isinstance(laid_out.get("made_at"), str):
        # A version laid out from the store: which snapshot this folder is
        record["from_snapshot"] = {"commit": laid_out["commit"], "made_at": laid_out["made_at"]}
    return [record, *assets]


def _add_snapshots(records: list[dict]) -> None:
    """Give each Pipeline record the snapshots of it that are in the store, newest first.

    Read from the store of the machine that builds the index, as a model's
    versions are; a catalog renders each as its own site
    (:mod:`chartbook.versions`). A store that cannot be read is said, and
    the records have no ``snapshots``.
    """
    pipelines = [record for record in records if record.get("kind") == "Pipeline"]
    if not pipelines:
        return
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError, default_store
    from chartbook.versions import version_name

    try:
        found, unreadable = snapshots.readable_snapshots(default_store())
    except (StoreError, ValueError, OSError) as error:
        warnings.warn(f"The snapshots in the store are not in the index: {error}", stacklevel=3)
        return
    if unreadable:
        warnings.warn(
            f"{len(unreadable)} snapshot record(s) in the store cannot be read and are not shown, "
            f"{unreadable[0][0].name} first: {unreadable[0][1]}",
            stacklevel=3,
        )
    by_pipeline: dict[str, list] = {}
    for taken in found:
        by_pipeline.setdefault(taken.pipeline, []).append(taken)
    for record in pipelines:
        listed = []
        for taken in sorted(by_pipeline.get(record["id"], []), key=lambda t: t.made_at, reverse=True):
            entry = {"commit": taken.commit, "made_at": taken.made_at, "name": version_name(taken.commit, taken.made_at)}
            if taken.built_by_run:
                entry["built_by_run"] = True
            if taken.tags:
                entry["tags"] = list(taken.tags)
            listed.append(entry)
        if listed:
            record["snapshots"] = listed
    _add_trained_from(records, by_pipeline)


def _describe_from_the_store(records: list[dict]) -> None:
    """Give a pipeline shown from the store alone what its newest snapshot's own index says of it.

    Its name, description and maintainer as plain text, and its repository
    and site when they are web addresses, as its owner wrote them at the
    newest snapshot (the one its page links to); nothing of its folder,
    which is not here. Anyone who can write to the store can write these,
    so they are only ever text: the writers show them as written and never
    read them as markup.
    """
    from chartbook import snapshot as snapshots
    from chartbook.identity import plain_line, web_link
    from chartbook.store import default_store

    from_store = [
        r for r in records
        if r.get("kind") == "Pipeline" and (r.get("location") or {}).get("kind") == "store" and r.get("snapshots")
    ]
    if not from_store:
        return
    store = default_store()
    found, _ = snapshots.readable_snapshots(store)
    for record in from_store:
        newest = record["snapshots"][0]
        taken = next(
            (t for t in found if t.pipeline == record["id"] and t.commit == newest["commit"] and t.made_at == newest["made_at"]),
            None,
        )
        own = snapshots.stored_pipeline_record(taken, store) if taken is not None else {}
        for key, longest in (("name", 200), ("description", 2000), ("maintainer", 200)):
            text = plain_line(own.get(key), longest)
            if text:
                record[key] = text
        for key in ("repo_url", "site_url"):
            if web_link(own.get(key)):
                record[key] = web_link(own[key])


def _add_trained_from(records: list[dict], by_pipeline: dict) -> None:
    """Give each Model record trained on another pipeline's data the snapshot that held it.

    ``trained_with`` says the hash of each input when the model was trained,
    keyed by the name the model's pipeline knows the other one by. What it
    was trained on is the snapshot of that pipeline the model's own
    pipeline was pinned to then, as recorded by the first snapshot of the
    model's pipeline that held the model's bytes; failing that, the newest
    snapshot holding those bytes made no later than that one. ``trained_from``
    is keyed as ``inputs`` are, by the input's ID in this build.
    """
    by_id = {record["id"]: record for record in records}
    for record in records:
        if record.get("kind") != "Model" or not record.get("trained_with"):
            continue
        pipeline_id = record.get("pipeline")
        pipeline = by_id.get(pipeline_id) or {}
        by_key = {
            dependency.get("key") or dependency.get("id"): dependency
            for dependency in pipeline.get("dependencies") or []
            if dependency.get("id")
        }
        local_model = record["id"].rpartition(":")[2]
        held = min(
            (
                t for t in by_pipeline.get(pipeline_id, [])
                if record.get("content_hash") and (t.assets.get(local_model) or {}).get("content_hash") == record["content_hash"]
            ),
            key=lambda t: t.made_at,
            default=None,
        )
        pins_then = {
            entry.get("id"): ((entry.get("location") or {}).get("commit"), entry.get("snapshot"))
            for entry in (held.inputs if held is not None else [])
            if isinstance(entry, dict)
        }
        found = {}
        for input_key, content_hash in sorted(record["trained_with"].items()):
            key, _, local = input_key.rpartition(":")
            dependency = by_key.get(key)
            if dependency is None:
                continue
            owner = dependency["id"]
            holding = [
                taken for taken in by_pipeline.get(owner, [])
                if (taken.assets.get(local) or {}).get("content_hash") == content_hash
            ]
            chosen = next((t for t in holding if (t.commit, t.made_at) == pins_then.get(key)), None)
            if chosen is None:
                earlier = [t for t in holding if held is not None and t.made_at <= held.made_at]
                chosen = max(earlier, key=lambda t: t.made_at, default=None)
            if chosen is not None:
                found[f"{owner}:{local}"] = {"commit": chosen.commit, "made_at": chosen.made_at}
        if found:
            record["trained_from"] = found


def _site_pages(project: dict, base_dir: Path) -> Optional[tuple[dict, list[str]]]:
    """The pages a pipeline supplies for its own site, and the folder they are in.

    The folder is ``[project] site_dir``, or ``docs_src/site/`` when that
    exists; None when the pipeline supplies none. The pages are every
    Markdown file under it, by path relative to the folder, sorted. The
    build copies them beside the generated pages; a writer lists them in
    the front page's table of contents and reads ``index_toc.md`` if it is
    one of them.
    """
    resolved = project.get("_resolved_site_dir")
    if not resolved:
        return None
    folder = Path(resolved)
    pages = sorted(page.relative_to(folder).as_posix() for page in folder.rglob("*.md") if page.is_file())
    where = {
        "path": Path(os.path.relpath(folder, base_dir)).as_posix(),
        "resolved_path": folder.as_posix(),
    }
    return where, pages


def code_changed_at(pipeline_manifest: dict) -> Optional[str]:
    """When the pipeline's code last changed, as a docs build worked it out, in UTC.

    Present only when :func:`chartbook.manifest.apply_code_change_times` has
    run on the manifest, which a docs build does once per pipeline and
    remembers across incremental builds: the last commit that touched the
    source where it is committed and unmodified, else the newest
    modification time. An index built from a manifest as loaded says
    nothing here, rather than passing off a file's modification time as
    the code's history. The index asks git for nothing itself.
    """
    moment = pipeline_manifest.get("_code_changed_at")
    return moment if isinstance(moment, str) else None


def apply_code_times(index: dict, manifest: dict) -> dict:
    """Set each ``Pipeline`` record's ``code_changed_at`` from the manifest's code times.

    For a build that works the times out after the index is made, as an
    incremental build does once it knows which pipelines it reuses.
    """
    from chartbook.manifest import get_pipeline_manifest

    for record in index.get("records", []):
        if record.get("kind") != "Pipeline":
            continue
        try:
            pipeline_manifest = get_pipeline_manifest(manifest, record["id"])
        except KeyError:
            continue
        changed = code_changed_at(pipeline_manifest)
        if changed:
            record["code_changed_at"] = changed
    return index


def build_index(
    manifest: dict,
    *,
    cache: Optional[hashing.HashCache] = None,
    skip_pipelines: Iterable[str] = (),
    generated_at: Optional[datetime] = None,
) -> dict:
    """Build the index for a loaded manifest, pipeline or catalog.

    Same manifests and same files give the same index, apart from
    ``generated_at``: records are in a fixed order and so are their keys.
    A catalog's index also lists the snapshots in this machine's store, as a
    model's versions are read from it.

    A declared asset whose file does not exist still has a record; it has
    no ``content_hash``. The index says what the manifest declares, and
    ``chartbook check`` is what complains about missing files.

    :param manifest: The manifest, from :func:`chartbook.manifest.load_manifest`.
    :param cache: A hash cache, so unchanged files are not read again.
    :param skip_pipelines: Pipelines left out of this build altogether.
    :param generated_at: The time to record; defaults to now.
    :returns: The full index, with ``resolved_path`` in each location. Pass
        it through :func:`published` before it leaves this machine.
    """
    cache = cache if cache is not None else hashing.HashCache()
    skipped = set(skip_pipelines)
    pipeline_ids = sorted(p for p in get_pipeline_ids(manifest) if p not in skipped)
    project = manifest["project"]

    records: list[dict] = []
    if project["type"] == "catalog":
        catalog: dict = {
            "kind": "Catalog",
            "version": RECORD_VERSION,
            "id": project["id"],
            "name": project["name"],
        }
        if project.get("description"):
            catalog["description"] = project["description"]
        # Where the catalog is, as for a pipeline: a writer looks there for
        # the catalog's own template overrides. Dropped when published
        catalog["location"] = {"kind": "path", "value": Path(manifest["base_dir"]).resolve().as_posix()}
        catalog["pipelines"] = pipeline_ids
        if manifest.get("policy"):
            catalog["policy"] = _jsonable(manifest["policy"])
        records.append(catalog)

    directories = get_pipeline_dirs(manifest)
    known_pipelines = {
        pipeline_id: directories[pipeline_id] for pipeline_id in pipeline_ids
    }
    for pipeline_id in pipeline_ids:
        records += pipeline_records(
            pipeline_id,
            get_pipeline_manifest(manifest, pipeline_id),
            cache,
            known_pipelines=known_pipelines,
        )
    if project["type"] == "catalog":
        # A pipeline the catalog names with no folder here is shown from the store
        for pipeline_id in manifest.get("store_pipelines") or []:
            records.append(
                {
                    "kind": "Pipeline",
                    "version": RECORD_VERSION,
                    "id": pipeline_id,
                    "name": pipeline_id,
                    "location": {"kind": "store"},
                }
            )
        # A catalog shows every version of its pipelines; a pipeline's own site does not
        _add_snapshots(records)
        _describe_from_the_store(records)

    moment = generated_at or datetime.now(timezone.utc)
    return {
        "schema": SCHEMA,
        "generated_at": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {"name": "chartbook", "version": __version__},
        "root": project["id"],
        "records": records,
    }


def published(index: dict) -> dict:
    """The index as it may leave this machine: no local absolute paths.

    Drops ``resolved_path`` from every asset's ``location``, and the
    ``value`` of a pipeline's ``location`` when it is a local directory,
    which goes for each of its dependencies too. Everything else, hashes
    included, is unchanged.
    """
    public = copy.deepcopy(index)
    for record in public.get("records", []):
        location = record.get("location")
        if not isinstance(location, dict):
            continue
        location.pop("resolved_path", None)
        if record.get("kind") == "Pipeline" and str(record.get("site_url", "")).startswith("file://"):
            record.pop("site_url")  # a local path, not a site
        if record.get("kind") == "Catalog" and location.get("kind") == "path":
            # A catalog is only ever a folder: with the folder gone, the
            # location says nothing, so it goes too
            record.pop("location", None)
        if record.get("kind") == "Pipeline":
            places = [location]
            places += [d.get("location") for d in record.get("dependencies", [])]
            for place in places:
                if isinstance(place, dict) and place.get("kind") == "path":
                    place.pop("value", None)
            if isinstance(record.get("site_dir"), dict):
                record["site_dir"].pop("resolved_path", None)
    return public


def write_index(
    index: dict, path: Union[str, Path], only_if_changed: bool = False
) -> Path:
    """Write an index as JSON.

    :param only_if_changed: If True, and the file already holds this index
        in everything but ``generated_at``, leave the file as it is. A build
        that finds nothing different then touches nothing, and
        ``generated_at`` stays the time the index last changed.
    :returns: The path of the file.
    """
    path = Path(path)
    if only_if_changed and _same_but_for_time(index, path):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    return path


def _same_but_for_time(index: dict, path: Path) -> bool:
    """Whether a file already holds an index, ignoring when it was generated."""
    try:
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(existing, dict):
        return False

    def timeless(value: dict) -> dict:
        return {key: item for key, item in value.items() if key != "generated_at"}

    # Through JSON, so that the comparison is of what would be written
    return timeless(existing) == timeless(json.loads(json.dumps(index, default=str)))
