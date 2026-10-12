# Design: start here

```{note}
The entry point to the design documents. It is written for someone, or some agent, who has
never seen this project and has to continue building it. It says what ChartBook is, the words
it uses, what is built, what to build next and in what order, and where every decision is
written down.

Last revised 2026-10-12, for version 0.2.0.
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
    model                   …:model/rate_forecaster        a trained model (planned)

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
| **front door** | A Python module that hands out one kind of asset: `chartbook.data` for dataframes, `chartbook.assets` for any kind |
| **location** | Where an asset physically is. A file today; a database table later ({doc}`data-access`) |
| **index** | One JSON file describing everything a catalog contains. A build product. Planned ({doc}`index-schema`) |
| **record** | One entry in the index. Each has a `kind` (`Dataframe`, `Chart`, …) and a `version` |
| **store** | A local folder of files named by their hash, used for caching and pinning. Planned ({doc}`asset-graph`) |
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

## The documents, and the order to read them

| Order | Document | What it settles | State |
|---|---|---|---|
| 1 | This page | The map | |
| 2 | {doc}`toml-format-v2` | The manifest: tables, fields, pipeline IDs, catalogs, policy | Built |
| 3 | {doc}`references` | How an asset is addressed | Parser built; local resolution built |
| 4 | {doc}`asset-graph` | Dependencies, pinning, the store, build records, what ChartBook will not do | Designed, not built |
| 5 | {doc}`index-schema` | The index file, record by record | Designed, not built. **Next to build** |
| 6 | {doc}`models` | Models as assets | Direction accepted, not built |
| 7 | {doc}`data-access` | Dataframes that live in a database | Designed, not built |

For how the existing build works, read {doc}`../guide/how-the-build-works`. For every command
and field, {doc}`../reference/cli` and {doc}`../reference/configuration`.

## What is built

As of 0.2.0.

| Capability | Where | Notes |
|---|---|---|
| Manifest format v2, pipeline IDs, catalogs, policy | `manifest.py`, `identity.py` | `repo_url` defaults to the git remote |
| The documentation site | `build_docs.py`, `markdown_generator.py`, `docs_src_pipeline/`, `docs_src_catalog/` | Two stages: write Markdown into `_docs/`, then run Sphinx |
| Incremental builds and `--watch` | `incremental.py` | A state file of file sizes and times. No server. Catalog builds are incremental by default |
| `chartbook check`, the CI gate | `check.py` | Required fields, broken paths, expiring licenses. `--skip-outputs` for CI that does not build data |
| The reference grammar | `refs.py` | All of it parses |
| Resolving local references | `resolve.py`, `assets.py`, `data.py`, `chartbook path` | One resolver, typed locations |
| Loading a dataframe through a catalog | `data.py` | `data.load(pipeline=…, dataframe=…)`. The older, two-argument form |
| Scratch directory | `data.scratch()` | `<pipeline>/_data/_scratch/` |
| Freshness lines on pages | `markdown_generator.py`, `chartbook-freshness.js` | "Data updated 2 days ago", computed in the browser |
| Data glimpses | `create_data_glimpses.py` | Reads the manifest, not `dodo.py` |
| Scaffolding | `scaffold.py`, `chartbook init --git/--github` | Renders the cookiecutter template |
| Plotting helpers and backends | `plotting/` | The one real plugin system. See {doc}`../guide/plotting-backends` |
| Reserved for later, and refused | `refs.py`, `resolve.py`, `identity.py`, `cli.py` | Cross-pipeline references, `#part`, `@rev`, registry prefixes, `model/…`, `chartbook push` |

Not built: the index, `[dependencies]`, the lockfile, the store, pinning, build records,
`chartbook run`, `[scripts]`, `[models]`, `[sources]` and SQL access, any export.

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

### Step 1. The index

**Goal:** `chartbook build` also writes one JSON file that describes everything.

- Read {doc}`index-schema` whole. It is the specification.
- A new module (suggested: `chartbook/index.py`) that takes a loaded manifest and returns the
  records: `Catalog`, `Pipeline`, `Dataframe`, `Series`, `Chart`, `Notebook`, `Note`.
- Every asset record has a fully qualified `id` and a structured `ref`, both made from an
  `AssetRef`. Never build an ID by joining strings.
- A new module for hashing (suggested: `chartbook/hashing.py`): the hash of a file, of a glob
  and of a directory. There must be exactly one. Cache results by file size and time, because
  data files are large and builds are frequent.
- `columns` on each `Dataframe` record, read from the parquet schema.
- Series: teach the manifest loader the `[dataframes.x.series.y]` table ({ref}`series-addressing`),
  and write a `Series` record per value column, `declared: true` where a table documents it.
- JSON Schemas under `schemas/chartbook/v1/`, one per record kind, and a test that every
  generated record validates.
- Leave `chartbook ls` alone. It exists and reads the manifests; moving it onto the index is
  part of step 6.
- Leave out for now: `Build` records, `dependencies`, `built_by`, and `inputs` beyond what a
  chart's `dataframe` field already says.

**Done when:** `chartbook build` in `examples/catalog` writes an index that validates against
the schemas, lists every asset of both example pipelines with a hash, and is identical when the
build is run twice (apart from `generated_at`).

**Do not** make the site render *from* the index in this step. That is a later, separate change;
doing both at once makes neither reviewable.

### Step 2. Declared models

**Goal:** a pipeline can declare a model and get a page for it.

This is slice M1 of {doc}`models`, which lists exactly what to build and gives a worked example
that doubles as the acceptance test. No versions yet.

### Step 3. Dependencies, the lockfile and the store

**Goal:** `data.path("fed_yield_curve:treasury_rates")` works, and returns a frozen copy.

- `[dependencies]` in the manifest, with `path` and `git` + `rev` forms ({doc}`asset-graph`,
  "Identity and location").
- The resolution chain, in one place: an explicit location in `[dependencies]`, then the local
  catalog, then (reserved) registries, then an error that lists candidates.
- The store: objects named by content hash, with the link ladder and garbage collection roots.
- `chartbook.lock`, `chartbook pin`, `chartbook update`.
- Cross-pipeline references resolve **through the lockfile into the store**, never to the
  upstream's working directory. Remove the cross-pipeline refusal in `resolve.parse_local_ref()`.
- Loading from a pipeline that is not a declared dependency fails, and says what to add.
- A second example pipeline that depends on `yield_curve`.

**Done when:** the second example builds from a clean clone with no catalog configured, and
editing the upstream's data does not change what the downstream reads until `chartbook update`.

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
| 2026-10-12 | Models are assets. ChartBook is a model registry, not an experiment tracker. ML operations is a central use case | {doc}`models` |

## Open questions, collected

Each is explained where it lives.

- How `@rev` is looked up; how model versions are numbered across branches; which builds make a
  version; retention. ({doc}`references`, {doc}`models`)
- Whether the site should render from the index, and when. (Step 6)
- `plotting.line()` and its siblings can only use the two built-in backends, although third
  parties can register others. ({doc}`../guide/plotting-backends`)
- The project template's CI should run `chartbook check --skip-outputs`, once 0.2.0 is on PyPI.
