"""Data access for chartbook: where dataframes live, and loading them.

This is the front door for **dataframes**. Every function here takes a
dataframe and nothing else; :mod:`chartbook.assets` is the general module,
for charts, notebooks and notes as well.

Ask the manifest where a dataframe of the current pipeline belongs, instead
of repeating its path in code::

    from chartbook import data

    # The path declared for [dataframes.repo_public] in the enclosing
    # chartbook.toml; works before the file exists, so it can name a target
    df.to_parquet(data.path("repo_public"))

    # A throwaway directory for intermediates: _data/_scratch/ in the pipeline
    raw.to_csv(data.scratch() / "raw_download.csv")

Load dataframes from registered pipelines in a catalog::

    # Load as Polars LazyFrame (default)
    lf = data.load(pipeline="yield_curve", dataframe="repo_public")

    # Load as Polars eager DataFrame
    df = data.load(pipeline="yield_curve", dataframe="repo_public", format="polars_eager")

    # Load as pandas DataFrame
    df = data.load(pipeline="yield_curve", dataframe="repo_public", format="pandas")

    # Get just the data path
    path = data.get_data_path(pipeline="yield_curve", dataframe="repo_public")

    # Get documentation content
    docs = data.get_docs(pipeline="yield_curve", dataframe="repo_public")

    # Get path to documentation source
    docs_path = data.get_docs_path(pipeline="yield_curve", dataframe="repo_public")
"""

import sys
from pathlib import Path
from typing import Optional, Union

from chartbook import assets as _assets
from chartbook.identity import resolve_pipeline_ref
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import (
    FileLocation,
    caller_start_dirs,
    find_manifest_dir,
    require_file,
    resolve,
)
from chartbook.resolve import resolve_catalog_path as _resolve_catalog_path
from chartbook.utils import is_glob_pattern


def path(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path the manifest declares for a dataframe of the current pipeline.

    The enclosing ``chartbook.toml`` is the single source of truth for where
    a dataframe lives, so code can ask for the path rather than repeat it:

    >>> from chartbook import data
    >>> df.to_parquet(data.path("merged_rates"))  # doctest: +SKIP

    and a build definition can use the same call for what it reads and what
    it writes — ``file_dep`` and ``targets`` in a ``dodo.py``, say. The path
    is whatever ``path`` the entry declares, made absolute; nothing checks
    that the file exists, so a target can be named before it is built.

    This is :func:`chartbook.assets.path` with ``kind="dataframe"``: it
    answers for dataframes and nothing else, so a typo cannot hand back a
    chart's HTML where a parquet file was meant. For a chart, a notebook or
    a note, use :func:`chartbook.assets.path`. Asking for a name that
    ``[dataframes]`` does not declare raises immediately, naming the table
    to add, rather than surfacing later as a missing file.

    This is a convenience, never a requirement. A script that hardcodes the
    same path, in any language, works just as well; ``chartbook path`` on the
    command line gives the same answer to a shell, Make, R or Stata.

    Only local references resolve today. The rest of the reference grammar —
    ``other_pipeline:asset``, ``asset#part``, ``@rev`` — is reserved and
    raises "not yet supported".

    :param ref: The dataframe's name: its key in ``[dataframes]``.
    :type ref: str
    :param project_dir: Where to look for the pipeline. The enclosing
        ``chartbook.toml`` is found by walking up from here. By default the
        search starts at the calling file's directory, then falls back to the
        current working directory.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path declared for the dataframe (it may contain
        glob characters for partitioned data).
    :rtype: Path
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises ValueError: If the reference names another kind of asset, uses
        reserved syntax, or the entry has no ``path``.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    try:
        return _assets._path(ref, "dataframe", start_dirs)
    except KindMismatchError as e:
        raise KindMismatchError(
            str(ref), e.found, e.expected, hint=(
                f"data.path() answers for dataframes only; use "
                f"chartbook.assets.path({str(ref)!r}) for a {e.found}."
            )
        ) from None


#: Where :func:`scratch` puts throwaway files, relative to the pipeline root.
SCRATCH_DIR = Path("_data") / "_scratch"


def scratch(project_dir: Optional[Union[str, Path]] = None) -> Path:
    """Get the current pipeline's directory for throwaway files.

    Use it for intermediates that nothing else depends on: a partial
    download, a cache between two steps, a file you only want to look at.

    >>> from chartbook import data
    >>> tmp = data.scratch() / "raw_download.csv"  # doctest: +SKIP

    The directory is ``_data/_scratch/`` inside the pipeline, created on
    first use. What goes in it is not an asset: it is not declared in the
    manifest, not documented, not published, and it ignores itself in git.
    It is safe to delete at any time. Because it lives inside the project,
    two checkouts or worktrees of the same pipeline each get their own.

    One thing to avoid: a dataframe whose ``path`` is a glob over all of
    ``_data/`` (``./_data/**/*.parquet``) would pick up scratch files too.

    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path of the scratch directory, which exists.
    :rtype: Path
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    directory = find_manifest_dir(*start_dirs) / SCRATCH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return directory


def _get_dataframe_docs_info_from_catalog(
    catalog_path: Path,
    pipeline: str,
    dataframe: str,
) -> tuple:
    """Look up docs info for a dataframe inside a catalog manifest.

    :param catalog_path: Path to the catalog's ``chartbook.toml``.
    :type catalog_path: Path
    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :returns: Tuple of (doc_mode, doc_value, pipeline_base_dir) where doc_mode
        is ``"path"`` or ``"str"``, doc_value is the path string or inline
        content, and pipeline_base_dir is the base directory of the pipeline.
    :rtype: tuple[str, str, Path]
    :raises KeyError: If the pipeline or dataframe is not found.
    """
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

    df_manifest = pipeline_manifest["dataframes"][dataframe]
    doc_mode = df_manifest["_doc_mode"]
    doc_value = df_manifest["_doc_value"]
    pipeline_base_dir = Path(pipeline_manifest["base_dir"])

    return doc_mode, doc_value, pipeline_base_dir


def get_data_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the resolved path to a dataframe's parquet file, through a catalog.

    For glob patterns (e.g., ``**/*.parquet``), returns a ``Path`` containing
    the glob pattern characters.

    :func:`path` supersedes this for assets of the current pipeline, and will
    for other pipelines' once cross-pipeline references resolve. Until then
    this remains the way to locate another pipeline's dataframe.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The resolved path to the parquet file (may contain glob characters).
    :rtype: Path
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path)
    return require_file(location, f"Dataframe {dataframe!r}")


def get_docs_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path to a dataframe's documentation source.

    For dataframes using ``docs_path``, returns the path to the ``.md``
    file. For dataframes using ``docs`` (inline docs), returns the path to
    the ``chartbook.toml`` file where the docs are defined.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The resolved path to the documentation source file.
    :rtype: Path
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    resolved_catalog = _resolve_catalog_path(catalog_path)
    doc_mode, doc_value, pipeline_base_dir = _get_dataframe_docs_info_from_catalog(
        resolved_catalog, pipeline, dataframe
    )
    if doc_mode == "path":
        return (pipeline_base_dir / doc_value).resolve()
    else:  # doc_mode == "str"
        return (pipeline_base_dir / "chartbook.toml").resolve()


def get_docs(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> str:
    """Get the documentation content for a dataframe as a string.

    Works with both documentation modes:

    - If the dataframe uses ``docs_path``, reads and returns the content of
      the ``.md`` file.
    - If the dataframe uses ``docs``, returns the inline string directly.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The documentation content as a string.
    :rtype: str
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    resolved_catalog = _resolve_catalog_path(catalog_path)
    doc_mode, doc_value, pipeline_base_dir = _get_dataframe_docs_info_from_catalog(
        resolved_catalog, pipeline, dataframe
    )
    if doc_mode == "path":
        doc_path = (pipeline_base_dir / doc_value).resolve()
        return doc_path.read_text()
    else:  # doc_mode == "str"
        return doc_value


def load(
    pipeline: str,
    dataframe: str,
    format: str = "polars",
    catalog_path: Optional[Union[str, Path]] = None,
):
    """Load a dataframe from a registered pipeline in a catalog.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param format: Output format — ``"polars"`` (default, returns LazyFrame),
        ``"polars_eager"``, ``"pandas"``, or ``"polars-lazyframe"`` (deprecated
        alias for ``"polars"``).  Glob patterns in a dataframe's ``path`` only
        support ``"polars"`` (LazyFrame).
    :type format: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The loaded dataframe in the requested format.
    :rtype: pandas.DataFrame or polars.DataFrame or polars.LazyFrame
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    :raises ValueError: If *format* is not one of the supported values, or if
        a glob path is used with a non-LazyFrame format.

    **Examples**

    Load as a Polars LazyFrame (default):

    >>> from chartbook import data
    >>> lf = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP

    Load as a Polars eager DataFrame:

    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="polars_eager",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP

    Load as a pandas DataFrame:

    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="pandas",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP
    """
    location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path)
    if not isinstance(location, FileLocation):
        raise NotImplementedError(
            f"Dataframe {dataframe!r} is {location.kind}-backed; only "
            f"file-backed dataframes can be loaded."
        )
    file_path = location.path
    _is_glob = is_glob_pattern(file_path)

    if format == "pandas":
        if _is_glob:
            raise ValueError(
                "Glob patterns in a dataframe's path only support format='polars' "
                "(LazyFrame). Use data.load(..., format='polars') and call .collect() "
                "to materialize, then .to_pandas() if needed."
            )
        import pandas as pd

        return pd.read_parquet(file_path)
    elif format == "polars":
        import polars as pl

        return pl.scan_parquet(file_path, hive_partitioning=True)
    elif format == "polars_eager":
        if _is_glob:
            raise ValueError(
                "Glob patterns in a dataframe's path only support format='polars' "
                "(LazyFrame). Use data.load(..., format='polars') and call .collect() "
                "to materialize."
            )
        import polars as pl

        return pl.read_parquet(file_path, hive_partitioning=True)
    elif format == "polars-lazyframe":
        import warnings

        import polars as pl

        warnings.warn(
            "format='polars-lazyframe' is deprecated. Use format='polars' instead "
            "(polars format now returns LazyFrame by default).",
            DeprecationWarning,
            stacklevel=2,
        )
        return pl.scan_parquet(file_path, hive_partitioning=True)
    else:
        raise ValueError(
            f"Invalid format: {format!r}. Must be 'polars', 'polars_eager', "
            f"'pandas', or 'polars-lazyframe'."
        )
