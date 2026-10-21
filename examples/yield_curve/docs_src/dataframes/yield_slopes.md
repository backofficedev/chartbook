**Description:** Slopes of the U.S. Treasury zero-coupon yield curve: the 10-year yield less the 1-, 2- and 3-year yields, in percentage points.

**How it is made:** This dataframe is not a file. It is a SQL query, declared in `chartbook.toml`, that DuckDB runs over the `fed_yield_curve` table in `_data/yield_curve.duckdb` whenever the dataframe is read:

```sql
select Date,
       SVENY10 - SVENY01 as slope_10y_1y,
       SVENY10 - SVENY02 as slope_10y_2y,
       SVENY10 - SVENY03 as slope_10y_3y
from fed_yield_curve
order by Date
```

The pipeline builds the DuckDB file from its own parquet data (`src/build_duckdb.py`). ChartBook never writes a table; it names this query and runs it when asked:

```python
from chartbook import data

slopes = data.load("yield_slopes")                       # the query, as a LazyFrame
recent = data.sql("select * from {yield_slopes} where Date >= '2024-01-01'")
```

**Columns:**

| Column | Description |
|--------|-------------|
| `Date` | Observation date |
| `slope_10y_1y` | 10-year yield minus 1-year yield |
| `slope_10y_2y` | 10-year yield minus 2-year yield |
| `slope_10y_3y` | 10-year yield minus 3-year yield |
