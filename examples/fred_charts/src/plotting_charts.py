"""Generate charts using chartbook.plotting module.

This script creates several charts from FRED data using the chartbook.plotting
API. Each chart is saved with a chart_id that matches the chartbook.toml
configuration, enabling automatic discovery and documentation.
"""

from pathlib import Path

import pull_fred
from settings import config

import chartbook.plotting

DATA_DIR = Path(config("DATA_DIR"))
OUTPUT_DIR = Path(config("OUTPUT_DIR"))

# Configure chartbook.plotting
chartbook.plotting.configure(
    default_output_dir=str(OUTPUT_DIR),
    nber_recessions=True,
)


def create_cpi_chart():
    """Create a CPI inflation line chart."""
    df = pull_fred.load_fred(data_dir=DATA_DIR)

    # Calculate year-over-year percent change
    df = df[["CPIAUCSL"]].dropna().copy()
    df["date"] = df.index
    df["cpi_yoy"] = 100 * df["CPIAUCSL"].pct_change(12)  # 12-month percent change
    df = df.dropna()

    result = chartbook.plotting.line(
        df,
        x="date",
        y="cpi_yoy",
        title="Consumer Price Index Inflation",
        y_title="Percent Change (Year-over-Year)",
        source="Federal Reserve Bank of St. Louis (FRED)",
        note="CPI for All Urban Consumers, seasonally adjusted.",
        nber_recessions=True,
        hlines=[{"y": 2, "color": "red", "dash": "dash", "label": "2% Target"}],
    )
    result.save(chart_id="cpi_inflation_chart")
    print(f"Saved CPI chart to {result.html_path}")


def create_fedfunds_chart():
    """Create a Federal Funds Rate area chart."""
    df = pull_fred.load_fred(data_dir=DATA_DIR)

    df = df[["FEDFUNDS"]].dropna().copy()
    df["date"] = df.index

    result = chartbook.plotting.area(
        df,
        x="date",
        y="FEDFUNDS",
        title="Federal Funds Effective Rate",
        y_title="Percent",
        source="Federal Reserve Bank of St. Louis (FRED)",
        note="Federal Funds Effective Rate, monthly average.",
        nber_recessions=True,
    )
    result.save(chart_id="fedfunds_chart")
    print(f"Saved Fed Funds chart to {result.html_path}")


def create_gdp_unemployment_dual_chart():
    """Create a dual-axis chart showing GDP and Unemployment Rate."""
    df = pull_fred.load_fred(data_dir=DATA_DIR)

    # Prepare data - need to forward fill GDP to align with monthly unemployment
    df = df[["GDP", "UNRATE"]].copy()
    df["GDP"] = df["GDP"].ffill()  # Forward fill quarterly GDP
    df = df.dropna()
    df["date"] = df.index

    result = chartbook.plotting.dual(
        df,
        x="date",
        left_y="GDP",
        right_y="UNRATE",
        left_type="bar",
        right_type="line",
        title="GDP and Unemployment Rate",
        left_y_title="GDP (Billions of Dollars)",
        right_y_title="Unemployment Rate (%)",
        source="Federal Reserve Bank of St. Louis (FRED)",
        note="GDP is quarterly, Unemployment Rate is monthly.",
        nber_recessions=True,
    )
    result.save(chart_id="gdp_unemployment_dual_chart")
    print(f"Saved dual-axis chart to {result.html_path}")


def create_inflation_gdp_scatter():
    """Create a scatter plot of inflation vs GDP growth."""
    df = pull_fred.load_fred(data_dir=DATA_DIR)

    # Calculate annual changes
    df = df[["GDP", "CPIAUCSL"]].dropna().copy()
    df["gdp_growth"] = 100 * df["GDP"].pct_change(4)  # Quarterly data -> annual
    df["cpi_inflation"] = 100 * df["CPIAUCSL"].pct_change(12)  # Monthly -> annual
    df = df.dropna()
    df["date"] = df.index

    result = chartbook.plotting.scatter(
        df,
        x="gdp_growth",
        y="cpi_inflation",
        title="GDP Growth vs. Inflation",
        x_title="GDP Growth (%)",
        y_title="CPI Inflation (%)",
        source="Federal Reserve Bank of St. Louis (FRED)",
        note="Annual percent changes. GDP is quarterly, CPI is monthly.",
        regression_line=True,
    )
    result.save(chart_id="inflation_gdp_scatter")
    print(f"Saved scatter chart to {result.html_path}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    create_cpi_chart()
    create_fedfunds_chart()
    create_gdp_unemployment_dual_chart()
    create_inflation_gdp_scatter()

    print("\nAll charts generated successfully!")
