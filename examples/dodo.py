"""Root dodo.py - Orchestrates builds across all pipelines and generates catalog docs for GitHub Pages.

Every task here runs another build: a pipeline's own doit, or a chartbook
command. doit cannot see into those, so each task declares what that build
reads and makes, and a second run with nothing changed runs nothing:

- its sources are the files git tracks, or does not ignore, in the folder
  (`git_files`): what is built there (_data/, _output/, docs/) is ignored,
  and so is not a source;
- what it makes is the pipeline's site and every asset its chartbook.toml
  declares with a path (`made_by`); a missing one brings the build back;
- what is not a file and still decides what a build does is compared with
  what it was after the task last ran (`unchanged`): the commit, the store
  and the snapshots in it, and the lockfiles that say what a pipeline reads.

The project's own dodo.py runs this whole build as one task, and takes what
it reads and makes from `sources`, `outputs` and `context` here.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

from chartbook.config import get_store_url, shown_store_url
from chartbook.resolve import declared_files

DOIT_CONFIG = {
    "backend": "sqlite3",
    "dep_file": "./.doit-db.sqlite",
    "num_process": 4,  # Run up to 4 tasks in parallel
}

BASE_DIR = Path(__file__).parent
CATALOG_DIR = BASE_DIR / "catalog"
CATALOG_DOCS = CATALOG_DIR / "docs"
ROOT_DOCS = BASE_DIR / "docs"
YIELD_CURVE_DIR = BASE_DIR / "yield_curve"
FRED_CHARTS_DIR = BASE_DIR / "fred_charts"
RATE_FORECAST_DIR = BASE_DIR / "rate_forecast"
PIPELINE_DIRS = [YIELD_CURVE_DIR, FRED_CHARTS_DIR, RATE_FORECAST_DIR]


def git_files(*folders):
    """The files git tracks, or does not ignore, under *folders*: a build's sources, for file_dep.

    A file someone is working on and has not committed counts; what the
    build itself makes, which git ignores, does not.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(BASE_DIR), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
             *(str(folder) for folder in folders)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError(
            f"git could not list the files under {BASE_DIR}. The examples are built in a checkout of the "
            f"repository, with git installed."
        ) from e
    # A file deleted and not yet committed is still listed, and is no source
    return sorted(path for path in (BASE_DIR / name for name in listed.split("\0") if name) if path.is_file())


def made_by(pipeline_dir):
    """What a pipeline's build makes: its site, and every asset its chartbook.toml declares with a path."""
    return [pipeline_dir / "docs" / "index.html", *(absolute for _, _, absolute in declared_files(pipeline_dir))]


def unchanged(name, fingerprint):
    """An uptodate check on what is not a file.

    *fingerprint()* is compared with what it gave after the task last ran,
    and the task runs when they differ. It is taken when the task is looked
    at, and again after the task has run, so that what the task itself
    changes (the lockfile its build writes, the snapshot it makes) is what
    the next run is compared with. Nothing is saved after a failure, so the
    task runs again.
    """

    def check(task, values):
        task.value_savers.append(lambda: {name: fingerprint()})
        return values.get(name) == fingerprint()

    return check


def commit():
    """The commit the examples are at; empty in a repository with no commit yet."""
    result = subprocess.run(["git", "-C", str(BASE_DIR), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def store_and_snapshots():
    """The store, and which snapshots are in it: one made or removed there, by anyone, changes this.

    Read from the store when a task is looked at, not when this file is loaded.
    """
    from chartbook.store import default_store

    listing = "\n".join(str(path) for path in default_store().all_snapshot_files())
    return shown_store_url(get_store_url()) + "\n" + hashlib.sha256(listing.encode("utf-8")).hexdigest()


def lockfiles():
    """What each pipeline has pinned, as its lockfile says.

    A lockfile is written by the pipeline's own build (so it is no
    file_dep: there is none before the first build) and moved by `chartbook
    update`, which rebuilds nothing.
    """
    digests = []
    for pipeline_dir in PIPELINE_DIRS:
        lock = pipeline_dir / "chartbook.lock"
        digests.append(hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else "")
    return "\n".join(digests)


# What a snapshot is of, and what the catalog and the check read, that is not a file
AT_COMMIT = unchanged("commit", commit)
IN_STORE = unchanged("store", store_and_snapshots)
PINNED = unchanged("lockfiles", lockfiles)


def context():
    """The uptodate checks on everything that is not a file and still decides what this build does."""
    return [AT_COMMIT, IN_STORE, PINNED]


def sources():
    """Every source of the examples' build: the files git tracks, or does not ignore, under examples/."""
    return git_files(BASE_DIR)


def outputs():
    """Everything the examples' build makes: each pipeline's site and declared assets, the catalog's site, and its copy for GitHub Pages."""
    return [
        *(made for pipeline_dir in PIPELINE_DIRS for made in made_by(pipeline_dir)),
        CATALOG_DOCS / "index.html",
        ROOT_DOCS / "index.html",
        ROOT_DOCS / ".nojekyll",
    ]


def catalog_inputs():
    """What the catalog's site and its check are made from: the catalog's own files, and every pipeline's sources and build."""
    return [
        *git_files(CATALOG_DIR, *PIPELINE_DIRS),
        *(made for pipeline_dir in PIPELINE_DIRS for made in made_by(pipeline_dir)),
    ]


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
    return {
        "actions": [f"doit -f {YIELD_CURVE_DIR / 'dodo.py'}"],
        "file_dep": git_files(YIELD_CURVE_DIR),
        "targets": made_by(YIELD_CURVE_DIR),
        "verbosity": 2,
    }


def task_build_fred_charts():
    """Run doit in fred_charts directory"""
    return {
        "actions": [f"doit -f {FRED_CHARTS_DIR / 'dodo.py'}"],
        "file_dep": git_files(FRED_CHARTS_DIR),
        "targets": made_by(FRED_CHARTS_DIR),
        "verbosity": 2,
    }


def task_snapshot_yield_curve():
    """Declare yield_curve's build ready for the pipelines that depend on it"""
    return {
        # A snapshot is what rate_forecast pins: it never reads yield_curve's
        # folder. It needs everything in that folder to be committed. It is
        # of what yield_curve built, and its documents, at the commit it is
        # at, in the store: with none of those changed there is nothing to
        # declare, and chartbook would make no new snapshot either.
        "actions": [f"chartbook snapshot --project-dir {YIELD_CURVE_DIR}"],
        "file_dep": [*git_files(YIELD_CURVE_DIR), *made_by(YIELD_CURVE_DIR)],
        "uptodate": [AT_COMMIT, IN_STORE],
        "task_dep": ["build_yield_curve"],
        "verbosity": 2,
    }


def task_build_rate_forecast():
    """Run doit in rate_forecast directory, which reads yield_curve's data"""
    return {
        # Its own first task is `chartbook pin`, which pins yield_curve's
        # snapshot the first time and leaves the pin alone after that; a pin
        # `chartbook update` moved is what its model is trained on next
        "actions": [f"doit -f {RATE_FORECAST_DIR / 'dodo.py'}"],
        "file_dep": [*git_files(RATE_FORECAST_DIR), YIELD_CURVE_DIR / "docs" / "index.html"],
        "targets": [*made_by(RATE_FORECAST_DIR), RATE_FORECAST_DIR / "chartbook.lock"],
        "uptodate": [PINNED],
        "task_dep": ["snapshot_yield_curve"],
        "verbosity": 2,
    }


def task_snapshot_fred_charts():
    """Publish the FRED pipeline for the store catalog."""
    return {
        "actions": [f"chartbook snapshot --project-dir {FRED_CHARTS_DIR}"],
        "file_dep": [*git_files(FRED_CHARTS_DIR), *made_by(FRED_CHARTS_DIR)],
        "uptodate": [AT_COMMIT, IN_STORE],
        "task_dep": ["build_fred_charts"],
        "verbosity": 2,
    }


def task_snapshot_rate_forecast():
    """Publish the consumer after its upstream pin and model are built."""
    return {
        "actions": [f"chartbook snapshot --project-dir {RATE_FORECAST_DIR}"],
        "file_dep": [*git_files(RATE_FORECAST_DIR), *made_by(RATE_FORECAST_DIR)],
        "uptodate": [AT_COMMIT, IN_STORE],
        "task_dep": ["build_rate_forecast"],
        "verbosity": 2,
    }


def task_generate_catalog():
    """Render the catalog's site"""
    return {
        # The catalog shows only published snapshots in its stores.
        "actions": [f"cd {CATALOG_DIR} && chartbook docs build -f"],
        "file_dep": catalog_inputs(),
        "uptodate": context(),
        "targets": [CATALOG_DOCS / "index.html"],
        "task_dep": ["snapshot_yield_curve", "snapshot_fred_charts", "snapshot_rate_forecast"],
        "verbosity": 2,
    }


def task_copy_docs():
    """Copy catalog/docs to ./docs and add .nojekyll"""
    return {
        "actions": [copy_docs_action],
        "file_dep": [CATALOG_DOCS / "index.html"],
        "targets": [ROOT_DOCS / "index.html", ROOT_DOCS / ".nojekyll"],
        "task_dep": ["generate_catalog"],
        "verbosity": 2,
    }


def task_check():
    """Gate the catalog: required metadata, declared paths, license dates"""
    return {
        # Checking the catalog checks every member pipeline against its
        # policy. Like the tests, it is run again when what it checks has
        # changed, not on every build.
        "actions": [f"chartbook check --project-dir {folder}" for folder in PIPELINE_DIRS],
        "file_dep": catalog_inputs(),
        "uptodate": context(),
        "task_dep": ["build_yield_curve", "build_fred_charts", "build_rate_forecast"],
        "verbosity": 2,
    }
