"""The CI gate: metadata and path checks over a loaded manifest.

``chartbook check`` runs everything here and exits nonzero when any problem
is found. It looks at *metadata and paths* only — required fields under the
active policy, the files a manifest points at, and license expiration
dates. It never opens a data file; data-quality checks (row counts, null
rates, schema assertions) are a separate concern.

The checks are thin wrappers over machinery the build already uses:
:func:`chartbook.conf_validation.validate_source_files` for paths and
:func:`chartbook.diagnostics.build_diagnostics` for required fields.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional, Union

import tomli

from chartbook.conf_validation import validate_source_files
from chartbook.diagnostics import build_diagnostics
from chartbook.manifest import (
    _resolve_policy,
    get_pipeline_ids,
    get_pipeline_manifest,
)
from chartbook.utils import is_glob_pattern

#: Default window, in days, inside which an unexpired license still fails.
DEFAULT_WITHIN_DAYS = 30

#: ``license_expiration`` values that mean "this license does not expire".
#: Compared case-insensitively. Anything else must parse as a date.
NO_EXPIRATION_VALUES = frozenset({"", "n/a", "na", "none", "never"})

#: Kinds of missing file that are things a pipeline *builds*: data, rendered
#: charts and executed notebooks. They are normally git-ignored, so on a
#: fresh checkout that has not run the pipeline they are all absent.
OUTPUT_FILE_TYPES = frozenset({"dataframe", "chart", "notebook"})

# MissingFile.file_type -> (manifest section, field) for per-entity files
_FILE_TYPE_FIELDS = {
    "dataframe": ("dataframes", "path"),
    "dataframe_docs": ("dataframes", "docs_path"),
    "chart": ("charts", "path"),
    "chart_docs": ("charts", "docs_path"),
    "notebook": ("notebooks", "path"),
    "note": ("notes", "path"),
}


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
    path = Path(path)
    if path.is_dir():
        path = path / "chartbook.toml"
    if not path.is_file():
        raise FileNotFoundError(f"No policy file found at {path}")
    with open(path, "rb") as f:
        raw = tomli.load(f)
    return _resolve_policy(raw, source=str(path))


def check_required_fields(
    manifest: dict, base_dir: Path, policy_label: str = "the active policy"
) -> list[Problem]:
    """Report every field the active policy requires that is missing or empty.

    The policy is the manifest's resolved ``policy`` (catalogs), or the
    default required-field lists (standalone pipelines); see
    :func:`chartbook.diagnostics.get_active_policy`. A catalog's
    ``policy.mode`` is not consulted: it decides what a *build* does with
    missing metadata, whereas a check always reports it.

    :param policy_label: How to name the policy in messages, so a reader of
        a CI log knows who required the field.
    """
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
                    table,
                    field,
                    f"required by {policy_label}, but missing or empty",
                )
            )
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
    for missing in validate_source_files(manifest, base_dir):
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

        if is_glob_pattern(str(missing.file_path)):
            message = f"no files match {missing.file_path}"
        else:
            message = f"file not found: {missing.file_path}"
        problems.append(Problem(toml_file, table, field, message))
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
    """Report dataframe licenses that are expired or expire within the window.

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
        for dataframe_id, dataframe in pipeline_manifest.get("dataframes", {}).items():
            raw = dataframe.get("license_expiration")
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
                    f"dataframes.{dataframe_id}",
                    "license_expiration",
                    message,
                )
            )
    return problems


def run_checks(
    manifest: dict,
    base_dir: Union[str, Path],
    within_days: int = DEFAULT_WITHIN_DAYS,
    today: Optional[date] = None,
    policy_label: str = "the active policy",
    skip_outputs: bool = False,
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
    :returns: Every problem found, sorted by file then table; empty for a
        healthy project.
    """
    base_dir = Path(base_dir).resolve()
    problems = [
        *check_required_fields(manifest, base_dir, policy_label=policy_label),
        *check_paths(manifest, base_dir, skip_outputs=skip_outputs),
        *check_licenses(manifest, base_dir, within_days=within_days, today=today),
    ]
    return sorted(problems, key=lambda p: (str(p.file), p.table, p.field))
