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
chartbook generate           # Generate HTML documentation website
chartbook generate -f        # Force overwrite existing docs
chartbook publish            # Publish to directory
chartbook create-data-glimpses  # Create data summary report
```

## Configuration File

Projects use `chartbook.toml` with these sections:

- `[config]`: Project type (pipeline/catalog) and version
- `[site]`: Title, author, copyright, logo
- `[pipeline]`: ID, name, description, developer info
- `[charts]`: Chart definitions with metadata
- `[dataframes]`: Data source definitions with governance info
- `[notebooks]`: Jupyter notebook references
- `[notes]`: Additional documentation

## Data Loading API

```python
from chartbook import data

# Load a dataframe
df = data.load(pipeline_id="PROJ", dataframe_id="my_data")

# Load with format specification
df = data.load(pipeline_id="PROJ", dataframe_id="my_data", format="polars")
```

## Directory Structure

```
my-pipeline/
├── chartbook.toml      # Configuration
├── _data/               # Parquet data files
├── _output/             # Generated HTML charts
├── docs_src/            # Markdown documentation
│   ├── charts/
│   └── dataframes/
└── src/                 # Python source code
```

## Quick Start Configuration

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.1"

[site]
title = "My Analytics"
author = "Your Name"
copyright = "2025"

[pipeline]
id = "MYPROJ"
pipeline_name = "My Pipeline"
pipeline_description = "Description"
lead_pipeline_developer = "Your Name"
```

See REFERENCE.md for complete configuration examples and all available fields.
