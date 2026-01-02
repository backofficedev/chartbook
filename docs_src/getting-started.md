# Getting Started

This guide will help you install chartbook and create your first project.

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

chartbook has two main use cases with different installation methods:

### For Data Scientists (using chartbook in your projects)

Install the minimal package for loading data from ChartBook pipelines:

```console
pip install chartbook
```

This gives you access to the data loading API:

```python
from chartbook import data
df = data.load(pipeline_id="EX", dataframe_id="repo_public")
```

### For Generating Documentation (CLI)

**Recommended** (isolated installation, no dependency pollution):

```console
# Install globally via pipx
pipx install chartbook

# Or run without installing
pipx run chartbook generate
uvx chartbook generate
```

**Alternative** (if you prefer pip, installs Sphinx dependencies):

```console
pip install chartbook[sphinx]
```

### Development Installation

chartbook uses [Hatch](https://hatch.pypa.io/) for package management:

```console
pip install hatch
git clone <your-repo-url>
cd chartbook
hatch shell

# Install with all dependencies (sphinx + dev tools)
pip install -e ".[dev]"
```

**Important:** The quotes around `".[dev]"` are required when installing with extras locally.

Common installation patterns:

```console
pip install -e .              # Core only (data loading)
pip install -e ".[sphinx]"    # Core + Sphinx CLI
pip install -e ".[all]"       # All optional features (sphinx)
pip install -e ".[dev]"       # Everything (all + pytest)
```

**Tip:** Use `pip install -e ".[all]"` for development when you want all features but don't need testing tools. This is ideal for contributors working on documentation or CLI features.

## Quick Start Tutorial

### 1. Create Your First Pipeline Project

Create a new directory for your project and navigate to it:

```console
mkdir my-analytics-project
cd my-analytics-project
```

### 2. Create a Configuration File

Create a `chartbook.toml` file to configure your project:

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.1"

[site]
title = "My Analytics Project"
author = "Your Name"
copyright = "2025"
logo_path = ""
favicon_path = ""

[pipeline]
id = "MYPROJ"
pipeline_name = "My First Pipeline"
pipeline_description = "A demo pipeline for learning chartbook"
lead_pipeline_developer = "Your Name"
contributors = ["Your Name"]
```

### 3. Create Your First Chart

Create the necessary directories:

```console
mkdir -p _data _output docs_src/charts
```

Create a simple Python script to generate data (`generate_data.py`):

```python
import pandas as pd
import numpy as np
from pathlib import Path

# Generate sample data
dates = pd.date_range('2023-01-01', '2024-01-01', freq='D')
data = {
    'date': dates,
    'value1': np.cumsum(np.random.randn(len(dates))) + 100,
    'value2': np.cumsum(np.random.randn(len(dates))) + 100
}
df = pd.DataFrame(data)

# Save to parquet
df.to_parquet('_data/sample_data.parquet')
print("Sample data generated!")
```

### 4. Create a Chart

Create a chart using chartbook's plotting utilities:

```python
import chartbook
import pandas as pd
from pathlib import Path

# Load the data
df = pd.read_parquet('_data/sample_data.parquet')

# Create an interactive plot
chartbook.plotting.multiline(
    df=df,
    x_col='date',
    y_cols=['value1', 'value2'],
    title='My First Chart',
    output_file_path=Path('_output/my_first_chart.html')
)
print("Chart created!")
```

### 5. Add Chart Documentation

Create `docs_src/charts/my_first_chart.md`:

```markdown
# My First Chart

This chart shows the relationship between value1 and value2 over time.

## Key Insights
- Both values show trending behavior
- The correlation between the series changes over time

## Data Sources
- Generated sample data for demonstration
```

### 6. Update Configuration

Add the chart to your `chartbook.toml`:

```toml
[charts]

[charts.my_first_chart]
chart_name = "My First Chart"
short_description_chart = "Demo chart showing two time series"
dataframe_id = "sample_data"
topic_tags = ["Demo", "Time Series"]
data_frequency = "Daily"
units = "Index"
path_to_html_chart = "./_output/my_first_chart.html"
chart_docs_path = "./docs_src/charts/my_first_chart.md"

[dataframes]

[dataframes.sample_data]
dataframe_name = "Sample Data"
short_description_df = "Generated sample data for demonstration"
data_sources = ["Generated"]
path_to_parquet_data = "./_data/sample_data.parquet"
date_col = "date"
```

### 7. Generate Documentation

Now generate your documentation website:

```console
chartbook generate -f ./docs
```

Open `docs/index.html` in your browser to see your generated site!

## Next Steps

- Read the {doc}`user-guide/index` to learn about advanced features
- Explore {doc}`examples/index` for more complex use cases
- Check the {doc}`configuration` guide for all configuration options
- Learn about {doc}`user-guide/pipelines` to build reproducible analytics

## Common Issues

### Module Not Found Error

If you get import errors, make sure chartbook is installed in your current environment:

```console
pip show chartbook
```

### Permission Errors

On Windows, you might need to run commands as administrator or adjust file permissions.

### Sphinx Build Errors

If documentation generation fails, check that all required files exist:
- `chartbook.toml` in the project root
- Chart HTML files in the paths specified
- Documentation markdown files

## Getting Help

- Check the {doc}`cli-reference` for command options
- See {doc}`examples/index` for working examples
- Report issues on [GitHub](https://github.com/backofficedev/chartbook) 