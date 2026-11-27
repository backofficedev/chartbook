# Quickstart

Build your first ChartBook pipeline, take a verified snapshot, and open your searchable catalog in **five minutes**—starting from three minimal files with zero framework lock-in.

```{raw} html
<video class="cb-terminal" autoplay loop muted playsinline aria-label="A terminal walking through the ChartBook Quickstart: chartbook.toml, build script, running, snapshotting, and opening the catalog">
<source src="_static/tapes/quickstart.webm" type="video/webm">
<source src="_static/tapes/quickstart.mp4" type="video/mp4">
</video>
```

**Prerequisites:** Python 3.10+ and `git`.

## 1. Create a folder and install ChartBook

A pipeline is just a regular git folder. Create one, set up a virtual environment, and install ChartBook:

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

:::{tab-item} uv
:sync: uv
```bash
mkdir -p my-pipeline/src
cd my-pipeline
git init
uv venv
source .venv/bin/activate
uv pip install chartbook
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
If PowerShell blocks script activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and activate again.
:::

::::

One install includes everything: the CLI, data loading, plotting, and the catalog site builder.

## 2. Declare what your pipeline builds

Add a small `chartbook.toml` manifest in `my-pipeline/`. It tells ChartBook two things: **how to run your build** (`[scripts]`) and **what datasets or charts it produces**:

```{literalinclude} _examples/quickstart/chartbook.toml
:language: toml
:caption: chartbook.toml
```

Add a short `README.md` (which becomes your pipeline's landing page in the catalog) and a `.gitignore` so git tracks your code while ignoring generated data and HTML:

```{literalinclude} _examples/quickstart/README.md
:language: markdown
:caption: README.md
```

```{literalinclude} _examples/quickstart/.gitignore
:language: text
:caption: .gitignore
```

## 3. Write your build script

ChartBook doesn't care how you generate your outputs—Python, R, Stata, SQL, or a Makefile all work. Here's a short Python script that writes the `walks` dataset (asking ChartBook where `walks` lives instead of hardcoding paths) and saves a chart:

```{literalinclude} _examples/quickstart/src/build_chart.py
:language: python
:caption: src/build_chart.py
:emphasize-lines: 13
```

## 4. Run, commit, and snapshot

Now use the core ChartBook loop: **run** to build and verify outputs, **commit** your code, and **snapshot** to freeze the result into your store.

```bash
chartbook run
```

The first time you run a new folder, ChartBook asks you to confirm you trust it (type `y`). Then `chartbook run` executes `python src/build_chart.py` and confirms that both `_data/walks.parquet` and `_output/random_walks.html` were created.

Next, commit your code and take a snapshot:

```bash
git add -A
git commit -m "First pipeline"
chartbook snapshot
```

```text
my_pipeline at ad2f29a: 2 asset(s) in the store
Snapshot made: 5 files, 18.2 KB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
No catalog yet, to show it in.
Create one over your store at /Users/you/.chartbook/store? [Y/n]:
```

Press **Enter** to create your local catalog over `~/.chartbook/store` (ChartBook only asks once).

## 5. Open your catalog

```bash
chartbook catalog open
```

ChartBook builds your catalog website (confirm with **Enter** when prompted) and opens it in your browser.

```{image} _static/screenshots/quickstart-site-light.png
:alt: The catalog site showing the pipeline README, charts, and dataframes in the sidebar
:class: only-light cb-screenshot
:align: center
```

```{image} _static/screenshots/quickstart-site-dark.png
:alt: The catalog site showing the pipeline README, charts, and dataframes in the sidebar
:class: only-dark cb-screenshot
:align: center
```

Click **Two Random Walks** to inspect the chart page, then click the **Random Walks** dataframe link:

```{image} _static/screenshots/quickstart-chart-light.png
:alt: The chart page showing the interactive plot, write-up, and verified provenance table
:class: only-light cb-screenshot
:width: 560px
:align: center
```

```{image} _static/screenshots/quickstart-chart-dark.png
:alt: The chart page showing the interactive plot, write-up, and verified provenance table
:class: only-dark cb-screenshot
:width: 560px
:align: center
```

```{image} _static/screenshots/quickstart-dataframe-light.png
:alt: The dataframe page showing a data glimpse, columns, row count, and content hash
:class: only-light cb-screenshot
:width: 560px
:align: center
```

```{image} _static/screenshots/quickstart-dataframe-dark.png
:alt: The dataframe page showing a data glimpse, columns, row count, and content hash
:class: only-dark cb-screenshot
:width: 560px
:align: center
```

## What you just unlocked

- **Your agents can now discover and load this data.** Run `chartbook ls` or `chartbook get-docs my_pipeline:walks` in any terminal—or run `chartbook install agents` to teach Claude Code, Cursor, and other coding agents automatically.
- **Other pipelines can depend on it like a package.** Any project can now call `data.load("my_pipeline:walks")` and get these exact, hash-verified bytes without touching this folder.
- **Every number has an audit trail.** Change the random seed in `src/build_chart.py`, run `chartbook run`, commit, and `chartbook snapshot`—the chart, data glimpse, and hashes update together while keeping the old version intact.

## The four everyday commands

You just used almost everything you need day to day:

| Command | When you use it |
|---|---|
| `chartbook run` | Build your pipeline, pin any new dependencies, and verify outputs |
| `chartbook snapshot` | Freeze a committed build into your store for other pipelines and the catalog |
| `chartbook pin --update` | Pull the latest snapshots from upstream pipelines you depend on |
| `chartbook catalog open` | Build (if needed) and open the catalog in your browser |

:::{tip} Want a batteries-included project template?
This Quickstart stayed minimal on purpose. If you want a ready-made project with a `doit` task runner, example notebooks, and pre-wired data sources (FRED, Fed yield curve, OFR, Bloomberg, CRSP), run `chartbook init`—see {doc}`guide/starting-a-project`.
:::

## Next steps

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} {octicon}`hubot;1.4em` Working with AI Agents
:link: guide/agents
:link-type: doc
Run `chartbook install agents` and turn your catalog into a living skills layer for your coding agents.
:::

:::{grid-item-card} {octicon}`repo-forked;1.4em` Linking Pipelines Together
:link: guide/depending-on-pipelines
:link-type: doc
Depend on another pipeline's snapshot, lock versions in `chartbook.lock`, and update on your schedule.
:::

:::{grid-item-card} {octicon}`book;1.4em` Explore a Real Catalog
:link: tutorials/explore-a-catalog
:link-type: doc
Clone and connect three public-data pipelines, browse their versions, and trace a model back to its source.
:::

:::{grid-item-card} {octicon}`file-directory;1.4em` Start from the Full Template
:link: guide/starting-a-project
:link-type: doc
Use `chartbook init` to scaffold a full project with `doit`, notebooks, and built-in data pullers.
:::

::::
