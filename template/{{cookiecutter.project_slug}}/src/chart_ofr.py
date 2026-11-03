"""Repo reference rates, from the OFR's Short-term Funding Monitor: [charts.repo_reference_rates] in chartbook.toml.

Reads the `ofr_repo` dataframe by its name, as chartbook.toml declares it.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

# pull_ofr_api_data.py saved the dates as the index
df = data.load("ofr_repo", format="pandas").reset_index()

chartbook.plotting.line(
    df,
    x="Date",
    y=["FNYR-BGCR-A", "FNYR-TGCR-A", "REPO-TRI_AR_OO-P"],
    labels={
        "FNYR-BGCR-A": "Broad General Collateral Rate",
        "FNYR-TGCR-A": "Tri-Party General Collateral Rate",
        "REPO-TRI_AR_OO-P": "Tri-party overnight average rate",
    },
    title="Repo Reference Rates",
    y_title="Percent",
    source="Office of Financial Research",
).save(chart_id="repo_reference_rates", output_dir=OUTPUT_DIR)
