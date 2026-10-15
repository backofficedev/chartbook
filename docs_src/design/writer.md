# Design: the writer, and what every page shows

```{note}
A design document, written 2026-10-14 as the second of the four steps the maintainer approved:
vocabulary ({doc}`../guide/vocabulary`), then this inventory, then the Sphinx writer, then the
documentation site. Status: **inventory done; the index additions built (2026-10-14); the writer's first slice built
(2026-10-15): the dataframe page, held equal to the generator's by a golden test. The generator
still writes the site.** The decisions it
proposes are marked *proposed* until the maintainer takes them.
```

## What this is for

A **writer** turns the index into **pages** for one site tool. For the Sphinx writer to replace the
generator that writes pages today, two things have to be true: the index must carry every *fact*
a page shows, and every *rendering* a page shows must be something the writer can make from
facts. This page inventories every section of every page the generator writes now, says which it
is, and lists what the index must gain. The rule it applies is the one on the vocabulary page: the
index records facts about the build, including comparisons it made, and no renderings.

## The writer's input: the index, and the files it names

*Proposed.* The vocabulary page settles that the writer reads the write-ups the index points at,
because they are source and not facts about the build. The inventory below shows the same is
true of two more things a page shows: the **first rows of a dataframe** (the glimpse) and a
**chart's HTML** (the iframe). Neither is a fact about the build, and neither belongs in a JSON
file; both are files the index names, with their hashes. So the writer's input is: **the index,
and the files the index names** — write-ups, data files, chart files, notebooks — read at the
paths the index gives, and nothing else. A writer never reads a manifest, never walks a folder,
and never asks git. The index is the map; the files are the territory it maps.

## The inventory

Each row: a section a page shows today; what it shows; whether that is a **fact** (belongs in the
index), a **rendering** (the writer makes it from facts), or a **file** (the writer reads what the
index names); where the generator gets it today; and whether the index has it.

### Every asset page

| Section | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Title | Kind, ID, name | fact | manifest | yes |
| Freshness line | When the data file was last written ("Data updated 2 days ago"); for a chart, when the chart file was; "Code updated" on the pipeline page | fact: a file's modification time; a pipeline's last code change | file system; git | **no.** Add `modified_at` to a `file` location; add the pipeline's last code change to the `Pipeline` record |
| The write-up | The author's text, from `docs_path` or inline `docs` | file | the file, or the manifest | partly: `docs` has the path or the text. Add the **hash** (decided) |
| Provenance panel | What this is, where, hash, size, rows, built by, made from, used by, version | fact | the index | yes (6b) |
| Manifest tables | Name, description, tags, sources, providers, links, access, pull method, units, frequency… every declared field | fact | manifest | yes: every declared field is on the record |
| Pipeline manifest table | Name, ID, maintainer, contributors, repository, site URL, OS, code update date, linked dataframes, build command | fact | manifest; git | mostly. Add `site_url` and `readme` if absent; the code change date as above; linked dataframes are the `assets` list |
| Download links | Parquet, Excel, HTML of the chart | rendering of a location | manifest | yes (location) |

### Dataframe page

| Section | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Glimpse | Row and column counts, dtypes, one sample row | counts and dtypes: fact (`row_count`, `columns`); the sample row: **file** | the parquet file | counts and columns yes; the sample is read from the file the location names |
| Data available up to (min/max) | For a file: the least and the greatest, over the other columns, of the last date at which that column is non-null (a staleness measure across columns); for a table or query: the first and last date | a **comparison the writer makes from the file**, for a file; a fact, for a table or query | the parquet file; the engine | the plain first and last date are now a fact, `date_range`, for both; the per-column measure the file page shows stays a rendering the writer computes from the file it names |
| Table / query row | Source, identifier or SQL | fact | manifest | yes (location) |
| Linked charts | Charts whose `dataframe` is this one | rendering of a comparison | manifest | yes: the charts' `inputs`; the panel's reverse map |
| Series tables | Documented columns | fact | manifest | yes (`Series` records) |

### Chart page

| Section | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Front matter | Date, tags, category, for ABlog's listing | rendering of facts: the chart file's time, the dataframe's `sources`, the chart's `tags` | manifest; file system | yes once `modified_at` exists |
| The chart | The HTML file, in an iframe; "Sources: …" under it | **file**; a fact | the chart file; the dataframe's declared fields | the location names the file; `sources` is on the dataframe record |
| Chart specs | Frequency, units, period, release lag… | fact | manifest | yes |

### Model page

| Section | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Scores | The metrics file's values | fact | the metrics file | yes (`metrics`) |
| Versions table | Each version: name, made, commit, labels, each metric | fact | the store | yes (`versions`) |
| Trained on | Each input, linked where the site has it | rendering: links from `inputs` | manifest; site manifest | yes (`inputs`) |
| Out of date | The inputs that moved, then and now | fact: a comparison the build made | the store, the lockfile, the files | yes (`trained_with`, `stale_inputs`) |
| Files | A directory model's files and sizes | fact | the file system | yes (`files`) |

### Pipeline page, notebooks, notes

| Page | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Pipeline README | The README's text under a title; the manifest table | file; facts | the README file | `docs` on the `Pipeline` record names it; add the hash |
| Notebook | The executed notebook, rendered by Sphinx | file | the `.ipynb` file | the location names it |
| Note | The write-up | file | the file | the location names it |

### The catalog's own pages

| Page | Shows | Is | Today from | In the index |
|---|---|---|---|---|
| Landing | Cards to charts, dataframes, models, pipelines, contributing, diagnostics | rendering (static text) | the theme | nothing needed |
| Lists (dataframes, models, pipelines) | Every page of a kind | rendering of the records | the manifest | yes |
| Charts | ABlog's listing by date and category | rendering | front matter | yes once `modified_at` exists |
| Diagnostics | Which assets lack which required fields, against the policy | **a comparison**: rendering, or a fact the build records | `diagnostics.py`, against `[policy]` | the `Catalog` record must carry the **policy**; then the writer computes it, or the build records a `complete` flag per record. *Proposed: the writer computes it; the policy is a fact, completeness is a comparison any reader can make* |
| Contributing | Static text | rendering | the theme | nothing needed |

## What the index must gain

In the order a writer needs them. Each is a fact, and each is small. *(All built 2026-10-14,
the same day, as 6c; `tests/test_index.py`, `TestWhatTheWriterNeeds`. The diff reads what a
file holds, not when it was written, so `modified_at` alone is not a change; a changed write-up
reads "write-up changed", a `date_range` whose last date moved "data reaches further" or "less
far", a pipeline's `code_changed_at` "source changed". A review found and fixed: `code_changed_at`
was written from file times by any `build_index()` while the schema promised git — it is present
only in an index a docs build writes; a directory's `modified_at` was the directory's own; a text
`date_col` gave a lexical range — only temporal columns are read, in ISO 8601; the diff said
"reaches further" whatever the direction. Known: the time is carried as an instant when freshly
worked out, and from the incremental state's local-time string when remembered, so a state file
reused on a machine in another zone, or a stamp in the repeated hour of a DST change, can be off.)*

1. **The write-up's path and hash** on every asset record and on the `Pipeline` record (its
   README). *Decided 2026-10-14.* A build then says which text it showed, and a diff says the
   write-up changed.
2. **`modified_at`** on every `file` location: when the file was last written, in UTC. The
   freshness lines and ABlog's dates come from it. *Proposed.*
3. **`date_range`** on a dataframe record with a `date_col` of a date or datetime type: the
   first and last date in the data, in ISO 8601. *Proposed.* The engine answers it for a table
   or a query; for a file it is one column, read from the parquet statistics. The file page's
   per-column "available up to" rows are a different quantity, a comparison across columns,
   which the writer computes from the file it names.
4. **`code_changed_at`** on the `Pipeline` record: when the pipeline's code last changed, as
   the build works it out (the last commit that touched the source where it is committed and
   unmodified, else the newest modification time), which the pipeline page shows today.
   *Proposed.* The index asks git for nothing itself: the build works the times out once, and
   an incremental build remembers them for the pipelines it reuses. It is the first field of
   the `Build` record the index design leaves for later; the rest of that record (the commit
   the site was built at, the time, the tool versions) belongs with it, and the envelope's
   `generator` already carries the versions.
5. **The policy** on the `Catalog` record, so the diagnostics page is a comparison a reader can
   make. *Proposed.* The schema has a place for it.
6. **`site_url` and `readme`** on the `Pipeline` record if either is missing; a check, not a
   design.

Nothing on this list is a rendering. The sample row, the chart HTML and the write-up text stay
in the files the index names.

## The writer, in outline

*Proposed.*

- **One module per site tool**: `chartbook/writers/sphinx.py` first. Its input is the index and
  the files it names; its output is a folder of pages and the files Sphinx needs beside them.
  It takes the theme (`pipeline` or `catalog`) and the build options the pages depend on.
- **The link scheme is the writer's.** `page_path(record) -> str` and `link(from, to) -> str`,
  one rule per writer. The provenance panel names assets by ID today because the scheme is not
  yet a function; it becomes one here, and the panel gains links.
- **Today's Jinja templates become the Sphinx writer's templates.** They already render from a
  context; the context becomes the record plus what the writer computed. The generator is
  replaced section by section, each section's page compared with the old one on the example
  sites, and the old code removed when the pages match.
- **Golden tests:** one page of each kind, rendered from a fixed index and fixed files, compared
  whole. The index is small enough to keep as a fixture.
- **MkDocs and Next.js** are later writers reading the same index; they are why the index stays
  free of renderings. Not scheduled.

## As built, slice by slice

*2026-10-15, slice 1: the dataframe page.* `chartbook/writers/sphinx.py`, `SphinxWriter`. Its
input is the **full** index (with `resolved_path`, since it reads the files the index names) and
the files; it takes the theme, the project's own `docs_src` for template overrides, and the two
build options the page depends on. It renders today's templates unchanged, from a context made
of records: the dataframe's declared fields and location; a `project` table and the dataframes
list made from the `Pipeline` record; the write-up read at the path the record gives; the glimpse
and the per-column date rows from the data file, or from the engine for a table or a query,
opened through `chartbook.backends.source_url()` from the public `url` the location now carries;
the freshness line from `modified_at`; the panel from the records. The link scheme is three
functions on the writer. A golden test (`tests/test_writer_sphinx.py`) builds the site with the
generator and asserts the writer's page is the same text, on a file-backed pipeline and on one
with a DuckDB table and query. Two facts were added for it: `site_url` on the `Pipeline` record
(dropped from the published index when it is a local `file://` path, as `resolved_path` is) and
`url` on a table or query location. Not yet: the chart, model, notebook, note and pipeline pages,
the catalog's list pages, and the build calling the writer instead of the generator.

## What this does not decide

Whether a site built later for a past snapshot (the direction on the vocabulary page) reads the
write-ups from git at the snapshot's commit, or from the store; the `Build` record's full shape;
whether the catalog's diagnostics are computed by the writer or recorded by the build. Each is
marked above where it arises.
