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
commit the template is at (:func:`template_commit`), so ``cruft update`` and
``cruft check`` follow the template from there; with no commit known there
is no ``.cruft.json``, and ``chartbook init`` says how to make one. cruft
itself would clone the template, which a wheel's folder is not. A source
checkout renders only the files git tracks in ``template/``, as a wheel
built from it ships.

With ``--git`` it also runs ``git init`` and makes the first commit; with
``--github`` it then creates a GitHub repository and pushes that commit.
These are the same three commands every time, run here through ``git`` and
``gh`` as subprocesses, with the user's existing configuration and login.

Everything that can be checked is checked *before* the template is rendered
(:func:`preflight`), so a missing tool or login fails with nothing created.
"""

from __future__ import annotations

import contextlib
import importlib.resources
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

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


def _git(checkout: Path, *arguments: str) -> Optional[str]:
    """What git says in *checkout*, or None if it fails; without the environment's git location variables."""
    from chartbook.gitcache import GIT_LOCATION_VARIABLES

    environment = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), *arguments], capture_output=True, text=True, env=environment, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _source_checkout(template: Path, package_dir: Path) -> Optional[Path]:
    """The git checkout a source template is in, if it is that checkout's own; None for a packaged one."""
    if template.parent == package_dir:
        return None
    checkout = template.parent
    # The checkout's own repository, not one it happens to sit inside
    top = _git(checkout, "rev-parse", "--show-toplevel")
    if not top or Path(top.strip()).resolve() != checkout.resolve():
        return None
    return checkout


def template_commit(package_dir: Optional[Path] = None) -> Optional[str]:
    """The commit of ChartBook's repository that the template is at, or None if it is not known.

    A built package records it (``built_from.txt``, written at build time).
    A source checkout is asked with git for its ``HEAD``, without the
    environment's git location variables, as other reads of a repository
    here are; a ``template/`` with changes git has not committed is at no
    commit, and neither is a folder that is not a checkout of its own.
    """
    package_dir = Path(package_dir) if package_dir is not None else _package_dir()
    template = find_template(package_dir)
    if template.parent == package_dir:
        recorded = package_dir / BUILT_FROM
        if recorded.is_file():
            return recorded.read_text(encoding="utf-8").strip() or None
        return None
    checkout = _source_checkout(template, package_dir)
    if checkout is None:
        return None
    changed = _git(checkout, "status", "--porcelain", "--", TEMPLATE_DIRECTORY)
    if changed is None or changed.strip():
        return None
    return (_git(checkout, "rev-parse", "HEAD") or "").strip() or None


def commit_is_pushed(commit: str, package_dir: Optional[Path] = None) -> Optional[bool]:
    """Whether a source checkout has *commit* on a remote-tracking branch: True, False, or None if it cannot tell.

    ``cruft update`` clones the template from GitHub, so the commit that
    ``.cruft.json`` names must be there. A built package cannot tell.
    """
    package_dir = Path(package_dir) if package_dir is not None else _package_dir()
    checkout = _source_checkout(find_template(package_dir), package_dir)
    if checkout is None:
        return None
    branches = _git(checkout, "branch", "--remotes", "--contains", commit)
    if branches is None:
        return None
    return bool(branches.strip())


@contextlib.contextmanager
def _template_to_render(template: Path, package_dir: Path) -> Iterator[Path]:
    """The template as a package ships it: in a source checkout, only the files git tracks.

    A wheel built from the checkout carries those files and no others
    (``hatch_build.py``), so a source install renders the same set: a
    git-ignored ``.env`` or ``.ipynb_checkpoints/`` in ``template/`` is not
    rendered, while a change to a tracked file is, at its content on disk.
    """
    checkout = _source_checkout(template, package_dir)
    listed = _git(checkout, "ls-files", "-z", "--", TEMPLATE_DIRECTORY) if checkout is not None else None
    if not listed:
        yield template
        return
    with tempfile.TemporaryDirectory(prefix="chartbook-template-") as scratch:
        for name in listed.split("\0"):
            source = checkout / name
            if name and source.is_file():
                target = Path(scratch) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        yield Path(scratch) / TEMPLATE_DIRECTORY


def _make_writable(project_dir: Path) -> None:
    """Let the owner write all that was rendered.

    cookiecutter copies the template's file modes, so a template installed
    read-only (a Nix store, a locked tree on a cluster) made a read-only
    project.
    """
    for root, folders, files in os.walk(project_dir):
        for name in [*folders, *files]:
            path = Path(root) / name
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
    project_dir.chmod(project_dir.stat().st_mode | stat.S_IWUSR)


@dataclass(frozen=True)
class Rendered:
    """A project :func:`render` made.

    Its folder; the template commit its ``.cruft.json`` names, None when it
    has none; and whether that commit is on a remote branch of the checkout
    ChartBook runs from (None when that cannot be told).
    """

    project_dir: Path
    commit: Optional[str]
    pushed: Optional[bool] = None


def render(
    output_dir: Path,
    no_input: bool = False,
    answers: Optional[dict] = None,
    package_dir: Optional[Path] = None,
) -> Rendered:
    """Render a new project from the template that came with this ChartBook, into *output_dir*.

    The questions are asked as cookiecutter asks them (``no_input`` takes
    the defaults, and *answers*, by name), and the template's hooks run.
    The project's environment files ask for the template's
    ``_chartbook_version``, which is this ChartBook's version (a test keeps
    the two equal). Then ``.cruft.json`` is written as ``cruft create``
    writes it, when the template's commit is known; with none, there is no
    commit for ``cruft update`` to start from, and no file.

    :raises cookiecutter.exceptions.CookiecutterException: If cookiecutter
        refuses, as when a hook stops it (the template's own hooks print why)
        or the project's folder is there already.
    """
    from cookiecutter.config import get_user_config
    from cookiecutter.generate import generate_context, generate_files
    from cookiecutter.prompt import prompt_for_config

    package_dir = Path(package_dir) if package_dir is not None else _package_dir()
    template = find_template(package_dir)
    commit = template_commit(package_dir)
    with _template_to_render(template, package_dir) as source:
        context = generate_context(
            context_file=str(source / "cookiecutter.json"),
            default_context=get_user_config()["default_context"],
            extra_context=answers or {},
        )
        context["cookiecutter"] = prompt_for_config(context, no_input)
        # What cruft adds, so that the context is the one `cruft create` would record
        context["cookiecutter"]["_template"] = TEMPLATE_REPOSITORY
        context["cookiecutter"]["_commit"] = commit
        # A hook that stops it is said by the hook, and by chartbook init
        # after it; cookiecutter's log of it would add a traceback
        quiet = logging.NullHandler()
        logging.getLogger("cookiecutter").addHandler(quiet)
        try:
            project_dir = Path(
                generate_files(
                    repo_dir=str(source), context=context, overwrite_if_exists=False, output_dir=str(output_dir)
                )
            )
        finally:
            logging.getLogger("cookiecutter").removeHandler(quiet)
    _make_writable(project_dir)
    if commit is None:
        return Rendered(project_dir, None)
    write_cruft_file(project_dir, context, commit)
    return Rendered(project_dir, commit, commit_is_pushed(commit, package_dir))


def write_cruft_file(project_dir: Path, context: dict, commit: str) -> Path:
    """Write ``.cruft.json`` as ``cruft create`` does, naming the template on GitHub.

    ``cruft update`` and ``cruft check`` read it, and clone the template from
    :data:`TEMPLATE_REPOSITORY` at ``commit``. It has no ``skip``, as
    ``cruft create`` writes none: ``cruft update`` adds the project's own
    skips to one that is there, again on every run.
    """
    state = {
        "template": TEMPLATE_REPOSITORY,
        "commit": commit,
        "checkout": None,
        "context": context,
        "directory": TEMPLATE_DIRECTORY,
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
