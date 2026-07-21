# Documenting a Pipeline

A pipeline is a project that produces artifacts — parquet files, chart HTML, notebooks. ChartBook doesn't run the pipeline; you build the artifacts however you like (`doit`, `make`, plain scripts) and `chartbook.toml` describes what they are, where they live, and how they fit together. `chartbook build` then renders that description into a website.

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

The write-up is the part only you can provide: what the chart shows, how to read it, caveats. The generated chart page assembles the interactive chart, your write-up, and auto-generated spec tables (chart metadata, dataframe manifest, pipeline manifest). Fields you leave out simply don't appear; the full metadata vocabulary — publication tracking, clearance dates, release timing — is in {doc}`../reference/configuration`.

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

The same `docs_path`/`docs` rule applies. The generated page shows your write-up, a **glimpse** (schema and row count read from the parquet at build time), and a manifest table. Provenance fields — `providers`, `license`, `access_types`, `pull_method`, and friends — exist for governance-minded catalogs; see the reference.

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

## Notes and custom pages

`[notes]` entries add standalone markdown documents to the site:

```toml
[notes.methodology]
path = "./docs_src/methodology.md"
```

And any markdown placed in `docs_src/site/` merges into the site automatically (that's the default `site_dir`; auto-generated pages live in a separate `cb/` directory, so nothing collides). Write-ups and site pages are MyST markdown — regular markdown plus admonitions, math, and cross-references; see the [MyST syntax guide](https://myst-parser.readthedocs.io/en/latest/syntax/typography.html).

## Finding project paths from code

Pipeline scripts often need paths that work from any working directory, including notebooks. `chartbook.env` helps:

```python
import chartbook

BASE_DIR = chartbook.env.get_project_root()   # searches upward for .git / pyproject.toml / .env
DATA_DIR = BASE_DIR / "_data"
API_KEY = chartbook.env.get("FRED_API_KEY", default="")  # .env file or environment
```

## Checking your work

`chartbook build` is strict by default: if a `path` or `docs_path` points at a file that doesn't exist, the build fails and names both the missing file and the manifest entry referencing it. `--no-strict` downgrades this to a warning that skips the affected pipeline. Two more inspection tools:

- Unknown `[project]` keys warn with a did-you-mean suggestion rather than becoming silently dead metadata.
- `chartbook create-data-glimpses` scans your `dodo.py` targets and writes `data_glimpses.md` — schema, null rates, sample rows, and summary stats for every data file your tasks produce.

Once the pipeline builds cleanly, register it in a catalog: {doc}`catalogs-and-data`.
