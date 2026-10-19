"""Root dodo.py - Orchestrates builds across all pipelines and generates catalog docs for GitHub Pages."""

import shutil
from pathlib import Path

DOIT_CONFIG = {
    "backend": "sqlite3",
    "dep_file": "./.doit-db.sqlite",
    "num_process": 4,  # Run up to 4 tasks in parallel
}

BASE_DIR = Path(__file__).parent
CATALOG_DOCS = BASE_DIR / "catalog" / "docs"
ROOT_DOCS = BASE_DIR / "docs"


def copy_docs_action():
    """Copy catalog/docs to ./docs and add .nojekyll (module-level for pickling)"""
    # Remove existing docs if present
    if ROOT_DOCS.exists():
        shutil.rmtree(ROOT_DOCS)
    # Copy catalog/docs to root/docs
    shutil.copytree(CATALOG_DOCS, ROOT_DOCS)
    # Create .nojekyll file
    (ROOT_DOCS / ".nojekyll").touch()


def task_build_yield_curve():
    """Run doit in yield_curve directory"""
    yield_curve_dir = BASE_DIR / "yield_curve"
    return {
        "actions": [f"doit -f {yield_curve_dir / 'dodo.py'}"],
        "file_dep": [
            str(yield_curve_dir / "dodo.py"),
            str(yield_curve_dir / "chartbook.toml"),
        ],
        "targets": [str(yield_curve_dir / "docs" / "index.html")],
        "verbosity": 2,
    }


def task_build_fred_charts():
    """Run doit in fred_charts directory"""
    fred_charts_dir = BASE_DIR / "fred_charts"
    return {
        "actions": [f"doit -f {fred_charts_dir / 'dodo.py'}"],
        "file_dep": [
            str(fred_charts_dir / "dodo.py"),
            str(fred_charts_dir / "chartbook.toml"),
        ],
        "targets": [str(fred_charts_dir / "docs" / "index.html")],
        "verbosity": 2,
    }


def task_snapshot_yield_curve():
    """Declare yield_curve's build ready for the pipelines that depend on it"""
    yield_curve_dir = BASE_DIR / "yield_curve"
    return {
        # A snapshot is what rate_forecast pins: it never reads yield_curve's
        # folder. It needs everything in that folder to be committed. With
        # nothing new built, it makes no new snapshot.
        "actions": [f"chartbook snapshot --project-dir {yield_curve_dir}"],
        "task_dep": ["build_yield_curve"],
        "verbosity": 2,
    }


def task_build_rate_forecast():
    """Run doit in rate_forecast directory, which reads yield_curve's data"""
    rate_forecast_dir = BASE_DIR / "rate_forecast"
    yield_curve_dir = BASE_DIR / "yield_curve"
    return {
        # Its own first task is `chartbook pin`, which pins yield_curve's
        # snapshot the first time and leaves the pin alone after that
        "actions": [f"doit -f {rate_forecast_dir / 'dodo.py'}"],
        "file_dep": [
            str(rate_forecast_dir / "dodo.py"),
            str(rate_forecast_dir / "chartbook.toml"),
            str(yield_curve_dir / "docs" / "index.html"),
        ],
        "targets": [str(rate_forecast_dir / "docs" / "index.html")],
        "task_dep": ["snapshot_yield_curve"],
        "verbosity": 2,
    }


def task_generate_catalog():
    """Render the catalog's site"""
    catalog_dir = BASE_DIR / "catalog"
    yield_curve_dir = BASE_DIR / "yield_curve"
    fred_charts_dir = BASE_DIR / "fred_charts"
    rate_forecast_dir = BASE_DIR / "rate_forecast"
    return {
        "actions": [f"cd {catalog_dir} && chartbook docs generate -f"],
        "file_dep": [
            str(catalog_dir / "chartbook.toml"),
            str(yield_curve_dir / "docs" / "index.html"),
            str(fred_charts_dir / "docs" / "index.html"),
            str(rate_forecast_dir / "docs" / "index.html"),
        ],
        "targets": [str(catalog_dir / "docs" / "index.html")],
        "task_dep": ["build_yield_curve", "build_fred_charts", "build_rate_forecast"],
        "verbosity": 2,
    }


def task_copy_docs():
    """Copy catalog/docs to ./docs and add .nojekyll"""
    catalog_dir = BASE_DIR / "catalog"
    return {
        "actions": [copy_docs_action],
        "file_dep": [str(catalog_dir / "docs" / "index.html")],
        "targets": [str(ROOT_DOCS / "index.html"), str(ROOT_DOCS / ".nojekyll")],
        "task_dep": ["generate_catalog"],
        "verbosity": 2,
    }


def task_check():
    """Gate the catalog: required metadata, declared paths, license dates"""
    catalog_dir = BASE_DIR / "catalog"
    return {
        # Checking the catalog checks every member pipeline against its policy
        "actions": [f"chartbook check --project-dir {catalog_dir}"],
        "task_dep": ["build_yield_curve", "build_fred_charts", "build_rate_forecast"],
        "verbosity": 2,
    }
