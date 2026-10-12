# Stability and Deprecation Policy

What you can rely on in ChartBook, what you cannot, and what will happen before anything you rely on changes.

## Where the project is

ChartBook is pre-1.0. Until now that has meant breaking changes arrived whole: the `chartbook.toml` format was replaced outright in 0.1.0, with a one-time migration script and no loader for the old format, and the install extras were flattened in the same release. That was a reasonable way to run a project whose every user could be migrated in an afternoon. It stops being reasonable as soon as anything outside the project depends on a manifest, a command, or a file ChartBook writes.

So from the release in which this page first appears, breaking changes follow the process below. They will still happen before 1.0 — several are already designed, and are [listed here](#the-path-to-10) — but not without notice.

## What is covered

Four surfaces. A change to one of these is what "breaking" means.

| Surface | What is covered | Defined in |
|---|---|---|
| **The manifest format** | Every table, key, type, default and inference rule of `chartbook.toml`, and the pipeline-ID grammar | {doc}`configuration` |
| **The index schema** | Each record's `kind` and `version`, and the fields of that kind at that version. Covered from the first release that writes an index; none does yet | {doc}`../design/index-schema` |
| **The Python API** | What `import chartbook` exposes: `chartbook.data`, `chartbook.env` and `chartbook.plotting`; the exception classes in `chartbook.errors`; and the backend contract in `chartbook.plotting.backends` | {doc}`api`, {doc}`../guide/plotting-backends` |
| **The CLI** | Command names, arguments, options and exit codes; and the standard output of the commands meant to be captured — `chartbook path` and `chartbook data get-path` / `get-docs-path` | {doc}`cli` |

Within the Python API, a name is covered if it has no leading underscore and is documented. For `chartbook.plotting`, that is the module's `__all__`.

## What is not covered

These can change in any release. Where a change is likely to be noticed it is still noted in the {doc}`changelog <../changelog>`, but there is no deprecation period.

- **Internal modules**, even though the API reference lists them for contributors: `chartbook.manifest`, `chartbook.markdown_generator`, `chartbook.build_docs`, `chartbook.resolve`, `chartbook.identity`, `chartbook.check`, `chartbook.diagnostics`, `chartbook.cli` and the rest. That includes the dictionary `load_manifest()` returns.
- **Anything whose name starts with an underscore**, in any module.
- **The generated site**: its HTML structure, CSS classes, page URLs, and the page templates with the variables passed to them. Overriding a template is supported on a best-effort basis; an override may need updating after an upgrade.
- **Text meant for people**: the wording of messages, warnings and errors; the layout of `chartbook ls`; the layout of the `create-data-glimpses` report.
- **Intermediate build directories** (`_docs/`, `_docs_src/`) and anything in them.
- **The bundled assistant skill and the `llms.txt` files.**
- **Supported versions of Python and of dependencies** such as Sphinx. These follow upstream; a dropped version is announced in the changelog.
- **Reserved syntax.** `scope/name@rev`, `registry/scope/name`, `pipeline:asset`, `asset#series` and the `chartbook push` command are refused today as "not yet supported". They will stay refused until they are given the meaning they were reserved for. Gaining that meaning is not a breaking change.

## What counts as breaking

A change is breaking if, after upgrading and changing nothing else:

- a manifest that loaded now fails to load, or loads and means something different;
- a covered function, class or argument is gone, renamed, or returns something of a different type;
- a command or option is gone or renamed, an exit code means something else, or captured output has a different form;
- an index record of a given `kind` and `version` has lost a field, or a field has changed type or meaning.

These are **not** breaking: a new optional manifest key; a new command, option or function; a new optional argument; a new record `kind`, or a new field on an existing one; a new warning; a clearer error message; and a bug fix that makes behaviour match what was documented.

## How a breaking change happens

1. **It is announced before it happens.** The old behaviour keeps working, and warns, for at least one minor release before it is removed. In Python the warning is a `DeprecationWarning` naming the replacement. On the command line it is a `warning:` line on standard error. In a manifest it is a load-time warning naming the key and what to write instead.
2. **Where old and new cannot coexist, the old form is detected and refused, with the fix.** It is never silently read as something else. The v1 manifest check is the model: a v1 file is recognized by its shape and rejected with the command that migrates it.
3. **It lands in a minor release** (`0.x.0`) before 1.0, and only in a major release after. Never in a patch release.
4. **The changelog entry is marked breaking** and says what to change.

No migration tooling is promised. A large change may ship with a one-time script, as the v2 format did, but the commitment is to notice and a clear error, not to a tool.

After 1.0 the same four rules hold with one change: removal waits for the next major version.

## How formats carry their version

The two file formats are versioned differently, on purpose.

**The manifest has no version key, and a manifest without one is format v2.** If the format ever breaks again, a `format_version` key is introduced at that point, and its absence continues to mean v2. A version field that every file must carry from day one is cheap insurance for a format with thousands of external users and dead weight for one that does not have them yet; see {doc}`../design/toml-format-v2`.

**The index versions every record separately.** Each record carries its own `kind` and `version`:

```json
{ "kind": "Dataframe", "version": "chartbook/v1", "id": "ftsfr/fed_yield_curve:treasury_rates" }
```

That is the mechanism this policy leans on:

- Within one version of a kind, changes are **additive only**. Fields are added; none is removed, renamed or given a different type.
- An incompatible change to a kind creates a **new version of that kind** — `chartbook/v2` for charts, say — and leaves every other kind alone. One record type can move without a coordinated upgrade for every consumer.
- A consumer must **ignore record kinds and fields it does not recognize**. That rule is what makes additions safe, so it is part of the contract in both directions.
- A JSON Schema is published per kind per version.

The reasoning is in {doc}`../design/index-schema`.

(the-path-to-10)=
## The path to 1.0

1.0 is the release from which the four covered surfaces change incompatibly only in a major version. It will not be declared while a breaking change to any of them is known to be coming. There is no date.

These are known to be coming. Each is designed and none is scheduled; each will go through the process above when it lands.

| Change | Surface | Design |
|---|---|---|
| `chartbook build` comes to mean "make everything current: data, then site". Rendering only the site becomes `chartbook docs` | CLI | {doc}`../design/asset-graph`, "The command surface" |
| `[project] build` generalizes into a `[scripts]` table, with `build` the one reserved name | Manifest | {doc}`../design/asset-graph`, "Running things" |
| A chart's `dataframe` key is replaced by `inputs`, a list that may name several dataframes or individual series | Manifest | {doc}`../design/index-schema`, "Chart" |
| Loading data from another pipeline requires declaring it under `[dependencies]` | Manifest, Python API | {doc}`../design/asset-graph`, "Loading data declares a dependency" |
| `data.get_data_path()` is superseded by `data.path()` once cross-pipeline references resolve | Python API | {doc}`../design/asset-graph`, "The whole surface" |

Not on this list because they are additions, not breaks: `[dependencies]` itself, the index and lockfile, `[sources]` with table- and query-backed dataframes, and series addressing.

## Currently deprecated

Still working, and warning. May be removed in any minor release.

| What | Deprecated in | Use instead |
|---|---|---|
| `data.load(format="polars-lazyframe")` | 0.0.10 | `format="polars"`, which returns a `LazyFrame` |

## Removed

| What | Deprecated in | Removed | Use instead |
|---|---|---|---|
| The `[all]`, `[data]`, `[plotting]` and `[sphinx]` install extras | 0.1.0, as no-op aliases | The release after 0.1.1 | `pip install chartbook`, which installs everything |
| The v1 `chartbook.toml` format (`[config]` / `[site]` / `[pipeline]`) | — | 0.1.0 | Format v2; `python scripts/migrate_toml_v2.py <project>` rewrites a v1 file |
