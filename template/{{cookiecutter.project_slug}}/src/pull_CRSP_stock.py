"""
Functions to pull and calculate the value and equal weighted CRSP indices.

This module uses the CRSP CIZ format (Flat File Format 2.0), which replaced
the legacy SIZ format as of January 2025.

Key resources:
 - Data for indices: https://wrds-www.wharton.upenn.edu/data-dictionary/crsp_a_indexes/
 - Tidy Finance guide: https://www.tidy-finance.org/python/wrds-crsp-and-compustat.html
 - CRSP 2.0 Update: https://www.tidy-finance.org/blog/crsp-v2-update/
 - Transition FAQ: https://wrds-www.wharton.upenn.edu/pages/support/manuals-and-overviews/crsp/stocks-and-indices/crsp-stock-and-indexes-version-2/crsp-ciz-faq/
 - Cross-Reference Guide: https://www.crsp.org/wp-content/uploads/guides/CRSP_Cross_Reference_Guide_1.0_to_2.0.pdf

Key changes from SIZ to CIZ format:
 - Monthly stock table: crspm.msf -> crspm.msf_v2
 - Security info: crspm.msenames -> crspm.stksecurityinfohist
 - Delisting returns are now built into mthret (no separate table needed)
 - Column names: date->mthcaldt, ret->mthret, retx->mthretx, prc->mthprc
 - Share code filters (shrcd) replaced with securitytype, securitysubtype, sharetype

Thank you to Tobias Rodriguez del Pozo for his assistance in writing this code.

"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import wrds
from dateutil.relativedelta import relativedelta
from pandas.tseries.offsets import MonthEnd

from settings import config

DATA_DIR = Path(config("DATA_DIR"))
WRDS_USERNAME = config("WRDS_USERNAME")
START_DATE = config("START_DATE")
END_DATE = config("END_DATE")


def pull_CRSP_monthly_file(
    start_date=START_DATE, end_date=END_DATE, wrds_username=WRDS_USERNAME
):
    """
    Pulls monthly CRSP stock data from a specified start date to end date.

    Uses the new CRSP CIZ format (msf_v2 and stksecurityinfohist tables).
    Delisting returns are now built into mthret, so no separate handling needed.

    Notes
    -----

    From Bali, Engle, Murray -- Empirical asset pricing-the cross section of stock returns (2016):
    "There are two main proxies for the market portfolio that are commonly used
    in empirical asset pricing research. The first is the value-weighted portfolio of all
    U.S.-based common stocks in the CRSP database... We follow common convention by referring
    to this portfolio and its excess returns as MKT. The second portfolio commonly used as
    a proxy for the market portfolio is the CRSP value-weighted portfolio, which contains
    all securities in the CRSP database, not just common stocks, but excluding American
    Depository Receipts (ADRs). Following CRSP, we denote this portfolio VWRETD."

    **CIZ Format Security Filtering:**

    The old SIZ format used share codes (shrcd):
    * 10, 11: Common stock
    * 20, 21: Preferred stock
    * 40, 41: Warrants
    * 70, 71: Units
    * 73: Foreign stocks

    The new CIZ format uses these fields instead:
    * securitytype: 'EQTY' for equity
    * securitysubtype: 'COM' (common), 'PFD' (preferred), etc.
    * sharetype: 'NS' (no special), 'AD' (ADR), etc.
    * usincflg: 'Y' for US incorporated
    * issuertype: 'ACOR', 'CORP' for corporations

    This function uses a broad filter to approximate the original shrcd filter
    for VWRETD replication purposes.

    **Note on Returns:**
    The new mthret uses compound daily returns with dividends reinvested on
    ex-dates, which may differ slightly from the old ret (month-to-month
    holding period return with dividends reinvested at month-end).

    """
    # Convert start_date to datetime if it's a string
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    # Not a perfect solution, but since value requires t-1 period market cap,
    # we need to pull one extra month of data. This is hidden from the user.
    start_date = start_date - relativedelta(months=1)
    start_date = start_date.strftime("%Y-%m-%d")

    # CIZ format query using msf_v2 and stksecurityinfohist
    # Delisting returns are now built into mthret - no separate join needed
    query = f"""
    SELECT
        msf.permno,
        msf.permco,
        msf.mthcaldt,
        msf.mthret,
        msf.mthretx,
        msf.shrout,
        msf.mthprc,
        msf.mthvol,
        msf.mthcumfacshr,
        msf.mthcumfacpr,
        ssih.primaryexch,
        ssih.siccd,
        ssih.naics,
        ssih.issuertype,
        ssih.securitytype,
        ssih.securitysubtype,
        ssih.sharetype,
        ssih.usincflg,
        ssih.tradingstatusflg,
        ssih.conditionaltype
    FROM crspm.msf_v2 AS msf
    INNER JOIN crspm.stksecurityinfohist AS ssih
        ON msf.permno = ssih.permno
        AND ssih.secinfostartdt <= msf.mthcaldt
        AND msf.mthcaldt <= ssih.secinfoenddt
    WHERE
        msf.mthcaldt BETWEEN '{start_date}' AND '{end_date}'
        AND ssih.securitytype = 'EQTY'
    """
    # Note: Using securitytype = 'EQTY' as broad filter to include various equity types.
    # For stricter common-stock-only filtering, add:
    #   AND ssih.securitysubtype = 'COM'
    #   AND ssih.sharetype = 'NS'
    #   AND ssih.usincflg = 'Y'
    #   AND ssih.issuertype IN ('ACOR', 'CORP')

    db = wrds.Connection(wrds_username=wrds_username)
    df = db.raw_sql(query, date_cols=["mthcaldt"])
    db.close()

    df = df.loc[:, ~df.columns.duplicated()]

    # shrout is in thousands in CRSP, convert to actual shares
    df["shrout"] = df["shrout"] * 1000

    # Rename columns for backward compatibility with downstream code
    df = df.rename(
        columns={
            "mthcaldt": "date",
            "mthret": "ret",
            "mthretx": "retx",
            "mthprc": "prc",
            "mthvol": "vol",
            "mthcumfacshr": "cfacshr",
            "mthcumfacpr": "cfacpr",
        }
    )

    # Create altprc for compatibility (absolute value of price)
    df["altprc"] = df["prc"].abs()

    # Calculate adjusted shares and prices for market cap calculation
    df["adj_shrout"] = df["shrout"] * df["cfacshr"]
    df["adj_prc"] = df["prc"].abs() / df["cfacpr"]
    df["market_cap"] = df["adj_prc"] * df["adj_shrout"]

    # Add jdate (month-end aligned date) for portfolio formation
    df["jdate"] = df["date"] + MonthEnd(0)

    return df


def pull_CRSP_index_files(
    start_date=START_DATE, end_date=END_DATE, wrds_username=WRDS_USERNAME
):
    """
    Pulls the CRSP index files from crsp_a_indexes.msix:
    (Monthly) NYSE/AMEX/NASDAQ Capitalization Deciles, Annual Rebalanced (msix)

    Note: The index tables (crsp_a_indexes) were not significantly changed
    in the CIZ transition. The column names and structure remain the same.
    """
    query = f"""
        SELECT *
        FROM crsp_a_indexes.msix
        WHERE caldt BETWEEN '{start_date}' AND '{end_date}'
    """
    db = wrds.Connection(wrds_username=wrds_username)
    df = db.raw_sql(query, date_cols=["caldt"])
    db.close()
    return df


def load_CRSP_monthly_file(data_dir=DATA_DIR):
    path = Path(data_dir) / "CRSP_monthly_stock.parquet"
    df = pd.read_parquet(path)
    return df


def load_CRSP_index_files(data_dir=DATA_DIR):
    path = Path(data_dir) / "CRSP_MSIX.parquet"
    df = pd.read_parquet(path)
    return df


def _demo():
    df_msf = load_CRSP_monthly_file(data_dir=DATA_DIR)
    df_msix = load_CRSP_index_files(data_dir=DATA_DIR)


if __name__ == "__main__":
    df_msf = pull_CRSP_monthly_file(start_date=START_DATE, end_date=END_DATE)
    path = Path(DATA_DIR) / "CRSP_monthly_stock.parquet"
    df_msf.to_parquet(path)

    df_msix = pull_CRSP_index_files(start_date=START_DATE, end_date=END_DATE)
    path = Path(DATA_DIR) / "CRSP_MSIX.parquet"
    df_msix.to_parquet(path)
