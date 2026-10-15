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
  ``chartbook.lock`` to the copy in the store, and never to the other
  pipeline's working directory. So what a pipeline reads from another one
  does not change until it runs ``chartbook update``;
- a **catalog** reference — a pipeline plus a dataframe name — through a
  catalog, as ``data.load(pipeline=..., dataframe=...)`` always has.

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
        kind: ``"path"``, a directory on this machine, or ``"git"``, a
            repository that has to be fetched.
        path: The pipeline's directory, when *kind* is ``"path"``. Absolute;
            nothing has checked that it exists.
        url: The repository, when *kind* is ``"git"``.
        rev: The revision of it to fetch, if the manifest names one.
    """

    id: str
    found_in: str
    kind: str
    path: Optional[Path] = None
    url: Optional[str] = None
    rev: Optional[str] = None


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
        close = difflib.get_close_matches(pipeline, known, n=1)
        parts = [f"Pipeline {pipeline!r} not found."]
        if close:
            parts.append(f"Did you mean {close[0]!r}?")
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
    if key is not None:
        entry = dependencies[key]
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
    return locate_pipeline(pipeline, catalog=catalog).id


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

    # The lockfile knows the pipeline by its key in [dependencies]
    pinned = asset.in_pipeline(dependency.id)
    asset_id = str(pinned)
    locked = _read_lock(manifest_dir)
    of_dependency = locked.assets_of(dependency.id) if locked else {}
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
            f"{dependency.id!r} and has no pinned copy: a pin from a folder takes no table, "
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
            f"{store.root} does not have it. Run `chartbook pin` in "
            f"{manifest_dir}: it puts it back if it can, and says what to do "
            f"if it cannot.",
        )

    return _held(store, record)


def _held(store, record: dict) -> Location:
    """Where the store holds an asset, given its record with a content hash."""
    from chartbook import hashing
    from chartbook.utils import is_glob_pattern

    held = store.object_path(record["content_hash"])
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
            f"made{pointing}, and the store at {store.root} no longer has its "
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
            f"{asset_id!r} names a version by its hash, and {dependency.id!r} is "
            f"pinned from its folder (`--from-folder`), not from a snapshot, so its "
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
            f"bytes are not in the store at {store.root}.",
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
        manifest_dir = find_manifest_dir(*start_dirs)
        if asset.is_local:
            return _resolve_local(asset, manifest_dir)
        return _resolve_pinned(asset, manifest_dir)
    if kind not in (None, DEFAULT_KIND):
        raise UnsupportedReferenceError(
            f"Only dataframes resolve through a catalog, not a {kind}."
        )
    return _resolve_in_catalog(resolve_catalog_path(catalog_path), pipeline, str(ref))


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
