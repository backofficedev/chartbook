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
│   ├── charts/           # Chart documentation
│   └── dataframes/       # Dataframe documentation
└── excel/                 # Excel files (optional)
```

## Creating a Pipeline

### Step 1: Initialize Configuration

Create a `chartbook.toml` file:

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.1"

[site]
title = "My Analytics Pipeline"
author = "Data Team"
copyright = "2025"

[pipeline]
id = "ANALYTICS"
pipeline_name = "Business Analytics Pipeline"
pipeline_description = "Monthly business metrics and KPIs"
lead_pipeline_developer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
git_repo_URL = "https://repository.yourcompany.org/scm/chart/repos/analytics"
README_file_path = "./README.md"
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
chartbook.plotting.multiline(
    df=df,
    x_col="date",
    y_cols=["revenue", "costs"],
    title="Revenue vs Costs",
    output_file_path=output_dir / "revenue_costs.html"
)
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

### Required Fields

Every pipeline must define:

```toml
[pipeline]
id = "UNIQUE_ID"              # Unique identifier (uppercase)
pipeline_name = "Full Name"   # Human-readable name
pipeline_description = "..."  # Detailed description
lead_pipeline_developer = "Name"
```

### Optional Fields

Additional metadata:

```toml
[pipeline]
contributors = ["Name1", "Name2"]
software_modules_command = "module load python/3.11"
runs_on_grid_or_windows_or_other = "Windows/Linux"
git_repo_URL = "https://..."
README_file_path = "./README.md"
```

## Best Practices

### 1. Consistent Naming

Use consistent naming conventions:
- Pipeline ID: `UPPERCASE_WITH_UNDERSCORES`
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
chartbook==0.0.1
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
   chartbook generate --project-dir .
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