"""Tests for chartbook.data — catalog-aware data loading."""

from pathlib import Path

import polars as pl
import pytest

from chartbook import config, data
from chartbook.errors import CatalogNotConfiguredError


@pytest.fixture
def fake_config_dir(tmp_path, monkeypatch):
    """Redirect the global config directory to a temporary path."""
    fake_dir = tmp_path / ".chartbook_data_tests"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
    monkeypatch.setattr(
        config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
    )
    return fake_dir


# --- Loading with explicit catalog_path ---


def test_load_pandas_default(catalog_project):
    """Load as pandas DataFrame (default format) with explicit catalog_path."""
    import pandas as pd

    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0


def test_load_polars(catalog_project):
    """Load as polars DataFrame with explicit catalog_path."""
    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pl.DataFrame)
    assert len(df) > 0


def test_load_polars_lazyframe(catalog_project):
    """Load as polars LazyFrame with explicit catalog_path."""
    lf = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars-lazyframe",
        catalog_path=catalog_project,
    )
    assert isinstance(lf, pl.LazyFrame)
    # Collect to verify it actually loads
    df = lf.collect()
    assert len(df) > 0


# --- catalog_path as directory ---


def test_catalog_path_as_directory(catalog_project):
    """catalog_path can be a directory; chartbook.toml is inferred."""
    import pandas as pd

    df = data.load(
        pipeline="pipeline_b",
        dataframe="dataframe_0",
        catalog_path=catalog_project,  # directory, not file
    )
    assert isinstance(df, pd.DataFrame)


# --- Error cases ---


def test_pipeline_not_found(catalog_project):
    """KeyError with helpful message when pipeline is not in the catalog."""
    with pytest.raises(KeyError, match="not_a_pipeline"):
        data.load(
            pipeline="not_a_pipeline",
            dataframe="dataframe_0",
            catalog_path=catalog_project,
        )


def test_pipeline_not_found_lists_available(catalog_project):
    """KeyError message lists available pipelines."""
    with pytest.raises(KeyError, match="pipeline_a"):
        data.load(
            pipeline="missing",
            dataframe="dataframe_0",
            catalog_path=catalog_project,
        )


def test_dataframe_not_found(catalog_project):
    """KeyError with helpful message when dataframe is not in the pipeline."""
    with pytest.raises(KeyError, match="not_a_df"):
        data.load(
            pipeline="pipeline_a",
            dataframe="not_a_df",
            catalog_path=catalog_project,
        )


def test_dataframe_not_found_lists_available(catalog_project):
    """KeyError message lists available dataframes."""
    with pytest.raises(KeyError, match="dataframe_0"):
        data.load(
            pipeline="pipeline_a",
            dataframe="missing_df",
            catalog_path=catalog_project,
        )


def test_invalid_format(catalog_project):
    """ValueError for unsupported format string."""
    with pytest.raises(ValueError, match="Invalid format"):
        data.load(
            pipeline="pipeline_a",
            dataframe="dataframe_0",
            format="csv",
            catalog_path=catalog_project,
        )


# --- CatalogNotConfiguredError ---


def test_no_catalog_configured_raises(fake_config_dir):
    """CatalogNotConfiguredError when no catalog is configured and no path given."""
    with pytest.raises(CatalogNotConfiguredError, match="chartbook config"):
        data.load(pipeline="any", dataframe="any")


# --- Loading via global config ---


def test_load_via_global_config(fake_config_dir, catalog_project):
    """data.load() uses the catalog from global settings when no path is given."""
    import pandas as pd

    config.set_default_catalog_path(catalog_project)
    df = data.load(pipeline="pipeline_a", dataframe="dataframe_0")
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0


# --- get_path ---


def test_get_path_returns_resolved_path(catalog_project):
    """get_path returns an absolute Path to the parquet file."""
    path = data.get_path(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.suffix == ".parquet"
    assert path.exists()
