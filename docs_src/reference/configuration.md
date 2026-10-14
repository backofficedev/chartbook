# Configuration Guide

chartbook uses a TOML configuration file (`chartbook.toml`) to define your project metadata, charts, dataframes, and pipelines. This page is the reference for **format v2**; the reasoning behind the design lives in {doc}`../design/toml-format-v2`.

## Configuration File Structure

A **pipeline** manifest has one metadata table plus entity sections:

```toml
[project]          # Project metadata (all fields optional)
[charts]           # Chart definitions
[dataframes]       # Dataframe definitions
[notebooks]        # Jupyter notebook references
[notes]            # Additional documentation notes
[models]           # Trained models
[dependencies]     # Other pipelines this one reads from
```

A **catalog** manifest has the metadata table plus a registry:

```toml
[project]          # Project metadata
[pipelines]        # Registered pipelines (scoped keys)
[policy]           # Optional: required-field policy for member pipelines
```

## Project Types

You almost never need to declare the type — it is inferred from structure:

- A `[pipelines]` registry table present → **catalog**
- Otherwise → **pipeline**

An explicit `type = "pipeline"` or `type = "catalog"` in `[project]` is allowed. A file whose explicit type contradicts its structure (e.g. `type = "pipeline"` alongside `[pipelines]`) is a hard error asking you to fix one or the other.

## The `[project]` Table

Every field is optional. Types and defaults:

| Key | Type | Default |
|-----|------|---------|
| `type` | `"pipeline"` or `"catalog"` | inferred (see above) |
| `id` | `scope/name` or bare `name` | derived: scope from the git remote, name from the directory |
| `name` | string | directory name |
| `description` | string | `""` |
| `maintainer` | string | first entry of `contributors` |
| `contributors` | array of strings | `[]` |
| `repo_url` | string | the repo's git `origin` remote, as a web address; `""` if there is none |
| `site_url` | string | `file://` path to the local built docs |
| `readme` | path | `"./README.md"` |
| `copyright` | string | current year |
| `logo` | path | bundled default |
| `favicon` | path | bundled default |
| `os_compatibility` | array of strings | `[]` |
| `build` | string (multi-line allowed) | `""` |
| `site_dir` | path | `"./docs_src/site/"` when that directory exists |
| `enable_data_download` | bool | `false` |

Unknown keys in `[project]` produce a warning naming the closest known key, so typos don't silently become dead metadata.

A fully populated pipeline:

```toml
[project]
name = "CRSP Treasury"
description = "Treasury Securities Data from CRSP"
maintainer = "Jeremy Bejarano"
contributors = ["Jeremy Bejarano"]
repo_url = "https://github.com/ftsfr/crsp_treasury"
os_compatibility = ["Windows", "Linux", "macOS"]
build = """
doit
"""
```

The **minimal** valid pipeline manifest is an empty file — its presence alone marks a directory as a chartbook pipeline. In practice you'll usually want at least:

```toml
[project]
name = "My Pipeline"
```

### Build commands

`build` is a single string with **shell-script semantics**: a multi-line value is one script, so environment state carries across lines:

```toml
[project]
build = """
module load anaconda3/2024.02
conda activate myenv
doit
"""
```

Today the field is rendered on the pipeline's documentation page; the script semantics mean a future `chartbook run` can execute it as-is.

## Pipeline Identity

Every pipeline has a canonical ID, ideally scoped: `scope/name` (e.g. `ftsfr/crsp_treasury`). It is derived automatically — scope from the repo's git `origin` remote (or `repo_url`), name from the directory name — or set explicitly with `id` in `[project]`. Anywhere a pipeline reference is accepted (`data.load`, `chartbook data get-path`, `chartbook data get-docs`), three forms work:

```python
data.load(pipeline="crsp_treasury", ...)                          # bare, if unambiguous
data.load(pipeline="ftsfr/crsp_treasury", ...)                    # canonical
data.load(pipeline="https://github.com/ftsfr/crsp_treasury", ...) # URL, normalized
```

If a bare name matches pipelines in more than one scope, chartbook errors and lists the candidates. See {doc}`../design/toml-format-v2` for why identity works this way.

Two extensions of the ID grammar are **reserved**: the parser recognizes them and refuses them with a "not yet supported" error, so they can be given meaning later without changing what any existing ID means.

| Reserved form | Example | For |
|---|---|---|
| `scope/name@rev` | `ftsfr/crsp_treasury@a1b2c3d` | Pinning a revision |
| `registry/scope/name` | `charthub.example/ftsfr/crsp_treasury` | Naming the registry that resolves an ID |

A registry prefix is the first of exactly three components, and looks like a host — it contains `.` or `:`, or is `localhost` (the rule Docker uses). `acme/rates` therefore means the same thing whether or not a registry ever exists, and a two-component ID is always `scope/name`, even if the scope contains a dot. See {doc}`../design/asset-graph`.

## `[pipelines]` — Catalog Registry

Catalog keys are pipeline IDs; scoped keys contain a `/` and must be quoted:

```toml
[project]
name = "My Catalog"

[pipelines."ftsfr/crsp_treasury"]
path = "../crsp_treasury"

[pipelines."ftsfr/fed_yield_curve"]
path = "../fed_yield_curve"
disabled = true                    # kept but skipped during builds

[pipelines."finm-33200/news_headlines"]
path = { unix = "/data/pipelines/news_headlines", windows = "T:/pipelines/news_headlines" }
```

Entry keys: `path` (string, or a `{ unix = ..., windows = ... }` table) and `disabled` (bool). A plain string value is shorthand for the path. `chartbook catalog add <dir>` writes the scoped key for you, derived from the target's git remote.

### Auto-discovery with `members`

For a local catalog, skip per-pipeline entries entirely and declare membership as path patterns — new projects dropped into a matched directory join the catalog automatically:

```toml
[project]
name = "My Catalog"

[pipelines]
members = [
    "../GitRepositories/ftsfr_repos/*",
    "../GitRepositories/finm33200/news_headlines",
]
disabled = ["ftsfr/sovereign_bonds"]   # switch members off by ID
exclude = ["../GitRepositories/ftsfr_repos/scratch_*"]   # optional
```

Each matched directory containing a pipeline `chartbook.toml` joins under its derived scoped ID. Glob matches skip non-pipeline directories and catalogs silently; a *literal* member path that's broken is a hard error, as are v1-format members and two members deriving the same ID — all errors explain how to fix them. Explicit entries coexist with `members` and win when they point at the same directory (useful to rename a pipeline in your catalog). `members`, `exclude`, and `disabled` are reserved keys and can't be used as bare pipeline IDs.

This is designed for the **local** catalog — publishing to a shared catalog should stay an explicit act.

(policy)=
## `[policy]` — Which Fields Are Required

The format itself is permissive; **which fields are required is a policy**, and usually your catalog's:

```toml
[policy]
mode = "warn"          # default; "strict" fails the build instead

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
models     = ["name", "trained_on", "docs"]
```

Without a `[policy]` section, chartbook's default recommended-field lists apply, warn-only. A kind you leave out of `[policy.required]` keeps its default list. In a list, `docs` means "a write-up", and is satisfied by either `docs` or `docs_path`.

A pipeline may have a `[policy]` section of its own. It says what that pipeline holds itself to when it is checked or built by itself. Inside a catalog, the catalog's policy applies and the pipeline's is ignored: whoever gathers the pipelines together decides what they must say.

To enforce a policy in CI — for a catalog or a single pipeline — run {doc}`chartbook check <cli>`, which exits nonzero on any missing required field regardless of `mode`.

## `[charts]` — Chart Definitions

```toml
[charts.revenue_trend]
name = "Revenue Trend Analysis"
description = "Monthly revenue trends with seasonal adjustments"
dataframe = "revenue_data"           # links to a [dataframes.*] entry
tags = ["Revenue", "Financial", "Monthly"]
frequency = "Monthly"
observation_period = "Month-end"
release_lag = "15 days"
release_timing = "Mid-month"
seasonal_adjustment = "X-13ARIMA-SEATS"
units = "USD Millions"
series = ["Gross Revenue", "Net Revenue"]
start_date = "1/1/2020"
mnemonic = "REV_TREND"
publications = [
    "[Q4 Report 2024, p15](https://example.com/reports/q4-2024)",
]
date_cleared_by_iv_and_v = "2025-01-15"
last_legal_clearance_date = "2025-01-15"
last_cleared_by = "Legal Team"
path = "./_output/revenue_trend.html"        # the chart's HTML file
excel_path = "./excel/revenue_trend.xlsx"    # optional Excel version
docs_path = "./docs_src/charts/revenue_trend.md"
```

Exactly one of `docs_path` (a markdown file) or `docs` (inline markdown, usually a multi-line string) is required per chart.

## `[dataframes]` — Dataframe Definitions

`path` points at the parquet artifact — a single file or a glob pattern for hive-partitioned data:

```toml
[dataframes.revenue_data]
name = "Revenue Dataset"
description = "Comprehensive revenue data with geographic breakdowns"
sources = ["Internal Sales System", "Finance Database"]
providers = ["Sales Team", "Finance Team"]
provider_links = ["https://internal.company.com/sales"]
access_types = ["Internal"]
contact_required = "No"
pre_approved = "Yes"
license = "Internal Use Only"
license_expiration = "2025-12-31"
provider_contact = "data-team@company.com"
restrictions = "Internal analytics only"
pull_method = "SQL query via Python"
tags = ["Revenue", "Sales", "Financial"]
date_col = "date"
path = "./_data/revenue_data.parquet"
excel_path = "./_data/revenue_data.xlsx"
docs_path = "./docs_src/dataframes/revenue_data.md"
```

Hive-partitioned data:

```toml
path = "./_data/revenue_data/**/*.parquet"
```

Glob paths only support `format="polars"` (LazyFrame) in `data.load`. As with charts, exactly one of `docs_path` / `docs` is required.

`date_col` must be the column's name exactly as it is in the data, capitals included. The build warns when the data has no such column.

### Naming columns

Give columns code-friendly names: letters, digits and underscores, starting with a letter, such as `spread_10y_2y` or `dgs10`. Lowercase is safest. Such a name works unquoted in SQL, as an attribute in Python and R, and as part of an address (`term_premium#spread_10y_2y`).

A name for people to read, such as "10Y-2Y Spread", is metadata. Put it in a series table (next section), not in the data. A column called `10Y 2Y Spread` still loads and is still listed, but it has no address of its own until a series table gives it one.

### Documenting a column: `[dataframes.<id>.series.<key>]`

A dataframe with a date column and several value columns holds several time series. To give one of them a name, units and a write-up of its own, add a series table under the dataframe:

```toml
[dataframes.treasury_rates.series.dgs10]
name = "10-Year Treasury Constant Maturity"
column = "DGS10"              # the column in the data; defaults to the key
units = "Percent"
frequency = "Daily"
docs_path = "./docs_src/series/dgs10.md"
```

The key (`dgs10`) is the series' address inside the dataframe, `treasury_rates#dgs10`, so it may only contain letters, digits, `.`, `_` and `-`. If the column already has a code-friendly name, use it as the key and leave `column` out:

```toml
[dataframes.term_premium.series.spread_10y_2y]
name = "10Y-2Y Spread"
units = "Percentage points"
```

The column a table names may be spelled any way at all, which is how one called `10Y 2Y Spread` gets an address when the data cannot be changed. Every field is optional, and you may add fields of your own.

You do not have to declare a series for it to exist. Every column except the `date_col` is listed in the build's `index.json` whether or not it has a table; a table only documents one. Series are not shown on the dataframe's page yet, and `data.load()` does not take a series address yet. `chartbook check` reports a `docs_path` that points at no file.

## `[notebooks]` — Jupyter Notebooks

`name` is inferred from the notebook's first `# Heading`; set it explicitly to override. `publishable = true` includes the notebook in `chartbook publish` output.

```toml
[notebooks.exploratory_analysis]
description = "Initial exploration of revenue patterns and anomalies"
path = "_output/01_exploratory_analysis.ipynb"
publishable = true
```

## `[notes]` — Additional Documentation

```toml
[notes.methodology]
path = "./docs_src/methodology.md"
```

## `[models]` — Trained Models

A model is a file, or a directory of files, that the pipeline's own code produces. ChartBook records where it is, what it was trained on and how it scores, and gives it a page. It never loads, runs or serves a model.

```toml
[models.rate_forecaster]
name = "Rate Forecaster"
description = "Forecasts the 10-year Treasury yield one month ahead."
path = "./_models/rate_forecaster.joblib"
trained_on = ["treasury_rates"]
metrics_path = "./_output/rate_forecaster_metrics.json"
docs_path = "./docs_src/models/rate_forecaster.md"
tags = ["Forecast", "Treasury"]
```

| Field | Required | Meaning |
|---|---|---|
| `path` | yes | The model file, or the directory that holds its files |
| `trained_on` | no | The dataframes it was trained on. One of this pipeline's is its key in `[dataframes]`; another pipeline's is `pipeline:name` or `scope/pipeline:name` |
| `metrics_path` | no | A JSON file of scores, written by your training code (below) |
| `docs_path` or `docs` | no | The model's write-up: what it is for, how it was built, where not to use it. Strongly recommended: `chartbook check` reports a model without one unless your policy says otherwise |
| `name`, `description`, `tags` | no | As for dataframes and charts. You may add fields of your own |

The key (`rate_forecaster`) is the model's address, `model/rate_forecaster`, so it may only contain letters, digits, `.`, `_` and `-`.

**The metrics file** is one flat JSON object. Values are numbers, strings or `true`/`false`:

```json
{ "rmse": 0.214, "mae": 0.171, "n_train": 5120, "n_test": 1280 }
```

Scores live in a file, not in `chartbook.toml`, because they are an output: they change every time the model is retrained. A table or a curve does not belong here; declare it as a dataframe or a chart.

**Getting the path.** Training code asks where to write, and anything that uses the model asks where to read:

```python
import joblib
from chartbook import models

joblib.dump(model, models.path("rate_forecaster"))       # in the training script
model = joblib.load(models.path("rate_forecaster"))      # anywhere else in the pipeline
```

```console
$ chartbook path model/rate_forecaster
```

There is no `models.load()`: loading is one line of your own code, and keeping it there keeps every machine-learning library out of ChartBook.

**Training data in another pipeline.** A model is often trained on data another pipeline produces. Say so:

```toml
trained_on = ["ftsfr/fed_yield_curve:treasury_rates", "local_features"]
```

Then say where that pipeline is, in {ref}`[dependencies] <dependencies>`:

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
```

With that, `chartbook check` opens the other pipeline's `chartbook.toml` and reports a dataframe it does not declare. The training data is recorded in `index.json`, listed on the model's page, and linked to the dataframe's page when both pipelines are in the same catalog. Without the `[dependencies]` entry the manifest does not load, and the error shows the line to add.

Then pin it, and train on the pinned copy:

```console
$ chartbook pin
```

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates", format="pandas")   # as pinned
```

The model's record in `index.json` then says which bytes that was, under `pinned_inputs`:

```json
"inputs": ["ftsfr/fed_yield_curve:treasury_rates"],
"pinned_inputs": { "ftsfr/fed_yield_curve:treasury_rates": "sha256:4b1f…" }
```

`pinned_inputs` says what `chartbook.lock` pins, which is what your training code is handed. It is not yet a record of what one particular training run read; that comes with build records.

**What you get.** A page for the model with its write-up, a table of its scores, links to the dataframes it was trained on, and its files if it is a directory. A `Model` record in `index.json` with its content hash. And `chartbook check` reports a missing model file, metrics file or write-up, a metrics file that is not a flat object, and (by default) a model with no `name`, `description`, `trained_on` or write-up. `--skip-outputs` leaves out the model and its metrics, which training produces.

A model in another pipeline is read the same way as its data: `models.path("forecasting:rate_forecaster")` is the pinned copy of a declared dependency's model.

Not yet: versions of a model (`model/rate_forecaster@v3`), labels such as `@champion`, and one file inside a directory model (`model/x#weights.pt`).

(dependencies)=
## `[dependencies]` — Other Pipelines This One Reads From

A pipeline that uses another pipeline's data says so, and says where that pipeline is:

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
"ftsfr/crsp_compustat"  = { git = "https://gitlab.example.org/ftsfr/crsp_compustat", rev = "a1b2c3d" }
```

The **key** is the name this pipeline knows the other one by. It is a pipeline ID, `name` or `scope/name`, and a key with a `/` in it must be quoted. The **value** says where to get it:

| Field | Meaning |
|-------|---------|
| `path` | A directory holding the other pipeline's `chartbook.toml`. Relative to this pipeline's root, or absolute |
| `git` | A git repository holding it. Any host, any URL git accepts |
| `rev` | With `git`: the commit, tag or branch to use. Optional |

An entry has `path` or `git`, not both.

**The name and the place are separate on purpose.** Your code, your lineage and `index.json` say `ftsfr/fed_yield_curve`. Only this table says where that is. When a repository moves, one line changes.

**The key is your name for it.** It usually matches what the other pipeline calls itself, and it does not have to. In a reference you may leave the scope off when only one dependency has that name: with the table above, `fed_yield_curve:treasury_rates` and `ftsfr/fed_yield_curve:treasury_rates` are the same dataframe.

**What it does today.**

- `chartbook check` reports a `path` that is not there, has no `chartbook.toml`, is a catalog, or is the pipeline's own directory.
- `chartbook check` reports training data that a dependency does not declare (`trained_on = ["fed_yield_curve:no_such_table"]`).
- `index.json` lists them, under `dependencies` in the pipeline's record.
- A model's training data in another pipeline is written by the dependency's name, so `fed_yield_curve:treasury_rates` becomes `ftsfr/fed_yield_curve:treasury_rates`.

- `chartbook pin` freezes what each `path` dependency has now. Every asset it declares is copied into the store, and its content hash is written to `chartbook.lock`, which you commit. `chartbook update` moves the pins forward. See {doc}`cli`.
- **Your code reads the pinned copy.** `data.path("fed_yield_curve:treasury_rates")`, `data.load(…)`, `assets.path(…)`, `models.path(…)` and `chartbook path …` all resolve a reference to another pipeline's asset through `chartbook.lock` into the store, never to that pipeline's working directory. No catalog is needed.
- A reference to a pipeline that is not in this table fails, and shows the line to add.

**What it does not do yet.**

- A `git` dependency is recorded and not fetched; `check` and `pin` each say so, and its assets cannot be read.
- `data.load(pipeline=…, dataframe=…)`, with two arguments, still looks in a catalog and reads the other pipeline's own file, as it always has. It does not read this table.

A catalog has no `[dependencies]`. It reads from no pipeline; it lists them in `[pipelines]`. The design is {doc}`../design/asset-graph`.

## Custom Site Pages

Custom markdown pages merge into the generated site from `./docs_src/site/` — auto-detected, no configuration needed. Set `site_dir` in `[project]` only to use a different directory. Chart and dataframe doc fragments stay outside it (`docs_src/charts/`, `docs_src/dataframes/`) so they aren't published twice. The built HTML output remains `./docs/`.

## Migrating from v1

The old `[config]`/`[site]`/`[pipeline]` format is not supported; loading a v1 file fails with a pointer to the migration script:

```console
python scripts/migrate_toml_v2.py /path/to/project
```

The full v1 → v2 field mapping is in the {doc}`design doc <../design/toml-format-v2>`.

## Global Configuration

Per-user settings live in `~/.chartbook/settings.toml`, managed by the `chartbook config` command:

```toml
[catalog]
path = "/absolute/path/to/catalog/chartbook.toml"
```

When a default catalog is configured (or `~/.chartbook/chartbook.toml` exists), `data.load()` and `data.get_data_path()` work without an explicit `catalog_path` argument:

```python
from chartbook import data
df = data.load(pipeline="yield_curve", dataframe="repo_public")
```

An explicit `catalog_path` argument always takes priority over the global setting. See the {doc}`cli` reference for details.

The same file says where the store is, if it is not at `~/.chartbook/store/`:

```toml
[store]
path = "/a/bigger/disk/chartbook-store"
```

The store is a folder of files kept under the hash of their content. It is where `chartbook pin` keeps its copies of other pipelines' data, and it is shared by all your projects. The `CHARTBOOK_STORE` environment variable overrides the setting, for one shell or one CI job. `chartbook store verify` checks a store and `chartbook store gc` clears out what no project needs ({doc}`cli`).

## Best Practices

1. **Let defaults work**: omit fields whose defaults are right; the file stays small
2. **File paths**: use relative paths from the project root
3. **Scoped IDs**: keep pipelines in git repos with remotes so IDs derive automatically
4. **Tags**: use consistent tags across charts and dataframes
5. **Policy over convention**: encode required metadata in your catalog's `[policy]` rather than in personal habit
6. **Data governance**: fill in licensing and access fields for anything shared

## Validation

chartbook validates the manifest when running commands. Common errors:

- Both or neither of `docs_path` / `docs` provided
- A chart's `dataframe` key referencing a missing dataframe
- Explicit `type` contradicting the file's structure
- Referenced files that don't exist (run `chartbook check`, or `chartbook build`)

Warnings (unknown `[project]` keys, missing policy-required fields) appear during `chartbook build` and on the catalog's diagnostics page. `chartbook check` turns missing required fields, missing files and expiring licenses into a nonzero exit code for CI.
