"""PyDoit build automation for ChartBook: the docs, the examples, the package, the tests.

Run with:
    uv run doit               # everything: notebooks, docs, examples, package, the test matrix
    uv run doit build_package # the same without the tests
    uv run doit test          # the suite on the default Python, once
    uv run doit list          # every task

`uv run` syncs the environment from uv.lock and puts its tools first on the
path, so the nested doit, sphinx-build and hatch below are the project's own.
Publishing is not a task here: `uv publish`, by hand, after the tag.
"""

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from colorama import Fore, Style, init
from doit.reporter import ConsoleReporter

# Project paths
PROJECT_ROOT = Path(__file__).parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "_build"
DOCS_SRC = PROJECT_ROOT / "docs_src"
DOCS_OUTPUT = PROJECT_ROOT / "docs"
SRC_DIR = PROJECT_ROOT / "src"
TEST_RESULTS_DIR = OUTPUT_DIR / "test-results"

# Ensure build directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
    src_files = list(SRC_DIR.rglob("*.py"))
    docs_src_files = list(DOCS_SRC.rglob("*"))
    docs_src_files = [f for f in docs_src_files if f.is_file()]

    return {
        "actions": [
            f"sphinx-build -b html {DOCS_SRC} {DOCS_OUTPUT}",
            copy_llms_file(PROJECT_ROOT / "llm" / "llms.txt", DOCS_OUTPUT / "llms.txt"),
            copy_llms_file(PROJECT_ROOT / "llm" / "llms-full.txt", DOCS_OUTPUT / "llms-full.txt"),
        ],
        "file_dep": notebook_scripts + src_files + docs_src_files
        + [PROJECT_ROOT / "llm" / "llms.txt", PROJECT_ROOT / "llm" / "llms-full.txt"],
        "targets": sphinx_targets,
        "task_dep": ["run_notebooks"],
        "clean": True,
        "verbosity": 2,
    }


def task_build_examples():
    """Build all examples documentation."""
    examples_dodo = PROJECT_ROOT / "examples" / "dodo.py"
    return {
        # This interpreter's doit, never another on the path
        "actions": [f"{sys.executable} -m doit -f {examples_dodo}"],
        "task_dep": ["sphinx"],
        "verbosity": 2,
    }


def task_build_package():
    """Build the wheel and the sdist into dist/, for publishing.

    `uv build` calls the hatchling backend, whose hook records the commit the
    template is at (`hatch_build.py`) and stops where it cannot: build from a
    clean checkout, with git at hand. Publishing is `uv publish`, by hand.
    """
    return {
        "actions": ["uv build"],
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
