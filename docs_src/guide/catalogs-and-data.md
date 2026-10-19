# Catalogs and Data Access

A catalog aggregates pipelines into one searchable site and gives every dataset a stable, loadable address: `pipeline` + `dataframe`. A typical setup is one **local catalog** per person or machine (auto-discovering your working repos) plus **shared catalogs** maintained explicitly.

## The catalog manifest

A catalog is a `chartbook.toml` with a `[pipelines]` table — that table's presence is what makes it a catalog. Keys are scoped pipeline IDs, quoted because they contain `/`:

```toml
[project]
name = "Team Analytics Catalog"

[pipelines."acme/yield_curve"]
path = "../yield_curve"

[pipelines."acme/fred_charts"]
path = { unix = "/data/pipelines/fred_charts", windows = "T:/pipelines/fred_charts" }

[pipelines."acme/old_thing"]
path = "../old_thing"
disabled = true          # kept, but skipped during builds
```

`chartbook docs generate` inside the catalog directory renders the combined site: chart and dataframe listings across all member pipelines, per-pipeline pages, and a diagnostics page showing metadata completeness.

A catalog's site is built from its own folder and from every member folder on this machine, and each of them must be one you trust: `chartbook trust --members` in the catalog's folder records them all, and until then the build stops and lists the folders that are not ({ref}`chartbook trust <chartbook-trust>`). A member the catalog shows from the store has no folder here and needs no trust. `chartbook run` in a catalog runs each member's build script, and asks the same of each.

## The global catalog

For personal use there's a ready-made location, `~/.chartbook/chartbook.toml`, with its own commands:

```console
chartbook catalog init            # create it
chartbook catalog add ../my-repo  # register a pipeline
chartbook catalog generate        # render its site into ~/.chartbook/docs/ (only what changed since last time)
chartbook catalog open            # open that site
```

`catalog add` keys each pipeline by its ID ({ref}`the rule <pipeline-identity>`): at the top of a repository with a remote (its `repo_url`, or else its git `origin` remote), the repository's name (`ftsfr/crsp_treasury` from `github.com/ftsfr/crsp_treasury`, whatever the folder is called); in a subfolder, the remote's scope and the subfolder's name; with no remote, the folder's name. It stores the path relative to the catalog, between the two folders as they really are, with any link in their paths followed (so a home folder reached through a link works), and skips duplicates. It accepts globs (`chartbook catalog add ../repos/*`) and a `--catalog` option to target a catalog other than the default. `chartbook catalog disable <id>` / `enable <id>` toggle entries without deleting them.

## Auto-discovery with `members`

For a local catalog, you can skip per-pipeline entries entirely: declare membership as path patterns, and any pipeline dropped into a matched directory joins automatically.

```toml
[pipelines]
members = [
    "../GitRepositories/ftsfr_repos/*",
    "../GitRepositories/finm33200/news_headlines",
]
exclude = ["../GitRepositories/ftsfr_repos/scratch_*"]
disabled = ["ftsfr/sovereign_bonds"]
```

The rules:

- Patterns resolve relative to the catalog directory. Each matched directory containing a pipeline `chartbook.toml` joins under its derived scoped ID.
- Glob matches are forgiving — non-pipeline directories and other catalogs are skipped silently, and a catalog never discovers itself. A *literal* member path that is missing or broken is a hard error: you named it explicitly.
- Two members deriving the same ID, or a v1-format member, are hard errors with "To fix" suggestions. Two checkouts of one repository (a worktree beside it, a second clone) are one pipeline, listed once: from the main worktree, else from the one found first, or from the explicit entry when one names a checkout of it, with a warning naming the other.
- `disabled` lists IDs to switch off (`chartbook catalog disable` maintains it for member-discovered pipelines); `exclude` removes paths before matching; explicit entries coexist with `members` and win when they point at the same directory — which is also how you rename a pipeline within your catalog.

Auto-discovery is designed for the local catalog, where "everything in this directory is mine" is exactly right. Publishing to a shared catalog should stay an explicit act with explicit entries.

## Versions

A catalog shows every pipeline twice over. The **working version** is the pipeline's folder as it is now, and every page of the catalog shows it. Each **snapshot** of the pipeline in the store (`chartbook snapshot`, see {doc}`depending-on-pipelines`) is a version its owner declared ready, and the catalog builds each one as the pipeline's own site, from the store alone, with the write-ups and the data dictionary as they were then. The **Versions** page lists them all, newest first, with the commit, the date and which pipeline of the catalog pins each one.

Links follow pins: on a catalog page, a model's training data from another pipeline links to its page in the snapshot that held the bytes the model was trained on, and the page says when the pin has since moved; the provenance panel links it to the snapshot the lockfile pins now. Where the catalog shows no such snapshot, "Trained On" links the other pipeline's working version and the panel links nothing. A version's site is built once on a machine and kept, under `~/.chartbook/cache/versions/` (`[cache] path`, or `CHARTBOOK_CACHE`), so later builds only copy it. One that cannot be built, an object gone from the store, say, gets a page that says why, and the build prints a `warning:` line. The versions are separate sites: the catalog's search finds the working versions.

**For an assistant.** The catalog's `llms.txt`, beside its `index.json`, lists every pipeline, dataframe, chart and model with a link to its page, and each pipeline's newest versions, each linking that version's own `llms.txt`. An agent reading a catalog from the command line starts there.

**A pipeline that is not on this machine.** Name it in the catalog with no path, `"acme/rates" = {}` under `[pipelines]`, and the catalog shows it from its snapshots in the store: its page says what its newest snapshot says of it, as plain text, and links that version, and the Versions page lists every one. When you later clone it and add its folder, the folder fills the entry in. A store a team shares makes this the way to browse a colleague's pipeline without cloning it.

**Whose files these are.** A store may be one a team shares, and anyone who can write to it can put a snapshot in it, as anyone whose repository your catalog lists can put pages in it. So a version's site is built as files that are not your own: no template from its folder, every template in Jinja's sandbox, only pages and pictures from its site folder, no page taking in a file, no picture or download from outside the site, no table or query run, no path outside its folder, no notebook run, and a time limit. Its pages are still its owner's, HTML and script included, as a listed repository's pages are, and they are served with your catalog: share a store only with people you would let put pages in your catalog. A snapshot record that is not what a snapshot writes is not shown, and the build says how many there were. On the catalog's own pages, what a snapshot says of its pipeline (its name, description and maintainer) is shown as plain text, never read as Markdown or HTML, with HTML's own characters (`< > " '` and the backtick) shown as look-alikes and `&` as "and", and its repository and site are links only when they are web addresses.

## Requiredness is catalog policy

The manifest format itself is permissive — every field optional. Which fields member pipelines *must* fill in is the catalog's decision, declared in `[policy]`:

```toml
[policy]
mode = "warn"          # default: report gaps on the diagnostics page
                       # "strict": fail the catalog build instead

[policy.required]
project    = ["description", "maintainer", "repo_url"]
dataframes = ["date_col", "pull_method"]
charts     = ["units", "frequency"]
```

With no `[policy]` section, a built-in recommended-field list drives the diagnostics page, warn-only. A pipeline may have a `[policy]` of its own, which it is held to when it is checked or built by itself; inside a catalog, the catalog's policy applies and the pipeline's is ignored. `mode = "strict"` fails the build, a catalog's or a lone pipeline's, on a missing required field.

### Enforcing it in CI

`chartbook check` is the gate. It exits nonzero when a field a policy requires is missing, a declared path points at nothing, or a dataframe's `license_expiration` has passed or is within 30 days, naming the manifest and field each time.

```console
chartbook check                        # in a catalog: every member, against its [policy]
chartbook check --policy ../catalog    # in a pipeline: against that catalog's [policy]
chartbook check --within 90            # widen the license window
chartbook check --skip-outputs         # in CI, without building the data first
```

A pipeline is checked against its own `[policy]` when it has one, unless `--policy` is given: then the file's `[policy]` replaces it, as a catalog's replaces its members', and a file with none, such as a catalog that sets no policy, gives no policy. When no policy is given anywhere (none in the pipeline, none in the catalog it is checked in, and no `--policy`, or a `--policy` file with no `[policy]` table), the built-in recommended list is advice: each missing field is a `warning:` line and the check does not fail on it. A dataframe or chart with no write-up fails it all the same, since the format requires one. Details: {doc}`../reference/cli`.

## Loading data

Point ChartBook at a catalog once:

```console
chartbook config
```

This writes the catalog path into `~/.chartbook/settings.toml` (the global catalog works without any configuration). Then every cataloged dataset is loadable by name.

```{note}
This is loading *through a catalog*: from a notebook or a script that belongs to no pipeline, for looking at data. It reads each pipeline's newest snapshot in the store, and its own folder, as it is right now, only when it has none, with a warning. Called from a file inside a pipeline that declares the other one, it reads that pipeline's pin instead, wherever the script is run from, as `data.load("yield_curve:repo_public")` would.

Inside a pipeline that depends on another one, declare the dependency and pin it instead. `data.load("yield_curve:repo_public")`, with one argument, then reads a frozen copy and needs no catalog. See "Depending on another pipeline" in {doc}`documenting-a-pipeline`.
```

```python
from chartbook import data

lf = data.load(pipeline="yield_curve", dataframe="repo_public")   # polars LazyFrame (default)
df = data.load(pipeline="yield_curve", dataframe="repo_public", format="pandas")
df = data.load(pipeline="yield_curve", dataframe="repo_public", format="polars_eager")

path = data.get_data_path(pipeline="yield_curve", dataframe="repo_public")  # the parquet path
text = data.get_docs(pipeline="yield_curve", dataframe="repo_public")       # the write-up, as a string
where = data.get_docs_path(pipeline="yield_curve", dataframe="repo_public") # the write-up's source file
```

All of these accept `catalog_path="/path/to/catalog"` to bypass the global setting. Inside a pipeline, `data.path("repo_public")` gives the path of one of its *own* dataframes straight from its `chartbook.toml`, with no catalog involved (and `assets.path("chart/repo_rates")` that of a chart, notebook or note) — see {doc}`documenting-a-pipeline`. Hive-partitioned (glob-path) dataframes support only the LazyFrame default — call `.collect()` to materialize.

### SQL

Inside a pipeline, write SQL and name dataframes in braces. ChartBook puts each name in and the engine runs the rest:

```python
from chartbook import data

recent = data.sql("""
    select r.Date, r.SVENY10, s.slope_10y_2y
    from {fed_yield_curve} r
    join {yield_slopes} s on r.Date = s.Date
    where r.Date >= '2024-01-01'
""")                                      # a LazyFrame; .collect() runs it
```

A file is read as a table (`read_parquet('…')`), a table in a source by its name, a query dataframe as a sub-select. The SQL runs in one engine: the source the tables and queries are in, or a fresh in-memory DuckDB when the query names only files. Another pipeline's file, `{fed_yield_curve:treasury_rates}`, is the pinned copy, as everywhere else. ChartBook does not parse or rewrite the SQL; what is between the braces is a reference, and everything else is yours, in DuckDB's dialect. A literal brace, as in DuckDB's `{'a': 1}` struct syntax or inside a string, is written twice: `{{'a': 1}}`.

For SQL you run with your own tooling, `data.ref("yield_slopes")` gives the name to paste in, and `data.connect("local")` is the raw, read-only connection to a source. {ref}`[sources] <sources>` says how a pipeline declares one.

The same lookups exist on the command line, for shell scripts and quick checks:

```console
chartbook ls                       # tree of every pipeline, dataframe, and chart
chartbook ls dataframes            # flat list
chartbook data get-path --pipeline yield_curve --dataframe repo_public
chartbook data get-docs --pipeline yield_curve --dataframe repo_public
```

## Referring to pipelines

Wherever you pass a pipeline reference — `data.load` (and the other `data.*` helpers) and the `chartbook data` commands — three forms are accepted:

```python
data.load(pipeline="crsp_treasury", ...)                          # bare name — fine when unambiguous
data.load(pipeline="ftsfr/crsp_treasury", ...)                    # canonical scoped name
data.load(pipeline="https://github.com/ftsfr/crsp_treasury", ...) # repo URL, normalized on input
```

A bare name resolves if exactly one catalog entry matches; if several scopes share it, the error lists the candidates so you can qualify. A registry-qualified form (`charthub.example/ftsfr/crsp_treasury`) and a pinned one (`ftsfr/crsp_treasury@a1b2c3d`) are reserved syntax, refused as not yet supported. How IDs are derived — and why URLs are accepted as input but never stored — is covered in {doc}`../reference/configuration`.
