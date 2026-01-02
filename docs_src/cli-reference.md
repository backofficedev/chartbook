# CLI Reference

The chartbook command-line interface provides tools for generating documentation and managing pipelines.

## Installation

The CLI commands require Sphinx dependencies. Choose one of these installation methods:

**Recommended** (isolated installation, no dependency pollution):

```console
# Install globally via pipx
pipx install chartbook

# Or run without installing
pipx run chartbook generate
uvx chartbook generate
```

**Alternative** (installs dependencies in current environment):

```console
pip install chartbook[sphinx]
```

If you run CLI commands without Sphinx dependencies installed, you'll see a helpful error message with installation instructions.

## Global Usage

```console
chartbook [OPTIONS] COMMAND [ARGS]...
```

## Commands Overview

| Command | Description |
|---------|-------------|
| `generate` | Generate HTML documentation website |
| `publish` | Publish pipeline to a directory |
| `create-data-glimpses` | Create data glimpse reports |

## Command Reference

### `chartbook generate`

Generate HTML documentation in the specified output directory.

```console
chartbook generate [OPTIONS] [OUTPUT_DIR]
```

**Arguments:**
- `OUTPUT_DIR`: Directory where HTML will be generated (default: `./docs`)

**Options:**
- `-f, --force-write`: Overwrite existing output directory
- `--project-dir PATH`: Path to project directory
- `--publish-dir PATH`: Directory for published files (default: `./_output/to_be_published/`)
- `--docs-build-dir PATH`: Build directory (default: `./_docs`)
- `--temp-docs-src-dir PATH`: Temporary source directory (default: `./_docs_src`)
- `--keep-build-dirs`: Keep temporary build directories after generation
- `--size-threshold FLOAT`: File size threshold in MB above which to use memory-efficient loading (default: 50)

**Examples:**

```console
# Basic usage
chartbook generate

# Force overwrite existing docs
chartbook generate -f

# Generate in custom directory
chartbook generate ./my-docs --force-write

# Keep build directories for debugging
chartbook generate --keep-build-dirs
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
chartbook generate -f

# 3. Publish to production
chartbook publish
```

### Development Workflow

```console
# 1. Create data glimpse report
chartbook create-data-glimpses -o ./docs/

# 2. Generate docs with build dirs kept
chartbook generate --keep-build-dirs

# 3. Test locally
python -m http.server -d ./docs
```
