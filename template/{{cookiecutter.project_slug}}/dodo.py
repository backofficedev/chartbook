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
from os import environ
from pathlib import Path

from settings import config

# Which tasks `doit` runs on its own is set at the end of this file
DOIT_CONFIG = {"backend": "sqlite3", "dep_file": "./.doit-db.sqlite"}


BASE_DIR = config("BASE_DIR")
DATA_DIR = config("DATA_DIR")
MANUAL_DATA_DIR = config("MANUAL_DATA_DIR")
OUTPUT_DIR = config("OUTPUT_DIR")
OS_TYPE = config("OS_TYPE")
USER = config("USER")
{%- if cookiecutter.include_jupyter_notebooks %}

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
{%- endif %}


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
        "actions": ["python ./src/settings.py"],
        "targets": [DATA_DIR, OUTPUT_DIR],
        "file_dep": ["./src/settings.py"],
        "clean": [],
    }

{%- if cookiecutter.include_fred or cookiecutter.include_ofr_api or cookiecutter.include_bloomberg or cookiecutter.include_crsp_stock or cookiecutter.include_crsp_compustat %}


def task_pull():
    """Pull data from external sources"""
{%- if cookiecutter.include_fred %}
    yield {
        "name": "fred",
        "doc": "Pull data from FRED",
        "actions": [
            "python ./src/settings.py",
            "python ./src/pull_fred.py",
        ],
        "targets": [DATA_DIR / "fred.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_fred.py"],
        "clean": [],
    }
{%- endif %}
{%- if cookiecutter.include_ofr_api %}
    yield {
        "name": "ofr",
        "doc": "Pull data from OFR API",
        "actions": [
            "python ./src/settings.py",
            "python ./src/pull_ofr_api_data.py",
        ],
        "targets": [DATA_DIR / "ofr_public_repo_data.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_ofr_api_data.py"],
        "clean": [],
    }
{%- endif %}
{%- if cookiecutter.include_bloomberg %}
    yield {
        "name": "bloomberg",
        "doc": "Pull data from Bloomberg",
        "actions": [
            "python ./src/settings.py",
            "python ./src/pull_bloomberg.py",
        ],
        "targets": [DATA_DIR / "bloomberg.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_bloomberg.py"],
        "clean": [],
    }
{%- endif %}
{%- if cookiecutter.include_crsp_stock %}
    yield {
        "name": "crsp_stock",
        "doc": "Pull CRSP stock data from WRDS",
        "actions": [
            "python ./src/settings.py",
            "python ./src/pull_CRSP_stock.py",
        ],
        "targets": [DATA_DIR / "CRSP_monthly_stock.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_CRSP_stock.py"],
        "clean": [],
    }
{%- endif %}
{%- if cookiecutter.include_crsp_compustat %}
    yield {
        "name": "crsp_compustat",
        "doc": "Pull CRSP Compustat data from WRDS",
        "actions": [
            "python ./src/settings.py",
            "python ./src/pull_CRSP_Compustat.py",
        ],
        "targets": [DATA_DIR / "CRSP_Compustat.parquet"],
        "file_dep": ["./src/settings.py", "./src/pull_CRSP_Compustat.py"],
        "clean": [],
    }
{%- endif %}
{%- endif %}
{%- if cookiecutter.include_latex_reports %}


def task_summary_stats():
    """Generate summary statistics tables"""
    file_dep = ["./src/example_table.py"]
    file_output = [
        "example_table.tex",
        "pandas_to_latex_simple_table1.tex",
    ]
    targets = [OUTPUT_DIR / file for file in file_output]

    return {
        "actions": [
            "python ./src/example_table.py",
            "python ./src/pandas_to_latex_demo.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }
{%- endif %}
{%- if cookiecutter.include_fred or cookiecutter.include_latex_reports %}


def task_example_plot():
    """Example plots"""
{%- if cookiecutter.include_fred %}
    file_dep = [Path("./src") / file for file in ["example_plot.py", "pull_fred.py"]]
{%- else %}
    file_dep = [Path("./src") / file for file in ["example_plot.py"]]
{%- endif %}
    file_output = ["example_plot.png"]
    targets = [OUTPUT_DIR / file for file in file_output]

    return {
        "actions": [
            "python ./src/example_plot.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }
{%- endif %}
{%- if cookiecutter.include_fred and cookiecutter.include_ofr_api %}


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
            "python ./src/chart_relative_repo_rates.py",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }
{%- endif %}
{%- if cookiecutter.include_jupyter_notebooks %}


notebook_tasks = {
    "01_example_notebook_interactive.ipynb.py": {
        "path": "./src/01_example_notebook_interactive.ipynb.py",
        "file_dep": [],
        "targets": [],
    },
{%- if cookiecutter.include_fred %}
    "02_example_with_dependencies.ipynb.py": {
        "path": "./src/02_example_with_dependencies.ipynb.py",
        "file_dep": ["./src/pull_fred.py"],
        "targets": [OUTPUT_DIR / "GDP_graph.png"],
    },
{%- endif %}
{%- if cookiecutter.include_fred and cookiecutter.include_ofr_api %}
    "03_public_repo_summary_charts.ipynb.py": {
        "path": "./src/03_public_repo_summary_charts.ipynb.py",
        "file_dep": [
            "./src/pull_fred.py",
            "./src/pull_ofr_api_data.py",
            "./src/pull_public_repo_data.py",
        ],
        "targets": [
            OUTPUT_DIR / "repo_rate_spikes_and_relative_reserves_levels.png",
            OUTPUT_DIR / "rates_relative_to_midpoint.png",
        ],
    },
{%- endif %}
}


# fmt: off
def task_run_notebooks():
    """Preps the notebooks for presentation format.
    Execute notebooks if the script version of it has been changed.
    """
    for notebook in notebook_tasks.keys():
        pyfile_path = Path(notebook_tasks[notebook]["path"])
        notebook_path = pyfile_path.with_suffix("")  # strips .py, leaves .ipynb
        notebook_name = notebook_path.stem  # e.g. "01_example_notebook_interactive"
        yield {
            "name": notebook,
            "actions": [
                """python -c "import sys; from datetime import datetime; print(f'Start """ + notebook + """: {datetime.now()}', file=sys.stderr)" """,
                f"jupytext --to notebook --output {notebook_path} {pyfile_path}",
                jupyter_execute_notebook(notebook_path),
                jupyter_to_html(notebook_path),
                mv(notebook_path, OUTPUT_DIR),
                """python -c "import sys; from datetime import datetime; print(f'End """ + notebook + """: {datetime.now()}', file=sys.stderr)" """,
            ],
            "file_dep": [
                pyfile_path,
                *notebook_tasks[notebook]["file_dep"],
            ],
            "targets": [
                OUTPUT_DIR / f"{notebook_name}.ipynb",
                OUTPUT_DIR / f"{notebook_name}.html",
                *notebook_tasks[notebook]["targets"],
            ],
            "clean": True,
        }
# fmt: on
{%- endif %}
{%- if cookiecutter.include_latex_reports %}

###############################################################
## Task below is for LaTeX compilation
###############################################################


def task_compile_latex_docs():
    """Compile the LaTeX documents to PDFs"""
    file_dep = [
        "./reports/report_example.tex",
        "./reports/my_article_header.sty",
        "./reports/slides_example.tex",
        "./reports/my_beamer_header.sty",
        "./reports/my_common_header.sty",
        "./reports/report_simple_example.tex",
        "./reports/slides_simple_example.tex",
        # Generated inputs. The reports typeset a placeholder for a missing one
        # instead of failing, so list them here to have doit build them first.
        OUTPUT_DIR / "example_plot.png",
        OUTPUT_DIR / "example_table.tex",
        OUTPUT_DIR / "pandas_to_latex_simple_table1.tex",
    ]
    targets = [
        "./reports/report_example.pdf",
        "./reports/slides_example.pdf",
        "./reports/report_simple_example.pdf",
        "./reports/slides_simple_example.pdf",
    ]

    if shutil.which("latexmk") is None:
        # Without TeX, the rest of the project still builds
        def say_latex_not_found():
            print(
                "latexmk was not found, so the reports in ./reports are not compiled. "
                "Install TeX Live (https://tug.org/texlive/), then run `doit compile_latex_docs`.",
                file=sys.stderr,
            )

        return {
            "actions": [say_latex_not_found],
            "targets": targets,
            "file_dep": file_dep,
        }

    return {
        "actions": [
            # My custom LaTeX templates
            "latexmk -xelatex -halt-on-error -cd ./reports/report_example.tex",  # Compile
            "latexmk -xelatex -halt-on-error -c -cd ./reports/report_example.tex",  # Clean
            "latexmk -xelatex -halt-on-error -cd ./reports/slides_example.tex",  # Compile
            "latexmk -xelatex -halt-on-error -c -cd ./reports/slides_example.tex",  # Clean
            # Simple templates based on small adjustments to Overleaf templates
            "latexmk -xelatex -halt-on-error -cd ./reports/report_simple_example.tex",  # Compile
            "latexmk -xelatex -halt-on-error -c -cd ./reports/report_simple_example.tex",  # Clean
            "latexmk -xelatex -halt-on-error -cd ./reports/slides_simple_example.tex",  # Compile
            "latexmk -xelatex -halt-on-error -c -cd ./reports/slides_simple_example.tex",  # Clean
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }
{%- endif %}
{%- if cookiecutter.include_r_scripts %}

##############################################################
# R Tasks - Uncomment if you have R installed
##############################################################


def task_install_r_packages():
    """Install R packages"""
    file_dep = [
        "r_requirements.txt",
        "./src/install_packages.r",
    ]
    targets = [OUTPUT_DIR / "R_packages_installed.txt"]

    return {
        "actions": [
            "Rscript ./src/install_packages.r",
        ],
        "targets": targets,
        "file_dep": file_dep,
        "clean": True,
    }


def task_example_r_script():
    """Example R plots"""
    file_dep = [
{%- if cookiecutter.include_fred %}
        "./src/pull_fred.py",
{%- endif %}
        "./src/example_r_plot.r"
    ]
    targets = [
        OUTPUT_DIR / "example_r_plot.png",
    ]

    return {
        "actions": [
            "Rscript ./src/example_r_plot.r",
        ],
        "targets": targets,
        "file_dep": file_dep,
{%- if cookiecutter.include_fred %}
        "task_dep": ["pull:fred"],
{%- endif %}
        "clean": True,
    }


rmarkdown_tasks = {
    "04_example_regressions.Rmd": {
{%- if cookiecutter.include_fred %}
        "file_dep": ["./src/pull_fred.py"],
{%- else %}
        "file_dep": [],
{%- endif %}
        "targets": [],
    },
}


def task_knit_RMarkdown_files():
    """Preps the RMarkdown files for presentation format.
    This will knit the RMarkdown files for easier sharing of results.
    """
    str_output_dir = str(OUTPUT_DIR).replace("\\", "/")
    def knit_string(file):
        return (
            "Rscript -e "
            '"library(rmarkdown); '
            f"rmarkdown::render('./src/{file}.Rmd', "
            "output_format='html_document', "
            f"output_dir='{str_output_dir}')\""
        )

    for notebook in rmarkdown_tasks.keys():
        notebook_name = notebook.split(".")[0]
        file_dep = [f"./src/{notebook}", *rmarkdown_tasks[notebook]["file_dep"]]
        html_file = f"{notebook_name}.html"
        targets = [f"{OUTPUT_DIR / html_file}", *rmarkdown_tasks[notebook]["targets"]]
        actions = [
            knit_string(notebook_name)
        ]

        yield {
            "name": notebook,
            "actions": actions,
            "file_dep": file_dep,
            "targets": targets,
            "clean": True,
        }
{%- endif %}
{%- if cookiecutter.include_stata_scripts %}

###############################################################
## Stata Tasks - Uncomment if you have Stata installed
###############################################################

if OS_TYPE == "windows":
    STATA_COMMAND = f"{config('STATA_EXE')} /e"
elif OS_TYPE == "nix":
    STATA_COMMAND = f"{config('STATA_EXE')} -b"
else:
    raise ValueError(f"OS_TYPE {OS_TYPE} is unknown")

def task_example_stata_script():
    """Example Stata plots

    Make sure to run
    ```
    net install doenv, from(https://github.com/vikjam/doenv/raw/master/) replace
    ```
    first to install the doenv package: https://github.com/vikjam/doenv.
    """
    file_dep = [
{%- if cookiecutter.include_fred %}
        "./src/pull_fred.py",
{%- endif %}
        "./src/example_stata_plot.do",
    ]
    targets = [
        OUTPUT_DIR / "example_stata_plot.png",
    ]
    return {
        "actions": [
            f"{STATA_COMMAND} do ./src/example_stata_plot.do",
        ],
        "targets": targets,
        "file_dep": file_dep,
{%- if cookiecutter.include_fred %}
        "task_dep": ["pull:fred"],
{%- endif %}
        "clean": True,
        "verbosity": 2,
    }
{%- endif %}


def task_run_pytest():
    """Run pytest and save results to OUTPUT_DIR"""
    src_py_files = list(Path("./src").glob("*.py"))
    test_output = OUTPUT_DIR / "pytest_results.xml"

    def run_pytest():
        import subprocess

        result = subprocess.run(
            ["pytest", f"--junitxml={test_output}"],
        )
        if result.returncode != 0:
            # Remove the XML so doit won't consider the target up-to-date
            Path(test_output).unlink(missing_ok=True)
            raise RuntimeError(f"pytest failed with exit code {result.returncode}")

    return {
        "actions": [run_pytest],
        "targets": [test_output],
        "file_dep": src_py_files,
        "clean": True,
        "verbosity": 2,
    }


## `doit` on its own (and so `chartbook build`) runs every task in this file
## but the tests, which run with `doit run_pytest`. Keep this at the end, so
## that a task you add above it is run too.
DOIT_CONFIG["default_tasks"] = [
    name.removeprefix("task_")
    for name in list(globals())
    if name.startswith("task_") and name != "task_run_pytest"
]
