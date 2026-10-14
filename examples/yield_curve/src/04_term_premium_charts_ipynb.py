# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Term Premium Analysis
#
# This notebook analyzes term premium measures derived from the U.S. Treasury
# zero-coupon yield curve. The term premium represents the extra compensation
# investors require for holding longer-term bonds instead of rolling over
# short-term bonds.
#
# We calculate simple term premium proxies as the spread between the 10-year
# yield and shorter maturities (1-year, 2-year, and 3-year).

# %%
from chartbook import assets, data
from chartbook.env import get_project_root

BASE_DIR = get_project_root()
DATA_DIR = BASE_DIR / "_data"

import load_fed_yield_curve
import pandas as pd
import plotly.graph_objects as go

# %% [markdown]
# ## Load Data

# %%
df = load_fed_yield_curve.load_fed_yield_curve(data_dir=DATA_DIR)
print(f"Data range: {df.index.min()} to {df.index.max()}")
print(f"Shape: {df.shape}")

# %% [markdown]
# ## Calculate Term Premium Measures
#
# We calculate three measures of the term premium:
# - **10Y - 1Y Spread**: 10-year yield minus 1-year yield
# - **10Y - 2Y Spread**: 10-year yield minus 2-year yield
# - **10Y - 3Y Spread**: 10-year yield minus 3-year yield

# %%
# Calculate term premium measures
df_premium = pd.DataFrame(index=df.index)
df_premium["spread_10y_1y"] = df["SVENY10"] - df["SVENY01"]
df_premium["spread_10y_2y"] = df["SVENY10"] - df["SVENY02"]
df_premium["spread_10y_3y"] = df["SVENY10"] - df["SVENY03"]

# Display summary statistics
df_premium.describe()

# %% [markdown]
# ## Chart 1: 10-Year minus 1-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["spread_10y_1y"],
        mode="lines",
        name="10Y - 1Y Spread",
        line=dict(width=1),
    )
)

# Add zero line
fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

fig.update_layout(
    title="Term Premium: 10-Year minus 1-Year Treasury Yield",
    xaxis_title="Date",
    yaxis_title="Spread (Percentage Points)",
    hovermode="x unified",
)

fig.show()
fig.write_html(assets.path("chart/term_premium_10y_1y"), include_plotlyjs="cdn", div_id="chart")

# %% [markdown]
# ## Chart 2: 10-Year minus 2-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["spread_10y_2y"],
        mode="lines",
        name="10Y - 2Y Spread",
        line=dict(width=1, color="orange"),
    )
)

# Add zero line
fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

fig.update_layout(
    title="Term Premium: 10-Year minus 2-Year Treasury Yield",
    xaxis_title="Date",
    yaxis_title="Spread (Percentage Points)",
    hovermode="x unified",
)

fig.show()
fig.write_html(assets.path("chart/term_premium_10y_2y"), include_plotlyjs="cdn", div_id="chart")

# %% [markdown]
# ## Chart 3: 10-Year minus 3-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["spread_10y_3y"],
        mode="lines",
        name="10Y - 3Y Spread",
        line=dict(width=1, color="green"),
    )
)

# Add zero line
fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

fig.update_layout(
    title="Term Premium: 10-Year minus 3-Year Treasury Yield",
    xaxis_title="Date",
    yaxis_title="Spread (Percentage Points)",
    hovermode="x unified",
)

fig.show()
fig.write_html(assets.path("chart/term_premium_10y_3y"), include_plotlyjs="cdn", div_id="chart")

# %% [markdown]
# ## Save Data

# %%
# Column names stay code-friendly (spread_10y_1y): letters, digits and
# underscores, so they work unquoted in SQL and as attribute names. The
# readable names ("10Y-1Y Spread") are metadata, and live in chartbook.toml
# under [dataframes.term_premium.series.*].
df_premium_formatted = df_premium.copy()
df_premium_formatted.index.name = "date"

# Save to parquet and excel
filepath = data.path("term_premium")
df_premium_formatted.to_parquet(filepath)

filepath = DATA_DIR / "term_premium.xlsx"
df_premium_formatted.to_excel(filepath)

print(f"Data saved to {data.path('term_premium')}")
