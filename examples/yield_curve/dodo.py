"""Run or update the project. This file uses the `doit` Python package. It works
like a Makefile, but is Python-based

"""

#######################################
## Configuration and Helpers for PyDoit
#######################################
## Make sure the src folder is in the path
import sys

sys.path.insert(1, "./src/")

import shutil
from os import environ, getcwd, path
from pathlib import Path

from colorama import Fore, Style, init

## Custom reporter: Print PyDoit Text in Green
# This is helpful because some tasks write to sterr and pollute the output in
# the console. I don't want to mute this output, because this can sometimes
# cause issues when, for example, LaTeX hangs on an error and requires
# presses on the keyboard before continuing. However, I want to be able
# to easily see the task lines printed by PyDoit. I want them to stand out
# from among all the other lines printed to the console.
from doit.reporter import ConsoleReporter
from settings import config

try:
    in_slurm = environ["SLURM_JOB_ID"] is not None
except:
    in_slurm = False


class GreenReporter(ConsoleReporter):
    def write(self, stuff, **kwargs):
        doit_mark = stuff.split(" ")[0].ljust(2)
        task = " ".join(stuff.split(" ")[1:]).strip() + "\n"
        output = (
            Fore.GREEN
            + doit_mark
            + f" {path.basename(getcwd())}: "
            + task
            + Style.RESET_ALL
        )
        self.outstream.write(output)


if not in_slurm:
    DOIT_CONFIG = {
        "reporter": GreenReporter,
        # other config here...
        # "cleanforget": True, # Doit will forget about tasks that have been cleaned.
        "backend": "sqlite3",
        "dep_file": "./.doit-db.sqlite",
    }
else:
    DOIT_CONFIG = {"backend": "sqlite3", "dep_file": "./.doit-db.sqlite"}
init(autoreset=True)


BASE_DIR = config("BASE_DIR")
DATA_DIR = config("DATA_DIR")
MANUAL_DATA_DIR = config("MANUAL_DATA_DIR")
OUTPUT_DIR = config("OUTPUT_DIR")
OS_TYPE = config("OS_TYPE")
USER = config("USER")

## Helpers for handling Jupyter Notebook tasks
environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"


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


def mv(from_path, to_path):
    """Move a file to a folder"""
    from_path = Path(from_path)
    to_path = Path(to_path)
    to_path.mkdir(parents=True, exist_ok=True)
    if OS_TYPE == "nix":
        command = f"mv {from_path} {to_path}"
    else:
        command = f"move {from_path} {to_path}"
    return command


def copy_file(origin_path, destination_path, mkdir=True):
    """Create a Python action for copying a file."""

    def _copy_file():
        origin = Path(origin_path)
        dest = Path(destination_path)
        if mkdir:
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, dest)

    return _copy_file


##################################
## Begin rest of PyDoit tasks here
##################################


def task_config():
    """Create empty directories for data and output if they don't exist"""
    return {
        "actions": ["ipython ./src/settings.py"],
        "targets": [DATA_DIR, OUTPUT_DIR],
        "file_dep": ["./src/settings.py"],
        "clean": [],
    }


def task_pull():
    """Pull data from external sources"""
    yield {
        "name": "fred",
        "doc": "Pull data from FRED",
        "actions": [
            "ipython ./src/settings.py",
            "ipython ./src/pull_fred.py",
        ],
        "targets": [DATA_DIR / "fred.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_fred.py"],
        "clean": [],
    }
    yield {
        "name": "ofr",
        "doc": "Pull data from OFR API",
        "actions": [
            "ipython ./src/settings.py",
            "ipython ./src/pull_ofr_api_data.py",
        ],
        "targets": [DATA_DIR / "ofr_public_repo_data.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_ofr_api_data.py"],
        "clean": [],
    }
    yield {
        "name": "fed_yield_curve",
        "doc": "Pull Fed yield curve data",
        "actions": [
            "ipython ./src/settings.py",
            "ipython ./src/load_fed_yield_curve.py",
        ],
        "targets": [DATA_DIR / "fed_yield_curve.parquet"],
        "file_dep": ["./src/settings.py", "./src/load_fed_yield_curve.py"],
        "clean": [],
    }


def task_example_plot():
    """Example plots"""
    file_dep = [Path("./src") / file for file in ["example_plot.py", "pull_fred.py"]]
    file_output = ["example_plot.png"]
    targets = [OUTPUT_DIR / file for file in file_output]

    return {
        "actions": [
            "ipython ./src/example_plot.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }


def task_chart_repo_rates():
    """Example charts for Chartbook"""
    file_dep = [
        "./src/pull_fred.py",
        "./src/chart_relative_repo_rates.py",
    ]
    targets = [
        DATA_DIR / "repo_public.parquet",
        DATA_DIR / "repo_public.xlsx",
        DATA_DIR / "repo_public_relative_fed.parquet",
        DATA_DIR / "repo_public_relative_fed.xlsx",
        OUTPUT_DIR / "repo_rates.html",
        OUTPUT_DIR / "repo_rates_normalized.html",
        OUTPUT_DIR / "repo_rates_normalized_w_balance_sheet.html",
    ]

    return {
        "actions": [
            "ipython ./src/chart_relative_repo_rates.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }


def task_chart_yield_curve():
    """Chart the current yield curve"""
    file_dep = [
        "./src/load_fed_yield_curve.py",
        "./src/chart_yield_curve.py",
    ]
    targets = [
        DATA_DIR / "fed_yield_curve_current.parquet",
        DATA_DIR / "fed_yield_curve_current.xlsx",
        OUTPUT_DIR / "yield_curve_current.html",
    ]

    return {
        "actions": [
            "ipython ./src/chart_yield_curve.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "task_dep": ["pull:fed_yield_curve"],
        "clean": True,
    }


notebook_tasks = {
    "01_example_notebook_interactive_ipynb": {
        "path": "./src/01_example_notebook_interactive_ipynb.py",
        "file_dep": [],
        "targets": [],
    },
    "02_example_with_dependencies_ipynb": {
        "path": "./src/02_example_with_dependencies_ipynb.py",
        "file_dep": ["./src/pull_fred.py"],
        "targets": [OUTPUT_DIR / "GDP_graph.png"],
    },
    "04_term_premium_charts_ipynb": {
        "path": "./src/04_term_premium_charts_ipynb.py",
        "file_dep": ["./src/load_fed_yield_curve.py"],
        "targets": [
            OUTPUT_DIR / "term_premium_10y_1y.html",
            OUTPUT_DIR / "term_premium_10y_2y.html",
            OUTPUT_DIR / "term_premium_10y_3y.html",
            DATA_DIR / "term_premium.parquet",
            DATA_DIR / "term_premium.xlsx",
        ],
        "task_dep": ["pull:fed_yield_curve"],
    },
}


# fmt: off
def task_run_notebooks():
    """Preps the notebooks for presentation format.
    Execute notebooks if the script version of it has been changed.
    """
    for notebook in notebook_tasks.keys():
        pyfile_path = Path(notebook_tasks[notebook]["path"])
        notebook_path = pyfile_path.with_suffix(".ipynb")
        task_config = {
            "name": notebook,
            "actions": [
                """python -c "import sys; from datetime import datetime; print(f'Start """ + notebook + """: {datetime.now()}', file=sys.stderr)" """,
                f"jupytext --to notebook --output {notebook_path} {pyfile_path}",
                jupyter_execute_notebook(notebook_path),
                jupyter_to_html(notebook_path),
                mv(notebook_path, OUTPUT_DIR / "_notebook_build"),
                """python -c "import sys; from datetime import datetime; print(f'End """ + notebook + """: {datetime.now()}', file=sys.stderr)" """,
            ],
            "file_dep": [
                pyfile_path,
                *notebook_tasks[notebook]["file_dep"],
            ],
            "targets": [
                OUTPUT_DIR / f"{notebook}.html",
                *notebook_tasks[notebook]["targets"],
            ],
            "clean": True,
        }
        # Add task_dep if specified
        if "task_dep" in notebook_tasks[notebook]:
            task_config["task_dep"] = notebook_tasks[notebook]["task_dep"]
        yield task_config
# fmt: on

sphinx_targets = [
    "./docs/index.html",
]


def task_compile_sphinx_docs():
    """Compile Sphinx Docs"""
    notebook_scripts = [
        Path(notebook_tasks[notebook]["path"]) for notebook in notebook_tasks.keys()
    ]
    file_dep = [
        "./README.md",
        "./chartbook.toml",
        *notebook_scripts,
    ]

    return {
        "actions": [
            "chartbook build -f",
        ],  # Use docs as build destination
        "targets": sphinx_targets,
        "file_dep": file_dep,
        "task_dep": [
            "run_notebooks",
        ],
        "clean": True,
    }
