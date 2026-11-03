"""Build the pipeline: pull the series, chart them, render the site."""

from chartbook import assets, data

DOIT_CONFIG = {"backend": "sqlite3", "dep_file": "./.doit-db.sqlite"}


def task_pull():
    return {
        "actions": ["python src/pull_macro.py"],
        "file_dep": ["src/pull_macro.py"],
        "targets": [data.path("macro_series")],
    }


def task_charts():
    return {
        "actions": ["python src/charts.py"],
        "file_dep": ["src/charts.py", data.path("macro_series")],
        "targets": [assets.path("chart/unemployment_and_inflation"), assets.path("chart/payrolls")],
    }


def task_docs():
    return {"actions": ["chartbook docs build -f"], "task_dep": ["pull", "charts"]}
