"""
ChartBook Plotting Module - Simple, consistent chart creation.

Usage:
    import chartbook

    # Basic charts
    chartbook.plotting.line(df, chart_id="gdp", x="date", y="value")
    chartbook.plotting.bar(df, chart_id="sales", x="category", y="amount")
    chartbook.plotting.scatter(df, chart_id="correlation", x="x", y="y")
    chartbook.plotting.pie(df, chart_id="shares", names="category", values="amount")
    chartbook.plotting.area(df, chart_id="trend", x="date", y="value")

    # Dual-axis charts
    chartbook.plotting.dual(
        df, chart_id="gdp_rate", x="date",
        left_y="gdp", right_y="rate",
        left_type="bar", right_type="line"
    )

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
