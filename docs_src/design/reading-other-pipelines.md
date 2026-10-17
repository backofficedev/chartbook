# Design: reading another pipeline while you work

```{note}
A design document, written 2026-10-16 for the maintainer to choose between options. Each decision
shows what a data scientist would write and see under each option, and which one is recommended.
Status: **decided by the maintainer on 2026-10-16: 1a, 2c, 3b, 4b, 5b (silent), 6b.** Built by
2026-10-17: 6b (#81), 1a's dependency by ID from the store, with `commit` (#84), and 2c, 3b, 4b
and 5b (#85). Not yet: `rev` and `[resolve] default_host`, which need the repository.
```

## The story this serves

The store is in a Google Drive folder, kept in step between two machines. Each machine's
`[store] url` points at its local copy.

1. **On machine 1**, pipeline A (`acme/rates`) is built, and its owner declares the build ready:
   `chartbook snapshot`. Drive syncs the new files to machine 2.
2. **On machine 2**, pipeline B (`acme/forecast`) is in the middle of development. In a notebook,
   B's author loads A's `rates` dataframe with `data.load`. It should get A's newest snapshot from
   the store, with no clone of A, no build of A, and no decision yet about which version to keep.
3. **B is finished**, and its author runs `chartbook snapshot` in B. That should refuse unless B
   has recorded which version of A it read, so that B's snapshot carries its lineage. B's
   snapshot holds B's outputs only: A's bytes are in the store already, and B's lockfile names
   them.

## What happens today

- **Step 2 does not work.** B must declare A with a `path` (A's folder on this machine) or a
  `git` URL. With a `path`, choosing A's version needs A's folder on machine 2. With `git`,
  ChartBook clones A and builds it. Until something is pinned, `data.load("rates:rates")` fails
  with `AssetNotPinnedError: ... Run chartbook pin`.
- **A load through a catalog reads a working folder, silently.**
  `data.load(pipeline="acme/rates", dataframe="rates")` reads the file in A's folder as it is
  right now.
- **Step 3 checks nothing about dependencies.** `chartbook snapshot` in B succeeds with no
  lockfile, and records B's inputs as empty.
- **What already works, and stays.** Once B's `chartbook.lock` is committed, any machine with the
  store reads A's pinned bytes, with A's folder gone and A never built there (checked
  2026-10-16, for a folder store and an S3 store). A pipeline's own
  assets, `data.load("forecast_inputs")` inside B, are B's working files: that is what is being
  developed, and a snapshot of B captures them.

The decisions below close the gaps. They are independent enough to choose one at a time.

## Decision 1: how B names A

### Option 1a: by ID, the store first, git worked out from the ID

```toml
# acme/forecast/chartbook.toml
[dependencies]
"acme/rates" = {}
```

```toml
# ~/.chartbook/settings.toml, once per machine (or the organization's settings)
[resolve]
default_host = "github.com"
```

```python
from chartbook import data

rates = data.load("acme/rates:rates")
```

- `pin` finds `acme/rates`'s snapshots in the store by its ID, as the catalog already does.
- When A's code is needed (A has no snapshot and must be built, or its repository is wanted),
  ChartBook clones `https://github.com/acme/rates`: the URL is the ID on the default host.
  `{ git = "..." }` in the entry overrides that.
- The key is a local name, as it is today. A short one reads better in code:
  `rates = { id = "acme/rates" }`, then `data.load("rates:rates")`.
- This is the identity {doc}`asset-graph` already decided: the ID is the identity, git distributes
  code, and the host is a setting, so a repository move changes one line. Only the store lookup
  is new. `default_host` was designed there and never built.

### Option 1b: by git URL, bytes from the store

```toml
[dependencies]
rates = { git = "https://github.com/acme/rates", rev = "main" }
```

```python
rates = data.load("rates:rates")
```

- The entry says where the code is, as today. `pin` works out the pipeline's ID from the URL, and
  takes the newest snapshot in the store at or before the commit `rev` names. It builds A from its
  clone only when there is no snapshot.
- Every pin asks the git host what `rev` means, so it needs the network.
- The host is in every manifest that depends on A, so a repository move changes all of them.

### Option 1c: by ID, the store only

```toml
[dependencies]
"acme/rates" = {}
```

- The same entry as 1a, with no `default_host` and no `git`. Snapshots in the store are the only
  source: a pipeline with no snapshot cannot be read, and ChartBook never clones or builds it.
- Simplest, and it works offline. A clone of B on a machine without the store cannot get A at all.
- This is what 1a does when no default host is set, so choosing 1a includes it.

### `path`, in every option

```toml
[dependencies]
rates = { path = "../rates" }   # still allowed
```

```console
$ chartbook check
warning: acme/forecast: the dependency `rates` is a path, ../rates. It works on this machine only;
  name it by its ID, "acme/rates" = {}, to read it from the store anywhere.
```

Kept for two pipelines in one repository and for working on both at once, with a warning that
says what to write instead.

**Recommended: 1a.** It is the identity already decided, it reads the store first, which is
your use case, and with no default host it is 1c. *Decided by the maintainer 2026-10-16: 1a.*

## Decision 2: what an unpinned dependency gives you

B declares A and has pinned nothing. In a notebook:

### Option 2a: refuse (today)

```python
>>> data.load("acme/rates:rates")
AssetNotPinnedError: 'acme/rates:rates' is not pinned: ~/forecast/chartbook.lock does not list
the dependency 'acme/rates'. Run `chartbook pin` in ~/forecast.
```

### Option 2b: read the newest snapshot, every time, and say so

```python
>>> data.load("acme/rates:rates")
UserWarning: acme/rates is not pinned: reading its newest snapshot, 3f2a9c1, made
2026-10-16 22:06 UTC. `chartbook pin` records it.
<LazyFrame ...>
```

Nothing is written. A later call gets a newer snapshot as soon as one arrives in the store, so
two runs of the same notebook can read different data.

### Option 2c: pin on the first read, as `uv` and `cargo` write their lockfiles

```python
>>> data.load("acme/rates:rates")
acme/rates: pinned to its newest snapshot, 3f2a9c1, made 2026-10-16 22:06 UTC (chartbook.lock).
`chartbook update acme/rates` moves it.
<LazyFrame ...>
>>> data.load("acme/rates:rates")      # the same bytes, until you update
<LazyFrame ...>
```

```console
$ chartbook update acme/rates           # when A's owner has made a newer snapshot
acme/rates: 3f2a9c1 (2026-10-16) -> 8b41d07 (2026-10-18)
  rates: changed, 5,210 -> 5,233 rows
Wrote chartbook.lock.
```

- A pin is not a decision about the final version. It is a note of what you read, which you move
  whenever you like.
- B's lineage is right from its first read, results do not change under you, and step 3 needs no
  extra command.
- The cost is that a load in a notebook writes a file, `chartbook.lock`, which you commit with B.

### Which snapshot is "newest"

The one made last, by its owner's clock, across every branch. An entry narrows it:

```toml
"acme/rates" = { commit = "3f2a9c1" }   # exactly this one (the newest at that commit)
"acme/rates" = { rev = "main" }         # the newest at or before main's commit (asks git)
```

**Recommended: 2c,** with "newest" by time and `commit` or `rev` to narrow it. *Decided by the
maintainer 2026-10-16: 2c.*

## Decision 3: a pipeline B has not declared

```python
>>> data.load("acme/yields:curve")    # acme/yields is not in B's [dependencies]
```

### Option 3a: refuse, and say what to add

```text
DependencyNotDeclaredError: acme/forecast does not declare acme/yields. Add it:
    chartbook add acme/yields          # writes "acme/yields" = {} under [dependencies]
```

### Option 3b: read it, and warn that nothing records it

```text
UserWarning: acme/yields is not a dependency of acme/forecast: reading its newest snapshot,
a91c2e0, and recording nothing. `chartbook add acme/yields` declares it; until then
`chartbook run` and `chartbook snapshot` refuse this read.
<LazyFrame ...>
```

### Option 3c: declare it for you

The load adds `"acme/yields" = {}` to B's `chartbook.toml`, pins it, and reads it.

**Recommended: 3b.** Exploring is quick, the warning says exactly what a batch run will refuse,
and a manifest is never edited behind your back. `chartbook add` is new in every option.
*Decided by the maintainer 2026-10-16: 3b.*

## Decision 4: no snapshot, but a working folder

A has never been snapshotted, but its folder is on this machine (a `path` dependency, or the
catalog lists it).

### Option 4a: refuse

```text
SnapshotNotFoundError: acme/rates has no snapshot in the store. Its owner makes one with
`chartbook snapshot` in its folder.
```

### Option 4b: read the working file, and say so loudly

```text
UserWarning: acme/rates has no snapshot in the store: reading its WORKING version,
/Users/you/repos/rates/_data/rates.parquet, as it is right now. Nothing records this read, and
`chartbook run` and `chartbook snapshot` refuse it.
<LazyFrame ...>
```

**Recommended: 4b,** as you suggested. The hidden `--from-folder` option of `pin` and `update`
becomes this, and a lockfile never records a working read. *Decided by the maintainer 2026-10-16:
4b.*

## Decision 5: outside any pipeline

A scratch notebook with no `chartbook.toml` in its folder or above it.

### Option 5a: refuse

```text
ManifestNotFoundError: no chartbook.toml in ~/scratch or above it. `chartbook init` makes one,
and data.load then reads what it declares.
```

### Option 5b: read the newest snapshot, and say nothing is recorded

```python
>>> data.load("acme/rates:rates")
UserWarning: not in a pipeline: reading acme/rates's newest snapshot, 3f2a9c1, and recording
nothing.
```

`data.load(pipeline="acme/rates", dataframe="rates")` becomes the same read: the store's newest
snapshot, never a working folder without the 4b warning.

You suggested 5a. **I lean 5b,** for browsing and for an assistant on the command line, since
nothing here can be built or snapshotted, so there is no lineage to protect. Either is small.

*Decided by the maintainer 2026-10-16: 5b, and silent.* With no `chartbook.toml`, a script is a
one-off exploration: it loads the newest snapshot quietly, with no warning. Once a `chartbook.toml`
exists, the stricter rules above apply, and they get noisier exactly when someone makes the work
a proper pipeline. *Proposed with it, 2026-10-16:* a read of another pipeline's working folder
(4b) still warns outside a pipeline, since that warning is about which data was read, not about
lineage.

## Decision 6: what `chartbook snapshot` requires

### Option 6a: nothing about dependencies (today)

### Option 6b: every declared dependency pinned to a snapshot

```console
$ chartbook snapshot
Error: acme/forecast cannot have a snapshot: its lockfile does not match its dependencies.
  acme/rates: declared, not pinned
  acme/yields: pinned from a working folder, not a snapshot
Run `chartbook pin`, then snapshot again.
```

It is the check `chartbook pin --frozen` already makes, run first. B's snapshot then holds B's
outputs and its lockfile; A's bytes are in the store already, named by that lockfile.

**Recommended: 6b.** *Decided by the maintainer 2026-10-16: 6b, a snapshot only with full
lineage by its pins.* Being built: `chartbook snapshot` runs the `--frozen` check first, and also
refuses a dependency pinned from a working folder. An upstream asset that was not built when it
was pinned does not stop it, since B cannot have read it.

## How strict, where

"Batch" is `chartbook run` (it sets an environment variable that the `data.load` calls in its
build see), `chartbook snapshot`, `chartbook pin --frozen` and CI. Everything else is interactive.
With the recommended options:

| `data.load` of another pipeline finds | In a notebook or script in a pipeline | In a batch run |
|---|---|---|
| A pin | Reads it | Reads it |
| A declared dependency, not pinned, with a snapshot | Pins the newest, says so (2c) | `run` pins it before the build, as it does today; `snapshot` refuses (6b) |
| An undeclared pipeline | Reads the newest snapshot, warns (3b) | Refuses |
| No snapshot, a working folder | Reads it, warns loudly (4b) | Refuses |
| Nothing | Error | Error |

Outside any pipeline (no `chartbook.toml`), a read takes the newest snapshot silently; only a read
of a working folder warns.

## The order of work, if approved

1. `chartbook snapshot` refuses unpinned dependencies (6b). Small, and right in every option.
   *Built, #81 (2026-10-16).*
2. A dependency by ID, pinned from the store (1a without `default_host`, which is 1c), with
   `commit` and `rev`, and `chartbook add`. *Built, #84 (2026-10-17), with `commit`; `rev` moves to
   step 4, since it asks the repository.*
3. The interactive rules (2c, 3b, 4b, 5b) and the batch variable. *Built, #85 (2026-10-17). As
   built, a reference by the pipeline's own ID is refused unless a dependency is known to be that
   pipeline, and the batch variable is set for `build` only.*
4. `[resolve] default_host`, and building from git when there is no snapshot.

## For the maintainer to choose

All decided by the maintainer on 2026-10-16:

1. How B names A: **1a**.
2. An unpinned dependency: **2c**.
3. An undeclared pipeline: **3b**.
4. No snapshot, a working folder: **4b**.
5. Outside a pipeline: **5b, silent** (a working-folder read still warns: proposed).
6. What a snapshot requires: **6b** (built).
