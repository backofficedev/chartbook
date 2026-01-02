"""Tests for the errors module."""

from pathlib import Path

import pytest

from chartbook.errors import ChartBookError, ValidationError


class TestChartBookError:
    """Tests for ChartBookError dataclass."""

    def test_format_message_basic(self):
        """Test basic error message formatting."""
        error = ChartBookError(message="Something went wrong")
        formatted = error.format_message()

        assert "Error:" in formatted
        assert "Something went wrong" in formatted

    def test_format_message_with_file_path(self):
        """Test error message includes file path."""
        error = ChartBookError(
            message="Invalid configuration",
            file_path=Path("/path/to/chartbook.toml"),
        )
        formatted = error.format_message()

        assert "File:" in formatted
        assert "/path/to/chartbook.toml" in formatted

    def test_format_message_with_field_name(self):
        """Test error message includes field name."""
        error = ChartBookError(
            message="Invalid value",
            field_name="site.title",
        )
        formatted = error.format_message()

        assert "Field:" in formatted
        assert "site.title" in formatted

    def test_format_message_with_invalid_value(self):
        """Test error message includes invalid value."""
        error = ChartBookError(
            message="Invalid characters",
            invalid_value="test value",
        )
        formatted = error.format_message()

        assert "Value:" in formatted
        assert "test value" in formatted

    def test_format_message_truncates_long_values(self):
        """Test that long values are truncated for display."""
        long_value = "x" * 100
        error = ChartBookError(
            message="Value too long",
            invalid_value=long_value,
        )
        formatted = error.format_message()

        # Should be truncated to 50 chars + "..."
        assert "..." in formatted
        # Full value should not appear
        assert long_value not in formatted

    def test_format_message_with_hint(self):
        """Test error message includes hint."""
        error = ChartBookError(
            message="Invalid configuration",
            hint="Try using only alphanumeric characters.",
        )
        formatted = error.format_message()

        assert "Hint:" in formatted
        assert "Try using only alphanumeric characters." in formatted

    def test_format_message_full(self):
        """Test error message with all fields populated."""
        error = ChartBookError(
            message="Field contains invalid characters",
            file_path=Path("/project/chartbook.toml"),
            field_name="site.title",
            invalid_value='Test"; import os',
            hint="Remove quotes and semicolons.",
        )
        formatted = error.format_message()

        assert "Error:" in formatted
        assert "Field contains invalid characters" in formatted
        assert "File:" in formatted
        assert "/project/chartbook.toml" in formatted
        assert "Field:" in formatted
        assert "site.title" in formatted
        assert "Value:" in formatted
        assert "Hint:" in formatted
        assert "Remove quotes and semicolons." in formatted

    def test_exit_with_message_raises_system_exit(self):
        """Test that exit_with_message raises SystemExit."""
        error = ChartBookError(message="Fatal error")

        with pytest.raises(SystemExit) as exc_info:
            error.exit_with_message()

        assert exc_info.value.code == 1


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_basic_validation_error(self):
        """Test creating a basic ValidationError."""
        error = ValidationError("Validation failed")

        assert str(error) == "Validation failed"
        assert error.field_name is None
        assert error.invalid_value is None
        assert error.hint is None

    def test_validation_error_with_context(self):
        """Test ValidationError with full context."""
        error = ValidationError(
            message="Field contains invalid characters",
            field_name="site.title",
            invalid_value="bad;value",
            hint="Remove semicolons.",
        )

        assert str(error) == "Field contains invalid characters"
        assert error.field_name == "site.title"
        assert error.invalid_value == "bad;value"
        assert error.hint == "Remove semicolons."

    def test_to_chartbook_error_without_file_path(self):
        """Test converting ValidationError to ChartBookError without file path."""
        error = ValidationError(
            message="Invalid value",
            field_name="site.author",
            invalid_value="test()",
            hint="Remove parentheses.",
        )
        chartbook_error = error.to_chartbook_error()

        assert chartbook_error.message == "Invalid value"
        assert chartbook_error.file_path is None
        assert chartbook_error.field_name == "site.author"
        assert chartbook_error.invalid_value == "test()"
        assert chartbook_error.hint == "Remove parentheses."

    def test_to_chartbook_error_with_file_path(self):
        """Test converting ValidationError to ChartBookError with file path."""
        error = ValidationError(
            message="Configuration error",
            field_name="site.title",
        )
        chartbook_error = error.to_chartbook_error(
            file_path=Path("/project/chartbook.toml")
        )

        assert chartbook_error.file_path == Path("/project/chartbook.toml")
        assert chartbook_error.message == "Configuration error"
        assert chartbook_error.field_name == "site.title"

    def test_validation_error_is_exception(self):
        """Test that ValidationError can be raised and caught."""
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError(
                message="Test error",
                field_name="test.field",
            )

        assert exc_info.value.field_name == "test.field"
