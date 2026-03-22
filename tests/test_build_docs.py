"""
Integration tests for the generator module.

Tests the full documentation generation workflow:
generate_docs() -> load_manifest() -> _retrieve_correct_docs_src_dir() ->
run_build_markdown() -> run_sphinx_build()
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from chartbook.build_docs import (
    _retrieve_correct_docs_src_dir,
    _strip_mathjax2_from_notebooks,
    generate_docs,
    get_docs_src_path,
    run_sphinx_build,
)
from chartbook.manifest import load_manifest
from chartbook.utils import MATHJAX2_PATTERN, strip_mathjax2_from_notebook


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

    Uses fixture-generated projects to test the full documentation pipeline.
    """

    def test_generate_docs_with_fixture_project(self, pipeline_project, monkeypatch):
        """Test generate_docs with a fixture-generated project."""
        output_dir = pipeline_project / "docs_test"

        # Change to project directory (required for template resolution)
        monkeypatch.chdir(pipeline_project)

        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            keep_build_dirs=False,
        )

        # Verify HTML output created
        assert output_dir.exists()
        assert (output_dir / "index.html").exists()
        assert (output_dir / ".nojekyll").exists()

    def test_generate_docs_keeps_build_dirs(self, pipeline_project, monkeypatch):
        """Test that keep_build_dirs=True preserves temp directories."""
        output_dir = pipeline_project / "docs_test"
        docs_dir = pipeline_project / "_docs"
        docs_src_dir = pipeline_project / "_docs_src"

        # Change to project directory
        monkeypatch.chdir(pipeline_project)

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
        assert 'project = "Test Pipeline"' in conf_content
        assert 'html_theme = "sphinx_book_theme"' in conf_content

    def test_generate_docs_atomic_replacement(self, pipeline_project, monkeypatch):
        """Test that should_remove_existing replaces output atomically."""
        output_dir = pipeline_project / "docs_test"

        # Change to project directory
        monkeypatch.chdir(pipeline_project)

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

    def test_catalog_dataframes_toctree_uses_relative_paths(
        self, catalog_project, monkeypatch
    ):
        """Test that catalog dataframes.md toctree entries are relative to cb/.

        Regression test: the dataframes.md file lives at cb/dataframes.md,
        so toctree entries must NOT have a cb/ prefix (Sphinx resolves them
        relative to the document location). A cb/ prefix would cause Sphinx
        to look for cb/cb/dataframes/... which doesn't exist, resulting in
        an empty Dataframes page.
        """
        output_dir = catalog_project / "docs_test"
        docs_dir = catalog_project / "_docs"

        monkeypatch.chdir(catalog_project)

        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            _docs_dir=docs_dir,
            keep_build_dirs=True,
        )

        # Read the rendered dataframes.md from the build directory
        dataframes_md = docs_dir / "cb" / "dataframes.md"
        assert dataframes_md.exists(), "cb/dataframes.md not generated"
        content = dataframes_md.read_text()

        # Toctree entries should start with "dataframes/", not "cb/dataframes/"
        lines = content.strip().splitlines()
        toctree_entries = [
            line.strip()
            for line in lines
            if line.strip() and line.strip().endswith(".md") and not line.startswith("#")
        ]
        assert len(toctree_entries) > 0, "No dataframe entries found in toctree"
        for entry in toctree_entries:
            assert not entry.startswith("cb/"), (
                f"Toctree entry '{entry}' has cb/ prefix — paths in cb/dataframes.md "
                f"must be relative to cb/, not the project root"
            )


class TestStrictFlag:
    """Tests for --strict flag behavior in generate_docs."""

    def test_default_skips_pipelines_with_missing_files(
        self, catalog_project, monkeypatch, capsys
    ):
        """Test that without --strict, pipelines with missing files are skipped."""
        output_dir = catalog_project / "docs_test"
        monkeypatch.chdir(catalog_project)

        # Delete a chart file from pipeline_a to trigger missing file detection
        chart_files = list(
            (catalog_project / "pipelines" / "pipeline_a" / "_output" / "charts").glob("*.html")
        )
        assert len(chart_files) > 0, "Fixture should create chart HTML files"
        chart_files[0].unlink()

        # Default (strict=False) should succeed, skipping pipeline_a
        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            keep_build_dirs=False,
        )

        # Build should succeed
        assert output_dir.exists()
        assert (output_dir / "index.html").exists()

        # Warning about skipping should appear on stderr
        captured = capsys.readouterr()
        assert "Skipping pipeline 'pipeline_a'" in captured.err

    def test_strict_errors_on_missing_files(
        self, catalog_project, monkeypatch
    ):
        """Test that --strict causes exit on missing files."""
        output_dir = catalog_project / "docs_test"
        monkeypatch.chdir(catalog_project)

        # Delete a chart file from pipeline_a
        chart_files = list(
            (catalog_project / "pipelines" / "pipeline_a" / "_output" / "charts").glob("*.html")
        )
        assert len(chart_files) > 0, "Fixture should create chart HTML files"
        chart_files[0].unlink()

        with pytest.raises(SystemExit) as exc_info:
            generate_docs(
                output_dir=output_dir,
                project_dir=Path("."),
                keep_build_dirs=False,
                strict=True,
            )
        assert exc_info.value.code == 1

    def test_no_missing_files_builds_all_pipelines(
        self, catalog_project, monkeypatch
    ):
        """Test that when no files are missing, all pipelines are built."""
        output_dir = catalog_project / "docs_test"
        docs_dir = catalog_project / "_docs"
        monkeypatch.chdir(catalog_project)

        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            _docs_dir=docs_dir,
            keep_build_dirs=True,
        )

        assert output_dir.exists()
        assert (output_dir / "index.html").exists()


class TestMissingSourceFilesError:
    """Tests for MissingSourceFilesError helper methods."""

    def test_get_pipelines_to_skip(self):
        """Test that get_pipelines_to_skip returns correct pipeline IDs."""
        from chartbook.errors import MissingFile, MissingSourceFilesError

        missing = [
            MissingFile(Path("/a.parquet"), "dataframe", "df1", "pipeline_a"),
            MissingFile(Path("/b.html"), "chart", "chart1", "pipeline_a"),
            MissingFile(Path("/c.parquet"), "dataframe", "df2", "pipeline_b"),
        ]
        error = MissingSourceFilesError(missing)
        assert error.get_pipelines_to_skip() == {"pipeline_a", "pipeline_b"}

    def test_format_skip_warnings_groups_by_pipeline(self):
        """Test that format_skip_warnings groups messages by pipeline."""
        from chartbook.errors import MissingFile, MissingSourceFilesError

        missing = [
            MissingFile(Path("/a.parquet"), "dataframe", "df1", "pipeline_a"),
            MissingFile(Path("/b.html"), "chart", "chart1", "pipeline_a"),
            MissingFile(Path("/c.parquet"), "dataframe", "df2", "pipeline_b"),
        ]
        error = MissingSourceFilesError(missing)
        warnings = error.format_skip_warnings()

        # Should have header + 2 files for pipeline_a, then header + 1 file for pipeline_b
        assert any("pipeline_a" in w and "2 missing" in w for w in warnings)
        assert any("pipeline_b" in w and "1 missing" in w for w in warnings)

    def test_format_cli_message_mentions_strict(self):
        """Test that the CLI error message references --strict."""
        from chartbook.errors import MissingFile, MissingSourceFilesError

        missing = [
            MissingFile(Path("/a.parquet"), "dataframe", "df1", "pipeline_a"),
        ]
        error = MissingSourceFilesError(missing)
        message = error.format_cli_message()
        assert "--strict" in message
        assert "--warn-missing" not in message


# Sample MathJax 2 script tags as injected by Plotly's NotebookRenderer
PLOTLY_MATHJAX2_SCRIPT = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/'
    'MathJax.js?config=TeX-AMS-MML_SVG"></script>'
)
PLOTLY_MATHJAX2_SCRIPT_WITH_CONFIG = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/'
    'MathJax.js?config=TeX-AMS-MML_SVG"></script>'
    '<script type="text/javascript">if (window.MathJax && window.MathJax.Hub'
    " && window.MathJax.Hub.Config) {window.MathJax.Hub.Config({SVG:"
    ' {font: "STIX-Web"}});}</script>'
)


def _make_notebook(cells):
    """Create a minimal notebook dict with the given cells."""
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": cells,
    }


def _make_plotly_cell(mathjax_script=PLOTLY_MATHJAX2_SCRIPT_WITH_CONFIG):
    """Create a notebook cell that mimics Plotly output with MathJax 2 injection."""
    return {
        "cell_type": "code",
        "source": ["import plotly"],
        "outputs": [
            {
                "output_type": "display_data",
                "data": {
                    "text/html": [
                        "<div>",
                        mathjax_script,
                        '<div id="plotly-graph"></div>',
                        "</div>",
                    ]
                },
                "metadata": {},
            }
        ],
        "metadata": {},
    }


class TestStripMathjax2FromNotebook:
    """Tests for strip_mathjax2_from_notebook function."""

    def test_strips_mathjax2_from_plotly_output(self, tmp_path):
        """Test that MathJax 2 scripts are removed from notebook outputs."""
        nb = _make_notebook([_make_plotly_cell()])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))

        result = strip_mathjax2_from_notebook(nb_path)

        assert result is True
        cleaned = json.loads(nb_path.read_text())
        html_parts = cleaned["cells"][0]["outputs"][0]["data"]["text/html"]
        for part in html_parts:
            assert "mathjax/2" not in part
            assert "MathJax.Hub.Config" not in part

    def test_preserves_non_mathjax_content(self, tmp_path):
        """Test that non-MathJax HTML content is preserved."""
        nb = _make_notebook([_make_plotly_cell()])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))

        strip_mathjax2_from_notebook(nb_path)

        cleaned = json.loads(nb_path.read_text())
        html_parts = cleaned["cells"][0]["outputs"][0]["data"]["text/html"]
        assert "<div>" in html_parts
        assert '<div id="plotly-graph"></div>' in html_parts

    def test_no_modification_when_no_mathjax2(self, tmp_path):
        """Test that notebooks without MathJax 2 are not modified."""
        cell = {
            "cell_type": "code",
            "source": ["print('hello')"],
            "outputs": [
                {
                    "output_type": "display_data",
                    "data": {"text/html": ["<div>No mathjax here</div>"]},
                    "metadata": {},
                }
            ],
            "metadata": {},
        }
        nb = _make_notebook([cell])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))

        result = strip_mathjax2_from_notebook(nb_path)

        assert result is False

    def test_strips_mathjax2_cdn_script_only(self, tmp_path):
        """Test that only the CDN script is stripped (without the config script)."""
        nb = _make_notebook([_make_plotly_cell(PLOTLY_MATHJAX2_SCRIPT)])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))

        result = strip_mathjax2_from_notebook(nb_path)

        assert result is True
        cleaned = json.loads(nb_path.read_text())
        html_parts = cleaned["cells"][0]["outputs"][0]["data"]["text/html"]
        for part in html_parts:
            assert "mathjax/2" not in part

    def test_handles_string_html_output(self, tmp_path):
        """Test handling of text/html as a single string instead of list."""
        cell = {
            "cell_type": "code",
            "source": [],
            "outputs": [
                {
                    "output_type": "display_data",
                    "data": {
                        "text/html": f"<div>{PLOTLY_MATHJAX2_SCRIPT}</div>"
                    },
                    "metadata": {},
                }
            ],
            "metadata": {},
        }
        nb = _make_notebook([cell])
        nb_path = tmp_path / "test.ipynb"
        nb_path.write_text(json.dumps(nb))

        result = strip_mathjax2_from_notebook(nb_path)

        assert result is True
        cleaned = json.loads(nb_path.read_text())
        html = cleaned["cells"][0]["outputs"][0]["data"]["text/html"]
        assert isinstance(html, str)
        assert "mathjax/2" not in html


class TestStripMathjax2FromNotebooks:
    """Tests for _strip_mathjax2_from_notebooks helper."""

    def test_processes_all_notebooks_in_directory(self, tmp_path):
        """Test that all .ipynb files in subdirectories are processed."""
        nb = _make_notebook([_make_plotly_cell()])

        # Create notebooks in nested directories
        (tmp_path / "notebooks" / "pipeline_a").mkdir(parents=True)
        (tmp_path / "notebooks" / "pipeline_b").mkdir(parents=True)

        for subdir in ["pipeline_a", "pipeline_b"]:
            nb_path = tmp_path / "notebooks" / subdir / "test.ipynb"
            nb_path.write_text(json.dumps(nb))

        _strip_mathjax2_from_notebooks(tmp_path)

        for subdir in ["pipeline_a", "pipeline_b"]:
            nb_path = tmp_path / "notebooks" / subdir / "test.ipynb"
            cleaned = json.loads(nb_path.read_text())
            html_parts = cleaned["cells"][0]["outputs"][0]["data"]["text/html"]
            for part in html_parts:
                assert "mathjax/2" not in part


class TestMathjax2Pattern:
    """Tests for the MATHJAX2_PATTERN regex."""

    def test_matches_plotly_mathjax2_cdn_script(self):
        """Test that pattern matches the Plotly MathJax 2 CDN script."""
        assert MATHJAX2_PATTERN.search(PLOTLY_MATHJAX2_SCRIPT)

    def test_matches_plotly_mathjax2_with_config(self):
        """Test that pattern matches MathJax 2 script + SVG config script."""
        assert MATHJAX2_PATTERN.search(PLOTLY_MATHJAX2_SCRIPT_WITH_CONFIG)

    def test_does_not_match_mathjax3(self):
        """Test that pattern does not match MathJax 3 scripts."""
        mathjax3 = '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>'
        assert not MATHJAX2_PATTERN.search(mathjax3)

    def test_does_not_match_unrelated_scripts(self):
        """Test that pattern does not match other script tags."""
        other_script = '<script src="https://cdn.example.com/plotly.min.js"></script>'
        assert not MATHJAX2_PATTERN.search(other_script)
