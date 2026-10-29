# Manifest Files (`chartbook.toml`) Configuration

Complete reference for configuring `chartbook.toml` manifest files — both pipeline and catalog types.

## Installation

```bash
# One install, everything included (data loading, plotting, CLI, scaffolder)
pip install chartbook

# Isolated CLI install via pipx
pipx install chartbook

# Development (in a clone of the ChartBook repository, with uv)
uv sync
```

## Format Overview

- All project metadata lives in a single `[project]` table. **Every key is
  optional** with a sensible default — there are no required project fields.
- There is **no format version key**. (Legacy v1 files — recognizable by a
  top-level `config` section — are rejected by the loader with a pointer to
  the migration script. Never write the old v1 section names or prefixed
  field names.)
- **Project type is inferred**: a manifest with a `[pipelines]` registry table
  is a **catalog**; otherwise it is a **pipeline**. You may set
  `type = "pipeline"` or `type = "catalog"` explicitly in `[project]`, but a
  `type` that contradicts the file structure (e.g. `type = "pipeline"` with a
  `[pipelines]` table, or `type = "catalog"` with `[charts]`/`[dataframes]`
  sections) is an error. A file with both a `[pipelines]` table and entity
  sections and no explicit `type` is also an error — set `type` explicitly.
- The minimal valid pipeline manifest is an **empty file** — its presence
  alone marks a directory as a ChartBook pipeline. Defaults cover everything
  else (name from the directory name, copyright from the current year, and so
  on).
- Unknown keys in `[project]` produce a warning naming the closest known key.

## The `[project]` Table

All keys are optional:

| Key | Type | Default |
|-----|------|---------|
| `type` | `"pipeline"` or `"catalog"` | inferred from structure (see above) |
| `id` | string: `scope/name` or bare `name` | derived (see [Pipeline Identity](#pipeline-identity)) |
| `name` | string | directory name (doubles as the site title) |
| `description` | string | `""` |
| `maintainer` | string | `""` (also rendered as the site author) |
| `contributors` | array of strings | `[]` |
| `repo_url` | string | git remote `origin` if available, else `""` |
| `site_url` | string | `file://` path to local built docs |
| `readme` | string (path) | `"./README.md"` |
| `copyright` | string | current year |
| `logo` | string (path) | bundled default asset |
| `favicon` | string (path) | bundled default asset |
| `os_compatibility` | array of strings | `[]` |
| `build` | string (multi-line allowed); the same as `[scripts] build` | `""` |
| `requires_chartbook` | a version specifier, as a pip requirement has it after the name (`">=0.2.0"`); every command that acts on the manifest stops first, saying how to install a ChartBook that meets it; a bare version, or the name with it, is refused with the specifier to write | `""` (any) |
| `site_dir` | string (path) | `"./docs_src/site/"` when that directory exists, else disabled |
| `enable_data_download` | bool | `false` |
| `writer` | `"sphinx"` or `"mkdocs"`: the site tool (MkDocs needs `pip install chartbook[mkdocs]`) | `"sphinx"` |

### Scripts

`[scripts]` names the commands that are run in a pipeline. `chartbook run <name>`
runs one, in this pipeline.

```toml
[scripts]
build = "doit"
test = "pytest"
fetch = """
module load anaconda3/2024.02
conda activate myenv
python src/pull.py
"""
```

- `build` is the one reserved name: the command that makes the pipeline's data
  current. `chartbook run` with no name runs it. It MUST be a command that builds
  the pipeline, not a note: `chartbook run` executes it.
- A script is a single string with **shell-script semantics**: a multi-line value
  is one script, so state (e.g. `conda activate`) carries across lines. It runs in
  the pipeline's directory under `bash -e` and stops at the first failing command.
- A name matches `[A-Za-z0-9._-]+`. An empty script does not load.
- `[project] build = "..."` is the same thing as `[scripts] build` and is still
  read. Give it in one place; two different values do not load.
- Scripts are not tasks: no dependencies between them, no retries, no schedule.
- A catalog cannot have this table.

## Complete Pipeline Configuration

```toml
[project]
name = "Sales Analytics Pipeline"
description = "End-to-end sales analytics and reporting"
maintainer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
repo_url = "https://github.com/org/sales-analytics"
os_compatibility = ["Windows", "Linux", "macOS"]
site_dir = "./docs_src/site/"

[scripts]
build = "doit"

[charts.monthly_sales]
name = "Monthly Sales Overview"
description = "Total sales by month with YoY comparison"
dataframe = "sales_data"
tags = ["Sales", "Monthly", "Revenue"]
frequency = "Monthly"
observation_period = "Month-end"
release_lag = "5 days"
seasonal_adjustment = "None"
units = "USD"
series = ["Gross Sales", "Net Sales"]
mnemonic = "SALES_MO"
date_cleared_by_iv_and_v = "2025-01-15"
last_legal_clearance_date = "2025-01-10"
last_cleared_by = "Legal Team"
publications = [
    "[Q4 Report 2024, p15](https://example.com/q4)",
]
path = "./_output/monthly_sales.html"
excel_path = "./excel/monthly_sales.xlsx"
docs_path = "./docs_src/charts/monthly_sales.md"

[dataframes.sales_data]
name = "Sales Transactions"
description = "Detailed sales transaction data"
sources = ["CRM System", "ERP System"]
providers = ["Sales Team", "Finance Team"]
provider_links = [
    "https://internal.company.com/crm",
    "https://internal.company.com/erp"
]
access_types = ["Internal", "Internal"]
contact_required = ["No", "No"]
pre_approved = ["Yes", "Yes"]
license = "Internal Use Only"
license_expiration = "2025-12-31"
provider_contact = "data-team@company.com"
restrictions = "Internal analytics only"
pull_method = "SQL query via Python"
tags = ["Sales", "Transactions", "Revenue"]
date_col = "transaction_date"
path = "./_data/sales_data.parquet"
excel_path = "./_data/sales_data.xlsx"
docs_path = "./docs_src/dataframes/sales_data.md"

[notebooks.exploratory]
description = "Initial exploration of sales patterns"
path = "_output/01_exploratory.ipynb"

[notes.methodology]
path = "./docs_src/methodology.md"

# Other pipelines this one reads from: a name, and where to find it
[dependencies]
"myorg/fed_yield_curve" = { path = "../fed_yield_curve" }
```

### Sources

A dataframe is in one place: a file (`path`), or a table or query in a source.

```toml
[sources.local]
backend = "duckdb"                          # or "databricks"; others are refused
url = "duckdb:///./_data/local.duckdb"      # public part only; NEVER credentials

[dataframes.curve]
source = "local"
table = "fed_yield_curve"                   # one to three dot-separated parts
[dataframes.slopes]
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope from fed_yield_curve"
```

- Exactly one of `path`, `table`, `query`. `table`/`query` need `source`; `path` forbids it.
- A table/query dataframe has no file: `data.path()`/`chartbook path` refuse it; use
  `data.load()`, `data.sql()`, `data.ref()`. It is not pinned and not in a snapshot.
- The URL is relative to the pipeline root (`duckdb:///./x.duckdb`), absolute with four
  slashes, or `duckdb:///:memory:`. Credentials come from `CHARTBOOK_SOURCE_<NAME>_URL`,
  then `~/.chartbook/sources.toml`, then the manifest URL. Connections are read-only and
  opened afresh per load; a `:memory:` source is one writable connection for the process.
  A DuckDB url is the file alone: no host, user or `?options`.
- `backend = "databricks"` (EXPERIMENTAL; needs `pip install chartbook[databricks]`) is a SQL warehouse:
  `url = "databricks://<host>?http_path=<path>&catalog=<c>&schema=<s>"`, every part optional.
  The machine signs in with `DATABRICKS_HOST` + `DATABRICKS_TOKEN` (or the machine URL
  `databricks://token:<t>@<host>?http_path=…`, or `?auth=oauth` in the machine URL; never in the
  manifest, which names no user or token either). A token goes only to the host
  the machine names: a manifest host that differs stops the read. Rows come when the lazy frame
  is collected. A query in a warehouse cannot name a file of the pipeline. Another pipeline
  cannot pin a warehouse table yet.
- ChartBook never parses or rewrites SQL. The index records `location` kind
  `table`/`query` with a `definition_hash` instead of a `content_hash`.
- A catalog cannot have `[sources]`.

### Dependencies

`[dependencies]` names the other pipelines a pipeline reads from. The key is a
pipeline ID (`name` or `scope/name`; quote a key that has a `/`). The value is a
table that says where to get it. Empty, `"acme/rates" = {}`, names the pipeline
by its ID alone: it is pinned from its newest snapshot in the store, with no
folder of it here and no clone (`chartbook add acme/rates` writes the line; `id`
gives the full ID when the key is a shorter name, `commit` takes the newest
snapshot at that commit, `rev` a branch or tag of its repository, `repository`
says which repository when more than one claims the ID). `path` is a directory
holding that pipeline's `chartbook.toml`, for two pipelines in one repository.
`git` is a repository URL, optionally with `rev`. Never `path` and `git` both.

- `chartbook check` reports a `path` that is missing, has no `chartbook.toml`, is
  a catalog, or is the pipeline itself, and a model whose `trained_on` names a
  dataframe the dependency does not declare.
- `index.json` lists them under `dependencies` in the pipeline's record.
- A model's `trained_on = ["fed_yield_curve:treasury_rates"]` must name a
  declared dependency (the scope may be left off when unambiguous). If it does
  not, the manifest does not load, and the error shows the line to add.
- A `path` dependency is read through **snapshots**, never through its folder
  (people and agents work on different pipelines at the same time, and a folder
  may be half-way through a change). In the OTHER pipeline, its owner runs
  `chartbook run --snapshot` (build, then snapshot; or `chartbook snapshot`
  alone after a build): everything in that folder must be committed, and its
  built assets are copied to the store, labelled with the commit. It is made on
  purpose, not by every build. A snapshot never contains anything from `.env`.
- `chartbook pin` pins each dependency's newest snapshot (the newest at the
  commit its folder is on, else at the nearest earlier commit that has one) and
  writes the content hashes and the commit to `chartbook.lock`, which is
  committed. With no snapshot it fails and says so. It never moves an existing
  pin; `chartbook update [dep...]` does, to the newest snapshot. A rebuild with
  no new snapshot is not seen at all.
- To see a change in a pipeline you are changing too: commit it, run
  `chartbook snapshot` there, then `chartbook update` here. A lockfile never
  records a read of a working folder. In a notebook, `data.load()` reads a
  dependency with no snapshot yet from its folder, with a `WorkingVersionWarning`,
  and pins nothing.
- Code then reads the pinned copy by reference: `data.load("fed_yield_curve:treasury_rates")`,
  `data.path(...)`, `assets.path("fed_yield_curve:chart/x")`, `models.path(...)`,
  or `chartbook path fed_yield_curve:treasury_rates` from a shell. It never
  resolves to the other pipeline's working directory, and is read-only.
- A `git` dependency (`{ git = "https://…", rev = "v1.2" }`; `rev` optional) is
  cloned by `chartbook pin` into `~/.chartbook/git/` and pinned like a directory.
  It has ONLY what its repository commits: git-ignored, built data is "not built".
  The lockfile records the commit; `chartbook update` re-fetches and follows a branch.
  A catalog cannot have this table.
- `chartbook run` pins whatever has no pin yet and then runs THIS pipeline's
  `build`. It never moves a pin (`chartbook update` does). It NEVER builds in a
  `path` dependency's folder: that folder is somebody's work, and is its owner's
  to build (run `chartbook run` there). It builds a `git` dependency once per
  commit, in a clean writable copy of its checkout (`~/.chartbook/git/work/`),
  so its built data can be pinned; `chartbook run --force` builds it again.
  To move a git dependency to a newer commit: `chartbook update`, then
  `chartbook run` (update lets go of data built at the old commit).

A minimal — but complete and valid — pipeline manifest:

```toml
[project]
name = "Sales Analytics Pipeline"
```

as is an empty file.

## Pipeline Identity

The canonical pipeline identity is a **scoped name**: `scope/name`, e.g.
`ftsfr/crsp_treasury`. Each component matches `[A-Za-z0-9._-]+`; lowercase is
recommended. The scope is conventionally the hosting org/user (GitHub org). A
bare unscoped `name` is also legal for local-only projects.

**Derivation precedence** (highest first):

1. Explicit `id` in `[project]` (e.g. `id = "ftsfr/crsp_treasury"`).
2. At the top of a git repository with a remote (`repo_url`, or else the
   git `origin` remote): scope and name from the remote, whatever the folder
   is called. `github.com/ftsfr/crsp_treasury` cloned into `crsp-copy/`, or
   checked out in a git worktree, is still `ftsfr/crsp_treasury`.
3. In a subfolder of such a repository: scope from the remote, name from the
   subfolder (`yield-curve/` in `github.com/acme/monorepo` is
   `acme/yield_curve`).
4. With no remote: the folder's name, unscoped.

A derived scope is lowercase, and a derived name lowercase with `_` for `-`
and spaces, however the remote is written (`https://`, `ssh://`,
`user@host:path`); write references in lowercase too (`acme/rates`, not
`Acme/rates`). A clone of a folder on disk (a path remote) takes its own
folder's name. An SSH host alias (`git@github.com-work:acme/rates.git`) gives
the same ID and counts as another repository's address. `repo_url` comes before the remote, and `chartbook check` warns
when the two name different repositories. Adding a remote to a pipeline that
had none changes its ID (`first_pipeline` becomes `testorg/first_pipeline`),
and its snapshots are made under the new one; `chartbook pin`/`update` say
when a dependency named by the old ID has newer snapshots of the same
repository under another, and name the entry to write
(`"first_pipeline" = { id = "testorg/first_pipeline" }`); `chartbook check`
warns when a catalog key or such a dependency no longer matches what the
folder calls itself. Two checkouts of one repository (a worktree, a second
clone) are one pipeline: a catalog lists it once. Set `[project] id` to pin
the ID down.

**Resolution** for `data.load(pipeline=...)`, `chartbook ls`, and friends:

```python
data.load(pipeline="crsp_treasury", ...)                          # bare name
data.load(pipeline="ftsfr/crsp_treasury", ...)                    # canonical scoped name
data.load(pipeline="https://github.com/ftsfr/crsp_treasury", ...) # URL, normalized
```

- A scoped name matches its catalog key exactly.
- A bare name matches any catalog entry whose name component equals it; if
  several entries match, ChartBook errors and lists the candidates so the
  caller can qualify with a scope.
- A URL is normalized to a scoped name (last two path segments, `.git`
  stripped).
- The `@rev` suffix (e.g. `ftsfr/crsp_treasury@a1b2c3d`) is **reserved but not
  yet supported** — the parser rejects it with a "not yet supported" error.
- A registry prefix (e.g. `charthub.example/ftsfr/crsp_treasury`) is likewise
  **reserved but not yet supported**: the first of three components, when it
  looks like a host (contains `.` or `:`, or is `localhost`). Write
  `ftsfr/crsp_treasury`.

## Catalog Configuration

A catalog aggregates multiple pipelines into unified documentation. Catalog
keys under `[pipelines]` are canonical scoped pipeline IDs; TOML requires
quoting keys that contain `/`:

```toml
[project]
name = "Company Analytics Catalog"
maintainer = "Data Team"

[pipelines."acme/sales"]
path = "../pipelines/sales"

[pipelines."acme/marketing"]
path = "../pipelines/marketing"

# Disabled pipeline — skipped during builds
[pipelines."acme/broken_pipeline"]
path = "../pipelines/broken"
disabled = true

# Platform-specific paths
[pipelines."acme/finance"]
path = { unix = "/data/pipelines/finance", windows = "T:/pipelines/finance" }
```

Entry keys: `path` (string, or a `{ unix = ..., windows = ... }` table for
platform-specific locations) and `disabled` (bool, default false).

`chartbook catalog add <dir>` writes the pipeline's ID as the key (see
[Pipeline Identity](#pipeline-identity)).

### Catalog Auto-Discovery

Local catalogs can declare membership as path patterns instead of explicit entries; matched directories with a pipeline `chartbook.toml` join under their derived scoped IDs:

```toml
[pipelines]
members = ["../my_repos/*"]
disabled = ["scope/some_pipeline"]   # switch members off by ID
exclude = ["../my_repos/scratch_*"]  # optional
```

`members`, `exclude`, and `disabled` are reserved keys (not usable as pipeline IDs). Globs skip non-pipeline directories silently; literal broken paths, v1-format members, and duplicate derived IDs are hard errors with fix suggestions. Explicit entries coexist and win over a member pointing at the same directory. A plain string entry value is shorthand for `{ path = ... }`.

### Catalog Policy

The format itself is permissive; **requiredness is policy**. A catalog may
declare which fields its member pipelines must fill in, and a lone pipeline may
declare what it holds itself to:

```toml
[policy]
mode = "warn"          # "warn" (default): report in the diagnostics page
                       # "strict": fail the build

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
notebooks  = ["description"]
```

- With no `[policy]` section, a default warn-only policy of recommended fields
  applies, reported on the diagnostics page.
- A pipeline may have a `[policy]` of its own: it applies when the pipeline is
  checked or built by itself. Inside a catalog, the catalog's policy applies and
  the pipeline's is ignored.
- `mode = "strict"` fails the build, a catalog's or a lone pipeline's, on a
  missing required field. `chartbook check` exits nonzero on one whatever the
  mode; with no policy anywhere it reports the recommended fields as warnings
  and exits 0.

## Required Fields

The v2 format makes everything optional except one rule: **each chart and each
dataframe must have exactly one of `docs_path` or `docs`** (external markdown
file vs. inline markdown string — mutually exclusive). Any further
requiredness comes from a `[policy]` section, the catalog's or a lone pipeline's
own, not the format.

Practical notes:

- A dataframe needs `path` (its parquet file) for `data.load` and the data
  glimpse tooling to work.
- A chart needs `path` (its HTML file) to render on the site.

**Minimal dataframe example:**

```toml
[dataframes.my_data]
name = "My Dataset"
description = "Brief description"
path = "_data/my_data.parquet"
docs = "Detailed documentation about this dataset, its columns, and usage."
```

**Minimal chart example:**

```toml
[charts.my_chart]
name = "My Chart"
description = "Brief description"
dataframe = "my_data"
path = "./_output/my_chart.html"
docs_path = "./docs_src/charts/my_chart.md"
```

### Notebooks

The notebook name is automatically inferred from the first `# Heading` in the
notebook. Set `name` explicitly to override. Set `publishable = false` to
exclude a notebook from publishing.

```toml
[notebooks.my_notebook]
description = "What this notebook does"
path = "_output/my_notebook.ipynb"
```

## Chart Field Reference

| Field | Description |
|-------|-------------|
| `name` | Human-readable chart name |
| `description` | Brief description |
| `dataframe` | Links to the dataframe definition (key in `[dataframes]`) |
| `tags` | List of topic tags |
| `frequency` | Daily, Weekly, Monthly, Quarterly, Annual |
| `observation_period` | When measurement taken |
| `release_lag` | Delay until data available |
| `release_timing` | When data is typically released |
| `seasonal_adjustment` | None, X-13ARIMA-SEATS, etc. |
| `units` | Units of measurement |
| `series` | List of data series names |
| `start_date` | Start date of the data series |
| `mnemonic` | Short identifier |
| `date_cleared_by_iv_and_v` | Internal validation date |
| `last_legal_clearance_date` | Legal review date |
| `last_cleared_by` | Approver name |
| `publications` | List of previous uses |
| `path` | Path to the HTML chart file |
| `keep` | `true` keeps every version of it in the store; `chartbook restore` puts it back (the only value; leave it out otherwise) |
| `excel_path` | Path to Excel file |
| `docs_path` | Path to documentation file (mutually exclusive with `docs`) |
| `docs` | Inline markdown documentation (mutually exclusive with `docs_path`) |

## Dataframe Field Reference

| Field | Description |
|-------|-------------|
| `name` | Human-readable name |
| `description` | Brief description |
| `sources` | List of data sources |
| `providers` | List of providers |
| `provider_links` | Provider URLs |
| `access_types` | Access types per source |
| `contact_required` | Contact requirements per source |
| `pre_approved` | Pre-approval status per source |
| `license` | License agreement |
| `license_expiration` | License expiry |
| `provider_contact` | Contact information |
| `restrictions` | Usage restrictions |
| `pull_method` | Data collection method |
| `tags` | List of topic tags |
| `date_col` | Date column name |
| `path` | Path to Parquet file or glob pattern (e.g., `_data/**/*.parquet` for hive-partitioned data) |
| `keep` | `true` for an output that cost money or compute to make: every version stays in the store, `chartbook restore` puts it back on disk, and `chartbook run` stops before remaking it. Also on notebooks, notes and models (a trained model's weights) |
| `excel_path` | Path to Excel file |
| `docs_path` | Path to documentation file (mutually exclusive with `docs`) |
| `docs` | Inline markdown documentation (mutually exclusive with `docs_path`) |

## Site Directory (Custom Pages)

The `site_dir` field in `[project]` adds custom markdown pages alongside
auto-generated ChartBook documentation. It defaults to `./docs_src/site/` and
is auto-enabled when that directory exists — no configuration needed.

### Configuration

```toml
[project]
name = "My Pipeline"
site_dir = "./docs_src/site/"   # optional — this is the default when the directory exists
```

### Directory Layout

```
docs_src/
├── charts/                # Chart doc fragments (docs_path targets)
├── dataframes/            # Dataframe doc fragments (docs_path targets)
└── site/                  # Custom site pages (site_dir)
    ├── index_toc.md       # Controls how pages appear in the index toctree
    ├── methodology.md     # Custom page
    ├── data-sources.md    # Custom page
    ├── guides_toc.md      # Sub-toctree for nested pages
    └── guides/
        ├── getting-started.md
        └── faq.md
```

Convention: chart/dataframe doc fragments live in `docs_src/charts/` and
`docs_src/dataframes/`; custom site pages live in `docs_src/site/`. The
`site_dir` default is deliberately not `./docs_src/` itself, because
`site_dir` auto-discovers every `.md` file recursively and would publish each
fragment twice.

### How It Works

1. **`index_toc.md`**: If present, its content is injected into the generated index page as a toctree block. Example:

   ````markdown
   ```{toctree}
   :maxdepth: 1
   :caption: Project Documentation

   methodology
   data-sources
   guides_toc.md
   ```
   ````

2. **Auto-discovery fallback**: If `index_toc.md` is absent, ChartBook auto-discovers all `.md` files in the site directory and generates a toctree automatically.

3. **Reserved namespace**: The site directory must not contain a `cb/` subdirectory, as `cb/` is reserved for auto-generated ChartBook content (charts, dataframes, pipelines, notebooks, diagnostics).

4. **File placement**: Site pages are copied to the root of the built docs directory, alongside the `cb/` directory containing auto-generated content.

### `cb/` Namespace

All auto-generated ChartBook content is placed under a `cb/` subdirectory in the built documentation:

```
docs/                        # Built output
├── cb/                      # ChartBook auto-generated content
│   ├── charts/              # Individual chart pages
│   ├── dataframes/          # Dataframe documentation
│   ├── pipelines/           # Pipeline README pages
│   ├── notebooks/           # Rendered notebooks
│   └── diagnostics.md       # Metadata diagnostics
├── methodology.md           # Custom site pages (from site_dir)
└── index.md                 # Landing page
```

## Hive-Partitioned Data Configuration

Use glob patterns in the dataframe `path` field for hive-style partitioned
datasets:

```toml
[dataframes.partitioned_data]
name = "Partitioned Dataset"
description = "Data partitioned by year and month"
path = "./_data/partitioned/**/*.parquet"
date_col = "date"
docs = "Hive-partitioned dataset with year/month partitions."
```

Polars `scan_parquet` handles glob patterns natively with automatic hive partitioning. Partition columns (e.g., `year`, `month`) are automatically added to the LazyFrame. Every `format=` of `data.load` reads a glob: `"pandas"` and `"polars_eager"` collect the LazyFrame.

## The File's Format

A dataframe's file is parquet, CSV/TSV, JSON lines (NDJSON, gzipped or not) or Arrow IPC (Feather). The path's ending says which: `.parquet`; `.csv`, `.tsv`, `.csv.gz`, `.tsv.gz`; `.jsonl`, `.ndjson`, `.jsonl.gz`, `.ndjson.gz`; `.arrow`, `.feather`, `.ipc`. Anything else, a folder included, is parquet unless `format` says otherwise:

```toml
[dataframes.vendor_prices]
path = "./_data/vendor/prices.txt"
format = "csv"                                   # "parquet" | "csv" | "jsonl" | "ipc"
read_options = { separator = ";", schema_overrides = { zip = "String" } }
docs = "The vendor's daily drop, kept as delivered."
```

- `read_options` are for CSV and JSON lines, by polars' names: `separator`, `has_header`, `quote_char`, `skip_lines`, `null_values`, `decimal_comma` (CSV), and `schema_overrides`, `infer_schema_length` (both; 20480 rows by default in both engines). `data.sql` gives DuckDB the same ones under its own names, meaning the same; polars' `comment_prefix` and `skip_rows` are not taken. A parquet or Arrow IPC file takes none.
- An unknown `format`, an option not in that list, or one of the wrong type stops the manifest from loading; an override of a column the file lacks is refused when it is read.
- A folder's Hive keys are those below it. Each JSON lines file of a glob is inferred from its own lines, and the files joined by name. With `format` given, a folder whose files lack its endings is read as all of them.
- `data.load` reads the schema when called: a file not built raises `FileNotFoundError`, and a file that is not its format raises `UnreadableTableError` naming the format and the reader's reason.
- A file that is not a table belongs under `[files]`, not `[dataframes]`.
