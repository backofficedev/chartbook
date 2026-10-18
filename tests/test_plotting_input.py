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


@pytest.mark.parametrize("kind", ["polars", "lazy"])
def test_a_category_and_an_enum_are_drawn_as_text(kind):
    """Found by a reviewer: pandas made these unordered Categoricals, which the
    backends refused ("Categorical is not ordered")."""
    names = ["a", "b", "c"]
    frame = pl.DataFrame(
        {
            "cat": pl.Series(names, dtype=pl.Categorical),
            "enum": pl.Series(names, dtype=pl.Enum(names)),
            "rate": ROWS["rate"],
            "spread": ROWS["spread"],
        }
    )
    df = frame.lazy() if kind == "lazy" else frame
    for x in ("cat", "enum"):
        result = chartbook.plotting.line(df, x=x, y="rate")
        assert list(result.figure.data[0].x) == names
        chartbook.plotting.bar(df, x=x, y="rate")
        chartbook.plotting.scatter(df, x=x, y="rate")
        chartbook.plotting.area(df, x=x, y=["rate", "spread"])
        chartbook.plotting.dual(df, x=x, left_y="rate", right_y="spread")


def test_a_pandas_category_x_column_is_drawn():
    """Found by a reviewer: every chart asked the x column for its least and greatest,
    which an unordered pandas category has not. Only the recession shading needs them."""
    from chartbook.plotting._overlays import _x_range

    df = pd.DataFrame({"c": pd.Categorical(["a", "b", "c"]), "rate": ROWS["rate"], "spread": ROWS["spread"]})
    result = chartbook.plotting.line(df, x="c", y="rate")
    assert list(result.figure.data[0].x) == ["a", "b", "c"]
    assert result.mpl_figure is not None
    chartbook.plotting.bar(df, x="c", y="rate")
    chartbook.plotting.scatter(df, x="c", y="rate")
    chartbook.plotting.area(df, x="c", y=["rate", "spread"])
    chartbook.plotting.dual(df, x="c", left_y="rate", right_y="spread")
    assert _x_range(df["c"]) == (None, None)
    assert _x_range(df["c"].cat.as_ordered()) == ("a", "c")


def test_a_decimal_column_is_drawn_as_a_float():
    """Found by a reviewer: pandas kept a Decimal as an object, and an area chart
    failed adding it to a float."""
    from decimal import Decimal

    df = pl.DataFrame(
        {
            "date": ROWS["date"],
            "rate": pl.Series([Decimal("3.50"), Decimal("3.60"), Decimal("3.85")], dtype=pl.Decimal(10, 2)),
            "spread": ROWS["spread"],
        }
    )
    result = chartbook.plotting.area(df, x="date", y=["rate", "spread"])
    assert list(result.figure.data[0].y) == [3.5, 3.6, 3.85]


@pytest.mark.parametrize("chart_id", [".", ".."])
def test_a_chart_id_that_is_a_dot_or_two_is_refused(chart_id, tmp_path):
    """Found by a reviewer: `..` was accepted and saved as `...html` and `.._wide.pdf`."""
    from chartbook.plotting._validation import validate_chart_id

    with pytest.raises(DataValidationError, match="is not a name"):
        validate_chart_id(chart_id)
    with pytest.raises(DataValidationError, match="is not a name"):
        chartbook.plotting.line(pd.DataFrame(ROWS), x="date", y="rate").save(chart_id, output_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("chart_id", ["-flag", "-", ".hidden", ".gdp"])
def test_a_chart_id_starting_with_a_dash_or_a_dot_is_refused(chart_id):
    from chartbook.plotting._validation import validate_chart_id

    with pytest.raises(DataValidationError, match=r"may not start with '-' or '\.'") as caught:
        validate_chart_id(chart_id)
    assert repr(chart_id) in str(caught.value) and "<chart_id>.html" in str(caught.value)


@pytest.mark.parametrize("chart_id", ["gdp_growth", "curve-today", "q1.2024", "Chart 1", "2024", "_draft", "ünïcode", "a..b"])
def test_every_name_that_was_valid_still_is(chart_id):
    from chartbook.plotting._validation import validate_chart_id

    validate_chart_id(chart_id)


def test_a_chart_id_with_a_separator_or_a_colon_is_still_refused():
    from chartbook.plotting._validation import validate_chart_id

    for chart_id in ("a/b", "a\\b", "a:b", "a*b", ""):
        with pytest.raises(DataValidationError):
            validate_chart_id(chart_id)
