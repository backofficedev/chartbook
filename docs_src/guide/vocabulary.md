# Vocabulary

ChartBook has few words, and they are used exactly. This page is where they are defined; every
other page uses them in these senses.

## The sentence

**A manifest asks, a lockfile records what was got, a snapshot records what was made, and an
index records what a site shows.**

## The chain

A pipeline is a folder of code in git. ChartBook turns it into a site in three steps, each a
transformation of the one before:

```text
 repository ──resolve──▶ index ──write──▶ pages ──build──▶ site
 (source)               (the facts)       (text for a tool)   (HTML)
```

| Word | What it is | Who makes it |
|---|---|---|
| **repository** | A pipeline's folder in git: its manifest, its code, its write-ups and the data it builds. For a catalog, several of these. The **source**: when anything disagrees with the repository, the repository is right | People |
| **index** | One JSON file, `index.json`, describing everything a site contains: every pipeline and asset by ID, where each is, its content hash, what it was made from and at which hashes, what pins what. The record of what was true when the build ran | `chartbook docs` (and `chartbook build`, which runs the build first). Never `chartbook run` |
| **pages** | The files a site tool reads: Markdown for Sphinx or MkDocs, JSX for Next.js. Text, never data | A **writer**: one per site tool, reading the index and the write-ups it points at |
| **site** | HTML | The site tool, by its name: Sphinx today; others later |

Two roles, named by what each does and not by what it produces:

- A **writer** turns the index into pages for one site tool. ChartBook's writers are its own;
  the Sphinx writer is the first, and MkDocs and Next.js writers are on the roadmap, reading the
  same index.
- A **site tool** turns pages into a site: Sphinx, MkDocs, Next.js. ChartBook writes none of these
  and calls each by its name.

## The four documents

Four files, one record format. Each answers a different question, and none is another in
disguise.

| Document | File | Records | Written by | Where it lives |
|---|---|---|---|---|
| **manifest** | `chartbook.toml` | What a pipeline *asks*: which assets it declares, where they are, what it depends on, what its scripts are | People | In the repository, committed |
| **lockfile** | `chartbook.lock` | What was *got*: for each dependency, which snapshot was pinned and the content hash of each of its assets | `chartbook pin`, `chartbook update` | In the repository, committed. No timestamp on purpose: a `git diff` of it means "a pin moved" |
| **snapshot** | `<store>/snapshots/<commit>/…/<time>.json` | What was *made*: every asset one pipeline built at one commit, with its hash, declared ready by its owner | `chartbook snapshot`, `chartbook run --snapshot` | In the store, with the bytes. Not in git, since one commit can have several |
| **index** | `index.json` beside the site | What a site *shows*: every record of every pipeline the site contains, as built now, with each dependency's pins reported | `chartbook docs`, `chartbook build` | Beside the site, so it travels with it |

Three rules follow, and they settle arguments:

1. **The lockfile is an input to a build; the index is its output.** One cannot be the other.
   The index *reports* pins and never makes one. They share one record format, and that is the
   only merge there is.
2. **The index records facts about the build, including comparisons it made, and no
   renderings.** A fact is an ID, a location, a hash, a row count, an input, a pin, a version, a
   label, the path and hash of a write-up, or a comparison such as which of a model's inputs
   have moved since it was trained. A rendering is anything a writer makes from facts: a table of
   first rows, a "2 days ago", a link, a page. Renderings stay out, so that the index can be
   turned into pages for any tool.
3. **Write-ups are not pinned.** A snapshot records the commit it was made at, and the commit
   holds the write-ups as they were. The index records each write-up's path and hash, so a build
   can say which text it showed.

## Where this is going

A snapshot is one pipeline's index at one commit, kept with its bytes. A site's index is its own
pipeline at the current build, plus each dependency's pinned snapshot, plus the catalog. The two
converge: a site is a pure function of an index and the write-ups at the commit the index names,
so a site can later be built for any snapshot, and lineage can link across sites by commit. That
is the direction; it is not built.

## The rest of the words

| Word | Means |
|---|---|
| **pipeline** | One project with a `chartbook.toml`: code that produces assets. Identified as `scope/name`, e.g. `ftsfr/fed_yield_curve` |
| **scope** | The organization or owner half of a pipeline's ID. Taken from the git remote's owner |
| **catalog** | A `chartbook.toml` that lists pipelines and builds one site over all of them. It declares no assets of its own |
| **asset** | Something a pipeline declares: a dataframe, chart, notebook, note or model |
| **kind** | Which of those five an asset is. Written singular: `chart` |
| **dataframe** | A table of data: a parquet file (or a glob of them), or a table or query in a source |
| **series** | One column of a dataframe, given its own address and documentation |
| **part** | Something inside an asset, addressed with `#`. A series is a dataframe's part; a file is a model's part |
| **reference** | The address of an asset: `[registry/][scope/]pipeline:[kind/]name[#part][@rev]` |
| **local reference** | A reference with no `pipeline:` in front: "in the pipeline I am in" |
| **front door** | A Python module that hands out one kind of asset: `chartbook.data` for dataframes, `chartbook.models` for models, `chartbook.assets` for any kind |
| **location** | Where an asset physically is: a file, or a table or query in a source |
| **record** | One entry in the index, a lockfile or a snapshot. Each has a `kind` (`Dataframe`, `Chart`, …) and a `version` |
| **store** | A folder of files named by their hash: `~/.chartbook/store`, or one a team shares. Holds snapshots and the pinned copies pipelines read |
| **object** | One asset in the store: a directory named by the asset's content hash, holding its files under their own names |
| **dependency** | Another pipeline this one reads from, declared in `[dependencies]`: a name, and where to find it (`path` or `git`) |
| **pin** | To freeze which snapshot of a dependency a pipeline reads; also the record of it in the lockfile. `chartbook pin` makes pins and never moves one; `chartbook update` moves them |
| **version** | A model's bytes as a snapshot first held them, named by the first twelve digits of their hash; `[models.x.aliases]` gives labels such as `champion` |
| **source / backend** | A named database connection in a manifest / the engine behind it. DuckDB is the engine that is built |
| **writer** | What turns the index into pages for one site tool |
| **scratch** | `_data/_scratch/` inside a pipeline: throwaway files that are not assets |

Three different things are called "kind", and they do not mix: an **asset kind**, lowercase, in
a reference (`chart`); a **record kind**, capitalized, in the index (`Chart`, plus the non-asset
records `Catalog`, `Pipeline`, `Series`); and a **location kind**, inside a record's `location`
(`file`, `table`, `query`).
