"""Download the Board's zero-coupon yield curve into the dataframe chartbook.toml declares."""

from io import BytesIO

import pandas as pd
import requests

from chartbook import data

URL = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"

response = requests.get(URL, timeout=60)
response.raise_for_status()
curve = pd.read_csv(BytesIO(response.content), skiprows=9, index_col=0, parse_dates=True)
yields = curve[[f"SVENY{n:02d}" for n in range(1, 31)]].dropna(how="all")
yields.index.name = "date"
yields.reset_index().to_parquet(data.path("zero_coupon_yields"), index=False)
