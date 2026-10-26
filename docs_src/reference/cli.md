# CLI Reference

Every command supports `--help`. Everything the CLI needs ships with `pip install chartbook`; see {doc}`../getting-started`.

| Command | Purpose |
|---------|---------|
| `chartbook init` | Scaffold a new pipeline project |
| `chartbook docs generate` | Render the documentation site |
| `chartbook docs open` | Open the rendered site in a browser |
| `chartbook build` | Make everything current: run the build script, then render the site |
| `chartbook check` | Fail CI on missing metadata, broken paths, or expiring licenses |
| `chartbook trust` | Say a pipeline's folder is yours to build, so that a build of it runs as your own |
| `chartbook path` | Print the path the manifest declares for an asset |
| `chartbook publish` | Stage a pipeline's publishable files into a directory |
| `chartbook catalog init/add/disable/enable/generate/open` | Manage a catalog and its site |
| `chartbook ls [pipelines\|dataframes\|charts]` | List cataloged objects |
| `chartbook data get-path/get-docs/get-docs-path` | Look up a dataframe's file or write-up |
| `chartbook create-data-glimpses` | Summarize every dataframe the manifest declares |
| `chartbook snapshot` | Declare this pipeline's build ready for the pipelines that depend on it |
| `chartbook restore` | Put this pipeline's own assets back on disk from its snapshots: a costly output, after a clean or a clone |
| `chartbook add PIPELINE` | Declare a dependency by its ID, read from the store, and pin it |
| `chartbook pin` | Freeze what this pipeline depends on, in `chartbook.lock` |
| `chartbook update` | Move pins forward to each dependency's newest snapshot |
| `chartbook lineage` | Show and check every snapshot upstream of this pipeline |
| `chartbook run [SCRIPT]` | Run a named script in this pipeline; `build` by default, after pinning what it depends on |
| `chartbook store verify` | Check that nothing in the store has changed since it was stored |
| `chartbook store gc` | Remove old snapshots, and from the store what nothing names |
| `chartbook config` | Set the default catalog for data loading |
| `chartbook install claude-skill` | Install the bundled Claude Code skill (user-level by default) |

`chartbook --version` prints the installed version; `chartbook <command> --help` prints a command's options.

## chartbook init

Scaffold a new pipeline from the [cookiecutter template](https://github.com/backofficedev/chartbook/tree/main/template) that came with your ChartBook. It asks 19 questions, each with a default that Enter takes: the project's name and its folder name (made from the name), a description, your name and email, the Python version, how to install the dependencies, and which examples and data sources to include. {doc}`../getting-started` says which answers matter. A folder name that is not lowercase letters, digits and `_`, starting with a lowercase letter, stops it with nothing created, and its last line says what to do at the second question next time: press Enter, or type such a name (the name made from the project's name may not be one, as for `2024 Rates`).

**The template comes with the package**, as `chartbook/template` in the wheel (the files git tracks in the repository's `template/`; in a source checkout, those same files of `template/` beside `src/`), so a project is always made with the template of the ChartBook that makes it, and making it needs no network. It is rendered with cookiecutter, and the project's `.cruft.json` is written as [cruft](https://cruft.github.io/cruft/) writes it: the template's repository on GitHub, its `template` folder, and the commit the template is at (recorded in the package when it is built; asked of git in a source checkout). So `cruft update` and `cruft check` in the project follow the template on GitHub from there. The command says when that commit is in no tag and on no branch of a remote that is the template's repository, in the checkout it runs from, so may not be on GitHub, where `cruft update` looks for it. When the commit is not known (the package recorded none, or the checkout's `template/` has changes git has not committed to tracked files), there is no `.cruft.json`, and the command says why and prints the command that makes one once the commit is known, with the answers you gave: `cruft link https://github.com/backofficedev/chartbook --directory template --checkout <commit> --no-input --extra-context '{…}'`. A source checkout that git cannot read, or a copy of one with no `.git`, is not rendered from, since which files git tracks cannot be told; the command says what to do. Everything rendered can be written by its owner, even from a template installed read-only. A folder of the project's name that is there already stops it, with nothing changed. The project's environment files ask for `chartbook>=` the template's version, which is your ChartBook's; `cruft update` moves it to the template's version then.

The template is the `template/` folder of ChartBook's own repository, so the commands it uses and the commands themselves change together, and a test builds a freshly made project on every change. The new project names its build in `chartbook.toml` (`[scripts] build = "doit"`), so `chartbook build` builds it and renders its site, and before that `chartbook docs generate` renders its site with the example notebook shown as not built. `doit` there runs every task in `dodo.py` but the tests, which are `doit run_pytest`. When the project is made, the command prints the next steps: `chartbook docs generate`, the commands that install its dependencies, then `chartbook build -f`, `chartbook docs open` and `chartbook check`. The new project is recorded as trusted to run, since you made it, and the command says so among the next steps (`Trusted: this folder`); a folder you cloned is not, until {ref}`chartbook trust <chartbook-trust>` says it is. When the record cannot be written (no home folder), the command says so and goes on.

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

The documentation site, as a group of two commands: `chartbook docs generate` renders it, and `chartbook docs open` opens it. Neither builds the project's data: {ref}`chartbook run <chartbook-run>` does that, and {ref}`chartbook build <chartbook-build>` runs the build script and then generates the site. `chartbook docs` on its own lists the two.

### docs generate

```console
chartbook docs generate [OPTIONS] [OUTPUT_DIR]
```

Render the HTML site into `OUTPUT_DIR` (default `./docs`; it cannot be the current working directory itself). Works for both pipelines and catalogs — the project type comes from the manifest. Internals: {doc}`../guide/how-the-build-works`.

It renders the site from what is already built. It does not build the project's data: {ref}`chartbook run <chartbook-run>` does that, and {ref}`chartbook build <chartbook-build>` does both.

**In a folder you have not trusted**, you are asked first when you are at a terminal ({ref}`chartbook trust <chartbook-trust>`, "Asked at a terminal"); elsewhere, and after the answer `r`, the site is rendered as a version from a store is: no query is run (the dataframe's glimpse says why), no template or file from outside the folder is read (a manifest that names one stops the render, naming the entry), and every template runs in Jinja's sandbox. The command says so in a `Warning:` line, and the site is still built. {ref}`chartbook trust <chartbook-trust>` in the folder says the pipeline is yours to build (`--render` to render only); a project `chartbook init` made is trusted already. In a catalog, the catalog's own folder and every member folder on this machine must be trusted, or nothing is built and the error lists them: `chartbook trust --members`.

**Before anything is built.** A lone pipeline that has built none of the data, charts, notebooks and models it declares, as a project just made by `chartbook init` or a fresh clone has not, is rendered all the same, with a warning that lists them:

```text
Warning: rates_study has built nothing it declares yet, so the site shows each as not built:
  - notebook: _output/01_example_notebook_interactive.ipynb
`chartbook build` runs its build script and renders the site again.
With --strict, this is an error.
```

Each of them keeps its record in `index.json`, without a hash, and its provenance panel says "not built". A notebook's page is its title and "Not built yet", with how to build it; a chart's embedded frame and its full-screen link say the same, and so does a dataframe's glimpse, which then has no dates and no download link. A model's page says it only in its provenance panel.

It takes every declared output to be missing. A pipeline that has some of them and not others has been built, so a missing one is an error; a clone of a pipeline that commits some of its outputs to git is such a pipeline. A missing write-up, note or README, which nothing builds, is an error too. And so is a pipeline that has built nothing, when `--strict` is given: after a build that should have made everything, as in CI, run `chartbook docs generate --strict`, or `chartbook build`, which runs the build first and makes no exception. An output that is there and cannot be read is not "not built": the render stops and names it.

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
chartbook docs generate             # the first time
chartbook docs generate -f          # again, over what is there
chartbook docs generate ./site -f   # custom output directory
chartbook docs generate -f --incremental   # rebuild only what changed
chartbook docs generate -f --watch         # ...and keep doing so as you edit
```

**Incremental builds.** A plain `docs generate` starts from nothing every time, which is what you want in CI. `--incremental` keeps the intermediate Sphinx project (`_docs/`) and uses it the next time:

- a pipeline none of whose files changed is not regenerated at all — its `chartbook.toml`, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares are compared by modification time and size;
- a page whose content comes out the same is left untouched, so Sphinx does not read it again;
- if no page changed, Sphinx is not run.

Each build says what it did:

```console
$ chartbook docs generate -f --incremental
Incremental build: regenerated 1 of 40 pipeline(s); 10 source file(s) changed, 0 removed; Sphinx re-read 10 page(s).
```

When a page is added or removed, every page is rendered again — from Sphinx's cache, without re-reading anything — so that navigation stays right and no stale page is left behind. Upgrading ChartBook, Sphinx or a theme, or changing a build option, starts over from nothing. The kept `_docs/` directory ignores itself in git.

Two things an incremental build does not promise, both fixed by one plain `chartbook docs generate`: the "Last updated" date on the front page moves only when that page is rendered again, and a page whose *title* changed keeps its old title in other pages' sidebars until they are next rendered.

**Watch mode.** `--watch` is an incremental build in a loop. It polls the project's files (once a second by default), rebuilds on any change, reports a failed build and carries on. There is no server and nothing to install: open the site with `chartbook docs open` and refresh the page.

### docs open

```console
chartbook docs open [OUTPUT_DIR] [--project-dir PATH]
```

Open the rendered site, `OUTPUT_DIR/index.html` (default `./docs/index.html`), in your default browser. There is no server: the file is opened as it is, and after a rebuild you refresh the page. If there is no site yet, it says to run `chartbook docs generate` first.

(chartbook-build)=
## chartbook build

```console
chartbook build [OPTIONS] [OUTPUT_DIR]
```

Make everything current: run the project's `build` script, then render the site. It is `chartbook run` followed by `chartbook docs generate`, and it takes the arguments of {ref}`chartbook docs generate <chartbook-docs>`.

```console
$ chartbook build -f
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
Successfully generated documentation in /work/rate_forecast/docs
```

| Command | Builds the data | Renders the site |
|---|---|---|
| `chartbook run` | Yes | No |
| `chartbook docs generate` | No | Yes |
| `chartbook build` | Yes | Yes |

- **If the script fails, the site is not rendered**, and the command exits with the script's exit code.
- **After the script has run, a declared file that is missing is an error**, even when none of them is there, which `chartbook docs generate` would show as not built yet: the build has just run and did not make it.
- **With no `build` script** in {ref}`[scripts] <scripts>`, there is nothing to run. It says so and renders the site.
- **A build tool's task that says `chartbook build`**, as a `dodo.py` written for 0.1.1 does to render the site, is run by the build command that `chartbook build` runs first: the site would be rendered twice, and a plain `doit` would run inside itself. When the build command runs doit, make or just and that tool's task file (`dodo.py`, a `Makefile`, a `justfile`) runs `chartbook build` on this pipeline, `chartbook build` stops before building anything, names each such line (a catalog's members' too), and says to write `chartbook docs generate -f` there. A comment, a docstring and `chartbook build --project-dir` of another pipeline do not count; `"chartbook", "build"` as a list does. `chartbook check` reports the same on the `build` field, and warns of such a line where no build command is declared.
- **`--remake`** is {ref}`chartbook run <chartbook-run>`'s: without it, the build stops when an asset marked `keep = true` is not on disk while the store has a version of it, and says `chartbook build --remake` as the way on.
- **In a catalog**, the script is run in each of the catalog's pipelines, and then the catalog's site is rendered.
- **In a folder you have not trusted to run**, you are asked first when you are at a terminal: `y` trusts it and builds, `r` renders the site without running the script, Enter stops ({ref}`chartbook trust <chartbook-trust>`). Where no one is asked, the script is not run: a build script is code, and the command stops, naming the folder and the command that trusts it, {ref}`chartbook trust <chartbook-trust>`. With no `build` script, the site is rendered as `chartbook docs generate` renders an untrusted folder.

```{warning}
**`chartbook build` used to mean what `chartbook docs generate` means now.** A build script that says `chartbook build -f`, as the `dodo.py` of a project made by an older `chartbook init` does, must say `chartbook docs generate -f`, or, better, not render the site at all: `chartbook build` renders it after the script, and the template's `dodo.py` no longer has a task that does.

Until it does: called from inside the build script that `chartbook build` or `chartbook run` is running, `chartbook build` renders the site and prints a warning, so that it does not run the script that called it without end. Called from a build tool you started yourself (plain `doit`), it runs the build script, which is that same tool, a second time.
```

## chartbook check

```console
chartbook check [--project-dir PATH] [--within DAYS] [--policy PATH] [--skip-outputs]
```

The CI gate. Exits `0` on a healthy project and `1` when it finds any of:

- **a missing required field** — a field the policy requires that is absent or empty (with no policy given, the recommended fields are only warnings; see below);
- **a broken path** — a `path`, `docs_path`, `readme`, `logo` or `favicon` pointing at a file that does not exist (or a glob matching nothing);
- **a dependency that cannot be found** — an entry of {ref}`[dependencies] <dependencies>` whose `path` is not a directory with a pipeline's `chartbook.toml` in it, or a model's `trained_on` naming a dataframe that the other pipeline does not declare. A `path` whose folder is not on this machine, and that `chartbook.lock` pins with every pin in the store, is a warning instead (another machine's folder: the pipeline builds here with `run --frozen`), and either way the message gives the entry that names it by its ID;
- **an expiring license** — a dataframe whose `license_expiration` has passed, or falls within `--within` days;
- **a build tool's task that says `chartbook build`** — in the pipeline's `dodo.py`, `Makefile` or `justfile` (the file of the tool its build command runs), as a pipeline written for 0.1.1 has to render its site; reported on the `build` field, since `chartbook build` would run the build command, which runs that task again (see {ref}`chartbook build <chartbook-build>`).

A project whose `[project] requires_chartbook` this ChartBook does not meet is not checked: the command stops first, as every command that acts on the manifest does, and says how to install one that meets it.

Each finding is one line naming the manifest, the table and the field, so a CI log is enough to fix it:

```console
$ chartbook check --policy ../catalog
chartbook.toml: [charts.repo_rates] units: required by the policy in ../catalog, but missing or empty
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

**Which fields are required.** Run in a catalog, `check` applies the catalog's {ref}`[policy.required] <policy>` to every member pipeline. Run in a pipeline, it applies the pipeline's own `[policy]`. To hold a pipeline to the policy of the catalog it is published to, or to a list of your own, pass `--policy`; only the `[policy]` table is read, so the catalog's other pipelines need not be checked out, and it replaces the pipeline's own `[policy]`. A field that a policy requires and that is missing or empty is a problem, and the check fails.

When no policy is given anywhere (no `[policy]` in the pipeline, none in the catalog it is checked in, no `--policy`, or a `--policy` file with no `[policy]` table, as a catalog that sets none), `check` uses the built-in recommended-field lists, the same ones that drive the diagnostics page, as advice only: each missing field is a `warning:` line, and none of them makes the check fail. The one exception is a write-up: a dataframe or chart whose `docs_path` or `docs` is empty fails the check whatever the policy, since the format itself requires one.

```console
$ chartbook check
warning: chartbook.toml: [project] repo_url: recommended by the default policy, but missing or empty
warning: chartbook.toml: [charts.repo_rates] units: recommended by the default policy, but missing or empty
chartbook.toml: OK (1 pipeline(s), 1 dataframes, 1 charts, 0 notebooks)
```

A missing build script is named `[scripts] build`. `[project] build`, the old place, is still read and counts as well, here and for a policy's `project = ["build"]`.

`policy.mode` is not consulted. It decides what a *build* does about missing metadata; `check` always reports it.

**License dates** are ISO dates (`license_expiration = "2026-12-31"`, or a bare TOML date). An empty value, `"N/A"`, `"None"` and `"Never"` mean the license does not expire. Anything else that is not a date is itself reported, because a gate that cannot read a date cannot vouch for it.

**In CI, on a project that has not been built.** Data files, rendered charts and executed notebooks are what a pipeline *produces*, and they are usually not in git. A CI job that checks out the repository without running the pipeline — which is every job for a pipeline whose data needs a subscription — would see all of them as broken paths. `--skip-outputs` leaves those three out and still checks everything that lives in the repository: required fields, license dates, write-ups, notes, the README, the logo. Without it, a lone pipeline that has built none of its outputs (a project `chartbook init` just made, a fresh clone) has each reported as "not built yet" rather than "file not found", with one line on what builds them; the check still fails.

```yaml
# .github/workflows/check.yml
- run: pip install chartbook
- run: chartbook check --skip-outputs
```

**Dependencies.** For each `path` in `[dependencies]`, `check` looks for a pipeline there and reads its `chartbook.toml`, nothing more. So a pipeline that depends on `../fed_yield_curve` needs that directory checked out wherever `check` runs. A `git` dependency is looked at where `chartbook pin` has fetched it, at the commit `chartbook.lock` names. `check` never uses the network: if the dependency has not been fetched on this machine, it says so in a `warning:` line and does not fail. A dependency named by its ID, or a `path` dependency that is there, with no pin in `chartbook.lock` yet draws a `warning:` line too: `chartbook pin` pins its newest snapshot, as the first read of it does, and so does `chartbook run` (the build). A fresh clone is in that state on purpose, and {ref}`--frozen <chartbook-pin>` is the gate that fails on it. A `trained_on` that names a pipeline `[dependencies]` does not declare stops the manifest loading, so `check` fails on it.

**IDs that changed.** A pipeline's ID can change, when it gets a git remote or a `[project] id` ({ref}`Pipeline Identity <pipeline-identity>`), and its snapshots are then made under the new one. `check` warns, naming what to write, when a catalog's `[pipelines]` key is not what the pipeline in that folder calls itself now (the catalog shows only the snapshots made under the key), and when a dependency named by its ID, with no `commit`, is a pipeline whose folders on this machine all call themselves something else now (the dependency stays at the last snapshot made under the old ID). Its folders are the catalog's own under that ID and those a store on this disk notes its newest snapshots were made in, each only if it is a checkout of the repository those snapshots record; a store at a URL is not read, since `check` uses no network, and then nothing is said. It also warns when a pipeline's `[project] repo_url` and its git remote name two repositories, since its ID is then `repo_url`'s, and says what it would be without it.

```console
$ chartbook check
chartbook.toml: [dependencies."ftsfr/fed_yield_curve"] path: directory not found: /work/fed_yield_curve
chartbook.toml: [models.rate_forecaster] trained_on: 'crsp:ratingz' names a dataframe that the pipeline 'ftsfr/crsp' does not declare. Its dataframes are: ratings, returns
```

`check` reads metadata and looks at whether files exist. It never opens a data file, so it says nothing about row counts, nulls or schemas.

**Warnings, not problems.** Seven things are said with `warning:` and do not fail the command: a recommended field that is missing when no policy is given, a task that says `chartbook build` in a pipeline with no build command (where `chartbook build` only renders the site, as it did), a `git` dependency that has not been fetched here, a dependency that has no pin yet, a `chartbook.lock` this version cannot read (no dependency is then said to be unpinned on its account), a model label whose version is not on this machine (it may be in the store of the machine that made it), and a model that is out of date, trained on inputs that have since moved (`chartbook run` retrains it).

**Trust.** `check` reads and runs nothing, so it works in any folder, trusted or not. When the folder is not trusted to run ({ref}`chartbook trust <chartbook-trust>`), its last line says so, and what `build`, `run` and `docs` would do there, and names the command; in a catalog, that is the lowest level among the catalog's folder and its member folders on this machine.

(chartbook-trust)=
## chartbook trust

```console
chartbook trust [PATH] [--render] [--repository] [--members] [--list] [--forget]
```

Say that a pipeline's folder is yours to build. Usually you need not: the first build of a folder asks you, at a terminal (below). A build of a folder you have not trusted, where no one is asked (a script, CI), runs as a build of files from a store does: `chartbook docs generate` renders its site with no query run (the dataframe's glimpse says why) and no template or file from outside the folder, every template in Jinja's sandbox, with a warning that says how to trust it; `chartbook build` and `chartbook run` refuse to run its build script, which is code, naming the folder and this command. A project `chartbook init` made is trusted as it is made. One you cloned is trusted when you say so, here. `chartbook check` is not gated, and its last line says the level when it is not `run`.

**Asked at a terminal.** The first `chartbook build`, `chartbook run` or `chartbook docs generate` of a folder you have not trusted asks, when you are at a terminal:

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

`y` (or `yes`) records the folder at `run`, as `chartbook trust` there would, so the folders inside it too, and nothing asks again; since a later `chartbook build` then runs its build command without asking, `docs generate`'s question shows that command as well. `r` renders the site and runs no build command: a folder not trusted at all renders as a build of files from a store is rendered (a `Warning:` line says so), and one trusted to render renders as it always does. It records nothing, and is offered by `chartbook build` and `docs generate`, which have a site to render, not by `run`. Enter, `n`, end of input and Ctrl-C stop at once, and nothing is run; any other answer is asked again. A folder trusted to render only is asked about running. A catalog asks once, `[y/N]`, listing the catalog's own folder and each member folder this command needs and does not have (for `chartbook build`, a member trusted to render only too), each with its build command; `y` records them all. One command asks once. What the question shows of a folder (its path, ID, repository and build command) is shown plainly: blank lines and runs of space folded, a control or format character written as `<U+202E>`, at most ten lines. No one is asked when stdin or stderr is not a terminal, under `CI`, or in a build `chartbook run` or `chartbook build` is running (`CHARTBOOK_BATCH`, `CHARTBOOK_RUN_DIR`): there the build refuses and `docs generate` renders without the folder's code, as described here, and `chartbook trust` is the way to say it beforehand. `chartbook trust` also does what a question cannot: a parent folder for everything inside it, a repository for every clone of it, a level of `render` only.

| Option | Effect |
|---|---|
| `PATH` | The folder; this one by default. Its trust covers the folders inside it, so `chartbook trust ~/GitRepositories/ftsfr` trusts every pipeline under it, and the command says so when the folder has no `chartbook.toml` |
| `--render` | Trust it to render only: queries run for glimpses and the index, and the files its manifest names are read wherever they are. `build` and `run` still refuse, saying "trusted to render, not to run" |
| `--repository` | Trust the folder's `origin` repository instead of the folder: every clone of it, wherever it is on this machine. The folder must have an `origin` remote |
| `--members` | In a catalog: trust the catalog's own folder and each member folder on this machine. A member shown from the store has no folder here and needs no trust. With `--render`, to render only |
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

**Recorded for you.** A project `chartbook init` makes is recorded at `run`, and so is the folder of a catalog `chartbook catalog init` makes: you made them. A folder `chartbook catalog add` adds is recorded at `render`, unless it is trusted already: adding it to your catalog asks for it to be rendered there, and `run` stays yours to say, since `chartbook build` in a catalog runs every member's script. Each says so in one line, and goes on when the record cannot be written.

**Without a record.** Under `CI` (the environment variable, set to anything) the checkout is trusted to run: the top of the git repository the working directory is in, or the working directory itself when it is in none; a runner builds its own checkout. `CHARTBOOK_TRUST=all` trusts every folder to run, for a container that is nothing but your own code (the test suite runs so); it is the one value the variable takes, and another is said once and ignored. A build of files from a store (`CHARTBOOK_UNTRUSTED_SOURCE=1`) is never trusted, whatever the record says. A `git` dependency is built in ChartBook's own copy of its commit: naming it in `[dependencies]` is the trust for that, and the pipeline that names it must itself be trusted to run.

`chartbook docs generate`, `chartbook build`, `chartbook run`, `chartbook catalog generate`, `chartbook create-data-glimpses` and `chartbook publish` take the gate; `chartbook check` does not, and says the level. In a catalog, `--members` records nothing while a member's folder has no `chartbook.toml` where the catalog says it is, and names it: a folder trusted before anything is there would trust whatever is put there later.

No prompt: a command that needs trust refuses and prints this command, so a script behaves as a person does. The reasoning is {doc}`../design/trust`.

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

Another pipeline's asset, `rates:treasury`, is read as `data.load` reads it: its pinned copy in the store, and before anything is pinned, by the rules in {doc}`../guide/depending-on-pipelines`. A dependency declared and not pinned is pinned then, which writes `chartbook.lock` and says so on stderr.

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

This resolves differently, on purpose. Your own assets resolve *live*, to the file you are working on. Another pipeline's resolve *pinned*: to the copy that `chartbook.lock` names, in the store, not to that pipeline's working directory (before a pin, by the rules in {doc}`../guide/depending-on-pipelines`). So what you read from it stays the same while it is being worked on, and changes only when you run `chartbook update`.

Three things have to be true, and each has its own message when it is not:

| What is missing | What it says to do |
|---|---|
| The pipeline is not in {ref}`[dependencies] <dependencies>` | Shows the line to add, then `chartbook pin` |
| It is declared and not pinned, or the asset was not built when it was pinned | `chartbook pin` (after building it there) |
| It is pinned and the store does not have the bytes, as after a clone | Point `CHARTBOOK_STORE` at the store that has them. Otherwise, for a `git` dependency, `chartbook pin` puts them back; for a `path` dependency, its owner runs `chartbook snapshot` and you run `chartbook update` |

The scope may be left off when only one dependency has that name. The path is for reading; never write to it.

Two more parts of the {doc}`reference grammar <../design/references>` do not give a path. `dataframe#series` is the address of one column, for documentation: use the dataframe's path and pick the column yourself. A registry in front is reserved and refused as not yet supported. To find a dataframe through a catalog, from outside any pipeline, use `chartbook data get-path`.

## chartbook publish

Copy the pipeline's publishable *source* files — README, `chartbook.toml`, parquet artifacts, write-ups, chart HTML, and notebooks marked `publishable = true` — into a staging directory. This is for sharing the pipeline itself; `build` is what renders the website.

```console
chartbook publish [--publish-dir PATH] [--project-dir PATH] [-v]
```

It copies the files the manifest names, so in a folder you have not trusted it reads as a build of files from a store does: a manifest that names a file outside the folder stops it, naming the entry, and the command says how to trust the folder ({ref}`chartbook trust <chartbook-trust>`).

```{note}
`publish` copies files into a directory and does nothing else — no network, no registry. Sending a pipeline to a registry is a different act and will get a different verb, **`chartbook push`**. That name is reserved: the command exists only to say it is not yet supported, and `publish` will not grow a second meaning.
```

## chartbook catalog

Manage a catalog — by default the global one at `~/.chartbook/chartbook.toml` (`chartbook config` can point these commands at a different catalog). Concepts and the auto-discovery alternative: {doc}`../guide/catalogs-and-data`.

### catalog init

Create the global catalog with an empty `[pipelines]` section. Its folder is recorded as trusted to run ({ref}`chartbook trust <chartbook-trust>`): you made it.

```console
chartbook catalog init [--title TITLE]
```

### catalog add

Register pipeline directories. Each is keyed by its pipeline ID ({ref}`the rule <pipeline-identity>`): its `[project] id` if set; otherwise, at the top of a git repository with a remote (its `[project] repo_url`, or else its git `origin` remote), the repository's scope and name from the remote, whatever the folder is called; in a subfolder of one, the remote's scope and the subfolder's name; with no remote, the bare folder name. Paths are stored relative to the catalog, between the two folders with any link in their paths followed (a path written from the catalog's folder as named through a link, as an older `catalog add` wrote it, is still read where the catalog is reached that way, with a warning naming the path to write); duplicates (by resolved path) are skipped, as are paths already covered by a `pipelines.members` pattern. A folder that is another checkout of a pipeline the catalog has (a worktree of its repository, or a second clone), whether an entry names it under any key or a `members` pattern finds it, is said to be in the catalog already, under that key, and is not added; a disabled one is enabled again, as adding its own folder does.

```console
chartbook catalog add PATHS... [--catalog PATH] [-y]

chartbook catalog add ../crsp_treasury      # one pipeline
chartbook catalog add ../repos/* -y         # glob, no confirmation prompt
```

Each folder added is recorded as trusted to render, unless it is trusted already ({ref}`chartbook trust <chartbook-trust>`): adding it to your catalog asks for it to be rendered there. To run stays yours to say, `chartbook trust` in the folder or `chartbook trust --members` in the catalog's, since `chartbook build` in a catalog runs every member's script.

### catalog disable / enable

Switch a pipeline off or on without deleting its registration. Explicit entries get `disabled = true`; member-discovered pipelines are tracked on the `pipelines.disabled` ID list. In a catalog with only explicit entries, an unknown ID errors and lists the available pipelines; in a member-based catalog the ID is simply added to (or removed from) the list, and if it matches no pipeline the next build warns with a did-you-mean suggestion.

```console
chartbook catalog disable ftsfr/sovereign_bonds [--catalog PATH]
chartbook catalog enable ftsfr/sovereign_bonds [--catalog PATH]
```

### catalog generate

Render the catalog's site into `~/.chartbook/docs/` (or the configured catalog's location). Unlike `chartbook docs generate`, the default here is `--no-strict`: one member pipeline with missing files is skipped with a warning instead of sinking the whole site.

```console
chartbook catalog generate [-f] [--strict/--no-strict] [--clean] [--watch [--watch-interval SECONDS]]
```

A catalog build is **incremental by default**. Its working files are kept beside the catalog, in `_docs/`, and the next build reads them and redoes only the pipelines whose files have changed since — in a large catalog, usually a handful or none. Nothing runs between builds: there is no server or background process, only that directory. See [Incremental builds](#chartbook-docs).

`--clean` throws the kept files away and rebuilds everything, which is also what happens automatically after ChartBook, Sphinx or a theme is upgraded. `--watch` rebuilds whenever a member pipeline's files change, until Ctrl-C.

As `chartbook docs generate` in the catalog's folder, it builds only when the catalog's own folder and every member folder on this machine are trusted ({ref}`chartbook trust --members <chartbook-trust>`); otherwise it lists the folders that are not, and builds nothing.

### catalog open

Open the rendered catalog site in your default browser.

```console
chartbook catalog open
```

## chartbook ls

List cataloged objects. Without a subcommand, prints a tree of every pipeline with its dataframes and charts; subcommands print flat lists.

```console
chartbook ls [--catalog PATH]              # the tree
chartbook ls pipelines [--catalog PATH]    # flat lists
chartbook ls dataframes [--catalog PATH]
chartbook ls charts [--catalog PATH]
```

```console
$ chartbook ls
Catalog: /data/my-catalog/chartbook.toml

[pipeline] acme/yield_curve: Yield Curve Analysis
  [dataframe] acme/yield_curve:repo_public: Repo Public Data
  [chart] acme/yield_curve:chart/yield_spread: Yield Spread Chart
```

Each asset is written as its reference, `pipeline:name`. A pipeline the catalog shows from the store alone is listed as store only, with the dataframes and charts its newest snapshot lists.

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

`-o DIR` (`--output-dir`) is the directory the report is written in, as `DIR/data_glimpses.md`; it is made if it does not exist. A path ending in `.md` is taken as the report's own path; anything else already there that is not a directory, a file or a broken link, is refused, as it is neither. Without `-o`, the report is `data_glimpses.md` in the current directory.

The report reads the files the manifest names, so in a folder you have not trusted it reads as a build of files from a store does: a manifest that names a file outside the folder stops it, naming the entry, no query is run, and the command says how to trust the folder ({ref}`chartbook trust <chartbook-trust>`).

(chartbook-snapshot)=
## chartbook snapshot

```console
chartbook snapshot [--project-dir PATH] [--deep]
```

Declare this pipeline's build ready for the pipelines that depend on it. Every asset the pipeline declares and has built is copied into the store, labelled with the commit the pipeline is at; a dataframe that is a table or a query in a DuckDB file is written out as a parquet file there, so that it can be pinned and read like any other. That is a **snapshot**.

```console
$ chartbook run            # build it
$ chartbook snapshot       # and say it is ready
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
```

**A snapshot carries its lineage.** It records what the pipeline was pinned to, each dependency's commit and a hash over everything pinned from it, so it is made only when those pins account for every dependency: the check `chartbook pin --frozen` makes (every dependency in the lockfile, pinned from where the manifest says, its bytes in the store); no `path` dependency, or one named by its ID, whose pin names no snapshot (as in a lockfile changed by hand); and for each dependency pinned from a snapshot, that snapshot in the store, holding each asset pinned from it at its hash, and each label pinned naming a version some snapshot of it holds, so a lockfile changed by hand is caught (a `git` dependency, pinned from its clone, is checked only to have its bytes in the store). Nothing that cannot have been read stops it: an asset the other pipeline had not built when it was pinned, or a dependency of which nothing is pinned (it declares nothing, or has no snapshot yet). Otherwise nothing is made, and each gap is listed with what to run. `chartbook run --snapshot` makes the same check after it pins and before it builds, so a gap is found before an hour of building.

Two things it does not see. A snapshot pinned from that was made before this check, or by an older ChartBook, may have gaps of its own: the check is of this pipeline's pins. `--deep` also walks every snapshot upstream ({ref}`chartbook lineage <chartbook-lineage>`) and refuses if any has a gap; it needs every snapshot upstream in the store, so it is for when you want that audit, not a requirement. The record says which was done (`built_with.lineage`: `pins` or `deep`). And a read that does not go through the lockfile (a load through a catalog, a model version named by its hash) is not in them.


```console
$ chartbook snapshot
Error: acme/forecast cannot have a snapshot: its pins do not account for every dependency, and a snapshot carries its lineage.
  rates: is in [dependencies] and not in the lockfile. Run `chartbook pin`.
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

**New data, same code.** A pipeline that pulls data from outside builds other bytes on another day, with no file changed. Build again and snapshot again: the commit is the same and the snapshot is new. If nothing was rebuilt, and `chartbook.lock` pins what it pinned, nothing is made:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
Nothing has changed since the snapshot of 2026-10-13 18:22 UTC. No new one was made.
```

A snapshot records what the pipeline was pinned to, so after `chartbook update` it is made again with the same bytes: a pipeline that pins this one then reads where they came from. Two checkouts of one pipeline that share a store and pin differently (a lockfile git ignores) each make their own when they snapshot, and the newest is the one a pin takes.

An asset that is declared and not built is listed, and the rest is in the snapshot all the same. A pipeline that has built nothing has no snapshot to make.

**A git tag is a version's name.** A snapshot records the git tags on its commit when it is made (`tags`). A commit is often tagged after it is built: run `chartbook snapshot` again after tagging, and since the tags are new it records them, with the same bytes; and `chartbook lineage` and a catalog's Versions page show them. Name a version with `git tag`, and unname it with `git tag -d`: `store gc` keeps the newest snapshot a tag can pin from while the tag is there, and lets it go once it is not, or always with `--aggressive`. A name keeps that snapshot only, not what it was made from (`store gc --keep-lineage` does that).

**The snapshot holds the description of its data.** With the bytes, a snapshot keeps the pipeline's own index at that commit, without any path of your machine, and the files a site needs that are not assets: `chartbook.toml`, `chartbook.lock`, the README, every write-up (`docs_path`), the pipeline's own site pages and its logo and favicon. Only files git tracks are taken, so a `.env` or an ignored draft never reaches the store; only plain paths inside the pipeline's folder, and no file that is a link or under one. Each document named and not kept is listed (`document not kept: …`). So the data dictionary of each version is kept as it stood when the data was made, and a version's site can be built from the store alone, with the repository gone: `chartbook.snapshot.materialize(taken, folder)` lays the version out as a folder, under the pipeline's own ID whatever the folder is called, with each model's recorded scores written back to its `metrics_path`, and `chartbook docs generate` builds there. A dataframe that is a table or a query is in the store as parquet while its manifest names a database, so in a laid-out version its page says it is not built. A manifest a docs build would refuse still gets its snapshot; the index is then left out and the command says why:

```console
$ chartbook snapshot
ftsfr/fed_yield_curve at 4f2a91c: 3 asset(s) in the store
  index not recorded: Chart 'curve' has no 'dataframe' key linking it to a dataframe in the [dataframes] section. The bytes and the documents are in the store; `chartbook check` says what a docs build would refuse.
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
```

A snapshot made by an earlier ChartBook carries neither; making one again at the same commit adds them, even when the bytes have not changed.

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
- **It costs disk where the disk has no copy-on-write clones.** A snapshot is its own copy of the files (a Mac, and Linux with btrfs or XFS, clone them for free). {ref}`chartbook store gc <chartbook-store-gc>` clears old ones: those nothing pins, that are not the newest of their pipeline, that no label points into, that hold no version of an asset marked `keep = true`, and that are over 7 days old.
- **It is found by commit, or by the pipeline's ID.** A pipeline that depends on this folder, or on the same repository by URL, finds it by the commit; one that names this pipeline by its ID (`"ftsfr/fed_yield_curve" = {}`) finds it by the ID. It is in the store, so another machine that shares the store ({ref}`a store a team shares <chartbook-store>`) finds it the same ways once the store has synced, and by the ID with no folder of this pipeline there at all.

(chartbook-restore)=
## chartbook restore

```console
chartbook restore [NAMES...] [--project-dir PATH]
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

(chartbook-pin)=
## chartbook add

```console
chartbook add PIPELINE [--as NAME] [--commit COMMIT] [--project-dir PATH]
```

Declare that this pipeline reads another, by the other's ID, and pin it. It writes the entry under `[dependencies]` in `chartbook.toml`, leaving the rest of the file as it is (its comments and order), then runs `chartbook pin`. The other pipeline is read from its snapshots in the store alone: no folder of it here, and no clone.

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

A key already in `[dependencies]`, or a `commit` that is not the start of one, writes nothing. Nor does a dependency whose pin would make this pipeline depend, through what it depends on, on itself: the pin is refused as `chartbook pin` refuses it, `chartbook.toml` is put back as it was, and the command says the dependency was not added. `chartbook update` moves the pin to a newer snapshot once its owner makes one.

## chartbook pin

```console
chartbook pin [--project-dir PATH] [--frozen]
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
1 pinned asset(s) have changed upstream. `chartbook update` moves the pins.
```

An asset that the pinned snapshot had not built and the newer one has is still listed as not built, with the reason `a newer snapshot has it`. A rebuild that its owner has not made a snapshot of is not mentioned, because it is not seen.

**A dependency is pinned to one snapshot, whole.** `pin` does not take one asset from a newer snapshot and leave the rest. What a second `pin` does do is pin a dependency that has no pin yet.

**Its labels are pinned too.** A snapshot records the labels the pipeline's `[models.x.aliases]` gave when it was made, and `pin` writes each as a record of its own, `ftsfr/fed_yield_curve:model/term_premium_ar1@champion`, with the hash of the version it names. `forecasting:model/x@champion` then resolves to those bytes until `chartbook update`, which follows the owner's labels: a label moved shows as `moved`, one taken away as `dropped`, and one the owner has moved since you pinned is reported by `pin` as changed upstream. A label whose version the store cannot supply (no snapshot names it, or its bytes are gone) is pinned without bytes, as a `not built` asset is, with the reason, and `--frozen` reports it. Labels come only from snapshots. A `git` dependency has no versions and no labels pinned, and a dependency that becomes one lets its labels go (`let go`).

`pin` exits `1` when something could not be pinned: a dependency with no snapshot, a repository that cannot be fetched, or a pin whose bytes are not in the store, or not all there yet. The size on disk of each file a pin reads is compared with the size its record gives (no byte is read), so a file that a sync service has only half delivered is said, not read:

```console
$ chartbook update
acme/rates: 1 already pinned, 1 not fully synced
  not fully synced: acme/rates:treasury: nothing was moved to the snapshot at 9c1d2e3, which names it: its object in the store at /Users/x/Google Drive/chartbook-store has 4,096 bytes of treasury.parquet where its record says 18,640: it is not fully synced yet. Wait for the sync to finish, and run this again (if it stays so, `chartbook store verify` says more)
chartbook.lock is unchanged.

1 thing(s) could not be pinned.
```

`pin --frozen` and a read (`data.load`, `data.path`) say the same of a pin whose object is not whole. An object that is not in the store at all is `lost`, and in a store that machines share through a synced folder the likeliest cause is a sync that has not finished, on this machine or on the one that put it there: the message says what to do on each side.

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

To see a change in a pipeline you depend on and are changing too, declare it ready and move to it: commit the change there, run `chartbook snapshot` there, then `chartbook update` here, which prints what moved. A lockfile names only what a snapshot or a commit holds, so every pin can be traced to the commit it came from.

In a notebook, or a script you run yourself, `data.load()` reads a dependency that has no snapshot yet from its working folder, with a `WorkingVersionWarning`, and records nothing in the lockfile. A build does not: `chartbook run` sets `CHARTBOOK_BATCH=1` for `build`, and there that read is an error.

**`--frozen`: say, and write nothing but a note.** For CI, and for anyone whose store is read-only. `chartbook pin --frozen` pins nothing, fetches nothing and does not write the lockfile or any object. It reads `[dependencies]`, `chartbook.lock` and the store, and exits `1` unless the pipeline can be built from its lockfile alone: every dependency pinned, from where the manifest says it is; every asset built when it was pinned; every pin in the store. The one thing it may write is the store's note that this machine reads these pins, replaced with what the lockfile pins now as `pin` would write it, where the store can be written and the note says otherwise (under CI with no `CHARTBOOK_MACHINE_ID`, the note names the lockfile's path alone, as `pin`'s does there), so that `store gc` on another machine keeps them (see {ref}`store gc <chartbook-store-gc>`); it then says `Nothing written but the store's note that this machine reads these pins`, and says so when the note could not be written. A read through the lockfile (`data.load`) leaves the same note, silently.

```console
$ chartbook pin --frozen
ftsfr/fed_yield_curve:model/term_premium_ar1: was declared and not built when it was pinned. Build it there, declare it ready, and `chartbook update`.
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.

$ chartbook pin --frozen
4 pin(s) of 1 dependency, all in the store. Nothing written.
```

Where `pin` records an asset that was not built and goes on, `--frozen` counts it a problem: the build that follows may need it.

Dependencies between pipelines must form a graph with no cycles. A pin whose new or moved entries would lead back to this pipeline, or into pipelines that depend on each other, is not written: `chartbook pin` says who depends on whom, and where each was read, and exits 1 with `chartbook.lock` and the store as they were. `chartbook update` and `chartbook add` do the same, and the first read of a dependency, which pins it, raises `AssetNotPinnedError` with reason `cycle`. A cycle reached only through pins made before is not the new pin's doing and does not stop it: `chartbook run` and `chartbook check` say it, and `chartbook pin --frozen` exits 1. An ID names one pipeline: a copy that kept another's ID and reads it depends on itself. Where the cycle closes on the ID in another folder, the message names both and says what to do either way: two checkouts of one repository are one pipeline, and one of the dependencies comes out; two pipelines that share the ID give one of them an ID of its own with `[project] id`.

## chartbook update

```console
chartbook update [DEPENDENCY...] [--project-dir PATH]
```

Move pins forward, and rewrite `chartbook.lock`. A folder you depend on moves to its newest snapshot. A repository is fetched again, and moves to what its `rev` means now. With no argument every dependency is updated. Name some to update only those, as they are written in `[dependencies]`; the scope may be left off when only one has that name.

```console
$ chartbook update fed_yield_curve
ftsfr/fed_yield_curve: 1 moved, 2 already pinned, 1 not built
  ftsfr/fed_yield_curve:treasury_rates
    sha256:4b1f9a0c2e3d… -> sha256:99ab40d12e77…
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

**A pipeline whose ID changed.** A dependency named by its ID stays at the last snapshot made under that ID. When the store has newer snapshots of the same repository and folder under another ID (the owner added a remote, so the pipeline has a scope now; see {ref}`Pipeline Identity <pipeline-identity>`), `pin` and `update` say so each time, and name the entry that follows it:

```console
$ chartbook update
first_pipeline: 1 already pinned
  the store has newer snapshots of the same repository and folder under another ID, testorg/first_pipeline (the newest made 2026-10-17 16:54 UTC): the pipeline probably calls itself that now, as one does when it gets a git remote or a [project] id. To follow it, write "first_pipeline" = { id = "testorg/first_pipeline" } under [dependencies], then `chartbook update first_pipeline`.
```

The `id` keeps the name your code uses, `first_pipeline:rates`.

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

(chartbook-lineage)=
## chartbook lineage

```console
chartbook lineage [--project-dir PATH] [--check] [--rehash] [--json]
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
chartbook run [SCRIPT] [--force] [--snapshot] [--frozen] [--remake] [--project-dir PATH]
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
2. **Pins what has no pin yet**, so this pipeline's code can read it: a folder you depend on from its newest {ref}`snapshot <chartbook-snapshot>`, a repository from that clean copy. A dependency named by its ID that the store has no snapshot of is built and pinned from its repository on the default host, as a `git` dependency is ({doc}`configuration`, `[resolve] default_host`).
3. **Runs this pipeline's `build`**, in its own directory. What the script prints is shown as it runs. If it fails, the command exits with the script's exit code.

`build` runs with `CHARTBOOK_BATCH=1` set; another script runs as interactively as the shell it was run from. In a batch run, `data.load` and the other readers read another pipeline only through its pin: one that is not declared, or that has no snapshot and is read from its working folder, is an error rather than a warning, since nothing would record what was read. CI can set the variable too. See {doc}`../guide/depending-on-pipelines`.

In a fresh clone, `chartbook run` is the only command you need: there is no `chartbook pin` to remember first.

**Only in a folder you trust to run.** A build script is code. In a pipeline you have not trusted to run, you are asked first when you are at a terminal (`y` trusts it, Enter stops; {ref}`chartbook trust <chartbook-trust>`). Where no one is asked, `chartbook run` stops before anything runs, naming the folder and {ref}`chartbook trust <chartbook-trust>`; in a catalog, it lists every member that is not trusted, and nothing runs (`chartbook trust --members`). A pipeline trusted to render only is refused the same way. A project `chartbook init` made is trusted as it is made, and under `CI` the checkout is.

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

A script is run by `bash`, or by `sh` where there is no `bash`, and stops at the first command in it that fails. On Windows it is run by `cmd`: a script of one line as it is, and one of several lines as a batch file that stops at the first line that fails, with that line's exit code; there a line that runs another batch file (`conda activate`, which is `conda.bat`) must begin with `call`, or nothing after it runs.

**`--frozen`.** Pin nothing and write nothing before the build but the store's note that this machine reads these pins (as `chartbook pin --frozen` does): not the lockfile, no object, and no `git` dependency is fetched or built. The build runs only if `chartbook pin --frozen` would pass; otherwise nothing runs and the problems are listed. `--frozen` and `--snapshot` are one or the other.

**`--remake`.** An asset `chartbook.toml` marks `keep = true` cost something to make ({doc}`../guide/keeping-costly-outputs`). When one is not on disk while the store has a version of it, `build` stops before anything runs, in a catalog before any member's build, and says the two ways on:

```text
Error: acme/docs: embeddings is kept, and is not on disk (./_data/embeddings.parquet). The store has its version from 4f2a91c, made 2026-09-30 14:02 UTC.
  chartbook restore           puts it back
  chartbook run --remake      runs the build without it, which makes it again
Nothing was built.
```

{ref}`chartbook restore <chartbook-restore>` puts the bytes back, and `--remake` runs the build without them, which makes the asset again; it covers every kept asset at once, so to remake one and keep another, restore the other first. A first build, with no version in the store, is not stopped, and a kept asset that is on disk stops nothing: to remake one on purpose, delete the file, then `--remake`. The stop covers the pipelines the command was given, and a catalog's members; a `git` dependency built in ChartBook's own copy is not stopped. A version whose bytes are not in the store is nothing to put back, so it stops nothing either.

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

(chartbook-store)=
## chartbook store

The store keeps files under the hash of what is in them. It is a folder on this machine, a folder machines share (on a shared disk, or synced by a service such as Google Drive), or a bucket. It is where `chartbook snapshot` puts what a pipeline built, and where `chartbook pin` finds it.

It is at `~/.chartbook/store/`. To put it somewhere else, set `CHARTBOOK_STORE`, or add this to `~/.chartbook/settings.toml`, or to the organization's settings file (`/etc/chartbook/settings.toml`, or the file `CHARTBOOK_SYSTEM_SETTINGS` names), which every user on the machine shares and the user's file overrides:

```toml
[store]
url = "/a/bigger/disk/chartbook-store"
```

`chartbook store info` says which one this machine uses, and what set it.

**A store a team shares.** Point every machine's `[store] url` (or `CHARTBOOK_STORE`) at one folder on a shared disk or in a synced folder ({doc}`configuration` says what to know about a sync service), or at one bucket (`s3://bucket/prefix`, with `pip install chartbook[s3]`; see {doc}`configuration`), and a snapshot made on one machine is there for all of them: a colleague, or CI, runs `chartbook pin` and gets the bytes the lockfile names, with no build of their own. A dependency named by its ID (`"acme/rates" = {}`) is pinned and updated from the store alone, with no folder of it on that machine. A snapshot is always the store's own bytes (a copy-on-write clone or a copy, never a link to a file on someone's machine), so this works across machines. The folder may be read-only for everyone but its owner: pinning a `path` dependency from a snapshot writes nothing in the store but the note for `store gc`, and `pin` says when it could not leave it. Make `roots/` writable for everyone (for a bucket, `s3:PutObject` on `<prefix>/roots/*`) and the notes get through. What does have to write the store says so and stops: a `git` dependency's first pin and `chartbook snapshot` both put files in. `--frozen` writes nothing but, where it can, this machine's note for `store gc`, and is what CI should run (under CI with no `CHARTBOOK_MACHINE_ID`, every note names the lockfile's path alone, so each run at the same checkout path replaces the last one's). Each machine's notes are its own (they name the machine, from `~/.chartbook/machine-id`, as well as the lockfile's path, since two machines can have a project at the same path), and `store gc` keeps what another machine's lockfiles recorded at their last pin. It is best run by the store's owner, from the machine the snapshots were made on: a label another machine gave is known here only through the snapshots that recorded it.

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

What set it is one of: `CHARTBOOK_STORE`; `[store] url` in your settings file; `[store] url` in the organization's settings file; or the default, `~/.chartbook/store`. A folder that does not exist yet is said (`nothing is there yet`): the first snapshot or pin makes it. The kind is a folder, an S3 bucket, or a `scheme://` store a plugin provides, and the command makes sure this machine can use one of that kind: a bucket on a machine without boto3 is an error here, naming `pip install chartbook[s3]`, and exits `1`, rather than at the first pin or read; so is a scheme nothing installed provides.

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
chartbook store gc [--dry-run] [--yes] [--forget-missing] [--keep-days DAYS] [--keep-lineage] [--aggressive]
```

Remove from the store what nothing needs any more: old snapshots, and the objects that only they, or a pin that has since moved, named.

The store is shared by all your projects. Two things keep what is in it. Every `chartbook pin` and `chartbook update`, and, where the store can be written, every `--frozen` and every read through a lockfile, notes its lockfile in the store with what it pins (its objects and its snapshots), and `gc` keeps whatever those notes and lockfiles name. And every {ref}`snapshot <chartbook-snapshot>` keeps what it names, for as long as the snapshot is kept.

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

Everything else may be removed. So a nightly `chartbook run --snapshot` leaves, after a while, the last week of snapshots, the ones somebody pins, and the ones a tag or a label names.

It lists what it would remove and asks before removing anything:

```console
$ chartbook store gc
Kept: 14 object(s), named by 3 lockfile(s) or a kept snapshot
  /work/crsp_treasury/chartbook.lock
  /work/rate_forecast/chartbook.lock
  /Volumes/usb/old_project/chartbook.lock  (not found; its pins are kept)
Kept: 4 snapshot(s), naming 9 object(s): 1 because a lockfile pins it, 2 because it is the newest of its pipeline, 1 because it was made in the last 7 days
Would remove 6 snapshot(s):
  ftsfr/fed_yield_curve at 2a9c01d, made 2026-08-02 06:00 UTC: nothing pins it, it is not the newest, and it is older than 7 days
  …
Would remove 5 object(s), 2.1 GB, that nothing names.
Remove them? [y/N]:
```

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
- **Another machine's lockfile keeps what it recorded at its last pin.** In a store that machines share, each note names the machine its lockfile is on, and records the objects and the snapshots the lockfile pinned. Each `chartbook pin` and `chartbook update`, and each `--frozen` and read through the lockfile, replaces that machine's note for that lockfile with what the lockfile pins then (a `--frozen` or a read writes nothing when the note says that already). A lockfile at the same path here is another file, so `gc` keeps what the note recorded and does not open that path. It lists the note as `(on another machine, <its host name>: what it recorded at its last pin is kept; note <store>/roots/<file>)`. `--forget-missing` does not forget it: only that machine can tell that its lockfile is gone, and its own `gc --forget-missing` does. A machine that only reads leaves its note this way where the store can be written; on a store it may only read, `--frozen` says its note could not be written, and `gc` on another machine does not know what it reads. Under CI (the `CI` environment variable set, and no `CHARTBOOK_MACHINE_ID`), `pin`, `update`, `run`, `--frozen` and a read write their note under the lockfile's path alone, with no machine name, as notes were written before they named machines: a runner with a fresh home each run would otherwise have a new name, and leave a note under each. So each run at the same checkout path replaces the last one's note, and `gc` on a runner whose store lasts reads its lockfile and keeps what it pins.
- **Which machine is which.** A machine is named by a random name made once and kept in `~/.chartbook/machine-id`, beside what the operating system calls the machine (`/etc/machine-id`, `MachineGuid`, the hardware's UUID; the host name where there is none), so a home folder copied to another machine (by a migration, a restored backup, or a sync service) gets a name of its own there. Machines are told apart by that identity, or by `CHARTBOOK_MACHINE_ID`, and by nothing else: a note records the host name and a hardware address for you to read, and nothing goes by them, since one machine's may change. So a clone that kept the operating system's identity (a virtual machine cloned without a new `/etc/machine-id`, or Windows without sysprep; an image with one baked in), with a copied home, is not told apart from the machine it was cloned from: the two share a name and one note per path. Each machine that lasts needs an identity of its own, or a `CHARTBOOK_MACHINE_ID` of its own. Never copy `machine-id` between machines, and never keep `~/.chartbook` itself in a synced folder. `CHARTBOOK_MACHINE_ID` also names a machine that comes and goes with a fresh home folder (a CI runner that pins, a container): give each run the same one, and check its project out at the same path, so that each run's note replaces the last one's rather than piling up.
- **Old notes and copies.** In your own store, under `~/.chartbook` (the default one), a note from before notes named their machine can only be this machine's. Its lockfile is read alone, as it was before notes named their machine, and what the note recorded keeps nothing more. The next `chartbook pin`, `chartbook update`, `--frozen` or read through that lockfile writes this machine's note and removes the old one; `gc` removes an old note once this machine has a note of the same lockfile and that lockfile is read here (while it cannot be found, a drive unplugged, what the old note recorded is kept), or, with `--forget-missing`, once the lockfile is gone, and names its file under `roots/` on the lockfile's line. A CI runner with no `CHARTBOOK_MACHINE_ID` writes its notes this way, under the path alone, and its own pins and reads replace such a note rather than remove it. In any other store, such a note, and a sync service's copy of a note (`<name> (1).json`) in any store, may be any machine's: what they recorded is kept, and nothing removes them for you, since nothing can tell whose they are. A note from before notes recorded snapshots keeps, of the snapshots holding each object it names, the newest. A note or a copy that cannot be read (half synced) stops `gc`, which names it and says what to do. To let go of a machine that is no longer used, or of an old note or a copy, remove its file from `roots/` in the store; `gc` names each file, and each is JSON naming its `lockfile`, `machine` and `host`.
- **Only a lockfile on this machine is read.** The store's note for each lockfile is written by whoever can write to the store, so `gc` reads only an absolute path named `chartbook.lock` that is not a network path. Any other (a project on a network drive among them) is not read: the pins its note records are kept, `--forget-missing` included, and `gc` says it did not read it.
- **An object stored in the last hour is never removed.** A pin puts files in the store before it writes the lockfile that names them. So the run that removes a snapshot's record may leave its objects for the next run.
- **If a lockfile, a note or a snapshot's record cannot be read, nothing is removed.** `gc` stops, says which, and says what to do. In a store a sync service keeps, a file can be there before its bytes (empty, or cut short), and that is the likeliest cause: run `gc` again once the sync has finished. A note or a record that stays unreadable is removed by hand: a note is written again by the next `chartbook pin`, `chartbook update`, `--frozen` or read through its lockfile, and a record is one snapshot's, which the store then has no more.
- **What it cannot remove is said, and the rest goes.** In a store users share, an object or a record another user put there sits in a folder of theirs that you may not write. `gc` removes everything else in the plan, prints what it removed, lists each thing it could not remove with its path and what to do (its owner removes it, with `chartbook store gc` there or by hand, or gives you write permission on it and on the folder holding it), and exits `1`. What a record that stayed names stays with it, and an object that stayed is in the next run's list.

A note only ever adds to what is kept. A lockfile on this machine is read as it is now, and what its note recorded at its last pin (the objects, and the snapshots) is kept as well: check out an older commit and run `gc` without pinning, and the pins of the commit you left are kept, by the note, until the next `chartbook pin`, `chartbook update`, `--frozen` or read writes it again (a read, or `--frozen`, on the older commit writes it too, with that commit's pins). A note from before notes named their machine, in your own store, is read as it was then: its lockfile alone.

## chartbook config

Interactively set the default catalog path (stored as `catalog.path` in `~/.chartbook/settings.toml`). This is what `data.load()`, `chartbook ls`, `chartbook data`, and the `catalog` commands use when no explicit `--catalog`/`catalog_path` is given.

```console
chartbook config
```

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
  chartbook-version: "0.2.0"
```

A copy for an older version is replaced, and the command says which: `Updated the skill in ~/.claude/skills/chartbook from ChartBook 0.1.1 to 0.2.0`. A copy installed before 0.2.0 says its version only in a `.chartbook-skill-version` file beside it, which is read and then removed; such a copy is older than any skill that names its version, whatever the file says. A copy for a newer version (another environment's ChartBook), or for this version with files changed by hand, is replaced only when you say so, or with `-f`. When the files already match, nothing is copied. Files of older layouts are removed, so the copy mirrors the bundled skill.

**Finding a stale copy.** Every other command, run by a person at a terminal, says in one line on stderr when your copy, or the project's, is for an older ChartBook, and names the command that installs this version's. The project's copy is `.claude/skills/chartbook/` in the working directory or the nearest folder above it, up to the top of its git repository and never the home folder. A script, CI, a command inside a script `chartbook run` is running, or anything reading the output never sees the line, and a copy for a newer ChartBook is not mentioned, so that two environments on two versions do not take turns replacing it. `chartbook check` says the same as a `warning:` line, which fails nothing. The command was called `install skill` before 0.2.0, and that spelling says the new name.
