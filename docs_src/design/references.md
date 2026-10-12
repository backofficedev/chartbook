# Design: references

```{note}
A design document, and the specification for how ChartBook addresses an asset. Every other
design here writes addresses in this grammar, so read it before {doc}`asset-graph`,
{doc}`index-schema`, {doc}`models` or {doc}`data-access`. New to the project? Start with
{doc}`overview`.

Status: **accepted 2026-10-12.** The parser accepts the whole grammar (`chartbook.refs`, in
0.2.0). Only *local* references resolve to a path today. Everything else parses and is refused
as "reserved and not yet supported". See {ref}`refs-status`.
```

## The idea in one picture

Data is the spine of ChartBook. An organization has pipelines, a pipeline has dataframes, and a
dataframe has series (its columns):

```text
ftsfr / fed_yield_curve : treasury_rates # dgs10
scope   pipeline          dataframe        series
```

Everything else a pipeline declares hangs off the pipeline, and says what kind of thing it is:

```text
ftsfr/fed_yield_curve:chart/curve_today
ftsfr/fed_yield_curve:notebook/analysis
ftsfr/fed_yield_curve:note/methodology
ftsfr/fed_yield_curve:model/rate_forecaster@v3
```

That string is a **reference**. It is the one way to name an asset, wherever a name is needed: on
the command line, in Python, in `chartbook.toml`, in the index, in a lockfile and in a URL.

## Examples

| Reference | Means |
|---|---|
| `treasury_rates` | The dataframe `treasury_rates` in the pipeline you are in |
| `chart/curve_today` | The chart `curve_today` in the pipeline you are in |
| `notebook/analysis` | A notebook |
| `note/methodology` | A note |
| `model/rate_forecaster` | A model |
| `treasury_rates#dgs10` | The series `dgs10` of that dataframe |
| `model/rate_forecaster#weights.pt` | One file inside that model |
| `model/rate_forecaster@v3` | Version 3 of that model |
| `model/rate_forecaster@champion` | Whichever version is currently labelled `champion` |
| `fed_yield_curve:treasury_rates` | A dataframe in another pipeline |
| `ftsfr/fed_yield_curve:treasury_rates` | The same, naming the organization too |
| `ftsfr/fed_yield_curve:chart/curve_today` | A chart in another pipeline |
| `charthub.example/ftsfr/fed_yield_curve:treasury_rates` | The same dataframe, from a named registry |

## The grammar

```text
reference   = [ pipeline-id ":" ] asset [ "#" part ] [ "@" rev ]

pipeline-id = [ registry "/" ] [ scope "/" ] pipeline
asset       = [ kind "/" ] name
kind        = "dataframe" | "chart" | "notebook" | "note" | "model"

scope, pipeline, name = one or more of  A-Z a-z 0-9 . _ -
part                  = one or more of  A-Z a-z 0-9 . _ - /
rev                   = one or more of  A-Z a-z 0-9 . _ - :
registry              = a host name, optionally with a port
```

There are four separators, and each asks a different question. Read left to right:

| Separator | Question it answers | Example |
|---|---|---|
| `/` | One level down. Scope, then pipeline. Kind, then name. | `ftsfr/fed_yield_curve`, `chart/curve_today` |
| `:` | "From this pipeline, take…" | `fed_yield_curve:treasury_rates` |
| `#` | "…this part of it." | `treasury_rates#dgs10` |
| `@` | "…at this version." | `model/rate_forecaster@v3` |

Because the separators differ, any piece can be left out and the rest still reads the same way.
That is the whole reason there are four and not one.

### Rules

1. **No colon means local.** A reference without `:` names an asset of the pipeline you are in.
   The current pipeline is found by walking up from the caller to the nearest `chartbook.toml`,
   as git finds a repository.
2. **No kind means dataframe.** `treasury_rates` and `dataframe/treasury_rates` are the same
   reference. The short one is canonical: ChartBook always writes it that way.
3. **Kinds are singular.** `chart/gdp`, never `charts/gdp`. The manifest's *tables* are plural
   (`[charts.gdp]`); the parser says "did you mean `chart`?" when given a plural.
4. **Without a colon, `x/y` is always `kind/name`.** It is never `scope/pipeline`. So
   `ftsfr/fed_yield_curve` is not an asset reference, and the error says to write
   `ftsfr/fed_yield_curve:<asset>`. This keeps the short forms unambiguous.
5. **Each kind has its own names.** `[dataframes.gdp]` and `[charts.gdp]` are two assets, `gdp`
   and `chart/gdp`. Nothing is ambiguous, because the kind is part of the address.
6. **An asset may be named like a kind.** `chart` alone is a dataframe called `chart`.
7. **A registry is only ever the first of exactly three components**, and only if it looks like
   a host: it contains `.` or `:`, or is `localhost`. So `charthub.example/acme/rates` has a
   registry, and `my.group/rates` is a scope with a dot in it. No ID that was valid before
   registries were reserved changes meaning. (This is Docker's rule, narrowed to three
   components.)
8. **Parsing goes right to left**: take off `@rev` at the last `@`, then `#part` at the first
   `#`, then split pipeline from asset at the last `:`. That order is what lets a revision be a
   hash (`@sha256:7f3a…`) and a registry carry a port (`localhost:5000/acme/rates:gdp`).

### A reference to a pipeline is a different thing

Some places name a *pipeline*, not an asset: `data.load(pipeline="ftsfr/fed_yield_curve", …)`,
a key of `[dependencies]`, a key of a catalog's `[pipelines]`. Those take a pipeline ID,
`[registry/][scope/]name`, optionally with `@rev`. They are handled by `chartbook.identity`, and
they also accept a repository URL. The `pipeline-id` half of an asset reference follows the same
rules, minus the URL form.

## Kinds

| Kind | Manifest table | Index record | What `#part` means | Python front door |
|---|---|---|---|---|
| `dataframe` (default) | `[dataframes.x]` | `Dataframe` | A series: one column | `chartbook.data` |
| `chart` | `[charts.x]` | `Chart` | Nothing yet | `chartbook.assets` |
| `notebook` | `[notebooks.x]` | `Notebook` | Nothing yet | `chartbook.assets` |
| `note` | `[notes.x]` | `Note` | Nothing yet | `chartbook.assets` |
| `model` | `[models.x]` (not yet) | `Model` | A file inside the model | `chartbook.models` (not yet) |

**Why dataframe is the default.** Data is what gets passed between pipelines, loaded in
notebooks and written in dependency lists. Charts, notebooks and notes are mostly looked at, not
passed around. The common case gets the short spelling. (kubectl and Hugging Face do the same:
the most common kind needs no prefix.)

**Why names are per kind, not one namespace.** An earlier draft made every asset name unique
within a pipeline, so that `scope/pipeline:name` was enough. The maintainer rejected it: a chart
of GDP and the GDP dataframe are naturally both called `gdp`, charts are not first-class in the
way data is, and one namespace would have forced renames on existing projects.

**Adding a kind** means, in this order: add it to `KINDS` and `KIND_TABLES` in
`chartbook/refs.py`; teach the manifest loader its table; add it to `RESOLVABLE_KINDS` in
`chartbook/resolve.py`; add its record to the {doc}`index schema <index-schema>`; give it a
page in the site; decide what `#part` means for it; and, if code will ask for it often, give it a
front door module. `model` is the first kind to go through this; see {doc}`models`.

## One address, three spellings

The same address is written three ways, depending on who is reading it.

**Text**, for people, the command line, and `chartbook.toml`:

```console
$ chartbook path chart/curve_today
$ chartbook path curve_today --kind chart
```

**Python**, where the kind can be an argument:

```python
from chartbook import assets, data

assets.path("chart/curve_today")
assets.path("curve_today", kind="chart")     # the same call
data.path("treasury_rates")                  # dataframes only
```

**JSON**, in the index and anywhere a program reads an address. Named fields, nothing to parse:

```json
{ "scope": "ftsfr", "pipeline": "fed_yield_curve",
  "kind": "model", "name": "rate_forecaster", "rev": "v3" }
```

`kind` and `name` are always present. The other keys (`registry`, `scope`, `pipeline`, `part`,
`rev`) appear only when set, in the order the address is written.

### What `kind=` means

In Python and on the command line, `kind` says **what you expect**:

- the reference names no kind → it takes this one;
- the reference names the same kind → fine;
- the reference names a different kind → `KindMismatchError`.

```python
assets.path("gdp", kind="chart")          # chart/gdp
assets.path("chart/gdp", kind="chart")    # chart/gdp
assets.path("chart/gdp", kind="note")     # KindMismatchError
assets.path("gdp")                        # the dataframe gdp
```

### Type safety, the small version

Two things, and no more:

1. **Parse once.** `chartbook.refs.parse_asset_ref()` turns text into an `AssetRef`, a frozen
   object with named fields that is checked when it is made. Code inside ChartBook passes that
   object around, never a raw string, and never splits a reference by hand.
2. **Typed front doors.** `chartbook.assets` takes any kind. `chartbook.data` takes dataframes
   only: `data.path("chart/gdp")` raises, and says to use `chartbook.assets`. A later
   `chartbook.models` does the same for models. So a typo cannot hand back a chart's HTML file
   where a parquet file was meant.

```python
from chartbook import assets

ref = assets.parse("ftsfr/fed_yield_curve:model/rate_forecaster@v3")
ref.scope, ref.pipeline, ref.kind, ref.name, ref.rev
# ('ftsfr', 'fed_yield_curve', 'model', 'rate_forecaster', 'v3')

ref.pipeline_id     # 'ftsfr/fed_yield_curve'
ref.local_name      # 'model/rate_forecaster'
ref.table           # 'models'   (the manifest table)
ref.is_local        # False
str(ref)            # the canonical text
ref.to_dict()       # the JSON form
assets.AssetRef.from_dict(ref.to_dict()) == ref     # True
```

## Parts: `#`

A part is something *inside* an asset that deserves its own address. It needs no storage of its
own; the asset already holds it.

- **In a dataframe, a part is a series.** `treasury_rates#dgs10` is one column, so that
  documentation, units and a frequency can attach to it. The key after `#` is the series' key in
  `[dataframes.treasury_rates.series.dgs10]`, which may name a differently-spelled column. See
  {ref}`series-addressing` in the asset graph.
- **In a model, a part is a file.** A model is often a directory (weights, a tokenizer, a config).
  `model/rate_forecaster#weights/best.pt` is one file in it. This is why a part may contain `/`.
- **Charts, notebooks and notes have no parts yet.** The syntax parses; nothing gives it meaning.

`#` was chosen because it maps onto the URL fragment of the asset's page
(`…/treasury_rates.html#dgs10`), and because it cannot appear in a name. In a shell it sometimes
needs quoting (zsh with extended globbing reads `#` specially).

## Versions: `@`

`@` selects a version. Two kinds of version name exist, and both are needed:

- an **exact version**, which never changes meaning: `@v3`, or a content hash `@sha256:7f3a…`;
- a **label that moves**: `@champion` points at whichever version was last given that label.

This is Docker's lesson. A tag (`:latest`) and a digest (`@sha256:…`) are different things, and
conflating them is how "it worked yesterday" happens.

```{admonition} Proposed, not yet settled
:class: warning

What follows is the working proposal for how a `rev` is looked up. It needs the store and the
lockfile, so it is settled when those are built (step 4 in the {doc}`overview`). The decided
part is only: `@` means a version, and exact versions and moving labels both exist.

1. If it contains `:`, it is a **content hash** (`sha256:<hex>`): exactly those bytes.
2. Otherwise, if the asset's pipeline has recorded a **version** or an **alias** by that name
   for that asset (`v3`, `champion`), it is that.
3. Otherwise it is a **git revision of the pipeline** (a commit, tag or branch): the asset as
   that revision of the pipeline built it.

Where version names and aliases are recorded is proposed in {doc}`models`, since models are the
first asset that needs them.
```

## Where references appear

| Place | Example | Notes |
|---|---|---|
| Command line | `chartbook path chart/curve_today` | |
| Python | `assets.path(…)`, `data.path(…)` | Text or an `AssetRef` |
| `chartbook.toml` | `dataframe = "repo_public"` in `[charts.x]` | A local dataframe reference today. Future fields (`inputs`, `trained_on`) hold references in this grammar, with dataframe as the default kind |
| The index | `"id": "ftsfr/fed_yield_curve:chart/curve_today"` plus a `ref` object | IDs are fully qualified and carry no `rev`. See {doc}`index-schema` |
| The lockfile | Keys of pinned assets | Same form as index IDs |
| SQL templates | `{acme/rates:treasury_rates}` in `data.sql()` | Dataframes only. See {doc}`data-access` |
| URLs | `…/treasury_rates.html#dgs10` | Why `#` is the part separator |

(refs-status)=
## What works today

| Form | Example | Today |
|---|---|---|
| Local dataframe | `treasury_rates` | **Resolves** |
| Local chart, notebook, note | `chart/curve_today` | **Resolves** |
| A dataframe through a catalog | `data.load(pipeline="fed_yield_curve", dataframe="treasury_rates")` | **Resolves**, by the older two-argument call |
| Another pipeline's asset | `fed_yield_curve:treasury_rates` | Parses. `UnsupportedReferenceError` |
| A part | `treasury_rates#dgs10` | Parses. `UnsupportedReferenceError` |
| A version | `treasury_rates@a1b2c3d` | Parses. `UnsupportedRevisionError` |
| A registry | `charthub.example/acme/rates:gdp` | Parses. `UnsupportedRegistryError` |
| A model | `model/rate_forecaster` | Parses. `UnsupportedReferenceError` |

All three `Unsupported…` errors are `ValueError`s whose message contains "reserved syntax and not
yet supported". A reference that breaks the grammar raises a plain `ValueError` instead. The
difference matters: "not yet" tells the user the syntax is right.

What unlocks each row is in the {doc}`overview`'s build order.

## Where the code is

| Module | What it does |
|---|---|
| `chartbook/refs.py` | The grammar. `AssetRef`, `parse_asset_ref()`, `KINDS`, `KIND_TABLES`, `KindMismatchError`. Parses and formats; knows nothing about what resolves |
| `chartbook/resolve.py` | The one resolver. `resolve(ref, kind=…)` returns a typed `Location`. `parse_local_ref()` is where reserved forms are refused |
| `chartbook/assets.py` | The general front door: `assets.path()`, `assets.parse()`, `assets.AssetRef` |
| `chartbook/data.py` | The dataframe front door: `data.path()`, `data.load()`, `data.scratch()` |
| `chartbook/identity.py` | Pipeline IDs: `scope/name`, the registry rule, deriving an ID from a git remote |
| `chartbook/cli.py` | `chartbook path REF [--kind KIND]` |
| `tests/test_refs.py` | Every example in this document, as a test |

Rules for whoever extends this:

- **There is one parser.** Do not split a reference with string operations anywhere else. If a
  new form is needed, add it to `refs.py` and to this document in the same change.
- **There is one resolver.** `path()`, `load()` and the CLI all call `resolve()`. Name
  resolution is singular by design ({ref}`not-doing`): two code paths that disagree about a name
  make dependencies unportable.
- **Refuse, do not guess.** A form that cannot be resolved yet raises an `Unsupported…` error.
  It never falls back to something that happens to work.
- **To unlock a form**, remove its refusal in `parse_local_ref()` and add the resolution next to
  `_resolve_local()`. The grammar does not change.

## Why this shape

### What other tools teach

| Tool | Address | Lesson taken |
|---|---|---|
| Docker | `registry/org/image:tag@digest` | Different separators let you leave parts out. A moving label and an exact version are different things; keep both |
| Bazel, Python entry points, git | `//pkg:target`, `module:object`, `commit:path` | A colon means "container, then the thing inside it". That is our colon |
| URLs | `page#section` | `#` means a part of the thing |
| kubectl, Hugging Face | `pod/web`, `datasets/org/name` | Kind goes in front, and the most common kind needs no prefix |
| npm, pip, Hugging Face | `pkg@1.2.3`, `repo@revision` | `@` means a version |
| SQL, Maven | `db.schema.table`, `group:artifact:version` | With one separator you must fill every slot, or depend on a hidden "current schema" setting |

### Alternatives that were turned down

- **One separator for everything** (`ftsfr.fed_yield_curve.treasury_rates.dgs10`). You could not
  tell `pipeline.dataframe` from `dataframe.series`, and `.` is legal inside a name.
- **The kind as a Python argument only** (`data.path("gdp", kind="chart")`). It works in Python
  and nowhere else: not on a command line, not in TOML, not in the index. And it made
  `chartbook.data` hand out charts. The argument stays, as a statement of what you expect.
- **One namespace for all asset names.** See "Kinds" above.
- **A URI scheme** (`chartbook://ftsfr/fed_yield_curve/dataframe/treasury_rates`). Unambiguous,
  and nobody would type it. The short local form is the one people write a hundred times a day.
- **Plural kinds** (`charts/gdp`), to match the manifest tables. Singular reads as a name
  ("the chart gdp") and matches the index's record kinds.

## Open questions

- **How `@rev` is looked up.** Proposed above; settled with the store.
- **Parts of charts, notebooks and notes.** A notebook cell? A chart's series? Nothing has asked
  for one yet.
- **Whether `chartbook.toml` tables may themselves be keyed by a reference** (for example
  documenting a series of another pipeline's dataframe). Not needed so far.
