"""Input validation utilities for chartbook.plotting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from chartbook.plotting._exceptions import DataValidationError

if TYPE_CHECKING:
    import pandas as pd


def validate_dataframe(df: "pd.DataFrame") -> None:
    """Validate that df is a pandas DataFrame."""
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        raise DataValidationError(
            column=None,
            message=f"Expected pandas DataFrame, got {type(df).__name__}",
        )

    if df.empty:
        raise DataValidationError(
            column=None,
            message="DataFrame is empty",
        )


def validate_columns_exist(
    df: "pd.DataFrame", columns: Sequence[str], context: str = ""
) -> None:
    """Validate that all specified columns exist in the DataFrame."""
    missing = [col for col in columns if col not in df.columns]
    if missing:
        ctx = f" for {context}" if context else ""
        raise DataValidationError(
            column=None,
            message=f"Missing columns{ctx}: {missing}. Available columns: {list(df.columns)}",
        )


def validate_numeric_columns(df: "pd.DataFrame", columns: Sequence[str]) -> None:
    """Validate that columns contain numeric data."""
    import pandas as pd

    for col in columns:
        if col not in df.columns:
            continue  # Will be caught by validate_columns_exist
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise DataValidationError(
                column=col,
                message=f"Expected numeric column, got {df[col].dtype}",
            )


def validate_datetime_column(df: "pd.DataFrame", column: str) -> None:
    """Validate that a column is datetime-like or can be converted."""
    import pandas as pd

    if column not in df.columns:
        return  # Will be caught by validate_columns_exist

    if pd.api.types.is_datetime64_any_dtype(df[column]):
        return  # Already datetime

    # Try to parse as datetime
    try:
        pd.to_datetime(df[column])
    except Exception as e:
        raise DataValidationError(
            column=column,
            message=f"Cannot convert to datetime: {e}",
        )


def validate_chart_id(chart_id: str) -> None:
    """Validate chart_id is a valid identifier."""
    if not chart_id:
        raise DataValidationError(
            column=None,
            message="chart_id cannot be empty",
        )

    # Check for invalid characters (should be valid for filenames)
    invalid_chars = set('<>:"/\\|?*')
    found_invalid = [c for c in chart_id if c in invalid_chars]
    if found_invalid:
        raise DataValidationError(
            column=None,
            message=f"chart_id contains invalid characters: {found_invalid}",
        )


def validate_overlay_hlines(hlines: list[dict]) -> None:
    """Validate horizontal line overlay configuration."""
    for i, hline in enumerate(hlines):
        if "y" not in hline:
            raise DataValidationError(
                column=None,
                message=f"hlines[{i}] missing required 'y' value",
            )


def validate_overlay_vlines(vlines: list[dict]) -> None:
    """Validate vertical line overlay configuration."""
    for i, vline in enumerate(vlines):
        if "x" not in vline:
            raise DataValidationError(
                column=None,
                message=f"vlines[{i}] missing required 'x' value",
            )


def validate_overlay_shaded_regions(regions: list[dict]) -> None:
    """Validate shaded region overlay configuration."""
    for i, region in enumerate(regions):
        if "x0" not in region or "x1" not in region:
            raise DataValidationError(
                column=None,
                message=f"shaded_regions[{i}] missing required 'x0' and/or 'x1' values",
            )


def validate_overlay_bands(df: "pd.DataFrame", bands: list[dict]) -> None:
    """Validate band overlay configuration."""
    for i, band in enumerate(bands):
        if "y_upper" not in band or "y_lower" not in band:
            raise DataValidationError(
                column=None,
                message=f"bands[{i}] missing required 'y_upper' and/or 'y_lower' column names",
            )
        # Check that referenced columns exist
        validate_columns_exist(
            df, [band["y_upper"], band["y_lower"]], context=f"bands[{i}]"
        )
