from pathlib import Path

{% if cookiecutter.include_fred -%}
import pull_fred
{% else -%}
import numpy as np
import pandas as pd
{% endif -%}
from settings import config

DATA_DIR = Path(config("DATA_DIR"))
OUTPUT_DIR = Path(config("OUTPUT_DIR"))

import seaborn as sns
from matplotlib import pyplot as plt

sns.set()

{% if cookiecutter.include_fred -%}
df = pull_fred.load_fred(data_dir=DATA_DIR)
{% else -%}
# FRED was not selected for this project, so simulate quarterly levels to stand
# in for the CPI and real GDP series that pull_fred.py would otherwise load.
rng = np.random.default_rng(100)
dates = pd.date_range("1947-01-01", "2023-10-01", freq="QS", name="DATE")
growth = rng.normal(loc=0.008, scale=0.01, size=(len(dates), 2))
df = pd.DataFrame(
    100 * np.exp(growth.cumsum(axis=0)), index=dates, columns=["CPIAUCNS", "GDPC1"]
)
{% endif %}
(
    100
    * df[["CPIAUCNS", "GDPC1"]]
    .rename(columns={"CPIAUCNS": "Inflation", "GDPC1": "Real GDP"})
    .dropna()
    .pct_change(4)
).plot()
{% if cookiecutter.include_fred -%}
plt.title("Inflation and Real GDP, Seasonally Adjusted")
{% else -%}
plt.title("Simulated Inflation and Real GDP")
{% endif -%}
plt.ylabel("Percent change from 12-months prior")
filename = OUTPUT_DIR / "example_plot.png"
plt.savefig(filename)
