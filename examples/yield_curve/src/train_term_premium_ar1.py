"""Train a small model, to show how ChartBook treats one.

The model is as simple as a model gets: tomorrow's 10-year minus 2-year
spread is predicted from today's, by a straight line fitted with NumPy. It
is an example of the mechanics, not a forecast to act on.

ChartBook does not train, load or run a model. This script does the
training; chartbook.toml declares where the result is, what it was trained
on and where its scores are:

    [models.term_premium_ar1]
    path = "./_models/term_premium_ar1.json"
    trained_on = ["term_premium"]
    metrics_path = "./_output/term_premium_ar1_metrics.json"
"""

import json

import numpy as np
import pandas as pd

from chartbook import data, models
from chartbook.env import get_project_root

OUTPUT_DIR = get_project_root() / "_output"
COLUMN = "spread_10y_2y"

spread = pd.read_parquet(data.path("term_premium"))[COLUMN].dropna()
split = int(len(spread) * 0.8)
train, test = spread.iloc[:split], spread.iloc[split:]

# y[t] = intercept + slope * y[t-1]
slope, intercept = np.polyfit(train.values[:-1], train.values[1:], 1)
predicted = intercept + slope * test.values[:-1]
errors = test.values[1:] - predicted

# Ask the manifest where the model belongs, as for any other asset
model_path = models.path("term_premium_ar1")
model_path.parent.mkdir(parents=True, exist_ok=True)
model_path.write_text(
    json.dumps(
        {
            "column": COLUMN,
            "intercept": float(intercept),
            "slope": float(slope),
            "trained_through": str(pd.Timestamp(train.index[-1]).date()),
        },
        indent=2,
    )
    + "\n"
)

# Scores go in a file of their own: one flat JSON object
metrics = {
    "rmse": float(np.sqrt(np.mean(errors**2))),
    "mae": float(np.mean(np.abs(errors))),
    "n_train": int(len(train)),
    "n_test": int(len(test)),
}
metrics_path = OUTPUT_DIR / "term_premium_ar1_metrics.json"
metrics_path.parent.mkdir(parents=True, exist_ok=True)
metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")

print(f"Model saved to: {model_path}")
print(f"Scores saved to: {metrics_path}")
