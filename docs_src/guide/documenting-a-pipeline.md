# Documenting a Pipeline

A pipeline is a project that produces artifacts: parquet files, chart HTML, notebooks, models.
ChartBook does not build them. You build them however you like, and `chartbook.toml` says what they
are, where they live and how they fit together. `chartbook docs build` renders that into a site.

```toml
[project]
name = "Yield Curve"
description = "Zero-coupon yield curve estimates and repo rates"

[scripts]
build = "doit"

[dataframes.repo_public]
name = "Public Repo Data"
path = "./_data/repo_public.parquet"
date_col = "date"
sources = ["FRED", "Office of Financial Research"]
docs = "Overnight repo rates and volumes, daily, from 2018."

[charts.repo_rates]
name = "Repo Rates"
dataframe = "repo_public"
path = "./_output/repo_rates.html"
docs_path = "./docs_src/charts/repo_rates.md"
```

```console
$ chartbook run            # your build script writes _data/ and _output/
$ chartbook docs build     # the site, in ./docs
$ chartbook docs open
```

The field-by-field reference is {doc}`../reference/configuration`. This page is the shape.

## Layout

```text
my-pipeline/
├── chartbook.toml     # the manifest
├── README.md          # required; the site's front page
├── dodo.py            # or any other way of running your pipeline
├── src/               # code that produces the artifacts
├── _data/             # dataframes ([dataframes] point here)
├── _output/           # chart HTML and executed notebooks
└── docs_src/
    ├── charts/        # chart write-ups (docs_path)
    ├── dataframes/    # dataframe write-ups
    └── site/          # extra site pages, merged in
```

Only `chartbook.toml` and `README.md` are fixed names. Every entry carries its own `path`, so the
artifacts can live wherever your build puts them, and your code asks for the path by name instead
of repeating it ({doc}`reading-and-writing-data`).

## Project and build

Every `[project]` field is optional: `name` defaults to the folder's name, `maintainer` to the first
contributor, the pipeline's `id` to its git remote and folder. `[scripts] build` is the command that
builds the artifacts, shown on the pipeline's page and run by `chartbook run` in the pipeline's
folder. A multi-line value is one shell script, so an environment activation carries into later
lines. Make it the command that builds the pipeline, not a note about the environment.

## Dataframes

A dataframe is a data file and its provenance. The page shows when the data was last updated, your
write-up, a **glimpse** of the first rows and the row count, and the manifest table.

```toml
[dataframes.repo_public]
path = "./_data/repo_public.parquet"
date_col = "date"
sources = ["FRED"]
docs_path = "./docs_src/dataframes/repo_public.md"
```

Exactly one of `docs_path` (a Markdown file) or `docs` (inline Markdown) supplies the write-up. The
ending says the format, parquet, CSV, JSON lines or Arrow IPC, unless `format` says otherwise.

A dataset of many files is a folder, which polars writes with `partition_by` and reads with its
Hive keys as columns:

```toml
[dataframes.articles]
path = "./_data/articles"
docs = "One file a year, year=2024/part-0.parquet."
```

A dataframe can also be a table, or a query, in a database the pipeline names. It gets the same
page, its columns and first rows read from the engine, and `data.load("slopes")` runs the query:

```toml
[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/local.duckdb"

[dataframes.slopes]
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope from fed_yield_curve"
docs = "The 10-year yield less the 2-year, computed when read."
```

Provenance fields, `providers`, `license`, `access_types`, `pull_method` and the rest, exist for
governance-minded catalogs; the reference lists them. A column can be documented on its own under
`[dataframes.repo_public.series.sofr]`.

## Charts

A chart is an HTML file and an entry. The HTML usually comes from {doc}`plotting`, but any HTML
works: ChartBook embeds it in an iframe. `dataframe` names the entry that feeds it, which is an
error to leave dangling. The page assembles the chart, your write-up and the spec tables, and says
under its title how fresh it is: "Chart updated 2 days ago · Data updated 2 days ago".

## Notebooks

```toml
[notebooks.exploration]
path = "_output/01_exploration.ipynb"
docs = "Exploratory analysis of curve-fitting residuals."
```

Notebooks render as pages, pre-executed; ChartBook does not run them. The title is the notebook's
first heading unless `name` says otherwise.

## Models

```toml
[models.rate_forecaster]
path = "./_models/rate_forecaster.joblib"
trained_on = ["treasury_rates"]
metrics_path = "./_output/rate_forecaster_metrics.json"
docs_path = "./docs_src/models/rate_forecaster.md"
```

Your training code writes the model file and a small JSON file of scores; ChartBook reads the
scores and never looks inside the model. The page shows the scores, the data it was trained on,
and whether that data has moved since. When a build is ready, `chartbook run --snapshot` keeps the
model as a **version**, named by the start of its hash; a label under `[models.rate_forecaster.aliases]`
names the one in use, and `models.path("rate_forecaster@champion")` reads it.

## Files that are not tables

An archive of gzipped JSON lines, a corpus of filings, images, a vendor's zip kept byte for byte:
declare it under `[files]`, with the same provenance fields a dataframe has.

```toml
[files.earnings_releases]
path = "./_data/archive/EARNINGS_RELEASE_*.jsonl.gz"
sources = ["Vendor API"]
docs = "The API's earnings releases, one file a quarter, as sent."
```

The page lists how many files there are and of which types, the first of them with their sizes,
and a short preview of one. `assets.files("file/earnings_releases")` gives the files to your code,
sorted; `assets.index(...)` a table of them to choose from before opening any.

## Notes and your own pages

`[notes]` entries add standalone Markdown documents. Any Markdown in `docs_src/site/` merges into
the site as it is. Both are MyST Markdown: regular Markdown plus admonitions, math and
cross-references.

## Checking your work

`chartbook check` compares the manifest and the files it names against its `[policy]` (a catalog's
with `--policy`, or the default list), and warns about a dependency declared and not pinned. `chartbook docs build` fails when a `path` or
`docs_path` points at nothing, naming the entry; a new project that has built nothing yet is
rendered with each output shown as not built, and the build warns. While writing,
`chartbook docs build -f --watch` rebuilds on every save.

Every dataframe, chart, model and files page ends with a **provenance panel**, written from the
build's index and nothing else: the asset's hash, size, rows and columns; what it was made from, at
which hash, pinned from which snapshot; and what is made from it. The pipeline's page lists each
dependency and what the lockfile pins it to. {doc}`how-the-build-works` says where all of it comes
from.
