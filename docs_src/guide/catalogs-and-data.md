# Catalogs and Shared Stores

A **store** is a folder that holds versioned snapshots of your datasets, trained models, charts, and other build artifacts. A **catalog** is the searchable website (and CLI index) built over all the snapshots in your stores.

Putting a store in a synced or shared folder lets you **share artifacts across multiple machines, teammates, and parallel coding agents**—with zero servers or infrastructure to maintain.

```bash
chartbook catalog open
```

`chartbook catalog open` is the one command to remember: if new snapshots have landed since the last build, it asks to rebuild the site and opens it in your browser. (Use `chartbook catalog build` in scripts or CI when you don't want to open a browser.)

```{image} ../_static/screenshots/tutorial-versions-light.png
:alt: The catalog Versions page listing snapshots by commit and timestamp, and showing which pipelines pin each one
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-versions-dark.png
:alt: The catalog Versions page listing snapshots by commit and timestamp, and showing which pipelines pin each one
:class: only-dark cb-screenshot
:align: center
```

## Sharing snapshots with your team

Your personal store lives at `~/.chartbook/store`. To share snapshots with a team or research group, point everyone at a **synced or shared folder**—Google Drive, Dropbox, OneDrive, or a network drive:

```bash
chartbook store add team "~/Google Drive/chartbook-store-team"
```

When one teammate runs `chartbook snapshot`, the synced folder delivers the snapshot to everyone else. Their `chartbook ls`, `chartbook catalog open`, and `chartbook pin --update` see it automatically.

:::{note} Looking for S3 stores?
S3 stores are temporarily unavailable on the 0.6.0 store layout and are tracked on the {doc}`../roadmap`.
:::

## Routing pipelines across multiple stores

Your machine's catalog configuration lives in `~/.chartbook/catalog.toml`. Add as many stores as you like—personal, team, per-collaborator, or read-only archives:

```toml
[project]
name = "Team Analytics Catalog"

[stores.mine]
url = "~/data/chartbook"

[stores.team]
url = "~/Google Drive/chartbook-store-team"
pipelines = ["acme/news_headlines"]

[stores.archive]
url = "/mnt/archive/chartbook-store"
read_only = true
```

- New snapshots go to the first store unless a store's `pipelines` list routes a pipeline elsewhere.
- Move an existing pipeline's snapshots between stores safely with `chartbook store move <id> --to <store_name>`.
- Inspect your active stores anytime with `chartbook store info` or `chartbook ls stores`.

## Keeping your store small

Snapshots are stored either as **complete** folders (every file) or **increments** (only files that changed since the last complete snapshot). See what's on disk with `chartbook store ls`:

```console
$ chartbook store ls acme/news_headlines
acme/news_headlines (3 snapshot(s))
  2026-05-01T120000Z_a1b2c3d4e5f6  2026-05-01 12:00 UTC  a1b2c3d  complete   2.1 GB here
  2026-06-01T120000Z_e5f6a7b8c9d0  2026-06-01 12:00 UTC  e5f6a7b  increment  310.2 MB here, 41 file(s) in 2026-05-01T120000Z_a1b2c3d4e5f6
  2026-07-01T120000Z_c9d0e1f2a3b4  2026-07-01 12:00 UTC  c9d0e1f  increment  611.9 MB here, 41 file(s) in 2026-05-01T120000Z_a1b2c3d4e5f6
```

To free disk space, **never delete snapshot folders manually**—use `chartbook store gc`:

```bash
chartbook store gc
```

`chartbook store gc` always previews what it will delete and asks before removing anything. It automatically protects:
- The newest snapshot of every pipeline
- Any snapshot pinned by a lockfile (across your local branches and tags)
- Any snapshot referenced by a model alias or a kept increment
- Any snapshot less than 7 days old

:::{dropdown} Inside a store folder (for the curious)
```text
chartbook-store-team/
  snapshots/
    acme+news_headlines/
      2026-05-01T120000Z_a1b2c3d4e5f6/     # complete snapshot (date_commit)
        _data/articles/year=2023/...
        _chartbook/snapshot.json           # manifest + file hashes
  increments/
    acme+news_headlines/
      2026-06-01T120000Z_e5f6a7b8c9d0/     # only changed files
        _data/articles/year=2024/...
        _chartbook/snapshot.json
        _chartbook/INCREMENT.txt
  _chartbook/                              # internal metadata
  store.json
  README.txt
```
Catalog builds only read snapshot indexes, charts, and docs—they never copy or scan your raw data files.
:::
