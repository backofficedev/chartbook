"""Treasury yields from the Fed's zero-coupon curve: [charts.treasury_yields] in chartbook.toml.

Reads the `fed_yield_curve` dataframe by its name, as chartbook.toml declares it.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

# load_fed_yield_curve.py saved the dates as the index
df = data.load("fed_yield_curve", format="pandas").reset_index()

chartbook.plotting.line(
    df,
    x="Date",
    y=["SVENY02", "SVENY10", "SVENY30"],
    labels={"SVENY02": "2-year", "SVENY10": "10-year", "SVENY30": "30-year"},
    title="Zero-Coupon Treasury Yields",
    y_title="Percent",
    source="Federal Reserve Board, Gurkaynak, Sack and Wright (2007)",
).save(chart_id="treasury_yields", output_dir=OUTPUT_DIR)
