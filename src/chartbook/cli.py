from __future__ import annotations

import contextlib
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


class _Group(click.Group):
    """A group that tells a user who types a command's old name what it is called now.

    ``renamed`` maps a first word that used to be a command of the group
    to the words that stand in its place; ``arguments_go_to`` names the
    subcommand that takes what the group itself took while it was a
    command, so that ``chartbook docs ./site -f`` is told to say
    ``chartbook docs generate ./site -f``. Either is one usage error with
    the line to type; nothing is run under the old name.
    """

    renamed: dict = {}
    arguments_go_to: str = ""

    def parse_args(self, ctx, args):
        if ctx.resilient_parsing:
            return super().parse_args(ctx, args)  # shell completion asking: nothing to say
        first = args[0] if args else None
        if first is not None and first not in self.commands and first != "--help":
            # The words as a person types them, whatever the program was invoked
            # as (`chartbook`, `main` under a test, `python -m chartbook.cli`)
            root = ctx.find_root().info_name or ""
            tail = ctx.command_path[len(root):] if ctx.command_path.startswith(root) else ""
            path = ("chartbook" + tail).strip()
            if first in self.renamed:
                old, new, rest = f"{path} {first}", f"{path} {self.renamed[first]}", args[1:]
            elif self.arguments_go_to and _reads_as_an_argument(first):
                # An option or a path, as the command took them; a word that is
                # neither may be a misspelt subcommand, which click says
                old, new, rest = path, f"{path} {self.arguments_go_to}", args
            else:
                return super().parse_args(ctx, args)
            raise click.UsageError(f"`{old}` is `{new}` now. Try: {' '.join([new, *rest])}", ctx)
        return super().parse_args(ctx, args)


def _reads_as_an_argument(word: str) -> bool:
    """Whether a first word is an option or a path, rather than a possible subcommand."""
    import os

    return word.startswith(("-", ".")) or "/" in word or os.sep in word or os.path.exists(word)


class _Main(_Group):
    renamed = {"browse": "docs open"}


class _Docs(_Group):
    arguments_go_to = "generate"


class _Catalog(_Group):
    renamed = {"build": "generate", "browse": "open"}


class _Install(_Group):
    renamed = {"skill": "claude-skill"}


@click.group(cls=_Main)
@click.version_option(version=__version__)
@click.pass_context
def main(ctx):
    """chartbook CLI tool for generating documentation websites."""
    # A warning from the settings or a manifest is one line for a person,
    # not Python's file, line and source line
    warnings.showwarning = _show_warning
    # A question about trust is asked once per command, never carried to the next one in this process
    _trust_answers.clear()
    # `install` is what mends it, and `check` says it as a warning of its own
    if not ctx.resilient_parsing and ctx.invoked_subcommand not in (None, "install", "check"):
        _say_if_the_skill_is_stale()


def _stderr_is_a_terminal() -> bool:
    import sys

    try:
        return sys.stderr is not None and sys.stderr.isatty()
    except (AttributeError, ValueError, OSError):  # closed, or not a file
        return False


def _say_if_the_skill_is_stale():
    """One line on stderr for each installed copy of the Claude Code skill written for another ChartBook.

    Only for a person at a terminal: a script, CI or a test reading the
    output never sees it. Reading two small files costs nothing, and nothing
    here stops a command (``chartbook.claude_skill``).
    """
    try:
        import os

        from chartbook.run import RUN_DIR_ENV_VAR

        # Not inside a script `chartbook run` is running: its own run said it
        if not _stderr_is_a_terminal() or os.environ.get(RUN_DIR_ENV_VAR):
            return
        from chartbook import claude_skill

        for copy in claude_skill.stale():
            click.echo(click.style("Note: ", fg="yellow", bold=True) + claude_skill.notice(copy), err=True)
    except Exception:  # noqa: BLE001 - a note about the skill never stops a command
        pass


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

    `docs generate` renders it, and `build` renders it after running the
    build script, so both take the same ones.
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
            help="File size in MB above which a dataframe page does not read the file for its date range; the glimpse reads only the first rows at any size (default: 50)",
        ),
        click.option(
            "--strict/--no-strict",
            default=True,
            help="Fail on missing source files (default), except in a lone pipeline that has built nothing yet, "
            "which is rendered with a warning; typed explicitly, --strict fails on that too. In a catalog, "
            "--no-strict skips the pipelines that have missing files instead.",
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


@main.group(cls=_Docs)
def docs():
    """The documentation site: `generate` renders it, `open` opens it.

    `chartbook docs generate` renders the site from what the project has
    built and writes index.json beside it. `chartbook docs open` opens the
    rendered site in your browser. Neither builds the project's data:
    `chartbook run` does that, and `chartbook build` runs the build script
    and then generates the site.
    """


@docs.command("generate")
@_site_options
def docs_generate(**site):
    """Render the documentation site, in OUTPUT_DIR (./docs by default).

    This renders the site and writes index.json beside it. It does not
    build the project's data: `chartbook run` does that, and
    `chartbook build` does both. A lone pipeline that has built none of
    its data, charts, notebooks and models yet, as a new project has not,
    is rendered with a warning and each shown as not built; with --strict
    typed, and in a catalog, that is an error.

    By default every render starts from nothing. With --incremental the
    intermediate build directory (--docs-build-dir) is kept, pipelines whose
    files have not changed are not regenerated, and only pages that differ
    are rendered again. --watch does that in a loop: render, then again each
    time a file changes. Open the site with `chartbook docs open` and
    refresh.

    \b
    Examples:
        chartbook docs generate -f
        chartbook docs generate -f --incremental
        chartbook docs generate -f --watch
    """
    _render_site(**site)


@docs.command("open")
@click.argument("output_dir", type=click.Path(), default="./docs", required=False)
@click.option("--project-dir", type=click.Path(), help="Path to project directory")
def docs_open(output_dir, project_dir):
    """Open the generated site in your default browser.

    Looks for index.html in OUTPUT_DIR (./docs by default) and opens it
    with the system's default web browser, on macOS, Windows and Linux.

    \b
    Examples:
        chartbook docs open
        chartbook docs open ./my-docs
        chartbook docs open --project-dir /path/to/project
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
        click.echo("Run 'chartbook docs generate' first.", err=True)
        raise SystemExit(1)

    import webbrowser

    url = index_path.as_uri()
    click.echo(f"Opening {index_path}")
    if not webbrowser.open(url):
        click.echo(f"Could not open browser. Open this URL manually: {url}")


@main.command()
@_site_options
@click.option(
    "--remake",
    is_flag=True,
    help="Build even though an asset marked keep = true is not on disk while the store has a version of it (see `chartbook run --remake`)",
)
@click.option(
    "--upstream",
    is_flag=True,
    help="First build and snapshot each pipeline this one depends on by path that has no snapshot to pin (see `chartbook run --upstream`)",
)
def build(remake, upstream, **site):
    """Make everything current: run the build script, then render the site.

    The same as `chartbook run` followed by `chartbook docs generate`, and
    it takes the arguments of `chartbook docs generate`. In a catalog, the
    build script is run in each of the catalog's pipelines before the
    catalog's site is rendered.

    With no `build` script in [scripts], there is nothing to run, and only
    the site is rendered.

    Inside a build script, say `chartbook docs generate`. `chartbook build`
    there would run the script that called it; it renders the site and
    says so.

    As `chartbook run`, it stops before the build when an asset marked
    `keep = true` is not on disk while the store has a version of it:
    `chartbook restore` puts it back, and --remake builds without it.

    --upstream first builds and snapshots each pipeline this one depends
    on by path that has no snapshot to pin, as `chartbook run --upstream`
    does.

    \b
    Examples:
        chartbook build -f
        chartbook build -f --project-dir ../rate_forecast
        chartbook build -f --upstream
    """
    from chartbook import run as runner
    from chartbook.manifest import BUILD_SCRIPT

    project_dir = resolve_project_dir(site["project_dir"])
    if _is_catalog_folder(project_dir):
        # Every member's script would run before the render refused the
        # catalog: the render's gate comes first. A pipeline's own run is
        # gated in `run.run` before its render.
        _require_trust_to_render(project_dir, running=True)
    after_build = False
    if runner.running(project_dir, BUILD_SCRIPT):
        click.echo(
            click.style("Warning: ", fg="yellow", bold=True)
            + "`chartbook build` was called from this pipeline's own build script. "
            "It runs that script and then renders the site, so here it only "
            "renders the site. In a build script, say `chartbook docs generate`.",
            err=True,
        )
    elif _has_script(project_dir, BUILD_SCRIPT):
        _stop_where_a_build_tool_says_chartbook_build(project_dir, upstream=upstream)
        if _ask_before_running(project_dir, BUILD_SCRIPT, may_render=True, upstream=upstream) == "render":
            click.echo("The build command was not run; only the site is rendered.", err=True)
            _stop_on_a_cycle(project_dir)
        else:
            _run_script(
                project_dir, BUILD_SCRIPT, remake=remake, remake_command="chartbook build --remake", upstream=upstream
            )
            # So what the script did not make is an error, not "not built yet"
            after_build = True
    else:
        click.echo("No `build` script here, so only the site is rendered.")
        _stop_on_a_cycle(project_dir)
    _render_site(**site, after_build=after_build)


def _stop_on_a_cycle(project_dir):
    """Stop before rendering when a pipeline here depends, through what it depends on, on itself.

    Dependencies between pipelines form a directed acyclic graph, and
    `chartbook run` refuses a cycle before it pins or builds anything
    (:func:`chartbook.lineage.cycle`).
    Where `chartbook build` runs no build command, nothing has looked yet,
    so it looks here: at the pipeline, or at each pipeline of a catalog.
    """
    from chartbook import lineage
    from chartbook import run as runner
    from chartbook.snapshot import SnapshotError

    try:
        steps = runner.plan(project_dir, git=False)
    except (runner.RunError, ValueError, OSError):
        return  # the render says what is wrong
    members = {step.id: step.directory for step in steps if step.source == "asked" and step.directory is not None}
    shared: dict = {}  # the store read once for every pipeline's walk
    for step in steps:
        if step.source != "asked" or step.directory is None or not step.has_dependencies:
            continue
        try:
            loop = lineage.cycle(step.directory, pipeline=step.id, members=members, shared=shared)
        except (SnapshotError, ValueError, OSError):
            continue  # `chartbook check` says what is wrong with the manifest
        if loop is not None:
            click.echo(
                click.style("Error: ", fg="red", bold=True)
                + f"{step.id}: {lineage.cycle_lead(loop)}, so there is no order to build in.\n"
                + lineage.explain_cycle(loop)
                + "\nNothing was rendered.",
                err=True,
            )
            raise SystemExit(1)


def _stop_where_a_build_tool_says_chartbook_build(project_dir, upstream=False):
    """Stop before any build runs when a pipeline's build tool has a task that says `chartbook build`.

    Written when `chartbook build` rendered the site (before 0.2.0). Now it
    runs the build command first, which runs that task: under `chartbook
    build` the site is rendered twice, and under a plain `doit` the build
    runs inside itself. Each pipeline `chartbook build` would build is
    looked at, a catalog's members too, and all are named at once
    (:func:`chartbook.run.build_tool_runs_chartbook_build`).
    """
    from chartbook import run as runner
    from chartbook.manifest import BUILD_SCRIPT

    from chartbook.store import StoreError

    try:
        steps = runner.plan(project_dir, git=False, upstream=upstream)
    except (runner.RunError, ValueError, OSError, StoreError):
        return  # the run says what is wrong
    found = []
    for step in steps:
        command = step.scripts.get(BUILD_SCRIPT) if step.directory is not None and step.source in ("asked", "upstream") else None
        clash = runner.build_tool_runs_chartbook_build(step.directory, command) if command else None
        if clash is not None:
            name, number, line = clash
            where = name if step.directory == project_dir else str(step.directory / name)
            found.append(f"  {where}, line {number}: {line}")
    if not found:
        return
    click.echo(
        click.style("Error: ", fg="red", bold=True)
        + ("These lines run" if len(found) > 1 else "This line runs")
        + " `chartbook build`:\n"
        + "\n".join(found)
        + "\n`chartbook build` runs the build command first, and the build command runs that line: under "
        "`chartbook build` the site would be rendered twice, and under a plain build-tool run (`doit`) the "
        "build would run inside itself. Before 0.2.0 `chartbook build` rendered the site; now `chartbook docs "
        "generate -f` does. Say that there, or take the task out: `chartbook build` renders the site after "
        "the build command. Nothing was built.",
        err=True,
    )
    raise SystemExit(1)


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
    after_build=False,
):
    """Render the documentation site: what `docs` does, and `build` does last.

    :param output_dir: Directory where output will be generated.
    :param project_dir: Root directory of the project.
    :param publish_dir: Directory where files will be published.
    :param docs_build_dir: Directory where documentation will be built.
    :param temp_docs_src_dir: Temporary directory for documentation source files.
    :param keep_build_dirs: If True, keeps temporary build directory after generation.
    :param force_write: If True, overwrites existing output directory.
    :param size_threshold: File size in MB above which a dataframe page does not read the file for its date range.
    :param strict: If True, error and exit on missing source files. Only
        `--strict` typed on the command line makes a pipeline that has
        built nothing yet an error too.
    :param strip_mathjax2: If True, strip Plotly's MathJax 2 scripts from notebook outputs.
    :param incremental: If True, keep the build directory and redo only what changed.
    :param watch: If True, render incrementally and again on every change.
    :param watch_interval: Seconds between checks for changes in watch mode.
    :param after_build: The build script has just run, so a pipeline that
        has built nothing it declares is an error, not "not built yet".
    """
    from click.core import ParameterSource

    context = click.get_current_context(silent=True)
    asked = context is not None and context.get_parameter_source("strict") is ParameterSource.COMMANDLINE
    if strict and not asked:
        # The default, not asked for: generate_docs then leaves room for a
        # pipeline that has not been built yet
        strict = None

    # Validate paths for shell/platform mismatches
    from chartbook.path_validation import detect_shell_environment, validate_cli_paths

    shell_env = detect_shell_environment()
    path_args = [p for p in [output_dir, project_dir, publish_dir, docs_build_dir, temp_docs_src_dir] if p is not None]
    if path_args:
        validate_cli_paths(path_args, shell_env, auto_confirm=True)

    # Check for Sphinx dependencies
    _check_sphinx_installed()

    # The project, before anything is asked or written: with no manifest
    # there is nothing to render, as `chartbook build` says it
    project_dir = resolve_project_dir(project_dir)
    if not (project_dir / "chartbook.toml").is_file():
        click.echo(click.style("Error: ", fg="red", bold=True) + f"No chartbook.toml in {project_dir}.", err=True)
        raise SystemExit(1)
    # Before anything of the project is read: a folder the user has not
    # trusted is rendered as a build of files from a store is
    untrusted = _require_trust_to_render(project_dir)

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

    # Store whether we need to remove existing directory after successful generation
    should_remove_existing = output_dir.exists() and force_write

    with _untrusted_mode(untrusted):
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
            after_build=after_build,
        )
    if not watch:
        click.echo(f"Successfully generated documentation in {output_dir}")


# Asking to trust a folder, once, when a person is at a terminal
# (docs_src/design/trust.md, "Asked at a terminal")

#: What a person answered in this process, by folder: one command asks once
_trust_answers: dict = {}


def _stdin_is_a_terminal() -> bool:
    import sys

    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):  # closed (`<&-`), or not a file
        return False


def _can_ask() -> bool:
    """Whether a person is there to answer: stdin and stderr are terminals, and this is no build ChartBook runs, and no CI.

    A script, a pipe, CI and a command inside a build script ChartBook is
    running never see a question: they behave as before, refused with the
    command that trusts, or rendered as files from a store are.
    """
    import os

    from chartbook.config import untrusted_source
    from chartbook.resolve import batch
    from chartbook.run import RUN_DIR_ENV_VAR

    if os.environ.get("CI", "").strip() or batch() or os.environ.get(RUN_DIR_ENV_VAR) or untrusted_source():
        return False
    return _stdin_is_a_terminal() and _stderr_is_a_terminal()


def _shown_text(text, width: int = 160) -> str:
    """Text from a folder, as a question shows it: no control or format character, runs of space folded, cut at *width*.

    A manifest is anyone's: a build command padded with blank lines or
    spaces, or holding a right-to-left mark or a zero-width space, must not
    hide or reorder what the person is agreeing to.
    """
    import re
    import unicodedata

    shown = "".join(
        f"<U+{ord(c):04X}>" if unicodedata.category(c)[0] == "C" and c not in "\t" else c for c in str(text)
    )
    shown = re.sub(r"\s+", " ", shown).strip()
    return shown if len(shown) <= width else shown[: width - 1] + "…"


def _shown_command(command, at_most: int = 10) -> list:
    """A build command as a question shows it: its lines that say something, each shown plainly, ten at most."""
    lines = [_shown_text(line) for line in str(command).splitlines()]
    lines = [line for line in lines if line]
    if len(lines) > at_most:
        lines = lines[:at_most] + [f"… and {len(lines) - at_most} more line(s): the whole command is in its chartbook.toml"]
    return lines or ["(empty)"]


def _pipeline_id_here(folder):
    """The pipeline ID a folder's manifest gives itself, or None; for the question and the record, never for a decision."""
    from chartbook.identity import derive_pipeline_id
    from chartbook.manifest import _read_manifest_file

    try:
        raw = _read_manifest_file(folder)
        project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
        return derive_pipeline_id(project, folder)
    except Exception:  # noqa: BLE001 - the build says what is wrong with a manifest
        return None


def _described(folder, pipeline_id=None) -> str:
    """A folder as a question shows it: its path, then its pipeline ID and its repository, when it has them."""
    from chartbook.identity import get_git_remote_url, repository_key

    notes = [note for note in (pipeline_id or _pipeline_id_here(folder), repository_key(get_git_remote_url(folder))) if note]
    return _shown_text(folder, width=400) + (f"  ({', '.join(_shown_text(n, width=120) for n in notes)})" if notes else "")


def _record_trusted(folder, pipeline_id=None, catalog: bool = False) -> None:
    """Record a folder as the user's, at run, as `chartbook trust` there would (a catalog's own folder with no ID)."""
    from chartbook import config
    from chartbook.identity import get_git_remote_url, repository_key

    try:
        config.record_trust(
            folder, "run", id=None if catalog else (pipeline_id or _pipeline_id_here(folder)),
            repository=repository_key(get_git_remote_url(folder)) or None,
        )
    except (ValueError, OSError) as error:
        click.echo(
            click.style("Error: ", fg="red", bold=True) + f"could not record {_shown_text(folder, 400)} as trusted: "
            + _explain_os_error(error),
            err=True,
        )
        raise SystemExit(1)


_ANSWERS = {"y": "y", "yes": "y", "r": "r", "render": "r", "n": "n", "no": "n", "": "n"}


def _read_answer(prompt: str) -> str:
    """A line typed at the terminal, after *prompt*.

    Read in short waits rather than one blocking read: an interrupt that
    the system hands to another thread (polars runs its own) would otherwise
    not stop the read until Enter, and Ctrl-C must stop at once.

    :raises KeyboardInterrupt: On Ctrl-C.
    :raises EOFError: At the end of input.
    """
    import os
    import sys

    if os.name == "nt" or not _stdin_is_a_terminal():
        return click.prompt(prompt, default="", show_default=False, err=True, prompt_suffix=" ")
    import select

    click.echo(f"{prompt} ", nl=False, err=True)
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if ready:
            line = sys.stdin.readline()
            if line == "":
                raise EOFError
            return line.rstrip("\r\n")


def _ask(question: str, choices: str) -> str:
    """One answer among *choices* (``"yrn"`` or ``"yn"``). Enter, end of input and Ctrl-C are n; anything else is asked again."""
    shown = "/".join(choice.upper() if choice == "n" else choice for choice in choices)
    while True:
        try:
            answer = _read_answer(f"{question} [{shown}]:")
        except (click.Abort, EOFError, KeyboardInterrupt):
            click.echo("", err=True)
            return "n"
        letter = _ANSWERS.get(answer.strip().lower())
        if letter is not None and letter in choices:
            return letter
        click.echo(f"  Type {', '.join(choices[:-1])} or {choices[-1]}.", err=True)


def _build_command_of(folder):
    """The build command a folder's manifest declares, or None; shown in a question, never run from here."""
    from chartbook.manifest import BUILD_SCRIPT, _read_manifest_file, read_scripts

    try:
        return read_scripts(_read_manifest_file(folder)).get(BUILD_SCRIPT)
    except Exception:  # noqa: BLE001 - the build says what is wrong with a manifest
        return None


def _ask_to_trust_a_folder(folder, command=None, may_render=True, script="build") -> str:
    """Ask once whether a pipeline's folder is the user's: ``y`` (recorded at run), ``r`` (render only) or ``n``.

    A yes is trust at `run`, as `chartbook trust` records it: the question
    says so, and shows the build command a later `chartbook build` would
    then run without asking, even where only the site is rendered now.

    :param command: The command about to run (the *script*), shown in the
        question; None when only the site is to be rendered.
    :param may_render: Whether ``r`` is offered: rendering the site without
        running the folder's code.
    """
    from chartbook.config import trust_of

    key = Path(folder).resolve()
    if key in _trust_answers:
        return _trust_answers[key]
    if trust_of(key) == "render":
        lines = ["This folder is trusted to render its site, not to run its code:"]
    elif command:
        lines = ["ChartBook has not run the code in this folder before:"]
    else:
        lines = ["ChartBook has not rendered this folder before:"]
    lines.append(f"  {_described(key)}")
    if command:
        said = "Its build command" if script == "build" else f"Its {_shown_text(script, 40)!r} script"
        lines.append(f"{said} runs on this machine:")
        lines += [f"    {line}" for line in _shown_command(command)]
    else:
        lines.append("Rendering it as your own runs its manifest's SQL queries and reads the files it names, wherever they are.")
        later = _build_command_of(key)
        if later:
            lines.append("Trusting it also lets `chartbook build` run its build command, without asking:")
            lines += [f"    {line}" for line in _shown_command(later)]
    lines.append("  y  it's mine: trust this folder and the folders inside it, and don't ask again")
    if may_render:
        lines.append(
            "  r  render its site only, without running its code" if command
            else "  r  render it without its queries and without files from outside it"
        )
    lines.append("  n  stop")
    click.echo("\n".join(lines), err=True)
    answer = _ask("Trust this folder?", "yrn" if may_render else "yn")
    if answer == "y":
        _record_trusted(key)
        click.echo(
            f"Trusted: {_shown_text(key, 400)} (`chartbook trust --list` shows it; `chartbook trust --forget` there "
            f"takes it back)",
            err=True,
        )
    _trust_answers[key] = answer
    return answer


def _ask_to_trust_folders(folders: list, running: bool, script: str = "build") -> bool:
    """Ask once whether every listed folder is the user's, a catalog's; True when they are, and recorded at run.

    Each folder is shown with the build command a later `chartbook build`
    would run without asking, since a yes is trust at `run`.

    :param folders: ``(folder, pipeline ID or None, what it is)`` for each;
        what it is ``"the catalog's own folder"`` for the catalog's.
    :param running: Whether their scripts run now, said in the question.
    """
    lines = ["These folders are not trusted yet:"]
    for folder, pipeline_id, note in folders:
        lines.append(f"  {_described(folder, pipeline_id)}{f'  {note}' if note else ''}")
        command = _build_command_of(folder)
        if command:
            first, *rest = _shown_command(command, at_most=3)
            lines.append(f"      build: {first}")
            lines += [f"             {line}" for line in rest]
    what = "build scripts" if script == "build" else f"{_shown_text(script, 40)!r} scripts"
    lines.append(
        f"Building them as your own runs their {what} and their manifests' SQL queries, and reads the files they "
        f"name, wherever they are." if running else
        "Rendering them as your own runs their manifests' SQL queries and reads the files they name, wherever they "
        "are; trusting them also lets `chartbook build` run their build commands, without asking."
    )
    lines += ["  y  they're mine: trust them and the folders inside them, and don't ask again", "  n  stop"]
    click.echo("\n".join(lines), err=True)
    if _ask("Trust them?", "yn") != "y":
        return False
    for folder, pipeline_id, note in folders:
        _record_trusted(folder, pipeline_id, catalog=note == "the catalog's own folder")
        _trust_answers[Path(folder).resolve()] = "y"
    click.echo(f"Trusted: {len(folders)} folder(s) (`chartbook trust --list` shows them)", err=True)
    return True


def _ask_before_running(project_dir, script, may_render, upstream=False) -> str:
    """At a terminal, ask about each folder whose script would run and is not trusted to run: ``"go"`` or ``"render"``.

    ``"render"``, for `chartbook build` alone, is the answer r: the site is
    rendered without running the folder's code. ``n`` stops here. Where no
    one can be asked, nothing is asked, and the run refuses as it always
    did (:func:`chartbook.run._require_trust_to_run`).
    """
    from chartbook import run as runner
    from chartbook.config import trust_of

    if not _can_ask():
        return "go"
    from chartbook.store import StoreError

    try:
        steps = runner.plan(project_dir, git=False, upstream=upstream)
    except (runner.RunError, ValueError, OSError, StoreError):
        return "go"  # the run says what is wrong
    try:
        waiting = [
            step for step in steps
            if step.source in ("asked", "upstream") and step.directory is not None and script in step.scripts
            and trust_of(step.directory) != "run"
        ]
    except ValueError:
        return "go"  # a trust record that cannot be read: the run says so
    if not waiting:
        return "go"
    here = Path(project_dir).resolve()
    if len(waiting) == 1 and waiting[0].directory.resolve() == here:
        answer = _ask_to_trust_a_folder(here, waiting[0].scripts[script], may_render=may_render, script=script)
        if answer == "r":
            return "render"
        if answer == "n":
            click.echo("Nothing was run.", err=True)
            raise SystemExit(1)
        return "go"
    folders = [
        (step.directory, step.id, "an upstream: built, then snapshotted" if step.source == "upstream" else None)
        for step in waiting
    ]
    if not _ask_to_trust_folders(folders, running=True, script=script):
        click.echo("Nothing was run.", err=True)
        raise SystemExit(1)
    return "go"


def _require_trust_to_render(project_dir, running: bool = False) -> bool:
    """Whether a site is rendered as one from a store is, by how far the user trusts its folder (``docs_src/design/trust.md``).

    A pipeline folder with no trust is rendered as a build of files from a
    store is (:func:`_untrusted_mode` sets ``CHARTBOOK_UNTRUSTED_SOURCE=1``
    for the render, before anything of the folder is read), and the user
    is told why. A catalog's own folder and every member folder on this
    machine must be trusted at least to render, since the untrusted mode
    is the process's and cannot be one member's; one that is not is an
    error that lists them, and nothing is built.

    :returns: True to render as a build of files from a store.
    :raises SystemExit: For a catalog with a folder that is not trusted,
        or a trust record that cannot be read.
    """
    from chartbook.config import trust_of
    from chartbook.manifest import _read_manifest_file, catalog_member_dirs, resolve_project_type

    def fail(message):
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(message), err=True)
        raise SystemExit(1)

    try:
        raw = _read_manifest_file(project_dir)
        is_catalog = resolve_project_type(raw, source=str(project_dir / "chartbook.toml")) == "catalog"
    except (ValueError, FileNotFoundError):
        # A manifest that cannot be read is the build's error to say
        return False
    here = "here" if project_dir.resolve() == Path.cwd().resolve() else f"in {project_dir}"
    try:
        if not is_catalog:
            answered = _trust_answers.get(Path(project_dir).resolve())
            if trust_of(project_dir) is None and answered is None and _can_ask():
                answered = _ask_to_trust_a_folder(project_dir)
                if answered == "n":
                    click.echo("Nothing was rendered.", err=True)
                    raise SystemExit(1)
            if trust_of(project_dir) is None and answered == "r":
                click.echo(
                    click.style("Warning: ", fg="yellow", bold=True)
                    + "rendered as files from a store are, as you answered: no query is run, and no template or "
                    "file from outside the folder is read.",
                    err=True,
                )
                return True
            if trust_of(project_dir) is None:
                click.echo(
                    click.style("Warning: ", fg="yellow", bold=True)
                    + f"{project_dir} is not a pipeline you trust, so it is read as files from a store are: "
                    f"no query is run, and no template or file from outside the folder is read. If it is "
                    f"yours to run, `chartbook trust` {here} trusts it; `chartbook trust --render` trusts it "
                    f"to render only.",
                    err=True,
                )
                return True
            return False
        try:
            # The build reads the same entries next, and says what it warns of
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                members = catalog_member_dirs(project_dir)
        except (ValueError, FileNotFoundError, TypeError, KeyError):
            return False  # the build says what is wrong with the catalog
        untrusted = []
        if trust_of(project_dir) is None:
            untrusted.append(f"  {project_dir} (the catalog's own folder)")
        for pipeline_id, directory in members.items():
            if not (directory / "chartbook.toml").is_file():
                continue  # nothing to trust or read there; the build says the entry names no pipeline
            if trust_of(directory) is None:
                untrusted.append(f"  {directory} ({pipeline_id})")
    except ValueError as error:
        fail(error)
    # Building runs each member's script too: one question about every
    # folder this command needs, a member trusted to render only included
    wanted = (lambda level: level != "run") if running else (lambda level: level is None)
    if _can_ask() and (untrusted or (running and any(
        (d / "chartbook.toml").is_file() and wanted(trust_of(d)) for d in members.values()
    ))):
        folders = []
        if trust_of(project_dir) is None:
            folders.append((project_dir, None, "the catalog's own folder"))
        for pipeline_id, directory in members.items():
            if (directory / "chartbook.toml").is_file() and wanted(trust_of(directory)):
                folders.append((directory, pipeline_id, None))
        if _ask_to_trust_folders(folders, running=running):
            return False
        click.echo("Nothing was built.", err=True)
        raise SystemExit(1)
    if untrusted:
        fail(
            "a catalog's site is built only from folders you trust, and these are not trusted:\n"
            + "\n".join(untrusted)
            + f"\n`chartbook trust --members` {here} trusts the catalog's folder and each member folder on "
            f"this machine (`chartbook trust --members --render` to render only); `chartbook trust` in one "
            f"folder trusts that one."
        )
    return False


def _is_catalog_folder(project_dir) -> bool:
    """Whether the manifest in *project_dir* is a catalog's; False when there is none or it cannot be read."""
    from chartbook.manifest import _read_manifest_file, resolve_project_type

    try:
        raw = _read_manifest_file(project_dir)
        return resolve_project_type(raw, source=str(project_dir / "chartbook.toml")) == "catalog"
    except (ValueError, FileNotFoundError):
        return False


@contextlib.contextmanager
def _untrusted_mode(untrusted: bool):
    """``CHARTBOOK_UNTRUSTED_SOURCE=1`` for the render of a folder the user has not trusted, and only for it.

    The mode is read from the environment wherever a build decides what it
    may read or run (:func:`chartbook.config.untrusted_source`), so it is
    set there; and it is put back after, since the process may be a test's,
    or a library's, that renders again.
    """
    import os

    from chartbook.config import UNTRUSTED_ENV_VAR

    if not untrusted:
        yield
        return
    before = os.environ.get(UNTRUSTED_ENV_VAR)
    os.environ[UNTRUSTED_ENV_VAR] = "1"
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(UNTRUSTED_ENV_VAR, None)
        else:
            os.environ[UNTRUSTED_ENV_VAR] = before


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
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)

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
    # Publishing copies the files the manifest names: in a folder the user
    # has not trusted, as a build of files from a store, nothing outside it
    untrusted = _require_trust_to_render(project_dir)
    try:
        with _untrusted_mode(untrusted):
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
    except (ValueError, FileNotFoundError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)


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


def _as_named(path=None) -> Path:
    """A folder as the user named it, made absolute with its links kept; the current folder as the shell has it by default.

    For reading a catalog whose entries' paths were written from the
    folder as named through a link (:func:`chartbook.manifest.catalog_entry_dir`).
    The current folder is the shell's ``$PWD`` when that is it, since the
    one the system gives has every link followed.
    """
    import os

    if path is not None:
        return Path(os.path.abspath(path))
    here = Path.cwd()
    shell = os.environ.get("PWD", "")
    try:
        if shell and os.path.isabs(shell) and os.path.samefile(shell, here):
            return Path(shell)
    except OSError:
        pass
    return here


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

    Required fields come from the [policy] of the catalog or pipeline
    checked, or from --policy, which checks a pipeline against the catalog
    it is published to. With no policy anywhere, the default recommended
    fields are reported as warnings and do not fail the check.

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

    from chartbook.check import NOT_BUILT_YET, display_path, not_built_hint, read_policy, run_checks
    from chartbook.manifest import (
        _read_manifest_file,
        get_pipeline_ids,
        get_pipeline_manifest,
        load_manifest,
    )

    # A catalog is read from its folder as named too, links and all (_as_named)
    named_dir = _as_named(project_dir)
    project_dir = resolve_project_dir(project_dir)
    manifest_path = project_dir / "chartbook.toml"
    # An installed Claude Code skill written for an older ChartBook teaches
    # the wrong commands: said first, before anything can stop the check,
    # and it fails nothing
    try:
        from chartbook import claude_skill

        for copy in claude_skill.stale(project_dir):
            click.echo(f"warning: {claude_skill.notice(copy)}", err=True)
    except Exception:  # noqa: BLE001 - a note about the skill never stops a check
        pass
    try:
        # Manifest warnings (e.g. unknown [project] keys) belong in the
        # report, not in Python's warning format
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manifest = load_manifest(base_dir=named_dir)
        # A catalog's manifest always carries a resolved policy, so whether
        # one was written down is read from the file itself
        policy_given = "policy" in _read_manifest_file(project_dir)
        if policy_path is not None:
            # A catalog that sets no policy gives none: its default lists
            # are recommendations, as they are everywhere else
            manifest["policy"], policy_given = read_policy(policy_path)
            policy_label = f"the policy in {policy_path}"
        elif manifest["project"]["type"] == "catalog":
            policy_label = "the catalog policy"
        elif policy_given:
            policy_label = "the pipeline's policy"
        else:
            policy_label = "the default policy"
    except (ValueError, FileNotFoundError, TypeError, KeyError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
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
            policy_given=policy_given,
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
        if any(p.message.startswith(f"{NOT_BUILT_YET}:") for p in problems):
            click.echo(not_built_hint(manifest), err=True)
        _say_trust_level(manifest, project_dir)
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
    _say_trust_level(manifest, project_dir)


def _say_trust_level(manifest, project_dir):
    """One last line of `chartbook check`, when a build here would not run as the user's own.

    `check` reads and runs nothing, so it is not gated; it says the level
    the folder is trusted at (``docs_src/design/trust.md``) when that is
    not `run`, and the command that trusts it. For a catalog, the lowest
    level among its own folder and its member folders on this machine.
    """
    from chartbook.config import TRUST_LEVELS, trust_of
    from chartbook.manifest import get_pipeline_dirs

    try:
        folders = [project_dir]
        if manifest["project"]["type"] == "catalog":
            folders += list(get_pipeline_dirs(manifest).values())
        levels = [trust_of(folder) for folder in folders]
    except (ValueError, OSError):
        return  # the record is faulty: the build says so
    if all(level == "run" for level in levels):
        return
    lowest = None if None in levels else min(levels, key=TRUST_LEVELS.index)
    if manifest["project"]["type"] == "catalog":
        standing = "Not every folder of this catalog is trusted" + (" to run" if lowest == "render" else "")
        command = "`chartbook trust --members` here trusts the catalog's folder and each member folder on this machine"
    else:
        standing = "This pipeline is " + ("trusted to render, not to run" if lowest == "render" else "not trusted")
        command = "`chartbook trust` here trusts it"
    refused = "`chartbook build` and `chartbook run` refuse to run the build script"
    if lowest is None:
        refused += (
            ", and `chartbook docs generate` renders the site as one from a store is (no query run, no file from "
            "outside the folder)"
        )
    click.echo(f"{standing}: {refused}. {command}; `chartbook trust --list` shows what is trusted.")


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
    from chartbook.store import StoreError

    try:
        asset_path = resolve_path(
            ref, kind=kind, project_dir=project_dir or Path.cwd()
        )
    except (LookupError, FileNotFoundError, ValueError, TypeError, StoreError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
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
    help="Directory to write data_glimpses.md in, made if it does not exist "
    "(default: current directory)",
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

    The report is data_glimpses.md in --output-dir, which is made if it does
    not exist. An --output-dir ending in .md is the report's own path.

    Example usage:
        chartbook create-data-glimpses
        chartbook create-data-glimpses --no-samples
        chartbook create-data-glimpses --no-samples --no-stats
        chartbook create-data-glimpses -o ./docs/
        chartbook create-data-glimpses --size-threshold 100
    """
    from chartbook.create_data_glimpses import main as create_data_glimpses_main

    project_dir = resolve_project_dir(project_dir)
    # The report reads the files the manifest names: in a folder the user
    # has not trusted, as a build of files from a store, nothing outside it
    untrusted = _require_trust_to_render(project_dir)
    try:
        with _untrusted_mode(untrusted):
            create_data_glimpses_main(
                output_dir=output_dir,
                no_samples=no_samples,
                no_stats=no_stats,
                size_threshold=size_threshold,
                project_dir=project_dir,
            )
    except (FileNotFoundError, NotADirectoryError) as e:
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

    # Read from the folder as it was named, links and all, as well as the
    # folder itself: an entry's path written from the former still reads
    named = _as_named(catalog_path) if catalog_path is not None else resolved
    if named.is_dir():
        named = named / "chartbook.toml"
    try:
        manifest = load_manifest(base_dir=named.parent)
    except (ValueError, FileNotFoundError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
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
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(2)
    if as_json:
        click.echo(json.dumps(found.to_dict(), indent=2, default=str))
    else:
        click.echo(indexdiff.format_diff(found))
    if exit_code and not found.empty:
        raise SystemExit(1)


#: How `chartbook ls` shows a pipeline the catalog names with no folder here
STORE_ONLY = "(store only: not on this machine; the catalog shows its snapshots)"


def _from_the_store(manifest, kinds=("Dataframe", "Chart")):
    """The dataframes and charts of each pipeline a catalog names with no folder here, by pipeline ID.

    As the newest snapshot of each in the store lists them, each as
    ``(kind, ID, name)``; its name is plain text, as its owner wrote it.
    At most :data:`chartbook.snapshot.STORED_ASSETS_SHOWN` of each, with how
    many more there are. A store that cannot be read gives none.

    :returns: By pipeline ID, the assets listed and how many are not.
    """
    pipeline_ids = manifest.get("store_pipelines") or []
    if not pipeline_ids:
        return {}
    from chartbook import snapshot
    from chartbook.store import StoreError, default_store

    try:
        store = default_store()
        found, _ = snapshot.readable_snapshots(store)
    except (StoreError, OSError, ValueError):
        return {pipeline_id: ([], 0) for pipeline_id in pipeline_ids}
    listed = {}
    for pipeline_id in pipeline_ids:
        newest = max((t for t in found if t.pipeline == pipeline_id), key=lambda t: t.made_at, default=None)
        assets = snapshot.stored_assets(newest, store) if newest is not None else []
        shown = sorted((a for a in assets if a["kind"] in kinds), key=lambda a: (kinds.index(a["kind"]), a["id"]))
        rows = [(a["kind"], a["id"], a["name"] or "Unknown") for a in shown]
        listed[pipeline_id] = (rows[: snapshot.STORED_ASSETS_SHOWN], max(len(rows) - snapshot.STORED_ASSETS_SHOWN, 0))
    return listed


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
            stored = _from_the_store(manifest)
            for pipeline_id in sorted([*manifest["pipelines"], *(manifest.get("store_pipelines") or [])]):
                if pipeline_id not in manifest["pipelines"]:
                    click.echo(f"[pipeline] {pipeline_id}: {STORE_ONLY}")
                    rows, more = stored.get(pipeline_id, ([], 0))
                    for kind, asset_id, name in rows:
                        click.echo(f"  [{kind.lower()}] {asset_id}: {name}")
                    if more:
                        click.echo(f"  ... and {more} more")
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
                        click.echo(f"  [dataframe] {pipeline_id}:{df_id}: {df_name}")

                # List charts under this pipeline
                if "charts" in pipeline_manifest:
                    for chart_id in sorted(pipeline_manifest["charts"].keys()):
                        chart_name = pipeline_manifest["charts"][chart_id].get(
                            "name", "Unknown"
                        )
                        click.echo(f"  [chart] {pipeline_id}:chart/{chart_id}: {chart_name}")
        else:
            # Single pipeline
            pipeline_id = manifest["project"]["id"]
            pipeline_name = _get_pipeline_name(manifest)
            click.echo(f"[pipeline] {pipeline_id}: {pipeline_name}")

            if "dataframes" in manifest:
                for df_id in sorted(manifest["dataframes"].keys()):
                    df_name = manifest["dataframes"][df_id].get("name", "Unknown")
                    click.echo(f"  [dataframe] {pipeline_id}:{df_id}: {df_name}")

            if "charts" in manifest:
                for chart_id in sorted(manifest["charts"].keys()):
                    chart_name = manifest["charts"][chart_id].get("name", "Unknown")
                    click.echo(f"  [chart] {pipeline_id}:chart/{chart_id}: {chart_name}")


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
        stored = _from_the_store(manifest, ("Dataframe",))
        for pipeline_id in sorted([*manifest["pipelines"], *stored]):
            if pipeline_id not in manifest["pipelines"]:
                rows, more = stored[pipeline_id]
                for _, asset_id, name in rows:
                    click.echo(f"{asset_id}: {name}")
                if more:
                    click.echo(f"... and {more} more of {pipeline_id}")
                continue
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "dataframes" in pipeline_manifest:
                for df_id in sorted(pipeline_manifest["dataframes"].keys()):
                    df_name = pipeline_manifest["dataframes"][df_id].get(
                        "name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}:{df_id}: {df_name}")
    else:
        pipeline_id = manifest["project"]["id"]
        if "dataframes" in manifest:
            for df_id in sorted(manifest["dataframes"].keys()):
                df_name = manifest["dataframes"][df_id].get("name", "Unknown")
                click.echo(f"{pipeline_id}:{df_id}: {df_name}")


@ls.command("charts")
@click.pass_context
def ls_charts(ctx):
    """List all charts across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)

    if manifest["project"]["type"] == "catalog":
        stored = _from_the_store(manifest, ("Chart",))
        for pipeline_id in sorted([*manifest["pipelines"], *stored]):
            if pipeline_id not in manifest["pipelines"]:
                rows, more = stored[pipeline_id]
                for _, asset_id, name in rows:
                    click.echo(f"{asset_id}: {name}")
                if more:
                    click.echo(f"... and {more} more of {pipeline_id}")
                continue
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            if "charts" in pipeline_manifest:
                for chart_id in sorted(pipeline_manifest["charts"].keys()):
                    chart_name = pipeline_manifest["charts"][chart_id].get(
                        "name", "Unknown"
                    )
                    click.echo(f"{pipeline_id}:chart/{chart_id}: {chart_name}")
    else:
        pipeline_id = manifest["project"]["id"]
        if "charts" in manifest:
            for chart_id in sorted(manifest["charts"].keys()):
                chart_name = manifest["charts"][chart_id].get("name", "Unknown")
                click.echo(f"{pipeline_id}:chart/{chart_id}: {chart_name}")


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
    try:
        config_type = resolve_project_type(data, source=str(catalog_toml_path))
    except ValueError as error:  # a requirement this ChartBook does not meet, or a type it cannot tell
        raise click.ClickException(str(error)) from None
    if config_type != "catalog":
        raise click.UsageError(
            f"{catalog_toml_path} is not a catalog (type={config_type!r})"
        )
    data.setdefault("pipelines", {})
    return data


def _reenable(raw_catalog, key, entry=True) -> bool:
    """Enable a pipeline of the catalog again: its entry's ``disabled`` flag, and the ``disabled`` list.

    :param entry: Whether it has an entry of its own; one ``members`` finds is on the list only.
    :returns: Whether it was disabled.
    """
    listed_entry = raw_catalog["pipelines"].get(key) if entry else None
    flagged = isinstance(listed_entry, dict) and bool(listed_entry.pop("disabled", False))
    return _off_the_disabled_list(raw_catalog, key) or flagged


def _another_checkout(directory, listed, covered, checkouts):
    """The pipeline of the catalog that a folder is another checkout of: a worktree of its repository, or a second clone.

    :param listed: The folders the catalog's entries name, each with its key.
    :param covered: The folders ``members`` patterns match, each with its pattern.
    :param checkouts: Where each folder is in its repository, as looked up already; filled in.
    :returns: The other folder, its key in the catalog, and the pattern
        that found it (None for an entry); or None.
    """
    from chartbook.identity import checkout_of, derive_pipeline_id, same_pipeline_checked_out
    from chartbook.manifest import _read_manifest_file

    def where(folder):
        if folder not in checkouts:
            checkouts[folder] = checkout_of(folder)
        return checkouts[folder]

    mine = where(directory)
    if mine is None:
        return None
    for folder, key in listed.items():
        if folder != directory and same_pipeline_checked_out(where(folder), mine):
            return folder, key, None
    for folder, pattern in covered.items():
        if folder == directory or not (folder / "chartbook.toml").is_file():
            continue
        if same_pipeline_checked_out(where(folder), mine):
            try:
                project = _read_manifest_file(folder).get("project")
                key = derive_pipeline_id(project if isinstance(project, dict) else {}, folder)
            except (OSError, ValueError):
                continue
            return folder, key, pattern
    return None


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
    from chartbook.manifest import RESERVED_PIPELINES_KEYS, catalog_entry_dir, resolve_platform_path

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
        abs_path = catalog_entry_dir(catalog_dir, resolved)
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


@main.group(cls=_Catalog)
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
    # You made it: its folder is trusted to run, as a project `chartbook init` makes is
    if _record_trust_or_say(catalog_path.parent, "run"):
        click.echo(f"Trusted: {catalog_path.parent} (chartbook trust --list)")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  chartbook catalog add /path/to/pipeline   # add a pipeline")
    click.echo("  chartbook catalog generate                # render its site")
    click.echo("  chartbook catalog open                    # open it in the browser")


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

    # Resolve catalog. Its folder is taken with every link in its path
    # followed, as each pipeline's is below: a relative path is worked out
    # between the two as they really are, and read back the same way (a
    # home folder reached through a link, /var on macOS)
    catalog_toml = _resolve_catalog_toml_path(catalog_path)
    catalog_dir = catalog_toml.parent.resolve()
    raw_catalog = _load_raw_catalog(catalog_toml)

    # Get existing absolute paths for duplicate detection
    existing_abs = _get_existing_absolute_paths(raw_catalog, catalog_toml.parent)
    members_covered = _get_members_covered_paths(raw_catalog, catalog_dir)
    existing_keys = set(raw_catalog.get("pipelines", {}).keys())
    checkouts = {}  # where each folder looked at is in its repository
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

    # In one order, whatever order the filesystem gave the glob: a
    # repository's main worktree before one made with `git worktree add`,
    # so that of two checkouts of one pipeline the main one is the entry and
    # the other is said to be another checkout of it; then by path. Found by
    # CI, where the worktree came first on one filesystem and not another
    from chartbook.identity import checkout_of

    def where(folder):
        if folder not in checkouts:
            checkouts[folder] = checkout_of(folder)
        return checkouts[folder]

    candidate_dirs.sort(key=lambda d: (not (where(d) is None or where(d).main), str(d)))

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
            if _reenable(raw_catalog, key):
                reenabled += 1
                click.echo(f"  Re-enabled '{key}': {d.name}/")
            else:
                click.echo(
                    f"  Already in catalog as '{key}': {d.name}/"
                )
            continue

        # Another checkout of a pipeline the catalog has (a worktree, a
        # second clone) is that pipeline, whatever its key there
        other = _another_checkout(d, existing_abs, members_covered, checkouts)
        if other is not None:
            folder, key, pattern = other
            how = f"found by pipelines.members pattern '{pattern}', " if pattern else ""
            said = f"({how}another checkout of the same repository, {folder}): {d.name}/"
            if _reenable(raw_catalog, key, entry=pattern is None):
                reenabled += 1
                click.echo(f"  Re-enabled '{key}' {said}")
            else:
                click.echo(f"  Already in catalog as '{key}' {said}")
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
    from chartbook.identity import checkout_of, same_pipeline_checked_out

    # The folder each key names, listed already or added now: a second
    # checkout of one repository is that same pipeline, not another one
    folder_of = {key: folder for folder, key in existing_abs.items()}
    planned = []  # (directory, name, key, whether it fills in an entry from the store)
    for d, name, project_table in valid_pipelines:
        key = _derive_catalog_key(d, project_table)
        fills = key in from_the_store
        if fills:
            from_the_store.discard(key)
        elif key in folder_of and same_pipeline_checked_out(checkout_of(folder_of[key]), checkout_of(d)):
            click.echo(
                f"  Already in catalog as '{key}' (another checkout of the same repository, "
                f"{folder_of[key]}): {d.name}/"
            )
            continue
        else:
            key = _ensure_unique_key(key, existing_keys)
        existing_keys.add(key)
        folder_of.setdefault(key, d)
        planned.append((d, name, key, fills))

    if not planned:
        # Every one was another checkout of a pipeline already listed
        if reenabled:
            with open(catalog_toml, "wb") as f:
                tomli_w.dump(raw_catalog, f)
            click.echo("")
            click.echo(f"Re-enabled {reenabled} pipeline(s) in {catalog_toml}")
        else:
            click.echo("No new pipelines to add.")
        return

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
        # With / on every system, so a catalog file is read the same on each
        try:
            rel_path = Path(os.path.relpath(d, catalog_dir)).as_posix()
        except ValueError:
            # Cross-drive on Windows
            rel_path = Path(d).as_posix()

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
        # Adding a folder to your own catalog asks for it to be rendered
        # there: trusted to render, unless it is trusted already. To run
        # stays yours to say (`chartbook build` in a catalog runs every
        # member's script)
        if _trust_to_render_if_untrusted(d, key):
            click.echo(f"  Trusted to render: {d} (chartbook trust --list; `chartbook trust` there to run)")

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


@catalog.command("generate")
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
def catalog_generate(force_write, strict, clean, watch, watch_interval):
    """Render the global catalog's site, into docs/ beside its chartbook.toml.

    The catalog is the one ~/.chartbook/settings.toml names, or else
    ~/.chartbook/chartbook.toml. `chartbook catalog open` opens the site.

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

    click.echo(f"Generating the catalog's site from: {catalog_path}")
    click.echo(f"Output directory: {output_dir}")

    # As `chartbook docs generate` in the catalog's folder: every folder it
    # reads must be trusted. Before --clean, so that a refused build leaves
    # the kept tree. A settings file may point the catalog at a pipeline's
    # folder: that renders as `chartbook docs generate` there would, trusted
    # or not
    untrusted = _require_trust_to_render(project_dir)

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
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not incremental and watch:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + "--watch rebuilds with Sphinx; this catalog is built with MkDocs ([project] writer = \"mkdocs\"), "
            "whole, each time. Run it without --watch.",
            err=True,
        )
        raise SystemExit(1)
    with _untrusted_mode(untrusted):
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
    click.echo(f"Catalog site generated: {output_dir / 'index.html'}")
    click.echo("Run 'chartbook catalog open' to open it in your browser.")


@catalog.command("open")
def catalog_open():
    """Open the global catalog's site in your default browser."""

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
        click.echo("Run 'chartbook catalog generate' first.", err=True)
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
        # The command is in the working directory's pipeline: the calling file is this one
        path = get_data_path(pipeline, dataframe, catalog_path=catalog, project_dir=Path.cwd())
        click.echo(str(path))
    except CatalogNotConfiguredError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to set a default catalog.", err=True)
        raise SystemExit(1)
    except (LookupError, OSError, ValueError) as e:
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
            "unsynced": "not fully synced",
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
            elif event.status in ("passed_over", "unchecked", "id_changed"):
                click.echo(f"  {event.detail}.")

        for event in assets:
            if event.status == "moved":
                click.echo(f"  {event.asset}\n    {_short_hash(event.old)} -> {_short_hash(event.new)}")
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
                pinned_at = f" ({_short_hash(event.old)})" if event.old else ""
                click.echo(f"  lost: {event.asset}{pinned_at}: {event.detail}")
            elif event.status == "unsynced":
                click.echo(f"  not fully synced: {event.asset}: {event.detail}")
        if dependency in report.snapshots:
            taken = report.snapshots[dependency]
            made_in = f", which says it was made in {taken.repository}" if getattr(taken, "repository", "") else ""
            click.echo(
                f"  From its snapshot at {taken.commit[:7]}, made {_when(taken.made_at)}{made_in}."
            )
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


def _short_hash(content_hash):
    """A content hash as a person reads it in a line of output: its first twelve digits.

    ``sha256:4b1f9a0c2e3d…``, as a provenance panel and ``index diff`` show
    one. The lockfile keeps the whole hash.
    """
    if isinstance(content_hash, str) and len(content_hash) > 19:
        return content_hash[:19] + "…"
    return content_hash


def _run_pin(project_dir, dependencies=None, on_refused=None):
    """Run a pin, or an update when *dependencies* is given; exit 1 on a problem.

    :param on_refused: Called before exiting when the lockfile was not
        written because its new pins would close a cycle, or lead into one.
    """
    from chartbook import lock
    from chartbook.store import StoreError

    project_dir = resolve_project_dir(project_dir)
    try:
        if dependencies is None:
            report = lock.pin(project_dir)
        else:
            report = lock.update(project_dir, dependencies)
    except (lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    if report.refused:
        # Nothing was written, so what it would have pinned is not shown as pinned
        click.echo(click.style("Error: ", fg="red", bold=True) + report.refused, err=True)
        if on_refused is not None:
            on_refused()
        raise SystemExit(1)
    _echo_pin_report(report)
    if report.unrooted:
        click.echo(
            f"The store's note of this lockfile, for `store gc`, could not be written "
            f"({report.unrooted}); `store gc` goes by the note it has."
        )
    if report.problems:
        click.echo(
            f"\n{len(report.problems)} thing(s) could not be pinned.", err=True
        )
        raise SystemExit(1)


def _echo_frozen_report(step, report):
    """Print what `--frozen` found: one line when all is well, else each problem."""
    who = f"{step.id}: " if step is not None else ""
    if not report.problems and not report.dependencies:
        click.echo(f"{who}no dependencies to check. Nothing written.")
        return
    if report.unrooted:
        # Only the note for gc: the pins are as they were
        click.echo(
            f"{who}the store's note that this machine reads these pins could not be written "
            f"({report.unrooted}): `store gc` on another machine does not know of them.",
            err=True,
        )
    written = "Nothing written but the store's note that this machine reads these pins." if report.noted else "Nothing written."
    if not report.problems:
        click.echo(
            f"{who}{report.pins} pin(s) of {report.dependencies} dependenc"
            f"{'y' if report.dependencies == 1 else 'ies'}, all in the store. {written}"
        )
        return
    for problem in report.problems:
        where = problem.asset or problem.dependency
        click.echo(f"{who}{where + ': ' if where else ''}{problem.message}", err=True)
    click.echo(
        f"{who}{len(report.problems)} problem(s): the pipeline cannot be built from its "
        f"lockfile alone. {written}",
        err=True,
    )


@main.command()
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@click.option(
    "--frozen",
    is_flag=True,
    help="Write nothing but the store's note for gc: say whether the lockfile is complete and every pin is in the store",
)
def pin(project_dir, frozen):
    """Freeze what this pipeline depends on.

    Each pipeline in [dependencies] is pinned to a snapshot of it: what its
    owner declared ready, at a commit (`chartbook snapshot`). The content
    hash of each of its assets is written to chartbook.lock. Commit that
    file: a change to what the project depends on then shows in a diff.

    None of the other pipeline's data in its folder is read. It can be
    half-way through a change, and what you pin is still the build that
    was declared ready. Its chartbook.toml and chartbook.lock are read, to
    see that the pin makes no cycle: a pin whose new or moved entries would
    lead back to this pipeline, or into pipelines that depend on each
    other, is not written.

    A pin that already exists is never moved, whatever the other pipeline
    has done since; `chartbook update` moves pins. What `pin` does do again
    is pin a dependency that has no pin yet.

    A dependency that is a git repository is fetched, and pinned from a
    clean copy of the commit.

    --frozen pins nothing and writes nothing but, where the store can be
    written, its note that this machine reads these pins, so that `store
    gc` on another machine keeps them: not the lockfile, no object. It says
    whether the pipeline can be built from its lockfile alone, every
    dependency pinned and every pin in the store, and exits 1 if not. For
    CI, and for a store you may only read.

    \b
    Examples:
        chartbook pin
        chartbook pin --project-dir ../rate_forecast
        chartbook pin --frozen
    """
    if frozen:
        _run_frozen(project_dir)
        return
    _run_pin(project_dir)


def _said(error) -> str:
    """An error as it may be printed: with no password that a path or URL in it carried (``//user:pw@host``)."""
    from chartbook.config import without_credentials

    return without_credentials(str(error))


def _explain_os_error(error):
    """An OSError as a sentence: what a read-only store means, else the error."""
    from chartbook import lock
    from chartbook.store import ReadOnlyStoreError, default_store

    if isinstance(error, ReadOnlyStoreError):
        return _said(
            f"{error} This had to write it: a git dependency's first pin and a "
            f"snapshot both put files into the store. Do it where the store can be written; or, "
            f"if the store already has what the lockfile names, use --frozen."
        )
    if isinstance(error, OSError) and lock.is_read_only(error):
        try:
            the_store = default_store()
            root = str(getattr(the_store, "root", ""))
        except Exception:  # pragma: no cover - the store path is unreadable
            the_store, root = None, ""
        if root and str(getattr(error, "filename", "") or "").startswith(root):
            return _said(
                f"The store at {the_store} is read-only for you, and this had to write "
                f"it: a git dependency's first pin and a snapshot "
                f"both put files into the store. Do it where the store can be "
                f"written; or, if the store already has what the lockfile names, "
                f"use --frozen. ({error})"
            )
    return _said(error)


def _run_frozen(project_dir):
    """Say whether a pipeline can be built from its lockfile alone; exit 1 if not."""
    from chartbook import lock
    from chartbook.store import StoreError

    try:
        report = lock.verify(resolve_project_dir(project_dir), note=True)
    except (lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    _echo_frozen_report(None, report)
    if report.problems:
        raise SystemExit(1)
    # Built from its lockfile alone, as `chartbook run --frozen` would: not in a cycle
    from chartbook import lineage
    from chartbook.snapshot import SnapshotError

    from chartbook.snapshot import pipeline_in

    try:
        folder = resolve_project_dir(project_dir)
        loop, pipeline_id = lineage.cycle(folder), pipeline_in(folder)
    except (SnapshotError, ValueError, OSError):
        loop = None
    if loop is not None:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"{pipeline_id}: {lineage.cycle_lead(loop)}, so there is no order to build in.\n"
            + lineage.explain_cycle(loop),
            err=True,
        )
        raise SystemExit(1)


@main.command()
@click.argument("dependencies", nargs=-1)
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
def update(dependencies, project_dir):
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
    _run_pin(project_dir, dependencies=list(dependencies))


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
        # Before anything is written: a manifest for a newer ChartBook is not edited by this one
        from chartbook.manifest import _read_manifest_file, require_chartbook

        if manifest_file.is_file():
            require_chartbook(_read_manifest_file(project_dir), str(manifest_file))
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

    def put_back():
        # A dependency whose pin would close a cycle, or lead into one, is not added either
        with open(manifest_file, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        click.echo(f"{pipeline} was not added: {manifest_file} is as it was.", err=True)

    _run_pin(project_dir, on_refused=put_back)


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
    if node.kind == "no_snapshot":
        return f"{node.label}: its pin names no snapshot"
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
    help="Pin nothing and write nothing before the build but the store's note for gc; refuse unless every pin is in the store",
)
@click.option(
    "--remake",
    is_flag=True,
    help="Build even though an asset marked keep = true is not on disk while the store has a version of it, so that the build makes it again (`chartbook restore` puts it back instead)",
)
@click.option(
    "--upstream",
    is_flag=True,
    help="First build and snapshot each pipeline this one depends on by path that has no snapshot to pin, its own first; each must be trusted and committed",
)
def run_command(script, project_dir, force, make_snapshot, frozen, remake, upstream):
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

    It never builds in a folder this pipeline depends on, unless you say
    --upstream (below). That folder is somebody's work, and this pipeline
    reads what is pinned, not what is there.

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
        chartbook run --upstream

    --frozen pins nothing and writes nothing before the build but, where
    the store can be written, its note that this machine reads these pins:
    not the lockfile, no object, and no git dependency is fetched or built.
    The build runs only if the lockfile is complete and every pin is in
    the store (`chartbook pin --frozen` says the same without building).
    For CI, and for a store you may only read.

    An asset chartbook.toml marks `keep = true` cost something to make. If
    one is not on disk while the store has a version of it, `build` stops
    before anything runs and says so: `chartbook restore` puts it back,
    and --remake runs the build without it, which makes it again.

    --upstream is for folders that are yours. A pipeline this one depends
    on by path, on this machine, that has no snapshot to pin and is not
    pinned yet is built first, and snapshotted once its build succeeds, so
    that this one can pin it; its own the same way, each before what
    depends on it. Each must be trusted to run, have a `build` script and
    have everything committed, and its build must leave it so. The first
    that fails stops the run.
    """
    project_dir = resolve_project_dir(project_dir)
    from chartbook.manifest import BUILD_SCRIPT

    # Not for arguments the run refuses anyway: it says why, and nothing is recorded
    refused = (frozen and (make_snapshot or upstream)) or ((frozen or make_snapshot or upstream) and script != BUILD_SCRIPT)
    if not refused:
        _ask_before_running(project_dir, script, may_render=False, upstream=upstream)
    _run_script(
        project_dir,
        script,
        force=force,
        snapshot=make_snapshot,
        frozen=frozen,
        remake=remake,
        upstream=upstream,
    )


def _has_script(project_dir, script):
    """Whether a pipeline, or any pipeline of a catalog, has a script by this name."""
    from chartbook import run as runner

    try:
        steps = runner.plan(project_dir, git=False)
    except (runner.RunError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    return any(script in step.scripts for step in steps if step.source == "asked")


def _echo_snapshot(report, upstream=False):
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
    if report.made and upstream:
        click.echo("Snapshot made, for what depends on it in this run to pin.")
    elif report.made:
        click.echo(
            "Snapshot made. A pipeline that depends on this one gets it with "
            "`chartbook update`."
        )
    else:
        click.echo(
            f"Nothing has changed since the snapshot of {_when(taken.made_at)}. "
            f"No new one was made."
        )


def _run_script(
    project_dir, script, force=False, snapshot=False, frozen=False, remake=False, remake_command="chartbook run --remake",
    upstream=False,
):
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
            on_snapshot=lambda step, made: _echo_snapshot(made, upstream=step.snapshot_first),
            frozen=frozen,
            on_verify=_echo_frozen_report,
            remake=remake,
            remake_command=remake_command,
            upstream=upstream,
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


@main.command("restore")
@click.argument("names", nargs=-1)
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline (default: the current directory)")
def restore_command(names, project_dir):
    """Put this pipeline's own assets back on disk, from its snapshots in the store.

    With no NAMES, every asset chartbook.toml marks `keep = true` that is
    not on disk: a costly output, after a clean or in a fresh clone. Name
    assets to put those back, kept or not, as `chartbook path` names them:
    `embeddings`, `model/forecaster`, `chart/curve`.

    Each comes from the newest snapshot of this pipeline that holds it,
    with its bytes in the store, and is written at the path the manifest
    declares now; the command says which commit and date it came from.
    Nothing on disk is written over: an asset that is there is left, and
    said. This is the mirror of `chartbook snapshot`, which copies the
    folder into the store. Whether your build tool then skips the step
    that makes the asset is its own rule; the guide on keeping costly
    outputs has the recipe for doit.

    Exits 1 if an asset named could not be put back. With no NAMES, a kept
    asset that is missing and that no snapshot holds yet (a first build) is
    said, and the command exits 0, so that CI may run it before every
    build. The snapshots are found through the commits the clone has: a
    shallow clone (CI's `fetch-depth: 1`) sees none of them.

    \b
    Examples:
        chartbook restore
        chartbook restore embeddings
        chartbook restore model/forecaster chart/curve
    """
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError, default_store

    directory = resolve_project_dir(project_dir)
    try:
        report = snapshots.restore(directory, list(names) or None, default_store())
    except (snapshots.SnapshotError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    for name, path, taken, size in report.put_back:
        click.echo(
            f"{name}: put back at {path} from the snapshot at {taken.commit[:7]}, made {_when(taken.made_at)} "
            f"({_format_bytes(size)})"
        )
    for name, why in report.left:
        click.echo(f"{name}: not put back: {_printable(why)}", err=True)
    if not names and not report.put_back and not report.left:
        click.echo("Nothing to restore: nothing marked `keep = true` is missing from disk.")
    # Asked for by name and not put back: an error. Found missing on its own
    # and not put back (a first build, with no snapshot yet): said, and
    # nothing more, so that a CI step may run this before every build
    if names and report.left:
        raise SystemExit(1)


@main.group()
def store():
    """Look after the store: where pinned files and snapshots are kept.

    The store keeps files under the hash of what is in them. It is a folder
    on this machine, or one machines share (on a shared disk, or synced by
    a service such as Google Drive), or a bucket. It is ~/.chartbook/store
    unless CHARTBOOK_STORE, or [store] url in ~/.chartbook/settings.toml or
    in the organization's settings file (/etc/chartbook/settings.toml, or
    what CHARTBOOK_SYSTEM_SETTINGS names), says otherwise. `chartbook store
    info` says which it is.
    """


@store.command("info")
def store_info():
    """Say which store this machine uses, and what set it.

    The store is a setting of the machine, read in layers: CHARTBOOK_STORE,
    then [store] url in your settings file, then in the organization's,
    then the default. On a machine that is to share a store with another,
    this is what to check first.

    \b
    Examples:
        chartbook store info
        CHARTBOOK_STORE=/shared/store chartbook store info
    """
    from chartbook.config import (
        STORE_ENV_VAR,
        folder_of_store_url,
        get_cache_path,
        get_global_settings_path,
        get_store_setting,
        get_system_settings_path,
        shown_store_url,
        store_kind,
        without_credentials,
    )

    from chartbook.store import store_for_url

    try:
        url, origin = get_store_setting()
        kind = store_kind(url)
        folder = folder_of_store_url(url) if kind == "folder" else None
        # Never a user name or password, which a URL, its endpoint or a //host path may carry
        shown = shown_store_url(str(folder) if folder is not None else url)
        cache = get_cache_path()
    except ValueError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + without_credentials(str(e)), err=True)
        raise SystemExit(1)
    # The store of that kind, as the first pin or read would make it: a bucket
    # needs its library, and this is where to hear that it is missing, not then
    try:
        store_for_url(url)
        not_usable = None
    except ValueError as e:
        not_usable = e
    said_by = {
        "environment": f"set by {STORE_ENV_VAR}",
        "user": f"set by [store] url in {get_global_settings_path()}, your settings",
        "system": f"set by [store] url in {get_system_settings_path()}, the organization's settings",
        "default": f"the default: neither {STORE_ENV_VAR} nor a [store] url in a settings file says otherwise",
    }[origin]
    if folder is not None and not folder.exists():
        said_by += "; nothing is there yet"
    what = {"folder": "a folder", "s3": "an S3 bucket"}.get(kind, f"a {kind}:// store")
    click.echo(f"Store: {shown}")
    click.echo(f"  {what}, {said_by}")
    if not_usable is not None:
        click.echo(click.style("Error: ", fg="red", bold=True) + without_credentials(str(not_usable)), err=True)
        raise SystemExit(1)
    click.echo(f"Cache: {shown_store_url(str(cache))}")
    click.echo("  where what is read from a remote store is kept on this machine")
    _say_how_long_paths_are(folder)


def _say_how_long_paths_are(folder) -> None:
    """On Windows, say when the store's folder leaves its paths too little room (#136)."""
    from chartbook import store as stores

    if folder is None or not stores._ON_WINDOWS or stores.long_paths_enabled():
        return
    try:
        longest, made = stores.FolderStore(folder).longest_paths()
    except (stores.StoreError, OSError):
        return
    # Before any snapshot: an ID of 34 characters, and an ordinary file 30 deep in its pipeline
    expected = max(longest, made, len(str(folder)) + len("\\pipelines\\") + 34 + 33 + 30)
    if expected < stores.WINDOWS_PATH_LIMIT - 20:
        return
    click.echo(
        click.style("Warning: ", fg="yellow", bold=True)
        + f"the store's folder is {len(str(folder))} characters long, and its paths reach about {expected}: Windows "
        f"refuses a path of {stores.WINDOWS_PATH_LIMIT} or more on this machine, where long paths are not turned on. "
        f"{stores.LONG_PATHS_REMEDY}.",
        err=True,
    )


@store.command("migrate")
@click.option("--dry-run", is_flag=True, help="Say what would be moved, and move nothing")
@click.option("--yes", "-y", is_flag=True, help="Do not ask")
def store_migrate(dry_run, yes):
    """Move a store made by ChartBook 0.2 to the layout of 0.3.

    ChartBook 0.3 keeps a folder for each pipeline in the store, a folder
    for each snapshot in it named by when it was made and its commit, and
    each file once, under its own name. A store of 0.2 is refused until it
    is moved, once, on one machine.

    Upgrade every machine that uses the store to ChartBook 0.3 first: a
    machine still on 0.2 cannot read the store once it is moved, and says
    so. Then run this on one of them; in a store a sync service keeps, the
    others wait for the sync.

    Files are moved by renaming, so a store in a synced folder uploads
    nothing again; bytes two pipelines' snapshots share are copied for the
    second. The files of a glob, whose records give no hash for each file,
    are read once to hash them: in a folder that streams its files (Google
    Drive's), that downloads them. A migrate cut short is run again and
    goes on where it stopped. A store in a bucket is moved by syncing it to
    a folder (`aws s3 sync`), moving that, and syncing it back.

    \b
    Examples:
        chartbook store migrate --dry-run
        chartbook store migrate
    """
    from chartbook import migrate
    from chartbook.store import FolderStore, StoreError, default_store

    try:
        the_store = default_store()
    except (StoreError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not isinstance(the_store, FolderStore):
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"The store at {the_store} is not a folder. Sync it to one (`aws s3 sync`), set CHARTBOOK_STORE to "
            f"that folder, run this, and sync it back.",
            err=True,
        )
        raise SystemExit(1)
    try:
        plan = migrate.plan(the_store.root)
    except StoreError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not plan.needed:
        click.echo(f"The store at {the_store} has the layout of this version already: nothing to move.")
        return
    left = len(plan.records) - plan.done
    if plan.layout == "chartbook/store/v2" and not plan.unfinished:
        click.echo(f"The store at {the_store} says it has the layout of ChartBook 0.3, and holds 0.2's folders too.")
    elif not plan.unfinished:
        click.echo(f"The store at {the_store} has the layout of ChartBook 0.2.")
    if not plan.unfinished:
        click.echo(
            f"Would move {left} snapshot(s) of {len(plan.records)} into their pipelines' folders, from "
            f"{plan.objects} object(s), {_format_bytes(plan.size_bytes)}"
            + (f"; {plan.done} were moved by a migrate cut short" if plan.done else "")
            + "."
        )
    if plan.unowned:
        click.echo(f"{len(plan.unowned)} object(s) no snapshot names go to pipelines/+unowned/, until no lockfile names them.")
    if plan.shared:
        click.echo(f"{plan.shared} object(s) two pipelines' snapshots share are copied for the second.")
    if plan.to_read:
        click.echo(f"{_format_bytes(plan.to_read)} of globs and documents is read once, to hash each file.")
    if plan.lost:
        click.echo(f"{plan.lost} asset(s) the store had lost already, in 0.2, are named by their records still, as they were.")
    if plan.unfinished:
        click.echo(f"A migrate was cut short after it switched the store at {the_store}; what is left of the old layout is to go.")
    if dry_run:
        click.echo("Nothing was moved (--dry-run).")
        return
    if not yes and not click.confirm("Move it now? Every machine that uses this store must have ChartBook 0.3 first", default=False):
        click.echo("Nothing was moved.")
        return
    try:
        migrate.run(the_store.root, echo=click.echo)
    except (StoreError, OSError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        click.echo("What was moved stays moved: run this again to go on.", err=True)
        raise SystemExit(1)
    click.echo(f"Moved. The store at {the_store} has the layout of ChartBook 0.3; `chartbook store verify` checks it.")


def _folder_store_or_exit():
    """This machine's store, if it is a folder; else the command stops, saying so."""
    from chartbook.store import FolderStore, StoreError, default_store

    try:
        the_store = default_store()
    except (StoreError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not isinstance(the_store, FolderStore):
        click.echo(click.style("Error: ", fg="red", bold=True) + f"The store at {the_store} is not a folder: this works on a folder store.", err=True)
        raise SystemExit(1)
    return the_store


def _say_copied(done, verb: str) -> None:
    click.echo(f"{verb} {len(done.copied)} snapshot(s), {_format_bytes(done.size_bytes)} copied.")
    if done.there:
        click.echo(f"{len(done.there)} snapshot(s) were there already, and were left as they are.")
    for what, why in done.refused:
        click.echo(click.style("Refused: ", fg="red", bold=True) + f"{what}: {why}", err=True)
    if done.refused:
        raise SystemExit(1)


@store.command("export")
@click.argument("pipeline")
@click.option("--to", "to", required=True, type=click.Path(file_okay=False), help="The folder to write the export into")
@click.option("--latest", is_flag=True, help="Only the newest snapshot, every file it needs in its own folder")
@click.option("--snapshot", "snapshots", multiple=True, metavar="COMMIT[@MADE_AT]", help="Only this snapshot (more than one may be given)")
def store_export(pipeline, to, latest, snapshots):
    """Write one pipeline's snapshots into a folder, to send to someone.

    The folder is laid out as a store is: TO/pipelines/PIPELINE/, a folder
    for each snapshot, each file once, with its record. Send that folder;
    whoever receives it runs `chartbook store import` on it, or copies it
    into their store's pipelines/ by hand.

    Every snapshot its owner made is written, or with --latest the newest
    alone (one complete snapshot, readable without ChartBook), or each
    --snapshot named. Only what a snapshot's record names is written: its
    data, its documents and its index, never anything that runs.

    \b
    Examples:
        chartbook store export ftsfr/fed_yield_curve --to ~/Desktop/for-alice
        chartbook store export ftsfr/fed_yield_curve --latest --to ~/Desktop/for-alice
        chartbook store export ftsfr/fed_yield_curve --snapshot 4f2a91c --to ./out
    """
    from chartbook import sharing
    from chartbook.store import StoreError

    the_store = _folder_store_or_exit()
    if latest and snapshots:
        click.echo(click.style("Error: ", fg="red", bold=True) + "Give --latest or --snapshot, not both.", err=True)
        raise SystemExit(1)
    try:
        done = sharing.export(the_store, pipeline, to, "latest" if latest else list(snapshots) or None, echo=click.echo)
    except StoreError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    _say_copied(done, "Exported")
    click.echo(f"Send {Path(to).expanduser().resolve() / 'pipelines'}; `chartbook store import` there takes it in.")


@store.command("import")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def store_import(folder):
    """Copy the snapshots a folder holds into this machine's store.

    FOLDER is what `chartbook store export` wrote, a store, or one
    pipeline's folder from a store (its snapshots' folders, each with
    _chartbook/snapshot.json). Every file is hashed as it is copied and
    checked against its record: a snapshot with a file that is not what its
    record says is refused, and said. A file the store holds already is
    not copied again, a snapshot it has already is left as it is, and
    nothing in the store is written over. A pipeline in this store then
    pins the snapshots by the pipeline's ID, with `chartbook pin` and
    `chartbook update`.

    \b
    Examples:
        chartbook store import ~/Downloads/for-alice
        chartbook store import ~/Downloads/ftsfr+fed_yield_curve
    """
    from chartbook import sharing
    from chartbook.store import StoreError

    the_store = _folder_store_or_exit()
    try:
        done = sharing.import_snapshots(the_store, folder, echo=click.echo)
    except StoreError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    _say_copied(done, "Imported")


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
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
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


def _printable(text) -> str:
    """Text a store holds, as it may be printed: a control character (a line break, an escape) is a ``?``."""
    return "".join("?" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(text))


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
    help="Stop keeping the pins of a lockfile on this machine that cannot be found (another machine's are never forgotten from here)",
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

    A snapshot is kept if a lockfile pins it, if a lockfile pins a model
    version by its label and this is the newest snapshot holding that
    version, if it is the newest of its pipeline from its repository or the
    newest a branch or tag can pin from, if it says which repository the
    kept snapshots are of, if a label points at a model version in it (in
    that pipeline's chartbook.toml, or as its newest snapshot recorded), if
    it is the newest holding a version of an asset marked `keep = true`
    (every version of such an asset is kept, --aggressive or not, and the
    command says what the marks keep), or
    if it was made in the last 7 days (--keep-days). Otherwise it may be
    removed, and what only it named goes with it. A store keeps what work
    needs now, and lets old lineage go: with --keep-lineage, every snapshot
    a kept snapshot was made from is kept too, as far up as it goes, for
    `chartbook lineage` to check. With --aggressive, names keep nothing: a
    snapshot a git tag or branch names, or one holding a labelled model
    version that no lockfile pins, goes once nothing else keeps it.

    A lockfile that cannot be found, because its project was deleted or its
    drive is not plugged in, still keeps what it last pinned. Pass
    --forget-missing to let those go. A note only ever adds to what is kept:
    what a lockfile's note recorded at its last pin is kept even when the
    lockfile here says otherwise now. A note of a lockfile on another
    machine, which a store in a shared or synced folder has, is kept with
    --forget-missing or without, as is a note from before notes named their
    machine and a sync service's copy of a note; each is listed with its
    file under roots/, which you remove once no machine needs it. In your
    own store, under ~/.chartbook, a note from before notes named their
    machine is this machine's: its lockfile is read, and the note is
    removed once this machine has a note of that lockfile and the lockfile
    is read here, or with --forget-missing once the lockfile is gone.

    What would be removed is listed, and nothing is removed until you say
    yes. An object stored in the last hour is never removed: a pin puts
    files in the store before it writes the lockfile that names them. In a
    store users share, what another user put there may be theirs alone to
    remove: gc removes what it can, says what it removed, lists each thing
    it could not remove with what to do, and exits 1.

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
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        click.echo("Nothing was removed.", err=True)
        raise SystemExit(1)

    def carry_out() -> tuple[int, int]:
        """Remove what the plan says to, and say what could not be removed, if anything could not."""
        try:
            return lock.run_gc(plan, the_store)
        except lock.GcError as e:
            # Everything else went: say so, then each thing that stayed and what to do
            if e.removed_snapshots or e.removed:
                click.echo(f"Removed {e.removed_snapshots} snapshot(s) and {e.removed} object(s), {_format_bytes(e.size_bytes)}.")
            click.echo(click.style("Error: ", fg="red", bold=True) + f"{len(e.failures)} thing(s) could not be removed:", err=True)
            for _, why in e.failures:
                click.echo(f"  {_printable(_said(why))}", err=True)  # the store's words name the thing and say what to do
            if any(what.startswith("the snapshot") for what, _ in e.failures):
                click.echo("What a record that stayed names stays with it.", err=True)
            raise SystemExit(1)
        except (StoreError, lock.LockError, ValueError) as e:
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
            click.echo("Nothing was removed.", err=True)
            raise SystemExit(1)

    # A kept snapshot keeps objects too, which no lockfile may name
    named_by = f"{len(plan.lockfiles) + len(plan.elsewhere)} lockfile(s)" + (" or a kept snapshot" if plan.snapshots_kept else "")
    click.echo(f"Kept: {plan.kept} object(s), named by {named_by}")
    for lockfile, found in plan.lockfiles:
        if found:
            note = ""
        elif lockfile in plan.not_read:
            note = "  (not read: not a chartbook.lock on this machine; its pins are kept)"
        elif forget_missing:
            note = "  (not found; forgotten)"
        else:
            note = "  (not found; its pins are kept)"
        if lockfile in plan.forget_old:
            # In this user's own store: a note from before notes named their machine, this machine's
            from chartbook.store import root_name

            note += f"  (its note under no machine name goes: {the_store}/roots/{root_name(lockfile)})"
        click.echo(f"  {_printable(lockfile)}{note}")
    from chartbook.store import this_host

    here = this_host()
    for root in plan.elsewhere:
        # A note is written by whoever can write to the store: what it says is printed, never obeyed
        host = _printable(root.host)
        if root.copy:
            whose = "a sync service's copy of a note"
        elif not root.machine:
            whose = "noted under no machine name (before notes named their machine, or by a CI runner with none), so perhaps another machine's"
        elif root.host and root.host == here:
            # Not this machine's name now: an earlier one of its own, or another machine of the same host name
            whose = f"noted by {host} under another machine name than this one's now"
        else:
            whose = f"on another machine, {host}" if root.host else "on another machine"
        read = "; the lockfile here at that path is read as well" if root.lockfile in plan.read_here else ""
        click.echo(
            f"  {_printable(root.lockfile)}  ({whose}: what it recorded at its last pin is kept{read}; "
            f"note {the_store}/roots/{_printable(root.note)})"
        )
    if plan.snapshots_kept:
        reasons = {}
        for _, why in plan.snapshots_kept:
            reasons[why] = reasons.get(why, 0) + 1
        said = ", ".join(f"{count} because {why}" for why, count in reasons.items())
        click.echo(
            f"Kept: {len(plan.snapshots_kept)} snapshot(s), naming {plan.snapshots} "
            f"object(s): {said}"
        )
    if plan.kept_versions:
        # What the marks keep, asset by asset: the bill for `keep = true`
        by_asset: dict = {}
        for kept in plan.kept_versions:
            entry = by_asset.setdefault((kept.pipeline, kept.name), {"versions": {}, "snapshots": set()})
            entry["versions"].setdefault(kept.content_hash, kept.size_bytes)
            entry["snapshots"].add(kept.snapshot.path)
        for (pipeline, name), entry in sorted(by_asset.items()):
            click.echo(
                f"Kept for `keep = true`: {len(entry['versions'])} version(s) of "
                f"{_printable(pipeline)}:{_printable(name)}, {_format_bytes(sum(entry['versions'].values()))}, "
                f"in {len(entry['snapshots'])} snapshot(s)"
            )
    if plan.recent:
        click.echo(
            f"Kept: {len(plan.recent)} object(s) nothing names, stored in the last hour"
        )

    if any(not found for _, found in plan.lockfiles) and any(
        "cannot be found" in why for _, why in plan.snapshots_kept
    ):
        click.echo(
            "  A lockfile that cannot be found keeps the snapshots its note recorded "
            "(for a note from before notes did, the newest holding each object it "
            "named). --forget-missing lets them go."
        )

    if not plan.delete and not plan.snapshots_delete:
        click.echo("Nothing to remove.")
        if not dry_run:
            carry_out()  # forgets the missing, if asked to
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
    removed_snapshots, removed = carry_out()
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

    The template is the one that came with this ChartBook (the `template/`
    folder of ChartBook's repository, which the package carries), so the
    two always match, and rendering it needs no network. When the commit
    the template is at is known, the new project's `.cruft.json` names the
    template on GitHub and that commit, so `cruft update` there brings in
    later changes to it; when it is not, there is no `.cruft.json`, and the
    command prints the `cruft link` that makes one.

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
        import cookiecutter  # noqa: F401
    except ImportError:
        click.echo("Error: cookiecutter is not installed.", err=True)
        click.echo("", err=True)
        click.echo(
            "cookiecutter ships with chartbook, so this usually means a broken or"
            " partial installation. Reinstall with:", err=True
        )
        click.echo("    pip install --force-reinstall chartbook", err=True)
        raise SystemExit(1)

    from chartbook import scaffold

    if public is not None and not use_github:
        raise click.UsageError("--public/--private only applies with --github.")
    use_git = use_git or use_github
    cwd = Path.cwd()

    def fail(error):
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)
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

    # The template that came with this ChartBook, rendered here: no network
    from cookiecutter.exceptions import CookiecutterException

    try:
        rendered = scaffold.render(cwd)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except scaffold.ScaffoldError as e:
        # A source checkout git cannot read, or a project folder there already
        fail(e)
    except CookiecutterException as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + str(e), err=True)
        # The template's own message is above; its advice is said again
        # last, where it is seen. The name made from the project's name may
        # be refused too ("2024 Rates")
        click.echo(
            "If the folder name was refused, run `chartbook init` again and, at the second "
            "question, press Enter, or type a name of lowercase letters, digits and `_`.",
            err=True,
        )
        raise SystemExit(1)
    project_dir = rendered.project_dir
    # You made it: a build of it runs as your own, as `chartbook trust` would say
    if _trust_new_project(project_dir):
        click.echo("  Trusted: this folder (chartbook trust --list)")
    if rendered.commit is None:
        # A .cruft.json naming no commit is one cruft takes for up to date, and never updates
        click.echo(
            f"Note: this ChartBook cannot name the commit of {scaffold.TEMPLATE_REPOSITORY} its "
            f"template is at ({rendered.why}), so {project_dir.name} has no {scaffold.CRUFT_MARKER}, "
            f"and cruft cannot update it yet. Once you know the commit, run this in "
            f"{project_dir.name}, with the commit in place of <commit>; it gives cruft the answers "
            f"you gave here:\n"
            f"    {rendered.link_command()}",
            err=True,
        )
    elif rendered.pushed is False:
        click.echo(
            f"Note: the template's commit, {rendered.commit[:12]}, is on no branch of a remote that is "
            f"{scaffold.TEMPLATE_REPOSITORY}, and in no tag, of the checkout this ChartBook runs from, "
            f"so it may not be on GitHub, where `cruft update` looks for it. Push it before you run "
            f"`cruft update`.",
            err=True,
        )

    if not use_git:
        return

    try:
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
        from chartbook.identity import clear_git_remote_cache, derive_pipeline_id, get_git_remote_url, repository_key

        clear_git_remote_cache()
        click.echo(f"Pipeline ID: {derive_pipeline_id(_project_table(project_dir), project_dir)}")
        # ...and so does the trust record's note of it, and of its repository
        _trust_new_project(project_dir, repository=repository_key(get_git_remote_url(project_dir)) or None)


def _project_table(project_dir) -> dict:
    """The raw ``[project]`` table of a folder's chartbook.toml; ``{}`` with none."""
    import tomli

    manifest_path = project_dir / "chartbook.toml"
    if not manifest_path.is_file():
        return {}
    with open(manifest_path, "rb") as f:
        return tomli.load(f).get("project", {})


def _trust_new_project(project_dir, repository=None) -> bool:
    """Record a project `chartbook init` just made as trusted to run; say so if that cannot be done.

    :returns: Whether the record was written.
    """
    from chartbook.identity import derive_pipeline_id

    return _record_trust_or_say(
        project_dir, "run", id=derive_pipeline_id(_project_table(project_dir), project_dir), repository=repository
    )


def _record_trust_or_say(folder, level, id=None, repository=None) -> bool:
    """Record a folder the user made or added as trusted, or say in one line why that could not be done and go on.

    For `init`, `catalog init` and `catalog add`: the command's own work
    is done, and a record that cannot be written (no home folder) is not a
    reason to undo it.

    :returns: Whether the record was written.
    """
    from chartbook.config import record_trust

    try:
        record_trust(folder, level, id=id, repository=repository)
    except (OSError, RuntimeError, ValueError) as error:
        click.echo(
            f"Note: {folder} could not be recorded as trusted ({_said(error)}), so a build of it runs "
            f"as one from a store does until `chartbook trust` in that folder records it.",
            err=True,
        )
        return False
    return True


def _trust_to_render_if_untrusted(folder, pipeline_id) -> bool:
    """Record a folder `catalog add` is adding as trusted to render, unless it is trusted already.

    A folder already trusted, to render or to run, keeps its level: a
    record at `render` would take `run` away from a project the user made.

    :returns: Whether a record was written.
    """
    from chartbook.config import recorded_trust
    from chartbook.identity import get_git_remote_url, repository_key

    try:
        # The record alone: CHARTBOOK_TRUST=all or CI would say "run" today
        # and leave the folder untrusted when they are gone
        if recorded_trust(folder) is not None:
            return False
    except ValueError as error:
        click.echo(f"Note: {_said(error)} The folder's trust was left as it is.", err=True)
        return False
    return _record_trust_or_say(folder, "render", id=pipeline_id, repository=repository_key(get_git_remote_url(folder)) or None)


@main.command()
@click.argument("path", type=click.Path(), required=False)
@click.option(
    "--render",
    "render_only",
    is_flag=True,
    default=False,
    help="Trust it to render only: queries run and the files its manifest names are read, and its build script is not run",
)
@click.option(
    "--repository",
    is_flag=True,
    default=False,
    help="Trust the folder's origin repository instead of the folder: every clone of it, wherever it is",
)
@click.option(
    "--members",
    is_flag=True,
    default=False,
    help="In a catalog: trust the catalog's folder and each member folder on this machine",
)
@click.option("--list", "list_", is_flag=True, default=False, help="Show what is trusted, and how")
@click.option(
    "--forget",
    is_flag=True,
    default=False,
    help="No longer trust the folder (or, with --repository, its repository)",
)
def trust(path, render_only, repository, members, list_, forget):
    """Trust a pipeline's folder, so that a build of it runs as your own.

    A build of a folder you have not trusted runs as a build of files from
    a store does: `chartbook docs generate` renders its site with no query
    run and no template or file from outside the folder, and `chartbook build` and
    `chartbook run` refuse to run its build script, which is code. A
    project `chartbook init` made is trusted as it is made. One you cloned
    is trusted when you say so, here.

    With no PATH, this folder. A folder's trust covers the folders inside
    it, so `chartbook trust ~/GitRepositories/ftsfr` trusts every pipeline
    under it. --repository trusts the folder's origin repository instead:
    every clone of it, wherever it is. --members, in a catalog, trusts the
    catalog's folder and each of its member folders on this machine.

    Two levels. `run`, the default, lets the build script run. --render
    lets queries run and the files the manifest names be read, wherever
    they are, and no more. The record is ~/.chartbook/trust.toml, yours;
    --list shows it, and --forget takes a folder (or, with --repository,
    a repository) out of it. Under CI (the environment variable) the
    checkout is trusted to run without a record, and CHARTBOOK_TRUST=all
    trusts every folder.

    \b
    Examples:
        chartbook trust
        chartbook trust --render
        chartbook trust ../rates
        chartbook trust --repository
        chartbook trust --members
        chartbook trust --list
        chartbook trust --forget
    """
    import os

    from chartbook import config
    from chartbook.identity import derive_pipeline_id, get_git_remote_url, repository_key
    from chartbook.manifest import _read_manifest_file, catalog_member_dirs, resolve_project_type

    if list_ and (path or render_only or repository or members or forget):
        raise click.UsageError("--list shows what is trusted; it takes no PATH and no other option.")
    if forget and (render_only or members):
        raise click.UsageError("--forget takes a PATH, and --repository; a level or --members means nothing to it.")
    if repository and members:
        raise click.UsageError("--repository trusts one repository and --members a catalog's folders: one or the other.")

    def fail(message):
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(message), err=True)
        raise SystemExit(1)

    level = "render" if render_only else "run"
    verb = {"render": "Trusted to render", "run": "Trusted to run"}

    if list_:
        try:
            entries = config.read_trust()
        except ValueError as error:
            fail(error)
        mode = os.environ.get(config.TRUST_ENV_VAR, "").strip()
        if mode == "all":
            click.echo(f"{config.TRUST_ENV_VAR}=all: every folder is trusted to run, whatever the record says.")
        elif os.environ.get("CI", "").strip():
            click.echo(f"CI is set: {config._ci_checkout()} and the folders inside it are trusted to run.")
        pipelines = [entry for entry in entries if entry["kind"] == "pipeline"]
        repositories = [entry for entry in entries if entry["kind"] == "repository"]
        if not pipelines and not repositories:
            click.echo(
                f"Nothing is recorded in {config.get_trust_path()}. `chartbook trust` in a pipeline's folder "
                f"trusts it; a project `chartbook init` makes is recorded as it is made."
            )
            return
        click.echo(f"{config.get_trust_path()}:")
        if pipelines:
            click.echo("Pipelines (each covers the folders inside it):")
            for entry in pipelines:
                notes = [note for note in (entry["id"], entry["repository"]) if note]
                said = f"  {entry['level']:<7} {entry['path']}"
                if notes:
                    said += f"  ({', '.join(notes)})"
                if entry["since"]:
                    said += f"  since {entry['since']}"
                click.echo(said)
        if repositories:
            click.echo("Repositories (every clone whose origin remote is it):")
            for entry in repositories:
                said = f"  {entry['level']:<7} {entry['url']}"
                if entry["since"]:
                    said += f"  since {entry['since']}"
                click.echo(said)
        return

    folder = resolve_project_dir(path)
    # A folder that is gone can still be forgotten; trusting one needs it to be there
    if not folder.is_dir() and not (forget and not repository):
        fail(f"{folder} is not a folder.")
    manifest_path = folder / "chartbook.toml"

    if forget:
        try:
            if repository:
                remote = repository_key(get_git_remote_url(folder))
                if not remote:
                    fail(f"{folder} has no origin remote, so there is no repository to forget.")
                removed = config.forget_trust(url=remote)
                named = remote
            else:
                removed = config.forget_trust(path=folder)
                named = str(folder)
        except (ValueError, OSError) as error:
            fail(error)
        if removed:
            click.echo(f"No longer trusted: {named} ({removed} entr{'y' if removed == 1 else 'ies'} removed).")
        else:
            click.echo(f"Nothing was recorded for {named}; `chartbook trust --list` shows what is.")
        return

    if repository:
        remote = repository_key(get_git_remote_url(folder))
        if not remote:
            fail(
                f"{folder} has no origin remote, so there is no repository to trust. "
                f"`chartbook trust` trusts the folder itself."
            )
        try:
            config.record_repository_trust(remote, level)
        except (ValueError, OSError) as error:
            fail(error)
        click.echo(f"{verb[level]}: {remote} (every clone whose origin remote is it; this one is {folder})")
        return

    if members:
        try:
            member_dirs = catalog_member_dirs(folder)
        except FileNotFoundError:
            fail(f"No chartbook.toml in {folder}. --members is for a catalog's folder.")
        except ValueError as error:
            fail(f"{error} --members is for a catalog's folder; `chartbook trust` trusts a pipeline's.")
        # A folder with no pipeline in it is not recorded: whatever was put
        # there later would be trusted. Nothing is recorded until every
        # member can be, as `chartbook trust /nowhere` records nothing
        missing = [(pipeline_id, d) for pipeline_id, d in member_dirs.items() if not (d / "chartbook.toml").is_file()]
        if missing:
            fail(
                "these members of the catalog have no chartbook.toml where the catalog says they are, so nothing "
                "was recorded (a folder trusted now would trust whatever is put there later):\n"
                + "\n".join(f"  {d} ({pipeline_id})" for pipeline_id, d in missing)
                + "\nFix or remove their entries in the catalog's chartbook.toml, and run this again."
            )
        try:
            config.record_trust(folder, level, id=None, repository=repository_key(get_git_remote_url(folder)) or None)
            click.echo(f"{verb[level]}: {folder} (the catalog's folder)")
            for pipeline_id, directory in member_dirs.items():
                config.record_trust(
                    directory, level, id=pipeline_id, repository=repository_key(get_git_remote_url(directory)) or None
                )
                click.echo(f"{verb[level]}: {directory} ({pipeline_id})")
        except (ValueError, OSError) as error:
            fail(error)
        if not member_dirs:
            click.echo("The catalog has no member folder on this machine; what it shows from the store needs no trust.")
        return

    pipeline_id = None
    try:
        raw = _read_manifest_file(folder) if manifest_path.is_file() else None
        if raw is not None and resolve_project_type(raw, source=str(manifest_path)) == "pipeline":
            pipeline_id = derive_pipeline_id(raw.get("project") or {}, folder)
    except ValueError:
        raw = None  # a manifest that cannot be read is the build's to say; the folder is still trusted
    remote = repository_key(get_git_remote_url(folder)) or None
    try:
        config.record_trust(folder, level, id=pipeline_id, repository=remote)
    except (ValueError, OSError) as error:
        fail(error)
    notes = ", ".join(note for note in (pipeline_id, remote) if note)
    click.echo(f"{verb[level]}: {folder}" + (f" ({notes})" if notes else ""))
    if not manifest_path.is_file():
        click.echo(
            f"There is no chartbook.toml in {folder}, so this trusts every pipeline in the folders inside it."
        )
    elif raw is not None and pipeline_id is None:
        click.echo("That is a catalog's folder; `chartbook trust --members` trusts its member folders too.")


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


@main.group(cls=_Install)
def install():
    """Install bundled resources: user-level by default, or into the current directory with --project."""


@install.command("claude-skill")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite skill files changed by hand without prompting",
)
@click.option(
    "--project",
    is_flag=True,
    default=False,
    help="Install into ./.claude/skills/ in the current directory (commit it "
    "to share the skill with everyone working in the repo) instead of the "
    "user-level skills directory",
)
def install_claude_skill(force, project):
    """Install the Claude Code skill that comes with this ChartBook.

    By default the skill is installed user-level, into
    ~/.claude/skills/chartbook/, or $CLAUDE_CONFIG_DIR/skills/chartbook/ when
    that variable is set, so it is available in every Claude Code session.
    With --project it is installed into ./.claude/skills/chartbook/ in the
    current directory instead.

    The skill's SKILL.md names the ChartBook version it was written for. A
    copy for an older version is replaced, and the command says which
    version it replaced. A copy for a newer version, or for this version
    with files changed by hand, is replaced when you say so, or with
    --force. When the files already match, nothing is copied. Files of
    older layouts are removed, so the copy mirrors the bundled skill.

    Any other command, run at a terminal, says in one line when your copy or
    the project's is for an older ChartBook, and `chartbook check` warns.

    \b
    Examples:
        chartbook install claude-skill
        chartbook install claude-skill --project
    """
    import shutil

    from chartbook import claude_skill

    skill_files = claude_skill.bundled_files()
    if not skill_files:
        click.echo("Error: No bundled skill files found in package.", err=True)
        raise SystemExit(1)

    target_dir = Path.cwd() / ".claude" / "skills" / claude_skill.SKILL_NAME if project else claude_skill.user_dir()
    expected_names = {p.name for p in skill_files}

    def _visible_files():
        return [p for p in target_dir.iterdir() if p.is_file() and not p.name.startswith(".")]

    old_stamp = target_dir / claude_skill.OLD_STAMP
    existed = target_dir.is_dir() and (any(_visible_files()) or old_stamp.is_file())
    before = claude_skill._shown_version(target_dir) if existed else None
    standing = claude_skill.relation(target_dir) if existed else None
    shown = claude_skill.shown(target_dir)

    # Nothing to do: the installed files are the bundled ones. Hidden files
    # (.DS_Store, ...) do not count; an old stamp beside them goes
    if target_dir.is_dir():
        current = _visible_files()
        if {p.name for p in current} == expected_names and all(
            (target_dir / p.name).read_bytes() == p.read_bytes() for p in skill_files
        ):
            old_stamp.unlink(missing_ok=True)
            click.echo(f"Skill already up to date in {shown} (ChartBook {__version__})")
            return

    # A copy for an older version is an upgrade, and replaced; one for a
    # newer version, for this version but changed by hand, or naming none,
    # is asked about
    if existed and not force and (standing != "older" or before is None):
        if standing == "newer":
            click.echo(f"The skill in {shown} is for ChartBook {before}, newer than this one, {__version__}.")
        elif standing == "current":
            click.echo(f"The skill in {shown} is this version's, with files changed since it was installed.")
        else:
            click.echo(f"Skill files already exist in {shown}, naming no ChartBook version.")
        if not click.confirm(f"Replace them with ChartBook {__version__}'s?"):
            raise SystemExit(0)

    target_dir.mkdir(parents=True, exist_ok=True)

    # Drop files from older skill layouts (e.g. REFERENCE.md) so the
    # installed copy exactly mirrors the bundled skill
    for existing in _visible_files():
        if existing.name not in expected_names:
            existing.unlink()
            click.echo(f"  removed stale {existing.name}")
    old_stamp.unlink(missing_ok=True)

    for src_file in skill_files:
        shutil.copyfile(src_file, target_dir / src_file.name)
        click.echo(f"  {src_file.name}")

    if existed and before and standing != "current":
        click.echo(f"\nUpdated the skill in {shown} from ChartBook {before} to {__version__}")
    else:
        click.echo(f"\nInstalled {len(skill_files)} skill file(s) to {shown} (ChartBook {__version__})")

if __name__ == "__main__":
    main()
