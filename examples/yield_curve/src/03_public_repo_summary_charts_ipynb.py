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
# # 03. Public Repo Summary Charts
# This contains a few summary stats and basic charts to get a better understanding of repo.
#
#
# ## Load and Format Data

# %%
from pathlib import Path

import pandas as pd
import pull_public_repo_data
from matplotlib import pyplot as plt
from settings import config

OUTPUT_DIR = Path(config("OUTPUT_DIR"))
DATA_DIR = Path(config("DATA_DIR"))

# %%
pull_public_repo_data.series_descriptions

# %%
df = pull_public_repo_data.load_all(data_dir=DATA_DIR)
df = df.loc["2012-01-01":, :]

df["target_midpoint"] = (df["DFEDTARU"] + df["DFEDTARL"]) / 2
df["SOFR-IORB"] = df["SOFR"] - df["Gen_IORB"]

df["Fed Balance Sheet / GDP"] = df["WALCL"] / df["GDP"]
df["Tri-Party - Fed ON/RRP Rate"] = (df["REPO-TRI_AR_OO-P"] - df["RRPONTSYAWARD"]) * 100
df["Tri-Party Rate Less Fed Funds Upper Limit"] = (
    df["REPO-TRI_AR_OO-P"] - df["DFEDTARU"]
) * 100
df["Tri-Party Rate Less Fed Funds Midpoint"] = (
    df["REPO-TRI_AR_OO-P"] - (df["DFEDTARU"] + df["DFEDTARL"]) / 2
) * 100

df["net_fed_repo"] = (
    df["RPONTSYD"] - df["RRPONTSYD"]
) / 1000  # Fed Repo minus reverse repo volume
df["Total Reserves / Currency"] = (
    df["TOTRESNS"] / df["CURRCIR"]
)  # total reserves among depository institutions vs currency in circulation
df["Total Reserves / GDP"] = df["TOTRESNS"] / df["GDP"]

df["SOFR (extended with Tri-Party)"] = df["SOFR"].fillna(df["REPO-TRI_AR_OO-P"])

new_labels = {
    "REPO-TRI_AR_OO-P": "Tri-Party Overnight Average Rate",
    "RRPONTSYAWARD": "ON-RRP facility rate",
    "Gen_IORB": "Interest on Reserves",
}

# %% [markdown]
# ### Rates Relative to Fed Funds Target Midpoint
# Normalize rates to be centered at the fed funds target window midpoint.

# %%
df_norm = pd.DataFrame().reindex_like(df[["target_midpoint"]])
df_norm[["target_midpoint"]] = 0

for s in [
    "DFEDTARU",
    "DFEDTARL",
    "REPO-TRI_AR_OO-P",
    "EFFR",
    "target_midpoint",
    "Gen_IORB",
    "RRPONTSYAWARD",
    "SOFR",
    "SOFR (extended with Tri-Party)",
    "FNYR-BGCR-A",
    "FNYR-TGCR-A",
]:
    df_norm[s] = df[s] - df["target_midpoint"]

# %% [markdown]
# ## Replicate "Anatomy of a Repo Spike" Charts
#
# Replicate Figure 1 from "Anatomy of the Repo Rate Spikes

# %%
fig, ax = plt.subplots()
ax.fill_between(df.index, df["DFEDTARU"], df["DFEDTARL"], alpha=0.5)
df[["REPO-TRI_AR_OO-P", "EFFR"]].rename(columns=new_labels).plot(ax=ax)

# %%
fig, ax = plt.subplots()
date_start = "2014-Aug"
date_end = "2019-Dec"
_df = df.loc[date_start:date_end, :]
ax.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.5)
_df[["REPO-TRI_AR_OO-P", "EFFR"]].rename(columns=new_labels).plot(ax=ax)

# %%
fig, ax = plt.subplots()
date_start = "2014-Aug"
date_end = "2019-Dec"
_df = df_norm.loc[date_start:date_end, :]
ax.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.2)
_df[["REPO-TRI_AR_OO-P", "EFFR"]].rename(columns=new_labels).plot(ax=ax)
plt.ylim(-0.4, 1.0)
plt.ylabel("Spread of federal feds target midpoint (percent)")
arrowprops = dict(arrowstyle="->")
ax.annotate(
    "Sep. 17, 2019: 3.06%",
    xy=("2019-Sep-17", 0.95),
    xytext=("2017-Oct-27", 0.9),
    arrowprops=arrowprops,
)

# %%
fig, ax = plt.subplots()
date_start = "2014-Aug"
date_end = "2019-Dec"
_df = df_norm.loc[date_start:date_end, :].copy()

ax.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.2)
_df[["REPO-TRI_AR_OO-P", "EFFR", "Gen_IORB", "RRPONTSYAWARD"]].rename(
    columns=new_labels
).plot(ax=ax)
plt.ylim(-0.4, 1.0)
plt.ylabel("Spread of federal feds target midpoint (percent)")
arrowprops = dict(arrowstyle="->")
ax.annotate(
    "Sep. 17, 2019: 3.06%",
    xy=("2019-Sep-17", 0.95),
    xytext=("2017-Oct-27", 0.9),
    arrowprops=arrowprops,
)

# %%
fig, ax = plt.subplots()
date_start = "2018-Apr"
date_end = None
_df = df_norm.loc[date_start:date_end, :].copy()

ax.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.1)
_df = _df[
    [
        "SOFR",
        "Gen_IORB",
        "RRPONTSYAWARD",
    ]
].rename(columns=new_labels)
_df.plot(ax=ax)
plt.ylim(-0.4, 1.0)
plt.ylabel("Rate relative to Federal Funds target midpoint (percent)")
arrowprops = dict(arrowstyle="->")
ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))
ax.annotate(
    "Sep. 17, 2019: 3.06%",
    xy=("2019-Sep-17", 0.95),
    xytext=("2020-Oct-27", 0.9),
    arrowprops=arrowprops,
)
plt.savefig(OUTPUT_DIR / "rates_relative_to_midpoint.png")

# %%
fig, ax = plt.subplots()
date_start = "2023-Jul"
date_end = None
_df = df_norm.loc[date_start:date_end, :].copy()

ax.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.1)
_df[["SOFR", "EFFR", "Gen_IORB", "RRPONTSYAWARD"]].rename(columns=new_labels).plot(
    ax=ax
)
plt.ylim(-0.4, 1.0)
plt.ylabel("Spread of federal feds target midpoint (percent)")
arrowprops = dict(arrowstyle="->")
ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))

# %% [markdown]
# ## Understanding this plot
#
# Now, let's spend some time trying to understand this plot.
#
# ### Reserve Levels vs Spikes
# First of all, depository intitutions have a choice between keeping their reserves at the Fed and earning interest on reserve balances or lending the money into repo. When the repo rates were spiking in 2018 and 2019, I would imagine that total reserve levels would be low.

# %%
df["net_fed_repo"] = (df["RPONTSYD"] - df["RRPONTSYD"]) / 1000
df["triparty_less_fed_onrrp_rate"] = (
    df["REPO-TRI_AR_OO-P"] - df["RRPONTSYAWARD"]
) * 100
df["total reserves / currency"] = df["TOTRESNS"] / df["CURRCIR"]

# %%
fig, ax1 = plt.subplots()
ax2 = ax1.twinx()
df[["TOTRESNS"]].rename(columns=pull_public_repo_data.series_descriptions).plot(
    ax=ax1, color="g"
)
ax1.set_ylabel("$ Billions")
ax2.set_ylabel("Basis Points")
ax1.legend(loc="center left", bbox_to_anchor=(1, 1.1))
df[["Tri-Party - Fed ON/RRP Rate"]].plot(ax=ax2)
ax2.legend(loc="center left", bbox_to_anchor=(1, 1))

# %% [markdown]
# Now, let's normalize by currency in circulation, so as to account for the normal growth in the economy or the financial system. This is done because total reserves is not stationary.

# %%
fig, ax1 = plt.subplots()
ax2 = ax1.twinx()
_df = df[["Tri-Party - Fed ON/RRP Rate", "Total Reserves / Currency"]]
_df[["Total Reserves / Currency"]].plot(ax=ax1, color="g")
_df[["Tri-Party - Fed ON/RRP Rate"]].plot(ax=ax2)
ax1.set_ylabel("Ratio")
ax2.set_ylabel("Basis Points")
ax1.legend(loc="center left", bbox_to_anchor=(1, 1.1))
ax2.legend(loc="center left", bbox_to_anchor=(1, 1))
plt.savefig(OUTPUT_DIR / "repo_rate_spikes_and_relative_reserves_levels.png")

# %% [markdown]
# ### Fed Balance Sheet Size vs Spikes

# %%
fig, ax1 = plt.subplots()
ax2 = ax1.twinx()

date_start = "2016-Jan"
date_end = None

_df = df_norm.loc[date_start:date_end, :].copy()
_df = _df[
    [
        "SOFR (extended with Tri-Party)",
        "Gen_IORB",
        "RRPONTSYAWARD",
        "DFEDTARU",  # Fed Funds Upper Limit
        "DFEDTARL",  # Fed Funds Lower Limit
    ]
].rename(columns=new_labels)
cols = [
    "Fed Balance Sheet / GDP",
]
for col in cols:
    _df[col] = df[col]
_df.to_excel(DATA_DIR / "AR2024_SEC_4_2_Fed_Balance_Sheet_Repo.xlsx")

ax1.fill_between(_df.index, _df["DFEDTARU"], _df["DFEDTARL"], alpha=0.1)

_df = df_norm.loc[date_start:date_end, :].copy()
_df = _df[
    [
        "SOFR (extended with Tri-Party)",
        "Gen_IORB",
        "RRPONTSYAWARD",
    ]
].rename(columns=new_labels)
_df.plot(ax=ax1)
plt.ylim(-0.4, 1.0)
plt.ylabel("Rate relative to Federal Funds target midpoint (percent)")
arrowprops = dict(arrowstyle="->")
ax1.annotate(
    "Sep. 17, 2019: 3.06%",
    xy=("2019-Sep-17", 0.95),
    xytext=("2020-Oct-27", 0.9),
    arrowprops=arrowprops,
)
_df = df[
    [
        "Tri-Party Rate Less Fed Funds Upper Limit",
        "Fed Balance Sheet / GDP",
    ]
]

_df.loc[date_start:, ["Fed Balance Sheet / GDP"]].plot(
    ax=ax2, color="black", alpha=0.75
)

ax1.set_ylabel("Basis Points")
ax2.set_ylabel("Ratio")
ax1.set_ylim([-0.2, 0.4])
ax2.set_ylim([0.10, 0.4])
ax2.legend("")
plt.title("Black line is Fed Balance Sheet / GDP")

# %%
_df.loc["Sep. 17, 2019", ["Tri-Party Rate Less Fed Funds Upper Limit"]]

# %% [markdown]
# ### Fed Repo and Reverse Repo Facility Takeup

# %%
df[["RPONTSYD", "RRPONTSYD"]].rename(
    columns=pull_public_repo_data.series_descriptions
).plot(alpha=0.5)

# %%
df[["net_fed_repo"]].plot()
plt.ylabel("$ Trillions")

# %%
df.loc["2023", ["net_fed_repo"]].plot()
plt.ylabel("$ Trillions")

# %%
df[["net_fed_repo", "triparty_less_fed_onrrp_rate"]].plot()
plt.ylim([-50, 100])

# %% [markdown]
# The Fed is lending money when the repo rate is spiking. When the repo rate is low relative to the ON/RRP rate, usage of the ON/RRP facility goes up, as can be seen here.

# %%
fig, ax1 = plt.subplots()
ax2 = ax1.twinx()
df[["net_fed_repo"]].plot(ax=ax1, color="g")
df[["triparty_less_fed_onrrp_rate"]].plot(ax=ax2)

# %% [markdown]
# ## How should we define a repo spike?
#
# Now, I turn to the question of how to define a repo rate spike.
#
# ### Fed Fund's Target Range
#
# The first way to approach this is to just look at when the triparty rate exceeded the upper bound of the fed's federal funds rate target range.

# %% [markdown]
# **Tri-Party Ave vs Fed Upper Limit**

# %%
df["is_tri_above_fed_upper"] = df["REPO-TRI_AR_OO-P"] > df["DFEDTARU"]

# %%
df.index[df["is_tri_above_fed_upper"]]

# %%
len(df.index[df["is_tri_above_fed_upper"]])

# %% [markdown]
# **SOFR vs Fed Upper Limit**

# %%
df["is_SOFR_above_fed_upper"] = df["SOFR"] > df["DFEDTARU"]
len(df.index[df["is_SOFR_above_fed_upper"]])

# %%
df.index[df["is_SOFR_above_fed_upper"]]

# %% [markdown]
# **SOFR vs Interest of Reserves**
#
# This measure is good because it represents a kind of arbitrage opportunity. Either leave money at Fed to earn interest, or put money into repo market. This is what the paper, "Reserves were not so amply after all" uses.

# %%
df[["SOFR-IORB"]].dropna(how="all").plot()

# %%
df["is_SOFR_above_IORB"] = df["SOFR-IORB"] > 0
len(df.index[df["is_SOFR_above_IORB"]])

# %%
df.index[df["is_SOFR_above_IORB"]]

# %% [markdown]
# Now, let's ask if it's 2 standard deviations above IORB

# %%
df["SOFR-IORB"].std()

# %%
df["is_SOFR_2std_above_IORB"] = df["SOFR-IORB"] > 2 * df["SOFR-IORB"].std()
len(df.index[df["is_SOFR_2std_above_IORB"]])

# %%
df.index[df["is_SOFR_2std_above_IORB"]]

# %%
df["SOFR-IORB"].mean()

# %%
df.index[df["is_SOFR_2std_above_IORB"]].intersection(
    df.index[df["is_SOFR_above_fed_upper"]]
)

# %%
len(
    df.index[df["is_SOFR_2std_above_IORB"]].intersection(
        df.index[df["is_SOFR_above_fed_upper"]]
    )
)

# %%
filedir = Path(OUTPUT_DIR)
df[
    [
        "is_SOFR_above_fed_upper",
        "is_SOFR_2std_above_IORB",
        "is_SOFR_above_IORB",
        "is_tri_above_fed_upper",
    ]
].to_csv(filedir / "is_spike.csv")

# %% [markdown]
# ## Summary Stats about Various Repo Rates

# %%
df.info()

# %% [markdown]
# I don't include GCF in this first comparison, because it has a lot of missing values. I want to only compare values for which all rates are non-null. That's why I drop the whole row when any rate is missing.
#
# Here, we see that DVP average is lower than Triparty average. SOFR is closer to triparty, but is still lower. This is because SOFR tries to remove specials.
#
# Notice, however, that this is different when comparing the 75% percentiles. SOFR is higher than triparty and DVP is even higher.

# %%
df[["SOFR", "REPO-TRI_AR_OO-P", "REPO-DVP_AR_OO-P"]].dropna().describe()

# %% [markdown]
# Now, I include GCF. It appears that GCF is the highest. Borrow low at tri-party, lend higher into SOFR (but lower to specials) and lend highest to GCF.

# %%
df[
    ["SOFR", "REPO-TRI_AR_OO-P", "REPO-DVP_AR_OO-P", "REPO-GCF_AR_OO-P"]
].dropna().describe()

# %%
