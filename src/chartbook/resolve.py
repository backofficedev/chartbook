"""Name resolution: turn a reference into a typed location.

Everything that maps a name to a place — ``data.path()``, ``data.load()``,
``data.get_data_path()``, ``chartbook path`` — calls :func:`resolve` and
gets back a :class:`Location`. What to do with a location is the caller's
business; looking the name up is not, so there is exactly one place where
names are resolved.

Today a location is always a :class:`FileLocation`. The data-access design
(``docs_src/design/data-access.md``) adds table- and query-backed
dataframes as further kinds, which is why ``load()`` and ``path()`` each
call the resolver rather than one calling the other: a table has no path,
but it can still be loaded.

Two forms of reference resolve today:

- a **local** reference — a bare asset name — against the ``chartbook.toml``
  enclosing the caller. The raw file is read and nothing else, so this is
  cheap, offline, and does not care whether the asset has been built yet;
- a **catalog** reference — a pipeline plus a dataframe name — through a
  catalog, as ``data.load()`` always has.

The rest of the reference grammar (``other_pipeline:asset``, ``#series``,
``@rev``, a registry prefix) is recognized and refused as not yet
supported. See "Paths" in ``docs_src/design/asset-graph.md``.
"""

from __future__ import annotations

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
    ID_COMPONENT_PATTERN,
    UnsupportedRegistryError,
    UnsupportedRevisionError,
    resolve_pipeline_ref,
    split_registry,
    split_rev,
)

MANIFEST_NAME = "chartbook.toml"

#: Manifest tables whose entries are assets with a ``path``. Within one
#: pipeline they share a single namespace: an asset's ID is
#: ``scope/name:asset`` whatever its kind.
ASSET_TABLES = ("dataframes", "charts", "notebooks", "notes")

#: An example ``path`` per table, used when telling someone what to add.
_EXAMPLE_PATHS = {
    "dataframes": "./_data/{name}.parquet",
    "charts": "./_output/{name}.html",
    "notebooks": "./_output/{name}.ipynb",
    "notes": "./docs_src/{name}.md",
}


class UnsupportedReferenceError(ValueError):
    """Raised for reference syntax that is reserved but not yet supported.

    Cross-pipeline references (``pipeline:asset``) and series addresses
    (``asset#series``) are part of the reference grammar and will resolve
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


def parse_local_ref(ref: str) -> str:
    """Validate a reference to an asset of the current pipeline.

    Only a bare asset name is accepted. The rest of the reference grammar,
    ``[registry/]scope/name[:asset[#series]][@rev]``, is recognized so that
    the refusal can say the syntax is reserved rather than merely invalid.

    :param ref: The reference, e.g. ``"treasury_rates"``.
    :returns: The asset name.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If it carries a registry prefix.
    :raises UnsupportedReferenceError: If it names a series or another
        pipeline.
    :raises ValueError: If it is not a valid asset name.
    """
    ref = ref.strip()
    base, rev = split_rev(ref)
    if rev is not None:
        raise UnsupportedRevisionError(
            f"Reference {ref!r} pins a revision with '@rev'. Version pinning "
            f"is reserved syntax and not yet supported; use {base!r} instead."
        )
    if "#" in ref:
        raise UnsupportedReferenceError(
            f"Reference {ref!r} addresses a series with '#'. Series addresses "
            f"are reserved syntax and not yet supported; use "
            f"{ref.split('#', 1)[0]!r} to get the dataframe that holds it."
        )
    registry, unqualified = split_registry(ref)
    if registry is not None:
        raise UnsupportedRegistryError(
            f"Reference {ref!r} is qualified with the registry {registry!r}. "
            f"Registry prefixes are reserved syntax and not yet supported "
            f"(and neither, yet, is the cross-pipeline reference "
            f"{unqualified!r} that remains without it)."
        )
    if ":" in ref or "/" in ref:
        raise UnsupportedReferenceError(
            f"Reference {ref!r} names an asset in another pipeline. "
            f"Cross-pipeline references are reserved syntax and not yet "
            f"supported; only a bare name declared in the current pipeline's "
            f"{MANIFEST_NAME} resolves. To locate a dataframe through a "
            f"catalog, use data.get_data_path(pipeline=..., dataframe=...)."
        )
    if not ID_COMPONENT_PATTERN.match(ref):
        raise ValueError(
            f"Invalid asset name {ref!r}. Expected a name declared in "
            f"{MANIFEST_NAME}, matching [A-Za-z0-9._-]+."
        )
    return ref


def _resolve_local(name: str, manifest_dir: Path, tables: Iterable[str]) -> Location:
    """Resolve a bare asset name against one pipeline's raw manifest."""
    from chartbook.manifest import resolve_project_type

    manifest_path = manifest_dir / MANIFEST_NAME
    raw = _read_raw_manifest(manifest_path)
    if resolve_project_type(raw, source=str(manifest_path)) == "catalog":
        raise ValueError(
            f"{manifest_path} is a catalog, which declares no assets of its "
            f"own. A bare name resolves against a pipeline's {MANIFEST_NAME}; "
            f"run from inside the pipeline that declares {name!r}."
        )

    tables = tuple(tables)
    declared = {table: sorted(raw.get(table) or {}) for table in tables}
    matches = [table for table in tables if name in declared[table]]

    if not matches:
        raise AssetNotDeclaredError(name, manifest_path, declared)
    if len(matches) > 1:
        both = " and ".join(f"[{table}.{name}]" for table in matches)
        raise ValueError(
            f"{name!r} is ambiguous: {manifest_path} declares {both}. Asset "
            f"names share one namespace within a pipeline; rename one of them."
        )

    (table,) = matches
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
    ref: str,
    *,
    pipeline: Optional[str] = None,
    catalog_path: Optional[Union[str, Path]] = None,
    start_dirs: Iterable[Union[str, Path]] = (),
    tables: Iterable[str] = ASSET_TABLES,
) -> Location:
    """Resolve a reference to the location of the asset it names.

    This is the one resolver. With *pipeline* unset, *ref* is a local
    reference and resolves against the enclosing ``chartbook.toml``. With
    *pipeline* set, *ref* is a dataframe of that pipeline and resolves
    through a catalog.

    :param ref: A bare asset name (local), or a dataframe ID (catalog).
    :param pipeline: A pipeline reference — bare name, scoped ID, or URL —
        to resolve *ref* within, through a catalog.
    :param catalog_path: The catalog to use when *pipeline* is given;
        defaults to the globally configured one.
    :param start_dirs: Directories to walk up from when looking for the
        enclosing manifest of a local reference, in order of preference.
        Defaults to the current working directory.
    :param tables: The asset tables a local reference may resolve in.
    :returns: The asset's location.
    :raises ManifestNotFoundError: If a local reference has no enclosing
        ``chartbook.toml``.
    :raises AssetNotDeclaredError: If a local reference names nothing the
        manifest declares.
    :raises UnsupportedReferenceError: For reserved reference syntax.
    :raises CatalogNotConfiguredError: If a catalog is needed and none is
        configured.
    :raises KeyError: If the pipeline or dataframe is not in the catalog.
    """
    if pipeline is None:
        name = parse_local_ref(ref)
        return _resolve_local(name, find_manifest_dir(*start_dirs), tables)
    return _resolve_in_catalog(resolve_catalog_path(catalog_path), pipeline, ref)

