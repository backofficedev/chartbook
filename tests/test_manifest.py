from pathlib import Path
from unittest.mock import patch

import pytest

from chartbook.manifest import (
    get_pipeline_ids,
    get_pipeline_manifest,
    load_manifest,
    resolve_platform_path,
    validate_config_file,
)


class TestResolvePlatformPath:
    """Tests for resolve_platform_path function."""

    def test_string_input_returns_path(self):
        """String input should be converted directly to Path."""
        result = resolve_platform_path("/path/to/dir")
        assert result == Path("/path/to/dir")

    def test_string_input_relative_path(self):
        """Relative string paths should work."""
        result = resolve_platform_path("relative/path")
        assert result == Path("relative/path")

    @patch("platform.system")
    def test_dict_input_unix_platform(self, mock_system):
        """Dict input on Unix should return Unix path."""
        mock_system.return_value = "Linux"
        path_input = {"Windows": "C:/data", "Unix": "/home/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("/home/data")

    @patch("platform.system")
    def test_dict_input_macos_uses_unix(self, mock_system):
        """Dict input on macOS should use Unix path."""
        mock_system.return_value = "Darwin"
        path_input = {"Windows": "C:/data", "Unix": "/Users/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("/Users/data")

    @patch("platform.system")
    def test_dict_input_windows_platform(self, mock_system):
        """Dict input on Windows should return Windows path."""
        mock_system.return_value = "Windows"
        path_input = {"Windows": "C:/data", "Unix": "/home/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("C:/data")

    @patch("platform.system")
    def test_dict_missing_unix_on_unix_raises(self, mock_system):
        """Dict without Unix key on Unix platform should raise ValueError."""
        mock_system.return_value = "Linux"
        path_input = {"Windows": "C:/data"}

        with pytest.raises(
            ValueError, match="No valid path found for current platform"
        ):
            resolve_platform_path(path_input)

    @patch("platform.system")
    def test_dict_missing_windows_on_windows_raises(self, mock_system):
        """Dict without Windows key on Windows platform should raise ValueError."""
        mock_system.return_value = "Windows"
        path_input = {"Unix": "/home/data"}

        with pytest.raises(
            ValueError, match="No valid path found for current platform"
        ):
            resolve_platform_path(path_input)


class TestLoadManifestPipelineWorkflow:
    """Integration tests for reading pipeline manifest.

    Tests the full chain: load_manifest() -> validate_config_file() ->
    _load_pipeline_manifest() -> find_latest_source_modification()
    """

    def test_load_manifest_pipeline_full_workflow(self, pipeline_project):
        """Test reading a complete pipeline project with dataframes and charts."""
        manifest = load_manifest(pipeline_project)

        # Verify config type
        assert manifest["config"]["type"] == "pipeline"

        # Verify pipeline metadata
        assert manifest["pipeline"]["id"] == "test_pipeline"
        assert manifest["pipeline"]["pipeline_name"] == "Test Pipeline"

        # Verify dataframe paths resolved
        assert "dataframes" in manifest
        assert "dataframe_0" in manifest["dataframes"]
        df_manifest = manifest["dataframes"]["dataframe_0"]
        assert "dataframe_path" in df_manifest
        assert df_manifest["dataframe_path"].exists()

        # Verify charts linked to dataframes
        assert "linked_charts" in df_manifest
        assert "chart_0_0" in df_manifest["linked_charts"]

        # Verify topic tags normalized to Title Case
        assert "Test Tag" in df_manifest["topic_tags"]
        assert "Uppercase Tag" in df_manifest["topic_tags"]

        # Verify source modification time computed
        assert "source_last_modified_date" in manifest

        # Verify webpage URL generated
        assert "webpage_URL" in manifest
        assert manifest["webpage_URL"].startswith("file://")

    def test_load_manifest_with_dataframes_and_charts_linking(
        self, pipeline_project_multi_dataframes
    ):
        """Test that charts are correctly linked to their dataframes."""
        manifest = load_manifest(pipeline_project_multi_dataframes)

        # Should have 2 dataframes
        assert len(manifest["dataframes"]) == 2

        # Dataframe 0 should have charts chart_0_0 and chart_0_1
        df0_charts = manifest["dataframes"]["dataframe_0"]["linked_charts"]
        assert len(df0_charts) == 2
        assert "chart_0_0" in df0_charts
        assert "chart_0_1" in df0_charts

        # Dataframe 1 should have charts chart_1_0 and chart_1_1
        df1_charts = manifest["dataframes"]["dataframe_1"]["linked_charts"]
        assert len(df1_charts) == 2
        assert "chart_1_0" in df1_charts
        assert "chart_1_1" in df1_charts

        # Verify chart manifest reference correct dataframe
        assert manifest["charts"]["chart_0_0"]["dataframe_id"] == "dataframe_0"
        assert manifest["charts"]["chart_1_0"]["dataframe_id"] == "dataframe_1"

    def test_load_manifest_with_notes(self, pipeline_project_with_notes):
        """Test reading pipeline manifest that include notes section."""
        manifest = load_manifest(pipeline_project_with_notes)

        assert "notes" in manifest
        assert "note1" in manifest["notes"]

        note_manifest = manifest["notes"]["note1"]

        # Verify full_path computed correctly
        assert "full_path" in note_manifest
        assert note_manifest["full_path"].name == "note1.md"
        assert note_manifest["full_path"].exists()


class TestLoadManifestCatalogWorkflow:
    """Integration tests for reading catalog manifest with multiple pipelines."""

    def test_load_manifest_catalog_with_multiple_pipelines(self, catalog_project):
        """Test reading a catalog with multiple sub-pipelines."""
        manifest = load_manifest(catalog_project)

        # Verify config type
        assert manifest["config"]["type"] == "catalog"

        # Verify both pipelines discovered
        assert "pipelines" in manifest
        assert "pipeline_a" in manifest["pipelines"]
        assert "pipeline_b" in manifest["pipelines"]

        # Verify each sub-pipeline has full manifest
        for pipeline_id in ["pipeline_a", "pipeline_b"]:
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            assert pipeline_manifest["config"]["type"] == "pipeline"
            assert pipeline_manifest["pipeline"]["id"] == pipeline_id
            assert "dataframes" in pipeline_manifest
            assert "charts" in pipeline_manifest

    def test_load_manifest_catalog_platform_paths(
        self, catalog_project_platform_paths
    ):
        """Test catalog with platform-specific path dictionaries."""
        manifest = load_manifest(catalog_project_platform_paths)

        # Should resolve paths correctly for current platform
        assert "pipeline_x" in manifest["pipelines"]
        assert "pipeline_y" in manifest["pipelines"]

        # Each pipeline should have valid manifest
        for pid in ["pipeline_x", "pipeline_y"]:
            assert manifest["pipelines"][pid]["config"]["type"] == "pipeline"

    def test_get_pipeline_ids_catalog(self, catalog_project):
        """Test get_pipeline_ids returns all pipeline IDs for catalog."""
        manifest = load_manifest(catalog_project)
        pipeline_ids = get_pipeline_ids(manifest)

        assert len(pipeline_ids) == 2
        assert "pipeline_a" in pipeline_ids
        assert "pipeline_b" in pipeline_ids

    def test_get_pipeline_ids_pipeline(self, pipeline_project):
        """Test get_pipeline_ids returns single ID for pipeline type."""
        manifest = load_manifest(pipeline_project)
        pipeline_ids = get_pipeline_ids(manifest)

        assert len(pipeline_ids) == 1
        assert "test_pipeline" in pipeline_ids

    def test_get_pipeline_manifest_from_catalog(self, catalog_project):
        """Test extracting individual pipeline manifest from a catalog."""
        manifest = load_manifest(catalog_project)

        pipeline_a_manifest = get_pipeline_manifest(manifest, "pipeline_a")
        assert pipeline_a_manifest["pipeline"]["id"] == "pipeline_a"
        assert "dataframes" in pipeline_a_manifest

        pipeline_b_manifest = get_pipeline_manifest(manifest, "pipeline_b")
        assert pipeline_b_manifest["pipeline"]["id"] == "pipeline_b"


class TestLoadManifestValidationErrors:
    """Integration tests for manifest validation error handling."""

    def test_load_manifest_missing_chartbook_toml(self, invalid_project_missing_file):
        """Test that missing chartbook.toml raises ValueError."""
        with pytest.raises(AssertionError):
            load_manifest(invalid_project_missing_file)

    def test_validate_missing_chartbook_toml(self, invalid_project_missing_file):
        """Test validate_config_file raises for missing file."""
        with pytest.raises(ValueError, match="No chartbook.toml found"):
            validate_config_file(invalid_project_missing_file)

    def test_load_manifest_invalid_config_type(self, invalid_project_invalid_type):
        """Test that invalid config type raises error."""
        with pytest.raises(ValueError):
            load_manifest(invalid_project_invalid_type)

    def test_load_manifest_invalid_version_format(self, invalid_project_invalid_version):
        """Test that invalid version format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version format"):
            load_manifest(invalid_project_invalid_version)
