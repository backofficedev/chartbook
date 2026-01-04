# Configuration Guide

chartbook uses a TOML configuration file (`chartbook.toml`) to define your project structure, charts, dataframes, and pipelines.

## Configuration File Structure

The configuration file has several main sections:

```toml
[config]           # Project type and version
[site]             # Website metadata
[pipeline]         # Pipeline information (for pipeline projects)
[pipelines]        # Pipeline references (for catalog projects)
[charts]           # Chart definitions
[dataframes]       # Dataframe definitions
[notes]            # Additional documentation notes
[notebooks]        # Jupyter notebook references
```

## Project Types

chartbook supports two project types:

### Pipeline Project

A single analytics pipeline with its own charts and dataframes:

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.2"
```

### Catalog Project

A collection of multiple pipelines aggregated into a unified catalog:

```toml
[config]
type = "catalog"
chartbook_format_version = "0.0.2"
```

## Configuration Sections

### `[config]` - Project Configuration

Required fields for all projects:

```toml
[config]
type = "pipeline"  # or "catalog"
chartbook_format_version = "0.0.2"
```

### `[site]` - Website Metadata

Configure the generated website:

```toml
[site]
title = "My Analytics Project"
author = "Data Team"
copyright = "2025"
logo_path = "./assets/logo.png"    # Optional
favicon_path = "./assets/icon.png"  # Optional
```

### `[pipeline]` - Pipeline Information

For pipeline projects only:

```toml
[pipeline]
id = "MYPROJ"
pipeline_name = "My Analytics Pipeline"
pipeline_description = "Comprehensive analytics for business metrics"
lead_pipeline_developer = "Jane Doe"
contributors = ["Jane Doe", "John Smith", "Alice Johnson"]
software_modules_command = "module load python/3.11"  # Optional
runs_on_grid_or_windows_or_other = "Windows/Linux/MacOS"
git_repo_URL = "https://repository.yourcompany.org/scm/chart/repos/repo"
README_file_path = "./README.md"
```

### `[pipelines]` - Pipeline References

For catalog projects only:

```toml
[pipelines]

[pipelines.EX]
path_to_pipeline = "../pipelines/example"

[pipelines.ANALYTICS]
path_to_pipeline = "../pipelines/analytics"

# Platform-specific paths
[pipelines.DATA.MONTHLY]
Unix = "/data/pipelines/monthly"
Windows = "T:/pipelines/monthly"
```

### `[charts]` - Chart Definitions

Define individual charts:

```toml
[charts.revenue_trend]
chart_name = "Revenue Trend Analysis"
date_cleared_by_iv_and_v = "2025-01-15"
last_legal_clearance_date = "2025-01-15"
last_cleared_by = "Legal Team"
past_publications = [
    "[Q4 Report 2024, p15](https://example.com/reports/q4-2024)",
    "[Annual Report 2024, p45](https://example.com/reports/annual-2024)",
]
short_description_chart = "Monthly revenue trends with seasonal adjustments"
dataframe_id = "revenue_data"
topic_tags = ["Revenue", "Financial", "Monthly"]
data_series_start_date = "1/1/2020"
data_frequency = "Monthly"
observation_period = "Month-end"
lag_in_data_release = "15 days"
data_release_timing = "Mid-month"
seasonal_adjustment = "X-13ARIMA-SEATS"
units = "USD Millions"
data_series = ["Gross Revenue", "Net Revenue", "Revenue Growth Rate"]
mnemonic = "REV_TREND"
path_to_html_chart = "./_output/revenue_trend.html"
path_to_excel_chart = "./excel/revenue_trend.xlsx"
chart_docs_path = "./docs_src/charts/revenue_trend.md"
```

### `[dataframes]` - Dataframe Definitions

Define data sources:

```toml
[dataframes.revenue_data]
dataframe_name = "Revenue Dataset"
short_description_df = "Comprehensive revenue data with geographic breakdowns"
data_sources = ["Internal Sales System", "Finance Database"]
data_providers = ["Sales Team", "Finance Team"]
need_to_contact_provider = ["No", "No"]
data_on_pre_approved_list = ["Yes", "Yes"]
links_to_data_providers = [
    "https://internal.company.com/sales",
    "https://internal.company.com/finance"
]
topic_tags = ["Revenue", "Sales", "Financial"]
type_of_data_access = ["Internal", "Internal"]
data_license = "Internal Use Only"
license_expiration_date = "2025-12-31"
provider_contact_info = "data-team@company.com"
restriction_on_use = "Internal analytics only"
how_is_pulled = "SQL query via Python"
path_to_parquet_data = "./_data/revenue_data.parquet"
path_to_excel_data = "./_data/revenue_data.xlsx"
date_col = "date"
dataframe_docs_path = "./docs_src/dataframes/revenue_data.md"
```

### `[notes]` - Additional Documentation

Include extra documentation:

```toml
[notes]

[notes.methodology]
path_to_markdown_file = "./docs_src/methodology.md"

[notes.data_quality]
path_to_markdown_file = "./docs_src/data_quality_notes.md"
```

### `[notebooks]` - Jupyter Notebooks

Reference analytical notebooks:

```toml
[notebooks]

[notebooks.exploratory_analysis]
notebook_name = "Exploratory Data Analysis"
notebook_description = "Initial exploration of revenue patterns and anomalies"
notebook_path = "_output/01_exploratory_analysis.ipynb"

[notebooks.model_development]
notebook_name = "Forecasting Model Development"
notebook_description = "Time series models for revenue forecasting"
notebook_path = "_output/02_model_development.ipynb"
```

## Complete Example

Here's a complete example for a pipeline project:

```toml
[config]
type = "pipeline"
chartbook_format_version = "0.0.2"

[site]
title = "Sales Analytics Pipeline"
author = "Analytics Team"
copyright = "2025, My Company"
logo_path = "./assets/company_logo.png"
favicon_path = "./assets/favicon.ico"

[pipeline]
id = "SALES"
pipeline_name = "Sales Analytics Pipeline"
pipeline_description = "End-to-end sales analytics and reporting"
lead_pipeline_developer = "Jane Doe"
contributors = ["Jane Doe", "John Smith"]
runs_on_grid_or_windows_or_other = "Windows/Linux"
git_repo_URL = "https://github.com/yourorg/sales-analytics"
README_file_path = "./README.md"

[charts]

[charts.monthly_sales]
chart_name = "Monthly Sales Overview"
short_description_chart = "Total sales by month with YoY comparison"
dataframe_id = "sales_data"
topic_tags = ["Sales", "Monthly", "Revenue"]
data_frequency = "Monthly"
units = "USD"
path_to_html_chart = "./_output/monthly_sales.html"
chart_docs_path = "./docs_src/charts/monthly_sales.md"

[dataframes]

[dataframes.sales_data]
dataframe_name = "Sales Transactions"
short_description_df = "Detailed sales transaction data"
data_sources = ["CRM System"]
path_to_parquet_data = "./_data/sales_data.parquet"
date_col = "transaction_date"
```

## Best Practices

1. **Version Control**: Always specify the `chartbook_format_version`
2. **File Paths**: Use relative paths from the project root
3. **Metadata**: Provide comprehensive metadata for discoverability
4. **Tags**: Use consistent topic tags across charts and dataframes
5. **Documentation**: Link to markdown files for detailed documentation
6. **Data Governance**: Include licensing and access information

## Validation

chartbook validates your configuration file when running commands. Common validation errors:

- Missing required fields
- Invalid file paths
- Mismatched dataframe references
- Invalid date formats

Run `chartbook build` to validate your configuration. 