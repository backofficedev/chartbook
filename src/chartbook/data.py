"""Catalog-aware data loading for chartbook.

Load dataframes from registered pipelines in a catalog::

    from chartbook import data

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

from pathlib import Path
from typing import Optional, Union

from chartbook.config import get_default_catalog_path, get_global_settings_path
from chartbook.errors import CatalogNotConfiguredError
from chartbook.utils import is_glob_pattern


def _resolve_catalog_path(
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
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
            catalog_path = catalog_path / "chartbook.toml"
        return catalog_path.resolve()

    default_path = get_default_catalog_path()
    if default_path is not None:
        return default_path

    raise CatalogNotConfiguredError(get_global_settings_path())


def _get_dataframe_path_from_catalog(
    catalog_path: Path,
    pipeline: str,
    dataframe: str,
) -> Path:
    """Look up the parquet path for a dataframe inside a catalog manifest.

    :param catalog_path: Path to the catalog's ``chartbook.toml``.
    :type catalog_path: Path
    :param pipeline: The pipeline identifier within the catalog.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :returns: Resolved path to the parquet file.
    :rtype: Path
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    from chartbook.manifest import load_manifest

    manifest = load_manifest(base_dir=catalog_path.parent)

    available_pipelines = list(manifest.get("pipelines", {}).keys())
    if pipeline not in manifest.get("pipelines", {}):
        raise KeyError(
            f"Pipeline {pipeline!r} not found in catalog. "
            f"Available pipelines: {available_pipelines}"
        )

    pipeline_manifest = manifest["pipelines"][pipeline]
    available_dataframes = list(pipeline_manifest.get("dataframes", {}).keys())
    if dataframe not in pipeline_manifest.get("dataframes", {}):
        raise KeyError(
            f"Dataframe {dataframe!r} not found in pipeline {pipeline!r}. "
            f"Available dataframes: {available_dataframes}"
        )

    return Path(pipeline_manifest["dataframes"][dataframe]["dataframe_path"])


def _get_dataframe_docs_info_from_catalog(
    catalog_path: Path,
    pipeline: str,
    dataframe: str,
) -> tuple:
    """Look up docs info for a dataframe inside a catalog manifest.

    :param catalog_path: Path to the catalog's ``chartbook.toml``.
    :type catalog_path: Path
    :param pipeline: The pipeline identifier within the catalog.
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

    available_pipelines = list(manifest.get("pipelines", {}).keys())
    if pipeline not in manifest.get("pipelines", {}):
        raise KeyError(
            f"Pipeline {pipeline!r} not found in catalog. "
            f"Available pipelines: {available_pipelines}"
        )

    pipeline_manifest = manifest["pipelines"][pipeline]
    available_dataframes = list(pipeline_manifest.get("dataframes", {}).keys())
    if dataframe not in pipeline_manifest.get("dataframes", {}):
        raise KeyError(
            f"Dataframe {dataframe!r} not found in pipeline {pipeline!r}. "
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
    """Get the resolved path to a dataframe's parquet file.

    For glob patterns (e.g., ``**/*.parquet``), returns a ``Path`` containing
    the glob pattern characters.

    :param pipeline: The pipeline identifier within the catalog.
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
    resolved_catalog = _resolve_catalog_path(catalog_path)
    return _get_dataframe_path_from_catalog(resolved_catalog, pipeline, dataframe)


def get_docs_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path to a dataframe's documentation source.

    For dataframes using ``dataframe_docs_path``, returns the path to the
    ``.md`` file. For dataframes using ``dataframe_docs_str`` (inline docs),
    returns the path to the ``chartbook.toml`` file where the docs are defined.

    :param pipeline: The pipeline identifier within the catalog.
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

    - If the dataframe uses ``dataframe_docs_path``, reads and returns the
      content of the ``.md`` file.
    - If the dataframe uses ``dataframe_docs_str``, returns the inline string
      directly.

    :param pipeline: The pipeline identifier within the catalog.
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

    :param pipeline: The pipeline identifier within the catalog.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param format: Output format — ``"polars"`` (default, returns LazyFrame),
        ``"polars_eager"``, ``"pandas"``, or ``"polars-lazyframe"`` (deprecated
        alias for ``"polars"``).  Glob patterns in ``path_to_parquet_data`` only
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
    file_path = get_data_path(pipeline, dataframe, catalog_path)
    _is_glob = is_glob_pattern(file_path)

    if format == "pandas":
        if _is_glob:
            raise ValueError(
                "Glob patterns in path_to_parquet_data only support format='polars' "
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
                "Glob patterns in path_to_parquet_data only support format='polars' "
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
