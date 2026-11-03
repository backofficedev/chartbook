"""The S&P 500, from Bloomberg: [charts.sp500] in chartbook.toml.

Reads the `bloomberg` dataframe by its name, as chartbook.toml declares it.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

# pull_bloomberg.py saved the dates as the index
df = data.load("bloomberg", format="pandas").reset_index()

chartbook.plotting.line(
    df,
    x="Date",
    y="index",
    labels={"index": "S&P 500"},
    title="The S&P 500 Index",
    y_title="Index level",
    source="Bloomberg",
).save(chart_id="sp500", output_dir=OUTPUT_DIR)
