# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.18.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # 01. Example Notebook with Interactive Elements
#
# This example comes from here: https://jupyterbook.org/en/stable/interactive/interactive.html

# %%
import plotly.express as px

df = px.data.iris()
fig = px.scatter(
    df, x="sepal_width", y="sepal_length", color="species", size="sepal_length"
)
fig

# %%
