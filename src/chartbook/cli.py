from __future__ import annotations

import warnings
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
        click.echo(
            "These ship with chartbook, so this usually means a broken or"
            " partial installation. Reinstall with:", err=True
        )
        click.echo("    pip install --force-reinstall chartbook", err=True)
        raise SystemExit(1)


@click.group()
@click.version_option(version=__version__)
def main():
    """chartbook CLI tool for generating documentation websites."""
    # A warning from the settings or a manifest is one line for a person,
    # not Python's file, line and source line
    warnings.showwarning = _show_warning


def _show_warning(message, category, filename, lineno, file=None, line=None):
    click.echo(f"Warning: {message}", err=True)


def _default_catalog_path():
    """The default catalog from the settings, or a clean error if the settings are faulty."""
    from chartbook.config import get_default_catalog_path

    try:
        return get_default_catalog_path()
    except ValueError as error:
        raise click.ClickException(str(error)) from None


def _site_options(command):
    """Give a command the arguments of rendering the site.

    `docs` renders it, and `build` renders it after running the build
    script, so both take the same ones.
    """
    options = [
        click.argument("output_dir", type=click.Path(), default="./docs", required=False),
        click.option("--project-dir", type=click.Path(), help="Path to project directory"),
        click.option(
            "--publish-dir",
            type=click.Path(),
            default="./_output/to_be_published/",
            help="Directory where files will be published",
        ),
        click.option(
            "--docs-build-dir",
            type=click.Path(),
            default="./_docs",
            help="Directory where documentation will be built",
        ),
        click.option(
            "--temp-docs-src-dir",
            type=click.Path(),
            default="./_docs_src",
            help="Directory where documentation source files are temporarily stored in two stage procedure",
        ),
        click.option(
            "--keep-build-dirs",
            is_flag=True,
            default=False,
            help="Keep temporary build directory after generation",
        ),
        click.option(
            "--force-write",
            "-f",
            is_flag=True,
            default=False,
            help="Overwrite existing output directory by deleting it first",
        ),
        click.option(
            "--size-threshold",
            type=float,
            default=50,
            help="File size threshold in MB above which to use memory-efficient loading (default: 50)",
        ),
        click.option(
            "--strict/--no-strict",
            default=True,
            help="Fail on missing source files (default). Use --no-strict to skip affected pipelines instead.",
        ),
        click.option(
            "--strip-mathjax2/--no-strip-mathjax2",
            default=True,
            help="Strip Plotly's MathJax 2 scripts from notebook outputs to prevent conflicts with Sphinx's MathJax 3 (default: enabled)",
        ),
        click.option(
            "--incremental",
            is_flag=True,
            default=False,
            help="Keep the build directory between builds and redo only what changed since the last incremental build",
        ),
        click.option(
            "--watch",
            is_flag=True,
            default=False,
            help="Render incrementally, then again whenever the project's files change, until Ctrl-C",
        ),
        click.option(
            "--watch-interval",
            type=click.FloatRange(min=0.1),
            default=None,
            metavar="SECONDS",
            help="How often --watch checks for changes (default: 1)",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


@main.command()
@_site_options
def docs(**site):
    """Render the documentation site, in OUTPUT_DIR (./docs by default).

    This renders the site and writes index.json beside it. It does not
    build the project's data: `chartbook run` does that, and
    `chartbook build` does both.

    By default every render starts from nothing. With --incremental the
    intermediate build directory (--docs-build-dir) is kept, pipelines whose
    files have not changed are not regenerated, and only pages that differ
    are rendered again. --watch does that in a loop: render, then again each
    time a file changes. Open the site with `chartbook browse` and refresh.

    \b
    Examples:
        chartbook docs -f
        chartbook docs -f --incremental
        chartbook docs -f --watch
    """
    _render_site(**site)


@main.command()
@_site_options
def build(**site):
    """Make everything current: run the build script, then render the site.

    The same as `chartbook run` followed by `chartbook docs`, and it takes
    the arguments of `chartbook docs`. In a catalog, the build script is run
    in each of the catalog's pipelines before the catalog's site is rendered.

    With no `build` script in [scripts], there is nothing to run, and only
    the site is rendered.

    Inside a build script, say `chartbook docs`. `chartbook build` there
    would run the script that called it; it renders the site and says so.

    \b
    Examples:
        chartbook build -f
        chartbook build -f --project-dir ../rate_forecast
    """
    from chartbook import run as runner
    from chartbook.manifest import BUILD_SCRIPT

    project_dir = resolve_project_dir(site["project_dir"])
    if runner.running(project_dir, BUILD_SCRIPT):
        click.echo(
            click.style("Warning: ", fg="yellow", bold=True)
            + "`chartbook build` was called from this pipeline's own build script. "
            "It runs that script and then renders the site, so here it only "
            "renders the site. In a build script, say `chartbook docs`.",
            err=True,
        )
    elif _has_script(project_dir, BUILD_SCRIPT):
        _run_script(project_dir, BUILD_SCRIPT)
    else:
        click.echo("No `build` script here, so only the site is rendered.")
    _render_site(**site)


def _render_site(
    output_dir,
    project_dir,
    publish_dir,
    docs_build_dir,
    temp_docs_src_dir,
    keep_build_dirs,
    force_write,
    size_threshold,
    strict,
    strip_mathjax2,
    incremental,
    watch,
    watch_interval,
):
    """Render the documentation site: what `docs` does, and `build` does last.

    :param output_dir: Directory where output will be generated.
    :param project_dir: Root directory of the project.
    :param publish_dir: Directory where files will be published.
    :param docs_build_dir: Directory where documentation will be built.
    :param temp_docs_src_dir: Temporary directory for documentation source files.
    :param keep_build_dirs: If True, keeps temporary build directory after generation.
    :param force_write: If True, overwrites existing output directory.
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :param strict: If True, error and exit on missing source files.
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs.
    :param incremental: If True, keep the build directory and redo only what changed.
    :param watch: If True, render incrementally and again on every change.
    :param watch_interval: Seconds between checks for changes in watch mode.
    """
    # Validate paths for shell/platform mismatches
    from chartbook.path_validation import detect_shell_environment, validate_cli_paths

    shell_env = detect_shell_environment()
    path_args = [p for p in [output_dir, project_dir, publish_dir, docs_build_dir, temp_docs_src_dir] if p is not None]
    if path_args:
        validate_cli_paths(path_args, shell_env, auto_confirm=True)

    # Check for Sphinx dependencies
    _check_sphinx_installed()

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

    _run_docs_build(
        project_dir,
        incremental=incremental,
        watch=watch,
        watch_interval=watch_interval,
        output_dir=output_dir,
        project_dir=project_dir,
        publish_dir=publish_dir,
        _docs_dir=docs_build_dir,
        temp_docs_src_dir=temp_docs_src_dir,
        keep_build_dirs=keep_build_dirs,
        should_remove_existing=should_remove_existing,
        size_threshold=size_threshold,
        strict=strict,
        strip_mathjax2=strip_mathjax2,
    )
    if not watch:
        click.echo(f"Successfully generated documentation in {output_dir}")


def _run_docs_build(manifest_dir, incremental, watch, watch_interval, **build_kwargs):
    """Run a documentation build once, or keep rebuilding it on change.

    :param manifest_dir: The directory holding the project's chartbook.toml.
    :param incremental: Keep the build directory and redo only what changed.
    :param watch: Build incrementally, then rebuild whenever inputs change.
    :param watch_interval: Seconds between checks in watch mode, or None.
    :param build_kwargs: Passed to ``generate_docs``.
    """
    from chartbook.build_docs import generate_docs

    if watch_interval is not None and not watch:
        raise click.UsageError("--watch-interval only applies with --watch.")

    def report(error):
        click.echo(click.style("Error: ", fg="red", bold=True) + str(error), err=True)

    if not watch:
        try:
            summary = generate_docs(incremental=incremental, **build_kwargs)
        except (ValueError, FileNotFoundError) as e:
            report(e)
            raise SystemExit(1)
        if summary is not None:
            click.echo(summary.describe())
        return

    from chartbook import incremental as incremental_builds
    from chartbook.manifest import load_manifest

    def build_once():
        try:
            summary = generate_docs(incremental=True, **build_kwargs)
        except (ValueError, FileNotFoundError) as e:
            report(e)
            raise SystemExit(1)
        click.echo(summary.describe())

    def snapshot():
        manifest = load_manifest(base_dir=manifest_dir)
        return incremental_builds.snapshot_inputs(manifest, manifest_dir)

    incremental_builds.watch(
        build_once, snapshot, interval=watch_interval or 1.0, echo=click.echo
    )


@main.command()
@click.argument("output_dir", type=click.Path(), default="./docs", required=False)
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
def browse(output_dir, project_dir):
    """Open the project documentation in your default browser.

    Looks for index.html in the OUTPUT_DIR (default: ./docs) and opens it
    using the system's default web browser. Works on macOS, Windows, and Linux.

    Examples:
        chartbook browse
        chartbook browse ./my-docs
        chartbook browse --project-dir /path/to/project
    """
    # Validate paths for shell/platform mismatches
    from chartbook.path_validation import detect_shell_environment, validate_cli_paths

    shell_env = detect_shell_environment()
    path_args = [p for p in [output_dir, project_dir] if p is not None]
    if path_args:
        validate_cli_paths(path_args, shell_env, auto_confirm=True)

    project_dir = resolve_project_dir(project_dir)
    index_path = (project_dir / Path(output_dir) / "index.html").resolve()

    if not index_path.is_file():
        click.echo("Error: Documentation not found.", err=True)
        click.echo(f"  Expected: {index_path}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook docs' first.", err=True)
        raise SystemExit(1)

    import webbrowser

    url = index_path.as_uri()
    click.echo(f"Opening {index_path}")
    if not webbrowser.open(url):
        click.echo(f"Could not open browser. Open this URL manually: {url}")


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
    """Stage a pipeline's publishable files into a directory.

    If no publish directory is provided, a default local directory will be used.

    Publishing copies files and does nothing else: no network, no registry.
    Sending a pipeline to a registry is a different act with a different
    verb, `chartbook push`, which is reserved and not yet implemented.

    :param publish_dir: Directory where files will be published.
    :type publish_dir: Path or str, optional
    :param project_dir: Root directory of the project.
    :type project_dir: Path or str
    :param verbose: If True, enables verbose output.
    :type verbose: bool
    """
    # Validate paths for shell/platform mismatches
    from chartbook.path_validation import detect_shell_environment, validate_cli_paths

    shell_env = detect_shell_environment()
    path_args = [p for p in [publish_dir, project_dir] if p is not None]
    if path_args:
        validate_cli_paths(path_args, shell_env, auto_confirm=True)

    # Check for Sphinx dependencies
    _check_sphinx_installed()

    # Import here to avoid loading Sphinx deps at module level
    from chartbook.manifest import load_manifest
    from chartbook.publish import publish_pipeline

    project_dir = resolve_project_dir(project_dir)
    manifest = load_manifest(base_dir=project_dir)
    pipeline_id = manifest["project"]["id"]

    if publish_dir is None:
        BASE_DIR = Path(".").resolve()
        publish_dir = BASE_DIR / Path("./_output/to_be_published")
    else:
        publish_dir = Path(publish_dir) / pipeline_id

    # if publish_dir is a relative path, convert it to an absolute path relative to the project directory
    if not publish_dir.is_absolute():
        publish_dir = project_dir / Path(publish_dir)
    publish_pipeline(publish_dir=publish_dir, base_dir=project_dir, verbose=verbose)


@main.command(hidden=True)
def push():
    """Reserved: send a pipeline to a registry. Not yet supported.

    `publish` already means "stage files into a directory", so the registry
    gets its own verb rather than a second meaning for that one. The name is
    claimed here so that nothing else takes it first.
    """
    click.echo(
        click.style("Error: ", fg="red", bold=True)
        + "'chartbook push' is reserved for sending a pipeline to a registry, "
        "which is not yet supported. To stage a pipeline's files into a "
        "directory, use 'chartbook publish'.",
        err=True,
    )
    raise SystemExit(1)


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
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
@click.option(
    "--within",
    "within_days",
    type=click.IntRange(min=0),
    default=30,
    show_default=True,
    metavar="DAYS",
    help="Fail on licenses that expire within this many days",
)
@click.option(
    "--policy",
    "policy_path",
    type=click.Path(),
    default=None,
    help="Check required fields against the [policy] of this catalog "
    "chartbook.toml (or its directory) instead of the project's own",
)
@click.option(
    "--skip-outputs",
    is_flag=True,
    default=False,
    help="Do not require data files, charts and notebooks to exist. For CI "
    "that checks a project without building it",
)
def check(project_dir, within_days, policy_path, skip_outputs):
    """Check a project's metadata and paths; exit nonzero on any problem.

    Meant for CI. Works on a pipeline or a catalog and reports four things,
    each naming the chartbook.toml and field to edit:

    \b
    - fields the policy requires that are missing or empty
    - declared paths that point at files that do not exist
    - pipelines in [dependencies] that cannot be found where they are said
      to be, and training data they do not declare
    - dataframe licenses that are expired, or expire within --within days

    Required fields come from a catalog's [policy.required], or from the
    default recommended lists for a standalone pipeline. Pass --policy to
    check a pipeline against the catalog it is published to.

    Only metadata and paths are checked; no data file is opened.

    Data files, charts and notebooks are things a pipeline builds, and are
    usually not in git. A CI job that has not run the pipeline will find
    them all missing; --skip-outputs leaves them out and checks the rest.

    Examples:
        chartbook check
        chartbook check --within 90
        chartbook check --policy ../catalog
        chartbook check --skip-outputs
    """
    import warnings

    from chartbook.check import display_path, load_policy, run_checks
    from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest, load_manifest

    project_dir = resolve_project_dir(project_dir)
    manifest_path = project_dir / "chartbook.toml"
    try:
        # Manifest warnings (e.g. unknown [project] keys) belong in the
        # report, not in Python's warning format
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manifest = load_manifest(base_dir=project_dir)
        if policy_path is not None:
            manifest["policy"] = load_policy(policy_path)
            policy_label = f"the policy in {policy_path}"
        elif manifest["project"]["type"] == "catalog":
            policy_label = "the catalog policy"
        else:
            policy_label = "the default policy"
    except (ValueError, FileNotFoundError, TypeError, KeyError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)

    # The checks warn about what they could not look at
    with warnings.catch_warnings(record=True) as unchecked:
        warnings.simplefilter("always")
        problems = run_checks(
            manifest,
            project_dir,
            within_days=within_days,
            policy_label=policy_label,
            skip_outputs=skip_outputs,
        )

    for warning in [*caught, *unchecked]:
        click.echo(f"warning: {warning.message}", err=True)

    for problem in problems:
        click.echo(problem.format(relative_to=Path.cwd()))

    if problems:
        files = len({p.file for p in problems})
        click.echo(
            f"\n{len(problems)} problem(s) found in {files} manifest(s).", err=True
        )
        raise SystemExit(1)

    pipelines = [
        get_pipeline_manifest(manifest, pid) for pid in get_pipeline_ids(manifest)
    ]
    # Models and dependencies are counted only where there are some, so that
    # the line for a project without them reads as it always has
    sections = ["dataframes", "charts", "notebooks"]
    for optional in ("models", "dependencies"):
        if any(p.get(optional) for p in pipelines):
            sections.append(optional)
    counts = ", ".join(
        f"{sum(len(p.get(section, {})) for p in pipelines)} {section}"
        for section in sections
    )
    shown = display_path(manifest_path, relative_to=Path.cwd())
    note = "; built outputs not checked" if skip_outputs else ""
    click.echo(f"{shown}: OK ({len(pipelines)} pipeline(s), {counts}{note})")


@main.command("path")
@click.argument("ref")
@click.option(
    "--kind",
    type=click.Choice(["dataframe", "chart", "notebook", "note", "model"]),
    help="The kind of asset REF names, when REF does not say "
    "(default: dataframe). The same as writing KIND/REF.",
)
@click.option(
    "--project-dir",
    type=click.Path(),
    help="Where to look for the pipeline: its chartbook.toml is found by "
    "walking up from here (default: the current directory)",
)
def path_command(ref, kind, project_dir):
    """Print the path of an asset: this pipeline's, or a pinned copy of another's.

    REF names an asset declared in the enclosing chartbook.toml. A dataframe
    is named by its key alone; anything else has its kind in front:

    \b
        treasury_rates          [dataframes.treasury_rates]
        chart/yield_curve       [charts.yield_curve]
        notebook/analysis       [notebooks.analysis]
        note/methodology        [notes.methodology]
        model/rate_forecaster   [models.rate_forecaster]

    The path is printed absolute, whether or not the file exists yet, so a
    build tool can use it for inputs and outputs alike. This is
    `chartbook.assets.path()` for Make, shell, R and Stata:

    \b
        MERGED := $(shell chartbook path merged_rates)

    An undeclared name fails, naming the table to add.

    An asset of another pipeline has that pipeline in front:

    \b
        fed_yield_curve:treasury_rates
        fed_yield_curve:chart/curve_today

    The pipeline must be in [dependencies], and what is printed is the path
    of the copy that chartbook.lock pins, in the store: not the other
    pipeline's own directory. Run `chartbook pin` first. That copy stays as
    it is until `chartbook update`.

    Examples:
        chartbook path repo_public
        chartbook path chart/repo_rates
        chartbook path repo_rates --kind chart --project-dir ../yield_curve
        chartbook path fed_yield_curve:treasury_rates
    """
    from chartbook.assets import path as resolve_path

    try:
        asset_path = resolve_path(
            ref, kind=kind, project_dir=project_dir or Path.cwd()
        )
    except (LookupError, FileNotFoundError, ValueError, TypeError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)
    # Nothing but the path on stdout: this output gets captured
    click.echo(str(asset_path))


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
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
def create_data_glimpses(no_samples, no_stats, output_dir, size_threshold, project_dir):
    """Create a data glimpses report for the project's declared dataframes.

    This command reads chartbook.toml, takes every dataframe it declares, and
    creates a comprehensive data glimpse report in Markdown format. The list
    comes from the manifest alone, so it works the same whether the project
    is built with doit, Snakemake, Make or plain scripts. Declared dataframes
    whose files do not exist yet are skipped.

    :param no_samples: If True, exclude sample values sections from the report.
    :type no_samples: bool
    :param no_stats: If True, exclude numeric column statistics sections from the report.
    :type no_stats: bool
    :param output_dir: Directory to save the output file.
    :type output_dir: str, optional
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param project_dir: Directory holding the project's chartbook.toml.
    :type project_dir: str, optional

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
            project_dir=resolve_project_dir(project_dir),
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
    except CatalogNotConfiguredError:
        resolved = _prompt_catalog_init()
    except ValueError as error:  # the settings file that names the default catalog is faulty
        raise click.ClickException(str(error)) from None

    try:
        manifest = load_manifest(base_dir=resolved.parent)
    except (ValueError, FileNotFoundError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)
    return manifest, resolved


def _get_pipeline_name(pipeline_manifest):
    """Extract pipeline name from manifest.

    :param pipeline_manifest: The pipeline manifest dict.
    :type pipeline_manifest: dict
    :returns: The pipeline name or 'Unknown'.
    :rtype: str
    """
    return pipeline_manifest.get("project", {}).get("name", "Unknown")


@main.group("index")
def index_group():
    """Read the index.json a build writes beside the site."""


@index_group.command("diff")
@click.argument("before", type=click.Path(exists=True))
@click.argument("after", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, help="Print the diff as JSON, for a script")
@click.option(
    "--exit-code", is_flag=True, help="Exit 1 when the two differ, as `git diff --exit-code` does"
)
def index_diff(before, after, as_json, exit_code):
    """Say what changed between two builds, from their index.json files.

    BEFORE and AFTER are two index.json files, or the folders that hold
    them (the site folder, `docs/`). Records are matched by kind and ID;
    the two are compared as published, so a build directory's index and
    the site's compare as equals, and `generated_at` is ignored.

    \b
    Examples:
        chartbook index diff docs-main/ docs/
        chartbook index diff old.json docs/index.json --exit-code
    """
    import json

    from chartbook import indexdiff

    try:
        found = indexdiff.diff(indexdiff.read_index(before), indexdiff.read_index(after))
    except (OSError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(2)
    if as_json:
        click.echo(json.dumps(found.to_dict(), indent=2, default=str))
    else:
        click.echo(indexdiff.format_diff(found))
    if exit_code and not found.empty:
        raise SystemExit(1)


#: How `chartbook ls` shows a pipeline the catalog names with no folder here
STORE_ONLY = "(store only: not on this machine; the catalog shows its snapshots)"


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

        if manifest["project"]["type"] == "catalog":
            # Catalog with multiple pipelines, and those it shows from the store
            for pipeline_id in sorted([*manifest["pipelines"], *(manifest.get("store_pipelines") or [])]):
                if pipeline_id not in manifest["pipelines"]:
                    click.echo(f"[pipeline] {pipeline_id}: {STORE_ONLY}")
                    continue
                pipeline_manifest = manifest["pipelines"][pipeline_id]
                pipeline_name = _get_pipeline_name(pipeline_manifest)
                click.echo(f"[pipeline] {pipeline_id}: {pipeline_name}")

                # List dataframes under this pipeline
                if "dataframes" in pipeline_manifest:
                    for df_id in sorted(pipeline_manifest["dataframes"].keys()):
                        df_name = pipeline_manifest["dataframes"][df_id].get(
                            "name", "Unknown"
                        )
                        click.echo(f"  [dataframe] {pipeline_id}/{df_id}: {df_name}")

                # List charts under this pipeline
                if "charts" in pipeline_manifest:
                    for chart_id in sorted(pipeline_manifest["charts"].keys()):
                        chart_name = pipeline_manifest["charts"][chart_id].get(
                            "name", "Unknown"
                        )
                        click.echo(f"  [chart] {pipeline_id}/{chart_id}: {chart_name}")
        else:
            # Single pipeline
            pipeline_id = manifest["project"]["id"]
            pipeline_name = _get_pipeline_name(manifest)
            click.echo(f"[pipeline] {pipeline_id}: {pipeline_name}")

            if "dataframes" in manifest:
                for df_id in sorted(manifest["dataframes"].keys()):
                    df_name = manifest["dataframes"][df_id].get("name", "Unknown")
                    click.echo(f"  [dataframe] {pipeline_id}/{df_id}: {df_name}")

            if "charts" in manifest:
                for chart_id in sorted(manifest["charts"].keys()):
                    chart_name = manifest["charts"][chart_id].get("name", "Unknown")
                    click.echo(f"  [chart] {pipeline_id}/{chart_id}: {chart_name}")


@ls.command("pipelines")
@click.pass_context
def ls_pipelines(ctx):
    """List all pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["project"]["type"] == "catalog":
        for pipeline_id in sorted([*manifest["pipelines"], *(manifest.get("store_pipelines") or [])]):
            if pipeline_id not in manifest["pipelines"]:
                click.echo(f"{pipeline_id}: {STORE_ONLY}")
                continue
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            pipeline_name = _get_pipeline_name(pipeline_manifest)
            click.echo(f"{pipeline_id}: {pipeline_name}")
    else:
        pipeline_id = manifest["project"]["id"]
        pipeline_name = _get_pipeline_name(manifest)
        click.echo(f"{pipeline_id}: {pipeline_name}")


@ls.command("dataframes")
@click.pass_context
def ls_dataframes(ctx):
    """List all dataframes across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["project"]["type"] == "catalog":
        for pipeline_id in sorted(manifest["pipelines"].keys()):
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "dataframes" in pipeline_manifest:
                for df_id in sorted(pipeline_manifest["dataframes"].keys()):
                    df_name = pipeline_manifest["dataframes"][df_id].get(
                        "name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}/{df_id}: {df_name}")
    else:
        pipeline_id = manifest["project"]["id"]
        if "dataframes" in manifest:
            for df_id in sorted(manifest["dataframes"].keys()):
                df_name = manifest["dataframes"][df_id].get("name", "Unknown")
                click.echo(f"{pipeline_id}/{df_id}: {df_name}")


@ls.command("charts")
@click.pass_context
def ls_charts(ctx):
    """List all charts across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["project"]["type"] == "catalog":
        for pipeline_id in sorted(manifest["pipelines"].keys()):
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "charts" in pipeline_manifest:
                for chart_id in sorted(pipeline_manifest["charts"].keys()):
                    chart_name = pipeline_manifest["charts"][chart_id].get(
                        "name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}/{chart_id}: {chart_name}")
    else:
        pipeline_id = manifest["project"]["id"]
        if "charts" in manifest:
            for chart_id in sorted(manifest["charts"].keys()):
                chart_name = manifest["charts"][chart_id].get("name", "Unknown")
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

    from chartbook.manifest import detect_v1_format, resolve_project_type

    with open(catalog_toml_path, "rb") as f:
        data = tomli.load(f)
    if detect_v1_format(data):
        raise click.UsageError(
            f"{catalog_toml_path} uses the old v1 format. "
            f"Run: python scripts/migrate_toml_v2.py {catalog_toml_path.parent}"
        )
    config_type = resolve_project_type(data, source=str(catalog_toml_path))
    if config_type != "catalog":
        raise click.UsageError(
            f"{catalog_toml_path} is not a catalog (type={config_type!r})"
        )
    data.setdefault("pipelines", {})
    return data


def _off_the_disabled_list(raw_catalog, key) -> bool:
    """Take a pipeline ID off the catalog's ``[pipelines] disabled`` list, every time it is there.

    :returns: Whether it was on it.
    """
    pipelines = raw_catalog.get("pipelines", {})
    listed = pipelines.get("disabled")
    if not isinstance(listed, list) or key not in listed:
        return False
    pipelines["disabled"] = [other for other in listed if other != key]
    if not pipelines["disabled"]:
        pipelines.pop("disabled")
    return True


def _get_existing_absolute_paths(raw_catalog, catalog_dir):
    """Resolve all existing pipeline paths in the catalog to absolute paths.

    :param raw_catalog: The raw catalog dictionary.
    :type raw_catalog: dict
    :param catalog_dir: The directory containing the catalog TOML.
    :type catalog_dir: Path
    :returns: A dict mapping absolute paths to their catalog keys.
    :rtype: dict
    """
    from chartbook.manifest import RESERVED_PIPELINES_KEYS, resolve_platform_path

    result = {}
    for key, entry in raw_catalog.get("pipelines", {}).items():
        if key in RESERVED_PIPELINES_KEYS:
            continue
        if isinstance(entry, str):
            entry = {"path": entry}
        pipeline_path = entry.get("path")
        if pipeline_path is None:
            continue
        try:
            resolved = resolve_platform_path(pipeline_path)
        except (ValueError, TypeError):
            continue
        abs_path = (catalog_dir / resolved).resolve()
        result[abs_path] = key
    return result


def _get_members_covered_paths(raw_catalog, catalog_dir):
    """Map absolute paths already covered by pipelines.members patterns.

    :returns: Dict of absolute path -> the members pattern that covers it.
    :rtype: dict
    """
    import glob as glob_mod

    covered = {}
    members = raw_catalog.get("pipelines", {}).get("members", [])
    if not isinstance(members, list):
        return covered
    for pattern in members:
        if not isinstance(pattern, str):
            continue
        for match in glob_mod.glob(str(catalog_dir / pattern)):
            covered[Path(match).resolve()] = pattern
    return covered


def _prompt_catalog_init():
    """Prompt the user to create a global catalog if running interactively.

    :returns: The resolved catalog path if created, otherwise raises SystemExit.
    :rtype: Path
    :raises SystemExit: If the user declines or stdin is not a TTY.
    """
    import sys

    from chartbook.config import create_global_catalog, get_global_catalog_path

    if not sys.stdin.isatty():
        click.echo(
            "Run 'chartbook catalog init' to create a new catalog, "
            "or 'chartbook config' to point to an existing one.",
            err=True,
        )
        raise SystemExit(1)

    click.echo("No catalog found.", err=True)
    if click.confirm("Create a new global catalog now?", default=False):
        title = click.prompt("Catalog title", default="My Catalog")
        catalog_path = create_global_catalog(title=title)
        click.echo(f"Created global catalog: {catalog_path}")
        click.echo("")
        return get_global_catalog_path()

    click.echo("", err=True)
    click.echo(
        "Run 'chartbook catalog init' to create a new catalog, "
        "or 'chartbook config' to point to an existing one.",
        err=True,
    )
    raise SystemExit(1)


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
    except CatalogNotConfiguredError:
        return _prompt_catalog_init()


@main.group()
def catalog():
    """Manage the chartbook catalog."""
    pass


@catalog.command("init")
@click.option("--title", default=None, help="Title for the catalog site")
def catalog_init(title):
    """Initialize the global catalog at ~/.chartbook/chartbook.toml.

    Creates a minimal catalog with an empty pipelines section.
    Use ``chartbook catalog add`` to add pipelines afterwards.
    """
    from chartbook.config import create_global_catalog, get_global_catalog_path

    catalog_path = get_global_catalog_path()
    if catalog_path.is_file():
        click.echo(f"Global catalog already exists: {catalog_path}")
        return

    if title is None:
        title = click.prompt("Catalog title", default="My Catalog")

    catalog_path = create_global_catalog(title=title)
    click.echo(f"Created global catalog: {catalog_path}")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  chartbook catalog add /path/to/pipeline   # add a pipeline")
    click.echo("  chartbook catalog build                   # build HTML docs")
    click.echo("  chartbook catalog browse                  # open in browser")


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

    from chartbook.path_validation import detect_shell_environment, validate_cli_paths

    # Validate paths for shell/platform mismatches before processing
    shell_env = detect_shell_environment()
    paths = validate_cli_paths(paths, shell_env, auto_confirm=yes)

    # Resolve catalog
    catalog_toml = _resolve_catalog_toml_path(catalog_path)
    catalog_dir = catalog_toml.parent
    raw_catalog = _load_raw_catalog(catalog_toml)

    # Get existing absolute paths for duplicate detection
    existing_abs = _get_existing_absolute_paths(raw_catalog, catalog_dir)
    members_covered = _get_members_covered_paths(raw_catalog, catalog_dir)
    existing_keys = set(raw_catalog.get("pipelines", {}).keys())
    reenabled = 0

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
        tried = ", ".join(paths)
        click.echo(
            f"No matching directories found for: {tried}\n"
            f"Check that the path(s) exist and are spelled correctly.",
            err=True,
        )
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

        from chartbook.manifest import detect_v1_format, resolve_project_type

        if detect_v1_format(pipeline_toml):
            if is_multi:
                click.echo(f"  Skipping {d.name}/ (old v1-format chartbook.toml)")
                continue
            else:
                click.echo(
                    f"Error: {toml_path} uses the old v1 format. "
                    f"Run: python scripts/migrate_toml_v2.py {d}",
                    err=True,
                )
                raise SystemExit(1)

        try:
            config_type = resolve_project_type(pipeline_toml, source=str(toml_path))
        except ValueError as e:
            if is_multi:
                click.echo(f"  Skipping {d.name}/ ({e})")
                continue
            else:
                click.echo(f"Error: {e}", err=True)
                raise SystemExit(1)
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

        # Paths already matched by a members pattern need no explicit entry
        if d in members_covered:
            click.echo(
                f"  Already covered by pipelines.members pattern "
                f"'{members_covered[d]}': {d.name}/"
            )
            continue

        # Check for duplicates — re-enable if disabled
        if d in existing_abs:
            key = existing_abs[d]
            entry = raw_catalog["pipelines"][key]
            flagged = isinstance(entry, dict) and entry.pop("disabled", False)
            listed = _off_the_disabled_list(raw_catalog, key)
            if flagged or listed:
                reenabled += 1
                click.echo(f"  Re-enabled '{key}': {d.name}/")
            else:
                click.echo(
                    f"  Already in catalog as '{key}': {d.name}/"
                )
            continue

        pipeline_name = pipeline_toml.get("project", {}).get("name", d.name)
        valid_pipelines.append((d, pipeline_name, pipeline_toml.get("project", {})))

    if not valid_pipelines and not reenabled:
        click.echo("No new pipelines to add.")
        return

    if not valid_pipelines and reenabled:
        # Only re-enables, no new additions — still need to write
        with open(catalog_toml, "wb") as f:
            tomli_w.dump(raw_catalog, f)
        click.echo("")
        click.echo(f"Re-enabled {reenabled} pipeline(s) in {catalog_toml}")
        return

    from chartbook.identity import derive_pipeline_id

    def _derive_catalog_key(directory, project_table):
        # Scoped id: explicit project.id, else scope from the git remote /
        # repo_url with the directory name, else the bare directory name
        try:
            return derive_pipeline_id(project_table, directory)
        except ValueError:
            return _sanitize_pipeline_key(directory.name)

    from chartbook.manifest import RESERVED_PIPELINES_KEYS

    # An entry with no path is a pipeline the catalog shows from the store:
    # a folder of the same ID is that pipeline, and fills the entry in
    from_the_store = {
        key
        for key, entry in raw_catalog.get("pipelines", {}).items()
        if key not in RESERVED_PIPELINES_KEYS and isinstance(entry, dict) and entry.get("path") is None
    }
    planned = []  # (directory, name, key, whether it fills in an entry from the store)
    for d, name, project_table in valid_pipelines:
        key = _derive_catalog_key(d, project_table)
        fills = key in from_the_store
        if fills:
            from_the_store.discard(key)
        else:
            key = _ensure_unique_key(key, existing_keys)
        existing_keys.add(key)
        planned.append((d, name, key, fills))

    # Prompt for confirmation if multiple
    if len(planned) > 1 and not yes:
        click.echo("")
        click.echo("Pipelines to add:")
        for d, name, key, fills in planned:
            shown = " (shown from the store until now)" if fills else ""
            click.echo(f"  {key}: {name} ({d}){shown}")
        click.echo("")
        if not click.confirm(f"Add {len(planned)} pipeline(s)?"):
            raise SystemExit(0)

    # Add each pipeline
    added = 0
    for d, name, key, fills in planned:
        try:
            rel_path = os.path.relpath(d, catalog_dir)
        except ValueError:
            # Cross-drive on Windows
            rel_path = str(d)

        # What is added is enabled, whatever the disabled list said of its ID
        listed = _off_the_disabled_list(raw_catalog, key)
        enabled = " (it was on the disabled list)" if listed else ""
        if fills:
            entry = raw_catalog["pipelines"][key]
            entry["path"] = rel_path
            entry.pop("disabled", None)
            click.echo(f"  Added '{key}', which the catalog showed from the store: {name} ({rel_path}){enabled}")
        else:
            raw_catalog["pipelines"][key] = {"path": rel_path}
            click.echo(f"  Added '{key}': {name} ({rel_path}){enabled}")
        added += 1

    # Write back
    with open(catalog_toml, "wb") as f:
        tomli_w.dump(raw_catalog, f)

    click.echo("")
    parts = [f"Added {added} pipeline(s)"]
    if reenabled:
        parts.append(f"re-enabled {reenabled}")
    click.echo(f"{', '.join(parts)} in {catalog_toml}")


def _set_pipeline_disabled(pipeline_id, catalog_path, disabled):
    """Set or clear the disabled flag on a pipeline in the catalog.

    :param pipeline_id: The pipeline key in the catalog.
    :type pipeline_id: str
    :param catalog_path: Optional explicit path to catalog chartbook.toml.
    :type catalog_path: str or Path, optional
    :param disabled: Whether to disable (True) or enable (False) the pipeline.
    :type disabled: bool
    """
    import tomli_w

    from chartbook.manifest import RESERVED_PIPELINES_KEYS

    catalog_toml = _resolve_catalog_toml_path(catalog_path)
    raw_catalog = _load_raw_catalog(catalog_toml)

    pipelines = raw_catalog.get("pipelines", {})
    has_members = isinstance(pipelines.get("members"), list)

    if pipeline_id in pipelines and pipeline_id not in RESERVED_PIPELINES_KEYS:
        # Explicit entry: toggle its disabled flag (string shorthand becomes
        # a table when the flag is set)
        entry = pipelines[pipeline_id]
        if isinstance(entry, str):
            entry = {"path": entry}
            pipelines[pipeline_id] = entry
        if disabled:
            entry["disabled"] = True
        else:
            entry.pop("disabled", None)
    elif has_members:
        # Member-discovered pipelines are toggled via the pipelines.disabled
        # ID list
        disabled_list = pipelines.setdefault("disabled", [])
        if disabled and pipeline_id not in disabled_list:
            disabled_list.append(pipeline_id)
        elif not disabled and pipeline_id in disabled_list:
            disabled_list.remove(pipeline_id)
        if not disabled_list:
            pipelines.pop("disabled", None)
    else:
        click.echo(f"Error: Pipeline '{pipeline_id}' not found in catalog.", err=True)
        click.echo("", err=True)
        available = ", ".join(
            sorted(k for k in pipelines if k not in RESERVED_PIPELINES_KEYS)
        ) or "(none)"
        click.echo(f"Available pipelines: {available}", err=True)
        raise SystemExit(1)

    with open(catalog_toml, "wb") as f:
        tomli_w.dump(raw_catalog, f)

    state = "disabled" if disabled else "enabled"
    click.echo(f"Pipeline '{pipeline_id}' {state} in {catalog_toml}")


@catalog.command("disable")
@click.argument("pipeline_id")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(),
    default=None,
    help="Path to catalog chartbook.toml (uses default from settings if omitted)",
)
def catalog_disable(pipeline_id, catalog_path):
    """Disable a pipeline in the catalog.

    The pipeline entry is kept but skipped during builds.
    Re-enable with ``chartbook catalog enable``.
    """
    _set_pipeline_disabled(pipeline_id, catalog_path, disabled=True)


@catalog.command("enable")
@click.argument("pipeline_id")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(),
    default=None,
    help="Path to catalog chartbook.toml (uses default from settings if omitted)",
)
def catalog_enable(pipeline_id, catalog_path):
    """Re-enable a previously disabled pipeline in the catalog."""
    _set_pipeline_disabled(pipeline_id, catalog_path, disabled=False)


@catalog.command("build")
@click.option(
    "-f",
    "--force-write",
    is_flag=True,
    default=False,
    help="Overwrite existing docs without prompting",
)
@click.option(
    "--strict/--no-strict",
    default=False,
    help="Skip pipelines with missing source files (default). Use --strict to fail on any missing file.",
)
@click.option(
    "--clean",
    is_flag=True,
    default=False,
    help="Throw away what was kept from earlier builds and rebuild everything",
)
@click.option(
    "--watch",
    is_flag=True,
    default=False,
    help="After building, rebuild whenever a pipeline's files change, until Ctrl-C",
)
@click.option(
    "--watch-interval",
    type=click.FloatRange(min=0.1),
    default=None,
    metavar="SECONDS",
    help="How often --watch checks for changes (default: 1)",
)
def catalog_build(force_write, strict, clean, watch, watch_interval):
    """Build HTML documentation for the global catalog.

    Uses the catalog path from ``~/.chartbook/settings.toml`` if configured,
    otherwise falls back to ``~/.chartbook/chartbook.toml``.

    The build is incremental. Its working files are kept next to the catalog
    (in ``_docs/``), and the next build redoes only the pipelines whose files
    changed since: for most of a large catalog, most of the time, nothing.
    Nothing runs in between; it is a record on disk that the next build
    reads. --clean discards it and rebuilds everything. --watch keeps
    rebuilding as files change.
    """
    _check_sphinx_installed()


    catalog_path = _default_catalog_path()
    if catalog_path is None or not catalog_path.is_file():
        click.echo("Error: No global catalog found.", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook catalog init' to create one.", err=True)
        raise SystemExit(1)

    project_dir = catalog_path.parent
    config_dir = catalog_path.parent
    output_dir = config_dir / "docs"
    _docs_dir = config_dir / "_docs"
    temp_docs_src_dir = config_dir / "_docs_src"

    click.echo(f"Building catalog from: {catalog_path}")
    click.echo(f"Output directory: {output_dir}")

    if clean:
        from chartbook.incremental import looks_like_build_tree

        if looks_like_build_tree(_docs_dir):
            import shutil

            shutil.rmtree(_docs_dir)

    # A site built with MkDocs is built whole: the kept build directory is Sphinx's
    from chartbook.manifest import load_manifest

    try:
        incremental = load_manifest(project_dir)["project"].get("writer", "sphinx") != "mkdocs"
    except (ValueError, FileNotFoundError, TypeError, KeyError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)
    if not incremental and watch:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + "--watch rebuilds with Sphinx; this catalog is built with MkDocs ([project] writer = \"mkdocs\"), "
            "whole, each time. Run it without --watch.",
            err=True,
        )
        raise SystemExit(1)
    _run_docs_build(
        project_dir,
        incremental=incremental,
        watch=watch,
        watch_interval=watch_interval,
        output_dir=output_dir,
        project_dir=project_dir,
        _docs_dir=_docs_dir,
        temp_docs_src_dir=temp_docs_src_dir,
        should_remove_existing=force_write,
        strict=strict,
    )
    if watch:
        return

    click.echo("")
    click.echo(f"Catalog built successfully: {output_dir / 'index.html'}")
    click.echo("Run 'chartbook catalog browse' to open in your browser.")


@catalog.command("browse")
def catalog_browse():
    """Open the global catalog documentation in your default browser."""

    catalog_path = _default_catalog_path()
    if catalog_path is None:
        click.echo("Error: No global catalog found.", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook catalog init' to create one.", err=True)
        raise SystemExit(1)

    index_path = catalog_path.parent / "docs" / "index.html"
    if not index_path.is_file():
        click.echo("Error: Catalog docs not found.", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook catalog build' first.", err=True)
        raise SystemExit(1)

    import webbrowser

    url = index_path.as_uri()
    click.echo(f"Opening {index_path}")
    if not webbrowser.open(url):
        click.echo(f"Could not open browser. Open this URL manually: {url}")


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
    except (KeyError, ValueError) as e:
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
    except (KeyError, ValueError) as e:
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
    except (KeyError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


def _echo_pin_report(report):
    """Print what a pin or an update did, one line per dependency and exception."""
    from chartbook.check import display_path

    by_dependency = {}
    for event in report.events:
        by_dependency.setdefault(event.dependency, []).append(event)

    for dependency, events in by_dependency.items():
        whole = [e for e in events if e.asset is None]
        assets = [e for e in events if e.asset is not None]
        counts = {}
        for event in assets:
            counts[event.status] = counts.get(event.status, 0) + 1
        words = {
            "pinned": "pinned",
            "restored": "put back in the store",
            "moved": "moved",
            "kept": "already pinned",
            "stale": "changed upstream since it was pinned",
            "not_built": "not built",
            "outside": "outside the repository",
            "let_go": "let go",
            "dropped": "no longer declared",
            "lost": "lost",
        }
        summary = ", ".join(
            f"{counts[status]} {words[status]}" for status in words if status in counts
        )
        for event in whole:
            if event.status == "fetched":
                click.echo(f"{dependency}: fetched {event.detail}")
            elif event.status == "removed":
                summary = "no longer a dependency; its pins are let go"
            elif event.status in ("unreachable", "unfetched", "no_snapshot"):
                note = f"cannot be pinned: {event.detail}"
                summary = f"{note}; {summary}" if summary else note
        click.echo(f"{dependency}: {summary or 'declares nothing to pin'}")
        for event in whole:
            if event.status == "relocated":
                click.echo(
                    f"  [dependencies] now says {event.detail}. It stays pinned "
                    f"where it was: `chartbook update {dependency}` follows it."
                )

        for event in assets:
            if event.status == "moved":
                click.echo(f"  {event.asset}\n    {event.old} -> {event.new}")
            elif event.status == "not_built":
                click.echo(f"  not built: {event.asset} ({event.detail})")
            elif event.status == "stale":
                click.echo(f"  changed upstream: {event.asset}")
            elif event.status == "let_go":
                click.echo(f"  let go: {event.asset} ({event.detail})")
            elif event.status == "outside":
                click.echo(f"  not pinned: {event.asset}: {event.detail}")
            elif event.status == "dropped":
                click.echo(f"  no longer declared: {event.asset}")
            elif event.status == "lost":
                click.echo(f"  lost: {event.asset} ({event.old}): {event.detail}")
        if dependency in report.snapshots:
            taken = report.snapshots[dependency]
            made_in = f" of {taken.repository}" if getattr(taken, "repository", "") else ""
            click.echo(
                f"  From its snapshot{made_in} at {taken.commit[:7]}, made {_when(taken.made_at)}."
            )
        if dependency in report.from_folder:
            click.echo("  Taken from its folder as it is now, not from a snapshot.")
        if dependency in report.git and counts.get("let_go"):
            click.echo(
                "  What was let go was built at the commit pinned before, and is "
                "not built at this one. `chartbook run` builds it and pins it."
            )
        elif counts.get("let_go"):
            click.echo("  What was let go is not built in the snapshot this moved to.")
        if dependency in report.git and counts.get("not_built"):
            click.echo("  A git dependency has only what its repository commits.")

    if not report.events:
        click.echo("No dependencies to pin.")
    shown = display_path(report.lockfile, relative_to=Path.cwd())
    if report.written:
        click.echo(f"Wrote {shown}.")
    elif report.lockfile.exists():
        click.echo(f"{shown} is unchanged.")

    stale = report.count("stale")
    if stale:
        click.echo(
            f"{stale} pinned asset(s) have changed upstream. `chartbook update` "
            f"moves the pins."
        )


def _when(made_at):
    """A snapshot's time as a person reads it: 2026-10-13 18:22 UTC."""
    return f"{made_at[:10]} {made_at[11:16]} UTC"


def _run_pin(project_dir, dependencies=None, from_folder=False):
    """Run a pin, or an update when *dependencies* is given; exit 1 on a problem."""
    from chartbook import lock
    from chartbook.store import StoreError

    project_dir = resolve_project_dir(project_dir)
    try:
        if dependencies is None:
            report = lock.pin(project_dir, from_folder=from_folder)
        else:
            report = lock.update(project_dir, dependencies, from_folder=from_folder)
    except (lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    _echo_pin_report(report)
    if report.unrooted:
        click.echo(
            f"The store is read-only for you, so its note of this lockfile could not "
            f"be updated, and its `store gc` goes by the note it has ({report.unrooted})."
        )
    if report.problems:
        click.echo(
            f"\n{len(report.problems)} thing(s) could not be pinned.", err=True
        )
        raise SystemExit(1)


#: Off by default and left out of --help on purpose: the ordinary way is a
#: snapshot. It is for someone working on both pipelines at once.
_from_folder = click.option(
    "--from-folder",
    is_flag=True,
    hidden=True,
    help="Take a path dependency from what is in its folder now, not from a snapshot",
)


def _echo_frozen_report(step, report):
    """Print what `--frozen` found: one line when all is well, else each problem."""
    who = f"{step.id}: " if step is not None else ""
    if not report.problems and not report.dependencies:
        click.echo(f"{who}no dependencies to check. Nothing written.")
        return
    if not report.problems:
        click.echo(
            f"{who}{report.pins} pin(s) of {report.dependencies} dependenc"
            f"{'y' if report.dependencies == 1 else 'ies'}, all in the store. Nothing written."
        )
        return
    for problem in report.problems:
        where = problem.asset or problem.dependency
        click.echo(f"{who}{where + ': ' if where else ''}{problem.message}", err=True)
    click.echo(
        f"{who}{len(report.problems)} problem(s): the pipeline cannot be built from its "
        f"lockfile alone. Nothing written.",
        err=True,
    )


@main.command()
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@click.option(
    "--frozen",
    is_flag=True,
    help="Write nothing: say whether the lockfile is complete and every pin is in the store",
)
@_from_folder
def pin(project_dir, frozen, from_folder):
    """Freeze what this pipeline depends on.

    Each pipeline in [dependencies] is pinned to a snapshot of it: what its
    owner declared ready, at a commit (`chartbook snapshot`). The content
    hash of each of its assets is written to chartbook.lock. Commit that
    file: a change to what the project depends on then shows in a diff.

    Nothing in the other pipeline's folder is read. It can be half-way
    through a change, and what you pin is still the build that was
    declared ready.

    A pin that already exists is never moved, whatever the other pipeline
    has done since; `chartbook update` moves pins. What `pin` does do again
    is pin a dependency that has no pin yet.

    A dependency that is a git repository is fetched, and pinned from a
    clean copy of the commit.

    --frozen pins nothing and writes nothing: not the lockfile, not the
    store. It says whether the pipeline can be built from its lockfile
    alone, every dependency pinned and every pin in the store, and exits
    1 if not. For CI, and for a store you may only read.

    \b
    Examples:
        chartbook pin
        chartbook pin --project-dir ../rate_forecast
        chartbook pin --frozen
    """
    if frozen and from_folder:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + "--frozen writes nothing, and --from-folder pins. One or the other.",
            err=True,
        )
        raise SystemExit(1)
    if frozen:
        _run_frozen(project_dir)
        return
    _run_pin(project_dir, from_folder=from_folder)


def _explain_os_error(error):
    """An OSError as a sentence: what a read-only store means, else the error."""
    from chartbook import lock
    from chartbook.store import ReadOnlyStoreError, default_store

    if isinstance(error, ReadOnlyStoreError):
        return (
            f"{error} This had to write it: a git dependency's first pin, --from-folder, and a "
            f"snapshot all put files into the store. Do it where the store can be written; or, "
            f"if the store already has what the lockfile names, use --frozen."
        )
    if isinstance(error, OSError) and lock.is_read_only(error):
        try:
            root = str(default_store())
        except Exception:  # pragma: no cover - the store path is unreadable
            root = ""
        if root and str(getattr(error, "filename", "") or "").startswith(root):
            return (
                f"The store at {root} is read-only for you, and this had to write "
                f"it: a git dependency's first pin, --from-folder, and a snapshot "
                f"all put files into the store. Do it where the store can be "
                f"written; or, if the store already has what the lockfile names, "
                f"use --frozen. ({error})"
            )
    return str(error)


def _run_frozen(project_dir):
    """Say whether a pipeline can be built from its lockfile alone; exit 1 if not."""
    from chartbook import lock
    from chartbook.store import StoreError

    try:
        report = lock.verify(resolve_project_dir(project_dir))
    except (lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    _echo_frozen_report(None, report)
    if report.problems:
        raise SystemExit(1)


@main.command()
@click.argument("dependencies", nargs=-1)
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@_from_folder
def update(dependencies, project_dir, from_folder):
    """Move pins forward to the newest snapshot of each dependency.

    With no argument, every dependency is updated. Name some to update only
    those, as they are written in [dependencies]; the scope may be left off
    when only one has that name. Each pin that changes is printed with its
    old and new hash, and chartbook.lock is rewritten.

    Nothing is rebuilt: this pipeline's own outputs are as they were.

    \b
    Examples:
        chartbook update
        chartbook update fed_yield_curve
    """
    _run_pin(project_dir, dependencies=list(dependencies), from_folder=from_folder)


@main.command("add")
@click.argument("pipeline")
@click.option("--as", "key", metavar="NAME", help="The name to know it by in code, PIPELINE by default (`NAME:dataframe`)")
@click.option("--commit", metavar="COMMIT", help="Take its snapshots at this commit (the start of one), not the newest")
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
def add_command(pipeline, key, commit, project_dir):
    """Declare a dependency on another pipeline by its ID, and pin its newest snapshot from the store.

    Writes `"PIPELINE" = {}` under [dependencies] in this pipeline's
    chartbook.toml, leaving the rest of the file as it is, then runs
    `chartbook pin`. The pipeline is read from its snapshots in the store
    alone: no folder of it here, and no clone. `chartbook update` moves the
    pin to a newer snapshot.

    \b
    Examples:
        chartbook add acme/rates
        chartbook add acme/rates --as rates
        chartbook add acme/rates --commit 3f2a9c1
    """
    from chartbook.identity import validate_pipeline_id
    from chartbook.manifest import dependency_line, validate_dependencies, with_dependency

    project_dir = resolve_project_dir(project_dir)
    manifest_file = project_dir / "chartbook.toml"
    try:
        validate_pipeline_id(pipeline)
        from chartbook.snapshot import SnapshotError, pipeline_in

        try:
            itself = pipeline_in(project_dir)
        except (SnapshotError, ValueError):
            itself = None
        if pipeline == itself:
            raise ValueError(f"{pipeline} is this pipeline itself: a pipeline cannot depend on itself.")
        key = key or pipeline
        entry = {}
        if key != pipeline:
            entry["id"] = pipeline
        if commit:
            entry["commit"] = commit
        with open(manifest_file, encoding="utf-8", newline="") as f:  # as it is, line endings included
            text = f.read()
        changed = with_dependency(text, key, entry)
        import tomli

        validate_dependencies(tomli.loads(changed).get("dependencies") or {}, project_dir)
    except (ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    with open(manifest_file, "w", encoding="utf-8", newline="") as f:
        f.write(changed)
    click.echo(f"Added to [dependencies] in {manifest_file}: {dependency_line(key, entry)}")
    _run_pin(project_dir)


@main.command()
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@click.option(
    "--deep",
    is_flag=True,
    help="Also refuse if any snapshot upstream has a gap in its own lineage (see `chartbook lineage`)",
)
def snapshot(project_dir, deep):
    """Declare this pipeline's build ready for the pipelines that depend on it.

    Every asset the pipeline declares and has built is copied into the
    store, labelled with the commit the pipeline is at. That is a snapshot,
    and it is what other pipelines pin: they never read this folder. With
    the bytes go the pipeline's own index at that commit and the files a
    site needs (the manifest, the README, the write-ups, the site pages),
    only those git tracks, so a version's site can be built from the store.

    Everything in the pipeline's folder must be committed first. The label
    says "this is what that commit built", and with uncommitted changes it
    would not be true. What git ignores, such as built data, does not count.

    A snapshot is made when you ask for one, not by every build. Until you
    make another, pipelines that depend on this one keep getting this one,
    however much you change here. When you do, they get it with
    `chartbook update`, and not before.

    Build first: this does not run the build. `chartbook run` does.

    \b
    Examples:
        chartbook run && chartbook snapshot
        chartbook snapshot --project-dir ../fed_yield_curve
    """
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError

    project_dir = resolve_project_dir(project_dir)
    try:
        report = snapshots.make(project_dir, deep=deep)
    except (snapshots.SnapshotError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)

    _echo_snapshot(report)


def _lineage_line(node) -> str:
    """How one pipeline of a lineage is shown."""
    made = f"{node.made_at[:10]} {node.made_at[11:19]} UTC" if node.made_at else ""
    if node.kind == "working":
        return f"{node.pipeline} (this folder)"
    if node.kind == "snapshot":
        seen = " (shown above)" if node.seen else ""
        checked = {"pins": "pins checked", "deep": "lineage checked"}.get(node.checked, "made before pins were checked")
        tagged = f", tagged {', '.join(node.tags)}" if node.tags else ""
        return f"{node.label}: {node.pipeline} {node.commit[:7]}{tagged}, made {made}, {checked}{seen}"
    if node.kind == "git":
        at = f" at {node.commit[:7]}" if node.commit else ""
        return f"{node.label}: pinned from its git clone{at}; not walked further"
    if node.kind == "folder":
        return f"{node.label}: pinned from its working folder"
    if node.kind == "nothing":
        return f"{node.label}: nothing pinned"
    if node.kind == "mismatch":
        return f"{node.label}: its snapshot at {node.commit[:7]} does not hold what was pinned"
    if node.kind == "unreadable":
        return f"{node.label}: a record that cannot be read"
    return f"{node.label}: not found in the store"


def _lineage_lines(node, prefix: str = "", last: bool = True, top: bool = True) -> list:
    """A lineage as a tree, each gap under the pipeline it is at."""
    lines = [(prefix + ("" if top else ("└── " if last else "├── "))) + _lineage_line(node)]
    inner = prefix + ("" if top else ("    " if last else "│   "))
    for gap in node.gaps:
        lines.append(f"{inner}{'│ ' if node.children else '  '} gap: {gap}")
    for number, child in enumerate(node.children):
        lines += _lineage_lines(child, inner, number == len(node.children) - 1, top=False)
    return lines


@main.command("lineage")
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@click.option("--check", is_flag=True, help="Exit 1 if there is any gap: for CI")
@click.option(
    "--rehash",
    is_flag=True,
    help="Also hash every asset of every snapshot again, which reads all of their bytes",
)
@click.option("--json", "as_json", is_flag=True, help="Print the lineage as JSON")
def lineage_command(project_dir, check, rehash, as_json):
    """Show where this pipeline's data comes from: every snapshot upstream, and any gap.

    Follows the pins up from this pipeline's lockfile: each snapshot it is
    pinned to, the snapshots those were pinned to, and so on. Each step is
    checked: the snapshot is in the store, what was pinned is what it
    holds (by hash), and its recorded pins cover every dependency its own
    manifest declares. Nothing is written.

    \b
    Examples:
        chartbook lineage
        chartbook lineage --check
        chartbook lineage --rehash --json
    """
    import json

    from chartbook import lineage
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError

    project_dir = resolve_project_dir(project_dir)
    try:
        found = lineage.walk(project_dir, rehash=rehash)
    except (snapshots.SnapshotError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(2)
    gaps = found.gaps()
    if as_json:
        click.echo(json.dumps(found.to_dict(), indent=2))
    else:
        for line in _lineage_lines(found.root):
            click.echo(line)
        rehashed = f", {found.rehashed} object(s) hashed again" if rehash else ""
        said = f"{len(gaps)} gap(s)" if gaps else "no gaps"
        click.echo(f"{found.snapshots} snapshot(s) upstream{rehashed}; {said}.")
    if check and gaps:
        raise SystemExit(1)


@main.command("run")
@click.argument("script", required=False, default="build")
@click.option(
    "--project-dir",
    type=click.Path(),
    help="Path to the pipeline, or to a catalog (default: the current directory)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Build a git dependency again, even if it is built already",
)
@click.option(
    "--snapshot",
    "make_snapshot",
    is_flag=True,
    help="After the build, declare it ready: make a snapshot (see `chartbook snapshot`)",
)
@click.option(
    "--frozen",
    is_flag=True,
    help="Pin nothing and write nothing before the build; refuse unless every pin is in the store",
)
def run_command(script, project_dir, force, make_snapshot, frozen):
    """Run a script in this pipeline: `build`, unless another is named.

    SCRIPT is a name from [scripts] in chartbook.toml.

    \b
        [scripts]
        build = "doit"
        test = "pytest"

    `build` is the script that makes a pipeline's data current. Before it
    runs, whatever this pipeline depends on and has not pinned yet is
    pinned, so its code can read it. A pin that exists is never moved: you
    are told what has changed, and `chartbook update` moves pins.

    It never builds in a folder this pipeline depends on. That folder is
    somebody's work, and this pipeline reads what is pinned, not what is
    there.

    A dependency that is a git repository is built once, in ChartBook's own
    clean copy of the commit, so that what it builds can be pinned. --force
    builds it again, which is how data it pulls from outside is refreshed.

    In a catalog, the script is run in each of the catalog's pipelines.

    --snapshot builds and then declares the build ready, in one command.
    It is `chartbook run` followed by `chartbook snapshot`, with two
    differences: it checks that everything is committed before it builds,
    and the snapshot records that the build ran in the same command.

    \b
    Examples:
        chartbook run
        chartbook run test
        chartbook run --force
        chartbook run --snapshot
        chartbook run --frozen

    --frozen pins nothing and writes nothing before the build: not the
    lockfile, not the store, and no git dependency is fetched or built.
    The build runs only if the lockfile is complete and every pin is in
    the store (`chartbook pin --frozen` says the same without building).
    For CI, and for a store you may only read.
    """
    _run_script(
        resolve_project_dir(project_dir),
        script,
        force=force,
        snapshot=make_snapshot,
        frozen=frozen,
    )


def _has_script(project_dir, script):
    """Whether a pipeline, or any pipeline of a catalog, has a script by this name."""
    from chartbook import run as runner

    try:
        steps = runner.plan(project_dir, git=False)
    except (runner.RunError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)
    return any(script in step.scripts for step in steps if step.source == "asked")


def _echo_snapshot(report):
    """Print what making a snapshot did."""
    taken = report.snapshot
    built = sum(1 for record in taken.assets.values() if record.get("content_hash"))
    summary = f"{built} asset(s) in the store"
    if report.not_built:
        summary += f", {len(report.not_built)} not built"
    click.echo(f"{taken.pipeline} at {taken.commit[:7]}: {summary}")
    for asset, declared_path in report.not_built:
        click.echo(f"  not built: {asset} ({declared_path})")
    for model, version in report.new_versions:
        click.echo(f"  {model}: new version {version}")
    if report.index_skipped:
        click.echo(
            f"  index not recorded: {report.index_skipped}. The bytes and the documents are in the "
            f"store; `chartbook check` says what a docs build would refuse."
        )
    for path, why in report.documents_skipped:
        shown = path if path.isprintable() else ascii(path)  # a name may carry what a terminal would act on
        click.echo(f"  document not kept: {shown} ({why})")
    for model, label in report.skipped_labels:
        click.echo(
            f"  label not recorded: {model} {label!r}. A label is letters, digits, '.', "
            f"'_' and '-', does not read as a hash, and names a version by twelve or more "
            f"of its digits; `chartbook check` says the same."
        )
    if report.made:
        click.echo(
            "Snapshot made. A pipeline that depends on this one gets it with "
            "`chartbook update`."
        )
    else:
        click.echo(
            f"Nothing has changed since the snapshot of {_when(taken.made_at)}. "
            f"No new one was made."
        )


def _run_script(project_dir, script, force=False, snapshot=False, frozen=False):
    """Run a named script as `chartbook run` does; exit with its code if it fails."""
    from chartbook import lock
    from chartbook import run as runner
    from chartbook.store import StoreError

    def show_pins(step, pins):
        # Said only when there is something to say: a pin that is not
        # simply still in place, or a lockfile that was written
        quiet = ("kept", "not_built")  # as they were the last time
        if pins.written or any(event.status not in quiet for event in pins.events):
            click.echo(f"{step.id}: pinning what it depends on")
            _echo_pin_report(pins)

    try:
        report = runner.run(
            project_dir,
            script,
            echo=click.echo,
            on_pin=show_pins,
            force=force,
            snapshot=snapshot,
            on_snapshot=lambda step, made: _echo_snapshot(made),
            frozen=frozen,
            on_verify=_echo_frozen_report,
        )
    except (runner.RunError, lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)

    if report.failed is not None:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"{report.failed.id}: {report.reason}. Nothing after it was run.",
            err=True,
        )
        raise SystemExit(report.exit_code or 1)
    click.echo(f"Ran {script} in {len(report.ran)} pipeline(s).")


@main.group()
def store():
    """Look after the store: the local folder of pinned files.

    The store keeps files under the hash of what is in them. It is at
    ~/.chartbook/store unless CHARTBOOK_STORE, or [store] url in
    ~/.chartbook/settings.toml or in the organization's settings file
    (/etc/chartbook/settings.toml, or what CHARTBOOK_SYSTEM_SETTINGS names), says
    otherwise.
    """


@store.command("verify")
def store_verify():
    """Hash every object in the store again; exit nonzero if one has changed.

    An object's name is the hash of its content, so this finds whatever has
    changed since it was stored: a file the store hard-linked or symlinked
    to that has since been rewritten, a link whose file has gone, or
    anything edited in the store by hand. Every byte is read, so on a large
    store it takes a while.

    Examples:
        chartbook store verify
        CHARTBOOK_STORE=/shared/store chartbook store verify
    """
    from chartbook.store import StoreError, default_store

    try:
        the_store = default_store()
        total = len(list(the_store.hashes()))
        problems = the_store.verify()
    except (StoreError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        raise SystemExit(1)

    for problem in problems:
        click.echo(problem.format())
    if problems:
        click.echo(
            f"\n{len(problems)} of {total} object(s) in {the_store} are "
            f"not what their names say.",
            err=True,
        )
        raise SystemExit(1)
    click.echo(f"{the_store}: OK ({total} object(s))")


def _format_bytes(size):
    """A size for a person: ``18.2 KB``, ``4.1 GB``."""
    size = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} bytes" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024


@store.command("gc")
@click.option("--dry-run", is_flag=True, help="List what would be removed, and remove nothing")
@click.option("--yes", "-y", is_flag=True, help="Do not ask")
@click.option(
    "--forget-missing",
    is_flag=True,
    help="Stop keeping the pins of a lockfile that cannot be found (on a store a team shares, that is every other machine's)",
)
@click.option(
    "--keep-days",
    type=click.FloatRange(min=0),
    default=None,
    metavar="DAYS",
    help="Keep a snapshot that nothing pins and that is not the newest of its pipeline for this long (default: 7)",
)
@click.option(
    "--keep-lineage",
    is_flag=True,
    help="Also keep every snapshot a kept snapshot was made from, as far up as it goes, so `chartbook lineage` finds them all",
)
@click.option(
    "--aggressive",
    is_flag=True,
    help="Let names keep nothing: no snapshot is kept for a git tag or branch, or for a model label",
)
def store_gc(dry_run, yes, forget_missing, keep_days, keep_lineage, aggressive):
    """Remove from the store what nothing needs any more.

    The store is shared by every project of yours. Two things keep what is
    in it. A lockfile: each `chartbook pin` and `chartbook update` notes
    its lockfile here, and every object one of them names is kept. And a
    snapshot: what `chartbook snapshot` kept of a pipeline at a commit.

    A snapshot is kept if a lockfile pins it, if it is the newest of its
    pipeline or the newest a branch or tag can pin from, if a label points
    at a model version in it (in that pipeline's chartbook.toml, or as its
    newest snapshot recorded), or if it was made in the last 7 days
    (--keep-days). Otherwise it may be removed, and what only it named
    goes with it. A store keeps what work needs now, and lets old lineage
    go: with --keep-lineage, every snapshot a kept snapshot was made from
    is kept too, as far up as it goes, for `chartbook lineage` to check.
    With --aggressive, names keep nothing: a snapshot a git tag or branch
    names, or one holding a labelled model version, goes once nothing else
    keeps it.

    A lockfile that cannot be found, because its project was deleted or its
    drive is not plugged in, still keeps what it last pinned. Pass
    --forget-missing to let those go. On a store a team shares, every other
    machine's lockfile is one that cannot be found from here, so there the
    store's owner runs gc without it.

    What would be removed is listed, and nothing is removed until you say
    yes. An object stored in the last hour is never removed: a pin puts
    files in the store before it writes the lockfile that names them.

    \b
    Examples:
        chartbook store gc --dry-run
        chartbook store gc
        chartbook store gc --keep-days 7
        chartbook store gc --yes --forget-missing
        chartbook store gc --keep-lineage
        chartbook store gc --aggressive --keep-days 0
    """
    from chartbook import lock
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError, default_store

    days = keep_days if keep_days is not None else snapshots.KEEP_DAYS
    try:
        the_store = default_store()
        plan = lock.plan_gc(the_store, forget_missing=forget_missing, keep_days=days, keep_lineage=keep_lineage, aggressive=aggressive)
    except (StoreError, lock.LockError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        click.echo("Nothing was removed.", err=True)
        raise SystemExit(1)

    click.echo(f"Kept: {plan.kept} object(s), named by {len(plan.lockfiles)} lockfile(s)")
    for lockfile, found in plan.lockfiles:
        if found:
            note = ""
        elif lockfile in plan.not_read:
            note = "  (not read: not a chartbook.lock on this machine; its pins are kept)"
        elif forget_missing:
            note = "  (not found; forgotten)"
        else:
            note = "  (not found; its pins are kept)"
        click.echo(f"  {lockfile}{note}")
    if plan.snapshots_kept:
        reasons = {}
        for _, why in plan.snapshots_kept:
            reasons[why] = reasons.get(why, 0) + 1
        said = ", ".join(f"{count} because {why}" for why, count in reasons.items())
        click.echo(
            f"Kept: {len(plan.snapshots_kept)} snapshot(s), naming {plan.snapshots} "
            f"object(s): {said}"
        )
    if plan.recent:
        click.echo(
            f"Kept: {len(plan.recent)} object(s) nothing names, stored in the last hour"
        )

    if any(not found for _, found in plan.lockfiles) and any(
        "cannot be found" in why for _, why in plan.snapshots_kept
    ):
        click.echo(
            "  A lockfile that cannot be found keeps every snapshot that holds "
            "something it named. --forget-missing lets them go; on a store a team "
            "shares, that includes what other machines pin."
        )

    if not plan.delete and not plan.snapshots_delete:
        click.echo("Nothing to remove.")
        if not dry_run:
            lock.run_gc(plan, the_store)  # forgets the missing, if asked to
        return

    if plan.snapshots_delete:
        click.echo(f"Would remove {len(plan.snapshots_delete)} snapshot(s):")
        for taken, why in plan.snapshots_delete:
            click.echo(
                f"  {taken.pipeline} at {taken.commit[:7]}, made "
                f"{_when(taken.made_at)}: {why}"
            )
    summary = (
        f"{len(plan.delete)} object(s), {_format_bytes(plan.size_bytes)}, that "
        f"nothing names"
    )
    if dry_run:
        if plan.delete:
            click.echo(f"Would remove {summary}:")
            for content_hash, size in plan.delete:
                click.echo(f"  {content_hash}  {_format_bytes(size)}")
        return
    if plan.delete:
        click.echo(f"Would remove {summary}.")
    if not yes and not click.confirm("Remove them?", default=False):
        click.echo("Nothing was removed.")
        return
    removed_snapshots, removed = lock.run_gc(plan, the_store)
    click.echo(
        f"Removed {removed_snapshots} snapshot(s) and {removed} object(s), "
        f"{_format_bytes(plan.size_bytes)}."
    )
    spared = len(plan.snapshots_delete) - removed_snapshots + len(plan.delete) - removed
    if spared:
        click.echo(f"{spared} of them were pinned while you were deciding, and kept.")

@main.command()
@click.option(
    "--git",
    "use_git",
    is_flag=True,
    default=False,
    help="Run git init in the new project and make an initial commit",
)
@click.option(
    "--github",
    "use_github",
    is_flag=True,
    default=False,
    help="Also create a GitHub repository for it with gh and push the commit "
    "(implies --git)",
)
@click.option(
    "--public/--private",
    "public",
    default=None,
    help="Visibility of the repository --github creates (default: private)",
)
def init(use_git, use_github, public):
    """Initialize a new chartbook project from the cookiecutter template.

    The template is the `template/` folder of ChartBook's repository. It is
    rendered with cruft, so `cruft update` in the new project brings in
    later changes to it.

    With --git, the new project is also made a git repository with one
    commit. With --github, a GitHub repository is then created for it under
    the account `gh` is logged in as, and the commit is pushed. Both are off
    by default.

    --github needs the GitHub CLI installed and logged in (`gh auth login`).
    That is checked first, so if it is missing nothing is created.

    Examples:
        chartbook init
        chartbook init --git
        chartbook init --github
        chartbook init --github --public
    """
    try:
        import cruft  # noqa: F401
    except ImportError:
        click.echo("Error: cruft is not installed.", err=True)
        click.echo("", err=True)
        click.echo(
            "cruft ships with chartbook, so this usually means a broken or"
            " partial installation. Reinstall with:", err=True
        )
        click.echo("    pip install --force-reinstall chartbook", err=True)
        raise SystemExit(1)

    import subprocess

    from chartbook import scaffold

    if public is not None and not use_github:
        raise click.UsageError("--public/--private only applies with --github.")
    use_git = use_git or use_github
    cwd = Path.cwd()

    def fail(error):
        click.echo(click.style("Error: ", fg="red", bold=True) + str(error), err=True)
        raise SystemExit(1)

    if use_git:
        # Before the template is rendered, so a missing tool or login
        # leaves nothing behind
        try:
            scaffold.preflight(cwd, use_github=use_github)
        except scaffold.ScaffoldError as e:
            fail(e)
        outer_repo = scaffold.enclosing_repository(cwd)
        if outer_repo:
            click.echo(
                f"Note: {cwd} is inside the git repository {outer_repo}; the "
                f"new project will be its own repository nested in it.",
                err=True,
            )

    if not use_git:
        try:
            rendered = subprocess.run(scaffold.template_command())
        except KeyboardInterrupt:
            raise SystemExit(130)
        if rendered.returncode != 0:
            raise SystemExit(rendered.returncode)
        return

    # The project's directory is named from an answer at cruft's prompt, so
    # it is identified afterwards as the one that was not here before
    before = scaffold.rendered_projects(cwd)
    rendered = subprocess.run(scaffold.template_command())
    if rendered.returncode != 0:
        raise SystemExit(rendered.returncode)

    try:
        project_dir = scaffold.find_new_project(cwd, before)
        scaffold.git_init_and_commit(project_dir)
        click.echo(f"Initialized a git repository in {project_dir} with one commit.")
        if use_github:
            created = scaffold.github_create_and_push(project_dir, public=bool(public))
            visibility = "public" if public else "private"
            click.echo(f"Created a {visibility} GitHub repository and pushed:")
            click.echo(f"  {created}")
    except scaffold.ScaffoldError as e:
        fail(e)

    if use_github:
        # With the remote in place, the pipeline's scope comes from it
        import tomli

        from chartbook.identity import clear_git_remote_cache, derive_pipeline_id

        clear_git_remote_cache()
        manifest_path = project_dir / "chartbook.toml"
        project_table = {}
        if manifest_path.is_file():
            with open(manifest_path, "rb") as f:
                project_table = tomli.load(f).get("project", {})
        click.echo(f"Pipeline ID: {derive_pipeline_id(project_table, project_dir)}")


@main.command()
def config():
    """Configure the default catalog path for data loading.

    Sets the path to a catalog's ``chartbook.toml`` in
    ``~/.chartbook/settings.toml`` so that ``data.load()`` can find
    pipelines without an explicit ``catalog_path`` argument.
    """
    from chartbook.config import (
        set_default_catalog_path,
    )

    current = _default_catalog_path()
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

    resolved = _default_catalog_path()
    click.echo(f"Catalog path set to: {resolved}")
    click.echo("")
    click.echo("You can now load data with:")
    click.echo('  from chartbook import data')
    click.echo('  df = data.load(pipeline="my_pipeline", dataframe="my_df")')


@main.group()
def install():
    """Install bundled resources into the current project."""


VERSION_STAMP_NAME = ".chartbook-skill-version"


@install.command("skill")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing skill files without prompting",
)
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Install into ./.claude/skills/ in the current directory (commit it "
    "to share the skill with everyone working in the repo) instead of the "
    "user-level skills directory",
)
def install_skill(force, project):
    """Install the bundled Claude Code skill.

    By default the skill is installed user-level — into
    ``~/.claude/skills/chartbook/``, or ``$CLAUDE_CONFIG_DIR/skills/chartbook/``
    when that variable is set — so it is available in every Claude Code
    session. With ``--project`` it is installed into
    ``./.claude/skills/chartbook/`` in the current directory instead.

    The command is idempotent: if the installed files already match the
    bundled skill, nothing is rewritten. Files from older skill layouts are
    removed so the installed copy exactly mirrors the bundled one, and the
    installing chartbook version is recorded alongside the skill files.

    :param force: If True, overwrite existing files without prompting.
    :type force: bool
    :param project: If True, install into the current directory's .claude/
        instead of the user-level skills directory.
    :type project: bool
    """
    import importlib.resources
    import os
    import shutil

    package_path = importlib.resources.files("chartbook")
    skills_src = Path(str(package_path)) / "skills"

    skill_files = sorted(
        p for p in (skills_src.iterdir() if skills_src.is_dir() else []) if p.is_file()
    )
    if not skill_files:
        click.echo("Error: No bundled skill files found in package.", err=True)
        raise SystemExit(1)

    if project:
        base_dir = Path.cwd() / ".claude"
    else:
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        base_dir = (
            Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
        )
    target_dir = base_dir / "skills" / "chartbook"
    expected_names = {p.name for p in skill_files}

    def _visible_files():
        return [
            p
            for p in target_dir.iterdir()
            if p.is_file() and not p.name.startswith(".")
        ]

    # Idempotent no-op: the installed files already match the bundled skill.
    # Hidden files (the version stamp, .DS_Store, ...) don't affect the check.
    if target_dir.is_dir():
        current = _visible_files()
        if {p.name for p in current} == expected_names and all(
            (target_dir / p.name).read_bytes() == p.read_bytes() for p in skill_files
        ):
            (target_dir / VERSION_STAMP_NAME).write_text(f"{__version__}\n")
            click.echo(f"Skill already up to date in {target_dir}")
            return

    if target_dir.is_dir() and any(_visible_files()) and not force:
        click.echo(f"Skill files already exist in {target_dir}")
        if not click.confirm("Overwrite existing files?"):
            raise SystemExit(0)

    target_dir.mkdir(parents=True, exist_ok=True)

    # Drop files from older skill layouts (e.g. REFERENCE.md) so the
    # installed copy exactly mirrors the bundled skill
    for existing in _visible_files():
        if existing.name not in expected_names:
            existing.unlink()
            click.echo(f"  removed stale {existing.name}")

    copied = 0
    for src_file in skill_files:
        shutil.copyfile(src_file, target_dir / src_file.name)
        click.echo(f"  {src_file.name}")
        copied += 1

    (target_dir / VERSION_STAMP_NAME).write_text(f"{__version__}\n")
    click.echo(f"\nInstalled {copied} skill file(s) to {target_dir}")


if __name__ == "__main__":
    main()
