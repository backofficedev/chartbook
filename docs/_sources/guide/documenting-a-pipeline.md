# Documenting a Pipeline

A pipeline is a project that produces artifacts — parquet files, chart HTML, notebooks. ChartBook is not the tool that builds them; you build the artifacts however you like (`doit`, `make`, plain scripts), and `chartbook.toml` describes what they are, where they live, how they fit together, and the command that builds them. `chartbook docs generate` then renders that description into a website, and `chartbook run` runs the command.

This page covers the describing. For the field-by-field reference, see {doc}`../reference/configuration`.

## Layout

The conventional layout (what `chartbook init` scaffolds):

```
my-pipeline/
├── chartbook.toml     # the manifest — this page's subject
├── README.md          # required; becomes the site's front page
├── dodo.py            # or any other way of running your pipeline
├── src/               # code that produces the artifacts
├── _data/             # parquet files ([dataframes] point here)
├── _output/           # chart HTML and executed notebooks ([charts] and [notebooks] point here)
└── docs_src/
    ├── charts/        # chart write-ups (referenced via docs_path)
    ├── dataframes/    # dataframe write-ups
    └── site/          # optional extra site pages, merged in automatically
```

Only `chartbook.toml` and `README.md` are fixed names. The rest is convention — each manifest entry carries its own `path`, so artifacts can live wherever your build puts them.

## Project metadata

Every `[project]` field is optional with sensible defaults (`name` defaults to the directory name, `copyright` to the current year, `maintainer` to the first contributor; the pipeline's `id`, when unset, comes from its `repo_url` (or else its git `origin` remote) and its folder, as {ref}`Pipeline Identity <pipeline-identity>` says):

```toml
[project]
name = "Yield Curve"
description = "Zero-coupon yield curve estimates and repo rates"
maintainer = "Jane Doe"

[scripts]
build = """
conda activate myenv
doit
"""
```

`build`, under `[scripts]`, is the command that builds the artifacts. It has shell-script semantics — a multi-line value is one script, so environment activation carries into later lines (on Windows it is a batch file, where a line that runs another batch file, such as `conda activate`, must begin with `call`, or nothing after it runs). It is shown on the pipeline's page, and it is run: `chartbook run` runs it in the pipeline's directory, and `chartbook build` runs it and then renders the site, which `chartbook docs generate` does alone. Make it the command that builds the pipeline, not a note about the environment. `build` under `[project]`, the old place, is still read and means the same thing; give it in one place. See {ref}`[scripts] <scripts>` in the reference and {ref}`chartbook run <chartbook-run>`.

## Charts

A chart is an HTML file plus an entry describing it. The HTML usually comes from {doc}`plotting`, but any HTML works — ChartBook embeds it in an iframe.

```toml
[charts.repo_rates]
name = "Repo Rates"
description = "SOFR and EFFR overnight rates"
dataframe = "repo_public"                     # which [dataframes.*] entry feeds it
path = "./_output/repo_rates.html"
docs_path = "./docs_src/charts/repo_rates.md"
tags = ["Repo", "Short Term Funding"]
frequency = "Daily"
units = "Percent"
```

Two rules:

- `dataframe` names the entry in `[dataframes]` that feeds the chart; referencing a missing one is an error.
- Exactly one of `docs_path` (a markdown file) or `docs` (inline markdown) supplies the write-up.

The write-up is the part only you can provide: what the chart shows, how to read it, caveats. The generated chart page assembles the interactive chart, your write-up, and auto-generated spec tables (chart metadata, dataframe manifest, pipeline manifest). Under its title it says how fresh it is — "Chart updated 2 days ago · Data updated 2 days ago" — so a reader can tell a stale chart from a current one without asking. (When the pipeline's code last changed is on the pipeline's front page.) Fields you leave out simply don't appear; the full metadata vocabulary — publication tracking, clearance dates, release timing — is in {doc}`../reference/configuration`.

## Dataframes

A dataframe is a data file (parquet, or CSV, JSON lines or Arrow IPC) plus provenance:

```toml
[dataframes.repo_public]
name = "Public Repo Data"
description = "Overnight repo rates and volumes"
sources = ["FRED", "Office of Financial Research"]
path = "./_data/repo_public.parquet"
date_col = "date"
docs_path = "./docs_src/dataframes/repo_public.md"
```

The same `docs_path`/`docs` rule applies. The generated page shows when the data was last updated, your write-up, a **glimpse** (schema and row count read from the file at build time), and a manifest table. Provenance fields — `providers`, `license`, `access_types`, `pull_method`, and friends — exist for governance-minded catalogs; see the reference.

For hive-partitioned datasets, `path` takes a glob:

```toml
path = "./_data/market_data/**/*.parquet"
```

A glob-path dataframe loads as one frame, in every `format=` `data.load` offers, with partition columns appearing automatically; see {doc}`catalogs-and-data`. A dataframe's file may be CSV, JSON lines or Arrow IPC as well as parquet, as its path's ending or its `format` key says ({ref}`formats`).

A dataframe can also be a table, or a query, in a database the pipeline names:

```toml
[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/local.duckdb"

[dataframes.slopes]
name = "Yield Curve Slopes"
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope from fed_yield_curve"
docs = "The 10-year yield less the 2-year, computed when read."
```

It gets the same page, with its columns and first rows read from the engine, and `data.load("slopes")` runs the query. {ref}`[sources] <sources>` has every field. The `yield_curve` example has one.

## Notebooks

```toml
[notebooks.exploration]
description = "Exploratory analysis of curve-fitting residuals"
path = "_output/01_exploration.ipynb"
publishable = true
```

Notebooks render as pages, pre-executed — ChartBook does not run them. The title comes from the notebook's first `# Heading`; set `name` to override. `publishable = true` includes the notebook when you run `chartbook publish`.

## Models

If the pipeline trains a model, declare it, and it gets a page of its own: its write-up, its scores, and links to the data it was trained on.

```toml
[models.rate_forecaster]
name = "Rate Forecaster"
description = "Forecasts the 10-year Treasury yield one month ahead."
path = "./_models/rate_forecaster.joblib"
trained_on = ["treasury_rates"]
metrics_path = "./_output/rate_forecaster_metrics.json"
docs_path = "./docs_src/models/rate_forecaster.md"
```

Your training code writes the model file and a small JSON file of scores; ChartBook reads both and never looks inside the model. {doc}`../reference/configuration` has every field, and the `yield_curve` example trains a small one end to end.

**Versions.** When a build of the model is ready, `chartbook run --snapshot` keeps it as a version, named by the start of its hash. Give the one in use a label, and have the code that uses it ask for the label:

```toml
[models.rate_forecaster.aliases]
champion = "7f3a9c2e41b0"
```

```python
model = joblib.load(models.path("rate_forecaster@champion"))
```

Promoting a newer version is changing that one line. See {ref}`Versions and labels <model-versions>`.

## Files that are not tables

Some of what a pipeline keeps is not a table: an archive of gzipped JSON lines kept in its source's format, a corpus of filings as HTML, PDFs, images, NumPy arrays, a vendor's zip kept byte for byte. Declare it under `[files]`, with the same fields a dataframe has to say where it came from and who may use it:

```toml
[files.earnings_releases]
description = "The data API's earnings releases, one file a quarter, as the API sends them."
path = "./_data/archive/EARNINGS_RELEASE_*.jsonl.gz"
sources = ["Vendor API"]
license = "Licensed to the department"
docs_path = "./docs_src/files/earnings_releases.md"
```

It gets a page with its write-up, how many files it has and of which types, the first of them with their sizes, and a short preview of one: the first lines of a text or JSON-lines file, or a thumbnail of an image. ChartBook never reads it otherwise. Your code reads the files, which `assets.files` gives, sorted:

```python
import gzip, json
from chartbook import assets

for path in assets.files("file/earnings_releases"):
    with gzip.open(path, "rt") as f:
        releases = [json.loads(line) for line in f]
```

`assets.index("file/earnings_releases")` is a table of the files, with their sizes and hashes, to pick from with polars before opening any. Another pipeline reads them the same way, as pinned: `assets.files("filings:file/earnings_releases")`. See {ref}`[files] <files>`.

## Depending on another pipeline

A pipeline that uses another pipeline's data declares it in `[dependencies]`, pins a **snapshot**
of it with `chartbook pin`, and reads the pinned copy by name. It does not read the other
pipeline's folder, except, with a loud warning, before there is any snapshot of it. {doc}`depending-on-pipelines` has the whole of it: snapshots, pins, the
lockfile, `chartbook run`, and a diagram.

## Notes and custom pages

`[notes]` entries add standalone markdown documents to the site:

```toml
[notes.methodology]
path = "./docs_src/methodology.md"
```

And any markdown placed in `docs_src/site/` merges into the site automatically (that's the default `site_dir`; auto-generated pages live in a separate `cb/` directory, so nothing collides). Write-ups and site pages are MyST markdown — regular markdown plus admonitions, math, and cross-references; see the [MyST syntax guide](https://myst-parser.readthedocs.io/en/latest/syntax/typography.html).

## Asking the manifest for a path

Once `chartbook.toml` says where a dataframe or chart lives, your code does not have to say it again. `data.path()` returns the `path` declared for a dataframe of the current pipeline, and `assets.path()` does the same for anything the pipeline declares:

```python
# dodo.py — declaring what each task reads and writes
from chartbook import assets, data

def task_merge():
    return {
        "file_dep": [data.path("treasury_rates")],
        "targets": [data.path("merged_rates")],
        "actions": ["python src/merge.py"],
    }

def task_chart():
    return {
        "file_dep": [data.path("merged_rates")],
        "targets": [assets.path("chart/rates_over_time")],
        "actions": ["python src/chart.py"],
    }

# src/merge.py — doing the work
df.to_parquet(data.path("merged_rates"))
```

### How an asset is named

A dataframe is named by its key in `[dataframes]`, and nothing more. Any other asset has its kind in front:

| You write | It means |
|---|---|
| `merged_rates` | `[dataframes.merged_rates]` |
| `chart/rates_over_time` | `[charts.rates_over_time]` |
| `notebook/analysis` | `[notebooks.analysis]` |
| `note/methodology` | `[notes.methodology]` |
| `model/rate_forecaster` | `[models.rate_forecaster]` |
| `file/earnings_releases` | `[files.earnings_releases]` |

Data is what gets passed around most, so it gets the short spelling. Each kind has its own names: a dataframe and a chart may both be called `gdp`, and they are `gdp` and `chart/gdp`.

In Python the kind can be an argument instead, which reads better when the name is in a variable. It says what you expect, so it fills in a missing kind and rejects a different one:

```python
assets.path("rates_over_time", kind="chart")    # the same as "chart/rates_over_time"
assets.path("chart/rates_over_time", kind="note")   # error: that names a chart
```

`data.path(name)` is `assets.path(name, kind="dataframe")`. It answers for dataframes only, so a mistyped name cannot hand back a chart's HTML where a parquet file was meant. `models.path(name)` is the same for models, and `files.path(name)` for files assets. A path may be a folder or a glob; `assets.files(ref)` gives the files themselves, sorted, for any kind.

The enclosing `chartbook.toml` is found by walking up from the calling file (then from the working directory), so the call works from a script, a `dodo.py` or a notebook alike. The path comes back absolute, and nothing checks that the file exists — which is what lets it name a target that has not been built yet.

Asking for a name the manifest does not declare fails on the spot, with the table to add:

```text
No dataframe named 'merged_rates' is declared in /work/repo/chartbook.toml.

To register it, add a table to that file, for example:

    [dataframes.merged_rates]
    path = "./_data/merged_rates.parquet"
```

`chartbook path` gives the same answer on the command line, which is how Make, R, Stata or a shell script reach it:

```makefile
TREASURY := $(shell chartbook path treasury_rates)
MERGED   := $(shell chartbook path merged_rates)
CHART    := $(shell chartbook path chart/rates_over_time)

$(MERGED): $(TREASURY)
	Rscript src/merge.R
```

```{note}
This is a convenience, never a requirement. A pipeline that writes straight to `_data/merged_rates.parquet` — from Python, R, Stata or a shell script — works exactly as before. The manifest is the contract; `data.path()` and `assets.path()` only save you from stating it twice.
```

These names are the local end of a longer address, `scope/pipeline:kind/name#part@rev`. With a pipeline in front, `fed_yield_curve:treasury_rates`, it reaches another pipeline's asset, as pinned. With `@`, `model/rate_forecaster@champion`, it reaches a version of a model. `#` names one column, `treasury_rates#dgs10`, so that it can be documented; it does not load the column, which is for polars or SQL to do. {doc}`../design/references` has the whole grammar.

For files that are *not* assets — a partial download, a cache between two steps — `data.scratch()` gives you a throwaway directory instead:

```python
tmp = data.scratch() / "raw_download.csv"     # <pipeline>/_data/_scratch/raw_download.csv
```

It is created on first use, ignores itself in git, and is never documented, published or treated as an input. Delete it whenever you like. (Avoid declaring a dataframe whose `path` is a glob over all of `_data/`, such as `./_data/**/*.parquet`; it would sweep scratch files in.)

A name with a pipeline in front, `data.path("fed_yield_curve:treasury_rates")`, is another pipeline's asset: the pinned copy of it, as described under "Depending on another pipeline" above. That path is for reading only. To find a dataframe through a catalog instead, from a notebook that belongs to no pipeline, use `data.get_data_path()` ({doc}`catalogs-and-data`).

## Finding project paths from code

Pipeline scripts often need paths that work from any working directory, including notebooks. For files the manifest does not declare, `chartbook.env` helps:

```python
import chartbook

BASE_DIR = chartbook.env.get_project_root()   # searches upward for .git / pyproject.toml / .env
DATA_DIR = BASE_DIR / "_data"
API_KEY = chartbook.env.get("FRED_API_KEY", default="")  # .env file or environment
```

## Checking your work

While you are writing, `chartbook docs generate -f --watch` rebuilds the site each time you save, redoing only the pages that changed; refresh the browser to see it. ({doc}`how-the-build-works` explains what it skips.)

`chartbook docs generate` is strict by default: if a `path` or `docs_path` points at a file that doesn't exist, the build fails and names both the missing file and the manifest entry referencing it. The exception is a lone pipeline (not a catalog, where it is an error) that has built none of its data, charts, notebooks and models yet, as a new project or a fresh clone has not: its site is rendered with each of them shown as not built, and the command warns, listing them. Given `--strict`, that is an error after all, which is what CI wants after a build; and `chartbook build`, which has just run the build, makes no such exception. In a catalog, `--no-strict` downgrades a missing file to a warning that skips the affected pipeline; a single pipeline has nothing left to build once skipped, so there it is still an error. Two more inspection tools:

- Unknown `[project]` keys warn with a did-you-mean suggestion rather than becoming silently dead metadata.
- `chartbook create-data-glimpses` writes `data_glimpses.md` — schema, null rates, sample rows, and summary stats for every dataframe declared in `chartbook.toml`, whatever tool builds them.

Once the pipeline builds cleanly, register it in a catalog: {doc}`catalogs-and-data`.

## The provenance panel

Every dataframe, chart, model and files page carries a **Provenance** section, before its manifest sections, written from the build's `index.json` and nothing else: what the asset is and where it is; its content hash, size, rows and columns; which pipeline built it and with what script; what it was made from, at which hash, pinned from which snapshot of which commit, and whether that has moved since a model was trained; and what is made from it. It is the answer to "which data, exactly, is behind this page", for a reader and for an auditor, and it changes only when the index does.

The pipeline's own page answers the same question for the whole pipeline. Under **Dependencies** it lists each pipeline in its `[dependencies]`, as declared, and what `chartbook.lock` pins it to: the snapshot's commit and when it was made, or, for one pinned from its repository (a `git` dependency), that repository's commit; a dependency with no pin yet says so. In a catalog that shows the other pipeline, each entry links its page, in the snapshot pinned when the catalog has that version.
