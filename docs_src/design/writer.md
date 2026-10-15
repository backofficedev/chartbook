# Design: the writer, and what every page shows

```{note}
A design document, written 2026-10-14 as the second of the four steps the maintainer approved:
vocabulary ({doc}`../guide/vocabulary`), then this inventory, then the Sphinx writer, then the
documentation site. Status: **inventory done; the index additions built (2026-10-14); the writer's first four slices
built (2026-10-15): the dataframe, chart, model and pipeline pages, each held equal to the
generator's by a golden test. The generator still writes the site.** The decisions it
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
3. **`date_range`** on a dataframe record with a `date_col`: the first and last date in the
   data, in ISO 8601; a text column is parsed as dates, and what does not parse is left out. *Proposed.* The engine answers it for a table
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

*Decided with the slice, proposed:* **a write-up is text, not a template.** The generator had
concatenated the write-up into the page's Jinja source, so `{{ name }}` or `{% if %}` inside a
write-up was evaluated, and `{{'a': 1}}` crashed the build; nothing documented it and no example
used it. The writer passes the write-up as a value, and the generator's dataframe page does the
same now, so what the author wrote is what the page shows. **The date rows of a table or query
come from the index's `date_range`**, which parses a text column as dates, where the generator had
shown the engine's least and greatest text. **A declared path is shown normalized**
(`../shared/x` as the folder it names), as the index and the resolver have it. An adversarial
review of the slice found the writer resolving a relative DuckDB url against the process's
working directory instead of the pipeline's folder, which the golden test's `chdir` had hidden
(fixed; the catalog theme, built from the catalog's root, is tested now); a published index gave
a bare `KeyError` (a message says the writer needs the full index); `docs_src_dir` unset dropped
the override paths (it defaults as the generator's). Known: the pipeline table's code-change time
is converted back from UTC to local for the page and can land on the other side of a repeated
DST hour.

*2026-10-15, slice 2: the chart page.* `SphinxWriter.chart_page()`. The chart's record gives its
declared fields and its file's path and `modified_at`; its `inputs` name the dataframe it was
drawn from, whose record gives the dataframe manifest table, the link and "Data updated"; the
pipeline's record gives the pipeline table and the fallback date for the listing's front matter;
the write-up is read at the path the record gives. The chart's HTML is not read: the page embeds
it by its path under the site, and the build copies it there (that copy is the build's, not the
writer's, as the inventory said). The link scheme gained the chart page's own forms, which the
generator had: a chart links to the pipeline's page from one folder less deep, and to its
dataframe through `../dataframes/` in both themes. Decided with it, proposed: **a chart's
write-up is text too**, as a dataframe's became; and **"Data updated" on a chart of a table or
query is the engine file's time** — the generator had taken the pipeline folder's own
modification time for it, since a table has no `path`, and now says what the writer says. The
writer does not refuse an index that a build could not have made (a chart whose dataframe record
is missing, or whose file has no `modified_at`): it writes the page with no data line and no
dataframe table, and takes the listing's date from the pipeline's code-change time, as the
generator would; the manifest loader and a strict build refuse both cases before an index exists.
The golden test covers the chart pages of the file-backed pipeline, of a chart drawn from a DuckDB
table (with a `series` list, which the index had been dropping from charts: `series` was treated
as structural for every kind, where only a dataframe's become Series records — an adversarial
review of the slice found it), and of the catalog. The same review found the generator's
provenance-panel cache keyed by the `id()` of the records dict, which a later build in the same
process could reuse after the first was freed; it holds the records themselves now.

*2026-10-15, slice 3: the model page.* `SphinxWriter.model_page()`. The whole page is in the
`Model` record, as the inventory said it should be: scores from `metrics`, the versions table from
`versions`, the files table from `files`, "Trained On" from `inputs` (a link when the input's
record is in this index, which is when its pipeline is part of the site; a name and a note
otherwise), and the out-of-date notice from `trained_with`, `inputs_now` and `stale_inputs`. The
third of those is new with this slice, and an adversarial review is why: the notice shows each
moved input's hash *then* and *now*, and the first version of the writer took "now" from the
inputs' own records (a local dataframe's `content_hash`, another pipeline's pin in
`pinned_inputs`), matching the lockfile-style keys of `trained_with` (`d`, `rates:treasury`) to the
build IDs of `inputs` by name. The review built the cases where that guess is wrong — the
declaration reordered after the snapshot, two upstream pipelines with a dataframe of the same
name, an input dropped from `trained_on` but still in the version's record — and showed the page
naming a wrong hash or raising. The index did not state the mapping, so the writer could not
derive it; now the record states the three facts of the comparison, keyed alike, and a reader
needs nothing else. The model's bytes are never read. The page's skeleton is still the generator's
two template strings, imported, until the generator goes and they move here. Decided with it,
proposed: **a model's write-up is text too**. Aligned on both sides: a directory model's files are
listed by path as text, as the index sorts them (the generator had sorted `Path` objects, which
order `a-b/x` and `a/x` the other way); a directory's `modified_at` in the index counts the files
its hash counts, and is absent when there are none — an empty folder, or one holding only
`.DS_Store`, had been given the folder's own time and so a "Model updated" line the generator did
not show; the generator's "Data updated" for a dataframe that is a directory now says the same
(it had shown the folder's own modification time, which moves only when an entry is added or
removed, so a folder of parts written days ago could be dated today); and training data that a pipeline *in the site* does not declare is named by its build
ID on both sides, with the note "which that pipeline does not declare" (the generator had named it
as stated and called it "not part of this site", which it was). The golden test covers a file
model with scores, a bare directory model, one with nothing counted in it, a model with two
versions that is out of date on a local and on another pipeline's dataframe, the same model in a
catalog that also holds the other pipeline (where "Trained On" links to it), and one trained on a
name its upstream does not declare.

*2026-10-15, slice 4: the pipeline page.* `SphinxWriter.pipeline_page()`. In the pipeline theme
it is the site's front page: the theme's `index.md` (or the project's override) rendered with the
README's text from the file the `Pipeline` record's `docs` names, the tables of contents made from
the records — notebooks and notes of this pipeline, dataframes and models of the site, each by
name — and "Code updated" from `code_changed_at`. In a catalog it is the pipeline's README page,
`cb/pipelines/<slug>_README.md`, with the repository and site named above the text from the
record's `repo_url` and `site_url`. One fact was added for it: a pipeline's own **site pages**.
The generator found them by walking `[project] site_dir` (or `docs_src/site/`), which the writer
may not do; the `Pipeline` record now carries `site_dir` (`path`, and `resolved_path` until
published) and `site_pages`, every Markdown file under it by relative path, sorted. The build
copies them beside the generated pages, as before; the writer lists them in the front page's
table of contents and reads `index_toc.md`, if it is one of them, to merge in. Decided with it,
proposed: **notebooks and notes are listed by name**, as the index has them, where the generator
had kept the manifest's order; the generator does the same now. Notebooks and notes themselves
are files the build copies, not pages the writer renders (the inventory above). The golden test
covers a pipeline site with and without its own site pages, one with notes, and a catalog's
README pages. An adversarial review found the generator ordering the site pages as `Path` objects
(`guide/intro.md` before `guide.md`) where the index orders them as text, and listing a directory
named `*.md`; the generator now does as the index does, since the index's order is the one any
reader of the JSON reproduces. It also found the writer splitting the README with `splitlines()`,
which breaks on a form feed where the generator's `readlines()` does not; both read lines now. A
diff says "site pages changed" when one appears or goes. Known: the site pages are listed without
hashes, so a diff cannot say *which* page changed. *Proposed:* give each the same `path` +
`content_hash` shape as a write-up when a reader needs it.

## What this does not decide

Whether a site built later for a past snapshot (the direction on the vocabulary page) reads the
write-ups from git at the snapshot's commit, or from the store; the `Build` record's full shape;
whether the catalog's diagnostics are computed by the writer or recorded by the build. Each is
marked above where it arises.
