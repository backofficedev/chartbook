# ChartBook

**Catalog and publish your team's data science work.**

<!-- ```{image} _static/logo.png
:alt: ChartBook logo
:width: 300px
:align: center
``` -->

ChartBook turns an analytics project — code, parquet files, chart HTML — into a documented website, and aggregates many projects into a searchable catalog with programmatic data access. If you know [Backstage](https://backstage.io/), Spotify's service catalog for software teams: ChartBook plays that role for data science teams, so pipelines, datasets, and charts are registered and discoverable instead of scattered across notebooks and shared drives.

Everything hangs off two kinds of `chartbook.toml`:

- A **pipeline** is any project directory whose `chartbook.toml` describes its charts, dataframes, and notebooks. `chartbook build` renders it into a static documentation site.
- A **catalog** is a `chartbook.toml` that registers many pipelines. It builds one combined, searchable site — and lets anyone load any cataloged dataset by name:

```python
from chartbook import data

df = data.load(pipeline="fred_charts", dataframe="fred", format="pandas")
```

## From zero to a documented pipeline

```console
pip install "chartbook[all]"
chartbook init            # scaffold a pipeline project
cd my-pipeline
chartbook build           # generate its documentation site
chartbook browse          # open it in your browser
```

{doc}`getting-started` walks through this and ends with your first chart on a page.

## Where things are

- {doc}`getting-started` — install, scaffold, first build
- {doc}`guide/documenting-a-pipeline` — describe your charts, dataframes, and notebooks
- {doc}`guide/catalogs-and-data` — aggregate pipelines and load data from anywhere
- {doc}`guide/plotting` — one call, five output files (interactive HTML plus static PNG/PDF)
- {doc}`reference/configuration` — every `chartbook.toml` field, type, and default
- {doc}`reference/cli` — every command

Working with an AI assistant? The built docs site ships [llms.txt](https://llmstxt.org/) files (`llms.txt` and `llms-full.txt` at the site root), and `chartbook install skill` adds a ChartBook skill to a Claude Code project.

```{toctree}
:hidden:
:caption: Learn

getting-started
guide/documenting-a-pipeline
guide/catalogs-and-data
guide/plotting
guide/gallery
guide/how-the-build-works
examples
```

```{toctree}
:hidden:
:caption: Reference

reference/configuration
reference/cli
reference/api
```

```{toctree}
:hidden:
:caption: Project

changelog
contributing
design/toml-format-v2
```
