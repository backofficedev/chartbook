# Design: the plan for 0.3.0

```{note}
A plan, written 2026-10-28, two days after 0.2.0 was released. It says what 0.3.0 is for, the new
layout of the store at its centre, and the order of the work. Status: **proposed; nothing in it is
built.** What the maintainer decided on 2026-10-28 is marked *decided*; the rest is *proposed*, and
much of it comes from a review of an earlier draft against the code, which is cited where it
matters. The layout inside a pipeline's folder was revised the same day, on the maintainer's
proposal.
```

## What 0.3.0 is for

Two things came out of using 0.2.0.

**A person cannot find their way around the store.** Everything in it is named by a hash or a
commit: `objects/sha256/7f/3a9c…/` and `snapshots/4f2a91c0…/_top/`. Nothing at its top says which
pipelines it holds, and one pipeline's data is spread among folders that every other pipeline's
data shares, so there is no one folder of it to send. The maintainer sends collaborators folders
for the projects they work on, and wants them able to add those to their own store by hand. The
wish, in the maintainer's words: *look in the store and see a short list of folders, one for each
pipeline*. Doing it with a command can come later.

**The store copies too much.** An asset of many files is stored whole for every version of it
(#135). In `finm-33200/explaining_markets_data`, thirteen yearly files of transcripts, 2.0 GB, are
one object, and the first snapshot after a new year makes another full copy, uploaded again to the
store in Google Drive. The 2026 file is in the store twice already, byte for byte. *Decided
2026-10-28: the store never holds a file twice.*

Both are about how the store lays out what it holds, so they are one change: **store v2**. The
rest of 0.3.0 is the issues that came in after the release (#133 to #136), most of which build on
it.

## The two hashes, kept

The store was designed around two hashes ({doc}`asset-graph`, "The store needs two indexes"). The
maintainer, on 2026-10-28:

- **Before**: a hash of the code that makes a dataset. If the code has not changed, the data
  should not have, so you can ask *do I already have the data I need?* without computing anything.
- **After**: the hash of the data itself, which answers *is the data I received the right data?*.
  It costs a build to know, and it is what proves the bytes.

*Decided 2026-10-28: the "before" hash is the git commit.* "That's honestly the simplest way and
probably the best way … I don't want to overcomplicate things." There is no input hash and no
build key. This is what 0.2.0 already does ({doc}`overview`, "4b, as built", under "Where the
design was wrong"): a snapshot maps a commit to what that commit built. What changes is that the
store now shows it. Every snapshot's folder is named by its commit, so "do I have this commit's
data?" is answered from a listing of folder names. `builds/`, the folder kept free for an
input-hash index, is not part of v2.

The "after" hash is unchanged. Every file's hash is written down in its snapshot, `store verify`
and `store import` check the files against it, and a lockfile pins what it pinned before. What a
snapshot was pinned to (its `inputs`) and which lockfiles pin it (the roots) are kept as they are,
so lineage still runs both ways.

## Store v2

*Proposed.* This revises a decision of 2026-10-12, "one directory per asset, named by its hash,
holding the asset's files under their own names" ({doc}`overview`, "Answers to the open
questions", 1).

```text
<store>/
  store.json                              which layout this is: chartbook/store/v2
  pipelines/
    ftsfr+fed_yield_curve/                one folder per pipeline
      2026-10-12T091500Z_4f2a91c0e1b2/    a snapshot: when it was made _ its commit
        _data/treasury_rates.parquet      the pipeline's files, in their own places
        _data/scraped_articles/article01.txt
        _data/scraped_articles/article02.txt
        _chartbook/                       ChartBook's own, the one name it reserves
          snapshot.json                   the dictionary: every file, its hash, its size,
                                          and which snapshot's folder keeps it
          index.json                      the pipeline's index at this commit
      2026-10-26T182205Z_9b1e22d7a0c4/    two weeks later: only what is new or changed
        _data/treasury_rates.parquet          changed
        _data/scraped_articles/article03.txt  new
        _chartbook/
          snapshot.json                   lists all four files; article01 and article02
          index.json                      are kept in 2026-10-12T091500Z_4f2a91c0e1b2
    finm-33200+explaining_markets_data/
    local_scratch/                        an ID with no scope
  origins/                                which folder, on which machine, a pipeline's
                                          snapshots were made from
  roots/                                  which lockfiles, on which machines, pin what
  tmp/                                    what is being written
```

Read from the top: the store's marker, the list of pipelines, and the store's bookkeeping. Inside a
pipeline's folder, its snapshots in the order they were made. Inside a snapshot's folder, the
pipeline's own files where the pipeline keeps them, as in a checkout of it, and one folder of
ChartBook's.

### The top layer

*Decided 2026-10-28: flat, under `pipelines/`.* One folder per pipeline, named by its ID with `/`
written as `+`: `ftsfr/fed_yield_curve` is `ftsfr+fed_yield_curve`. No part of an ID may contain
`+` ({doc}`toml-format-v2`; `identity.validate_pipeline_id`), so no two IDs share a name, and no
ID can be the name of one of the store's own folders. A folder sent alone goes straight back into
`pipelines/`, with nowhere else it could belong.

Nesting by scope (`pipelines/ftsfr/fed_yield_curve/`) was considered and set aside. A folder sent
alone would have to be put back under its scope, and a bare ID such as `rates` would collide with a
scope named `rates`.

**A folder's name is for people; what the folder is comes from inside it.** Each snapshot's
`snapshot.json` says which pipeline it is. The name alone cannot be trusted, for three reasons:

- IDs are case-sensitive, and the disks of macOS and Windows are not. `Acme/rates` and
  `acme/rates` would be one folder. So the name is the ID in lower case, and a name that is already
  another ID's folder gets `~` and eight hex digits of the ID's hash, as
  `snapshot.record_name` already does for subdirectories.
- Windows reserves some names (`con`, `nul`, `com1`, …) and drops a trailing `.`; such a name gets
  the same suffix.
- A sync service that meets two changes at once makes `acme+rates (1)`.

A snapshot whose `snapshot.json` names another pipeline than its folder is reported, by `store
verify` and wherever it is met, and is not read. (`versions.slug` cannot be reused for these names:
it writes `/` as `--`, which an ID may contain, so `a--b/c` and `a/b--c` come out the same.) One ID
can come from more than one repository, a fork or a repository that moved
(`snapshot.repository_groups`), so each snapshot keeps its repository and first commit, as now.

### Inside a pipeline's folder

*Decided 2026-10-28, on the maintainer's proposal: a folder for each snapshot, holding the
pipeline's files under their own names, in their own places, and each file once.* A file is kept in
the first snapshot that had it. A later snapshot's folder holds only what is new or has changed
since, and its dictionary says where the rest is kept.

That is the only way to have both real names and no copies on every kind of store. A file in ten
snapshots can appear in ten folders at no cost only by hard links. Google Drive has none (Drive for
desktop reports FAT32), and neither has a bucket. There, a file's bytes can be in one place only,
and the choice is which place. Two others were weighed the same day:

- **A pool of files named by their hashes** (`files/sha256/7f/3a9c…`), with the names in the
  records. It was simpler to write and stored each file once, but a person looking in the store
  saw only hashes.
- **A complete folder for every snapshot.** Readable, and a folder could be sent alone, but every
  snapshot copied every file again: #135's problem.

**A snapshot's folder** is named `<time>_<commit>`: `2026-10-26T182205Z_9b1e22d7a0c4`. The time
comes first, in UTC, so that sorting the folders sorts them by when they were made. Then the first
12 hex digits of the commit. `_` appears in neither part, so the name splits in two at it, and a
program needs nothing else to tell them apart. One pattern describes the name, and everything that
reads one (`snapshot._count`, `store._RECORD_NAME`, `lineage`'s search for a missing record) uses
it. The full commit and the time to the microsecond are in `snapshot.json`, and a lookup confirms
them there. A second snapshot of the same commit in the same second takes the next second's name.

*Decided 2026-10-28: the time is in the name, first.* A snapshot is not one to one with a commit.
The same commit can have several snapshots (decided 2026-10-13, {doc}`overview`, "The snapshot
model"): a pipeline that pulls data from outside, FRED or a vendor's API, gives other bytes next
week with no file changed in git, and `chartbook snapshot` after a `chartbook update` records new
pins with no new commit. The newest is the one a pin moves to.

- **The pipeline's files** that are new in this snapshot are at the snapshot folder's top, at the
  paths they have in the pipeline's folder: `_data/treasury_rates.parquet`,
  `_data/scraped_articles/article01.txt`. A snapshot's folder reads as the pipeline's folder does.
- **`_chartbook/`** is ChartBook's, and the one name in a snapshot's folder it reserves. Everything
  of ChartBook's in a snapshot is in it, and it is where anything ChartBook keeps with a snapshot
  later goes. *Decided 2026-10-28: `_chartbook`, which every system shows*, so a person finds the
  dictionary without showing hidden files. A pipeline whose own folder has a `_chartbook` at its top
  cannot be snapshotted; the message says to rename it. ChartBook writes nothing by that name in a
  pipeline's folder (its files there are named `.chartbook-…`, such as
  `.chartbook-hash-cache.json`), and a pipeline is unlikely to. The name is fixed by the layout: a
  later layout, with a new `store.json`, could change it for every snapshot at once, but it does not
  vary from one snapshot to another, so ChartBook never has to search for it.
- **`_chartbook/tables/`** holds a table or a query pinned as parquet (`<name>.parquet`). It has no
  place among the pipeline's files, because it was never a file there.
- **`_chartbook/snapshot.json`** is the dictionary, and it is the snapshot's record: the pipeline,
  the commit, the time, what it was pinned to, every asset with its content hash, and **every file
  of every asset**, with its hash, its size and the snapshot that keeps it:

  ```json
  {
    "path": "_data/scraped_articles/article01.txt",
    "content_hash": "sha256:7f3a9c…",
    "size_bytes": 5120,
    "kept_in": "2026-10-12T091500Z_4f2a91c0e1b2"
  }
  ```

  The record format grows to `chartbook/snapshot/v2`, since in v1 only a folder's record lists its
  files. An asset's own hash, which a lockfile pins, does not change: one file's hash, or the hash
  of its files' `sha256sum` listing ({doc}`index-schema`), which can be rebuilt from the dictionary
  and checked against it.
- **`_chartbook/index.json`** is the pipeline's index at this commit, which 0.2.0 keeps as an object
  so that any version's site can be rendered from the store alone ({doc}`versioned-catalog`). A
  version's documents are the pipeline's own files, so they are among them.

**`kept_in` is where to look; the hash is what is trusted.** A file found anywhere in the
pipeline's folder with the right hash is as good, which matters when two copies of a folder are
merged by hand (below).

**Nothing in the store is moved or rewritten once it is written.** A snapshot adds a new folder,
and only `store gc` removes anything. That is what makes a store in a synced folder, a bucket, and
a folder copied by hand safe.

**An object belongs to the pipeline that made it.** Ten projects that pin one upstream share one
copy, in the upstream's folder. The same bytes made by two different pipelines are stored twice.
That is rare, and it is the price of a folder that can be sent alone. A `git` dependency's files,
which `pin` puts in the store from a clone rather than from a snapshot its owner made, are a
snapshot of the same shape in the dependency's folder. Its `snapshot.json` says it was pinned from
a clone, not made by the owner, and a pin by ID from the store chooses only snapshots their owners
made, as today.

*Decided 2026-10-28:* **the store keeps only its own bytes.** A file goes in by a copy-on-write
clone or a copy, never by a hard link or a symlink to a file outside the store. In practice nothing
changes: every caller of `put` already asks for exactly those two (`snapshot.LINKS`, and
`lock.PIN_LINKS`, which is the same). The ladder of four (reflink, hard link, symlink, copy)
moves to reading (below). This revises "the store keeps all four kinds" (2026-10-12).

**Writes are ordered, so that a half-made snapshot is never taken for a whole one.** The files go
first and `_chartbook/snapshot.json` last: a folder without it is not a snapshot yet. A snapshot that reuses
files kept in earlier folders first leaves a note of them in `tmp/`, and `store gc` keeps what such
a note names for an hour (`RECENT_SECONDS`). The note does what v1 does by updating an object's
time (`os.utime` in `FolderStore._move_into_place`), without changing a file a sync service would
then carry to every machine.

### Later: a snapshot with its code

*Decided 2026-10-28: this waits; it is not in 0.3.0.* It is written down here because the layout is
made to leave room for it. From the maintainer's idea, the same day: because a snapshot's folder
holds the pipeline's files in their own places, it can hold the pipeline's code as well as its data,
and be the whole pipeline at that commit. Or it can hold the data alone. Which one would be the
owner's choice:

- **A snapshot an owner makes would hold the data alone**, as now, unless the owner asks for the code
  too (`chartbook snapshot --with-code`, or a setting in `chartbook.toml`). A pipeline whose code is
  not to be shared shares its data and nothing else.
- **A `git` dependency's snapshot would hold its code**, since it is made from a clone of code the
  pipeline that pinned it can already read.
- **The code is what git has committed at the commit, and nothing else.** So never a `.env`
  (`chartbook.snapshot` already keeps nothing of it), and never a file git ignores. It is kept once,
  in the first snapshot that had it, as data is.
- **Code in the store is never run there.** Reading a snapshot, or rendering a version's site from
  it, runs nothing ({doc}`trust`).

The maintainer also asked whether a `git` dependency could be cloned into its snapshot's folder and
built there, leaving the data in place. The result would be the same folder, but built elsewhere
and then put in the store:

- A build writes scratch (caches, logs, an environment) and can fail half-way. In the store, all of
  that would be in a snapshot's folder, and a store in a synced folder would upload it as it was
  written.
- Until the build was done, another machine, or a pin, could take the folder for a snapshot.
- Code run inside a store that a team shares could change anything else in it.
- A clone's `.git` folder is thousands of small files that hold the code a second time.

So ChartBook would build where it builds today, in its own working copy of the commit
(`gitcache.work_copy`, under `~/.chartbook/git/`). When the build had succeeded, the committed
files and the data it made would go into a new snapshot's folder, in their places, and nothing in
the store would be written by the build itself. To run a pipeline from a snapshot that holds its code, a person copies
the folder out of the store first.

### What does not change

- How anything is hashed. Every content hash in a record, a lockfile or a root means what it meant.
- `[store] url`, the settings layers, and pipeline IDs.
- A bucket holds the same layout as a folder.
- A lockfile still has no path into the store. It gains one field: each dependency records the
  pipeline whose folder holds what it pinned, so a reader knows where to look. Today only a
  dependency pinned from the store, or named by its ID, records it. For a lockfile without the
  field, the pipeline is found once per dependency, from the snapshot it is pinned to, or else by
  looking in each pipeline's folder.

### Reading: in place, or gathered

A file in the store now has its real name in its real place, so it can often be read right where
it is. `data.path()` then answers with a path into the store that ends in `.parquet`. That happens
when an asset's files are exactly what one snapshot's folder holds for it: a single file, or every
file of a folder in the snapshot that first had them.

An asset whose files are kept in more than one snapshot's folder is **gathered**. Its files are laid
out together in the machine's cache, `~/.chartbook/cache/views/<hash>/`, by reflink, then hard
link, then symlink, then copy. That is what `data.load` needs to read a partitioned dataset through
its `year=2024/` folders, and what a model loader needs to open a folder of named files. On this
machine's own disk a gathered asset costs nothing, by hard link. From Google Drive or a bucket it
costs one copy, in the cache and not in the store, as an S3 store's reads do today. On Windows
nothing is gathered by symlink, which needs rights a user may not have.

- `Store.get` is handed the asset's entry from the dictionary, so it knows every file's name and
  place, and never guesses from a bare hash.
- A gathered asset is laid out in a temporary folder and renamed into place, so a reader never
  meets half of one.
- An S3 store downloads each file into the cache and checks its hash as it arrives. That replaces
  the notes of verified names it keeps today.
- **The promise of `chartbook path` holds.** It says the path it prints "stays as it is until
  `chartbook update`", and other tools (Make, R, Stata) keep that path. A file in the store is never
  moved, and a gathered asset that this machine's lockfiles pin is never cleared from the cache.
- `snapshot.materialize`, which lays out a version for its site, links the files straight into
  place.
- `Store.lacks`, and pinning's "the same bytes under another name", go away. A name is a fact of
  the dictionary.

**A half-synced store.** A sync service may show a file before all of its bytes have arrived, and
`Store.incomplete` is how ChartBook says "not fully synced yet" instead of reading a cut-off file.
Every file's size is in the dictionary now, so it is one comparison per file. A snapshot whose
`snapshot.json` has not arrived is not there yet.

### Finding a snapshot

- **By pipeline**: list that pipeline's folder. Today every record in the store is read and then
  filtered by pipeline (`lock._newest_in_store`, `resolve._snapshots_in`, the catalog,
  `chartbook.versions`), so this gets faster.
- **By commit and subdirectory**, for a dependency that is a folder on this machine: look in the
  folder of that folder's ID first. Then look across every pipeline by folder name (`*_<commit12>`,
  one listing per pipeline and no file read), and confirm the full commit and the subdirectory in
  `snapshot.json`. This search must not depend on the ID. The ID worked out from a
  folder changes with no new commit, when a remote is added or a clone is renamed
  (`identity.derive_pipeline_id`), and an older snapshot would otherwise be lost to every pin,
  model version and `restore` that looks for it.
- **By commit and time**, which lineage and `store gc` do: the same search by folder name.
- **A pipeline whose ID changed** (`lock._under_another_id`, `_repointed`) is still found by the
  repository and first commit in its snapshots.

### Clearing old snapshots

`store gc` keeps the same snapshots it keeps now, by the same rules ({doc}`overview`, "Clearing
old snapshots"), worked out within each pipeline's folder. What changes is how files are kept:

- A file is removed only when no kept snapshot's dictionary names it and no root names its hash.
  If any kept snapshot's dictionary cannot be read, nothing is removed.
- **A cleared snapshot's folder keeps the files that later snapshots use.** Its
  `_chartbook/snapshot.json` goes, a `_chartbook/CLEARED.txt` says when it was cleared and why files
  are left in it, and the folder goes once nothing in it is used. Nothing is moved, so no other snapshot's dictionary goes out of date.
- A second copy of a file in one pipeline's folder, which a merge by hand can leave, is removed,
  and the first is kept.
- Files a note in `tmp/` names are kept, as above.
- *Decided 2026-10-28:* `pipelines/+unowned/` (from migration, below) is cleared once no root
  names what is in it.
- What `gc` says it will free counts each file once, and says which files are shared between
  snapshots.
- Names that are neither a pipeline's files nor ChartBook's, such as the `(1)` copies a sync
  service makes of `snapshot.json`, are removed once they are an hour old.
- A pipeline's folder deleted by hand is not an error to `gc`. A lockfile that pinned it says "not
  in the store", and what to do, as it does today for a missing object.

### Windows and long paths (#136)

Windows refuses a path longer than 260 characters unless long paths are turned on, which is off by
default and needs an administrator. The error it gives, "No such file or directory", points the
wrong way (#136). Every name in the layout spends from that limit. The flat top layer puts the
pipeline's ID in every path, so the maintainer asked that this be weighed before it was chosen.

| | The longest paths in the store |
|---|---|
| v1 | the root + 82 + the asset's own path, for a file. A record's temporary file is the root + 93: #136's root of 174 made 267 |
| v2 | the root + 44 + the folder's name + the file's path in its pipeline. `snapshot.json` is the root + 68 + the folder's name |

The pipeline's own paths are back in the store, because that is what makes it readable: they are
the paths the pipeline already has in its own folder. For an ordinary file, v2's paths are shorter
than v1's. A deep partitioned dataset is where the room goes. With a folder name of 34 characters
(`finm-33200+explaining_markets_data`):

| Store root | Length | `_data\treasury_rates.parquet` | `_data\trades\exchange=XNAS\symbol=ABCD\date=2026-10-27\part-0.parquet` |
|---|---|---|---|
| `C:\Users\<name>\.chartbook\store`, the default | ~35 | 141 | 182 |
| `G:\My Drive\chartbook_store` | ~27 | 133 | 174 |
| `C:\Users\<name>\OneDrive - The University of Chicago\chartbook_store` | ~70 | 177 | 218 |
| #136's temporary folder | 174 | 280: too long | 321: too long |

So the root can be up to about 153 characters for a pipeline of ordinary files, and about 112 for
one with folders that deep. What 0.3.0 does about it:

1. **On Windows the store's own paths are extended-length.** `FolderStore` keeps its root in the
   `\\?\` form, which Windows exempts from the limit without the registry setting. One helper strips
   the prefix for messages, and the check that a file stays inside the store compares paths in the
   same form. It is tested on the Windows CI, under a long root.
2. **A reader is handed a path in the store only when it fits.** Polars, DuckDB and a user's code
   may not take `\\?\` paths, so on Windows an asset whose paths in the store are too long is
   gathered into the cache, under the home directory, instead.
3. **Internal names are short**: temporary names of 12 hex digits, and a snapshot's folder name of
   31 characters.
4. **The error says what happened**: the path's length, the limit, and the two ways out (turn on
   long paths, or use a shorter store folder).
5. **ChartBook checks before it writes**, since it knows every path a snapshot will make, and
   `chartbook store info` warns when a pipeline's longest path leaves too little room.

One thing this does not fix: File Explorer is not long-path aware. A person who copies a pipeline's
folder by hand out of a store whose paths pass 260 characters can still be stopped by Explorer.
Keep the store's root short.

## Sharing one pipeline

**By hand**, as the maintainer does now: copy `pipelines/<folder>/` into the other store's
`pipelines/`. The collaborator gets the pipeline's files under their own names. Nothing in the
folder changes once written, so copying it into a folder of the same pipeline that is already there
is a merge: snapshot folders that are new are added, and those that were there are the same. The
other person's pipelines then pin it by its ID, with `chartbook pin` and `chartbook update`, as a
dependency named by its ID alone already works.

*Proposed:* **`chartbook store export <id> --to <folder>`** writes the pipeline's folder as a store
holds it. With `--latest`, or `--snapshot …`, it writes only those snapshots, each with every file
it needs in its own folder: one complete snapshot, readable without ChartBook, that can be dropped
into a store like any other. *Decided 2026-10-28 ("we should never duplicate files"):* there is no
`--readable` copy beside it, since the export is readable already.

**`chartbook store import <folder>`** checks every file against its dictionary, copies in what the
store does not have, and copies no file it already holds; nothing is overwritten. A folder copied in
by hand is read as it is, as a shared store is; `store verify` checks it.

What a pipeline's folder carries is data, the dictionary, and the documents a version's site is made
from. It carries no code that runs.

## Moving a store from v1 to v2

*Proposed.* `chartbook store migrate`, once, on one machine.

1. **Every machine that uses the store is upgraded to 0.3.0 first.** 0.3.0 refuses a v1 store and
   says to run `chartbook store migrate`.
2. **0.2.0 does not refuse a v2 store by itself.** It reads snapshot records without checking
   `store.json` (`FolderStore.snapshot_files` and its neighbours), so it would say that there is no
   snapshot. `migrate` therefore leaves a record under v1's `snapshots/` that 0.2.0 reports as
   unreadable: a warning in a catalog, a refusal in `store gc`. This is to be tried against an
   installed 0.2.0.
3. **Each file goes to the first snapshot of its pipeline that had it**, at its place in the
   pipeline. Snapshots are taken in the order they were made.
4. **Files are moved by renaming**, so a store in a synced folder uploads nothing again. Where two
   pipelines' snapshots name one v1 object, the second gets a copy. In a bucket, a move is a copy on
   the server followed by a delete.
5. **`pipelines/` is built beside `objects/`; `store.json` is switched; the v1 folders go last.**
   An interrupted `migrate` is run again and goes on. `--dry-run` says what it would move and how
   much it would read.
6. **What it costs.** A v1 record of a glob has no hash for each file, so those files are read and
   hashed once. In a Drive that streams its files, that downloads them. `--dry-run` says how much.
7. **Where each object goes.** To the pipeline of the records that name it. Else to the pipeline a
   lockfile on this machine says it is. Else to `pipelines/+unowned/<hash>/`, with its files under
   their names. `+unowned` is a name no ID can have. A `git` dependency's files there are put in
   their own pipeline's folder by its next `chartbook pin`, as 0.2.0 already puts them back from a
   clone, and `store gc` then clears them.
8. **v1's notes of origins** go to `origins/<folder>/legacy.txt`, which every machine reads.

## The rest of 0.3.0

*Decided 2026-10-28: these are in 0.3.0.* Each issue has its own "Done when"; what is here is how
it meets store v2.

**#135, multi-file datasets, the rest.** Storing each file once is store v2. Besides that:
`data.load(format="pandas")` and `"polars_eager"` read a glob, as `"polars"` does. A dataset's page
lists its files, with sizes, and its partition keys. `chartbook check` warns about a path that names
one file of a set (`transcripts_2026.parquet` beside 2014 to 2025). `assets.files()` returns an
asset's files, read from the dictionary.

**#134, tables stored as CSV, JSON lines or Arrow IPC.** One reader, shared by `data.load`,
`data.sql`, the glimpse and the data dictionary, which choose a reader separately today. `format`
and `read_options` on a dataframe. Hashing and the store do not change: they never cared what the
bytes are.

**#133, files that are not tables.** A `[files.<name>]` kind, with `chartbook.models` as the
pattern: ChartBook moves, versions and documents the bytes, and never opens them except for a
bounded preview. `assets.files()` and `assets.index()`, the second a table of the files with their
sizes and hashes, which the dictionary already holds. A `[dataframes]` path that is not a table
ChartBook reads fails `chartbook check` with "declare it under `[files]`". It comes after #134 for
that reason.

**#136, long paths on Windows.** The section above.

**Housekeeping.**
- #9 (`data.load` over SQL) was built and released in 0.2.0, and was closed on 2026-10-28.
- The project template's CI runs `chartbook check --skip-outputs`. This was waiting on 0.2.0
  being on PyPI ({doc}`overview`, "Open questions"), and it is.

## The order of work

One pull request each, stacked, as step 4 was. Each adds its entry to `[Unreleased]` in the
changelog. The contract tests (`tests/test_store_contract.py`) run every part against both kinds of
store, and the Windows CI runs the tests under a long root.

1. `Store`'s methods take the pipeline, and lockfiles record each dependency's pipeline. The layout
   is still v1, so nothing else moves.
2. The v2 layout: `pipelines/`, a folder for each snapshot, the dictionary, reading in place or
   gathered, `incomplete`, for the folder store and the S3 store.
3. `store gc` on snapshot folders.
4. `chartbook store migrate`.
5. Long paths on Windows (#136).
6. `chartbook store export` and `store import`.
7. #135, the rest.
8. #134, the shared reader.
9. #133, `[files]`.
10. The template's CI.

## Breaking changes, for the changelog

- **The store's layout.** Upgrade every machine that shares a store, then run `chartbook store
  migrate` on one of them.
- **A snapshot's record** is `chartbook/snapshot/v2`, and lists every file.
- **A store plugin's methods** take the pipeline, and `get` takes the asset's entry.
- **A lockfile gains a field** on its next `pin` or `update`: each dependency's pipeline.
- **`builds/` is no longer kept free** in the store.

## Not in 0.3.0

- An input hash, or a build skipped because its inputs are in the store. The commit is the
  "before" hash.
- The same bytes kept once across two pipelines.
- A snapshot with its code ("Later: a snapshot with its code", above).
- An MCP server (#54).
- Pins of a Delta table by its version (pull request 90), which waits on a test in a real
  Databricks workspace ({doc}`../roadmap`).
- Excel files as tables.
- Sending a pipeline's folder automatically, beyond `export` and `import`.

## Open questions

None, as of 2026-10-28. Answered that day, besides the four decisions at the top of the store's
section:

- The store keeps only its own bytes, by reflink or copy; the four ways of linking are for reading.
- A snapshot's folder is named by its time and then its commit, split by `_`.
- ChartBook keeps what is its own in a snapshot in one folder whose name it reserves, `_chartbook`.
- `export` writes no readable copy beside the store's, since it never duplicates a file.
- `store gc` clears `pipelines/+unowned/` once no root names what is in it.
- A snapshot with its code waits.
- #9 was closed, built in 0.2.0.
