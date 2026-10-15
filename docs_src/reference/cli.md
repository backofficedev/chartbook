# CLI Reference

Every command supports `--help`. Everything the CLI needs ships with `pip install chartbook`; see {doc}`../getting-started`.

| Command | Purpose |
|---------|---------|
| `chartbook init` | Scaffold a new pipeline project |
| `chartbook docs` | Render the documentation site |
| `chartbook build` | Make everything current: run the build script, then render the site |
| `chartbook browse` | Open the generated site in a browser |
| `chartbook check` | Fail CI on missing metadata, broken paths, or expiring licenses |
| `chartbook path` | Print the path the manifest declares for an asset |
| `chartbook publish` | Stage a pipeline's publishable files into a directory |
| `chartbook catalog init/add/disable/enable/build/browse` | Manage a catalog and its site |
| `chartbook ls [pipelines\|dataframes\|charts]` | List cataloged objects |
| `chartbook data get-path/get-docs/get-docs-path` | Look up a dataframe's file or write-up |
| `chartbook create-data-glimpses` | Summarize every dataframe the manifest declares |
| `chartbook snapshot` | Declare this pipeline's build ready for the pipelines that depend on it |
| `chartbook pin` | Freeze what this pipeline depends on, in `chartbook.lock` |
| `chartbook update` | Move pins forward to each dependency's newest snapshot |
| `chartbook run [SCRIPT]` | Run a named script in this pipeline; `build` by default, after pinning what it depends on |
| `chartbook store verify` | Check that nothing in the store has changed since it was stored |
| `chartbook store gc` | Remove old snapshots, and from the store what nothing names |
| `chartbook config` | Set the default catalog for data loading |
| `chartbook install skill` | Install the bundled Claude Code skill (user-level by default) |

## chartbook init

Scaffold a new pipeline from the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template), via [cruft](https://cruft.github.io/cruft/) — so `cruft update` can pull template improvements later. Prompts for project name and author.

The template is the `template/` folder of ChartBook's own repository, so the commands it uses and the commands themselves change together, and a test builds a freshly made project on every change. The new project names its build in `chartbook.toml` (`[scripts] build = "doit"`), so `chartbook build` builds it and renders its site.

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

(chartbook-docs)=
## chartbook docs

```console
chartbook docs [OPTIONS] [OUTPUT_DIR]
```

Render the HTML site into `OUTPUT_DIR` (default `./docs`; it cannot be the current working directory itself). Works for both pipelines and catalogs — the project type comes from the manifest. Internals: {doc}`../guide/how-the-build-works`.

It renders the site from what is already built. It does not build the project's data: {ref}`chartbook run <chartbook-run>` does that, and {ref}`chartbook build <chartbook-build>` does both.

Beside the HTML it writes `index.json`: one record for every pipeline, dataframe, column, chart, notebook, note and model the site contains, each with an ID and a content hash. See {doc}`"The index" <../guide/how-the-build-works>`.

| Option | Default | Effect |
|--------|---------|--------|
| `-f, --force-write` | off | Delete and recreate an existing output directory |
| `--project-dir PATH` | `.` | The project whose site is rendered |
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
chartbook docs             # the first time
chartbook docs -f          # again, over what is there
chartbook docs ./site -f   # custom output directory
chartbook docs -f --incremental   # rebuild only what changed
chartbook docs -f --watch         # ...and keep doing so as you edit
```

**Incremental builds.** A plain `docs` starts from nothing every time, which is what you want in CI. `--incremental` keeps the intermediate Sphinx project (`_docs/`) and uses it the next time:

- a pipeline none of whose files changed is not regenerated at all — its `chartbook.toml`, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares are compared by modification time and size;
- a page whose content comes out the same is left untouched, so Sphinx does not read it again;
- if no page changed, Sphinx is not run.

Each build says what it did:

```console
$ chartbook docs -f --incremental
Incremental build: regenerated 1 of 40 pipeline(s); 10 source file(s) changed, 0 removed; Sphinx re-read 10 page(s).
```

When a page is added or removed, every page is rendered again — from Sphinx's cache, without re-reading anything — so that navigation stays right and no stale page is left behind. Upgrading ChartBook, Sphinx or a theme, or changing a build option, starts over from nothing. The kept `_docs/` directory ignores itself in git.

Two things an incremental build does not promise, both fixed by one plain `chartbook docs`: the "Last updated" date on the front page moves only when that page is rendered again, and a page whose *title* changed keeps its old title in other pages' sidebars until they are next rendered.

**Watch mode.** `--watch` is an incremental build in a loop. It polls the project's files (once a second by default), rebuilds on any change, reports a failed build and carries on. There is no server and nothing to install: open the site with `chartbook browse` and refresh the page.

(chartbook-build)=
## chartbook build

```console
chartbook build [OPTIONS] [OUTPUT_DIR]
```

Make everything current: run the project's `build` script, then render the site. It is `chartbook run` followed by `chartbook docs`, and it takes the arguments of {ref}`chartbook docs <chartbook-docs>`.

```console
$ chartbook build -f
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
Successfully generated documentation in /work/rate_forecast/docs
```

| Command | Builds the data | Renders the site |
|---|---|---|
| `chartbook run` | Yes | No |
| `chartbook docs` | No | Yes |
| `chartbook build` | Yes | Yes |

- **If the script fails, the site is not rendered**, and the command exits with the script's exit code.
- **With no `build` script** in {ref}`[scripts] <scripts>`, there is nothing to run. It says so and renders the site.
- **In a catalog**, the script is run in each of the catalog's pipelines, and then the catalog's site is rendered.

```{warning}
**`chartbook build` used to mean what `chartbook docs` means now.** A build script that says `chartbook build -f`, as the `dodo.py` of a project made by an older `chartbook init` does, must say `chartbook docs -f`.

Until it does: called from inside the build script that `chartbook build` or `chartbook run` is running, `chartbook build` renders the site and prints a warning, so that it does not run the script that called it without end. Called from a build tool you started yourself (plain `doit`), it runs the build script, which is that same tool, a second time.
```

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
- **a dependency that cannot be found** — an entry of {ref}`[dependencies] <dependencies>` whose `path` is not a directory with a pipeline's `chartbook.toml` in it, or a model's `trained_on` naming a dataframe that the other pipeline does not declare;
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

**Dependencies.** For each `path` in `[dependencies]`, `check` looks for a pipeline there and reads its `chartbook.toml`, nothing more. So a pipeline that depends on `../fed_yield_curve` needs that directory checked out wherever `check` runs. A `git` dependency is looked at where `chartbook pin` has fetched it, at the commit `chartbook.lock` names. `check` never uses the network: if the dependency has not been fetched on this machine, it says so in a `warning:` line and does not fail. A `trained_on` that names a pipeline `[dependencies]` does not declare stops the manifest loading, so `check` fails on it.

```console
$ chartbook check
chartbook.toml: [dependencies."ftsfr/fed_yield_curve"] path: directory not found: /work/fed_yield_curve
chartbook.toml: [models.rate_forecaster] trained_on: 'crsp:ratingz' names a dataframe that the pipeline 'ftsfr/crsp' does not declare. Its dataframes are: ratings, returns
```

`check` reads metadata and looks at whether files exist. It never opens a data file, so it says nothing about row counts, nulls or schemas.

**Warnings, not problems.** Two things are said with `warning:` and do not fail the command: a model label whose version is not on this machine (it may be in the store of the machine that made it), and a model that is out of date, trained on inputs that have since moved (`chartbook run` retrains it).

## chartbook path

```console
chartbook path REF [--kind KIND] [--project-dir PATH]
```

Print the path that the enclosing `chartbook.toml` declares for an asset — a dataframe, chart, notebook, note or model — and nothing else, so the output can be captured. The manifest is found by walking up from the current directory (or from `--project-dir`), as git finds a repository.

`REF` names the asset. A dataframe is its key in `[dataframes]`; anything else has its kind in front:

| `REF` | Table in `chartbook.toml` |
|---|---|
| `repo_public` | `[dataframes.repo_public]` |
| `chart/repo_rates` | `[charts.repo_rates]` |
| `notebook/analysis` | `[notebooks.analysis]` |
| `note/methodology` | `[notes.methodology]` |
| `model/rate_forecaster` | `[models.rate_forecaster]` |
| `model/rate_forecaster@7f3a9c2e41b0` | A {ref}`version <model-versions>` of that model, in the store |
| `model/rate_forecaster@champion` | The version that label points at |
| `forecasting:model/rate_forecaster@champion` | The version that label named when `forecasting` was pinned; `chartbook update` moves it |

```console
$ chartbook path repo_public
/work/yield_curve/_data/repo_public.parquet

$ chartbook path chart/repo_rates
/work/yield_curve/_output/repo_rates.html

$ chartbook path repo_rates --kind chart
/work/yield_curve/_output/repo_rates.html
```

`--kind` is the same as writing the kind in front, for when the name comes from a variable. If `REF` already names a kind, `--kind` must agree with it.

The path is absolute and is printed whether or not the file exists, so a build tool can use it for outputs as well as inputs. This is the command-line form of `chartbook.assets.path()` in Python: one rule for where things live, reachable from Make, a shell, R (`system2`) or Stata (`shell`).

```makefile
MERGED := $(shell chartbook path merged_rates)
```

A name the manifest does not declare exits `1` and says which table to add (or, if the name is declared as another kind of asset, how to refer to it); nothing is printed to standard output.

**Another pipeline's asset** has that pipeline's name in front, then a colon:

```console
$ chartbook path fed_yield_curve:treasury_rates
/Users/x/.chartbook/store/objects/sha256/4b/1f…/treasury_rates.parquet

$ chartbook path fed_yield_curve:chart/curve_today
/Users/x/.chartbook/store/objects/sha256/cc/71…/curve_today.html
```

This resolves differently, on purpose. Your own assets resolve *live*, to the file you are working on. Another pipeline's resolve *pinned*: to the copy that `chartbook.lock` names, in the store, and never to that pipeline's working directory. So what you read from it stays the same while it is being worked on, and changes only when you run `chartbook update`.

Three things have to be true, and each has its own message when it is not:

| What is missing | What it says to do |
|---|---|
| The pipeline is not in {ref}`[dependencies] <dependencies>` | Shows the line to add, then `chartbook pin` |
| It is declared and not pinned, or the asset was not built when it was pinned | `chartbook pin` (after building it there) |
| It is pinned and the store does not have the bytes, as after a clone | `chartbook pin`, which puts them back |

The scope may be left off when only one dependency has that name. The path is for reading; never write to it.

Two more parts of the {doc}`reference grammar <../design/references>` do not give a path. `dataframe#series` is the address of one column, for documentation: use the dataframe's path and pick the column yourself. A registry in front is reserved and refused as not yet supported. To find a dataframe through a catalog, from outside any pipeline, use `chartbook data get-path`.

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

(chartbook-snapshot)=
## chartbook snapshot

```console
chartbook snapshot [--project-dir PATH]
```

Declare this pipeline's build ready for the pipelines that depend on it. Every asset the pipeline declares and has built is copied into the store, labelled with the commit the pipeline is at. That is a **snapshot**.

```console
$ chartbook run            # build it
$ chartbook snapshot       # and say it is ready
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
```

Or both in one command, which is the better habit: `chartbook run --snapshot`. See {ref}`below <run-then-snapshot>`.

**Why.** People, and agents, work on different pipelines at the same time. Someone is always half-way through a change. So a pipeline that depends on this one never reads this folder. It reads the last snapshot you made, and your folder can be in any state in between.

Three rules:

1. **Everything in the pipeline's folder must be committed first.** The label says "this is what that commit built", and with uncommitted changes that would not be true. What git ignores, such as built data, does not count. Neither does other work elsewhere in the same repository.
2. **It is made when you ask, not by every build.** Until you make another, pipelines that depend on this one keep getting this one, however much you change here.
3. **Nobody is moved to it.** A pipeline that depends on this one gets a new snapshot with `chartbook update`, and not before.

```console
$ chartbook snapshot
Error: ftsfr/fed_yield_curve has changes that are not committed:
   M fed_yield_curve/src/pull_fred.py
  ?? fed_yield_curve/src/new_script.py
A snapshot is labelled with the commit it was built from, so everything in the pipeline's folder must be committed first.
```

**New data, same code.** A pipeline that pulls data from outside builds other bytes on another day, with no file changed. Build again and snapshot again: the commit is the same and the snapshot is new. If nothing was rebuilt, nothing is made:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Nothing has changed since the snapshot of 2026-10-13 18:22 UTC. No new one was made.
```

An asset that is declared and not built is listed, and the rest is in the snapshot all the same. A pipeline that has built nothing has no snapshot to make.

(run-then-snapshot)=
**Build and snapshot in one command: `chartbook run --snapshot`.** `chartbook snapshot` by itself takes your word that what is on disk was built by the commit you are on. Change a script, commit, forget to rebuild, and the old data gets the new commit's label. `chartbook run --snapshot` does not have that hole:

```console
$ chartbook run --snapshot
ftsfr/fed_yield_curve: build
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
Ran build in 1 pipeline(s).
```

1. It checks that everything is committed **before** it builds, so you are not refused after an hour. `chartbook.lock` does not count: the pin before the build is about to write it, and the snapshot records what it says.
2. It builds.
3. It checks again. A build that changes a committed file leaves a folder the commit does not describe, and gets no snapshot. So does a build that makes a commit.
4. It makes the snapshot, and records in it that the build ran in the same command.

With `--force` as well, it is the weekly refresh in one line: `chartbook run --force --snapshot`. In a catalog, each pipeline is built and declared ready in turn, so a pipeline later in the catalog pins what an earlier one has just declared ready.

**What a snapshot records.**

| It says | With | How complete |
|---|---|---|
| Which data this is | The hash of every file | Complete |
| Which code made it | The commit | Complete |
| What it was built from | `inputs`: what this pipeline was itself pinned to | As complete as its `chartbook.lock` |
| Under what conditions | `built_with`: whether the build ran in the same command, and the ChartBook, Python and platform versions | A note. It explains a difference; it does not make a build repeatable |
| Which model versions were labelled | `labels`: what `[models.x.aliases]` named, by model | As of this snapshot. `store gc` reads the newest snapshot's, so a label given on one machine keeps its version on another |
| What each model scored | `metrics` on the model's record, as its metrics file had them | Kept with the version, so two versions compare after the file is written over |
| What each model was trained on | `trained_on` on the model's record: each input's content hash when the version was first made | The version's, not this snapshot's: a later snapshot of the same bytes copies it forward. What `check` and the page judge staleness against |

**Nothing of your `.env` is ever copied.** It holds secrets, and a store is something to share. A setting that changes your results belongs in a file you commit; then the commit covers it.

Things to know:

- **`chartbook snapshot` does not run the build.** `chartbook run --snapshot` does.
- **It costs disk where the disk has no copy-on-write clones.** A snapshot is its own copy of the files (a Mac, and Linux with btrfs or XFS, clone them for free). {ref}`chartbook store gc <chartbook-store-gc>` clears old ones: those nothing pins, that are not the newest of their pipeline, that no label points into, and that are over 30 days old.
- **It is found by commit.** So it is found by a pipeline that depends on this folder, and by one that depends on the same repository by URL, on this machine. It is not shared between machines.

(chartbook-pin)=
## chartbook pin

```console
chartbook pin [--project-dir PATH]
```

Freeze what this pipeline depends on. Each pipeline in {ref}`[dependencies] <dependencies>` is pinned to a snapshot of it, and the content hash of each of its assets is written to `chartbook.lock`, beside `chartbook.toml`.

```console
$ chartbook pin
ftsfr/fed_yield_curve: 3 pinned, 1 not built
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
  From its snapshot at 4f2a91c, made 2026-10-13 18:22 UTC.
Wrote chartbook.lock.
```

**Commit `chartbook.lock`.** It is source. A change to what the project depends on then shows up in a diff, and someone who clones the project sees which data it was built against. It holds no path from your machine, so pinning twice with nothing changed leaves the file as it was.

**What is asked for, and what was got.** It is the split between `requirements.txt` and `uv.lock`:

| | File | Says |
|---|---|---|
| What you ask for | `chartbook.toml` | Which pipeline, and where: a folder, or a repository at a tag or a branch |
| What you got | `chartbook.lock` | The exact commit, and the hash of every file |

A commit alone would not be enough: the same code gives other data on another day. The hashes are what say which data.

**The other pipeline's folder is not read.** `pin` takes the newest snapshot at the commit that folder is on or, if that commit has none, at the nearest commit before it that has one. So its owner can be several commits past the last build they declared ready, with the folder in any state, and you still get that build.

**A pipeline with no snapshot cannot be pinned**, and the command says what its owner has to do:

```console
$ chartbook pin
ftsfr/fed_yield_curve: cannot be pinned: it has no snapshot at or before 4f2a91c, the commit its folder is on. In ../fed_yield_curve: commit, then run `chartbook snapshot`
```

**A pin never moves by itself.** Run `pin` again after the other pipeline's owner has made a newer snapshot, and nothing changes; it tells you what the newer one would change:

```console
$ chartbook pin
ftsfr/fed_yield_curve: 2 already pinned, 1 changed upstream since it was pinned, 1 not built
  changed upstream: ftsfr/fed_yield_curve:treasury_rates
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
chartbook.lock is unchanged.
1 pinned asset(s) have changed upstream. `chartbook update` moves the pins.
```

A rebuild that its owner has not made a snapshot of is not mentioned, because it is not seen.

**A dependency is pinned to one snapshot, whole.** `pin` does not take one asset from a newer snapshot and leave the rest. What a second `pin` does do is pin a dependency that has no pin yet.

**Its labels are pinned too.** A snapshot records the labels the pipeline's `[models.x.aliases]` gave when it was made, and `pin` writes each as a record of its own, `ftsfr/fed_yield_curve:model/term_premium_ar1@champion`, with the hash of the version it names. `forecasting:model/x@champion` then resolves to those bytes until `chartbook update`, which follows the owner's labels: a label moved shows as `moved`, one taken away as `dropped`, and one the owner has moved since you pinned is reported by `pin` as changed upstream. A label whose version the store cannot supply (no snapshot names it, or its bytes are gone) is pinned without bytes, as a `not built` asset is, with the reason, and `--frozen` reports it. `--from-folder` pins carry the labels they have and gain none; labels come from snapshots. A `git` dependency has no versions and no labels pinned, and a dependency that becomes one lets its labels go (`let go`).

`pin` exits `1` when something could not be pinned: a dependency with no snapshot, a repository that cannot be fetched, or a pin whose bytes are not in the store.

**A `git` dependency** is fetched first, into `~/.chartbook/git/`, and pinned from ChartBook's own clean copy of the commit:

```console
$ chartbook pin
ftsfr/ref_data: fetched https://gitlab.example.org/ftsfr/ref_data at 4f2a91c (v1.2)
ftsfr/ref_data: 2 pinned, 1 not built
  not built: ftsfr/ref_data:daily_prices (./_data/daily_prices.parquet)
  A git dependency has only what its repository commits.
Wrote chartbook.lock.
```

That last line matters. A clone has the other pipeline's code and whatever data it keeps in git. Data that it builds and git-ignores is not in a clone, and `pin` does not run another pipeline's build. So with `pin` alone, a `git` dependency suits reference data, small tables and models that are committed. For a pipeline whose data is built, use {ref}`chartbook run <chartbook-run>`, which builds the dependency once in a clean copy of that commit and pins what that produces.

The lockfile records the commit. `pin` stays at that commit and uses the network only if this machine has lost its copy; `chartbook update` fetches again and asks what the `rev` means now, so a branch moves forward and a tag or a commit does not. If you change `rev` in `chartbook.toml`, `pin` says so and stays where it was, and `update` follows the change. ChartBook runs your own `git`, so your SSH keys and credential helpers work as they do by hand; it never asks for a password, and fails instead.

Once it is pinned, your code reads the pinned copy: `chartbook path fed_yield_curve:treasury_rates`, `data.path("fed_yield_curve:treasury_rates")` and `data.load("fed_yield_curve:treasury_rates")` all go through `chartbook.lock` into the store.

**A pin is a copy that cannot change.** A snapshot's files are copy-on-write clones where the disk has them (a Mac; Linux with btrfs or XFS), which cost nothing, and full copies everywhere else, which cost the files' size. They are never hard links or symlinks to the other pipeline's files, because those get rewritten in place when the other pipeline rebuilds.

### Working on two pipelines at once

There is one way to pin what is in a folder this minute, with no snapshot: `chartbook pin --from-folder` and `chartbook update --from-folder`. It is off by default and left out of `--help` on purpose. It is for when you are changing both pipelines yourself and want to see one change in the other without committing each try.

```console
$ chartbook update --from-folder
ftsfr/fed_yield_curve: 1 moved, 2 already pinned
  ftsfr/fed_yield_curve:treasury_rates
    sha256:4b1f… -> sha256:99ab…
  Taken from its folder as it is now, not from a snapshot.
Wrote chartbook.lock.
```

The folder may be half-built, and the lockfile then names no commit, because nothing says which one those bytes came from. Do not commit a lockfile made this way. The next plain `chartbook update` moves back to a snapshot.

**`--frozen`: say, and write nothing.** For CI, and for anyone whose store is read-only. `chartbook pin --frozen` pins nothing, fetches nothing and writes nothing, not the lockfile, not the store. It reads `[dependencies]`, `chartbook.lock` and the store, and exits `1` unless the pipeline can be built from its lockfile alone: every dependency pinned, from where the manifest says it is; every asset built when it was pinned; every pin in the store.

```console
$ chartbook pin --frozen
ftsfr/fed_yield_curve:model/term_premium_ar1: was declared and not built when it was pinned. Build it there, declare it ready, and `chartbook update`.
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.

$ chartbook pin --frozen
4 pin(s) of 1 dependency, all in the store. Nothing written.
```

Where `pin` records an asset that was not built and goes on, `--frozen` counts it a problem: the build that follows may need it.

## chartbook update

```console
chartbook update [DEPENDENCY...] [--project-dir PATH]
```

Move pins forward, and rewrite `chartbook.lock`. A folder you depend on moves to its newest snapshot. A repository is fetched again, and moves to what its `rev` means now. With no argument every dependency is updated. Name some to update only those, as they are written in `[dependencies]`; the scope may be left off when only one has that name.

```console
$ chartbook update fed_yield_curve
ftsfr/fed_yield_curve: 1 moved, 2 already pinned, 1 not built
  ftsfr/fed_yield_curve:treasury_rates
    sha256:4b1f… -> sha256:99ab…
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
  From its snapshot at 9c1d2e3, made 2026-10-14 09:00 UTC.
Wrote chartbook.lock.
```

**Newer code, or only newer data**, depends on what you asked for in `chartbook.toml`:

| You depend on | `chartbook update` brings |
|---|---|
| A folder | Whatever its owner last declared ready: newer code if they committed any, newer data if they only rebuilt |
| A repository at a tag or a commit | The same code. Newer data only if it was built again (`chartbook run --force`) |
| A repository at a branch | Newer code, when the branch has moved |

If the other pipeline's owner has rebuilt and made no snapshot, there is nothing to move to, and `update` changes nothing.

An asset the newer snapshot no longer declares is dropped from the lockfile. One it declares and did not build is let go: a pin from an older snapshot does not belong beside a newer one's commit. Nothing of this pipeline is rebuilt. The object a pin moved away from stays in the store.

**A `git` dependency that `chartbook run` built** is treated the same way. When an update moves it to a new commit, data that was built at the old commit, and is not built at the new one yet, is let go:

```console
$ chartbook update
ftsfr/ref_data: fetched https://gitlab.example.org/ftsfr/ref_data at 9c1d2e3 (main)
ftsfr/ref_data: 2 already pinned, 1 let go
  let go: ftsfr/ref_data:daily_prices (./_data/daily_prices.parquet)
  What was let go was built at the commit pinned before, and is not built at this one. `chartbook run` builds it and pins it.
Wrote chartbook.lock.
```

Keeping it would leave the lockfile naming one commit beside data built from another, which nobody else could get back. `chartbook run` then builds the new commit and pins what it builds.

(chartbook-run)=
## chartbook run

```console
chartbook run [SCRIPT] [--force] [--snapshot] [--project-dir PATH]
```

Run a script in this pipeline. `SCRIPT` is a name from {ref}`[scripts] <scripts>`. With none given it is `build`, the script that makes a pipeline's data current.

```toml
[scripts]
build = "doit"
```

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

What `chartbook run` does for `build`, in order:

1. **Builds a `git` dependency that is not built yet**, in ChartBook's own clean copy of the commit.
2. **Pins what has no pin yet**, so this pipeline's code can read it: a folder you depend on from its newest {ref}`snapshot <chartbook-snapshot>`, a repository from that clean copy.
3. **Runs this pipeline's `build`**, in its own directory. What the script prints is shown as it runs. If it fails, the command exits with the script's exit code.

In a fresh clone, `chartbook run` is the only command you need: there is no `chartbook pin` to remember first.

**It never builds in a folder this pipeline depends on, and never reads one.** A `path` dependency is a folder somebody works in. They may be half-way through a change. This pipeline reads the snapshot it pinned, not what is in that folder, so building there would disturb its owner and change nothing this pipeline reads. That folder is its owner's to build, and to declare ready with `chartbook snapshot`. If its owner has made no snapshot yet, `chartbook run` stops and says so.

**It never moves a pin.** If the other pipeline's owner has made a newer snapshot, this one is still built against the one it pinned, and you are told:

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 2 already pinned, 1 changed upstream since it was pinned
  changed upstream: ftsfr/fed_yield_curve:treasury_rates
chartbook.lock is unchanged.
1 pinned asset(s) have changed upstream. `chartbook update` moves the pins.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

To build against the newer snapshot, run `chartbook update` and then `chartbook run`. The lockfile changes only when you ask it to, so it only ever changes in a commit you meant to make.

**A `git` dependency is built once.** Nobody works in ChartBook's copy of a commit, so there is nothing to disturb. Its `build` runs in a writable copy of the checkout, under `~/.chartbook/git/work/`, and that is how data the repository builds, and does not commit, comes to be there to pin. That build needs whatever it needs: its tools, its credentials, its network.

**That is running the repository's code, with your environment.** Add a `git` dependency only from a repository you would run code from. `chartbook pin` by itself runs nothing, and pins nothing a repository's manifest declares outside the repository's own files: an absolute path, a `..` or a symlink that reaches out is reported as `outside the repository` and left alone.

```console
$ chartbook run
ftsfr/ref_data: build    in /Users/you/.chartbook/git/work/gitlab.example.org/ftsfr/ref_data/4f2a91c0…
ftsfr/rate_forecast: pinning what it depends on
ftsfr/ref_data: 3 pinned
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 2 pipeline(s).

$ chartbook run
ftsfr/ref_data: built already, at 4f2a91c
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

Nothing builds it a second time by itself. Two things do, both on purpose:

| You want | You run |
|---|---|
| The same code, and fresh data it pulls from outside | `chartbook run --force`, then `chartbook update` |
| Newer code | `chartbook update`, then `chartbook run` |

`run` stays at the commit in `chartbook.lock`. A `git` dependency that commits its data and has no `build` script is not built and not mentioned.

**Build, and declare it ready.** `chartbook run --snapshot` makes a {ref}`snapshot <run-then-snapshot>` after the build, in the same command.

**Another script.** `chartbook run test` runs `test` in this pipeline, and that is all it does. Only `build` pins, and only `build` reaches what the pipeline depends on.

**In a catalog**, the script is run in each of the catalog's pipelines, one that another of them depends on first. A pipeline of the catalog that has no script by that name is passed over, and named.

**What it is not.** It is not a task runner. A script is one string. Scripts do not depend on each other, and there are no retries, no schedule and no history. What is out of date inside a pipeline is for the pipeline's own tool to decide (doit, Make, Snakemake); `chartbook run` runs that tool every time.

A script is run by `bash`, or by `sh` where there is no `bash`, and stops at the first command in it that fails. On Windows it is run by `cmd`.

**`--frozen`.** Pin nothing and write nothing before the build: not the lockfile, not the store, and no `git` dependency is fetched or built. The build runs only if `chartbook pin --frozen` would pass; otherwise nothing runs and the problems are listed. `--frozen` and `--snapshot` are one or the other.

```console
$ chartbook run --frozen
ftsfr/rate_forecast: 4 pin(s) of 1 dependency, all in the store. Nothing written.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

## chartbook index

```console
chartbook index diff BEFORE AFTER [--json] [--exit-code]
```

Say what changed between two builds, from the `index.json` each wrote beside its site. `BEFORE` and `AFTER` are two `index.json` files, or the folders that hold them. Records are matched by kind and ID; the two are compared as published, so a build directory's full index and the site's compare as equals, and `generated_at` is ignored.

```console
$ chartbook index diff docs-main/ docs/
Added 1:
  Chart ftsfr/fed_yield_curve:chart/curve_slope
Changed 3:
  Dataframe ftsfr/fed_yield_curve:treasury_rates: data changed
    content_hash: sha256:2c7ffc38b1c1… -> sha256:9ab40d12e77e…
    row_count: 17043 -> 17044
  Model ftsfr/rate_forecast:model/rate_forecaster: out of date; pins moved
    stale_inputs: [] -> ["fed_yield_curve:treasury_rates"]
  Pipeline ftsfr/fed_yield_curve: assets changed
```

A changed record is described in a reviewer's words: *data changed* (a content or definition hash, a size, a row count, columns or files; a chart or a notebook says *rendered differently*, since each is a rendering of its dataframes), *pins moved* (a dependency's pinned hash, on a pipeline; or a model's pinned inputs), *dependencies changed* (a dependency added, removed or relocated without a pin moving), *N new version(s)* and *N version(s) gone*, *labels moved*, *out of date* or *up to date again*, *scores changed*, *trained on other data*, *assets changed*, *inputs changed*, *moved*, *write-up changed*, *data reaches further* or *less far* (a dated dataframe's last date), *source changed* (a pipeline's code, write-ups or manifest were committed), and *declared differently* with the fields, for what the manifest declares. Under the line: the hashes and row counts, the columns added or gone, the versions new or gone, and the inputs out of date, whole. A different `root` or `schema` between the two files is said first: they may not be the same site, or not written the same way. `--json` prints the same as JSON, each changed field with its value before and after, for a script or a bot that comments on a pull request. `--exit-code` exits `1` when the two differ, as `git diff --exit-code` does, so CI can ask "did this change what the site says?". This is the first reader of the index ({doc}`../design/index-schema`, "What this unblocks").

**Across a commit, a pipeline always says *source changed*:** its `code_changed_at` moves with every commit that touches `src`, `docs_src` or the manifest, so `--exit-code` is `1` for any two builds on either side of one. That is a fact; read it as such.

**Two things that look like changes and are not.** A chart file that Plotly writes without a fixed `div_id` has a fresh id in it on every render, so its hash moves with nothing changed; pass `div_id=` to `write_html` (the examples and the template do; ChartBook's own plotting helpers always do). An executed notebook's HTML carries ids and times from the run, and moves on every render; read *rendered differently* on a notebook as the run, not the data. And a model's `versions`, `trained_with` and `stale_inputs` are read from the store of the machine that built the index, so two indexes from two machines differ in them for no change.

## chartbook store

The store is a folder of files kept under the hash of what is in them. It is where `chartbook pin` keeps its copies of other pipelines' data.

It is at `~/.chartbook/store/`. To put it somewhere else, set `CHARTBOOK_STORE`, or add this to `~/.chartbook/settings.toml`:

```toml
[store]
path = "/a/bigger/disk/chartbook-store"
```

**A store a team shares.** Point every machine's `[store] path` (or `CHARTBOOK_STORE`) at one folder on a shared disk, and a snapshot made on one machine is there for all of them: a colleague, or CI, runs `chartbook pin` and gets the bytes the lockfile names, with no build of their own. A snapshot is always the store's own bytes (a copy-on-write clone or a copy, never a link to a file on someone's machine), so this works across machines. The folder may be read-only for everyone but its owner: pinning a `path` dependency from a snapshot writes nothing in the store but the note for `store gc`, and `pin` says when it could not leave it. Make `roots/` writable for everyone and the notes get through. What does have to write the store says so and stops: a `git` dependency's first pin, `--from-folder` and `chartbook snapshot` all put files in. `--frozen` writes nothing at all, and is what CI should run. `store gc` is the owner's to run, from the machine the snapshots were made on, and without `--forget-missing`: a label another machine gave is known here only through the snapshots that recorded it, and another machine's lockfile is one that cannot be found from here.

### store verify

```console
chartbook store verify
```

Hash every object in the store again, and exit `1` if any is no longer what its name says.

```console
$ chartbook store verify
/Users/x/.chartbook/store: OK (14 object(s))

$ chartbook store verify
sha256:3e744b9d…: its content is no longer what its name says (now sha256:64daa44a…). rates.parquet is a hard link to a file outside the store, which has been rewritten

1 of 14 object(s) in /Users/x/.chartbook/store are not what their names say.
```

**Why an object can change.** The store never moves or copies a file if it can avoid it. It tries four ways to hold one, cheapest first:

| Way | Cost | Can it change after it is stored? |
|-----|------|-----------------------------------|
| reflink (a copy-on-write clone; APFS, btrfs, XFS) | free | No |
| hardlink (a second name for the same file) | free | Yes, if the original is rewritten in place. Not if it is replaced by a new file |
| symlink (a pointer to the file) | free | Yes, whenever the original changes. It breaks if the original is moved |
| copy | the file's size | No |

`chartbook pin` asks for the first or the last of these only, so a pin is always frozen. The two in the middle are there for what is cheap to make again, a build cache, which is not built yet. `verify` is how you find out that an object has changed. It reads every byte, so on a large store it takes a while.

(chartbook-store-gc)=
### store gc

```console
chartbook store gc [--dry-run] [--yes] [--forget-missing] [--keep-days DAYS]
```

Remove from the store what nothing needs any more: old snapshots, and the objects that only they, or a pin that has since moved, named.

The store is shared by all your projects. Two things keep what is in it. Every `chartbook pin` and `chartbook update` notes its lockfile in the store, and `gc` keeps whatever any of those lockfiles names. And every {ref}`snapshot <chartbook-snapshot>` keeps what it names, for as long as the snapshot is kept.

**Which snapshots are kept.** A snapshot is kept if any of these holds:

| Kept because | Example |
|---|---|
| A lockfile pins it | `rate_forecast` is pinned to it |
| It is the newest of its pipeline, or the newest a branch or tag can pin from | The last build of `yield_curve` that was declared ready; the last one on its `release` branch |
| A label points at a model version in it | `champion = "7f3a9c2e41b0"` in that pipeline's `chartbook.toml`, read from its folder or as its newest snapshot recorded |
| It was made in the last 30 days | `--keep-days` changes the number |

Everything else may be removed. So a nightly `chartbook run --snapshot` leaves, after a while, the last month of snapshots, the ones somebody pins, and the ones a label names.

It lists what it would remove and asks before removing anything:

```console
$ chartbook store gc
Kept: 14 object(s), named by 3 lockfile(s)
  /work/crsp_treasury/chartbook.lock
  /work/rate_forecast/chartbook.lock
  /Volumes/usb/old_project/chartbook.lock  (not found; its pins are kept)
Kept: 4 snapshot(s), naming 9 object(s): 1 because a lockfile pins it, 2 because it is the newest of its pipeline, 1 because it was made in the last 30 days
Would remove 6 snapshot(s):
  ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: nothing pins it, it is not the newest, and it is older than 30 days
  …
Would remove 5 object(s), 2.1 GB, that nothing names.
Remove them? [y/N]:
```

| Option | Effect |
|--------|--------|
| `--dry-run` | List each snapshot and object that would be removed, with sizes, and remove nothing |
| `--yes`, `-y` | Do not ask |
| `--forget-missing` | Stop keeping the pins of a lockfile that cannot be found. On a store a team shares, every other machine's lockfile is one |
| `--keep-days DAYS` | Keep an unpinned snapshot that is not the newest of its pipeline for this long. Default 30 |

Five things it is careful about:

- **It looks again when you say yes.** The list is made before the question, and a `chartbook pin` can land while you decide. Whatever became pinned in between is kept, and the command says so.
- **A snapshot's branches are read from the folder it was made from; its labels from there and from the snapshots themselves.** The store notes that folder beside each pipeline's snapshots, and each snapshot records the labels its manifest had when it was made. If the folder is gone (a deleted project, a throwaway checkout, another machine's), the labels the newest snapshot recorded still count, so a label given on one machine keeps its version on another once a snapshot follows it, and a label taken away releases it once a snapshot follows that; nothing is known about branches, and the other rules apply.
- **A lockfile it cannot find still keeps its pins.** The project may be on a drive that is not plugged in. The store remembers what that lockfile named when it was last pinned, and keeps it until you pass `--forget-missing`.
- **An object stored in the last hour is never removed.** A pin puts files in the store before it writes the lockfile that names them. So the run that removes a snapshot's record may leave its objects for the next run.
- **If a lockfile or a snapshot's record cannot be read, nothing is removed.** `gc` stops and says which.

A lockfile is read as it is now. If you check out an older commit and run `gc` without pinning, the pins of the commit you left are not named by anything and can be removed; run `chartbook pin` after switching back.

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
