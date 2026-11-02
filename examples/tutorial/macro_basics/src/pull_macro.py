"""Pull four FRED series into the dataframe chartbook.toml declares."""

import pandas as pd
import pandas_datareader.data as web

from chartbook import data

raw = web.DataReader(["UNRATE", "CPIAUCSL", "PAYEMS", "GDPC1"], "fred", start="1960-01-01")
monthly = raw[["UNRATE", "CPIAUCSL", "PAYEMS"]].resample("MS").mean()
quarterly = raw["GDPC1"].dropna()
macro = pd.DataFrame(
    {
        "unemployment": monthly["UNRATE"],
        "inflation": monthly["CPIAUCSL"].pct_change(12) * 100,
        "payrolls": monthly["PAYEMS"].diff(),
        "gdp_growth": (quarterly.pct_change(4) * 100).reindex(monthly.index),
    }
).dropna(subset=["unemployment"])
macro.index.name = "date"
macro.reset_index().to_parquet(data.path("macro_series"), index=False)
