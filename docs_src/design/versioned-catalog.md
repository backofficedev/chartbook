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
   test builds a site from one with the repository gone. As built, after a review and a live run
   on the examples:
   - **What is taken, and how.** Documents are named by the manifest's text, so a manifest a
     docs build refuses still keeps them; the index is best-effort for the same reason, and the
     command says in one line why it was left out (it is not tried again at that commit unless
     the bytes change). Only files git tracks are taken, asked of git with literal pathspecs; a
     path must be plain (`safe_relative`: nothing absolute on any system, no `..`, no part named
     `.git`, no `:`), and no file that is a link or under one is taken; each one not kept is
     said. The review found that without these, glob characters, git's pathspec magic and tracked
     links each reached files outside the folder.
   - **A record is untrusted.** A store may be shared, so `materialize` judges every path in a
     record by the same rule, follows no link inside an object, writes no `.git`, and writes
     nothing until every object the record names is there.
   - **A laid-out version keeps its identity.** `materialize` writes `.chartbook-version.json`
     (`chartbook.identity.VERSION_FILE`): the pipeline, the commit, when it was made and when its
     code last changed, from its index. A pipeline whose ID came from its folder's name and its
     git remote keeps that ID in a folder of any name, and its code time is not asked of a git it
     does not have. The live run found both missing.
   - **What a build writes and git does not keep** is written back where the snapshot recorded
     it: a model's scores to its `metrics_path`; a `site_dir` the manifest names is made if none
     of its files were kept. A table or query dataframe is in the store as parquet while the
     manifest names its database, so its page in a laid-out version says it is not built; the
     catalog's renderer (step 2) will read the parquet instead.
   - **Cost.** Making the index hashes every file again, as a docs build would; for large data
     that doubles the hashing a snapshot does. Accepted for an index that says exactly what a
     build of that commit would say.
   - **A second review** found more, all fixed with tests and every exploit script rerun: a
     tracked decoy whose name differs from an ignored file's only by a trailing space or a `\`
     (git's names are now taken exactly, never put in order, and decoded losslessly); `.git`
     aliases that HFS+ and NTFS make of other names (the rule is now git's own: case, the
     invisible code points HFS+ drops, trailing dots and spaces, `git~1`), with a last check
     after layout that removes any `.git` and refuses the folder; a store object folder that is
     itself a link (the folder store now refuses one); a file swapped for a link between being
     looked at and being read (a document is opened without following a link and must be the
     very file looked at); and the version file honoured where it does not belong (it is read
     only in a folder that is not a repository's own and where git does not track it, never
     when too large, and a laid-out version never has git asked about its code time). A named
     file git does not track is now said too.
2. **The catalog renders snapshots.** Working copies as today, plus the newest snapshot of each
   pipeline, each version at its own path. This proves rendering from the store. *Built
   2026-10-16, with every snapshot rather than the newest:* a version's site is built once on a
   machine and kept, so all of them cost what one did. Each Pipeline record of the index lists
   its `snapshots` in the store, newest first. A catalog build lays each one out from the store
   (`materialize`), builds it as the pipeline's own site in a process of its own, with the site
   tool its manifest names, keeps it under `versions/` in the machine's cache, keyed by the
   ChartBook version, and copies it into the catalog's site at
   `versions/<pipeline>/<commit>-<made_at>/`. A version that cannot be built gets a page that says
   why, and a `warning:` line, so a link to it never leads nowhere. A laid-out folder's Pipeline
   record says `from_snapshot`, and its front page says which snapshot it is. Built otherwise
   than item 4 of the section above: the version list is one catalog page, `cb/versions.md`, every
   pipeline with its working version and its snapshots, the commit, the date, whether `chartbook
   run` built it and which pipeline of the catalog pins it; not a list on each pipeline page,
   because the catalog's own pages are written on every build and a pipeline's page is not when
   an incremental build reuses it. Search is scoped by construction: each version is its own site,
   so the catalog's search finds the working versions only.

   *After the review, 2026-10-16.* Building versions automatically means running a docs build on
   files anyone who can write the store may have written, so a version's build runs as a build of
   files that are not the user's own (`chartbook.config.untrusted_source`): every template, a
   project's own included, renders in Jinja's sandbox, and a version takes no template from its
   folder at all; its site folder gives only pages and pictures; no page takes in a file
   (`file_insertion_enabled` off) and no picture or download that names a file outside the site is
   copied; notebooks are never run, as in any build; and each version's build has a time limit.
   Two holes the review found are closed for every build, not only versions': `conf.py` is
   rendered from the package's own template, never from the build tree where a site page named
   `conf.py.j2` could stand in for it, and a site page may not be `conf.py*`, `_templates/` or the
   tool's configuration. A snapshot record is checked when read (a full commit hash, a time as a
   snapshot writes one, a pipeline ID, a plain subdirectory), and `.` and `..` are no longer
   pipeline ID parts, so that no value in a record becomes a path outside the site or the cache;
   the review showed a forged `made_at` could otherwise delete and write folders anywhere. One
   record that cannot be read no longer hides every version; only a catalog's index lists
   snapshots, so a pipeline's published index carries no store history; the store is read twice
   per catalog build rather than once per pipeline; the kept sites are keyed by ChartBook's
   version and a fingerprint of its code, so an edit to ChartBook builds them again; a version
   whose snapshot `store gc` removed is removed from the site, the incremental build's tree
   included; and a staging folder a stopped build left is cleared.

   *After a second review, 2026-10-16.* The restrictions above held against forged snapshots, and
   the data path did not: a forged manifest could name a DuckDB query that reads any file of the
   machine, or a dataframe path outside the folder, and the version's pages showed the rows. In a
   build of files from a store, ChartBook now runs no table and no query at all (DuckDB refuses to
   open; the snapshot holds those rows as parquet, and the page says so), and the manifest loader
   refuses any path in `[project]` or an asset table (`path` and every `*_path`) that is not a
   plain path inside the folder, so that version's build stops and its page says why. Both
   forgeries were rerun against the fix: neither secret reaches the site.
3. **All versions.** Every snapshot, links following pins, the version list, snapshot pages kept
   across builds, search scoped. *What remains after step 2:* links following pins, so that a
   page of `C` links to `A` at the version `C` pinned, inside a version's site as in the catalog;
   a catalog entry by pipeline ID alone, for a pipeline whose folder is not on this machine; and
   clearing the kept sites, in the cache, of snapshots `store gc` removed. *Built 2026-10-16, in
   part, after a review:* the only input of another pipeline a page has is a model's training
   data. In a catalog, a model's "Trained On" links each such input to its page in the snapshot
   that held the bytes it was trained on (the index records it as `trained_from`, from
   `trained_with` and the store), and says when the pin has since moved; failing that, to the
   snapshot the lockfile pins for that input; failing that, to the working version, as before.
   The provenance panel links an input the lockfile pins to its page in the pinned snapshot; it
   linked nothing before. A link leads into a version only when the catalog shows that snapshot,
   and to the page that says why when its site could not be built, so the catalog builds the
   versions' sites before its own pages. An incremental build regenerates a pipeline's pages
   when any of this changes. `store gc` clears the kept site of every snapshot it removes. Not
   built: the same links inside a version's own site, which is built once and kept, and so
   cannot know which other versions a catalog will show; its pages say the pinned commit and
   date in words. And a catalog entry by ID alone, which is the next step.
4. **An assistant file** for generated sites, written from the index.
5. **A development build**, later if wanted: a folder with gaps rendered with its assets marked
   not built and its notebooks unexecuted.

## What this does not decide

How a version is named on a page (the commit's start and the date is the proposal); whether a
snapshot should also carry template overrides from `docs_src/_templates`; whether the version
list should be a drop-down in each theme; what the assistant file is called.
