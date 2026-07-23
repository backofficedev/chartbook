"""Tests for chartbook.data — catalog-aware data loading."""

import warnings
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


def test_load_pandas(catalog_project):
    """Load as pandas DataFrame with explicit format and catalog_path."""
    import pandas as pd

    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="pandas",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0


def test_load_default_format_is_polars_lazyframe(catalog_project):
    """Default format returns polars LazyFrame."""
    result = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert len(df) > 0


def test_load_polars(catalog_project):
    """Load as polars LazyFrame with format='polars'."""
    lf = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars",
        catalog_path=catalog_project,
    )
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0


def test_load_polars_eager(catalog_project):
    """Load as polars eager DataFrame with format='polars_eager'."""
    df = data.load(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        format="polars_eager",
        catalog_path=catalog_project,
    )
    assert isinstance(df, pl.DataFrame)
    assert len(df) > 0


def test_load_polars_lazyframe_deprecated(catalog_project):
    """format='polars-lazyframe' emits deprecation warning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        lf = data.load(
            pipeline="pipeline_a",
            dataframe="dataframe_0",
            format="polars-lazyframe",
            catalog_path=catalog_project,
        )
        assert isinstance(lf, pl.LazyFrame)
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()


# --- catalog_path as directory ---


def test_catalog_path_as_directory(catalog_project):
    """catalog_path can be a directory; chartbook.toml is inferred."""
    lf = data.load(
        pipeline="pipeline_b",
        dataframe="dataframe_0",
        catalog_path=catalog_project,  # directory, not file
    )
    assert isinstance(lf, pl.LazyFrame)


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
    config.set_default_catalog_path(catalog_project)
    lf = data.load(pipeline="pipeline_a", dataframe="dataframe_0")
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0


# --- get_data_path ---


def test_get_data_path_returns_resolved_path(catalog_project):
    """get_data_path returns an absolute Path to the parquet file."""
    path = data.get_data_path(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.suffix == ".parquet"
    assert path.exists()


# --- get_docs_path ---


def test_get_docs_path_returns_md_file(catalog_project):
    """get_docs_path returns an absolute Path to the markdown file."""
    path = data.get_docs_path(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.suffix == ".md"
    assert path.exists()


# --- get_docs ---


def test_get_docs_returns_markdown_content(catalog_project):
    """get_docs returns the markdown content as a string."""
    docs = data.get_docs(
        pipeline="pipeline_a",
        dataframe="dataframe_0",
        catalog_path=catalog_project,
    )
    assert isinstance(docs, str)
    assert "Dataframe 0" in docs
    assert "Documentation for dataframe 0" in docs


# --- Inline docs (dataframe_docs_str) ---


def test_get_docs_path_returns_toml_for_inline(catalog_project_inline_docs):
    """get_docs_path returns path to chartbook.toml for inline docs."""
    path = data.get_docs_path(
        pipeline="pipeline_inline",
        dataframe="dataframe_0",
        catalog_path=catalog_project_inline_docs,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert path.name == "chartbook.toml"
    assert path.exists()


def test_get_docs_returns_inline_content(catalog_project_inline_docs):
    """get_docs returns the inline string content directly."""
    docs = data.get_docs(
        pipeline="pipeline_inline",
        dataframe="dataframe_0",
        catalog_path=catalog_project_inline_docs,
    )
    assert isinstance(docs, str)
    assert "Dataframe 0" in docs
    assert "Inline documentation for dataframe 0" in docs


# --- Glob pattern / hive-partitioned support ---


def test_load_polars_glob_returns_lazyframe(catalog_project_glob):
    """Load glob path as polars LazyFrame (default)."""
    lf = data.load(
        pipeline="pipeline_glob",
        dataframe="dataframe_0",
        catalog_path=catalog_project_glob,
    )
    assert isinstance(lf, pl.LazyFrame)
    df = lf.collect()
    assert len(df) > 0
    # Hive partition column should be present
    assert "category" in df.columns


def test_glob_polars_eager_raises(catalog_project_glob):
    """ValueError when using polars_eager with glob path."""
    with pytest.raises(ValueError, match="Glob patterns"):
        data.load(
            pipeline="pipeline_glob",
            dataframe="dataframe_0",
            format="polars_eager",
            catalog_path=catalog_project_glob,
        )


def test_glob_pandas_raises(catalog_project_glob):
    """ValueError when using pandas with glob path."""
    with pytest.raises(ValueError, match="Glob patterns"):
        data.load(
            pipeline="pipeline_glob",
            dataframe="dataframe_0",
            format="pandas",
            catalog_path=catalog_project_glob,
        )


def test_get_data_path_returns_path_for_glob(catalog_project_glob):
    """get_data_path returns a Path for glob patterns."""
    path = data.get_data_path(
        pipeline="pipeline_glob",
        dataframe="dataframe_0",
        catalog_path=catalog_project_glob,
    )
    assert isinstance(path, Path)
    assert path.is_absolute()
    assert "**" in str(path)
    assert "*.parquet" in str(path)
