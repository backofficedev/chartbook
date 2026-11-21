"""What a pipeline reads that is not in your store: the list, in the order to build it.

``docs_src/design/one-command.md``, "What is not in your store". A class
with no shared store, a new laptop: the lockfile pins snapshots this
machine's store does not have, and each of those was built from others
it may not have either. ``chartbook run`` and ``chartbook pin`` say all
that has to be built, each pipeline after everything it reads, with what
to type. Nothing here builds, and nothing here writes but a fetch into
the git cache.

On the list is a dependency with no snapshot to pin, and one that is
pinned where the store has neither the pinned snapshot nor any build of
yours of that commit. A build of yours that is there and does not meet
the pins is not: that is said as it is, by the pin.

It goes up. For each one on the list, its own ``chartbook.toml`` and
``chartbook.lock`` at the commit to be built are read, and whatever of
*its* dependencies the store lacks goes on the list before it. A folder
on this machine is asked through git for those two files at that commit,
and is not changed; a repository is fetched into the git cache, as a
``git`` dependency is. A line says what is known and no more: it may
lack its address, its commit, or what it reads in turn.

What ``chartbook run`` builds by itself is not on the list: a ``git``
dependency, and one named by its ID where the settings name a host to
clone it from.

**Whose text this is.** A lockfile, a manifest and a repository's tree
are anyone's. An address is one only if it is a plain web address, which
is all a snapshot ever records: nothing else is fetched, and nothing
else is printed as something to clone. A pipeline's name is one only if
it is an ID. Everything shown is shown without control characters, and
everything in a command is quoted for the shell. On Windows, where no
quoting makes every sign text in each of its shells, a line whose
commands would hold such a sign is given no command.
"""

from __future__ import annotations

import contextlib
import os
import posixpath
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from chartbook import lock, snapshot
from chartbook.gitcache import GitCache, GitError, default_git_cache
from chartbook.store import Store, StoreError

#: How far up the walk goes before it stops reading (as the walk for cycles: :data:`chartbook.lineage.DEEPEST`).
DEEPEST = 64

#: How many manifests of one repository are read to find a pipeline's own.
MOST_MANIFESTS = 200

#: How slow a fetch may be, in bytes a second, and for how many seconds, before git gives it up: a
#: server that answers nothing must not hold a pin for ever. Only where the person has set neither.
SLOWEST_FETCH = {"GIT_HTTP_LOW_SPEED_LIMIT": "1000", "GIT_HTTP_LOW_SPEED_TIME": "30"}

_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class NoOrder(Exception):
    """Raised when what is not in the store depends on itself: there is no order to build it in.

    Its text is what a run says of a cycle, after the name of the pipeline
    it was asked of, which is ``root``.
    """

    def __init__(self, root: str, said: str):
        super().__init__(said)
        self.root = root


@dataclass
class Wanted:
    """One pipeline to build: a line of the list.

    Attributes:
        pipeline: Its ID.
        commit: The commit to build, as its pin names it; None for one
            that was never pinned, of which any commit will do.
        repository: Its repository's web address, where the pin recorded
            one, the entry names one, or the store's other snapshots of it
            record one.
        folder: Its folder, where it is one on this machine: the folder a
            ``path`` entry names, or its folder in a clone of its
            repository (``clone``), once that was found there.
        clone: The top of a clone of its repository on this machine: the
            pipeline's own repository, or a folder beside it, whose
            ``origin`` is that address. Its files are read from it, and
            nothing is fetched.
        expected: For a ``path`` entry whose folder is not on this
            machine: the path as the manifest writes it.
        top: The top of the git repository its folder is in, if it is in one.
        subdirectory: Its folder within its repository, where that was
            read; empty at the top.
        placed: Whether that folder is known: False where its repository
            could not be read, and the top is only the likeliest place.
        given: Whether that folder was given by the entry that reads it (a
            ``path`` entry of a pipeline in the same repository), and so
            is not looked for.
        on_commit: Whether its folder on this machine is on that commit
            already, so that nothing has to be checked out.
        read_at: The commit its two files were read at, in full: the pinned
            one, or for one that was never pinned the commit its
            repository was on. A line above may leave that repository on
            another commit, and this is the one to come back to.
        absent: Whether its repository was read at that commit and holds
            no pipeline of this ID: there is nothing there to build.
        lacks: Whether its clone on this machine does not have the commit to
            build (or any commit yet), so that it is fetched first.
        shallow: Whether its clone on this machine is a shallow one, which
            a plain ``git fetch`` does not deepen.
        builds: Whether its manifest, where it was read, has a ``build``
            script. One that has none commits what it declares, and its
            snapshot is made by ``chartbook snapshot``.
        built: For one that was never pinned: whether its folder has
            nothing uncommitted and has on disk everything its manifest
            declares with a path. A snapshot is all it lacks, and nothing
            has to be built again. Never for a pinned one: its files may
            be of another build than the pin's.
        by_path: Whether it is a ``path`` entry, never pinned, of a folder
            on this machine: what ``chartbook run --upstream`` builds.
        reads: The lines above it that it reads, by their numbers from 1.
        unknown: Why what it reads in turn is not known, where it is not.
    """

    pipeline: str
    commit: Optional[str] = None
    repository: Optional[str] = None
    folder: Optional[Path] = None
    clone: Optional[Path] = None
    expected: str = ""
    top: Optional[Path] = None
    subdirectory: str = ""
    placed: bool = False
    given: bool = False
    on_commit: bool = False
    read_at: str = ""
    absent: bool = False
    lacks: bool = False
    shallow: bool = False
    builds: bool = True
    built: bool = False
    by_path: bool = False
    reads: list[int] = field(default_factory=list)
    unknown: str = ""


@dataclass
class Listing:
    """What a pipeline reads that is not in the store, each after everything it reads.

    Attributes:
        root: The ID of the pipeline it was asked of.
        directory: That pipeline's folder.
        wanted: The lines, in the order to build in.
        keys: The pipeline's own dependencies that are on the list, by
            their keys in ``[dependencies]``: what is said of them is the
            list, and no line of a pin's report.
        stores: Where was looked: the store, or each of the catalog's, as
            a message names it.
        top: The top of the pipeline's own git repository, if it is in one.
    """

    root: str
    directory: Path
    wanted: list[Wanted] = field(default_factory=list)
    keys: set = field(default_factory=set)
    stores: list[str] = field(default_factory=list)
    top: Optional[Path] = None


@dataclass
class _Place:
    """Where one pipeline's manifest and lockfile are read from.

    Attributes:
        files: A folder that holds the two files.
        base: The folder on this machine that its ``path`` entries are
            relative to; None for one read from its repository.
        shown: The manifest, as a message names it.
        repository: For one read from its repository: the address,
        clone: the clone on this machine it was read from, if it was,
        commit: the commit it was read at,
        within: and its folder in the repository, ending in ``/``; empty at the top.
    """

    files: Path
    base: Optional[Path]
    shown: str
    repository: Optional[str] = None
    clone: Optional[Path] = None
    commit: str = ""
    within: str = ""


@dataclass
class _Need:
    """One dependency read at a place: its key, the pipeline it is by its ID, and what to build where the store lacks it."""

    key: str
    pipeline: str
    wanted: Optional[Wanted]


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _address(value: object) -> Optional[str]:
    """A repository's address as a snapshot records one: a plain web address, without credentials; None for anything else.

    Nothing else is fetched, and nothing else is printed as something to
    clone: an address that starts with ``-`` is an option to git, and one
    with a transport of its own runs a command.
    """
    from chartbook.identity import web_link

    return web_link(value) or None


def _an_id(value: object) -> str:
    """A pipeline's ID, if that is what a file gave; empty for anything else, which is shown nowhere."""
    from chartbook.identity import validate_pipeline_id

    try:
        return validate_pipeline_id(value) if isinstance(value, str) and value == _plain(value) else ""
    except Exception:  # noqa: BLE001 - whatever the grammar refuses, and however, is no ID
        return ""


class _Walk:
    """Reads what each pipeline depends on, and tells which of it the store lacks."""

    def __init__(
        self, store: Store, git_cache: Optional[GitCache], echo: Callable[[str], None], scratch: Path, beside: Path,
        own_top: Optional[Path],
    ):
        self.store = store
        self._git_cache = git_cache
        self.echo = echo
        self.scratch = scratch
        #: The folder the pipeline's own repository is in: where a clone of another is looked for, and would be put
        self.beside = beside
        #: The top of the pipeline's own repository, which may hold other pipelines
        self.own_top = own_top
        self._snapshots: Optional[list] = None
        self._host: Optional[str] = None
        self._fetched: dict = {}
        self._count = 0

    def snapshots(self) -> list:
        """The store's snapshots that owners made, read once."""
        if self._snapshots is None:
            self._snapshots = snapshot.readable_snapshots(self.store)[0]
        return self._snapshots

    def host(self) -> str:
        """The host a pipeline named by its ID alone is cloned from, if the settings name one: its run gets it by itself."""
        if self._host is None:
            from chartbook.config import get_default_host

            try:
                self._host = get_default_host()
            except ValueError:
                self._host = ""
        return self._host

    def git_cache(self) -> GitCache:
        if self._git_cache is None:
            self._git_cache = default_git_cache()
        return self._git_cache

    def needs(self, place: _Place) -> tuple[list[_Need], str, bool]:
        """Each dependency read at a place, with what to build where the store lacks it; what could not be told of the others; and whether the pipeline there has a ``build`` script.

        :raises Exception: If the manifest there cannot be read.
        """
        from chartbook.manifest import BUILD_SCRIPT, read_scripts, validate_dependencies
        from chartbook.resolve import MANIFEST_NAME

        raw = snapshot._read_manifest_file(place.files)
        dependencies = validate_dependencies(raw.get("dependencies") or {}, place.base or place.files)
        try:
            builds = BUILD_SCRIPT in read_scripts(raw)
        except ValueError:
            builds = True  # a `[scripts]` that cannot be read: its own run says so
        try:
            locked = lock.read_lock(place.files / lock.LOCK_FILE)
        except lock.LockError:
            locked = None  # read as none: its own `chartbook pin` says what is wrong with it
        listed = {
            entry["id"]: entry for entry in (locked.dependencies if locked is not None else [])
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
        found: list[_Need] = []
        untold: list[str] = []
        for key in sorted(dependencies):
            entry, was = dependencies[key], listed.get(key)
            location = was.get("location") if isinstance(was, dict) and isinstance(was.get("location"), dict) else {}
            if "git" in entry or location.get("kind") == "git":
                continue  # from its repository, which the pipeline's own run fetches, and builds
            by_path = bool(entry.get("_resolved_path"))
            folder = Path(entry["_resolved_path"]) if by_path and place.base is not None else None
            # A `path` entry of a pipeline read from its repository names a folder of that repository,
            # or, read from a clone on this machine, a folder beside that clone
            beside_it = _within(place.within, _text(entry.get("path"))) if by_path and place.base is None and place.repository else None
            if by_path and place.base is None and place.clone is not None and beside_it is None:
                # Only where clones are kept, beside the pipeline's own repository: a lockfile is anyone's,
                # and must not aim a command at any folder of this machine
                beside_clone = Path(os.path.normpath(place.clone / place.within / _text(entry.get("path"))))
                folder = beside_clone if beside_clone.parent == self.beside else None
            if lock.names_a_snapshot(was):
                pipeline = _an_id(lock.pinned_pipeline(was, folder) or _text(entry.get("_store")))
                if not pipeline:
                    continue  # no pipeline's name: a pin from before pins said whose they are, or a file not as ChartBook wrote it
                wanted = None
                if self._pin_is_not_here(was, locked.assets_of(key), folder):
                    wanted = Wanted(pipeline, _text(location.get("commit")))
                    if folder is not None and (folder / MANIFEST_NAME).is_file():
                        wanted.folder = folder
                    elif beside_it is not None:
                        wanted.repository, wanted.clone, wanted.subdirectory, wanted.given = place.repository, place.clone, beside_it, True
                    else:
                        wanted.repository = _address(location.get("repository")) or self._recorded(pipeline)
                        wanted.clone = self._cloned(wanted.repository)
                        if wanted.repository is None:
                            wanted.repository, wanted.clone = self._cloned_by_its_id(pipeline)
                        wanted.expected = _plain(_text(entry.get("path"))) if by_path else ""
                found.append(_Need(key, pipeline, wanted))
            elif entry.get("_store"):
                if entry.get("rev"):
                    continue  # what its `rev` means is asked of its repository, by the pin
                pipeline, at = entry["_store"], _text(entry.get("commit"))
                of_it = [taken for taken in self.snapshots() if taken.pipeline == pipeline]
                wanted = None
                if not of_it and any(_text(taken.pipeline).casefold() == pipeline.casefold() for taken in self.snapshots()):
                    pass  # there under the same ID in other letters: a name to put right, as the pin says, and nothing to build
                elif not any(_text(taken.commit).startswith(at) for taken in of_it) and not self.host():
                    repository = _address(entry.get("_repository")) or self._recorded(pipeline)
                    clone = self._cloned(repository)
                    if repository is None:
                        repository, clone = self._cloned_by_its_id(pipeline)
                    wanted = Wanted(pipeline, at or None, repository, clone=clone)
                found.append(_Need(key, pipeline, wanted))
            elif folder is not None:
                if not (folder / MANIFEST_NAME).is_file():
                    continue  # no pipeline there: the pin says so
                try:
                    pipeline = snapshot.pipeline_in(folder)
                    newest, _ = snapshot.newest_for(folder, self.store)
                except (snapshot.SnapshotError, StoreError, OSError, ValueError):
                    continue  # a catalog, a folder that is not in git, a record that cannot be read: the pin says so
                found.append(_Need(key, pipeline, Wanted(pipeline, folder=folder, by_path=True) if newest is None else None))
            elif beside_it is not None:
                # Never pinned, in the repository its reader was read from: built there, at the same commit
                pipeline = self._id_at(_Source(self, place.repository, place.clone), place.commit, beside_it)
                if not pipeline:
                    untold.append(f"it reads a folder of its repository ({_plain(_text(entry.get('path')))}) that holds no pipeline there")
                    continue
                wanted = None
                if not snapshot.builds_at(self.snapshots(), pipeline, place.commit):
                    wanted = Wanted(pipeline, place.commit, place.repository, clone=place.clone, subdirectory=beside_it, given=True)
                found.append(_Need(key, pipeline, wanted))
            else:
                untold.append(f"it reads a folder outside its repository ({_plain(_text(entry.get('path')))}) that its lockfile does not pin")
        return found, "; ".join(untold), builds

    def _recorded(self, pipeline: str) -> Optional[str]:
        """The address the store's snapshots of a pipeline record, where they record one and only one."""
        from chartbook.identity import repository_key

        found = {repository_key(taken.repository): taken.repository for taken in self.snapshots() if taken.pipeline == pipeline and taken.repository}
        return _address(next(iter(found.values()))) if len(found) == 1 else None

    def _cloned(self, repository: Optional[str]) -> Optional[Path]:
        """A clone, on this machine, of the repository at an address: its top, or None.

        Looked for in two places: the pipeline's own repository, which may
        hold several pipelines, and a folder beside it named as ``git
        clone`` names one. A folder is a clone of the repository only
        where its ``origin`` is that address, so with no address nothing
        is taken for one, and a folder that happens to hold a pipeline of
        the same ID is not it. Where there is one, nothing is fetched: the
        repository's files are read from it at the commit to build, and
        the line says to build there. A repository that wants a password
        cannot be fetched here at all, and a class has its clones side by
        side.
        """
        from chartbook.identity import get_git_remote_url, is_repository_top, repository_key

        wanted = repository_key(repository) if repository else ""
        if not wanted:
            return None
        for top in dict.fromkeys([*([self.own_top] if self.own_top else []), *_clone_folders(self.beside, _clone_name(repository))]):
            try:
                if Path(top).is_dir() and is_repository_top(top) and repository_key(get_git_remote_url(top)) == wanted:
                    return _named_by_the_disk(Path(top))
            except (OSError, ValueError):
                continue
        return None

    def _cloned_by_its_id(self, pipeline: str) -> tuple[Optional[str], Optional[Path]]:
        """For a pipeline whose address nothing records: a clone beside the pipeline's own, told by its ``origin`` giving that ID; its address and its top, or neither.

        ``https://example.org/acme/rates`` is the repository of
        ``acme/rates`` (:func:`chartbook.identity.id_from_address`), as a
        pipeline at the top of its repository is named. A folder is still
        told by its ``origin`` alone, never by what its manifest says.
        """
        from chartbook.identity import get_git_remote_url, id_from_address, is_repository_top, remote_to_web_url

        for top in _clone_folders(self.beside, pipeline.rsplit("/", 1)[-1]):
            try:
                if not (top.is_dir() and is_repository_top(top)):
                    continue
                origin = get_git_remote_url(top)
                address = _address(remote_to_web_url(origin)) if origin else None
                if address and id_from_address(address) == pipeline:
                    return address, _named_by_the_disk(top)
            except (OSError, ValueError):
                continue
        return None, None

    def _pin_is_not_here(self, was: dict, assets: dict, folder: Optional[Path]) -> bool:
        """Whether the store has neither the snapshot a pin names, nor a build of yours of that commit, nor every pinned file whole in a snapshot of that pipeline."""
        if lock.read_from(was, self.snapshots(), folder):
            return False  # the pin itself, or a build of yours that stands in or does not: said as it is, by the pin
        pins = [record for record in assets.values() if record.get("content_hash") and lock.in_lockfile(record)]
        # With nothing of it in the lockfile, its entry is the pin, and names a snapshot that is not here.
        # A pinned file is here as a read of it is handed it: whole, in one of that pipeline's own
        # snapshots, and never by another pipeline's copy of the same bytes
        of = lock.pinned_pipeline(was)  # as the entry names it; with no name, the whole store is asked, as a read asks it
        return not pins or any(
            not self.store.has(record["content_hash"], of) or snapshot.not_whole(self.store, record, of) for record in pins
        )

    def place_of(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        """Where a pipeline to build has its manifest and lockfile at its commit; or None, and why what it reads is not known."""
        try:
            if wanted.folder is not None:
                return self._in_folder(wanted)
            if wanted.repository:
                return self._in_repository(wanted)  # from a clone of it on this machine, or from the git cache
        except Exception as error:  # noqa: BLE001 - whatever stops the reading is said in the line, and the line stays
            return None, _first_line(error)
        return None, "its repository is not recorded"

    def _in_folder(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        from chartbook.resolve import MANIFEST_NAME

        folder = wanted.folder
        why_not = ""
        try:
            code = snapshot.code_of(folder)
        except snapshot.NotInARepository:
            code, why_not = None, f"{folder} is not in a git repository"  # the list's own words: what a snapshot is does not belong in a line of it
        except snapshot.SnapshotError as error:
            # Said as the folder's own commands say it, and whole: git that does not trust the repository
            # (the sentence ends with the command that makes it), git that could not be run, a repository
            # with no commit yet. Each was "is not in a git repository" here, of a folder that is in one
            code, why_not = None, _plain((str(error).strip().splitlines() or [""])[0].rstrip("."), most=4096)
        wanted.top = code.top if code is not None else None
        if not wanted.commit:
            wanted.built = code is not None and _is_built(folder)
            wanted.read_at = code.commit if code is not None else ""
            return _Place(folder, folder, str(folder / MANIFEST_NAME)), ""
        if not _COMMIT.match(wanted.commit):
            return None, "its pin names no commit git would take"
        if code is None:
            return None, why_not
        wanted.on_commit = code.commit.startswith(wanted.commit)
        wanted.read_at = wanted.commit
        within = f"{code.subdirectory}/" if code.subdirectory else ""
        try:
            manifest = snapshot._git(code.top, "show", f"{wanted.commit}:{within}{MANIFEST_NAME}")
        except snapshot.SnapshotError:
            try:
                shallow = snapshot._git(code.top, "rev-parse", "--is-shallow-repository").strip() == "true"
            except snapshot.SnapshotError:
                shallow = False
            return None, (
                f"{folder} does not have its {MANIFEST_NAME} at {wanted.commit[:7]} (`git fetch"
                f"{' --unshallow' if shallow else ''}` there, if the commit is not in it)"
            )
        try:
            lockfile = snapshot._git(code.top, "show", f"{wanted.commit}:{within}{lock.LOCK_FILE}")
        except snapshot.SnapshotError:
            lockfile = None  # none in that commit: its run pins the newest of each
        return self._kept(manifest, lockfile, folder, f"{folder / MANIFEST_NAME} at {wanted.commit[:7]}"), ""

    def _fetch(self, url: str, pipeline: str) -> str:
        """Fetch a repository into the git cache, once in a walk; why it could not be, or nothing."""
        if url not in self._fetched:
            self.echo(f"Fetching {_plain(url)}, to see what {_plain(pipeline)} reads in turn.")
            try:
                self.git_cache().fetch(url)
                self._fetched[url] = ""
            except (GitError, ValueError, OSError) as error:
                self._fetched[url] = _first_line(error) or "git could not fetch it"
        return self._fetched[url]

    def _in_repository(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        from chartbook.resolve import MANIFEST_NAME

        if wanted.commit and not _COMMIT.match(wanted.commit):
            return None, "its pin names no commit git would take"
        source = _Source(self, wanted.repository, wanted.clone)
        if wanted.clone is not None:
            wanted.top = wanted.clone
            try:
                wanted.shallow = snapshot._git(wanted.clone, "rev-parse", "--is-shallow-repository").strip() == "true"
            except snapshot.SnapshotError:
                wanted.shallow = False
        commit, why = source.commit(wanted.commit, wanted.pipeline)
        if why:
            if wanted.clone is not None:
                wanted.lacks = True
                if not wanted.given:
                    # Where it is in the clone as the clone is now: the likeliest folder at the commit it lacks
                    try:
                        now = snapshot._git(wanted.clone, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
                        found, _ = self._manifest_of(wanted.pipeline, source, now)
                    except (snapshot.SnapshotError, GitError, ValueError, OSError):
                        found = None
                    if found:
                        wanted.subdirectory = found[: -len(MANIFEST_NAME)].rstrip("/")
            return None, why
        wanted.read_at = commit
        there = 0
        if wanted.given:
            chosen = f"{wanted.subdirectory}/{MANIFEST_NAME}" if wanted.subdirectory else MANIFEST_NAME
        else:
            chosen, there = self._manifest_of(wanted.pipeline, source, commit)
        manifest = source.text(commit, chosen) if chosen is not None else None
        if manifest is None:
            if there > MOST_MANIFESTS:
                # Not all of them were read: it may well be there
                return None, (
                    f"its {MANIFEST_NAME} was not found among the first {MOST_MANIFESTS} of the {there} in its repository "
                    f"at {commit[:7]}"
                )
            wanted.absent = True
            return None, f"no {MANIFEST_NAME} of {wanted.pipeline} was found in its repository at {commit[:7]}"
        within = chosen[: -len(MANIFEST_NAME)]
        wanted.subdirectory, wanted.placed = within.rstrip("/"), True
        if wanted.clone is not None:
            # Its folder on this machine, which the line says to build in
            wanted.folder = wanted.clone / within if within else wanted.clone
            try:
                wanted.on_commit = snapshot.code_of(wanted.clone).commit == commit
            except snapshot.SnapshotError:
                wanted.on_commit = False
            wanted.built = not wanted.commit and _is_built(wanted.folder)
        place = self._kept(
            manifest, source.text(commit, f"{within}{lock.LOCK_FILE}"), None,
            _plain(f"{within}{MANIFEST_NAME} of {wanted.repository} at {commit[:7]}"),
        )
        place.repository, place.clone, place.commit, place.within = wanted.repository, wanted.clone, commit, within
        return place, ""

    def _manifest_of(self, pipeline: str, source: "_Source", commit: str) -> tuple[Optional[str], int]:
        """The path, in a repository at a commit, of the manifest of a pipeline, or None; and how many manifests are there.

        The one that gives that ID, or that its place in the repository
        gives it (:func:`chartbook.identity.derive_pipeline_id`: the
        repository's name at the top, the folder's name below, under the
        scope its address gives). The only manifest there is is not taken
        for it unasked: an entry that names another pipeline's repository
        would be told to build that pipeline, for ever.
        """
        from chartbook.resolve import MANIFEST_NAME

        paths = source.paths(commit, MANIFEST_NAME)
        # Those whose place gives the ID are read first: of many, at most so many are read
        paths.sort(key=lambda path: _derived(source.url, path) != pipeline)
        for path in paths[:MOST_MANIFESTS]:
            if self._id_at(source, commit, path[: -len(MANIFEST_NAME)].rstrip("/")) == pipeline:
                return path, len(paths)
        return None, len(paths)

    def _id_at(self, source: "_Source", commit: str, subdirectory: str) -> str:
        """The ID of the pipeline in a folder of a repository at a commit: the one its manifest gives, or its place does; empty where there is none."""
        import tomli

        from chartbook.resolve import MANIFEST_NAME

        path = f"{subdirectory}/{MANIFEST_NAME}" if subdirectory else MANIFEST_NAME
        try:
            text = source.text(commit, path)
        except (ValueError, GitError, snapshot.SnapshotError):
            return ""
        if text is None:
            return ""
        try:
            project = tomli.loads(text).get("project")
        except (tomli.TOMLDecodeError, ValueError):
            # A manifest that cannot be read is still its folder's: the ID its place gives, and its own run says what is wrong with it
            return _an_id(_derived(source.url, path))
        project = project if isinstance(project, dict) else {}
        # As a manifest's own `repo_url` comes before the remote, where it names a repository
        written = _text(project.get("repo_url"))
        return _an_id(project.get("id")) or _an_id(_derived(written, path) or _derived(source.url, path))

    def _kept(self, manifest: Optional[str], lockfile: Optional[str], base: Optional[Path], shown: str) -> _Place:
        """The two files as they are at a commit, in a folder of their own to be read from."""
        from chartbook.resolve import MANIFEST_NAME

        self._count += 1
        files = self.scratch / str(self._count)
        files.mkdir()
        for name, text in ((MANIFEST_NAME, manifest), (lock.LOCK_FILE, lockfile)):
            if text is not None:
                with open(files / name, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    f.write(text)
        return _Place(files, base, shown)


class _Source:
    """A repository's files at a commit, with nothing checked out: from a clone on this machine as it is, or from the git cache once it is fetched."""

    def __init__(self, walk: _Walk, url: str, clone: Optional[Path]):
        self.walk, self.url, self.clone = walk, url, clone

    def commit(self, wanted: Optional[str], pipeline: str) -> tuple[str, str]:
        """The commit to read, in full: the one a pin names, the one an entry's ``commit`` starts, or where the repository is now; and why not, where it cannot be had.

        :param wanted: Seven to forty hex digits, or None.
        """
        if self.clone is not None:
            try:
                return snapshot._git(self.clone, "rev-parse", "--verify", "--quiet", f"{wanted or 'HEAD'}^{{commit}}").strip(), ""
            except snapshot.SnapshotError:
                if not wanted:
                    return "", f"its clone, {self.clone}, has no commit yet"
                return "", f"its clone, {self.clone}, does not have the commit {wanted[:7]}"
        why = self.walk._fetch(self.url, pipeline)
        if why:
            return "", f"its repository could not be fetched ({why})"
        cache = self.walk.git_cache()
        try:
            if wanted and _FULL_COMMIT.match(wanted):
                if not lock._has_commit(cache, self.url, wanted, fetch=True):
                    return "", f"its repository does not have the commit {wanted[:7]}"
                return wanted, ""
            # Never pinned: the default branch, or the commit its entry starts
            return cache.resolve(self.url, wanted or None), ""
        except (GitError, ValueError, OSError) as error:
            return "", _first_line(error)

    def paths(self, commit: str, named: str) -> list[str]:
        """Where the files of one name are at a commit, each from the top with ``/`` between its parts."""
        if self.clone is None:
            return self.walk.git_cache().paths_at(self.url, commit, named)
        listed = snapshot._git(self.clone, "ls-tree", "-r", "-z", "--name-only", commit).split("\0")
        return [path for path in listed if path == named or path.endswith(f"/{named}")]

    def text(self, commit: str, path: str) -> Optional[str]:
        """A file's text at a commit; None if the commit has no such file."""
        if self.clone is None:
            return self.walk.git_cache().text_at(self.url, commit, path)
        try:
            return snapshot._git(self.clone, "show", f"{commit}:{path}")
        except snapshot.SnapshotError:
            return None


def _derived(address: str, path: str) -> str:
    """The ID a manifest's place in the repository at an address gives a pipeline with no ID of its own; empty where the address names no repository."""
    from chartbook.identity import _sanitize_component, id_from_address

    at_top = id_from_address(address) if address else None
    if not at_top:
        return ""
    if "/" not in path:
        return at_top
    scope = at_top.rpartition("/")[0]
    name = _sanitize_component(path.split("/")[-2])
    return f"{scope}/{name}" if scope else name


def _within(within: str, path: str) -> Optional[str]:
    """A ``path`` entry of a pipeline in a repository, as a folder of that repository; None where it leads out of it, or is no relative path."""
    if not path or path.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", path):
        return None
    joined = posixpath.normpath(posixpath.join(within, path.replace("\\", "/")))
    if joined == ".":
        return ""
    return None if joined.startswith("../") or joined == ".." else joined


@contextlib.contextmanager
def _not_for_ever():
    """While a walk fetches: a fetch that receives nothing is given up (:data:`SLOWEST_FETCH`), where the person has not said how long to wait."""
    set_here = {name: value for name, value in SLOWEST_FETCH.items() if name not in os.environ}
    try:
        # http.lowSpeedLimit and http.lowSpeedTime, in any of git's own files: the environment would go over them
        said = subprocess.run(
            ["git", "config", "--get-regexp", r"^http\.lowspeed(limit|time)$"], capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        said = ""
    if said:
        set_here = {}
    os.environ.update(set_here)
    try:
        yield
    finally:
        for name in set_here:
            os.environ.pop(name, None)


def find(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    only: Optional[Iterable[str]] = None,
    echo: Callable[[str], None] = lambda line: None,
) -> Listing:
    """What the pipeline in a folder reads that is not in the store, each after everything it reads.

    The lockfile is read as it is on disk: ``chartbook pin`` and ``chartbook
    run`` ask this after their pin, of what it could not pin.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default, with the stores its
        dependencies name.
    :param git_cache: Where a repository is fetched to; this user's by
        default.
    :param only: The keys of the pipeline's own dependencies to ask it of;
        all by default.
    :param echo: Called with a line before each repository is fetched,
        which may take a while.
    :raises NoOrder: If what is not in the store depends on itself, in
        the words a run has for a cycle.
    :raises chartbook.snapshot.SnapshotError: If the folder holds no pipeline.
    :raises ValueError: If the pipeline's own ``[dependencies]`` is malformed.
    """
    from chartbook import lineage
    from chartbook.multi_store import with_dependencies
    from chartbook.resolve import MANIFEST_NAME

    directory = Path(project_dir).resolve()
    root = snapshot.pipeline_in(directory)
    looked_in = with_dependencies(directory, store)
    try:
        own_top = snapshot.code_of(directory).top
    except snapshot.SnapshotError:
        own_top = None
    entries = getattr(looked_in, "entries", None)
    listing = Listing(
        root, directory, top=own_top,
        stores=[str(entry.store) for entry in entries] if entries else [str(looked_in)],
    )
    asked = None if only is None else set(only)
    #: The pipelines on the way down, and the edge that led to each
    chain: list[str] = [root]
    edges: list = []
    #: The line each pipeline at a commit has, by number
    numbered: dict = {}

    with tempfile.TemporaryDirectory(prefix="chartbook-missing-") as scratch, _not_for_ever():
        walk = _Walk(looked_in, git_cache, echo, Path(scratch), _beside(directory), own_top)

        def visit(place: _Place) -> tuple[list[int], str, bool]:
            needs, untold, builds = walk.needs(place)
            reads: list[int] = []
            for need in needs:
                first = len(chain) == 1
                if first and (need.pipeline == root or (asked is not None and need.key not in asked)):
                    continue  # one that reads itself is said by its pin; and only what was asked of
                edge = lineage.Edge(chain[-1], need.pipeline, need.key, f"declared in {place.shown}")
                if need.pipeline in chain:
                    at = chain.index(need.pipeline)
                    loop = lineage.Cycle(edges[at:] + [edge], edges[:at])
                    raise NoOrder(
                        root, f"{lineage.cycle_lead(loop)}, so there is no order to build in.\n{lineage.explain_cycle(loop)}"
                    )
                wanted = need.wanted
                if wanted is None:
                    continue
                # One that was never pinned is met by any line of that pipeline
                known = numbered.get((wanted.pipeline, wanted.commit)) or (
                    None if wanted.commit else next((n for (pipeline, _), n in numbered.items() if pipeline == wanted.pipeline), None)
                )
                if known is None and wanted.commit:
                    # A line of it with no pin, listed already from another reader, that builds this very
                    # commit: it is this build, and takes the pin. At another commit they are two builds
                    earlier = next(
                        ((at, n) for (pipeline, at), n in numbered.items() if pipeline == wanted.pipeline and not at), None
                    )
                    line = listing.wanted[earlier[1] - 1] if earlier is not None else None
                    if line is not None and line.read_at and _COMMIT.match(wanted.commit) and line.read_at.startswith(wanted.commit):
                        line.commit, line.on_commit, line.built, line.by_path = wanted.commit, True, False, False
                        del numbered[(wanted.pipeline, earlier[0])]
                        numbered[(wanted.pipeline, wanted.commit)] = known = earlier[1]
                if known is not None:
                    if first:
                        listing.keys.add(need.key)
                    reads.append(known)
                    continue
                if len(chain) > DEEPEST:
                    above, wanted.unknown = None, f"the list stops here: it is more than {DEEPEST} pipelines deep"
                else:
                    above, wanted.unknown = walk.place_of(wanted)
                if wanted.absent and first:
                    continue  # the repository its entry names holds no such pipeline: an entry to put right, as its pin says
                if first:
                    listing.keys.add(need.key)
                if above is not None:
                    chain.append(wanted.pipeline)
                    edges.append(edge)
                    try:
                        wanted.reads, wanted.unknown, wanted.builds = visit(above)
                    except NoOrder:
                        raise
                    except Exception as error:  # noqa: BLE001 - a manifest that cannot be read: said in its line
                        wanted.unknown = f"its {MANIFEST_NAME} cannot be read ({_first_line(error)})"
                    finally:
                        chain.pop()
                        edges.pop()
                listing.wanted.append(wanted)
                numbered[(wanted.pipeline, wanted.commit)] = len(listing.wanted)
                reads.append(len(listing.wanted))
            return sorted(set(reads)), untold, builds

        visit(_Place(directory, directory, str(directory / MANIFEST_NAME)))
    return listing


def after_pin(
    project_dir: Union[str, Path], pins: "lock.PinReport", store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None, echo: Callable[[str], None] = lambda line: None,
) -> Optional[Listing]:
    """The list for what a pin just could not pin; None where nothing of it is a pipeline to build.

    Asked only of the dependencies whose pin found no snapshot, or found
    its pinned bytes gone: with no such problem nothing is read here, and
    nothing is fetched.

    :raises NoOrder: As :func:`find`.
    """
    keys = {event.dependency for event in pins.problems if event.status in ("no_snapshot", "lost")}
    if not keys:
        return None
    try:
        listing = find(project_dir, store, git_cache, only=keys, echo=echo)
    except (snapshot.SnapshotError, StoreError, OSError, ValueError):
        return None  # what the pin said stands
    return listing if listing.wanted else None


#: On Windows, in the place of a word that one of its shells would read even inside quotes: a command a
#: message prints never holds such a word. The list says it better, and gives no command at all
NOT_TEXT = "ITS-NAME-HOLDS-A-SIGN-A-SHELL-READS"

#: Said of a repository whose pipeline could not be placed in it, where the command names the repository's top
NOT_AT_THE_TOP = "if it is not at the top of its repository, give its folder there to `--project-dir`"


def _first_line(error: object) -> str:
    """What went wrong, in a line a list can hold: the first line of it, with no full stop."""
    lines = str(error).strip().splitlines()
    return _plain(lines[0].rstrip(".")) if lines else ""


def _plain(text: str, most: int = 300) -> str:
    """Text a file gave (an ID, an address, a path), as a terminal can show it: no control or format character, and not without end."""
    import unicodedata

    # Controls, format characters, lone surrogates, private and unassigned ones, and line separators: not a
    # space of another kind, which a folder's name may well have
    kept = "".join(
        character for character in text
        if unicodedata.category(character) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
    )
    return kept if len(kept) <= most else kept[: most - 1] + "…"


def _quoted(text: Union[str, Path], windows: Optional[bool] = None) -> str:
    """A word of a command, as this system's shells take it: quoted where it has to be, and never with a control character.

    :param windows: Whether for Windows, where the word is one that
        ``cmd.exe``, PowerShell and Git Bash all take; by the system it runs
        on, by default.
    """
    text = _plain(str(text), most=4096)
    if not (os.name == "nt" if windows is None else windows):
        return shlex.quote(text)
    # cmd.exe: inside double quotes `&`, `|`, `<`, `>`, `^` and spaces are text. A `%` stays
    # as it is: doubled it is one only in a batch file, and these lines are pasted at a prompt, where `%20` in an
    # address must stay `%20`. (A `%NAME%` that names a variable is filled in there, in quotes or out, and
    # nothing typed prevents it: the word is then another word, and still one word.)
    # PowerShell takes the same word, bare or in double quotes, but for a `$NAME` or a backtick in it, which it
    # reads in double quotes and cmd.exe does not: no one spelling is right in both, and cmd's is the one given.
    # Git Bash, which comes with git there, reads a `\` outside quotes as an escape (`C:\work\rates` reaches
    # the command as `C:workrates`; found by typing it, 2026-11-20), and inside double quotes as itself before
    # anything a path has. So a word with a backslash is in double quotes, a path among them. (Not right there:
    # a `$NAME` or a backtick, as in PowerShell, and the `\\` a network path begins with.) What no spelling
    # makes text in all three, the list gives no command for: `_a_windows_shell_reads`. And no other message
    # is to hold it either, whoever writes it: the word is then this one, which runs nothing and says why
    if _a_windows_shell_reads([text]):
        return NOT_TEXT
    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text):
        return text
    # A backslash that would come before the closing quote would be read with it, as a quote that is text:
    # doubled, it is one backslash (`"C:\\"`, of a drive's own folder)
    return '"' + text + "\\" * (len(text) - len(text.rstrip("\\"))) + '"'


def typed(words: Iterable[Union[str, Path]], windows: Optional[bool] = None) -> str:
    """A command as a message prints it, to be pasted: its words, each as this system's shells take it.

    What ``shlex.join`` gives is for a POSIX shell alone: a folder on
    Windows comes out of it in single quotes, which ``cmd.exe`` reads as
    part of the word.
    """
    return " ".join(_quoted(word, windows) for word in words)


def _in(folder: Union[str, Path], windows: Optional[bool] = None) -> str:
    """`` --project-dir FOLDER``, which ends a command of the list: the folder it builds is named in it, and none is entered.

    `cd FOLDER && chartbook run` is one line only where the shell reads
    `&&`, and Windows PowerShell does not; `cd /d`, which cmd.exe needs to
    change the drive, no PowerShell reads. A command that names its folder
    is the same line in every shell, and leaves whoever types it where
    they are.
    """
    return f" --project-dir {_quoted(folder, windows)}"


def _counted(numbers: list[int]) -> str:
    """1; 1 and 2; 1, 2 and 5."""
    said = [str(number) for number in numbers]
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} and {said[-1]}"


def _clone_name(url: str) -> str:
    """The folder ``git clone`` makes of a repository: the last part of its address, without ``.git``."""
    name = re.split(r"[/\\:]", url.rstrip("/\\"))[-1]
    name = name[:-4] if name.endswith(".git") else name
    return name if re.fullmatch(r"[A-Za-z0-9._-]+", name) and name.strip(".") else "repository"


def _clone_folders(beside: Path, name: str) -> list[Path]:
    """Where a clone of a repository may be, beside the pipeline's own: under the name ``git clone`` gives it, or the next names the list offers where that one is taken (``NAME-2`` … ``NAME-9``, then ``NAME-clone``)."""
    return [*(beside / (name if number == 1 else f"{name}-{number}") for number in range(1, 10)), beside / f"{name}-clone"]


def _named_by_the_disk(folder: Path) -> Path:
    """A folder by the name the folder it is in lists it under.

    A clone is looked for under the name its address gives (``rates``),
    and a disk that takes either letter case finds ``Rates`` for it. Where
    a folder is in its repository is told from the name the disk gives, so
    under the other one the clone could not be read, and a command that
    named it so would be refused.
    """
    try:
        names = os.listdir(folder.parent)
    except OSError:
        return folder
    if folder.name in names:
        return folder
    alike = [name for name in names if name.casefold() == folder.name.casefold()]
    return folder.with_name(alike[0]) if len(alike) == 1 else folder


#: What cmd.exe fills in by itself, where no variable of that name is set
_CMD_OWN = frozenset({
    "CD", "DATE", "TIME", "RANDOM", "ERRORLEVEL", "CMDEXTVERSION", "CMDCMDLINE", "HIGHESTNUMANODENUMBER", "__CD__", "__APPDIR__",
})

#: What PowerShell takes for a double quote, beside the one on the keyboard
_QUOTES = "\u201c\u201d\u201e"


def _a_windows_shell_reads(words: Iterable[Union[str, Path]], environment: Optional[Iterable[str]] = None) -> str:
    """What, in a word of a command, a shell on Windows reads even inside double quotes, as a message names it; empty for nothing.

    On Windows a word is in double quotes, and each of its shells reads
    something inside them:

    - PowerShell and Git Bash a ``$`` (a variable, and with a parenthesis
      a command to run) and a backtick. A ``$`` that ends the word, or
      comes before a slash of either kind, is text to both: a share that
      is not listed is named so (``\\\\server\\home$\\work``). One that
      comes after a backslash is not: Git Bash takes the two for a ``$``
      that is text, and the folder is then another.
    - Git Bash a ``!``, for a command typed before, and a ``\\"``, which it
      takes for a quote that is text, so that the next one ends the word.
    - PowerShell a ``"`` of the kind a word processor writes, which ends
      the word as the plain one does.
    - ``cmd.exe`` a ``%NAME%`` whose name is a variable. So a ``%`` is
      text only where it begins the two digits a web address writes a
      sign with (``%20``), and no name between two of them is a variable
      of this machine, or one cmd.exe fills in by itself (``%CD%``).
    - ``cmd.exe`` again, behind PowerShell: a word with no space in it is
      handed on without its quotes, and where the command is a batch file
      (a shim of pyenv's is one) cmd.exe reads its ``&``, ``|``, ``<``,
      ``>`` and ``^``. A word with a space keeps its quotes.

    No one spelling keeps any of them as text in all three, so a line with
    one is given no command. A folder may be named so, and an address or a
    folder in a lockfile or in a repository's tree is anyone's: a command
    that held ``$env:TOKEN`` would send the token where the address says,
    and one that held ``$(…)`` would run it.

    The word is read as it is printed (:func:`_plain`), which is what is
    pasted.

    :param environment: The names of the variables that are set; this
        process's, by default.
    """
    names = {name.upper() for name in (os.environ if environment is None else environment)} | _CMD_OWN
    for word in words:
        word = _plain(str(word), most=4096)
        for sign in ("`", '"', "!", *_QUOTES):
            if sign in word:
                return "a backtick" if sign == "`" else f"a `{sign}`"
        if re.search(r"\\\$|\$(?![\\/]|$)", word):
            return "a `$`"
        # A space or a tab, and no other kind: whether PowerShell quotes a word for a space of another kind is not known
        behind = None if re.search(r"[ \t]", word) else re.search(r"[&|<>^]", word)
        if behind:
            return f"a `{behind[0]}`"
        # As cmd.exe reads a line at its prompt: from a `%` to the next is a name (up to a `:`, which
        # begins what to take of it); one that is no variable is left as text, and its second `%` may begin another
        start = word.find("%")
        while start != -1:
            end = word.find("%", start + 1)
            if end == -1:
                break
            name = word[start + 1:end].split(":", 1)[0]
            if name.upper() in names:
                return f"`%{name}%`"
            start = end
        # And a name that is no variable here may be one in the shell the line is pasted into
        if re.search(r"%(?![0-9A-Fa-f]{2})", word):
            return "a `%`"
    return ""


def _worktree_at(tree: Path, commit: str) -> bool:
    """Whether a folder is a checkout that git knows, with that commit checked out: a worktree the list said to add, as it was left.

    A folder of that name that is anything else (a leftover, a worktree
    somebody has since moved to another commit) is not it, and is passed by.
    """
    try:
        if not tree.is_dir():
            return False
        top = Path(snapshot._git(tree, "rev-parse", "--show-toplevel").strip())
        return _same(top, tree) and snapshot._git(tree, "rev-parse", "HEAD").strip().startswith(commit)
    except (snapshot.SnapshotError, OSError):
        return False


def said(
    listing: Listing, again: str = "chartbook run", done: str = "built", here: Optional[Union[str, Path]] = None,
    windows: Optional[bool] = None,
) -> list[str]:
    """The list as it is printed: what cannot be done yet, each pipeline to build with what to type, and what to type after.

    A line is one command, as every shell takes it: none enters a folder
    and none is joined to another (``&&``), so the lines are the same in a
    POSIX shell, in ``cmd.exe`` and in PowerShell, and whoever types them
    stays where they are. Each can be pasted from any folder, in the order
    given, the last among them: a folder on this machine is named whole,
    and a repository is cloned beside the pipeline's own, which is where a
    ``path`` entry would look for it. A command never moves the
    pipeline's own repository to another commit: a pipeline in that
    repository is built in a worktree of it.

    On Windows a line whose commands would hold what one of its shells
    reads even inside quotes (:func:`_a_windows_shell_reads`) is given no
    command, and says so; so is the last.

    :param again: The command to give once they are built, as it was
        typed. It is given the pipeline's folder.
    :param done: What cannot be done yet, as a participle: ``built``, or ``pinned``.
    :param here: The folder a folder on this machine is shown from; the
        working directory by default.
    :param windows: Whether the commands are for Windows' shells; by the
        system it runs on, by default.
    """
    windows = os.name == "nt" if windows is None else windows
    #: The words of the line being made, as they are before they are quoted
    held: list[str] = []

    def word(text: Union[str, Path]) -> str:
        held.append(str(text))
        return _quoted(text, windows)

    def named(folder: Union[str, Path]) -> str:
        held.append(str(folder))
        return _in(folder, windows)

    wanted = listing.wanted
    one = len(wanted) == 1
    pipelines = len({line.pipeline for line in wanted})
    here = Path(here) if here is not None else Path.cwd()
    beside = _beside(listing.directory)
    lines = [
        f"{_plain(listing.root)} cannot be {done} yet: "
        + ("1 pipeline it reads is" if pipelines == 1 else f"{pipelines} pipelines it reads are")
        + (
            f" not in the store at {_plain(listing.stores[0])}." if len(listing.stores) == 1
            else f" not in your stores ({', '.join(_plain(shown) for shown in listing.stores)})."
        ),
        # "With the commands below": a build by itself ends with no snapshot, and these do. "One at a time": a
        # line is one command, and typed together each runs whatever the one before it did
        "Build it first, with the commands below, one at a time. They end with a snapshot, which is what this one reads." if one
        else "Build them in this order, with the commands below, one at a time. Each ends with a snapshot, which is what the next one reads.",
        "",
    ]
    #: What the commands above a line have made or moved: clones, worktrees, and repositories now on another commit
    cloned: dict = {}
    worktrees: dict = {}
    moved: set = set()

    def at_its_commit(top: Path, folder: Path, commit: str, make: str) -> list[str]:
        """Check a repository out and build in a folder of it: from its top, since the folder may not be there until the checkout."""
        moved.add(top)
        return [f"git -C {word(top)} checkout {commit}", make + named(folder)]

    def in_a_worktree(line: Wanted, commit: str, make: str, fetch: str = "") -> list[str]:
        """Build in a worktree of the pipeline's own repository at a commit, which leaves the repository itself where it is."""
        add = commit not in worktrees
        if add:
            # One that is there, on that commit, is used as it is. A folder of its name that is anything else is
            # passed by, for the next name that is free
            names = _clone_folders(beside, f"{_clone_name(listing.top.name)}-at-{commit}")
            there = next((tree for tree in names if _worktree_at(tree, commit)), None)
            add = there is None
            worktrees[commit] = there or next((tree for tree in names if not os.path.lexists(tree)), names[-1])
        tree = worktrees[commit]
        within = os.path.relpath(line.folder, listing.top) if line.folder is not None else line.subdirectory
        commands = [make + named(tree / within if within else tree)]
        if add:
            commands.insert(0, f"git -C {word(listing.top)} worktree add {word(tree)} {commit}")
        if fetch:
            commands.insert(0, fetch)
        return commands

    for number, line in enumerate(wanted, 1):
        held.clear()
        before = (dict(cloned), dict(worktrees))
        pinned = bool(line.commit) and bool(_COMMIT.match(line.commit))
        at = f" at {line.commit[:7]}" if pinned else ""
        # In a command, enough of a commit that a large repository has no two of it: of the commit it was read
        # at, where an entry's own `commit` gives fewer digits
        resolved = bool(line.read_at) and (not pinned or line.read_at.startswith(line.commit))
        commit = (line.read_at if resolved else line.commit if pinned else "")[:12]
        built = line.built and line.top not in moved
        # One with no build script commits what it declares, and one that is built has its files: a
        # snapshot is all there is to make, and a build that may take an hour is not run again
        make = "chartbook run --snapshot" if line.builds and not built else "chartbook snapshot"
        if (
            not line.builds and line.folder is not None and (not pinned or line.on_commit)
            and not _would_be_held(line.folder, line.pipeline)
        ):
            # Nothing builds it, and what it declares is not all committed: its files are taken as they
            # are, which is typed (chartbook.built). A snapshot without that would be refused. Asked of
            # the folder as it stands, so not of one that a line is to check out to another commit first
            make = "chartbook snapshot --as-is"
        unknown = line.unknown
        in_own = listing.top is not None and line.top is not None and _same(line.top, listing.top)
        if line.absent:
            # Its repository was read, and has no pipeline of this ID: nothing there to build
            where = f"{_plain(line.repository)}, which holds no pipeline of that ID" + (f" at {line.read_at[:7]}" if line.read_at else "")
            commands = []
        elif line.folder is not None:
            shown = _plain(_from(line.folder, here))
            if pinned and in_own and not line.on_commit:
                # In the pipeline's own repository, at another commit: a checkout would move the pipeline
                # itself, so it is built in a worktree of that commit, and the reader's work stays where it is
                where = f"{shown} (a folder of this repository, at another commit)"
                commands = in_a_worktree(line, commit, make)
            else:
                # Checked out where its pin says, or, for one that was never pinned, where it was read once a
                # line above has left its repository on another commit. Never the pipeline's own repository
                moves = (pinned and (not line.on_commit or line.top in moved)) or (not pinned and line.top in moved and commit and not in_own)
                where = f"{shown} (a folder on this machine{', built already' if built else ''})"
                if line.repository and not in_own:
                    where = f"{shown} (a clone of {_plain(line.repository)}{', built already' if built else ''})"
                if moves and line.top is not None:
                    commands = at_its_commit(line.top, line.folder, commit, make)
                else:
                    commands = [*([f"git -C {word(line.folder)} checkout {commit}"] if moves else []), make + named(line.folder)]
        elif line.repository and line.clone is not None:
            # A clone of it is here, and its files could not be read at that commit. Where it lacks the commit,
            # fetched there, it can be. Its folder in the clone is the one its reader names, or where the clone has
            # it now
            fetch = f"git -C {word(line.clone)} fetch{' --unshallow' if line.shallow else ''}" if line.lacks else ""
            where = f"{_plain(_from(line.clone, here))} (a clone of {_plain(line.repository)})"
            into = line.clone / line.subdirectory if line.subdirectory else line.clone
            if in_own and pinned:
                commands = in_a_worktree(line, commit, make, fetch)  # and not by moving the pipeline's own repository
            elif pinned:
                commands = [*([fetch] if fetch else []), *at_its_commit(line.clone, into, commit, make)]
            elif line.lacks:
                # Never pinned, and its clone could not be read where it is: it has no commit yet (`git init`, an
                # `origin`, and nothing pulled). A fetch would leave its folder empty; a pull fills it
                commands = [f"git -C {word(line.clone)} pull origin HEAD", make + named(line.clone)]
            else:
                commands = [make + named(into)]
            if unknown and not line.placed:
                unknown += (
                    f"; {NOT_AT_THE_TOP}" if not line.subdirectory
                    else "" if line.given else "; its folder is where the clone has it now"
                )
        elif line.repository:
            address = _plain(line.repository)
            first = address not in cloned
            if first:
                # Beside the pipeline's own, under the name `git clone` gives it, or the next that is free
                name = _clone_name(address)
                cloned[address] = next(
                    (folder for folder in _clone_folders(beside, name) if not os.path.lexists(folder)), beside / f"{name}-clone"
                )
            clone = cloned[address]
            into = clone / line.subdirectory if line.subdirectory else clone
            where = address
            # A commit where its pin names one; and for one that was never pinned, the commit it was read at once a
            # line above has left the clone elsewhere
            if commit and (pinned or clone in moved):
                commands = at_its_commit(clone, into, commit, make)
            else:
                commands = [make + named(into)]
            if first:  # once for a repository of several pipelines: a second clone into the same folder would only fail
                commands.insert(0, f"git clone {word(address)} {word(clone)}")
            if unknown and not line.placed:
                unknown += f"; {NOT_AT_THE_TOP}"
        else:
            where = (
                f"its folder, {line.expected}, is not on this machine, and its repository is not recorded" if line.expected
                else "its repository is not recorded"
            ) + ", so neither is what it reads in turn"
            commands = [f"In a clone of it: {'`git checkout ' + commit + '`, then ' if pinned else ''}`{make}`"]
            unknown = ""
        read = _a_windows_shell_reads(held) if windows else ""
        if read:
            # No spelling of it is text in every shell there, and a pasted line is run as it is read. What to
            # make is said, and not how: a checkout by hand may be of the pipeline's own repository
            commands = [
                f"No command is given for it: one would hold {read}, which a shell on Windows reads even inside quotes.",
                f"By hand: `{make}` in its folder{', at ' + commit if commit and pinned else ''}.",
            ]
            # Nothing of it was typed: no clone was made by it, and no worktree. A repository it would have
            # moved stays counted as moved, since by hand it may well be: a checkout too many costs nothing,
            # and a folder taken for built on a commit it is no longer on would be labelled with another's files
            for kept, was in zip((cloned, worktrees), before):
                kept.clear()
                kept.update(was)
        reads = f"; reads {_counted(line.reads)} above" if line.reads else ""
        lines.append(f"{number}. {_plain(line.pipeline)}{at}    {where}{reads}")
        lines += [f"     {command}" for command in commands]
        if line.absent:
            lines.append("     It could not be found there, so no command is given for it.")
        elif unknown:
            lines.append(f"     What it reads in turn is not known: {unknown}. Its own `chartbook run` says.")
    # With its folder, as every command above has its own: typed wherever those were, it builds this pipeline.
    # The pipeline's folder may be one of somebody's repository too, named as they named it
    own = _a_windows_shell_reads([listing.directory]) if windows else ""
    lines += ["", "Then here again:", (
        f"     In this pipeline's folder, which no command can name (it holds {own}): `{again}`" if own
        else f"     {again}{_in(listing.directory, windows)}"
    )]
    if again == "chartbook run" and all(line.by_path and line.builds for line in wanted):
        these = "this folder" if one else "these folders"
        lines.append(f"Or `chartbook run --upstream` here, which builds and snapshots {these} itself.")
    # The other way on, and the likelier one where people share a store: nothing to build at all
    lines.append(
        f"Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has "
        f"{'it' if one else 'them'}, or wait for its sync to finish."
    )
    return lines


def _would_be_held(folder: Path, pipeline: str) -> bool:
    """Whether `chartbook snapshot` of a folder would be made as it is typed, and not refused for files that no build left."""
    from chartbook import built

    try:
        built.check(folder, built.pipeline_of(folder, pipeline))
    except built.NotHeld:
        return False
    except (OSError, ValueError):
        pass  # not known: a folder that is not there yet, a manifest that cannot be read
    return True


def _is_built(folder: Path) -> bool:
    """Whether a folder has nothing uncommitted, has on disk everything its manifest declares with a path, declares something a snapshot holds, and is what the last build here ran on and left.

    The last, so that the `chartbook snapshot` a list gives for it is one
    that is made, and not one that is refused (:mod:`chartbook.built`).
    """
    from chartbook import built, run

    try:
        return (
            run._declares_what_a_snapshot_holds(folder) and not run.unwritten(folder) and not snapshot.uncommitted(folder)
            and built.would_hold(folder, built.pipeline_of(folder))
        )
    except Exception:  # noqa: BLE001 - a manifest that cannot be read is not known to be built
        return False


def _same(one: Path, other: Path) -> bool:
    """Whether two paths are one folder, on a disk that may not tell case apart too."""
    try:
        return one == other or os.path.samefile(one, other)
    except OSError:
        return False


def _beside(directory: Path) -> Path:
    """The folder a pipeline's repository is in: where a clone of another is looked for, and where the list says to put one.

    The pipeline's own folder's, where its repository is the home folder
    or holds it (settings kept in git): beside that would be above home.
    """
    directory = Path(directory)
    try:
        top = snapshot.code_of(directory).top
    except snapshot.SnapshotError:
        return directory.parent
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if top.parent == top or (home is not None and (top == home or top in home.parents)):
        return directory.parent
    return top.parent


def _from(folder: Path, here: Path) -> str:
    """A folder as it is shown from another: relative where that is the shorter, as a manifest's ``path`` writes it."""
    try:
        relative = os.path.relpath(folder, here)
    except ValueError:  # another drive, on Windows
        return str(folder)
    return relative if len(relative) < len(str(folder)) else str(folder)
