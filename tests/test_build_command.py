from click.testing import CliRunner

from chartbook.cli import main


def test_build_command(pipeline_project, monkeypatch):
    """Test build command with a fixture-generated project."""
    # Setup paths
    output_dir = pipeline_project / "docs"

    # Change to project directory
    monkeypatch.chdir(pipeline_project)

    # Run the command
    runner = CliRunner()
    result = runner.invoke(main, ["build", "./docs", "--force-write"])

    # Debug output
    print("Command output:", result.output)
    print("Exception:", result.exception)

    # Check command success
    assert result.exit_code == 0, f"Command failed with output: {result.output}"

    # Verify output file
    html_file = output_dir / "index.html"
    assert html_file.exists(), "HTML output not generated"
    assert html_file.stat().st_size > 0, "HTML file is empty"


def test_build_from_another_directory(pipeline_project, tmp_path, monkeypatch):
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
        ["build", str(output_dir), "--project-dir", str(pipeline_project), "-f"],
    )

    assert result.exit_code == 0, f"Command failed with output: {result.output}"
    assert "Pipeline Specs" in (output_dir / "index.html").read_text()
    # Nothing is left behind where the command was run
    assert list(elsewhere.iterdir()) == []


def test_build_with_a_renamed_intermediate_directory(pipeline_project, monkeypatch):
    """--temp-docs-src-dir may be any name, not only the default ``_docs_src``."""
    monkeypatch.chdir(pipeline_project)

    result = CliRunner().invoke(
        main,
        [
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
    assert "Pipeline Specs" in (pipeline_project / "docs" / "index.html").read_text()
