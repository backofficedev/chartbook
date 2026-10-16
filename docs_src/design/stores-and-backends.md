# Design: stores and backends

```{note}
A design document, written 2026-10-16 after cross-pipeline dependencies were made to work on one
machine ({doc}`overview`, step 4, and PR 65). It plans how ChartBook keeps the same experience for
the person using it, from a laptop with nothing installed to an organization's own storage and
warehouses. Status: **the settings layers are built (2026-10-16); the store interface is the next work; the rest is proposed.**
The decisions the maintainer has taken are marked *decided*; the rest is *proposed*.
```

## What this is for

ChartBook should scale to zero and to the enterprise with the same manifest, the same commands
and the same `data.load()` calls. On a laptop, `pip install chartbook` and nothing else: the store
is a folder under the home directory, and the data engine is DuckDB, which the package already
brings. In an organization, the store may be an object store or a database, the tables may live
in a warehouse, and the credentials may come from a secret manager, and the pipeline's repository
must not know any of that.

One rule makes it possible, and the sources follow it already: **the manifest names the kind of
thing; the machine says where it is.** A pipeline's `chartbook.toml` says `backend = "duckdb"` and, for a
file engine, the manifest's public path, and never a credential. Where that engine is on this machine comes from the environment or
the settings. This page extends the rule to the store, and says what it takes to add a store or a
backend without changing anything a pipeline's author sees.

## Two extension points, because data moves differently

ChartBook holds data in two ways, and they generalize separately.

| | A **store** | A **backend** |
|---|---|---|
| Holds | Bytes ChartBook *copied*: snapshots, and the pinned files pipelines read | Tables ChartBook *never copies*: a dataframe declared as a `table` or `query` in a `[sources]` entry |
| Is a fact about | The machine, or the organization | The pipeline |
| Named in | The settings (never the manifest) | The manifest, as the engine's name only |
| Today | A folder, content-addressed | DuckDB |
| Later | An object store (S3, GCS, Azure Blob), a shared drive, a database | Snowflake, Databricks, Postgres, … |

### The store is a setting of the machine, never of the pipeline

*Decided 2026-10-16.* A store is where snapshots of all of a person's, or an organization's,
pipelines are kept. Which store a machine uses is not a property of any one pipeline, so it never
appears in `chartbook.toml`, and no record ever names it. It is read from settings, in layers;
each layer is consulted only where the one above it is silent, key by key:

1. the environment, `CHARTBOOK_STORE`, for CI and a one-off run;
2. the user's own settings, `~/.chartbook/settings.toml`;
3. the organization's settings, system-wide: `/etc/chartbook/settings.toml` on Unix and macOS,
   `%ProgramData%\chartbook\settings.toml` on Windows, or the file `CHARTBOOK_SYSTEM_SETTINGS`
   names;
4. the default, `~/.chartbook/store`, so a machine with nothing configured works.

So an organization sets the store once, for every machine, and a person keeps their own choices
for everything else. A person who sets their own store overrides the organization's for
themselves, which is the right way round for a laptop that is sometimes offline.

The setting is a URL, not a path. A bare path is a folder, as today. `s3://bucket/prefix` is an
object store. A database URL is a database used as a store, which is what an organization that
runs everything in one warehouse wants. The key is `[store] url`; `[store] path` is read as a
folder URL for one release of notice, then goes.

### A backend is named by the pipeline, located by the machine

*As built.* Which engine a pipeline reads from is a fact about the pipeline, so `[sources.x]
backend = "duckdb"` stays in the manifest, with the manifest's public `url` for a file engine.
Where that engine is on this machine, and the credentials, come from `CHARTBOOK_SOURCE_<NAME>_URL`
or `~/.chartbook/sources.toml`; reading `sources.toml` in the same layers as the store is
proposed, not built. One pipeline
can read from Postgres while the organization's store is in Snowflake, and nothing in the
repository knows either address.

## Scales to zero: plugins behind extras

*Proposed.* `pip install chartbook` installs no cloud library and no warehouse driver. Each store
kind and each backend is a plugin found by an entry point, as plotting backends already are
({doc}`../guide/plotting-backends`): the groups `chartbook.stores` and `chartbook.backends`. An
extra installs one: `pip install chartbook[s3]`, `chartbook[snowflake]`. The local folder store
and DuckDB are in the package itself and are what you get with no extra. A setting or a manifest
that names a plugin that is not installed gets one message, naming the extra to install.

Credentials stay where they are now: never in a manifest, never in a record, never in a
snapshot. They come from the environment, the settings files, or whatever the organization's
secret manager hands to the process.

## The store interface

*Proposed.* Everything that stores or finds bytes already goes through one class,
`chartbook.store.Store`, and every record refers to bytes by content hash, so the records do not
change when the store does. The class becomes an interface with the local folder as its first
implementation:

| Method | What it does |
|---|---|
| `put(path) -> StoredObject` | Store what a declared path names; the object's name is the hash of what the store holds |
| `has(hash)`, `get(hash)` | Whether an object is there; where it is, as something a reader can open |
| `hashes()`, `size_of(hash)`, `age_of(hash)`, `delete(hash)` | What `verify` and `gc` need |
| `add_root`, `remove_root`, `roots()` | The lockfiles that keep objects alive |
| `write_snapshot`, `read_snapshot`, `snapshots(pipeline, commit)` | The snapshot records, which today are JSON files under `store/snapshots/`; four places in `chartbook.snapshot` reach into the folder for them and move behind this |

Three things tie the folder store to a local disk, and each is a seam, not a wall. `get()` hands
back a filesystem path and the readers open the parquet there; a remote store hands back a URL,
and the readers scan it through Polars, which reads `s3://` paths already, so `data.path()` may
then answer with a URL. `put()` makes objects by reflink, hard link or copy; those are local
speed tricks, and an upload replaces them. And the snapshot folder is listed directly; the
interface's snapshot methods replace that.

The interface is extracted when the second implementation is written, not before, so that it is
shaped by a real one. The first remote store is S3 through one object-store library, behind
`chartbook[s3]`; the headline use is a build server running `chartbook run --frozen` against a
read-only shared store, which already needs no write to it.

## Pins in a warehouse

*Proposed.* A table in a DuckDB file is pinned by writing it out as parquet into the store (PR
65). A table in a warehouse should not be copied out: a warehouse with time travel, Delta
versions, Iceberg snapshots, Snowflake's `AT`, can pin a table as a *version or a timestamp*, and
`data.load("rates:curve")` then runs the query at that version. The lockfile record keeps the
source's `location` and gains a `pinned_at` (the version or timestamp) where it has a
`content_hash` today; the content hash of the result is recorded too when the engine can give
one cheaply, so staleness is still a comparison of hashes. An engine without time travel pins by
copy, as DuckDB does. What a backend must provide, then, is: scan a table or query to Arrow,
describe it, say whether it can pin by version, and run a pinned query. The interface is
formalized from what DuckDB does today, and the first warehouse adapter shapes the rest.

## The order of work

1. This page, and the settings layers with `[store] url`. *Built 2026-10-16:* the organization's file is read where the user's is silent, key by key; each layer is put in order before the merge, so a user's `[store] path` (read as `url` with a warning) still wins over the organization's `url`; a fault in the organization's file is a warning and the file is ignored, a fault in the user's names the file; a relative folder is relative to its settings file.
2. The store interface extracted, the folder store as its implementation, a test double, and the
   snapshot folder access moved behind it. No behaviour changes; the matrix and the live examples
   prove it.
3. The S3 store behind `chartbook[s3]`; readers accept URLs.
4. The backend interface formalized from DuckDB; the first warehouse adapter with version pins.

## What this does not decide

Which warehouse comes first, Snowflake or Databricks; the first one shapes the backend
interface. Whether a warehouse pin should be a version where the engine offers one and a copy
only where it does not, which is the recommendation here. How a database used as a *store*
lays out objects and snapshots inside it. Each is marked where it arises, and each waits for the
maintainer.
