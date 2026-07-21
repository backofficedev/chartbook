# CLI Reference

The chartbook command-line interface provides tools for generating documentation and managing pipelines.

## Installation

The CLI commands require Sphinx dependencies. Choose one of these installation methods:

**Recommended** (isolated installation, no dependency pollution):

```console
# Install globally via pipx
pipx install chartbook

# Or run without installing
pipx run chartbook build
uvx chartbook build
```

**Alternative** (installs dependencies in current environment):

```console
pip install "chartbook[sphinx]"
```

If you run CLI commands without Sphinx dependencies installed, you'll see a helpful error message with installation instructions.

## Global Usage

```console
chartbook [OPTIONS] COMMAND [ARGS]...
```

## Commands Overview

| Command | Description |
|---------|-------------|
| `init` | Scaffold a new chartbook project from a template |
| `build` | Generate HTML documentation website |
| `browse` | Open project documentation in your default browser |
| `publish` | Publish pipeline to a directory |
| `create-data-glimpses` | Create data glimpse reports |
| `config` | Configure the default catalog path for data loading |
| `install` | Install bundled resources (e.g., Claude skill) |
| `catalog` | Manage the catalog (add pipelines) |
| `ls` | List catalog objects (pipelines, dataframes, charts) |
| `data` | Data operations (get paths, docs) |

## Command Reference

### `chartbook init`

Scaffold a new chartbook project from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook) using [cruft](https://cruft.github.io/cruft/). Because the project is created with cruft, you can later pull upstream template updates with `cruft update`.

```console
chartbook init
```

This command requires `cruft`, which is included in the `all` extra:

```console
pip install "chartbook[all]"
```

**Example session:**

```console
$ chartbook init
# Cruft will prompt you to fill in the template variables
# (project name, author, etc.) and then create the project directory.
```

### `chartbook build`

Generate HTML documentation in the specified output directory.

```console
chartbook build [OPTIONS] [OUTPUT_DIR]
```

**Arguments:**
- `OUTPUT_DIR`: Directory where HTML will be generated (default: `./docs`)

**Options:**
- `-f, --force-write`: Overwrite existing output directory
- `--project-dir PATH`: Path to project directory
- `--publish-dir PATH`: Directory for published files (default: `./_output/to_be_published/`)
- `--docs-build-dir PATH`: Build directory (default: `./_docs`)
- `--temp-docs-src-dir PATH`: Temporary source directory (default: `./_docs_src`)
- `--keep-build-dirs`: Keep temporary build directories after generation. See {doc}`user-guide/build-pipeline` for details on what these directories contain
- `--size-threshold FLOAT`: File size threshold in MB above which to use memory-efficient loading (default: 50)

**Examples:**

```console
# Basic usage
chartbook build

# Force overwrite existing docs
chartbook build -f

# Generate in custom directory
chartbook build ./my-docs --force-write

# Keep build directories for debugging
chartbook build --keep-build-dirs
```

### `chartbook browse`

Open the project documentation in your default web browser. Works on macOS, Windows, and Linux.

```console
chartbook browse [OUTPUT_DIR] [OPTIONS]
```

**Arguments:**
- `OUTPUT_DIR`: Directory containing the generated HTML (default: `./docs`)

**Options:**
- `--project-dir PATH`: Path to project directory

**Examples:**

```console
# Open docs from default location
chartbook browse

# Open docs from a custom output directory
chartbook browse ./my-docs

# Open docs for a project in another directory
chartbook browse --project-dir /path/to/project
```

### `chartbook publish`

Publish the documentation to a specified directory.

```console
chartbook publish [OPTIONS]
```

**Options:**
- `--publish-dir PATH`: Directory where files will be published
- `--project-dir PATH`: Path to project directory
- `-v, --verbose`: Enable verbose output

**Examples:**

```console
# Publish to default location
chartbook publish

# Publish to custom directory
chartbook publish --publish-dir /path/to/publish

# Publish with verbose output
chartbook publish -v
```

### `chartbook create-data-glimpses`

Create a comprehensive data glimpse report from dodo.py tasks.

```console
chartbook create-data-glimpses [OPTIONS]
```

**Options:**
- `--no-samples`: Exclude sample values from report
- `--no-stats`: Exclude numeric statistics from report
- `-o, --output-dir PATH`: Directory to save output file (default: current directory)
- `--size-threshold FLOAT`: File size threshold in MB above which to use memory-efficient loading (default: 50)

**Examples:**

```console
# Basic usage (creates data_glimpses.md)
chartbook create-data-glimpses

# Exclude sample values
chartbook create-data-glimpses --no-samples

# Exclude both samples and statistics
chartbook create-data-glimpses --no-samples --no-stats

# Save to specific directory
chartbook create-data-glimpses -o ./docs/

# Or using long form
chartbook create-data-glimpses --output-dir ./reports/

# Use a larger threshold for memory-efficient loading (100 MB)
chartbook create-data-glimpses --size-threshold 100
```

The report includes:
- Summary of datasets organized by task
- File metadata (size, type, shape)
- Column information with data types and null percentages
- Sample values (first 5 rows)
- Numeric column statistics (min, max, mean, median)

For large files (above the size threshold), the command uses memory-efficient loading by only collecting sampled data while still reporting the correct total row count.

### `chartbook config`

Configure the default catalog path for data loading. Sets the path to a catalog's `chartbook.toml` in `~/.chartbook/settings.toml` so that `data.load()` can locate pipelines without an explicit `catalog_path` argument.

```console
chartbook config
```

The command will:
1. Show the current catalog path if one is already configured
2. Prompt for the path to a catalog `chartbook.toml` (or its parent directory)
3. Validate the path exists and is a catalog-type manifest
4. Write the setting to `~/.chartbook/settings.toml`

**Example session:**

```console
$ chartbook config
Path to catalog chartbook.toml (or its parent directory): /data/my-catalog
Catalog path set to: /data/my-catalog/chartbook.toml

You can now load data with:
  from chartbook import data
  df = data.load(pipeline="my_pipeline", dataframe="my_df")
```

### `chartbook install`

Install bundled resources into the current project.

```console
chartbook install COMMAND [OPTIONS]
```

**Subcommands:**
- `skill`: Install the Claude Code skill

#### `chartbook install skill`

Copy the bundled Claude Code skill files into `.claude/skills/chartbook/` in the current directory. This gives Claude context about chartbook's CLI, configuration, and data loading API so it can assist with your project.

```console
chartbook install skill [OPTIONS]
```

**Options:**
- `-f, --force`: Overwrite existing skill files without prompting

**Examples:**

```console
# Install the skill
chartbook install skill

# Overwrite existing skill files
chartbook install skill -f
```

### `chartbook catalog`

Manage the chartbook catalog.

```console
chartbook catalog COMMAND [OPTIONS]
```

**Subcommands:**
- `init`: Initialize the global catalog at `~/.chartbook/chartbook.toml`
- `add`: Add pipeline directory(ies) to the catalog

#### `chartbook catalog init`

Create a minimal global catalog with an empty `[pipelines]` section. Use `chartbook catalog add` to add pipelines afterwards.

```console
chartbook catalog init [--title TITLE]
```

#### `chartbook catalog add`

Add one or more pipeline directories to the catalog. Each directory must contain a pipeline `chartbook.toml` (the project type is inferred from the file; directories with old v1-format files or catalog-type manifests are skipped). Paths are stored relative to the catalog directory.

The catalog key is the pipeline's scoped ID (`scope/name`), derived from the target's `[project] id` if set, otherwise from its git `origin` remote plus the directory name, falling back to the bare directory name when there is no remote.

```console
chartbook catalog add [OPTIONS] PATHS...
```

**Arguments:**
- `PATHS`: One or more directories (or glob patterns) containing pipeline `chartbook.toml` files

**Options:**
- `--catalog PATH`: Path to catalog `chartbook.toml` (uses configured default if not specified)
- `-y, --yes`: Skip confirmation prompt when adding multiple pipelines

The command will:
1. Verify each path contains a valid pipeline `chartbook.toml`
2. Derive the scoped catalog key from the pipeline's git remote and directory name
3. Check for duplicates against existing catalog entries (comparing resolved absolute paths)
4. Prompt for confirmation when adding multiple pipelines (unless `-y` is used)
5. Store paths relative to the catalog directory

**Examples:**

```console
# Add a single pipeline
chartbook catalog add /path/to/my-pipeline

# Add all pipelines in a directory using a glob pattern
chartbook catalog add /path/to/projects/*

# Add multiple pipelines without confirmation prompt
chartbook catalog add /path/to/projects/* -y

# Add to a specific catalog (instead of the default)
chartbook catalog add /path/to/pipeline --catalog /path/to/catalog/chartbook.toml

# Add multiple specific directories
chartbook catalog add ./proj1 ./proj2 ./proj3
```

**Example output:**

```console
$ chartbook catalog add /data/projects/*
  Skipping assets/ (no chartbook.toml)
  Already in catalog as 'acme/yield_curve': yield_curve/

Pipelines to add:
  acme/fred_charts: FRED Charts (/data/projects/fred_charts)
  acme/macro_data: Macro Economic Data (/data/projects/macro_data)

Add 2 pipeline(s)? [y/N]: y
  Added 'acme/fred_charts': FRED Charts (../projects/fred_charts)
  Added 'acme/macro_data': Macro Economic Data (../projects/macro_data)

Added 2 pipeline(s) to /data/catalog/chartbook.toml
```

### `chartbook ls`

List catalog objects (pipelines, dataframes, charts). Without a subcommand, displays all objects in a tree format.

```console
chartbook ls [OPTIONS] [COMMAND]
```

**Options:**
- `--catalog PATH`: Path to catalog `chartbook.toml` (uses configured default if not specified)

**Subcommands:**
- `pipelines`: List pipelines only
- `dataframes`: List all dataframes across pipelines
- `charts`: List all charts across pipelines

**Examples:**

```console
# List all objects in tree format
chartbook ls

# List pipelines only
chartbook ls pipelines

# List all dataframes
chartbook ls dataframes

# List all charts
chartbook ls charts

# Use a specific catalog
chartbook ls --catalog /path/to/chartbook.toml
```

**Example output:**

Pipelines are listed under their scoped catalog keys (`scope/name`):

```console
$ chartbook ls
Catalog: /data/my-catalog/chartbook.toml

[pipeline] acme/yield_curve: Yield Curve Analysis
  [dataframe] acme/yield_curve/repo_public: Repo Public Data
  [dataframe] acme/yield_curve/treasury_rates: Treasury Rates
  [chart] acme/yield_curve/yield_spread: Yield Spread Chart
[pipeline] acme/macro_data: Macro Economic Data
  [dataframe] acme/macro_data/gdp_quarterly: GDP Quarterly
```

### `chartbook data`

Data operations for retrieving paths and documentation for dataframes.

```console
chartbook data COMMAND [OPTIONS]
```

**Subcommands:**

#### `chartbook data get-path`

Get the path to a dataframe's parquet file.

```console
chartbook data get-path --pipeline PIPELINE --dataframe DATAFRAME [--catalog PATH]
```

**Options:**
- `--pipeline`: Pipeline reference (required) — a bare name (if unambiguous), scoped ID (`scope/name`), or repo URL
- `--dataframe`: Dataframe ID (required)
- `--catalog PATH`: Path to catalog `chartbook.toml`

#### `chartbook data get-docs`

Print documentation content for a dataframe.

```console
chartbook data get-docs --pipeline PIPELINE --dataframe DATAFRAME [--catalog PATH]
```

**Options:**
- `--pipeline`: Pipeline reference (required) — a bare name (if unambiguous), scoped ID (`scope/name`), or repo URL
- `--dataframe`: Dataframe ID (required)
- `--catalog PATH`: Path to catalog `chartbook.toml`

#### `chartbook data get-docs-path`

Get the path to a dataframe's documentation source file.

```console
chartbook data get-docs-path --pipeline PIPELINE --dataframe DATAFRAME [--catalog PATH]
```

**Options:**
- `--pipeline`: Pipeline reference (required) — a bare name (if unambiguous), scoped ID (`scope/name`), or repo URL
- `--dataframe`: Dataframe ID (required)
- `--catalog PATH`: Path to catalog `chartbook.toml`

**Examples:**

A bare pipeline name resolves against the catalog when exactly one entry matches; if several scopes share the name, the command errors and lists the candidates so you can qualify (e.g. `acme/yield_curve`).

```console
# Get path to a dataframe's parquet file (bare name, unambiguous)
chartbook data get-path --pipeline yield_curve --dataframe repo_public
# Output: /data/my-catalog/yield_curve/_output/repo_public.parquet

# Fully qualified with a scoped ID
chartbook data get-path --pipeline acme/yield_curve --dataframe repo_public

# Print documentation for a dataframe
chartbook data get-docs --pipeline yield_curve --dataframe repo_public

# Get path to documentation source
chartbook data get-docs-path --pipeline yield_curve --dataframe repo_public
# Output: /data/my-catalog/yield_curve/docs_src/dataframes/repo_public.md

# Use a specific catalog
chartbook data get-path --pipeline macro_data --dataframe gdp_quarterly --catalog /path/to/chartbook.toml
```

## Environment Variables

chartbook uses several environment variables for configuration:

| Variable | Description |
|----------|-------------|
| `OS_TYPE` | Operating system type (`windows` or `nix`) |
| `BASE_DIR` | Base directory for the project |
| `DATA_DIR` | Directory for data files |
| `OUTPUT_DIR` | Directory for output files |

## Configuration File

chartbook looks for a `chartbook.toml` file in the project directory. See the {doc}`configuration` guide for details.

## Exit Codes

- `0`: Success
- `1`: General error
- `2`: Configuration error
- `3`: File not found

## Common Workflows

### Documentation Generation Workflow

```console
# 1. Generate data (using your own scripts/doit)
doit

# 2. Generate documentation
chartbook build -f

# 3. Publish to production
chartbook publish
```

### Development Workflow

```console
# 1. Create data glimpse report
chartbook create-data-glimpses -o ./docs/

# 2. Generate docs with build dirs kept
chartbook build --keep-build-dirs

# 3. Open in browser
chartbook browse
```
