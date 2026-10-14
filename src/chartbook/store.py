"""The store: a local folder of files named by the hash of what is in them.

The store is where a pinned copy of another pipeline's asset is kept, and
later where a build's result is kept so that the same build need not run
twice. An object in it is one asset, and its name is the asset's content
hash (:mod:`chartbook.hashing`), so the same bytes pinned by ten projects
are one object.

::

    ~/.chartbook/store/
      store.json                                       which layout this is
      objects/sha256/7f/3a9c…/treasury_rates.parquet   an asset that is one file
      objects/sha256/b2/09e1…/year=2024/part-0.parquet an asset of many files
      builds/                                          a name kept free; nothing is written here
      roots/                                           the lockfiles that name objects
      snapshots/                                       what each commit of a pipeline built
      tmp/                                             objects being written

An object is a directory holding the asset's files under their own names.
That is why a path into the store still ends in ``.parquet``, and why a
partitioned dataset keeps folders like ``year=2024/``.

Four operations are the whole interface, and are what a second kind of
store (one a team shares, one that is hosted) would have to provide::

    from chartbook.store import Store

    store = Store("~/.chartbook/store")
    stored = store.put("_data/treasury_rates.parquet")   # -> its hash
    store.has(stored.content_hash)                       # True
    store.get(stored.content_hash)                       # the object's directory
    store.delete(stored.content_hash)

There is no base class and no registry of stores. One exists, so the seam
is this class; an interface is extracted when a second is written.

**The declared file never moves.** ``put`` leaves ``path`` where it is and
makes the object from it by the cheapest means the disk allows, tried in
this order (:data:`LINKS`):

``reflink``
    A copy-on-write clone (APFS, btrfs, XFS). Costs nothing, and is the
    store's own bytes: nothing outside the store can change it.
``hardlink``
    A second name for the same file. Costs nothing, and **is** the original
    file: if that is later rewritten in place, the object changes with it.
``symlink``
    A pointer to the original file. Crosses disks, changes whenever the
    original does, and dangles if the original is moved.
``copy``
    A full copy. The store's own bytes.

So an object made by ``reflink`` or ``copy`` is frozen, and one made by
``hardlink`` or ``symlink`` is frozen only for as long as the original is
left alone or is replaced with a new file, never rewritten.
:meth:`Store.verify` is what tells: it hashes every object again and
reports each whose content is no longer what its name says.

A snapshot (:mod:`chartbook.snapshot`) and pinning (:mod:`chartbook.lock`)
are what put things in the store. A snapshot's record is kept under
``snapshots/``, and what it names is never cleared. Pinning
leaves a note of each lockfile under ``roots/`` so that clearing the store
out never removes another project's pins. The design is "The store" in
``docs_src/design/asset-graph.md``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from chartbook import hashing
from chartbook.config import get_store_path

#: The ways the store can hold a file, cheapest first. The order is the
#: design's ("Links, not copies").
LINKS = ("reflink", "hardlink", "symlink", "copy")

#: The link kinds whose result is the store's own bytes, which nothing
#: outside the store can change.
FROZEN_LINKS = frozenset({"reflink", "copy"})

#: The version of the store's layout on disk.
SCHEMA = "chartbook/store/v1"

#: The file at the store's root that says which layout it has.
MARKER_FILE = "store.json"

#: Where objects are, under the root: ``objects/<algorithm>/<2 hex>/<rest>``.
OBJECTS_DIR = "objects"

#: Reserved for build records, which map the hash of a build's inputs to
#: the hash of its output. Nothing is written here yet.
BUILDS_DIR = "builds"

#: Where an object is assembled before it is moved into place.
TMP_DIR = "tmp"

#: Where the store remembers which lockfiles name its objects, so that
#: removing what nothing needs never removes another project's pins.
ROOTS_DIR = "roots"

_HEX = re.compile(r"^[0-9a-f]{64}$")
_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


class StoreError(Exception):
    """Raised when the store cannot do what was asked of it."""


class ObjectNotFoundError(StoreError, LookupError):
    """Raised when the store holds no object with a given hash."""


@dataclass(frozen=True)
class StoredObject:
    """An object in the store.

    Attributes:
        content_hash: The asset's content hash, ``sha256:<hex>``, which is
            the object's name.
        size_bytes: The total size of its files.
        path: The object's directory in the store.
        files: Its files, as paths inside that directory with forward
            slashes, sorted.
        entries: For an asset of several files, each file with its own
            size and hash, as it was just stored. Empty for an asset that
            is one file.
        links: The kinds of link that were used to make it, in the order of
            :data:`LINKS`. Empty when the object was already there.
        created: True if this call made the object; False if the store
            already held it.
    """

    content_hash: str
    size_bytes: int
    path: Path
    files: tuple[str, ...]
    links: tuple[str, ...] = ()
    created: bool = True
    entries: tuple[hashing.FileEntry, ...] = ()

    @property
    def frozen(self) -> bool:
        """Whether nothing outside the store can change what was just stored.

        True when every file was cloned or copied. False when one was
        hard-linked or symlinked, or when the object was already there and
        how it was made is not known.
        """
        return bool(self.links) and set(self.links) <= FROZEN_LINKS


@dataclass(frozen=True)
class Root:
    """A lockfile whose pins the store keeps.

    Attributes:
        lockfile: The absolute path of a ``chartbook.lock``.
        hashes: The objects it named when it was last pinned or updated.
            That is what the store goes by if the file can no longer be
            found, on a drive that is unplugged, say.
    """

    lockfile: Path
    hashes: tuple[str, ...]


@dataclass(frozen=True)
class StoreProblem:
    """One object that is not what its name says.

    Attributes:
        content_hash: The object's name.
        path: Its directory in the store.
        message: What is wrong with it.
    """

    content_hash: str
    path: Path
    message: str

    def format(self) -> str:
        """Render as ``hash: message``, one line."""
        return f"{self.content_hash}: {self.message}"


def _split_hash(content_hash: str) -> tuple[str, str]:
    """Check a content hash and split it into its algorithm and hex digest.

    A hash becomes part of a path, and may come from a file someone else
    wrote, so nothing but ``sha256:<64 hex digits>`` is let through.
    """
    algorithm, _, digest = str(content_hash).partition(":")
    if algorithm != hashing.ALGORITHM or not _HEX.match(digest):
        raise ValueError(
            f"{content_hash!r} is not a content hash. Expected "
            f"'{hashing.ALGORITHM}:' followed by 64 hexadecimal digits."
        )
    return algorithm, digest


def _reflink(source: str, destination: str) -> None:
    """Clone a file copy-on-write: a second file that shares the first's blocks.

    :raises OSError: Where it cannot be done: the filesystem has no such
        thing, the two paths are on different disks, or the platform is
        one this function does not know how to ask.
    """
    if sys.platform == "darwin":
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        libc.clonefile.restype = ctypes.c_int
        if libc.clonefile(os.fsencode(source), os.fsencode(destination), 0) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), destination)
        return
    if sys.platform.startswith("linux"):
        import fcntl

        ficlone = 0x40049409  # FICLONE, from <linux/fs.h>
        with open(source, "rb") as original, open(destination, "xb") as clone:
            fcntl.ioctl(clone.fileno(), ficlone, original.fileno())
        return
    raise OSError(errno.ENOTSUP, "no copy-on-write clone here", destination)


def _link(source: str, destination: str, links: Iterable[str]) -> str:
    """Make *destination* from *source* by the first kind of link that works.

    :returns: The kind that worked.
    :raises StoreError: If none did.
    """
    failures = []
    for kind in links:
        try:
            if kind == "reflink":
                _reflink(source, destination)
            elif kind == "hardlink":
                os.link(source, destination)
            elif kind == "symlink":
                os.symlink(source, destination)
            else:
                shutil.copyfile(source, destination)
        except (OSError, NotImplementedError, AttributeError) as error:
            failures.append(f"{kind}: {error}")
            # A failed attempt may leave part of a file behind
            if os.path.lexists(destination):
                os.remove(destination)
            continue
        if kind in FROZEN_LINKS:
            # The store's own bytes: keep them from being written through
            # the store. A hard link is the original file under another
            # name, with the original's one set of permissions, so it is
            # left as it is.
            os.chmod(destination, _READ_ONLY)
        return kind
    raise StoreError(
        f"Could not store {source}. Tried " + "; ".join(failures) + "."
    )


def _make_removable(path: str) -> None:
    """Give back the permissions that removing *path* needs, to the store only.

    Removal can fail on a read-only file (Windows) or in a read-only
    directory. The directory holding *path* is the store's, and so is a
    file that is a clone or a copy. A symlink or a hard link leads to a
    file that is not the store's, and its permissions are never touched.
    """
    os.chmod(os.path.dirname(path), stat.S_IRWXU)
    if os.path.islink(path):
        return
    if os.path.isdir(path):
        os.chmod(path, stat.S_IRWXU)
    elif os.lstat(path).st_nlink == 1:
        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)


def _is_frozen(directory: Path) -> bool:
    """Whether every file under a directory is the store's own bytes.

    A symlink is not, and neither is a file that has another name somewhere:
    a hard link to a file outside the store.
    """
    for file in hashing.directory_files(directory):
        if file.is_symlink() or os.lstat(file).st_nlink > 1:
            return False
    return True


def _remove_tree(directory: Path) -> None:
    """Remove a directory and what is in it, read-only files included."""

    def retry_writable(function, path, _error):
        _make_removable(path)
        function(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(directory, onexc=retry_writable)
    else:
        shutil.rmtree(directory, onerror=retry_writable)


class Store:
    """A store in a directory on this machine.

    :param root: The store's directory. It need not exist: it is made when
        something is first put in it.
    """

    def __init__(self, root: Union[str, Path]):
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self._layout_checked = False

    def __repr__(self) -> str:
        return f"Store({str(self.root)!r})"

    def object_path(self, content_hash: str) -> Path:
        """Where the object with a given hash is, or would be.

        :raises ValueError: If *content_hash* is not a content hash.
        """
        algorithm, digest = _split_hash(content_hash)
        return self.root / OBJECTS_DIR / algorithm / digest[:2] / digest[2:]

    def has(self, content_hash: str) -> bool:
        """Whether the store holds an object with this hash."""
        return self.object_path(content_hash).is_dir()

    def get(self, content_hash: str) -> Path:
        """The directory of the object with this hash.

        The asset's files are in it under their own names: one file for an
        asset that is a file, a tree for one that is a directory or a glob.
        They are there to be read, not written.

        :raises ObjectNotFoundError: If the store has no such object.
        """
        self._check_layout()
        path = self.object_path(content_hash)
        if not path.is_dir():
            raise ObjectNotFoundError(
                f"The store at {self.root} has no object {content_hash}."
            )
        return path

    def put(
        self, path: Union[str, Path], links: Iterable[str] = LINKS
    ) -> StoredObject:
        """Store what a declared ``path`` names, and return its hash.

        *path* is a file, a directory, or a glob, as in a manifest. It is
        left exactly where it is. The object is made beside it, by the
        first of *links* that the disk allows, and then hashed, so the name
        an object gets is the hash of what the store actually holds.

        Storing the same content twice makes one object. Storing a file
        whose bytes are already there under another name adds the name.

        :param path: An absolute path, which may contain glob characters.
        :param links: The kinds of link to try, in order; see :data:`LINKS`.
            Pass ``("reflink", "copy")`` for an object that must not change
            when the original does. If the store already holds this content
            as a link to a file outside it, the object is then replaced by
            one that is the store's own.
        :returns: The stored object.
        :raises FileNotFoundError: If nothing is at *path*.
        :raises StoreError: If no kind of link works, or the store's layout
            is one this version does not know.
        :raises ValueError: If *links* names an unknown kind.
        """
        links = tuple(links)
        unknown = [kind for kind in links if kind not in LINKS]
        if unknown or not links:
            raise ValueError(
                f"Unknown link kind(s) {unknown}. The kinds are: {', '.join(LINKS)}."
            )
        found = hashing.find_files(path)
        if found is None or not found.files:
            raise FileNotFoundError(f"Nothing at {path} to put in the store.")

        self._check_layout(create=True)
        staging = self.root / TMP_DIR / uuid.uuid4().hex
        staging.mkdir(parents=True)
        try:
            used = set()
            root = os.path.abspath(found.root)
            for file in found.files:
                relative = os.path.relpath(os.path.abspath(file), root)
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                # The real file, so the store never holds a link to a link
                used.add(_link(os.path.realpath(file), str(destination), links))

            if found.single:
                content = hashing.hash_file(staging / found.files[0].name)
            else:
                content = hashing.hash_directory(staging)
            final = self.object_path(content.content_hash)
            created = self._move_into_place(
                staging,
                final,
                single=found.single,
                frozen=set(links) <= FROZEN_LINKS,
            )
        finally:
            if staging.exists():
                _remove_tree(staging)

        return StoredObject(
            content_hash=content.content_hash,
            size_bytes=content.size_bytes,
            path=final,
            files=tuple(
                sorted(
                    file.relative_to(final).as_posix()
                    for file in hashing.directory_files(final)
                )
            ),
            links=tuple(kind for kind in LINKS if kind in used) if created else (),
            created=created,
            entries=content.files,
        )

    def _check_layout(self, create: bool = False) -> None:
        """Check that the store on disk has the layout this class reads.

        A store says which layout it has in :data:`MARKER_FILE`. One made by
        a later ChartBook, laid out differently, is refused instead of
        being misread.

        :param create: If True, a store that does not exist yet is made.
        :raises StoreError: If the layout is not this one.
        """
        if self._layout_checked:
            return
        marker = self.root / MARKER_FILE
        try:
            with open(marker, encoding="utf-8") as f:
                schema = json.load(f).get("schema")
        except FileNotFoundError:
            if not create:
                return  # nothing here yet; nothing to misread
            self.root.mkdir(parents=True, exist_ok=True)
            # Written whole or not at all, for another process reading it
            temporary = marker.with_name(f"{MARKER_FILE}.{uuid.uuid4().hex}.tmp")
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump({"schema": SCHEMA}, f)
                f.write("\n")
            os.replace(temporary, marker)
            self._layout_checked = True
            return
        except (OSError, ValueError, AttributeError) as error:
            raise StoreError(f"Cannot read {marker}: {error}") from None
        if schema != SCHEMA:
            raise StoreError(
                f"The store at {self.root} has the layout {schema!r}, and this "
                f"version of ChartBook reads {SCHEMA!r}. Use a newer ChartBook, "
                f"or point CHARTBOOK_STORE at another directory."
            )
        self._layout_checked = True

    @staticmethod
    def _move_into_place(
        staging: Path, final: Path, single: bool, frozen: bool = False
    ) -> bool:
        """Move a finished object to its name. Returns False if it was there.

        The move is one rename, so another process sees the whole object or
        none of it. If two processes store the same content at once, one
        rename wins and the other finds the object already there.

        :param frozen: True if the caller asked for an object that cannot
            change. One that is already there as a link to a file outside
            the store is then replaced by the one just made, which is not.
        """
        final.parent.mkdir(parents=True, exist_ok=True)
        if frozen and final.is_dir() and not _is_frozen(final):
            if single:
                # The same bytes may be there under other names, from other
                # pipelines. They come along, as copies of the new frozen
                # file, so that no pin loses the name it resolves by.
                (frozen_file,) = list(staging.iterdir())
                for other in final.iterdir():
                    if other.name != frozen_file.name and other.is_file():
                        shutil.copyfile(frozen_file, staging / other.name)
                        os.chmod(staging / other.name, _READ_ONLY)
            aside = staging.with_name(staging.name + ".linked")
            os.rename(final, aside)
            try:
                os.rename(staging, final)
            except OSError:
                if not final.is_dir():
                    os.rename(aside, final)
                    raise
            _remove_tree(aside)
            return True
        if not final.is_dir():
            try:
                os.rename(staging, final)
                return True
            except OSError:
                if not final.is_dir():
                    raise
        if single:
            # The same bytes under a name the object does not have yet
            for file in staging.iterdir():
                if not os.path.lexists(final / file.name):
                    os.rename(file, final / file.name)
        try:
            # Stored again just now: an object someone is in the middle of
            # pinning must not look old enough to be cleared away
            os.utime(final, None)
        except OSError:
            pass
        return False

    def _root_file(self, lockfile: Union[str, Path]) -> Path:
        """Where the store notes one lockfile: a name made from its path."""
        key = hashlib.sha256(os.path.abspath(lockfile).encode("utf-8")).hexdigest()
        return self.root / ROOTS_DIR / f"{key[:32]}.json"

    def add_root(self, lockfile: Union[str, Path], hashes: Iterable[str]) -> None:
        """Note that a lockfile names these objects, so that they are kept.

        Called whenever a lockfile is written. One note is kept per
        lockfile, and a later call replaces it.

        :param lockfile: The path of a ``chartbook.lock``.
        :param hashes: The content hashes it names.
        :raises ValueError: If one of *hashes* is not a content hash.
        """
        hashes = sorted(set(hashes))
        for content_hash in hashes:
            _split_hash(content_hash)
        self._check_layout(create=True)
        note = self._root_file(lockfile)
        note.parent.mkdir(parents=True, exist_ok=True)
        temporary = note.with_name(f"{note.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(
                    {"lockfile": os.path.abspath(lockfile), "hashes": hashes}, f, indent=1
                )
                f.write("\n")
            os.replace(temporary, note)
        except BaseException:
            # Whole or not at all: a half-written note is not left behind
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def remove_root(self, lockfile: Union[str, Path]) -> bool:
        """Forget a lockfile. Its objects are then kept by nothing.

        :returns: True if the store had a note of it.
        """
        note = self._root_file(lockfile)
        if not note.is_file():
            return False
        note.unlink()
        return True

    def roots(self) -> list[Root]:
        """Every lockfile the store has a note of, by path.

        :raises StoreError: If a note cannot be read. Nothing should be
            removed from a store that cannot say what it is keeping.
        """
        self._check_layout()
        directory = self.root / ROOTS_DIR
        if not directory.is_dir():
            return []
        found = []
        for note in sorted(directory.glob("*.json")):
            try:
                with open(note, encoding="utf-8") as f:
                    stored = json.load(f)
                root = Root(Path(stored["lockfile"]), tuple(stored["hashes"]))
                for content_hash in root.hashes:
                    _split_hash(content_hash)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise StoreError(f"Cannot read {note}: {error}") from None
            found.append(root)
        return sorted(found, key=lambda root: str(root.lockfile))

    def size_of(self, content_hash: str) -> int:
        """The total size in bytes of an object's files; 0 if it has none."""
        total = 0
        for file in hashing.directory_files(self.object_path(content_hash)):
            try:
                total += file.stat().st_size
            except OSError:
                pass  # a link whose file has gone
        return total

    def age_of(self, content_hash: str, now: Optional[float] = None) -> float:
        """How many seconds ago an object was put in the store."""
        stored_at = self.object_path(content_hash).stat().st_mtime
        return (time.time() if now is None else now) - stored_at

    def delete(self, content_hash: str) -> bool:
        """Remove the object with this hash.

        Only the store's own names are removed. A file that an object was
        hard-linked or symlinked to is untouched.

        :returns: True if there was one to remove.
        """
        path = self.object_path(content_hash)
        if not path.is_dir():
            return False
        _remove_tree(path)
        try:
            path.parent.rmdir()  # the two-character folder, if now empty
        except OSError:
            pass
        return True

    def hashes(self) -> Iterator[str]:
        """The hash of every object in the store, in order."""
        self._check_layout()
        algorithm_dir = self.root / OBJECTS_DIR / hashing.ALGORITHM
        if not algorithm_dir.is_dir():
            return
        for prefix in sorted(p for p in algorithm_dir.iterdir() if p.is_dir()):
            for rest in sorted(p for p in prefix.iterdir() if p.is_dir()):
                digest = prefix.name + rest.name
                if _HEX.match(digest):
                    yield hashing.format_hash(digest)

    def verify(
        self, content_hashes: Optional[Iterable[str]] = None
    ) -> list[StoreProblem]:
        """Hash objects again, and report each that is not what its name says.

        This reads every byte. It is how a change made from outside is
        found: an object that was hard-linked or symlinked to a file which
        has since been rewritten, a symlink whose file has gone, or
        anything edited in the store by hand.

        :param content_hashes: The objects to check; every object by default.
        :returns: The problems found; empty when every object is intact.
        """
        asked = content_hashes is not None
        problems = []
        for content_hash in self.hashes() if not asked else content_hashes:
            path = self.object_path(content_hash)
            if not path.is_dir():
                problems.append(StoreProblem(content_hash, path, "not in the store"))
                continue
            message = self._what_is_wrong(content_hash, path)
            if message is not None:
                problems.append(StoreProblem(content_hash, path, message))
        return problems

    @staticmethod
    def _what_is_wrong(content_hash: str, path: Path) -> Optional[str]:
        """What is wrong with one object; None if nothing is."""
        files = sorted(hashing.directory_files(path))
        if not files:
            return "the object is empty"
        for file in files:
            if file.is_symlink() and not file.exists():
                return (
                    f"{file.relative_to(path).as_posix()} is a link to "
                    f"{os.readlink(file)}, which is no longer there"
                )

        cache = hashing.HashCache()  # fresh, so every byte is read
        try:
            # An asset that is one file is named by the hash of that file.
            # Its object may hold the same bytes under more than one name.
            flat = all(file.parent == path for file in files)
            if flat and all(
                hashing.hash_file(file, cache).content_hash == content_hash
                for file in files
            ):
                return None
            # An asset of several files is named by the hash of their listing
            actual = hashing.hash_files(files, path, cache).content_hash
        except OSError as error:
            return f"cannot be read: {error}"
        if actual == content_hash:
            return None
        if len(files) == 1:
            actual = hashing.hash_file(files[0], cache).content_hash

        outside = ""
        linked = [f for f in files if f.is_symlink() or f.stat().st_nlink > 1]
        if linked:
            name = linked[0].relative_to(path).as_posix()
            where = (
                f"a link to {os.readlink(linked[0])}"
                if linked[0].is_symlink()
                else "a hard link to a file outside the store"
            )
            outside = f". {name} is {where}, which has been rewritten"
        return f"its content is no longer what its name says (now {actual}){outside}"


def default_store() -> Store:
    """The store this user's ChartBook uses.

    ``CHARTBOOK_STORE`` if it is set; otherwise ``[store] path`` in
    ``~/.chartbook/settings.toml``; otherwise ``~/.chartbook/store``.
    """
    return Store(get_store_path())
