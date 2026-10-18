# Design: trust, for a build of files on this machine

```{note}
Decided with the maintainer on 2026-10-18, after the review before 0.2.0 asked where a local
build's trust comes from. It says what a build of a pipeline's folder may do before you have said
you trust that pipeline, how you say so, and what a record of it looks like. Built with this page,
2026-10-18: `chartbook trust`, the record, and the gates.
```

## The problem

A build of a folder trusted its `chartbook.toml` completely. Three things followed. `chartbook
docs` ran a dataframe's SQL `query` to show its first rows, and DuckDB's SQL reads any file on the
machine (`read_csv('~/.aws/credentials')`), so the manifest decided what landed on a page. The
manifest's `logo`, `favicon`, `site_dir`, a note's `path` and a write-up's `docs_path` could name
any file on the disk, and the build copied it into the site. And `chartbook build` and `chartbook
run` ran the pipeline's build script, which is code. None of this matters for your own work. It
matters the day you clone a stranger's pipeline to look at it, and publish what the build made.

A build of files from a store already runs as a build of files that are not your own
(`chartbook.config.untrusted_source`, {doc}`versioned-catalog`): no template from the folder, every
template in Jinja's sandbox, only pages and pictures from the site folder, no table or query run, no
path outside the folder, no notebook run. This page brings a local folder under the same rule until
you say otherwise.

## What you say, and what it allows

You trust a **pipeline** (a folder) or a **repository** (any clone whose `origin` is it), at one of
two levels:

| Level | `chartbook docs`, `catalog build` | `chartbook build`, `chartbook run` |
|---|---|---|
| none (the default for a folder you did not make) | As a build of files from a store: no query run (the glimpse says the query was not read, and why), no template or file from outside the folder, Jinja's sandbox. The site is still built, with a warning that says how to trust the folder; a manifest that names a file outside the folder stops the render, naming the entry, as it stops a version's build. | Refused, naming the folder, its ID and the command that trusts it. |
| `render` | As your own: queries run for glimpses and the index, files the manifest names are read wherever they are. | Refused: trusted to render, not to run. |
| `run` | As your own. | The build script runs. |

`run` includes `render`. A third level later is a new word in the same file; nothing here depends
on there being two.

## How you say it

```console
chartbook trust                      # this folder, at "run"
chartbook trust --render             # this folder, to render only
chartbook trust ../rates             # another folder
chartbook trust --repository         # this folder's origin repository: every clone of it
chartbook trust --members            # in a catalog: the catalog's folder and each member folder here
chartbook trust --members --render   # the same, to render only
chartbook trust --list               # what is trusted, and how
chartbook trust --forget [PATH]      # no longer
chartbook trust --forget --repository   # no longer, for this folder's repository
```

A folder's trust covers the folders inside it, so `chartbook trust ~/GitRepositories/ftsfr` trusts
every pipeline under it, and `chartbook trust ~` would trust them all; the command says so when the
folder has no `chartbook.toml`. A repository's trust covers any folder whose `origin` remote names it
(`chartbook.identity.repository_key`), wherever it is cloned.

Two things are trusted without a record. A project `chartbook init` makes is recorded at `run` as
it is made: you made it. And under `CI` (the environment variable, as the store's notes already use
it), the checkout is trusted at `run`: the top of the git repository the working directory is in,
or the working directory itself. A runner builds its own checkout, and a pull request from a fork
runs its code in CI whatever ChartBook does. `CHARTBOOK_TRUST=all` trusts every folder at `run`
(the test suite runs so; a container that is nothing but your own code may); it is the one value
the variable takes, and another is said once, and ignored. A build of files from a store
(`CHARTBOOK_UNTRUSTED_SOURCE=1`) is never trusted, whatever the record says.

A `git` dependency is built in ChartBook's own copy of its commit, by its own build script: naming
it in `[dependencies]` is the trust for that, as installing a package is for its code, and the
pipeline that names it must itself be trusted at `run` for `chartbook build` to run at all.

## The record

`~/.chartbook/trust.toml`, this user's, beside `chartbook.toml`, `sources.toml` and `machine-id`.
Written by `chartbook trust` and by `chartbook init`, whole or not at all; read by every build on
this machine.

```toml
# Pipelines you have trusted (chartbook trust): their queries and build scripts run here, and the
# files their manifests name are read wherever they are.

[[pipeline]]
path = "/Users/me/GitRepositories/ftsfr/rates"   # resolved; the folders inside it too
level = "run"                                     # "render" or "run"
id = "ftsfr/rates"                                # for you to read; nothing goes by it
repository = "https://github.com/ftsfr/rates"
since = "2026-10-18T22:14:05Z"

[[repository]]
url = "https://github.com/ftsfr/rates"            # any clone whose origin remote is this
level = "run"
since = "2026-10-18T22:14:05Z"
```

A folder's level is the highest of every entry that covers it. The file is read as settings are:
one that cannot be read stops the command, naming the file; an entry of another shape is passed
over with a warning naming the file and the entry (TOML gives no line for a table), and a write
keeps it as it was. The `id` and `repository` of a `[[pipeline]]` entry are notes for you; a
stranger's manifest claiming your `[project] id` gains nothing, since the entry is matched by
path. A `[[repository]]` entry is matched by the folder's `origin` remote, which you set when you
cloned.

## Where the gate is

- `chartbook.config`: `trust_of(folder)` gives `"run"`, `"render"` or None, from the record, `CI`,
  `CHARTBOOK_TRUST`; `record_trust`, `record_repository_trust`, `forget_trust`, `read_trust`.
  `untrusted_source()` is unchanged: the environment variable, for a build of files from a store.
- `chartbook docs` (`cli._render_site`): a pipeline folder with no trust renders as a store build
  renders (the process sets `CHARTBOOK_UNTRUSTED_SOURCE=1` for itself before anything is read), with
  a warning that says why and how to trust it. A catalog: the catalog's own folder and every member
  folder on this machine must be trusted at `render`; one that is not is an error that lists them
  and says `chartbook trust --members`. The member folders are read from the catalog's manifest
  alone (`manifest.catalog_member_dirs`), before any member's is loaded. Mixing trusted and
  untrusted members in one build is not built: the untrusted mode is the process's. A member that
  is store-only has no folder and is unaffected.
- `chartbook build` and `chartbook run` (`run.run`, so that the library is gated as the command is):
  every folder whose script would run must be trusted at `run`, else `RunError` with the list and the
  command. The check is made once the order of the run is known, so a `git` dependency may be
  fetched into ChartBook's own cache before an untrusted pipeline is refused; nothing of either
  runs. `catalog build` as `docs`.
- `chartbook check` reads and executes nothing, and is not gated; it says the folder's level in its
  last line when the level is not `run` (for a catalog, the lowest among its own folder and its
  member folders here).
- `chartbook init` records the new project at `run` and says so in one line; when the record cannot
  be written (no home folder), it says so and goes on.

## Not doing, and later

- No prompt. A command refuses and prints the command that trusts; nothing asks a question, so a
  script's behaviour is the same as a person's.
- No trust by `[project] id`, since a manifest can say any ID.
- Rendering untrusted members of a catalog the store way, beside trusted ones, when the untrusted
  mode is no longer the process's.
- Trust carried in a shared store's notes, or by an organization's settings file. A machine's trust
  is its user's.
