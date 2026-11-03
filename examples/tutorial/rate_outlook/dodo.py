"""Build the pipeline: derive the spread from the pinned inputs, fit the model, chart, render."""

from chartbook import assets, data, models

DOIT_CONFIG = {"backend": "sqlite3", "dep_file": "./.doit-db.sqlite"}


def task_spread():
    return {
        "actions": ["python src/build_spread.py"],
        # The pins: a moved pin is new input
        "file_dep": ["src/build_spread.py", "chartbook.lock"],
        "targets": [data.path("term_spread")],
    }


def task_model():
    return {
        "actions": ["python src/train_model.py"],
        "file_dep": ["src/train_model.py", data.path("term_spread")],
        "targets": [models.path("spread_ar1"), "_output/spread_ar1_metrics.json"],
    }


def task_charts():
    return {
        "actions": ["python src/charts.py"],
        "file_dep": ["src/charts.py", data.path("term_spread")],
        "targets": [assets.path("chart/term_spread")],
    }


def task_docs():
    return {"actions": ["chartbook docs build -f"], "task_dep": ["spread", "model", "charts"]}
