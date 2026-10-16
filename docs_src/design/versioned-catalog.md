# Design: the versioned catalog

```{note}
A design document, written 2026-10-16 after the maintainer and the last person to work on this
talked through what an index is for and what a snapshot is for. The conclusion is here, with the
plan it leads to. Status: **the self-sufficient snapshot (step 1) is built; the rest is proposed.**
What the maintainer decided is marked *decided*.
```

## The use cases this serves

1. A project grows and is split into repositories. One depends on the outputs of another, and
   the dependencies diverge: `B` reads `A` at one version while `C` reads `A` at a later one.
2. Depending upstream must be reproducible and show its lineage: which version of what, by
   commit and by hash.
3. One place to browse everything a person is working on, across every pipeline and every
   version of each, with links that follow the real dependencies.
4. An assistant browses the same thing from the command line.
5. While working on one repository, its own site is rebuilt now and then, for the author and
   for collaborators, from whatever is in the folder.

The first two exist: declared dependencies, pins by commit and hash, snapshots in the store, the
provenance panel. The fifth is today's pipeline site. The third and fourth are what this page
plans.

## Index and snapshot: the conclusion

*Decided 2026-10-16.* The two documents stay two documents, and the record format they share is
the only merge. They are different acts:

| | A **snapshot** | An **index** |
|---|---|---|
| Is | A preservation act: the bytes one pipeline built at one commit, copied into the store, declared ready | A description of what a site shows, taken from whatever is in the folders now |
| Needs | Everything committed, the bytes present | Nothing committed; a pipeline with missing outputs can be skipped |
| Covers | One pipeline, once | Many pipelines at once, the catalog's own facts, and comparisons no one pipeline can make: a model out of date against its inputs now, versions read across commits |
| Lives | In the store | Beside the site, and a copy without machine paths travels with it |

Neither is derivable from the other. A snapshot cannot be made from an index: the index has
hashes and not bytes, no commit, and may describe a half-built folder. An index can almost be
assembled from snapshots, but only from every pipeline's snapshots plus the files at those
commits plus the store, and the result describes what was declared ready rather than what is in
front of you. That is a different site, and a useful one; it is the catalog below.

What was wrong before this conversation: a snapshot could not render a site. The index records
facts and pointers, not the write-ups, notebooks, or chart files, and those came only from a
checkout. So a version's site, and a version's data dictionary as it stood when the data was
made, lived in git and nowhere else. The maintainer's point: the snapshot of the data should
carry the description of the data.

**So a snapshot holds the index of its version.** Not a merge; nesting. A snapshot contains the
pipeline's own index at that commit and the small documentation files a writer needs; a site's
index is assembled from version indexes plus the comparisons only a site can make. The
vocabulary page says this now, where it used to say the two "converge".

## The catalog shows every version of every pipeline

*Decided 2026-10-16.* A catalog shows every snapshot in the store of every pipeline it knows,
found by pipeline ID, plus the **working version** of each pipeline whose folder is on this
machine: the folder as it is, committed or not, built or not, which is what the pipeline's own
site shows too. The store is the source of versions; the catalog's manifest is the source of
working copies, as it is today. A catalog with no snapshots is today's catalog, so nothing
breaks. "Latest" is not a word here: the working version is the working version, and the newest
snapshot is the newest snapshot.

What that needs:

1. **Which versions.** Every snapshot of every pipeline the catalog lists, and the working
   version of each whose folder is present. A snapshot that `store gc` removes leaves the catalog
   with it: gc is the lifecycle.
2. **Pages per version**, each set under a path that carries the pipeline ID and the version:
   the commit's start and the snapshot's time, since one commit may have several snapshots when
   a pull script brought other data. Static pages are cheap.
3. **Links follow pins.** `C`'s pages link to `A` at the snapshot `C` pinned; `B`'s to the
   other. The link scheme is a function of the writer for this reason.
4. **A version list on every pipeline page**: the working version first, then snapshots newest
   first, with the commit and the date, each a link to the same page in that version or to the
   version's front page where the page does not exist there. Both writers render it as a list; a
   drop-down is theme work.
5. **Comparisons stay within a version.** An out-of-date notice compares what a version
   recorded with what it pinned, never with a version it did not pin.
6. **Rendering a snapshot costs once.** A snapshot never changes, so its pages are rendered the
   first time a catalog build sees it and kept; only working versions are rendered every build.
   The incremental build is the home for that rule.
7. **Search is scoped** to working versions and newest snapshots by default, or every hit is a
   near-duplicate.
8. **Diagnostics and policy** apply to working versions; a snapshot's metadata is history.

A shared store makes a shared catalog: with the S3 store, a team's catalog is built from the
bucket, and that is the use case for several machines ({doc}`stores-and-backends`).

## For the assistant

The catalog's `index.json` is the assistant's entry point already. Generated sites should also
ship an assistant file written from the index, one line per pipeline, dataframe, chart and
model with where its page is, so that a command-line agent finds its way without scraping.

## The order of work

1. **The self-sufficient snapshot.** The snapshot carries the pipeline's own index at that
   commit, in the published form, as an object in the store, and the documentation files a
   writer needs that are not assets: the manifest, the lockfile, the README, every write-up, the
   pipeline's own site pages, the logo and favicon. Notebooks, notes, charts, dataframes and
   models are assets already. A snapshot can then be laid out as a folder from the store alone
   and a site built from that folder, which is the test. *Built 2026-10-16:* `Snapshot.index`
   and `Snapshot.documents` in the record, written by `chartbook snapshot`, kept alive by `store
   gc` like the assets; `chartbook.snapshot.materialize()` lays a snapshot out as a folder, and a
   test builds a site from one with the repository gone.
2. **The catalog renders snapshots.** Working copies as today, plus the newest snapshot of each
   pipeline, each version at its own path. This proves rendering from the store.
3. **All versions.** Every snapshot, links following pins, the version list, snapshot pages kept
   across builds, search scoped.
4. **An assistant file** for generated sites, written from the index.
5. **A development build**, later if wanted: a folder with gaps rendered with its assets marked
   not built and its notebooks unexecuted.

## What this does not decide

How a version is named on a page (the commit's start and the date is the proposal); whether a
snapshot should also carry template overrides from `docs_src/_templates`; whether the version
list should be a drop-down in each theme; what the assistant file is called.
