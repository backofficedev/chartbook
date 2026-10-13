"""Running a script in a pipeline, after the pipelines it depends on.

A pipeline names its commands in ``[scripts]``. ``build`` is the one that
makes its assets current, and it is usually one word: ``doit``, ``make``,
``snakemake``. That tool decides what inside the pipeline is out of date.
ChartBook decides only the order *between* pipelines::

    $ chartbook run
    ftsfr/fed_yield_curve: build    in /work/fed_yield_curve
    ftsfr/rate_forecast: build

``chartbook run`` works out which pipelines this one depends on, and those
depend on, from each one's ``[dependencies]``. It runs the script in each,
dependencies first, each in its own directory, and stops at the first that
fails. In a catalog it does the same over all the catalog's pipelines.

Before a pipeline's ``build`` runs, whatever it depends on that has no pin
yet is pinned, so that its code can read it. **A pin that exists is never
moved**: if a dependency's rebuild changed its data, this pipeline is built
against the copy it had pinned, and is told what has changed.
``chartbook update`` is still the only thing that moves a pin.

A dependency that is a git repository is built too, in a writable copy of
its checkout (:meth:`chartbook.gitcache.GitCache.work_copy`), which is how
data that it builds and does not commit comes to be there to pin. Its
build needs whatever it needs: its tools, its credentials, its network.

This is not a task runner. There is one string per script name, no
dependencies between scripts, no retries, no schedule and no history. The
only graph is over pipelines. See "Running things" and "Not doing" in
``docs_src/design/asset-graph.md``.

Nothing is skipped yet: every pipeline's script is run every time, and the
pipeline's own tool skips what it can. Skipping a whole pipeline whose
inputs have not changed comes with build records.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from chartbook import lock
from chartbook.gitcache import GitCache, GitError, default_git_cache, local_url
from chartbook.identity import derive_pipeline_id, strip_url_credentials
from chartbook.manifest import (
    BUILD_SCRIPT,
    _read_manifest_file,
    get_pipeline_dirs,
    load_manifest,
    read_scripts,
    resolve_project_type,
    validate_dependencies,
)
from chartbook.resolve import MANIFEST_NAME
from chartbook.store import Store


class RunError(Exception):
    """Raised when the pipelines to run cannot be put in an order, or found."""


@dataclass(frozen=True)
class Step:
    """One pipeline, in the order they are to be run.

    Attributes:
        id: The pipeline's name: its own ID. For one that could not be
            read, or a ``git`` dependency whose manifest sets no ``id``, the
            key it is declared under.
        directory: Where it is, and where its script runs. None if it is
            not on this disk.
        source: How it comes to be in the order: ``"asked"`` (the pipeline
            ``run`` was given, or a member of the catalog it was given),
            ``"path"`` or ``"git"`` (something one of those depends on).
        scripts: Its named scripts.
        has_dependencies: Whether it declares any.
        missing: Why it cannot be run, if it cannot: it is not here.
    """

    id: str
    directory: Optional[Path]
    source: str
    scripts: dict = field(default_factory=dict)
    has_dependencies: bool = False
    missing: str = ""


@dataclass
class RunReport:
    """What a run did.

    Attributes:
        script: The script that was run.
        ran: The pipelines it was run in, in order.
        skipped: The pipelines it was not run in, each with why.
        failed: The pipeline in which it failed, if it did.
        exit_code: 0, or the exit code of what failed.
        reason: What went wrong, when it was not the script itself.
    """

    script: str
    ran: list[Step] = field(default_factory=list)
    skipped: list[tuple[Step, str]] = field(default_factory=list)
    failed: Optional[Step] = None
    exit_code: int = 0
    reason: str = ""


def _read_manifest(directory: Path) -> dict:
    """Read a pipeline's chartbook.toml; an error in it names the file.

    Several manifests are read in one run, so "invalid statement at line 3"
    has to say whose line 3.
    """
    try:
        return _read_manifest_file(directory)
    except FileNotFoundError:
        raise
    except ValueError as error:
        manifest_path = str(directory / MANIFEST_NAME)
        if manifest_path in str(error):
            raise
        raise ValueError(f"{manifest_path}: {error}") from None


def _locked_commit(directory: Path, key: str) -> Optional[str]:
    """The commit a pipeline's lockfile pins one of its git dependencies at."""
    try:
        locked = lock.read_lock(directory)
    except lock.LockError:
        return None
    for listed in locked.dependencies if locked is not None else []:
        if listed.get("id") == key:
            return listed.get("location", {}).get("commit")
    return None


def _working_copy(
    directory: Path, key: str, entry: dict, git_cache: GitCache
) -> tuple[Optional[Path], str]:
    """A git dependency's writable copy, at the commit it is pinned at.

    The commit is the lockfile's if it names one, since a pin does not
    move; otherwise it is what the ``rev`` means now.

    :returns: The working copy, or None and why there is none.
    """
    url = local_url(entry["git"], directory)
    commit = _locked_commit(directory, key)
    try:
        if commit is None:
            commit = git_cache.get(url, entry.get("rev")).commit
        elif git_cache.files(url, commit) is None:
            git_cache.fetch(url)
        return git_cache.work_copy(url, commit), ""
    except (GitError, ValueError, OSError) as error:
        return None, f"could not fetch {strip_url_credentials(entry['git'])}: {error}"


def plan(
    project_dir: Union[str, Path] = ".", git_cache: Optional[GitCache] = None
) -> list[Step]:
    """Put a pipeline and everything it depends on in the order to run them.

    Each pipeline comes after the ones it depends on, and once, however
    many depend on it. In a catalog, every pipeline of the catalog is in
    the order, in the order the catalog lists them. A ``git`` dependency is
    fetched if it has to be, and given a working copy; that is the only
    thing here that changes anything.

    A dependency that is not on this disk is in the order all the same,
    marked as missing: it cannot be built, and what depends on it may still
    have its pins.

    :param project_dir: A pipeline's directory, or a catalog's.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :returns: The pipelines, dependencies first.
    :raises RunError: If *project_dir* holds no manifest, or two pipelines
        depend on each other.
    :raises ValueError: If a manifest's ``[dependencies]`` or ``[scripts]``
        is malformed.
    """
    start = Path(project_dir).resolve()
    try:
        raw = _read_manifest(start)
    except FileNotFoundError:
        raise RunError(f"No {MANIFEST_NAME} in {start}.") from None
    if resolve_project_type(raw, source=str(start / MANIFEST_NAME)) == "catalog":
        roots = list(get_pipeline_dirs(load_manifest(start)).values())
    else:
        roots = [start]

    order: list[Step] = []
    done: set[Path] = set()
    visiting: list[Path] = []
    caches = [git_cache]  # made only if some pipeline has a git dependency

    def visit(directory: Path, source: str, name: str) -> None:
        directory = directory.resolve()
        if directory in done:
            return
        if directory in visiting:
            loop = [*visiting[visiting.index(directory) :], directory]
            raise RunError(
                "These pipelines depend on each other, so there is no order to "
                "run them in: " + " -> ".join(str(d) for d in loop)
            )
        manifest_path = directory / MANIFEST_NAME
        try:
            raw = _read_manifest(directory)
            is_pipeline = resolve_project_type(raw, str(manifest_path)) == "pipeline"
        except FileNotFoundError:
            done.add(directory)
            order.append(Step(name, None, source, missing=f"no pipeline at {directory}"))
            return
        if not is_pipeline:
            done.add(directory)
            order.append(Step(name, None, source, missing=f"{directory} is a catalog"))
            return

        try:
            dependencies = validate_dependencies(raw.get("dependencies") or {}, directory)
            scripts = read_scripts(raw)
        except ValueError as error:
            raise ValueError(f"{manifest_path}: {error}") from None

        visiting.append(directory)
        for key in sorted(dependencies):
            entry = dependencies[key]
            if "git" in entry:
                if caches[0] is None:
                    caches[0] = default_git_cache()
                copy, why = _working_copy(directory, key, entry, caches[0])
                if copy is None:
                    order.append(Step(key, None, "git", missing=why))
                else:
                    visit(copy, "git", key)
            else:
                visit(Path(entry["_resolved_path"]), "path", key)
        visiting.pop()

        done.add(directory)
        project = raw.get("project") or {}
        if source == "git" and not project.get("id"):
            # A working copy's directory is named after a commit, and has no
            # remote to take a scope from. The name it is declared under is
            # the one that means something.
            step_id = name
        else:
            step_id = derive_pipeline_id(project, directory)
        order.append(
            Step(
                id=step_id,
                directory=directory,
                source=source,
                scripts=scripts,
                has_dependencies=bool(dependencies),
            )
        )

    for root in roots:
        visit(root, "asked", str(root))
    return order


def execute(script: str, directory: Path) -> int:
    """Run one script in a directory, and return its exit code.

    The script is handed to a shell whole, so a value of several lines is
    one script: what one line sets up, the next can use. It stops at the
    first command that fails. Its output goes where this process's does.

    The shell is ``bash`` where there is one, because that is what an
    ``module load`` or a ``conda activate`` expects, and ``sh`` otherwise.
    On Windows it is ``cmd``.

    :returns: The script's exit code. One that a signal stopped gives 128
        plus the signal's number, as a shell reports it.
    """
    # What has been said so far goes out before the script says anything,
    # or a log would have the two out of order
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass
    code = _execute(script, directory)
    return 128 - code if code < 0 else code


def _execute(script: str, directory: Path) -> int:
    if os.name == "nt":
        if "\n" not in script.strip():
            return subprocess.run(script, shell=True, cwd=directory).returncode
        # cmd takes one line; several go in a file
        handle, name = tempfile.mkstemp(suffix=".cmd", text=True)
        try:
            with os.fdopen(handle, "w") as f:
                f.write("@echo off\n" + script + "\n")
            return subprocess.run(["cmd", "/d", "/c", name], cwd=directory).returncode
        finally:
            os.unlink(name)
    shell = shutil.which("bash") or "/bin/sh"
    return subprocess.run([shell, "-e", "-c", script], cwd=directory).returncode


def run(
    project_dir: Union[str, Path] = ".",
    script: str = BUILD_SCRIPT,
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    echo: Callable[[str], None] = print,
    on_pin: Optional[Callable] = None,
) -> RunReport:
    """Run a script in a pipeline, after running it in what it depends on.

    For ``build``, each pipeline's dependencies are pinned before its own
    script runs: what has no pin yet is pinned, and no pin is moved. A
    pipeline with no ``build`` script is not pinned for, since nothing is
    run in it.

    A pipeline in the order that has no script by that name is passed over.
    The pipeline that was asked for must have one.

    :param project_dir: A pipeline's directory, or a catalog's.
    :param script: The script to run; ``build`` by default.
    :param store: The store to pin into; this user's by default.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param echo: Called with each line that says what is being done.
    :param on_pin: Called with a pipeline's step and its
        :class:`chartbook.lock.PinReport` after its dependencies are pinned.
    :returns: What was run, and what failed if anything did.
    :raises RunError: If the pipelines cannot be put in an order, or the
        one asked for has no such script.
    """
    here = Path(project_dir).resolve()
    steps = plan(here, git_cache)
    # A pipeline that is asked for by name must have the script. A catalog
    # is asked for all of its pipelines, and those without it are passed over.
    for step in steps:
        if step.directory == here and script not in step.scripts:
            declared = ", ".join(sorted(step.scripts)) or "(none)"
            raise RunError(
                f"{step.id} has no script named {script!r}. Its scripts are: "
                f"{declared}. To add it, put the command under [scripts] in "
                f'{MANIFEST_NAME}: {script} = "…".'
            )
    if not any(script in step.scripts for step in steps):
        raise RunError(f"No pipeline here has a script named {script!r}.")

    report = RunReport(script=script)
    for step in steps:
        if step.directory is None:
            echo(f"{step.id}: not run. {step.missing}")
            report.skipped.append((step, step.missing))
            continue

        command = step.scripts.get(script)
        if command is None:
            why = f"it has no script named {script!r}"
            echo(f"{step.id}: not run. {why[0].upper()}{why[1:]}.")
            report.skipped.append((step, why))
            continue

        if script == BUILD_SCRIPT and step.has_dependencies:
            # What its code reads from other pipelines has to be pinned
            # before it runs. Nothing that is pinned is moved.
            pins = lock.pin(step.directory, store, git_cache)
            if on_pin is not None:
                on_pin(step, pins)
            if pins.problems:
                report.failed, report.exit_code = step, 1
                report.reason = "what it depends on could not be pinned"
                break

        where = "" if step.directory == here else f"    in {step.directory}"
        echo(f"{step.id}: {script}{where}")
        code = execute(command, step.directory)
        if code != 0:
            report.failed, report.exit_code = step, code
            report.reason = f"its {script!r} script exited with {code}"
            break
        report.ran.append(step)
    return report
