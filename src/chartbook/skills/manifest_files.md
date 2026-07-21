# Manifest Files (`chartbook.toml`) Configuration

Complete reference for configuring `chartbook.toml` manifest files — both pipeline and catalog types.

## Installation

```bash
# Data loading only
pip install chartbook

# CLI (recommended - isolated via pipx)
pipx install chartbook

# CLI with pip
pip install "chartbook[sphinx]"

# Full install (recommended — includes data, plotting, sphinx)
pip install "chartbook[all]"

# Development
pip install -e ".[dev]"
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
| `build` | string (multi-line allowed) | `""` |
| `site_dir` | string (path) | `"./docs_src/site/"` when that directory exists, else disabled |
| `enable_data_download` | bool | `false` |

`build` is a single string with **shell-script semantics**: a multi-line value
is one script, so state (e.g. `conda activate`) carries across lines:

```toml
[project]
build = """
module load anaconda3/2024.02
conda activate myenv
doit
"""
```

## Complete Pipeline Configuration

```toml
[project]
name = "Sales Analytics Pipeline"
description = "End-to-end sales analytics and reporting"
maintainer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
repo_url = "https://github.com/org/sales-analytics"
os_compatibility = ["Windows", "Linux", "macOS"]
build = """
doit
"""
site_dir = "./docs_src/site/"

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
```

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
2. Derived: scope from the repo's git `origin` remote (or `repo_url`), name
   from the directory name.
3. Bare fallback: the directory name, unscoped.

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

`chartbook catalog add <dir>` reads the target's git remote and writes the
scoped key automatically, falling back to the bare directory name.

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

The format itself is permissive; **requiredness is catalog policy**. A catalog
may declare which fields its member pipelines must fill in:

```toml
[policy]
mode = "warn"          # "warn" (default): report in the diagnostics page
                       # "strict": fail the catalog build

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
notebooks  = ["description"]
```

- With no `[policy]` section, a default warn-only policy of recommended fields
  applies, reported on the diagnostics page.
- Policy is enforced only when the **catalog** builds. A pipeline built
  standalone is always permissive.

## Required Fields

The v2 format makes everything optional except one rule: **each chart and each
dataframe must have exactly one of `docs_path` or `docs`** (external markdown
file vs. inline markdown string — mutually exclusive). Any further
requiredness comes from the catalog's `[policy]` section, not the format.

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

Polars `scan_parquet` handles glob patterns natively with automatic hive partitioning. Partition columns (e.g., `year`, `month`) are automatically added to the LazyFrame. Glob paths only support `format="polars"` (LazyFrame) — using `"pandas"` or `"polars_eager"` with a glob path raises a `ValueError`.
