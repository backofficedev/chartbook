"""
chartbook - Data catalog and documentation generator.

For data loading:
    from chartbook import data
    df = data.load(pipeline_id="EX", dataframe_id="my_data")

For CLI (install via pipx):
    pipx install chartbook
    chartbook generate
"""

from . import data
from .__about__ import __version__

__all__ = [
    "__version__",
    "data",
]
