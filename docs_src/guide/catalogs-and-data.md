# Catalogs and Stores

A **store** is a folder that holds snapshots. A **catalog** is a list of stores, and a site over
every snapshot in them. Neither reads a working folder, and neither copies data anywhere. By
default the two are one unit: ChartBook makes the catalog over your store the first time you need
it, and asks first at a terminal.

```console
$ chartbook catalog open        # the first time: "No catalog yet. Create one over your store at …? [Y/n]"
The catalog's site has not been built yet. Build it before opening? [Y/n]: 
$ chartbook store add team "~/Google Drive/chartbook-store-team"   # a second store joins it
```

`chartbook catalog open` is the one command to remember: it builds the site when the stores have
snapshots the site does not show yet, after asking, and opens it. `chartbook catalog build` builds
it without opening, for a script.

The catalog lists every snapshot of every pipeline in its stores, each its own site as its owner
declared it ready, and which pipeline pins it. {doc}`../tutorials/explore-a-catalog` builds this one
from three pipelines you clone and build:

```{image} ../_static/screenshots/tutorial-versions-light.png
:alt: The catalog's Versions page: each pipeline's snapshots by commit and time, and which pipeline pins each
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-versions-dark.png
:alt: The catalog's Versions page: each pipeline's snapshots by commit and time, and which pipeline pins each
:class: only-dark cb-screenshot
:align: center
```

## A store is a folder

Your own store is a folder on this machine. A store a team shares is a folder a sync service keeps
in step between machines, Google Drive, Dropbox or OneDrive, or a folder on a shared disk, or an S3
bucket. Point each machine at the same folder and a snapshot made on one is there for the others
once the sync has finished. Nothing in ChartBook moves snapshots between machines; the folder does.

Inside, the layout is made to be read by a person:

```text
chartbook-store-team/
  snapshots/
    acme+news_headlines/
      README.txt                           that each folder is a complete snapshot, and that gc removes them
      2026-05-01T120000Z_a1b2c3d4e5f6/     a snapshot: when it was made _ its commit
        _data/articles/year=2023/...       the pipeline's files, in their own places
        _chartbook/snapshot.json           the record: every file, and its hash
      2026-06-01T120000Z_e5f6a7b8c9d0/     a later one: every file of it again
  _chartbook/                              ChartBook's own notes; nothing here is for a person
  store.json                               which layout this is
  README.txt                               what the folder is, for whoever opens it
```

Every snapshot's folder is complete: it holds every file of that version, and can be read, copied
or sent as it is. A store that ChartBook 0.5 laid out has `pipelines/` at the top and keeps each
file once; this ChartBook reads such a store as it is, makes no snapshot in it and removes nothing
from it, and says so.

`CHARTBOOK_STORE` points a process at exactly one store; `chartbook store info` says which stores
this machine uses and what set them.

## The catalog is its stores

The machine's catalog is `~/.chartbook/catalog.toml`, made over the machine's store the first time a
command needs it (`chartbook catalog init` makes it ahead of time, or with a title). Its `[stores]`
table lists the stores to read,
in order; the first is where new snapshots go unless a store's `pipelines` list routes a pipeline
elsewhere.

```toml
[project]
name = "Team Analytics Catalog"

[stores.mine]
url = "~/data/chartbook"

[stores.team]
url = "~/Google Drive/chartbook-store-team"
pipelines = ["acme/news_headlines"]

[stores.public]
url = "s3://acme-data/chartbook?anonymous=true"
read_only = true
```

A store is a folder, a `file://` URL, an S3 bucket, or a scheme a plugin provides. `chartbook store
add NAME URL` adds one and lists the pipelines it finds; `store remove NAME` removes the entry and
leaves the files; `store move ID --to NAME` moves a pipeline's snapshots to another store, verifies
the copies, and removes them from the source. One Drive folder per collaborator, each a store, is
how one person shares different projects with different people.

## What the catalog shows

Every pipeline with a snapshot in any store, and every version of each. A version's page is built
from its snapshot's documents, charts, notebooks and index: the data is not laid out and not read.
The index recorded each dataframe's columns, rows, dates and first rows when the snapshot was made,
so the catalog shows them without touching a data file. What a catalog build keeps on your disk is
the site, its `_docs/` build tree beside the catalog, and each version's built site under
`~/.chartbook/cache/versions`; no data file is copied or read. A pipeline enters the catalog when its owner runs `chartbook
snapshot`; the catalog runs no pipeline's code.

`chartbook ls` lists what the catalog shows on the command line; `chartbook ls stores` and
`chartbook ls versions` the stores and the versions.

## Keeping the store small

Every snapshot is **complete**: its folder holds every file of its version. `chartbook store ls`
lists them and what each one's folder holds:

```console
$ chartbook store ls acme/news_headlines
acme/news_headlines (3 snapshot(s))
  2026-05-01T120000Z_a1b2c3d4e5f6  2026-05-01 12:00 UTC  a1b2c3d  complete   2.1 GB here
  2026-06-01T120000Z_e5f6a7b8c9d0  2026-06-01 12:00 UTC  e5f6a7b  complete   2.4 GB here
  2026-07-01T120000Z_c9d0e1f2a3b4  2026-07-01 12:00 UTC  c9d0e1f  complete   2.7 GB here
```

A snapshot's folder is not deleted by hand: a lockfile may pin it.
`chartbook store gc` removes snapshots safely: it keeps the newest of each pipeline, everything a
lockfile pins, a snapshot a model's label points into, and anything made in the last seven days,
lists what it would remove, and asks. After `chartbook snapshot` and `chartbook catalog build`, one line
says what gc would clear and how much it would free, so a store nobody clears is at least a store
whose owner was told; `--no-gc-reminder` silences it, and `chartbook catalog build --gc` runs gc
after the build. Nothing is removed unless you ask.

```console
$ chartbook catalog build
...
`chartbook store gc` would clear 6 snapshot(s), freeing 2.1 GB: older than 7 days, and neither pinned nor the newest of their pipeline. Nothing is removed unless you ask (`--no-gc-reminder` silences this line).
```

To give someone a version, `chartbook store export acme/news_headlines --latest
--to FOLDER` writes its snapshot, complete, wherever you say. `chartbook store import FOLDER` takes one
in.

## Reading data through a catalog

Inside a pipeline, another pipeline's data is read as pinned ({doc}`depending-on-pipelines`).
Outside any pipeline, in a notebook that belongs to none, a read is a one-off exploration of a
pipeline's newest snapshot:

```python
from chartbook import data

frame = data.load(pipeline="acme/rates", dataframe="rates")
```

There is no fallback to a working folder: a pipeline with no snapshot is not read. If two
repositories claim one ID, `repository = "https://github.com/acme/rates"` under
`[pipelines."acme/rates"]` in the catalog says which. A dataset of many files has files and no one
path; `data.load` reads it, as {doc}`reading-and-writing-data` says.

## Upgrading from a folder catalog

`chartbook catalog migrate`, once on each machine, turns a catalog that listed folders into one
that lists stores, keeps a backup, and names the working pipelines that need a snapshot before they
appear. It changes no store layout, snapshot hash or lockfile.
