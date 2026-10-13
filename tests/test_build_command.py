"""Tests for the two commands that make a site: ``chartbook docs`` renders
it, and ``chartbook build`` runs the build script first.

``chartbook build`` used to mean what ``chartbook docs`` means now.
"""

import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import run
from chartbook.cli import main

posix = pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")
CHARTBOOK = Path(sys.executable).with_name("chartbook")


def _add_script(project: Path, script: str) -> None:
    """Give a project a build script, in its chartbook.toml."""
    with open(project / "chartbook.toml", "a") as f:
        f.write(f"\n[scripts]\nbuild = {script!r}\n")


def test_docs_command(pipeline_project, monkeypatch):
    """Test the docs command with a fixture-generated project."""
    # Setup paths
    output_dir = pipeline_project / "docs"

    # Change to project directory
    monkeypatch.chdir(pipeline_project)

    # Run the command
    runner = CliRunner()
    result = runner.invoke(main, ["docs", "./docs", "--force-write"])

    # Debug output
    print("Command output:", result.output)
    print("Exception:", result.exception)

    # Check command success
    assert result.exit_code == 0, f"Command failed with output: {result.output}"

    # Verify output file
    html_file = output_dir / "index.html"
    assert html_file.exists(), "HTML output not generated"
    assert html_file.stat().st_size > 0, "HTML file is empty"


def test_docs_from_another_directory(pipeline_project, tmp_path, monkeypatch):
    """--project-dir is enough: the build need not be run from inside the project.

    The pipeline's front page used to include a template by a path that
    spelled out the default name of the intermediate directory, which only
    resolved when that directory sat inside the project.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    output_dir = tmp_path / "site"

    result = CliRunner().invoke(
        main,
        ["docs", str(output_dir), "--project-dir", str(pipeline_project), "-f"],
    )

    assert result.exit_code == 0, f"Command failed with output: {result.output}"
    assert "Pipeline Specs" in (output_dir / "index.html").read_text()
    # Nothing is left behind where the command was run. (Under `hatch test
    # --cover` the Sphinx subprocess writes its coverage data file there.)
    left_behind = [p.name for p in elsewhere.iterdir() if not p.name.startswith(".coverage")]
    assert left_behind == []


def test_docs_with_a_renamed_intermediate_directory(pipeline_project, monkeypatch):
    """--temp-docs-src-dir may be any name, not only the default ``_docs_src``."""
    monkeypatch.chdir(pipeline_project)

    result = CliRunner().invoke(
        main,
        [
            "docs",
            "./docs",
            "-f",
            "--temp-docs-src-dir",
            "./_staging",
            "--docs-build-dir",
            "./_site_build",
        ],
    )

    assert result.exit_code == 0, f"Command failed with output: {result.output}"
    assert "Pipeline Specs" in (pipeline_project / "docs" / "index.html").read_text()


@posix
class TestDocs:
    def test_it_does_not_run_the_build_script(self, pipeline_project, monkeypatch):
        """It renders the site. Building the data is `chartbook run`."""
        _add_script(pipeline_project, "echo ran >> ran.log")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert (pipeline_project / "docs" / "index.html").exists()
        assert not (pipeline_project / "ran.log").exists()


@posix
class TestBuild:
    """`chartbook build` is `chartbook run`, then `chartbook docs`."""

    def test_it_runs_the_script_and_then_renders_the_site(self, pipeline_project, monkeypatch):
        # The script checks that the site is not there yet: it runs first
        _add_script(pipeline_project, "test ! -e docs/index.html && echo ran >> ran.log")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert (pipeline_project / "ran.log").read_text().split() == ["ran"]
        assert (pipeline_project / "docs" / "index.html").exists()
        said = result.output.splitlines()
        ran = said.index("Ran build in 1 pipeline(s).")
        rendered = [i for i, line in enumerate(said) if line.startswith("Successfully generated")]
        assert rendered and ran < rendered[0]

    def test_it_takes_the_arguments_of_docs(self, pipeline_project, tmp_path, monkeypatch):
        _add_script(pipeline_project, "echo ran >> ran.log")
        monkeypatch.chdir(tmp_path)
        site = tmp_path / "site"
        result = CliRunner().invoke(
            main, ["build", str(site), "--project-dir", str(pipeline_project), "-f"]
        )
        assert result.exit_code == 0, result.output
        assert (site / "index.html").exists()
        assert (pipeline_project / "ran.log").exists()

    def test_with_no_build_script_only_the_site_is_rendered(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "No `build` script here, so only the site is rendered." in result.output
        assert (pipeline_project / "docs" / "index.html").exists()

    def test_a_script_that_fails_stops_it_before_the_site(self, pipeline_project, monkeypatch):
        _add_script(pipeline_project, "exit 4")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 4
        assert "its 'build' script exited with 4" in result.output
        assert not (pipeline_project / "docs").exists()

    def test_in_a_catalog_each_pipeline_is_built_and_then_the_catalogs_site(
        self, catalog_project, monkeypatch
    ):
        for name in ("pipeline_a", "pipeline_b"):
            _add_script(catalog_project / "pipelines" / name, "echo ran >> ran.log")
        monkeypatch.chdir(catalog_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "Ran build in 2 pipeline(s)." in result.output
        for name in ("pipeline_a", "pipeline_b"):
            assert (catalog_project / "pipelines" / name / "ran.log").exists()
        assert (catalog_project / "docs" / "index.html").exists()

    def test_no_manifest_is_a_clean_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 1
        assert "No chartbook.toml in" in result.output


@posix
class TestCalledFromItsOwnScript:
    """An old build script says `chartbook build` and means "render the site"."""

    def test_build_inside_its_own_build_script_renders_and_says_so(
        self, pipeline_project, monkeypatch
    ):
        """It must not run the script that called it, or it would never end."""
        _add_script(
            pipeline_project,
            f"echo ran >> ran.log && {CHARTBOOK} build ./docs -f > nested.log 2>&1",
        )
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert (pipeline_project / "ran.log").read_text().split() == ["ran"]  # once
        nested = (pipeline_project / "nested.log").read_text()
        assert "Warning: `chartbook build` was called from this pipeline's own build script." in nested
        assert "In a build script, say `chartbook docs`." in nested
        assert "Successfully generated documentation" in nested

    def test_run_inside_its_own_script_is_refused(self, pipeline_project, monkeypatch):
        _add_script(pipeline_project, f"echo ran >> ran.log && {CHARTBOOK} run > nested.log 2>&1")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1
        assert (pipeline_project / "ran.log").read_text().split() == ["ran"]
        nested = (pipeline_project / "nested.log").read_text()
        assert "was called from" in nested and "run itself without end" in nested

    def test_docs_inside_a_build_script_is_the_ordinary_thing(self, pipeline_project, monkeypatch):
        _add_script(pipeline_project, f"{CHARTBOOK} docs ./docs -f > nested.log 2>&1")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 0, result.output
        assert "Warning" not in (pipeline_project / "nested.log").read_text()
        assert (pipeline_project / "docs" / "index.html").exists()

    def test_a_script_is_told_which_pipeline_and_script_it_is(self, tmp_path):
        code = run.execute(
            'echo "$CHARTBOOK_RUN_SCRIPT in $CHARTBOOK_RUN_DIR" > told.txt', tmp_path, "build"
        )
        assert code == 0
        assert (tmp_path / "told.txt").read_text().strip() == f"build in {tmp_path.resolve()}"

    def test_running(self, tmp_path, monkeypatch):
        assert not run.running(tmp_path, "build")
        monkeypatch.setenv(run.RUN_DIR_ENV_VAR, str(tmp_path))
        monkeypatch.setenv(run.RUN_SCRIPT_ENV_VAR, "build")
        assert run.running(tmp_path, "build")
        assert not run.running(tmp_path, "test")  # another script of the same pipeline
        assert not run.running(tmp_path / "other", "build")  # the same script of another

