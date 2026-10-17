# Design: the index

```{note}
A design document. The index is the artifact every other part of ChartBook reads or writes, so it
is specified before anything that depends on it. See {doc}`asset-graph` for the mechanism this
serves.

Status: **the first implementation is built** (`chartbook.index`, `chartbook.hashing`): every
build writes `index.json` with `Catalog`, `Pipeline`, `Dataframe`, `Series`, `Chart`, `Notebook`,
`Note` and `Model` records, and each pipeline's declared `dependencies`. `Build` records and
pinned hashes are not written yet; they come with the parts of the {doc}`asset graph
<asset-graph>` that produce them.
{ref}`index-implementing` says exactly what is and is not there.

Revised 2026-10-12, before any of it was built: IDs carry the asset's kind
(`…:chart/curve_today`), every asset record has a structured `ref`, an asset's whereabouts is a
typed `location` object, a `Model` record was added, and the `Build` record gained `code`. The
reasons are in {doc}`references`, {doc}`models` and {doc}`data-access`.
```

## What the index is

`chartbook build` produces two things: the **write-ups** (markdown, as authored) and an **index** (a
structured description of everything the catalog contains). *(2026-10-14: the words are now fixed
in {doc}`../guide/vocabulary`: a writer turns the index into **pages** for a site tool; the index
records facts and no renderings; the lockfile is never merged into it.)* The index is a build product, not
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
- **Content-addressed.** Every asset carries its hash, in the same record format the lockfile
  and a snapshot use. *(2026-10-14: the lockfile stays its own document, an input to the build
  where the index is the output; the shared record format is the only merge.)*
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

(Today the file is not under `_build/`. It is written beside the HTML, as `docs/index.json`, and
in the build directory. See {ref}`index-implementing`.)

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

They are in the package, at `chartbook/schemas/chartbook/v1/`, with one for the envelope at
`chartbook/schemas/chartbook/index/v1.json`, and they are published with this documentation at
the URL each one's `$id` gives, e.g.
`https://backofficedev.github.io/chartbook/schemas/chartbook/v1/Dataframe.json`. Each schema
fixes the fields this document names and allows others, because an asset record also carries
whatever else its manifest entry declares.

## Conventions

**Identifiers** follow the reference grammar in {doc}`references`:

```text
[registry/][scope/]pipeline:[kind/]name[#part][@rev]
```

Every record's `id` is fully qualified — never local, never relative — so an ID is meaningful
wherever it is copied to. An asset's ID carries its kind, unless it is a dataframe:

```text
ftsfr/fed_yield_curve                          Pipeline
ftsfr/fed_yield_curve:treasury_rates           Dataframe
ftsfr/fed_yield_curve:treasury_rates#dgs10     Series
ftsfr/fed_yield_curve:chart/curve_today        Chart
ftsfr/fed_yield_curve:notebook/analysis        Notebook
ftsfr/fed_yield_curve:note/methodology         Note
ftsfr/fed_yield_curve:model/rate_forecaster    Model
```

An ID never carries `@rev`. Which version a record describes is said by its `content_hash`.

Each kind has its own names, so the kind is what keeps `…:gdp` (a dataframe) and `…:chart/gdp`
(a chart) apart. An earlier draft of this document gave both the ID `…:gdp`.

**`ref`.** Every asset record, and every `Series` record, also carries the same address as named
fields, so that no consumer ever has to parse an ID:

```json
"id":  "ftsfr/fed_yield_curve:chart/curve_today",
"ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve", "kind": "chart", "name": "curve_today" }
```

`kind` and `name` are always present; `registry`, `scope`, `pipeline` and `part` appear when
set. This is exactly `chartbook.refs.AssetRef.to_dict()`, and `str()` of the same object is the
`id`. Build both from one `AssetRef`; never assemble an ID by joining strings.

**Record kinds and asset kinds.** A record's `kind` is capitalized (`Chart`). The kind in a
reference is lowercase (`chart`). For the five asset kinds one is the other, capitalized:
`dataframe`/`Dataframe`, `chart`/`Chart`, `notebook`/`Notebook`, `note`/`Note`, `model`/`Model`.
`Catalog`, `Pipeline`, `Series` and `Build` are records that are not assets.

**Hashes** are `"<algorithm>:<hex>"`, e.g. `"sha256:7f3a9c…"`. Never a bare hex string, so the
algorithm can change without ambiguity.

What gets hashed is fixed, because hash computation is one of the three things that must have
exactly one implementation ({ref}`not-doing`):

- **A file:** SHA-256 of its bytes.
- **A glob of files, or a directory:** SHA-256 of a listing with one line per file,
  `<hex of the file's SHA-256>`, two spaces, `<path relative to the directory or to the glob's
  fixed prefix, with forward slashes>`, newline; lines sorted by path (by code point, which is
  what `LC_ALL=C sort` gives). The fixed prefix of a glob is its leading directories that
  contain no wildcard: `_data/rates` for `_data/rates/**/*.parquet`. This is the output format
  of `sha256sum`, so anyone can reproduce it by hand, and a test does. A glob that matches one
  file is still a listing. *(Decided 2026-10-12; implemented in `chartbook.hashing`. Once a
  release carries it, it must not change without a new algorithm prefix.)*
- **Which files count:** every file, hidden ones included, except a short, fixed list that
  operating systems create by themselves: `.DS_Store`, `Thumbs.db`, `desktop.ini`, and any file
  whose name starts with `._`, compared without regard to case. So opening a model's folder in
  Finder does not change the model's hash, and a Zarr dataset's `.zarray` still counts. The
  list applies to a directory and to a glob. A `path` that names one file is that file,
  whatever it is called. *(Decided by the maintainer 2026-10-12, replacing "every file counts,
  hidden ones included". No release carried the earlier rule, so the algorithm prefix is
  unchanged. `chartbook.hashing.is_ignored`.)*

**Location.** Where an asset's content is, as a typed object. Today there is one kind:

```json
"location": { "kind": "file",
              "path": "./_data/treasury_rates.parquet",
              "resolved_path": "/Users/x/repos/fed_yield_curve/_data/treasury_rates.parquet" }
```

- `path` — exactly as declared in the manifest, relative to the pipeline root. Stable across
  machines. This is what a human compares against their TOML.
- `resolved_path` — absolute, machine-specific. Convenient for a local consumer; meaningless to a
  remote one, and therefore never the field a registry stores, and never published to a website.

{doc}`data-access` adds `"kind": "table"` and `"kind": "query"` for dataframes that live in a
database. That a location is a typed object and not a bare path was settled there; this document
used to show `path` and `resolved_path` at the top level of each record.

A `Pipeline` record also has a `location`, with a different vocabulary: `"path"` or `"git"`,
saying where the pipeline's *source* comes from.

**Docs.** An asset's write-up is `"docs": { "path": "./docs_src/…md" }` when the manifest gives
`docs_path`, and `"docs": { "text": "…" }` when it gives the text inline with `docs`. The
`rendered` key shown in the examples below points into the `content/` directory of the target
layout; it is not written until that layout exists.

**Declared metadata.** An asset record carries every field its manifest entry declares
(`sources`, `tags`, `license`, `units`, a field of your own), as declared, with keys sorted. TOML
dates become ISO strings. What the index states in another form is left out: `path` (it is in
`location`), `docs` and `docs_path` (in `docs`), a chart's `dataframe` (in `inputs`), and a
dataframe's `series` (they are records of their own). A chart's `series`, the list of what it
shows, is declared metadata and stays (so written 2026-10-15; before that the index dropped it
from every kind).

**Timestamps** are RFC 3339 with an explicit offset, in UTC.

`generated_at` is when the index last *changed*. A build that finds nothing different from the
`index.json` already there leaves the file as it is, timestamp included, so that a build which
changes nothing writes nothing and a published site does not churn. *(Decided 2026-10-12.)*

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
    "required": { "dataframes": ["name", "description", "sources"] }
  }
}
```

`policy` is the catalog's resolved `[policy]`, so the keys of `required` are the manifest's:
`project`, `dataframes`, `charts`, `notebooks`. *(An earlier version of this example wrote
`dataframe`.)*

An index for a single pipeline omits the `Catalog` record and sets `root` to that pipeline's ID.

*(2026-10-15, built: the `Catalog` record also has a `location`, `{"kind": "path", "value":
"/…/catalog"}`, as a pipeline's has, so a writer knows where the catalog's own template
overrides are; it is dropped from the published index altogether, since a catalog is only ever
a folder and a bare `kind` would say nothing. The diagnostics page is a
comparison a writer makes from the records and this record's `policy`, as the inventory
proposed; the build still writes the same comparison as a CSV file.)*

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
  "assets": ["ftsfr/fed_yield_curve:treasury_rates",
             "ftsfr/fed_yield_curve:chart/curve_today"],
  "docs": { "path": "./README.md", "rendered": "content/ftsfr/fed_yield_curve/readme.md" }
}
```

`location.kind` is `"path"` or `"git"`. `dependencies[].via` records whether the pin came from a
local directory or a fetched revision — the field that keeps "was this built against a stable
upstream?" answerable.

*(2026-10-15, built: a pipeline that supplies pages for its own site — `[project] site_dir`, or
`docs_src/site/` when that exists — has `site_dir` (`path` relative to its root, and
`resolved_path` until published) and `site_pages`, every Markdown file under it by relative path,
sorted. The build copies them beside the generated pages; a writer lists them in the front page's
table of contents and reads `index_toc.md` if it is one of them. Without hashes for now.)*

*(Added 2026-10-12 with the implementation; proposed.)* The example above shows a `git`
dependency. One that is a directory is written like this:

```json
{ "id": "ftsfr/fed_yield_curve",
  "via": "path",
  "location": { "kind": "path", "path": "../fed_yield_curve",
                "value": "/Users/x/repos/fed_yield_curve" } }
```

`path` is as declared in `[dependencies]`, relative to the pipeline's root. `value` is the
absolute directory, as in the pipeline's own `location`, and like it is left out of a published
index. `pinned_hash` is there once the dependency is pinned, copied from `chartbook.lock`. A `git` location's `url` is written
without any user name or password it had in the manifest (`https://user:token@host/…`), since a
published index goes wherever the site goes.

`dependencies` is absent when the manifest has no `[dependencies]` table, and `[]` when it has
an empty one, by the rule under "Absent versus empty". (The worked example below writes
`"dependencies": []` for a pipeline that is not said to have the table.)

A dependency's `id` is its key in `[dependencies]`, with one exception. A key is the pipeline's
own name for another pipeline. In a catalog's index, a dependency that is one of the catalog's
pipelines is written by the catalog's ID for it, so that it is the `id` of a `Pipeline` record
in the same file. The same goes for a model's `inputs`.

### Dataframe

```json
{
  "kind": "Dataframe", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:treasury_rates",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "dataframe", "name": "treasury_rates" },
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Treasury Rates",
  "description": "Constant-maturity yields from H.15.",
  "location": { "kind": "file",
                "path": "./_data/treasury_rates.parquet",
                "resolved_path": "/Users/x/repos/fed_yield_curve/_data/treasury_rates.parquet" },
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
exist knowable without any declaration** — see below. The schema is read the way `data.load()`
reads it, so it includes the partition columns of a hive-partitioned dataset, and a `dtype` is
the Polars type in lower case with its parameters in square brackets: `float64`, `int32`,
`string`, `boolean`, `date`, `datetime[ns]`, `datetime[us, UTC]`, `duration[ms]`,
`decimal[10,2]`, `list[int64]`, `categorical`, `struct`. *(The dtype vocabulary was added
2026-10-12 with the implementation; this document had only shown `date` and `float64`.)* `inputs` carries the asset-level edges;
`built_by` points at the `Build` record whose `output_hash` matches.

### Series

A series needs no storage — the dataframe holds the data. It needs an *address*, so documentation
and metadata can attach to one column.

```json
{
  "kind": "Series", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:treasury_rates#dgs10",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "dataframe", "name": "treasury_rates", "part": "dgs10" },
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

A series is the **part** of a dataframe, in the reference grammar's word: what follows `#`. For
an undeclared series the part is the column's own name. A column whose name is not a legal part
(it contains a space, say) gets no `Series` record until a `[dataframes.x.series.y]` table gives
it a key; it still appears in the dataframe's `columns`. *(Decided 2026-10-12.)*

That is deliberate, and comes with a recommendation the maintainer made when deciding it:
**columns should have code-friendly, SQL-compatible names**, letters, digits and underscores,
starting with a letter (`spread_10y_2y`). The readable name ("10Y-2Y Spread") is metadata, and
belongs in the series table's `name`, not in the data. {doc}`data-access` makes the same
names appear in SQL, which is one more reason.

The dataframe's `date_col` is not a series. A declared series whose `column` the data does not
have is still recorded, and the build warns.

### Chart

```json
{
  "kind": "Chart", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:chart/curve_today",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "chart", "name": "curve_today" },
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Yield Curve, Latest",
  "location": { "kind": "file", "path": "./_output/curve_today.html",
                "resolved_path": "/Users/x/repos/fed_yield_curve/_output/curve_today.html" },
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

Until the manifest changes, a chart's `dataframe = "x"` becomes `"inputs": ["<pipeline>:x"]` in
the index. The entries of `inputs` are IDs, so they are always fully qualified, whatever was
written in the manifest.

### Notebook and Note

```json
{ "kind": "Notebook", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:notebook/analysis",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "notebook", "name": "analysis" },
  "pipeline": "ftsfr/fed_yield_curve",
  "name": "Initial exploration",
  "location": { "kind": "file", "path": "./_output/analysis.ipynb", "resolved_path": "…" },
  "content_hash": "sha256:…",
  "inputs": ["ftsfr/fed_yield_curve:treasury_rates"] }
```

```json
{ "kind": "Note", "version": "chartbook/v1",
  "id": "ftsfr/fed_yield_curve:note/methodology",
  "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
           "kind": "note", "name": "methodology" },
  "pipeline": "ftsfr/fed_yield_curve",
  "location": { "kind": "file", "path": "./docs_src/methodology.md", "resolved_path": "…" },
  "content_hash": "sha256:…",
  "docs": { "path": "./docs_src/methodology.md", "rendered": "…" } }
```

A notebook's `name` is inferred from its first level-one heading when not declared, as today.

### Model

A trained model that a pipeline declares. The record, its fields and what they are for are in
{doc}`models` ("In the index"). It has the same skeleton as the other asset records — `id`,
`ref`, `pipeline`, `name`, `location`, `content_hash`, `inputs`, `docs`, `built_by` — plus
`metrics`, and `files` when the model is a directory. Its ID is
`ftsfr/fed_yield_curve:model/rate_forecaster`.

A model whose inputs include another pipeline's dataframe also has `pinned_inputs`: for each
such input, its ID as `inputs` writes it, and the content hash `chartbook.lock` pins it at.

```json
"inputs": ["ftsfr/fed_yield_curve:treasury_rates", "ftsfr/rate_forecast:features"],
"pinned_inputs": { "ftsfr/fed_yield_curve:treasury_rates": "sha256:4b1f…" }
```

It is absent when nothing is pinned. An input of the pipeline's own is not in it: a local
asset is live, so there is no pin to name. It says what is pinned, which is what code that
asks for the input is handed; it is not proof of what one training run read. That is a
`Build` record's job. *(Decided by the maintainer 2026-10-12: a field beside `inputs`, which
stays a list of IDs with no version in them.)*

*(2026-10-13, proposed: a `Model` record also has `aliases`, the model's labels as declared,
and `versions`, oldest first: each with `version` (its name), `content_hash`, `made_at`,
`commit`, and where there are any `labels`, `metrics` and `inputs`. They are the versions in
the store of the machine that built the index.)*

*(2026-10-14, built: when the model file's bytes are a version whose snapshot recorded what they
were trained on, the record has `trained_with`, the content hash of each input then, keyed as the
lockfile writes an input (`d`, `rates:treasury`), and `stale_inputs`, the keys whose content now
differs. 2026-10-15: `inputs_now` beside them, each input's content hash now under the same keys
— a local dataframe's as it is in the folder, another pipeline's as `chartbook.lock` pins it —
so that the record alone says which input moved from what to what. A writer cannot derive it:
`inputs` and `pinned_inputs` are keyed by build ID, and the index does not state which
lockfile-style key is which build ID once a declaration is reordered or two upstreams share a
dataframe name.)*

`Model` records are written (step 2), without `built_by`. An entry of a model's `inputs` that
is in another pipeline is written by the ID that pipeline has in this build when it is part of
it (a catalog knows `rates` as `ftsfr/rates`); otherwise by the name `[dependencies]` declares
that pipeline under (`rates:x` becomes `ftsfr/rates:x` when the table has `"ftsfr/rates"`); and
as the manifest states it when nothing knows the pipeline. So in a
catalog's index an input is the `id` of another record in the same file whenever it can be. A model's `location` has
`"kind": "file"` whether its `path` is a file or a directory; `files` is what tells the two
apart.

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
  "code": { "rev": "a1b2c3d4e5f6…", "dirty": false },
  "tools": { "chartbook": "0.2.0", "python": "3.12.4", "polars": "1.9.0" },
  "built_at": "2026-10-11T21:58:09Z",
  "duration_seconds": 412.6,
  "impure": ["wrds_fetch"]
}
```

`asset` is the ID of what was built, so for a chart it is `…:chart/curve_today` and for a model
`…:model/rate_forecaster`.

`code` is the pipeline's git commit when the asset was built, and whether the working tree had
uncommitted changes. It answers "what code made this?" in a form a person can check out. It is a
label for people, not an input to any hash: `recipe_hash` is what the cache uses. *(Added
2026-10-12, proposed. It is what lets a {doc}`model <models>` version say which code trained
it.)*

`input_hash` is the store's lookup key — computable *before* building, which is what lets a cache be
asked and the work skipped. `output_hash` is what downstream consumers compare, so a rebuild
producing identical bytes does not cascade.

**Hashes are transitive.** `input_hash` covers each input's *hash*, not its path or name. Because
those hashes were computed the same way, an asset's identity transitively covers its whole upstream
history — a Merkle DAG, the same structure that makes a git commit hash a statement about an entire
repository. That is what makes recorded lineage *checkable* rather than merely trusted.

`impure` names steps that cannot be reproduced from their inputs. Verifiability reaches back to the
last impure boundary, and a digest of what arrived is recorded there.

### Added for the versioned catalog

*Added 2026-10-16* ({doc}`versioned-catalog`). In a **catalog's** index only, read from the store
of the machine that built it, as a model's versions are:

- A **Pipeline** record's `snapshots`: every snapshot of it in the store, newest first, each with
  `commit`, `made_at`, `name` (the version's folder under `versions/`), `built_by_run`, and
  `rendered`, whether the catalog built that snapshot's site or shows the page that says why.
- For a pipeline shown from the store alone (`location.kind: store`), its `assets` are those its
  newest snapshot's own index lists, and `asset_names` gives each one's name there as plain text.
  *Added 2026-10-17.*
- A **Model** record's `trained_from`: for each input of another pipeline it was trained on, keyed
  as `inputs` is, the snapshot of that pipeline it was trained on: the one the model's pipeline
  was pinned to when the model's bytes were first snapshotted, else the newest holding the
  trained bytes made no later than that.

In any index: a **Pipeline** record's `from_snapshot` (`commit`, `made_at`) when its folder is a
version laid out from the store; and on a pipeline's `dependencies` entry, `key`, the name the
pipeline knows the other by in `[dependencies]`, when it is not the other's ID in the build (the
name its lockfile, its snapshots and `trained_with` use).

## Where the lockfile fits

`chartbook.lock` is the subset of the index that a project commits: its own `Build` records and its
resolved `dependencies`. The index is a build product and need not be committed; the lockfile is
source, because it is what makes a rebuild reproducible and an upstream pin stable.

Both use the same record schemas. There is no second format.

*(Built 2026-10-12, `chartbook.lock` the module. Corrected here as built; the shape was decided
by the maintainer, the details below are proposed.)* What the lockfile holds is not quite the
paragraph above. There are no `Build` records yet. And the part that freezes anything is
missing from it: one record for each asset of each dependency, with its `content_hash`.

```json
{
  "schema": "chartbook/lock/v1",
  "root": "ftsfr/rate_forecast",
  "records": [
    { "kind": "Pipeline", "version": "chartbook/v1", "id": "ftsfr/rate_forecast",
      "dependencies": [
        { "id": "ftsfr/fed_yield_curve", "via": "path",
          "location": { "kind": "path", "path": "../yield_curve" },
          "pinned_hash": "sha256:9ac2…" } ] },
    { "kind": "Dataframe", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:treasury_rates",
      "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
               "kind": "dataframe", "name": "treasury_rates" },
      "pipeline": "ftsfr/fed_yield_curve",
      "location": { "kind": "file", "path": "./_data/treasury_rates.parquet" },
      "content_hash": "sha256:4b1f…", "size_bytes": 2148374 }
  ]
}
```

- **The envelope** is the index's, without `generated_at` and without `generator`, so that
  neither the clock nor a ChartBook upgrade changes a lockfile.
- **An asset record** is the index's record for that asset, cut down to these fields. It fits
  the index's JSON Schema for its kind as it is. One with a `content_hash` is a pin; one
  without was declared by the other pipeline and not built when this was pinned.
- **The `Pipeline` record** is this pipeline's, cut down to `id` and `dependencies`. That is
  below what the index's schema requires of a `Pipeline` (`name`, `location`, `assets`), on
  purpose: those would change the lockfile whenever the manifest changed. The lockfile's own
  envelope schema, `schemas/chartbook/lock/v1.json`, says what is there.
- **IDs use the dependency's key** in `[dependencies]`, which is this pipeline's name for it.
- **`pinned_hash`** is the SHA-256 of a listing with one line per pinned asset of that
  dependency, `<hex of its content hash>`, two spaces, `<its ID>`, newline, sorted by ID.
- **A `location` of kind `path` has `path` and no `value`**: a lockfile holds no absolute path.
- **A `location` of kind `git` has `url`, `rev` if the manifest gives one, and `commit`**: the
  full hash that `rev` meant when the dependency was pinned. `rev` is what was asked for;
  `commit` is what was got. The index copies `commit` onto the pipeline's dependency once it
  is pinned. The `url` never has a user name or a password in it. *(Proposed 2026-10-12, with
  `git` dependencies.)*

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
                 "ftsfr/fed_yield_curve:chart/curve_today"] },

    { "kind": "Dataframe", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:treasury_rates",
      "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
               "kind": "dataframe", "name": "treasury_rates" },
      "pipeline": "ftsfr/fed_yield_curve",
      "name": "Treasury Rates",
      "location": { "kind": "file", "path": "./_data/treasury_rates.parquet" },
      "content_hash": "sha256:4b1f…",
      "date_col": "date",
      "columns": [ { "name": "date", "dtype": "date" },
                   { "name": "DGS10", "dtype": "float64" } ],
      "inputs": [],
      "built_by": "sha256:9ac2…" },

    { "kind": "Series", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:treasury_rates#dgs10",
      "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
               "kind": "dataframe", "name": "treasury_rates", "part": "dgs10" },
      "dataframe": "ftsfr/fed_yield_curve:treasury_rates",
      "column": "DGS10", "declared": true,
      "name": "10-Year Treasury Constant Maturity",
      "units": "Percent", "frequency": "Daily" },

    { "kind": "Chart", "version": "chartbook/v1",
      "id": "ftsfr/fed_yield_curve:chart/curve_today",
      "ref": { "scope": "ftsfr", "pipeline": "fed_yield_curve",
               "kind": "chart", "name": "curve_today" },
      "pipeline": "ftsfr/fed_yield_curve",
      "name": "Yield Curve, Latest",
      "location": { "kind": "file", "path": "./_output/curve_today.html" },
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

The asset records here leave `resolved_path` out of `location`, as a published copy of the index
does. Note the `Series` record for `DGS10` but none for `date`, and that a hypothetical
`DGS2` column would appear as `declared: false` — addressable, undocumented. Note also that the chart's `inputs`
names a *series*, so "what does this chart depend on" is answerable at column granularity even
though the build graph remains coarse.

## What this unblocks

Once the index exists, several things stop being subsystems and become readers of one file:

- An **MCP server** exposing pipelines and assets as resources, and `data.load` as a tool.
- A **Dagster export**, mapping each asset to an `@asset` with `deps`.
- **Faceted search** over the catalog, computed in a browser against a small file.
- A **provenance panel** on every asset page: what built this, from which inputs at which hashes.
  *(Built 2026-10-14: `chartbook/provenance.py`, the index is built first and each page reads its
  record; {doc}`overview`, "6b, as built".)*
- A **build diff** for reviewing what changed, including changes made by automated tooling.
  *(Built 2026-10-14: `chartbook index diff`, `chartbook/indexdiff.py`; {doc}`overview`, "6a, as built".)*

Which is the reason this document comes first.

(index-implementing)=
## What the first implementation does

Built in `chartbook/index.py` and `chartbook/hashing.py`, with the JSON Schemas beside them in
`chartbook/schemas/`. `tests/test_index.py` and `tests/test_hashing.py` are the executable form
of this section.

*(2026-10-14, for the writer, {doc}`writer`: every write-up carries its `content_hash`; a `file`
location its `modified_at`; a dated dataframe its `date_range`; a pipeline its `code_changed_at`.)*

**What is written.** `Catalog`, `Pipeline`, `Dataframe`, `Series`, `Chart`, `Notebook`, `Note`
and `Model` records; `dependencies` on a `Pipeline` that declares some, each with its
`pinned_hash` once pinned; and `pinned_inputs` on a `Model`. Not yet: `Build`
records and `built_by`;
`inputs` on a dataframe or a notebook (the manifest has no field to declare them); `rendered`
in `docs`. A dependency that is a directory, once pinned from a snapshot, has the
snapshot's commit in its `location.commit` and its time in `snapshot` *(2026-10-13, proposed;
a `git` dependency already had `commit`)*. A pipeline's scripts are written as `"scripts": { "build": …, "test": … }`,
sorted by name: all of `[scripts]`, with `[project] build` as `build` *(all of them since
2026-10-13; before the table was read, only `build`)*.

**Where it is written.** The `_build/` layout at the top of this document is a destination, not
today's layout. `chartbook build` *(since 2026-10-13, `chartbook docs`: the command that
renders the site was renamed)* writes two files:

- the **published** index, `index.json` beside the HTML (`docs/index.json`), so that it travels
  with the site and a browser can fetch it. It has no `resolved_path` anywhere, and a pipeline's
  `location` of kind `path` has no `value`, nor does a dependency's: local absolute paths never
  reach a published site;
- the **full** index, `index.json` in the build directory (`_docs/`), with those paths. A plain
  build deletes that directory when it finishes, so the full index outlives the build only with
  `--keep-build-dirs` or in an incremental build, which is the default for a catalog.

`chartbook.index.build_index(manifest)` returns the full index to a program, and
`chartbook.index.published()` turns it into the other.

**Records come from one object.** `chartbook.refs.AssetRef` gives the `id` (`str(ref)`) and the
`ref` (`ref.to_dict()`). A local name from a manifest becomes an ID with
`ref.in_pipeline(pipeline_id)`. In a catalog, the pipeline's ID is the catalog's key for it.

**It is deterministic.** The same manifests and files give the same bytes, apart from
`generated_at`. Records are in a fixed order: the catalog; then pipelines by ID; within one, the
pipeline, then its dataframes, charts, notebooks, notes and models, each by name, and each
dataframe followed by its series in column order. Declared metadata is in sorted key order, so reordering
a `chartbook.toml` does not reorder the index.

**Hashes are cached.** `chartbook.hashing.HashCache` remembers each file's hash against its size
and modification time, in `.chartbook-hash-cache.json` in the build directory. An incremental
build reads only the files that changed. A plain build starts from an empty build directory and
hashes everything, as it does everything else.

**Files that are not built yet.** A declared asset whose file is missing still has a record,
without `content_hash`, `size_bytes`, `row_count` or `columns`. The index describes what the
manifest declares; `chartbook check` is what complains about missing files. (By default
`chartbook docs` stops on a missing file before it gets this far, and with `--no-strict` the
affected pipelines are left out of the site and of the index alike. The case arises through the
Python API, and in a pipeline that has built none of its outputs yet, which `chartbook docs`
renders with each of them shown as not built.)

**A key that is not an address.** An asset whose key in `chartbook.toml` cannot be written in a
reference (it contains a space, say) is left out, with a warning naming it.

**The site does not read the index.** Sphinx still renders from the manifests. Moving the
renderer onto the index is its own change (step 6 in {doc}`overview`), for when the index has
been stable for a while.

### Decided while building it

Each of these was open or unstated when the build began.

**Decided by the maintainer, 2026-10-12:**

1. The hashing rule for a glob or a directory, as written under "Conventions". Which files
   count was decided a second time the same day, when the store was built: a short fixed
   list of operating-system files is left out.
2. Columns whose names are not legal parts have no `Series` record until a table names them.
   Columns should have SQL-compatible names; the readable name is metadata.
3. `generated_at` is when the index last changed; an unchanged index is not rewritten.

**Proposed: implemented, and waiting on the maintainer's yes:**

4. Two files, with the published one free of local paths.
5. The `dtype` vocabulary.
6. `docs.text` for inline write-ups, and no `rendered` for now.
7. An asset record carries all declared metadata, not a fixed list of fields.
8. `policy.required` keeps the manifest's plural keys.
9. Pipelines that a `--no-strict` build skips are left out of the index.

**Proposed with declared dependencies (step 3a), 2026-10-12: implemented, and waiting on the
maintainer's yes:**

10. A `path` dependency's `location` has `path` (as declared) and `value` (absolute, not
    published). The design showed only the `git` form.
11. `dependencies` is absent when there is no `[dependencies]` table, not `[]`. A build of a
    project with no dependencies therefore writes the same index as before.
12. Within one index, a dependency and a cross-pipeline input are written by the ID the
    pipeline has in that index, when it is one of its pipelines; by its key in `[dependencies]`
    otherwise.
13. Credentials are removed from a `git` dependency's `url`.

**Proposed with cross-pipeline references (step 3d), 2026-10-12:**

14. `pinned_inputs` holds only inputs that belong to another pipeline, and is absent when none
    is pinned. (That it is a field beside `inputs` was the maintainer's decision.)
15. A `chartbook.lock` that cannot be read leaves what is pinned out of the index, with a
    warning, and does not stop the build.

**Proposed with `git` dependencies (step 3e), 2026-10-12:**

16. A dependency's `location` of kind `git` gains `commit`, beside `url` and `rev`.
