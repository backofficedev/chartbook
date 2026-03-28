---
name: chartbook
description: Help users work with ChartBook - a data science documentation platform for organizing pipelines, charts, and dataframes
---

# ChartBook Assistant

Use this skill when helping users with ChartBook projects for data science documentation and analytics pipeline management.

## What is ChartBook?

ChartBook is a developer platform for data science teams to discover, document, and share analytics work. It provides:
- Centralized catalog for pipelines, charts, and dataframes
- Automatic documentation website generation
- Data governance and licensing tracking
- Programmatic data loading via Python API

## Project Types

1. **Pipeline**: Single analytics project with charts and dataframes
2. **Catalog**: Collection of multiple pipelines in unified documentation

## Key CLI Commands

```bash
chartbook init              # Scaffold new project (requires chartbook[all])
chartbook build             # Generate HTML documentation website
chartbook build -f          # Force overwrite existing docs
chartbook browse            # Open project docs in default browser
chartbook publish           # Publish to directory
chartbook create-data-glimpses  # Create data summary report
chartbook config            # Configure default catalog path (interactive)
chartbook catalog init      # Create global catalog at ~/.chartbook/chartbook.toml
chartbook catalog add <path>     # Add pipeline(s) to catalog
chartbook catalog add <glob> -y  # Add multiple pipelines without prompt
chartbook catalog disable <id>   # Disable a pipeline (skip during builds)
chartbook catalog enable <id>    # Re-enable a disabled pipeline
chartbook catalog build     # Build HTML docs for the global catalog
chartbook catalog browse    # Open global catalog docs in browser
chartbook ls                # List all pipelines, dataframes, charts
chartbook ls pipelines      # List pipelines only
chartbook ls dataframes     # List dataframes only
chartbook ls charts         # List charts only
chartbook data get-path --pipeline <id> --dataframe <id>   # Get parquet path
chartbook data get-docs --pipeline <id> --dataframe <id>   # Print docs content
chartbook data get-docs-path --pipeline <id> --dataframe <id>  # Get docs path
```

For detailed catalog management commands, browsing, and data access workflows, see **catalog_system.md**.

## Global Config Directory (`~/.chartbook/`)

```
~/.chartbook/
├── settings.toml        # User settings (catalog path override, etc.)
├── chartbook.toml       # Default global catalog
├── artifacts/           # Auxiliary files (e.g. cached data)
├── docs/                # Rendered catalog HTML (from `catalog build`)
├── _docs/               # Temp Sphinx build dir (auto-cleaned)
└── _docs_src/           # Temp source dir (auto-cleaned)
```

**Catalog path resolution order:**
1. Explicit `--catalog` flag on CLI commands
2. `catalog.path` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Auto-prompt to create one (interactive TTY only)

## Configuration File

Projects use `chartbook.toml` with these sections:

- `[config]`: Project type (pipeline/catalog) and version
- `[site]`: Title, author, copyright, logo, `enable_data_download`
- `[pipeline]`: ID, name, description, developer info, `site_dir` (optional path to custom site pages)
- `[charts]`: Chart definitions with metadata
- `[dataframes]`: Data source definitions with governance info
- `[notebooks]`: Jupyter notebook references
- `[notes]`: Additional documentation

For complete TOML field references, required fields, and full configuration examples, see **manifest_files.md**.

### Pipeline disable/enable

Pipelines in a catalog can be temporarily disabled by adding `disabled = true`:

```toml
[pipelines.sovereign_bonds]
path_to_pipeline = "../sovereign_bonds"
disabled = true
```

Disabled pipelines are skipped during builds. Use `chartbook catalog disable <id>` / `chartbook catalog enable <id>` to toggle. Re-adding a disabled pipeline with `chartbook catalog add` automatically re-enables it.

## Data Loading API

```python
from chartbook import data

# Load a dataframe (returns Polars LazyFrame by default)
lf = data.load(pipeline="PROJ", dataframe="my_data")

# Load as Polars eager DataFrame
df = data.load(pipeline="PROJ", dataframe="my_data", format="polars_eager")

# Load as pandas DataFrame
df = data.load(pipeline="PROJ", dataframe="my_data", format="pandas")

# Load with explicit catalog path
lf = data.load(pipeline="PROJ", dataframe="my_data", catalog_path="/path/to/catalog")

# Get data file path
path = data.get_data_path(pipeline="PROJ", dataframe="my_data")

# Get documentation content as a string
docs = data.get_docs(pipeline="PROJ", dataframe="my_data")

# Get path to documentation source file
docs_path = data.get_docs_path(pipeline="PROJ", dataframe="my_data")
```

For advanced loading options, format details, and catalog setup, see **catalog_system.md**.

### Hive-Partitioned Data

Use glob patterns in `path_to_parquet_data` for hive-partitioned datasets:

```toml
[dataframes.my_data]
path_to_parquet_data = "./_data/hive_dataset/**/*.parquet"
```

Polars `scan_parquet` handles glob patterns natively with automatic hive partitioning. Glob paths only support `format="polars"` (LazyFrame).

## Directory Structure

```
my-pipeline/
├── chartbook.toml       # Configuration
├── _data/               # Parquet data files
├── _output/             # Generated HTML charts
├── docs_src/            # Markdown documentation
│   ├── charts/
│   ├── dataframes/
│   └── site/            # (Optional) Custom site pages (site_dir)
│       ├── index_toc.md # Controls toctree injection into index page
│       └── *.md         # Custom markdown pages
└── src/                 # Python source code
```

## Plotting API

```python
import chartbook

# Basic charts — returns ChartResult with .show() and .save(chart_id)
chartbook.plotting.line(df, x="date", y="value", title="GDP")
chartbook.plotting.bar(df, x="category", y="amount")
chartbook.plotting.scatter(df, x="x", y="y")
chartbook.plotting.pie(df, names="category", values="amount")
chartbook.plotting.area(df, x="date", y="value")

# Dual-axis chart
chartbook.plotting.dual(df, x="date", left_y="gdp", right_y="rate",
                         left_type="bar", right_type="line")

# Configuration
chartbook.plotting.configure(nber_recessions=True, default_output_dir="./_output")
chartbook.plotting.set_style("chartbook")
```

Requires `pip install "chartbook[plotting]"` or `pip install "chartbook[all]"`.

## Quick Start Configuration

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.19"

[site]
title = "My Analytics"
author = "Your Name"
copyright = "2026"

[pipeline]
id = "MYPROJ"
pipeline_name = "My Pipeline"
pipeline_description = "Description"
lead_pipeline_developer = "Your Name"
# site_dir = "./docs_src/site/"  # Optional: custom site pages directory
```

## Troubleshooting

- **Module Not Found**: Run `pip show chartbook` to verify installation
- **Permission Errors**: On Windows, run as administrator
- **Sphinx Build Errors**: Check all required files exist
- **Path Errors**: Use relative paths from project root
- **TOML Syntax**: Validate with online TOML validators
- **site_dir errors**: Ensure the directory exists and does not contain a `cb/` subdirectory (reserved namespace)
