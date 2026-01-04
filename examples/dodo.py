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


def task_generate_catalog():
    """Run chartbook build in catalog directory"""
    catalog_dir = BASE_DIR / "catalog"
    yield_curve_dir = BASE_DIR / "yield_curve"
    fred_charts_dir = BASE_DIR / "fred_charts"
    return {
        "actions": [f"cd {catalog_dir} && chartbook build -f"],
        "file_dep": [
            str(catalog_dir / "chartbook.toml"),
            str(yield_curve_dir / "docs" / "index.html"),
            str(fred_charts_dir / "docs" / "index.html"),
        ],
        "targets": [str(catalog_dir / "docs" / "index.html")],
        "task_dep": ["build_yield_curve", "build_fred_charts"],
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
