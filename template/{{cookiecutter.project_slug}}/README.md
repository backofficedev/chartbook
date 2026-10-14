{{ cookiecutter.project_name }}
{{ '=' * cookiecutter.project_name|length }}

## About this project

{{ cookiecutter.project_description }}

## Quick Start

The quickest way to run code in this repo is to use the following steps.
{% if cookiecutter.include_latex_reports %}
You must have TexLive (or another LaTeX distribution) installed on your computer and available in your path.
You can do this by downloading and installing it from here ([windows](https://tug.org/texlive/windows.html#install)
and [mac](https://tug.org/mactex/mactex-download.html) installers).
{% endif %}
{% if cookiecutter.environment_manager == "pip" %}
First, create a virtual environment and activate it:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```
Then install the dependencies:
```bash
pip install -r requirements.txt
```
{% elif cookiecutter.environment_manager == "uv" %}
This project uses [uv](https://docs.astral.sh/uv/) for dependency management. First, install uv if you haven't already:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Then sync the environment:
```bash
uv sync
```
{% elif cookiecutter.environment_manager == "conda" %}
First, you must have the `conda` package manager installed (e.g., via Anaconda). However, I recommend using `mamba`, via [miniforge](https://github.com/conda-forge/miniforge) as it is faster and more lightweight than `conda`.

Create and activate the conda environment:
```bash
conda env create -f environment.yml
conda activate {{ cookiecutter.project_slug }}
```
{% elif cookiecutter.environment_manager == "pixi" %}
This project uses [pixi](https://pixi.sh/) for dependency management. First, install pixi if you haven't already:
```bash
curl -fsSL https://pixi.sh/install.sh | bash
```
Then install the dependencies:
```bash
pixi install
```
{% endif %}
Finally, run the project tasks:
```bash
{% if cookiecutter.environment_manager == "pixi" %}pixi run doit{% else %}doit{% endif %}
```
And that's it!
{% if cookiecutter.include_r_scripts %}

### Running R Code

This project includes R code. The R dependencies are managed alongside Python dependencies.
{% if cookiecutter.environment_manager == "conda" %}
The `environment.yml` file includes R packages. After creating the conda environment, R will be available.
{% elif cookiecutter.environment_manager == "pixi" %}
The `pixi.toml` file includes R packages. After running `pixi install`, R will be available.
{% endif %}
Make sure to uncomment the RMarkdown task from the `dodo.py` file, then run `doit` as before.
{% endif %}

### Other commands

#### Unit Tests and Doc Tests

You can run the unit test, including doctests, with the following command:
```
pytest --doctest-modules
```
{% if cookiecutter.include_chartbook %}
You can build the documentation site with:
```
chartbook docs -f
```
`doit` does this as its last step, and `chartbook build -f` runs `doit` and then renders the site.
{% endif %}

#### Setting Environment Variables

You can [export your environment variables](https://stackoverflow.com/questions/43267413/how-to-set-environment-variables-from-env-file)
from your `.env` files like so, if you wish. This can be done easily in a Linux or Mac terminal with the following command:
```bash
set -a  # automatically export all variables
source .env
set +a
```
On Windows (PowerShell):
```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') } }
```

### Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting Python code.

```bash
# Auto-fix linting issues (e.g., unused imports, undefined names)
ruff check . --fix

# Format code (consistent style, spacing, line length)
ruff format .

# Sort imports, then fix linting issues, then format
ruff format . && ruff check --select I --fix . && ruff check --fix .
```

- `ruff check --fix` applies safe auto-fixes for linting violations
- `ruff format` formats code similar to Black
- `--select I` targets only import sorting rules (isort-compatible)

### General Directory Structure

 - The `assets` folder is used for things like hand-drawn figures or other
   pictures that were not generated from code. These things cannot be easily
   recreated if they are deleted.

 - The `_output` folder, on the other hand, contains dataframes and figures that are
   generated from code. The entire folder should be able to be deleted, because
   the code can be run again, which would again generate all of the contents.

 - The `data_manual` is for data that cannot be easily recreated. This data
   should be version controlled. Anything in the `_data` folder or in
   the `_output` folder should be able to be recreated by running the code
   and can safely be deleted.

 - I'm using the `doit` Python module as a task runner. It works like `make` and
   the associated `Makefile`s. To rerun the code, install `doit`
   (https://pydoit.org/) and execute the command `doit` from the `src`
   directory. Note that doit is very flexible and can be used to run code
   commands from the command prompt, thus making it suitable for projects that
   use scripts written in multiple different programming languages.

 - I'm using the `.env` file as a container for absolute paths that are private
   to each collaborator in the project. You can also use it for private
   credentials, if needed. It should not be tracked in Git.

### Data and Output Storage

I'll often use a separate folder for storing data. Any data in the data folder
can be deleted and recreated by rerunning the PyDoit command (the pulls are in
the dodo.py file). Any data that cannot be automatically recreated should be
stored in the "data_manual" folder. Because of the risk of manually-created data
getting changed or lost, I prefer to keep it under version control if I can.
Thus, data in the "_data" folder is excluded from Git (see the .gitignore file),
while the "data_manual" folder is tracked by Git.

Output is stored in the "_output" directory. This includes dataframes, charts, and
rendered notebooks. When the output is small enough, I'll keep this under
version control. I like this because I can keep track of how dataframes change as my
analysis progresses, for example.

Of course, the _data directory and _output directory can be kept elsewhere on the
machine. To make this easy, I always include the ability to customize these
locations by defining the path to these directories in environment variables,
which I intend to be defined in the `.env` file, though they can also simply be
defined on the command line or elsewhere. The `settings.py` is responsible for
loading these environment variables and doing some preprocessing on them.
The `settings.py` file is the entry point for all other scripts to these
definitions. That is, all code that references these variables and others are
loaded by importing `config`.

### Naming Conventions

 - **`pull_` vs `load_`**: Files or functions that pull data from an external
 data source are prepended with "pull_", as in "pull_fred.py". Functions that
 load data that has been cached in the "_data" folder are prepended with "load_".
 For example, inside of the `pull_CRSP_Compustat.py` file there is both a
 `pull_compustat` function and a `load_compustat` function. The first pulls from
 the web, whereas the other loads cached data from the "_data" directory.


### Dependencies and Virtual Environments
{% if cookiecutter.environment_manager == "pip" %}
#### Working with `pip` requirements

This project uses `pip` with a virtual environment. Install requirements with:
```bash
pip install -r requirements.txt
```

To update the requirements file after adding new packages:
```bash
pip freeze > requirements.txt
```
{% elif cookiecutter.environment_manager == "uv" %}
#### Working with `uv`

This project uses [uv](https://docs.astral.sh/uv/) for fast, reliable Python package management. Dependencies are defined in `pyproject.toml` and locked in `uv.lock`.

To sync your environment with the lockfile:
```bash
uv sync
```

To add a new dependency:
```bash
uv add <package-name>
```

To update all dependencies:
```bash
uv lock --upgrade
uv sync
```
{% elif cookiecutter.environment_manager == "conda" %}
#### Working with `conda` environments

This project uses conda for environment management. The dependencies are stored in `environment.yml`.

To create/update the environment:
```bash
conda env create -f environment.yml
# or to update an existing environment:
conda env update -f environment.yml
```

To activate the environment:
```bash
conda activate {{ cookiecutter.project_slug }}
```

To export the current environment:
```bash
conda env export > environment.yml
```

**Tip:** Consider using `mamba` instead of `conda` for faster package resolution. Install via [miniforge](https://github.com/conda-forge/miniforge).
{% elif cookiecutter.environment_manager == "pixi" %}
#### Working with `pixi`

This project uses [pixi](https://pixi.sh/) for fast, reproducible environment management. Dependencies are defined in `pixi.toml`.

To install/update dependencies:
```bash
pixi install
```

To add a new dependency:
```bash
pixi add <package-name>
```

To run commands in the environment:
```bash
pixi run <command>
# or use predefined tasks:
pixi run test
pixi run format
```
{% endif %}
