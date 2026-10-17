# Reading From a Databricks Warehouse

A dataframe can be a table, or a query, in a Databricks SQL warehouse. The pipeline names the
table; the warehouse keeps it. ChartBook reads it where it is, documents it on the site like any
other dataframe, and copies nothing.

## Install the driver

```console
$ pip install "chartbook[databricks]"
```

This installs the Databricks SQL connector. `pip install chartbook` alone does not, so a pipeline
that never reads a warehouse carries none of it.

## Name the table

In `chartbook.toml`, a source says which engine, and each dataframe in it says which table or which
query:

```toml
[sources.warehouse]
backend = "databricks"
url = "databricks://dbc-a1b2c3d4-e5f6.cloud.databricks.com?http_path=/sql/1.0/warehouses/abc123&catalog=workspace"

[dataframes.curve]
name = "Yield Curve"
source = "warehouse"
table = "workspace.rates.curve"
docs = "The zero-coupon curve, as the warehouse keeps it."

[dataframes.slopes]
name = "Yield Curve Slopes"
source = "warehouse"
query = "select d, y10 - y02 as slope from workspace.rates.curve"
docs = "The 10-year yield less the 2-year, computed when read."
```

The `url` names the workspace's host and the SQL warehouse's HTTP path; the warehouse's
**Connection details** tab shows both. `catalog` and `schema` say where a name without them is
found. Every part may be left out, `url = "databricks://"`, when each machine says it instead. A
token never goes here, nor a user name, nor how to sign in: a `url` with one does not load.

## Tell this machine how to sign in

Set the two variables Databricks' own tools read:

```console
$ export DATABRICKS_HOST=dbc-a1b2c3d4-e5f6.cloud.databricks.com
$ export DATABRICKS_TOKEN=dapi...
```

`DATABRICKS_HTTP_PATH` gives the warehouse when the manifest does not. To give one source a whole
URL of its own instead, set `CHARTBOOK_SOURCE_<NAME>_URL`
(`CHARTBOOK_SOURCE_WAREHOUSE_URL` for the source above), or put it under `[warehouse]` in
`~/.chartbook/sources.toml`:

```toml
[warehouse]
url = "databricks://token:dapi...@dbc-a1b2c3d4-e5f6.cloud.databricks.com?http_path=/sql/1.0/warehouses/abc123"
```

To sign in through the browser instead of with a token, say so in the machine's URL for the
source, `CHARTBOOK_SOURCE_WAREHOUSE_URL=databricks://<host>?auth=oauth`: the first connection opens
the browser, and the sign-in serves every connection after it until the process ends. It needs a
person at the browser, so a build server uses a token.

**The token goes only to the host this machine names.** The manifest's host is checked against
`DATABRICKS_HOST`, or against the host of the machine's URL, and a read stops if they differ. A
manifest you cloned, or another pipeline's record in a shared store, can name a host, and this
machine's token must never be sent there because of it. What does run with your token is the
pipeline's own SQL, in your workspace: building a pipeline someone else wrote runs their queries as
you, just as running their code does, so build only what you would run.

## Read it

```python
from chartbook import data

curve = data.load("curve")              # a Polars LazyFrame
curve.head(5).collect()                 # asks the warehouse for 5 rows
data.sql("select max(y10) as top from {curve}").collect()
data.ref("curve")                       # `workspace`.`rates`.`curve`, for SQL you run yourself
data.connect("warehouse")               # the connector's own connection
```

`data.load()` asks the warehouse for the columns at once, so a table that is not there is refused
then. The rows come when the frame is collected, a batch at a time, and `head(n)` with nothing
filtered asks for `n` rows only. `data.sql()` runs in the warehouse, in its dialect; the warehouse
reads its own tables and no file of yours, so a query that also names a file of the pipeline is
refused, and you join the two frames in Polars instead.

ChartBook itself runs nothing but `select` there. The SQL you run with `data.sql()` or
`data.connect()` is yours, with your token's rights.

## On the site

`chartbook docs` describes each table and query from the warehouse: its columns with the
warehouse's type names, its row count, its first rows, and the first and last date of its
`date_col`. This runs queries in the warehouse when the site is built, so the machine building the
site needs the same settings. Where it cannot reach the warehouse, the page says so and the site is
still built.

## What it does not do yet

**Another pipeline cannot pin it yet.** `chartbook snapshot` records a warehouse table without a
copy and says it is not pinned. Pinning a Delta table by its version, so that a pipeline that
depends on this one reads the table as it was, comes next.

## Try it with Databricks Free Edition

[Databricks Free Edition](https://www.databricks.com/learn/free-edition) is free, does not expire
and needs no card. It has one small SQL warehouse and a daily usage quota.

1. Sign up, and open the workspace.
2. Open **SQL Warehouses**, choose the warehouse, and copy **Server hostname** and **HTTP path**
   from **Connection details**.
3. Make a token: click your user name, then **Settings**, **Developer**, **Access tokens**,
   **Generate new token**. If your workspace does not offer tokens, sign in through the browser
   instead: set `CHARTBOOK_SOURCE_WAREHOUSE_URL=databricks://<server hostname>?auth=oauth` in step 6
   in place of the token.
4. In the **SQL Editor**, make a small table:

   ```sql
   create table workspace.default.curve as
   select * from values
     (date'2024-01-01', 1.0, 4.0),
     (date'2024-01-02', 1.1, 4.3),
     (date'2024-01-03', 1.2, 4.1) as t(d, y02, y10);
   ```

5. In a pipeline's `chartbook.toml`, declare it, with your own host and path:

   ```toml
   [sources.warehouse]
   backend = "databricks"
   url = "databricks://<server hostname>?http_path=<HTTP path>&catalog=workspace&schema=default"

   [dataframes.curve]
   source = "warehouse"
   table = "curve"
   docs = "A table in Databricks Free Edition."
   ```

6. Set `DATABRICKS_HOST` and `DATABRICKS_TOKEN`, then, in the pipeline's folder:

   ```console
   $ python -c 'from chartbook import data; print(data.load("curve").collect())'
   $ chartbook docs
   ```

The first query after the warehouse has been idle can take a minute, while it starts.
