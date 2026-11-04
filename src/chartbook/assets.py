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
    "gathered",
    "get_docs",
    "get_docs_page",
    "get_docs_path",
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


#: The kinds whose entry carries a write-up, ``docs`` or ``docs_path``. A
#: note is a write-up itself, and a notebook's page is the notebook.
WRITE_UP_KINDS = ("dataframe", "chart", "model", "file")

#: The most of a write-up, a README or a stored ``chartbook.toml`` that is
#: read: anyone who can write to a shared store wrote these.
WRITE_UP_LIMIT = 8 * 1024 * 1024


def _newest_snapshot(manifest: dict, pipeline_key: str):
    """A cataloged pipeline's newest snapshot in the catalog's stores, with the stores.

    :raises KeyError: If the stores hold no snapshot of it.
    """
    from chartbook import snapshot
    from chartbook.hubs import selected_snapshots

    stores = manifest["stores"]
    found, _ = snapshot.readable_snapshots(stores)
    chosen = selected_snapshots(found, pipeline_key, manifest.get("pipeline_notes", {}).get(pipeline_key, {}).get("repository"))
    if not chosen:
        raise KeyError(f"{pipeline_key} has no snapshot. Run `chartbook snapshot` in its pipeline.")
    return stores, max(chosen, key=lambda t: t.made_at)


def _docs_info(
    catalog_path: Path, pipeline: str, asset: Optional[Union[str, AssetRef]], manifest: Optional[dict] = None, newest=None
) -> tuple[str, str, Path]:
    """Where a cataloged pipeline's write-up of an asset is, or its README with no asset.

    *manifest* is the catalog's, loaded, and *newest* the stores and the
    pipeline's newest snapshot (:func:`_newest_snapshot`), when the caller
    has them already; each is read here if None.

    :returns: ``("path", declared, file)`` for a write-up in a file, the
        file where it is: in the pipeline's folder, or where the store keeps
        it; ``("str", text, manifest)`` for an inline ``docs``, with the
        ``chartbook.toml`` that holds it.
    :raises KeyError: If the pipeline, the asset or its write-up is not there.
    :raises ValueError: If the asset is a notebook, which has no write-up,
        or the stored ``chartbook.toml`` is not one ChartBook can read.
    :raises chartbook.store.StoreError: If the store does not have a file
        of the snapshot yet, as a synced folder still downloading.
    """
    from chartbook.manifest import load_manifest
    from chartbook.refs import KIND_TABLES
    from chartbook.resolve import locate_in_catalog

    ref = parse(asset) if asset is not None else None
    if ref is not None and (ref.pipeline is not None or ref.part or ref.rev):
        raise ValueError(
            f"Reference {str(ref)!r} is more than kind/name: give the pipeline on its own, and the asset as kind/name"
        )
    if ref is not None and ref.kind not in (*WRITE_UP_KINDS, "note"):
        raise ValueError(
            f"{ref} is a {ref.kind}, which has no write-up of its own: its page on the catalog's site is the {ref.kind}"
        )
    shown = f"{ref.kind} {ref.name!r}" if ref is not None else "README"

    manifest = manifest if manifest is not None else load_manifest(base_dir=catalog_path.parent)
    pipeline_key = locate_in_catalog(manifest, pipeline)

    if manifest.get("stores") is not None:
        import tomli

        from chartbook import snapshot

        stores, taken = newest if newest is not None else _newest_snapshot(manifest, pipeline_key)
        if not taken.documents:
            raise KeyError(f"The newest snapshot of {pipeline_key} has no stored documents")
        kept = stores.files(taken.documents["content_hash"], pipeline_key).by_relative()
        manifest_file = kept.get("chartbook.toml")
        if manifest_file is None:
            raise KeyError(f"The newest snapshot of {pipeline_key} keeps no chartbook.toml among its documents")
        try:
            raw = tomli.loads(snapshot._read_regular_file(Path(manifest_file), WRITE_UP_LIMIT).decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomli.TOMLDecodeError) as error:
            raise ValueError(f"The newest snapshot of {pipeline_key} keeps a chartbook.toml that cannot be read: {error}") from None

        def table(key):
            # A shared store's manifest was written by anyone who can write to it
            value = raw.get(key)
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"The newest snapshot of {pipeline_key} keeps a chartbook.toml whose [{key}] is not a table")
            return value or {}

        if ref is None:
            readme = table("project").get("readme")
            declared = readme.strip() if isinstance(readme, str) and readme.strip() else "README.md"
            plain = snapshot.safe_relative(declared)
            if plain is None or plain not in kept:
                raise KeyError(f"The newest snapshot of {pipeline_key} keeps no {declared}")
            return "path", plain, Path(kept[plain])
        entry = table(KIND_TABLES[ref.kind]).get(ref.name)
        if not isinstance(entry, dict):
            raise KeyError(f"{pipeline_key} declares no {shown} in its newest snapshot")
        if ref.kind == "note":
            # A note is an asset, and a page of the documents: by its own path there, as declared
            declared = entry.get("path") if isinstance(entry.get("path"), str) else ""
            plain = snapshot.safe_relative(declared) if declared else None
            if plain is not None and plain in kept:
                return "path", plain, Path(kept[plain])
            # Else as the store keeps the asset, its one file
            record = taken.assets.get(str(ref)) or {}
            if not record.get("content_hash"):
                raise KeyError(f"The newest snapshot of {pipeline_key} keeps no file of {shown}")
            files = stores.files(record["content_hash"], pipeline_key).files
            if len(files) != 1:
                raise KeyError(f"{pipeline_key}'s {shown} is {len(files)} files, not one page")
            return "path", declared, Path(files[0].location)
        for key in ("docs_path", "docs"):
            if entry.get(key) and not isinstance(entry[key], str):
                raise ValueError(f"{pipeline_key}'s {shown} has a {key} that is not text in its newest snapshot")
        if entry.get("docs_path"):
            plain = snapshot.safe_relative(entry["docs_path"])
            if plain is None or plain not in kept:
                raise ValueError("The documentation path is not inside the snapshot's documents")
            return "path", plain, Path(kept[plain])
        if not entry.get("docs"):
            raise KeyError(f"{pipeline_key}'s {shown} has no write-up: neither docs nor docs_path")
        return "str", entry["docs"], Path(manifest_file)

    pipeline_manifest = manifest["pipelines"][pipeline_key]
    pipeline_base_dir = Path(pipeline_manifest["base_dir"])
    if ref is None:
        readme = (pipeline_manifest.get("project") or {}).get("readme") or "README.md"
        return "path", readme, (pipeline_base_dir / readme).resolve()
    declared = pipeline_manifest.get(KIND_TABLES[ref.kind]) or {}
    if ref.name not in declared:
        raise KeyError(f"{shown} not found in pipeline {pipeline_key!r}. Declared: {sorted(declared)}")
    entry = declared[ref.name]
    if ref.kind == "note":
        return "path", entry["path"], (pipeline_base_dir / entry["path"]).resolve()
    if entry.get("docs_path"):
        return "path", entry["docs_path"], (pipeline_base_dir / entry["docs_path"]).resolve()
    if not entry.get("docs"):
        raise KeyError(f"{pipeline_key}'s {shown} has no write-up: neither docs nor docs_path")
    return "str", entry["docs"], (pipeline_base_dir / "chartbook.toml").resolve()


def get_docs_path(
    pipeline: str,
    asset: Optional[Union[str, AssetRef]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path to the write-up of a cataloged pipeline's asset, or to its README.

    The file is the asset's ``docs_path``, or the ``chartbook.toml`` that
    holds its inline ``docs``; a note's own file; with no asset, the
    pipeline's README. It is where the store keeps it, from the pipeline's
    newest snapshot; the store keeps the same bytes once, so the file may
    be named for another of the same bytes. :func:`chartbook.data.get_docs_path` is this for a
    dataframe.

    :param pipeline: The pipeline reference: a bare name, a scoped ID or a
        repository URL.
    :param asset: The asset within the pipeline, as ``kind/name``
        (``"chart/gdp"``, ``"model/forecaster"``, ``"file/filings"``,
        ``"note/methodology"``) or a bare name for a dataframe; None for the
        pipeline's README.
    :param catalog_path: The catalog to look in; the default one if None.
    :raises KeyError: If the pipeline, the asset or its write-up is not there.
    :raises ValueError: If the asset is a notebook, which has no write-up.
    """
    from chartbook.resolve import resolve_catalog_path

    _, _, docs_file = _docs_info(resolve_catalog_path(catalog_path), pipeline, asset)
    return docs_file


def get_docs(
    pipeline: str,
    asset: Optional[Union[str, AssetRef]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
) -> str:
    """Get the write-up of a cataloged pipeline's asset as text, or its README.

    What a person reads on the asset's page, for a program or an agent that
    reads no site: the content of its ``docs_path`` or its inline ``docs``;
    a note's own text; with no asset, the pipeline's README::

        assets.get_docs("yield_curve")                     # its README
        assets.get_docs("yield_curve", "chart/repo_rates") # a chart's write-up
        assets.get_docs("rate_forecast", "model/forecaster")

    Read from the pipeline's newest snapshot in the catalog's stores.
    :func:`chartbook.data.get_docs` is this for a dataframe.

    :param pipeline: The pipeline reference, as for :func:`get_docs_path`.
    :param asset: The asset, as for :func:`get_docs_path`.
    :param catalog_path: The catalog to look in; the default one if None.
    :raises KeyError: If the pipeline, the asset or its write-up is not there.
    :raises ValueError: If the asset is a notebook, which has no write-up.
    """
    from chartbook.resolve import resolve_catalog_path

    return _read_docs(*_docs_info(resolve_catalog_path(catalog_path), pipeline, asset))


def _read_docs(mode: str, value: str, docs_file: Path) -> str:
    """The text of a write-up, from where :func:`_docs_info` says it is."""
    from chartbook.snapshot import _read_regular_file

    if mode == "path":
        # Not a link, a device or a pipe, which a shared store's writer could leave there
        try:
            return _read_regular_file(docs_file, WRITE_UP_LIMIT).decode("utf-8")
        except FileNotFoundError:
            raise
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f"The write-up {docs_file} cannot be read as text: {error}") from None
    return value


def get_docs_page(
    pipeline: str,
    asset: Optional[Union[str, AssetRef]] = None,
    catalog_path: Optional[Union[str, Path]] = None,
) -> str:
    """What ``chartbook get-docs`` prints: a dataframe's whole page, or another asset's write-up.

    A dataframe's page is in Markdown, from what its newest snapshot's index
    recorded of it: its name, ID and description; its sources, providers
    and license; how it is pulled; its rows and the span of its dates; the
    snapshot it is from; then its write-up, and a table of its columns and
    their types::

        print(assets.get_docs_page("yield_curve", "repo_public"))

    Any other asset, and the README with no asset, is its write-up, as
    :func:`get_docs` gives it. So is a dataframe whose snapshot's index
    has no record of it.

    :param pipeline: The pipeline reference, as for :func:`get_docs_path`.
    :param asset: The asset, as for :func:`get_docs_path`.
    :param catalog_path: The catalog to look in; the default one if None.
    :raises KeyError: If the pipeline or the asset is not there, or an
        asset other than a dataframe has no write-up.
    :raises ValueError: If the asset is a notebook, which has no write-up.
    """
    from chartbook.manifest import load_manifest
    from chartbook.resolve import locate_in_catalog, resolve_catalog_path
    from chartbook.snapshot import _stored_records

    ref = parse(asset) if asset is not None else None
    if ref is None or ref.kind != "dataframe" or ref.pipeline is not None or ref.part or ref.rev:
        return get_docs(pipeline, asset, catalog_path)
    resolved = resolve_catalog_path(catalog_path)
    manifest = load_manifest(base_dir=resolved.parent)
    if manifest.get("stores") is None:
        return _read_docs(*_docs_info(resolved, pipeline, ref, manifest))
    newest = _newest_snapshot(manifest, locate_in_catalog(manifest, pipeline))
    stores, taken = newest
    asset_id = f"{taken.pipeline}:{ref.name}"
    record = next(
        (r for r in _stored_records(taken, stores) if isinstance(r, dict) and r.get("kind") == "Dataframe" and r.get("id") == asset_id),
        None,
    )
    try:
        write_up = _read_docs(*_docs_info(resolved, pipeline, ref, manifest, newest))
    except KeyError:
        if record is None:
            raise
        write_up = None  # the page is still its facts and columns
    return write_up if record is None else _dataframe_page(record, taken, write_up)


def _dataframe_page(record: dict, taken, write_up: Optional[str]) -> str:
    """A dataframe's page in Markdown, from its record in a stored index; see :func:`get_docs_page`.

    The record is whatever its owner put in the store, so each field is
    read as one line of what can be seen, and anything not of its shape is
    left out.
    """
    from chartbook.identity import plain_line

    def line(value) -> str:
        return plain_line(value, 2000)

    def listed(value) -> str:
        return ", ".join(text for text in (line(v) for v in value) if text) if isinstance(value, list) else line(value)

    lines = [f"# {line(record.get('name')) or line(record.get('id'))}", ""]
    if line(record.get("description")):
        lines += [line(record["description"]), ""]
    facts = [
        ("ID", line(record.get("id"))),
        ("Sources", listed(record.get("sources"))),
        ("Providers", listed(record.get("providers"))),
        ("Provider links", listed(record.get("provider_links"))),
        ("License", line(record.get("license"))),
        ("Pulled", line(record.get("pull_method"))),
        ("Tags", listed(record.get("tags"))),
    ]
    rows = record.get("row_count")
    if isinstance(rows, int) and not isinstance(rows, bool):
        facts.append(("Rows", f"{rows:,}"))
    span = record.get("date_range")
    if isinstance(span, dict) and line(span.get("first")) and line(span.get("last")):
        dates = f"{_day(line(span['first']))} to {_day(line(span['last']))}"
        if line(record.get("date_col")):
            dates += f", in column {line(record['date_col'])}"
        facts.append(("Dates", dates))
    made = taken.made_at.split(".")[0].removesuffix("Z") + "Z"  # to the second
    facts.append(("Snapshot", f"{taken.commit[:7]}, made {made}"))
    lines += [f"- {label}: {value}" for label, value in facts if value] + [""]
    if write_up and write_up.strip():
        # A write-up often starts with the dataframe's name, which the page has
        first, _, rest = write_up.strip().partition("\n")
        if first.lstrip("#").strip().casefold() == line(record.get("name")).casefold() and first.startswith("# "):
            write_up = rest
        if write_up.strip():
            lines += [write_up.strip(), ""]
    columns = record.get("columns") if isinstance(record.get("columns"), list) else []
    columns = [c for c in columns if isinstance(c, dict) and line(c.get("name"))]
    if columns:
        lines += ["## Columns", "", "| Column | Type |", "|---|---|"]
        lines += [f"| {_cell(c.get('name'))} | {_cell(c.get('dtype'))} |" for c in columns]
    return "\n".join(lines).rstrip("\n") + "\n"


def _day(text: str) -> str:
    """An ISO 8601 date or time as written, but a midnight as its day alone."""
    return text.removesuffix("T00:00:00")


def _cell(value) -> str:
    """Text as one cell of a Markdown table: one line, its bars escaped."""
    from chartbook.identity import plain_line

    return plain_line(value, 200).replace("|", "\\|")
