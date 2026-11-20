# CLI Reference

Every command supports `--help`. Everything the CLI needs ships with `pip install chartbook`; see {doc}`../getting-started`.

## Start with these

Six commands cover most of what people do. The middle four are typed in a pipeline's folder, and `chartbook run` runs the script that `chartbook.toml` names as `build` under `[scripts]`. `chartbook --help` lists them first.

| You type | It does |
|---|---|
| `chartbook init` | Once: starts a project from the template, in a new folder |
| `chartbook run` | Builds this pipeline: pins what it reads, runs its build script, and looks for everything `chartbook.toml` declares |
| `chartbook snapshot` | Puts that build in your store, labelled with its commit, where other pipelines read it and the catalog shows it. Commit first |
| `chartbook pin --update` | Takes the newest snapshot of each pipeline it reads |
| `chartbook catalog open` | Opens the catalog in your browser: every snapshot in your stores |
| `chartbook install agents` | Once per project: teaches your coding agent ChartBook |

## More commands

Every command has a section below. These are the ones reached for most after those:

| Command | Purpose |
|---------|---------|
| `chartbook init` | Scaffold a new pipeline project |
| `chartbook docs build` | Render the documentation site |
| `chartbook docs open` | Open the rendered site in a browser |
| `chartbook run --check` | Fail CI on missing metadata, broken paths, or expiring licenses |
| `chartbook trust` | Say a pipeline's folder is yours to build, so that a build of it runs as your own |
| `chartbook path` | Print the path the manifest declares for an asset |
| `chartbook publish` | Stage a pipeline's publishable files into a directory |
| `chartbook catalog init/disable/enable/build/open` | Manage a catalog and its site; the first command that needs the catalog makes it |
| `chartbook ls [pipelines\|dataframes\|charts] [--json]` | List cataloged objects |
| `chartbook get-docs` | Print a dataframe's page, any other cataloged asset's write-up, or a pipeline's README |
| `chartbook data get-path/get-docs/get-docs-path` | Look up a dataframe's file or write-up |
| `chartbook create-data-glimpses` | Summarize every dataframe the manifest declares |
| `chartbook snapshot` | Declare this pipeline's build ready for the pipelines that depend on it |
| `chartbook restore` | Put this pipeline's own assets back on disk from its snapshots: a costly output, after a clean or a clone |
| `chartbook add PIPELINE` | Declare a dependency by its ID, read from the store, and pin it |
| `chartbook pin` | Freeze what this pipeline depends on, in `chartbook.lock` |
| `chartbook pin --update` | Move pins forward to each dependency's newest snapshot |
| `chartbook lineage` | Show and check every snapshot upstream of this pipeline |
| `chartbook run [SCRIPT]` | Run a named script in this pipeline. `build` by default: pin what it reads, run it, and look for what the manifest declares |
| `chartbook store verify` | Check that nothing in the store has changed since it was stored |
| `chartbook store gc` | Remove old snapshots, and from the store what nothing names |
| `chartbook store export` | Write one pipeline's snapshots into a folder, to send to someone |
| `chartbook store import` | Copy the snapshots a folder holds into this machine's store |
| `chartbook store migrate` | Move a store to this version's layout: one that ChartBook 0.5 laid out, or one made by 0.2 |
| `chartbook config` | Set the default catalog for data loading |
| `chartbook install agents` | Set a project up for coding agents: the Claude Code skill, and a ChartBook section in `AGENTS.md` |
| `chartbook install claude-skill` | Install the bundled Claude Code skill (user-level by default) |

`chartbook --version` prints the installed version; `chartbook <command> --help` prints a command's options.

## chartbook init

Scaffold a new pipeline from the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template) that came with your ChartBook. It asks 19 questions, each with a default that Enter takes: the project's name and its folder name (made from the name), a description, your name and email, the Python version, how to install the dependencies, and which examples and data sources to include. {doc}`../getting-started` says which answers matter. A folder name that is not lowercase letters, digits and `_`, starting with a lowercase letter, stops it with nothing created, and its last line says what to do at the second question next time: press Enter, or type such a name (the name made from the project's name may not be one, as for `2024 Rates`).

**The template comes with the package**, as `chartbook/template` in the wheel (the files git tracks in the repository's `template/`; in a source checkout, those same files of `template/` beside `src/`), so a project is always made with the template of the ChartBook that makes it, and making it needs no network. It is rendered with cookiecutter, and the project's `.cruft.json` is written as [cruft](https://cruft.github.io/cruft/) writes it: the template's repository on GitHub, its `template` folder, and the commit the template is at (recorded in the package when it is built; asked of git in a source checkout). So `cruft update` and `cruft check` in the project follow the template on GitHub from there. The command says when that commit is in no tag and on no branch of a remote that is the template's repository, in the checkout it runs from, so may not be on GitHub, where `cruft update` looks for it. When the commit is not known (the package recorded none, or the checkout's `template/` has changes git has not committed to tracked files), there is no `.cruft.json`, and the command says why and prints the command that makes one once the commit is known, with the answers you gave: `cruft link https://github.com/backofficedev/chartbook --directory template --checkout <commit> --no-input --extra-context '{…}'`. A source checkout that git cannot read, or a copy of one with no `.git`, is not rendered from, since which files git tracks cannot be told; the command says what to do. Everything rendered can be written by its owner, even from a template installed read-only. A folder of the project's name that is there already stops it, with nothing changed. The project's environment files ask for `chartbook>=` the template's version, which is your ChartBook's; `cruft update` moves it to the template's version then.

The template is the `template/` folder of ChartBook's own repository, so the commands it uses and the commands themselves change together, and a test builds a freshly made project on every change. The new project names its build in `chartbook.toml` (`[scripts] build = "doit"`), so `chartbook run` builds it and renders its site, and before that `chartbook docs build` renders its site with the example notebook shown as not built. `doit` there runs every task in `dodo.py` but the tests, which are `doit run_pytest`. When the project is made, the command prints the next steps: `chartbook docs build`, the commands that install its dependencies, then `chartbook run`, `chartbook docs open` and `chartbook run --check`. The new project is recorded as trusted to run, since you made it, and the command says so among the next steps (`Trusted: this folder`); a folder you cloned is not, until {ref}`chartbook trust <chartbook-trust>` says it is. When the record cannot be written (no home folder), the command says so and goes on.

```console
chartbook init [--git] [--github [OPTIONS] [--public | --private]]
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

The documentation site, as a group of two commands: `chartbook docs build` renders it, and `chartbook docs open` opens it. Neither builds the project's data: {ref}`chartbook run <chartbook-run>` does that, and {ref}`chartbook run <chartbook-run>` runs the build script and then generates the site. `chartbook docs` on its own lists the two.

### docs build

```console
chartbook docs build [OPTIONS] [OUTPUT_DIR]
```

Render the HTML site into `OUTPUT_DIR` (default `./docs`; it cannot be the current working directory itself). Works for both pipelines and catalogs — the project type comes from the manifest. Internals: {doc}`../guide/how-the-build-works`.

It renders the site from what is already built. {ref}`chartbook run <chartbook-run>` executes the build script. Its task runner should render documentation as the final task.

**In a folder you have not trusted**, you are asked first when you are at a terminal ({ref}`chartbook trust <chartbook-trust>`, "Asked at a terminal"); elsewhere, and after the answer `r`, the site is rendered as a version from a store is: no query is run (the dataframe's glimpse says why), no template or file from outside the folder is read (a manifest that names one stops the render, naming the entry), and every template runs in Jinja's sandbox. The command says so in a `Warning:` line, and the site is still built. {ref}`chartbook trust <chartbook-trust>` in the folder says the pipeline is yours to build (`--render` to render only); a project `chartbook init` made is trusted already. A catalog renders stored snapshots and needs no trust in working folders.

**Before anything is built.** A lone pipeline that has built none of the data, charts, notebooks and models it declares, as a project just made by `chartbook init` or a fresh clone has not, is rendered all the same, with a warning that lists them:

```text
Warning: rates_study has built nothing it declares yet, so the site shows each as not built:
  - notebook: _output/01_example_notebook_interactive.ipynb
`chartbook run` runs the build script. A script can render documentation as its final step.
With --strict, this is an error.
```

Each of them keeps its record in `index.json`, without a hash, and its provenance panel says "not built". A notebook's page is its title and "Not built yet", with how to build it; a chart's embedded frame and its full-screen link say the same, and so does a dataframe's glimpse, which then has no dates and no download link. A model's page says it only in its provenance panel.

It takes every declared output to be missing. A pipeline that has some of them and not others has been built, so a missing one is an error; a clone of a pipeline that commits some of its outputs to git is such a pipeline. A missing write-up, note or README, which nothing builds, is an error too. And so is a pipeline that has built nothing, when `--strict` is given: after a build that should have made everything, as in CI, run `chartbook docs build --strict`, or `chartbook run`, which runs the build first and makes no exception. An output that is there and cannot be read is not "not built": the render stops and names it.

A version's site, which a catalog builds from the store (see `chartbook snapshot`), holds what that version's build made. Any output it did not make is shown the same way, built in part or not, and says "Not built in this version", with no advice.

Beside the HTML it writes `index.json`: one record for every pipeline, dataframe, column, chart, notebook, note and model the site contains, each with an ID and a content hash. See {doc}`"The index" <../guide/how-the-build-works>`. And `llms.txt`, the site for an assistant: one line per pipeline, dataframe, chart and model with its name linking its page, its ID and, in quotation marks, its owner's description; in a catalog, each pipeline's ten newest versions under it, each linking that version's own `llms.txt`.

| Option | Default | Effect |
|--------|---------|--------|
| `-f, --force-write` | off | Delete and recreate an existing output directory |
| `--project-dir PATH` | `.` | The project whose site is rendered |
| `--strict / --no-strict` | `--strict` | Strict: a `path`/`docs_path` pointing at a missing file fails the build, naming the file and the manifest entry, unless the pipeline has built nothing yet (above) and `--strict` was not given. `--no-strict` warns and skips the affected pipeline of a catalog (a single pipeline still fails: there would be nothing left to build, and its error does not suggest `--no-strict`) |
| `--size-threshold FLOAT` | `50` | File size (MB) above which a dataframe page does not read the file for its date range ("N/A (large file)"); the glimpse reads only the first rows at any size |
| `--strip-mathjax2 / --no-strip-mathjax2` | on | Strip Plotly's MathJax 2 scripts from notebook outputs so they don't clash with Sphinx's MathJax 3 |
| `--incremental` | off | Keep the intermediate `_docs/` directory between builds and redo only what changed since the last incremental build |
| `--watch` | off | Build incrementally, then rebuild each time a file of the project changes, until Ctrl-C |
| `--watch-interval SECONDS` | `1` | How often `--watch` checks for changes |
| `--keep-build-dirs` | off | Keep the intermediate `_docs/` and `_docs_src/` directories for inspection |
| `--docs-build-dir PATH` | `./_docs` | Intermediate build directory |
| `--temp-docs-src-dir PATH` | `./_docs_src` | Intermediate template directory |
| `--publish-dir PATH` | `./_output/to_be_published/` | Publish staging directory |

```console
chartbook docs build             # the first time
chartbook docs build -f          # again, over what is there
chartbook docs build ./site -f   # custom output directory
chartbook docs build -f --incremental   # rebuild only what changed
chartbook docs build -f --watch         # ...and keep doing so as you edit
```

**Incremental builds.** A plain `docs build` starts from nothing every time, which is what you want in CI. `--incremental` keeps the intermediate Sphinx project (`_docs/`) and uses it the next time:

- a pipeline none of whose files changed is not regenerated at all — its `chartbook.toml`, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares are compared by modification time and size;
- a page whose content comes out the same is left untouched, so Sphinx does not read it again;
- if no page changed, Sphinx is not run.

Each build says what it did:

```console
$ chartbook docs build -f --incremental
Incremental build: regenerated 1 of 40 pipeline(s); 10 source file(s) changed, 0 removed; Sphinx re-read 10 page(s).
```

When a page is added or removed, every page is rendered again — from Sphinx's cache, without re-reading anything — so that navigation stays right and no stale page is left behind. Upgrading ChartBook, Sphinx or a theme, or changing a build option, starts over from nothing. The kept `_docs/` directory ignores itself in git.

Two things an incremental build does not promise, both fixed by one plain `chartbook docs build`: the "Last updated" date on the front page moves only when that page is rendered again, and a page whose *title* changed keeps its old title in other pages' sidebars until they are next rendered.

**Watch mode.** `--watch` is an incremental build in a loop. It polls the project's files (once a second by default), rebuilds on any change, reports a failed build and carries on. There is no server and nothing to install: open the site with `chartbook docs open` and refresh the page.

### docs open

```console
chartbook docs open [OUTPUT_DIR] [OPTIONS] [--project-dir PATH]
```

Open the rendered site, `OUTPUT_DIR/index.html` (default `./docs/index.html`), in your default browser. There is no server: the file is opened as it is, and after a rebuild you refresh the page. If there is no site yet, it says to run `chartbook docs build` first.

(chartbook-trust)=
## chartbook trust

```console
chartbook trust [PATH] [--render] [--repository] [--list] [OPTIONS] [--forget]
```

Say that a pipeline's folder is yours to build. Usually you need not: the first build of a folder asks you, at a terminal (below). A build of a folder you have not trusted, where no one is asked (a script, CI), runs as a build of files from a store does: `chartbook docs build` renders its site with no query run (the dataframe's glimpse says why) and no template or file from outside the folder, every template in Jinja's sandbox, with a warning that says how to trust it; `chartbook run` and `chartbook run` refuse to run its build script, which is code, naming the folder and this command. A project `chartbook init` made is trusted as it is made. One you cloned is trusted when you say so, here. `chartbook run --check` is not gated, and its last line says the level when it is not `run`.

**Asked at a terminal.** The first `chartbook run`, `chartbook run` or `chartbook docs build` of a folder you have not trusted asks, when you are at a terminal:

```text
ChartBook has not run the code in this folder before:
  ~/GitRepositories/rates  (acme/rates, github.com/acme/rates)
Its build command runs on this machine:
    doit
  y  it's mine: trust this folder and the folders inside it, and don't ask again
  r  render its site only, without running its code
  n  stop
Trust this folder? [y/r/N]:
```

`y` (or `yes`) records the folder at `run`, as `chartbook trust` there would, so the folders inside it too, and nothing asks again; since a later `chartbook run` then runs its build command without asking, `docs build`'s question shows that command as well. `r` renders the site and runs no build command: a folder not trusted at all renders as a build of files from a store is rendered (a `Warning:` line says so), and one trusted to render renders as it always does. It records nothing, and is offered by `chartbook run` and `docs build`, which have a site to render, not by `run`. Enter, `n`, end of input and Ctrl-C stop at once, and nothing is run; any other answer is asked again. A folder trusted to render only is asked about running. A catalog asks once, `[y/N]`, listing the catalog's own folder and each member folder this command needs and does not have (for `chartbook run`, a member trusted to render only too), each with its build command; `y` records them all. One command asks once. What the question shows of a folder (its path, ID, repository and build command) is shown plainly: blank lines and runs of space folded, a control or format character written as `<U+202E>`, at most ten lines. No one is asked when stdin or stderr is not a terminal, under `CI`, or in a build `chartbook run` or `chartbook run` is running (`CHARTBOOK_BATCH`, `CHARTBOOK_RUN_DIR`): there the build refuses and `docs build` renders without the folder's code, as described here, and `chartbook trust` is the way to say it beforehand. `chartbook trust` also does what a question cannot: a parent folder for everything inside it, a repository for every clone of it, a level of `render` only.

| Option | Effect |
|---|---|
| `PATH` | The folder; this one by default. Its trust covers the folders inside it, so `chartbook trust ~/GitRepositories/ftsfr` trusts every pipeline under it, and the command says so when the folder has no `chartbook.toml` |
| `--render` | Trust it to render only: queries run for glimpses and the index, and the files its manifest names are read wherever they are. `build` and `run` still refuse, saying "trusted to render, not to run" |
| `--repository` | Trust the folder's `origin` repository instead of the folder: every clone of it, wherever it is on this machine. The folder must have an `origin` remote |
| `--list` | What is trusted, and how: each folder and repository with its level and when it was recorded, and whether `CHARTBOOK_TRUST=all` or `CI` trusts more |
| `--forget` | Take the folder (or, with `--repository`, its repository) out of the record. A parent folder's entry that covers it is left as it is |

Two levels: `run`, the default, lets the build script run, and includes `render`. A folder's level is the highest of every entry that covers it: its own, a parent folder's, its repository's.

```console
$ chartbook trust
Trusted to run: /work/rates (ftsfr/rates, https://github.com/ftsfr/rates)
$ chartbook trust --list
/Users/me/.chartbook/trust.toml:
Pipelines (each covers the folders inside it):
  run     /work/rates  (ftsfr/rates, https://github.com/ftsfr/rates)  since 2026-10-18T22:14:05Z
```

**The record** is `~/.chartbook/trust.toml`, this user's ({doc}`configuration`): `[[pipeline]]` entries with a resolved `path`, a `level`, and the pipeline's `id` and `repository` as notes for you (nothing goes by them: an entry is matched by its path, so a stranger's manifest claiming your ID gains nothing), and `[[repository]]` entries with a `url`, matched by the folder's `origin` remote, which you set when you cloned. Trust a repository only for clones you made yourself: a folder that arrived with a `.git/` inside may name any repository in its `.git/config`, and is trusted by its path. The file is written whole or not at all. One that cannot be read stops the command, naming the file; an entry of another shape (a relative `path` is one) is passed over with a warning naming it, and a `pipeline` or `repository` key that is a table rather than an array stops a write, which would otherwise drop it.

**Recorded for you.** A project `chartbook init` makes is trusted to run. Catalogs and their stores need no working-folder trust: the catalog renders snapshots in the version renderer's sandbox.

**Without a record.** Under `CI` (the environment variable, set to anything) the checkout is trusted to run: the top of the git repository the working directory is in, or the working directory itself when it is in none; a runner builds its own checkout. `CHARTBOOK_TRUST=all` trusts every folder to run, for a container that is nothing but your own code (the test suite runs so); it is the one value the variable takes, and another is said once and ignored. A build of files from a store (`CHARTBOOK_UNTRUSTED_SOURCE=1`) is never trusted, whatever the record says. A `git` dependency is built in ChartBook's own copy of its commit: naming it in `[dependencies]` is the trust for that, and the pipeline that names it must itself be trusted to run.

`chartbook docs build`, `chartbook run`, `chartbook create-data-glimpses` and `chartbook publish` use the pipeline trust gate; `chartbook run --check` reports the trust level without requiring trust. `chartbook catalog build` renders stored snapshots without member trust.

No prompt: a command that needs trust refuses and prints this command, so a script behaves as a person does. The reasoning is {design}`trust`.

## chartbook path

```console
chartbook path REF [--kind KIND] [--project-dir PATH] [OPTIONS] [--files]
```

Print the path that the enclosing `chartbook.toml` declares for an asset — a dataframe, chart, notebook, note, model or files asset — and nothing else, so the output can be captured. The manifest is found by walking up from the current directory (or from `--project-dir`), as git finds a repository.

`REF` names the asset. A dataframe is its key in `[dataframes]`; anything else has its kind in front:

| `REF` | Table in `chartbook.toml` |
|---|---|
| `repo_public` | `[dataframes.repo_public]` |
| `chart/repo_rates` | `[charts.repo_rates]` |
| `notebook/analysis` | `[notebooks.analysis]` |
| `note/methodology` | `[notes.methodology]` |
| `model/rate_forecaster` | `[models.rate_forecaster]` |
| `file/filings` | `[files.filings]` |
| `model/rate_forecaster@7f3a9c2e41b0` | A {ref}`version <model-versions>` of that model, in the store |
| `model/rate_forecaster@champion` | The version that label points at |
| `forecasting:model/rate_forecaster@champion` | The version that label named when `forecasting` was pinned; `chartbook pin --update` moves it |

```console
$ chartbook path repo_public
/work/yield_curve/_data/repo_public.parquet

$ chartbook path chart/repo_rates
/work/yield_curve/_output/repo_rates.html

$ chartbook path repo_rates --kind chart
/work/yield_curve/_output/repo_rates.html
```

`--kind` is the same as writing the kind in front, for when the name comes from a variable. If `REF` already names a kind, `--kind` must agree with it.

`--files` prints the asset's files instead, one per line, sorted by their path inside it: the file itself, every file under a folder, or every file a glob matches, the files its hash is made of. It is `chartbook.assets.files()` for a shell, and works for any asset with files, a dataframe of many parts included. An asset with no files there yet exits `1`.

```console
$ chartbook path file/filings --files
/work/filings/_data/filings/year=2024/10-K.htm
/work/filings/_data/filings/year=2025/10-K.htm
```

Another pipeline's asset, `rates:treasury`, is read as `data.load` reads it: its pinned copy in the store, and before anything is pinned, by the rules in {doc}`../guide/depending-on-pipelines`. A dependency declared and not pinned is pinned then, which writes `chartbook.lock` and says so on stderr.

The path is absolute and is printed whether or not the file exists, so a build tool can use it for outputs as well as inputs. This is the command-line form of `chartbook.assets.path()` in Python: one rule for where things live, reachable from Make, a shell, R (`system2`) or Stata (`shell`).

```makefile
MERGED := $(shell chartbook path merged_rates)
```

A name the manifest does not declare exits `1` and says which table to add (or, if the name is declared as another kind of asset, how to refer to it); nothing is printed to standard output.

**Another pipeline's asset** has that pipeline's name in front, then a colon:

```console
$ chartbook path fed_yield_curve:treasury_rates
/Users/x/.chartbook/store/snapshots/fed_yield_curve/2026-10-26T182205Z_9b1e22d7a0c4/_data/treasury_rates.parquet

$ chartbook path fed_yield_curve:chart/curve_today
/Users/x/.chartbook/store/snapshots/fed_yield_curve/2026-10-26T182205Z_9b1e22d7a0c4/_output/curve_today.html
```

The path is into the store, in the folder of the snapshot that keeps the file, under its own
name. An asset of several files, a folder or a glob, has no one path: a store need not keep its
files in one folder (a bucket, and a store that ChartBook 0.5 laid out, keep each file once, so a
snapshot's files may sit in other snapshots' folders). Asking exits `1` and says
so, whatever the folders happen to hold today; `--files` prints the files, each where the store
keeps it, and `data.load` reads them. Nothing is gathered into this machine's cache.

```console
$ chartbook path news_headlines:articles
Error: 'news_headlines:articles' is a dataset of 14 files, kept in 3 places in the store, so there is no one folder. Read it with data.load('news_headlines:articles'), or hand data.files('news_headlines:articles') to your own reader. `chartbook path news_headlines:articles --files` prints them, one per line.
```

This resolves differently, on purpose. Your own assets resolve *live*, to the file you are working on. Another pipeline's resolve *pinned*: to the copy that `chartbook.lock` names, in the store, not to that pipeline's working directory (before a pin, by the rules in {doc}`../guide/depending-on-pipelines`). So what you read from it stays the same while it is being worked on, and changes only when you run `chartbook pin --update`.

Three things have to be true, and each has its own message when it is not:

| What is missing | What it says to do |
|---|---|
| The pipeline is not in {ref}`[dependencies] <dependencies>` | Shows the line to add, then `chartbook pin` |
| It is declared and not pinned, or the asset was not built when it was pinned | `chartbook pin` (after building it there) |
| It is pinned and the store does not have the bytes, as after a clone | Point `CHARTBOOK_STORE` at the store that has them. Otherwise, for a `git` dependency, `chartbook pin` puts them back; for a `path` dependency, its owner runs `chartbook snapshot` and you run `chartbook pin --update` |

The scope may be left off when only one dependency has that name. The path is for reading; never write to it.

Two more parts of the {design}`reference grammar <references>` do not give a path. `dataframe#series` is the address of one column, for documentation: use the dataframe's path and pick the column yourself. A registry in front is reserved and refused as not yet supported. To find a dataframe through a catalog, from outside any pipeline, use `chartbook data get-path`.

## chartbook publish

Copy the pipeline's publishable *source* files — README, `chartbook.toml`, parquet artifacts, write-ups, chart HTML, and notebooks marked `publishable = true` — into a staging directory. This is for sharing the pipeline itself; `build` is what renders the website.

```console
chartbook publish [--publish-dir PATH] [--project-dir PATH] [OPTIONS] [-v]
```

It copies the files the manifest names, so in a folder you have not trusted it reads as a build of files from a store does: a manifest that names a file outside the folder stops it, naming the entry, and the command says how to trust the folder ({ref}`chartbook trust <chartbook-trust>`).

```{note}
`publish` copies files into a directory and does nothing else — no network, no registry. Sending a pipeline to a registry is a different act and will get a different verb, **`chartbook push`**. That name is reserved: the command exists only to say it is not yet supported, and `publish` will not grow a second meaning.
```

(chartbook-catalog)=
## chartbook catalog

Manage a catalog — by default the machine's, `~/.chartbook/catalog.toml` (`chartbook config` can point these commands at a different catalog). Concepts: {doc}`../guide/catalogs-and-data`.

**By default a store and a catalog are one unit.** The first command that needs the catalog and finds none (`chartbook ls`, `get-docs`, `data`, `catalog build`, `catalog open`, and `chartbook snapshot` or `run --snapshot` once the snapshot is made) makes `~/.chartbook/catalog.toml` over the store this machine uses, and nothing else. At a terminal it asks first, and Enter says yes:

```console
$ chartbook ls
No catalog yet.
Create one over your store at /Users/x/.chartbook/store? [Y/n]:
Made /Users/x/.chartbook/catalog.toml.
```

`n` stops a command that needs one, with the commands that make or name one; after a snapshot it only leaves the catalog unmade. A script, a pipe or CI is not asked: the catalog is made and one line on stderr says so (`Made …: a catalog over your store at …`), since it names the machine's store and nothing is lost by making it. So does `data.load(pipeline=…, dataframe=…)` in Python. A catalog the settings name (`chartbook config`) is used as it is, and an old `~/.chartbook/chartbook.toml` stops the command and names `chartbook catalog migrate`.

### catalog init

Make the machine's catalog ahead of time, or with a title. Asks nothing: the title is "My Catalog" unless `--title` says otherwise. Other stores join it with `chartbook store add`.

```console
chartbook catalog init [OPTIONS] [--title TITLE]
```

### catalog migrate

```console
chartbook catalog migrate [OPTIONS]
```

Rename a folder catalog to `catalog.toml`, preserving `[project]`, `[policy]`, and disabled notes. An exact `.pre-0.4.bak` backup is kept. Store definitions replace working-folder entries. Pipelines without snapshots are listed with the command to publish them. `--catalog PATH` selects the old catalog.

### catalog disable / enable

Switch a pipeline off or on without deleting its registration. Explicit entries get `disabled = true`; member-discovered pipelines are tracked on the `pipelines.disabled` ID list. In a catalog with only explicit entries, an unknown ID errors and lists the available pipelines; in a member-based catalog the ID is simply added to (or removed from) the list, and if it matches no pipeline the next build warns with a did-you-mean suggestion.

```console
chartbook catalog disable ftsfr/sovereign_bonds [OPTIONS] [--catalog PATH]
chartbook catalog enable ftsfr/sovereign_bonds [OPTIONS] [--catalog PATH]
```

### catalog build

Render the catalog's site into `~/.chartbook/docs/` (or the configured catalog's location). Unlike `chartbook docs build`, the default here is `--no-strict`: one member pipeline with missing files is skipped with a warning instead of sinking the whole site.

```console
chartbook catalog build [-f] [--strict/--no-strict] [--clean] [--watch [OPTIONS] [--watch-interval SECONDS]] [--gc] [--no-gc-reminder]
```

A catalog build is **incremental by default**. Its working files are kept beside the catalog, in `_docs/`, and the next build reads them and redoes only the pipelines whose files have changed since — in a large catalog, usually a handful or none. Nothing runs between builds: there is no server or background process, only that directory. See [Incremental builds](#chartbook-docs).

`--clean` throws the kept files away and rebuilds everything, which is also what happens automatically after ChartBook, Sphinx or a theme is upgraded. `--watch` rebuilds whenever a member pipeline's files change, until Ctrl-C.

The catalog reads snapshots from its stores. It runs no member code and needs no member trust. It lays out no data: a version's site is built from its snapshot's documents, charts, notebooks, notes and index, which recorded each dataframe's columns, rows, dates and first rows when the snapshot was made ({design}`plan-data-reads`).

After the build, one line on stderr says what `chartbook store gc` would clear, if anything: snapshots older than seven days that are neither pinned nor the newest of their pipeline, and how much their removal would free. Nothing is removed unless you ask: `--gc` runs gc then, as `chartbook store gc --yes` would, and `--no-gc-reminder` silences the line. With `--gc`, something gc could not remove (another user's, in a store users share) exits `1` after the site was built, as `store gc` itself does.

```console
$ chartbook catalog build
...
Catalog site generated: /Users/x/.chartbook/docs/index.html
`chartbook store gc` would clear 6 snapshot(s), freeing 2.1 GB: older than 7 days, and neither pinned nor the newest of their pipeline. Nothing is removed unless you ask (`--no-gc-reminder` silences this line).
```

`chartbook run --snapshot` says the same after its snapshot, and takes `--no-gc-reminder` too. With several stores in the catalog, each that gc could clear is named, with the `--store NAME` that gc takes there.

(chartbook-catalog-open)=
### catalog open

Open the catalog's site in your default browser.

```console
chartbook catalog open
```

**It asks before it opens a site that is behind.** A snapshot is made by one command and the site built by another: the site is built when it is looked at. So `catalog open` works out, when you type it, whether the site shows what your stores have now, and asks:

```console
$ chartbook catalog open
The catalog's site is behind your stores: 3 snapshots are not in it yet. Build it before opening? [Y/n]: 
...
Catalog site generated: /Users/x/.chartbook/docs/index.html
Opening /Users/x/.chartbook/docs/index.html
```

Enter builds it, as `chartbook catalog build` does, and opens it; `n` opens it as it is. A site that was never built is asked for the same way (`The catalog's site has not been built yet. Build it before opening? [Y/n]`), and `n` there opens nothing.

- **Behind is worked out, not remembered.** The snapshots the site was built from (the `index.json` beside it) are compared with those in the catalog's stores now. A mark left by a run would miss a snapshot that came through a synced folder from another machine, and one that was cleared there.
- **It counts both ways:** snapshots the stores have that the site does not show, and snapshots the site shows that the catalog no longer lists, because they were cleared from its stores or their pipeline was disabled in `catalog.toml` (`1 snapshot is not in it yet, and 2 it shows are no longer in the catalog`).
- **Where nothing can ask** (a script, a pipe, CI), it opens the site as it is and says how far behind it is, on stderr: `… Opening it as it is: `chartbook catalog build` brings it up to date.` With no site at all it exits `1` and names `chartbook catalog build`.
- **What is only away is not called gone.** Where the site shows snapshots that are not in the stores now, and a store is not there (a drive that is away), a snapshot's record cannot be read (a sync part-way), or two repositories claim one ID (which stops the build until `catalog.toml` says which), nothing is asked: a build then would take those pages out of the site. It says `Whether the catalog's site is behind your stores cannot be told now: the store at … is not there now. Opening it as it is.`
- **A snapshot that was not all in the store when the site was built** has a page that says so, and is not counted again: `chartbook catalog build` makes its pages once it has arrived.

The catalog shows snapshots. Work that is not committed yet is on the pipeline's own site, which its build writes: {ref}`chartbook docs open <chartbook-docs>`.

## chartbook ls

List cataloged objects. Without a subcommand, prints a tree of every pipeline with its dataframes and charts; `chartbook ls pipelines`, `chartbook ls dataframes` and `chartbook ls charts` print flat lists. `--catalog PATH` is an option of `ls` itself, and goes before the subcommand.

```console
chartbook ls [--catalog PATH] [--json]               # the tree
chartbook ls [--catalog PATH] pipelines [--json]     # flat lists
chartbook ls [--catalog PATH] dataframes [--json]
chartbook ls [--catalog PATH] charts [--json]
```

```console
$ chartbook ls
Catalog: /data/my-catalog/chartbook.toml

[pipeline] acme/yield_curve: Yield Curve Analysis
  [dataframe] acme/yield_curve:repo_public: Repo Public Data
  [chart] acme/yield_curve:chart/yield_spread: Yield Spread Chart
```

Each asset is written as its reference, `pipeline:name`. A pipeline the catalog shows from the store alone is listed as store only, with the dataframes and charts its newest snapshot lists.

`--json` prints the listing as JSON, for a script or an agent: a list with one record per pipeline and per asset, of every kind (models, files assets, notes and notebooks too, which the tree leaves out), none cut off. Each record has `kind` (`pipeline`, `dataframe`, `chart`, `model`, `file`, `note`, `notebook`), `id`, `name` and `description`, and an asset's has its `pipeline`. The `id` is what {ref}`chartbook get-docs <chartbook-get-docs>` and `data.load` take. Each listing takes `--json` as well, and `chartbook ls --json charts` is `chartbook ls charts --json`.

```console
$ chartbook ls --json
[
  {"kind": "pipeline", "id": "acme/yield_curve", "name": "Yield Curve Analysis", "description": "..."},
  {"kind": "dataframe", "id": "acme/yield_curve:repo_public", "pipeline": "acme/yield_curve", "name": "Repo Public Data", "description": "..."},
  ...
]
```

### ls stores

```console
chartbook ls stores
```

List catalog stores in order, including read-only and unreachable stores. The group's `--catalog PATH` selects another catalog. With `--json`, each is `name`, `url`, `read_only` and `reachable`.

### ls versions

```console
chartbook ls versions
```

List every snapshot across the catalog's stores, newest first, showing the store name. Duplicate copies are listed once. With `--json`, each is `pipeline`, `commit`, `made_at` and `store`.

(chartbook-get-docs)=
## chartbook get-docs

Print what a person reads on a cataloged asset's page, in Markdown, for a script or an agent. Name the asset by its ID, as `chartbook ls` prints it, or with keywords:

```console
chartbook get-docs yield_curve                                  # the pipeline's README
chartbook get-docs yield_curve:repo_public                      # a dataframe's page
chartbook get-docs yield_curve:chart/repo_rates                 # a chart's write-up
chartbook get-docs --pipeline yield_curve --chart repo_rates    # the same, with keywords
chartbook get-docs --pipeline rate_forecast --model forecaster  # a model's
chartbook get-docs yield_curve:repo_public --path               # where the write-up's file is
```

The keywords are `--pipeline` and one of `--dataframe`, `--chart`, `--model`, `--file` (a files asset) or `--note`; with no asset, the pipeline's README. A bare name is a pipeline, since this reads the catalog. In an ID the last colon divides the pipeline from the asset, so a pipeline may be named by its scoped ID or its repository URL: `chartbook get-docs https://github.com/acme/yield_curve:chart/repo_rates`; a URL alone is the README. A dataframe's page is what its snapshot's index recorded of it: its name, description and ID; its sources, providers and license; how it is pulled; its rows and the span of its dates; the snapshot it is from; then its write-up and a table of its columns and their types. Pipe it through `head` for the top alone. For any other asset it is the write-up: the asset's `docs_path` or inline `docs`, and a note's own text; a notebook has no write-up apart from itself, and is refused, saying so. `--path` prints where the file is instead of its text: the `docs_path`, the `chartbook.toml` that holds inline `docs`, or the note. Each is read from the pipeline's newest snapshot in the catalog's stores. `--catalog PATH` overrides the configured catalog. In Python, `assets.get_docs_page(pipeline, "repo_public")` is the page, `assets.get_docs(pipeline, "chart/repo_rates")` the write-up alone, and `assets.get_docs_path(...)` where it is.

## chartbook data

Look up a cataloged dataframe from the shell. `--pipeline` accepts a bare name (when unambiguous), a scoped ID, or a repo URL; ambiguous bare names error with the candidates listed.

```console
chartbook data get-path      --pipeline yield_curve --dataframe repo_public   # parquet path
chartbook data get-docs      --pipeline yield_curve --dataframe repo_public   # its page
chartbook data get-docs-path --pipeline yield_curve --dataframe repo_public   # write-up source file
```

All three take `--catalog PATH` to override the configured catalog. {ref}`chartbook get-docs <chartbook-get-docs>` reads any asset's write-up, and a pipeline's README. The Python equivalents live in `chartbook.data` — see {doc}`../guide/catalogs-and-data`.

## chartbook create-data-glimpses

Read `chartbook.toml`, take every dataframe it declares, and write `data_glimpses.md`: file metadata, column types, null percentages, sample rows, and numeric summary stats.

```console
chartbook create-data-glimpses [--no-samples] [--no-stats] [-o DIR] [--size-threshold MB] [OPTIONS] [--project-dir PATH]
```

The manifest is the only source of the list. Nothing about how the project is built is consulted, so a pipeline built with doit, Snakemake, Make or plain scripts gets the same report, and a data file the manifest does not declare is not included. Partitioned dataframes (a glob `path`) are summarized as one dataset. Declared dataframes whose files do not exist yet are skipped with a note. Run in a catalog, the report covers every member pipeline.

`-o DIR` (`--output-dir`) is the directory the report is written in, as `DIR/data_glimpses.md`; it is made if it does not exist. A path ending in `.md` is taken as the report's own path; anything else already there that is not a directory, a file or a broken link, is refused, as it is neither. Without `-o`, the report is `data_glimpses.md` in the current directory.

The report reads the files the manifest names, so in a folder you have not trusted it reads as a build of files from a store does: a manifest that names a file outside the folder stops it, naming the entry, no query is run, and the command says how to trust the folder ({ref}`chartbook trust <chartbook-trust>`).

(chartbook-snapshot)=
## chartbook snapshot

```console
chartbook snapshot [OPTIONS] [--project-dir PATH] [--deep] [--store NAME] [--no-gc-reminder]
```

Declare this pipeline's build ready for the pipelines that depend on it. Every asset the pipeline declares and has built is copied into the store, labelled with the commit the pipeline is at; a dataframe that is a table or a query in a DuckDB file is written out as a parquet file there, so that it can be pinned and read like any other. That is a **snapshot**.

**You type this when a build is one that others should read.** {ref}`chartbook run <run-makes-no-snapshot>` builds and makes no snapshot, and its last lines name this command. `chartbook snapshot` does not run the build: it takes what is on disk, however it was built (`chartbook run`, `doit` by hand, a notebook, a job that ran overnight).

```console
$ chartbook run            # build it
…
ftsfr/fed_yield_curve: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
$ git add -A && git commit -m "Yields through October"
$ chartbook snapshot       # and say it is ready
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
```

Or both in one command, where the work is committed before the build: `chartbook run --snapshot`. See {ref}`below <run-then-snapshot>`.

**A snapshot carries its lineage.** It records what the pipeline was pinned to, each dependency's commit and a hash over everything pinned from it, so it is made only when those pins account for every dependency: the check `chartbook pin --check` makes (every dependency in the lockfile, pinned from where the manifest says, its bytes in the store); no `path` dependency, or one named by its ID, whose pin names no snapshot (as in a lockfile changed by hand); and for each dependency pinned from a snapshot, that snapshot in the store, holding each asset pinned from it at its hash, and each label pinned naming a version some snapshot of it holds, so a lockfile changed by hand is caught (a `git` dependency, pinned from its clone, is checked only to have its bytes in the store). Nothing that cannot have been read stops it: an asset the other pipeline had not built when it was pinned, or a dependency of which nothing is pinned (it declares nothing, or has no snapshot yet). Otherwise nothing is made, and each gap is listed with what to run. `chartbook run --snapshot` makes the same check after it pins and before it builds, so a gap is found before an hour of building.

Two things it does not see. A snapshot pinned from that was made before this check, or by an older ChartBook, may have gaps of its own: the check is of this pipeline's pins. `--deep` also walks every snapshot upstream ({ref}`chartbook lineage <chartbook-lineage>`) and refuses if any has a gap; it needs every snapshot upstream in the store, so it is for when you want that audit, not a requirement. The record says which was done (`built_with.lineage`: `pins` or `deep`). And a read that does not go through the lockfile (a load through a catalog, a model version named by its hash) is not in them.


```console
$ chartbook snapshot
Error: acme/forecast cannot have a snapshot: its pins do not account for every dependency, and a snapshot carries its lineage.
  rates: is in [dependencies] and not in the lockfile. Run `chartbook pin`.
```

After a snapshot, one line on stderr says what `chartbook store gc` would clear, if anything, as {ref}`catalog build <chartbook-catalog>` says it; `--no-gc-reminder` silences it. Nothing is removed unless you ask. The first snapshot of a pipeline leaves a `README.txt` in the pipeline's folder of the store, for whoever finds the folder: each folder there is a complete snapshot, and one is removed with `chartbook store gc` and never by hand ({ref}`store ls <chartbook-store>`).

**Why.** People, and agents, work on different pipelines at the same time. Someone is always half-way through a change. So a pipeline that depends on this one never reads this folder. It reads the last snapshot you made, and your folder can be in any state in between.

Three rules:

1. **Everything in the pipeline's folder must be committed first.** The label says "this is what that commit built", and with uncommitted changes that would not be true. What git ignores, such as built data, does not count. Neither does other work elsewhere in the same repository.
2. **It is made when you ask, not by every build.** Until you make another, pipelines that depend on this one keep getting this one, however much you change and build here.
3. **Nobody is moved to it.** A pipeline that depends on this one keeps the snapshot it pinned, however many you make after it. It gets a newer one with `chartbook pin --update`, and not before.

```console
$ chartbook snapshot
Error: ftsfr/fed_yield_curve has changes that are not committed:
   M fed_yield_curve/src/pull_fred.py
  ?? fed_yield_curve/src/new_script.py
A snapshot is labelled with the commit it was built from, so everything in the pipeline's folder must be committed first.
```

**The same bytes make no new snapshot.** `chartbook snapshot` hashes what the build made and compares it with the snapshots of this pipeline at this commit: the same bytes and the same pins mean it has nothing to do, and it says so. A pipeline that pulls data from outside builds other bytes on another day, with no file changed; build again and snapshot again, and the commit is the same and the snapshot is new, named by its time, and complete: its folder holds every file, those that did not change too (a bucket, which keeps each file once, holds only the ones that changed). If nothing was rebuilt, and `chartbook.lock` pins what it pinned, nothing is made:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
No new snapshot: the same bytes and the same pins as the one made 2026-10-13 18:22 UTC.
```

A snapshot records what the pipeline was pinned to, so after `chartbook pin --update` it is made again with the same bytes: a pipeline that pins this one then reads where they came from. And it records each dataframe's rows, which a snapshot made by a ChartBook from before 0.6.0 does not: the same bytes as such a one make a new snapshot, once, and the command says why: `The same files as the snapshot made 2026-11-04 05:46 UTC, which says nothing of the rows of 1 dataframe: this one records them, so that a rebuild can meet a pin of it.` (A table whose rows cannot be hashed is not counted there: `rows not hashed: …` says why it has none.) Two checkouts of one pipeline that share a store and pin differently (a lockfile git ignores) each make their own when they snapshot, and the newest is the one a pin takes.

An asset that is declared and not built is listed, and the rest is in the snapshot all the same. A pipeline that has built nothing has no snapshot to make, and the refusal names each thing that is not there (`not built: ftsfr/fed_yield_curve:treasury_rates (./_data/treasury_rates.parquet)`, ten of them and then how many more).

**Where it refuses, it says the way on.** Two cases have a line of their own:

- **Only `chartbook.lock` is not committed.** A run wrote it, and its owner commits it. In a clone at a commit somebody else pinned, a commit would be one nobody else has, and a snapshot of that meets no pin; there the line names `chartbook run --snapshot`, which passes over the lockfile.
- **The catalog's first store may only be read,** and the catalog sends this pipeline nowhere by name: a class's store listed ahead of your own. The lines say which store can be written and how to send the pipeline there (add its ID to `pipelines` under that store in `catalog.toml`), or `chartbook snapshot --store NAME` for this one snapshot.

**A dataframe's rows.** Beside the hash of each dataframe's file, a snapshot records its rows: the last date in it (`as_of`, the data's own and never the clock's) and a hash of the rows of each calendar year up to that date, a year over 128 MB by month and such a month by day. A pin copies them, and they are what lets a build of someone else's own meet the pin ({ref}`chartbook pin <a-build-of-your-own>`). They are dated by the dataframe's `date_col`; with none, the table has one hash of all its rows. The table is read a little at a time, never whole, so the memory this takes is set by a period and not by the table. A new snapshot says what each dataframe's rows did beside the snapshot before it:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at f321fcb: 2 asset(s) in the store
  Beside the snapshot before it, of f321fcb, made 2026-11-17 09:41 UTC:
    ftsfr/fed_yield_curve:treasury_yields: 24 new rows, through 2026-11-11; earlier rows unchanged
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
```

or `earlier rows changed: the rows of 2025-09-26 to 2025-12-31 differ; 2 new rows, through 2026-11-12` when the source has revised its past, and `the same rows, in other bytes` when only the writer changed. The one before is named by its commit as well as its time, since it may be another branch's. Nothing in telling this stops a snapshot, and a store that is not a folder on this machine is not read for it. Three more lines may follow the first, each for one dataframe:

- `rows not hashed: … (why). A pin of it is met by the same file, and by no rebuild.` A column of lists or structs; a single day, the rows with no date, or a table with no `date_col`, whose rows count for more than 128 MB (eight bytes a value, and sixteen and its own bytes for one of text); more than 256 columns; a CSV or JSON lines table of more than 32 MB of text; an Arrow IPC file; a date outside the years 1 to 9999, or dates in more than 1,024 calendar years; a parquet file written so that it cannot be read a little at a time (very large pages or dictionaries, or a footer of more than 16 MB: the line says which, and that the same rows written with fewer values a page can be hashed; pandas with fastparquet and DuckDB write large or wide tables so, one page to a column chunk).
- `rows not hashed this time: … (why).` No room for the scratch files, say. The snapshot is made all the same, and the next `chartbook snapshot` hashes them.
- `…: its file has the column pandas makes of an index with no name (__index_level_0__).` Where that holds row positions, they shift when a pull has more rows, and no rebuild then has the rows a pin names: `to_parquet(index=False)` drops it, and `reset_index()` keeps it as a column with a name. {ref}`chartbook run --check <chartbook-check>` warns of the same, of a parquet file that is built.

**A git tag is a version's name.** A snapshot records the git tags on its commit when it is made (`tags`). A commit is often tagged after it is built: run `chartbook snapshot` again after tagging, and since the tags are new it records them, with the same bytes; and `chartbook lineage` and a catalog's Versions page show them. Name a version with `git tag`, and unname it with `git tag -d`: `store gc` keeps the newest snapshot a tag can pin from while the tag is there, and lets it go once it is not, or always with `--aggressive`. A name keeps that snapshot only, not what it was made from (`store gc --keep-lineage` does that).

**The snapshot holds the description of its data.** With the bytes, a snapshot keeps the pipeline's own index at that commit, without any path of your machine, and the files a site needs that are not assets: `chartbook.toml`, `chartbook.lock`, the README, every write-up (`docs_path`), the pipeline's own site pages and its logo and favicon. Only files git tracks are taken, so a `.env` or an ignored draft never reaches the store; only plain paths inside the pipeline's folder, and no file that is a link or under one. Each document named and not kept is listed (`document not kept: …`). So the data dictionary of each version is kept as it stood when the data was made, and a version's site can be built from the store alone, with the repository gone: `chartbook.snapshot.materialize(taken, folder)` lays the version out as a folder, under the pipeline's own ID whatever the folder is called, with each model's recorded scores written back to its `metrics_path`, and `chartbook docs build` builds there. A dataframe that is a table or a query is in the store as parquet while its manifest names a database, so in a laid-out version its page says it is not built. A manifest a docs build would refuse still gets its snapshot; the index is then left out and the command says why:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
  index not recorded: Chart 'curve' has no 'dataframe' key linking it to a dataframe in the [dataframes] section. The bytes and the documents are in the store; `chartbook run --check` says what a docs build would refuse.
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
```

A snapshot made by an earlier ChartBook carries neither; making one again at the same commit adds them, even when the bytes have not changed.

(run-then-snapshot)=
**Build and snapshot in one command: `chartbook run --snapshot`.** `chartbook snapshot` by itself takes your word that what is on disk was built by the commit you are on. Change a script, commit, forget to rebuild, and the old data gets the new commit's label. `chartbook run --snapshot` does not have that hole:

```console
$ chartbook run --snapshot
ftsfr/fed_yield_curve: build
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
Ran build in 1 pipeline(s).
```

1. It checks that everything is committed **before** it builds, so nothing is built for an hour and then left without a snapshot. `chartbook.lock` does not count: the pin before the build is about to write that file, and the snapshot records what it says; commit the lockfile after. It also refuses here where the catalog says the store its snapshot goes to may only be read, and says how to send the pipeline to a store that can be written. (A store that is away, or a folder the system will not let you write, is found by the snapshot, after the build.)
2. It builds, and looks for what `chartbook.toml` declares.
3. It checks again. A build that changes a committed file leaves a folder the commit does not describe, and gets no snapshot. So does a build that makes a commit.
4. It makes the snapshot, and records in it that the build ran in the same command.

It exits `1` where no snapshot can be made, and it makes one of a commit checked out by its hash as of any other. It is for a script that must end with a snapshot, and for building somebody's pipeline at the commit a lockfile names. A plain `chartbook run` makes none ({ref}`chartbook run <run-makes-no-snapshot>`).

With `--force` as well, it is the weekly refresh in one line: `chartbook run --force --snapshot`.

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
- **It costs disk where the disk has no copy-on-write clones.** A snapshot is its own copy of the files (a Mac, and Linux with btrfs or XFS, clone them for free). {ref}`chartbook store gc <chartbook-store-gc>` clears old ones: those nothing pins, that are not the newest of their pipeline, that no label points into, that hold no version of an asset marked `keep = true`, and that are over 7 days old.
- **It is found by commit, or by the pipeline's ID.** A pipeline that depends on this folder, or on the same repository by URL, finds it by the commit; one that names this pipeline by its ID (`"ftsfr/fed_yield_curve" = {}`) finds it by the ID. It is in the store, so another machine that shares the store ({ref}`a store a team shares <chartbook-store>`) finds it the same ways once the store has synced, and by the ID with no folder of this pipeline there at all.

(chartbook-restore)=
`--store NAME` writes this snapshot to that catalog store; repeat it to write to several. Without it, catalog routing applies, then the first store. A read-only or unreachable destination is refused before any write. With several stores, the command says which it wrote to (`Stores: personal`).

## chartbook restore

```console
chartbook restore [NAMES...] [OPTIONS] [--project-dir PATH]
```

Put this pipeline's own assets back on disk, from its snapshots in the store. The mirror of {ref}`chartbook snapshot <chartbook-snapshot>`, which copies the folder into the store; the guide is {doc}`../guide/keeping-costly-outputs`.

With no `NAMES`, every asset `chartbook.toml` marks `keep = true` that is not on disk: a costly output, after a clean or in a fresh clone. With names, those assets, kept or not, as `chartbook path` names them: `embeddings`, `model/forecaster`, `chart/curve`. Any asset a snapshot holds can be put back.

```console
$ chartbook restore
embeddings: put back at ./_data/embeddings.parquet from the snapshot at 4f2a91c, made 2026-09-30 14:02 UTC (1.2 GB)
```

Each comes from the newest snapshot of this pipeline that holds it built, with its bytes in the store and whole, and is written at the path the manifest declares now; a newer version whose bytes are gone is refused, never quietly replaced by an older one. Nothing on disk is written over: an asset that is there is left, and said. A folder asset whose path has changed since the snapshot is not laid out at the new path, and said. What cannot be put back is said with why (no snapshot of the pipeline holds it; the store does not have its bytes; it is a table or a query in a source, which has no file; the manifest does not declare it). An asset named and not put back exits 1; with no names, a kept asset that is missing and that no snapshot holds yet is said and the command exits 0, so that CI may run it before every build, and a kept table or query is passed over. With no names and nothing missing, it says there is nothing to restore.

The snapshots are found through the commits the clone has: a shallow clone (`fetch-depth: 1` in a CI checkout) finds none of them. Fetch the whole history where `restore` is to run.

Whether the build tool then skips the step that makes the asset is its own rule: doit skips a task whose target exists only if it has no `file_dep` or has seen them before. The guide gives the recipe.

(chartbook-add)=
## chartbook add

```console
chartbook add PIPELINE [--as NAME] [--commit COMMIT] [OPTIONS] [--project-dir PATH]
```

**You seldom type this.** A build that reads a pipeline your manifest does not declare is offered it by {ref}`chartbook run <run-asks-to-add>`, at a terminal. The command is for declaring one before any code reads it, under another name (`--as`), or at a commit (`--commit`).

Declare that this pipeline reads another, by the other's ID, and pin it. It writes the entry under `[dependencies]` in `chartbook.toml`, leaving the rest of the file as it is (its comments and order), then runs `chartbook pin`. The other pipeline is read from its snapshots in the store alone: no folder of it here, and no clone.

A bare name is the one pipeline in the stores whose ID ends in it, as `chartbook get-docs` and `data.load(pipeline=...)` read one, and that full ID is written: with the store holding `tutorial/treasury_curve`, `chartbook add treasury_curve` writes `"tutorial/treasury_curve" = {}`. A bare ID the stores hold is written as it is. When several pipelines end in the name, the command lists them and writes nothing; when none does, it says which IDs the stores hold, or that they hold none, and writes nothing. Either way `chartbook.toml` and `chartbook.lock` are as they were.

```console
$ chartbook add acme/rates --as rates
Added to [dependencies] in /work/forecast/chartbook.toml: "rates" = { id = "acme/rates" }
rates: 2 pinned
Wrote chartbook.lock.
```

| Option | Effect |
|--------|--------|
| `--as NAME` | The name to know it by in code, `NAME:treasury`; its ID by default |
| `--commit COMMIT` | Take the newest snapshot at this commit (its start, 7 or more hex digits) rather than the newest of all |
| `--project-dir PATH` | The pipeline (default: the current directory) |

A key already in `[dependencies]`, or a `commit` that is not the start of one, writes nothing. An entry under a bare name that no store has a snapshot of, as `chartbook add` before 0.5.0 wrote and left when it could not pin it, can never be pinned, and code that names the bare name reads it rather than the full ID: `chartbook add` says so, of the name you give or of the full ID's last part, and that the way out is to delete its line in `chartbook.toml`. Nor does a dependency whose pin would make this pipeline depend, through what it depends on, on itself: the pin is refused as `chartbook pin` refuses it, `chartbook.toml` is put back as it was, and the command says the dependency was not added. `chartbook pin --update` moves the pin to a newer snapshot once its owner makes one.

(chartbook-pin)=
## chartbook pin

```console
chartbook pin [--update [NAMES...]] [--check] [--project-dir PATH]
```

| You type | It does |
|---|---|
| `chartbook pin` | Pins what has no pin yet. `chartbook run` does this itself before a build |
| `chartbook pin --update [NAMES...]` | Moves pins to the newest snapshot: all of them, or those of the dependencies named ({ref}`below <chartbook-update>`) |
| `chartbook pin --check` | Says whether everything pinned can be read here. Writes nothing |

Freeze what this pipeline depends on. Each pipeline in {ref}`[dependencies] <dependencies>` is pinned to a snapshot of it, and the content hash of each of its assets that code reads is written to `chartbook.lock`, beside `chartbook.toml`.

```console
$ chartbook pin
ftsfr/fed_yield_curve: 3 pinned, 1 not built. Its 2 charts and 1 notebook are not pinned: each build draws them anew
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
  From its snapshot at 4f2a91c, made 2026-10-13 18:22 UTC.
Wrote chartbook.lock.
```

**What is in the lockfile, by kind.** A dataframe and a model, always: they are what code reads. A chart, a notebook, a note or a plain file only when its owner's `chartbook.toml` says `lock = true` on it ({ref}`configuration <lock-true>`). Each of those is drawn from the data, and drawn anew by every build: a Plotly chart has a random id in its page, and an executed notebook the time of each cell, so no rebuild gives the same bytes and a pin of them could never be met by anyone who builds the other pipeline themselves. They are still read, `assets.path("fed_yield_curve:chart/curve")`, from the snapshot the lockfile names, when the store has that snapshot, and otherwise from your own newest snapshot of that pipeline at that commit that holds it, with nothing checked. A pipeline that makes only charts is pinned by its entry in the lockfile, which names its snapshot. All of this is for a dependency pinned from a snapshot; one that is a `git` repository is pinned whole, every kind of asset, since its bytes are its commit's and the same for everyone.

**Commit `chartbook.lock`.** It is source. A change to what the project depends on then shows up in a diff, and someone who clones the project sees which data it was built against. It holds no path from your machine, so pinning twice with nothing changed leaves the file as it was.

**A lockfile, and the ChartBook that reads it.** The lockfile is `chartbook/lock/v2`, which began with ChartBook 0.6.0. One written before is still read, and is written again once, by the first `pin`, `pin --update` or `run`, which says so; no pin moves. An earlier ChartBook cannot read version 2, and says only which version it reads. So where `chartbook.toml` says which ChartBook the pipeline needs, `chartbook pin`, `pin --update` and `add` raise that line when they leave a version 2 lockfile beside it (`requires_chartbook = ">=0.5.0"` becomes `">=0.6.0"`, and `">=0.5,<0.7"` becomes `">=0.6.0,<0.7"`), and an earlier ChartBook is then told what to install:

```console
chartbook.toml: requires_chartbook is now ">=0.6.0" (it was ">=0.5.0"). chartbook.lock is of a version that began with ChartBook 0.6.0, and an earlier one cannot read it: with this line it is told to upgrade, and how. Commit the manifest with the lockfile.
```

The line is rewritten in place: comments, order, quotes and line endings stay, and the file is whole or as it was (its new text is written beside it and moved over it). A manifest without the key says nothing of versions, and is left without it. So is one whose lockfile git ignores while it does not ignore the manifest: the project is shared through git with its lockfile left out, and that lockfile reaches no one else. What cannot be written so (an inline `project = { … }`, a string over several lines, a file made read-only, or one with a second name) is left, and the command says what to write there and why it did not. `pin --check` writes nothing, this included, and `chartbook run --check` fails on a version 2 lockfile under a line that admits an earlier ChartBook.

A build and a read never write a manifest. `chartbook run`, and a first read that pins, say which command does (`chartbook pin --project-dir FOLDER`, where the manifest is in another folder than the command), each time, until it has been run; where that command could not write the line either, they say what to write:

```console
chartbook.toml: requires_chartbook = ">=0.5.0" admits a ChartBook that cannot read chartbook.lock, which is of a version that began with 0.6.0: such a one says only which version it reads. `chartbook pin` raises the line to ">=0.6.0", and it is then told to upgrade, and how.
```

**A pin from a snapshot that an earlier ChartBook made** records no rows, since none were hashed before 0.6.0, and is met by the same file only. `pin` and `pin --update` say so when they write the lockfile, and what gives pins a rebuild can meet:

```console
1 dataframe is pinned by its file alone: its snapshot is from before ChartBook 0.6.0, which recorded no rows, and no rebuild meets such a pin. To pin its rows: `chartbook snapshot` again in its pipeline, with this version, then `chartbook pin --update` here. Nothing has to be built again: where a table's rows can be recorded, the same commit and the same files make a new snapshot, once.
```

It is said of what the command has just pinned, moved, or written again in the new form: never by a pin that changes nothing, and not again of a dependency that stays where it is while another moves. Once the other pipeline has such a snapshot, `chartbook pin --update` says `already pinned` of a table whose file is the same, writes the lockfile all the same, and says why: `1 dataframe has its rows pinned now, as well as its file: a build of someone's own that holds the same rows meets the pin.` A table whose rows cannot be hashed says so there too: `acme/rates:nested: its rows are not hashed (column 'l' is List(Int64) …): it stays pinned by its file alone.`

**What is asked for, and what was got.** It is the split between `requirements.txt` and `uv.lock`:

| | File | Says |
|---|---|---|
| What you ask for | `chartbook.toml` | Which pipeline, and where: a folder, or a repository at a tag or a branch |
| What you got | `chartbook.lock` | The exact commit, and the hash of every file |

A commit alone would not be enough: the same code gives other data on another day. The hashes are what say which data.

**The other pipeline's data in its folder is not read.** `pin` takes the newest snapshot at the commit that folder is on or, if that commit has none, at the nearest commit before it that has one. So its owner can be several commits past the last build they declared ready, with the folder in any state, and you still get that build. Its `chartbook.toml` and `chartbook.lock` are read, to see that the pin makes no cycle (below).

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
1 pinned asset(s) have changed upstream. `chartbook pin --update` moves the pins.
```

An asset that the pinned snapshot had not built and the newer one has is still listed as not built, with the reason `a newer snapshot has it`. A rebuild that its owner has not made a snapshot of is not mentioned, because it is not seen.

**A dependency is pinned to one snapshot, whole.** `pin` does not take one asset from a newer snapshot and leave the rest. What a second `pin` does do is pin a dependency that has no pin yet.

**Its labels are pinned too.** A snapshot records the labels the pipeline's `[models.x.aliases]` gave when it was made, and `pin` writes each as a record of its own, `ftsfr/fed_yield_curve:model/term_premium_ar1@champion`, with the hash of the version it names. `forecasting:model/x@champion` then resolves to those bytes until `chartbook pin --update`, which follows the owner's labels: a label moved shows as `moved`, one taken away as `dropped`, and one the owner has moved since you pinned is reported by `pin` as changed upstream. A label whose version the store cannot supply (no snapshot names it, or its bytes are gone) is pinned without bytes, as a `not built` asset is, with the reason, and `chartbook pin --check` reports it. Labels come only from snapshots. A `git` dependency has no versions and no labels pinned, and a dependency that becomes one lets its labels go (`let go`).

`pin` exits `1` when something could not be pinned: a dependency with no snapshot, a repository that cannot be fetched, or a pin whose bytes are not in the store, or not all there yet. Where what stands in the way is a pipeline to build (no snapshot of it, or a pin from a snapshot this store does not have and no build of yours of that commit), `pin` says so as {ref}`chartbook run <not-in-your-store>` does: the list of what to build, each pipeline after everything it reads, with what to type. The size on disk of each file a pin reads is compared with the size its record gives (no byte is read), so a file that a sync service has only half delivered is said, not read:

```console
$ chartbook pin --update
acme/rates: 1 already pinned, 1 not fully synced
  not fully synced: acme/rates:treasury: nothing was moved to the snapshot at 9c1d2e3, which names it: its object in the store at /Users/x/Google Drive/chartbook-store has 4,096 bytes of treasury.parquet where its record says 18,640: it is not fully synced yet. Wait for the sync to finish, and run this again (if it stays so, `chartbook store verify` says more)
chartbook.lock is unchanged.

1 thing(s) could not be pinned.
```

When a pin moves, `pin --update` says under the two hashes what the dataframe's rows are beside the pin it had: `24 new rows, through 2026-11-11; earlier rows unchanged`, or `earlier rows changed: the rows of 2025-09-26 to 2025-12-31 differ`, so a revision by the source is seen when the pin is moved, and the lockfile's diff shows which periods changed.

`pin --check` and a read (`data.load`, `data.path`) say the same of a pin whose object is not whole. An object that is not in the store at all is `lost`, and in a store that machines share through a synced folder the likeliest cause is a sync that has not finished, on this machine or on the one that put it there: the message says what to do on each side.

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

The lockfile records the commit. `pin` stays at that commit and uses the network only if this machine has lost its copy; `chartbook pin --update` fetches again and asks what the `rev` means now, so a branch moves forward and a tag or a commit does not. If you change `rev` in `chartbook.toml`, `pin` says so and stays where it was, and `pin --update` follows the change. ChartBook runs your own `git`, so your SSH keys and credential helpers work as they do by hand; it never asks for a password, and fails instead.

Once it is pinned, your code reads the pinned copy: `chartbook path fed_yield_curve:treasury_rates`, `data.path("fed_yield_curve:treasury_rates")` and `data.load("fed_yield_curve:treasury_rates")` all go through `chartbook.lock` into the store.

**A pin is a copy that cannot change.** A snapshot's files are copy-on-write clones where the disk has them (a Mac; Linux with btrfs or XFS), which cost nothing, and full copies everywhere else, which cost the files' size. They are never hard links or symlinks to the other pipeline's files, because those get rewritten in place when the other pipeline rebuilds.

### Working on two pipelines at once

To see a change in a pipeline you depend on and are changing too, declare it ready and move to it: commit the change there, run `chartbook snapshot` there, then `chartbook pin --update` here, which prints what moved. A lockfile names only what a snapshot or a commit holds, so every pin can be traced to the commit it came from.

When working on two pipelines together, run `chartbook link ID FOLDER` in the consumer. Reads follow that explicit local link and warn that pins are not in use. Without a link, a dependency needs a snapshot. A snapshot is refused while `chartbook.links.toml` exists; remove it and update pins before publishing.

**`--check`: say, and write nothing.** For CI, and for anyone whose store is read-only. `chartbook pin --check` pins nothing, fetches nothing and writes nothing: not the lockfile, no object, and not the store's note for `store gc`. It reads `[dependencies]`, `chartbook.lock` and the store, and exits `1` unless the pipeline can be built from its lockfile alone: every dependency pinned, from where the manifest says it is; every asset built when it was pinned; every pin in the store. What keeps those pins from `store gc` on another machine is the note that this machine reads them, and that is left by what does read them: {ref}`chartbook run --frozen <chartbook-run>`, which builds from the lockfile, and a read through the lockfile (`data.load`), silently (see {ref}`store gc <chartbook-store-gc>`).

Through 0.5.1 this was `chartbook pin --frozen`, and it left that note. `--frozen` is gone from `pin`, and says so when typed. A job that ran only `pin --frozen` to leave the note runs `chartbook run --frozen` instead; in a pipeline with no build script, a read through the lockfile leaves it.

```console
$ chartbook pin --check
ftsfr/fed_yield_curve:model/term_premium_ar1: was declared and not built when it was pinned. Build it there, declare it ready, and `chartbook pin --update`.
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.

$ chartbook pin --check
4 pin(s) of 1 dependency, all in the store. Nothing written.
```

Where `pin` records an asset that was not built and goes on, `--check` counts it a problem: the build that follows may need it.

(a-build-of-your-own)=
**A pin is met by the same file, or by a build of your own that holds the same rows.** A team that shares a store has the pinned files in it, and nothing more is looked at. Where no store is shared, each person builds the other pipeline themselves, at the commit the lockfile names, and `chartbook run --snapshot` there puts that build in their own store. Where the store does not have the snapshot the lockfile names, a snapshot of yours of the same pipeline at the same commit **stands in** for it when it meets every pin of that dependency: each by the same file or, for a dataframe, by the same rows up to the pin's last date (its `as_of`). Rows after that date are left out and counted. `pin --check`, `chartbook pin`, `chartbook run` and every read then use your build, whole, and say which, by its commit and when it was made:

```console
$ chartbook pin --check
ftsfr/fed_yield_curve: read from your own build of 0db8051, made 2026-11-17 09:22 UTC
  treasury_yields: the pinned rows, through 2026-10-30; 24 newer rows
1 pin(s) of 1 dependency: 0 in the store, 1 met by your own build. Nothing written.
```

The lockfile is not touched, so everyone who builds that commit is checked against the same pin. A value the source has since changed in the past is a real difference: the check exits `1`, a read raises `AssetNotPinnedError` (reason `differs`), and each names the periods that differ and the way on, `chartbook pin --update`, which pins your build instead.

```console
$ chartbook pin --check
ftsfr/fed_yield_curve: your build of 79986dd, made 2026-11-17 09:21 UTC, does not match the pin
  treasury_yields: the rows of 2025-09-26 to 2025-12-31 differ
  To read your build instead: chartbook pin --update ftsfr/fed_yield_curve
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.
```

A model is met by the same file only. So is a version pinned by its label, and a dataframe whose pin records no rows: one pinned before ChartBook hashed rows (pin it again from a snapshot made by this version), one whose rows are not hashed ({ref}`chartbook snapshot <chartbook-snapshot>` says which), or a table that had no rows when it was pinned. The comparison reads the table's rows once and is remembered in this machine's cache folder. With neither the pinned files nor a build of yours in the store, the check says so once for each dependency, with how to build it; where the store has some other snapshot of that pipeline, a last line offers `chartbook pin --update` to move the pin to it:

```console
$ chartbook pin --check
ftsfr/fed_yield_curve: 1 of its 1 pin is not in the store at ~/store, and no build of yours at 0db8051 stands in: treasury_yields
  To build it yourself: in ../fed_yield_curve, `git checkout 0db8051` and `chartbook run --snapshot`: a build of yours meets a pin by the same file or, for a dataframe, by the same rows up to the pin's last date.
  What it reads in turn may not be in the store either: `chartbook run` lists all there is to build, in order.
  Where a store is shared: point CHARTBOOK_STORE at the one that has it; in a synced folder, wait for the sync to finish, here and on the machine that made the pin.
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.
```

The check fetches nothing, so it names what this pipeline lacks and no more; {ref}`chartbook run <not-in-your-store>` reads what each of those reads in turn, and lists all of it.

A store that has the snapshot the lockfile names has the pin itself, and no build stands in for it there: a pinned file such a store lacks is lost from it, or not synced yet, and the check says so and how to wait or put it back. That is the case of a team that shares a store, where another build of the same commit may be anyone's.

Dependencies between pipelines must form a graph with no cycles. A pin whose new or moved entries would lead back to this pipeline, or into pipelines that depend on each other, is not written: `chartbook pin` says who depends on whom, and where each was read, and exits 1 with `chartbook.lock` and the store as they were. `chartbook pin --update` and `chartbook add` do the same, and the first read of a dependency, which pins it, raises `AssetNotPinnedError` with reason `cycle`. A cycle reached only through pins made before is not the new pin's doing and does not stop it: `chartbook run` and `chartbook run --check` say it, and `chartbook pin --check` exits 1. An ID names one pipeline: a copy that kept another's ID and reads it depends on itself. Where the cycle closes on the ID in another folder, the message names both and says what to do either way: two checkouts of one repository are one pipeline, and one of the dependencies comes out; two pipelines that share the ID give one of them an ID of its own with `[project] id`.

(chartbook-update)=
### pin --update

`chartbook pin --update` moves every pin, and `chartbook pin --update NAMES...` those of the dependencies named. (Until 0.6.0 this was `chartbook update`, which now says where it went.)

Move pins forward, and rewrite `chartbook.lock`. A folder you depend on moves to its newest snapshot. A repository is fetched again, and moves to what its `rev` means now. With no argument every dependency is updated. Name some to update only those, as they are written in `[dependencies]`; the scope may be left off when only one has that name.

```console
$ chartbook pin --update fed_yield_curve
ftsfr/fed_yield_curve: 1 moved, 2 already pinned, 1 not built
  ftsfr/fed_yield_curve:treasury_rates
    sha256:4b1f9a0c2e3d… -> sha256:99ab40d12e77…
  not built: ftsfr/fed_yield_curve:model/term_premium_ar1 (./_models/term_premium_ar1.json)
  From its snapshot at 9c1d2e3, made 2026-10-14 09:00 UTC.
Wrote chartbook.lock.
```

**Newer code, or only newer data**, depends on what you asked for in `chartbook.toml`:

| You depend on | `chartbook pin --update` brings |
|---|---|
| A folder | Whatever its owner last declared ready: newer code if they committed any, newer data if they only rebuilt |
| A repository at a tag or a commit | The same code. Newer data only if it was built again (`chartbook run --force`) |
| A repository at a branch | Newer code, when the branch has moved |

If the other pipeline's owner has rebuilt and made no snapshot, there is nothing to move to, and `pin --update` changes nothing.

**A pipeline whose ID changed.** A dependency named by its ID stays at the last snapshot made under that ID. When the store has newer snapshots of the same repository and folder under another ID (the owner added a remote, so the pipeline has a scope now; see {ref}`Pipeline Identity <pipeline-identity>`), `pin` and `pin --update` say so each time, and name the entry that follows it:

```console
$ chartbook pin --update
first_pipeline: 1 already pinned
  the store has newer snapshots of the same repository and folder under another ID, testorg/first_pipeline (the newest made 2026-10-17 16:54 UTC): the pipeline probably calls itself that now, as one does when it gets a git remote or a [project] id. To follow it, write "first_pipeline" = { id = "testorg/first_pipeline" } under [dependencies], then `chartbook pin --update first_pipeline`.
```

The `id` keeps the name your code uses, `first_pipeline:rates`.

An asset the newer snapshot no longer declares is dropped from the lockfile. One it declares and did not build is let go: a pin from an older snapshot does not belong beside a newer one's commit. Nothing of this pipeline is rebuilt. The object a pin moved away from stays in the store.

**A `git` dependency that `chartbook run` built** is treated the same way. When an update moves it to a new commit, data that was built at the old commit, and is not built at the new one yet, is let go:

```console
$ chartbook pin --update
ftsfr/ref_data: fetched https://gitlab.example.org/ftsfr/ref_data at 9c1d2e3 (main)
ftsfr/ref_data: 2 already pinned, 1 let go
  let go: ftsfr/ref_data:daily_prices (./_data/daily_prices.parquet)
  What was let go was built at the commit pinned before, and is not built at this one. `chartbook run` builds it and pins it.
Wrote chartbook.lock.
```

Keeping it would leave the lockfile naming one commit beside data built from another, which nobody else could get back. `chartbook run` then builds the new commit and pins what it builds.

(chartbook-lineage)=
## chartbook lineage

```console
chartbook lineage [--project-dir PATH] [--check] [--rehash] [OPTIONS] [--json]
```

Show where this pipeline's data comes from, and check it, all the way up. It starts from the lockfile: each snapshot the pipeline is pinned to, then the snapshots those were pinned to, as each recorded them when it was made, and so on. Every step of the way is a hash, and each is checked:

- the snapshot named is in the store, and can be read;
- what was pinned from it is what it holds: each asset at its hash, for this pipeline's lockfile; for a snapshot upstream, the hash it recorded over everything it pinned, made again from the snapshot it names;
- each snapshot's recorded pins cover every dependency its own manifest, kept with it in the store, declares;
- each asset of each snapshot is in the store.

```console
$ chartbook lineage
acme/forecast (this folder)
├── fred: acme/fred 49780a2, made 2026-10-16 23:51:46 UTC
└── rates: acme/rates 49780a2, made 2026-10-16 23:51:46 UTC
       gap: its manifest declares the dependency 'fred', and the snapshot records no pin of it: it was made before snapshots checked their pins, or from a lockfile that did not list it
2 snapshot(s) upstream; 1 gap(s).
```

A snapshot met twice is walked once and marked "shown above". A `git` dependency is pinned from its clone, not from a snapshot, so the walk stops there. What the walk reads was written by whoever can write to the store, so a record that is not what ChartBook writes is a gap where it is met ("a record that cannot be read"), never an error that stops the walk; a snapshot that is there and does not hold what was pinned is shown as such. Model labels are resolved from the snapshots the walk has read, or by their hash among the store's objects; where several objects share a label's start, the one that gives the recorded hash is taken. `--rehash` reads those versions too. By default `store gc` lets old lineage go, keeping what work needs now; a snapshot upstream it removed is shown as not in the store, and `store gc --keep-lineage` keeps a lineage whole. Each snapshot's line gives its tags, if any, and says how its own lineage was checked when it was made, as its record says (`built_with.lineage`): "pins checked" for every snapshot made since snapshots check their pins, "lineage checked" for one made with `chartbook snapshot --deep`, "made before pins were checked" otherwise. Nothing is written.

| Option | Effect |
|--------|--------|
| `--project-dir PATH` | The pipeline (default: the current directory) |
| `--check` | Exit `1` if there is any gap: for CI |
| `--rehash` | Also hash every asset of every snapshot again, which reads all of their bytes |
| `--json` | Print the graph as JSON: each pipeline's `label`, `kind` (`working`, `snapshot`, `git`, `no_snapshot`, `nothing`, `missing`, `mismatch`, `unreadable`), `pipeline`, `commit`, `made_at`, `gaps` and `children` |

(chartbook-run)=
## chartbook run

```console
chartbook run [SCRIPT] [--force] [--snapshot] [--frozen] [--remake] [--upstream] [--no-gc-reminder] [--check [--within DAYS] [--policy PATH]] [--project-dir PATH]
```

Build this pipeline. It pins what the pipeline reads, runs its build, and looks for what the build was to make. A {ref}`snapshot <chartbook-snapshot>`, which is what your other pipelines read and the catalog shows, is a command of its own: a run makes none, and its last lines name the command.

```toml
[scripts]
build = "doit"
```

```console
$ chartbook run
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

`SCRIPT` is a name from {ref}`[scripts] <scripts>`. With none given it is `build`, the script that makes a pipeline's data current.

What `chartbook run` does for `build`, in order:

1. **Builds a `git` dependency that is not built yet**, in ChartBook's own clean copy of the commit.
2. **Pins what has no pin yet**, so this pipeline's code can read it: a folder you depend on from its newest {ref}`snapshot <chartbook-snapshot>`, a repository from that clean copy. A dependency named by its ID that the store has no snapshot of is built and pinned from its repository on the default host, as a `git` dependency is ({doc}`configuration`, `[resolve] default_host`).
3. **Runs this pipeline's `build`**, in its own directory. What the script prints is shown as it runs. If it fails, the command exits with the script's exit code.
4. **Looks for what `chartbook.toml` declares.** Whatever the manifest gives a `path` that a build is to write (a dataframe, a chart, a notebook, a model and its metrics file, a file), and the file of a DuckDB source, must be there now. One that is not fails the run, whatever the script exited with.
5. **Says what makes a snapshot of it.** It makes none itself: its last lines say to commit and then `chartbook snapshot`, and are the same whatever is committed.

(run-makes-no-snapshot)=
**A run makes no snapshot.** Building, and putting a build where other pipelines read it, are two things, and a run does the first. Most builds are of work in progress, and what is in the store is what somebody chose to put there. So the last lines of a run are the same whether or not everything is committed, on any branch, in a git repository or not:

```console
$ chartbook run
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

When the build is one to keep: commit, and {ref}`chartbook snapshot <chartbook-snapshot>`, which takes what is on disk and builds nothing again. What stands in a snapshot's way (a file that is not committed, a `chartbook.lock` the run wrote, a gap in the pins, a store that cannot be written) is said by that command, when it is typed. Where the run was given `--project-dir`, the command in the line has it too (`chartbook snapshot --project-dir /work/rate_forecast`). The catalog is named because it shows snapshots and nothing else: a pipeline that is built and has none is not in it. A pipeline that declares nothing a snapshot would hold is told nothing of snapshots; neither is a script other than `build`, nor a run with `--frozen`, which is for CI and for a store you may only read.

A run that must end with a snapshot is asked for one: `chartbook run --snapshot` (below). A plain run puts nothing of what it built in a store, and neither makes a catalog nor asks about one. (The one question a run asks is whether you trust a folder to run, once, the first time: below.)

(run-looks-for-what-was-declared)=
**A build that did not write what `chartbook.toml` declares is a failed run.** A script can exit `0` and have made nothing: a task that was skipped, a file written under another name, an output added to the manifest and not yet to the code.

```console
$ chartbook run
ftsfr/rate_forecast: build
Error: ftsfr/rate_forecast: its build did not write 1 thing chartbook.toml declares: forecast (./_data/forecast.parquet). Nothing after it was run.
$ echo $?
1
```

With `--snapshot`, no snapshot is made of it. What is looked for is what a snapshot would hold as a file: a path is written when it holds a file, so a folder with nothing in it, or a pattern that matches nothing, is not. The file of a DuckDB {ref}`source <sources>` is looked for too, since the build writes its tables into it (`source local (./_data/local.duckdb)`). A dataframe that is a table or a query in a source has no file of its own, and a page of prose kept in git (a note, a write-up) is not an output: neither is asked of a build. Only `build` is asked: another script may run before anything is built. The names are the ones `chartbook path` takes (`forecast`, `chart/curve`, `model/ar1`).

`build` runs with `CHARTBOOK_BATCH=1` set; another script runs as interactively as the shell it was run from. In a batch run, `data.load` and the other readers read another pipeline only through its pin: an undeclared dependency or an unpinned dependency is refused. Explicit links are honored for development, and `--snapshot` refuses them. `--frozen` and CI ignore links. CI can set the variable too. See {doc}`../guide/depending-on-pipelines`.

In a fresh clone, `chartbook run` is the only command you need: there is no `chartbook pin` to remember first.

(run-asks-to-add)=
**A read of a pipeline that is not declared: the run offers to add it.** You write the read, and run. The build's read is refused, as ever, since nothing in `[dependencies]` names that pipeline; and where your store has snapshots of it, the run asks:

```console
$ chartbook run
ftsfr/rate_forecast: build
…
ftsfr/rate_forecast: its code reads from a pipeline that chartbook.toml does not declare:
  ftsfr/fed_yield_curve   (in your store: 2 snapshots, the newest of 4f2a91c)
Add it to [dependencies] and build again? [Y/n]: y
Added to [dependencies] in /work/rate_forecast/chartbook.toml: "ftsfr/fed_yield_curve" = {}
ftsfr/fed_yield_curve: 3 pinned
  From its snapshot at 4f2a91c, made 2026-11-19 14:02 UTC.
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

Yes does what {ref}`chartbook add <chartbook-add>` does, and builds again. The read is found when the code makes it; nothing reads your source for names. One pipeline is asked of at a time: a build stops at the first read it is refused, so a second is asked of when the build is run again.

(not-in-your-store)=
**What it reads is not in your store: the run lists what to build, in the order to build it.** A class with no shared store, a new laptop: the lockfile pins snapshots that this machine's store does not have, and each of those was built from others it may not have either. The run stops before anything is built and says all of it, each pipeline after everything it reads, with what to type:

```console
$ chartbook run
Fetching https://github.com/ftsfr/he_kelly_manela, to see what ftsfr/he_kelly_manela reads in turn.
ftsfr/report cannot be built yet: 2 pipelines it reads are not in the store at /Users/x/.chartbook/store.
Build them in this order, with the commands below. Each ends with a snapshot, which is what the next one reads.

1. ftsfr/he_kelly_manela at 7802799    https://github.com/ftsfr/he_kelly_manela
     git clone https://github.com/ftsfr/he_kelly_manela /work/he_kelly_manela
     git -C /work/he_kelly_manela checkout 7802799a41c2
     chartbook run --snapshot --project-dir /work/he_kelly_manela
2. ftsfr/fed_yield_curve at 0db8051    ../fed_yield_curve (a folder on this machine); reads 1 above
     git -C /work/fed_yield_curve checkout 0db8051e3f7b
     chartbook run --snapshot --project-dir /work/fed_yield_curve

Then here again:
     chartbook run --project-dir /work/report
Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has them, or wait for its sync to finish.
```

- **What is on the list:** a dependency with no snapshot to pin, and one that is pinned where the store has neither the pinned snapshot nor a build of yours of that commit. A build of yours that is there and does not meet the pins is not on it: that is said {ref}`as it is <a-build-of-your-own>`, with `chartbook pin --update` as the way to read your build.
- **It goes up.** For each pipeline on the list, its own `chartbook.toml` and `chartbook.lock` at the commit to build are read, and what *it* reads that the store lacks comes before it. A folder a `path` entry names is asked through git for those two files, and is not changed. A repository is fetched into ChartBook's git cache, as a `git` dependency is, and nothing of it is checked out; a fetch that receives nothing for 30 seconds is given up.
- **A clone you already have is read where it is.** A repository whose clone sits beside this pipeline's own (a folder named as `git clone` names it, whose `origin` is that address; in whatever letter case the disk has it, where the disk takes either), or that *is* this pipeline's own repository, is not fetched: its files are read from the clone at the commit to build, and its line says to build there (`../fed_yield_curve (a clone of https://…)`). A repository that wants a password cannot be fetched from here at all, and a class has its clones side by side. A folder is taken for a clone only by its `origin`, never by its name or by the ID of a pipeline in it; where nothing records a pipeline's address, a clone beside is its own when its `origin` gives that ID (`https://github.com/acme/rates` is `acme/rates`). A clone that lacks the commit gets a `git fetch` line first (`--unshallow` for a shallow one), and one with no commit yet a `git pull origin HEAD`; its folder in the clone is then taken from where the clone has the pipeline now, and the line says so.
- **A pipeline is listed once for each commit of it that is wanted.** What two pipelines read is one line, and each names it (`reads 1 above`). A read with no pin is met by any line of that pipeline; and where one reader has no pin and another pins the very commit that would be built, the one line is the pinned one.
- **A line says what is known, and no more.** It may lack its commit (never pinned: any commit of it will do), its address (`its repository is not recorded`: a snapshot made in a repository with no remote records none), or what it reads in turn (`What it reads in turn is not known: its repository could not be fetched (…)`).
- **A line is one command, the same in every shell.** None enters a folder, and none is joined to another with `&&`: a command names the folder it works in (`git -C FOLDER …`, `chartbook run --snapshot --project-dir FOLDER`). So the lines are the same in a POSIX shell, in `cmd.exe`, in PowerShell and in Git Bash, and you stay in the folder you are in. The last line is the command you typed, with this pipeline's folder. Type them one at a time. Pasted together, each runs whatever the one before it did: a build after a checkout that failed builds the commit its folder is on, and makes a snapshot of that. What is read through a pin is safe from it, since a pin is met only by the same file or, for a dataframe, the same rows. A pipeline that was never pinned takes the snapshot that was made, and the line of its pin says of which commit. Each command runs in the environment you are in: where a pipeline has one of its own, enter its folder and type its `chartbook run --snapshot` there.
- **Every command can be pasted, from any folder, in the order given.** A folder is named whole, and a repository is cloned beside this pipeline's own, once, under a name that is free. A commit in a command is its first twelve digits. A pipeline in a folder of its repository is built in that folder, and the checkout is made at the repository's top (`git -C REPOSITORY checkout COMMIT`, then `chartbook run --snapshot --project-dir FOLDER`); a line with no pin, in a repository a line above has left on another commit, checks out the commit it was read at. One with no `build` script, which commits what it declares, is given `chartbook snapshot`; so is a folder that was never pinned, has nothing uncommitted and has every declared file on disk (`built already`), since a build may take an hour. On Windows a folder is in double quotes, which `cmd.exe`, PowerShell and Git Bash all read. A line there is given no command, and says so, where one would hold what a shell reads even inside quotes: a `$` (but one that ends a name or comes before a slash, as in a share named `home$`), a backtick, a `!`, a `"` of the plain kind or of a word processor's, or a `%` that does not begin the two digits a web address writes a sign with (`%20`) or that, with another, encloses the name of a variable. An address in a lockfile is anyone's, and so is a folder's name in a repository that was cloned: `git clone "https://…/$env:TOKEN"` would send the token where the address says, and a folder named `$(…)` would be run. The line says what to make by hand, and the last line is given so too. In Git Bash a network folder (`\\server\…`) is read otherwise: type it in single quotes there.
- **No command moves this pipeline's own repository.** A pipeline in the same repository, wanted at another commit, is built in a worktree of that commit: `git -C REPOSITORY worktree add REPOSITORY-at-COMMIT COMMIT`, then `chartbook run --snapshot --project-dir` with its folder there. Your checkout stays on its branch. A worktree of that name that is there, on that commit, is used as it is; a folder of that name that is anything else is passed by, for `REPOSITORY-at-COMMIT-2`.
- **A repository that does not hold the pipeline is not on the list.** Where an entry's `repository` is another pipeline's, the pin's own words say so (`has no snapshot of acme/beta made in https://…`), and nothing says to build there. A manifest that cannot be read is still its folder's (the line names the folder, and that pipeline's own run says what is wrong with it), and in a repository of more than 200 manifests the line says how far the search went.
- **Whose text it is.** A lockfile is anyone's. An address in it is printed, and fetched, only if it is a plain web address (`https://…`), which is all a snapshot records; a pipeline's name only if it is an ID; and everything is shown without control characters and quoted for the shell.
- **Pipelines that are not in the store and read each other have no order to be built in.** That is an error, in the words of any cycle: which pipelines, and for each step the file it was read from.
- **What the run builds by itself is not on the list:** a `git` dependency; one named by its ID where `[resolve] default_host` says where to clone it; and, with `--upstream`, a folder a `path` entry names that was never pinned. Where every line is such a folder with a `build` script, the list's last lines offer `chartbook run --upstream`.

{ref}`chartbook pin <chartbook-pin>` prints the same list. `chartbook pin --update` does not: it asks for the newest snapshot of each, which is not the commit a pin names. `chartbook pin --check` and `chartbook run --frozen`, which fetch nothing, say what this pipeline itself lacks and that `chartbook run` lists the rest.

It asks only where yes can work. With no one there to answer (a script, a pipe, CI), with `--frozen` or `--snapshot`, for a read made from another pipeline's folder, for a name two pipelines in the stores share, for an ID two repositories claim, and for a pipeline the stores have no snapshot of (a folder or a repository, which is declared by hand), there is no question: the build's own error stands, and it names the entry to write, and `chartbook add` where the store has the pipeline. Keys pressed while the build ran do not answer the question: they are discarded before it is shown.

**Only in a folder you trust to run.** A build script is code. In a pipeline you have not trusted to run, you are asked first when you are at a terminal (`y` trusts it, Enter stops; {ref}`chartbook trust <chartbook-trust>`). Where no one is asked, `chartbook run` stops before anything runs, naming the folder and {ref}`chartbook trust <chartbook-trust>`; catalogs have no runnable members. A pipeline trusted to render only is refused the same way. A project `chartbook init` made is trusted as it is made, and under `CI` the checkout is.

**It never builds in a folder this pipeline depends on, and never reads one**, unless you say `--upstream` (below). A `path` dependency is a folder somebody works in. They may be half-way through a change. This pipeline reads the snapshot it pinned, not what is in that folder, so building there would disturb its owner and change nothing this pipeline reads. That folder is its owner's to build, and to declare ready with `chartbook snapshot`. If its owner has made no snapshot yet, `chartbook run` stops and says so.

**Unless you say `--upstream`, for folders that are yours.** With `--upstream`, a `path` dependency on this machine that has no snapshot to pin, and is not pinned yet, is built first and snapshotted after its build succeeds, so that this pipeline can pin it; and so is each of its own, as far up as they go, each before what depends on it. The run says which first:

```console
$ chartbook run --upstream
Upstream with no snapshot to pin, built and snapshotted first:
  ftsfr/fed_yield_curve    in /work/fed_yield_curve
ftsfr/fed_yield_curve: build    in /work/fed_yield_curve
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made, for what depends on it in this run to pin.
ftsfr/rate_forecast: pinning what it depends on
...
```

Before anything runs, each upstream must be trusted to run, as this pipeline must (at a terminal you are asked, with each upstream marked as one; elsewhere an untrusted one stops the run), must have a `build` script, and must have everything committed, since a snapshot is labelled with its commit; and the dependencies, the upstreams' too, must form no cycle. Its build must leave its committed files as they were, and its commit where it was. A pipeline of the run itself, in a catalog, that another pins by path and that has no snapshot is snapshotted after its build the same way. Builds that end in a snapshot of one folder take turns, across runs (an upstream of two runs, a catalog member, the owner's own `chartbook run --snapshot`): a run that has to wait says so, an upstream that has a snapshot by its turn is not built again, and a folder that changed while it waited is not built. A lockfile its pin wrote in its folder is said, to commit there. The first that fails stops the run, and nothing that depends on it is built. An upstream that has a snapshot, or that this pipeline has pinned already, is not built again. `--upstream` is not taken with `--frozen`, and is for `build` only. A `git` dependency, and one named by its ID got from its repository, is built in ChartBook's own copy and pinned from it whether or not you say `--upstream`.

**It never moves a pin.** If the other pipeline's owner has made a newer snapshot, this one is still built against the one it pinned, and you are told:

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 2 already pinned, 1 changed upstream since it was pinned
  changed upstream: ftsfr/fed_yield_curve:treasury_rates
chartbook.lock is unchanged.
1 pinned asset(s) have changed upstream. `chartbook pin --update` moves the pins.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

To build against the newer snapshot, run `chartbook pin --update` and then `chartbook run`. The lockfile changes only when you ask it to, so it only ever changes in a commit you meant to make.

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
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.

$ chartbook run
ftsfr/ref_data: built already, at 4f2a91c
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
ftsfr/rate_forecast: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

Nothing builds it a second time by itself. Two things do, both on purpose:

| You want | You run |
|---|---|
| The same code, and fresh data it pulls from outside | `chartbook run --force`, then `chartbook pin --update` |
| Newer code | `chartbook pin --update`, then `chartbook run` |

`run` stays at the commit in `chartbook.lock`. A `git` dependency that commits its data and has no `build` script is not built and not mentioned.

**Build, and snapshot: `--snapshot`.** `chartbook run --snapshot` makes a {ref}`snapshot <run-then-snapshot>` after the build, in the same command: it refuses to build with anything uncommitted, and it fails where no snapshot can be made. For a nightly job, and for building somebody's pipeline at the commit a lockfile names ({ref}`a build of your own <a-build-of-your-own>`). After its snapshot, one line says what `chartbook store gc` would clear, as `chartbook snapshot` says it (`--no-gc-reminder` silences it).

**Check without building: `--check`.** `chartbook run --check` runs nothing: it checks the manifest and the folder, for CI, and has {ref}`a section of its own <chartbook-check>`. It goes with `--within`, `--policy` and `--project-dir`, and with no script but `build` and none of the options above.

**Another script.** `chartbook run test` runs `test` in this pipeline, and that is all it does. Only `build` pins, only `build` reaches what the pipeline depends on, and only `build` is followed by the look for what was declared and by the lines that name `chartbook snapshot`.

**Run it in a pipeline.** A catalog lists stored snapshots and runs no code: in a catalog's folder, `chartbook run` says so and stops.

**What it is not.** It is not a task runner. A script is one string. Scripts do not depend on each other, and there are no retries, no schedule and no history. What is out of date inside a pipeline is for the pipeline's own tool to decide (doit, Make, Snakemake); `chartbook run` runs that tool every time.

A script is run by `bash`, or by `sh` where there is no `bash`, and stops at the first command in it that fails. On Windows it is run by `cmd`: a script of one line as it is, and one of several lines as a batch file that stops at the first line that fails, with that line's exit code; there a line that runs another batch file (`conda activate`, which is `conda.bat`) must begin with `call`, or nothing after it runs.

**`--frozen`.** Pin nothing and write nothing before the build but the store's note that this machine reads these pins, so that `store gc` on another machine keeps them: not the lockfile, no object, and no `git` dependency is fetched or built. The first time, the check's line ends `Nothing written but the store's note that this machine reads these pins.`; once the note names them all it ends `Nothing written.`; and where the store cannot be written it says the note could not be, on stderr, and builds all the same. The build runs only if `chartbook pin --check` would pass; otherwise nothing runs and the problems are listed. `--frozen` and `--snapshot` are one or the other.

**`--remake`.** An asset `chartbook.toml` marks `keep = true` cost something to make ({doc}`../guide/keeping-costly-outputs`). When one is not on disk while the store has a version of it, `build` stops before anything runs, in a catalog before any member's build, and says the two ways on:

```text
Error: acme/docs: embeddings is kept, and is not on disk (./_data/embeddings.parquet). The store has its version from 4f2a91c, made 2026-09-30 14:02 UTC.
  chartbook restore           puts it back
  chartbook run --remake      runs the build without it, which makes it again
Nothing was built.
```

{ref}`chartbook restore <chartbook-restore>` puts the bytes back (for an upstream of `--upstream`, `chartbook restore --project-dir` its folder), and `--remake` runs the build without them, which makes the asset again; it covers every kept asset at once, so to remake one and keep another, restore the other first. A first build, with no version in the store, is not stopped, and a kept asset that is on disk stops nothing: to remake one on purpose, delete the file, then `--remake`. The stop covers the pipeline and any upstream pipelines the command builds; a `git` dependency built in ChartBook's own copy is not stopped. A version whose bytes are not in the store is nothing to put back, so it stops nothing either.

```console
$ chartbook run --frozen
ftsfr/rate_forecast: 4 pin(s) of 1 dependency, all in the store. Nothing written.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

(chartbook-check)=
### run --check

`chartbook run --check` goes with `--within DAYS`, `--policy PATH` and `--project-dir PATH`, and with nothing else of `chartbook run`.

The CI gate: {ref}`chartbook run <chartbook-run>` told to run nothing. It checks the manifest and the folder in seconds, builds and pins nothing, and asks for more than a run does of its own build: a policy's fields, a license's date. (Until 0.6.0 this was `chartbook check`, which now says where it went.) It exits `0` on a healthy project and `1` when it finds any of:

- **a missing required field** — a field the policy requires that is absent or empty (with no policy given, the recommended fields are only warnings; see below);
- **a broken path** — a `docs_path`, a note's `path`, `readme`, `logo` or `favicon` pointing at a file that does not exist: what is kept in the repository. (An output that is not built is listed, and is no problem: below.) Or an asset's `path` that names a file or folder with `[`, `?` or `*` in its name (`./_data/[raw]`), which a reader would take for a pattern: rename it;
- **a dependency that cannot be found** — an entry of {ref}`[dependencies] <dependencies>` whose `path` is not a directory with a pipeline's `chartbook.toml` in it, or a model's `trained_on` naming a dataframe that the other pipeline does not declare. A `path` whose folder is not on this machine, and that `chartbook.lock` pins with every pin in the store, is a warning instead (another machine's folder: the pipeline builds here with `run --frozen`), and either way the message gives the entry that names it by its ID;
- **an expiring license** — a dataframe whose `license_expiration` has passed, or falls within `--within` days;
- **a build tool's task that says `chartbook run`** — in the pipeline's `dodo.py`, `Makefile` or `justfile` (the file of the tool its build command runs), as a pipeline written for 0.1.1 has to render its site; reported on the `build` field, since `chartbook run` would run the build command, which runs that task again (see {ref}`chartbook run <chartbook-run>`).

A project whose `[project] requires_chartbook` this ChartBook does not meet is not checked: the command stops first, as every command that acts on the manifest does, and says how to install one that meets it.

Each finding is one line naming the manifest, the table and the field, so a CI log is enough to fix it:

```console
$ chartbook run --check --policy ../catalog
chartbook.toml: [charts.repo_rates] units: required by the policy in ../catalog, but missing or empty
chartbook.toml: [dataframes.crsp_bonds] license_expiration: license expires on 2026-11-02 (in 22 days, inside the 30-day window)
chartbook.toml: [dataframes.repo_public] path: not built yet: /work/repo/_data/repo_public.parquet

2 problem(s) found in 1 manifest(s). 1 output is not built yet, which is no problem.
```

| Option | Default | Effect |
|--------|---------|--------|
| `--project-dir PATH` | `.` | Pipeline to check |
| `--within DAYS` | `30` | How far ahead a license expiration counts as a failure. `0` fails only on licenses already expired or expiring today |
| `--policy PATH` | — | Take required fields from the `[policy]` table of this file (a catalog's `catalog.toml`, its directory, or any TOML file with a `[policy]` table) |

**Which fields are required.** A pipeline uses its own `[policy]`, with the machine catalog's policy as a fallback. `--policy FILE` explicitly replaces it. A missing required field fails the check. Catalogs compare snapshot metadata with their policy on the Diagnostics page; `chartbook run --check` is a pipeline command.

When no policy is given anywhere (no `[policy]` in the pipeline, none in the catalog it is checked in, no `--policy`, or a `--policy` file with no `[policy]` table, as a catalog that sets none), the check uses the built-in recommended-field lists, the same ones that drive the diagnostics page, as advice only: each missing field is a `warning:` line, and none of them makes the check fail. The one exception is a write-up: a dataframe or chart whose `docs_path` or `docs` is empty fails the check whatever the policy, since the format itself requires one.

```console
$ chartbook run --check
warning: chartbook.toml: [project] repo_url: recommended by the default policy, but missing or empty
warning: chartbook.toml: [charts.repo_rates] units: recommended by the default policy, but missing or empty
chartbook.toml: OK (1 pipeline(s), 1 dataframes, 1 charts, 0 notebooks)
```

A missing build script is named `[scripts] build`. `[project] build`, the old place, is still read and counts as well, here and for a policy's `project = ["build"]`.

`policy.mode` is not consulted. It decides what a *build* does about missing metadata; the check always reports it.

**License dates** are ISO dates (`license_expiration = "2026-12-31"`, or a bare TOML date). An empty value, `"N/A"`, `"None"` and `"Never"` mean the license does not expire. Anything else that is not a date is itself reported, because a gate that cannot read a date cannot vouch for it.

**An output that is not built is no problem.** Data files, rendered charts, executed notebooks, models and a source's DuckDB file are what a pipeline *produces*, and they are usually not in git. A CI job that checks out the repository without running the pipeline, which is every job for a pipeline whose data needs a subscription, has none of them. Each is listed as `not built yet` and counted as nothing, and everything that lives in the repository is still checked: required fields, license dates, write-ups, notes, the README, the logo. (Until 0.6.0 this was `chartbook check --skip-outputs`, which left them out; the option is gone, since it is how the check always is.) A build that did not write what it declares is caught where a build is: `chartbook run` fails on it, on each of these kinds. The lines are on stderr, as a warning is: what is on stdout is a problem to mend, or the line that says there is none.

```console
$ chartbook run --check
chartbook.toml: [charts.repo_rates] path: not built yet: /work/repo/_output/repo_rates.html
chartbook.toml: [dataframes.repo_public] path: not built yet: /work/repo/_data/repo_public.parquet
chartbook.toml: OK (1 pipeline(s), 1 dataframes, 1 charts, 0 notebooks; 2 outputs are not built yet)
Nothing is built yet: `chartbook run` builds it.
```

```yaml
# .github/workflows/check.yml
- run: pip install chartbook
- run: chartbook run --check
```

**Dependencies.** For each `path` in `[dependencies]`, the check looks for a pipeline there and reads its `chartbook.toml`, nothing more. So a pipeline that depends on `../fed_yield_curve` needs that directory checked out wherever the check runs. A `git` dependency is looked at where `chartbook pin` has fetched it, at the commit `chartbook.lock` names. The check never uses the network: if the dependency has not been fetched on this machine, it says so in a `warning:` line and does not fail. A dependency named by its ID, or a `path` dependency that is there, with no pin in `chartbook.lock` yet draws a `warning:` line too: `chartbook pin` pins its newest snapshot, as the first read of it does, and so does `chartbook run` (the build). A fresh clone is in that state on purpose, and {ref}`pin --check <chartbook-pin>` and `run --frozen` are the gates that fail on it. A `trained_on` that names a pipeline `[dependencies]` does not declare stops the manifest loading, so `check` fails on it.

**IDs that changed.** A pipeline's ID can change, when it gets a git remote or a `[project] id` ({ref}`Pipeline Identity <pipeline-identity>`), and its snapshots are then made under the new one. The check warns, naming what to write, when a catalog's `[pipelines]` key is not what the pipeline in that folder calls itself now (the catalog shows only the snapshots made under the key), and when a dependency named by its ID, with no `commit`, is a pipeline whose folders on this machine all call themselves something else now (the dependency stays at the last snapshot made under the old ID). Its folders are the catalog's own under that ID and those a store on this disk notes its newest snapshots were made in, each only if it is a checkout of the repository those snapshots record; a store at a URL is not read, since the check uses no network, and then nothing is said. It also warns when a pipeline's `[project] repo_url` and its git remote name two repositories, since its ID is then `repo_url`'s, and says what it would be without it.

```console
$ chartbook run --check
chartbook.toml: [dependencies."ftsfr/fed_yield_curve"] path: directory not found: /work/fed_yield_curve
chartbook.toml: [models.rate_forecaster] trained_on: 'crsp:ratingz' names a dataframe that the pipeline 'ftsfr/crsp' does not declare. Its dataframes are: ratings, returns
```

**One file of a set.** A dataframe whose `path` names one file, beside files named the same but for a number or a date, draws a warning that gives the glob that names them all:

```console
$ chartbook run --check
warning: chartbook.toml: [dataframes.transcripts] path: _data/transcripts_2026.parquet may be one file of a set: no asset declares the 12 files beside it named the same but for a number or date (transcripts_2014.parquet … transcripts_2025.parquet). If they are one dataset, write path = "_data/transcripts_*.parquet".
chartbook.toml: OK (1 pipeline(s), 1 dataframes, 0 charts, 0 notebooks)
```

It is meant to say nothing where nothing is wrong, so it asks a lot before it speaks:

- Only the file's own folder is looked at.
- A sibling's name differs from the file's only in its runs of digits (`2026`, `20261027`) or dates with `-` or `_` between their parts (`2026-10`, `2026_10`), each with as many digits in each part: `2026-10` stands beside `2025-12`, not beside `2025` or `2026-9`, and `yields_10y` beside `yields_30y`, not beside `yields_2y`.
- At least one run that differs is a date or a number of two digits or more. `results_v2` beside `results_v1`, or `data.h5` beside `data.h4`, is more often a version or a format than a part, and is passed by; so is `part_1` beside `part_2`.
- A file that a path of the manifest names already, a dataframe's, a model's or a glob's, is not counted, and there must be two or more that no path names.

Where more than one run differs (`transcripts_2026_q4` beside the other quarters of 2024 to 2026), each is a `*` in the glob (`transcripts_*_q*.parquet`). Where a `*` would take in a file that is not one of them, such as `transcripts_sample.parquet`, the glob has a `[0-9]` for each digit instead (`transcripts_[0-9][0-9][0-9][0-9].parquet`). Models are not looked at: a model's path is a file or a folder, never a glob.

The check reads metadata and looks at whether files exist. Of a data file it opens only a built parquet file's own description of its columns, for the warning below of the column pandas makes of an index; it reads no rows, so it says nothing about row counts, nulls or schemas.

**A lockfile the manifest does not ask enough for** is a problem. `chartbook.lock` in the version this ChartBook writes cannot be read by one from before 0.6.0, which says only which version it reads; given a `requires_chartbook` it does not meet, it says what to install. `chartbook pin` raises that line when it writes such a lockfile. A manifest that was put back, or merged from a branch that had not moved, or left by a `chartbook run` (which writes no manifest), is caught here: `[project] requires_chartbook: ">=0.5.0" admits a ChartBook that cannot read chartbook.lock …. Write ">=0.6.0" (\`chartbook pin\` does)`, where the command is named only if it can rewrite the line. A manifest without the key is not held to any version, nor is one whose lockfile git ignores and whose manifest it does not.

**Warnings, not problems.** Nothing said with `warning:` fails the command. Besides those about IDs that changed (above), these are: a recommended field that is missing when no policy is given, a task that says `chartbook run` in a pipeline with no build command (where `chartbook run` only renders the site, as it did), a `git` dependency that has not been fetched here, a `path` dependency whose folder is not on this machine and whose pins are all in the store, a `path` dependency in another git repository than the pipeline's own, or in none (it works on this machine only, and the message gives the entry that names it by its ID), a dependency that has no pin yet, a `chartbook.lock` this version cannot read (no dependency is then said to be unpinned on its account), a model label whose version is not on this machine (it may be in the store of the machine that made it), a model that is out of date, trained on inputs that have since moved (`chartbook run` retrains it), a dataframe's path that names one file of a set (above), and a dataframe whose file has the column pandas makes of an index with no name, `__index_level_0__`: where it holds row positions, they shift when a pull has more rows, and no rebuild then has the rows a pin of it names (`to_parquet(index=False)` drops it; `reset_index()` keeps it as a column with a name).

**Trust.** The check reads and runs nothing, so it works in any folder, trusted or not. When the folder is not trusted to run ({ref}`chartbook trust <chartbook-trust>`), its last line says so, and what `run` and `docs` would do there, and names the command.

## chartbook index

```console
chartbook index diff BEFORE AFTER [--json] [OPTIONS] [--exit-code]
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

A changed record is described in a reviewer's words: *data changed* (a content or definition hash, a size, a row count, columns or files; a chart or a notebook says *rendered differently*, since each is a rendering of its dataframes), *pins moved* (a dependency's pinned hash, on a pipeline; or a model's pinned inputs), *dependencies changed* (a dependency added, removed or relocated without a pin moving), *N new version(s)* and *N version(s) gone*, *labels moved*, *out of date* or *up to date again*, *scores changed*, *trained on other data*, *assets changed*, *inputs changed*, *moved*, *write-up changed*, *data reaches further* or *less far* (a dated dataframe's last date), *source changed* (a pipeline's code, write-ups or manifest were committed), and *declared differently* with the fields, for what the manifest declares. Under the line: the hashes and row counts, the columns added or gone, the versions new or gone, and the inputs out of date, whole. A different `root` or `schema` between the two files is said first: they may not be the same site, or not written the same way. `--json` prints the same as JSON, each changed field with its value before and after, for a script or a bot that comments on a pull request. `--exit-code` exits `1` when the two differ, as `git diff --exit-code` does, so CI can ask "did this change what the site says?". This is the first reader of the index ({design}`index-schema`, "What this unblocks").

**Across a commit, a pipeline always says *source changed*:** its `code_changed_at` moves with every commit that touches `src`, `docs_src` or the manifest, so `--exit-code` is `1` for any two builds on either side of one. That is a fact; read it as such.

**Two things that look like changes and are not.** A chart file that Plotly writes without a fixed `div_id` has a fresh id in it on every render, so its hash moves with nothing changed; pass `div_id=` to `write_html` (the examples and the template do; ChartBook's own plotting helpers always do). An executed notebook's HTML carries ids and times from the run, and moves on every render; read *rendered differently* on a notebook as the run, not the data. And a model's `versions`, `trained_with` and `stale_inputs` are read from the store of the machine that built the index, so two indexes from two machines differ in them for no change.

(chartbook-store)=
## chartbook store

The store keeps files under the hash of what is in them. It is a folder on this machine, a folder machines share (on a shared disk, or synced by a service such as Google Drive). A store in a bucket is not available in ChartBook 0.6.0: it has not been brought to this version's layout yet ({doc}`../roadmap`), and a command that meets one says so. It is where `chartbook snapshot` puts what a pipeline built, and where `chartbook pin` finds it.

It is at `~/.chartbook/store/`. To put it somewhere else, set `CHARTBOOK_STORE`, or add this to `~/.chartbook/settings.toml`, or to the organization's settings file (`/etc/chartbook/settings.toml`, or the file `CHARTBOOK_SYSTEM_SETTINGS` names), which every user on the machine shares and the user's file overrides:

```toml
[store]
url = "/a/bigger/disk/chartbook-store"
```

`chartbook store info` says which one this machine uses, and what set it.

**What is in the folder.** `snapshots/` holds one folder for each pipeline, and in it one folder for each snapshot, complete: every file of that version, in its own place. `_chartbook/` holds ChartBook's own notes (of the lockfiles that pin what is here, of the folders snapshots were made from, and what is being written). `store.json` says which layout this is, and `README.txt` says all of this to whoever opens the folder.

**A store that ChartBook 0.5 laid out** has `pipelines/` at the top, and keeps each file once. This ChartBook reads it as it is: `chartbook pin`, `chartbook pin --update`, every read, the catalog, `store ls`, `store info` and `store verify` work in it, and the notes of lockfiles are written where it keeps them. It makes no snapshot in it and removes nothing from it. `chartbook snapshot`, `chartbook run --snapshot`, `chartbook store gc`, and a `store move` or `store import` that would write to it or remove from it, stop and say:

```text
The store at /Users/x/.chartbook/store has the layout of ChartBook 0.5, which this ChartBook reads and does not write. `chartbook store migrate` moves it to this version's; an earlier ChartBook will not read it afterwards.
```

A plain `chartbook run` there builds as usual, and its last lines say why there is no snapshot. `chartbook run --snapshot` stops before it builds, and its message ends `Nothing was built.`

A folder with no `store.json` in which `pipelines/` holds a snapshot's folder, or `roots/` the note of a lockfile, is taken for such a store whose `store.json` has not arrived yet (a sync brings folders before files): it is read as one, a pin's note is written where 0.5 kept them, and no store is made over it. A command that would write data to it stops with a message of its own, which says what was found and the way out:

```text
The store at /shared/store has no store.json, and holds a roots/ folder with notes in it: what a store of ChartBook 0.5 holds, whose store.json may not have arrived yet (a sync that has not finished). Until it has, the folder is read as that store, and no data is written to it or removed from it. If it is no store of ChartBook 0.5 any more, remove roots/ from it and try again. If it is one whose store.json is lost for good, put one back that holds {"schema": "chartbook/store/v2"}.
```

A folder with both layouts in it is neither read nor written: a `store.json` that says this version's layout over a `pipelines/` folder with snapshots in it, or one that says the layout of 0.5 over a `snapshots/` folder with snapshots in it, most likely a store of 0.5 that this version wrote into before its `store.json` had arrived; or no `store.json` at all, and snapshots under both `pipelines/` and `snapshots/`, which read as either would pass the other's over. Every command that reads the store says so, and how to part the two, the store of 0.5 staying where every machine expects it: move `snapshots/` and `_chartbook/` out into a folder of their own, beside a `store.json` that holds `{"schema": "chartbook/store/v3"}`, and see that the `store.json` left behind holds `{"schema": "chartbook/store/v2"}`.

**A store a team shares.** Point every machine's `[store] url` (or `CHARTBOOK_STORE`) at one folder on a shared disk or in a synced folder ({doc}`configuration` says what to know about a sync service), and a snapshot made on one machine is there for all of them: a colleague, or CI, runs `chartbook pin` and gets the bytes the lockfile names, with no build of their own. A dependency named by its ID (`"acme/rates" = {}`) is pinned and updated from the store alone, with no folder of it on that machine. A snapshot is always the store's own bytes (a copy-on-write clone or a copy, never a link to a file on someone's machine), so this works across machines. The folder may be read-only for everyone but its owner: pinning a `path` dependency from a snapshot writes nothing in the store but the note for `store gc`, and `pin` says when it could not leave it. Make `_chartbook/roots/` writable for everyone (`roots/` in a store that ChartBook 0.5 laid out; for a bucket, `s3:PutObject` on `<prefix>/roots/*`) and the notes get through. What does have to write the store says so and stops: a `git` dependency's first pin and `chartbook snapshot` both put files in. `chartbook run --frozen` writes nothing but, where it can, this machine's note for `store gc`, and is what CI should run to build; `chartbook pin --check` checks, and writes nothing to the project or the store. Under CI with no `CHARTBOOK_MACHINE_ID`, every note names the lockfile's path alone, so each run at the same checkout path replaces the last one's. Each machine's notes are its own (they name the machine, from `~/.chartbook/machine-id`, as well as the lockfile's path, since two machines can have a project at the same path), and `store gc` keeps what another machine's lockfiles recorded at their last pin. It is best run by the store's owner, from the machine the snapshots were made on: a label another machine gave is known here only through the snapshots that recorded it.

### store info

```console
chartbook store info
```

Say which store this machine uses, what kind it is, what set it, and where the cache is. Run it on each machine that is to share a store, to see that they name the same folder.

```console
$ chartbook store info
Store: /Users/x/Google Drive/chartbook-store
  a folder, set by [store] url in /Users/x/.chartbook/settings.toml, your settings
Cache: /Users/x/.chartbook/cache
  where what is read from a remote store is kept on this machine
```

What set it is one of: `CHARTBOOK_STORE`; `[store] url` in your settings file; `[store] url` in the organization's settings file; or the default, `~/.chartbook/store`. A folder that does not exist yet is said (`nothing is there yet`): the first snapshot or pin makes it. The kind is a folder, or a `scheme://` store a plugin provides, and the command makes sure this machine can use one of that kind: a scheme nothing installed provides is an error here, and exits `1`, rather than at the first pin or read. So is a store in an S3 bucket, which is not available in ChartBook 0.6.0: the command names the store and says the one line every command says of it.

`--store NAME` shows just that catalog store. Without it, every store is shown, including read-only and unreachable stores.

### store ls

```console
chartbook store ls [PIPELINE] [--store NAME]
```

List the snapshots in the store, one line each, newest last within its pipeline: the folder's name (when it was made and the commit), that it is **complete**, and how much its folder holds.

```console
$ chartbook store ls acme/news_headlines
acme/news_headlines (3 snapshot(s))
  2026-05-01T120000Z_a1b2c3d4e5f6  2026-05-01 12:00 UTC  a1b2c3d  complete   2.1 GB here
  2026-06-01T120000Z_e5f6a7b8c9d0  2026-06-01 12:00 UTC  e5f6a7b  complete   2.4 GB here
  2026-07-01T120000Z_c9d0e1f2a3b4  2026-07-01 12:00 UTC  c9d0e1f  complete   2.7 GB here
A complete snapshot's folder holds every file of its version, and can be read or copied as it is. Remove snapshots with `chartbook store gc`, never by hand.
```

Every snapshot is a complete version: its record, `_chartbook/snapshot.json`, lists every file of every asset, and its folder holds every one of them, each in its own place, so the folder can be read, copied or sent as it is. A dataset costs its whole size at each snapshot. A snapshot's folder is not to be deleted by hand, since a lockfile may pin it: `chartbook store gc` removes snapshots, each with its whole folder. A `README.txt` at the top of the store, and one in each pipeline's folder, say the same, for whoever finds the folder.

A snapshot is listed as **complete** where its folder holds every file of its version, and as an **increment** where it holds the files that the complete snapshot it builds on does not have, with how many of its files are in that one's folder and which it is. A store that ChartBook 0.5 laid out, and a bucket, keep each file once, usually in the first snapshot that had it: there an increment's other files may be in several snapshots' folders.

`PIPELINE` lists one pipeline's snapshots; `--store NAME` one named catalog store, said to be unreachable when it is. A snapshot a pin made from a clone of a `git` dependency, which is not one its owner made, is marked as such. A store of a kind that keeps no folders (a plugin's) is passed over.

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

In a folder store each snapshot is checked for itself. Every file its record names is read in the snapshot's own folder, and every one that is missing there, or has other bytes, is said with the snapshot's name, a snapshot's files together, though another snapshot has the same bytes:

```console
$ chartbook store verify
sha256:9a41c7e2…: _data/parts/year=2020/part-0.parquet is not in the store (the snapshot 2026-11-19T140200Z_4f2a91c0e1b2)
sha256:9a41c7e2…: _data/parts/year=2021/part-0.parquet is not in the store (the snapshot 2026-11-19T140200Z_4f2a91c0e1b2)

1 of 14 object(s) in /Users/x/.chartbook/store are not what their names say.
```

Nothing puts a file back into a snapshot: its folder is not changed once its record is written. A read of it is handed the copy in the newest snapshot of its pipeline that holds the asset whole (never another pipeline's copy, whatever its bytes), and `store gc` removes no snapshot of that pipeline while a snapshot that stays lacks a file. A `chartbook run` that would otherwise say `No new snapshot` of the one with the hole stands on the newest whole snapshot of the same files, and only where none is whole makes a new one and says which file the other lacks. A run that writes to several stores stands on a snapshot only where each of them that has it has it whole, and otherwise makes a new one, whole in each, naming the store and the file the other lacks. `store move`, `store import` and a snapshot sent to several stores read and hash a store's own snapshot of the same moment before they take it to be there: one that is not whole is named with its store and its file, nothing is written over it, and nothing is removed from where it came from.

**Why an object can change.** The store never moves or copies a file if it can avoid it. It tries four ways to hold one, cheapest first:

| Way | Cost | Can it change after it is stored? |
|-----|------|-----------------------------------|
| reflink (a copy-on-write clone; APFS, btrfs, XFS) | free | No |
| hardlink (a second name for the same file) | free | Yes, if the original is rewritten in place. Not if it is replaced by a new file |
| symlink (a pointer to the file) | free | Yes, whenever the original changes. It breaks if the original is moved |
| copy | the file's size | No |

`chartbook pin` asks for the first or the last of these only, so a pin is always frozen. The two in the middle are there for what is cheap to make again, a build cache, which is not built yet. `verify` is how you find out that an object has changed. It reads every byte, so on a large store it takes a while.

(chartbook-store-gc)=
`--store NAME` selects one catalog store. Verification and garbage collection visit every store by default, each using its own retention notes.

### store gc

```console
chartbook store gc [--dry-run] [--yes] [--forget-missing] [--keep-days DAYS] [--keep-lineage] [OPTIONS] [--aggressive]
```

Remove from the store what nothing needs any more: old snapshots, and the objects that only they, or a pin that has since moved, named.

The store is shared by all your projects. Two things keep what is in it. Every `chartbook pin` and `chartbook pin --update`, and, where the store can be written, every `--frozen` and every read through a lockfile, notes its lockfile in the store with what it pins (its objects and its snapshots), and `gc` keeps whatever those notes and lockfiles name. And every {ref}`snapshot <chartbook-snapshot>` keeps what it names, for as long as the snapshot is kept.

**Which snapshots are kept.** A snapshot is kept if any of these holds:

| Kept because | Example |
|---|---|
| A lockfile pins it | `rate_forecast` is pinned to it |
| A lockfile pins a model version in it by its label | `rate_forecast` pins `rates:model/m@champion`, and this is the newest snapshot of `rates` holding that version, which the snapshot `rate_forecast` is pinned to may not hold. The lockfile's note records it, so another machine's lockfile keeps it too |
| It is the newest of its pipeline, from its repository | The last build of `yield_curve` that was declared ready; a copy of the project that gives itself the same ID keeps its own newest |
| It is the newest a branch or tag can pin from (not with `--aggressive`) | The last one on its `release` branch, or at its `v1.0` tag |
| A label points at a model version in it (not with `--aggressive`) | `champion = "7f3a9c2e41b0"` in that pipeline's `chartbook.toml`, read from its folder or as its newest snapshot recorded |
| It says which repository the kept snapshots are of: the newest that names an address and first commit together, where the kept ones would otherwise look like two repositories or one of them is from a clone with a path remote; or those that name its repository, where a kept one names none | The main checkout's last snapshot, which tells a shallow clone's and an agent's clone's snapshots are one repository |
| It is the newest holding a version of an asset marked `keep = true` (with `--aggressive` too) | Every version `acme/docs` ever built of `embeddings`, the output of a paid API run ({doc}`../guide/keeping-costly-outputs`). The command says what the marks keep: `Kept for \`keep = true\`: 3 version(s) of acme/docs:embeddings, 4.2 GB, in 3 snapshot(s)` |
| It was made in the last 7 days | `--keep-days` changes the number |
| With `--keep-lineage`: a snapshot kept for any of these was made from it, or from a label pointing at a version in it, and so on up | The `fred` snapshot that a pinned `rates` snapshot was made from: `chartbook lineage` walks to it |
| A snapshot of its pipeline that stays has lost a file | Each snapshot's folder holds its own copy of every file, and the newest snapshot of `rates` lacks its `treasury.parquet` (a sync that has not brought it, a file removed by hand). No snapshot of `rates` is removed meanwhile: a read of the one with the hole is handed the copy in another snapshot of `rates` |

Everything else may be removed. So a nightly `chartbook run --snapshot` leaves, after a while, the last week of snapshots, the ones somebody pins, and the ones a tag or a label names.

Where a snapshot that stays lacks a file of its own, `gc` says which, why that snapshot stays, and what to do:

```text
Nothing of acme/rates is removed: its snapshot 2026-11-19T140200Z_4f2a91c0e1b2 lacks _data/treasury.parquet, and stays because it is the newest of its pipeline.
  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists everything missing. If it is lost for good, that snapshot goes once a newer snapshot of its pipeline is made (`chartbook run` in its folder) and nothing else keeps it.
```

A snapshot that is itself to be removed holds nothing back, whatever it has lost, and the same bytes in another pipeline never count.

It lists what it would remove and asks before removing anything:

```console
$ chartbook store gc
Kept: 14 object(s), named by 3 lockfile(s) or a kept snapshot
  /work/crsp_treasury/chartbook.lock
  /work/rate_forecast/chartbook.lock
  /Volumes/usb/old_project/chartbook.lock  (not found; its pins are kept)
Kept: 4 snapshot(s), naming 9 object(s): 1 because a lockfile pins it, 2 because it is the newest of its pipeline, 1 because it was made in the last 7 days
Would remove 6 snapshot(s) and 5 object(s) that nothing names, 2.1 GB:
  ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: nothing pins it, it is not the newest, and it is older than 7 days
  …
Remove them? [y/N]: y
Removed 6 snapshot(s) and 5 object(s), 2.1 GB.
```

The size before the question is of everything that would go: the objects that nothing names, and each removed snapshot's own copy of a file that a kept snapshot has too. With no snapshot to remove the line is `Would remove 5 object(s), 2.1 GB, that nothing names.` The last line says what was removed and freed, after a line for each thing that was kept after all, with why: `Kept after all: ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: a lockfile pins it`. A snapshot that `chartbook pin` made from a repository is listed, asked about and counted with the rest (`Would remove 1 snapshot(s) a pin made from a repository and 1 object(s) that nothing names, 4.1 KB:`). Before a snapshot that holds an asset a lockfile pins goes, the copy of that asset in the snapshot of its pipeline that stays is read and hashed, in the dry run too: where it has other bytes than its record says, nothing of that pipeline goes, and the lines above say which snapshot and which file.

| Option | Effect |
|--------|--------|
| `--dry-run` | List each snapshot and object that would be removed, with sizes, and remove nothing |
| `--yes`, `-y` | Do not ask |
| `--forget-missing` | Stop keeping the pins of a lockfile on this machine that cannot be found. Another machine's lockfiles are never forgotten from here |
| `--keep-days DAYS` | Keep an unpinned snapshot that is not the newest of its pipeline for this long. Default 7 |
| `--keep-lineage` | Also keep every snapshot a kept snapshot was made from, as far up as it goes, so that `chartbook lineage` finds them all. By default a store keeps what work needs now and lets old lineage go |
| `--aggressive` | Let names keep nothing: no snapshot is kept for a git tag or branch, or for a model label. What a lockfile pins (by its moment, or a version by its label), the newest of each pipeline, every version of an asset marked `keep = true`, what keeps a repository's snapshots one, and the last `--keep-days` days are still kept; `--keep-days 0` leaves only the first four |

What it is careful about:

- **It looks again when you say yes.** The list is made before the question, and a `chartbook pin` can land while you decide. Whatever became pinned in between is kept, and the command says so.
- **A snapshot's branches are read from the folder it was made from; its labels from there and from the snapshots themselves.** The store notes that folder beside each pipeline's snapshots, and each snapshot records the labels its manifest had when it was made. If the folder is gone (a deleted project, a throwaway checkout, another machine's), the labels the newest snapshot recorded still count, so a label given on one machine keeps its version on another once a snapshot follows it, and a label taken away releases it once a snapshot follows that; nothing is known about branches, and the other rules apply.
- **A lockfile it cannot find still keeps its pins.** The project may be on a drive that is not plugged in. The store remembers what that lockfile named when it was last pinned, and keeps it until you pass `--forget-missing`.
- **Another machine's lockfile keeps what it recorded at its last pin.** In a store that machines share, each note names the machine its lockfile is on, and records the objects and the snapshots the lockfile pinned. Each `chartbook pin` and `chartbook pin --update`, and each `--frozen` and read through the lockfile, replaces that machine's note for that lockfile with what the lockfile pins then (a `--frozen` or a read writes nothing when the note says that already). A lockfile at the same path here is another file, so `gc` keeps what the note recorded and does not open that path. It lists the note as `(on another machine, <its host name>: what it recorded at its last pin is kept; note <store>/_chartbook/roots/<file>)`. `--forget-missing` does not forget it: only that machine can tell that its lockfile is gone, and its own `gc --forget-missing` does. A machine that only reads leaves its note this way where the store can be written; on a store it may only read, `--frozen` says its note could not be written, and `gc` on another machine does not know what it reads. Under CI (the `CI` environment variable set, and no `CHARTBOOK_MACHINE_ID`), `pin`, `pin --update`, `run`, `--frozen` and a read write their note under the lockfile's path alone, with no machine name, as notes were written before they named machines: a runner with a fresh home each run would otherwise have a new name, and leave a note under each. So each run at the same checkout path replaces the last one's note, and `gc` on a runner whose store lasts reads its lockfile and keeps what it pins.
- **Which machine is which.** A machine is named by a random name made once and kept in `~/.chartbook/machine-id`, beside what the operating system calls the machine (`/etc/machine-id`, `MachineGuid`, the hardware's UUID; the host name where there is none), so a home folder copied to another machine (by a migration, a restored backup, or a sync service) gets a name of its own there. Machines are told apart by that identity, or by `CHARTBOOK_MACHINE_ID`, and by nothing else: a note records the host name and a hardware address for you to read, and nothing goes by them, since one machine's may change. So a clone that kept the operating system's identity (a virtual machine cloned without a new `/etc/machine-id`, or Windows without sysprep; an image with one baked in), with a copied home, is not told apart from the machine it was cloned from: the two share a name and one note per path. Each machine that lasts needs an identity of its own, or a `CHARTBOOK_MACHINE_ID` of its own. Never copy `machine-id` between machines, and never keep `~/.chartbook` itself in a synced folder. `CHARTBOOK_MACHINE_ID` also names a machine that comes and goes with a fresh home folder (a CI runner that pins, a container): give each run the same one, and check its project out at the same path, so that each run's note replaces the last one's rather than piling up.
- **Old notes and copies.** In your own store, under `~/.chartbook` (the default one), a note from before notes named their machine can only be this machine's. Its lockfile is read alone, as it was before notes named their machine, and what the note recorded keeps nothing more. The next `chartbook pin`, `chartbook pin --update`, `--frozen` or read through that lockfile writes this machine's note and removes the old one; `gc` removes an old note once this machine has a note of the same lockfile and that lockfile is read here (while it cannot be found, a drive unplugged, what the old note recorded is kept), or, with `--forget-missing`, once the lockfile is gone, and names its file under `_chartbook/roots/` on the lockfile's line. A CI runner with no `CHARTBOOK_MACHINE_ID` writes its notes this way, under the path alone, and its own pins and reads replace such a note rather than remove it. In any other store, such a note, and a sync service's copy of a note (`<name> (1).json`) in any store, may be any machine's: what they recorded is kept, and nothing removes them for you, since nothing can tell whose they are. A note from before notes recorded snapshots keeps, of the snapshots holding each object it names, the newest. A note or a copy that cannot be read (half synced) stops `gc`, which names it and says what to do. To let go of a machine that is no longer used, or of an old note or a copy, remove its file from `_chartbook/roots/` in the store; `gc` names each file, and each is JSON naming its `lockfile`, `machine` and `host`.
- **Only a lockfile on this machine is read.** The store's note for each lockfile is written by whoever can write to the store, so `gc` reads only an absolute path named `chartbook.lock` that is not a network path. Any other (a project on a network drive among them) is not read: the pins its note records are kept, `--forget-missing` included, and `gc` says it did not read it.
- **An object stored in the last hour is never removed, but what only a removed snapshot holds.** A pin puts files in the store before it writes the lockfile that names them, so an object no pipeline owns, and one a snapshot that stays holds, are spared for an hour. What only the removed snapshots hold goes with their folders, new or not: a snapshot's folder goes whole. (In a bucket, which keeps each file once, the run that removes a snapshot's record may leave its objects for the next run.)
- **If a lockfile, a note or a snapshot's record cannot be read, nothing is removed.** `gc` stops, says which, and says what to do. In a store a sync service keeps, a file can be there before its bytes (empty, or cut short), and that is the likeliest cause: run `gc` again once the sync has finished. A note or a record that stays unreadable is removed by hand: a note is written again by the next `chartbook pin`, `chartbook pin --update`, `--frozen` or read through its lockfile, and a record is one snapshot's, which the store then has no more.
- **What it cannot remove is said, and the rest goes.** In a store users share, an object or a record another user put there sits in a folder of theirs that you may not write. `gc` removes everything else in the plan, prints what it removed, lists each thing it could not remove with its path and what to do (its owner removes it, with `chartbook store gc` there or by hand, or gives you write permission on it and on the folder holding it), and exits `1`. What a record that stayed names stays with it, and an object that stayed is in the next run's list.

A note only ever adds to what is kept. A lockfile on this machine is read as it is now, and what its note recorded at its last pin (the objects, and the snapshots) is kept as well: check out an older commit and run `gc` without pinning, and the pins of the commit you left are kept, by the note, until the next `chartbook pin`, `chartbook pin --update`, `--frozen` or read writes it again (a read, or `--frozen`, on the older commit writes it too, with that commit's pins). A note from before notes named their machine, in your own store, is read as it was then: its lockfile alone.



`--store NAME` selects one catalog store. Verification and garbage collection visit every store by default, each using its own retention notes.

### store export

```console
chartbook store export PIPELINE --to FOLDER [--latest | --snapshot COMMIT[OPTIONS] [@MADE_AT] ...]
```

Write one pipeline's snapshots into a folder, to send to a collaborator. The folder is laid out as
a store is, `FOLDER/snapshots/<pipeline>/`: a folder for each snapshot, complete, the pipeline's
files at their own paths, and each snapshot's record. Every snapshot the pipeline's owner
made is written; with `--latest`, the newest alone; with `--snapshot`, each one named,
by its commit (or its start) and, where one commit has several, `@` and when it was made. Each is
readable without ChartBook. Only what
a snapshot's record names goes: its data, its documents and its index, never anything that runs.
A folder that holds an export or a store of ChartBook 0.5 is not added to: export into another.

With several stores in the catalog, the one that holds the pipeline is used, and `--store NAME` chooses when more than one does.

### store import

```console
chartbook store import FOLDER
```

Copy the snapshots a folder holds into this machine's store: what `chartbook store export` wrote,
a store, or one pipeline's folder copied by hand out of one. They go in oldest first, each file
hashed as it is copied and checked against its record: a snapshot with a file that is not what its
record says is refused, said, and the rest go in. Each snapshot is written complete, a snapshot
the store has already is left as it is, and nothing is written over. An export or a pipeline's
folder that ChartBook 0.5 wrote (`pipelines/<pipeline>/`, each file once) is taken in too, each of
its snapshots written complete. A pipeline then
pins them by the pipeline's ID, as `"acme/rates" = {}` in `[dependencies]`, with `chartbook pin`
and `chartbook pin --update`.

```console
$ chartbook store import ~/Downloads/for-bob
acme/rates at 4f2a91c, made 2026-10-01T10:00:00.000000Z
acme/rates at 9b1e22d, made 2026-10-02T10:00:00.000000Z
Imported 2 snapshot(s), 2.1 GB copied.
```

`--store NAME` selects one catalog store; with several stores in the catalog it is required.

### store migrate

```console
chartbook store migrate [--dry-run] [OPTIONS] [--yes]
```

Move a store to this version's layout, once, on one machine.

**A store that ChartBook 0.5 laid out** (`pipelines/` at its top) is read by this ChartBook as it is and not written (above). This moves it. In each pipeline the newest snapshot its owner made becomes complete under `snapshots/`; every other one its owner made becomes an increment on it under `increments/`, keeping in its own folder only the files that one does not have; and a snapshot that `chartbook pin` made from a repository becomes complete. Files change folder by a rename inside the store and are not read, so a store in a synced folder uploads nothing again; only a file that two folders must each hold is copied, and hashed as it is written. A snapshot's record is rewritten only where it says how the store keeps it. `roots/`, `origins/` and `tmp/` go under `_chartbook/`. Last, what is left of `pipelines/` (the old records, the notes, every file no record names, anything that arrived meanwhile) is moved aside in one rename, to `_chartbook/left-by-0.5/pipelines`: the move removes nothing but its own journal, and that folder may be removed once the move has been checked.

The move never renames a file onto one that is there. Where a file is already at the place a record's file goes (a move on another machine half arrived, a sync put a file back), what is in place stays and the file at the old place goes aside with the old folder; the dry run and the last lines count such files and name the first few, with both sizes where they differ, and `chartbook store verify` says whether what is in place is right. It does not stop the move.

`--dry-run` says what would happen, in counts and sizes, and moves nothing. The command says the same, and then, before it asks: nothing else may use the store while it runs, on this machine or another; afterwards every machine that uses it needs this ChartBook, and an earlier one will not read it; and in a synced folder the sync must finish before another machine uses the store. So upgrade ChartBook on every machine first, run this on one of them, and let the sync finish.

Whatever was true before a move and would stop it half way is found before anything moves, and said with its way out: a record that cannot be followed (one that names a file outside its pipeline's folder among them), a folder with files and no record yet, a snapshot being made, a `store.json` that says neither layout, a folder this user may not write, a folder that is a link, a file or a link where the move makes a folder, two names the disk does not tell apart, too little room for the copies, and a path that would be too long. A file a record names that is missing does not stop it: it was so before, it is counted and named by the dry run and again by the last lines, and its record goes on naming it; nor does a file to be copied whose bytes are not what its record says, which is copied as it is and named in the last lines. A `README.txt` a person wrote at the top is moved aside, not replaced.

The folders are the truth: every plan is made from the store as it is, so a move cut short goes on by running the command again, whatever became of its journal. The journal (`_chartbook/move-to-v3.jsonl`) only says that a move is under way and which machine began it. While it is there every other command on that store stops with one line that says so; one another machine began stops this one's move, and says how to take the move over if that machine cannot finish; one that cannot be read stops the command, with the way out (wait for a sync, or remove it and run again). With the journal gone, a store whose `store.json` still says 0.5 while it has folders of this layout is refused by every other command, which says to wait for a sync that may still be bringing a move and then to run this one: what a move renamed is under the new folders and nowhere else, so nothing says to take them out of the store. And the snapshot the others build on does not change once a move has begun: one that a machine still on 0.5 makes while a move is cut short becomes an increment on it, like any other.

The command can always be run again on a moved store, and is the one remedy where a machine that had not been brought the move wrote `pipelines/`, `roots/`, `origins/` or `tmp/` at its top afterwards: every other command refuses such a store and names this one. It merges the notes under `_chartbook/`: one the store has stays and the late one goes aside, but of two notes of one lockfile the store keeps the later, and the other goes aside first. And it moves `pipelines/` aside, whole: nothing under it is moved in, an object no pipeline owns neither, and the last lines name each snapshot there, to be made again with this ChartBook, and each file that arrived for a snapshot already moved, with where it is.

**A store made by ChartBook 0.2** is moved to the layout of 0.3 to 0.5 first, as before ({design}`plan-0.3.0`): a folder for each pipeline, a folder for each snapshot, each file once under its own name. Run the command again to move that one on.

- **Upgrade every machine first.** A machine still on ChartBook 0.2 cannot read the store once it
  is moved, and says so. Run this on one machine; in a store a sync service keeps, the others wait
  for the sync.
- **Files are moved, not copied,** so a store in a synced folder uploads nothing again. Bytes two
  pipelines' snapshots share are copied for the second. The files of a glob, whose records give no
  hash for each file, are read once to hash them; in a folder that streams its files, as Google
  Drive's does, that downloads them. `--dry-run` says how much.
- **Cut short, it goes on.** What is moved is noted before it is moved, and running it again goes
  on where it stopped.
- **What no snapshot names**, a `git` dependency's pins in 0.2, goes to `pipelines/+unowned/`,
  where it is kept while a lockfile names it.
- **A store in a bucket** is not moved: it is not available in ChartBook 0.6.0 (see the
  {doc}`roadmap <../roadmap>`), and a command that meets one stops and says so.

```console
$ chartbook store migrate --dry-run
The store at /Volumes/GoogleDrive/My Drive/chartbook_store has the layout of ChartBook 0.2.
Would move 14 snapshot(s) of 14 into their pipelines' folders, from 61 object(s), 2.3 GB.
2.0 GB of globs and documents is read once, to hash each file.
Nothing was moved (--dry-run).
```

`--store NAME` selects one catalog store; with several stores in the catalog it is required.

### store add

```console
chartbook store add NAME URL [OPTIONS]
```

Read a store and add it to `catalog.toml`. `--pipelines ID` may be repeated to route new snapshots there. `--read-only` prevents writes. `--catalog PATH` selects the catalog. Comments are preserved and duplicate locations are refused.

### store remove

```console
chartbook store remove NAME [OPTIONS]
```

Remove a store definition, leaving its files untouched. `--catalog PATH` selects the catalog.

### store move

```console
chartbook store move PIPELINE --to NAME [OPTIONS]
```

Copy every snapshot to `--to NAME`, checking hashes and copying retention and origin notes before removing source snapshots. Once the copies are verified, the moved pipeline's files are removed from each source, as `store gc` would, and no other pipeline's folder is looked in; a source that refuses a removal is reported after routing, saying the snapshots moved and which files stayed. Two names for one store (a folder in another letter case, or reached through a link) are refused before anything is touched. `--dry-run` reports the count and bytes. `--keep` keeps the source copies; `--no-route` leaves catalog routing unchanged. Otherwise future snapshots are routed to the destination. Previously resolved paths may disappear; resolve them again.

## chartbook config

Interactively set the default catalog path (stored as `catalog.path` in `~/.chartbook/settings.toml`). This is what `data.load()`, `chartbook ls`, `chartbook data`, and the `catalog` commands use when no explicit `--catalog`/`catalog_path` is given. With nothing set, they use `~/.chartbook/catalog.toml`, made over the machine's store the first time one of them needs it ({ref}`chartbook catalog <chartbook-catalog>`).

```console
chartbook config
```

(chartbook-install-agents)=
## chartbook install agents

Set a project up for coding agents, in one command. It has two halves:

1. It installs the Claude Code skill for you, as {ref}`chartbook install claude-skill <chartbook-install-claude-skill>` does.
2. In a pipeline's folder, or a folder below one, it writes a ChartBook section into that project's `AGENTS.md`, which other coding agents read: what the project is, the few commands that matter, and where the whole reference is.

```console
$ chartbook install agents
  SKILL.md
  catalog_system.md
  manifest_files.md

Installed 3 skill file(s) to ~/.claude/skills/chartbook (ChartBook 0.6.0)
Wrote AGENTS.md: a ChartBook section, for the agents that read that file (ChartBook 0.6.0).
```

**The section is ChartBook's, and the rest of the file is yours.** It stands between two marker lines:

```markdown
<!-- chartbook:start version=0.6.0 text=11c60b4e256c; written by `chartbook install agents`, which replaces everything down to chartbook:end. Notes of your own go outside these two lines. -->
## ChartBook
…
<!-- chartbook:end -->
```

Run again after an upgrade, the command replaces what is between them and says so (`Updated the ChartBook section of AGENTS.md from ChartBook 0.5.1 to 0.6.0. The rest of the file is as it was.`). A file the project already has gets the section added at its end, and the rest of it is kept byte for byte: its line endings, a byte-order mark, blank lines at its end. One with none is made. When the section is already this version's, nothing is written. The file is written whole or not at all, and one that is read-only, that has a second name (a hard link), or that something else saved while the command ran is not written: the command says which. Commit `AGENTS.md`: it is for everyone who works in the repository.

- **Nothing a person wrote is replaced unasked.** The opening marker carries the version and a hash of the section (`text=…`: of its two marker lines and the text between them), so a section somebody has written in is told from one that is as ChartBook left it, whatever its version. One that was written in, or that `chartbook install agents` did not write at all (markers typed by hand, no hash), is replaced only when you say so at the question, which says which lines and how many would go (`The ChartBook section of AGENTS.md (lines 12 to 40) was changed since ChartBook 0.6.0 wrote it. … Replace what is between them (27 lines)? [y/N]`), or with `-f`, which is for the skill's files too. Where nothing can ask, the command exits `1` and says that notes of your own go outside the two lines. Blank lines that a formatter puts inside the markers, and spaces after them, are nobody's writing.
- **A newer ChartBook's section is left as it is,** and the command says so: `AGENTS.md` is committed, and two environments on two versions would otherwise take turns at it.
- **A marker is a whole line.** From its first column, the comment and nothing else, and not inside a fenced code block. A line that only mentions one (in a sentence, indented as code, in an example) is the project's own text and is left alone. A marker line with other text after it, and marker lines that do not hold one section (a start with no end, two of either), are an error that says which lines, and nothing is written.
- **A fence is as Markdown takes one.** Three or more backticks or tildes open it, and the same character, at least as many and nothing after, closes it. A file that ends inside one (a fence never closed) is an error that names the line: a section written below it would be part of that code.
- **A file that is a link** is written through to a file of the project that is there (`AGENTS.md` linked to `CLAUDE.md`, say), and stays a link. One that leads outside the project, or to nothing, is an error.
- **Both halves are done.** Where the skill's question is declined or cannot be answered, or its folder cannot be written, the section is still written; the command then exits `1` and says what was left. Ctrl-C at the skill's question ends the command. A skill that is a newer ChartBook's is left as it is, as a newer section is, and that is no error.
- **Outside a project** it installs the skill and says that the `AGENTS.md` half is for a project. A project is the folder you are in, or the nearest above it in the same git repository, that holds a `chartbook.toml`; in no repository, or where the repository is your home folder, only the folder itself. Never the home folder.
- **A section from an older ChartBook** teaches that version's commands. Every other command, run by a person at a terminal, says so in one line, and `chartbook run --check` as a `warning:`, as for a stale skill (below). One that somebody has written in is theirs, and is not said.

(chartbook-install-claude-skill)=
## chartbook install claude-skill

Install the bundled Claude Code skill, giving Claude context about the CLI, the manifest format and the data API. By default it installs **user-level**, into `~/.claude/skills/chartbook/`, or `$CLAUDE_CONFIG_DIR/skills/chartbook/` when that variable is set, so the skill is available in every Claude Code session on your machine. With `--project` it installs into `./.claude/skills/chartbook/` in the current directory, to commit with a repository; a project `chartbook init` makes has one already.

```console
chartbook install claude-skill              # user-level (default)
chartbook install claude-skill --project    # ./.claude/skills/chartbook/: commit it to share with a team
chartbook install claude-skill -f           # overwrite files changed by hand without prompting
```

**Which ChartBook a copy is for.** The skill's `SKILL.md` names the version it was written for, in its front matter:

```yaml
metadata:
  chartbook-version: "0.6.0"
```

A copy for an older version is replaced, and the command says which: `Updated the skill in ~/.claude/skills/chartbook from ChartBook 0.5.1 to 0.6.0`. A copy installed before 0.2.0 says its version only in a `.chartbook-skill-version` file beside it, which is read and then removed; such a copy is older than any skill that names its version, whatever the file says. A copy for a newer version (another environment's ChartBook), or for this version with files changed by hand, is replaced only when you say so, or with `-f`. When the files already match, nothing is copied. Files of older layouts are removed, so the copy mirrors the bundled skill.

**Finding a stale copy.** Every other command, run by a person at a terminal, says in one line on stderr when your copy, or the project's, is for an older ChartBook, and names the command that installs this version's. The project's copy is `.claude/skills/chartbook/` in the working directory or the nearest folder above it, up to the top of its git repository and never the home folder. A script, CI, a command inside a script `chartbook run` is running, or anything reading the output never sees the line, and a copy for a newer ChartBook is not mentioned, so that two environments on two versions do not take turns replacing it. `chartbook run --check` says the same as a `warning:` line, which fails nothing. The command was called `install skill` before 0.2.0, and that spelling says the new name.

(chartbook-link)=
## chartbook link

```console
chartbook link PIPELINE FOLDER [OPTIONS]
```

Use a dependency's built files while developing both pipelines. The command checks the folder's declared ID and writes `chartbook.links.toml` beside the consumer's manifest. `--project-dir PATH` selects that consumer. Paths are relative to it. Delete the line or file to return to pins.

Reads warn once per linked dependency. Pins and updates ignore links and leave the lockfile's identity unchanged. A snapshot refuses while the file exists; remove it, update, then snapshot. Frozen runs and CI ignore links. A tracked links file is a check error. Build indexes record the linked folder, commit, and whether it has uncommitted changes.
