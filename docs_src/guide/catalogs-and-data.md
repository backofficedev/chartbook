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

`chartbook build` inside the catalog directory renders the combined site: chart and dataframe listings across all member pipelines, per-pipeline pages, and a diagnostics page showing metadata completeness.

## The global catalog

For personal use there's a ready-made location, `~/.chartbook/chartbook.toml`, with its own commands:

```console
chartbook catalog init            # create it
chartbook catalog add ../my-repo  # register a pipeline
chartbook catalog build           # build its site into ~/.chartbook/docs/
chartbook catalog browse          # open that site
```

`catalog add` derives the scoped key from the target's git remote (`ftsfr/crsp_treasury` from `github.com/ftsfr/crsp_treasury`), stores the path relative to the catalog, and skips duplicates. It accepts globs (`chartbook catalog add ../repos/*`) and a `--catalog` option to target a catalog other than the default. `chartbook catalog disable <id>` / `enable <id>` toggle entries without deleting them.

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
- Two members deriving the same ID, or a v1-format member, are hard errors with "To fix" suggestions.
- `disabled` lists IDs to switch off (`chartbook catalog disable` maintains it for member-discovered pipelines); `exclude` removes paths before matching; explicit entries coexist with `members` and win when they point at the same directory — which is also how you rename a pipeline within your catalog.

Auto-discovery is designed for the local catalog, where "everything in this directory is mine" is exactly right. Publishing to a shared catalog should stay an explicit act with explicit entries.

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

With no `[policy]` section, a built-in recommended-field list drives the diagnostics page, warn-only. Policy is enforced only when the catalog builds; a pipeline built standalone is always permissive.

## Loading data

Point ChartBook at a catalog once:

```console
chartbook config
```

This writes the catalog path into `~/.chartbook/settings.toml` (the global catalog works without any configuration). Then every cataloged dataset is loadable by name:

```python
from chartbook import data

lf = data.load(pipeline="yield_curve", dataframe="repo_public")   # polars LazyFrame (default)
df = data.load(pipeline="yield_curve", dataframe="repo_public", format="pandas")
df = data.load(pipeline="yield_curve", dataframe="repo_public", format="polars_eager")

path = data.get_data_path(pipeline="yield_curve", dataframe="repo_public")  # the parquet path
text = data.get_docs(pipeline="yield_curve", dataframe="repo_public")       # the write-up, as a string
where = data.get_docs_path(pipeline="yield_curve", dataframe="repo_public") # the write-up's source file
```

All of these accept `catalog_path="/path/to/catalog"` to bypass the global setting. Hive-partitioned (glob-path) dataframes support only the LazyFrame default — call `.collect()` to materialize.

The same lookups exist on the command line, for shell scripts and quick checks:

```console
chartbook ls                       # tree of every pipeline, dataframe, and chart
chartbook ls dataframes            # flat list
chartbook data get-path --pipeline yield_curve --dataframe repo_public
chartbook data get-docs --pipeline yield_curve --dataframe repo_public
```

## Referring to pipelines

Wherever a pipeline is named — `data.load`, `chartbook ls`, `chartbook data` — three forms are accepted:

```python
data.load(pipeline="crsp_treasury", ...)                          # bare name — fine when unambiguous
data.load(pipeline="ftsfr/crsp_treasury", ...)                    # canonical scoped name
data.load(pipeline="https://github.com/ftsfr/crsp_treasury", ...) # repo URL, normalized on input
```

A bare name resolves if exactly one catalog entry matches; if several scopes share it, the error lists the candidates so you can qualify. How IDs are derived — and why URLs are accepted as input but never stored — is covered in {doc}`../reference/configuration`.
