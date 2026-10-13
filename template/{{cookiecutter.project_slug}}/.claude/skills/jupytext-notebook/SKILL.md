---
name: jupytext-notebook
description: Write Python files in jupytext percent format for Jupyter notebook conversion. Use when creating or editing *.ipynb.py files, or when the user asks about notebook authoring, jupytext, or the percent format.
---

# Jupytext Percent Format Notebooks

Notebooks are authored as `*.ipynb.py` files using [jupytext's percent format](https://jupytext.readthedocs.io/), then converted to `.ipynb` and executed by the build system. This keeps notebooks version-control friendly and diff-able.

## YAML Header

Every notebook file starts with this header:

```python
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---
```

## Cell Types

**Markdown cells** — Use `# %% [markdown]`. Each content line starts with `# `. Use a bare `#` for blank lines:

```python
# %% [markdown]
# ## Section Title
#
# First paragraph of explanation.
#
# Second paragraph with details:
# 1. Step one
# 2. Step two
```

**Code cells** — Use `# %%`:

```python
# %%
import polars as pl

df = pl.read_parquet("data.parquet")
df
```

## Complete Example

```python
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # 01. GDP Over Time
#
# This notebook visualizes US GDP over time using Plotly charts.

# %%
from pathlib import Path

import plotly.express as px
import pull_fred
from settings import config

OUTPUT_DIR = Path(config("OUTPUT_DIR"))

# %%
df = pull_fred.load_fred()
df

# %%
gdp_df = df[["GDP"]].dropna().reset_index()
gdp_df.columns = ["Date", "GDP"]

fig = px.line(
    gdp_df,
    x="Date",
    y="GDP",
    title="US Gross Domestic Product (GDP)",
    labels={"GDP": "GDP (Billions of Dollars)", "Date": "Date"},
)
fig.update_layout(hovermode="x unified", template="plotly_white")
fig

# %%
chart_path = OUTPUT_DIR / "01_gdp_chart.html"
fig.write_html(chart_path)
print(f"Chart saved to: {chart_path}")

# %%
```

## Conventions

- **File naming**: Files MUST end with `.ipynb.py` (e.g., `01_analysis.ipynb.py`)
- **DataFrame display**: End code cells with a bare variable name to render output in Jupyter (e.g., `df` on the last line)
- **Wide DataFrames**: Use `.glimpse()` for Polars DataFrames with many columns (vertical display)
- **No sys.path manipulation**: Do NOT use `sys.path.insert()` or `__file__` — these are unavailable in converted notebooks. Rely on proper package installation and PYTHONPATH
- **No defensive programming**: Assume data is available; skip empty DataFrame checks and file existence guards
- **No print for DataFrames**: Let Jupyter render DataFrames natively instead of using `print()`

## Build System Integration (dodo.py)

Notebooks are converted, executed, and published via PyDoit tasks in `dodo.py`.

### Helper Functions

These helpers generate shell commands for the notebook pipeline:

```python
def jupyter_execute_notebook(notebook_path):
    return f"jupyter nbconvert --execute --to notebook --ClearMetadataPreprocessor.enabled=True --inplace {notebook_path}"

def jupyter_to_html(notebook_path, output_dir=OUTPUT_DIR):
    return f"jupyter nbconvert --to html --output-dir={output_dir} {notebook_path}"

def mv(from_path, to_path):
    from_path = Path(from_path)
    to_path = Path(to_path)
    to_path.mkdir(parents=True, exist_ok=True)
    return f"mv {from_path} {to_path}"
```

### Registering Notebooks

Add entries to the `notebook_tasks` dictionary:

```python
notebook_tasks = {
    "01_data_sources_overview.ipynb.py": {
        "path": "./src/01_data_sources_overview.ipynb.py",
        "file_dep": [
            DATA_DIR / "ravenpack_djpr.parquet",
            DATA_DIR / "gdelt_sp500_headlines" / "year=2025" / "month=01" / "data.parquet",
        ],
        "targets": [],
    },
    "02_gdelt_sp500_filtering.ipynb.py": {
        "path": "./src/02_gdelt_sp500_filtering.ipynb.py",
        "file_dep": [
            DATA_DIR / "gdelt_sp500_headlines" / "year=2025" / "month=01" / "data.parquet",
            DATA_DIR / "sp500_names_lookup.parquet",
        ],
        "targets": [],
    },
}
```

Each entry has:
- **path**: Path to the `.ipynb.py` source file
- **file_dep**: Python modules or data files the notebook depends on. The notebook re-runs when these change.
- **targets**: Output files the notebook produces (plots, tables, etc.)

### The Pipeline Task

The `task_run_notebooks()` generator processes each notebook through:

1. `jupytext --to notebook` — convert `.py` to `.ipynb`
2. `jupyter nbconvert --execute` — execute the notebook in place
3. `jupyter nbconvert --to html` — create an HTML version
4. Move the `.ipynb` to `OUTPUT_DIR`

```python
def task_run_notebooks():
    for notebook in notebook_tasks.keys():
        pyfile_path = Path(notebook_tasks[notebook]["path"])
        notebook_path = pyfile_path.with_suffix("")  # strips .py, leaves .ipynb
        notebook_name = notebook_path.stem  # e.g. "01_data_sources_overview"
        yield {
            "name": notebook,
            "actions": [
                f"jupytext --to notebook --output {notebook_path} {pyfile_path}",
                jupyter_execute_notebook(notebook_path),
                jupyter_to_html(notebook_path),
                mv(notebook_path, OUTPUT_DIR),
            ],
            "file_dep": [
                pyfile_path,
                *notebook_tasks[notebook]["file_dep"],
            ],
            "targets": [
                OUTPUT_DIR / f"{notebook_name}.html",
                *notebook_tasks[notebook]["targets"],
            ],
            "clean": True,
        }
```

### Running Notebooks

```bash
doit run_notebooks                                           # Run all notebooks
doit run_notebooks:01_data_sources_overview.ipynb.py          # Run a specific notebook
```
