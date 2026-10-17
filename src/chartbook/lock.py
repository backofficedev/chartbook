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
either way. Pinning from a folder as it stands is still there, as
``from_folder``, for someone working on both pipelines at once.

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
one record for each asset of each dependency, cut down to its ``id``, its
declared ``path`` and its ``content_hash``. There is no timestamp, no
ChartBook version and no absolute path in it, so pinning twice with nothing
changed writes the same bytes.

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

from chartbook import hashing, snapshot
from chartbook.gitcache import GitCache, GitError, default_git_cache, local_url
from chartbook.identity import derive_pipeline_id, repository_key, strip_url_credentials
from chartbook.index import RECORD_VERSION, SCHEMAS_DIR
from chartbook.manifest import (
    _read_manifest_file,
    resolve_project_type,
    validate_dependencies,
)
from chartbook.refs import AssetRef
from chartbook.resolve import MANIFEST_NAME, _same_directory, declared_files, locate_pipeline
from chartbook.snapshot import asset_record as _asset_record
from chartbook.store import ReadOnlyStoreError, Store, StoreError, default_store

#: The lockfile's name, beside ``chartbook.toml``.
LOCK_FILE = "chartbook.lock"

#: The version of the lockfile's envelope.
SCHEMA = "chartbook/lock/v1"

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
                for entry in lock.dependencies:
                    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
                        raise ValueError(
                            "it lists a dependency without an id that is a name. The file is not one "
                            "ChartBook wrote: restore it from git, or remove it and run `chartbook pin`"
                        )
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
    # A name of its own, so that two pins at once do not write over each
    # other's half-written file and then rename it away
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
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
            ``dropped`` (no longer declared, so no longer pinned),
            ``outside`` (declared with a path that reaches outside the
            dependency's own files, which is not pinned),
            ``passed_over`` (a dependency named by its ID: a newer snapshot
            of its ID was made in another repository, and not taken),
            ``unchecked`` (one taken from a snapshot that names no
            repository, so not checked against the one first pinned from),
            ``let_go`` (an update moved a ``git`` dependency to another
            commit, and this was built from the one before and is not built
            at the new one, so it is no longer pinned). For a
            whole dependency: ``removed`` (no longer in ``[dependencies]``),
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
PROBLEM_STATUSES = frozenset({"lost", "unreachable", "unfetched", "no_snapshot", "outside"})


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
        from_folder: The ``path`` dependencies that were pinned from what
            was in their folder, because that was asked for.
        unrooted: Why the store's note of this lockfile could not be
            written or removed, when it could not: the store is read-only
            for this user, as a store a team shares may be for everyone but
            its owner. The lockfile is written all the same; the store's
            ``gc`` goes by the note it has, if any.
    """

    lockfile: Path
    events: list[PinEvent] = field(default_factory=list)
    written: bool = False
    git: set = field(default_factory=set)
    snapshots: dict = field(default_factory=dict)
    from_folder: set = field(default_factory=set)
    unrooted: str = ""

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
    own_first = location.get("first_commit") if from_repository or (pinned and location.get("kind") == "store") else None
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


#: What git takes from the environment about which repository it is in
_GIT_LOCATION_VARIABLES = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
})


def _first_commit_of(git_cache: GitCache, url: str, commit: str) -> str:
    """A repository's first commit, back from *commit* by first parents, from its clone in the git cache; empty if not known."""
    import subprocess

    # The bare clone, named outright: a GIT_DIR in the environment (a git hook
    # sets one) would otherwise be asked instead
    environment = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            ["git", f"--git-dir={git_cache.repo_path(url)}", "rev-list", "--max-parents=0", "--first-parent", commit],
            capture_output=True, text=True, timeout=60, env={**environment, "GIT_OPTIONAL_LOCKS": "0"},
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
    from_folder: bool = False,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
) -> PinReport:
    """:func:`_sync_now`, one at a time for each lockfile."""
    with _one_at_a_time(Path(project_dir) / LOCK_FILE):
        return _sync_now(project_dir, store, move, git_cache, from_folder, only, clone_missing, built_here)


def _sync_now(
    project_dir: Union[str, Path],
    store: Optional[Store],
    move: Optional[Iterable[str]],
    git_cache: Optional[GitCache] = None,
    from_folder: bool = False,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
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
    :param from_folder: Pin a ``path`` dependency from what is in its
        folder now, and not from a snapshot.
    """
    project_dir = Path(project_dir).resolve()
    store = store if store is not None else default_store()
    root, dependencies = _read_pipeline(project_dir)
    # The store's snapshots, read once for every dependency named by its ID
    read = []

    def snapshots_in_store() -> list:
        if not read:
            read.append(snapshot.readable_snapshots(store)[0])
        return read[0]

    host: Optional[str] = None  # the default host, read when a dependency is named by its ID
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
        if only is not None:
            # Only what was asked is looked at: the rest stays as it was
            after.dependencies.append(next(entry for entry in before.dependencies if entry["id"] == key))
            after.assets.update(before.assets_of(key))
            continue
        report.events.append(PinEvent("removed", key))

    locked = {entry["id"]: entry for entry in before.dependencies}
    for key in sorted(dependencies):
        entry = dependencies[key]
        may_move = key in moving
        had = before.assets_of(key)
        if only is not None and key not in only:
            if key in locked:
                after.dependencies.append(locked[key])
                after.assets.update(had)
            continue
        # A label's record is pinned from a snapshot and only from one; a
        # pin from a folder or a repository carries what it has unchanged
        had_labels = {k: v for k, v in had.items() if (v.get("ref") or {}).get("rev")}
        had_assets = {k: v for k, v in had.items() if k not in had_labels}
        was = locked.get(key)
        kept_as_it_is = False
        if entry.get("_store"):
            if host is None:
                from chartbook.config import get_default_host

                host = get_default_host()
            was_location = (was or {}).get("location", {})
            has_bytes = any(record.get("content_hash") for record in had.values())
            from_repository = (
                has_bytes and was_location.get("kind") == "git" and was_location.get("pipeline") == entry["_store"]
            )
            if clone_missing:
                entry = clone_instead(entry, root, was, may_move, snapshots_in_store, host, built_here, pinned=has_bytes)
            if from_repository and "git" not in entry and (
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

        if kept_as_it_is:
            records = dict(had)
            if _declared_elsewhere(was, listed):
                report.events.append(PinEvent("relocated", key, detail=_describe(listed["location"])))
            listed = {**was, "location": dict(was["location"])}
            report.git.add(key)
            for asset_id, record in sorted(had.items()):
                content_hash = record.get("content_hash")
                if not content_hash:
                    continue
                if store.has(content_hash):
                    report.events.append(PinEvent("kept", key, asset_id, old=content_hash, new=content_hash))
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
        elif "git" in entry:
            if git_cache is None:
                git_cache = default_git_cache()
            directory, listed, failure = _fetch(
                key, entry, was, listed, may_move, project_dir, git_cache, report
            )
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
                    first = _first_commit_of(git_cache, local_url(entry["git"], project_dir), commit) if commit else ""
                    recorded = None if entry.get("_repository") else (was or {}).get("location", {}).get("first_commit")
                    if named and named != entry["_from_id"]:
                        said = named if named.startswith(("a [project]", "an id ")) else f"the ID {named}"
                        failure = f"{why}, and that repository's chartbook.toml gives {said}, not {entry['_from_id']}"
                    elif first and recorded and first != recorded:
                        failure = (
                            f"{why}, and that repository's history begins at {first[:7]}, not at {recorded[:7]} as the "
                            f"one it was pinned from: another repository, or its history rewritten. To take it, name it "
                            f"with repository = \"...\" in its [dependencies] entry"
                        )
                    elif first:
                        listed = {**listed, "location": {**listed["location"], "first_commit": first}}
                    if failure:
                        directory = None
                        # Nothing of a refused clone is recorded: not its commit either
                        listed = was if was is not None else _dependency_entry(key, entry)
            commit_was = (was or {}).get("location", {}).get("commit")
            commit_now = listed.get("location", {}).get("commit")
            commit_moved = bool(commit_was and commit_now and commit_was != commit_now)
            pinned = any(record.get("content_hash") for record in had.values())
            lost = failure is not None and any(
                record.get("content_hash") and not store.has(record["content_hash"]) for record in had.values()
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
            if pinned_from.get("kind") == "git" and pinned_from.get("pipeline") == entry["_store"]:
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
                newest_of=lambda entry=entry, repository=repository, first_commit=first_commit, named=named: _newest_in_store(
                    entry["_store"], entry.get("commit"), store, repository,
                    found=snapshots_in_store(), first_commit=first_commit, named=named,
                ),
                found=snapshots_in_store,
            )
        elif from_folder:
            # What is in the folder this minute, whatever state it is in.
            # The lockfile then names no commit: nothing says which one
            # these bytes came from.
            report.from_folder.add(key)
            records = _sync_dependency(
                key, Path(entry["_resolved_path"]), had_assets, may_move, store, cache, report
            )
            records.update(had_labels)
            for asset_id, record in sorted(had_labels.items()):
                if not record.get("content_hash"):
                    report.events.append(
                        PinEvent("not_built", key, asset_id, detail=record.get("missing") or "the label was pinned without its bytes")
                    )
            if not may_move and was is not None and records == had:
                # Nothing moved, so the pins are still the snapshot's, and
                # the lockfile goes on saying so
                if _declared_elsewhere(was, listed):
                    report.events.append(
                        PinEvent("relocated", key, detail=_describe(listed["location"]))
                    )
                listed = {**was, "location": dict(was["location"])}
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

    # With nothing to lock and no lockfile yet, do not make an empty one
    if dependencies or lock_path.exists():
        report.written = write_lock(after, lock_path)
    hashes = after.hashes()
    try:
        if hashes:
            store.add_root(lock_path, hashes)
        else:
            store.remove_root(lock_path)
    except (OSError, StoreError) as error:
        if not is_read_only(error):
            raise LockError(
                f"{lock_path} was written, and the store's note of it for `gc` "
                f"could not be: {error}. The pins are in the store and the lockfile "
                f"names them; `chartbook pin` again, once the store can be written, "
                f"leaves the note."
            ) from None
        # A store that is read-only for this user: the pins are in it, the
        # lockfile names them, and only the note for `gc` is missing
        report.unrooted = str(error)
    return report


def label_remedy(missing: Optional[str], key: str) -> str:
    """What puts bytes behind a label pinned without them, given why it was."""
    if "share that start" in (missing or ""):
        return f"its owner gives the label more digits of the hash, and makes a snapshot; then `chartbook update {key}`"
    return f"when its owner has made a snapshot that holds that version, `chartbook update {key}`"


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
            that declares none. Empty otherwise.
    """

    dependency: str
    asset: Optional[str]
    message: str
    kind: str = ""


@dataclass
class FrozenReport:
    """What :func:`verify` found: whether every pin can be had, with nothing written.

    Attributes:
        lockfile: The lockfile's path.
        dependencies: How many dependencies the manifest declares.
        pins: How many pinned assets are in the store.
        problems: Everything that stands in the way, in order.
    """

    lockfile: Path
    dependencies: int = 0
    pins: int = 0
    problems: list[FrozenProblem] = field(default_factory=list)


def verify(project_dir: Union[str, Path] = ".", store: Optional[Store] = None) -> FrozenReport:
    """Say whether a pipeline can be built from its lockfile alone. Nothing is written.

    This is ``--frozen``: what CI runs, and what anyone with a store they
    may only read runs. It opens no repository, fetches nothing, pins
    nothing and writes nothing, not the lockfile, not the store. It reads
    the manifest's ``[dependencies]``, the lockfile and the store, and
    reports a problem for

    - a lockfile that is not there while the manifest has dependencies;
    - a dependency in the manifest and not in the lockfile, or in the
      lockfile and no longer in the manifest, or pinned from one place
      while the manifest now says another;
    - a dependency with nothing pinned;
    - an asset that was declared and not built when it was pinned;
    - a pinned asset that the store does not have.

    The stricter choice the design kept for ``--frozen``: where ``pin``
    records an unbuilt asset and goes on, ``verify`` counts it a problem,
    since the build that follows may need it.

    :param project_dir: The pipeline's directory.
    :param store: The store the pins should be in; this user's by default.
    :returns: What was found. No problems means the build can go ahead.
    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        is there and cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    project_dir = Path(project_dir).resolve()
    store = store if store is not None else default_store()
    _, dependencies = _read_pipeline(project_dir)
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
    entries = {entry["id"]: entry for entry in locked.dependencies}
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
                    f"`chartbook update {key}` follows it.",
                )
            )
        assets = locked.assets_of(key)
        if not assets:
            report.problems.append(
                FrozenProblem(key, None, "has nothing pinned. Run `chartbook pin`, and see what it says.", "nothing_pinned")
            )
        for asset_id in sorted(assets):
            content_hash = assets[asset_id].get("content_hash")
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
                        "folder takes no table, and a snapshot writes one out only from a DuckDB file. "
                        "`chartbook snapshot` there, then `chartbook update`.",
                        "not_built",
                    )
                )
            elif not content_hash:
                report.problems.append(
                    FrozenProblem(
                        key, asset_id, "was declared and not built when it was pinned. Build it there, declare it ready, and `chartbook update`.",
                        "not_built",
                    )
                )
            elif not store.has(content_hash):
                if assets[asset_id].get("label"):
                    remedy = f"its owner makes a snapshot that holds that version again, and then `chartbook update {key}`"
                elif entry.get("via") == "rev" and not entry.get("location", {}).get("url"):
                    remedy = (
                        "`chartbook pin`, where the store can be written and `[resolve] default_host` "
                        "is set, puts it back from its repository"
                    )
                elif entry.get("via") == "rev":
                    remedy = "`chartbook pin`, where the store can be written, puts it back from the repository"
                elif entry.get("location", {}).get("commit"):
                    remedy = (
                        f"`chartbook update {key}` moves to a snapshot the store has, or "
                        f"`chartbook snapshot` in its folder at that commit makes it again"
                    )
                else:
                    remedy = "`chartbook pin --from-folder`, where the store can be written, puts it back from the folder"
                report.problems.append(
                    FrozenProblem(
                        key,
                        asset_id,
                        f"is pinned at {content_hash[:19]}… and the store at {store} "
                        f"does not have it. Point CHARTBOOK_STORE at the store that has it; "
                        f"or {remedy}.",
                    )
                )
            else:
                report.pins += 1
    for key in sorted(set(entries) - set(dependencies)):
        report.problems.append(
            FrozenProblem(key, None, "is in the lockfile and no longer in [dependencies]. Run `chartbook pin`.")
        )
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


def _describe(location: dict) -> str:
    """Where a dependency is, in a few words, for a message."""
    if location.get("kind") == "store":
        at = f" at {location['at']}" if location.get("at") else ""
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
            # Still the commit it was pinned at. The network is used only
            # if this disk has lost its copy of it. A working copy, where
            # `chartbook run` built it, has more in it than the checkout.
            directory = git_cache.files(url, locked_commit)
            if directory is None:
                git_cache.fetch(url)
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
        not taken (``passed_over``).
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
    if not taken:
        others = sorted({_made_in(t) for t in mine})
        claim = f"; snapshots from {', '.join(others)} claim its ID too, and are not taken" if others and there else ""
        if there:
            return None, (
                f"the store at {store} has no snapshot of {pipeline_id}{where} made in {there}{claim}{dated}. "
                f"If it has moved, say where with repository = \"...\" in its [dependencies] entry"
            ), {}
        return None, (
            f"the store at {store} has no snapshot of {pipeline_id}{where}{dated}. Its owner makes one "
            f"with `chartbook snapshot`; on another machine, the store must be the one theirs "
            f"syncs with or shares ([store] url)"
        ), {}
    newest = max(taken, key=lambda t: t.made_at)

    # What to record of its repository: its own address and first commit;
    # for one made in a shallow clone or a clone with no address, what was
    # known already, which is never lost, or what the snapshots it was
    # taken with say
    accepted = sorted((t for t in every if made_there(t)), key=lambda t: t.made_at, reverse=True)
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
            f"[dependencies] entry, then `chartbook update`"
        )
    return newest, "", identity


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
    :returns: Its records as they should be, by asset ID, and the entry the
        lockfile should list: with the snapshot's commit and time.
    """
    # A label's record, `key:model/x@champion`, is pinned beside the assets
    # and judged apart from them: it follows the owner's labels, not the
    # snapshot's content
    had_labels = {k: v for k, v in had.items() if (v.get("ref") or {}).get("rev")}
    had = {k: v for k, v in had.items() if k not in had_labels}
    pinned = [record for record in had.values() if record.get("content_hash")]
    locked_commit = (was or {}).get("location", {}).get("commit")
    locked_made = (was or {}).get("snapshot")
    why = ""
    code = None
    identity: dict = {}
    if newest_of is not None:
        newest, why, identity = newest_of()
        if may_move or not pinned:
            # Said when the choice is made, not on every pin after it
            for status in ("passed_over", "unchecked"):
                if identity.get(status):
                    report.events.append(PinEvent(status, key, detail=identity[status]))
    else:
        try:
            newest, code = snapshot.newest_for(directory, store)
        except snapshot.SnapshotError as error:
            newest, code, why = None, None, str(error)

    def as_it_was() -> dict:
        """The listing, still naming the snapshot the pins came from, and the repository it came from."""
        if (was or {}).get("location", {}).get("kind") == "git":
            # Pinned from its repository: it says so still, not a store pin at its commit
            return {**was, "location": dict(was["location"])}
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
        return kept

    if pinned and not may_move:
        # `pin` does not move a pin. It says what a newer snapshot has.
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
        for record in had.values():
            old = record.get("content_hash")
            if not old:
                report.events.append(
                    PinEvent("not_built", key, record["id"], detail=_where(record))
                )
            elif not store.has(old):
                report.events.append(
                    PinEvent(
                        "lost",
                        key,
                        record["id"],
                        old=old,
                        detail=(
                            "it is not in the store. A snapshot puts it there: "
                            "`chartbook update` moves to the newest one"
                        ),
                    )
                )
            else:
                now = theirs.get(snapshot.local_name(record))
                status = "stale" if now is not None and now != old else "kept"
                report.events.append(PinEvent(status, key, record["id"], old=old, new=old))
        for asset_id, record in sorted(had_labels.items()):
            # A label the owner has since moved is stale, like changed data
            old = record.get("content_hash")
            now = (newest.labels.get(snapshot.local_name(record)) or {}).get(record.get("label")) if newer else None
            moved = bool(old and now and not old.split(":", 1)[-1].startswith(now))
            if old:
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
        snapshot.renamed(newest.assets[name], key)["id"]
        for name in sorted(newest.assets)
        if newest.assets[name].get("content_hash")
        and not store.has(newest.assets[name]["content_hash"])
    ]
    if missing:
        for record in pinned:
            _report_kept(record, key, store, report)
        had = {**had, **had_labels}
        for asset_id in missing:
            report.events.append(
                PinEvent(
                    "lost",
                    key,
                    asset_id,
                    detail=(
                        f"the snapshot at {newest.commit[:7]} names it, and it is "
                        f"not in the store, so nothing was moved. Making the "
                        f"snapshot again puts it back"
                    ),
                )
            )
        return dict(had), as_it_was()

    records: dict[str, dict] = {}
    for name in sorted(newest.assets):
        # `trained_on` is the owner's record, keyed in the owner's names,
        # and would read as asset IDs here that are not; it stays with the
        # snapshot
        record = {k: v for k, v in snapshot.renamed(newest.assets[name], key).items() if k != "trained_on"}
        asset_id = record["id"]
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
        records[asset_id] = record

    # What the lockfile has that this snapshot does not
    for asset_id in sorted(set(had) - set(records)):
        old = had[asset_id].get("content_hash")
        if old:
            report.events.append(PinEvent("dropped", key, asset_id, old=old))

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
        record = {k: v for k, v in snapshot.renamed(newest.assets[name], key).items() if k not in ("content_hash", "size_bytes", "files")}
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
    listed = {**listed, "location": location, "snapshot": newest.made_at}
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

    :param directory: Where the dependency's files are: its ``path``, or
        the checkout of a ``git`` dependency. None if they could not be got.
    :param had: The records the lockfile has for it now, by asset ID.
    :param may_move: Whether its existing pins may move (an update).
    :param commit_moved: Whether this update moved a ``git`` dependency to
        another commit than the one it was pinned at.
    :param within: If given, a declared path that reaches a file outside
        this directory is not pinned, and is a problem.
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
        )

    # A table or query in a source has no file in the folder to take: a pin
    # of it comes from a snapshot, and stays as the lockfile has it. One the
    # lockfile does not have yet is listed without a hash, and said so
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
                detail="a table or query in a source is not taken from a folder; "
                "`chartbook snapshot` there writes it out, then `chartbook update` pins it",
            )
        )

    # What the lockfile has that the other pipeline no longer declares
    for asset_id in sorted(set(had) - set(records)):
        old = had[asset_id].get("content_hash")
        if not old:
            continue  # it was never pinned; there is nothing to let go of
        if had[asset_id].get("location", {}).get("kind") in ("table", "query"):
            # A table or query has no file in the folder to take: its pin
            # is the snapshot's parquet, and stays until a snapshot moves it
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
    commit_moved: bool = False,
    within: Optional[Path] = None,
) -> dict:
    """Decide what one asset's record is, storing its bytes if they are needed."""
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
        stored = store.put(absolute, links=PIN_LINKS)
        if old is None:
            status = "pinned"
        elif stored.content_hash == old:
            status = "kept"
        else:
            status = "moved"
        report.events.append(
            PinEvent(status, key, asset_id, old=old, new=stored.content_hash)
        )
        return _asset_record(ref, key, declared_path, stored, found.single)

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
        store.put(absolute, links=PIN_LINKS)
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
    from_folder: bool = False,
    only: Optional[Iterable[str]] = None,
    clone_missing: bool = True,
    built_here: Iterable[str] = (),
) -> PinReport:
    """Pin whatever a pipeline depends on that has no pin yet.

    A pin that already exists is left exactly where it is, whatever the
    other pipeline has done since: :func:`update` is what moves one.

    A ``path`` dependency is pinned from its newest **snapshot**: what its
    owner declared ready, at a commit (:mod:`chartbook.snapshot`). Nothing
    in its folder is read. One that has no snapshot cannot be pinned, and
    the report says what its owner has to do.

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
    :param from_folder: Pin a ``path`` dependency from what is in its
        folder at this moment, and not from a snapshot. For someone working
        on both pipelines at once. The folder may be in any state, and the
        lockfile then names no commit.
    :param only: The keys of the dependencies to pin; the rest keep what
        the lockfile has, and nothing of them is fetched. All by default.
    :param clone_missing: Whether a dependency named by its ID that the
        store has no snapshot of is cloned from the default host, and
        pinned from the clone (:func:`clone_instead`).
    :param built_here: The IDs of pipelines a run builds itself (a
        catalog's own), which are never cloned.
    :returns: What was done.
    :raises LockError: If *project_dir* is not a pipeline, or its lockfile
        cannot be read.
    :raises ValueError: If its ``[dependencies]`` table is malformed.
    """
    return _sync(
        project_dir, store, move=None, git_cache=git_cache, from_folder=from_folder,
        only=None if only is None else ({only} if isinstance(only, str) else set(only)),
        clone_missing=clone_missing,
        built_here=built_here,
    )


def update(
    project_dir: Union[str, Path] = ".",
    dependencies: Iterable[str] = (),
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    from_folder: bool = False,
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
    :param from_folder: Take a ``path`` dependency from what is in its
        folder at this moment, and not from a snapshot. See :func:`pin`.
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
        from_folder=from_folder,
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
        recent: Objects that nothing names, stored too recently to remove.
        delete: Objects that nothing names, each with its size in bytes.
        not_read: Lockfiles a store names that are not read here, as they are
            not a local ``chartbook.lock``: what their notes name is kept.
        forget: Lockfiles that could not be found and are to be forgotten.
        forget_missing, recent_seconds, keep_days, keep_lineage, aggressive: What the plan was made
            with, so that it can be made again the same way when it is
            carried out.
    """

    lockfiles: list[tuple[Path, bool]] = field(default_factory=list)
    kept: int = 0
    snapshots: int = 0
    snapshots_kept: list = field(default_factory=list)
    snapshots_delete: list = field(default_factory=list)
    recent: list[str] = field(default_factory=list)
    delete: list[tuple[str, int]] = field(default_factory=list)
    forget: list[Path] = field(default_factory=list)
    not_read: list[Path] = field(default_factory=list)
    forget_missing: bool = False
    recent_seconds: float = RECENT_SECONDS
    keep_days: float = snapshot.KEEP_DAYS
    keep_lineage: bool = False
    aggressive: bool = False

    @property
    def size_bytes(self) -> int:
        """The total size of what would be removed."""
        return sum(size for _, size in self.delete)


def plan_gc(
    store: Optional[Store] = None,
    forget_missing: bool = False,
    recent_seconds: float = RECENT_SECONDS,
    keep_days: float = snapshot.KEEP_DAYS,
    keep_lineage: bool = False,
    aggressive: bool = False,
) -> GcPlan:
    """Work out what a store can let go of. Nothing is removed.

    First the snapshots: one is kept if a lockfile pins it, if it is the
    newest of its pipeline, if a label points at a model version in it, or
    if it was made in the last *keep_days* days; and with *keep_lineage*, if
    a snapshot kept for any of these was made from it (or from a label
    pointing into it), as far up as that goes
    (:func:`chartbook.snapshot.plan_removals`). Then the objects: one is
    kept if a lockfile the store knows of names it, or a kept snapshot
    does. The store knows of every lockfile that was pinned or updated into
    it. A lockfile is read as it is now; one that cannot be found (a
    deleted project, a drive that is not plugged in) still keeps what it
    named when it was last pinned, unless *forget_missing* is set.

    :param store: The store; this user's by default.
    :param forget_missing: If True, a lockfile that cannot be found keeps
        nothing, and is forgotten when the plan is carried out. On a store
        a team shares, every other machine's lockfile is one that cannot be
        found from here.
    :param recent_seconds: An unnamed object newer than this is left alone.
    :param keep_days: How long an unpinned snapshot that is not the newest
        of its pipeline is kept.
    :returns: The plan, for :func:`run_gc`.
    :raises StoreError: If the store's notes cannot be read.
    :raises LockError: If a lockfile that is there cannot be read. Nothing
        is removed from a store when what it must keep is in doubt.
    """
    store = store if store is not None else default_store()
    plan = GcPlan(
        forget_missing=forget_missing, recent_seconds=recent_seconds, keep_days=keep_days,
        keep_lineage=keep_lineage, aggressive=aggressive,
    )
    keep: set[str] = set()
    pinned_snapshots: set[tuple[str, str]] = set()
    hashes_of_missing: set[str] = set()
    for root in store.roots():
        # A root is written by whoever can write to the store, and names a
        # path: only a lockfile on this machine is read, never another file
        # or a path on another host. One that is not read is never taken
        # as gone: what its note names is kept, even with forget_missing,
        # since it may be a real lockfile on a network drive
        if not _a_local_lockfile(root.lockfile):
            plan.lockfiles.append((root.lockfile, False))
            plan.not_read.append(root.lockfile)
            keep |= set(root.hashes)
            hashes_of_missing |= set(root.hashes)
            continue
        found = read_lock(root.lockfile)
        plan.lockfiles.append((root.lockfile, found is not None))
        if found is not None:
            keep |= found.hashes()
            for entry in found.dependencies:
                commit = entry.get("location", {}).get("commit")
                if commit and entry.get("snapshot"):
                    pinned_snapshots.add((commit, entry["snapshot"]))
        elif forget_missing:
            plan.forget.append(root.lockfile)
        else:
            keep |= set(root.hashes)
            hashes_of_missing |= set(root.hashes)

    try:
        snapshots = snapshot.plan_removals(
            store, pinned_snapshots, hashes_of_missing, keep_days=keep_days, keep_lineage=keep_lineage, aggressive=aggressive
        )
    except snapshot.SnapshotError as error:
        raise LockError(str(error)) from None
    plan.snapshots_kept = snapshots.keep
    plan.snapshots_delete = snapshots.remove
    named_by_snapshots = snapshots.kept_hashes()
    plan.snapshots = len(named_by_snapshots)
    keep |= named_by_snapshots

    for content_hash in store.hashes():
        if content_hash in keep:
            plan.kept += 1
        elif store.age_of(content_hash) < recent_seconds:
            plan.recent.append(content_hash)
        else:
            plan.delete.append((content_hash, store.size_of(content_hash)))
    return plan


def run_gc(plan: GcPlan, store: Optional[Store] = None) -> tuple[int, int]:
    """Carry out a plan from :func:`plan_gc`: remove what it says to remove.

    The plan was made before anyone said yes, and a pin may have landed in
    between and taken something it names. So the plan is made again now,
    and only what both say may go is removed.

    :returns: How many snapshots and how many objects were removed.
    """
    store = store if store is not None else default_store()
    now = plan_gc(
        store,
        forget_missing=plan.forget_missing,
        recent_seconds=plan.recent_seconds,
        keep_days=plan.keep_days,
        keep_lineage=plan.keep_lineage,
        aggressive=plan.aggressive,
    )
    from chartbook import versions

    still_removable = {taken.path for taken, _ in now.snapshots_delete}
    removed_snapshots = 0
    for taken, _ in plan.snapshots_delete:
        if taken.path in still_removable and snapshot.remove(store, taken):
            removed_snapshots += 1
            versions.forget(taken)  # its site, kept for catalogs on this machine
    still_unnamed = {content_hash for content_hash, _ in now.delete}
    removed = sum(
        store.delete(content_hash)
        for content_hash, _ in plan.delete
        if content_hash in still_unnamed
    )
    for lockfile in plan.forget:
        store.remove_root(lockfile)
    return removed_snapshots, removed
