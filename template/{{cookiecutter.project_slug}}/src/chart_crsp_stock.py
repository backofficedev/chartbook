"""What a dollar in the CRSP value-weighted index grew to: [charts.crsp_value_weighted] in chartbook.toml.

Reads the `crsp_index` dataframe by its name, as chartbook.toml declares it.
"""

import chartbook
from chartbook import data

from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")

df = data.load("crsp_index", format="pandas").sort_values("caldt")
df["growth_of_a_dollar"] = (1 + df["vwretd"]).cumprod()

chartbook.plotting.line(
    df,
    x="caldt",
    y="growth_of_a_dollar",
    labels={"growth_of_a_dollar": "Value-weighted, with dividends"},
    title="Growth of $1 in the CRSP Value-Weighted Index",
    y_title="Dollars",
    source="CRSP, through WRDS",
).save(chart_id="crsp_value_weighted", output_dir=OUTPUT_DIR)
