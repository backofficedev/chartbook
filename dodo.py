"""PyDoit build automation for ChartBook: the docs, the examples, the package, the tests.

Run with:
    uv run doit               # everything: notebooks, docs, examples, package, the test matrix
    uv run doit build_package # the same without the tests
    uv run doit test          # the suite on the default Python, once
    uv run doit list          # every task

`uv run` syncs the environment from uv.lock and puts its tools first on the
path, so the nested doit, sphinx-build and hatch below are the project's own.
Publishing is not a task here: `uv publish`, by hand, after the tag.

A second run with nothing changed runs nothing. A task's sources are the
files git tracks, or does not ignore, where it reads (`git_files`): what a
build leaves behind (apidocs/, __pycache__/, the examples' _data/) is
ignored, and so is not a source. `build_examples` and `build_package` run
another build (the examples' own doit, hatchling), which doit cannot see
into, so each declares what that build reads and makes, and what is not a
file and still goes in: the commit, and the store the examples' snapshots
go to, as a `config_changed`.
"""

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from colorama import Fore, Style, init
from doit.reporter import ConsoleReporter
from doit.tools import config_changed

from chartbook.config import get_store_url, shown_store_url
from chartbook.manifest import catalog_member_dirs
from chartbook.resolve import declared_files

# Project paths
PROJECT_ROOT = Path(__file__).parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "_build"
DOCS_SRC = PROJECT_ROOT / "docs_src"
DOCS_OUTPUT = PROJECT_ROOT / "docs"
SRC_DIR = PROJECT_ROOT / "src"
TEST_RESULTS_DIR = OUTPUT_DIR / "test-results"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
EXAMPLES_CATALOG = EXAMPLES_DIR / "catalog"

# Ensure build directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def git_files(*paths):
    """The files git tracks, or does not ignore, under *paths*: a task's sources, for file_dep.

    A file someone is working on and has not committed counts; what a build
    makes, which git ignores, does not.
    """
    listed = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
         *(str(path) for path in paths)],
        capture_output=True, text=True, check=True,
    ).stdout
    # A file deleted and not yet committed is still listed, and is no source
    return sorted(path for path in (PROJECT_ROOT / name for name in listed.split("\0") if name) if path.is_file())


def git_head():
    """The commit the checkout is at; empty where git cannot say (the builds that need it then fail on their own)."""
    result = subprocess.run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def made_by(pipeline_dir):
    """What an example pipeline's build makes: its site, and every asset its chartbook.toml declares with a path."""
    return [pipeline_dir / "docs" / "index.html", *(absolute for _, _, absolute in declared_files(pipeline_dir))]


# Custom reporter: Print PyDoit Text in Green
class GreenReporter(ConsoleReporter):
    def write(self, stuff, **kwargs):
        doit_mark = stuff.split(" ")[0].ljust(2)
        task = " ".join(stuff.split(" ")[1:]).strip() + "\n"
        output = Fore.GREEN + doit_mark + " chartbook: " + task + Style.RESET_ALL
        self.outstream.write(output)


DOIT_CONFIG = {
    "reporter": GreenReporter,
    "backend": "sqlite3",
    "dep_file": "./.doit-db.sqlite",
    # `build` pulls in the notebooks, the docs, the examples and the package;
    # `test_all` is the matrix, which includes the default Python, so `test`
    # is not run as well (it is for `uv run doit test`, the quick check)
    "default_tasks": ["build", "test_all"],
}

init(autoreset=True)


# fmt: off
## Helper functions for automatic execution of Jupyter notebooks
def jupyter_execute_notebook(notebook_path):
    return f"jupyter nbconvert --execute --to notebook --ClearMetadataPreprocessor.enabled=True --inplace {notebook_path}"

def jupyter_to_html(notebook_path, output_dir=OUTPUT_DIR):
    return f"jupyter nbconvert --to html --output-dir={output_dir} {notebook_path}"

def jupyter_to_md(notebook_path, output_dir=OUTPUT_DIR):
    """Requires jupytext"""
    return f"jupytext --to markdown --output-dir={output_dir} {notebook_path}"

def jupyter_clear_output(notebook_path):
    """Clear the output of a notebook"""
    return f"jupyter nbconvert --ClearOutputPreprocessor.enabled=True --ClearMetadataPreprocessor.enabled=True --inplace {notebook_path}"
# fmt: on


def copy_file(origin_path, destination_path, mkdir=True):
    """Create a Python action for copying a file."""

    def _copy_file():
        origin = Path(origin_path)
        dest = Path(destination_path)
        if mkdir:
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, dest)

    return _copy_file


def copy_llms_file(origin_path, destination_path):
    """Create a Python action that copies an llms file into the site, with its links made the site's.

    The files under llm/ link the docs by their source paths from the
    repository's root (`docs_src/guide/plotting.md`), which is right for the
    copy at the root and for an agent reading the repository; in the built
    site each is a page, `guide/plotting.html`.
    """
    import re

    def _copy():
        text = Path(origin_path).read_text(encoding="utf-8")
        text = re.sub(r"\]\(docs_src/([^)#\s]+)\.(?:md|ipynb)(#[^)\s]*)?\)", r"](\1.html\2)", text)
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")

    return _copy


def mv(from_path, to_path):
    """Move a file to a folder"""
    from_path = Path(from_path)
    to_path = Path(to_path)
    to_path.mkdir(parents=True, exist_ok=True)
    return f"mv {from_path} {to_path}"


# Notebook tasks configuration
notebook_tasks = {
    "plotting_gallery": {
        "path": SCRIPTS_DIR / "plotting_gallery_ipynb.py",
        "docs_path": DOCS_SRC / "guide" / "gallery.ipynb",
        "file_dep": [],
        "targets": [],
    },
}


# fmt: off
def task_run_notebooks():
    """Convert, execute, and prepare all notebooks for documentation.

    Notebooks are pre-executed here, then copied to docs_src/ where
    myst_nb renders them with nb_execution_mode='off'.
    """
    for notebook_name, config in notebook_tasks.items():
        pyfile_path = Path(config["path"])
        notebook_path = OUTPUT_DIR / f"{notebook_name}.ipynb"
        docs_notebook_path = Path(config["docs_path"])

        yield {
            "name": notebook_name,
            "actions": [
                f"jupytext --to notebook --output {notebook_path} {pyfile_path}",
                jupyter_execute_notebook(notebook_path),
                copy_file(notebook_path, docs_notebook_path),
                mv(notebook_path, OUTPUT_DIR / "_notebook_build"),
            ],
            "file_dep": [
                pyfile_path,
                *config["file_dep"],
            ],
            "targets": [
                docs_notebook_path,
                *config["targets"],
            ],
            "clean": True,
            "verbosity": 2,
        }
# fmt: on


sphinx_targets = [
    DOCS_OUTPUT / "index.html",
]


def task_sphinx():
    """Build Sphinx documentation."""
    notebook_scripts = [Path(config["path"]) for config in notebook_tasks.values()]
    llms_files = [PROJECT_ROOT / "llm" / "llms.txt", PROJECT_ROOT / "llm" / "llms-full.txt"]

    return {
        "actions": [
            f"sphinx-build -b html {DOCS_SRC} {DOCS_OUTPUT}",
            copy_llms_file(llms_files[0], DOCS_OUTPUT / "llms.txt"),
            copy_llms_file(llms_files[1], DOCS_OUTPUT / "llms-full.txt"),
        ],
        # Not everything under docs_src/: the build writes apidocs/ there,
        # and Python its __pycache__/, which git ignores
        "file_dep": git_files(SRC_DIR, DOCS_SRC, *notebook_scripts, *llms_files),
        "targets": sphinx_targets,
        "task_dep": ["run_notebooks"],
        "clean": True,
        "verbosity": 2,
    }


def task_build_examples():
    """Build all examples documentation."""
    # The examples are the pipelines of their catalog (examples/dodo.py builds each)
    pipelines = catalog_member_dirs(EXAMPLES_CATALOG).values()
    return {
        # This interpreter's doit, never another on the path
        "actions": [f"{sys.executable} -m doit -f {EXAMPLES_DIR / 'dodo.py'}"],
        # The examples' own doit knows each step's inputs; this task knows
        # the whole build's, so that the examples' doit is run when they
        # change and not otherwise: the examples' sources, chartbook itself
        # (it renders their sites), and the commit and the store (a snapshot
        # is made per commit, and the catalog shows every snapshot in the
        # store). An intermediate the examples' doit alone knows of, removed
        # by hand, is brought back by running that doit: `uv run doit -f
        # examples/dodo.py`.
        "file_dep": git_files(EXAMPLES_DIR, SRC_DIR),
        "targets": [
            EXAMPLES_DIR / "docs" / "index.html",
            EXAMPLES_CATALOG / "docs" / "index.html",
            *(made for pipeline_dir in pipelines for made in made_by(pipeline_dir)),
        ],
        "uptodate": [config_changed({"commit": git_head(), "store": shown_store_url(get_store_url())})],
        "task_dep": ["sphinx"],
        "verbosity": 2,
    }


def task_build_package():
    """Build the wheel and the sdist into dist/, for publishing.

    `uv build` calls the hatchling backend, whose hook records the commit the
    template is at (`hatch_build.py`) and stops where it cannot: build from a
    clean checkout, with git at hand. Publishing is `uv publish`, by hand.
    """
    about = (SRC_DIR / "chartbook" / "__about__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__\s*=\s*"([^"]+)"', about).group(1)
    return {
        "actions": ["uv build"],
        # What goes into the package (see pyproject.toml and hatch_build.py),
        # and the commit, which the package records
        "file_dep": git_files(
            SRC_DIR,
            PROJECT_ROOT / "template",
            PROJECT_ROOT / "pyproject.toml",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "LICENSE.md",
            PROJECT_ROOT / "hatch_build.py",
        ),
        "targets": [
            PROJECT_ROOT / "dist" / f"chartbook-{version}.tar.gz",
            PROJECT_ROOT / "dist" / f"chartbook-{version}-py3-none-any.whl",
        ],
        "uptodate": [config_changed({"commit": git_head()})],
        "task_dep": ["build_examples"],
        "verbosity": 2,
    }


def task_build():
    """Meta-task: notebooks, docs, examples and the package."""
    return {
        "actions": None,
        "task_dep": ["build_package"],
    }


def task_clean_notebooks():
    """Clean generated notebook files. Run with: doit clean_notebooks"""
    return {
        "actions": [
            f"rm -rf {OUTPUT_DIR}/_notebook_build",
        ],
        "uptodate": [True],
        "verbosity": 2,
    }


def task_clean_all():
    """Clean all generated files. Run with: doit clean_all"""
    return {
        "actions": [
            f"rm -rf {OUTPUT_DIR}",
            f"rm -rf {DOCS_OUTPUT}",
        ],
        "uptodate": [True],
        "verbosity": 2,
    }


def _run_tests(hatch_cmd, junit_path):
    """Run tests via hatch, produce JUnit XML, fail if any tests fail."""

    def _action():
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        if junit_path.exists():
            junit_path.unlink()

        result = subprocess.run(
            f"{hatch_cmd} -- --junitxml={junit_path}",
            shell=True,
        )

        # If hatch/pytest exited non-zero, clean up target and fail
        if result.returncode != 0:
            if junit_path.exists():
                junit_path.unlink()
            raise RuntimeError(f"Tests failed (exit code {result.returncode})")

        # Double-check: parse XML for failures even if exit code was 0
        if junit_path.exists():
            tree = ET.parse(junit_path)
            root = tree.getroot()
            failures = int(root.attrib.get("failures", 0))
            errors = int(root.attrib.get("errors", 0))
            if failures > 0 or errors > 0:
                junit_path.unlink()
                raise RuntimeError(
                    f"Tests had {failures} failure(s) and {errors} error(s)"
                )

    return _action


def task_test():
    """Run tests on default Python version."""
    src_files = list(SRC_DIR.rglob("*.py"))
    test_files = list((PROJECT_ROOT / "tests").rglob("*.py"))
    junit_path = TEST_RESULTS_DIR / "junit.xml"
    return {
        "actions": [_run_tests(f"{sys.executable} -m hatch test -v", junit_path)],
        "file_dep": src_files + test_files + [PROJECT_ROOT / "pyproject.toml"],
        "targets": [junit_path],
        "clean": True,
        "verbosity": 2,
    }


def task_test_all():
    """Run tests on all Python versions and the Sphinx matrix (see pyproject)."""
    src_files = list(SRC_DIR.rglob("*.py"))
    test_files = list((PROJECT_ROOT / "tests").rglob("*.py"))
    junit_path = TEST_RESULTS_DIR / "junit-all.xml"
    return {
        "actions": [_run_tests(f"{sys.executable} -m hatch test --all -v", junit_path)],
        "file_dep": src_files + test_files + [PROJECT_ROOT / "pyproject.toml"],
        "targets": [junit_path],
        "clean": True,
        "verbosity": 2,
    }
