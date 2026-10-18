"""User-friendly error handling for chartbook CLI.

This module provides structured error types and formatting utilities
that produce readable, actionable error messages for CLI users.
"""

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click

from chartbook.refs import DEFAULT_KIND, KIND_TABLES


@dataclass
class ChartBookError:
    """Base error with user-friendly formatting.

    Attributes:
        message: The main error message to display.
        file_path: Path to the file where the error occurred.
        field_name: Name of the field that caused the error.
        invalid_value: The invalid value that was provided.
        hint: A helpful hint about how to fix the error.
    """

    message: str
    file_path: Optional[Path] = None
    field_name: Optional[str] = None
    invalid_value: Optional[str] = None
    hint: Optional[str] = None

    def format_message(self) -> str:
        """Format error for CLI display with colors and structure.

        :returns: A formatted string ready for CLI output.
        :rtype: str
        """
        lines = [click.style("Error: ", fg="red", bold=True) + self.message]

        if self.file_path:
            lines.append(f"  File: {click.style(str(self.file_path), fg='cyan')}")

        if self.field_name:
            lines.append(f"  Field: {click.style(self.field_name, fg='yellow')}")

        if self.invalid_value:
            # Truncate long values for readability
            if len(self.invalid_value) > 50:
                display_val = self.invalid_value[:50] + "..."
            else:
                display_val = self.invalid_value
            lines.append(f"  Value: {click.style(repr(display_val), fg='yellow')}")

        if self.hint:
            lines.append("")
            lines.append(click.style("Hint: ", fg="green") + self.hint)

        return "\n".join(lines)

    def exit_with_message(self) -> None:
        """Print formatted message to stderr and exit with code 1.

        :raises SystemExit: Always exits with code 1.
        """
        click.echo(self.format_message(), err=True)
        raise SystemExit(1)


class ValidationError(Exception):
    """Raised when a value fails security validation.

    This exception carries additional context that can be used to generate
    user-friendly error messages for the CLI.

    Attributes:
        field_name: Name of the field that failed validation.
        invalid_value: The value that failed validation.
        hint: A helpful hint about how to fix the error.
    """

    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        invalid_value: Optional[str] = None,
        hint: Optional[str] = None,
    ):
        """Initialize a ValidationError.

        :param message: The error message.
        :type message: str
        :param field_name: Name of the field that failed validation.
        :type field_name: str, optional
        :param invalid_value: The value that failed validation.
        :type invalid_value: str, optional
        :param hint: A helpful hint about how to fix the error.
        :type hint: str, optional
        """
        super().__init__(message)
        self.field_name = field_name
        self.invalid_value = invalid_value
        self.hint = hint

    def to_chartbook_error(self, file_path: Optional[Path] = None) -> ChartBookError:
        """Convert to ChartBookError for CLI display.

        :param file_path: Path to the file where the error occurred.
        :type file_path: Path, optional
        :returns: A ChartBookError instance ready for CLI display.
        :rtype: ChartBookError
        """
        return ChartBookError(
            message=str(self),
            file_path=file_path,
            field_name=self.field_name,
            invalid_value=self.invalid_value,
            hint=self.hint,
        )


class ProjectRootNotFoundError(Exception):
    """Raised when the project root directory cannot be found.

    This exception is raised by `get_project_root()` when no marker file
    (e.g., .git, pyproject.toml, .env) can be found within the search limit.

    Attributes:
        start_path: The directory from which the search started.
        markers: The marker files/directories that were searched for.
        max_levels: The maximum number of parent directories searched.
    """

    def __init__(
        self,
        start_path: Path,
        markers: tuple[str, ...],
        max_levels: int,
    ):
        self.start_path = start_path
        self.markers = markers
        self.max_levels = max_levels
        super().__init__(
            f"Could not find project root from {start_path}. "
            f"Searched {max_levels} levels for markers: {list(markers)}. "
            f"Set the BASE_DIR environment variable or ensure one of these markers exists."
        )


class CatalogNotConfiguredError(Exception):
    """Raised when no catalog path is configured and none was provided.

    This exception is raised by data loading functions when no catalog_path
    argument is given and no default catalog is set in ~/.chartbook/settings.toml.

    Attributes:
        settings_path: Path to the settings file that should be configured.
    """

    def __init__(self, settings_path: Path):
        self.settings_path = settings_path
        super().__init__(
            f"No catalog configured. Either pass catalog_path= to data.load() "
            f"or run 'chartbook config' to set a default catalog in {settings_path}"
        )


class ManifestNotFoundError(FileNotFoundError):
    """Raised when no chartbook.toml encloses the place a lookup started from.

    A bare asset name resolves against the manifest of the pipeline the
    caller is in, found by walking up the directory tree.

    Attributes:
        start_dirs: The directories the upward search started from.
    """

    def __init__(self, start_dirs: list[Path]):
        self.start_dirs = list(start_dirs)
        searched = " or ".join(str(d) for d in self.start_dirs)
        super().__init__(
            f"No chartbook.toml found in {searched}, or in any parent "
            f"directory. A bare asset name resolves against the chartbook.toml "
            f"of the pipeline you are in: run from inside a pipeline, or say "
            f"which one with project_dir (--project-dir on the command line)."
        )


class AssetNotDeclaredError(LookupError):
    """Raised when a pipeline's chartbook.toml declares no such asset.

    The manifest is the single source of truth for where assets live, so a
    path is only handed out for a name it declares. The message says which
    table to add, or, if the name is declared as another kind of asset, how
    to refer to that.

    Attributes:
        name: The asset name that was asked for.
        kind: The kind of asset that was asked for.
        manifest_path: The chartbook.toml that was searched.
        declared: The asset names it does declare, by table.
    """

    def __init__(
        self,
        name: str,
        manifest_path: Path,
        declared: dict[str, list[str]],
        kind: str = DEFAULT_KIND,
        example_path: Optional[str] = None,
    ):
        self.name = name
        self.kind = kind
        self.manifest_path = manifest_path
        self.declared = declared

        table = KIND_TABLES[kind]
        kind_of = {t: k for k, t in KIND_TABLES.items()}
        lines = [f"No {kind} named {name!r} is declared in {manifest_path}."]

        other_kinds = [
            kind_of[t] for t, names in declared.items() if t != table and name in names
        ]
        if other_kinds:
            other = other_kinds[0]
            lines.append(
                f"It is declared as a {other}: refer to it as {other + '/' + name!r} "
                f"(in Python, chartbook.assets.path({other + '/' + name!r}))."
            )
        else:
            close = difflib.get_close_matches(name, declared.get(table, []), n=1)
            if close:
                lines.append(f"Did you mean {close[0]!r}?")
            lines += ["", "To register it, add a table to that file, for example:", ""]
            lines.append(f"    [{table}.{name}]")
            lines.append(f'    path = "{example_path or "..."}"')

        listing = "; ".join(
            f"{t}: {', '.join(names)}" for t, names in declared.items() if names
        )
        lines += ["", f"Declared assets: {listing or '(none)'}"]
        super().__init__("\n".join(lines))


class DependencyNotDeclaredError(LookupError):
    """Raised when a reference names a pipeline that is not a declared dependency.

    A pipeline may read only from the pipelines its ``[dependencies]``
    declares, so that what it depends on can be read off its manifest
    without running anything. The message says what to add.

    Attributes:
        reference: The reference that was asked for, as text.
        pipeline: The pipeline it names.
        manifest_path: The chartbook.toml that does not declare it.
        declared: The dependencies it does declare.
    """

    def __init__(
        self,
        reference: str,
        pipeline: str,
        manifest_path: Path,
        declared: list[str],
        found_at: Optional[tuple[str, str]] = None,
    ):
        self.reference = reference
        self.pipeline = pipeline
        self.manifest_path = manifest_path
        self.declared = list(declared)

        key, where = found_at or (pipeline, f"../{pipeline.rsplit('/', 1)[-1]}")
        lines = [
            f"Reference {reference!r} names an asset of the pipeline "
            f"{pipeline!r}, which is not declared in [dependencies] of "
            f"{manifest_path}.",
        ]
        close = difflib.get_close_matches(pipeline, self.declared, n=1)
        if close:
            lines.append(f"Did you mean {close[0]!r}?")
        if found_at:
            lines.append(f"Your catalog has it, as {key!r}.")
        lines += [
            "",
            "To read from another pipeline, say where it is, then pin it:",
            "",
            "    [dependencies]",
            f'    "{key}" = {{ path = "{where}" }}',
            "",
            "    $ chartbook pin",
            "",
            f"Declared dependencies: {', '.join(self.declared) or '(none)'}",
        ]
        super().__init__("\n".join(lines))


class AssetNotPinnedError(LookupError):
    """Raised when another pipeline's asset has no pinned copy to resolve to.

    A reference to another pipeline's asset resolves to the copy that
    ``chartbook.lock`` pins, in the store, and never to that pipeline's
    working directory. So there has to be a pin, and its bytes have to be
    in the store. The message says which is missing and what to run.

    Attributes:
        asset: The asset's ID, as the lockfile would have it.
        reason: What is missing: ``"no_lockfile"``, ``"not_in_lockfile"``,
            ``"not_built"``, ``"not_in_store"``, or ``"not_synced"`` (the
            store has the object, and not all of its bytes yet).
    """

    def __init__(self, asset: str, reason: str, message: str):
        self.asset = asset
        self.reason = reason
        super().__init__(message)


def handle_validation_error(error: ValidationError, config_path: Path) -> None:
    """Handle validation error with user-friendly output.

    This function converts a ValidationError to a ChartBookError and
    displays it to the user before exiting.

    :param error: The validation error to handle.
    :type error: ValidationError
    :param config_path: Path to the configuration file that caused the error.
    :type config_path: Path
    """
    chartbook_error = error.to_chartbook_error(file_path=config_path)
    chartbook_error.exit_with_message()


@dataclass
class MissingFile:
    """Information about a missing source file.

    Attributes:
        file_path: The path to the missing file.
        file_type: The type of file (e.g., "notebook", "chart", "dataframe").
        item_id: The ID of the item in chartbook.toml that references this file.
        pipeline_id: The pipeline ID that contains this item.
    """

    file_path: Path
    file_type: str
    item_id: str
    pipeline_id: str


class MissingSourceFilesError(Exception):
    """Raised when source files referenced in chartbook.toml are not found.

    This exception carries a list of missing files that can be used to generate
    user-friendly error messages for the CLI.

    Attributes:
        missing_files: List of MissingFile objects describing each missing file.
        hint: The lines the CLI message ends with, saying what to do.
    """

    #: The hint when the caller gives none. It suits a catalog, where
    #: --no-strict builds the pipelines that are not named.
    DEFAULT_HINT = (
        "Ensure these files exist or update the paths in chartbook.toml.",
        "Use --no-strict to skip affected pipelines instead of failing.",
    )

    def __init__(self, missing_files: list[MissingFile], hint: Optional[list[str]] = None):
        """Initialize a MissingSourceFilesError.

        :param missing_files: List of MissingFile objects.
        :type missing_files: list[MissingFile]
        :param hint: What to do about them, a line each; the default suits
            a catalog.
        :type hint: list[str] | None
        """
        self.missing_files = missing_files
        self.hint = list(hint) if hint else list(self.DEFAULT_HINT)
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format a simple message listing the count of missing files.

        :returns: A formatted string describing the error.
        :rtype: str
        """
        return f"Found {len(self.missing_files)} missing source file(s) referenced in chartbook.toml"

    def format_cli_message(self) -> str:
        """Format a detailed, user-friendly message for CLI output.

        :returns: A formatted string ready for CLI display with colors.
        :rtype: str
        """
        lines = [
            click.style("Error: ", fg="red", bold=True)
            + "Missing source files referenced in chartbook.toml",
            "",
            "The following files were not found:",
        ]

        for mf in self.missing_files:
            lines.append(
                f"  - {mf.file_type.capitalize()}: {click.style(str(mf.file_path), fg='cyan')}"
            )
            lines.append(
                f"    Referenced by: {click.style(f'{mf.file_type}s.{mf.item_id}', fg='yellow')} "
                f"in pipeline {click.style(mf.pipeline_id, fg='yellow')}"
            )

        lines.append("")
        first, *rest = self.hint
        lines.append(click.style("Hint: ", fg="green") + first)
        lines.extend(f"      {line}" for line in rest)

        return "\n".join(lines)

    def format_warnings(self) -> list[str]:
        """Format individual warning messages for each missing file.

        :returns: A list of warning message strings.
        :rtype: list[str]
        """
        warnings = []
        for mf in self.missing_files:
            warnings.append(
                f"Warning: Missing {mf.file_type} file: {mf.file_path} "
                f"(referenced by {mf.file_type}s.{mf.item_id} in pipeline {mf.pipeline_id})"
            )
        return warnings

    def get_pipelines_to_skip(self) -> set[str]:
        """Return the set of pipeline IDs that have missing files.

        :returns: Set of pipeline IDs with at least one missing file.
        :rtype: set[str]
        """
        return {mf.pipeline_id for mf in self.missing_files}

    def format_skip_warnings(self) -> list[str]:
        """Format per-pipeline skip warnings grouped by pipeline.

        :returns: A list of warning message strings, one header per pipeline
            followed by its missing files.
        :rtype: list[str]
        """
        from collections import defaultdict

        by_pipeline: dict[str, list[MissingFile]] = defaultdict(list)
        for mf in self.missing_files:
            by_pipeline[mf.pipeline_id].append(mf)

        warnings: list[str] = []
        for pipeline_id, files in by_pipeline.items():
            warnings.append(
                f"Warning: Skipping pipeline '{pipeline_id}' due to "
                f"{len(files)} missing file(s):"
            )
            for mf in files:
                warnings.append(f"  - {mf.file_type}: {mf.file_path}")
        return warnings

    def exit_with_message(self) -> None:
        """Print formatted message to stderr and exit with code 1.

        :raises SystemExit: Always exits with code 1.
        """
        click.echo(self.format_cli_message(), err=True)
        raise SystemExit(1)


class VersionNotFoundError(LookupError):
    """Raised when a reference names a version of an asset that cannot be found.

    A version is made by a snapshot (``chartbook run --snapshot``) and is
    named by the start of its content hash, ``model/x@7f3a9c2e41b0``, or by a
    label the manifest gives it, ``model/x@champion``.

    Attributes:
        asset: The asset's reference, without the revision.
        rev: The revision that was asked for.
        reason: What is wrong: ``"no_such_version"``, ``"ambiguous"`` or
            ``"not_in_store"``.
    """

    def __init__(self, asset: str, rev: str, reason: str, message: str):
        self.asset = asset
        self.rev = rev
        self.reason = reason
        super().__init__(message)

