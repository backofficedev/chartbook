"""
Integration tests for the generator module.

Tests the full documentation generation workflow:
generate_docs() -> load_manifest() -> _retrieve_correct_docs_src_dir() ->
run_build_markdown() -> run_sphinx_build()
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from chartbook.build_docs import (
    _retrieve_correct_docs_src_dir,
    generate_docs,
    get_docs_src_path,
    run_sphinx_build,
)
from chartbook.manifest import load_manifest


class TestGetDocsSrcPath:
    """Tests for get_docs_src_path function."""

    def test_docs_src_path_pipeline(self):
        """Test that pipeline theme returns docs_src_pipeline path."""
        path = get_docs_src_path("pipeline")
        assert path.name == "docs_src_pipeline"
        assert path.exists()

    def test_docs_src_path_catalog(self):
        """Test that catalog theme returns docs_src_catalog path."""
        path = get_docs_src_path("catalog")
        assert path.name == "docs_src_catalog"
        assert path.exists()

    def test_docs_src_path_invalid_raises(self):
        """Test that invalid theme raises ValueError."""
        with pytest.raises(ValueError, match="Invalid pipeline theme"):
            get_docs_src_path("invalid_theme")


class TestRunSphinxBuild:
    """Tests for run_sphinx_build function."""

    def test_sphinx_build_failure_raises_runtime_error(self, tmp_path):
        """Test that failed sphinx-build raises RuntimeError."""
        # Create a minimal _docs directory without proper Sphinx setup
        docs_dir = tmp_path / "_docs"
        docs_dir.mkdir()

        with pytest.raises(RuntimeError, match="Sphinx build failed"):
            run_sphinx_build(docs_dir)

    @patch("subprocess.run")
    def test_sphinx_build_success_no_error(self, mock_run, tmp_path):
        """Test that successful sphinx-build completes without error."""
        docs_dir = tmp_path / "_docs"
        docs_dir.mkdir()

        # Mock successful subprocess run
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        # Should not raise
        run_sphinx_build(docs_dir)

        # Verify sphinx-build was called with correct arguments
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "sphinx-build" in call_args
        assert "-M" in call_args
        assert "html" in call_args


class TestRetrieveCorrectDocsSrcDir:
    """Tests for _retrieve_correct_docs_src_dir function."""

    def test_retrieve_creates_static_and_assets_dirs(self, pipeline_project, tmp_path):
        """Test that _static and assets directories are created."""
        temp_docs_src = tmp_path / "_docs_src"
        temp_docs_src.mkdir()

        manifest = load_manifest(pipeline_project)

        _retrieve_correct_docs_src_dir(
            temp_docs_src, manifest, pipeline_project, "pipeline"
        )

        assert (temp_docs_src / "_static").exists()
        assert (temp_docs_src / "assets").exists()

    def test_retrieve_copies_logo_to_both_locations(self, pipeline_project, tmp_path):
        """Test that logo is copied to both _static and assets."""
        temp_docs_src = tmp_path / "_docs_src"
        temp_docs_src.mkdir()

        manifest = load_manifest(pipeline_project)

        _retrieve_correct_docs_src_dir(
            temp_docs_src, manifest, pipeline_project, "pipeline"
        )

        # Logo should exist in both locations
        assert (temp_docs_src / "_static" / "logo.png").exists()
        assert (temp_docs_src / "assets" / "logo.png").exists()

    def test_retrieve_copies_favicon_to_both_locations(
        self, pipeline_project, tmp_path
    ):
        """Test that favicon is copied to both _static and assets."""
        temp_docs_src = tmp_path / "_docs_src"
        temp_docs_src.mkdir()

        manifest = load_manifest(pipeline_project)

        _retrieve_correct_docs_src_dir(
            temp_docs_src, manifest, pipeline_project, "pipeline"
        )

        # Favicon should exist in both locations
        assert (temp_docs_src / "_static" / "favicon.ico").exists()
        assert (temp_docs_src / "assets" / "favicon.ico").exists()

    def test_retrieve_copies_docs_src_files(self, pipeline_project, tmp_path):
        """Test that docs_src files from package are copied."""
        temp_docs_src = tmp_path / "_docs_src"
        temp_docs_src.mkdir()

        manifest = load_manifest(pipeline_project)

        _retrieve_correct_docs_src_dir(
            temp_docs_src, manifest, pipeline_project, "pipeline"
        )

        # Should have conf.py.j2 template from docs_src_pipeline
        assert (temp_docs_src / "conf.py.j2").exists()


class TestGenerateDocsEndToEnd:
    """End-to-end integration tests for generate_docs.

    Note: Full end-to-end tests require proper working directory setup.
    The existing test_generate_command.py tests end-to-end with the
    examples/fred_charts directory via CLI. These tests use the same approach
    with monkeypatch.chdir().
    """

    def test_generate_docs_with_example_project(self, monkeypatch):
        """Test generate_docs with the example project."""
        import shutil

        example_dir = Path("examples/fred_charts").resolve()
        output_dir = example_dir / "docs_test"

        # Clean previous runs
        if output_dir.exists():
            shutil.rmtree(output_dir)

        # Change to example directory (required for template resolution)
        monkeypatch.chdir(example_dir)

        try:
            generate_docs(
                output_dir=output_dir,
                project_dir=Path("."),  # Use relative path since we chdir'd
                keep_build_dirs=False,
            )

            # Verify HTML output created
            assert output_dir.exists()
            assert (output_dir / "index.html").exists()
            assert (output_dir / ".nojekyll").exists()

        finally:
            # Cleanup
            if output_dir.exists():
                shutil.rmtree(output_dir)

    def test_generate_docs_keeps_build_dirs(self, monkeypatch):
        """Test that keep_build_dirs=True preserves temp directories."""
        import shutil

        example_dir = Path("examples/fred_charts").resolve()
        output_dir = example_dir / "docs_test"
        # Use default names for _docs and _docs_src since templates expect them
        docs_dir = example_dir / "_docs"
        docs_src_dir = example_dir / "_docs_src"

        # Clean previous runs
        for d in [output_dir, docs_dir, docs_src_dir]:
            if d.exists():
                shutil.rmtree(d)

        # Change to example directory
        monkeypatch.chdir(example_dir)

        try:
            generate_docs(
                output_dir=output_dir,
                project_dir=Path("."),
                _docs_dir=docs_dir,
                temp_docs_src_dir=docs_src_dir,
                keep_build_dirs=True,
            )

            # Verify HTML output created
            assert output_dir.exists()

            # Verify temp directories preserved
            assert docs_dir.exists()
            assert docs_src_dir.exists()

            # Verify conf.py updated with project title
            conf_content = (docs_dir / "conf.py").read_text()
            assert 'project = "Example Charts from FRED"' in conf_content
            assert 'html_theme = "sphinx_book_theme"' in conf_content

        finally:
            # Cleanup
            for d in [output_dir, docs_dir, docs_src_dir]:
                if d.exists():
                    shutil.rmtree(d)

    def test_generate_docs_atomic_replacement(self, monkeypatch):
        """Test that should_remove_existing replaces output atomically."""
        import shutil

        example_dir = Path("examples/fred_charts").resolve()
        output_dir = example_dir / "docs_test"

        # Clean previous runs
        if output_dir.exists():
            shutil.rmtree(output_dir)

        # Change to example directory
        monkeypatch.chdir(example_dir)

        try:
            # Create existing output with marker file
            output_dir.mkdir()
            marker_file = output_dir / "old_marker.txt"
            marker_file.write_text("old content")

            generate_docs(
                output_dir=output_dir,
                project_dir=Path("."),
                should_remove_existing=True,
                keep_build_dirs=False,
            )

            # Verify new output created
            assert output_dir.exists()
            assert (output_dir / "index.html").exists()
            assert (output_dir / ".nojekyll").exists()

            # Verify old marker file is gone
            assert not marker_file.exists()

        finally:
            # Cleanup
            if output_dir.exists():
                shutil.rmtree(output_dir)
