"""Fit next month's term spread on this month's, and score it on the months it did not see."""

import json

import numpy as np

from chartbook import data, models

spread = data.load("term_spread", format="pandas").set_index("date")["spread"]
split = int(len(spread) * 0.8)
train, test = spread.iloc[:split], spread.iloc[split:]

slope, intercept = np.polyfit(train.values[:-1], train.values[1:], 1)
errors = test.values[1:] - (intercept + slope * test.values[:-1])

model = {"intercept": float(intercept), "slope": float(slope), "trained_through": f"{train.index[-1]:%Y-%m}"}
models.path("spread_ar1").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")

metrics = {
    "rmse": round(float(np.sqrt(np.mean(errors**2))), 4),
    "mae": round(float(np.mean(np.abs(errors))), 4),
    "n_train": len(train),
    "n_test": len(test),
}
metrics_path = data.path("term_spread").parent.parent / "_output" / "spread_ar1_metrics.json"
metrics_path.parent.mkdir(parents=True, exist_ok=True)
metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
