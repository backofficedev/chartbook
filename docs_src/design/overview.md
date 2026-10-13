# Design: start here

```{note}
The entry point to the design documents. It is written for someone, or some agent, who has
never seen this project and has to continue building it. It says what ChartBook is, the words
it uses, what is built, what to build next and in what order, and where every decision is
written down.

Last revised 2026-10-12, after version 0.2.0, the index, declared models, and all five parts
of step 3: declared dependencies, the store, pinning, references to another pipeline's
assets, and `git` dependencies. **Step 3 is built. The next step is 4**, running and build
records.
```

## What ChartBook is

ChartBook is a Python command-line tool and library. A data project describes what it produces
in one file, `chartbook.toml`, and ChartBook turns that description into a documentation
website, a way to load the data by name, and (the work ahead) a record of what depends on what.

Three sentences hold most of the design:

1. **The manifest is the contract.** `chartbook.toml` says what exists and where. ChartBook
   reads it; it never requires your code to call ChartBook.
2. **ChartBook publishes; it never orchestrates.** It does not schedule, retry or run your
   analysis. Your own tool (`doit`, `make`, a shell script) does that.
3. **Everything works for one person on one laptop with no server.** Sharing is the same files,
   in git or on a shared drive.

It is experimental and pre-1.0. Breaking changes are allowed, with a changelog entry that says
what to do instead ({doc}`../reference/stability`).

## The picture

```text
organization (scope)        ftsfr
  pipeline                  ftsfr/fed_yield_curve          one repository, one chartbook.toml
    dataframe               …:treasury_rates               a parquet file (later: a table)
      series                …:treasury_rates#dgs10         one column of it
    chart                   …:chart/curve_today            an HTML file
    notebook                …:notebook/analysis
    note                    …:note/methodology             a page of prose
    model                   …:model/rate_forecaster        a trained model

catalog                     many pipelines, browsed and searched as one site
```

**Data is the spine.** Organization, pipeline, dataframe, series: that chain is what people load,
depend on and cite. Charts, notebooks, notes and models hang off a pipeline and say what kind
they are. This was the maintainer's explicit correction to an earlier draft that treated all
assets alike.

## Words

| Word | Means |
|---|---|
| **pipeline** | One project with a `chartbook.toml`: code that produces assets. Identified as `scope/name`, e.g. `ftsfr/fed_yield_curve` |
| **scope** | The organization or owner half of a pipeline's ID. Taken from the git remote's owner |
| **catalog** | A `chartbook.toml` that lists pipelines and builds one site over all of them. It declares no assets of its own |
| **manifest** | The `chartbook.toml` file |
| **asset** | Something a pipeline declares: a dataframe, chart, notebook, note or model |
| **kind** | Which of those five an asset is. Written singular: `chart` |
| **dataframe** | A table of data. Today always a parquet file (or a glob of them) |
| **series** | One column of a dataframe, given its own address and documentation |
| **part** | Something inside an asset, addressed with `#`. A series is a dataframe's part; a file is a model's part |
| **reference** | The address of an asset: `[registry/][scope/]pipeline:[kind/]name[#part][@rev]`. Specified in {doc}`references` |
| **local reference** | A reference with no `pipeline:` in front. It means "in the pipeline I am in" |
| **front door** | A Python module that hands out one kind of asset: `chartbook.data` for dataframes, `chartbook.models` for models, `chartbook.assets` for any kind |
| **location** | Where an asset physically is. A file today; a database table later ({doc}`data-access`) |
| **index** | One JSON file describing everything a catalog contains. A build product. Planned ({doc}`index-schema`) |
| **record** | One entry in the index. Each has a `kind` (`Dataframe`, `Chart`, …) and a `version` |
| **store** | A local folder of files named by their hash, used for caching and pinning. One per user, shared by their projects ({doc}`asset-graph`) |
| **object** | One asset in the store: a directory named by the asset's content hash, holding its files under their own names |
| **dependency** | Another pipeline that this one reads from, declared in `[dependencies]`: a name, and where to find it (`path` or `git`) |
| **resolution chain** | The order in which a pipeline's location is looked for: `[dependencies]`, then the catalog. One function, `chartbook.resolve.locate_pipeline` |
| **lockfile** | `chartbook.lock`: the exact bytes of the upstream assets a project uses, by content hash. JSON in the index's format. Committed |
| **pin** | To freeze which version of an upstream asset a project reads. Also the record of it: an asset's entry in the lockfile, with a `content_hash`. `chartbook pin` makes pins and never moves one; `chartbook update` moves them |
| **build record** | A written description of how one asset was made: inputs, code, tools, output hash. Planned |
| **source / backend** | A named database connection in a manifest / the engine behind it. Planned ({doc}`data-access`) |
| **scratch** | `_data/_scratch/` inside a pipeline: throwaway files that are not assets |

Three different things are called "kind", and they do not mix:

- an **asset kind**, lowercase, in a reference: `chart`;
- a **record kind**, capitalized, in the index: `Chart`. It is the asset kind capitalized, plus
  the non-asset records (`Catalog`, `Pipeline`, `Series`, `Build`);
- a **location kind**, inside a record's `location`: `file`, `table` or `query`.

## Rules that settle arguments

These come from the maintainer and from {doc}`asset-graph`. When a design question is close,
they decide it.

1. **Scale to zero.** No capability may require a running service to be useful to one person on
   one machine.
2. **A convenience is never a requirement.** `data.path()` is nice. A script that hardcodes the
   same path, in any language, must keep working.
3. **No orchestration.** No scheduler, retries, backfills, run history or run UI. Export the
   graph to a tool that has them.
4. **No plugin system before a second implementation exists.** Leave one internal seam. Write the
   second implementation. Then extract the interface.
5. **Some things are singular.** Hash computation, name resolution and the index schema each have
   exactly one implementation, on purpose.
6. **No features for machines alone.** Anything built for programs must fall out of something
   that already helps a person.
7. **Refuse, do not guess.** Syntax that is reserved for later raises "not yet supported". It
   never quietly does something else.
8. **Plain files stay plain.** A declared `path` is the real location of the real file. The store
   links to it; it never moves it.

The full list of things that will be declined is {ref}`"Not doing" <not-doing>` in the asset
graph. Read it before proposing a feature.

## Versions

Decided by the maintainer, 2026-10-12.

- **The asset graph is one change, not a release per step.** The steps under "What to build
  next" do not each get a minor version. Do not bump the version in a pull request.
- **0.2.0 is the working state** while that change is under way. What lands goes under
  "Unreleased" in the changelog.
- **When all of it is finished it is wrapped up, probably as 0.3.0.** When, and whether that is
  the number, is the maintainer's call.
- **1.0 is a long way off**, on purpose: there is room for many more changes before any promise
  of stability. Nothing here should be planned as "the last thing before 1.0".

## The documents, and the order to read them

| Order | Document | What it settles | State |
|---|---|---|---|
| 1 | This page | The map | |
| 2 | {doc}`toml-format-v2` | The manifest: tables, fields, pipeline IDs, catalogs, policy | Built |
| 3 | {doc}`references` | How an asset is addressed | Parser built. Local references resolve live; another pipeline's resolve pinned |
| 4 | {doc}`asset-graph` | Dependencies, pinning, the store, build records, what ChartBook will not do | Step 3 built: declared dependencies, the store, pinning, cross-pipeline references, `git` dependencies. Step 4a built: `[scripts]` and `chartbook run`. **Next to build**: step 4b, build records and skipping what is current |
| 5 | {doc}`index-schema` | The index file, record by record | First implementation built |
| 6 | {doc}`models` | Models as assets | First slice built: declared models |
| 7 | {doc}`data-access` | Dataframes that live in a database | Designed, not built |

For how the existing build works, read {doc}`../guide/how-the-build-works`. For every command
and field, {doc}`../reference/cli` and {doc}`../reference/configuration`.

## What is built

As of 0.2.0, plus the index, declared models, declared dependencies, the store, pinning,
named scripts and `chartbook run`, which came after it.

| Capability | Where | Notes |
|---|---|---|
| Manifest format v2, pipeline IDs, catalogs, policy | `manifest.py`, `identity.py` | `repo_url` defaults to the git remote |
| The documentation site | `build_docs.py`, `markdown_generator.py`, `docs_src_pipeline/`, `docs_src_catalog/` | Two stages: write Markdown into `_docs/`, then run Sphinx |
| Incremental builds and `--watch` | `incremental.py` | A state file of file sizes and times. No server. Catalog builds are incremental by default |
| `chartbook check`, the CI gate | `check.py` | Required fields, broken paths, expiring licenses. `--skip-outputs` for CI that does not build data |
| The reference grammar | `refs.py` | All of it parses |
| Resolving local references | `resolve.py`, `assets.py`, `data.py`, `chartbook path` | One resolver, typed locations. Live: the declared `path` |
| `git` dependencies | `gitcache.py`, `lock.py` | Cloned into `~/.chartbook/git/`, checked out at a commit, then pinned like a directory. Only what the repository commits, until `chartbook run` builds it in a working copy |
| Named scripts and `chartbook run` | `manifest.py` (`read_scripts`), `run.py`, `gitcache.py` (`work_copy`) | `[scripts]`, with `build` reserved. Runs a script in the pipelines this one depends on, in order, then in it. Pins what has no pin before a build; never moves a pin. Skips nothing yet |
| Resolving another pipeline's assets | `resolve.py` (`_resolve_pinned`), `lock.py`, `store.py` | `pipeline:name`, for a declared dependency, resolves through `chartbook.lock` to the pinned copy in the store. Every kind, every front door, and `data.load("pipeline:name")` |
| The index, `index.json` | `index.py`, `hashing.py`, `schemas/` | Written by every build, beside the HTML. One hash rule; hashes cached in the build directory |
| Series tables | `manifest.py` (`validate_series`) | `[dataframes.x.series.y]` documents a column. In the index; not on pages yet |
| Models | `models.py`, `manifest.py` (`validate_models`), `markdown_generator.py` (`generate_model_docs`) | `[models.x]`, `chartbook.models.path()`, a page and an index record per model. No versions yet |
| Declared dependencies | `manifest.py` (`validate_dependencies`), `resolve.py` (`locate_pipeline`), `check.py` (`check_dependencies`) | `[dependencies]`, with `path` or `git`. One resolution chain. In the index, and checked |
| The store | `store.py`, `config.py` (`get_store_path`), `chartbook store verify` | Objects named by content hash, behind `has`, `get`, `put`, `delete`. Four kinds of link |
| Pinning | `lock.py`, `chartbook pin`, `chartbook update`, `chartbook store gc` | `chartbook.lock`: a content hash for every asset of every dependency. `pin` never moves a pin; `update` does |
| Loading a dataframe through a catalog | `data.py` | `data.load(pipeline=…, dataframe=…)`. The older, two-argument form. It enters the resolution chain at the catalog and does not read `[dependencies]` |
| Scratch directory | `data.scratch()` | `<pipeline>/_data/_scratch/` |
| Freshness lines on pages | `markdown_generator.py`, `chartbook-freshness.js` | "Data updated 2 days ago", computed in the browser |
| Data glimpses | `create_data_glimpses.py` | Reads the manifest, not `dodo.py` |
| Scaffolding | `scaffold.py`, `chartbook init --git/--github` | Renders the cookiecutter template |
| Plotting helpers and backends | `plotting/` | The one real plugin system. See {doc}`../guide/plotting-backends` |
| Reserved for later, and refused | `refs.py`, `resolve.py`, `identity.py`, `cli.py` | `#part`, `@rev`, registry prefixes, `chartbook push` |

Not built: build records, skipping a pipeline that is current, `--frozen`, the command
rename, model versions, `[sources]` and SQL access, any export, and anything that *reads* the
index.

## What to build next, in order

```{admonition} Who decided what
:class: note

The maintainer has decided the destination (everything in {doc}`asset-graph`,
{doc}`index-schema`, {doc}`models` and {doc}`data-access`) and that the index comes first. The
order of the steps after the first, and their boundaries, are the recommendation of the last
person to work on this. Change them if a better cut appears, and say so here.
```

Each step ends with something a user can run. Do them one at a time, each as its own branch and
pull request.

### Step 1. The index — built

`chartbook build` also writes one JSON file that describes everything: `index.json`, beside the
HTML. It has `Catalog`, `Pipeline`, `Dataframe`, `Series`, `Chart`, `Notebook` and `Note`
records, each asset with a fully qualified `id`, a structured `ref` and a content hash. The code
is `chartbook/index.py` and `chartbook/hashing.py`; the JSON Schemas are in `chartbook/schemas/`;
the loader reads `[dataframes.x.series.y]`.

{doc}`index-schema` is the specification, and its last section, "What the first implementation
does", says exactly what is written and what is not. Nine things were settled while building
it. The maintainer has decided three; six are listed there as *proposed*, still to confirm.

Left for later steps, on purpose: `Build` records, `dependencies`, `Model` records, and
rendering the site *from* the index.

### Step 2. Declared models — built

A pipeline can declare a trained model in `[models.x]`, ask for its path
(`chartbook path model/x`, `chartbook.models.path("x")`), check it, and get a page and a `Model`
record in the index. This is slice M1 of {doc}`models`; its section "What is built" lists every
file involved and eight things that were settled while building it, all *proposed*.

Left for later steps, on purpose: versions and labels (`@v3`, `@champion`), parts
(`model/x#file`), and anything that crosses a pipeline boundary.

### Step 3. Dependencies, the lockfile and the store

**Goal:** `data.path("fed_yield_curve:treasury_rates")` works, and returns a frozen copy.
*(Met 2026-10-12, with 3d.)*

```{admonition} The case this step is for
:class: important

**A model in one pipeline, trained on data from another, reproducibly.** The maintainer was
explicit: cross-pipeline training data is what ChartBook is going for, not a later refinement,
and it is one reason all of this is being built as one change with no release in between.

Today a model can *state* that it was trained on another pipeline's dataframe ({doc}`models`).
Nothing fetches that data, pins a version of it, or records which bytes were used. This step
makes it real. Judge every design choice in it against that case first, and against "a chart of
another pipeline's data" second.
```

It is the largest step, and the first where the design has never met code. Build it as five
pull requests, in this order. Each leaves `main` working.

| | Pull request | What a user gets | What it does not do |
|---|---|---|---|
| **3a** *(built)* | **Declared dependencies.** `[dependencies]` in the manifest (`path` first). One resolution chain in one function: an explicit location in `[dependencies]`, then the local catalog, then (reserved) registries, then an error that lists candidates. `dependencies` on the `Pipeline` record. `check` verifies each one resolves | A pipeline says what it depends on, and `check` says whether that can be found. A cross-pipeline `trained_on` or chart input must name a declared dependency (a warning first, an error once 3d lands) | Nothing is fetched, copied or pinned |
| **3b** *(built)* | **The store.** Objects named by content hash, behind four operations (has, get, put, delete). Links, not copies: reflink, hardlink, symlink, copy, in that order. `chartbook store verify` | Nothing visible. This is the piece everything after sits on, and it can be tested alone | Nothing uses it yet |
| **3c** *(built)* | **Pinning.** `chartbook.lock`, written in the index's record schemas. `chartbook pin` snapshots each dependency's declared assets into the store and records their hashes. `chartbook update` moves pins forward. `chartbook store gc`, with the lockfile as its roots | A project can freeze what it depends on, and see in a diff when that changes | References still do not resolve across pipelines |
| **3d** *(built)* | **Cross-pipeline references resolve.** `assets.path("pipeline:asset")`, `data.path`, `chartbook path` and `data.load("pipeline:asset")` resolve through the lockfile into the store, never to the upstream's working directory. Loading from an undeclared pipeline fails and says what to add. A model's cross-pipeline `trained_on` is recorded by pinned hash. A second example pipeline, `examples/rate_forecast`, whose model is trained on `yield_curve`'s data | **The payoff.** The case in the box above works end to end | `git` dependencies |
| **3e** *(built)* | **`git` dependencies.** `{ git = "…", rev = "…" }`: fetch at a revision into a cache, then as for `path` | A dependency that is not on your disk | — |

**Done when:** `examples/rate_forecast` builds from a clean clone with no catalog configured, its
model's index record names the exact bytes of the dataframe it was trained on, and editing the
upstream's data does not change what the downstream reads until `chartbook update`.

**Settled with the maintainer, 2026-10-12:** where the store lives on disk and its layout;
how it links to a file; the lockfile's shape; what `pin` does when an upstream has not been
built; and which hidden files a directory's hash skips. **Still to settle:** how a `git`
dependency is fetched and where its checkout is kept (before 3e), and whether
`data.load("pipeline:asset")` arrives in 3d. All seven are under "Answers to the open
questions" below.

#### 3a, as built

*Added 2026-10-12.* What a user can do: declare `[dependencies]`, run `chartbook check`, and be
told whether each one is there and whether it declares the training data a model names.

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }

[models.rate_forecaster]
path = "./_models/rate_forecaster.joblib"
trained_on = ["fed_yield_curve:treasury_rates"]
```

| What | Where |
|---|---|
| The `[dependencies]` table, validated when the manifest loads | `chartbook/manifest.py`, `validate_dependencies()` |
| The resolution chain, and the one place a pipeline's name becomes a location | `chartbook/resolve.py`: `locate_pipeline()`, `PipelineLocation`, `known_as()` |
| Matching a name against a set of pipeline IDs, without failing on a miss | `chartbook/identity.py`, `match_pipeline_ref()` |
| `dependencies` on a `Pipeline` record, and inputs written by a dependency's name | `chartbook/index.py`, `schemas/chartbook/v1/Pipeline.json` |
| `check`: a dependency that is not there; training data it does not declare; one ID for two directories in a catalog | `chartbook/check.py`: `check_dependencies()`, `check_model_lineage()` |
| The warning for a `trained_on` that names an undeclared pipeline | `chartbook/manifest.py`, `validate_models()` |
| The tests | `tests/test_dependencies.py` |

Everything that used to look a pipeline up by name now calls `locate_pipeline()`: the catalog
lookups behind `data.load(pipeline=…)`, the index, the model page and `check`.

**Not done in 3a, on purpose.** Nothing is fetched, copied or pinned. `pipeline:asset` is still
refused wherever a path is asked for: it must resolve to a frozen copy, never to the other
pipeline's working directory, so making it resolve early would change what the same text means
later. No example pipeline declares a dependency yet; `examples/rate_forecast` arrives in 3d.
Pages do not list a pipeline's dependencies.

**Proposed: implemented in 3a, and waiting on the maintainer's yes.** Each was open or unstated
in the design.

1. **A `git` dependency may be declared now**, though nothing fetches it until 3e. It is
   validated, recorded in the index, and `check` warns that it was not looked at. (The table
   above says "`path` first". Refusing `git` until 3e was the other option; the design's own
   example manifest would not have loaded.)
2. **`rev` is optional on a `git` dependency.** With none, the revision is whatever the
   repository's default branch has when it is pinned, as a `path` is whatever the directory
   holds. What that fetch does is 3e's to settle.
3. **`{ rev = "…" }` with no `git` is refused**, with a message. {doc}`toml-format-v2` shows
   that form, which needs `[resolve] default_host` to work out the URL. Not built.
4. **The key of `[dependencies]` is a plain pipeline ID.** No URL, and no `@rev`: a revision
   goes in the entry. {doc}`references` said such a key may carry both.
5. **A reference may leave the scope off** when exactly one dependency has that name, as a
   catalog lookup allows. A name that fits two dependencies is an error, and is not passed on
   to the catalog to be guessed at.
6. **A `trained_on` that names an undeclared pipeline warns when the manifest loads**, so
   `build` shows it as well as `check`, and `check` does not fail on it. It becomes an error in
   3d.
7. **`check` needs a `path` dependency to be on disk**, with `--skip-outputs` too. A dependency
   is not something this pipeline builds. A project whose CI checks out one repository will
   want `git` dependencies, which is 3e.
8. **Within one build, a pipeline goes by the build's name for it.** If a pipeline calls
   `../fed_yield_curve` `yield_curve` and the catalog calls that directory
   `ftsfr/fed_yield_curve`, the catalog's index says `ftsfr/fed_yield_curve` in both
   `dependencies` and `inputs`. Alone, the pipeline's index says `yield_curve`.
9. **One ID for two directories is reported by `check` on a catalog**, when a dependency's key
   is a catalog pipeline's ID and its `path` is a different directory. Inside one pipeline the
   case cannot arise (a TOML table has each key once), and two pipelines of a catalog may
   point one name at different places without it being reported.
10. **A catalog with a `[dependencies]` table does not load.** It reads from no pipeline.
11. **An unknown key in an entry is an error**, not a warning, so that a later key (`branch`,
    `tag`) is never silently ignored by an older ChartBook.
12. The index's shape for a dependency: see {doc}`index-schema`, "Decided while building it",
    items 10 to 13.

**One row of the table above cannot be met as written.** "A cross-pipeline `trained_on` or
chart input must name a declared dependency." A chart has no way to name another pipeline's
dataframe: its `dataframe` field must be one this pipeline declares, or the manifest does not
load. So only `trained_on` is covered. A chart of another pipeline's data needs the chart's
`inputs` field ({doc}`index-schema`) or a looser `dataframe`, and a page that can render it;
that is best decided with 3d.

#### 3b, as built

*Added 2026-10-12.* Nothing a user sees, apart from one command. The store is the piece that
pinning sits on, and it is tested alone.

```python
from chartbook.store import Store

store = Store("~/.chartbook/store")
stored = store.put("_data/treasury_rates.parquet")   # the file stays where it is
stored.content_hash                                  # "sha256:7f3a9c…", the object's name
store.get(stored.content_hash)                       # …/objects/sha256/7f/3a9c…/
store.has(stored.content_hash), store.delete(stored.content_hash)
```

```console
$ chartbook store verify
/Users/x/.chartbook/store: OK (14 object(s))
```

| What | Where |
|---|---|
| The store: `has`, `get`, `put`, `delete`, and `verify` | `chartbook/store.py`, `Store` |
| The four kinds of link, and the one place they are tried in order | `chartbook/store.py`: `LINKS`, `_link()`, `_reflink()` |
| Where the store is: `CHARTBOOK_STORE`, then `[store] path` in `settings.toml`, then `~/.chartbook/store/` | `chartbook/config.py`, `get_store_path()` |
| `chartbook store verify` | `chartbook/cli.py` |
| Which files make up an asset, for hashing and storing alike; the files that never do | `chartbook/hashing.py`: `find_files()`, `is_ignored()` |
| The tests | `tests/test_store.py`, `tests/test_hashing.py` |

**Not done in 3b, on purpose.** Nothing puts anything in the store: no `pin`, no lockfile, no
`gc`. `builds/`, the index from a build's inputs to its output, is a name the layout keeps
free and nothing writes to. The link kinds cannot be chosen in `settings.toml`; a caller in
code can pass its own list.

**Proposed: implemented in 3b, and waiting on the maintainer's yes.**

1. **An object is hashed after it is stored, not before.** `put` links or copies the file into
   the store first and then hashes what the store holds. So an object's name is right even if
   the original was being rewritten while it was stored.
2. **A clone or a copy is made read-only in the store. A hard link is not**, because it cannot
   be: see the first correction below.
3. **`put` takes the kinds of link to try.** The default is the designed four. A caller that
   must have a frozen object passes `links=("reflink", "copy")`, and what comes back says
   whether it is frozen (`stored.frozen`). So 3c can tell a user, when it pins, how many of the
   pins are links to files that can still change. Nothing chooses for the user.
4. **The same bytes under another file name are one object with both names in it.** A file's
   hash does not include its name, and a path into the store has to end in the right one.
5. **An empty directory is not stored.** There is nothing to pin, and its hash would be the
   hash of an empty file.
6. **The store says which layout it has**, in `store.json`. A store laid out by a later
   ChartBook is refused, not misread.
7. **A store comes into being when something is first put in it**, never by being looked at.
   `chartbook store verify` on a machine with no store says "OK (0 object(s))" and creates
   nothing.
8. **An object is built in `tmp/` and moved into place with one rename**, so another process
   sees all of it or none of it, and two that store the same content at once end with one
   object.
9. **`verify` exits 1 if any object has changed**, and prints `hash: what is wrong`. It
   ignores the same operating-system files that hashing ignores, so Finder looking inside the
   store does no harm.
10. **A symlink in the store points at the real file**, with any links on the way resolved, so
    the store never holds a link to a link.

**Where the design was wrong about what a disk does.** Both are in {doc}`asset-graph`, "Links,
not copies", and are marked there.

1. *"Hardlink: make the store side read-only."* A hard link has no store side. Both names are
   one file with one set of permissions, so making it read-only makes the upstream's own file
   read-only, and its next build fails on a file it wrote itself. That would break rule 2,
   "a pipeline that hardcodes its paths keeps working". So a hard-linked object is left
   writable, and `verify` is what protects it.
2. *"The copy rung will be exercised: a shared network mount is a different filesystem, so
   neither reflinks nor hardlinks reach it."* A symlink comes before copy in the ladder, and a
   symlink does reach across filesystems. So with the store on one disk and the data on
   another, an object is a symlink, never a copy. Copy is reached only where symlinks are not
   allowed, which in practice is Windows without the privilege.

#### 3c, as built

*Added 2026-10-12.* What a user can do: freeze what a pipeline depends on, see in a diff when
that changes, and clear out of the store what nothing needs any more.

```console
$ chartbook pin
ftsfr/fed_yield_curve: 3 pinned, 1 not built
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
Wrote chartbook.lock.

$ chartbook update fed_yield_curve
ftsfr/fed_yield_curve: 1 moved, 2 already pinned, 1 not built
  ftsfr/fed_yield_curve:treasury_rates
    sha256:4b1f… -> sha256:99ab…
Wrote chartbook.lock.
```

| What | Where |
|---|---|
| Reading and writing `chartbook.lock`; `pin()` and `update()`; what `gc` keeps | `chartbook/lock.py` |
| The lockfile's JSON Schema | `chartbook/schemas/chartbook/lock/v1.json` |
| Which lockfiles name the store's objects | `chartbook/store.py`: `add_root()`, `roots()`, `remove_root()` |
| Every asset a pipeline declares with a `path`, from its raw manifest | `chartbook/resolve.py`, `declared_files()` |
| `chartbook pin`, `chartbook update`, `chartbook store gc` | `chartbook/cli.py` |
| The tests | `tests/test_lock.py` |

**Decided by the maintainer, 2026-10-12, while it was being built:**

1. **`pin` never moves a pin; `update` does.** A second `pin` pins what has no pin yet and
   leaves the rest exactly where it is, saying what has changed upstream.
2. **`chartbook store gc` keeps what registered lockfiles name, and asks before removing
   anything.** Each `pin` and `update` notes its lockfile in the store. A lockfile that cannot
   be found still keeps its pins unless `--forget-missing` is given. `--dry-run` only lists;
   `--yes` does not ask.

**Not done in 3c, on purpose.** Nothing reads the lockfile to resolve a reference:
`chartbook path fed_yield_curve:treasury_rates` is still refused, and the index does not carry
`pinned_hash`. Both are 3d. `chartbook check` says nothing about a lockfile that is out of
date; refusing to run with one is `--frozen`, in step 4. A `git` dependency is listed and not
pinned.

**Proposed: implemented in 3c, and waiting on the maintainer's yes.**

1. **The lockfile leaves out `generator` as well as `generated_at`.** The decision was "no
   timestamp". Without the ChartBook version too, upgrading ChartBook does not rewrite every
   lockfile.
2. **The lockfile is keyed by the dependency's key in `[dependencies]`**, the pipeline's own
   name for it, not by what the other pipeline calls itself.
3. **Every kind of asset is pinned**: dataframes, charts, notebooks, notes and models. The
   plan says "declared assets", and with links it costs nothing.
4. **A dependency's `pinned_hash` is the hash of a listing of its pins**, one line per pinned
   asset, in the form a directory is hashed in. One line of a diff then says a dependency
   moved.
5. **`pin` puts back what the store has lost**, when the other pipeline still has the same
   bytes. That is what makes it the command to run after cloning. When the bytes are gone the
   asset is reported as *lost* and `pin` exits 1; the pin is not moved to what is there now.
6. **`pin` hashes what is already pinned, to say what has changed upstream.** It reads every
   byte of every pinned asset on each run. A remembered hash would make that cheap, and is
   not built.
7. **An asset the other pipeline stops declaring keeps its pin under `pin`, and is dropped by
   `update`.** One it declares and no longer has on disk keeps its pin under both.
   *(2026-10-13, proposed: one exception, for a `git` dependency that an update moves to
   another commit. See "4a, as built", number 17.)*
8. **A pinned dependency whose directory has gone is fine for `pin`.** The pins are in the
   store, which is the point. For `update` it is an error.
9. **No lockfile is made for a pipeline with no dependencies.** Removing the last one leaves
   a lockfile with nothing in it.
10. **`pin` reads only the pipeline's ID and its `[dependencies]`**, so something wrong
    elsewhere in the manifest does not stop it.
11. **`pin` says when what it stored is held as links** to the other pipeline's files, and
    points at `chartbook store verify`.
12. **`gc` leaves alone anything stored in the last hour.** A pin puts files in the store
    before it writes the lockfile that names them, so a `gc` running at the same moment would
    otherwise remove them.
13. **`gc` reads each lockfile as it is now.** After checking out an older commit, the pins of
    the commit you left are named by nothing until you pin again.
14. **`gc` removes nothing if a lockfile, or one of the store's notes, cannot be read.**

**Where the design was wrong, or assumed something that does not exist yet.**

1. *"`chartbook.lock` is … its own `Build` records and its resolved `dependencies`"*
   ({doc}`index-schema`). It leaves out the part that freezes anything: the other pipelines'
   asset records, with their hashes. Those are what the lockfile mostly holds.
2. *"Both use the same record schemas."* True of the asset records, which fit the index's
   schema for their kind as they are. The lockfile's `Pipeline` record has only `id` and
   `dependencies`, and the index's schema for a `Pipeline` also requires `name`, `location`
   and `assets`, which would change the lockfile every time the manifest did. The lockfile
   has an envelope schema of its own that says so.
3. *"`chartbook run` pins anything not yet pinned, so neither verb is needed to get started."*
   There is no `run` until step 4, so until then `pin` is how to get started.
4. *"`chartbook update` … and rebuild what that invalidates."* That also needs `run`. `update`
   moves pins and rebuilds nothing.
5. *"An object is reachable if some lockfile references it."* With one store for all of a
   user's projects, the store has to be told which lockfiles there are. It keeps a note of
   each one that pins into it.

*("Done when" is met, 2026-10-12, for `path` dependencies.
`tests/test_integration.py::test_rate_forecast_example` is that sentence as a test: it builds
the example with an empty store and no catalog, reads the model's `pinned_inputs` from
`index.json` and checks it against the bytes, rewrites the upstream's parquet file in place
with pandas, and checks that the downstream still reads the old bytes until
`chartbook update`. "From a clean clone" is true of the code; the example's upstream pulls its
data from the network.)*

#### 3d, as built

*Added 2026-10-12.* The payoff. A pipeline reads another pipeline's asset by name and gets
the pinned copy.

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates")     # theirs, as pinned
mine = data.load("merged_rates")                        # mine, as it is now
```

```console
$ chartbook path fed_yield_curve:treasury_rates
/Users/x/.chartbook/store/objects/sha256/4b/1f…/treasury_rates.parquet
```

| What | Where |
|---|---|
| A reference to another pipeline's asset: `[dependencies]`, then `chartbook.lock`, then the store | `chartbook/resolve.py`, `_resolve_pinned()` |
| The two errors that say what to add or run | `chartbook/errors.py`: `DependencyNotDeclaredError`, `AssetNotPinnedError` |
| `data.load()` with one reference | `chartbook/data.py` |
| Pins are a clone or a copy; an object that was a link is replaced | `chartbook/lock.py` (`PIN_LINKS`), `chartbook/store.py` (`_is_frozen`) |
| `pinned_inputs` on a `Model` record; `pinned_hash` on a dependency | `chartbook/index.py`, `schemas/chartbook/v1/Model.json` |
| An undeclared pipeline in `trained_on` is an error | `chartbook/manifest.py`, `validate_models()` |
| The second example | `examples/rate_forecast` |
| The tests | `tests/test_pinned_refs.py`, `tests/test_integration.py` |

**Decided by the maintainer, 2026-10-12, while it was being built:**

1. **A pin is frozen.** `pin` and `update` ask the store for a reflink, then a copy, and
   never a hard link or a symlink. The store keeps all four kinds for what is cheap to make
   again. This settles the conflict set out under answer 2 below: the "Done when" line holds
   on every disk, and a pin on a disk without reflinks costs the file's size.
2. **`data.load()` takes one reference**, beside the two-argument form, which still means
   "through a catalog".
3. **A model's record names the bytes in a field beside `inputs`**, `pinned_inputs`: each
   cross-pipeline input's ID and the hash the lockfile pins it at. `inputs` stays a list of
   IDs.
4. **The example's lockfile is git-ignored**, because its upstream pulls live data. Its build
   runs `chartbook pin`. Its README says a real project commits the file.

**Not done in 3d, on purpose.** A part (`…#dgs10`), a version (`…@v3`) and a registry are
still refused. A `git` dependency's assets cannot be read; that is 3e. `chartbook check` does
not look at the lockfile or the store, since a CI runner has no store. A chart still cannot be
made from another pipeline's dataframe. Pages do not show what is pinned.

**Proposed: implemented in 3d, and waiting on the maintainer's yes.**

1. **What path comes back.** For an asset that is a file, the file in the object, under its
   own name. For a glob, the object's directory with the glob's own tail
   (`…/**/*.parquet`). For a directory, the object's directory.
2. **The lockfile lists the files of a pinned directory**, as the index lists a directory
   model's. That is how a directory is told from a file, by the index's own rule. A glob is
   not listed, so a partitioned dataset does not swell the lockfile; a dataframe declared as a
   bare directory does.
3. **Four ways of not being pinned, each with its own message**: no lockfile entry for the
   dependency, no such asset when it was pinned (with a "did you mean"), not built when it was
   pinned, and pinned with the bytes not in the store. Each says to run `chartbook pin`, and
   where.
4. **An undeclared pipeline is an error that shows the line to add.** The user's catalog is
   asked where that pipeline is, to fill in the `path`. That is the chain's second step, used
   for the message only: being in a catalog never lets a pipeline be read from.
5. **Resolving stays cheap.** It reads the manifest's `[dependencies]` and the lockfile (kept
   in memory while the file is unchanged), and looks at whether one directory exists in the
   store. Nothing is hashed. The other pipeline's own directory is not touched, so it can be
   moved or gone.
6. **`data.load()`'s arguments.** One argument is a reference. With a `dataframe`, the first
   is the pipeline, as it always was, so no existing call changes. A mix is a `TypeError`
   that shows both forms.
7. **Pinning replaces an object that is in the store as a link.** Something else may have
   stored the same bytes more cheaply; a pin of them has to be frozen all the same.
8. **`pinned_inputs` holds only inputs that are another pipeline's.** This pipeline's own
   inputs are live, so there is nothing pinned to name. It says what the lockfile pins, not
   what a given training run read.
9. **A lockfile that cannot be read does not stop a build.** The index is written without
   what is pinned, with a warning.
10. **One function says what a manifest may state and what resolves**
    (`resolve.parse_declared_ref`). There were two, because another pipeline's asset could be
    stated before it could be resolved. `parse_local_ref` is gone.
11. **The example retrains when `chartbook.lock` changes.** Its training task depends on the
    lockfile, not on the path of the data. See the first correction below for why.

**Where the design was wrong, or did not see something coming.**

1. *The `dodo.py` in {doc}`asset-graph`, "Paths":
   `"file_dep": [data.path("fed_yield_curve:treasury_rates")]`.* It works, once pinned. But a
   `dodo.py` is run from top to bottom before any task starts, so that call fails unless the
   pin is already there, and a task inside the same file cannot be what makes it. The example
   depends on `chartbook.lock` instead, which exists as a name before it exists as a file.
2. *"`path()` … reads the raw `chartbook.toml` and nothing else … it raises only when the name
   is not declared or its entry has no `path`."* True of a local reference. For another
   pipeline's asset it also reads the lockfile and looks in the store, and can fail for a
   reason in either.
3. *The link ladder against the step's own "Done when".* They could not both hold on a disk
   without reflinks. Resolved by decision 1 above.
4. *The handoff brief: "`doit forget --all` in an example forces its tasks to run again."*
   It does, and the tasks then keep the test suite's mock data: each pull script skips the
   download when its data file is newer than itself. A live rebuild needs the examples'
   `_data` folders removed first. Three earlier reports in this series said "live pulls" and
   were wrong about that.

#### 3e, as built

*Added 2026-10-12.* A dependency that is not on your disk.

```toml
[dependencies]
"ftsfr/ref_data" = { git = "https://gitlab.example.org/ftsfr/ref_data", rev = "v1.2" }
```

```console
$ chartbook pin
ftsfr/ref_data: fetched https://gitlab.example.org/ftsfr/ref_data at 4f2a91c (v1.2)
ftsfr/ref_data: 2 pinned, 1 not built
  not built: ftsfr/ref_data:daily_prices (./_data/daily_prices.parquet)
  A git dependency has only what its repository commits.
Wrote chartbook.lock.
```

| What | Where |
|---|---|
| The clone cache: fetch, resolve a revision, check out a commit | `chartbook/gitcache.py`, `GitCache` |
| Where the cache is: `CHARTBOOK_GIT_CACHE`, then `[git] path`, then `~/.chartbook/git/` | `chartbook/config.py`, `get_git_cache_path()` |
| Pinning from a checkout, at the locked commit | `chartbook/lock.py`, `_fetch()` |
| `check` looks at a fetched dependency, offline | `chartbook/check.py`, `_fetched_checkout()` |
| The commit, on a dependency in the index | `chartbook/index.py`, `schemas/chartbook/v1/Pipeline.json` |
| The tests, all on repositories made by the test | `tests/test_git_dependencies.py` |

**Decided by the maintainer, 2026-10-12, before it was built:**

1. **Build it now, plainly.** Clone, check out the revision, then treat it as a `path`
   dependency. It pins the declared files that are in the checkout, lists the rest as not
   built, and says that a git dependency has only what its repository commits. Running the
   upstream's build, or a shared store, fills in the rest later with no change to the format.
2. **The clones are in `~/.chartbook/git/`**, beside the store, one per user: a bare clone per
   repository and a checkout per commit. ChartBook runs the user's own `git`.

**Not done in 3e, on purpose.** ChartBook does not run a fetched pipeline's build, so built,
git-ignored data stays "not built". Submodules and Git LFS are not handled.
`[resolve] default_host` is not built, so `{ rev = "…" }` with no `git` is still refused.
Nothing clears old checkouts; `chartbook store gc` does not touch the git cache.

**Proposed: implemented in 3e, and waiting on the maintainer's yes.**

1. **The cache's layout.** `repos/<host>/<owner>/<name>.git` and
   `checkouts/<host>/<owner>/<name>/<commit>/`. A repository on this disk goes under
   `local/`. The same repository reached by two URLs shares one clone.
2. **The lockfile records the commit beside the declared `rev`**:
   `"location": { "kind": "git", "url": …, "rev": "v1.2", "commit": "4f2a91c0…" }`. `rev` is
   what the manifest says; `commit` is what it meant when it was pinned. With no `rev`, the
   repository's default branch.
3. **`pin` stays at the locked commit, and uses the network only if this disk has lost its
   copy of it.** `update` fetches again and asks what the `rev` means now, so a branch moves
   and a tag or a commit does not.
4. **A changed `git` or `rev` in the manifest is followed by `update`, not by `pin`.** `pin`
   says that the manifest now names something else, and stays.
5. **A repository that cannot be reached is a failure only when it matters**: on an update,
   or when nothing of it is pinned. With its pins in the store, `pin` carries on, as it does
   for a directory that has gone.
6. **A token never reaches a disk or a screen through ChartBook.** The URL is handed to git on
   each call and is not written into the clone's configuration. Every message, the lockfile
   and the index show the URL without its user name and password.
7. **Git is never left waiting for someone to type.** Prompts are off, so a repository that
   needs a password ChartBook cannot supply fails.
8. **A URL or a `rev` that git could take for an option is refused**, when the manifest loads
   and again before git is run: one that starts with `-`, a `rev` with anything but letters,
   digits, `.`, `_`, `/` and `-`, and git's `ext::` transport, which runs a command.
9. **A path is a repository too**, relative to the manifest: `git = "../ref_data"`.
10. **A checkout is read-only and has no `.git` in it.** It is a copy of one commit, not a
    place to work.
11. **`check` never uses the network.** It looks at a `git` dependency where it has been
    fetched, at the lockfile's commit, and warns when it has not been.
12. **Every test runs with its own store and its own git cache.** A fixture sets the two
    environment variables for all of them. (Before it existed, one test run put an empty
    clone in the real `~/.chartbook/git/`. It was removed.)

**Where the design was wrong, or said less than it seemed to.**

1. *"`path` versus `rev`: both are pinned. The difference is only where a refresh gets its
   content from — a local directory, or a git fetch."* ({doc}`asset-graph`.) There is a second
   difference, and it is the one that matters. A directory has the pipeline's built files. A
   git fetch has only what was committed, which for most pipelines is none of the data.
2. *"A shipped pipeline is self-resolving. Someone who clones the repository can build it with
   no catalog configured and no access to your filesystem."* True of its code and of its
   dependencies' code. Its dependencies' *data* still has to come from somewhere: committed
   outputs today; `chartbook run` or a shared store later.
3. *The build record writes a dependency's location as one string*
   (`"https://gitlab.internal/…@a1b2c3d"`), *and the `Pipeline` record as an object*
   (`{ "kind": "git", "url": …, "rev": … }`). The lockfile and the index use the object, with
   `commit` added. Build records should follow when they are built.

#### Answers to the open questions

*The maintainer answered five of these on 2026-10-12, after 3a, a sixth with 3d and the last
with 3e. All seven are **decided**.*

1. **Where the store lives. Decided.** One store per user, at `~/.chartbook/store/`, beside the
   settings file that is already there. `CHARTBOOK_STORE`, or `[store] path = "…"` in
   `settings.toml`, points it somewhere else: a bigger disk, or a drive a team shares. Not one
   store per project, because ten projects that pin the same upstream should hold one copy.

   Layout: one directory per asset, named by its hash, holding the asset's files under their
   own names.

   ```text
   ~/.chartbook/store/
     objects/sha256/7f/3a9c…/treasury_rates.parquet          a one-file asset
     objects/sha256/b2/09e1…/year=2024/part-0.parquet        an asset of many files
     builds/                                                 kept for step 4
   ```

   The file names are kept because the path handed to a reader has to still end in `.parquet`,
   and a partitioned dataset has to keep folders like `year=2024/`.

2. **How the store links to a file. Decided: all four kinds, in the designed order.** Reflink,
   then hardlink, then symlink, then copy ({doc}`asset-graph`, "Links, not copies"). The
   builder of 3a asked to drop the two middle ones, and the maintainer kept them: they are the
   cheapest on every disk.

   What that means, so that nobody is surprised later. A reflink or a copy is the store's own
   bytes: nothing outside the store can change it. A hardlink *is* the upstream's file under a
   second name, and a symlink only points at it. If the upstream pipeline rewrites
   `_data/rates.parquet` in place, an object stored either of those ways changes with it, and
   still sits under its old hash. **`chartbook store verify` is what catches that**, by hashing
   every object again. So the step's "Done when" line, "editing the upstream's data does not
   change what the downstream reads", holds on a disk with reflinks (APFS, btrfs, XFS) and
   wherever the upstream replaces its files instead of rewriting them; elsewhere it holds only
   until the upstream rebuilds, and `verify` says when it has stopped holding.

   *Decided later the same day, with 3d: a **pin** asks for a reflink, then a copy, and
   nothing else.* The store still offers all four kinds. So the paragraph above now describes
   what a build cache would get, and a pin is frozen on every disk ("3d, as built").

3. **The lockfile's shape. Decided.** JSON, in the index's own format: the same envelope
   (`"schema": "chartbook/lock/v1"`) and a `records` list. It holds this pipeline's `Pipeline`
   record with only its `id` and `dependencies` (each now with a `pinned_hash`), and, for each
   pinned asset, the upstream's own record for it, cut down to `id`, `ref`, `pipeline`,
   `location.path`, `content_hash` and `size_bytes`. No timestamp and no absolute path, so
   pinning twice with nothing changed writes the same bytes and shows no diff. `Build` records
   join it in step 4. This is what "no second format" in {doc}`index-schema` asks for.

4. **`pin` when an upstream has not been built. Decided.** Pin what is there and say what is
   not. An asset whose file is missing gets a record with no `content_hash`, exactly as the
   index writes one today. Asking for its path later fails, and says to build it upstream and
   run `chartbook update`. So an upstream with ten dataframes, one of which needs a
   subscription you do not have, is still usable. The stricter choice, refusing to pin at all,
   is what `--frozen` is for in step 4.

5. **Hidden files when hashing a directory. Decided.** Skip a short, fixed list of files that
   operating systems create by themselves: `.DS_Store`, `Thumbs.db`, `desktop.ini`, and any
   name starting with `._`. Every other file counts, hidden or not. A Zarr dataset keeps its
   real metadata in `.zarray` and `.zattrs`, and leaving those out would give two different
   datasets one hash. No release carries the earlier rule, so this changes it without a new
   algorithm prefix. It is built with the store (3b), which is keyed by it.

6. **A `git` dependency. Decided, and built in 3e.** Clone once into `~/.chartbook/git/`,
   fetch on `update`, and check the wanted commit out into a directory beside it. From there
   it is a `path` dependency. The lockfile records the full commit hash that `rev` meant when
   it was pinned.

   What had to be decided first: a fresh clone has the upstream's *code*, not its data,
   because built data is usually git-ignored. So a `git` dependency can only be pinned where
   the upstream commits its outputs. Otherwise it needs step 4 (run the upstream's `build`)
   or a shared store to download from. The maintainer's answer: build it now, plainly, and
   have it say so. It does.

7. **`data.load("pipeline:asset")`. Decided, and built in 3d.** `data.load("treasury_rates")`
   loads this pipeline's own dataframe, `data.load("fed_yield_curve:treasury_rates")` loads the
   pinned copy, and the two-argument `data.load(pipeline=…, dataframe=…)` keeps meaning
   "through a catalog". One reference is the form every other call already takes.

### Step 4. Running, build records and versions

**Goal:** `chartbook run` builds pipelines in dependency order and skips what is current.

- `[scripts]`, with `build` as the reserved name. `chartbook run [script]`.
- `Build` records: input hash, output hash, code revision, tools, `impure`.
- Skip a pipeline whose input hash is already in the store.
- `--frozen`, for CI.
- The command rename in {doc}`asset-graph` ("The command surface"): `build` makes everything
  current, `docs` renders the site.
- `@rev` resolves. Model versions and labels (slice M4 of {doc}`models`). Settle the open
  questions there first.
- Parts: `dataframe#series` resolves for `data.load()`.

**Done when:** changing one upstream script and running `chartbook run` in the downstream
example rebuilds exactly the pipelines that depend on it, and running it again does nothing.

*(Added 2026-10-13.)* Step 4 is built in five parts, one pull request each:

| Part | What | State |
|---|---|---|
| 4a | `[scripts]` and `chartbook run`: the order between pipelines, and a script run in each | Built |
| 4b | `Build` records, skipping a pipeline whose inputs have not changed, `--frozen` | Next |
| 4c | The command rename: `build` makes everything current, `docs` renders the site. Breaking | |
| 4d | `@rev` resolves. Model versions and labels | |
| 4e | Parts: `dataframe#series` for `data.load()` | |

**Decided by the maintainer, 2026-10-13, before 4a was built:**

1. **`chartbook run` never moves a pin.** It pins what has no pin, as `chartbook pin` does,
   and leaves the rest. {doc}`asset-graph` says the opposite: *"By default it also refreshes
   `path` pins, because the common case is 'pick up a colleague's latest.'"* The rule from 3c
   holds for `run` too: `chartbook update` is the one thing that moves a pin, so a lockfile
   changes only in a commit someone meant to make.
2. **`chartbook run` builds a `git` dependency**, in a writable copy of its checkout. This is
   the answer to the question 3e left open: how a `git` dependency's built data gets here.
3. **Step 4 is cut into the five parts above**, 4a first.
4. **The pull requests keep stacking**, each branch made from the one before it.

**What decision 1 does to "Done when".** Example: `yield_curve` changes one script, and
someone runs `chartbook run` in `rate_forecast`. `yield_curve` is rebuilt. `rate_forecast`
reads its pins, and no pin moved, so nothing it reads has changed. The sentence above
("rebuilds exactly the pipelines that depend on it") is therefore true after
`chartbook update`, not before: `update`, then `run`, rebuilds what depends on what moved.
*Proposed:* 4b is built to that reading. The sentence is left as written, with this note.

#### 4a, as built

*Added 2026-10-13.* A pipeline says how it is built, and one command builds what it depends
on first.

```toml
[scripts]
build = "doit"
test  = "pytest"
```

```console
$ chartbook run
ftsfr/fed_yield_curve: build    in /work/fed_yield_curve
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 2 pipeline(s).
```

| What | Where |
|---|---|
| Reading `[scripts]`, and `[project] build` as the same thing | `chartbook/manifest.py`, `read_scripts()` |
| The order between pipelines | `chartbook/run.py`, `plan()` |
| Running one script | `chartbook/run.py`, `execute()` |
| Pinning before a build, then running, then stopping at a failure | `chartbook/run.py`, `run()` |
| The command | `chartbook/cli.py`, `run_command()` |
| A writable copy of a git checkout, to build in | `chartbook/gitcache.py`, `GitCache.work_copy()` |
| Pinning from that copy when there is one | `chartbook/lock.py`, `_fetch()` |
| Letting go of what was built at a commit an update moved away from | `chartbook/lock.py`, `_pin_asset()` |
| Every script in the index | `chartbook/index.py`, `pipeline_records()` |
| The tests | `tests/test_run.py`; one end to end in `tests/test_integration.py` |

**Not done in 4a, on purpose.** Nothing is skipped: every pipeline's script runs every time,
and the pipeline's own tool skips what it can. There are no `Build` records and no
`--frozen`. Pipelines run one at a time. `chartbook build` still renders the website, so the
word still means two things until 4c. `chartbook update` still rebuilds nothing.

**Proposed: implemented in 4a, and waiting on the maintainer's yes.**

1. **`[project] build` and `[scripts] build` are one thing.** Both are read. A manifest that
   gives both, with different text, does not load. Pages and the policy keep reading
   `project.build`, which the loader fills from whichever was written.
2. **A script's name matches `[A-Za-z0-9._-]+`**, the rule an ID component already has, because
   it is typed after `chartbook run`. An empty script does not load.
3. **A script is handed whole to `bash -e -c`**, to `sh` where there is no `bash`, and to `cmd`
   on Windows. It runs in the pipeline's directory, with the environment `chartbook run` was
   started in, and its output is not captured. `bash` because `module load` and
   `conda activate` expect it.
4. **The order.** Depth first. A pipeline's dependencies are taken in the order of their keys,
   and a catalog's pipelines in the order the catalog lists them. A pipeline is the directory
   it is in, so one that two others depend on is run once.
5. **Two pipelines that depend on each other are an error** that shows the loop. Nothing is run.
6. **The pipeline that was asked for must have the script.** One it depends on, or a member of
   a catalog, that has no script by that name is passed over and named. A name that no
   pipeline has is an error.
7. **Only `build` pins.** `chartbook run test` pins nothing and writes no lockfile.
8. **Each pipeline is pinned just before its own build**, after the pipelines it depends on
   have been built, not all at once at the start. So a dependency that itself has
   dependencies, a `build` script and no lockfile gets a `chartbook.lock` written in *its*
   directory. For a `path` dependency that is someone else's working directory. A pipeline
   with no `build` script is not pinned for.
9. **What cannot be pinned stops the run before that pipeline's build**: a dependency that is
   not there and has nothing pinned, a repository that cannot be fetched, a lost pin. A
   dependency that has gone and *is* pinned is no trouble: it is named as not run, and the
   build goes ahead on its pins.
10. **The exit code is the failed script's.** One stopped by a signal gives 128 plus the
    signal's number, as a shell reports it. What ChartBook printed is flushed before a script
    starts, so a log has the lines in order.
11. **A git dependency's working copy** is `~/.chartbook/git/work/<host>/<owner>/<name>/<commit>/`:
    the checkout's files, made writable. It is made once and kept, so a second run finds the
    first one's work. It is shared by every project of this user that depends on that commit.
    The checkout itself is never written to.
12. **`pin` and `update` pin a git dependency from its working copy when there is one**, and
    from the checkout otherwise. Running `chartbook pin` after `chartbook run` therefore sees
    the built data too.
13. **Which commit is built.** The lockfile's, if it names one, since a pin does not move.
    Otherwise what the `rev` means now.
14. **The index lists every script** under `scripts`, sorted by name. The schema already
    allowed it.
15. **A catalog has no `[scripts]`.** A manifest that gives one does not load.
16. **What it says.** One line per pipeline, `id: script    in <directory>`, with no directory
    for the pipeline the command was run in. Pins are mentioned only when something happened:
    a run where every pin was already in place says nothing about them.
17. **An update that moves a `git` dependency's commit lets go of what was built at the old
    one.** This changes one case of a rule proposed in 3c (number 7 there: an asset the other
    pipeline "declares and no longer has on disk keeps its pin"). Example: `ref_data` is pinned
    at commit A, with `daily_prices` built there by `run`. `update` moves it to commit B, where
    nothing is built yet. Under the 3c rule the lockfile would then say commit B beside the
    bytes built from A. Nobody else could get those back: a fresh clone builds B, gets other
    bytes, and the pin is lost. And `run` could not fix it, because `run` moves no pin. So the
    pin is removed, `update` says "let go", and the next `run` builds B and pins it. The rule
    is unchanged for a `path` dependency, and for a `git` one whose commit did not move.

**Known gaps in 4a.**

1. **Nothing clears old working copies.** A branch that moves leaves one per commit, each with
   whatever its build wrote. `chartbook store gc` does not touch the git cache.
2. **Two runs at once in one working copy** are not kept apart. Two projects of one user that
   depend on the same commit share it.
3. **A `path` dependency of a `git` dependency** is looked for beside the working copy, where
   it almost never is. It is named as not run.
4. **On a first run, a `git` dependency is fetched twice**: once to choose the commit to build,
   once by the pin. If the branch moves in between, the pin lands on a commit that was not
   built, and says "not built". The next run builds that commit and pins it.

**Where the design was wrong, or said less than it seemed to.**

1. *"By default it also refreshes `path` pins."* ({doc}`asset-graph`, "Two verbs".) Decided
   otherwise, above. It takes this step's "Done when" with it, also above.
2. *"Today the field is documentation-only … choosing script semantics now means a future
   `chartbook run` can execute the value as-is with no format change."*
   ({doc}`toml-format-v2`.) True of the format and not of the values. Nothing ever ran the
   field, so nothing ever checked that it held a command. This repository's own
   `examples/yield_curve` had `build = "module load anaconda3/3.11.4 TeXLive/2023"`: a note
   about the environment. `chartbook run` would have run it and failed. The example now says
   `doit`. Other manifests may hold notes too, and the changelog says so.
3. *"If variants are ever needed … the natural extension is a `[project.build]` table with
   named keys."* ({doc}`toml-format-v2`.) {doc}`asset-graph`, written later, has `[scripts]`.
   `[scripts]` is what is built.
4. *"`chartbook update` — move pins forward to current upstream state, and rebuild what that
   invalidates."* ({doc}`asset-graph`.) `update` rebuilds nothing. With pins that `run` does
   not move, the pair is `update`, then `run`. Whether `update` should run the build itself
   is a question for 4b.
5. *"`chartbook run` pins anything not yet pinned, so neither verb is needed to get started."*
   True as built, for `build`. Any other script pins nothing.
6. *"`build` still means 'render the website' and keeps doing so until `run` exists; the
   rename is one breaking change, made once, in the same release as `run`."*
   ({doc}`asset-graph`.) `run` exists and the rename is 4c. Both are unreleased, so "the same
   release" still holds, and until 4c `chartbook build` and `[scripts] build` mean different
   things.
7. *The `dodo.py` in {doc}`asset-graph` that reads another pipeline's asset at the top of the
   file* failed until the dependency was pinned ("3d, as built"). Under `chartbook run` it
   works, because the pin is made before `doit` starts. Run as plain `doit` in a fresh clone,
   it still fails.

**Seen while trying it by hand.** A pin is read-only (decided in 3d). A build script that
copies a pinned file with `cp` gets a read-only copy, and cannot write over it on the next
run. Nothing is wrong, and it will surprise someone. Reading the pinned file in place avoids
it.

### Step 5. Data in databases

**Goal:** a dataframe can be a table, and `data.load()` does not change.

This is {doc}`data-access` and GitHub issue 9. It depends only on step 1 (it changes the
`Dataframe` record's `location`), so it can be done any time after that, by someone else, in
parallel with steps 2 to 4.

### Step 6. Readers of the index

Once the index is stable: render the site from it, a Dagster export, an MCP server, a
provenance panel on each page, a diff of two indexes. Each is a reader of one file
({doc}`index-schema`, "What this unblocks").

## Working in the code

The contributing guide ({doc}`../contributing`) has setup and style. These are the things that
are easy to miss:

- **Run tests with `hatch test`**, not `pytest` directly. `hatch test --all` runs six
  environments (Python 3.10 to 3.13, and Sphinx 7 and 8 on 3.13), and all six must pass.
- **Build the docs with `hatch run docs:build`.** One warning is expected, about a plotly MIME
  type in `gallery.ipynb`. Any other warning is yours.
- **A new module needs a line in `docs_src/reference/api.md`**, or the docs build warns.
- **The index is a contract.** A change to what `chartbook/index.py` writes needs the same change
  in {doc}`index-schema` and in the JSON Schema for that record, in one commit. A change to how
  anything is hashed needs a new algorithm prefix.
- **Every user-visible change needs a changelog entry** in `docs_src/changelog.md`, in
  paragraphs that say why. A breaking change is marked **breaking** and says what to do instead.
- **The agent skill is in two places.** Edit `src/chartbook/skills/`, then copy to
  `.claude/skills/chartbook/`. Update `llm/llms.txt` and `llm/llms-full.txt` when commands
  change.
- **The examples are tests.** `cd examples && doit` must build both example pipelines and the
  catalog, and `chartbook check` must pass on each. They pull live data and need a FRED API key
  in a git-ignored `.env`; never print or commit it.
- **Do not edit a design document to match what you happened to build.** If the design is wrong,
  change the design on purpose, say why in the document, and get the maintainer's agreement.
  Mark what is *decided* and what is *proposed*, as {doc}`models` does.
- **Commit messages explain why**, in paragraphs.

## Decisions on record

Dated, so a later reader can tell what was known when. All were made or approved by the
maintainer.

| Date | Decision | Where it is written |
|---|---|---|
| 2026-07-20 | Manifest format v2: one `[project]` table, scoped pipeline IDs, policy in the catalog | {doc}`toml-format-v2` |
| 2026-10-11 | The asset graph and the index. ChartBook publishes and never orchestrates | {doc}`asset-graph`, {doc}`index-schema` |
| 2026-10-11 | Dataframes may live in databases; ChartBook substitutes names and never rewrites SQL | {doc}`data-access` |
| 2026-10-12 | A registry is the first of exactly *three* ID components, so a dotted scope stays a scope | {doc}`references`, rule 7 |
| 2026-10-12 | `repo_url` defaults to the git remote. "Code updated" comes from the last git commit and is shown only on the pipeline's page | Changelog 0.2.0 |
| 2026-10-12 | Catalog builds are incremental by default, with no running server | Changelog 0.2.0 |
| 2026-10-12 | Scratch files go in `<pipeline>/_data/_scratch/` | Changelog 0.2.0 |
| 2026-10-12 | The stability policy is one line: experimental, anything can change, breaking changes are in the changelog | {doc}`../reference/stability` |
| 2026-10-12 | Asset names are **per kind**, not one namespace. Data is the spine | {doc}`references` |
| 2026-10-12 | The kind goes in the address (`chart/gdp`), dataframe is the default, the four separators stay, and one parser produces a structured object | {doc}`references` |
| 2026-10-12 | `chartbook.assets` is the general module. `chartbook.data` is dataframes only. `chartbook.models` will follow the same pattern | {doc}`references` |
| 2026-10-12 | No minor version per step: the asset graph is one change, built under 0.2.0 and wrapped up at the end | "Versions", above |
| 2026-10-12 | How a directory or glob is hashed; an unchanged index is not rewritten, so `generated_at` is when it last changed | {doc}`index-schema` |
| 2026-10-12 | Columns should have SQL-compatible names; a readable name is metadata. A column whose name is not a legal address has no series until a table names it | {doc}`index-schema`, {doc}`../reference/configuration` |
| 2026-10-12 | A model's training data may be another pipeline's dataframe, and may be declared now, ahead of dependencies. Making it a real, pinned dependency is the headline case for step 3 | {doc}`models`, step 3 above |
| 2026-10-12 | By default `check` reports a model that does not say what it was trained on. A model's write-up is strongly recommended, not required | {doc}`models` |
| 2026-10-12 | Models are assets. ChartBook is a model registry, not an experiment tracker. ML operations is a central use case | {doc}`models` |
| 2026-10-12 | The store is one per user, at `~/.chartbook/store/`, movable with `CHARTBOOK_STORE` or `settings.toml`. One directory per asset, named by its hash, files under their own names | "Answers to the open questions", above |
| 2026-10-12 | The store links by reflink, hardlink, symlink, copy, in that order, as designed. `chartbook store verify` is what catches an object changed from outside | "Answers to the open questions", above; {doc}`asset-graph` |
| 2026-10-12 | `chartbook.lock` is JSON in the index's format: no timestamp, no absolute path | "Answers to the open questions", above |
| 2026-10-12 | `chartbook pin` pins what is built and says what is not; asking for an unpinned asset is what fails | "Answers to the open questions", above |
| 2026-10-12 | Hashing a directory skips `.DS_Store`, `Thumbs.db`, `desktop.ini` and `._*`, and nothing else | "Answers to the open questions", above; {doc}`index-schema` |
| 2026-10-12 | `chartbook pin` never moves an existing pin. `chartbook update` is what moves one | "3c, as built", above |
| 2026-10-12 | `chartbook store gc` keeps what the lockfiles registered in the store name, keeps the pins of one it cannot find unless told to forget it, and asks before removing | "3c, as built", above |
| 2026-10-12 | A pin is frozen: `pin` and `update` ask the store for a reflink, then a copy, never a hard link or a symlink. The store keeps all four kinds | "3d, as built", above |
| 2026-10-12 | `data.load()` takes one reference, `data.load("pipeline:name")`, beside the two-argument catalog form | "3d, as built", above |
| 2026-10-12 | A `Model` record names what its cross-pipeline inputs are pinned at in `pinned_inputs`, beside `inputs` | "3d, as built", above; {doc}`index-schema` |
| 2026-10-12 | `examples/rate_forecast` git-ignores its lockfile, because its upstream pulls live data | "3d, as built", above |
| 2026-10-12 | `git` dependencies are built now, plainly: clone, check out, pin what the repository commits, and say that is all a clone has | "3e, as built", above |
| 2026-10-12 | Clones of `git` dependencies are kept in `~/.chartbook/git/`, one per user, and ChartBook runs the user's own `git` | "3e, as built", above |
| 2026-10-13 | `chartbook run` never moves a pin. It pins what has no pin and leaves the rest; `chartbook update` moves pins | Step 4 above; {doc}`asset-graph`, "Two verbs" |
| 2026-10-13 | `chartbook run` builds a `git` dependency, in a writable copy of its checkout, and its built data is pinned from there | Step 4 above, "4a, as built" |
| 2026-10-13 | Step 4 is built in five parts, 4a to 4e, one pull request each, stacked | Step 4 above |

## Open questions, collected

Each is explained where it lives.

- How `@rev` is looked up; how model versions are numbered across branches; which builds make a
  version; retention. ({doc}`references`, {doc}`models`)
- Whether dataframes and charts should still be *required* to have a write-up, or only strongly
  recommended, as models are. ({doc}`models`, "Decided while building it")
- Whether a pipeline's own `[policy]` table is wanted. It is honoured today, as a *proposed*
  answer to a crash. ({doc}`toml-format-v2`, "Since this was written")
- The things settled while building declared dependencies (twelve), the store (ten) and
  pinning (fourteen), cross-pipeline references (eleven) and `git` dependencies (twelve), each
  listed as *proposed* under its "as built" heading. (Step 3 above)
- The seventeen things settled while building `chartbook run`, and the reading of step 4's
  "Done when" now that `run` moves no pin. (Step 4 above, "4a, as built")
- Whether `chartbook update` should run the build after it moves a pin, as {doc}`asset-graph`
  says, or stay a command that only moves pins. (Step 4 above; a question for 4b)
- A shared store, as a second way for a `git` dependency's built data to get here. The first
  is built: `chartbook run` builds it. (Step 4 above, "4a, as built")
- How a chart says it was made from another pipeline's data. (Step 3 above)
- Whether the site should render from the index, and when. (Step 6)
- `plotting.line()` and its siblings can only use the two built-in backends, although third
  parties can register others. ({doc}`../guide/plotting-backends`)
- The project template's CI should run `chartbook check --skip-outputs`, once 0.2.0 is on PyPI.
