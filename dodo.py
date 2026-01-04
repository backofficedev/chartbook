"""PyDoit build automation for ChartBook documentation.

Run with:
    doit              # Run all tasks
    doit list         # List available tasks
    doit run_notebooks    # Run specific task
"""

import shutil
from pathlib import Path

from colorama import Fore, Style, init
from doit.reporter import ConsoleReporter

# Project paths
PROJECT_ROOT = Path(__file__).parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "_build"
DOCS_SRC = PROJECT_ROOT / "docs_src"
DOCS_OUTPUT = PROJECT_ROOT / "docs"

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
        "docs_path": DOCS_SRC / "user-guide" / "gallery.ipynb",
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

    return {
        "actions": [
            f"sphinx-build -b html {DOCS_SRC} {DOCS_OUTPUT}",
        ],
        "file_dep": notebook_scripts,
        "targets": sphinx_targets,
        "task_dep": ["run_notebooks"],
        "clean": True,
        "verbosity": 2,
    }


def task_build_examples():
    """Build all examples documentation."""
    examples_dodo = PROJECT_ROOT / "examples" / "dodo.py"
    return {
        "actions": [f"doit -f {examples_dodo}"],
        "task_dep": ["sphinx"],
        "verbosity": 2,
    }


def task_hatch_build():
    """Build the package with hatch for publishing."""
    return {
        "actions": ["hatch build"],
        "task_dep": ["build_examples"],
        "verbosity": 2,
    }


def task_build():
    """Meta-task: Full documentation build pipeline."""
    return {
        "actions": None,
        "task_dep": ["hatch_build"],
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
