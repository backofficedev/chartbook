"""What ``chartbook init`` renders, and what it does after.

``chartbook init`` renders a project from the cookiecutter template, which
is the ``template/`` folder of ChartBook's own repository
(:data:`TEMPLATE_REPOSITORY`, :data:`TEMPLATE_DIRECTORY`). It lives beside
the code so that a command the template uses and the command itself change
in one pull request, and so that the tests here build a freshly rendered
project. It is rendered with cruft, which records where the project came
from in ``.cruft.json``, so ``cruft update`` can bring in later changes. With
``--git`` it also runs ``git init`` and makes the first commit; with
``--github`` it then creates a GitHub repository and pushes that commit.
These are the same three commands every time, run here through ``git`` and
``gh`` as subprocesses, with the user's existing configuration and login.

Everything that can be checked is checked *before* the template is rendered
(:func:`preflight`), so a missing tool or login fails with nothing created.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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


def template_command() -> list[str]:
    """The command that renders a new project from the template."""
    return ["cruft", "create", TEMPLATE_REPOSITORY, "--directory", TEMPLATE_DIRECTORY]


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


def rendered_projects(cwd: Path) -> set[Path]:
    """The cruft-rendered projects directly inside *cwd*."""
    return {
        child
        for child in cwd.iterdir()
        if child.is_dir() and (child / CRUFT_MARKER).is_file()
    }


def find_new_project(cwd: Path, before: set[Path]) -> Path:
    """Find the project cruft just rendered into *cwd*.

    The directory is named from an answer given at cruft's prompt, so it is
    found afterwards — the one rendered project that was not there before —
    rather than guessed.

    :param cwd: The directory cruft was run in.
    :param before: :func:`rendered_projects` of *cwd* from before it ran.
    :returns: The new project's directory.
    :raises ScaffoldError: If there is not exactly one new project.
    """
    new = sorted(rendered_projects(cwd) - before)
    if len(new) == 1:
        return new[0]
    found = ", ".join(p.name for p in new) if new else "none"
    raise ScaffoldError(
        f"Could not tell which directory the template was rendered into "
        f"(new projects found in {cwd}: {found}), so git was not initialized. "
        f"Run 'git init' in the new project yourself."
    )


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
