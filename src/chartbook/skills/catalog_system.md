# Catalog System & Data Access

How to set up, manage, browse, and load data from ChartBook catalogs.

## Global Catalog Setup

### Directory Structure

```
~/.chartbook/
├── settings.toml        # User settings (catalog path override)
├── chartbook.toml       # Default global catalog
├── artifacts/           # Auxiliary files (e.g. cached data)
├── docs/                # Rendered catalog HTML (from `catalog build`)
├── _docs/               # Temp Sphinx build dir (auto-cleaned)
└── _docs_src/           # Temp source dir (auto-cleaned)
```

### Initialize a Global Catalog

```bash
chartbook catalog init                       # Interactive — prompts for title
chartbook catalog init --title "My Catalog"  # Non-interactive
```

Creates `~/.chartbook/chartbook.toml` with a minimal skeleton:

```toml
[project]
type = "catalog"
name = "My Catalog"
maintainer = ""

[pipelines]
```

Also creates `~/.chartbook/artifacts/`. Errors if catalog already exists.

### Configure Default Catalog Path

```bash
chartbook config   # Interactive — prompts for path to an existing catalog
```

Sets `catalog.path` in `~/.chartbook/settings.toml` so that `data.load()` and CLI commands can find the catalog without an explicit `--catalog` argument.

### Catalog Path Resolution Order

1. Explicit `--catalog` flag on CLI commands (or `catalog_path=` in Python API)
2. `catalog.path` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Auto-prompt to create one (interactive TTY only)

## Managing the Catalog

### Add Pipelines

```bash
# Add a single pipeline
chartbook catalog add /path/to/pipeline

# Add all pipelines under a directory (glob expansion)
chartbook catalog add /path/to/projects/*

# Add without confirmation prompt
chartbook catalog add /path/to/projects/* -y

# Add to a specific catalog
chartbook catalog add ./my-pipeline --catalog /path/to/catalog/chartbook.toml
```

**Behavior:**
- Validates each directory contains a `chartbook.toml` that resolves to a pipeline (an empty file counts — type is inferred)
- Derives the scoped catalog key (`scope/name`) from an explicit `[project] id` if set, else from the target's git remote plus directory name, falling back to the bare directory name
- Writes the key quoted in TOML when it contains `/`: `[pipelines."ftsfr/crsp_treasury"]`
- Stores relative paths from the catalog directory in the entry's `path` key
- Detects duplicates by absolute path comparison
- Re-adding a disabled pipeline automatically re-enables it

Resulting entries look like:

```toml
[pipelines."ftsfr/crsp_treasury"]
path = "../crsp_treasury"

[pipelines."ftsfr/fed_yield_curve"]
path = "../fed_yield_curve"
disabled = true

# Platform-specific paths
[pipelines."finm/news_headlines"]
path = { unix = "/data/pipelines/news_headlines", windows = "T:/pipelines/news_headlines" }
```

### Auto-Discovery with `members` (local catalogs)

Instead of explicit entries, a catalog's `[pipelines]` table can declare membership as path patterns — new pipelines dropped into a matched directory join automatically:

```toml
[pipelines]
members = [
    "../GitRepositories/ftsfr_repos/*",
    "../GitRepositories/finm33200/news_headlines",
]
disabled = ["ftsfr/sovereign_bonds"]    # switch member pipelines off by ID
exclude = ["../GitRepositories/ftsfr_repos/scratch_*"]   # optional
```

Rules:
- Patterns resolve relative to the catalog directory; matched directories with a pipeline `chartbook.toml` join under their **derived** scoped ID.
- Glob matches skip non-pipeline directories and catalogs silently (the catalog never discovers itself); a *literal* member path that is missing/broken is a hard error.
- v1-format members and duplicate derived IDs are hard errors with "To fix" suggestions.
- Explicit entries coexist with `members`; one pointing at the same directory a pattern matched wins (rename mechanism).
- `members`, `exclude`, `disabled` are reserved keys — not usable as bare pipeline IDs.
- `catalog add` on a covered path reports "already covered by pipelines.members pattern" instead of adding an entry.

Auto-discovery targets the **local** catalog; publishing to shared catalogs should stay explicit.

### Disable / Enable Pipelines

```bash
chartbook catalog disable ftsfr/crsp_treasury [--catalog PATH]
chartbook catalog enable ftsfr/crsp_treasury [--catalog PATH]
```

For explicit entries, sets or clears `disabled = true` on the entry; for member-discovered pipelines, maintains the `pipelines.disabled` ID list. Disabled pipelines remain in the TOML file but are skipped during builds and excluded from queries.

### Catalog Policy (Required Fields)

The `chartbook.toml` format itself makes nearly all fields optional; a catalog can impose requiredness on its member pipelines via a `[policy]` section in the catalog's `chartbook.toml`:

```toml
[policy]
mode = "warn"          # "warn" (default): report on the diagnostics page
                       # "strict": fail the catalog build on missing fields

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
```

Without a `[policy]` section, a default warn-only list of recommended fields is reported on the diagnostics page. Policy is enforced only during catalog builds — standalone pipeline builds are always permissive.

### Build Catalog Documentation

```bash
chartbook catalog build              # Build HTML docs to ~/.chartbook/docs/
chartbook catalog build -f           # Force overwrite existing docs
chartbook catalog build --strict     # Error on missing files instead of skipping
```

### Browse Catalog Documentation

```bash
chartbook catalog browse   # Opens ~/.chartbook/docs/index.html in default browser
```

## Browsing the Catalog (CLI)

### List Catalog Contents

```bash
chartbook ls                    # Tree format: all pipelines, dataframes, charts
chartbook ls pipelines          # List pipelines only
chartbook ls dataframes         # List all dataframes across pipelines
chartbook ls charts             # List all charts across pipelines
chartbook ls --catalog /path/to/catalog/chartbook.toml
```

**Output format:**
```
Catalog: /path/to/catalog/chartbook.toml

[pipeline] acme/sales: Sales Analytics Pipeline
  [dataframe] acme/sales/sales_data: Sales Transactions
  [chart] acme/sales/monthly_sales: Monthly Sales Overview
```

### Access Dataframe Metadata

```bash
# Get path to a dataframe's parquet file (bare pipeline name)
chartbook data get-path --pipeline sales --dataframe sales_data

# Print documentation content for a dataframe (scoped pipeline name)
chartbook data get-docs --pipeline acme/sales --dataframe sales_data

# Get path to documentation source file
chartbook data get-docs-path --pipeline sales --dataframe sales_data
```

All `chartbook data` commands accept an optional `--catalog PATH` flag.

## Data Loading API (Python)

```python
from chartbook import data

# Load a dataframe (returns Polars LazyFrame by default) — bare pipeline name
lf = data.load(pipeline="sales", dataframe="sales_data")

# Scoped pipeline name (canonical form; required when a bare name is ambiguous)
lf = data.load(pipeline="acme/sales", dataframe="sales_data")

# Load as Polars eager DataFrame
df = data.load(pipeline="sales", dataframe="sales_data", format="polars_eager")

# Load as pandas DataFrame
df = data.load(pipeline="sales", dataframe="sales_data", format="pandas")

# Load with explicit catalog path
lf = data.load(pipeline="sales", dataframe="sales_data",
               catalog_path="/path/to/catalog/chartbook.toml")

# Get data file path
path = data.get_data_path(pipeline="sales", dataframe="sales_data")

# Get documentation content as a string
docs = data.get_docs(pipeline="sales", dataframe="sales_data")

# Get path to documentation source file
docs_path = data.get_docs_path(pipeline="sales", dataframe="sales_data")
```

### Pipeline Reference Resolution

The `pipeline` argument (and `--pipeline` CLI flag) accepts three forms:

1. **Bare name** (`crsp_treasury`) — matches any catalog entry whose name component equals it; errors listing candidates if ambiguous
2. **Scoped name** (`ftsfr/crsp_treasury`) — matches its catalog key exactly
3. **Repo URL** (`https://github.com/ftsfr/crsp_treasury`) — normalized to a scoped name

An `@rev` suffix (e.g. `ftsfr/crsp_treasury@a1b2c3d`) is reserved for future version pinning and is rejected with a "not yet supported" error.

### Format Options

| Format | Returns | Glob support |
|--------|---------|--------------|
| `"polars"` (default) | `polars.LazyFrame` via `scan_parquet(hive_partitioning=True)` | Yes |
| `"polars_eager"` | `polars.DataFrame` via `read_parquet()` | No (`ValueError`) |
| `"pandas"` | `pandas.DataFrame` via `read_parquet()` | No (`ValueError`) |

### Hive-Partitioned Data Loading

When a dataframe's `path` uses a glob pattern (e.g., `**/*.parquet`), Polars `scan_parquet` automatically detects hive directory structure and adds partition columns to the LazyFrame. Only `format="polars"` supports glob patterns.

### Catalog Path Resolution in Python

Same priority as CLI:
1. Explicit `catalog_path=` argument
2. `get_default_catalog_path()` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Raises `CatalogNotConfiguredError` — suggests running `chartbook config`

### Documentation Retrieval

`get_docs()` and `get_docs_path()` handle both documentation modes transparently:
- **`docs_path`**: Reads the external `.md` file; `get_docs_path()` returns the file path
- **`docs`** (inline string): Returns the string directly; `get_docs_path()` returns the `chartbook.toml` path

## Environment & Path Utilities (`chartbook.env`)

```python
import chartbook

# Find project root (searches for .git, pyproject.toml, .env)
BASE_DIR = chartbook.env.get_project_root()
DATA_DIR = BASE_DIR / "_data"
OUTPUT_DIR = BASE_DIR / "_output"

# Read from CLI args, environment variables, or .env file
username = chartbook.env.get("WRDS_USERNAME")
api_key = chartbook.env.get("FRED_API_KEY", default="")

# Get OS type ("nix", "windows", or "unknown")
os_type = chartbook.env.get_os_type()
```

### `chartbook.env.get()` Resolution Priority

1. Command-line arguments (`--VAR_NAME=value`)
2. Environment variables (including `.env` file via `decouple`)
3. Module defaults
4. Caller-provided `default` value
5. Error if not found

## Scaffolding New Projects

```bash
chartbook init   # Wraps cruft create — requires pip install "chartbook[all]"
```

Creates a new pipeline project from the cookiecutter template. Projects can later pull upstream template updates via `cruft update`.

## CLI Build & Publish Reference

```bash
chartbook build [OUTPUT_DIR]     # Generate HTML documentation
chartbook build -f               # Force overwrite existing output
chartbook build --strict         # Error on missing files
chartbook build --keep-build-dirs  # Keep temp build directories
chartbook publish                # Publish to directory
chartbook create-data-glimpses   # Create data summary report
```

### Build Options

```
-f, --force-write        Overwrite existing output directory
--project-dir PATH       Path to project directory
--publish-dir PATH       Directory for published files
--docs-build-dir PATH    Build directory (default: ./_docs)
--temp-docs-src-dir PATH Temporary source directory
--keep-build-dirs        Keep temporary build directories
--size-threshold FLOAT   File size threshold in MB (default: 50)
--strict                 Error on missing source files instead of skipping
--strip-mathjax2 / --no-strip-mathjax2  Strip Plotly MathJax 2 (default: enabled)
```
