# Chart Gallery

This gallery demonstrates all chart types available in `chartbook.plotting` using real economic data from FRED (Federal Reserve Economic Data).

Each example shows:
- How to create the chart
- Common customization options
- Best practices for different use cases

```{note}
This gallery is generated from a Jupyter notebook. To regenerate, run:
`doit notebooks`
```

## Setup

First, import the required libraries and fetch some FRED data.

```python
import chartbook
import pandas as pd
import numpy as np
from datetime import datetime

# For fetching FRED data
import pandas_datareader.data as web

# Configuration
START_DATE = "2000-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# Fetch economic data
economic_data = web.DataReader(
    ["GDP", "UNRATE", "CPIAUCSL", "FEDFUNDS", "GS10"],
    "fred",
    START_DATE,
    END_DATE
).reset_index()
```

## Line Charts

Line charts are ideal for time series data. They show trends and patterns over time.

### Basic Line Chart

```python
chartbook.plotting.line(
    economic_data,
    x="DATE",
    y="GDP",
    title="U.S. Gross Domestic Product",
    y_title="Billions of Dollars",
    source="FRED",
).show()
```

### Multi-Series Line Chart

```python
chartbook.plotting.line(
    economic_data,
    x="DATE",
    y=["FEDFUNDS", "GS10"],
    title="Interest Rates Comparison",
    y_title="Percent",
    labels={"FEDFUNDS": "Fed Funds Rate", "GS10": "10-Year Treasury"},
    source="Federal Reserve Economic Data",
).show()
```

### Line Chart with NBER Recession Shading

```python
chartbook.plotting.line(
    economic_data,
    x="DATE",
    y="GDP",
    title="GDP with Recession Shading",
    y_title="Billions of Dollars",
    nber_recessions=True,
    source="FRED",
    note="Shaded areas indicate NBER recession periods",
).show()
```

## Bar Charts

Bar charts are useful for comparing values across categories or discrete time periods.

### Basic Bar Chart

```python
# Create annual averages
annual_gdp = economic_data.groupby(economic_data["DATE"].dt.year)["GDP"].mean().reset_index()
annual_gdp.columns = ["year", "GDP"]
annual_gdp = annual_gdp.tail(10)

chartbook.plotting.bar(
    annual_gdp,
    x="year",
    y="GDP",
    title="Annual Average GDP (Last 10 Years)",
    y_title="Billions of Dollars",
    source="FRED",
).show()
```

### Stacked Bar Chart

```python
chartbook.plotting.bar(
    df,
    x="year",
    y=["consumption", "investment", "government"],
    stacked=True,
    title="GDP Components",
    y_title="Billions of Dollars",
).show()
```

## Scatter Plots

Scatter plots show relationships between two continuous variables.

### Basic Scatter Plot

```python
chartbook.plotting.scatter(
    df,
    x="UNRATE",
    y="inflation",
    title="Phillips Curve: Unemployment vs Inflation",
    x_title="Unemployment Rate (%)",
    y_title="Inflation Rate (%)",
    source="FRED",
).show()
```

### Scatter Plot with Regression Line

```python
chartbook.plotting.scatter(
    df,
    x="UNRATE",
    y="inflation",
    title="Phillips Curve with Trend Line",
    x_title="Unemployment Rate (%)",
    y_title="Inflation Rate (%)",
    regression_line=True,
).show()
```

## Area Charts

Area charts emphasize the magnitude of values over time.

### Stacked Area Chart

```python
chartbook.plotting.area(
    df,
    x="year",
    y=["consumption", "investment", "government"],
    stacked=True,
    title="GDP Components Over Time",
    y_title="Billions of Dollars",
).show()
```

## Pie Charts

Pie charts show proportional composition. Use sparingly and only for parts of a whole.

```python
gdp_shares = pd.DataFrame({
    "component": ["Consumption", "Investment", "Government", "Net Exports"],
    "share": [68, 18, 17, 3],
})

chartbook.plotting.pie(
    gdp_shares,
    names="component",
    values="share",
    title="GDP Composition by Component",
).show()
```

## Dual-Axis Charts

Dual-axis charts combine two different scales on the same plot.

### Bar + Line Dual Axis

```python
chartbook.plotting.dual(
    df,
    x="year",
    left_y="gdp_growth",
    right_y="UNRATE",
    left_type="bar",
    right_type="line",
    title="GDP Growth vs Unemployment",
    left_y_title="GDP Growth (%)",
    right_y_title="Unemployment Rate (%)",
).show()
```

## Advanced Features

### Confidence Bands

```python
chartbook.plotting.line(
    df,
    x="date",
    y="forecast",
    title="GDP with Confidence Interval",
    bands=[{
        "y_upper": "upper",
        "y_lower": "lower",
        "color": "blue",
        "alpha": 0.2,
    }],
).show()
```

### Custom Shaded Regions

```python
chartbook.plotting.line(
    df,
    x="date",
    y="UNRATE",
    title="Unemployment with COVID Period Highlighted",
    shaded_regions=[{
        "x0": "2020-02-01",
        "x1": "2021-06-01",
        "color": "red",
        "alpha": 0.15,
        "label": "COVID-19 Impact",
    }],
).show()
```

## Accessing Raw Figures

ChartBook returns a `ChartResult` that provides access to underlying figure objects.

### Plotly Figure Access

```python
result = chartbook.plotting.line(df, x="date", y="GDP")

# Access and customize Plotly figure
fig = result.figure
fig.update_layout(title_font=dict(size=24, color="darkblue"))
result.show()
```

### Matplotlib Access

```python
result = chartbook.plotting.line(df, x="date", y="UNRATE")

# Access matplotlib objects (lazily created)
ax = result.mpl_axes
ax.axhspan(0, 4, alpha=0.1, color="green", label="Low unemployment")
ax.legend()

# Save with customizations
result.save("custom_chart")
```

## Best Practices

1. **Use `.show()` for exploration** - Quick inline display
2. **Use `.save()` for production** - Generates all formats
3. **Add context** - Use `source`, `note`, and `caption`
4. **Choose the right chart type** based on your data and message
5. **Use overlays wisely** for additional context
