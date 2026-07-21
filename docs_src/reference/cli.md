# CLI Reference

Every command supports `--help`. The site-building commands (`build`, `publish`, `catalog build`) require the Sphinx stack from `pip install "chartbook[all]"` and print install instructions if it's missing; see {doc}`../getting-started` for install options.

| Command | Purpose |
|---------|---------|
| `chartbook init` | Scaffold a new pipeline project |
| `chartbook build` | Generate the documentation site |
| `chartbook browse` | Open the generated site in a browser |
| `chartbook publish` | Stage a pipeline's publishable files into a directory |
| `chartbook catalog init/add/disable/enable/build/browse` | Manage a catalog and its site |
| `chartbook ls [pipelines\|dataframes\|charts]` | List cataloged objects |
| `chartbook data get-path/get-docs/get-docs-path` | Look up a dataframe's file or write-up |
| `chartbook create-data-glimpses` | Summarize every data file your `dodo.py` produces |
| `chartbook config` | Set the default catalog for data loading |
| `chartbook install skill` | Install the bundled Claude Code skill |

## chartbook init

Scaffold a new pipeline from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook), via [cruft](https://cruft.github.io/cruft/) — so `cruft update` can pull template improvements later. Prompts for project name and author. Requires `cruft` (included in `chartbook[all]`).

```console
chartbook init
```

## chartbook build

```console
chartbook build [OPTIONS] [OUTPUT_DIR]
```

Generate the HTML site into `OUTPUT_DIR` (default `./docs`; it cannot be the current working directory itself). Works for both pipelines and catalogs — the project type comes from the manifest. Internals: {doc}`../guide/how-the-build-works`.

| Option | Default | Effect |
|--------|---------|--------|
| `-f, --force-write` | off | Delete and recreate an existing output directory |
| `--project-dir PATH` | `.` | Project to build |
| `--strict / --no-strict` | `--strict` | Strict: a `path`/`docs_path` pointing at a missing file fails the build, naming the file and the manifest entry. `--no-strict` warns and skips the affected pipeline |
| `--size-threshold FLOAT` | `50` | File size (MB) above which parquet glimpses use memory-efficient loading |
| `--strip-mathjax2 / --no-strip-mathjax2` | on | Strip Plotly's MathJax 2 scripts from notebook outputs so they don't clash with Sphinx's MathJax 3 |
| `--keep-build-dirs` | off | Keep the intermediate `_docs/` and `_docs_src/` directories for inspection |
| `--docs-build-dir PATH` | `./_docs` | Intermediate build directory |
| `--temp-docs-src-dir PATH` | `./_docs_src` | Intermediate template directory |
| `--publish-dir PATH` | `./_output/to_be_published/` | Publish staging directory |

```console
chartbook build             # first build
chartbook build -f          # rebuild
chartbook build ./site -f   # custom output directory
```

## chartbook browse

Open the generated site (default `./docs/index.html`) in your default browser.

```console
chartbook browse [OUTPUT_DIR] [--project-dir PATH]
```

## chartbook publish

Copy the pipeline's publishable *source* files — README, `chartbook.toml`, parquet artifacts, write-ups, chart HTML, and notebooks marked `publishable = true` — into a staging directory. This is for sharing the pipeline itself; `build` is what renders the website.

```console
chartbook publish [--publish-dir PATH] [--project-dir PATH] [-v]
```

## chartbook catalog

Manage a catalog — by default the global one at `~/.chartbook/chartbook.toml` (`chartbook config` can point these commands at a different catalog). Concepts and the auto-discovery alternative: {doc}`../guide/catalogs-and-data`.

### catalog init

Create the global catalog with an empty `[pipelines]` section.

```console
chartbook catalog init [--title TITLE]
```

### catalog add

Register pipeline directories. For each path, the scoped key (`scope/name`) is derived from the target's `[project] id` if set, otherwise from its git `origin` remote plus the directory name, falling back to the bare directory name. Paths are stored relative to the catalog; duplicates (by resolved path) are skipped, as are paths already covered by a `pipelines.members` pattern.

```console
chartbook catalog add PATHS... [--catalog PATH] [-y]

chartbook catalog add ../crsp_treasury      # one pipeline
chartbook catalog add ../repos/* -y         # glob, no confirmation prompt
```

### catalog disable / enable

Switch a pipeline off or on without deleting its registration. Explicit entries get `disabled = true`; member-discovered pipelines are tracked on the `pipelines.disabled` ID list. In a catalog with only explicit entries, an unknown ID errors and lists the available pipelines; in a member-based catalog the ID is simply added to (or removed from) the list, and if it matches no pipeline the next build warns with a did-you-mean suggestion.

```console
chartbook catalog disable ftsfr/sovereign_bonds [--catalog PATH]
chartbook catalog enable ftsfr/sovereign_bonds
```

### catalog build

Build the catalog's site into `~/.chartbook/docs/` (or the configured catalog's location). Unlike top-level `build`, the default here is `--no-strict`: one member pipeline with missing files is skipped with a warning instead of sinking the whole site.

```console
chartbook catalog build [-f] [--strict/--no-strict]
```

### catalog browse

Open the built catalog site.

```console
chartbook catalog browse
```

## chartbook ls

List cataloged objects. Without a subcommand, prints a tree of every pipeline with its dataframes and charts; subcommands print flat lists.

```console
chartbook ls [pipelines|dataframes|charts] [--catalog PATH]
```

```console
$ chartbook ls
Catalog: /data/my-catalog/chartbook.toml

[pipeline] acme/yield_curve: Yield Curve Analysis
  [dataframe] acme/yield_curve/repo_public: Repo Public Data
  [chart] acme/yield_curve/yield_spread: Yield Spread Chart
```

## chartbook data

Look up a cataloged dataframe from the shell. `--pipeline` accepts a bare name (when unambiguous), a scoped ID, or a repo URL; ambiguous bare names error with the candidates listed.

```console
chartbook data get-path      --pipeline yield_curve --dataframe repo_public   # parquet path
chartbook data get-docs      --pipeline yield_curve --dataframe repo_public   # write-up content
chartbook data get-docs-path --pipeline yield_curve --dataframe repo_public   # write-up source file
```

All three take `--catalog PATH` to override the configured catalog. The Python equivalents live in `chartbook.data` — see {doc}`../guide/catalogs-and-data`.

## chartbook create-data-glimpses

Parse `dodo.py`, find every CSV/parquet target your tasks produce, and write `data_glimpses.md`: file metadata, column types, null percentages, sample rows, and numeric summary stats.

```console
chartbook create-data-glimpses [--no-samples] [--no-stats] [-o DIR] [--size-threshold MB]
```

## chartbook config

Interactively set the default catalog path (stored as `catalog.path` in `~/.chartbook/settings.toml`). This is what `data.load()`, `chartbook ls`, `chartbook data`, and the `catalog` commands use when no explicit `--catalog`/`catalog_path` is given.

```console
chartbook config
```

## chartbook install skill

Copy the bundled Claude Code skill into `./.claude/skills/chartbook/`, giving Claude context about the CLI, manifest format, and data API when working in your project. `-f` overwrites existing files.

```console
chartbook install skill [-f]
```
