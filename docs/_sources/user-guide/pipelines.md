# Pipelines

Pipelines are the core organizational unit in chartbook. A pipeline represents a complete analytics workflow that produces charts and dataframes.

## What is a Pipeline?

A pipeline is:
- A self-contained analytics project
- A collection of related charts and dataframes
- A reproducible workflow with documentation
- A unit that can be published and shared

## Pipeline Structure

A typical pipeline directory structure:

```
my-pipeline/
├── chartbook.toml          # Configuration file
├── README.md               # Pipeline documentation
├── dodo.py                 # Task automation (optional)
├── _data/                  # Data files
│   ├── raw/               # Raw input data
│   └── processed/         # Processed data
├── _output/               # Generated outputs
│   ├── *.html            # Interactive charts
│   └── *.ipynb           # Notebooks
├── src/                   # Source code
│   ├── data_processing.py
│   └── create_charts.py
├── docs_src/              # Documentation sources
│   ├── charts/           # Chart documentation fragments
│   ├── dataframes/       # Dataframe documentation fragments
│   └── site/             # Custom site pages (auto-detected as site_dir)
└── excel/                 # Excel files (optional)
```

Custom markdown pages placed in `docs_src/site/` are merged into the generated site automatically — `site_dir` defaults to `./docs_src/site/` when that directory exists. The built HTML output goes to `./docs/`.

## Creating a Pipeline

### Step 1: Initialize Configuration

Create a `chartbook.toml` file. The presence of the file alone marks the directory as a chartbook pipeline — even an empty file is valid — but you will usually add project metadata:

```toml
[project]
name = "Business Analytics Pipeline"
description = "Monthly business metrics and KPIs"
maintainer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
repo_url = "https://repository.yourcompany.org/scm/chart/repos/analytics"
```

### Step 2: Organize Your Data

Store data in the `_data` directory:

```python
import pandas as pd
from pathlib import Path

# Create data directory
data_dir = Path("_data")
data_dir.mkdir(exist_ok=True)

# Save processed data
df = process_raw_data()
df.to_parquet(data_dir / "metrics.parquet")
```

### Step 3: Create Charts

Generate charts in the `_output` directory:

```python
import chartbook
from pathlib import Path

# Create output directory
output_dir = Path("_output")
output_dir.mkdir(exist_ok=True)

# Generate chart
chartbook.plotting.line(
    df,
    x="date",
    y=["revenue", "costs"],
    title="Revenue vs Costs",
).save(chart_id="revenue_costs", output_dir=output_dir)
```

### Step 4: Document Everything

Create documentation in `docs_src`:

```markdown
# Revenue vs Costs Chart

This chart displays the relationship between revenue and costs over time.

## Key Insights
- Revenue growth outpaces cost growth
- Seasonal patterns evident in Q4

## Methodology
- Data sourced from financial system
- Monthly aggregation applied
```

## Pipeline Configuration

All `[project]` keys are optional with sensible defaults — `name` defaults to the directory name, `repo_url` to the git `origin` remote, and the pipeline's scoped ID (`scope/name`) is derived from the git remote and directory name (see {doc}`concepts` for how identity works). Whether any field is *required* is decided by the catalog that aggregates your pipeline, via its `[policy]` section (see {doc}`catalog-projects`).

### Core Fields

The fields most catalogs expect:

```toml
[project]
name = "Full Name"            # Human-readable name (also the site title)
description = "..."           # Detailed description
maintainer = "Name"           # Primary maintainer (also the site author)
repo_url = "https://..."      # Repository URL
```

### Additional Fields

```toml
[project]
id = "acme/analytics"         # Scoped ID; usually derived, set only to override
contributors = ["Name1", "Name2"]
os_compatibility = ["Windows", "Linux", "macOS"]
readme = "./README.md"        # Defaults to ./README.md
site_url = "https://..."      # URL of the published site
copyright = "2026"            # Defaults to the current year
logo = "./assets/logo.png"    # Defaults to a bundled asset
favicon = "./assets/favicon.ico"
build = """
module load python/3.11
doit
"""
```

The `build` field is a single string with shell-script semantics: a multi-line value is one script, so state (like an activated environment) carries across lines. See {doc}`../configuration` for the full key reference.

## Best Practices

### 1. Consistent Naming

Use consistent naming conventions:
- Pipeline ID: `scope/name` with lowercase components (e.g. `ftsfr/crsp_treasury`)
- File names: `lowercase_with_underscores`
- Chart IDs: `descriptive_chart_name`

### 2. Version Control

Track all pipeline files in git:
```bash
git init
git add chartbook.toml src/ docs_src/
git commit -m "Initial pipeline setup"
```

### 3. Data Management

- Store raw data separately from processed data
- Use Parquet format for efficiency
- Document data sources and transformations
- Include data validation checks

### 4. Reproducibility

Make your pipeline reproducible:
```python
# Set random seeds
import numpy as np
np.random.seed(42)

# Document package versions
# requirements.txt
pandas==2.0.0
numpy==1.24.0
chartbook==0.0.21
```

### 5. Documentation

Document at multiple levels:
- `README.md`: Overall pipeline documentation
- Chart docs: Individual chart explanations
- Code comments: Implementation details
- Dataframe docs: Data source information

## Pipeline Automation

Use `dodo.py` for task automation:

```python
# dodo.py
from doit import task_params

@task_params([{"name": "year", "default": 2024}])
def task_process_data(year):
    """Process raw data for specified year."""
    return {
        'actions': [f'python src/process_data.py --year {year}'],
        'file_dep': ['src/process_data.py'],
        'targets': [f'_data/processed_{year}.parquet'],
    }

def task_create_charts():
    """Generate all charts."""
    return {
        'actions': ['python src/create_all_charts.py'],
        'file_dep': ['_data/processed_2024.parquet'],
        'targets': ['_output/revenue_costs.html'],
    }
```

Run tasks:
```bash
doit
```

## Publishing Pipelines

Prepare your pipeline for publication:

1. **Clean up temporary files**:
   ```bash
   rm -rf __pycache__ .ipynb_checkpoints
   ```

2. **Validate configuration**:
   ```bash
   chartbook build --project-dir .
   ```

3. **Publish to staging**:
   ```bash
   chartbook publish --publish-dir ./staging
   ```

4. **Review and publish to production**:
   ```bash
   chartbook publish
   ```

## Troubleshooting

### Common Issues

1. **Missing dependencies**: Ensure all required packages are installed
2. **Path errors**: Use relative paths in configuration
3. **Data not found**: Check file paths and extensions
4. **Chart generation fails**: Verify data types and column names

### Debugging Tips

- Use `--keep-build-dirs` to inspect intermediate files
- Check logs in `_docs/_build/` directory
- Validate TOML syntax with online validators
- Test charts individually before full generation

## Next Steps

- Learn about {doc}`charts` to create visualizations
- Understand {doc}`dataframes` for data management