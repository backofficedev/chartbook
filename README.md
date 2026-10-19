# ChartBook

A developer platform for data science teams.

[![PyPI - Version](https://img.shields.io/pypi/v/chartbook?logo=pypi)](https://pypi.org/project/chartbook)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/chartbook?logo=python)](https://pypi.org/project/chartbook)
[![GitHub Stars](https://img.shields.io/github/stars/backofficedev/chartbook?style=flat&logo=github)](https://github.com/backofficedev/chartbook)
[![Documentation](https://img.shields.io/badge/docs-backofficedev.github.io%2Fchartbook-blue)](https://backofficedev.github.io/chartbook/)

Discover, document, and share data science work across your organization. ChartBook provides a centralized catalog for data pipelines, charts, and documentation—making it easy to find, understand, and reuse analytics work.

## Terminology

ChartBook supports two project types:

- **Pipeline** — A single analytics pipeline with its own charts, dataframes, and documentation
- **Catalog** — A collection of multiple pipelines aggregated into a unified documentation site

See [Documenting a Pipeline](https://backofficedev.github.io/chartbook/guide/documenting-a-pipeline.html) and [Catalogs and Data Access](https://backofficedev.github.io/chartbook/guide/catalogs-and-data.html) for how the two fit together, and [Vocabulary](https://backofficedev.github.io/chartbook/guide/vocabulary.html) for the words ChartBook uses: a manifest asks, a lockfile records what was got, a snapshot records what was made, and an index records what a site shows.

## Features

- **Pipeline Catalog** — Organize and discover data pipelines across your team
- **Documentation Generation** — Build searchable documentation websites from your analytics work
- **Data Governance** — Track data sources, licenses, and access permissions
- **Programmatic Data Access** — Load pipeline outputs directly into pandas or polars
- **Multi-Pipeline Catalogs** — Aggregate multiple pipelines into a single documentation site

## Installation

```bash
pip install chartbook
```

One install, everything included: data loading, plotting utilities, and the CLI for building documentation.

**Development** needs [uv](https://docs.astral.sh/uv/) and nothing else:

```bash
uv sync          # the project, editable, and its dev toolchain, from uv.lock
uv run doit      # notebooks, docs, examples, the package, then the test matrix
```

`uv run doit build_package` is the same without the tests; `uv run doit test` is the suite on one Python. The [contributing page](https://backofficedev.github.io/chartbook/contributing.html) has the rest.

## Quick Start

### Load data from a pipeline

```python
from chartbook import data

df = data.load(pipeline="fred_charts", dataframe="fred")
```

### Build documentation

```bash
chartbook docs generate
chartbook docs generate -f --watch    # rebuild as you edit; refresh the browser
```

### Check a project in CI

```bash
chartbook check               # fails on broken paths, expiring licenses, and fields a [policy] requires
```

### Ask the manifest where a file belongs

```bash
chartbook path repo_public          # the path chartbook.toml declares for that dataframe
chartbook path chart/repo_rates     # ...and for that chart
```

```python
from chartbook import assets, data

df.to_parquet(data.path("repo_public"))            # a dataframe
fig.write_html(assets.path("chart/repo_rates"))    # anything else says its kind
```

### Declare a trained model

```toml
[models.rate_forecaster]
path = "./_models/rate_forecaster.joblib"
trained_on = ["repo_public"]
metrics_path = "./_output/rate_forecaster_metrics.json"
```

```python
from chartbook import models

joblib.dump(model, models.path("rate_forecaster"))  # the model gets a page: scores, lineage
```

### Browse your catalog

```bash
# List all pipelines, dataframes, and charts
chartbook ls

# List dataframes only
chartbook ls dataframes

# Get path to a dataframe's parquet file
chartbook data get-path --pipeline fred_charts --dataframe fred
```

See the [documentation](https://backofficedev.github.io/chartbook) for configuration options and detailed guides.

## Documentation

Full documentation is available at [backofficedev.github.io/chartbook](https://backofficedev.github.io/chartbook).

- [Getting Started](https://backofficedev.github.io/chartbook/getting-started.html)
- [Configuration Reference](https://backofficedev.github.io/chartbook/reference/configuration.html)
- [CLI Reference](https://backofficedev.github.io/chartbook/reference/cli.html)

## Contributing

Contributions are welcome. See [CONTRIBUTING](https://backofficedev.github.io/chartbook/contributing.html) for guidelines.

## License

Modified BSD License