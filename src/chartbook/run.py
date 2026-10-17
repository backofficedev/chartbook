"""Running a script in a pipeline.

A pipeline names its commands in ``[scripts]``. ``build`` is the one that
makes its assets current, and it is usually one word: ``doit``, ``make``,
``snakemake``. That tool decides what inside the pipeline is out of date::

    $ chartbook run
    ftsfr/rate_forecast: pinning what it depends on
    ftsfr/fed_yield_curve: 3 pinned
    Wrote chartbook.lock.
    ftsfr/rate_forecast: build

``chartbook run`` builds the pipeline it is run in. First it sees that
what the pipeline depends on can be read, and it does that without ever
touching another pipeline's working directory:

- **It never builds in a folder the pipeline depends on.** A ``path``
  dependency is a directory somebody works in. They may be half-way
  through a change. This pipeline reads what is pinned, not what is there,
  so running that folder's build would disturb its owner and change
  nothing this pipeline reads. It is its owner's to build.
- **A git dependency is built once, in a clean copy.** Nobody works in
  ChartBook's own copy of a commit, so there is nothing to disturb. The
  build runs in a writable copy of the checkout
  (:meth:`chartbook.gitcache.GitCache.work_copy`), which is how data that a
  repository builds and does not commit comes to be there to pin. It is
  built once for a commit. ``force`` builds it again, which is how data
  that is pulled from outside is refreshed on purpose.
- **What has no pin yet is pinned**, just before the build, so the
  pipeline's code can read it. **A pin that exists is never moved.**
  ``chartbook update`` is the only thing that moves one.

In a catalog, the script is run in each of the catalog's pipelines, one
that another of them depends on first.

This is not a task runner. There is one string per script name, no
dependencies between scripts, no retries, no schedule and no history. See
"Running things" and "Not doing" in ``docs_src/design/asset-graph.md``, and
"The snapshot model" in ``docs_src/design/overview.md`` for why a pipeline
is never built from the outside in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from chartbook import lock
from chartbook import snapshot as snapshots
from chartbook.gitcache import (
    GitCache,
    GitError,
    default_git_cache,
    forget_built,
    is_built,
    local_url,
    mark_built,
)
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
from chartbook.resolve import BATCH_ENV_VAR, MANIFEST_NAME
from chartbook.store import Store, default_store


#: Set for a script while ChartBook runs it: the pipeline's directory, and
#: the script's name. They are how a command that would run that same
#: script again can tell that it was called from inside it.
RUN_DIR_ENV_VAR = "CHARTBOOK_RUN_DIR"
RUN_SCRIPT_ENV_VAR = "CHARTBOOK_RUN_SCRIPT"

#: Every script ChartBook is running, outermost first, as a JSON list of
#: ``[directory, script]`` pairs, so that any character a directory can hold
#: survives. The two variables above are the innermost; this is the whole
#: chain, so that two pipelines whose scripts call each other are caught as
#: well as one that calls itself.
RUN_STACK_ENV_VAR = "CHARTBOOK_RUN_STACK"


def _stack() -> list[tuple[str, str]]:
    """The scripts this process is running inside, outermost first."""
    text = os.environ.get(RUN_STACK_ENV_VAR, "")
    if not text:
        return []
    try:
        entries = json.loads(text)
    except ValueError:
        entries = []
    found = [
        (entry[0], entry[1])
        for entry in entries
        if isinstance(entry, list) and len(entry) == 2 and all(isinstance(e, str) for e in entry)
    ]
    # The innermost is kept separately too, in two plain variables, so a
    # stack that has been mangled still stops the simplest loop
    inside, name = os.environ.get(RUN_DIR_ENV_VAR), os.environ.get(RUN_SCRIPT_ENV_VAR)
    if inside and name and (inside, name) not in found:
        found.append((inside, name))
    return found


def running(directory: Union[str, Path], script: str) -> bool:
    """Whether this process is inside that script of that pipeline.

    A build script that calls ``chartbook build`` or ``chartbook run`` in
    its own pipeline would be run by the command it calls, without end; so
    would two pipelines whose build scripts each run the other's. Every
    script ChartBook is running is in :data:`RUN_STACK_ENV_VAR`, and a
    pipeline anywhere in it is one this process is already inside.
    """
    try:
        here = Path(directory).resolve()
    except OSError:
        return False
    for inside, name in _stack():
        if name != script:
            continue
        try:
            if Path(inside).resolve() == here:
                return True
        except OSError:
            continue
    return False


class RunError(Exception):
    """Raised when the pipelines to run cannot be put in an order, or found."""


@dataclass(frozen=True)
class Step:
    """One pipeline a script may be run in, in the order they come.

    Attributes:
        id: The pipeline's name: its own ID. For a ``git`` dependency that
            could not be fetched, or whose manifest sets no ``id``, the key
            it is declared under.
        directory: Where it is, and where its script runs. For a ``git``
            dependency, its working copy. None if it could not be fetched.
        source: How it comes to be in the order: ``"asked"`` (the pipeline
            ``run`` was given, or a member of the catalog it was given) or
            ``"git"`` (a git dependency of one of those).
        scripts: Its named scripts.
        has_dependencies: Whether it declares any.
        missing: Why it cannot be run, if it cannot: it could not be fetched.
        built: For a ``git`` dependency, whether its build has already
            finished in this working copy.
    """

    id: str
    directory: Optional[Path]
    source: str
    scripts: dict = field(default_factory=dict)
    has_dependencies: bool = False
    missing: str = ""
    built: bool = False


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
        snapshots: The snapshot made of each pipeline after its build, when
            that was asked for, as :class:`chartbook.snapshot.SnapshotReport`.
    """

    script: str
    ran: list[Step] = field(default_factory=list)
    skipped: list[tuple[Step, str]] = field(default_factory=list)
    snapshots: list = field(default_factory=list)
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
    project_dir: Union[str, Path] = ".",
    git_cache: Optional[GitCache] = None,
    git: bool = True,
    force: bool = False,
    store: Optional[Store] = None,
) -> list[Step]:
    """Say which pipelines a run is about, in order.

    That is the pipeline in *project_dir*, or every pipeline of the catalog
    there, each after any other of them that it depends on. With *git*, it
    is also their ``git`` dependencies, each before what depends on it: a
    git dependency is fetched if it has to be and given a working copy,
    which is the only thing here that changes anything.

    A ``path`` dependency is never in the order. It is a folder somebody
    works in, and it is theirs to build.

    A git dependency that is built already is in the order, marked as
    built, and what *it* depends on is left out: that was needed to build
    it, and it is built. With *force* it is gone into all the same.

    :param project_dir: A pipeline's directory, or a catalog's.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param git: Whether ``git`` dependencies are in the order.
    :param force: Whether to go into a git dependency that is built already.
    :param store: The store, which says which dependencies named by their
        ID have no snapshot and so are built from the default host; this
        user's by default.
    :returns: The pipelines, each after what it depends on.
    :raises RunError: If *project_dir* holds no manifest, or two of a
        catalog's pipelines depend on each other.
    :raises ValueError: If a manifest cannot be read, or its
        ``[dependencies]`` or ``[scripts]`` is malformed.
    """
    start = Path(project_dir).resolve()
    try:
        raw = _read_manifest(start)
    except FileNotFoundError:
        raise RunError(f"No {MANIFEST_NAME} in {start}.") from None
    if resolve_project_type(raw, source=str(start / MANIFEST_NAME)) == "catalog":
        roots = [
            directory.resolve()
            for directory in get_pipeline_dirs(load_manifest(start)).values()
        ]
    else:
        roots = [start]
    asked = set(roots)

    order: list[Step] = []
    done: set[Path] = set()
    visiting: list[Path] = []
    caches = [git_cache]  # made only if some pipeline has a git dependency
    found_in_store: list = [None]  # read only if some pipeline names a dependency by its ID

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
        if git:
            # One named by its ID that the store has no snapshot of is built
            # from its repository on the default host, as a git one is

            def in_store() -> list:
                if found_in_store[0] is None:
                    found_in_store[0] = snapshots.readable_snapshots(store if store is not None else default_store())[0]
                return found_in_store[0]

            dependencies = lock._with_clones(dependencies, derive_pipeline_id(raw.get("project") or {}, directory), in_store)

        built = source == "git" and is_built(directory)
        if not built or force:
            visiting.append(directory)
            for key in sorted(dependencies):
                entry = dependencies[key]
                if "git" in entry:
                    if not git:
                        continue
                    if caches[0] is None:
                        caches[0] = default_git_cache()
                    copy, why = _working_copy(directory, key, entry, caches[0])
                    if copy is None:
                        order.append(Step(key, None, "git", missing=why))
                    else:
                        visit(copy, "git", key)
                elif entry.get("_store"):
                    # Named by its ID alone: its snapshots are read from the
                    # store, and nothing of it is built here
                    continue
                else:
                    # A folder somebody works in is not built from here. It
                    # is in the order only if it was asked for itself, as
                    # another pipeline of the same catalog.
                    there = Path(entry["_resolved_path"]).resolve()
                    if there in asked:
                        visit(there, "asked", key)
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
                built=built,
            )
        )

    for root in roots:
        visit(root, "asked", str(root))
    return order


def execute(script: str, directory: Path, name: Optional[str] = None) -> int:
    """Run one script in a directory, and return its exit code.

    The script is handed to a shell whole, so a value of several lines is
    one script: what one line sets up, the next can use. It stops at the
    first command that fails. Its output goes where this process's does.

    The shell is ``bash`` where there is one, because that is what an
    ``module load`` or a ``conda activate`` expects, and ``sh`` otherwise.
    On Windows it is ``cmd``.

    :param name: The script's name in ``[scripts]``. With it, the script
        is told which pipeline and which script it is (:func:`running`).
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
    environment = dict(os.environ)
    if name == BUILD_SCRIPT:
        # A build is a batch run: a read of another pipeline that nothing
        # would record is refused there, not warned about
        # (chartbook.resolve.batch). Another script, `lab` or `test`, is as
        # interactive as the shell it was run from.
        environment[BATCH_ENV_VAR] = "1"
    if name is not None:
        where = str(Path(directory).resolve())
        environment[RUN_DIR_ENV_VAR] = where
        environment[RUN_SCRIPT_ENV_VAR] = name
        environment[RUN_STACK_ENV_VAR] = json.dumps([*_stack(), [where, name]])
    code = _execute(script, directory, environment)
    return 128 - code if code < 0 else code


def _execute(script: str, directory: Path, environment: dict) -> int:
    if os.name == "nt":
        if "\n" not in script.strip():
            return subprocess.run(
                script, shell=True, cwd=directory, env=environment
            ).returncode
        # cmd takes one line; several go in a file
        handle, name = tempfile.mkstemp(suffix=".cmd", text=True)
        try:
            with os.fdopen(handle, "w") as f:
                f.write("@echo off\n" + script + "\n")
            return subprocess.run(
                ["cmd", "/d", "/c", name], cwd=directory, env=environment
            ).returncode
        finally:
            os.unlink(name)
    shell = shutil.which("bash") or "/bin/sh"
    return subprocess.run(
        [shell, "-e", "-c", script], cwd=directory, env=environment
    ).returncode


def run(
    project_dir: Union[str, Path] = ".",
    script: str = BUILD_SCRIPT,
    store: Optional[Store] = None,
    git_cache: Optional[GitCache] = None,
    echo: Callable[[str], None] = print,
    on_pin: Optional[Callable] = None,
    force: bool = False,
    snapshot: bool = False,
    frozen: bool = False,
    on_verify: Optional[Callable] = None,
    on_snapshot: Optional[Callable] = None,
) -> RunReport:
    """Run a script in a pipeline, or in every pipeline of a catalog.

    For ``build``, two things are done first. A ``git`` dependency that has
    not been built at its commit is built, in its working copy. And each
    pipeline's dependencies are pinned before its own script runs: what has
    no pin yet is pinned, and no pin is moved.

    Nothing is ever run in a ``path`` dependency's directory. Any other
    script is run only where it was asked for.

    The pipeline that was asked for must have the script. A pipeline of a
    catalog that has no script by that name is passed over.

    :param project_dir: A pipeline's directory, or a catalog's.
    :param script: The script to run; ``build`` by default.
    :param store: The store to pin into; this user's by default.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param echo: Called with each line that says what is being done.
    :param on_pin: Called with a pipeline's step and its
        :class:`chartbook.lock.PinReport` after its dependencies are pinned.
    :param force: Build a ``git`` dependency again even if it is built
        already. This is how data it pulls from outside is refreshed.
    :param snapshot: After a pipeline's ``build`` succeeds, make a snapshot
        of it (:mod:`chartbook.snapshot`): build, and declare the build
        ready, in one command. Everything in its folder must be committed
        before the build starts and still be when it ends. The snapshot
        records that the build ran in the same command.
    :param on_snapshot: Called with a pipeline's step and its
        :class:`chartbook.snapshot.SnapshotReport` after its snapshot is made.
    :param frozen: Write nothing before the build: no pin, no fetch, no
        lockfile, no store. Instead check that the lockfile is complete and
        every pin is in the store (:func:`chartbook.lock.verify`), and
        refuse to build if not. A ``git`` dependency is not built either;
        its pins have to be there. For CI, and for a store one may only read.
    :param on_verify: Called with a pipeline's step and its
        :class:`chartbook.lock.FrozenReport`, under *frozen*.
    :returns: What was run, and what failed if anything did.
    :raises RunError: If the pipelines cannot be put in an order, or the
        one asked for has no such script.
    """
    here = Path(project_dir).resolve()
    building = script == BUILD_SCRIPT
    if frozen and snapshot:
        raise RunError(
            "--frozen writes nothing, and --snapshot writes a snapshot. One or the other."
        )
    if frozen and not building:
        raise RunError(
            f"--frozen is about what `{BUILD_SCRIPT}` pins before it runs, and "
            f"`chartbook run {script}` pins nothing, so `--frozen` has nothing to check."
        )
    # Under --frozen a git dependency is neither fetched nor built: what is
    # pinned of it has to be in the store already, and verify() checks that
    steps = plan(here, git_cache, git=building and not frozen, force=force, store=store)
    commits_before: dict[Path, str] = {}
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
    if not any(script in step.scripts for step in steps if step.source == "asked"):
        raise RunError(f"No pipeline here has a script named {script!r}.")
    if snapshot:
        if not building:
            raise RunError(
                f"A snapshot is of what `{BUILD_SCRIPT}` makes, so `chartbook run "
                f"{script} --snapshot` has nothing to take one of."
            )
        # Found out now, and not after an hour of building. The lockfile
        # does not count: the pin before the build is about to write it,
        # and the snapshot records what it says in `inputs`.
        for step in steps:
            if step.source == "asked" and step.directory and script in step.scripts:
                try:
                    code = snapshots.require_committed(
                        step.directory, step.id, ignoring=(lock.LOCK_FILE,)
                    )
                    snapshots.check_within(step.directory, step.id)
                except snapshots.SnapshotError as error:
                    raise RunError(f"{error} Nothing was built.") from None
                commits_before[step.directory] = code.commit

    report = RunReport(script=script)
    for step in steps:
        if step.directory is None:
            echo(f"{step.id}: not run. {step.missing}")
            report.skipped.append((step, step.missing))
            continue

        command = step.scripts.get(script)
        if command is None:
            why = f"it has no script named {script!r}"
            if step.source == "asked":
                echo(f"{step.id}: not run. {why[0].upper()}{why[1:]}.")
            # A git dependency with no build script is the ordinary case of
            # a repository that commits its data. There is nothing to say.
            report.skipped.append((step, why))
            continue

        if step.source == "git":
            if step.built and not force:
                echo(f"{step.id}: built already, at {step.directory.name[:7]}")
                report.skipped.append((step, "it is built already"))
                continue
            # Until this build finishes, the copy is not a built one
            forget_built(step.directory)

        if running(step.directory, script):
            raise RunError(
                f"`chartbook run {script}` was called from {step.id}'s own "
                f"{script!r} script, which would then run itself without end. "
                f"Take it out of the script."
            )

        if building and frozen:
            # Nothing is written. Either every pin can be had, or nothing
            # runs. Checked whether or not the manifest has dependencies
            # now: a lockfile may still list one it dropped.
            checked = lock.verify(step.directory, store)
            if on_verify is not None:
                on_verify(step, checked)
            if checked.problems:
                report.failed, report.exit_code = step, 1
                report.reason = (
                    "its lockfile is not complete, or a pin is not in the store, "
                    "and --frozen writes nothing"
                )
                break
        elif building and step.has_dependencies:
            # What its code reads from other pipelines has to be pinned
            # before it runs. Nothing that is pinned is moved.
            pins = lock.pin(step.directory, store, git_cache)
            if on_pin is not None:
                on_pin(step, pins)
            if pins.problems:
                report.failed, report.exit_code = step, 1
                report.reason = "what it depends on could not be pinned"
                break

        if building and snapshot and step.source == "asked":
            # Its snapshot will carry its lineage: found out now, with what
            # was just pinned, and not after the build
            try:
                gaps = snapshots.lineage_gaps(step.directory, store)
            except (lock.LockError, ValueError) as error:
                gaps = [str(error)]
            if gaps:
                report.failed, report.exit_code = step, 1
                report.reason = (
                    "its pins do not account for every dependency, so it could not have a snapshot, "
                    "and it was not built:\n" + "\n".join(f"  {gap}" for gap in gaps)
                ).rstrip(".")
                break

        where = "" if step.directory == here else f"    in {step.directory}"
        echo(f"{step.id}: {script}{where}")
        code = execute(command, step.directory, script)
        if code != 0:
            report.failed, report.exit_code = step, code
            report.reason = f"its {script!r} script exited with {code}"
            break
        if step.source == "git":
            mark_built(step.directory)
        report.ran.append(step)

        if snapshot and step.source == "asked":
            # A build that changes a committed file, or that commits, leaves
            # a folder the commit the build ran at does not describe, and
            # the label would not be true
            try:
                changed = snapshots.uncommitted(step.directory, ignoring=(lock.LOCK_FILE,))
                if changed:
                    echo(f"{step.id}: its build changed files that are committed:")
                    for line in changed[:10]:
                        echo(f"  {line}")
                    raise snapshots.SnapshotError(
                        "its build left changes that are not committed, so no "
                        "snapshot was made"
                    )
                now = snapshots.code_of(step.directory).commit
                if now != commits_before.get(step.directory, now):
                    raise snapshots.SnapshotError(
                        f"its build moved the repository from "
                        f"{commits_before[step.directory][:7]} to {now[:7]}, so no "
                        f"snapshot was made: the label would not say which code ran"
                    )
                made = snapshots.make(
                    step.directory, store, built_by_run=True, ignoring=(lock.LOCK_FILE,)
                )
            except snapshots.SnapshotError as error:
                report.failed, report.exit_code = step, 1
                report.reason = str(error).rstrip(".")
                break
            report.snapshots.append(made)
            if on_snapshot is not None:
                on_snapshot(step, made)
    return report
