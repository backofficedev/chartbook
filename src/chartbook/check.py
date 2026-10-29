"""The CI gate: metadata and path checks over a loaded manifest.

``chartbook check`` runs everything here and exits nonzero when any problem
is found. It looks at *metadata and paths* only — required fields under the
active policy, the files a manifest points at, the pipelines it depends on,
and license expiration dates. It never opens a data file; data-quality
checks (row counts, null rates, schema assertions) are a separate concern.

The checks are thin wrappers over machinery the build already uses:
:func:`chartbook.conf_validation.validate_source_files` for paths and
:func:`chartbook.diagnostics.build_diagnostics` for required fields.
"""

from __future__ import annotations

import fnmatch
import functools
import glob
import os
import re
import warnings
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Union

import tomli

from chartbook.conf_validation import OUTPUT_FILE_TYPES, built_nothing, validate_source_files
from chartbook.diagnostics import DOCS_FIELDS, build_diagnostics
from chartbook.identity import strip_url_credentials
from chartbook.manifest import (
    _parse_toml_file,
    _read_manifest_file,
    _resolve_policy,
    get_pipeline_dirs,
    get_pipeline_ids,
    get_pipeline_manifest,
    resolve_project_type,
)
from chartbook.resolve import declared_assets, known_as, locate_pipeline
from chartbook.utils import is_glob_pattern

#: Default window, in days, inside which an unexpired license still fails.
DEFAULT_WITHIN_DAYS = 30

#: ``license_expiration`` values that mean "this license does not expire".
#: Compared case-insensitively. Anything else must parse as a date.
NO_EXPIRATION_VALUES = frozenset({"", "n/a", "na", "none", "never"})

# MissingFile.file_type -> (manifest section, field) for per-entity files
_FILE_TYPE_FIELDS = {
    "dataframe": ("dataframes", "path"),
    "dataframe_docs": ("dataframes", "docs_path"),
    "chart": ("charts", "path"),
    "chart_docs": ("charts", "docs_path"),
    "notebook": ("notebooks", "path"),
    "note": ("notes", "path"),
    "model": ("models", "path"),
    "model_metrics": ("models", "metrics_path"),
    "model_docs": ("models", "docs_path"),
    "file": ("files", "path"),
    "file_docs": ("files", "docs_path"),
}


#: How :func:`check_paths` begins the message for an output of a pipeline that has built nothing yet
NOT_BUILT_YET = "not built yet"


def _kept(manifest: dict, missing) -> bool:
    """Whether the manifest marks a missing output ``keep = true``."""
    section = _FILE_TYPE_FIELDS[missing.file_type][0]
    try:
        entries = get_pipeline_manifest(manifest, missing.pipeline_id).get(section) or {}
    except (KeyError, ValueError):
        return False
    entry = entries.get(missing.item_id)
    return isinstance(entry, dict) and entry.get("keep") is True


def not_built_hint(manifest: dict) -> str:
    """What to run when :func:`check_paths` found a lone pipeline that has built nothing yet.

    `chartbook build` is named only when there is a build script for it to
    run, as `chartbook docs generate` names it.
    """
    build = (
        "`chartbook build` builds it"
        if manifest["project"].get("build")
        else "build its outputs (it has no build script for `chartbook build` to run)"
    )
    return f"Nothing is built yet: {build}, and the same check with --skip-outputs checks the rest without it."


@dataclass(frozen=True)
class Problem:
    """One finding, addressed by the file and field that needs editing.

    Attributes:
        file: The ``chartbook.toml`` that declares the offending entry.
        table: The TOML table within it, e.g. ``dataframes.repo_public``.
        field: The key within that table, e.g. ``license_expiration``.
        message: What is wrong with it.
    """

    file: Path
    table: str
    field: str
    message: str

    def format(self, relative_to: Optional[Path] = None) -> str:
        """Render as ``file: [table] field: message``, one line.

        :param relative_to: If given, the file is shown relative to this
            directory when it lies beneath it (shorter CI logs).
        """
        shown = display_path(self.file, relative_to)
        return f"{shown}: [{self.table}] {self.field}: {self.message}"


def display_path(path: Path, relative_to: Optional[Path] = None) -> Path:
    """Return *path* relative to *relative_to* when it lies beneath it."""
    if relative_to is None:
        return path
    try:
        relative = Path(os.path.relpath(path, relative_to))
    except ValueError:  # different drive on Windows
        return path
    return path if relative.parts[:1] == ("..",) else relative


def _manifest_file(manifest: dict, pipeline_id: str, base_dir: Path) -> Path:
    """The chartbook.toml that declares *pipeline_id*'s entries."""
    pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
    pipeline_dir = pipeline_manifest.get("pipeline_base_dir", base_dir)
    return Path(pipeline_dir) / "chartbook.toml"


def load_policy(path: Union[str, Path]) -> dict:
    """Read the resolved ``[policy]`` of a catalog's chartbook.toml.

    Only the policy table is read — the catalog's member pipelines are not
    loaded and need not exist on this machine, so a pipeline's own CI can
    check itself against the policy of a catalog it is published to.

    :param path: A catalog ``chartbook.toml`` or the directory holding one.
    :returns: Dict with ``mode`` and per-object-type ``required`` field lists.
    :raises FileNotFoundError: If there is no such file.
    :raises ValueError: If the file is not valid TOML or its policy is invalid.
    """
    return read_policy(path)[0]


def read_policy(path: Union[str, Path]) -> tuple[dict, bool]:
    """Read the resolved ``[policy]`` of a file, and whether it has one.

    A file with no ``[policy]`` table resolves to the default lists, as
    :func:`load_policy` gives them; the second value says it had none, so
    that ``chartbook check --policy`` on a catalog that sets no policy
    gives none.

    :param path: A catalog ``chartbook.toml`` or the directory holding one.
    :returns: The policy, and True if the file has a ``[policy]`` table.
    :raises FileNotFoundError: If there is no such file.
    :raises ValueError: If the file is not valid TOML or its policy is invalid.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "chartbook.toml"
    if not path.is_file():
        raise FileNotFoundError(f"No policy file found at {path}")
    raw = _parse_toml_file(path)  # a syntax error names the file
    return _resolve_policy(raw, source=str(path)), "policy" in raw


#: Fields of a pipeline's project that a manifest writes in another table,
#: with the table a missing one is said to go in. The build script is
#: ``[scripts] build``; ``[project] build``, the old place, is still read as
#: the same thing, so either satisfies a policy's ``project = ["build"]``.
PROJECT_FIELDS_WRITTEN_IN = {"build": "scripts"}


def check_required_fields(
    manifest: dict,
    base_dir: Path,
    policy_label: str = "the active policy",
    warn_only: bool = False,
) -> list[Problem]:
    """Report every field the active policy requires that is missing or empty.

    The policy is the manifest's resolved ``policy`` (catalogs), or the
    default required-field lists (standalone pipelines); see
    :func:`chartbook.diagnostics.get_active_policy`. A catalog's
    ``policy.mode`` is not consulted: it decides what a *build* does with
    missing metadata, whereas a check always reports it.

    :param policy_label: How to name the policy in messages, so a reader of
        a CI log knows who required the field.
    :param warn_only: If True, no policy was given and the lists are the
        default recommended ones: each missing field is a warning, not a
        problem. A missing write-up stays a problem: the format itself
        requires one for each dataframe and chart, whatever the policy.

    A missing build script is said to belong in ``[scripts] build``
    (:data:`PROJECT_FIELDS_WRITTEN_IN`), where a manifest writes it now.
    """
    write_up = " or ".join(DOCS_FIELDS)  # as the diagnostics row names it
    problems = []
    for row in build_diagnostics(manifest):
        if row.metadata_complete:
            continue
        if row.object_type == "pipeline":
            table = "project"
        else:
            table = f"{row.object_type}s.{row.identifier}"
        toml_file = _manifest_file(manifest, row.pipeline_id, base_dir)
        # DiagnosticRow carries the missing fields ", "-joined for the CSV
        for field in row.missing_fields.split(", "):
            problems.append(
                Problem(
                    toml_file,
                    PROJECT_FIELDS_WRITTEN_IN.get(field, table) if table == "project" else table,
                    field,
                    f"required by {policy_label}, but missing or empty",
                )
            )
    if warn_only:
        kept = []
        for problem in problems:
            if problem.field == write_up:
                kept.append(
                    replace(problem, message="required by the format, but missing or empty")
                )
                continue
            warnings.warn(
                f"{display_path(problem.file, base_dir)}: [{problem.table}] "
                f"{problem.field}: recommended by the default policy, but "
                f"missing or empty",
                UserWarning,
                stacklevel=2,
            )
        return kept
    return problems


def check_paths(
    manifest: dict, base_dir: Path, skip_outputs: bool = False
) -> list[Problem]:
    """Report every declared file that does not exist on disk.

    :param skip_outputs: If True, do not report missing data files, charts
        or notebooks. These are what a pipeline builds, so a checkout that
        has not run it has none of them. Files kept in the repository are
        still checked: write-ups, notes, the README, the logo and favicon.
    """
    problems = []
    missing_files = validate_source_files(manifest, base_dir)
    # A lone pipeline that has built nothing yet (a project just made, a
    # fresh clone) lacks every output, which is not a mistake in its
    # manifest; told as `chartbook docs generate` tells it
    unbuilt = (
        not skip_outputs
        and manifest["project"].get("type") == "pipeline"
        and built_nothing(manifest, missing_files)
    )
    for missing in missing_files:
        if skip_outputs and missing.file_type in OUTPUT_FILE_TYPES:
            continue
        if missing.file_type in ("logo", "favicon"):
            toml_file = Path(base_dir) / "chartbook.toml"
            table, field = "project", missing.file_type
        elif missing.file_type == "readme":
            toml_file = _manifest_file(manifest, missing.pipeline_id, base_dir)
            table, field = "project", "readme"
        else:
            section, field = _FILE_TYPE_FIELDS[missing.file_type]
            toml_file = _manifest_file(manifest, missing.pipeline_id, base_dir)
            table = f"{section}.{missing.item_id}"

        if unbuilt:
            message = f"{NOT_BUILT_YET}: {missing.file_path}"
        elif is_glob_pattern(str(missing.file_path)):
            message = f"no files match {missing.file_path}"
        elif missing.file_type == "file" and Path(missing.file_path).is_dir():
            message = f"the folder holds no file: {missing.file_path}"
        else:
            message = f"file not found: {missing.file_path}"
        if field == "path" and missing.file_type in _FILE_TYPE_FIELDS and _kept(manifest, missing):
            # A costly output: the store may have it (docs_src/design/keep.md)
            message += "; it is marked keep = true, and `chartbook restore` puts it back from the store"
        problems.append(Problem(toml_file, table, field, message))

    # A series' write-up. The build does not render these yet, so nothing
    # else notices when one is missing.
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_dir = Path(pipeline_manifest.get("pipeline_base_dir", base_dir))
        for dataframe_id, dataframe in (pipeline_manifest.get("dataframes") or {}).items():
            for key, series in (dataframe.get("series") or {}).items():
                docs_path = series.get("docs_path")
                if docs_path and not (pipeline_dir / docs_path).is_file():
                    problems.append(
                        Problem(
                            pipeline_dir / "chartbook.toml",
                            f"dataframes.{dataframe_id}.series.{key}",
                            "docs_path",
                            f"file not found: {pipeline_dir / docs_path}",
                        )
                    )
    return problems


def check_model_metrics(manifest: dict, base_dir: Path) -> list[Problem]:
    """Report every model metrics file that is there and is not well formed.

    A metrics file is one flat JSON object of scores. A missing file is
    :func:`check_paths`'s business, not this function's.
    """
    from chartbook.models import read_metrics

    problems = []
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_dir = Path(pipeline_manifest.get("pipeline_base_dir", base_dir))
        for model_id, model in (pipeline_manifest.get("models") or {}).items():
            declared = model.get("metrics_path")
            if not declared or not (pipeline_dir / declared).is_file():
                continue
            try:
                read_metrics(pipeline_dir / declared)
            except (OSError, ValueError) as error:
                problems.append(
                    Problem(
                        pipeline_dir / "chartbook.toml",
                        f"models.{model_id}",
                        "metrics_path",
                        str(error),
                    )
                )
    return problems


def check_glob_names(manifest: dict, base_dir: Path) -> list[Problem]:
    """Report an asset's path that names a file or folder with a glob character in its name.

    Its files are found as they are named, but a reader takes the declared
    path for a pattern (:func:`chartbook.hashing.glob_named`), so
    ``chartbook snapshot`` refuses it. A folder above the pipeline's own,
    such as ``Research [2026]/``, is not part of the path and is fine.
    """
    from chartbook.hashing import glob_named, glob_named_said

    problems = []
    for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for section in _DECLARING:
            for name, entry in (pipeline_manifest.get(section) or {}).items():
                path = entry.get("path") if isinstance(entry, dict) else None
                if not isinstance(path, str) or not path.strip():
                    continue
                named = glob_named(path, os.path.normpath(os.path.join(pipeline_dir, path)))
                if named is not None:
                    problems.append(
                        Problem(pipeline_dir / "chartbook.toml", f"{section}.{name}", "path", glob_named_said(path, named))
                    )
    return problems


#: A run of digits, or a date with ``-`` or ``_`` between its parts
#: (``2026``, ``2026-10``, ``20261027``, ``2026_10``): what tells one file
#: of a set from the others
_NUMBER_OR_DATE = re.compile(r"[0-9]+(?:[-_][0-9]+)*")

#: The sections and fields whose files belong to an asset already
_DECLARING = ("dataframes", "charts", "notebooks", "notes", "models")
_DECLARING_FIELDS = ("path", "docs_path", "metrics_path", "excel_path")


def _counts(run: str) -> bool:
    """Whether a run can tell one file of a set from another: a date, or a number of two digits or more.

    ``v2`` beside ``v1``, or ``.h5`` beside ``.h4``, is more often a version
    or a format than a part.
    """
    return len(run) - run.count("-") - run.count("_") >= 2


class _Declared:
    """Which files the manifest's paths name, asked one folder at a time.

    A path to a file names that file, and one to a folder every file under
    it. A glob is matched only when its root is the folder asked about or
    holds it, so a check does not walk folders it has no question about.
    A folder is known by what the disk says it is (its device and inode),
    so a link to it, or its name in another case on macOS or Windows, is
    the same folder. A file's name is compared without regard to case:
    two names that differ only in it are one file on those disks, and on
    the others the warning is the one left unsaid.
    """

    def __init__(self, manifest: dict):
        from chartbook.hashing import is_pattern, split_glob

        self._ids: dict = {}
        self._files: dict = {}  # a folder: the names of the files named in it
        self._folders: list = []  # folders named, and so everything under them
        self._globs: list = []  # (the folder a glob starts in, the glob)
        self._asked: dict = {}
        for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
            pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
            for section in _DECLARING:
                for entry in (pipeline_manifest.get(section) or {}).values():
                    for field in _DECLARING_FIELDS:
                        path = entry.get(field) if isinstance(entry, dict) else None
                        if not isinstance(path, str) or not path.strip():
                            continue
                        full = os.path.join(pipeline_dir, path)
                        if is_pattern(full):
                            root, pattern = split_glob(full)
                            self._globs.append((self.id(root), pattern))
                        elif os.path.isdir(full):
                            self._folders.append(self.id(full))
                        else:
                            folder, name = os.path.split(os.path.abspath(full))
                            self._files.setdefault(self.id(folder), set()).add(name.casefold())

    def id(self, folder) -> tuple:
        """What a folder is, whatever it is called: its device and inode, or its path if it is not there."""
        key = str(folder)
        if key not in self._ids:
            try:
                found = os.stat(key)
            except OSError:
                found = None
            # A file system that gives no inode (some network shares) is known by the path
            self._ids[key] = (
                (found.st_dev, found.st_ino) if found and found.st_ino else (None, os.path.normcase(os.path.realpath(key)))
            )
        return self._ids[key]

    def names_in(self, folder: str) -> Optional[set]:
        """The names, case folded, of the files in *folder* that some path names; None if a folder named holds them all."""
        asked = self.id(folder)
        if asked not in self._asked:
            real = Path(os.path.realpath(folder))
            above = {self.id(each) for each in (real, *real.parents)}
            if any(named in above for named in self._folders):
                names = None
            else:
                names = set(self._files.get(asked, ()))
                for root, pattern in self._globs:
                    if root in above:
                        for match in glob.glob(pattern, recursive=True):
                            parent, name = os.path.split(match)
                            if self.id(parent) == asked:
                                names.add(name.casefold())
            self._asked[asked] = names
        return self._asked[asked]


def check_siblings(manifest: dict, base_dir: Path) -> list[Problem]:
    """Warn about a dataframe whose path names one file of a set.

    ``transcripts_2026.parquet``, beside ``transcripts_2014.parquet`` to
    ``transcripts_2025.parquet``, is most likely one year of a dataset
    that is all of them. Only the dataframe's own folder is looked at. A
    sibling is a file named as it is but for its runs of digits or dates,
    each of the same shape as the file's, with as many digits in each part
    (``2026-10`` stands beside ``2025-12``, not beside ``2025`` or
    ``2026-9``; ``yields_10y`` beside ``yields_30y``, not beside
    ``yields_2y``). One run that differs must be a date or a number of two
    digits or more. A file that some path of the manifest names already (a
    dataframe's, a model's, a glob's) is not one, and it takes two. The
    warning gives the glob that names them all, each run that differs
    written ``*``, or ``[0-9]`` for each digit where a ``*`` would take in
    a file that is not one of them. It is a warning and not a problem: the
    one file may be what was meant.

    Models are not looked at: a model's path cannot be a glob, and a number
    in a model's name more often marks an old version than a part.
    """
    from chartbook.hashing import is_ignored

    declared: Optional[_Declared] = None  # read once some dataframe has siblings
    listed: dict = {}  # a folder: the names of its files
    matched: dict = {}  # (a folder, a pattern): the names that match, with their runs

    def matches(folder: str, head: str, pattern: str, tail: str) -> list:
        if (folder, pattern) not in matched:
            if folder not in listed:
                try:
                    with os.scandir(folder) as entries:
                        listed[folder] = [e.name for e in entries if e.is_file() and not is_ignored(e.name)]
                except OSError:
                    listed[folder] = []
            fullmatch = re.compile(pattern).fullmatch
            matched[folder, pattern] = [
                (name, found.groups())
                for name in listed[folder]
                if name.startswith(head) and name.endswith(tail) and (found := fullmatch(name))
            ]
        return matched[folder, pattern]

    for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        toml_file = display_path(pipeline_dir / "chartbook.toml", base_dir)
        for dataframe_id, dataframe in (pipeline_manifest.get("dataframes") or {}).items():
            path = dataframe.get("path")
            if not isinstance(path, str) or not path.strip() or is_glob_pattern(path):
                continue
            folder, name = os.path.split(os.path.join(pipeline_dir, path))
            runs = list(_NUMBER_OR_DATE.finditer(name))
            if not any(_counts(run.group()) for run in runs) or not os.path.isfile(os.path.join(folder, name)):
                continue
            # The name with each run as a group of its own shape
            pattern, last = "", 0
            for run in runs:
                shape = re.sub("[0-9]+", lambda digits: "[0-9]{%d}" % len(digits.group()), re.escape(run.group()))
                pattern += re.escape(name[last : run.start()]) + f"({shape})"
                last = run.end()
            head, tail = name[: runs[0].start()], name[last:]
            found = [(other, groups) for other, groups in matches(folder, head, pattern + re.escape(tail), tail) if other != name]
            if not found:
                continue
            declared = declared or _Declared(manifest)
            named = declared.names_in(folder)
            if named is None:
                continue
            siblings = [(other, groups) for other, groups in found if other.casefold() not in named]
            differ = {i for i, run in enumerate(runs) if any(groups[i] != run.group() for _, groups in siblings)}
            if len(siblings) < 2 or not any(_counts(runs[i].group()) for i in differ):
                continue

            # Each run that differs a *, unless that would take in a file that is
            # not one of them (transcripts_sample.parquet): then a digit for a digit
            glob_name, exact, last = "", "", 0
            for i, run in enumerate(runs):
                between = name[last : run.start()]
                glob_name += between + ("*" if i in differ else run.group())
                exact += between + (re.sub("[0-9]", "[0-9]", run.group()) if i in differ else run.group())
                last = run.end()
            ours = {name, *(other for other, _ in found)}
            takes = re.compile(fnmatch.translate(glob_name + tail)).match
            if any(takes(other) and other not in ours for other in listed[folder]):
                glob_name = exact
            cut = max(path.rfind("/"), path.rfind("\\")) + 1
            # Written with / on any system: a \ in a TOML string starts an escape
            suggested = (path[:cut] + glob_name + tail).replace("\\", "/").replace('"', '\\"')
            names = [other for other, _ in siblings]
            if len(names) <= 3:
                shown = ", ".join(sorted(names))
            else:
                shown = f"{min(names)} … {max(names)}"  # all of one length, so in the order of their numbers
            but_for = "a number or date" if len(differ) == 1 else "numbers or dates"
            warnings.warn(
                f"{toml_file}: [dataframes.{dataframe_id}] path: {path} may be one file of a set: no asset "
                f"declares the {len(names)} files beside it named the same but for {but_for} ({shown}). "
                f"If they are one dataset, write path = \"{suggested}\".",
                UserWarning,
                stacklevel=2,
            )
    return []


def _dependency_table(key: str) -> str:
    """A dependency's table as TOML writes it: ``dependencies."scope/name"``."""
    bare = all(c.isascii() and (c.isalnum() or c in "_-") for c in key)
    return f"dependencies.{key}" if bare else f'dependencies."{key}"'


def _pipeline_at(directory: Path) -> Optional[str]:
    """What is wrong with *directory* as a pipeline; None if nothing is."""
    if not directory.is_dir():
        return f"directory not found: {directory}"
    toml_file = directory / "chartbook.toml"
    if not toml_file.is_file():
        return (
            f"no chartbook.toml in {directory}; a dependency is a pipeline, "
            f"and its chartbook.toml is what says what it has"
        )
    try:
        raw = _read_manifest_file(directory)
        project_type = resolve_project_type(raw, source=str(toml_file))
    except (ValueError, OSError) as error:
        return str(error)  # these name the file themselves, a syntax error included
    if project_type != "pipeline":
        return (
            f"{directory} is a catalog, not a pipeline; depend on the "
            f"pipelines it lists"
        )
    return None


def _fetched_checkout(pipeline_dir: Path, key: str, entry: dict) -> Optional[Path]:
    """Where a ``git`` dependency's files are on this disk, if it was fetched.

    That is the checkout of the commit ``chartbook.lock`` names, in the git
    cache. Nothing is fetched here: a check does not use the network.
    """
    from chartbook import lock
    from chartbook.gitcache import default_git_cache, local_url

    try:
        locked = lock.read_lock(pipeline_dir)
    except lock.LockError:
        return None
    for listed in locked.dependencies if locked is not None else []:
        commit = listed.get("location", {}).get("commit")
        if listed.get("id") == key and commit:
            try:
                url = local_url(entry["git"], pipeline_dir)
                return default_git_cache().find(url, commit)
            except ValueError:
                return None
    return None


@functools.lru_cache(maxsize=256)
def _repository_top(directory: str) -> Optional[Path]:
    """The top of the git repository a directory is in, a submodule's superproject's if it is one; None if in none."""
    import subprocess

    from chartbook.identity import _git_environment

    try:
        found = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-superproject-working-tree", "--show-toplevel"],
            capture_output=True, text=True, check=True, env={**_git_environment(), "GIT_OPTIONAL_LOCKS": "0"},
            # A path: its bytes as they are, as the file system takes them back
            encoding="utf-8", errors="surrogateescape"
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    lines = [line for line in found.stdout.splitlines() if line.strip()]
    return Path(lines[0]).resolve() if lines else None


def _elsewhere(pipeline_dir: Path, other: Path) -> str:
    """Where a path dependency is, when that makes it work on this machine only: in another git repository than the pipeline's own, or in none; empty otherwise."""
    mine = _repository_top(str(Path(pipeline_dir).resolve()))
    if mine is None:
        return ""
    theirs = _repository_top(str(Path(other).resolve()))
    if theirs is None:
        return "in no git repository"
    return "" if theirs == mine else "in another git repository"


def _id_at(directory: Path) -> Optional[str]:
    """The ID the pipeline in a directory gives itself, if it can be worked out."""
    try:
        from chartbook.identity import derive_pipeline_id

        raw = tomli.loads((directory / "chartbook.toml").read_text(encoding="utf-8"))
        project = raw.get("project") or {}
        # A [project] that is not a table gives no ID: the manifest is broken there
        return derive_pipeline_id(project, directory) if isinstance(project, dict) else None
    except (OSError, ValueError):
        return None


def _quoted(key: str) -> str:
    return f'"{key}"'


def _dependency_dir(pipeline_dir: Path, key: str, entry: dict) -> Optional[Path]:
    """The directory a dependency's files are in; None if they are not here."""
    if entry.get("_store"):
        return None  # named by its ID alone: its snapshots are in the store, no folder of it
    if "git" in entry:
        return _fetched_checkout(pipeline_dir, key, entry)
    return Path(entry["_resolved_path"])


def _pinned_keys(pipeline_dir: Path) -> Optional[set[str]]:
    """The dependency keys a pipeline's lockfile pins; empty with no lockfile.

    None if there is a lockfile and it cannot be read: a warning says so,
    and no dependency is then said to be unpinned on its account.
    """
    from chartbook import lock

    lock_path = pipeline_dir / lock.LOCK_FILE
    try:
        locked = lock.read_lock(pipeline_dir)
    except lock.LockError as error:
        detail = str(error).removeprefix(f"Cannot read {lock_path}: ")
        warnings.warn(f"{lock_path}: not checked. {detail}", UserWarning, stacklevel=3)
        return None
    if locked is None:
        return set()
    return {listed["id"] for listed in locked.dependencies if listed.get("id")}


def _not_on_this_machine(pipeline_dir: Path, key: str, entry: dict, directory: Path) -> tuple[str, bool]:
    """What to say of a ``path`` dependency whose folder is not here, and whether the pipeline builds without it.

    It builds when the lockfile pins it from that path, and the store has
    every pin whole (``chartbook run --frozen`` reads nothing else). The
    store is looked in only when it is a folder: a check uses no network,
    and with a bucket the lockfile is taken at its word, which ``chartbook
    pin --frozen`` checks.
    """
    from chartbook import lock, snapshot
    from chartbook.config import without_credentials
    from chartbook.store import FolderStore, StoreError, default_store

    try:
        locked = lock.read_lock(pipeline_dir)
    except lock.LockError:
        locked = None  # said already, by _pinned_keys
    pinned = next((e for e in (locked.dependencies if locked else []) if e.get("id") == key), None)
    try:
        store, unopened = default_store(), None
    except (ValueError, StoreError) as error:  # a URL no store is made from
        store, unopened = None, error
    folder = store if isinstance(store, FolderStore) else None
    advice = lock.name_it_by_its_id(key, pinned, lambda: snapshot.readable_snapshots(folder)[0] if folder else [])
    records = [r for r in locked.assets_of(key).values() if r.get("content_hash")] if pinned else []
    if not records or lock._declared_elsewhere(pinned, lock._dependency_entry(key, entry)):
        return (
            f"directory not found: {directory}. Nothing of it is pinned from there, so nothing of it "
            f"can be read on this machine. {advice}",
            False,
        )
    if unopened is not None:
        return (
            f"directory not found: {directory}, and the store cannot be opened "
            f"({without_credentials(str(unopened))}). {advice}",
            False,
        )
    try:
        whole = folder is None or all(folder.has(r["content_hash"]) and not lock._incomplete(folder, r) for r in records)
    except (StoreError, OSError, ValueError) as error:  # a store that cannot be read, a half-synced store.json
        # What the system says names the store's path, which may carry a password (//user:pw@host)
        return (
            f"directory not found: {directory}, and the store cannot be read "
            f"({without_credentials(str(error))}). {advice}",
            False,
        )
    if not whole:
        return (
            f"directory not found: {directory}, and the store does not have all that the lockfile "
            f"pins of it (`chartbook pin --frozen` says what). {advice}",
            False,
        )
    return (
        f"there is no folder at {directory} on this machine (another machine's folder, or one that has "
        f"moved). It is pinned from there, with its pins in the store, so this pipeline builds here "
        f"(`chartbook run --frozen`), and only `chartbook update` needs the folder. {advice}",
        True,
    )


def check_dependencies(manifest: dict, base_dir: Path) -> list[Problem]:
    """Report every declared dependency that cannot be found.

    A ``path`` dependency must be a directory with a pipeline's
    ``chartbook.toml`` in it, and not the pipeline's own. Nothing in it is
    built, read or copied. A ``git`` dependency is looked at where
    ``chartbook pin`` has fetched it, at the commit the lockfile names. A
    check never uses the network, so one that has not been fetched draws a
    warning that says so, not a problem.

    In a catalog, a dependency whose key is one of the catalog's own
    pipelines must be that pipeline. One ID that means two directories in
    one build is reported, naming both.

    A dependency named by its ID, or a ``path`` dependency that is there,
    with no pin in ``chartbook.lock`` draws a warning too: it is not pinned
    yet, and ``chartbook pin`` (or ``chartbook run``) pins its newest
    snapshot, as the first read of it does. That is a warning and not a
    problem because a fresh clone is in that state on purpose, and
    ``--frozen`` is the gate that fails on it.
    """
    problems = []
    in_build = get_pipeline_dirs(manifest)
    is_catalog = manifest["project"]["type"] == "catalog"
    for pipeline_id, pipeline_dir in in_build.items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        toml_file = pipeline_dir / "chartbook.toml"
        pinned = _pinned_keys(pipeline_dir)
        for key, entry in (pipeline_manifest.get("dependencies") or {}).items():
            table = _dependency_table(key)
            location = locate_pipeline(key, dependencies={key: entry})
            if location.kind == "store":
                # Named by its ID alone: there is no folder to look at here,
                # only whether it is pinned
                if location.pipeline in (pipeline_id, pipeline_manifest["project"].get("id")):
                    problems.append(
                        Problem(toml_file, table, "id", f"{location.pipeline} is this pipeline itself; a pipeline cannot depend on itself")
                    )
                    continue
                if pinned is not None and key not in pinned:
                    warnings.warn(
                        f"{toml_file}: [{table}] not pinned yet. `chartbook pin` pins the newest "
                        f"snapshot of {location.pipeline} in the store, as the first read of it does, "
                        f"and so does `chartbook run` (the build). With a rev, `pin` takes the newest "
                        f"at or before it; with no snapshot and a [resolve] default_host set, its "
                        f"repository there.",
                        UserWarning,
                        stacklevel=2,
                    )
                continue
            if location.kind == "git":
                checkout = _fetched_checkout(pipeline_dir, key, entry)
                if checkout is None and pinned is None:
                    continue  # the lockfile could not be read, and that was said
                if checkout is None:
                    warnings.warn(
                        f"{toml_file}: [{table}] git: not checked. "
                        f"{strip_url_credentials(location.url)} has not been "
                        f"fetched here; `chartbook pin` fetches it.",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                wrong = _pipeline_at(checkout)
                if wrong is not None:
                    problems.append(Problem(toml_file, table, "git", wrong))
                continue

            if not location.path.exists():
                # Not on this machine: another machine's folder, perhaps, which
                # is a problem only if nothing of it can be built from here
                said, builds = _not_on_this_machine(pipeline_dir, key, entry, location.path)
                if builds:
                    warnings.warn(f"{toml_file}: [{table}] path: {said}", UserWarning, stacklevel=2)
                else:
                    problems.append(Problem(toml_file, table, "path", said))
                continue
            wrong = _pipeline_at(location.path)
            if wrong is None and location.path.samefile(pipeline_dir):
                wrong = (
                    "this is the pipeline's own directory; a pipeline cannot "
                    "depend on itself"
                )
            if wrong is not None:
                problems.append(Problem(toml_file, table, "path", wrong))
                continue

            claimed = in_build.get(key) if is_catalog else None
            if claimed is not None and not location.path.samefile(claimed):
                problems.append(
                    Problem(
                        toml_file,
                        table,
                        "path",
                        f"{key!r} is {location.path} here, and {claimed} in "
                        f"this catalog: one ID for two pipelines. Point both "
                        f"at one directory, or give this dependency another "
                        f"key (a key in [dependencies] is a local name)",
                    )
                )
                continue
            elsewhere = _elsewhere(pipeline_dir, location.path)
            if elsewhere:
                found_id = _id_at(location.path) or key
                instead = (
                    f'"{key}" = {{}}' if found_id == key else f'"{key}" = {{ id = "{found_id}" }}'
                )
                warnings.warn(
                    f"{toml_file}: [{table}] path: {entry['path']} is {elsewhere}, so this works on "
                    f"this machine only. Name it by its ID, {instead}, and it is read from the store "
                    f"on any machine.",
                    UserWarning,
                    stacklevel=2,
                )
            if pinned is not None and key not in pinned:
                warnings.warn(
                    f"{toml_file}: [{table}] path: not pinned yet. `chartbook pin` pins its newest "
                    f"snapshot, as the first read of it does, and so does `chartbook run` (the build).",
                    UserWarning,
                    stacklevel=2,
                )
    return problems


def check_dependency_cycles(manifest: dict, base_dir: Path) -> list[Problem]:
    """Report a pipeline that depends, through what it depends on, on itself.

    Dependencies between pipelines must form a directed acyclic graph:
    ``chartbook run``, ``chartbook build`` and ``chartbook snapshot`` refuse
    a cycle, and this says so without building. The graph is walked as
    :func:`chartbook.lineage.cycle` walks it: through the folders on this
    machine, and through the pins in the store when the store is a folder
    on this disk. A check uses no network, so a store at a URL is not read,
    and a cycle that only its snapshots would show is not seen here. The
    problem is addressed to the pipeline's own dependency that is in the
    cycle, or that leads to one among the pipelines it depends on. A
    pipeline that depends on itself directly, by its own folder or its own
    ID, is reported by :func:`check_dependencies`, not here.
    """
    from chartbook import lineage
    from chartbook.snapshot import SnapshotError
    from chartbook.store import FolderStore, StoreError, default_store

    store: list = []  # the user's store, read once some pipeline here has dependencies

    def folder_store():
        if not store:
            try:
                found = default_store()
                store.append(found if isinstance(found, FolderStore) else None)
            except (StoreError, OSError, ValueError):
                store.append(None)
        return store[0]

    problems = []
    in_build = get_pipeline_dirs(manifest)
    # A catalog's pipelines, by ID: one named by its ID is walked through its folder
    members = {(_id_at(folder) or key): folder for key, folder in in_build.items()}
    shared: dict = {}  # the store read once for every pipeline's walk
    for pipeline_id, pipeline_dir in in_build.items():
        dependencies = get_pipeline_manifest(manifest, pipeline_id).get("dependencies") or {}
        if not dependencies:
            continue
        readable = folder_store()
        try:
            found = lineage.cycle(
                pipeline_dir, readable, follow_pins=readable is not None, members=members, shared=shared
            )
        except (SnapshotError, ValueError, OSError):
            continue  # said by the checks of the manifest itself
        if found is None:
            continue
        first = (found.way_in or found.edges)[0]
        entry = dependencies.get(first.key) or {}
        if len(found.edges) == 1 and not found.way_in:
            there = Path(entry["_resolved_path"]) if entry.get("_resolved_path") else None
            if entry.get("_store") or (there is not None and there.exists() and there.samefile(pipeline_dir)):
                continue  # its own folder or its own ID: check_dependencies says so
        if found.way_in:
            lead = (
                "a pipeline this one depends on depends on itself" if len(found.edges) == 1
                else "pipelines this one depends on depend on each other"
            )
        else:
            lead = "this pipeline depends on itself" if len(found.edges) == 1 else "these pipelines depend on each other"
        field = "git" if "git" in entry else "path" if "path" in entry else "id"
        around = " -> ".join([edge.pipeline for edge in found.edges] + [found.edges[0].pipeline])
        if found.two_places is not None:
            remedy = lineage.two_places_said(*found.two_places).rstrip(".")
        else:
            remedy = "Take one of these out of its [dependencies]"
        problems.append(
            Problem(
                pipeline_dir / "chartbook.toml",
                _dependency_table(first.key),
                field,
                f"{around}: {lead}, so there is no order to build in. {remedy}",
            )
        )
    return problems


def check_build_tool(manifest: dict, base_dir: Path) -> list[Problem]:
    """A build tool's task that says ``chartbook build``, as one written before 0.2.0 did to render the site.

    With a build command declared (``[scripts] build``), ``chartbook build``
    runs that command first, which is the same build tool: the build would
    run inside itself, and ``chartbook build`` refuses. That is a problem,
    on the ``build`` field. Without one, ``chartbook build`` there only
    renders the site, as it did; a warning says that ``chartbook docs
    generate`` is the command that renders (:func:`chartbook.run.build_tool_runs_chartbook_build`).
    """
    from chartbook.manifest import _read_manifest_file
    from chartbook.run import build_tool_runs_chartbook_build

    problems = []
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        directory = Path(pipeline_manifest.get("pipeline_base_dir", base_dir))
        command = str((pipeline_manifest.get("project") or {}).get("build") or "").strip()
        # With a build command, the task file of the tool it runs; with none, any tool's
        clash = build_tool_runs_chartbook_build(directory, command or None)
        if clash is None:
            continue
        name, number, line = clash
        if command:
            try:
                raw = _read_manifest_file(directory)
                table = "scripts" if (raw.get("scripts") or {}).get("build") else "project"
            except (OSError, ValueError):
                table = "scripts"
            problems.append(
                Problem(
                    directory / "chartbook.toml",
                    table,
                    "build",
                    f"{name}, line {number}, runs `chartbook build` ({line}), and the build command runs "
                    f"{name}: under `chartbook build` the site would be rendered twice, and under a plain "
                    f"build-tool run the build would run inside itself. Since 0.2.0 the command that renders "
                    f"the site is `chartbook docs generate -f`: say that in {name}",
                )
            )
        else:
            warnings.warn(
                f"{display_path(directory / name, Path.cwd())}, line {number}: `chartbook build` renders the "
                f"site here only because no build command is declared; the command that renders is "
                f"`chartbook docs generate -f`, and with a build command `chartbook build` would run it first",
                UserWarning,
                stacklevel=2,
            )
    return problems


def check_ids(manifest: dict, base_dir: Path) -> list[Problem]:
    """Warn where a pipeline is named by an ID its folder no longer gives itself, or will be named by another repository's.

    A pipeline's ID can change: it gets a git remote, and so a scope; it is
    given ``[project] id``. Its snapshots are then made under the new ID,
    while a catalog entry keyed by the old one shows only the old ID's
    snapshots, and a dependency named by the old one stays at the last of
    them. Each is a warning, naming the key to write: the old snapshots are
    still there, and nothing fails.

    A catalog's entry is compared with what its folder calls itself now. A
    dependency named by its ID (with no ``commit``, which keeps it where it
    is) is compared with the folders of it on this machine: the catalog's
    own, under that ID, and the folders a store on this disk notes its
    newest snapshots were made in, each one only if it is in the
    repository those snapshots record. If any of them still calls itself
    by the dependency's ID, nothing is said.

    A pipeline whose ``repo_url`` names another repository than its git
    remote is named after ``repo_url``'s: a project copied into a new
    repository with its manifest would claim the original's ID.
    """
    from chartbook.identity import get_git_remote_url, repository_key
    from chartbook.manifest import dependency_line

    in_build = get_pipeline_dirs(manifest)
    if manifest["project"]["type"] == "catalog":
        catalog_toml = Path(base_dir) / "chartbook.toml"
        for pipeline_id, pipeline_dir in in_build.items():
            current = _id_at(pipeline_dir)
            if current and current != pipeline_id:
                warnings.warn(
                    f"{catalog_toml}: [{_pipelines_table(pipeline_id)}] the pipeline in {pipeline_dir} calls itself "
                    f"{current} now, and its new snapshots are made under that ID; under {pipeline_id}, this "
                    f"catalog shows only those made before. Name the entry {_quoted(current)} to show them.",
                    UserWarning,
                    stacklevel=2,
                )
    made_in = _snapshot_folders()
    for pipeline_id, pipeline_dir in in_build.items():
        _check_repo_url(pipeline_dir)
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for key, entry in (pipeline_manifest.get("dependencies") or {}).items():
            named = entry.get("_store")
            if not named or entry.get("commit"):
                continue
            folders = ([in_build[named]] if named in in_build else []) + made_in(named)
            ids = {folder: _id_at(folder) for folder in dict.fromkeys(folders)}
            if not ids or named in ids.values():
                continue  # a folder of it still calls itself by this ID
            folder, current = next(((f, i) for f, i in ids.items() if i), (None, None))
            if current is None:
                continue
            kept = {name: entry[name] for name in ("rev", "repository") if name in entry}
            if "repository" in kept and repository_key(kept["repository"]) != repository_key(get_git_remote_url(folder)):
                del kept["repository"]  # its snapshots are not made at that address now
            line = dependency_line(key, kept if key == current else {"id": current, **kept})
            warnings.warn(
                f"{pipeline_dir / 'chartbook.toml'}: [{_dependency_table(key)}] {named} is the pipeline in "
                f"{folder}, which calls itself {current} now: its new snapshots are made under that ID, and "
                f"this dependency stays at the last one made as {named}. Write {line} to follow it, then "
                f"`chartbook update {key}`.",
                UserWarning,
                stacklevel=2,
            )
    return []


def _check_repo_url(pipeline_dir: Path) -> None:
    """Warn when a pipeline's ``repo_url`` and its git remote name two repositories: its ID is ``repo_url``'s."""
    from chartbook.identity import derive_pipeline_id, get_git_remote_url, repository_key, remote_to_web_url

    try:
        project = _read_manifest_file(pipeline_dir).get("project")
    except (OSError, ValueError):
        return
    if not isinstance(project, dict) or project.get("id") or not isinstance(project.get("repo_url"), str):
        return
    remote = get_git_remote_url(pipeline_dir)
    written, actual = repository_key(project["repo_url"]), repository_key(remote)
    if not written or not actual or written == actual:
        return
    try:
        named, own = derive_pipeline_id(project, pipeline_dir), derive_pipeline_id({}, pipeline_dir)
    except ValueError:
        return
    if named == own:
        return
    warnings.warn(
        f"{pipeline_dir / 'chartbook.toml'}: [project] repo_url: {remote_to_web_url(project['repo_url'])} is "
        f"not this folder's git remote, {remote_to_web_url(remote)}, and the pipeline is named after repo_url's "
        f"repository: {named}. If this is a copy of that project in a repository of its own, take repo_url out "
        f"(or write this repository's) and it is {own}; to keep {named}, write [project] id = \"{named}\".",
        UserWarning,
        stacklevel=2,
    )


def _pipelines_table(key: str) -> str:
    """A catalog entry's table as TOML writes it: ``pipelines."scope/name"``."""
    return _dependency_table(key).replace("dependencies", "pipelines", 1)


#: How many of a pipeline's newest snapshots ``check`` looks at for the folders they were made in
_SNAPSHOTS_LOOKED_AT = 5


def _snapshot_folders():
    """What gives the folders on this machine that a pipeline's newest snapshots were made in, by its ID; newest first.

    Only a store that is a folder on this disk is read, and only if some
    pipeline names a dependency by its ID: ``check`` uses no network, so
    for a store at a URL it gives no folder, and says nothing. Of the
    snapshots of an ID, the newest few commits are looked at, and a folder
    noted for one is given only if it is a checkout of the repository the
    snapshot records: its remote's address, or its first commit where
    either has no address or where no folder of that commit has the
    recorded address any more (a clone set to the repository's new
    address).
    """
    from chartbook import snapshot
    from chartbook.identity import checkout_of, get_git_remote_url, repository_key
    from chartbook.store import FolderStore, StoreError, default_store

    read: list = []

    def folders(pipeline_id: str) -> list:
        if not read:
            try:
                store = default_store()
                found = snapshot.readable_snapshots(store)[0] if isinstance(store, FolderStore) else []
            except (StoreError, OSError, ValueError):
                store, found = None, []
            read.append((store, found))
        store, found = read[0]
        seen, looked = [], set()
        for taken in sorted((t for t in found if t.pipeline == pipeline_id), key=lambda t: t.made_at, reverse=True):
            moment = (taken.commit, taken.subdirectory)
            if moment in looked:
                continue
            looked.add(moment)
            if len(looked) > _SNAPSHOTS_LOOKED_AT:
                break
            try:
                tops = snapshot.origins(store, taken)
            except (StoreError, OSError):
                continue
            recorded = repository_key(taken.repository)
            now = {top: repository_key(get_git_remote_url(top)) for top in tops}
            # A clone whose remote was set to a new address (the repository
            # moved, or changed owner) is still that repository, when no
            # folder of the commit has the address the snapshot recorded
            moved = bool(recorded) and recorded not in now.values()
            for top, address in now.items():
                folder = top / taken.subdirectory if taken.subdirectory else top
                if folder in seen or not (folder / "chartbook.toml").is_file():
                    continue
                if recorded and address and not moved:
                    same = recorded == address
                else:
                    checkout = checkout_of(top)
                    same = bool(taken.first_commit) and checkout is not None and checkout.first_commit == taken.first_commit
                if same:
                    seen.append(folder)
        return seen

    return folders


def check_model_lineage(manifest: dict, base_dir: Path) -> list[Problem]:
    """Report training data that names a dataframe which is known not to exist.

    A model may be trained on another pipeline's dataframe. That pipeline
    is looked for where anything else would look for it: in the
    ``[dependencies]`` of the pipeline that declares the model, then among
    the pipelines being checked with it. Where its ``chartbook.toml`` can
    be read, a dataframe it does not declare is a mistake. Where the
    pipeline is nowhere to be seen, or is in a git repository that has not
    been fetched, nothing can be said, and nothing is. Once ``chartbook
    pin`` has fetched it, it is checked like any other.
    """
    problems = []
    in_build = get_pipeline_dirs(manifest)
    for pipeline_id, pipeline_dir in in_build.items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        dependencies = pipeline_manifest.get("dependencies") or {}
        for model_id, model in (pipeline_manifest.get("models") or {}).items():
            for reference in model.get("_trained_on", []):
                if reference.is_local:
                    continue  # the loader has already checked it
                try:
                    location = locate_pipeline(
                        reference.pipeline_id,
                        dependencies=dependencies,
                        catalog=in_build,
                    )
                except (KeyError, ValueError):
                    continue
                directory = location.path
                if directory is None and location.found_in == "dependencies":
                    # A git dependency: its checkout, if it has been fetched
                    directory = _dependency_dir(
                        pipeline_dir, location.id, dependencies[location.id]
                    )
                if directory is None:
                    continue
                try:
                    dataframes = declared_assets(directory)["dataframes"]
                except (OSError, ValueError):
                    continue  # check_dependencies says what is wrong there
                if reference.name not in dataframes:
                    problems.append(
                        Problem(
                            pipeline_dir / "chartbook.toml",
                            f"models.{model_id}",
                            "trained_on",
                            f"{str(reference)!r} names a dataframe that the "
                            f"pipeline {known_as(location, in_build)!r} does "
                            f"not declare. Its dataframes are: "
                            f"{', '.join(dataframes) or '(none)'}",
                        )
                    )
    return problems


def parse_expiration(value: Any) -> Optional[date]:
    """Interpret a ``license_expiration`` value.

    :param value: A TOML date or datetime, or a string. Strings must be ISO
        dates (``YYYY-MM-DD``) unless they are one of
        :data:`NO_EXPIRATION_VALUES`.
    :returns: The expiration date, or None when the license does not expire.
    :raises ValueError: If the value cannot be read as a date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in NO_EXPIRATION_VALUES:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return datetime.fromisoformat(text).date()
    raise ValueError(f"unsupported type {type(value).__name__}")


def check_licenses(
    manifest: dict,
    base_dir: Path,
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: Optional[date] = None,
) -> list[Problem]:
    """Report the licenses of dataframes and files assets that are expired or expire within the window.

    :param within_days: A license expiring this many days from *today* or
        sooner is reported. ``0`` reports only licenses already expired or
        expiring today.
    :param today: The date to measure from. Defaults to the current date.
    """
    today = today or date.today()
    problems = []
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        toml_file = _manifest_file(manifest, pipeline_id, base_dir)
        licensed = [
            (table, key, entry)
            for table in ("dataframes", "files")
            for key, entry in (pipeline_manifest.get(table) or {}).items()
        ]
        for table, key, entry in licensed:
            raw = entry.get("license_expiration")
            try:
                expires = parse_expiration(raw)
            except ValueError:
                message = (
                    f"cannot read {raw!r} as a date; use YYYY-MM-DD, or remove "
                    f"the field if the license does not expire"
                )
            else:
                if expires is None:
                    continue
                days_left = (expires - today).days
                if days_left > within_days:
                    continue
                if days_left < 0:
                    message = f"license expired on {expires} ({-days_left} days ago)"
                elif days_left == 0:
                    message = f"license expires today ({expires})"
                else:
                    message = (
                        f"license expires on {expires} (in {days_left} days, "
                        f"inside the {within_days}-day window)"
                    )
            problems.append(
                Problem(
                    toml_file,
                    f"{table}.{key}",
                    "license_expiration",
                    message,
                )
            )
    return problems


def check_sources(manifest: dict, base_dir: Path, skip_outputs: bool = False) -> list[Problem]:
    """Report a source that is not there: a DuckDB file that does not exist.

    A source's file is something the pipeline builds, so with
    *skip_outputs* it is not reported. Whether the engine *connects* is not
    checked, as the data-access design says: a source has to resolve, and
    whether a table or query in it runs is found out when it is read.
    """
    from chartbook.backends import duckdb_path

    if skip_outputs:
        return []
    problems = []
    for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        toml_file = Path(pipeline_dir) / "chartbook.toml"
        for name, source in (pipeline_manifest.get("sources") or {}).items():
            if source.get("backend") != "duckdb":
                continue
            path = duckdb_path(source["_resolved_url"], pipeline_dir)
            if path != ":memory:" and not Path(path).is_file():
                problems.append(
                    Problem(
                        toml_file,
                        f"sources.{name}",
                        "url",
                        f"the DuckDB file is not there: {path}. The pipeline builds it.",
                    )
                )
    return problems


def check_model_staleness(manifest: dict, base_dir: Path) -> list[Problem]:
    """Warn about a model trained on inputs that have since moved.

    The model file's bytes are a version; the snapshot that first held them
    recorded what each ``trained_on`` input was then. An input that is
    something else now, a local dataframe rebuilt or another pipeline's
    pinned elsewhere by ``chartbook update``, makes the model out of date.
    That is a warning and not a problem: a model may be kept on purpose,
    and retraining is the pipeline's build to run.
    """
    from chartbook.config import without_credentials
    from chartbook.models import staleness
    from chartbook.store import StoreError

    for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for model_id, model in (pipeline_manifest.get("models") or {}).items():
            try:
                found = staleness(pipeline_dir, model_id, model)
            except (StoreError, OSError, ValueError) as error:  # a store of 0.2, or one that cannot be read
                warnings.warn(
                    f"{display_path(pipeline_dir / 'chartbook.toml', base_dir)}: [models.{model_id}] "
                    f"trained_on: not checked. {without_credentials(str(error))}",
                    stacklevel=2,
                )
                continue
            if found is None or not found.stale:
                continue
            moved = "; ".join(
                f"{key} was {found.trained_with[key][:19]}… and is {found.now[key][:19]}…"
                for key in found.stale
            )
            warnings.warn(
                f"{display_path(pipeline_dir / 'chartbook.toml', base_dir)}: [models.{model_id}] "
                f"trained_on: out of date: version {found.version} was trained on inputs that "
                f"have since moved ({moved}). `chartbook run` retrains it; if that gives the same "
                f"bytes, the version keeps the inputs it was first made with.",
                stacklevel=2,
            )
    return []


def check_model_labels(manifest: dict, base_dir: Path) -> list[Problem]:
    """Look at each model's labels: does each point at a version that is here?

    A label points at a version by the start of its content hash, and a
    version is made by a snapshot, which is kept in the store of the
    machine that made it. So a label can be right and its version not be
    on this machine. That is a warning, as a git dependency that has not
    been fetched is: nothing can be said, and that is said.

    A label that matches more than one version is a problem: it does not
    say which.
    """
    from chartbook.models import versions_in

    problems = []
    for pipeline_id, pipeline_dir in get_pipeline_dirs(manifest).items():
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        toml_file = Path(pipeline_dir) / "chartbook.toml"
        for model_id, model in (pipeline_manifest.get("models") or {}).items():
            aliases = model.get("aliases")
            if not isinstance(aliases, dict) or not aliases:
                continue
            kept = versions_in(pipeline_dir, model_id, aliases)
            for label, points_at in aliases.items():
                digits = str(points_at).split(":", 1)[-1]
                matches = [
                    version.name
                    for version in kept
                    if version.content_hash.split(":", 1)[-1].startswith(digits)
                ]
                if len(matches) > 1:
                    problems.append(
                        Problem(
                            toml_file,
                            f"models.{model_id}.aliases",
                            label,
                            f"{points_at} is the start of {len(matches)} versions "
                            f"({', '.join(matches)}). Give more digits.",
                        )
                    )
                elif not matches:
                    warnings.warn(
                        f"{toml_file}: [models.{model_id}.aliases] {label}: not "
                        f"checked. No version {points_at} of model/{model_id} is "
                        f"on this machine; a version is made by a snapshot, in "
                        f"the store of the machine that made it.",
                        UserWarning,
                        stacklevel=2,
                    )
    return problems


def run_checks(
    manifest: dict,
    base_dir: Union[str, Path],
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: Optional[date] = None,
    policy_label: str = "the active policy",
    skip_outputs: bool = False,
    policy_given: bool = True,
) -> list[Problem]:
    """Run every check over a loaded manifest.

    :param manifest: A manifest from :func:`chartbook.manifest.load_manifest`
        (pipeline or catalog).
    :param base_dir: The directory holding that manifest's chartbook.toml.
    :param within_days: The license-expiration window, in days.
    :param today: The date to measure license expiration from.
    :param policy_label: How to name the policy in required-field messages.
    :param skip_outputs: If True, built files (data, charts, notebooks) need
        not exist; see :func:`check_paths`.
    :param policy_given: False when no ``[policy]`` was given anywhere: the
        default recommended fields are then warned about, not problems; see
        :func:`check_required_fields`.
    :returns: Every problem found, sorted by file then table; empty for a
        healthy project.
    """
    base_dir = Path(base_dir).resolve()
    problems = [
        *check_required_fields(
            manifest, base_dir, policy_label=policy_label, warn_only=not policy_given
        ),
        *check_paths(manifest, base_dir, skip_outputs=skip_outputs),
        *check_glob_names(manifest, base_dir),
        *check_siblings(manifest, base_dir),
        *check_dependencies(manifest, base_dir),
        *check_dependency_cycles(manifest, base_dir),
        *check_ids(manifest, base_dir),
        *check_build_tool(manifest, base_dir),
        *check_model_metrics(manifest, base_dir),
        *check_model_lineage(manifest, base_dir),
        *check_model_labels(manifest, base_dir),
        *check_model_staleness(manifest, base_dir),
        *check_sources(manifest, base_dir, skip_outputs=skip_outputs),
        *check_licenses(manifest, base_dir, within_days=within_days, today=today),
    ]
    return sorted(problems, key=lambda p: (str(p.file), p.table, p.field))
