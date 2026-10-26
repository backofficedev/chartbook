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

What a store is, whatever holds it, is :class:`Store`: objects named by
their content hash, the lockfiles that keep them, and the snapshot
records. The folder store, :class:`FolderStore`, is the one that is built::

    from chartbook.store import FolderStore

    store = FolderStore("~/.chartbook/store")
    stored = store.put("_data/treasury_rates.parquet")   # -> its hash
    store.has(stored.content_hash)                       # True
    store.get(stored.content_hash)                       # the object's directory
    store.delete(stored.content_hash)

Another kind, an object store or a database, is a plugin: a class that
provides the same methods, found by the scheme of the store's URL in the
entry-point group ``chartbook.stores`` (:func:`store_for_url`). The store
is a setting of the machine, never of a pipeline; see
:func:`chartbook.config.get_store_url`.

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

**A store in a synced folder.** A folder that a sync service (Google
Drive, Dropbox, OneDrive) keeps in step between machines is a store they
share, and the service leaves two marks of its own in it. A file can be
there before all of its bytes are: a record says how many an asset has
(``size_bytes``), and :meth:`Store.incomplete` compares the sizes on disk
with it, which costs no read. And a file changed in two places at once is
kept twice, the second under a name of the service's
(``20261017T163232.294414Z (1).json``): records and origin notes are
listed by the names a store gives them (:func:`is_record_name`), so such
a copy is passed over; a copy of a note of a lockfile is read
(:attr:`Root.copy`), as a note only ever adds to what is kept.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import abc
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Optional, Union

from chartbook import hashing

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


class ReadOnlyStoreError(StoreError):
    """Raised when a store refused a write for want of permission.

    A store a team shares is read-only for most machines on purpose, so a
    caller that can do without the write (the note a pin leaves for ``gc``)
    catches this and carries on; see :func:`chartbook.lock.is_read_only`.
    """


class StoreUnreachableError(StoreError):
    """Raised when a remote store cannot be reached at all: no network, no service."""


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
        machine: The machine the lockfile is on
            (:func:`chartbook.config.get_machine_id`). A path names a file
            on one machine only, and one person's two machines can each
            have a lockfile at the same path. Empty for a note from before
            notes named their machine, which may be any machine's.
        host: That machine's host name when the note was written, for a
            person to read; nothing goes by it, as it may follow the network.
        note: The name of the note's file under ``roots/``, so that a
            person can find it; another name than the store gives a note
            is a sync service's copy of one (:attr:`copy`).
        snapshots: The snapshots the lockfile pinned when it was last
            pinned or updated, each ``(commit, made_at)`` as the lockfile
            names it, which ``store gc`` keeps. None for a note from before
            notes recorded them: the snapshots holding its objects are kept
            then, the newest holding each.
        node: The hardware address of the machine that wrote it
            (:func:`this_node`), for a person to read; nothing goes by it.
            Empty where it had none to give, or for a note from before
            notes recorded it.
        labelled: The model versions the lockfile pinned by label when it
            was last pinned or updated, each ``(commit, made_at, name,
            content_hash)``: the snapshot moment of the dependency the label
            was pinned from, the model's reference within its pipeline, and
            the version's hash. A label resolves to a version an older
            snapshot may hold, which the moment alone does not keep, so
            ``store gc`` keeps a snapshot holding each. None for a note
            from before notes recorded them.
    """

    lockfile: Path
    hashes: tuple[str, ...]
    machine: str = field(default="", compare=False)
    host: str = field(default="", compare=False)
    note: str = field(default="", compare=False)
    snapshots: Optional[tuple[tuple[str, str], ...]] = field(default=None, compare=False)
    node: str = field(default="", compare=False)
    labelled: Optional[tuple[tuple[str, str, str, str], ...]] = field(default=None, compare=False)

    @property
    def copy(self) -> bool:
        """Whether this is a sync service's copy of a note, not a note the store wrote."""
        return bool(self.note) and not is_root_name(self.note)


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
    """Remove a directory and what is in it, read-only files included.

    :raises OSError: What the system said of the first file or folder that
        could not be removed, once given the permissions removing it needs:
        another user's folder in a store users share, whose permissions
        are not this user's to give.
    """

    def retry_writable(function, path, error):
        try:
            _make_removable(path)
        except OSError:
            # Not this user's to make removable: what the removal itself
            # said is the plainer error (``onerror`` hands the exc_info tuple)
            raise (error[1] if isinstance(error, tuple) else error) from None
        function(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(directory, onexc=retry_writable)
    else:
        shutil.rmtree(directory, onerror=retry_writable)


#: Where a folder store keeps snapshot records: ``snapshots/<commit>/<name>/<time>.json``.
SNAPSHOTS_DIR = "snapshots"
#: The file beside a pipeline's records that notes the folders they were made from.
ORIGINS_FILE = "origins"
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
#: A record's name: when it was made, ``20261013T182205.123456Z``, and a count if two share that time.
_RECORD_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}(\.[0-9]{1,9})?Z(-[0-9]+)?\.json$")
#: A note of a lockfile's name: 32 hex digits of a hash (:func:`root_name`).
_ROOT_NAME = re.compile(r"^[0-9a-f]{32}\.json$")


def is_record_name(name: str) -> bool:
    """Whether a file is named as a store names a snapshot record.

    A sync service that finds a file changed in two places keeps both, the
    second under a name of its own, ``20261017T163232.294414Z (1).json``.
    That copy is not a record the store wrote, and is passed over.
    """
    return bool(_RECORD_NAME.match(name))


def is_root_name(name: str) -> bool:
    """Whether a file is named as a store names its note of a lockfile; a sync service's copy of one is not."""
    return bool(_ROOT_NAME.match(name))


def root_name(lockfile: Union[str, Path], machine: str = "") -> str:
    """The name of a store's note of one lockfile: a hash of the machine and the lockfile's path.

    Two machines can have a lockfile at one path, and each keeps its own
    note. With no machine, the name a note had before notes named theirs.
    """
    path = os.path.abspath(lockfile)
    key = f"{machine}\n{path}" if machine else path
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + ".json"


def this_machine(create: bool = True) -> str:
    """The name this machine goes by in a store's notes of lockfiles (:func:`chartbook.config.get_machine_id`).

    :param create: Whether to make it if there is none yet: only writing a note needs one.
    """
    from chartbook.config import get_machine_id

    return get_machine_id(create=create)


def this_host() -> str:
    """This machine's host name, as a note records it, for a person to read."""
    import socket

    return socket.gethostname()


def this_node() -> str:
    """The hardware address of one of this machine's network interfaces, as twelve hex digits; empty if it has none to give.

    For a person to read in a note, beside the host name: nothing goes by
    it, since one machine's may change (another interface, a dock, a
    restart). Asked only when a note is written. An address that is not
    the hardware's is none: Python's random stand-in (the multicast bit
    set), and a locally administered one.
    """
    import uuid

    node = uuid.getnode()
    if not node or (node >> 40) & 0b11:
        return ""
    return f"{node:012x}"


def root_document(
    lockfile: Union[str, Path],
    hashes: Iterable[str],
    snapshots: Iterable[tuple[str, str]],
    machine: str,
    labelled: Iterable[tuple[str, str, str, str]] = (),
) -> dict:
    """A note of a lockfile on this machine, named *machine*, as a store keeps it.

    :param labelled: The model versions the lockfile pins by label, each
        ``(commit, made_at, name, content_hash)`` (:attr:`Root.labelled`);
        the moment may be empty for a pin that names no snapshot.
    """
    return {
        "lockfile": os.path.abspath(lockfile),
        "machine": machine,
        "host": this_host(),
        "node": this_node(),
        "hashes": list(hashes),
        "snapshots": [
            {"commit": commit, "made_at": made_at}
            for commit, made_at in sorted(set(snapshots))
            if isinstance(commit, str) and _FULL_COMMIT.match(commit) and isinstance(made_at, str)
        ],
        "labelled": [
            {"commit": commit, "made_at": made_at, "name": name, "content_hash": content_hash}
            for commit, made_at, name, content_hash in sorted(set(labelled))
            if _is_labelled_entry(commit, made_at, name, content_hash)
        ],
    }


def _is_labelled_entry(commit: object, made_at: object, name: object, content_hash: object) -> bool:
    """Whether four values are a labelled version as a note records one: a moment (or none), a name, a content hash."""
    if not all(isinstance(value, str) for value in (commit, made_at, name, content_hash)):
        return False
    if (commit or made_at) and not _FULL_COMMIT.match(commit):
        return False
    try:
        _split_hash(content_hash)
    except ValueError:
        return False
    return bool(name)


def read_root(stored: dict, note: str = "") -> Root:
    """A note of a lockfile, from what a store kept in the file named *note*.

    :raises ValueError: If it is not a note a store writes, or a hash in it
        is not a content hash. So may ``KeyError`` and ``TypeError``.
    """
    machine, host, node = stored.get("machine", ""), stored.get("host", ""), stored.get("node", "")
    if not isinstance(machine, str) or not isinstance(host, str) or not isinstance(node, str):
        raise ValueError("its machine, host and node are not names")
    snapshots = None
    if isinstance(stored.get("snapshots"), list):
        # A pair that is not a full commit and a time (a lockfile edited by
        # hand) is passed over: the note's objects are kept all the same
        snapshots = tuple(sorted({
            (entry["commit"], entry["made_at"])
            for entry in stored["snapshots"]
            if isinstance(entry, dict) and isinstance(entry.get("commit"), str)
            and _FULL_COMMIT.match(entry["commit"]) and isinstance(entry.get("made_at"), str)
        }))
    labelled = None
    if isinstance(stored.get("labelled"), list):
        # An entry that is not a labelled version as a note records one (a
        # lockfile edited by hand) is passed over, as a snapshot pair is
        labelled = tuple(sorted({
            (entry["commit"], entry["made_at"], entry["name"], entry["content_hash"])
            for entry in stored["labelled"]
            if isinstance(entry, dict)
            and _is_labelled_entry(entry.get("commit"), entry.get("made_at"), entry.get("name"), entry.get("content_hash"))
        }))
    root = Root(Path(stored["lockfile"]), tuple(stored["hashes"]), machine, host, note, snapshots, node, labelled)
    for content_hash in root.hashes:
        _split_hash(content_hash)
    return root


def _read_note(note: Path) -> Optional[Root]:
    """One note, read from its file; None if there is none, or it cannot be read."""
    try:
        with open(note, encoding="utf-8") as f:
            return read_root(json.load(f), note.name)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _unreadable_note_remedy(name: str, error: Optional[Exception] = None) -> str:
    """What to do about a file under ``roots/`` that cannot be read.

    A sync that has not finished is the likeliest cause when the file cannot
    be opened or is not JSON (a file can be there before its bytes), for a
    note under its proper name as for a sync service's copy of one. A note
    that is JSON of another shape is not one this version reads, and is said
    so. Nothing is removed from the store until it is read or gone, since it
    may be the only record of a machine's pins.
    """
    if is_root_name(name) and error is not None and not isinstance(error, (OSError, json.JSONDecodeError)):
        return (
            f" It is not a note this version of ChartBook reads: remove roots/{name}; the next `chartbook pin`, "
            f"`chartbook update`, `--frozen` or read through its lockfile writes it again. Nothing is removed "
            f"from the store until it is read or gone"
        )
    if is_root_name(name):
        return (
            f" A sync that has not finished is the likeliest cause (a file there before its bytes): run this "
            f"again once it has finished. If it stays unreadable, remove roots/{name}; the next `chartbook pin`, "
            f"`chartbook update`, `--frozen` or read through its lockfile writes it again. Nothing is removed "
            f"from the store until it is read or gone"
        )
    return (
        f" It is not named as a note is: a sync service's copy of one, perhaps, half synced. Wait for the "
        f"sync, or remove roots/{name} if it is a copy nobody needs; nothing is removed from the store "
        f"until it is read or gone"
    )


def unreadable_detail(path: Path, error: Exception) -> str:
    """What is wrong with a JSON file that could not be read, for a message: ``the file is empty`` for one of no bytes, else the error."""
    try:
        if isinstance(error, ValueError) and path.stat().st_size == 0:
            return "the file is empty"
    except OSError:
        pass
    return str(error)


def declared_name(declared: str) -> Optional[str]:
    """The name a declared file has inside its object: the last part of its path, ``/`` and ``\\`` both separating parts.

    One rule for the three that must agree: :meth:`Store.put`, which names
    the file in the object; a record's list of what a reader opens
    (``chartbook.snapshot.files_read``); and the reader
    (``chartbook.resolve._held``). A manifest written on Windows says
    ``_output\\m.json``, and the object holds ``m.json`` on every system;
    a file whose own name holds a backslash, which only POSIX allows, is
    stored under what follows it, so that it reads the same everywhere.
    None for a path of no name.
    """
    parts = [part for part in re.split(r"[\\/]+", str(declared).strip()) if part not in ("", ".")]
    return parts[-1] if parts else None


def plain_parts(relative: str) -> Optional[list[str]]:
    """The parts of a path inside an object, if it is a plain relative path; else None.

    Plain: parts joined by single ``/``, none empty, ``.`` or ``..``, and no
    NUL; on Windows, also no backslash or colon, which it reads as a
    separator or a drive (elsewhere they are ordinary characters of a name,
    and an object may have a file named with them, ``part-2024-01-01T00:00``).
    A record or a key may come from anyone who can write to a store, and a
    reader makes a path of each.
    """
    if not isinstance(relative, str) or not relative or "\0" in relative:
        return None
    if os.name == "nt" and any(c in relative for c in "\\:"):
        return None
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return parts


def on_disk(folder: Path, parts: list[str]) -> Path:
    """The file at these parts of a path under a folder, as the disk names it.

    A name with a letter outside ASCII may be written in either of
    Unicode's forms (``é`` as one character, or as ``e`` and an accent),
    and a sync between macOS and Linux may hand a file over in the other:
    where the name as written is not there, a name equal to it under NFC
    is taken. An ASCII name is the same in both, and nothing is looked at.
    """
    exact = folder.joinpath(*parts)
    if all(part.isascii() for part in parts) or exact.exists() or exact.is_symlink():
        return exact
    here = folder
    for part in parts:
        wanted = here / part
        if not (wanted.exists() or wanted.is_symlink()):
            name = unicodedata.normalize("NFC", part)
            try:
                wanted = next((entry for entry in here.iterdir() if unicodedata.normalize("NFC", entry.name) == name), wanted)
            except OSError:
                pass
        here = wanted
    return here


#: The objects found whole as a record has them, in this process: an object does not change.
_found_whole: set = set()

#: The hash of the one file of an object, by its path, time and size, worked out once a process.
_hashed_once: dict = {}


def _hash_once(file: Path) -> Optional[str]:
    """The content hash of a file, worked out once a process while it is unchanged; None if it cannot be read."""
    try:
        seen = file.stat()
        key = (str(file), seen.st_mtime_ns, seen.st_size)
        if key not in _hashed_once:
            _hashed_once[key] = hashing.hash_file(file, hashing.HashCache()).content_hash
        return _hashed_once[key]
    except OSError:
        return None


def unsynced_part(
    path: Path, size_bytes: int, files: Optional[dict] = None, every: bool = False, content_hash: str = ""
) -> Optional[tuple[str, bool]]:
    """What of an object's folder is not as its record gives it, in a few words; None when nothing is.

    *files* are the files a reader opens, by their path in the object, each
    with its size, as the record gives them: the one file of an asset that
    is a file, under its own name (the object may hold the same bytes under
    other names too, which are other pins' business), or each file of a
    directory, which are then *every* file of it. Without them, as for a
    glob, the files the object holds are summed, as they were hashed; so
    they are when the one file named is not in it and what it holds is not
    those bytes under other names (by size, and for that rare case by the
    hash of one, against *content_hash*), as a directory pinned before
    records listed its files, which a reader reads as the folder.

    A file that is a link is no sync's doing, and is not judged here:
    :meth:`Store.verify` and a reader's own checks see to it. Only sizes and
    names are looked at, but in that rare case.

    :returns: What is wrong, and whether a sync that has not finished would
        explain it (False for a file the record does not list, a sync
        service's copy most likely, which waiting does not mend).
    """

    def size_of(file: Path) -> Optional[int]:
        try:
            return file.stat().st_size if file.is_file() else None
        except OSError:
            return None

    held = hashing.directory_files(path)
    present = [file for file in held if not file.is_symlink()]
    if files and len(files) == 1 and not every:
        ((relative, expected),) = files.items()
        own = on_disk(path, list(PurePosixPath(relative).parts))
        if not own.is_file() and not own.is_symlink():
            same = [file for file in present if file.parent == path and size_of(file) == expected]
            # The same bytes under other names, and this one on its way; or a
            # directory pinned before records listed its files, with one file
            # of the directory's size. Its hash tells which, in this rare case
            if content_hash and present and len(same) == len(present) and _hash_once(same[0]) == content_hash:
                return f"does not have {relative} yet", True
            files = None
    if files:
        listed = set()
        for relative, expected in sorted(files.items()):
            parts = plain_parts(relative)
            if parts is None:
                return (
                    f"is named by a record that lists {relative!r}, which is not a plain path in it: "
                    f"the record is not one a store wrote",
                    False,
                )
            listed.add(unicodedata.normalize("NFC", "/".join(parts)))
            file = on_disk(path, parts)
            if file.is_symlink():
                continue
            size = size_of(file)
            if size is None:
                return f"does not have {relative} yet", True
            if size != expected:
                return f"has {size:,} bytes of {relative} where its record says {expected:,}", True
        if every:
            for file in present:
                relative = file.relative_to(path).as_posix()
                # Compared as Unicode's one form: a sync between macOS and Linux may
                # write a listed name in the other. And a name starting "." no
                # reader reads (a Finder .DS_Store, a Syncthing .syncthing.*.tmp)
                if any(part.startswith(".") for part in relative.split("/")):
                    continue
                if unicodedata.normalize("NFC", relative) not in listed:
                    return (
                        f"holds {relative}, which its record does not list (a sync service's copy, most "
                        f"likely, which a reader of the folder would read as its own: remove that file "
                        f"from the object's folder)",
                        False,
                    )
        return None
    if len(present) != len(held):
        return None  # a link among its files: not judged by size
    if not present:
        return "has none of its files yet", True
    total = sum(size_of(file) or 0 for file in present)
    if total != size_bytes:
        return f"has {total:,} bytes where its record says {size_bytes:,}", True
    return None


class Store(abc.ABC):
    """What a store is, whatever holds it.

    Objects named by their content hash, the lockfiles (roots) that keep
    them, and the snapshot records, which say what each commit of a
    pipeline built. A kind of store provides these methods and nothing
    else is asked of it. :class:`FolderStore` is the one every install
    has; :class:`chartbook.stores.s3.S3Store` is a bucket, behind
    ``pip install chartbook[s3]``.
    """

    @abc.abstractmethod
    def put(self, path: Union[str, Path], links: Iterable[str] = LINKS) -> "StoredObject":
        """Store what a declared ``path`` names, and return its hash."""

    @abc.abstractmethod
    def has(self, content_hash: str) -> bool:
        """Whether the store holds an object with this hash."""

    @abc.abstractmethod
    def get(self, content_hash: str) -> Path:
        """Where a reader opens the object with this hash: its files under their own names."""

    @abc.abstractmethod
    def delete(self, content_hash: str) -> bool:
        """Remove the object with this hash; True if there was one."""

    @abc.abstractmethod
    def hashes(self) -> Iterator[str]:
        """The hash of every object in the store, in order."""

    @abc.abstractmethod
    def size_of(self, content_hash: str) -> int:
        """The total size in bytes of an object's files."""

    @abc.abstractmethod
    def age_of(self, content_hash: str, now: Optional[float] = None) -> float:
        """How many seconds ago an object was put in the store."""

    @abc.abstractmethod
    def verify(self, content_hashes: Optional[Iterable[str]] = None) -> list["StoreProblem"]:
        """Hash objects again, and report each that is not what its name says."""

    def lacks(self, content_hash: str, names: Iterable[str], single: bool = True) -> bool:
        """Whether a put of the same bytes would add a file the store's object lacks under one of these names.

        Two assets with the same bytes share one object, under each one's
        name; put back one at a time, the object may hold one name and not
        the other. False when nothing would be added, or that cannot be
        told without reading. Reads nothing.

        :param single: Whether the bytes are one file, not a directory.
        """
        return False

    def incomplete(
        self, content_hash: str, size_bytes: Optional[int], files: Optional[dict] = None, every: bool = False
    ) -> Optional[str]:
        """Why an object the store has is not whole as its record has it; None if it is, or if that cannot be told cheaply.

        A record says how many bytes an asset has (``size_bytes``), and the
        files a reader opens with the size of each (*files*, by their path
        in the object, *every* one of them for a directory; see
        :func:`unsynced_part`); a store in a folder a sync service keeps
        can have an object before all of them have arrived, or with a copy
        of one of them that the service made. Asked of every pin and every
        read, so it reads nothing; :meth:`verify` reads every byte. A store
        that cannot tell without reading says None.
        """
        return None

    @abc.abstractmethod
    def add_root(
        self,
        lockfile: Union[str, Path],
        hashes: Iterable[str],
        snapshots: Iterable[tuple[str, str]] = (),
        machine: Optional[str] = None,
        labelled: Iterable[tuple[str, str, str, str]] = (),
    ) -> None:
        """Note that a lockfile names these objects, pins these snapshots, and pins these model versions by label (:attr:`Root.labelled`), so that they are kept: under this machine's name, or *machine* (``""`` names the path alone)."""

    @abc.abstractmethod
    def remove_root(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> bool:
        """Forget a lockfile on this machine (or, with ``machine=""``, its note from before notes named their machine); True if the store had a note of it."""

    @abc.abstractmethod
    def roots(self) -> list["Root"]:
        """Every lockfile the store has a note of."""

    def root_of(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> Optional["Root"]:
        """This machine's note of a lockfile (or *machine*'s), if the store has one."""
        here = this_machine(create=False) if machine is None else machine
        path = Path(os.path.abspath(lockfile))
        return next((r for r in self.roots() if r.lockfile == path and r.machine == here and not r.copy), None)

    @abc.abstractmethod
    def snapshot_commits(self) -> set[str]:
        """Every commit some snapshot in the store was made at."""

    @abc.abstractmethod
    def snapshot_files(self, commit: str, name: str) -> list[Path]:
        """The records of one pipeline (by its record name) at one commit, as files to read."""

    @abc.abstractmethod
    def all_snapshot_files(self) -> list[Path]:
        """Every snapshot record in the store, as files to read."""

    @abc.abstractmethod
    def write_snapshot(self, commit: str, name: str, stamp: str, document: dict) -> Path:
        """Write one record, whole or not at all, and return its file."""

    @abc.abstractmethod
    def remove_snapshot(self, path: Path) -> bool:
        """Remove one record; True if it was there."""

    @abc.abstractmethod
    def note_origin(self, commit: str, name: str, top: str) -> None:
        """Note, beside a pipeline's records at a commit, the repository folder they came from."""

    @abc.abstractmethod
    def origins(self, commit: str, name: str) -> list[str]:
        """The repository folders a pipeline's records at a commit were made from, as noted."""

    def __str__(self) -> str:
        return repr(self)


class FolderStore(Store):
    """A store in a directory on this machine.

    :param root: The store's directory. It need not exist: it is made when
        something is first put in it.
    """

    def __init__(self, root: Union[str, Path]):
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self._layout_checked = False

    def __repr__(self) -> str:
        return f"FolderStore({str(self)!r})"

    def __str__(self) -> str:
        from chartbook.config import shown_store_url

        return shown_store_url(str(self.root))  # a //host path may carry a password

    def snapshot_folder(self, commit: str, name: str) -> Path:
        """Where the records of one pipeline at one commit are kept."""
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self.root / SNAPSHOTS_DIR / commit / name

    def snapshot_commits(self) -> set[str]:
        try:
            return {n for n in os.listdir(self.root / SNAPSHOTS_DIR) if _FULL_COMMIT.match(n)}
        except FileNotFoundError:
            return set()

    def snapshot_files(self, commit: str, name: str) -> list[Path]:
        folder = self.snapshot_folder(commit, name)
        if not folder.is_dir():
            return []
        return sorted(path for path in folder.glob("*.json") if is_record_name(path.name))

    def all_snapshot_files(self) -> list[Path]:
        directory = self.root / SNAPSHOTS_DIR
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("*/*/*.json") if is_record_name(path.name))

    def write_snapshot(self, commit: str, name: str, stamp: str, document: dict) -> Path:
        folder = self.snapshot_folder(commit, name)
        folder.mkdir(parents=True, exist_ok=True)
        final = folder / f"{stamp}.json"
        count = 1
        while final.exists():
            count += 1
            final = folder / f"{stamp}-{count}.json"
        temporary = folder / f"{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(document, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(temporary, final)
        finally:
            if temporary.exists():
                temporary.unlink()
        return final

    def remove_snapshot(self, path: Path) -> bool:
        """Remove one record; True if it was there.

        :raises StoreError: If it could not be removed, naming it and what
            to do (see :meth:`delete`).
        """
        path = Path(path)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as error:
            raise StoreError(
                f"Cannot remove the snapshot record {self._shown(path)}: {error.strerror or error}. "
                f"{self._not_this_users_remedy()}"
            ) from None
        folder = path.parent
        if not any(is_record_name(other.name) for other in folder.glob("*.json")):
            # The last record of this pipeline at this commit: its note of
            # origins goes too, and the folders if nothing else is in them. A
            # record another process is writing this moment is left alone.
            try:
                (folder / ORIGINS_FILE).unlink()
            except OSError:
                pass
            for empty in (folder, folder.parent):
                try:
                    empty.rmdir()
                except OSError:
                    break
        return True

    def note_origin(self, commit: str, name: str, top: str) -> None:
        folder = self.snapshot_folder(commit, name)
        folder.mkdir(parents=True, exist_ok=True)
        note = folder / ORIGINS_FILE
        try:
            known = note.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            known = []
        if top not in known:
            with open(note, "a", encoding="utf-8") as f:
                f.write(top + "\n")

    def origins(self, commit: str, name: str) -> list[str]:
        note = self.snapshot_folder(commit, name) / ORIGINS_FILE
        try:
            return [line for line in note.read_text(encoding="utf-8").splitlines() if line]
        except FileNotFoundError:
            return []

    def object_path(self, content_hash: str) -> Path:
        """Where the object with a given hash is, or would be.

        :raises ValueError: If *content_hash* is not a content hash.
        """
        algorithm, digest = _split_hash(content_hash)
        return self.root / OBJECTS_DIR / algorithm / digest[:2] / digest[2:]

    def has(self, content_hash: str) -> bool:
        """Whether the store holds an object with this hash.

        :raises StoreError: If the store has a layout this version does not
            read, as :meth:`get` does: what it holds cannot be said.
        """
        self._check_layout()
        return self.object_path(content_hash).is_dir()

    def get(self, content_hash: str) -> Path:
        """The directory of the object with this hash.

        The asset's files are in it under their own names: one file for an
        asset that is a file, a tree for one that is a directory or a glob.
        They are there to be read, not written.

        :raises ObjectNotFoundError: If the store has no such object.
        :raises StoreError: If the object's folder is a link, or leads out of
            the store's objects: a store a team shares holds what anyone put
            there, and a reader must not be handed a folder of its own.
        """
        self._check_layout()
        path = self.object_path(content_hash)
        if not path.is_dir():
            raise ObjectNotFoundError(
                f"The store at {self} has no object {content_hash}."
            )
        objects = Path(os.path.realpath(self.root / OBJECTS_DIR))
        if path.is_symlink() or not Path(os.path.realpath(path)).is_relative_to(objects):
            raise StoreError(
                f"The object {content_hash} in the store at {self} is a link, or leads out of "
                f"the store; it is not read. `chartbook store verify` checks a store."
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
                if found.single:
                    # Under the one name every system reads it by (declared_name)
                    relative = declared_name(relative) or relative
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                # The real file, so the store never holds a link to a link
                used.add(_link(os.path.realpath(file), str(destination), links))

            if found.single:
                content = hashing.hash_file(staging / (declared_name(found.files[0].name) or found.files[0].name))
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
            raise StoreError(f"Cannot read {self._shown(marker)}: {unreadable_detail(marker, error)}") from None
        if schema != SCHEMA:
            raise StoreError(
                f"The store at {self} has the layout {schema!r}, and this "
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

    def add_root(
        self,
        lockfile: Union[str, Path],
        hashes: Iterable[str],
        snapshots: Iterable[tuple[str, str]] = (),
        machine: Optional[str] = None,
        labelled: Iterable[tuple[str, str, str, str]] = (),
    ) -> None:
        """Note that a lockfile on this machine names these objects, and pins these snapshots, so that they are kept.

        Called whenever a lockfile is written. One note is kept per
        lockfile and machine, and a later call replaces it. A note of the
        same path from before notes named their machine is left as it is:
        it may be another machine's, and only a person can tell. In this
        user's own store (:meth:`is_users_own`) it can only be this
        machine's, and this note takes its place.

        Machines are told apart by name only
        (:func:`chartbook.config.get_machine_id`): two that share one (a
        clone that kept its operating system's identity, with a copied
        home) write one note per path.

        :param lockfile: The path of a ``chartbook.lock``.
        :param hashes: The content hashes it names.
        :param snapshots: The snapshots it pins, each ``(commit, made_at)``.
        :param machine: The name to note it under: this machine's by
            default; ``""`` for the path alone, as notes were named before
            they named machines (a CI runner with no name of its own),
            which no note under a name then takes the place of.
        :param labelled: The model versions it pins by label, each
            ``(commit, made_at, name, content_hash)`` (:attr:`Root.labelled`).
        :raises ValueError: If one of *hashes* is not a content hash.
        """
        hashes = sorted(set(hashes))
        for content_hash in hashes:
            _split_hash(content_hash)
        self._check_layout(create=True)
        machine = this_machine() if machine is None else machine
        note = self._root_file(lockfile, machine)
        note.parent.mkdir(parents=True, exist_ok=True)
        temporary = note.with_name(f"{note.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(root_document(lockfile, hashes, snapshots, machine, labelled), f, indent=1)
                f.write("\n")
            os.replace(temporary, note)
        except BaseException:
            # Whole or not at all: a half-written note is not left behind
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        if machine and self.is_users_own():
            self._remove_old_note(lockfile)

    def is_users_own(self) -> bool:
        """Whether this is this user's own store: a folder under ``~/.chartbook``, as the default store is.

        There, a note from before notes named their machine can only be this
        machine's: ``~/.chartbook`` is never to be shared or synced.
        """
        from chartbook.config import get_global_config_dir

        try:
            home = Path(os.path.realpath(get_global_config_dir()))
        except (RuntimeError, KeyError, OSError):
            return False  # no home folder
        return Path(os.path.realpath(self.root)).is_relative_to(home)

    def _remove_old_note(self, lockfile: Union[str, Path]) -> bool:
        """Remove the note of a lockfile from before notes named their machine; True if there was one."""
        try:
            (self.root / ROOTS_DIR / root_name(lockfile)).unlink()
        except FileNotFoundError:
            return False
        except OSError:
            return False  # left for `store gc`, which removes it once this machine has a note of the lockfile
        return True

    def root_of(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> Optional[Root]:
        """This machine's note of a lockfile (or *machine*'s), if the store has one it can read."""
        return _read_note(self._root_file(lockfile, this_machine(create=False) if machine is None else machine))

    def remove_root(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> bool:
        """Forget a lockfile on this machine. Its objects are then kept by nothing.

        :param machine: ``""`` for the note from before notes named their
            machine; this machine's by default, and, in this user's own
            store, where it can only be this machine's, the note from
            before as well.
        :returns: True if the store had a note of it.
        """
        old = machine is None and self.is_users_own() and self._remove_old_note(lockfile)
        note = self._root_file(lockfile, this_machine(create=False) if machine is None else machine)
        if not note.is_file():
            return old
        note.unlink()
        return True

    def _root_file(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> Path:
        """Where the store notes one lockfile of a machine; this machine's by default."""
        return self.root / ROOTS_DIR / root_name(lockfile, this_machine() if machine is None else machine)

    def roots(self) -> list[Root]:
        """Every lockfile the store has a note of, on every machine, by path.

        A sync service's copy of a note, a ``.json`` file in ``roots/`` under
        another name than a note's, is read too (:attr:`Root.copy`): it may
        hold what the note held before the conflict, and a note only ever
        adds to what is kept.

        :raises StoreError: If a note, or a copy of one, cannot be read,
            naming the file. Nothing should be removed from a store that
            cannot say what it is keeping.
        """
        self._check_layout()
        directory = self.root / ROOTS_DIR
        if not directory.is_dir():
            return []
        found = []
        for note in sorted(directory.glob("*.json")):
            try:
                with open(note, encoding="utf-8") as f:
                    found.append(read_root(json.load(f), note.name))
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise StoreError(
                    f"Cannot read {self._shown(note)}: {unreadable_detail(note, error)}.{_unreadable_note_remedy(note.name, error)}"
                ) from None
        return sorted(found, key=lambda root: (str(root.lockfile), root.machine, root.note))

    def _shown(self, path: Path) -> str:
        """A file of the store, as a message names it: under the store as :meth:`__str__` shows it, which carries no password."""
        try:
            return f"{self}/{path.relative_to(self.root).as_posix()}"
        except ValueError:
            return str(path)

    def lacks(self, content_hash: str, names: Iterable[str], single: bool = True) -> bool:
        """Whether the object of one file lacks it under this name: a put of the same bytes adds a name to such an object only, never a file to a directory's (:meth:`_move_into_place`)."""
        names = list(names)
        if not single or len(names) != 1:
            return False
        parts = plain_parts(names[0])
        path = self.object_path(content_hash)
        if parts is None or len(parts) != 1 or not path.is_dir() or path.is_symlink():
            return False
        if not os.access(path, os.W_OK):
            return False  # a name it could not add: a store this user cannot write
        return not os.path.lexists(on_disk(path, parts))

    def incomplete(
        self, content_hash: str, size_bytes: Optional[int], files: Optional[dict] = None, every: bool = False
    ) -> Optional[str]:
        """Why an object is not whole as its record has it, by the names and sizes of its files; None if it is.

        A folder that a sync service keeps can have an object's files before
        their bytes, or some of its files before the rest, or a copy of one
        of them the service made. The sizes are compared with the record's,
        which reads nothing.
        """
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
            return None
        # An object is named by its content and does not change: one found
        # whole as a record has it is not looked at again in this process
        seen = (str(self.root), content_hash, size_bytes, tuple(sorted((files or {}).items())), every)
        if seen in _found_whole:
            return None
        path = self.object_path(content_hash)
        if not path.is_dir() or path.is_symlink():
            return None  # not there at all, which `has` says; or a link, which `get` refuses
        wrong = unsynced_part(path, size_bytes, files, every, content_hash)
        if wrong is None:
            _found_whole.add(seen)
            return None
        what, waiting = wrong
        if not waiting:
            return f"its object in the store at {self} {what}; `chartbook store verify` checks the rest"
        return (
            f"its object in the store at {self} {what}: it is not fully synced yet. Wait for "
            f"the sync to finish, and run this again (if it stays so, `chartbook store verify` says more)"
        )

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
        """How many seconds ago an object was put in the store.

        :raises ObjectNotFoundError: If the store has no such object: one
            removed since it was listed, by another ``gc`` or a ``put``
            replacing it.
        """
        # A sync service may give a file the time it had on the machine it
        # came from; when it came to this one is its status change (its
        # creation, on Windows), so an object that arrived just now, whose
        # record may not have, is not taken for an old one
        try:
            held = self.object_path(content_hash).stat()
        except FileNotFoundError:
            raise ObjectNotFoundError(f"The store at {self} has no object {content_hash}.") from None
        stored_at = max(held.st_mtime, held.st_ctime)
        return (time.time() if now is None else now) - stored_at

    def delete(self, content_hash: str) -> bool:
        """Remove the object with this hash.

        Only the store's own names are removed. A file that an object was
        hard-linked or symlinked to is untouched.

        :returns: True if there was one to remove.
        :raises StoreError: If it could not be removed, naming it and what
            to do: in a store users share, another user's object is in a
            folder of theirs this user may not write.
        """
        path = self.object_path(content_hash)
        if not path.is_dir():
            return False
        try:
            _remove_tree(path)
        except OSError as error:
            raise StoreError(
                f"Cannot remove the object {content_hash} at {self._shown(path)}: {error.strerror or error}. "
                f"{self._not_this_users_remedy()}"
            ) from None
        try:
            path.parent.rmdir()  # the two-character folder, if now empty
        except OSError:
            pass
        return True

    @staticmethod
    def _not_this_users_remedy() -> str:
        """What to do about a file of the store this user may not remove."""
        return (
            "It is another user's, most likely, in a store users share: its owner removes it (`chartbook store gc` "
            "there, or by hand), or gives you write permission on it and on the folder holding it, and you run "
            "`chartbook store gc` again."
        )

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
            message = what_is_wrong(content_hash, path)
            if message is not None:
                problems.append(StoreProblem(content_hash, path, message))
        return problems


def what_is_wrong(content_hash: str, path: Path) -> Optional[str]:
    """What is wrong with one object, laid out as a folder; None if nothing is.

    *path* is the object's folder, with its files under their own names,
    in any store that keeps or caches objects on a disk.
    """
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


#: The entry-point group a kind of store is found in, by its URL's scheme.
STORE_PLUGIN_GROUP = "chartbook.stores"


def store_for_url(url: str) -> Store:
    """The store a URL names: a folder, or a kind a plugin provides.

    A bare path or ``file:///`` is a :class:`FolderStore`. Another scheme is
    looked up in the entry-point group ``chartbook.stores``: an entry named
    by the scheme, whose value is a class taking the URL.

    :raises ValueError: If the URL names a kind of store nothing provides;
        the message names the scheme.
    """
    from chartbook.config import folder_of_store_url, shown_store_url, store_kind

    kind = store_kind(url)
    if kind == "folder":
        return FolderStore(folder_of_store_url(url))
    plugin = _plugin_store_class(kind)
    if plugin is None:
        raise ValueError(
            f"The store {shown_store_url(url)!r} is a {kind}:// store, and nothing provides one: only a folder "
            f"store is built in, and no installed package has a `{STORE_PLUGIN_GROUP}` entry "
            f"point named {kind!r}. An S3 bucket, s3://bucket/prefix, is a store ChartBook brings, "
            f"with `pip install chartbook[s3]`; see the design page on stores and backends for the rest."
        )
    return plugin(url)


@functools.lru_cache(maxsize=None)
def _plugin_store_class(kind: str):
    """The class a plugin provides for a kind of store, or None.

    Looked up once per process: the entry points are read from installed
    packages, which do not change while ChartBook runs. The first entry
    with the name wins; a package that installs two is its own problem.

    :raises ValueError: If the plugin is there and cannot be loaded, naming it.
    """
    from importlib.metadata import entry_points

    for entry in entry_points(group=STORE_PLUGIN_GROUP):
        if entry.name == kind:
            try:
                return entry.load()
            except Exception as error:  # noqa: BLE001 - whatever the plugin's import raised
                raise ValueError(
                    f"The store plugin {entry.value!r} for {kind}:// stores cannot be loaded: {error}"
                ) from None
    return None


def default_store() -> Store:
    """The store this machine's ChartBook uses.

    ``CHARTBOOK_STORE`` if it is set; otherwise ``[store] url`` in the
    user's ``~/.chartbook/settings.toml``, then in the organization's
    settings file; otherwise ``~/.chartbook/store``. A folder, or a kind a
    plugin provides; see :func:`chartbook.config.get_store_url`.
    """
    from chartbook.config import get_store_url

    return store_for_url(get_store_url())
