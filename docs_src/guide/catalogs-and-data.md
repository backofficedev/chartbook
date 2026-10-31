# Catalogs and Data Access

A catalog is a view of its stores. It shows every pipeline with a snapshot in any of them, and every published version, without reading a working repository. A pipeline enters the catalog when its owner runs `chartbook snapshot`.

## The catalog manifest

A catalog's file is `catalog.toml`. A pipeline's file remains `chartbook.toml`.

```toml
[project]
name = "Team Analytics Catalog"

[stores.mine]
url = "~/data/chartbook"

[stores.collaboration]
url = "~/shared/project-data"
pipelines = ["acme/rates"]

[stores.public]
url = "s3://acme-data/chartbook?anonymous=true"
read_only = true

[pipelines."acme/retired"]
disabled = true
```

Store locations can be folders, `file://` URLs, S3 buckets, or schemes supplied by a store plugin. Relative folders are relative to the catalog file. Platform-specific locations use `{ unix = "…", windows = "…" }`. Store names are single ID components. Two names for the same location are rejected.

The first store is the default. New snapshots go there unless a store's `pipelines` list routes the pipeline elsewhere. Listing a pipeline in several stores writes it to all of them, with verified copies. `chartbook snapshot --store NAME` overrides routing once; repeat the option for several destinations. At a terminal, the first snapshot asks where to route an unassigned pipeline if several writable stores exist. In batch mode the default applies. Read-only stores are never written.

A missing named folder is unreachable: reads warn and continue with the remaining stores, and writes fail. The default folder may be created on first use.

## The machine's catalog

The machine uses `[catalog] path` in `~/.chartbook/settings.toml`, or `~/.chartbook/catalog.toml`.

```console
chartbook catalog init
chartbook store add collaborator /path/to/shared/store --read-only
chartbook store info
chartbook catalog build
chartbook catalog open
```

`store add` lists the pipelines it discovers and preserves catalog comments. `store remove NAME` removes the definition and leaves the files untouched. `store move ID --to NAME --dry-run` previews a move; without the dry run it verifies the destination, copies retention notes, removes source snapshots, and changes future routing. `--keep` retains the sources; `--no-route` retains the routing.

With no configured stores, `[store] url` in settings remains the fallback, then `~/.chartbook/store`. `CHARTBOOK_STORE` isolates a process to exactly one store, including tests and CI.

## Reading data

Pins and updates choose the newest snapshot across all configured stores, within the selected repository. An existing pin stays in that repository. If two repositories claim an ID, declare `repository = "https://github.com/acme/rates"`. The lockfile records snapshot identity and hashes, never a machine's store path.

```python
from chartbook import data

frame = data.load(pipeline="acme/rates", dataframe="rates")
```

Outside a consumer pipeline, this reads the catalog's newest snapshot. Inside a consumer pipeline, declared dependencies read their pins. There is no implicit working-folder fallback. While fixing two pipelines together, use `chartbook link acme/rates ../rates`; delete `chartbook.links.toml` to restore pinned reads. A snapshot refuses while that file exists, and CI and frozen runs ignore it.

## Catalog pages

The catalog's pipeline and asset pages are hubs over snapshot versions. A version's own site is rendered from its stored documents and built files in a sandbox; notebooks are never executed again. Asset hubs compare consecutive indexes, including column and row changes. The Stores page shows locations, reachability, routing, and snapshot counts. Published indexes keep store names while omitting local folder locations. `chartbook ls stores` and `chartbook ls versions` expose those facts on the command line.

The catalog does not run build scripts or check working members. Use `chartbook run` and `chartbook check` inside a pipeline. Its own site is built with `chartbook docs build`; a task runner can make that the final step of the build script.

## Upgrading a folder catalog

Run `chartbook catalog migrate` once on each machine. It keeps an exact backup, writes `catalog.toml` with the former machine store, retains project metadata, policy, and disabled notes, and lists the working pipelines that need snapshots before they appear. It does not change store layout, snapshot hashes, or lockfiles.
