"""The store: where the snapshots of pipelines are kept, each file once.

A pipeline's data is read by other pipelines from the store, never from
its folder. What a pipeline has built is put there by ``chartbook
snapshot``, and what a pin takes from another repository by ``chartbook
pin``. The store's layout is made to be read by a person as well::

    ~/.chartbook/store/
      store.json                                which layout this is
      pipelines/
        ftsfr+fed_yield_curve/                  one folder per pipeline (pipeline_folder)
          2026-10-12T091500Z_4f2a91c0e1b2/      a snapshot: when it was made _ its commit
            _data/treasury_rates.parquet        the pipeline's files, in their own places
            _chartbook/snapshot.json            the record, and the dictionary of every file
          2026-10-26T182205Z_9b1e22d7a0c4/      a later one: only what is new or changed
        +unowned/7f3a9c…/rates.parquet          an object no pipeline owns
      origins/                                  the folders snapshots were made from
      roots/                                    the lockfiles that pin what is here
      tmp/                                      what is being written

**Each file is kept once in its pipeline's folder**, usually in the first
snapshot that had it. A snapshot's folder may hold only what is new or changed,
and its record says, for every file of every asset, its hash, its size and
the snapshot that keeps it (``kept_in``). The record is written last, so
a folder without one is never taken for a snapshot, and nothing in the
store is moved or rewritten once written: only ``store gc`` removes. That
is what makes a store in a synced folder, a bucket, and a pipeline's folder
copied by hand into another store safe. The design is
``docs_src/design/plan-0.3.0.md``.

An asset is still named by its content hash (:mod:`chartbook.hashing`):
one file's, or the hash of the listing of its files. A reader asks for it
by that hash (:meth:`Store.files`) and is handed its files, each by its
path inside the asset (``year=2024/part-0.parquet``) and where the store
keeps it, which may be another snapshot's folder.
Readers take the list: polars and DuckDB read a list of files, Hive keys
included. Nothing gathers a version into one folder on each machine; the
one folder a version is laid out in is one a command was asked for
(``store export``, ``restore``, a catalog's rendering).

What a store is, whatever holds it, is :class:`Store`. The folder store,
:class:`FolderStore`, is the one every install has::

    from chartbook.store import FolderStore

    store = FolderStore("~/.chartbook/store")
    pending = store.begin("ftsfr/fed_yield_curve", commit, made_at, base=pipeline_folder)
    stored = pending.put(pipeline_folder / "_data/treasury_rates.parquet")
    pending.write(record)                                  # the snapshot, last
    store.files(stored.content_hash)                       # its files, where they are kept

Another kind, an object store or a database, is a plugin: a class that
provides the same methods, found by the scheme of the store's URL in the
entry-point group ``chartbook.stores`` (:func:`store_for_url`). The store
is a setting of the machine, never of a pipeline; see
:func:`chartbook.config.get_store_url`.

**The declared file never moves.** A snapshot's file is the store's own
bytes: a copy-on-write clone where the disk allows (``reflink``: APFS,
btrfs, XFS), else a copy, so nothing outside the store can change it.
:meth:`Store.verify` hashes every file again and reports each that is no
longer what its record says.

Pinning leaves a note of each lockfile under ``roots/`` so that clearing
the store out never removes another project's pins.

**A store in a synced folder.** A folder that a sync service (Google
Drive, Dropbox, OneDrive) keeps in step between machines is a store they
share, and the service leaves two marks of its own in it. A file can be
there before all of its bytes are: a record says how many each file has,
and :meth:`Store.incomplete` compares the sizes on disk with it, which
costs no read. And a file changed in two places at once is kept twice, the
second under a name of the service's (``snapshot (1).json``): a record is
read under its own name only, so such a copy is passed over; a copy of a
note of a lockfile is read (:attr:`Root.copy`), as a note only ever adds
to what is kept.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import dataclasses
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
SCHEMA = "chartbook/store/v2"

#: The layout of a store made by ChartBook 0.2: objects named by their hash,
#: records by their commit. ``chartbook store migrate`` moves one to this.
V1_SCHEMA = "chartbook/store/v1"

#: The file at the store's root that says which layout it has.
MARKER_FILE = "store.json"

#: Where the pipelines are, under the root: one folder each (:func:`pipeline_folder`).
PIPELINES_DIR = "pipelines"

#: The folder, among the pipelines', of objects no pipeline owns: one put
#: with no snapshot to put it in, or one ``store migrate`` found no owner
#: for. No ID has a ``+`` of its own, so no pipeline's folder has this name.
UNOWNED_DIR = "+unowned"

#: The one name in a snapshot's folder that is ChartBook's own.
OWN_DIR = "_chartbook"

#: A snapshot's record, its dictionary, in its folder's ``_chartbook/``.
RECORD_FILE = "snapshot.json"

#: What a snapshot's ``_chartbook/`` holds once ``store gc`` has cleared it
#: and files later snapshots use are left in its folder.
CLEARED_FILE = "CLEARED.txt"

#: Where a table or a query written out as parquet is, in a snapshot's folder.
TABLES_DIR = "_chartbook/tables"

#: Where the store notes the folders each pipeline's snapshots were made from.
ORIGINS_DIR = "origins"

#: Where a file is written before it is moved into place, and where a
#: snapshot being made notes the files of earlier ones it uses.
TMP_DIR = "tmp"

#: The journal of ``chartbook store migrate``, under :data:`TMP_DIR`: while it is there, the move has not finished.
MIGRATE_JOURNAL = "migrate.jsonl"

#: Where the store remembers which lockfiles name its objects, so that
#: removing what nothing needs never removes another project's pins.
ROOTS_DIR = "roots"

#: Where ChartBook 0.4 gathered, in this machine's cache, assets whose files
#: are kept in more than one snapshot's folder. 0.5 reads files where they
#: are kept; the folder is removed when it is found (``chartbook.cli``).
OLD_VIEWS_DIR = "views"

#: The marker ``chartbook.cli`` leaves in the cache once the folder above has been removed.
OLD_VIEWS_REMOVED = ".views-removed"

#: The note left in each pipeline's folder of a folder store, for a person who finds the folder: what a
#: snapshot's folder holds, and that ``store gc`` is how to remove snapshots. Written once, never rewritten.
README_FILE = "README.txt"

README_TEXT = """This folder holds the snapshots of one pipeline, kept by ChartBook.

Each snapshot is a folder named by when it was made and the commit it was made at, and a
complete record of that version: _chartbook/snapshot.json lists every file of every asset,
with its hash and the folder that keeps it.

A file is kept once, usually in the first snapshot that had it. So a snapshot's folder may hold
only what is new or changed (a "shared" snapshot), and the rest of its files sit in other
snapshots' folders of this pipeline. A snapshot whose folder holds every file of its version is
"standalone". `chartbook store ls` says which each is.

Do not delete a snapshot's folder by hand: another snapshot may keep files in it, and would
lose them. `chartbook store gc` removes snapshots safely, keeping every file a remaining
snapshot uses. `chartbook store export PIPELINE --latest --to FOLDER` writes one complete,
standalone copy of the newest version wherever you say.
"""


def write_readme(pipeline_path: Path) -> None:
    """Leave :data:`README_FILE` in a pipeline's folder if there is none; nothing in the store is ever rewritten."""
    note = pipeline_path / README_FILE
    if note.exists() or os.path.lexists(note):
        return
    try:
        with open(note, "x", encoding="utf-8", newline="\n") as f:
            f.write(README_TEXT)
    except OSError:
        pass  # a store read-only for this user, or a race with another writer: the note is a courtesy

#: How long a note of a snapshot being made keeps the files it uses from
#: ``store gc``, in seconds; a snapshot's folder with no record is left as
#: long, as one being made.
PENDING_SECONDS = 3600

#: The folders of a store laid out as ChartBook 0.2 laid one out, which
#: ``store migrate`` reads: ``objects/<algorithm>/<2 hex>/<rest>``.
OBJECTS_DIR = "objects"

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


class TidyError(StoreError):
    """Raised by :meth:`Store.tidy` when some of what no snapshot uses could not be removed: the rest was.

    Attributes:
        removed: What was removed, each as its name in the store and its size.
        failed: What was not, each as its name in the store and why, with what to do.
    """

    def __init__(self, message: str, removed: list, failed: list):
        super().__init__(message)
        self.removed = removed
        self.failed = failed


class PathTooLongError(StoreError):
    """Raised on Windows, before anything is written, when a path the store would write is longer than Windows takes (#136)."""


#: Windows' limit on a path's length, unless long paths are turned on (MAX_PATH).
WINDOWS_PATH_LIMIT = 260

#: Windows' limit on a folder's path when it is made: MAX_PATH less room for a file's 8.3 name.
WINDOWS_FOLDER_LIMIT = 248

#: Whether this is Windows, where a path has a limit; a test of another system sets it.
_ON_WINDOWS = os.name == "nt"


@functools.lru_cache(maxsize=None)
def long_paths_enabled() -> bool:
    """Whether this machine takes a path past Windows' limit: any but Windows, or Windows with ``LongPathsEnabled``.

    Python itself is long-path aware, so on Windows the setting alone decides.
    """
    if not _ON_WINDOWS:
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (OSError, ImportError):
        return False


#: How to lift Windows' limit, or keep under it: said wherever a path is too long.
LONG_PATHS_REMEDY = (
    "Either turn long paths on (an administrator sets LongPathsEnabled to 1 under "
    "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem, or turns on \"Enable Win32 long paths\" in Group "
    "Policy), or use a store in a shorter folder ([store] url in your settings, or CHARTBOOK_STORE)"
)


def too_long(path: Union[str, Path], folder: bool = False) -> Optional[str]:
    """Why a path cannot be written or read on this machine, in a sentence; None when it can.

    Windows refuses a path of :data:`WINDOWS_PATH_LIMIT` characters or more,
    and a folder of :data:`WINDOWS_FOLDER_LIMIT` or more, unless long paths
    are turned on, and says only "No such file or directory" (#136). A path
    in the ``\\\\?\\`` form has no limit.

    :param folder: Whether *path* is a folder to be made.
    """
    text = str(path)
    limit = WINDOWS_FOLDER_LIMIT if folder else WINDOWS_PATH_LIMIT
    if not _ON_WINDOWS or len(text) < limit or text.startswith("\\\\?\\") or long_paths_enabled():
        return None
    return (
        f"{text} is {len(text)} characters long, and Windows refuses {'a folder' if folder else 'a path'} of {limit} "
        f"or more unless long paths are turned on, which they are not on this machine. {LONG_PATHS_REMEDY}."
    )


def _check_length(path: Union[str, Path], folder: bool = False) -> None:
    why = too_long(path, folder)
    if why is not None:
        raise PathTooLongError(why)
    if not folder:
        _check_length(Path(path).parent, folder=True)


def _exists(path: Union[str, Path]) -> bool:
    """Whether a file is there, asked in the form Windows takes whatever its length: a file another machine wrote may be past this one's limit."""
    text = str(path)
    if _ON_WINDOWS and len(text) >= WINDOWS_FOLDER_LIMIT and not text.startswith("\\\\?\\"):
        absolute = os.path.abspath(text)
        text = "\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute
    return os.path.lexists(text)


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
        stored: For an asset a snapshot holds, where its files are, as its
            record keeps it: ``{"at": …, "files": [{"path", "content_hash",
            "size_bytes", "kept_in"}, …]}``, and ``"single": true`` for one
            file. None for an object no pipeline owns.
    """

    content_hash: str
    size_bytes: int
    path: Path
    files: tuple[str, ...]
    links: tuple[str, ...] = ()
    created: bool = True
    entries: tuple[hashing.FileEntry, ...] = ()
    stored: Optional[dict] = None

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


def _read_marker(marker: Path):
    """The layout a store's marker names.

    On Windows a file another thread or process is replacing cannot be
    opened for a moment (it is "delete pending"): it is tried again for a
    second before that is said.
    """
    for attempt in range(20):
        try:
            with open(marker, encoding="utf-8") as f:
                return json.load(f).get("schema")
        except PermissionError:
            if os.name != "nt" or attempt == 19:
                raise
            time.sleep(0.05)


def link_target(path) -> str:
    """Where a symlink points, as a path is written: on Windows without the ``\\\\?\\`` that ``os.readlink`` may give."""
    target = os.readlink(path)
    if os.name == "nt" and target.startswith("\\\\?\\UNC\\"):
        return "\\\\" + target[8:]  # \\?\UNC\server\share is \\server\share
    if os.name == "nt" and target.startswith("\\\\?\\"):
        target = target[4:]
    return target


def _make_removable(path: str, own: bool = False) -> None:
    """Give back the permissions that removing *path* needs, to the store only.

    Removal can fail on a read-only file (Windows) or in a read-only
    directory. The directory holding *path* is the store's, and so is a
    file that is a clone or a copy. A symlink, or a hard link in an object
    put by one, leads to a file that is not the store's, and its
    permissions are never touched: unless the caller says the files are
    ChartBook's *own* (a snapshot's, the cache's, a view's), whose second
    names are ChartBook's too.
    """
    os.chmod(os.path.dirname(path), stat.S_IRWXU)
    if os.path.islink(path):
        return
    if os.path.isdir(path):
        os.chmod(path, stat.S_IRWXU)
    elif own or os.lstat(path).st_nlink == 1:
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


def _remove_file(path: Path) -> None:
    """Remove one file of the store, read-only or not: it and the folder holding it are the store's.

    Permissions are touched only when the removal is refused without them,
    and the folder's are given back after, so that what stays beside it is
    still read by whoever shares the store.

    :raises OSError: What the system said, when it cannot be: another
        user's file, in a store users share.
    """
    try:
        os.remove(path)
        return
    except PermissionError:
        pass
    folder = os.path.dirname(path)
    mode = stat.S_IMODE(os.stat(folder).st_mode)
    os.chmod(folder, mode | stat.S_IRWXU)
    try:
        if not os.path.islink(path):
            os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
        os.remove(path)
    finally:
        try:
            os.chmod(folder, mode)
        except OSError:
            pass


def _remove_tree(directory: Path, own: bool = False) -> None:
    """Remove a directory and what is in it, read-only files included.

    :raises OSError: What the system said of the first file or folder that
        could not be removed, once given the permissions removing it needs:
        another user's folder in a store users share, whose permissions
        are not this user's to give.
    """

    def retry_writable(function, path, error):
        try:
            _make_removable(path, own)
        except OSError:
            # Not this user's to make removable: what the removal itself
            # said is the plainer error (``onerror`` hands the exc_info tuple)
            raise (error[1] if isinstance(error, tuple) else error) from None
        function(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(directory, onexc=retry_writable)
    else:
        shutil.rmtree(directory, onerror=retry_writable)


#: Where a store of ChartBook 0.2 kept snapshot records: ``snapshots/<commit>/<name>/<time>.json``.
SNAPSHOTS_DIR = "snapshots"
#: The file beside a pipeline's records, in a store of ChartBook 0.2, that notes the folders they were made from.
ORIGINS_FILE = "origins"
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
#: A record's name in a store of ChartBook 0.2: when it was made, ``20261013T182205.123456Z``, and a count if two share that time.
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

    The snapshots of pipelines, each in its pipeline's folder with a record
    of every file it holds; assets named by their content hash; and the
    lockfiles (roots) that keep them. A kind of store provides these
    methods and nothing else is asked of it. :class:`FolderStore` is the
    one every install has; :class:`chartbook.stores.s3.S3Store` is a
    bucket, behind ``pip install chartbook[s3]``.
    """

    @abc.abstractmethod
    def begin(
        self, pipeline: str, commit: str, made_at: str, base: Optional[Union[str, Path]] = None, made_by: str = "snapshot"
    ) -> "PendingSnapshot":
        """Begin a snapshot of a pipeline at a commit, to put its assets in and then write (:class:`PendingSnapshot`).

        :param pipeline: The pipeline's ID, whose folder it goes in.
        :param commit: The commit, in full.
        :param made_at: When it was made, as a record has it.
        :param base: The pipeline's own folder, from which an asset's place
            in it is worked out.
        :param made_by: ``snapshot`` for one the pipeline's owner makes;
            ``pin`` for one a pin makes from a clone of its repository.
        :raises ValueError: If the ID, the commit or the time is not one.
        """

    @abc.abstractmethod
    def put(self, path: Union[str, Path], links: Iterable[str] = LINKS) -> "StoredObject":
        """Store what a declared ``path`` names as an object no pipeline owns, and return its hash."""

    @abc.abstractmethod
    def has(self, content_hash: str, pipeline: Optional[str] = None) -> bool:
        """Whether the store holds an asset with this hash."""

    @abc.abstractmethod
    def files(self, content_hash: str, pipeline: Optional[str] = None, name: Optional[str] = None) -> "KeptFiles":
        """The files of the asset with this hash, each by its path inside the asset and where the store keeps it.

        A reader reads the files where they are: a list of files to polars
        or DuckDB, Hive keys included. Nothing is copied or gathered.

        :param pipeline: The pipeline it is of, whose snapshots are looked in first.
        :param name: For an asset that is one file, the name it is read by:
            the same bytes may be two assets', each under its own name, and
            kept once.
        :raises ObjectNotFoundError: If the store has no such asset.
        :raises StoreError: If a file of it is missing, not synced yet, or
            leads out of the store.
        """

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
        """Every snapshot record in the store that an owner made, as files to read."""

    def pinned_snapshot_files(self) -> list[Path]:
        """Every snapshot record in the store that a pin made from a clone, as files to read."""
        return []

    def snapshot_commit_prefixes(self) -> set[str]:
        """The first 12 hex digits of the commit of every snapshot an owner made, a record that cannot be read among them: its folder's name says."""
        return {commit[:12] for commit in self.snapshot_commits()}

    def write_snapshot(self, commit: str, name: str, stamp: str, document: dict) -> Path:
        """Write one record that holds no files of its own, whole or not at all, and return its file.

        What its assets name is found by their hashes elsewhere in the
        store. A snapshot with files is written by :meth:`begin`.
        """
        return self.begin(document["root"], commit, document["made_at"], made_by=document.get("made_by", "snapshot")).write(document)

    @abc.abstractmethod
    def remove_snapshot(self, path: Path) -> bool:
        """Clear one snapshot: its record, and the files no other snapshot uses; True if it was there."""

    def held_hashes(self) -> set[str]:
        """The hash of every asset a snapshot's record says where the files of are: what goes with snapshots, not by its hash."""
        return set()

    def files_of(self, content_hash: str) -> list[tuple[str, int]]:
        """Where the store keeps an asset's files, each as a name for it in the store and its size; empty for an object no pipeline owns."""
        return []

    def listing(self, content_hash: str, single: bool) -> Optional[tuple[hashing.FileEntry, ...]]:
        """Each file of an asset, by its path in the asset, with its size and hash, as a snapshot's record gives them.

        Nothing is read but the records, whose files' hashes make the
        asset's (:func:`read_kept_record`). None when no record says: an
        object no pipeline owns, or a store that keeps no records.

        :param single: Whether the asset is one file. The hash of one file
            and the hash of a listing of several are written alike, and a
            file can hold the very listing of others (a ``SHA256SUMS`` beside
            them), so only a hold of the shape asked for is taken.
        """
        return None

    def tidy(self, dry_run: bool = False, keep: Iterable[str] = ()) -> list[tuple[str, int]]:
        """Remove what no snapshot uses (a snapshot begun and never written, a sync service's copies); what was removed, or with *dry_run* would be, each with its size.

        :param keep: Names in the store not to remove.
        """
        return []

    def tidy_pipeline(self, pipeline: str, dry_run: bool = False) -> list[tuple[str, int]]:
        """Remove what no snapshot uses from one pipeline's folder, as :meth:`tidy` does from every one; what was removed, or with *dry_run* would be, each with its size.

        For what clears a pipeline's snapshots and not the store's, such as
        ``store move``: the files of the snapshots it cleared go, and no
        other pipeline's folder is looked in.
        """
        return []

    def delete_unowned(self, content_hash: str) -> bool:
        """Remove the object no pipeline owns with this hash, and nothing a snapshot's record names; True if there was one."""
        return self.delete(content_hash)

    @contextlib.contextmanager
    def reading(self):
        """A block in which the store may go by the records as it first read them: for what asks it many times at once."""
        yield self

    @abc.abstractmethod
    def note_origin(self, commit: str, name: str, top: str) -> None:
        """Note, beside a pipeline's records at a commit, the repository folder they came from."""

    @abc.abstractmethod
    def origins(self, commit: str, name: str) -> list[str]:
        """The repository folders a pipeline's records at a commit were made from, as noted."""

    def __str__(self) -> str:
        return repr(self)


class PendingSnapshot(abc.ABC):
    """A snapshot being written: its files go into its own folder, and its record last.

    Got from :meth:`Store.begin`. Each :meth:`put` stores one asset, each
    file kept once in its pipeline's folder: a file an earlier snapshot of
    the pipeline already keeps is used where it is, and only a new one is
    copied, into this snapshot's folder at its path in the pipeline.
    :meth:`write` writes the record, ``_chartbook/snapshot.json``, last, so
    that a folder without one is never taken for a snapshot. :meth:`discard`
    lets go of a snapshot that is not to be written.
    """

    #: Whether a file has been written into this snapshot's own folder: a
    #: snapshot that has is to be written, or its files are lost.
    placed: bool = False

    @abc.abstractmethod
    def put(self, path: Union[str, Path], place: Optional[str] = None, links: Iterable[str] = ("reflink", "copy")) -> "StoredObject":
        """Store what a declared ``path`` names, at *place* in the pipeline's folder, and return it with its hash.

        :param place: Where the asset is in the pipeline's folder, with
            ``/`` between parts: a file's own path, or the folder its files
            are listed from (a directory, or a glob's fixed prefix; ``""``
            for the top). By default, worked out from the pipeline's
            folder the pending snapshot was begun with.
        """

    @abc.abstractmethod
    def write(self, document: dict) -> Path:
        """Write the snapshot's record, whole or not at all, and return its file."""

    @abc.abstractmethod
    def discard(self) -> None:
        """Let go of a snapshot that is not to be written: what was copied into its folder goes."""


@dataclass(frozen=True)
class KeptFile:
    """One file of an asset, as a snapshot's dictionary has it.

    Attributes:
        relative: Its path inside the asset, as the asset is hashed.
        path: Its path in the pipeline's folder.
        size_bytes: Its size.
        content_hash: Its hash.
        location: Where the store keeps it.
    """

    relative: str
    path: str
    size_bytes: int
    content_hash: str
    location: Path


@dataclass(frozen=True)
class KeptAsset:
    """An asset as one snapshot's record holds it: where each of its files is kept.

    Attributes:
        content_hash: The asset's hash.
        record: The record that names it.
        at: Where the asset is in the pipeline's folder: the file's folder,
            or the folder its files are listed from.
        single: Whether it is one file, read by its name.
        files: Its files.
    """

    content_hash: str
    record: "KeptRecord"
    at: str
    single: bool
    files: tuple[KeptFile, ...]


@dataclass(frozen=True)
class KeptFiles:
    """An asset's files, as a store hands them to a reader (:meth:`Store.files`).

    Attributes:
        content_hash: The asset's hash.
        single: Whether the asset is one file, read by its name.
        files: Its files, sorted by their path inside the asset. Each is
            where the store keeps it, which in a shared snapshot may be an
            earlier snapshot's folder than the asset's own (``kept_in``).
        home: The folder the asset is listed from, in the snapshot that
            recorded it: where it is whole when every file of it sits in
            that snapshot. It need not exist, and a reader reads *files*,
            never the folder.
    """

    content_hash: str
    single: bool
    files: tuple[KeptFile, ...]
    home: Path

    @property
    def one(self) -> KeptFile:
        """The file of an asset that is one file.

        :raises StoreError: If the asset is several files.
        """
        if len(self.files) != 1:
            raise StoreError(f"{self.content_hash} is {len(self.files)} files, not one.")
        return self.files[0]

    def by_relative(self) -> dict[str, Path]:
        """Where each file is, by its path inside the asset."""
        return {file.relative: file.location for file in self.files}

    def in_place(self) -> bool:
        """Whether every file sits under *home* at its path inside the asset: the asset is whole in one folder."""
        return all(file.location == self.home.joinpath(*file.relative.split("/")) for file in self.files)


@dataclass(frozen=True)
class KeptRecord:
    """What the store reads of one snapshot's record: who made it, and what it holds where.

    Attributes:
        path: The record's file, ``<snapshot folder>/_chartbook/snapshot.json``.
        pipeline: The pipeline it is of, by its ID; empty if it cannot be read.
        commit: Its commit; empty if it cannot be read.
        subdirectory: The pipeline's folder in its repository.
        made_at: When it was made.
        made_by: ``snapshot`` for one its pipeline's owner made; ``pin`` for
            one a pin made from a clone of the pipeline's repository.
        assets: What it holds, each asset with where its files are.
        named: Every content hash it names, held here or not.
        readable: Whether it could be read; one that cannot is still a
            snapshot, for the layers above to report.
        stamp: Its file's time and size, which say whether it has changed.
        whole: Whether every part with a dictionary is one this machine
            follows. One that is not (a name another system takes and this
            one does not, a record written by hand) keeps ``store gc`` from
            removing anything in its pipeline's folder.
        mentioned: Every file its dictionary names, followed or not, by its
            path: what ``store gc`` never removes while it is there.
    """

    path: Path
    pipeline: str = ""
    commit: str = ""
    subdirectory: str = ""
    made_at: str = ""
    made_by: str = "snapshot"
    assets: tuple[KeptAsset, ...] = ()
    named: frozenset = frozenset()
    readable: bool = True
    stamp: tuple = ()
    whole: bool = True
    mentioned: frozenset = frozenset()

    @property
    def folder(self) -> Path:
        """The snapshot's folder."""
        return self.path.parent.parent


#: Each record read, by its file, with the time and size it had then: a record is never rewritten, so one read is enough.
_read_records: dict = {}


def _record_stamp(path: Path) -> Optional[tuple]:
    try:
        seen = os.stat(path)
    except OSError:
        return None
    return (seen.st_mtime_ns, seen.st_size, seen.st_ino)


def _kept_files(stored: object, pipeline_folder: Path, own: str) -> Optional[tuple[str, bool, tuple[KeptFile, ...]]]:
    """Where an asset's files are, from its ``stored`` in a record; None if it says nothing a store could follow.

    A record may come from anyone who can write to a store, and each of its
    paths becomes a path in it: only plain relative paths are followed, and
    a folder named as a snapshot's is.
    """
    if not isinstance(stored, dict) or not isinstance(stored.get("files"), list):
        return None
    at = stored.get("at", "")
    if not isinstance(at, str) or (at and plain_parts(at) is None):
        return None
    single = stored.get("single") is True
    files = []
    for entry in stored["files"]:
        if not isinstance(entry, dict):
            return None
        path, size, content_hash = entry.get("path"), entry.get("size_bytes"), entry.get("content_hash")
        kept_in, kept_as = entry.get("kept_in", own), entry.get("kept_as", path)
        if not all(isinstance(value, str) for value in (path, content_hash, kept_in, kept_as)):
            return None
        if not isinstance(size, int) or isinstance(size, bool) or not is_snapshot_folder(kept_in):
            return None
        parts, kept_parts = plain_parts(path), plain_parts(kept_as)
        if parts is None or kept_parts is None:
            return None
        relative = path[len(at) + 1:] if at else path
        if at and not path.startswith(at + "/"):
            return None
        try:
            _split_hash(content_hash)
        except ValueError:
            return None
        files.append(KeptFile(relative, path, size, content_hash, pipeline_folder.joinpath(kept_in, *kept_parts)))
    if not files or (single and len(files) != 1):
        return None
    return at, single, tuple(files)


def kept_listing(asset: "KeptAsset") -> tuple[hashing.FileEntry, ...]:
    """An asset's files as a record holds them, each by its path in the asset, sorted as a hash lists them."""
    return tuple(
        sorted((hashing.FileEntry(f.relative, f.size_bytes, f.content_hash) for f in asset.files), key=lambda e: e.path)
    )


def _makes(single: bool, files: tuple) -> str:
    """The hash an asset's files make, from their hashes as a record gives them: one file's, or their listing's."""
    if single:
        return files[0].content_hash
    return hashing.hash_listing(hashing.FileEntry(f.relative, f.size_bytes, f.content_hash) for f in files).content_hash


def _mentioned(stored: object, pipeline_folder: Path, own: str) -> set[str]:
    """Every file a part's dictionary names, as a path, whether this machine follows it or not.

    A name another system takes (a ``:`` on Windows) is still a file that
    machine's snapshot holds, which nothing here may remove.
    """
    found: set[str] = set()
    if not isinstance(stored, dict) or not isinstance(stored.get("files"), list):
        return found
    for entry in stored["files"]:
        if not isinstance(entry, dict):
            continue
        kept_in, kept_as = entry.get("kept_in", own), entry.get("kept_as", entry.get("path"))
        if not isinstance(kept_in, str) or not is_snapshot_folder(kept_in) or not isinstance(kept_as, str):
            continue
        parts = kept_as.split("/")
        if any(part in ("", ".", "..") or "\0" in part for part in parts):
            continue
        found.add(str(pipeline_folder.joinpath(kept_in, *parts)))
    return found


def read_kept_record(path: Path) -> KeptRecord:
    """What the store reads of one snapshot's record (:class:`KeptRecord`), once while it is unchanged."""
    stamp = _record_stamp(path)
    known = _read_records.get(str(path))
    if known is not None and known.stamp == stamp:
        return known
    folder = path.parent.parent
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
        if document.get("schema") not in ("chartbook/snapshot/v1", "chartbook/snapshot/v2"):
            raise ValueError("a record of another version")  # its dictionary is not this version's to follow
        code = document["code"]
        commit = code["commit"]
        if not isinstance(commit, str) or not _FULL_COMMIT.match(commit):
            raise ValueError("no commit")
        pipeline = document["root"]
        made_at = document["made_at"]
        subdirectory = code.get("subdirectory", "")
        if not all(isinstance(value, str) for value in (pipeline, made_at, subdirectory)):
            raise ValueError("not a record")
        made_by = document.get("made_by", "snapshot")
        parts = []
        for record in document.get("records") or []:
            if isinstance(record, dict):
                parts.append(record)
        for name in ("index", "documents"):
            if isinstance(document.get(name), dict):
                parts.append(document[name])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        found = KeptRecord(path, readable=False, stamp=stamp or ())
        _read_records[str(path)] = found
        return found
    assets, named, mentioned, whole = [], set(), set(), True
    for part in parts:
        content_hash = part.get("content_hash")
        if not isinstance(content_hash, str):
            continue
        try:
            _split_hash(content_hash)
        except ValueError:
            continue
        named.add(content_hash)
        if part.get("stored") is None:
            continue
        mentioned |= _mentioned(part.get("stored"), folder.parent, folder.name)
        kept = _kept_files(part.get("stored"), folder.parent, folder.name)
        if kept is not None and _makes(kept[1], kept[2]) == content_hash:
            # Only files whose hashes make the asset's: a record may be anyone's, and a
            # dictionary of other files under a hash would hand a reader other bytes
            at, single, files = kept
            assets.append((content_hash, at, single, files))
        else:
            whole = False
    found = KeptRecord(
        path, pipeline, commit, subdirectory, made_at, made_by if made_by in ("snapshot", "pin") else "snapshot",
        named=frozenset(named), stamp=stamp or (), whole=whole, mentioned=frozenset(mentioned),
    )
    found = dataclasses.replace(
        found, assets=tuple(KeptAsset(content_hash, found, at, single, files) for content_hash, at, single, files in assets)
    )
    _read_records[str(path)] = found
    return found


class FolderStore(Store):
    """A store in a directory on this machine.

    :param root: The store's directory. It need not exist: it is made when
        something is first put in it.
    """

    def __init__(self, root: Union[str, Path]):
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self._layout_checked = False
        self._memo: Optional[tuple] = None
        self._reading = 0

    def __repr__(self) -> str:
        return f"FolderStore({str(self)!r})"

    def __str__(self) -> str:
        from chartbook.config import shown_store_url

        return shown_store_url(str(self.root))  # a //host path may carry a password

    # The pipelines and their snapshots

    def pipeline_path(self, pipeline: str) -> Path:
        """The folder of one pipeline's snapshots."""
        return self.root / PIPELINES_DIR / pipeline_folder(pipeline)

    def records(self) -> list[KeptRecord]:
        """Every snapshot's record in the store, made by an owner or by a pin, oldest folder first in each pipeline.

        A record whose pipeline is not its folder's, or whose commit is not
        its folder's, is one that cannot be read: a folder is named for
        people, and a record in another pipeline's folder is not that
        pipeline's, nor is it read as its own.
        """
        self._check_layout()
        if self._memo is not None and self._reading:
            return list(self._memo[1])
        pipelines = self.root / PIPELINES_DIR
        try:
            folders = sorted(os.listdir(pipelines))
        except (FileNotFoundError, NotADirectoryError):
            return []
        found = []
        for name in folders:
            if name == UNOWNED_DIR:
                continue
            try:
                snapshots = sorted(n for n in os.listdir(pipelines / name) if is_snapshot_folder(n))
            except (NotADirectoryError, FileNotFoundError):
                continue
            for snapshot_name in snapshots:
                path = pipelines / name / snapshot_name / OWN_DIR / RECORD_FILE
                if not os.path.isfile(path):
                    continue  # being made, or cleared
                kept = read_kept_record(path)
                if kept.readable and (pipeline_folder(kept.pipeline) != name or not snapshot_name.endswith("_" + kept.commit[:12])):
                    # In another pipeline's folder, or another commit's: not read, and said so where it is met
                    kept = KeptRecord(path, readable=False, stamp=kept.stamp)
                found.append(kept)
        index: dict = {}
        for record in found:
            if record.readable:
                for asset in record.assets:
                    index.setdefault(asset.content_hash, []).append(asset)
        self._memo = (time.monotonic(), found, index)
        return list(found)

    def records_in(self, pipeline_path: Path) -> list[KeptRecord]:
        """The records in one pipeline's folder, read as they are now, as :meth:`records` reads them."""
        name = pipeline_path.name
        try:
            snapshots = sorted(n for n in os.listdir(pipeline_path) if is_snapshot_folder(n))
        except (FileNotFoundError, NotADirectoryError):
            return []
        found = []
        for snapshot_name in snapshots:
            path = pipeline_path / snapshot_name / OWN_DIR / RECORD_FILE
            if not os.path.isfile(path):
                continue
            kept = read_kept_record(path)
            if kept.readable and (pipeline_folder(kept.pipeline) != name or not snapshot_name.endswith("_" + kept.commit[:12])):
                kept = KeptRecord(path, readable=False, stamp=kept.stamp)
            found.append(kept)
        return found

    def _forget(self) -> None:
        """Read the records again next time: this process has just written or removed one."""
        self._memo = None

    @contextlib.contextmanager
    def reading(self):
        """Go by the records as they were first read, until the block ends, but for what this store writes meanwhile.

        For what asks the store many times over at once, ``store gc``'s plan:
        outside such a block every question reads the records as they are.
        """
        if not self._reading:
            self._memo = None  # what was read before the block may be old by now
        self._reading += 1
        try:
            yield self
        finally:
            self._reading -= 1
            if not self._reading:
                self._memo = None

    def _held(self, content_hash: str, pipeline: Optional[str] = None) -> list[KeptAsset]:
        """Every record's hold of an asset, newest first; *pipeline*'s first."""
        self.records()
        held = list(self._memo[2].get(content_hash, ())) if self._memo is not None else []
        held.sort(key=lambda asset: (asset.record.pipeline == pipeline, asset.record.made_at), reverse=True)
        return held

    def unowned_path(self, content_hash: str) -> Path:
        """Where an object no pipeline owns is, or would be: ``pipelines/+unowned/<hex>``.

        :raises ValueError: If *content_hash* is not a content hash.
        """
        _, digest = _split_hash(content_hash)
        return self.root / PIPELINES_DIR / UNOWNED_DIR / digest

    def object_path(self, content_hash: str) -> Path:
        """Where an object no pipeline owns is, or would be (:meth:`unowned_path`)."""
        return self.unowned_path(content_hash)

    def snapshot_commits(self) -> set[str]:
        return {record.commit for record in self.records() if record.readable and record.made_by == "snapshot"}

    def snapshot_commit_prefixes(self) -> set[str]:
        return {
            record.folder.name.rpartition("_")[2] for record in self.records()
            if not record.readable or record.made_by == "snapshot"
        }

    def snapshot_files(self, commit: str, name: str) -> list[Path]:
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        from chartbook.snapshot import record_name

        return sorted(
            record.path for record in self.records()
            if record.folder.name.endswith("_" + commit[:12])
            and (not record.readable or (record.made_by == "snapshot" and record.commit == commit and record_name(record.subdirectory) == name))
        )

    def all_snapshot_files(self) -> list[Path]:
        return sorted(record.path for record in self.records() if not record.readable or record.made_by == "snapshot")

    def pinned_snapshot_files(self) -> list[Path]:
        return sorted(record.path for record in self.records() if record.readable and record.made_by == "pin")

    def begin(
        self, pipeline: str, commit: str, made_at: str, base: Optional[Union[str, Path]] = None, made_by: str = "snapshot"
    ) -> "PendingSnapshot":
        self._check_layout(create=True)
        self._forget()
        return _FolderPending(self, pipeline, commit, made_at, base, made_by)

    def remove_snapshot(self, path: Path) -> bool:
        """Clear one snapshot: its record goes, and ``_chartbook/CLEARED.txt`` says so.

        Its files go with :meth:`tidy`, but those a later snapshot uses,
        which stay where they are in this one's folder, so no other record
        goes out of date; the folder goes once nothing in it is used.

        :raises StoreError: If it could not be removed, naming it and what
            to do (see :meth:`delete`).
        """
        path = Path(path)
        if not path.is_file():
            return False
        folder = path.parent.parent
        self._forget()
        pipelines = Path(os.path.realpath(self.root / PIPELINES_DIR))
        if folder.is_symlink() or folder.parent.is_symlink() or not Path(os.path.realpath(path)).is_relative_to(pipelines):
            raise StoreError(
                f"The snapshot record {self._shown(path)} is in a folder that is a link to another place: it is not "
                f"cleared from this store. Clear it where its folder is."
            )
        kept = read_kept_record(path)
        try:
            path.unlink()
        except OSError as error:
            raise StoreError(
                f"Cannot remove the snapshot record {self._shown(path)}: {error.strerror or error}. "
                f"{self._not_this_users_remedy()}"
            ) from None
        _read_records.pop(str(path), None)
        try:
            (path.parent / CLEARED_FILE).write_text(
                f"Cleared by `chartbook store gc` on {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC.\n"
                f"The files left in this folder are used by later snapshots of the same pipeline,\n"
                f"whose _chartbook/snapshot.json says so; the folder goes once none is.\n",
                encoding="utf-8",
                newline="\n",
            )
        except OSError:
            pass
        if kept.readable and kept.made_by == "snapshot":
            from chartbook.snapshot import record_name

            name = record_name(kept.subdirectory)
            if not self.snapshot_files(kept.commit, name):
                # The last of this pipeline at this commit: its note of origins goes too
                try:
                    self.origins_file(kept.commit, name).unlink()
                    self.origins_file(kept.commit, name).parent.rmdir()
                except OSError:
                    pass
        return True

    def _notes(self) -> tuple[set, set]:
        """What the notes of snapshots being made keep, while each is younger than :data:`PENDING_SECONDS`: their own folders, and the files of earlier ones they use."""
        folders: set = set()
        files: set = set()
        tmp = self.root / TMP_DIR
        now = time.time()
        for note in tmp.glob("*" + PENDING_SUFFIX) if tmp.is_dir() else ():
            try:
                if now - note.stat().st_mtime > PENDING_FOLDER_SECONDS:
                    continue
                for line in note.read_text(encoding="utf-8").splitlines():
                    if line.startswith(FOLDER_MARK):
                        folders.add(str(self.root / line[len(FOLDER_MARK):]))
                    elif line:
                        files.add(str(self.root / line))
            except OSError:
                continue
        return folders, files

    def sweep(
        self,
        pipeline_path: Path,
        older_than: float = PENDING_SECONDS,
        only: Optional[str] = None,
        keep: Iterable[str] = (),
        dry_run: bool = False,
    ) -> tuple[list[tuple[Path, int]], list[tuple[Path, str]]]:
        """Remove what no snapshot of a pipeline uses from its folder.

        A file is used when a record in the pipeline's folder names it,
        followed by this machine or not, or a snapshot being made has noted
        it (for :data:`PENDING_SECONDS`), or it is one of *keep* (names in the
        store). Files are told apart by what the disk says they are, not by
        how their names are written, so a name a sync wrote in another of
        Unicode's forms, or another letter case, is the file its record
        names. What is not used goes:

        - from a snapshot's folder that has no record, one begun and never
          written, once nothing in it has changed for
          :data:`PENDING_FOLDER_SECONDS` and no snapshot being made has noted
          it; at once if ``store gc`` cleared it;
        - from one that has a record, once the file is *older_than* that
          many seconds: a sync service's copy (``snapshot (1).json``,
          ``part-0 (1).parquet``), which no reader reads.

        Nothing is removed from a pipeline's folder while one of its records
        cannot be read, or names files this machine cannot follow. The notes
        are read again just before anything goes, for a snapshot that began
        meanwhile. Each file is removed by itself, and a folder left empty goes.

        :param only: The one snapshot's folder to look in; every one by default.
        :param dry_run: Say what would be removed, and remove nothing.
        :returns: What was removed (or would be), each with its size; and what
            could not be, each with why.
        """
        if pipeline_path.is_symlink():
            return [], []  # another place's snapshots, shared by a link: cleared there
        # The notes first, then the records as they are now: a snapshot that is written between the
        # two is in the records, and one that is still being made is in the notes
        folders, noted = self._notes()
        self._forget()
        here = [record for record in self.records() if record.path.parent.parent.parent == pipeline_path]
        doubt = next((record for record in here if not record.readable or not record.whole), None)
        if doubt is not None:
            import warnings

            warnings.warn(
                f"Nothing in {self._shown(pipeline_path)} is removed: its record {self._shown(doubt.path)} cannot be "
                f"read, or names files this machine does not follow (a sync that has not finished, or names another "
                f"system takes and this one does not). `chartbook store verify` says more.",
                stacklevel=2,
            )
            return [], []
        used = {path for record in here for path in record.mentioned}
        used |= noted | {str(self.root / name) for name in keep}
        used_ids = {identity for identity in map(_identity, used) if identity is not None}
        # As a disk that tells neither letter case nor Unicode's two forms apart reads them: another
        # machine syncing this store may have one, where these names are the same file
        used_folded = {_folded(path) for path in used}
        now = time.time()
        found: list = []
        try:
            names = sorted(os.listdir(pipeline_path))
        except (FileNotFoundError, NotADirectoryError):
            return [], []
        for name in names:
            folder = pipeline_path / name
            if (only is not None and name != only) or not is_snapshot_folder(name):
                continue
            if not folder.is_dir() or folder.is_symlink():
                continue
            recorded = (folder / OWN_DIR / RECORD_FILE).is_file()
            cleared = (folder / OWN_DIR / CLEARED_FILE).is_file()
            if not recorded and not cleared:
                if str(folder) in folders or (older_than and now - _newest_in(folder) < PENDING_FOLDER_SECONDS):
                    continue  # a snapshot being made, most likely
            own = {folder / OWN_DIR / RECORD_FILE, folder / OWN_DIR / CLEARED_FILE}
            for directory, _, files in os.walk(folder):
                for file_name in files:
                    file = Path(directory) / file_name
                    if file in own or str(file) in used or _identity(file) in used_ids or _folded(str(file)) in used_folded:
                        continue
                    try:
                        seen = file.lstat()
                    except OSError:
                        continue
                    if recorded and older_than and now - max(seen.st_mtime, seen.st_ctime) < older_than:
                        continue  # beside a snapshot's files: a copy of a sync's, an hour on
                    found.append((file, seen.st_size, folder))
        # A snapshot that began meanwhile may have noted one of these: the notes once more
        folders, noted = self._notes()
        noted_ids = {identity for identity in map(_identity, noted) if identity is not None}
        found = [
            (file, size, folder) for file, size, folder in found
            if str(folder) not in folders and str(file) not in noted and _identity(file) not in noted_ids
        ]
        if dry_run:
            return [(file, size) for file, size, _ in found], []
        removed: list = []
        failed: list = []
        for file, size, _ in found:
            try:
                _remove_file(file)
            except OSError as error:
                if os.path.lexists(file):
                    failed.append((file, error.strerror or str(error)))
                continue
            removed.append((file, size))
        # Folders this emptied, whose times say only that: not a snapshot's just made
        emptied = {str(file.parent) for file, _ in removed}
        for name in names:
            folder = pipeline_path / name
            if (only is not None and name != only) or not is_snapshot_folder(name) or not folder.is_dir() or folder.is_symlink():
                continue
            cleared = folder / OWN_DIR / CLEARED_FILE
            if cleared.is_file() and not (folder / OWN_DIR / RECORD_FILE).is_file() and not any(
                Path(directory) / file_name != cleared for directory, _, files in os.walk(folder) for file_name in files
            ):
                try:
                    _remove_file(cleared)
                    emptied.add(str(cleared.parent))
                except OSError:
                    pass
            for directory, _, _ in sorted(os.walk(folder), key=lambda walked: -len(walked[0])):
                try:
                    if directory not in emptied and older_than and now - os.stat(directory).st_mtime < older_than:
                        continue  # made just now: a snapshot about to write into it
                    os.rmdir(directory)
                    emptied.add(os.path.dirname(directory))
                except OSError:
                    pass
        if not dry_run and not any(
            is_snapshot_folder(name) and (pipeline_path / name / OWN_DIR / RECORD_FILE).is_file()
            for name in (os.listdir(pipeline_path) if pipeline_path.is_dir() else [])
        ):
            # The last snapshot gone, the note for a person who finds the folder goes with it
            note = pipeline_path / README_FILE
            try:
                if note.is_file() and not note.is_symlink():
                    _remove_file(note)
            except OSError:
                pass
        try:
            if not older_than or now - os.stat(pipeline_path).st_mtime >= older_than:
                pipeline_path.rmdir()
        except OSError:
            pass
        self._forget()
        return removed, failed

    def note_origin(self, commit: str, name: str, top: str) -> None:
        note = self.origins_file(commit, name)
        _check_length(note)
        note.parent.mkdir(parents=True, exist_ok=True)
        try:
            known = note.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            known = []
        if top not in known:
            with open(note, "a", encoding="utf-8", newline="\n") as f:
                f.write(top + "\n")

    def origins(self, commit: str, name: str) -> list[str]:
        try:
            return [line for line in self.origins_file(commit, name).read_text(encoding="utf-8").splitlines() if line]
        except FileNotFoundError:
            return []

    def origins_file(self, commit: str, name: str) -> Path:
        """Where the store notes the repository folders a pipeline's snapshots at a commit were made from."""
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self.root / ORIGINS_DIR / commit / f"{name}.txt"

    # Assets, by their hash

    def has(self, content_hash: str, pipeline: Optional[str] = None) -> bool:
        """Whether the store holds an asset with this hash: a snapshot's record says where, or no pipeline owns it.

        :raises StoreError: If the store has a layout this version does not
            read, as :meth:`get` does: what it holds cannot be said.
        """
        self._check_layout()
        # As an object of ChartBook 0.2 was there once its folder was: an
        # asset is once any of its files is, and one with only some of them
        # is not whole yet (:meth:`incomplete`), a sync to wait for. One none
        # of whose files is there is not in the store, as an object whose
        # folder had not come yet was not, and the message says a sync may
        # explain it
        held = self._held(content_hash, pipeline)
        return any(_exists(file.location) for asset in held for file in asset.files) or (
            self.unowned_path(content_hash).is_dir()
        )

    def files(self, content_hash: str, pipeline: Optional[str] = None, name: Optional[str] = None) -> KeptFiles:
        """The asset with this hash as its files, each where the store keeps it (:meth:`Store.files`).

        A file of a later snapshot that an earlier one keeps is read in the
        earlier one's folder: nothing is copied or gathered. They are there
        to be read, not written.

        :param pipeline: The pipeline the asset is of, whose snapshots are
            looked in first.
        :param name: For an asset that is one file, the name it is read by:
            the same bytes may be two assets', each under its own name, and
            kept once.
        :raises ObjectNotFoundError: If the store has no such asset.
        :raises StoreError: If a file of it is missing, not synced yet, or
            leads out of the store: a store a team shares holds what anyone
            put there, and a reader must not be handed a file of its own.
        """
        self._check_layout()
        held = _of_shape(self._held(content_hash, pipeline), single=bool(name))
        if name:
            # The one under that name first; another's bytes under that name else
            held.sort(key=lambda asset: not (asset.single and asset.files[0].relative == name))
            held = [
                asset if not asset.single or asset.files[0].relative == name
                else dataclasses.replace(asset, files=(dataclasses.replace(asset.files[0], relative=name),))
                for asset in held
            ]
        missing = None
        pipelines = Path(os.path.realpath(self.root / PIPELINES_DIR))
        checked: dict = {}
        for asset in held:
            # A link first, there or not: what it leads to is never read, nor taken for a sync to wait for
            for file in asset.files:
                if _is_or_under_a_link(file.location, self.root / PIPELINES_DIR, checked) or not Path(os.path.realpath(file.location)).is_relative_to(pipelines):
                    raise StoreError(
                        f"The file {file.path} of {content_hash} in the store at {self} is a link, or leads out of the "
                        f"store, or is under a link; it is not read. `chartbook store verify` checks a store."
                    )
            for file in asset.files:
                _check_length(file.location)  # written by a machine that takes longer paths than this one
            missing = _unsynced_file(asset)
            if missing is not None:
                continue  # the one `incomplete` judges whole is the one read
            return handed(asset)
        if missing is not None and not self.unowned_path(content_hash).is_dir():
            raise StoreError(
                f"The store at {self} {missing} of {content_hash}, though a snapshot's record names it: it is not "
                f"fully synced yet, most likely. Wait for the sync to finish, and run this again (if it stays so, "
                f"`chartbook store verify` says more)."
            )
        path = self.unowned_path(content_hash)
        if not path.is_dir():
            raise ObjectNotFoundError(f"The store at {self} has no object {content_hash}.")
        unowned = Path(os.path.realpath(self.root / PIPELINES_DIR / UNOWNED_DIR))
        if path.is_symlink() or not Path(os.path.realpath(path)).is_relative_to(unowned):
            raise StoreError(
                f"The object {content_hash} in the store at {self} is a link, or leads out of "
                f"the store; it is not read. `chartbook store verify` checks a store."
            )
        return unowned_files(content_hash, path, name)

    def put(self, path: Union[str, Path], links: Iterable[str] = LINKS) -> StoredObject:
        """Store what a declared ``path`` names as an object no pipeline owns, and return its hash.

        What a snapshot holds is put by :meth:`begin` instead, into the
        pipeline's folder. An object put here is in
        ``pipelines/+unowned/<hex>/``, its files under their own names, until
        ``store gc`` finds nothing names it.

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
        # The longest it could be, before anything is written: under its hash, its own names
        root_of_files = os.path.abspath(found.root)
        for file in found.files:
            relative = os.path.relpath(os.path.abspath(file), root_of_files)
            _check_length(self.unowned_path(hashing.format_hash("0" * 64)) / (
                declared_name(relative) or relative if found.single else relative
            ))
        staging = self.root / TMP_DIR / uuid.uuid4().hex[:12]
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
            final = self.unowned_path(content.content_hash)
            for file in hashing.directory_files(staging):
                _check_length(final / file.relative_to(staging))
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

    def layout(self) -> Optional[str]:
        """The layout the store's marker names; None if it has none yet."""
        try:
            return _read_marker(self.root / MARKER_FILE)
        except FileNotFoundError:
            return None

    def _check_layout(self, create: bool = False) -> None:
        """Check that the store on disk has the layout this class reads.

        A store says which layout it has in :data:`MARKER_FILE`. One made by
        another ChartBook, laid out differently, is refused instead of
        being misread: one of 0.2 is moved to this layout by ``chartbook
        store migrate``.

        :param create: If True, a store that does not exist yet is made.
        :raises StoreError: If the layout is not this one.
        """
        if self._layout_checked:
            return
        marker = self.root / MARKER_FILE
        try:
            schema = _read_marker(marker)
        except FileNotFoundError:
            if not create:
                return  # nothing here yet; nothing to misread
            if holds_v1(self.root):
                raise StoreError(
                    f"The store at {self} has no store.json, and holds the folders of a store of ChartBook 0.2 "
                    f"(objects/, snapshots/): its store.json has not arrived (a sync that has not finished), or was "
                    f"removed. Nothing is written to it. Wait for the sync; if store.json is gone, run `chartbook "
                    f"store migrate` once every machine that uses it has ChartBook 0.3."
                )
            self.root.mkdir(parents=True, exist_ok=True)
            # Written whole or not at all, for another process reading it
            temporary = marker.with_name(f"{MARKER_FILE}.{uuid.uuid4().hex[:12]}.tmp")
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"schema": SCHEMA}, f)
                f.write("\n")
            try:
                os.replace(temporary, marker)
            except PermissionError:
                # Windows does not replace a file that another thread or
                # process has open: another made it first, and is reading it
                try:
                    os.remove(temporary)
                except OSError:
                    pass
                if not marker.is_file():
                    raise
                return self._check_layout()
            self._layout_checked = True
            return
        except (OSError, ValueError, AttributeError) as error:
            raise StoreError(f"Cannot read {self._shown(marker)}: {unreadable_detail(marker, error)}") from None
        if schema == V1_SCHEMA:
            raise StoreError(
                f"The store at {self} has the layout of ChartBook 0.2 ({V1_SCHEMA!r}), and this version reads "
                f"{SCHEMA!r}. Once every machine that uses this store has ChartBook 0.3, run `chartbook store "
                f"migrate` on one of them; until then, use ChartBook 0.2 with it."
            )
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
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
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
        """Whether an object no pipeline owns, of one file, lacks it under this name: a put of the same bytes adds a name to such an object only (:meth:`_move_into_place`).

        What a snapshot holds lacks nothing: its record names each file.
        """
        names = list(names)
        if not single or len(names) != 1:
            return False
        parts = plain_parts(names[0])
        path = self.unowned_path(content_hash)
        if parts is None or len(parts) != 1 or not path.is_dir() or path.is_symlink():
            return False
        if not os.access(path, os.W_OK):
            return False  # a name it could not add: a store this user cannot write
        return not os.path.lexists(on_disk(path, parts))

    def incomplete(
        self, content_hash: str, size_bytes: Optional[int], files: Optional[dict] = None, every: bool = False
    ) -> Optional[str]:
        """Why an asset is not whole as its record has it, by the sizes of its files; None if it is.

        A folder that a sync service keeps can have a snapshot's record before
        its files, or a file before its bytes. Each file's size is in the
        record, and is compared with the file's, which reads nothing. An
        object no pipeline owns is judged as *size_bytes* and *files* say
        (:func:`unsynced_part`).
        """
        # Of the record's shape: one file it is read by, or several (a directory, a glob)
        held = _of_shape(self._held(content_hash), single=bool(files) and len(files) == 1 and not every)
        if held:
            seen = (str(self.root), content_hash, bool(files) and len(files) == 1 and not every)
            if seen in _found_whole:
                return None
            what = None
            for asset in held:
                what = _unsynced_file(asset)
                if what is None:
                    _found_whole.add(seen)
                    return None
            return (
                f"its file in the store at {self} {what}: it is not fully synced yet. Wait for "
                f"the sync to finish, and run this again (if it stays so, `chartbook store verify` says more)"
            )
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
            return None
        # An object is named by its content and does not change: one found
        # whole as a record has it is not looked at again in this process
        seen = (str(self.root), content_hash, size_bytes, tuple(sorted((files or {}).items())), every)
        if seen in _found_whole:
            return None
        path = self.unowned_path(content_hash)
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
        """The total size in bytes of an asset's files; 0 if it has none."""
        held = self._held(content_hash)
        if held:
            return sum(file.size_bytes for file in held[0].files)
        total = 0
        for file in hashing.directory_files(self.unowned_path(content_hash)):
            try:
                total += file.stat().st_size
            except OSError:
                pass  # a link whose file has gone
        return total

    def age_of(self, content_hash: str, now: Optional[float] = None) -> float:
        """How many seconds ago an asset was put in the store: its newest record's, or its object's.

        :raises ObjectNotFoundError: If the store has no such asset: one
            removed since it was listed, by another ``gc``.
        """
        # A sync service may give a file the time it had on the machine it
        # came from; when it came to this one is its status change (its
        # creation, on Windows), so an asset that arrived just now is not
        # taken for an old one
        paths = [asset.record.path for asset in self._held(content_hash)] + [self.unowned_path(content_hash)]
        times = []
        for path in paths:
            try:
                held = path.stat()
            except FileNotFoundError:
                continue
            times.append(max(held.st_mtime, held.st_ctime))
        if not times:
            raise ObjectNotFoundError(f"The store at {self} has no object {content_hash}.")
        return (time.time() if now is None else now) - max(times)

    def delete(self, content_hash: str) -> bool:
        """Remove the asset with this hash: its files, and its object if no pipeline owns it.

        ``store gc`` clears whole snapshots (:meth:`remove_snapshot`); this
        removes one asset's bytes, which its records then name without
        holding, as a store that lost them would. A file another asset has
        too goes with it.

        :returns: True if there was one to remove.
        :raises StoreError: If it could not be removed, naming it and what
            to do: in a store users share, another user's object is in a
            folder of theirs this user may not write.
        """
        removed = False
        pipelines = Path(os.path.realpath(self.root / PIPELINES_DIR))
        for asset in self._held(content_hash):
            for file in asset.files:
                if not os.path.lexists(file.location):
                    continue
                if os.path.islink(file.location) or not Path(os.path.realpath(file.location)).is_relative_to(pipelines):
                    raise StoreError(
                        f"{file.path} of {content_hash} in the store at {self} is a link, or leads out of the store: "
                        f"it is not removed. `chartbook store verify` checks a store."
                    )
                try:
                    _make_removable(str(file.location))
                    os.remove(file.location)
                except OSError as error:
                    raise StoreError(
                        f"Cannot remove {file.path} of {content_hash} at {self._shown(file.location)}: "
                        f"{error.strerror or error}. {self._not_this_users_remedy()}"
                    ) from None
                removed = True
        if removed:
            _found_whole.difference_update({(str(self.root), content_hash, True), (str(self.root), content_hash, False)})
        path = self.unowned_path(content_hash)
        if not path.is_dir():
            return removed
        try:
            _remove_tree(path)
        except OSError as error:
            raise StoreError(
                f"Cannot remove the object {content_hash} at {self._shown(path)}: {error.strerror or error}. "
                f"{self._not_this_users_remedy()}"
            ) from None
        return True

    def delete_unowned(self, content_hash: str) -> bool:
        """Remove the object no pipeline owns with this hash, and nothing a snapshot's record names; True if there was one."""
        path = self.unowned_path(content_hash)
        if not path.is_dir() or path.is_symlink():
            return False
        try:
            _remove_tree(path)
        except OSError as error:
            raise StoreError(
                f"Cannot remove the object {content_hash} at {self._shown(path)}: {error.strerror or error}. "
                f"{self._not_this_users_remedy()}"
            ) from None
        return True

    @staticmethod
    def _not_this_users_remedy() -> str:
        """What to do about a file of the store this user may not remove."""
        return (
            "It is another user's, most likely, in a store users share: its owner removes it (`chartbook store gc` "
            "there, or by hand), or gives you write permission on it and on the folder holding it, and you run "
            "`chartbook store gc` again."
        )

    def held_hashes(self) -> set[str]:
        return {asset.content_hash for record in self.records() if record.readable for asset in record.assets}

    def files_of(self, content_hash: str) -> list[tuple[str, int]]:
        found: dict = {}
        for asset in self._held(content_hash):
            for file in asset.files:
                found.setdefault(file.location.relative_to(self.root).as_posix(), file.size_bytes)
        return sorted(found.items())

    def listing(self, content_hash: str, single: bool) -> Optional[tuple[hashing.FileEntry, ...]]:
        held = [asset for asset in self._held(content_hash) if asset.single == single]
        return kept_listing(held[0]) if held else None

    def tidy(self, dry_run: bool = False, keep: Iterable[str] = ()) -> list[tuple[str, int]]:
        """Remove what no snapshot uses from every pipeline's folder (:meth:`sweep`); what was removed, each with its size.

        :param dry_run: Say what would be removed, and remove nothing.
        :param keep: Names in the store not to remove: what ``store gc``
            spares for being new.
        :raises TidyError: Once the rest is removed, if some of it could not
            be, naming each with what the system said and what to do.
        """
        self._check_migrated()
        if not dry_run:
            self._tidy_tmp()
        try:
            names = sorted(os.listdir(self.root / PIPELINES_DIR))
        except (FileNotFoundError, NotADirectoryError):
            return []
        return self._tidy_folders(names, list(keep), dry_run)

    def tidy_pipeline(self, pipeline: str, dry_run: bool = False) -> list[tuple[str, int]]:
        """Remove what no snapshot uses from one pipeline's folder (:meth:`sweep`); what was removed, each with its size.

        :raises TidyError: As :meth:`tidy` does.
        """
        self._check_migrated()
        return self._tidy_folders([pipeline_folder(pipeline)], [], dry_run)

    def _tidy_folders(self, names: list[str], keep: list[str], dry_run: bool) -> list[tuple[str, int]]:
        """Sweep the pipelines' folders of these names; raise :class:`TidyError` once all are swept, if some of it could not be removed."""
        removed, failed = [], []
        for name in names:
            folder = self.root / PIPELINES_DIR / name
            if name != UNOWNED_DIR and folder.is_dir() and not folder.is_symlink():
                gone, stuck = self.sweep(folder, keep=keep, dry_run=dry_run)
                removed += [(path.relative_to(self.root).as_posix(), size) for path, size in gone]
                failed += [(path.relative_to(self.root).as_posix(), why) for path, why in stuck]
        if failed and not dry_run:
            name, why = failed[0]
            more = f" (and {len(failed) - 1} more)" if len(failed) > 1 else ""
            raise TidyError(
                f"Cannot remove {self}/{name}{more}, which no snapshot uses: {why}. {self._not_this_users_remedy()}",
                removed,
                [(name, f"{why}. {self._not_this_users_remedy()}") for name, why in failed],
            )
        return removed

    def _check_migrated(self) -> None:
        """Refuse to remove anything from a store a migrate has not finished moving: what it moved may have no record yet."""
        if (self.root / TMP_DIR / MIGRATE_JOURNAL).exists() or holds_v1(self.root):
            raise StoreError(
                f"The store at {self} has not finished moving to the layout of ChartBook 0.3: it holds the folders "
                f"of a store of 0.2 (objects/, snapshots/), or the journal of a migrate cut short ({TMP_DIR}/"
                f"{MIGRATE_JOURNAL}). Nothing is removed from it until it has. Run `chartbook store migrate`; if "
                f"another machine moved it, wait for the sync to bring the rest."
            )

    def _tidy_tmp(self) -> None:
        """Remove what a writer that died left under ``tmp/``: its notes, a file half written, a staging folder; two days on."""
        tmp = self.root / TMP_DIR
        now = time.time()
        try:
            entries = list(tmp.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name == MIGRATE_JOURNAL:
                continue  # a migrate's journal, which only a migrate removes
            try:
                # By the later of its times: a clone keeps its source's, and a writer at work touches its note
                seen = entry.lstat()
                if now - max(seen.st_mtime, seen.st_ctime) < 2 * PENDING_FOLDER_SECONDS:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    _remove_tree(entry, own=True)
                else:
                    _remove_file(entry)
            except OSError:
                continue

    def longest_paths(self) -> tuple[int, int]:
        """How long the store's paths are, in characters: the longest of a file it holds, and the longest a new snapshot of one of its pipelines would make.

        A new snapshot's folder is named by the second it is made, so its
        files' paths are the ones the pipeline's last snapshot has, under
        a folder name of the same length.
        """
        longest = made = 0
        for record in self.records():
            for asset in record.assets:
                for file in asset.files:
                    longest = max(longest, len(str(file.location)))
                    made = max(made, len(str(record.folder.joinpath(*file.path.split("/")))))
        return longest, made

    def unowned_hashes(self) -> list[str]:
        """The hash of every object no pipeline owns, in order."""
        self._check_layout()
        try:
            names = sorted(os.listdir(self.root / PIPELINES_DIR / UNOWNED_DIR))
        except (FileNotFoundError, NotADirectoryError):
            return []
        return [hashing.format_hash(name) for name in names if _HEX.match(name) and (self.root / PIPELINES_DIR / UNOWNED_DIR / name).is_dir()]

    def hashes(self) -> Iterator[str]:
        """The hash of every asset in the store, in order: what its records hold, and the objects no pipeline owns."""
        yield from sorted(self.held_hashes() | set(self.unowned_hashes()))

    def verify(
        self, content_hashes: Optional[Iterable[str]] = None
    ) -> list[StoreProblem]:
        """Hash assets again, and report each that is not what its record says.

        This reads every byte. It is how a change made from outside is
        found: a file edited or replaced in the store by hand, one a sync
        cut short, or a record whose files do not make its hash.

        :param content_hashes: The assets to check; every one by default.
        :returns: The problems found; empty when every asset is intact.
        """
        problems = []
        for content_hash in self.hashes() if content_hashes is None else content_hashes:
            held = self._held(content_hash)
            if held:
                message = None
                for asset in held:
                    message = what_is_wrong_with(asset)
                    if message is None:
                        break
                if message is not None:
                    problems.append(StoreProblem(content_hash, held[0].record.folder, message))
                continue
            path = self.unowned_path(content_hash)
            if not path.is_dir():
                problems.append(StoreProblem(content_hash, path, "not in the store"))
                continue
            message = what_is_wrong(content_hash, path)
            if message is not None:
                problems.append(StoreProblem(content_hash, path, message))
        return problems


def _of_shape(held: list, single: bool) -> list:
    """The holds of an asset of the shape asked for, one file or several, where any is; else all, in their order.

    A file's bytes may be another asset's listing (a ``SHA256SUMS`` of a
    folder has that folder's hash): a hold of the other shape is never read
    in place of one of this shape that is there but not whole yet.
    """
    shaped = [asset for asset in held if asset.single == single]
    return shaped or list(held)


def _unsynced_file(asset: KeptAsset) -> Optional[str]:
    """What of an asset's files is not there as its record has it, in a few words; None when all are.

    A file that is a link is no sync's doing, and is not judged here:
    :meth:`FolderStore.get` refuses it, and :meth:`FolderStore.verify` says so.
    """
    pipelines = Path(os.path.realpath(asset.record.folder.parent.parent))
    for file in asset.files:
        if os.path.islink(file.location) or not Path(os.path.realpath(file.location)).is_relative_to(pipelines):
            continue
        try:
            size = os.stat(file.location).st_size
        except OSError:
            return f"does not have {file.path} yet"
        if size != file.size_bytes:
            return f"has {size:,} bytes of {file.path} where its record says {file.size_bytes:,}"
    return None


def what_is_wrong_with(asset: KeptAsset) -> Optional[str]:
    """What is wrong with one asset as a snapshot's record holds it, reading every byte; None if nothing is."""
    cache = hashing.HashCache()  # fresh, so every byte is read
    entries = []
    for file in asset.files:
        if os.path.islink(file.location):
            return f"{file.path} is a link to {link_target(file.location)}, not a file the store keeps"
        try:
            actual = hashing.format_hash(cache.file_hex(file.location))
        except FileNotFoundError:
            return f"{file.path} is not in the store"
        except OSError as error:
            return f"{file.path} cannot be read: {error}"
        if actual != file.content_hash:
            return f"{file.path} is no longer what its record says (now {actual})"
        entries.append(hashing.FileEntry(file.relative, file.size_bytes, file.content_hash))
    made = entries[0].content_hash if asset.single else hashing.hash_listing(entries).content_hash
    if made != asset.content_hash:
        return f"its record's files make {made}, not its hash: the record is not one a store wrote"
    return None


def handed(asset: KeptAsset) -> KeptFiles:
    """An asset as one snapshot's record holds it, as a reader is handed it: its files, sorted, and its home.

    Each file's location is as the disk names it (:func:`on_disk`): a sync
    between systems may hand a name over in the other of Unicode's forms.
    """
    pipeline_folder = asset.record.folder.parent
    files = []
    for file in sorted(asset.files, key=lambda file: file.relative):
        try:
            parts = file.location.relative_to(pipeline_folder).parts
        except ValueError:
            parts = ()
        location = on_disk(pipeline_folder, list(parts)) if parts else file.location
        files.append(file if location == file.location else dataclasses.replace(file, location=location))
    at = plain_parts(asset.at) if asset.at else []
    home = asset.record.folder.joinpath(*at) if at else asset.record.folder
    return KeptFiles(asset.content_hash, asset.single, tuple(files), home)


def unowned_files(content_hash: str, folder: Path, name: Optional[str] = None) -> KeptFiles:
    """The files of an object no pipeline owns, as its folder holds them, under their own names.

    Such an object's record lists no files, so each is read from the disk,
    and its hash is not known without reading it (``content_hash`` is
    empty). With *name*, the one file read by that name; without, every
    file, and the object is one file when the folder holds one.
    """
    found = []
    for file in hashing.directory_files(folder):
        relative = file.relative_to(folder).as_posix()
        try:
            size = os.stat(file).st_size
        except OSError:
            continue
        found.append(KeptFile(relative, relative, size, "", file))
    found.sort(key=lambda file: file.relative)
    if name:
        # By the name asked for, in either of Unicode's forms (a sync between
        # systems may hand a name over in the other); the files as they are if none is
        wanted = unicodedata.normalize("NFC", name)
        named = [file for file in found if unicodedata.normalize("NFC", file.relative) == wanted]
        if named:
            return KeptFiles(content_hash, True, (dataclasses.replace(named[0], relative=name),), folder)
    return KeptFiles(content_hash, len(found) == 1, tuple(found), folder)


def _is_or_under_a_link(location: Path, pipelines: Path, checked: Optional[dict] = None) -> bool:
    """Whether a file of the store is a link, or a folder between ``pipelines/`` and it is one.

    :param checked: Folders already judged, by path, so that a dataset of
        many files in one folder costs one look at the folder.
    """
    try:
        parts = Path(os.path.abspath(location)).relative_to(Path(os.path.abspath(pipelines))).parts
    except ValueError:
        return True
    checked = checked if checked is not None else {}
    current = pipelines
    for part in parts[:-1]:
        current = current / part
        known = checked.get(current)
        if known is None:
            known = checked[current] = os.path.islink(current)
        if known:
            return True
    return os.path.islink(location)


#: The end of a note, under ``tmp/``, of a snapshot being made: its own folder, and the files of earlier ones it uses.
PENDING_SUFFIX = ".pending"

#: How a note names the folder of the snapshot being made, beside the files of earlier ones it uses.
FOLDER_MARK = "folder "

#: How long a snapshot's folder that never got its record is left, nothing in it changing, before
#: ``store gc`` takes it for one given up: a day, for one uploaded slowly through a sync.
PENDING_FOLDER_SECONDS = 86400

def _identity(path) -> Optional[tuple]:
    """What the disk says a file is (its device and number), whatever form of its name it was asked by; None if it is not there."""
    try:
        seen = os.stat(path)
    except (OSError, ValueError):
        return None
    return (seen.st_dev, seen.st_ino)


#: What a desktop leaves in a folder it shows, which is nobody's data (and a sync service may not remove).
_LEFT_BY_A_DESKTOP = frozenset({"desktop.ini", "thumbs.db", "icon\r"})


def _files_in(folder: Path) -> Iterator[str]:
    """The names of the files under a folder, but for what a desktop leaves there (``.DS_Store``, ``desktop.ini``)."""
    for _, _, files in os.walk(folder):
        for name in files:
            if not name.startswith(".") and name.lower() not in _LEFT_BY_A_DESKTOP:
                yield name


def holds_v1(root: Path) -> bool:
    """Whether a folder holds what a store of ChartBook 0.2 held: a file under objects/, or under a commit's folder in snapshots/ other than the one a migrate leaves for 0.2 to refuse.

    A folder a sync left empty, or holding only what a desktop leaves, holds nothing.
    """
    if next(_files_in(root / OBJECTS_DIR), None) is not None:
        return True
    try:
        commits = [entry.path for entry in os.scandir(root / "snapshots") if _FULL_COMMIT.match(entry.name) and entry.name != "0" * 40]
    except OSError:
        return False
    return any(next(_files_in(Path(path)), None) is not None for path in commits)


def _folded(path: str) -> str:
    """A path as a disk that tells neither letter case nor Unicode's two forms apart compares it."""
    return unicodedata.normalize("NFC", path).casefold()


def _newest_in(folder: Path) -> float:
    """When anything in a folder last changed or came, as the disk says."""
    newest = 0.0
    for directory, folders, files in os.walk(folder):
        for name in [*folders, *files]:
            try:
                seen = os.lstat(os.path.join(directory, name))
            except OSError:
                continue
            newest = max(newest, seen.st_mtime, seen.st_ctime)
    try:
        seen = os.lstat(folder)
        newest = max(newest, seen.st_mtime, seen.st_ctime)
    except OSError:
        pass
    return newest


class _FolderPending(PendingSnapshot):
    """A snapshot being written into a folder store (:meth:`FolderStore.begin`)."""

    def __init__(self, store: FolderStore, pipeline: str, commit: str, made_at: str, base, made_by: str):
        from chartbook.identity import validate_pipeline_id

        validate_pipeline_id(pipeline)
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        if made_by not in ("snapshot", "pin"):
            raise ValueError(f"{made_by!r} is not who makes a snapshot: 'snapshot' or 'pin'.")
        snapshot_folder_name(made_at, commit)  # a time a snapshot writes, or ValueError
        self.store = store
        self.pipeline = pipeline
        self.commit = commit
        self.made_at = made_at
        self.made_by = made_by
        self.base = Path(os.path.abspath(base)) if base is not None else None
        self.pipeline_path = store.pipeline_path(pipeline)
        self.name: Optional[str] = None
        self.placed = False
        self._written = False
        self._kept: Optional[dict] = None
        self._here: dict[str, str] = {}
        self._note: Optional[Path] = None
        #: Hashes already known, by the source file's path, which are then not read again
        self.known: dict[str, str] = {}
        self._reused: list = []
        self._taken: list = []

    def _claim(self) -> Path:
        """This snapshot's folder, made the first time it is needed: its time, the next free second if another has it, and its commit."""
        if self.name is None:
            self.pipeline_path.mkdir(parents=True, exist_ok=True)
            for later in range(86400):
                name = snapshot_folder_name(self.made_at, self.commit, later)
                _check_length(self.pipeline_path / name / OWN_DIR / f"{'0' * 12}.tmp")
                # Noted first, so that `store gc` never meets the folder without its note
                self._note_line(FOLDER_MARK + (self.pipeline_path / name).relative_to(self.store.root).as_posix())
                try:
                    os.mkdir(self.pipeline_path / name)
                except FileExistsError:
                    continue
                self.name = name
                break
            else:
                raise StoreError(f"No folder is free for a snapshot of {self.pipeline} in the store at {self.store}.")
        return self.pipeline_path / self.name

    def _kept_files(self) -> dict:
        """Every file the pipeline's snapshots keep, by its hash."""
        if self._kept is None:
            self._kept = {}
            for record in self.store.records():
                if record.readable and record.folder.parent == self.pipeline_path:
                    for asset in record.assets:
                        for file in asset.files:
                            self._kept.setdefault(file.content_hash, []).append(file)
        return self._kept

    def _note_line(self, line: str) -> None:
        if self._note is None:
            tmp = self.store.root / TMP_DIR
            tmp.mkdir(parents=True, exist_ok=True)
            self._note = tmp / f"{uuid.uuid4().hex[:12]}{PENDING_SUFFIX}"
        with open(self._note, "a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    def _note_use(self, location: Path) -> None:
        """Note, before it is used, a file of an earlier snapshot that this one uses, so that ``store gc`` keeps it meanwhile."""
        self._note_line(location.relative_to(self.store.root).as_posix())

    def _alive(self) -> None:
        """Say, by the note's time, that this snapshot is still being made: a slow one is not taken for one given up."""
        if self._note is not None:
            try:
                os.utime(self._note, None)
            except OSError:
                pass

    def _confirm(self, links: tuple = ("reflink", "copy")) -> None:
        """See that each file of an earlier snapshot this one has taken is still named by a record, now that its use is noted.

        Done once, before the record is written, from this pipeline's
        records alone. The entries are the ones in the record about to be
        written, so a file written here instead is written there too.

        ``store gc`` clears a snapshot's record before it removes the files
        no record names, and keeps what a note names: one cleared before the
        note was read may lose its files, so a file whose record has gone is
        written into this snapshot's own folder instead.
        """
        taken = [(entry, source) for entry, source in self._taken if entry.get("kept_in") != self.name]
        if not taken:
            return
        named = set()
        for record in self.store.records_in(self.pipeline_path):
            if record.readable:
                named |= record.mentioned
        for entry, source in taken:
            location = self.pipeline_path.joinpath(entry["kept_in"], *entry.get("kept_as", entry["path"]).split("/"))
            if str(location) in named:
                continue
            target = self._claim().joinpath(*entry["path"].split("/"))
            if os.path.lexists(target):
                continue  # this snapshot has it already, under this path
            written, _ = self._write_file(source, target, links, expect=entry["content_hash"])
            if written != entry["content_hash"]:
                raise StoreError(f"{source} changed while a snapshot of {self.pipeline} was made: make it again.")
            self.placed = True
            self._here.setdefault(written, entry["path"])
            self._reused = [reuse for reuse in self._reused if reuse[0] != location]
            entry.update(kept_in=self.name)
            entry.pop("kept_as", None)

    def _refill(self) -> None:
        """Put back a file of an earlier snapshot this one uses, if it went while this one was made (a ``store gc`` elsewhere)."""
        for location, source, content_hash in self._reused:
            if os.path.lexists(location):
                continue
            if not os.path.isfile(source):
                raise StoreError(
                    f"{location} went from the store while a snapshot of {self.pipeline} was made, which uses it, and "
                    f"{source} is no longer there to put it back from. Make the snapshot again."
                )
            written, _ = self._write_file(source, location, ("reflink", "copy"), expect=content_hash)
            if written != content_hash:
                raise StoreError(f"{source} changed while a snapshot of {self.pipeline} was made: make it again.")

    def _drop_note(self) -> None:
        if self._note is not None:
            try:
                self._note.unlink()
            except OSError:
                pass
            self._note = None

    def _write_file(self, source: str, target: Path, links: tuple, expect: Optional[str] = None) -> tuple[str, str]:
        """Write one file into the store at *target*, its own bytes, and return its hash and how it was made.

        :param expect: The hash the file must have to go at *target* (a file
            a record names, put back): bytes that are not it are not written
            there, and the hash returned says so.
        """
        _check_length(target)
        self._inside(target)
        tmp = self.store.root / TMP_DIR
        tmp.mkdir(parents=True, exist_ok=True)
        temporary = tmp / f"{uuid.uuid4().hex[:12]}.part"
        try:
            kind = _link(source, str(temporary), links)
            content_hash = hashing.format_hash(hashing._file_hex(temporary))
            if expect is not None and content_hash != expect:
                return content_hash, kind
            for attempt in range(3):
                target.parent.mkdir(parents=True, exist_ok=True)
                self._inside(target)
                if os.path.lexists(target):
                    if expect is not None and _hash_once(target) == content_hash:
                        return content_hash, kind  # put back by another snapshot at the same time
                    raise StoreError(f"{target} is in the store already, with other bytes than {source}.")
                try:
                    os.rename(temporary, target)
                    break
                except FileNotFoundError:
                    if attempt == 2 or not os.path.exists(temporary):
                        raise  # the folder went again and again (a `store gc` elsewhere): said as it is
            self.store._forget()
        finally:
            if os.path.lexists(temporary):
                _remove_file(temporary)  # read-only already, which Windows will not remove as it is
        return content_hash, kind

    def _inside(self, target: Path) -> None:
        """Refuse to write where a link leads: a record or a folder of the store may be anyone's."""
        pipelines = Path(os.path.realpath(self.store.root / PIPELINES_DIR))
        if os.path.islink(target) or not Path(os.path.realpath(target.parent)).is_relative_to(pipelines):
            raise StoreError(
                f"{target} is a link, or under one that leads out of the store: nothing is written there. "
                f"`chartbook store verify` checks a store."
            )

    def _keep(self, source: str, path: str, links: tuple, used: set) -> dict:
        """Keep one file at *path* in the pipeline, once: where an earlier snapshot keeps it, or new in this one's folder."""
        self._alive()
        content_hash = self.known.get(source) or hashing.format_hash(hashing._file_hex(Path(source)))
        size = os.stat(source).st_size
        if content_hash in self._here:
            kept_as = self._here[content_hash]
            entry = {"path": path, "content_hash": content_hash, "size_bytes": size, "kept_in": self.name}
            if kept_as != path:
                entry["kept_as"] = kept_as
            return entry
        holes = []
        for file in self._kept_files().get(content_hash, []):
            if file.size_bytes != size:
                continue
            self._note_use(file.location)
            if os.path.islink(file.location):
                continue
            try:
                there = os.stat(file.location).st_size
            except FileNotFoundError:
                holes.append(file)
                continue
            if there == size:
                self._reused.append((file.location, source, content_hash))
                entry = self._entry(path, content_hash, size, file.location)
                self._taken.append((entry, source))
                return entry
        for file in holes:
            # A file a record names that is missing (removed by hand, or lost
            # to a sync): put back where the record says, so that it is whole again
            folder = self.pipeline_path / file.location.relative_to(self.pipeline_path).parts[0]
            if not (folder / OWN_DIR / RECORD_FILE).is_file():
                continue
            written, kind = self._write_file(source, file.location, links, expect=content_hash)
            if written == content_hash:
                used.add(kind)
                self._reused.append((file.location, source, content_hash))
                entry = self._entry(path, content_hash, size, file.location)
                self._taken.append((entry, source))
                return entry
            content_hash = written  # the bytes changed since they were hashed: new, in this snapshot's folder
        target = self._claim().joinpath(*path.split("/"))
        written, kind = self._write_file(source, target, links)
        used.add(kind)
        self.placed = True
        self._here.setdefault(written, path)
        return {"path": path, "content_hash": written, "size_bytes": os.stat(target).st_size, "kept_in": self.name}

    def _entry(self, path: str, content_hash: str, size: int, location: Path) -> dict:
        kept_in, *kept_as = location.relative_to(self.pipeline_path).parts
        entry = {"path": path, "content_hash": content_hash, "size_bytes": size, "kept_in": kept_in}
        if "/".join(kept_as) != path:
            entry["kept_as"] = "/".join(kept_as)
        return entry

    def put(self, path: Union[str, Path], place: Optional[str] = None, links: Iterable[str] = ("reflink", "copy")) -> StoredObject:
        if self._written:
            raise StoreError("This snapshot is written; nothing more goes into it.")
        # The store keeps only its own bytes: a clone or a copy, never a link to a file outside it
        links = tuple(kind for kind in links if kind in FROZEN_LINKS) or ("copy",)
        found = hashing.find_files(path)
        if found is None or not found.files:
            raise FileNotFoundError(f"Nothing at {path} to put in the store.")
        derived = place is None
        if derived:
            if self.base is None:
                raise ValueError("Where it goes in the pipeline's folder is not known: give its place.")
            named = found.files[0] if found.single else found.root
            place = os.path.relpath(os.path.abspath(named), self.base)
        place = "" if place in (".", "") else str(place).replace("\\", "/") if os.name == "nt" else str(place)
        parts = plain_parts(place) if place else []
        if parts is None or (derived and parts and parts[0] == OWN_DIR):
            raise StoreError(
                f"{path} is not a plain path inside the pipeline's folder ({place!r}), or is under {OWN_DIR}/, "
                f"the name a snapshot's folder keeps for ChartBook; it is not put in the store."
            )
        root = os.path.abspath(found.root)
        if found.single:
            listed = [(declared_name(place.rpartition("/")[2]) or place.rpartition("/")[2], os.path.realpath(found.files[0]))]
        else:
            listed = [
                (relative, os.path.realpath(file))
                for file in sorted(found.files)
                for relative in [Path(os.path.relpath(os.path.abspath(file), root)).as_posix()]
                if not hashing.is_ignored(relative)
            ]
        return self.put_listed(listed, place, found.single, links)

    def put_listed(self, listed: list, place: str, single: bool, links: Iterable[str] = ("reflink", "copy")) -> StoredObject:
        """Store an asset given as its files, each ``(its path in the asset, the file to take it from)``, at *place*.

        What :meth:`put` does once it has found the files; for a caller that
        knows them otherwise, as ``store migrate`` does.

        :param place: For one file (*single*), its path in the pipeline;
            else the folder the files' paths are under.
        """
        links = tuple(kind for kind in links if kind in FROZEN_LINKS) or ("copy",)
        used: set = set()
        if single:
            ((name, source),) = listed
            at = place.rpartition("/")[0]
            entry = self._keep(source, f"{at}/{name}" if at else name, links, used)
            stored = {"at": at, "single": True, "files": [entry]}
            content_hash, size_bytes, entries, files = entry["content_hash"], entry["size_bytes"], (), (name,)
        else:
            kept = []
            for relative, source in listed:
                entry = self._keep(source, f"{place}/{relative}" if place else relative, links, used)
                kept.append((relative, entry))
            stored = {"at": place, "files": [entry for _, entry in kept]}
            content = hashing.hash_listing(
                hashing.FileEntry(relative, entry["size_bytes"], entry["content_hash"]) for relative, entry in kept
            )
            content_hash, size_bytes, entries = content.content_hash, content.size_bytes, content.files
            files = tuple(sorted(relative for relative, _ in kept))
        return StoredObject(
            content_hash=content_hash,
            size_bytes=size_bytes,
            path=self.pipeline_path / (self.name or "") / place,
            files=files,
            links=tuple(kind for kind in LINKS if kind in used),
            created=bool(used),
            entries=entries,
            stored=stored,
        )

    def write(self, document: dict) -> Path:
        if self._written:
            raise StoreError("This snapshot is written already.")
        if self.made_by != "snapshot" and "made_by" not in document:
            # Said just after when it was made, for a person reading it
            written = {}
            for name, value in document.items():
                written[name] = value
                if name == "made_at":
                    written["made_by"] = self.made_by
            written.setdefault("made_by", self.made_by)
            document = written
        own = self._claim() / OWN_DIR
        _check_length(own / f"{'0' * 12}.tmp")
        self._alive()
        self._confirm()
        self._refill()
        own.mkdir(exist_ok=True)
        record = own / RECORD_FILE
        temporary = own / f"{uuid.uuid4().hex[:12]}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
                json.dump(document, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(temporary, record)
        finally:
            if temporary.exists():
                temporary.unlink()
        self._written = True
        self.store._forget()
        self._refill()  # a `store gc` between the check and the record
        self._drop_note()
        write_readme(self.pipeline_path)  # for a person who finds the folder: what shared snapshots are, and gc
        return record

    def discard(self) -> None:
        if self._written:
            return
        if self.name is not None and (self.pipeline_path / self.name / OWN_DIR / RECORD_FILE).is_file():
            # Written, though what wrote it was cut short before it could say so: kept
            self._written = True
            self._drop_note()
            return
        if self.name is not None:
            try:
                _remove_tree(self.pipeline_path / self.name, own=True)
            except OSError:
                pass  # `store gc` clears a folder that has no record
            self.name = None
            try:
                self.pipeline_path.rmdir()
            except OSError:
                pass
        self.placed = False
        self._drop_note()


#: A snapshot's folder: when it was made, to the second in UTC, and the first 12 hex digits of its commit.
_SNAPSHOT_FOLDER = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z_[0-9a-f]{12}$")

#: Names Windows keeps for devices, with or without an extension.
_RESERVED_ON_WINDOWS = frozenset(
    {"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(10)} | {f"lpt{n}" for n in range(10)}
)


def is_snapshot_folder(name: str) -> bool:
    """Whether a folder is named as a store names a snapshot's: ``2026-10-26T182205Z_9b1e22d7a0c4``."""
    return isinstance(name, str) and bool(_SNAPSHOT_FOLDER.match(name))


def snapshot_folder_name(made_at: str, commit: str, later: int = 0) -> str:
    """The name of a snapshot's folder: when it was made, to the second, ``_``, and the first 12 hex digits of its commit.

    The time first, so that a sort of the folders is by when they were
    made; neither part has a ``_``, so the name splits in two at it.

    :param later: How many seconds later than *made_at* to name it: the
        next free second, when another snapshot of the commit has the name.
    :raises ValueError: If *made_at* is not a time as a snapshot writes one.
    """
    from datetime import datetime, timedelta

    when = datetime.strptime(made_at[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(seconds=later)
    return f"{when:%Y-%m-%dT%H%M%S}Z_{commit[:12]}"


def pipeline_folder(pipeline: str) -> str:
    """The name of a pipeline's folder in a store: its ID with ``/`` written as ``+``.

    ``+`` is in no ID, so no two IDs share a name. The disks of macOS and
    Windows do not tell letter case apart, so an ID with a capital letter,
    and one that Windows would not take as a name (``con``, or one ending
    in ``.``), also gets ``~`` and eight hex digits of a hash of the ID: a
    name no other ID's folder can have, as no ID has a ``~``.
    """
    name = pipeline.replace("/", "+")
    lowered = name.lower()
    if lowered == name and lowered.split(".")[0] not in _RESERVED_ON_WINDOWS and not lowered.endswith((".", " ")):
        return name
    return f"{lowered}~{hashlib.sha256(pipeline.encode('utf-8')).hexdigest()[:8]}"


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
                f"{link_target(file)}, which is no longer there"
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
            f"a link to {link_target(linked[0])}"
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

    from chartbook.multi_store import Stores, selected_store

    selected = selected_store.get()
    if selected is not None:
        return selected
    stores = Stores.configured()
    return stores.default() if len(stores.entries) == 1 and stores.catalog is None else stores


def __getattr__(name):
    if name == "Stores":
        from chartbook.multi_store import Stores
        return Stores
    raise AttributeError(name)
