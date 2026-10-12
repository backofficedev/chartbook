# CLI Reference

Every command supports `--help`. Everything the CLI needs ships with `pip install chartbook`; see {doc}`../getting-started`.

| Command | Purpose |
|---------|---------|
| `chartbook init` | Scaffold a new pipeline project |
| `chartbook build` | Generate the documentation site |
| `chartbook browse` | Open the generated site in a browser |
| `chartbook check` | Fail CI on missing metadata, broken paths, or expiring licenses |
| `chartbook path` | Print the path the manifest declares for an asset |
| `chartbook publish` | Stage a pipeline's publishable files into a directory |
| `chartbook catalog init/add/disable/enable/build/browse` | Manage a catalog and its site |
| `chartbook ls [pipelines\|dataframes\|charts]` | List cataloged objects |
| `chartbook data get-path/get-docs/get-docs-path` | Look up a dataframe's file or write-up |
| `chartbook create-data-glimpses` | Summarize every dataframe the manifest declares |
| `chartbook config` | Set the default catalog for data loading |
| `chartbook install skill` | Install the bundled Claude Code skill (user-level by default) |

## chartbook init

Scaffold a new pipeline from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook), via [cruft](https://cruft.github.io/cruft/) — so `cruft update` can pull template improvements later. Prompts for project name and author.

```console
chartbook init [--git] [--github [--public | --private]]
```

| Option | Effect |
|--------|--------|
| `--git` | Run `git init` in the new project and make one initial commit of everything its `.gitignore` allows. The branch is `main` unless your git configuration sets `init.defaultBranch` |
| `--github` | Do that, then create a GitHub repository named after the project directory with `gh repo create`, add it as `origin`, and push the commit. Implies `--git` |
| `--public` / `--private` | Visibility of the repository `--github` creates. Private unless you say `--public` |

Both are off by default; plain `chartbook init` only renders the template.

`--github` uses your existing [GitHub CLI](https://cli.github.com) login — it never asks for credentials. Whether `git` and `gh` are installed, whether git knows your name and email, and whether `gh` is logged in are all checked **before** the template is rendered, so if something is missing the command stops with the fix (`gh auth login`, say) and nothing has been created. The repository is created under the account `gh` is logged in as.

Once the remote exists, the pipeline's ID is scoped from it: a project `my_pipeline` pushed to `github.com/octo/my_pipeline` is `octo/my_pipeline` from its first build, with nothing to configure. The command prints the ID when it finishes.

If a later step fails — a commit hook rejects the commit, or the repository name is taken — the project is left as far as it got and the error names the command that finishes the job by hand.

## chartbook build

```console
chartbook build [OPTIONS] [OUTPUT_DIR]
```

Generate the HTML site into `OUTPUT_DIR` (default `./docs`; it cannot be the current working directory itself). Works for both pipelines and catalogs — the project type comes from the manifest. Internals: {doc}`../guide/how-the-build-works`.

| Option | Default | Effect |
|--------|---------|--------|
| `-f, --force-write` | off | Delete and recreate an existing output directory |
| `--project-dir PATH` | `.` | Project to build |
| `--strict / --no-strict` | `--strict` | Strict: a `path`/`docs_path` pointing at a missing file fails the build, naming the file and the manifest entry. `--no-strict` warns and skips the affected pipeline of a catalog (a single pipeline still fails: there would be nothing left to build) |
| `--size-threshold FLOAT` | `50` | File size (MB) above which parquet glimpses use memory-efficient loading |
| `--strip-mathjax2 / --no-strip-mathjax2` | on | Strip Plotly's MathJax 2 scripts from notebook outputs so they don't clash with Sphinx's MathJax 3 |
| `--incremental` | off | Keep the intermediate `_docs/` directory between builds and redo only what changed since the last incremental build |
| `--watch` | off | Build incrementally, then rebuild each time a file of the project changes, until Ctrl-C |
| `--watch-interval SECONDS` | `1` | How often `--watch` checks for changes |
| `--keep-build-dirs` | off | Keep the intermediate `_docs/` and `_docs_src/` directories for inspection |
| `--docs-build-dir PATH` | `./_docs` | Intermediate build directory |
| `--temp-docs-src-dir PATH` | `./_docs_src` | Intermediate template directory |
| `--publish-dir PATH` | `./_output/to_be_published/` | Publish staging directory |

```console
chartbook build             # first build
chartbook build -f          # rebuild
chartbook build ./site -f   # custom output directory
chartbook build -f --incremental   # rebuild only what changed
chartbook build -f --watch         # ...and keep doing so as you edit
```

**Incremental builds.** A plain `build` starts from nothing every time, which is what you want in CI. `--incremental` keeps the intermediate Sphinx project (`_docs/`) and uses it the next time:

- a pipeline none of whose files changed is not regenerated at all — its `chartbook.toml`, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares are compared by modification time and size;
- a page whose content comes out the same is left untouched, so Sphinx does not read it again;
- if no page changed, Sphinx is not run.

Each build says what it did:

```console
$ chartbook build -f --incremental
Incremental build: regenerated 1 of 40 pipeline(s); 10 source file(s) changed, 0 removed; Sphinx re-read 10 page(s).
```

When a page is added or removed, every page is rendered again — from Sphinx's cache, without re-reading anything — so that navigation stays right and no stale page is left behind. Upgrading ChartBook, Sphinx or a theme, or changing a build option, starts over from nothing. The kept `_docs/` directory ignores itself in git.

Two things an incremental build does not promise, both fixed by one plain `chartbook build`: the "Last updated" date on the front page moves only when that page is rendered again, and a page whose *title* changed keeps its old title in other pages' sidebars until they are next rendered.

**Watch mode.** `--watch` is an incremental build in a loop. It polls the project's files (once a second by default), rebuilds on any change, reports a failed build and carries on. There is no server and nothing to install: open the site with `chartbook browse` and refresh the page.

## chartbook browse

Open the generated site (default `./docs/index.html`) in your default browser.

```console
chartbook browse [OUTPUT_DIR] [--project-dir PATH]
```

## chartbook check

```console
chartbook check [--project-dir PATH] [--within DAYS] [--policy PATH] [--skip-outputs]
```

The CI gate. Exits `0` on a healthy project and `1` when it finds any of:

- **a missing required field** — a field the policy requires that is absent or empty;
- **a broken path** — a `path`, `docs_path`, `readme`, `logo` or `favicon` pointing at a file that does not exist (or a glob matching nothing);
- **an expiring license** — a dataframe whose `license_expiration` has passed, or falls within `--within` days.

Each finding is one line naming the manifest, the table and the field, so a CI log is enough to fix it:

```console
$ chartbook check
chartbook.toml: [charts.repo_rates] units: required by the default policy, but missing or empty
chartbook.toml: [dataframes.crsp_bonds] license_expiration: license expires on 2026-11-02 (in 22 days, inside the 30-day window)
chartbook.toml: [dataframes.repo_public] path: file not found: /work/repo/_data/repo_public.parquet

3 problem(s) found in 1 manifest(s).
```

| Option | Default | Effect |
|--------|---------|--------|
| `--project-dir PATH` | `.` | Project to check — a pipeline or a catalog |
| `--within DAYS` | `30` | How far ahead a license expiration counts as a failure. `0` fails only on licenses already expired or expiring today |
| `--policy PATH` | — | Take required fields from the `[policy]` table of this file (a catalog's `chartbook.toml`, its directory, or any TOML file with a `[policy]` table) |
| `--skip-outputs` | off | Do not require data files, charts and notebooks to exist |

**Which fields are required.** Run in a catalog, `check` applies the catalog's {ref}`[policy.required] <policy>` to every member pipeline. Run in a standalone pipeline, it applies the built-in recommended-field lists — the same ones that drive the diagnostics page. To hold a pipeline to the policy of the catalog it is published to, or to a list of your own, pass `--policy`; only the `[policy]` table is read, so the catalog's other pipelines need not be checked out.

`policy.mode` is not consulted. It decides what a *build* does about missing metadata; `check` always reports it.

**License dates** are ISO dates (`license_expiration = "2026-12-31"`, or a bare TOML date). An empty value, `"N/A"`, `"None"` and `"Never"` mean the license does not expire. Anything else that is not a date is itself reported, because a gate that cannot read a date cannot vouch for it.

**In CI, on a project that has not been built.** Data files, rendered charts and executed notebooks are what a pipeline *produces*, and they are usually not in git. A CI job that checks out the repository without running the pipeline — which is every job for a pipeline whose data needs a subscription — would see all of them as broken paths. `--skip-outputs` leaves those three out and still checks everything that lives in the repository: required fields, license dates, write-ups, notes, the README, the logo.

```yaml
# .github/workflows/check.yml
- run: pip install chartbook
- run: chartbook check --skip-outputs
```

`check` reads metadata and looks at whether files exist. It never opens a data file, so it says nothing about row counts, nulls or schemas.

## chartbook path

```console
chartbook path REF [--project-dir PATH]
```

Print the path that the enclosing `chartbook.toml` declares for an asset — a dataframe, chart, notebook or note — and nothing else, so the output can be captured. `REF` is the asset's key in the manifest. The manifest is found by walking up from the current directory (or from `--project-dir`), as git finds a repository.

```console
$ chartbook path repo_public
/work/yield_curve/_data/repo_public.parquet

$ chartbook path repo_rates
/work/yield_curve/_output/repo_rates.html
```

The path is absolute and is printed whether or not the file exists, so a build tool can use it for outputs as well as inputs. This is the command-line form of `data.path()` in Python: one rule for where things live, reachable from Make, a shell, R (`system2`) or Stata (`shell`).

```makefile
MERGED := $(shell chartbook path merged_rates)
```

A name the manifest does not declare exits `1` and says which table to add; nothing is printed to standard output. Only names declared in the current pipeline resolve: `other_pipeline:asset`, `asset#series` and `@rev` are reserved syntax and are refused as not yet supported. To locate another pipeline's dataframe through a catalog, use `chartbook data get-path`.

## chartbook publish

Copy the pipeline's publishable *source* files — README, `chartbook.toml`, parquet artifacts, write-ups, chart HTML, and notebooks marked `publishable = true` — into a staging directory. This is for sharing the pipeline itself; `build` is what renders the website.

```console
chartbook publish [--publish-dir PATH] [--project-dir PATH] [-v]
```

```{note}
`publish` copies files into a directory and does nothing else — no network, no registry. Sending a pipeline to a registry is a different act and will get a different verb, **`chartbook push`**. That name is reserved: the command exists only to say it is not yet supported, and `publish` will not grow a second meaning.
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
chartbook catalog build [-f] [--strict/--no-strict] [--clean] [--watch [--watch-interval SECONDS]]
```

A catalog build is **incremental by default**. Its working files are kept beside the catalog, in `_docs/`, and the next build reads them and redoes only the pipelines whose files have changed since — in a large catalog, usually a handful or none. Nothing runs between builds: there is no server or background process, only that directory. See [Incremental builds](#chartbook-build).

`--clean` throws the kept files away and rebuilds everything, which is also what happens automatically after ChartBook, Sphinx or a theme is upgraded. `--watch` rebuilds whenever a member pipeline's files change, until Ctrl-C.

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

Read `chartbook.toml`, take every dataframe it declares, and write `data_glimpses.md`: file metadata, column types, null percentages, sample rows, and numeric summary stats.

```console
chartbook create-data-glimpses [--no-samples] [--no-stats] [-o DIR] [--size-threshold MB] [--project-dir PATH]
```

The manifest is the only source of the list. Nothing about how the project is built is consulted, so a pipeline built with doit, Snakemake, Make or plain scripts gets the same report, and a data file the manifest does not declare is not included. Partitioned dataframes (a glob `path`) are summarized as one dataset. Declared dataframes whose files do not exist yet are skipped with a note. Run in a catalog, the report covers every member pipeline.

## chartbook config

Interactively set the default catalog path (stored as `catalog.path` in `~/.chartbook/settings.toml`). This is what `data.load()`, `chartbook ls`, `chartbook data`, and the `catalog` commands use when no explicit `--catalog`/`catalog_path` is given.

```console
chartbook config
```

## chartbook install skill

Install the bundled Claude Code skill, giving Claude context about the CLI, manifest format, and data API. By default it installs **user-level** — `~/.claude/skills/chartbook/`, or `$CLAUDE_CONFIG_DIR/skills/chartbook/` when that variable is set — so the skill is available in every Claude Code session on your machine. Re-run it after upgrading chartbook; when nothing changed it reports "already up to date" and exits.

```console
chartbook install skill              # user-level (default)
chartbook install skill --project    # ./.claude/skills/chartbook/ — commit it to share with a team
chartbook install skill -f           # overwrite locally modified files without prompting
```

Files from older skill layouts are removed on install so the copy exactly mirrors the bundled skill, and the installing chartbook version is recorded in a `.chartbook-skill-version` stamp alongside the files.
