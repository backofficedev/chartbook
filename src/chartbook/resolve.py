"""Name resolution: turn a reference into a typed location.

Everything that maps a name to a place — ``assets.path()``, ``data.path()``,
``data.load()``, ``data.get_data_path()``, ``chartbook path`` — calls
:func:`resolve` and gets back a :class:`Location`. What to do with a
location is the caller's business; looking the name up is not, so there is
exactly one place where names are resolved.

A reference is parsed by :mod:`chartbook.refs`, which accepts the whole
grammar. This module decides which references can be *resolved* yet, and
refuses the rest as reserved, not invalid.

Today a location is always a :class:`FileLocation`. The data-access design
(``docs_src/design/data-access.md``) adds table- and query-backed
dataframes as further kinds, which is why ``load()`` and ``path()`` each
call the resolver rather than one calling the other: a table has no path,
but it can still be loaded.

Three forms of reference resolve today:

- a **local** reference — ``name`` or ``kind/name`` — against the
  ``chartbook.toml`` enclosing the caller. It resolves *live*: to the
  ``path`` the manifest declares, which is the file you are working on.
  The raw file is read and nothing else, so this is cheap, offline, and
  does not care whether the asset has been built yet;
- a **cross-pipeline** reference — ``pipeline:name`` — to an asset of a
  pipeline that ``[dependencies]`` declares. It resolves *pinned*: through
  ``chartbook.lock`` to the copy in the store. So what a pipeline reads
  from another one does not change until it runs ``chartbook update``.
  Before a pin, interactively, a read pins on first use, reads the newest
  snapshot of a pipeline not declared, or reads a working folder when there
  is no snapshot, each with what it did said; a batch run refuses all but
  the pin, and a script in no pipeline reads the newest snapshot quietly
  (see :func:`_read_in_a_pipeline`);
- a **catalog** reference — a pipeline plus a dataframe name — read by the
  same rules, with the catalog's folder as the working version.

The rest of the grammar (``#part``, ``@rev``, a registry prefix) is
recognized and refused as not yet supported. See
``docs_src/design/references.md``.

Finding *a pipeline* by name is here too, in :func:`locate_pipeline`: the
one resolution chain, which asks the ``[dependencies]`` of the pipeline
that wants to know, then the catalog. ``chartbook check``, the index, the
catalog lookups and cross-pipeline references all go through it.
"""

from __future__ import annotations

import dataclasses
import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterable, Mapping, Optional, Union

import tomli

from chartbook.config import get_default_catalog_path, get_global_settings_path
from chartbook.errors import (
    AssetNotDeclaredError,
    AssetNotPinnedError,
    CatalogNotConfiguredError,
    DependencyNotDeclaredError,
    ManifestNotFoundError,
    VersionNotFoundError,
)
from chartbook.identity import (
    UnsupportedRegistryError,
    UnsupportedRevisionError,
    in_another_case,
    match_pipeline_ref,
)
from chartbook.refs import DEFAULT_KIND, KIND_TABLES, AssetRef, parse_asset_ref

MANIFEST_NAME = "chartbook.toml"

#: The kinds of asset a manifest can declare, and so the kinds that resolve.
RESOLVABLE_KINDS = ("dataframe", "chart", "notebook", "note", "model")

#: The manifest tables those kinds are declared in. Each table is its own
#: namespace: ``[dataframes.gdp]`` and ``[charts.gdp]`` are two assets,
#: ``gdp`` and ``chart/gdp``.
ASSET_TABLES = tuple(KIND_TABLES[kind] for kind in RESOLVABLE_KINDS)

#: An example ``path`` per table, used when telling someone what to add.
_EXAMPLE_PATHS = {
    "dataframes": "./_data/{name}.parquet",
    "charts": "./_output/{name}.html",
    "notebooks": "./_output/{name}.ipynb",
    "notes": "./docs_src/{name}.md",
    "models": "./_models/{name}.joblib",
}


class UnsupportedReferenceError(ValueError):
    """Raised for reference syntax that is reserved but not yet supported.

    Cross-pipeline references (``pipeline:asset``) and parts
    (``asset#part``) are part of the reference grammar and will resolve
    once the asset graph is implemented.
    """


class Location:
    """Where a declared asset lives. Each subclass is one ``kind``."""

    kind: ClassVar[str]


@dataclass(frozen=True)
class FileLocation(Location):
    """An asset stored as a file, or as a glob of files.

    Attributes:
        path: Absolute path. For partitioned data it contains glob
            characters. The file need not exist: a path can be asked for
            before anything has written to it.
    """

    kind: ClassVar[str] = "file"

    path: Path


@dataclass(frozen=True)
class TableLocation(Location):
    """A dataframe that is a table or view in a source.

    Attributes:
        source: The source's name in ``[sources]``.
        backend: The source's backend, ``duckdb``.
        url: The source's URL, public part only, with a relative DuckDB
            file made absolute.
        identifier: The table, as declared: one to three dot-separated parts.
    """

    kind: ClassVar[str] = "table"

    source: str
    backend: str
    url: str
    identifier: str


@dataclass(frozen=True)
class QueryLocation(Location):
    """A dataframe that is a query run in a source: a view ChartBook names.

    Attributes:
        source, backend, url: As for :class:`TableLocation`.
        sql: The query, in the source's dialect, as declared.
    """

    kind: ClassVar[str] = "query"

    source: str
    backend: str
    url: str
    sql: str


@dataclass(frozen=True)
class PipelineLocation:
    """Where a pipeline's source is, and which step of the chain said so.

    Attributes:
        id: The name the pipeline goes by where it was found: its key in
            ``[dependencies]``, or its key in the catalog.
        found_in: ``"dependencies"`` or ``"catalog"``.
        kind: ``"path"``, a directory on this machine, ``"git"``, a
            repository that has to be fetched, or ``"store"``, a pipeline
            named by its ID alone, whose snapshots are in the store.
        path: The pipeline's directory, when *kind* is ``"path"``. Absolute;
            nothing has checked that it exists.
        url: The repository, when *kind* is ``"git"``.
        rev: The revision of it to fetch, if the manifest names one.
        pipeline: The pipeline's own ID, when *kind* is ``"store"``.
    """

    id: str
    found_in: str
    kind: str
    path: Optional[Path] = None
    url: Optional[str] = None
    rev: Optional[str] = None
    pipeline: Optional[str] = None


class PipelineNotFoundError(KeyError):
    """Raised when no step of the resolution chain knows a pipeline.

    Attributes:
        pipeline: The reference that was looked up.
        candidates: The pipelines each step that was asked does know, by
            step: ``"dependencies"`` and ``"catalog"``. A step the caller
            had nothing for is not in it.
    """

    def __init__(self, pipeline: str, candidates: dict[str, list[str]]):
        self.pipeline = pipeline
        self.candidates = candidates
        labels = {
            "dependencies": "Declared in [dependencies]",
            "catalog": "In the catalog",
        }
        known = [name for names in candidates.values() for name in names]
        other = in_another_case(known, pipeline)
        close = [other] if other else difflib.get_close_matches(pipeline, known, n=1)
        parts = [f"Pipeline {pipeline!r} not found."]
        if close:
            parts.append(f"Did you mean {close[0]!r}?")
        if other:
            parts.append("A scope derived from a remote is in lowercase.")
        parts += [
            f"{labels[step]}: {', '.join(names) or '(none)'}."
            for step, names in candidates.items()
        ]
        super().__init__(" ".join(parts))

    def __str__(self) -> str:
        # KeyError shows its message as a quoted string
        return self.args[0]


def locate_pipeline(
    pipeline: str,
    *,
    dependencies: Optional[Mapping[str, dict]] = None,
    catalog: Optional[Mapping[str, Union[str, Path]]] = None,
) -> PipelineLocation:
    """Find where a pipeline is. This is the one resolution chain.

    Each place a pipeline's location can come from is asked in turn, and
    the first that knows the name answers:

    1. ``[dependencies]`` of the pipeline that is asking: an explicit
       location, written down by the project that needs it.
    2. The local catalog.
    3. *(Reserved)* configured registries. Nothing is asked today.
    4. Otherwise an error that lists what steps 1 and 2 do know.

    At each step the name is matched as a catalog matches one
    (:func:`chartbook.identity.match_pipeline_ref`): a scoped ID exactly,
    a bare name if exactly one entry has it, a URL by the ID it reduces to.
    A bare name that fits two entries of one step is an error there; it
    does not fall through to the next step to be guessed at.

    Nothing on disk is looked at. The caller gathers the two tables, and
    what comes back is where the pipeline is said to be, whether or not it
    is there.

    :param pipeline: A reference to a pipeline: bare name, scoped ID or URL.
    :param dependencies: The asking pipeline's ``[dependencies]``, as
        :func:`chartbook.manifest.validate_dependencies` returns it.
    :param catalog: The catalog's pipelines: each key and its directory.
    :returns: Where the pipeline is.
    :raises PipelineNotFoundError: If no step knows it. A ``KeyError``.
    :raises KeyError: If a bare name is ambiguous within one step.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If it carries a registry prefix.
    """
    # Only the steps the caller has are asked, and only they are named in
    # the error: a catalog lookup has no [dependencies] to speak of
    asked = {
        step: sorted(table)
        for step, table in (("dependencies", dependencies), ("catalog", catalog))
        if table is not None
    }
    dependencies = dependencies or {}
    catalog = catalog or {}

    # 1. An explicit location in [dependencies]
    key = match_pipeline_ref(dependencies, pipeline, where="[dependencies]")
    if key is None:
        # Named by its ID under a shorter key: `rates = { id = "acme/rates" }`
        named = [k for k, entry in dependencies.items() if isinstance(entry, dict) and entry.get("_store") == pipeline]
        if len(named) == 1:
            key = named[0]
    if key is not None:
        entry = dependencies[key]
        if entry.get("_store"):
            return PipelineLocation(id=key, found_in="dependencies", kind="store", pipeline=entry["_store"])
        if "git" in entry:
            return PipelineLocation(
                id=key,
                found_in="dependencies",
                kind="git",
                url=entry["git"],
                rev=entry.get("rev"),
            )
        return PipelineLocation(
            id=key,
            found_in="dependencies",
            kind="path",
            path=Path(entry["_resolved_path"]),
        )

    # 2. The local catalog
    key = match_pipeline_ref(catalog, pipeline, where="the catalog")
    if key is not None:
        return PipelineLocation(
            id=key, found_in="catalog", kind="path", path=Path(catalog[key])
        )

    # 3. Configured registries. Reserved: a registry-qualified reference is
    #    refused above, and there is nothing to ask about any other.

    # 4. Nothing knows it
    raise PipelineNotFoundError(pipeline, asked)


def known_as(
    location: PipelineLocation, pipelines: Mapping[str, Union[str, Path]]
) -> str:
    """The ID a located pipeline has among the pipelines of one build.

    A dependency's key is a local name: one pipeline may call
    ``../fed_yield_curve`` ``yield_curve`` while the catalog it is built in
    calls the same directory ``ftsfr/fed_yield_curve``. Within a build the
    catalog's name is the one every record uses, so a located pipeline that
    is one of the build's own is known by the build's ID for it. One that is
    not keeps the name it was found under.

    :param location: A pipeline, from :func:`locate_pipeline`.
    :param pipelines: The pipelines of the build: each ID and its directory.
    """
    if location.path is not None:
        for pipeline_id, directory in pipelines.items():
            if _same_directory(location.path, directory):
                return pipeline_id
    if location.pipeline is not None and location.pipeline in pipelines:
        # Named by its ID alone, and that ID is one of the build's pipelines
        return location.pipeline
    return location.id


def locate_in_catalog(catalog_manifest: dict, pipeline: str) -> str:
    """Find a pipeline in a loaded catalog, and return its key there.

    For callers that name a catalog outright, as ``data.load(pipeline=...,
    dataframe=...)`` does. They enter the chain at its second step: there
    is no asking pipeline, so no ``[dependencies]`` to look in first.

    :param catalog_manifest: A catalog, from
        :func:`chartbook.manifest.load_manifest`.
    :param pipeline: A reference to a pipeline: bare name, scoped ID or URL.
    :raises KeyError: If the catalog has no such pipeline, or a bare name
        is ambiguous in it.
    """
    pipelines = catalog_manifest.get("pipelines", {})
    catalog = {key: entry["pipeline_base_dir"] for key, entry in pipelines.items()}
    try:
        return locate_pipeline(pipeline, catalog=catalog).id
    except KeyError:
        # A pipeline the catalog names with no folder here: say so, not "no such pipeline"
        named = [
            key for key in catalog_manifest.get("store_pipelines") or []
            if pipeline in (key, key.rsplit("/", 1)[-1])
        ]
        if named:
            raise KeyError(
                f"The catalog names {named[0]!r}, but it has no folder on this machine: the "
                f"catalog only shows its snapshots in the store. To read its data here, add its "
                f"folder to the catalog (chartbook catalog add), or read it from a pipeline that "
                f"declares it in [dependencies] and pins it."
            ) from None
        raise


def _same_directory(first: Union[str, Path], second: Union[str, Path]) -> bool:
    """Whether two paths are one directory; by name if either is not there."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return Path(first) == Path(second)


def resolve_catalog_path(catalog_path: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the catalog path from an explicit argument or global settings.

    Priority:
    1. Explicit *catalog_path* argument
    2. Global settings (``~/.chartbook/settings.toml``)
    3. Raise :class:`CatalogNotConfiguredError`

    :param catalog_path: Explicit path to a catalog ``chartbook.toml`` or its parent directory.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: Resolved path to the catalog's ``chartbook.toml``.
    :rtype: Path
    :raises CatalogNotConfiguredError: If no catalog is configured.
    """
    if catalog_path is not None:
        catalog_path = Path(catalog_path)
        if catalog_path.is_dir():
            catalog_path = catalog_path / MANIFEST_NAME
        return catalog_path.resolve()

    default_path = get_default_catalog_path()
    if default_path is not None:
        return default_path

    raise CatalogNotConfiguredError(get_global_settings_path())


def find_manifest_dir(*starts: Union[str, Path]) -> Path:
    """Find the directory of the enclosing ``chartbook.toml``.

    Walks up from each starting directory in turn, the way git and cargo
    find their roots, and returns the first directory that holds a
    ``chartbook.toml``.

    :param starts: Directories to walk up from, in order of preference.
        Defaults to the current working directory.
    :returns: The absolute directory containing ``chartbook.toml``.
    :raises ManifestNotFoundError: If no starting point is enclosed by one.
    """
    start_dirs = [Path(s).resolve() for s in starts] or [Path.cwd().resolve()]
    for start in start_dirs:
        for directory in (start, *start.parents):
            if (directory / MANIFEST_NAME).is_file():
                return directory
    raise ManifestNotFoundError(start_dirs)


# Parsed manifests keyed by path, with the (mtime, size) they were read at. A
# dodo.py typically calls path() once per target, so one file is otherwise
# parsed dozens of times in a single evaluation.
_raw_manifest_cache: dict[Path, tuple[tuple[int, int], dict]] = {}


def _read_raw_manifest(manifest_path: Path) -> dict:
    """Parse a chartbook.toml, reusing the last parse while the file is unchanged."""
    stat = manifest_path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _raw_manifest_cache.get(manifest_path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    with open(manifest_path, "rb") as f:
        raw = tomli.load(f)
    _raw_manifest_cache[manifest_path] = (stamp, raw)
    return raw


def declared_assets(manifest_dir: Union[str, Path]) -> dict[str, list[str]]:
    """The names of the assets a pipeline declares, by manifest table.

    Read from the raw ``chartbook.toml`` and nothing else, as a local
    reference is resolved.

    :param manifest_dir: The pipeline's directory.
    :returns: The keys of each table in :data:`ASSET_TABLES`, sorted.
    :raises OSError: If there is no ``chartbook.toml`` there to read.
    :raises ValueError: If it is not valid TOML.
    """
    raw = _read_raw_manifest(Path(manifest_dir) / MANIFEST_NAME)
    return {table: sorted(raw.get(table) or {}) for table in ASSET_TABLES}


def declared_files(
    manifest_dir: Union[str, Path],
) -> list[tuple[AssetRef, str, Path]]:
    """Every asset a pipeline declares with a ``path``, and where that is.

    Read from the raw ``chartbook.toml`` and nothing else. An entry with no
    ``path``, or whose key cannot be written in a reference, is left out.

    :param manifest_dir: The pipeline's directory.
    :returns: For each asset, in the order of :data:`ASSET_TABLES` and then
        by name: its local reference, its ``path`` as declared, and that
        path made absolute.
    :raises OSError: If there is no ``chartbook.toml`` there to read.
    :raises ValueError: If it is not valid TOML.
    """
    manifest_dir = Path(manifest_dir)
    raw = _read_raw_manifest(manifest_dir / MANIFEST_NAME)
    found = []
    for kind in RESOLVABLE_KINDS:
        entries = raw.get(KIND_TABLES[kind]) or {}
        for name in sorted(entries):
            entry = entries[name]
            declared = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(declared, str) or not declared.strip():
                continue
            try:
                ref = AssetRef(kind=kind, name=name)
            except ValueError:
                continue  # a key that is not an address has no reference
            # Joined lexically, as a local reference is resolved
            absolute = Path(os.path.normpath(manifest_dir / declared))
            found.append((ref, declared, absolute))
    return found


def declared_in_source(manifest_dir: Union[str, Path]) -> list[tuple[AssetRef, dict]]:
    """Every dataframe a pipeline declares as a table or a query in a source.

    Read from the raw ``chartbook.toml`` and nothing else, as
    :func:`declared_files` is; a key that cannot be written in a reference
    is left out.
    """
    raw = _read_raw_manifest(Path(manifest_dir) / MANIFEST_NAME)
    found = []
    for name in sorted(raw.get("dataframes") or {}):
        entry = (raw.get("dataframes") or {})[name]
        if not isinstance(entry, dict) or not (entry.get("table") or entry.get("query")):
            continue
        try:
            found.append((AssetRef(kind="dataframe", name=name), entry))
        except ValueError:
            continue
    return found


def parse_declared_ref(
    ref: Union[str, AssetRef], kind: Optional[str] = None, resolving: bool = False
) -> AssetRef:
    """Parse a reference of a form that is supported today.

    That is an asset of this pipeline or of another one: ``name``,
    ``kind/name``, ``pipeline:name`` or ``scope/pipeline:name``. It is what
    a manifest may state and what :func:`resolve` resolves, and the two
    differ in what else they take.

    A registry is refused as reserved either way, so the message can say
    "not yet" where the syntax is right.

    A revision resolves for a model: a version of one of this pipeline's
    own, ``model/x@7f3a9c2e41b0`` or ``model/x@champion``, or of a
    dependency's, ``other:model/x@champion``, which the lockfile pins. A
    manifest does not state one.

    A part, ``dataframe#series``, is the address of one column. In a
    manifest it would say which column something was made from, and that
    is refused as not yet supported. When *resolving*, it is refused for
    good: the address is for documenting the column, it has no file of its
    own, and ChartBook does not select columns (decided by the maintainer,
    2026-10-13; ``docs_src/design/overview.md``, step 4).

    :param ref: The reference.
    :param kind: The kind the caller expects; see
        :func:`chartbook.refs.parse_asset_ref`.
    :param resolving: Whether the reference is being resolved to where
        an asset is, as :func:`resolve` does, and not stated in a manifest.
    :returns: The parsed reference.
    :raises UnsupportedRevisionError: If the reference carries an ``@rev``
        that does not resolve.
    :raises UnsupportedRegistryError: If it carries a registry prefix.
    :raises UnsupportedReferenceError: If it names a part.
    :raises ValueError: If it does not follow the grammar, or names a kind
        other than *kind*.
    """
    asset = parse_asset_ref(ref, kind=kind)
    if asset.rev is not None:
        without = dataclasses.replace(asset, rev=None)
        if not resolving:
            raise UnsupportedRevisionError(
                f"Reference {str(asset)!r} pins a revision with '@rev'. Version "
                f"pinning is reserved syntax and not yet supported; use "
                f"{str(without)!r} instead."
            )
        if asset.kind != "model":
            raise UnsupportedRevisionError(
                f"Reference {str(asset)!r} names a version of a {asset.kind}. "
                f"Versions are kept for models only so far; use "
                f"{str(without)!r} instead."
            )
    if asset.part is not None:
        without = dataclasses.replace(asset, part=None)
        if not resolving:
            # Said in a manifest, a part is a statement about lineage: which
            # column, or which file. That may come; it loads nothing.
            raise UnsupportedReferenceError(
                f"Reference {str(asset)!r} addresses a part of an asset with '#'. "
                f"Parts are reserved syntax and not yet supported; use "
                f"{str(without)!r} to get the {asset.kind} that holds it."
            )
        if asset.kind == "dataframe":
            # Decided: ChartBook says where a dataframe is. It is not a
            # language for picking columns out of one.
            raise UnsupportedReferenceError(
                f"Reference {str(asset)!r} names one column of a dataframe. "
                f"That address is for documenting the column; it has no file "
                f"of its own, and ChartBook does not select columns. Use "
                f"{str(without)!r} to get the dataframe, and pick the column "
                f"with polars or SQL."
            )
        if asset.kind == "model":
            raise UnsupportedReferenceError(
                f"Reference {str(asset)!r} names a file inside a model. Use "
                f"{str(without)!r} to get the model's path, and join "
                f"{asset.part!r} to it."
            )
        raise UnsupportedReferenceError(
            f"Reference {str(asset)!r} addresses a part of a {asset.kind} with "
            f"'#'. A {asset.kind} has no parts; use {str(without)!r}."
        )
    if asset.registry is not None:
        without = dataclasses.replace(asset, registry=None)
        raise UnsupportedRegistryError(
            f"Reference {str(asset)!r} is qualified with the registry "
            f"{asset.registry!r}. Registry prefixes are reserved syntax and "
            f"not yet supported; use {str(without)!r} instead."
        )
    if asset.kind not in RESOLVABLE_KINDS:
        raise UnsupportedReferenceError(
            f"Reference {str(asset)!r} names a {asset.kind}. Assets of that "
            f"kind are reserved syntax and not yet supported: a "
            f"{MANIFEST_NAME} cannot declare one yet. The kinds that resolve "
            f"are: {', '.join(RESOLVABLE_KINDS)}."
        )
    return asset


# Lockfiles keyed by path, with the (mtime, size) they were read at, for the
# same reason raw manifests are remembered: a dodo.py asks for many paths.
_lock_cache: dict[Path, tuple[tuple[int, int], object]] = {}


def _read_lock(manifest_dir: Path):
    """A pipeline's lockfile, reusing the last read while the file is unchanged.

    :returns: The :class:`chartbook.lock.Lock`, or None if there is no file.
        It is shared between calls and must not be changed.
    """
    from chartbook import lock

    path = manifest_dir / lock.LOCK_FILE
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _lock_cache.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    locked = lock.read_lock(path)
    _lock_cache[path] = (stamp, locked)
    return locked


def _catalog_hint(pipeline: str, manifest_dir: Path) -> Optional[tuple[str, str]]:
    """Where the user's catalog says an undeclared pipeline is, if it says.

    This is the second step of the chain, used only to make an error more
    useful: a pipeline found in the catalog and not in ``[dependencies]`` is
    still not one this pipeline may read from.

    :returns: The catalog's key for it and its directory relative to
        *manifest_dir*, or None.
    """
    from chartbook.manifest import get_pipeline_dirs, load_manifest

    try:
        catalog = load_manifest(base_dir=resolve_catalog_path().parent)
        found = locate_pipeline(pipeline, catalog=get_pipeline_dirs(catalog))
        return found.id, Path(os.path.relpath(found.path, manifest_dir)).as_posix()
    except Exception:  # noqa: BLE001 - a hint is never worth failing for
        return None


def _resolve_pinned(asset: AssetRef, manifest_dir: Path) -> Location:
    """Resolve a reference to another pipeline's asset, to its pinned copy.

    The pipeline must be one ``[dependencies]`` declares. The asset is then
    looked up in ``chartbook.lock``, and its content hash in the store.
    Nothing is hashed and nothing outside the manifest, the lockfile and
    the store is looked at, so this is as cheap as a local reference.
    """
    from chartbook import hashing
    from chartbook.manifest import validate_dependencies
    from chartbook.store import default_store
    from chartbook.utils import is_glob_pattern

    manifest_path = manifest_dir / MANIFEST_NAME
    raw = _read_raw_manifest(manifest_path)
    try:
        dependencies = validate_dependencies(raw.get("dependencies") or {}, manifest_dir)
    except ValueError as error:
        raise type(error)(f"{manifest_path}: {error}") from None

    try:
        dependency = locate_pipeline(asset.pipeline_id, dependencies=dependencies)
    except PipelineNotFoundError:
        raise DependencyNotDeclaredError(
            str(asset),
            asset.pipeline_id,
            manifest_path,
            sorted(dependencies),
            found_at=_catalog_hint(asset.pipeline_id, manifest_dir),
        ) from None

    if dependency.kind == "path" and dependency.path is not None and _same_directory(dependency.path, manifest_dir):
        raise AssetNotPinnedError(
            str(asset), "no_snapshot",
            f"{dependency.id!r} is {manifest_dir}, this pipeline itself: a pipeline cannot depend on itself. "
            f"Read its own assets by their own names.",
        )

    # The lockfile knows the pipeline by its key in [dependencies]
    pinned = asset.in_pipeline(dependency.id)
    asset_id = str(pinned)
    locked = _read_lock(manifest_dir)
    of_dependency = locked.assets_of(dependency.id) if locked else {}
    if of_dependency and dependency.kind == "store":
        listed = next((e for e in locked.dependencies if e.get("id") == dependency.id), {})
        pinned_as = (listed.get("location") or {}).get("pipeline")
        if pinned_as and pinned_as != dependency.pipeline:
            # The entry names another pipeline now; its pin is still the old one's
            _warn(
                UserWarning(
                    f"{dependency.id!r} is pinned as {pinned_as}, and [dependencies] now names "
                    f"{dependency.pipeline}: reading {pinned_as}'s pinned copy until "
                    f"`chartbook update {dependency.id}` follows it."
                )
            )
    if not of_dependency:
        raise AssetNotPinnedError(
            asset_id,
            "no_lockfile",
            f"{asset_id!r} is not pinned: {manifest_dir / 'chartbook.lock'} "
            f"{'does not list' if locked else 'does not exist, so nothing lists'} "
            f"the dependency {dependency.id!r}. Run `chartbook pin` in "
            f"{manifest_dir}. A reference to another pipeline's asset resolves "
            f"to its pinned copy, not to that pipeline's working directory.",
        )
    record = of_dependency.get(asset_id)
    if record is None and pinned.rev is not None:
        return _resolve_pinned_version(pinned, dependency, of_dependency, locked, manifest_dir)
    if record is None:
        in_source = pinned.kind == "dataframe" and _declared_in_source(dependency, pinned.name)
        if in_source:
            raise AssetNotPinnedError(
                asset_id,
                "in_source",
                f"{asset_id!r} is a {in_source} in a source of the pipeline "
                f"{dependency.id!r}, and the snapshot that is pinned was made before "
                f"it was declared, or before tables were written out as parquet. "
                f"`chartbook snapshot` in that pipeline's folder writes it out; then "
                f"`chartbook update` in {manifest_dir} pins it.",
            )
        same_kind = sorted(
            AssetRef.from_dict(other["ref"]).name
            for other in of_dependency.values()
            if other.get("ref", {}).get("kind") == pinned.kind
        )
        close = difflib.get_close_matches(pinned.name, same_kind, n=1)
        raise AssetNotPinnedError(
            asset_id,
            "not_in_lockfile",
            f"The pipeline {dependency.id!r} had no {pinned.kind} named "
            f"{pinned.name!r} when it was pinned."
            f"{f' Did you mean {close[0]!r}?' if close else ''} Its "
            f"{KIND_TABLES[pinned.kind]} in {manifest_dir / 'chartbook.lock'} "
            f"are: {', '.join(same_kind) or '(none)'}. If it has declared "
            f"one since, `chartbook update` pins it.",
        )
    content_hash = record.get("content_hash")
    if not content_hash and record.get("label"):
        from chartbook.lock import label_remedy

        remedy = label_remedy(record.get("missing"), dependency.id)
        raise AssetNotPinnedError(
            asset_id,
            "not_built",
            f"{asset_id!r} was pinned without its bytes: "
            f"{record.get('missing') or 'the store could not supply the version the label names'}. "
            f"{remedy[0].upper()}{remedy[1:]}, in {manifest_dir}.",
        )
    if not content_hash and record["location"].get("kind") in ("table", "query"):
        raise AssetNotPinnedError(
            asset_id,
            "not_built",
            f"{asset_id!r} is a {record['location']['kind']} in a source of the pipeline "
            f"{dependency.id!r} and has no pinned copy: a pin from a repository takes no table, "
            f"and a snapshot writes one out only from a DuckDB file (`chartbook snapshot` "
            f"there says what it could not). `chartbook snapshot` in that pipeline's folder, "
            f"then `chartbook update` in {manifest_dir}, pins it.",
        )
    if not content_hash:
        raise AssetNotPinnedError(
            asset_id,
            "not_built",
            f"{asset_id!r} is not pinned: the pipeline {dependency.id!r} "
            f"declares it, and had not built it when it was pinned. Build it "
            f"there and declare the build ready (`chartbook snapshot` in its "
            f"folder; for a git repository, `chartbook run` here). Then "
            f"`chartbook update` in {manifest_dir} pins it.",
        )
    store = default_store()
    if not store.has(content_hash):
        raise AssetNotPinnedError(
            asset_id,
            "not_in_store",
            f"{asset_id!r} is pinned at {content_hash}, and the store at "
            f"{store} does not have it. In a store shared through a synced folder, "
            f"the likeliest cause is a sync that has not finished: wait for it, and "
            f"read again. Otherwise run `chartbook pin` in {manifest_dir}: it puts it "
            f"back if it can, and says what to do if it cannot.",
        )

    return _held(store, record)


def _held(store, record: dict) -> Location:
    """Where the store holds an asset, given its record with a content hash."""
    from chartbook import hashing
    from chartbook.snapshot import not_whole
    from chartbook.utils import is_glob_pattern

    held = store.get(record["content_hash"])
    # The names and sizes the record gives, against the files': a store in a
    # synced folder can have a file before the whole of it. Nothing is read
    unsynced = not_whole(store, record)
    if unsynced:
        raise AssetNotPinnedError(record.get("id", record["content_hash"]), "not_synced", f"{record.get('id')!r}: {unsynced}.")
    if record["location"].get("kind") in ("table", "query"):
        # Written out as parquet when the snapshot was made
        from chartbook.snapshot import materialized_name

        return FileLocation(held / materialized_name(record))
    declared_path = record["location"]["path"]
    if is_glob_pattern(declared_path):
        # The files are laid out from the glob's fixed prefix
        tail = Path(declared_path).relative_to(hashing.glob_root(declared_path))
        return FileLocation(held / tail)
    name = Path(declared_path).name
    if "files" in record or not (held / name).is_file():
        return FileLocation(held)  # a directory: the object is the directory
    return FileLocation(held / name)


def _resolve_version(asset: AssetRef, manifest_dir: Path, entry: dict) -> Location:
    """Resolve a version of one of this pipeline's models, to the store.

    ``model/x@7f3a9c2e41b0`` names a version by the start of its content hash.
    ``model/x@champion`` names it by a label, which ``[models.x.aliases]``
    points at a version. A version is made by a snapshot, so it is found in
    this pipeline's snapshots, at any commit of its repository.
    """
    from chartbook import snapshot
    from chartbook.store import default_store

    local = str(dataclasses.replace(asset, rev=None))
    aliases = entry.get("aliases") if isinstance(entry.get("aliases"), dict) else {}
    labels = {name: value for name, value in aliases.items() if isinstance(value, str)}
    label = asset.rev if asset.rev in labels else None
    wanted = labels[label] if label else asset.rev
    algorithm, _, digits = wanted.rpartition(":")
    pointing = f" (the label {label!r} points at it)" if label else ""
    if algorithm and algorithm != "sha256":
        raise VersionNotFoundError(
            local,
            asset.rev,
            "no_such_version",
            f"{str(asset)!r}: a version is named by its sha256 hash, and "
            f"{wanted!r} names a {algorithm} one{pointing}.",
        )

    try:
        versions = snapshot.versions_of(manifest_dir, local)
    except snapshot.SnapshotError as error:
        raise VersionNotFoundError(
            local,
            asset.rev,
            "no_such_version",
            f"{str(asset)!r} names a version, and this pipeline has none: "
            f"{error}. A version is made by a snapshot.",
        ) from None
    records = {content_hash: taken.assets[local] for content_hash, taken in versions}
    hashes = list(records)
    known = ", ".join(snapshot.version_name(h, hashes) for h in hashes) or "(none)"

    if not all(c in "0123456789abcdef" for c in digits) or len(digits) < 4:
        raise VersionNotFoundError(
            local,
            asset.rev,
            "no_such_version",
            f"{str(asset)!r}: {asset.rev!r} is not a label of {local} (its labels "
            f"in [models.{asset.name}.aliases] are: "
            f"{', '.join(sorted(labels)) or '(none)'}), and is not the start of a "
            f"version's hash. Its versions on this machine are: {known}.",
        )
    matches = [h for h in hashes if h.split(":", 1)[-1].startswith(digits)]
    if not matches:
        raise VersionNotFoundError(
            local,
            asset.rev,
            "no_such_version",
            f"No version {wanted} of {local} is on this machine{pointing}. Its "
            f"versions here are: {known}. A version is made by a snapshot: "
            f"`chartbook run --snapshot`.",
        )
    if len(matches) > 1:
        raise VersionNotFoundError(
            local,
            asset.rev,
            "ambiguous",
            f"{wanted} is the start of {len(matches)} versions of {local}"
            f"{pointing}: {', '.join(snapshot.version_name(h, hashes) for h in matches)}. "
            f"Give more digits.",
        )
    store = default_store()
    if not store.has(matches[0]):
        raise VersionNotFoundError(
            local,
            asset.rev,
            "not_in_store",
            f"Version {snapshot.version_name(matches[0], hashes)} of {local} was "
            f"made{pointing}, and the store at {store} no longer has its "
            f"bytes.",
        )
    return _held(store, records[matches[0]])


def _resolve_pinned_version(
    pinned: AssetRef, dependency: PipelineLocation, of_dependency: dict, locked, manifest_dir: Path
) -> Location:
    """A version of a dependency's model that the lockfile does not pin by label.

    ``other:model/x@7f3a9c2e41b0`` names a version by the start of its
    hash: it is looked for among the dependency's snapshots in the store,
    by the name the dependency gives itself, which the pinned snapshot
    says. Nothing of the other pipeline's folder is read. A label the
    lockfile does not have is a label the owner had not given when this
    pipeline pinned; ``chartbook update`` pins it.
    """
    from chartbook import snapshot
    from chartbook.store import default_store

    asset_id = str(pinned)
    without = str(dataclasses.replace(pinned, rev=None))
    labels = sorted(
        other["ref"]["rev"]
        for other in of_dependency.values()
        if other.get("ref", {}).get("rev") and other.get("ref", {}).get("name") == pinned.name
        and other.get("ref", {}).get("kind") == pinned.kind
    )
    digits = pinned.rev.split(":", 1)[-1]
    if dependency.kind == "git":
        raise AssetNotPinnedError(
            asset_id,
            "not_in_lockfile",
            f"{dependency.id!r} is a git dependency, and a git dependency has no "
            f"versions: it is pinned from a checkout of its repository, not from a "
            f"snapshot, so no label of its models is pinned and no version of them "
            f"is in the store. {without!r} is its model as pinned.",
        )
    if pinned.kind != "model" or not all(c in "0123456789abcdef" for c in digits) or len(digits) < 4:
        raise AssetNotPinnedError(
            asset_id,
            "not_in_lockfile",
            f"{pinned.rev!r} was not a label of {without} when the pipeline "
            f"{dependency.id!r} was pinned. Its labels then: "
            f"{', '.join(labels) or '(none)'}. If its owner has given the label "
            f"since, and made a snapshot, `chartbook update {dependency.id}` pins it.",
        )
    store = default_store()
    local = str(AssetRef(kind=pinned.kind, name=pinned.name))
    # A version a label of this lockfile pins is at hand whatever has become
    # of the snapshot that made it: the lockfile's root note keeps the bytes
    by_label = [
        other
        for other in of_dependency.values()
        if other.get("ref", {}).get("rev")
        and other.get("ref", {}).get("name") == pinned.name
        and other.get("ref", {}).get("kind") == pinned.kind
        and (other.get("content_hash") or "").split(":", 1)[-1].startswith(digits)
    ]
    if len({other["content_hash"] for other in by_label}) == 1 and store.has(by_label[0]["content_hash"]):
        return _held(store, by_label[0])
    entry = next((e for e in locked.dependencies if e.get("id") == dependency.id), {})
    commit, made_at = entry.get("location", {}).get("commit"), entry.get("snapshot")
    if not (commit and made_at):
        raise AssetNotPinnedError(
            asset_id,
            "not_in_store",
            f"{asset_id!r} names a version by its hash, and the pin of "
            f"{dependency.id!r} in the lockfile names no snapshot, so its "
            f"versions cannot be looked up in the store. `chartbook update "
            f"{dependency.id}` pins it from a snapshot.",
        )
    pinned_snapshot = next(
        (t for t in snapshot.all_snapshots(store) if t.same_moment(commit, made_at)), None
    )
    if pinned_snapshot is None:
        raise AssetNotPinnedError(
            asset_id,
            "not_in_store",
            f"{asset_id!r} names a version by its hash, and the snapshot that "
            f"{dependency.id!r} is pinned to is not in the store, so its versions "
            f"cannot be looked up there. `chartbook update {dependency.id}` pins "
            f"one that is.",
        )
    versions = snapshot.versions_of_pipeline(
        store, pinned_snapshot.pipeline, pinned_snapshot.subdirectory, local
    )
    hashes = [h for h, _ in versions]
    matches = [(h, t) for h, t in versions if h.split(":", 1)[-1].startswith(digits)]
    if not matches:
        known = ", ".join(snapshot.version_name(h, hashes) for h in hashes) or "(none)"
        where = f"{pinned_snapshot.pipeline!r}" + (
            f" at {pinned_snapshot.subdirectory}" if pinned_snapshot.subdirectory else ""
        )
        raise AssetNotPinnedError(
            asset_id,
            "not_in_store",
            f"No snapshot of {where} in the store names a version {pinned.rev} of "
            f"{without}. Its versions there are: {known}. A version is made by a "
            f"snapshot, in its own pipeline; a snapshot `store gc` has cleared no "
            f"longer names one.",
        )
    if len(matches) > 1:
        raise AssetNotPinnedError(
            asset_id,
            "ambiguous",
            f"{pinned.rev} is the start of {len(matches)} versions of {without}: "
            f"{', '.join(snapshot.version_name(h, hashes) for h, _ in matches)}. Give more digits.",
        )
    content_hash, taken = matches[0]
    if not store.has(content_hash):
        raise AssetNotPinnedError(
            asset_id,
            "not_in_store",
            f"Version {pinned.rev} of {without} is named by a snapshot, and its "
            f"bytes are not in the store at {store}.",
        )
    return _held(store, taken.assets[local])


def _declared_in_source(dependency: PipelineLocation, name: str) -> Optional[str]:
    """``"table"`` or ``"query"`` if the dependency's manifest, where it can be
    read on this machine, declares the dataframe in a source; else None."""
    if dependency.path is None:
        return None
    try:
        raw = _read_raw_manifest(Path(dependency.path) / MANIFEST_NAME)
    except (OSError, ValueError):
        return None
    entry = (raw.get("dataframes") or {}).get(name)
    if not isinstance(entry, dict):
        return None
    return "table" if "table" in entry else "query" if "query" in entry else None


def _resolve_local(asset: AssetRef, manifest_dir: Path) -> Location:
    """Resolve a local reference against one pipeline's raw manifest."""
    from chartbook.manifest import resolve_project_type

    name, table = asset.name, asset.table
    manifest_path = manifest_dir / MANIFEST_NAME
    raw = _read_raw_manifest(manifest_path)
    if resolve_project_type(raw, source=str(manifest_path)) == "catalog":
        raise ValueError(
            f"{manifest_path} is a catalog, which declares no assets of its "
            f"own. A local reference resolves against a pipeline's "
            f"{MANIFEST_NAME}; run from inside the pipeline that declares "
            f"{str(asset)!r}."
        )

    # Only the table for the reference's kind is searched. The others are
    # read so that a miss can say what the name is, if it is something else.
    declared = declared_assets(manifest_dir)
    if name not in declared[table]:
        raise AssetNotDeclaredError(
            name,
            manifest_path,
            declared,
            kind=asset.kind,
            example_path=_EXAMPLE_PATHS[table].format(name=name),
        )

    entry = raw[table][name]
    if table == "dataframes" and ("table" in entry or "query" in entry):
        return _resolve_in_source(entry, name, raw, manifest_dir)
    declared_path = entry.get("path")
    if not isinstance(declared_path, str) or not declared_path.strip():
        example = _EXAMPLE_PATHS[table].format(name=name)
        raise ValueError(
            f"[{table}.{name}] in {manifest_path} has no 'path'. Add one, "
            f'e.g. path = "{example}".'
        )
    if asset.rev is not None:
        # A version: what a snapshot kept, not what is in the folder now
        return _resolve_version(asset, manifest_dir, raw[table][name])
    # Joined lexically, not resolved: the declared path is the asset's real
    # location even when something has since linked another file into it.
    return FileLocation(Path(os.path.normpath(manifest_dir / declared_path)))


def _resolve_in_source(entry: dict, name: str, raw: dict, manifest_dir: Path) -> Location:
    """Resolve a dataframe that lives in a source, as its manifest declares."""
    from chartbook.manifest import validate_dataframe_location, validate_sources

    manifest_path = manifest_dir / MANIFEST_NAME
    try:
        sources = validate_sources(raw.get("sources"), manifest_dir)
        kind = validate_dataframe_location(entry, name, sources)
    except ValueError as error:
        raise ValueError(f"{manifest_path}: {error}") from None
    source = sources[entry["source"]]
    if kind == "table":
        return TableLocation(entry["source"], source["backend"], source["_resolved_url"], entry["table"])
    return QueryLocation(entry["source"], source["backend"], source["_resolved_url"], entry["query"])


def _resolve_in_catalog(
    catalog_path: Path, pipeline: str, dataframe: str
) -> Location:
    """Resolve a pipeline's dataframe through a catalog manifest."""
    from chartbook.manifest import load_manifest

    manifest = load_manifest(base_dir=catalog_path.parent)

    pipeline_key = locate_in_catalog(manifest, pipeline)

    pipeline_manifest = manifest["pipelines"][pipeline_key]
    available_dataframes = list(pipeline_manifest.get("dataframes", {}).keys())
    if dataframe not in pipeline_manifest.get("dataframes", {}):
        raise KeyError(
            f"Dataframe {dataframe!r} not found in pipeline {pipeline_key!r}. "
            f"Available dataframes: {available_dataframes}"
        )

    entry = pipeline_manifest["dataframes"][dataframe]
    if entry.get("_location_kind") in ("table", "query"):
        source = entry["_source"]
        if entry["_location_kind"] == "table":
            return TableLocation(entry["source"], source["backend"], source["_resolved_url"], entry["table"])
        return QueryLocation(entry["source"], source["backend"], source["_resolved_url"], entry["query"])
    resolved = entry.get("_resolved_path")
    if resolved is None:
        raise KeyError(
            f"Dataframe {dataframe!r} in pipeline {pipeline_key!r} has no "
            f"'path' set in its chartbook.toml."
        )
    return FileLocation(Path(resolved))


def resolve(
    ref: Union[str, AssetRef],
    *,
    kind: Optional[str] = None,
    pipeline: Optional[str] = None,
    catalog_path: Optional[Union[str, Path]] = None,
    start_dirs: Iterable[Union[str, Path]] = (),
) -> Location:
    """Resolve a reference to the location of the asset it names.

    This is the one resolver. With *pipeline* unset, *ref* is a reference
    in the grammar and resolves against the enclosing ``chartbook.toml``:
    live if it is local, and to the pinned copy if it names another
    pipeline. With *pipeline* set, *ref* is a dataframe of that pipeline
    and resolves through a catalog.

    :param ref: A reference, ``name``, ``kind/name`` or ``pipeline:name``;
        or, with *pipeline*, a dataframe's name.
    :param kind: The kind of asset the caller expects. A reference that
        names no kind takes it; one that names another kind is an error.
        By default a reference that names no kind is a dataframe.
    :param pipeline: A pipeline reference — bare name, scoped ID, or URL —
        to resolve *ref* within, through a catalog.
    :param catalog_path: The catalog to use when *pipeline* is given;
        defaults to the globally configured one.
    :param start_dirs: Directories to walk up from when looking for the
        enclosing manifest of a local reference, in order of preference.
        Defaults to the current working directory.
    :returns: The asset's location.
    :raises ManifestNotFoundError: If a local reference has no enclosing
        ``chartbook.toml``.
    :raises AssetNotDeclaredError: If a local reference names nothing the
        manifest declares, of that kind.
    :raises DependencyNotDeclaredError: If a reference names a pipeline
        that ``[dependencies]`` does not declare.
    :raises AssetNotPinnedError: If another pipeline's asset has no pinned
        copy: there is no pin, or the store does not have its bytes.
    :raises UnsupportedReferenceError: For reserved reference syntax.
    :raises CatalogNotConfiguredError: If a catalog is needed and none is
        configured.
    :raises KeyError: If the pipeline or dataframe is not in the catalog.
    """
    if pipeline is None:
        asset = parse_declared_ref(ref, kind=kind, resolving=True)
        try:
            manifest_dir = find_manifest_dir(*start_dirs)
        except ManifestNotFoundError:
            if asset.is_local:
                raise
            manifest_dir = None
        if asset.is_local:
            return _resolve_local(asset, manifest_dir)
        return _read_another(asset, manifest_dir, _in_a_catalog_folder(catalog_path))
    if kind not in (None, DEFAULT_KIND):
        raise UnsupportedReferenceError(
            f"Only dataframes resolve through a catalog, not a {kind}."
        )
    # Through a catalog: the same read as a reference to the pipeline's
    # dataframe, by the ID its own chartbook.toml gives it. The catalog is
    # where its working version is read from when there is no snapshot to
    # read, with what it says when it has not got it.
    catalog, key, folder, why_not = None, pipeline, None, None
    try:
        catalog = resolve_catalog_path(catalog_path)
        listed = _catalog_manifest(catalog)
        key = locate_in_catalog(listed, pipeline)
        folder = listed["pipelines"][key].get("pipeline_base_dir")
    except (CatalogNotConfiguredError, KeyError, OSError, ValueError) as error:
        why_not = error  # the store may still have it
    try:
        asset = AssetRef(name=str(ref)).in_pipeline((_own_id(Path(folder)) if folder else None) or key)
    except ValueError:
        if why_not is not None:
            raise why_not from None
        raise

    def from_the_catalog(asset: AssetRef, why: str, error: Exception) -> Location:
        if why_not is not None:
            raise why_not from None
        working = Path(folder) if folder else catalog.parent
        _refuse_working_in_a_batch(asset, why, working)
        location = _resolve_in_catalog(catalog, key, str(ref))
        _warn_working(asset, location, working, why)
        return location

    try:
        manifest_dir = find_manifest_dir(*start_dirs)
    except ManifestNotFoundError:
        manifest_dir = None
    return _read_another(asset, manifest_dir, from_the_catalog, folder=folder)


#: Set to ``1`` for a pipeline's ``build`` script under ``chartbook run``,
#: so that a read of another pipeline that nothing would record is refused
#: there, not warned about. CI can set it too.
BATCH_ENV_VAR = "CHARTBOOK_BATCH"


def batch() -> bool:
    """Whether this is a batch run, where every read of another pipeline must be one the lockfile records."""
    return os.environ.get(BATCH_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


class UnrecordedReadWarning(UserWarning):
    """A read of another pipeline that nothing records: it is not in ``[dependencies]``."""


class WorkingVersionWarning(UserWarning):
    """A read of another pipeline's working folder, as it is now, and not of a snapshot."""


def _warn(warning: Warning) -> None:
    """Warn, from the first caller outside ChartBook: the user's line that read."""
    import sys
    import warnings

    package = os.path.normcase(str(Path(__file__).parent)) + os.sep
    level, frame = 2, sys._getframe(1)
    while frame is not None and os.path.normcase(frame.f_code.co_filename).startswith(package):
        frame = frame.f_back
        level += 1
    warnings.warn(warning, stacklevel=level)


def _catalog_manifest(catalog_path: Path) -> dict:
    from chartbook.manifest import load_manifest

    return load_manifest(base_dir=Path(catalog_path).parent)


def _own_id(folder: Path) -> Optional[str]:
    """The ID a pipeline's own chartbook.toml gives it; None if it cannot be read."""
    from chartbook.identity import derive_pipeline_id

    try:
        raw = _read_raw_manifest(Path(folder) / MANIFEST_NAME)
        return derive_pipeline_id(raw.get("project", {}), Path(folder))
    except Exception:  # noqa: BLE001 - no pipeline there, or one that cannot be read
        return None


def _read_another(asset: AssetRef, manifest_dir: Optional[Path], working, folder=None) -> Location:
    """Another pipeline's asset, read from where the caller is: in a pipeline, or not.

    A catalog's folder is no pipeline, so a notebook there reads as one in
    no pipeline does. Through a catalog that lists the caller's own folder,
    the read is a local one. A name that is the caller's own ID, or the end
    of it, reads a dependency only where one is known to be that pipeline
    (a copy may depend on its original under the original's ID); otherwise
    it is refused, and its own assets are read by their own names. Nothing
    is guessed: a dependency whose ID cannot be known here might be it.
    """
    from chartbook.manifest import resolve_project_type

    if manifest_dir is not None:
        raw = _read_raw_manifest(manifest_dir / MANIFEST_NAME)
        if resolve_project_type(raw, source=str(manifest_dir / MANIFEST_NAME)) == "catalog":
            manifest_dir = None
        elif folder is not None and _same_directory(folder, manifest_dir):
            return _resolve_local(AssetRef(kind=asset.kind, name=asset.name, rev=asset.rev), manifest_dir)
        else:
            key = _refuse_this_pipeline_by_name(asset, manifest_dir, raw)
            if key is not None:
                # The dependency found to be the pipeline that name is: read it by its key
                asset = asset.in_pipeline(key)
    if manifest_dir is None:
        return _read_outside_a_pipeline(asset, working)
    return _read_in_a_pipeline(asset, manifest_dir, working)


def _names_this_pipeline(asset: AssetRef, manifest_dir: Path) -> Optional[str]:
    """This pipeline's own ID, if a reference's pipeline is it or the end of it; else None."""
    own, wanted = _own_id(manifest_dir), asset.pipeline_id
    if not own or (wanted != own and ("/" in wanted or own.rsplit("/", 1)[-1] != wanted)):
        return None
    return own


def _this_pipeline_error(asset: AssetRef, manifest_dir: Path, own: str, unknown=()) -> ValueError:
    named = asset.local_name + (f"@{asset.rev}" if asset.rev else "")
    perhaps = (
        f" If you mean {', '.join(unknown)} in [dependencies], whose ID cannot be known here, read it "
        f"by that key (`chartbook pin` may settle which pipeline it is)."
        if unknown else ""
    )
    return ValueError(
        f"{str(asset)!r} names this pipeline, {own}. Read its own assets by their own names "
        f"({named!r}); a dependency by its key in [dependencies].{perhaps}"
    )


def _refuse_this_pipeline_by_name(asset: AssetRef, manifest_dir: Path, raw: dict) -> Optional[str]:
    """Refuse a name that is the caller's own pipeline, unless a dependency is known to be that pipeline.

    :returns: The key of the dependency under another key that the name is,
        if it is one; None otherwise (including a name that is no such
        thing, or a dependency's own key).
    :raises ValueError: If the name is this pipeline's own ID, or the end of
        it, and no dependency is known to be the pipeline it names; or if
        ``[dependencies]`` cannot be read.
    """
    from chartbook.manifest import validate_dependencies

    own = _names_this_pipeline(asset, manifest_dir)
    if own is None:
        return None
    try:
        dependencies = validate_dependencies(raw.get("dependencies") or {}, manifest_dir)
    except ValueError as error:
        raise type(error)(f"{manifest_dir / MANIFEST_NAME}: {error}") from None
    try:
        locate_pipeline(asset.pipeline_id, dependencies=dependencies)
        return None  # a dependency by that key
    except PipelineNotFoundError:
        pass
    key = _declared_as(asset.pipeline_id, manifest_dir)
    if key is not None:
        return key  # a dependency under another key that is that pipeline
    unknown = sorted(name for name, known in _dependency_ids(manifest_dir, dependencies).items() if known is None)
    raise _this_pipeline_error(asset, manifest_dir, own, unknown)


# Snapshot records read from a store, by file, with the (mtime, size) they
# were read at: a notebook that reads another pipeline in a loop reads each
# record once
_snapshot_cache: dict[str, tuple[tuple[int, int], object]] = {}


def _snapshots_in(store) -> list:
    """Every snapshot in a store that can be read, oldest first, each record parsed once while it is unchanged."""
    from chartbook import snapshot

    found = []
    for file in store.all_snapshot_files():
        try:
            stat = os.stat(file)
        except OSError:
            continue
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = _snapshot_cache.get(str(file))
        if cached is None or cached[0] != stamp:
            try:
                cached = (stamp, snapshot.read(file))
            except snapshot.SnapshotError:
                continue
            _snapshot_cache[str(file)] = cached
        found.append(cached[1])
    found.sort(key=lambda taken: (taken.made_at, snapshot._count(taken.path)))
    return found


def _newest_snapshot_of(asset: AssetRef):
    """The asset as the newest snapshot of its pipeline in the store holds it.

    The pipeline is found by its ID, or by a bare name that only one ID in
    the store ends with; the snapshot by the rules of a dependency named by
    its ID (:func:`chartbook.lock._newest_in_store`). A version (``@hash``,
    ``@label``) is found among that repository's snapshots, by the labels
    the newest one records.

    :returns: The location (None if there is none to read); why there is
        none; the snapshot; and whether that is settled, so that the
        pipeline's working folder must not be read instead: the store could
        not be read, a bare name is more than one pipeline's, or the store
        has snapshots of it that none can be taken from.
    """
    from chartbook import lock
    from chartbook.store import default_store

    try:
        store = default_store()
        found = _snapshots_in(store)
    except Exception as error:  # noqa: BLE001 - an unreadable store is a reason, said in the error
        return None, f"the store cannot be read ({error})", None, True
    pipeline_id = asset.pipeline_id
    ids = {taken.pipeline for taken in found}
    if pipeline_id not in ids:
        ending = sorted(i for i in ids if i.rsplit("/", 1)[-1] == pipeline_id)
        if len(ending) > 1:
            return None, f"the store has snapshots of {', '.join(ending)}; name one by its ID", None, True
        if not ending:
            return None, f"the store at {store} has no snapshot of {pipeline_id}", None, False
        pipeline_id = ending[0]
    newest, why, _ = lock._newest_in_store(pipeline_id, None, store, found=found)
    if newest is None:
        return None, why, None, True
    location, why = _held_in(asset, newest, found, store)
    # A snapshot that lacks the asset settles it too: the folder is read
    # only when the store has no snapshot of the pipeline at all
    return location, why, newest, True


def _held_in(asset: AssetRef, newest, found: list, store):
    """The asset, or a version of it (``@hash``, ``@label``), as a snapshot holds it; None, and why, where it does not.

    A version is found among the snapshots of the snapshot's repository, by
    the labels it records, or by four or more digits of its hash.
    """
    from chartbook import snapshot

    name = asset.local_name
    if asset.rev is not None:
        start = (newest.labels.get(name) or {}).get(asset.rev)
        if start is None and not re.fullmatch(r"(sha256:)?[0-9a-f]{4,64}", asset.rev):
            return None, (
                f"{asset.rev!r} is neither a label its newest snapshot, {newest.commit[:7]}, gives {name}, "
                f"nor the start of a version"
            )
        start = (start or asset.rev).split(":", 1)[-1]
        of_it = [t for t in found if t.pipeline == newest.pipeline and t.subdirectory == newest.subdirectory]
        named, unnamed = snapshot.repository_groups(of_it + [newest])
        group = next((g for g in named if any(t is newest for t in g)), []) + unnamed
        held = [
            (content_hash, taken)
            for content_hash, taken in snapshot.versions_of_pipeline(store, newest.pipeline, newest.subdirectory, name, group)
            if content_hash.split(":", 1)[-1].startswith(start)
        ]
        if len(held) != 1:
            return None, (
                f"{'no' if not held else len(held)} version{'s' if len(held) > 1 else ''} of {name} in the store "
                f"{'starts' if len(held) <= 1 else 'start'} with {start}"
            )
        record = held[0][1].assets[name]
    else:
        record = newest.assets.get(name)
    if record is None:
        names = sorted(n for n in newest.assets if "/" not in n) if asset.kind == DEFAULT_KIND else sorted(newest.assets)
        close = difflib.get_close_matches(name, names, n=1)
        return None, (
            f"its newest snapshot, {newest.commit[:7]}, has no {name}"
            f"{f' (did you mean {close[0]!r}?)' if close else ''}; it has {', '.join(names) or 'nothing'}"
        )
    if not record.get("content_hash"):
        return None, f"its newest snapshot, {newest.commit[:7]}, did not build {name}"
    if not store.has(record["content_hash"]):
        return None, f"the store does not have the bytes of {name} from its newest snapshot"
    return _held(store, record), ""


def _refuse_working_in_a_batch(asset: AssetRef, why: str, folder: Path) -> None:
    if batch():
        raise AssetNotPinnedError(
            str(asset),
            "working",
            f"{asset} cannot be read: {why}. A batch run (`chartbook run`, or {BATCH_ENV_VAR}=1) "
            f"does not read another pipeline's working folder, since nothing would record what "
            f"was read. Its owner makes a snapshot with `chartbook snapshot` in {folder}.",
        )


def _warn_working(asset: AssetRef, location: Location, folder: Path, why: str) -> None:
    what = f"{asset.local_name}@{asset.rev} as its working chartbook.toml names it" if asset.rev else "its WORKING version"
    _warn(
        WorkingVersionWarning(
            f"{asset.pipeline_id} has no snapshot to read this from ({why}): reading {what}, "
            f"{getattr(location, 'path', folder)}, as it is right now. Nothing records this read, "
            f"and a build under `chartbook run` refuses it."
        )
    )


def _read_working(asset: AssetRef, folder: Path, why: str) -> Location:
    """Read another pipeline's asset from its working folder, and say so loudly; refused in a batch run."""
    _refuse_working_in_a_batch(asset, why, folder)
    if not (Path(folder) / MANIFEST_NAME).is_file():
        raise AssetNotPinnedError(
            str(asset), "no_snapshot", f"{asset} cannot be read: {why}, and {folder} has no {MANIFEST_NAME}."
        )
    try:
        location = _resolve_local(AssetRef(kind=asset.kind, name=asset.name, rev=asset.rev), Path(folder))
    except AssetNotDeclaredError:
        raise AssetNotPinnedError(
            str(asset),
            "no_snapshot",
            f"{asset} cannot be read: {why}, and its working folder, {folder}, declares no {asset.local_name} either.",
        ) from None
    _warn_working(asset, location, Path(folder), why)
    return location


def _in_a_catalog_folder(catalog_path=None):
    """How a reference reads a pipeline's working version: from the folder a catalog lists it in.

    The folder's own chartbook.toml must give the pipeline's ID (a bare name:
    the end of it), so that a catalog's key never stands for another
    pipeline.

    :returns: A function of the asset, why there is no snapshot to read,
        and the error to raise when no catalog lists a folder of it.
    """
    from chartbook.manifest import get_pipeline_dirs

    def working(asset: AssetRef, why: str, error: Exception) -> Location:
        wanted = asset.pipeline_id
        try:
            folders = get_pipeline_dirs(_catalog_manifest(resolve_catalog_path(catalog_path)))
        except Exception:  # noqa: BLE001 - no catalog: no folder to read
            raise error from None
        found = []
        for folder in folders.values():
            own = _own_id(Path(folder))
            if own and (own == wanted or ("/" not in wanted and own.rsplit("/", 1)[-1] == wanted)):
                found.append(Path(folder))
        if len(found) != 1:
            raise error from None
        return _read_working(asset, found[0], why)

    return working


def _read_outside_a_pipeline(asset: AssetRef, working) -> Location:
    """Another pipeline's asset, read from a script in no pipeline: its newest snapshot, quietly.

    With no ``chartbook.toml`` there is no lineage to record, so nothing is
    said. With no snapshot to read, its working version is read, with the
    working-version warning: that one is about what was read, not about
    lineage.
    """
    location, why, _, settled = _newest_snapshot_of(asset)
    if location is not None:
        return location
    if settled:
        raise AssetNotPinnedError(str(asset), "no_snapshot", f"{asset} cannot be read: {why}.")
    error = AssetNotPinnedError(
        str(asset),
        "no_snapshot",
        f"{asset} cannot be read: {why}. Its owner makes a snapshot with `chartbook snapshot`; on "
        f"another machine, the store must be the one theirs syncs with or shares ([store] url).",
    )
    return working(asset, why, error)


_ids_cache: dict[str, tuple[float, tuple, dict]] = {}


def _dependency_ids(manifest_dir: Path, dependencies: dict) -> dict[str, Optional[str]]:
    """Each dependency's own pipeline ID, where it can be known here; None where it cannot.

    A store entry names it. A folder's chartbook.toml gives it, or, for a
    folder not on this machine, the snapshot the lockfile pinned it from. A
    ``git`` dependency's checkout at its pinned commit gives it, if the git
    cache has it and its manifest names its ID (a checkout's folder is
    named after its commit, so an ID derived from it means nothing).
    Nothing is fetched, and a lockfile that cannot be read identifies
    nothing.
    """
    import time

    def stamp(path: Path):
        try:
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    key = str(manifest_dir)
    stamps = (
        stamp(manifest_dir / MANIFEST_NAME),
        stamp(manifest_dir / "chartbook.lock"),
        # A dependency's folder may be given another ID at any moment
        tuple(
            stamp(Path(entry["_resolved_path"]) / MANIFEST_NAME)
            for _, entry in sorted(dependencies.items())
            if entry.get("_resolved_path")
        ),
    )
    cached = _ids_cache.get(key)
    if cached is not None and cached[1] == stamps and time.monotonic() - cached[0] < _TRY_AGAIN_SECONDS:
        return cached[2]

    from chartbook.gitcache import default_git_cache, local_url
    from chartbook.store import default_store

    listed: Optional[dict] = None
    found: Optional[list] = None

    def lockfile_entry(name: str) -> dict:
        nonlocal listed
        if listed is None:
            try:
                locked = _read_lock(manifest_dir)
            except Exception:  # noqa: BLE001 - a lockfile that cannot be read identifies nothing
                locked = None
            listed = {
                entry.get("id"): entry
                for entry in (locked.dependencies if locked else [])
                if isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("location"), dict)
            }
        return listed.get(name) or {}

    ids: dict[str, Optional[str]] = {}
    for name, entry in dependencies.items():
        own = entry.get("_store") or (_own_id(Path(entry["_resolved_path"])) if entry.get("_resolved_path") else None)
        if own is None and "git" not in entry:
            pinned = lockfile_entry(name)
            commit, made_at = pinned.get("location", {}).get("commit"), pinned.get("snapshot")
            if commit and made_at:
                try:
                    found = found if found is not None else _snapshots_in(default_store())
                except Exception:  # noqa: BLE001 - a store that cannot be read identifies nothing
                    found = []
                own = next((t.pipeline for t in found if t.commit == commit and t.made_at == made_at), None)
        if own is None and "git" in entry:
            commit = lockfile_entry(name).get("location", {}).get("commit")
            checkout = None
            if commit:
                try:
                    checkout = default_git_cache().find(local_url(entry["git"], manifest_dir), commit)
                except Exception:  # noqa: BLE001 - no git cache: not known here
                    checkout = None
            if checkout is not None:
                try:
                    named = (_read_raw_manifest(Path(checkout) / MANIFEST_NAME).get("project") or {}).get("id")
                except Exception:  # noqa: BLE001 - a checkout with no manifest names nothing
                    named = None
                own = named if isinstance(named, str) and named else None
        ids[name] = own
    _ids_cache[key] = (time.monotonic(), stamps, ids)
    return ids


def _declared_as(pipeline_id: str, manifest_dir: Path) -> Optional[str]:
    """The key ``[dependencies]`` declares a pipeline under, when it is not its ID: by the ID it is known to have (:func:`_dependency_ids`)."""
    from chartbook.manifest import validate_dependencies

    dependencies = validate_dependencies(
        _read_raw_manifest(manifest_dir / MANIFEST_NAME).get("dependencies") or {}, manifest_dir
    )
    exact, ending = [], []
    for key, own in _dependency_ids(manifest_dir, dependencies).items():
        if own == pipeline_id:
            exact.append(key)
        elif own and "/" not in pipeline_id and own.rsplit("/", 1)[-1] == pipeline_id:
            ending.append(key)
    chosen = exact or ending
    if len(chosen) > 1:
        raise ValueError(
            f"{pipeline_id!r} is more than one dependency's: {', '.join(sorted(chosen))}. Name it by "
            f"its key in [dependencies]{'' if '/' in pipeline_id else ', or by its scoped ID'}."
        )
    return chosen[0] if chosen else None


def _pinned_now(report, key: str) -> None:
    """Say what a pin on first read pinned, on stderr, as ``uv`` says what it locked."""
    import sys

    if key in report.snapshots and any(e.dependency == key and e.status == "pinned" for e in report.events):
        taken = report.snapshots[key]
        sys.stderr.write(
            f"{key}: pinned to its newest snapshot, {taken.commit[:7]}, made "
            f"{taken.made_at[:16].replace('T', ' ')} UTC ({report.lockfile.name}). "
            f"`chartbook update {key}` moves it.\n"
        )


#: When a read last tried to pin a dependency that had no snapshot, so that
#: a loop of reads does not pin again on every one
_tried: dict[tuple[str, str], tuple[float, int, str, str]] = {}
_TRY_AGAIN_SECONDS = 30


def _read_in_a_pipeline(asset: AssetRef, manifest_dir: Path, working) -> Location:
    """Another pipeline's asset, read from a pipeline: through its lockfile, with the interactive rules.

    - Declared and pinned: the pinned copy.
    - Declared and not pinned, a folder or an ID: pinned now, to its newest
      snapshot, and said (as ``uv`` writes its lockfile on first use). A
      ``git`` dependency is not fetched to read it: ``chartbook pin`` does.
    - Not declared: its newest snapshot, with a warning that nothing records
      the read.
    - No snapshot to read, and a folder of it here (a ``path`` dependency,
      or the catalog lists it): the working version, with a loud warning.

    A dependency declared under a key other than its ID is found by its ID.
    A batch run (:func:`batch`) takes only the first: ``chartbook run`` pins
    before it builds, and the rest would read what no lockfile records.

    :param working: How its working version is read when there is no
        snapshot (:func:`_in_a_catalog_folder`).
    """
    import time

    try:
        return _resolve_pinned(asset, manifest_dir)
    except DependencyNotDeclaredError as error:
        key = _declared_as(asset.pipeline_id, manifest_dir)
        if key is not None:
            return _read_in_a_pipeline(asset.in_pipeline(key), manifest_dir, working)
        own = _names_this_pipeline(asset, manifest_dir)
        if own is not None:
            # Never this pipeline's own snapshot read as another's
            raise _this_pipeline_error(asset, manifest_dir, own) from None
        if batch():
            raise
        location, why, newest, settled = _newest_snapshot_of(asset)
        if location is None:
            if settled:
                raise AssetNotPinnedError(str(asset), "no_snapshot", f"{asset} cannot be read: {why}.") from None
            return working(asset, why, error)
        from chartbook.manifest import validate_dependencies

        unknown = sorted(
            key for key, known in _dependency_ids(
                manifest_dir,
                validate_dependencies(_read_raw_manifest(manifest_dir / MANIFEST_NAME).get("dependencies") or {}, manifest_dir),
            ).items() if known is None
        )
        perhaps = (
            f" If it is {', '.join(unknown)} in [dependencies], whose ID cannot be known here, read it by that key."
            if unknown else ""
        )
        _warn(
            UnrecordedReadWarning(
                f"{asset.pipeline_id} is not known to be a dependency of this pipeline: reading its newest "
                f"snapshot, {newest.commit[:7]}, and recording nothing. `chartbook add "
                f"{newest.pipeline}` declares it; until then a build under `chartbook run` refuses this read.{perhaps}"
            )
        )
        return location
    except AssetNotPinnedError as error:
        if error.reason != "no_lockfile" or batch():
            raise
        not_pinned = error

    from chartbook import lock
    from chartbook.manifest import validate_dependencies
    from chartbook.store import default_store

    dependencies = validate_dependencies(
        _read_raw_manifest(manifest_dir / MANIFEST_NAME).get("dependencies") or {}, manifest_dir
    )
    dependency = locate_pipeline(asset.pipeline_id, dependencies=dependencies)
    if dependency.kind not in ("path", "store"):
        raise not_pinned  # a repository is fetched by `chartbook pin`, never by a read
    entry = dependencies[dependency.id]
    # The pipeline by its own ID, which its snapshots carry, whatever key it is declared under
    if dependency.kind == "store":
        real_id = dependency.pipeline
    else:
        real_id = (_own_id(Path(dependency.path)) if dependency.path else None) or dependency.id
    real = asset.in_pipeline(real_id)
    if (dependency.kind == "store" and real_id == _own_id(manifest_dir)) or (
        dependency.kind == "path" and dependency.path is not None and _same_directory(dependency.path, manifest_dir)
    ):
        # As `chartbook pin` refuses a store one and `chartbook check` a folder one; a copy may
        # depend on its original under the original's ID
        raise AssetNotPinnedError(
            not_pinned.asset, "no_snapshot", f"{dependency.id!r} is this pipeline itself: a pipeline cannot depend on itself."
        )
    store = default_store()
    try:
        found = _snapshots_in(store)
    except Exception as error:  # noqa: BLE001 - an unreadable store: no folder is read for want of it
        raise AssetNotPinnedError(not_pinned.asset, "no_snapshot", f"the store cannot be read ({error}).") from None
    has_snapshots = any(taken.pipeline == real_id for taken in found)

    # Declared, and nothing of it pinned: pin it now, from its newest
    # snapshot. One that could not be is not tried again on every read of a
    # loop, until the store has a snapshot of it.
    memo = (str(manifest_dir), dependency.id)
    tried = _tried.get(memo)
    retry_unwritable = tried is not None and tried[2] == "unwritable" and _writable(manifest_dir)
    if (
        tried is not None
        and not retry_unwritable
        and (not has_snapshots or tried[2] == "unwritable")
        and time.monotonic() - tried[0] < _TRY_AGAIN_SECONDS
    ):
        kind, why = tried[2], tried[3]
    else:
        try:
            report = lock.pin(manifest_dir, only=[dependency.id], clone_missing=False)  # a read never fetches
        except OSError as failure:
            kind, why = "unwritable", str(failure)
        else:
            _pinned_now(report, dependency.id)
            try:
                return _resolve_pinned(asset, manifest_dir)
            except AssetNotPinnedError as error:
                no_snapshot = [e for e in report.problems if e.dependency == dependency.id and e.status == "no_snapshot"]
                # Its newest snapshot is in the store, and not all of it yet: a store in a synced folder
                not_whole = [e for e in report.problems if e.dependency == dependency.id and e.status in ("unsynced", "lost")]
                if error.reason == "no_lockfile" and not_whole:
                    reason = "not_synced" if not_whole[0].status == "unsynced" else "not_in_store"
                    raise AssetNotPinnedError(
                        not_pinned.asset, reason,
                        f"{not_pinned.asset!r} cannot be pinned yet: {not_whole[0].asset}: {not_whole[0].detail}.",
                    ) from None
                if error.reason != "no_lockfile" or not no_snapshot:
                    raise
                kind, why = "no_snapshot", no_snapshot[0].detail or "it has no snapshot"
        _tried[memo] = (time.monotonic(), 0, kind, why)

    if kind == "unwritable":
        # The pipeline's folder cannot be written: read what a pin would take, and say nothing was pinned
        location, newest, reason = _as_a_pin_would_take(real, entry, store, found)
        if location is None and has_snapshots:
            raise AssetNotPinnedError(not_pinned.asset, "no_snapshot", f"{not_pinned.asset!r} cannot be read: {reason or why}.")
        if location is not None:
            _warn(
                UnrecordedReadWarning(
                    f"{dependency.id} could not be pinned ({why}): reading the snapshot a pin would take, "
                    f"{newest.commit[:7]}, and recording nothing."
                )
            )
            return location
    # Nothing a pin could take. Its working version is read only when the
    # store has no snapshot of it at all: one that two repositories claim,
    # one dated ahead, or none at the commit asked for, is not a reason to
    # read a folder.
    clone = ""
    if dependency.kind == "store":
        from chartbook.config import get_default_host
        from chartbook.identity import strip_url_credentials

        # The address pin would clone, if it would: the repository the
        # entry names, or the default host's
        converted = lock.clone_instead(
            entry, _own_id(manifest_dir) or "", None, True, lambda: found, get_default_host(), pinned=False
        )
        if "git" in converted:
            rev = entry.get("rev") or converted.get("rev")
            at = f" at {rev}" if rev else ""
            clone = (
                f" `chartbook pin` gets it from its repository{at}, {strip_url_credentials(converted['git'])} "
                f"({converted['_from']}); a read never fetches."
            )
    if has_snapshots:
        raise AssetNotPinnedError(not_pinned.asset, "no_snapshot", f"{not_pinned.asset!r} cannot be pinned: {why}.{clone}")
    if dependency.kind == "path" and dependency.path is not None:
        return _read_working(asset, Path(dependency.path), why)
    return working(
        real,
        why,
        AssetNotPinnedError(not_pinned.asset, "no_snapshot", f"{not_pinned.asset!r} cannot be pinned: {why}.{clone}"),
    )


def _writable(folder: Path) -> bool:
    """Whether a file can be made in a folder, by making one: a directory's mode says nothing on Windows."""
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".chartbook-", delete=True):
            return True
    except OSError:
        return False


def _as_a_pin_would_take(asset: AssetRef, entry: dict, store, found: list):
    """The asset as the snapshot a pin of this dependency would take holds it, that snapshot, and why there is none."""
    from chartbook import lock, snapshot

    if entry.get("rev"):
        return None, None, f"rev = {entry['rev']!r} is resolved by `chartbook pin`, which asks its repository"
    try:
        if entry.get("_store"):
            newest, why, _ = lock._newest_in_store(
                entry["_store"], entry.get("commit"), store, entry.get("_repository"),
                found=found, named=bool(entry.get("_repository")),
            )
        else:
            newest, _ = snapshot.newest_for(Path(entry["_resolved_path"]), store)
            why = ""
    except snapshot.SnapshotError as error:
        return None, None, str(error)
    if newest is None:
        return None, None, why
    location, why = _held_in(asset, newest, found, store)
    return location, newest, why


def caller_start_dirs(
    project_dir: Optional[Union[str, Path]], caller_frame
) -> list:
    """Where to start looking for the pipeline a call belongs to.

    "Walking up from the caller": the calling file first, so a script run
    from another directory still finds its own pipeline, then the working
    directory for callers with no file (a notebook, a REPL, ``python -c``).
    An explicit *project_dir* replaces both.

    :param project_dir: The directory the caller named, if any.
    :param caller_frame: The stack frame of the code that made the call,
        i.e. ``sys._getframe(1)`` in the public function.
    """
    if project_dir is not None:
        return [project_dir]
    start_dirs = [Path.cwd()]
    caller_file = caller_frame.f_globals.get("__file__")
    if caller_file:
        start_dirs.insert(0, os.path.dirname(os.path.abspath(caller_file)))
    return start_dirs


def require_file(location: Location, what: str) -> Path:
    """Return a file location's path; no other kind of location has one.

    :param location: A resolved location.
    :param what: What it is the location of, to begin the error message.
    :raises TypeError: If the location is not a file.
    """
    if isinstance(location, FileLocation):
        return location.path
    raise TypeError(
        f"{what} is {location.kind}-backed, so it has no file path. "
        f"Use data.load() to read it, data.sql() to query it, or data.ref() "
        f"for its name in SQL."
    )
