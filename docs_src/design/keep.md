# Design: keeping costly outputs

```{note}
Decided with the maintainer on 2026-10-18, before 0.2.0. It says how a pipeline marks an output that
cost real money or compute to make, what the store then keeps for it, how the bytes come back to disk,
and what a build does when they are not there. Built with this page, 2026-10-18: `keep = true`, the
gc rule, `chartbook restore`, and the stop in `chartbook run` with `--remake`.
```

## The problem

A pipeline's outputs are not all alike. Most are cheap to make again: a chart, a notebook, a table
joined from two others. Some are not. The output of a paid API run over a large corpus, OpenAI's
batch API over every filing of a decade, costs money each time. A trained model, a PyTorch network
or a fine-tuned language model, costs GPU hours, and its exact weights never come back bit for bit.
A pull from a vendor with a daily quota or hours-long queries, Bloomberg or WRDS, costs a day. A
scrape of a page that has since changed, or a point-in-time vintage of a series that is revised,
cannot be made again at all. And data a person made by hand, labels or a curated list, costs
someone's week.

The store treats them all alike. A snapshot is kept or removed whole, by the rules `store gc` has
({doc}`versioned-catalog`): pinned, newest, labelled, tagged, or made in the last seven days. So the
costly file lives only as long as some snapshot that happens to hold it, and a week of ordinary work
lets every earlier version of it go. And a folder that loses the file, by a clean or a fresh clone,
has a build tool that sees a target missing and makes it again, at the price.

Two things are wanted, then: a store that never lets the costly bytes go, and a cheap way to put
them back on disk, so that the build does not remake them.

## What you say

One key, on the asset, in the manifest:

```toml
[dataframes.embeddings]
path = "./_data/embeddings.parquet"
keep = true

[models.forecaster]
path = "./_models/forecaster.pt"
keep = true
```

`keep = true` goes on any entry of `[dataframes]`, `[charts]`, `[notebooks]`, `[notes]` and
`[models]`. It takes `true`, or is left out; anything else is an error naming the entry. It means:
**every version of this asset's bytes is kept in the store.**

The mark is in the manifest, not in the store, because the author knows what their outputs cost and
the store does not; because it belongs beside `path` and `description`, versioned with the code; and
because it travels with the snapshot, so that on a store a team shares a colleague's `gc` honours it.
*Decided 2026-10-18.*

## What the store keeps

`chartbook snapshot` writes the mark into the asset's record (`keep: true`). `store gc` then keeps,
**for each distinct version of a marked asset, the newest snapshot that holds it.** That is the rule
a model label already has ("a label points at a version in it"), with one holder per version: a
marked asset is a model whose every version is labelled. The snapshot stays whole, so each kept version
keeps its commit, its date, its data dictionary and its page in the catalog, and `chartbook restore`
has a record to read.

"Every version" was chosen over "the newest only" (*decided 2026-10-18*). What it costs is bounded by
how many times the costly thing was in fact made, which is what was paid for; a version made twice
to the same bytes is one object, by content hash. The newest alone would lose the point: a bad
regeneration could not be undone, and the run before it cost as much.

Which assets are marked is read as labels are: from the pipeline's manifest in the folder the
snapshots were made from, and, where no folder is known (another machine's snapshots, a checkout
thrown away), from the newest snapshot's records. So the current intent governs, and taking `keep`
out of the manifest and running `chartbook snapshot` releases the old versions at the next `gc`. No
flag lifts a mark; the manifest does.

`--aggressive` does not touch it. Aggressive means *names* keep nothing: tags, branches, labels. A
keep mark is not a name; it is a cost. `--aggressive --keep-days 0` leaves pins, the newest of each
pipeline, and every kept version.

`gc` shows the bill, one line per marked asset among its "Kept" lines, in a dry run too:

```text
Kept for `keep = true`: 3 version(s) of acme/docs:embeddings, 4.2 GB, in 3 snapshot(s)
```

## Getting the bytes back

```console
chartbook restore                   # every kept asset that is not on disk
chartbook restore embeddings        # one asset, kept or not
chartbook restore model/forecaster
```

`chartbook restore` copies an asset from the pipeline's newest snapshot that holds it, built and
whole in the store, to the path the manifest declares, and says which commit and date it came from.
It never writes over a file that is there: an asset on disk is left alone and said. It is the mirror
of `chartbook snapshot`, which copies the folder into the store. A table or query dataframe has no
file to put back, and is said so. With no argument it restores the kept assets that are missing;
with arguments, those assets, marked or not, since any asset a snapshot holds can be put back.

Whether the build then skips the step is the build tool's rule, and ChartBook does not try to know
it. doit skips a task whose targets exist and whose inputs it has seen before; on a fresh clone it
has seen nothing and runs the task anyway. The guide gives the recipe for a costly task: targets,
`uptodate: [True]` and no `file_dep`, so that it runs only when its file is missing.

## The stop before a build

`chartbook run` and `chartbook build`, before they run the build script, look at each kept asset of
the pipeline about to be built. One that is not on disk while the store has a version of it stops
the command:

```text
Error: acme/docs: embeddings is kept, and is not on disk (./_data/embeddings.parquet). The store has its version from 4f2a91c, made 2026-09-30 14:02 UTC.
  chartbook restore           puts it back
  chartbook run --remake      runs the build without it, which makes it again
Nothing was built.
```

Only ChartBook knows the three facts at once, and the stop fires in exactly the one dangerous
moment: the asset is marked, it is missing, and a copy is at hand. On a true first run nothing
stops, since the store has no version, so the flag is only ever typed for an asset that was made
before. `--remake` is one flag, for every kept asset at once: to remake one and not another, restore
the other first. To remake on purpose, delete the file first: with the file on disk nothing
stops, and a target-only build task does not run either. The stop is strict, with a plain message, and asks no question, as every stop here
does. *Decided 2026-10-18, over three others: doing nothing (one forgotten restore is one bill);
restoring by itself before the build (after a change to the code the old bytes would come back, the
build would skip the step, and the output would be stale with nothing said); and a doit helper that
asks the store (ChartBook logic in dodo.py, for one build tool).*

In a catalog, `chartbook run` looks at each member it is about to build, before any member's build
runs. `--frozen` is unaffected: the stop is about the folder, not the store. The stop and
`restore` agree on which snapshot holds an asset: the newest holding it built, with its bytes in
the store and whole (`snapshot.newest_holder`); a newer version whose bytes are gone is refused,
never quietly replaced by an older one, and then there is nothing to stop for either. A
snapshot dated after now is no holder, as it is not "the newest" elsewhere in gc. Snapshots are
found through the commits the clone has, so a shallow clone sees none.

`chartbook check` says the same of a kept asset that is missing, on its "file not found" line, so
that a CI job, or a person who runs doit directly, hears of it.

## The record

In a snapshot's asset record, `keep: true`, present only when the manifest says so. It is not
copied into a lockfile that pins the asset: the lockfile records what a dependant got, and the mark
is the owner's intent about the owner's store. The asset's index record carries it (`keep: true`),
so that a page or a program can say every version of it is kept.

## Not doing, and later

- A `keep` that is less than forever (`keep = "newest"`, `keep = "90d"`). Nothing asked for it;
  `true` leaves the string forms free.
- Restoring a particular version, `chartbook restore model/x@7f3a9c2e41b0`. `chartbook path
  model/x@<version>` gives its path in the store already.
- A store-side mark, for bytes no manifest claims. The manifest is the place.
- Restoring by itself before a build. See the stop above.
- A "kept" line in the provenance panel of the asset's page: proposed, not built, until the writers'
  panel has a row for it.
- The stop for a `git` dependency's build, which runs in ChartBook's own copy of the commit, where
  nothing is on disk and `chartbook restore` cannot be run; restoring into that copy before its
  build is the natural extension.
- Finding a pipeline's snapshots by its ID and repository rather than through the clone's commits,
  so that a shallow clone in CI finds them.
- Restoring a folder asset at a path that changed since the snapshot; today that is refused,
  since a folder written where a file is now expected would be taken as built.

## The order of work

1. This page.
2. The manifest key, validated; the snapshot record; the index record.
3. The gc rule and its cost line.
4. `chartbook restore`.
5. The stop in `run` and `build`, with `--remake`; the line in `check`.
6. The guide page, the reference entries, the changelog.
