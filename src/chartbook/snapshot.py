"""Snapshots: what one commit of a pipeline built, kept in the store.

A pipeline is worked on while other pipelines depend on it. So the others
never read its folder. They read a **snapshot**: every asset the pipeline
declares, as it was built at one commit, copied into the store and
labelled with that commit.

A snapshot is made on purpose, by whoever works on the pipeline, when its
build is ready for others::

    $ chartbook snapshot
    ftsfr/fed_yield_curve at 4f2a91c: 3 assets in the store
    Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.

Three rules, decided by the maintainer on 2026-10-13
(``docs_src/design/overview.md``, "The snapshot model"):

- **Everything in the pipeline's folder must be committed first.** The
  label says "this is what that commit built", and with uncommitted
  changes it would not be true.
- **It is not made by every build.** Declaring a build ready is a
  decision, and the store changes slowly and on purpose.
- **Nothing else reads the folder.** :mod:`chartbook.lock` pins from a
  snapshot, and a pipeline's working directory can be in any state.

The same commit can have several snapshots. A pipeline that pulls data
from outside gives other bytes on another day, with no file changed, so a
snapshot has the time it was made, and the newest is the one a pin moves
to. A snapshot that would be the same as the one before it is not made.

Where they are kept::

    ~/.chartbook/store/
      snapshots/
        4f2a91c0…/                       the commit
          _top/                          a pipeline at the repository's top
            20261013T182205.123456Z.json
          examples--yield_curve/         one in a folder of the repository
            20261013T182205.123456Z.json

A record is JSON in the index's format, like a lockfile: an envelope and
one record for each asset, each with its content hash. The bytes are
objects in the store like any other, and a snapshot keeps them from being
cleared (:func:`chartbook.lock.plan_gc`).

**Clearing old ones.** Every snapshot is kept until ``chartbook store gc``
is run, and then one is kept if a lockfile pins it, if it is the newest of
its pipeline, if a label in that pipeline's manifest points at a model
version in it, or if it was made in the last :data:`KEEP_DAYS` days
(:func:`plan_removals`). The rest may be removed, and the command asks
first. Beside each pipeline's records the store notes the folder they were
made from (``origins``), which is how it finds that manifest.

A snapshot is found by commit, and a commit is the same in every clone of
a repository. So one made in a folder is found by a pipeline that depends
on that folder, and by one that depends on the same repository by URL.

Made by ``chartbook snapshot``, a snapshot takes its owner's word that what
is on disk was built by that commit. ``chartbook run --snapshot`` builds
and then makes one in the same command, and the record says so
(``built_with.run``).

**What a snapshot says, and what it does not.** Which data it is: the hash
of every file, which is complete. Which code made it: the commit. And a
short note of the conditions it was made under (``built_with``, and
``inputs``: what the pipeline itself was pinned to), which is there to
explain a difference between two snapshots, not to make a build
repeatable. Nothing of a pipeline's ``.env`` is ever copied: it holds
secrets, and a store is something to share.
"""

from __future__ import annotations

import hashlib
import dataclasses
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from chartbook import hashing
from chartbook.identity import (
    _git_environment,
    derive_pipeline_id,
    get_git_remote_url,
    remote_to_web_url,
    repository_key,
    validate_pipeline_id,
    web_link,
)
from chartbook.index import RECORD_VERSION, SCHEMAS_DIR, record_kind
from chartbook.manifest import VERSION_PATTERN, _read_manifest_file, resolve_project_type
from chartbook.refs import AssetRef
from chartbook.resolve import MANIFEST_NAME, declared_files
from chartbook.store import Store, StoreError, default_store
from chartbook.utils import is_glob_pattern

#: The version of a snapshot record's envelope.
SCHEMA = "chartbook/snapshot/v1"


#: The folder, under a commit's, for a pipeline at the top of its repository.
TOP = "_top"

#: How long a snapshot that nothing pins, that is not the newest of its
#: pipeline and that no label points into is kept, in days. Long enough to
#: come back from a holiday to; short enough that a nightly build does not
#: fill a disk that has no copy-on-write clones.
KEEP_DAYS = 7

#: The kinds of link a snapshot's files are stored with: a copy-on-write
#: clone, or a copy. Never a hard link or a symlink, which are the
#: pipeline's own file and change when it is rewritten.
LINKS = ("reflink", "copy")



class SnapshotError(Exception):
    """Raised when a snapshot cannot be made, or a pipeline has none to find."""


class StoreNotReadyError(SnapshotError):
    """Raised when the store does not have all of a snapshot's objects yet, or not all of their bytes.

    In a store a sync service keeps, the sync may not have finished: trying
    again later may succeed, so what fails for this is not kept as failed.
    """


def schema_path() -> Path:
    """The JSON Schema file for a snapshot record's envelope."""
    return SCHEMAS_DIR / "snapshot" / "v1.json"


@dataclass(frozen=True)
class Code:
    """Where a pipeline's code is in git.

    Attributes:
        top: The top directory of the repository it is in.
        commit: The commit that repository is at, in full.
        subdirectory: The pipeline's folder within the repository, with
            ``/`` between its parts; empty at the top.
    """

    top: Path
    commit: str
    subdirectory: str


@dataclass(frozen=True)
class Snapshot:
    """What one commit of a pipeline built.

    Attributes:
        pipeline: The pipeline's own ID when the snapshot was made.
        commit: The commit it was built from.
        subdirectory: The pipeline's folder in its repository; empty at the top.
        made_at: When it was made, in UTC, to the microsecond:
            ``2026-10-13T18:22:05.123456Z``. With the commit, it is what
            names the snapshot.
        assets: A record for each asset the pipeline declared, by the
            asset's reference within the pipeline (``treasury_rates``,
            ``chart/curve_today``). One with a ``content_hash`` was built.
        path: The record's file, if it has been written.
        built_with: A note of the conditions it was made under: whether the
            build ran in the same command (``run``), how its lineage was
            checked (``lineage``: ``pins`` or ``deep``), and the versions of
            ChartBook and Python and the platform. It explains a
            difference; no hash covers it.
        inputs: What the pipeline itself was pinned to when the snapshot
            was made: the dependencies of its own lockfile, each with its
            commit and its ``pinned_hash``. Empty if it has no lockfile.
        repository: The repository it was made in, as the web address of
            its ``origin`` remote (no credentials); empty when it has none.
            A dependency named by its ID alone keeps to the repository it
            was first pinned from.
        first_commit: The first commit of the repository it was made in,
            from its current commit back by first parents: the same in
            every full clone, with a remote or none, under any URL. Empty
            for a shallow clone, which does not have it. With
            ``repository``, it is how a dependency named by its ID alone
            tells one repository from another.
        tags: The git tags on its commit when it was made: the names of
            that version, as ``git tag`` gave them. A tag made later is not
            in it. For people and pages; ``store gc`` asks git for tags.
        labels: The labels the pipeline's manifest gave its models' versions
            when the snapshot was made, by the model's reference: ``{"model/x":
            {"champion": "7f3a9c2e41b0"}}``. Labels travel with snapshots so
            that a machine that cannot read the folder they were made from,
            a store a team shares, still knows which versions to keep; and
            so that a pipeline that depends on this one can pin
            ``this:model/x@champion`` without reading its folder.
        index: The pipeline's own index at this commit, in the published
            form, as an object in the store: ``{"content_hash": …,
            "size_bytes": …}``, the object holding one ``index.json``. It
            is what a docs build of the folder would have written just
            before the snapshot was made, so the data dictionary of this
            version is kept with its data. None for a snapshot made before
            snapshots carried it.
        documents: The files a writer needs that are not assets, as one
            object in the store: the manifest, the lockfile, the README,
            the write-ups, the pipeline's own site pages, its logo and
            favicon, each under its path in the pipeline's folder, and only
            those git tracks. ``{"content_hash": …, "size_bytes": …,
            "files": [...]}``. With the assets, they are enough to lay the
            version out as a folder and build its site
            (:func:`materialize`). None for a snapshot made before.
    """

    pipeline: str
    commit: str
    subdirectory: str
    made_at: str
    assets: dict[str, dict] = field(default_factory=dict)
    path: Optional[Path] = None
    built_with: dict = field(default_factory=dict, compare=False)
    inputs: list = field(default_factory=list, compare=False)
    labels: dict = field(default_factory=dict, compare=False)
    tags: list = field(default_factory=list, compare=False)
    repository: str = field(default="", compare=False)
    first_commit: str = field(default="", compare=False)
    index: Optional[dict] = field(default=None, compare=False)
    documents: Optional[dict] = field(default=None, compare=False)

    @property
    def built_by_run(self) -> bool:
        """Whether ChartBook ran the build in the command that made this."""
        return bool(self.built_with.get("run"))

    def asset_hashes(self) -> set[str]:
        """The content hash of every asset it holds: what a lockfile pinning it names."""
        return {
            record["content_hash"]
            for record in self.assets.values()
            if record.get("content_hash")
        }

    def hashes(self) -> set[str]:
        """Every object it names, its assets, its index and its documents: what the store must keep."""
        named = self.asset_hashes()
        for kept in (self.index, self.documents):
            if kept and kept.get("content_hash"):
                named.add(kept["content_hash"])
        return named

    def content(self) -> dict[str, Optional[str]]:
        """Each asset's content hash, by its reference; None if not built."""
        return {name: record.get("content_hash") for name, record in self.assets.items()}

    def same_moment(self, commit: Optional[str], made_at: Optional[str]) -> bool:
        """Whether this is the snapshot a lockfile names."""
        return self.commit == commit and self.made_at == made_at

    def to_document(self) -> dict:
        """The snapshot as it is written: an envelope and a list of records."""
        code = {"commit": self.commit}
        if self.subdirectory:
            code["subdirectory"] = self.subdirectory
        document = {
            "schema": SCHEMA,
            "root": self.pipeline,
            "code": code,
            "made_at": self.made_at,
        }
        if self.built_with:
            document["built_with"] = self.built_with
        if self.inputs:
            document["inputs"] = self.inputs
        if self.tags:
            document["tags"] = list(self.tags)
        if self.repository:
            document["repository"] = self.repository
        if self.first_commit:
            document["first_commit"] = self.first_commit
        if self.labels:
            document["labels"] = {
                name: dict(sorted(self.labels[name].items())) for name in sorted(self.labels)
            }
        if self.index:
            document["index"] = self.index
        if self.documents:
            document["documents"] = self.documents
        document["records"] = [self.assets[name] for name in sorted(self.assets)]
        return document


@dataclass
class SnapshotReport:
    """What making a snapshot did.

    Attributes:
        snapshot: The snapshot: the one just made, or the one already there
            when nothing had changed.
        made: Whether a new one was written.
        not_built: The assets the pipeline declares and has not built, each
            with its declared path.
        new_versions: The models whose bytes no earlier snapshot of this
            pipeline had, each with the name of the version this makes
            (:func:`version_name`). A snapshot is what makes a version.
        skipped_labels: Labels of the manifest the snapshot did not record,
            by model: a name a reference cannot carry, or one that reads as
            a version, or one whose value is not a version. ``chartbook
            check`` refuses the same ones.
        index_skipped: Why the version's index could not be built and is
            not in the snapshot, in one line; None when it is (or when no
            new snapshot was made).
        documents_skipped: The documents the manifest names that were not
            kept, each with why: not a plain path inside the folder, a
            link, not a file.
    """

    snapshot: Snapshot
    made: bool
    not_built: list[tuple[str, str]] = field(default_factory=list)
    new_versions: list[tuple[str, str]] = field(default_factory=list)
    skipped_labels: list[tuple[str, str]] = field(default_factory=list)
    index_skipped: Optional[str] = None
    documents_skipped: list[tuple[str, str]] = field(default_factory=list)


def asset_record(
    ref: AssetRef, pipeline: str, declared_path: str, content, single: bool
) -> dict:
    """An asset as a snapshot and a lockfile record it; with its hash if stored.

    This is the one place that shape is written.

    :param ref: The asset's reference, qualified with the pipeline's name.
    :param pipeline: That name.
    :param declared_path: The asset's ``path`` as its manifest gives it.
    :param content: What was stored: its hash, its size and its files; or
        None for an asset that is declared and not built.
    :param single: Whether the asset's ``path`` named one file. A directory
        has its files listed, as the index lists a directory model's:
        ``files`` is what tells a directory from a file.
    """
    record = {
        "kind": record_kind(ref.kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": pipeline,
        "location": {"kind": "file", "path": declared_path},
    }
    if content is not None:
        record["content_hash"] = content.content_hash
        record["size_bytes"] = content.size_bytes
        if not single and not is_glob_pattern(declared_path):
            record["files"] = [
                {
                    "path": file.path,
                    "size_bytes": file.size_bytes,
                    "content_hash": file.content_hash,
                }
                for file in content.entries
            ]
    return record


def source_record(ref: AssetRef, pipeline: str, entry: dict, source: Optional[dict], content) -> dict:
    """A dataframe that is a table or a query in a source, as a snapshot records it.

    Its ``location`` is the source's, as the index writes it: the kind, the
    source's name and backend, the manifest's public url, and the table's
    name or the query's text. With *content*, the hash of the parquet file
    the table was written out to, which is what a pin copies.
    """
    location: dict = {
        "kind": "table" if entry.get("table") else "query",
        "source": entry.get("source"),
        "backend": (source or {}).get("backend"),
    }
    if source is not None:
        location["url"] = source.get("url")
    if entry.get("table"):
        location["identifier"] = entry["table"]
    else:
        location["sql"] = entry["query"]
    record = {
        "kind": record_kind(ref.kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": pipeline,
        "location": location,
    }
    if content is not None:
        record["content_hash"] = content.content_hash
        record["size_bytes"] = content.size_bytes
    return record


def _has_order_by(connection, sql: str) -> Optional[bool]:
    """Whether a query's outermost statement has its own ORDER BY.

    Asked of the engine's parser. None for a query the parser refuses: it
    is then run as the author wrote it, so that the engine's error names
    the author's text and not a wrapper around it.
    """
    import json

    try:
        (serialized,) = connection.execute("select json_serialize_sql(?)", [sql]).fetchone()
        statements = json.loads(serialized).get("statements") or []
    except Exception:  # noqa: BLE001 - not SQL the engine can parse; the scan says so
        return None
    if not statements:
        return None
    modifiers = (statements[0].get("node") or {}).get("modifiers") or []
    return any(modifier.get("type") == "ORDER_MODIFIER" for modifier in modifiers)


def materialized_name(record: dict) -> str:
    """The file a table or query is written out as, inside its store object: ``<name>.parquet``."""
    return f"{record['ref']['name']}.parquet"


def files_read(record: dict) -> Optional[dict]:
    """The files a reader opens of an asset's object, by their path in it, each with its size, as the record gives them.

    One file for an asset that is a file (under the name of its declared
    path, or ``<name>.parquet`` for a table or query written out), each
    file for a directory. None for a glob, whose record lists no files, or
    a record with no sizes: the object's files are then summed
    (:meth:`chartbook.store.Store.incomplete`).
    """
    size = record.get("size_bytes")
    location = record.get("location") or {}
    try:
        if location.get("kind") in ("table", "query"):
            return {materialized_name(record): size} if isinstance(size, int) else None
    except (KeyError, TypeError):
        return None
    listed = record.get("files")
    if isinstance(listed, list):
        found = {
            entry["path"]: entry["size_bytes"]
            for entry in listed
            if isinstance(entry, dict) and isinstance(entry.get("path"), str) and isinstance(entry.get("size_bytes"), int)
        }
        return found or None
    declared = location.get("path")
    if not isinstance(declared, str) or not isinstance(size, int) or is_glob_pattern(declared):
        return None
    return {Path(declared).name: size}


def not_whole(store: Store, record: dict) -> Optional[str]:
    """Why the store's object of a record with a hash is not whole as the record has it; None if it is, or that cannot be told.

    By the names and sizes of the files a reader opens (:func:`files_read`),
    and, for a directory, that it holds no file its record does not list.
    Nothing is read (:meth:`chartbook.store.Store.incomplete`).
    """
    if not record.get("content_hash"):
        return None
    files = files_read(record)
    every = files is not None and isinstance(record.get("files"), list)
    return store.incomplete(record["content_hash"], record.get("size_bytes"), files, every)


def materialize_in_source(
    directory: Path, pipeline: str, raw: dict, store: Store
) -> list[tuple[AssetRef, dict, Optional[str]]]:
    """Write each table or query dataframe out as parquet, into the store.

    A table in a DuckDB file is what the pipeline made, as much as a parquet
    file is; a snapshot holds files, so the table is written out as one.
    The record's location stays the source's, and its ``content_hash`` is
    the parquet's. A table in ``:memory:``, one in a warehouse, one the
    engine cannot read, or one with a column Polars cannot import, is recorded without a hash,
    with the reason, as an asset that is not built is. The file is read on
    one thread, and a query that has no ORDER BY of its own is written
    sorted on every column, so that the same rows give the same bytes
    whatever order the engine found them in; a query the author ordered
    keeps that order.

    :returns: For each such dataframe, in name order: its local reference,
        its record, and why it was not written out, or None.
    """
    import tempfile

    import duckdb
    import polars as pl

    from chartbook.backends import MEMORY_URL, DuckDBBackend, duckdb_path
    from chartbook.manifest import validate_sources
    from chartbook.resolve import QueryLocation, TableLocation

    entries = raw.get("dataframes") or {}
    in_source = {
        name: entry
        for name, entry in entries.items()
        if isinstance(entry, dict) and (entry.get("table") or entry.get("query"))
    }
    if not in_source:
        return []
    try:
        sources = validate_sources(raw.get("sources"), directory)
    except ValueError as error:
        raise SnapshotError(f"{pipeline}: {error}") from None
    found = []
    for name in sorted(in_source):
        entry = in_source[name]
        try:
            local = AssetRef(kind="dataframe", name=name)
        except ValueError:
            continue  # a key that is not an address has no reference
        ref = local.in_pipeline(pipeline)
        source = sources.get(entry.get("source"))
        what = f"table {entry['table']}" if entry.get("table") else "query"
        where = f"{what} in source {entry.get('source')!r}"
        if source is None:
            found.append((local, source_record(ref, pipeline, entry, None, None), f"{where}: no such source"))
            continue
        if source.get("backend") != "duckdb":
            # A warehouse's table is read where it is, by whoever reads it
            found.append((local, source_record(ref, pipeline, entry, source, None),
                          f"{where}: a {source.get('backend')} source is read where it is, and a snapshot "
                          f"does not pin it yet"))
            continue
        url = source["_resolved_url"]
        if url == MEMORY_URL:
            found.append((local, source_record(ref, pipeline, entry, source, None),
                          f"{where}: only a table in a DuckDB file is written out as parquet"))
            continue
        if not Path(duckdb_path(url, directory)).is_file():
            found.append((local, source_record(ref, pipeline, entry, source, None),
                          f"{where}: the DuckDB file is not there"))
            continue
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / f"{name}.parquet"
            try:
                # The file is read on one thread: a parallel aggregate of
                # floats is not bit-stable from run to run, and a hash that is
                # to say "unchanged" must be
                connection = duckdb.connect(duckdb_path(url, directory), read_only=True)
                connection.sql("set threads = 1")
                backend = DuckDBBackend(url, connection=connection)
                if entry.get("table"):
                    # A scan of a table comes out in insertion order, every time
                    typed = TableLocation(entry["source"], "duckdb", url, entry["table"])
                elif _has_order_by(connection, entry["query"]) in (True, None):
                    # The author chose the order, and it is the pinned copy's
                    # too; or the parser refused the text, and the scan is to
                    # say so about the author's own SQL
                    typed = QueryLocation(entry["source"], "duckdb", url, entry["query"])
                else:
                    # An unordered query's rows come out in whatever order the
                    # engine found them, and the file's hash must not depend on
                    # that: sorted on every column, the same rows give the same bytes
                    typed = QueryLocation(entry["source"], "duckdb", url, f"select * from ({entry['query']}) as q order by all")
                # A table streams; a query the engine must sort is sorted there first
                backend.scan(typed).sink_parquet(out)
            except (Exception, pl.exceptions.PanicException) as error:  # noqa: BLE001
                # The engine's own error, whatever it is; and Polars panics,
                # which are not Exceptions, for a type it cannot import
                # (an INTERVAL column). One such table must not stop the snapshot
                found.append((local, source_record(ref, pipeline, entry, source, None),
                              f"{where}: could not be read: {error}"))
                continue
            finally:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - never opened, or closed already
                    pass
            # A copy, never a link: the file is about to be deleted with its folder
            stored = store.put(out, links=("reflink", "copy"))
        found.append((local, source_record(ref, pipeline, entry, source, stored), None))
    return found


def renamed(record: dict, pipeline: str) -> dict:
    """An asset's record under another name for its pipeline.

    A snapshot names a pipeline as the pipeline names itself. A lockfile
    names it by its key in ``[dependencies]``, which may differ.
    """
    local = AssetRef.from_dict(
        {key: record["ref"][key] for key in ("kind", "name") if key in record["ref"]}
    )
    ref = local.in_pipeline(pipeline)
    return {**record, "id": str(ref), "ref": ref.to_dict(), "pipeline": pipeline}


def local_name(record: dict) -> str:
    """An asset's reference within its pipeline: ``x``, or ``chart/y``."""
    return str(AssetRef(kind=record["ref"]["kind"], name=record["ref"]["name"]))


def _git(directory: Path, *arguments: str, stdin: str = "") -> str:
    """Run git in a directory and return what it printed.

    It takes no lock it does not need, so that looking at a repository
    never gets in the way of whoever is working in it.
    """
    environment = {**_git_environment(), "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env=environment,
            input=stdin,
        )
    except OSError as error:
        raise SnapshotError(f"git could not be run: {error}") from None
    if result.returncode != 0:
        said = result.stderr.strip() or f"git {arguments[0]} failed"
        raise SnapshotError(said)
    return result.stdout


def code_of(directory: Union[str, Path]) -> Code:
    """Say where a pipeline's folder is in git, and at which commit.

    :raises SnapshotError: If there is no such folder, it is not in a git
        repository, or the repository has no commit yet.
    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise SnapshotError(f"there is no folder at {directory}")
    try:
        top = Path(_git(directory, "rev-parse", "--show-toplevel").strip()).resolve()
    except SnapshotError:
        raise SnapshotError(
            f"{directory} is not in a git repository. A snapshot is labelled "
            f"with the commit it was built from, so only a pipeline that is in "
            f"git has any"
        ) from None
    try:
        commit = _git(directory, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
    except SnapshotError:
        raise SnapshotError(f"the repository at {top} has no commit yet") from None
    subdirectory = directory.relative_to(top).as_posix()
    return Code(top, commit, "" if subdirectory == "." else subdirectory)


def uncommitted(directory: Union[str, Path], ignoring: tuple = ()) -> list[str]:
    """What in a pipeline's folder is not committed, as ``git status`` lists it.

    A changed file, a staged one, and a new file that git does not ignore
    all count. What git ignores does not, which is how built data stays
    out of it. Only the pipeline's own folder is looked at, so other work
    in the same repository does not hold a snapshot up.

    :param ignoring: File names that do not count, wherever they are. The
        lockfile that ``chartbook run`` writes before a build is one.
    :returns: One line for each, as ``git status --porcelain`` prints it,
        with paths from the top of the repository.
    """
    # -z: one record per NUL, and paths as they are, not quoted and escaped
    # as they would be for a terminal. A rename or copy has the old path in
    # a record of its own, which follows.
    listing = _git(
        Path(directory).resolve(),
        "status", "--porcelain", "-z", "--untracked-files=all", "--", ".",
    )
    records = listing.split("\0")
    found = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 3:
            continue
        status, path = record[:2], record[3:]
        if status[0] in "RC" and index < len(records):
            path = f"{records[index]} -> {path}"
            index += 1
        if os.path.basename(path.split(" -> ")[-1]) in ignoring:
            continue
        found.append(f"{status} {path}")
    return found


def record_name(subdirectory: str) -> str:
    """The name a pipeline's records are kept under in a store, from its folder in its repository.

    The folder names it, with ``--`` for ``/``. A folder whose own name
    holds ``--``, or is ``_top``, would then be mistaken for another; such
    a one gets a short hash of itself as well, so that two pipelines never
    share a name here.
    """
    clean = subdirectory.strip("/")
    name = clean.replace("/", "--") or TOP
    if clean and ("--" in clean or name == TOP):
        name += "~" + hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8]
    return name


def read(path: Union[str, Path]) -> Snapshot:
    """Read one snapshot record.

    :raises SnapshotError: If the file is not a record this version reads.
    """
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
        if document.get("schema") != SCHEMA:
            raise ValueError(
                f"its schema is {document.get('schema')!r}, and this version of "
                f"ChartBook reads {SCHEMA!r}"
            )
        code = document["code"]
        # A record may come from a store anyone on a team writes; what names
        # folders and pages must be what it claims to be
        if not isinstance(code.get("commit"), str) or not _COMMIT.match(code["commit"]):
            raise ValueError("its commit is not a full commit hash")
        if not isinstance(document.get("made_at"), str) or not _MADE_AT.match(document["made_at"]):
            raise ValueError(f"its made_at, {document.get('made_at')!r}, is not a time as a snapshot writes one")
        validate_pipeline_id(document.get("root"))
        subdirectory = code.get("subdirectory", "")
        if subdirectory and safe_relative(subdirectory) != subdirectory:
            raise ValueError(f"its subdirectory, {subdirectory!r}, is not a plain path")
        assets = {local_name(record): record for record in document["records"]}
        return Snapshot(
            pipeline=document["root"],
            commit=code["commit"],
            subdirectory=code.get("subdirectory", ""),
            made_at=document["made_at"],
            assets=assets,
            path=path,
            built_with=dict(document.get("built_with") or {}),
            inputs=list(document.get("inputs") or []),
            labels={k: dict(v) for k, v in (document.get("labels") or {}).items()},
            tags=_tag_names(document.get("tags")),
            repository=web_link(document.get("repository")),
            first_commit=_first_commit_in(document.get("first_commit")),
            index=dict(document["index"]) if document.get("index") else None,
            documents=dict(document["documents"]) if document.get("documents") else None,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError(f"Cannot read the snapshot {path}: {error}") from None


def _first_commit_in(value: object) -> str:
    """A record's first commit, if it is a full commit hash; else an empty string."""
    return value if isinstance(value, str) and _COMMIT.match(value) else ""


def _first_commit(top: Path) -> str:
    """The first commit of a repository, back from where it is by first parents; empty in a shallow clone."""
    try:
        if _git(top, "rev-parse", "--is-shallow-repository").strip() == "true":
            return ""
        roots = _git(top, "rev-list", "--max-parents=0", "--first-parent", "HEAD").split()
    except SnapshotError:
        return ""
    return _first_commit_in(roots[-1]) if roots else ""


def identity_keys(taken: "Snapshot") -> set:
    """What names the repository a snapshot was made in: its address and its first commit, those it records."""
    keys = set()
    if repository_key(taken.repository):
        keys.add(("address", repository_key(taken.repository)))
    if taken.first_commit:
        keys.add(("first", taken.first_commit))
    return keys


def repository_groups(snapshots: list) -> tuple[list[list], list]:
    """Snapshots of one pipeline ID, grouped by the repository each was made in.

    Two snapshots are of one repository when they name one address or one
    first commit, and so on through the rest: a repository whose remote
    changed keeps its first commit, one whose history was rewritten keeps
    its address, and a clone whose remote is a path on disk keeps its
    first commit. A fork has its original's first commit and is taken as
    one repository with it, as another branch would be.

    :returns: The groups, each in the order given, and the snapshots that
        name neither (made before snapshots recorded their repository).
    """
    parent: dict = {}

    def root(key):
        while parent.setdefault(key, key) != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for taken in snapshots:
        keys = sorted(identity_keys(taken))
        for key in keys[1:]:
            parent[root(key)] = root(keys[0])
        if keys:
            root(keys[0])
    groups: dict = {}
    unnamed = []
    for taken in snapshots:
        keys = sorted(identity_keys(taken))
        if keys:
            groups.setdefault(root(keys[0]), []).append(taken)
        else:
            unnamed.append(taken)
    return list(groups.values()), unnamed


def by_repository(snapshots: list) -> list[list]:
    """Snapshots of one pipeline, a list for each repository; those that name none go with the one repository there is, if one.

    For what keeps and resolves within a repository: ``store gc``'s newest
    and labels, and the versions a label is looked up among. A snapshot
    that names no repository was made before snapshots recorded one, and
    is taken as the named repository's when there is only one.
    """
    groups, unnamed = repository_groups(snapshots)
    if len(groups) == 1:
        merged = set(map(id, groups[0] + unnamed))
        return [[taken for taken in snapshots if id(taken) in merged]]
    return groups + ([unnamed] if unnamed else [])


def find(store: Store, commit: str, subdirectory: str = "") -> list[Snapshot]:
    """The snapshots of one pipeline at one commit, newest first.

    :param store: The store they are kept in.
    :param commit: The commit, in full.
    :param subdirectory: The pipeline's folder in its repository.
    :raises SnapshotError: If one of them cannot be read.
    """
    found = [read(file) for file in store.snapshot_files(commit, record_name(subdirectory))]
    return sorted(found, key=lambda s: (s.made_at, _count(s.path)), reverse=True)


def newest_for(
    directory: Union[str, Path], store: Optional[Store] = None
) -> tuple[Optional[Snapshot], Code]:
    """Find the newest snapshot of the pipeline in a folder.

    That is the newest snapshot at the commit the folder is on or, if that
    commit has none, at the nearest commit before it that has one. So the
    folder's owner can be several commits past the last build they
    declared ready, and a pipeline that depends on the folder still gets
    that build. A snapshot made on another branch is not found.

    Nothing in the folder is read but where it is in git.

    :param directory: The pipeline's folder.
    :param store: The store; this user's by default.
    :returns: The snapshot, or None if there is none, and where the folder
        is in git now.
    :raises SnapshotError: If the folder is not in a git repository.
    """
    store = store if store is not None else default_store()
    code = code_of(directory)
    commits = store.snapshot_commits()
    if not commits:
        return None, code
    # Newest first, and the commit the folder is on comes first of all
    for commit in _git(code.top, "rev-list", "HEAD").split():
        if commit in commits:
            found = [t for t in find(store, commit, code.subdirectory) if not made_in_the_future(t)]
            if found:
                return found[0], code
    return None, code


def history(directory: Union[str, Path], store: Optional[Store] = None) -> list[Snapshot]:
    """Every snapshot of the pipeline in a folder, oldest first.

    At any commit the repository still has, on any branch or on none: a
    snapshot made on a branch that was never merged, or at a commit that
    was then amended away, is still something that was built. Only a
    commit git has pruned is gone, and so are its snapshots to this
    repository.

    :raises SnapshotError: If the folder is not in a git repository.
    """
    store = store if store is not None else default_store()
    code = code_of(directory)
    commits = store.snapshot_commits()
    if not commits:
        return []
    # A store holds snapshots of many repositories; these are this one's.
    # Asked of the object store, not of the branches, so a commit that was
    # amended away still counts while git keeps it.
    answers = _git(
        code.top, "cat-file", "--batch-check=%(objectname) %(objecttype)",
        stdin="".join(f"{commit}\n" for commit in sorted(commits)),
    )
    ours = {
        line.split()[0] for line in answers.splitlines() if line.endswith(" commit")
    }
    found = [taken for commit in ours for taken in find(store, commit, code.subdirectory)]
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path)))


def versions_of(
    directory: Union[str, Path], name: str, store: Optional[Store] = None
) -> list[tuple[str, Snapshot]]:
    """The versions of one asset: each content it has had in a snapshot.

    A version is made by the first snapshot that holds those bytes. Making
    a snapshot again with the same bytes makes no new version.

    :param directory: The pipeline's folder.
    :param name: The asset's reference within the pipeline, ``model/x``.
    :returns: Each content hash with the first snapshot that held it,
        oldest first.
    """
    seen: dict[str, Snapshot] = {}
    for taken in history(directory, store):
        content_hash = (taken.assets.get(name) or {}).get("content_hash")
        if content_hash and content_hash not in seen:
            seen[content_hash] = taken
    return list(seen.items())


#: How many digits of a content hash name a version, unless more are needed.
#: Twelve, as Docker shows an image and the Linux kernel asks for a commit:
#: a label in a committed file should go on naming one version for years.
#: Among 10,000 versions of one model, two share twelve digits about once in
#: five million; with git's seven it would be nearer one in six.
VERSION_DIGITS = 12


def version_name(content_hash: str, among: Optional[list[str]] = None) -> str:
    """The name of a version: the start of its content hash, as git names a commit.

    ``sha256:7f3a9c2e41b0…`` is ``7f3a9c2e41b0``. It is the same on every machine and
    every branch, since it is worked out from the bytes and nothing else.

    :param among: The other versions of the same asset. If two would share
        a name, both get as many more digits as tells them apart.
    """
    digits = content_hash.split(":", 1)[-1]
    others = [h.split(":", 1)[-1] for h in (among or []) if h != content_hash]
    length = VERSION_DIGITS
    while length < len(digits) and any(o.startswith(digits[:length]) for o in others):
        length += 1
    return digits[:length]


#: A full commit hash, as a record must name one.
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
#: When a snapshot was made, as :func:`_now` writes it (a test may leave out the fraction).
_MADE_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$")


def all_snapshots(store: Store) -> list[Snapshot]:
    """Every snapshot in a store, oldest first.

    :raises SnapshotError: If a record cannot be read. Nothing should be
        removed from a store that cannot say what it is keeping.
    """
    found = [read(file) for file in store.all_snapshot_files()]
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path)))


def readable_snapshots(store: Store) -> tuple[list[Snapshot], list[tuple[Path, str]]]:
    """Every snapshot in a store that can be read, oldest first, and each record that cannot, with why.

    For what only shows the store, a catalog's versions: one record a newer
    ChartBook wrote, or one written to mislead, leaves the rest shown.
    What removes anything uses :func:`all_snapshots`, which refuses instead.
    """
    found, unreadable = [], []
    for file in store.all_snapshot_files():
        try:
            found.append(read(file))
        except SnapshotError as error:
            unreadable.append((Path(file), str(error)))
    found.sort(key=lambda taken: (taken.made_at, _count(taken.path)))
    return found, unreadable


def all_hashes(store: Store) -> set[str]:
    """Every object any snapshot in a store names."""
    kept: set[str] = set()
    for taken in all_snapshots(store):
        kept |= taken.hashes()
    return kept


def origins(store: Store, taken: Snapshot) -> list[Path]:
    """The repository folders a pipeline's snapshots were made from."""
    noted = store.origins(taken.commit, record_name(taken.subdirectory))
    # Only an absolute folder is a place to look; anything else noted says nothing
    return [Path(line) for line in noted if os.path.isabs(line)]


def _first_holding(directory: Path, name: str, content_hash: str, store: Store) -> Optional[dict]:
    """The record of an asset in the first snapshot of this pipeline that held these bytes."""
    try:
        for held, taken in versions_of(directory, name, store):
            if held == content_hash:
                return taken.assets.get(name)
    except SnapshotError:
        return None
    return None


def training_inputs(directory: Path, raw: dict, assets: dict) -> dict[str, dict[str, str]]:
    """For each model with ``trained_on``, the content hash of each input now.

    A local dataframe's hash is the one this snapshot records for it; another
    pipeline's is the one the folder's lockfile pins, under the ID the
    lockfile uses (the dependency's key). An input that is not built, not
    pinned, or not a reference that parses is left out; ``chartbook check``
    reports those.

    :returns: By the model's reference, ``{input_id: content_hash}``.
    """
    from chartbook.lock import LOCK_FILE, LockError, read_lock
    from chartbook.manifest import validate_dependencies
    from chartbook.resolve import locate_pipeline, parse_declared_ref

    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    if not models:
        return {}
    try:
        dependencies = validate_dependencies(raw.get("dependencies") or {}, directory)
    except ValueError:
        dependencies = {}
    try:
        locked = read_lock(directory / LOCK_FILE)
    except LockError:
        locked = None
    found: dict[str, dict[str, str]] = {}
    for name, entry in models.items():
        references = entry.get("trained_on") if isinstance(entry, dict) else None
        if not isinstance(references, list):
            continue
        inputs: dict[str, str] = {}
        for text in references:
            try:
                ref = parse_declared_ref(text, kind="dataframe")
            except ValueError:
                continue
            if ref.is_local:
                key = str(ref)
                content_hash = (assets.get(key) or {}).get("content_hash")
            else:
                try:
                    location = locate_pipeline(ref.pipeline_id, dependencies=dependencies)
                except (KeyError, ValueError):
                    continue
                key = str(ref.in_pipeline(location.id))
                content_hash = ((locked.assets.get(key) if locked else None) or {}).get("content_hash")
            if content_hash:
                inputs[key] = content_hash
        if inputs:
            found[f"model/{name}"] = inputs
    return found


def labels_of(raw: dict) -> dict[str, dict[str, str]]:
    """The labels a manifest's ``[models.x.aliases]`` give, and what they name.

    :returns: For each model's reference, each label and the start of the
        hash it names. Only what a label may say counts: twelve or more hex
        digits; anything shorter would keep every snapshot for ever.
    """
    pointed: dict[str, dict[str, str]] = {}
    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    for name, entry in models.items():
        aliases = entry.get("aliases") if isinstance(entry, dict) else None
        if not isinstance(aliases, dict):
            continue
        for label, version in aliases.items():
            # Only a label a reference can carry, and one that does not read
            # as a version; `chartbook check` refuses the rest, and a snapshot
            # must not hand a dependant a name its lockfile cannot hold
            if not LABEL_PATTERN.match(label) or _HEX_START.match(label):
                continue
            if isinstance(version, str) and VERSION_PATTERN.match(version):
                pointed.setdefault(f"model/{name}", {})[label] = version.split(":", 1)[-1]
    return pointed


#: What a label may be called: what a reference carries after ``@``, and
#: not something that reads as the start of a version's hash.
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_HEX_START = re.compile(r"^[0-9a-f]{4,64}$")  # as `validate_aliases` reads "looks like a version"


def labels_skipped(raw: dict) -> list[tuple[str, str]]:
    """The labels of a manifest that :func:`labels_of` leaves out, for the owner to hear of."""
    recorded = labels_of(raw)
    skipped = []
    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    for name, entry in sorted(models.items()):
        aliases = entry.get("aliases") if isinstance(entry, dict) else None
        if not isinstance(aliases, dict):
            continue
        for label in sorted(aliases):
            if label not in recorded.get(f"model/{name}", {}):
                skipped.append((f"model/{name}", label))
    return skipped


def versions_of_pipeline(
    store: Store, pipeline: str, subdirectory: str, name: str, found: Optional[list] = None
) -> list[tuple[str, "Snapshot"]]:
    """The versions of one asset of a pipeline, from the store alone.

    What :func:`versions_of` answers from a folder's repository, this
    answers from the snapshots a store holds of the pipeline, by the name
    the pipeline gives itself. For a pipeline that depends on another: it
    never reads the other's folder.

    :param found: The store's snapshots, read already; read from the
        store when not given.
    :returns: Each content hash with the first snapshot that held it,
        oldest first.
    """
    seen: dict[str, Snapshot] = {}
    for taken in found if found is not None else all_snapshots(store):
        if taken.pipeline != pipeline or taken.subdirectory != subdirectory:
            continue
        content_hash = (taken.assets.get(name) or {}).get("content_hash")
        if content_hash and content_hash not in seen:
            seen[content_hash] = taken
    return list(seen.items())


def label_records(
    newest: "Snapshot", key: str, store: Store, found: Optional[list] = None
) -> tuple[dict[str, dict], list[tuple[str, str, str]]]:
    """The lockfile records for the labels a snapshot carries, resolved to bytes.

    Each label of each model becomes a record of its own, ``key:model/x@champion``,
    with the content hash of the version the label names, so that a
    pipeline that depends on this one gets the labelled version through
    its lockfile and the store, as it gets anything else, and a build
    stays repeatable until ``chartbook update`` moves the label.

    :param newest: The snapshot being pinned from, whose ``labels`` say
        what the owner's manifest said when it was made.
    :param key: The dependency's key in ``[dependencies]``.
    :param found: The store's snapshots, read already (see
        :func:`versions_of_pipeline`).
    :returns: The records, by ID; and the labels that could not be
        resolved, as ``(model, label, start, why)``: no snapshot of the
        pipeline in the store names such a version, two versions share
        the start, or the version is named and its bytes are not there.
    """
    records: dict[str, dict] = {}
    unresolved: list[tuple[str, str, str, str]] = []
    where = f"{newest.pipeline!r}" + (f" at {newest.subdirectory}" if newest.subdirectory else "")
    if newest.labels:
        # The versions of the repository it was made in: another that gives
        # itself the same ID cannot make one of its labels ambiguous. A
        # record that cannot be read is no version of it.
        if found is None:
            found, _ = readable_snapshots(store)
        of_it = [taken for taken in found if taken.pipeline == newest.pipeline and taken.subdirectory == newest.subdirectory]
        named, unnamed = repository_groups(of_it + [newest])
        if identity_keys(newest):
            found = next(group for group in named if any(t is newest for t in group)) + unnamed
        else:
            found = (named[0] if len(named) == 1 else []) + unnamed
    for name, labels in sorted(newest.labels.items()):
        versions = None
        for label, start in sorted(labels.items()):
            if versions is None:
                versions = versions_of_pipeline(store, newest.pipeline, newest.subdirectory, name, found)
            named = [
                (content_hash, taken)
                for content_hash, taken in versions
                if content_hash.split(":", 1)[-1].startswith(start)
            ]
            if not named:
                why = f"no snapshot of {where} in the store names such a version"
            elif len(named) > 1:
                why = f"{len(named)} versions share that start"
            elif not store.has(named[0][0]):
                why = "a snapshot names it, and its bytes are not in the store"
            else:
                why = ""
            if why:
                unresolved.append((name, label, start, why))
                continue
            content_hash, taken = named[0]
            # What the version was trained on is the owner's record, keyed in
            # the owner's names; a dependant's lockfile does not carry it
            record = {k: v for k, v in renamed(taken.assets[name], key).items() if k != "trained_on"}
            ref = AssetRef.from_dict(record["ref"])
            ref = dataclasses.replace(ref, rev=label)
            records[str(ref)] = {**record, "id": str(ref), "ref": ref.to_dict(), "label": label}
    return records, unresolved


def _labels_in(store: Store, group: list[Snapshot], newest: Optional[Snapshot]) -> dict[str, set[str]]:
    """The labels of each model of one pipeline: as its manifest has them
    now, and as its snapshots recorded them.

    The manifest is read from each folder the pipeline's snapshots were
    made from. A folder that is gone, or whose manifest cannot be read,
    says nothing; and that is the case for every snapshot made on another
    machine, in a store a team shares, and for one made in a checkout that
    was thrown away. So the newest snapshot's own record of the labels its
    manifest had when it was made counts too: the newest only, so that a
    label the owner has since taken away releases its version once a
    snapshot follows. A label given after the newest snapshot is known
    only where the folder is.

    :returns: For each model's reference, the starts of the hashes its
        labels point at.
    """
    pointed: dict[str, set[str]] = {}
    seen: set[Path] = set()
    for name, labels in (newest.labels if newest is not None else {}).items():
        pointed.setdefault(name, set()).update(labels.values())
    for taken in group:
        for top in origins(store, taken):
            directory = top / taken.subdirectory if taken.subdirectory else top
            if directory in seen:
                continue
            seen.add(directory)
            try:
                raw = _read_manifest_file(directory)
            except (OSError, ValueError):
                continue
            for name, labels in labels_of(raw).items():
                pointed.setdefault(name, set()).update(labels.values())
    return pointed


def _pinnable(store: Store, group: list[Snapshot], now: Optional[datetime] = None) -> set[Path]:
    """The snapshots of one pipeline that a branch or a tag can pin from.

    ``pin`` takes the newest snapshot at the nearest commit, at or before
    the one a folder is on, that has one. So for each branch and tag of
    each repository the snapshots were made from, the first of its
    commits, walking back, that has a snapshot is pinnable, and the newest
    snapshot there is the one. A repository that is gone says nothing.

    :param now: The time the plan is made at.
    :returns: The records' paths.
    """
    at_commit: dict[str, list[Snapshot]] = {}
    for taken in group:
        # As pin finds the newest: never one dated after now
        if not made_in_the_future(taken, now):
            at_commit.setdefault(taken.commit, []).append(taken)
    keep: set[Path] = set()
    seen: set[Path] = set()
    for taken in group:
        for top in origins(store, taken):
            if top in seen:
                continue
            seen.add(top)
            try:
                tips = _git(top, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/tags")
            except SnapshotError:
                continue
            for tip in set(tips.split()):
                try:
                    walk = _git(top, "rev-list", tip)
                except SnapshotError:
                    continue
                for commit in walk.split():
                    if commit in at_commit:
                        keep.add(at_commit[commit][-1].path)
                        break
    return keep


def _made_at(taken: Snapshot) -> datetime:
    return datetime.fromisoformat(taken.made_at.rstrip("Z")).replace(tzinfo=timezone.utc)


#: How far ahead of this machine's clock a snapshot's time may be and still
#: count as made: two machines' clocks differ a little, and no more
FUTURE_SLACK_SECONDS = 600


def made_in_the_future(taken: Snapshot, now: Optional[datetime] = None) -> bool:
    """Whether a snapshot says it was made later than now: a clock far ahead, or a record written to win.

    Such a snapshot is never taken as the newest, which would let it stay
    the newest, and so be pinned and kept, for as long as its date says.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    try:
        return (_made_at(taken) - now).total_seconds() > FUTURE_SLACK_SECONDS
    except ValueError:
        return True


def _ahead(taken: Snapshot, now: datetime) -> float:
    """How many seconds after *now* a snapshot is dated; endless for a date that is no date."""
    try:
        return (_made_at(taken) - now).total_seconds()
    except ValueError:
        return float("inf")


@dataclass
class SnapshotPlan:
    """Which snapshots a store keeps and which it may let go of.

    Attributes:
        keep: Each snapshot that is kept, with why.
        remove: Each snapshot that may be removed, with why it may.
    """

    keep: list[tuple[Snapshot, str]] = field(default_factory=list)
    remove: list[tuple[Snapshot, str]] = field(default_factory=list)

    def kept_hashes(self) -> set[str]:
        """The objects the kept snapshots name."""
        hashes: set[str] = set()
        for taken, _ in self.keep:
            hashes |= taken.hashes()
        return hashes


def plan_removals(
    store: Store,
    pinned: set[tuple[str, str]],
    hashes_of_missing: set[str] = frozenset(),
    keep_days: float = KEEP_DAYS,
    now: Optional[datetime] = None,
    keep_lineage: bool = False,
    aggressive: bool = False,
    hashes_elsewhere: set[str] = frozenset(),
    hashes_noted: set[str] = frozenset(),
    noted: Optional[dict] = None,
) -> SnapshotPlan:
    """Say which snapshots may be removed. Nothing is removed.

    A snapshot is kept if, in this order:

    1. a lockfile pins it (its commit and time are named by a dependency);
    2. a note of a lockfile pins it: one that cannot be found, one on
       another machine, or one read here whose note, from its last pin,
       names it (*noted*); or, for a note from before notes named their
       snapshots, it is the newest snapshot holding one of the objects the
       note names;
    3. it is the newest snapshot of its pipeline, or the newest that a
       branch or a tag of the repository it came from can pin from;
    4. a label points at a model version it holds: in the pipeline's
       manifest, read from the folder the snapshots were made from, or as
       recorded in the newest snapshot of the pipeline (:func:`labels_of`);
    5. it was made in the last *keep_days* days, or is dated after now by
       less than that, as a snapshot made on a machine whose clock is ahead
       is; one dated further ahead is removed if nothing pins it;
    6. with *keep_lineage*: a snapshot kept for any of these reasons was
       made from it, or from a label pointing into it, and so on up, so
       that a kept snapshot's lineage stays whole (:func:`_keep_lineage`).
       Without it, which is the default, a store keeps what work needs now
       and lets old lineage go; ``chartbook lineage`` then says a snapshot
       upstream is not in the store.

    With *aggressive*, names keep nothing: 3 is only the newest of the
    pipeline, never the newest a branch or tag can pin from, and 4 is not
    asked at all, so a tagged version, or a labelled model version, goes
    once nothing else keeps it.

    Otherwise it may be removed. What it names and nothing else names is
    then removed with it, by :func:`chartbook.lock.plan_gc`.

    :param pinned: The ``(commit, made_at)`` pairs that readable lockfiles
        pin.
    :param hashes_of_missing: The objects named by lockfiles that cannot be
        found and are not to be forgotten.
    :param hashes_elsewhere: The objects named by lockfiles on other
        machines, which are not read here, and by notes from before notes
        named their machine, or copies of notes.
    :param hashes_noted: The objects the notes of lockfiles that were read
        recorded at their last pin, which the lockfile may no longer name
        (after a pull, or a switch of branch): a note only adds.
    :param noted: The snapshots notes record, ``(commit, made_at)``, each
        with why it is kept. The three sets of objects above are for notes
        that record no snapshots.
    :raises SnapshotError: If a record cannot be read.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    plan = SnapshotPlan()
    groups: dict[tuple[str, str], list[Snapshot]] = {}
    for taken in all_snapshots(store):
        groups.setdefault((taken.pipeline, taken.subdirectory), []).append(taken)
    planned = []
    for whole in groups.values():
        # Within one repository: another that gives itself the same ID takes
        # nothing from this one's keep. A snapshot that names no repository,
        # with more than one repository claiming the ID, may be any one's:
        # what any of their labels points at in it is kept.
        named, unnamed = repository_groups(whole)
        parts = by_repository(whole) if len(named) <= 1 else named + ([unnamed] if unnamed else [])
        of_whole = []
        for part in parts:
            # Not one dated after now: it would stay "the newest" while the
            # real newest went unkept
            present = [taken for taken in part if not made_in_the_future(taken, now)]
            newest = present[-1] if present else None
            labels = {} if aggressive else _labels_in(store, part, newest)
            of_whole.append([part, newest, labels, set() if aggressive else _pinnable(store, part, now)])
        if len(named) > 1 and unnamed:
            for _, _, labels, _ in of_whole[:-1]:
                for name, starts in labels.items():
                    of_whole[-1][2].setdefault(name, set()).update(starts)
        planned.extend(of_whole)
    # A note that names no snapshots (from before notes recorded them) keeps,
    # of the snapshots holding each object it names, the newest: an object
    # that never changes would otherwise keep every snapshot there is
    every = sorted((taken for group, _, _, _ in planned for taken in group), key=lambda t: (t.made_at, _count(t.path)))

    def newest_holding(hashes: set) -> set:
        holder: dict = {}
        for taken in every:
            for content_hash in taken.hashes() & hashes:
                holder[content_hash] = taken
        return {id(taken) for taken in holder.values()}

    by_missing = newest_holding(set(hashes_of_missing))
    by_elsewhere = newest_holding(set(hashes_elsewhere))
    by_noted = newest_holding(set(hashes_noted))
    noted = noted or {}
    for group, newest, labels, pinnable in planned:
        for taken in group:
            if (taken.commit, taken.made_at) in pinned:
                why = "a lockfile pins it"
            elif (taken.commit, taken.made_at) in noted:
                why = noted[(taken.commit, taken.made_at)]
            elif id(taken) in by_missing:
                why = "a lockfile that cannot be found named what it holds"
            elif id(taken) in by_elsewhere:
                why = "a lockfile not read here, another machine's, named what it holds"
            elif id(taken) in by_noted:
                why = "a lockfile's note, from its last pin, names what it holds"
            elif taken is newest:
                why = "it is the newest of its pipeline"
            elif taken.path in pinnable:
                why = "it is the newest a branch or tag can pin from"
            elif any(
                (record.get("content_hash") or "").split(":", 1)[-1].startswith(start)
                for name, starts in labels.items()
                for record in [taken.assets.get(name) or {}]
                for start in starts
            ):
                why = "a label points at a version in it"
            elif made_in_the_future(taken, now) and _ahead(taken, now) > keep_days * 86400:
                plan.remove.append(
                    (taken, f"nothing pins it, and it is dated more than {keep_days:g} days after now, so it is not taken as made")
                )
                continue
            elif made_in_the_future(taken, now):
                # A clock behind this one's: kept as a new snapshot is
                why = f"it is dated after now, by less than {keep_days:g} days"
            elif (now - _made_at(taken)).total_seconds() < keep_days * 86400:
                why = f"it was made in the last {keep_days:g} days"
            else:
                plan.remove.append(
                    (taken, f"nothing pins it, it is not the newest, and it is older than {keep_days:g} days")
                )
                continue
            plan.keep.append((taken, why))
    # What keeps a repository's snapshots one, and with --keep-lineage what
    # those were made from, until neither keeps more
    while True:
        kept = len(plan.keep)
        if keep_lineage:
            _keep_lineage(plan, groups)
        _keep_repositories_whole(plan, groups, now)
        if len(plan.keep) == kept:
            return plan


def _keep_repositories_whole(plan: SnapshotPlan, groups: dict, now: datetime) -> None:
    """Keep, of what the plan would remove, what tells which repository the kept snapshots are of.

    Snapshots of an ID are one repository by a shared address or first
    commit (:func:`repository_groups`), and only a snapshot that names both
    says that an address and a first commit go together. So, for each
    repository, of the snapshots that name both (the newest of each address
    and first commit, one dated a little ahead only where no other names
    them):

    - all of them, where removing them would leave the kept snapshots
      looking like two repositories;
    - for each first commit a kept snapshot names with no address (a clone
      whose remote is a path), those that name it with an address, so that
      a dependency that names any of those addresses still takes that
      snapshot;
    - all of them, where a snapshot kept of the one repository there is
      names no repository (made by a ChartBook from before), since its pin
      may know only one of the repository's keys; or, if none names both
      and nothing else of the repository is kept, the newest that names it.

    An address or first commit that no kept snapshot needs keeps nothing.
    """
    kept = {taken.path for taken, _ in plan.keep}
    removable = {taken.path: taken for taken, _ in plan.remove}
    rescued: dict = {}

    def keep(taken, why: str) -> None:
        if taken.path in removable and taken.path not in rescued:
            rescued[taken.path] = (taken, why)

    for whole in groups.values():
        named, unnamed = repository_groups(whole)
        for group in named:
            held = [taken for taken in group if taken.path in kept]
            holders: dict = {}
            for taken in group:
                if taken.repository and taken.first_commit:
                    pair = (repository_key(taken.repository), taken.first_commit)
                    if not made_in_the_future(taken, now) or pair not in holders:
                        holders[pair] = taken
            if len(repository_groups(held)[0]) > 1:
                for taken in holders.values():
                    keep(taken, "it names its repository's address and first commit together, which joins its snapshots")
            # Every address a kept clone's first commit goes with: a
            # dependency may name any one of them (a fork, a moved repository)
            for first in {taken.first_commit for taken in held if not taken.repository and taken.first_commit}:
                for (_, commit), taken in holders.items():
                    if commit == first:
                        keep(taken, "it names the address of a kept snapshot's first commit")
            if len(named) == 1 and any(taken.path in kept for taken in unnamed):
                # A kept snapshot that names no repository may have been
                # pinned when only one of its keys was known: keep them all
                for taken in holders.values():
                    keep(taken, "it is the newest that names its repository")
                if not held and not holders:
                    present = [taken for taken in group if not made_in_the_future(taken, now)] or group
                    keep(present[-1], "it is the newest that names its repository")
    if rescued:
        plan.remove = [(taken, why) for taken, why in plan.remove if taken.path not in rescued]
        plan.keep.extend(rescued.values())


def _keep_lineage(plan: SnapshotPlan, groups: dict) -> None:
    """Keep what a kept snapshot's lineage needs, as far up as it goes.

    A snapshot records the snapshots it was made from (``inputs``), and
    ``chartbook lineage`` walks to them and checks them by hash. So each of
    those is kept too, and what it was made from, and so on. What a kept
    snapshot was made from includes the versions the labels of each of its
    inputs named, since a pin of a snapshot pins its labels: the snapshots
    holding those versions are kept as well. A label on a snapshot no kept
    snapshot was made from keeps nothing beyond the newest snapshot's, as
    before, so taking a label away still releases its version.
    """
    removable = {id(taken): (taken, why) for taken, why in plan.remove}
    by_moment: dict[tuple[str, str], list] = {}
    for group in groups.values():
        for taken in group:
            by_moment.setdefault((taken.commit, taken.made_at), []).append(taken)
    def holding_labelled(upstream) -> list:
        """The snapshots of its pipeline holding the versions a snapshot's labels name."""
        found = []
        labels = upstream.labels if isinstance(upstream.labels, dict) else {}
        for name, named in labels.items():
            for start in (named.values() if isinstance(named, dict) else []):
                start = str(start).split(":", 1)[-1]
                if len(start) < 12:
                    continue
                for other in groups.get((upstream.pipeline, upstream.subdirectory), []):
                    held = (other.assets.get(name) or {}).get("content_hash")
                    if isinstance(held, str) and held.split(":", 1)[-1].startswith(start):
                        found.append(other)
        return found

    queue = [taken for taken, _ in plan.keep]
    while queue and removable:
        taken = queue.pop()
        rescued = []
        for entry in taken.inputs if isinstance(taken.inputs, list) else []:
            location = entry.get("location") if isinstance(entry, dict) else None
            if isinstance(location, dict) and isinstance(location.get("commit"), str) and isinstance(entry.get("snapshot"), str):
                for upstream in by_moment.get((location["commit"], entry["snapshot"]), []):
                    rescued.append((upstream, "a snapshot that is kept was made from it"))
                    # What was pinned from it held its labels' versions too
                    for holder in holding_labelled(upstream):
                        rescued.append((holder, "a snapshot that is kept was made from a label pointing at a version in it"))
        for upstream, why in rescued:
            if id(upstream) in removable:
                del removable[id(upstream)]
                plan.keep.append((upstream, why))
                queue.append(upstream)
    plan.remove = [(taken, why) for taken, why in plan.remove if id(taken) in removable]


def remove(store: Store, taken: Snapshot) -> bool:
    """Remove one snapshot's record. Its objects are the store's to clear.

    :returns: True if the record was there.
    """
    if taken.path is None:
        return False
    return store.remove_snapshot(taken.path)


def _count(path: Path) -> int:
    """Which of the snapshots made at one instant a file is: 1, unless numbered."""
    _, _, number = path.stem.partition("-")
    return int(number) if number.isdigit() else 1


def _now() -> str:
    """The time, in UTC, to the microsecond.

    It is that fine because the time is part of what names a snapshot: a lockfile
    says which one it pinned by its commit and its time, and two made at
    one commit must not look like the same one.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write(snapshot: Snapshot, store: Store) -> Path:
    """Write a snapshot's record, whole or not at all, and return its file."""
    stamp = snapshot.made_at.replace("-", "").replace(":", "")
    return store.write_snapshot(
        snapshot.commit, record_name(snapshot.subdirectory), stamp, snapshot.to_document()
    )


def lineage_gaps(directory: Union[str, Path], store: Optional[Store] = None) -> list[str]:
    """What stands between a pipeline's pins and its full lineage, one line each with what to run; empty if nothing.

    A snapshot records what its pipeline was pinned to (``inputs``: each
    dependency's commit and the hash over its pins), and the assets it holds
    were made from those bytes. So first the check ``chartbook pin --frozen``
    makes (:func:`chartbook.lock.verify`): a lockfile, every dependency in
    it, pinned from where the manifest says, its bytes in the store. Then,
    for a ``path`` dependency something was pinned from: that its pin names
    a snapshot, by its commit and time, that the store has that snapshot
    and it holds each asset pinned from it under its name at its hash, and
    that each label pinned names a version some snapshot of the pipeline
    holds; so that a lockfile changed by hand, or brought from another
    store, is caught. (A ``git`` dependency is pinned from its clone, not a
    snapshot, and its hashes are checked only to be in the store.)

    Nothing that could not have been read is a gap: an asset the other
    pipeline had not built when it was pinned, and a dependency of which
    nothing is pinned (it declares nothing, or has no snapshot yet). Reads
    that do not go through the lockfile (a load through a catalog, a model
    version named by its hash) are not seen here.

    :raises LockError: If the lockfile is there and cannot be read.
    :raises ValueError: If the manifest's ``[dependencies]`` is malformed.
    """
    from chartbook.lock import LOCK_FILE, read_lock, verify

    directory = Path(directory)
    store = store if store is not None else default_store()
    checked = verify(directory, store)
    locked = read_lock(directory / LOCK_FILE)
    gaps = [
        f"{problem.asset or problem.dependency or LOCK_FILE}: {problem.message}"
        for problem in checked.problems
        if problem.kind not in ("not_built", "nothing_pinned")
    ]
    if locked is None:
        return gaps
    found = unreadable = None
    for entry in locked.dependencies:
        key = entry.get("id")
        location = entry.get("location") or {}
        hashed = {
            asset_id: record for asset_id, record in locked.assets_of(key).items() if record.get("content_hash")
        }
        if location.get("kind") not in ("path", "store") or not hashed:
            continue
        commit, made_at = location.get("commit"), entry.get("snapshot")
        if not (commit and made_at):
            gaps.append(
                f"{key}: its pin names no snapshot, so nothing says which commit its bytes "
                f"came from. `chartbook update {key}` pins its newest snapshot "
                f"(its owner makes one with `chartbook snapshot`)."
            )
            continue
        if found is None:
            found, unreadable = readable_snapshots(store)
        plain = {a: r for a, r in hashed.items() if not (r.get("ref") or {}).get("rev")}
        labels = {a: r for a, r in hashed.items() if (r.get("ref") or {}).get("rev")}
        # The snapshot the lockfile names: at that moment, and holding each
        # asset pinned from it under its own name at its own hash
        at_moment = [t for t in found if t.same_moment(commit, made_at)]
        held = [t for t in at_moment if all(t.content().get(local_name(r)) == r["content_hash"] for r in plain.values())]
        if not at_moment:
            why = next((reason for path, reason in unreadable if commit in str(path)), None)
            said = f": a record at that commit cannot be read ({why})" if why else ""
            gaps.append(
                f"{key}: the lockfile pins its snapshot at {commit[:7]}, made {made_at}, and the store at "
                f"{store} has no such snapshot{said}, so nothing says what it was made from. "
                f"`chartbook update {key}` pins one the store has."
            )
            continue
        if not held:
            before = len(gaps)
            for asset_id, record in sorted(plain.items()):
                if not any(t.content().get(local_name(record)) == record["content_hash"] for t in at_moment):
                    gaps.append(
                        f"{asset_id}: is pinned at {record['content_hash'][:19]}…, which its snapshot at "
                        f"{commit[:7]} does not hold as {local_name(record)}: the lockfile was changed by hand, "
                        f"or came from another store. `chartbook update {key}` pins it again."
                    )
            if len(gaps) == before:
                gaps.append(
                    f"{key}: what is pinned from it is not all from one snapshot at {commit[:7]}: the lockfile "
                    f"was changed by hand. `chartbook update {key}` pins it again."
                )
            continue
        # A label names a version: some snapshot of that pipeline must hold it
        pipelines = {t.pipeline for t in held}
        for asset_id, record in sorted(labels.items()):
            name = local_name(record)
            if not any(t.pipeline in pipelines and t.content().get(name) == record["content_hash"] for t in found):
                gaps.append(
                    f"{asset_id}: is pinned at {record['content_hash'][:19]}…, a version of {name} that no "
                    f"snapshot of it in the store holds: the lockfile was changed by hand, or came from "
                    f"another store. `chartbook update {key}` pins it again."
                )
    return gaps


def require_lineage(directory: Union[str, Path], pipeline: str, store: Optional[Store] = None) -> None:
    """Refuse a snapshot whose pins do not give its full lineage (:func:`lineage_gaps`).

    :raises SnapshotError: Listing each gap and what to run.
    """
    from chartbook.lock import LockError

    try:
        gaps = lineage_gaps(directory, store)
    except (LockError, ValueError) as error:
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {error}") from None
    if gaps:
        shown = "\n".join(f"  {gap}" for gap in gaps)
        raise SnapshotError(
            f"{pipeline} cannot have a snapshot: its pins do not account for every dependency, and a "
            f"snapshot carries its lineage.\n{shown}\nThen commit chartbook.lock, and snapshot again."
        )


def require_committed(
    directory: Union[str, Path], pipeline: str, ignoring: tuple = ()
) -> Code:
    """Check that a pipeline can have a snapshot now, and say where it is in git.

    :param ignoring: File names that may be uncommitted all the same; see
        :func:`uncommitted`.
    :raises SnapshotError: If its folder is not in git, or anything in it
        is not committed. The message lists what.
    """
    try:
        code = code_of(directory)
    except SnapshotError as error:
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {error}.") from None
    changes = uncommitted(directory, ignoring)
    if changes:
        shown = "\n".join(f"  {line}" for line in changes[:10])
        more = f"\n  and {len(changes) - 10} more" if len(changes) > 10 else ""
        raise SnapshotError(
            f"{pipeline} has changes that are not committed:\n{shown}{more}\n"
            f"A snapshot is labelled with the commit it was built from, so "
            f"everything in the pipeline's folder must be committed first."
        )
    return code


def check_within(directory: Union[str, Path], pipeline: str) -> None:
    """Refuse a manifest whose declared paths reach outside the pipeline's folder.

    What :func:`make` checks when it stores; here, so that it can be found
    out before a build, not after one.

    :raises SnapshotError: Naming the first asset that reaches out.
    """
    directory = Path(directory).resolve()
    for local, declared_path, absolute in declared_files(directory):
        reached = hashing.escapes(absolute, directory)
        if reached is not None:
            raise SnapshotError(
                f"{pipeline} declares {str(local.in_pipeline(pipeline))!r} at "
                f"{declared_path!r}, which reaches {reached}, outside the "
                f"pipeline's folder. A snapshot is what the pipeline built, so "
                f"everything in it must be under {directory}."
            )


#: What a tag name may be, to be recorded and shown: git's own rules are
#: looser, and a record in a shared store is anyone's to write
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,99}")


def _tag_names(value: object) -> list:
    """Tag names as a record holds them: text in a tag's shape, at most 50; anything else is left out."""
    if not isinstance(value, list):
        return []
    return [tag for tag in value if isinstance(tag, str) and _TAG.fullmatch(tag) and ".." not in tag][:50]


def _tags_at(directory: Path, commit: str) -> list:
    """The git tags on a commit, sorted: the names of the version a snapshot is of."""
    try:
        listed = _git(Path(directory), "tag", "--points-at", commit)
    except SnapshotError:
        return []
    return sorted(_tag_names(listed.split()))


def _built_with(run: bool, lineage: str = "pins") -> dict:
    """The conditions a snapshot is being made under, as far as they are recorded.

    ``lineage`` says how its lineage was checked: ``pins`` (its own pins
    account for every dependency, which every snapshot now needs) or
    ``deep`` (every snapshot upstream was walked and checked too).
    """
    from chartbook import __version__

    return {
        "run": run,
        "lineage": lineage,
        "chartbook": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _inputs(directory: Path) -> list:
    """What a pipeline is itself pinned to: the dependencies of its lockfile.

    Read from the file as it is, so that a snapshot says what it was built
    from. They hold no absolute path and no password.

    :raises SnapshotError: If there is a lockfile and it cannot be read.
    """
    lockfile = directory / "chartbook.lock"
    if not lockfile.is_file():
        return []
    try:
        with open(lockfile, encoding="utf-8") as f:
            records = json.load(f)["records"]
        for record in records:
            if record.get("kind") == "Pipeline":
                return list(record.get("dependencies") or [])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError(f"Cannot read {lockfile}: {error}") from None
    return []


def _scores(directory: Path, entry) -> Optional[dict]:
    """A model's scores as its metrics file has them now, if it has a readable one."""
    from chartbook.models import read_metrics

    declared = entry.get("metrics_path") if isinstance(entry, dict) else None
    if not isinstance(declared, str) or not declared.strip():
        return None
    metrics_file = directory / declared
    if not metrics_file.is_file():
        return None
    try:
        return read_metrics(metrics_file)
    except ValueError:
        return None  # `chartbook check` is what reports a malformed one


def pipeline_in(directory: Union[str, Path]) -> str:
    """The ID of the pipeline in a folder, which must hold one.

    :raises SnapshotError: If the folder holds no pipeline.
    """
    directory = Path(directory).resolve()
    manifest_path = directory / MANIFEST_NAME
    try:
        raw = _read_manifest_file(directory)
    except FileNotFoundError:
        raise SnapshotError(f"No {MANIFEST_NAME} in {directory}.") from None
    if resolve_project_type(raw, source=str(manifest_path)) != "pipeline":
        raise SnapshotError(
            f"{directory} is a catalog. A snapshot is of one pipeline: run "
            f"`chartbook snapshot` in the pipeline's own folder."
        )
    return derive_pipeline_id(raw.get("project") or {}, directory)


def make(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    made_at: Optional[str] = None,
    built_by_run: bool = False,
    ignoring: tuple = (),
    deep: bool = False,
) -> SnapshotReport:
    """Make a snapshot of a pipeline: what it has built, at the commit it is on.

    Every asset the pipeline declares and has built is put in the store,
    as its own frozen copy, and a record of them is written under the
    commit. An asset that is declared and not built is in the record
    without a hash, and in the report.

    If nothing has changed since the newest snapshot at this commit, no
    new one is made; unless that one took its owner's word and this one
    follows a build, which is worth recording.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param made_at: The time to record, for a test; now by default.
    :param built_by_run: Whether the build was run by the command that is
        making this snapshot (``chartbook run --snapshot``).
    :param ignoring: File names that may be uncommitted; see
        :func:`uncommitted`.
    :param deep: Also refuse if any snapshot upstream has a gap in its own
        lineage (:func:`chartbook.lineage.walk`), not only this pipeline's
        pins.
    :returns: The snapshot, and whether it is new.
    :raises SnapshotError: If the folder holds no pipeline, is not in git,
        has anything uncommitted, or has built nothing.
    """
    directory = Path(project_dir).resolve()
    pipeline = pipeline_in(directory)
    code = require_committed(directory, pipeline, ignoring)

    store = store if store is not None else default_store()
    require_lineage(directory, pipeline, store)
    if deep:
        from chartbook.lineage import walk

        upstream = [(node, gap) for node, gap in walk(directory, store).gaps() if node.kind != "working"]
        if upstream:
            shown = "\n".join(f"  {node.label}: {gap}" for node, gap in upstream[:10])
            more = f"\n  and {len(upstream) - 10} more" if len(upstream) > 10 else ""
            raise SnapshotError(
                f"{pipeline} cannot have a snapshot with --deep: a snapshot upstream has a gap in its "
                f"own lineage.\n{shown}{more}\n`chartbook lineage` shows the whole graph."
            )
    raw = _read_manifest_file(directory)
    assets: dict[str, dict] = {}
    not_built: list[tuple[str, str]] = []
    check_within(directory, pipeline)
    for local, declared_path, absolute in declared_files(directory):
        ref = local.in_pipeline(pipeline)
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            assets[str(local)] = asset_record(ref, pipeline, declared_path, None, True)
            not_built.append((str(ref), declared_path))
            continue
        stored = store.put(absolute, links=LINKS)
        record = asset_record(ref, pipeline, declared_path, stored, found.single)
        if local.kind == "model":
            scores = _scores(directory, (raw.get("models") or {}).get(local.name))
            if scores is not None:
                # Kept with the version, so two versions can be compared
                # after the metrics file has been written over
                record["metrics"] = scores
        assets[str(local)] = record

    # A dataframe that is a table or a query in a DuckDB file has no file of
    # its own: it is written out as parquet into the store, so that a pin
    # copies it like any file and another pipeline reads it by name
    for local, record, reason in materialize_in_source(directory, pipeline, raw, store):
        assets[str(local)] = record
        if reason is not None:
            not_built.append((record["id"], reason))

    # What each model was trained on: the hashes staleness is later judged
    # against. A version keeps the inputs it was first made with, so a later
    # snapshot of the same bytes copies the first one's record forward;
    # only bytes no snapshot has held yet take the inputs as they are now
    now = training_inputs(directory, raw, assets)
    for model_name, record in assets.items():
        if not model_name.startswith("model/") or not record.get("content_hash"):
            continue
        first = _first_holding(directory, model_name, record["content_hash"], store)
        if first is not None and first.get("trained_on"):
            record["trained_on"] = dict(first["trained_on"])
        elif model_name in now:
            record["trained_on"] = now[model_name]

    if not assets:
        raise SnapshotError(
            f"{pipeline} declares nothing with a path, so there is nothing to "
            f"take a snapshot of."
        )
    if len(not_built) == len(assets):
        raise SnapshotError(
            f"{pipeline} has built nothing it declares, so there is nothing to "
            f"take a snapshot of. Build it first: `chartbook run`."
        )

    snapshot = Snapshot(
        pipeline,
        code.commit,
        code.subdirectory,
        made_at or _now(),
        assets,
        built_with=_built_with(built_by_run, "deep" if deep else "pins"),
        inputs=_inputs(directory),
        labels=labels_of(raw),
        tags=_tags_at(directory, code.commit),
        repository=web_link(remote_to_web_url(get_git_remote_url(code.top))),
        first_commit=_first_commit(code.top),
    )
    # The files a writer needs that are not assets, worked out before anything
    # is compared, so that a pipeline with none is not given a new snapshot on
    # every run
    documents, documents_skipped = document_paths(directory, raw)
    # Not one dated after now: it would stand for this commit for as long as its date says
    before = [taken for taken in find(store, code.commit, code.subdirectory) if not made_in_the_future(taken)]
    # The newest record of this commit that says at least as much of its
    # repository as this one would, with nothing newer that holds other
    # bytes: a clone with a path remote, or a shallow one, reuses its main
    # checkout's, and the main checkout makes its own once. A newer record
    # with other bytes would otherwise be the one a pin takes.
    same = None
    for taken in before:
        if taken.content() != snapshot.content():
            break
        # One made under another ID is not this pipeline's, whose ID has
        # changed since (a remote added, a folder renamed): it gets its own
        if taken.pipeline == snapshot.pipeline and identity_keys(snapshot) <= identity_keys(taken):
            same = taken
            break
    if same is not None:
        # The same bytes; made again only to say more than the one before:
        # its documents, that a run built them, or the commit's tags, since
        # a commit is often tagged after it is built. Or because the store
        # has lost its index or its documents (its assets were put back
        # above): an index is made again with the time it is made, so it is
        # not the same object, and the new snapshot holds both
        says_as_much = (same.documents is not None or not documents) and same.tags == snapshot.tags
        lost = [part["content_hash"] for part in (same.index, same.documents) if part and not store.has(part["content_hash"])]
        if says_as_much and (same.built_by_run or not built_by_run) and not lost:
            store.note_origin(code.commit, record_name(code.subdirectory), str(code.top))
            return SnapshotReport(same, False, not_built, skipped_labels=labels_skipped(raw))
        if same.built_by_run:
            # Made again for what the one before lacks: the bytes are still the ones a run built
            snapshot = dataclasses.replace(snapshot, built_with=dict(snapshot.built_with, run=True))

    # A model whose bytes no snapshot of this pipeline has had is a new version
    new_versions = []
    for name in sorted(assets):
        content_hash = assets[name].get("content_hash")
        if not name.startswith("model/") or not content_hash:
            continue
        had = [h for h, _ in versions_of(directory, name, store)]
        if content_hash not in had:
            new_versions.append((name, version_name(content_hash, had)))

    # The version's own description, and the files a writer needs, with the
    # bytes. The bytes are what a snapshot is for: an index that cannot be
    # built (a manifest a docs build would refuse) is said, not fatal. It is
    # not tried again at this commit unless the bytes change
    index_skipped = None
    try:
        index = _put_index(_version_index(directory), store)
    except Exception as error:  # noqa: BLE001 - whatever the docs build would have raised
        said = str(error).strip()
        index, index_skipped = None, said.splitlines()[0].rstrip(".") if said else type(error).__name__
    snapshot = dataclasses.replace(snapshot, index=index, documents=_put_documents(directory, documents, store))
    path = _write(snapshot, store)
    store.note_origin(code.commit, record_name(code.subdirectory), str(code.top))
    snapshot = dataclasses.replace(snapshot, path=path)
    return SnapshotReport(
        snapshot,
        True,
        not_built,
        new_versions,
        labels_skipped(raw),
        index_skipped=index_skipped,
        documents_skipped=documents_skipped,
    )


#: The one file in a snapshot's index object.
INDEX_FILE = "index.json"


def _version_index(directory: Path) -> dict:
    """The pipeline's own index as a docs build of its folder would write it now, published.

    Published: no path of this machine is in it, so it may sit in a store a
    team shares. A model's versions in it are those made before this
    snapshot, since this one is not written yet. Every file is hashed again,
    as a docs build hashes it; the cost of that is the price of an index
    that says exactly what a build of this commit would say. The manifest's
    warnings are passed on, saying where they come from.
    """
    import warnings

    from chartbook import index as index_module
    from chartbook.manifest import apply_code_change_times, load_manifest

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        manifest = load_manifest(directory)
        apply_code_change_times(manifest)
        built = index_module.build_index(manifest, cache=hashing.HashCache())
    for warning in caught:
        warnings.warn(f"While recording the version's index: {warning.message}", UserWarning, stacklevel=3)
    return index_module.published(built)


def _put_index(published: dict, store: Store) -> dict:
    """Put an index in the store as an object holding one ``index.json``."""
    import tempfile

    from chartbook import index as index_module

    with tempfile.TemporaryDirectory(prefix="chartbook-index-") as scratch:
        path = Path(scratch) / INDEX_FILE
        index_module.write_index(published, path)
        stored = store.put(path, links=LINKS)
    return {"content_hash": stored.content_hash, "size_bytes": stored.size_bytes}


def safe_relative(text: object) -> Optional[str]:
    """A path from a manifest or a record, if it is a plain path inside a folder; else None.

    Judged by its text alone, since it may come from a store a team shares
    or from a manifest written to mislead: nothing absolute on any system
    (``/x``, ``\\x``, ``C:x``, ``C:\\x``), no ``..`` anywhere, no part named
    ``.git``, no ``:`` (a Windows drive, an alternate stream, git's pathspec
    magic). ``/`` and ``\\`` both separate parts.

    :returns: The path with ``/`` between its parts and no ``.`` part.
    """
    from pathlib import PurePosixPath, PureWindowsPath

    if not isinstance(text, str) or not text.strip() or "\0" in text:
        return None
    text = text.strip()
    for pure in (PurePosixPath(text), PureWindowsPath(text)):
        if pure.drive or pure.root:
            return None
    parts = [part for part in re.split(r"[\\/]+", text) if part not in ("", ".")]
    if not parts:
        return None
    for part in parts:
        if part == ".." or ":" in part or _is_dot_git(part):
            return None
    return "/".join(parts)


#: Code points HFS+ drops from a name, so that ``.g\u200cit`` is ``.git`` there (git's ``is_hfs_dotgit``).
_HFS_IGNORED = re.compile("[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]")


def _is_dot_git(part: str) -> bool:
    """Whether a name is, or a filesystem may take it for, ``.git``.

    As git judges it: case does not count; HFS+ drops certain invisible code
    points; NTFS drops trailing dots and spaces and has the short name
    ``git~1``.
    """
    name = _HFS_IGNORED.sub("", part).lower().rstrip(". ")
    return name == ".git" or name.startswith("git~")


def plain_name(name: str) -> Optional[str]:
    """A name exactly as git or a store gave it, if it is already a plain path; else None.

    :func:`safe_relative` puts a path written by a person in order. A name
    a program gave is not put in order: one that differs from its plain
    form (a trailing space, a ``\\`` on a system where it is a letter) may
    name some other file, an ignored one, once put in order.
    """
    return name if safe_relative(name) == name else None


def _through_a_link(root: Path, relative: str) -> bool:
    """Whether a path inside *root* is a link, or is under one."""
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            return True
    return False


#: Why a document is not kept, by the reason's key.
NOT_A_PLAIN_PATH = "not a plain path inside the pipeline's folder"
A_LINK = "a link, or under one: only files that are themselves in the folder are kept"
NOT_A_FILE = "not a file"
NOT_TRACKED = "not tracked by git"


def document_paths(
    directory: Union[str, Path], raw: Optional[dict] = None
) -> tuple[list[str], list[tuple[str, str]]]:
    """The files of a pipeline a writer needs that are not assets, as git tracks them.

    The manifest and the lockfile; the README; every write-up an asset
    names (``docs_path``); the pipeline's own site pages, every file under
    its ``site_dir`` (``docs_src/site/`` by default); the logo and the
    favicon if the manifest names them. Read from the manifest's text, so
    that a manifest a docs build would refuse still has its documents kept.

    What is taken: only files git tracks, so nothing ignored, a ``.env``
    above all, can reach the store; only files that are themselves in the
    folder, so no link and nothing under a link; only plain paths
    (:func:`safe_relative`), asked of git literally, so that no glob
    character or pathspec magic reaches past what was named.

    :returns: The paths kept, relative to the pipeline's folder, with ``/``,
        sorted; and each path not kept, with why.
    """
    from chartbook.resolve import ASSET_TABLES

    directory = Path(directory)
    raw = raw if raw is not None else _read_manifest_file(directory)
    project = raw.get("project") or {}
    wanted = {MANIFEST_NAME, "chartbook.lock"}
    for key, default in (("readme", "README.md"), ("site_dir", "docs_src/site"), ("logo", ""), ("favicon", "")):
        value = project.get(key) if isinstance(project.get(key), str) and project[key].strip() else default
        if value:
            wanted.add(value.strip())
    for table in ASSET_TABLES:
        for entry in (raw.get(table) or {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("docs_path"), str) and entry["docs_path"].strip():
                wanted.add(entry["docs_path"].strip())

    explicit = {project.get(key, "").strip() for key in ("readme", "site_dir", "logo", "favicon") if isinstance(project.get(key), str)}
    for table in ASSET_TABLES:
        for entry in (raw.get(table) or {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("docs_path"), str):
                explicit.add(entry["docs_path"].strip())

    skipped: list[tuple[str, str]] = []
    asked = []
    for path in sorted(wanted):
        plain = safe_relative(path)
        if plain is None:
            skipped.append((path, NOT_A_PLAIN_PATH))
        else:
            asked.append((path, plain))
    if not asked:
        return [], skipped
    listed = _git(directory, "--literal-pathspecs", "ls-files", "-z", "--", *sorted({p for _, p in asked}))
    names = sorted({name for name in listed.split("\0") if name})
    root = Path(os.path.realpath(directory))
    kept = []
    for name in names:
        plain = plain_name(name)
        if plain is None:
            skipped.append((name, NOT_A_PLAIN_PATH))
        elif _through_a_link(directory, plain):
            skipped.append((plain, A_LINK))
        elif not (directory / plain).is_file():
            skipped.append((plain, NOT_A_FILE))
        elif not Path(os.path.realpath(directory / plain)).is_relative_to(root):
            skipped.append((plain, NOT_A_PLAIN_PATH))
        else:
            kept.append(plain)
    # A path the manifest names, that is there and that git does not track, is said too
    for path, plain in asked:
        if path in explicit and os.path.lexists(directory / plain):
            if not any(name == plain or name.startswith(plain + "/") for name in names):
                skipped.append((plain, NOT_TRACKED))
    return kept, skipped


#: The most a snapshot's stored index is read of: more than a pipeline's
#: index, and little enough that parsing it (JSON takes many times its
#: size in memory) does not trouble the machine reading it
STORED_INDEX_LIMIT = 8 * 1024 * 1024


def _read_regular_file(path: Path, limit: int) -> bytes:
    """A file's bytes, only if it is a regular file of at most ``limit`` bytes, not read through a link.

    As :func:`_copy_regular_file` copies: looked at, opened without following
    a final link (and without waiting, should it have become a pipe), and the
    two must be one file. What a store holds was written by whoever can
    write to it, so a link out of it, a device or a pipe is not read.

    :raises OSError: If it is not such a file, or is longer.
    """
    import stat

    looked = os.lstat(path)
    if not stat.S_ISREG(looked.st_mode) or looked.st_size > limit:
        raise OSError(f"{path} is not a regular file of at most {limit} bytes")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as reader:
        opened = os.fstat(reader.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (looked.st_dev, looked.st_ino):
            raise OSError(f"{path} changed while it was opened")
        read = reader.read(limit + 1)
    if len(read) > limit:
        raise OSError(f"{path} is longer than {limit} bytes")
    return read


def _copy_regular_file(source: Path, target: Path) -> bool:
    """Copy a file only if it is a regular file, not a link, and the very file that was looked at.

    The file is looked at, then opened without following a final link, and
    the two must be one file (device and inode): a file swapped for a link,
    or a folder above it swapped for one, between the two is not copied.
    """
    import stat

    try:
        looked = os.lstat(source)
        if not stat.S_ISREG(looked.st_mode):
            return False
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(source, flags)
    except OSError:
        return False
    with os.fdopen(descriptor, "rb") as reader:
        opened = os.fstat(reader.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (looked.st_dev, looked.st_ino):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
    return True


def _put_documents(directory: Path, paths: list[str], store: Store) -> Optional[dict]:
    """Put a pipeline's documents in the store as one object, each under its own path; None if there are none."""
    import tempfile

    if not paths:
        return None
    with tempfile.TemporaryDirectory(prefix="chartbook-documents-") as scratch:
        staged = Path(scratch)
        copied = 0
        for relative in paths:
            # Checked again, and opened so that what is read is what was checked:
            # the folder may change while it is read
            if plain_name(relative) is None or _through_a_link(directory, relative):
                continue
            if _copy_regular_file(directory / relative, staged / relative):
                copied += 1
        if not copied:
            return None
        for file in staged.rglob("*"):
            if file.is_symlink():  # never written above; checked all the same
                raise SnapshotError(f"A link appeared among the documents being stored: {file.relative_to(staged)}")
        stored = store.put(staged, links=LINKS)
    return {"content_hash": stored.content_hash, "size_bytes": stored.size_bytes, "files": list(stored.files)}


@dataclass
class Materialized:
    """What :func:`materialize` laid out.

    Attributes:
        folder: The folder the version was laid out in.
        documents: The documents written, by path in the folder.
        assets: The assets written, by reference.
        left_out: The assets and documents not written, each with why.
    """

    folder: Path
    documents: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    left_out: list[tuple[str, str]] = field(default_factory=list)


def materialize(taken: Snapshot, into: Union[str, Path], store: Optional[Store] = None) -> Materialized:
    """Lay a snapshot out as a folder: its documents and its assets at their paths, from the store alone.

    The folder is then the pipeline at that version, as far as a site is
    concerned: ``chartbook docs`` builds the version's site there with the
    repository gone. Its code is not in it; the commit names that. Beside
    the documents and the assets:

    - each model's scores, as the snapshot recorded them, are written to
      its ``metrics_path``, which a build writes and git does not keep;
    - a ``site_dir`` the manifest names is made if none of its files were
      kept, so that a docs build there does not refuse it;
    - :data:`chartbook.identity.VERSION_FILE` says which pipeline and which
      version this is, so the folder keeps the pipeline's ID wherever it is
      and says when its code last changed without asking git.

    A dataframe that is a table or a query is in the store as parquet while
    the manifest names its database, so it is left out and said. A record
    is read from a store that may be shared, so every path in it is judged
    by its text (:func:`safe_relative`), no link in an object is followed,
    and nothing is written until every object it names is there, whole as
    its record has it (:func:`not_whole`).

    :param into: A folder that does not exist yet or is empty.
    :raises StoreNotReadyError: If an object it names is not in the store,
        or not whole: a sync that has not finished, perhaps.
    :raises SnapshotError: If the snapshot carries no documents (it was made
        before snapshots did), or *into* is a file or has something in it.
    """
    import shutil

    from chartbook.hashing import glob_root
    from chartbook.identity import VERSION_FILE

    store = store if store is not None else default_store()
    if not taken.documents:
        raise SnapshotError(
            f"The snapshot of {taken.pipeline} at {taken.commit[:7]} ({taken.made_at}) carries no "
            f"documents: it was made before snapshots did. Make a new one at that commit."
        )
    folder = Path(into)
    if folder.exists() and not folder.is_dir():
        raise SnapshotError(f"{folder} is a file; a snapshot is laid out in an empty folder.")
    if folder.exists() and any(folder.iterdir()):
        raise SnapshotError(f"{folder} has something in it; a snapshot is laid out in an empty folder.")
    named = [taken.documents.get("content_hash")]
    named += [r["content_hash"] for r in taken.assets.values() if r.get("content_hash") and (r.get("location") or {}).get("kind") == "file"]
    try:
        missing = [h for h in named if not isinstance(h, str) or not store.has(h)]
    except ValueError as error:  # a hash that is not one: a record written to mislead
        raise SnapshotError(f"The snapshot of {taken.pipeline} names an object that is not a hash: {error}") from None
    if missing:
        raise (StoreNotReadyError if all(isinstance(h, str) for h in missing) else SnapshotError)(
            f"The store {store} does not have {len(missing)} object(s) the snapshot of {taken.pipeline} at "
            f"{taken.commit[:7]} names, {missing[0]} first; in a store a sync service keeps, the sync may "
            f"not have finished. `chartbook store verify` says more."
        )
    # Each object whole as its record has it: a site built from a file a
    # sync has half delivered would be wrong, and kept
    for record in [taken.documents, *taken.assets.values()]:
        declared = (record.get("location") or {}).get("path")
        if record is not taken.documents and safe_relative(declared) is None:
            continue  # not laid out at all, and said so below
        if record.get("content_hash") in named:
            unsynced = not_whole(store, record)
            if unsynced:
                raise StoreNotReadyError(
                    f"The snapshot of {taken.pipeline} at {taken.commit[:7]} names {record['content_hash']}, "
                    f"and {unsynced}."
                )
    folder.mkdir(parents=True, exist_ok=True)
    report = Materialized(folder.resolve())

    # The version file first, so that nothing a record names can take its place
    marker = {"pipeline": taken.pipeline, "commit": taken.commit, "made_at": taken.made_at}
    if taken.subdirectory:
        marker["subdirectory"] = taken.subdirectory
    code_changed_at = _code_changed_at(taken, store)
    if code_changed_at:
        marker["code_changed_at"] = code_changed_at
    (folder / VERSION_FILE).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")

    held = Path(store.get(taken.documents["content_hash"]))
    for relative in taken.documents.get("files", []):
        plain = plain_name(relative) if isinstance(relative, str) else None
        if plain is None or plain.split("/")[0] == VERSION_FILE:
            report.left_out.append((str(relative), NOT_A_PLAIN_PATH))
            continue
        if _through_a_link(held, plain):
            report.left_out.append((plain, A_LINK))
            continue
        if os.path.lexists(folder / plain) or not _copy_regular_file(held / plain, folder / plain):
            report.left_out.append((plain, NOT_A_FILE))
            continue
        report.documents.append(plain)

    for name in sorted(taken.assets):
        record = taken.assets[name]
        location = record.get("location") or {}
        if not record.get("content_hash"):
            report.left_out.append((record["id"], "not built when the snapshot was made"))
            continue
        if location.get("kind") != "file":
            report.left_out.append(
                (record["id"], "a table or a query: in the store as parquet, and the manifest names its database")
            )
            continue
        declared = location.get("path", "")
        plain = safe_relative(declared)
        if plain is None or plain.split("/")[0] == VERSION_FILE:
            report.left_out.append((record["id"], f"its path {declared} is not a plain path inside the pipeline's folder"))
            continue
        held = Path(store.get(record["content_hash"]))
        if is_glob_pattern(plain):
            _copy_tree(held, folder / glob_root(plain))
        elif record.get("files"):
            _copy_tree(held, folder / plain)
        else:
            # The same bytes may be held under several names: the declared one, else the first
            files = sorted(p for p in held.iterdir() if p.is_file() and not p.is_symlink())
            source = held / Path(plain).name
            if source.is_symlink() or not source.is_file():
                source = files[0] if files else None
            if source is None:
                report.left_out.append((record["id"], "its object holds no file"))
                continue
            target = folder / plain
            if os.path.lexists(target) or not _copy_regular_file(source, target):
                report.left_out.append((record["id"], "its file could not be written where its path says"))
                continue
        report.assets.append(record["id"])

    _write_back(taken, folder, report)
    # Whatever the filesystem made of the names written, there is no repository here
    if os.path.lexists(folder / ".git"):
        planted = folder / ".git"
        if planted.is_dir() and not planted.is_symlink():
            shutil.rmtree(planted)
        else:
            planted.unlink()
        raise SnapshotError(
            f"Laying out the snapshot of {taken.pipeline} at {taken.commit[:7]} made a .git in {folder}, which "
            f"this filesystem took one of its names for; it was removed, and the folder is not to be used."
        )
    return report


def _write_back(taken: Snapshot, folder: Path, report: Materialized) -> None:
    """What a build writes, git does not keep and the snapshot recorded: scores, and an empty site folder."""
    from chartbook.identity import VERSION_FILE

    try:
        raw = _read_manifest_file(folder) if (folder / MANIFEST_NAME).is_file() else {}
    except (OSError, ValueError):
        return  # the docs build says what is wrong with a manifest
    for name, entry in (raw.get("models") or {}).items():
        record = taken.assets.get(f"model/{name}") or {}
        plain = safe_relative(entry.get("metrics_path")) if isinstance(entry, dict) else None
        if plain is None or plain.split("/")[0] == VERSION_FILE:
            continue
        if not isinstance(record.get("metrics"), dict) or os.path.lexists(folder / plain):
            continue
        try:
            target = folder / plain
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(record["metrics"], indent=2) + "\n", encoding="utf-8")
        except OSError:
            report.left_out.append((f"model/{name}", f"its scores could not be written to {plain}"))
    site_dir = safe_relative((raw.get("project") or {}).get("site_dir"))
    if site_dir is not None and site_dir.split("/")[0] != VERSION_FILE:
        try:
            (folder / site_dir).mkdir(parents=True, exist_ok=True)
        except OSError:
            report.left_out.append((site_dir, "the site folder could not be made"))


def _stored_records(taken: Snapshot, store: Store) -> list:
    """The records of the index a snapshot holds; empty when it has none or it cannot be read.

    The index is whatever its owner put in the store, so nothing is assumed
    of its shape: anything but a JSON object with a list of records reads
    as none, and each record is still to be checked by what reads it.
    """
    if not isinstance(taken.index, dict) or not isinstance(taken.index.get("content_hash"), str):
        return []
    try:
        held = Path(store.get(taken.index["content_hash"])) / INDEX_FILE
        recorded = json.loads(_read_regular_file(held, STORED_INDEX_LIMIT).decode("utf-8"))
    except (OSError, ValueError, KeyError, TypeError, RecursionError, StoreError):
        return []
    records = recorded.get("records") if isinstance(recorded, dict) else None
    return records if isinstance(records, list) else []


def stored_pipeline_record(taken: Snapshot, store: Store) -> dict:
    """The snapshot's own Pipeline record, from the index it holds; empty when it has none or it cannot be read.

    Anything but a record of the pipeline's own ID is no record.
    """
    for record in _stored_records(taken, store):
        if isinstance(record, dict) and record.get("kind") == "Pipeline" and record.get("id") == taken.pipeline:
            return record
    return {}


#: How many of a pipeline's assets known from the store alone a page or ``chartbook ls`` lists,
#: of each pipeline: anyone who can write to the store chose how many there are
STORED_ASSETS_SHOWN = 100

#: The records of an index that are a pipeline's assets, each with the kind its ID names
_ASSET_KINDS = {"Dataframe": "dataframe", "Chart": "chart", "Model": "model", "Notebook": "notebook", "Note": "note"}


def stored_assets(taken: Snapshot, store: Store) -> list[dict]:
    """The assets the index a snapshot holds lists, each as ``{"kind", "id", "name"}``, by ID; empty when it has none.

    For a pipeline known from the store alone, whose folder is not here to
    say what it declares. Only a record whose ID reads as a reference to
    an asset of the snapshot's own pipeline, of the kind the record says,
    is listed; its name is one line of plain text
    (:func:`chartbook.identity.plain_line`), empty when it has none.
    Anyone who can write to the store wrote these.
    """
    from chartbook.identity import plain_line
    from chartbook.refs import parse_asset_ref

    listed: dict[str, dict] = {}
    for record in _stored_records(taken, store):
        if not isinstance(record, dict) or record.get("kind") not in _ASSET_KINDS:
            continue
        text = record.get("id")
        if not isinstance(text, str) or len(text) > 500:
            continue
        try:
            ref = parse_asset_ref(text)
        except ValueError:
            continue
        if ref.pipeline_id != taken.pipeline or ref.registry or ref.kind != _ASSET_KINDS[record["kind"]] or ref.part or ref.rev:
            continue
        listed.setdefault(str(ref), {"kind": record["kind"], "id": str(ref), "name": plain_line(record.get("name"), 200)})
    return [listed[asset_id] for asset_id in sorted(listed)]


def _code_changed_at(taken: Snapshot, store: Store) -> Optional[str]:
    """When the version's code last changed, as its index recorded it; None if it has none."""
    changed = stored_pipeline_record(taken, store).get("code_changed_at")
    return changed if isinstance(changed, str) else None


def _copy_tree(source: Path, target: Path) -> None:
    """Copy an object's files to a folder, writable, under the same relative paths; never through a link."""
    for file in hashing.directory_files(source):
        relative = file.relative_to(source).as_posix()
        if plain_name(relative) is None or _through_a_link(source, relative):
            continue
        destination = target / relative
        if not os.path.lexists(destination):
            _copy_regular_file(file, destination)
