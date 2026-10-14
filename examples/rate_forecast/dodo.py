"""Build the rate_forecast example. This file uses the `doit` Python package.

Three steps: pin what this pipeline reads from yield_curve, train the model
on the pinned copy, and build the documentation site.
"""

from chartbook import assets

DOIT_CONFIG = {
    "backend": "sqlite3",
    "dep_file": "./.doit-db.sqlite",
    "verbosity": 2,
}

LOCK_FILE = "./chartbook.lock"
METRICS_FILE = "./_output/rate_forecast_metrics.json"


def task_pin():
    """Freeze what this pipeline reads from the pipelines it depends on"""
    return {
        # It has no dependencies of its own, so doit runs it every time. That
        # is cheap and safe: `pin` never moves a pin. It pins what has none,
        # and puts back in the store what the store has lost. To pick up
        # newer data from yield_curve, run `chartbook update` by hand.
        "actions": ["chartbook pin"],
        "targets": [LOCK_FILE],
    }


def task_train_rate_forecast():
    """Train the example model on yield_curve's pinned data"""
    return {
        "actions": ["python ./src/train_rate_forecast.py"],
        # The lockfile is the dependency, not the data: the model is trained
        # again exactly when a pin moves, and not because yield_curve rebuilt
        "file_dep": ["./src/train_rate_forecast.py", LOCK_FILE],
        "targets": [assets.path("model/rate_forecast"), METRICS_FILE],
        "clean": True,
    }


def task_compile_sphinx_docs():
    """Compile the documentation site"""
    return {
        "actions": ["chartbook build -f"],
        "targets": ["./docs/index.html"],
        "file_dep": [
            "./README.md",
            "./chartbook.toml",
            LOCK_FILE,
            assets.path("model/rate_forecast"),
            METRICS_FILE,
        ],
        "clean": True,
    }
