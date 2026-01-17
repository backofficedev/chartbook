"""Core chart API functions for chartbook.plotting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from chartbook.plotting._config import get_config
from chartbook.plotting._output import create_chart_result
from chartbook.plotting._types import ChartConfig, ChartResult, OverlayConfig
from chartbook.plotting._validation import (
    validate_columns_exist,
    validate_dataframe,
    validate_overlay_bands,
    validate_overlay_hlines,
    validate_overlay_shaded_regions,
    validate_overlay_vlines,
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


def _build_overlay_config(
    nber_recessions: bool | None,
    hlines: Sequence[dict[str, Any]] | None,
    vlines: Sequence[dict[str, Any]] | None,
    shaded_regions: Sequence[dict[str, Any]] | None,
    bands: Sequence[dict[str, Any]] | None,
    regression_line: bool,
) -> OverlayConfig:
    """Build OverlayConfig from parameters.

    :param nber_recessions: Whether to show NBER recession shading.
    :type nber_recessions: bool, optional
    :param hlines: Horizontal reference lines.
    :type hlines: Sequence[dict[str, Any]], optional
    :param vlines: Vertical reference lines.
    :type vlines: Sequence[dict[str, Any]], optional
    :param shaded_regions: Shaded vertical regions.
    :type shaded_regions: Sequence[dict[str, Any]], optional
    :param bands: Fill between y-columns.
    :type bands: Sequence[dict[str, Any]], optional
    :param regression_line: Whether to add a regression line.
    :type regression_line: bool
    :returns: The overlay configuration.
    :rtype: OverlayConfig
    """
    config = get_config()

    return OverlayConfig(
        nber_recessions=nber_recessions
        if nber_recessions is not None
        else config.nber_recessions,
        hlines=list(hlines) if hlines else [],
        vlines=list(vlines) if vlines else [],
        shaded_regions=list(shaded_regions) if shaded_regions else [],
        bands=list(bands) if bands else [],
        regression_line=regression_line,
    )


def line(
    df: "pd.DataFrame",
    *,
    x: str,
    y: str | Sequence[str],
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Series customization
    color: str | Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
    # Axis configuration
    x_title: str | None = None,
    y_title: str | None = None,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    x_tickformat: str | None = None,
    y_tickformat: str | None = None,
    # Overlays
    nber_recessions: bool | None = None,
    hlines: Sequence[dict[str, Any]] | None = None,
    vlines: Sequence[dict[str, Any]] | None = None,
    shaded_regions: Sequence[dict[str, Any]] | None = None,
    bands: Sequence[dict[str, Any]] | None = None,
    regression_line: bool = False,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create a line chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    :param df: Data to plot.
    :type df: DataFrame
    :param x: Column name for x-axis.
    :type x: str
    :param y: Column name(s) for y-axis. Multiple columns create multiple series.
    :type y: str or Sequence[str]
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :param color: Color(s) for the series.
    :type color: str or Sequence[str], optional
    :param labels: Mapping of column names to display labels.
    :type labels: dict, optional
    :param x_title: X-axis title.
    :type x_title: str, optional
    :param y_title: Y-axis title.
    :type y_title: str, optional
    :param x_range: X-axis range as (min, max).
    :type x_range: tuple, optional
    :param y_range: Y-axis range as (min, max).
    :type y_range: tuple, optional
    :param x_tickformat: X-axis tick format string.
    :type x_tickformat: str, optional
    :param y_tickformat: Y-axis tick format string.
    :type y_tickformat: str, optional
    :param nber_recessions: Show NBER recession shading. None uses global config.
    :type nber_recessions: bool, optional
    :param hlines: Horizontal reference lines. Each dict: {"y": value, "color": "gray", "dash": "solid", "label": "..."}.
    :type hlines: Sequence[dict], optional
    :param vlines: Vertical reference lines. Each dict: {"x": value, "color": "gray", "dash": "solid", "label": "..."}.
    :type vlines: Sequence[dict], optional
    :param shaded_regions: Shaded vertical regions. Each dict: {"x0": start, "x1": end, "color": "gray", "alpha": 0.3, "label": "..."}.
    :type shaded_regions: Sequence[dict], optional
    :param bands: Fill between y-columns. Each dict: {"y_upper": col, "y_lower": col, "color": "blue", "alpha": 0.3}.
    :type bands: Sequence[dict], optional
    :param regression_line: If True, add a linear regression trend line. Default: False
    :type regression_line: bool
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult

    Examples
    --------

    ```python
    import chartbook
    import pandas as pd
    df = pd.DataFrame({"date": pd.date_range("2020", periods=12, freq="M"), "gdp": range(12)})

    # Display inline
    chartbook.plotting.line(df, x="date", y="gdp").show()

    # Save to files
    result = chartbook.plotting.line(df, x="date", y="gdp", title="GDP Growth")
    result.save(chart_id="gdp")
    print(result.html_path)
    # Output: ./_output/gdp.html

    # Multiple series with NBER recessions
    chartbook.plotting.line(
        df, x="date", y=["gdp", "cpi"],
        title="Economic Indicators", nber_recessions=True
    ).save("indicators")
    ```
    """
    # Validation
    validate_dataframe(df)
    y_cols = _normalize_y(y)
    validate_columns_exist(df, [x] + y_cols)

    if hlines:
        validate_overlay_hlines(list(hlines))
    if vlines:
        validate_overlay_vlines(list(vlines))
    if shaded_regions:
        validate_overlay_shaded_regions(list(shaded_regions))
    if bands:
        validate_overlay_bands(df, list(bands))

    # Build configs
    chart_config = ChartConfig(
        chart_type="line",
        x=x,
        y=y_cols,
        title=title,
        caption=caption,
        note=note,
        source=source,
        color=color,
        labels=labels,
        x_title=x_title,
        y_title=y_title,
        x_range=x_range,
        y_range=y_range,
        x_tickformat=x_tickformat,
        y_tickformat=y_tickformat,
        extra_kwargs=kwargs,
    )

    overlay_config = _build_overlay_config(
        nber_recessions, hlines, vlines, shaded_regions, bands, regression_line
    )

    return create_chart_result(df, chart_config, overlay_config)


def bar(
    df: "pd.DataFrame",
    *,
    x: str,
    y: str | Sequence[str],
    stacked: bool = False,
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Series customization
    color: str | Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
    # Axis configuration
    x_title: str | None = None,
    y_title: str | None = None,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    y_tickformat: str | None = None,
    # Overlays
    nber_recessions: bool | None = None,
    hlines: Sequence[dict[str, Any]] | None = None,
    shaded_regions: Sequence[dict[str, Any]] | None = None,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create a bar chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    :param df: Data to plot.
    :type df: DataFrame
    :param x: Column name for x-axis (categories).
    :type x: str
    :param y: Column name(s) for y-axis values.
    :type y: str or Sequence[str]
    :param stacked: If True, stack bars instead of grouping. Default: False
    :type stacked: bool
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :param color: Color(s) for the series.
    :type color: str or Sequence[str], optional
    :param labels: Mapping of column names to display labels.
    :type labels: dict, optional
    :param x_title: X-axis title.
    :type x_title: str, optional
    :param y_title: Y-axis title.
    :type y_title: str, optional
    :param x_range: X-axis range as (min, max).
    :type x_range: tuple, optional
    :param y_range: Y-axis range as (min, max).
    :type y_range: tuple, optional
    :param y_tickformat: Y-axis tick format string.
    :type y_tickformat: str, optional
    :param nber_recessions: Show NBER recession shading. None uses global config.
    :type nber_recessions: bool, optional
    :param hlines: Horizontal reference lines.
    :type hlines: Sequence[dict], optional
    :param shaded_regions: Shaded vertical regions.
    :type shaded_regions: Sequence[dict], optional
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult
    """
    validate_dataframe(df)
    y_cols = _normalize_y(y)
    validate_columns_exist(df, [x] + y_cols)

    if hlines:
        validate_overlay_hlines(list(hlines))
    if shaded_regions:
        validate_overlay_shaded_regions(list(shaded_regions))

    chart_config = ChartConfig(
        chart_type="bar",
        x=x,
        y=y_cols,
        title=title,
        caption=caption,
        note=note,
        source=source,
        color=color,
        labels=labels,
        x_title=x_title,
        y_title=y_title,
        x_range=x_range,
        y_range=y_range,
        y_tickformat=y_tickformat,
        stacked=stacked,
        extra_kwargs=kwargs,
    )

    overlay_config = _build_overlay_config(
        nber_recessions, hlines, None, shaded_regions, None, False
    )

    return create_chart_result(df, chart_config, overlay_config)


def scatter(
    df: "pd.DataFrame",
    *,
    x: str,
    y: str,
    # Scatter-specific
    size: str | None = None,
    color_by: str | None = None,
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Series customization
    color: str | None = None,
    # Axis configuration
    x_title: str | None = None,
    y_title: str | None = None,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    x_tickformat: str | None = None,
    y_tickformat: str | None = None,
    # Overlays
    hlines: Sequence[dict[str, Any]] | None = None,
    vlines: Sequence[dict[str, Any]] | None = None,
    regression_line: bool = False,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create a scatter chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    :param df: Data to plot.
    :type df: DataFrame
    :param x: Column name for x-axis.
    :type x: str
    :param y: Column name for y-axis.
    :type y: str
    :param size: Column name for marker size.
    :type size: str, optional
    :param color_by: Column name for categorical coloring.
    :type color_by: str, optional
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :param color: Color for the markers.
    :type color: str, optional
    :param x_title: X-axis title.
    :type x_title: str, optional
    :param y_title: Y-axis title.
    :type y_title: str, optional
    :param x_range: X-axis range as (min, max).
    :type x_range: tuple, optional
    :param y_range: Y-axis range as (min, max).
    :type y_range: tuple, optional
    :param x_tickformat: X-axis tick format string.
    :type x_tickformat: str, optional
    :param y_tickformat: Y-axis tick format string.
    :type y_tickformat: str, optional
    :param hlines: Horizontal reference lines.
    :type hlines: Sequence[dict], optional
    :param vlines: Vertical reference lines.
    :type vlines: Sequence[dict], optional
    :param regression_line: If True, add a linear regression trend line. Default: False
    :type regression_line: bool
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult
    """
    validate_dataframe(df)
    cols_to_check = [x, y]
    if size:
        cols_to_check.append(size)
    if color_by:
        cols_to_check.append(color_by)
    validate_columns_exist(df, cols_to_check)

    if hlines:
        validate_overlay_hlines(list(hlines))
    if vlines:
        validate_overlay_vlines(list(vlines))

    chart_config = ChartConfig(
        chart_type="scatter",
        x=x,
        y=[y],
        title=title,
        caption=caption,
        note=note,
        source=source,
        color=color,
        x_title=x_title,
        y_title=y_title,
        x_range=x_range,
        y_range=y_range,
        x_tickformat=x_tickformat,
        y_tickformat=y_tickformat,
        size=size,
        color_by=color_by,
        extra_kwargs=kwargs,
    )

    overlay_config = _build_overlay_config(
        False, hlines, vlines, None, None, regression_line
    )

    return create_chart_result(df, chart_config, overlay_config)


def pie(
    df: "pd.DataFrame",
    *,
    names: str,
    values: str,
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create a pie chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    :param df: Data to plot.
    :type df: DataFrame
    :param names: Column name for category labels.
    :type names: str
    :param values: Column name for slice values.
    :type values: str
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult
    """
    validate_dataframe(df)
    validate_columns_exist(df, [names, values])

    chart_config = ChartConfig(
        chart_type="pie",
        x=names,  # Use x for names
        y=[values],  # Use y for values
        title=title,
        caption=caption,
        note=note,
        source=source,
        names=names,
        values=values,
        extra_kwargs=kwargs,
    )

    # Pie charts don't use overlays
    overlay_config = OverlayConfig()

    return create_chart_result(df, chart_config, overlay_config)


def area(
    df: "pd.DataFrame",
    *,
    x: str,
    y: str | Sequence[str],
    stacked: bool = True,
    # Annotations
    title: str | None = None,
    caption: str | None = None,
    note: str | None = None,
    source: str | None = None,
    # Series customization
    color: str | Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
    # Axis configuration
    x_title: str | None = None,
    y_title: str | None = None,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    x_tickformat: str | None = None,
    y_tickformat: str | None = None,
    # Overlays
    nber_recessions: bool | None = None,
    hlines: Sequence[dict[str, Any]] | None = None,
    shaded_regions: Sequence[dict[str, Any]] | None = None,
    # Advanced
    **kwargs: Any,
) -> ChartResult:
    """Create an area chart.

    Returns a ChartResult with the figure. Call `.show()` to display inline,
    or `.save(chart_id)` to export to multiple formats.

    :param df: Data to plot.
    :type df: DataFrame
    :param x: Column name for x-axis.
    :type x: str
    :param y: Column name(s) for y-axis values.
    :type y: str or Sequence[str]
    :param stacked: If True, stack areas. Default: True
    :type stacked: bool
    :param title: Chart title.
    :type title: str, optional
    :param caption: Caption text displayed above the chart.
    :type caption: str, optional
    :param note: Note text displayed below the chart.
    :type note: str, optional
    :param source: Source attribution text.
    :type source: str, optional
    :param color: Color(s) for the series.
    :type color: str or Sequence[str], optional
    :param labels: Mapping of column names to display labels.
    :type labels: dict, optional
    :param x_title: X-axis title.
    :type x_title: str, optional
    :param y_title: Y-axis title.
    :type y_title: str, optional
    :param x_range: X-axis range as (min, max).
    :type x_range: tuple, optional
    :param y_range: Y-axis range as (min, max).
    :type y_range: tuple, optional
    :param x_tickformat: X-axis tick format string.
    :type x_tickformat: str, optional
    :param y_tickformat: Y-axis tick format string.
    :type y_tickformat: str, optional
    :param nber_recessions: Show NBER recession shading. None uses global config.
    :type nber_recessions: bool, optional
    :param hlines: Horizontal reference lines.
    :type hlines: Sequence[dict], optional
    :param shaded_regions: Shaded vertical regions.
    :type shaded_regions: Sequence[dict], optional
    :returns: Object with `.show()`, `.save(chart_id)`, `.figure`, `.mpl_figure`, `.mpl_axes`.
    :rtype: ChartResult
    """
    validate_dataframe(df)
    y_cols = _normalize_y(y)
    validate_columns_exist(df, [x] + y_cols)

    if hlines:
        validate_overlay_hlines(list(hlines))
    if shaded_regions:
        validate_overlay_shaded_regions(list(shaded_regions))

    chart_config = ChartConfig(
        chart_type="area",
        x=x,
        y=y_cols,
        title=title,
        caption=caption,
        note=note,
        source=source,
        color=color,
        labels=labels,
        x_title=x_title,
        y_title=y_title,
        x_range=x_range,
        y_range=y_range,
        x_tickformat=x_tickformat,
        y_tickformat=y_tickformat,
        stacked=stacked,
        extra_kwargs=kwargs,
    )

    overlay_config = _build_overlay_config(
        nber_recessions, hlines, None, shaded_regions, None, False
    )

    return create_chart_result(df, chart_config, overlay_config)
