"""The term spread, from two other pipelines' data as chartbook.lock pins it."""

import pandas as pd

from chartbook import data

# "pipeline:dataframe" is another pipeline's dataframe, the copy chartbook.lock pins
curve = data.load("treasury_curve:zero_coupon_yields", format="pandas")
macro = data.load("macro_basics:macro_series", format="pandas")

month_end = curve.set_index("date")[["SVENY02", "SVENY10"]].resample("MS").last()
spread = pd.DataFrame(
    {
        "two_year": month_end["SVENY02"],
        "ten_year": month_end["SVENY10"],
        "spread": month_end["SVENY10"] - month_end["SVENY02"],
        "unemployment": macro.set_index("date")["unemployment"],
    }
).dropna()
spread.index.name = "date"
spread.reset_index().to_parquet(data.path("term_spread"), index=False)
