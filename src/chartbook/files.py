"""Files: the front door for assets that are not tables.

A files asset is a file, a folder of files or a glob of them, that a
pipeline declares in ``[files]``, whatever is inside: gzipped JSON lines,
text, HTML, PDFs, images, NumPy arrays, a SQLite file, a vendor's zip.
ChartBook moves, versions and documents the bytes. It does not read them:
the one exception is a short preview on the asset's page, at most
:data:`PREVIEW_BYTES` of one file. Reading is one line of your own code::

    import gzip, json
    from chartbook import assets

    for path in assets.files("file/earnings_releases"):
        with gzip.open(path, "rt") as f:
            records = [json.loads(line) for line in f]

:func:`chartbook.assets.files` gives the files, sorted, and
:func:`chartbook.assets.index` a table of them, with their sizes, hashes
and the keys of any ``key=value`` folders, to pick files from before
opening any. Both work for every asset with files, a dataframe's too.
:func:`path` here is :func:`chartbook.assets.path` with the kind fixed, as
:func:`chartbook.models.path` is for models.

A snapshot, a pin, ``chartbook update``, ``restore``, ``lineage`` and
``store gc`` treat a files asset as any other: its hash is the hash of
its file, or of the listing of its files (:mod:`chartbook.hashing`).
"""

import gzip
import json
import os
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional, Union

from chartbook import assets as _assets
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import caller_start_dirs

#: The most of a file a page's preview decompresses or reads as text: a
#: preview never costs more than this, and four times as much read of a
#: compressed file.
PREVIEW_BYTES = 4096

#: The most lines a preview shows, once pretty-printed, and the longest line.
PREVIEW_LINES = 40
PREVIEW_LINE_LENGTH = 300

#: Endings of a file that a preview reads as text, with or without ``.gz``.
TEXT_SUFFIXES = frozenset(
    {
        ".txt", ".text", ".md", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".html", ".htm",
        ".xml", ".yaml", ".yml", ".log", ".sql", ".tex", ".bib",
    }
)

#: Endings of a file that are lines of JSON, which a preview pretty-prints.
JSON_LINES_SUFFIXES = frozenset({".jsonl", ".ndjson"})

#: Endings of an image a page shows as a thumbnail: what a browser shows in
#: an ``<img>``. SVG is left out, since opened as a page it runs scripts.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

#: The largest image a page shows; a larger one is named, and not copied into the site.
THUMBNAIL_BYTES = 2 * 1024 * 1024

#: Endings that say a file is compressed, so its type is the ending before.
COMPRESSED_SUFFIXES = frozenset({".gz", ".bz2", ".xz", ".zst", ".lz4", ".zip"})


def path(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path the manifest declares for a files asset of the current pipeline.

    >>> from chartbook import files
    >>> files.path("earnings_releases")  # doctest: +SKIP

    This is :func:`chartbook.assets.path` with ``kind="file"``: it answers
    for files assets and nothing else. The path is the file, the folder,
    or the glob as declared; :func:`chartbook.assets.files` gives the
    files themselves. Nothing checks that it exists, so a build can ask
    where to write before anything is there.

    A files asset of another pipeline is named with the pipeline in front,
    ``files.path("filings:earnings_releases")``, and is the copy that
    ``chartbook.lock`` pins.

    :param ref: The asset's name: its key in ``[files]``.
    :param project_dir: Where to look for the pipeline, as for
        :func:`chartbook.assets.path`.
    :returns: The absolute path declared for the asset.
    :raises AssetNotDeclaredError: If the manifest declares no such asset.
    :raises ValueError: If the reference names another kind of asset.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    try:
        return _assets._path(ref, "file", start_dirs)
    except KindMismatchError as e:
        raise KindMismatchError(
            str(ref),
            e.found,
            e.expected,
            hint=(
                f"files.path() answers for files assets only; use "
                f"chartbook.assets.path({str(ref)!r}) for a {e.found}."
            ),
        ) from None


def extension(name: str) -> str:
    """A file's type, by its name: ``.jsonl.gz``, ``.pdf``; empty when it has no ending.

    In lower case. A compressed file keeps the ending before its
    compression's, so that ``x.jsonl.gz`` and ``y.csv.gz`` are told apart.
    """
    suffixes = [s.lower() for s in Path(name).suffixes]
    if not suffixes:
        return ""
    if suffixes[-1] in COMPRESSED_SUFFIXES and len(suffixes) > 1 and len(suffixes[-2]) <= 8:
        return "".join(suffixes[-2:])
    return suffixes[-1]


def count_by_extension(names: Iterable[str]) -> dict[str, int]:
    """How many files there are of each type (:func:`extension`), by type; ``""`` for those with no ending."""
    return dict(sorted(Counter(extension(name) for name in names).items()))


def partitions(relative: str) -> dict[str, str]:
    """The ``key=value`` folders of a file's path inside its asset, in order: ``{"year": "2024"}``.

    Only folders count, not the file's own name, as a reader of Hive's
    layout takes them. A folder whose key is empty is not one.
    """
    found = {}
    for part in relative.replace("\\", "/").split("/")[:-1]:
        key, sign, value = part.partition("=")
        if sign and key:
            found[key] = value
    return found


def _bounded(file: Path) -> tuple[bytes, bool]:
    """The start of a file, at most :data:`PREVIEW_BYTES`, decompressed if it is gzip; and whether that is all of it.

    Of a gzip file, no more than :data:`PREVIEW_BYTES` is inflated, from
    at most four times as much read.
    """
    with open(file, "rb") as f:
        head = f.read(PREVIEW_BYTES)
        if not head.startswith(b"\x1f\x8b"):
            return head, len(head) < PREVIEW_BYTES
        inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = inflate.decompress(head, PREVIEW_BYTES)
        read = len(head)
        while len(out) < PREVIEW_BYTES and not inflate.eof:
            more = inflate.unconsumed_tail
            if not more:
                if read >= 4 * PREVIEW_BYTES:
                    break
                more = f.read(PREVIEW_BYTES)
                read += len(more)
                if not more:
                    break
            out += inflate.decompress(more, PREVIEW_BYTES - len(out))
        return out, inflate.eof and len(out) < PREVIEW_BYTES


def preview_text(file: Union[str, Path]) -> Optional[str]:
    """The first lines of a text file, for a page: None if it is not text, or cannot be read.

    At most :data:`PREVIEW_BYTES` are read (decompressed, for gzip;
    :func:`_bounded`). A line that is a JSON object or array is
    pretty-printed, and then at most :data:`PREVIEW_LINES` lines are kept,
    each cut to :data:`PREVIEW_LINE_LENGTH` characters. A line cut short by
    the limit is left out. Bytes that are not UTF-8, or a NUL, say it is
    not text.
    """
    file = Path(file)
    try:
        head, whole = _bounded(file)
    except (OSError, zlib.error, EOFError, gzip.BadGzipFile):
        return None
    if b"\0" in head or not _mostly_utf8(head):
        return None
    lines = head.decode("utf-8", errors="ignore").splitlines()
    if not whole and len(lines) > 1:
        lines = lines[:-1]  # the last is cut short
    if extension(file.name).removesuffix(".gz") in JSON_LINES_SUFFIXES | {".json"}:
        shown = []
        for line in lines:
            if line.strip().startswith(("{", "[")):
                try:
                    shown += json.dumps(json.loads(line), indent=2, ensure_ascii=False).splitlines()
                    continue
                except ValueError:
                    pass
            shown.append(line)
        lines = shown
    cut = len(lines) > PREVIEW_LINES or not whole
    lines = [_printable(line) for line in lines[:PREVIEW_LINES]]
    lines = [line if len(line) <= PREVIEW_LINE_LENGTH else line[: PREVIEW_LINE_LENGTH - 1] + "…" for line in lines]
    return "\n".join(lines + (["…"] if cut else []))


def _mostly_utf8(head: bytes) -> bool:
    """Whether bytes are UTF-8, allowing a character cut at the end by the limit."""
    for cut in range(4):
        try:
            head[: len(head) - cut].decode("utf-8")
            return True
        except UnicodeDecodeError:
            continue
    return False


def _printable(line: str) -> str:
    """A line with control and direction-changing characters taken out; a tab stays."""
    return "".join(c for c in line if c == "\t" or c.isprintable())


def preview_kind(name: str) -> Optional[str]:
    """``"text"`` or ``"image"`` for a file a page previews, by its name; None for one it does not."""
    kind = extension(name)
    if kind in IMAGE_SUFFIXES:
        return "image"
    if kind.removesuffix(".gz") in TEXT_SUFFIXES:
        return "text"
    return None


def preview_of(listed: list, root: Union[str, Path]) -> Optional[dict]:
    """What a files asset's page previews: the first file in its listing that a preview can show.

    :param listed: The files, as the index lists them (``path`` relative to
        *root*, and ``size_bytes``), in order.
    :param root: The folder they are listed from.
    :returns: ``{"path", "kind", "file"}`` (the file on disk), with ``text``
        for a text file; None when no file listed is one to preview, or the
        first that is cannot be read. An image larger than
        :data:`THUMBNAIL_BYTES` is not previewed.
    """
    for entry in listed:
        relative = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(relative, str) or any(part in ("", ".", "..") for part in relative.split("/")):
            continue  # a path inside the asset, and nothing else, is read
        kind = preview_kind(relative)
        if kind is None:
            continue
        file = Path(root).joinpath(*relative.split("/"))
        if kind == "image":
            if not isinstance(entry.get("size_bytes"), int) or entry["size_bytes"] > THUMBNAIL_BYTES:
                continue
            if not file.is_file():
                return None
            return {"path": relative, "kind": "image", "file": file}
        text = preview_text(file)
        if text is None:
            return None
        return {"path": relative, "kind": "text", "file": file, "text": text}
    return None


def listing_root(declared: Union[str, Path]) -> Path:
    """The folder an asset's files are listed from: a folder itself, a glob's fixed prefix, a file's own folder."""
    from chartbook import hashing
    from chartbook.utils import is_glob_pattern

    declared = str(declared)
    if is_glob_pattern(declared):
        return hashing.glob_root(declared)
    if os.path.isdir(declared):
        return Path(declared)
    return Path(declared).parent
