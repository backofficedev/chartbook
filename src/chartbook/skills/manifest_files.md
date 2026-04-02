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

## Complete Pipeline Configuration

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.19"

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
site_dir = "./docs_src/site/"

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
notebook_description = "Initial exploration of sales patterns"
notebook_path = "_output/01_exploratory.ipynb"

[notes.methodology]
path_to_markdown_file = "./docs_src/methodology.md"
```

## Catalog Configuration

A catalog aggregates multiple pipelines into unified documentation.

```toml
[config]
type = "catalog"
chartbook_format_version = "0.0.19"

[site]
title = "Company Analytics Catalog"
author = "Data Team"
copyright = "2026"

[pipelines.SALES]
path_to_pipeline = "../pipelines/sales"

[pipelines.MARKETING]
path_to_pipeline = "../pipelines/marketing"

# Disabled pipeline — skipped during builds
[pipelines.BROKEN_PIPELINE]
path_to_pipeline = "../pipelines/broken"
disabled = true

# Platform-specific paths
[pipelines.FINANCE]
Unix = "/data/pipelines/finance"
Windows = "T:/pipelines/finance"
```

## Required Fields

### Site

The `[site]` section configures website metadata. `logo_path` and `favicon_path` are optional (default assets used when omitted):

```toml
[site]
title = "My Project"        # Required
author = "Author Name"      # Required
copyright = "2026"          # Required
# logo_path and favicon_path are optional (defaults provided)
```

### Dataframes

| Field | Required | Notes |
|-------|----------|-------|
| `path_to_parquet_data` | Yes | Path to parquet file or glob pattern for hive-partitioned data |
| `dataframe_docs_path` OR `dataframe_docs_str` | Yes (one of) | Use `dataframe_docs_path` for external markdown or `dataframe_docs_str` for inline docs. Mutually exclusive. |

**Minimal dataframe example:**
```toml
[dataframes.my_data]
dataframe_name = "My Dataset"
short_description_df = "Brief description"
path_to_parquet_data = "_data/my_data.parquet"
dataframe_docs_str = "Detailed documentation about this dataset, its columns, and usage."
```

### Charts

| Field | Required | Notes |
|-------|----------|-------|
| `path_to_html_chart` | Yes | Path to the HTML chart file |
| `chart_docs_path` OR `chart_docs_str` | Yes (one of) | Mutually exclusive documentation options |

### Notebooks

The notebook name is automatically inferred from the first `# Heading` in the notebook. Set `notebook_name` explicitly to override.

```toml
[notebooks.my_notebook]
notebook_description = "What this notebook does"
notebook_path = "_output/my_notebook.ipynb"
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
| `path_to_parquet_data` | Path to Parquet file or glob pattern (e.g., `_data/**/*.parquet` for hive-partitioned data) |
| `path_to_excel_data` | Path to Excel file |
| `dataframe_docs_path` | Path to documentation (mutually exclusive with `dataframe_docs_str`) |

## Site Directory (Custom Pages)

The `site_dir` field in `[pipeline]` adds custom markdown pages alongside auto-generated ChartBook documentation.

### Configuration

```toml
[pipeline]
id = "MYPROJ"
pipeline_name = "My Pipeline"
site_dir = "./docs_src/site/"
```

### Directory Layout

```
docs_src/site/
├── index_toc.md           # Controls how pages appear in the index toctree
├── methodology.md         # Custom page
├── data-sources.md        # Custom page
├── guides_toc.md          # Sub-toctree for nested pages
└── guides/
    ├── getting-started.md
    └── faq.md
```

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

Use glob patterns in `path_to_parquet_data` for hive-style partitioned datasets:

```toml
[dataframes.partitioned_data]
dataframe_name = "Partitioned Dataset"
short_description_df = "Data partitioned by year and month"
path_to_parquet_data = "./_data/partitioned/**/*.parquet"
date_col = "date"
dataframe_docs_str = "Hive-partitioned dataset with year/month partitions."
```

Polars `scan_parquet` handles glob patterns natively with automatic hive partitioning. Partition columns (e.g., `year`, `month`) are automatically added to the LazyFrame. Glob paths only support `format="polars"` (LazyFrame) — using `"pandas"` or `"polars_eager"` with a glob path raises a `ValueError`.
