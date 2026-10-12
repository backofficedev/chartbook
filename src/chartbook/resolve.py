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

Two forms of reference resolve today:

- a **local** reference — ``name`` or ``kind/name`` — against the
  ``chartbook.toml`` enclosing the caller. The raw file is read and nothing
  else, so this is cheap, offline, and does not care whether the asset has
  been built yet;
- a **catalog** reference — a pipeline plus a dataframe name — through a
  catalog, as ``data.load()`` always has.

The rest of the grammar (``pipeline:asset``, ``#part``, ``@rev``, a
registry prefix) is recognized and refused as not yet supported. See
``docs_src/design/references.md``.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterable, Optional, Union

import tomli

from chartbook.config import get_default_catalog_path, get_global_settings_path
from chartbook.errors import (
    AssetNotDeclaredError,
    CatalogNotConfiguredError,
    ManifestNotFoundError,
)
from chartbook.identity import (
    UnsupportedRegistryError,
    UnsupportedRevisionError,
    resolve_pipeline_ref,
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


def parse_declared_ref(
    ref: Union[str, AssetRef], kind: Optional[str] = None
) -> AssetRef:
    """Parse a reference that a manifest may *declare* today.

    That is an asset of this pipeline or of another one: ``name``,
    ``kind/name``, ``pipeline:name`` or ``scope/pipeline:name``. A manifest
    can say that a model was trained on another pipeline's dataframe before
    ChartBook can fetch that dataframe; saying so is lineage, and needs no
    resolution. Parts, revisions and registries are still refused, since
    each means something only once there is a store to look in.

    :param ref: The reference.
    :param kind: The kind the caller expects; see
        :func:`chartbook.refs.parse_asset_ref`.
    :returns: The parsed reference.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If it carries a registry prefix.
    :raises UnsupportedReferenceError: If it names a part.
    :raises ValueError: If it does not follow the grammar, or names a kind
        other than *kind*.
    """
    asset = parse_asset_ref(ref, kind=kind)
    if asset.rev is not None:
        without = dataclasses.replace(asset, rev=None)
        raise UnsupportedRevisionError(
            f"Reference {str(asset)!r} pins a revision with '@rev'. Version "
            f"pinning is reserved syntax and not yet supported; use "
            f"{str(without)!r} instead."
        )
    if asset.part is not None:
        without = dataclasses.replace(asset, part=None)
        raise UnsupportedReferenceError(
            f"Reference {str(asset)!r} addresses a part of an asset with '#'. "
            f"Parts are reserved syntax and not yet supported; use "
            f"{str(without)!r} to get the {asset.kind} that holds it."
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


def parse_local_ref(
    ref: Union[str, AssetRef], kind: Optional[str] = None
) -> AssetRef:
    """Parse a reference and check that it is one that *resolves* today.

    That is a local reference, ``name`` or ``kind/name``. Everything else
    the grammar allows is refused as reserved, so the message can say "not
    yet" where the syntax is right.

    :param ref: The reference, e.g. ``"treasury_rates"`` or ``"chart/gdp"``.
    :param kind: The kind the caller expects; see
        :func:`chartbook.refs.parse_asset_ref`.
    :returns: The parsed reference.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If it carries a registry prefix.
    :raises UnsupportedReferenceError: If it names a part or another
        pipeline.
    :raises ValueError: If it does not follow the grammar, or names a kind
        other than *kind*.
    """
    asset = parse_declared_ref(ref, kind=kind)
    if not asset.is_local:
        raise UnsupportedReferenceError(
            f"Reference {str(asset)!r} names an asset in another pipeline. "
            f"Cross-pipeline references are reserved syntax and not yet "
            f"supported; only an asset declared in the current pipeline's "
            f"{MANIFEST_NAME} resolves. To locate a dataframe through a "
            f"catalog, use data.get_data_path(pipeline=..., dataframe=...)."
        )
    return asset


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
    declared = {t: sorted(raw.get(t) or {}) for t in ASSET_TABLES}
    if name not in declared[table]:
        raise AssetNotDeclaredError(
            name,
            manifest_path,
            declared,
            kind=asset.kind,
            example_path=_EXAMPLE_PATHS[table].format(name=name),
        )

    declared_path = raw[table][name].get("path")
    if not isinstance(declared_path, str) or not declared_path.strip():
        example = _EXAMPLE_PATHS[table].format(name=name)
        raise ValueError(
            f"[{table}.{name}] in {manifest_path} has no 'path'. Add one, "
            f'e.g. path = "{example}".'
        )
    # Joined lexically, not resolved: the declared path is the asset's real
    # location even when something has since linked another file into it.
    return FileLocation(Path(os.path.normpath(manifest_dir / declared_path)))


def _resolve_in_catalog(
    catalog_path: Path, pipeline: str, dataframe: str
) -> Location:
    """Resolve a pipeline's dataframe through a catalog manifest."""
    from chartbook.manifest import load_manifest

    manifest = load_manifest(base_dir=catalog_path.parent)

    pipeline_key = resolve_pipeline_ref(manifest.get("pipelines", {}).keys(), pipeline)

    pipeline_manifest = manifest["pipelines"][pipeline_key]
    available_dataframes = list(pipeline_manifest.get("dataframes", {}).keys())
    if dataframe not in pipeline_manifest.get("dataframes", {}):
        raise KeyError(
            f"Dataframe {dataframe!r} not found in pipeline {pipeline_key!r}. "
            f"Available dataframes: {available_dataframes}"
        )

    resolved = pipeline_manifest["dataframes"][dataframe].get("_resolved_path")
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

    This is the one resolver. With *pipeline* unset, *ref* is a local
    reference and resolves against the enclosing ``chartbook.toml``. With
    *pipeline* set, *ref* is a dataframe of that pipeline and resolves
    through a catalog.

    :param ref: A local reference, ``name`` or ``kind/name``; or, with
        *pipeline*, a dataframe's name.
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
    :raises UnsupportedReferenceError: For reserved reference syntax.
    :raises CatalogNotConfiguredError: If a catalog is needed and none is
        configured.
    :raises KeyError: If the pipeline or dataframe is not in the catalog.
    """
    if pipeline is None:
        asset = parse_local_ref(ref, kind=kind)
        return _resolve_local(asset, find_manifest_dir(*start_dirs))
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
        f"Use data.load() to read it."
    )
