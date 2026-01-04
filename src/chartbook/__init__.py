"""
chartbook - Data catalog and documentation generator.

For data loading:
    from chartbook import data
    df = data.load(pipeline_id="EX", dataframe_id="my_data")

For plotting:
    from chartbook import plotting
    plotting.line(df, chart_id="my_chart", x="date", y="value")

For CLI (install via pipx):
    pipx install chartbook
    chartbook build
"""

import importlib

from . import data
from .__about__ import __version__

# Lazy import for plotting to avoid requiring plotting dependencies
# when only using data loading features
_plotting_module = None


def __getattr__(name: str):
    global _plotting_module
    if name == "plotting":
        if _plotting_module is None:
            _plotting_module = importlib.import_module("chartbook.plotting")
        return _plotting_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "data",
    "plotting",
]
