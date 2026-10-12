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

      cd _data/rates && find . -type f | sed 's|^\\./||' | LC_ALL=C sort \\
          | xargs sha256sum | sha256sum

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

_CHUNK_SIZE = 1024 * 1024
_GLOB_CHARACTERS = frozenset("*?[")


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
        temporary = self.path.with_name(self.path.name + ".tmp")
        with open(temporary, "w", encoding="utf-8") as f:
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
    # Code point order, which is byte order in UTF-8: what `LC_ALL=C sort` gives
    entries.sort(key=lambda entry: entry.path)
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


def hash_directory(
    directory: Union[str, Path], cache: Optional[HashCache] = None
) -> ContentHash:
    """Hash every file under a directory, as one asset."""
    directory = Path(directory)
    files = [
        Path(folder) / name
        for folder, _, names in os.walk(directory)
        for name in names
    ]
    return hash_files(files, directory, cache)


def hash_path(
    path: Union[str, Path], cache: Optional[HashCache] = None
) -> Optional[ContentHash]:
    """Hash whatever a declared ``path`` names: a file, a glob or a directory.

    :param path: An absolute path, which may contain glob characters.
    :returns: The hash, or None if nothing is there yet: the file does not
        exist, or the glob matches no file.
    """
    text = str(path)
    if is_glob_pattern(text):
        matches = [m for m in glob.glob(text, recursive=True) if os.path.isfile(m)]
        if not matches:
            return None
        return hash_files(matches, glob_root(text), cache)
    if os.path.isdir(text):
        return hash_directory(text, cache)
    if os.path.isfile(text):
        return hash_file(text, cache)
    return None
