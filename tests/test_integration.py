"""
Cross-module integration tests.

These tests exercise the complete workflow from manifest reading through
documentation generation, verifying that the full pipeline works correctly.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from chartbook.build_docs import generate_docs
from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest, load_manifest


class TestManifestToGeneratorPipelineWorkflow:
    """End-to-end tests for pipeline documentation workflow.

    Uses fixture-generated projects to test the complete workflow.
    """

    def test_full_pipeline_workflow(self, pipeline_project, monkeypatch):
        """Test complete workflow: read manifest -> generate docs."""
        output_dir = pipeline_project / "docs_integration_test"

        # Change to project directory (required for template resolution)
        monkeypatch.chdir(pipeline_project)

        # Step 1: Read and verify manifest
        manifest = load_manifest(Path("."))
        assert manifest["config"]["type"] == "pipeline"
        assert "dataframes" in manifest
        assert "charts" in manifest

        # Verify chart-dataframe linking
        for df_id in manifest["dataframes"]:
            assert "linked_charts" in manifest["dataframes"][df_id]

        # Verify pipeline ID list works
        pipeline_ids = get_pipeline_ids(manifest)
        assert len(pipeline_ids) == 1

        # Verify get_pipeline_manifest works
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_ids[0])
        assert "dataframes" in pipeline_manifest

        # Step 2: Generate documentation
        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            keep_build_dirs=False,
        )

        # Step 3: Verify output structure
        assert output_dir.exists()
        assert (output_dir / "index.html").exists()
        assert (output_dir / ".nojekyll").exists()

        # Verify HTML has content
        html_content = (output_dir / "index.html").read_text()
        assert len(html_content) > 0


class TestManifestToGeneratorCatalogWorkflow:
    """End-to-end tests for catalog documentation workflow.

    Note: These tests verify manifest reading for catalog type works correctly.
    Full generation tests would require a complete catalog example.
    """

    def test_catalog_manifest_reading(self, catalog_project):
        """Test that catalog manifest is read and processed correctly."""
        manifest = load_manifest(catalog_project)
        assert manifest["config"]["type"] == "catalog"

        pipeline_ids = get_pipeline_ids(manifest)
        assert len(pipeline_ids) == 2
        assert "pipeline_a" in pipeline_ids
        assert "pipeline_b" in pipeline_ids

        # Verify each pipeline has full manifest
        for pid in pipeline_ids:
            pipeline_manifest = get_pipeline_manifest(manifest, pid)
            assert pipeline_manifest["config"]["type"] == "pipeline"
            assert "dataframes" in pipeline_manifest
            assert "charts" in pipeline_manifest

    def test_catalog_platform_paths_resolution(self, catalog_project_platform_paths):
        """Test catalog with platform-specific path dictionaries."""
        manifest = load_manifest(catalog_project_platform_paths)
        assert manifest["config"]["type"] == "catalog"

        # Both pipelines should be accessible
        pipeline_ids = get_pipeline_ids(manifest)
        assert "pipeline_x" in pipeline_ids
        assert "pipeline_y" in pipeline_ids

        # Each should have valid manifest
        for pid in pipeline_ids:
            pipeline_manifest = get_pipeline_manifest(manifest, pid)
            assert pipeline_manifest["pipeline"]["id"] == pid


class TestWorkflowErrorHandling:
    """Tests for error handling across the workflow."""

    def test_workflow_fails_gracefully_for_missing_chartbook(
        self, invalid_project_missing_file, tmp_path
    ):
        """Test that missing chartbook.toml is caught early in workflow."""
        output_dir = tmp_path / "output"
        docs_dir = tmp_path / "_docs"
        docs_src_dir = tmp_path / "_docs_src"

        with pytest.raises((AssertionError, ValueError)):
            generate_docs(
                output_dir=output_dir,
                project_dir=invalid_project_missing_file,
                _docs_dir=docs_dir,
                temp_docs_src_dir=docs_src_dir,
            )

    def test_workflow_fails_for_invalid_config_type(
        self, invalid_project_invalid_type, tmp_path
    ):
        """Test that invalid config type is caught."""
        output_dir = tmp_path / "output"
        docs_dir = tmp_path / "_docs"
        docs_src_dir = tmp_path / "_docs_src"

        with pytest.raises(ValueError):
            generate_docs(
                output_dir=output_dir,
                project_dir=invalid_project_invalid_type,
                _docs_dir=docs_dir,
                temp_docs_src_dir=docs_src_dir,
            )


class TestExampleProjects:
    """Integration tests that run the actual example projects.

    These tests execute the full doit pipeline for each example to verify
    the complete workflow works end-to-end.
    """

    @staticmethod
    def _clean_example_dirs(example_path: Path):
        """Remove _data, _output, docs, and build directories from an example."""
        for dir_name in ["_data", "_output", "docs", "_docs", "_docs_src"]:
            dir_path = example_path / dir_name
            if dir_path.exists():
                shutil.rmtree(dir_path)
        # Also remove doit database for clean state
        doit_db = example_path / ".doit-db.sqlite"
        if doit_db.exists():
            doit_db.unlink()

    @staticmethod
    def _get_env_with_pythonpath():
        """Get environment with PYTHONPATH set to use local src."""
        import os

        env = os.environ.copy()
        src_path = Path(__file__).parent.parent / "src"
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = str(src_path)
        return env

    def test_fred_charts_example(self):
        """Test that fred_charts example runs successfully with doit -a."""
        example_path = Path("examples/fred_charts").resolve()

        # Clean up before running
        self._clean_example_dirs(example_path)

        # Run doit -a with PYTHONPATH set to use local chartbook
        result = subprocess.run(
            ["doit", "-a"],
            cwd=example_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=self._get_env_with_pythonpath(),
        )

        assert result.returncode == 0, f"doit failed: {result.stderr}"

        # Verify outputs exist
        assert (example_path / "_data" / "fred.parquet").exists()
        assert (example_path / "_output" / "01_gdp_chart.html").exists()
        assert (example_path / "docs" / "index.html").exists()

    def test_yield_curve_example(self):
        """Test that yield_curve example runs successfully with doit -a."""
        example_path = Path("examples/yield_curve").resolve()

        # Clean up before running
        self._clean_example_dirs(example_path)

        # Run doit -a with PYTHONPATH set to use local chartbook
        result = subprocess.run(
            ["doit", "-a"],
            cwd=example_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=self._get_env_with_pythonpath(),
        )

        assert result.returncode == 0, f"doit failed: {result.stderr}"

        # Verify outputs exist
        assert (example_path / "_data" / "fed_yield_curve.parquet").exists()
        assert (example_path / "_output" / "yield_curve_current.html").exists()
        assert (example_path / "docs" / "index.html").exists()

    def test_catalog_example(self):
        """Test that catalog example builds successfully.

        The catalog references fred_charts and yield_curve pipelines,
        so we need to run those first to generate the required data files.
        """
        catalog_path = Path("examples/catalog").resolve()
        fred_charts_path = Path("examples/fred_charts").resolve()
        yield_curve_path = Path("examples/yield_curve").resolve()

        # Clean up catalog before running
        self._clean_example_dirs(catalog_path)

        # Run doit -a on fred_charts first (if not already run by previous test)
        if not (fred_charts_path / "_data" / "fred.parquet").exists():
            self._clean_example_dirs(fred_charts_path)
            result = subprocess.run(
                ["doit", "-a"],
                cwd=fred_charts_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._get_env_with_pythonpath(),
            )
            assert result.returncode == 0, f"fred_charts doit failed: {result.stderr}"

        # Run doit -a on yield_curve (if not already run by previous test)
        if not (yield_curve_path / "_data" / "fed_yield_curve.parquet").exists():
            self._clean_example_dirs(yield_curve_path)
            result = subprocess.run(
                ["doit", "-a"],
                cwd=yield_curve_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._get_env_with_pythonpath(),
            )
            assert result.returncode == 0, f"yield_curve doit failed: {result.stderr}"

        # Now run chartbook build -f on catalog
        result = subprocess.run(
            ["chartbook", "build", "-f"],
            cwd=catalog_path,
            capture_output=True,
            text=True,
            timeout=300,
            env=self._get_env_with_pythonpath(),
        )

        assert result.returncode == 0, f"chartbook build failed: {result.stderr}"

        # Verify outputs exist
        assert (catalog_path / "docs" / "index.html").exists()
