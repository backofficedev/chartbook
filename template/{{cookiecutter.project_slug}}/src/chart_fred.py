"""The Fed's policy rates, from FRED: [charts.policy_rates] in chartbook.toml.

Reads the `fred` dataframe by its name, as chartbook.toml declares it, so the path is written once.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

# pull_fred.py saved the dates as the index
df = data.load("fred", format="pandas").reset_index().dropna(subset=["DFEDTARU"])

chartbook.plotting.line(
    df,
    x="DATE",
    y=["DFEDTARU", "DFEDTARL", "EFFR", "SOFR"],
    labels={
        "DFEDTARU": "Target range, upper",
        "DFEDTARL": "Target range, lower",
        "EFFR": "Effective fed funds rate",
        "SOFR": "SOFR",
    },
    title="The Fed's Policy Rates",
    y_title="Percent",
    source="FRED",
).save(chart_id="policy_rates", output_dir=OUTPUT_DIR)
