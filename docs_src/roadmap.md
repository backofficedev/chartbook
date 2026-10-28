# Roadmap

What ChartBook does now, what is an early experiment, and what may come next. Nothing below the first
section is a promise; it is where the work is pointed.

## Now: one machine, and a folder shared between machines

ChartBook is meant to be useful on one laptop with nothing but `pip install chartbook`:

- A pipeline documents its charts, dataframes, notebooks and models in `chartbook.toml`, and
  `chartbook build` makes a site of them.
- A catalog gathers several pipelines into one site.
- One pipeline reads another's data by name, from a **snapshot** in the **store**, pinned in its
  lockfile, so that what it read is recorded and can be read again
  ({doc}`guide/depending-on-pipelines`).

Several machines share by sharing the store: point each one at the same folder, on a network drive
or in a synced folder such as Google Drive, Dropbox or OneDrive (`CHARTBOOK_STORE`, or `[store] url`
in the settings; see {doc}`reference/configuration`). A bucket in S3 works the same way, with
`pip install chartbook[s3]`.

The work now is to make this smooth from end to end, for one person on one machine first.

## Next: 0.3.0

The plan is {doc}`design/plan-0.3.0`. At its centre is a store a person can find their way
around: one folder for each pipeline, which can be sent to someone else and added to their store,
by hand or with `chartbook store export` and `store import`. Inside it, each snapshot has a folder
holding the pipeline's files under their own names, and each file is kept once, however many
snapshots hold it, so a dataset that grows by a file a year no longer stores a full copy each time.
With it come files that are not tables, tables stored as CSV, JSON lines or Arrow IPC, more for
datasets of many files, and a clear message about long paths on Windows.

## Experimental: Databricks

A dataframe can be a table or a query in a Databricks SQL warehouse
({doc}`guide/reading-a-warehouse`). It is an early experiment, more so than the rest of ChartBook: it
has been tested against a stand-in for the warehouse, not yet against a real workspace, and how it
works may change. It is here to make sure ChartBook can grow adapters for other warehouses: the
engine behind a source is a plugin (`chartbook.backends`), as a kind of store is
(`chartbook.stores`).

Reading works: `data.load()`, `data.sql()`, `data.ref()`, and the site's pages for such a dataframe.
What another pipeline cannot do yet is pin a Databricks table.

## Next, to research

**Pinning a Delta table by its version.** Delta tables keep a history of versions, so a pin could
name a version, `VERSION AS OF 42`, rather than copy the rows out of the warehouse. This is built,
and reviewed three times, in [pull request 90](https://github.com/backofficedev/chartbook/pull/90), and is held back for one question about
Databricks itself: how long an old version stays readable. Delta keeps the files of old versions for
7 days by default, and newer runtimes refuse to read a version "older than" that. If the 7 days count
from when a version was written, a pin of a table no one has changed for a week breaks at its next
commit, and Databricks' own optimization of a Unity Catalog table makes such commits. The way to
find out is a pin on a real workspace (Databricks Free Edition is enough). If version pins hold up,
they come in; if not, the choice is between copying a table's rows into the store and asking a
table's owner to keep more history.

**Snowflake.** The same kind of adapter, for a Snowflake warehouse. Snowflake keeps history for time
travel too, a day by default, so the same question about pins arises there.

**Other warehouses** (Postgres, BigQuery) as plugins, once two are built and the interface has
settled.

**A database as the store,** for an organization that keeps everything in one warehouse
({doc}`design/stores-and-backends` leaves its layout open).

**An MCP server,** so that an assistant can browse a catalog and read what it describes.
