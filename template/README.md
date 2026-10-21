# Economics/Finance Project Template

A [Cookiecutter](https://github.com/cookiecutter/cookiecutter)-compatible template for creating reproducible data science projects with optional features for LaTeX reports, Jupyter notebooks, R scripts, Stata scripts, and various data sources.

We recommend using [cruft](https://cruft.github.io/cruft/) instead of cookiecutter to generate projects from this template. Cruft is fully compatible with cookiecutter templates but adds the ability to keep your project synchronized with template updates over time.

## Features

This template allows you to generate a customized data science project with:

- **Core Features** (always included):
  - PyDoit task runner for reproducible workflows
  - Python project structure with settings management
  - Git and environment configuration

- **Optional Features**:
  - LaTeX reports and slides (using custom templates)
  - Jupyter notebooks (stored as Python files using jupytext)
  - R scripts and RMarkdown files
  - Stata scripts
  - Chartbook documentation site
  - GitHub Actions CI/CD

- **Data Source Integration**:
  - FRED (Federal Reserve Economic Data)
  - Federal Reserve yield curve (Gürkaynak, Sack, and Wright)
  - OFR API (Office of Financial Research)
  - Bloomberg (requires terminal access)
  - CRSP Stock data (requires WRDS)
  - CRSP Compustat data (requires WRDS)

## Quick Start

### Prerequisites

1. Install [cruft](https://cruft.github.io/cruft/):
   ```bash
   pip install cruft
   ```

2. (Optional) Install [miniforge](https://github.com/conda-forge/miniforge) for conda environment management.

### Generate a New Project

```bash
chartbook init
```

`chartbook init` renders the copy of this template that came with your ChartBook, with no network,
and writes a `.cruft.json` that tracks the template's version on GitHub, enabling future updates (when
it knows the commit the template is at; otherwise it says how to link the project with `cruft link`).
The project's environment files ask for the template's private variable `_chartbook_version` or later,
which is the version of the ChartBook it came with: a test keeps `cookiecutter.json`'s value equal to
`chartbook.__about__.__version__`, so a release changes both.

Rendered with cruft instead, it comes from GitHub's main branch:

```bash
cruft create https://github.com/backofficedev/chartbook --directory template
```

You will be prompted for:
- Project name, and the folder name, which is made from it (press Enter to keep it)
- Description
- Author information
- Python version
- Which optional features to include
- Which data sources to include

### Updating Your Project

One of the key benefits of using cruft is the ability to update your project when the template changes:

```bash
# Check if your project is up-to-date with the template
cruft check

# View differences between your project and the latest template
cruft diff

# Update your project to the latest template version
cruft update
```

You can also add `cruft check` to your CI pipeline to ensure projects stay synchronized.

`cruft update` also moves the project's ChartBook floor (`chartbook>=` in its environment files) to the
template's version: cruft does not carry a private variable such as `_chartbook_version` forward, and
takes the template's own.

### Example Usage

```bash
# Generate with all defaults (interactive prompts)
cruft create https://github.com/backofficedev/chartbook --directory template

# Generate with custom options
cruft create https://github.com/backofficedev/chartbook --directory template \
  --no-input \
  --overwrite-if-exists \
  --extra-context '{"project_name": "My Analysis", "include_latex_reports": "y", "include_fred": "y"}'
```

## Project Structure

The generated project will have this structure (files vary based on options):

```
my_project/
├── README.md
├── dodo.py                 # PyDoit task definitions
├── requirements.txt        # Python dependencies
├── environment.yml         # Conda environment
├── .gitignore
├── .env.example
├── src/
│   ├── settings.py         # Configuration management
│   ├── misc_tools.py       # Utility functions
│   ├── pull_*.py           # Data pull scripts (based on selections)
│   ├── *.ipynb.py          # Notebook files (if selected)
│   └── ...
├── reports/                # LaTeX reports (if selected)
├── assets/                 # Static assets
├── data_manual/            # Version-controlled data
├── _data/                  # Downloaded data (gitignored)
├── _output/                # Generated outputs
└── .github/                # GitHub Actions (if selected)
```

## Running a Generated Project

After generating a project:

```bash
cd my_project

# Create and activate environment
conda create -n my_project python=3.12
conda activate my_project
pip install -r requirements.txt

# Run every task but the tests, then render the ChartBook site
chartbook build -f

# Or run every task but the tests, without the site
doit

# Run the tests
doit run_pytest

# List available tasks
doit list

# Run specific task
doit pull:fred
```

## Development

### Local Development Setup

When developing or testing the template locally, use `.` instead of the GitHub URL:

```bash
# Clone the repository. The template is its `template/` folder.
git clone https://github.com/backofficedev/chartbook
cd chartbook

# Generate a project from the local template to a specific output directory
cruft create . --directory template --output-dir ./tmp/

# Or with no prompts (use defaults)
cruft create . --directory template --no-input --output-dir ./tmp/

# Overwrite existing project with same name
cruft create . --directory template --no-input --output-dir ./tmp/ --overwrite-if-exists
```

cruft reads the template from git, so it renders what is **committed**. To try
an uncommitted change, use cookiecutter, which reads the folder as it is:
`cookiecutter template -o ./tmp/`. `chartbook init`, run from this checkout,
renders the files git tracks in `template/` at their content on disk: an
uncommitted change to one of them is rendered, and then the project has no
`.cruft.json`, since the template is at no commit.

If you have an existing project that was created with cookiecutter, you can link it to the template:

```bash
cd my_existing_project
cruft link https://github.com/backofficedev/chartbook --directory template
```

### Code Formatting

```bash
# Format code, sort imports, and fix linting issues
ruff format . && ruff check --select I --fix . && ruff check --fix .
```

### Running Template Tests

The template's tests are part of ChartBook's own, in `tests/test_template.py`,
and run with the rest:

```bash
hatch test tests/test_template.py
```

They render projects with different options and check what comes out. One
builds a rendered project with the ChartBook in this repository, so a change
to a command that the template uses is caught here. The integration tests run
the generated example scripts and compile the LaTeX reports. Each one is
skipped when what it needs (`latexmk` and `pdflatex`) is not installed.

### Testing Different Configurations

```bash
# Test minimal project (all features disabled)
cruft create . --directory template --no-input --output-dir ./tmp/ --extra-context '{
  "project_name": "Minimal Test",
  "include_latex_reports": "n", "include_jupyter_notebooks": "n", "include_r_scripts": "n",
  "include_stata_scripts": "n", "include_chartbook": "n", "include_github_actions": "n",
  "include_fred": "n", "include_ofr_api": "n", "include_bloomberg": "n",
  "include_crsp_stock": "n", "include_crsp_compustat": "n"}'

# Test full project (all features enabled; R needs conda or pixi)
cruft create . --directory template --no-input --output-dir ./tmp/ --extra-context '{
  "project_name": "Full Test", "environment_manager": "conda",
  "include_latex_reports": "y", "include_jupyter_notebooks": "y", "include_r_scripts": "y",
  "include_stata_scripts": "y", "include_chartbook": "y", "include_github_actions": "y",
  "include_fred": "y", "include_ofr_api": "y", "include_bloomberg": "y",
  "include_crsp_stock": "y", "include_crsp_compustat": "y"}'

# Verify generated project works
cd ./tmp/minimal_test  # or ./tmp/full_test
doit list
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
