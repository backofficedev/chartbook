# Documenting a Pipeline

A pipeline is a project that produces artifacts — parquet files, chart HTML, notebooks. ChartBook doesn't run the pipeline; you build the artifacts however you like (`doit`, `make`, plain scripts) and `chartbook.toml` describes what they are, where they live, and how they fit together. `chartbook docs` then renders that description into a website.

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

Every `[project]` field is optional with sensible defaults (`name` defaults to the directory name, `copyright` to the current year, `maintainer` to the first contributor; the pipeline `id`'s scope is inferred from the git `origin` remote when `id` and `repo_url` are unset):

```toml
[project]
name = "Yield Curve"
description = "Zero-coupon yield curve estimates and repo rates"
maintainer = "Jane Doe"
build = """
conda activate myenv
doit
"""
```

`build` records how to regenerate the artifacts. It has shell-script semantics — a multi-line value is one script, so environment activation carries into later lines. It's displayed on the pipeline's page (and reserved for a future `chartbook run`).

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

A dataframe is a parquet artifact plus provenance:

```toml
[dataframes.repo_public]
name = "Public Repo Data"
description = "Overnight repo rates and volumes"
sources = ["FRED", "Office of Financial Research"]
path = "./_data/repo_public.parquet"
date_col = "date"
docs_path = "./docs_src/dataframes/repo_public.md"
```

The same `docs_path`/`docs` rule applies. The generated page shows when the data was last updated, your write-up, a **glimpse** (schema and row count read from the parquet at build time), and a manifest table. Provenance fields — `providers`, `license`, `access_types`, `pull_method`, and friends — exist for governance-minded catalogs; see the reference.

For hive-partitioned datasets, `path` takes a glob:

```toml
path = "./_data/market_data/**/*.parquet"
```

Glob-path dataframes load as polars LazyFrames only, with partition columns appearing automatically; see {doc}`catalogs-and-data`.

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

## Depending on another pipeline

If the pipeline uses another pipeline's data, say which pipeline and where it is:

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }

[models.rate_forecaster]
path = "./_models/rate_forecaster.joblib"
trained_on = ["fed_yield_curve:treasury_rates"]
```

`chartbook check` then confirms that the other pipeline is there and that it declares that dataframe.

**The other pipeline's owner says when a build is ready.** In its folder, with everything committed:

```console
$ chartbook run --snapshot     # build it, and copy what it built into the store, labelled with the commit
```

That is a snapshot, and it is the only thing of theirs you ever read. You never read their folder. (`chartbook run` and then `chartbook snapshot` are the same two steps, apart.)

Then freeze what you depend on, and read it by name:

```console
$ chartbook pin          # pin their newest snapshot; write chartbook.lock
$ git add chartbook.lock
```

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates")     # the pinned copy
path = data.path("fed_yield_curve:treasury_rates")      # or just where it is
```

What you get is the build they declared ready, not whatever is in `../fed_yield_curve/_data/` this minute. They can rebuild, or be half-way through a change, and your results do not move. When they have made a newer snapshot and you want it:

```console
$ chartbook update       # move the pins; chartbook.lock shows the change in a diff
```

| Who | Does | When |
|---|---|---|
| The other pipeline's owner | `chartbook run --snapshot` | When a build is ready for others |
| You | `chartbook pin`, once | To start depending on it |
| You | `chartbook update` | When you want their newer snapshot |

The `rate_forecast` example does exactly this, with a model trained on the `yield_curve` example's data. {ref}`[dependencies] <dependencies>` and {ref}`chartbook snapshot <chartbook-snapshot>` have every detail.

### Building it

Say how the pipeline is built, in its `chartbook.toml`:

```toml
[scripts]
build = "doit"
```

Then one command pins what you depend on, if nothing is pinned yet, and builds:

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
  From its snapshot at 4f2a91c, made 2026-10-13 18:22 UTC.
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

`chartbook run` does not build `../fed_yield_curve`, and does not read it. That folder is somebody's work, perhaps in the middle of a change. Whoever owns it builds it and makes the snapshot.

It never moves a pin either. If the other pipeline has a newer snapshot, yours is still built against the one you pinned, and the command tells you so. `chartbook update` is what moves a pin. See {ref}`chartbook run <chartbook-run>`.

A dependency can also be a git repository, `{ git = "https://…", rev = "v1.2" }`, for one that is not on your disk. `chartbook pin` clones it, and can pin only what that repository keeps in git: reference data and models that are committed. For data that the other pipeline builds, use `chartbook run`, which builds it once in a clean copy of that commit.

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

Data is what gets passed around most, so it gets the short spelling. Each kind has its own names: a dataframe and a chart may both be called `gdp`, and they are `gdp` and `chart/gdp`.

In Python the kind can be an argument instead, which reads better when the name is in a variable. It says what you expect, so it fills in a missing kind and rejects a different one:

```python
assets.path("rates_over_time", kind="chart")    # the same as "chart/rates_over_time"
assets.path("chart/rates_over_time", kind="note")   # error: that names a chart
```

`data.path(name)` is `assets.path(name, kind="dataframe")`. It answers for dataframes only, so a mistyped name cannot hand back a chart's HTML where a parquet file was meant. `models.path(name)` is the same for models.

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

These names are the local end of a longer address — `scope/pipeline:kind/name#part@rev` — that will also reach other pipelines' assets, columns inside a dataframe, and versions. Only the local form works today; {doc}`../design/references` has the whole grammar.

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

While you are writing, `chartbook docs -f --watch` rebuilds the site each time you save, redoing only the pages that changed; refresh the browser to see it. ({doc}`how-the-build-works` explains what it skips.)

`chartbook docs` is strict by default: if a `path` or `docs_path` points at a file that doesn't exist, the build fails and names both the missing file and the manifest entry referencing it. In a catalog, `--no-strict` downgrades this to a warning that skips the affected pipeline; a single pipeline has nothing left to build once skipped, so there it is still an error. Two more inspection tools:

- Unknown `[project]` keys warn with a did-you-mean suggestion rather than becoming silently dead metadata.
- `chartbook create-data-glimpses` writes `data_glimpses.md` — schema, null rates, sample rows, and summary stats for every dataframe declared in `chartbook.toml`, whatever tool builds them.

Once the pipeline builds cleanly, register it in a catalog: {doc}`catalogs-and-data`.
