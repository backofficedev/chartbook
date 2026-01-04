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
