# Design: the index

```{note}
A design document. The index is the artifact every other part of ChartBook reads or writes, so it
is specified before anything that depends on it. See {doc}`asset-graph` for the mechanism this
serves.

Status: specification proposed, implementation pending.
```

## What the index is

`chartbook build` produces two things: **content** (markdown, as authored) and an **index** (a
structured description of everything the catalog contains). The index is a build product, not
source — the resolved, composed view of the manifests, with paths absolutized, cross-pipeline edges
resolved, defaults filled in, policy inherited and content hashes attached.

```text
_build/
  index.json     # the resolved catalog
  content/       # markdown as authored
  site/          # Sphinx output — one renderer among several
```

The relationship is exactly dbt's `manifest.json` to its `.sql` and `schema.yml` files. And dbt's
entire third-party ecosystem exists because that file is stable and documented, which is the
outcome worth copying.

```{admonition} The index is the product; every renderer is a consumer
:class: important

Sphinx renders it today. Another frontend could render it tomorrow. An MCP server serves it. A
Dagster adapter reads it. A registry stores it. A diff of two of them is a review surface.
Sphinx stops being an architectural commitment and becomes the default frontend.
```

Four properties are load-bearing:

- **Self-contained.** A consumer reads the index and needs nothing else — no catalog lookup, no
  filesystem walk, no manifest parsing.
- **Versioned per record**, so the format can change without a flag day.
- **Content-addressed.** Every asset carries its hash, so the index is the lockfile's source of
  truth rather than a parallel structure.
- **Diffable.** `diff(before, after)` answers "what did this build change?" — which assets moved,
  which hashes changed, which upstream inputs shifted.

## File shape

One JSON object: an envelope, then a flat array of self-describing records.

```json
{
  "schema": "chartbook/index/v1",
  "generated_at": "2026-10-11T22:14:03Z",
  "generator": { "name": "chartbook", "version": "0.2.0" },
  "root": "ftsfr/catalog",
  "records": [ ]
}
```

`schema` versions the *file*; each record versions *itself*. This is the shape Kubernetes uses — a
list with its own version, holding items that each carry `kind` and `version` — and it has survived
a decade and hundreds of resource types.

### Why per-record `kind` and `version`

```json
{ "kind": "Dataframe", "version": "chartbook/v1", "id": "…" }
{ "kind": "Chart",     "version": "chartbook/v1", "id": "…" }
{ "kind": "Build",     "version": "chartbook/v1", "asset": "…" }
```

1. **One file holds mixed types.** New record kinds need no restructuring.
2. **Readers skip what they do not understand.** An MCP server filters for `kind: "Dataframe"`; a
   Dagster adapter that has never heard of `kind: "Note"` ignores it rather than failing.
3. **Version is per record.** Charts can move to `chartbook/v2` while everything else stays `v1`.
   Otherwise every change is a whole-file bump and a coordinated upgrade for every consumer.

Twenty bytes per record, and the cheapest available insurance for a project that intends to stop
breaking things before 1.0.

A JSON Schema is published per `kind` per version, under `schemas/chartbook/v1/<Kind>.json`. That
publication is what makes third-party consumers possible.

## Conventions

**Identifiers** follow the reference grammar in {doc}`asset-graph`:

```text
[registry/]scope/name[:asset[#series]][@rev]
```

Every record's `id` is fully qualified — never bare, never relative — so an ID is meaningful
wherever it is copied to.

**Hashes** are `"<algorithm>:<hex>"`, e.g. `"sha256:7f3a9c…"`. Never a bare hex string, so the
algorithm can change without ambiguity.

**Paths** appear in two forms, both present:

- `path` — exactly as declared in the manifest, relative to the pipeline root. Stable across
  machines. This is what a human compares against their TOML.
- `resolved_path` — absolute, machine-specific. Convenient for a local consumer; meaningless to a
  remote one, and therefore never the field a registry stores.

**Timestamps** are RFC 3339 with an explicit offset, in UTC.

**Absent versus empty.** A field that was not declared is omitted. A field declared as empty is
present and empty. A consumer can therefore tell "no tags were given" from "tags were explicitly
cleared", which matters for diffing.

## Record kinds

### Catalog

The root. Exactly one per index.

```json
{
  "kind": "Catalog", "version": "chartbook/v1",
  "id": "ftsfr/catalog",
  "name": "FTSFR Catalog",
  "pipelines": ["ftsfr/fed_yield_curve", "ftsfr/crsp_treasury"],
  "policy": {
    "mode": "warn",
    "required": { "dataframe": ["name", "description", "sources"] }
  }
}
```

An index for a single pipeline omits the `Catalog` record and sets `root` to that pipeline's ID.

### Pipeline

```json
{
  "kind": "Pipeline", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve",
  "name": "Fed Yield Curve",
  "description": "Daily Treasury constant-maturity yields.",
  "maintainer": "Jeremy Bejarano",
  "contributors": ["…"],
  "repo_url": "https://gitlab.internal/ftsfr/fed_yield_curve",
  "os_compatibility": ["Linux", "Windows"],
  "location": { "kind": "path", "value": "/Users/x/repos/fed_yield_curve" },
  "scripts": { "build": "doit", "test": "pytest" },
  "dependencies": [
    {
      "id": "ftsfr/crsp_compustat",
      "via": "rev",
      "location": { "kind": "git", "url": "https://gitlab.internal/…", "rev": "a1b2c3d" },
      "pinned_hash": "sha256:…"
    }
  ],
  "assets": ["ftsfr/fed_yield_curve:treasury_rates"],
  "docs": { "path": "./README.md", "rendered": "content/ftsfr/fed_yield_curve/readme.md" }
}
```

`location.kind` is `"path"` or `"git"`. `dependencies[].via` records whether the pin came from a
local directory or a fetched revision — the field that keeps "was this built against a stable
upstream?" answerable.

### Dataframe

```json
{
  "kind": "Dataframe", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:treasury_rates",
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Treasury Rates",
  "description": "Constant-maturity yields from H.15.",
  "path": "./_data/treasury_rates.parquet",
  "resolved_path": "/Users/x/repos/fed_yield_curve/_data/treasury_rates.parquet",
  "content_hash": "sha256:…",
  "size_bytes": 2148374,
  "row_count": 15842,
  "date_col": "date",
  "columns": [
    { "name": "date",  "dtype": "date" },
    { "name": "DGS10", "dtype": "float64" },
    { "name": "DGS2",  "dtype": "float64" }
  ],
  "inputs": ["ftsfr/crsp_compustat:ratings"],
  "sources": ["FRED"],
  "providers": ["Federal Reserve Board"],
  "access_types": ["Public"],
  "license": "Public domain",
  "license_expiration": null,
  "tags": ["Interest Rates", "Daily"],
  "docs": { "path": "./docs_src/dataframes/treasury_rates.md",
            "rendered": "content/ftsfr/fed_yield_curve/dataframes/treasury_rates.md" },
  "built_by": "sha256:…"
}
```

`columns` carries the physical schema read from the parquet file. This is what makes **which series
exist knowable without any declaration** — see below. `inputs` carries the asset-level edges;
`built_by` points at the `Build` record whose `output_hash` matches.

### Series

A series needs no storage — the dataframe holds the data. It needs an *address*, so documentation
and metadata can attach to one column.

```json
{
  "kind": "Series", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:treasury_rates#dgs10",
  "dataframe": "ftsfr/fed_yield_curve:treasury_rates",
  "column": "DGS10",
  "declared": true,
  "name": "10-Year Treasury Constant Maturity",
  "units": "Percent",
  "frequency": "Daily",
  "docs": { "path": "./docs_src/series/dgs10.md", "rendered": "…" }
}
```

`declared: false` marks a series inferred from the parquet schema — present, addressable, and
undocumented. `declared: true` marks one with a `[dataframes.x.series.y]` table behind it. So
declaring is how you *document* a series, not how you make it exist, and a FRED-style listing works
from day one without anyone filling in metadata.

An explicit `column` is what lets the address survive a column rename.

### Chart

```json
{
  "kind": "Chart", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:curve_today",
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Yield Curve, Latest",
  "path": "./_output/curve_today.html",
  "content_hash": "sha256:…",
  "inputs": ["ftsfr/fed_yield_curve:treasury_rates#dgs10",
             "ftsfr/fed_yield_curve:treasury_rates#dgs2"],
  "tags": ["Interest Rates"],
  "frequency": "Daily",
  "units": "Percent",
  "date_cleared_by_iv_and_v": "2026-01-15",
  "last_legal_clearance_date": "2026-01-15",
  "docs": { "path": "…", "rendered": "…" }
}
```

`inputs` replaces the single `dataframe` field, as a list — a chart may plot several dataframes, and
with series now addressable it may name individual series. This is a breaking change to the manifest
and worth taking while nothing external depends on it.

### Notebook and Note

```json
{ "kind": "Notebook", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:analysis",
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Initial exploration",
  "path": "./_output/analysis.ipynb",
  "content_hash": "sha256:…",
  "inputs": ["ftsfr/fed_yield_curve:treasury_rates"] }
```

```json
{ "kind": "Note", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:methodology",
  "pipeline": "ftsfr/fed_yield_curve",
  "docs": { "path": "./docs_src/methodology.md", "rendered": "…" } }
```

A notebook's `name` is inferred from its first level-one heading when not declared, as today.

### Build

The derivation record: a complete description of how an asset was produced. One object serving as
build plan, cache key and provenance record.

```json
{
  "kind": "Build", "version": "chartbook/v1",
  "asset": "ftsfr/fed_yield_curve:treasury_rates",
  "input_hash": "sha256:…",
  "output_hash": "sha256:…",
  "recipe_hash": "sha256:…",
  "params": {},
  "inputs": {
    "ftsfr/crsp_compustat:ratings": {
      "hash": "sha256:…",
      "via": "rev",
      "location": "https://gitlab.internal/ftsfr/crsp_compustat@a1b2c3d"
    }
  },
  "tools": { "chartbook": "0.2.0", "python": "3.12.4", "polars": "1.9.0" },
  "built_at": "2026-10-11T21:58:09Z",
  "duration_seconds": 412.6,
  "impure": ["wrds_fetch"]
}
```

`input_hash` is the store's lookup key — computable *before* building, which is what lets a cache be
asked and the work skipped. `output_hash` is what downstream consumers compare, so a rebuild
producing identical bytes does not cascade.

**Hashes are transitive.** `input_hash` covers each input's *hash*, not its path or name. Because
those hashes were computed the same way, an asset's identity transitively covers its whole upstream
history — a Merkle DAG, the same structure that makes a git commit hash a statement about an entire
repository. That is what makes recorded lineage *checkable* rather than merely trusted.

`impure` names steps that cannot be reproduced from their inputs. Verifiability reaches back to the
last impure boundary, and a digest of what arrived is recorded there.

## Where the lockfile fits

`chartbook.lock` is the subset of the index that a project commits: its own `Build` records and its
resolved `dependencies`. The index is a build product and need not be committed; the lockfile is
source, because it is what makes a rebuild reproducible and an upstream pin stable.

Both use the same record schemas. There is no second format.

## Candidate additions, deliberately out of v1

- **`Diagnostic` records** carrying metadata-completeness results. Derived and recomputable, so the
  index does not need to carry them yet.
- **A parquet form of the asset table**, for catalogs large enough that a browser should query the
  index with DuckDB-WASM rather than parse JSON.
- **Per-pipeline index fragments** (`_build/index/<scope>/<name>.json`) to make incremental
  regeneration cheap. An implementation detail if adopted; `index.json` stays the normative artifact
  a consumer reads.
- **An `Export` record** describing what was emitted to RO-Crate, OpenLineage or Dagster, so a
  consumer can tell which views exist.

## Worked example

The smallest useful index — one pipeline, one dataframe, one documented series, one chart.

```json
{
  "schema": "chartbook/index/v1",
  "generated_at": "2026-10-11T22:14:03Z",
  "generator": { "name": "chartbook", "version": "0.2.0" },
  "root": "ftsfr/fed_yield_curve",
  "records": [
    { "kind": "Pipeline", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve",
      "name": "Fed Yield Curve",
      "location": { "kind": "path", "value": "/Users/x/repos/fed_yield_curve" },
      "scripts": { "build": "doit" },
      "dependencies": [],
      "assets": ["ftsfr/fed_yield_curve:treasury_rates",
                 "ftsfr/fed_yield_curve:curve_today"] },

    { "kind": "Dataframe", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:treasury_rates",
      "pipeline": "ftsfr/fed_yield_curve",
      "name": "Treasury Rates",
      "path": "./_data/treasury_rates.parquet",
      "content_hash": "sha256:4b1f…",
      "date_col": "date",
      "columns": [ { "name": "date", "dtype": "date" },
                   { "name": "DGS10", "dtype": "float64" } ],
      "inputs": [],
      "built_by": "sha256:9ac2…" },

    { "kind": "Series", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:treasury_rates#dgs10",
      "dataframe": "ftsfr/fed_yield_curve:treasury_rates",
      "column": "DGS10", "declared": true,
      "name": "10-Year Treasury Constant Maturity",
      "units": "Percent", "frequency": "Daily" },

    { "kind": "Chart", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:curve_today",
      "pipeline": "ftsfr/fed_yield_curve",
      "name": "Yield Curve, Latest",
      "path": "./_output/curve_today.html",
      "content_hash": "sha256:cc71…",
      "inputs": ["ftsfr/fed_yield_curve:treasury_rates#dgs10"] },

    { "kind": "Build", "version": "chartbook/v1",
      "asset": "ftsfr/fed_yield_curve:treasury_rates",
      "input_hash": "sha256:0e55…",
      "output_hash": "sha256:4b1f…",
      "recipe_hash": "sha256:7721…",
      "inputs": {},
      "tools": { "chartbook": "0.2.0", "python": "3.12.4" },
      "built_at": "2026-10-11T21:58:09Z",
      "impure": ["fred_api_fetch"] }
  ]
}
```

Note the `Series` record for `DGS10` but none for `date`, and that a hypothetical `DGS2` column
would appear as `declared: false` — addressable, undocumented. Note also that the chart's `inputs`
names a *series*, so "what does this chart depend on" is answerable at column granularity even
though the build graph remains coarse.

## What this unblocks

Once the index exists, several things stop being subsystems and become readers of one file:

- An **MCP server** exposing pipelines and assets as resources, and `data.load` as a tool.
- A **Dagster export**, mapping each asset to an `@asset` with `deps`.
- **Faceted search** over the catalog, computed in a browser against a small file.
- A **provenance panel** on every asset page: what built this, from which inputs at which hashes.
- A **build diff** for reviewing what changed, including changes made by automated tooling.

Which is the reason this document comes first.
