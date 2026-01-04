"""Dual-axis chart API for chartbook.plotting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Sequence

from chartbook.plotting._config import get_config
from chartbook.plotting._output import create_dual_chart_result
from chartbook.plotting._types import ChartResult, DualAxisConfig, OverlayConfig
from chartbook.plotting._validation import (
    validate_columns_exist,
    validate_dataframe,
    validate_overlay_hlines,
    validate_overlay_shaded_regions,
)

if TYPE_CHECKING:
    import pandas as pd


def _normalize_y(y: str | Sequence[str]) -> list[str]:
    """Normalize y parameter to a list."""
    if isinstance(y, str):
        return [y]
    return list(y)


def dual(
    df: "pd.DataFrame",
    *,
    x: str,
    left_y: str | Sequence[str],
    right_y: str | Sequence[str],
    left_type: Literal["line", "bar", "scatter", "area"] = "line",
    right_type: Literal["line", "bar", "scatter", "area"] = "line",
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Axis titles
    x_title: str | None = None,
    left_y_title: str | None = None,
    right_y_title: str | None = None,
    # Axis ranges
    left_y_range: tuple[float, float] | None = None,
    right_y_range: tuple[float, float] | None = None,
    # Tick formatting
    left_y_tickformat: str | None = None,
    right_y_tickformat: str | None = None,
    # Colors
    left_colors: Sequence[str] | None = None,
    right_colors: Sequence[str] | None = None,
    # Overlays
    nber_recessions: bool | None = None,
    hlines: Sequence[dict[str, Any]] | None = None,
    shaded_regions: Sequence[dict[str, Any]] | None = None,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create a dual-axis chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    Combines two different chart types on left and right y-axes sharing
    a common x-axis.

    Parameters
    ----------
    df : DataFrame
        Data to plot.
    x : str
        Column name for shared x-axis.
    left_y : str | Sequence[str]
        Column name(s) for left y-axis.
    right_y : str | Sequence[str]
        Column name(s) for right y-axis.
    left_type : str
        Chart type for left axis: "line", "bar", "scatter", "area". Default: "line"
    right_type : str
        Chart type for right axis: "line", "bar", "scatter", "area". Default: "line"
    title : str, optional
        Chart title.
    caption : str, optional
        Caption text displayed above the chart.
    note : str, optional
        Note text displayed below the chart.
    source : str, optional
        Source attribution text.
    x_title : str, optional
        X-axis title.
    left_y_title : str, optional
        Left y-axis title.
    right_y_title : str, optional
        Right y-axis title.
    left_y_range : tuple, optional
        Left y-axis range as (min, max).
    right_y_range : tuple, optional
        Right y-axis range as (min, max).
    left_y_tickformat : str, optional
        Left y-axis tick format string.
    right_y_tickformat : str, optional
        Right y-axis tick format string.
    left_colors : Sequence[str], optional
        Colors for left axis series.
    right_colors : Sequence[str], optional
        Colors for right axis series.
    nber_recessions : bool, optional
        Show NBER recession shading. None uses global config.
    hlines : Sequence[dict], optional
        Horizontal reference lines (applied to left axis).
    shaded_regions : Sequence[dict], optional
        Shaded vertical regions.

    Returns
    -------
    ChartResult
        Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.

    Examples
    --------
    >>> import chartbook
    >>> import pandas as pd

    >>> df = pd.DataFrame({
    ...     "date": pd.date_range("2020", periods=12, freq="M"),
    ...     "gdp": range(100, 112),
    ...     "growth_rate": [0.01, 0.02, 0.015, 0.025, 0.03, 0.02, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035]
    ... })

    >>> # Display inline
    >>> chartbook.plotting.dual(
    ...     df, x="date", left_y="gdp", right_y="growth_rate",
    ...     left_type="bar", right_type="line"
    ... ).show()

    >>> # Save to files
    >>> result = chartbook.plotting.dual(
    ...     df, x="date", left_y="gdp", right_y="growth_rate",
    ...     left_type="bar", right_type="line",
    ...     left_y_title="GDP (Billions)",
    ...     right_y_title="Growth Rate (%)",
    ...     right_y_tickformat=".1%",
    ... )
    >>> result.save(chart_id="gdp_growth")
    >>> print(result.html_path)
    ./_output/gdp_growth.html

    >>> # With NBER recessions
    >>> chartbook.plotting.dual(
    ...     df, x="date", left_y="price", right_y="volume",
    ...     left_type="line", right_type="area",
    ...     nber_recessions=True
    ... ).save("price_volume")
    """
    # Validation
    validate_dataframe(df)
    left_y_cols = _normalize_y(left_y)
    right_y_cols = _normalize_y(right_y)
    validate_columns_exist(df, [x] + left_y_cols + right_y_cols)

    if hlines:
        validate_overlay_hlines(list(hlines))
    if shaded_regions:
        validate_overlay_shaded_regions(list(shaded_regions))

    # Build config
    config = DualAxisConfig(
        x=x,
        left_y=left_y_cols,
        right_y=right_y_cols,
        left_type=left_type,
        right_type=right_type,
        title=title,
        caption=caption,
        note=note,
        source=source,
        x_title=x_title,
        left_y_title=left_y_title,
        right_y_title=right_y_title,
        left_y_range=left_y_range,
        right_y_range=right_y_range,
        left_y_tickformat=left_y_tickformat,
        right_y_tickformat=right_y_tickformat,
        left_colors=list(left_colors) if left_colors else None,
        right_colors=list(right_colors) if right_colors else None,
        extra_kwargs=kwargs,
    )

    # Build overlay config
    global_config = get_config()
    overlay_config = OverlayConfig(
        nber_recessions=nber_recessions
        if nber_recessions is not None
        else global_config.nber_recessions,
        hlines=list(hlines) if hlines else [],
        shaded_regions=list(shaded_regions) if shaded_regions else [],
    )

    return create_dual_chart_result(df, config, overlay_config)
