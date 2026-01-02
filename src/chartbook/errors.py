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

        Returns:
            A formatted string ready for CLI output.
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
        """Print formatted message to stderr and exit with code 1."""
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
        super().__init__(message)
        self.field_name = field_name
        self.invalid_value = invalid_value
        self.hint = hint

    def to_chartbook_error(self, file_path: Optional[Path] = None) -> ChartBookError:
        """Convert to ChartBookError for CLI display.

        Args:
            file_path: Path to the file where the error occurred.

        Returns:
            A ChartBookError instance ready for CLI display.
        """
        return ChartBookError(
            message=str(self),
            file_path=file_path,
            field_name=self.field_name,
            invalid_value=self.invalid_value,
            hint=self.hint,
        )


def handle_validation_error(error: ValidationError, config_path: Path) -> None:
    """Handle validation error with user-friendly output.

    This function converts a ValidationError to a ChartBookError and
    displays it to the user before exiting.

    Args:
        error: The validation error to handle.
        config_path: Path to the configuration file that caused the error.
    """
    chartbook_error = error.to_chartbook_error(file_path=config_path)
    chartbook_error.exit_with_message()
