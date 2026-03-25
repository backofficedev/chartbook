"""User-friendly error handling for chartbook CLI.

This module provides structured error types and formatting utilities
that produce readable, actionable error messages for CLI users.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click


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
    """

    def __init__(self, missing_files: list[MissingFile]):
        """Initialize a MissingSourceFilesError.

        :param missing_files: List of MissingFile objects.
        :type missing_files: list[MissingFile]
        """
        self.missing_files = missing_files
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
        lines.append(
            click.style("Hint: ", fg="green")
            + "Ensure these files exist or update the paths in chartbook.toml."
        )
        lines.append("      Use --no-strict to skip affected pipelines instead of failing.")

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
