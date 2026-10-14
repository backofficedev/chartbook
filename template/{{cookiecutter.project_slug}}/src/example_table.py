"""
At some point, I should probably refactor this into a set of
helper functions to help convert Pandas to LaTeX tables.


"""

from pathlib import Path

import pandas as pd

from settings import config

DATA_DIR = Path(config("DATA_DIR"))
OUTPUT_DIR = Path(config("OUTPUT_DIR"))

{% if cookiecutter.include_fred -%}
import pull_fred

# Keep only the series used below before dropping missing values. Dropping
# rows with a missing value in any FRED series would leave only a few dates.
df_level = pull_fred.load_fred(data_dir=DATA_DIR)[["CPIAUCNS", "GDPC1"]].dropna()
{% else -%}
import numpy as np

# FRED was not selected for this project, so simulate quarterly levels to stand
# in for the CPI and real GDP series that pull_fred.py would otherwise load.
rng = np.random.default_rng(100)
dates = pd.date_range("1947-01-01", "2023-10-01", freq="QS", name="DATE")
growth = rng.normal(loc=0.008, scale=0.01, size=(len(dates), 2))
df_level = pd.DataFrame(
    100 * np.exp(growth.cumsum(axis=0)), index=dates, columns=["CPIAUCNS", "GDPC1"]
)
{% endif %}
df_quarterly = 100 * df_level.pct_change()
# df_quarterly.plot()

# Select only the values that occur in July
_df = df_level[df_level.index.month == 7]
df_annual = 100 * _df.pct_change()
# df_annual.plot()

df_quarterly.describe()
df_annual.describe()


columns_for_summary_stats = [
    "CPIAUCNS",
    "GDPC1",
]

# This maps the column names to their LaTeX descriptions
column_names_map = {
    "CPIAUCNS": "Inflation",
    "GDPC1": "Real GDP",
}

escape_coverter = {"25%": "25\\%", "50%": "50\\%", "75%": "75\\%"}

# The first year has no prior year to compare against
df_annual = df_annual[columns_for_summary_stats].dropna()
first_year = df_annual.index.year.min()
last_year = df_annual.index.year.max()

## Suppress scientific notation and limit to 3 decimal places
# Sets display, but doesn't affect formatting to LaTeX
pd.set_option("display.float_format", lambda x: "%.2f" % x)
# Sets format for printing to LaTeX
float_format_func = lambda x: "{:.2f}".format(x)

# Pooled summary stats
describe_all = (
    df_annual[columns_for_summary_stats]
    .describe()
    .T.rename(index=column_names_map, columns=escape_coverter)
)
describe_all["count"] = describe_all["count"].astype(int)
describe_all.columns.name = f"Full Sample: {first_year} - {last_year}"
latex_table_string_all = describe_all.to_latex(
    escape=False, float_format=float_format_func
)

describe1 = (
    df_annual.loc[:"1989", columns_for_summary_stats]
    .describe()
    .T.rename(index=column_names_map, columns=escape_coverter)
)
describe1["count"] = describe1["count"].astype(int)
describe1.columns.name = f"Subsample: {first_year} - 1989"
latex_table_string1 = describe1.to_latex(escape=False, float_format=float_format_func)

describe2 = (
    df_annual.loc["1990":, columns_for_summary_stats]
    .describe()
    .T.rename(index=column_names_map, columns=escape_coverter)
)
describe2["count"] = describe2["count"].astype(int)
describe2.columns.name = f"Subsample: 1990 - {last_year}"
latex_table_string2 = describe2.to_latex(escape=False, float_format=float_format_func)

latex_table_string_split = [
    *latex_table_string_all.split("\n")[
        0:-3
    ],  # Skip the \end{tabular} and \bottomrule lines
    "\\midrule",
    *latex_table_string1.split("\n")[2:-3],  # Skip the \begin and \end lines
    "\\midrule",
    *latex_table_string2.split("\n")[2:],  # Skip the \begin{tabular} and \toprule lines
]
latex_table_string = "\n".join(latex_table_string_split)
# print(latex_table_string)
path = OUTPUT_DIR / "example_table.tex"
with open(path, "w") as text_file:
    text_file.write(latex_table_string)
