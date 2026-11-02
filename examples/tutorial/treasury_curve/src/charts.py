"""The two charts chartbook.toml declares, from the dataframe by its name."""

import chartbook
from chartbook import data

yields = data.load("zero_coupon_yields", format="pandas")

chartbook.plotting.line(
    yields,
    x="date",
    y=["SVENY02", "SVENY10", "SVENY30"],
    labels={"SVENY02": "2-year", "SVENY10": "10-year", "SVENY30": "30-year"},
    title="Treasury Yields Since 1961",
    y_title="Percent",
    source="Federal Reserve Board",
).save(chart_id="yields", output_dir="_output")

latest = yields.dropna().iloc[-1]
curve = (
    latest.drop("date").rename("yield").rename_axis("column").reset_index()
    .assign(maturity=lambda df: df["column"].str[-2:].astype(int))
)
chartbook.plotting.line(
    curve,
    x="maturity",
    y="yield",
    title=f"The Curve on {latest['date']:%B %d, %Y}, by Maturity in Years",
    y_title="Percent",
    source="Federal Reserve Board",
).save(chart_id="curve_today", output_dir="_output")
