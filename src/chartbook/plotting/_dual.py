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
    """Normalize y parameter to a list.

    :param y: Y column name(s).
    :type y: str or Sequence[str]
    :returns: List of y column names.
    :rtype: list[str]
    """
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

    :param df: Data to plot.
    :type df: DataFrame
    :param x: Column name for shared x-axis.
    :type x: str
    :param left_y: Column name(s) for left y-axis.
    :type left_y: str or Sequence[str]
    :param right_y: Column name(s) for right y-axis.
    :type right_y: str or Sequence[str]
    :param left_type: Chart type for left axis: "line", "bar", "scatter", "area". Default: "line"
    :type left_type: str
    :param right_type: Chart type for right axis: "line", "bar", "scatter", "area". Default: "line"
    :type right_type: str
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :param x_title: X-axis title.
    :type x_title: str, optional
    :param left_y_title: Left y-axis title.
    :type left_y_title: str, optional
    :param right_y_title: Right y-axis title.
    :type right_y_title: str, optional
    :param left_y_range: Left y-axis range as (min, max).
    :type left_y_range: tuple, optional
    :param right_y_range: Right y-axis range as (min, max).
    :type right_y_range: tuple, optional
    :param left_y_tickformat: Left y-axis tick format string.
    :type left_y_tickformat: str, optional
    :param right_y_tickformat: Right y-axis tick format string.
    :type right_y_tickformat: str, optional
    :param left_colors: Colors for left axis series.
    :type left_colors: Sequence[str], optional
    :param right_colors: Colors for right axis series.
    :type right_colors: Sequence[str], optional
    :param nber_recessions: Show NBER recession shading. None uses global config.
    :type nber_recessions: bool, optional
    :param hlines: Horizontal reference lines (applied to left axis).
    :type hlines: Sequence[dict], optional
    :param shaded_regions: Shaded vertical regions.
    :type shaded_regions: Sequence[dict], optional
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult

    Examples
    --------

    ```python
    import chartbook
    import pandas as pd

    df = pd.DataFrame({
        "date": pd.date_range("2020", periods=12, freq="M"),
        "gdp": range(100, 112),
        "growth_rate": [0.01, 0.02, 0.015, 0.025, 0.03, 0.02, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035]
    })

    # Display inline
    chartbook.plotting.dual(
        df, x="date", left_y="gdp", right_y="growth_rate",
        left_type="bar", right_type="line"
    ).show()

    # Save to files
    result = chartbook.plotting.dual(
        df, x="date", left_y="gdp", right_y="growth_rate",
        left_type="bar", right_type="line",
        left_y_title="GDP (Billions)",
        right_y_title="Growth Rate (%)",
        right_y_tickformat=".1%",
    )
    result.save(chart_id="gdp_growth")
    print(result.html_path)
    # Output: ./_output/gdp_growth.html

    # With NBER recessions
    chartbook.plotting.dual(
        df, x="date", left_y="price", right_y="volume",
        left_type="line", right_type="area",
        nber_recessions=True
    ).save("price_volume")
    ```
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
