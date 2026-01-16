from pathlib import Path

import pull_fred
from chartbook.env import get_project_root

BASE_DIR = get_project_root()
DATA_DIR = BASE_DIR / "_data"
OUTPUT_DIR = BASE_DIR / "_output"

import seaborn as sns
from matplotlib import pyplot as plt

sns.set()

df = pull_fred.load_fred(data_dir=DATA_DIR)

(
    100
    * df[["CPIAUCSL", "GDP"]]
    .rename(columns={"CPIAUCSL": "Inflation (CPI)", "GDP": "GDP"})
    .dropna()
    .pct_change(4)
).plot()
plt.title("Inflation and GDP, Seasonally Adjusted")
plt.ylabel("Percent change from 12-months prior")
filename = OUTPUT_DIR / "example_plot.png"
plt.savefig(filename)
