"""What ``chartbook init`` renders, and what it does after.

``chartbook init`` renders a project from the cookiecutter template, which
is the ``template/`` folder of ChartBook's own repository
(:data:`TEMPLATE_REPOSITORY`, :data:`TEMPLATE_DIRECTORY`). It lives beside
the code so that a command the template uses and the command itself change
in one pull request, and so that the tests here build a freshly rendered
project. It comes with the package (a wheel carries it as
``chartbook/template``; a source checkout has it beside ``src/``), so the
template a project gets is always the one this ChartBook was made with, and
rendering it needs no network (:func:`find_template`, :func:`render`).

It is rendered with cookiecutter, and ``.cruft.json`` is written as cruft
writes it, naming the repository on GitHub, its ``template`` folder and the
commit this ChartBook was built from (:func:`template_commit`), so ``cruft
update`` and ``cruft check`` follow the template from there. cruft itself
would clone the template, which a wheel's folder is not.

With ``--git`` it also runs ``git init`` and makes the first commit; with
``--github`` it then creates a GitHub repository and pushes that commit.
These are the same three commands every time, run here through ``git`` and
``gh`` as subprocesses, with the user's existing configuration and login.

Everything that can be checked is checked *before* the template is rendered
(:func:`preflight`), so a missing tool or login fails with nothing created.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

INITIAL_COMMIT_MESSAGE = "Initial commit from chartbook init"

#: The first branch's name when the user's git configuration does not set one.
DEFAULT_BRANCH = "main"

#: A project rendered by cruft carries this file at its root.
CRUFT_MARKER = ".cruft.json"

#: The repository the project template is in: ChartBook's own.
TEMPLATE_REPOSITORY = "https://github.com/backofficedev/chartbook"

#: The folder of that repository that is the template.
TEMPLATE_DIRECTORY = "template"

#: The file a built package carries the commit it was built from in, beside
#: its modules (written by ``hatch_build.py`` at the repository's root).
BUILT_FROM = "built_from.txt"

#: The template's private variable for the ChartBook that rendered it: the
#: new project's environment files ask for this version or later.
VERSION_VARIABLE = "_chartbook_version"


class ScaffoldError(Exception):
    """A step of ``chartbook init --git/--github`` could not be done.

    The message says what to do about it. Nothing here is a bug to report
    with a traceback: it is a missing tool, a missing login, or a command
    that git or gh refused.
    """


def _run(command: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run a git or gh command, capturing its output."""
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def _detail(result: subprocess.CompletedProcess) -> str:
    """The part of a failed command's output worth showing."""
    return (result.stderr or result.stdout or "").strip()


def github_host() -> str:
    """The host ``gh`` will create the repository on."""
    return os.environ.get("GH_HOST") or "github.com"


def enclosing_repository(cwd: Path) -> Optional[str]:
    """Return the root of the git repository *cwd* is inside, if any.

    A project created there with ``--git`` becomes a repository nested in
    that one, which is legitimate but worth saying out loud.
    """
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else None


def preflight(cwd: Path, use_github: bool) -> None:
    """Check everything ``--git`` (and ``--github``) needs, before anything exists.

    :param cwd: The directory the project will be created in.
    :param use_github: Whether a GitHub repository will be created too.
    :raises ScaffoldError: Naming the fix, if a tool, an identity or a login
        is missing.
    """
    if shutil.which("git") is None:
        raise ScaffoldError(
            "git is not installed, or not on PATH. Install it from "
            "https://git-scm.com/downloads and try again."
        )

    # The first commit needs an author; git says so only at commit time
    if _run(["git", "var", "GIT_AUTHOR_IDENT"], cwd=cwd).returncode != 0:
        raise ScaffoldError(
            "git does not know who you are, so it cannot make the first commit. "
            "Set your identity and try again:\n"
            '    git config --global user.name "Your Name"\n'
            '    git config --global user.email "you@example.com"'
        )

    if not use_github:
        return

    if shutil.which("gh") is None:
        raise ScaffoldError(
            "--github needs the GitHub CLI (gh), which is not installed or not "
            "on PATH. Install it from https://cli.github.com, run 'gh auth "
            "login', and try again."
        )

    host = github_host()
    if _run(["gh", "auth", "status", "--hostname", host], cwd=cwd).returncode != 0:
        raise ScaffoldError(
            f"--github needs gh to be logged in to {host}, and it is not. "
            f"Run 'gh auth login' and try again."
        )


def _package_dir() -> Path:
    """This package's folder, as installed."""
    return Path(str(importlib.resources.files("chartbook")))


def find_template(package_dir: Optional[Path] = None) -> Path:
    """The project template that came with this ChartBook: the folder holding ``cookiecutter.json``.

    A wheel carries it in the package as ``chartbook/template``. A source
    checkout, which an editable install runs from, has it as ``template/``
    beside ``src/``.

    :param package_dir: The package's folder; this ChartBook's by default.
    :raises ScaffoldError: If neither is there, as in a broken install.
    """
    package_dir = Path(package_dir) if package_dir is not None else _package_dir()
    candidates = [package_dir / TEMPLATE_DIRECTORY]
    if package_dir.parent.name == "src":
        candidates.append(package_dir.parent.parent / TEMPLATE_DIRECTORY)
    for candidate in candidates:
        if (candidate / "cookiecutter.json").is_file():
            return candidate
    raise ScaffoldError(
        f"This ChartBook has no project template (looked in {', '.join(map(str, candidates))}). "
        f"Reinstall it: pip install --force-reinstall chartbook"
    )


def template_commit(package_dir: Optional[Path] = None) -> Optional[str]:
    """The commit of ChartBook's repository that the template came from, or None if it is not known.

    A built package records it (``built_from.txt``, written at build time).
    A source checkout is asked with git for its ``HEAD``, without the
    environment's git location variables, as other reads of a repository
    here are.
    """
    package_dir = Path(package_dir) if package_dir is not None else _package_dir()
    template = find_template(package_dir)
    if template.parent == package_dir:
        recorded = package_dir / BUILT_FROM
        if recorded.is_file():
            return recorded.read_text(encoding="utf-8").strip() or None
        return None
    from chartbook.gitcache import GIT_LOCATION_VARIABLES

    checkout = template.parent
    environment = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES}

    def git(*arguments) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(checkout), *arguments],
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    # The checkout's own repository, not one it happens to sit inside
    top = git("rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != checkout.resolve():
        return None
    return git("rev-parse", "HEAD") or None


@dataclass(frozen=True)
class Rendered:
    """A project :func:`render` made: its folder, and the template commit its ``.cruft.json`` names."""

    project_dir: Path
    commit: Optional[str]


def render(
    output_dir: Path,
    no_input: bool = False,
    answers: Optional[dict] = None,
    package_dir: Optional[Path] = None,
) -> Rendered:
    """Render a new project from the template that came with this ChartBook, into *output_dir*.

    The questions are asked as cookiecutter asks them (``no_input`` takes
    the defaults, and *answers*, by name), and the template's hooks run.
    The template's private ``_chartbook_version`` is this ChartBook's
    version, which the project's environment files ask for at least. Then
    ``.cruft.json`` is written as ``cruft create`` writes it.

    :raises cookiecutter.exceptions.CookiecutterException: If cookiecutter
        refuses, as when a hook stops it (the template's own hooks print why).
    """
    from cookiecutter.config import get_user_config
    from cookiecutter.generate import generate_context, generate_files
    from cookiecutter.prompt import prompt_for_config

    from chartbook.__about__ import __version__

    template = find_template(package_dir)
    commit = template_commit(package_dir)
    context = generate_context(
        context_file=str(template / "cookiecutter.json"),
        default_context=get_user_config()["default_context"],
        extra_context={**(answers or {}), VERSION_VARIABLE: __version__},
    )
    context["cookiecutter"] = prompt_for_config(context, no_input)
    # What cruft adds, so that the context is the one `cruft create` would record
    context["cookiecutter"]["_template"] = TEMPLATE_REPOSITORY
    context["cookiecutter"]["_commit"] = commit
    project_dir = Path(
        generate_files(repo_dir=str(template), context=context, overwrite_if_exists=False, output_dir=str(output_dir))
    )
    write_cruft_file(project_dir, context, commit)
    return Rendered(project_dir, commit)


def write_cruft_file(project_dir: Path, context: dict, commit: Optional[str]) -> Path:
    """Write ``.cruft.json`` as ``cruft create`` does, naming the template on GitHub.

    ``cruft update`` and ``cruft check`` read it, and clone the template from
    :data:`TEMPLATE_REPOSITORY` at ``commit``. With no commit known it holds
    ``null``, which ``cruft update`` cannot start from: ``chartbook init``
    says so.
    """
    state = {
        "template": TEMPLATE_REPOSITORY,
        "commit": commit,
        "checkout": None,
        "context": context,
        "directory": TEMPLATE_DIRECTORY,
        "skip": [],
    }
    path = Path(project_dir) / CRUFT_MARKER
    # cruft's own layout (cruft._commands.utils.cruft.json_dumps)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n", encoding="utf-8")
    return path


def git_init_and_commit(project_dir: Path) -> None:
    """Make *project_dir* a git repository holding one commit of everything in it.

    The project's own ``.gitignore`` (the template ships one) decides what
    "everything" means.

    :raises ScaffoldError: If a git command fails, saying which.
    """
    # Name the first branch "main" unless the user has said what they want.
    # Unconfigured, git still calls it "master" and prints a hint about it,
    # and a repository pushed to GitHub keeps whatever name it arrives with.
    chosen = _run(["git", "config", "--get", "init.defaultBranch"], cwd=project_dir)
    if chosen.returncode == 0 and chosen.stdout.strip():
        init_attempts = [["git", "init"]]
    else:
        # The second is for a git too old to know the option
        init_attempts = [["git", "init", f"--initial-branch={DEFAULT_BRANCH}"], ["git", "init"]]

    def failed(command, result):
        return ScaffoldError(
            f"'{' '.join(command[:2])}' failed in {project_dir}:\n"
            f"{_detail(result)}\n"
            f"The project itself was created. Fix the problem above and "
            f"finish by hand with: git init && git add --all && git commit"
        )

    for command in init_attempts:
        result = _run(command, cwd=project_dir)
        if result.returncode == 0:
            break
    else:
        raise failed(command, result)

    for command in (
        ["git", "add", "--all"],
        ["git", "commit", "-m", INITIAL_COMMIT_MESSAGE],
    ):
        result = _run(command, cwd=project_dir)
        if result.returncode != 0:
            raise failed(command, result)


def github_create_and_push(project_dir: Path, public: bool = False) -> str:
    """Create a GitHub repository for *project_dir* and push its commit.

    The repository is named after the directory, belongs to the account gh is
    logged in as, and becomes the ``origin`` remote.

    :param project_dir: A git repository with at least one commit.
    :param public: Create a public repository. Private by default.
    :returns: The new repository's URL.
    :raises ScaffoldError: If gh fails, with the command to finish by hand.
    """
    command = [
        "gh",
        "repo",
        "create",
        project_dir.name,
        "--public" if public else "--private",
        "--source",
        ".",
        "--remote",
        "origin",
        "--push",
    ]
    result = _run(command, cwd=project_dir)
    if result.returncode != 0:
        raise ScaffoldError(
            f"gh could not create the GitHub repository:\n"
            f"{_detail(result)}\n"
            f"The project and its first commit are in {project_dir}. Fix the "
            f"problem above and finish from that directory with:\n"
            f"    {' '.join(command)}"
        )
    # gh prints the URL, then whatever git said while pushing
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    urls = [line for line in lines if line.startswith(("https://", "http://"))]
    return urls[0] if urls else (lines[0] if lines else "")
