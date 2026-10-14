# Design: data access

```{note}
A design document, not a user guide. It records how `data.load()` grows from "a name that
resolves to a parquet file" into "a name that resolves to a location, which may be a database
table", and why ChartBook stays a thin layer over the database rather than becoming one.

Status: built for DuckDB on 2026-10-13 (step 5 in {doc}`overview`, "Step 5, as built"; GitHub
issue 9): `[sources]`, `table`, `query`, `data.sql()`, `data.ref()`, `data.connect()`, the typed
`location` in the index, and the worked example. Where what was built departs from this page,
the overview says so and this page keeps its text with a dated note.
Companion to the {doc}`asset graph <asset-graph>`, whose rules and "not doing" list apply here.

Revised 2026-10-12: `chartbook.data` is now the front door for **dataframes only**. Everything
in this document is about dataframes, so nothing here changed in substance; the wording about
references and about the index was brought up to date.
```

## The problem

Today a dataframe *is* a file. `data.load()` resolves a name to a parquet path and calls
`pl.scan_parquet`. The manifest has exactly one storage concept, `path`.

Organizations keep their data in Snowflake, Databricks, Postgres or a DuckDB file, and they already
have tools that move it (dbt, Airflow, cron). ChartBook must not become another one. What it can do
is let the *same name* point at a table instead of a file, so that:

- `data.load("acme/rates", "treasury_rates")` keeps working when the parquet moves into a warehouse;
- a user who wants control can write SQL, referring to dataframes by their ChartBook names, and have
  the warehouse run it;
- the catalog page for a table-backed dataframe looks the same as for a file-backed one.

## The rule

**A name resolves to a location. The backend runs the query. Arrow comes back. Polars wraps it.**

ChartBook never parses, plans, rewrites or transpiles SQL. It knows *where* a name lives and
*which dialect* lives there, and it substitutes identifiers. This is dbt's `source()` and `ref()`:
the resolver returns an identifier, and the SQL is the user's.

## Manifest

A pipeline may declare named sources. A dataframe then points at **exactly one of** `path`,
`table` or `query`.

```toml
[sources.warehouse]
backend = "snowflake"
url = "snowflake://acct/RESEARCH_DB"        # the public part only; no credentials, ever

[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/local.duckdb"

[dataframes.treasury_rates]
name = "Treasury Rates"
source = "warehouse"
table = "RATES.TREASURY_RATES"               # a table or view that already exists

[dataframes.term_premium]
name = "Term Premium"
source = "warehouse"
query = "select date, dgs10 - dgs2 as tp from RATES.TREASURY_RATES"   # a view ChartBook defines

[dataframes.yields_local]
path = "./_data/yields.parquet"              # unchanged; the built-in parquet backend, no source needed
```

Rules:

- `table` and `query` require `source`. `path` forbids it. Declaring two of the three is an error.
- `url` follows the SQLAlchemy URL convention (`snowflake://`, `databricks://`, `postgresql://`,
  `duckdb:///`). ChartBook does not use SQLAlchemy; the convention is what Polars, Ibis and Kedro
  already accept, so one string works everywhere.
- Identifiers are three-level everywhere that matters (`catalog.schema.table` in Unity Catalog and
  DuckDB, `database.schema.table` in Snowflake and Postgres). `table` may give one, two or three
  parts; the backend fills the rest from `url` and quotes for its dialect.

### Credentials never enter the repo

The manifest names a source. The machine supplies the secret, in this order:

1. environment variable `CHARTBOOK_SOURCE_<NAME>_URL` holding a complete URL;
2. `~/.chartbook/sources.toml`, a table per source name with either `url` or individual keys
   (`user`, `password`, `token`, `warehouse`, `role`) merged into the manifest URL;
3. the manifest URL alone, which is enough for DuckDB files and for anything the backend's own
   client can authenticate (SSO, key pair, `~/.snowflake/connections.toml`).

This is dbt's `profiles.yml` and Airflow's `conn_id`: code names a handle, the environment
resolves it. `chartbook check` verifies that every source *resolves*, not that it *connects*.

## Python surface

Four calls, from easiest to rawest. The first is unchanged.

```python
from chartbook import data as cb

cb.load("acme/rates", "treasury_rates")          # -> pl.LazyFrame, as today
cb.sql("select date, rate from {acme/rates:treasury_rates} where date >= '2024-01-01'")
cb.ref("acme/rates:treasury_rates")              # -> 'RESEARCH_DB.RATES.TREASURY_RATES'
cb.connect("warehouse")                          # -> the raw duckdb / snowflake / databricks connection
```

- **`load`** returns a `pl.LazyFrame` for every backend. For files, Iceberg and Delta it is truly
  lazy. For a warehouse it is Arrow fetched eagerly and wrapped, because Polars has no lazy
  database scan. The docstring says so. `format="pandas"` and `format="polars_eager"` keep working.
- **`sql`** substitutes each `{ref}` with the backend's identifier. If every reference lives in one
  source, the query runs there, in that dialect, with that engine's pushdown. If references span
  sources, the query runs in DuckDB with each non-DuckDB reference registered as a view or temp
  table first, and the SQL is DuckDB's dialect. That is the whole rule; there is no third case.
  *(As built, 2026-10-13: one source per query, plus any files, which DuckDB reads alongside. Two
  sources are refused. With DuckDB the only engine the mixed case is two DuckDB files, and
  `ATTACH` through `connect()` is the honest answer until there is a second engine.)*
- **`ref`** exists so a user can paste the identifier into SQL they run with their own tooling.
- **`connect`** hands back the client object. Anything ChartBook does not expose is reachable here.

The reference grammar is the one in {doc}`references`: `treasury_rates` is local,
`fed_yield_curve:treasury_rates` is another pipeline, `ftsfr/fed_yield_curve:treasury_rates` is
fully scoped. Every function in `chartbook.data` takes dataframes only, so a reference that names
another kind (`chart/gdp`, `model/x`) is refused, and a `{ref}` inside `sql()` must be a
dataframe. Cross-pipeline references need the resolution chain (step 3 in {doc}`overview`); the
first implementation of this design is local-only. *(As built: the chain existed first, so a
cross-pipeline file dataframe works in `sql()` and `ref()`, as the pinned copy. A table or
query of another pipeline is not pinned and cannot be read across pipelines.)*

Because `sql()` puts dataframes' columns into SQL that the user writes, column names should be
SQL-compatible: letters, digits and underscores, starting with a letter. ChartBook recommends
that for every dataframe; a readable name is metadata, given in a series table
({doc}`index-schema`, "Series").

Two words to keep apart: the *kind of an asset* (`dataframe`, `chart`, …) is part of its
address. The *kind of a location* (`file`, `table`, `query`) is where a dataframe's content is,
and is what this document adds to.

## Backends

A **backend** is the thing behind a source: how to connect, how to quote, how to scan, how to run
SQL, how to describe. A **source** is a configured instance of a backend, named in a manifest.

```python
class Backend(Protocol):
    name: ClassVar[str]                                   # "parquet", "duckdb", "snowflake"
    def ref(self, loc: Location) -> str: ...              # quoted identifier in this dialect
    def scan(self, loc: Location) -> pl.LazyFrame: ...    # lazy where the engine allows
    def sql(self, query: str) -> pl.LazyFrame: ...        # run dialect-native SQL, Arrow -> Polars
    def connect(self): ...                                # raw handle
    def describe(self, loc: Location) -> Description: ... # columns, row count, last modified
```

- **Built in:** `parquet` (what exists today) and `duckdb`. DuckDB is the local engine because its
  relation API returns a real `pl.LazyFrame`, it reads parquet, Iceberg and Delta, and it attaches
  Postgres, SQLite and Unity Catalog. It is also the fallback engine for mixed-source `sql()`.
- **Plugins, later:** `snowflake` and `databricks` using each vendor's Arrow fetch, `postgres` via
  ADBC. Package naming `chartbook-backend-<name>`, entry-point group `chartbook.backends`,
  selected by name from `backend =`. Following the asset graph's rule, the Protocol is extracted
  into a public contract only once the third implementation exists; `duckdb` is the second.
- **Optional, never core:** `cb.table(ref)` returning an `ibis.Table` for users who want Ibis's
  expression API. Ibis stays an extra. The public return type is Polars.

Backends are *selected*, not broadcast, so this is a registry keyed by name, not a pluggy hook.
The plotting backends stay pluggy because many renderers legitimately answer the same call.

## Index consequences

The {doc}`Dataframe record <index-schema>` carries a typed `location` object, which for a file
is `{ "kind": "file", "path", "resolved_path" }`. (The index schema was revised on 2026-10-12 to
have this from its first version, so that this design is an addition and not a migration.) A
table-backed dataframe needs:

- two more kinds of `location`: `{ "kind": "table", "source", "backend", "identifier" }` and
  `{ "kind": "query", "source", "backend", "sql" }`;
- `columns` populated from `describe()` rather than from reading parquet;
- an honest hash. A warehouse table cannot be content-hashed cheaply. Record
  `content_hash: null`, hash the *definition* (identifier or query text plus the described schema),
  and take freshness from the warehouse's own metadata (`last_altered`, or `max(date_col)`). The
  Build record lists the source as impure, exactly as it does for a FRED fetch. Hash what you can,
  record what you cannot.

Settle the exact field names of the `table` and `query` kinds when this is implemented. That a
dataframe's location is a typed object, not a bare path, is settled, and the index schema shows it.

## Vocabulary

| Term | Means | Not |
|---|---|---|
| backend | an engine behind a source: parquet, duckdb, snowflake | "adapter" (dbt's word for a large dialect shim), "connector" (extract-and-load) |
| source | a named, configured instance of a backend in a manifest | a credential |
| exporter | one-way emission of the graph to an orchestrator or standard | "integration" |
| plugin | a pip package that registers backends or exporters via entry points | a design concept; it is only how code arrives |

## Not doing

- **No query planning, rewriting or transpiling.** `sql()` substitutes identifiers and nothing
  else. If dialect translation is ever wanted, it is an optional, best-effort sqlglot pass, and it
  is not in this design.
- **No semantic layer.** No measures, dimensions, joins or metric definitions in the manifest. A
  "series" stays a column of a dataframe, as the index schema has it. If a user wants a derived
  series, `query` is the tool.
- **No writes.** ChartBook never creates, loads or alters a warehouse table. Pipelines write with
  their own tools; `data.path()` serves file outputs; `table` and `query` describe what already
  exists.
- **No credentials in any committed file.** Including the catalog's.
- **No Ibis as a return type or dependency of the core.**
- **No DuckDB-WASM for data access in the browser.** Chart pages embed series inline; anyone who
  wants to query gets `sql()` in Python. Cross-origin parquet in the browser is the problem this
  design avoids.
- **No per-backend plugin system before the third backend.** Rule from the asset graph.

## Phasing

1. **Built (0.2.0).** `data.path()` and `data.load()` call one internal resolver,
   `chartbook.resolve.resolve()`, that returns a typed `Location`. Only `FileLocation` exists.
   `path()` returns a `Path` for file locations and raises `TypeError` for anything else
   (`resolve.require_file()`); `load()` raises `NotImplementedError`. This is the seam; it adds no
   behaviour. To add a location kind: subclass `Location`, return it from the resolver, and teach
   `load()` to scan it.
2. **After the index.** `[sources]`, `table`, `query`; the `duckdb` backend; `sql()`, `ref()`,
   `connect()`; local references only; the index's typed `location`. Worked example: the
   `yield_curve` example pipeline gains one `query`-backed dataframe over a DuckDB file.
   *(Built 2026-10-13.)*
3. **With P1 resolution.** Cross-pipeline references in `sql()` and `ref()`. *(Built with 2,
   for file dataframes.)*
4. **On demand.** `snowflake` and `databricks` as plugins, then extract the Protocol.

## Prior art

- **dbt** `source()` / `ref()`: a name compiles to a qualified identifier spliced into the user's
  SQL. The model for `ref()` and `sql()`.
- **Kedro** `ibis.TableDataset`: `table_name` plus `connection: {backend: duckdb, ...}`; one dataset
  type covers every SQL engine through a `backend` key. The model for `[sources]`.
- **Airflow connections** and **dbt profiles**: code names a handle; the environment resolves it.
  The model for credentials.
- **DuckDB** `relation.pl(lazy=True)`, `ATTACH`, `read_parquet`: the local engine.
- **Polars** `read_database` is eager and there is no `scan_database`; why warehouse loads are
  honest about eagerness.
- **Evidence.dev** sources: a connection file plus `.sql` files in the source's dialect, each
  addressable by name from page-level SQL. The model for `query`.
