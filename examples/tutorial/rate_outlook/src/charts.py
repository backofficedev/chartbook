"""The chart chartbook.toml declares, from the dataframe by its name."""

import chartbook
from chartbook import data

spread = data.load("term_spread", format="pandas")

chartbook.plotting.line(
    spread,
    x="date",
    y=["spread", "unemployment"],
    labels={"spread": "10-year less 2-year yield", "unemployment": "Unemployment rate"},
    title="The Term Spread and Unemployment",
    y_title="Percent",
    hlines=[{"y": 0}],
    source="Federal Reserve Board; BLS",
    nber_recessions=True,
).save(chart_id="term_spread", output_dir="_output")
