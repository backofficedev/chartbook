"""
ChartBook Plotting Module - Simple, consistent chart creation.

Usage:
    import chartbook

    # Basic charts
    chartbook.plotting.line(df, x="date", y="value").save(chart_id="gdp")
    chartbook.plotting.bar(df, x="category", y="amount").save(chart_id="sales")
    chartbook.plotting.scatter(df, x="x", y="y").save(chart_id="correlation")
    chartbook.plotting.pie(df, names="category", values="amount").save(chart_id="shares")
    chartbook.plotting.area(df, x="date", y="value").save(chart_id="trend")

    # Dual-axis charts
    chartbook.plotting.dual(
        df, x="date",
        left_y="gdp", right_y="rate",
        left_type="bar", right_type="line"
    ).save(chart_id="gdp_rate")

    # Configuration
    chartbook.plotting.configure(nber_recessions=True, default_output_dir="./_output")
    chartbook.plotting.set_style("chartbook")  # or path to .mplstyle
"""

from chartbook.plotting._api import area, bar, line, pie, scatter
from chartbook.plotting._config import configure, get_config, set_style
from chartbook.plotting._dual import dual
from chartbook.plotting._types import (
    ChartConfig,
    ChartResult,
    DualAxisConfig,
    OverlayConfig,
)

__all__ = [
    # Chart functions
    "line",
    "bar",
    "scatter",
    "pie",
    "area",
    "dual",
    # Configuration
    "configure",
    "get_config",
    "set_style",
    # Types
    "ChartConfig",
    "ChartResult",
    "OverlayConfig",
    "DualAxisConfig",
]
