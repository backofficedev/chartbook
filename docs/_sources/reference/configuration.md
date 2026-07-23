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
| `repo_url` | string | `""` |
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

If a bare name matches pipelines in more than one scope, chartbook errors and lists the candidates. `scope/name@rev` is reserved syntax for future version pinning and is rejected for now. See {doc}`../design/toml-format-v2` for why identity works this way.

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

## `[policy]` — Catalog Requiredness

The format itself is permissive; **which fields are required is your catalog's policy**:

```toml
[policy]
mode = "warn"          # default; "strict" fails the catalog build instead

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
```

Without a `[policy]` section, chartbook's default recommended-field lists drive the diagnostics page, warn-only. Policy is enforced only when the catalog builds; a pipeline built standalone is always permissive.

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
- Referenced files that don't exist (run `chartbook build` to check)

Warnings (unknown `[project]` keys, missing policy-required fields) appear during `chartbook build` and on the catalog's diagnostics page.
