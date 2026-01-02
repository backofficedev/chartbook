# Charts

Charts are the primary output of chartbook pipelines. Each chart combines data visualization with comprehensive metadata for governance and discovery.

## Chart Concepts

A chart in chartbook consists of:
- **Visualization**: Interactive HTML file (Plotly-based)
- **Metadata**: Descriptive information in `chartbook.toml`
- **Documentation**: Markdown file with insights and methodology
- **Excel Export**: Optional Excel file with underlying data

## Defining Charts

### Basic Configuration

Add charts to your `chartbook.toml`:

```toml
[charts.monthly_revenue]
chart_name = "Monthly Revenue Analysis"
short_description_chart = "Revenue trends with YoY comparison"
dataframe_id = "revenue_data"  # Links to dataframe
path_to_html_chart = "./_output/monthly_revenue.html"
chart_docs_path = "./docs_src/charts/monthly_revenue.md"
```

### Complete Configuration

All available fields:

```toml
[charts.revenue_forecast]
# Basic Information
chart_name = "Revenue Forecast Model"
short_description_chart = "12-month revenue forecast with confidence intervals"

# Clearance and Governance
date_cleared_by_iv_and_v = "2025-01-15"
last_legal_clearance_date = "2025-01-10"
last_cleared_by = "Legal Team"

# Publication History
past_publications = [
    "[Q4 Report 2024, Figure 3](https://example.com/q4-2024)",
    "[Board Presentation, Slide 15](https://example.com/board-2024)",
]

# Data Characteristics
dataframe_id = "revenue_forecast_data"
topic_tags = ["Revenue", "Forecast", "Financial Planning"]
data_series_start_date = "1/1/2020"
data_frequency = "Monthly"
observation_period = "Month-end"
lag_in_data_release = "5 business days"
data_release_timing = "First week of month"
seasonal_adjustment = "X-13ARIMA-SEATS"
units = "USD (Millions)"
data_series = ["Historical Revenue", "Forecast", "Upper Bound", "Lower Bound"]
mnemonic = "REV_FCST"

# File Paths
path_to_html_chart = "./_output/revenue_forecast.html"
path_to_excel_chart = "./excel/revenue_forecast.xlsx"
chart_docs_path = "./docs_src/charts/revenue_forecast.md"
```

## Creating Charts

### Step 1: Generate the Visualization

```python
import chartbook
import pandas as pd
from pathlib import Path

# Load data
df = pd.read_parquet("_data/revenue_forecast_data.parquet")

# Create chart
chartbook.plotting.multiline(
    df=df,
    x_col="date",
    y_cols=["actual", "forecast", "upper_bound", "lower_bound"],
    title="Revenue Forecast Model",
    subtitle="12-month forecast with 95% confidence interval",
    y_axis_label="Revenue (USD Millions)",
    output_file_path=Path("_output/revenue_forecast.html")
)
```

### Step 2: Write Documentation

Create `docs_src/charts/revenue_forecast.md`:

```markdown
# Revenue Forecast Model

## Overview
This chart presents a 12-month revenue forecast using an ARIMA model with seasonal adjustments.

## Key Insights
- Revenue expected to grow 15% YoY
- Strong seasonal pattern in Q4
- Confidence interval widens after month 6

## Methodology
- Model: ARIMA(2,1,2)(1,1,1)[12]
- Training period: 2020-2024
- Validation: Time series cross-validation
- Seasonal adjustment: X-13ARIMA-SEATS

## Data Sources
- Historical revenue from financial system
- Economic indicators from Federal Reserve

## Updates
- Updated monthly with latest actuals
- Model retrained quarterly
- Annual methodology review

## Contact
Analytics Team - analytics@company.com
```

### Step 3: Excel Export (Optional)

```python
# Create Excel file with chart and data
from chartbook.excel import create_excel_chart

create_excel_chart(
    df=df,
    chart_type="line",
    x_col="date",
    y_cols=["actual", "forecast"],
    output_path="excel/revenue_forecast.xlsx",
    chart_title="Revenue Forecast"
)
```

## Chart Metadata

### Governance Fields

Track approvals and clearances:

```toml
date_cleared_by_iv_and_v = "2025-01-15"  # Internal validation
last_legal_clearance_date = "2025-01-10"  # Legal review
last_cleared_by = "John Doe, Legal Team"  # Approver
```

### Publication Tracking

Document where charts have been used:

```toml
past_publications = [
    "[Annual Report 2024, p.45](https://link-to-report)",
    "[Board Meeting Q4 2024](https://internal-link)",
    "Investor Presentation, March 2024",  # No link available
]
```

### Data Characteristics

Describe the underlying data:

```toml
data_frequency = "Daily"        # Daily, Weekly, Monthly, Quarterly, Annual
observation_period = "Close"    # When measurement taken
lag_in_data_release = "T+1"     # How long until available
seasonal_adjustment = "None"    # None, X-13ARIMA-SEATS, etc.
units = "Percent"              # Units of measurement
```

## Best Practices

### 1. Consistent Naming

Use descriptive, consistent names:
- Chart ID: `metric_timeperiod_type` (e.g., `revenue_monthly_trend`)
- File names: Match the chart ID
- Titles: Clear and professional

### 2. Version Control

Track chart changes:
```bash
# Good commit messages
git add _output/revenue_forecast.html
git commit -m "Update revenue forecast with Q4 actuals"
```

### 3. Documentation Standards

Every chart should document:
- **Purpose**: Why this chart exists
- **Methodology**: How it's calculated
- **Interpretation**: What it means
- **Limitations**: Known issues or caveats
- **Updates**: Frequency and process

### 4. Quality Checks

Before publishing:
1. Verify data accuracy
2. Check axis labels and units
3. Ensure title is descriptive
4. Test interactivity
5. Review documentation

### 5. Accessibility

Make charts accessible:
```python
# Include descriptive titles
title = "Monthly Revenue Trend from Jan 2020 to Dec 2024"

# Add alt text in documentation
"""
![Revenue trend chart showing steady growth with seasonal peaks]
(_output/revenue_trend.html)
"""

# Use colorblind-friendly palettes
colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]  # Blue, Orange, Green
```

## Chart Templates

### Time Series Template

```python
def create_time_series_chart(df, metric_name, output_path):
    """Standard time series chart template."""
    chartbook.plotting.multiline(
        df=df,
        x_col="date",
        y_cols=[metric_name],
        title=f"{metric_name} Over Time",
        subtitle=f"Monthly data from {df['date'].min()} to {df['date'].max()}",
        y_axis_label=get_units(metric_name),
        output_file_path=output_path
    )
```

### Comparison Template

```python
def create_comparison_chart(df, metrics, output_path):
    """Standard comparison chart template."""
    chartbook.plotting.bar(
        df=df,
        x_col="category",
        y_cols=metrics,
        title="Metric Comparison by Category",
        orientation="h",
        output_file_path=output_path
    )
```

## Troubleshooting

### Common Issues

1. **Chart not found**: Check file paths in `chartbook.toml`
2. **Broken links**: Ensure documentation paths are correct
3. **Missing data**: Verify dataframe_id matches
4. **Display issues**: Check browser compatibility

### Validation

Validate your charts:

```python
# Check all charts exist
from chartbook.spec_reader import read_specs
from pathlib import Path

specs = read_specs()
for chart_id, chart_config in specs["charts"].items():
    chart_path = Path(chart_config["path_to_html_chart"])
    if not chart_path.exists():
        print(f"Missing chart: {chart_id}")
```

## Next Steps

- Learn about {doc}`dataframes` that power your charts