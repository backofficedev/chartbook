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
from settings import config

OUTPUT_DIR = config("OUTPUT_DIR")
DATA_DIR = config("DATA_DIR")

import pandas as pd
import plotly.graph_objects as go

import load_fed_yield_curve

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
df_premium["10Y_1Y_Spread"] = df["SVENY10"] - df["SVENY01"]
df_premium["10Y_2Y_Spread"] = df["SVENY10"] - df["SVENY02"]
df_premium["10Y_3Y_Spread"] = df["SVENY10"] - df["SVENY03"]

# Display summary statistics
df_premium.describe()

# %% [markdown]
# ## Chart 1: 10-Year minus 1-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["10Y_1Y_Spread"],
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
fig.write_html(OUTPUT_DIR / "term_premium_10y_1y.html", include_plotlyjs="cdn")

# %% [markdown]
# ## Chart 2: 10-Year minus 2-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["10Y_2Y_Spread"],
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
fig.write_html(OUTPUT_DIR / "term_premium_10y_2y.html", include_plotlyjs="cdn")

# %% [markdown]
# ## Chart 3: 10-Year minus 3-Year Spread

# %%
fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=df_premium.index,
        y=df_premium["10Y_3Y_Spread"],
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
fig.write_html(OUTPUT_DIR / "term_premium_10y_3y.html", include_plotlyjs="cdn")

# %% [markdown]
# ## Save Data

# %%
# Format column names for export
df_premium_formatted = df_premium.copy()
df_premium_formatted.columns = df_premium_formatted.columns.str.replace("_", " ")
df_premium_formatted.index.name = "date"

# Save to parquet and excel
filepath = DATA_DIR / "term_premium.parquet"
df_premium_formatted.to_parquet(filepath)

filepath = DATA_DIR / "term_premium.xlsx"
df_premium_formatted.to_excel(filepath)

print(f"Data saved to {DATA_DIR / 'term_premium.parquet'}")
