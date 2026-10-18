"""
Integration tests for the generator module.

Tests the full documentation generation workflow:
generate_docs() -> load_manifest() -> _retrieve_correct_docs_src_dir() ->
run_build_markdown() -> run_sphinx_build()
"""

import os
import re
import sys
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

        # Verify Sphinx was called with correct arguments: this interpreter's
        # own Sphinx, not whichever sphinx-build is first on PATH
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[:3] == [sys.executable, "-m", "sphinx"]
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

    def test_no_strict_skips_pipelines_with_missing_files(
        self, catalog_project, monkeypatch, capsys
    ):
        """Test that with --no-strict, pipelines with missing files are skipped."""
        output_dir = catalog_project / "docs_test"
        monkeypatch.chdir(catalog_project)

        # Delete a chart file from pipeline_a to trigger missing file detection
        chart_files = list(
            (catalog_project / "pipelines" / "pipeline_a" / "_output" / "charts").glob("*.html")
        )
        assert len(chart_files) > 0, "Fixture should create chart HTML files"
        chart_files[0].unlink()

        # Explicit strict=False should succeed, skipping pipeline_a
        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            keep_build_dirs=False,
            strict=False,
        )

        # Build should succeed
        assert output_dir.exists()
        assert (output_dir / "index.html").exists()

        # Warning about skipping should appear on stderr
        captured = capsys.readouterr()
        assert "Skipping pipeline 'pipeline_a'" in captured.err

    def test_default_strict_errors_on_missing_files(
        self, catalog_project, monkeypatch
    ):
        """Test that the default (strict=True) causes exit on missing files."""
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
            )
        assert exc_info.value.code == 1

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

    def test_format_cli_message_mentions_no_strict(self):
        """Test that the CLI error message references --no-strict."""
        from chartbook.errors import MissingFile, MissingSourceFilesError

        missing = [
            MissingFile(Path("/a.parquet"), "dataframe", "df1", "pipeline_a"),
        ]
        error = MissingSourceFilesError(missing)
        message = error.format_cli_message()
        assert "--no-strict" in message

    def test_a_hint_given_is_the_hint(self):
        """A lone pipeline's hint does not offer --no-strict, which it refuses."""
        from chartbook.errors import MissingFile, MissingSourceFilesError

        missing = [MissingFile(Path("/a.parquet"), "dataframe", "df1", "pipeline_a")]
        message = MissingSourceFilesError(missing, hint=["First line.", "Second line."]).format_cli_message()
        assert "First line." in message
        assert "      Second line." in message
        assert "--no-strict" not in message


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


class TestSmallFixes:
    """Regressions for bugs found while building P0."""

    def test_no_strict_on_a_single_pipeline_is_a_clean_error(
        self, pipeline_project, monkeypatch, capsys
    ):
        """Used to crash with UnboundLocalError once the only pipeline was skipped."""
        monkeypatch.chdir(pipeline_project)
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        with pytest.raises(SystemExit) as excinfo:
            generate_docs(
                output_dir=pipeline_project / "docs",
                project_dir=pipeline_project,
                strict=False,
            )
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "Skipping pipeline 'test_pipeline'" in err
        assert "nothing left to build" in err

    def test_importing_chartbook_leaves_shutil_alone(self):
        """chartbook used to replace shutil.copy2 and friends process-wide."""
        import subprocess

        code = (
            "import shutil\n"
            "before = (shutil.copy2, shutil.copystat, shutil.copymode)\n"
            "import chartbook, chartbook.utils, chartbook.build_docs\n"
            "assert before == (shutil.copy2, shutil.copystat, shutil.copymode)\n"
            "assert shutil.copy2 is not shutil.copy\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_copy_tree_merges_and_copies_contents(self, tmp_path):
        from chartbook.utils import copy_file, copy_tree, move_tree

        source = tmp_path / "source"
        (source / "nested").mkdir(parents=True)
        (source / "a.txt").write_text("a")
        (source / "nested" / "b.txt").write_text("b")
        destination = tmp_path / "destination"
        destination.mkdir()
        (destination / "kept.txt").write_text("kept")
        (destination / "a.txt").write_text("old")

        copy_tree(source, destination)
        assert (destination / "a.txt").read_text() == "a"
        assert (destination / "nested" / "b.txt").read_text() == "b"
        assert (destination / "kept.txt").read_text() == "kept"

        copy_file(source / "a.txt", tmp_path / "copy.txt")
        assert (tmp_path / "copy.txt").read_text() == "a"

        move_tree(destination, tmp_path / "moved")
        assert not destination.exists()
        assert (tmp_path / "moved" / "nested" / "b.txt").read_text() == "b"

    def test_readme_setting_is_honoured_by_the_build(self, pipeline_project, monkeypatch):
        """project.readme used to be read only by `publish`."""
        import tomli
        import tomli_w

        monkeypatch.chdir(pipeline_project)
        (pipeline_project / "README.md").rename(pipeline_project / "ABOUT.md")
        (pipeline_project / "ABOUT.md").write_text(
            "# Test Pipeline\n\nText from the configured readme.\n"
        )
        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["project"]["readme"] = "./ABOUT.md"
        toml_path.write_bytes(tomli_w.dumps(config).encode())

        output_dir = pipeline_project / "docs"
        generate_docs(output_dir=output_dir, project_dir=pipeline_project)
        assert "Text from the configured readme." in (output_dir / "index.html").read_text()

    def test_pipeline_site_builds_without_dangling_toctree_warnings(
        self, pipeline_project, monkeypatch
    ):
        from chartbook import build_docs

        monkeypatch.chdir(pipeline_project)
        captured = {}
        real_run = build_docs.subprocess.run

        def spy(cmd, **kwargs):
            result = real_run(cmd, **kwargs)
            captured["stderr"] = result.stderr
            return result

        monkeypatch.setattr(build_docs.subprocess, "run", spy)
        generate_docs(output_dir=pipeline_project / "docs", project_dir=pipeline_project)
        assert "nonexisting document" not in captured["stderr"]


class TestNotBuiltYet:
    """A pipeline that has built nothing it declares still has a site.

    A project just made by `chartbook init` is one, and so is any fresh
    clone of a pipeline whose data is git-ignored. `chartbook docs` used to
    stop there, and its hint offered --no-strict, which a lone pipeline
    refuses.
    """

    @pytest.fixture
    def unbuilt(self, pipeline_project, monkeypatch):
        """The fixture's pipeline, with a notebook and a build script, and none of its outputs."""
        import tomli
        import tomli_w

        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["notebooks"] = {"walkthrough": {"name": "Walkthrough", "path": "_output/walkthrough.ipynb"}}
        config["models"] = {"forecast": {"name": "Forecast", "path": "_models/forecast.json"}}
        config["scripts"] = {"build": "true"}
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        (pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet").unlink()
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        monkeypatch.chdir(pipeline_project)
        return pipeline_project

    def test_its_site_shows_each_output_as_not_built(self, unbuilt, capsys):
        output_dir = unbuilt / "docs"
        generate_docs(output_dir=output_dir, project_dir=unbuilt)

        assert (output_dir / "index.html").is_file()
        # Where each one's page links, a page that says so
        notebook = output_dir / "cb" / "notebooks" / "test_pipeline" / "walkthrough.html"
        assert "Not built yet" in notebook.read_text()
        assert "Not built yet" in (output_dir / "_static" / "test_pipeline" / "chart_0_0.html").read_text()
        # The glimpse is highlighted, a span a word
        dataframe = re.sub(
            r"<[^>]+>", "", (output_dir / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html").read_text()
        )
        assert "Not built yet" in dataframe
        assert "Error reading file" not in dataframe
        # No dates to give, rather than "None": the row is left out
        assert not re.search(r"Data available up to \((min|max)\)\s*None", dataframe)
        # A model says so in its provenance panel
        model = re.sub(r"<[^>]+>", "", (output_dir / "cb" / "models" / "test_pipeline" / "forecast.html").read_text())
        assert re.search(r"Content\s+not built", model)
        # The index has the records, without hashes
        records = {r["id"]: r for r in json.loads((output_dir / "index.json").read_text())["records"]}
        for asset in (
            "test_pipeline:dataframe_0",
            "test_pipeline:chart/chart_0_0",
            "test_pipeline:notebook/walkthrough",
            "test_pipeline:model/forecast",
        ):
            assert "content_hash" not in records[asset]
        err = capsys.readouterr().err
        assert "Warning: test_pipeline has built nothing it declares yet" in err
        assert "  - notebook: _output/walkthrough.ipynb" in err
        assert "`chartbook build` runs its build script" in err
        assert "With --strict, this is an error." in err

    def test_with_strict_it_is_an_error(self, unbuilt, capsys):
        """`--strict` asked for, as CI does after a build that should have made everything."""
        with pytest.raises(SystemExit) as excinfo:
            generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt, strict=True)
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "Missing source files" in err
        assert "Ensure these files exist or update the paths in chartbook.toml." in err
        assert "--no-strict" not in err
        assert not (unbuilt / "docs").exists()

    def test_with_no_strict_it_is_rendered_too(self, unbuilt):
        """--no-strict skips a pipeline; one that has built nothing is not skipped, it is shown."""
        generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt, strict=False)
        assert (unbuilt / "docs" / "index.html").is_file()

    def test_nothing_to_download_from_a_dataframe_not_built(self, unbuilt):
        """The download row linked to a file the build had not copied: a dead link, and MkDocs warned."""
        import tomli
        import tomli_w

        toml_path = unbuilt / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["project"]["enable_data_download"] = True
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        output_dir = unbuilt / "docs"
        generate_docs(output_dir=output_dir, project_dir=unbuilt)
        for page in (
            output_dir / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html",
            output_dir / "cb" / "charts" / "test_pipeline.chart_0_0.html",
        ):
            assert "Download Data as Parquet" not in page.read_text(), page
            assert "download_dataframe" not in page.read_text(), page

    def test_in_a_version_from_the_store_it_gives_no_advice(self, unbuilt, monkeypatch):
        """A version's site is built from the store: it is as it was made, and `chartbook build` builds nothing of it."""
        from chartbook.config import UNTRUSTED_ENV_VAR

        monkeypatch.setenv(UNTRUSTED_ENV_VAR, "1")
        output_dir = unbuilt / "docs"
        generate_docs(output_dir=output_dir, project_dir=unbuilt)
        notebook = (output_dir / "cb" / "notebooks" / "test_pipeline" / "walkthrough.html").read_text()
        chart = (output_dir / "_static" / "test_pipeline" / "chart_0_0.html").read_text()
        dataframe = re.sub(
            r"<[^>]+>", "", (output_dir / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html").read_text()
        )
        for page in (notebook, chart, dataframe):
            assert "Not built in this version" in page
            assert "chartbook build" not in page

    def test_with_no_build_script_it_says_to_build_it(self, unbuilt, capsys):
        import tomli
        import tomli_w

        toml_path = unbuilt / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        del config["scripts"]
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt)
        assert "Build them, then run `chartbook docs` again." in capsys.readouterr().err

    def test_after_its_build_script_has_run_it_is_an_error(self, unbuilt, capsys):
        """`chartbook build` says this: the build has just run, and made none of it."""
        with pytest.raises(SystemExit) as excinfo:
            generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt, after_build=True)
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "Missing source files" in err
        assert "The build script has just run and did not make" in err
        # doit's tasks after the `default_tasks` block of the template's dodo.py are not run
        assert "A task the build tool does not run by default is not built" in err
        assert "--no-strict" not in err
        assert not (unbuilt / "docs").exists()

    def test_built_in_part_is_still_an_error_and_the_hint_is_the_build(self, unbuilt, capsys):
        """One output there means it was built, so what is missing is a mistake."""
        (unbuilt / "_output" / "walkthrough.ipynb").write_text(
            json.dumps({"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 4})
        )
        with pytest.raises(SystemExit) as excinfo:
            generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt)
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "dataframe_0.parquet" in err and "chart_0_0.html" in err
        assert "`chartbook build` runs the build script" in err
        # A lone pipeline has nothing left to build once it is skipped
        assert "--no-strict" not in err

    @pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0, reason="needs a file its owner cannot read")
    @pytest.mark.parametrize(
        "unreadable", ["_output/charts/chart_0_0.html", "_data/test_pipeline/dataframe_0.parquet"]
    )
    def test_an_output_that_is_there_and_unreadable_is_an_error(self, pipeline_project, monkeypatch, capsys, unreadable):
        """It has no hash, as a file that is not there has none, but it is there: the build stops and names it.

        A dataframe's page used to say "Error reading file" with exit 0, and
        its provenance panel "not built".
        """
        monkeypatch.chdir(pipeline_project)
        output = pipeline_project / unreadable
        output.chmod(0)
        try:
            with pytest.raises(SystemExit) as excinfo:
                generate_docs(output_dir=pipeline_project / "docs", project_dir=pipeline_project)
        finally:
            output.chmod(0o644)
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "These files are there and could not be read:" in err
        assert unreadable in err
        assert not (pipeline_project / "docs").exists()

    def test_with_downloads_only_a_file_the_build_copies_is_linked(self, pipeline_project, monkeypatch):
        """A folder of parts or a glob has no one file to download: the row linked to nothing."""
        import tomli
        import tomli_w

        parts = pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        frame = parts.read_bytes()
        parts.unlink()
        parts.mkdir()
        (parts / "part-0.parquet").write_bytes(frame)
        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["project"]["enable_data_download"] = True
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        monkeypatch.chdir(pipeline_project)
        output_dir = pipeline_project / "docs"
        generate_docs(output_dir=output_dir, project_dir=pipeline_project)
        page = (output_dir / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html").read_text()
        assert "Download Data as Parquet" not in page
        assert "Download Data as Parquet" not in (output_dir / "cb" / "charts" / "test_pipeline.chart_0_0.html").read_text()

    def test_a_date_that_cannot_be_read_is_not_shown_as_none(self, pipeline_project, monkeypatch):
        import tomli
        import tomli_w

        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["dataframes"]["dataframe_0"]["date_col"] = "no_such_column"
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        monkeypatch.chdir(pipeline_project)
        output_dir = pipeline_project / "docs"
        generate_docs(output_dir=output_dir, project_dir=pipeline_project)
        page = re.sub(r"<[^>]+>", "", (output_dir / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.html").read_text())
        # The row is left out, rather than saying "None"
        assert not re.search(r"Data available up to \((min|max)\)\s*None", page)

    def test_a_glob_that_matches_only_folders_is_missing(self, pipeline_project, monkeypatch, capsys):
        """The index finds no files in it, so neither may the check: it was "not built", exit 0, even with --strict."""
        import tomli
        import tomli_w

        (pipeline_project / "_data" / "test_pipeline" / "parts" / "a.parquet").mkdir(parents=True)
        toml_path = pipeline_project / "chartbook.toml"
        config = tomli.loads(toml_path.read_text())
        config["dataframes"]["dataframe_0"]["path"] = "_data/test_pipeline/parts/*.parquet"
        toml_path.write_bytes(tomli_w.dumps(config).encode())
        monkeypatch.chdir(pipeline_project)
        with pytest.raises(SystemExit):
            generate_docs(output_dir=pipeline_project / "docs", project_dir=pipeline_project, strict=True)
        assert "parts/*.parquet" in capsys.readouterr().err

    def test_a_missing_write_up_is_still_an_error(self, unbuilt, capsys):
        """Nothing builds a write-up."""
        (unbuilt / "docs_src" / "charts" / "chart_0_0.md").unlink()
        with pytest.raises(SystemExit):
            generate_docs(output_dir=unbuilt / "docs", project_dir=unbuilt)
        assert "chart_0_0.md" in capsys.readouterr().err

    def test_a_catalog_keeps_its_own_rules(self, catalog_project, monkeypatch, capsys):
        """A catalog member that has built nothing is skipped by --no-strict, and stops a strict build."""
        monkeypatch.chdir(catalog_project)
        for built in (catalog_project / "pipelines" / "pipeline_a").glob("_*/**/*.*"):
            if built.suffix in (".parquet", ".html"):
                built.unlink()
        with pytest.raises(SystemExit):
            generate_docs(output_dir=catalog_project / "docs_test", project_dir=Path("."))
        assert "--no-strict" in capsys.readouterr().err


class TestBuiltNothing:
    """`built_nothing`: every output of one pipeline is missing, and nothing else is."""

    def _missing(self, *files):
        from chartbook.errors import MissingFile

        return [MissingFile(Path(f"/p/{name}"), kind, name, "p") for kind, name in files]

    def _manifest(self):
        return {
            "project": {"type": "pipeline", "id": "p"},
            "dataframes": {"a": {"path": "a.parquet"}, "q": {"source": "local", "query": "select 1"}},
            "charts": {"c": {"path": "c.html", "docs_path": "c.md"}},
            "notebooks": {},
            "models": {"m": {"path": "m.json", "metrics_path": "m_scores.json"}},
        }

    def test_all_of_them(self):
        from chartbook import conf_validation

        missing = self._missing(("dataframe", "a"), ("chart", "c"), ("model", "m"), ("model_metrics", "m"))
        assert conf_validation.built_nothing(self._manifest(), missing)

    def test_some_of_them(self):
        from chartbook import conf_validation

        missing = self._missing(("dataframe", "a"), ("chart", "c"), ("model", "m"))
        assert not conf_validation.built_nothing(self._manifest(), missing)

    def test_with_a_write_up(self):
        from chartbook import conf_validation

        missing = self._missing(
            ("dataframe", "a"), ("chart", "c"), ("model", "m"), ("model_metrics", "m"), ("chart_docs", "c")
        )
        assert not conf_validation.built_nothing(self._manifest(), missing)

    def test_nothing_missing(self):
        from chartbook import conf_validation

        assert not conf_validation.built_nothing(self._manifest(), [])


class TestAWriteUpIsTextOnThePage:
    """What the author wrote is what the built page shows.

    The writer keeps Jinja syntax in a write-up as characters
    (tests/test_writer_sphinx.py); Sphinx, with MyST's `substitution`
    extension on, then evaluated every `{{ … }}` on the page through a Jinja
    environment that reaches Python. The extension is off, and this is the
    check on the built HTML.
    """

    MARKERS = "WRITEUP-TEST-A: {{ 6+7 }}\n\nWRITEUP-TEST-B: {{ env.srcdir }}\n"

    def _add_markers(self, pipeline_project):
        import tomli

        manifest = tomli.loads((pipeline_project / "chartbook.toml").read_text())
        docs_path = next(iter(manifest["dataframes"].values()))["docs_path"]
        with open(pipeline_project / docs_path, "a", encoding="utf-8") as f:
            f.write("\n\n" + self.MARKERS)
        with open(pipeline_project / "README.md", "a", encoding="utf-8") as f:
            f.write("\n\nREADME-TEST: {{ 6+7 }}\n")

    @staticmethod
    def _built_html(output_dir):
        return "\n".join(page.read_text(encoding="utf-8") for page in output_dir.rglob("*.html"))

    def _build(self, pipeline_project, monkeypatch):
        self._add_markers(pipeline_project)
        monkeypatch.chdir(pipeline_project)
        generate_docs(output_dir=pipeline_project / "docs_test", project_dir=Path("."), keep_build_dirs=False)
        return self._built_html(pipeline_project / "docs_test")

    def test_jinja_in_a_write_up_and_a_readme_is_shown_as_written(self, pipeline_project, monkeypatch):
        html = self._build(pipeline_project, monkeypatch)
        assert "WRITEUP-TEST-A: {{ 6+7 }}" in html
        assert "WRITEUP-TEST-B: {{ env.srcdir }}" in html
        assert "README-TEST: {{ 6+7 }}" in html
        assert "WRITEUP-TEST-A: 13" not in html
        assert "README-TEST: 13" not in html
        assert "WRITEUP-TEST-B: /" not in html

    def test_and_in_a_build_of_files_from_a_store(self, pipeline_project, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
        html = self._build(pipeline_project, monkeypatch)
        assert "WRITEUP-TEST-A: {{ 6+7 }}" in html
        assert "WRITEUP-TEST-A: 13" not in html
        assert "WRITEUP-TEST-B: {{ env.srcdir }}" in html
