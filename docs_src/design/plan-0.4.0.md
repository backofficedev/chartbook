# Design: the plan for 0.4.0

```{note}
A plan, written 2026-10-30, the day after 0.3.0 was released, from a conversation with the
maintainer that day. It says what 0.4.0 is for, the rule at its centre (a catalog is its stores,
and a machine may have several), and the order of the work. Status: **implemented in 0.4.0**. What the
maintainer decided on 2026-10-30 is marked *decided*; the original proposal labels below
are retained as design history. The fix for a
pipeline's page in a catalog, found the same day, is not part of this plan: it ships first, as
0.3.1 (the {doc}`../changelog`).
```

## What 0.4.0 is for

Three things came out of using 0.3.0.

**A store cannot be shared in part.** The maintainer's store is a Google Drive folder, synced
between their own machines, and it holds every pipeline: some for a course, some with a
co-author, some with licensed data that may be shared with no one. To give a co-author the data
of the one project they share, the maintainer can send a pipeline's folder (`store export`), but
then there are two copies, and each new snapshot is sent again. What they want is to share a
*folder* through Drive, as Drive is made to do, and have that folder be where that project's
snapshots live: one Drive folder per collaborator, each a store, each holding only what that
collaborator should see, and the maintainer's own machines reading all of them as one.

**A pin should be fetchable by a stranger.** A downstream pipeline commits its lockfile. Someone
who clones it, call them Bob, should be able to run it against the pinned upstream snapshot
without building the upstream, by fetching the snapshot from wherever the upstream publishes.
The lockfile already identifies a snapshot in a portable way: the pipeline, its repository, the
commit, and the content hashes that prove the bytes (the time is only there to tell two
snapshots of one commit apart). What is not portable is *where to look*, which today is a
setting of the machine and nothing else.

**The catalog should represent the stores.** *Decided 2026-10-30.* In the maintainer's words:
listing paths to working folders in the catalog was the mistake; "the catalog should have been a
list of stores all along." The store is the state of the pipelines, declared ready one snapshot
at a time, with the data dictionary and write-ups of each snapshot bundled in it
({doc}`versioned-catalog`). A catalog is the view of that: every pipeline in every store, every
version, each documented as it was then, and the same facts on the command line for a program.

So 0.4.0 is **the catalog as its stores**, and **several stores**. Nothing inside a store
changes: the layout, the records, the hashes and the lockfiles are 0.3.0's.

## The two files

*Proposed.* ChartBook has had two files in `~/.chartbook/`, `settings.toml` and the global
catalog's `chartbook.toml`, and the line between them was never written down. It is:

- **`settings.toml` says how this machine works**: `[cache] path`, `[git] path`, `[resolve]
  default_host`, `[catalog] path` (which catalog is this machine's). Nothing in it is about what
  exists.
- **A catalog says what exists**: the stores, and how to show them. Its file is **`catalog.toml`**
  (*decided 2026-10-30*: renamed from `chartbook.toml`, so that a `chartbook.toml` is always a
  pipeline's and a `catalog.toml` always a catalog's; 0.4.0 reads a `chartbook.toml` with
  `type = "catalog"` only to say "run `chartbook catalog migrate`"). The machine's own is
  `~/.chartbook/catalog.toml`. A team's is committed to a repository and names a bucket.
  `charthub.toml` was weighed the same day, the maintainer owning charthub.dev and thinking of
  it as a global catalog people plug into, and set aside: the file is named for what it is, not
  for a service that may read it; a hub is a *registry*, and the ID grammar
  (`charthub.dev/acme/rates`, {doc}`asset-graph`, "Reserving a future global namespace") and the
  resolution chain already keep a slot for one, so a catalog can list a registry later without
  renaming anything.

```toml
# ~/.chartbook/catalog.toml
[project]
name = "My Catalog"
maintainer = "Jeremy Bejarano"

[stores.mine]                                   # the first store is the default
url = "~/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/chartbook_cache"

[stores.lucy]                                   # a Drive folder shared with a co-author
url = "~/Library/CloudStorage/GoogleDrive-me@gmail.com/My Drive/chartbook-lucy"
pipelines = ["finm-33200/explaining_markets_data"]   # whose new snapshots are written here

[stores.jones-lab]                              # a folder someone shared with you
url = "~/Library/CloudStorage/GoogleDrive-me@gmail.com/Shared with me/jones-chartbook"
read_only = true

[stores.public]                                 # a bucket anyone may read
url = "s3://jeremy-public/chartbook"
pipelines = ["jeremy/upstream_data"]

[pipelines."acme/rates"]                        # optional notes on one pipeline
disabled = true                                 # hide it
repository = "https://github.com/acme/rates"    # which repository, when two claim the ID
```

- `url` is as `[store] url` was: a folder, `file://`, `s3://`, or a plugin's scheme; relative to
  the catalog's file if relative; `{ unix = "…", windows = "…" }` where one catalog serves two
  systems, as a pipeline path could. A store's name is one word (the rules of one part of a
  pipeline ID), so it can be an argument and a folder name. The first store written is the
  **default store**.
- **`[store] url` in `settings.toml`, and `CHARTBOOK_STORE`, stay.** `CHARTBOOK_STORE` set means
  the one and only store of the process, which is what keeps CI, the tests and a scratch run out
  of every real store. With it unset, a command reads the stores of the machine's catalog
  (`[catalog] path`, else `~/.chartbook/catalog.toml`); a machine whose catalog names no store,
  or has no catalog, uses `[store] url` from the settings (user's, then organization's), else
  `~/.chartbook/store`, as in 0.3.0. So a machine with nothing new behaves as it did.
- **A pipeline's `chartbook.toml` and `chartbook.lock` never name a store by path.** A
  dependency may name one by URL (below), because a URL is the same on every machine.

## The catalog is its stores

*Decided 2026-10-30.* A catalog lists stores, and shows every pipeline that has a snapshot in
any of them. It lists no working folders.

What that removes, and why it is right to remove it:

- **The catalog site no longer shows working copies.** A pipeline's folder as it is now is what
  the pipeline's own site shows (`chartbook docs build`), for its author; the catalog shows what
  its owner declared ready. To see work in progress in the catalog, snapshot it; a local store
  under `~/.chartbook/store`, listed beside the shared ones, makes that cheap when the shared
  store is in Drive.
- **Nothing a catalog does runs code or reads a folder you have not trusted.** Every page is
  rendered from a snapshot, in the sandbox a version's site is rendered in today. The trust
  prompt for a catalog's members, and `chartbook trust --members`, go; trust stays for building
  a pipeline's own folder.
- **`chartbook run` in a catalog** (every member's build script, in dependency order) and
  **`chartbook check` of a catalog's members** go with the folders. `chartbook run --upstream` in
  a pipeline already builds what it depends on; building a set of pipelines is a `dodo.py` or a
  shell loop, as the examples do. `[policy]` stays in the catalog: `chartbook check` in a pipeline
  reads the machine's catalog's policy as now, and the Diagnostics page is made from the
  snapshots' indexes.
- **`data.load(pipeline=…, dataframe=…)` through a catalog** reads the pipeline's newest snapshot
  and nothing else; with no snapshot it says to make one. The read of a working folder "with a
  louder warning" goes; a link file (below) is its explicit replacement.
- **`members` globs, `path` entries, and `chartbook catalog add`** go. *Decided 2026-10-30:* a
  pipeline enters a catalog in one way, by `chartbook snapshot`; the first snapshot of a new
  pipeline is how it is published, and the routing prompt (below) is where it is asked which
  stores should hold it. `[pipelines."id"]` keeps two notes: `disabled`, and `repository` (which
  repository's snapshots to show when two claim the ID). A *store* enters a catalog with
  `chartbook store add`.

A catalog with one store, the machine's `[store] url`, is a complete catalog with nothing
configured. The pipeline's own site, built from its folder, is unchanged.

## Working on two pipelines at once: `chartbook.links.toml`

*Decided 2026-10-30.* With no working folder in any catalog, one case needs a way to read a
folder: an upstream and a downstream being fixed together, where the fault in the downstream
is in the upstream, and committing and snapshotting the upstream after every change
(`chartbook snapshot` refuses uncommitted changes, `snapshot.py:2079`) is the friction. Today the
guide says to do exactly that ({doc}`../reference/cli`, "Working on two pipelines at once"), and
`data.load` falls back to a working folder, loudly, only when a pipeline has *no* snapshot at
all, which stops helping the moment one exists.

Every ecosystem with this problem answers it with a link (`npm link`, `pip install -e`, Go's
`replace`, Cargo's `[patch]`): local to the consumer, explicit, loud, never in the lockfile, easy
to see and remove. ChartBook's is **a file**:

```toml
# chartbook.links.toml — never committed. Reads of these dependencies come from working
# folders on this machine, not from their pins. Delete this file to use the pins again.
"finm-33200/upstream_data" = "../upstream_data"
```

- It sits beside `chartbook.toml` (what I declare) and `chartbook.lock` (what I pinned): what I am
  overriding, here, now. A path is relative to the pipeline's folder, or absolute.
- **Its existence is the switch.** A read of a linked dependency (`data.load`, `assets.path`,
  `chartbook path`) comes from the folder's built files, as a local read of that pipeline
  would, and warns once per process that the pin is not in use. `chartbook.lock` is untouched.
- **`chartbook snapshot` refuses while the file exists**, naming it: nothing could reproduce what
  this pipeline read. Delete the file, `chartbook update`, then snapshot.
- **`chartbook run` honors a link and marks the build**: `index.json` and the provenance panel
  say the build read a working copy of the dependency, at which folder and commit, with
  uncommitted changes or not; `chartbook check` lists every link; the site says so.
- **`pin` and `update`** work on the store as always and say "N link(s) in place, not used here."
  **`--frozen` and CI** ignore the file (its folders are not there), and a *tracked* links file is
  a `check` error. `chartbook init` adds it to the template's `.gitignore`.
- **`chartbook link ID FOLDER`** writes a line after checking that the folder's `chartbook.toml`
  gives that ID. There is no `unlink`: delete the line or the file. The file, not the command,
  is the feature, and a person who has forgotten the command can write the line.
- The `WorkingVersionWarning` fallback goes: a link is its explicit form.

## The commands: `run`, `docs build`, `catalog build`

*Decided 2026-10-30.* 0.2.0 made `chartbook build` mean "run the build script, then render the
site", after dbt ({doc}`overview`, "4c, as built"), and recorded two gaps it never closed: a
build script that renders the site itself, as the examples' and the maintainer's `dodo.py` do,
has it rendered twice; and `catalog build` disagreed with `build` about the word. In the Make
and doit world the task runner orchestrates everything, docs included, and ChartBook's job is to
be a good step inside it, not to wrap it. So, as `cargo run` and `cargo doc`, or `mkdocs build`:

| Command | Does |
|---|---|
| `chartbook run [SCRIPT]` | pins what has no pin, checks trust, runs `[scripts] build` (or SCRIPT); `--snapshot` declares the result ready; `--frozen`, `--upstream`, `--remake` as today |
| `chartbook docs build` | renders a pipeline's site; what `docs generate` did, with its options; `docs open` stays |
| `chartbook catalog build` | renders a catalog from its stores; what `catalog generate` did; `catalog open` stays |
| `chartbook build` | **removed**; prints: "`chartbook build` is gone. `chartbook run` runs the build script, which renders the site; `chartbook docs build` renders it alone." |

- The template's `dodo.py` ends with a task that runs `chartbook docs build -f`, as the examples
  already do, so plain `doit` makes everything and nothing renders twice (gap 3 of 4c closed).
- No `run --docs`: it would render twice for every script that already renders, and the script
  owns that step. A pipeline whose script does not render runs `chartbook docs build` after.
- The guard that stops a build tool whose task says `chartbook build`
  (`cli._stop_where_a_build_tool_says_chartbook_build`) becomes the message above; `chartbook
  run` called from inside the script it is running is refused, as today.
- Every occurrence of `docs generate`, `catalog generate` and `chartbook build` in the docs, the
  template, the examples, the Claude skill and the `.claude/skills` copies is changed.

## Several stores

### Reading: newest everywhere

*Decided 2026-10-30.* Where ChartBook chooses a snapshot (`pin` and `update` of a dependency
named by its ID, a catalog's "newest", `data.load` through a catalog), it takes **the newest
across every store it knows**, within the repository the pin keeps to, as if the stores were
one. No store ranks above another for reading, and no pipeline is tied to a store for reading:
tying by a path is not portable, and if a collaborator's own experimental snapshot is newer than
yours, that is theirs to manage, and perhaps what they wanted. Every `pin` and `update` says
which store the snapshot it chose is in.

Where ChartBook looks up a pinned snapshot (`data.load`, `run --frozen`, `restore`, `lineage`,
rendering a version), any store that holds it serves it; a snapshot in two stores is the same
snapshot (same folder name, same record, same hashes), and `kept_in` never crosses a store.
Where it lists, every store is read and every snapshot shown, each saying its store; one in two
stores is listed once.

Two repositories claiming one ID is the same case as today, only likelier (a fork in a
collaborator's store): the repository grouping in `lock._newest_in_store` applies before
"newest", a pin keeps to its repository across stores, and a first pin that finds two asks for
`repository = "…"`, which `chartbook add URL` now writes by default (*decided 2026-10-30*:
`chartbook add https://github.com/org/name` writes `"org/name" = { repository =
"https://github.com/org/name" }`, and the examples, the template and the docs use that form; the
ID already is the GitHub `org/name`, and a URL is normalized on input and never stored as
identity, so the grammar does not change).

### Writing: where a new snapshot goes

*Decided 2026-10-30: central routing in the catalog, set by a prompt once; the details are
proposed.* A new snapshot is written to the **default store** (the first in the catalog), unless
the catalog routes the pipeline elsewhere: a pipeline named in a store's `pipelines` has its
new snapshots written there, and a pipeline named by several stores is written to each (the same
bytes, each copy checked), which is how a public pipeline goes to the private store and the
public bucket at once. `chartbook snapshot --store NAME` says where to write this once. The
command always prints which store it wrote to.

The routing is set the first time, at a terminal, when `chartbook snapshot` meets a pipeline the
catalog does not route and the catalog has more than one writable store: it asks which, and
writes the answer into the catalog (`pipelines = […]`), as the trust prompt records its answer.
Unattended (no terminal, `CI`, `CHARTBOOK_BATCH`) it writes to the default store and says so.
The routing lives in the catalog and in no other file: it is the one table of which pipelines go
where, which is what a person checking what they share wants to read, and the Stores page
shows it. A per-project settings file was considered (a `.chartbook/` file in the pipeline's
folder, written on first snapshot); it was set aside for being a third file, uncommitted or
carrying names that mean something only where a catalog defines them.

**Data governance.** A store with `read_only = true` is never written. `pipelines` is an
allow-list: a pipeline not routed to a store is never written there except by `--store`, which
prints that it did. *Later:* a store marked `public = true` refuses a snapshot whose manifest
declares a `license` or `restrictions` that is not public, unless told.

A `git` dependency's files, which `pin` puts in the store from a clone, go to the default store.
An object no pipeline owns goes to the default store. A note under `roots/` is written to every
store that holds a snapshot the lockfile pins, since each store's `gc` reasons from its own notes
alone. An `origins` note goes with its snapshot.

### Portability: a store named by a dependency

*Proposed.* A dependency entry may say where the upstream publishes its snapshots, beside
`repository`:

```toml
[dependencies]
"jeremy/upstream_data" = { repository = "https://github.com/jeremy/upstream_data",
                           store = "s3://jeremy-public/chartbook" }
```

`store` is a URL, never a path (as `repository` refuses a path: it is not the same on another
machine). That store is read for this dependency as one more of the machine's stores: Bob clones
the downstream, and `chartbook run --frozen` finds the pinned commit in it and checks the hashes;
`chartbook update` takes the newest across the machine's stores and this one. Nothing is ever
written to it by a reader. In 0.4.0 the URL is a bucket (`s3://`, with an `?anonymous=true`
option on the S3 store for a public bucket, which it lacks today) or any scheme a plugin
provides. A static `https://` host is the obvious public store and is **later**: HTTP has no
directory listing, so the layout would need a listing file at the store's top, written by
`chartbook store export`, before an `https` store can find a snapshot. A Google Drive folder
cannot be fetched by URL: Drive is for people you share with, who add the synced folder as a
store.

The lockfile does not record the store a pin came from, which answers the open question in
{doc}`overview` ("whether a lockfile should record which store its pins were made into"): no. The
entry in `chartbook.toml` says where to look, portably; the lockfile says what to find; the
hashes say whether it was found.

### Stores that are not there, or named twice

- A store whose folder is missing (a Drive folder not yet synced, a disk not mounted, a shared
  folder taken back) is **unreachable**, not empty: a command that reads says so once, naming
  it, and goes on with the others; a command that would write to it stops. The default store is
  created when missing, as today; a named store is not.
- Two names for one store (the same folder resolved, or one URL) is an error in the catalog.
- `store info` lists every store in order, reachable or not, with what it holds.

### Clearing, verifying, moving

*Proposed.* `store gc` works one store at a time, from that store's own `roots/`, `origins/` and
snapshots; a file in store A is never kept for a note in store B. With no option it runs over
every writable store in order, each under its name, skipping a read-only or unreachable one with
a line; `--store NAME` does one. `store verify` and `store info` the same. `store migrate`,
`store export` and `store import` take `--store NAME`.

**`chartbook store move ID --to NAME`** is the command the maintainer asked for ("copy the files
to this new directory and delete them from the old megastore"): it finds every store holding
snapshots of the pipeline, owner-made and pin-made both; copies the pipeline's folder into the
target as `store import` does (every file re-hashed, nothing overwritten, what is there skipped,
so a target that has some of it is merged); copies the `roots/` notes that name its snapshots and
its `origins/` notes; removes the folder from the source only once every file is verified in the
target (`--keep` leaves it); routes the pipeline to the target in the catalog (`--no-route`
leaves the catalog alone); and says what moved and that a path `chartbook path` printed from the
old store is gone (a reader that calls `data.load` finds the snapshot again by itself). Between
two Drive folders the bytes are uploaded once more; `--dry-run` says how much.

**`chartbook store add NAME URL [--pipelines ID …] [--read-only]`** writes a `[stores.NAME]`
table into the catalog in place, comments kept (as `chartbook add` edits a manifest), after
reading the store: it refuses a URL that is not a store, one in the 0.2 layout (say `migrate`),
or one already listed; then lists the pipelines the store holds, which is what a person who was
just shared a folder wants to see. **`store remove NAME`** takes the table out and says the files
are untouched.

## The catalog as hubs over versions

*Decided 2026-10-30: the shape. Proposed: the details.* Every version of every pipeline is
rendered by one renderer, the one that renders a version's site from the store today
(`versions.render`: lay the snapshot out, build the pipeline's own site in the sandbox, keep it
under the cache by its fingerprint). The catalog's own pages are **hubs**:

- **A pipeline's hub**: its name, description and maintainer as its newest snapshot says them
  (plain text, as today for a store-only pipeline); its versions, newest first, each with its
  commit, date, store, tags and who pins it, linking to that version's site; its dataframes,
  charts, models and files as the newest snapshot lists them, each linking to its page there;
  its dependencies and what they are pinned to.
- **A dataframe's hub** (and a chart's, a model's, a files asset's): its name and description from
  the newest snapshot; its versions, each linking to the asset's page in that version's site,
  where the data dictionary is as it was then; and **what changed** between consecutive
  snapshots, computed by `chartbook index diff` from the `_chartbook/index.json` each snapshot
  carries: columns added and removed, a dtype changed, rows, the description. A version with no
  page for the asset (it did not exist yet) is listed as such.
- **The listings** (Pipelines, Dataframes, Charts, Models, Files) are over every pipeline's
  newest snapshot, each entry linking to the hub. **Versions** lists every version of every
  pipeline with its store. **Diagnostics** is metadata completeness over newest snapshots,
  against `[policy]`.
- **Stores**: a page listing each store in the catalog's order: its name, its location (a URL
  without credentials; a folder's path, which is this machine's), whether it is read-only or
  unreachable, the pipelines it holds with their snapshot counts, the newest snapshot in it, and
  which pipelines are routed to it.
- **`index.json` and `llms.txt`** carry the same: a `stores` list, and on every snapshot entry
  its store's name; the published copy of the index keeps store names and drops folder paths, as
  it drops machine paths today. `chartbook ls` gains `stores` and `versions`; `chartbook store
  info` prints the Stores page's facts.

A version's site is still rendered once per snapshot and kept; hubs are cheap and rendered every
build. Search covers hubs and the newest version of each pipeline.

**Making the store enough to render from.** A snapshot already carries what a site needs: every
asset with a `path` (the built notebook included, never run again), tables and queries as
parquet under `_chartbook/tables/`, the documents (`chartbook.toml`, `chartbook.lock`, the README,
every write-up, the site folder, logo and favicon, as git tracks them), and `_chartbook/index.json`
with each dataframe's columns, dtypes, rows, date range and one Series record per documented
column: the data dictionary as it was then. Three gaps in a version's site are closed, since
there is no working folder to fall back on: a table or query dataframe gets its columns and
glimpse from the parquet in `_chartbook/tables/` (planned in {doc}`versioned-catalog`, not built);
"updated" dates come from the snapshot's index, not the layout's time; `repo_url` comes from the
record's repository. jupytext sources are not needed: the built notebook is the asset.

## Migration

*Proposed.* `chartbook catalog migrate`, once, on each machine:

1. Renames the catalog's `chartbook.toml` to `catalog.toml` (`~/.chartbook/chartbook.toml` to
   `~/.chartbook/catalog.toml`), keeping `[project]` and `[policy]`.
2. Writes `[stores.default]` from the settings' `[store] url` (or `~/.chartbook/store`), so the
   catalog names what the machine used.
3. Drops `[pipelines]` paths and `members`, and lists in its output every pipeline that had a
   folder but no snapshot in the store, with the line to run (`chartbook snapshot` there) for it
   to appear in the catalog. `disabled` is kept.
4. 0.4.0 refuses a catalog that is still a `chartbook.toml`, saying to run this.

The settings' `[store] url` is read as the fallback (above) and warned about once per command
when a catalog names stores too, since it then does nothing.

## What does not change

- The store's layout, `chartbook/snapshot/v2`, every hash, every lockfile, the `Store` plugin
  API. Several stores are a layer above one store: a `Stores` object in `chartbook.store`, built
  from the catalog (or the settings' fallback), that answers `default()`, `for_writing(pipeline)`,
  `in_order()`, and `find`/`snapshots` across them; `default_store()` keeps working for the
  single-store case and for `CHARTBOOK_STORE`.
- A pipeline's own site (`chartbook docs build`), `chartbook run` in a pipeline, trust for a
  folder.
- `[dependencies]` and the ID grammar.

## The order of work

One pull request each, stacked, each adding its entry to `[Unreleased]`. Contract tests run
every store method against both kinds of store; a new `tests/test_several_stores.py` builds
machines with two and three stores on the pattern of `tests/test_shared_store.py`'s `drive`
fixture; a new `tests/test_catalog_from_stores.py` builds a catalog from stores alone, with the
repository gone, on the pattern of `tests/test_versioned_catalog.py`.

1. **`catalog.toml` and `[stores]`**, read and validated; `Stores`; the settings' fallback;
   `CHARTBOOK_STORE` as the only store; `store info` over every store; `catalog migrate`.
2. **Reading across stores**: the fan-in points (`snapshot.readable_snapshots`,
   `resolve._snapshots_in`, `snapshot.find`, `snapshot.newest_for`, `lock._newest_in_store`)
   search every store; the Versions page and `chartbook ls` list every store's snapshots with
   the store's name; "newest everywhere".
3. **Writing**: routing in the catalog, the first-snapshot prompt, `--store`, several stores at
   once, `read_only`, `roots/` notes to every holding store.
4. **`store gc`, `verify`, `migrate`, `export`, `import` over several stores**; `store add`,
   `store remove`, in-place edits that keep comments.
5. **`store move`.**
6. **`store = URL` on a dependency**; `?anonymous=true` on the S3 store; `chartbook add URL`
   writes `repository = URL`; examples, template and docs use it.
7. **The catalog from stores alone**: `[pipelines]` paths, `members`, `catalog add`, catalog
   `run`, member `check`, `trust --members`, and the working-folder read go; policy and
   diagnostics from snapshots.
8. **`chartbook.links.toml`** and `chartbook link`: reads follow it, `snapshot` refuses, `check`
   reports, `run` marks the build, `init` ignores it in git; the `WorkingVersionWarning` fallback
   goes. Tests in a new `tests/test_links.py`.
9. **The commands**: `docs build`, `catalog build`, `chartbook build` removed with its message;
   the template's `dodo.py` docs task; every doc, example and skill copy updated
   (`tests/test_cli_reference.py` and `tests/test_template.py` guard the rename).
10. **The three gaps**: table/query columns and glimpse from `_chartbook/tables/`, dates from the
    index, `repo_url` from the record.
11. **Hubs**: pipeline, dataframe, chart, model and files hubs with version lists and `index diff`
    between versions; listings over newest snapshots; the Stores page; `index.json`, `llms.txt`,
    `chartbook ls stores`/`versions`.
12. **Docs**: `reference/configuration.md` (a `catalog.toml` section, "Several stores"),
    `reference/cli.md`, `guide/catalogs-and-data.md` rewritten around stores,
    `guide/depending-on-pipelines.md` (Bob), `roadmap.md`, and {doc}`stores-and-backends` and
    {doc}`versioned-catalog` get a paragraph each pointing here.

## Breaking changes, for the changelog

- **A catalog's file is `catalog.toml`**, and a catalog lists stores, not folders: `[pipelines]`
  paths and `members` are gone; `chartbook catalog migrate` rewrites the file and says which
  pipelines need a snapshot to appear.
- **The catalog shows no working copy.** `chartbook run` in a catalog, `chartbook check` of a
  catalog's members, `chartbook trust --members`, `chartbook catalog add`, and `data.load`
  through a catalog of a pipeline with no snapshot are gone, each saying what to do instead. A
  pipeline enters a catalog by `chartbook snapshot`.
- **`chartbook build` is removed**; `docs generate` is `docs build`; `catalog generate` is
  `catalog build`. Each old form prints the new one. A build script's `chartbook docs generate`
  line must change.
- **The `WorkingVersionWarning` read is gone**; `chartbook.links.toml` is how a working folder
  is read, and `snapshot` refuses while one exists.
- **`CHARTBOOK_STORE`** names the only store of the process (there was only one before).
- **The catalog's pages are hubs**; the paths of a pipeline's page and of asset pages in a
  catalog's site change (version sites keep their paths).
- Nothing in a store, a lockfile, or a pipeline's `chartbook.toml` changes meaning.

## Not in 0.4.0

- A `https://` store (needs a listing file; `store export` would write it).
- A store named in a lockfile, or by path in any pipeline's file.
- A per-project settings file for snapshot routing.
- `public = true` governance checks against a manifest's `license` and `restrictions`.
- An upstream declaring where it publishes (`[project] published_at`), copied into a
  downstream's entry by `chartbook add`.
- The same bytes kept once across two stores or two pipelines; a snapshot folder named by hash
  rather than by time (the time orders; the hashes identify).
- Sharing part of a pipeline; the unit of sharing is the pipeline.
- Working copies back in the catalog, in any form. A link is a reading override for one
  consumer, never a catalog fact.
- `chartbook run --docs`, or any form of `chartbook build`.
- A registry (a hub such as charthub.dev) listed in a catalog, `[registries.<name>] url = …`,
  that resolves an ID to snapshots the way a store does. The grammar and the resolution chain
  reserve its place ({doc}`asset-graph`); nothing in 0.4.0 closes it.

## Open questions

Answered 2026-10-30 with the maintainer: the decisions marked above. Open:

1. Whether `chartbook run` across a set of pipelines is wanted back under another name (a
   workspace file), or whether `dodo.py` is the answer for good.
2. Whether the first-snapshot prompt should also offer to create a local scratch store when the
   catalog's only store is in Drive.
3. Whether `[scripts] build` should keep its name now that `chartbook build` is gone (it is the
   pipeline's build, run by `chartbook run`; `docs build` is the site's), or become `run`.
