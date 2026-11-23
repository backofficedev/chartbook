"""Snapshots: what one commit of a pipeline built, kept in the store.

A pipeline is worked on while other pipelines depend on it. So the others
never read its folder. They read a **snapshot**: every asset the pipeline
declares, as it was built at one commit, copied into the store and
labelled with that commit.

A snapshot is made on purpose, by whoever works on the pipeline, when its
build is ready for others::

    $ chartbook snapshot
    ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
    Snapshot made: 6 files, 23.0 MB.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

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
        ftsfr+fed_yield_curve/                 the pipeline
          2026-10-13T182205Z_4f2a91c0e1b2/     when it was made _ its commit
            _data/treasury_rates.parquet       every file of it, in its place
            _chartbook/snapshot.json           the record

A record is JSON in the index's format, like a lockfile: an envelope and
one record for each asset, each with its content hash, and, for each of
its files, where the store keeps it (``stored``): in a folder store, the
snapshot's own folder, which holds every file of a complete snapshot; in a
bucket, and in a store ChartBook 0.5 laid out, each file once in the
pipeline's folder, usually in the first snapshot that had it
(:class:`chartbook.store.PendingSnapshot`). A snapshot keeps what it names
from being cleared (:func:`chartbook.lock.plan_gc`).

**Complete, or an increment.** A folder store keeps a later snapshot where
little changed in less room, under ``increments/``: its folder holds the
files that one complete snapshot of the pipeline does not have, and its
record says of each file which of the two folders keeps it. Which kind a
snapshot is, each store decides as the snapshot is made, by the rule of
adding up (:func:`to_be_kept`); ``chartbook snapshot --complete`` asks for
a complete one. To whatever reads or pins, it is a snapshot either way
(``docs_src/design/snapshots-and-increments.md``).

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

import collections
import hashlib
import contextlib
import dataclasses
import json
import os
import platform
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from chartbook import formats, hashing
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
from chartbook.manifest import VERSION_PATTERN, _read_manifest_file, later_form_said, resolve_project_type
from chartbook.refs import KIND_TABLES, AssetRef
from chartbook.resolve import MANIFEST_NAME, RESOLVABLE_KINDS, declared_files
from chartbook.store import OWN_DIR, TABLES_DIR, PendingSnapshot, Store, StoreError, declared_name, default_store, plain_parts
from chartbook.utils import is_glob_pattern

#: The version of a snapshot record's envelope.
SCHEMA = "chartbook/snapshot/v2"

#: The versions of a record this version reads: v1 is a store of ChartBook
#: 0.2's, as ``store migrate`` finds it, and lists no file but a folder's.
READS = ("chartbook/snapshot/v1", SCHEMA)


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


class NotInARepository(SnapshotError):
    """A pipeline's folder is in no git repository (:func:`code_of`): a class of its own, as :class:`RepositoryNotTrusted` is, so that what has shorter words for it need not read the sentence."""


class NothingToSnapshot(SnapshotError):
    """A pipeline with nothing to take a snapshot of: it declares nothing with a path, or has built none of what it declares.

    Not a fault of anything: a pipeline just begun. ``chartbook snapshot``
    says so and lists what is not built; ``chartbook run --snapshot``,
    which was asked to end with one, fails with it. A plain ``chartbook
    run`` makes no snapshot, and never meets it.

    Attributes:
        not_built: What it declares and has not built, each with its path
            or with why, as :attr:`SnapshotReport.not_built` has them.
    """

    def __init__(self, message: str, not_built: Optional[list] = None):
        super().__init__(message)
        self.not_built = list(not_built or [])


class NotInEveryStore(SnapshotError):
    """A snapshot that was written to the first of the stores it goes to, and whose copy to another failed: making it again finishes the copies."""


class RepositoryNotTrusted(SnapshotError):
    """A pipeline's folder is in a repository that git will not read, because another user owns it or it is on a network share (:func:`code_of`).

    The folder is in git, and git says nothing of it until it is told to
    trust the repository: the message has the command that does that. A
    class of its own so that what asks where a folder is in git can tell
    this from a folder in no repository without reading the sentence.

    Attributes:
        command: The command that makes git trust the repository, as this
            system's shells take it (``git config --global --add
            safe.directory …``), for what has to give it apart from the
            sentence; empty where no command of ChartBook's can name the
            folder, and the sentence points to git's own.
    """

    def __init__(self, message: str, command: str = ""):
        super().__init__(message)
        self.command = command


class StoreNotReadyError(SnapshotError):
    """Raised when the store does not have all of a snapshot's objects yet, or not all of their bytes.

    In a store a sync service keeps, the sync may not have finished: trying
    again later may succeed, so what fails for this is not kept as failed.
    """


def schema_path() -> Path:
    """The JSON Schema file for a snapshot record's envelope."""
    return SCHEMAS_DIR / "snapshot" / "v2.json"


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
        stored: Where the store keeps the files of what it holds, as its
            record says: ``{"records": {name: …}, "index": …, "documents":
            …}``, each as :attr:`chartbook.store.StoredObject.stored` has
            it. Kept apart from the records, which a lockfile copies.
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
    stored: dict = field(default_factory=dict, compare=False)

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
        held = self.stored.get("records") or {}

        def with_stored(part: dict, stored: Optional[dict]) -> dict:
            return {**part, "stored": stored} if stored else part

        if self.index:
            document["index"] = with_stored(self.index, self.stored.get("index"))
        if self.documents:
            document["documents"] = with_stored(self.documents, self.stored.get("documents"))
        document["records"] = [with_stored(self.assets[name], held.get(name)) for name in sorted(self.assets)]
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
            a version, or one whose value is not a version. ``chartbook run
            --check`` refuses the same ones.
        index_skipped: Why the version's index could not be built and is
            not in the snapshot, in one line; None when it is (or when no
            new snapshot was made).
        documents_skipped: The documents the manifest names that were not
            kept, each with why: not a plain path inside the folder, a
            link, not a file.
        stores: Where it was written: the names of the catalog's stores,
            or the one store it was given.
        several: Whether the catalog has more than one store, so that
            saying which it went to tells something.
        not_hashed: The dataframes whose rows have no hash, each with why
            (:class:`chartbook.rowhash.NotHashed`): a pin of one is met by
            the same file and by nothing else.
        not_hashed_now: The dataframes whose rows could not be hashed this
            time, for no fault of theirs, each with why
            (:class:`chartbook.rowhash.NotNow`): the record says nothing
            of their rows, and the next snapshot of the same bytes hashes
            them.
        rows_said: For a snapshot that was made: each dataframe whose file
            is not the one the snapshot before it had, with what its rows
            are beside that one's, new rows or earlier rows changed
            (:func:`chartbook.standins.since`).
        rows_beside: The snapshot before it, which those are told beside.
        index_columns: The dataframes whose file has the column pandas
            makes of an index with no name
            (:data:`chartbook.rowhash.INDEX_COLUMN`), or of a level with
            none of an index of several.
        index_column_names: And which columns those are, by the
            dataframe's ID.
        rows_first_said: For a snapshot that was made of the same files as
            one already at this commit: that one, where it says nothing of
            a dataframe's rows that this one records. A snapshot made by a
            ChartBook from before rows were recorded is why this one was
            made at all, and the command says so.
        rows_first_count: And how many dataframes' rows this one is the
            first to record. One whose rows are not hashed is not counted:
            the command says why it has none.
        not_whole: For a snapshot that was made of the same files, commit
            and pins as one already in the store, because that one lacks a
            file of its own (:meth:`chartbook.store.Store.holes_of`): that
            one, the files it lacks, and the store it lacks them in where
            that is another store this run sends the snapshot to (None
            where it is the one the snapshot is made in). It is left as it is.
        kept: How the store it was written to keeps the snapshot, as its
            record there says (:class:`Kept`): complete, or as an
            increment, with the counts and sizes a person is told. Of the
            one already there, where no new one was made.
        asked_complete: Whether a complete snapshot was asked for
            (``--complete``), and so where its folder is, is said.
        kept_otherwise: For a snapshot that was made and sent to several
            stores: each other store that keeps it the other way (complete
            there and an increment here, or the reverse), by its name,
            with how it keeps it. Each store decides for itself.
    """

    snapshot: Snapshot
    made: bool
    not_built: list[tuple[str, str]] = field(default_factory=list)
    new_versions: list[tuple[str, str]] = field(default_factory=list)
    skipped_labels: list[tuple[str, str]] = field(default_factory=list)
    index_skipped: Optional[str] = None
    documents_skipped: list[tuple[str, str]] = field(default_factory=list)
    stores: list[str] = field(default_factory=list)
    several: bool = False
    not_hashed: list[tuple[str, str]] = field(default_factory=list)
    not_hashed_now: list[tuple[str, str]] = field(default_factory=list)
    rows_said: list[tuple[str, str]] = field(default_factory=list)
    rows_beside: Optional[Snapshot] = None
    index_columns: list[str] = field(default_factory=list)
    index_column_names: dict = field(default_factory=dict)
    rows_first_said: Optional[Snapshot] = None
    rows_first_count: int = 0
    not_whole: Optional[tuple] = None
    kept: Optional["Kept"] = None
    asked_complete: bool = False
    kept_otherwise: list[tuple[str, "Kept"]] = field(default_factory=list)


@dataclass(frozen=True)
class Kept:
    """How one store keeps one snapshot: complete, or as an increment on a complete one.

    Attributes:
        files: How many files its record lists.
        size_bytes: Their bytes: the size of the snapshot, kept complete.
        builds_on: For an increment, the folder name of the complete
            snapshot of its pipeline that keeps the rest of its files;
            empty for a complete one.
        rest_made_at: For an increment, when that snapshot was made.
        own_files: How many of its files its own folder holds: all of them
            for a complete one; for an increment, those the snapshot it
            builds on does not have.
        own_bytes: Their bytes: what keeping it copied.
        increments_bytes: For an increment, what its record carries beside
            what it builds on: the bytes of the increments made on that
            snapshot up to and with this one.
        added_up: For a complete one that :func:`to_be_kept` decided:
            whether it is complete because the increments since the last
            complete one, with this one, had added up to its size. Not so
            for one that alone is the whole of it, every file differing.
        folder: Its folder in the store, once it is written.
    """

    files: int
    size_bytes: int
    builds_on: str = ""
    rest_made_at: str = ""
    own_files: int = 0
    own_bytes: int = 0
    increments_bytes: int = 0
    added_up: bool = False
    folder: Optional[Path] = None

    @property
    def increment(self) -> bool:
        """Whether it is kept as an increment."""
        return bool(self.builds_on)


def asset_record(
    ref: AssetRef,
    pipeline: str,
    declared_path: str,
    content,
    single: bool,
    keep: bool = False,
    reading: Optional[dict] = None,
    locked: bool = False,
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
    :param keep: Whether the manifest marks the asset ``keep = true``: every
        version of it is kept in the store (``docs_src/design/keep.md``).
        Written only when it does.
    :param reading: A dataframe's ``format`` and ``read_options``, as its
        manifest gives them (:func:`chartbook.formats.declared`), kept in
        its ``location`` so that a pipeline that reads the pin reads the
        bytes as their owner said to. Written only when given.
    :param locked: Whether the manifest marks the asset ``lock = true``: a
        pipeline that depends on this one pins it in its lockfile, whatever
        its kind (:func:`chartbook.lock.in_lockfile`). Written only when
        it does.
    """
    record = {
        "kind": record_kind(ref.kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": pipeline,
        "location": {"kind": "file", "path": declared_path, **(reading or {})},
    }
    if keep:
        record["keep"] = True
    if locked:
        record["lock"] = True
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


def source_record(
    ref: AssetRef, pipeline: str, entry: dict, source: Optional[dict], content, keep: bool = False,
    locked: bool = False,
) -> dict:
    """A dataframe that is a table or a query in a source, as a snapshot records it.

    Its ``location`` is the source's, as the index writes it: the kind, the
    source's name and backend, the manifest's public url, and the table's
    name or the query's text. With *content*, the hash of the parquet file
    the table was written out to, which is what a pin copies. *keep* and
    *locked* are as :func:`asset_record` has them.
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
    if keep:
        record["keep"] = True
    if locked:
        record["lock"] = True
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
        # Fetched whole: from DuckDB 2.0 a result read in part keeps the connection busy
        ((serialized,),) = connection.execute("select json_serialize_sql(?)", [sql]).fetchall()
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
    name = declared_name(declared)
    return {name: size} if name else None


def improper_path(record: dict) -> Optional[str]:
    """Why a reader of this record would reach outside its object, or None.

    A reader lays a glob's tail after its fixed prefix, and a directory's
    listed files, onto the object the store holds
    (``chartbook.resolve._held``). A record may come from anyone who can
    write to a store, so each must be a plain relative path: no ``..``, no
    absolute part (:func:`chartbook.store.plain_parts`). A file's record is
    read by its name alone, and a table's or a query's by the asset's name,
    so neither can reach outside.
    """
    location = record.get("location") or {}
    if not isinstance(location, dict) or location.get("kind") in ("table", "query"):
        return None
    declared = location.get("path")
    if isinstance(declared, str) and is_glob_pattern(declared):
        tail = Path(declared).relative_to(hashing.glob_root(declared))
        if not _plain_everywhere(tail.as_posix()):
            return f"has the path {declared!r}, which is not plain after its wildcard"
    listed = record.get("files")
    if isinstance(listed, list):
        for entry in listed:
            name = entry.get("path") if isinstance(entry, dict) else None
            if isinstance(name, str) and not _plain_everywhere(name):
                return f"lists the file {name!r}, which is not a plain path in its object"
    return None


def _plain_everywhere(relative: str) -> bool:
    """Whether a path inside an object stays inside it on every system.

    Parts joined by ``/`` or ``\\``, none empty, ``.`` or ``..``, and no
    NUL. What one system reads otherwise (a colon or a backslash in a name,
    on Windows) is that system's reader's concern, for that asset alone
    (:func:`chartbook.store.plain_parts`), not a reason to refuse the whole
    snapshot everywhere.
    """
    if not isinstance(relative, str) or not relative or "\0" in relative:
        return False
    return all(part not in ("", ".", "..") for part in re.split(r"[\\/]", relative))


def not_whole(store: Store, record: dict, pipeline: Optional[str] = None) -> Optional[str]:
    """Why the store's object of a record with a hash is not whole as the record has it; None if it is, or that cannot be told.

    By the names and sizes of the files a reader opens (:func:`files_read`),
    and, for a directory, that it holds no file its record does not list.
    Nothing is read (:meth:`chartbook.store.Store.incomplete`). With *pipeline*, the
    pipeline it is of, whole means that one of that pipeline's own snapshots holds it whole.
    """
    if not record.get("content_hash"):
        return None
    files = files_read(record)
    every = files is not None and isinstance(record.get("files"), list)
    if pipeline is None:
        return store.incomplete(record["content_hash"], record.get("size_bytes"), files, every)
    return store.incomplete(record["content_hash"], record.get("size_bytes"), files, every, pipeline=pipeline)


@contextlib.contextmanager
def _staged(staging: Optional[Path], name: str, pending=None, prefix: str = "chartbook-"):
    """A folder to stage files for a snapshot in, as its path.

    The folder *name* under *staging*, which whoever made *staging* removes
    once the snapshot is written or let go (:func:`_make_in`). On the way
    out of the block, every file in it goes but those the snapshot being
    made still wants at hand
    (:meth:`chartbook.store.PendingSnapshot.at_hand`): one it has written
    into its own folder is kept no longer, and one whose copy waits for the
    record stays, as where the bytes are taken from if the earlier
    snapshot's copy has gone or is damaged by then. With no *staging*, a
    folder of its own, removed on the way out.
    """
    import tempfile

    if staging is None:
        with tempfile.TemporaryDirectory(prefix=prefix) as scratch:
            yield scratch
        return
    folder = Path(staging) / name
    folder.mkdir(parents=True, exist_ok=True)
    yield str(folder)
    wanted = pending.at_hand() if isinstance(pending, PendingSnapshot) else set()
    for directory, _, files in os.walk(folder):
        for file in files:
            if os.path.realpath(os.path.join(directory, file)) not in wanted:
                try:
                    os.remove(os.path.join(directory, file))
                except OSError:
                    pass  # it goes with the folder, once the snapshot is written or let go


def materialize_in_source(
    directory: Path, pipeline: str, raw: dict, store: Union[Store, "PendingSnapshot"], rows=None,
    staging: Optional[Path] = None,
) -> list[tuple[AssetRef, dict, Optional[str]]]:
    """Write each table or query dataframe out as parquet, into the store: a snapshot being made, at ``_chartbook/tables/<name>.parquet``.

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

    :param rows: What says a record's rows, given the record and the
        parquet file written out (:func:`_rows_of`); nothing by default.
    :param staging: A folder to write the parquet files out in, which the
        caller removes once the snapshot is written or let go
        (:func:`_staged`); by default each is removed as soon as it is put.
    :returns: For each such dataframe, in name order: its local reference,
        its record, and why it was not written out, or None.
    """
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
        keep = entry.get("keep") is True
        locked = entry.get("lock") is True
        source = sources.get(entry.get("source"))
        what = f"table {entry['table']}" if entry.get("table") else "query"
        where = f"{what} in source {entry.get('source')!r}"
        if source is None:
            found.append((local, source_record(ref, pipeline, entry, None, None, keep=keep, locked=locked), f"{where}: no such source"))
            continue
        if source.get("backend") != "duckdb":
            # A warehouse's table is read where it is, by whoever reads it
            found.append((local, source_record(ref, pipeline, entry, source, None, keep=keep, locked=locked),
                          f"{where}: a {source.get('backend')} source is read where it is, and a snapshot "
                          f"does not pin it yet"))
            continue
        url = source["_resolved_url"]
        if url == MEMORY_URL:
            found.append((local, source_record(ref, pipeline, entry, source, None, keep=keep, locked=locked),
                          f"{where}: only a table in a DuckDB file is written out as parquet"))
            continue
        if not Path(duckdb_path(url, directory)).is_file():
            found.append((local, source_record(ref, pipeline, entry, source, None, keep=keep, locked=locked),
                          f"{where}: the DuckDB file is not there"))
            continue
        with _staged(staging, "tables", store, prefix="chartbook-tables-") as scratch:
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
                found.append((local, source_record(ref, pipeline, entry, source, None, keep=keep, locked=locked),
                              f"{where}: could not be read: {error}"))
                continue
            finally:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001 - never opened, or closed already
                    pass
            # A copy, never a link: the file is about to be deleted with its folder
            if isinstance(store, PendingSnapshot):
                stored = store.put(out, place=f"{TABLES_DIR}/{name}.parquet", links=("reflink", "copy"))
            else:
                stored = store.put(out, links=("reflink", "copy"))
            record = source_record(ref, pipeline, entry, source, stored, keep=keep, locked=locked)
            if rows is not None:
                # While the file is still there: its rows, as any dataframe's
                record.update(rows(str(local), record, out, entry, None))
        if stored.stored:
            record["stored"] = stored.stored  # where it is kept, which make() takes off the record
        found.append((local, record, None))
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


#: How :func:`_git` begins what it says where git itself could not be run (not installed, not on the PATH): nothing
#: is known of the folder then, and what asked says that, not what git's silence would mean
_GIT_NOT_RUN = "git could not be run"


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
        raise SnapshotError(f"{_GIT_NOT_RUN}: {error}") from None
    if result.returncode != 0:
        said = result.stderr.strip() or f"git {arguments[0]} failed"
        raise SnapshotError(said)
    return result.stdout


def _its_line(printed: str) -> str:
    """The one line git printed, without its line end and with every other character of it: a folder's name may end in a space."""
    return printed[:-1] if printed.endswith("\n") else printed


def _name_on_disk(parent: Path, name: str, listings: dict) -> str:
    """The name the disk has for the entry of a folder that *name* opens.

    The name itself where the folder lists it. Where it does not, the
    disk took another spelling for one of its entries (another letter
    case, the other of Unicode's forms, a short name of Windows): the
    entry that is the same file is the one, and its name is the disk's.
    Nothing but the folder's listing is looked at, and its entries only
    for a name the listing does not have. A folder that cannot be listed,
    or lists no such entry, leaves the name as it came.
    """
    key = str(parent)
    if key not in listings:
        try:
            listings[key] = os.listdir(parent)
        except OSError:
            listings[key] = None
    listed = listings[key]
    if listed is None or name in listed:
        return name
    wanted = parent / name

    def folded(text: str) -> str:
        return unicodedata.normalize("NFC", text).casefold()

    # The likeliest first: the same name in another letter case, or the other of Unicode's forms
    alike = folded(name)
    for entry in sorted(listed, key=lambda entry: folded(entry) != alike):
        try:
            if os.path.samefile(parent / entry, wanted):
                return entry
        except OSError:
            continue
    return name


def _as_the_disk_names_it(path: Path, listings: dict) -> Path:
    """An absolute path with each of its parts under the name the disk has for it (:func:`_name_on_disk`).

    A disk that does not tell letter cases apart, or Unicode's two forms,
    opens ``../RATES`` for a folder it names ``rates``, and
    ``Path.resolve`` keeps the spelling that was typed (on macOS; Windows
    gives the disk's). Two spellings of one folder are then two paths,
    and one is not found under the other.

    :param listings: The folders listed so far, by their path: two paths
        that share their first parts list those once.
    """
    named = Path(path.anchor)
    for part in path.parts[1:]:
        named = named / _name_on_disk(named, part, listings)
    return named


def _not_trusted_by_git(directory: Path, said: str) -> Optional[RepositoryNotTrusted]:
    """What to raise where git refuses to read a repository that is there, because it does not trust it: the sentence, and the command in it; None for any other failure.

    Git reads no repository whose folder is another user's unless it is
    told to (``safe.directory``), and on Windows a folder on a network
    share, or on a drive letter mapped to one, is such a folder whoever
    made it. Git's own words say so: ``fatal: detected dubious ownership
    in repository at '//server/share/…'``, then the ``git config`` line
    that adds the exception. That is no folder outside any repository,
    and the person has one command to run: git's own, with the folder as
    git writes it there (``%(prefix)///server/share/…`` for a share),
    quoted for this system's shell. Without that line, the repository git
    names; without that either, the folder asked of.

    A failure is this one only by git's own sentence, or by its ``git
    config --global --add safe.directory`` line (which git writes the
    same in every language, and wrote before it had the sentence). One
    that merely has ``safe.directory`` in it, as the path of a folder of
    that name, is another failure. And the repository is named whole: git
    writes it between apostrophes, and a path may have one of its own, so
    it is taken from the command line, where git quotes it for a shell.

    :param said: What git said as it failed.
    """
    command = re.search(r"git config --global --add safe\.directory[ \t]+(\S.*)", said)
    if "detected dubious ownership" not in said and not command:
        return None
    import shlex

    from chartbook.missing import NOT_TEXT, _quoted  # which imports this module

    folder = None
    if command:
        try:
            (folder,) = shlex.split(command.group(1).strip())  # as git quotes it, for a POSIX shell
        except ValueError:
            folder = None
    found = re.search(r"detected dubious ownership in repository at '(.+)'[ \t]*$", said, re.MULTILINE)
    if folder is not None:
        # A share's is written for git's own reading there: `%(prefix)/` and then the path
        repository = folder[len("%(prefix)/"):] if folder.startswith("%(prefix)/") else folder
    else:
        repository = found.group(1) if found else str(directory)
        folder = repository
    # The word is handed to git, which is a program and no batch file: the `%` git begins a share's with is
    # text in every shell there, and the command in double quotes makes git trust the folder, by its server
    # and through a connected letter (typed on Windows 11, 2026-11-20, in cmd.exe, Windows PowerShell and Git
    # Bash; git's own line, in single quotes, is two words in cmd.exe). Where the folder's own name holds what
    # a shell would read (a `%NAME%`, a backtick), no command of ours is given: git prints its own in that
    # folder, which PowerShell and Git Bash take as it is
    if _quoted(folder, batch=False) == NOT_TEXT:
        command = ""
        to_run = (
            "run the `git config --global --add safe.directory` command that `git status` prints in that folder "
            "(in PowerShell or Git Bash: `cmd.exe` does not read its quotes)"
        )
    else:
        command = f"git config --global --add safe.directory {_quoted(folder, batch=False)}"
        to_run = f"run `{command}`"
    return RepositoryNotTrusted(
        f"git does not trust the repository that {directory} is in ({repository}): another user owns it, or it "
        f"is on a network share, and git reads no such repository until it is told to. To have git trust it, "
        f"{to_run}, and then this again",
        command,
    )


def code_of(directory: Union[str, Path]) -> Code:
    """Say where a pipeline's folder is in git, and at which commit.

    The folder is placed in its repository by the name the disk has for
    each part of its path, and so is the top git gives
    (:func:`_as_the_disk_names_it`): however the folder was spelled to get
    here, it is one place in its repository, the one a reader of the
    folder under its own name finds. Git's own word for the place
    (``--show-prefix``) is not asked: it writes a name in Unicode's
    composed form whichever the disk has.

    Each message says what is known, and no more. Git that could not be
    run says nothing of the folder. A folder that is not under the top git
    gives is said to be so; that the repository's ``core.worktree`` names
    another folder is said only where git says it is set, since a folder
    typed in another letter case under a parent that may not be listed
    ends there too.

    :raises RepositoryNotTrusted: If git does not trust the repository the
        folder is in (another user's, or on a network share): the message
        has the command that makes git trust it. A ``SnapshotError``
        with a class of its own.
    :raises NotInARepository: If the folder is not in a git repository.
        A ``SnapshotError`` with a class of its own too.
    :raises SnapshotError: If there is no such folder, git could not be
        run, the repository has no commit yet, or git gives a top the
        folder is not under.
    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise SnapshotError(f"there is no folder at {directory}")
    try:
        top = Path(_its_line(_git(directory, "rev-parse", "--show-toplevel"))).resolve()
    except SnapshotError as error:
        if str(error).startswith(_GIT_NOT_RUN):
            raise  # not installed, or not on the PATH: that is what is known, and it is said
        not_trusted = _not_trusted_by_git(directory, str(error))
        if not_trusted is not None:
            raise not_trusted from None
        raise NotInARepository(
            f"{directory} is not in a git repository. A snapshot is labelled "
            f"with the commit it was built from, so only a pipeline that is in "
            f"git has any"
        ) from None
    try:
        commit = _git(directory, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
    except SnapshotError:
        raise SnapshotError(f"the repository at {top} has no commit yet") from None
    listings: dict = {}
    top = _as_the_disk_names_it(top, listings)
    directory = _as_the_disk_names_it(directory, listings)
    try:
        subdirectory = directory.relative_to(top).as_posix()
    except ValueError:
        try:
            elsewhere = _its_line(_git(directory, "config", "--get", "core.worktree"))
        except SnapshotError:
            elsewhere = ""  # not set: git ends 1, and says nothing
        if elsewhere:
            raise SnapshotError(
                f"{directory} is not under {top}, which is where git says the files of its repository are: the "
                f"repository's core.worktree names another folder than its own. A snapshot records where a "
                f"pipeline is in its repository, so it is made of a folder under that one"
            ) from None
        raise SnapshotError(
            f"{directory} is not under {top}, which is the top of its repository as git gives it, so where the "
            f"folder is in its repository cannot be told"
        ) from None
    return Code(top, commit, "" if subdirectory == "." else subdirectory)


def uncommitted(directory: Union[str, Path], ignoring: tuple = (), only: str = ".") -> list[str]:
    """What in a pipeline's folder is not committed, as ``git status`` lists it.

    A changed file, a staged one, and a new file that git does not ignore
    all count. What git ignores does not, which is how built data stays
    out of it. Only the pipeline's own folder is looked at, so other work
    in the same repository does not hold a snapshot up.

    :param ignoring: File names that do not count, wherever they are. The
        lockfile that ``chartbook run`` writes before a build is one.
    :param only: A path in the pipeline's folder to ask of alone, as git
        takes one; the whole folder by default. Git finds the file however
        the folder was spelled to get here (another letter case, another
        of Unicode's forms), and its lines are spelled as the whole
        folder's are.
    :returns: One line for each, as ``git status --porcelain`` prints it,
        with paths from the top of the repository.
    """
    # -z: one record per NUL, and paths as they are, not quoted and escaped
    # as they would be for a terminal. A rename or copy has the old path in
    # a record of its own, which follows.
    listing = _git(
        Path(directory).resolve(),
        "status", "--porcelain", "-z", "--untracked-files=all", "--", only,
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


def ignored_by_git(path: Union[str, Path]) -> Optional[bool]:
    """Whether git ignores a file: True for one in a repository whose rules leave it out, and that it does not track; False for one it tracks, or would.

    None where that cannot be told: no repository there, no git, or a git
    that does not answer in a moment. A caller that acts on either answer
    asks for it by name (``is True``, ``is False``).
    """
    path = Path(path)
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "check-ignore", "--quiet", "--", path.name],
            capture_output=True,
            env={**_git_environment(), "GIT_OPTIONAL_LOCKS": "0"},
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # 0: ignored. 1: not ignored. Anything else is git saying it cannot tell (128: no repository)
    return {0: True, 1: False}.get(result.returncode)


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


#: How many files the snapshots remembered may list in all. A snapshot read holds an entry for every file its
#: record lists, and records differ by four orders of magnitude (one real record lists 127,676 files and
#: another 9), so what a process holds goes by the files listed and not by the number of records: about 140
#: megabytes at this bound, by a measure of 188 MB for 400,000. A process that reads every record of a store
#: (a catalog built, a ``store gc`` planned) holds no more than that until it ends, and a pipeline's whole
#: history stays remembered through one command, where it comes to less. Two records of the largest table
#: known (127,676 files each) are remembered together: the one before and the one being made are the two a
#: snapshot reads again and again.
READ_KEPT_FILES = 300_000

#: The snapshots read and remembered, the least recently read first, each by its record's file with the time
#: and size the file had then and the number of files it lists: a record is never rewritten, so one read is
#: enough while it is remembered. Together they list :data:`READ_KEPT_FILES` at most, but for one that lists
#: more alone. A record that is removed is forgotten (:func:`forget`).
_read_snapshots: collections.OrderedDict = collections.OrderedDict()


def read(path: Union[str, Path]) -> Snapshot:
    """Read one snapshot record; one that is remembered is not read again while its file is unchanged.

    A record lists every file of its snapshot, and one command asks for
    the same record many times over (each snapshot of the pipeline's
    history, each time the history is asked for): it is opened and parsed
    the first time, and the snapshot read then is handed out again for as
    long as the file has the time and the size it had. A record that
    cannot be read is not remembered: a sync may yet bring the rest of it.

    **What is remembered is bounded by what the records hold,** not by
    how many there are: the snapshots remembered list
    :data:`READ_KEPT_FILES` files at most in all (:func:`_how_many_listed`),
    and the least recently read goes first. One record that lists more
    than that is remembered alone, since it is the one being read again
    and again; the next record read puts it out.

    What is handed out is the one snapshot, to every caller: its records
    are not to be changed in place.

    :raises SnapshotError: If the file is not a record this version reads.
    """
    from chartbook.store import _record_stamp

    path = Path(path)
    key = str(path)
    stamp = _record_stamp(path)  # taken before the file is opened: one that changes meanwhile is read again next time
    known = _read_snapshots.get(key)
    if known is not None and stamp is not None and known[0] == stamp:
        _read_snapshots.move_to_end(key)
        return known[1]
    _read_snapshots.pop(key, None)  # gone, or no longer the file that was read
    taken = _read(path)
    if stamp is not None:
        _read_snapshots[key] = (stamp, taken, _how_many_listed(taken))
        # Counted afresh each time one is read from the disk, which costs far more: nothing else keeps the sum
        listed = sum(files for _, _, files in _read_snapshots.values())
        while listed > READ_KEPT_FILES and len(_read_snapshots) > 1:
            listed -= _read_snapshots.popitem(last=False)[1][2]
    return taken


def _how_many_listed(taken: Snapshot) -> int:
    """How many files a snapshot's record says the store keeps for it: those of each asset, of its index and of its documents; one, for a record that lists none.

    What a snapshot read holds in memory goes by this: an entry for each
    file, with its path, its hash, its size and where it is kept.
    """
    stored = taken.stored if isinstance(taken.stored, dict) else {}
    records = stored.get("records")
    held = [*(records.values() if isinstance(records, dict) else ()), stored.get("index"), stored.get("documents")]
    return max(1, sum(len(one["files"]) for one in held if isinstance(one, dict) and isinstance(one.get("files"), list)))


def forget(path: Union[str, Path]) -> None:
    """Forget what was read of one record (:func:`read`): its store has removed it."""
    _read_snapshots.pop(str(Path(path)), None)


def _read(path: Path) -> Snapshot:
    """Open one snapshot record and read it (:func:`read`)."""
    from chartbook.store import _any_length, unreadable_detail

    try:
        # In the form Windows takes whatever its length: a record another machine wrote may be past this one's limit
        with open(_any_length(path), encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError) as error:
        # Not JSON, or not readable: in a store a sync service keeps, a file
        # there before its bytes, most likely
        raise SnapshotError(
            f"Cannot read the snapshot {path}: {unreadable_detail(path, error)}. A sync that has not finished is the "
            f"likeliest cause (a file there before its bytes): run this again once it has finished. If it stays "
            f"unreadable, remove the file; it is the record of one snapshot, and the store then has that snapshot "
            f"no more"
        ) from None
    try:
        if document.get("schema") not in READS:
            raise ValueError(
                f"its schema is {document.get('schema')!r}, and this version of "
                f"ChartBook reads {SCHEMA!r}{later_form_said(document.get('schema'), SCHEMA)}"
            )
        code = document["code"]
        # A record may come from a store anyone on a team writes; what names
        # folders and pages must be what it claims to be
        if not isinstance(code.get("commit"), str) or not _COMMIT.match(code["commit"]):
            raise ValueError("its commit is not a full commit hash")
        if not isinstance(document.get("made_at"), str) or not _MADE_AT.match(document["made_at"]):
            raise ValueError(f"its made_at, {document.get('made_at')!r}, is not a time as a snapshot writes one")
        validate_pipeline_id(document.get("root"))
        if path.name == "snapshot.json":
            # Where a store keeps it says whose it is and at what commit, and must agree
            from chartbook.store import pipeline_folder

            folder = path.parent.parent
            if folder.parent.name != pipeline_folder(document["root"]):
                raise ValueError(f"it names the pipeline {document['root']}, and is in the folder of another, {folder.parent.name}")
            if not folder.name.endswith("_" + code["commit"][:12]):
                raise ValueError(f"its commit, {code['commit'][:7]}, is not the one its folder, {folder.name}, is named by")
        subdirectory = code.get("subdirectory", "")
        if subdirectory and safe_relative(subdirectory) != subdirectory:
            raise ValueError(f"its subdirectory, {subdirectory!r}, is not a plain path")
        for record in document["records"]:
            why = improper_path(record)
            if why:
                raise ValueError(f"its record for {record.get('id')!r} {why}")
        # Where the files are is the store's to read; the records are kept as a lockfile has them
        assets, held = {}, {}
        for record in document["records"]:
            record = dict(record)
            stored = record.pop("stored", None)
            assets[local_name(record)] = record
            if isinstance(stored, dict):
                held[local_name(record)] = stored
        stored = {"records": held} if held else {}
        kept = {}
        for name in ("index", "documents"):
            if document.get(name):
                kept[name] = dict(document[name])
                if isinstance(kept[name].get("stored"), dict):
                    stored[name] = kept[name].pop("stored")
                else:
                    kept[name].pop("stored", None)
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
            index=kept.get("index"),
            documents=kept.get("documents"),
            stored=stored,
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
    return sorted(found, key=lambda s: (s.made_at, _count(s.path, s.made_at)), reverse=True)


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
    # A record that cannot be read is said to be, not passed over: its folder names its commit
    prefixes = store.snapshot_commit_prefixes() - {commit[:12] for commit in commits}
    if not commits and not prefixes:
        return None, code
    # Newest first, and the commit the folder is on comes first of all
    for commit in _git(code.top, "rev-list", "HEAD").split():
        if commit in commits or commit[:12] in prefixes:
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
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path, taken.made_at)))


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
_COMMIT = re.compile(r"^[0-9a-f]{40}\Z")
#: When a snapshot was made, as :func:`_now` writes it (a test may leave out the fraction).
_MADE_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z\Z")  # \Z, not $, which lets a last newline through


def all_snapshots(store: Store) -> list[Snapshot]:
    """Every snapshot in a store, oldest first.

    :raises SnapshotError: If a record cannot be read. Nothing should be
        removed from a store that cannot say what it is keeping.
    """
    found = [read(file) for file in store.all_snapshot_files()]
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path, taken.made_at)))


def is_at(path: Union[str, Path], commit: str) -> bool:
    """Whether a record's file is of a snapshot at *commit*, by where it is: in a folder named ``<time>_<first 12 of the commit>``.

    For a record that cannot be read, which says nothing of itself.
    """
    path = Path(path)
    if path.name == "snapshot.json":
        return path.parent.parent.name.endswith("_" + commit[:12])
    return commit in str(path)  # a store of ChartBook 0.2: under the full commit


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
    found.sort(key=lambda taken: (taken.made_at, _count(taken.path, taken.made_at)))
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
    pinned, or not a reference that parses is left out; ``chartbook run --check``
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
            # as a version; `chartbook run --check` refuses the rest, and a snapshot
            # must not hand a dependant a name its lockfile cannot hold
            if not LABEL_PATTERN.match(label) or _HEX_START.match(label):
                continue
            if isinstance(version, str) and VERSION_PATTERN.match(version):
                pointed.setdefault(f"model/{name}", {})[label] = version.split(":", 1)[-1]
    return pointed


def keeps_of(raw: dict) -> set[str]:
    """The assets a manifest marks ``keep = true``, by their reference within the pipeline.

    Every version of such an asset is kept in the store
    (``docs_src/design/keep.md``): ``store gc`` keeps, for each distinct
    version of its bytes, the newest snapshot holding it. Only ``true``
    counts; the manifest loader refuses any other value.

    :returns: ``{"embeddings", "model/forecaster"}``.
    """
    return _marked(raw, "keep")


def locks_of(raw: dict) -> set[str]:
    """The assets a manifest marks ``lock = true``, by their reference within the pipeline.

    A pipeline that depends on this one pins such an asset in its lockfile
    whatever its kind (:func:`chartbook.lock.in_lockfile`): a chart, a
    notebook, a note or a plain file is otherwise left out, since every
    build draws it anew (``docs_src/design/pins-and-rebuilds.md``). Only
    ``true`` counts; the manifest loader refuses any other value.

    :returns: ``{"file/parameters"}``.
    """
    return _marked(raw, "lock")


def _marked(raw: dict, key: str) -> set[str]:
    """The assets whose entry in a manifest says ``<key> = true``, by their reference within the pipeline."""
    marked: set[str] = set()
    for kind in RESOLVABLE_KINDS:
        entries = raw.get(KIND_TABLES[kind])
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            if isinstance(entry, dict) and entry.get(key) is True:
                try:
                    marked.add(str(AssetRef(kind=kind, name=name)))
                except ValueError:
                    continue  # a key that is not an address has no reference
    return marked


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
    stays repeatable until ``chartbook pin --update`` moves the label.

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
            elif not store.has(named[0][0], newest.pipeline):
                why = "a snapshot names it, and its bytes are not in the store"
            else:
                why = ""
            if why:
                unresolved.append((name, label, start, why))
                continue
            content_hash, taken = named[0]
            # What the version was trained on is the owner's record, keyed in
            # the owner's names; a dependant's lockfile does not carry it
            record = {k: v for k, v in renamed(taken.assets[name], key).items() if k not in ("trained_on", "keep")}
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


def _keeps_in(store: Store, group: list[Snapshot], newest: Optional[Snapshot]) -> set[str]:
    """The assets of one pipeline marked ``keep = true``: in its manifest now, and as its newest snapshot recorded.

    Read as :func:`_labels_in` reads labels: from each folder the snapshots
    were made from, and from the newest snapshot's records, so that a mark
    given on another machine counts here, and a mark the owner has taken
    out releases its versions once a snapshot follows.

    :returns: The assets' references within the pipeline.
    """
    marked: set[str] = set()
    if newest is not None:
        marked.update(local_name(record) for record in newest.assets.values() if record.get("keep") is True)
    seen: set[Path] = set()
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
            marked.update(keeps_of(raw))
    return marked


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


def builds_at(found: list, pipeline: Optional[str], commit: str, named: Optional[str] = None, now: Optional[datetime] = None) -> list:
    """The snapshots that hold a dependency as it was pinned at one commit, for what its lockfile does not: the one its entry names first, then the others of that pipeline at that commit, newest first.

    One definition, for a read of an asset the lockfile does not hold, for
    the checks that say whether such a read will work, and for ``store
    gc``, which keeps them.

    :param found: The store's snapshots that owners made
        (:func:`readable_snapshots`): one a pin made from a clone is no
        build of the pipeline's owner.
    :param pipeline: The pipeline the pins came from, by its own ID. With
        none, nothing is taken: another pipeline's snapshot of the same
        commit (a repository of several) is not this one's.
    :param named: When the snapshot the entry names was made. That one is
        the pin itself, and is taken whatever its date; any other dated
        after now is not, so that a record written to win is never the
        newest.
    """
    if not isinstance(pipeline, str) or not pipeline or not isinstance(commit, str) or not commit:
        return []
    at = [taken for taken in found if taken.commit == commit and taken.pipeline == pipeline]
    exact = [taken for taken in at if isinstance(named, str) and taken.same_moment(commit, named)]
    others = [taken for taken in at if not any(taken is one for one in exact) and not made_in_the_future(taken, now)]
    return exact + sorted(others, key=lambda taken: (taken.made_at, _count(taken.path, taken.made_at)), reverse=True)


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


@dataclass(frozen=True)
class KeptVersion:
    """One version of an asset marked ``keep = true``, and the snapshot that keeps it.

    Attributes:
        pipeline: The pipeline's ID.
        name: The asset's reference within it (``embeddings``, ``model/x``).
        content_hash: The version: the hash of its bytes.
        size_bytes: Its size, as the record has it; 0 if the record does not say.
        snapshot: The newest snapshot of the pipeline holding it, which is kept.
    """

    pipeline: str
    name: str
    content_hash: str
    size_bytes: int
    snapshot: Snapshot


@dataclass
class SnapshotPlan:
    """Which snapshots a store keeps and which it may let go of.

    Attributes:
        keep: Each snapshot that is kept, with why.
        remove: Each snapshot that may be removed, with why it may.
        kept_versions: Each version of an asset marked ``keep = true``
            (:class:`KeptVersion`), for the bill: what the marks keep.
    """

    keep: list[tuple[Snapshot, str]] = field(default_factory=list)
    remove: list[tuple[Snapshot, str]] = field(default_factory=list)
    kept_versions: list[KeptVersion] = field(default_factory=list)

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
    labelled: Optional[dict] = None,
) -> SnapshotPlan:
    """Say which snapshots may be removed. Nothing is removed.

    A snapshot is kept if, in this order:

    1. a lockfile pins it (its commit and time are named by a dependency);
    2. a note of a lockfile pins it: one that cannot be found, one on
       another machine, or one read here whose note, from its last pin,
       names it (*noted*); or, for a note from before notes named their
       snapshots, it is the newest snapshot holding one of the objects the
       note names;
    2b. a lockfile, or a note of one, pins a model version by its label
       (``rates:model/m@champion``), and this is the newest snapshot of that
       pipeline holding the version (*labelled*): a label resolves to a
       version an older snapshot holds, which the pinned moment alone
       would not keep, and a dependant's next snapshot needs it;
    3. it is the newest snapshot of its pipeline, or the newest that a
       branch or a tag of the repository it came from can pin from;
    4. a label points at a model version it holds: in the pipeline's
       manifest, read from the folder the snapshots were made from, or as
       recorded in the newest snapshot of the pipeline (:func:`labels_of`);
    4b. it is the newest snapshot holding a version of an asset the manifest
       marks ``keep = true`` (:func:`keeps_of`, read as labels are: from the
       folder, or from the newest snapshot's records): every version of such
       an asset is kept, with *aggressive* or without, since the mark is a
       cost and not a name (``docs_src/design/keep.md``); each is in
       :attr:`SnapshotPlan.kept_versions`;
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
    :param labelled: The model versions lockfiles and notes pin by label,
        each ``(commit, made_at, name, content_hash)`` as
        :meth:`chartbook.lock.Lock.labelled` gives them, with why each is
        kept. The version is looked for among the snapshots of the pipeline
        the moment names; among every pipeline's where the moment names
        none the store has.
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
            of_whole.append([part, newest, labels, set() if aggressive else _pinnable(store, part, now), _keeps_in(store, part, newest)])
        if len(named) > 1 and unnamed:
            for _, _, labels, _, marks in of_whole[:-1]:
                for name, starts in labels.items():
                    of_whole[-1][2].setdefault(name, set()).update(starts)
                of_whole[-1][4].update(marks)
        planned.extend(of_whole)
    # A note that names no snapshots (from before notes recorded them) keeps,
    # of the snapshots holding each object it names, the newest: an object
    # that never changes would otherwise keep every snapshot there is
    every = sorted((taken for group, _, _, _, _ in planned for taken in group), key=lambda t: (t.made_at, _count(t.path, t.made_at)))

    def newest_holding(hashes: set) -> set:
        # In each pipeline: a note names bytes and not whose they are, and a read of a pipeline's asset
        # is handed that pipeline's own newest holder, never another pipeline's copy of the same bytes
        holder: dict = {}
        for taken in every:
            for content_hash in taken.hashes() & hashes:
                holder[(taken.pipeline, content_hash)] = taken
        return {id(taken) for taken in holder.values()}

    by_missing = newest_holding(set(hashes_of_missing))
    by_elsewhere = newest_holding(set(hashes_elsewhere))
    by_noted = newest_holding(set(hashes_noted))
    noted = noted or {}
    # A lockfile may name a snapshot this store does not have: its author's,
    # where each person builds the other pipeline themselves. What is read
    # of it is then read from the snapshots here of that commit: the newest
    # that holds what is asked for, which need not be the newest of them
    # (builds_at). They stand in, each of them, and are kept as the named one would be
    here = {(taken.commit, taken.made_at) for taken in every}
    # Stand-ins are for a live lockfile's pins only: a note (including one
    # of a branch or tag that is not checked out) holds the snapshot it
    # names and no other of its commit
    absent = {commit for commit, made_at in set(pinned) if (commit, made_at) not in here}
    by_standing = {id(taken) for taken in every if taken.commit in absent and not made_in_the_future(taken, now)}
    by_label = _holding_labelled(every, labelled or {})
    # An asset marked `keep = true` keeps every version of its bytes: for
    # each, the newest snapshot of the pipeline holding it, as a label keeps
    # the version it points at. Whatever else keeps that snapshot, the
    # version is on the bill
    by_keep: dict[int, str] = {}
    for group, _, _, _, marks in planned:
        if not marks:
            continue
        holders: dict[tuple[str, str], Snapshot] = {}
        # Not one dated after now: a record written to win would otherwise be
        # the holder for ever, and the genuine holder let go
        for taken in sorted((t for t in group if not made_in_the_future(t, now)), key=lambda t: (t.made_at, _count(t.path, t.made_at))):
            for name in marks:
                content_hash = (taken.assets.get(name) or {}).get("content_hash")
                if content_hash:
                    holders[(name, content_hash)] = taken
        for (name, content_hash), taken in sorted(holders.items(), key=lambda item: (item[0][0], item[1].made_at, item[0][1])):
            by_keep.setdefault(id(taken), f"it holds a version of {name}, which is kept (`keep = true` in its chartbook.toml)")
            size = (taken.assets.get(name) or {}).get("size_bytes")
            plan.kept_versions.append(KeptVersion(taken.pipeline, name, content_hash, size if isinstance(size, int) else 0, taken))
    for group, newest, labels, pinnable, _ in planned:
        for taken in group:
            if (taken.commit, taken.made_at) in pinned:
                why = "a lockfile pins it"
            elif (taken.commit, taken.made_at) in noted:
                why = noted[(taken.commit, taken.made_at)]
            elif id(taken) in by_label:
                why = by_label[id(taken)]
            elif id(taken) in by_standing:
                why = "a lockfile pins a snapshot of its commit that this store does not have, and it stands in"
            elif id(taken) in by_missing:
                why = "a lockfile that cannot be found named what it holds"
            elif id(taken) in by_elsewhere:
                why = "a lockfile not read here, another machine's, named what it holds"
            elif id(taken) in by_noted:
                why = "a lockfile's note, from its last pin, names what it holds"
            elif taken is newest:
                why = "it is the newest of its pipeline"
            elif id(taken) in by_keep:
                why = by_keep[id(taken)]
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


def _holding_labelled(every: list, labelled: dict) -> dict[int, str]:
    """The snapshots that keep the versions lockfiles pin by label: for each, the newest holding it, with why.

    *every* is every snapshot in the store, oldest first. A version is
    looked for among the snapshots of the pipeline (and folder in its
    repository) that the pinned moment names, as a dependant's lineage check
    does (:func:`lineage_gaps`); where the store has no snapshot at that
    moment, or the pin names none, among them all. The newest holding it is
    kept, as the newest holding an old note's object is: one is enough, and
    an object that never changes would otherwise keep every snapshot.
    """
    kept: dict[int, str] = {}
    if not labelled:
        return kept
    at_moment: dict[tuple[str, str], set] = {}
    for taken in every:
        at_moment.setdefault((taken.commit, taken.made_at), set()).add((taken.pipeline, taken.subdirectory))
    for (commit, made_at, name, content_hash), why in sorted(labelled.items()):
        of_pipeline = at_moment.get((commit, made_at))
        # The newest holder in each pipeline it may be of: a read is handed that pipeline's own, never another's
        holders: dict = {}
        for taken in every:
            if of_pipeline and (taken.pipeline, taken.subdirectory) not in of_pipeline:
                continue
            if taken.content().get(name) == content_hash:
                holders[(taken.pipeline, taken.subdirectory)] = taken
        for holder in holders.values():
            kept.setdefault(id(holder), why)
    return kept


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
                # The snapshot its pin named, and the build of yours that stood in for it where that was not here
                stood = entry.get("stood_in") if isinstance(entry.get("stood_in"), str) else None
                for upstream in by_moment.get((location["commit"], entry["snapshot"]), []) + by_moment.get((location["commit"], stood), []):
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


def _count(path: Path, made_at: Optional[str] = None) -> int:
    """Which of the snapshots made at one instant a file is: 1, unless numbered.

    A store names a snapshot's folder by the second, and gives a second
    snapshot of the same second the next one's name: its folder's name
    orders them.

    :param made_at: When the snapshot was made, as its record says, where
        whoever asks has the snapshot in hand: the record is then not
        opened for it. It lists every file of the snapshot, and this is
        asked of each snapshot each time some are put in order.
    """
    if path.name == "snapshot.json":
        from chartbook.store import is_snapshot_folder

        folder = path.parent.parent.name
        try:
            made = made_at if made_at is not None else json.loads(path.read_text(encoding="utf-8")).get("made_at", "")
            later = datetime.strptime(folder[:18], "%Y-%m-%dT%H%M%SZ") - datetime.strptime(made[:19], "%Y-%m-%dT%H:%M:%S")
        except (OSError, ValueError, AttributeError, TypeError):
            return 1
        return 1 + int(later.total_seconds()) if is_snapshot_folder(folder) else 1
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
    were made from those bytes. So first the check ``chartbook pin --check``
    makes (:func:`chartbook.lock.verify`): a lockfile, every dependency in
    it, pinned from where the manifest says, its bytes in the store. Then,
    for a ``path`` dependency something was pinned from: that its pin names
    a snapshot, by its commit and time, that the store has that snapshot
    and it holds each asset pinned from it under its name at its hash, and
    that each label pinned names a version some snapshot of the pipeline
    holds; so that a lockfile changed by hand, or brought from another
    store, is caught. (A ``git`` dependency is pinned from its clone, not a
    snapshot, and its hashes are checked only to be in the store.) Where
    the store does not have the snapshot a pin names, one of yours of that
    commit that holds every pin of it stands in, by the same bytes or by
    the same rows (:mod:`chartbook.standins`): what was read was read from it.

    Nothing that could not have been read is a gap: an asset the other
    pipeline had not built when it was pinned, and a dependency of which
    nothing is pinned (it declares nothing, or has no snapshot yet). Reads
    that do not go through the lockfile (a load through a catalog, a model
    version named by its hash) are not seen here.

    Where the store has the snapshot a pin names, what the lockfile
    records of each dataframe's rows must be what that snapshot records:
    a build of someone else's is told to hold the pinned rows by them, so
    a lockfile whose rows were changed by hand, or merged from two, would
    pass here and fail for everyone who builds the other pipeline.

    :raises LockError: If the lockfile is there and cannot be read.
    :raises ValueError: If the manifest's ``[dependencies]`` is malformed.
    """
    return _lineage_of_pins(directory, store)[0]


def _lineage_of_pins(directory: Union[str, Path], store: Optional[Store] = None) -> tuple[list[str], dict]:
    """The gaps in a pipeline's lineage (:func:`lineage_gaps`); and, for each dependency whose pinned snapshot the store does not have, the snapshot of yours that stands in for it, by the dependency's key."""
    from chartbook import rowhash, standins
    from chartbook.lock import LOCK_FILE, _read_pipeline, names_a_snapshot, read_lock, verify

    directory = Path(directory)
    store = store if store is not None else default_store()
    checked = verify(directory, store)
    locked = read_lock(directory / LOCK_FILE)
    gaps, said, stood_in = [], set(), {}
    for problem in checked.problems:
        if problem.kind in ("not_built", "nothing_pinned"):
            continue
        once = checked.not_in_store.get(problem.dependency) if problem.kind == "not_in_store" else None
        if once:
            # Pins the store does not have, with no build of yours to stand in: one gap for the dependency
            if problem.dependency not in said:
                said.add(problem.dependency)
                gaps.append(f"{problem.dependency}: " + ". ".join(line.strip().rstrip(".") for line in once) + ".")
            continue
        if problem.kind == "differs":
            said.add(problem.dependency)  # a build of yours that does not match the pin: said here, whole
        gaps.append(
            f"{problem.asset or problem.dependency or LOCK_FILE}: "
            + "; ".join(line.strip() for line in problem.message.splitlines())
        )
    if locked is None:
        return gaps, stood_in
    # The folder of each dependency named by its path, which says whose snapshots its pins came from
    folders = {key: declared.get("_resolved_path") for key, declared in _read_pipeline(directory.resolve())[1].items()}
    found = unreadable = None
    for entry in locked.dependencies:
        key = entry.get("id")
        location = entry.get("location") or {}
        hashed = {
            asset_id: record for asset_id, record in locked.assets_of(key).items() if record.get("content_hash")
        }
        if location.get("kind") not in ("path", "store"):
            continue
        if not hashed:
            if names_a_snapshot(entry):
                # Pinned by its entry alone: where the store does not have the snapshot
                # it names, what is read of it is read from your newest build of that commit
                if found is None:
                    found, unreadable = readable_snapshots(store)
                yours = standins.candidates(entry, found, folders.get(key))
                if yours:
                    stood_in[key] = yours[0]
            continue
        commit, made_at = location.get("commit"), entry.get("snapshot")
        if not (commit and made_at):
            gaps.append(
                f"{key}: its pin names no snapshot, so nothing says which commit its bytes "
                f"came from. `chartbook pin --update {key}` pins its newest snapshot "
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
            # A snapshot of yours of that commit that meets every pin of it, by
            # the same file or by the same rows, stands in for the one named: the
            # same question `chartbook pin --check` asks, with the same answer
            stood = standins.find(entry, locked.assets_of(key), store, found, folders.get(key))
            if stood.stands_in:
                stood_in[key] = stood.snapshot
                continue
            why = next((reason for path, reason in unreadable if is_at(path, commit)), None)
            if key in said and not why:
                continue  # its pins are not in the store, which is why its snapshot is not: said above, with what to do
            unread = f": a record at that commit cannot be read ({why})" if why else ""
            gaps.append(
                f"{key}: the lockfile pins its snapshot at {commit[:7]}, made {made_at}, and the store at "
                f"{store} has no such snapshot{unread}, so nothing says what it was made from. "
                f"`chartbook pin --update {key}` pins one the store has."
            )
            continue
        if not held:
            before = len(gaps)
            for asset_id, record in sorted(plain.items()):
                if not any(t.content().get(local_name(record)) == record["content_hash"] for t in at_moment):
                    gaps.append(
                        f"{asset_id}: is pinned at {record['content_hash'][:19]}…, which its snapshot at "
                        f"{commit[:7]} does not hold as {local_name(record)}: the lockfile was changed by hand, "
                        f"or came from another store. `chartbook pin --update {key}` pins it again."
                    )
            if len(gaps) == before:
                gaps.append(
                    f"{key}: what is pinned from it is not all from one snapshot at {commit[:7]}: the lockfile "
                    f"was changed by hand. `chartbook pin --update {key}` pins it again."
                )
            continue
        # What the lockfile says of each table's rows is what that snapshot says
        for asset_id, record in sorted(plain.items()):
            theirs = held[0].assets.get(local_name(record)) or {}
            if any(record.get(name) != theirs.get(name) for name in rowhash.FIELDS):
                gaps.append(
                    f"{asset_id}: what the lockfile records of its rows is not what its snapshot at {commit[:7]} "
                    f"records: the lockfile was changed by hand, or merged from two. Restore it from git, or "
                    f"`chartbook pin --update {key}` pins it again."
                )
        # A label names a version: some snapshot of that pipeline must hold it
        pipelines = {t.pipeline for t in held}
        for asset_id, record in sorted(labels.items()):
            name = local_name(record)
            if not any(t.pipeline in pipelines and t.content().get(name) == record["content_hash"] for t in found):
                gaps.append(
                    f"{asset_id}: is pinned at {record['content_hash'][:19]}…, a version of {name} that no "
                    f"snapshot of it in the store holds: the lockfile was changed by hand, or came from "
                    f"another store. `chartbook pin --update {key}` pins it again."
                )
    return gaps, stood_in


def require_lineage(directory: Union[str, Path], pipeline: str, store: Optional[Store] = None) -> dict:
    """Refuse a snapshot whose pins do not give its full lineage (:func:`lineage_gaps`).

    :returns: For each dependency whose pinned snapshot the store does not
        have, the snapshot of yours that stands in for it, by the
        dependency's key: what the snapshot records it was made from.
    :raises SnapshotError: Listing each gap and what to run.
    """
    from chartbook.lock import LockError

    try:
        gaps, stood_in = _lineage_of_pins(directory, store)
    except (LockError, ValueError) as error:
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {error}") from None
    if gaps:
        shown = "\n".join(f"  {gap}" for gap in gaps)
        raise SnapshotError(
            f"{pipeline} cannot have a snapshot: its pins do not account for every dependency, and a "
            f"snapshot carries its lineage.\n{shown}\nThen commit chartbook.lock, and snapshot again."
        )
    return stood_in


def require_acyclic(directory: Union[str, Path], pipeline: str, store: Optional[Store] = None) -> None:
    """Refuse a snapshot of a pipeline that depends, through what it depends on, on itself (:func:`chartbook.lineage.cycle`).

    Dependencies between pipelines must form a directed acyclic graph: a
    snapshot carries its lineage, and this one's would lead back to it.

    :raises SnapshotError: Saying who depends on whom, where each was read,
        and what to do.
    """
    from chartbook.lineage import cycle, cycle_lead, explain_cycle

    found = cycle(directory, store)
    if found is not None:
        raise SnapshotError(
            f"{pipeline} cannot have a snapshot: {cycle_lead(found)}, so its lineage would carry a cycle.\n"
            f"{explain_cycle(found)}"
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
    """Refuse a manifest whose declared paths reach outside the pipeline's folder, or name a file with a glob character.

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
        named = hashing.glob_named(declared_path, absolute)
        if named is not None:
            said = hashing.glob_named_said(declared_path, named)
            raise SnapshotError(f"{pipeline} declares {str(local.in_pipeline(pipeline))!r}, and its path {said}.")


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


def _inputs(directory: Path, stood_in: Optional[dict] = None) -> list:
    """What a pipeline is itself pinned to: the dependencies of its lockfile.

    Read from the file as it is, so that a snapshot says what it was built
    from. They hold no absolute path and no password. Where a snapshot of
    yours stood in for the one an entry names, which the store does not
    have, the entry gains ``stood_in``, when that snapshot was made: what
    was read was read from it, and the lineage goes on up from it.

    :param stood_in: The snapshots that stood in, by the dependency's key
        (:func:`require_lineage`).
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
                return [
                    {**entry, "stood_in": stood_in[entry["id"]].made_at}
                    if stood_in and isinstance(entry, dict) and entry.get("id") in stood_in else entry
                    for entry in record.get("dependencies") or []
                ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError(f"Cannot read {lockfile}: {error}") from None
    return []


def _inputs_key(inputs: object) -> list:
    """A snapshot's inputs in one order and form, to tell whether two say the same.

    An entry's ``pinned_from``, the ID its pins are kept under, says where
    they are and not what they are, so it is left out: a lockfile that
    gained it says the same pins as before. So is ``stood_in``, the build
    of the maker's own that was read in the place of a pinned snapshot:
    the same bytes from the same pins are the same snapshot, whichever
    build of the upstream is the newest today, and the one that stays
    recorded is the one that stood in when those bytes were first
    declared ready.
    """
    listed = inputs if isinstance(inputs, list) else []
    return sorted(
        json.dumps(
            {k: v for k, v in entry.items() if k not in ("pinned_from", "stood_in")} if isinstance(entry, dict) else entry,
            sort_keys=True,
            default=str,
        )
        for entry in listed
    )


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
        return None  # `chartbook run --check` is what reports a malformed one


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


def check_store_takes_one(pipeline: str, store: Optional[Store] = None) -> None:
    """Refuse a snapshot of a pipeline where the store it would be written to takes none: one laid out as ChartBook 0.5 laid one out.

    Asked of the stores :func:`make` would write it to, with nothing
    written: for a command that builds first (``chartbook run --snapshot``)
    to find out before the build, as it finds out that work is uncommitted.

    :param store: As for :func:`make`.
    :raises StoreError: What the store says of itself
        (:meth:`chartbook.store.Store.check_writable`): that it has the
        layout of 0.5, and which command moves it; or that it has no
        ``store.json`` and holds what such a store holds. Which stores a
        snapshot goes to, where that cannot be said now (one that is
        read-only, or cannot be reached), is left for :func:`make` to say.
    """
    from chartbook.multi_store import Stores

    if store is None or isinstance(store, Stores):
        try:
            targets = (Stores.configured() if store is None else store).for_writing(pipeline, None)
        except (StoreError, OSError):
            return
    else:
        targets = [store]
    for target in targets:
        check = getattr(target, "check_writable", None)
        if check is not None:
            check()


def _files_listed(taken: Snapshot) -> dict[str, tuple]:
    """Every file a snapshot's record lists, by its path in the pipeline: its hash, its size, and the folder that keeps it where the record says one.

    Read where the record says how the store keeps each part (``stored``):
    its assets, its index and its documents. A file that is of two assets
    is one file.
    """
    listed: dict[str, tuple] = {}
    for part in (*(taken.stored.get("records") or {}).values(), taken.stored.get("index"), taken.stored.get("documents")):
        for entry in (part or {}).get("files") or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str) and isinstance(entry.get("size_bytes"), int):
                listed.setdefault(entry["path"], (entry.get("content_hash"), entry["size_bytes"], entry.get("kept_in")))
    return listed


def _to_build_on(store: Store, taken: Snapshot, now: Optional[datetime] = None) -> Optional[tuple]:
    """The complete snapshot that a snapshot about to be written to a store would be an increment on, and what the increments on it have added up to: ``(its record there, bytes)``; None where there is none to build on.

    The newest complete snapshot of the pipeline in that store that its
    owner made (one a pin made from a repository is built on by nothing),
    of the same repository as the records tell it, as a snapshot's making
    tells it before it says two are one pipeline's (:func:`_make`), whole
    (:meth:`chartbook.store.Store.holes_of`), and not dated after now.
    Complete by what its record is
    (:attr:`chartbook.store.KeptRecord.complete`): one of a pipeline's
    folder that ChartBook 0.5 laid out, copied into the store by hand,
    keeps files in earlier folders and is not built on. The
    bytes are the largest count that any increment on it carries in its
    record, whatever the dates of the two (a machine whose clock is ahead
    or behind makes increments too, and one that had not been brought
    another's writes one that counts from less): 0 where there is none,
    or where none carries one. The count is of what snapshots made in this
    store copied: an increment that ``chartbook store migrate`` wrote, or
    that was copied in from another store (``store move``, ``store
    import``), carries none, and the next snapshot counts from what this
    store's own increments carry.
    """
    records = [
        record for record in store.records()
        if record.readable and record.pipeline == taken.pipeline and record.made_by == "snapshot"
    ]

    def when(record) -> tuple:
        return (record.made_at, record.folder.name)

    for record in sorted((record for record in records if record.complete), key=when, reverse=True):
        try:
            complete = read(record.path)
        except SnapshotError:
            continue
        if not identity_keys(taken) <= identity_keys(complete) or made_in_the_future(complete, now) or store.holes_of(record.path):
            continue
        return record, max(
            (other.increments_bytes for other in records if other.increment and other.builds_on == record.folder.name), default=0
        )
    return None


def to_be_kept(store: Store, taken: Snapshot, complete: bool = False, now: Optional[datetime] = None) -> Kept:
    """How one store is to keep a snapshot that is about to be written to it: the rule of adding up.

    **A snapshot is kept as an increment until the increments since the
    last complete snapshot, with this one, add up to the size of a complete
    one. Then it is a complete one**
    (``docs_src/design/snapshots-and-increments.md``, "Which one
    ``chartbook snapshot`` makes"). The size of a complete one is the bytes
    of every file the snapshot's record lists. An increment's is the bytes
    of the files that the complete snapshot it builds on
    (:func:`_to_build_on`) does not have, by their hashes and sizes,
    whatever their names. So the first snapshot of a pipeline in a store
    is complete, and so is one where every file differs. Each store
    decides for itself, from its own records: this is the one place the
    rule is written, and it reads no file of the snapshot.

    :param taken: The snapshot, with where each of its files is listed
        (``stored``): one its pipeline's owner made.
    :param complete: Whether a complete one was asked for (``--complete``),
        whatever the rule would choose.
    :returns: How it is to be kept. An increment's ``increments_bytes`` is
        what its record is to carry beside what it builds on.
    """
    files = _files_listed(taken)
    size = sum(size for _, size, _ in files.values())
    whole = Kept(len(files), size, own_files=len(files), own_bytes=size)
    if complete or getattr(store, "increments_path", lambda: None)() is None:
        return whole
    found = _to_build_on(store, taken, now)
    if found is None:
        return whole
    on, since = found
    has = {(file.content_hash, file.size_bytes) for asset in on.assets for file in asset.files}
    own = [size for content_hash, size, _ in files.values() if (content_hash, size) not in has]
    if since + sum(own) >= size:
        # Said to have added up only where this one alone is less than the whole: one where every file differs is complete for that
        return dataclasses.replace(whole, added_up=since > 0 and sum(own) < size)
    return Kept(len(files), size, on.folder.name, on.made_at, len(own), sum(own), since + sum(own))


def as_kept(store: Store, taken: Snapshot) -> Kept:
    """How a store keeps a snapshot it has, as its record there says: complete, or as an increment on which one."""
    from chartbook.store import read_kept_record

    files = _files_listed(taken)
    size = sum(size for _, size, _ in files.values())
    folder = Path(taken.path).parent.parent if taken.path is not None else None
    asked = getattr(store, "builds_on", None)
    on = asked(taken.path) if asked is not None and taken.path is not None else None
    if on is None:
        return Kept(len(files), size, own_files=len(files), own_bytes=size, folder=folder)
    own = [size for _, size, kept_in in files.values() if kept_in == folder.name]
    return Kept(
        len(files), size, on.parent.parent.name, read_kept_record(on).made_at, len(own), sum(own),
        read_kept_record(Path(taken.path)).increments_bytes, folder=folder,
    )


def make(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    made_at: Optional[str] = None,
    built_by_run: bool = False,
    ignoring: tuple = (),
    deep: bool = False,
    store_names: Optional[list[str]] = None,
    ask: bool = True,
    complete: bool = False,
) -> SnapshotReport:
    """Make a snapshot of a pipeline: what it has built, at the commit it is on.

    Every asset the pipeline declares and has built is put in the store,
    as its own frozen copy, and a record of them is written under the
    commit. An asset that is declared and not built is in the record
    without a hash, and in the report.

    If nothing has changed since the newest snapshot at this commit (its
    bytes, and what the pipeline is pinned to), no new one is made; unless
    that one took its owner's word and this one follows a build, which is
    worth recording.

    A folder store keeps the snapshot complete, every file of it in its
    own folder, or as an increment, which holds only the files that one
    complete snapshot of the pipeline does not have. Which, each store
    decides for itself by the rule of adding up (:func:`to_be_kept`), and
    the report says (:attr:`SnapshotReport.kept`). To whatever reads or
    pins it, it is a snapshot either way.

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
    :param store_names: The catalog's stores to write to; by default,
        those the catalog sends the pipeline to, or its first.
    :param ask: Whether, at a terminal, a pipeline the catalog sends
        nowhere may be asked about when there are several stores to write
        to. A run that makes a snapshot (``chartbook run --snapshot``, and
        ``--upstream`` of what it builds first) passes False: it asks
        nothing, and follows the catalog. A plain run makes none.
    :param complete: Write a complete snapshot in every store it goes to,
        whatever the rule of adding up would choose (``--complete``).
        Where the newest snapshot of the same commit, bytes and pins is
        kept as an increment, a new, complete one is made: the increment
        is left as it is, since a snapshot's folder is not changed once
        its record is written.
    :returns: The snapshot, and whether it is new.
    :raises SnapshotError: If the folder holds no pipeline, is not in git,
        has anything uncommitted, or has built nothing.
    """
    directory = Path(project_dir).resolve()
    if os.path.lexists(directory / "chartbook.links.toml"):
        raise SnapshotError("Cannot snapshot while chartbook.links.toml exists. Delete it, run `chartbook pin --update`, then snapshot.")
    pipeline = pipeline_in(directory)
    from chartbook.manifest import section_that_is_no_table

    no_table = section_that_is_no_table(_read_manifest_file(directory), MANIFEST_NAME)
    if no_table:
        # What walks the tables would stop on it, each in its own way: said once, in the manifest's words
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {no_table} `chartbook run --check` says more.")
    code = require_committed(directory, pipeline, ignoring)
    from chartbook.multi_store import Stores
    if store is None or isinstance(store, Stores):
        stores = Stores.configured() if store is None else store
        if ask and store_names is None and stores.catalog and not any(pipeline in e.pipelines for e in stores.entries):
            writable = [e for e in stores.entries if not e.read_only]
            import sys
            try:
                is_tty = sys.stdin is not None and sys.stdin.isatty()
            except (AttributeError, ValueError, OSError):
                is_tty = False
            if len(writable) > 1 and is_tty and not os.environ.get("CI") and not os.environ.get("CHARTBOOK_BATCH"):
                import click
                choices = ", ".join(e.name for e in writable)
                answer = click.prompt(f"Write snapshots of {pipeline} to which stores? ({choices}; comma-separated)", default=writable[0].name)
                store_names = [name.strip() for name in answer.split(",") if name.strip()]
                if not store_names:
                    raise ValueError("No store name given")
                stores.for_writing(pipeline, store_names)
                from chartbook.catalog_config import route
                route(pipeline, store_names, stores.catalog)
        targets = stores.for_writing(pipeline, store_names)
        for target in targets:
            # A store laid out as ChartBook 0.5 laid one out takes no snapshot: said before the first is written
            check = getattr(target, "check_writable", None)
            if check is not None:
                check()
        # Validate every target before writing the first one. A partial fan-out
        # remains recoverable: repeating the command skips existing snapshots.
        # The lineage is checked in every store, where the pins were read
        # from: a snapshot pinned from a read-only store is written to another
        stood_in = _check_lineage(directory, pipeline, stores, deep)
        report = _make_in(
            directory, pipeline, code, targets[0], made_at, built_by_run, deep, stood_in, also=tuple(targets[1:]), complete=complete,
        )
        if len(targets) > 1:
            from chartbook.transfer import NotWholeThere, copy_snapshot
            for target in targets[1:]:
                try:
                    # Each store decides for itself how it keeps it, from its own snapshots (to_be_kept)
                    there = copy_snapshot(report.snapshot, targets[0], target, complete=complete, decides=True)
                    theirs = as_kept(target, read(there))
                    if report.made and report.kept is not None and theirs.increment != report.kept.increment:
                        # Kept the other way there: said, with that store's name
                        report.kept_otherwise.append((next((e.name for e in stores.entries if e.store is target), str(target)), theirs))
                except NotWholeThere as error:
                    # That store's own copy of this snapshot lacks a file, and nothing is written over it
                    raise NotInEveryStore(
                        f"{error}. The snapshot in {targets[0]} is whole. If a sync is still bringing the file "
                        f"there, it arrives with the sync. If it is lost for good, that store's copy stays as it "
                        f"is until a later snapshot of {pipeline} is sent there, and then goes with `chartbook "
                        f"store gc` there once nothing keeps it."
                    ) from error
                except (StoreError, OSError) as error:
                    raise NotInEveryStore(f"Snapshot written to {targets[0]}, but copy to {target} failed: {error}. Rerun the snapshot to finish the remaining copies.") from error
        report.stores = [e.name for e in stores.entries if e.store in targets]
        report.several = len(stores.entries) > 1  # with one store there is nothing to tell apart
        return report

    store = store if store is not None else default_store()
    stood_in = _check_lineage(directory, pipeline, store, deep)
    return _make_in(directory, pipeline, code, store, made_at, built_by_run, deep, stood_in, complete=complete)


def _check_lineage(directory: Path, pipeline: str, store: Store, deep: bool) -> dict:
    """Refuse a snapshot whose lineage, read in ``store`` (one, or all of a catalog's), has a gap or a cycle.

    :returns: The snapshots of yours that stood in for ones its pins name
        and the store does not have, by the dependency's key
        (:func:`require_lineage`).
    :raises SnapshotError: Saying what is wrong and what to run.
    """
    stood_in = require_lineage(directory, pipeline, store)
    require_acyclic(directory, pipeline, store)
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
    return stood_in


def _make_in(directory: Path, pipeline: str, code: "Code", store: Store, made_at: Optional[str],
             built_by_run: bool, deep: bool, stood_in: Optional[dict] = None, also: tuple = (),
             complete: bool = False) -> SnapshotReport:
    """Write the snapshot to one store, its lineage already checked (:func:`_check_lineage`); *also* are the other stores it is then sent to."""
    raw = _read_manifest_file(directory)
    check_within(directory, pipeline)
    check_own_name(directory, pipeline, raw)
    import tempfile

    from chartbook.store import FolderStore

    made_at = made_at or _now()
    # A folder store keeps a snapshot complete or as an increment, which is decided once every file of it
    # is known (to_be_kept): its folder there is claimed then, in the one place or the other
    undecided = {"undecided": True} if isinstance(store, FolderStore) else {}
    pending = store.begin(pipeline, code.commit, made_at, base=directory, **undecided)
    # What is staged for the snapshot (its documents, its index, a table written out of a DuckDB file) is
    # kept until the snapshot is written or let go (_staged)
    with tempfile.TemporaryDirectory(prefix="chartbook-snapshot-") as staging:
        try:
            report = _make(
                directory, pipeline, code, raw, store, pending, made_at, built_by_run, deep, stood_in, staging=Path(staging), also=also,
                complete=complete,
            )
            report.stores = [str(store)]
            return report
        except BaseException:
            # What was put in a snapshot that is not written goes with it
            pending.discard()
            raise


def check_own_name(directory: Path, pipeline: str, raw: dict) -> None:
    """Refuse a pipeline that keeps a file a snapshot would hold under ``_chartbook/``, the one name a snapshot's folder keeps for ChartBook.

    :raises SnapshotError: Naming the first such file and what to do.
    """
    named = [(str(local), declared) for local, declared, _ in declared_files(directory)]
    named += [("a document", relative) for relative in document_paths(directory, raw)[0]]
    for what, declared in named:
        parts = [part for part in re.split(r"[\\/]+", str(declared).strip()) if part not in ("", ".")]
        if parts and parts[0].lower() == OWN_DIR:
            raise SnapshotError(
                f"{pipeline} keeps {what} at {declared!r}, under {OWN_DIR}/: a snapshot's folder in the store keeps "
                f"that name for ChartBook's own files. Rename the folder (and the paths in chartbook.toml), "
                f"commit, and make the snapshot again."
            )


def _holes_there(other: Store, taken: Snapshot) -> Optional[tuple]:
    """What another store's own record of one snapshot lacks there: that record, the files, and the store; None where it lacks nothing.

    Its record is found as any is (:func:`find`), by its commit and its
    folder in the repository, and is this snapshot by its pipeline and its
    time. A store with no record of it lacks nothing: the snapshot is
    written there whole. Nor does one that keeps each file once (a bucket),
    or one that cannot be asked now, whose copy then says what is wrong.
    """
    if getattr(type(other), "holes_of", Store.holes_of) is Store.holes_of:
        return None
    try:
        for theirs in find(other, taken.commit, taken.subdirectory):
            if theirs.pipeline == taken.pipeline and theirs.made_at == taken.made_at and theirs.path is not None:
                holes = other.holes_of(theirs.path)
                return (theirs, holes, other) if holes else None
    except (SnapshotError, StoreError, OSError):
        pass
    return None


def _kept_as_an_increment(taken: Snapshot, store: Store, also: tuple = ()) -> bool:
    """Whether a snapshot is kept as an increment in a store, or in any other store of *also* that has a record of it (found as :func:`_holes_there` finds it)."""
    def asked(one: Store, path) -> bool:
        builds_on = getattr(one, "builds_on", None)
        return builds_on is not None and path is not None and builds_on(path) is not None

    if asked(store, taken.path):
        return True
    for other in also:
        try:
            for theirs in find(other, taken.commit, taken.subdirectory):
                if theirs.pipeline == taken.pipeline and theirs.made_at == taken.made_at and asked(other, theirs.path):
                    return True
        except (SnapshotError, StoreError, OSError):
            continue
    return False


def _complete_and_reads_right(taken: Snapshot, store: Store) -> bool:
    """Whether the snapshot a store has is one ``--complete`` may name in place of making one: a complete snapshot of what its record says.

    Complete by what its record is
    (:attr:`chartbook.store.KeptRecord.complete`): not an increment, and
    not one that keeps files in another snapshot's folder, as one that
    ChartBook 0.5 laid out does. And each of its own files, read and
    hashed, is what its record says
    (:meth:`chartbook.store.Store.verify_snapshot`, as ``store move`` asks
    before it takes a snapshot for there). So every byte of it is read:
    only where a complete one was asked for, since the folder is then
    named for a person to look at, to copy or to hand on.
    """
    from chartbook.store import FolderStore, read_kept_record

    if taken.path is None:
        return False
    try:
        if isinstance(store, FolderStore) and not read_kept_record(Path(taken.path)).complete:
            return False
        return not store.verify_snapshot(Path(taken.path), taken.hashes())
    except (StoreError, OSError):
        return False


def _make(directory: Path, pipeline: str, code: "Code", raw: dict, store: Store, pending, made_at: str,
          built_by_run: bool, deep: bool, stood_in: Optional[dict] = None, staging: Optional[Path] = None,
          also: tuple = (), complete: bool = False) -> SnapshotReport:
    """The rest of :func:`make`, once the snapshot is begun: what is put in it, and whether it is written.

    :param staging: A folder for what is staged for the snapshot, which the
        caller removes once this has returned (:func:`_staged`).
    :param also: The other stores this run sends the snapshot to: the one
        it stands on must be whole in each that has a record of it.
    :param complete: As for :func:`make`.
    """
    assets: dict[str, dict] = {}
    held: dict[str, dict] = {}
    not_built: list[tuple[str, str]] = []
    marked, locked = keeps_of(raw), locks_of(raw)
    earlier: list = []  # this pipeline's snapshots, read once if a dataframe asks

    not_now: list[tuple[str, str]] = []  # the dataframes whose rows could not be hashed this time, each with why
    index_columns: list[str] = []  # the dataframes whose file has the column pandas makes of an index with no name
    index_names: dict = {}  # and which columns those are
    # Each dataframe put from files of the folder: where they are, how they are read, and each as it was just before
    # it was put (_as_they_are). What is said of its rows is told from the folder while they are still so (_rows_since)
    put_from: dict = {}

    def rows(name: str, record: dict, path: Path, entry, reading: Optional[dict]) -> dict:
        """What a dataframe's record says of its rows, taken from an earlier snapshot of these bytes where there is one.

        A snapshot is of the bytes, and is made whatever becomes of this:
        where the rows could not be hashed, for want of room for the
        scratch files say, the record says nothing of them and the report
        says why. So too where the folder no longer holds the files the
        dataframe was put from once its rows are hashed there: they are
        not known to be the rows of the bytes the snapshot holds.
        """
        from chartbook import rowhash

        if not earlier:
            try:
                earlier.append(history(directory, store))
            except SnapshotError:
                earlier.append([])
        table = rowhash.Table(path, (reading or {}).get("format"), (reading or {}).get("read_options"))
        made_of_an_index = rowhash.index_columns_of(table) if record.get("content_hash") else []
        if made_of_an_index:
            index_columns.append(record.get("id") or name)
            index_names[record.get("id") or name] = made_of_an_index
        put = put_from.get(name)
        try:
            return _rows_of(name, record, path, entry, reading, earlier[0], put if put is not None and put[0] == path else None)
        except rowhash.NotNow as error:
            not_now.append((record.get("id") or name, str(error)))
            return {}
    for local, declared_path, absolute in declared_files(directory):
        ref = local.in_pipeline(pipeline)
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            assets[str(local)] = asset_record(ref, pipeline, declared_path, None, True, keep=str(local) in marked, locked=str(local) in locked)
            not_built.append((str(ref), declared_path))
            continue
        reading = formats.declared((raw.get("dataframes") or {}).get(local.name)) if local.kind == "dataframe" else None
        if local.kind == "dataframe":
            put_from[str(local)] = (absolute, reading, _as_they_are(found.files))  # before a byte of them is hashed
        stored = pending.put(absolute, links=LINKS)
        held[str(local)] = stored.stored
        record = asset_record(ref, pipeline, declared_path, stored, found.single, keep=str(local) in marked, reading=reading,
                              locked=str(local) in locked)
        if local.kind == "model":
            scores = _scores(directory, (raw.get("models") or {}).get(local.name))
            if scores is not None:
                # Kept with the version, so two versions can be compared
                # after the metrics file has been written over
                record["metrics"] = scores
        if local.kind == "dataframe":
            # Its rows as well as its bytes, by period: what a rebuild can meet
            record.update(rows(str(local), record, absolute, (raw.get("dataframes") or {}).get(local.name), reading))
        assets[str(local)] = record

    # A dataframe that is a table or a query in a DuckDB file has no file of
    # its own: it is written out as parquet into the store, so that a pin
    # copies it like any file and another pipeline reads it by name
    for local, record, reason in materialize_in_source(directory, pipeline, raw, pending, rows=rows, staging=staging):
        if "stored" in record:
            held[str(local)] = record.pop("stored")
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
        raise NothingToSnapshot(
            f"{pipeline} declares nothing with a path, so there is nothing to "
            f"take a snapshot of."
        )
    if len(not_built) == len(assets):
        raise NothingToSnapshot(
            f"{pipeline} has built nothing it declares, so there is nothing to "
            f"take a snapshot of. Build it first: `chartbook run`.",
            not_built,
        )

    snapshot = Snapshot(
        pipeline,
        code.commit,
        code.subdirectory,
        made_at,
        assets,
        built_with=_built_with(built_by_run, "deep" if deep else "pins"),
        inputs=_inputs(directory, stood_in),
        labels=labels_of(raw),
        tags=_tags_at(directory, code.commit),
        repository=web_link(remote_to_web_url(get_git_remote_url(code.top))),
        first_commit=_first_commit(code.top),
        stored={"records": held},
    )
    # The files a writer needs that are not assets, worked out before anything
    # is compared, so that a pipeline with none is not given a new snapshot on
    # every run
    documents, documents_skipped = document_paths(directory, raw)
    # Not one dated after now: it would stand for this commit for as long as its date says
    before = [taken for taken in find(store, code.commit, code.subdirectory) if not made_in_the_future(taken)]
    # The newest record of this commit that says at least as much of its
    # repository as this one would, with nothing newer that holds other
    # bytes or other pins: a clone with a path remote, or a shallow one,
    # reuses its main checkout's, and the main checkout makes its own once.
    # A newer record with other bytes, or pinned to other snapshots (a clone
    # whose own lockfile has moved, with nothing committed), would otherwise
    # be the one a pin takes. What it was pinned to is part of what a
    # snapshot says, so one whose pins have moved since is not given back
    # Each that this could stand on is asked whether it is whole: its own files, at the sizes its
    # record says, one question for each (Store.holes_of), here and in every other store this run
    # sends it to that has a record of it already (one that has none is sent it whole). The newest
    # that is whole in each of them is stood on. One that is not is not stood on, nor written to,
    # since a snapshot's folder is not changed once its record is written; and only where none is
    # whole is a new one made from the files at hand, the report saying which file the newest of
    # them lacks, and in which store where that is not this one
    same = None
    not_whole = None
    rows_first_said, rows_first_count = None, 0  # the one of the same files that says nothing of the rows this one records
    for taken in before:
        if taken.content() != snapshot.content() or _inputs_key(taken.inputs) != _inputs_key(snapshot.inputs):
            break
        # One made under another ID is not this pipeline's, whose ID has
        # changed since (a remote added, a folder renamed): it gets its own
        if taken.pipeline == snapshot.pipeline and identity_keys(snapshot) <= identity_keys(taken):
            holed = (taken, store.holes_of(taken.path), None) if taken.path is not None else (taken, [], None)
            for other in also:
                if holed[1]:
                    break
                holed = _holes_there(other, taken) or holed
            if not holed[1]:
                same, not_whole = taken, None
                break
            not_whole = not_whole or holed
    if not_whole is not None and not_whole[0].built_by_run:
        # The bytes are still the ones a run built, from these same pins: the whole one says so too
        snapshot = dataclasses.replace(snapshot, built_with=dict(snapshot.built_with, run=True))
    if same is not None:
        # The same bytes; made again only to say more than the one before:
        # its documents, that a run built them, or the commit's tags, since
        # a commit is often tagged after it is built. Or because the store
        # has lost its index or its documents, where it keeps each file
        # once (a bucket): an index is made again with the time it is made,
        # so it is not the same object, and the new snapshot holds both
        # Or the rows of a dataframe, which a snapshot made before rows were hashed does not
        # say, and one made before its entry named its dates says otherwise
        from chartbook import rowhash

        says_its_rows = all(
            not any(key in record for key in ("rows", "not_hashed"))
            or all(record.get(key) == (same.assets.get(name) or {}).get(key) for key in rowhash.FIELDS)
            for name, record in snapshot.assets.items()
        )
        says_as_much = (same.documents is not None or not documents) and same.tags == snapshot.tags and says_its_rows
        lost = [
            part["content_hash"] for part in (same.index, same.documents)
            if part and (not store.has(part["content_hash"], same.pipeline) or store.incomplete(part["content_hash"], part.get("size_bytes"), pipeline=same.pipeline))
        ]
        # A file the store lacked (`placed`) is kept only if this snapshot is written
        # Asked for complete, the one there is stood on only where it is a complete snapshot of what its record
        # says: complete by its record, each of its own files read and hashed. Where it is kept as an increment
        # (here, or in another store this run sends it to), keeps files in another folder, or does not read
        # right, a new, complete one is made, and that one is left as it is. Not asked, nothing is read
        tells = says_as_much and (same.built_by_run or not built_by_run) and not lost and not pending.placed
        wanted_complete = tells and complete and (
            _kept_as_an_increment(same, store, also) or not _complete_and_reads_right(same, store)
        )
        if tells and not wanted_complete:
            pending.discard()
            store.note_origin(code.commit, record_name(code.subdirectory), str(code.top))
            return SnapshotReport(
                same, False, not_built, skipped_labels=labels_skipped(raw), not_hashed=_not_hashed(same), not_hashed_now=not_now,
                index_columns=index_columns,
                index_column_names=index_names,
                kept=as_kept(store, same),
                asked_complete=complete,
            )
        if same.built_by_run:
            # Made again for what the one before lacks: the bytes are still
            # the ones a run built, from these same pins
            snapshot = dataclasses.replace(snapshot, built_with=dict(snapshot.built_with, run=True))
        # The dataframes whose rows this one records and that one said nothing of. A table whose rows
        # are not hashed is not of them: of it the command says why, and no rebuild meets a pin of it
        rows_first_count = sum(
            1 for name, record in snapshot.assets.items()
            if "rows" in record and not any(key in (same.assets.get(name) or {}) for key in ("rows", "not_hashed"))
        )
        if rows_first_count:
            rows_first_said = same

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
    stored = dict(snapshot.stored)
    try:
        index, stored["index"] = _put_index(_version_index(directory), pending, staging)
    except Exception as error:  # noqa: BLE001 - whatever the docs build would have raised
        said = str(error).strip()
        index, index_skipped = None, said.splitlines()[0].rstrip(".") if said else type(error).__name__
        stored.pop("index", None)
    kept_documents, stored["documents"] = _put_documents(directory, documents, pending, staging)
    snapshot = dataclasses.replace(snapshot, index=index, documents=kept_documents, stored={k: v for k, v in stored.items() if v})
    # Complete, or an increment: decided now that every file of it is listed, from the hashes and sizes
    # the record is about to carry. If the snapshot it would build on goes before the record is written,
    # or loses a file, the store writes this one complete (_FolderPending.write)
    decided = to_be_kept(store, snapshot, complete)
    if decided.increment and getattr(pending, "undecided", False):
        pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
    path = pending.write(snapshot.to_document())
    store.note_origin(code.commit, record_name(code.subdirectory), str(code.top))
    snapshot = dataclasses.replace(snapshot, path=path)
    # As its record says it is kept, and whether it is complete because the increments had added up
    kept = dataclasses.replace(as_kept(store, snapshot), added_up=decided.added_up)
    beside, rows_said = _rows_since(directory, snapshot, store, put_from)
    return SnapshotReport(
        snapshot,
        True,
        not_built,
        new_versions,
        labels_skipped(raw),
        index_skipped=index_skipped,
        documents_skipped=documents_skipped,
        not_hashed=_not_hashed(snapshot),
        not_hashed_now=not_now,
        rows_said=rows_said,
        rows_beside=beside,
        index_columns=index_columns,
        index_column_names=index_names,
        rows_first_said=rows_first_said,
        rows_first_count=rows_first_count,
        not_whole=not_whole,
        kept=kept,
        asked_complete=complete,
    )


def _as_they_are(files) -> Optional[dict]:
    """Each of some files with its size and when it was last written, as the disk has them now; None where one cannot be asked about."""
    seen = {}
    for file in files:
        try:
            looked = os.stat(file)
        except OSError:
            return None
        seen[str(file)] = (looked.st_size, looked.st_mtime_ns)
    return seen


def _at_hand(put: Optional[tuple]):
    """What gives a dataframe's table where it was put from, in the pipeline's folder, for as long as it is there as it was put; None for a dataframe put from no file of the folder.

    Asked, it gives the table to read (:class:`chartbook.rowhash.Table`)
    where the folder holds the files the dataframe was put from, no more
    and no fewer, each at the size and the time it had just before it was
    put. It gives None once any of that is no longer so (a build under
    way again while the snapshot is made), and whoever asks reads the
    store's copy.

    A look, and no proof: a file written again and put back at the size
    and the time it had passes it with other bytes. So it chooses where a
    line of output is read, and what is read there is remembered as the
    snapshot's by nobody (:func:`chartbook.standins.rows_compared`).

    :param put: Where its files are, how they are read, and each as it was
        (:func:`_as_they_are`), as :func:`_make` notes them.
    """
    if put is None or put[2] is None:
        return None
    path, reading, _ = put

    def table():
        from chartbook import rowhash

        if not _still_as_put(put):
            return None
        return rowhash.Table(path, (reading or {}).get("format"), (reading or {}).get("read_options"))

    return table


def _still_as_put(put: tuple) -> bool:
    """Whether the folder holds the files a dataframe was put from, no more and no fewer, each at the size and the time it had just before it was put.

    :param put: As :func:`_make` notes it: where its files are, how they
        are read, and each as it was (:func:`_as_they_are`), which is None
        where one could not be asked about, and then nothing is known.
    """
    path, _, as_put = put
    if as_put is None:
        return False
    found = hashing.find_files(path)
    return found is not None and _as_they_are(found.files) == as_put


def _rows_since(directory: Path, taken: Snapshot, store: Store, put_from: Optional[dict] = None) -> tuple:
    """The snapshot of this pipeline before one just made, and what each dataframe's rows are beside it: ``(snapshot, [(asset ID, what)])``.

    Only a dataframe whose file is another than the one before is told
    of: ``24 new rows, through 2026-11-11; earlier rows unchanged``, or
    ``earlier rows changed: …`` (:func:`chartbook.standins.since`). Telling
    it reads nothing where the two records already show every period to
    be the same. Otherwise the new table is read, every file of it, and
    its rows hashed in the periods still to be told, which for a table
    that gained rows is its last. Nothing here stops a snapshot: what
    cannot be told is left unsaid.

    **The table is read where it was put from, in the pipeline's folder,
    and not in the store,** where its files are still as they were put
    (:func:`_at_hand`). Its rows were hashed there a moment ago; the store
    may be a folder a sync service keeps, where reading the table back was
    more than a dozen questions of the disk for each of its files, and
    every byte of it. Where the folder has changed since, the store's
    copy is read, as it always was. What is read in the folder is said and
    is not remembered: only what the store's copy gave is taken later for
    what the snapshot's rows are. A table written out of a DuckDB file has
    no file in the folder, and is read in the store.

    :param put_from: The dataframes put from files of the folder, by name,
        each as :func:`_make` notes it.
    """
    from chartbook import standins

    try:
        earlier = [one for one in history(directory, store) if one.made_at < taken.made_at]
    except (SnapshotError, OSError):
        return None, []
    if not earlier:
        return None, []
    before = earlier[-1]
    told = []
    read = standins.reads_here(store)  # a line of output is not worth fetching a table for
    for name, record in sorted(taken.assets.items()):
        if (record.get("ref") or {}).get("kind") != "dataframe" or name not in before.assets:
            continue
        # A snapshot is made whatever becomes of what is said of it: since() raises nothing
        what = standins.since(before.assets[name], record, taken, store, read=read, at_hand=_at_hand((put_from or {}).get(name)))
        if what:
            told.append((record["id"], what))
    return (before, told) if told else (None, [])


def _not_hashed(taken: Snapshot) -> list:
    """The dataframes of a snapshot whose rows have no hash, each with why."""
    return [
        (record["id"], record["not_hashed"])
        for name, record in sorted(taken.assets.items()) if isinstance(record.get("not_hashed"), str)
    ]


def _rows_of(name: str, record: dict, path: Path, entry, reading: Optional[dict], earlier: list, put: Optional[tuple] = None) -> dict:
    """What a dataframe's record says of its rows: their hash by period, up to its last date (:mod:`chartbook.rowhash`).

    ``date_col``, ``as_of``, ``rows`` and ``row_count``; or ``not_hashed``,
    why its rows have no hash, with the ``date_col`` they would be dated
    by; or nothing, for a file that cannot be read as a table
    (``docs_src/design/pins-and-rebuilds.md``, "A dataframe's record").
    Hashing reads every row, so what an earlier snapshot of the same bytes
    said, read the same way and dated by the same column, is taken as it
    is: its rows, or why it has none. The column is the one that dates
    the rows now, which is the entry's ``date_col`` where the table has it
    and it holds dates: so an entry that declares one since, or another,
    is hashed again, and one that names a column of numbers is not hashed
    again at every snapshot.

    **The rows are hashed in the pipeline's folder, once its files are
    put, and are said only where the folder still holds those files.**
    *put* says each as it was just before it was put, and the folder is
    looked at again when the rows are hashed: the same files, no more and
    no fewer, each at that size and time, and the rows are those of the
    bytes the snapshot holds. A build that writes the table again while
    the snapshot is made gave the record the rows of a file it does not
    hold; now nothing is said of the rows this time, with why, and a
    snapshot of the same bytes made again says them. (Reading them from
    what the store was given instead is not built: before the record, the
    store has the files under other names, or in an earlier snapshot's
    folder that nothing has looked at.)

    :param record: Its record so far, with its ``content_hash``.
    :param path: Its file, glob or folder, on disk.
    :param entry: Its entry in the manifest, for its ``date_col``.
    :param reading: Its ``format`` and ``read_options``, if it has them.
    :param earlier: This pipeline's snapshots, oldest first.
    :param put: Its files as they were just before they were put
        (:func:`_make` notes them); None for a table put from no file of
        the folder, which is hashed without the look.
    :raises chartbook.rowhash.NotNow: If its rows could not be hashed this
        time, for no fault of the table's, or were hashed from a folder
        that no longer holds the files put.
    """
    from chartbook import rowhash

    if not record.get("content_hash"):
        return {}
    declared = entry.get("date_col") if isinstance(entry, dict) else None
    declared = declared if isinstance(declared, str) and declared else None
    reading = reading or {}
    table = rowhash.Table(path, reading.get("format"), reading.get("read_options"))
    try:
        dated = rowhash.dated_by(table, declared)
    except rowhash.NotRead:
        return {}
    except rowhash.NotHashed:
        dated = None  # a file not read at all, its footer too large: said below, with why
    except (OSError, MemoryError) as error:
        # A file that may not be opened now, no memory: this machine's, this time
        raise rowhash.NotNow(f"{type(error).__name__}: {rowhash._first_line(error)}") from None
    for taken in reversed(earlier):
        before = taken.assets.get(name) or {}
        if before.get("content_hash") != record["content_hash"] or before.get("location") != record.get("location"):
            continue
        said = {key: before[key] for key in rowhash.FIELDS if key in before}
        if ("rows" in said or "not_hashed" in said) and said.get("date_col") == dated:
            return said
    said = rowhash.fields_of(table, declared)
    if put is not None and not _still_as_put(put):
        raise rowhash.NotNow("its files in the pipeline's folder changed while the snapshot was made")
    return said


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


def _put_index(published: dict, pending: PendingSnapshot, staging: Optional[Path] = None) -> tuple[dict, Optional[dict]]:
    """Put an index in a snapshot being made, as ``_chartbook/index.json``; its record, and where it is kept.

    :param staging: Where the file is written first (:func:`_staged`).
    """
    from chartbook import index as index_module

    with _staged(staging, "index", pending, prefix="chartbook-index-") as scratch:
        path = Path(scratch) / INDEX_FILE
        index_module.write_index(published, path)
        stored = pending.put(path, place=f"{OWN_DIR}/{INDEX_FILE}", links=LINKS)
    return {"content_hash": stored.content_hash, "size_bytes": stored.size_bytes}, stored.stored


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


def _put_documents(
    directory: Path, paths: list[str], pending: PendingSnapshot, staging: Optional[Path] = None
) -> tuple[Optional[dict], Optional[dict]]:
    """Put a pipeline's documents in a snapshot being made, each at its own path; their record and where they are kept, or None if there are none.

    :param staging: Where they are copied first (:func:`_staged`).
    """
    if not paths:
        return None, None
    with _staged(staging, "documents", pending, prefix="chartbook-documents-") as scratch:
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
            return None, None
        for file in staged.rglob("*"):
            if file.is_symlink():  # never written above; checked all the same
                raise SnapshotError(f"A link appeared among the documents being stored: {file.relative_to(staged)}")
        stored = pending.put(staged, place="", links=LINKS)
    return {"content_hash": stored.content_hash, "size_bytes": stored.size_bytes, "files": list(stored.files)}, stored.stored


@dataclass
class Materialized:
    """What :func:`materialize` laid out.

    Attributes:
        folder: The folder the version was laid out in.
        documents: The documents written, by path in the folder.
        assets: The assets written, by reference.
        left_out: The assets and documents not written, each with why.
        from_index: The data assets not laid out on purpose (``data=False``),
            by reference: the site built there shows them from the
            snapshot's index.
    """

    folder: Path
    documents: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    left_out: list[tuple[str, str]] = field(default_factory=list)
    from_index: list[str] = field(default_factory=list)


#: The kinds of asset whose files are data, which a version rendered for a catalog does without.
DATA_KINDS = frozenset({"Dataframe", "File", "Model"})


def materialize(taken: Snapshot, into: Union[str, Path], store: Optional[Store] = None, data: bool = True) -> Materialized:
    """Lay a snapshot out as a folder: its documents and its assets at their paths, from the store alone.

    The folder is then the pipeline at that version, as far as a site is
    concerned: ``chartbook docs build`` builds the version's site there with the
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
    :param data: Whether to lay out the data too: dataframes, files assets
        and models (:data:`DATA_KINDS`), and tables written out as parquet.
        A version rendered for a catalog is laid out without (``False``):
        its site shows each from the snapshot's own index, which recorded
        their columns, rows, dates and glimpse when it had the files
        (``chartbook.index``), so no data is copied or read, and the data
        need not be in the store for the pages to be built. They are listed
        in :attr:`Materialized.from_index`.
    :raises StoreNotReadyError: If an object it names is not in the store,
        or not whole: a sync that has not finished, perhaps.
    :raises SnapshotError: If the snapshot carries no documents (it was made
        before snapshots did), or *into* is a file or has something in it.
    """
    import shutil

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
    named += [
        r["content_hash"] for r in taken.assets.values()
        if r.get("content_hash") and (r.get("location") or {}).get("kind") == "file" and (data or r.get("kind") not in DATA_KINDS)
    ]
    # The snapshot's own index: without its data laid out, a version's pages are built from it
    index_record = None
    if isinstance(taken.index, dict) and isinstance(taken.index.get("content_hash"), str):
        index_record = {**taken.index, "location": {"kind": "file", "path": INDEX_FILE}}
        named.append(taken.index["content_hash"])
    try:
        missing = [h for h in named if not isinstance(h, str) or not store.has(h, taken.pipeline)]
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
    for record in [taken.documents, *taken.assets.values(), *([index_record] if index_record else [])]:
        declared = (record.get("location") or {}).get("path")
        if record is not taken.documents and record is not index_record and safe_relative(declared) is None:
            continue  # not laid out at all, and said so below
        if record.get("content_hash") in named:
            unsynced = not_whole(store, record, taken.pipeline)
            if unsynced:
                raise StoreNotReadyError(
                    f"The snapshot of {taken.pipeline} at {taken.commit[:7]} names {record['content_hash']}, "
                    f"and {unsynced}."
                )
    folder.mkdir(parents=True, exist_ok=True)
    report = Materialized(folder.resolve())

    # The version file first, so that nothing a record names can take its place
    marker = {"pipeline": taken.pipeline, "commit": taken.commit, "made_at": taken.made_at, "repository": taken.repository}
    if taken.subdirectory:
        marker["subdirectory"] = taken.subdirectory
    code_changed_at = _code_changed_at(taken, store)
    if code_changed_at:
        marker["code_changed_at"] = code_changed_at
    (folder / VERSION_FILE).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8", newline="\n")

    # Each document where the store keeps it; a file that is a link, or under one, the store never hands out
    kept = store.files(taken.documents["content_hash"], taken.pipeline, snapshot=(taken.commit, taken.made_at)).by_relative()
    for relative in taken.documents.get("files", []):
        plain = plain_name(relative) if isinstance(relative, str) else None
        if plain is None or plain.split("/")[0] == VERSION_FILE:
            report.left_out.append((str(relative), NOT_A_PLAIN_PATH))
            continue
        source = kept.get(plain)
        if source is None or os.path.lexists(folder / plain) or not _copy_regular_file(source, folder / plain):
            report.left_out.append((plain, NOT_A_FILE))
            continue
        report.documents.append(plain)

    for name in sorted(taken.assets):
        record = taken.assets[name]
        if not data and record.get("kind") in DATA_KINDS:
            if (record.get("location") or {}).get("kind") == "file":
                report.from_index.append(record["id"])
            continue  # shown from the index; a table or query is dealt with below
        why = _place_asset(record, store, folder, taken)
        if why is not None:
            report.left_out.append((record["id"], why))
            continue
        report.assets.append(record["id"])

    # Materialized tables are file inputs to the version renderer; no database
    # or warehouse connection is opened while rendering a published snapshot.
    manifest_path = folder / "chartbook.toml"
    raw = _read_manifest_file(folder) if manifest_path.is_file() else {}
    changed = False
    for record in taken.assets.values():
        if record.get("kind") != "Dataframe" or (record.get("location") or {}).get("kind") not in ("table", "query") or not record.get("content_hash"):
            continue
        name = record.get("ref", {}).get("name")
        if not isinstance(name, str) or plain_name(materialized_name(record)) is None:
            continue
        relative = f"_chartbook/tables/{materialized_name(record)}"
        if data:
            written = store.files(record["content_hash"], taken.pipeline, name=materialized_name(record), snapshot=(taken.commit, taken.made_at)).one.location
            if not _copy_regular_file(written, folder / relative):
                continue
        # The manifest names the database; here the table is a parquet file (laid out, or shown from the index)
        dataframes_table = raw.get("dataframes")
        entry = dataframes_table.get(name) if isinstance(dataframes_table, dict) else None
        if isinstance(entry, dict):
            for key in ("source", "table", "query", "format", "read_options"):
                entry.pop(key, None)
            entry["path"] = relative
            entry["format"] = "parquet"
            changed = True
            if data:
                report.assets.append(record["id"])
                report.left_out = [(key, why) for key, why in report.left_out if key != record["id"]]
            else:
                report.from_index.append(record["id"])
    if changed:
        import tomli_w
        manifest_path.write_text(tomli_w.dumps(raw), encoding="utf-8", newline="\n")
    if index_record is not None:
        try:
            held = store.files(taken.index["content_hash"], taken.pipeline, name=INDEX_FILE, snapshot=(taken.commit, taken.made_at)).one.location
            copied = _copy_regular_file(held, folder / "_chartbook" / INDEX_FILE)
        except StoreError as error:
            copied, error_said = False, str(error)
        else:
            error_said = "it is not a regular file, or could not be read"
        if not copied:
            # Tried again next time (a sync not finished): a version with no index would show no data at all
            raise StoreNotReadyError(
                f"The snapshot of {taken.pipeline} at {taken.commit[:7]} names its index {taken.index['content_hash']}, "
                f"and the store {store} does not give it: {error_said.rstrip('.')}."
            )
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


def _place_asset(record: dict, store: Store, folder: Path, of: Snapshot, at: Optional[str] = None) -> Optional[str]:
    """Copy one asset's bytes from the store to its path under *folder*; why it was not, if it was not: the copy in the snapshot *of* which it is, or in the newest of its pipeline that holds it whole.

    The path is the record's, or *at*, the path the manifest declares now,
    for :func:`restore`; either is judged as a record's is
    (:func:`safe_relative`), and nothing on disk is written over: a file
    that is there stays, and a folder's files that are there stay.
    """
    from chartbook.hashing import glob_root
    from chartbook.identity import VERSION_FILE

    location = record.get("location") or {}
    if not record.get("content_hash"):
        return "not built when the snapshot was made"
    if location.get("kind") != "file":
        return "a table or a query: in the store as parquet, and the manifest names its database"
    declared = location.get("path", "") if at is None else at
    plain = safe_relative(declared)
    if plain is None or plain.split("/")[0] == VERSION_FILE:
        return f"its path {declared} is not a plain path inside the pipeline's folder"
    then = safe_relative(location.get("path", "")) if at is not None else plain
    if then != plain and (record.get("files") or is_glob_pattern(plain) or is_glob_pattern(then or "")):
        # A folder or a glob laid out under a new name may not be what the
        # new path means (a folder written where a file is now expected)
        return (
            f"its path is {declared} now and was {location.get('path')} when the snapshot was made, and the "
            f"snapshot holds a folder: put it back by hand"
        )
    single = not is_glob_pattern(plain) and not record.get("files")
    try:
        kept = store.files(
            record["content_hash"], of.pipeline, name=Path(plain).name if single else None, snapshot=(of.commit, of.made_at),
        )
    except StoreError as error:
        # A file of it is a link, or not synced yet: the rest of the version is laid out
        return f"the store does not give it: {str(error).rstrip('.')}"
    if is_glob_pattern(plain):
        _copy_kept(kept, folder / glob_root(plain))
    elif record.get("files") or not kept.single:
        _copy_kept(kept, folder / plain)
    else:
        if not kept.files:
            return "its object holds no file"
        # The same bytes may be held under several names: the one asked for by its name, else the first
        target = folder / plain
        if os.path.lexists(target) or not _copy_regular_file(kept.files[0].location, target):
            return "its file could not be written where its path says"
    return None


def newest_holder(snapshots: list, store: Store, name: str) -> tuple[Optional[Snapshot], str]:
    """The newest snapshot holding an asset built, with its bytes in the store and whole; or why there is none.

    Walked newest first and stopped at the first that holds the asset: an
    older version is never handed over in place of a newer one whose bytes
    are missing, which would be stale data with nothing said. Shared by
    :func:`restore` and the stop before a build
    (:func:`chartbook.run.kept_missing`), so that the two agree. A record
    from a store others can write to may name an object that is not one;
    that is said, not raised.

    :param snapshots: The pipeline's snapshots, oldest first (:func:`history`).
    :returns: The snapshot and ``""``, or None and the reason.
    """
    for taken in reversed(snapshots):
        record = taken.assets.get(name) or {}
        content_hash = record.get("content_hash")
        if not content_hash:
            continue
        where = f"the newest snapshot holding it, at {taken.commit[:7]},"
        try:
            if not store.has(content_hash, taken.pipeline):
                return None, f"{where} names bytes the store does not have"
            unsynced = not_whole(store, record, taken.pipeline)
        except (ValueError, TypeError) as error:  # not a hash: a record written to mislead
            return None, f"{where} names an object that is not one: {error}"
        if unsynced:
            return None, f"{where} names an object that {unsynced}"
        return taken, ""
    return None, "no snapshot of this pipeline holds it"


@dataclass
class Restored:
    """What :func:`restore` did.

    Attributes:
        put_back: Each asset put back: its reference within the pipeline,
            the path it was written at as the manifest declares it, the
            snapshot it came from, and its size in bytes.
        left: Each asset asked for and not put back, with why: it is on
            disk already, no snapshot of the pipeline holds it, the store
            does not have its bytes, it is a table or a query, or the
            manifest does not declare it.
    """

    put_back: list[tuple[str, str, Snapshot, int]] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)


def restore(
    project_dir: Union[str, Path] = ".", names: Optional[list] = None, store: Optional[Store] = None
) -> Restored:
    """Put a pipeline's own assets back on disk from its snapshots: `chartbook restore`.

    With no *names*, every asset the manifest marks ``keep = true``
    (:func:`keeps_of`) that is not on disk; a kept table or query, which
    has no file, is passed over. With *names*, those assets, marked or
    not: any asset a snapshot holds can be put back. Each comes from the
    newest snapshot of this pipeline that holds it built, with its bytes
    in the store and whole (:func:`newest_holder`), and is written at the
    path the manifest declares now. Nothing on disk is written over: an
    asset that is there is left, and said. The mirror of :func:`make`,
    which copies the folder into the store (``docs_src/design/keep.md``).
    The snapshots are found through the commits the clone has
    (:func:`history`): a shallow clone sees only its own.

    :param names: References within the pipeline, as `chartbook path` takes
        them: ``embeddings``, ``model/forecaster``.
    :raises SnapshotError: If the folder holds no pipeline, or is not in git
        (its snapshots are found through its repository's commits).
    :raises ValueError: If a name is not a reference.
    """
    from chartbook.resolve import declared_in_source, parse_declared_ref

    directory = Path(project_dir).resolve()
    pipeline = pipeline_in(directory)
    store = store if store is not None else default_store()
    raw = _read_manifest_file(directory)
    declared = {str(local): (path, absolute) for local, path, absolute in declared_files(directory)}
    in_source = {str(local) for local, _ in declared_in_source(directory)}
    report = Restored()
    if names is None:
        wanted = sorted(keeps_of(raw))
    else:
        wanted = []
        for name in names:
            ref = parse_declared_ref(name)
            if not ref.is_local:
                raise ValueError(
                    f"{name} names another pipeline's asset. `chartbook restore` puts this pipeline's own "
                    f"assets back; another pipeline's are read where they are pinned."
                )
            wanted.append(str(ref))
    snapshots = None  # read once, when an asset needs one
    for name in wanted:
        if name in in_source:
            if names is not None:
                report.left.append((name, "a table or a query in a source: it has no file to put back"))
            continue  # nothing of it is on disk to be missing
        if name not in declared:
            report.left.append((name, f"not declared with a path in {MANIFEST_NAME}"))
            continue
        path, absolute = declared[name]
        found = hashing.find_files(absolute)
        if found is not None and found.files:
            if names is None:
                continue  # a kept asset that is on disk needs nothing
            report.left.append((name, f"on disk at {path}; nothing is written over"))
            continue
        if snapshots is None:
            snapshots = history(directory, store)
        holder, why = newest_holder(snapshots, store, name)
        if holder is None:
            report.left.append((name, why))
            continue
        record = holder.assets[name]
        placed = _place_asset(record, store, directory, holder, at=path)
        if placed is not None:
            report.left.append((name, placed))
            continue
        size = record.get("size_bytes")
        report.put_back.append((name, path, holder, size if type(size) is int else 0))
    return report


def _write_back(taken: Snapshot, folder: Path, report: Materialized) -> None:
    """What a build writes, git does not keep and the snapshot recorded: scores, and an empty site folder."""
    from chartbook.identity import VERSION_FILE

    try:
        raw = _read_manifest_file(folder) if (folder / MANIFEST_NAME).is_file() else {}
    except (OSError, ValueError):
        return  # the docs build says what is wrong with a manifest
    models_table = raw.get("models")
    for name, entry in (models_table if isinstance(models_table, dict) else {}).items():
        record = taken.assets.get(f"model/{name}") or {}
        plain = safe_relative(entry.get("metrics_path")) if isinstance(entry, dict) else None
        if plain is None or plain.split("/")[0] == VERSION_FILE:
            continue
        if not isinstance(record.get("metrics"), dict) or os.path.lexists(folder / plain):
            continue
        try:
            target = folder / plain
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(record["metrics"], indent=2) + "\n", encoding="utf-8", newline="\n")
        except OSError:
            report.left_out.append((f"model/{name}", f"its scores could not be written to {plain}"))
    project_table = raw.get("project")
    site_dir = safe_relative((project_table if isinstance(project_table, dict) else {}).get("site_dir"))
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
        held = store.files(taken.index["content_hash"], taken.pipeline, name=INDEX_FILE, snapshot=(taken.commit, taken.made_at)).one.location
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
_ASSET_KINDS = {
    "Dataframe": "dataframe", "Chart": "chart", "Model": "model", "Notebook": "notebook", "Note": "note", "File": "file"
}


def stored_assets(taken: Snapshot, store: Store) -> list[dict]:
    """The assets the index a snapshot holds lists, each as ``{"kind", "id", "name", "description"}``, by ID; empty when it has none.

    For a pipeline known from the store alone, whose folder is not here to
    say what it declares. Only a record whose ID reads as a reference to
    an asset of the snapshot's own pipeline, of the kind the record says,
    is listed; its name is one line of plain text
    (:func:`chartbook.identity.plain_line`), empty when it has none, and
    so is its description.
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
        listed.setdefault(str(ref), {
            "kind": record["kind"], "id": str(ref), "name": plain_line(record.get("name"), 200),
            "description": plain_line(record.get("description"), 2000),
        })
    return [listed[asset_id] for asset_id in sorted(listed)]


def _code_changed_at(taken: Snapshot, store: Store) -> Optional[str]:
    """When the version's code last changed, as its index recorded it; None if it has none."""
    changed = stored_pipeline_record(taken, store).get("code_changed_at")
    return changed if isinstance(changed, str) else None


def _copy_kept(kept, target: Path) -> None:
    """Copy an asset's files from where the store keeps them to a folder, under their paths inside the asset, writable; nothing on disk is written over."""
    for file in kept.files:
        parts = plain_parts(file.relative)
        if parts is None:
            continue
        destination = target.joinpath(*parts)
        if not os.path.lexists(destination):
            _copy_regular_file(file.location, destination)
