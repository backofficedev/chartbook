# Changelog

All notable changes to chartbook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — the Sphinx writer's third slice: the model page

`SphinxWriter.model_page()` writes a model's page from its index record alone, plus the write-up it names: scores, versions, files, what it was trained on (linked when that dataframe's pipeline is part of the site) and the out-of-date notice. It never reads the model's bytes. For the notice the `Model` record gains `inputs_now`: the content hash of each `trained_with` input now, keyed as `trained_with` is, so the record alone says which input moved from what to what (an adversarial review showed the mapping from those keys to `inputs` cannot be derived from the index once a declaration is reordered or two upstreams share a dataframe name). A model's write-up is text, not a template, like the others now. Aligned on both sides: a directory model's files are listed by path as text; a directory's `modified_at` in the index counts only the files its hash counts and is absent when there are none (an empty folder, or one holding only `.DS_Store`, no longer gets a time), and a dataframe that is a directory of parts now shows the same "Data updated" as its index record, the newest part's time, where the page had shown the folder's own; and training data that a pipeline in the site does not declare is named by its build ID with the note "which that pipeline does not declare", where the generator had called it "not part of this site".

### Added — the Sphinx writer's second slice: the chart page

`SphinxWriter.chart_page()` writes a chart's page from its record, the record of the dataframe it was made from (its `inputs`), its pipeline's record and the write-up the record names. It reads no chart file: the page embeds the chart by its path under the site. "Chart updated" is the chart file's `modified_at` and "Data updated" is its dataframe's, which for a table or query is the engine file's — the generator used to show the pipeline folder's own time there, and now says the same as the writer. A chart's write-up is text, not a template, as a dataframe's became with the first slice. The golden test now holds the chart pages equal too, on a file-backed pipeline, on a chart drawn from a DuckDB table, and on a catalog. Two things an adversarial review of the slice found, fixed: a chart's `series` list was missing from its index record (`series` had been treated as structural for every asset kind, where only a dataframe's become Series records), so a writer's page would have lacked the Data Series row; and the generator's provenance-panel cache was keyed by the `id()` of the records dict, which a later build in the same process could wrongly match once the first was freed.

### Added — the Sphinx writer's first slice: the dataframe page from the index

`chartbook.writers.sphinx.SphinxWriter` writes a dataframe's page from the index and the files the index names, and nothing else: the record for its declared fields, hashes, counts and dates; the pipeline's record for the manifest table; the write-up at the path the record gives; the data file for the glimpse, or the engine for a table or query, opened from the public `url` the location now carries. A golden test holds its page equal to the generator's, section for section, on a file-backed pipeline and on one with a DuckDB table and query. The generator still writes the site; the writer replaces it one page kind at a time. Two facts the slice needed are in the index: a pipeline's `site_url` (left out of the published index when it is a local `file://` path) and a table or query location's `url`. Decided with it: a write-up is text, not a template — Jinja syntax inside one is no longer evaluated on the dataframe page; a table or query's date rows come from the index's `date_range`; a declared path is shown normalized.

### Added — the four facts a writer needs, in the index

From the page inventory: every write-up (an asset's `docs`, a pipeline's README) now carries its `content_hash`, so a build says which text it showed and `index diff` says *write-up changed*; a `file` location carries `modified_at`, when the file was last written, for the freshness lines; a dataframe with a `date_col` carries `date_range`, the first and last date in its data; a `Pipeline` record carries `code_changed_at`, when its code last changed as the docs build worked it out (git where the source is committed and unmodified, else the newest file time; absent from an index built outside a docs build). `index diff` reads what a file holds, not when it was written, so a touch is not a change; it says *write-up changed*, *data reaches further* or *less far*, and *source changed*.

### Documentation — the vocabulary page, and the inventory for the writer

`docs_src/design/writer.md` inventories every section of every page the generator writes today, says whether each is a fact (belongs in the index), a rendering (the writer makes it) or a file (the writer reads what the index names), and lists what the index must gain before a Sphinx writer can replace the generator: the write-up's path and hash, `modified_at` on file locations, `date_range` on dated dataframes, `code_changed_at` on the pipeline, the policy on the catalog. Nothing is built.

### Documentation — the vocabulary page

A page that defines ChartBook's words and is the one place they are defined: the chain *repository → index → pages → site*, with a *writer* per site tool; the four documents and the sentence that tells them apart — *a manifest asks, a lockfile records what was got, a snapshot records what was made, and an index records what a site shows*; the three rules that follow (the lockfile is never merged into the index; the index records facts and comparisons, no renderings; write-ups are not pinned, the commit holds them); and where this is going (snapshot and index converge). The design's own Words table now points at it.

### Added — a provenance panel on every dataframe, chart and model page

Each page now carries a **Provenance** section, before its manifest sections, that says, from `index.json` alone: what this is and where it is; its content hash, size, rows and columns (or its definition hash, for a table or query); which pipeline built it and with what script; what it was made from, at which hash, pinned from which snapshot at which commit, and whether that has moved since the model was trained; and what is made from it. The build makes the index first, once, and hands each page its record, so the pages are readers of the index and say what it says; `chartbook.provenance.panel()` is the reader; the same index is written beside the site at the end. An incremental build regenerates a pipeline's pages when what their panels would say has changed, even if none of its own files did, since a panel reads other pipelines' records.

### Added — `chartbook index diff`: what changed between two builds

The first reader of the index. Two `index.json` files, from two builds, say what a change did without anyone opening the site: records added and removed, and for each changed one, in a reviewer's words, whether its data moved (with the hashes and row counts), its pins moved, a model got a new version or its labels moved, it went out of date or came back up to date, or it is declared differently. The two are compared as published, so a build directory's index and the site's compare as equals, and `generated_at` is ignored. `--json` for a script or a bot; `--exit-code` for CI. In Python it is `chartbook.indexdiff.diff()`. A review of it found that a Plotly chart written without a fixed `div_id` embeds a fresh id on every render, so its hash in the index moved with nothing changed: ChartBook's plotting helpers, the examples and the template now pass one, and the docs say what to do in your own code.

### Added — a model shows as out of date when what it was trained on has moved

The last line of the loop in `models.md`. A snapshot now records, on each model's record, the content hash of every `trained_on` input at the time: a local dataframe's as the snapshot has it, another pipeline's as the lockfile pinned it. The model file's bytes are a version, and that version's record is compared with the inputs now: the local dataframe as it is in the folder, the other pipeline's as `chartbook.lock` pins it after `chartbook update`. The model's page says **Out of date** and lists each input then and now; the `Model` record in `index.json` gains `trained_with` and `stale_inputs`; `chartbook check` warns, and does not fail: a model may be kept on purpose, and `chartbook run` retrains it. A model that was just retrained and not yet snapshotted is no version yet, so nothing is said until the snapshot that makes it one. In Python it is `chartbook.models.staleness()`. An adversarial review found ten things, fixed with a test each except the two gaps written down in `overview.md` under "4i, as built" (a model retrained to the same bytes stays its version and is reported out of date; a renamed dependency key is not matched).

### Added — a version of another pipeline's model: `forecasting:model/x@champion`

The fifth row of the design's table in `models.md`, and the last piece of model versions. A pipeline that depends on another can ask for a labelled version of its model, `models.path("forecasting:rate_forecaster@champion")`, or an exact one, `@7f3a9c2e41b0`. The label is looked up when pinning and frozen in the lockfile: a snapshot records the labels its manifest gave (`labels` on the record, by label name now, not only by version), `chartbook pin` writes each as a record of its own, `forecasting:model/rate_forecaster@champion`, with the hash of the version it names, and `chartbook update` moves it with the owner's manifest (`moved`, or `dropped` when the label is gone; `pin` reports a label the owner has moved since as changed upstream). An exact version is found among the pipeline's snapshots in the store. Nothing of the other pipeline's folder is read. A label the owner gave after you pinned is not in your lockfile, and the error says `chartbook update` pins it. What a label pins is a root for `store gc`, so the version is kept; a label whose version the store cannot supply is pinned without bytes, with the reason, and `--frozen` reports it. An adversarial review found eleven things in the first commit, two of them crashes (an exact version of a dependency declared with a scope; a label name the owner's manifest spells illegally, which the snapshot recorded and every dependant's `pin` then fell over), fixed with a test each, except where `overview.md` says otherwise under "4h, as built". A second review found eight more, three about `git` dependencies, which have no versions: their messages said otherwise, and a dependency that went from `path` to `git` carried its label pins for ever (they are let go now). `chartbook snapshot` says which labels it did not record.

### Added — `--frozen`, and a store a team shares

`chartbook pin --frozen` and `chartbook run --frozen` write nothing: not the lockfile, not the store, and no `git` dependency is fetched or built. They say whether the pipeline can be built from its lockfile alone (every dependency pinned from where the manifest says, every asset built when pinned, every pin in the store) and exit `1` if not; `run --frozen` builds only when that holds. It is what CI runs, and what anyone with a store they may only read runs. `--frozen` and `--snapshot` are one or the other. In Python it is `chartbook.lock.verify()`.

With it, a store a team shares works end to end: point every machine's `[store] path` or `CHARTBOOK_STORE` at one folder on a shared disk, and a snapshot made on one machine is what the others pin. Two things were in the way and are fixed. `pin` of a `path` dependency failed on a store that is read-only for this user, over the one write it still made, the note it leaves for `store gc`; it now pins, and says the note could not be left (what does have to write the store, a `git` dependency's first pin, `--from-folder` and `snapshot`, says that the store is read-only and stops). And `store gc` run from one machine could not see another machine's labels, which it reads from the folder a snapshot was made from, and would have removed a labelled version; a snapshot now records the labels its manifest had when it was made, and `gc` reads the newest snapshot's too, so labels travel with snapshots, and a label taken away releases its version once a snapshot follows. A review before merge found that the first design, keeping every snapshot whose folder is gone, would have kept every CI runner's snapshot for ever; it was replaced by this.

### Added — a dataframe can be a table or a query: `[sources]`, `data.sql()`, `data.ref()`, `data.connect()`

A dataframe was a parquet file. It can now be a table, or a query, in a database the pipeline names, and the same name loads it.

```toml
[sources.local]
backend = "duckdb"
url = "duckdb:///./_data/yield_curve.duckdb"

[dataframes.yield_slopes]
source = "local"
query = "select Date, SVENY10 - SVENY02 as slope_10y_2y from fed_yield_curve"
```

```python
data.load("yield_slopes")                                          # runs the query; a LazyFrame
data.sql("select * from {yield_slopes} s join {fed_yield_curve} r on r.Date = s.Date")
data.ref("yield_slopes")                                           # its name, for SQL you run yourself
data.connect("local")                                              # the raw connection, read-only
```

This is step 5 of the design, `data-access.md`, and the second of the two ways the maintainer said data should be read (2026-10-13): SQL that ChartBook passes through, or a path handed to polars. The rule is the design's: a name resolves to a location, the engine runs the query, Arrow comes back, Polars wraps it. ChartBook never parses, plans or rewrites SQL. In `data.sql()` the only thing it touches is what is between braces, which it replaces with the dataframe's name in SQL: `read_parquet('…')` for a file, a quoted identifier for a table, a sub-select for a query. Everything else is the user's, in the engine's dialect.

DuckDB is the engine that is built: a file the pipeline makes, or `:memory:`, opened read-only, and the fallback engine for SQL over files. It reads parquet, so one query can join a table with a file. Other engines are refused by name until they exist. A query runs in one source; one that names two is refused. A dataframe in a source has no file, so it is not pinned and not in a snapshot, and `data.path()` says so.

A source's `url` is the public part; a manifest with credentials in it does not load. The machine supplies the rest, from `CHARTBOOK_SOURCE_<NAME>_URL`, then `~/.chartbook/sources.toml`, then the manifest alone; a machine URL for another engine is refused. A DuckDB file is opened afresh for each load, so a rebuilt file is seen; a `:memory:` source is one writable connection for the process, since it holds only what is put in it. A literal brace in `data.sql()` is written twice. The index records a table or query dataframe's `location` with its source, backend and identifier or SQL, its columns as the engine describes them, and a `definition_hash` in place of a `content_hash`. The page shows the columns, the first rows and, with `date_col`, the first and last date; a query that cannot be read is said so on its page, and the site is still built. `chartbook check` reports a DuckDB file that is not built yet, and the index warns about a table it cannot describe. The `yield_curve` example gains `yield_slopes`, a query over a DuckDB table the pipeline builds from its own parquet. `duckdb` is a dependency of `chartbook`, at 1.4 or later; `polars` is 1.20 or later. An adversarial review of the step before merge found fifteen things, listed in `overview.md` under "Step 5, as built"; all but the dependency floors are fixed with a test each.

### Fixed — what two adversarial reviews of the asset graph found

None of this was released. It is listed because each item changes something the entries below describe.

- **A git dependency's manifest could name files outside its repository, and `chartbook pin` copied them.** An absolute `path`, a `..`, or a committed symlink pointing at, say, `~/.ssh/id_rsa` had `pin` copy that file into the store and write its hash into the committed lockfile, without running anything. Now a repository gives up nothing but its own files: every declared path is followed to where it really is, and one that reaches outside is reported as `outside the repository`, not pinned, and counted as a problem. `chartbook snapshot` refuses a pipeline whose manifest reaches outside its folder for the same reason.
- **`chartbook update` could write a lockfile that named a new snapshot beside an old asset's bytes**, when the store had lost one of the new snapshot's objects. A snapshot is now taken whole or not at all: if any object it names is missing, nothing moves, the lockfile is left as it was, and the missing object is reported.
- **`chartbook run --snapshot` refused itself in a project that commits `chartbook.lock`**, because the pin it made before the build changed that file and the check after the build blamed the build. The lockfile ChartBook itself writes no longer counts as an uncommitted change, before or after the build. A build that *commits* is refused: the label would name a commit that did not run the build.
- **Two pipelines whose build scripts ran each other looped without end.** The guard against a build script calling `chartbook build` or `chartbook run` saw only the innermost call. Every script ChartBook is running is now in `CHARTBOOK_RUN_STACK`, and a pipeline anywhere in it is refused. The guard also comes before the pin, so a refused call writes no lockfile.
- **A model version at a commit that was amended away was lost.** Amending right after `chartbook run --snapshot` is routine. Versions are now found among every commit the repository still has, not only those a branch points at.
- **A git dependency with `build = "./build.sh"` could not run**: the checkout made every file read-only and dropped the executable bit. It is kept.
- **Two different repositories could share one clone**, when their URLs differed only in port or in a character the cache does not keep (`a b` and `a_b`). A port stays in the clone's name, and a component that had to be cleaned carries a short hash of itself.
- **Two pipelines could share one folder of snapshots** (`a--b/c` and `a/b--c`; a folder named `_top` and the repository's top). Such names carry a short hash of themselves.
- **A frozen pin of bytes already in the store under another name dropped that name**, when the earlier object was a hard link or symlink made through the Python API. The other names are kept, as frozen copies.
- Smaller: two `pin`s at once no longer trip over one temporary file name; `pin` now says `relocated` and stays put when a `path` dependency is pointed at another folder, as it does for `git`; `pin --from-folder` that moves nothing keeps saying which snapshot the pins came from; `model/x@md5:…` is refused instead of being read as sha256; a label that is not text is not a label; `chartbook init` interrupted at the prompt exits cleanly; the template no longer ships a path from its author's machine.


Every snapshot was kept for ever, and on a disk without copy-on-write clones each one is a full copy of a pipeline's data. `chartbook store gc` now lets old ones go. A snapshot is kept if a lockfile pins it, if it is the newest of its pipeline or the newest that a branch or tag of its repository can pin from, if a label in that pipeline's `chartbook.toml` points at a model version it holds, or if it was made in the last 30 days (`--keep-days` changes the number). The rest are listed, and removed when you say yes, together with whatever only they named. The list is made again when the yes comes, so a pin that landed in between is kept.

```console
$ chartbook store gc --dry-run
Kept: 4 snapshot(s), naming 9 object(s): 1 because a lockfile pins it, 2 because it is the newest of its pipeline, 1 because it was made in the last 30 days
Would remove 6 snapshot(s):
  ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: nothing pins it, it is not the newest, and it is older than 30 days
```

For the labels, the store notes beside each pipeline's snapshots the folder they were made from, and reads that folder's manifest when it clears. A folder that is gone says nothing, and the other three rules still hold.


`treasury_rates#dgs10` is the address of one column of a dataframe. It is what a `[dataframes.treasury_rates.series.dgs10]` table documents and what `index.json` lists. The design also had `data.load("treasury_rates#dgs10")` hand back that column, as the last part of this step.

That will not be built. The maintainer decided (2026-10-13) that ChartBook should not grow a language for loading data: it says where a dataframe is, what it is and which copy you get, and picking columns and rows is for the tools that already do it. Load the dataframe and select with polars, or take `data.path()` and hand it to anything else; a database is read with SQL passed through.

So a reference with `#` is still refused by `data.load()`, `data.path()` and `chartbook path`, and the message no longer says "not yet". It says what the address is for and what to do instead.

### Changed — the project template lives in this repository

`chartbook init` now renders the `template/` folder of ChartBook's own repository. It used to render a separate repository, `cookiecutter_chartbook`.

Three things were wrong with keeping it apart. The template could disagree with the ChartBook that rendered it: renaming `chartbook build` to `chartbook docs`, below, left it calling a command that no longer meant what it wanted. Nothing here tested it: the tests of `chartbook init` stand in for the download, so no test ever built a freshly made project. And a change to a command took two pull requests in two repositories. Now the template and the commands change in one pull request, the template's own tests run with ChartBook's, and one of them renders a project and builds it with the ChartBook in the same commit.

The template was brought over as it was (from `cookiecutter_chartbook` at commit `a67eeea`), with what the changes below need:

- Its build file renders the site with `chartbook docs -f`.
- Its manifest names its build, `[scripts] build = "doit"`, where it had a note about which modules to load, so `chartbook run` and `chartbook build` work in a new project.
- Its copy of ChartBook's skill is the package's own, and a test keeps it so.
- Its pixi file no longer asks for the `[all]` extra, which is gone.

A new project is still made with cruft, and `.cruft.json` in it records this repository and the `template` folder, so `cruft update` brings in later changes.

**For a project made before this:** its `.cruft.json` names the old repository, and `cruft update` there keeps reading the old one. To follow the template here, re-link it: `cruft link https://github.com/backofficedev/chartbook --directory template`.

**The old repository should be left as it is.** Released versions of ChartBook render it, and in those versions `chartbook build` still means "render the site". Not brought over: the generated `example/` project that the old repository keeps for reference, and its editor rules.

### Added — versions of a model, and labels: `model/x@7f3a9c2e41b0`, `model/x@champion`

A model now has versions, and a name can point at one.

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

```python
models.path("rate_forecaster")             # what is in your folder now
models.path("rate_forecaster@7f3a9c2e41b0")     # that version, in the store
models.path("rate_forecaster@champion")    # the version the label points at
models.versions("rate_forecaster")         # all of them, with scores and commits
```

**A version is made by a snapshot**, the first one that holds new bytes for the model. The design had every build that changed a model make a version. The maintainer decided otherwise (2026-10-13), in line with snapshots: a version is something declared ready, with everything committed, so tuning a model all afternoon makes none and every version has a commit that describes it. A snapshot already records what a version needs: the commit (which code), what the pipeline was pinned to (which data), and now the model's scores as its metrics file had them at that moment, so two versions can be compared after the file has been written over.

**A version is named by the start of its content hash**, as git names a commit. The design proposed `v1`, `v2`, `v3`, and listed the problem with it as an open question: two branches that each retrain both make a `v4`, and the merge conflicts. A name worked out from the bytes is the same on every machine and every branch and never needs renumbering. The names people use are labels, in the manifest, so promoting a model is a one-line change reviewed in a pull request.

The model's page lists its versions, newest first, with their scores, and `index.json` has them under `versions` on the `Model` record. `chartbook check` warns about a label whose version is not on this machine, and does not fail: the version may be in the store of the machine that made it. A labelled version is kept by `chartbook store gc` for as long as the label is in a manifest the store knows about, or in the pipeline's newest snapshot.

`@` in a reference used to be refused everywhere as reserved. It now resolves for one thing, a version of one of this pipeline's own models. Not built: a version of another pipeline's model (`other:model/x@champion`), versions of anything but a model, and versions that travel between machines, which need a store to share.

### Changed — **breaking: `chartbook build` is now `chartbook docs`, and `chartbook build` builds everything**

| Command | Builds the data | Renders the site |
|---|---|---|
| `chartbook run` | Yes | No |
| `chartbook docs` | No | Yes |
| `chartbook build` | Yes | Yes |

**What to change.** Wherever a build script says `chartbook build`, make it say `chartbook docs`. That is the `dodo.py` of every project made by `chartbook init` so far (a project made from now on already says `chartbook docs`: see the entry above):

```python
"actions": ["chartbook docs -f"],     # was: chartbook build -f
```

`chartbook docs` takes every argument and option `chartbook build` took, and does exactly what it did: it renders the site and writes `index.json`.

**Why.** One word meant two things. `chartbook build` rendered the website, while `build` in a manifest is the script that makes a pipeline's data. Now each word means the plain thing: `run` runs a script, `docs` makes the documentation, and `build` builds everything, which is `chartbook run` followed by `chartbook docs`. The maintainer's instruction was to do the right thing and not to keep the old meaning working (2026-10-13).

`chartbook build` runs the `build` script first. If the script fails, the site is not rendered and the exit code is the script's. With no `build` script it says so and renders the site. In a catalog it runs the script in each of the catalog's pipelines and then renders the catalog's site.

**The one protection.** A build script that still says `chartbook build` would be run by the command it calls, without end. So a script is told which pipeline and script it is, and `chartbook build` called from inside the build script it is running renders the site and prints a warning that says to use `chartbook docs`. `chartbook run` called from inside the script it is running is refused. That is all the compatibility there is: started from plain `doit`, an old `dodo.py` runs its own build a second time, nested, before the warning stops it.

`chartbook catalog build` is unchanged. It renders the global catalog's site and runs no script, so its name now disagrees with `chartbook build`; what it should be called is not settled.

### Added — snapshots: `chartbook snapshot`

A pipeline's owner now says when a build is ready for others, and that is the only thing another pipeline ever reads.

```console
$ chartbook run --snapshot       # build it, and say it is ready
ftsfr/fed_yield_curve: build
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
Ran build in 1 pipeline(s).
```

A **snapshot** is every asset a pipeline declares, as built at one commit, copied into the store and labelled with that commit. `chartbook snapshot` makes one from what is on disk; `chartbook run --snapshot` builds first and makes one in the same command.

The reason is that pipelines are worked on at the same time, by people and by agents, one to a pipeline. Someone is always half-way through a change. Until now `chartbook pin` and `chartbook update` copied whatever was in the other pipeline's folder at the moment they ran, so an update made during a rebuild pinned a half-built folder, and one pipeline's work reached into another's working directory. Now nothing does. The store is the read-only middle that every pipeline reads from, and it changes slowly and on purpose. The maintainer decided this model on 2026-10-13; it is written up in the design overview.

Three rules. **Everything in the pipeline's folder must be committed before a snapshot**, because the label says "this is what that commit built"; what git ignores, such as built data, does not count. **A snapshot is made when its owner asks, not by every build.** And **nobody is moved to it**: a pipeline that depends on this one gets a new snapshot with `chartbook update`, and not before.

**This changes `chartbook pin` and `chartbook update` for a `path` dependency** (they are described under "pinning" below, and have not been released). They now choose among snapshots. `pin` takes the newest at the commit the other folder is on or, if that commit has none, at the nearest one before it; `update` moves to the newest. `chartbook.lock` records the snapshot's commit and time beside the hashes, so it says which code as well as which data, as it already did for a `git` dependency. A pipeline whose owner has made no snapshot cannot be pinned, and the command says what the owner has to do. A rebuild that has not been declared ready is not seen at all. A dependency is pinned to one snapshot, whole.

One commit can have several snapshots, since a pipeline that pulls data from outside builds other bytes on another day; rebuilding and making a snapshot again gives a new one at the same commit, and making one when nothing was rebuilt gives none. `chartbook store gc` keeps what a snapshot names for as long as it keeps the snapshot; see the entry above.

For working on two pipelines at once, `chartbook pin --from-folder` and `chartbook update --from-folder` still take what is in the folder this minute. The option is off by default and left out of `--help` on purpose, and a lockfile made with it names no commit.

**Build and snapshot together.** `chartbook snapshot` by itself takes its owner's word that what is on disk was built by the commit they are on: change a script, commit, forget to rebuild, and the old data gets the new commit's label. `chartbook run --snapshot` closes that. It checks that everything is committed before it builds, builds, checks again (a build that changes a committed file gets no snapshot), and records in the snapshot that the build ran in the same command. In a catalog each pipeline is built and declared ready in turn.

**What a snapshot records, and what it never does.** Which data: the hash of every file. Which code: the commit. What it was built from: `inputs`, what the pipeline was itself pinned to, so a snapshot of `rate_forecast` names the snapshot of `fed_yield_curve` it read. And a note of the conditions, `built_with`: whether the build ran in the same command, and the ChartBook, Python and platform versions. The note is there to explain a difference between two snapshots, not to make a build repeatable. Nothing of a pipeline's `.env` is copied, ever: it holds secrets, and a store is something to share.

Not built yet: sharing snapshots between machines.

### Added — `[scripts]` and `chartbook run`

A pipeline can now say how it is built, and one command gets it built.

```toml
[scripts]
build = "doit"
test = "pytest"
```

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

Until now, a pipeline that read another's data was built by hand in steps: `chartbook pin`, then the build. `chartbook run` pins what has no pin yet and runs the pipeline's `build` script, so a fresh clone needs one command. `chartbook run test` runs another script by name, and in a catalog the script is run in each of the catalog's pipelines, one that another depends on first.

`build` is the one script name with a meaning: it makes a pipeline's data current. A script is one string handed to a shell (`bash`, or `sh` where there is none), so one of several lines is one script and it stops at its first failing command. The command exits with the script's exit code.

**It never builds in a folder the pipeline depends on.** A `path` dependency is a folder somebody works in, and they may be half-way through a change. This pipeline reads what is pinned, not what is in that folder, so building there would disturb its owner and change nothing this pipeline reads. The design had `chartbook run` build every pipeline in the dependency graph, and a first version did. The maintainer decided against it (2026-10-13): pipelines are worked on side by side, by people and by agents, and one of them must not reach into another's working directory.

**It never moves a pin.** If the other pipeline has newer data, this one is still built against the copy it pinned, and the command says what has changed; `chartbook update` moves the pins. The design had `run` pick up new upstream data by default. That was decided against too: a lockfile should change only in a commit someone meant to make.

**It builds a `git` dependency, once.** `chartbook pin` can pin only what a repository commits, because a clone has no built data in it. Nobody works in ChartBook's own copy of a commit, so there is nothing to disturb: `chartbook run` makes a writable copy of the checkout under `~/.chartbook/git/work/`, runs the dependency's `build` there, and pins what that produces. This is what the note under "`git` dependencies" below was waiting for. It is built once for a commit, and nothing builds it again by itself. `chartbook run --force` does, which is how data it pulls from outside is refreshed on purpose. `run` stays at the commit in the lockfile. `chartbook update` moves to a newer one, and when it does, data that was built at the old commit and is not built at the new one is let go from the lockfile, since it did not come from the commit now named; the next `chartbook run` builds it and pins it.

**`[project] build` is now executed.** It has always been described as a script, and until now it was only shown on the pipeline's page. It is the same thing as `[scripts] build` and is still read; a manifest that gives both, differently, does not load. If yours holds a note and not the command that builds the pipeline (one of the examples here had `build = "module load anaconda3/3.11.4 TeXLive/2023"`), `chartbook run` will run that note. Make it the command. Nothing else reads the field differently, so this matters only once you use `chartbook run`.

`index.json` lists all of a pipeline's scripts under `scripts`, where it had only `build`.

Not built yet: `--frozen` for CI. Scripts are not tasks, and that part is on purpose: one does not depend on another, and there are no retries, no schedule and no history.

### Added — `git` dependencies

A dependency no longer has to be on your disk. It can be a git repository:

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

`chartbook pin` clones the repository into `~/.chartbook/git/`, checks out the revision, and from there treats it like a directory: what it declares is pinned, and its assets are read with `data.load("ref_data:countries")` like any other dependency's. Any git host works, and so does a path to a repository on disk. `rev` is a branch, a tag or a commit, and may be left out for the default branch. `chartbook.lock` records the exact commit.

**It can pin only what the repository commits.** A clone has the other pipeline's code and whatever data it keeps in git. Data that is built and git-ignored is not in a clone, and ChartBook does not run another pipeline's build, so those assets are listed as not built and the command says why. This is useful today for reference data, small tables and models that are committed. Reading *built* data from a pipeline you only have as a repository needs ChartBook to be able to run that pipeline, which is a later step.

`pin` stays at the commit in the lockfile, and uses the network only if this machine has lost its copy of it. `chartbook update` fetches again and asks what the `rev` means now: a branch moves forward, a tag or a commit does not. Change `rev` in the manifest and `pin` points it out and stays put; `update` follows it.

ChartBook runs the `git` you already have, so SSH keys and credential helpers work as they do by hand. It never waits at a password prompt; it fails. A URL is handed to git on each call and is not written into the clone, and a URL is shown without its user name and password in every message and in the lockfile. A `git` URL or a `rev` that git could take for an option is refused when the manifest loads.

`chartbook check` looks at a `git` dependency where it has been fetched, and never uses the network: one that has not been fetched on this machine is a warning. To keep the clones somewhere else, set `CHARTBOOK_GIT_CACHE`, or `[git] path = "…"` in `~/.chartbook/settings.toml`.

Not handled: submodules, Git LFS, working out a repository from an ID alone, and clearing out old checkouts, which `chartbook store gc` does not touch.

### Added — reading another pipeline's assets: `data.load("pipeline:name")`

A pipeline can now read what another pipeline produces, by name, and get a copy that does not change under it.

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
```

```console
$ chartbook pin
$ chartbook path fed_yield_curve:treasury_rates
/Users/x/.chartbook/store/objects/sha256/4b/1f…/treasury_rates.parquet
```

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates")     # the pinned copy
path = data.path("fed_yield_curve:treasury_rates")      # or just where it is
```

This is what the three entries below were for. A reference with a pipeline in front, `pipeline:name`, used to be refused as reserved. It now resolves, through `chartbook.lock`, to the copy in the store that `chartbook pin` froze, and never to the other pipeline's working directory. The rule is: **your own assets resolve live, another pipeline's resolve pinned.** So the other pipeline can rebuild, or be half-way through a change, and what you read stays the same until you run `chartbook update`. It works for every kind of asset and from every front door: `assets.path()`, `data.path()`, `models.path()`, `data.load()` and `chartbook path`, which makes it reachable from Make, a shell, R and Stata as well. No catalog is involved.

`data.load()` takes one reference now: `data.load("treasury_rates")` is this pipeline's own dataframe, and `data.load("fed_yield_curve:treasury_rates")` is another's, as pinned. The two-argument form, `data.load(pipeline=…, dataframe=…)`, is unchanged and still means "through a catalog", reading the other pipeline's own file.

When something is missing, the error says which thing and what to do: the pipeline is not in `[dependencies]` (it shows the line to add, and looks in your catalog for where that pipeline is); it is declared and not pinned; the asset was not built when it was pinned; or it is pinned and the store does not have the bytes, as after a clone (`chartbook pin` puts them back).

**A model's record now names the bytes it is trained on.** In `index.json`, a model whose `trained_on` names another pipeline's dataframe has `pinned_inputs`: that input's ID and the content hash `chartbook.lock` pins it at. Each dependency in a pipeline's record has its `pinned_hash`. This says what is pinned, which is what the training code is handed; a record of what one particular run read comes later, with build records.

A `trained_on` that names a pipeline `[dependencies]` does not declare is now an error, not a warning.

**A new example, `examples/rate_forecast`**, is the whole thing in one small pipeline: a model trained on the `yield_curve` example's data. It declares the dependency, pins it, loads the pinned copy, and retrains exactly when `chartbook.lock` changes. Its README shows what happens when `yield_curve` rebuilds afterwards: nothing, until `chartbook update`.

Not yet: one column of another pipeline's dataframe (`…#dgs10`) and a version (`…@v3`). The design is "Pinning and isolation" in {doc}`design/asset-graph`, and the reference grammar is {doc}`design/references`.

### Added — pinning: `chartbook pin`, `chartbook update`, `chartbook.lock`

A pipeline can now freeze what it depends on.

```console
$ chartbook pin
ftsfr/fed_yield_curve: 3 pinned, 1 not built
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
Wrote chartbook.lock.
```

For each pipeline in `[dependencies]`, every asset it declares is put in the store and its content hash is written to `chartbook.lock`, beside `chartbook.toml`. The lockfile is source: commit it, and a change to what the project depends on shows up in a diff. It is JSON in the same format as `index.json`, with no timestamp and no path from your machine, so pinning twice with nothing changed leaves it untouched.

**`pin` never moves a pin; `update` does.** Run `pin` again after the other pipeline has rebuilt and your pins stay where they were, with a line saying what has changed upstream. `chartbook update` moves them, for every dependency or the ones you name, and prints each old and new hash. The split is the one `cargo build` and `cargo update` have, and it means an accidental `pin` cannot undo a freeze.

`pin` also pins whatever has no pin yet, and puts back in the store anything the lockfile names that the store has lost, as long as the other pipeline still has those bytes. So it is the command to run after cloning. An asset that is declared and not built is listed and left unpinned; the rest is pinned.

**`chartbook store gc`** removes from the store what no lockfile names. The store is shared by all your projects, so each `pin` and `update` notes its lockfile there, and `gc` keeps whatever any of them names. It lists what it would remove and asks first. A lockfile it cannot find (a drive not plugged in) still keeps what it last pinned, unless you pass `--forget-missing`; nothing stored in the last hour is removed; and if a lockfile cannot be read, nothing is removed at all.

**A pin is a copy that cannot change.** It is a copy-on-write clone where the disk has them (a Mac; Linux with btrfs or XFS), which costs nothing, and a full copy everywhere else, which costs the file's size. It is never a hard link or a symlink to the other pipeline's file. Those are the cheapest ways to hold a file and the store offers them, but that file is rewritten in place when the other pipeline rebuilds (pandas and polars both write a parquet file that way), and a pin that changed with it would not be a pin.

A `git` dependency is fetched and then pinned the same way; see the entry on `git` dependencies above. The design is "Pinning and isolation" in {doc}`design/asset-graph`.

### Added — the store: `chartbook.store` and `chartbook store verify`

ChartBook now has a store: a folder of files kept under the hash of what is in them, at `~/.chartbook/store/`. It is where a pinned copy of another pipeline's data will live, so that a project keeps reading the data it was built against while the other pipeline moves on. **Nothing puts anything in it yet.** This is the piece that pinning is built on, added first so that it can be tested alone.

An asset in the store is a directory named by its content hash, holding the asset's files under their own names, so a path into the store still ends in `.parquet` and a partitioned dataset keeps folders like `year=2024/`. The same bytes stored by ten projects are one object. The store has four operations, `has`, `get`, `put` and `delete`, in `chartbook.store.Store`.

A file that is stored never moves. The store can hold it four ways, tried in order: a copy-on-write clone, a hard link, a symlink, a copy. A clone and a copy are the store's own bytes and cannot change. A hard link is the original file under a second name, so it changes if the original is rewritten in place; a symlink changes whenever the original does. A caller says which of the four it will accept. Pinning accepts only the two that cannot change. The cheaper two are for what can simply be made again, and because an object held that way can change, there is one command already:

```console
$ chartbook store verify
/Users/x/.chartbook/store: OK (14 object(s))
```

`verify` hashes every object again and exits `1` if any is no longer what its name says, naming it and saying why when it can ("is a hard link to a file outside the store, which has been rewritten").

To keep the store on a bigger disk, or on a drive a team shares, set `CHARTBOOK_STORE`, or `[store] path = "…"` in `~/.chartbook/settings.toml`. The design is "The store" in {doc}`design/asset-graph`.

### Changed — a folder's hash ignores `.DS_Store` and its kind

A model or a dataset that is a folder has one content hash over all its files. Until now that meant *all*: opening the folder in Finder wrote a `.DS_Store`, and the hash in `index.json` changed although nothing in the model had. Four kinds of file that operating systems create by themselves are now left out: `.DS_Store`, `Thumbs.db`, `desktop.ini`, and any file whose name starts with `._`. They are also left out of a directory model's `files` in the index and of the Files table on its page.

Every other file still counts, hidden or not. Skipping every dotfile would have been simpler to say and wrong: a Zarr dataset keeps its real metadata in `.zarray` and `.zattrs`. A `path` that names a single file is unaffected, whatever the file is called.

The index and its hashes have not been in a release, so no stored hash changes meaning. The rule is in {doc}`design/index-schema`, with a shell command that reproduces it.

### Added — dependencies: `[dependencies]`

A pipeline can now say which other pipelines it reads from, and where each one is:

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
"ftsfr/crsp_compustat"  = { git = "https://gitlab.example.org/ftsfr/crsp_compustat", rev = "a1b2c3d" }
```

Until now a pipeline could *state* that a model was trained on another pipeline's dataframe, and nothing knew where that pipeline was. So nothing could be checked unless both happened to sit in one catalog. The key is the name this pipeline uses for the other one, and the value is where to find it. Keeping the two apart means a repository can move and only one line changes: code, lineage and the index keep saying `ftsfr/fed_yield_curve`.

What declaring a dependency does today:

- **`chartbook check` says whether it can be found.** A `path` that is not there, has no `chartbook.toml`, is a catalog, or is the pipeline's own directory is reported, naming the entry. So is a model whose `trained_on` names a dataframe the other pipeline does not declare, which until now was caught only inside a catalog.
- **`index.json` lists them**, as `dependencies` in the pipeline's record. A model's training data in another pipeline is written by the dependency's name, so `fed_yield_curve:treasury_rates` in a manifest becomes `ftsfr/fed_yield_curve:treasury_rates` in the index. In a catalog, a dependency that is one of the catalog's own pipelines is written by the catalog's ID for it, so the entry matches a record in the same file.
- **A `trained_on` that names a pipeline not in `[dependencies]` does not load**, and the error shows the line to add. A manifest that named another pipeline's dataframe on trust, which `[models]` first allowed, needs that one line.

Declaring is the first half. Pinning what is declared, and reading the pinned copy, are the two entries above this one. A `git` dependency is fetched when it is pinned; `check` looks at it where it has been fetched, and never uses the network itself. `data.load(pipeline=…, dataframe=…)` still looks in a catalog and does not read this table.

A `[dependencies]` table used to be ignored. One that is malformed now stops the manifest from loading, with a message naming the entry, and a catalog that has one is refused: a catalog reads from no pipeline. This is the first of five parts of step 3 in {doc}`design/overview`; the design is {doc}`design/asset-graph`.

### Added — models: `[models]` and `chartbook.models`

A pipeline can now declare a trained model, the way it declares a dataframe or a chart:

```toml
[models.rate_forecaster]
name = "Rate Forecaster"
path = "./_models/rate_forecaster.joblib"
trained_on = ["treasury_rates"]
metrics_path = "./_output/rate_forecaster_metrics.json"
docs_path = "./docs_src/models/rate_forecaster.md"
```

A model is a file, or a directory of files, that the pipeline's own code produces. Six months after training one, the questions that matter are where it is, what data it was trained on, and how good it is. Declaring it puts the answers in one place. ChartBook records them and never looks inside the file: it does not load, run or serve a model, and it imports no machine-learning library. It is a registry of the models a pipeline chooses to keep, not a tracker of training runs.

What a declared model gets:

- **An address**, `model/rate_forecaster`, in the same grammar as every other asset. `chartbook path model/rate_forecaster` prints its path; `chartbook.models.path("rate_forecaster")` returns it in Python, for training code that writes the model and for anything that reads it. `chartbook.models` answers for models only, as `chartbook.data` does for dataframes.
- **A page** with its write-up, a table of its scores, links to the dataframes it was trained on, and its files if it is a directory. A pipeline's front page lists its models; a catalog gets a Models page when some pipeline declares one.
- **A record in `index.json`**, with a content hash (for a directory, one hash over all its files, and each file listed), its scores, and the dataframes it was trained on as `inputs`.
- **`chartbook check`** reports a missing model, metrics file or write-up; a metrics file that is not a flat JSON object; and, by default, a model with no `name`, `description`, `trained_on` or write-up. `--skip-outputs` leaves out the model and its metrics. A catalog sets its own list with `[policy.required] models = […]`, in which `docs` means a write-up given either way.

**Training data may be in another pipeline.** `trained_on = ["ftsfr/fed_yield_curve:treasury_rates"]` names a dataframe of a pipeline that `[dependencies]` declares. It is recorded in the index, listed on the model's page, linked to the dataframe's page when both pipelines are in one catalog, and checked against what the other pipeline declares. Once it is pinned, the model's record also says which bytes it is pinned at. See the entries on dependencies, pinning and references above.

Scores go in a small JSON file that the training code writes (`{"rmse": 0.21, "n_train": 5120}`), not in `chartbook.toml`, because they change with every retraining.

The `yield_curve` example now trains a small model end to end. Not built yet, and refused as "not yet supported": versions and labels (`model/x@v3`, `@champion`), and one file inside a directory model (`model/x#weights.pt`). The design is {doc}`design/models`.

### Added — the index: `index.json`

Every build now writes one more file beside the HTML, `docs/index.json`: a description of everything the site contains, as a flat list of self-describing records. There is one record for each pipeline, dataframe, chart, notebook and note, and one for each column of each dataframe. Until now the only machine-readable description of a ChartBook project was its `chartbook.toml` files, which say what should exist; the index says what a build found. It is the first piece of the {doc}`asset graph <design/asset-graph>`, and the file that later pieces read and write.

Each asset record has a fully qualified ID in the same grammar as `chartbook path` (`scope/pipeline:name`, `scope/pipeline:chart/name`), the same address as named fields (`ref`), a `content_hash` of its file, and every field its manifest entry declares. A dataframe record also has its columns and row count, read from the parquet footer without loading data, and a chart record names the dataframe it was made from in `inputs`. A dataframe stored as many files has one hash that covers all of them, computed in a way that can be reproduced with `sha256sum`.

The published file holds no path from the machine that built it. A fuller copy with absolute paths is written to the build directory (`_docs/index.json`). The same index is available from Python as `chartbook.index.build_index(manifest)`. An incremental build remembers file hashes and reads only the files that changed.

The format is specified in {doc}`design/index-schema`, and a JSON Schema for each kind of record ships in the package under `chartbook/schemas/` and is published with this documentation. Nothing reads the index yet: the site is still rendered from the manifests.

### Added — `[dataframes.<id>.series.<key>]`: documenting a column

A column of a dataframe can now be given a name, units, a frequency and a write-up of its own:

```toml
[dataframes.treasury_rates.series.dgs10]
name = "10-Year Treasury Constant Maturity"
column = "DGS10"
units = "Percent"
```

The key is the series' address inside the dataframe (`treasury_rates#dgs10`). The index lists every column as a series whether or not it has a table; a table documents one, and gives an address to a column whose own name could not be one (`10Y 2Y Spread`).

The recommendation that goes with this: give columns code-friendly, SQL-compatible names (`spread_10y_2y`: letters, digits and underscores, starting with a letter), and put the name people read ("10Y-2Y Spread") in the series table. The `yield_curve` example's term premium dataframe now does exactly that; its columns used to be `10Y 2Y Spread` and the like. The loader rejects a malformed table, an illegal key, and two series that name one column. `chartbook check` reports a series `docs_path` that points at no file. Series are not shown on pages yet, and a series address does not resolve yet.

### Fixed

- A `[policy]` table in a *pipeline's* `chartbook.toml` crashed `chartbook docs` (then called `chartbook build`) and `chartbook check` with `KeyError`. It is now read the way a catalog's is, and says what that pipeline holds itself to when it is built or checked alone; inside a catalog, the catalog's policy still decides. A `strict` policy's message no longer says "Catalog policy" when the policy is a pipeline's.
- Two example dataframes declared `date_col = "date"` when their date columns are `DATE` and `Date`. The page generator swallowed the mismatch, and their pages showed `None` for "Data available up to". The manifests now name the columns, and building the index warns when a `date_col` names no column. That warning then found a second problem: the FRED example's live download left its date index unnamed, so the column existed only in the test suite's stand-in data. The pull script now names it.

## [0.2.0] - 2026-10-12

Tools around the manifest: a CI gate, paths you can ask for, freshness on every page, incremental builds, and a scaffolder that can put a new project on GitHub. The breaking changes are marked as such. ChartBook is still {doc}`experimental <reference/stability>`.

### Added — `chartbook check`, the CI gate

`chartbook check` exits nonzero when a project is broken or non-compliant, and zero when it is healthy. It reports fields the policy requires that are missing or empty, declared paths (`path`, `docs_path`, `readme`, `logo`, `favicon`) that point at no file, and dataframes whose `license_expiration` has passed or falls within `--within` days (default 30). Every finding is one line naming the `chartbook.toml`, the table and the field.

Run in a catalog, it checks every member pipeline against the catalog's `[policy.required]`. Run in a standalone pipeline, it uses the built-in recommended-field lists; `--policy PATH` substitutes the `[policy]` table of a catalog (or of any TOML file), so a pipeline's own CI can hold it to the catalog it is published to without that catalog's other members being present. `policy.mode` still governs builds only — `check` always fails on a missing required field.

`--skip-outputs` is for CI that checks a project without building it. Data files, charts and notebooks are what a pipeline produces and are rarely in git, so on a fresh checkout they are all "missing"; with the flag they are left out, and required fields, license dates and the files that do live in the repository are still checked.

`license_expiration` is read as an ISO date. Empty, `"N/A"`, `"None"` and `"Never"` mean no expiry; any other unreadable value is reported rather than passed. Only metadata and file existence are checked — no data file is opened.

The example projects now set `repo_url` (required by the default policy), and `examples/dodo.py` runs `chartbook check` on the example catalog.

### Added — `chartbook path`, `chartbook.assets` and `data.path()`

A build definition or a script can now ask the manifest where an asset belongs instead of repeating the path. There is one general function and one for the common case:

- `chartbook.assets.path(ref)` returns the `path` declared in the enclosing `chartbook.toml` for any asset — a dataframe, chart, notebook or note — as an absolute `Path`.
- `chartbook.data.path(name)` is the same thing for dataframes only: `assets.path(name, kind="dataframe")`.
- `chartbook path REF` prints the same answer, which is how Make, R, Stata and shell scripts reach it.

An asset is named by a *reference*. A dataframe is its key in `[dataframes]`; anything else has its kind in front: `merged_rates`, `chart/rates_over_time`, `notebook/analysis`, `note/methodology`. Each kind has its own names, so a dataframe and a chart may share one. In Python the kind may be the argument `kind="chart"` instead (`--kind chart` on the command line); it states what you expect, so it fills in a missing kind and rejects a different one. A reference can also be handled as an object, `assets.AssetRef`, which is what `assets.parse()` returns.

The manifest is found by walking up from the calling file, then from the working directory. The file need not exist, so the same call names a `dodo.py` target and the place a script writes to. A name the manifest does not declare raises `AssetNotDeclaredError` immediately, naming the table to add — or, if the name is declared as another kind of asset, saying how to refer to it — rather than surfacing later as a missing file. It is a convenience, never a requirement: a pipeline that hardcodes its paths, in any language, is unaffected.

These names are the local end of one address grammar, `[registry/][scope/]pipeline:[kind/]name[#part][@rev]`, specified in {doc}`design/references`. All of it parses now. Only the local form resolves: another pipeline's asset, a `#part` (a column of a dataframe, a file in a model), an `@rev` and the `model` kind are refused as "reserved syntax and not yet supported".

`data.get_data_path(pipeline=, dataframe=)` keeps working and remains the way to locate another pipeline's dataframe through a catalog. It, the `path()` functions and `data.load()` share one internal resolver (`chartbook.resolve`) that returns a typed location, which is the seam table- and query-backed dataframes will later plug into; no behaviour changes.

Both example pipelines use `data.path()` and `assets.path()` for the declared targets in their `dodo.py`.

The folder of default logos inside the package moved from `chartbook/assets/` to `chartbook/branding/`, to free the name for the module.

`data.scratch()` completes the set: it returns `_data/_scratch/` inside the current pipeline, created on first use, for throwaway files that are not assets. The directory ignores itself in git, and nothing documents, publishes or depends on what is in it.

### Changed — **breaking: data glimpses come from the manifest, not `dodo.py`**

`chartbook create-data-glimpses` no longer imports `dodo.py` and calls its task functions to find data files. It reads `chartbook.toml` and summarizes the dataframes declared there, so a project built with Snakemake, Make or plain scripts gets the same report as one built with doit — previously the command failed with `No dodo.py file found`.

What this changes for existing users:

- **Only declared dataframes are summarized.** A CSV or parquet file that appeared as a doit target but has no `[dataframes.*]` entry is no longer in the report. Declare it to include it.
- **The report is organized by dataframe.** Sections are titled by dataframe ID (`pipeline:dataframe` in a catalog) and show the declared name; the summary groups by pipeline instead of by doit task.
- **Partitioned dataframes work.** A glob `path` is summarized as one dataset across its part files.
- **Catalogs work.** Run in a catalog, the report covers every member pipeline.
- New `--project-dir` option. Declared dataframes whose files are not built yet are skipped with a note.

`create_data_glimpses.parse_dodo_tasks()` and its helpers are removed.

### Changed — registry-prefixed IDs and `chartbook push` are reserved

Two pieces of future syntax are claimed now, while claiming them costs nothing.

A pipeline ID qualified with a registry — `charthub.example/acme/rates`, `localhost:5000/acme/rates` — is now recognized and refused with `UnsupportedRegistryError` ("reserved syntax and not yet supported; use 'acme/rates' instead"), wherever an ID or pipeline reference is accepted: `[project] id`, catalog keys, `data.load(pipeline=...)`, `chartbook data`, `data.path()`. Previously it failed with a generic "Invalid pipeline id" grammar error. A registry is the first of exactly three components and looks like a host (contains `.` or `:`, or is `localhost`), which is Docker's rule. No existing ID changes meaning: a bare `name` and a `scope/name` are untouched, including a `scope` that contains a dot.

`chartbook publish` keeps its one meaning, staging a pipeline's files into a directory, and its help now says so. Sending a pipeline to a registry will be a separate verb, `chartbook push`; the command exists (hidden from `--help`) only to say it is reserved and to point at `publish`.

### Added — `chartbook init --git` and `--github`

`chartbook init` can now leave you with a repository rather than just a directory. `--git` runs `git init` in the new project and makes an initial commit, on a branch named `main` unless your git configuration says otherwise. `--github` does that, then creates a GitHub repository for it with `gh repo create`, adds it as `origin`, and pushes — private by default, `--public` to override. Both are off by default.

`--github` uses your existing `gh` login and never prompts for one. Everything it depends on is checked before the template is rendered — `git` and `gh` on `PATH`, a git identity for the commit, `gh` logged in — so a missing piece stops the command with the fix named and nothing created. The new project's directory is identified after `cruft` returns (it is named by an answer at the prompt), not guessed. After `--github` the `origin` remote exists, so the pipeline's ID is scoped (`owner/project`) from its first build; the command prints it.

### Added — data freshness on every asset page

Dataframe and chart pages now say how fresh they are, directly under the title, in plain relative wording: a dataframe page says "Data updated 2 days ago", and a chart page says "Chart updated 2 days ago · Data updated 2 days ago", so a chart rendered before its data was last refreshed is visible at a glance. Hovering shows the exact time. A chart's date in listings is now when the chart itself was written.

A page says only things about its own asset. When the pipeline's *code* last changed is shown once, on the pipeline's front page ("Code updated 3 weeks ago") and on a catalog's Pipelines page, and no longer in the table at the foot of every chart and dataframe page. Besides being the right place for it, this means a code edit no longer alters every page of the pipeline.

The data and chart times are file modification times: the dataframe's file (the newest part file of a partitioned dataframe) and the chart's HTML. The dataframe's time was previously computed and never rendered.

Because the site is static, the page carries the timestamp and a small bundled script (`chartbook-freshness.js`) turns it into "2 days ago" when the page is read, so the wording is never stale. With scripts off, the date is shown. The line is a template, `freshness.md`, and can be overridden like the others.

Fixed along the way: a chart backed by a partitioned (glob-path) dataframe had its data time stamped with the moment of the build.

### Added — documentation for writing a plotting backend

A new guide, *Writing a Plotting Backend*, documents the interface a third-party plotting backend implements: the `PlottingBackend` protocol and its `BaseBackend` starting point, what each `create_*` method is handed (`ChartConfig`, `OverlayConfig` and `DualAxisConfig`, field by field), the `chartbook_plotting` entry-point group, and a complete Vega-Lite backend in one dependency-free file that ChartBook's own tests run through a real entry point.

Three things about the machinery itself were fixed or removed along the way. An entry point (or `register_backend()`) may now name a backend **class** as well as an instance; naming a class used to register something unusable. A third-party entry point that is not a backend is skipped with a warning instead of breaking the built-in ones. And two pieces of dead code are gone: the pluggy hook specifications in `PlottingHookSpec`, which nothing ever called, and `configure(default_backend=...)`, which nothing ever read. A registered backend is still reachable through `get_backend()` and not yet selectable from `plotting.line()` and friends, which always use the built-in `plotly` and `matplotlib` backends.

### Removed — **breaking: the `[all]`, `[data]`, `[plotting]` and `[sphinx]` extras**

The four install extras that became no-op aliases in 0.1.0 are gone, after the one release of notice they were given. `pip install chartbook` has installed everything since 0.1.0 and still does; drop the bracket from any requirement that has one (`chartbook[all]>=0.0.14` → `chartbook>=0.0.14`). pip and uv both still install the package for such a requirement rather than failing — uv warns that the extra does not exist — so nothing breaks at install time, but the bracket no longer names anything. The `[dev]` extra for contributors is unchanged.

### Added — a note on stability

{doc}`reference/stability` says plainly that ChartBook is experimental and anything can change between releases. Breaking changes are listed in this changelog with what to do about each. A real stability promise will come with 1.0.

### Added — incremental builds and a watch mode

`chartbook build --incremental` keeps the intermediate Sphinx project in `_docs/` and makes the next build redo only what changed. **`chartbook catalog build` now does this by default** — its working files live beside the catalog in `~/.chartbook/`, not in anyone's repository — and takes `--clean` to discard them and rebuild everything. A pipeline none of whose files changed — its manifest, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares, compared by modification time and size — is not regenerated. A page whose content comes out the same is left untouched, so Sphinx, whose cache is now kept, does not read it again. If no page changed, Sphinx is not run at all. Each build prints one line saying what it redid.

On a synthetic catalog of 40 pipelines and 411 pages, a clean build took about 20 seconds; an incremental build took 0.4 seconds when nothing had changed and about 5 seconds after one write-up or one data file changed. Within a pipeline, editing one chart's write-up re-renders that chart's page and the front page, not every page.

`chartbook build --watch` is the same thing in a loop: build, check the project's files once a second (`--watch-interval`), rebuild on any change, report a failed build and keep going until Ctrl-C. It is a single polling process — no server, no live reload, no new dependency. Refresh the browser to see a rebuild.

A plain `chartbook build` is unchanged: a clean build that leaves nothing behind. Adding or removing a page re-renders every page from Sphinx's cache, so navigation stays right; upgrading ChartBook, Sphinx or a theme starts over from nothing. The kept `_docs/` carries its own `.gitignore`.

Fixed along the way, because it defeated Sphinx's cache: the generated `conf.py` now sets `fontawesome_included` explicitly. The themes switched it on mid-build, which Sphinx read as a changed configuration and answered by re-reading every page on every run.

### Changed — `repo_url` and "code updated" come from git

Two things that should never have needed filling in by hand now come from the repository.

`[project] repo_url` defaults to the repo's `origin` remote, turned into a web address: `git@github.com:acme/rates.git` becomes `https://github.com/acme/rates`. Credentials embedded in a remote (`https://user:token@…`) are always dropped, and a remote that is a path on disk gives no URL. An explicit `repo_url` still wins. One consequence: a project with a remote no longer fails `chartbook check` for a missing `repo_url`.

The "Code updated" time on a pipeline's front page (and "Date of Last Code Update") is the time of the last commit that touched `src/`, `docs_src/` or `chartbook.toml`, when those are committed and unmodified. It was the newest file modification time, which on a fresh clone is the moment of the checkout — so every site built in CI claimed its code had changed just now. With uncommitted changes, or outside a git repository, the modification time is still used. Only a docs build asks git; loading a manifest (`data.load()`, `chartbook ls`) does not.

### Fixed

- `chartbook build --no-strict` on a single pipeline with a missing file crashed with `UnboundLocalError`. It now reports the missing files and exits cleanly; skipping only makes sense in a catalog, which has other pipelines left to build.
- Sphinx is now run as `python -m sphinx` with the interpreter that is running ChartBook. It used to run whichever `sphinx-build` came first on `PATH`, which could be a different Sphinx from a different environment.
- `project.readme` is honoured by `build` and `check`. Only `publish` read it; the others always looked for `README.md`.
- Importing `chartbook` no longer replaces `shutil.copy2`, `shutil.copystat` and `shutil.copymode` for the whole Python process. ChartBook still copies file contents without metadata, for the sake of shared drives, but does so in its own helpers.
- A pipeline site's front page listed two appendix documents that do not exist in a generated site, producing two Sphinx warnings on every build and forcing that page to be re-read on every run. The entries are gone.
- `chartbook create-data-glimpses` crashed on a numeric column with no non-null values.
- A pipeline loaded from the relative path `.` derived the name `pipeline` instead of its directory's name, because `Path(".")` has no name. The directory is now resolved first.
- `chartbook build --project-dir PATH` failed with `TemplateNotFound` unless it was run from inside the project, and `--temp-docs-src-dir` failed with any name other than the default. The pipeline's front page included a template by a path that spelled out `_docs_src/`, which only resolved when a directory of that name sat inside the project. It now asks for the template by name, as the guide already told people writing their own templates to do.

### Removed

- `create_data_glimpses.create_xml_report()`, which nothing called.

## [0.1.1] - 2026-07-23

### Changed — `install skill` defaults to user-level

`chartbook install skill` now installs to `~/.claude/skills/chartbook/` (honoring `$CLAUDE_CONFIG_DIR`), making the skill available in every Claude Code session rather than one repo; the previous per-repo behavior moved behind `--project`. The command is now idempotent ("already up to date" when the installed files match), removes files from older skill layouts on install, and records the installing chartbook version in a `.chartbook-skill-version` stamp.

## [0.1.0] - 2026-07-22

The format-v2 release. Everything below ships together: the breaking `chartbook.toml` redesign, catalog auto-discovery, single-install packaging, Sphinx 9 support, and rebuilt documentation.

### Changed — single install, extras retired

`pip install chartbook` now installs everything: data loading, plotting, the Sphinx documentation toolchain, and the `chartbook init` scaffolder. The old `[data]`, `[plotting]`, `[sphinx]`, and `[all]` extras remain as deprecated no-op aliases — specs like `chartbook[all]` still resolve and now install the same full package — and will be removed in a future release. `pandas-datareader` is now a declared dependency, so NBER recession shading (`nber_recessions=True`) works out of the box. The `[dev]` extra (contributor tooling) is unchanged. Longer term, the package may split into `chartbook-data` / `chartbook-plot` distributions that `chartbook` depends on; `pip install chartbook` will keep meaning "you get it all".

### Changed — Sphinx support widened to 9.x

The Sphinx constraint is now `>=7.2.6,<10` (was `<9.0`), verified against Sphinx 8.2 and 9.1 across pipeline, catalog, and API-doc builds. The test suite now runs a Sphinx version matrix (7.4 and 8.2 pinned on Python 3.13, with newer majors covered by the unpinned Python matrix), so every supported Sphinx major is exercised in CI.

### Added — catalog auto-discovery (`pipelines.members`)

A catalog's `[pipelines]` table now accepts reserved keys for glob-based membership, aimed at local catalogs so new projects join without `catalog add`:

- `members = ["../my_repos/*", ...]` — path patterns (relative to the catalog) whose matched directories join under their derived scoped IDs. Globs skip non-pipeline directories and catalogs silently; literal paths that are broken, v1-format members, and duplicate derived IDs are hard errors with "To fix" suggestions.
- `disabled = ["scope/name", ...]` — switch member pipelines off by ID (unknown IDs warn with a did-you-mean); `chartbook catalog disable/enable` maintains this list for member-discovered pipelines.
- `exclude = [...]` — paths removed from matching.
- Explicit entries coexist and override members pointing at the same directory; a plain string entry value is now shorthand for `{ path = ... }`.
- `chartbook catalog add` recognizes paths already covered by a members pattern, and manifest-loading errors in `build`/`ls`/`data` commands now print as clean messages instead of tracebacks.

### Changed — **breaking: chartbook.toml format v2**

The manifest format was redesigned; v1 files are no longer supported. Run `python scripts/migrate_toml_v2.py <project>` to rewrite a v1 file. The full specification and the reasoning behind each decision are in the {doc}`design doc <design/toml-format-v2>`.

- The `[config]`, `[site]`, and `[pipeline]` sections are consolidated into a single `[project]` table. Every field is optional with sensible defaults (`name` defaults to the directory name, `copyright` to the current year, `maintainer` to the first contributor, …). The minimal valid pipeline manifest is an empty file.
- `chartbook_format_version` is removed. Project `type` is inferred from structure (`[pipelines]` registry → catalog, otherwise pipeline); explicit `type` is allowed and contradictions are hard errors.
- Entity fields are de-prefixed across `[charts]`, `[dataframes]`, `[notebooks]`, and `[notes]` (e.g. `chart_name` → `name`, `dataframe_id` → `dataframe`, `path_to_parquet_data` → `path`, `topic_tags` → `tags`, `*_docs_str` → `docs`, `*_docs_path` → `docs_path`). Every entity's primary artifact is now `path`.
- **Scoped pipeline identity**: pipelines are canonically identified as `scope/name` (e.g. `ftsfr/crsp_treasury`), derived from the git remote and directory name. `data.load(pipeline=...)` accepts bare names (when unambiguous), scoped names, or repository URLs; ambiguous bare names error with candidates. `scope/name@rev` is reserved for future version pinning. Catalog `[pipelines]` keys are scoped IDs (quoted), with `path` replacing `path_to_pipeline`.
- **Catalog policy**: requiredness moved out of the format. A catalog may declare `[policy]` (`mode = "warn"|"strict"`) and `[policy.required]` field lists per object type; strict mode fails the catalog build on missing metadata. Defaults preserve the old diagnostics behavior.
- `build` replaces `build_commands`/`software_modules_command`: one string with shell-script semantics (multi-line values are one script).
- `site_dir` now defaults to `./docs_src/site/` when that directory exists.
- Unknown keys in `[project]` produce a warning with a did-you-mean suggestion, preventing silent field-name drift.
- Fixed: catalog builds now generate per-pipeline README pages and render every member pipeline with the catalog theme (previously only the first member used it and README pages were skipped).

### Changed — documentation overhaul

The documentation was rebuilt around user tasks for this release: a `chartbook init`-based quick start (verified end-to-end), two consolidated guides (*Documenting a Pipeline* and *Catalogs and Data Access*) replacing the per-noun user guide, and a CLI reference regenerated from the actual command surface (adding `catalog build/browse/disable/enable` and `--strict`, dropping invented environment-variable and exit-code tables). Sections documenting features that don't exist (Trino upload, `chartbook.excel`, `chartbook.spec_reader`) were removed, duplicated field references were consolidated into a single configuration reference under `reference/`, and the site now carries roughly a third of its former word count. Old page URLs under `user-guide/` moved accordingly.

## [0.0.21]

### Fixed
- `chartbook catalog build` and `chartbook catalog browse` now respect the custom catalog path set via `chartbook config`. Previously these commands always used the default `~/.chartbook/chartbook.toml` location, ignoring the `catalog.path` setting in `settings.toml`. ([#2](https://github.com/backofficedev/chartbook/issues/2))

## [0.0.20]

### Added
- New `chartbook install skill` command to install the bundled Claude Code skill into the current project. Copies skill files to `.claude/skills/chartbook/` so Claude can assist with chartbook projects. Supports `-f/--force` to overwrite without prompting. The chartbook Claude skill is now shipped with the Python package.

## [0.0.19]

### Added
- `notebook_name` is now automatically inferred from the first level-1 markdown heading (`# Title`) in the notebook when not explicitly set in `chartbook.toml`. This makes `notebook_name` optional — notebooks just need a `# Heading` cell and the title will be extracted for the TOC and sidebar.

## [0.0.18] - 2026-03-25

### Fixed
- Notebooks silently fail to appear in the sidebar and toctree when they lack a top-level markdown heading (e.g., jupytext-generated notebooks whose first cell is code). Chartbook now injects a title cell using `notebook_name` from the manifest before Sphinx rendering, and toctree entries use explicit titles so links are always generated.

## [0.0.17] - 2026-03-25

### Changed
- `chartbook catalog build` now defaults to `--no-strict` (lenient): pipelines with missing source files are skipped with warnings instead of failing the build. Use `--strict` to restore the previous behavior. `chartbook build` remains strict by default.

## [0.0.16] - 2026-03-23

### Added
- New `path_validation` module for detecting shell/platform path mismatches. Detects MINGW/Git Bash, Cygwin, and WSL environments and warns when Windows-style paths (e.g., `C:\Users\...`) are used in POSIX-like shells. Provides actionable suggestions with corrected paths (e.g., `/c/Users/...` for Git Bash, `/mnt/c/Users/...` for WSL).
- Path validation integrated into `catalog add`, `build`, `browse`, and `publish` commands, as well as TOML path resolution in `manifest.py`.

### Changed
- Renamed `validation.py` to `conf_validation.py` for clarity — it contains conf.py security validation, not general validation.
- Improved "No matching directories found" error in `catalog add` to show which paths were tried.

## [0.0.15] - 2026-03-22

### Added
- New `chartbook browse` command to open project documentation in your default browser. Works cross-platform (macOS, Windows, Linux). Accepts an optional output directory argument (default: `./docs`).

## [0.0.14] - 2026-03-22

### Added
- New `chartbook catalog browse` command to open global catalog documentation in your default browser.
- New `chartbook catalog add` CLI command for adding pipeline directories to the global catalog. Supports single paths, glob patterns (e.g., `/path/to/projects/*`), duplicate detection, and a `-y` flag to skip confirmation prompts.

### Changed
- **Breaking:** Replaced `--warn-missing` flag with `--strict` on both `chartbook build` and `chartbook catalog build`. The default behavior is now lenient: pipelines with missing source files are skipped with warnings and the build continues. Use `--strict` to restore the previous behavior of erroring on any missing file.

### Fixed
- Fixed empty Dataframes page in catalog builds. The toctree in `cb/dataframes.md` used paths prefixed with `cb/`, but since the file itself lives inside `cb/`, Sphinx resolved them as `cb/cb/dataframes/...` which didn't exist. Paths are now relative to the document location.

## [0.0.13] - 2026-03-11

### Fixed
- Charts silently fail to appear in the Chart List when TOML field values (e.g. `data_sources`, `topic_tags`) contain YAML-special characters like colons, brackets, or ampersands. YAML frontmatter values in chart templates are now quoted and escaped, and a post-generation validation step raises a clear error if frontmatter is malformed.

## [0.0.12] - 2026-03-09

### Added
- New `site_dir` option in `[pipeline]` for adding custom markdown pages alongside auto-generated documentation. Supports `index_toc.md` for explicit toctree control or auto-discovery of `.md` files. Site pages are copied to the docs root alongside the `cb/` directory.
- New "Build Pipeline Internals" user guide page documenting the two-stage build process, intermediate file inspection, template customization, and debugging tips.

### Changed
- All auto-generated content (charts, dataframes, pipelines, notebooks, diagnostics) is now placed under a `cb/` subdirectory in the built docs. This separates generated content from custom site pages and prevents naming conflicts. Relative links and template paths updated accordingly.
- `dodo.py` test tasks now produce JUnit XML reports, track file dependencies for incremental runs, and fail explicitly on test failures or errors.

## [0.0.11] - 2026-03-02

### Fixed
- `date_col` is now optional in `chartbook.toml` dataframe definitions. Previously, omitting `date_col` caused a `KeyError` crash during `chartbook build`. When not specified, date range fields display "N/A" in the generated docs.

## [0.0.10] - 2026-02-22

### Added
- Glob pattern support in `path_to_parquet_data` for hive-style partitioned parquet datasets. Use patterns like `_data/hive_dataset/**/*.parquet` in `chartbook.toml`. Polars `scan_parquet` handles these natively with automatic hive partitioning.
- New `format="polars_eager"` option for `data.load()` to explicitly request an eager Polars DataFrame.

### Changed
- **Breaking**: Default `data.load()` format changed from `"pandas"` to `"polars"`. The default now returns a Polars LazyFrame. Pass `format="pandas"` to restore the previous behavior.
- **Breaking**: `format="polars"` now returns a Polars LazyFrame instead of an eager DataFrame. Use `format="polars_eager"` for the previous eager loading behavior.
- `format="polars-lazyframe"` is now deprecated. Use `format="polars"` instead (which now returns a LazyFrame by default).

## [0.0.9] - 2026-02-19

### Added
- New `chartbook init` CLI command to scaffold a new chartbook project from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook). Wraps `cruft create` so projects can later pull upstream template updates. Requires `pip install "chartbook[all]"` (adds `cruft` dependency).

## [0.0.8] - 2026-02-17

### Added
- New `--strip-mathjax2/--no-strip-mathjax2` CLI flag for `chartbook build` (enabled by default). Automatically strips Plotly's MathJax 2 script tags from notebook cell outputs during the build, preventing them from conflicting with Sphinx's MathJax 3 and crashing LaTeX math rendering in the generated HTML.

## [0.0.7] - 2026-02-02

### Changed
- Configuration fields in `chartbook.toml` are now more forgiving with sensible defaults:
  - `logo_path` and `favicon_path` are now optional; missing values use default assets
  - `chartbook_format_version` defaults to current version instead of failing validation
  - `copyright` auto-generates current year when the key is missing (explicit empty string `""` still respected)
  - `charts`, `dataframes`, and `notebooks` sections are now optional (default to empty)
- Minimal `chartbook.toml` now only requires `[config]` section with `type = "pipeline"`

## [0.0.6] - 2026-02-01

### Added
- `data.get_docs(pipeline, dataframe)` returns the documentation content for a dataframe as a string (works with both `dataframe_docs_path` and `dataframe_docs_str` modes)
- `data.get_docs_path(pipeline, dataframe)` returns the path to the documentation source file (`.md` file for path mode, `chartbook.toml` for inline mode)
- New `chartbook ls` CLI command to list catalog objects:
  - `chartbook ls` lists all pipelines, dataframes, and charts in a tree format
  - `chartbook ls pipelines` lists pipelines only
  - `chartbook ls dataframes` lists all dataframes across pipelines
  - `chartbook ls charts` lists all charts across pipelines
  - Supports `--catalog` option to override the default catalog
- New `chartbook data` CLI command group for data operations:
  - `chartbook data get-path --pipeline <id> --dataframe <id>` prints the parquet file path
  - `chartbook data get-docs --pipeline <id> --dataframe <id>` prints the documentation content
  - `chartbook data get-docs-path --pipeline <id> --dataframe <id>` prints the documentation source path
  - All commands support `--catalog` option to override the default catalog

### Changed
- `data.get_path()` renamed to `data.get_data_path()` for clarity
- Data download links (Parquet/Excel) are now disabled by default in generated documentation. Set `enable_data_download = true` in the `[site]` section of `chartbook.toml` to enable them.

### Fixed
- Fixed "Linked Charts" not rendering correctly in dataframe documentation pages. The linked charts are now displayed as a bulleted list below the metadata table instead of inside a table cell.
- Extended full-width page layout to dataframe, pipeline, and diagnostics pages (previously only chart pages had full-width styling).
- Fixed Git Repo URL in pipeline manifest displaying a broken icon (box character) by converting it to a proper markdown link.

## [0.0.5] - 2026-01-26

### Added
- Catalog-aware data loading: `data.load(pipeline="yield_curve", dataframe="repo_public")` loads dataframes from registered pipelines in a catalog
- `data.get_path()` returns the resolved parquet path for a pipeline's dataframe
- `polars-lazyframe` format option for `data.load()` (returns `pl.scan_parquet`)
- New `chartbook config` CLI command to set the default catalog path in `~/.chartbook/settings.toml`
- New `chartbook.config` module for reading/writing global settings
- `CatalogNotConfiguredError` exception with actionable message when no catalog is configured

### Changed
- `data.load()` and `data.get_path()` now use `pipeline` and `dataframe` parameters (replaces `pipeline_id`, `dataframe_id`, `base_dir`)
- `tomli` and `tomli_w` moved from the `[data]` optional dependency group to base dependencies

## [0.0.4] - 2026-01-22

### Added
- New `--warn-missing` CLI flag for `chartbook build` to warn instead of error when source files are missing.

### Fixed
- Fixed notebook rendering in Sphinx documentation where notebooks were not appearing in the generated docs. The `notebook_list` was incorrectly using dictionary keys instead of the actual notebook paths, resulting in toctree entries missing the `.ipynb` extension.
- Build process now validates that all source files (notebooks, charts, dataframes) specified in `chartbook.toml` exist before starting the build. Missing files now produce a clear error message with the file path and the `chartbook.toml` entry that references it. Use `--warn-missing` to continue with warnings instead.

### Changed
- Standardized all docstrings across the codebase to use Sphinx-style format with `:param`, `:type`, `:returns`, and `:rtype` tags for improved API documentation rendering

## [0.0.3] - 2026-01-16

### Added
- New `chartbook.env` module (renamed from `chartbook.settings`) for project path management
  - `get_project_root()` function with configurable `start`, `markers`, `max_levels`, and `use_cache` parameters
  - `get_os_type()` function for cross-platform scripts (returns "nix", "windows", or "unknown")
  - `get()` function (renamed from `config()`) for reading environment variables and `.env` files
  - `clear_cache()` function to reset cached project root lookups
  - `ProjectRootNotFoundError` exception with helpful error messages
  - Backwards compatibility alias: `config = get`

## [0.0.2] - 2026-01-03

### Added
- New `chartbook.plotting` submodule for creating charts directly from DataFrames
  - Simple, consistent API for common chart types: `line()`, `bar()`, `scatter()`, `pie()`, and `area()`
  - `dual()` function for dual-axis charts combining different chart types on left and right y-axes
  - Built-in support for chart overlays: NBER recession shading, horizontal/vertical reference lines, shaded regions, confidence bands, and regression lines
  - `ChartResult` object with `.show()` for inline display and `.save(chart_id)` for multi-format export (HTML, PNG, SVG)
  - Global configuration via `configure()` for default output directory, backends, NBER recessions, and styling
  - `set_style()` for applying matplotlib styles, including a bundled "chartbook" style
  - Support for both Plotly (interactive) and Matplotlib backends
  - Rich annotation support: titles, captions, notes, and source attribution


### Added
- Initial release