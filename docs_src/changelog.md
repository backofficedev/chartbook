# Changelog

All notable changes to chartbook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — `chartbook check`, the CI gate

`chartbook check` exits nonzero when a project is broken or non-compliant, and zero when it is healthy. It reports fields the policy requires that are missing or empty, declared paths (`path`, `docs_path`, `readme`, `logo`, `favicon`) that point at no file, and dataframes whose `license_expiration` has passed or falls within `--within` days (default 30). Every finding is one line naming the `chartbook.toml`, the table and the field.

Run in a catalog, it checks every member pipeline against the catalog's `[policy.required]`. Run in a standalone pipeline, it uses the built-in recommended-field lists; `--policy PATH` substitutes the `[policy]` table of a catalog (or of any TOML file), so a pipeline's own CI can hold it to the catalog it is published to without that catalog's other members being present. `policy.mode` still governs builds only — `check` always fails on a missing required field.

`license_expiration` is read as an ISO date. Empty, `"N/A"`, `"None"` and `"Never"` mean no expiry; any other unreadable value is reported rather than passed. Only metadata and file existence are checked — no data file is opened.

The example projects now set `repo_url` (required by the default policy), and `examples/dodo.py` runs `chartbook check` on the example catalog.

### Added — `chartbook path` and `data.path()`

A build definition or a script can now ask the manifest where an asset belongs instead of repeating the path. `data.path("merged_rates")` returns the `path` declared for that name in the enclosing `chartbook.toml` — for a dataframe, chart, notebook or note — as an absolute `Path`; `chartbook path merged_rates` prints the same thing, which is how Make, R, Stata and shell scripts reach it. The manifest is found by walking up from the calling file, then from the working directory. The file need not exist, so the same call names a `dodo.py` target and the place a script writes to.

A name the manifest does not declare raises `AssetNotDeclaredError` immediately, naming the table to add, rather than surfacing later as a missing file. Only local names resolve: `other_pipeline:asset`, `asset#series` and `@rev` are reserved and refused as not yet supported. It is a convenience, never a requirement — a pipeline that hardcodes its paths, in any language, is unaffected.

`data.get_data_path(pipeline=, dataframe=)` keeps working and remains the way to locate another pipeline's dataframe through a catalog. It, `data.path()` and `data.load()` now share one internal resolver (`chartbook.resolve`) that returns a typed location, which is the seam table- and query-backed dataframes will later plug into; no behaviour changes.

Both example pipelines use `data.path()` for the declared targets in their `dodo.py`.

`data.scratch()` completes the set: it returns `_data/_scratch/` inside the current pipeline, created on first use, for throwaway files that are not assets. The directory ignores itself in git, and nothing documents, publishes or depends on what is in it.

### Changed — **breaking: data glimpses come from the manifest, not `dodo.py`**

`chartbook create-data-glimpses` no longer imports `dodo.py` and calls its task functions to find data files. It reads `chartbook.toml` and summarizes the dataframes declared there, so a project built with Snakemake, Make or plain scripts gets the same report as one built with doit — previously the command failed with `No dodo.py file found`.

What this changes for existing users:

- **Only declared dataframes are summarized.** A CSV or parquet file that appeared as a doit target but has no `[dataframes.*]` entry is no longer in the report. Declare it to include it.
- **The report is organized by dataframe.** Sections are titled by dataframe ID (`pipeline:dataframe` in a catalog) and show the declared name; the summary groups by pipeline instead of by doit task.
- **Partitioned dataframes work.** A glob `path` is summarized as one dataset across its part files.
- **Catalogs work.** Run in a catalog, the report covers every member pipeline.
- New `--project-dir` option. Declared dataframes whose files are not built yet are skipped with a note.

`create_data_glimpses.parse_dodo_tasks()` and its helpers are removed.

### Changed — registry-prefixed IDs and `chartbook push` are reserved

Two pieces of future syntax are claimed now, while claiming them costs nothing.

A pipeline ID qualified with a registry — `charthub.example/acme/rates`, `localhost:5000/acme/rates` — is now recognized and refused with `UnsupportedRegistryError` ("reserved syntax and not yet supported; use 'acme/rates' instead"), wherever an ID or pipeline reference is accepted: `[project] id`, catalog keys, `data.load(pipeline=...)`, `chartbook data`, `data.path()`. Previously it failed with a generic "Invalid pipeline id" grammar error. A registry is the first of exactly three components and looks like a host (contains `.` or `:`, or is `localhost`), which is Docker's rule. No existing ID changes meaning: a bare `name` and a `scope/name` are untouched, including a `scope` that contains a dot.

`chartbook publish` keeps its one meaning, staging a pipeline's files into a directory, and its help now says so. Sending a pipeline to a registry will be a separate verb, `chartbook push`; the command exists (hidden from `--help`) only to say it is reserved and to point at `publish`.

### Added — `chartbook init --git` and `--github`

`chartbook init` can now leave you with a repository rather than just a directory. `--git` runs `git init` in the new project and makes an initial commit, on a branch named `main` unless your git configuration says otherwise. `--github` does that, then creates a GitHub repository for it with `gh repo create`, adds it as `origin`, and pushes — private by default, `--public` to override. Both are off by default.

`--github` uses your existing `gh` login and never prompts for one. Everything it depends on is checked before the template is rendered — `git` and `gh` on `PATH`, a git identity for the commit, `gh` logged in — so a missing piece stops the command with the fix named and nothing created. The new project's directory is identified after `cruft` returns (it is named by an answer at the prompt), not guessed. After `--github` the `origin` remote exists, so the pipeline's ID is scoped (`owner/project`) from its first build; the command prints it.

### Added — data freshness on every asset page

Dataframe and chart pages now say how fresh they are, directly under the title, in plain relative wording: "Data updated 2 days ago · Code updated 3 weeks ago". A chart page adds when the chart file itself was written, so a chart rendered before its data was last refreshed is visible at a glance. Hovering shows the exact time.

The times are file modification times: the dataframe's file (the newest part file of a partitioned dataframe), the chart's HTML, and the pipeline's source (`src/`, `docs_src/`, `chartbook.toml`) — the last of which was already computed and shown only as "Date of Last Code Update" in the pipeline table at the foot of the page. The dataframe's time was computed and never rendered.

Because the site is static, the page carries the timestamp and a small bundled script (`chartbook-freshness.js`) turns it into "2 days ago" when the page is read, so the wording is never stale. With scripts off, the date is shown. The line is a template, `freshness.md`, and can be overridden like the others.

Fixed along the way: a chart backed by a partitioned (glob-path) dataframe had its data time stamped with the moment of the build.

### Added — documentation for writing a plotting backend

A new guide, *Writing a Plotting Backend*, documents the interface a third-party plotting backend implements: the `PlottingBackend` protocol and its `BaseBackend` starting point, what each `create_*` method is handed (`ChartConfig`, `OverlayConfig` and `DualAxisConfig`, field by field), the `chartbook_plotting` entry-point group, and a complete Vega-Lite backend in one dependency-free file that ChartBook's own tests run through a real entry point.

It also corrects what the code and the old "Plugin System" paragraph implied. An entry point must name a backend **instance** — the previously documented `"mypackage.backend:MyBackend"` registers an unusable class. The pluggy hook specifications in `PlottingHookSpec` are declared but never called, so implementing them does nothing. And a registered backend is reachable through `get_backend()` but is not yet selectable from `plotting.line()` and friends, which always use the built-in `plotly` and `matplotlib` backends. No behaviour changed; three docstrings did.

### Removed — **breaking: the `[all]`, `[data]`, `[plotting]` and `[sphinx]` extras**

The four install extras that became no-op aliases in 0.1.0 are gone, after the one release of notice they were given. `pip install chartbook` has installed everything since 0.1.0 and still does; drop the bracket from any requirement that has one (`chartbook[all]>=0.0.14` → `chartbook>=0.0.14`). pip and uv both still install the package for such a requirement rather than failing — uv warns that the extra does not exist — so nothing breaks at install time, but the bracket no longer names anything. The `[dev]` extra for contributors is unchanged.

### Added — a stability and deprecation policy

{doc}`reference/stability` says what ChartBook commits to and what it does not. Four surfaces are covered: the manifest format, the index schema, the Python API (`chartbook.data`, `chartbook.env`, `chartbook.plotting`) and the CLI. A breaking change to any of them is now announced by a deprecation warning for at least one minor release; where old and new cannot coexist, the old form is detected and refused with the fix rather than misread; such changes land only in minor releases before 1.0 and major releases after; and the changelog marks them. The index's per-record `kind` and `version` is the mechanism for changing one record type without a coordinated upgrade.

The page also lists what is explicitly *not* covered (internal modules, the generated site's HTML and templates, message wording), the breaking changes already designed and still to come before 1.0, and what is currently deprecated. No migration tooling is promised.

### Added — incremental builds and a watch mode

`chartbook build --incremental` keeps the intermediate Sphinx project in `_docs/` and makes the next build redo only what changed. **`chartbook catalog build` now does this by default** — its working files live beside the catalog in `~/.chartbook/`, not in anyone's repository — and takes `--clean` to discard them and rebuild everything. A pipeline none of whose files changed — its manifest, `src/`, `docs_src/`, README, and every data file, chart and notebook it declares, compared by modification time and size — is not regenerated. A page whose content comes out the same is left untouched, so Sphinx, whose cache is now kept, does not read it again. If no page changed, Sphinx is not run at all. Each build prints one line saying what it redid.

On a synthetic catalog of 40 pipelines and 411 pages, a clean build took about 20 seconds; an incremental build took 0.4 seconds when nothing had changed and about 5 seconds after one write-up or one data file changed.

`chartbook build --watch` is the same thing in a loop: build, check the project's files once a second (`--watch-interval`), rebuild on any change, report a failed build and keep going until Ctrl-C. It is a single polling process — no server, no live reload, no new dependency. Refresh the browser to see a rebuild.

A plain `chartbook build` is unchanged: a clean build that leaves nothing behind. Adding or removing a page re-renders every page from Sphinx's cache, so navigation stays right; upgrading ChartBook, Sphinx or a theme starts over from nothing. The kept `_docs/` carries its own `.gitignore`.

Fixed along the way, because it defeated Sphinx's cache: the generated `conf.py` now sets `fontawesome_included` explicitly. The themes switched it on mid-build, which Sphinx read as a changed configuration and answered by re-reading every page on every run.

### Changed — `repo_url` and "code updated" come from git

Two things that should never have needed filling in by hand now come from the repository.

`[project] repo_url` defaults to the repo's `origin` remote, turned into a web address: `git@github.com:acme/rates.git` becomes `https://github.com/acme/rates`. Credentials embedded in a remote (`https://user:token@…`) are always dropped, and a remote that is a path on disk gives no URL. An explicit `repo_url` still wins. One consequence: a project with a remote no longer fails `chartbook check` for a missing `repo_url`.

The "Code updated" time on pages (and "Date of Last Code Update", and a chart's `date`) is the time of the last commit that touched `src/`, `docs_src/` or `chartbook.toml`, when those are committed and unmodified. It was the newest file modification time, which on a fresh clone is the moment of the checkout — so every site built in CI claimed its code had changed just now. With uncommitted changes, or outside a git repository, the modification time is still used. Only a docs build asks git; loading a manifest (`data.load()`, `chartbook ls`) does not.

### Fixed

- `chartbook build --no-strict` on a single pipeline with a missing file crashed with `UnboundLocalError`. It now reports the missing files and exits cleanly; skipping only makes sense in a catalog, which has other pipelines left to build.
- Sphinx is now run as `python -m sphinx` with the interpreter that is running ChartBook. It used to run whichever `sphinx-build` came first on `PATH`, which could be a different Sphinx from a different environment.
- `project.readme` is honoured by `build` and `check`. Only `publish` read it; the others always looked for `README.md`.
- Importing `chartbook` no longer replaces `shutil.copy2`, `shutil.copystat` and `shutil.copymode` for the whole Python process. ChartBook still copies file contents without metadata, for the sake of shared drives, but does so in its own helpers.
- A pipeline site's front page listed two appendix documents that do not exist in a generated site, producing two Sphinx warnings on every build and forcing that page to be re-read on every run. The entries are gone.
- `chartbook create-data-glimpses` crashed on a numeric column with no non-null values.
- A pipeline loaded from the relative path `.` derived the name `pipeline` instead of its directory's name, because `Path(".")` has no name. The directory is now resolved first.

### Removed

- `create_data_glimpses.create_xml_report()`, which nothing called.

## [0.1.1] - 2026-07-23

### Changed — `install skill` defaults to user-level

`chartbook install skill` now installs to `~/.claude/skills/chartbook/` (honoring `$CLAUDE_CONFIG_DIR`), making the skill available in every Claude Code session rather than one repo; the previous per-repo behavior moved behind `--project`. The command is now idempotent ("already up to date" when the installed files match), removes files from older skill layouts on install, and records the installing chartbook version in a `.chartbook-skill-version` stamp.

## [0.1.0] - 2026-07-22

The format-v2 release. Everything below ships together: the breaking `chartbook.toml` redesign, catalog auto-discovery, single-install packaging, Sphinx 9 support, and rebuilt documentation.

### Changed — single install, extras retired

`pip install chartbook` now installs everything: data loading, plotting, the Sphinx documentation toolchain, and the `chartbook init` scaffolder. The old `[data]`, `[plotting]`, `[sphinx]`, and `[all]` extras remain as deprecated no-op aliases — specs like `chartbook[all]` still resolve and now install the same full package — and will be removed in a future release. `pandas-datareader` is now a declared dependency, so NBER recession shading (`nber_recessions=True`) works out of the box. The `[dev]` extra (contributor tooling) is unchanged. Longer term, the package may split into `chartbook-data` / `chartbook-plot` distributions that `chartbook` depends on; `pip install chartbook` will keep meaning "you get it all".

### Changed — Sphinx support widened to 9.x

The Sphinx constraint is now `>=7.2.6,<10` (was `<9.0`), verified against Sphinx 8.2 and 9.1 across pipeline, catalog, and API-doc builds. The test suite now runs a Sphinx version matrix (7.4 and 8.2 pinned on Python 3.13, with newer majors covered by the unpinned Python matrix), so every supported Sphinx major is exercised in CI.

### Added — catalog auto-discovery (`pipelines.members`)

A catalog's `[pipelines]` table now accepts reserved keys for glob-based membership, aimed at local catalogs so new projects join without `catalog add`:

- `members = ["../my_repos/*", ...]` — path patterns (relative to the catalog) whose matched directories join under their derived scoped IDs. Globs skip non-pipeline directories and catalogs silently; literal paths that are broken, v1-format members, and duplicate derived IDs are hard errors with "To fix" suggestions.
- `disabled = ["scope/name", ...]` — switch member pipelines off by ID (unknown IDs warn with a did-you-mean); `chartbook catalog disable/enable` maintains this list for member-discovered pipelines.
- `exclude = [...]` — paths removed from matching.
- Explicit entries coexist and override members pointing at the same directory; a plain string entry value is now shorthand for `{ path = ... }`.
- `chartbook catalog add` recognizes paths already covered by a members pattern, and manifest-loading errors in `build`/`ls`/`data` commands now print as clean messages instead of tracebacks.

### Changed — **breaking: chartbook.toml format v2**

The manifest format was redesigned; v1 files are no longer supported. Run `python scripts/migrate_toml_v2.py <project>` to rewrite a v1 file. The full specification and the reasoning behind each decision are in the {doc}`design doc <design/toml-format-v2>`.

- The `[config]`, `[site]`, and `[pipeline]` sections are consolidated into a single `[project]` table. Every field is optional with sensible defaults (`name` defaults to the directory name, `copyright` to the current year, `maintainer` to the first contributor, …). The minimal valid pipeline manifest is an empty file.
- `chartbook_format_version` is removed. Project `type` is inferred from structure (`[pipelines]` registry → catalog, otherwise pipeline); explicit `type` is allowed and contradictions are hard errors.
- Entity fields are de-prefixed across `[charts]`, `[dataframes]`, `[notebooks]`, and `[notes]` (e.g. `chart_name` → `name`, `dataframe_id` → `dataframe`, `path_to_parquet_data` → `path`, `topic_tags` → `tags`, `*_docs_str` → `docs`, `*_docs_path` → `docs_path`). Every entity's primary artifact is now `path`.
- **Scoped pipeline identity**: pipelines are canonically identified as `scope/name` (e.g. `ftsfr/crsp_treasury`), derived from the git remote and directory name. `data.load(pipeline=...)` accepts bare names (when unambiguous), scoped names, or repository URLs; ambiguous bare names error with candidates. `scope/name@rev` is reserved for future version pinning. Catalog `[pipelines]` keys are scoped IDs (quoted), with `path` replacing `path_to_pipeline`.
- **Catalog policy**: requiredness moved out of the format. A catalog may declare `[policy]` (`mode = "warn"|"strict"`) and `[policy.required]` field lists per object type; strict mode fails the catalog build on missing metadata. Defaults preserve the old diagnostics behavior.
- `build` replaces `build_commands`/`software_modules_command`: one string with shell-script semantics (multi-line values are one script).
- `site_dir` now defaults to `./docs_src/site/` when that directory exists.
- Unknown keys in `[project]` produce a warning with a did-you-mean suggestion, preventing silent field-name drift.
- Fixed: catalog builds now generate per-pipeline README pages and render every member pipeline with the catalog theme (previously only the first member used it and README pages were skipped).

### Changed — documentation overhaul

The documentation was rebuilt around user tasks for this release: a `chartbook init`-based quick start (verified end-to-end), two consolidated guides (*Documenting a Pipeline* and *Catalogs and Data Access*) replacing the per-noun user guide, and a CLI reference regenerated from the actual command surface (adding `catalog build/browse/disable/enable` and `--strict`, dropping invented environment-variable and exit-code tables). Sections documenting features that don't exist (Trino upload, `chartbook.excel`, `chartbook.spec_reader`) were removed, duplicated field references were consolidated into a single configuration reference under `reference/`, and the site now carries roughly a third of its former word count. Old page URLs under `user-guide/` moved accordingly.

## [0.0.21]

### Fixed
- `chartbook catalog build` and `chartbook catalog browse` now respect the custom catalog path set via `chartbook config`. Previously these commands always used the default `~/.chartbook/chartbook.toml` location, ignoring the `catalog.path` setting in `settings.toml`. ([#2](https://github.com/backofficedev/chartbook/issues/2))

## [0.0.20]

### Added
- New `chartbook install skill` command to install the bundled Claude Code skill into the current project. Copies skill files to `.claude/skills/chartbook/` so Claude can assist with chartbook projects. Supports `-f/--force` to overwrite without prompting. The chartbook Claude skill is now shipped with the Python package.

## [0.0.19]

### Added
- `notebook_name` is now automatically inferred from the first level-1 markdown heading (`# Title`) in the notebook when not explicitly set in `chartbook.toml`. This makes `notebook_name` optional — notebooks just need a `# Heading` cell and the title will be extracted for the TOC and sidebar.

## [0.0.18] - 2026-03-25

### Fixed
- Notebooks silently fail to appear in the sidebar and toctree when they lack a top-level markdown heading (e.g., jupytext-generated notebooks whose first cell is code). Chartbook now injects a title cell using `notebook_name` from the manifest before Sphinx rendering, and toctree entries use explicit titles so links are always generated.

## [0.0.17] - 2026-03-25

### Changed
- `chartbook catalog build` now defaults to `--no-strict` (lenient): pipelines with missing source files are skipped with warnings instead of failing the build. Use `--strict` to restore the previous behavior. `chartbook build` remains strict by default.

## [0.0.16] - 2026-03-23

### Added
- New `path_validation` module for detecting shell/platform path mismatches. Detects MINGW/Git Bash, Cygwin, and WSL environments and warns when Windows-style paths (e.g., `C:\Users\...`) are used in POSIX-like shells. Provides actionable suggestions with corrected paths (e.g., `/c/Users/...` for Git Bash, `/mnt/c/Users/...` for WSL).
- Path validation integrated into `catalog add`, `build`, `browse`, and `publish` commands, as well as TOML path resolution in `manifest.py`.

### Changed
- Renamed `validation.py` to `conf_validation.py` for clarity — it contains conf.py security validation, not general validation.
- Improved "No matching directories found" error in `catalog add` to show which paths were tried.

## [0.0.15] - 2026-03-22

### Added
- New `chartbook browse` command to open project documentation in your default browser. Works cross-platform (macOS, Windows, Linux). Accepts an optional output directory argument (default: `./docs`).

## [0.0.14] - 2026-03-22

### Added
- New `chartbook catalog browse` command to open global catalog documentation in your default browser.
- New `chartbook catalog add` CLI command for adding pipeline directories to the global catalog. Supports single paths, glob patterns (e.g., `/path/to/projects/*`), duplicate detection, and a `-y` flag to skip confirmation prompts.

### Changed
- **Breaking:** Replaced `--warn-missing` flag with `--strict` on both `chartbook build` and `chartbook catalog build`. The default behavior is now lenient: pipelines with missing source files are skipped with warnings and the build continues. Use `--strict` to restore the previous behavior of erroring on any missing file.

### Fixed
- Fixed empty Dataframes page in catalog builds. The toctree in `cb/dataframes.md` used paths prefixed with `cb/`, but since the file itself lives inside `cb/`, Sphinx resolved them as `cb/cb/dataframes/...` which didn't exist. Paths are now relative to the document location.

## [0.0.13] - 2026-03-11

### Fixed
- Charts silently fail to appear in the Chart List when TOML field values (e.g. `data_sources`, `topic_tags`) contain YAML-special characters like colons, brackets, or ampersands. YAML frontmatter values in chart templates are now quoted and escaped, and a post-generation validation step raises a clear error if frontmatter is malformed.

## [0.0.12] - 2026-03-09

### Added
- New `site_dir` option in `[pipeline]` for adding custom markdown pages alongside auto-generated documentation. Supports `index_toc.md` for explicit toctree control or auto-discovery of `.md` files. Site pages are copied to the docs root alongside the `cb/` directory.
- New "Build Pipeline Internals" user guide page documenting the two-stage build process, intermediate file inspection, template customization, and debugging tips.

### Changed
- All auto-generated content (charts, dataframes, pipelines, notebooks, diagnostics) is now placed under a `cb/` subdirectory in the built docs. This separates generated content from custom site pages and prevents naming conflicts. Relative links and template paths updated accordingly.
- `dodo.py` test tasks now produce JUnit XML reports, track file dependencies for incremental runs, and fail explicitly on test failures or errors.

## [0.0.11] - 2026-03-02

### Fixed
- `date_col` is now optional in `chartbook.toml` dataframe definitions. Previously, omitting `date_col` caused a `KeyError` crash during `chartbook build`. When not specified, date range fields display "N/A" in the generated docs.

## [0.0.10] - 2026-02-22

### Added
- Glob pattern support in `path_to_parquet_data` for hive-style partitioned parquet datasets. Use patterns like `_data/hive_dataset/**/*.parquet` in `chartbook.toml`. Polars `scan_parquet` handles these natively with automatic hive partitioning.
- New `format="polars_eager"` option for `data.load()` to explicitly request an eager Polars DataFrame.

### Changed
- **Breaking**: Default `data.load()` format changed from `"pandas"` to `"polars"`. The default now returns a Polars LazyFrame. Pass `format="pandas"` to restore the previous behavior.
- **Breaking**: `format="polars"` now returns a Polars LazyFrame instead of an eager DataFrame. Use `format="polars_eager"` for the previous eager loading behavior.
- `format="polars-lazyframe"` is now deprecated. Use `format="polars"` instead (which now returns a LazyFrame by default).

## [0.0.9] - 2026-02-19

### Added
- New `chartbook init` CLI command to scaffold a new chartbook project from the [cookiecutter template](https://github.com/backofficedev/cookiecutter_chartbook). Wraps `cruft create` so projects can later pull upstream template updates. Requires `pip install "chartbook[all]"` (adds `cruft` dependency).

## [0.0.8] - 2026-02-17

### Added
- New `--strip-mathjax2/--no-strip-mathjax2` CLI flag for `chartbook build` (enabled by default). Automatically strips Plotly's MathJax 2 script tags from notebook cell outputs during the build, preventing them from conflicting with Sphinx's MathJax 3 and crashing LaTeX math rendering in the generated HTML.

## [0.0.7] - 2026-02-02

### Changed
- Configuration fields in `chartbook.toml` are now more forgiving with sensible defaults:
  - `logo_path` and `favicon_path` are now optional; missing values use default assets
  - `chartbook_format_version` defaults to current version instead of failing validation
  - `copyright` auto-generates current year when the key is missing (explicit empty string `""` still respected)
  - `charts`, `dataframes`, and `notebooks` sections are now optional (default to empty)
- Minimal `chartbook.toml` now only requires `[config]` section with `type = "pipeline"`

## [0.0.6] - 2026-02-01

### Added
- `data.get_docs(pipeline, dataframe)` returns the documentation content for a dataframe as a string (works with both `dataframe_docs_path` and `dataframe_docs_str` modes)
- `data.get_docs_path(pipeline, dataframe)` returns the path to the documentation source file (`.md` file for path mode, `chartbook.toml` for inline mode)
- New `chartbook ls` CLI command to list catalog objects:
  - `chartbook ls` lists all pipelines, dataframes, and charts in a tree format
  - `chartbook ls pipelines` lists pipelines only
  - `chartbook ls dataframes` lists all dataframes across pipelines
  - `chartbook ls charts` lists all charts across pipelines
  - Supports `--catalog` option to override the default catalog
- New `chartbook data` CLI command group for data operations:
  - `chartbook data get-path --pipeline <id> --dataframe <id>` prints the parquet file path
  - `chartbook data get-docs --pipeline <id> --dataframe <id>` prints the documentation content
  - `chartbook data get-docs-path --pipeline <id> --dataframe <id>` prints the documentation source path
  - All commands support `--catalog` option to override the default catalog

### Changed
- `data.get_path()` renamed to `data.get_data_path()` for clarity
- Data download links (Parquet/Excel) are now disabled by default in generated documentation. Set `enable_data_download = true` in the `[site]` section of `chartbook.toml` to enable them.

### Fixed
- Fixed "Linked Charts" not rendering correctly in dataframe documentation pages. The linked charts are now displayed as a bulleted list below the metadata table instead of inside a table cell.
- Extended full-width page layout to dataframe, pipeline, and diagnostics pages (previously only chart pages had full-width styling).
- Fixed Git Repo URL in pipeline manifest displaying a broken icon (box character) by converting it to a proper markdown link.

## [0.0.5] - 2026-01-26

### Added
- Catalog-aware data loading: `data.load(pipeline="yield_curve", dataframe="repo_public")` loads dataframes from registered pipelines in a catalog
- `data.get_path()` returns the resolved parquet path for a pipeline's dataframe
- `polars-lazyframe` format option for `data.load()` (returns `pl.scan_parquet`)
- New `chartbook config` CLI command to set the default catalog path in `~/.chartbook/settings.toml`
- New `chartbook.config` module for reading/writing global settings
- `CatalogNotConfiguredError` exception with actionable message when no catalog is configured

### Changed
- `data.load()` and `data.get_path()` now use `pipeline` and `dataframe` parameters (replaces `pipeline_id`, `dataframe_id`, `base_dir`)
- `tomli` and `tomli_w` moved from the `[data]` optional dependency group to base dependencies

## [0.0.4] - 2026-01-22

### Added
- New `--warn-missing` CLI flag for `chartbook build` to warn instead of error when source files are missing.

### Fixed
- Fixed notebook rendering in Sphinx documentation where notebooks were not appearing in the generated docs. The `notebook_list` was incorrectly using dictionary keys instead of the actual notebook paths, resulting in toctree entries missing the `.ipynb` extension.
- Build process now validates that all source files (notebooks, charts, dataframes) specified in `chartbook.toml` exist before starting the build. Missing files now produce a clear error message with the file path and the `chartbook.toml` entry that references it. Use `--warn-missing` to continue with warnings instead.

### Changed
- Standardized all docstrings across the codebase to use Sphinx-style format with `:param`, `:type`, `:returns`, and `:rtype` tags for improved API documentation rendering

## [0.0.3] - 2026-01-16

### Added
- New `chartbook.env` module (renamed from `chartbook.settings`) for project path management
  - `get_project_root()` function with configurable `start`, `markers`, `max_levels`, and `use_cache` parameters
  - `get_os_type()` function for cross-platform scripts (returns "nix", "windows", or "unknown")
  - `get()` function (renamed from `config()`) for reading environment variables and `.env` files
  - `clear_cache()` function to reset cached project root lookups
  - `ProjectRootNotFoundError` exception with helpful error messages
  - Backwards compatibility alias: `config = get`

## [0.0.2] - 2026-01-03

### Added
- New `chartbook.plotting` submodule for creating charts directly from DataFrames
  - Simple, consistent API for common chart types: `line()`, `bar()`, `scatter()`, `pie()`, and `area()`
  - `dual()` function for dual-axis charts combining different chart types on left and right y-axes
  - Built-in support for chart overlays: NBER recession shading, horizontal/vertical reference lines, shaded regions, confidence bands, and regression lines
  - `ChartResult` object with `.show()` for inline display and `.save(chart_id)` for multi-format export (HTML, PNG, SVG)
  - Global configuration via `configure()` for default output directory, backends, NBER recessions, and styling
  - `set_style()` for applying matplotlib styles, including a bundled "chartbook" style
  - Support for both Plotly (interactive) and Matplotlib backends
  - Rich annotation support: titles, captions, notes, and source attribution


### Added
- Initial release