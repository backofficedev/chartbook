# Catalog System & Data Access

How to set up, manage, browse, and load data from ChartBook catalogs.

## Global Catalog Setup

### Directory Structure

```
~/.chartbook/
├── settings.toml        # User settings (catalog path override)
├── chartbook.toml       # Default global catalog
├── artifacts/           # Auxiliary files (e.g. cached data)
├── docs/                # Rendered catalog HTML (from `catalog build`)
├── _docs/               # Temp Sphinx build dir (auto-cleaned)
└── _docs_src/           # Temp source dir (auto-cleaned)
```

### Initialize a Global Catalog

```bash
chartbook catalog init                       # Interactive — prompts for title
chartbook catalog init --title "My Catalog"  # Non-interactive
```

Creates `~/.chartbook/chartbook.toml` with a minimal skeleton:

```toml
[config]
type = "catalog"

[site]
title = "My Catalog"
author = ""
copyright = "2026"
logo_path = ""
favicon_path = ""

[pipelines]
```

Also creates `~/.chartbook/artifacts/`. Errors if catalog already exists.

### Configure Default Catalog Path

```bash
chartbook config   # Interactive — prompts for path to an existing catalog
```

Sets `catalog.path` in `~/.chartbook/settings.toml` so that `data.load()` and CLI commands can find the catalog without an explicit `--catalog` argument.

### Catalog Path Resolution Order

1. Explicit `--catalog` flag on CLI commands (or `catalog_path=` in Python API)
2. `catalog.path` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Auto-prompt to create one (interactive TTY only)

## Managing the Catalog

### Add Pipelines

```bash
# Add a single pipeline
chartbook catalog add /path/to/pipeline

# Add all pipelines under a directory (glob expansion)
chartbook catalog add /path/to/projects/*

# Add without confirmation prompt
chartbook catalog add /path/to/projects/* -y

# Add to a specific catalog
chartbook catalog add ./my-pipeline --catalog /path/to/catalog/chartbook.toml
```

**Behavior:**
- Validates each directory contains a `chartbook.toml` with `type = "pipeline"`
- Extracts pipeline name from `pipeline.pipeline_name` field
- Generates sanitized TOML keys from directory names (lowercase, underscores)
- Stores relative paths from the catalog directory
- Detects duplicates by absolute path comparison
- Re-adding a disabled pipeline automatically re-enables it

### Disable / Enable Pipelines

```bash
chartbook catalog disable PIPELINE_ID [--catalog PATH]
chartbook catalog enable PIPELINE_ID [--catalog PATH]
```

Sets or clears `disabled = true` on a pipeline entry. Disabled pipelines remain in the TOML file but are skipped during builds and excluded from queries.

### Build Catalog Documentation

```bash
chartbook catalog build              # Build HTML docs to ~/.chartbook/docs/
chartbook catalog build -f           # Force overwrite existing docs
chartbook catalog build --strict     # Error on missing files instead of skipping
```

### Browse Catalog Documentation

```bash
chartbook catalog browse   # Opens ~/.chartbook/docs/index.html in default browser
```

## Browsing the Catalog (CLI)

### List Catalog Contents

```bash
chartbook ls                    # Tree format: all pipelines, dataframes, charts
chartbook ls pipelines          # List pipelines only
chartbook ls dataframes         # List all dataframes across pipelines
chartbook ls charts             # List all charts across pipelines
chartbook ls --catalog /path/to/catalog/chartbook.toml
```

**Output format:**
```
Catalog: /path/to/catalog/chartbook.toml

[pipeline] SALES: Sales Analytics Pipeline
  [dataframe] SALES/sales_data: Sales Transactions
  [chart] SALES/monthly_sales: Monthly Sales Overview
```

### Access Dataframe Metadata

```bash
# Get path to a dataframe's parquet file
chartbook data get-path --pipeline SALES --dataframe sales_data

# Print documentation content for a dataframe
chartbook data get-docs --pipeline SALES --dataframe sales_data

# Get path to documentation source file
chartbook data get-docs-path --pipeline SALES --dataframe sales_data
```

All `chartbook data` commands accept an optional `--catalog PATH` flag.

## Data Loading API (Python)

```python
from chartbook import data

# Load a dataframe (returns Polars LazyFrame by default)
lf = data.load(pipeline="SALES", dataframe="sales_data")

# Load as Polars eager DataFrame
df = data.load(pipeline="SALES", dataframe="sales_data", format="polars_eager")

# Load as pandas DataFrame
df = data.load(pipeline="SALES", dataframe="sales_data", format="pandas")

# Load with explicit catalog path
lf = data.load(pipeline="SALES", dataframe="sales_data",
               catalog_path="/path/to/catalog/chartbook.toml")

# Get data file path
path = data.get_data_path(pipeline="SALES", dataframe="sales_data")

# Get documentation content as a string
docs = data.get_docs(pipeline="SALES", dataframe="sales_data")

# Get path to documentation source file
docs_path = data.get_docs_path(pipeline="SALES", dataframe="sales_data")
```

### Format Options

| Format | Returns | Glob support |
|--------|---------|--------------|
| `"polars"` (default) | `polars.LazyFrame` via `scan_parquet(hive_partitioning=True)` | Yes |
| `"polars_eager"` | `polars.DataFrame` via `read_parquet()` | No (`ValueError`) |
| `"pandas"` | `pandas.DataFrame` via `read_parquet()` | No (`ValueError`) |

### Hive-Partitioned Data Loading

When `path_to_parquet_data` uses a glob pattern (e.g., `**/*.parquet`), Polars `scan_parquet` automatically detects hive directory structure and adds partition columns to the LazyFrame. Only `format="polars"` supports glob patterns.

### Catalog Path Resolution in Python

Same priority as CLI:
1. Explicit `catalog_path=` argument
2. `get_default_catalog_path()` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Raises `CatalogNotConfiguredError` — suggests running `chartbook config`

### Documentation Retrieval

`get_docs()` and `get_docs_path()` handle both documentation modes transparently:
- **`dataframe_docs_path`**: Reads the external `.md` file; `get_docs_path()` returns the file path
- **`dataframe_docs_str`**: Returns the inline string directly; `get_docs_path()` returns the `chartbook.toml` path

## Environment & Path Utilities (`chartbook.env`)

```python
import chartbook

# Find project root (searches for .git, pyproject.toml, .env)
BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"
OUTPUT_DIR = BASE_DIR / "_output"

# Read from CLI args, environment variables, or .env file
username = chartbook.env.get("WRDS_USERNAME")
api_key = chartbook.env.get("FRED_API_KEY", default="")

# Get OS type ("nix", "windows", or "unknown")
os_type = chartbook.env.get_os_type()
```

### `chartbook.env.get()` Resolution Priority

1. Command-line arguments (`--VAR_NAME=value`)
2. Environment variables (including `.env` file via `decouple`)
3. Module defaults
4. Caller-provided `default` value
5. Error if not found

## Scaffolding New Projects

```bash
chartbook init   # Wraps cruft create — requires pip install "chartbook[all]"
```

Creates a new pipeline project from the cookiecutter template. Projects can later pull upstream template updates via `cruft update`.

## CLI Build & Publish Reference

```bash
chartbook build [OUTPUT_DIR]     # Generate HTML documentation
chartbook build -f               # Force overwrite existing output
chartbook build --strict         # Error on missing files
chartbook build --keep-build-dirs  # Keep temp build directories
chartbook publish                # Publish to directory
chartbook create-data-glimpses   # Create data summary report
```

### Build Options

```
-f, --force-write        Overwrite existing output directory
--project-dir PATH       Path to project directory
--publish-dir PATH       Directory for published files
--docs-build-dir PATH    Build directory (default: ./_docs)
--temp-docs-src-dir PATH Temporary source directory
--keep-build-dirs        Keep temporary build directories
--size-threshold FLOAT   File size threshold in MB (default: 50)
--strict                 Error on missing source files instead of skipping
--strip-mathjax2 / --no-strip-mathjax2  Strip Plotly MathJax 2 (default: enabled)
```
