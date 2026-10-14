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
| **location** | Where an asset physically is: a file, or a table or query in a source ({doc}`data-access`) |
| **index** | One JSON file describing everything a catalog contains. A build product. Planned ({doc}`index-schema`) |
| **record** | One entry in the index. Each has a `kind` (`Dataframe`, `Chart`, …) and a `version` |
| **store** | A local folder of files named by their hash, used for caching and pinning. One per user, shared by their projects ({doc}`asset-graph`) |
| **object** | One asset in the store: a directory named by the asset's content hash, holding its files under their own names |
| **dependency** | Another pipeline that this one reads from, declared in `[dependencies]`: a name, and where to find it (`path` or `git`) |
| **resolution chain** | The order in which a pipeline's location is looked for: `[dependencies]`, then the catalog. One function, `chartbook.resolve.locate_pipeline` |
| **lockfile** | `chartbook.lock`: the exact bytes of the upstream assets a project uses, by content hash. JSON in the index's format. Committed |
| **pin** | To freeze which version of an upstream asset a project reads. Also the record of it: an asset's entry in the lockfile, with a `content_hash`. `chartbook pin` makes pins and never moves one; `chartbook update` moves them |
| **build record** | A written description of how one asset was made: inputs, code, tools, output hash. Planned |
| **source / backend** | A named database connection in a manifest / the engine behind it. Built: DuckDB ({doc}`data-access`) |
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
| 4 | {doc}`asset-graph` | Dependencies, pinning, the store, build records, what ChartBook will not do | Step 3 built: declared dependencies, the store, pinning, cross-pipeline references, `git` dependencies. Step 4 is done: `[scripts]`, `chartbook run`, snapshots, the command rename, and versions of a model. Its last listed part, loading one column, was decided against. **Nothing is next by default**: what is open is listed under "Open questions" The model the maintainer decided on 2026-10-13 is in this page, under step 4, and overrides {doc}`asset-graph` where they differ |
| 5 | {doc}`index-schema` | The index file, record by record | First implementation built |
| 6 | {doc}`models` | Models as assets | First slice built: declared models |
| 7 | {doc}`data-access` | Dataframes that live in a database | Built for DuckDB, 2026-10-13: `[sources]`, `table`, `query`, `data.sql()` |

For how the existing build works, read {doc}`../guide/how-the-build-works`. For every command
and field, {doc}`../reference/cli` and {doc}`../reference/configuration`.

## What is built

As of 0.2.0, plus the index, declared models, declared dependencies, the store, pinning,
named scripts, `chartbook run` and snapshots, which came after it.

| Capability | Where | Notes |
|---|---|---|
| Manifest format v2, pipeline IDs, catalogs, policy | `manifest.py`, `identity.py` | `repo_url` defaults to the git remote |
| The documentation site | `build_docs.py`, `markdown_generator.py`, `docs_src_pipeline/`, `docs_src_catalog/`, `chartbook docs` | Two stages: write Markdown into `_docs/`, then run Sphinx. `chartbook build` runs the build script first |
| Incremental builds and `--watch` | `incremental.py` | A state file of file sizes and times. No server. Catalog builds are incremental by default |
| `chartbook check`, the CI gate | `check.py` | Required fields, broken paths, expiring licenses. `--skip-outputs` for CI that does not build data |
| The reference grammar | `refs.py` | All of it parses |
| Resolving local references | `resolve.py`, `assets.py`, `data.py`, `chartbook path` | One resolver, typed locations. Live: the declared `path` |
| `git` dependencies | `gitcache.py`, `lock.py` | Cloned into `~/.chartbook/git/`, checked out at a commit, then pinned like a directory. Only what the repository commits, until `chartbook run` builds it in a working copy |
| Named scripts and `chartbook run` | `manifest.py` (`read_scripts`), `run.py`, `gitcache.py` (`work_copy`) | `[scripts]`, with `build` reserved. Runs a script in the pipeline it is given. Pins what has no pin before a build; never moves a pin. Never builds in a folder the pipeline depends on. Builds a `git` dependency once, in a clean copy |
| Resolving another pipeline's assets | `resolve.py` (`_resolve_pinned`), `lock.py`, `store.py` | `pipeline:name`, for a declared dependency, resolves through `chartbook.lock` to the pinned copy in the store. Every kind, every front door, and `data.load("pipeline:name")` |
| The index, `index.json` | `index.py`, `hashing.py`, `schemas/` | Written by every build, beside the HTML. One hash rule; hashes cached in the build directory |
| Series tables | `manifest.py` (`validate_series`) | `[dataframes.x.series.y]` documents a column. In the index; not on pages yet |
| Models | `models.py`, `manifest.py` (`validate_models`), `markdown_generator.py` (`generate_model_docs`) | `[models.x]`, `chartbook.models.path()`, a page and an index record per model. Versions, made by a snapshot and named by the start of the content hash, with labels in `[models.x.aliases]` |
| Declared dependencies | `manifest.py` (`validate_dependencies`), `resolve.py` (`locate_pipeline`), `check.py` (`check_dependencies`) | `[dependencies]`, with `path` or `git`. One resolution chain. In the index, and checked |
| The store | `store.py`, `config.py` (`get_store_path`), `chartbook store verify` | Objects named by content hash, behind `has`, `get`, `put`, `delete`. Four kinds of link |
| Snapshots | `snapshot.py`, `chartbook snapshot` | What one commit of a pipeline built, in the store. Made on purpose by its owner, with everything committed. The only thing of a pipeline that another reads |
| Pinning | `lock.py`, `chartbook pin`, `chartbook update`, `chartbook store gc` | `chartbook.lock`: the commit, and a content hash for every asset, of every dependency. A folder is pinned from a snapshot, a repository from a clean copy. `pin` never moves a pin; `update` does |
| Loading a dataframe through a catalog | `data.py` | `data.load(pipeline=…, dataframe=…)`. The older, two-argument form. It enters the resolution chain at the catalog and does not read `[dependencies]` |
| Scratch directory | `data.scratch()` | `<pipeline>/_data/_scratch/` |
| Freshness lines on pages | `markdown_generator.py`, `chartbook-freshness.js` | "Data updated 2 days ago", computed in the browser |
| Data glimpses | `create_data_glimpses.py` | Reads the manifest, not `dodo.py` |
| Scaffolding | `scaffold.py`, `chartbook init --git/--github`, `template/` | Renders the cookiecutter template, which is the `template/` folder of this repository |
| Plotting helpers and backends | `plotting/` | The one real plugin system. See {doc}`../guide/plotting-backends` |
| Reserved for later, and refused | `refs.py`, `resolve.py`, `identity.py`, `cli.py` | `#part`, `@rev`, registry prefixes, `chartbook push` |

Not built: `--frozen`, a version of another pipeline's model, any export, and anything that
*reads* the index. Not to be built: loading one column by its
address (`data.load("dataframe#series")`).

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

`chartbook docs` also writes one JSON file that describes everything: `index.json`, beside the
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
   another commit. See "4a, as built", number 19.)*
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
- Parts: `dataframe#series` resolves for `data.load()`. *(Decided against, 2026-10-13: "4e",
  below.)*

**Done when:** changing one upstream script and running `chartbook run` in the downstream
example rebuilds exactly the pipelines that depend on it, and running it again does nothing.

*(Added 2026-10-13.)* The goal and the "Done when" above are no longer what is wanted. The
maintainer decided the model below while the first part was being built, and it replaces them.

#### The snapshot model

*Decided by the maintainer, 2026-10-13.* Two names make it concrete: `yield_curve` makes data,
and `rate_forecast` uses it.

**Why.** Pipelines are worked on side by side, by people and, more and more, by agents working
in parallel, one to a pipeline. Someone is always half-way through a change in `yield_curve`.
That must not reach `rate_forecast`. So the store is the one thing every pipeline reads from:
it is read-only, and it changes slowly and on purpose.

**The rules.**

1. **A pipeline never reads, hashes or builds in a folder it depends on.** `rate_forecast`
   does not look in `../yield_curve/_data/`, and nothing it runs is run there.
2. **A snapshot is every asset a pipeline declares, as built at one commit**, kept in the store
   and labelled with that commit. Dataframes, charts, notebooks, notes and models alike.
3. **A snapshot is made on purpose, by the pipeline's owner**, and only when everything is
   committed. It is not made by every build. That is how a pipeline is declared ready for
   others, and what keeps the label "built by this commit" true.
4. **`pin` and `update` choose among snapshots.** They do not copy whatever is in the folder.
5. **Nothing that happens in `yield_curve` rebuilds `rate_forecast`.** It rebuilds when it asks
   to move its pins, with `chartbook update`.
6. **`chartbook run` builds the pipeline it is run in.** A `git` dependency is the one thing it
   builds besides, once, in ChartBook's own clean copy of the commit: nobody works there, so
   there is nothing to disturb. Data that is pulled from outside is refreshed on purpose, with
   `--force`, and not because time has passed.
7. **Taking whatever is in a folder stays possible**, as an option that is off by default and
   out of the way, for someone working on both pipelines at once.

**What is asked for, and what was got.** The split is the one between `requirements.txt` and
`uv.lock`:

| | File | Says | Example |
|---|---|---|---|
| What is asked for | `chartbook.toml` | The repository, and a tag or a branch | `rev = "v1.2"` |
| What was got | `chartbook.lock` | The exact commit, and the hash of every file | `4f2a91c…`, `sha256:7ff1…` |

A commit alone is not enough: the same code gives other data on another day, or with other
settings. The lockfile does not try to list every cause. It records the *output*, the hash
of every file, and that catches a difference whatever caused it. What a hash cannot do is
bring the bytes back, which is what the store is for, and a store shared between machines
later.

**Code changes and data changes** are told apart by what is asked for. Pinned to a tag or a
commit, the code never changes, and `chartbook update` brings only newer data built from that
code. Pinned to a branch, `update` brings newer code as well.

**How much of it is built.** All seven rules: 5 and 6 in 4a, and 1, 2, 3, 4 and 7 in 4b,
both below. What is left is listed there as known gaps: old snapshots are never cleared, a
snapshot is not shared between machines, and making one takes its owner's word that what is
on disk was built by the commit.

**What it replaces in this step.** "`chartbook run` builds pipelines in dependency order and
skips what is current" is not the goal any more: a pipeline's dependencies are not built from
it. "Skip a pipeline whose input hash is already in the store" has become "a git dependency is
built once for a commit". And the `Build` record has become the snapshot: what one commit of
a pipeline built, with the bytes kept. *Proposed* "Done when", in its place: one agent can
rebuild `yield_curve` as often as it likes while another builds `rate_forecast`, and nothing
`rate_forecast` reads changes until it runs `chartbook update`.

#### The parts of step 4

| Part | What | State |
|---|---|---|
| 4a | `[scripts]` and `chartbook run` | Built |
| 4b | Snapshots: an owner declares a build ready, and pinning takes from that and never from the folder | Built |
| 4c | The command rename: `build` makes everything current, `docs` renders the site. Breaking | Built |
| 4d | `@rev` resolves. Model versions and labels | Built, for a pipeline's own models |
| 4e | Parts: `dataframe#series` for `data.load()` | **Not to be built.** Decided 2026-10-13, below |

`--frozen`, for CI, has no part yet. *Proposed:* it follows snapshots, since what it has to
check is that the lockfile is complete and that every pin can be had.

**Decided by the maintainer, 2026-10-13:**

1. **`chartbook run` never moves a pin.** It pins what has no pin, as `chartbook pin` does,
   and leaves the rest. {doc}`asset-graph` says the opposite: *"By default it also refreshes
   `path` pins, because the common case is 'pick up a colleague's latest.'"* The rule from 3c
   holds for `run` too: `chartbook update` is the one thing that moves a pin, so a lockfile
   changes only in a commit someone meant to make.
2. **`chartbook run` builds a `git` dependency**, in a writable copy of its checkout. This is
   the answer to the question 3e left open: how a `git` dependency's built data gets here.
3. **`chartbook run` never builds in a folder a pipeline depends on** (rule 1 above). The
   first version of 4a did, as {doc}`asset-graph` describes: it ran `build` in every pipeline
   of the dependency graph, each in its own folder. That was taken out before it was merged.
   It was also pointless once pins did not move: the other pipeline was rebuilt, and this one
   went on reading its pinned copy.
4. **A build is refreshed on purpose.** A git dependency is built once for a commit, and
   `chartbook run --force` builds it again. A pipeline that pulls live data is not rebuilt
   because a day has passed.
5. **The snapshot model**, above.
6. **Step 4 is built in parts**, 4a first, and the pull requests keep stacking, each branch
   made from the one before it.

#### 4a, as built

*Added 2026-10-13.* A pipeline says how it is built, and one command gets it built.

```toml
[scripts]
build = "doit"
test  = "pytest"
```

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

| What | Where |
|---|---|
| Reading `[scripts]`, and `[project] build` as the same thing | `chartbook/manifest.py`, `read_scripts()` |
| Which pipelines a run is about, and in what order | `chartbook/run.py`, `plan()` |
| Running one script | `chartbook/run.py`, `execute()` |
| Building a git dependency once, pinning before a build, then running | `chartbook/run.py`, `run()` |
| The command | `chartbook/cli.py`, `run_command()` |
| A writable copy of a git checkout, to build in, and whether it is built | `chartbook/gitcache.py`, `GitCache.work_copy()`, `is_built()` |
| Pinning from that copy when there is one | `chartbook/lock.py`, `_fetch()` |
| Letting go of what was built at a commit an update moved away from | `chartbook/lock.py`, `_pin_asset()` |
| Every script in the index | `chartbook/index.py`, `pipeline_records()` |
| The tests | `tests/test_run.py`; one end to end in `tests/test_integration.py` |

**Not done in 4a, on purpose.** There are no snapshots, so pinning still reads a `path`
dependency's folder (the model's rule 1 is met by `run` and not yet by `pin` and `update`).
There is no `--frozen`. `chartbook build` still renders the website, so the word still means
two things until 4c. `chartbook update` still rebuilds nothing.

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
4. **In a catalog, the script is run in each of the catalog's pipelines**, one that another of
   them depends on first, and otherwise in the order the catalog lists them. A pipeline the
   catalog does not list is not run, whoever depends on it. Two of its pipelines that depend
   on each other are an error that shows the loop, and nothing is run.
5. **The pipeline that was asked for must have the script.** A pipeline of a catalog that has
   no script by that name is passed over and named. A name that no pipeline has is an error.
6. **Only `build` pins, and only `build` reaches a git dependency.** `chartbook run test`
   writes no lockfile and fetches nothing.
7. **Each pipeline is pinned just before its own build.** A pipeline with no `build` script
   is not pinned for.
8. **What cannot be pinned stops the run before that pipeline's build**: a dependency that is
   not there and has nothing pinned, a repository that cannot be fetched, a lost pin. A
   dependency that has gone and *is* pinned is no trouble.
9. **The exit code is the failed script's.** One stopped by a signal gives 128 plus the
   signal's number, as a shell reports it. What ChartBook printed is flushed before a script
   starts, so a log has the lines in order.
10. **A git dependency's working copy** is `~/.chartbook/git/work/<host>/<owner>/<name>/<commit>/`:
    the checkout's files, made writable. It is made once and kept. It is shared by every
    project of this user that depends on that commit. The checkout itself is never written to.
11. **"Built" is a file in the working copy**, `.chartbook-built`, written when the build exits
    0 and removed before a forced one. A build that fails leaves the copy unbuilt, so the next
    run tries again. One that is built says `built already, at 4f2a91c`.
12. **What a built git dependency itself depends on is not looked at again**, unless `--force`
    is given. It was needed to build it, and it is built.
13. **A git dependency with no `build` script is not mentioned.** That is the ordinary case of
    a repository that commits its data.
14. **`pin` and `update` pin a git dependency from its working copy when there is one**, and
    from the checkout otherwise.
15. **Which commit is built.** The lockfile's, if it names one, since a pin does not move.
    Otherwise what the `rev` means now.
16. **The index lists every script** under `scripts`, sorted by name. The schema already
    allowed it.
17. **A catalog has no `[scripts]`.** A manifest that gives one does not load.
18. **What it says.** One line for each pipeline it runs in, with the directory when that is
    not where the command was given. Pins are mentioned only when something happened, and a
    lockfile is never written without a line that says so.
19. **An update that moves a `git` dependency's commit lets go of what was built at the old
    one.** This changes one case of a rule proposed in 3c (number 7 there: an asset the other
    pipeline "declares and no longer has on disk keeps its pin"). Example: `ref_data` is pinned
    at commit A, with `daily_prices` built there by `run`. `update` moves it to commit B, where
    nothing is built yet. Under the 3c rule the lockfile would then say commit B beside the
    bytes built from A. Nobody else could get those back: a fresh clone builds B, gets other
    bytes, and the pin is lost. And `run` could not fix it, because `run` moves no pin. So the
    pin is removed, `update` says "let go", and the next `run` builds B and pins it. The rule
    is unchanged for a `path` dependency, and for a `git` one whose commit did not move.

**Known gaps in 4a.**

1. **Pinning still reads the folder.** For a `path` dependency, `pin` and `update` copy what
   is there at that moment, and `pin` hashes it to say what has changed. Run while its owner
   is half-way through a rebuild, `update` pins the half-built state. Snapshots (4b) close it.
2. **Refreshing a git dependency's data takes two commands**: `chartbook run --force` builds
   it again, and the pin does not move until `chartbook update`.
3. **Nothing clears old working copies.** A branch that moves leaves one per commit, each with
   whatever its build wrote. `chartbook store gc` does not touch the git cache.
4. **Two runs at once in one working copy** are not kept apart. Two projects of one user that
   depend on the same commit share it.
5. **A `path` dependency of a `git` dependency** is not built, and is looked for beside the
   working copy, where it almost never is. That dependency's build stops at its pin.
6. **On a first run, a `git` dependency is fetched twice**: once to choose the commit to build,
   once by the pin. If the branch moves in between, the pin lands on a commit that was not
   built, and says "not built". The next run builds that commit and pins it.

**Where the design was wrong, or said less than it seemed to.**

1. *"`build` … is what the dependency graph invokes"*, *"`chartbook run [script]` — execute a
   named script across the graph"*, and *"ChartBook's runner is topological order, a process
   pool, an input-addressed cache and a per-asset lock."* ({doc}`asset-graph`, "Running things"
   and "Relationship to orchestrators".) Decided otherwise: a pipeline's dependencies are not
   built from it. The only order left is among a catalog's own pipelines.
2. *"By default it also refreshes `path` pins."* ({doc}`asset-graph`, "Two verbs".) Decided
   otherwise.
3. *"Today the field is documentation-only … choosing script semantics now means a future
   `chartbook run` can execute the value as-is with no format change."*
   ({doc}`toml-format-v2`.) True of the format and not of the values. Nothing ever ran the
   field, so nothing ever checked that it held a command. This repository's own
   `examples/yield_curve` had `build = "module load anaconda3/3.11.4 TeXLive/2023"`: a note
   about the environment. `chartbook run` would have run it and failed. The example now says
   `doit`. Other manifests may hold notes too, and the changelog says so.
4. *"If variants are ever needed … the natural extension is a `[project.build]` table with
   named keys."* ({doc}`toml-format-v2`.) {doc}`asset-graph`, written later, has `[scripts]`.
   `[scripts]` is what is built.
5. *"`chartbook update` — move pins forward to current upstream state, and rebuild what that
   invalidates."* ({doc}`asset-graph`.) `update` rebuilds nothing; the pair is `update`, then
   `run`.
6. *"`chartbook run` pins anything not yet pinned, so neither verb is needed to get started."*
   True as built, for `build`. Any other script pins nothing.
7. *"`build` still means 'render the website' and keeps doing so until `run` exists; the
   rename is one breaking change, made once, in the same release as `run`."*
   ({doc}`asset-graph`.) `run` exists and the rename is 4c. Both are unreleased, so "the same
   release" still holds, and until 4c `chartbook build` and `[scripts] build` mean different
   things.
8. *The `dodo.py` in {doc}`asset-graph` that reads another pipeline's asset at the top of the
   file* failed until the dependency was pinned ("3d, as built"). Under `chartbook run` it
   works, because the pin is made before `doit` starts. Run as plain `doit` in a fresh clone,
   it still fails.
9. *The `Build` record is one per asset, with a `recipe_hash`* ({doc}`asset-graph`,
   {doc}`index-schema`), *and "the graph's nodes are pipelines … ChartBook therefore never
   needs per-asset build recipes"* ({doc}`asset-graph`, "Granularity"). The two do not fit:
   one build makes all of a pipeline's assets. The snapshot settles it as one record for a
   pipeline at a commit, naming each asset's hash.

**Seen while trying it by hand.** A pin is read-only (decided in 3d). A build script that
copies a pinned file with `cp` gets a read-only copy, and cannot write over it on the next
run. Nothing is wrong, and it will surprise someone. Reading the pinned file in place avoids
it.

#### 4b, as built

*Added 2026-10-13.* A pipeline's owner declares a build ready, and that is what others pin.

```console
$ chartbook snapshot                      # in fed_yield_curve, with everything committed
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.

$ chartbook pin                           # in rate_forecast
ftsfr/fed_yield_curve: 3 pinned
  From its snapshot at 4f2a91c, made 2026-10-13 18:22 UTC.
Wrote chartbook.lock.
```

| What | Where |
|---|---|
| Making a snapshot, and refusing with anything uncommitted | `chartbook/snapshot.py`, `make()`, `uncommitted()` |
| Where a folder is in git | `chartbook/snapshot.py`, `code_of()` |
| The newest snapshot at or before the commit a folder is on | `chartbook/snapshot.py`, `newest_for()` |
| One shape for an asset's record, in a snapshot and in a lockfile | `chartbook/snapshot.py`, `asset_record()` |
| Pinning a `path` dependency from a snapshot | `chartbook/lock.py`, `_sync_from_snapshots()` |
| Pinning from the folder, when asked | `chartbook/lock.py`, `pin(from_folder=True)` |
| A snapshot is never cleared | `chartbook/lock.py`, `plan_gc()` |
| The commands | `chartbook/cli.py`: `snapshot`, and `--from-folder` on `pin` and `update` |
| The record's schema | `schemas/chartbook/snapshot/v1.json` |
| The snapshot's commit and time, on a dependency in the index | `chartbook/index.py`, `schemas/chartbook/v1/Pipeline.json` |
| The tests | `tests/test_snapshot.py`; the examples, in `tests/test_integration.py` |

**Decided by the maintainer, 2026-10-13, before it was built:** the model above. In his
answers: yes to the picture as a whole; yes, everything must be committed before a snapshot;
and taking what is in a folder is "only a buried option that is not on by default".

**Not done in 4b, on purpose.** `chartbook snapshot` does not run the build. Old snapshots
are not cleared. Snapshots are not shared between machines. A `git` dependency is pinned as
before, from ChartBook's clean copy of the commit, and does not look for a snapshot.
`chartbook check` still reads a dependency's manifest from its folder.

**Proposed: implemented in 4b, and waiting on the maintainer's yes.**

1. **The command is `chartbook snapshot`**, run in the pipeline, with no argument.
2. **"Everything committed" means the pipeline's own folder.** A changed, staged, deleted or
   new un-ignored file there is refused, and listed. What git ignores does not count, which is
   how built data stays out of it. Other work in the same repository does not count either,
   so one agent's half-finished change does not hold up another pipeline's snapshot. The cost:
   a pipeline that imports code from elsewhere in its repository can be given a label that
   uncommitted work elsewhere makes untrue.
3. **A snapshot is found by commit and by the pipeline's folder in its repository**, not by
   the pipeline's name: `snapshots/<commit>/<folder>/<time>.json`. A commit is the same in
   every clone, so nothing needs to agree on a name.
4. **A `path` dependency follows the branch its folder is on.** `pin` and `update` take the
   newest snapshot at the commit the folder is on or, if that commit has none, at the nearest
   commit before it that has one. Its owner can be several commits past the last build they
   declared ready. A snapshot made on another branch is not found.
5. **One commit can have several snapshots**, told apart by the time they were made, to the
   microsecond. The newest is the one a pin moves to. Making one when nothing has changed
   since the last at that commit makes none.
6. **A dependency is pinned to one snapshot, whole.** `pin` does not take one asset from a
   newer snapshot and leave the rest. This replaces, for a `path` dependency, 3c's "pins what
   has no pin yet: an asset the other pipeline has started to declare".
7. **`pin` says what a newer snapshot would change, and stays.** It no longer hashes anything
   to find out: it compares two records.
8. **`update` drops what the newer snapshot no longer declares, and lets go of what it did
   not build.** The second is the rule of 4a's number 19, for the same reason.
9. **An asset that is declared and not built is in the snapshot without a hash**, and the
   rest is in it all the same, as `pin` already did. A pipeline that has built nothing has
   no snapshot to make.
10. **The lockfile names the snapshot**: its commit in `location.commit`, where a `git`
    dependency's commit already is, and its time in `snapshot`. So the lockfile says which
    code as well as which data, for both kinds of dependency. The index carries both.
11. **With no snapshot, nothing is pinned**, and the message says what the owner has to do.
    `chartbook run` stops there, before the build.
12. **The record is JSON in the index's format**, like the lockfile, with its own schema.
13. **A snapshot's files are stored as a pin's are**: a copy-on-write clone or a copy, never a
    link to the pipeline's own file.
14. **`chartbook store gc` never removes what a snapshot names**, whether or not anything
    pins it yet. A record that cannot be read stops the clearing.
15. **The buried option is `--from-folder`**, on `pin` and `update`, hidden from `--help`.
    It does what both did before 4b. The lockfile then names no commit, and a plain `update`
    afterwards moves back to a snapshot.
16. **Looking at a repository takes no lock** (`GIT_OPTIONAL_LOCKS=0`), so finding a
    snapshot never gets in the way of whoever is working in that folder.
17. **`builds/` in the store stays a name that is kept free.** Records go in `snapshots/`.

**Known gaps in 4b.**

1. **A snapshot takes its owner's word.** It records what is on disk as what the commit
   built. If the owner changed code, committed, and did not rebuild, the label is wrong and
   nothing notices. *(Closed the same day for `chartbook run --snapshot`, which builds first:
   "4b, continued", below. `chartbook snapshot` by itself still takes its owner's word, and
   the record says which of the two made it.)*
2. **Nothing clears old snapshots.** Each is its own copy of the files where the disk has no
   copy-on-write clones, and the store grows with each one. *(Closed 2026-10-13: "Clearing old
   snapshots", below.)*
3. **A snapshot is on one machine.** A colleague, or CI, has none of them. For a `path`
   dependency they make their own in that folder. A shared store is the answer, later.
4. **A lockfile from one machine cannot be put back on another** for a `path` dependency
   unless the same bytes are built there. `pin` reports a pin whose bytes are not in the
   store as lost.
5. **`chartbook check` reads a dependency's manifest from its folder**, as it stands, to see
   that it declares what a model was trained on. It should read it at the pinned commit.
6. **A `git` dependency does not use a snapshot.** If its owner made one at that commit on
   this machine, `chartbook run` still builds the commit again in a clean copy.
7. **The examples need a clean folder.** `cd examples && doit` makes a snapshot of
   `yield_curve`, so it fails, and says why, if that example has been edited and not
   committed.

**Where the design was wrong, or said less than it seemed to.**

1. *"Keep the boring files. `path` stays the real location where a parquet file lives, and
   the store is a cache that links into it."* ({doc}`asset-graph`, "The store".) For the
   pipeline's own folder, still true. For what others read, the store is not a cache: it is
   the only place they read from.
2. *"A cache and a pin are not the same thing … a pinned object is reachable and must never be
   collected, while an unreferenced build result may be."* ({doc}`asset-graph`.) A snapshot is
   a third thing: nothing pins it yet, and it must not be collected, because it was declared
   ready on purpose.
3. *The store's two indexes: "the build record maps input hash → output hash".*
   ({doc}`asset-graph`.) What was built maps a commit to output hashes. The commit is the
   input that people can name and check out; an input hash over code, parameters and tools
   is not built, and the model does not need one.
4. *"`pin` puts back what the store has lost, when the other pipeline still has the same
   bytes"* (3c, proposed 5). For a `path` dependency it no longer can, because it does not
   read the folder. A snapshot is what puts bytes in the store.
5. *"`pin` hashes what is already pinned, to say what has changed upstream"* (3c, proposed
   6), with its note that a remembered hash would make that cheap. For a `path` dependency
   there is nothing to hash any more.

#### 4b, continued: build and snapshot together, and what a snapshot records

*Added 2026-10-13.* The maintainer, on whether `chartbook snapshot` should run the build:
"Running and snapshotting are two separate things that need separate commands. But it's
clear that you often want to run them together." And: "a commit is not enough to pin, since
we need to snapshot .env and environment variables and other config, too, right?"

```console
$ chartbook run --snapshot
ftsfr/fed_yield_curve: build
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
Ran build in 1 pipeline(s).
```

| What | Where |
|---|---|
| Build, then snapshot, with the two checks | `chartbook/run.py`, `run(snapshot=True)` |
| The check that everything is committed | `chartbook/snapshot.py`, `require_committed()` |
| What a snapshot was built with, and from | `chartbook/snapshot.py`, `_built_with()`, `_inputs()` |
| The tests | `tests/test_run.py` (`TestRunThenSnapshot`), `tests/test_snapshot.py` (`TestBuiltWith`) |

**Decided by the maintainer:** they stay two commands. And, asked afterwards with what was
built in front of him: **one spelling is enough** (number 1 below), and **named environment
variables wait** until a real pipeline needs them.

**Proposed: implemented, and waiting on the maintainer's yes.**

1. **One spelling for both together: `chartbook run --snapshot`.** *(Decided, 2026-10-13. He
   had floated two equivalent spellings, that and `chartbook snapshot --run`. One: it reads
   in the order it happens, `run` already has `--force` so `run --force --snapshot` is the
   weekly refresh in one line, and two spellings are two things to document.)*
2. **It checks that everything is committed before it builds**, so nobody is refused after an
   hour, and **again after**: a build that changes a committed file gets no snapshot.
3. **The snapshot records that the build ran in the same command**, `built_with.run`. One
   made by `chartbook snapshot` alone says `false`.
4. **A snapshot that follows a build replaces one of the same bytes that took its owner's
   word.** Otherwise the same bytes make no new snapshot.
5. **A snapshot is of what `build` makes.** `chartbook run test --snapshot` is refused.
6. **In a catalog, each pipeline is built and declared ready in turn**, so one later in the
   catalog pins what an earlier one has just declared ready. A git dependency that is built
   on the way gets no snapshot.
7. **`inputs`: a snapshot says what it was built from.** The dependencies of the pipeline's
   own lockfile, each with its commit, snapshot time and `pinned_hash`. This is the design's
   "hash each input's hash", at the granularity of a pipeline: a snapshot of `rate_forecast`
   names the snapshot of `fed_yield_curve` it read.
8. **`built_with`: a note of the conditions.** The ChartBook, Python and platform versions.
   It explains a difference between two snapshots. No hash covers it, and it does not make
   a build repeatable.
9. **Nothing of a pipeline's `.env`, or of the environment, is recorded.** It holds secrets,
   and a store is something to share. A setting that changes results belongs in a committed
   file, where the commit covers it.

**Not built, by his decision: later.** Recording the values of environment variables that a
pipeline **names** in its manifest as affecting its results, for example
`[snapshot] env = ["START_DATE"]`. Only named ones, so no secret gets in by accident. A
setting that changes results belongs in a committed file until a real pipeline needs more.

**Where the design said less than it seemed to.**

1. *The `Build` record's `tools` and `impure`* ({doc}`index-schema`) are what `built_with` is
   a first, smaller form of. `impure` is not recorded: nothing declares it.
2. *"Make the hashes transitive … hash each input's hash, not its path or name."*
   ({doc}`asset-graph`.) `inputs` records each input's hash. No hash is yet taken *over* the
   inputs, so the chain is recorded and not yet checkable in one step.

#### 4d, as built

*Added 2026-10-13.* A model has versions, and a name can point at one. It is listed after
4c in the table above and was built after it; it is placed here, beside the snapshots it is
made of.

```console
$ chartbook run --snapshot
ftsfr/rate_forecast: build
ftsfr/rate_forecast at 4f2a91c: 1 asset(s) in the store
  model/rate_forecaster: new version 7f3a9c2e41b0
```

```toml
[models.rate_forecaster.aliases]
champion = "7f3a9c2e41b0"
```

| What | Where |
|---|---|
| Every snapshot of a pipeline, on any branch; the versions of one asset; a version's name | `chartbook/snapshot.py`, `history()`, `versions_of()`, `version_name()` |
| A model's scores kept in its snapshot record | `chartbook/snapshot.py`, `make()` |
| `[models.x.aliases]` | `chartbook/manifest.py`, `validate_aliases()` |
| `model/x@7f3a9c2e41b0` and `model/x@champion` resolve | `chartbook/resolve.py`, `_resolve_version()` |
| `chartbook.models.versions()`, `Version` | `chartbook/models.py` |
| Versions and labels on the `Model` record, and on the model's page | `chartbook/index.py`, `chartbook/markdown_generator.py`, `schemas/chartbook/v1/Model.json` |
| A label whose version is not here | `chartbook/check.py`, `check_model_labels()` |
| The tests | `tests/test_model_versions.py` |

**Decided by the maintainer, 2026-10-13, before it was built:**

1. **A version is made by a snapshot**, the first that holds new bytes for the model.
   {doc}`models` proposed every build that changes the model. Tuning a model all afternoon
   makes no versions, and every version has a commit that describes it.
2. **A version is named by the start of its content hash**, with labels as the names people
   use. {doc}`models` proposed `v1`, `v2`, `v3`, and listed their trouble as an open question:
   two branches that each retrain both make a `v4`.

**Not done in 4d, on purpose.** A version of another pipeline's model
(`other:model/x@champion`) is refused: the lockfile pins one snapshot of a dependency, and a
second version of one of its models beside it has no place there yet. Only models have
version names; a dataframe has snapshots and no names for them. Nothing says a model is out
of date when what it was trained on has moved.

**Proposed: implemented in 4d, and waiting on the maintainer's yes.**

1. **A name is twelve digits of the hash**, and more only when two versions of the same model
   would share them. A longer start, the whole hash, and `sha256:` in front all name the same
   version; so does a shorter start of four or more, when typed, if it names only one. *(The
   length was decided by the maintainer, 2026-10-13: twelve, not git's seven, as Docker and
   the Linux kernel use. The whole hash is what is stored. A start that matches two versions
   is refused.)*
2. **A version is looked for in every snapshot of the pipeline, on any branch** of its
   repository. One made on a branch that was never merged is still a version.
3. **A label is looked up before a hash**, and a label may not look like the start of one (four or
   more hex digits), so the two cannot be confused.
4. **A label points at the start of a hash, at least twelve digits.** `chartbook check` warns
   when the version is not on this machine, and does not fail: it may be on another. A label
   that matches two versions is a problem.
5. **A version keeps the model's scores**, read from its metrics file when the snapshot is
   made, so two versions can be compared after the file has been written over. It also has
   the snapshot's commit and `inputs`.
6. **`@` resolves for a pipeline's own models and nothing else.** The plain name stays the
   file in the folder: local references are live, and a version is the one way to ask for
   something that is not.
7. **A snapshot says when it makes a version**: `model/x: new version 7f3a9c2e41b0`.
8. **The index lists a model's versions**, oldest first, and its labels. The page lists them
   newest first. Both are the versions in the store of the machine that built them.
9. **`chartbook.models.versions()`** is the one new function. There is no command that lists
   versions; the page, the index and the snapshot's own line are where they are seen.

**Known gaps in 4d.**

1. **A version is on one machine.** It is in the store that holds its snapshot. A label is in
   the manifest, which is committed, so a label can name a version a colleague does not
   have. A store to share closes it.
2. **The index and the page depend on the machine that built them.** Two machines build
   different `versions` lists from the same commit.
3. **No version of another pipeline's model, no version names for other kinds, no staleness.**
   As above.
4. **Nothing clears old versions.** They are in snapshots, and nothing clears those. *(Closed
   2026-10-13: a version a label points at is kept by `store gc`; one no label names goes
   with its snapshot. "Clearing old snapshots", below.)*

**Where the design was wrong, or said less than it seemed to.**

1. *"Recorded in the pipeline's committed `chartbook.lock` so the numbers are the same on
   every machine."* ({doc}`models`.) A lockfile is what a pipeline *depends on*; its own
   models' versions do not belong in it, and nothing was ever written there. With names
   worked out from the bytes, nothing needs recording for them to agree.
2. *"A team that wants to share model versions points at a shared store."* ({doc}`models`.)
   Still the answer, and still not built. Until it is, "serving code asks for
   `model/x@champion` and gets a path" works on the machine that made the snapshot.
3. *"`@rev` resolves"* in this step's list read as one thing. It is at least three: a version
   of this pipeline's model (built), a version of another pipeline's (not built), and a
   revision of a dataframe or a chart (nothing has asked for one).

#### 4c, as built

*Added 2026-10-13.* Each word means the plain thing.

| Command | Builds the data | Renders the site |
|---|---|---|
| `chartbook run` | Yes | No |
| `chartbook docs` | No | Yes |
| `chartbook build` | Yes | Yes |

| What | Where |
|---|---|
| `chartbook docs`: what `chartbook build` was | `chartbook/cli.py`, `docs()`, `_render_site()` |
| `chartbook build`: run, then docs | `chartbook/cli.py`, `build()` |
| A script is told which pipeline and script it is | `chartbook/run.py`, `execute()`, `running()` |
| The tests | `tests/test_build_command.py` |

**Decided by the maintainer, 2026-10-13:** make the rename now, as designed, and breaking.
"I don't care about backwards compatibility. Let's do the right thing. We can add warning
maybe. But that's as far as I'd go."

**Proposed: implemented in 4c, and waiting on the maintainer's yes.**

1. **`chartbook build` takes exactly the arguments of `chartbook docs`.** It does not take
   `chartbook run`'s `--force`. To rebuild a git dependency and then render: `chartbook run
   --force`, then `chartbook docs`.
2. **With no `build` script, `chartbook build` says so and renders the site.** A project that
   only documents files it already has is not an error.
3. **If the script fails, the site is not rendered**, and the exit code is the script's.
4. **In a catalog, the script is run in each of the catalog's pipelines**, and then the
   catalog's site is rendered.
5. **The one protection, and the only compatibility.** A script is told which pipeline and
   script it is, in two environment variables (`CHARTBOOK_RUN_DIR`, `CHARTBOOK_RUN_SCRIPT`).
   `chartbook build` called from inside the build script it is running renders the site and
   prints a warning that says to use `chartbook docs`. `chartbook run` called from inside the
   script it is running is refused. Without this, an old build script would run itself
   without end.
6. **`chartbook catalog build` is unchanged.** It renders the global catalog's site and runs
   no script.

**Known gaps in 4c.**

1. **The project template still says `chartbook build`.** It is in another repository
   (`cookiecutter_chartbook`), which this work does not touch. Its `dodo.py` needs the
   one-line change before this is released, or every new project starts with the warning.
   *(Closed the same day another way: the template was moved into this repository, and
   says `chartbook docs`. The old repository is left as it is, for the released versions
   that render it. "The project template, moved in", below.)*
2. **An old `dodo.py` started with plain `doit`** runs its own build a second time, nested,
   before the warning stops it, and may trip over doit's own lock on its database. The fix is
   the one-line change.
3. **A build script that renders the site itself, as the examples' do, has it rendered
   twice** by `chartbook build`. Taking that step out of a build script means plain `doit` no
   longer makes the site.
4. **`chartbook catalog build` now disagrees with `chartbook build`** about what "build"
   means. What it should be called is not settled.

**Where the design said less than it seemed to.**

1. *"The rename is one breaking change, made once."* ({doc}`asset-graph`.) It did not say
   that the build script of every existing pipeline calls `chartbook build`, so that under
   its new meaning the command runs the script that called it.
2. *"`chartbook build` — make everything current: data, then site."* Most build scripts
   already render the site as their last step. So "data, then site" is, for now, "data and
   site, then site".

#### Clearing old snapshots

*Added 2026-10-13. Built after step 4, on the maintainer's instruction to go on building and
decide the order myself; this was the first known gap worth closing, because a nightly
`chartbook run --snapshot` on a disk without copy-on-write clones fills it.*

```console
$ chartbook store gc --dry-run
Kept: 4 snapshot(s), naming 9 object(s): 1 because a lockfile pins it, 2 because it is the newest of its pipeline, 1 because it was made in the last 30 days
Would remove 6 snapshot(s):
  ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: nothing pins it, it is not the newest, and it is older than 30 days
```

| What | Where |
|---|---|
| Which snapshots are kept, and why | `chartbook/snapshot.py`, `plan_removals()` |
| The folder a snapshot was made from, noted beside the records | `chartbook/snapshot.py`, `_note_origin()`, `origins()` |
| Labels read from that folder's manifest | `chartbook/snapshot.py`, `_labels_in()` |
| Removing a record, then what only it named | `chartbook/lock.py`, `plan_gc()`, `run_gc()`; `chartbook/snapshot.py`, `remove()` |
| The command | `chartbook/cli.py`, `store gc --keep-days` |
| The tests | `tests/test_snapshot.py`, `TestClearingOldSnapshots` |

**Proposed: implemented, and waiting on the maintainer's yes.** All of it; the maintainer
asked not to be consulted on rules of this size.

1. **A snapshot is kept if a lockfile pins it, if it is the newest of its pipeline or the
   newest a branch or tag can pin from, if a label points at a model version in it, or if it
   was made in the last 30 days.** Otherwise it may be removed. The rules are tried in that
   order, and the first that holds is the reason the command gives. *(The branch rule was
   added by the third review, below: `pin` chooses by commit ancestry, so a release branch's
   last snapshot is what its users pin, and the plain "newest" would have removed it.)*
2. **Thirty days.** Long enough to come back from a holiday to; short enough that a nightly
   build does not fill a disk. `--keep-days` moves it, down to zero.
3. **"The newest of its pipeline" is by pipeline ID and folder within its repository**,
   which is what the store can tell without a repository to hand. A pipeline that renames
   itself becomes two pipelines to this rule for as long as both have snapshots.
4. **The store notes where a snapshot was made from**, in a file `origins` beside the
   pipeline's records at that commit: one repository folder per line. It is not a record,
   has no `.json`, and is not shared. It is how `gc` finds the manifest whose labels say
   which versions to keep.
5. **Labels are read from that manifest as it is now, committed or not.** A label is what
   someone is relying on now. A folder that is gone, or a manifest that cannot be read, says
   nothing, and the other three rules still hold.
6. **A lockfile that cannot be found keeps any snapshot that holds an object it named.** That
   is as much as is known about it.
7. **Removing a snapshot removes its record; its objects go by the existing rule**, in the
   same run, when nothing else names them. An object stored in the last hour is spared, as
   before, so the run that removes a record may leave its objects for the next.
8. **The last record at a commit takes its folder and its `origins` note with it.**
9. **Nothing is removed if any record cannot be read**, as for a lockfile.
10. **The plan is made again when the yes comes**, and only what both plans say may go is
    removed. A `pin` that landed while someone was deciding is honoured. *(Third review.)*
11. **A label shorter than a version's name keeps nothing.** `champion = ""` would otherwise
    match every version. Only what `[models.x.aliases]` accepts, twelve or more hex digits,
    is read. *(Third review.)*
12. **The last record at a commit leaves a half-written one alone.** Only the `origins` note
    goes with it, and the folder if it is then empty. *(Third review.)*

**Known gaps.**

1. **A label in a manifest that was never a snapshot's origin is not seen.** A clone that
   pins nothing and makes no snapshots can label a version that `gc` on this machine then
   removes. `chartbook check` there says the version is not on this machine.
2. **Git working copies are still never cleared.** `~/.chartbook/git/work/` grows by one copy
   per commit built.

**Where the design said less than it seemed to.** *"A recorded version is reachable, so
`chartbook store gc` never collects it."* ({doc}`models`.) Every version would then be kept
for ever, and {doc}`models` itself lists retention as an open question ("a model retrained
nightly makes 365 a year … probably a per-model `keep = N`"). As built, a labelled version is
kept and an unlabelled one goes with its snapshot after 30 days, which answers the question
without a new field.

#### What two adversarial reviews found, and what was done

*Added 2026-10-13.* After the step 4 pull requests were merged, two sub-agents reviewed
`main` with no knowledge of the builder's conclusions: one for correctness and races, one for
safety. They found twenty-six things between them. Each is in the changelog under "Fixed", and
the ones that change a rule are here.

**Changed rules, all *proposed*.**

1. **A pipeline that is only read gives up nothing but its own files.** A git dependency's
   manifest, or a pipeline being snapshotted, may declare an absolute path, a `..`, or a
   symlink that reaches outside; every declared path is followed to where it really is
   (`chartbook.hashing.escapes`), and one that reaches out is `outside`, not pinned, and a
   problem. This is the boundary 3e implied and did not enforce: `pin` is safe, `run` is
   trust. A `path` dependency pinned `--from-folder` is not checked: it is a folder on this
   disk that the user chose.
2. **A snapshot is pinned whole or not at all.** An update to a snapshot with an object the
   store has lost moves nothing. 4a's rule 19 and 4b's rule 8 said a lockfile must never name
   one commit beside another's bytes; this was the case that could still do it.
3. **The lockfile ChartBook writes does not count as an uncommitted change** for
   `run --snapshot`, before or after the build. The snapshot's `inputs` record what it says.
   A build that makes a commit gets no snapshot.
4. **The recursion guard sees the whole chain of scripts**, in `CHARTBOOK_RUN_STACK`, and
   comes before the pin.
5. **A version is found at any commit the repository still has**, asked of git's object store,
   so an amended-away commit keeps its versions until git prunes it.
6. **Names in the store carry a short hash when they would otherwise collide**: a clone's
   folder with a port or a cleaned character, a snapshot folder with `--` or `_top`.

**The third review** read the two commits of this pull request before they were merged, and
found twelve more. The two that mattered: the gc plan was made before the "yes" and run
after, so a `pin` landing in between lost its only bytes (now the plan is made again on the
yes); and the lockfile exemption for `run --snapshot` read `git status` as a terminal would,
so a folder with a space or an accent in its name was refused all the same (now `-z`). Also:
the recursion guard's stack is JSON, so a `:` or a tab in a folder's name does not break it;
a release branch's last snapshot is kept; a too-short label keeps nothing; a path that
reaches out is refused before the build; `remove()` leaves another process's half-written
record alone; `pin --from-folder` says `relocated`; an `origins` line that is not an absolute
folder says nothing.

**Found and left, with the reason.**

- *Two `chartbook snapshot` at once make two identical snapshots.* Cosmetic; the newer wins.
- *A snapshot that takes over an hour to store can lose an early object to a concurrent `gc`.*
  Improbable; a store-wide lock is the fix, and is not built.
- *A shallow clone cannot see snapshots beyond its depth*, and the message blames the owner.
- *`chartbook init` renders whatever is on `main`*, not the installed version; needs tags.
- *No timeouts on git calls.* Prompts are off; a GUI credential helper could still block.
- *A lockfile that cannot be found keeps every snapshot that shares one object with it*, for
  as long as it is missing. Conservative; the command now points at `--forget-missing`.
- *Store names made before the hashing change are not found again.* Nothing is released.

#### 4e: loading one column. Decided against

*Added 2026-10-13.* This step's list ends with *"Parts: `dataframe#series` resolves for
`data.load()`."* Asked what `data.load("treasury_rates#dgs10")` should hand back, the
maintainer answered a larger question:

> "I don't think I want to develop a domain-specific language. I don't want to recommend that
> people load data this way. At this point, they write an SQL an chartbook passes through, or
> access tha path to the parquet and pass over to polars. I don't want chartbook's scope to
> get too large here."

**Decided.**

1. **A reference never selects data.** Not a column, not a date range, not rows. ChartBook
   says where a dataframe is, what it is and which copy you get.
2. **There are two ways to read one**: SQL that ChartBook passes through ({doc}`data-access`),
   or `data.path()` handed to polars or to anything else. `data.load()` of a whole dataframe
   stays, as the short form of the second.
3. **A series address stays what it was first for**: a name to hang documentation, units, a
   frequency and an index record on. `[dataframes.x.series.y]` and the `Series` records are
   unchanged.

**What was built for it.** Only the message. `data.load("treasury_rates#dgs10")`,
`data.path(…)` and `chartbook path …` still refuse a `#`. They said "reserved syntax and not
yet supported", which promised something that is not coming. They now say what the address is
for and what to do instead. `chartbook/resolve.py`, `parse_declared_ref(resolving=True)`.

**Proposed, and waiting on the maintainer's yes.**

1. **A column named in a manifest still says "not yet".** `trained_on =
   ["treasury_rates#dgs10"]` would say which column a model was trained on. That is a
   statement about lineage, loads nothing, and {doc}`index-schema` has a chart's `inputs` name
   a series. It stays reserved, with its old message.
2. **A file inside a model, `model/x#weights.pt`, is not built either** (slice M2 of
   {doc}`models`), by the same reasoning: it is `models.path("x") / "weights.pt"`, and the
   message now says so. This one is the builder's reading of the decision, not the
   maintainer's words.

**Where the design said something else.** *"The reference grammar has an optional segment for
this … `ftsfr/fed_yield_curve:treasury_rates#dgs10`"* ({doc}`asset-graph`) and the table in
{doc}`references` that has `treasury_rates#dgs10` mean "the series `dgs10` of that
dataframe". Both stand, as addresses. What does not stand is this step's bullet, and "M2.
Parts" in {doc}`models` as something to resolve.

#### The project template, moved in

*Added 2026-10-13. Decided by the maintainer the same day:* "Should we move the project
template to this repository? Maybe, right?" and then yes.

`chartbook init` renders `template/`, a folder of this repository. It rendered a separate
repository, `cookiecutter_chartbook`.

| What | Where |
|---|---|
| The template | `template/`: `cookiecutter.json`, `hooks/`, `{{cookiecutter.project_slug}}/` |
| Where `chartbook init` gets it | `chartbook/scaffold.py`, `template_command()` |
| The template's own tests, and a build of a fresh project | `tests/test_template.py` |

**Why.** The rename of 4c showed it: the template called a command that had changed its
meaning, in a repository this work could not reach, and no test here could have noticed,
because the tests of `chartbook init` stand in for the download. Now a command and the
template that uses it change in one pull request, and a test renders a project and builds it
with the ChartBook of the same commit.

**Proposed: implemented, and waiting on the maintainer's yes.**

1. **It is a folder at the top of the repository, `template/`**, not inside the package. It is
   fetched from git by cruft, as before, so it does not need to be installed.
2. **A project is still made with cruft**, and its `.cruft.json` records this repository and
   the `template` folder, so `cruft update` goes on working for new projects. The template's
   own README calls that one of its main benefits.
3. **The template was copied, not merged in with its history.** It came from
   `cookiecutter_chartbook` at commit `a67eeea`, and that is written here and in the test
   file. The old repository has the history.
4. **Four changes on the way in**, each needed by something built in this step: the build
   file renders with `chartbook docs -f`; the manifest says `[scripts] build = "doit"` where
   it had a note about which modules to load; its copy of the skill is the package's, kept
   so by a test; its pixi file does not ask for the removed `[all]` extra. Two stale lines
   that told people to build the site with `jupyter-book` now say `chartbook docs -f`.
5. **Not brought over:** the generated `example/` project, which was a rendered copy kept
   for reference and has to be regenerated on every change (the test that builds a fresh
   project does that job here); the template repository's own build file and CI workflow,
   whose jobs the tests here do; and its editor rules.
6. **The old repository is left exactly as it is.** Released versions of ChartBook render
   it, and there `chartbook build` still means "render the site". Changing it would break
   them. Nothing in this work touches it.
7. **The skill now has three copies kept the same by hand and checked by a test**: the
   package's, which is the source; `.claude/skills/chartbook/`; and the template's.

**Known gaps.**

1. **A project gets the template as it is on `main` today, whatever ChartBook is installed.**
   That was true before the move and still is. Someone with an older ChartBook who runs
   `chartbook init` after a later change to the template can get a build file that uses a
   command they do not have. Pinning what `chartbook init` fetches to the installed version
   needs releases to be tagged in git, which they are not. *Proposed:* tag them, and have
   `chartbook init` ask cruft for that tag.
2. **`chartbook init` still needs the network.**
3. **Existing projects point at the old repository.** `cruft update` in them keeps reading
   it until they are re-linked: `cruft link https://github.com/backofficedev/chartbook
   --directory template`.
4. **A project straight from the template fails `chartbook check` on one thing**: it has no
   `repo_url`, because it has no git remote yet. `chartbook init --github` gives it one.
   This was so before the move; the new test is what showed it.
5. **The template asks for `chartbook>=0.1.0`.** A project made from it needs the release
   that has `chartbook docs`. The number is the release's to set, and is not set here.

### Step 5. Data in databases

**Goal:** a dataframe can be a table, and `data.load()` does not change.

This is {doc}`data-access` and GitHub issue 9. It depends only on step 1 (it changes the
`Dataframe` record's `location`), so it can be done any time after that, by someone else, in
parallel with steps 2 to 4.

#### Step 5, as built

*Added 2026-10-13.* Built after step 4, as the second of the two ways the maintainer said data
should be read: SQL that ChartBook passes through, or a path handed to polars.

```toml
[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/yield_curve.duckdb"

[dataframes.yield_slopes]
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope_10y_2y from fed_yield_curve"
```

| What | Where |
|---|---|
| `[sources]`, and a dataframe's `table` or `query` | `chartbook/manifest.py`, `validate_sources()`, `validate_dataframe_location()` |
| The two new location kinds | `chartbook/resolve.py`, `TableLocation`, `QueryLocation`, `_resolve_in_source()` |
| The engines: parquet, and DuckDB | `chartbook/backends.py` |
| `data.sql()`, `data.ref()`, `data.connect()`; `load()` of a table or query | `chartbook/data.py` |
| Where a machine keeps credentials | `chartbook/backends.py`, `source_url()` |
| The index: `location` kinds, `definition_hash`, columns from the engine | `chartbook/index.py`, `schemas/chartbook/v1/Dataframe.json` |
| The page | `chartbook/markdown_generator.py`, `_source_glimpse()` |
| `check`: a DuckDB file not built | `chartbook/check.py`, `check_sources()` |
| The example | `examples/yield_curve`: `yield_slopes`, `src/build_duckdb.py` |
| The tests | `tests/test_data_access.py` |

**Built as designed.** The manifest shape, the four Python calls, the rule that SQL is never
parsed, the credential order, the typed `location`, `definition_hash` in place of a content
hash, read-only connections, DuckDB as the engine and the fallback, and the worked example.

**Proposed: where the design was silent or is departed from.**

1. **Cross-pipeline references work in `data.sql()` and `data.ref()` for file dataframes**, as
   the pinned copy. The design put that in a later phase; the resolution chain exists, so it
   costs nothing. A table or query of another pipeline is not pinned (a snapshot holds files)
   and cannot be read across pipelines; the known gap.
2. **A query names one source.** The design's mixed-source rule (register each foreign table in
   DuckDB first) is not built: with DuckDB the only engine, the case is two DuckDB files, and
   the honest answer is `ATTACH`, which the user can do through `data.connect()`. A query
   that names two sources is refused and says so.
3. **`duckdb` is a dependency of `chartbook`**, not an extra, by the one-install rule.
4. **A `url` with credentials in it does not load.** The design said "no credentials, ever";
   the loader enforces it.
5. **An unknown backend is refused by name.** No plugin seam yet: DuckDB is the second
   implementation after parquet, and the rule is three.
6. **`data.load()` of a table or query returns a LazyFrame that DuckDB backs**, through one
   connection per URL kept for the process. Collecting it runs the query.
7. **The default policy's `path` requirement is met by a `table` or a `query`.** The rule
   asks where the dataframe is; a source answers.
8. **`check` reports a DuckDB file that is not built**, and skips that with `--skip-outputs`,
   as for any output. It does not connect.
9. **The page is read from the engine when the site is built**: columns, row count, first
   five rows. A source that cannot be read gets a page that says so.

**Known gaps.** A table or query is not pinned and not in a snapshot, so it is not reproducible
across time or pipelines the way a file is. Only DuckDB. One source per query. The DuckDB
connection is opened read-only, which a user can get round with their own `duckdb.connect`;
ChartBook does not police the engine.


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
| 2026-10-13 | `chartbook run` builds a `git` dependency, in a writable copy of its checkout, once for a commit, and its built data is pinned from there. `--force` builds it again: data is refreshed on purpose | Step 4 above, "4a, as built" |
| 2026-10-13 | A pipeline never reads, hashes or builds in a folder it depends on. `chartbook run` builds the pipeline it is run in | Step 4 above, "The snapshot model" |
| 2026-10-13 | A snapshot is every asset a pipeline declares, as built at one commit, in the store. Its owner makes it on purpose, and only with everything committed. `pin` and `update` choose among snapshots | Step 4 above, "The snapshot model" |
| 2026-10-13 | Taking whatever is in a folder stays possible only as an option that is off by default and out of the way | Step 4 above, "The snapshot model" |
| 2026-10-13 | The purpose: people and agents work on different pipelines in parallel. The store is the read-only middle they all depend on, updated slowly and on purpose | Step 4 above, "The snapshot model" |
| 2026-10-13 | Step 4 is built in parts, one pull request each, stacked | Step 4 above |
| 2026-10-13 | A version of a model is made by a snapshot: the first that holds new bytes for it. Not by every build | Step 4 above, "4d, as built"; {doc}`models` |
| 2026-10-13 | A version is named by the start of its content hash: twelve digits, with the whole hash stored. The names people use are labels in the manifest, `[models.x.aliases]` | Step 4 above, "4d, as built"; {doc}`models` |
| 2026-10-13 | Building and making a snapshot together has one spelling, `chartbook run --snapshot`. Recording named environment variables in a snapshot waits until a pipeline needs it | Step 4 above, "4b, continued" |
| 2026-10-13 | A reference never selects data. No language for loading: SQL passed through, or `data.path()` to polars. `data.load("dataframe#series")` will not be built; a series address is for documentation | Step 4 above, "4e" |
| 2026-10-13 | The project template moves into this repository, as `template/` | Step 4 above, "The project template, moved in" |
| 2026-10-13 | The command rename is made now and is breaking: `chartbook docs` renders the site, `chartbook build` runs the build script and then renders. No compatibility beyond a warning | Step 4 above, "4c, as built" |
| 2026-10-13 | No backwards compatibility in this work: the right design, even if it breaks, with a warning at most. The order of the remaining work is the builder's to choose | Step 4 above, "4c, as built" |

## Open questions, collected

Each is explained where it lives.

- For model versions: one of another pipeline's model, versions that travel between machines,
  and saying when a model is out of date. Retention is answered by "Clearing old snapshots". How they are named and what makes one is
  decided. ({doc}`models`; step 4 above, "4d, as built")
- Whether dataframes and charts should still be *required* to have a write-up, or only strongly
  recommended, as models are. ({doc}`models`, "Decided while building it")
- Whether a pipeline's own `[policy]` table is wanted. It is honoured today, as a *proposed*
  answer to a crash. ({doc}`toml-format-v2`, "Since this was written")
- The things settled while building declared dependencies (twelve), the store (ten) and
  pinning (fourteen), cross-pipeline references (eleven) and `git` dependencies (twelve), each
  listed as *proposed* under its "as built" heading. (Step 3 above)
- The nineteen things settled while building `chartbook run`, and the *proposed* "Done when"
  that replaces step 4's. (Step 4 above, "4a, as built" and "The snapshot model")
- The seventeen things settled while building snapshots, and its known gaps. Two were
  answered the same day: `chartbook run --snapshot` builds first, and "Clearing old
  snapshots" says how old ones go. (Step 4 above, "4b, as built")
- `--frozen`, for CI: what it checks, and when it is built. (Step 4 above)
- For data in a database: when a second engine is wanted and the backend contract is
  extracted; whether a table-backed dataframe can be pinned, by hash of a snapshot of its
  rows or not at all. (Step 5 above)
- What `chartbook catalog build` should be called now that `chartbook build` runs a build
  script, and whether a build script should still render the site itself. (Step 4 above, "4c,
  as built")
- A shared store, as a second way for a `git` dependency's built data to get here. The first
  is built: `chartbook run` builds it. (Step 4 above, "4a, as built")
- How a chart says it was made from another pipeline's data. (Step 3 above)
- Whether the site should render from the index, and when. (Step 6)
- `plotting.line()` and its siblings can only use the two built-in backends, although third
  parties can register others. ({doc}`../guide/plotting-backends`)
- The project template's CI should run `chartbook check --skip-outputs`, once 0.2.0 is on PyPI.
