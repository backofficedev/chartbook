# Quickstart

In five minutes you will build a pipeline that makes a dataset and a chart, and a website that
shows both, with a record of exactly what each one was made from.

```{image} _static/screenshots/quickstart-chart-light.png
:alt: The chart's page this Quickstart builds: the chart, its write-up, and what it was made from
:class: only-light cb-screenshot
:width: 560px
:align: center
```

```{image} _static/screenshots/quickstart-chart-dark.png
:alt: The chart's page this Quickstart builds: the chart, its write-up, and what it was made from
:class: only-dark cb-screenshot
:width: 560px
:align: center
```

You need Python 3.10 or newer, and git.

## 1. Make a folder and install ChartBook

A pipeline is a folder. Make one, give it its own Python environment, and install ChartBook in
it.

::::{tab-set}
:sync-group: shell

:::{tab-item} macOS / Linux
:sync: bash
```bash
mkdir -p my-pipeline/src
cd my-pipeline
git init
python -m venv .venv
source .venv/bin/activate
pip install chartbook
```
:::

:::{tab-item} Windows PowerShell
:sync: powershell
```powershell
mkdir my-pipeline\src
cd my-pipeline
git init
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install chartbook
```
If PowerShell says running scripts is disabled, allow your own once with
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, and activate again.
:::

:::{tab-item} Windows Command Prompt
:sync: cmd
```bat
mkdir my-pipeline\src
cd my-pipeline
git init
python -m venv .venv
.venv\Scripts\activate.bat
pip install chartbook
```
:::

::::

One install has everything: the command line, data loading, plotting and the site builder.
Using [uv](https://docs.astral.sh/uv/)? `uv venv` and `uv pip install chartbook` do the same.

## 2. Say what the pipeline makes

`chartbook.toml` is the pipeline's **manifest**. It names each thing the pipeline makes, says
where it goes, and carries a short write-up of it. This one makes a dataframe, `walks`, and a
chart of it, `random_walks`. Save it in `my-pipeline/`:

```{literalinclude} _examples/quickstart/chartbook.toml
:language: toml
:caption: chartbook.toml
```

And a `README.md` beside it, which becomes the site's front page:

```{literalinclude} _examples/quickstart/README.md
:language: markdown
:caption: README.md
```

## 3. Write the code that makes it

ChartBook does not run your analysis for you, and does not care how it is written. Here it is one
Python script. It asks the manifest where `walks` goes instead of repeating the path:

```{literalinclude} _examples/quickstart/src/build_chart.py
:language: python
:caption: src/build_chart.py
:emphasize-lines: 13
```

Run it from the `my-pipeline` folder:

```console
python src/build_chart.py
```

It writes the dataset, `_data/walks.parquet`, and the chart in five files under `_output/`:
interactive HTML, and PNG and PDF in two sizes, ready for a paper or a slide.

## 4. Build the site

```console
chartbook docs build
```

The first time, ChartBook asks whether this folder is yours, since building a pipeline's site can
run what its manifest names. It is: type `y`. Then open it:

```console
chartbook docs open
```

```{image} _static/screenshots/quickstart-site-light.png
:alt: The site's front page: the README, and the pipeline's charts and dataframes in the sidebar
:class: only-light cb-screenshot
:align: center
```

```{image} _static/screenshots/quickstart-site-dark.png
:alt: The site's front page: the README, and the pipeline's charts and dataframes in the sidebar
:class: only-dark cb-screenshot
:align: center
```

Click **Two Random Walks** under Pipeline Charts, then the dataframe it names.

## What just happened

- **The manifest declared two assets**, each with a name, a place and a write-up. Your code
  asked for `walks` by name, so the path is written once.
- **The build recorded everything it found** in `docs/index.json`, beside the site: an ID for
  each asset (`my_pipeline:walks`, `my_pipeline:chart/random_walks`), where it is, and a content
  hash of its bytes. The chart's page reads that record: **Made from** `my_pipeline:walks`, at
  the hash it had.
- **The dataframe got a page of its own**: its columns and first rows, its date range, and which
  charts use it.

```{image} _static/screenshots/quickstart-dataframe-light.png
:alt: The dataframe's page: a glimpse of its columns and rows, and a Provenance table with its hash, size, rows and the chart that uses it
:class: only-light cb-screenshot
:width: 560px
:align: center
```

```{image} _static/screenshots/quickstart-dataframe-dark.png
:alt: The dataframe's page: a glimpse of its columns and rows, and a Provenance table with its hash, size, rows and the chart that uses it
:class: only-dark cb-screenshot
:width: 560px
:align: center
```

Change the seed in `build_chart.py`, run it again and rebuild the site: the chart, the glimpse and
both hashes change with it.

## Next

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} Explore a catalog
:link: tutorials/explore-a-catalog
:link-type: doc
Download a catalog of several pipelines built on public data, browse it, and point your agent
at it.
:::

:::{grid-item-card} Depend on another pipeline
:link: guide/depending-on-pipelines
:link-type: doc
Take a snapshot of this pipeline, and read `walks` from another one, pinned.
:::

:::{grid-item-card} Start a real project
:link: guide/starting-a-project
:link-type: doc
`chartbook init` scaffolds a project with a build script, notebooks and its own pages.
:::

:::{grid-item-card} Document a pipeline
:link: guide/documenting-a-pipeline
:link-type: doc
Notebooks, models, files, notes and your own pages: everything the manifest can describe.
:::

::::
