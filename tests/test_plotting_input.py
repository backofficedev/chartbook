"""What the chart functions take: a pandas frame, and what ``data.load()`` gives.

``data.load()`` returns a polars LazyFrame, so a chart made from what it
returns must not need a conversion first.
"""

from datetime import date

import pandas as pd
import polars as pl
import pytest

import chartbook
from chartbook.plotting._exceptions import DataValidationError

ROWS = {
    "date": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)],
    "rate": [3.5, 3.6, 3.85],
    "spread": [0.1, 0.2, 0.15],
}


def _frames():
    return {
        "pandas": pd.DataFrame(ROWS),
        "polars": pl.DataFrame(ROWS),
        "lazy": pl.LazyFrame(ROWS),
    }


@pytest.mark.parametrize("kind", ["pandas", "polars", "lazy"])
def test_line_takes_pandas_polars_and_a_lazy_frame(kind):
    result = chartbook.plotting.line(_frames()[kind], x="date", y="rate")
    (trace,) = result.figure.data
    assert list(trace.y) == ROWS["rate"]


@pytest.mark.parametrize("kind", ["polars", "lazy"])
def test_every_chart_function_takes_polars(kind):
    df = _frames()[kind]
    chartbook.plotting.bar(df, x="date", y="rate")
    chartbook.plotting.scatter(df, x="rate", y="spread")
    chartbook.plotting.area(df, x="date", y=["rate", "spread"])
    chartbook.plotting.pie(df, names="date", values="rate")
    chartbook.plotting.dual(df, x="date", left_y="rate", right_y="spread")


def test_a_lazy_frame_from_data_load_plots(tmp_path):
    """What ``data.load`` gives back for a parquet file is plotted as it is."""
    path = tmp_path / "rates.parquet"
    pl.DataFrame(ROWS).write_parquet(path)
    result = chartbook.plotting.line(pl.scan_parquet(path), x="date", y=["rate"])
    assert list(result.figure.data[0].y) == ROWS["rate"]


def test_an_empty_polars_frame_is_refused():
    with pytest.raises(DataValidationError, match="DataFrame is empty"):
        chartbook.plotting.line(pl.DataFrame(ROWS).head(0), x="date", y="rate")


def test_anything_else_is_refused_by_name():
    with pytest.raises(DataValidationError, match="pandas or polars DataFrame, got dict"):
        chartbook.plotting.line(ROWS, x="date", y="rate")
