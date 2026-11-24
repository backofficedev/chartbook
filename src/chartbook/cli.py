from __future__ import annotations

import codecs
import contextlib
import sys
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
    ``chartbook docs build ./site -f``. Either is one usage error with
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


#: What everyone learns (``docs_src/design/one-command.md``): the words to type, and what each is
#: for, in the order a person meets them. `chartbook --help` shows these first; the Quickstart,
#: the README and the skill teach them first; a test holds each to a command there is.
TO_KNOW = (
    ("chartbook init", "Start a project from the template"),
    ("chartbook run", "Build this pipeline, pinning what it reads"),
    ("chartbook snapshot", "Make this build what other pipelines read"),
    ("chartbook pin --update", "Take newer snapshots of what this one reads"),
    ("chartbook catalog open", "Browse every snapshot in your stores"),
    ("chartbook install agents", "Teach your coding agent ChartBook"),
)


class _Main(_Group):
    renamed = {"browse": "docs open"}

    def invoke(self, ctx):
        """Run the command; a store that this version does not open (one in a bucket) is said in one line, by whichever command meets it."""
        from chartbook.store import StoreNotAvailableError

        try:
            return super().invoke(ctx)
        except StoreNotAvailableError as error:
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)
            raise SystemExit(1)

    def format_commands(self, ctx, formatter):
        """The commands everyone learns, as they are typed, and then the rest by name.

        A command that is all there under its own name above (`init`,
        `run`, `snapshot`) is not listed again; one that has more to it
        than the form above (`pin`, `catalog`, `install`) is.
        """
        with formatter.section("Start with these"):
            formatter.write_dl(list(TO_KNOW))
        said_whole = {words.split()[1] for words, _ in TO_KNOW if len(words.split()) == 2}
        more = [
            (name, command) for name in self.list_commands(ctx)
            if (command := self.get_command(ctx, name)) is not None and not command.hidden and name not in said_whole
        ]
        if more:
            # Each in one line, cut to what is left beside the longest name, as click lists commands
            limit = formatter.width - 6 - max(len(name) for name, _ in more)
            with formatter.section("More"):
                formatter.write_dl([(name, command.get_short_help_str(limit)) for name, command in more])

    def parse_args(self, ctx, args):
        if args and args[0] == "build" and not ctx.resilient_parsing:
            raise click.UsageError("`chartbook build` is gone. `chartbook run` runs the build script, which renders the site; `chartbook docs build` renders it alone.", ctx)
        if args and args[0] == "update" and not ctx.resilient_parsing:
            from chartbook import missing

            # Its help was asked for: that of the command it became, and not a command that moves every pin
            asked_for_help = any(word in ("--help", "-h") for word in args[1:])
            tried = ["chartbook", "pin", "--help"] if asked_for_help else ["chartbook", "pin", "--update", *args[1:]]
            raise click.UsageError(
                "`chartbook update` is gone: `chartbook pin --update`. It moves pins to the newest snapshot, all of "
                f"them or those of the dependencies named. Try: {missing.typed(tried)}",
                ctx,
            )
        if args and args[0] == "check" and not ctx.resilient_parsing:
            raise click.UsageError(
                "`chartbook check` is gone: `chartbook run --check`. It checks a pipeline without building it, with the "
                "same --within and --policy; an output that is not built is listed and is no problem, so --skip-outputs "
                "is gone too. `chartbook run` checks what it builds.",
                ctx,
            )
        return super().parse_args(ctx, args)


class _Docs(_Group):
    arguments_go_to = "build"
    renamed = {"generate": "build"}


class _Catalog(_Group):
    renamed = {"generate": "build", "browse": "open"}

    def parse_args(self, ctx, args):
        if args and args[0] == "add" and not ctx.resilient_parsing:
            raise click.UsageError(
                "`chartbook catalog add` is gone. Run `chartbook snapshot` in the pipeline's "
                "folder to add its snapshot to the catalog. To connect an existing store, "
                "use `chartbook store add NAME URL`.", ctx
            )
        return super().parse_args(ctx, args)


class _Install(_Group):
    renamed = {"skill": "claude-skill"}


class _Ls(_Group):
    """`chartbook ls` and each of its listings: a store that is not read is said plainly, with exit 1, by whichever of them meets it."""

    def invoke(self, ctx):
        from chartbook.store import StoreError

        try:
            return super().invoke(ctx)
        except (StoreError, ValueError, OSError) as error:  # a store this version does not read, or one with two layouts in it
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)
            raise SystemExit(1)


@click.group(cls=_Main)
@click.version_option(version=__version__)
@click.pass_context
def main(ctx):
    """ChartBook builds a pipeline, keeps what it built as a snapshot that other pipelines pin, and shows every snapshot in a catalog.

    Every command takes --help.
    """
    _utf8_output()
    # A warning from the settings or a manifest is one line for a person,
    # not Python's file, line and source line
    warnings.showwarning = _show_warning
    # A question about trust is asked once per command, never carried to the next one in this process
    _trust_answers.clear()
    from chartbook.multi_store import settings_warnings
    settings_warnings.clear()
    # `install` is what mends it. `run` says it for itself once it has read its options: `run --check`
    # says it as a warning of its own, whether or not at a terminal
    if not ctx.resilient_parsing and ctx.invoked_subcommand not in (None, "install", "run"):
        _say_if_the_skill_is_stale()
    if not ctx.resilient_parsing:
        _remove_old_views()


def _utf8_output(streams=None) -> None:
    """Write a pipe or a file in UTF-8, whatever the system's code page.

    On Windows, Python writes a console as UTF-16, but a pipe or a file in
    the ANSI code page (cp1252), which has no ``├──``, ``→`` or ``…``: a
    command that prints one, such as `chartbook lineage`, raised
    UnicodeEncodeError the moment its output was piped, which is how an
    agent always reads it. A console is left as it is.

    :param streams: The streams to set, by default stdout and stderr.
    """
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        try:
            if stream is None or stream.isatty() or codecs.lookup(stream.encoding or "ascii").name == "utf-8":
                continue
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, LookupError, OSError, ValueError):
            continue  # not a text stream that can be set (a test's runner, a closed stream): left as it is


def _remove_old_views() -> None:
    """Remove what ChartBook 0.4 gathered into this machine's cache for reading, once; this version reads files where the store keeps them.

    0.4 laid an asset whose files sit in several snapshot folders out
    together under ``cache/views/<hash>/``, and nothing removed the folder.
    The cache is disposable by definition, so the folder goes the first time
    a command finds it, and one line on stderr says so. A read-only file in
    it (Windows) goes too. Each asset's folder goes on its own: one a 0.4
    process is reading as this runs (Windows refuses to remove an open
    file) stays, the rest go, and the next command tries it again. Once
    nothing is left, a marker says it was done, so that a 0.4 install beside
    this one, which gathers again, is not undone under its feet on every
    command.

    Where ``[cache] path`` in the settings has moved the cache, 0.4 may
    have gathered into ``~/.chartbook/cache`` before it did, and nothing
    reads there now: its ``views/`` goes too. A cache that
    ``CHARTBOOK_CACHE`` moves for one process (a test, CI) leaves the
    default one alone.
    """
    import os

    from chartbook.config import CACHE_ENV_VAR, get_cache_path, get_global_config_dir

    try:
        cache = get_cache_path()
    except (ValueError, OSError):
        return
    _remove_old_views_in(cache)
    if os.environ.get(CACHE_ENV_VAR, "").strip():
        return
    former = get_global_config_dir() / "cache"
    if os.path.normcase(os.path.abspath(former)) != os.path.normcase(os.path.abspath(cache)):
        _remove_old_views_in(former, former=True)


def _remove_old_views_in(cache, former: bool = False) -> None:
    """Remove what ChartBook 0.4 gathered under one cache folder, as :func:`_remove_old_views` says.

    :param former: The default cache, which the settings have moved away
        from: its ``views/`` goes only when it holds nothing but what 0.4
        gathered, as a bucket's does.
    """
    import os

    from chartbook.store import OLD_VIEWS_DIR, OLD_VIEWS_REMOVED, _remove_tree

    marker = cache / OLD_VIEWS_REMOVED
    try:
        if not cache.is_dir() or marker.is_file():
            return  # nothing of 0.4's here, or seen to once already: a 0.4 install beside this one keeps its own
    except OSError:
        return
    leftovers = [cache / OLD_VIEWS_DIR] if not former or _only_gathered(cache / OLD_VIEWS_DIR) else []
    for depth in ("*", "*/*", "*/*/*", "*/*/*/*"):
        # A bucket's cache, laid out as a folder store: its views/ beside pipelines/, and holding only
        # what 0.4 gathered, never a pipeline or an asset of that name, or a bucket's prefix
        leftovers.extend(
            folder for folder in cache.glob(f"s3/{depth}/{OLD_VIEWS_DIR}")
            if "pipelines" not in folder.relative_to(cache).parts and _only_gathered(folder)
        )
    stayed = False
    for folder in leftovers:
        if not folder.is_dir() or folder.is_symlink():
            continue
        in_use = 0
        try:
            views = sorted(folder.iterdir())
        except OSError:
            stayed = True
            continue
        for view in views:
            try:
                if view.is_dir() and not view.is_symlink():
                    _remove_tree(view, own=True)
                else:
                    os.remove(view)
            except OSError:
                in_use += 1
        try:
            folder.rmdir()
        except OSError:
            pass
        if not os.path.lexists(folder):
            click.echo(
                f"Removed {folder}: ChartBook 0.4 gathered copies of data there for reading, and this version "
                f"reads files where the store keeps them.",
                err=True,
            )
        else:
            stayed = True
            click.echo(
                f"Not all of {folder} could be removed: {in_use} of what ChartBook 0.4 gathered there for reading "
                f"is in use, most likely by a 0.4 process reading it now. The next command removes it once that has finished.",
                err=True,
            )
    if stayed:
        return  # no marker yet: what stayed goes on a later command
    try:
        marker.write_text("ChartBook 0.5 removed what 0.4 gathered under views/ here, once.\n", encoding="utf-8", newline="\n")
    except OSError:
        pass


def _only_gathered(folder) -> bool:
    """Whether a folder holds nothing but what 0.4 gathered: one folder per asset, named by its hash, or one being made."""
    import re

    try:
        return all(re.fullmatch(r"\.?[0-9a-f]{64}(\.[0-9a-f]{12}\.(tmp|old))?", entry.name) for entry in folder.iterdir())
    except OSError:
        return False


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
        from chartbook import agents

        # And what other agents read of ChartBook in this project
        old = agents.stale()
        if old is not None:
            click.echo(click.style("Note: ", fg="yellow", bold=True) + agents.notice(*old), err=True)
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

    `docs build` renders it, and `build` renders it after running the
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
    """The documentation site: `build` renders it, `open` opens it.

    `chartbook docs build` renders the site from what the project has
    built and writes index.json beside it. `chartbook docs open` opens the
    rendered site in your browser. `chartbook run` runs the pipeline build script.
    The script can render the site as its final step.
    """


@docs.command("build")
@_site_options
def docs_generate(**site):
    """Render the documentation site, in OUTPUT_DIR (./docs by default).

    This renders the site and writes index.json beside it. It does not
    run the build script: `chartbook run` does that. A lone pipeline that has built none of
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
        chartbook docs build -f
        chartbook docs build -f --incremental
        chartbook docs build -f --watch
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
        click.echo("Run 'chartbook docs build' first.", err=True)
        raise SystemExit(1)

    import webbrowser

    url = index_path.as_uri()
    click.echo(f"Opening {index_path}")
    if not webbrowser.open(url):
        click.echo(f"Could not open browser. Open this URL manually: {url}")


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
    # there is nothing to render, as `chartbook docs build` says it
    project_dir = resolve_project_dir(project_dir)
    if not (project_dir / "chartbook.toml").is_file() and not (project_dir / "catalog.toml").is_file():
        click.echo(click.style("Error: ", fg="red", bold=True) + f"No chartbook.toml in {project_dir}.", err=True)
        raise SystemExit(1)
    # Before anything of the project is read: a folder the user has not
    # trusted is rendered as a build of files from a store is
    untrusted = False if (project_dir / "catalog.toml").is_file() else _require_trust_to_render(project_dir)

    # Convert output_dir and build dirs to Path (relative paths resolve against project_dir, matching `docs open`)
    output_dir = (project_dir / Path(output_dir)).resolve()
    docs_build_dir = (project_dir / Path(docs_build_dir)).resolve()
    temp_docs_src_dir = (project_dir / Path(temp_docs_src_dir)).resolve()
    if publish_dir is not None:
        publish_dir = (project_dir / Path(publish_dir)).resolve()

    # Prevent deleting the current working directory
    if output_dir == Path.cwd():
        raise click.UsageError(
            "Output directory cannot be the current directory '.' to prevent accidental project deletion"
        )

    if output_dir.exists() and not output_dir.is_dir():
        raise click.UsageError(
            f"Output path '{output_dir}' exists and is not a directory"
        )

    # Check if output directory exists and prompt for confirmation
    if output_dir.exists() and not force_write and any(output_dir.iterdir()):
        if not click.confirm(
            f"Directory '{output_dir}' already exists. Do you want to overwrite it?\n"
            "(add the -f/--force-write option to overwrite without prompting)",
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


def _let_ctrl_c_end_a_read() -> None:
    """Make a read at the terminal end at Ctrl-C, whatever a library loaded since has done to the signal."""
    import signal

    try:
        signal.siginterrupt(signal.SIGINT, True)
    except (AttributeError, ValueError, OSError):  # no such call on Windows; not the main thread
        pass


def _confirm(question: str, default: bool) -> bool:
    """Ask a yes-or-no question that comes after work has run, on stderr; `click.Abort` at Ctrl-C or the end of input.

    Two things a question asked first thing does not meet. A library
    loaded by then (polars) has installed a signal handler of its own in a
    way that restarts a read at the terminal, so Ctrl-C at the question
    did nothing until Enter: the read is made interruptible again. And a
    key pressed while a build ran, an Enter above all, would answer the
    question before it was shown: what was typed before is discarded.
    """
    import os

    _let_ctrl_c_end_a_read()
    try:
        if _stdin_is_a_terminal():
            if os.name == "nt":
                import msvcrt

                while msvcrt.kbhit():
                    msvcrt.getwch()
            else:
                import termios

                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except Exception:  # noqa: BLE001 - a terminal that cannot be flushed is asked all the same
        pass
    return click.confirm(question, default=default, err=True)


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
    says so, and shows the build command a later `chartbook run` would
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
            lines.append("Trusting it also lets `chartbook run` run its build command, without asking:")
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

    Each folder is shown with the build command a later `chartbook run`
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
        "are; trusting them also lets `chartbook run` run their build commands, without asking."
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

    ``"render"`` is the answer r when the caller allows rendering without
    running the folder's code. ``n`` stops here. Where no
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
    is told why. A catalog renders stored snapshots without consulting
    working folders or their trust records.

    :returns: True to render as a build of files from a store.
    :raises SystemExit: If the user declines to render.
    """
    from chartbook.config import trust_of
    if (Path(project_dir) / "catalog.toml").is_file():
        return False
    project_dir = Path(project_dir)
    here = "here" if project_dir.resolve() == Path.cwd().resolve() else f"in {project_dir}"
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
    from chartbook.store import StoreError

    if watch_interval is not None and not watch:
        raise click.UsageError("--watch-interval only applies with --watch.")

    def report(error):
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)

    if not watch:
        try:
            summary = generate_docs(incremental=incremental, **build_kwargs)
        except (ValueError, FileNotFoundError, StoreError) as e:
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
        except (ValueError, FileNotFoundError, StoreError) as e:
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
    untrusted = False if (project_dir / "catalog.toml").is_file() else _require_trust_to_render(project_dir)
    try:
        with _untrusted_mode(untrusted):
            manifest = load_manifest(base_dir=project_dir)
            pipeline_id = manifest["project"]["id"]

            if publish_dir is None:
                publish_dir = project_dir / Path("./_output/to_be_published")
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


def _check_pipeline(project_dir, within_days, policy_path):
    """What `chartbook run --check` does: check a pipeline's manifest and folder, and exit nonzero on any problem.

    Nothing is run, pinned or built, and no data file is opened but to read
    a parquet file's own description of its columns. Four things are
    reported, each naming the chartbook.toml and field to edit: fields the
    policy requires that are missing or empty; declared paths kept in the
    repository (a write-up, a note, the README) that point at no file;
    pipelines in [dependencies] that cannot be found where they are said
    to be, and training data they do not declare; and dataframe licenses
    that are expired, or expire within *within_days* days.

    An output that is not built is listed as "not built yet" and counted
    as no problem: a checkout that has not been built, as in CI, is no
    mistake, and `chartbook run` itself fails where its build did not
    write one.

    Required fields come from the [policy] of the pipeline, or from
    *policy_path*, which checks it against the catalog it is published to.
    With no policy anywhere, the default recommended fields are reported
    as warnings and do not fail the check.
    """
    import warnings

    from chartbook.check import display_path, not_built_hint, nothing_is_built, read_policy, run_checks
    from chartbook.manifest import (
        _read_manifest_file,
        _working_pipeline_ids,
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
        from chartbook import agents

        old = agents.stale(project_dir)
        if old is not None:
            click.echo(f"warning: {agents.notice(*old)}", err=True)
    except Exception:  # noqa: BLE001 - a note about the skill never stops a check
        pass
    from chartbook.store import StoreError

    try:
        # Manifest warnings (e.g. unknown [project] keys) belong in the
        # report, not in Python's warning format
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manifest = load_manifest(base_dir=named_dir)
            if manifest["project"]["type"] == "catalog":
                raise ValueError("Catalog member checks are gone. `chartbook run --check` checks a pipeline; the catalog Diagnostics page checks snapshot metadata.")
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
            from chartbook.config import get_default_catalog_path
            machine_catalog = get_default_catalog_path()
            if machine_catalog is not None:
                try:
                    manifest["policy"], policy_given = read_policy(machine_catalog)
                    policy_label = f"the policy in {machine_catalog}" if policy_given else "the default policy"
                except FileNotFoundError:
                    policy_label = "the default policy"
            else:
                policy_label = "the default policy"
    except (ValueError, FileNotFoundError, TypeError, KeyError, StoreError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)

    # The checks warn about what they could not look at
    not_built: list = []
    with warnings.catch_warnings(record=True) as unchecked:
        warnings.simplefilter("always")
        problems = run_checks(
            manifest,
            project_dir,
            within_days=within_days,
            policy_label=policy_label,
            policy_given=policy_given,
            not_built=not_built,
        )

    for warning in [*caught, *unchecked]:
        click.echo(f"warning: {warning.message}", err=True)

    for problem in problems:
        click.echo(problem.format(relative_to=Path.cwd()))
    # What a build is to write and has not: listed, and no problem. A checkout that has not been built is no
    # mistake. On stderr, as a warning is: what is on stdout is a problem to mend, or the line that says there is none
    for output in sorted(not_built, key=lambda found: (str(found.file), found.table, found.field)):
        click.echo(output.format(relative_to=Path.cwd()), err=True)
    outputs = (
        "" if not not_built
        else "1 output is not built yet" if len(not_built) == 1
        else f"{len(not_built)} outputs are not built yet"
    )

    if problems:
        files = len({p.file for p in problems})
        click.echo(
            f"\n{len(problems)} problem(s) found in {files} manifest(s)."
            + (f" {outputs}, which is no problem." if outputs else ""),
            err=True,
        )
        _say_trust_level(manifest, project_dir)
        raise SystemExit(1)

    pipelines = [
        get_pipeline_manifest(manifest, pid) for pid in _working_pipeline_ids(manifest)
    ]
    # Models, files and dependencies are counted only where there are some,
    # so that the line for a project without them reads as it always has
    sections = ["dataframes", "charts", "notebooks"]
    for optional in ("models", "files", "dependencies"):
        if any(p.get(optional) for p in pipelines):
            sections.append(optional)
    counts = ", ".join(
        f"{sum(len(p.get(section) or {}) for p in pipelines)} {'files assets' if section == 'files' else section}"
        for section in sections
    )
    shown = display_path(manifest_path, relative_to=Path.cwd())
    note = f"; {outputs}" if outputs else ""
    click.echo(f"{shown}: OK ({len(pipelines)} pipeline(s), {counts}{note})")
    if outputs and nothing_is_built(manifest, project_dir):
        # A project just made, a fresh clone: one line on what builds it
        click.echo(not_built_hint(manifest), err=True)
    _say_trust_level(manifest, project_dir)


def _say_trust_level(manifest, project_dir):
    """One last line of `chartbook run --check`, when a build here would not run as the user's own.

    The check reads and runs nothing, so it is not gated; it says the level
    the folder is trusted at (``docs_src/design/trust.md``) when that is
    not `run`, and the command that trusts it. A catalog never gets here:
    the check refuses one before, and a catalog's stores need no trust.
    """
    from chartbook.config import trust_of

    try:
        lowest = trust_of(project_dir)
    except (ValueError, OSError):
        return  # the record is faulty: the build says so
    if lowest == "run":
        return
    standing = "This pipeline is " + ("trusted to render, not to run" if lowest == "render" else "not trusted")
    command = "`chartbook trust` here trusts it"
    refused = "`chartbook run` refuses to run the build script"
    if lowest is None:
        refused += (
            ", and `chartbook docs build` renders the site as one from a store is (no query run, no file from "
            "outside the folder)"
        )
    # Beside the warnings: what the check puts on stdout is a problem to mend, or the line that says there is none
    click.echo(f"{standing}: {refused}. {command}; `chartbook trust --list` shows what is trusted.", err=True)


@main.command("path")
@click.argument("ref")
@click.option(
    "--kind",
    type=click.Choice(["dataframe", "chart", "notebook", "note", "model", "file"]),
    help="The kind of asset REF names, when REF does not say "
    "(default: dataframe). The same as writing KIND/REF.",
)
@click.option(
    "--project-dir",
    type=click.Path(),
    help="Where to look for the pipeline: its chartbook.toml is found by "
    "walking up from here (default: the current directory)",
)
@click.option(
    "--files",
    "list_files",
    is_flag=True,
    default=False,
    help="Print the asset's files, one per line, sorted: the file, a "
    "folder's files or a glob's matches",
)
def path_command(ref, kind, project_dir, list_files):
    """Print the path of an asset: this pipeline's, or a pinned copy of another's.

    REF names an asset declared in the enclosing chartbook.toml. A dataframe
    is named by its key alone; anything else has its kind in front:

    \b
        treasury_rates          [dataframes.treasury_rates]
        chart/yield_curve       [charts.yield_curve]
        notebook/analysis       [notebooks.analysis]
        note/methodology        [notes.methodology]
        model/rate_forecaster   [models.rate_forecaster]
        file/filings            [files.filings]

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
    pipeline's own directory. Run `chartbook pin` first. It is the pinned
    snapshot's own copy (for a `git` dependency, the copy in the newest
    snapshot of the pinned commit), and the path stays the same while that
    snapshot is in the store and whole. Where it is not, the newest
    snapshot of that pipeline that holds the asset whole is printed, and
    never another pipeline's copy. Another pipeline's folder or glob of
    files has no one path, since a store may keep each file once (a bucket
    does), a snapshot's files then sitting in other snapshots' folders:
    print them with --files.

    With --files, the asset's files are printed instead, one per line: the
    file, a folder's files, or a glob's matches, as
    `chartbook.assets.files()` gives them.

    Examples:
        chartbook path repo_public
        chartbook path chart/repo_rates
        chartbook path repo_rates --kind chart --project-dir ../yield_curve
        chartbook path fed_yield_curve:treasury_rates
        chartbook path file/filings --files
    """
    from chartbook.assets import files as resolve_files
    from chartbook.assets import path as resolve_path
    from chartbook.errors import NoSinglePathError
    from chartbook.store import StoreError

    resolver = resolve_files if list_files else resolve_path
    try:
        found = resolver(ref, kind=kind, project_dir=project_dir or Path.cwd())
    except NoSinglePathError as e:
        from chartbook.missing import _quoted

        click.echo(
            click.style("Error: ", fg="red", bold=True) + _said(e) + f" `chartbook path {_quoted(ref)} --files` prints them, one per line.",
            err=True,
        )
        raise SystemExit(1)
    except (LookupError, FileNotFoundError, ValueError, TypeError, StoreError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    # Nothing but the paths on stdout: this output gets captured
    for asset_path in found if list_files else [found]:
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
    untrusted = False if (project_dir / "catalog.toml").is_file() else _require_trust_to_render(project_dir)
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

    :param catalog_path: Optional path to catalog catalog.toml.
    :type catalog_path: str or Path, optional
    :returns: Tuple of (manifest, resolved_catalog_path).
    :rtype: tuple
    :raises SystemExit: If no catalog is configured.
    """
    from chartbook.manifest import load_manifest
    from chartbook.resolve import resolve_catalog_path as _resolve_catalog_path

    if catalog_path is None:
        _catalog_or_make_one()
    try:
        resolved = _resolve_catalog_path(catalog_path)
    except ValueError as error:  # the settings file that names the default catalog is faulty
        raise click.ClickException(str(error)) from None

    # Read from the folder as it was named, links and all, as well as the
    # folder itself: an entry's path written from the former still reads
    named = _as_named(catalog_path) if catalog_path is not None else resolved
    if named.is_dir():
        named = named / "catalog.toml"
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
STORE_ONLY = "(stored snapshots)"


def _newest_stored(manifest):
    """The newest snapshot of each pipeline a catalog names with no folder here, with the store it is read from.

    :returns: The store, and by pipeline ID its newest snapshot, None for
        one with none; a store that cannot be read gives None for each.
    """
    pipeline_ids = manifest.get("store_pipelines") or []
    if not pipeline_ids:
        return None, {}
    from chartbook import snapshot
    from chartbook.hubs import selected_snapshots
    from chartbook.store import StoreError, default_store

    try:
        store = manifest.get("stores") or default_store()
        found, _ = snapshot.readable_snapshots(store)
    except (StoreError, OSError, ValueError):
        return None, {pipeline_id: None for pipeline_id in pipeline_ids}
    newest = {}
    for pipeline_id in pipeline_ids:
        selected = selected_snapshots(found, pipeline_id, manifest.get("pipeline_notes", {}).get(pipeline_id, {}).get("repository"))
        newest[pipeline_id] = max(selected, key=lambda t: t.made_at, default=None)
    return store, newest


def _from_the_store(manifest, kinds=("Dataframe", "Chart")):
    """The dataframes and charts of each pipeline a catalog names with no folder here, by pipeline ID.

    As the newest snapshot of each in the store lists them, each as
    ``(kind, ID, name)``; its name is plain text, as its owner wrote it.
    At most :data:`chartbook.snapshot.STORED_ASSETS_SHOWN` of each, with how
    many more there are. A store that cannot be read gives none.

    :returns: By pipeline ID, the assets listed and how many are not.
    """
    from chartbook import snapshot

    store, newest = _newest_stored(manifest)
    listed = {}
    for pipeline_id, taken in newest.items():
        assets = snapshot.stored_assets(taken, store) if taken is not None else []
        shown = sorted((a for a in assets if a["kind"] in kinds), key=lambda a: (kinds.index(a["kind"]), a["id"]))
        rows = [(a["kind"], a["id"], a["name"] or "Unknown") for a in shown]
        listed[pipeline_id] = (rows[: snapshot.STORED_ASSETS_SHOWN], max(len(rows) - snapshot.STORED_ASSETS_SHOWN, 0))
    return listed


def _ls_records(manifest, kinds=None):
    """What `chartbook ls --json` prints: a record per pipeline and per asset, every kind, none left out.

    Each is ``{"kind", "id", "name", "description"}``, and an asset's also
    ``"pipeline"``; ``kind`` is ``pipeline`` or an asset's kind
    (``dataframe``, ``chart``, ``model``, ...), and ``id`` is what
    ``chartbook get-docs``, ``data.load`` and the index take. A pipeline
    known from the store alone is described by its newest snapshot's index,
    as its owner wrote it.

    :param kinds: Only records of these kinds; every kind if None.
    """
    from chartbook import snapshot
    from chartbook.identity import plain_line
    from chartbook.refs import KIND_TABLES, KINDS, parse_asset_ref

    records = []

    def declared(pipeline_id, pipeline_manifest):
        project = pipeline_manifest.get("project", {})
        records.append({
            "kind": "pipeline", "id": pipeline_id,
            "name": project.get("name", ""), "description": project.get("description", ""),
        })
        for kind in KINDS:
            for name in sorted(pipeline_manifest.get(KIND_TABLES[kind]) or {}):
                entry = pipeline_manifest[KIND_TABLES[kind]][name]
                local = name if kind == "dataframe" else f"{kind}/{name}"
                records.append({
                    "kind": kind, "id": f"{pipeline_id}:{local}", "pipeline": pipeline_id,
                    "name": entry.get("name", ""), "description": entry.get("description", ""),
                })

    if manifest["project"]["type"] == "catalog":
        store, newest = _newest_stored(manifest)
        for pipeline_id in sorted([*manifest["pipelines"], *newest]):
            if pipeline_id in manifest["pipelines"]:
                declared(pipeline_id, manifest["pipelines"][pipeline_id])
                continue
            taken = newest[pipeline_id]
            own = snapshot.stored_pipeline_record(taken, store) if taken is not None else {}
            records.append({
                "kind": "pipeline", "id": pipeline_id,
                "name": plain_line(own.get("name"), 200), "description": plain_line(own.get("description"), 2000),
            })
            for asset in snapshot.stored_assets(taken, store) if taken is not None else []:
                # stored_assets lists only IDs that parse, of the kind the record says
                records.append({**asset, "kind": parse_asset_ref(asset["id"]).kind, "pipeline": pipeline_id})
    else:
        declared(manifest["project"]["id"], manifest)
    return [record for record in records if kinds is None or record["kind"] in kinds]


def _echo_json(value):
    """Print a value as JSON, for a script or an agent."""
    import json

    click.echo(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _json_option(command):
    """`--json`, on `chartbook ls` and each of its listings."""
    return click.option("--json", "as_json", is_flag=True, help="Print the listing as JSON, for a script or an agent")(command)


@main.group(cls=_Ls, invoke_without_command=True)
@click.option("--catalog", type=click.Path(), help="Path to catalog.toml")
@_json_option
@click.pass_context
def ls(ctx, catalog, as_json):
    """List catalog objects (pipelines, dataframes, charts).

    Without a subcommand, lists all objects in a tree format.
    Use subcommands to list specific object types.

    With --json, a list of records, one per pipeline and per asset of every
    kind (models, files, notes and notebooks too): kind, id, name,
    description, and an asset's pipeline. The id is what `chartbook
    get-docs` and `data.load` take.

    \b
    Examples:
        chartbook ls
        chartbook ls pipelines
        chartbook ls dataframes
        chartbook ls charts
        chartbook ls --json
    """
    ctx.ensure_object(dict)
    ctx.obj["catalog"] = catalog
    ctx.obj["json"] = as_json

    if ctx.invoked_subcommand is None:
        manifest, catalog_path = _load_catalog_for_cli(catalog)
        if as_json:
            _echo_json(_ls_records(manifest))
            return
        # List everything in tree format
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
@_json_option
@click.pass_context
def ls_pipelines(ctx, as_json):
    """List all pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)
    if as_json or ctx.obj.get("json"):
        _echo_json(_ls_records(manifest, ("pipeline",)))
        return

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
@_json_option
@click.pass_context
def ls_dataframes(ctx, as_json):
    """List all dataframes across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)
    if as_json or ctx.obj.get("json"):
        _echo_json(_ls_records(manifest, ("dataframe",)))
        return

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
@_json_option
@click.pass_context
def ls_charts(ctx, as_json):
    """List all charts across pipelines."""
    catalog = ctx.obj.get("catalog")
    manifest, _ = _load_catalog_for_cli(catalog)
    if as_json or ctx.obj.get("json"):
        _echo_json(_ls_records(manifest, ("chart",)))
        return

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






def _load_raw_catalog(catalog_toml_path):
    """Load a catalog TOML file without full manifest processing.

    :param catalog_toml_path: Path to the catalog's catalog.toml.
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
        from chartbook.missing import _quoted

        raise click.UsageError(
            f"{catalog_toml_path} uses the old v1 format. "
            f"Run: python scripts/migrate_toml_v2.py {_quoted(catalog_toml_path.parent)}"
        )
    if catalog_toml_path.name == "catalog.toml":
        data.setdefault("project", {}).setdefault("type", "catalog")
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












def _catalog_or_make_one(required=True, to_show_a_snapshot=False):
    """The catalog this machine uses, made over its store if there is none yet.

    By default a store and a catalog are one unit, so the first command
    that needs the catalog makes it, `~/.chartbook/catalog.toml`, listing
    the machine's store and nothing else. At a terminal it asks first, and
    Enter says yes; a script, a pipe or CI gets it made and told so on
    stderr, since nothing is lost by making it. A catalog the settings
    name is used as it is.

    :param required: Whether the command cannot go on without one: a
        refusal then stops it with the commands that make or name one.
        Otherwise a refusal returns None.
    :param to_show_a_snapshot: Asked after a snapshot, which the catalog
        would show.
    :returns: The catalog's path; None when it was declined and not required.
    """
    path = _default_catalog_path()
    if path is not None:
        return path
    from chartbook.config import get_store_url, make_default_catalog, shown_store_url

    store = shown_store_url(get_store_url())
    if _can_ask():
        click.echo("No catalog yet" + (", to show it in." if to_show_a_snapshot else "."), err=True)
        try:
            agreed = _confirm(f"Create one over your store at {store}?", default=True)
        except click.Abort:  # Ctrl-C, or the end of input
            if not required:
                click.echo("", err=True)
                return None
            raise
        if not agreed:
            if not required:
                return None
            click.echo(
                "Run `chartbook catalog init` to make one, or `chartbook config` to point at one you have.",
                err=True,
            )
            raise SystemExit(1)
        path, _ = make_default_catalog()
        click.echo(f"Made {path}.", err=True)
        return path
    from chartbook.config import said_catalog_made

    path, made = make_default_catalog()
    if made:
        click.echo(said_catalog_made(path), err=True)
    return path


def _say_where_a_snapshot_shows():
    """After a snapshot, make the catalog that shows it if there is none yet (asking at a terminal), and say how to see it.

    The snapshot is made: nothing here fails the command. A catalog that
    cannot be read (an old one, wanting `catalog migrate`) is said, as a
    note.
    """
    try:
        if _default_catalog_path() is not None:
            return
        if _catalog_or_make_one(required=False, to_show_a_snapshot=True) is not None:
            click.echo("`chartbook catalog build` renders its site, and `chartbook catalog open` opens it.", err=True)
    except click.ClickException as error:
        click.echo(f"Note: no catalog to show it in: {error.format_message()}", err=True)
    except PermissionError:
        pass


def _resolve_catalog_toml_path(catalog_path):
    """Resolve the catalog TOML path from an option or global settings.

    :param catalog_path: Optional explicit path to catalog catalog.toml.
    :type catalog_path: str or Path, optional
    :returns: The resolved path to the catalog's catalog.toml.
    :rtype: Path
    :raises SystemExit: If no catalog is configured.
    """
    from chartbook.resolve import resolve_catalog_path as _resolve_catalog_path

    if catalog_path is None:
        _catalog_or_make_one()
    try:
        return _resolve_catalog_path(catalog_path)
    except ValueError as error:  # the settings file that names the default catalog is faulty
        raise click.ClickException(str(error)) from None


@main.group(cls=_Catalog)
def catalog():
    """Manage the chartbook catalog."""
    pass


@catalog.command("init")
@click.option("--title", default="My Catalog", show_default=True, help="The catalog site's title")
def catalog_init(title):
    """Make this machine's catalog, ~/.chartbook/catalog.toml, over its store.

    By default a store and a catalog are one unit: the first command that
    needs the catalog (`chartbook ls`, `catalog build`, a snapshot) makes
    this one for you. This makes it ahead of time, or with a title. A
    pipeline enters it when its owner runs `chartbook snapshot`; other
    stores join it with `chartbook store add`.
    """
    from chartbook.config import create_global_catalog, get_global_catalog_path, said_catalog_made

    # The settings may name one, and an old ~/.chartbook/chartbook.toml wants `catalog migrate`
    named = _default_catalog_path()
    if named is not None and named.is_file():
        click.echo(f"Global catalog already exists: {named}")
        return
    if get_global_catalog_path().is_file():
        click.echo(f"Global catalog already exists: {get_global_catalog_path()}")
        return

    catalog_path = create_global_catalog(title=title)
    click.echo(said_catalog_made(catalog_path))
    click.echo("`chartbook catalog build` renders its site, and `chartbook catalog open` opens it.")


def _set_pipeline_disabled(pipeline_id, catalog_path, disabled):
    """Set or clear the disabled flag on a pipeline in the catalog.

    :param pipeline_id: The pipeline key in the catalog.
    :type pipeline_id: str
    :param catalog_path: Optional explicit path to catalog catalog.toml.
    :type catalog_path: str or Path, optional
    :param disabled: Whether to disable (True) or enable (False) the pipeline.
    :type disabled: bool
    """
    import tomli_w

    from chartbook.manifest import RESERVED_PIPELINES_KEYS

    catalog_toml = _resolve_catalog_toml_path(catalog_path)
    try:
        _load_raw_catalog(catalog_toml)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    if catalog_toml.name == "catalog.toml":
        import tomlkit
        from chartbook.identity import validate_pipeline_id
        try:
            validate_pipeline_id(pipeline_id)
            document = tomlkit.parse(catalog_toml.read_text(encoding="utf-8"))
            if disabled:
                notes = document.setdefault("pipelines", tomlkit.table())
                if not isinstance(notes, dict):
                    raise ValueError(f"{catalog_toml}: [pipelines] must be a table.")
                note = notes.setdefault(pipeline_id, tomlkit.table())
                if not isinstance(note, dict):
                    raise ValueError(f"{catalog_toml}: [pipelines.{pipeline_id!r}] must be a table.")
                note["disabled"] = True
                catalog_toml.write_text(tomlkit.dumps(document), encoding="utf-8", newline="\n")
            else:
                notes = document.get("pipelines")
                if notes is not None and not isinstance(notes, dict):
                    raise ValueError(f"{catalog_toml}: [pipelines] must be a table.")
                if isinstance(notes, dict) and pipeline_id in notes:
                    note = notes[pipeline_id]
                    if not isinstance(note, dict):
                        raise ValueError(f"{catalog_toml}: [pipelines.{pipeline_id!r}] must be a table.")
                    if "disabled" in note:
                        note.pop("disabled", None)
                        catalog_toml.write_text(tomlkit.dumps(document), encoding="utf-8", newline="\n")
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None
        click.echo(f"{pipeline_id}: {'disabled' if disabled else 'enabled'} in {catalog_toml}")
        return

    raise click.ClickException(f"{catalog_toml} is an old catalog. Run `chartbook catalog migrate`.")


@catalog.command("disable")
@click.argument("pipeline_id")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(),
    default=None,
    help="Path to catalog.toml (uses default from settings if omitted)",
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
    help="Path to catalog.toml (uses default from settings if omitted)",
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
@click.option("--gc", "run_gc", is_flag=True, help="After the build, run `chartbook store gc` (without asking)")
@click.option("--no-gc-reminder", is_flag=True, help="Do not say what `chartbook store gc` would clear")
@click.pass_context
def catalog_generate(ctx, force_write, strict, clean, watch, watch_interval, run_gc, no_gc_reminder, to_open=False):
    """Render the global catalog's site, into docs/ beside its catalog.toml.

    The catalog is the one ~/.chartbook/settings.toml names, or else
    ~/.chartbook/catalog.toml. `chartbook catalog open` opens the site.

    The build is incremental. Its working files are kept next to the catalog
    (in ``_docs/``), and the next build redoes only the pipelines whose files
    changed since: for most of a large catalog, most of the time, nothing.
    Nothing runs in between; it is a record on disk that the next build
    reads. --clean discards it and rebuilds everything. --watch keeps
    rebuilding as files change.

    After the build, one line says what `chartbook store gc` would clear,
    if anything; --gc runs it then, as `chartbook store gc --yes` would.
    Nothing is removed from the store unless you ask.
    """
    _check_sphinx_installed()


    catalog_path = _catalog_or_make_one()
    if not catalog_path.is_file():
        click.echo(f"Error: the settings name a catalog at {catalog_path}, and there is no file there.", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to point at one, or 'chartbook catalog init' to make one.", err=True)
        raise SystemExit(1)

    project_dir = catalog_path.parent
    config_dir = catalog_path.parent
    output_dir = config_dir / "docs"
    _docs_dir = config_dir / "_docs"
    temp_docs_src_dir = config_dir / "_docs_src"

    click.echo(f"Generating the catalog's site from: {catalog_path}")
    click.echo(f"Output directory: {output_dir}")

    # As `chartbook docs build` in the catalog's folder: every folder it
    # reads must be trusted. Before --clean, so that a refused build leaves
    # the kept tree. A settings file may point the catalog at a pipeline's
    # folder: that renders as `chartbook docs build` there would, trusted
    # or not
    untrusted = False if (project_dir / "catalog.toml").is_file() else _require_trust_to_render(project_dir)

    if clean:
        from chartbook.incremental import looks_like_build_tree

        if looks_like_build_tree(_docs_dir):
            import shutil

            shutil.rmtree(_docs_dir)

    # A site built with MkDocs is built whole: the kept build directory is Sphinx's
    from chartbook.manifest import load_manifest

    from chartbook.store import StoreError

    try:
        incremental = load_manifest(project_dir)["project"].get("writer", "sphinx") != "mkdocs"
    except (ValueError, FileNotFoundError, TypeError, KeyError, StoreError) as e:
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
    if to_open:
        return  # built by `chartbook catalog open`, which opens it now
    click.echo("Run 'chartbook catalog open' to open it in your browser.")
    if run_gc:
        ctx.invoke(
            store_gc, dry_run=False, yes=True, forget_missing=False, forget_note=None,
            keep_days=None, keep_lineage=False, aggressive=False,
        )
    else:
        _remind_of_gc(no_gc_reminder)


@catalog.command("open")
@click.pass_context
def catalog_open(ctx):
    """Open the global catalog's site in your default browser.

    The site shows the snapshots that were in your stores when it was last
    built. Where the stores have moved on since (a snapshot made or
    cleared, here or on a machine that shares a store with this one), or
    the site was never built, you are asked whether to build it first.
    Where nothing can ask, it opens the site as it is and says how far
    behind it is. `chartbook catalog build` builds it without opening.
    """
    from chartbook import versions
    from chartbook.store import StoreError, StoreNotAvailableError

    catalog_path = _catalog_or_make_one()
    if not catalog_path.is_file():
        click.echo(f"Error: the settings name a catalog at {catalog_path}, and there is no file there.", err=True)
        click.echo("", err=True)
        click.echo("Run 'chartbook config' to point at one, or 'chartbook catalog init' to make one.", err=True)
        raise SystemExit(1)

    index_path = catalog_path.parent / "docs" / "index.html"
    said, unknown = "", ""
    # Of a catalog, which lists stores. Settings may name a pipeline's own manifest, whose site is its own
    if catalog_path.name == "catalog.toml":
        try:
            # Worked out now, from the stores as they are: no run leaves a mark for this
            state = versions.behind(catalog_path)
            said, unknown = state.said(), state.unknown
        except StoreNotAvailableError:
            raise  # a store in a bucket stops the command; the site is not opened over it
        except (ValueError, OSError, StoreError) as e:
            # A catalog or a store that cannot be read now: what there is is opened, and its build says what is wrong
            unknown = (str(e).strip().splitlines() or ["it could not be read"])[0].rstrip(".")
    if not index_path.is_file():
        said = said or "The catalog's site has not been built yet."
    elif unknown:
        # Nobody is asked to build a site that would lose the pages of what is only away
        click.echo(
            f"Whether the catalog's site is behind your stores cannot be told now: {unknown}. Opening it as it is.", err=True
        )
        said = ""
    if said and _can_ask():
        try:
            build = _confirm(f"{said} Build it before opening?", default=True)
        except click.Abort:  # Ctrl-C, or the end of input
            click.echo("", err=True)
            raise SystemExit(1)
        if build:
            ctx.invoke(
                catalog_generate, force_write=False, strict=False, clean=False, watch=False, watch_interval=None,
                run_gc=False, no_gc_reminder=True, to_open=True,
            )
        elif not index_path.is_file():
            click.echo("Nothing to open. `chartbook catalog build` builds it.", err=True)
            return
    elif said and index_path.is_file():
        click.echo(f"{said} Opening it as it is: `chartbook catalog build` brings it up to date.", err=True)
    if not index_path.is_file():
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + "The catalog's site has not been built yet. `chartbook catalog build` builds it.",
            err=True,
        )
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
@click.option("--catalog", type=click.Path(), help="Path to catalog.toml")
def data_get_path(pipeline, dataframe, catalog):
    """Get the path to a dataframe's parquet file.

    Examples:
        chartbook data get-path --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.data import get_data_path
    from chartbook.store import StoreError

    if catalog is None:
        _catalog_or_make_one()
    try:
        # The command is in the working directory's pipeline: the calling file is this one
        path = get_data_path(pipeline, dataframe, catalog_path=catalog, project_dir=Path.cwd())
        click.echo(str(path))
    except (LookupError, OSError, ValueError, StoreError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@data.command("get-docs")
@click.option("--pipeline", required=True, help="Pipeline ID")
@click.option("--dataframe", required=True, help="Dataframe ID")
@click.option("--catalog", type=click.Path(), help="Path to catalog.toml")
def data_get_docs(pipeline, dataframe, catalog):
    """Print a dataframe's page: its facts, its write-up and its columns.

    `chartbook get-docs` does this for any asset, and a pipeline's README.

    \b
    Examples:
        chartbook data get-docs --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.assets import get_docs_page
    from chartbook.refs import parse_asset_ref
    from chartbook.store import StoreError

    if catalog is None:
        _catalog_or_make_one()
    try:
        docs = get_docs_page(pipeline, parse_asset_ref(dataframe, kind="dataframe"), catalog_path=catalog)
        click.echo(docs.rstrip("\n"))
    except (KeyError, ValueError, StoreError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except FileNotFoundError as e:
        click.echo(f"Error: Documentation file not found: {e}", err=True)
        raise SystemExit(1)


@data.command("get-docs-path")
@click.option("--pipeline", required=True, help="Pipeline ID")
@click.option("--dataframe", required=True, help="Dataframe ID")
@click.option("--catalog", type=click.Path(), help="Path to catalog.toml")
def data_get_docs_path(pipeline, dataframe, catalog):
    """Get the path to a dataframe's documentation source.

    Examples:
        chartbook data get-docs-path --pipeline yield_curve --dataframe repo_public
    """
    from chartbook.data import get_docs_path
    from chartbook.store import StoreError

    if catalog is None:
        _catalog_or_make_one()
    try:
        path = get_docs_path(pipeline, dataframe, catalog_path=catalog)
        click.echo(str(path))
    except (KeyError, ValueError, StoreError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


#: The options of `chartbook get-docs` that name one asset of a pipeline by its kind
_KIND_OPTIONS = ("dataframe", "chart", "model", "file", "note")


def _named_by_options(options):
    """The asset the kind options name, of the option's kind; None for none, the pipeline's README."""
    from chartbook.refs import parse_asset_ref

    given = [(kind, options[kind]) for kind in _KIND_OPTIONS if options[kind]]
    if len(given) > 1:
        raise click.UsageError(f"Name one asset, not {len(given)}: {', '.join('--' + kind for kind, _ in given)}.")
    if not given:
        return None
    kind, name = given[0]
    try:
        ref = parse_asset_ref(name, kind=kind)
    except ValueError as error:  # KindMismatchError too: --dataframe chart/x is not a dataframe
        raise click.UsageError(f"--{kind} {name}: {error}") from None
    if ref.pipeline is not None or ref.part or ref.rev:
        raise click.UsageError(f"--{kind} takes the {kind}'s name alone: give its pipeline with --pipeline.")
    return ref


def _kind_options(command):
    """`--dataframe`, `--chart`, `--model`, `--file` and `--note`, each a name."""
    for kind in reversed(_KIND_OPTIONS):
        shown = "files asset" if kind == "file" else kind
        command = click.option(f"--{kind}", metavar="NAME", help=f"A {shown}'s name")(command)
    return command


def _split_docs_id(text):
    """A `get-docs` ID as its pipeline and its asset; the asset None when the ID is a pipeline alone.

    An asset never holds a colon, so the last one divides the two, as in any
    reference (:func:`chartbook.refs.parse_asset_ref`): ``acme/yield_curve:chart/x``,
    ``https://github.com/acme/yield_curve:repo_public``. What follows the
    last colon is the asset only when it reads as one, so a repository URL
    alone (``https://github.com/acme/yield_curve``, ``git@github.com:acme/yield_curve.git``,
    a host with a port) is a pipeline.
    """
    import re

    from chartbook.refs import parse_asset_ref

    head, colon, tail = text.rpartition(":")
    if not colon or not head:
        return text, None
    try:
        parse_asset_ref(tail)
        # And what comes before is a pipeline: a URL (git's form has a path,
        # git@github.com:acme/rates), or an ID, which holds no "@"
        if "://" not in head and not re.fullmatch(r"[^\s/@:]+@[^\s/:]+:\S*/\S*", head):
            probe = parse_asset_ref(f"{head}:name")
            if probe.pipeline is None or probe.part or probe.rev:
                return text, None
    except ValueError:
        return text, None
    return head, tail


@main.command("get-docs")
@click.argument("asset_id", metavar="[ID]", required=False)
@click.option("--pipeline", help="The pipeline: a bare name, a scoped ID or a repository URL")
@_kind_options
@click.option("--path", "as_path", is_flag=True, help="Print where the write-up's file is, not its text")
@click.option("--catalog", type=click.Path(), help="Path to catalog.toml")
def get_docs_command(asset_id, pipeline, dataframe, chart, model, file, note, as_path, catalog):
    """Print the documentation of a cataloged pipeline's asset, or with no asset its README.

    What a person reads on the asset's page in the catalog, for a script or
    an agent, in Markdown. A dataframe's is its whole page: its name,
    description, sources and license, its rows and dates, its write-up, and
    a table of its columns and their types. A chart's, model's or files
    asset's is its write-up (its docs or docs_path), and a note's its text.
    Name the asset by its ID, as `chartbook ls` prints it, or with keywords.
    A bare name is a pipeline, so `chartbook get-docs yield_curve` is its
    README. A notebook has no write-up apart from itself. Read from the
    pipeline's newest snapshot in the catalog's stores.

    \b
    Examples:
        chartbook get-docs yield_curve
        chartbook get-docs yield_curve:chart/repo_rates
        chartbook get-docs --pipeline yield_curve --chart repo_rates
        chartbook get-docs --pipeline rate_forecast --model forecaster
        chartbook get-docs yield_curve:repo_public --path
    """
    from chartbook.assets import get_docs_page, get_docs_path
    from chartbook.store import StoreError

    keyword = _named_by_options({"dataframe": dataframe, "chart": chart, "model": model, "file": file, "note": note})
    if asset_id and pipeline:
        raise click.UsageError("Give the pipeline once: in the ID (yield_curve:chart/repo_rates) or with --pipeline.")
    pipeline_in_id, asset_in_id = _split_docs_id(asset_id) if asset_id else (None, None)
    if asset_in_id is not None:
        if keyword is not None:
            raise click.UsageError(f"{asset_id} names its asset already: leave out the asset option.")
        pipeline, asset = pipeline_in_id, asset_in_id
    else:
        pipeline, asset = asset_id or pipeline, keyword
    if not pipeline:
        raise click.UsageError("Name a pipeline: chartbook get-docs PIPELINE[:kind/name], or --pipeline PIPELINE.")
    if catalog is None:
        _catalog_or_make_one()
    try:
        if as_path:
            click.echo(str(get_docs_path(pipeline, asset, catalog_path=catalog)))
        else:
            click.echo(get_docs_page(pipeline, asset, catalog_path=catalog).rstrip("\n"))
    except StoreError as e:
        # The store's own words, as a synced folder still downloading the snapshot
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except (KeyError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except FileNotFoundError as e:
        click.echo(f"Error: Documentation file not found: {e}", err=True)
        raise SystemExit(1)


def _echo_pin_report(report, listed=()):
    """Print what a pin or an update did, one line per dependency and exception.

    :param listed: The dependencies that are on the list of what is not in
        the store (:mod:`chartbook.missing`): the list says what there is
        to say of them.
    """
    from chartbook import lock
    from chartbook.check import display_path
    from chartbook.links import read as read_links
    from chartbook.refs import KIND_TABLES
    linked = read_links(report.lockfile.parent, active=False)
    if linked:
        click.echo(f"{len(linked)} link(s) in place, not used here.")

    by_dependency = {}
    for event in report.events:
        by_dependency.setdefault(event.dependency, []).append(event)

    for dependency, events in by_dependency.items():
        if dependency in listed:
            continue
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
            "glob_name": "named like a pattern",
            "let_go": "let go",
            "dropped": "no longer declared",
            "lost": "lost",
            "unsynced": "not fully synced",
            "stood_in": "met by your own build",
            "differs": "not met by your own build",
        }
        summary = ", ".join(
            f"{counts[status]} {words[status]}" for status in words if status in counts
        )
        # What a lockfile does not hold, by kind: 2 charts and 1 notebook
        unlocked = {}
        for event in assets:
            if event.status == "unlocked":
                kind = KIND_TABLES.get(event.detail, "others")
                unlocked[kind] = unlocked.get(kind, 0) + 1
        if unlocked:
            one = sum(unlocked.values()) == 1
            # A chart and a notebook for what they are; a note or a plain file for want of its owner's mark
            why = (
                f"each build draws {'it' if one else 'them'} anew" if set(unlocked) <= {"charts", "notebooks"}
                else f"{'it is' if one else 'they are'} read from its snapshot"
            )
            not_pinned = f"{lock.left_out_said(unlocked)} {'is' if one else 'are'} not pinned: {why}"
            summary = f"{summary}. Its {not_pinned}" if summary else f"its {not_pinned}"
        for event in whole:
            if event.status == "fetched":
                click.echo(f"{dependency}: fetched {event.detail}")
            elif event.status == "at_snapshot":
                summary = (
                    f"pinned to its snapshot at {event.detail}; none of its assets is in the lockfile"
                    + (f"; {summary}" if summary else "")
                )
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
                    f"where it was: `chartbook pin --update {dependency}` follows it."
                )
            elif event.status in ("passed_over", "unchecked", "id_changed"):
                click.echo(f"  {event.detail}.")

        for event in assets:
            if event.status == "moved":
                click.echo(f"  {event.asset}\n    {_short_hash(event.old)} -> {_short_hash(event.new)}")
                if event.asset in getattr(report, "rows_said", {}):
                    click.echo(f"    {report.rows_said[event.asset]}")
            elif event.status == "not_built":
                click.echo(f"  not built: {event.asset} ({event.detail})")
            elif event.status == "stale":
                click.echo(f"  changed upstream: {event.asset}")
            elif event.status == "let_go":
                click.echo(f"  let go: {event.asset} ({event.detail})")
            elif event.status in ("outside", "glob_name"):
                click.echo(f"  not pinned: {event.asset}: {event.detail}")
            elif event.status == "dropped":
                click.echo(f"  no longer declared: {event.asset}")
            elif event.status == "lost":
                # What is wrong with one is most often wrong with all of them: said once
                same = [e for e in assets if e.status == "lost" and e.detail == event.detail]
                if same[0] is not event:
                    continue
                if len(same) == 1:
                    pinned_at = f" ({_short_hash(event.old)})" if event.old else ""
                    click.echo(f"  lost: {event.asset}{pinned_at}: {event.detail}")
                else:
                    names = ", ".join(e.asset.split(":", 1)[-1] for e in same)
                    click.echo(f"  lost, each of {names}: {event.detail}")
            elif event.status == "unsynced":
                click.echo(f"  not fully synced: {event.asset}: {event.detail}")
            elif event.status == "differs":
                click.echo(f"  differs: {event.asset}: {event.detail}")
        stood = getattr(report, "stood_in", {}).get(dependency)
        if stood is not None and not stood.stands_in:
            from chartbook import standins

            with_index = [unmet.asset.split(":", 1)[-1] for unmet in stood.unmet if unmet.index_column]
            if with_index:
                click.echo(f"  {lock.index_column_said(with_index)}")
            yours = lock.read_yours_said(dependency, stood)
            click.echo(
                f"  Your build of {standins.build_said(stood.snapshot)}, does not match the pin."
                + (f" {yours}" if yours else "")
            )
        elif stood is not None and counts.get("stood_in"):
            # The store does not have the pinned bytes, and a snapshot of yours holds the same rows
            from chartbook import standins

            click.echo(f"  Read from your own build of {standins.build_said(stood.snapshot)}.")
            for line in _met_by_rows(stood):
                click.echo(f"  {line}")
        if dependency in report.snapshots:
            taken = report.snapshots[dependency]
            made_in = f", which says it was made in {taken.repository}" if getattr(taken, "repository", "") else ""
            from chartbook.multi_store import with_dependencies
            sources = with_dependencies(report.lockfile.parent)
            if hasattr(sources, "name_of"):
                source_name = sources.name_of(taken.path)
                if source_name:
                    made_in += f", in store {source_name}"
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
    if report.earlier:
        # Said once: the next pin finds it in this form
        click.echo(lock.written_again_said(shown, report.left_out, report.kept_earlier))
    if getattr(report, "without_rows", None):
        click.echo(lock.without_rows_said(report.without_rows))
    if getattr(report, "rows_now", None):
        click.echo(lock.rows_now_said(report.rows_now))
    for asset, why in getattr(report, "not_hashed_now", ()):
        # The other outcome of a snapshot made again: a table that cannot be hashed says why, and the lockfile with it
        click.echo(f"{asset}: its rows are not hashed ({why}): it stays pinned by its file alone.")
    floor = getattr(report, "floor", None)
    if floor is not None:
        manifest_shown = display_path(floor.manifest, relative_to=Path.cwd())
        click.echo(lock.floor_said(floor, manifest_shown, report.lockfile.name, lock.where_to_pin(floor)))
    if report.written:
        click.echo(f"Wrote {shown}.")
    elif report.lockfile.exists() and not (listed and all(event.dependency in listed for event in report.events)):
        # With everything on the list of what is not in the store, the list says what there is to say
        click.echo(f"{shown} is unchanged.")

    stale = report.count("stale")
    if stale:
        click.echo(
            f"{stale} pinned asset(s) have changed upstream. `chartbook pin --update` "
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
        # The two commands a person runs to change what the project pins: they see to the manifest's
        # requires_chartbook as well, which a build and a read never write
        if dependencies is None:
            report = lock.pin(project_dir, raise_floor=True)
        else:
            report = lock.update(project_dir, dependencies, raise_floor=True)
    except (lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    if report.refused:
        # Nothing was written, so what it would have pinned is not shown as pinned
        click.echo(click.style("Error: ", fg="red", bold=True) + report.refused, err=True)
        if on_refused is not None:
            on_refused()
        raise SystemExit(1)
    listing, no_order = None, None
    if dependencies is None and report.problems:
        # What it reads that is not in the store, in the order to build it. Not for --update, which
        # wants the newest of each, and not the commit its pin names
        from chartbook import missing

        try:
            listing = missing.after_pin(project_dir, report, echo=click.echo)
        except missing.NoOrder as e:
            no_order = e
    listed = listing.keys if listing is not None else set()
    # Always: its closing lines say what was written, the manifest's requires_chartbook among it
    _echo_pin_report(report, listed=listed)
    if report.unrooted:
        click.echo(
            f"The store's note of this lockfile, for `store gc`, could not be written "
            f"({report.unrooted}); `store gc` goes by the note it has."
        )
    if no_order is not None:
        # Said, and nothing undone: the cycle may be one the entry just added has no part in
        click.echo(click.style("Error: ", fg="red", bold=True) + f"{no_order.root}: {no_order}", err=True)
        raise SystemExit(1)
    if listing is not None:
        for line in missing.said(listing, again="chartbook pin", done="pinned"):
            click.echo(line, err=True)
    others = [event for event in report.problems if event.dependency not in listed]
    if others:
        click.echo(
            f"\n{len(others)} {'other ' if listed else ''}thing(s) could not be pinned.", err=True
        )
    if report.problems:
        raise SystemExit(1)


def _met_by_rows(stood) -> list:
    """A line for each pin a snapshot of yours meets by its rows: how far the pinned rows go, and how many it has after."""
    lines = []
    for asset_id in sorted(stood.met):
        met = stood.met[asset_id]
        if met.by != "rows":
            continue
        through = f", through {met.as_of}" if met.as_of else ""
        after = (
            f"; {met.newer:,} newer row{'' if met.newer == 1 else 's'}" if met.newer else ", in other bytes"
        )
        lines.append(f"{asset_id.split(':', 1)[-1]}: the pinned rows{through}{after}")
    return lines


def _echo_frozen_report(step, report):
    """Print what `pin --check` or `run --frozen` found: one line when all is well, else each problem."""
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
    if report.earlier:
        from chartbook import lock

        # Checked as this version would have written it; `pin --check` writes nothing
        gone = lock.left_out_said(report.left_out)
        one = sum(report.left_out.values()) == 1
        why = (
            f"since no rebuild gives {'its' if one else 'their'} bytes again" if set(report.left_out) <= {"charts", "notebooks"}
            else f"since {'it is' if one else 'they are'} no longer pinned"
        )
        kept = getattr(report, "kept_earlier", 0)
        click.echo(
            f"{who}{report.lockfile.name} is in an earlier form, which pinned every asset"
            + (f": its {gone} {'is' if one else 'are'} not checked, {why}" if gone else "")
            + (
                f"; {kept} of its records of charts, notebooks, notes and files {'is' if kept == 1 else 'are'} checked "
                f"all the same, the store having {'its' if kept == 1 else 'their'} bytes and no snapshot to read "
                f"{'it' if kept == 1 else 'them'} from"
                if kept else ""
            )
            + ". `chartbook pin` writes it again in the new form."
        )
    # A dependency read from a snapshot of yours, which holds the pinned rows in other bytes
    for key, stood in sorted(getattr(report, "stood_in", {}).items()):
        from chartbook import standins

        click.echo(f"{who}{key}: read from your own build of {standins.build_said(stood.snapshot)}")
        for line in _met_by_rows(stood):
            click.echo(f"  {line}")
    if not report.problems:
        by_build = getattr(report, "by_your_build", 0)
        where = (
            f": {report.pins - by_build} in the store, {by_build} met by your own build" if by_build
            else ", all in the store"
        )
        by_entry = getattr(report, "by_entry", 0)
        alone = (
            f"; {by_entry} dependenc{'y is' if by_entry == 1 else 'ies are'} pinned by "
            f"{'its' if by_entry == 1 else 'their'} snapshot alone, which the store has a build of" if by_entry else ""
        )
        click.echo(
            f"{who}{report.pins} pin(s) of {report.dependencies} dependenc"
            f"{'y' if report.dependencies == 1 else 'ies'}{where}{alone}. {written}"
        )
        return
    said = set()
    for problem in report.problems:
        once = getattr(report, "not_in_store", {}).get(problem.dependency) if problem.kind == "not_in_store" else None
        if once:
            # Pins the store does not have: said once for their dependency, with each way on
            if problem.dependency not in said:
                said.add(problem.dependency)
                click.echo(f"{who}{problem.dependency}: " + "\n".join(once), err=True)
            continue
        where = problem.asset or problem.dependency
        click.echo(f"{who}{where + ': ' if where else ''}{problem.message}", err=True)
    click.echo(
        f"{who}{len(report.problems)} problem(s): the pipeline cannot be built from its "
        f"lockfile alone. {written}",
        err=True,
    )


def _pin_frozen_is_gone(ctx, param, value):
    """Refuse `chartbook pin --frozen`, the name `chartbook pin --check` had through 0.5.1, and say what does each half of what it did."""
    if value:
        raise click.UsageError(
            "`chartbook pin --frozen` is gone. `chartbook pin --check` says whether everything pinned can be read "
            "here, and writes nothing; `chartbook run --frozen` builds from the lockfile, and leaves the store's "
            "note that this machine reads these pins.",
            ctx=ctx,
        )


@main.command()
@click.argument("names", nargs=-1)
@click.option("--project-dir", type=click.Path(), help="Path to the pipeline")
@click.option(
    "--update",
    "moving",
    is_flag=True,
    help="Move pins to the newest snapshot: every dependency's, or those of the dependencies named",
)
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    help="Write nothing: say whether the lockfile is complete and every pin is in the store; exit 1 if not",
)
@click.option("--frozen", is_flag=True, hidden=True, expose_value=False, callback=_pin_frozen_is_gone)
def pin(names, project_dir, moving, check_only):
    """Freeze what this pipeline depends on, in chartbook.lock.

    \b
    chartbook pin                     pin what has no pin yet
    chartbook pin --update [NAMES...] move pins to the newest snapshot
    chartbook pin --check             can everything pinned be read here?

    Each pipeline in [dependencies] is pinned to a snapshot of it: what its
    owner built at a commit (`chartbook snapshot`). The content hash of each of
    its dataframes and models is written to chartbook.lock. Commit that
    file: a change to what the project depends on then shows in a diff.

    A chart, a notebook, a note or a plain file is not pinned unless its
    owner's chartbook.toml says lock = true on it: every build draws one
    anew, so no rebuild gives its bytes again. It is read from the snapshot
    the lockfile names.

    None of the other pipeline's data in its folder is read. It can be
    half-way through a change, and what you pin is still the build that
    was snapshotted. Its chartbook.toml and chartbook.lock are read, to
    see that the pin makes no cycle: a pin whose new or moved entries would
    lead back to this pipeline, or into pipelines that depend on each
    other, is not written.

    A pin that already exists is never moved by a plain `chartbook pin`,
    whatever the other pipeline has done since: it pins a dependency that
    has no pin yet, which `chartbook run` does itself before a build.

    --update moves pins forward to the newest snapshot of each dependency.
    With no NAMES, every dependency is updated. Name some to update only
    those, as they are written in [dependencies]; the scope may be left
    off when only one has that name. Each pin that changes is printed with
    its old and new hash, and chartbook.lock is rewritten. Nothing is
    rebuilt: this pipeline's own outputs are as they were.

    A dependency that is a git repository is fetched, and pinned from a
    clean copy of the commit.

    --check pins nothing and writes nothing: not the lockfile, no object,
    and not the store's note for `store gc`. It says whether the pipeline
    can be built from its lockfile alone, every dependency pinned and every
    pin in the store, and exits 1 if not. For CI, and for a store you may
    only read. `chartbook run --frozen`, which builds from the lockfile,
    is what leaves the note that this machine reads these pins.

    \b
    Examples:
        chartbook pin
        chartbook pin --update
        chartbook pin --update fed_yield_curve
        chartbook pin --project-dir ../rate_forecast
        chartbook pin --check
    """
    if moving and check_only:
        raise click.UsageError("--update moves pins and --check writes nothing. One or the other.")
    if names and check_only:
        # Not answered with a command that writes: the check is of every pin, and takes no name
        raise click.UsageError("--check takes no name: it says whether every pin of the pipeline can be read here, and writes nothing.")
    if names and not moving:
        import os

        from chartbook import missing

        folder = next((name for name in names if os.path.isdir(name)), None)
        if folder is not None and project_dir is None:
            # A folder where a dependency's name goes: the pipeline to pin was meant
            raise click.UsageError(
                f"{folder} is a folder, and a pipeline is named with --project-dir: "
                f"`{missing.typed(['chartbook', 'pin', '--project-dir', folder])}`."
            )
        meant = ["chartbook", "pin", "--update", *names, *(["--project-dir", project_dir] if project_dir else [])]
        raise click.UsageError(
            f"A name goes with --update: `{missing.typed(meant)}` moves the pins of what it names. "
            f"`chartbook pin` pins what has no pin yet, of every dependency."
        )
    if check_only:
        _run_check(project_dir)
        return
    _run_pin(project_dir, dependencies=list(names) if moving else None)


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
            f"{str(error).rstrip('.')}. This had to write it: a git dependency's first pin and a "
            f"snapshot both put files into the store. Do it where the store can be written; or, "
            f"if the store already has what the lockfile names, use `run --frozen` (or `pin --check` to only check)."
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
                f"use `run --frozen` (or `pin --check` to only check). ({error})"
            )
    return _said(error)


def _run_check(project_dir):
    """Say whether a pipeline can be built from its lockfile alone, and write nothing; exit 1 if not."""
    from chartbook import lock
    from chartbook.store import StoreError

    try:
        report = lock.verify(resolve_project_dir(project_dir), note=False)
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


class _StoredIds:
    """The IDs of the pipelines a pipeline's stores hold snapshots of, read once, when first asked for."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self._store = self._ids = None

    def _stores(self):
        if self._store is None:
            from chartbook.multi_store import with_dependencies
            self._store = with_dependencies(self.project_dir)
        return self._store

    @property
    def where(self) -> str:
        return str(self._stores())

    @property
    def unreachable(self) -> list:
        """The names of the stores that cannot be read now, whose pipelines are not among :attr:`ids`."""
        return [entry.name for entry in getattr(self._stores(), "entries", None) or [] if not entry.reachable]

    @property
    def ids(self) -> list:
        if self._ids is None:
            from chartbook.snapshot import readable_snapshots
            self._ids = sorted({taken.pipeline for taken in readable_snapshots(self._stores())[0]})
        return self._ids


def _bare_name_in_stores(name, stored, itself):
    """The ID of the one pipeline in the stores that a bare name names; ValueError if none does, or several.

    As `chartbook get-docs` and `data.load(pipeline=...)` read a bare name:
    the ID itself if the stores hold a bare one, else the one whose name
    part it is. A bare ID is never cloned from a host, so one the stores
    do not hold could never be pinned.
    """
    from chartbook.identity import in_another_case, match_pipeline_ref

    if stored.unreachable:
        # The one it names among those read may not be the only one
        raise ValueError(
            f"Which pipeline {name} names cannot be told while {', '.join(stored.unreachable)} cannot be "
            f"read: add it by its ID (`chartbook add SCOPE/{name}`), or once every store can be read. "
            f"Nothing was written."
        )
    others = [i for i in stored.ids if i != itself]  # never itself, when another has the name too
    try:
        found = match_pipeline_ref(others, name, where=f"the store at {stored.where}")
    except KeyError:
        matching = [i for i in others if i.rsplit("/", 1)[-1] == name]
        raise ValueError(
            f"{name} names more than one pipeline in the store at {stored.where}: "
            f"{', '.join(matching)}. Add one by its ID, as `chartbook add {matching[0]}`. "
            f"Nothing was written."
        ) from None
    if found is not None:
        return found
    if itself is not None and name == itself.rsplit("/", 1)[-1]:
        return itself
    if not stored.ids:
        held = "it holds no snapshots"
    else:
        other = in_another_case(stored.ids, name)
        hint = f" Did you mean {other}?" if other else ""
        held = f"it holds snapshots of {', '.join(stored.ids)}.{hint} Add one by its ID"
    raise ValueError(
        f"No pipeline in the store at {stored.where} is named {name}: {held}. A pipeline is in "
        f"the store once its owner runs `chartbook snapshot`. Nothing was written."
    )


def _unpinnable_bare_name(declared, name, stored):
    """How a [dependencies] entry under a bare name that no store holds is described; None if it is not one.

    An older `chartbook add NAME` wrote such an entry and left it: it can
    never be pinned, and code naming NAME reads it rather than the pipeline
    meant.
    """
    entry = declared.get(name)
    if not isinstance(entry, dict) or "path" in entry or "git" in entry:
        return None
    named = entry.get("id", name)
    if not isinstance(named, str) or "/" in named or named in stored.ids:
        return None
    return f"a bare ID the store at {stored.where} has no snapshot of, so it cannot be pinned"


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
    alone: no folder of it here, and no clone. `chartbook pin --update` moves the
    pin to a newer snapshot.

    A bare name (`rates`) is the one pipeline in the stores whose ID ends in
    it, and that ID is written. If several do, or none, nothing is written
    and the IDs the stores hold are listed.

    \b
    Examples:
        chartbook add acme/rates
        chartbook add rates
        chartbook add acme/rates --as rates
        chartbook add acme/rates --commit 3f2a9c1
    """
    _add_dependency(project_dir, pipeline, key=key, commit=commit)


def _add_dependency(project_dir, pipeline, key=None, commit=None):
    """Write a dependency into a pipeline's manifest and pin it, as `chartbook add` does; exit 1 where it cannot be.

    For the command, and for a run that offers to declare a pipeline its
    build read without declaring it (:func:`_offer_to_add`).
    """
    from chartbook.identity import validate_pipeline_id
    from chartbook.manifest import dependency_line, validate_dependencies, with_dependency
    from chartbook.store import StoreError

    project_dir = resolve_project_dir(project_dir)
    manifest_file = project_dir / "chartbook.toml"
    try:
        # Before anything is written: a manifest for a newer ChartBook is not edited by this one
        from chartbook.manifest import _read_manifest_file, require_chartbook

        if manifest_file.is_file():
            require_chartbook(_read_manifest_file(project_dir), str(manifest_file))
        repository = None
        if "://" in pipeline or pipeline.startswith("git@"):
            from chartbook.identity import id_from_address, remote_to_web_url
            repository = remote_to_web_url(pipeline)
            pipeline = id_from_address(pipeline)
            if pipeline is None:
                raise ValueError("The dependency must name a repository URL")
        validate_pipeline_id(pipeline)
        from chartbook.snapshot import SnapshotError, pipeline_in

        try:
            itself = pipeline_in(project_dir)
        except (SnapshotError, ValueError):
            itself = None
        with open(manifest_file, encoding="utf-8", newline="") as f:  # as it is, line endings included
            text = f.read()
        import tomli

        declared = tomli.loads(text).get("dependencies")
        declared = declared if isinstance(declared, dict) else {}
        stored = _StoredIds(project_dir)
        if not repository and "/" not in pipeline:
            if pipeline in declared and not key:
                stale = _unpinnable_bare_name(declared, pipeline, stored)
                if stale:
                    raise ValueError(
                        f"[dependencies] has {pipeline!r} already, as {stale}. Delete its line in "
                        f"{manifest_file}, then run `chartbook add {pipeline}` again."
                    )
            else:
                # A bare name is the one pipeline in the stores whose ID ends in it
                pipeline = _bare_name_in_stores(pipeline, stored, itself)
        if pipeline == itself:
            raise ValueError(f"{pipeline} is this pipeline itself: a pipeline cannot depend on itself.")
        key = key or pipeline
        entry = {"repository": repository} if repository else {}
        if key != pipeline:
            entry["id"] = pipeline
        if commit:
            entry["commit"] = commit
        changed = with_dependency(text, key, entry)
        validate_dependencies(tomli.loads(changed).get("dependencies") or {}, project_dir)
        # A bare name left by an older `chartbook add`, which code naming the bare name reads instead
        bare = pipeline.rsplit("/", 1)[-1]
        stale = _unpinnable_bare_name(declared, bare, stored) if bare != pipeline and bare != key else None
    except (ValueError, OSError, StoreError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)
    try:
        with open(manifest_file, "w", encoding="utf-8", newline="") as f:
            f.write(changed)
    except OSError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + f"{manifest_file} could not be written: {_explain_os_error(e)}", err=True)
        raise SystemExit(1)
    click.echo(f"Added to [dependencies] in {manifest_file}: {dependency_line(key, entry)}")
    if stale:
        click.echo(
            f"[dependencies] also has {bare!r}, as {stale}: `{bare}:NAME` reads that entry, not "
            f"{pipeline}. Delete its line in {manifest_file}.",
            err=True,
        )

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
@click.option("--store", "store_names", multiple=True, help="Write to this catalog store (repeat for several)")
@click.option(
    "--complete",
    is_flag=True,
    help="Keep this snapshot complete: every file of it in one folder of the store, which is named. Without it the store may keep one as an increment, with only the files that changed",
)
@click.option(
    "--as-is",
    "as_is",
    is_flag=True,
    help="Take what is on disk as it is, without holding it against the last build `chartbook run` made here",
)
@click.option("--no-gc-reminder", is_flag=True, help="Do not say what `chartbook store gc` would clear")
def snapshot(project_dir, deep, store_names, complete, as_is, no_gc_reminder):
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

    `chartbook run` builds and makes no snapshot: you type this when a
    build is one that others should read. It does not run the build. It
    holds what is committed, and what is on disk, against the note the
    last `chartbook run` left here: the files it built from, and the
    files it left. Where they differ it stops and names them, since the
    label would say that this commit built files it did not. Build again,
    or type --as-is to take what is on disk as it is, however it was
    built (doit by hand, a notebook, a long job). A pipeline with no
    `build` script is not asked: it commits what it declares.
    `chartbook run --snapshot` is the two in one command.

    A pipeline that depends on this one keeps the snapshot it pinned,
    however many you make after it. It gets a newer one with
    `chartbook pin --update`, and not before.

    Where little has changed since an earlier snapshot, the store keeps
    this one in less room, as an increment: its folder there holds only
    the files that differ. To whatever reads or pins it, it is a snapshot
    like any other. --complete keeps it complete, a folder that stands by
    itself and can be copied as it is, and says where that folder is. A
    complete one of the same files that is there already is named only
    once each of its files has been read and found to be what its record
    says; otherwise a new one is made.

    \b
    Examples:
        chartbook snapshot
        chartbook snapshot --project-dir ../fed_yield_curve
        chartbook snapshot --complete
    """
    from chartbook import snapshot as snapshots
    from chartbook.store import ReadOnlyStoreError, StoreError

    project_dir = resolve_project_dir(project_dir)
    here = _in_its_folder(project_dir)
    ran_by_chartbook = False if as_is else _held_against_its_build(project_dir, here, deep, store_names, complete)
    try:
        report = snapshots.make(
            project_dir, deep=deep, store_names=list(store_names) or None, complete=complete, built_by_run=ran_by_chartbook,
        )
    except (snapshots.SnapshotError, StoreError, ValueError, OSError) as e:
        said = _explain_os_error(e)
        if isinstance(e, snapshots.NothingToSnapshot) and here:
            # The command it names builds this pipeline from wherever the snapshot was typed
            said = said.replace("Build it first: `chartbook run`.", f"Build it first: `chartbook run{here}`.")
        click.echo(click.style("Error: ", fg="red", bold=True) + said, err=True)
        # Nothing of it is there to take: each thing, and why, since the run that built it said only
        # that this command makes a snapshot. A reason may run to several lines (an engine's own
        # message): its first says it
        not_built = list(getattr(e, "not_built", None) or ())
        for name, why in not_built[:10]:
            click.echo(f"  not built: {name} ({(str(why).splitlines() or [''])[0]})", err=True)
        if len(not_built) > 10:
            click.echo(f"  and {len(not_built) - 10} more", err=True)
        if isinstance(e, ReadOnlyStoreError) and not store_names:
            # A class's store listed ahead of one's own stops every snapshot of a pipeline the catalog
            # sends nowhere, until the catalog says where this one goes: the way out, where there is one
            sent = _a_store_to_send_it_to(project_dir)
            if sent is not None:
                way, other = sent
                click.echo(
                    f"  It is the catalog's first store, where a pipeline the catalog sends nowhere is written.\n"
                    f"  {way}\n"
                    f"  Or, for this one snapshot: `chartbook snapshot --store {other}{here}`.",
                    err=True,
                )
        if _only_the_lockfile_is_uncommitted(project_dir, e):
            # A run wrote it. Its owner commits it. At a commit somebody else pinned, a commit would be one
            # nobody else has, and a snapshot of that meets no pin: there the run that passes over the lockfile
            click.echo(
                f"  Only chartbook.lock is not committed: commit it. Or, at a commit somebody else pinned, "
                f"`chartbook run --snapshot{here}`, which builds and takes its snapshot with the lockfile as it is.",
                err=True,
            )
        raise SystemExit(1)

    _echo_snapshot(report)
    _say_where_a_snapshot_shows()
    try:
        from chartbook.snapshot import pipeline_in

        which = pipeline_in(Path(project_dir) if project_dir else Path("."))
    except Exception:  # noqa: BLE001 - a reminder never fails the command; without an ID, say of the whole store
        which = None
    _remind_of_gc(no_gc_reminder, pipeline=which)


def _held_against_its_build(project_dir, here: str, deep: bool, store_names, complete: bool) -> bool:
    """Hold a pipeline's folder against what the last `chartbook run` built here, before a snapshot of it is made; whether ChartBook ran the build.

    Stops the command where the files are not the build's
    (:mod:`chartbook.built`), with what differs and the two ways on. Not
    where something is uncommitted, or the folder cannot be read: the
    snapshot itself says that, in its own words.
    """
    from chartbook import built
    from chartbook import snapshot as snapshots
    from chartbook.missing import _quoted

    try:
        if snapshots.uncommitted(project_dir):
            return False
        if not built.built_files(project_dir):
            from chartbook import hashing
            from chartbook.resolve import declared_files

            if not any((found := hashing.find_files(abs_path)) and found.files for _, _, abs_path in declared_files(project_dir)):
                return False  # not committed, or nothing built at all: the snapshot names each thing
        pipeline = snapshots.pipeline_in(project_dir)
    except (snapshots.SnapshotError, OSError, ValueError):
        return False  # no pipeline there, no repository, a manifest that is no TOML: the snapshot says so
    try:
        return built.check(project_dir, pipeline)
    except built.NotHeld as refusal:
        typed = "".join([
            " --deep" if deep else "", *(f" --store {_quoted(name)}" for name in store_names), " --complete" if complete else "",
        ])
        first, *rest = built.said(refusal, pipeline, here, typed)
        click.echo(click.style("Error: ", fg="red", bold=True) + first, err=True)
        for line in rest:
            click.echo(line, err=True)
        raise SystemExit(1) from None


def _a_store_to_send_it_to(project_dir):
    """For a snapshot refused because the catalog sends its pipeline nowhere and its first store may only be read: the sentence that says how to send it to the first store that may be written (:func:`chartbook.run.way_out_said`), and that store's name; None otherwise.

    A catalog's first store is where everything goes that it sends nowhere
    by name (a pin's copies, a lockfile's note, a snapshot), so a class's
    read-only store listed ahead of one's own stops every snapshot until
    the catalog says where this pipeline goes. Where no store of the
    catalog may be written, there is nowhere to send it, and nothing to say.
    """
    from chartbook import run as runner
    from chartbook import snapshot as snapshots

    try:
        pipeline = snapshots.pipeline_in(project_dir)
    except Exception:  # noqa: BLE001 - only to say more of an error already said
        return None
    other = runner._a_store_to_send_it_to(None, pipeline)
    return (runner.way_out_said(None, pipeline), other) if other is not None else None


def _only_the_lockfile_is_uncommitted(project_dir, error) -> bool:
    """Whether a snapshot was refused for uncommitted work, and this pipeline's own lockfile, written, is all of it.

    Its own: asked of git by its path in the pipeline's folder, so not a
    file of that name in a folder below. Written: a lockfile that was
    removed is not one to commit, nor one a run would build "as it is".
    """
    from chartbook import lock
    from chartbook import snapshot as snapshots

    if not isinstance(error, snapshots.SnapshotError) or "has changes that are not committed" not in str(error):
        return False
    try:
        every = snapshots.uncommitted(project_dir)
        own = snapshots.uncommitted(project_dir, only=lock.LOCK_FILE)
        return bool(every) and every == own and all("D" not in line[:2] for line in own)
    except Exception:  # noqa: BLE001 - only to say more of an error already said
        return False


def _lineage_line(node) -> str:
    """How one pipeline of a lineage is shown."""
    made = f"{node.made_at[:10]} {node.made_at[11:19]} UTC" if node.made_at else ""
    if node.kind == "working":
        return f"{node.pipeline} (this folder)"
    if node.kind == "snapshot":
        seen = " (shown above)" if node.seen else ""
        checked = {"pins": "pins checked", "deep": "lineage checked"}.get(node.checked, "made before pins were checked")
        tagged = f", tagged {', '.join(node.tags)}" if node.tags else ""
        stood = "; your build stands in for the pinned snapshot, which the store does not have" if getattr(node, "stands_in", False) else ""
        return f"{node.label}: {node.pipeline} {node.commit[:7]}{tagged}, made {made}, {checked}{seen}{stood}"
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
    help="Build, then make a snapshot: refuse to build with anything uncommitted but chartbook.lock, and fail unless the build ends with a snapshot",
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
@click.option(
    "--complete",
    is_flag=True,
    help="With --snapshot: keep the snapshot complete, every file of it in one folder of the store, as `chartbook snapshot --complete` does",
)
@click.option("--no-gc-reminder", is_flag=True, help="After a snapshot, do not say what `chartbook store gc` would clear")
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    help="Run nothing: check the manifest and the folder, and exit 1 on any problem. For CI. An output that is not built is listed, and is no problem",
)
@click.option(
    "--within",
    "within_days",
    type=click.IntRange(min=0),
    default=None,
    metavar="DAYS",
    help="With --check: fail on licenses that expire within this many days (default: 30)",
)
@click.option(
    "--policy",
    "policy_path",
    type=click.Path(),
    default=None,
    help="With --check: check required fields against the [policy] of this catalog (its catalog.toml, or its folder) instead of the pipeline's own",
)
def run_command(script, project_dir, force, make_snapshot, frozen, remake, upstream, complete, no_gc_reminder, check_only, within_days, policy_path):
    """Build this pipeline: pin what it reads, run its build, look for what it made.

    \b
    What `chartbook run` does, in order:
      1. Pins whatever this pipeline depends on and has not pinned yet,
         so that its code can read it.
      2. Runs the `build` script of chartbook.toml.
      3. Looks for what chartbook.toml declares. Something with a path
         that the build did not write, or the file of a DuckDB source,
         fails the run.

    It makes no snapshot, which is what other pipelines read of this one
    and what the catalog shows: its last lines name the command that
    does, `chartbook snapshot`, typed once the work is committed.

    SCRIPT is a name from [scripts] in chartbook.toml, `build` unless you
    name another. Another script is only run: nothing is pinned for it or
    looked for after it.

    \b
        [scripts]
        build = "doit"
        test = "pytest"

    A pin that exists is never moved: you are told what has changed, and
    `chartbook pin --update` moves pins.

    It never builds in a folder this pipeline depends on, unless you say
    --upstream (below). That folder is somebody's work, and this pipeline
    reads what is pinned, not what is there.

    A dependency that is a git repository is built once, in ChartBook's own
    clean copy of the commit, so that what it builds can be pinned. --force
    builds it again, which is how data it pulls from outside is refreshed.

    Run this in a pipeline. A catalog lists stored snapshots and runs no code.

    --snapshot is the build and a snapshot in one command, for a script
    that must end with one. It refuses to build with anything uncommitted
    but chartbook.lock, which its own pin is about to write, and where the
    catalog says the store its snapshot goes to may only be read; and it
    fails where no snapshot can be made. Its snapshot records that the
    build ran in the same command. With --complete the snapshot is kept
    complete, as `chartbook snapshot --complete` keeps one.

    \b
    Examples:
        chartbook run
        chartbook run test
        chartbook run --force
        chartbook run --snapshot
        chartbook run --snapshot --complete
        chartbook run --frozen
        chartbook run --upstream
        chartbook run --check
        chartbook run --check --within 90 --policy ../catalog

    --check runs nothing. It checks the manifest and the folder, in
    seconds, and exits 1 on any problem: a field the policy requires that
    is missing, a write-up or a note that is not there, a dependency that
    cannot be found, a license that has expired or will within --within
    days. An output that is not built is listed and is no problem, since a
    checkout that has not been built is no mistake. For CI: what a run
    checks of its own build, a run checks; this asks for more (a policy,
    a license's date) and builds nothing. Whether what is pinned is in the
    store is `chartbook pin --check`.

    --frozen pins nothing, and writes nothing before
    the build but, where the store can be written, its note that this
    machine reads these pins: not the lockfile, no object, and no git
    dependency is fetched or built. The build runs only if the lockfile is
    complete and every pin is in the store (`chartbook pin --check` says
    the same without building). For CI, and for a store you may only read.

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
    if not check_only:
        _say_if_the_skill_is_stale()
    if check_only:
        with_it = [
            name for name, given in (
                (f"a script ({script})", script != "build"), ("--force", force), ("--snapshot", make_snapshot),
                ("--frozen", frozen), ("--remake", remake), ("--upstream", upstream), ("--complete", complete),
                ("--no-gc-reminder", no_gc_reminder),
            ) if given
        ]
        if with_it:
            raise click.UsageError(
                f"--check runs nothing, so it does not go with {', '.join(with_it)}. It takes --within, --policy and --project-dir."
            )
        return _check_pipeline(project_dir, 30 if within_days is None else within_days, policy_path)
    if within_days is not None or policy_path is not None:
        raise click.UsageError("--within and --policy go with --check: `chartbook run --check --within 90`.")
    if complete and not make_snapshot:
        # A run makes no snapshot unless it is asked for one, so there is none to keep complete
        raise click.UsageError("--complete goes with --snapshot: `chartbook run --snapshot --complete`.")
    project_dir = resolve_project_dir(project_dir)
    if _is_catalog_folder(project_dir):
        raise click.ClickException("A catalog lists stored snapshots. Run `chartbook run` in a pipeline, or orchestrate pipelines with doit.")
    from chartbook.manifest import BUILD_SCRIPT

    # Not for arguments the run refuses anyway: it says why, and nothing is recorded
    refused = (frozen and (make_snapshot or upstream)) or ((frozen or make_snapshot or upstream) and script != BUILD_SCRIPT)
    if not refused:
        _ask_before_running(project_dir, script, may_render=False, upstream=upstream)
    _run_script(
        project_dir,
        script,
        force=force,
        # Told nothing, a build makes no snapshot: its last line names the command that does
        snapshot=make_snapshot,
        frozen=frozen,
        remake=remake,
        upstream=upstream,
        no_gc_reminder=no_gc_reminder,
        complete=complete,
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
    for asset, why in getattr(report, "not_hashed", ()):
        click.echo(f"  rows not hashed: {asset} ({why}). A pin of it is met by the same file, and by no rebuild.")
    for asset, why in getattr(report, "not_hashed_now", ()):
        click.echo(
            f"  rows not hashed this time: {asset} ({why}). Its bytes are in the snapshot; "
            f"`chartbook snapshot` again hashes its rows."
        )
    if getattr(report, "rows_first_said", None) is not None and report.made:
        # Made of the same files as one already here, for what that one does not say: an owner who
        # has just upgraded sees why a build that changed nothing has a new snapshot
        count = getattr(report, "rows_first_count", 0)
        click.echo(
            f"  The same files as the snapshot made {_when(report.rows_first_said.made_at)}, which says nothing of "
            f"the rows of {count} dataframe{'' if count == 1 else 's'}: this one records them, so that a rebuild can "
            f"meet a pin of {'it' if count == 1 else 'them'}."
        )
    if getattr(report, "not_whole", None) and report.made:
        # Made of the same files as one already here, because that one lacks a file of its own in the store:
        # the one it is made in, or another this run sends it to, which is then named
        holed, files, where = report.not_whole
        more = f" and {len(files) - 1} more" if len(files) > 1 else ""
        there = f" at {_printable(str(where))}" if where is not None else ""
        click.echo(
            f"  The same files as the snapshot made {_when(holed.made_at)} ({holed.path.parent.parent.name}), which "
            f"lacks {_printable(files[0])}{more} in the store{there}: this one is whole, and that one is left as it is."
        )
    if getattr(report, "rows_said", None):
        # Each dataframe whose file changed, beside the snapshot before this one
        # Named by its commit too: the one before may be of another branch, and its rows are then another's
        click.echo(
            f"  Beside the snapshot before it, of {report.rows_beside.commit[:7]}, made {_when(report.rows_beside.made_at)}:"
        )
        for asset, told in report.rows_said:
            click.echo(f"    {asset}: {told}")
    for asset in getattr(report, "index_columns", ()):
        from chartbook import rowhash

        click.echo(f"  {asset}: {rowhash.index_column_said(getattr(report, 'index_column_names', {}).get(asset) or ())}.")
    if report.index_skipped:
        click.echo(
            f"  index not recorded: {report.index_skipped}. The bytes and the documents are in the "
            f"store; `chartbook run --check` says what a docs build would refuse."
        )
    for path, why in report.documents_skipped:
        shown = path if path.isprintable() else ascii(path)  # a name may carry what a terminal would act on
        click.echo(f"  document not kept: {shown} ({why})")
    for model, label in report.skipped_labels:
        click.echo(
            f"  label not recorded: {model} {label!r}. A label is letters, digits, '.', "
            f"'_' and '-', does not read as a hash, and names a version by twelve or more "
            f"of its digits; `chartbook run --check` says the same."
        )
    kept = getattr(report, "kept", None)
    if report.made:
        # How the store keeps it, as the report has it: complete, or as an increment on an earlier one
        how, sizes, rest = _kept_said(kept)
        made = f"Snapshot made{', kept ' + how if kept is not None and kept.increment else ''}{': ' + sizes if sizes else ''}"
        click.echo(f"{made}, for what depends on it in this run to pin.{rest}" if upstream else f"{made}.{rest}")
    else:
        click.echo(
            f"No new snapshot: the same bytes and the same pins as the one made {_when(taken.made_at)}."
        )
    if getattr(report, "asked_complete", False) and kept is not None and kept.folder is not None:
        # Asked for a complete one, to look at or to hand on: where it is
        click.echo(f"  {_printable(kept.folder)}")
    elif report.made and not upstream:
        click.echo("A pipeline that depends on this one gets it with `chartbook pin --update`.")
    for name, other in getattr(report, "kept_otherwise", ()):
        # Each store decides for itself: one that keeps it the other way is named
        how, sizes, rest = _kept_said(other)
        click.echo(f"Store {_printable(name)} keeps it {how}: {sizes}.{rest}")

    if getattr(report, "stores", None) and getattr(report, "several", False):
        click.echo("Stores: " + ", ".join(report.stores))


def _kept_said(kept) -> tuple:
    """How a store keeps a snapshot (:class:`chartbook.snapshot.Kept`), in the words of the lines that say one was made: how, its files and their size, and the sentence that follows.

    ``("complete", "5 files, 23.0 MB", "")``, or ``("as an increment", "2
    of 5 files, 409.6 KB", " The rest is in the snapshot made 2026-11-16
    09:15 UTC.")``. A count of files is of the files the record lists.
    Where the record of what an increment builds on could not be read for
    its time, no blank date is printed: "The rest is in the snapshot it
    builds on."
    """
    if kept is None:
        return "", "", ""
    files = "1 file" if kept.files == 1 else f"{kept.files} files"
    if kept.increment:
        rest = f"made {_when(kept.rest_made_at)}" if kept.rest_made_at else "it builds on"
        return (
            "as an increment", f"{kept.own_files} of {files}, {_format_bytes(kept.own_bytes)}",
            f" The rest is in the snapshot {rest}.",
        )
    added_up = " The increments since the last complete one had added up to its size." if kept.added_up else ""
    return "complete", f"{files}, {_format_bytes(kept.size_bytes)}", added_up


def _offer_to_add(project_dir, report, strict, frozen, added):
    """After a build that stopped on a read of a pipeline its manifest does not declare: offer to declare it; the ID added, or None.

    Asked only where yes can work (``docs_src/design/one-command.md``): a
    person is there to answer; the run is a plain one, not ``--frozen``
    (which writes nothing) nor ``--snapshot`` (which a manifest just
    changed cannot end in); the read was made from this pipeline's own
    folder; and the stores have exactly one pipeline of that name. A name
    two pipelines share, or one the stores do not have (a folder or a
    repository, which is declared by hand), is left to the build's own
    error, as before. Yes does what `chartbook add` does.

    :param added: The IDs added before in this command: one is never
        asked of twice, so that a build that goes on failing ends.
    """
    if not report.undeclared or strict or frozen or report.failed is None or report.failed.source != "asked":
        return None
    if not _can_ask():
        return None
    from chartbook.snapshot import SnapshotError, pipeline_in, readable_snapshots
    from chartbook.store import StoreError

    from chartbook.snapshot import repository_groups

    asked = report.undeclared[0]
    try:
        try:
            itself = pipeline_in(project_dir)
        except (SnapshotError, ValueError):
            itself = None
        stored = _StoredIds(project_dir)
        every = readable_snapshots(stored._stores())[0]  # the stores are read once, for the name and for the line
        stored._ids = sorted({one.pipeline for one in every})
        found = (asked if asked in stored.ids else None) if "/" in asked else _bare_name_in_stores(asked, stored, itself)
        if found is None or found == itself or found in added:
            return None
        taken = [one for one in every if one.pipeline == found]
        if len(repository_groups(taken)[0]) > 1:
            # Two repositories claim the ID: which is meant is said by hand (`repository = "..."`), and a
            # bare entry could not be pinned
            return None
        newest = max(taken, key=lambda one: one.made_at)
    except (ValueError, StoreError, OSError):
        return None  # none of that name, or several, or a store that cannot be read: the build's error says the rest
    count = "1 snapshot" if len(taken) == 1 else f"{len(taken)} snapshots"
    click.echo(f"{report.failed.id}: its code reads from a pipeline that chartbook.toml does not declare:", err=True)
    click.echo(f"  {found}   (in your store: {count}, the newest of {newest.commit[:7]})", err=True)
    try:
        agreed = _confirm("Add it to [dependencies] and build again?", default=True)
    except click.Abort:  # Ctrl-C, or the end of input
        click.echo("", err=True)
        return None
    if not agreed:
        return None
    _add_dependency(project_dir, found)
    return found


def _in_its_folder(folder) -> str:
    """`` --project-dir FOLDER`` for a pipeline that is not in the folder the command was typed in, to follow a command a message names; else empty.

    Quoted as this system's shell takes it, as the list of what is not in
    a store quotes a folder, so that the command can be pasted.
    """
    import os

    from chartbook.missing import _quoted

    try:
        if os.path.samefile(folder, Path.cwd()):  # however either is spelled
            return ""
    except OSError:
        pass
    return " --project-dir " + _quoted(folder)


def _run_script(
    project_dir, script, force=False, snapshot=False, frozen=False, remake=False, remake_command="chartbook run --remake",
    upstream=False, no_gc_reminder=False, added=(), complete=False,
):
    """Run a named script as `chartbook run` does; exit with its code if it fails.

    :param added: The dependencies this command has added to the manifest
        at the person's yes (:func:`_offer_to_add`), before running again.
    :param complete: With *snapshot*: keep the snapshot complete (``--complete``).
    """
    from chartbook import lock
    from chartbook import run as runner
    from chartbook.store import StoreError

    def show_pins(step, pins):
        # Said only when there is something to say: a pin that is not
        # simply still in place, or a lockfile that was written
        quiet = ("kept", "not_built")  # as they were the last time
        if step.source == "git":
            # ChartBook's own copy of a dependency: its lockfile goes nowhere, and its manifest is nobody's to write here
            pins.floor = None
        # What is on the list of what is not in the store is said there, once the run has stopped
        listing = getattr(pins, "not_in_store", None)
        listed = listing.keys if listing is not None else set()
        if pins.written or any(event.status not in quiet and event.dependency not in listed for event in pins.events):
            click.echo(f"{step.id}: pinning what it depends on")
            _echo_pin_report(pins, listed=listed)
        elif getattr(pins, "floor", None) is not None:
            # Nothing of the pins to say, and a manifest that admits a ChartBook which cannot read the
            # lockfile: a run writes no manifest, and says each time which command does
            from chartbook.check import display_path

            shown = display_path(pins.floor.manifest, relative_to=Path.cwd())
            click.echo(f"{step.id}: {lock.floor_said(pins.floor, shown, pins.lockfile.name, lock.where_to_pin(pins.floor))}")

    try:
        report = runner.run(
            project_dir,
            script,
            echo=click.echo,
            on_pin=show_pins,
            force=force,
            snapshot=snapshot,
            on_snapshot=lambda step, made: (
                _echo_snapshot(made, upstream=step.snapshot_first),
                None if step.snapshot_first else _remind_of_gc(no_gc_reminder, pipeline=step.id),
            ),
            frozen=frozen,
            on_verify=_echo_frozen_report,
            remake=remake,
            remake_command=remake_command,
            upstream=upstream,
            complete=complete,
        )
    except (runner.RunError, lock.LockError, StoreError, ValueError, OSError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _explain_os_error(e), err=True)
        raise SystemExit(1)

    if report.failed is not None:
        now_declared = _offer_to_add(project_dir, report, strict=snapshot, frozen=frozen, added=added)
        if now_declared is not None:
            # Declared and pinned: the build again, which asks again if its code reads another. Not
            # --force a second time: what it rebuilds was rebuilt a moment ago, before the build that stopped
            return _run_script(
                project_dir, script, force=False, snapshot=snapshot, frozen=frozen, remake=remake,
                remake_command=remake_command, upstream=upstream, no_gc_reminder=no_gc_reminder,
                added=(*added, now_declared), complete=complete,
            )
        if report.not_in_store is not None:
            from chartbook import missing

            # The command to come back with, as it was typed
            again = "chartbook run" + "".join(
                f" {flag}" for flag, given in (
                    ("--force", force), ("--snapshot", snapshot), ("--complete", complete), ("--remake", remake),
                    ("--upstream", upstream),
                ) if given
            )
            for line in missing.said(report.not_in_store, again=again):
                click.echo(line, err=True)
            if report.reason == runner.NOT_IN_STORE:
                raise SystemExit(report.exit_code or 1)  # the list has said it
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"{report.failed.id}: {report.reason}. Nothing after it was run.",
            err=True,
        )
        raise SystemExit(report.exit_code or 1)
    click.echo(f"Ran {script} in {len(report.ran)} pipeline(s).")
    if report.snapshots:
        # Once the run is over, for the catalog that shows them: a run makes one only where it was asked to
        _say_where_a_snapshot_shows()
    # A run makes no snapshot of what it was asked to build, in whatever state the folder is: said
    # last, where it is seen, and the same every time, with no look at git or at the store. Most runs
    # are of work that is not committed yet, so it always says to commit; and the catalog shows only
    # snapshots, so it names the catalog too. Not under --frozen, which is for CI and for a store one
    # may only read: a snapshot is not what comes next there
    for step in () if frozen else report.to_snapshot:
        click.echo(f"{step.id}: built.")
        if step.id in report.not_noted:
            # A snapshot of it would be refused, for git's trust and then for the note this build could
            # not leave: what to do first is said, and the run after it names the command that makes one
            click.echo(f"  No note of this build was kept: {report.not_noted[step.id]}.")
            continue
        click.echo(
            f"  For other pipelines and the catalog: commit, then `chartbook snapshot{_in_its_folder(step.directory)}`."
        )


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
    """Look after the named stores that keep pinned files and snapshots.

    Define stores in catalog.toml under [stores]. Each is a folder, local
    or shared (a store in a bucket is not available in this version, and a
    command that meets one says so). CHARTBOOK_STORE selects the process's only
    store. Without catalog stores, [store] url in user or system settings
    is the fallback, then ~/.chartbook/store. `chartbook store info` lists
    the configured stores; --store NAME selects one for maintenance.
    """


@store.command("ls")
@click.argument("pipeline", required=False)
@click.option("--store", "store_name", help="List one named catalog store")
def store_ls(pipeline, store_name):
    """List the snapshots in the store, and how much each one's folder holds.

    One line per snapshot, newest last within its pipeline: when it was
    made, its commit, how the store keeps it, and how much its folder
    holds. A complete snapshot's folder holds every file of its version,
    and can be read or copied as it is. An increment's folder holds the
    files that the complete snapshot it builds on does not have; the rest
    are in that one's folder. A snapshot is removed with `chartbook store
    gc`, never by hand.

    The size is the one a snapshot's record gives, each file counted once
    however many of its assets name it. Where files its record
    names are not in the store, or not at their size, its line says how
    many of how many it lacks, and `chartbook store verify` names each.

    A store that ChartBook 0.5 laid out keeps each file once:
    there an increment's other files may be in several snapshots' folders.

    \b
    Examples:
        chartbook store ls
        chartbook store ls acme/news_headlines
        chartbook store ls --store team
    """
    from chartbook.store import FolderStore, StoreError, StoreUnreachableError

    try:
        stores = _stores_to_list(store_name)
    except (ValueError, OSError, StoreError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    shown = unreachable = unread = failed = 0
    said_complete = said_shared = said_lacking = False
    for name, the_store, reachable in stores:
        records = getattr(the_store, "records", None)
        if records is None:
            continue  # a store of a kind that keeps no folders to list
        label = f"Store {name}: {the_store}" if name else f"Store: {the_store}"
        if not reachable:
            # A folder store that is not there lists nothing, which is not "no snapshots" (a Drive not mounted)
            click.echo(f"{label}: unreachable", err=True)
            unreachable += 1
            continue
        try:
            every = list(records())
            found = [r for r in every if r.readable and (pipeline is None or r.pipeline == pipeline)]
        except (StoreUnreachableError, OSError) as error:
            click.echo(f"{label}: unreachable ({_said(error)})", err=True)
            unreachable += 1
            continue
        except StoreError as error:
            click.echo(f"{label}: not read ({_said(error)})", err=True)
            failed += 1
            continue
        found.sort(key=lambda r: (r.pipeline, r.made_at))
        if len(stores) > 1 or name:
            click.echo(f"Store {name or the_store}: {the_store}" if name else f"Store: {the_store}")
        # A record this ChartBook cannot read is not listed, and is not passed over in silence: one a
        # later ChartBook wrote says so, and how to get that one
        from chartbook import snapshot as snapshots
        from chartbook.store import pipeline_folder

        for record in every:
            if record.readable or (pipeline is not None and record.folder.parent.name != pipeline_folder(pipeline)):
                continue
            try:
                snapshots.read(record.path)
                why = f"the snapshot record {record.path} is not where a record of what it says is kept"
            except snapshots.SnapshotError as error:
                why = _said(error)
            click.echo(f"  not listed: {why}", err=True)
            unread += 1
        current = None
        asked: dict = {}  # what the disk said of each file of this store: one that several snapshots name is asked about once
        for record in found:
            if record.pipeline != current:
                current = record.pipeline
                click.echo(f"{current} ({sum(1 for r in found if r.pipeline == current)} snapshot(s))")
            here, elsewhere = _held_here_and_elsewhere(record)
            # Its record names files in another snapshot's folder: the one it builds on, or, as 0.5 wrote
            # one, any earlier ones
            kind = "increment" if record.increment or elsewhere else "complete"  # by what its record is
            said_shared = said_shared or bool(elsewhere)
            said_complete = said_complete or kind == "complete"
            note = "" if elsewhere == 0 else f", {elsewhere:,} file(s) in {record.builds_on or 'other folders'}"
            if record.made_by != "snapshot":
                note += ", pinned from a clone of its repository"  # not one its owner made
            # The size is its record's. What its record names and is not where it says, by sizes as every
            # ordinary question of the store is asked, is said in the same words of either kind
            lacking = _files_it_lacks(the_store, record, asked)
            if lacking:
                note += f", lacks {lacking[0]:,} of its {lacking[1]:,} file(s)"
                said_lacking = True
            made = f"{record.made_at[:10]} {record.made_at[11:16]} UTC"
            click.echo(f"  {record.folder.name}  {made}  {record.commit[:7]}  {kind:<10} {_format_bytes(here)} here{note}")
            shown += 1
    if not shown:
        said = "No snapshots" if pipeline is None else f"No snapshot of {pipeline}"
        if unread:
            said += " that this ChartBook can read"
        click.echo(f"{said} in the stores that could be read." if (unreachable or failed) else f"{said}.")
        for name, the_store, reachable in stores:
            root = getattr(the_store, "root", None)
            own = getattr(the_store, "is_users_own", None)
            if reachable and root is not None and not root.is_dir() and not (callable(own) and own()):
                # A store is made by its first snapshot; a synced folder not mounted lists nothing either
                click.echo(f"The store's folder {root} is not there: not made yet, or a synced folder that is not mounted.")
        if failed or (unreachable and unreachable + failed == len(stores)):
            raise SystemExit(1)
        return
    if said_complete or said_shared:
        # One line: the store's README says how snapshots are removed
        click.echo("A complete snapshot's folder holds every file of its version; an increment's holds what the one it builds on does not.")
    if said_lacking:
        click.echo("What a snapshot lacks is a file its record names that is not in the store, or not at its size: `chartbook store verify` names each one.")
    if failed:
        # A store that is there and cannot be read is a failure, even when another store listed snapshots.
        # One that is not mounted is said above and does not, on its own, fail a listing that showed the rest.
        raise SystemExit(1)


def _held_here_and_elsewhere(record) -> tuple:
    """For `store ls`: how many bytes a snapshot's record says its own folder holds, and how many of its files are kept in another snapshot's folder.

    A file is counted once, however many of the record's assets name it:
    a pipeline that declares a folder as one asset and a folder inside it
    as another lists the inner files under both, and the size summed over
    every entry of every asset was twice the folder's (58.1 GB said of a
    folder that holds 25.9). The size is of the places in its folder,
    each once, which is what the folder holds on disk; the count is of the
    names kept elsewhere, each once, as the snapshot's closing line counts
    files (:func:`chartbook.snapshot._files_listed`).
    """
    here = 0
    places: set = set()
    elsewhere: set = set()
    for asset in record.assets:
        for file in asset.files:
            if not file.location.is_relative_to(record.folder):
                elsewhere.add(file.path)
            elif file.location not in places:
                places.add(file.location)
                here += file.size_bytes
    return here, len(elsewhere)


def _files_it_lacks(the_store, record, asked: dict):
    """For `store ls`: how many files a snapshot's record names that are not where it says, and how many it names in all; None where it lacks none.

    By sizes, with nothing read (:meth:`chartbook.store.Store.holes_of`),
    of a complete snapshot and of an increment alike: an increment's
    files are in two folders, and one missing from either is one it lacks.
    A store that cannot say (another kind, or a record it cannot follow
    now) says nothing here, and `store verify` is what checks a store.

    Both numbers are of the names the snapshot's record lists: a
    snapshot's files are its names. The store asks about a place once and
    says it once, under one of the names the record has for it; where a
    record keeps two names at one place (a store of ChartBook 0.5 kept
    two files of the same bytes once) and that place is missing, the
    snapshot lacks two files, and that is the number here. `store verify`
    says the place once, since its lines are of places in the store.

    :param asked: What the disk has said of each file of this store so
        far in the listing, which the store adds to: twenty snapshots
        that name the same files ask about each file once, not twenty
        times, and on a synced folder each question is a trip.
    """
    from chartbook.store import StoreError

    holes_of = getattr(the_store, "holes_of", None)
    try:
        holes = list(holes_of(record.path, asked)) if callable(holes_of) else []
    except (OSError, ValueError, StoreError):
        return None
    if not holes:
        return None
    names_at: dict = {}  # each place the record keeps a file at, with every name it has for the file there
    places_of: dict = {}  # and where each name is kept
    for asset in record.assets:
        for file in asset.files:
            names_at.setdefault(file.location, set()).add(file.path)
            places_of.setdefault(file.path, set()).add(file.location)
    lacked: set = set()
    for hole in holes:
        if hole in places_of:
            for place in places_of[hole]:
                lacked |= names_at[place]
        else:
            lacked.add(hole)  # what its record names without saying where it is: no place, and one file
    return len(lacked), len(lacked | set(places_of))


def _stores_to_list(store_name):
    """The stores a listing command looks in, each with its name and whether it can be reached: one named catalog store, or every configured one, or the default."""
    import os

    from chartbook.config import get_default_catalog_path
    from chartbook.multi_store import Stores
    from chartbook.store import default_store

    if store_name or (not os.environ.get("CHARTBOOK_STORE") and get_default_catalog_path() is not None):
        configured = Stores.configured()
        if configured is not None and (configured.catalog is not None or store_name is not None):
            # An unreachable store is listed too, and said to be unreachable
            entries = [configured.named(store_name)] if store_name else configured.entries
            return [(entry.name, entry.store, entry.reachable) for entry in entries]
        if store_name:
            raise ValueError(f"--store {store_name}: no catalog names stores on this machine (`chartbook store info` says what it uses).")
    the_store = default_store()
    entries = getattr(the_store, "entries", None)
    if entries is not None:  # several stores read as one: each listed by its name
        return [(entry.name, entry.store, entry.reachable) for entry in entries]
    return [("", the_store, True)]


def _remind_of_gc(silenced: bool, pipeline: "str | None" = None) -> None:
    """One line on stderr when `chartbook store gc` would clear snapshots; nothing is removed unless asked.

    After `chartbook snapshot`, `chartbook run --snapshot` and `chartbook catalog build`, the
    commands that grow the store or read all of it: a store that nobody
    ever clears grows without bound, and this is where a person learns the
    command. After a snapshot of one pipeline, the line is of that pipeline
    only (*pipeline*). After a catalog build it is of the whole store. The
    plan is the one gc makes, read-only, and made to look at no file of the
    store: it goes by the records alone (:func:`_what_gc_would_clear`); a
    store that cannot be read says nothing, since a reminder never fails a
    command.
    """
    if silenced:
        return
    try:
        from chartbook.multi_store import Stores
        from chartbook.store import default_store

        the_store = default_store()
        if isinstance(the_store, Stores):
            # gc works in one store at a time: each of the catalog's that it could clear, by its name
            named = [(entry.name, entry.store) for entry in the_store.entries if not entry.read_only and entry.reachable]
        else:
            named = [(None, the_store)]
        said = []
        for name, one in named:
            clearable = _what_gc_would_clear(one, pipeline=pipeline)
            if clearable and name is not None:
                clearable = f"Store {name}: " + clearable.replace("`chartbook store gc`", f"`chartbook store gc --store {name}`", 1)
            if clearable:
                said.append(clearable)
    except Exception:  # noqa: BLE001 - a reminder never fails the command it follows
        return
    for clearable in said:
        click.echo(clearable + " Nothing is removed unless you ask (`--no-gc-reminder` silences this line).", err=True)


@store.command("info")
@click.option("--store", "store_name", help="Show one named catalog store")
def store_info(store_name):
    """List configured stores, their reachability and snapshot counts.

    CHARTBOOK_STORE overrides the catalog's [stores]. Without catalog
    stores, user and system settings supply the fallback, then the default.
    Use --store NAME to inspect one named store.

    \b
    Examples:
        chartbook store info
        CHARTBOOK_STORE=/shared/store chartbook store info
    """
    from chartbook.multi_store import Stores
    try:
        import os
        from chartbook.config import get_default_catalog_path
        configured = Stores.configured() if store_name or (not os.environ.get("CHARTBOOK_STORE") and get_default_catalog_path() is not None) else None
        if configured is not None and (configured.catalog is not None or store_name is not None):
            from chartbook.snapshot import readable_snapshots
            entries = [configured.named(store_name)] if store_name else configured.entries
            refused = False
            for entry in entries:
                status = "read-only" if entry.read_only else "writable"
                if not entry.reachable:
                    status += ", unreachable"
                click.echo(f"Store {entry.name}: {entry.store} ({status})")
                if entry.reachable:
                    from chartbook.store import FolderStore, StoreError, StoreUnreachableError

                    if isinstance(entry.store, FolderStore):
                        _say_how_long_paths_are(entry.store.root)
                    try:
                        found, unreadable = readable_snapshots(entry.store)
                    except (StoreUnreachableError, OSError) as error:
                        click.echo(f"  Unreachable: {error}")
                        continue
                    except StoreError as error:  # a layout this version does not read, or two in one folder
                        click.echo(f"  Not read: {_said(error)}")
                        refused = True
                        continue
                    counts = {}
                    for taken in found:
                        counts[taken.pipeline] = counts.get(taken.pipeline, 0) + 1
                    for pipeline, count in sorted(counts.items()):
                        click.echo(f"  {pipeline}: {count} snapshot(s)")
                    if found:
                        click.echo(f"  Newest: {found[-1].made_at}")
                    if unreadable:
                        click.echo(f"  {len(unreadable)} unreadable record(s)")
                    clearable = _what_gc_would_clear(entry.store)
                    if clearable:
                        if len(configured.entries) > 1:
                            clearable = clearable.replace("`chartbook store gc`", f"`chartbook store gc --store {entry.name}`", 1)
                        click.echo(f"  {clearable}")
                if entry.pipelines:
                    click.echo("  Routed: " + ", ".join(entry.pipelines))
            if refused:
                raise SystemExit(1)  # one of them is a store this version does not read, or has two layouts in it
            return
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None

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
    # The store of that kind, as the first pin or read would make it: one that is not available in this
    # version (a bucket), or of a kind nothing provides, is said here, and not only then
    from chartbook.store import StoreError

    try:
        store_for_url(url)
        not_usable = None
    except (ValueError, StoreError) as e:
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
    if folder is None or folder.exists():
        from chartbook.store import StoreError

        try:
            the_store = store_for_url(url)
            if folder is not None:
                # Asked which layout it has: one this version does not read, or two in one folder, is said here too
                the_store.earlier_layout()
            clearable = _what_gc_would_clear(the_store)
        except StoreError as e:
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
            raise SystemExit(1)
        except (ValueError, OSError):
            clearable = None
        if clearable:
            click.echo(clearable)


def _what_gc_would_clear(the_store, pipeline: "str | None" = None) -> "str | None":
    """In a few words, what `chartbook store gc` would clear from a store; None when nothing, or when that cannot be told.

    The plan asks nothing of the disk about a snapshot's files
    (``looks=False``): it goes by the records alone. It walks no folder
    for what no snapshot uses, which is no part of the line; and it does
    not ask whether each snapshot that stays holds its files, which is
    what keeps a real gc from removing a pipeline's snapshots while one
    that stays lacks a file. Either asks about every file of many
    snapshots, at each snapshot of any pipeline, and a reminder removes
    nothing. So the line may count a snapshot that ``store gc`` would hold
    back; ``store gc --dry-run`` and the real one look, and are exact. A
    store a sweep would refuse still says nothing.

    :param pipeline: When set, only that pipeline's clearable snapshots
        (the line after ``chartbook snapshot`` of it). Whole-store ``store
        info`` and a catalog build leave it unset.
    """
    try:
        from chartbook import lock

        plan = lock.plan_gc(the_store, looks=False, pipeline=pipeline)
    except Exception:  # noqa: BLE001 - a store that cannot be planned for says nothing here; gc itself says why
        return None
    # A snapshot a pin made from a repository goes with gc too, with its own copy of every file
    cleared, pinned = len(plan.snapshots_delete), len(plan.pinned_delete)
    if not cleared and not pinned and not plan.delete:
        return None
    of = f" of {pipeline}" if pipeline else ""
    by_pins = f"{pinned} snapshot(s) a pin made from a repository, whose files no lockfile needs from them"
    if cleared:
        # With the snapshots' own copies of files that objects which stay have too: each snapshot is complete
        return (
            f"`chartbook store gc` would clear {cleared} snapshot(s){of}, freeing {_format_bytes(plan.freed_bytes)}: "
            f"older than {plan.keep_days:g} days, and neither pinned nor the newest of their pipeline"
            f"{f'; and {by_pins}' if pinned else ''}."
        )
    if pinned:
        return f"`chartbook store gc` would clear {by_pins}, freeing {_format_bytes(plan.freed_bytes)}."
    return f"`chartbook store gc` would clear {len(plan.delete)} object(s) nothing names, freeing {_format_bytes(plan.size_bytes)}."


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
    expected = max(longest, made, len(str(folder)) + len("\\snapshots\\") + 34 + 33 + 30)
    if expected < stores.WINDOWS_PATH_LIMIT - 20:
        return
    click.echo(
        click.style("Warning: ", fg="yellow", bold=True)
        + f"the store's folder is {len(str(folder))} characters long, and its paths reach about {expected}: Windows "
        f"refuses a path of {stores.WINDOWS_PATH_LIMIT} or more on this machine, where long paths are not turned on. "
        f"{stores.LONG_PATHS_REMEDY}.",
        err=True,
    )


def _move_from_0_5(the_store, dry_run: bool, yes: bool) -> None:
    """`chartbook store migrate` for a store that ChartBook 0.5 laid out, for one whose move was cut short, and for a moved one with what 0.5 keeps at its top: say what would happen, ask, move, and say what the whole move came to."""
    from chartbook import migrate_0_5
    from chartbook.store import FOLDER_SCHEMA, StoreError, this_machine

    def said_under(folders, most: int = 5) -> str:
        """Where files are, for a line: the folders they are under with how many each holds, the largest first, at most five, and how many folders more (:func:`chartbook.migrate_0_5.under`)."""
        folders = list(folders)
        named = ", ".join(f"{folder} ({count:,})" for folder, count in folders[:most])
        return named + (f" and {len(folders) - most:,} more" if len(folders) > most else "")

    def in_its_snapshot(path: str, before: int) -> str:
        """A file's path in its snapshot, from its path in the store: without the *before* folders that lead to the snapshot's own."""
        return path.split("/", before)[-1]

    def counts(found, verb: str) -> tuple:
        """What a move would do, or did, as lines in three lists: what is missing, which is said first; what is moved in; and the rest."""
        now = verb == "become"
        are = "are" if now else "were"
        aside = f"{migrate_0_5.LEFT_ASIDE}/"
        first = []
        if found.missing:
            # By snapshot, and before the other counts: folders that a sync never brought whole are one line each, not
            # thousands of names; and a person is to ask whether a sync is still at work before saying yes
            first.append(
                f"  {len(found.missing):,} file(s) that a record names are missing or of another size, as before the move, in "
                f"{len(found.missing_in):,} snapshot(s):"
            )
            first += [f"    {pipeline}/{snapshot}: {lacks:,} of {of:,} file(s)" for pipeline, snapshot, lacks, of in found.missing_in[:5]]
            if len(found.missing_in) > 5:
                first.append(f"    and {len(found.missing_in) - 5:,} more")
            # And which they are, by the folders they are under: three names of 58,325 said nothing, and less where a
            # file's name is a hash
            first.append(f"    under {said_under(migrate_0_5.under(path for _, _, path in found.missing))}")
            first.append(
                "  If a sync may still be bringing these files, wait for it to finish before the move: a file that arrives "
                "afterwards goes aside, and does not reach its snapshot. `chartbook store verify` lists every one."
                if now
                else "  `chartbook store verify` lists every one. A file that a sync brings now goes aside when `chartbook store "
                "migrate` is run again, and does not reach its snapshot."
            )
        moved_in = [
            f"  {found.complete:,} snapshot(s) {verb} complete ({found.by_pins:,} of them made by a pin), {found.increments:,} "
            f"{verb} increments on the newest of their pipeline.",
            f"  {found.renamed:,} file(s), {_format_bytes(found.renamed_bytes)}, {are} moved inside the store by rename: "
            f"nothing is copied or uploaded again for these.",
            f"  {found.copied:,} file(s), {_format_bytes(found.copied_bytes)}, {are} copied: each is in two folders that must each hold it."
            + (" In a synced folder every copied byte is uploaded again." if found.copied else ""),
        ]
        # Where the copies are much (a hundredth of the store, or 100 MB): what the store takes with them, and which
        # snapshots are given them, since one that is removed before the move is not copied
        if found.copied and (found.copied_bytes >= 100 * 1024 * 1024 or found.copied_bytes * 100 >= found.store_bytes):
            moved_in.append(
                f"  The store {'takes' if now else 'took'} {_format_bytes(found.store_bytes)} {'now' if now else 'before the move'}, "
                f"and {'will take' if now else 'takes'} {_format_bytes(found.store_after)}{'' if now else ' now'}. The copies "
                f"{'go' if now else 'went'} to {len(found.copied_into):,} snapshot(s), the largest first:"
            )
            moved_in += [f"    {pipeline}/{snapshot}: {_format_bytes(size)} in {files:,} file(s)" for pipeline, snapshot, files, size in found.copied_into[:5]]
            if len(found.copied_into) > 5:
                moved_in.append(f"    and {len(found.copied_into) - 5:,} more")
            if now:
                moved_in.append(
                    "  A snapshot that is removed before the move is not copied: `chartbook store gc` of ChartBook 0.5 removes "
                    "old ones (this version removes nothing from a store of 0.5)."
                )
        lines = [
            f"  What is left of pipelines/ {'goes' if verb == 'become' else 'went'} aside whole, under {aside}: its old records and "
            f"notes, and {found.aside:,} file(s) that no record names. Nothing is removed.",
        ]
        if found.doubled:
            lines.append(
                f"  {found.doubled:,} file(s) that a record names {'go' if verb == 'become' else 'went'} aside with the old folder "
                f"too: each is a second copy, or part of one, of bytes that {are} moved in from another place a record names."
            )
        if found.elsewhere:
            lines.append(
                f"  {found.elsewhere:,} file(s) {are} not where their record says, and {are} taken from where another "
                f"snapshot of their pipeline keeps the same bytes: under {said_under(found.elsewhere_under)}."
            )
        if found.no_record:
            named = ", ".join(f"{pipeline}/{folder} ({files:,} file(s))" for pipeline, folder, files in found.no_record[:3])
            lines.append(
                f"  {len(found.no_record):,} folder(s) {'hold' if verb == 'become' else 'held'} files and "
                f"{'have' if verb == 'become' else 'had'} no record: {named}{' and more' if len(found.no_record) > 3 else ''}. "
                f"The files in such a folder that a record names {are} moved with that record, and the rest "
                f"{'goes' if verb == 'become' else 'went'} aside. "
                + (
                    "If a sync may still be bringing a folder's record, wait for it and run this again: a record that "
                    "arrives after the move goes aside, and that snapshot has to be made again."
                    if verb == "become"
                    else "A record that a sync brings for one now goes aside when `chartbook store migrate` is run again, "
                    "and that snapshot has to be made again."
                )
            )
        if found.second_folders:
            # Named for a snapshot the store has the record of, in another folder: no record of its own is to be waited for
            named = ", ".join(
                f"{pipeline}/{folder} ({files:,} file(s); its record {'is' if verb == 'become' else 'was'} in {other})"
                for pipeline, folder, files, other in found.second_folders[:3]
            )
            lines.append(
                f"  {len(found.second_folders):,} folder(s) {'hold' if verb == 'become' else 'held'} files and no record, and {are} "
                f"named for a snapshot whose record {'is' if verb == 'become' else 'was'} in another folder: {named}"
                f"{' and more' if len(found.second_folders) > 3 else ''}. The files in such a folder that a record names {are} "
                f"moved with that record, and the rest {'goes' if verb == 'become' else 'went'} aside."
            )
        if found.not_pipelines:
            lines.append(
                f"  {len(found.not_pipelines):,} folder(s) under pipelines/ {are} named as no pipeline's folder is, and "
                f"{'go' if verb == 'become' else 'went'} aside whole with it: {', '.join(found.not_pipelines[:3])}"
                f"{' and more' if len(found.not_pipelines) > 3 else ''}. ChartBook 0.5 read no record in such a folder, and "
                f"nothing in it {'is' if verb == 'become' else 'was'} moved in."
            )
        if found.set_aside:
            named = ", ".join(f"{pipeline}/{snapshot}" for pipeline, snapshot in found.set_aside[:3])
            lines.append(
                f"  {len(found.set_aside):,} snapshot(s) {'go' if verb == 'become' else 'went'} aside without being moved in: {named}"
                f"{' and more' if len(found.set_aside) > 3 else ''}. Run that pipeline again with this ChartBook."
            )
        if found.second:
            named = ", ".join(f"{pipeline}/{folder}" for pipeline, folder in found.second[:3])
            lines.append(
                f"  {len(found.second):,} second record(s) of a snapshot that {'is' if verb == 'become' else 'was'} moved in "
                f"{'go' if verb == 'become' else 'went'} aside: {named}{' and more' if len(found.second) > 3 else ''}."
            )
        in_place = {pair[0] for pair in found.in_place}  # once: a set made for each file is the square of the files
        arrived = [path for path in found.late if path not in in_place]
        if arrived:
            # Each is where the old folder is kept, under its pipeline's and its snapshot's folders: five folders deep
            where = said_under(migrate_0_5.under(in_its_snapshot(path, 5) for path in arrived))
            lines.append(
                f"  {len(arrived):,} file(s) arrived for a snapshot that is moved already, and {'go' if verb == 'become' else 'went'} "
                f"aside with the old folder: under {where}. `chartbook store verify` names the snapshot that lacks each."
            )
        if found.in_place:
            where = said_under(migrate_0_5.under(in_its_snapshot(place, 3) for _, place, _, _ in found.in_place))
            other_size = sum(1 for _, _, there, here in found.in_place if here != there)
            lines.append(
                f"  {len(found.in_place):,} file(s) a record names {are} not moved, a file being where each goes already: under "
                f"{where}."
                + (f" {other_size:,} of them {are} not of the size of the file at the old place." if other_size else "")
                + f" What is in place stays, and the file at the old place {'goes' if verb == 'become' else 'went'} aside with "
                f"the old folder. `chartbook store verify` says whether what is in place is right."
            )
        if found.copied_as_is:
            where = said_under(migrate_0_5.under(in_its_snapshot(place, 3) for place in found.copied_as_is))
            lines.append(
                f"  {len(found.copied_as_is):,} file(s) were copied as they are, though their bytes are not what their records "
                f"say: under {where}. `chartbook store verify` says more."
            )
        return first, moved_in, lines

    root = the_store.root
    synced = "In a synced folder, let the sync finish before another machine uses the store."
    try:
        started = migrate_0_5.journal_of(root)
        migrate_0_5._check_before_plan(root)
        found = migrate_0_5.plan(root)
        migrate_0_5.check(root, found)
        moved = migrate_0_5.marker_of(root) == FOLDER_SCHEMA
        # Its old folder is aside, and store.json does not say so yet: a move cut short at its end, which is planned as a moved store is
        ended = not moved and migrate_0_5.is_moved(root)
        # The question is skipped only where this machine's own journal says a move is under way
        mine = started is not None and started.get("machine") == this_machine(create=False)
        if moved and started is None and not found.steps:
            # A moved store with nothing of 0.5 at its top and no journal: what is left to do is the move's own folder of
            # temporaries, which a run killed as it ended left. It is the move's own, and no question is asked
            click.echo(
                f"The store at {the_store} has this version's layout, and the folder a move keeps its own temporary files in "
                f"is still there ({migrate_0_5.MOVING}/): a move was cut short as it ended. "
                + ("It would be removed: nothing in it is a file of the store's." if dry_run else "It is removed: nothing in it is a file of the store's.")
            )
            if dry_run:
                click.echo("Nothing was moved.")
            else:
                migrate_0_5.run(root)
            return
        again = ", ".join(name + "/" for name in migrate_0_5.old_left(root))
        # No journal of this machine says whose move left its signs in a store of 0.5. One made on another machine and
        # finished there has none either, and a sync may have brought its folders before its store.json: said before
        # the question, as every other command says of such a store
        wait = "If another machine moved it, a sync may still be bringing the rest: wait for the sync to finish, and move nothing here."
        if mine and ended:
            click.echo(
                f"A move of the store at {the_store} to this version's layout was cut short at its end, its old folder "
                f"aside already: it is finished now."
                + (
                    f" What ChartBook 0.5 keeps at a store's top is there again ({again}): its notes are moved under "
                    f"_chartbook/, and pipelines/ goes aside whole: nothing under it is moved in."
                    if again else ""
                )
            )
        elif mine:
            click.echo(f"A move of the store at {the_store} to this version's layout was cut short: it goes on where it stopped.")
        elif moved:
            click.echo(
                f"The store at {the_store} has this version's layout, and at its top what ChartBook 0.5 keeps there "
                f"({again}). Its notes are moved under _chartbook/, and "
                f"pipelines/ goes aside whole: nothing under it is moved in."
            )
        elif ended:
            # The old folder is aside and store.json does not say the new layout: this machine's own move, cut short at
            # its end, where its journal says so (above). Without one it may as well be what a sync has brought so far
            # of another machine's move, and then what is at the top is this machine's whole store: the line does not
            # say that a move is finished, and says what a yes does
            click.echo(
                f"The store at {the_store} has the layout of ChartBook 0.5, and what a move to this version's layout puts "
                f"aside is there already ({migrate_0_5.LEFT_ASIDE}/), with no journal of a move on this machine. {wait} "
                f"If a move on this machine was cut short at its end, this finishes it."
                + (
                    f" What ChartBook 0.5 keeps at a store's top is there ({again}): a yes moves its notes under "
                    f"_chartbook/ and puts pipelines/ aside whole. Nothing under it is moved in, and a file there that a "
                    f"snapshot lacks does not reach it."
                    if again else ""
                )
            )
        elif migrate_0_5.new_there(root):
            click.echo(
                f"The store at {the_store} has the layout of ChartBook 0.5, and folders of this version's beside it: it "
                f"looks half moved, and the move goes on from the folders as they are. {wait} "
                f"{found.pipelines:,} pipeline(s), {found.snapshots:,} snapshot(s)."
            )
        else:
            click.echo(f"The store at {the_store} has the layout of ChartBook 0.5: {found.pipelines:,} pipeline(s), {found.snapshots:,} snapshot(s).")
        if not mine:
            first, moved_in, rest = counts(found, "become")
            for line in first + ([] if moved or ended else moved_in) + rest:
                click.echo(line)
        if dry_run:
            click.echo("Nothing was moved.")
            return
        if not mine:
            click.echo("Nothing else may use the store while this runs, on this machine or another.")
            click.echo("Afterwards every machine that uses it needs this ChartBook: an earlier one will not read it.")
            click.echo(synced)
            if not yes and not click.confirm("Move it?", default=False):
                click.echo("Nothing was moved.")
                return
        done = migrate_0_5.run(root)
    except StoreError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    except OSError as e:
        # A failure of the disk part way: every step done is done, and the rest is still to do
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"The move stopped: {_said(e)}. The store is as far as the move got, and nothing is lost: run "
            f"`chartbook store migrate` again, and it goes on.",
            err=True,
        )
        raise SystemExit(1)
    click.echo(f"The store at {the_store} has this version's layout: {done.pipelines:,} pipeline(s), {done.snapshots:,} snapshot(s).")
    first, moved_in, rest = counts(done, "became")
    # Where files are missing, the old folder is where to look before it goes: a sync's second copy of a snapshot's
    # folder (`<name> 2`) may hold what the first lacked, and the move reads no record of such a folder
    look_first = (
        f" {len(done.missing):,} file(s) are missing, and one may be in that folder (in a second copy of its snapshot's "
        f"folder, as a sync names one: `<name> 2`): look there first."
        if done.missing else ""
    )
    if not done.counted:
        # The journal carried what the move came to, and is gone (removed by hand, as two messages say to, once the old
        # folder was aside): the snapshots are counted from the folders, and what went with the journal is left out,
        # not said as 0
        lines = first + moved_in[:1] + [
            f"  How many files the move renamed, copied and put aside went with its journal, which is gone. The old folder "
            f"is under {migrate_0_5.LEFT_ASIDE}/: it may be removed once the move has been checked.{look_first}"
        ]
    else:
        # What this move moved in, by what its journal carries: a run that goes on after store.json was written says
        # the same as the one that was cut short would have. And after a move that ended before this run and left no
        # journal, the snapshots, renames and copies are not this run's to say
        lines = first + (moved_in if done.moved_in or not (moved or ended) else []) + rest
    for line in lines:
        click.echo(line)
    if done.kept:
        click.echo(f"The old folder, with its records, is kept at {done.kept}: it may be removed once the move has been checked.{look_first}")
    click.echo(synced)


@store.command("migrate")
@click.option("--dry-run", is_flag=True, help="Say what would be moved, and move nothing")
@click.option("--yes", "-y", is_flag=True, help="Do not ask")
def store_migrate(dry_run, yes):
    """Move a store to this version's layout: one that ChartBook 0.5 laid out, or one made by 0.2.

    A store of 0.5 (`pipelines/` at its top) is read as it is and not
    written. This moves it, once, on one machine: in each pipeline the
    newest snapshot its owner made becomes complete under `snapshots/`,
    the others it made become increments on it under `increments/`, and
    a snapshot a pin made becomes complete. Files change folder by rename,
    and a synced folder uploads nothing again for them. A file that two
    folders must each hold is copied, and uploaded again: that is much
    where older snapshots share files the newest does not have, so
    `--dry-run` says what the store will take, and a snapshot removed
    first (with `chartbook store gc` of ChartBook 0.5) is not copied. A
    file that is not where its record says is taken from where another
    snapshot of its pipeline keeps the same bytes; one that is missing is
    said first, by snapshot. What is not moved in goes aside under
    `_chartbook/left-by-0.5/`, never removed. Nothing else may use the
    store while it runs, and afterwards every machine that uses it needs
    this ChartBook. Cut short, it is run again and goes on.

    A store made by ChartBook 0.2 is moved to the layout of 0.5 by the
    first run of this command, and on to this version's by a second.

    A store in a bucket is not moved: it is not available in this
    version, and a command that meets one says so.

    \b
    Examples:
        chartbook store migrate --dry-run
        chartbook store migrate
    """
    from chartbook import migrate, migrate_0_5
    from chartbook.store import FolderStore, StoreError, default_store

    try:
        the_store = default_store()
    except (StoreError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not isinstance(the_store, FolderStore):
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + f"The store at {the_store} is not a folder, and this command moves a store in a folder.",
            err=True,
        )
        raise SystemExit(1)
    try:
        plan = migrate.plan(the_store.root)
    except StoreError as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        raise SystemExit(1)
    if not plan.needed and migrate_0_5.to_move(the_store.root):
        # A store of 0.5, a move to this layout that was cut short, or a moved store with what 0.5 keeps at its top
        _move_from_0_5(the_store, dry_run, yes)
        return
    if not plan.needed:
        try:
            # Asked of the store itself: one with two layouts in it is neither, and says so
            earlier = the_store.earlier_layout()
        except StoreError as e:
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
            raise SystemExit(1)
        if earlier:
            # What this command moves is a store of 0.2. One of 0.3 to 0.5 is read as it is, and is not this version's
            _move_from_0_5(the_store, dry_run, yes)
        else:
            click.echo(f"The store at {the_store} has the layout of this version already: nothing to move.")
        return
    left = len(plan.records) - plan.done
    if plan.layout == "chartbook/store/v2" and not plan.unfinished:
        click.echo(f"The store at {the_store} says it has the layout of ChartBook 0.3, and holds 0.2's folders too.")
    elif not plan.unfinished:
        click.echo(f"The store at {the_store} has the layout of ChartBook 0.2.")
    if not plan.unfinished:
        click.echo(
            f"Would move {left:,} snapshot(s) of {len(plan.records):,} into their pipelines' folders, from "
            f"{plan.objects:,} object(s), {_format_bytes(plan.size_bytes)}"
            + (f"; {plan.done:,} were moved by a migrate cut short" if plan.done else "")
            + "."
        )
    if plan.unowned:
        click.echo(f"{len(plan.unowned):,} object(s) no snapshot names go to pipelines/+unowned/, until no lockfile names them.")
    if plan.shared:
        click.echo(f"{plan.shared:,} object(s) two pipelines' snapshots share are copied for the second.")
    if plan.to_read:
        click.echo(f"{_format_bytes(plan.to_read)} of globs and documents is read once, to hash each file.")
    if plan.lost:
        click.echo(f"{plan.lost:,} asset(s) the store had lost already, in 0.2, are named by their records still, as they were.")
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
    click.echo("Run `chartbook store migrate` once more to move it on to this version's layout.")


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

    The folder is laid out as a store is: TO/snapshots/PIPELINE/, a folder
    for each complete snapshot, with its record; and, for each snapshot
    the store keeps as an increment, a folder under TO/increments/PIPELINE/
    with the files that the complete one it builds on does not have. The
    last line says which folder to send; whoever receives it runs
    `chartbook store import` on it.

    Every snapshot its owner made is written, or with --latest the newest
    alone, or each --snapshot named. One written without the snapshot it
    builds on is written complete, so --latest is one complete snapshot,
    readable without ChartBook. Only what a snapshot's record names is
    written: its data, its documents and its index, never anything that
    runs. With several stores in the catalog, the one that holds the
    pipeline is used; --store NAME chooses when more than one does.

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
    sent = Path(to).expanduser().resolve()
    # A snapshot kept as an increment has files in two folders of the export, snapshots/ and increments/: the
    # whole of it is then what to send. With complete ones alone, snapshots/ is all there is
    where = sent if (sent / "increments").is_dir() else sent / "snapshots"
    click.echo(f"Send {where}; `chartbook store import` there takes it in.")


@store.command("import")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def store_import(folder):
    """Copy the snapshots a folder holds into this machine's store.

    FOLDER is what `chartbook store export` wrote, a store, or one
    pipeline's folder from a store (its snapshots' folders, each with
    _chartbook/snapshot.json). Every file is hashed as it is copied and
    checked against its record: a snapshot with a file that is not what its
    record says is refused, and said. Each snapshot is written as it came,
    complete or as an increment on a complete one that is whole here, a
    snapshot the store has already is left as it is, and
    nothing in the store is written over. A pipeline in this store then
    pins the snapshots by the pipeline's ID, with `chartbook pin` and
    `chartbook pin --update`.

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

    In a folder store each snapshot is checked for itself: every file its
    record names is read in the snapshot's own folder, and every one that
    is missing there or has other bytes is said with the snapshot's name,
    though another snapshot has the same bytes. A file that snapshots kept
    as increments keep in the complete snapshot they build on is said
    once, under the name it has there, with that snapshot's name and how
    many of them keep it there.

    Ahead of the lines for each file comes what they add up to: how many
    files of how many snapshots, and one line for each such snapshot,
    with its pipeline, its folder's name and how many files. A folder
    files are missing from that has no record is said to be that, not a
    snapshot: `chartbook store ls` names the snapshots that lack them.

    A record that cannot be read is named on a line of its own, with why:
    nothing of its snapshot is checked.

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

    # A count for each snapshot first: the lines for each file run to thousands where a store has lost many,
    # and what they add up to was only to be had by counting them
    for line in _wrong_by_snapshot(the_store, problems):
        click.echo(line)
    for problem in problems:
        click.echo(problem.format())
    if problems:
        # A record that cannot be read is no object, and its snapshot's objects are not among those counted: said by itself
        unread = sum(1 for problem in problems if getattr(problem, "of_record", False))
        closing = []
        if unread < len(problems):
            # By object: one that two snapshots have each lost a file of is said twice above, and is one object
            wrong = len({problem.content_hash for problem in problems if not getattr(problem, "of_record", False)})
            closing.append(f"{wrong} of {total} object(s) in {the_store} are not what their names say.")
        if unread:
            closing.append(f"{unread} snapshot record(s) in {the_store} cannot be read.")
        click.echo("\n" + " ".join(closing), err=True)
        raise SystemExit(1)
    click.echo(f"{the_store}: OK ({total} object(s))")


def _wrong_by_snapshot(the_store, problems) -> list:
    """For `store verify`: how many files are wrong in how many snapshots, and one line for each such snapshot, to print ahead of the lines for each file.

    The first line counts every line below that is of a file of a
    snapshot (:attr:`chartbook.store.StoreProblem.of_snapshot`), each
    under the snapshot in whose folder the file is, or is missing from
    (:attr:`~chartbook.store.StoreProblem.path`): for a file that
    increments keep in the complete snapshot they build on, that one. Such
    a folder may have no record now, as one cleared in a store of
    ChartBook 0.5, or a complete snapshot that has gone and that
    increments still name: its files are counted under its name all the
    same, its pipeline is the one whose folder it is in, and its line says
    that it is a folder with no record, as each of its files' lines does,
    and whose the files are: the snapshot whose record keeps them there,
    the newest where several do, with how many more
    (:attr:`~chartbook.store.StoreProblem.kept_by`). That is the snapshot
    ``store ls`` says lacks them, so the two commands' lines are joined.
    Each line has the pipeline, the folder's name and how many files, a
    pipeline's folders together, oldest first.
    What is wrong outside any snapshot (a record that cannot be read, an
    object no pipeline owns, a folder that is not read) has its own line
    below and none here; with nothing wrong in any snapshot there is
    nothing to say.
    """
    from chartbook.store import StoreError

    counts: dict = {}
    no_record: dict = {}  # each folder with no record, with the snapshots whose records keep its files there
    for problem in problems:
        if getattr(problem, "of_snapshot", False):
            counts[problem.path] = counts.get(problem.path, 0) + 1
            if getattr(problem, "no_record", False):
                no_record.setdefault(problem.path, set()).update(getattr(problem, "kept_by", ()))
    if not counts:
        return []
    # A pipeline's ID is in its records: a folder that has none is named by a record in a folder of its pipeline
    by_snapshot: dict = {}  # the pipeline of each snapshot that has a record, by its folder
    by_pipeline_folder: dict = {}  # and of each pipeline's folder, by its name (the same under snapshots/ and increments/)
    records = getattr(the_store, "records", None)
    try:
        for record in records() if callable(records) else ():
            if record.readable:
                by_snapshot[record.folder] = record.pipeline
                by_pipeline_folder.setdefault(record.folder.parent.name, record.pipeline)
    except (OSError, ValueError, StoreError):
        pass

    def pipeline(folder) -> str:
        return by_snapshot.get(folder) or by_pipeline_folder.get(folder.parent.name) or folder.parent.name

    lines = [
        f"{sum(counts.values()):,} file(s) of {len(counts):,} snapshot(s) are missing or are not what their records say. "
        f"By snapshot, and then each file:"
    ]
    def whose(folder) -> str:
        """For a folder with no record: the snapshot whose record keeps its files there, which `store ls` says lacks them; the newest of several (a snapshot's folder is named by when it was made), and how many more."""
        keepers = sorted(no_record[folder], reverse=True)
        if not keepers:
            return ""
        if len(keepers) == 1:
            return f"; the record of {keepers[0]} keeps them there"
        return f"; the records of {keepers[0]} and {len(keepers) - 1:,} more keep them there"

    for folder in sorted(counts, key=lambda folder: (pipeline(folder), folder.name)):
        named = f"{folder.name} (a folder with no record{whose(folder)})" if folder in no_record else folder.name
        lines.append(f"  {_printable(pipeline(folder))}  {named}  {counts[folder]:,} file(s)")
    return lines


def _printable(text) -> str:
    """Text a store holds, as it may be printed: a control character (a line break, an escape) is a ``?``."""
    return "".join("?" if ord(c) < 32 or 127 <= ord(c) < 160 else c for c in str(text))


def _note_path(the_store, name: str) -> str:
    """Where a store keeps the note *name* of a lockfile, as a person finds it: a folder's in its own system's separators.

    A folder store keeps its notes under ``_chartbook/roots/``; one laid
    out as ChartBook 0.5 laid one out, and a bucket, under ``roots/``.
    """
    import os

    from chartbook.store import FolderStore, ROOTS_DIR

    if isinstance(the_store, FolderStore):
        # Under the store as it is shown, which carries no password
        folder = os.sep.join(the_store.roots_path().relative_to(the_store.root).parts)
        return f"{the_store}{os.sep}{folder}{os.sep}{name}"
    return f"{the_store}/{ROOTS_DIR}/{name}"


def _normalize_note_name(name: str) -> tuple[str, str]:
    """Strip a leading ``_chartbook/roots/`` or ``roots/`` prefix (as ``store gc`` prints); return ``(wanted, bare)``."""
    bare = name.replace("\\", "/")
    for prefix in ("_chartbook/roots/", "roots/"):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    wanted = bare if bare.endswith(".json") else f"{bare}.json"
    return wanted, bare


def _note_to_forget(the_store, name: str):
    """The note *name* names, when this machine may forget it. Nothing is removed.

    :raises ValueError: If there is no such note, more than one, a sync
        service's copy, or another machine's note.
    :raises StoreError: If the store is one nothing is removed from (a layout of ChartBook 0.5).
    """
    from chartbook.store import this_machine

    # Check the store's layout before changing anything: an earlier layout (0.5) must be migrated first
    the_store.check_tidy()
    wanted, bare = _normalize_note_name(name)
    roots = the_store.roots()
    match = [root for root in roots if root.note in (wanted, bare, name)]
    if not match:
        raise ValueError(
            f"No note named {wanted} under _chartbook/roots/. "
            f"`chartbook store gc --dry-run` lists each note it keeps pins for."
        )
    if len(match) > 1:
        raise ValueError(f"More than one note matches {wanted}: refuse to guess.")
    (root,) = match
    from chartbook.lock import _users_own_store

    here = this_machine(create=False)
    if root.copy:
        raise ValueError(
            f"{root.note} is a sync service's copy of a note, not one this machine wrote. "
            f"Remove {_note_path(the_store, root.note)} by hand once no machine needs it."
        )
    old_and_mine = _users_own_store(the_store) and root.machine == ""
    if root.machine != here and not old_and_mine:
        whose = f"on {root.host}" if root.host else (f"under machine {root.machine}" if root.machine else "from before notes named their machine")
        raise ValueError(
            f"{root.note} is another machine's note ({whose}). "
            f"Refuse to forget it from here: remove {_note_path(the_store, root.note)} "
            f"by hand once no machine needs it."
        )
    return root


def _forget_root(the_store, root) -> None:
    """Remove *root* from *the_store* and say so."""
    if not the_store.remove_root(root.written or root.lockfile, machine=root.machine):
        raise ValueError(f"Could not remove {_note_path(the_store, root.note)}.")
    click.echo(f"Forgot note {_note_path(the_store, root.note)}.")


def _forget_one_note(the_store, name: str) -> None:
    """Forget one note under ``_chartbook/roots/`` by its file name: this machine's only.

    Another machine's note, or a sync service's copy of one, is refused:
    remove its file by hand once no machine needs it.
    """
    _forget_root(the_store, _note_to_forget(the_store, name))


def _when_it_goes(why: str) -> str:
    """When a snapshot that `store gc` keeps for *why* goes, in the words of the plan's own reasons: the way out for one that has lost a file for good."""
    if "builds on it" in why:
        return "once the increments that build on it have gone, each for its own reason (`chartbook store gc --dry-run` says which stay, and why)"
    if "was made from" in why:
        return "once the snapshot that was made from it goes, or with a `chartbook store gc` without `--keep-lineage`"
    if "newest that names its repository" in why:
        return "once a newer snapshot of its pipeline names its repository (one made in a clone that has its remote)"
    if "repository's address" in why or "address of a kept" in why:
        return "once the kept snapshots it ties to their repository have gone"
    if "that stays has" in why:
        return "once the snapshot that holds its pipeline back is whole again, or has gone"
    if "cannot be found" in why:
        return "with `chartbook store gc --forget-missing`, which lets go of what a lockfile that cannot be found pinned"
    if "another machine" in why or "not read here" in why:
        return "once that machine's lockfile pins another (`chartbook pin --update` there), or its note is removed from the store"
    if "lockfile" in why:
        return "once no lockfile pins it: `chartbook pin --update` in the pipeline that does moves its pin to a newer snapshot"
    if "newest of its pipeline" in why:
        return "once a newer snapshot of its pipeline is made (`chartbook snapshot` in its folder) and nothing else keeps it"
    if "branch or tag" in why or "label points" in why:
        return "once a newer snapshot takes its place for that name, or with `chartbook store gc --aggressive`, which lets names keep nothing"
    if "keep = true" in why:
        return (
            "once the mark `keep = true` is taken out of its pipeline's chartbook.toml, that is committed, and a "
            "snapshot is made since (`chartbook snapshot` in its folder)"
        )
    if "days" in why:
        return "once it is older than that"
    return "once that is no longer so"


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
    "--forget-note",
    metavar="NAME",
    default=None,
    help="Forget one note under _chartbook/roots/ (this machine's only; another machine's: remove its file by hand), then plan as usual. --dry-run lists the note and leaves it in place",
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
def store_gc(dry_run, yes, forget_missing, forget_note=None, keep_days=None, keep_lineage=False, aggressive=False):
    """Remove from the store what nothing needs any more.

    The store is shared by every project of yours. Two things keep what is
    in it. A lockfile: each `chartbook pin` and `chartbook pin --update` notes
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
    command says what the marks keep), if an increment that stays builds
    on it (a snapshot the store keeps in less room, the rest of whose
    files are in this one's folder), or
    if it was made in the last 7 days (--keep-days). Otherwise it may be
    removed, and what only it named goes with it. A store keeps what work
    needs now, and lets old lineage go: with --keep-lineage, every snapshot
    a kept snapshot was made from is kept too, as far up as it goes, for
    `chartbook lineage` to check. With --aggressive, names keep nothing: a
    snapshot a git tag or branch names, or one holding a labelled model
    version that no lockfile pins, goes once nothing else keeps it.

    While a snapshot that stays lacks a file of its own (a sync that has
    not brought it, a file removed by hand), no snapshot of its pipeline is
    removed, since a read of the one with the hole is handed another's
    copy. gc names the pipeline, the snapshot and the file: the snapshot
    whose folder the file is missing from, as `chartbook store verify`
    names it, or, where that snapshot has itself gone from the store (one
    that increments build on), the newest of those that kept the file
    there, which verify names by the folder that has gone. Wait for the
    sync, or see `chartbook store verify`, which lists everything missing.
    gc says why that snapshot stays, and so when one that has lost a file
    for good goes: once a newer one is made, once no lockfile pins it, or
    with the option that lets go of what keeps it.

    A lockfile that cannot be found, because its project was deleted or its
    drive is not plugged in, still keeps what it last pinned. Pass
    --forget-missing to let those go. A note only ever adds to what is kept:
    what a lockfile's note recorded at its last pin is kept even when the
    lockfile here says otherwise now. A note of a lockfile on another
    machine, which a store in a shared or synced folder has, is kept with
    --forget-missing or without, as is a note from before notes named their
    machine and a sync service's copy of a note; each is listed with its
    file under _chartbook/roots/, which you remove once no machine needs it.
    --forget-note NAME forgets one of this machine's notes (the name gc
    prints); another machine's note is refused here, and removed by hand
    once no machine needs it. In your own store, under ~/.chartbook, a note
    from before notes named their machine is this machine's: its lockfile is
    read, and the note is removed once this machine has a note of that
    lockfile and the lockfile is read here, or with --forget-missing once
    the lockfile is gone.

    What would be removed is listed, and nothing is removed until you say
    yes. An object stored in the last hour is never removed, but what only
    a removed snapshot holds, which goes with its folder: a pin puts
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
        chartbook store gc --forget-note abcdef0123456789abcdef0123456789.json --dry-run
        chartbook store gc --keep-lineage
        chartbook store gc --aggressive --keep-days 0
    """
    from chartbook import lock
    from chartbook import snapshot as snapshots
    from chartbook.store import StoreError, default_store

    days = keep_days if keep_days is not None else snapshots.KEEP_DAYS
    pending = None
    forgotten = False
    try:
        the_store = default_store()
        if forget_note:
            pending = _note_to_forget(the_store, forget_note)
            if dry_run:
                click.echo(f"Would forget note {_note_path(the_store, pending.note)}.")
        plan = lock.plan_gc(
            the_store, forget_missing=forget_missing, keep_days=days, keep_lineage=keep_lineage,
            aggressive=aggressive, hashed=True, without_notes=(pending.note,) if pending is not None else None,
        )
    except (StoreError, lock.LockError, ValueError) as e:
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
        click.echo("Nothing was removed.", err=True)
        raise SystemExit(1)

    def _why_with_note(taken, why: str) -> str:
        """*why*, with which note under ``_chartbook/roots/`` holds the pin when the keep is by the note.

        A live lockfile's pin (``a lockfile pins it``) needs no note named: the
        lockfile is listed above. A keep that is by the note alone names it.
        """
        note = plan.noted_by.get((taken.commit, taken.made_at))
        if not note:
            return why
        if why == "a lockfile pins it" or why.startswith("a lockfile pins a labelled version"):
            return why
        return f"{why} (note _chartbook/roots/{note})"

    def say_held_back(held_back: dict, kept: list, not_intact: set) -> None:
        """Say of each pipeline none of whose snapshots is removed which snapshot lacks which file, or has it with other bytes, why that one stays, and what to do."""
        reasons = {taken.path: _why_with_note(taken, why) for taken, why in kept}
        for pipeline, (record, file, count) in sorted(held_back.items()):
            why = reasons.get(record, "")
            stays = f"stays{f' because {why}' if why else ''}"
            if pipeline in not_intact:
                # Found by reading it: the file is there, at the size its record says, and is not what it was
                more = f" (and {count - 1} more of its files)" if count > 1 else ""
                wrong = f"in its snapshot {record.parent.parent.name}, {_printable(file)}{more}, and it {stays}"
            else:
                more = f" and {count - 1} more" if count > 1 else ""
                wrong = f"its snapshot {record.parent.parent.name} lacks {_printable(file)}{more}, and {stays}"
            click.echo(f"Nothing of {_printable(pipeline)} is removed: {wrong}.")
            click.echo(
                f"  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists "
                f"everything missing. If it is lost for good, that snapshot goes {_when_it_goes(why)}."
            )

    def drop_note() -> None:
        """Forget the note once a removal is actually carried out. A dry run, and a no to the question, leave it."""
        nonlocal forgotten
        if pending is None or forgotten:
            return
        _forget_root(the_store, pending)
        forgotten = True

    def _say_removed(snapshots: int, objects: int, pinned: int, size: int) -> None:
        by_pins = f", {pinned} snapshot(s) a pin made from a repository" if pinned else ""
        click.echo(f"Removed {snapshots} snapshot(s){by_pins} and {objects} object(s), {_format_bytes(size)}.")

    def _say_note_stayed(error: BaseException) -> None:
        """The removals are done, and forgetting the note failed: say both, and where the note still is."""
        click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)
        if pending is not None:
            click.echo(
                f"The note {_note_path(the_store, pending.note)} is still there. "
                f"`chartbook store gc --forget-note {pending.note}` forgets it.",
                err=True,
            )

    def carry_out():
        """Remove what the plan says to, and say what could not be removed, if anything could not."""
        try:
            done = lock.carry_out_gc(plan, the_store)
        except lock.GcError as e:
            try:
                drop_note()
            except (StoreError, lock.LockError, ValueError, OSError) as note_error:
                e.failures.append(("the note", note_error))
            # Everything else went: say so, then each thing that stayed and what to do
            if e.removed_snapshots or e.removed or e.pinned:
                _say_removed(e.removed_snapshots, e.removed, e.pinned, e.size_bytes)
            click.echo(click.style("Error: ", fg="red", bold=True) + f"{len(e.failures)} thing(s) could not be removed:", err=True)
            for _, why in e.failures:
                click.echo(f"  {_printable(_said(why))}", err=True)  # the store's words name the thing and say what to do
            if any(what.startswith("the snapshot") for what, _ in e.failures):
                click.echo("What a record that stayed names stays with it.", err=True)
            raise SystemExit(1)
        except (StoreError, lock.LockError, ValueError, OSError) as e:
            click.echo(click.style("Error: ", fg="red", bold=True) + _said(e), err=True)
            click.echo(
                "The note was forgotten. Nothing else was removed." if forgotten else "Nothing was removed.",
                err=True,
            )
            raise SystemExit(1)
        try:
            drop_note()
        except (StoreError, lock.LockError, ValueError, OSError) as error:
            # The store is already changed. "Nothing was removed" would deny that.
            if done.snapshots or done.objects or done.pinned or done.freed_bytes:
                _say_removed(done.snapshots, done.objects, done.pinned, done.freed_bytes)
            _say_note_stayed(error)
            raise SystemExit(1)
        return done

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

            note += f"  (its note under no machine name goes: {_note_path(the_store, root_name(lockfile))})"
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
            f"  {_printable(root.written or str(root.lockfile))}  ({whose}: what it recorded at its last pin is kept{read}; "
            f"note {_note_path(the_store, _printable(root.note))})"
        )
    if plan.snapshots_kept:
        reasons = {}
        for taken, why in plan.snapshots_kept:
            reasons[_why_with_note(taken, why)] = reasons.get(_why_with_note(taken, why), 0) + 1
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
    say_held_back(plan.held_back, plan.snapshots_kept + plan.pinned_kept, plan.not_intact)

    if not plan.delete and not plan.snapshots_delete and not plan.pinned_delete and not plan.unused:
        click.echo("Nothing to remove.")
        if not dry_run:
            carry_out()  # forgets the missing, if asked to
        return

    # The size of what goes: the objects nothing names and, with a snapshot's folder, its own copies of
    # files that a kept snapshot has too, and what no snapshot uses (GcPlan.freed_bytes); and after the
    # yes, of what went (GcDone)
    freed = _format_bytes(plan.freed_bytes)

    def say_unused(*, among: bool) -> None:
        """On a dry run, name the files no snapshot uses, which a real gc removes with the store's tidy."""
        if not (dry_run and plan.unused):
            return
        if among:
            click.echo(f"  and {len(plan.unused)} file(s) no snapshot uses  {_format_bytes(plan.unused_bytes)}")
        for name, size in plan.unused:
            click.echo(f"  {name}  {_format_bytes(size)}")

    if plan.snapshots_delete or plan.pinned_delete:
        # A snapshot a pin made from a repository goes as any does, its whole folder: said, and asked about
        counted = [f"{len(plan.snapshots_delete)} snapshot(s)"] if plan.snapshots_delete else []
        counted += [f"{len(plan.pinned_delete)} snapshot(s) a pin made from a repository"] if plan.pinned_delete else []
        counted += [f"{len(plan.delete)} object(s) that nothing names"] if plan.delete else []
        click.echo(f"Would remove {', '.join(counted[:-1]) + ' and ' if counted[1:] else ''}{counted[-1]}, {freed}:")
        for taken, why in plan.snapshots_delete:
            click.echo(
                f"  {taken.pipeline} at {taken.commit[:7]}, made "
                f"{_when(taken.made_at)}: {why}"
            )
        for taken, why in plan.pinned_delete:
            click.echo(f"  {taken.pipeline} at {taken.commit[:7]}, which a pin made {_when(taken.made_at)}: {why}")
        if dry_run and plan.delete:
            for content_hash, size in plan.delete:
                click.echo(f"  {content_hash}  {_format_bytes(size)}")
            if plan.copies_bytes:
                click.echo(
                    f"  and the removed snapshots' own copies of files a kept snapshot has too  "
                    f"{_format_bytes(plan.copies_bytes)}"
                )
        say_unused(among=True)
    elif plan.delete:
        if dry_run:
            click.echo(f"Would remove {len(plan.delete)} object(s), {freed}, that nothing names:")
            for content_hash, size in plan.delete:
                click.echo(f"  {content_hash}  {_format_bytes(size)}")
            if plan.copies_bytes:
                click.echo(f"  and the copies of files a kept snapshot has too, in the folders that go  {_format_bytes(plan.copies_bytes)}")
            say_unused(among=True)
        else:
            click.echo(f"Would remove {len(plan.delete)} object(s), {freed}, that nothing names.")
    elif plan.unused:
        if dry_run:
            click.echo(f"Would remove {len(plan.unused)} file(s) no snapshot uses, {freed}:")
            say_unused(among=False)
        else:
            click.echo(f"Would remove {len(plan.unused)} file(s) no snapshot uses, {freed}.")
    if dry_run:
        return
    if not yes and not click.confirm("Remove them?", default=False):
        click.echo("Nothing was removed.")
        return
    done = carry_out()
    # What the plan made again at the yes keeps, each with why: pinned meanwhile only where it was
    for taken, why in done.kept_after_all:
        made = "which a pin made" if any(taken.path == pinned.path for pinned, _ in plan.pinned_delete) else "made"
        click.echo(f"Kept after all: {taken.pipeline} at {taken.commit[:7]}, {made} {_when(taken.made_at)}: {why}")
    if done.objects_kept:
        click.echo(f"Kept after all: {done.objects_kept} object(s), which a lockfile or a snapshot names or uses now")
    say_held_back(
        {pipeline: held for pipeline, held in done.held_back.items() if pipeline not in plan.held_back}, done.kept, done.not_intact
    )
    by_pins = f", {done.pinned} snapshot(s) a pin made from a repository" if done.pinned else ""
    click.echo(f"Removed {done.snapshots} snapshot(s){by_pins} and {done.objects} object(s), {_format_bytes(done.freed_bytes)}.")

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

    For `init`: the command's own work
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
@click.option("--list", "list_", is_flag=True, default=False, help="Show what is trusted, and how")
@click.option(
    "--forget",
    is_flag=True,
    default=False,
    help="No longer trust the folder (or, with --repository, its repository)",
)
def trust(path, render_only, repository, list_, forget):
    """Trust a pipeline's folder, so that a build of it runs as your own.

    A build of a folder you have not trusted runs as a build of files from
    a store does: `chartbook docs build` renders its site with no query
    run and no template or file from outside the folder, and `chartbook run`
    refuses to run its build script, which is code. A
    project `chartbook init` made is trusted as it is made. One you cloned
    is trusted when you say so, here.

    With no PATH, this folder. A folder's trust covers the folders inside
    it, so `chartbook trust ~/GitRepositories/ftsfr` trusts every pipeline
    under it. --repository trusts the folder's origin repository instead:
    every clone of it, wherever it is. Catalogs render stored snapshots
    and need no member trust.

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
        chartbook trust --list
        chartbook trust --forget
    """
    import os

    from chartbook import config
    from chartbook.identity import derive_pipeline_id, get_git_remote_url, repository_key
    from chartbook.manifest import _read_manifest_file, catalog_member_dirs, resolve_project_type

    if list_ and (path or render_only or repository or forget):
        raise click.UsageError("--list shows what is trusted; it takes no PATH and no other option.")
    if forget and render_only:
        raise click.UsageError("--forget takes a PATH, and --repository; a level means nothing to it.")

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
        "Path to catalog.toml (or its parent directory)",
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
    the project's is for an older ChartBook, and `chartbook run --check` warns.

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
        _let_ctrl_c_end_a_read()  # found by review: Ctrl-C at this question did nothing until Enter
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



@install.command("agents")
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Replace skill files, and a ChartBook section of AGENTS.md, that were changed by hand or are a newer ChartBook's, without asking",
)
@click.pass_context
def install_agents(ctx, force):
    """Set a project up for coding agents: the Claude Code skill, and a ChartBook section in AGENTS.md.

    Two halves. The first installs the Claude Code skill for you, as
    `chartbook install claude-skill` does. The second, in a pipeline's
    folder (or below one), writes a ChartBook section into that project's
    AGENTS.md, which other coding agents read: what the project is, the
    few commands that matter, and where the whole reference is.

    The section stands between two marker lines. Run again after an
    upgrade, the command replaces what is between them with this
    version's and leaves the rest of the file alone, so notes of your own
    go outside those lines. A section somebody has written in is replaced
    only when you say so, or with --force, and a newer ChartBook's is
    left as it is. Commit AGENTS.md: it is for everyone who works in the
    repository.

    Anywhere else it installs the skill and says the AGENTS.md half is
    for a project.

    \b
    Examples:
        chartbook install agents
    """
    import os

    import tomli

    from chartbook import agents
    from chartbook.check import display_path

    def stop(said: str) -> None:
        click.echo(click.style("Error: ", fg="red", bold=True) + said, err=True)
        raise SystemExit(1)

    from chartbook import claude_skill

    failed = False
    yours = claude_skill.user_dir()
    try:
        newer = claude_skill.version_of(yours) if claude_skill.relation(yours) == "newer" else None
    except OSError:
        newer = None  # a copy that cannot be read: the skill's own half says so
    if newer and not force:
        # As for the section below: two environments on two versions do not take turns, and neither fails for it
        click.echo(
            f"The skill in {claude_skill.shown(yours)} is for ChartBook {newer}, newer than this one, {__version__}. "
            "Left as it is (--force installs this version's)."
        )
    else:
        try:
            ctx.invoke(install_claude_skill, force=force, project=False)
        except SystemExit as stopped:  # declined at its question, or no skill in the package: the other half is still done
            failed = bool(stopped.code)
        except click.Abort:
            if _can_ask():
                raise  # a person at the question, with Ctrl-C: the command ends, and nothing more is written
            # Its question, where nobody could answer it
            click.echo("", err=True)
            click.echo("The skill was left as it is: `chartbook install claude-skill` installs it, and asks.", err=True)
            failed = True
        except (OSError, RuntimeError) as e:  # a folder that cannot be written; no input to ask of
            click.echo(click.style("Error: ", fg="red", bold=True) + f"the skill could not be installed: {_explain_os_error(e)}", err=True)
            failed = True

    project = agents.project_folder()
    if project is None:
        click.echo(
            "No chartbook.toml here, or above in this repository: the AGENTS.md half is for a project. Run "
            "`chartbook install agents` in a pipeline's folder to write it."
        )
        raise SystemExit(1 if failed else 0)
    try:
        tomli.loads((project / "chartbook.toml").read_bytes().decode("utf-8"))
    except (OSError, ValueError) as e:
        stop(f"{display_path(project / 'chartbook.toml', relative_to=Path.cwd())} cannot be read as a manifest ({_said(e)}), so no AGENTS.md was written beside it.")
    file = project / agents.FILE
    shown = display_path(file, relative_to=Path.cwd())
    # A link is written through only to a file of the project that is there: never to one outside it, or to nothing
    to = ""
    if file.is_symlink():
        real = Path(os.path.realpath(file))
        if real.is_dir():
            stop(f"{shown} is a link to {real}, which is a folder. Nothing was written.")
        if not real.is_file():
            stop(f"{shown} is a link to {real}, which is not there. Nothing was written.")
        if project.resolve() not in real.parents:
            stop(f"{shown} is a link to {real}, outside this project. Nothing was written to it.")
        to = f" (a link to {display_path(real, relative_to=project.resolve())})"
    try:
        existed = file.exists()
        was = file.read_bytes() if existed else None
        found = agents.read(was.decode("utf-8") if existed else "")
    except agents.Unclosed as e:
        stop(f"{shown}: {e}. Nothing was written to it: close the fence, and run this again.")
    except agents.Malformed as e:
        stop(f"{shown}: {e}. Nothing was written to it: put its marker lines right, or take them out, and run this again.")
    except (OSError, ValueError) as e:
        stop(f"{shown} cannot be read as text: {_explain_os_error(e)}")

    standing = agents.standing(found)
    if standing == "current":
        click.echo(f"{shown}: its ChartBook section is up to date (ChartBook {__version__}).")
        raise SystemExit(1 if failed else 0)
    if standing == "newer" and not force:
        # As for the skill: two environments on two versions do not take turns at one committed file
        click.echo(
            f"{shown}: its ChartBook section is for ChartBook {found.version}, newer than this one, {__version__}. "
            "Left as it is (--force writes this version's)."
        )
        raise SystemExit(1 if failed else 0)
    if standing == "by hand" and not force:
        # Which lines, and how many would go: a yes is given knowing what it is to
        where = f"lines {found.first} to {found.last}"
        between = found.last - found.first - 1
        said = (
            f"The ChartBook section of {shown} ({where}) was changed since ChartBook {found.version} wrote it."
            if found.hashed and claude_skill._parsed(found.version) is not None
            else f"The ChartBook section of {shown} ({where}) is not one that `chartbook install agents` wrote."
        )
        if not _can_ask():
            stop(
                f"{said} Notes of your own go outside its two marker lines. `chartbook install agents --force` replaces what "
                "is between them, and skill files changed by hand too."
            )
        click.echo(f"{said} Notes of your own go outside its two marker lines.", err=True)
        try:
            agreed = _confirm(f"Replace what is between them ({between} line{'' if between == 1 else 's'})?", default=False)
        except click.Abort:  # Ctrl-C, or the end of input
            click.echo("", err=True)
            agreed = False
        if not agreed:
            click.echo(f"{shown} was left as it is.")
            raise SystemExit(1 if failed else 0)
    try:
        agents.write(file, agents.written(found), was=was)
    except agents.NotWritten as e:
        stop(f"{shown} was not written: {e}.")
    except OSError as e:
        stop(f"{shown} could not be written, and is as it was: {_explain_os_error(e)}")
    if not existed:
        click.echo(f"Wrote {shown}: a ChartBook section, for the agents that read that file (ChartBook {__version__}).")
    elif standing == "none":
        click.echo(f"Added a ChartBook section to {shown}{to} (ChartBook {__version__}). The rest of the file is as it was.")
    elif found.version and found.version != __version__ and standing in ("older", "newer"):
        click.echo(
            f"Updated the ChartBook section of {shown}{to} from ChartBook {found.version} to {__version__}. "
            "The rest of the file is as it was."
        )
    else:
        click.echo(f"Wrote the ChartBook section of {shown}{to} again (ChartBook {__version__}). The rest of the file is as it was.")
    if failed:
        raise SystemExit(1)


@catalog.command("migrate")
@click.option("--catalog", "catalog_path", type=click.Path())
def catalog_migrate(catalog_path):
    """Replace a folder catalog with catalog.toml, keeping an exact backup."""
    from chartbook.catalog_config import migrate
    from chartbook.store import StoreError
    try:
        target, missing = migrate(catalog_path)
    except (OSError, ValueError, StoreError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Migrated to {target}")
    from chartbook.config import get_store_setting, get_global_settings_path, get_system_settings_path
    _, origin = get_store_setting()
    if origin in ("user", "system"):
        settings_path = get_global_settings_path() if origin == "user" else get_system_settings_path()
        click.echo(
            f"The catalog now defines [stores]. Remove the obsolete [store] table from "
            f"{settings_path} if it is no longer needed as a fallback for other catalogs; "
            "it is ignored by this catalog and otherwise warns on each command."
        )
    from chartbook.missing import _quoted

    for pipeline, folder in missing:
        click.echo(f"{pipeline} has no snapshot. Run: chartbook snapshot --project-dir {_quoted(folder)}")


@ls.command("stores")
@_json_option
@click.pass_context
def ls_stores(ctx, as_json):
    """List stores in catalog order."""
    from chartbook.multi_store import Stores
    catalog_arg = ctx.obj.get("catalog")
    if catalog_arg is None:
        _catalog_or_make_one()
    else:
        _resolve_catalog_toml_path(catalog_arg)
    stores = Stores.configured(catalog_arg)
    if as_json or ctx.obj.get("json"):
        _echo_json([
            {"name": entry.name, "url": str(entry.store), "read_only": bool(entry.read_only), "reachable": bool(entry.reachable)}
            for entry in stores.entries
        ])
        return
    for entry in stores.entries:
        state = "read-only" if entry.read_only else "writable"
        if not entry.reachable:
            state += ", unreachable"
        click.echo(f"{entry.name}: {entry.store} ({state})")


@ls.command("versions")
@_json_option
@click.pass_context
def ls_versions(ctx, as_json):
    """List every snapshot, newest first, with its store."""
    from chartbook.multi_store import Stores
    from chartbook.snapshot import readable_snapshots
    catalog_arg = ctx.obj.get("catalog")
    if catalog_arg is None:
        _catalog_or_make_one()
    else:
        _resolve_catalog_toml_path(catalog_arg)
    stores = Stores.configured(catalog_arg)
    found, unreadable = readable_snapshots(stores)  # a store that is not read is said by the group (_Ls)
    if as_json or ctx.obj.get("json"):
        _echo_json([
            {"pipeline": taken.pipeline, "commit": taken.commit, "made_at": taken.made_at, "store": stores.name_of(taken.path)}
            for taken in reversed(found)
        ])
    else:
        for taken in reversed(found):
            click.echo(f"{taken.pipeline} {taken.commit[:12]} {taken.made_at} {stores.name_of(taken.path)}")
    for path, why in unreadable:
        click.echo(f"warning: {path}: {why}", err=True)


@main.command("link")
@click.argument("pipeline")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--project-dir", type=click.Path())
def link_command(pipeline, folder, project_dir):
    """Read a dependency's working files until chartbook.links.toml is removed."""
    from chartbook.links import add
    try:
        path = add(resolve_project_dir(project_dir), pipeline, folder)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Linked {pipeline} in {path}; its pin is not in use.")


@store.command("add")
@click.argument("name")
@click.argument("url")
@click.option("--pipelines", multiple=True)
@click.option("--read-only", is_flag=True)
@click.option("--catalog", "catalog_path", type=click.Path())
def store_add(name, url, pipelines, read_only, catalog_path):
    """Add a store to the catalog; keep comments and list what it holds."""
    from chartbook.catalog_config import edit_store
    from chartbook.store import StoreError, store_for_url
    from chartbook.snapshot import readable_snapshots
    if catalog_path is None:
        _catalog_or_make_one()  # the machine's own store is listed first, before the one added
    try:
        from chartbook.config import get_default_catalog_path, get_global_catalog_path, _absolute_if_folder
        catalog_file = Path(catalog_path) if catalog_path else (get_default_catalog_path() or get_global_catalog_path())
        if catalog_file.is_dir():
            catalog_file /= "catalog.toml"
        candidate = store_for_url(_absolute_if_folder(url, catalog_file))
        from chartbook.store import FolderStore
        if isinstance(candidate, FolderStore) and not candidate.root.is_dir():
            raise ValueError(f"Store folder does not exist: {candidate}")
        if isinstance(candidate, FolderStore) and not (candidate.root / "store.json").is_file() and any(candidate.root.iterdir()):
            from chartbook.store import holds_v1
            if holds_v1(candidate.root):
                raise ValueError(f"{candidate} uses the old layout; run `chartbook store migrate` first")
            raise ValueError(f"{candidate} is not a store (no store.json)")
        found, errors = readable_snapshots(candidate)
        if errors:
            raise ValueError(f"Store has unreadable records: {errors[0][1]}")
        spec = {"url": url}
        if pipelines:
            spec["pipelines"] = list(pipelines)
        if read_only:
            spec["read_only"] = True
        path = edit_store(name, spec, catalog_path)
    except (ValueError, StoreError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Added {name} to {path}")
    for pipeline in sorted({t.pipeline for t in found}):
        click.echo(pipeline)


@store.command("remove")
@click.argument("name")
@click.option("--catalog", "catalog_path", type=click.Path())
def store_remove(name, catalog_path):
    """Remove a store from the catalog; its files are untouched."""
    from chartbook.catalog_config import edit_store
    try:
        edit_store(name, catalog=catalog_path)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"Removed {name}; its files are untouched.")


def _entries_holding(entries, pipeline):
    """The reachable stores among *entries* holding a snapshot its owner made of *pipeline*, and the stores that could not be read, as (name, error).

    Both empty when no pipeline is named. A record a pin made from a clone
    does not count: `store export` writes what the owner made, as
    :func:`chartbook.sharing.export` does.
    """
    from chartbook.store import StoreUnreachableError

    if not pipeline:
        return [], []
    found, unreadable = [], []
    for entry in entries:
        the_store = entry.store
        if getattr(the_store, "records", None) is None:
            continue
        if not entry.reachable:
            unreadable.append((entry.name, StoreUnreachableError(f"unreachable: {the_store}")))
            continue
        try:
            if getattr(the_store, "records_in", None) is not None and hasattr(the_store, "pipeline_path"):
                records = the_store.records_in(the_store.pipeline_path(pipeline))  # one pipeline's folder, not every record
            else:
                records = the_store.records()
            if any(r.readable and r.made_by == "snapshot" and r.pipeline == pipeline for r in records):
                found.append(entry)
        except Exception as error:  # noqa: BLE001 - said below when no store holds the pipeline; the command says the whole of it when the store is chosen
            unreadable.append((entry.name, error))
    return found, unreadable


def _entries_holding_note(entries, note_name: str):
    """Stores among *entries* that hold a note matching *note_name*, and any store that could not be read."""
    from chartbook.store import StoreUnreachableError

    wanted, bare = _normalize_note_name(note_name)
    found, unreadable = [], []
    for entry in entries:
        if not entry.reachable:
            unreadable.append((entry.name, StoreUnreachableError(f"unreachable: {entry.store}")))
            continue
        try:
            if any(root.note in (wanted, bare, note_name) for root in entry.store.roots()):
                found.append(entry)
        except Exception as error:  # noqa: BLE001 - reported below when no store holds the note
            unreadable.append((entry.name, error))
    return found, unreadable


def _store_selection(command, all_stores=False):
    """Keep maintenance local to each store and its own retention notes."""
    original = command.callback
    import functools
    @functools.wraps(original)
    def selected(*args, store_name=None, **kwargs):
        from chartbook.multi_store import Stores, selected_store
        try:
            configured = Stores.configured()
            chosen = configured.named(store_name) if store_name else None
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None
        forget_note = kwargs.get("forget_note") if command.name == "gc" else None
        scoped = store_name is not None
        holding_note = None
        if store_name:
            entries = [chosen]
        elif forget_note and len(configured.entries) > 1:
            wanted, _ = _normalize_note_name(forget_note)
            holding, unreadable = _entries_holding_note(configured.entries, forget_note)
            if len(holding) > 1:
                names = ", ".join(entry.name for entry in holding)
                raise click.ClickException(f"Note {wanted} is in stores {names}: select one with --store NAME")
            if not holding:
                looked = ", ".join(entry.name for entry in configured.entries)
                said = f"No store holds note {wanted} (looked in {looked}"
                for name, error in unreadable:
                    said += f"; {name} could not be read: {_said(error)}"
                raise click.ClickException(said + "). Select a store with --store NAME to work in it all the same.")
            # The note is in one store. Forget it there, and plan every store, as `store gc` does.
            holding_note = holding[0]
            if holding_note.read_only:
                raise click.ClickException(f"Store {holding_note.name!r} is read-only")
            if not holding_note.reachable:
                raise click.ClickException(f"Store {holding_note.name!r} is unreachable")
            from chartbook.store import StoreError

            try:
                holding_note.store.check_writable()
                _note_to_forget(holding_note.store, forget_note)
            except (StoreError, ValueError, OSError) as error:
                click.echo(click.style("Error: ", fg="red", bold=True) + _said(error), err=True)
                click.echo("Nothing was removed.", err=True)
                raise SystemExit(1)
            entries = configured.entries
        elif all_stores:
            entries = configured.entries
        elif len(configured.entries) > 1:
            # A command about one pipeline (export) works in the store that holds it
            pipeline = kwargs.get("pipeline")
            holding, unreadable = _entries_holding(configured.entries, pipeline)
            if len(holding) == 1:
                entries = holding
            elif len(holding) > 1:
                names = ", ".join(entry.name for entry in holding)
                raise click.ClickException(f"{pipeline} has snapshots in stores {names}: select one with --store NAME")
            elif pipeline:
                looked = ", ".join(entry.name for entry in configured.entries)
                said = f"No store holds a snapshot of {pipeline} (looked in {looked}"
                for name, error in unreadable:
                    said += f"; {name} could not be read: {_said(error)}"
                raise click.ClickException(said + "). Select a store with --store NAME to work in it all the same.")
            else:
                raise click.ClickException("Select a store with --store NAME")
        else:
            entries = configured.entries
        failures = []
        for entry in entries:
            if all_stores and not scoped and entry.reachable:
                from chartbook.store import StoreError, StoreUnreachableError
                try:
                    entry.store.all_snapshot_files()
                except (StoreUnreachableError, OSError) as error:
                    click.echo(f"Skipping store {entry.name}: unreachable ({error})")
                    continue
                except StoreError:
                    pass  # the command reports a layout or integrity error below
            if command.name not in ("verify", "info", "export") and entry.read_only:
                if all_stores and not scoped and entry is not holding_note:
                    click.echo(f"Skipping store {entry.name}: read-only")
                    continue
                raise click.ClickException(f"Store {entry.name!r} is read-only")
            if not entry.reachable:
                if all_stores and not scoped and entry is not holding_note:
                    click.echo(f"Skipping store {entry.name}: unreachable")
                    continue
                raise click.ClickException(f"Store {entry.name!r} is unreachable")
            if len(configured.entries) > 1:
                click.echo(f"Store {entry.name}: {entry.store}")
            token = selected_store.set(entry.store)
            call_kwargs = kwargs
            if holding_note is not None and entry is not holding_note:
                call_kwargs = {**kwargs, "forget_note": None}
            try:
                original(*args, **call_kwargs)
            except click.ClickException as error:
                if not all_stores or scoped or len(configured.entries) == 1:
                    raise
                failures.append(entry.name)
                click.echo(f"Store {entry.name}: {error.format_message()}", err=True)
            except SystemExit as exit_:
                if not exit_.code or not all_stores or scoped or len(configured.entries) == 1:
                    raise
                failures.append(entry.name)
            finally:
                selected_store.reset(token)
        if failures:
            raise click.ClickException("Maintenance failed in stores: " + ", ".join(failures))
    command.callback = selected
    command.params.append(click.Option(["--store", "store_name"], help="Select a named catalog store"))


for _command_name in ("gc", "verify", "migrate", "export", "import"):
    _store_selection(store.commands[_command_name], all_stores=_command_name in ("gc", "verify"))


# Retired commands retain actionable errors, without executing their old behavior.
main.commands.pop("build", None)
catalog.commands.pop("add", None)


@store.command("move")
@click.argument("pipeline")
@click.option("--to", required=True)
@click.option("--keep", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--no-route", is_flag=True)
def store_move(pipeline, to, keep, dry_run, no_route):
    """Copy and verify a pipeline in the destination before removing its sources."""
    from chartbook.multi_store import Stores
    from chartbook.transfer import move
    from chartbook.store import StoreError
    try:
        count, size = move(pipeline, Stores.configured(), to, keep=keep, dry_run=dry_run, route=not no_route)
    except (ValueError, StoreError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(f"{'Would move' if dry_run else 'Copied' if keep else 'Moved'} {count} snapshot(s), {_format_bytes(size)}, to {to}.")
    if not keep and not dry_run:
        click.echo("Paths previously printed from source stores may be gone; resolve them again with `chartbook path`.")


if __name__ == "__main__":
    main()
