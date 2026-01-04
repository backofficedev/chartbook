# ChartBook

**A developer platform for data science teams**

```{image} _static/logo.png
:alt: ChartBook logo
:width: 400px
:align: center
```

Discover, document, and share data science work across your organization.

## Overview

ChartBook provides a centralized catalog for data pipelines, charts, and documentation. It helps data science teams:

- Organize and discover analytics work across the organization
- Generate searchable documentation websites
- Track data governance, licensing, and access permissions
- Load pipeline outputs programmatically into pandas or polars

New to ChartBook? Read {doc}`why-chartbook` to understand how it compares to tools like Backstage.

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} 🚀 **Getting Started**
:link: getting-started
:link-type: doc

Installation and quick start guide.
:::

:::{grid-item-card} 📖 **User Guide**
:link: user-guide/index
:link-type: doc

Pipelines, charts, dataframes, and configuration.
:::

:::{grid-item-card} 💡 **Examples**
:link: examples/index
:link-type: doc

Real-world examples and best practices.
:::

:::{grid-item-card} 🐍 **API Reference**
:link: api/chartbook
:link-type: doc

Python API documentation.
:::

::::

## Features

- **Chart Management** — Organize and document charts with metadata and publication tracking
- **Dataframe Catalog** — Maintain a catalog of datasets with sources, licensing, and documentation
- **Pipeline Support** — Build reproducible analytics pipelines with dependency management
- **Documentation Generation** — Generate static websites to share analytics work
- **Database Integration** — Upload dataframes to Trino for enterprise-wide access
- **Plotting Module** — Simple API for creating charts with automatic HTML, PNG, and PDF export

## Quick Example

```python
from chartbook import data, plotting

# Load data from a pipeline
df = data.load(pipeline_id="fred_charts", dataframe_id="interest_rates")

# Create a chart with automatic multi-format export
plotting.line(
    df,
    chart_id="repo_rates",
    x="date",
    y=["SOFR", "EFFR"],
    title="Repo Rates",
    nber_recessions=True,
)
```

```bash
# Build documentation website
chartbook build
```

## Installation

**Recommended for most users:**

```console
pip install chartbook[all]
```

This installs everything you need to load data, create visualizations, and build documentation sites.

````{dropdown} Other installation options
:icon: tools

**Minimal install (data loading only):**
```console
pip install chartbook[data]
```

**Using pipx (isolated environment):**
```console
pipx install chartbook[all]
```

**Development:**
```console
git clone <your-repo-url>
cd chartbook
pip install -e ".[dev]"
```
````

## Next Steps

- Follow the {doc}`getting-started` guide to install chartbook
- Read the {doc}`user-guide/index` to learn about key concepts
- Explore {doc}`examples/index` to see chartbook in action
- Check the {doc}`cli-reference` for command-line usage

```{toctree}
:hidden:
:maxdepth: 2

why-chartbook
getting-started
user-guide/index
cli-reference
api/chartbook
examples/index
configuration
llms-txt
contributing
changelog
```
