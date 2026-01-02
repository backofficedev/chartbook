"""
Shared pytest fixtures for integration testing.
"""

import pytest

from tests.fixtures import (
    create_catalog_project,
    create_invalid_toml_project,
    create_pipeline_project,
)


@pytest.fixture
def pipeline_project(tmp_path):
    """Creates and returns path to a complete pipeline project.

    The project includes:
    - chartbook.toml with valid pipeline config
    - src/ directory with a source file
    - docs_src/ directory with index.md
    - _data/{pipeline_id}/ with parquet files
    - 1 dataframe with 1 chart
    """
    return create_pipeline_project(
        tmp_path / "pipeline_project",
        pipeline_id="test_pipeline",
        pipeline_name="Test Pipeline",
        include_dataframes=True,
        include_charts=True,
    )


@pytest.fixture
def pipeline_project_with_notes(tmp_path):
    """Creates a pipeline project that includes notes."""
    return create_pipeline_project(
        tmp_path / "pipeline_with_notes",
        pipeline_id="notes_pipeline",
        pipeline_name="Pipeline With Notes",
        include_dataframes=True,
        include_charts=True,
        include_notes=True,
    )


@pytest.fixture
def pipeline_project_multi_dataframes(tmp_path):
    """Creates a pipeline project with multiple dataframes and charts."""
    return create_pipeline_project(
        tmp_path / "multi_df_project",
        pipeline_id="multi_df",
        pipeline_name="Multi Dataframe Pipeline",
        include_dataframes=True,
        include_charts=True,
        dataframe_count=2,
        charts_per_dataframe=2,
    )


@pytest.fixture
def catalog_project(tmp_path):
    """Creates and returns path to a catalog with 2 pipelines."""
    return create_catalog_project(
        tmp_path / "catalog_project",
        pipeline_ids=["pipeline_a", "pipeline_b"],
    )


@pytest.fixture
def catalog_project_platform_paths(tmp_path):
    """Creates a catalog project using platform-specific path dicts."""
    return create_catalog_project(
        tmp_path / "catalog_platform",
        pipeline_ids=["pipeline_x", "pipeline_y"],
        use_platform_paths=True,
    )


@pytest.fixture
def invalid_project_missing_file(tmp_path):
    """Creates a project without chartbook.toml."""
    return create_invalid_toml_project(tmp_path / "missing_file", "missing_file")


@pytest.fixture
def invalid_project_invalid_type(tmp_path):
    """Creates a project with invalid config type."""
    return create_invalid_toml_project(tmp_path / "invalid_type", "invalid_type")


@pytest.fixture
def invalid_project_invalid_version(tmp_path):
    """Creates a project with invalid version format."""
    return create_invalid_toml_project(tmp_path / "invalid_version", "invalid_version")


@pytest.fixture
def invalid_project_old_version(tmp_path):
    """Creates a project with old version."""
    return create_invalid_toml_project(tmp_path / "old_version", "old_version")
