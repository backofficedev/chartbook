# Plotting

ChartBook includes a built-in plotting module that provides simple, consistent chart creation with automatic multi-format export. This module is designed to standardize chart styling across your organization while producing both interactive web charts and publication-ready static images.

## Overview

The plotting module follows a two-step workflow:

1. **Create** a chart — returns a `ChartResult` with the Plotly figure
2. **Display or Save** — call `.show()` to display inline, or `.save(chart_id)` to export files

When saving, the module generates **5 output files** for each chart:

| File | Format | Purpose |
|------|--------|---------|
| `{chart_id}.html` | Interactive HTML | Web display (Plotly) |
| `{chart_id}.png` | PNG (8×6") | Static single format |
| `{chart_id}_wide.png` | PNG (12×6") | Static wide format |
| `{chart_id}.pdf` | PDF (8×6") | Publication (LaTeX) |
| `{chart_id}_wide.pdf` | PDF (12×6") | Publication wide |

## Quick Start

```python
import chartbook
import pandas as pd

# Create sample data
df = pd.DataFrame({
    'date': pd.date_range('2020-01-01', periods=12, freq='ME'),
    'gdp': [100, 102, 101, 105, 108, 110, 112, 115, 114, 118, 120, 122],
    'cpi': [2.1, 2.2, 2.3, 2.2, 2.4, 2.5, 2.6, 2.5, 2.7, 2.8, 2.9, 3.0],
})

# Create a line chart and display inline
chartbook.plotting.line(df, x="date", y="gdp", title="GDP Growth").show()

# Create and save to files
result = chartbook.plotting.line(
    df,
    x="date",
    y=["gdp", "cpi"],
    title="Economic Indicators",
)
result.save(chart_id="gdp_growth")

print(result.paths)
# {'html': './_output/gdp_growth.html',
#  'png': './_output/gdp_growth.png', ...}
```

## ChartResult Object

All chart functions return a `ChartResult` object that provides access to the underlying figures and saving functionality:

```python
result = chartbook.plotting.line(df, x="date", y="value")

# Display inline (Jupyter, interactive environments)
result.show()

# Access the Plotly figure for customization
fig = result.figure
fig.update_layout(title_font_size=24)
result.show()

# Access matplotlib objects for fine-grained control
ax = result.mpl_axes
ax.axhline(y=100, color='red', linestyle='--', label='Target')
ax.legend()

fig = result.mpl_figure
fig.suptitle("Custom Title", fontsize=16)

# Save to files
result.save(chart_id="my_chart")

# Access saved paths
result.html_path      # Path to HTML file
result.png_path       # Path to PNG file
result.png_wide_path  # Path to wide PNG
result.pdf_path       # Path to PDF file
result.pdf_wide_path  # Path to wide PDF

# Get all paths as dict
result.paths  # {'html': Path(...), 'png': Path(...), ...}

# Chart metadata
result.chart_id     # "my_chart"
result.chart_type   # "line"
result.output_dir   # Path("./_output")
```

### Method Chaining

The `.save()` method returns the result for convenient chaining:

```python
# One-liner: create, save, and get paths
paths = chartbook.plotting.line(df, x="date", y="value").save("gdp").paths
```

## Chart Types

### Line Chart

```python
chartbook.plotting.line(
    df,
    x="date",
    y=["series1", "series2"],  # Multiple series supported
    title="My Line Chart",
    y_title="Value",
    nber_recessions=True,  # Add recession shading
).save("my_line")
```

### Bar Chart

```python
chartbook.plotting.bar(
    df,
    x="category",
    y=["value1", "value2"],
    stacked=True,  # Stack bars instead of grouping
    title="Sales by Category",
).save("my_bar")
```

### Scatter Plot

```python
chartbook.plotting.scatter(
    df,
    x="x_var",
    y="y_var",
    size="magnitude",       # Size points by column
    color_by="category",    # Color by category
    regression_line=True,   # Add trend line
).save("my_scatter")
```

### Pie Chart

```python
chartbook.plotting.pie(
    df,
    names="category",
    values="amount",
    title="Distribution",
).save("my_pie")
```

### Area Chart

```python
chartbook.plotting.area(
    df,
    x="date",
    y=["a", "b", "c"],
    stacked=True,
    title="Stacked Area",
).save("my_area")
```

### Dual-Axis Chart

Combine two chart types with independent y-axes:

```python
chartbook.plotting.dual(
    df,
    x="date",
    left_y="gdp",
    right_y="interest_rate",
    left_type="bar",        # "line", "bar", "scatter", "area"
    right_type="line",
    left_y_title="GDP (Billions)",
    right_y_title="Interest Rate (%)",
).save("gdp_vs_rate")
```

## Overlays

### NBER Recession Shading

Add NBER recession bars to time series charts:

```python
chartbook.plotting.line(
    df,
    x="date",
    y="value",
    nber_recessions=True,
).show()
```

```{note}
NBER recession data requires a FRED API key. Set the `FRED_API_KEY` environment variable.
Get a free key at [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
```

### Horizontal Lines

```python
chartbook.plotting.line(
    df,
    x="date",
    y="value",
    hlines=[
        {"y": 100, "color": "red", "dash": "dash", "label": "Target"},
        {"y": 0, "color": "gray", "dash": "solid"},
    ],
).show()
```

### Shaded Regions

Highlight specific time periods:

```python
chartbook.plotting.line(
    df,
    x="date",
    y="value",
    shaded_regions=[
        {
            "x0": "2020-03-01",
            "x1": "2020-06-01",
            "color": "red",
            "alpha": 0.2,
            "label": "COVID Period",
        },
    ],
).save("with_regions")
```

### Bands (Fill Between)

Fill between two y-columns (e.g., confidence intervals, target ranges):

```python
chartbook.plotting.line(
    df,
    x="date",
    y="value",
    bands=[
        {
            "y_upper": "upper_bound",
            "y_lower": "lower_bound",
            "color": "blue",
            "alpha": 0.2,
        },
    ],
).save("with_band")
```

## Configuration

### Global Settings

Configure defaults that apply to all charts:

```python
chartbook.plotting.configure(
    default_output_dir="./_charts",
    nber_recessions=False,
    figure_size_single=(8, 6),
    figure_size_wide=(12, 6),
    matplotlib_style="chartbook",
    plotly_template="plotly_white",
)
```

### Matplotlib Style

Set the matplotlib stylesheet:

```python
# Use built-in chartbook style
chartbook.plotting.set_style("chartbook")

# Use a built-in matplotlib style
chartbook.plotting.set_style("seaborn-v0_8-whitegrid")

# Use a custom .mplstyle file
chartbook.plotting.set_style("./my_custom_style.mplstyle")
```

## Annotations

Add title, caption, note, and source to any chart:

```python
chartbook.plotting.line(
    df,
    x="date",
    y="value",
    title="GDP Growth Over Time",
    caption="Quarterly data, seasonally adjusted",
    note="Preliminary data for Q4 2024",
    source="Bureau of Economic Analysis",
).save("annotated")
```

## Axis Formatting

```python
chartbook.plotting.line(
    df,
    x="date",
    y="rate",
    x_title="Date",
    y_title="Rate (%)",
    y_tickformat=".1%",     # Format as percentage
    y_range=(0, 10),        # Set axis range
).save("formatted")
```

## Advanced Usage: Accessing Raw Figures

For fine-grained control, access the underlying plotting library objects:

### Plotly Figure

```python
result = chartbook.plotting.line(df, x="date", y="value")

# Get the Plotly figure
fig = result.figure

# Customize with Plotly API
fig.update_layout(
    title_font_size=24,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
fig.update_traces(line=dict(width=3))

# Display the customized chart
result.show()
```

### Matplotlib Figure and Axes

```python
result = chartbook.plotting.line(df, x="date", y="value")

# Access matplotlib objects (lazily created)
ax = result.mpl_axes
fig = result.mpl_figure

# Customize with matplotlib API
ax.axhline(y=100, color='red', linestyle='--', linewidth=2, label='Target')
ax.fill_between(df['date'], 90, 110, alpha=0.1, color='green')
ax.legend(loc='upper left')
fig.suptitle("My Custom Chart", fontsize=16, fontweight='bold')

# Save the chart (matplotlib customizations apply to static formats)
result.save("custom_chart")
```

## Integration with chartbook.toml

When you create a chart with `chartbook.plotting`, you can reference it in your `chartbook.toml`:

```toml
[charts.gdp_growth]
chart_name = "GDP Growth"
short_description_chart = "Quarterly GDP growth rate"
dataframe_id = "fred"
path_to_html_chart = "./_output/gdp_growth.html"

# Optional: indicate this was generated by chartbook.plotting
generated_by_chartbook_plotting = true
```

If `path_to_html_chart` is a directory (or omitted), chartbook will look for `{chart_id}.html` in the default output directory.

## Plugin System

The plotting module uses [pluggy](https://pluggy.readthedocs.io/) for extensibility. Third-party packages can provide custom backends:

```toml
# In third-party package's pyproject.toml
[project.entry-points.chartbook_plotting]
altair = "mypackage.backend:AltairBackend"
```

See the API reference for details on implementing custom backends.

## Dependencies

The plotting module requires additional dependencies:

```console
pip install chartbook[plotting]
```

This installs:
- `matplotlib` — Static chart generation
- `plotly` — Interactive chart generation
- `kaleido` — Plotly static export
- `pluggy` — Plugin system
- `fredapi` — NBER recession data from FRED

## Best Practices

1. **Use `.show()` for exploration** — Quick inline display without saving files

2. **Use `.save()` for production** — Generates all formats with consistent `chart_id`

3. **Access `.figure` for Plotly customization** — Full Plotly API available

4. **Access `.mpl_axes` for fine control** — Matplotlib API for complex annotations

5. **Set global config early** — Call `configure()` at the start of your pipeline

6. **Use NBER recessions for time series** — Provides economic context

7. **Add source attribution** — Include data sources for reproducibility

8. **Keep titles concise** — Detailed info goes in caption/note/source
