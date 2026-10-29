"""Content hashes: the one way ChartBook names the bytes of an asset.

Hash computation is singular on purpose. Two implementations that hashed
differently would make no two indexes comparable, so everything that needs
the hash of an asset calls this module, and the rules below are part of the
index specification (``docs_src/design/index-schema.md``, "Hashes").

A hash is written ``"<algorithm>:<hex>"``, e.g. ``"sha256:7f3a9c..."``.

- **A file** is hashed as its bytes.
- **Several files**, the matches of a glob or the contents of a directory,
  are hashed as a listing with one line per file::

      <hex of the file's SHA-256>  <relative/path/with/forward/slashes>\\n

  sorted by path. This is the output of ``sha256sum``, so the result can be
  reproduced by hand::

      cd _data/rates && find . -type f | sed 's|^\\./||' \\
          | grep -viE '(^|/)(\\.DS_Store|Thumbs\\.db|desktop\\.ini|\\._[^/]*)$' \\
          | LC_ALL=C sort | xargs sha256sum | sha256sum

  The ``grep`` leaves out the few files that operating systems create by
  themselves (:func:`is_ignored`). Every other file counts, hidden or not.

Hashing reads every byte, and data files are large, so a
:class:`HashCache` remembers each file's hash against its size and
modification time. A file whose size and time are unchanged is not read
again. That is the same bet git makes, and it loses in the same case: a
file rewritten with identical size and identical timestamp.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from chartbook.utils import is_glob_pattern

#: The algorithm every content hash uses, and the prefix it is written with.
ALGORITHM = "sha256"

#: Name of the cache file kept in a build directory.
CACHE_FILE = ".chartbook-hash-cache.json"

#: Bumped when the cache file's layout changes; an old file is then ignored.
CACHE_VERSION = 1

#: Files that operating systems create by themselves, by name in lower case.
#: A directory or a glob is hashed without them, so that opening a folder in
#: Finder or Explorer does not change what the folder is.
IGNORED_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})

#: ...and by how the name starts: the ``._name`` companions macOS writes
#: beside files on a disk that is not its own.
IGNORED_PREFIX = "._"

_CHUNK_SIZE = 1024 * 1024
_GLOB_CHARACTERS = frozenset("*?[")


def is_ignored(name: Union[str, Path]) -> bool:
    """Whether a file is one of the few that are never part of an asset.

    These are ``.DS_Store``, ``Thumbs.db``, ``desktop.ini`` and anything
    whose name starts with ``._``, compared without regard to case. The
    list is short and fixed on purpose. A hidden file is content unless it
    is on it: a Zarr dataset keeps its metadata in ``.zarray``.

    The rule applies to an asset made of several files, a directory or a
    glob. A ``path`` that names one file is that file, whatever it is called.

    :param name: A file's name, or a path whose last component is one.
    """
    lowered = os.path.basename(str(name)).lower()
    return lowered in IGNORED_NAMES or lowered.startswith(IGNORED_PREFIX)


def format_hash(hex_digest: str) -> str:
    """Write a hex digest the way every hash is written: ``sha256:<hex>``."""
    return f"{ALGORITHM}:{hex_digest}"


def _file_hex(path: Path) -> str:
    """SHA-256 of a file's bytes, as hex, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class HashCache:
    """Remembers file hashes against each file's size and modification time.

    A cache is an optimization and nothing else: delete the file and every
    answer is the same, only slower.

    :param path: Where the cache is kept, or None to remember hashes for
        this object's lifetime only.
    """

    def __init__(self, path: Optional[Union[str, Path]] = None):
        self.path = Path(path) if path is not None else None
        self._stored: dict[str, list] = {}
        self._used: dict[str, list] = {}
        if self.path is not None:
            self._stored = self._read(self.path)
        self._known: dict[str, list] = dict(self._stored)

    @staticmethod
    def _read(path: Path) -> dict[str, list]:
        try:
            with open(path, encoding="utf-8") as f:
                stored = json.load(f)
        except (OSError, ValueError):
            return {}
        if not isinstance(stored, dict) or stored.get("version") != CACHE_VERSION:
            return {}
        files = stored.get("files")
        return files if isinstance(files, dict) else {}

    def file_hex(self, path: Union[str, Path]) -> str:
        """The hex SHA-256 of a file, read only if it changed since last seen.

        :raises OSError: If the file cannot be read.
        """
        path = Path(path)
        key = os.path.abspath(path)
        stat = path.stat()
        stamp = [stat.st_mtime_ns, stat.st_size]
        entry = self._known.get(key)
        if isinstance(entry, list) and len(entry) == 3 and entry[:2] == stamp:
            hex_digest = entry[2]
        else:
            hex_digest = _file_hex(path)
        self._known[key] = self._used[key] = [*stamp, hex_digest]
        return hex_digest

    def save(self) -> None:
        """Write the cache back, keeping only the files asked about this time.

        Dropping the rest is what stops the file growing for ever as data
        files come and go.
        """
        if self.path is None:
            return
        if self._used == self._stored and self.path.is_file():
            return  # nothing to add or drop; leave the file as it is
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                {"version": CACHE_VERSION, "files": self._used},
                f,
                indent=1,
                sort_keys=True,
            )
            f.write("\n")
        os.replace(temporary, self.path)


@dataclass(frozen=True)
class FileEntry:
    """One file of an asset that is made of several.

    Attributes:
        path: The file's path relative to the asset's root, with forward
            slashes.
        size_bytes: Its size.
        content_hash: Its hash, as ``sha256:<hex>``.
    """

    path: str
    size_bytes: int
    content_hash: str


@dataclass(frozen=True)
class ContentHash:
    """The hash of an asset's content, and what was hashed to get it.

    Attributes:
        content_hash: ``sha256:<hex>``.
        size_bytes: Total size of the bytes hashed.
        files: The files, when the asset is a glob or a directory; empty for
            a single file.
    """

    content_hash: str
    size_bytes: int
    files: tuple[FileEntry, ...] = field(default_factory=tuple)


def hash_file(path: Union[str, Path], cache: Optional[HashCache] = None) -> ContentHash:
    """Hash one file: the SHA-256 of its bytes.

    :raises OSError: If the file cannot be read.
    """
    path = Path(path)
    cache = cache if cache is not None else HashCache()
    return ContentHash(format_hash(cache.file_hex(path)), path.stat().st_size)


def hash_files(
    files: Iterable[Union[str, Path]],
    root: Union[str, Path],
    cache: Optional[HashCache] = None,
) -> ContentHash:
    """Hash several files as one asset: the SHA-256 of their listing.

    :param files: The files. Order does not matter.
    :param root: The directory their paths are written relative to.
    :raises ValueError: If a file is not under *root*.
    """
    cache = cache if cache is not None else HashCache()
    root = os.path.abspath(root)
    entries = []
    for file in files:
        file = Path(os.path.abspath(file))
        relative = Path(os.path.relpath(file, root))
        if relative.parts and relative.parts[0] == os.pardir:
            raise ValueError(f"{file} is not under {root}")
        entries.append(
            FileEntry(
                path=relative.as_posix(),
                size_bytes=file.stat().st_size,
                content_hash=format_hash(cache.file_hex(file)),
            )
        )
    return hash_listing(entries)


def hash_listing(entries: Iterable[FileEntry]) -> ContentHash:
    """The hash of an asset of several files, from each file's path, size and hash, reading none of them.

    The same as :func:`hash_files` gives for those files: the SHA-256 of
    their ``sha256sum`` listing.
    """
    # Code point order, which is byte order in UTF-8: what `LC_ALL=C sort` gives
    entries = sorted(entries, key=lambda entry: entry.path)
    listing = "".join(
        f"{entry.content_hash.split(':', 1)[1]}  {entry.path}\n" for entry in entries
    )
    return ContentHash(
        content_hash=format_hash(hashlib.sha256(listing.encode("utf-8")).hexdigest()),
        size_bytes=sum(entry.size_bytes for entry in entries),
        files=tuple(entries),
    )


def glob_root(pattern: Union[str, Path]) -> Path:
    """The fixed prefix of a glob pattern: its leading directories with no wildcard.

    ``_data/rates/**/*.parquet`` has the root ``_data/rates``, and
    ``_data/part-*.parquet`` has the root ``_data``. The files a glob
    matches are listed relative to this directory when they are hashed.
    """
    parts = Path(pattern).parts
    fixed = []
    for part in parts[:-1]:
        if _GLOB_CHARACTERS & set(part):
            break
        fixed.append(part)
    return Path(*fixed) if fixed else Path(".")


def directory_files(directory: Union[str, Path]) -> list[Path]:
    """Every file under a directory that counts as part of it.

    That is all of them but the ones :func:`is_ignored` names.
    """
    return [
        Path(folder) / name
        for folder, _, names in os.walk(directory)
        for name in names
        if not is_ignored(name)
    ]


def hash_directory(
    directory: Union[str, Path], cache: Optional[HashCache] = None
) -> ContentHash:
    """Hash every file under a directory, as one asset."""
    return hash_files(directory_files(directory), directory, cache)


@dataclass(frozen=True)
class PathFiles:
    """What a declared ``path`` names on disk.

    Attributes:
        root: The directory the files are listed relative to: the
            directory itself, a glob's fixed prefix, or a single file's
            parent.
        files: The files, in no particular order.
        single: True if the path names one file, which is hashed as its
            bytes. False for a directory or a glob, which is hashed as a
            listing even when it holds one file.
    """

    root: Path
    files: tuple[Path, ...]
    single: bool


def is_pattern(path: Union[str, Path]) -> bool:
    """Whether a path, made absolute, is a glob: it has glob characters and is not there as written.

    A pipeline in ``Research [2026]/`` gives every one of its paths a ``[``;
    a file or folder that is there under its own name is that file or folder.
    """
    text = str(path)
    return is_glob_pattern(text) and not os.path.exists(text)


def glob_named(declared: str, absolute: Union[str, Path]) -> Optional[str]:
    """The first part of a declared path that is a file or folder with a glob character in its name; None if none is.

    The files of such a path are found as they are named (:func:`is_pattern`),
    but whoever reads it later decides from the declared path whether it is
    a glob, and takes ``_data/[raw]`` for a pattern. So such a path is refused
    (:func:`glob_named_said`) rather than read two ways. The folders above
    the pipeline's own (``Research [2026]/``) are not part of it.

    :param declared: The path as the manifest writes it.
    :param absolute: That path joined to the pipeline's folder.
    :returns: The declared path up to that part, as declared.
    """
    # The declared parts, but for a leading climb, are the last parts of the absolute path
    tail = [part for part in Path(os.path.normpath(declared)).parts if part != os.pardir]
    parts = Path(absolute).parts
    above = len(parts) - len(tail)
    for i, part in enumerate(tail if above >= 0 else ()):
        if _GLOB_CHARACTERS & set(part) and os.path.lexists(os.path.join(*parts[: above + i + 1])):
            return Path(*tail[: i + 1]).as_posix()
    return None


def glob_named_said(declared: str, part: str) -> str:
    """What is said of a path :func:`glob_named` refuses, after "its path"."""
    return (
        f"{declared!r} names {part!r}, a file or folder whose name has a glob character "
        f"([, ? or *), which a reader would take for a pattern; rename it"
    )


def split_glob(pattern: Union[str, Path]) -> tuple[Path, str]:
    """A glob's root, and the pattern to match with that root taken as written.

    The root is the glob's leading folders that are there under their own
    names, ``[`` and all. That is :func:`glob_root` wherever those names have
    no glob characters in them.
    """
    parts = Path(pattern).parts
    fixed = 0
    while fixed < len(parts) - 1 and os.path.isdir(os.path.join(*parts[: fixed + 1])):
        fixed += 1
    if not fixed:
        return Path("."), str(pattern)
    root = Path(*parts[:fixed])
    return root, os.path.join(glob.escape(str(root)), *parts[fixed:])


def find_files(path: Union[str, Path]) -> Optional[PathFiles]:
    """Find the files a declared ``path`` names: a file, a glob or a directory.

    This is the one place that decides which files make up an asset, so
    that what is hashed and what is stored are the same files. A path that
    is there as written is a file or a directory, whatever characters are
    in it (:func:`is_pattern`).

    :param path: An absolute path, which may contain glob characters.
    :returns: The files, or None if nothing is there yet: the file does not
        exist, or the glob matches no file.
    """
    text = str(path)
    if is_pattern(text):
        root, pattern = split_glob(text)
        matches = tuple(
            Path(match)
            for match in glob.glob(pattern, recursive=True)
            if os.path.isfile(match) and not is_ignored(match)
        )
        if not matches:
            return None
        return PathFiles(root, matches, single=False)
    if os.path.isdir(text):
        return PathFiles(Path(text), tuple(directory_files(text)), single=False)
    if os.path.isfile(text):
        return PathFiles(Path(text).parent, (Path(text),), single=True)
    return None


def escapes(path: Union[str, Path], root: Union[str, Path]) -> Optional[Path]:
    """The first file a declared ``path`` reaches outside *root*, or None.

    A manifest's ``path`` is joined to the pipeline's directory, but it may
    be absolute, climb with ``..``, or be a symlink; and a file inside the
    directory may itself be a link to one outside. Every file the path
    names is followed to where it really is. This is what keeps a pipeline
    that is only read (a git dependency being pinned, a snapshot being
    made) from reaching anything but its own files.

    :param path: The declared path, made absolute, possibly a glob.
    :param root: The directory the files must be within.
    :returns: The real path of the first file outside *root*, or None if
        every file is inside it or there are no files.
    """
    inside = os.path.realpath(root)

    def outside(candidate) -> Optional[Path]:
        real = os.path.realpath(candidate)
        if real == inside or real.startswith(inside + os.sep):
            return None
        return Path(real)

    text = str(path)
    if not is_pattern(text):
        # The path itself, before anything is listed under it
        found = outside(text)
        if found is not None:
            return found
    files = find_files(text)
    if files is None:
        return None
    for file in files.files:
        found = outside(file)
        if found is not None:
            return found
    return None


def hash_path(
    path: Union[str, Path], cache: Optional[HashCache] = None
) -> Optional[ContentHash]:
    """Hash whatever a declared ``path`` names: a file, a glob or a directory.

    :param path: An absolute path, which may contain glob characters.
    :returns: The hash, or None if nothing is there yet: the file does not
        exist, or the glob matches no file.
    """
    found = find_files(path)
    if found is None:
        return None
    if found.single:
        return hash_file(found.files[0], cache)
    return hash_files(found.files, found.root, cache)
