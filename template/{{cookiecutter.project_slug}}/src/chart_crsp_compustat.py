"""Cumulative returns of the Fama-French factors: [charts.fama_french_factors] in chartbook.toml.

Reads the `fama_french_factors` dataframe by its name, as chartbook.toml declares it.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

df = data.load("fama_french_factors", format="pandas").sort_values("date")
factors = {"mktrf": "Market less the risk-free rate", "smb": "Small minus big", "hml": "High minus low"}
for factor in factors:
    df[factor] = (1 + df[factor]).cumprod()

chartbook.plotting.line(
    df,
    x="date",
    y=list(factors),
    labels=factors,
    title="Growth of $1 in the Fama-French Factors",
    y_title="Dollars",
    source="Kenneth French's data library, through WRDS",
).save(chart_id="fama_french_factors", output_dir=OUTPUT_DIR)
