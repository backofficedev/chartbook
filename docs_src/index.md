# ChartBook

**Turn a data pipeline into a documented, searchable site, and let other pipelines build on
what it made.**

A pipeline is a folder of code in git: a manifest, scripts, write-ups, and the data, charts and
models the scripts produce. ChartBook reads that folder, records what is in it, and writes a
site. Many pipelines make a catalog: one site over all of them, where any dataset can be loaded
by name, and where one pipeline can pin exactly what another one built.

```{image} _static/diagrams/chain-light.svg
:alt: repository, resolved into an index, written into pages, built into a site
:class: only-light
:align: center
```

```{image} _static/diagrams/chain-dark.svg
:alt: repository, resolved into an index, written into pages, built into a site
:class: only-dark
:align: center
```

Three steps, each a transformation of the one before. The **index** in the middle is the point
of the design: one JSON file that says what the site shows, with an ID and a content hash for
everything, so that pages can be written for any site tool, two builds can be compared, and
another program can read what you published without scraping it. {doc}`guide/vocabulary` defines
these words, and every page here uses them in those senses.

## Start

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} Install and build
:link: getting-started
:link-type: doc
`pip install chartbook`, scaffold a project with `chartbook init`, and have a site in a minute.
:::

:::{grid-item-card} Document a pipeline
:link: guide/documenting-a-pipeline
:link-type: doc
Describe charts, dataframes, notebooks, notes and models in `chartbook.toml`; each gets a page.
:::

:::{grid-item-card} Depend on another pipeline
:link: guide/depending-on-pipelines
:link-type: doc
Snapshots, pins and the lockfile: read exactly what another pipeline built, and nothing else.
:::

::::

## The four documents

Four files, one record format, and none is another in disguise. **A manifest asks, a lockfile
records what was got, a snapshot records what was made, and an index records what a site
shows.**

```{image} _static/diagrams/documents-light.svg
:alt: the manifest, the lockfile, the snapshot and the index: what each records, who writes it, where it lives
:class: only-light
:align: center
```

```{image} _static/diagrams/documents-dark.svg
:alt: the manifest, the lockfile, the snapshot and the index: what each records, who writes it, where it lives
:class: only-dark
:align: center
```

## From zero to a documented pipeline

```console
pip install chartbook
chartbook init            # scaffold a pipeline project
cd <your-project>
chartbook docs generate   # write the site, and index.json beside it
chartbook docs open       # open it
```

```python
from chartbook import data

df = data.load(pipeline="fred_charts", dataframe="fred", format="pandas")   # any cataloged dataset
rates = data.load("fed_yield_curve:treasury_rates")   # a dependency's dataframe: the pinned copy, by name
```

## Where things are

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User guide
- {doc}`getting-started`: install, scaffold, first build
- {doc}`guide/vocabulary`: the words, defined once
- {doc}`guide/documenting-a-pipeline`: the manifest and the pages it makes
- {doc}`guide/depending-on-pipelines`: snapshots, pins, the lockfile
- {doc}`guide/keeping-costly-outputs`: `keep = true`, `chartbook restore`, and the stop before a build remakes it
- {doc}`guide/catalogs-and-data`: one site over many pipelines; `data.load()`
- {doc}`guide/plotting`: one call, five chart files
- {doc}`guide/how-the-build-works`: the index, the writer, Sphinx
:::

:::{grid-item-card} Reference
- {doc}`reference/configuration`: every `chartbook.toml` field
- {doc}`reference/cli`: every command
- {doc}`reference/api`: the Python modules
- {doc}`reference/stability`: what "experimental" means here
- {doc}`design/overview`: the design, decision by decision
:::

::::

Working with an AI assistant? The built site ships [llms.txt](https://llmstxt.org/) files at its
root, and `chartbook install claude-skill` installs a ChartBook skill for Claude Code, which says when it is for another ChartBook.

```{toctree}
:hidden:
:caption: User guide

getting-started
guide/vocabulary
guide/documenting-a-pipeline
guide/depending-on-pipelines
guide/keeping-costly-outputs
guide/catalogs-and-data
guide/reading-a-warehouse
guide/plotting
guide/plotting-backends
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
reference/stability
```

```{toctree}
:hidden:
:caption: Project

changelog
roadmap
contributing
design/overview
design/toml-format-v2
design/references
design/asset-graph
design/index-schema
design/writer
design/models
design/data-access
design/stores-and-backends
design/versioned-catalog
design/trust
design/keep
design/reading-other-pipelines
design/plan-0.3.0
design/plan-0.4.0
design/plan-data-reads
```
