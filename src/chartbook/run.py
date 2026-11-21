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

- **It never builds in a folder the pipeline depends on**, unless asked
  to with ``--upstream``. A ``path`` dependency is a directory somebody
  works in. They may be half-way through a change. This pipeline reads
  what is pinned, not what is there, so running that folder's build would
  disturb its owner and change nothing this pipeline reads. It is its
  owner's to build; ``--upstream`` builds and snapshots one with no
  snapshot to pin, for folders that are yours.
- **A git dependency is built once, in a clean copy.** Nobody works in
  ChartBook's own copy of a commit, so there is nothing to disturb. The
  build runs in a writable copy of the checkout
  (:meth:`chartbook.gitcache.GitCache.work_copy`), which is how data that a
  repository builds and does not commit comes to be there to pin. It is
  built once for a commit. ``force`` builds it again, which is how data
  that is pulled from outside is refreshed on purpose.
- **What has no pin yet is pinned**, just before the build, so the
  pipeline's code can read it. **A pin that exists is never moved.**
  ``chartbook pin --update`` is the only thing that moves one.

In a catalog, the script is run in each of the catalog's pipelines, one
that another of them depends on first.

This is not a task runner. There is one string per script name, no
dependencies between scripts, no retries, no schedule and no history. See
"Running things" and "Not doing" in ``docs_src/design/asset-graph.md``, and
"The snapshot model" in ``docs_src/design/overview.md`` for why a pipeline
is never built from the outside in.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

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
    RequiresChartbookError,
    _read_manifest_file,
    get_pipeline_dirs,
    load_manifest,
    read_scripts,
    resolve_project_type,
    validate_dependencies,
)
from chartbook.resolve import BATCH_ENV_VAR, MANIFEST_NAME, UNDECLARED_ENV_VAR
from chartbook.store import ReadOnlyStoreError, Store, StoreError, default_store


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

    A build script that calls ``chartbook run`` in
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


#: The file each build tool reads its tasks from, at a pipeline's top, by the word that runs the tool.
BUILD_TOOL_FILES = {
    "doit": ("dodo.py",),
    "make": ("GNUmakefile", "makefile", "Makefile"),
    "just": ("justfile", "Justfile", ".justfile"),
}

# `chartbook build`, or `python -m chartbook.cli build`
_CHARTBOOK_BUILD = re.compile(r"(?<![\w-])chartbook(?:\.cli)?\s+build(?![\w-])")


def _tool_files(directory: Path, command: Optional[str]) -> list[str]:
    """The task files of the build tools *command* runs, as named in *directory*; every tool's when *command* is None."""
    words = set(re.findall(r"[A-Za-z0-9_.-]+", command)) if command is not None else set(BUILD_TOOL_FILES)
    wanted = [name for tool, names in BUILD_TOOL_FILES.items() if tool in words for name in names]
    try:
        present = set(os.listdir(directory))  # the name as it is on disk, on a disk that ignores case too
    except OSError:
        return []
    return [name for name in wanted if name in present]


def _runs_build(value: str) -> bool:
    """Whether a command line runs `chartbook build` on this pipeline: not on another, by --project-dir."""
    return bool(_CHARTBOOK_BUILD.search(value)) and "--project-dir" not in value


def _in_python(text: str) -> Optional[tuple[int, str]]:
    """The first line of Python source whose code runs `chartbook build`: in a string, or as `"chartbook", "build"`.

    Read with Python's own tokenizer, so a comment is no code, and a
    triple-quoted string (a docstring, a block of text) is not taken for a
    command.
    """
    import io
    import tokenize

    strings: list[tuple[int, str]] = []  # the string tokens of the current run of `"a", "b", ...`
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    for token in tokens:
        if token.type == tokenize.STRING:
            raw = token.string
            body = raw.lstrip("rRbBuUfF")
            if body.startswith(('"""', "'''")):
                strings = []
                continue
            value = body[1:-1] if len(body) >= 2 else body
            if _runs_build(value):
                return token.start[0], value
            strings.append((token.start[0], value))
            if len(strings) >= 2 and strings[-2][1] == "chartbook" and strings[-1][1] == "build":
                return strings[-2][0], "chartbook build"
        elif token.type == tokenize.OP and token.string == ",":
            continue
        elif token.type in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            continue
        else:
            strings = []
    return None


def _in_recipes(text: str) -> Optional[tuple[int, str]]:
    """The first line of a Makefile or a justfile that runs `chartbook build`, a comment cut off first."""
    for number, line in enumerate(text.splitlines(), 1):
        code = re.split(r"(?:^|\s)#", line, maxsplit=1)[0]
        if _runs_build(code):
            return number, code.strip()
    return None


def build_tool_runs_chartbook_build(
    directory: Union[str, Path], command: Optional[str] = None
) -> Optional[tuple[str, int, str]]:
    """A line of a pipeline's build tool's own file that runs ``chartbook build``: the file, the line number, what it runs.

    Before 0.2.0, ``chartbook build`` rendered the site, and a ``dodo.py``
    task said ``chartbook build -f`` to do it. From 0.2 through 0.3 that
    command ran the build script first; 0.4 removes it. Such tasks must
    now use ``chartbook docs build -f``. Only
    the task file of the tool *command* runs is read: ``dodo.py`` for doit,
    a ``Makefile`` for make, a ``justfile`` for just (each, with *command*
    None). What is not run is not taken: a comment, a docstring, a
    ``chartbook build --project-dir`` of another pipeline.

    :param command: The pipeline's build command, as ``[scripts] build`` says it.
    :returns: The first such line, or None.
    """
    directory = Path(directory)
    for name in _tool_files(directory, command):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = _in_python(text) if name.endswith(".py") else _in_recipes(text)
        if found is not None:
            return name, found[0], found[1]
    return None


def kept_missing(directory: Union[str, Path], store: Optional[Store] = None) -> list:
    """The assets a pipeline marks ``keep = true`` that are not on disk while a snapshot in the store holds them.

    For each: its reference within the pipeline, its path as declared, and
    the newest snapshot of the pipeline holding its bytes, in the store and
    whole (:func:`chartbook.snapshot.newest_holder`). This is the one
    moment a build would make a costly asset again that could be put back
    instead (``docs_src/design/keep.md``): an asset no snapshot holds has
    to be made, and nothing is said of it. A pipeline that is not in git
    has no snapshots, and a shallow clone sees only the commits it has.

    :raises ValueError: If the manifest cannot be read.
    """
    from chartbook import hashing
    from chartbook.resolve import declared_files

    directory = Path(directory).resolve()
    marked = snapshots.keeps_of(_read_manifest(directory))
    if not marked:
        return []
    declared = {str(local): (path, absolute) for local, path, absolute in declared_files(directory)}
    missing = []
    for name in sorted(marked):
        if name not in declared:
            continue  # a table or a query: nothing on disk to miss
        found = hashing.find_files(declared[name][1])
        if found is None or not found.files:
            missing.append(name)
    if not missing:
        return []
    store = store if store is not None else default_store()
    try:
        history = snapshots.history(directory, store)
    except snapshots.SnapshotError:
        return []
    held = []
    for name in missing:
        # The one `chartbook restore` would use, by the same rule: a version
        # whose bytes are not in the store is nothing to put back, so the
        # build is not stopped for it
        holder, _ = snapshots.newest_holder(history, store, name)
        if holder is not None:
            held.append((name, declared[name][0], holder))
    return held


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
            ``run`` was given, or a member of the catalog it was given),
            ``"upstream"`` (with ``--upstream``, a ``path`` dependency on
            this machine with no snapshot to pin, built and snapshotted
            first) or ``"git"`` (a git dependency of one of those).
        scripts: Its named scripts.
        has_dependencies: Whether it declares any.
        missing: Why it cannot be run, if it cannot: it could not be fetched.
        built: For a ``git`` dependency, whether its build has already
            finished in this working copy.
        snapshot_first: With ``--upstream``, whether it is snapshotted once
            built, before what pins it: an upstream, and a catalog member
            another pipeline of the run pins by path that has no snapshot.
    """

    id: str
    directory: Optional[Path]
    source: str
    scripts: dict = field(default_factory=dict)
    has_dependencies: bool = False
    missing: str = ""
    built: bool = False
    snapshot_first: bool = False


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
        snapshots: The snapshot made of each pipeline after its build, as
            :class:`chartbook.snapshot.SnapshotReport`.
        undeclared: Where a build failed: the pipelines its code read, from
            the pipeline's own folder, that its manifest does not declare,
            as the reads named them and in the order they were refused.
            ``chartbook run`` offers to declare the first.
        to_snapshot: The pipelines asked for that were built and not
            snapshotted, the run not having been asked to, and that declare
            something a snapshot holds. A run makes no snapshot unless it
            is told to (``docs_src/design/one-command.md``), and
            ``chartbook run`` ends by naming the command that makes one.
        not_in_store: Where the pipeline asked for could not be pinned for
            want of pipelines to build: what it reads that is not in the
            store, each after everything it reads
            (:class:`chartbook.missing.Listing`). ``reason`` is
            :data:`NOT_IN_STORE` where that is all that stopped the run.
    """

    script: str
    ran: list[Step] = field(default_factory=list)
    skipped: list[tuple[Step, str]] = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    to_snapshot: list[Step] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    not_in_store: Optional[object] = None
    failed: Optional[Step] = None
    exit_code: int = 0
    reason: str = ""


#: A run's ``reason`` where all that stopped it is in its ``not_in_store``: the list says the rest.
NOT_IN_STORE = "what it reads is not in your store"


def _a_store_to_send_it_to(store: Optional[Store], pipeline: str) -> Optional[str]:
    """For a snapshot refused because the catalog sends its pipeline nowhere and its first store may only be read: the name of the first store that may be written; None otherwise.

    A catalog's first store is where everything goes that it sends nowhere
    by name (a pin's copies, a lockfile's note, a snapshot), so a class's
    read-only store listed ahead of one's own stops every snapshot until
    the catalog says where this pipeline goes. Where no store of the
    catalog may be written, there is nowhere to send it, and nothing to say.
    """
    try:
        entries = getattr(store if store is not None else default_store(), "entries", None) or []
    except Exception:  # noqa: BLE001 - only to say more of an error already had
        return None
    if not entries or not entries[0].read_only or any(pipeline in entry.pipelines for entry in entries):
        return None
    return next((entry.name for entry in entries if not entry.read_only), None)


def way_out_said(store: Optional[Store], pipeline: str) -> str:
    """How to send a pipeline to a store that can be written, where the catalog's first store refused its snapshot because it may only be read: one sentence, or nothing where there is no such way.

    Said by ``chartbook snapshot`` after its error, and by a run that is
    asked for a snapshot before it builds. It says to add the pipeline to
    the store's ``pipelines``, and not what the line is to be: the store
    may be sent other pipelines already, and a line pasted over that one
    would send them back. The catalog's file is named whole.
    """
    other = _a_store_to_send_it_to(store, pipeline)
    if other is None:
        return ""
    try:
        catalog = getattr(store if store is not None else default_store(), "catalog", None)
    except Exception:  # noqa: BLE001 - only to say more of an error already had
        catalog = None
    return f'To send this one to {other}: add "{pipeline}" to `pipelines` under [stores.{other}] in {catalog or "catalog.toml"}.'


def only_read_said(error: Exception, store: Optional[Store], pipeline: str) -> str:
    """A store's refusal of a snapshot because it may only be read, with the way out where there is one: what a run that is asked for a snapshot says before it builds."""
    said = str(error).rstrip(".")
    way = way_out_said(store, pipeline)
    if not way:
        return said + "."
    return f"{said}, and it is the catalog's first, where a pipeline the catalog sends nowhere is written.\n  {way}"


def _no_store_to_write(store: Optional[Store], pipeline: str) -> str:
    """Why a snapshot of a pipeline would be refused by a store that may only be read, asked before anything is built; empty where it would not be.

    Asked of the catalog's stores as the snapshot asks it
    (``Stores.for_writing``), and only for this: a store that the catalog
    says may only be read is how the catalog is written, and an hour of
    building mends nothing. A store that is away may be back by the end
    of a build, and is the snapshot's to say then, as it was. So is a
    folder that the system will not let this user write, which no catalog
    says: nothing here tries a write.
    """
    try:
        stores = store if store is not None else default_store()
        for_writing = getattr(stores, "for_writing", None)
        if for_writing is None:
            return ""
        for_writing(pipeline)
    except ReadOnlyStoreError as error:
        return only_read_said(error, store, pipeline)
    except Exception:  # noqa: BLE001 - whatever else is wrong with the stores is said where it was, by what meets it next
        return ""
    return ""


def _declares_what_a_snapshot_holds(directory: Path) -> bool:
    """Whether a pipeline declares anything a snapshot could hold: an asset with a path, or a dataframe in a source.

    One that does not yet is told nothing of snapshots at the end of a
    run: there is nothing of it for one to take.
    """
    from chartbook.manifest import section_that_is_no_table
    from chartbook.resolve import declared_files, declared_in_source

    try:
        if section_that_is_no_table(_read_manifest(directory), MANIFEST_NAME):
            return True  # it means to declare something: the snapshot says what is wrong with how
        return bool(declared_files(directory)) or bool(declared_in_source(directory))
    except (OSError, ValueError):
        return True  # a manifest that cannot be read is said by what reads it next


def unwritten(directory: Union[str, Path]) -> list[tuple[str, str]]:
    """What a pipeline's manifest declares with a path that a build is to write, and that is not there: each as ``chartbook path`` names it, with its path as declared.

    Read from the raw ``chartbook.toml``, as a snapshot reads it, and asked
    as a snapshot asks: an asset is there when its path holds a file, so a
    folder with nothing in it, or a pattern that matches nothing, is not.
    A dataframe, a chart, a notebook, a model, the scores a model declares
    (``metrics_path``), a files asset and the file of a DuckDB source are
    looked for. A dataframe that is a table or a query in a source has no
    file of its own (its source's file is what the build writes), and a
    note is prose kept in git, which no build writes: neither is.

    :raises OSError: If there is no ``chartbook.toml`` there to read.
    :raises ValueError: If it is not valid TOML.
    """
    from chartbook import hashing
    from chartbook.resolve import declared_files

    # Whole, so that a source's file is not looked for under the folder's own name a second time
    directory = Path(os.path.abspath(directory))
    missing = []
    for local, declared, absolute in declared_files(directory):
        if local.kind == "note":
            continue
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            missing.append((str(local), declared))
    models = _read_manifest(directory).get("models") or {}
    for name in sorted(models) if isinstance(models, dict) else ():
        scores = models[name].get("metrics_path") if isinstance(models[name], dict) else None
        if isinstance(scores, str) and scores.strip() and not os.path.isfile(os.path.normpath(directory / scores)):
            missing.append((f"model/{name}'s scores", scores))
    # The file of a DuckDB source: what its tables and queries are read from, and what a snapshot writes them out of
    from chartbook.backends import MEMORY_URL, duckdb_path
    from chartbook.manifest import validate_sources

    declared_sources = _read_manifest(directory).get("sources")
    for name in sorted(declared_sources) if isinstance(declared_sources, dict) else ():
        try:
            # One at a time: a source that does not read (`chartbook run --check` says which, and why)
            # is passed over, and does not take the look at the others with it
            source = validate_sources({name: declared_sources[name]}, directory)[name]
            url = source.get("_resolved_url")
            if source.get("backend") != "duckdb" or not url or url == MEMORY_URL:
                continue
            path = Path(duckdb_path(url, directory))
        except (ValueError, KeyError, TypeError):
            continue
        if not path.is_file():
            try:
                shown = "./" + path.resolve().relative_to(directory.resolve()).as_posix()
            except ValueError:
                shown = str(path)
            missing.append((f"source {name}", shown))
    return missing


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
    upstream: bool = False,
) -> list[Step]:
    """Say which pipelines a run is about, in order.

    That is the pipeline in *project_dir*, or every pipeline of the catalog
    there, each after any other of them that it depends on. With *git*, it
    is also their ``git`` dependencies, each before what depends on it: a
    git dependency is fetched if it has to be and given a working copy,
    which is the only thing here that changes anything.

    A ``path`` dependency is not in the order. It is a folder somebody
    works in, and it is theirs to build. With *upstream*, one that has no
    snapshot a pin would take, and is not pinned yet, is: built and
    snapshotted before what depends on it (``"upstream"``), and so are its
    own, as far up as they go.

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
    :param upstream: Whether a ``path`` dependency with no snapshot to pin
        is in the order, to be built and snapshotted first.
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
        raise RunError("A catalog lists stored snapshots. Run `chartbook run` in a pipeline, or orchestrate pipelines with doit.")
    roots = [start]
    asked = set(roots)

    order: list[Step] = []
    #: The run's own pipelines a pin of another of them needs snapshotted first (--upstream)
    snapshot_first: set[Path] = set()
    done: set[Path] = set()
    visiting: list[Path] = []
    caches = [git_cache]  # made only if some pipeline has a git dependency
    found_in_store: list = [None]  # read only if some pipeline names a dependency by its ID
    host: list = [None]  # the default host, read likewise
    by_id: list = [None]

    def asked_by_id() -> dict:
        """The pipelines of this run, by their own ID."""
        if by_id[0] is None:
            by_id[0] = {}
            for there in asked:
                try:
                    raw = _read_manifest(there)
                except (OSError, ValueError):
                    continue
                by_id[0][derive_pipeline_id(raw.get("project") or {}, there)] = there
        return by_id[0]

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
        except RequiresChartbookError as error:
            if source == "git":
                # Its path is ChartBook's own copy, which says nothing to the user
                raise RequiresChartbookError(f"the git dependency {name!r}: {error}") from None
            raise
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
        if git and any(entry.get("_store") for entry in dependencies.values()):
            # One named by its ID that pin will get from its repository on the
            # default host (lock.clone_instead, the one decision both make) is
            # built as a git one is. One that is a pipeline of this run is
            # built here, before it, and never cloned.
            if host[0] is None:
                from chartbook.config import get_default_host

                host[0] = get_default_host()

            def in_store() -> list:
                if found_in_store[0] is None:
                    found_in_store[0] = snapshots.readable_snapshots(store if store is not None else default_store())[0]
                return found_in_store[0]

            try:
                locked = lock.read_lock(directory)
            except lock.LockError:
                locked = None
            listed = {entry.get("id"): entry for entry in (locked.dependencies if locked else [])}
            own = derive_pipeline_id(raw.get("project") if isinstance(raw.get("project"), dict) else {}, directory)
            def as_pin_will(key: str, entry: dict) -> dict:
                pinned = bool(locked) and lock.holds_a_pin(listed.get(key), locked.assets_of(key))
                if entry.get("_store") and entry.get("rev") and entry["_store"] not in asked_by_id():
                    # What `rev` means is asked of its repository, as pin asks it
                    if caches[0] is None:
                        caches[0] = default_git_cache()
                    kind, value = lock.choose_for_rev(
                        entry, own, listed.get(key), False, in_store, host[0], caches[0], directory, pinned=pinned
                    )
                    return value if kind == "entry" else entry
                return lock.clone_instead(entry, own, listed.get(key), False, in_store, host[0], asked_by_id(), pinned=pinned)

            dependencies = {key: as_pin_will(key, entry) for key, entry in dependencies.items()}

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
                    if entry.get("_from_id"):
                        got_from = f"{strip_url_credentials(entry['git'])} ({entry.get('_from', '[resolve] default_host')})"
                        if copy is None:
                            why = f"it is got from its repository, {got_from}, and {why}"
                        else:
                            # Got from its repository by its ID: it must call itself that, or it is not built
                            named = lock._project_id_in(copy)
                            if named and named != entry["_from_id"]:
                                copy, why = None, f"its repository, {got_from}, names itself {named}, not {entry['_from_id']}"
                    if copy is None:
                        order.append(Step(key, None, "git", missing=why))
                    else:
                        visit(copy, "git", key)
                elif entry.get("_store"):
                    # Named by its ID alone: its snapshots are read from the
                    # store, and nothing of it is built here, unless it is a
                    # pipeline of this run, which is built before it
                    there = asked_by_id().get(entry["_store"])
                    if there is not None and there != directory:
                        visit(there, "asked", key)
                else:
                    # A folder somebody works in is not built from here. It
                    # is in the order only if it was asked for itself, as
                    # another pipeline of the same catalog.
                    there = Path(entry["_resolved_path"]).resolve()
                    # With --upstream, from what this run is about only (not a git
                    # dependency's own manifest): built and snapshotted first
                    wanted = (
                        upstream and source in ("asked", "upstream") and BUILD_SCRIPT in scripts
                        and _nothing_to_pin(directory, key, entry, there, store)
                    )
                    if there in asked:
                        if wanted:
                            snapshot_first.add(there)
                        visit(there, "asked", key)
                    elif wanted:
                        visit(there, "upstream", key)
            visiting.pop()

        done.add(directory)
        project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
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
    import dataclasses

    return [
        dataclasses.replace(
            step,
            snapshot_first=step.source == "upstream"
            or (step.directory is not None and step.directory in snapshot_first and BUILD_SCRIPT in step.scripts),
        )
        for step in order
    ]


def _cycle(step: Step, store: Optional[Store], git_cache: Optional[GitCache], lockfiles=None, shared=None, members=None):
    """The first cycle among the pipelines a step depends on, if there is one (:func:`chartbook.lineage.cycle`).

    :param lockfiles: Lockfiles as a pin would write them, by folder, read
        in place of the files there.
    :param shared: Shared between walks with nothing written in between,
        so that the store is read once.
    :param members: The run's own pipelines, their folders by ID.
    :raises RunError: If the step's folder no longer holds a pipeline.
    """
    from chartbook import lineage

    try:
        return lineage.cycle(
            step.directory, store, pipeline=step.id, git_cache=git_cache, lockfiles=lockfiles, shared=shared,
            members=members,
        )
    except snapshots.SnapshotError as error:  # the folder changed under the run
        raise RunError(f"{step.id}: {error}") from None


def _snapshot_first(loop, steps: list, script: str, store: Optional[Store]) -> str:
    """Under --snapshot, what to do when a pin the run would make is of a snapshot a pipeline of the run will replace.

    The walk before the run takes the snapshot the store has now: the run
    cannot know which one a pin will take once it has made more. If that
    one leads back and the pipeline has since dropped the dependency, its
    new snapshot first breaks the cycle. Said only where it would: the
    pipeline has no snapshot at its commit yet (one that has may be given
    back unchanged), and the pin takes its newest (not narrowed to a
    commit, a revision or a repository).
    """
    from chartbook import missing

    snapshotted = {
        step.id: step for step in steps
        if step.source in ("asked", "upstream") and step.directory is not None and script in step.scripts
    }
    for edge in [*loop.way_in, *loop.edges]:
        member = snapshotted.get(edge.dependency)
        declarer = snapshotted.get(edge.pipeline)
        if member is None or declarer is None or "it would now be pinned to its snapshot at" not in edge.where:
            continue
        try:
            entry = (_read_manifest(declarer.directory).get("dependencies") or {}).get(edge.key)
            code = snapshots.code_of(member.directory)
            there_already = snapshots.find(store if store is not None else default_store(), code.commit, code.subdirectory)
        except Exception:  # noqa: BLE001 - nothing to say then
            continue
        if not isinstance(entry, dict) or any(entry.get(narrowed) for narrowed in ("commit", "rev", "repository")):
            continue
        if there_already:
            continue
        return (
            f"\nThe pin of {member.id} is of the snapshot the store has of it now, which this run would replace "
            f"with --snapshot. If {member.id} no longer depends on what leads back here, make its new snapshot "
            f"first (`chartbook run --snapshot --project-dir {missing._quoted(member.directory)}`), and run this again."
        )
    return ""


def _cycle_said(loop) -> str:
    """What a run says of a cycle: who is in it, and each edge with where it was read."""
    from chartbook import lineage

    return f"{lineage.cycle_lead(loop)}, so there is no order to build in.\n{lineage.explain_cycle(loop)}"


@contextlib.contextmanager
def _alone_while_built(step: Step, echo: Callable[[str], None], snapshotted: bool):
    """A build that ends in a snapshot, one at a time for its folder, across processes: runs that build it take turns.

    An upstream of two runs, a catalog member, or the owner's own ``chartbook
    run --snapshot``. The lock is a file under the cache, as a pin's is,
    keyed by the folder; a run that has to wait for it says so. Not where
    this build is what runs the command (:func:`running`): the run refuses
    that, and a lock would wait for itself.
    """
    if not snapshotted or step.directory is None or running(step.directory, BUILD_SCRIPT):
        yield
        return
    key = Path(step.directory) / ".chartbook-snapshot-build"
    if lock.held_elsewhere(key):
        echo(f"{step.id}: another run is building it to make a snapshot; waiting for it")
    with lock._one_at_a_time(key):
        yield


def _nothing_to_pin(directory: Path, key: str, entry: dict, there: Path, store: Optional[Store]) -> bool:
    """Whether a ``path`` dependency has no pin and no snapshot a pin would take: what ``--upstream`` builds and snapshots.

    A folder that holds no pipeline is not, and the pin says so. One that
    is not in git is, and is refused before anything runs, since it can
    have no snapshot.
    """
    if not (there / MANIFEST_NAME).is_file():
        return False
    try:
        if resolve_project_type(_read_manifest(there), str(there / MANIFEST_NAME)) != "pipeline":
            return False  # a catalog: the pin says so
    except (OSError, ValueError):
        return False  # a manifest that cannot be read: the pin says so
    try:
        locked = lock.read_lock(directory)
    except lock.LockError:
        locked = None
    listed = next((e for e in (locked.dependencies if locked else []) if e.get("id") == key), None)
    if locked is not None and lock._has_a_pin(listed, locked.assets_of(key), entry):
        return False
    try:
        snapshots.code_of(there)
    except snapshots.SnapshotError:
        return True  # not in git: refused, saying so, before anything runs
    try:
        newest, _ = snapshots.newest_for(there, store if store is not None else default_store())
    except (snapshots.SnapshotError, StoreError, OSError, ValueError):
        return False  # a record that cannot be read now: the pin says so, and nothing is built for it
    return newest is None


def _require_trust_to_run(steps: list, script: str, here: Path) -> None:
    """Refuse unless every pipeline whose script would run is one the user trusts to run.

    A script is code, and a folder is trusted to run it only when the
    user has said so (``chartbook trust``; ``docs_src/design/trust.md``).
    That is the pipeline asked for, or each pipeline of the catalog asked
    for that has the script, and with ``--upstream`` each upstream folder
    it builds. A ``git`` dependency is built in ChartBook's own copy of
    its commit: naming it in ``[dependencies]`` is the trust for that, and
    it is not asked about here.

    :raises RunError: Naming each folder that is not trusted to run, with
        its ID and the command that trusts it.
    """
    from chartbook.config import trust_of

    refused = []
    for step in steps:
        if step.source not in ("asked", "upstream") or step.directory is None or script not in step.scripts:
            continue
        level = trust_of(step.directory)
        if level != "run":
            refused.append((step, level))
    if not refused:
        return

    def standing(level: Optional[str]) -> str:
        return "trusted to render, not to run" if level == "render" else "not trusted"

    if len(refused) == 1 and refused[0][0].directory == here:
        step, level = refused[0]
        raise RunError(
            f"{step.id} is {standing(level)}, so its {script!r} script was not run. A build script is "
            f"code, and it runs here once you say the pipeline is yours to run: `chartbook trust` in "
            f"{step.directory} trusts it."
        )
    listed = "\n".join(
        f"  {step.id}: {step.directory} ({standing(level)}{', an upstream --upstream would build' if step.source == 'upstream' else ''})"
        for step, level in refused
    )
    remedy = (
        "`chartbook trust` in a folder trusts that one, once you have read what its build runs; "
        "`chartbook trust FOLDER` trusts a folder and every pipeline under it."
    )
    raise RunError(
        f"These pipelines are not trusted to run, so nothing was run:\n{listed}\n"
        f"A build script is code, and it runs here once you say the pipeline is yours to run: {remedy}"
    )


def execute(
    script: str, directory: Path, name: Optional[str] = None, foreign: bool = False, undeclared: Optional[list] = None
) -> int:
    """Run one script in a directory, and return its exit code.

    The script is handed to a shell whole, so a value of several lines is
    one script: what one line sets up, the next can use. It stops at the
    first command that fails. Its output goes where this process's does.

    The shell is ``bash`` where there is one, because that is what an
    ``module load`` or a ``conda activate`` expects, and ``sh`` otherwise.
    On Windows it is ``cmd``: one line is run as it is, and several go in
    a batch file that stops at the first line that fails, with its exit
    code (:func:`_batch_script`).

    :param name: The script's name in ``[scripts]``. With it, the script
        is told which pipeline and which script it is (:func:`running`).
    :param foreign: Whether the directory is a git dependency's working
        copy, the cache's: then git in the script is not told of any other
        repository the environment names (a git hook's ``GIT_DIR``).
    :param undeclared: A list that each read the script was refused, of a
        pipeline its manifest does not declare, is added to: the pipeline
        asked for, the reference as written and the folder of the pipeline
        that asked (:func:`chartbook.resolve._note_an_undeclared_read`).
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
    if foreign:
        # A git dependency's working copy, which is the cache's: git in its
        # build must find that copy, never the repository a git hook says
        from chartbook.gitcache import GIT_LOCATION_VARIABLES

        environment = {k: v for k, v in environment.items() if k not in GIT_LOCATION_VARIABLES}
        # Nor the repository the git cache may be inside (a home kept in git):
        # the copy has no .git of its own, and git looks no further up
        environment["GIT_CEILING_DIRECTORIES"] = str(Path(directory).resolve().parent)
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
    # A run that started this one, where this is a script a build runs (`build = "chartbook run analyze"`):
    # its file is left named for a script that is not asked about, and is told what this one's reads were
    outer = environment.get(UNDECLARED_ENV_VAR, "").strip()
    notes = None
    if undeclared is not None:
        try:
            # A file of its own for this script's refused reads, which the reads are told of by its name
            handle, notes = tempfile.mkstemp(prefix="chartbook-undeclared-", suffix=".jsonl")
            os.close(handle)
            environment[UNDECLARED_ENV_VAR] = notes
        except OSError:
            notes = None  # nowhere to note them: the build runs all the same, and nothing is offered
    try:
        code = _execute(script, directory, environment)
        if notes is not None:
            found = _undeclared_reads(notes)
            undeclared.extend(found)
            if outer and found:
                try:
                    descriptor = os.open(outer, os.O_WRONLY | os.O_APPEND)
                    try:
                        os.write(descriptor, "".join(json.dumps(note) + "\n" for note in found).encode("utf-8"))
                    finally:
                        os.close(descriptor)
                except OSError:
                    pass
    finally:
        if notes is not None:
            try:
                os.remove(notes)
            except OSError:
                pass
    return 128 - code if code < 0 else code


def _undeclared_reads(notes: str) -> list[dict]:
    """The reads a script was refused, as it noted them: each a pipeline, a reference and a folder; a line that is not one is passed over."""
    found = []
    try:
        # Whatever a build wrote there: bytes that are no text are no note, and never the failure of a build that went well
        with open(notes, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
        return found
    for line in lines:
        try:
            note = json.loads(line)
        except ValueError:
            continue
        if isinstance(note, dict) and all(isinstance(note.get(key), str) and note[key] for key in ("pipeline", "reference", "from")):
            found.append(note)
    return found


def _execute(script: str, directory: Path, environment: dict) -> int:
    if os.name == "nt":
        named = directory
        try:
            directory = _as_cmd_takes_it(directory)
        except RunError as error:
            raise RunError(f"{error} The script was not run.") from None
        above = os.fspath(named).replace("/", "\\").rstrip("\\").rsplit("\\", 1)[0]
        if directory is not named and environment.get("GIT_CEILING_DIRECTORIES", "").replace("/", "\\").rstrip("\\") == above:
            # Git in the script stands on the letter: the folder it is to look no further up than, by that name
            # too. Only where that folder is this one's own, as it is set for a git dependency's copy: one the
            # person set for themselves is theirs, and is left as it is
            environment = {
                **environment,
                "GIT_CEILING_DIRECTORIES": environment["GIT_CEILING_DIRECTORIES"] + os.pathsep + directory.rstrip("\\").rsplit("\\", 1)[0],
            }
        if "\n" not in script.strip():
            return subprocess.run(
                script, shell=True, cwd=directory, env=environment
            ).returncode
        # cmd takes one line; several go in a file, which cmd reads in the
        # console's code page (the OEM one), with \r\n line endings
        handle, name = tempfile.mkstemp(suffix=".cmd", text=True)
        try:
            with os.fdopen(handle, "w", encoding=_batch_encoding(), newline="\r\n") as f:
                try:
                    f.write(_batch_script(script))
                except UnicodeEncodeError as error:
                    raise RunError(
                        f"{script.strip().splitlines()[0]!r}…: the script holds {error.object[error.start:error.end]!r}, "
                        f"which cmd cannot read in this console's code page. Put the lines with it in a script "
                        f"file of their own (a .py, say), and run that file from [scripts]."
                    ) from None
            return subprocess.run(
                ["cmd", "/d", "/c", name], cwd=directory, env=environment
            ).returncode
        finally:
            os.unlink(name)
    shell = shutil.which("bash") or "/bin/sh"
    return subprocess.run(
        [shell, "-e", "-c", script], cwd=directory, env=environment
    ).returncode


def _as_cmd_takes_it(directory: Union[str, Path]) -> Union[str, Path]:
    """A folder as ``cmd.exe`` can stand in it: one that is a share (``\\\\server\\…``), by a drive letter the share is connected under.

    ``cmd.exe`` runs a script on Windows, and takes no share as its
    current folder. Started in one, it says "UNC paths are not
    supported", goes to ``C:\\Windows``, runs the script there, and ends
    with whatever the script ends with: a build that is one line of shell
    ran in the Windows folder, and the run said it had built. A folder on
    a drive letter that is a share is such a folder too, since a folder
    is followed to where it really is, and ``Z:\\work`` really is
    ``\\\\server\\home\\work``: a home folder on a network is met so, by
    someone who never typed a ``\\\\``.

    So the script is run from the letter, found among the drive letters
    that are connected to a share. Where the share has none, nothing is
    run, and the way on is said.

    :raises RunError: For a share that no drive letter is connected to.
        Its words end with the way on: whoever raises it on says what was
        not done.
    """
    text = os.fspath(directory)
    if text[:4] in ("\\\\?\\", "\\\\.\\") and text[4:8].upper() != "UNC\\":
        # The long spelling of a folder on a drive, which is that folder; and whatever else is spelled so
        # (a device, a volume) is no share, and is left as it was given
        return text[4:] if text[5:7] == ":\\" else directory
    if not text.replace("/", "\\").startswith("\\\\"):
        return directory  # as it was given: nothing of it is changed
    lettered = _by_its_drive_letter(text, _connected_drives())
    if lettered is None:
        from chartbook.missing import _quoted

        share = "\\".join(_share_parts(text)[:4])
        raise RunError(
            f"{text} is a network folder with no drive letter, and cmd.exe, which runs a script on Windows, takes "
            f"no such folder as its own: it would have run the script in C:\\Windows. Connect the share to a drive "
            f"letter (`net use Q: {_quoted(share, windows=True)}`, with a letter that is free), and run this again."
        )
    return lettered


def _share_parts(text: str) -> list[str]:
    """A share's path in parts, as ``\\\\server\\share\\folder`` has them: two empty ones, the server, the share, and the rest."""
    text = text.replace("/", "\\")
    if text.upper().startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]  # the long spelling of the same share
    return text.rstrip("\\").split("\\")


def _by_its_drive_letter(text: str, connected: Iterable[tuple[str, str]]) -> Optional[str]:
    """A folder of a share by a drive letter connected to that share, or to a folder of it above this one; None where there is none.

    :param connected: Each letter with a share it is connected to, as
        Windows names it: ``[("Z:", "\\\\server\\home")]``. A letter
        may be there under more than one name of its share.
    """
    parts = _share_parts(text)
    found = None
    for letter, remote in connected:
        under = _share_parts(remote)
        if len(under) < 4:
            continue  # no share: a server alone, or nothing
        if len(under) > len(parts) or [part.lower() for part in parts[:len(under)]] != [part.lower() for part in under]:
            continue
        if found is None or len(under) > found[0]:  # the letter nearest the folder: the shortest path, and a share's own letter
            found = (len(under), "\\".join([letter.rstrip("\\"), *parts[len(under):]]))
    if found is None:
        return None
    return found[1] if "\\" in found[1] else found[1] + "\\"  # `Z:` alone is wherever one last stood on it


def _connected_drives() -> list[tuple[str, str]]:
    """The drive letters that are connected to a share, each with its share; none on another system.

    A letter is given under each name its share has here: the one Windows
    says it was connected as, and the one its own folder is followed to,
    which is how a pipeline's folder on it was named. They differ where a
    share is reached through a name that stands for several servers.
    """
    import string

    found: list[tuple[str, str]] = []
    try:
        import ctypes

        ask = ctypes.WinDLL("mpr").WNetGetConnectionW
    except (AttributeError, ImportError, OSError):
        return found
    for letter in string.ascii_uppercase:
        try:
            size = ctypes.c_ulong(1024)
            share = ctypes.create_unicode_buffer(size.value)
            if ask(f"{letter}:", share, ctypes.byref(size)) != 0 or not share.value:
                continue
            found.append((f"{letter}:", share.value))
            followed = os.path.realpath(f"{letter}:\\")
            if followed.startswith("\\\\") and followed.rstrip("\\").lower() != share.value.rstrip("\\").lower():
                found.append((f"{letter}:", followed))
        except (OSError, ValueError):
            continue
    return found


def _no_script_in_a_share_without_a_letter(steps: Iterable, script: str, windows: Optional[bool] = None) -> None:
    """Stop a run on Windows, before anything is built, where a pipeline that was asked for is in a share that no drive letter is connected to.

    Its script could not be run (:func:`_as_cmd_takes_it`), and that is
    known now: not after an hour of building what it depends on. Only of
    a pipeline that was asked for and has the script: what it depends on
    may not be built at all (an upstream that has its snapshot, a git
    dependency that is built), and is refused when its script is reached,
    if it is.
    """
    if not (os.name == "nt" if windows is None else windows):
        return
    for step in steps:
        if step.source != "asked" or step.directory is None or script not in step.scripts:
            continue
        try:
            _as_cmd_takes_it(step.directory)
        except RunError as error:
            raise RunError(f"{step.id}: {error} Nothing was built.") from None


def _batch_encoding() -> str:
    """The code page cmd reads a batch file in: the console's (chcp can change it), else the OEM one.

    Both are Windows' alone; elsewhere it is UTF-8.
    """
    import codecs

    try:
        import ctypes

        page = ctypes.windll.kernel32.GetConsoleOutputCP()  # 0 with no console
        if page:
            codecs.lookup(f"cp{page}")
            return f"cp{page}"
    except (AttributeError, ImportError, OSError, LookupError):
        pass
    try:
        codecs.lookup("oem")
    except LookupError:
        return "utf-8"
    return "oem"

#: Stops a batch file where the line before it failed, with that line's exit code.
_STOP_ON_FAILURE = "if %errorlevel% neq 0 exit /b %errorlevel%"


def _batch_script(script: str) -> str:
    """A script of several lines as a batch file that stops at the first line that fails.

    ``cmd`` runs a batch file to its end whatever each line returns, and the
    file's exit code is its last line's, where ``bash -e`` stops at the first
    failure. So each command line is followed by a line that exits with the
    last exit code when it is not zero. A blank line, a ``rem`` or ``::``
    comment, and a line continued with a ``^`` at its end get no such line,
    since they run nothing of their own. ``@echo off`` comes first, so the
    lines are not echoed as they run, as a shell does not echo them.

    A block in parentheses (``if ... (`` over several lines) is read by cmd
    as one command, with ``%errorlevel%`` expanded once, before the block
    runs; so a failure inside it is caught at the line after the block, not
    inside it.

    :param script: The script, as the manifest gives it.
    :returns: The text of the batch file.
    """
    lines = ["@echo off"]
    for line in script.splitlines():
        lines.append(line)
        stripped = line.strip()
        is_comment = stripped.startswith("::") or stripped.lower() == "rem" or stripped.lower().startswith("rem ")
        if not stripped or is_comment or stripped.endswith("^"):
            continue
        lines.append(_STOP_ON_FAILURE)
    return "\n".join(lines) + "\n"


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
    remake: bool = False,
    remake_command: str = "chartbook run --remake",
    upstream: bool = False,
    complete: bool = False,
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
        records that the build ran in the same command. It refuses to
        build where that is not so, and fails if no snapshot can be made
        (``--snapshot``). Without it no snapshot is made of a pipeline
        asked for, which is what ``chartbook run`` does when it is told
        nothing: the report's ``to_snapshot`` then names what was built.
    :param on_snapshot: Called with a pipeline's step and its
        :class:`chartbook.snapshot.SnapshotReport` after its snapshot is made.
    :param frozen: Write nothing before the build but, where the store can
        be written, its note that this machine reads these pins
        (:func:`chartbook.lock.note_this_machine`): no pin, no fetch, no
        lockfile, no object. Instead check that the lockfile is complete and
        every pin is in the store (:func:`chartbook.lock.verify`), and
        refuse to build if not. A ``git`` dependency is not built either;
        its pins have to be there. For CI, and for a store one may only read.
    :param on_verify: Called with a pipeline's step and its
        :class:`chartbook.lock.FrozenReport`, under *frozen*.
    :param remake: Run ``build`` even though an asset the manifest marks
        ``keep = true`` is not on disk while the store has a version of it.
        Without it, that stops the command before anything is built, since
        the build would make the costly asset again
        (:func:`kept_missing`, ``docs_src/design/keep.md``).
    :param remake_command: The command line that says *remake*, for the
        message: ``chartbook run --remake`` from ``chartbook run``.
    :param upstream: Before the pipelines asked for, build and snapshot each
        ``path`` dependency on this machine that has no snapshot to pin and
        is not pinned yet, its own first, so that it can be pinned
        (``--upstream``). Each must be trusted to run and have everything
        committed, as a snapshot needs, and its build must leave it so; the
        first that fails stops the run, before anything that depends on it.
    :param complete: With *snapshot*: keep the snapshot of a pipeline that
        was asked for complete in the store, whatever the store would
        choose (:func:`chartbook.snapshot.make`). A pipeline built first
        for *upstream* is kept as the store chooses.
    :returns: What was run, and what failed if anything did.
    :raises RunError: If the pipelines cannot be put in an order, the one
        asked for has no such script, a pipeline it builds depends, through
        what it depends on, on itself, or would once the run pinned what it
        depends on (found before anything is pinned or run), or a kept
        asset is missing while the store has it and *remake* is not set. A
        pin that would still lead into a cycle when its turn comes (a
        dependency changed by a build earlier in the run) is not written,
        and the report says so.
    """
    here = Path(project_dir).resolve()
    building = script == BUILD_SCRIPT
    snapshot = bool(snapshot)
    if snapshot and os.path.lexists(here / "chartbook.links.toml"):
        raise RunError("Cannot snapshot while chartbook.links.toml exists. Delete it, run `chartbook pin --update`, then snapshot.")
    if frozen and snapshot:
        raise RunError(
            "--frozen pins nothing and writes no object, and --snapshot writes a snapshot. One or the other."
        )
    if frozen and not building:
        raise RunError(
            f"--frozen is about what `{BUILD_SCRIPT}` pins before it runs, and "
            f"`chartbook run {script}` pins nothing, so `--frozen` has nothing to check."
        )
    if upstream and frozen:
        raise RunError("--frozen writes nothing, and --upstream builds and snapshots upstream pipelines. One or the other.")
    if upstream and not building:
        raise RunError(
            f"--upstream builds what `{BUILD_SCRIPT}` pins, and `chartbook run {script}` pins nothing."
        )
    # Under --frozen a git dependency is neither fetched nor built: what is
    # pinned of it has to be in the store already, and verify() checks that
    steps = plan(here, git_cache, git=building and not frozen, force=force, store=store, upstream=upstream)
    upstreams = [step for step in steps if step.source == "upstream"]
    for step in upstreams:
        if script not in step.scripts:
            raise RunError(
                f"{step.id}, in {step.directory}, has no snapshot to pin and no `{BUILD_SCRIPT}` script, so "
                f"--upstream cannot build it. Its owner makes a snapshot with `chartbook snapshot` there. "
                f"Nothing was built."
            )
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
    _require_trust_to_run(steps, script, here)
    _no_script_in_a_share_without_a_letter(steps, script)
    if snapshot and not building:
        raise RunError(
            f"A snapshot is of what `{BUILD_SCRIPT}` makes, so `chartbook run "
            f"{script} --snapshot` has nothing to take one of."
        )
    if snapshot or any(step.snapshot_first for step in steps):
        # Found out now, and not after an hour of building. The lockfile
        # does not count: the pin before the build is about to write it,
        # and the snapshot records what it says in `inputs`. An upstream is
        # always snapshotted: that is what a pin of it takes
        for step in steps:
            snapshotted = (snapshot and step.source == "asked") or step.snapshot_first
            if snapshotted and step.directory and script in step.scripts:
                try:
                    code = snapshots.require_committed(
                        step.directory, step.id, ignoring=(lock.LOCK_FILE,)
                    )
                    snapshots.check_within(step.directory, step.id)
                except snapshots.SnapshotError as error:
                    why = (
                        " With --upstream it is snapshotted after its build, since another pipeline of this run pins it by path."
                        if step.snapshot_first and step.source == "asked" and not snapshot else ""
                    )
                    raise RunError(f"{error}{why} Nothing was built.") from None
                try:
                    # A store that takes no snapshot (laid out as ChartBook 0.5 laid one out, say) says so now too
                    snapshots.check_store_takes_one(step.id, store)
                except StoreError as error:
                    raise RunError(f"{error} Nothing was built.") from None
                except OSError:
                    pass  # a store that cannot be reached is said where the snapshot is made, as before
                # And a store that may only be read would refuse it after the build: said now, with the way out
                only_read = _no_store_to_write(store, step.id)
                if only_read:
                    raise RunError(f"{step.id} cannot have a snapshot: {only_read} Nothing was built.")
                commits_before[step.directory] = code.commit
    # Dependencies between pipelines form a directed acyclic graph. Each
    # pipeline the run builds is walked now, before anything is pinned,
    # written or run, with the pins the run would make worked out and not
    # written (lock.would_pin): a cycle a new pin would close is found here
    # too, and in a catalog no pipeline is built when one is in a cycle
    would_be: dict = {}
    # The pipelines of the run, by ID: one named by its ID is walked through its folder
    members = {
        step.id: step.directory for step in steps if step.source in ("asked", "upstream") and step.directory is not None
    }
    # The store's snapshots, read once for the walks below and the pins' own
    shared: dict = {}
    if building:
        # Every pipeline asked for (a catalog's members, with a build script
        # or not), and each git dependency the run builds
        walked = [
            step for step in steps
            if step.directory is not None and step.has_dependencies
            and not (step.source == "git" and (script not in step.scripts or (step.built and not force)))
        ]
        if not frozen:
            for step in walked:
                if script not in step.scripts:
                    continue  # it pins nothing in this run
                try:
                    after = lock.would_pin(step.directory, store, git_cache, built_here=set(members))
                except (lock.LockError, StoreError, ValueError, OSError) as error:
                    # What its pin would say in its turn, said before anything is built
                    raise RunError(f"{step.id}: {error}\nNothing was pinned or built.") from None
                if after is not None:
                    would_be[step.directory] = after
        for step in walked:
            loop = _cycle(step, store, git_cache, would_be, shared, members)
            if loop is not None:
                raise RunError(
                    f"{step.id}: {_cycle_said(loop)}{_snapshot_first(loop, steps, script, store) if snapshot else ''}"
                    f"\nNothing was pinned or built."
                )
        # The pins' own walks below come after builds that may make snapshots
        shared["may_be_old"] = True

    if building and not remake:
        # A costly output that is not on disk while the store has a version
        # of it: found out now, before any pipeline's build remakes it
        said, own, upstream_folders = [], False, []
        for step in steps:
            if step.source not in ("asked", "upstream") or step.directory is None or script not in step.scripts:
                continue
            for name, declared, taken in kept_missing(step.directory, store):
                said.append(
                    f"{step.id}: {name} is kept, and is not on disk ({declared}). The store has its version "
                    f"from {taken.commit[:7]}, made {taken.made_at[:10]} {taken.made_at[11:16]} UTC."
                )
                if step.source == "upstream":
                    if step.directory not in upstream_folders:
                        upstream_folders.append(step.directory)
                else:
                    own = True
        if said:
            from chartbook import missing

            them = "them" if len(said) > 1 else "it"
            # An upstream's own are put back from its own folder
            restore = (["chartbook restore"] if own else []) + [
                f"chartbook restore --project-dir {missing._quoted(folder)}" for folder in upstream_folders
            ]
            again = f"{remake_command} --upstream" if upstream else remake_command
            lines = [f"\n  {command}{' ' * max(1, 28 - len(command))}puts {them} back" for command in restore]
            raise RunError(
                "\n".join(said)
                + "".join(lines)
                + f"\n  {again}{' ' * max(1, 28 - len(again))}runs the build without {them}, which makes {them} again"
                + "\nNothing was built."
            )

    report = RunReport(script=script)
    if upstreams:
        # Said before anything runs: what --upstream builds, and snapshots, that is not this run's own
        echo("Upstream with no snapshot to pin, built and snapshotted first:")
        for step in upstreams:
            echo(f"  {step.id}    in {step.directory}")
    members_first = [step for step in steps if step.snapshot_first and step.source == "asked" and not snapshot]
    if members_first:
        echo("Pipelines of this run that another pins by path, snapshotted after their build:")
        for step in members_first:
            echo(f"  {step.id}    in {step.directory}")
    for step in steps:
        wrote_lockfile = False
        with _alone_while_built(step, echo, (snapshot and step.source == "asked") or step.snapshot_first):
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

            if step.source == "upstream":
                # Another run may have made its snapshot while this one waited: then it is not built again
                try:
                    newest, _ = snapshots.newest_for(step.directory, store if store is not None else default_store())
                except (snapshots.SnapshotError, StoreError, OSError, ValueError):
                    echo(f"{step.id}: its snapshots cannot be read now; not built")
                    report.skipped.append((step, "its snapshots cannot be read now"))
                    continue
                if newest is not None:
                    echo(f"{step.id}: has a snapshot now, from {newest.commit[:7]}; not built again")
                    report.skipped.append((step, "it has a snapshot now"))
                    continue
            if (snapshot and step.source == "asked") or step.snapshot_first:
                # Found committed before the run, and maybe waited for since: still as it was
                try:
                    now = snapshots.require_committed(step.directory, step.id, ignoring=(lock.LOCK_FILE,)).commit
                except snapshots.SnapshotError as error:
                    report.failed, report.exit_code = step, 1
                    report.reason = f"{str(error).rstrip('.')}. It changed before its turn came, and was not built"
                    break
                if now != commits_before.get(step.directory, now):
                    report.failed, report.exit_code = step, 1
                    report.reason = (
                        f"its repository moved from {commits_before[step.directory][:7]} to {now[:7]} before its "
                        f"turn came, so it was not built: it was checked at {commits_before[step.directory][:7]}"
                    )
                    break

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
                # Nothing is written but the store's note that this machine
                # reads these pins, so that gc elsewhere keeps them. Either
                # every pin can be had, or nothing runs. Checked whether or not
                # the manifest has dependencies now: a lockfile may still list
                # one it dropped.
                checked = lock.verify(step.directory, store, note=True)
                if on_verify is not None:
                    on_verify(step, checked)
                if checked.problems:
                    report.failed, report.exit_code = step, 1
                    report.reason = (
                        "its lockfile is not complete, or a pin is not in the store, "
                        "and --frozen pins nothing"
                    )
                    break
            elif building and step.has_dependencies:
                # What its code reads from other pipelines has to be pinned
                # before it runs. Nothing that is pinned is moved. A pin that
                # would lead into a cycle is not written: walked with the
                # lockfiles of the pipelines still to come as they were worked
                # out above, since what was built since may have changed them
                def refuse_a_cycle(after, step=step):
                    loop = _cycle(step, store, git_cache, {**would_be, step.directory: after}, shared, members)
                    if loop is None:
                        return None
                    into = "lead into" if loop.way_in else "close"
                    return (
                        f"pinning what it depends on would {into} a cycle: {_cycle_said(loop)}\n"
                        f"Its lockfile was left as it was, and it was not built"
                    )

                pins = lock.pin(
                    step.directory, store, git_cache,
                    built_here=set(members),
                    before_writing=refuse_a_cycle,
                )
                if pins.refused:
                    report.failed, report.exit_code = step, 1
                    report.reason = pins.refused
                    break
                would_be.pop(step.directory, None)  # written now: its file is what holds
                wrote_lockfile = pins.written
                no_order = None
                if pins.problems and step.source == "asked":
                    # What it reads that is not in the store, and what each of those reads: the
                    # list, in the order to build it (docs_src/design/one-command.md)
                    from chartbook import missing

                    try:
                        pins.not_in_store = missing.after_pin(step.directory, pins, store, git_cache, echo)
                    except missing.NoOrder as error:
                        no_order = error
                    report.not_in_store = pins.not_in_store
                if on_pin is not None:
                    on_pin(step, pins)
                if no_order is not None:
                    report.failed, report.exit_code = step, 1
                    report.reason = f"{no_order}\nIt was not built"
                    break
                if pins.problems:
                    report.failed, report.exit_code = step, 1
                    listed = pins.not_in_store.keys if pins.not_in_store is not None else set()
                    report.reason = (
                        NOT_IN_STORE if listed and all(event.dependency in listed for event in pins.problems)
                        else "what it depends on could not be pinned"
                    )
                    break

            if building and ((snapshot and step.source == "asked") or step.snapshot_first):
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
            old_frozen = os.environ.get("CHARTBOOK_FROZEN")
            if frozen:
                os.environ["CHARTBOOK_FROZEN"] = "1"
            refused: list = []
            try:
                code = execute(
                    command, step.directory, script, foreign=step.source == "git",
                    undeclared=refused if building and step.source == "asked" else None,
                )
            finally:
                if frozen:
                    if old_frozen is None:
                        os.environ.pop("CHARTBOOK_FROZEN", None)
                    else:
                        os.environ["CHARTBOOK_FROZEN"] = old_frozen
            # What its own code read and its manifest does not declare: only reads made from this
            # pipeline's folder, since another's manifest is not this run's to write. Said of a build
            # that fails, by its script or by what it did not write
            its_own = []
            for note in refused:
                try:
                    same = os.path.samefile(note["from"], step.directory)  # however either is spelled
                except OSError:
                    same = note["from"] == str(step.directory.resolve())
                if same and note["pipeline"] not in its_own:
                    its_own.append(note["pipeline"])
            if code != 0:
                report.failed, report.exit_code = step, code
                report.reason = f"its {script!r} script exited with {code}"
                report.undeclared = its_own
                break
            if step.source == "git":
                mark_built(step.directory)
            report.ran.append(step)

            if building and step.source in ("asked", "upstream"):
                # What chartbook.toml declares, the build is to write: one it did not is a build
                # that went wrong, whatever its script exited with, and nothing of it is a version
                try:
                    forgotten = unwritten(step.directory)
                except (ValueError, OSError):
                    forgotten = []  # a manifest the build has made unreadable is found by what reads it next
                if forgotten:
                    things = "1 thing" if len(forgotten) == 1 else f"{len(forgotten)} things"
                    report.failed, report.exit_code = step, 1
                    report.undeclared = its_own  # a build that went on past a read it was refused, and wrote less
                    report.reason = (
                        f"its build did not write {things} {MANIFEST_NAME} declares: "
                        + ", ".join(f"{name} ({path})" for name, path in forgotten[:10])
                        + (f", and {len(forgotten) - 10} more" if len(forgotten) > 10 else "")
                    )
                    break

            if building and step.source == "asked" and not snapshot and not step.snapshot_first:
                # Built, and no snapshot asked for: none is made, and the run's last line names the
                # command that makes one. One that declares nothing a snapshot could hold is told nothing
                if _declares_what_a_snapshot_holds(step.directory):
                    report.to_snapshot.append(step)

            if (snapshot and step.source == "asked") or step.snapshot_first:
                # A build that changes a committed file, or that commits, leaves
                # a folder the commit the build ran at does not describe, and
                # the label would not be true
                try:
                    changed = snapshots.uncommitted(step.directory, ignoring=(lock.LOCK_FILE,))
                    if changed:
                        echo(f"{step.id}: its build left files that are not committed:")
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
                        step.directory, store, built_by_run=True, ignoring=(lock.LOCK_FILE,), ask=False,
                        complete=complete and snapshot and step.source == "asked",
                    )
                except snapshots.SnapshotError as error:
                    report.failed, report.exit_code = step, 1
                    report.reason = str(error).rstrip(".")
                    break
                report.snapshots.append(made)
                if on_snapshot is not None:
                    on_snapshot(step, made)
                if step.source == "upstream" and wrote_lockfile:
                    try:
                        unrecorded = bool(snapshots._git(
                            step.directory, "status", "--porcelain", "--untracked-files=all", "--", lock.LOCK_FILE
                        ).strip())
                    except snapshots.SnapshotError:
                        unrecorded = False
                    if unrecorded:
                        echo(f"{step.id}: its {lock.LOCK_FILE} was written, and is not committed: commit it in {step.directory}.")
    return report
