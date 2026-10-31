"""Tests for the two commands that make a site: ``chartbook docs build`` renders
it, and ``chartbook build`` runs the build script first.

``chartbook build`` used to mean what ``chartbook docs build`` means now.
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
    with open(project / "chartbook.toml", "a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n[scripts]\nbuild = {script!r}\n")


def test_docs_command(pipeline_project, monkeypatch):
    """Test the docs command with a fixture-generated project."""
    # Setup paths
    output_dir = pipeline_project / "docs"

    # Change to project directory
    monkeypatch.chdir(pipeline_project)

    # Run the command
    runner = CliRunner()
    result = runner.invoke(main, ["docs", "build", "./docs", "--force-write"])

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
        ["docs", "build", str(output_dir), "--project-dir", str(pipeline_project), "-f"],
    )

    assert result.exit_code == 0, f"Command failed with output: {result.output}"
    assert "Pipeline Specs" in (output_dir / "index.html").read_text(encoding="utf-8")
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
            "build",
            "./docs",
            "-f",
            "--temp-docs-src-dir",
            "./_staging",
            "--docs-build-dir",
            "./_site_build",
        ],
    )

    assert result.exit_code == 0, f"Command failed with output: {result.output}"
    assert "Pipeline Specs" in (pipeline_project / "docs" / "index.html").read_text(encoding="utf-8")


@posix
class TestDocs:
    def test_it_does_not_run_the_build_script(self, pipeline_project, monkeypatch):
        """It renders the site. Building the data is `chartbook run`."""
        _add_script(pipeline_project, "echo ran >> ran.log")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert (pipeline_project / "docs" / "index.html").exists()
        assert not (pipeline_project / "ran.log").exists()


class TestDocsBeforeAnythingIsBuilt:
    """`chartbook docs build` warns about a pipeline that has built nothing, unless --strict was asked for."""

    @pytest.fixture
    def unbuilt(self, pipeline_project, monkeypatch):
        (pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet").unlink()
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        monkeypatch.chdir(pipeline_project)
        return pipeline_project

    def test_by_default_it_warns_and_renders(self, unbuilt):
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "Warning: test_pipeline has built nothing it declares yet" in result.output
        assert (unbuilt / "docs" / "index.html").is_file()

    def test_strict_on_the_command_line_makes_it_an_error(self, unbuilt):
        """`doit && chartbook docs build --strict` in CI: a build that made nothing must fail."""
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--strict"])
        assert result.exit_code == 1
        assert "Missing source files" in result.output
        assert "--no-strict" not in result.output
        assert not (unbuilt / "docs").exists()

    def test_the_help_says_what_strict_typed_does(self):
        """The warning says "With --strict, this is an error"; the help said only "(default)"."""
        said = " ".join(CliRunner().invoke(main, ["docs", "build", "--help"]).output.split())
        assert "a lone pipeline that has built nothing yet, which is rendered with a warning" in said
        assert "typed explicitly, --strict fails on that too" in said

    def test_no_strict_renders_it_too(self, unbuilt):
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--no-strict"])
        assert result.exit_code == 0, result.output
        assert (unbuilt / "docs" / "index.html").is_file()


@posix
class TestBuildRemoved:
    def test_old_build_never_executes_a_script(self, pipeline_project, monkeypatch):
        _add_script(pipeline_project, "echo unexpected > ran.log")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["build", "-f"])
        assert result.exit_code == 2
        assert "chartbook run" in result.output and "chartbook docs build" in result.output
        assert not (pipeline_project / "ran.log").exists()


class TestTheOldNamesSayTheNewOnes:
    """`chartbook docs` was the command that renders, and `chartbook browse` the one that opens;
    `catalog build` and `catalog browse` were the catalog's. Each old spelling is told the new
    one, with the arguments on the line to type, and nothing runs under the old name."""

    def test_docs_with_its_old_arguments(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f"])
        assert result.exit_code == 2
        assert "`chartbook docs` is `chartbook docs build` now. Try: chartbook docs build ./docs -f" in result.output
        assert not (pipeline_project / "docs").exists()

    def test_docs_with_an_old_option_first(self):
        result = CliRunner().invoke(main, ["docs", "-f", "--watch"])
        assert result.exit_code == 2
        assert "Try: chartbook docs build -f --watch" in result.output

    def test_browse(self):
        result = CliRunner().invoke(main, ["browse", "./site"])
        assert result.exit_code == 2
        assert "`chartbook browse` is `chartbook docs open` now. Try: chartbook docs open ./site" in result.output

    def test_catalog_build_and_browse(self):
        result = CliRunner().invoke(main, ["catalog", "generate", "-f"])
        assert result.exit_code == 2
        assert "`chartbook catalog generate` is `chartbook catalog build` now. Try: chartbook catalog build -f" in result.output
        result = CliRunner().invoke(main, ["catalog", "browse"])
        assert result.exit_code == 2
        assert "`chartbook catalog browse` is `chartbook catalog open` now. Try: chartbook catalog open" in result.output

    def test_a_misspelt_subcommand_is_clicks_error_not_a_confident_wrong_line(self):
        """Found by a reviewer: `docs genrate -f` was told to try `docs build genrate -f`, which would render into ./genrate."""
        result = CliRunner().invoke(main, ["docs", "genrate", "-f"])
        assert result.exit_code == 2
        assert "No such command 'genrate'" in result.output and "Try:" not in result.output

    def test_the_hint_names_the_program_as_a_person_types_it(self):
        """Found by a reviewer: under `python -m chartbook.cli` the hint said `chartbook -m chartbook.cli docs`."""
        result = CliRunner().invoke(main, ["docs", "./site", "-f"], prog_name="python -m chartbook.cli")
        assert "`chartbook docs` is `chartbook docs build` now. Try: chartbook docs build ./site -f" in result.output

    def test_shell_completion_is_not_told_off(self):
        """Found by a reviewer: completing `chartbook catalog build --` raised the usage error."""
        from click.shell_completion import CompletionItem, ShellComplete

        completer = ShellComplete(main, {}, "chartbook", "_CHARTBOOK_COMPLETE")
        for words, incomplete in ((["catalog", "build"], "--"), (["docs", "./site"], "-")):
            items = completer.get_completions(words, incomplete)  # must not raise
            assert all(isinstance(item, CompletionItem) for item in items)
        assert "build" in {item.value for item in completer.get_completions(["docs"], "bui")}

    def test_docs_alone_lists_generate_and_open(self):
        result = CliRunner().invoke(main, ["docs"])
        assert "build" in result.output and "open" in result.output

    def test_a_command_that_never_was_is_still_unknown(self):
        result = CliRunner().invoke(main, ["frobnicate"])
        assert result.exit_code == 2
        assert "No such command" in result.output and "Try:" not in result.output
        result = CliRunner().invoke(main, ["catalog", "frobnicate"])
        assert result.exit_code == 2
        assert "No such command" in result.output and "Try:" not in result.output


@posix
class TestCalledFromItsOwnScript:
    """An old build script says `chartbook build` and means "render the site"."""


    def test_run_inside_its_own_script_is_refused(self, pipeline_project, monkeypatch):
        _add_script(pipeline_project, f"echo ran >> ran.log && {CHARTBOOK} run > nested.log 2>&1")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1
        assert (pipeline_project / "ran.log").read_text(encoding="utf-8").split() == ["ran"]
        nested = (pipeline_project / "nested.log").read_text(encoding="utf-8")
        assert "was called from" in nested and "run itself without end" in nested









def test_docs_with_no_manifest_is_a_clean_error(tmp_path, monkeypatch):
    """Found by a reviewer: `chartbook docs build` in a folder with no chartbook.toml raised a
    ValueError traceback, where `chartbook build` says `Error: No chartbook.toml in …`."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
    assert result.exit_code == 1
    assert f"Error: No chartbook.toml in {Path.cwd()}." in result.output
    assert "Traceback" not in result.output and "ValueError" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not (tmp_path / "docs").exists()

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = CliRunner().invoke(main, ["docs", "build", str(tmp_path / "site"), "--project-dir", str(elsewhere), "-f"])
    assert result.exit_code == 1
    assert f"Error: No chartbook.toml in {elsewhere.resolve()}." in result.output

