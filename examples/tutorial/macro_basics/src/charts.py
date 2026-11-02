"""The two charts chartbook.toml declares, from the dataframe by its name."""

import chartbook
from chartbook import data

macro = data.load("macro_series", format="pandas")

chartbook.plotting.line(
    macro,
    x="date",
    y=["unemployment", "inflation"],
    labels={"unemployment": "Unemployment rate", "inflation": "CPI inflation, year over year"},
    title="Unemployment and Inflation",
    y_title="Percent",
    source="BLS, through FRED",
    nber_recessions=True,
).save(chart_id="unemployment_and_inflation", output_dir="_output")

chartbook.plotting.line(
    macro,
    x="date",
    y="payrolls",
    labels={"payrolls": "Change in nonfarm payrolls"},
    title="Jobs Added Each Month",
    y_title="Thousands of jobs",
    y_range=(-1000, 1200),
    source="BLS, through FRED",
    nber_recessions=True,
).save(chart_id="payrolls", output_dir="_output")
