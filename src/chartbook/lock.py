"""The lockfile: ``chartbook.lock``, the exact bytes a pipeline depends on.

A pipeline declares which pipelines it reads from in ``[dependencies]``.
*Pinning* freezes what it reads: every asset each of those pipelines
declares is put in the store (:mod:`chartbook.store`), and its content hash
is written to ``chartbook.lock`` beside the manifest. The lockfile is
source. Commit it: a change to what a project depends on then shows up in
a diff, and someone who clones the project can see exactly which data it
was built against.

::

    from chartbook import lock

    report = lock.pin("path/to/pipeline")       # pin what has no pin yet
    report = lock.update("path/to/pipeline")    # move every pin forward

``pin`` never moves a pin that exists. It pins what has none (a new
dependency, an asset the other pipeline has started to declare) and puts
back in the store anything the lockfile names that the store has lost, if
the other pipeline still has those bytes. ``update`` is the one thing that
moves a pin, to whatever the other pipeline has now.

The file is JSON in the index's own format: the same envelope, and records
with the same field names (``docs_src/design/index-schema.md``). It holds
this pipeline's ``Pipeline`` record, cut down to its ``dependencies``, and
one record for each asset of each dependency, cut down to its ``id``, its
declared ``path`` and its ``content_hash``. There is no timestamp, no
ChartBook version and no absolute path in it, so pinning twice with nothing
changed writes the same bytes.

An asset the other pipeline declares and has not built is recorded without
a ``content_hash``. It is not pinned, and asking for it will fail.

Nothing reads the lockfile to resolve a reference yet; that is the next
part. The design is "Pinning and isolation" in
``docs_src/design/asset-graph.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from chartbook import hashing
from chartbook.identity import derive_pipeline_id, strip_url_credentials
from chartbook.index import RECORD_VERSION, SCHEMAS_DIR, record_kind
from chartbook.manifest import (
    _read_manifest_file,
    resolve_project_type,
    validate_dependencies,
)
from chartbook.refs import AssetRef
from chartbook.resolve import MANIFEST_NAME, declared_files, locate_pipeline
from chartbook.store import FROZEN_LINKS, Store, default_store

#: The lockfile's name, beside ``chartbook.toml``.
LOCK_FILE = "chartbook.lock"

#: The version of the lockfile's envelope.
SCHEMA = "chartbook/lock/v1"

#: An unreferenced object stored more recently than this is not removed by
#: :func:`plan_gc`. Someone may be in the middle of pinning it: it is in
#: the store before the lockfile that names it is written.
RECENT_SECONDS = 3600


def schema_path() -> Path:
    """The JSON Schema file for the lockfile's envelope.

    An asset record in a lockfile fits the index's schema for its kind
    (:func:`chartbook.index.schema_path`), with fields left out.
    """
    return SCHEMAS_DIR / "lock" / "v1.json"


class LockError(Exception):
    """Raised when a lockfile cannot be read, or a project cannot be pinned."""


@dataclass
class Lock:
    """What a lockfile holds.

    Attributes:
        root: The ID of the pipeline the lockfile belongs to.
        dependencies: Its dependencies, as its ``Pipeline`` record lists
            them: ``id``, ``via``, ``location``, and ``pinned_hash`` when
            something of it is pinned.
        assets: One record for each asset of each dependency, by asset ID.
            A record with a ``content_hash`` is a pin.
    """

    root: str
    dependencies: list[dict] = field(default_factory=list)
    assets: dict[str, dict] = field(default_factory=dict)

    def hashes(self) -> set[str]:
        """The content hash of every pinned asset: what the store must keep."""
        return {
            record["content_hash"]
            for record in self.assets.values()
            if record.get("content_hash")
        }

    def assets_of(self, dependency: str) -> dict[str, dict]:
        """The records of one dependency's assets, by asset ID."""
        return {
            asset_id: record
            for asset_id, record in self.assets.items()
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


def read_lock(path: Union[str, Path]) -> Optional[Lock]:
    """Read a lockfile.

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
        if document.get("schema") != SCHEMA:
            raise ValueError(
                f"its schema is {document.get('schema')!r}, and this version of "
                f"ChartBook reads {SCHEMA!r}"
            )
        lock = Lock(root=document["root"])
        for record in document["records"]:
            if record.get("kind") == "Pipeline":
                lock.dependencies = list(record.get("dependencies", []))
            elif "id" in record:
                lock.assets[record["id"]] = record
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise LockError(f"Cannot read {path}: {error}") from None
    return lock


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
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return True


def pinned_hash(records: Iterable[dict]) -> Optional[str]:
    """One hash over everything pinned of a dependency.

    It is the SHA-256 of a listing with a line per pinned asset,
    ``<hex of its content hash>``, two spaces, ``<its ID>``, newline, sorted
    by ID: the form a directory is hashed in. It changes when any pin of
    the dependency does, so one line of a diff says a dependency moved.

    :returns: The hash, or None if nothing of the dependency is pinned.
    """
    lines = sorted(
        (record["id"], record["content_hash"].split(":", 1)[1])
        for record in records
        if record.get("content_hash")
    )
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
            ``dropped`` (no longer declared, so no longer pinned). For a
            whole dependency: ``removed`` (no longer in ``[dependencies]``),
            ``unreachable`` (its directory holds no pipeline), ``not_fetched``
            (a ``git`` dependency, which is not fetched yet).
        dependency: The dependency's key in ``[dependencies]``.
        asset: The asset's ID, or None when the event is about the whole
            dependency.
        old: The content hash it was pinned at, if it was.
        new: The content hash it is pinned at now, if it is.
        detail: More to say: a path, or why.
        linked: True if the bytes just stored are a hard link or a symlink
            to the other pipeline's own file, and so can still change.
    """

    status: str
    dependency: str
    asset: Optional[str] = None
    old: Optional[str] = None
    new: Optional[str] = None
    detail: str = ""
    linked: bool = False


#: The statuses that mean a project is not fully pinned, and should fail CI.
PROBLEM_STATUSES = frozenset({"lost", "unreachable"})


@dataclass
class PinReport:
    """What a ``pin`` or an ``update`` did.

    Attributes:
        lockfile: The lockfile's path.
        events: Everything that happened, in order: by dependency, then by
            asset.
        written: True if the lockfile was written; False if it already said
            what it would have.
    """

    lockfile: Path
    events: list[PinEvent] = field(default_factory=list)
    written: bool = False

    def count(self, *statuses: str) -> int:
        """How many events have one of these statuses."""
        return sum(event.status in statuses for event in self.events)

    @property
    def problems(self) -> list[PinEvent]:
        """The events that mean something could not be pinned."""
        return [event for event in self.events if event.status in PROBLEM_STATUSES]


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
    if "git" in entry:
        location = {"kind": "git", "url": strip_url_credentials(entry["git"])}
        if entry.get("rev"):
            location["rev"] = entry["rev"]
        return {"id": key, "via": "rev", "location": location}
    return {"id": key, "via": "path", "location": {"kind": "path", "path": entry["path"]}}


def _asset_record(
    ref: AssetRef, dependency: str, declared_path: str, content
) -> dict:
    """An asset as the lockfile records it; pinned if *content* is given."""
    record = {
        "kind": record_kind(ref.kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": dependency,
        "location": {"kind": "file", "path": declared_path},
    }
    if content is not None:
        record["content_hash"] = content.content_hash
        record["size_bytes"] = content.size_bytes
    return record


def _sync(
    project_dir: Union[str, Path],
    store: Optional[Store],
    move: Optional[Iterable[str]],
) -> PinReport:
    """Bring a pipeline's lockfile and the store in line with its manifest.

    :param move: None to leave every existing pin where it is (``pin``).
        Otherwise the dependencies whose pins may move (``update``); empty
        means all of them.
    """
    project_dir = Path(project_dir).resolve()
    store = store if store is not None else default_store()
    root, dependencies = _read_pipeline(project_dir)
    lock_path = project_dir / LOCK_FILE
    before = read_lock(lock_path) or Lock(root=root)

    moving: set = set()
    if move is not None:
        named = list(move)
        try:
            moving = {
                locate_pipeline(name, dependencies=dependencies).id for name in named
            }
        except KeyError as error:
            raise LockError(
                f"{error.args[0]} `chartbook update` takes the names of this "
                f"pipeline's dependencies."
            ) from None
        if not named:
            moving = set(dependencies)

    report = PinReport(lockfile=lock_path)
    after = Lock(root=root)
    cache = hashing.HashCache()

    locked_before = {entry["id"] for entry in before.dependencies}
    for key in sorted(locked_before - set(dependencies)):
        report.events.append(PinEvent("removed", key))

    for key in sorted(dependencies):
        entry = dependencies[key]
        listed = _dependency_entry(key, entry)
        records = _sync_dependency(
            key, entry, before.assets_of(key), key in moving, store, cache, report
        )
        overall = pinned_hash(records.values())
        if overall is not None:
            listed["pinned_hash"] = overall
        after.dependencies.append(listed)
        after.assets.update(records)

    # With nothing to lock and no lockfile yet, do not make an empty one
    if dependencies or lock_path.exists():
        report.written = write_lock(after, lock_path)
    hashes = after.hashes()
    if hashes:
        store.add_root(lock_path, hashes)
    else:
        store.remove_root(lock_path)
    return report


def _sync_dependency(
    key: str,
    entry: dict,
    had: dict[str, dict],
    may_move: bool,
    store: Store,
    cache: hashing.HashCache,
    report: PinReport,
) -> dict[str, dict]:
    """Work out the records of one dependency's assets, pinning as needed.

    :param had: The records the lockfile has for it now, by asset ID.
    :param may_move: Whether its existing pins may move (an update).
    :returns: Its records as they should be, by asset ID.
    """
    if "git" in entry:
        report.events.append(
            PinEvent("not_fetched", key, detail=strip_url_credentials(entry["git"]))
        )
        for record in had.values():
            _report_kept(record, key, store, report)
        return dict(had)

    directory = Path(entry["_resolved_path"])
    try:
        declared = declared_files(directory)
    except (OSError, ValueError) as error:
        # What is pinned stays pinned. That is the point of pinning: the
        # other pipeline can go away and this one still has its data.
        pinned = [record for record in had.values() if record.get("content_hash")]
        if not pinned or may_move:
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
        )

    # What the lockfile has that the other pipeline no longer declares
    for asset_id in sorted(set(had) - set(records)):
        old = had[asset_id].get("content_hash")
        if not old:
            continue  # it was never pinned; there is nothing to let go of
        if may_move:
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
    if store.has(pinned):
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
) -> dict:
    """Decide what one asset's record is, storing its bytes if they are needed."""
    asset_id = str(ref)
    old = (had or {}).get("content_hash")

    def put() -> tuple:
        stored = store.put(absolute)
        linked = stored.created and not set(stored.links) <= FROZEN_LINKS
        return stored, linked

    if old is None or may_move:
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            if old is not None:
                # An update with nothing to move to: the pin stays
                _report_kept(had, key, store, report)
                return had
            report.events.append(
                PinEvent("not_built", key, asset_id, detail=declared_path)
            )
            return _asset_record(ref, key, declared_path, None)
        stored, linked = put()
        if old is None:
            status = "pinned"
        elif stored.content_hash == old:
            status = "kept"
        else:
            status = "moved"
        report.events.append(
            PinEvent(
                status, key, asset_id, old=old, new=stored.content_hash, linked=linked
            )
        )
        return _asset_record(ref, key, declared_path, stored)

    # It has a pin, and `pin` does not move one
    try:
        current = hashing.hash_path(absolute, cache)
    except OSError as error:
        warnings.warn(f"Could not read {absolute}: {error}", stacklevel=2)
        current = None
    same = current is not None and current.content_hash == old
    if store.has(old):
        status = "kept" if same else "stale"
        report.events.append(PinEvent(status, key, asset_id, old=old, new=old))
    elif same:
        _, linked = put()
        report.events.append(
            PinEvent("restored", key, asset_id, old=old, new=old, linked=linked)
        )
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
    project_dir: Union[str, Path] = ".", store: Optional[Store] = None
) -> PinReport:
    """Pin whatever a pipeline depends on that has no pin yet.

    Every asset each dependency declares is put in the store and recorded
    in ``chartbook.lock``. A pin that already exists is left exactly where
    it is, whatever the other pipeline has done since: :func:`update` is
    what moves one. If the store has lost a pinned object and the other
    pipeline still has the same bytes, it is put back.

    An asset that is declared and not built is recorded as not pinned; the
    rest of the dependency is pinned all the same.

    :param project_dir: The pipeline's directory.
    :param store: The store to pin into; this user's by default.
    :returns: What was done.
    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    return _sync(project_dir, store, move=None)


def update(
    project_dir: Union[str, Path] = ".",
    dependencies: Iterable[str] = (),
    store: Optional[Store] = None,
) -> PinReport:
    """Move a pipeline's pins forward to what its dependencies have now.

    :param project_dir: The pipeline's directory.
    :param dependencies: The dependencies to update, as named in
        ``[dependencies]`` (the scope may be left off when unambiguous).
        All of them by default.
    :param store: The store to pin into; this user's by default.
    :returns: What was done. An asset whose pin changed has the status
        ``moved``.
    :raises LockError: If *project_dir* is not a pipeline, its lockfile
        cannot be read, or a name is not one of its dependencies.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    return _sync(project_dir, store, move=list(dependencies))


@dataclass
class GcPlan:
    """What clearing out a store would keep and what it would remove.

    Attributes:
        lockfiles: Each lockfile the store has a note of, and whether it
            could be found.
        kept: How many objects some lockfile names.
        recent: Objects that no lockfile names, stored too recently to
            remove.
        delete: Objects that no lockfile names, each with its size in bytes.
        forget: Lockfiles that could not be found and are to be forgotten.
    """

    lockfiles: list[tuple[Path, bool]] = field(default_factory=list)
    kept: int = 0
    recent: list[str] = field(default_factory=list)
    delete: list[tuple[str, int]] = field(default_factory=list)
    forget: list[Path] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        """The total size of what would be removed."""
        return sum(size for _, size in self.delete)


def plan_gc(
    store: Optional[Store] = None,
    forget_missing: bool = False,
    recent_seconds: float = RECENT_SECONDS,
) -> GcPlan:
    """Work out what a store can let go of. Nothing is removed.

    An object is kept if a lockfile the store knows of names it. The store
    knows of every lockfile that was pinned or updated into it. A lockfile
    is read as it is now; one that cannot be found (a deleted project, a
    drive that is not plugged in) still keeps what it named when it was
    last pinned, unless *forget_missing* is set.

    :param store: The store; this user's by default.
    :param forget_missing: If True, a lockfile that cannot be found keeps
        nothing, and is forgotten when the plan is carried out.
    :param recent_seconds: An unnamed object newer than this is left alone.
    :returns: The plan, for :func:`run_gc`.
    :raises StoreError: If the store's notes cannot be read.
    :raises LockError: If a lockfile that is there cannot be read. Nothing
        is removed from a store when what it must keep is in doubt.
    """
    store = store if store is not None else default_store()
    plan = GcPlan()
    keep: set[str] = set()
    for root in store.roots():
        found = read_lock(root.lockfile)
        plan.lockfiles.append((root.lockfile, found is not None))
        if found is not None:
            keep |= found.hashes()
        elif forget_missing:
            plan.forget.append(root.lockfile)
        else:
            keep |= set(root.hashes)

    for content_hash in store.hashes():
        if content_hash in keep:
            plan.kept += 1
        elif store.age_of(content_hash) < recent_seconds:
            plan.recent.append(content_hash)
        else:
            plan.delete.append((content_hash, store.size_of(content_hash)))
    return plan


def run_gc(plan: GcPlan, store: Optional[Store] = None) -> int:
    """Carry out a plan from :func:`plan_gc`: remove what it says to remove.

    :returns: How many objects were removed.
    """
    store = store if store is not None else default_store()
    removed = sum(store.delete(content_hash) for content_hash, _ in plan.delete)
    for lockfile in plan.forget:
        store.remove_root(lockfile)
    return removed
