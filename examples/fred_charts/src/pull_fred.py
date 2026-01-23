"""Pull basic economic time series from FRED (Federal Reserve Economic Data).

This module fetches a few key economic indicators from FRED and saves them
to a parquet file for use in analysis notebooks.
"""

from pathlib import Path

import pandas as pd
from fredapi import Fred
from chartbook.env import get, get_project_root

DATA_DIR = get_project_root() / "_data"
START_DATE = get("START_DATE", default="2000-01-01")
END_DATE = get("END_DATE", default="2025-12-31")


# Define the series to pull from FRED
series_to_pull = {
    "GDP": "Gross Domestic Product",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "FEDFUNDS": "Federal Funds Effective Rate",
}

series_descriptions = series_to_pull.copy()


def pull_fred(start_date=START_DATE, end_date=END_DATE):
    """
    Pull economic data from FRED.

    Lookup series code, e.g., like this:
    https://fred.stlouisfed.org/series/GDP

    Parameters
    ----------
    start_date : str or datetime
        Start date for the data pull
    end_date : str or datetime
        End date for the data pull

    Returns
    -------
    pd.DataFrame
        DataFrame with FRED time series data indexed by date
    """
    api_key = get("FRED_API_KEY", default=None)
    fred = Fred(api_key=api_key)
    dfs = []
    for series_id in series_to_pull.keys():
        series = fred.get_series(series_id, observation_start=start_date, observation_end=end_date)
        series.name = series_id
        dfs.append(series)
    df = pd.concat(dfs, axis=1)
    return df


def load_fred(data_dir=DATA_DIR):
    """
    Load previously saved FRED data from parquet file.

    Must first run this module as main to pull and save data.

    Parameters
    ----------
    data_dir : Path
        Directory containing the fred.parquet file

    Returns
    -------
    pd.DataFrame
        DataFrame with FRED time series data
    """
    file_path = Path(data_dir) / "fred.parquet"
    df = pd.read_parquet(file_path)
    return df


def demo():
    """Demonstrate loading FRED data."""
    df = load_fred()
    print(df.head())
    print(f"\nColumns: {list(df.columns)}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")


if __name__ == "__main__":
    filedir = Path(DATA_DIR)
    target_file = filedir / "fred.parquet"
    source_file = Path(__file__)

    # Check if target exists and is newer than source (for test mock data)
    if target_file.exists() and target_file.stat().st_mtime > source_file.stat().st_mtime:
        print(f"Data file {target_file} is up to date, skipping pull")
        df = pd.read_parquet(target_file)
    else:
        today = pd.Timestamp.today().strftime("%Y-%m-%d")
        end_date = today
        df = pull_fred(START_DATE, end_date)
        filedir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(target_file)
        df.to_csv(filedir / "fred.csv")
        print(f"Saved FRED data to {filedir}")

    print(f"Series: {list(series_to_pull.keys())}")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
