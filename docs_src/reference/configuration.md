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
| `id` | `scope/name` or bare `name` | derived from the git remote and the folder (see [Pipeline Identity](#pipeline-identity)) |
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
| `build` | string (multi-line allowed). The same as `build` in {ref}`[scripts] <scripts>` | `""` |
| `site_dir` | path | `"./docs_src/site/"` when that directory exists |
| `enable_data_download` | bool | `false` |
| `writer` | `"sphinx"` or `"mkdocs"`: the site tool the pages are written for. MkDocs needs `pip install chartbook[mkdocs]`; the build says so when it is missing | `"sphinx"` |

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

[scripts]
build = "doit"
```

The **minimal** valid pipeline manifest is an empty file — its presence alone marks a directory as a chartbook pipeline. In practice you'll usually want at least:

```toml
[project]
name = "My Pipeline"
```

### Build commands

`build` is the command that builds the pipeline. It is a single string with **shell-script semantics**: a multi-line value is one script, so environment state carries across lines:

```toml
[scripts]
build = """
module load anaconda3/2024.02
conda activate myenv
doit
"""
```

It is shown on the pipeline's documentation page, and {ref}`chartbook run <chartbook-run>` executes it. `build` in `[project]` means the same and is still read; {ref}`[scripts] <scripts>` is where it and any other named command go.

(pipeline-identity)=
## Pipeline Identity

Every pipeline has a canonical ID, ideally scoped: `scope/name` (e.g. `ftsfr/crsp_treasury`). An explicit `id` in `[project]` always wins. Otherwise the ID is derived from the pipeline's repository, by one rule:

- **At the top of a git repository with a remote**, the pipeline is named after the repository: its `repo_url`, or else its git `origin` remote, `https://github.com/ftsfr/crsp_treasury`, gives `ftsfr/crsp_treasury`, whatever the folder it is in is called. A clone into another folder, a git worktree and a renamed folder are the same pipeline.
- **In a subfolder of such a repository**, the scope comes from the remote and the name from the subfolder: `yield-curve/` in `github.com/acme/monorepo` is `acme/yield_curve`.
- **With no remote**, the folder's name, bare: `first-pipeline/` is `first_pipeline`.

A derived name is written in lowercase, with `_` for `-` and spaces. So adding a remote to a pipeline that had none changes its ID, from `first_pipeline` to `testorg/first_pipeline`, and its next snapshot is made under the new one. A dependency named by the old ID stays at the last snapshot made under it: `chartbook pin` and `chartbook update` say when the store has newer snapshots of the same repository and folder under another ID, and name the entry to write, `"first_pipeline" = { id = "testorg/first_pipeline" }`; `chartbook check` warns when a catalog's key, or a dependency named by its ID, is not what the pipeline's folder calls itself now. Set `id` to keep one ID whatever happens to the folder or the remote.

Anywhere a pipeline reference is accepted (`data.load`, `chartbook data get-path`, `chartbook data get-docs`), three forms work:

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

Entry keys: `path` (string, or a `{ unix = ..., windows = ... }` table) and `disabled` (bool); any other key is an error. A plain string value is shorthand for the path. An entry with no `path`, `"acme/rates" = {}`, is a pipeline whose folder is not on this machine: the catalog shows it from its snapshots in the store, with a page that links its newest version and the Versions page. Its name, description and maintainer are what its newest snapshot's own index says, shown as plain text (never read as Markdown or HTML, with `< > " '` and the backtick shown as look-alikes and `&` as "and", since anyone who can write to the store wrote them), and its repository and site only when they are `http` or `https` addresses. Its assets are those its newest snapshot's own index lists: its page lists its dataframes, charts and models, and the catalog's Dataframes page lists its dataframes after the catalog's own, each linked to its page in that snapshot's site and named as plain text. It has no working version, and `check`, `run` and the policy pass it by; `chartbook ls` lists it as store only, with its dataframes and charts, and loading its data through the catalog reads its newest snapshot from the store. A folder of the same ID, added with `chartbook catalog add` or found by `members`, fills the entry in. `chartbook catalog add <dir>` writes the key for you, the pipeline's ID (see [Pipeline Identity](#pipeline-identity)).

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

To enforce a policy in CI — for a catalog or a single pipeline — run {doc}`chartbook check <cli>`, which exits nonzero on any missing required field regardless of `mode`. `check --policy FILE` replaces the pipeline's own `[policy]` with the one in that file, as a catalog's replaces its members'; a file with no `[policy]` table gives no policy. When no policy is given anywhere (no `[policy]` in the pipeline, none in the catalog it is checked in, and no `--policy`, or a `--policy` file with no `[policy]` table), `check` reports the missing recommended fields as `warning:` lines, and they do not make it exit nonzero. An empty write-up (`docs_path` or `docs`) still fails it: the format requires one.

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

A dataframe is in one place: a parquet file (`path`), or a table or a query in one of the pipeline's {ref}`[sources] <sources>` (`source` with `table` or `query`). `path` points at the parquet artifact — a single file or a glob pattern for hive-partitioned data:

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

(sources)=
## `[sources]` — Where Data Lives Besides a File

A dataframe does not have to be a file. It can be a table, or a query, in a **source**: a database the pipeline names.

```toml
[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/local.duckdb"

[dataframes.curve]
name = "Yield Curve"
source = "local"
table = "fed_yield_curve"                 # a table or view that already exists
docs = "The Fed's zero-coupon curve, as a table."

[dataframes.slopes]
name = "Yield Curve Slopes"
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope from fed_yield_curve"   # a view ChartBook names
docs = "The 10-year yield less the 2-year, computed when read."
```

**The rule.** A name resolves to a location. The engine runs the query. Arrow comes back. Polars wraps it. ChartBook never parses, plans or rewrites SQL: it knows *where* a name lives and *which* engine lives there, and puts the name in. The SQL is yours.

| Field | Meaning |
|---|---|
| `backend` | The engine: `duckdb`, or `databricks` (a SQL warehouse, after `pip install chartbook[databricks]`). Another name is refused, unless a plugin provides it, so that nothing guesses |
| `url` | Where the engine's data is, public part only. `duckdb:///./_data/x.duckdb` is a file relative to the pipeline's root; `duckdb:////abs/path.duckdb` is absolute; `duckdb:///:memory:` is nothing on disk. A DuckDB url names the file and nothing else: no host, no user, no options after it. A Databricks url is `databricks://<host>?http_path=<path>&catalog=<c>&schema=<s>`, every part optional; see below |

| On a dataframe | Meaning |
|---|---|
| `source` | Which source it is in. Needed with `table` or `query`; not allowed with `path` |
| `table` | A table or view that already exists there: one to three dot-separated parts |
| `query` | SQL the engine runs when the dataframe is read, in the engine's dialect |

Exactly one of `path`, `table` and `query`. A dataframe in a source has no file, so `data.path()` and `chartbook path` refuse it and say what to use instead.

**Reading one.** `data.load("slopes")` gives a Polars LazyFrame, as for a file. The engine binds the query at once, so a name it does not know is refused then; collecting the frame runs it, and an error only running can find (a cast that fails on one value) is raised then, with the engine's message in it. A warehouse sends the rows a batch at a time when the frame is collected, and `head(n)` with nothing filtered asks it for `n` rows. `data.sql()` runs your own SQL with dataframes named in braces, `data.ref()` gives a dataframe's name in SQL for a query you run yourself, and `data.connect()` is the raw connection. See {doc}`../guide/catalogs-and-data`, "Loading data".

**Credentials never enter the manifest.** A `url` with a user name or a password in it does not load. The machine supplies the rest, in this order: the environment variable `CHARTBOOK_SOURCE_<NAME>_URL` holding a complete URL (`CHARTBOOK_SOURCE_LOCAL_URL` for `local`); `url` under `[local]` in `~/.chartbook/sources.toml`; the manifest's URL alone, which is all a DuckDB file needs. The machine says where the engine is, not which it is: a machine URL for another engine than `backend` is refused. The index and the pages record the manifest's URL only.

**A Databricks source**, an early experiment ({doc}`../roadmap`), takes its workspace and token from the machine: the machine's URL for the source above (`databricks://token:<token>@<host>?http_path=…`), or else `DATABRICKS_HOST` and `DATABRICKS_TOKEN`, Databricks' own variables; `DATABRICKS_HTTP_PATH` gives the warehouse when no URL does, and `auth=oauth` in the machine's URL signs in through the browser instead of a token, once per process. A manifest's URL names no user, no token and no way of signing in. The manifest's host is a check: if the machine names another, the read stops, so that a token is never sent to a host a manifest or another pipeline's record chose. {doc}`../guide/reading-a-warehouse` walks through it, with Databricks Free Edition.

**No writes.** ChartBook runs only `select` in a warehouse, and the SQL you run with `data.sql()` or `data.connect()` is yours. A DuckDB file is opened read-only, afresh for each load, so a rebuilt file is seen on the next call. The pipeline's own tools make the tables (`src/build_duckdb.py` in the `yield_curve` example); ChartBook names them. A LazyFrame from a DuckDB source keeps its own connection while it lives, and DuckDB locks the file against writers for that long: drop the frame before rebuilding the file in the same process. A `:memory:` source is the one exception: it holds nothing but what you put in it through `data.connect()`, so it is one writable connection for the life of the process.

**In the index and on the page.** The dataframe's `location` is `{ "kind": "table", "source", "backend", "identifier" }` or `{ "kind": "query", "source", "backend", "sql" }`. There is no `content_hash`, since a table is not bytes on disk; `definition_hash` hashes the identifier or the SQL, the source it is in, and the described columns, so a changed definition, place or schema shows. A table the engine cannot describe (not built yet, a typo in `table`, SQL that does not bind) gets a warning when the index is built and a record without columns. The page shows the columns, the first rows and, with `date_col`, the first and last date, read from the engine when the site is built; what cannot be read is said on the page, and the site is still built.

**What it does not do.**

- **DuckDB and Databricks.** Snowflake and Postgres are not built. A manifest that names one is refused.
- **A table is pinned as parquet.** A snapshot holds files, so `chartbook snapshot` writes a table or query in a DuckDB file out as a parquet file into the store, and another pipeline reads that copy by name, as it reads any pinned dataframe. A query's rows are written sorted on every column, so that the same rows give the same bytes. A table in `:memory:`, or one that cannot be read, is recorded as not built, and the snapshot says why. A table or query in Databricks is recorded and not copied, and another pipeline cannot pin it yet.
- **One source per query.** `data.sql()` runs in one engine: the source its tables and queries are in, with any files it names read alongside, if the engine reads files; DuckDB does and a warehouse does not. A query that names two sources is refused.
- A catalog has no `[sources]`.

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

You do not have to declare a series for it to exist. Every column except the `date_col` is listed in the build's `index.json` whether or not it has a table; a table only documents one. Series are not shown on the dataframe's page yet.

**A series address is for documentation, not for loading.** `treasury_rates#dgs10` names the column so that a name, units and a write-up can be attached to it. It does not load it: `data.load("treasury_rates#dgs10")` is refused, on purpose. ChartBook says where a dataframe is and which copy you get; picking columns and rows is for polars or SQL.

```python
rates = data.load("treasury_rates").select("date", "DGS10")     # polars
path = data.path("treasury_rates")                              # or the file, for anything else
```
 `chartbook check` reports a `docs_path` that points at no file.

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

(model-versions)=
### Versions and labels

**A version of a model is made by a snapshot.** Retrain twenty times in an afternoon and there are no new versions. Run `chartbook run --snapshot`, and if the model's bytes are new, that is a version:

```console
$ chartbook run --snapshot
ftsfr/rate_forecast: build
ftsfr/rate_forecast at 4f2a91c: 1 asset(s) in the store
  model/rate_forecaster: new version 7f3a9c2e41b0
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
```

**A version is named by the start of its content hash**, as git names a commit. The name is worked out from the model's bytes and nothing else, so it is the same on every machine and every branch, and two branches that each retrain never fight over a number.

The whole hash is what is stored and compared. The name is its first 12 digits, which is what Docker shows and what the Linux kernel asks for. Among 10,000 versions of one model, two share 12 digits about once in five million; if two ever do, both are shown with more digits, and a start that matches two versions is refused, never guessed at. You can type any start of four or more digits that names one version.

**A label is a name people use**, and it points at a version:

```toml
[models.rate_forecaster.aliases]
champion = "7f3a9c2e41b0"
challenger = "b2c91d0a77f3"
```

Promoting a model is changing one line, in a pull request like any other. There is no "promote" button and no service behind one.

| You write | You get |
|---|---|
| `models.path("rate_forecaster")` | The file in your folder: what you are working on |
| `models.path("rate_forecaster@7f3a9c2e41b0")` | That version, in the store. It never changes |
| `models.path("rate_forecaster@champion")` | The version the label points at |
| `models.versions("rate_forecaster")` | Every version, oldest first, each with its commit, its scores and what it was trained on |

The same names work on a command line: `chartbook path model/rate_forecaster@champion`.

Each version keeps, from the snapshot that made it: the commit (which code), what the pipeline was pinned to (which data), and the scores as the metrics file had them then. The model's page lists them in a table, newest first, and `index.json` has them under `versions`.

| Rule for `aliases` | Example |
|---|---|
| A label is letters, digits, `.`, `_` and `-` | `champion`, `last-quarter` |
| A label may not look like the start of a hash | `beef = "…"` does not load |
| It points at the start of a content hash, at least 12 digits, or all of it | `champion = "7f3a9c2e41b0"` |

`chartbook check` warns about a label whose version is not on this machine. It may still be right: the version may be in the store of the machine that made it.

**Out of date.** A snapshot records what each model was trained on, input by input, as the hash of each at the time. When a model file's bytes are a version and an input has since moved (a local dataframe rebuilt, another pipeline's pinned elsewhere by `chartbook update`), the model's page says so and lists the inputs, `index.json` has them under `stale_inputs`, and `chartbook check` warns. `chartbook run` retrains it, and the next snapshot makes the new bytes a version that is up to date.

**A version of another pipeline's model.** `forecasting:rate_forecaster@champion` is the version that label named when you pinned `forecasting`: `chartbook pin` reads the labels from the snapshot it pins (a snapshot records the labels its manifest had), and writes each as its own record in `chartbook.lock`, `forecasting:model/rate_forecaster@champion`, with the version's hash. So a build that serves the champion is repeatable until `chartbook update` moves the label with the owner's manifest. `forecasting:rate_forecaster@7f3a9c2e41b0` is that version: the one a label of your lockfile pins, if one does, else found among the pipeline's snapshots in the store. A label the owner gave after you pinned is not in your lockfile, and the error says so: `chartbook update` pins it. Nothing of the other pipeline's folder is read.

Not yet:

- **Versions that travel.** A version is in the store of the machine that made its snapshot, or in a store a team shares (see {doc}`cli`, "A store a team shares"). A label pinned across pipelines needs the version's bytes in the store; one whose version is not there is pinned without them, and `--frozen` reports it.
- **Versions of anything but a model.** A dataframe has snapshots, and no version names.
- One file inside a directory model (`model/x#weights.pt`).

(dependencies)=
## `[dependencies]` — Other Pipelines This One Reads From

A pipeline that uses another pipeline's data says so. Naming it by its ID is enough:

```toml
[dependencies]
"ftsfr/rates" = {}                                            # its snapshots in the store
yields = { id = "ftsfr/yield_curve", commit = "3f2a9c1" }     # a short name, and one commit's snapshots
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }     # a folder on this machine
"ftsfr/crsp_compustat"  = { git = "https://gitlab.example.org/ftsfr/crsp_compustat", rev = "a1b2c3d" }
```

`chartbook add ftsfr/rates` writes the first line for you and pins it ({doc}`cli`).

The **key** is the name this pipeline knows the other one by. It is a pipeline ID, `name` or `scope/name`, and a key with a `/` in it must be quoted. The **value** says where to get it:

| Field | Meaning |
|-------|---------|
| (none) | The pipeline is named by its ID alone, the key, and pinned from its snapshots in the store: no folder of it here, no clone. A store a team shares, or a folder synced between your machines, makes this the way to read a colleague's pipeline, or your own from another machine. When the store has no snapshot of it at all and a default host is set (`[resolve] default_host`, below), its repository there is cloned, pinned from and built, as a `git` dependency is |
| `id` | With neither `path` nor `git`: the pipeline's ID, when the key is a shorter name for it |
| `commit` | With neither `path` nor `git`: the start of a commit (7 to 40 hex digits); the newest snapshot at that commit is pinned, rather than the newest of all |
| `repository` | With neither `path` nor `git`: the repository its snapshots must have been made in, as a web address (`https://github.com/acme/rates`, or the `git@github.com:acme/rates` form of it), when more than one repository claims the ID. A path on disk is not taken: it is not the same on another machine |
| `path` | A directory holding the other pipeline's `chartbook.toml`. Relative to this pipeline's root, or absolute |
| `git` | A git repository holding it. Any host: an `https://` or `ssh://` URL, `git@host:owner/name`, or a path on disk (relative to this pipeline's root) |
| `rev` | With `git`: the branch, tag or commit to use. Optional; without it, the repository's default branch. With neither `path` nor `git`: a branch or tag of the pipeline's repository (the one `repository` names, or on `[resolve] default_host`); pin asks the repository what commit it is, and takes the newest snapshot of that repository at or before it, or, with none, the repository at that commit. Not with `commit` |

An entry has `path` or `git`, not both, or neither. Named by its ID alone, "newest" means the snapshot made last, by its owner's clock, on any branch; one dated after now (more than ten minutes ahead of this machine's clock) is never taken.

**Which repository.** Each snapshot records the repository it was made in: the web address of its `origin` remote, and the repository's first commit, which is the same in every full clone and needs no remote. Two snapshots are of one repository when they name one address or one first commit, so a repository that moved, one whose history was rewritten, and a clone whose remote is a path on disk are each still the same repository; two ways of writing one address (`git@github.com:Acme/Rates.git` and `https://github.com/acme/rates`) are one address. A fork has its original's first commit, and counts as the same repository, as another branch does. A dependency named by its ID is pinned from one repository's snapshots: the one it was first pinned from, which `chartbook.lock` records and every later `pin` and `update` keeps to, or the one `repository` names, which is then matched by its address alone, and by clones with no address that share a first commit with it (so a fork's clone with a path remote cannot be told from the original's). `store gc` keeps what says which repository the snapshots it keeps are of: where removing snapshots would leave them looking like two repositories, the newest that names each address and first commit together; for a kept snapshot from a clone with a path remote, those that name its first commit with an address, so that a dependency naming any of those addresses still takes it; and where it keeps a snapshot that names no repository, those that name an address and first commit together (or, failing those, the newest that names the repository). An old address no kept snapshot needs keeps nothing. A newer snapshot of the ID from another repository is not taken, and `pin` and `update` say so when they choose. With nothing pinned yet, an ID that snapshots from two repositories claim (a copied `[project] id`, or two folders of one name) is not pinned until `repository` says which, or `commit` names a commit of one of them. Snapshots made by a ChartBook from before snapshots recorded a repository name none: they count as the repository's when only one repository claims the ID, and are not pinned when more than one does, though `store gc` keeps what any of their labels points at in them. This guards against an accident only. A store's records are written by whoever can write to it, and what a record says of its repository is its word, so share a store only with people whose snapshots you would pin.

**The name and the place are separate on purpose.** Your code, your lineage and `index.json` say `ftsfr/fed_yield_curve`. Only this table says where that is. When a repository moves, one line changes.

**The key is your name for it.** It usually matches what the other pipeline calls itself, and it does not have to. In a reference you may leave the scope off when only one dependency has that name: with the table above, `fed_yield_curve:treasury_rates` and `ftsfr/fed_yield_curve:treasury_rates` are the same dataframe.

**What it does today.**

- `chartbook check` reports a `path` that is not there, has no `chartbook.toml`, is a catalog, or is the pipeline's own directory. It warns when a `path` is in another git repository than the pipeline's own, since that works on this machine only, and shows the line that names it by its ID instead. Two pipelines in one repository are the place for a `path`.
- `chartbook check` reports training data that a dependency does not declare (`trained_on = ["fed_yield_curve:no_such_table"]`).
- `index.json` lists them, under `dependencies` in the pipeline's record.
- A model's training data in another pipeline is written by the dependency's name, so `fed_yield_curve:treasury_rates` becomes `ftsfr/fed_yield_curve:treasury_rates`.

- `data.load` of a dependency that is declared and not pinned pins it, from its newest snapshot, on the first read, and says so; of a pipeline not declared, it reads its newest snapshot with a warning; of one with no snapshot, its working folder with a louder one. In a build under `chartbook run` (`CHARTBOOK_BATCH=1`) only pins are read. See {doc}`../guide/depending-on-pipelines`.
- `chartbook pin` freezes what each dependency was declared ready with. A pipeline named by its ID alone is pinned from its newest **snapshot** in the store, found by that ID. A folder (`path`) is pinned from its newest snapshot at or before the commit the folder is on, which its owner makes there with `chartbook snapshot`; the folder itself is never read, so it can be half-way through a change. A repository (`git`) is pinned from a clean copy of a commit. The content hash of every asset, and the commit, are written to `chartbook.lock`, which you commit. `chartbook update` moves the pins forward. See {doc}`cli`.
- **Your code reads the pinned copy.** `data.path("fed_yield_curve:treasury_rates")`, `data.load(…)`, `assets.path(…)`, `models.path(…)` and `chartbook path …` all resolve a reference to another pipeline's asset through `chartbook.lock` into the store, not to that pipeline's working directory. No catalog is needed. Before it is pinned, a read in a notebook pins it, or reads a pipeline not declared here with a warning, or a working folder with a louder one; a build under `chartbook run` refuses all but the pin (see {doc}`../guide/depending-on-pipelines`).
- A reference to a pipeline that is not in this table is read from its newest snapshot with a warning that names the `chartbook add` command that declares it; in a build under `chartbook run` it fails.

**What it does not do yet.**

- **A `git` dependency has only what its repository commits, until it is built.** `chartbook pin` clones it and pins the declared files that are in git, and only files inside the repository: a path in its manifest that reaches outside is not pinned. `chartbook run` builds it, which runs that repository's code with your environment, so depend on repositories you would run code from. Data the other pipeline builds and git-ignores is not in a clone, and `pin` does not run another pipeline's build, so those assets are listed as not built. `chartbook run` does build it, in a copy of its checkout, and then they can be pinned. An entry with neither is read from the store, and, when the store has no snapshot of it and a default host is set, from its repository on that host. A `rev` with no `git` asks the repository what it means, so it needs `repository` or a default host; a read never asks.
- `data.load(pipeline=…, dataframe=…)`, with two arguments, finds the pipeline in a catalog and reads it by the same rules: its pin, if this table declares it; otherwise its newest snapshot; the catalog's folder only when there is no snapshot, with the warning.

- `chartbook run` pins what has no pin yet, and then builds this pipeline. It never builds in a `path` dependency's folder, and never reads one: that folder is its owner's to build and to declare ready. It builds a `git` dependency once, in a clean copy. See {ref}`chartbook run <chartbook-run>`.

A catalog has no `[dependencies]`. It reads from no pipeline; it lists them in `[pipelines]`. The design is {doc}`../design/asset-graph`.

(scripts)=
## `[scripts]` — Named Commands

A pipeline names the commands that are run in it:

```toml
[scripts]
build = "doit"
test  = "pytest"
fetch = """
module load python/3.12
python src/pull_wrds.py
"""
```

`chartbook run` runs the first, `chartbook run test` the second. See {ref}`chartbook run <chartbook-run>`.

| Rule | Example |
|------|---------|
| A name is letters, digits, `.`, `_` and `-`, since you type it after `chartbook run` | `build`, `fetch.wrds` |
| A script is one string, and may not be empty | `build = "doit"` |
| A script of several lines is **one** script: what one line sets up, the next can use | `fetch`, above |
| It is run in the pipeline's own directory, and stops at the first command that fails | |

**`build` is the one name with a meaning.** It is the script that makes this pipeline's data current. It is what `chartbook run` runs when you name no script, and what it runs, once, in a `git` dependency that is not built yet. It is shown on the pipeline's page, and written to `index.json` with the others.

**`build` in `[project]` is the same thing**, and is still read. Give it in one place. A manifest that gives both, with different text, does not load.

```toml
[project]
build = "doit"      # the same as [scripts] build = "doit"
```

```{warning}
`chartbook run` **executes** `build`. Before `chartbook run` existed the field was only shown on a page, and some manifests keep a note there (`build = "module load anaconda3 TeXLive"`) and not the command that builds the pipeline. Make it the command.
```

**Scripts are not tasks.** One does not depend on another, and there is no order among them. What is out of date *inside* a pipeline is for the pipeline's own tool to decide: doit, Make, Snakemake.

A catalog has no `[scripts]`. `chartbook run` in a catalog runs each of its pipelines' own.

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
url = "/a/bigger/disk/chartbook-store"
```

The store is a setting of the machine or the organization, never of a pipeline, so it is read in layers, each only where the one above it is silent, key by key: the `CHARTBOOK_STORE` environment variable; the user's `~/.chartbook/settings.toml`; the organization's settings file, `/etc/chartbook/settings.toml` on Unix and macOS, `%ProgramData%\chartbook\settings.toml` on Windows, or the file `CHARTBOOK_SYSTEM_SETTINGS` names; then the default. An organization sets the store once for every machine, and a user keeps their own choices for everything else. The value is a URL: a bare path or `file://` is a folder; `s3://bucket/prefix` is a bucket; another scheme names a kind of store a plugin provides, and the setting says so when none does. `[store] path` is still read as a folder, with a warning.

The store is a folder of files kept under the hash of their content. It is where `chartbook pin` keeps its copies of other pipelines' data, and it is shared by all your projects. The `CHARTBOOK_STORE` environment variable overrides the setting, for one shell or one CI job. `chartbook store verify` checks a store and `chartbook store gc` clears out what no project needs ({doc}`cli`).

**A store in a synced folder.** A folder that a sync service such as Google Drive keeps in step between your machines is a store those machines share: point each machine's `[store] url` at the folder's local path. A pipeline cloned on another machine then reads what its committed `chartbook.lock` pins from the store (`chartbook run --frozen`, `data.load("other:name")`), with no folder of the other pipeline there and no build of it, and a catalog there shows every snapshot. Choosing a snapshot (the first `chartbook pin`, `chartbook update`) still needs the other pipeline's folder, and a `git` dependency is built from its clone. Four things to know:

- **Keep the files on this disk**, not online-only (in Google Drive, "Mirror files" rather than "Stream files"). A store is many small files, read often.
- **A snapshot made on one machine is whole on another only once all its files have synced.** A folder store does not hash what it reads again; `chartbook store verify` checks it.
- **Run `chartbook store gc` from one machine**, without `--forget-missing`: from any one machine, the others' lockfiles cannot be found.
- **Anyone who can write to the folder can put snapshots in it**, and the store keeps every snapshot until `gc` removes it.

**A store in S3.** `pip install chartbook[s3]`, and

```toml
[store]
url = "s3://bucket/prefix"
```

The bucket is laid out exactly as a folder store is, under the prefix, so `aws s3 sync` of a folder store into a bucket is this store. Credentials are the AWS SDK's own, from the environment, `~/.aws` or an instance role; the URL never carries them. A bucket that is not at AWS is named with `?endpoint=https://minio.example.org`, and a region with `?region=`. Everything a pipeline reads from the store is read through a copy on this machine, under `~/.chartbook/cache/` (`[cache] path`, or `CHARTBOOK_CACHE`, moves it; it can be emptied whenever nothing is reading from it): the first `data.load()` of a pinned asset downloads its files, checks that they hash to the object's name, and keeps them; each later read while online is one listing request, so that a name another pipeline added for the same bytes is seen, and the files come from disk; offline, what was read and checked before is served. `data.path()` is the path of that copy. A bucket that is read-only for a machine (`s3:ListBucket` and `s3:GetObject`) serves `chartbook pin`, `chartbook run --frozen` and `data.load()`; a command that would write says that it was refused, and `pin` leaves only its note for `store gc` unwritten. Writing (`chartbook snapshot`, a `git` dependency's first pin) needs `s3:PutObject`, and `store gc` `s3:DeleteObject`. A key under an object's prefix that is not a plain path inside it (a `..`, an empty part or a leading `/`; on Windows also a backslash or a colon) is not one of the object's files and is never downloaded, nor is such a key under `snapshots/`: anyone who can write to the bucket chooses its keys, and a reader makes a file of each. One difference from a folder: an object of several files is uploaded one file at a time, so a snapshot interrupted while uploading leaves a partial object, which a reader refuses by name; making the snapshot again completes it. Nothing else changes: the manifest, the lockfile and the snapshots are the same, and so are the commands.

`git` dependencies are cloned into `~/.chartbook/git/`: one clone per repository, and one checkout per commit that something has pinned. To keep them elsewhere, set `CHARTBOOK_GIT_CACHE`, or:

```toml
[git]
path = "/a/bigger/disk/chartbook-git"
```

Nothing in it is precious. Delete it and the next `chartbook pin` or `chartbook update` that needs a repository fetches it again.

**The default host.** A dependency named by its ID alone, `"acme/rates" = {}`, is read from the store. When the store has no snapshot of it at all, its repository is wanted, and the ID says where it is on a git host the machine or the organization sets:

```toml
[resolve]
default_host = "github.com"          # acme/rates is https://github.com/acme/rates
```

`default_host` is a host name, perhaps with a path under it (`github.com`, `gitlab.example.org/group`, cloned over `https`), an address the repositories are under (`https://…`, `ssh://…`, `git@gitlab.example.org:`), or a folder of repositories (`/srv/git`, `~/repos`, or `./repos` relative to the settings file). `default_host = ""` sets none, over the organization's. It is read from the user's settings, then the organization's, and never from a pipeline: the host is not part of a pipeline's identity, so a repository that moves changes this one line. With it set, `chartbook pin` clones a dependency named by its ID that the store has no snapshot of at all (or none at the commit its entry names with `commit`), from that host (or from the repository its entry names with `repository`, as written there, ssh and port included), checks that the clone calls itself by that ID, and pins from it; `chartbook run` checks the same and builds it first, as it does a `git` dependency, except a pipeline the same run builds itself, such as another of a catalog's, which is built before it and never cloned. The lockfile lists it as from its repository (`via: rev`) by the pipeline's ID, with no address, which each machine works out from its own setting. A pin keeps where a dependency was pinned from, the store or its repository, and puts back what the store has lost; an entry with nothing pinned yet, as a failed first read leaves, is looked at afresh. `chartbook update` looks again, takes the store's newest snapshot once there is one, and keeps a pin from the repository when it finds nothing better. Either way it keeps to the repository the dependency was pinned from, by that repository's first commit: a snapshot of another that gives itself the same ID is passed over, and a clone whose history does not begin where the pinned one's did (another repository at the default host, or a history rewritten) is not taken, and is said, as is one that lacks the commit a pin with no first commit recorded was made at; `repository = "..."` names the one to take, or remove the dependency from `chartbook.lock` and update. On a machine with no default host, a pin from its repository is kept as it is, and what the store has lost of it is said. A read never clones: `data.load` of such a dependency before it is pinned says that `chartbook pin` gets it. A pipeline with a bare ID (no scope) has no owner to find it under, and is read from the store only; with no default host, so is every dependency named by its ID.

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
- Referenced files that don't exist (run `chartbook check`, or `chartbook docs`)

Warnings (unknown `[project]` keys, missing policy-required fields) appear during `chartbook docs` and on the catalog's diagnostics page. `chartbook check` turns missing required fields, missing files and expiring licenses into a nonzero exit code for CI.
