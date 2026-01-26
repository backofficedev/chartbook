"""Catalog-aware data loading for chartbook.

Load dataframes from registered pipelines in a catalog::

    from chartbook import data

    df = data.load(pipeline="yield_curve", dataframe="repo_public")

    # Specify format
    df_pl = data.load(pipeline="yield_curve", dataframe="repo_public", format="polars")

    # Get just the path
    path = data.get_path(pipeline="yield_curve", dataframe="repo_public")
"""

from pathlib import Path
from typing import Optional, Union

from chartbook.config import get_default_catalog_path, get_global_settings_path
from chartbook.errors import CatalogNotConfiguredError


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


def get_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the resolved path to a dataframe's parquet file.

    :param pipeline: The pipeline identifier within the catalog.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The resolved path to the parquet file.
    :rtype: Path
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    resolved_catalog = _resolve_catalog_path(catalog_path)
    return _get_dataframe_path_from_catalog(resolved_catalog, pipeline, dataframe)


def load(
    pipeline: str,
    dataframe: str,
    format: str = "pandas",
    catalog_path: Optional[Union[str, Path]] = None,
):
    """Load a dataframe from a registered pipeline in a catalog.

    :param pipeline: The pipeline identifier within the catalog.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param format: Output format — ``"pandas"`` (default), ``"polars"``,
        or ``"polars-lazyframe"``.
    :type format: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The loaded dataframe in the requested format.
    :rtype: pandas.DataFrame or polars.DataFrame or polars.LazyFrame
    :raises CatalogNotConfiguredError: If no catalog is configured.
    :raises KeyError: If the pipeline or dataframe is not found.
    :raises ValueError: If *format* is not one of the supported values.

    **Examples**

    Load as a pandas DataFrame (default):

    >>> from chartbook import data
    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP

    Load as a polars DataFrame:

    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="polars",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP

    Load as a polars LazyFrame:

    >>> lf = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="polars-lazyframe",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP
    """
    file_path = get_path(pipeline, dataframe, catalog_path)

    if format == "pandas":
        import pandas as pd

        return pd.read_parquet(file_path)
    elif format == "polars":
        import polars as pl

        return pl.read_parquet(file_path)
    elif format == "polars-lazyframe":
        import polars as pl

        return pl.scan_parquet(file_path)
    else:
        raise ValueError(
            f"Invalid format: {format!r}. Must be 'pandas', 'polars', or 'polars-lazyframe'."
        )
