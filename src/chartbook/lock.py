"""The lockfile: ``chartbook.lock``, the exact bytes a pipeline depends on.

A pipeline declares which pipelines it reads from in ``[dependencies]``.
*Pinning* freezes what it reads: the content hash of every asset each of
those pipelines declares is written to ``chartbook.lock`` beside the
manifest, and the bytes are in the store (:mod:`chartbook.store`). The
lockfile is source. Commit it: a change to what a project depends on then
shows up in a diff, and someone who clones the project can see exactly
which data it was built against.

**Where the bytes come from.** Never from another pipeline's working
directory, which may be in any state. A ``path`` dependency is pinned from
a **snapshot**: what its owner declared ready, at a commit
(:mod:`chartbook.snapshot`). A ``git`` dependency is pinned from
ChartBook's own clean copy of a commit. The lockfile records the commit
either way.

::

    from chartbook import lock

    report = lock.pin("path/to/pipeline")       # pin what has no pin yet
    report = lock.update("path/to/pipeline")    # move every pin forward

``pin`` never moves a pin that exists. It pins a dependency that has no
pin yet. ``update`` is the one thing that moves a pin: to the dependency's
newest snapshot, or to what its ``rev`` means now.

The file is JSON in the index's own format: the same envelope, and records
with the same field names (``docs_src/design/index-schema.md``). It holds
this pipeline's ``Pipeline`` record, cut down to its ``dependencies``, and
one record for each asset of each dependency that code reads, cut down to
its ``id``, its declared ``path`` and its ``content_hash``. There is no
timestamp, no ChartBook version and no absolute path in it, so pinning
twice with nothing changed writes the same bytes.

**What is in it, by kind** (:func:`in_lockfile`;
``docs_src/design/pins-and-rebuilds.md``). A dataframe and a model always.
A chart, a notebook, a note or a plain file only when its owner's manifest
says ``lock = true``: each is drawn from the data, and drawn anew by every
build, so no rebuild gives its bytes again. An asset that is not in the
lockfile is still read from the snapshot the lockfile names
(:func:`chartbook.resolve.resolve`).

An asset the other pipeline declares and has not built is recorded without
a ``content_hash``. It is not pinned, and asking for it will fail.

A dependency that is a git repository is fetched first
(:mod:`chartbook.gitcache`) and pinned from its checkout. The lockfile
records the commit, ``pin`` stays at it, and ``update`` asks the repository
what the ``rev`` means now. Such a dependency has only what its repository
commits, so data it builds and git-ignores is "not built" here.

A pin is stored as a copy-on-write clone, or as a copy where the disk has
no clones (:data:`PIN_LINKS`), and never as a link to the other pipeline's
own file, so it cannot change when that file is rewritten.

A reference to another pipeline's asset, ``data.path("rates:treasury")``,
resolves through the lockfile to the pinned copy
(:func:`chartbook.resolve.resolve`). The design is "Pinning and isolation"
in ``docs_src/design/asset-graph.md``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import errno
import json
import os
import uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from chartbook import formats, hashing, snapshot
from chartbook.gitcache import GIT as _GIT
from chartbook.gitcache import GIT_LOCATION_VARIABLES as _GIT_LOCATION_VARIABLES
from chartbook.gitcache import GitCache, GitError, check_git_url, default_git_cache, local_url
from chartbook.identity import (
    derive_pipeline_id,
    get_git_remote_url,
    id_from_address,
    in_another_case,
    repository_key,
    strip_url_credentials,
    validate_pipeline_id,
)
from chartbook.index import RECORD_VERSION, SCHEMAS_DIR
from chartbook.manifest import (
    _read_manifest_file,
    admits_before,
    later_form_said,
    raised_to,
    resolve_project_type,
    validate_dependencies,
    with_requires_chartbook,
)
from chartbook.refs import KIND_TABLES, AssetRef
from chartbook.replacing import replace_when_let
from chartbook.resolve import MANIFEST_NAME, _same_directory, declared_files, locate_pipeline
from chartbook.snapshot import asset_record as _asset_record
from chartbook.store import LINKS as STORE_LINKS
from chartbook.store import (
    ObjectNotFoundError, ReadOnlyStoreError, Store, StoredObject, StoreError, TidyError, default_store, increment_note,
)

#: The lockfile's name, beside ``chartbook.toml``.
LOCK_FILE = "chartbook.lock"

#: The version of the lockfile's envelope. Version 2 holds a record only
#: for an asset that :func:`in_lockfile` says is pinned.
SCHEMA = "chartbook/lock/v2"

#: The versions of a lockfile this version reads. One of version 1 held a
#: record for every asset of every dependency: it is read as version 2
#: would have it, and written again as version 2 by the next command that
#: writes the lockfile.
READS = ("chartbook/lock/v1", SCHEMA)

#: The first ChartBook that reads a lockfile of this version (:data:`SCHEMA`).
#: One before it stops at such a lockfile and says only which version it
#: reads; told by the manifest's ``requires_chartbook`` that it is too old,
#: it says how to upgrade. So a manifest that says which ChartBook it needs
#: is kept to this one or later (:func:`see_to_the_floor`).
SINCE = "0.6.0"

#: The kinds of asset a lockfile holds whatever their owner says: what code
#: reads. Any other kind is in it only when its entry in its owner's
#: manifest says ``lock = true``.
LOCKED_KINDS = frozenset({"dataframe", "model"})

#: The kinds of link a pin may be stored with: a copy-on-write clone, or a
#: copy. Decided by the maintainer: a pin must not change when the other
#: pipeline rewrites its file, so it is never a hard link or a symlink,
#: which are that file. On a disk with no clones a pin costs the file's size.
#: A snapshot's files are stored the same way.
PIN_LINKS = snapshot.LINKS

#: An unreferenced object stored more recently than this is not removed by
#: :func:`plan_gc`. Someone may be in the middle of pinning it: it is in
#: the store before the lockfile that names it is written.
RECENT_SECONDS = 3600


def schema_path() -> Path:
    """The JSON Schema file for the lockfile's envelope.

    An asset record in a lockfile fits the index's schema for its kind
    (:func:`chartbook.index.schema_path`), with fields left out.
    """
    return SCHEMAS_DIR / "lock" / "v2.json"


class LockError(Exception):
    """Raised when a lockfile cannot be read, or a project cannot be pinned."""


def in_lockfile(record: dict) -> bool:
    """Whether a lockfile holds an asset's record.

    The lockfile is about what code reads: a dataframe and a model are
    always in it. A chart, a notebook, a note or a plain file is drawn from
    the data, and drawn anew by every build (a Plotly chart has a random id
    in its page, an executed notebook the time of each cell), so it is in
    it only when its owner's manifest says ``lock = true``, which a
    snapshot's record carries. Decided by the maintainer on 2026-11-15
    (``docs_src/design/pins-and-rebuilds.md``): there is no setting for a
    whole kind.

    This is the rule for a dependency pinned from a snapshot, which each
    person may have to build again. One pinned from its repository
    (``git``) is pinned whole, as it always was: its bytes are its
    commit's, the same for everyone, and nothing but the lockfile names
    them.

    :param record: An asset's record, as a snapshot or a lockfile has it.
    """
    ref = record.get("ref")
    kind = ref.get("kind") if isinstance(ref, dict) else None
    return kind in LOCKED_KINDS or record.get("lock") is True


def pinned_pipeline(entry: Optional[dict], folder: Optional[Union[str, Path]] = None) -> Optional[str]:
    """The pipeline a dependency's pins came from, by its own ID.

    As its entry in the lockfile says it. An entry written before 0.3.0
    does not say. With *folder*, for a dependency named by its folder, it
    is then guessed: the pipeline that folder holds now, where the folder
    is on this machine. The guess is for finding which snapshots a pin is
    read from (:func:`read_from`) and nothing else: the folder's ID may
    have changed since the pin. Every question asked by a hash (is it in
    the store, where, is it whole) is asked with no *folder*, so that an
    entry that names no pipeline is asked of the whole store, by a read
    and by ``pin --check`` alike.

    :param folder: The folder of a ``path`` dependency, as the manifest resolves it.
    """
    if not isinstance(entry, dict):
        return None
    location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    found = entry.get("pinned_from") or location.get("pipeline")
    if isinstance(found, str) and found:
        return found
    if folder is not None and location.get("kind") == "path":
        try:
            return snapshot.pipeline_in(folder)
        except (snapshot.SnapshotError, OSError, ValueError):
            return None
    return None


def read_from(entry: Optional[dict], snapshots: list, folder: Optional[Union[str, Path]] = None) -> list:
    """The snapshots an asset that a lockfile does not hold is read from, for one dependency, in the order they are tried.

    The snapshot its entry names, alone, where the store has it: a
    snapshot is taken whole, and that one is the pin. Where the store does
    not have it, your own builds of that pipeline at that commit, newest
    first (:func:`chartbook.snapshot.builds_at`). One rule, for a read
    (:func:`chartbook.resolve.resolve`), for the checks that say whether a
    read will work, for what ``store gc`` keeps, and for which records of
    an earlier lockfile stay in it.

    :param snapshots: The store's snapshots that owners made.
    """
    location = entry.get("location") if isinstance(entry, dict) and isinstance(entry.get("location"), dict) else {}
    named = (entry or {}).get("snapshot")
    found = snapshot.builds_at(snapshots, pinned_pipeline(entry, folder), location.get("commit"), named)
    exact = [taken for taken in found if isinstance(named, str) and taken.same_moment(location.get("commit"), named)]
    return exact or found


def has_named(entry: Optional[dict], snapshots: list, folder: Optional[Union[str, Path]] = None) -> bool:
    """Whether the store has the snapshot a dependency's entry names, by its commit and its time.

    Where it has, that snapshot is the pin: what the store lacks of it is
    lost, or not synced yet, and no other build of that commit is read in
    its place (:mod:`chartbook.standins`).
    """
    if not names_a_snapshot(entry):
        return False
    commit, named = entry["location"]["commit"], entry["snapshot"]
    return any(taken.same_moment(commit, named) for taken in read_from(entry, snapshots, folder))


def from_a_snapshot(entry: Optional[dict]) -> bool:
    """Whether a dependency is pinned from a snapshot (its entry's ``location.kind`` is ``store`` or ``path``), which each person may have to build again; and not from its repository, which is pinned whole."""
    location = entry.get("location") if isinstance(entry, dict) else None
    return isinstance(location, dict) and location.get("kind") in ("store", "path")


def names_a_snapshot(entry: Optional[dict]) -> bool:
    """Whether a lockfile's entry for a dependency names the snapshot it was pinned from, by its commit and its time.

    That is the pin of a dependency none of whose assets is in the lockfile
    (one that makes only charts, say): its entry is all the lockfile has of
    it, and what is read of it is read from that snapshot.
    """
    if not isinstance(entry, dict) or not isinstance(entry.get("location"), dict):
        return False
    location = entry["location"]
    return (
        location.get("kind") in ("store", "path")
        and isinstance(location.get("commit"), str) and bool(location["commit"])
        and isinstance(entry.get("snapshot"), str) and bool(entry["snapshot"])
    )


@dataclass
class Lock:
    """What a lockfile holds.

    Attributes:
        root: The ID of the pipeline the lockfile belongs to.
        dependencies: Its dependencies, as its ``Pipeline`` record lists
            them: ``id``, ``via``, ``location``, and ``pinned_hash`` when
            something of it is pinned. ``pinned_from`` is the pipeline the
            pins came from by its own ID, whatever the key: the snapshot's,
            or the one a ``git`` dependency's clone holds. A pin made before
            0.3.0 has none until it is made again or moved.
        assets: One record for each asset of each dependency that a
            lockfile holds (:func:`in_lockfile`), by asset ID. A record
            with a ``content_hash`` is a pin.
        read_as: The version of the file this was read from
            (:data:`READS`); :data:`SCHEMA` for one made here.
        left_out: For a file of an earlier version: how many records it
            held that this version does not (its charts, notebooks, notes
            and plain files), by the plural of their kind.
        earlier: Those records, by asset ID. They are no pins. What they
            name is not let go, though: while the file is still of the
            earlier version a read falls back on one where the store does
            not have the snapshot its dependency names, and ``store gc``
            keeps its bytes; and when the file is written again, one whose
            bytes the store has and that snapshot would not give stays in
            it, a pin as it was (:func:`still_pinned`). A file of this
            version has none.
    """

    root: str
    dependencies: list[dict] = field(default_factory=list)
    assets: dict[str, dict] = field(default_factory=dict)
    read_as: str = field(default=SCHEMA, compare=False)
    left_out: dict = field(default_factory=dict, compare=False)
    earlier: dict = field(default_factory=dict, compare=False)

    def hashes(self) -> set[str]:
        """The content hash of every pinned asset, and of what a file of an earlier version still names: what the store must keep."""
        return {
            record["content_hash"]
            for record in (*self.assets.values(), *self.earlier.values())
            if record.get("content_hash")
        }

    def snapshots(self) -> set[tuple[str, str, str]]:
        """The snapshots it pins, each ``(pipeline, commit, made_at)``: what a note of it records for ``store gc``.

        The pipeline is the dependency's ID. Only a full commit names one: a
        commit cut short or in capitals (a lockfile edited by hand) names no
        snapshot a store keeps.
        """
        from chartbook.store import _FULL_COMMIT

        return {
            (entry["id"], entry["location"]["commit"], entry["snapshot"])
            for entry in self.dependencies
            if isinstance(entry.get("id"), str)
            and isinstance(entry.get("location"), dict)
            and isinstance(entry["location"].get("commit"), str)
            and _FULL_COMMIT.match(entry["location"]["commit"])
            and isinstance(entry.get("snapshot"), str)
        }

    def labelled(self) -> set[tuple[str, str, str, str]]:
        """The model versions it pins by label, each ``(commit, made_at, name, content_hash)``: what a note of it records for ``store gc``.

        A label (``rates:model/m@champion``) resolves to a version that an
        older snapshot of the pipeline may hold, not the one the dependency
        is pinned to by its moment, so ``gc`` keeps a snapshot holding each
        (:func:`chartbook.snapshot.plan_removals`). The moment is the
        dependency's, so that the version is looked for among that
        pipeline's snapshots; empty for a pin that names no snapshot.
        """
        from chartbook.store import _FULL_COMMIT

        moments = {
            entry["id"]: (entry["location"]["commit"], entry["snapshot"])
            for entry in self.dependencies
            if isinstance(entry.get("id"), str)
            and isinstance(entry.get("location"), dict)
            and isinstance(entry["location"].get("commit"), str)
            and _FULL_COMMIT.match(entry["location"]["commit"])
            and isinstance(entry.get("snapshot"), str)
        }
        found = set()
        for record in self.assets.values():
            if not record.get("content_hash") or not (record.get("ref") or {}).get("rev"):
                continue
            try:
                name = snapshot.local_name(record)
            except (KeyError, TypeError, ValueError):
                continue
            commit, made_at = moments.get(record.get("pipeline"), ("", ""))
            found.add((commit, made_at, name, record["content_hash"]))
        return found

    def assets_of(self, dependency: str) -> dict[str, dict]:
        """The records of one dependency's assets, by asset ID."""
        return {
            asset_id: record
            for asset_id, record in self.assets.items()
            if record.get("pipeline") == dependency
        }

    def earlier_of(self, dependency: str) -> dict[str, dict]:
        """The records a file of an earlier version held of one dependency that this version does not, by asset ID."""
        return {
            asset_id: record
            for asset_id, record in self.earlier.items()
            if record.get("pipeline") == dependency
        }

    def to_document(self) -> dict:
        """The lockfile as it is written: an envelope and a list of records."""
        pipeline = {
            "kind": "Pipeline",
            "version": RECORD_VERSION,
            "id": self.root,
            "dependencies": sorted(self.dependencies, key=lambda entry: entry["id"]),
        }
        return {
            "schema": SCHEMA,
            "root": self.root,
            "records": [pipeline, *(self.assets[key] for key in sorted(self.assets))],
        }


def _a_local_lockfile(path: Union[str, Path]) -> bool:
    """Whether a path a store names is one to read as a lockfile: absolute, named ``chartbook.lock``, on this machine.

    Not a network path (``\\\\host\\share`` or ``//host/share``), which
    reading would make this machine connect to. A lockfile in a project on
    a network drive is therefore not read by gc; its note's pins are kept.
    (A path an automounter serves, such as Linux's ``/net/<host>``, is not
    told apart.)
    """
    from pathlib import PureWindowsPath

    text = str(path)
    if text.startswith(("\\\\", "//")) or PureWindowsPath(text).drive.startswith("\\\\"):
        return False
    path = Path(text)
    return path.is_absolute() and path.name == LOCK_FILE


def read_lock(path: Union[str, Path]) -> Optional[Lock]:
    """Read a lockfile.

    One of an earlier version (:data:`READS`) is read as this version
    would have written it: the records it held of the charts, notebooks,
    notes and plain files of a dependency pinned from a snapshot are left
    out (:func:`in_lockfile`), counted in ``left_out`` and kept in
    ``earlier``, and each dependency's ``pinned_hash`` is the hash over
    what is left. Nothing is written here; the next command that writes
    the lockfile writes it in this version, and says so.

    :param path: A ``chartbook.lock``, or the directory holding one.
    :returns: What it holds, or None if there is no such file.
    :raises LockError: If the file is not a lockfile this version reads.
    """
    path = Path(path)
    if path.is_dir():
        path = path / LOCK_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError) as error:
        raise LockError(f"Cannot read {path}: {error}") from None
    return _lock_from_document(document, str(path))


def _lock_from_document(document: dict, where: str) -> Lock:
    """A :class:`Lock` from a lockfile's JSON, as :func:`read_lock` builds it.

    :param where: Named in the error when the document is not a lockfile
        this version reads (a path, or ``git show``).
    """
    try:
        if document.get("schema") not in READS:
            raise ValueError(
                f"its schema is {document.get('schema')!r}, and this version of "
                f"ChartBook reads {SCHEMA!r}{later_form_said(document.get('schema'), SCHEMA)}"
            )
        lock = Lock(root=document["root"], read_as=document["schema"])
        earlier = document["schema"] != SCHEMA
        for record in document["records"]:
            if record.get("kind") == "Pipeline":
                lock.dependencies = list(record.get("dependencies", []))
                for entry in lock.dependencies:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                        raise ValueError(
                            "it lists a dependency without an id that is a name. The file is not one "
                            "ChartBook wrote: restore it from git, or remove it and run `chartbook pin`"
                        )
                    if "location" in entry and not isinstance(entry["location"], dict):
                        raise ValueError(
                            "it lists a dependency with a location that is not an object. The file is not one "
                            "ChartBook wrote: restore it from git, or remove it and run `chartbook pin`"
                        )
        # Pinned from a snapshot, which each person may build again; one from its repository is pinned whole
        from_snapshots = {
            entry["id"] for entry in lock.dependencies
            if isinstance(entry.get("location"), dict) and entry["location"].get("kind") in ("store", "path")
        }
        for record in document["records"]:
            if record.get("kind") != "Pipeline" and "id" in record:
                ref = record.get("ref")
                kind = ref.get("kind") if isinstance(ref, dict) else None
                if earlier and kind in KIND_TABLES and not in_lockfile(record) and record.get("pipeline") in from_snapshots:
                    # A chart, a notebook, a note or a file: no pin in this version
                    lock.left_out[KIND_TABLES[kind]] = lock.left_out.get(KIND_TABLES[kind], 0) + 1
                    lock.earlier[record["id"]] = record
                    continue
                lock.assets[record["id"]] = record
        if lock.left_out:
            # One hash over what is pinned of each dependency, as this version makes it
            for position, entry in enumerate(lock.dependencies):
                entry = {k: v for k, v in entry.items() if k != "pinned_hash"}
                overall = pinned_hash(lock.assets_of(entry["id"]).values())
                if overall is not None:
                    entry["pinned_hash"] = overall
                lock.dependencies[position] = entry
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
        raise LockError(f"Cannot read {where}: {error}") from None
    return lock


def holds_a_pin(entry: Optional[dict], records: dict) -> bool:
    """Whether a lockfile pins something of a dependency, so that ``pin`` leaves it where it is.

    Bytes of it: a record with a content hash. Or the snapshot its entry
    names (:func:`names_a_snapshot`): a snapshot is taken whole, so that is
    a pin whatever of it the lockfile holds, and all there is of one whose
    assets are all outside it (one that makes only charts).

    :param records: The lockfile's records of it, those a file of an
        earlier version held among them (:meth:`Lock.earlier_of`).
    """
    return (
        any(isinstance(record, dict) and record.get("content_hash") for record in records.values())
        or names_a_snapshot(entry)
    )


def still_pinned(
    earlier: dict, entry: Optional[dict], store: Store, snapshots: Callable[[], list],
    folder: Optional[Union[str, Path]] = None,
) -> dict:
    """The records an earlier lockfile held of a dependency that stay in it when it is written again, by asset ID.

    This version does not pin a chart, a notebook, a note or a plain file:
    it is read from the snapshot the dependency's entry names, or from
    your own build of that commit (:func:`chartbook.snapshot.builds_at`).
    So an earlier record of one is let go wherever such a snapshot in the
    store holds the asset, and wherever the store does not have the
    record's bytes, there being nothing to keep. That is every lockfile a
    team shares through a store, and every one whose reader builds the
    other pipeline themselves, so the file comes out the same on each of
    their machines.

    Where the store has the bytes and no snapshot to read the asset from
    (a pin made before pins named snapshots, or one whose snapshot's
    record is gone from the store), the record is all that is left to
    read it by: it stays, a pin as it was, so that the asset is still read
    and ``store gc`` keeps it.

    A record that stays has no ``lock = true`` of its owner's, and is a
    pin only where the store has its bytes: on a machine that does not,
    the asset is read as any that the lockfile does not hold, from a build
    of that commit, and the check passes over the record
    (:func:`in_lockfile`). So writing a lockfile again takes no read away,
    on the machine that writes it or on another.

    :param earlier: The earlier records of the dependency (:meth:`Lock.earlier_of`).
    :param entry: Its entry in the lockfile.
    :param snapshots: Gives the store's snapshots; asked only if needed.
    :param folder: The folder of a ``path`` dependency (:func:`pinned_pipeline`).
    """
    kept: dict = {}
    builds = None
    for asset_id, record in sorted(earlier.items()):
        content_hash = record.get("content_hash")
        try:
            if not content_hash or not store.has(content_hash, pinned_pipeline(entry)):
                continue
            if builds is None:
                builds = read_from(entry, snapshots(), folder)
            name = snapshot.local_name(record)
            read = any(
                (taken.assets.get(name) or {}).get("content_hash") and store.has(taken.assets[name]["content_hash"], taken.pipeline)
                for taken in builds
            )
        except (OSError, StoreError, snapshot.SnapshotError, KeyError, TypeError, ValueError):
            read = False  # it cannot be told: kept, which loses nothing
        if not read:
            kept[asset_id] = record
    return kept


def written_again_said(shown: str, left_out: dict, kept: int = 0) -> str:
    """What to say, once, when a lockfile of an earlier version is written again in this one.

    :param left_out: What it held that is no longer in it, by the plural of the kind.
    :param kept: How many such records stay in it (:func:`still_pinned`).
    """
    gone = left_out_said(left_out)
    one = sum(left_out.values()) == 1
    without = (
        f" without its {gone}: {'it is' if one else 'they are'} not pinned, and {'is' if one else 'are'} read "
        f"from the snapshot the lockfile names, or from your own build of that commit where the store does "
        f"not have that snapshot."
        if gone else "."
    )
    stays = (
        f" {kept} of its records of charts, notebooks, notes and files stay{'s' if kept == 1 else ''} pinned as "
        f"{'it was' if kept == 1 else 'they were'}: the store has {'its' if kept == 1 else 'their'} bytes, and "
        f"no snapshot there to read {'it' if kept == 1 else 'them'} from."
        if kept else ""
    )
    return f"{shown} was in an earlier form, which pinned every asset. It is written again{without}{stays}"


def _left_out(locked: Lock, kept: set) -> dict:
    """What an earlier lockfile held that this version does not, by the plural of the kind, less the records that stay in it (:func:`still_pinned`)."""
    found: dict = {}
    for asset_id, record in locked.earlier.items():
        if asset_id in kept:
            continue
        kind = KIND_TABLES.get((record.get("ref") or {}).get("kind"), "others")
        found[kind] = found.get(kind, 0) + 1
    return found


def left_out_said(left_out: dict) -> str:
    """The records an earlier lockfile held that this version does not, as words: ``10 charts and 7 notebooks``."""
    order = list(KIND_TABLES.values())
    parts = [
        f"{count} {kind if count != 1 else kind[:-1]}"
        for kind, count in sorted(left_out.items(), key=lambda item: order.index(item[0]) if item[0] in order else len(order))
    ]
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return parts[0] if parts else ""


@dataclass
class Floor:
    """A manifest whose ``requires_chartbook`` admits a ChartBook that cannot read its lockfile, and what was done about it.

    Attributes:
        manifest: The manifest's path.
        was: What it says, or said.
        now: What it says now, or is to say.
        written: Whether the manifest was written.
        asked: Whether the command is one that writes it: ``chartbook pin``,
            ``pin --update`` and ``add``, which a person runs to change what the
            project pins. A build and a read never write a manifest, and
            say which command does.
        why_not: Where it was to be written and was not, or could not be
            by ``chartbook pin`` either, why. The line is then the user's
            to write.
        by_pin: Whether ``chartbook pin`` can write it
            (:func:`cannot_be_raised`), so that a build and a read can
            name that command as what raises it.
    """

    manifest: Path
    was: str
    now: str
    written: bool = False
    asked: bool = False
    why_not: str = ""
    by_pin: bool = True


def floor_of(manifest_file: Union[str, Path]) -> Optional[tuple[str, str, str]]:
    """A manifest's text, what its ``requires_chartbook`` says, and what it is to say, where it admits a ChartBook from before :data:`SINCE`; None otherwise.

    A manifest that does not have the key says nothing of versions, and has
    nothing here to be kept true: None. So does one that cannot be read, or
    whose value is no specifier, which whatever reads the manifest says.
    """
    import tomli

    try:
        with open(manifest_file, encoding="utf-8", newline="") as f:  # as it is, line endings included
            text = f.read()
        project = tomli.loads(text).get("project")
        was = project.get("requires_chartbook") if isinstance(project, dict) else None
        if not isinstance(was, str) or not was.strip() or not admits_before(was, SINCE):
            return None
        return text, was, raised_to(was, SINCE)
    except Exception:  # noqa: BLE001 - packaging's errors among them; nothing of this stops a pin
        return None


def floor_wanted(project_dir: Union[str, Path]) -> Optional[tuple[str, str, str]]:
    """:func:`floor_of` a pipeline's manifest, where its lockfile is one that reaches other people; None where it reaches no one.

    A lockfile that git ignores, beside a manifest that it does not, is
    this machine's alone: the project is shared through git with its
    lockfile left out, so each person's ChartBook writes their own, in the
    version it reads, and nobody on an earlier ChartBook is handed this
    one. Raising the manifest there would make them upgrade for nothing.
    Where git ignores the manifest too (a project under a repository that
    leaves the whole of it out), git says nothing of how it is shared, and
    it is held to its lockfile as any other is.
    """
    project_dir = Path(project_dir)
    found = floor_of(project_dir / MANIFEST_NAME)
    if found is None:
        return None
    # Both answers are needed, and each as git gives it: where either cannot be told, the manifest is held to its lockfile
    if snapshot.ignored_by_git(project_dir / LOCK_FILE) is True and snapshot.ignored_by_git(project_dir / MANIFEST_NAME) is False:
        return None
    return found


def cannot_be_raised(manifest_file: Union[str, Path], text: str, now: str) -> str:
    """Why ``chartbook pin`` could not write a manifest's ``requires_chartbook``; empty where it can.

    Asked before anything is written, and by what only tells (a build, a
    read, ``chartbook run --check``), so that none of them names a command that
    would then say it could not. The manifest is written by moving a new
    file over it (:func:`_write_in_its_place`), which needs its folder to
    be writable, and which a file with a second name (a hard link) is not
    given: the other name would keep the old text.
    """
    if with_requires_chartbook(text, now) is None:
        return "its line there is not one that can be rewritten in place"
    target = Path(os.path.realpath(manifest_file))
    try:
        links = target.stat().st_nlink
    except OSError:
        links = 1
    if links > 1:
        return "the file has a second name (a hard link), which a new file moved over this one would leave with the old text"
    if not os.access(target, os.W_OK) or not os.access(target.parent, os.W_OK):
        # A file its owner has made read-only is not written over by moving another into its place
        return f"the file could not be written ({os.strerror(errno.EACCES)})"
    return ""


def _write_in_its_place(path: Path, text: str) -> None:
    """Write a file's new text so that it is whole or as it was: to a file beside it, moved over it.

    A manifest opened for writing is empty until its text is in it, and a
    disk that fills then leaves it cut short. The file a link points at is
    the one replaced, so the link stays; its mode is kept. What cannot be
    written this way is asked first (:func:`cannot_be_raised`).
    """
    import shutil

    target = Path(os.path.realpath(path))
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as f:  # the text has its own line endings
            f.write(text)
        shutil.copymode(target, temporary)
        replace_when_let(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def see_to_the_floor(project_dir: Union[str, Path], write: bool = False) -> Optional[Floor]:
    """See that a manifest which says which ChartBook it needs asks for one that reads its lockfile.

    For a pipeline whose lockfile is of this version (:data:`SCHEMA`),
    which a ChartBook before :data:`SINCE` cannot read. Such a one says only
    ``its schema is 'chartbook/lock/v2', and this version of ChartBook reads
    'chartbook/lock/v1'``; given a ``requires_chartbook`` it does not meet,
    it says which version to install, and the command that installs it.
    So ``requires_chartbook = ">=0.5.0"`` is to become ``">=0.6.0"``.

    :param write: Whether to write it: in the manifest's own text, with
        every other character of the file as it was
        (:func:`chartbook.manifest.with_requires_chartbook`). For
        ``chartbook pin``, ``pin --update`` and ``add``. A build (``chartbook
        run``) and a read never write a manifest: a run that snapshots
        must leave the folder as its commit has it, and a dependency built
        in ChartBook's own copy has a manifest that is nobody's to commit.
        They are told what is wanted, and which command writes it.
    :returns: What is wanted, and what was done, for the command to say;
        None where the manifest asks for nothing, or already for enough,
        or the lockfile is one git ignores (:func:`floor_wanted`).
    """
    manifest_file = Path(project_dir) / MANIFEST_NAME
    found = floor_wanted(project_dir)
    if found is None:
        return None
    text, was, now = found
    floor = Floor(manifest_file, was, now, asked=write)
    floor.why_not = cannot_be_raised(manifest_file, text, now)
    if floor.why_not:
        floor.by_pin = False
        return floor
    if not write:
        return floor
    try:
        _write_in_its_place(manifest_file, with_requires_chartbook(text, now))
    except OSError as error:
        floor.why_not = f"the file could not be written ({error.strerror or error})"
        return floor
    with contextlib.suppress(Exception):
        from chartbook import built
        built.note_manifest_written(Path(project_dir), text)
    floor.written = True
    return floor


def floor_said(floor: Floor, shown: str, lockfile: str = LOCK_FILE, where: str = "") -> str:
    """What to say of a manifest whose ``requires_chartbook`` admits a ChartBook that cannot read its lockfile (:func:`see_to_the_floor`).

    :param shown: The manifest's path, as it is to be printed.
    :param where: For a build or a read in another folder than the
        manifest's: `` --project-dir FOLDER``, to follow ``chartbook pin``
        (:func:`where_to_pin`).
    """
    why = f"{lockfile} is of a version that began with ChartBook {SINCE}, and an earlier one cannot read it"
    if floor.written:
        return (
            f'{shown}: requires_chartbook is now "{floor.now}" (it was "{floor.was}"). {why}: with this line it is '
            f"told to upgrade, and how. Commit the manifest with the lockfile."
        )
    if floor.asked or not floor.by_pin:
        return (
            f'{shown}: write requires_chartbook = "{floor.now}" under [project] (it says "{floor.was}"). {why}: '
            f"with that line it is told to upgrade, and how. It was not written for you: {floor.why_not}."
        )
    return (
        f'{shown}: requires_chartbook = "{floor.was}" admits a ChartBook that cannot read {lockfile}, which is of a '
        f'version that began with {SINCE}: such a one says only which version it reads. `chartbook pin{where}` raises '
        f'the line to "{floor.now}", and it is then told to upgrade, and how.'
    )


def where_to_pin(floor: Floor) -> str:
    """`` --project-dir FOLDER`` for a manifest that is not in the folder a command is run in, to follow ``chartbook pin``; else empty.

    Quoted as this system's shells take it, as every command a message
    prints is (:func:`chartbook.missing._quoted`), so that it can be pasted.
    """
    from chartbook.missing import _quoted  # here: that module reads this one

    folder = floor.manifest.parent
    try:
        if folder.resolve() == Path.cwd().resolve():
            return ""
    except OSError:
        pass
    return f" --project-dir {_quoted(folder)}"


def _from_before_rows(taken) -> bool:
    """Whether a snapshot was made by a ChartBook from before rows were recorded (:data:`SINCE`).

    Going by what it says made it, and by what it says: one that records
    the rows of any dataframe, or why one has none, is not from before,
    whatever version it names (a build of this ChartBook made before it
    had its number).
    """
    from packaging.version import InvalidVersion, Version

    if any("rows" in record or "not_hashed" in record for record in (getattr(taken, "assets", None) or {}).values()):
        return False
    made_by = (getattr(taken, "built_with", None) or {}).get("chartbook")
    try:
        return Version(str(made_by)) < Version(SINCE)
    except InvalidVersion:
        return True  # one that does not say is from before snapshots said


def pinned_before_rows(after: Lock, before: Lock, snapshots: dict) -> list[str]:
    """The dataframes a lockfile pins by their files alone because their snapshots are from before rows were recorded, by asset ID.

    Of dependencies pinned from a snapshot (one pinned from its repository
    records no rows by design). A record that says nothing of its rows is
    counted where the snapshot it was pinned from in this run says an
    earlier ChartBook made it (*snapshots*, by dependency), or where it is
    as a lockfile of the earlier version had it, which recorded none. One
    whose rows are not hashed says why, and is not of these; nor is a file
    this ChartBook's own snapshot found to be no table.

    Only what this run pinned, moved, or wrote again from a lockfile of the
    earlier version: a record that a lockfile of this version already had,
    as it is, was told of when it was made, and is not told of again each
    time another dependency moves.
    """
    from_snapshots = {
        entry["id"] for entry in after.dependencies
        if isinstance(entry.get("location"), dict) and entry["location"].get("kind") in ("store", "path")
    }
    found = []
    for asset_id, record in after.assets.items():
        ref = record.get("ref")
        if (ref.get("kind") if isinstance(ref, dict) else None) != "dataframe" or record.get("pipeline") not in from_snapshots:
            continue
        if not record.get("content_hash") or "rows" in record or "not_hashed" in record:
            continue
        if before.read_as == SCHEMA and before.assets.get(asset_id) == record:
            continue
        taken = snapshots.get(record.get("pipeline"))
        if taken is not None:
            if _from_before_rows(taken):
                found.append(asset_id)
        elif before.read_as != SCHEMA and (before.assets.get(asset_id) or {}).get("content_hash") == record["content_hash"]:
            found.append(asset_id)
    return sorted(found)


def rows_pinned_now(after: Lock, before: Lock) -> list[str]:
    """The dataframes pinned to the same file as before whose record now says its rows, and said nothing of them, by asset ID.

    The pin has not moved, so ``chartbook pin --update`` says ``already pinned``
    of it, and writes the lockfile all the same: this is why.
    """
    found = []
    for asset_id, record in after.assets.items():
        had = before.assets.get(asset_id)
        if not had or not record.get("content_hash") or had.get("content_hash") != record["content_hash"]:
            continue
        if "rows" in record and "rows" not in had and "not_hashed" not in had:
            found.append(asset_id)
    return sorted(found)


def rows_not_hashed_now(after: Lock, before: Lock) -> list[tuple[str, str]]:
    """The dataframes pinned to the same file as before whose record now says why its rows are not hashed, and said nothing of them: ``(asset ID, why)``.

    The other outcome of a snapshot made again by a ChartBook that hashes
    rows: a table it cannot hash (a column of lists, say) stays pinned by
    its file alone, and the lockfile is written to say why.
    """
    found = []
    for asset_id, record in after.assets.items():
        had = before.assets.get(asset_id)
        if not had or not record.get("content_hash") or had.get("content_hash") != record["content_hash"]:
            continue
        if isinstance(record.get("not_hashed"), str) and "rows" not in had and "not_hashed" not in had:
            found.append((asset_id, record["not_hashed"]))
    return sorted(found)


def rows_now_said(now: list) -> str:
    """What to say, when a lockfile is written, of the dataframes whose pins record their rows from now on (:func:`rows_pinned_now`)."""
    one = len(now) == 1
    return (
        f"{len(now)} dataframe{' has its' if one else 's have their'} rows pinned now, as well as "
        f"{'its file' if one else 'their files'}: a build of someone's own that holds the same rows meets the pin."
    )


def without_rows_said(without: list) -> str:
    """What to say, when a lockfile is written, of the dataframes it pins from snapshots made before rows were recorded (:func:`pinned_before_rows`)."""
    one = len(without) == 1
    return (
        f"{len(without)} dataframe{' is' if one else 's are'} pinned by {'its file' if one else 'their files'} alone: "
        f"{'its snapshot is' if one else 'their snapshots are'} from before ChartBook {SINCE}, which recorded no rows, "
        f"and no rebuild meets such a pin. To pin {'its' if one else 'their'} rows: `chartbook snapshot` again in "
        f"{'its pipeline' if one else 'each of their pipelines'}, with this version, then `chartbook pin --update` here. "
        f"Nothing has to be built again: where a table's rows can be recorded, the same commit and the same files make "
        f"a new snapshot, once."
    )


def write_lock(lock: Lock, path: Union[str, Path]) -> bool:
    """Write a lockfile, if what it would hold is not already there.

    :returns: True if the file was written; False if it already said this.
    """
    path = Path(path)
    text = json.dumps(lock.to_document(), indent=2, ensure_ascii=False) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    # A name of its own, so that two pins at once do not write over each
    # other's half-written file and then rename it away
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        replace_when_let(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def pinned_hash(records: Iterable[dict]) -> Optional[str]:
    """One hash over everything pinned of a dependency.

    It is the SHA-256 of a listing with a line per pinned asset,
    ``<hex of its content hash>``, two spaces, ``<its ID>``, newline, sorted
    by ID: the form a directory is hashed in. It changes when any pin of
    the dependency does, so one line of a diff says a dependency moved.

    :returns: The hash, or None if nothing of the dependency is pinned.
    """
    lines = []
    for record in records:
        content_hash = record.get("content_hash")
        if not content_hash:
            continue
        if not isinstance(content_hash, str) or ":" not in content_hash:
            raise ValueError(f"Invalid content_hash {content_hash!r} for {record.get('id')!r}")
        lines.append((record["id"], content_hash.split(":", 1)[1]))
    lines.sort()
    if not lines:
        return None
    listing = "".join(f"{digest}  {asset_id}\n" for asset_id, digest in lines)
    return hashing.format_hash(hashlib.sha256(listing.encode("utf-8")).hexdigest())


@dataclass(frozen=True)
class PinEvent:
    """One thing pinning did, or found.

    Attributes:
        status: What happened. For an asset: ``pinned``, ``restored`` (put
            back in a store that had lost it), ``kept`` (already pinned),
            ``stale`` (already pinned, and the other pipeline has something
            else now), ``moved`` (an update changed the pin), ``not_built``
            (declared, with no file to pin), ``lost`` (pinned, not in the
            store, and the other pipeline no longer has those bytes),
            ``dropped`` (no longer declared, so no longer pinned),
            ``outside`` (declared with a path that reaches outside the
            dependency's own files, which is not pinned),
            ``passed_over`` (a dependency named by its ID: a newer snapshot
            of its ID was made in another repository, and not taken),
            ``unchecked`` (one taken from a snapshot that names no
            repository, so not checked against the one first pinned from),
            ``id_changed`` (a dependency named by its ID: the store has newer
            snapshots of the same repository and folder under another ID,
            which the pipeline probably calls itself now),
            ``let_go`` (an update moved a ``git`` dependency to another
            commit, and this was built from the one before and is not built
            at the new one, so it is no longer pinned), ``unsynced`` (its
            object is in the store with other than the bytes its record
            says: a store in a synced folder whose sync has not finished),
            ``unlocked`` (an asset that is not in the lockfile, a chart say,
            which every build draws anew: it is read from the snapshot the
            dependency is pinned to, and not pinned; ``detail`` is its kind),
            ``stood_in`` (already pinned; the store does not have its bytes,
            and a snapshot of yours of the pinned commit holds the same
            rows, up to the pin's last date, which is ``detail``),
            ``differs`` (already pinned; the store does not have its bytes,
            and your snapshot of the pinned commit does not hold its rows:
            ``detail`` says where).
            For a
            whole dependency: ``removed`` (no longer in ``[dependencies]``),
            ``at_snapshot`` (it stays pinned to the snapshot its entry names,
            and none of its assets is in the lockfile),
            ``unreachable`` (its directory holds no pipeline), ``fetched`` (a
            ``git`` dependency was got from its repository), ``unfetched``
            (it could not be), ``relocated`` (the manifest says it is
            somewhere other than where it was pinned from, which only an
            update follows), ``no_snapshot`` (a ``path`` dependency has no
            snapshot to pin from).
        dependency: The dependency's key in ``[dependencies]``.
        asset: The asset's ID, or None when the event is about the whole
            dependency.
        old: The content hash it was pinned at, if it was.
        new: The content hash it is pinned at now, if it is.
        detail: More to say: a path, or why.
    """

    status: str
    dependency: str
    asset: Optional[str] = None
    old: Optional[str] = None
    new: Optional[str] = None
    detail: str = ""


#: The statuses that mean a project is not fully pinned, and should fail CI.
PROBLEM_STATUSES = frozenset(
    {"lost", "unsynced", "unreachable", "unfetched", "no_snapshot", "outside", "glob_name", "differs"}
)

#: What to do about an object a snapshot names that the store does not have.
#: In a store that machines share through a sync service, the likeliest
#: cause is a sync that has not finished, on one side or the other.
NOT_SYNCED_YET = (
    "In a store that machines share through a synced folder, the likeliest cause is a sync "
    "that has not finished: here, wait for it and run this again; on the machine that put it "
    "in the store, see that its sync has sent everything"
)


def _incomplete(store: Store, record: dict, pipeline: Optional[str] = None) -> Optional[str]:
    """Why the store's object of a record with a hash does not hold all of its bytes yet; None if it does, or that cannot be told."""
    return snapshot.not_whole(store, record, pipeline)


@dataclass
class PinReport:
    """What a ``pin`` or an ``update`` did.

    Attributes:
        lockfile: The lockfile's path.
        events: Everything that happened, in order: by dependency, then by
            asset.
        written: True if the lockfile was written; False if it already said
            what it would have.
        git: The dependencies that are git repositories, by key. One of
            these has only what its repository commits.
        snapshots: The snapshot each ``path`` dependency was pinned from in
            this run, by key.
        unrooted: Why the store's note of this lockfile could not be
            written or removed, when it could not: the store is read-only
            for this user, as a store a team shares may be for everyone but
            its owner. The lockfile is written all the same; the store's
            ``gc`` goes by the note it has, if any.
        refused: Why the lockfile was not written, when the pin's guard
            refused it (the default one refuses a lockfile that would make
            the pipeline's dependencies cyclic; a caller's
            ``before_writing`` takes its place): neither the lockfile, nor
            the store's note of it, nor any object was written. Empty
            otherwise.
        earlier: The version the lockfile was in, when this run wrote one
            of an earlier version again in this one (:data:`READS`). Empty
            otherwise.
        left_out: What that earlier lockfile held that this one does not,
            by the plural of the kind (:attr:`Lock.left_out`).
        stood_in: For each dependency whose pinned bytes the store does not
            all have, what a snapshot of yours of the pinned commit makes
            of its pins (:class:`chartbook.standins.Found`), by key: it
            stands in, or does not, and why.
        kept_earlier: How many such records stay in this one, pins as they
            were, the store having their bytes and no snapshot that names
            them (:func:`still_pinned`).
        rows_said: For each dataframe whose pin moved, what its rows are
            beside the pin it had, by asset ID: new rows, or earlier rows
            changed (:func:`chartbook.standins.since`).
        floor: What was done about a manifest whose ``requires_chartbook``
            admitted a ChartBook that cannot read this lockfile
            (:func:`see_to_the_floor`); None where there was nothing to do.
        without_rows: When the lockfile was written: the dataframes it pins
            by their files alone, their snapshots being from before rows
            were recorded (:func:`pinned_before_rows`), by asset ID.
        rows_now: When the lockfile was written: the dataframes whose pin
            is of the same file as before and now records its rows, which
            it did not (:func:`rows_pinned_now`), by asset ID. What the
            reader's ``chartbook pin --update`` does once an upstream has been
            snapshotted again by a ChartBook that records them.
        not_hashed_now: And those whose pin now says why its rows are not
            hashed (:func:`rows_not_hashed_now`), each with why.
        not_in_store: Where something could not be pinned for want of a
            pipeline to build: what this pipeline reads that is not in the
            store, in the order to build it
            (:class:`chartbook.missing.Listing`). Set by the commands that
            make the list, ``chartbook run`` and ``chartbook pin``; None
            otherwise.
    """

    lockfile: Path
    events: list[PinEvent] = field(default_factory=list)
    written: bool = False
    git: set = field(default_factory=set)
    #: The pipeline each dependency's pins are of, by its own ID, as its entry before this pin says it
    #: (pinned_pipeline): whose snapshots "is it in the store" is asked of, as a read asks it
    pipelines: dict = field(default_factory=dict)
    snapshots: dict = field(default_factory=dict)
    unrooted: str = ""
    refused: str = ""
    earlier: str = ""
    left_out: dict = field(default_factory=dict)
    stood_in: dict = field(default_factory=dict)
    kept_earlier: int = 0
    rows_said: dict = field(default_factory=dict)
    floor: Optional["Floor"] = None
    without_rows: list = field(default_factory=list)
    rows_now: list = field(default_factory=list)
    not_hashed_now: list = field(default_factory=list)
    not_in_store: Optional[object] = None

    def count(self, *statuses: str) -> int:
        """How many events have one of these statuses."""
        return sum(event.status in statuses for event in self.events)

    @property
    def problems(self) -> list[PinEvent]:
        """The events that mean something could not be pinned."""
        return [event for event in self.events if event.status in PROBLEM_STATUSES]


def store_has_for(
    entry: dict, snapshots: Callable[[], list], first_commit: Optional[str] = None, from_repository: bool = False
) -> bool:
    """Whether the store has a snapshot a pin of a dependency named by its ID could take, so its repository is not wanted.

    Of the ID, at the entry's ``commit`` if it names one; from the
    repository the entry names, if it names one; and, for one pinned from
    its repository before, from that repository (*first_commit*), so that
    another that gives itself the same ID is no reason not to go back to
    it. One pinned from its repository whose first commit is not known
    (*from_repository* with no *first_commit*) has nothing in the store
    known to be its own. Two repositories' snapshots of the ID with nothing
    to choose between them are something: pin says which to name, rather
    than clone. A snapshot dated after now is not one a pin takes.
    """
    pipeline, at, named = entry["_store"], entry.get("commit"), entry.get("_repository")
    every = [t for t in snapshots() if t.pipeline == pipeline and not snapshot.made_in_the_future(t)]

    def at_it(taken) -> bool:
        return not at or taken.commit.startswith(at)

    if named:
        return any(at_it(t) and repository_key(t.repository) == repository_key(named) for t in every)
    if first_commit:
        # Its repository as all its snapshots tell it, at the commit asked for
        groups, _ = snapshot.repository_groups(every)
        return any(
            ("first", first_commit) in set().union(*(snapshot.identity_keys(t) for t in group)) and any(at_it(t) for t in group)
            for group in groups
        )
    if from_repository:
        return False
    return any(at_it(t) for t in every)


def choose_for_rev(
    entry: dict,
    root: str,
    was: Optional[dict],
    may_move: bool,
    snapshots: Callable[[], list],
    host: str,
    git_cache: GitCache,
    project_dir: Path,
    *,
    pinned: bool,
) -> tuple:
    """For a dependency named by its ID with a ``rev``: what to pin it from.

    ``"acme/rates" = { rev = "main" }`` takes the newest snapshot at or
    before the commit ``main`` is in its repository, which only the
    repository can say: the one the entry names with ``repository``, or
    ``<default_host>/<id>``. Its history is walked back from that commit to
    the nearest one the store has a snapshot of, from that repository (by
    its first commit); with none, it is pinned from the clone at that
    commit, and ``chartbook run`` builds it, as a ``git`` dependency is. A
    plain pin keeps what is pinned. Pin and run's plan both ask this.

    :returns: ``("entry", entry)`` to pin it by the entry given (a store
        entry to keep, or a ``git`` one); ``("snapshot", (snapshot,
        identity))`` to pin it from that snapshot; or ``("none", why)``.
    """
    from chartbook.config import clone_url_for

    pipeline, rev = entry["_store"], entry["rev"]
    location = (was or {}).get("location", {})
    same = location.get("pipeline") == pipeline
    named = entry.get("repository") if entry.get("_repository") else None
    url = named or clone_url_for(pipeline, host)
    converted = (
        {"git": url, "_from_id": pipeline, "rev": rev,
         "_from": "the repository its entry names" if named else "[resolve] default_host"}
        if url else None
    )
    if converted and entry.get("_repository"):
        converted["_repository"] = entry["_repository"]
    recorded_commit = same and bool(location.get("commit"))
    if not may_move and pinned and same and location.get("kind") == "store":
        return "entry", entry  # a plain pin keeps a snapshot it pinned (a snapshot always holds bytes)
    if not may_move and (pinned or recorded_commit) and same and location.get("kind") == "git" and converted:
        return "entry", converted  # and a commit of its repository, built or not
    if pipeline == root:
        return "none", f"{pipeline} is this pipeline itself: a pipeline cannot depend on itself"
    if converted is None:
        return "none", (
            f"rev = {rev!r} asks its repository which commit that is, and none is known here: set "
            f"[resolve] default_host, or name it with repository = \"...\""
        )
    try:
        check_git_url(url)
        checkout = git_cache.get(local_url(url, project_dir), rev)
    except (GitError, ValueError, OSError) as error:
        return "none", f"could not ask {strip_url_credentials(url)} what {rev!r} is: {error}"
    named_id = _project_id_in(Path(checkout.path))
    if named_id and named_id != pipeline:
        said = named_id if named_id.startswith(("a [project]", "an id ")) else f"the ID {named_id}"
        return "none", f"{strip_url_credentials(url)}'s chartbook.toml gives {said}, not {pipeline}"
    first = _first_commit_of(git_cache, local_url(url, project_dir), checkout.commit)
    recorded = location.get("first_commit") if same and not entry.get("_repository") else None
    if first and recorded and first != recorded:
        return "none", (
            f"{strip_url_credentials(url)}'s history begins at {first[:7]}, not at {recorded[:7]} as the one "
            f"it was pinned from: another repository, or its history rewritten. Name it with repository = "
            f"\"...\", or remove it from chartbook.lock and `chartbook pin --update`"
        )
    # Its snapshots, from this repository, by commit
    every = [t for t in snapshots() if t.pipeline == pipeline and not snapshot.made_in_the_future(t)]
    if named:
        mine = [t for t in every if repository_key(t.repository) == repository_key(entry["_repository"])]
    elif first or repository_key(url):
        # Its repository's snapshots: by its first commit, or by its address
        # (a snapshot made in a shallow clone records only that); the walk
        # back along its history keeps to commits of this repository
        groups, unnamed = snapshot.repository_groups(every)
        keys = {("first", first)} if first else set()
        if repository_key(url):
            keys.add(("address", repository_key(url)))
        mine = [
            taken for group in groups
            if keys & set().union(*(snapshot.identity_keys(t) for t in group))
            for taken in group
        ] + (unnamed if len(groups) <= 1 else [])
    else:
        mine = []  # which snapshots are this repository's cannot be told
    by_commit: dict = {}
    for taken in mine:
        by_commit.setdefault(taken.commit, []).append(taken)
    if by_commit:
        for commit in _history(git_cache, local_url(url, project_dir), checkout.commit):
            if commit in by_commit:
                newest = max(by_commit[commit], key=lambda t: t.made_at)
                return "snapshot", (newest, {"repository": newest.repository, "first_commit": first or newest.first_commit})
    return "entry", converted


def _history(git_cache: GitCache, url: str, commit: str, limit: int = 200000) -> list:
    """The commits of a repository back from *commit*, newest first, from its clone in the git cache."""
    import subprocess

    from chartbook.gitcache import _FULL_COMMIT

    if not _FULL_COMMIT.match(commit or ""):
        return []
    environment = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            [*_GIT, f"--git-dir={git_cache.repo_path(url)}", "rev-list", f"--max-count={limit}", commit],
            capture_output=True, text=True, timeout=120, env={**environment, "GIT_OPTIONAL_LOCKS": "0"}, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return result.stdout.split() if result.returncode == 0 else []


def clone_instead(
    entry: dict,
    root: str,
    was: Optional[dict],
    may_move: bool,
    snapshots: Callable[[], list],
    host: str,
    built_here: Iterable[str] = (),
    *,
    pinned: bool,
) -> dict:
    """The entry to pin a dependency by: for one named by its ID that is to be got from its repository, a ``git`` one.

    Decision 1a: a pipeline named by its ID is read from its snapshots in
    the store, and its repository is wanted only when the store has no
    snapshot of it at all. Then, with a default host set (``[resolve]
    default_host``), it is cloned from ``<host>/<id>``, or from the
    repository its entry names, at the commit its entry names if it names
    one, and pinned and built as a ``git`` dependency is.

    A pin keeps where a dependency was pinned from: one pinned from the
    store stays there, and one pinned from its repository stays there, even
    when the store has a snapshot of it now. An update, or a first pin,
    looks again. A bare ID, the pipeline itself, and a pipeline built here
    (*built_here*, a catalog's own, by ID) are never cloned.

    :param was: Its entry in the lockfile, if it has one.
    :param snapshots: The store's readable snapshots, read when asked for.
    :param pinned: Whether the lockfile holds bytes of it (a content
        hash). An entry with nothing pinned, as a failed first read or a
        failed clone leaves, is looked at afresh, as a first pin is.
    """
    from chartbook.config import clone_url_for

    pipeline = entry.get("_store")
    if not pipeline or not host or pipeline == root or pipeline in set(built_here):
        return entry
    location = (was or {}).get("location", {})
    # Got from its repository before: a commit of it is recorded (a failed
    # clone records none, and says nothing of which repository it is)
    from_repository = location.get("kind") == "git" and location.get("pipeline") == pipeline and bool(location.get("commit"))
    pinned_from_repository = pinned and from_repository
    if not may_move and pinned and location.get("kind") in ("store", "path"):
        return entry  # pinned from the store (or a folder, before): a pin keeps it there
    # The repository it was pinned from, by its first commit, whether or not
    # any bytes of it are pinned yet (one not built is still that repository's)
    own_first = (
        location.get("first_commit")
        if from_repository or (pinned and location.get("kind") == "store" and location.get("pipeline") == pipeline)
        else None
    )
    if (may_move or not pinned_from_repository) and store_has_for(entry, snapshots, own_first, from_repository):
        return entry
    named = entry.get("_repository")
    # The repository the entry names, as it was written (an ssh address,
    # a port), or the pipeline's on the default host
    named = entry.get("repository") if named else None
    url = named or clone_url_for(pipeline, host)
    if url is None:
        return entry
    try:
        from chartbook.gitcache import check_git_url

        check_git_url(url)
    except ValueError:
        return entry
    converted = {"git": url, "_from_id": pipeline, "_from": "the repository its entry names" if named else "[resolve] default_host"}
    if entry.get("commit"):
        converted["rev"] = entry["commit"]
    if entry.get("_repository"):
        converted["_repository"] = entry["_repository"]
    return converted


def _project_id_in(directory: Path) -> Optional[str]:
    """The ID a folder's chartbook.toml gives itself in ``[project] id``, if it gives one; a description of it if it is no name.

    A ``[project]`` that is not a table, or an ``id`` that is not a
    non-empty string, is not "no ID": it is something other than the ID
    a dependency is named by, and is refused as such.
    """
    try:
        project = _read_manifest_file(Path(directory)).get("project")
    except (OSError, ValueError):
        return None
    if project is None:
        return None
    if not isinstance(project, dict):
        return "a [project] that is not a table"
    if "id" not in project:
        return None
    named = project["id"]
    return named if isinstance(named, str) and named else f"an id that is no name ({named!r:.40})"


def _pipeline_of_clone(directory: Path, entry: dict, project_dir: Path) -> Optional[str]:
    """The ID of the pipeline a ``git`` dependency's copy holds, as a clone of its repository derives it; None if nothing names one.

    A checkout is one commit's files, with no ``.git`` of its own, in a
    folder named after the commit, so the folder gives no ID. It is the ID
    the checkout's ``[project] id`` gives; else the one it was named by in
    ``[dependencies]``; else the one the repository's address gives, as
    for any pipeline at the top of its repository: ``repo_url`` in its
    manifest, else the address it was fetched from. A repository that is a
    folder on this disk, with no address, is named as that folder names
    itself.
    """
    named = _project_id_in(directory)
    try:
        if named:
            return validate_pipeline_id(named)
        if entry.get("_from_id"):
            return validate_pipeline_id(entry["_from_id"])
        project = _read_manifest_file(directory).get("project")
        project = project if isinstance(project, dict) else {}
        written = project.get("repo_url")
        for address in (written if isinstance(written, str) else "", entry.get("git") or ""):
            from_address = id_from_address(address) if address else None
            if from_address:
                return validate_pipeline_id(from_address)
        url = local_url(entry["git"], project_dir) if entry.get("git") else ""
        if url.startswith("file://"):
            from urllib.parse import urlparse
            from urllib.request import url2pathname

            # file:///C:/x is C:\x on Windows, where the path alone has no drive
            url = url2pathname(urlparse(url).path)
        if url and "://" not in url and Path(url).is_dir():
            derived = derive_pipeline_id(project, Path(url))
            # A bare repository's folder is named as its clone is, with .git
            if derived.endswith(".git") and Path(url).name.endswith(".git") and len(derived) > 4:
                derived = validate_pipeline_id(derived[:-4])
            return derived
    except (OSError, ValueError):
        pass
    return None


def _has_commit(git_cache: GitCache, url: str, commit: str, fetch: bool = False) -> bool:
    """Whether a repository's clone in the git cache has a commit; with *fetch*, after asking the repository for it by its hash.

    The cache fetches branches and tags, so a commit on none of them (a
    branch since deleted, a pull request's merge) is asked for by itself.
    The commit comes from a lockfile, which anyone can edit: only a full
    commit hash ever reaches git, never something it could read as an
    option.
    """
    import subprocess

    from chartbook.gitcache import _FULL_COMMIT

    if not isinstance(commit, str) or not _FULL_COMMIT.match(commit):
        return False

    environment = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARIABLES}

    def present() -> bool:
        try:
            result = subprocess.run(
                [*_GIT, f"--git-dir={git_cache.repo_path(url)}", "cat-file", "-e", f"{commit}^{{commit}}"],
                capture_output=True, text=True, timeout=60, env={**environment, "GIT_OPTIONAL_LOCKS": "0"}, encoding="utf-8", errors="replace"
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        return result.returncode == 0

    if present():
        return True
    if not fetch:
        return False
    try:
        git_cache._git(f"--git-dir={git_cache.repo_path(url)}", "fetch", "--quiet", url, commit, url=url)
    except (GitError, ValueError, OSError):
        return False
    return present()


def _first_commit_of(git_cache: GitCache, url: str, commit: str) -> str:
    """A repository's first commit, back from *commit* by first parents, from its clone in the git cache; empty if not known."""
    import subprocess

    from chartbook.gitcache import _FULL_COMMIT

    if not isinstance(commit, str) or not _FULL_COMMIT.match(commit):
        return ""  # only a full commit hash reaches git

    # The bare clone, named outright: a GIT_DIR in the environment (a git hook
    # sets one) would otherwise be asked instead
    environment = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            [*_GIT, f"--git-dir={git_cache.repo_path(url)}", "rev-list", "--max-parents=0", "--first-parent", commit],
            capture_output=True, text=True, timeout=60, env={**environment, "GIT_OPTIONAL_LOCKS": "0"}, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    roots = result.stdout.split() if result.returncode == 0 else []
    return roots[-1] if roots and len(roots[-1]) == 40 else ""


def _read_pipeline(project_dir: Path) -> tuple[str, dict]:
    """A pipeline's ID and its ``[dependencies]``, from its manifest alone.

    Only what pinning needs is read and checked, so a manifest with
    something else wrong in it can still be pinned.
    """
    source = project_dir / MANIFEST_NAME
    try:
        raw = _read_manifest_file(project_dir)
        project_type = resolve_project_type(raw, source=str(source))
    except FileNotFoundError:
        raise LockError(
            f"No {MANIFEST_NAME} in {project_dir}. Pinning is done in a pipeline."
        ) from None
    if project_type != "pipeline":
        raise LockError(
            f"{source} is a catalog. A catalog depends on no pipeline, so it "
            f"has nothing to pin; run this in the pipeline that has the "
            f"[dependencies]."
        )
    try:
        dependencies = validate_dependencies(raw.get("dependencies") or {}, project_dir)
    except ValueError as error:
        raise type(error)(f"{source}: {error}") from None
    return derive_pipeline_id(raw.get("project", {}), project_dir), dependencies


def _dependency_entry(key: str, entry: dict) -> dict:
    """A dependency as the lockfile lists it: no absolute path, no password."""
    if entry.get("_store"):
        location = {"kind": "store", "pipeline": entry["_store"]}
        if entry.get("commit"):
            location["at"] = entry["commit"]
        if entry.get("rev"):
            location["rev"] = entry["rev"]
        if entry.get("_repository"):
            location["repository"] = entry["_repository"]
        return {"id": key, "via": "store", "location": location}
    if entry.get("_from_id"):
        # Named by its ID, and got from its repository: by its ID, not by an
        # address, which each machine works out from its own default host
        location = {"kind": "git", "pipeline": entry["_from_id"]}
        if entry.get("rev"):
            location["rev"] = entry["rev"]
        if entry.get("_repository"):
            location["repository"] = entry["_repository"]
        return {"id": key, "via": "rev", "location": location}
    if "git" in entry:
        location = {"kind": "git", "url": strip_url_credentials(entry["git"])}
        if entry.get("rev"):
            location["rev"] = entry["rev"]
        return {"id": key, "via": "rev", "location": location}
    return {"id": key, "via": "path", "location": {"kind": "path", "path": entry["path"]}}


_in_process_locks: dict[str, "threading.Lock"] = {}


def held_elsewhere(lock_path: Path) -> bool:
    """Whether another thread or process holds :func:`_one_at_a_time`'s lock for this path now; False where that cannot be told.

    Asked without waiting, so that a command can say it is about to wait.
    """
    from chartbook.config import get_cache_path

    name = hashlib.sha256(str(Path(lock_path).resolve()).encode()).hexdigest()[:24]
    guard = _in_process_locks.get(name)
    if guard is not None and guard.locked():
        return True
    # Only "someone holds it" counts: a filesystem with no locks says
    # something else, and there nothing waits
    held = (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES, errno.EDEADLK)
    try:
        path = get_cache_path() / "locks" / f"{name}.lock"
        if not path.exists():
            return False
        with open(path, "a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    return error.errno in held
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                return False
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                return error.errno in held
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
    except (OSError, ValueError):
        return False


@contextlib.contextmanager
def _one_at_a_time(lock_path: Path):
    """Hold a lockfile while it is read, worked out and written, across threads and processes.

    Two pins of one pipeline at once, as two first reads by a notebook's
    threads or two parallel tasks would make, otherwise each write what the
    other did not see. The lock is a file under the cache, not beside the
    lockfile, so the pipeline's folder gains nothing to ignore. Where it
    cannot be made, the pin goes ahead without it.
    """
    import threading

    from chartbook.config import get_cache_path

    name = hashlib.sha256(str(Path(lock_path).resolve()).encode()).hexdigest()[:24]
    guard = _in_process_locks.setdefault(name, threading.Lock())
    with guard:
        handle = None
        try:
            folder = get_cache_path() / "locks"
            folder.mkdir(parents=True, exist_ok=True)
            handle = open(folder / f"{name}.lock", "a+b")
        except (OSError, ValueError):
            pass  # no cache to lock in, or a [cache] setting that is no path
        if handle is None:
            yield
            return
        with handle:
            locked = False
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    while not locked:
                        try:
                            # It tries for ten seconds, and then says so: try again
                            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                            locked = True
                        except OSError as error:
                            if error.errno not in (errno.EDEADLK, errno.EACCES):
                                break
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    locked = True
            except OSError:
                pass
            try:
                yield
            finally:
                if locked and os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _sync(
    project_dir: Union[str, Path],
    store: Optional[Store],
    move: Optional[Iterable[str]],
    git_cache: Optional[GitCache] = None,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
    before_writing: Optional[Callable[[Lock], Optional[str]]] = None,
    raise_floor: bool = False,
) -> PinReport:
    """:func:`_sync_now`, one at a time for each lockfile."""
    with _one_at_a_time(Path(project_dir) / LOCK_FILE):
        return _sync_now(project_dir, store, move, git_cache, only, clone_missing, built_here, before_writing, raise_floor)


def _sync_now(
    project_dir: Union[str, Path],
    store: Optional[Store],
    move: Optional[Iterable[str]],
    git_cache: Optional[GitCache] = None,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
    before_writing: Optional[Callable[[Lock], Optional[str]]] = None,
    raise_floor: bool = False,
) -> PinReport:
    """Bring a pipeline's lockfile and the store in line with its manifest.

    :param move: None to leave every existing pin where it is (``pin``).
        Otherwise the dependencies whose pins may move (``update``); empty
        means all of them.
    :param only: The keys of the dependencies to look at; the others keep
        what the lockfile had for them, and nothing of them is fetched.
        All of them by default.
    :param clone_missing: Whether a dependency named by its ID that the
        store has no snapshot of is cloned from the default host
        (:func:`clone_instead`). A read pins with it off: a read never fetches.
    :param built_here: The IDs of pipelines built in the same run (a
        catalog's own), which are never cloned.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param before_writing: Called with the lockfile as it would be written,
        whether or not that is what it holds now. What it returns, if
        anything, is why it is not to be written: then nothing is written,
        neither the lockfile, nor the store's note of it, nor any object
        (what the pin puts in the store is held until then), and the
        report's ``refused`` says why. By default a lockfile whose new or
        moved entries would close a cycle of dependencies, or lead into
        one, is refused (:func:`_refuse_a_cycle`); a caller that gives its
        own guard decides instead.
    :param raise_floor: Whether to write the manifest's
        ``requires_chartbook`` where it admits a ChartBook that cannot
        read the lockfile (:func:`see_to_the_floor`). Without it the
        report says what is wanted, and nothing of the manifest is written.
    """
    project_dir = Path(project_dir).resolve()
    root, dependencies = _read_pipeline(project_dir)
    from chartbook.multi_store import with_dependencies
    store = with_dependencies(project_dir, store)
    the_store = store
    if not isinstance(store, _PutLater):
        # What the pin puts in the store is put only once the lockfile may be written
        store = _PutLater(store)
    # The store's snapshots, read once for every dependency named by its ID
    read = []

    def snapshots_in_store() -> list:
        if not read:
            read.append(snapshot.readable_snapshots(store)[0])
        return read[0]

    host: Optional[str] = None  # the default host, read when a dependency is named by its ID
    lock_path = project_dir / LOCK_FILE
    before = read_lock(lock_path) or Lock(root=root)
    if before_writing is None:
        before_writing = _refuse_a_cycle(project_dir, root, the_store, git_cache, read, before)

    moving: set = set()
    if move is not None:
        named = list(move)
        try:
            moving = {
                locate_pipeline(name, dependencies=dependencies).id for name in named
            }
        except KeyError as error:
            raise LockError(
                f"{error.args[0]} `chartbook pin --update` takes the names of this "
                f"pipeline's dependencies."
            ) from None
        if not named:
            moving = set(dependencies)

    report = PinReport(lockfile=lock_path)
    after = Lock(root=root)
    kept_earlier: dict = {}  # the records of an earlier lockfile that stay in this one
    cache = hashing.HashCache()

    locked_before = {entry["id"] for entry in before.dependencies}
    for key in sorted(locked_before - set(dependencies)):
        if only is not None:
            # Only what was asked is looked at: the rest stays as it was
            gone = dict(next(entry for entry in before.dependencies if entry["id"] == key))
            stays = still_pinned(before.earlier_of(key), gone, store, snapshots_in_store) if before.earlier else {}  # its folder is no longer declared
            had_gone = {**before.assets_of(key), **stays}
            if stays:
                records = [v for v in had_gone.values() if isinstance(v, dict) and v.get("content_hash")]
                if records:
                    gone["pinned_hash"] = pinned_hash(records)
            after.dependencies.append(gone)
            after.assets.update(had_gone)
            kept_earlier.update(stays)
            continue
        report.events.append(PinEvent("removed", key))

    locked = {entry["id"]: entry for entry in before.dependencies}
    for key in sorted(dependencies):
        entry = dependencies[key]
        may_move = key in moving
        had = before.assets_of(key)
        stays = {}
        if before.earlier:
            # What an earlier lockfile held of it that this one does not: one that
            # nothing else names stays a pin, as it was (still_pinned)
            stays = still_pinned(before.earlier_of(key), locked.get(key), store, snapshots_in_store, entry.get("_resolved_path"))
            had = {**had, **stays}
            kept_earlier.update(stays)
        if only is not None and key not in only:
            if key in locked:
                kept_entry = dict(locked[key])
                if stays:
                    records = [v for v in had.values() if isinstance(v, dict) and v.get("content_hash")]
                    if records:
                        kept_entry["pinned_hash"] = pinned_hash(records)
                after.dependencies.append(kept_entry)
                after.assets.update(had)
            continue
        # A label's record is pinned from a snapshot and only from one; a
        # pin from a repository lets go of any it had
        had_labels = {k: v for k, v in had.items() if (v.get("ref") or {}).get("rev")}
        had_assets = {k: v for k, v in had.items() if k not in had_labels}
        was = locked.get(key)
        report.pipelines[key] = pinned_pipeline(was)  # as the entry names it: with no name, the whole store is asked
        kept_as_it_is = False
        chosen = None  # the snapshot a `rev` walked back to
        rev_failure = None
        if entry.get("_store"):
            if host is None:
                from chartbook.config import get_default_host

                host = get_default_host()
            was_location = (was or {}).get("location", {})
            has_bytes = holds_a_pin(was, had)
            from_repository = (
                has_bytes and was_location.get("kind") == "git" and was_location.get("pipeline") == entry["_store"]
            )
            if entry.get("rev") and entry["_store"] in set(built_here):
                rev_failure = (
                    f"rev = {entry['rev']!r} is not followed for {entry['_store']}, which this run builds "
                    f"itself from its folder: build this pipeline outside the catalog's run (`chartbook run` "
                    f"in its folder), which pins and builds what the rev names, or leave out its rev"
                )
            elif entry.get("rev"):
                if not clone_missing:
                    rev_failure = f"rev = {entry['rev']!r} is resolved by `chartbook pin`, which asks its repository"
                else:
                    if git_cache is None:
                        git_cache = default_git_cache()
                    kind, value = choose_for_rev(
                        entry, root, was, may_move, snapshots_in_store, host, git_cache, project_dir, pinned=has_bytes
                    )
                    if kind == "entry":
                        entry = value
                    elif kind == "snapshot":
                        chosen = value
                    else:
                        rev_failure = value
            elif clone_missing:
                entry = clone_instead(entry, root, was, may_move, snapshots_in_store, host, built_here, pinned=has_bytes)
            if from_repository and "git" not in entry and chosen is None and rev_failure is None and (
                not may_move
                or (not host and not store_has_for(entry, snapshots_in_store, was_location.get("first_commit"), True))
            ):
                # Pinned from its repository, and that repository is not to be
                # asked here (no default host, a read, or a pipeline this run
                # builds itself), nor has the store anything to take instead:
                # the pin stays as it is
                kept_as_it_is = True
        listed = _dependency_entry(key, entry)
        commit_moved = False

        if rev_failure is not None:
            # What `rev` means could not be asked, or what it means is not to be taken
            pinned_now = holds_a_pin(was, had)
            was_location = (was or {}).get("location", {})
            recorded = was_location.get("pipeline") == entry.get("_store") and (
                was_location.get("commit") or was_location.get("first_commit")
            )
            if was is not None and (pinned_now or recorded):
                records = dict(had)
                listed = {**was, "location": dict(was.get("location", {}))}
                for asset_id, record in sorted(had.items()):
                    _report_kept(record, key, store, report)
            else:
                records = {}
            if may_move or not pinned_now:
                report.events.append(PinEvent("no_snapshot", key, detail=rev_failure))
        elif kept_as_it_is:
            records = dict(had)
            if _declared_elsewhere(was, listed):
                report.events.append(PinEvent("relocated", key, detail=_describe(listed["location"])))
            listed = {**was, "location": dict(was["location"])}
            report.git.add(key)
            for asset_id, record in sorted(had.items()):
                content_hash = record.get("content_hash")
                if not content_hash:
                    continue
                if store.has(content_hash, report.pipelines.get(key)):
                    unsynced = _incomplete(store, record, report.pipelines.get(key))
                    report.events.append(
                        PinEvent("unsynced", key, asset_id, old=content_hash, new=content_hash, detail=unsynced)
                        if unsynced
                        else PinEvent("kept", key, asset_id, old=content_hash, new=content_hash)
                    )
                else:
                    report.events.append(
                        PinEvent(
                            "lost", key, asset_id, old=content_hash,
                            detail=(
                                "it was pinned from its repository, which is not asked here"
                                + ("" if host else ": no [resolve] default_host is set")
                            ),
                        )
                    )
        elif (
            "git" in entry
            and not entry.get("_from_id")
            and not may_move
            and (was or {}).get("location", {}).get("kind") in ("path", "store")
            and holds_a_pin(was, had)
        ):
            if _declared_elsewhere(was, listed):
                report.events.append(PinEvent("relocated", key, detail=_describe(listed["location"])))
            for asset_id, record in sorted(had.items()):
                if record.get("content_hash"):
                    _report_kept(record, key, store, report)
                else:
                    report.events.append(
                        PinEvent("not_built", key, asset_id, detail=record.get("missing") or "not built when it was pinned")
                    )
            records = dict(had)
            listed = {**was, "location": dict(was["location"])}
            listed = {k: v for k, v in listed.items() if k != "pinned_hash"}
            overall = pinned_hash(records.values())
            if overall is not None:
                listed["pinned_hash"] = overall
            after.dependencies.append(listed)
            after.assets.update(records)
            continue
        elif "git" in entry:
            if git_cache is None:
                git_cache = default_git_cache()
            directory, listed, failure = _fetch(
                key, entry, was, listed, may_move, project_dir, git_cache, report
            )
            # Fetched at a commit of its own, not kept at the one it was pinned at
            fetched_now = listed is not was
            report.git.add(key)
            if entry.get("_from_id"):
                source = f"{strip_url_credentials(entry['git'])} ({entry.get('_from', '[resolve] default_host')})"
                if any(record.get("content_hash") for record in had.values()) and (was or {}).get("location", {}).get("kind") == "git":
                    why = f"it was pinned from its repository, {source}"
                else:
                    at = f" at {entry['rev']}" if entry.get("rev") else ""
                    why = f"the store has no snapshot of {entry['_from_id']}{at}, so it is got from its repository, {source}"
                if failure:
                    failure = f"{why}: {failure}"
                elif directory is not None:
                    named = _project_id_in(Path(directory))
                    commit = listed.get("location", {}).get("commit")
                    # Which repository it is, by its first commit: the one it was
                    # pinned from, in the store or its repository, unless the entry
                    # names the repository to take
                    url = local_url(entry["git"], project_dir)
                    first = _first_commit_of(git_cache, url, commit) if commit else ""
                    # What the pin recorded of its repository, when it was this same
                    # pipeline and the entry does not name the repository to take
                    pinned_at = (was or {}).get("location", {})
                    same = pinned_at.get("pipeline") == entry["_from_id"] and not entry.get("_repository")
                    recorded = pinned_at.get("first_commit") if same else None
                    pinned_commit = pinned_at.get("commit") if same else None
                    way_out = (
                        f"To take it, name it with repository = \"...\" in its [dependencies] entry, or remove "
                        f"{key!r} from chartbook.lock and run `chartbook pin --update {key}`"
                    )
                    if named and named != entry["_from_id"]:
                        said = named if named.startswith(("a [project]", "an id ")) else f"the ID {named}"
                        failure = f"{why}, and that repository's chartbook.toml gives {said}, not {entry['_from_id']}"
                    elif first and recorded and first != recorded:
                        failure = (
                            f"{why}, and that repository's history begins at {first[:7]}, not at {recorded[:7]} as the "
                            f"one it was pinned from: another repository, or its history rewritten. {way_out}"
                        )
                    elif not recorded and pinned_commit and not _has_commit(git_cache, url, pinned_commit, fetch=True):
                        # Nothing of its first commit was recorded (a snapshot from a
                        # shallow clone): the commit it was pinned at must be in this one
                        failure = (
                            f"{why}, and that repository does not have {pinned_commit[:7]}, the commit it was "
                            f"pinned at, on any branch or tag or by its hash: another repository, or that commit "
                            f"gone from it. {way_out}"
                        )
                    elif first:
                        listed = {**listed, "location": {**listed["location"], "first_commit": first}}
                    if failure:
                        directory = None
                        # Nothing of a refused clone is recorded: not its commit either
                        listed = was if was is not None else _dependency_entry(key, entry)
            if directory is None and listed is was and (was or {}).get("location", {}).get("kind") == "store":
                # Not got from its repository: the store pin stays as it was, labels and all
                report.git.discard(key)
                lost = any(r.get("content_hash") and not store.has(r["content_hash"], report.pipelines.get(key)) for r in had.values())
                if may_move or not any(r.get("content_hash") for r in had.values()) or lost:
                    report.events.append(PinEvent("unfetched", key, detail=failure))
                for asset_id, record in sorted(had.items()):
                    if record.get("content_hash"):
                        _report_kept(record, key, store, report)
                    else:
                        report.events.append(
                            PinEvent("not_built", key, asset_id, detail=record.get("missing") or "not built when it was pinned")
                        )
                records = dict(had)
                listed = {**was, "location": dict(was["location"])}
                listed = {k: v for k, v in listed.items() if k != "pinned_hash"}
                overall = pinned_hash(records.values())
                if overall is not None:
                    listed["pinned_hash"] = overall
                after.dependencies.append(listed)
                after.assets.update(records)
                continue
            commit_was = (was or {}).get("location", {}).get("commit")
            commit_now = listed.get("location", {}).get("commit")
            commit_moved = bool(commit_was and commit_now and commit_was != commit_now)
            pinned = any(record.get("content_hash") for record in had.values())
            lost = failure is not None and any(
                record.get("content_hash") and not store.has(record["content_hash"], report.pipelines.get(key)) for record in had.values()
            )
            if failure and (may_move or not pinned or lost):
                # With pins in the store and nothing asked to move, a
                # repository that cannot be reached is no trouble: that is
                # what the pins are for
                report.events.append(PinEvent("unfetched", key, detail=failure))
            # A repository is only read. Nothing it declares may reach
            # outside its own files.
            records = _sync_dependency(
                key, directory, had_assets, may_move, store, cache, report, commit_moved,
                within=directory,
            )
            if directory is not None and (fetched_now or records != had_assets):
                # The pipeline its copy holds, by its own ID, whatever the key:
                # when it was fetched again, or something in it was pinned
                of_clone = _pipeline_of_clone(Path(directory), entry, project_dir)
                listed = {k: v for k, v in listed.items() if k != "pinned_from"}
                if of_clone:
                    listed["pinned_from"] = of_clone
            for asset_id, record in sorted(had_labels.items()):
                # A git dependency has no versions: a label pinned while this
                # was a path dependency is let go
                report.events.append(
                    PinEvent(
                        "let_go", key, asset_id, old=record.get("content_hash"),
                        detail="a git dependency has no versions, so none of its labels is pinned",
                    )
                )
        elif entry.get("_store") == root or (
            entry.get("_resolved_path") and _same_directory(entry["_resolved_path"], project_dir)
        ):
            records = {}
            itself = f"{project_dir}, this pipeline's own folder" if entry.get("_resolved_path") else f"{root}, this pipeline itself"
            report.events.append(
                PinEvent("no_snapshot", key, detail=f"{key!r} is {itself}: a pipeline cannot depend on itself")
            )
        elif entry.get("_store"):
            # Named by its ID alone: its snapshots are found in the store by
            # that ID, with no folder of it here and no clone. It keeps to the
            # repository the manifest names, or else the one it was first
            # pinned from
            pinned_from = (was or {}).get("location", {})
            if pinned_from.get("pipeline") != entry["_store"]:
                pinned_from = {}  # another pipeline then: nothing of its repository carries over
            elif pinned_from.get("kind") == "git":
                # Pinned from its repository: an update keeps to that repository's snapshots
                pinned_from = {"first_commit": pinned_from.get("first_commit")} if pinned_from.get("first_commit") else {}
            elif not (pinned_from.get("kind") == "store" and pinned_from.get("commit")):
                pinned_from = {}
            named = bool(entry.get("_repository"))
            # The repository the manifest names, by its address alone; or
            # the one it was first pinned from, by address or first commit
            repository = entry["_repository"] if named else (pinned_from.get("repository") or None)
            first_commit = None if named else (pinned_from.get("first_commit") or None)
            records, listed = _sync_from_snapshots(
                key, None, was, listed, had, may_move, store, report,
                newest_of=(lambda chosen=chosen: (chosen[0], "", chosen[1])) if chosen is not None else (
                    lambda entry=entry, repository=repository, first_commit=first_commit, named=named: _newest_in_store(
                        entry["_store"], entry.get("commit"), store, repository,
                        found=snapshots_in_store(), first_commit=first_commit, named=named,
                    )
                ),
                found=snapshots_in_store,
                declared=entry,
            )
        else:
            records, listed = _sync_from_snapshots(
                key, Path(entry["_resolved_path"]), was, listed, had, may_move, store, report,
                found=snapshots_in_store,
            )
        listed = {k: v for k, v in listed.items() if k != "pinned_hash"}
        overall = pinned_hash(records.values())
        if overall is not None:
            listed["pinned_hash"] = overall
        after.dependencies.append(listed)
        after.assets.update(records)

    if before_writing is not None:
        refused = before_writing(after)
        if refused:
            report.refused = refused
            store.forget_held(report)
            return report
        store.put_held(after, report)
        store = the_store

    # With nothing to lock and no lockfile yet, do not make an empty one; nor
    # for a pin of some dependencies only (the first read of one) that found
    # nothing of them to record: no asset, and no snapshot taken
    if lock_path.exists() or (
        dependencies and (only is None or after.assets or any(names_a_snapshot(entry) for entry in after.dependencies))
    ):
        report.written = write_lock(after, lock_path)
        if report.written and before.read_as != SCHEMA:
            # A lockfile of an earlier version, written again once in this one
            report.earlier, report.left_out = before.read_as, _left_out(before, set(after.assets))
            report.kept_earlier = sum(1 for asset_id in kept_earlier if asset_id in after.assets)
        if report.written:
            # Said when pins are made or moved, and when an earlier lockfile is written again: never by a pin that changes nothing
            report.without_rows = pinned_before_rows(after, before, report.snapshots)
            report.rows_now = rows_pinned_now(after, before)
            report.not_hashed_now = rows_not_hashed_now(after, before)
    noted_as = _noted_as()
    try:
        # A snapshot it names is kept too, with what the lockfile does not hold of it;
        # and what every local branch and tag of its clone pins (:func:`write_note`)
        write_note(lock_path, after, store, machine=noted_as)
    except (OSError, StoreError) as error:
        from chartbook.config import without_credentials

        # What the system says names the store's path, which may carry a password (//user:pw@host)
        said = without_credentials(str(error))
        if not is_read_only(error):
            raise LockError(
                f"{lock_path} was written, and the store's note of it for `gc` "
                f"could not be: {said.rstrip('.')}. The pins are in the store and the lockfile "
                f"names them; `chartbook pin` again, once the store can be written, "
                f"leaves the note."
            ) from None
        # A store that is read-only for this user: the pins are in it, the
        # lockfile names them, and only the note for `gc` is missing
        report.unrooted = said
    if lock_path.exists() and (report.written or before.read_as == SCHEMA):
        # The lockfile is of this version, which a ChartBook before SINCE cannot read: a manifest that
        # says which one it needs is to say so too, whether the lockfile was written just now or before.
        # Last, so that nothing that stops a pin leaves a manifest written and unsaid
        report.floor = see_to_the_floor(project_dir, write=raise_floor)
    return report


def label_remedy(missing: Optional[str], key: str) -> str:
    """What puts bytes behind a label pinned without them, given why it was."""
    if "share that start" in (missing or ""):
        return f"its owner gives the label more digits of the hash, and makes a snapshot; then `chartbook pin --update {key}`"
    return f"when its owner has made a snapshot that holds that version, `chartbook pin --update {key}`"


def is_read_only(error: Exception) -> bool:
    """Whether an error says the store could not be written for want of permission.

    A folder store raises an ``OSError`` for that; a remote store a
    :class:`chartbook.store.ReadOnlyStoreError`.
    """
    if isinstance(error, ReadOnlyStoreError):
        return True
    return isinstance(error, OSError) and (
        isinstance(error, PermissionError) or error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    )


@dataclass
class FrozenProblem:
    """One reason a pipeline cannot be built from its lockfile alone.

    Attributes:
        dependency: The dependency's key in ``[dependencies]``; empty when
            the problem is the lockfile itself.
        asset: The asset's ID, or None when it is about the dependency.
        message: What is wrong, and what to run.
        kind: ``"not_built"`` for an asset pinned without bytes because the
            other pipeline had not built it (or a label, or a table, that
            came without them): nothing can have read it. ``"nothing_pinned"``
            for a dependency with no asset in the lockfile, which may be one
            that declares none. ``"not_in_store"`` for a pin from a snapshot
            whose bytes the store does not have, with no build of yours of
            that commit to compare (said once for its dependency:
            :attr:`FrozenReport.not_in_store`). ``"differs"`` for a
            dependency whose pins a build of yours of that commit does not
            meet. Empty otherwise.
    """

    dependency: str
    asset: Optional[str]
    message: str
    kind: str = ""


@dataclass
class FrozenReport:
    """What :func:`verify` found: whether every pin can be had, with nothing written but a note for ``store gc``.

    Attributes:
        lockfile: The lockfile's path.
        dependencies: How many dependencies the manifest declares.
        pins: How many pinned assets are in the store.
        problems: Everything that stands in the way, in order.
        noted: Whether the store's note of this lockfile on this machine
            was written now, to name what it pins (:func:`note_this_machine`).
        unrooted: Why that note could not be written, when it could not.
        earlier: The version the lockfile is in, when it is an earlier one
            than this version writes (:data:`READS`): it is checked as this
            version would have written it. Empty otherwise.
        left_out: What that earlier lockfile holds that this version does
            not, and that was therefore not checked, by the plural of the
            kind (:attr:`Lock.left_out`).
        stood_in: The dependencies whose pinned bytes the store does not
            all have, and that a snapshot of yours of the pinned commit
            stands in for, each with how it meets every pin
            (:class:`chartbook.standins.Found`), by key.
        by_entry: How many dependencies are pinned by their entry alone,
            none of their assets being in the lockfile, with a snapshot of
            the commit it names in the store.
        not_in_store: For each dependency with pins from a snapshot that
            the store does not have, and no build of yours of that commit
            to compare: what to say of it once, in lines
            (:func:`not_in_store_said`). Each such pin is a problem of
            kind ``"not_in_store"`` as well.
        kept_earlier: How many records of an earlier lockfile that this
            version would leave out are checked all the same, as the pins
            they stay when it is written again (:func:`still_pinned`).
        passed_over: How many records such a lockfile kept, written again
            on another machine, that this store does not have the bytes
            of: no pins here, and read as any asset a lockfile does not
            hold.
    """

    lockfile: Path
    dependencies: int = 0
    pins: int = 0
    problems: list[FrozenProblem] = field(default_factory=list)
    noted: bool = False
    unrooted: str = ""
    earlier: str = ""
    left_out: dict = field(default_factory=dict)
    by_entry: int = 0
    kept_earlier: int = 0
    passed_over: int = 0
    stood_in: dict = field(default_factory=dict)
    not_in_store: dict = field(default_factory=dict)

    @property
    def by_your_build(self) -> int:
        """How many pins are met by a snapshot of yours and not by the pinned bytes."""
        return sum(met.record is not None for stood in self.stood_in.values() for met in stood.met.values())


def your_build(entry: dict, assets: dict, store: Store, snapshots: Callable[[], list], folder: Optional[Union[str, Path]] = None):
    """What a snapshot of yours makes of a dependency of which the store does not have a pinned file (:mod:`chartbook.standins`).

    None when the store has every pinned file of it, which is the cheapest
    check and reads nothing (one it has in part is on its way, and is said
    so). None when the store has the snapshot the lockfile names: that one
    is the pin, and what the store lacks of it is lost, or not synced yet.
    And None when the store has no other snapshot of that pipeline at the
    pinned commit to compare, so that what is said is that the bytes are
    not there. Else what was found: the snapshot that stands in, or the
    newest that does not, with why.

    :param snapshots: Gives the store's snapshots; asked only if needed.
    :param folder: The folder of a ``path`` dependency, as the manifest
        resolves it (:func:`pinned_pipeline`).
    """
    from chartbook import standins

    if not from_a_snapshot(entry):
        return None  # pinned from its repository: its bytes are its commit's, and `chartbook pin` puts them back
    absent = [
        record for record in assets.values()
        # One kept of an earlier lockfile is a pin only where its bytes are (still_pinned)
        if record.get("content_hash") and not store.has(record["content_hash"], pinned_pipeline(entry)) and in_lockfile(record)
    ]
    if not absent:
        return None
    try:
        found = standins.find(entry, assets, store, snapshots(), folder)
    except (OSError, StoreError, snapshot.SnapshotError):
        return None  # a store that cannot be read now: said as bytes that are not there
    return found if found.snapshot is not None else None


def build_it_said(entry: Optional[dict]) -> str:
    """How to build a dependency yourself, at the commit its pin names, where the store does not have what was pinned.

    Empty for one pinned from its repository, whose bytes are its
    commit's and are put back by ``chartbook pin``, and for a pin that
    names no commit.
    """
    import re

    from chartbook.identity import plain_line, validate_pipeline_id, web_link

    location = (entry or {}).get("location")
    location = location if isinstance(location, dict) else {}
    commit = location.get("commit")
    if location.get("kind") not in ("store", "path") or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return ""
    # A lockfile is anyone's, and this is shown: a pipeline's name only if it is an ID, an address
    # only if it is a plain web address, and a path as one line of text
    pipeline, repository = location.get("pipeline"), web_link(location.get("repository"))
    try:
        pipeline = validate_pipeline_id(pipeline) if isinstance(pipeline, str) and pipeline == plain_line(pipeline) else ""
    except ValueError:
        pipeline = ""
    path = plain_line(location.get("path"), 300)
    # Named by its ID, it may be one folder of a repository of several: said, unless the
    # repository is named as the pipeline is, and so is its own
    of = ""
    if pipeline:
        named = repository.rstrip("/").rsplit("/", 1)[-1]
        named = named[:-4] if named.endswith(".git") else named
        if named != pipeline.rsplit("/", 1)[-1]:
            of = f", in the folder of {pipeline}"
    if location.get("kind") == "path" and path:
        where = f"in {path}"
    elif repository:
        where = f"in a clone of {repository}{of}"
    else:
        where = f"in a clone of its repository{of}"
    return (
        f"{where}, `git checkout {commit[:7]}` and `chartbook run --snapshot`: a build of yours meets a pin by "
        f"the same file or, for a dataframe, by the same rows up to the pin's last date"
    )


def one_to_move_to(entry: dict, folder: Optional[Union[str, Path]], store: Store, snapshots: Callable[[], list]) -> bool:
    """Whether ``chartbook pin --update`` would find a snapshot of a dependency other than the one it is pinned to, so that offering it is no false lead.

    For a dependency named by its folder, as ``update`` looks: the newest
    snapshot at the commit the folder is on, or before it
    (:func:`chartbook.snapshot.newest_for`); none where the folder is not
    on this machine. For one named by its ID, any other snapshot of its
    pipeline in the store.
    """
    location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    commit, made = location.get("commit"), entry.get("snapshot")
    if location.get("kind") == "path":
        if folder is None:
            return False
        try:
            newest, _ = snapshot.newest_for(folder, store)
        except (snapshot.SnapshotError, StoreError, OSError, ValueError):
            return False
        return newest is not None and not newest.same_moment(commit, made)
    theirs = pinned_pipeline(entry, folder)
    return any(taken.pipeline == theirs and not taken.same_moment(commit, made) for taken in snapshots())


def not_in_store_said(
    key: str, entry: dict, absent: list, pinned: int, store: Store, movable: bool = True, named_here: bool = False,
    in_part: Iterable[str] = (),
) -> list:
    """What ``pin --check`` says of a dependency whose pinned bytes the store does not have, with no build of yours to stand in: once for the dependency, and each way on in a line.

    :param movable: Whether the store has a snapshot of that pipeline for
        ``chartbook pin --update`` to move the pin to (:func:`one_to_move_to`);
        with none, it is not offered.
    :param named_here: Whether the store has the snapshot the pins are of
        (:func:`has_named`): then they are lost from it, or not synced yet,
        and no build of yours is read in their place.
    :param in_part: The pins of it whose file the store has in part. While
        there are any, no build is read in the place of the others: the
        store is taken to be on its way to having them.
    """
    one = len(absent) == 1
    commit = (entry.get("location") or {}).get("commit") or ""
    names = ", ".join(asset.split(":", 1)[-1] for asset in absent)
    counted = f"{len(absent)} of its {pinned} pin{'' if pinned == 1 else 's'} {'is' if one else 'are'} not in the store at {store}"
    if named_here:
        lines = [
            f"{counted}, which has the snapshot {'it is' if one else 'they are'} of: {names}",
            "  In a synced folder, wait for the sync to finish, here and on the machine that made the snapshot.",
            f"  Otherwise {'it is' if one else 'they are'} lost from the store: `chartbook snapshot` in its folder at "
            f"{commit[:7]} puts back a file that builds to the same bytes.",
        ]
        if movable:
            lines.append(f"  To move the pin to another snapshot the store has: chartbook pin --update {key}")
        return lines
    waiting = ", ".join(asset.split(":", 1)[-1] for asset in in_part)
    if waiting:
        # Said for what it is: a build of yours may well hold these, and is not read while the store is arriving
        lines = [f"{counted}, and no build is read in {'its' if one else 'their'} place while {waiting} is in the store in part: {names}"]
    else:
        lines = [f"{counted}, and no build of yours at {commit[:7]} stands in: {names}"]
    build = build_it_said(entry)
    if build:
        lines.append(f"  To build it yourself: {build}.")
        # This check fetches nothing, so it names what this pipeline lacks and no more
        lines.append("  What it reads in turn may not be in the store either: `chartbook run` lists all there is to build, in order.")
    lines.append(
        f"  Where a store is shared: point CHARTBOOK_STORE at the one that has {'it' if one else 'them'}; in a "
        f"synced folder, wait for the sync to finish, here and on the machine that made the pin."
    )
    if movable:
        lines.append(f"  To move the pin to a snapshot the store has: chartbook pin --update {key}")
    return lines


def index_column_said(assets: list) -> str:
    """What to say of tables of yours that do not meet a pin and have the column pandas makes of an index with no name: it may be the whole difference."""
    from chartbook import rowhash

    return (
        f"{', '.join(assets)}: has the column pandas makes of an index with no name "
        f"({rowhash.INDEX_COLUMN}), which may be the whole difference: where it holds row positions, they "
        f"shift when a pull has more rows. Its owner drops it with to_parquet(index=False), or keeps it "
        f"under a name with reset_index()"
    )


def read_yours_said(key: str, stood) -> str:
    """The way on from a build of yours that does not match a pin: ``chartbook pin --update`` reads it instead; empty where only versions pinned by a label are unmet, which no update finds in your build."""
    if all(unmet.label for unmet in stood.unmet):
        return ""
    return f"To read your build instead: chartbook pin --update {key}"


def does_not_match(key: str, stood) -> str:
    """What to say of a dependency whose pins a snapshot of yours does not meet: each asset and where it differs, and the way on."""
    from chartbook import standins

    lines = [f"your build of {standins.build_said(stood.snapshot)}, does not match the pin"]
    for unmet in stood.unmet:
        lines.append(f"  {unmet.asset.split(':', 1)[-1]}: {unmet.why}")
    with_index = [unmet.asset.split(":", 1)[-1] for unmet in stood.unmet if unmet.index_column]
    if with_index:
        lines.append(f"  {index_column_said(with_index)}")
    if read_yours_said(key, stood):
        lines.append(f"  {read_yours_said(key, stood)}")
    return "\n".join(lines)


def _noted_as() -> Optional[str]:
    """The name this machine's notes of its lockfiles go under: None for its own, or ``""``, the path alone, under CI with no ``CHARTBOOK_MACHINE_ID``.

    A runner with a fresh home each run would have a new name each run,
    and leave a note under each, which no machine could forget. Under the
    path alone, as notes were named before they named machines, each run
    at the same checkout path replaces the last one's note; and ``store
    gc`` on a runner whose store lasts reads its lockfile, so that what its
    own checkout pins is kept. Runners given one ``CHARTBOOK_MACHINE_ID``
    replace their note under that name.
    """
    from chartbook.config import MACHINE_ENV_VAR

    if os.environ.get("CI", "").strip().lower() not in ("", "0", "false") and not os.environ.get(MACHINE_ENV_VAR, "").strip():
        return ""
    return None


def note_this_machine(lock_path: Path, locked: Lock, store: Store) -> tuple[bool, str]:
    """Make the store's note of a lockfile on this machine name what it pins now, as a pin does.

    A machine that only reads (``run --frozen``, a read through the lockfile)
    is kept this way: ``store gc`` on another machine keeps what a note
    records, and would otherwise know nothing of this one's pins. The note
    is replaced with what the lockfile pins now (and what every local branch
    and tag of its clone pins: :func:`write_note`), as ``pin`` and ``update``
    replace it, so a reader's note follows its pulls; nothing is written
    when it says that already.

    Under CI with no ``CHARTBOOK_MACHINE_ID``, the note names the path
    alone (:func:`_noted_as`), as a pin's does.

    :returns: Whether the note was written now, and why it could not be
        (a store that is read-only for this user, say); empty if it could.
    """
    from chartbook.config import without_credentials

    noted_as = _noted_as()
    try:
        pins = pins_for_note(lock_path, locked)
        wrote = _put_note(store, lock_path, pins, noted_as, if_changed=True)
    except Exception as error:  # noqa: BLE001 - a note is best effort, whatever the store raised
        return False, without_credentials(str(error))
    return wrote, ""


@dataclass
class NotePins:
    """What a store's note of a lockfile should hold.

    Attributes:
        hashes: Content hashes to keep.
        snapshots: Snapshot pins, each ``(pipeline, commit, made_at)``.
        labelled: Model versions pinned by label.
        complete: Whether every local branch and tag tip answered (lockfile
            resolved or clearly absent). True also when the project is not
            in a git clone. False means merge into the note that is there;
            True means replace it.
        keep_newest: Whether a note that already keeps the newest snapshot
            holding each of its objects must go on doing so. Set only when
            merging a partial answer into such a note.
    """

    hashes: set[str] = field(default_factory=set)
    snapshots: set[tuple[str, str, str]] = field(default_factory=set)
    labelled: set[tuple[str, str, str, str]] = field(default_factory=set)
    complete: bool = True
    keep_newest: bool = False


def pins_for_note(lock_path: Path, locked: Lock) -> NotePins:
    """What the store's note of *lock_path* should name: this lockfile's pins, and what every local branch and tag pins.

    In a git clone, each tip of ``refs/heads`` and ``refs/tags`` is asked
    for the lockfile at the same path relative to the repository top
    (``git show <tip>:…/chartbook.lock``). Only the snapshot that tip's
    lockfile names is taken: no other snapshot of its commit. Where every
    tip answered (the lockfile resolved or was clearly absent), the note
    may replace what it held; where any tip failed, the answer is partial
    and must be merged into the note that is there so pins are not dropped.

    Outside a clone, only this lockfile's pins are returned, and the note
    may replace.
    """
    pins = NotePins(
        hashes=set(locked.hashes()),
        snapshots=set(locked.snapshots()),
        labelled=set(locked.labelled()),
        complete=True,
    )
    try:
        code = snapshot.code_of(lock_path.parent)
    except snapshot.NotInARepository:
        return pins
    except snapshot.SnapshotError:
        # Git could not say where the folder is: keep what we have, and merge
        pins.complete = False
        return pins
    relative = f"{code.subdirectory}/{LOCK_FILE}" if code.subdirectory else LOCK_FILE
    try:
        tips = snapshot._git(code.top, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/tags")
    except snapshot.SnapshotError:
        pins.complete = False
        return pins
    for tip in set(tips.split()):
        found, status = _lockfile_at_tip(code.top, tip, relative)
        if status == "failed":
            pins.complete = False
            continue
        if found is None:
            continue  # clearly absent at that tip: answered
        pins.hashes |= found.hashes()
        pins.snapshots |= found.snapshots()
        pins.labelled |= found.labelled()
    return pins


def _lockfile_at_tip(top: Path, tip: str, relative: str) -> tuple[Optional[Lock], str]:
    """The lockfile at *relative* on *tip*, and whether git answered: ``ok``, ``absent``, or ``failed``."""
    try:
        text = snapshot._git(top, "-c", "i18n.logOutputEncoding=UTF-8", "show", f"{tip}:{relative}")
    except snapshot.SnapshotError as error:
        said = str(error).lower()
        # Git's words when the path is not in that commit: a clear answer, not a failure
        if "does not exist" in said or "exists on disk" in said or "not in '" in said or 'not in "' in said:
            return None, "absent"
        try:
            listed = snapshot._git(top, "ls-tree", "--", tip, relative)
        except snapshot.SnapshotError:
            return None, "failed"
        if not listed.strip():
            return None, "absent"
        return None, "failed"
    try:
        return _lock_from_text(text), "ok"
    except LockError:
        return None, "failed"


def _lock_from_text(text: str) -> Lock:
    """A lockfile as :func:`read_lock` would give it, from the text ``git show`` printed."""
    try:
        document = json.loads(text)
    except (ValueError, TypeError) as error:
        raise LockError(f"Cannot read lockfile text: {error}") from None
    return _lock_from_document(document, "git show")


def _writable_stores(store):
    """Every store a note may be written to: this one, or each writable store of a catalog."""
    listed = getattr(store, "writable_stores", None)
    if listed is None:
        return [store]
    return list(listed())


def _note_targets(store, hashes, snapshots):
    """The stores among :func:`_writable_stores` that a note of these pins is written to."""
    listed = getattr(store, "note_targets", None)
    if listed is None:
        return [store]
    return list(listed(hashes, () if snapshots is None else snapshots))


def _same_pins(root, pins: NotePins) -> bool:
    """Whether *root* already records *pins*, including the newest-holder rule."""
    if root is None or set(root.hashes) != set(pins.hashes):
        return False
    if set(root.labelled or ()) != set(pins.labelled):
        return False
    if root.keeps_newest() != bool(pins.keep_newest):
        return False
    held = set() if root.snapshots is None else set(root.snapshots)
    return held == set(pins.snapshots)


def _put_note(store, lock_path: Path, pins: NotePins, machine: Optional[str], *, if_changed: bool) -> bool:
    """Write *pins* onto each store that should hold the note. A partial answer is merged per store.

    Hashes and listed snapshots are the union of the answer and every note
    already held, so one store's pins are not dropped from another's. A note
    that keeps the newest snapshot of each object keeps doing so on that
    store: the snapshots the partial answer saw are recorded beside that
    rule, and a store whose note already listed its snapshots is not given
    the rule. A complete answer replaces every target note.

    :param if_changed: Whether a note that already says this is left as it is.
    :returns: Whether a note was written or removed.
    """
    wrote = False
    pairs = []
    first_error = None
    for one in _writable_stores(store):
        try:
            pairs.append((one, one.root_of(lock_path, machine=machine)))
        except (StoreError, OSError) as error:
            if first_error is None:
                first_error = error
    roots = [root for _, root in pairs if root is not None]
    if pins.complete or not roots:
        merged_hashes = set(pins.hashes)
        merged_snaps = set(pins.snapshots)
        merged_labels = set(pins.labelled)
    else:
        # A partial answer must not drop pins any of these notes already held
        merged_hashes = set(pins.hashes).union(*(root.hashes for root in roots))
        merged_snaps = set(pins.snapshots).union(*(set(root.snapshots) for root in roots if root.snapshots is not None))
        merged_labels = set(pins.labelled).union(*(set(root.labelled) for root in roots if root.labelled is not None))
    if not merged_hashes and not merged_snaps:
        if pins.complete:
            for one, before in pairs:
                if before is not None:
                    try:
                        if one.remove_root(lock_path, machine=machine):
                            wrote = True
                    except (StoreError, OSError) as error:
                        if first_error is None:
                            first_error = error
        if first_error is not None:
            raise first_error
        return wrote
    targets = {id(one) for one in _note_targets(store, merged_hashes, merged_snaps)}
    for one, before in pairs:
        if id(one) not in targets:
            if pins.complete and before is not None:
                with contextlib.suppress(StoreError, OSError):
                    if one.remove_root(lock_path, machine=machine):
                        wrote = True
            continue
        # Only the note that had the rule keeps it. A complete answer replaces the note.
        this_newest = (
            not pins.complete and before is not None and before.keeps_newest()
        )
        merged = NotePins(
            hashes=merged_hashes, snapshots=merged_snaps, labelled=merged_labels,
            complete=pins.complete, keep_newest=this_newest,
        )
        if if_changed and _same_pins(before, merged):
            continue
        # No list and the rule: leave the list out, as the note was written. A list and the rule: record both.
        snaps = None if this_newest and not merged_snaps else merged_snaps
        try:
            one.add_root(
                lock_path, merged_hashes, snaps, machine=machine, labelled=merged_labels,
                keep_newest=this_newest and bool(merged_snaps),
            )
            wrote = True
        except (StoreError, OSError) as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
    return wrote


def write_note(lock_path: Path, locked: Lock, store: Store, machine: Optional[str] = None) -> None:
    """Write the store's note of a lockfile: what it pins, and what every local branch and tag of its clone pins.

    Replaces the note when git answered for the whole clone (or the project
    is not in one). Merges into the note that is there when the answer is
    partial, so pins are not dropped, and a note that keeps the newest
    snapshot of each object goes on doing so. Removes the note when nothing
    is pinned.
    """
    pins = pins_for_note(lock_path, locked)
    noted_as = _noted_as() if machine is None else machine
    _put_note(store, lock_path, pins, noted_as, if_changed=False)


def verify(project_dir: Union[str, Path] = ".", store: Optional[Store] = None, note: bool = False) -> FrozenReport:
    """Say whether a pipeline can be built from its lockfile alone.

    This is ``pin --check``, and the gate ``run --frozen`` passes before it
    builds: what CI runs, and what anyone with a store they may only read
    runs. It opens no repository, fetches nothing, pins nothing and does
    not write the lockfile. It reads the manifest's
    ``[dependencies]``, the lockfile and the store, and reports a problem
    for

    - a lockfile that is not there while the manifest has dependencies;
    - a dependency in the manifest and not in the lockfile, or in the
      lockfile and no longer in the manifest, or pinned from one place
      while the manifest now says another;
    - a dependency with nothing pinned: no asset of it, and no snapshot
      named for what the lockfile does not hold of it (:func:`in_lockfile`);
    - an asset that was declared and not built when it was pinned;
    - a pinned asset that the store does not have.

    The stricter choice the design kept for this check: where ``pin``
    records an unbuilt asset and goes on, ``verify`` counts it a problem,
    since the build that follows may need it.

    :param project_dir: The pipeline's directory.
    :param store: The store the pins should be in; this user's by default.
    :param note: Whether to make the store's note of the lockfile on this
        machine name what it pins (:func:`note_this_machine`), so that
        ``store gc`` on another machine keeps it: the one thing ``run
        --frozen`` writes, and only when the note lacks something. ``pin
        --check`` passes False. Nothing is written without it.
    :returns: What was found. No problems means the build can go ahead.
    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        is there and cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    project_dir = Path(project_dir).resolve()
    _, dependencies = _read_pipeline(project_dir)
    from chartbook.multi_store import with_dependencies
    store = with_dependencies(project_dir, store)
    lock_path = project_dir / LOCK_FILE
    report = FrozenReport(lockfile=lock_path, dependencies=len(dependencies))
    locked = read_lock(lock_path)
    if locked is None:
        if dependencies:
            report.problems.append(
                FrozenProblem(
                    "",
                    None,
                    f"{lock_path} does not exist, and {MANIFEST_NAME} declares "
                    f"{len(dependencies)} dependenc{'y' if len(dependencies) == 1 else 'ies'}. "
                    f"Run `chartbook pin` and commit the lockfile.",
                )
            )
        return report
    if any(not isinstance(entry.get("id"), str) for entry in locked.dependencies):
        raise LockError(
            f"{lock_path} lists a dependency without an id. The file is not one "
            f"ChartBook wrote: restore it from git, or remove it and run `chartbook pin`."
        )
    if locked.read_as != SCHEMA:
        report.earlier, report.left_out = locked.read_as, dict(locked.left_out)
    kept_earlier: dict = {}
    entries = {entry["id"]: entry for entry in locked.dependencies}
    read: list = []

    def snapshots_in_store() -> list:
        """The store's snapshots, read once, and only if a pin's bytes are not in it."""
        if not read:
            read.append(snapshot.readable_snapshots(store)[0])
        return read[0]

    for key in sorted(dependencies):
        entry = entries.get(key)
        if entry is None:
            report.problems.append(
                FrozenProblem(key, None, "is in [dependencies] and not in the lockfile. Run `chartbook pin`.")
            )
            continue
        listed = _dependency_entry(key, dependencies[key])
        if _declared_elsewhere(entry, listed):
            report.problems.append(
                FrozenProblem(
                    key,
                    None,
                    f"is pinned from {_describe(entry.get('location', {}))} and "
                    f"[dependencies] now says {_describe(listed['location'])}. "
                    f"`chartbook pin --update {key}` follows it.",
                )
            )
        assets = locked.assets_of(key)
        if locked.earlier:
            # Checked as this version would write it: what stays a pin then is one now
            stays = still_pinned(locked.earlier_of(key), entry, store, snapshots_in_store, dependencies[key].get("_resolved_path"))
            assets = {**assets, **stays}
            kept_earlier.update(stays)
        # One whose assets are all drawn anew by every build has none in the
        # lockfile: its entry names the snapshot they are read from
        if not assets and not names_a_snapshot(entry):
            report.problems.append(
                FrozenProblem(key, None, "has nothing pinned. Run `chartbook pin`, and see what it says.", "nothing_pinned")
            )
        elif not assets and names_a_snapshot(entry):
            # Its entry is the whole of its pin: what is read of it is read
            # from a build of that commit, the one a read would take, so the store must have one
            commit = entry["location"]["commit"]
            if read_from(entry, snapshots_in_store(), dependencies[key].get("_resolved_path")):
                report.by_entry += 1
            else:
                report.problems.append(
                    FrozenProblem(
                        key, None,
                        f"is pinned to its snapshot at {commit[:7]}, with none of its assets in the lockfile, "
                        f"and the store at {store} has no snapshot of it at that commit to read them from. "
                        f"{NOT_SYNCED_YET}. Otherwise build that commit yourself (`chartbook run --snapshot` "
                        f"there), or `chartbook pin --update {key}` moves to a snapshot the store has.",
                    )
                )
        # Pinned bytes the store does not have, nor the snapshot they are of: a
        # snapshot of yours of that commit may hold the same rows, and stand in for it
        stood = your_build(entry, assets, store, snapshots_in_store, dependencies[key].get("_resolved_path"))
        in_part: list = []  # its pins whose file the store has in part
        if stood is not None and stood.stands_in:
            report.stood_in[key] = stood
        elif stood is not None:
            report.problems.append(FrozenProblem(key, None, does_not_match(key, stood), "differs"))
        for asset_id in sorted(assets):
            content_hash = assets[asset_id].get("content_hash")
            if content_hash and not in_lockfile(assets[asset_id]) and from_a_snapshot(entry) and not store.has(content_hash, pinned_pipeline(entry)):
                # A record kept of an earlier lockfile, for a store that had its bytes and no snapshot
                # to read it from (still_pinned): here it is no pin, and is read as any asset the
                # lockfile does not hold. No rebuild gives a chart's bytes again
                report.passed_over += 1
                continue
            if content_hash and stood is not None:
                if stood.stands_in:
                    report.pins += 1  # met: by its bytes in the store, or by your build
                    continue
                met = stood.met.get(asset_id)
                if met is None or met.record is not None:
                    continue  # its bytes are not in the store: its dependency's one line says what your build makes of it
            if not content_hash and assets[asset_id].get("label"):
                report.problems.append(
                    FrozenProblem(
                        key,
                        asset_id,
                        f"is a label pinned without its bytes: "
                        f"{assets[asset_id].get('missing') or 'the store could not supply the version it names'}. "
                        f"{label_remedy(assets[asset_id].get('missing'), key)[0].upper()}"
                        f"{label_remedy(assets[asset_id].get('missing'), key)[1:]}.",
                        "not_built",
                    )
                )
            elif not content_hash and assets[asset_id].get("location", {}).get("kind") in ("table", "query"):
                report.problems.append(
                    FrozenProblem(
                        key, asset_id, "is a table or query in a source and has no pinned copy: a pin from a "
                        "repository takes no table, and a snapshot writes one out only from a DuckDB file. "
                        "`chartbook snapshot` there, then `chartbook pin --update`.",
                        "not_built",
                    )
                )
            elif not content_hash:
                report.problems.append(
                    FrozenProblem(
                        key, asset_id, "was declared and not built when it was pinned. Build it there, declare it ready, and `chartbook pin --update`.",
                        "not_built",
                    )
                )
            elif not store.has(content_hash, pinned_pipeline(entry)):
                plain = False  # a pin from a snapshot, by its bytes: said once for its dependency
                if assets[asset_id].get("label"):
                    remedy = f"its owner makes a snapshot that holds that version again, and then `chartbook pin --update {key}`"
                elif entry.get("via") == "rev" and not entry.get("location", {}).get("url"):
                    remedy = (
                        "`chartbook pin`, where the store can be written and `[resolve] default_host` "
                        "is set, puts it back from its repository"
                    )
                elif entry.get("via") == "rev":
                    remedy = "`chartbook pin`, where the store can be written, puts it back from the repository"
                elif entry.get("location", {}).get("commit"):
                    # A build of yours stands in only where the store does not have the snapshot pinned
                    named_here = has_named(entry, snapshots_in_store(), dependencies[key].get("_resolved_path"))
                    build = "" if named_here else build_it_said(entry)
                    remedy = f"`chartbook pin --update {key}` moves to a snapshot the store has" + (
                        ", or `chartbook snapshot` in its folder at that commit makes it again" if named_here
                        else f"; or build it yourself, {build}" if build else ""
                    )
                    plain = True
                else:
                    # The pin names no commit (a lockfile changed by hand,
                    # or from before every pin came from a snapshot)
                    remedy = f"its owner's `chartbook snapshot` puts it back, then `chartbook pin --update {key}` pins it"
                report.problems.append(
                    FrozenProblem(
                        key,
                        asset_id,
                        f"is pinned at {content_hash[:19]}… and the store at {store} "
                        f"does not have it. {NOT_SYNCED_YET}. Otherwise point CHARTBOOK_STORE "
                        f"at the store that has it; or {remedy}.",
                        "not_in_store" if plain else "",
                    )
                )
            elif unsynced := _incomplete(store, assets[asset_id], pinned_pipeline(entry)):
                in_part.append(asset_id)
                report.problems.append(
                    FrozenProblem(key, asset_id, f"is pinned at {content_hash[:19]}…, and {unsynced}.")
                )
            else:
                report.pins += 1
        absent = [problem.asset for problem in report.problems if problem.dependency == key and problem.kind == "not_in_store"]
        if absent:
            pinned = sum(1 for record in assets.values() if record.get("content_hash"))
            # `chartbook pin --update` is a way on only where it would find a snapshot to move to
            folder = dependencies[key].get("_resolved_path")
            named_here = has_named(entry, snapshots_in_store(), folder)
            movable = one_to_move_to(entry, folder, store, snapshots_in_store)
            report.not_in_store[key] = not_in_store_said(key, entry, absent, pinned, store, movable, named_here, in_part)
    for key in sorted(set(entries) - set(dependencies)):
        report.problems.append(
            FrozenProblem(key, None, "is in the lockfile and no longer in [dependencies]. Run `chartbook pin`.")
        )
    if locked.read_as != SCHEMA:
        report.left_out, report.kept_earlier = _left_out(locked, set(kept_earlier)), len(kept_earlier)
    if note:
        report.noted, report.unrooted = note_this_machine(lock_path, locked, store)
    return report


def _declared_elsewhere(was: dict, now: dict) -> bool:
    """Whether a dependency's place in the manifest is not the one that was locked.

    The commit a ``git`` dependency resolved to is not part of where the
    manifest says it is, so it is left out of the comparison.
    """

    # A dependency named by its ID is the same dependency whether it was
    # pinned from the store or, with no snapshot there, from its repository
    # on the default host
    kinds = {was.get("location", {}).get("kind"), now.get("location", {}).get("kind")}
    if kinds == {"store", "git"} and was["location"].get("pipeline") and now["location"].get("pipeline"):

        def by_id(location: dict) -> tuple:
            return (
                location.get("pipeline"),
                location.get("at") or location.get("rev"),
                repository_key(location.get("repository")),
            )

        return by_id(was["location"]) != by_id(now["location"])

    # A dependency named by its ID records the repository its snapshot came
    # from; that is where the manifest says it is only when it names one.
    # Its first commit the manifest never names.
    named = "repository" in now.get("location", {}) and bool(was.get("location", {}).get("commit"))

    def declared(entry: dict) -> dict:
        location = {
            k: v for k, v in entry.get("location", {}).items()
            if k not in ("commit", "first_commit") and (named or k != "repository")
        }
        if "repository" in location:
            location["repository"] = repository_key(location["repository"])
        return location

    return declared(was) != declared(now)


def _where(record: dict) -> str:
    """Where an asset's record says it is: its path, or its table or query in a source."""
    location = record.get("location") or {}
    if location.get("kind") == "table":
        return f"table {location.get('identifier')} in source {location.get('source')!r}"
    if location.get("kind") == "query":
        return f"query in source {location.get('source')!r}"
    return str(location.get("path"))


def by_its_id(key: str, pinned: Optional[dict], found: Callable[[], list]) -> str:
    """The ``[dependencies]`` line that names a ``path`` dependency by its ID instead, for a message.

    The ID is the one its pinned snapshot carries, when the lockfile names
    a snapshot that *found* (the store's snapshots) has; otherwise a key
    with a scope is taken for the ID, and one without is given a place for it.

    :param pinned: The dependency's entry in the lockfile, if it has one.
    """
    location = (pinned or {}).get("location", {})
    pipeline_id = None
    if location.get("commit") and (pinned or {}).get("snapshot"):
        try:
            pipeline_id = next(
                (t.pipeline for t in found() if t.same_moment(location["commit"], pinned["snapshot"])), None
            )
        except (StoreError, snapshot.SnapshotError, OSError, ValueError):
            pipeline_id = None  # a store that cannot be read: the key is said instead
    if pipeline_id is None and "/" not in key:
        return f'"{key}" = {{ id = "<its ID>" }}'
    if pipeline_id is None or pipeline_id == key:
        return f'"{key}" = {{}}'
    return f'"{key}" = {{ id = "{pipeline_id}" }}'


def name_it_by_its_id(key: str, pinned: Optional[dict], found: Callable[[], list]) -> str:
    """What to say of a ``path`` dependency whose folder is not on this machine: how to name it so that it is read from the store."""
    return (
        f"A pipeline in another repository is named by its ID, and read from a store this machine "
        f"shares with the one it is on: {by_its_id(key, pinned, found)} in [dependencies]"
    )


def _describe(location: dict) -> str:
    """Where a dependency is, in a few words, for a message."""
    if location.get("kind") == "store":
        at = f" at {location['at']}" if location.get("at") else ""
        at += f" at {location['rev']}" if location.get("rev") else ""
        made_in = f", made in {location['repository']}" if location.get("repository") else ""
        return f"{location.get('pipeline')}{at}, from the store{made_in}"
    if location.get("kind") == "git":
        rev = f" at {location['rev']}" if location.get("rev") else ""
        if not location.get("url"):
            return f"{location.get('pipeline')}{rev}, from its repository"
        return f"{location['url']}{rev}"
    return str(location.get("path"))


def _fetch(
    key: str,
    entry: dict,
    was: Optional[dict],
    listed: dict,
    may_move: bool,
    project_dir: Path,
    git_cache: GitCache,
    report: PinReport,
) -> tuple[Optional[Path], dict, Optional[str]]:
    """Get a ``git`` dependency's files onto this disk, at the commit to pin.

    A dependency that has a commit in the lockfile is pinned at that commit,
    whatever its branch has done since: ``pin`` never moves a pin. An update,
    or a dependency with no commit yet, asks the repository what its ``rev``
    means now.

    :param was: The dependency's entry in the lockfile, if it has one.
    :param listed: Its entry as the manifest has it now.
    :returns: The directory its files are in, or None if they could not be
        got; the entry the lockfile should list; and, if they could not be
        got, why.
    """
    url = local_url(entry["git"], project_dir)
    shown = strip_url_credentials(entry["git"])
    rev = entry.get("rev")
    locked_commit = (was or {}).get("location", {}).get("commit")

    try:
        if locked_commit and not may_move:
            if _declared_elsewhere(was, listed):
                # The manifest names another repository or revision now.
                # Following it would move the pins, which is an update's job.
                report.events.append(
                    PinEvent("relocated", key, detail=_describe(listed["location"]))
                )
            was_loc = (was or {}).get("location") or {}
            if was_loc.get("kind") == "git" and was_loc.get("url"):
                url = local_url(was_loc["url"], project_dir)
                shown = strip_url_credentials(was_loc["url"])
            # Still the commit it was pinned at. The network is used only
            # if this disk has lost its copy of it. A working copy, where
            # `chartbook run` built it, has more in it than the checkout.
            directory = git_cache.files(url, locked_commit)
            if directory is None:
                # Branches and tags, then the commit itself when none of them lead to it.
                git_cache.fetch_commit(url, locked_commit)
                directory = git_cache.checkout(url, locked_commit)
                report.events.append(
                    PinEvent("fetched", key, detail=f"{shown} at {locked_commit[:7]}")
                )
            return directory, was, None
        checkout = git_cache.get(url, rev)
    except (GitError, ValueError, OSError) as error:
        # What the lockfile says stays as it is; so do its pins
        failure = f"could not fetch {shown}: {error}"
        return None, (was if was is not None else listed), failure

    named = f" ({rev})" if rev and rev != checkout.commit else ""
    report.events.append(
        PinEvent("fetched", key, detail=f"{shown} at {checkout.commit[:7]}{named}")
    )
    listed = {**listed, "location": {**listed["location"], "commit": checkout.commit}}
    built = git_cache.find_work(url, checkout.commit)
    return (built or checkout.path), listed, None


def _made_in(taken: "snapshot.Snapshot") -> str:
    """The repository a snapshot says it was made in, for a message."""
    if taken.repository:
        return taken.repository
    if taken.first_commit:
        return f"a repository with no remote whose first commit is {taken.first_commit[:7]}"
    return "a ChartBook that did not record its repository"


def _newest_in_store(
    pipeline_id: str,
    at: Optional[str],
    store: Store,
    repository: Optional[str] = None,
    found: Optional[list] = None,
    first_commit: Optional[str] = None,
    named: bool = False,
) -> tuple[Optional["snapshot.Snapshot"], str, dict]:
    """The newest snapshot of a pipeline in the store, by its ID; None, and why, if there is none to take.

    "Newest" is the one made last, by its owner's clock, on whatever branch;
    *at*, the start of a commit, narrows it to that commit's snapshots. A
    snapshot dated after now is never the newest.

    Two repositories can give themselves one ID by accident, a copy of a
    project say, so the snapshots are kept to one repository, as
    :func:`chartbook.snapshot.repository_groups` groups them by address and
    first commit:

    - *named*: the manifest names *repository*. Only snapshots made at that
      address are taken, and those with no address whose first commit is
      one of theirs (a clone whose remote is a path). This is how one
      repository is told from its fork.
    - Otherwise *repository* and *first_commit* are what the dependency was
      first pinned from, and its repository is the group either is in: it
      may have moved, or had its history rewritten, and still be found.
    - With neither, an ID that more than one repository claims is not
      pinned until the manifest says which.

    A snapshot that names no repository, made by a ChartBook from before
    snapshots named one, is the repository's when only one claims the ID,
    and is taken by no pin when more than one does.

    This guards against an accident only: anyone who can write to a store
    can write a record that claims any repository.

    :returns: The snapshot; why there is none; and what to record of its
        repository (``repository``, ``first_commit``), with a note of any
        newer snapshot of the ID that another repository made and that was
        not taken (``passed_over``), and the newest snapshot of the same
        pipeline under another ID, when it is newer than any of this one
        (``under_another_id``, see :func:`_under_another_id`).
    """
    if found is None:
        found, _ = snapshot.readable_snapshots(store)
    every = [t for t in found if t.pipeline == pipeline_id]
    of_it = [t for t in every if not at or t.commit.startswith(at)]
    ahead = [t for t in of_it if snapshot.made_in_the_future(t)]
    mine = [t for t in of_it if t not in ahead]
    where = f" at a commit starting {at}" if at else ""
    dated = f"; {len(ahead)} dated after now are not taken" if ahead else ""
    groups, _ = snapshot.repository_groups(every)
    group_of = {id(t): index for index, group in enumerate(groups) for t in group}
    keys_of = [set().union(*(snapshot.identity_keys(t) for t in group)) for group in groups]
    known = set()
    if repository_key(repository):
        known.add(("address", repository_key(repository)))
    if first_commit and not named:
        known.add(("first", first_commit))

    def unnamed_of(index_matches, none_named_is_one: bool = False) -> bool:
        # One that names no repository was made by a ChartBook from before
        # snapshots named one: it is the repository's when only one claims
        # the ID, or, for a pin that recorded its repository, when none does
        if not groups:
            return none_named_is_one
        return len(groups) == 1 and index_matches(0)

    if named:
        wanted = repository_key(repository)
        firsts = {t.first_commit for t in every if repository_key(t.repository) == wanted and t.first_commit}

        def made_there(taken) -> bool:
            if taken.repository:
                return repository_key(taken.repository) == wanted
            if taken.first_commit:
                return taken.first_commit in firsts
            return unnamed_of(lambda index: ("address", wanted) in keys_of[index])

        there = repository
    elif known:
        chosen = {index for index, keys in enumerate(keys_of) if keys & known}

        def made_there(taken) -> bool:
            if id(taken) in group_of:
                return group_of[id(taken)] in chosen
            return unnamed_of(lambda index: index in chosen, none_named_is_one=True)

        there = f"the repository it was first pinned from ({repository or f'first commit {first_commit[:7]}'})"
    else:
        claiming = sorted({group_of[id(t)] for t in mine if id(t) in group_of})
        if len(claiming) > 1:
            shown = sorted({_made_in(max((t for t in mine if group_of.get(id(t)) == index), key=lambda t: t.made_at)) for index in claiming})
            return None, (
                f"snapshots from {len(claiming)} repositories claim the ID {pipeline_id}: {', '.join(shown)}. "
                f"Say which with repository = \"...\" in its [dependencies] entry, or name a commit of "
                f"it with commit = \"...\""
            ), {}

        def made_there(taken) -> bool:
            if not claiming:
                return True
            if id(taken) in group_of:
                return group_of[id(taken)] == claiming[0]
            return unnamed_of(lambda index: index == claiming[0])

        there = None

    taken = [t for t in mine if made_there(t)]
    accepted = sorted((t for t in every if made_there(t)), key=lambda t: t.made_at, reverse=True)
    if not taken:
        others = sorted({_made_in(t) for t in mine})
        claim = f"; snapshots from {', '.join(others)} claim its ID too, and are not taken" if others and there else ""
        # Its repository goes on under another ID, perhaps: said beside why there is nothing here
        elsewhere = {} if at else _under_another_id(pipeline_id, accepted, known, "", found, named, store)
        if there:
            return None, (
                f"the store at {store} has no snapshot of {pipeline_id}{where} made in {there}{claim}{dated}. "
                f"If it has moved, say where with repository = \"...\" in its [dependencies] entry"
            ), elsewhere
        other = None if every else in_another_case({t.pipeline for t in found}, pipeline_id)
        if other:
            return None, (
                f"the store at {store} has no snapshot of {pipeline_id}{where}{dated}. Did you mean {other}? "
                f"A scope derived from a remote is in lowercase"
            ), elsewhere
        return None, (
            f"the store at {store} has no snapshot of {pipeline_id}{where}{dated}. Its owner makes one "
            f"with `chartbook snapshot`; on another machine, the store must be the one theirs "
            f"syncs with or shares ([store] url)"
        ), elsewhere
    newest = max(taken, key=lambda t: t.made_at)

    # What to record of its repository: its own address and first commit;
    # for one made in a shallow clone or a clone with no address, what was
    # known already, which is never lost, or what the snapshots it was
    # taken with say
    identity = {
        "repository": newest.repository
        or (repository if ("address", repository_key(repository)) in known else "")
        or next((t.repository for t in accepted if t.repository), ""),
        "first_commit": newest.first_commit
        or (first_commit if first_commit and ("first", first_commit) in known else "")
        or next((t.first_commit for t in accepted if t.first_commit), ""),
    }
    if known and not snapshot.identity_keys(newest):
        against = "the one [dependencies] names" if named else "the one it was first pinned from"
        identity["unchecked"] = (
            f"taken from a snapshot of {pipeline_id} that names no repository, made by a ChartBook that "
            f"did not record one, so it could not be checked against {against}"
        )
    newer = [t for t in mine if not made_there(t) and t.made_at > newest.made_at]
    if newer:
        identity["passed_over"] = (
            f"{len(newer)} newer snapshot(s) of {pipeline_id}, from {', '.join(sorted({_made_in(t) for t in newer}))}, "
            f"not taken: another repository's. If it is the one now, say so with repository = \"...\" in its "
            f"[dependencies] entry, then `chartbook pin --update`"
        )
    if not at:
        identity.update(_under_another_id(pipeline_id, accepted, known, newest.made_at, found, named, store))
    return newest, "", identity


def _under_another_id(
    pipeline_id: str, of_it: list, known: set, after: str, found: list, named: bool = False, store: Optional[Store] = None
) -> dict:
    """The newest snapshot of the same pipeline under another ID, made after *after*: ``{"under_another_id": it}``, or nothing.

    A pipeline's ID can change under the pipelines that depend on it: it
    gets a remote, so a scope; its folder's name was its name, and the
    repository's is now; it is given ``[project] id``. Its snapshots then
    go on under the new ID, and a dependency named by the old one stays at
    the last snapshot of that, with nothing newer to move to. The same
    pipeline is the same repository (:func:`_made_in_one_of`), or the
    same clone of it set to a new address (:func:`_repointed`), and the
    same folder in it.

    :param of_it: The snapshots of the ID taken as the dependency's.
    :param known: What the pin recorded of its repository, or the address
        its entry names, as :func:`chartbook.snapshot.identity_keys` gives them.
    :param after: Only one made after this time counts; ``""`` for any.
    :param named: Whether the entry names its repository: then only that
        address is the dependency's, and a first commit only that address's
        snapshots record, as :func:`_newest_in_store` takes them.
    :param store: Where the snapshots are, to ask which folders they were made in.
    """
    addresses = {value for kind, value in known if kind == "address"}
    addresses |= {repository_key(t.repository) for t in of_it if repository_key(t.repository)}
    if named:
        firsts = {t.first_commit for t in of_it if t.first_commit and repository_key(t.repository) in addresses}
    else:
        firsts = {value for kind, value in known if kind == "first"} | {t.first_commit for t in of_it if t.first_commit}
    folders = {t.subdirectory for t in of_it}
    if not (addresses or firsts) or not folders:
        return {}
    repointed = _repointed(store, of_it, addresses)
    later = [
        t for t in found
        if t.pipeline != pipeline_id
        and t.subdirectory in folders
        and t.made_at > after
        and not snapshot.made_in_the_future(t)
        and (_made_in_one_of(t, addresses, firsts) or (t.first_commit in firsts and repointed(t)))
    ]
    newest = max(later, key=lambda t: t.made_at, default=None)
    return {"under_another_id": newest} if newest is not None else {}


def _repointed(store: Optional[Store], of_it: list, addresses: set):
    """What says whether a snapshot of another address was made in a clone the dependency's own snapshots were made in, its remote since set to that address.

    That is a repository moved on its host, transferred to another owner or
    renamed, and its clone's remote changed to match: one repository at a
    new address. A fork's clone is another folder; and while any folder
    the dependency's snapshots were made in still has their address, that
    repository is still there, and the other is not it. Only the folders
    the store notes are asked, and their remotes on this machine.
    """
    tops: dict = {}  # each folder the dependency's snapshots were made in, and its remote's address now
    looked: list = []

    def known_tops() -> dict:
        if not looked and store is not None:
            looked.append(True)
            for moment in {(t.commit, t.subdirectory): t for t in of_it}.values():
                try:
                    tops.update({top: repository_key(get_git_remote_url(top)) for top in snapshot.origins(store, moment)})
                except (StoreError, OSError):
                    continue
        return tops

    def made_there(taken) -> bool:
        now = known_tops()
        if not now or any(address in addresses for address in now.values()):
            return False
        try:
            theirs = snapshot.origins(store, taken)
        except (StoreError, OSError):
            return False
        return any(now.get(top) == repository_key(taken.repository) for top in theirs)

    return made_there


def _made_in_one_of(taken: "snapshot.Snapshot", addresses: set, firsts: set) -> bool:
    """Whether a snapshot was made in the repository these addresses and first commits name.

    By its address where it and the repository both have one, so that a
    fork, which shares its original's first commit and has an address of
    its own, is another repository; by its first commit where either has
    none (a remote added since, a clone whose remote is a path).
    """
    address = repository_key(taken.repository)
    if address and addresses:
        return address in addresses
    return bool(taken.first_commit) and taken.first_commit in firsts


def _under_another_id_note(key: str, declared: dict, taken: "snapshot.Snapshot") -> str:
    """What to say of a dependency whose pipeline now makes its snapshots under another ID, and the entry to write."""
    from chartbook.manifest import dependency_line

    kept = {name: declared[name] for name in ("commit", "rev", "repository") if isinstance(declared.get(name), str)}
    if "repository" in kept and repository_key(kept["repository"]) != repository_key(taken.repository):
        # Its snapshots under the new ID name another address, or none: an entry naming this one would take none
        del kept["repository"]
    line = dependency_line(key, kept if key == taken.pipeline else {"id": taken.pipeline, **kept})
    made = f"{taken.made_at[:10]} {taken.made_at[11:16]} UTC"
    return (
        f"the store has newer snapshots of the same repository and folder under another ID, {taken.pipeline} "
        f"(the newest made {made}): the pipeline probably calls itself that now, as one does when it gets a "
        f"git remote or a [project] id. To follow it, write {line} under [dependencies], then "
        f"`chartbook pin --update {key}`"
    )


def _sync_from_snapshots(
    key: str,
    directory: Optional[Path],
    was: Optional[dict],
    listed: dict,
    had: dict[str, dict],
    may_move: bool,
    store: Store,
    report: PinReport,
    newest_of=None,
    found=None,
    declared: Optional[dict] = None,
) -> tuple[dict[str, dict], dict]:
    """Work out a dependency's records from its snapshots: a ``path`` dependency's, or one named by its ID.

    The dependency's folder is somebody's working directory, and nothing in
    it is read here but where it is in git. What is pinned is a snapshot:
    what its owner declared ready, at a commit (:mod:`chartbook.snapshot`).

    A dependency is pinned to one snapshot, whole. ``pin`` takes the newest
    when nothing is pinned yet, and otherwise stays where it is and says
    what a newer one would change. ``update`` moves to the newest.

    :param was: The dependency's entry in the lockfile, if it has one.
    :param listed: Its entry as the manifest has it now.
    :param had: The records the lockfile has for it now, by asset ID.
    :param may_move: Whether its existing pins may move (an update).
    :param newest_of: For a dependency named by its ID: what finds its
        newest snapshot, and why there is none; *directory* is then None.
    :param declared: For a dependency named by its ID: its entry in the
        manifest, to say what to write when its pipeline's snapshots go on
        under another ID.
    :returns: Its records as they should be, by asset ID, and the entry the
        lockfile should list: with the snapshot's commit and time.
    """
    # A label's record, `key:model/x@champion`, is pinned beside the assets
    # and judged apart from them: it follows the owner's labels, not the
    # snapshot's content
    had_labels = {k: v for k, v in had.items() if (v.get("ref") or {}).get("rev")}
    had = {k: v for k, v in had.items() if k not in had_labels}
    pinned = [record for record in had.values() if record.get("content_hash")]
    # Pinned, too, with nothing of it in the lockfile: one whose assets are
    # all drawn anew by every build is pinned by the snapshot its entry names
    is_pinned = bool(pinned) or names_a_snapshot(was)
    locked_commit = (was or {}).get("location", {}).get("commit")
    locked_made = (was or {}).get("snapshot")
    why = ""
    code = None
    identity: dict = {}
    if newest_of is not None:
        newest, why, identity = newest_of()
        if may_move or not is_pinned:
            # Said when the choice is made, not on every pin after it
            for status in ("passed_over", "unchecked"):
                if identity.get(status):
                    report.events.append(PinEvent(status, key, detail=identity[status]))
        if identity.get("under_another_id") is not None:
            # Said on every pin and update: nothing newer comes of this ID until its entry changes
            report.events.append(
                PinEvent("id_changed", key, detail=_under_another_id_note(key, declared or {}, identity["under_another_id"]))
            )
    else:
        try:
            newest, code = snapshot.newest_for(directory, store)
        except snapshot.SnapshotError as error:
            newest, code, why = None, None, str(error)
            if not Path(directory).is_dir():
                # Another machine's folder, most likely: said with the entry that works here
                found_now = found if found is not None else (lambda: snapshot.readable_snapshots(store)[0])
                why = f"{why}. {name_it_by_its_id(key, was, found_now)}"

    def as_it_was() -> dict:
        """The listing, still naming the snapshot the pins came from, and the repository it came from."""
        was_location = (was or {}).get("location", {})
        if was is not None and (
            was_location.get("kind") == "git"
            or (was_location.get("pipeline") and was_location.get("pipeline") != listed.get("location", {}).get("pipeline"))
            or _declared_elsewhere(was, listed)
        ):
            # Pinned from its repository, or as another pipeline, or moved in the manifest
            # without moving the pins: it says where the pins came from, not where the
            # manifest points now.
            return {**was, "location": dict(was_location)}
        kept = dict(listed)
        if locked_commit:
            kept["location"] = {**listed["location"], "commit": locked_commit}
        if kept["location"].get("kind") == "store":
            # The repository the pins came from, whatever the manifest names
            # now: only a pin from a snapshot records one
            had_location = (was or {}).get("location", {})
            location = {k: v for k, v in kept["location"].items() if k not in ("repository", "first_commit")}
            for name in ("repository", "first_commit"):
                if had_location.get(name):
                    location[name] = had_location[name]
            kept["location"] = location
        if locked_made:
            kept["snapshot"] = locked_made
        if (was or {}).get("pinned_from"):
            # Still the pipeline the pins came from
            kept["pinned_from"] = was["pinned_from"]
        return kept

    if is_pinned and not may_move:
        # `pin` does not move a pin. It says what a newer snapshot has.
        if not had and not had_labels:
            # Nothing of it is in the lockfile: its entry is the pin
            report.events.append(PinEvent("at_snapshot", key, detail=(locked_commit or "")[:7]))
        if was is not None and _declared_elsewhere(was, listed):
            # The manifest names another folder now. Following it would
            # move the pins, which is an update's job; the lockfile keeps
            # saying where these came from.
            report.events.append(
                PinEvent("relocated", key, detail=_describe(listed["location"]))
            )
            listed = {**listed, "via": was.get("via", listed.get("via")), "location": dict(was["location"])}
        newer = newest is not None and not newest.same_moment(locked_commit, locked_made)
        theirs = newest.content() if newer else {}
        # Pinned bytes the store does not have: a snapshot of yours of that
        # commit may hold the same rows, and stand in for the one pinned
        every = found if found is not None else (lambda: snapshot.readable_snapshots(store)[0])
        stood = your_build(was or {}, {**had, **had_labels}, store, every, directory)
        if stood is not None:
            report.stood_in[key] = stood

        def ways_on() -> str:
            """What puts a lost pin back, by what this store has: a newer snapshot for `chartbook pin --update` to move to, the pinned snapshot made again where the store has it, a build of your own where it has not."""
            ways = []
            # Named only where it would work: the newest may lack the same file (two snapshots kept as increments
            # on one complete snapshot that lost it), and a snapshot is taken whole or not at all
            if newer and all(
                store.has(asset["content_hash"], newest.pipeline) and not _incomplete(store, asset, newest.pipeline)
                for asset in newest.assets.values() if asset.get("content_hash")
            ):
                ways.append("`chartbook pin --update` moves to the newest one")
            if has_named(was, every(), directory):
                ways.append("`chartbook snapshot` in its folder at that commit makes it again")
            said = f" Otherwise a snapshot puts it there: {', or '.join(ways)}" if ways else ""
            if not has_named(was, every(), directory) and build_it_said(was):
                said += f"{'; or' if ways else ' Otherwise'} build it yourself, {build_it_said(was)}"
            return said

        for record in had.values():
            old = record.get("content_hash")
            if not old:
                # Built since, perhaps: say so, as for a pin that has changed
                built = theirs.get(snapshot.local_name(record))
                said = "a newer snapshot has it: `chartbook pin --update` pins it" if built else _where(record)
                report.events.append(PinEvent("not_built", key, record["id"], detail=said))
            elif not in_lockfile(record) and not store.has(old, report.pipelines.get(key)):
                # Kept of an earlier lockfile, on a machine whose store had its bytes: here
                # it is read as any asset the lockfile does not hold, and is no pin
                report.events.append(PinEvent("unlocked", key, record["id"], detail=(record.get("ref") or {}).get("kind", "")))
            elif stood is not None and not store.has(old, report.pipelines.get(key)):
                met = stood.met.get(record["id"])
                if met is not None:
                    report.events.append(PinEvent("stood_in", key, record["id"], old=old, new=old, detail=met.as_of or ""))
                else:
                    why = next((unmet.why for unmet in stood.unmet if unmet.asset == record["id"]), "your build does not hold it")
                    report.events.append(PinEvent("differs", key, record["id"], old=old, detail=why))
            elif not store.has(old, report.pipelines.get(key)):
                report.events.append(
                    PinEvent(
                        "lost",
                        key,
                        record["id"],
                        old=old,
                        detail=f"it is not in the store at {store}. {NOT_SYNCED_YET}.{ways_on()}",
                    )
                )
            elif unsynced := _incomplete(store, record, report.pipelines.get(key)):
                report.events.append(PinEvent("unsynced", key, record["id"], old=old, new=old, detail=unsynced))
            else:
                now = theirs.get(snapshot.local_name(record))
                # A chart is other bytes in every build: only what code reads is said to have changed
                status = "stale" if now is not None and now != old and in_lockfile(record) else "kept"
                report.events.append(PinEvent(status, key, record["id"], old=old, new=old))
        for asset_id, record in sorted(had_labels.items()):
            # A label the owner has since moved is stale, like changed data
            old = record.get("content_hash")
            now = (newest.labels.get(snapshot.local_name(record)) or {}).get(record.get("label")) if newer else None
            moved = bool(old and now and not old.split(":", 1)[-1].startswith(now))
            if old and stood is not None and not store.has(old, report.pipelines.get(key)):
                # A version no build of this commit gives: met by its own file only
                why = next((unmet.why for unmet in stood.unmet if unmet.asset == asset_id), "the store does not have it")
                report.events.append(PinEvent("differs", key, asset_id, old=old, detail=why))
            elif old and not store.has(old, report.pipelines.get(key)):
                report.events.append(
                    PinEvent(
                        "lost", key, asset_id, old=old,
                        detail=(
                            f"it is not in the store at {store}. {NOT_SYNCED_YET}. Otherwise its owner makes a "
                            f"snapshot that holds that version again, and then `chartbook pin --update {key}`"
                        ),
                    )
                )
            elif old and (unsynced := _incomplete(store, record, report.pipelines.get(key))):
                report.events.append(PinEvent("unsynced", key, asset_id, old=old, new=old, detail=unsynced))
            elif old:
                report.events.append(PinEvent("stale" if moved else "kept", key, asset_id, old=old, new=old))
            else:
                report.events.append(
                    PinEvent("not_built", key, asset_id, detail=record.get("missing") or "the label was pinned without its bytes")
                )
        return {**had, **had_labels}, as_it_was()

    if newest is None:
        # Nothing to pin from, or nothing to move to. What is pinned stays.
        for record in pinned:
            _report_kept(record, key, store, report)
        for asset_id, record in sorted(had_labels.items()):
            if record.get("content_hash"):
                _report_kept(record, key, store, report)
            else:
                report.events.append(
                    PinEvent("not_built", key, asset_id, detail=record.get("missing") or "the label was pinned without its bytes")
                )
        had = {**had, **had_labels}
        if not why:
            why = (
                f"it has no snapshot at or before {code.commit[:7]}, the commit "
                f"its folder is on. In {listed['location']['path']}: commit, "
                f"then run `chartbook snapshot`"
            )
        report.events.append(PinEvent("no_snapshot", key, detail=why))
        return dict(had), as_it_was()

    # A snapshot is taken whole or not at all. If the store has lost an
    # object the snapshot names, nothing moves: the lockfile would otherwise
    # name this snapshot beside bytes from another.
    missing = [
        (snapshot.renamed(newest.assets[name], key)["id"], newest.assets[name]["content_hash"])
        for name in sorted(newest.assets)
        if newest.assets[name].get("content_hash")
        and not store.has(newest.assets[name]["content_hash"], newest.pipeline)
    ]
    # Or it has the object, and not all of its bytes yet: a store in a
    # synced folder can have a file before the whole of it
    unsynced = []
    for name in sorted(newest.assets):
        if newest.assets[name].get("content_hash") and store.has(newest.assets[name]["content_hash"], newest.pipeline):
            short = _incomplete(store, newest.assets[name], newest.pipeline)
            if short:
                unsynced.append((snapshot.renamed(newest.assets[name], key)["id"], newest.assets[name]["content_hash"], short))
    if missing or unsynced:
        # Said once each: what the snapshot names, and what else is pinned
        said = {content_hash for _, content_hash in missing} | {content_hash for _, content_hash, _ in unsynced}
        for record in pinned:
            if record.get("content_hash") not in said:
                _report_kept(record, key, store, report)
        had = {**had, **had_labels}
        # The snapshot pinned already, or one it would move to
        there = newest.same_moment(locked_commit, locked_made)
        moved = "" if there else ", so nothing was moved"
        for asset_id, content_hash in missing:
            report.events.append(
                PinEvent(
                    "lost",
                    key,
                    asset_id,
                    old=content_hash if there else None,
                    detail=(
                        f"the snapshot at {newest.commit[:7]} names it, and the store at {store} does "
                        f"not have it{moved}. {NOT_SYNCED_YET}. If that machine's store lacks it too, "
                        f"its owner makes the snapshot again (`chartbook snapshot` in its folder, at "
                        f"that commit)"
                    ),
                )
            )
        for asset_id, content_hash, why in unsynced:
            report.events.append(
                PinEvent(
                    "unsynced", key, asset_id,
                    old=content_hash if there else None,
                    new=content_hash if there else None,
                    detail=(
                        f"{why}" if there
                        else f"nothing was moved to the snapshot at {newest.commit[:7]}, which names it: {why}"
                    ),
                )
            )
        return dict(had), as_it_was()

    records: dict[str, dict] = {}
    unlocked: set = set()
    for name in sorted(newest.assets):
        # `trained_on` is the owner's record, keyed in the owner's names,
        # and would read as asset IDs here that are not; it stays with the
        # snapshot. So does `keep`, the owner's intent about the owner's
        # store: a lockfile records what was got
        record = {k: v for k, v in snapshot.renamed(newest.assets[name], key).items() if k not in ("trained_on", "keep")}
        asset_id = record["id"]
        if not in_lockfile(record):
            # Not in the lockfile: read from this snapshot, and not pinned.
            # One that was not built is said so, as any asset is
            unlocked.add(asset_id)
            if record.get("content_hash"):
                report.events.append(PinEvent("unlocked", key, asset_id, detail=(record.get("ref") or {}).get("kind", "")))
            else:
                report.events.append(PinEvent("not_built", key, asset_id, detail=_where(record)))
            continue
        before = had.get(asset_id)
        old = (before or {}).get("content_hash")
        new = record.get("content_hash")
        declared_path = _where(record)
        if new is None:
            # Not built when the snapshot was made. A pin from an earlier
            # snapshot does not belong beside this one's commit.
            status = "let_go" if old else "not_built"
            report.events.append(PinEvent(status, key, asset_id, old=old, detail=declared_path))
        elif old is None:
            report.events.append(PinEvent("pinned", key, asset_id, new=new))
        elif old == new:
            report.events.append(PinEvent("kept", key, asset_id, old=old, new=new))
        else:
            report.events.append(PinEvent("moved", key, asset_id, old=old, new=new))
            if (record.get("ref") or {}).get("kind") == "dataframe":
                # Its rows beside the pin it had: new rows, or earlier rows changed
                from chartbook import standins

                # Said where it can be told without fetching a table; nothing of it stops an update
                told = standins.since(before, record, newest, store, read=standins.reads_here(store))
                if told:
                    report.rows_said[asset_id] = told
        records[asset_id] = record

    # What the lockfile has that this snapshot does not; one its owner no
    # longer marks `lock = true` is said already, as not pinned
    for asset_id in sorted(set(had) - set(records) - unlocked):
        old = had[asset_id].get("content_hash")
        if old:
            report.events.append(PinEvent("dropped", key, asset_id, old=old))
    # And what the snapshot it was pinned to had, outside the lockfile, that
    # this one does not: a chart its owner no longer declares
    if locked_commit and locked_made and not newest.same_moment(locked_commit, locked_made):
        earlier_pipeline = pinned_pipeline(was, directory) or newest.pipeline
        try:
            earlier = next(
                (
                    taken for taken in (found() if found is not None else [])
                    if taken.same_moment(locked_commit, locked_made) and taken.pipeline == earlier_pipeline
                ),
                None,
            )
        except (OSError, StoreError, snapshot.SnapshotError):
            earlier = None
        for name in sorted(set(earlier.assets) - set(newest.assets)) if earlier is not None else ():
            gone = snapshot.renamed(earlier.assets[name], key)
            if not in_lockfile(gone) and gone.get("content_hash") and gone["id"] not in had:
                report.events.append(PinEvent("dropped", key, gone["id"], old=gone["content_hash"]))

    # The labels the owner's manifest gave when the snapshot was made, each
    # pinned to the version it names
    labelled, unresolved = snapshot.label_records(newest, key, store, found=found() if found and newest.labels else None)
    for asset_id, record in labelled.items():
        old = (had_labels.get(asset_id) or {}).get("content_hash")
        new = record["content_hash"]
        status = "pinned" if old is None else "kept" if old == new else "moved"
        report.events.append(PinEvent(status, key, asset_id, old=old, new=new))
        records[asset_id] = record
    for name, label, start, why in unresolved:
        ref = dataclasses.replace(AssetRef.from_dict(snapshot.renamed(newest.assets[name], key)["ref"]), rev=label)
        asset_id = str(ref)
        record = {k: v for k, v in snapshot.renamed(newest.assets[name], key).items() if k not in ("content_hash", "size_bytes", "files", "trained_on", "keep")}
        missing = f"the label names version {start}, and {why}"
        records[asset_id] = {**record, "id": asset_id, "ref": ref.to_dict(), "label": label, "missing": missing}
        report.events.append(
            PinEvent(
                "not_built", key, asset_id,
                old=(had_labels.get(asset_id) or {}).get("content_hash"),
                detail=missing,
            )
        )
    for asset_id in sorted(set(had_labels) - set(records)):
        old = had_labels[asset_id].get("content_hash")
        if old:
            report.events.append(PinEvent("dropped", key, asset_id, old=old))

    report.snapshots[key] = newest
    location = {**listed["location"], "commit": newest.commit}
    if location.get("kind") == "store":
        # The repository it came from, which later pins and updates keep to
        location.pop("repository", None)
        for name in ("repository", "first_commit"):
            if identity.get(name):
                location[name] = identity[name]
    # The pipeline the snapshot is of, by its own ID, whatever the key: the
    # store keeps a snapshot by it
    listed = {**listed, "location": location, "snapshot": newest.made_at, "pinned_from": newest.pipeline}
    return records, listed


def _sync_dependency(
    key: str,
    directory: Optional[Path],
    had: dict[str, dict],
    may_move: bool,
    store: Store,
    cache: hashing.HashCache,
    report: PinReport,
    commit_moved: bool = False,
    within: Optional[Path] = None,
) -> dict[str, dict]:
    """Work out the records of one dependency's assets, pinning as needed.

    :param directory: Where the dependency's files are: the checkout of a
        ``git`` dependency. None if they could not be got.
    :param had: The records the lockfile has for it now, by asset ID.
    :param may_move: Whether its existing pins may move (an update).
    :param commit_moved: Whether this update moved a ``git`` dependency to
        another commit than the one it was pinned at.
    :param within: The checkout: a declared path that reaches a file
        outside it is not pinned, and is a problem.
    :returns: Its records as they should be, by asset ID.
    """
    try:
        if directory is None:
            raise OSError("it could not be fetched")
        declared = declared_files(directory)
    except (OSError, ValueError) as error:
        # What is pinned stays pinned. That is the point of pinning: the
        # other pipeline can go away and this one still has its data.
        pinned = [record for record in had.values() if record.get("content_hash")]
        if (not pinned or may_move) and directory is not None:
            report.events.append(
                PinEvent(
                    "unreachable",
                    key,
                    detail=f"no pipeline can be read at {directory} ({error})",
                )
            )
        for record in pinned:
            _report_kept(record, key, store, report)
        return dict(had)

    records: dict[str, dict] = {}
    # How the owner said to read each dataframe, which its record keeps;
    # and what it marks `lock = true`
    try:
        raw = _read_manifest_file(Path(directory))
    except (OSError, ValueError):
        raw = {}
    entries = raw.get("dataframes")
    entries = entries if isinstance(entries, dict) else {}
    # Every asset, of whatever kind, and with no mark of `lock = true`, which changes
    # nothing here: a repository's bytes are its commit's, the same for everyone,
    # and only the lockfile names them (in_lockfile)
    for ref, declared_path, absolute in declared:
        qualified = ref.in_pipeline(key)
        records[str(qualified)] = _pin_asset(
            qualified,
            key,
            declared_path,
            absolute,
            had.get(str(qualified)),
            may_move,
            store,
            cache,
            report,
            commit_moved,
            within,
            reading=formats.declared(entries.get(ref.name)) if ref.kind == "dataframe" else None,
        )

    # A table or query in a source has no file in the checkout to take: a
    # pin of it comes from a snapshot, and stays as the lockfile has it.
    # One the lockfile does not have yet is listed without a hash, and said so
    from chartbook.resolve import declared_in_source
    from chartbook.snapshot import source_record

    try:
        in_source = declared_in_source(directory)
    except (OSError, ValueError):
        in_source = []
    for ref, entry in in_source:
        asset_id = str(ref.in_pipeline(key))
        if asset_id in had:
            continue
        records[asset_id] = source_record(ref.in_pipeline(key), key, entry, None, None)
        report.events.append(
            PinEvent(
                "not_built", key, asset_id,
                detail="a table or query in a source is not taken from a repository; "
                "`chartbook snapshot` there writes it out, then `chartbook pin --update` pins it",
            )
        )

    # What the lockfile has that the other pipeline no longer declares
    for asset_id in sorted(set(had) - set(records)):
        old = had[asset_id].get("content_hash")
        if not old:
            continue  # it was never pinned; there is nothing to let go of
        if had[asset_id].get("location", {}).get("kind") in ("table", "query"):
            # A table or query has no file in the checkout to take: its
            # pin is the snapshot's parquet, and stays until a snapshot moves it
            records[asset_id] = had[asset_id]
            _report_kept(had[asset_id], key, store, report)
        elif may_move:
            report.events.append(PinEvent("dropped", key, asset_id, old=old))
        else:
            records[asset_id] = had[asset_id]
            _report_kept(had[asset_id], key, store, report)
    return records


def _report_kept(record: dict, key: str, store: Store, report: PinReport) -> None:
    """Report a pin that stays as it is, and whether the store still has it."""
    pinned = record.get("content_hash")
    if not pinned:
        return
    of = report.pipelines.get(key)  # asked of that pipeline's own snapshots, as a read asks
    unsynced = _incomplete(store, record, of) if store.has(pinned, of) else None
    if unsynced:
        report.events.append(PinEvent("unsynced", key, record["id"], old=pinned, new=pinned, detail=unsynced))
    elif store.has(pinned, of):
        report.events.append(
            PinEvent("kept", key, record["id"], old=pinned, new=pinned)
        )
    else:
        report.events.append(
            PinEvent(
                "lost",
                key,
                record["id"],
                old=pinned,
                detail="it is not in the store, and there is nothing to put it back from",
            )
        )


def _pin_asset(
    ref: AssetRef,
    key: str,
    declared_path: str,
    absolute: Path,
    had: Optional[dict],
    may_move: bool,
    store: Store,
    cache: hashing.HashCache,
    report: PinReport,
    commit_moved: bool = False,
    within: Optional[Path] = None,
    reading: Optional[dict] = None,
) -> dict:
    """Decide what one asset's record is, storing its bytes if they are needed.

    *reading* is a dataframe's ``format`` and ``read_options``, which a
    record of its bytes keeps (:func:`chartbook.snapshot.asset_record`).
    """
    asset_id = str(ref)
    old = (had or {}).get("content_hash")

    if within is not None:
        reached = hashing.escapes(absolute, within)
        if reached is not None:
            # Whatever the manifest says, a pipeline that is only read gives
            # up nothing but its own files. Nothing is stored, and a pin it
            # had is not kept either: it names bytes from outside.
            report.events.append(
                PinEvent(
                    "outside",
                    key,
                    asset_id,
                    old=old,
                    detail=(
                        f"its path {declared_path!r} reaches {reached}, which is "
                        f"outside the repository. Only a repository's own files "
                        f"are pinned"
                    ),
                )
            )
            return _asset_record(ref, key, declared_path, None, True)

    named = hashing.glob_named(declared_path, absolute)
    if named is not None:
        # Its files would be stored as named and read back as a pattern
        detail = f"its path {hashing.glob_named_said(declared_path, named)}"
        report.events.append(PinEvent("glob_name", key, asset_id, old=old, detail=detail))
        return _asset_record(ref, key, declared_path, None, True)

    if old is None or may_move:
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            if old is not None and not commit_moved:
                # An update with nothing to move to: the pin stays
                _report_kept(had, key, store, report)
                return had
            if old is not None:
                # The dependency is at another commit now. This was built
                # from the one before, and has not been built at this one.
                # Keeping the pin would have the lockfile name a commit
                # beside data that did not come from it, which nobody else
                # could get back. `chartbook run` builds it and pins it.
                report.events.append(
                    PinEvent("let_go", key, asset_id, old=old, detail=declared_path)
                )
            else:
                report.events.append(
                    PinEvent("not_built", key, asset_id, detail=declared_path)
                )
            return _asset_record(ref, key, declared_path, None, True)
        stored = store.put(absolute, links=PIN_LINKS, base=within, key=key)
        if old is None:
            status = "pinned"
        elif stored.content_hash == old:
            status = "kept"
        else:
            status = "moved"
        report.events.append(
            PinEvent(status, key, asset_id, old=old, new=stored.content_hash)
        )
        return _asset_record(ref, key, declared_path, stored, found.single, reading=reading)

    # It has a pin, and `pin` does not move one
    try:
        current = hashing.hash_path(absolute, cache)
    except OSError as error:
        warnings.warn(f"Could not read {absolute}: {error}", stacklevel=2)
        current = None
    same = current is not None and current.content_hash == old
    of = report.pipelines.get(key)  # asked of that pipeline's own snapshots, as a read asks
    unsynced = _incomplete(store, had, of) if store.has(old, of) else None
    names = snapshot.files_read(had) or {}
    # The bytes are one file, as its record and the checkout have them
    single = not isinstance(had.get("files"), list) and os.path.isfile(absolute)
    try:
        lacking = bool(unsynced and same and names) and store.lacks(old, names, single=single)
    except (OSError, StoreError):
        lacking = False  # a store that cannot be asked now: said as before
    if lacking:
        # The store has these bytes under another name only: two assets with
        # the same bytes, put back one at a time, or pinned by another
        # pipeline. The file here is what was pinned, so it is put in again,
        # which adds the name. A file that is there and still arriving is
        # not this, and is still said to be
        try:
            stored = store.put(absolute, links=PIN_LINKS, base=within, key=key)
        except (OSError, StoreError):
            stored = None  # a store this user cannot write, or the file gone: said as before
        if stored is not None and isinstance(store, _PutLater):
            # Put once the lockfile may be written, and said restored then if that makes it whole
            store.recheck[stored.content_hash] = (asset_id, had, of)
        elif stored is not None:
            unsynced = _incomplete(store, had, of)
            if not unsynced:
                report.events.append(PinEvent("restored", key, asset_id, old=old, new=old))
                return had
    if unsynced:
        report.events.append(PinEvent("unsynced", key, asset_id, old=old, new=old, detail=unsynced))
    elif store.has(old, of):
        status = "kept" if same else "stale"
        report.events.append(PinEvent(status, key, asset_id, old=old, new=old))
    elif same:
        store.put(absolute, links=PIN_LINKS, base=within, key=key)
        report.events.append(PinEvent("restored", key, asset_id, old=old, new=old))
    else:
        report.events.append(
            PinEvent(
                "lost",
                key,
                asset_id,
                old=old,
                detail=(
                    "it is not in the store, and the other pipeline no longer "
                    "has those bytes"
                ),
            )
        )
    return had


def pin(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
    before_writing: Optional[Callable[[Lock], Optional[str]]] = None,
    raise_floor: bool = False,
) -> PinReport:
    """Pin whatever a pipeline depends on that has no pin yet.

    A pin that already exists is left exactly where it is, whatever the
    other pipeline has done since: :func:`update` is what moves one.

    A ``path`` dependency is pinned from its newest **snapshot**: what its
    owner declared ready, at a commit (:mod:`chartbook.snapshot`). None of
    its data in its folder is read: its manifest and lockfile are, to see
    that the pin makes no cycle. One that has no snapshot cannot be pinned,
    and the report says what its owner has to do.

    A ``git`` dependency is fetched into the git cache and pinned from the
    checkout, at the commit the lockfile names if it names one. It has only
    what its repository commits, until ``chartbook run`` builds it; the
    rest of what it declares is not built.

    An asset that is declared and not built is recorded as not pinned; the
    rest of the dependency is pinned all the same.

    :param project_dir: The pipeline's directory.
    :param store: The store to pin into; this user's by default.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param only: The keys of the dependencies to pin; the rest keep what
        the lockfile has, and nothing of them is fetched. All by default.
        Where there is no lockfile yet, one is made only if something of
        them is recorded: the first read of a pipeline with no snapshot
        writes nothing.
    :param clone_missing: Whether a dependency named by its ID that the
        store has no snapshot of is cloned from the default host, and
        pinned from the clone (:func:`clone_instead`).
    :param built_here: The IDs of pipelines a run builds itself (a
        catalog's own), which are never cloned.
    :param raise_floor: Whether to raise the manifest's
        ``requires_chartbook`` where it admits a ChartBook that cannot
        read the lockfile (:func:`see_to_the_floor`), as ``chartbook pin``
        does. A build and a read leave the manifest as it is, and the
        report's ``floor`` says what is wanted.
    :param before_writing: Called with the lockfile as it would be written;
        what it returns, if anything, is why nothing is written. It takes
        the place of the default guard, which refuses a lockfile that would
        make the pipeline's dependencies cyclic (``chartbook run`` gives its
        own, which walks the run's other pipelines too). The report's
        ``refused`` says why.
    :returns: What was done.
    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    return _sync(
        project_dir, store, move=None, git_cache=git_cache,
        only=None if only is None else ({only} if isinstance(only, str) else set(only)),
        clone_missing=clone_missing,
        built_here=built_here,
        before_writing=before_writing,
        raise_floor=raise_floor,
    )


#: What a store does that writes, besides ``put``: refused by :class:`_PutLater`
_STORE_WRITES = ("add_root", "remove_root", "delete", "note_origin", "write_snapshot", "remove_snapshot")


class _PutLater:
    """A store read as it is, into which what a pin puts goes only once the lockfile may be written.

    ``put`` reads nothing and holds the path, under a stand-in for its hash;
    :meth:`put_held` puts each, once a pin's ``before_writing`` lets its
    lockfile through, and gives the records their hashes from what was put,
    so that each file is read once and a refused pin writes no object. With
    *hold* off (:func:`would_pin`), nothing is held: the records carry no
    hash, which is enough to see where a pin leads. Every other write is
    refused: none is reached before the lockfile is let through.
    """

    def __init__(self, store: Store, hold: bool = True):
        self._store = store
        self._hold = hold
        self.held: dict = {}
        #: Puts of bytes the store had under another name only, by stand-in:
        #: the asset and its record, said restored once put if that makes it whole
        self.recheck: dict = {}

    def __getattr__(self, name: str):
        if name in _STORE_WRITES:
            raise StoreError(f"nothing is written to the store before a lockfile is let through ({name})")
        return getattr(self._store, name)

    def __str__(self) -> str:
        return str(self._store)

    def __repr__(self) -> str:
        return repr(self._store)

    def put(
        self, path: Union[str, Path], links: Iterable[str] = STORE_LINKS, base: Optional[Path] = None, key: str = ""
    ) -> StoredObject:
        """Hold a put of what *path* names, from the clone of the dependency *key* whose pipeline's folder is *base*."""
        if hashing.find_files(path) is None:
            raise FileNotFoundError(f"Nothing at {path}")
        stand_in = ""
        if self._hold:
            # No hash a lockfile could hold, however it was written
            stand_in = f"held:{uuid.uuid4().hex}"
            self.held[stand_in] = (path, tuple(links), base, key)
        return StoredObject(content_hash=stand_in, size_bytes=0, path=Path(path), files=(), created=False)

    def forget_held(self, report: "PinReport") -> None:
        """Let go of what was held, for a pin that was refused: the report names no stand-in."""
        if not self._hold:
            return
        held, self.held = self.held, {}
        self.recheck = {}
        report.events[:] = [
            dataclasses.replace(
                event, old=None if event.old in held else event.old, new=None if event.new in held else event.new
            )
            for event in report.events
        ]

    def put_held(self, after: "Lock", report: "PinReport") -> None:
        """Put what was held, and give the lockfile and the report the hashes of what was put."""
        if not self._hold:
            raise StoreError("a pin that is only worked out is never put in the store")
        stored = {}
        by_key: dict = {}
        for stand_in, (path, links, base, key) in self.held.items():
            by_key.setdefault(key, []).append((stand_in, path, links, base))
        for key, held in by_key.items():
            stored.update(self._put_from_clone(key, held, after))
        self.held = {}
        rechecked, self.recheck = self.recheck, {}
        restored = {
            asset_id for stand_in, (asset_id, record, of) in rechecked.items()
            if stand_in in stored and not _incomplete(self._store, record, of)
        }
        if restored:
            report.events[:] = [
                dataclasses.replace(event, status="restored", detail="")
                if event.status == "unsynced" and event.asset in restored else event
                for event in report.events
            ]
        if not stored:
            return
        changed = set()
        for record in after.assets.values():
            put = stored.get(record.get("content_hash"))
            if put is None:
                continue
            record["content_hash"], record["size_bytes"] = put.content_hash, put.size_bytes
            if "files" in record:
                record["files"] = [
                    {"path": entry.path, "size_bytes": entry.size_bytes, "content_hash": entry.content_hash}
                    for entry in put.entries
                ]
            changed.add(record.get("pipeline"))
        for entry in after.dependencies:
            if entry.get("id") in changed:
                entry.pop("pinned_hash", None)
                overall = pinned_hash(after.assets_of(entry["id"]).values())
                if overall is not None:
                    entry["pinned_hash"] = overall
        def as_put(event: PinEvent) -> PinEvent:
            old = stored[event.old].content_hash if event.old in stored else event.old
            if event.new not in stored:
                return dataclasses.replace(event, old=old)
            new = stored[event.new].content_hash
            # `update` put the same bytes again: what it took for a move is none
            status = "kept" if event.status == "moved" and new == old else event.status
            return dataclasses.replace(event, status=status, old=old, new=new)

        report.events[:] = [as_put(event) for event in report.events]


    def _put_from_clone(self, key: str, held: list, after: "Lock") -> dict:
        """Put what was held from one dependency's clone, as a snapshot a pin made in its pipeline's folder; what was put, by stand-in.

        The files go where its owner's snapshots keep theirs, in its
        pipeline's folder (:class:`chartbook.store.PendingSnapshot`), and
        the snapshot is written only if it holds something the store did
        not: a pin of bytes its owner's snapshot already holds adds nothing.
        One that is written in a folder store is complete, as any snapshot
        there is. A pin by ID never takes such a snapshot for its owner's
        (``made_by``).
        """
        entry = next((e for e in after.dependencies if e.get("id") == key), {})
        location = entry.get("location") or {}
        commit = location.get("commit")
        base = next((base for _, _, _, base in held if base is not None), None)
        # By the pipeline's own ID, as its clone names it, where a lockfile of 0.2 says nothing of it
        clone_entry = {
            "_from_id": location.get("pipeline"),
            "git": location.get("url"),
        }
        pipeline = entry.get("pinned_from") or (_pipeline_of_clone(Path(base), clone_entry, Path(base)) if base else None) or key
        try:
            validate_pipeline_id(pipeline)
            pending = self._store.begin(pipeline, commit, snapshot._now(), base=base, made_by="pin")
        except (ValueError, TypeError, StoreError):
            pending = None  # no pipeline or commit to file it under: an object no pipeline owns
        stored = {}
        try:
            for stand_in, path, links, _ in held:
                try:
                    stored[stand_in] = (pending or self._store).put(path, links=links)
                except (OSError, StoreError):
                    if stand_in in self.recheck:
                        continue  # only a name to add: it stays said as not whole
                    raise
            if pending is None:
                return stored
            # It adds nothing only where one recorded snapshot of the pipeline holds every asset put,
            # whole: not where each file is whole in some snapshot or other, which no read can use
            if not pending.placed and self._store.holds_whole(pipeline, {put.content_hash for put in stored.values() if put.stored}):
                pending.discard()
                return stored
            records = []
            # A pin kept as it was, whose bytes were put back from the clone,
            # holds its own hash in the lockfile, not the stand-in it was put by
            by_hash = {}
            for put in stored.values():
                if put.stored:
                    by_hash.setdefault(put.content_hash, []).append(put)

            def put_of(record: dict):
                """Of the puts of the record's bytes, the one put from its own path: two assets may share bytes, not a name."""
                puts = by_hash.get(record.get("content_hash"), [])
                own = str((record.get("location") or {}).get("path") or "").removeprefix("./").rstrip("/")
                for put in puts:
                    paths = [file["path"] for file in put.stored.get("files", ())]
                    if own and any(path == own or path.startswith(own + "/") for path in paths):
                        return put
                return puts[0] if puts else None

            for record in after.assets.values():
                put = stored.get(record.get("content_hash"))
                if put is None and record.get("pipeline") == key:
                    put = put_of(record)
                if put is None or not put.stored:
                    continue
                kept = snapshot.renamed(record, pipeline)
                kept.update(content_hash=put.content_hash, size_bytes=put.size_bytes, stored=put.stored)
                kept.pop("files", None)
                if put.entries and "files" in record:
                    kept["files"] = [
                        {"path": e.path, "size_bytes": e.size_bytes, "content_hash": e.content_hash} for e in put.entries
                    ]
                records.append(kept)
            code = {"commit": commit}
            subdirectory = (entry.get("location") or {}).get("subdirectory")
            if subdirectory:
                code["subdirectory"] = subdirectory
            document = {
                "schema": snapshot.SCHEMA,
                "root": pipeline,
                "code": code,
                "made_at": pending.made_at,
                "made_by": "pin",
                "records": sorted(records, key=lambda record: record["id"]),
            }
            pending.write(document)
        except BaseException:
            if pending is not None:
                pending.discard()
            raise
        return stored


def _refuse_a_cycle(project_dir: Path, root: str, store: Store, git_cache: Optional[GitCache], read: list, before: "Lock"):
    """The guard a pin has unless its caller gives one: a lockfile whose new pins close a cycle, or lead into one, is not written.

    Dependencies between pipelines must form a directed acyclic graph
    (:func:`chartbook.lineage.cycle`), whichever command pins: ``chartbook
    pin``, ``pin --update`` and ``add``, and the first read of a dependency. The
    walk goes from the dependencies whose entry the pin makes, or whose
    location or snapshot it changes (all the walk reads of an entry),
    with the lockfile as it would be written: one that leads back to this
    pipeline, or into pipelines that depend on each other, is refused. A
    cycle reached only through pins made before is not this pin's doing:
    ``chartbook run`` and ``chartbook run --check`` say it, and the pin, a read of
    another dependency say, is not refused for it. A pin that changes no
    entry walks nothing.
    """

    def refuse(after: Lock) -> Optional[str]:
        from chartbook import lineage

        # Where each is pinned from, which is all the walk reads: a hash a pin
        # holds back until the lockfile is let through is no change
        def pinned_from(entry: Optional[dict]) -> tuple:
            entry = entry or {}
            return json.dumps(entry.get("location"), sort_keys=True, default=str), entry.get("snapshot")

        filed = {entry.get("id"): entry for entry in before.dependencies}
        new = {entry.get("id") for entry in after.dependencies if pinned_from(filed.get(entry.get("id"))) != pinned_from(entry)}
        if not new:
            return None
        try:
            found = lineage.cycle(
                project_dir, store, git_cache=git_cache, lockfiles={project_dir: after},
                shared={"found": read[0]} if read else {}, through=new,
            )
        except snapshot.SnapshotError:
            return None  # no pipeline here: the pin itself said so
        if found is None:
            return None
        return (
            f"{root}: {lineage.cycle_lead(found)}, so there is no order to build in.\n"
            f"{lineage.explain_cycle(found)}\nThe lockfile was left as it was."
        )

    return refuse


def _has_a_pin(listed: object, records: dict, declared: dict) -> bool:
    """Whether a lockfile's entry for a dependency is a pin that `pin` keeps as it is.

    As ``pin`` decides it: a ``git`` dependency is pinned once its entry
    names a commit; one named by its ID and got from its repository, once
    something of it was pinned from that repository with its bytes
    (:func:`clone_instead`); any other once something of it was pinned with
    its bytes, or once its entry names the snapshot it was pinned from
    (:func:`names_a_snapshot`), which is all the lockfile has of one whose
    assets are all drawn anew by every build.
    """
    if not isinstance(listed, dict) or not isinstance(listed.get("location"), dict):
        return False
    location = listed["location"]
    if "git" in declared:
        return location.get("kind") == "git" and bool(location.get("commit"))
    if names_a_snapshot(listed):
        return True  # all there is of one none of whose assets is in the lockfile
    if declared.get("_store") and location.get("kind") == "git":
        return (
            bool(location.get("commit"))
            and location.get("pipeline") == declared["_store"]
            and holds_a_pin(listed, records)
        )
    return any(
        isinstance(record, dict) and record.get("content_hash") and not (record.get("ref") or {}).get("rev")
        for record in records.values()
    )


def would_pin(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    built_here: Iterable[str] = (),
) -> Optional[Lock]:
    """The lockfile as :func:`pin` would write it now, worked out and not written; None if it would pin nothing new.

    Only the dependencies with no pin yet are worked out: one that has a
    pin keeps it, as ``pin`` keeps it. Nothing is written: not the
    lockfile, not the store's note of it, and no object. What a pin would
    put in the store is not even read, so its records carry no hash: the
    lockfile says where each dependency would be pinned from, which is
    what ``chartbook run`` walks to find a cycle a pin would close before
    anything is pinned or built. A ``git`` dependency may be fetched into
    the git cache, and one named by its ID cloned there, as ``pin`` would.

    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    project_dir = Path(project_dir).resolve()
    _, dependencies = _read_pipeline(project_dir)
    locked = read_lock(project_dir / LOCK_FILE)
    listed = {entry["id"]: entry for entry in (locked.dependencies if locked is not None else [])}
    unpinned = {
        key for key in dependencies
        if not _has_a_pin(listed.get(key), locked.assets_of(key) if locked is not None else {}, dependencies[key])
    }
    if not unpinned:
        return None
    worked_out: list = []

    def keep(after: Lock) -> str:
        worked_out.append(after)
        return "only worked out"

    _sync(
        project_dir, _PutLater(store if store is not None else default_store(), hold=False), move=None,
        git_cache=git_cache, only=unpinned, built_here=built_here, before_writing=keep,
    )
    return worked_out[0] if worked_out else None


def update(
    project_dir: Union[str, Path] = ".",
    dependencies: Iterable[str] = (),
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    raise_floor: bool = False,
) -> PinReport:
    """Move a pipeline's pins forward to what its dependencies have now.

    A ``path`` dependency moves to its newest snapshot: the newest at the
    commit its folder is on or, if that commit has none, at the nearest
    one before it that has. A ``git`` dependency is fetched again, and its
    ``rev`` looked up again: a branch may have moved, a tag or a commit
    has not.

    :param project_dir: The pipeline's directory.
    :param dependencies: The dependencies to update, as named in
        ``[dependencies]`` (the scope may be left off when unambiguous).
        All of them by default.
    :param store: The store to pin into; this user's by default.
    :param raise_floor: Whether to raise the manifest's
        ``requires_chartbook`` where it admits a ChartBook that cannot
        read the lockfile (:func:`see_to_the_floor`), as ``chartbook pin
        --update`` does.
    :returns: What was done. An asset whose pin changed has the status
        ``moved``.
    :raises LockError: If *project_dir* is not a pipeline, its lockfile
        cannot be read, or a name is not one of its dependencies.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    return _sync(
        project_dir,
        store,
        move=list(dependencies),
        git_cache=git_cache,
        raise_floor=raise_floor,
    )


@dataclass
class GcPlan:
    """What clearing out a store would keep and what it would remove.

    Attributes:
        lockfiles: Each lockfile the store has a note of, and whether it
            could be found.
        kept: How many objects are kept: some lockfile or kept snapshot
            names them.
        snapshots: How many objects some kept snapshot names.
        snapshots_kept: Each snapshot that is kept, with why.
        snapshots_delete: Each snapshot that is to be removed, with why it
            may be.
        pinned_kept, pinned_delete: Likewise for the snapshots a pin made
            from a clone, where a ``git`` dependency's bytes are kept: not
            anyone's snapshots, and counted with the objects.
        recent: Objects that nothing names, stored too recently to remove.
        delete: Objects that nothing names, each with its size in bytes.
        not_read: Lockfiles a store names that are not read here, as they are
            not a local ``chartbook.lock``: what their notes name is kept.
        elsewhere: The notes of lockfiles on other machines, those from
            before notes named their machine, which may be another's, and
            a sync service's copies of notes: never forgotten from here;
            what they recorded is kept. They are not in *lockfiles*, which
            are this machine's.
        read_here: The paths of notes in *elsewhere* at which this machine
            has a lockfile, read as well: what it pins is kept too.
        forget_old: Lockfiles whose notes from before notes named their
            machine are to be removed, in this user's own store, where they
            can only be this machine's: one this machine has a note of now
            as well, which takes its place, and, with *forget_missing*, one
            that cannot be found.
        forget: Lockfiles that could not be found and are to be forgotten.
        files: For each object in *delete* that a snapshot holds, the names
            in the store of its files that no kept asset uses: what goes
            with it.
        recent_files: The names in the store of the files of the objects in
            *recent*: what is not removed, as they are not.
        unused: What no snapshot uses besides, each name with its size: a
            snapshot's folder begun and never written, a sync service's
            copies beside a snapshot's files (:meth:`chartbook.store.Store.tidy`).
            Empty in a plan that looks at no file (:func:`plan_gc` with ``looks=False``).
        kept_versions: Each version of an asset marked ``keep = true`` that
            a kept snapshot holds (:class:`chartbook.snapshot.KeptVersion`):
            what the marks keep, for the bill.
        copies: The files that go with the folders of the snapshots in
            *snapshots_delete* and are of objects that stay, each name in
            the store with its size: where each snapshot is complete, a
            snapshot that stays has its own copy of them. Not in *delete*,
            which is of objects nothing names; and not of what a record a
            pin made holds, which goes without a word.
        held_back: The pipelines none of whose snapshots is removed, as one
            of those that stay has lost a file of its own
            (:meth:`chartbook.store.Store.holes_left`): by the pipeline's
            ID, that snapshot's record, the first such file, and how many.
            Its snapshots that would have gone are in *snapshots_kept*,
            with :data:`HELD_BACK` for why. Empty in a plan that looks at no
            file (:func:`plan_gc` with ``looks=False``), which may then count
            a snapshot that this would hold back.
        forget_missing, recent_seconds, keep_days, keep_lineage, aggressive: What the plan was made
            with, so that it can be made again the same way when it is
            carried out.
        noted_by: For each snapshot a note pins, ``(commit, made_at)`` to
            the note's file name under ``_chartbook/roots/``: so ``store
            gc`` can say which note holds it.
    """

    lockfiles: list[tuple[Path, bool]] = field(default_factory=list)
    kept: int = 0
    snapshots: int = 0
    snapshots_kept: list = field(default_factory=list)
    snapshots_delete: list = field(default_factory=list)
    pinned_kept: list = field(default_factory=list)
    pinned_delete: list = field(default_factory=list)
    kept_versions: list = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    delete: list[tuple[str, int]] = field(default_factory=list)
    forget: list[Path] = field(default_factory=list)
    not_read: list[Path] = field(default_factory=list)
    elsewhere: list = field(default_factory=list)
    read_here: list[Path] = field(default_factory=list)
    forget_old: list[Path] = field(default_factory=list)
    files: dict = field(default_factory=dict)
    recent_files: set = field(default_factory=set)
    unused: list = field(default_factory=list)
    copies: dict = field(default_factory=dict)
    held_back: dict = field(default_factory=dict)
    #: The pipelines of *held_back* whose snapshot that stays has a file with other bytes than its record
    #: says, found by reading it (:func:`plan_gc` with *hashed*); for them *held_back* gives what is wrong
    not_intact: set = field(default_factory=set)
    noted_by: dict = field(default_factory=dict)
    forget_missing: bool = False
    recent_seconds: float = RECENT_SECONDS
    keep_days: float = snapshot.KEEP_DAYS
    keep_lineage: bool = False
    aggressive: bool = False
    hashed: bool = False
    #: Note file names left out of this plan (``--forget-note``), so a dry run can say what would go once the note is gone
    without_notes: tuple = ()

    @property
    def size_bytes(self) -> int:
        """The total size of the objects that would be removed: those nothing names."""
        return sum(size for _, size in self.delete)

    @property
    def copies_bytes(self) -> int:
        """The total size of *copies*: the removed snapshots' own copies of files that objects which stay have too."""
        return sum(self.copies.values())

    @property
    def unused_bytes(self) -> int:
        """The total size of *unused*: what no snapshot uses, which the real ``store gc`` removes with :meth:`~chartbook.store.Store.tidy`."""
        return sum(size for _, size in self.unused)

    @property
    def freed_bytes(self) -> int:
        """What carrying out the plan would free: the objects nothing names, the removed snapshots' own copies of files that objects which stay have too, and what no snapshot uses.

        What ``store gc`` says before it asks; after, it says what was freed (:class:`GcDone`).
        """
        return self.size_bytes + self.copies_bytes + self.unused_bytes


def plan_gc(
    store: Optional[Store] = None,
    forget_missing: bool = False,
    recent_seconds: float = RECENT_SECONDS,
    keep_days: float = snapshot.KEEP_DAYS,
    keep_lineage: bool = False,
    aggressive: bool = False,
    hashed: bool = False,
    looks: bool = True,
    pipeline: Optional[str] = None,
    without_notes: Optional[Iterable[str]] = None,
) -> GcPlan:
    """Work out what a store can let go of. Nothing is removed.

    First the snapshots: one is kept if a lockfile pins it, if a lockfile
    pins a model version by its label and it is the newest holding that
    version (a label resolves to a version an older snapshot may hold, which
    the pinned moment alone would not keep), if it is the newest of its
    pipeline, if a label points at a model version in it, or if it was made
    in the last *keep_days* days; and with *keep_lineage*, if
    a snapshot kept for any of these was made from it (or from a label
    pointing into it), as far up as that goes
    (:func:`chartbook.snapshot.plan_removals`). Then the objects: one is
    kept if a lockfile the store knows of names it, or a kept snapshot
    does. The store knows of every lockfile that was pinned or updated into
    it, and a note only ever adds to what is kept. What a note recorded at
    its lockfile's last pin is kept (its objects, and the snapshots it
    pins; for a note from before notes recorded snapshots, the newest
    snapshot holding each of its objects), and a lockfile on this machine is read
    as it is now as well, which adds what it pins after a pull or a switch
    of branch; one that cannot be found (a deleted project, a drive that is
    not plugged in) keeps what it named when it was last pinned, unless
    *forget_missing* is set. A note of a lockfile on another machine, which
    a store in a shared or synced folder has, keeps what it recorded and is
    never forgotten from here; so is a note from before notes named their
    machine, which may be another machine's, and a sync service's copy of
    a note. A lockfile here at the path of an old note, or of a copy of
    this machine's own, is read as well; another machine's path is never
    opened (it may be a mount of another host). In this user's own store,
    under ``~/.chartbook``, an old note can only be this machine's: its
    lockfile is read alone, as before notes named their machine, and the
    note is removed once this machine has a note of the lockfile and the
    lockfile is read (until then, what it recorded is kept), or, with
    *forget_missing*, once the lockfile is gone.

    :param store: The store; this user's by default.
    :param forget_missing: If True, a lockfile on this machine that cannot
        be found keeps nothing, and is forgotten when the plan is carried
        out. Another machine's lockfiles are never forgotten from here.
    :param recent_seconds: An unnamed object newer than this is left alone.
    :param hashed: For a plan that can lead to removal (``chartbook store
        gc``, its dry run too): where a snapshot that goes holds an asset a
        lockfile pins, the copy of it in the snapshot of its pipeline that
        stays, which a read is handed afterwards, is read and hashed, and
        if it is not what its record says nothing of that pipeline goes.
        Off by default: the line a snapshot ends with reads nothing.
    :param looks: Whether the plan may look at the files of the store's
        snapshots. False for the line a snapshot ends with, which removes
        nothing: the plan then asks nothing of the disk about them and
        goes by the records alone. It walks no pipeline's folder for what
        no snapshot uses (:attr:`GcPlan.unused` is empty), and it does
        not ask whether each snapshot that stays holds its files
        (:attr:`GcPlan.held_back` is empty), each of which asks about
        every file of many snapshots; *hashed* reads nothing either. So
        such a plan may count a snapshot that ``store gc`` would hold
        back because a snapshot of its pipeline that stays has lost a
        file; ``store gc`` and its dry run look, and are exact. What a
        sweep refuses before it looks at anything is still refused
        (:meth:`chartbook.store.Store.check_tidy`).
    :param keep_days: How long an unpinned snapshot that is not the newest
        of its pipeline is kept.
    :param pipeline: When set, the plan is narrowed to that pipeline's
        snapshots only: for the line after ``chartbook snapshot``, which
        says what ``store gc`` could remove of this pipeline and removes
        nothing. Whole-store ``store gc`` leaves it unset.
    :param without_notes: Note file names to leave out of the plan, as
        ``--forget-note`` does on a dry run: the note stays in the store,
        and the plan says what would go once it is gone.
    :returns: The plan, for :func:`run_gc`.
    :raises StoreError: If the store's notes cannot be read.
    :raises LockError: If a lockfile that is there cannot be read. Nothing
        is removed from a store when what it must keep is in doubt.
    """
    store = store if store is not None else default_store()
    # Asked many times over: the records are read once for the whole plan
    with store.reading():
        plan = _plan_gc(
            store, forget_missing, recent_seconds, keep_days, keep_lineage, aggressive, hashed, looks,
            without_notes=tuple(without_notes or ()),
        )
        if pipeline is not None:
            _narrow_to_pipeline(plan, pipeline, store)
    return plan


def _narrow_to_pipeline(plan: GcPlan, pipeline: str, store: Optional[Store] = None) -> None:
    """Leave only what of *pipeline* the plan would clear or keep: for the line after a snapshot of that pipeline.

    Objects nothing names, and unused files, are of no one pipeline: the
    reminder of one says nothing of them. Objects and copies that would go
    are only those in this pipeline's snapshot folders.
    """
    from chartbook.store import pipeline_folder

    plan.snapshots_delete = [(taken, why) for taken, why in plan.snapshots_delete if taken.pipeline == pipeline]
    plan.pinned_delete = [(taken, why) for taken, why in plan.pinned_delete if taken.pipeline == pipeline]
    plan.snapshots_kept = [(taken, why) for taken, why in plan.snapshots_kept if taken.pipeline == pipeline]
    plan.pinned_kept = [(taken, why) for taken, why in plan.pinned_kept if taken.pipeline == pipeline]
    plan.kept_versions = [kept for kept in plan.kept_versions if kept.pipeline == pipeline]
    plan.held_back = {key: value for key, value in plan.held_back.items() if key == pipeline}
    plan.not_intact = plan.not_intact & {pipeline}
    plan.recent = []
    plan.unused = []
    plan.recent_files = set()
    folder = pipeline_folder(pipeline)
    markers = (f"snapshots/{folder}/", f"increments/{folder}/", f"pipelines/{folder}/")

    def of_this(name: str) -> bool:
        normalized = name.replace("\\", "/")
        return any(normalized.startswith(marker) or f"/{marker}" in normalized for marker in markers)

    plan.copies = {name: size for name, size in plan.copies.items() if of_this(name)}
    if not plan.snapshots_delete and not plan.pinned_delete:
        plan.delete = []
        plan.files = {}
        return
    kept_delete = []
    kept_files = {}
    counted = set(plan.copies)
    for content_hash, _ in plan.delete:
        names = [name for name in plan.files.get(content_hash, ()) if of_this(name)]
        if not names:
            continue
        sizes = dict(store.files_of(content_hash)) if store is not None else {}
        freed = {name: sizes.get(name, 0) for name in names if name not in counted}
        counted |= set(freed)
        kept_files[content_hash] = names
        kept_delete.append((content_hash, sum(freed.values())))
    plan.delete = kept_delete
    plan.files = kept_files


def _plan_gc(
    store: Store, forget_missing: bool, recent_seconds: float, keep_days: float, keep_lineage: bool, aggressive: bool,
    hashed: bool = False, looks: bool = True, without_notes: tuple = (),
) -> GcPlan:
    """The rest of :func:`plan_gc`, within one reading of the store's records."""
    plan = GcPlan(
        forget_missing=forget_missing, recent_seconds=recent_seconds, keep_days=keep_days,
        keep_lineage=keep_lineage, aggressive=aggressive, hashed=hashed and looks,
        without_notes=tuple(without_notes),
    )
    keep: set[str] = set()
    pinned_snapshots: set[tuple[str, str]] = set()
    hashes_of_missing: set[str] = set()
    hashes_elsewhere: set[str] = set()
    hashes_noted: set[str] = set()
    from chartbook.store import this_machine

    labelled: dict[tuple[str, str, str, str], str] = {}

    def read_too(lockfile: Path) -> Optional[Lock]:
        """Add what a lockfile here pins now to what is kept; the lockfile, or None if there is none."""
        found = read_lock(lockfile)
        if found is None:
            return None
        keep.update(found.hashes())
        for entry in found.dependencies:
            commit = entry.get("location", {}).get("commit")
            if commit and entry.get("snapshot"):
                pinned_snapshots.add((commit, entry["snapshot"]))
        # A label resolves to a version an older snapshot may hold: a
        # snapshot holding each is kept, as the pinned moment's is
        for version in found.labelled():
            labelled.setdefault(version, "a lockfile pins a labelled version in it")
        return found

    noted: dict[tuple[str, str], str] = {}
    # Which note file under _chartbook/roots/ holds each noted pin, for the listing
    noted_by: dict[tuple[str, str], str] = {}

    def keep_noted(root, why: str, fallback: set, hashes: Optional[set] = None) -> None:
        """Keep what a note recorded: its objects, the snapshots it pins (or, for a note that names none, by its objects), and a snapshot holding each version it pins by label.

        Each snapshot pin is kept by its ``(commit, made_at)`` alone: a note
        from a branch or tag that is not checked out holds only the snapshot
        it names, never another of its commit (stand-ins are for a live
        lockfile's pins only).
        """
        from chartbook.store import _snapshot_triple

        keep.update(root.hashes)
        if root.snapshots is not None:
            for item in root.snapshots:
                _, commit, made_at = _snapshot_triple(item)
                noted.setdefault((commit, made_at), why)
                if root.note:
                    noted_by.setdefault((commit, made_at), root.note)
        # No list, or a list a partial read merged into such a note: the newest snapshot holding each object
        if root.keeps_newest():
            fallback.update(root.hashes if hashes is None else hashes)
        for version in root.labelled or ():
            labelled.setdefault(version, why.replace("pins it", "pins a labelled version in it"))

    # A note only ever adds to what is kept: what it recorded at its
    # lockfile's last pin is kept, and reading the lockfile as it is now
    # (after a pull, or a switch of branch) adds to that, never replaces it
    here = this_machine(create=False)  # a machine that has written no note has none of its own
    # In this user's own store, under ~/.chartbook, a note from before notes
    # named their machine can only be this machine's; elsewhere it may be any
    # machine's, and is kept with care
    own_store = _users_own_store(store)
    roots = [root for root in store.roots() if root.note not in plan.without_notes]
    # The paths this machine has a note of: an old note of this user's own
    # store at one of them is superseded by it (a pin or a read writes this
    # machine's note in its place), and is removed
    noted_here = {root.lockfile for root in roots if root.machine == here and not root.copy}
    for root in roots:
        old_and_mine = own_store and root.machine == "" and not root.copy
        if old_and_mine and root.lockfile in noted_here:
            # Superseded by this machine's note only once its lockfile is
            # read: while it cannot be (a drive unplugged), what the note
            # recorded is kept, as a note only adds; with forget_missing, it
            # is forgotten with the lockfile
            local = _a_local_lockfile(root.lockfile)
            if local and (read_too(root.lockfile) is not None or forget_missing):
                plan.forget_old.append(root.lockfile)
            else:
                keep_noted(root, "a lockfile that cannot be found pins it", hashes_of_missing)
            continue
        if (root.machine != here or root.copy) and not old_and_mine:
            # Another machine's lockfile, or one noted before notes named
            # their machine, or a sync service's copy of a note: the path
            # names a file on a machine that may not be this one. What the
            # note recorded is kept, and never taken as gone, even with
            # forget_missing, since only that machine can tell. A lockfile
            # here at the path of an old note, or of a copy of this
            # machine's own, is read as well, which can only add; another
            # machine's path is never opened (a mount of another host)
            plan.elsewhere.append(root)
            keep_noted(root, "a lockfile not read here, another machine's, pins it", hashes_elsewhere)
            if (
                root.machine in ("", here)
                and _a_local_lockfile(root.lockfile)
                and read_too(root.lockfile) is not None
            ):
                plan.read_here.append(root.lockfile)
            continue
        # A root is written by whoever can write to the store, and names a
        # path: only a lockfile on this machine is read, never another file
        # or a path on another host. One that is not read is never taken
        # as gone: what its note names is kept, even with forget_missing,
        # since it may be a real lockfile on a network drive
        if not _a_local_lockfile(root.lockfile):
            plan.lockfiles.append((root.lockfile, False))
            plan.not_read.append(root.lockfile)
            keep_noted(root, "a lockfile that is not read here pins it", hashes_of_missing)
            continue
        found = read_too(root.lockfile)
        plan.lockfiles.append((root.lockfile, found is not None))
        if found is not None:
            # What the note recorded and the lockfile no longer names, a pull
            # or a switch of branch since its last pin, stays kept; a note
            # from before notes named their machine goes by the lockfile
            # alone, as it did then, until a pin or a read takes its place
            if not old_and_mine:
                keep_noted(root, "its lockfile's note, from its last pin, pins it", hashes_noted, set(root.hashes) - found.hashes())
        elif forget_missing:
            (plan.forget_old if old_and_mine else plan.forget).append(root.lockfile)
        else:
            keep_noted(root, "a lockfile that cannot be found pins it", hashes_of_missing)

    plan.noted_by = noted_by
    try:
        snapshots = snapshot.plan_removals(
            store, pinned_snapshots, hashes_of_missing, keep_days=keep_days, keep_lineage=keep_lineage,
            aggressive=aggressive, hashes_elsewhere=hashes_elsewhere, hashes_noted=hashes_noted, noted=noted,
            labelled=labelled,
        )
    except snapshot.SnapshotError as error:
        raise LockError(str(error)) from None
    plan.snapshots_kept = snapshots.keep
    plan.snapshots_delete = snapshots.remove
    plan.kept_versions = snapshots.kept_versions
    _keep_what_only_they_hold(plan, keep)
    _plan_pinned(store, plan, keep, recent_seconds)
    _keep_what_an_increment_builds_on(store, plan)
    if looks:
        # Asks whether each file of each snapshot that stays is there, for every pipeline something goes from:
        # what keeps a real gc from removing a snapshot while one that stays lacks a file. A plan that removes
        # nothing and may not look goes by the records, and may count a snapshot that this would hold back
        _hold_back_where_one_that_stays_has_a_hole(store, plan, keep)
    named_by_snapshots = set().union(*(taken.hashes() for taken, _ in plan.snapshots_kept + plan.pinned_kept))
    plan.snapshots = len(named_by_snapshots)
    keep |= named_by_snapshots

    # Where each asset's files would be once the snapshots to be removed are gone. A store whose snapshots
    # are each complete says so (FolderStore.files_left): a removed snapshot's folder goes whole, with its
    # own copy of every file, whatever a snapshot that stays holds of the same bytes. Any other store (a
    # bucket, which keeps each file once; several read as one) is asked as before: every file stays where
    # a record names it
    going = [taken.path for taken, _ in plan.snapshots_delete + plan.pinned_delete]
    says_what_is_left = getattr(type(store), "files_left", Store.files_left) is not Store.files_left

    def files_left(content_hash: str) -> list:
        return store.files_left(content_hash, going) if says_what_is_left else store.files_of(content_hash)

    # A file another kept asset uses is not freed, and one two assets share is counted once
    kept_files = {name for content_hash in keep for name, _ in files_left(content_hash)}
    plan.files = {}
    counted: set = set()
    recent_files: set = set()
    stay: list = []
    for content_hash in store.hashes():
        if content_hash in keep:
            plan.kept += 1
            stay.append(content_hash)
            continue
        try:
            age = store.age_of(content_hash)
        except ObjectNotFoundError:
            continue  # gone since it was listed: another gc, or a put replacing it
        files = store.files_of(content_hash)
        left = store.files_left(content_hash, going) if files and says_what_is_left else files
        if age < recent_seconds and (left or not files):
            # Spared for being new, where something of it stays: an object no pipeline owns, or one a
            # snapshot that stays holds. One only removed snapshots hold goes with their folders
            plan.recent.append(content_hash)
            recent_files |= {name for name, _ in left}
            stay.append(content_hash)
            continue
        if files:
            freed = {name: size for name, size in files if name not in kept_files and name not in counted}
            counted |= set(freed)
            plan.files[content_hash] = sorted(name for name, _ in files if name not in kept_files)
            plan.delete.append((content_hash, sum(freed.values())))
        else:
            plan.delete.append((content_hash, store.size_of(content_hash)))
    plan.recent_files = recent_files
    if says_what_is_left and going:
        for content_hash in stay:
            staying = {name for name, _ in files_left(content_hash)}
            for name, size in store.files_of(content_hash):
                if name not in staying and name not in kept_files and name not in counted:
                    counted.add(name)
                    plan.copies[name] = size
    # And the one line an increment that goes has for a person, which is ChartBook's own and goes with its folder
    root = getattr(store, "root", None)
    for path in going if isinstance(root, Path) and getattr(type(store), "builds_on", None) is not None else []:
        note = Path(path).parent / "INCREMENT.txt"
        on = store.builds_on(Path(path))
        if on is None:
            continue
        if not looks:
            # Its size by what the record says it builds on: the line is ChartBook's own (store.increment_note)
            said = increment_note(on.parent.parent.parent.name, on.parent.parent.name)
            plan.copies[note.relative_to(root).as_posix()] = len(said.encode("utf-8"))
        elif note.is_file():
            plan.copies[note.relative_to(root).as_posix()] = note.stat().st_size
    if not looks:
        # The line a snapshot ends with says nothing of what a sweep would find, and a sweep asks the disk about
        # every file of every snapshot in the store. What one refuses before it looks at anything is refused still
        store.check_tidy()
        return plan
    # What no snapshot uses beside that: a snapshot never written, a sync service's copies
    named = {name for names in plan.files.values() for name in names}
    plan.unused = [(name, size) for name, size in store.tidy(dry_run=True, keep=recent_files) if name not in named]
    return plan


def _keep_what_only_they_hold(plan: "GcPlan", keep: set) -> None:
    """Keep a snapshot that holds bytes a lockfile pins and no kept snapshot of its pipeline holds: a snapshot's record is what says where its files are.

    The newest such first, so that of two holding the same bytes the newer
    is kept: the one a read is handed. Only its own pipeline's snapshots
    count as holding them (:func:`_held_by_pipeline`), since a read never
    takes another pipeline's copy.
    """
    held = _held_by_pipeline(plan.snapshots_kept)
    for taken, why in sorted(plan.snapshots_delete, key=lambda pair: pair[0].made_at, reverse=True):
        if (taken.hashes() & keep) - held.setdefault(taken.pipeline, set()):
            plan.snapshots_delete.remove((taken, why))
            plan.snapshots_kept.append((taken, "a lockfile pins bytes it alone holds"))
            held[taken.pipeline] |= taken.hashes()


#: Why ``store gc`` keeps a complete snapshot that nothing else keeps: an increment's files are in two folders, its own and this one
BUILT_ON = "an increment that stays builds on it"


def _keep_what_an_increment_builds_on(store: Store, plan: "GcPlan") -> None:
    """Keep a complete snapshot while an increment that stays builds on it (:meth:`chartbook.store.Store.builds_on`).

    An increment that goes, goes whole, and takes nothing of the one it
    builds on. An increment never builds on another, so one pass is enough.
    """
    asked = getattr(type(store), "builds_on", None)
    if asked is None:
        return  # several stores read as one are planned as before
    going = {str(taken.path) for taken, _ in plan.snapshots_delete}
    needed = set()
    for taken, _ in plan.snapshots_kept + plan.snapshots_delete:
        if str(taken.path) not in going:
            complete = asked(store, taken.path)
            if complete is not None:
                needed.add(str(complete))
    # Any complete snapshot, one a pin made too
    for delete, keeping in ((plan.snapshots_delete, plan.snapshots_kept), (plan.pinned_delete, plan.pinned_kept)):
        for taken, why in list(delete):
            if str(taken.path) in needed:
                delete.remove((taken, why))
                keeping.append((taken, BUILT_ON))


def _held_by_pipeline(kept: list) -> dict:
    """What the kept snapshots of each pipeline hold, by the pipeline's ID: the holders gc counts for that pipeline's assets."""
    held: dict = {}
    for taken, _ in kept:
        held.setdefault(taken.pipeline, set()).update(taken.hashes())
    return held


#: Why ``store gc`` removes no snapshot of a pipeline one of whose snapshots that stay has lost a file of its own
HELD_BACK = "a snapshot of its pipeline that stays has lost a file"
#: And where that snapshot has the file, with other bytes than its record says (:attr:`GcPlan.not_intact`)
HELD_BACK_OTHER_BYTES = "a snapshot of its pipeline that stays has a file with other bytes than its record says"


def _hold_back_where_one_that_stays_has_a_hole(store: Store, plan: "GcPlan", keep: frozenset = frozenset()) -> None:
    """Remove no snapshot of a pipeline one of whose snapshots that stay lacks a file of its own (:attr:`GcPlan.held_back`).

    Where each snapshot holds its own copy of every file, one folder can
    lose a file that another still has (a sync that has not brought it, a
    file removed by hand), and a read of the one with the hole is handed
    another's copy. So while a snapshot that stays has a hole, every
    snapshot of its pipeline stays, and the command says which snapshot and
    which file. Bytes in another pipeline never count, and a snapshot that
    is itself to go holds nothing back, whatever it has lost.
    """
    going = [taken.path for taken, _ in plan.snapshots_delete + plan.pinned_delete]
    # Asked of one store, as what is left is (files_left): several read as one are planned as before
    asked = getattr(type(store), "holes_left", None)
    plan.held_back = asked(store, going) if asked is not None and going else {}
    if plan.hashed:
        # A plan that can lead to removal reads the copy a read is handed once the other has gone
        other_bytes = _holders_with_other_bytes(store, plan, keep)
        plan.not_intact = set(other_bytes)
        plan.held_back.update(other_bytes)
    for delete, keeping in ((plan.snapshots_delete, plan.snapshots_kept), (plan.pinned_delete, plan.pinned_kept)):
        for taken, why in list(delete):
            if taken.pipeline in plan.held_back:
                delete.remove((taken, why))
                keeping.append((taken, HELD_BACK_OTHER_BYTES if taken.pipeline in plan.not_intact else HELD_BACK))


def _holders_with_other_bytes(store: Store, plan: "GcPlan", keep: frozenset) -> dict:
    """Each pipeline one of whose snapshots that stay holds, with other bytes than its record says, an asset a lockfile pins that a snapshot which goes holds too: as :attr:`GcPlan.held_back` has it.

    A snapshot that holds a pinned asset goes only when a snapshot of its
    pipeline that stays holds that asset intact, read and hashed. The one
    read is the copy a read is handed once the other has gone: the newest
    that stays of that pipeline, and the newest that stays of the going
    one's own commit, which an entry that names a commit and no time is
    read from. Each asset of each snapshot is read once, and only where a
    copy of it would go; a pipeline already held back is not asked.
    """
    check = getattr(type(store), "verify_snapshot", None)
    if check is None or getattr(type(store), "holes_of", Store.holes_of) is Store.holes_of:
        return {}  # several stores read as one; or one that keeps each file once, where nothing that goes takes a file that stays
    staying: dict = {}
    builds_on = getattr(store, "builds_on", lambda _: None)
    for taken, _ in sorted(
        plan.snapshots_kept + plan.pinned_kept,
        key=lambda pair: (builds_on(pair[0].path) is None, pair[0].made_at),
        reverse=True,
    ):
        staying.setdefault(taken.pipeline, []).append(taken)
    found: dict = {}
    read: dict = {}
    files_read: dict = {}  # each file's hash as read, by where it is: two increments may name one file of the snapshot they build on
    for going, _ in plan.snapshots_delete + plan.pinned_delete:
        if going.pipeline in plan.held_back or going.pipeline in found:
            continue
        for content_hash in sorted(going.hashes() & keep):
            # Every snapshot of the pipeline that stays and names it: a read by its name, by its commit or
            # by neither is handed one of them, and which is not for a plan to guess. Each file is read once
            for holder in (taken for taken in staying.get(going.pipeline, []) if content_hash in taken.hashes()):
                asked = (str(holder.path), content_hash)
                if asked not in read:
                    read[asked] = check(store, holder.path, [content_hash], only=True, read=files_read)
                if read[asked] and going.pipeline not in found:
                    found[going.pipeline] = (holder.path, read[asked][0].message, len(read[asked]))
    return found


def _plan_pinned(store: Store, plan: "GcPlan", keep: set, recent_seconds: float) -> None:
    """Which snapshots a pin made from a clone are kept, and which go.

    They are where a ``git`` dependency's pinned bytes are kept, not
    anyone's snapshots: newest first, one is kept while it holds bytes a
    lockfile pins that nothing kept holds, and one stored in the last
    *recent_seconds* is left alone (what it alone names is recent, as an
    object is).
    """

    def age(taken) -> float:
        ages = []
        for content_hash in taken.asset_hashes():
            try:
                ages.append(store.age_of(content_hash))
            except ObjectNotFoundError:
                continue
        return min(ages, default=float("inf"))

    pinned = []
    for path in store.pinned_snapshot_files():
        try:
            pinned.append(snapshot.read(path))
        except snapshot.SnapshotError as error:
            raise LockError(f"{error}. Nothing is removed from a store when what it must keep is in doubt.") from None
    held = _held_by_pipeline(plan.snapshots_kept)  # by the pipeline's own snapshots alone, as a read finds them
    for taken in sorted(pinned, key=lambda taken: taken.made_at, reverse=True):
        if (taken.hashes() & keep) - held.setdefault(taken.pipeline, set()):
            plan.pinned_kept.append((taken, "a lockfile pins what it holds"))
            held[taken.pipeline] |= taken.hashes()
        elif age(taken) >= recent_seconds:
            plan.pinned_delete.append((taken, "no lockfile pins what it alone holds"))


def _users_own_store(store: Store) -> bool:
    """Whether a store is this user's own: a folder under ``~/.chartbook`` (:meth:`chartbook.store.FolderStore.is_users_own`)."""
    from chartbook.store import FolderStore

    return isinstance(store, FolderStore) and store.is_users_own()


class GcError(LockError):
    """Raised by :func:`run_gc` when something the plan said to remove could not be: it removed the rest.

    In a store users share, an object or a record another user put there
    may be in a folder of theirs this user cannot write. Everything else in
    the plan is removed first, and the objects a record that stayed names
    stay with it.

    Attributes:
        removed_snapshots: How many snapshots were removed.
        removed: How many objects were removed.
        size_bytes: The size of what was removed, as the plan had it: the
            objects, and the removed snapshots' own copies of files that
            objects which stay have too (:attr:`GcPlan.copies`).
        failures: Each thing that could not be removed, as ``(what, why)``:
            what it is, and the store's words on why and what to do.
    """

    def __init__(self, removed_snapshots: int, removed: int, size_bytes: int, failures: list[tuple[str, str]], pinned: int = 0):
        #: How many snapshots a pin made from a repository were removed
        self.pinned = pinned
        self.removed_snapshots = removed_snapshots
        self.removed = removed
        self.size_bytes = size_bytes
        self.failures = failures
        said = "\n".join(f"  {what}: {why}" for what, why in failures)
        super().__init__(
            f"{len(failures)} thing(s) could not be removed; {removed_snapshots} snapshot(s)"
            f"{f', {pinned} snapshot(s) a pin made from a repository' if pinned else ''} and {removed} "
            f"object(s) were:\n{said}"
        )


@dataclass
class GcDone:
    """What carrying out a plan removed, and what it kept after all (:func:`carry_out_gc`).

    Attributes:
        snapshots: How many snapshots were removed.
        objects: How many objects were removed.
        freed_bytes: The size of what was removed, as the plan had it: the
            objects, and the removed snapshots' own copies of files that
            objects which stay have too (:attr:`GcPlan.copies`).
        kept_after_all: Each snapshot the plan said to remove that the plan
            made again keeps, with why it keeps it.
        objects_kept: How many objects the plan said to remove that stay:
            a lockfile or a snapshot names or uses them now.
        held_back: :attr:`GcPlan.held_back` of the plan made again.
    """

    snapshots: int = 0
    objects: int = 0
    freed_bytes: int = 0
    kept_after_all: list = field(default_factory=list)
    objects_kept: int = 0
    held_back: dict = field(default_factory=dict)
    #: Each snapshot the plan made again keeps, with why: what says why one that lacks a file stays
    kept: list = field(default_factory=list)
    #: :attr:`GcPlan.not_intact` of the plan made again
    not_intact: set = field(default_factory=set)
    #: How many snapshots a pin made from a repository were removed
    pinned: int = 0


def run_gc(plan: GcPlan, store: Optional[Store] = None) -> tuple[int, int]:
    """Carry out a plan from :func:`plan_gc`; how many snapshots and how many objects were removed (:func:`carry_out_gc`, which says more)."""
    done = carry_out_gc(plan, store)
    return done.snapshots, done.objects


def carry_out_gc(plan: GcPlan, store: Optional[Store] = None) -> GcDone:
    """Carry out a plan from :func:`plan_gc`: remove what it says to remove.

    The plan was made before anyone said yes, and a pin may have landed in
    between and taken something it names, or a snapshot that stays lost a
    file. So the plan is made again now, and only what both say may go is
    removed.

    :returns: What was removed, and what was kept after all.
    :raises GcError: If something could not be removed (another user's, in
        a store users share), once everything else has been; it says what
        was removed and what was not, and what to do about each.
    :raises StoreError: If the store cannot be read to make the plan again;
        nothing is then removed.
    :raises LockError: If a lockfile cannot be read, likewise.
    """
    store = store if store is not None else default_store()
    now = plan_gc(
        store,
        forget_missing=plan.forget_missing,
        recent_seconds=plan.recent_seconds,
        keep_days=plan.keep_days,
        keep_lineage=plan.keep_lineage,
        aggressive=plan.aggressive,
        hashed=True,  # whatever plan it is handed: nothing is removed on what was not read
        without_notes=plan.without_notes,
    )
    from chartbook import versions

    failures: list[tuple[str, str]] = []
    still_removable = {taken.path for taken, _ in now.snapshots_delete}
    removed_snapshots = 0
    kept_back: set[str] = set()  # what a record that could not be removed still names
    kept_bases: set[str] = set()  # complete base snapshots that an unremoved increment still builds on
    builds_on = getattr(store, "builds_on", lambda record: None)
    # Increments first: what one builds on is there for as long as it is
    for taken, _ in sorted(plan.snapshots_delete, key=lambda pair: builds_on(pair[0].path) is None):
        if taken.path not in still_removable:
            continue
        if str(taken.path) in kept_bases:
            kept_back |= taken.hashes()
            continue
        try:
            gone = snapshot.remove(store, taken)
        except (StoreError, OSError) as error:
            failures.append((f"the snapshot of {taken.pipeline} at {taken.commit[:7]}, made {taken.made_at}", str(error)))
            kept_back |= taken.hashes()
            base = builds_on(taken.path)
            if base is not None:
                kept_bases.add(str(base))
            continue
        if gone:
            removed_snapshots += 1
            versions.forget(taken)  # its site, kept for catalogs on this machine
    still_unnamed = {content_hash for content_hash, _ in now.delete}
    removed = 0
    size_bytes = 0
    # Where a git dependency's bytes were kept, which only a pin made
    still_pinned = {taken.path for taken, _ in now.pinned_delete}
    removed_pinned = 0
    for taken, _ in plan.pinned_delete:
        if taken.path not in still_pinned:
            continue
        if str(taken.path) in kept_bases:
            kept_back |= taken.hashes()
            continue
        try:
            removed_pinned += 1 if snapshot.remove(store, taken) else 0
        except (StoreError, OSError) as error:
            failures.append((f"where a pin kept {taken.pipeline} at {taken.commit[:7]}", str(error)))
            kept_back |= taken.hashes()
    # What the cleared snapshots held goes now, file by file, but what a
    # snapshot that stays uses
    stuck: dict = {}
    tidied: dict = {}  # each file that went, with its size
    try:
        # Never what either plan spared for being new
        tidied = dict(store.tidy(keep=plan.recent_files | now.recent_files))
    except TidyError as error:
        stuck = dict(error.failed)
        tidied = dict(error.removed)
        if not any(name in stuck for names in plan.files.values() for name in names):
            failures.append(("what no snapshot uses", str(error)))
    except (StoreError, OSError) as error:
        failures.append(("what no snapshot uses", str(error)))
    # What a snapshot still holds stays: only an object no pipeline owns is removed by its hash
    held = store.held_hashes()
    objects_kept = 0
    for content_hash, size in plan.delete:
        if content_hash not in still_unnamed or content_hash in kept_back or content_hash in held:
            objects_kept += 1
            continue
        left = [name for name in plan.files.get(content_hash, ()) if name in stuck]
        if left:
            failures.append((
                f"the object {content_hash}",
                f"Cannot remove the object {content_hash} at {store.shown(left[0])}: {stuck[left[0]]}",
            ))
            continue
        files = plan.files.get(content_hash)
        try:
            if files is None:
                gone = store.delete_unowned(content_hash)
            else:
                # Its files went with its snapshots, or were not there to go; one still there was taken
                # up by a snapshot being made meanwhile
                left = set(files) - set(tidied)
                if left and isinstance(getattr(store, "root", None), Path):
                    left = {name for name in left if os.path.lexists(store.root / name)}
                gone = not left
        except (StoreError, OSError) as error:
            failures.append((f"the object {content_hash}", str(error)))
            continue
        if gone:
            removed += 1
            size_bytes += size if files is None else 0  # an object no pipeline owns; a file is counted below
        elif files is not None:
            objects_kept += 1  # a snapshot being made took one of its files up
    # Every file that went with a folder, as the disk had it: the removed snapshots' own, a pin-made one's among them
    size_bytes += sum(tidied.values())
    # Only what both plans forget: a drive plugged back in before the yes brings its lockfile back
    for lockfile, machine in [(lockfile, None) for lockfile in set(plan.forget) & set(now.forget)] + [
        (lockfile, "") for lockfile in set(plan.forget_old) & set(now.forget_old)
    ]:
        try:
            store.remove_root(lockfile, machine=machine)
        except (StoreError, OSError) as error:
            failures.append((f"the note of the lockfile {lockfile}", str(error)))
    if failures:
        raise GcError(removed_snapshots, removed, size_bytes, failures, pinned=removed_pinned)
    why_now = {taken.path: why for taken, why in now.snapshots_kept + now.pinned_kept}
    kept_after_all = [(taken, why_now[taken.path]) for taken, _ in plan.snapshots_delete + plan.pinned_delete if taken.path in why_now]
    return GcDone(
        removed_snapshots, removed, size_bytes, kept_after_all, objects_kept, now.held_back, now.snapshots_kept + now.pinned_kept,
        not_intact=now.not_intact, pinned=removed_pinned,
    )
