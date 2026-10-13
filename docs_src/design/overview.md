# Design: start here

```{note}
The entry point to the design documents. It is written for someone, or some agent, who has
never seen this project and has to continue building it. It says what ChartBook is, the words
it uses, what is built, what to build next and in what order, and where every decision is
written down.

Last revised 2026-10-12, after version 0.2.0, the index, declared models, and the first two
of five parts of step 3: declared dependencies, and the store.
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
| **store** | A local folder of files named by their hash, used for caching and pinning. Built, and not used by anything yet ({doc}`asset-graph`) |
| **object** | One asset in the store: a directory named by the asset's content hash, holding its files under their own names |
| **dependency** | Another pipeline that this one reads from, declared in `[dependencies]`: a name, and where to find it (`path` or `git`) |
| **resolution chain** | The order in which a pipeline's location is looked for: `[dependencies]`, then the catalog. One function, `chartbook.resolve.locate_pipeline` |
| **lockfile** | `chartbook.lock`: the exact versions of upstream assets a project uses. Planned |
| **pin** | To freeze which version of an upstream asset a project reads |
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
| 3 | {doc}`references` | How an asset is addressed | Parser built; local resolution built |
| 4 | {doc}`asset-graph` | Dependencies, pinning, the store, build records, what ChartBook will not do | Declared dependencies (3a) and the store (3b) built. **Next to build**: pinning (3c) |
| 5 | {doc}`index-schema` | The index file, record by record | First implementation built |
| 6 | {doc}`models` | Models as assets | First slice built: declared models |
| 7 | {doc}`data-access` | Dataframes that live in a database | Designed, not built |

For how the existing build works, read {doc}`../guide/how-the-build-works`. For every command
and field, {doc}`../reference/cli` and {doc}`../reference/configuration`.

## What is built

As of 0.2.0, plus the index, declared models, declared dependencies and the store, which came
after it.

| Capability | Where | Notes |
|---|---|---|
| Manifest format v2, pipeline IDs, catalogs, policy | `manifest.py`, `identity.py` | `repo_url` defaults to the git remote |
| The documentation site | `build_docs.py`, `markdown_generator.py`, `docs_src_pipeline/`, `docs_src_catalog/` | Two stages: write Markdown into `_docs/`, then run Sphinx |
| Incremental builds and `--watch` | `incremental.py` | A state file of file sizes and times. No server. Catalog builds are incremental by default |
| `chartbook check`, the CI gate | `check.py` | Required fields, broken paths, expiring licenses. `--skip-outputs` for CI that does not build data |
| The reference grammar | `refs.py` | All of it parses |
| Resolving local references | `resolve.py`, `assets.py`, `data.py`, `chartbook path` | One resolver, typed locations |
| The index, `index.json` | `index.py`, `hashing.py`, `schemas/` | Written by every build, beside the HTML. One hash rule; hashes cached in the build directory |
| Series tables | `manifest.py` (`validate_series`) | `[dataframes.x.series.y]` documents a column. In the index; not on pages yet |
| Models | `models.py`, `manifest.py` (`validate_models`), `markdown_generator.py` (`generate_model_docs`) | `[models.x]`, `chartbook.models.path()`, a page and an index record per model. No versions yet |
| Declared dependencies | `manifest.py` (`validate_dependencies`), `resolve.py` (`locate_pipeline`), `check.py` (`check_dependencies`) | `[dependencies]`, with `path` or `git`. One resolution chain. In the index, and checked. Nothing is fetched or pinned, and `pipeline:asset` does not resolve yet |
| The store | `store.py`, `config.py` (`get_store_path`), `chartbook store verify` | Objects named by content hash, behind `has`, `get`, `put`, `delete`. Four kinds of link. Nothing uses it yet |
| Loading a dataframe through a catalog | `data.py` | `data.load(pipeline=…, dataframe=…)`. The older, two-argument form. It enters the resolution chain at the catalog and does not read `[dependencies]` |
| Scratch directory | `data.scratch()` | `<pipeline>/_data/_scratch/` |
| Freshness lines on pages | `markdown_generator.py`, `chartbook-freshness.js` | "Data updated 2 days ago", computed in the browser |
| Data glimpses | `create_data_glimpses.py` | Reads the manifest, not `dodo.py` |
| Scaffolding | `scaffold.py`, `chartbook init --git/--github` | Renders the cookiecutter template |
| Plotting helpers and backends | `plotting/` | The one real plugin system. See {doc}`../guide/plotting-backends` |
| Reserved for later, and refused | `refs.py`, `resolve.py`, `identity.py`, `cli.py` | Cross-pipeline references, `#part`, `@rev`, registry prefixes, `chartbook push` |

Not built: the lockfile, pinning, `chartbook store gc`, fetching a `git` dependency, build records,
`chartbook run`, `[scripts]`, model versions, `[sources]` and SQL access, any export, and
anything that *reads* the index.

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
| **3c** | **Pinning.** `chartbook.lock`, written in the index's record schemas. `chartbook pin` snapshots each dependency's declared assets into the store and records their hashes. `chartbook update` moves pins forward. `chartbook store gc`, with the lockfile as its roots | A project can freeze what it depends on, and see in a diff when that changes | References still do not resolve across pipelines |
| **3d** | **Cross-pipeline references resolve.** `assets.path("pipeline:asset")`, `data.path`, `chartbook path` and `data.load("pipeline:asset")` resolve through the lockfile into the store, never to the upstream's working directory. Loading from an undeclared pipeline fails and says what to add. A model's cross-pipeline `trained_on` is recorded by pinned hash. A second example pipeline, `examples/rate_forecast`, whose model is trained on `yield_curve`'s data | **The payoff.** The case in the box above works end to end | `git` dependencies |
| **3e** | **`git` dependencies.** `{ git = "…", rev = "…" }`: fetch at a revision into a cache, then as for `path` | A dependency that is not on your disk | — |

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

#### Answers to the open questions

*The maintainer answered five of these on 2026-10-12, after 3a. Those are marked **decided**.
The other two are still the recommendation of whoever built 3a, marked **proposed**, and need a
yes before 3d and 3e.*

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

6. **A `git` dependency. Proposed.** Clone once into `~/.chartbook/git/`, fetch on `update`,
   and check the wanted commit out into a directory beside it. From there it is a `path`
   dependency. The lockfile records the full commit hash that `rev` meant when it was pinned.

   The thing to decide first: a fresh clone has the upstream's *code*, not its data, because
   built data is usually git-ignored. So in 3e a `git` dependency can only be pinned if the
   upstream commits its outputs. Otherwise it needs step 4 (run the upstream's `build`) or a
   shared store to download from. 3e should say so plainly and not pretend otherwise.

7. **`data.load("pipeline:asset")`. Proposed.** Add it in 3d. `data.load("treasury_rates")`
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
| 2026-10-12 | Hashing a directory skips `.DS_Store`, `Thumbs.db`, `desktop.ini` and `._*`, and nothing else | "Answers to the open questions", above; {doc}`index-schema` once built |

## Open questions, collected

Each is explained where it lives.

- How `@rev` is looked up; how model versions are numbered across branches; which builds make a
  version; retention. ({doc}`references`, {doc}`models`)
- Whether dataframes and charts should still be *required* to have a write-up, or only strongly
  recommended, as models are. ({doc}`models`, "Decided while building it")
- Whether a pipeline's own `[policy]` table is wanted. It is honoured today, as a *proposed*
  answer to a crash. ({doc}`toml-format-v2`, "Since this was written")
- The twelve things settled while building declared dependencies, and the two answers still
  proposed: how a `git` dependency is fetched, and `data.load("pipeline:asset")`. (Step 3 above)
- How a chart says it was made from another pipeline's data. (Step 3 above)
- Whether the site should render from the index, and when. (Step 6)
- `plotting.line()` and its siblings can only use the two built-in backends, although third
  parties can register others. ({doc}`../guide/plotting-backends`)
- The project template's CI should run `chartbook check --skip-outputs`, once 0.2.0 is on PyPI.
