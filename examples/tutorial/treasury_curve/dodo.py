"""Build the pipeline: pull the curve, chart it, render the site."""

from chartbook import assets, data

DOIT_CONFIG = {"backend": "sqlite3", "dep_file": "./.doit-db.sqlite"}


def task_pull():
    return {
        "actions": ["python src/pull_yields.py"],
        "file_dep": ["src/pull_yields.py"],
        "targets": [data.path("zero_coupon_yields")],
    }


def task_charts():
    return {
        "actions": ["python src/charts.py"],
        "file_dep": ["src/charts.py", data.path("zero_coupon_yields")],
        "targets": [assets.path("chart/yields"), assets.path("chart/curve_today")],
    }


def task_docs():
    return {"actions": ["chartbook docs build -f"], "task_dep": ["pull", "charts"]}
