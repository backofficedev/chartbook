# ChartBook

A developer platform for data science teams.

[![PyPI - Version](https://img.shields.io/badge/PyPI-v0.0.2-blue?logo=pypi)](https://pypi.org/project/chartbook)
[![PyPI - Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue?logo=python)](https://pypi.org/project/chartbook)

Discover, document, and share data science work across your organization. ChartBook provides a centralized catalog for data pipelines, charts, and documentation—making it easy to find, understand, and reuse analytics work.

## Terminology

ChartBook supports two project types:

- **Pipeline** — A single analytics pipeline with its own charts, dataframes, and documentation
- **Catalog** — A collection of multiple pipelines aggregated into a unified documentation site

See the [Concepts](https://backofficedev.github.io/chartbook/user-guide/concepts.html) page for the full terminology including ChartBooks and ChartHub.

## Features

- **Pipeline Catalog** — Organize and discover data pipelines across your team
- **Documentation Generation** — Build searchable documentation websites from your analytics work
- **Data Governance** — Track data sources, licenses, and access permissions
- **Programmatic Data Access** — Load pipeline outputs directly into pandas or polars
- **Multi-Pipeline Catalogs** — Aggregate multiple pipelines into a single documentation site

## Installation

**Recommended:**

```bash
pip install chartbook[all]
```

This gives you everything: data loading, plotting utilities, and the CLI for building documentation.

**Minimal install** (data loading only):

```bash
pip install chartbook[data]
```

**Development:**

```bash
pip install -e ".[dev]"
```

## Quick Start

### Load data from a pipeline

```python
from chartbook import data

df = data.load(pipeline_id="fred_charts", dataframe_id="interest_rates")
```

### Build documentation

```bash
chartbook build
```

See the [documentation](https://backofficedev.github.io/chartbook) for configuration options and detailed guides.

## Documentation

Full documentation is available at [backofficedev.github.io/chartbook](https://backofficedev.github.io/chartbook).

- [Getting Started](https://backofficedev.github.io/chartbook/getting-started.html)
- [Configuration Reference](https://backofficedev.github.io/chartbook/configuration.html)
- [CLI Reference](https://backofficedev.github.io/chartbook/cli-reference.html)

## Contributing

Contributions are welcome. See [CONTRIBUTING](https://backofficedev.github.io/chartbook/contributing.html) for guidelines.

## License

Modified BSD License