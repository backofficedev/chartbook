# Changelog

All notable changes to chartbook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — a roadmap

The documentation has a roadmap page: what ChartBook does now (one machine, and a store in a shared or synced folder between machines), what is an early experiment (reading a Databricks SQL warehouse, which has been tested only against a stand-in for the warehouse), and what may come next (pinning a Delta table by its version, held for a test of Delta's retention on a real workspace; Snowflake; other warehouses as plugins; a database as the store; an MCP server). The Databricks pages, the stability page, the changelog entry and the assistant files mark the Databricks source experimental.

### Changed — `chartbook check` with no policy warns about the recommended fields

`chartbook check` failed a pipeline made exactly as the docs show, on eleven recommended fields (`units`, `frequency`, `providers`, `repo_url` and the rest). When no policy is given anywhere, with no `[policy]` in the pipeline, none in the catalog it is checked in and no `--policy` (or a `--policy` file with no `[policy]` table, as a catalog that sets none), the recommended fields are now `warning:` lines and do not make it exit nonzero, as the docs said of the default lists. With a policy it fails as before; a pipeline's own `[policy]` is named as "the pipeline's policy". An empty write-up (`docs_path` or `docs`) still fails it whatever the policy, since the format requires one. CI that relied on `check` failing on missing fields with no policy should add a `[policy]` to the pipeline or the catalog, or pass `--policy`.

### Fixed — what a new user's first two pipelines ran into

`chartbook.plotting` takes a polars DataFrame and a polars LazyFrame, which is what `data.load()` returns, as well as a pandas DataFrame: polars data is collected and converted to pandas inside, since the plotting backends draw from pandas, with a category or an enum drawn as text and a decimal as a float. Before, it refused anything but pandas.

A pipeline's page lists what it depends on. Under "Dependencies", each pipeline in its `[dependencies]`, as declared, with what `chartbook.lock` pins it to: the snapshot's commit and when it was made, or a repository's commit, or "not pinned yet". In a catalog, each links the other pipeline's page, in the snapshot pinned when the catalog shows that version. The template is `pipeline_dependencies.md`. Before, a second pipeline's site never named the first.

`chartbook create-data-glimpses -o DIR` with no such `DIR` wrote the report as a file named `DIR`; the directory is made now, a path ending in `.md` is still the report's own path, and an existing file of another name is refused with a plain message. Its `--help`, and those of `publish` and `install skill`, no longer show `:param` lines.

The site, in small ways. A chart with no tags, or whose dataframe names no sources, no longer gives ABlog an empty category or tag, so there is no `cb/charts/index/category/.html` and no empty "(1)" under Categories; nor does the MkDocs chart page write them empty. The chart, dataframe and pipeline tables leave out the rows of fields left out, as the docs said they did; the "Download Data as Parquet" row is in its table rather than below it, and the "Pipeline Web Page" link is closed. A dataframe's glimpse shows its first five rows, not the last one, with a float rounded to fifteen significant digits only when what is cut is the noise of a binary fraction (`3.85`, not `3.8499999999999996`): a whole number such as `20240115.0` or a sixteen-digit ID, and a value such as `1/3`, show as they are. "Dataframe Path" is the path as the manifest gives it, relative to the pipeline, not this machine's absolute one, and it and a table's name are set in as code exactly as written. Only the templates the build guide lists as overridable are read from a pipeline's or a catalog's root; a `CHARTS.md` or a `models.md` there no longer replaces a page of the site. A dataframe's linked charts are named by their address, `first_pipeline:chart/rates_chart`. The times a page shows are in UTC and say so: "Date of Last Code Update", the freshness line's hover text, and "Last updated" (from Sphinx 8, and in the MkDocs writer; Sphinx 7 gives the local time with its offset). The one exception is a chart's day in the chart listings, which is in the build machine's own zone and can differ by a day from the UTC "Chart updated": ABlog publishes a chart only when it is dated before the machine's next local midnight, and keeps a later one as a draft, out of every listing. A chart whose file is dated in the future is listed as of the build, for the same reason. `chartbook update` and `pin` print a hash as its first twelve digits, `sha256:4b1f9a0c2e3d…`; the lockfile keeps it whole.

`chartbook install --help` said it installs "into the current project"; it says what it does, user-level by default and into the current directory with `--project`. The `catalog build` reference compares its `--no-strict` default with `chartbook docs`, not `build`.

### Changed — a pipeline's ID is its repository's, whatever its folder is called

A pipeline at the top of a git repository with a remote is now named after the repository, from its `repo_url` or else its `origin` remote, and no longer after the folder it is in: `https://github.com/testorg/first_pipeline` cloned into `first-copy/`, or checked out in a git worktree, is `testorg/first_pipeline`, where it was `testorg/first_copy`. A pipeline in a subfolder of a repository is still named by its subfolder, one with no remote by its folder, and an explicit `[project] id` still wins. The reference, the guides, the skill files and `llms-full.txt` now give this one rule; the guide said `catalog add` took the repository's name and the reference said the folder's. Who this changes: a pipeline whose folder is not named as its repository is (a clone into another folder, a worktree, a renamed folder) gets a new ID with its next snapshot, `chartbook catalog add` keys it by the new one, and a dependency or a catalog entry that names the old one goes on seeing only the old ID's snapshots, and is now told so. A pipeline whose folder has its repository's name, one in a subfolder, one with no remote, and one with `[project] id` keep the ID they had. Found by a new-user test.

When an ID changes, this way or when a pipeline with no remote gets one, `chartbook snapshot` at a commit with a snapshot under the old ID makes one under the new ID, where it reused the old one when the bytes were the same; and what depended on the old ID is told. For a dependency named by its ID, `chartbook pin` and `chartbook update` say when the store has newer snapshots of the same repository and folder under another ID, and name the entry that follows it, `"first_pipeline" = { id = "testorg/first_pipeline" }`, where they said only `first_pipeline: 1 already pinned` (a `PinEvent` of status `id_changed`). `chartbook check` warns when a catalog's `[pipelines]` key is not what the pipeline in its folder calls itself now, since the catalog then shows only the old key's snapshots, and when a dependency named by its ID is a pipeline whose folder is on this machine (the catalog's own, or where the store says its snapshots were made) and that calls itself something else now.

Three more from the same test. `chartbook catalog add` works out the path it writes between the catalog's folder and the pipeline's with every link in both followed, as the catalog is read: with a home folder reached through a link (a cluster's home, a moved macOS home, `/var` on macOS) it wrote a path that named no folder, and `chartbook catalog build` failed with `No chartbook.toml found`; an entry written that way needs its `path` written again, or to be removed and added again. A pipeline the catalog shows from the store alone now has its assets, as its newest snapshot's own index lists them: in the catalog's index (`assets`, and each name as plain text in `asset_names`), on its page (its dataframes, charts and models), on the catalog's Dataframes page (its dataframes, after the catalog's own), each linked to its page in that snapshot's site, and in `chartbook ls`; a name is shown as the rest of the store's text is, never read as markup. And `chartbook ls` writes an asset as its reference, `first_pipeline:rates` and `first_pipeline:chart/x`, where it wrote `first_pipeline/rates`, which reads as a scoped pipeline ID.

### Added, experimental — a source in a Databricks SQL warehouse

`[sources.x] backend = "databricks"` names a Databricks SQL warehouse, and a dataframe in it is a `table` or a `query` there, read where it is: `data.load()` gives a lazy frame whose columns the warehouse gives at once and whose rows it sends when the frame is collected (`head(n)` asks for `n`), `data.sql()` runs in the warehouse, `data.ref()` gives the name with backticks, `data.connect()` the connector's connection, and the index and the site describe it from the warehouse when the site is built. The driver is behind `pip install chartbook[databricks]`. The `url` names the workspace's host, the warehouse's `http_path`, and optionally a `catalog` and `schema`, and holds no token. The machine signs in: its own URL for the source (`CHARTBOOK_SOURCE_<NAME>_URL` or `~/.chartbook/sources.toml`), or `DATABRICKS_HOST` and `DATABRICKS_TOKEN`, Databricks' own variables, or `auth=oauth` in its own URL for one sign-in in the browser per process. A token is sent only to the host the machine names; a manifest or another pipeline's record that names another host stops the read, and a manifest's URL that names a user, a token or a way of signing in does not load. A build of a catalog's versions from the store gets none of these variables. A query that names a file of the pipeline alongside a warehouse's table is refused, since the warehouse reads its own tables only. A snapshot records a warehouse table without copying it, and another pipeline cannot pin it yet: pinning a Delta table by its version comes next. The backends are now a package with an interface, `chartbook.backends.Backend`, and a backend other than DuckDB is found by its name in the entry-point group `chartbook.backends`, as a kind of store is in `chartbook.stores`; a manifest that names one nothing provides is refused with the list of those there are. The new guide page, Reading From a Databricks Warehouse, includes a test with Databricks Free Edition. Databricks was chosen first by the maintainer on 2026-10-17.

### Removed — `--from-folder` on `pin` and `update`

The hidden `--from-folder` option of `chartbook pin` and `chartbook update`, and `from_folder` of `lock.pin` and `lock.update`, are removed, with `PinReport.from_folder`. A lockfile never records a read of another pipeline's working folder, so every pin can be traced to the commit it came from. To see a change in a pipeline you are changing too, commit it, run `chartbook snapshot` there and `chartbook update` here; in a notebook, `data.load()` reads a dependency that has no snapshot yet from its working folder, with a `WorkingVersionWarning`, and pins nothing. A lockfile made with the option, whose pins name no commit, still reads: `chartbook update` moves it to a snapshot, `chartbook snapshot` says that its pin names no snapshot, and the messages that named the option say what to run instead. In `chartbook lineage --json`, such a pin's `kind` is `no_snapshot`, where it was `folder`. Decided by the maintainer on 2026-10-16 (decision 4b).

With it, three smaller things. A snapshot made again at the same commit with the same bytes, after the store has lost what it holds, is now made anew when its index or documents are gone, so that the newest snapshot is whole; before, the assets came back and the old record was kept without them. `chartbook pin` says when an asset that was not built in the snapshot it pinned is built in a newer one, and that `chartbook update` pins it. And `store gc` says that what it keeps is named by the lockfiles or a kept snapshot, when a snapshot keeps some of it, rather than by the lockfiles alone.

### Added — `[resolve] default_host`: a pipeline with no snapshot is cloned from its repository

Step 4 of decision 1a. A dependency named by its ID alone, `"acme/rates" = {}`, is still read from the store first; when the store has no snapshot of it at all and the machine or the organization sets a default host, `[resolve] default_host = "github.com"`, its repository there, `https://github.com/acme/rates` (or the one its entry names with `repository`), is cloned, checked to call itself by that ID, pinned from, and built by `chartbook run`, as a `git` dependency is; a pipeline the same run builds, such as another of a catalog's, is built first and never cloned. The host may also be an address the repositories are under, or a folder of them, and `""` sets none. The lockfile lists such a dependency as from its repository by the pipeline's ID, with no address, which each machine works out from its own setting; a pin keeps where a dependency was pinned from, the store or its repository, and puts back what the store has lost, and `chartbook update` takes the store's newest snapshot once there is one. A read never clones, and says that `chartbook pin` gets it. A bare ID, or the pipeline itself, is never cloned. `rev` on a dependency named by its ID, `{ rev = "main" }`, asks the repository what commit that is and takes the newest snapshot of that repository at or before it, walking its history back; with none, the repository at that commit, which `chartbook run` builds. A plain pin keeps what it has; `update` asks again. A read never asks.

### Changed — `data.load` before a pin: pin on the first read, warn, and stay quiet outside a pipeline

Reading another pipeline in a notebook no longer stops at the first missing step. A dependency that is declared and not pinned is pinned on the first read, to its newest snapshot, and the read says so on stderr, as `uv` writes its lockfile on first use; a `git` dependency is still not fetched by a read. A pipeline not in `[dependencies]` is read from its newest snapshot with an `UnrecordedReadWarning` naming `chartbook add`. One with no snapshot, whose folder is a `path` dependency or in the catalog, is read from its working folder with a `WorkingVersionWarning`. Outside any pipeline, with no `chartbook.toml`, a read takes the newest snapshot silently, and `data.load(pipeline=..., dataframe=...)` and `get_data_path` do the same: the store first, the catalog's folder only with that warning, and the catalog's own messages when it has neither. `chartbook run` sets `CHARTBOOK_BATCH=1` for `build`, and in a batch run every one of these but the pin is an error. A read through a catalog that lists the pipeline's own folder is a local one, and a reference by its own ID or the end of it, with no dependency known to be that pipeline, is refused rather than guessed at; a pipeline that lists its own folder as a dependency is refused by `chartbook pin`, as one that lists its own ID is; a dependency declared under another key is found by its ID; a model version (`@hash`, `@label`) is found among its repository's snapshots; an ambiguous bare name or a store that cannot be read is an error, never a read of a folder; a notebook in a catalog's folder reads as one in no pipeline does. A warning points at the line that read and says why there was no snapshot. `lock.pin` takes `only=`, the dependencies to pin, and pins of one lockfile now take turns, so that two first reads at once do not lose one. `chartbook data get-path` reports these errors without a traceback. Decided by the maintainer on 2026-10-16 (decisions 2c, 3b, 4b and 5b, silent).

### Added — a dependency named by its ID alone, pinned from the store; `chartbook add`

A `[dependencies]` entry with neither `path` nor `git`, `"acme/rates" = {}`, names the pipeline by its ID and is pinned from its newest snapshot in the store, found by that ID: no folder of it on this machine, and no clone. With a store a team shares, or a folder synced between machines, a pipeline in development reads another's data with no checkout of it. `{ id = "acme/rates" }` gives it a shorter name in code, and `{ commit = "3f2a9c1" }` takes the newest snapshot at that commit. The lockfile names the snapshot (`via: store`), `chartbook update` moves it, `chartbook pin --frozen`, `chartbook snapshot`'s lineage check and `chartbook lineage` treat it as they treat a folder pinned from a snapshot, `chartbook check` says when it is not pinned, `chartbook run` builds nothing of it, and `index.json` records it (`location.kind: store`). `chartbook add acme/rates [--as NAME] [--commit C]` writes the entry into `chartbook.toml` as text, keeping the file's comments, and pins it. `chartbook check` warns when a `path` dependency is in another git repository, or in none, which works on this machine only, and shows the entry that names it by its ID. A snapshot now records the repository it was made in: its web address (`repository`) and its first commit (`first_commit`), which needs no remote and survives a new URL. Two snapshots are of one repository when they share an address or a first commit (a moved repository, a rewritten history, a clone with a path remote; a fork, as a branch is), and two ways of writing one address count as one. A dependency named by its ID keeps to the repository it was first pinned from, or to the address `repository = "..."` names; a newer snapshot of its ID from another repository is not taken, and `pin` says so; an ID claimed from two repositories is not pinned until one is named; older snapshots that name no repository count as the one repository's when only one claims the ID. `store gc` keeps the newest, and what labels point at, within each repository, and what says which repository the kept ones are of (the newest naming an address and first commit together where they would otherwise split, or where a kept one is from a clone with a path remote; the newest naming the repository where the rest name none); a label is resolved among its own repository's snapshots and those that name none; `chartbook snapshot` reuses a record of its commit that says as much of its repository, so the main checkout makes its own once and a clone of it reuses that. A snapshot dated after now is never the newest, for `pin`, for a new snapshot of the same commit, or for `store gc`, which keeps it as recent unless it is dated more than `--keep-days` ahead. A pipeline cannot depend on itself by its ID. Decided by the maintainer on 2026-10-16 (decision 1a); the repository worked out from the ID by a default host is still to come.

### Added — a git tag names a version; `store gc --aggressive`

A snapshot records the git tags on its commit when it is made, and `chartbook lineage` and a catalog's Versions page show them: a git tag is a version's name, given with `git tag` and taken away with `git tag -d`. `store gc` already kept the newest snapshot a tag can pin from; a name keeps that snapshot only, not its lineage. `store gc --aggressive` lets names keep nothing: no snapshot is kept for a tag or a branch, or for a model label, so only what a lockfile pins, the newest of each pipeline and the last `--keep-days` days stay. Tag names from a store's records are taken only in a tag's shape. Decided by the maintainer on 2026-10-16.

### Changed — `store gc` keeps an unneeded snapshot for 7 days, not 30

A snapshot that nothing pins, that is not the newest of its pipeline (or the newest a branch or tag can pin from), and that no label points into is now removed after 7 days rather than 30, so a store stays small. `--keep-days` still sets it. Decided by the maintainer on 2026-10-16.

### Added — `chartbook lineage`

`chartbook lineage` walks a pipeline's lineage up from its lockfile, through every snapshot it is pinned to and every snapshot those were pinned to, and checks each step by hash: the snapshot is in the store, what was pinned is what it holds (each asset for the pipeline's own pins; the recorded hash over everything pinned, made again, upstream), each snapshot's recorded pins cover what its own kept manifest declares, and each asset is in the store. It prints the graph as a tree with each gap under its pipeline; `--check` exits 1 on a gap, for CI; `--rehash` hashes every asset again; `--json` prints the graph. `chartbook snapshot --deep` also refuses when a snapshot upstream has a gap. The walk is `chartbook.lineage.walk`; a record in the store that is not what ChartBook writes is a gap where it is met, never an error. `chartbook store gc --keep-lineage` also keeps every snapshot a kept snapshot was made from, and those holding the versions the labels of what it was made from pointed at, as far up as they go; by default a store keeps what work needs now and lets old lineage go, and the walk says so. Each snapshot records how its lineage was checked when it was made (`built_with.lineage`: `pins`, or `deep` with `--deep`), and the tree shows it, for audit.

### Changed — a snapshot carries its lineage

`chartbook snapshot` is made only when the pipeline's pins account for every dependency: the check `chartbook pin --frozen` makes (every dependency in the lockfile, pinned from where the manifest says, its bytes in the store); no `path` dependency pinned from its working folder, which names no commit; and each snapshot pinned from in the store, holding each asset pinned from it at its hash (and each pinned label naming a version some snapshot of it holds), so a lockfile changed by hand is caught. Nothing that cannot have been read stops it: an asset the other pipeline had not built when it was pinned, or a dependency of which nothing is pinned. Before, a pipeline with no lockfile was snapshotted with its inputs recorded as empty. Each gap is listed with what to run. `chartbook run --snapshot` makes the check after it pins and before it builds. Decided by the maintainer on 2026-10-16.

### Documented — a store in a synced folder

The configuration reference says how to keep the store in a folder that a sync service such as Google Drive keeps in step between your machines: a pipeline cloned on another machine reads what its lockfile pins from it, with the pipeline it depends on neither there nor built, and a catalog there shows every snapshot. It says what still needs the other pipeline's folder (choosing a snapshot), and four things to know (keep the files on disk, sync lag and `store verify`, `gc` from one machine, who can write). A test covers reading with the other pipeline's folder gone, for a folder store and an S3 store.

### Added — an assistant file for every site

Every build writes `llms.txt` beside `index.json`, in the form of [llms.txt](https://llmstxt.org): the site's name, then one line per pipeline, dataframe, chart and model with its name linking its page, its ID and, in quotation marks, its owner's description, so that an assistant on the command line finds its way around a site without reading its HTML. It says how to use an ID. A version's site says which snapshot it is and that its names and descriptions are its owner's; a catalog's file lists each pipeline's ten newest versions under it, each linking that version's own `llms.txt`, and the versions page for the rest. What an owner wrote never starts a line, so it can make no heading, list or link of its own. The writer writes it from the index, and an incremental build that changes nothing leaves it alone. Step 4 of {doc}`design/versioned-catalog`.

### Fixed — what a store holds is read as someone else's

- **The S3 store never writes outside its cache.** It made a file on the reading machine for every key under an object's prefix and every record key under `snapshots/`, wherever the key's path led: a key with `..` or a leading `/` wrote outside the cache, so anyone who could write to the bucket could write files on every machine that read from it. A key that is not a plain path inside its folder (on Windows, also one with a backslash or a colon) is now not a file of the object, or not a record, and is never downloaded; every path is checked to be inside the cache before it is written. `store gc` sizes, ages and deletes an object by every key under it, so an object of stray keys alone is removed rather than stopping it.
- **`store gc` reads only a lockfile on this machine.** A store notes each lockfile that pins into it, and gc reads each to see what it still pins; the note is written by whoever can write to the store. Only an absolute path named `chartbook.lock` that is not a network path is read now. Any other is not read: what its note names is kept, and `--forget-missing` does not forget it, so a lockfile in a project on a network drive keeps its pins as its last `pin` noted them. `store gc` says which lockfiles it did not read.
- **Text from the store keeps out HTML however it is read.** For a pipeline shown from the store, any character whose normalized form holds one of HTML's own characters (a fullwidth `＜`, a small `﹠`, `≮`) is caught as that character is; `&` is now written "and", which no normalization turns back; everything else stays as written (`R²`, `CO₂`); a name of blank fillers or combining marks is no name. The stored index is read up to 8 MiB, and long text is cut before it is looked at.
- **`chartbook catalog add` enables what it adds.** It takes the pipeline's ID off `[pipelines] disabled` in every case (a folder already listed, a new one, one filling in an entry shown from the store), and no longer fails on a folder listed by a plain path string.

### Added — a catalog can show a pipeline that is not on this machine

A `[pipelines]` entry with no path, `"acme/rates" = {}`, names a pipeline whose folder is not here: the catalog shows it from its snapshots in the store, its page named and described as its newest snapshot's own index says, linking its newest version and the Versions page. On a store a team shares, this is how to browse a colleague's pipeline without cloning it. What the snapshot says is shown as plain text, never read as Markdown or HTML (HTML's own characters as look-alikes, since a page title or a search index may decode the text again), and its repository and site only when they are web addresses: anyone who can write to the store wrote it, and the catalog's own pages are built as yours. `check`, `run` and the policy pass such an entry by; `chartbook ls` lists it as store only, and `data.load` through the catalog says it has no folder here. `chartbook catalog add` of a folder with its ID, or a `members` pattern that finds one, fills the entry in rather than making a second pipeline. A `[pipelines]` entry with a key other than `path` and `disabled` is now an error, so a misspelt `path` does not quietly become an entry with none. Step 3 of {doc}`design/versioned-catalog` is complete.

### Added — links follow pins

On a catalog's pages, a model's "Trained On" links its training data from another pipeline to its page in the snapshot it was trained on (a new index field, `trained_from`: the snapshot the model's pipeline was pinned to when the model's bytes were first snapshotted), and says when the pin has since moved; failing that, to the snapshot the lockfile pins for it; failing that, to the working version as before. The provenance panel links an input the lockfile pins to its page in the pinned snapshot. A link leads into a version only when the catalog shows it, and to the page that says why when its site could not be built; the catalog builds the versions' sites before its own pages, so it knows. An incremental build regenerates a pipeline's pages when any of this changes. A dependency's entry in the index says `key`, the name the pipeline knows it by, when that is not its ID; `chartbook index diff` words `trained_from` and a change only in which versions' sites were built. `chartbook store gc` now also clears the kept site of every snapshot it removes. Step 3 of {doc}`design/versioned-catalog`, in part.

### Added — a catalog shows every snapshot of every pipeline, each its own site

A catalog's site now has a **Versions** page and, under `versions/<pipeline>/<commit>-<time>/`, the site of every snapshot of every pipeline in the store, built from the store alone as the pipeline's own site, with the write-ups and the data dictionary as they were when its owner declared it ready. The page lists each pipeline's working version and its snapshots, newest first, with the commit, the date, whether `chartbook run` built it, and which pipeline of the catalog pins it. A version's site is built once on a machine and kept in the cache, so later builds only copy it; one that cannot be built gets a page that says why, and a `warning:` line. Each Pipeline record of the index lists its `snapshots`; a folder laid out from a snapshot has `from_snapshot`, and its front page says which snapshot it is. `chartbook index diff` says "N new snapshot(s)". Both writers, full and incremental builds. A version's files may come from a store a team shares, so its build runs as a build of files that are not the user's own: no template from its folder, every template in Jinja's sandbox, only pages and pictures from its site folder, no page taking in a file, no table or query run (a query can read any file), no path in its manifest outside its folder, nothing from outside the site, and a time limit. For every build, `conf.py` is now rendered from the package's own template, and a site page may not be `conf.py*`, `_templates/` or the tool's configuration. A snapshot record is checked when read, and `.` and `..` are no longer pipeline ID parts. Step 2 of {doc}`design/versioned-catalog`; links that follow pins across versions are next.

### Added — a snapshot holds the index of its version, and can be laid out as a folder

A snapshot now carries the pipeline's own index at that commit, in the published form, as an object in the store, and the documentation files a writer needs that are not assets: the manifest, the lockfile, the README, every write-up, the pipeline's own site pages, the logo and the favicon. So the description of the data is preserved with the data, and a version's site can be built from the store alone: `chartbook.snapshot.materialize()` lays a snapshot out as a folder, and `chartbook docs` builds a site from it with the repository gone. Only files git tracks are taken, only plain paths inside the pipeline's folder (nothing absolute on any system, no `..`, no `.git`, no `:`, asked of git literally), and no file that is a link or under one; git's names are taken exactly as git gives them, a store's object folder that is a link is refused, a document is read only if it is the very file that was looked at, and `.git` is refused in every form a filesystem may make of it; each document named and not kept is listed. A laid-out version keeps its pipeline's ID through a `.chartbook-version.json` and gets its models' recorded scores written back. `store gc` keeps these objects as it keeps the assets'. Git is now asked without taking optional locks wherever ChartBook looks at a repository's status. The reasoning, and the plan for a catalog of every version of every pipeline, is the new design page {doc}`design/versioned-catalog`; the vocabulary page now says how the snapshot and the index relate instead of saying they converge.

### Fixed — four links on the pages go where they say

A dataframe page's link to itself, a chart page's link to itself in its linked-charts list, and in a catalog a dataframe page's links to itself and to its pipeline, resolved to nothing in either site tool since the generator; Sphinx showed each as an anchor on the same page. So did a chart page's Parquet download link, and the Excel download link everywhere, since no Excel file is ever written: the first is relative to its page now and the second is gone; and in a catalog a pipeline without a `repo_url` showed an empty link. The link scheme is now relative to the page a link is on; both site tools' reports of an unresolved link are printed as `warning:` lines, and the MkDocs build tests, with downloads on and a model in the site, assert there is none.

### Added — a site can be built with MkDocs

`[project] writer = "mkdocs"` in `chartbook.toml`, with `pip install chartbook[mkdocs]`, and `chartbook docs` writes the same pages for MkDocs: the Material theme, search, notebooks through `mkdocs-jupyter`, the notes as pages, the chart listing written from the index, and the navigation written from the index into `mkdocs.yml`. `chartbook.writers.mkdocs.MkDocsWriter` reads the same index as the Sphinx writer and shares its templates where they are plain Markdown; a theme folder of its own holds the pages that differ. `pip install chartbook` still installs Sphinx and nothing of MkDocs; a manifest that asks for MkDocs where it is not installed gets one message naming the extra. A pipeline's own site pages are listed on the front page and in the navigation in the order of its `index_toc.md`, and one that carries a MyST fence is named in a warning. `--incremental` and `--watch` build with Sphinx and say so for an MkDocs site; `chartbook catalog build` builds whole when the catalog names MkDocs. The model page's versions table, which rendered as paragraphs in both tools, is a table now.

### Added — a test keeps the CLI reference in step with the CLI

`docs_src/reference/cli.md` is written by hand, in prose, because the reasons behind a command matter more than its signature. `tests/test_cli_reference.py` now keeps the hand honest: every command a user can run, a group that runs on its own included, has its `## chartbook <name>` section; a subcommand is named under its group's as `chartbook <group> <sub>` or by a `###` heading, and where it has a heading of its own its options are looked for there; every option, the program's own `--version` among them, is mentioned as a whole word by a spelling the CLI accepts, long or short (a section that says it takes the arguments of another command, as `build` does of `docs`, is read with that one); every positional argument is named or shown in use; and no heading or `chartbook <group> <sub>` line names a command the CLI does not have. This is what "regenerate the CLI reference from the CLI" came to: the page stays prose, and the CLI is its source of truth for what exists.

### Changed — `chartbook check` warns about a dependency that has no pin

A `path` dependency that is there but has no pin in `chartbook.lock` now draws a `warning:` line from `chartbook check`, saying that nothing of it can be read until `chartbook pin` or `chartbook run` (the build) pins it. It is a warning and not a failure because a fresh clone is in that state on purpose; `pin --frozen` and `run --frozen` remain the gates that fail on it. A lockfile this version cannot read is reported once, and no dependency is blamed for it. There is no `check --frozen`: the frozen check already exists under the commands that build.

### Added — the store can be an S3 bucket

`[store] url = "s3://bucket/prefix"`, with `pip install chartbook[s3]`, and every command and every `data.load()` work as they did: the bucket is laid out exactly as a folder store is, so `aws s3 sync` of a folder store into a bucket is this store. What a pipeline reads is read through a copy on this machine, under `~/.chartbook/cache/` (`[cache] path`, or `CHARTBOOK_CACHE`): the first read of a pinned asset downloads its files, checks that they hash to the object's name, and keeps them; `data.path()` is the path of that copy. Credentials are the AWS SDK's own and never in the URL, which may name another service with `?endpoint=` and a region with `?region=`. A bucket that is read-only for a machine serves `chartbook pin`, `run --frozen` and `data.load()`; what would write raises `chartbook.store.ReadOnlyStoreError`, which `pin` treats as it treats a read-only folder (the pins are in the store, only its note for `gc` is not left), and offline an object read and checked before is served from the cache. The store is found by its URL's scheme through the entry-point group `chartbook.stores`, which `chartbook.stores.s3.S3Store` is registered in, and it passes the same contract tests as the folder store. `pip install chartbook` installs no cloud library.

### Changed — the store is an interface, and a kind of store is a plugin

`chartbook.store.Store` is now what a store is: objects by content hash, the lockfiles that keep them, and the snapshot records. `FolderStore` is the implementation that is built, and the one every command uses today; `chartbook.store.store_for_url()` makes a store from a URL and finds another kind by the URL's scheme in the entry-point group `chartbook.stores`, so an object store or a database can be added as a plugin without a change here; `default_store()` reads the settings and calls it. The snapshot module no longer reaches into the store's folder. One thing a user could see changes: a store whose layout this version does not read is now refused when a pinned asset is read, as it is by every other command. `tests/test_store_contract.py` is what any kind of store must pass.

### Changed — settings are read in layers, and the store is a URL

An organization's settings file, `/etc/chartbook/settings.toml` (Windows: `%ProgramData%\chartbook\settings.toml`, or the file `CHARTBOOK_SYSTEM_SETTINGS` names), is read where the user's `~/.chartbook/settings.toml` is silent, key by key, below the environment variables and above the defaults. The store's setting is `[store] url`: a bare path or `file:///` is a folder, and another scheme names a kind of store a plugin will provide (none is built yet, and the setting says so). `[store] path` is still read as a folder, with a warning to rename it, and a user's `path` still wins over the organization's `url`. A relative folder in a settings file is relative to that file, not to where a command runs. A fault in the organization's file is reported and the file ignored; a fault in the user's names the file.

### Design — stores and backends

A design page, {doc}`design/stores-and-backends`, for keeping the same experience from a laptop to an organization's own storage: the store is a setting of the machine, never of the pipeline, read in layers (the environment, the user's settings, a system-wide settings file, the default) and given as a URL; which engine a pipeline reads from stays in its manifest, located by the machine; stores and backends become plugins behind extras, so `pip install chartbook` installs no cloud library; a warehouse pins a table by version where it can. The settings layers are built with it (above); the store interface is the next work.

### Added — a table or query is pinned, and read across pipelines

`chartbook snapshot` writes a dataframe that is a table or a query in a DuckDB file out as a parquet file into the store, under the dataframe's name. Its record keeps the source's location and carries the parquet's hash, so `chartbook pin` pins it, `data.load("rates:curve")` and `data.path()` read the pinned copy by name, a model trained on it records its hash and goes out of date when the table moves. A query's rows are written sorted on every column, so the same rows give the same bytes whatever order the engine found them in. A table the machine cannot write out (one in `:memory:`, one the engine cannot read, one with a column Polars cannot import) is recorded as not built, and the snapshot says why; A folder has no table to take, so `update --from-folder` keeps such pins from the snapshot, and a fresh `pin --from-folder` lists them as not built and says that a snapshot writes them out. The file is read on one thread, so that a floating-point aggregate gives the same bytes run after run; a query the author ordered keeps that order in the pinned copy, and only an unordered one is sorted. A reference to a table that was pinned before it was written out says what to do.

### Documentation — the site, in the vocabulary, with diagrams

The front page now says what ChartBook is in the words of the vocabulary page, with two diagrams: the chain *repository → index → pages → site*, and the four documents and what each records. {doc}`guide/how-the-build-works` is rewritten around the three steps the build actually takes (resolve the index, write the pages, build the site) and what the index holds; it had still described the generator and said nothing read the index. A new page, {doc}`guide/depending-on-pipelines`, gathers snapshots, pins, the lockfile, `chartbook run`, the frozen check for CI and model versions in one place, with a diagram, where they had been two sections of the pipeline guide. Getting Started ends by pointing at the index the build wrote.

### Changed — the build calls the Sphinx writer; the Markdown generator is gone

`chartbook docs` and `chartbook build` now write the site through `chartbook.sitefiles.write_site()`: the index first, then every page rendered by `chartbook.writers.sphinx.SphinxWriter` from the index and the files it names, then the files themselves copied beside the pages from the index's records (charts, notebooks, notes, downloads, the theme's files, a pipeline's own site pages). `chartbook.markdown_generator` is removed; what the writer had still imported from it lives in the writer. Two small behaviours change: a catalog copies no pipeline's site pages (it had copied the first pipeline's to the catalog root, where nothing listed them), and the folders for charts, notebooks and downloads exist only when something is copied into them. Fixed on the way: a project under a folder named `models`, `charts`, `dataframes`, `notebooks` or `site` got no theme files, since the names to leave out were matched against the whole path.

### Added — the Sphinx writer's fifth slice: the catalog's own pages

`SphinxWriter.catalog_page()` writes the catalog's landing page, its lists of dataframes, models and pipelines, and its diagnostics page from the `Catalog` record and the records of the site. The diagnostics are a comparison the writer makes, each record's declared fields against the policy the `Catalog` record carries, where the generator read back the CSV the build had written; the build still writes that CSV, which the page links to. The `Catalog` record gains a `location`, as a pipeline's has, dropped when published; the `Pipeline` record carries `copyright` and the `Model` record `metrics_path`, as declared, so a policy may require them. Aligned on both sides: the lists and the diagnostics rows are by name, as the index orders records, and an empty "Missing Fields" cell is empty on the page where it had read "nan". Decided with it: a pipeline that `--no-strict` leaves out of the build is not part of the site, so the catalog's lists and diagnostics leave it out (they had listed pages that did not exist). The loader now refuses a dataframe, chart, notebook or note key that cannot be part of an address, as it already refused a model's: the index left such an asset out while the pages showed it.

### Added — the Sphinx writer's fourth slice: the pipeline page

`SphinxWriter.pipeline_page()` writes a pipeline site's front page (the README's text with the tables of contents made from the records) and, in a catalog, each pipeline's README page. For it the `Pipeline` record gains `site_dir` and `site_pages`: the folder of pages a pipeline supplies for its own site and every Markdown file under it, so a reader of the index knows them without walking the folder; `resolved_path` is dropped from the published index as for every location. Decided with it: the front page lists notebooks and notes by name, as the index does, where it had kept the manifest's order.

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