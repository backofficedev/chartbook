"""Input validation utilities for chartbook.plotting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from chartbook.plotting._exceptions import DataValidationError

if TYPE_CHECKING:
    import pandas as pd


def validate_dataframe(df) -> "pd.DataFrame":
    """Validate df and return it as a pandas DataFrame.

    A polars DataFrame or LazyFrame, which is what ``data.load()`` returns,
    is collected and converted here: the plotting backends work on pandas.
    """
    import pandas as pd

    # Checked by module so that polars is imported only when it is passed
    if type(df).__module__.split(".")[0] == "polars":
        import polars as pl

        if isinstance(df, (pl.LazyFrame, pl.DataFrame)):
            # What pandas would make of these the backends cannot draw: an
            # unordered Categorical for a category or an enum, a Decimal
            # object that does not add to a float
            schema = df.collect_schema() if isinstance(df, pl.LazyFrame) else df.schema
            df = df.with_columns(
                [
                    pl.col(name).cast(pl.String if dtype.base_type() in (pl.Categorical, pl.Enum) else pl.Float64)
                    for name, dtype in schema.items()
                    if dtype.base_type() in (pl.Categorical, pl.Enum, pl.Decimal)
                ]
            )
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        if isinstance(df, pl.DataFrame):
            df = df.to_pandas()

    if not isinstance(df, pd.DataFrame):
        raise DataValidationError(
            column=None,
            message=f"Expected a pandas or polars DataFrame, got {type(df).__name__}",
        )

    if df.empty:
        raise DataValidationError(
            column=None,
            message="DataFrame is empty",
        )
    return df


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
    """Validate chart_id names the saved files well: ``<chart_id>.html``, ``<chart_id>_wide.pdf`` and so on.

    Refused: an empty id; a character no filename may hold on every
    platform; ``.`` and ``..``, which are not names; and a leading ``-`` or
    ``.``, which would make a file read as an option or hidden. Anything
    else is a name as written.
    """
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

    if chart_id in (".", ".."):
        raise DataValidationError(
            column=None,
            message=(
                f"chart_id {chart_id!r} is not a name: the saved files are named "
                f"<chart_id>.html, <chart_id>.png and so on, so '.' and '..' are refused"
            ),
        )

    if chart_id[0] in "-.":
        raise DataValidationError(
            column=None,
            message=(
                f"chart_id {chart_id!r} starts with {chart_id[0]!r}: a chart id may not start with "
                f"'-' or '.', since it names the saved files (<chart_id>.html, <chart_id>_wide.pdf) "
                f"and one so named is read as an option or hidden"
            ),
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
