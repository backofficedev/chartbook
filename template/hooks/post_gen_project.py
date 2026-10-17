#!/usr/bin/env python
"""Post-generation hook for removing optional files based on user selections."""

import os
import shutil

# Get the current working directory (the generated project)
PROJECT_DIR = os.getcwd()


def remove_file(filepath):
    """Remove a file if it exists."""
    full_path = os.path.join(PROJECT_DIR, filepath)
    if os.path.exists(full_path):
        os.remove(full_path)
        # print(f"  Removed: {filepath}")


def remove_dir(dirpath):
    """Remove a directory and its contents if it exists."""
    full_path = os.path.join(PROJECT_DIR, dirpath)
    if os.path.isdir(full_path):
        shutil.rmtree(full_path)
        # print(f"  Removed: {dirpath}/")


def remove_files_by_pattern(directory, pattern):
    """Remove files matching a pattern in a directory."""
    import fnmatch

    dir_path = os.path.join(PROJECT_DIR, directory)
    if not os.path.isdir(dir_path):
        return
    for filename in os.listdir(dir_path):
        if fnmatch.fnmatch(filename, pattern):
            filepath = os.path.join(directory, filename)
            remove_file(filepath)


def is_truthy(value):
    """Convert y/n/yes/no/true/false string to boolean."""
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("y", "yes", "true", "1")


# Feature flags from cookiecutter
include_latex = is_truthy("{{ cookiecutter.include_latex_reports }}")
include_notebooks = is_truthy("{{ cookiecutter.include_jupyter_notebooks }}")
include_r = is_truthy("{{ cookiecutter.include_r_scripts }}")
include_stata = is_truthy("{{ cookiecutter.include_stata_scripts }}")
include_chartbook = is_truthy("{{ cookiecutter.include_chartbook }}")
include_github_actions = is_truthy("{{ cookiecutter.include_github_actions }}")

# Data source flags
include_fred = is_truthy("{{ cookiecutter.include_fred }}")
include_fed_yield_curve = is_truthy("{{ cookiecutter.include_fed_yield_curve }}")
include_ofr = is_truthy("{{ cookiecutter.include_ofr_api }}")
include_bloomberg = is_truthy("{{ cookiecutter.include_bloomberg }}")
include_crsp_stock = is_truthy("{{ cookiecutter.include_crsp_stock }}")
include_crsp_compustat = is_truthy("{{ cookiecutter.include_crsp_compustat }}")

# Environment manager
environment_manager = "{{ cookiecutter.environment_manager }}"

print("Configuring project based on selections...")

# Remove environment files based on environment manager choice
if environment_manager == "pip":
    remove_file("environment.yml")
    remove_file("pixi.toml")
    remove_file("pyproject.toml")
    # Keep requirements.txt
elif environment_manager == "uv":
    remove_file("environment.yml")
    remove_file("pixi.toml")
    remove_file("requirements.txt")
    # Keep pyproject.toml
elif environment_manager == "conda":
    remove_file("pixi.toml")
    remove_file("pyproject.toml")
    # Keep environment.yml and requirements.txt
elif environment_manager == "pixi":
    remove_file("environment.yml")
    remove_file("pyproject.toml")
    # Keep pixi.toml and requirements.txt

# Remove LaTeX-related files if not selected
if not include_latex:
    # print("Removing LaTeX files...")
    remove_dir("reports")
    remove_file(".latexmkrc")
    remove_file("src/example_table.py")
    remove_file("src/pandas_to_latex_demo.py")

# Remove notebook files if not selected
if not include_notebooks:
    # print("Removing Jupyter notebook files...")
    remove_files_by_pattern("src", "*.ipynb.py")
else:
    # Handle notebook dependencies
    # Notebook 02 requires FRED
    if not include_fred:
        remove_file("src/02_example_with_dependencies.ipynb.py")
    # Notebook 03 requires FRED + OFR
    if not (include_fred and include_ofr):
        remove_file("src/03_public_repo_summary_charts.ipynb.py")

# Remove R-related files if not selected
if not include_r:
    # print("Removing R files...")
    remove_files_by_pattern("src", "*.r")
    remove_files_by_pattern("src", "*.R")
    remove_files_by_pattern("src", "*.Rmd")
    remove_file("r_requirements.txt")

# Remove Stata-related files if not selected
if not include_stata:
    # print("Removing Stata files...")
    remove_files_by_pattern("src", "*.do")

# Remove Chartbook-related files if not selected
if not include_chartbook:
    # print("Removing Chartbook files...")
    remove_file("chartbook.toml")
    remove_dir("docs_src")
    remove_dir(".claude/skills/chartbook")

# Remove jupytext-notebook skill if notebooks not selected
if not include_notebooks:
    remove_dir(".claude/skills/jupytext-notebook")

# Remove .claude directory entirely if nothing remains in it
claude_dir = os.path.join(PROJECT_DIR, ".claude", "skills")
if os.path.isdir(claude_dir) and not os.listdir(claude_dir):
    remove_dir(".claude")

# Remove GitHub Actions if not selected
if not include_github_actions:
    # print("Removing GitHub Actions...")
    remove_dir(".github")

# Remove data pull scripts based on selection
# print("Configuring data pull scripts...")

if not include_fred:
    remove_file("src/pull_fred.py")
    remove_file("src/test_pull_fred.py")

# example_plot.py demonstrates FRED data and feeds the LaTeX reports
if not (include_fred or include_latex):
    remove_file("src/example_plot.py")

if not include_fed_yield_curve:
    remove_file("src/load_fed_yield_curve.py")

if not include_ofr:
    remove_file("src/pull_ofr_api_data.py")

# pull_public_repo_data.py and chart_relative_repo_rates.py require both FRED and OFR
if not (include_fred and include_ofr):
    remove_file("src/pull_public_repo_data.py")
    remove_file("src/chart_relative_repo_rates.py")

if not include_bloomberg:
    remove_file("src/pull_bloomberg.py")

if not include_crsp_stock:
    remove_file("src/pull_CRSP_stock.py")

if not include_crsp_compustat:
    remove_file("src/pull_CRSP_Compustat.py")

print("Project configuration complete!")
print("\nNext steps:")
print("  cd {{ cookiecutter.project_slug }}")
if include_chartbook:
    print("  chartbook docs       # its site already, with nothing built yet")

# Until the next ChartBook release: this template is from GitHub's main
# branch, which 0.2.0 from PyPI cannot build, and main calls itself 0.2.0
# too, so pip has to be told to replace the one it installed
FROM_GITHUB = '"chartbook @ git+https://github.com/backofficedev/chartbook"'
UNTIL_RELEASED = "  # until the next ChartBook release"

if environment_manager == "pip":
    print("  python -m venv .venv")
    print("  source .venv/bin/activate  # Windows: .venv\\Scripts\\activate")
    print("  pip install -r requirements.txt")
    if include_chartbook:
        print(f"  pip install --force-reinstall {FROM_GITHUB}{UNTIL_RELEASED}")
elif environment_manager == "uv":
    print("  uv sync")
    if include_chartbook:
        print(f"  uv add {FROM_GITHUB}{UNTIL_RELEASED}")
    print("  source .venv/bin/activate  # Windows: .venv\\Scripts\\activate")
elif environment_manager == "conda":
    print(
        "  conda env create -f environment.yml"
    )
    print("  conda activate {{ cookiecutter.project_slug }}")
    if include_chartbook:
        print(f"  pip install --force-reinstall {FROM_GITHUB}{UNTIL_RELEASED}")
elif environment_manager == "pixi":
    if include_chartbook:
        print(f"  pixi add --pypi {FROM_GITHUB}{UNTIL_RELEASED}")
    print("  pixi shell")

if include_chartbook:
    print("  chartbook build -f   # runs doit, then renders the site again")
    print("  chartbook browse     # opens the site")
    print("  chartbook check      # what chartbook.toml still needs")
else:
    print("  doit")
