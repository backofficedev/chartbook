# ChartBook Reference

Complete configuration reference and examples for ChartBook projects.

## Installation

```bash
# Data loading only
pip install chartbook

# CLI (recommended - isolated)
pipx install chartbook

# CLI with pip
pip install chartbook[sphinx]

# Full install (recommended — includes data, plotting, sphinx, and cruft)
pip install "chartbook[all]"

# Development
pip install -e ".[dev]"
```

## Complete Pipeline Configuration

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.9"

[site]
title = "Sales Analytics Pipeline"
author = "Analytics Team"
copyright = "2026, My Company"
logo_path = "./assets/logo.png"
favicon_path = "./assets/favicon.ico"

[pipeline]
id = "SALES"
pipeline_name = "Sales Analytics Pipeline"
pipeline_description = "End-to-end sales analytics and reporting"
lead_pipeline_developer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
software_modules_command = "module load python/3.11"
runs_on_grid_or_windows_or_other = "Windows/Linux"
git_repo_URL = "https://github.com/org/sales-analytics"
README_file_path = "./README.md"

[charts.monthly_sales]
chart_name = "Monthly Sales Overview"
short_description_chart = "Total sales by month with YoY comparison"
dataframe_id = "sales_data"
topic_tags = ["Sales", "Monthly", "Revenue"]
data_frequency = "Monthly"
observation_period = "Month-end"
lag_in_data_release = "5 days"
seasonal_adjustment = "None"
units = "USD"
data_series = ["Gross Sales", "Net Sales"]
mnemonic = "SALES_MO"
date_cleared_by_iv_and_v = "2025-01-15"
last_legal_clearance_date = "2025-01-10"
last_cleared_by = "Legal Team"
past_publications = [
    "[Q4 Report 2024, p15](https://example.com/q4)",
]
path_to_html_chart = "./_output/monthly_sales.html"
path_to_excel_chart = "./excel/monthly_sales.xlsx"
chart_docs_path = "./docs_src/charts/monthly_sales.md"

[dataframes.sales_data]
dataframe_name = "Sales Transactions"
short_description_df = "Detailed sales transaction data"
data_sources = ["CRM System", "ERP System"]
data_providers = ["Sales Team", "Finance Team"]
links_to_data_providers = [
    "https://internal.company.com/crm",
    "https://internal.company.com/erp"
]
type_of_data_access = ["Internal", "Internal"]
need_to_contact_provider = ["No", "No"]
data_on_pre_approved_list = ["Yes", "Yes"]
data_license = "Internal Use Only"
license_expiration_date = "2025-12-31"
provider_contact_info = "data-team@company.com"
restriction_on_use = "Internal analytics only"
how_is_pulled = "SQL query via Python"
topic_tags = ["Sales", "Transactions", "Revenue"]
date_col = "transaction_date"
path_to_parquet_data = "./_data/sales_data.parquet"
path_to_excel_data = "./_data/sales_data.xlsx"
dataframe_docs_path = "./docs_src/dataframes/sales_data.md"

[notebooks.exploratory]
notebook_name = "Exploratory Data Analysis"
notebook_description = "Initial exploration of sales patterns"
notebook_path = "_output/01_exploratory.ipynb"

[notes.methodology]
path_to_markdown_file = "./docs_src/methodology.md"
```

## Catalog Configuration

```toml
[config]
type = "catalog"
chartbook_format_version = "0.0.9"

[site]
title = "Company Analytics Catalog"
author = "Data Team"
copyright = "2026"

[pipelines.SALES]
path_to_pipeline = "../pipelines/sales"

[pipelines.MARKETING]
path_to_pipeline = "../pipelines/marketing"

# Platform-specific paths
[pipelines.FINANCE]
Unix = "/data/pipelines/finance"
Windows = "T:/pipelines/finance"
```

## CLI Reference

### chartbook init

Initialize a new chartbook project from the cookiecutter template. Wraps `cruft create` so projects can later pull upstream template updates.

Requires `pip install "chartbook[all]"` (includes `cruft`).

### chartbook build

```bash
chartbook build [OPTIONS] [OUTPUT_DIR]

Options:
  -f, --force-write        Overwrite existing output directory
  --project-dir PATH       Path to project directory
  --publish-dir PATH       Directory for published files
  --docs-build-dir PATH    Build directory (default: ./_docs)
  --temp-docs-src-dir PATH Temporary source directory
  --keep-build-dirs        Keep temporary build directories
  --size-threshold FLOAT   File size threshold in MB (default: 50)
  --warn-missing           Warn instead of error when source files are missing
  --strip-mathjax2 / --no-strip-mathjax2
                           Strip Plotly MathJax 2 from notebooks (default: enabled)
```

### chartbook publish

```bash
chartbook publish [OPTIONS]

Options:
  --publish-dir PATH   Directory where files will be published
  --project-dir PATH   Path to project directory
  -v, --verbose        Enable verbose output
```

### chartbook create-data-glimpses

```bash
chartbook create-data-glimpses [OPTIONS]

Options:
  --no-samples           Exclude sample values
  --no-stats             Exclude numeric statistics
  -o, --output-dir PATH  Directory to save output file
  --size-threshold FLOAT File size threshold in MB (default: 50)
```

### chartbook ls

List catalog objects (pipelines, dataframes, charts).

```bash
chartbook ls [OPTIONS] [COMMAND]

Commands:
  pipelines    List all pipelines
  dataframes   List all dataframes across pipelines
  charts       List all charts across pipelines

Options:
  --catalog PATH   Path to catalog chartbook.toml (overrides default)
```

**Examples:**
```bash
chartbook ls                    # List all objects in tree format
chartbook ls pipelines          # List pipelines only
chartbook ls dataframes         # List all dataframes
chartbook ls charts             # List all charts
chartbook ls --catalog /path/to/catalog/chartbook.toml
```

### chartbook data

Data operations for accessing dataframe paths and documentation.

```bash
chartbook data COMMAND [OPTIONS]

Commands:
  get-path       Get the path to a dataframe's parquet file
  get-docs       Print documentation content for a dataframe
  get-docs-path  Get the path to a dataframe's documentation source

Options (for all commands):
  --pipeline PIPELINE    Pipeline ID (required)
  --dataframe DATAFRAME  Dataframe ID (required)
  --catalog PATH         Path to catalog chartbook.toml (optional)
```

**Examples:**
```bash
chartbook data get-path --pipeline sales --dataframe transactions
chartbook data get-docs --pipeline sales --dataframe transactions
chartbook data get-docs-path --pipeline sales --dataframe transactions
```

### chartbook config

Configure the default catalog path for data loading. Sets the path to a catalog's `chartbook.toml` in `~/.chartbook/settings.toml` so that `data.load()` can find pipelines without an explicit `catalog_path` argument.

Prompts interactively for the catalog path.

## Data Loading Examples

```python
from chartbook import data

# Basic loading
df = data.load(pipeline="SALES", dataframe="sales_data")

# With format specification
df = data.load(pipeline="SALES", dataframe="sales_data", format="polars")

# Load as Polars LazyFrame
lf = data.load(pipeline="SALES", dataframe="sales_data", format="polars-lazyframe")

# Load with explicit catalog path
df = data.load(pipeline="SALES", dataframe="sales_data",
               catalog_path="/path/to/catalog/chartbook.toml")

# Get data file path
path = data.get_data_path(pipeline="SALES", dataframe="sales_data")

# Get documentation content as a string
docs = data.get_docs(pipeline="SALES", dataframe="sales_data")

# Get path to documentation source file
docs_path = data.get_docs_path(pipeline="SALES", dataframe="sales_data")
```

## Chart Field Reference

| Field | Description |
|-------|-------------|
| `chart_name` | Human-readable chart name |
| `short_description_chart` | Brief description |
| `dataframe_id` | Links to dataframe definition |
| `topic_tags` | List of topic tags |
| `data_frequency` | Daily, Weekly, Monthly, Quarterly, Annual |
| `observation_period` | When measurement taken |
| `lag_in_data_release` | Delay until data available |
| `data_release_timing` | When data is typically released |
| `seasonal_adjustment` | None, X-13ARIMA-SEATS, etc. |
| `units` | Units of measurement |
| `data_series` | List of data series names |
| `data_series_start_date` | Start date of the data series |
| `mnemonic` | Short identifier |
| `date_cleared_by_iv_and_v` | Internal validation date |
| `last_legal_clearance_date` | Legal review date |
| `last_cleared_by` | Approver name |
| `past_publications` | List of previous uses |
| `path_to_html_chart` | Path to HTML chart file |
| `path_to_excel_chart` | Path to Excel file |
| `chart_docs_path` | Path to documentation (mutually exclusive with `chart_docs_str`) |

## Dataframe Field Reference

| Field | Description |
|-------|-------------|
| `dataframe_name` | Human-readable name |
| `short_description_df` | Brief description |
| `data_sources` | List of data sources |
| `data_providers` | List of providers |
| `links_to_data_providers` | Provider URLs |
| `type_of_data_access` | Access types per source |
| `need_to_contact_provider` | Contact requirements |
| `data_on_pre_approved_list` | Pre-approval status |
| `data_license` | License agreement |
| `license_expiration_date` | License expiry |
| `provider_contact_info` | Contact information |
| `restriction_on_use` | Usage restrictions |
| `how_is_pulled` | Data collection method |
| `topic_tags` | List of topic tags |
| `date_col` | Date column name |
| `path_to_parquet_data` | Path to Parquet file |
| `path_to_excel_data` | Path to Excel file |
| `dataframe_docs_path` | Path to documentation (mutually exclusive with `dataframe_docs_str`) |

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

## Plotting (`chartbook.plotting`)

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

Requires `pip install "chartbook[plotting]"` or `pip install "chartbook[all]"`.

## Common Workflows

### Generate and Publish

```bash
doit                    # Run task automation
chartbook build -f  # Generate documentation
chartbook publish      # Publish to production
```

### Development

```bash
chartbook create-data-glimpses -o ./docs/
chartbook build --keep-build-dirs
python -m http.server -d ./docs
```

## Troubleshooting

- **Module Not Found**: Run `pip show chartbook` to verify installation
- **Permission Errors**: On Windows, run as administrator
- **Sphinx Build Errors**: Check all required files exist
- **Path Errors**: Use relative paths from project root
- **TOML Syntax**: Validate with online TOML validators

## Required Fields

### Site
The `[site]` section configures website metadata. Since v0.0.7, `logo_path` and `favicon_path` are optional (default assets are used when omitted):

```toml
[site]
title = "My Project"
author = "Author Name"
copyright = "2026"
# logo_path and favicon_path are optional (defaults provided)
```

### Dataframes
Dataframes have specific required fields that will cause build errors if missing:

| Field | Required | Notes |
|-------|----------|-------|
| `path_to_parquet_data` | Yes | Path to the parquet file (not `path`) |
| `dataframe_docs_path` OR `dataframe_docs_str` | Yes (one of) | Documentation is required - use `dataframe_docs_path` for external markdown file or `dataframe_docs_str` for inline documentation |

**Minimal dataframe example:**
```toml
[dataframes.my_data]
dataframe_name = "My Dataset"
short_description_df = "Brief description"
path_to_parquet_data = "_data/my_data.parquet"
dataframe_docs_str = "Detailed documentation about this dataset, its columns, and usage."
```

### Charts
Charts also require documentation:

| Field | Required | Notes |
|-------|----------|-------|
| `path_to_html_chart` | Yes | Path to the HTML chart file |
| `chart_docs_path` OR `chart_docs_str` | Yes (one of) | Documentation is required |

### Notebooks
Notebooks have a simpler structure:

```toml
[notebooks.my_notebook]
notebook_name = "My Notebook Title"
notebook_description = "What this notebook does"
notebook_path = "_output/my_notebook.html"
```
