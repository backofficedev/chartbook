from __future__ import annotations

from pathlib import Path

import click


def _check_sphinx_installed():
    """Check if Sphinx dependencies are installed."""
    try:
        import jinja2  # noqa: F401
        import sphinx  # noqa: F401
    except ImportError:
        click.echo("Error: Sphinx dependencies not installed.", err=True)
        click.echo("", err=True)
        click.echo("Install the full package:", err=True)
        click.echo("    pip install chartbook[all]", err=True)
        click.echo("", err=True)
        click.echo("Or use pipx for isolated installation:", err=True)
        click.echo("    pipx install chartbook[all]", err=True)
        click.echo("    pipx run chartbook[all] build", err=True)
        raise SystemExit(1)


@click.group()
def main():
    """chartbook CLI tool for generating documentation websites."""


@main.command()
@click.argument("output_dir", type=click.Path(), default="./docs", required=False)
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
@click.option(
    "--publish-dir",
    type=click.Path(),
    default="./_output/to_be_published/",
    help="Directory where files will be published",
)
@click.option(
    "--docs-build-dir",
    type=click.Path(),
    default="./_docs",
    help="Directory where documentation will be built",
)
@click.option(
    "--temp-docs-src-dir",
    type=click.Path(),
    default="./_docs_src",
    help="Directory where documentation source files are temporarily stored in two stage procedure",
)
@click.option(
    "--keep-build-dirs",
    is_flag=True,
    default=False,
    help="Keep temporary build directory after generation",
)
@click.option(
    "--force-write",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing output directory by deleting it first",
)
@click.option(
    "--size-threshold",
    type=float,
    default=50,
    help="File size threshold in MB above which to use memory-efficient loading (default: 50)",
)
def build(
    output_dir,
    project_dir,
    publish_dir,
    docs_build_dir,
    temp_docs_src_dir,
    keep_build_dirs,
    force_write,
    size_threshold,
):
    """Generate HTML documentation in the specified output directory."""
    # Check for Sphinx dependencies
    _check_sphinx_installed()

    # Import here to avoid loading Sphinx deps at module level
    from chartbook.build_docs import generate_docs

    # Convert output_dir to Path
    output_dir = Path(output_dir).resolve()

    # Prevent deleting the current working directory
    if output_dir == Path.cwd():
        raise click.UsageError(
            "Output directory cannot be the current directory '.' to prevent accidental project deletion"
        )

    # Check if output directory exists and prompt for confirmation
    if output_dir.exists() and not force_write and any(output_dir.iterdir()):
        if not click.confirm(
            f"Directory '{output_dir}' already exists. Do you want to overwrite it?\n"
            "(add the -f/--force option to overwrite without prompting)",
            default=False,
        ):
            raise SystemExit(0)
        force_write = True

    # If project_dir not provided, use current directory
    project_dir = resolve_project_dir(project_dir)
    # Check for config file and create if needed
    config_path = project_dir / "chartbook.toml"
    if not config_path.exists():
        raise ValueError(f"Could not find chartbook.toml at {config_path}")

    # Store whether we need to remove existing directory after successful generation
    should_remove_existing = output_dir.exists() and force_write

    generate_docs(
        output_dir=output_dir,
        project_dir=project_dir,
        publish_dir=publish_dir,
        _docs_dir=docs_build_dir,
        temp_docs_src_dir=temp_docs_src_dir,
        keep_build_dirs=keep_build_dirs,
        should_remove_existing=should_remove_existing,
        size_threshold=size_threshold,
    )
    click.echo(f"Successfully generated documentation in {output_dir}")


@main.command()
@click.option(
    "--publish-dir",
    type=click.Path(),
    default=None,
    help="Directory where files will be published",
)
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose output",
)
def publish(publish_dir: Path | str | None, project_dir: Path | str, verbose: bool):
    """Publish the documentation to the specified output directory.

    If no publish directory is provided, a default local directory will be used.
    """
    # Check for Sphinx dependencies
    _check_sphinx_installed()

    # Import here to avoid loading Sphinx deps at module level
    from chartbook.manifest import load_manifest
    from chartbook.publish import publish_pipeline

    project_dir = resolve_project_dir(project_dir)
    manifest = load_manifest(base_dir=project_dir)
    pipeline_id = manifest["pipeline"]["id"]

    if publish_dir is None:
        BASE_DIR = Path(".").resolve()
        publish_dir = BASE_DIR / Path("./_output/to_be_published")
    else:
        publish_dir = Path(publish_dir) / pipeline_id

    # if publish_dir is a relative path, convert it to an absolute path relative to the project directory
    if not publish_dir.is_absolute():
        publish_dir = project_dir / Path(publish_dir)
    publish_pipeline(publish_dir=publish_dir, base_dir=project_dir, verbose=verbose)


def resolve_project_dir(project_dir: Path | None):
    if project_dir is None:
        project_dir = Path.cwd()
    else:
        project_dir = Path(project_dir).resolve()
    return project_dir


@main.command()
@click.option(
    "--no-samples",
    is_flag=True,
    default=False,
    help="Exclude sample values sections from the report",
)
@click.option(
    "--no-stats",
    is_flag=True,
    default=False,
    help="Exclude numeric column statistics sections from the report",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(),
    default=None,
    help="Directory to save the output file (default: current directory)",
)
@click.option(
    "--size-threshold",
    type=float,
    default=50,
    help="File size threshold in MB above which to use memory-efficient loading (default: 50)",
)
def create_data_glimpses(no_samples, no_stats, output_dir, size_threshold):
    """Create a data glimpses report from dodo.py tasks.

    This command parses the dodo.py file in the current directory to find all
    CSV/Parquet files and creates a comprehensive data glimpse report in Markdown format.

    Example usage:
        chartbook create-data-glimpses
        chartbook create-data-glimpses --no-samples
        chartbook create-data-glimpses --no-samples --no-stats
        chartbook create-data-glimpses -o ./docs/
        chartbook create-data-glimpses --size-threshold 100
    """
    from chartbook.create_data_glimpses import main as create_data_glimpses_main

    try:
        create_data_glimpses_main(
            output_dir=output_dir,
            no_samples=no_samples,
            no_stats=no_stats,
            size_threshold=size_threshold,
        )
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        import sys

        sys.exit(1)
    except Exception as e:
        click.echo(f"Error generating data glimpses: {e}", err=True)
        import sys

        sys.exit(1)


if __name__ == "__main__":
    main()
