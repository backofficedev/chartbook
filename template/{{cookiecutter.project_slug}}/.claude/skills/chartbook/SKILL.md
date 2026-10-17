---
name: chartbook
description: Help users work with ChartBook - a data science documentation platform for organizing pipelines, charts, and dataframes
---

# ChartBook Assistant

Use this skill when helping users with ChartBook projects for data science documentation and analytics pipeline management.

## What is ChartBook?

ChartBook is a developer platform for data science teams to discover, document, and share analytics work. It provides:
- Centralized catalog for pipelines, charts, and dataframes
- Automatic documentation website generation
- Data governance and licensing tracking
- Programmatic data loading via Python API

## Project Types

1. **Pipeline**: Single analytics project with charts and dataframes
2. **Catalog**: Collection of multiple pipelines in unified documentation

## Key CLI Commands

```bash
chartbook init              # Scaffold new project from the cookiecutter template
chartbook init --git        # ...and git init + initial commit
chartbook init --github     # ...and create a private GitHub repo with gh, then push (--public to override)
chartbook docs              # Render the HTML documentation website (was `chartbook build`)
chartbook build -f          # Make everything current: run [scripts] build, THEN render the site. In a dodo.py task, use `chartbook docs -f`, never `chartbook build`
chartbook docs -f          # Force overwrite existing docs
chartbook docs -f --incremental  # Keep _docs/ and redo only what changed since last time
chartbook docs -f --watch  # Incremental build, then rebuild on every file change (Ctrl-C to stop)
chartbook browse            # Open project docs in default browser
# every build also writes docs/index.json: one record per pipeline, dataframe, column,
# chart, notebook and note, each with an ID (scope/pipeline:kind/name) and a content hash,
# and docs/llms.txt: one line per pipeline, dataframe, chart and model with its ID and a
# link to its page (a catalog's also links every version's own llms.txt). To find your way
# around a built site or catalog, read its llms.txt first
chartbook check             # CI gate: missing metadata, broken paths, dependencies that cannot be found, expiring licenses
chartbook check --skip-outputs  # same, without requiring built data/charts/notebooks (for CI)
chartbook path <name>       # Print the path chartbook.toml declares for a dataframe
chartbook path chart/<name> # ...for a chart (also notebook/<name>, note/<name>, model/<name>)
chartbook path model/<name>@<version>  # a version of a model, in the store: by the start of its hash (@7f3a9c2e41b0) or by a label (@champion)
chartbook path <dep>:model/<name>@champion  # another pipeline's labelled version: the label as pinned in chartbook.lock; `chartbook update` moves it
chartbook path <pipeline>:<name>  # another pipeline's asset: the pinned copy (needs [dependencies] + chartbook pin)
chartbook publish           # Publish to directory
chartbook create-data-glimpses  # Create data summary report
chartbook run --snapshot    # In a pipeline OTHERS depend on: build, then declare the build ready (a snapshot). Refuses BEFORE building if anything in its folder is uncommitted
chartbook snapshot          # The second half alone: copies its built assets to the store, labelled with the commit. Takes your word that they were built by that commit. Refuses unless its pins account for every dependency (run `chartbook pin` first)
chartbook lineage           # Every snapshot upstream of this pipeline, walked through the pins and checked by hash; --check for CI, --rehash to re-hash the bytes. `chartbook snapshot --deep` refuses on an upstream gap
chartbook add acme/rates    # Declare a dependency by its ID ("acme/rates" = {} under [dependencies]) and pin its newest snapshot from the store: no folder of it, no clone; --as NAME, --commit C
chartbook pin               # Freeze what [dependencies] have: each one's newest snapshot (never its folder); hashes and commit into chartbook.lock (commit it); clones git dependencies
chartbook pin --frozen      # Writes NOTHING. Exit 1 unless chartbook.lock is complete and every pin is in the store. For CI and a read-only shared store
chartbook index diff BEFORE AFTER  # What changed between two builds from their index.json (or site folders): data, pins, versions, labels, staleness. --json, --exit-code
chartbook update [dep...]   # Move pins forward to each dependency's newest snapshot (pin never moves an existing pin)
chartbook run               # Pin what has no pin, then run this pipeline's [scripts] build. Never moves a pin. NEVER builds in a folder it depends on
chartbook run --frozen      # Pin nothing, fetch nothing, write nothing; build only if every pin is in the store (CI). Not with --snapshot
chartbook run <script>      # ...or another named script, e.g. `chartbook run test` (pins nothing)
chartbook run --force       # Also rebuild git dependencies (each is built once, in a clean copy); refreshes data they pull from outside
chartbook store verify      # Re-hash everything in the store (~/.chartbook/store, `[store] url` in settings, or CHARTBOOK_STORE; a folder or s3://bucket/prefix with chartbook[s3]); exit 1 if an object changed
chartbook store gc          # Remove old snapshots (unpinned, not the newest of their repository, unlabelled, >7 days; --keep-days) and what nothing names; lists and asks first (--dry-run, --yes); --keep-lineage keeps every snapshot upstream of a kept one; --aggressive lets git tags, branches and model labels keep nothing. A git tag names a version (snapshots record their commit's tags)
chartbook config            # Configure default catalog path (interactive)
chartbook catalog init      # Create global catalog at ~/.chartbook/chartbook.toml
chartbook catalog add <path>     # Add pipeline(s) to catalog
chartbook catalog add <glob> -y  # Add multiple pipelines without prompt
chartbook catalog disable <id>   # Disable a pipeline (skip during builds)
chartbook catalog enable <id>    # Re-enable a disabled pipeline
chartbook catalog build     # Build HTML docs for the global catalog
chartbook catalog browse    # Open global catalog docs in browser
chartbook ls                # List all pipelines, dataframes, charts
chartbook ls pipelines      # List pipelines only
chartbook ls dataframes     # List dataframes only
chartbook ls charts         # List charts only
chartbook data get-path --pipeline <id> --dataframe <id>   # Get parquet path
chartbook data get-docs --pipeline <id> --dataframe <id>   # Print docs content
chartbook data get-docs-path --pipeline <id> --dataframe <id>  # Get docs path
```

For detailed catalog management commands, browsing, and data access workflows, see **catalog_system.md**.

## Global Config Directory (`~/.chartbook/`)

```
~/.chartbook/
├── settings.toml        # User settings (catalog path override, etc.)
├── chartbook.toml       # Default global catalog
├── artifacts/           # Auxiliary files (e.g. cached data)
├── docs/                # Rendered catalog HTML (from `catalog build`)
├── _docs/               # Temp Sphinx build dir (auto-cleaned)
└── _docs_src/           # Temp source dir (auto-cleaned)
```

**Catalog path resolution order:**
1. Explicit `--catalog` flag on CLI commands
2. `catalog.path` from `~/.chartbook/settings.toml`
3. `~/.chartbook/chartbook.toml` if it exists
4. Auto-prompt to create one (interactive TTY only)

## Configuration File

Projects use `chartbook.toml` with these sections (all `[project]` keys are optional — an empty file is a valid pipeline manifest):

- `[project]`: All project metadata — name, description, maintainer, contributors, repo_url, copyright, logo/favicon, os_compatibility, build (shell script string), `site_dir` (custom site pages, defaults to `./docs_src/site/` when it exists), `enable_data_download`, `writer` (`"sphinx"` by default; `"mkdocs"` builds the site with MkDocs, `pip install chartbook[mkdocs]`)
- `[charts]`: Chart definitions with metadata
- `[dataframes]`: Data source definitions with governance info
- `[notebooks]`: Jupyter notebook references
- `[notes]`: Additional documentation
- `[pipelines]`: Pipeline registry (catalogs only, scoped keys like `"ftsfr/crsp_treasury"`)
- `[policy]`: Required-field policy (catalogs only)

Project type is inferred: a `[pipelines]` table means catalog, otherwise pipeline. An explicit `type = "pipeline"`/`"catalog"` in `[project]` is allowed; contradictions with the file structure are errors. There is no format version key.

For complete TOML field references, required fields, and full configuration examples, see **manifest_files.md**.

### Pipeline disable/enable

Pipelines in a catalog can be temporarily disabled by adding `disabled = true`:

```toml
[pipelines."ftsfr/sovereign_bonds"]
path = "../sovereign_bonds"
disabled = true
```

Disabled pipelines are skipped during builds. Use `chartbook catalog disable <id>` / `chartbook catalog enable <id>` to toggle. Re-adding a disabled pipeline with `chartbook catalog add` automatically re-enables it.

## Data Loading API

```python
from chartbook import data

# Load a dataframe (returns Polars LazyFrame by default) — bare pipeline name
lf = data.load(pipeline="crsp_treasury", dataframe="my_data")

# Scoped pipeline name (canonical; required when a bare name is ambiguous)
lf = data.load(pipeline="ftsfr/crsp_treasury", dataframe="my_data")

# Load as Polars eager DataFrame
df = data.load(pipeline="crsp_treasury", dataframe="my_data", format="polars_eager")

# Load as pandas DataFrame
df = data.load(pipeline="crsp_treasury", dataframe="my_data", format="pandas")

# Load with explicit catalog path
lf = data.load(pipeline="crsp_treasury", dataframe="my_data", catalog_path="/path/to/catalog")
# Through a catalog, it is the pipeline's NEWEST SNAPSHOT in the store (its pin, in a pipeline
# that declares it); with no snapshot, its working folder, with a WorkingVersionWarning.

# Get data file path (through the catalog)
path = data.get_data_path(pipeline="crsp_treasury", dataframe="my_data")

# Inside a pipeline: the path its own chartbook.toml declares for a dataframe.
# No catalog needed; the file need not exist yet, so use it for dodo.py targets
# and for writing outputs.
df.to_parquet(data.path("my_data"))

# The same for any other asset: put its kind in front of the name
# (chart/, notebook/, note/). data.path(x) is assets.path(x, kind="dataframe").
from chartbook import assets
fig.write_html(assets.path("chart/my_chart"))

# A trained model is declared in [models.<id>] (path, trained_on, metrics_path,
# docs_path) and gets a page with its scores and lineage. ChartBook never loads
# a model; it hands out the path.
from chartbook import models
joblib.dump(model, models.path("my_model"))
# A VERSION of a model is made by a snapshot (`chartbook run --snapshot`), named by
# the start of its content hash, and labelled in chartbook.toml:
#   [models.my_model.aliases]
#   champion = "7f3a9c2e41b0"
# models.path("my_model@champion") is that version in the store (read-only);
# models.versions("my_model") lists them with their scores and commits.

# Another pipeline this one reads from is declared in chartbook.toml:
#   [dependencies]
#   "ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
# The other pipeline's owner declares a build ready there: `chartbook snapshot`
# (everything committed first). Then here: `chartbook pin` (writes chartbook.lock;
# commit it), or `chartbook run`, which pins what has no pin and builds THIS pipeline,
# or just a first data.load(), which pins it and says so on stderr. Before a pin:
#   declared, not pinned      -> pinned now to its newest snapshot (a git one: `chartbook pin`)
#   not in [dependencies]     -> its newest snapshot + UnrecordedReadWarning; `chartbook add <id>`
#   no snapshot, folder here  -> its WORKING version + WorkingVersionWarning
#   no chartbook.toml at all  -> its newest snapshot, silently
# In a build under `chartbook run` (CHARTBOOK_BATCH=1) only a pin is read; the others are errors. After that,
# "pipeline:name" is that pipeline's asset AS PINNED: a frozen copy in the store,
# not its working directory. It changes only on `chartbook update`. Read-only.
rates = data.load("fed_yield_curve:treasury_rates")           # LazyFrame, pinned copy
path = data.path("fed_yield_curve:treasury_rates")            # its path in the store
chart = assets.path("fed_yield_curve:chart/curve_today")      # any kind of asset
mine = data.load("my_data")                                   # this pipeline's own, live
# ChartBook NEVER selects columns or rows. "my_data#col" is an address for
# documenting a column and is refused by data.load()/data.path(). Load or locate
# the whole dataframe, then use polars or SQL:
one = data.load("my_data").select("date", "DGS10")
# SQL: name dataframes in braces; ChartBook substitutes names and the engine runs the rest
# (DuckDB for files and DuckDB sources; the warehouse for a databricks source).
# A file is read_parquet('…'), a [sources] table its identifier, a query a sub-select.
joined = data.sql("select a.date, a.x, b.y from {my_data} a join {other} b using (date)")
# A literal brace is written twice: data.sql("select {{'a': 1}} s from {my_data}")
data.ref("my_data")        # the name to paste into SQL you run yourself
data.connect("local")      # the raw connection to [sources.local]: read-only duckdb, or the Databricks connector's
# A dataframe may live in a source instead of a file (then it has no path):
#   [sources.local]            backend = "duckdb"   url = "duckdb:///./_data/x.duckdb"
#   (or backend = "databricks", url = "databricks://<host>?http_path=...", token from DATABRICKS_TOKEN)
#   [dataframes.slopes]        source = "local"     query = "select ... from t"   # or table = "t"
# A model's trained_on = ["fed_yield_curve:treasury_rates"] must name a declared
# dependency; `chartbook check` verifies the dataframe exists there.

# A throwaway directory for intermediates (<pipeline>/_data/_scratch/):
# not an asset, git-ignored, safe to delete
tmp = data.scratch() / "raw_download.csv"

# Get documentation content as a string
docs = data.get_docs(pipeline="crsp_treasury", dataframe="my_data")

# Get path to documentation source file
docs_path = data.get_docs_path(pipeline="crsp_treasury", dataframe="my_data")
```

The `pipeline` argument accepts a bare name (resolved against the catalog when unambiguous), a scoped name (`scope/name`), or a repo URL (normalized to a scoped name). An `@rev` suffix and a registry prefix (`registry.example/scope/name`) are reserved but not yet supported.

For advanced loading options, format details, and catalog setup, see **catalog_system.md**.

### Hive-Partitioned Data

Use glob patterns in the dataframe `path` field for hive-partitioned datasets:

```toml
[dataframes.my_data]
path = "./_data/hive_dataset/**/*.parquet"
docs = "Hive-partitioned dataset."
```

Polars `scan_parquet` handles glob patterns natively with automatic hive partitioning. Glob paths only support `format="polars"` (LazyFrame).

## Directory Structure

```
my-pipeline/
├── chartbook.toml       # Configuration
├── _data/               # Parquet data files
├── _output/             # Generated HTML charts
├── docs_src/            # Markdown documentation
│   ├── charts/
│   ├── dataframes/
│   └── site/            # (Optional) Custom site pages (site_dir)
│       ├── index_toc.md # Controls toctree injection into index page
│       └── *.md         # Custom markdown pages
└── src/                 # Python source code
```

## Plotting API

```python
import chartbook

# Basic charts — returns ChartResult with .show() and .save(chart_id)
chartbook.plotting.line(df, x="date", y="value", title="GDP")
chartbook.plotting.bar(df, x="category", y="amount")
chartbook.plotting.scatter(df, x="x", y="y")
chartbook.plotting.pie(df, names="category", values="amount")
chartbook.plotting.area(df, x="date", y="value")

# Dual-axis chart
chartbook.plotting.dual(df, x="date", left_y="gdp", right_y="rate",
                         left_type="bar", right_type="line")

# Configuration
chartbook.plotting.configure(nber_recessions=True, default_output_dir="./_output")
chartbook.plotting.set_style("chartbook")
```

Included in every install (`pip install chartbook`).

## Quick Start Configuration

```toml
[project]
name = "My Pipeline"
description = "Description"
maintainer = "Your Name"
# id = "myorg/my_pipeline"       # Optional: scoped ID (default derived from git remote + dirname)
# site_dir = "./docs_src/site/"  # Optional: default when the directory exists
# writer = "mkdocs"              # Optional: build the site with MkDocs instead of Sphinx (pip install chartbook[mkdocs])
```

Every key is optional — an empty `chartbook.toml` is a valid pipeline manifest.

## Troubleshooting

- **Module Not Found**: Run `pip show chartbook` to verify installation
- **Permission Errors**: On Windows, run as administrator
- **Sphinx Build Errors**: Check all required files exist
- **Path Errors**: Use relative paths from project root
- **TOML Syntax**: Validate with online TOML validators
- **site_dir errors**: Ensure the directory exists and does not contain a `cb/` subdirectory (reserved namespace)
