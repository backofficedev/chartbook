"""Put the Fed yield curve into a DuckDB file, as a table.

This is the pipeline's own tool doing what ChartBook never does: creating a
table. ChartBook then reads it, and the query-backed dataframe `yield_slopes`
is a view over it that ChartBook names in `chartbook.toml`.
"""

import duckdb

from chartbook import data

DB = data.scratch().parent / "yield_curve.duckdb"

if DB.exists():
    DB.unlink()
con = duckdb.connect(str(DB))
con.sql(
    f"create table fed_yield_curve as select * from read_parquet('{data.path('fed_yield_curve')}')"
)
print(f"{DB}: {con.sql('select count(*) from fed_yield_curve').fetchone()[0]} rows")
con.close()
