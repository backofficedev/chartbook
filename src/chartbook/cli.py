from __future__ import annotations

from pathlib import Path

import click

from chartbook.__about__ import __version__


def _check_sphinx_installed():
    """Check if Sphinx dependencies are installed.

    :raises SystemExit: If Sphinx dependencies are not installed.
    """
    try:
        import jinja2  # noqa: F401
        import sphinx  # noqa: F401
    except ImportError:
        click.echo("Error: Sphinx dependencies not installed.", err=True)
        click.echo("", err=True)
        click.echo("Install the full package:", err=True)
        click.echo('    pip install "chartbook[all]"', err=True)
        click.echo("", err=True)
        click.echo("Or use pipx for isolated installation:", err=True)
        click.echo('    pipx install "chartbook[all]"', err=True)
        click.echo('    pipx run "chartbook[all]" build', err=True)
        raise SystemExit(1)


@click.group()
@click.version_option(version=__version__)
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
@click.option(
    "--warn-missing",
    is_flag=True,
    default=False,
    help="Warn instead of error when source files (charts, notebooks, dataframes) are missing",
)
@click.option(
    "--strip-mathjax2/--no-strip-mathjax2",
    default=True,
    help="Strip Plotly's MathJax 2 scripts from notebook outputs to prevent conflicts with Sphinx's MathJax 3 (default: enabled)",
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
    warn_missing,
    strip_mathjax2,
):
    """Generate HTML documentation in the specified output directory.

    :param output_dir: Directory where output will be generated.
    :type output_dir: str
    :param project_dir: Root directory of the project.
    :type project_dir: str
    :param publish_dir: Directory where files will be published.
    :type publish_dir: str
    :param docs_build_dir: Directory where documentation will be built.
    :type docs_build_dir: str
    :param temp_docs_src_dir: Temporary directory for documentation source files.
    :type temp_docs_src_dir: str
    :param keep_build_dirs: If True, keeps temporary build directory after generation.
    :type keep_build_dirs: bool
    :param force_write: If True, overwrites existing output directory.
    :type force_write: bool
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param warn_missing: If True, warn instead of error when source files are missing.
    :type warn_missing: bool
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs.
    :type strip_mathjax2: bool
    """
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
        warn_missing=warn_missing,
        strip_mathjax2=strip_mathjax2,
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

    :param publish_dir: Directory where files will be published.
    :type publish_dir: Path or str, optional
    :param project_dir: Root directory of the project.
    :type project_dir: Path or str
    :param verbose: If True, enables verbose output.
    :type verbose: bool
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
    """Resolve the project directory to an absolute path.

    :param project_dir: The project directory path, or None to use cwd.
    :type project_dir: Path, optional
    :returns: The resolved absolute path to the project directory.
    :rtype: Path
    """
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

    :param no_samples: If True, exclude sample values sections from the report.
    :type no_samples: bool
    :param no_stats: If True, exclude numeric column statistics sections from the report.
    :type no_stats: bool
    :param output_dir: Directory to save the output file.
    :type output_dir: str, optional
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float

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


# =============================================================================
# ls command group - List catalog objects
# =============================================================================


def _load_catalog_for_cli(catalog_path=None):
    """Load manifest from catalog path or default settings.

    :param catalog_path: Optional path to catalog chartbook.toml.
    :type catalog_path: str or Path, optional
    :returns: Tuple of (manifest, resolved_catalog_path).
    :rtype: tuple
    :raises SystemExit: If no catalog is configured.
    """
    from chartbook.data import _resolve_catalog_path
    from chartbook.errors import CatalogNotConfiguredError
    from chartbook.manifest import load_manifest

    try:
        resolved = _resolve_catalog_path(catalog_path)
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)

    manifest = load_manifest(base_dir=resolved.parent)
    return manifest, resolved


def _get_pipeline_name(pipeline_manifest):
    """Extract pipeline name from manifest.

    :param pipeline_manifest: The pipeline manifest dict.
    :type pipeline_manifest: dict
    :returns: The pipeline name or 'Unknown'.
    :rtype: str
    """
    if "pipeline" in pipeline_manifest:
        return pipeline_manifest["pipeline"].get("pipeline_name", "Unknown")
    return "Unknown"


@main.group(invoke_without_command=True)
@click.option("--catalog", type=click.Path(), help="Path to catalog chartbook.toml")
@click.pass_context
def ls(ctx, catalog):
    """List catalog objects (pipelines, dataframes, charts).

    Without a subcommand, lists all objects in a tree format.
    Use subcommands to list specific object types.

    Examples:
        chartbook ls
        chartbook ls pipelines
        chartbook ls dataframes
        chartbook ls charts
    """
    ctx.ensure_object(dict)
    ctx.obj["catalog"] = catalog

    if ctx.invoked_subcommand is None:
        # List everything in tree format
        manifest, catalog_path = _load_catalog_for_cli(catalog)
        click.echo(f"Catalog: {catalog_path}")
        click.echo("")

        if manifest["config"]["type"] == "catalog":
            # Catalog with multiple pipelines
            for pipeline_id in sorted(manifest["pipelines"].keys()):
                pipeline_manifest = manifest["pipelines"][pipeline_id]
                pipeline_name = _get_pipeline_name(pipeline_manifest)
                click.echo(f"[pipeline] {pipeline_id}: {pipeline_name}")

                # List dataframes under this pipeline
                if "dataframes" in pipeline_manifest:
                    for df_id in sorted(pipeline_manifest["dataframes"].keys()):
                        df_name = pipeline_manifest["dataframes"][df_id].get(
                            "dataframe_name", "Unknown"
                        )
                        click.echo(f"  [dataframe] {pipeline_id}/{df_id}: {df_name}")

                # List charts under this pipeline
                if "charts" in pipeline_manifest:
                    for chart_id in sorted(pipeline_manifest["charts"].keys()):
                        chart_name = pipeline_manifest["charts"][chart_id].get(
                            "chart_name", "Unknown"
                        )
                        click.echo(f"  [chart] {pipeline_id}/{chart_id}: {chart_name}")
        else:
            # Single pipeline
            pipeline_id = manifest["pipeline"]["id"]
            pipeline_name = _get_pipeline_name(manifest)
            click.echo(f"[pipeline] {pipeline_id}: {pipeline_name}")

            if "dataframes" in manifest:
                for df_id in sorted(manifest["dataframes"].keys()):
                    df_name = manifest["dataframes"][df_id].get(
                        "dataframe_name", "Unknown"
                    )
                    click.echo(f"  [dataframe] {pipeline_id}/{df_id}: {df_name}")

            if "charts" in manifest:
                for chart_id in sorted(manifest["charts"].keys()):
                    chart_name = manifest["charts"][chart_id].get(
                        "chart_name", "Unknown"
                    )
                    click.echo(f"  [chart] {pipeline_id}/{chart_id}: {chart_name}")


@ls.command("pipelines")
@click.pass_context
def ls_pipelines(ctx):
    """List all pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["config"]["type"] == "catalog":
        for pipeline_id in sorted(manifest["pipelines"].keys()):
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            pipeline_name = _get_pipeline_name(pipeline_manifest)
            click.echo(f"{pipeline_id}: {pipeline_name}")
    else:
        pipeline_id = manifest["pipeline"]["id"]
        pipeline_name = _get_pipeline_name(manifest)
        click.echo(f"{pipeline_id}: {pipeline_name}")


@ls.command("dataframes")
@click.pass_context
def ls_dataframes(ctx):
    """List all dataframes across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["config"]["type"] == "catalog":
        for pipeline_id in sorted(manifest["pipelines"].keys()):
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "dataframes" in pipeline_manifest:
                for df_id in sorted(pipeline_manifest["dataframes"].keys()):
                    df_name = pipeline_manifest["dataframes"][df_id].get(
                        "dataframe_name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}/{df_id}: {df_name}")
    else:
        pipeline_id = manifest["pipeline"]["id"]
        if "dataframes" in manifest:
            for df_id in sorted(manifest["dataframes"].keys()):
                df_name = manifest["dataframes"][df_id].get("dataframe_name", "Unknown")
                click.echo(f"{pipeline_id}/{df_id}: {df_name}")


@ls.command("charts")
@click.pass_context
def ls_charts(ctx):
    """List all charts across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["config"]["type"] == "catalog":
        for pipeline_id in sorted(manifest["pipelines"].keys()):
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "charts" in pipeline_manifest:
                for chart_id in sorted(pipeline_manifest["charts"].keys()):
                    chart_name = pipeline_manifest["charts"][chart_id].get(
                        "chart_name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}/{chart_id}: {chart_name}")
    else:
        pipeline_id = manifest["pipeline"]["id"]
        if "charts" in manifest:
            for chart_id in sorted(manifest["charts"].keys()):
                chart_name = manifest["charts"][chart_id].get("chart_name", "Unknown")
                click.echo(f"{pipeline_id}/{chart_id}: {chart_name}")


# =============================================================================
# catalog command group - Manage the catalog
# =============================================================================


def _sanitize_pipeline_key(dirname):
    """Convert a directory name to a valid TOML key for the pipelines table.

    :param dirname: The directory name to sanitize.
    :type dirname: str
    :returns: A sanitized key suitable for use in TOML.
    :rtype: str
    """
    import re

    key = dirname.lower().replace("-", "_").replace(" ", "_")
    key = re.sub(r"[^a-z0-9_]", "_", key)
    key = re.sub(r"_+", "_", key)
    key = key.strip("_")
    return key


def _ensure_unique_key(key, existing_keys):
    """Append a numeric suffix if key already exists in the set.

    :param key: The candidate key.
    :type key: str
    :param existing_keys: Set of keys already in use.
    :type existing_keys: set
    :returns: A unique key.
    :rtype: str
    """
    if key not in existing_keys:
        return key
    i = 2
    while f"{key}_{i}" in existing_keys:
        i += 1
    return f"{key}_{i}"


def _load_raw_catalog(catalog_toml_path):
    """Load a catalog TOML file without full manifest processing.

    :param catalog_toml_path: Path to the catalog's chartbook.toml.
    :type catalog_toml_path: Path
    :returns: The raw catalog dictionary.
    :rtype: dict
    :raises click.UsageError: If the file is not a catalog-type manifest.
    """
    import tomli

    with open(catalog_toml_path, "rb") as f:
        data = tomli.load(f)
    config_type = data.get("config", {}).get("type")
    if config_type != "catalog":
        raise click.UsageError(
            f"{catalog_toml_path} is not a catalog (type={config_type!r})"
        )
    data.setdefault("pipelines", {})
    return data


def _get_existing_absolute_paths(raw_catalog, catalog_dir):
    """Resolve all existing pipeline paths in the catalog to absolute paths.

    :param raw_catalog: The raw catalog dictionary.
    :type raw_catalog: dict
    :param catalog_dir: The directory containing the catalog TOML.
    :type catalog_dir: Path
    :returns: A dict mapping absolute paths to their catalog keys.
    :rtype: dict
    """
    from chartbook.manifest import resolve_platform_path

    result = {}
    for key, entry in raw_catalog.get("pipelines", {}).items():
        path_to_pipeline = entry.get("path_to_pipeline")
        if path_to_pipeline is None:
            continue
        try:
            resolved = resolve_platform_path(path_to_pipeline)
        except (ValueError, TypeError):
            continue
        abs_path = (catalog_dir / resolved).resolve()
        result[abs_path] = key
    return result


def _resolve_catalog_toml_path(catalog_path):
    """Resolve the catalog TOML path from an option or global settings.

    :param catalog_path: Optional explicit path to catalog chartbook.toml.
    :type catalog_path: str or Path, optional
    :returns: The resolved path to the catalog's chartbook.toml.
    :rtype: Path
    :raises SystemExit: If no catalog is configured.
    """
    from chartbook.data import _resolve_catalog_path
    from chartbook.errors import CatalogNotConfiguredError

    try:
        return _resolve_catalog_path(catalog_path)
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)


@main.group()
def catalog():
    """Manage the chartbook catalog."""
    pass


@catalog.command("add")
@click.argument("paths", type=str, nargs=-1, required=True)
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(),
    default=None,
    help="Path to catalog chartbook.toml (uses default from settings if omitted)",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt when adding multiple pipelines",
)
def catalog_add(paths, catalog_path, yes):
    """Add pipeline directory(ies) to the catalog.

    PATHS can be one or more directories containing a chartbook.toml file,
    or glob patterns that expand to such directories.

    Examples::

        chartbook catalog add /path/to/pipeline
        chartbook catalog add /path/to/parent/*
        chartbook catalog add /path/to/parent/* -y
        chartbook catalog add ./proj1 ./proj2 ./proj3
    """
    import glob as glob_mod
    import os

    import tomli
    import tomli_w

    # Resolve catalog
    catalog_toml = _resolve_catalog_toml_path(catalog_path)
    catalog_dir = catalog_toml.parent
    raw_catalog = _load_raw_catalog(catalog_toml)

    # Get existing absolute paths for duplicate detection
    existing_abs = _get_existing_absolute_paths(raw_catalog, catalog_dir)
    existing_keys = set(raw_catalog.get("pipelines", {}).keys())

    # Expand all path arguments (handles globs)
    candidate_dirs = []
    for p in paths:
        expanded = glob_mod.glob(p)
        if not expanded:
            # Not a glob, treat as literal path
            expanded = [p]
        for entry in expanded:
            entry_path = Path(entry).resolve()
            if entry_path.is_dir():
                candidate_dirs.append(entry_path)

    if not candidate_dirs:
        click.echo("No matching directories found.", err=True)
        raise SystemExit(1)

    # Validate each candidate
    is_multi = len(candidate_dirs) > 1
    valid_pipelines = []  # list of (abs_path, pipeline_name)

    for d in candidate_dirs:
        toml_path = d / "chartbook.toml"
        if not toml_path.is_file():
            if is_multi:
                click.echo(f"  Skipping {d.name}/ (no chartbook.toml)")
                continue
            else:
                click.echo(f"Error: No chartbook.toml found in {d}", err=True)
                raise SystemExit(1)

        try:
            with open(toml_path, "rb") as f:
                pipeline_toml = tomli.load(f)
        except Exception as e:
            if is_multi:
                click.echo(f"  Skipping {d.name}/ (invalid TOML: {e})")
                continue
            else:
                click.echo(f"Error: Invalid TOML in {toml_path}: {e}", err=True)
                raise SystemExit(1)

        config_type = pipeline_toml.get("config", {}).get("type")
        if config_type != "pipeline":
            if is_multi:
                click.echo(f"  Skipping {d.name}/ (type={config_type!r}, not pipeline)")
                continue
            else:
                click.echo(
                    f"Error: {toml_path} is not a pipeline (type={config_type!r})",
                    err=True,
                )
                raise SystemExit(1)

        # Check for duplicates
        if d in existing_abs:
            click.echo(
                f"  Already in catalog as '{existing_abs[d]}': {d.name}/"
            )
            continue

        pipeline_name = (
            pipeline_toml.get("pipeline", {}).get("pipeline_name", d.name)
        )
        valid_pipelines.append((d, pipeline_name))

    if not valid_pipelines:
        click.echo("No new pipelines to add.")
        return

    # Prompt for confirmation if multiple
    if len(valid_pipelines) > 1 and not yes:
        click.echo("")
        click.echo("Pipelines to add:")
        for d, name in valid_pipelines:
            key = _sanitize_pipeline_key(d.name)
            key = _ensure_unique_key(key, existing_keys)
            click.echo(f"  {key}: {name} ({d})")
        click.echo("")
        if not click.confirm(f"Add {len(valid_pipelines)} pipeline(s)?"):
            raise SystemExit(0)

    # Add each pipeline
    added = 0
    for d, name in valid_pipelines:
        key = _sanitize_pipeline_key(d.name)
        key = _ensure_unique_key(key, existing_keys)
        existing_keys.add(key)

        try:
            rel_path = os.path.relpath(d, catalog_dir)
        except ValueError:
            # Cross-drive on Windows
            rel_path = str(d)

        raw_catalog["pipelines"][key] = {"path_to_pipeline": rel_path}
        click.echo(f"  Added '{key}': {name} ({rel_path})")
        added += 1

    # Write back
    with open(catalog_toml, "wb") as f:
        tomli_w.dump(raw_catalog, f)

    click.echo("")
    click.echo(f"Added {added} pipeline(s) to {catalog_toml}")


# =============================================================================
# data command group - Data operations
# =============================================================================


@main.group()
def data():
    """Data operations (get paths, docs)."""
    pass


@data.command("get-path")
@click.option("--pipeline", required=True, help="Pipeline ID")
@click.option("--dataframe", required=True, help="Dataframe ID")
@click.option("--catalog", type=click.Path(), help="Path to catalog chartbook.toml")
def data_get_path(pipeline, dataframe, catalog):
    """Get the path to a dataframe's parquet file.

    Examples:
        chartbook data get-path --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.data import get_data_path
    from chartbook.errors import CatalogNotConfiguredError

    try:
        path = get_data_path(pipeline, dataframe, catalog_path=catalog)
        click.echo(str(path))
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@data.command("get-docs")
@click.option("--pipeline", required=True, help="Pipeline ID")
@click.option("--dataframe", required=True, help="Dataframe ID")
@click.option("--catalog", type=click.Path(), help="Path to catalog chartbook.toml")
def data_get_docs(pipeline, dataframe, catalog):
    """Print documentation content for a dataframe.

    Examples:
        chartbook data get-docs --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.data import get_docs
    from chartbook.errors import CatalogNotConfiguredError

    try:
        docs = get_docs(pipeline, dataframe, catalog_path=catalog)
        click.echo(docs)
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except FileNotFoundError as e:
        click.echo(f"Error: Documentation file not found: {e}", err=True)
        raise SystemExit(1)


@data.command("get-docs-path")
@click.option("--pipeline", required=True, help="Pipeline ID")
@click.option("--dataframe", required=True, help="Dataframe ID")
@click.option("--catalog", type=click.Path(), help="Path to catalog chartbook.toml")
def data_get_docs_path(pipeline, dataframe, catalog):
    """Get the path to a dataframe's documentation source.

    Examples:
        chartbook data get-docs-path --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.data import get_docs_path
    from chartbook.errors import CatalogNotConfiguredError

    try:
        path = get_docs_path(pipeline, dataframe, catalog_path=catalog)
        click.echo(str(path))
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@main.command()
def init():
    """Initialize a new chartbook project from the cookiecutter template."""
    try:
        import cruft  # noqa: F401
    except ImportError:
        click.echo("Error: cruft is not installed.", err=True)
        click.echo("", err=True)
        click.echo("Install it with:", err=True)
        click.echo('    pip install "chartbook[all]"', err=True)
        raise SystemExit(1)

    import subprocess

    subprocess.run(
        ["cruft", "create", "https://github.com/backofficedev/cookiecutter_chartbook"],
        check=True,
    )


@main.command()
def config():
    """Configure the default catalog path for data loading.

    Sets the path to a catalog's ``chartbook.toml`` in
    ``~/.chartbook/settings.toml`` so that ``data.load()`` can find
    pipelines without an explicit ``catalog_path`` argument.
    """
    from chartbook.config import (
        get_default_catalog_path,
        set_default_catalog_path,
    )

    current = get_default_catalog_path()
    if current is not None:
        click.echo(f"Current catalog path: {current}")
        click.echo("")

    raw_path = click.prompt(
        "Path to catalog chartbook.toml (or its parent directory)",
        type=str,
    )
    catalog_path = Path(raw_path).expanduser()

    try:
        set_default_catalog_path(catalog_path)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)

    resolved = get_default_catalog_path()
    click.echo(f"Catalog path set to: {resolved}")
    click.echo("")
    click.echo("You can now load data with:")
    click.echo('  from chartbook import data')
    click.echo('  df = data.load(pipeline="my_pipeline", dataframe="my_df")')


if __name__ == "__main__":
    main()
