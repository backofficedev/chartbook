# ChartBook

<div class="cb-hero">
<p class="cb-eyebrow">Data pipelines with provenance</p>
<p class="cb-hero-title">Know exactly where every number came from.</p>
<p class="cb-hero-sub">ChartBook connects your team's data pipelines, in any language, so each one builds on
another's exact, versioned output. Every chart traces back to its sources, every input is
verified by hash, and everything lands in one catalog your team browses and your agents build
on.</p>
</div>

```{code-block} console
:class: cb-hero-install
pip install chartbook
```

<div class="cb-hero-actions">
<a class="sd-btn sd-btn-primary cb-hero-button" href="getting-started.html">Quickstart: five minutes</a>
<a class="sd-btn sd-btn-outline-primary cb-hero-button" href="tutorials/explore-a-catalog.html">Explore a catalog</a>
</div>

```{image} _static/screenshots/quickstart-chart-light.png
:alt: A chart's page in a ChartBook site: the chart, its write-up, and a Provenance table that names the dataframe it was made from and that dataframe's content hash
:class: only-light cb-screenshot
:width: 760px
:align: center
```

```{image} _static/screenshots/quickstart-chart-dark.png
:alt: A chart's page in a ChartBook site: the chart, its write-up, and a Provenance table that names the dataframe it was made from and that dataframe's content hash
:class: only-dark cb-screenshot
:width: 760px
:align: center
```

<p class="cb-caption">Every chart gets a page: the chart, its write-up, and exactly what it was
made from, down to the hash of the data. This one is the Quickstart's.</p>

## What ChartBook does

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} {octicon}`package-dependencies;1.5em` Depend
:link: guide/depending-on-pipelines
:link-type: doc
Build on another pipeline's exact output, the way you depend on a package.
`chartbook add acme/rates` pins its newest snapshot in `chartbook.lock`, and what you read
changes only when you run `chartbook update`.
:::

:::{grid-item-card} {octicon}`git-commit;1.5em` Trace
:link: chartbook-lineage
:link-type: ref
Every dataframe, chart and model records what it was made from, by content hash.
`chartbook lineage` walks the chain back to the first source and checks every hash on the way.
:::

:::{grid-item-card} {octicon}`history;1.5em` Rebuild
:link: guide/keeping-costly-outputs
:link-type: doc
A snapshot keeps the exact bytes a pipeline made, labelled with its commit. Rebuild from the
same inputs, and put back an output that took a day to compute with `chartbook restore`.
:::

:::{grid-item-card} {octicon}`search;1.5em` Discover
:link: guide/catalogs-and-data
:link-type: doc
Many pipelines become one catalog: a searchable website for your team, and an index, an
`llms.txt` and a command line your agents work from.
:::

::::

```{image} _static/diagrams/ecosystem-light.svg
:alt: Pipelines in Python, R and Stata each publish snapshots to one store; the catalog site, your agents and a pipeline of yours read from it
:class: only-light
:align: center
```

```{image} _static/diagrams/ecosystem-dark.svg
:alt: Pipelines in Python, R and Stata each publish snapshots to one store; the catalog site, your agents and a pipeline of yours read from it
:class: only-dark
:align: center
```

**In any language.** A pipeline's build is whatever command you name: a Python script, R, Stata,
SQL, a Makefile. ChartBook runs it, records what it made, and lets the next pipeline read it,
from Python with `data.load()` or from anything else with `chartbook path`.

## For your team and for your agents

The catalog is one set of facts with two ways in. A person browses the site; an agent asks the
command line the same questions and gets the same answers.

| | Your team, in the browser | Your agents, from the command line |
|---|---|---|
| **What is there?** | The catalog's home page and search | `chartbook ls --json`, or the site's `llms.txt` |
| **What is it?** | The dataset's or chart's page | `chartbook get-docs yield_curve:chart/repo_rates` |
| **Use it** | Copy the snippet on the page | `data.load("yield_curve:repo_public")`, `chartbook add yield_curve` |
| **Can I trust it?** | The Provenance table and the Versions page | `chartbook lineage --json`, and `chartbook.lock` in git |

`chartbook install claude-skill` teaches Claude Code all of this, and every site ChartBook builds
ships an [llms.txt](https://llmstxt.org/) at its root.

## A pipeline, in three files

A pipeline is a folder: a manifest that says what it makes, the code that makes it, and a README.
The {doc}`Quickstart <getting-started>` builds this one.

::::{tab-set}

:::{tab-item} chartbook.toml
```{literalinclude} _examples/quickstart/chartbook.toml
:language: toml
```
:::

:::{tab-item} src/build_chart.py
```{literalinclude} _examples/quickstart/src/build_chart.py
:language: python
```
:::

:::{tab-item} Terminal
```console
$ python src/build_chart.py      # writes _data/walks.parquet and the chart
$ chartbook docs build           # writes the site, and index.json beside it
$ chartbook docs open
```
:::

::::

Once it takes a snapshot (`chartbook snapshot`), any other pipeline can read that dataset by
name, pinned to the exact bytes this one made:

```python
from chartbook import data

walks = data.load("my_pipeline:walks")   # the pinned copy, never the other folder
```

## Where next

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} Quickstart
:link: getting-started
:link-type: doc
Build a pipeline and its site in five minutes, from three files.
:::

:::{grid-item-card} Explore a catalog
:link: tutorials/explore-a-catalog
:link-type: doc
Download a real catalog of public data, browse it, and point your agent at it.
:::

:::{grid-item-card} Depend on another pipeline
:link: guide/depending-on-pipelines
:link-type: doc
Pin exactly what another pipeline built, and read it by name.
:::

:::{grid-item-card} Let your agent use the catalog
:link: guide/agents
:link-type: doc
How an agent finds, reads and builds on your team's work.
:::

::::

```{toctree}
:hidden:
:caption: Get started

getting-started
tutorials/explore-a-catalog
```

```{toctree}
:hidden:
:caption: How-to guides

guide/starting-a-project
guide/reading-and-writing-data
guide/documenting-a-pipeline
guide/depending-on-pipelines
guide/catalogs-and-data
guide/agents
guide/keeping-costly-outputs
guide/reading-a-warehouse
guide/plotting
guide/plotting-backends
guide/gallery
```

```{toctree}
:hidden:
:caption: Concepts

guide/vocabulary
guide/how-the-build-works
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

examples
changelog
roadmap
contributing
```
