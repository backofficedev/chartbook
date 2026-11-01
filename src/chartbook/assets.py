"""Assets: everything a pipeline declares, addressed one way.

An asset is something ``chartbook.toml`` declares: a dataframe, a chart, a
notebook, a note, a model or a files asset. Each is addressed by a
*reference*. Within the pipeline you are in, that is the asset's name, with
its kind in front unless it is a dataframe::

    from chartbook import assets

    assets.path("treasury_rates")        # [dataframes.treasury_rates]
    assets.path("chart/yield_curve")     # [charts.yield_curve]
    assets.path("notebook/analysis")     # [notebooks.analysis]
    assets.path("note/methodology")      # [notes.methodology]
    assets.path("model/rate_forecaster") # [models.rate_forecaster]
    assets.path("file/filings")          # [files.filings]

An asset's path may be a folder or a glob. :func:`files` gives the files
themselves, sorted, and :func:`index` a table of them, with their sizes and
hashes, to choose from before opening any::

    assets.files("file/filings")         # [Path(".../2024/10-K.htm"), ...]
    assets.index("file/filings")         # a LazyFrame: path, size_bytes, sha256

The kind may be given as an argument instead, which reads better when the
name is in a variable. It says what you expect: a reference that names no
kind takes it, and one that names a different kind is an error::

    assets.path("yield_curve", kind="chart")       # the same chart
    assets.path("chart/yield_curve", kind="chart") # the same chart
    assets.path("yield_curve")                     # a *dataframe* called yield_curve

Data is the common case, so it gets the short spelling here and its own
front door: :func:`chartbook.data.path` is this function for dataframes
only, and :func:`chartbook.models.path` is this function for models only.

A reference can also be built and passed as an object, :class:`AssetRef`,
which is what :func:`parse` returns and what ChartBook carries internally::

    ref = assets.parse("chart/yield_curve")
    ref.kind, ref.name                   # ("chart", "yield_curve")
    assets.path(ref)

An asset of another pipeline has that pipeline's name in front::

    assets.path("fed_yield_curve:treasury_rates")
    assets.path("fed_yield_curve:chart/curve_today")

The pipeline must be one that ``[dependencies]`` declares, and the path is
that of the copy ``chartbook.lock`` pins, in the store. It is not the other
pipeline's working directory, so what it holds does not change until you
run ``chartbook update``. Read it; do not write to it.

The full grammar, ``[registry/][scope/]pipeline:[kind/]name[#part][@rev]``,
is specified in ``docs_src/design/references.md``. A part, a revision and a
registry parse, and are refused as not yet supported.
"""

import hashlib
import os
import sys
from pathlib import Path
from typing import Optional, Union

from chartbook.refs import (
    DEFAULT_KIND,
    KINDS,
    AssetRef,
    KindMismatchError,
)
from chartbook.refs import parse_asset_ref as parse
from chartbook.resolve import FileLocation, caller_start_dirs, require_single_path, resolve

__all__ = [
    "DEFAULT_KIND",
    "KINDS",
    "AssetRef",
    "KindMismatchError",
    "files",
    "index",
    "parse",
    "path",
]

#: The columns of :func:`index` that every row has; a ``key=value`` folder's key with one of these names is left out.
INDEX_COLUMNS = ("path", "size_bytes", "sha256")


def _path(ref: Union[str, AssetRef], kind: Optional[str], start_dirs: list) -> Path:
    """Resolve a reference to a file path, from given starting points.

    The public functions are thin shells over this one, because each must
    read *its own* caller's stack frame to find the calling file.
    """
    asset = parse(ref, kind=kind)
    location = resolve(asset, start_dirs=start_dirs)
    # Several files read from the store have no one path (require_single_path)
    path = require_single_path(location, f"The {asset.kind} {asset.name!r}", ref if isinstance(ref, str) else str(asset), asset.kind)
    if asset.is_local and not getattr(location, "content_hash", None):
        _make_room(path, start_dirs)  # this pipeline's own, where its build writes: the folder is there for the first write
    return path


def _make_room(path: Path, start_dirs: list) -> None:
    """Make the folder a file of this pipeline's own is written into, so that the first write does not fail for want of it.

    The file's parent folder: a folder dataset's own folder is made by
    polars when it writes with ``partition_by``, and a path with no ending
    may be a file. A glob's is the folder its pattern starts in, judged by
    the path inside the pipeline, so a pipeline whose own folder is named
    with a ``[`` is not taken for a glob. Only inside the pipeline's folder:
    a declared path that climbs out of it makes nothing. Nothing is made for
    another pipeline's asset, read where the store keeps it or, linked,
    in its own folder. A folder that cannot be made is left to the write
    to say so.
    """
    from chartbook import hashing
    from chartbook.resolve import find_manifest_dir

    try:
        root = Path(os.path.abspath(find_manifest_dir(*start_dirs)))
        inside = Path(os.path.abspath(path)).relative_to(root)
    except (ValueError, OSError, Exception):  # noqa: BLE001 - no manifest, or a path outside it: nothing is made
        return
    if hashing.is_pattern(inside.as_posix()):
        folder = root / hashing.glob_root(inside)
    else:
        folder = (root / inside).parent
    if not Path(os.path.abspath(folder)).is_relative_to(root):
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def path(
    ref: Union[str, AssetRef],
    kind: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path of an asset: this pipeline's own, or a pinned copy of another's.

    The enclosing ``chartbook.toml`` is the single source of truth for where
    an asset lives, so code can ask for the path rather than repeat it:

    >>> from chartbook import assets
    >>> fig.write_html(assets.path("chart/yield_curve"))  # doctest: +SKIP

    and a build definition can use the same call for what it reads and what
    it writes. The path is whatever ``path`` the entry declares, made
    absolute; nothing checks that the file exists, so a target can be named
    before it is built. For this pipeline's own asset the folder it is
    written into is made if it is not there yet, so the first write of a
    new pipeline does not fail for want of ``_data/``; polars makes a
    folder dataset's own folder when it writes with ``partition_by``.

    Each kind of asset has its own names: ``[dataframes.gdp]`` and
    ``[charts.gdp]`` are two assets, ``gdp`` and ``chart/gdp``. Asking for a
    name its table does not declare raises immediately, naming the table to
    add, or saying what kind of asset the name is declared as.

    This is a convenience, never a requirement. A script that hardcodes the
    same path, in any language, works just as well; ``chartbook path`` on the
    command line gives the same answer to a shell, Make, R or Stata.

    **Another pipeline's asset** is named ``"pipeline:name"``, and resolves
    differently on purpose. The pipeline must be declared in
    ``[dependencies]``, and the path returned is in the store: the copy that
    ``chartbook.lock`` pins, not the other pipeline's working directory.

    >>> assets.path("fed_yield_curve:treasury_rates")  # doctest: +SKIP

    So it does not change while the other pipeline is being worked on, and
    moves only when you run ``chartbook update``. It must have been pinned
    (``chartbook pin``), and is for reading: never write to it.

    **Another pipeline's folder or glob of files has no one path.** The
    store keeps each file once, so a snapshot's files may sit in other
    snapshots' folders. Asking raises
    :class:`~chartbook.errors.NoSinglePathError`, whatever the folders
    happen to hold today, so that a call that works does not stop working
    when the upstream takes another snapshot. :func:`files` lists the
    files, :func:`chartbook.data.load` reads a dataframe's where they are,
    and :func:`gathered` lays them out in a temporary folder for a loader
    that needs one. Your own pipeline's folder asset is the declared folder,
    as before.

    :param ref: A reference to the asset: ``"name"`` for a dataframe,
        ``"kind/name"`` for anything else, ``"pipeline:name"`` for another
        pipeline's, or an :class:`AssetRef`.
    :type ref: Union[str, AssetRef]
    :param kind: The kind of asset expected: ``"dataframe"``, ``"chart"``,
        ``"notebook"``, ``"note"``, ``"model"`` or ``"file"``. A reference that names no kind takes
        this one. By default, a reference that names no kind is a dataframe.
    :type kind: Optional[str]
    :param project_dir: Where to look for the pipeline. The enclosing
        ``chartbook.toml`` is found by walking up from here. By default the
        search starts at the calling file's directory, then falls back to the
        current working directory.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path of the asset (it may contain glob
        characters for partitioned data; :func:`files` gives the files).
    :rtype: Path
    :raises AssetNotDeclaredError: If the manifest declares no such asset.
    :raises DependencyNotDeclaredError: If the reference names a pipeline
        that ``[dependencies]`` does not declare.
    :raises AssetNotPinnedError: If another pipeline's asset has no pinned
        copy in the store.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises KindMismatchError: If the reference names a kind other than *kind*.
    :raises NoSinglePathError: If the asset is another pipeline's folder or
        glob of files, which has no one path (above).
    :raises ValueError: If the reference does not follow the grammar, uses
        syntax that is reserved and not yet supported, or the entry has no
        ``path``.
    """
    return _path(ref, kind, caller_start_dirs(project_dir, sys._getframe(1)))


def _located(ref: Union[str, AssetRef], kind: Optional[str], start_dirs: list) -> tuple[AssetRef, FileLocation]:
    """A reference and where its files are; a table or a query has none."""
    asset = parse(ref, kind=kind)
    location = resolve(asset, start_dirs=start_dirs)
    if not isinstance(location, FileLocation):
        raise TypeError(
            f"The {asset.kind} {asset.name!r} is {location.kind}-backed, so it has no files. "
            f"Use data.load() to read it, data.sql() to query it, or data.ref() for its name in SQL."
        )
    return asset, location


def _not_there(asset: AssetRef, location: FileLocation) -> FileNotFoundError:
    return FileNotFoundError(
        f"The {asset.kind} {str(asset)!r} has no files: no file is at {location.path}. "
        f"If it is this pipeline's own, its build makes them."
    )


def _found(asset: AssetRef, location: FileLocation) -> list[tuple[str, Path]]:
    """Each file of an asset, by its path in the asset, sorted as a hash lists them."""
    from chartbook import hashing

    inside = getattr(location, "inside", None)
    if inside:
        # From the store: the files its record lists, each where the store keeps it, and nothing else
        return sorted((relative, Path(where)) for relative, where in inside.items())
    found = hashing.find_files(location.path)
    if found is None or not found.files:
        raise _not_there(asset, location)
    if found.single:
        return [(found.files[0].name, Path(found.files[0]))]
    return sorted((Path(os.path.relpath(file, found.root)).as_posix(), Path(file)) for file in found.files)


def files(
    ref: Union[str, AssetRef],
    kind: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
) -> list[Path]:
    """Get the files of an asset: the file, a folder's files, or a glob's matches, sorted.

    >>> from chartbook import assets
    >>> for path in assets.files("filings:file/earnings_releases"):  # doctest: +SKIP
    ...     records = read_one(path)

    The asset is found as :func:`path` finds it, and its files are the
    ones its content hash is made of (:mod:`chartbook.hashing`): every file
    under a folder or matched by a glob, but ``.DS_Store`` and the few
    others operating systems write by themselves. Of another pipeline's
    asset they are the files of the pinned copy, as its record lists them,
    each where the store keeps it: the store keeps each file once, so they
    may sit in several snapshots' folders, and this is the call to read
    them by (polars and DuckDB take a list of files; so does a ``dodo.py``
    for its ``file_dep``). They are sorted by their path inside the asset,
    so a dataset of a file a year is read in order of the years.

    It works for every asset with files: a files asset, a dataframe of
    many parts (to read one at a time), a model that is a folder.

    :param ref: A reference to the asset, as for :func:`path`.
    :param kind: The kind of asset expected, as for :func:`path`.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: The absolute path of each file.
    :raises FileNotFoundError: If nothing is there: the asset is not built.
    :raises TypeError: If the asset is a table or a query in a source.
    :raises AssetNotDeclaredError: As for :func:`path`, and the rest of its errors.
    """
    asset, location = _located(ref, kind, caller_start_dirs(project_dir, sys._getframe(1)))
    return [file for _, file in _found(asset, location)]


class _Gathered:
    """A temporary folder an asset's files are laid out in (:func:`gathered`)."""

    def __init__(self, found: list):
        self._found = found
        self._temporary = None

    def __enter__(self) -> Path:
        import shutil
        import tempfile

        self._temporary = tempfile.TemporaryDirectory(prefix="chartbook-gathered-")
        root = Path(self._temporary.name)
        try:
            for relative, file in self._found:
                target = root.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
        except BaseException:
            self._temporary.cleanup()
            self._temporary = None
            raise
        return root

    def __exit__(self, *exc) -> bool:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
        return False


def gathered(
    ref: Union[str, AssetRef],
    kind: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
) -> _Gathered:
    """Lay an asset's files out together in a temporary folder, for a loader that needs one; the folder goes when the block ends.

    >>> from chartbook import assets
    >>> with assets.gathered("forecasting:model/rate_forecaster") as folder:  # doctest: +SKIP
    ...     model = AutoModel.from_pretrained(folder)

    For a model or a files asset whose loader takes a directory. The files
    are copied, so a loader may write beside them; nothing is kept once the
    block ends, and nothing is kept between runs. A dataframe needs none of
    this: :func:`chartbook.data.load` reads its files where they are, and
    :func:`files` lists them for any other reader.

    :param ref: A reference to the asset, as for :func:`path`.
    :param kind: The kind of asset expected, as for :func:`path`.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: A context manager whose value is the folder.
    :raises FileNotFoundError: If nothing is there: the asset is not built.
    :raises TypeError: If the asset is a table or a query in a source.
    :raises AssetNotDeclaredError: As for :func:`path`, and the rest of its errors.
    """
    asset, location = _located(ref, kind, caller_start_dirs(project_dir, sys._getframe(1)))
    return _Gathered(_found(asset, location))


def _hash_cache(declared: Path):
    """The hash cache for one asset's files, kept in this machine's cache: an asset hashed again reads only what changed."""
    from chartbook import hashing
    from chartbook.config import get_cache_path

    name = hashlib.sha256(str(declared).encode("utf-8", errors="surrogateescape")).hexdigest()[:32]
    return hashing.HashCache(get_cache_path() / "hashes" / f"{name}.json")


def _rows(asset: AssetRef, location: FileLocation) -> list[tuple[Path, str, int, str]]:
    """Each file of an asset with its path in the asset, its size and its hash.

    From the store's record when the store holds what is read: nothing is
    read but the record. Otherwise the files are hashed, each read only if
    it has changed since it was last hashed.
    """
    from chartbook import hashing
    from chartbook.files import listing_root
    from chartbook.store import default_store, on_disk, plain_parts
    from chartbook.utils import is_glob_pattern

    declared = Path(location.path)
    inside = getattr(location, "inside", None)
    single = not location.listed if inside else not is_glob_pattern(str(declared)) and declared.is_file()
    listed = default_store().listing(location.content_hash, single) if location.content_hash else None
    if listed is not None and inside:
        if single:
            # One file, read by the name its asset gives it: the same bytes may be two assets'
            ((relative, where),) = inside.items()
            return [(Path(where), relative, listed[0].size_bytes, listed[0].content_hash)]
        # Each where the store keeps it, which may be another snapshot's folder
        return [(Path(inside[entry.path]), entry.path, entry.size_bytes, entry.content_hash) for entry in listed if entry.path in inside]
    if listed is not None:
        if single:
            return [(declared, declared.name, listed[0].size_bytes, listed[0].content_hash)]
        root = listing_root(declared)
        return [
            (on_disk(root, plain_parts(entry.path)), entry.path, entry.size_bytes, entry.content_hash)
            for entry in listed
            if plain_parts(entry.path)
        ]
    cache = _hash_cache(declared)
    try:
        content = hashing.hash_path(declared, cache)
    except OSError as error:
        raise FileNotFoundError(f"The {asset.kind} {str(asset)!r} could not be read: {error}") from None
    if content is None:
        raise _not_there(asset, location)
    try:
        cache.save()
    except OSError:
        pass  # a cache that cannot be written is only slower
    if not content.files and not single:
        raise _not_there(asset, location)  # a folder with no file in it
    if not content.files:
        return [(declared, declared.name, content.size_bytes, content.content_hash)]
    root = listing_root(declared)
    return [(root.joinpath(*entry.path.split("/")), entry.path, entry.size_bytes, entry.content_hash) for entry in content.files]


def index(
    ref: Union[str, AssetRef],
    kind: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
):
    """Get a table of an asset's files, one row per file, to choose from before opening any.

    >>> import polars as pl
    >>> from chartbook import assets
    >>> chosen = (
    ...     assets.index("filings:file/earnings_releases")
    ...     .filter(pl.col("year") >= "2020")
    ...     .collect()
    ... )  # doctest: +SKIP

    The columns are ``path`` (the file, as :func:`files` gives it),
    ``size_bytes``, ``sha256`` (the file's hash, in hex), and then the key
    of each ``key=value`` folder the files are in, as text:
    ``filings/year=2024/q=1/x.htm`` has ``year`` ``"2024"`` and ``q``
    ``"1"``. The rows are in the order :func:`files` gives.

    Of another pipeline's asset, every file's size and hash come from the
    record the store keeps of it, and nothing is read. Of this pipeline's,
    the files are hashed, and a file is read again only when it has changed
    (a hash cache in this machine's cache, ``~/.chartbook/cache/hashes``).

    :param ref: A reference to the asset, as for :func:`path`.
    :param kind: The kind of asset expected, as for :func:`path`.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: A ``polars.LazyFrame``.
    :raises FileNotFoundError: If nothing is there: the asset is not built.
    :raises TypeError: If the asset is a table or a query in a source.
    :raises AssetNotDeclaredError: As for :func:`path`, and the rest of its errors.
    """
    import polars as pl

    from chartbook.files import partitions

    asset, location = _located(ref, kind, caller_start_dirs(project_dir, sys._getframe(1)))
    rows = sorted(_rows(asset, location), key=lambda row: row[1])
    keys: dict = {}
    for _, relative, _, _ in rows:
        for key in partitions(relative):
            if key not in INDEX_COLUMNS:
                keys.setdefault(key, None)
    columns: dict = {
        "path": [str(file) for file, _, _, _ in rows],
        "size_bytes": [size for _, _, size, _ in rows],
        "sha256": [content_hash.split(":", 1)[-1] for _, _, _, content_hash in rows],
    }
    for key in keys:
        columns[key] = [partitions(relative).get(key) for _, relative, _, _ in rows]
    schema = {"path": pl.String, "size_bytes": pl.Int64, "sha256": pl.String, **{key: pl.String for key in keys}}
    return pl.DataFrame(columns, schema=schema).lazy()
