"""Train a small model on another pipeline's data.

The data is the Federal Reserve's zero-coupon yield curve, which the
yield_curve pipeline pulls and declares as its dataframe `fed_yield_curve`.
This pipeline does not pull it again, and does not reach into
../yield_curve/_data. It says in chartbook.toml that it depends on that
pipeline:

    [dependencies]
    "backofficedev/yield_curve" = { path = "../yield_curve" }

and asks for the dataframe by name. What comes back is the copy that
`chartbook pin` froze, so this script reads the same bytes on every run
until `chartbook update` moves the pin, whatever yield_curve does meanwhile.

The model itself is as simple as a model gets: tomorrow's 10-year yield is
predicted from today's by a straight line fitted with NumPy. It is an
example of the mechanics, not a forecast to act on.
"""

import json
from pathlib import Path

import numpy as np

from chartbook import data, models

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "_output"
COLUMN = "SVENY10"  # the 10-year zero-coupon yield

# "pipeline:dataframe" is another pipeline's dataframe, as pinned
curve = data.load("yield_curve:fed_yield_curve", format="pandas")
if "Date" in curve.columns:  # pandas reads the date back as the index
    curve = curve.set_index("Date")
rate = curve[COLUMN].dropna().sort_index()
split = int(len(rate) * 0.8)
train, test = rate.iloc[:split], rate.iloc[split:]

# y[t] = intercept + slope * y[t-1]
slope, intercept = np.polyfit(train.values[:-1], train.values[1:], 1)
predicted = intercept + slope * test.values[:-1]
errors = test.values[1:] - predicted

# A model of this pipeline's own: ask the manifest where it belongs
model_path = models.path("rate_forecast")
model_path.parent.mkdir(parents=True, exist_ok=True)
model_path.write_text(
    json.dumps(
        {
            "column": COLUMN,
            "intercept": float(intercept),
            "slope": float(slope),
            "trained_through": str(train.index[-1].date()),
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
metrics_path = OUTPUT_DIR / "rate_forecast_metrics.json"
metrics_path.parent.mkdir(parents=True, exist_ok=True)
metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")

print(f"Trained on: {data.path('yield_curve:fed_yield_curve')}")
print(f"Model saved to: {model_path}")
print(f"Scores saved to: {metrics_path}")
