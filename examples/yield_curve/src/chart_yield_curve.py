"""
Chart the current yield curve (most recent observation).

This script creates an interactive Plotly chart showing the U.S. Treasury
zero-coupon yield curve based on the Gurkaynak, Sack, and Wright (2007) model.
"""

from chartbook import data
from chartbook.env import get_project_root

BASE_DIR = get_project_root()
DATA_DIR = BASE_DIR / "_data"

import load_fed_yield_curve
import pandas as pd
import plotly.graph_objects as go

##################################
## Load and prepare data
##################################

df = load_fed_yield_curve.load_fed_yield_curve(data_dir=DATA_DIR)

# Get the most recent observation
latest_date = df.index.max()
latest_curve = df.loc[latest_date]

# Create maturity values (1-30 years)
maturities = list(range(1, 31))
yields = latest_curve.values

# Create a dataframe for export
df_current = pd.DataFrame({"maturity_years": maturities, "yield_percent": yields})
df_current["date"] = latest_date

##################################
## Chart: Current Yield Curve
##################################

fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=maturities,
        y=yields,
        mode="lines+markers",
        name="Zero-Coupon Yield",
        line=dict(width=2),
        marker=dict(size=6),
    )
)

fig.update_layout(
    title=f"U.S. Treasury Zero-Coupon Yield Curve ({latest_date.strftime('%Y-%m-%d')})",
    xaxis_title="Maturity (Years)",
    yaxis_title="Yield (Percent)",
    hovermode="x unified",
)

fig.update_xaxes(
    tickmode="linear",
    tick0=1,
    dtick=5,
)

# The chart's location comes from [charts.yield_curve_current] in chartbook.toml
fig.write_html(data.path("yield_curve_current"), include_plotlyjs="cdn")

##################################
## Save data
##################################

filepath = DATA_DIR / "fed_yield_curve_current.parquet"
df_current.to_parquet(filepath, index=False)

filepath = DATA_DIR / "fed_yield_curve_current.xlsx"
df_current.to_excel(filepath, index=False)

print(f"Chart saved to: {data.path('yield_curve_current')}")
print(f"Data saved to: {DATA_DIR / 'fed_yield_curve_current.parquet'}")
