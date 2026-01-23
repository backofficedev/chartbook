"""
This module contains functions to load the zero coupon yield curve from the Federal Reserve.
It saves the pulled raw data to a parquet file for future use.
Functions to load the raw/clean data from the parquet file are also provided for future use.

"""

from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from chartbook.env import get, get_project_root

DATA_DIR = get_project_root() / "_data"
START_DATE = get("START_DATE", default="1990-01-01")
END_DATE = get("END_DATE", default="2025-12-31")


def pull_fed_yield_curve():
    """
    Download the latest yield curve from the Federal Reserve

    This is the published data using Gurkaynak, Sack, and Wright (2007) model
    """

    url = "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv"
    response = requests.get(url)
    pdf_stream = BytesIO(response.content)
    df = pd.read_csv(pdf_stream, skiprows=9, index_col=0, parse_dates=True)
    cols = ["SVENY" + str(i).zfill(2) for i in range(1, 31)]
    return df[cols]


def load_fed_yield_curve(data_dir=DATA_DIR):
    path = data_dir / "fed_yield_curve.parquet"
    _df = pd.read_parquet(path)
    return _df


if __name__ == "__main__":
    target_file = Path(DATA_DIR) / "fed_yield_curve.parquet"
    source_file = Path(__file__)

    # Check if target exists and is newer than source (for test mock data)
    if target_file.exists() and target_file.stat().st_mtime > source_file.stat().st_mtime:
        print(f"Data file {target_file} is up to date, skipping pull")
    else:
        df = pull_fed_yield_curve()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(target_file)
        print(f"Saved Fed yield curve data to {target_file}")
