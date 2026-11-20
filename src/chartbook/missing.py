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
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from chartbook import lock, snapshot
from chartbook.gitcache import GitCache, GitError, default_git_cache
from chartbook.identity import strip_url_credentials
from chartbook.store import Store, StoreError

#: How far up the walk goes before it stops reading (as the walk for cycles: :data:`chartbook.lineage.DEEPEST`).
DEEPEST = 64

#: How many manifests of one repository are read to find a pipeline's own.
MOST_MANIFESTS = 200

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
        repository: Its repository's address, where the pin recorded one
            or the entry names one.
        folder: Its folder, where it is one on this machine.
        subdirectory: Its folder within its repository, where that was
            read; empty at the top.
        on_commit: Whether its folder on this machine is on that commit
            already, so that nothing has to be checked out.
        builds: Whether its manifest, where it was read, has a ``build``
            script. One that has none commits what it declares, and its
            snapshot is made by ``chartbook snapshot``.
        built: Whether its folder on this machine is on the commit to
            build and has on disk everything its manifest declares with a
            path: a snapshot is all it lacks, and nothing has to be built
            again.
        reads: The lines above it that it reads, by their numbers from 1.
        unknown: Why what it reads in turn is not known, where it is not.
    """

    pipeline: str
    commit: Optional[str] = None
    repository: Optional[str] = None
    folder: Optional[Path] = None
    subdirectory: str = ""
    on_commit: bool = False
    builds: bool = True
    built: bool = False
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
    """

    root: str
    directory: Path
    wanted: list[Wanted] = field(default_factory=list)
    keys: set = field(default_factory=set)


@dataclass
class _Place:
    """Where one pipeline's manifest and lockfile are read from.

    Attributes:
        files: A folder that holds the two files.
        base: The folder on this machine that its ``path`` entries are
            relative to; None for one read from its repository.
        shown: The manifest, as a message names it.
    """

    files: Path
    base: Optional[Path]
    shown: str


@dataclass
class _Need:
    """One dependency read at a place: its key, the pipeline it is by its ID, and what to build where the store lacks it."""

    key: str
    pipeline: str
    wanted: Optional[Wanted]


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


class _Walk:
    """Reads what each pipeline depends on, and tells which of it the store lacks."""

    def __init__(self, store: Store, git_cache: Optional[GitCache], echo: Callable[[str], None], scratch: Path, beside: Path):
        self.store = store
        self._git_cache = git_cache
        self.echo = echo
        self.scratch = scratch
        #: The folder the pipeline's own repository is in: where a clone of another is looked for, and would be put
        self.beside = beside
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
            folder = Path(entry["_resolved_path"]) if entry.get("_resolved_path") and place.base is not None else None
            if lock.names_a_snapshot(was):
                # A lockfile is anyone's: what it calls a pipeline is shown, so it is text a terminal can show
                pipeline = _plain(lock.pinned_pipeline(was, folder) or _text(entry.get("_store")))
                if not pipeline:
                    continue  # a pin from before pins said whose they are, of a folder that is not here
                wanted = None
                if self._pin_is_not_here(was, locked.assets_of(key), folder):
                    repository = _text(location.get("repository")) or None
                    here = folder if folder is not None and (folder / MANIFEST_NAME).is_file() else self._cloned(pipeline, repository)
                    wanted = Wanted(pipeline, _text(location.get("commit")), repository, here)
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
                    repository = _text(entry.get("_repository")) or None
                    wanted = Wanted(pipeline, at or None, repository, self._cloned(pipeline, repository))
                found.append(_Need(key, pipeline, wanted))
            elif folder is None:
                untold.append(f"it reads a folder beside it ({_plain(_text(entry.get('path')))}) that its lockfile does not pin")
            else:
                if not (folder / MANIFEST_NAME).is_file():
                    continue  # no pipeline there: the pin says so
                try:
                    pipeline = snapshot.pipeline_in(folder)
                    newest, _ = snapshot.newest_for(folder, self.store)
                except (snapshot.SnapshotError, StoreError, OSError, ValueError):
                    continue  # a catalog, a folder that is not in git, a record that cannot be read: the pin says so
                found.append(_Need(key, pipeline, Wanted(pipeline, None, None, folder) if newest is None else None))
        return found, "; ".join(untold), builds

    def _cloned(self, pipeline: str, repository: Optional[str]) -> Optional[Path]:
        """A clone of a pipeline's repository beside this one's, if there is one: a folder named as ``git clone`` names it, or as the pipeline is, that holds that pipeline.

        Where it is, nothing is fetched: its files are read from it, and
        the line says to build there. A repository that needs a password
        cannot be fetched here at all, and its clone can still be read.
        """
        from chartbook.resolve import MANIFEST_NAME

        names = [_clone_name(repository)] if repository else []
        names.append(pipeline.rsplit("/", 1)[-1])
        for name in dict.fromkeys(names):
            folder = self.beside / name
            try:
                if (folder / MANIFEST_NAME).is_file() and snapshot.pipeline_in(folder) == pipeline:
                    return folder
            except (snapshot.SnapshotError, OSError, ValueError):
                continue
        return None

    def _pin_is_not_here(self, was: dict, assets: dict, folder: Optional[Path]) -> bool:
        """Whether the store has neither the snapshot a pin names, nor a build of yours of that commit, nor every pinned file."""
        if lock.read_from(was, self.snapshots(), folder):
            return False  # the pin itself, or a build of yours that stands in or does not: said as it is, by the pin
        pins = [record for record in assets.values() if record.get("content_hash") and lock.in_lockfile(record)]
        # With nothing of it in the lockfile, its entry is the pin, and names a snapshot that is not here
        return not pins or any(not self.store.has(record["content_hash"]) for record in pins)

    def place_of(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        """Where a pipeline to build has its manifest and lockfile at its commit; or None, and why what it reads is not known."""
        try:
            if wanted.folder is not None:
                return self._in_folder(wanted)
            if wanted.repository:
                return self._in_repository(wanted)
        except Exception as error:  # noqa: BLE001 - whatever stops the reading is said in the line, and the line stays
            return None, _first_line(error)
        return None, "its repository is not recorded"

    def _in_folder(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        from chartbook.resolve import MANIFEST_NAME

        folder = wanted.folder
        if not wanted.commit:
            wanted.built = _is_built(folder)
            return _Place(folder, folder, str(folder / MANIFEST_NAME)), ""
        if not _COMMIT.match(wanted.commit):
            return None, "its pin names no commit git would take"
        try:
            code = snapshot.code_of(folder)
        except snapshot.SnapshotError:
            return None, f"{folder} is not in a git repository"
        wanted.on_commit = code.commit.startswith(wanted.commit)
        wanted.built = wanted.on_commit and _is_built(folder)
        within = f"{code.subdirectory}/" if code.subdirectory else ""
        try:
            manifest = snapshot._git(code.top, "show", f"{wanted.commit}:{within}{MANIFEST_NAME}")
        except snapshot.SnapshotError:
            return None, (
                f"{folder} does not have its {MANIFEST_NAME} at {wanted.commit[:7]} (`git fetch` there, if the "
                f"commit is not in it)"
            )
        try:
            lockfile = snapshot._git(code.top, "show", f"{wanted.commit}:{within}{lock.LOCK_FILE}")
        except snapshot.SnapshotError:
            lockfile = None  # none in that commit: its run pins the newest of each
        return self._kept(manifest, lockfile, folder, f"{folder / MANIFEST_NAME} at {wanted.commit[:7]}"), ""

    def _in_repository(self, wanted: Wanted) -> tuple[Optional[_Place], str]:
        from chartbook.resolve import MANIFEST_NAME

        url, cache = wanted.repository, self.git_cache()
        shown = strip_url_credentials(url)
        if url not in self._fetched:
            self.echo(f"Fetching {_plain(shown)}, to see what {_plain(wanted.pipeline)} reads in turn.")
            try:
                cache.fetch(url)
                self._fetched[url] = ""
            except (GitError, ValueError, OSError) as error:
                self._fetched[url] = _first_line(error) or "git could not fetch it"
        if self._fetched[url]:
            return None, f"its repository could not be fetched ({self._fetched[url]})"
        try:
            if wanted.commit and _FULL_COMMIT.match(wanted.commit):
                commit = wanted.commit
                if not lock._has_commit(cache, url, commit, fetch=True):
                    return None, f"its repository does not have the commit {commit[:7]}"
            else:
                # Never pinned: the default branch, or the commit its entry starts
                commit = cache.resolve(url, wanted.commit or None)
        except (GitError, ValueError, OSError) as error:
            return None, _first_line(error)
        chosen = self._manifest_of(wanted.pipeline, url, commit)
        if chosen is None:
            return None, f"no {MANIFEST_NAME} of {wanted.pipeline} was found in its repository at {commit[:7]}"
        within = chosen[: -len(MANIFEST_NAME)]
        wanted.subdirectory = within.rstrip("/")
        return self._kept(
            cache.text_at(url, commit, chosen), cache.text_at(url, commit, f"{within}{lock.LOCK_FILE}"), None,
            _plain(f"{within}{MANIFEST_NAME} of {shown} at {commit[:7]}"),
        ), ""

    def _manifest_of(self, pipeline: str, url: str, commit: str) -> Optional[str]:
        """The path, in a repository at a commit, of the manifest of a pipeline: the only one there is, the one that gives that ID, or the one in a folder named as it is."""
        import tomli

        from chartbook.resolve import MANIFEST_NAME

        cache = self.git_cache()
        paths = cache.paths_at(url, commit, MANIFEST_NAME)[:MOST_MANIFESTS]
        if len(paths) <= 1:
            return paths[0] if paths else None
        name = pipeline.rsplit("/", 1)[-1]
        by_folder = None
        for path in paths:
            try:
                project = tomli.loads(cache.text_at(url, commit, path) or "").get("project")
            except (tomli.TOMLDecodeError, ValueError):
                continue
            given = project.get("id") if isinstance(project, dict) else None
            if given == pipeline:
                return path
            if not given and (path == f"{name}/{MANIFEST_NAME}" or path.endswith(f"/{name}/{MANIFEST_NAME}")):
                by_folder = by_folder or path
        return by_folder

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
    listing = Listing(root, directory)
    asked = None if only is None else set(only)
    #: The pipelines on the way down, and the edge that led to each
    chain: list[str] = [root]
    edges: list = []
    #: The line each pipeline at a commit has, by number
    numbered: dict = {}

    with tempfile.TemporaryDirectory(prefix="chartbook-missing-") as scratch:
        walk = _Walk(with_dependencies(directory, store), git_cache, echo, Path(scratch), _beside(directory))

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
                if first:
                    listing.keys.add(need.key)
                # One that was never pinned is met by any line of that pipeline
                known = numbered.get((wanted.pipeline, wanted.commit)) or (
                    None if wanted.commit else next((n for (pipeline, _), n in numbered.items() if pipeline == wanted.pipeline), None)
                )
                if known is not None:
                    reads.append(known)
                    continue
                above, wanted.unknown = (None, "the list stops here: it is more than 64 pipelines deep") if len(chain) > DEEPEST else walk.place_of(wanted)
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


def _first_line(error: object) -> str:
    """What went wrong, in a line a list can hold: the first line of it, with no full stop."""
    lines = str(error).strip().splitlines()
    return _plain(lines[0].rstrip(".")) if lines else ""


def _plain(text: str, most: int = 300) -> str:
    """Text a file gave (an ID, an address, a path), as a terminal can show it: no control or format character, and not without end."""
    kept = "".join(character for character in text if character.isprintable())
    return kept if len(kept) <= most else kept[: most - 1] + "…"


def _counted(numbers: list[int]) -> str:
    """1; 1 and 2; 1, 2 and 5."""
    said = [str(number) for number in numbers]
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} and {said[-1]}"


def _clone_name(url: str) -> str:
    """The folder ``git clone`` makes of a repository: the last part of its address, without ``.git``."""
    name = re.split(r"[/\\:]", url.rstrip("/\\"))[-1]
    name = name[:-4] if name.endswith(".git") else name
    return name if re.fullmatch(r"[A-Za-z0-9._-]+", name) and name.strip(".") else "repository"


def said(listing: Listing, again: str = "chartbook run", done: str = "built", here: Optional[Union[str, Path]] = None) -> list[str]:
    """The list as it is printed: what cannot be done yet, each pipeline to build with what to type, and what to type after.

    Every command can be pasted from any folder: a folder on this machine
    is named whole, and a repository is cloned beside the pipeline's own,
    which is where a ``path`` entry would look for it.

    :param again: The command to give once they are built.
    :param done: What cannot be done yet, as a participle: ``built``, or ``pinned``.
    :param here: The folder a folder on this machine is shown from; the
        working directory by default.
    """
    wanted = listing.wanted
    one = len(wanted) == 1
    here = Path(here) if here is not None else Path.cwd()
    beside = _beside(listing.directory)
    lines = [
        f"{_plain(listing.root)} cannot be {done} yet: "
        + ("1 pipeline it reads is" if one else f"{len(wanted)} pipelines it reads are")
        + " not in your store.",
        "Build it first. It ends with a snapshot, which is what this one reads." if one
        else "Build them in this order. Each ends with a snapshot, which is what the next one reads.",
        "",
    ]
    cloned: set = set()
    for number, line in enumerate(wanted, 1):
        at = f" at {line.commit[:7]}" if line.commit and _COMMIT.match(line.commit) else ""
        checkout = f"git checkout {line.commit[:7]} && " if at and not line.on_commit else ""
        # One with no build script commits what it declares, and one that is built has its files: a
        # snapshot is all there is to make, and a build that may take an hour is not run again
        checkout += "chartbook run --snapshot" if line.builds and not line.built else "chartbook snapshot"
        unknown = line.unknown
        if line.folder is not None:
            where = f"{_plain(_from(line.folder, here))} (a folder on this machine{', built already' if line.built else ''})"
            commands = [f"cd {shlex.quote(str(line.folder))} && {checkout}"]
        elif line.repository:
            address = _plain(strip_url_credentials(line.repository))
            clone = beside / _clone_name(address)
            into = clone / _plain(line.subdirectory) if line.subdirectory else clone
            where = address
            commands = [f"cd {shlex.quote(str(into))} && {checkout}"]
            if clone not in cloned:
                # Once for a repository of several pipelines: a second clone into the same folder would only fail
                commands.insert(0, f"git clone {shlex.quote(address)} {shlex.quote(str(clone))}")
                cloned.add(clone)
        else:
            where = "its repository is not recorded, so neither is what it reads in turn"
            commands = [f"In a clone of it: {checkout}"]
            unknown = ""
        reads = f"; reads {_counted(line.reads)} above" if line.reads else ""
        lines.append(f"{number}. {_plain(line.pipeline)}{at}    {where}{reads}")
        lines += [f"     {command}" for command in commands]
        if unknown:
            lines.append(f"     What it reads in turn is not known: {unknown}. Its own `chartbook run` says.")
    lines += ["", "Then here again:", f"     cd {shlex.quote(str(listing.directory))} && {again}"]
    if again == "chartbook run" and all(line.folder is not None and not line.commit for line in wanted):
        these = "this folder" if one else "these folders"
        lines.append(f"Or `chartbook run --upstream` here, which builds and snapshots {these} itself.")
    # The other way on, and the likelier one where people share a store: nothing to build at all
    lines.append(
        f"Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has "
        f"{'it' if one else 'them'}, or wait for its sync to finish."
    )
    return lines


def _is_built(folder: Path) -> bool:
    """Whether a folder has on disk everything its manifest declares with a path, and declares something a snapshot holds."""
    from chartbook import run

    try:
        return run._declares_what_a_snapshot_holds(folder) and not run.unwritten(folder)
    except Exception:  # noqa: BLE001 - a manifest that cannot be read is not known to be built
        return False


def _beside(directory: Path) -> Path:
    """The folder a pipeline's repository is in: where a clone of another is looked for, and where the list says to put one."""
    try:
        return snapshot.code_of(directory).top.parent
    except snapshot.SnapshotError:
        return Path(directory).parent


def _from(folder: Path, here: Path) -> str:
    """A folder as it is shown from another: relative where that is the shorter, as a manifest's ``path`` writes it."""
    try:
        relative = os.path.relpath(folder, here)
    except ValueError:  # another drive, on Windows
        return str(folder)
    return relative if len(relative) < len(str(folder)) else str(folder)
