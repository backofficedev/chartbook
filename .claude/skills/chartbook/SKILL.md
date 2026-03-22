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
chartbook build           # Generate HTML documentation website
chartbook build -f        # Force overwrite existing docs
chartbook publish            # Publish to directory
chartbook create-data-glimpses  # Create data summary report
chartbook config             # Configure default catalog path
chartbook catalog add <path>     # Add pipeline(s) to catalog
chartbook catalog add <glob> -y  # Add multiple pipelines without prompt
chartbook ls                 # List all pipelines, dataframes, charts
chartbook ls pipelines       # List pipelines only
chartbook ls dataframes      # List dataframes only
chartbook ls charts          # List charts only
chartbook data get-path --pipeline <id> --dataframe <id>   # Get parquet path
chartbook data get-docs --pipeline <id> --dataframe <id>   # Print docs content
chartbook data get-docs-path --pipeline <id> --dataframe <id>  # Get docs path
```

## Configuration File

Projects use `chartbook.toml` with these sections:

- `[config]`: Project type (pipeline/catalog) and version
- `[site]`: Title, author, copyright, logo, `enable_data_download`
- `[pipeline]`: ID, name, description, developer info, `site_dir` (optional path to custom site pages)
- `[charts]`: Chart definitions with metadata
- `[dataframes]`: Data source definitions with governance info
- `[notebooks]`: Jupyter notebook references
- `[notes]`: Additional documentation

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

## Quick Start Configuration

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.12"

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

See REFERENCE.md for complete configuration examples and all available fields.
