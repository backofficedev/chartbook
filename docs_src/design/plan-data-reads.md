# Design: the plan for data reads

```{note}
A plan, written 2026-10-31, the day after 0.4.0 was released, from a conversation with the
maintainer that day. It says what is wrong with how ChartBook reads data today, what replaces it,
and what the end user sees. What the maintainer decided on 2026-10-31 is marked *decided*. The
version is **0.5.0** (*decided 2026-10-31*): `data.path` on another pipeline's folder dataset
and the Store plugin contract both change, so it is more than a patch. Status: **being built**;
what lands goes under "Unreleased" in the changelog until it is published.
```

## The problem, in plain terms

The store keeps each file once. A later snapshot of a pipeline holds only the files that are new
or changed; its record says where the rest are kept. So one version of a dataset can have its files
in several snapshot folders:

```text
pipelines/news_headlines/
  2026-05-01T120000Z_a1b2c3d4/   _data/articles/year=2018/  year=2019/  year=2020/
  2026-06-01T120000Z_e5f6a7b8/   _data/articles/year=2021/            (2018–2020: kept in the first)
  2026-07-01T120000Z_c9d0e1f2/   _data/articles/year=2022/            (2018–2021: kept in the first two)
```

This is the standard design. A Git commit is a full tree whose objects are shared between commits.
A Delta table version is a list of parquet files shared with earlier versions. It is what keeps a
2.5 GB dataset from costing 2.5 GB more on every snapshot in a synced Google Drive folder, which
keeps no hard links. The maintainer confirmed on 2026-10-31 that this stays.

The mistake was built on top of it. The store's one way to hand out an asset, `Store.get`, returns
a *folder*. A version spread over three folders has no folder, so `FolderStore.get` builds one:
it links or copies every file into `~/.chartbook/cache/views/<hash>/` and returns that. This
"view" is what the pre-plan and the code call the cache. Three things follow:

- **It grows without bound.** Nothing removes `views/`. One `chartbook catalog build` on the
  maintainer's Mac made it 2.3 GB.
- **It pulls every byte local.** A clone or a copy needs the bytes, so the build most likely makes
  Google Drive download every dataset it touches. On Windows, where the ladder has no symlink and
  Drive is its own volume, they are most likely full copies.
- **Nobody needed the folder.** Polars and DuckDB read a list of files. The catalog needs row
  counts and date ranges that the snapshot's own `index.json` already holds. `restore` and
  `store move` copy files to a destination anyway.

The pre-plan is `_temp/preplan-data-reads.md` in the maintainer's checkout (not in the repository);
the measurements there are from 2026-10-31 on ChartBook 0.4.0.

## What a snapshot is

A **snapshot** is a complete version of a pipeline: its record, `_chartbook/snapshot.json`, lists
every file of every asset with its hash, its size, and the folder that keeps it. The record is
always complete. The folder is not.

- A snapshot's folder is **standalone** when it holds every file of its version.
- It is **shared** when it holds only what is new or changed, and the rest sit in earlier folders
  of the same pipeline.

A snapshot is not a diff: no snapshot has to be "applied" to another. But a shared snapshot's
folder cannot be read alone, and deleting an earlier folder by hand can take files from it. Only
`chartbook store gc` removes safely: it clears a snapshot's record, leaves any file a later
snapshot uses, writes `_chartbook/CLEARED.txt` saying why, and removes the folder once nothing
points into it. *Decided 2026-10-31:* shared folders stay the default, and ChartBook says so where
a person would look.

## What the user does

Every example is in a pipeline made by `chartbook init`, whose `chartbook.toml` declares
`path = "./_data/<name>.parquet"` for each dataframe.

**Write your own outputs.** `data.path` finds `chartbook.toml` by walking up from the file that
called it, so a script three folders deep in `src/` gets the same answer wherever it is run from.
The file need not exist; the declaration must.

```python
# src/pull/pull_repo.py, run from anywhere
from chartbook import data

df = fetch_from_fred()
df.write_parquet(data.path("repo_public"))             # <project>/_data/repo_public.parquet
```

```python
# a dataset of many files: declare its path as a folder, path = "./_data/articles"
df.write_parquet(data.path("articles"), partition_by="year")
```

If `_data/` does not exist yet, `data.path` makes it, so the first run of a new pipeline does not
fail with "No such file or directory" from the writer. An undeclared name raises at once, naming
the `chartbook.toml` it searched and the stanza to add. ChartBook never invents a path: a dataset
with no declaration has no description, no page and no snapshot.

**Read anyone's data, any shape, one call.** Your own dataset is read from your working folder.
Another pipeline's is read from the store, at the snapshot your lockfile pins, from wherever its
files sit. No copy is made.

```python
rates = data.load("fed_yield_curve:treasury_rates")     # one parquet file
news  = data.load("news_headlines:articles")            # Hive folder, spread over 3 snapshot folders
mine  = data.load("merged_rates")                       # my own, from my working folder
joined = data.sql("select * from {news_headlines:articles} a join {merged_rates} m using (date)")
```

**Name dependencies in `dodo.py`.** A build tool wants files. `data.files` gives every file of a
dataset, sorted, wherever each is kept.

```python
file_dep = data.files("news_headlines:articles")
targets  = [data.path("merged_rates")]
```

**Ask for a path to another pipeline's many-file dataset**, and get told the fix. *Decided
2026-10-31 (choice A):*

```python
data.path("news_headlines:articles")
# ChartBook: 'news_headlines:articles' is a dataset of 14 files kept in 3 places; there is no one
# folder. Read it with data.load("news_headlines:articles"), or hand
# data.files("news_headlines:articles") to your own reader.
```

The rule is by declaration: another pipeline's dataset declared as a folder or a glob always
raises here, whether or not its files happen to sit together today. So a call that works never
starts failing because the upstream took another snapshot. The alternative, returning a list, was
turned down because Polars reads a list of files without parsing Hive partitions unless told to,
so the `year` column would vanish silently; `data.load` passes that flag.

**Throwaway files.** `data.scratch()` is a folder inside the project for intermediates that are
not assets, made on first use, ignored by git. *Proposed:* `[project] scratch = "./_data/_scratch"`
in `chartbook.toml` names where it is; the default is today's place.

**Look in the store.** A person browsing `pipelines/<pipeline>/` finds a `README.txt` that says
what a shared folder is and that `chartbook store gc` is how to remove snapshots.
`chartbook store ls <pipeline>` lists each snapshot, when it was made, its commit, its size, and
whether it is standalone or shared.

**Send one version to someone.** `chartbook store export <pipeline> --latest --to <folder>` already
writes one complete snapshot, readable without ChartBook. This is the one honest use of gathering
a version's files into one place: an output the user asked for, in a place they named.

**Be reminded about gc.** After `chartbook snapshot` and `chartbook catalog build`, one line when
there is something to clear:

```text
The store holds 6 snapshots older than 7 days that `chartbook store gc` would clear (2.1 GB).
```

Nothing is removed unless asked. `--gc` on `catalog build` runs it then; a flag silences the line.
*Decided 2026-10-31:* the line is on by default.

## The design

### 1. The store hands out files, not folders

`Store.get(content_hash, pipeline, name) -> Path` goes. In its place:

```python
Store.files(content_hash, pipeline=None, name=None) -> list[StoredFile]
# StoredFile: relative (its path inside the asset, POSIX), location (Path), size, content_hash
```

Every caller takes the list. `resolve.py` (the reads behind `data.path`, `data.load`, `data.sql`,
`assets.files`) hands the list to the reader. `snapshot.materialize` copies file by file into the
destination it was given, which `restore`, `run --upstream` and `store move` already want.
`lineage` and `data.get_docs` read the one or two files they need from the list. `gather`,
`VIEW_LINKS`, `VIEWS_DIR`, `FolderStore.views` and the `views/` folder are deleted, not pruned. The
S3 store, which reads through a local copy laid out as a folder store, returns paths in that copy.
`chartbook.formats` and `assets.index` already accept lists. Hive keys stay in each file's path
inside the store, so `hive_partitioning=True` on the list reads them as before.

The checks in today's `get` (a link that leads out of the store is refused; a file not yet synced
is reported) move to `files` unchanged.

### 2. The catalog reads no data

A version page needs a dataframe's columns, row count, date range, a glimpse of its first rows,
and the last valid date per column. The first three are already in the snapshot's `index.json`.
The glimpse and the last dates are computed by the pipeline's own `chartbook docs build`, from the
files, when the index is made; they are added to the dataframe's index record then, so the
snapshot's `index.json` carries them. (A table or query in a source already renders from the
stored parquet copy, not the database.)

`versions.render` then lays out only what the site is made from: the documents asset (README,
`docs_src/`, `chartbook.toml`), charts, notebooks, notes and the stored `index.json`. Dataframe
and file assets are not laid out. The writer, rendering a version from a store, takes the glimpse
and the dates from the record and opens no data file. A pipeline's own `docs build` in its working
folder reads its files as it does today.

This also makes the version build cheap enough that keeping the pipeline's built site in the
snapshot, which the pre-plan asked about, is not needed now.

### 3. The read calls

| Call | Gives | Your own dataset | Another pipeline's dataset |
|---|---|---|---|
| `data.path(ref)` | one `Path` | the declared path, file or folder; parent folder made | the one file; a folder or glob raises, naming `data.load` and `data.files` |
| `data.files(ref)` | `list[Path]` | the files at the declared path | every file, wherever kept |
| `data.load(ref)` | a frame | read from the working folder | read from the store, no copy |
| `data.sql(query)` | a frame | the same, through DuckDB | the same |
| `data.scratch()` | a folder | inside the project | not applicable |

`data.files` is new: the dataframe-only front door to `assets.files`, as `data.path` is to
`assets.path`. The reference string `"pipeline:name"` stays, and so does
`data.load(pipeline=..., dataframe=...)`, which already exists for those who want the explicit
spelling. The dot was weighed and turned down in {doc}`references`.

### 4. Writing

- `data.path` of your own asset makes the parent folder of a file, or the folder itself for a
  folder dataset. It never makes anything for another pipeline's asset, and never anything else.
  (`data.scratch` already behaves this way.)
- The declaration decides the format, as it does for reading: the `format` field, else the
  extension of the declared path. The guide shows the writer that matches.
- A dataset of many files is declared as a folder. A glob stays allowed for an odd layout that
  needs one, but a glob is not a place to write, and the guide does not teach it.

### 5. Standalone and shared, in words a person reads

- `chartbook snapshot` writes `pipelines/<pipeline>/README.txt` if it is not there: snapshots share
  files, which ones, and `chartbook store gc` as the way to remove. Nothing already in the store is
  rewritten.
- `chartbook store ls [PIPELINE]` lists snapshots with their size and standalone/shared.
- `chartbook store info` says how many snapshots `gc` would clear, and the size.

### 6. The leftover `views/` folder

The cache is defined as disposable ("everything in it can be removed: it is read again from the
store"). The first command on this version that opens the cache removes a leftover `views/` and
says so in one line. The changelog's "Read this first" says the same.

## Deliberately not now

- **`chartbook snapshot --standalone`**, an opt-in for a version to keep whole. Small; the
  maintainer likes it; after this plan.
- **Consolidating**: a standalone snapshot of the version to keep, then `gc` of the older ones, as
  one command. Nothing in a synced store is ever rewritten, so this is the only safe shape. Later.
- **A location object** (`data.locate(ref)` with `.files`, `.path`, `.kind`). The honest type, but
  one more thing to learn for what `data.load` does. Turned down 2026-10-31.
- **The site's weight.** Each version's site is kept three times (`~/.chartbook/docs/versions`,
  `~/.chartbook/cache/versions`, `~/.chartbook/_docs`), each Plotly chart twice per version, a logo
  per version. Real, separate, and smaller. After the cache is gone.
- **Warehouses that keep the data.** Tables pinned in place by a version or timestamp where the
  engine has time travel. Roadmap, as before ({doc}`data-access`).
- **A loading DSL.** References never select columns or rows.

## The documentation

The guide is rewritten around what a person is trying to do. Each page opens with a complete
worked example a reader can run in a template project, then the two or three next most common
scenarios, then nothing. A page is under 800 words of prose plus its code. What a page does not
need to teach goes to the reference, which is generated and checked against the code.

| Page | Replaces | Teaches, in order |
|---|---|---|
| Getting started | the same | install, `chartbook init`, `chartbook run`, open the site |
| Reading and writing data | new, the heart of this plan | `data.path` to write, `data.load` and `data.sql` to read, your own and others', a folder dataset, `data.files` in `dodo.py`, scratch |
| Depending on pipelines | the same, cut from 2,200 words | declare, pin, read, update; what a snapshot is; standalone and shared; `gc` |
| Catalogs and stores | catalogs-and-data | a Drive folder as a store, several stores, `catalog build`, `store ls`, `store export`, `gc` |
| Documenting a pipeline | the same, cut from 2,600 words | the TOML stanza, `docs_path`, the page it makes |
| Keeping costly outputs | the same | unchanged in substance |
| Reading a warehouse | the same | unchanged in substance |
| Plotting, backends, gallery | the same | out of scope here |
| How the build works | the same, cut from 3,000 words | one page, for the reader who wants the machinery |
| Vocabulary | the same | adds standalone and shared; drops the cache |

The reference pages change only where a command or field changed: `store ls`, `--gc`, the
reminder's flag, `[project] scratch`, `data.files`, and the removal of `[cache] path` from
anything a user is told to care about (it stays for hashes, locks and a bucket's local copy).

## Order of work

1. **The store hands out files** (design item 1), the `views/` cache deleted, `data.files` added,
   `data.path` choice A, the leftover `views/` removed once. Tests: a dataset spread over three
   snapshot folders reads correctly with `data.load`, `data.sql`, `data.files`; `data.path` raises
   with the message; nothing is written under the cache. Run against a scratch copy of the
   maintainer's Drive store before merging.
2. **The catalog reads no data** (item 2): glimpse and last dates recorded in the index;
   `versions.render` lays out no data assets. Test: a catalog build over a store opens no dataframe
   file (count opens in the test).
3. **Writing** (item 4) and `[project] scratch` (item 5 of the user section).
4. **Standalone and shared** (item 5): README, `store ls`, `store info` counts, the reminder line
   and its flag, `catalog build --gc`.
5. **The documentation**, as above, with the changelog entry under `## [Unreleased]` and the
   "Read this first" note.

Each step is a pull request, reviewed by an adversarial sub-agent and merged by the agent, per
the standing arrangement. The whole plan ships as 0.5.0 (*decided 2026-10-31*). Step 1 and step 2 are the ones that end the disk growth; if the version
ships before the rest, they are enough.

## As built

*Step 1, PR #150 (2026-10-31).* `Store.files(content_hash, pipeline, name)` returns a `KeptFiles`:
the asset's files sorted by their path inside it, each where the store keeps it, and `home`, the
folder the asset is listed from in the snapshot that recorded it. `FileLocation` gains `inside`,
that mapping, and the reader (`chartbook.formats`) derives Hive keys from each file's path inside
the asset, so a dataset spread over snapshots reads as one in a folder; a TSV a bucket's cache keeps
under its hash is told by its name inside the asset. `data.path`, `assets.path`, `models.path` and
`data.get_data_path` raise `NoSinglePathError` for a folder or glob read from the store, by
declaration (`resolve.require_single_path`). `data.files` is the dataframe front door to
`assets.files`. `assets.gathered(ref)` was added: a folder model's loader needs a directory, and
the context manager lays the files out in a temporary one. The first command finds a leftover
`views/` folder, removes it, says so, and leaves a marker so it is done once. The glimpses report
reads a store pipeline's dataframe as its files.

*Step 2, PR #151 (2026-10-31).* The index records `glimpse` and `last_dates` for a dataframe and
`preview` for a files asset when it describes the files. `snapshot.materialize(..., data=False)`
lays out documents, charts, notebooks, notes and the stored index, and `versions.render` uses it;
`index.stored_index_records` gives a laid-out version's build the facts the snapshot recorded of
each data asset, and the build counts those files as not missing. A version builds even when its
data is not in the store. A 0.4 snapshot's version page says the first rows were not recorded.
After review: a table or query in a source, which has a `definition_hash` and no `content_hash`,
is shown from the index too, and the index records its glimpse (`utils.source_glimpse`) and dates;
the snapshot's own index is required whole in the store before a version is laid out, and a
half-synced one is tried again later rather than kept as a version with no data; every fact taken
from a stored index is checked for shape (`index._well_formed`), since anyone can write a store;
a glimpse is capped (`utils.GLIMPSE_MAX_CHARS`); a folder of parts gets `N/A` for its last dates
rather than being read whole; a CSV's text dates parse under polars 2.

*Step 3, PR #152 (2026-10-31, with step 4).* `data.path`, `assets.path` and `models.path` of a pipeline's own asset
make the folder the file is written into (`assets._make_room`): the file's parent, or a glob's
root, inside the pipeline's folder only; polars makes a folder dataset's own folder when it writes
with `partition_by`, and a path with no ending may be a file. `[project] scratch` names the scratch
folder (`data._scratch_declared` reads the manifest's text alone; the manifest refuses a value
that is not a plain path inside the pipeline). The reference says a dataset of many files is
declared as a folder, not a glob.

*Step 4, PR #152 (2026-10-31, with step 3).* `chartbook store ls [PIPELINE]` lists snapshots as standalone or
shared with the size each folder holds; the first snapshot of a pipeline writes `README.txt` in the
pipeline's store folder (`store.write_readme`, never rewritten, removed by `gc` with the last
snapshot); after
`chartbook snapshot` and `chartbook catalog build` one line says what gc would clear
(`cli._remind_of_gc`, from the gc plan, read-only), `--no-gc-reminder` silences it, and
`catalog build --gc` runs gc as `store gc --yes` would. `store export --latest` already writes a
standalone copy, so nothing was added for that.

## Decisions, dated

| Date | Decision |
|---|---|
| 2026-10-31 | Snapshots keep sharing files (each file once); `store gc` is the only remover; ChartBook says so in a README and in `store ls`. |
| 2026-10-31 | The `views/` cache is deleted, not pruned. Readers take lists of files. |
| 2026-10-31 | The catalog reads no data: glimpse and last dates are recorded at snapshot time. |
| 2026-10-31 | `data.path` returns one path or raises (choice A); `data.files` is the list; `data.load` and `data.sql` read anything. No location object. |
| 2026-10-31 | `data.path` of your own asset makes its parent folder. Folder datasets are declared as folders, not globs. |
| 2026-10-31 | The reference string `"pipeline:name"` stays, alongside the keyword form `data.load` already has. |
| 2026-10-31 | A gc reminder prints by default after `snapshot` and `catalog build`, with a flag to silence it; nothing is removed unless asked. |
| 2026-10-31 | `snapshot --standalone` and consolidation wait. The site's weight is a separate, later fix. |

## For whoever implements this

- The maintainer's real catalog is `~/.chartbook/catalog.toml` and the only real store is a Google
  Drive folder. Never run `chartbook catalog …`, `chartbook config`, `chartbook install …` or
  `chartbook store …` against the real home. Any call outside pytest sets `HOME`,
  `CHARTBOOK_STORE`, `CHARTBOOK_CACHE`, `CHARTBOOK_GIT_CACHE` and `CHARTBOOK_SYSTEM_SETTINGS` to a
  scratch folder.
- Never stash `tests/conftest.py`. Never run the examples during tests.
- Tests: `.venv/bin/python -m pytest tests/... -q -p no:cacheprovider`; the full suite with
  `.hatch/hatch-test.py3.13/bin/python -m pytest tests -q -n auto` (about five minutes).
- Text I/O names its encoding and newline (Windows CI).
