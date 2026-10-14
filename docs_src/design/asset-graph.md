# Design: the asset graph

```{note}
A design document, not a user guide. It records what the asset graph is, why each decision
went the way it did, and — in the {ref}`not-doing` section — which additions will be declined.
For how to use ChartBook today, start with {doc}`../getting-started`.

Status: design agreed. The groundwork is built (0.2.0): the reference grammar, local name
resolution, `chartbook path`, `chartbook check`, and the reserved syntax. The graph itself —
dependencies, the lockfile, the store, build records, `chartbook run` — is not. {doc}`overview`
says what is built and gives the order to build the rest. The {doc}`index schema <index-schema>`
is the first deliverable, because everything else here reads or writes it.

Revised 2026-10-12: the reference grammar moved to its own document, {doc}`references`, and
gained asset kinds (`chart/…`, `model/…`). Models became assets ({doc}`models`). The registry
rule, the scratch directory and the surface table below were brought in line with what was
decided while building the groundwork. Each change is marked where it was made.

Later the same day: the graph's first step is built, in five parts. A pipeline can declare
`[dependencies]`, by `path` or by `git`, and `chartbook check` says whether each can be found.
The store exists. `chartbook pin` and `chartbook update` write `chartbook.lock` and fill the
store. And a reference to another pipeline's asset resolves through the lockfile to the pinned
copy. Build records and `chartbook run` are not built. The notes marked *(Built: …)* say
exactly what, and {doc}`overview` ("3a, as built" to "3e, as built") lists what was settled on
the way, as *proposed*.

2026-10-13: `[scripts]` and `chartbook run` are built. Two things below were decided
otherwise by the maintainer first, and {doc}`overview` ("The snapshot model", under step 4)
is what holds where this page differs. `run` never moves a pin ("Two verbs"). And a pipeline
never reads, hashes or builds in a folder it depends on, so `run` builds the pipeline it is
run in and does not walk the graph ("Running things", "Relationship to orchestrators"). What
others read of a pipeline is a snapshot its owner makes on purpose, at a commit, with
`chartbook snapshot`; `pin` and `update` choose among snapshots and never read a folder.
```

## The problem

A pipeline today is self-contained: it declares its charts, dataframes and notebooks, and
`chartbook build` renders them. What it cannot say is that it *depends on another pipeline* —
so there is no way to build things in the right order, no way to know whether a downstream
result is stale, and no record of what any output was actually made from.

Four apparently separate wants turn out to be one mechanism:

- cross-project dependency management
- incremental builds that skip what is current
- several people (or several agents) working in parallel without recomputing or corrupting
  each other's results
- a verifiable record of how any number was produced

They all reduce to an **asset graph** whose nodes are addressable, whose edges are declared, and
whose results are addressed by a hash of everything that went into making them.

## Two design rules

These decide arguments, so they come first.

```{admonition} Rule 1 — scale to zero
:class: important

No capability may require a running service to be useful to a single user on one machine.
```

Every multi-user feature must degrade to a file-based form. A registry degrades to a git URL in a
dependency entry. Scheduled builds degrade to `chartbook run` in cron. A shared cache degrades to
the local store. Access control degrades to filesystem and git permissions.

```{admonition} Rule 2 — no features for machines alone
:class: important

Every capability aimed at automated consumers must fall out of one that already earns its place
for people.
```

Lineage lets a program prove its work and lets a person debug a bad number. Content-addressed
caching lets parallel work share results and makes one person's rebuild fast. A lockfile makes an
automated change auditable and makes a paper reproducible. Nothing ships that serves only
machines.

## Granularity: coarse outside, fine inside

The graph's nodes are **pipelines**, not individual assets. This is permanent, not a staging post,
because fine granularity already exists *inside* each node — provided by a tool better at it than
ChartBook would be.

A pipeline's `build` script is typically `doit`, `snakemake` or `nextflow run`, each of which is
itself a dependency graph that rebuilds only what is stale. The two layers compose: ChartBook owns
the graph *between* pipelines, and whatever the project already uses owns the graph *within* one.
ChartBook therefore never needs per-asset build recipes.

This also answers the obvious objection. "Any upstream change rebuilds the whole downstream
pipeline" sounds expensive, but running a pipeline means *invoking doit*, not recomputing from
scratch — so a coarse edge firing costs one invocation of a tool that then skips everything already
current. A three-hour data pull does not re-run because an unrelated dataframe moved upstream.

And the pipeline boundary is a choice the author makes, not a constraint the tool imposes. Anyone
wanting finer granularity splits one pipeline into several, paying in manifests to maintain.

**One refinement: coarse recipes, fine hashes.** The residual cost of coarse nodes is invalidation,
not compute — if a pipeline's whole output is hashed as one unit, any change marks every downstream
consumer stale. The fix needs no per-asset recipes: hash **per declared asset**, since the manifest
already lists each asset's `path`. Execution stays whole-pipeline while staleness is computed per
asset.

## Identity and location

The key is identity; the value is location. This one separation removes the need for a registry and
makes a shipped pipeline self-resolving.

```toml
# crsp_treasury/chartbook.toml
[dependencies]
"ftsfr/fed_yield_curve" = { git = "https://gitlab.internal/ftsfr/fed_yield_curve", rev = "a1b2c3d" }
"ftsfr/crsp_compustat"  = { path = "../crsp_compustat" }
```

`scope/name` stays what you write in `data.load()`, what keys the lockfile, and what labels lineage
edges. The git URL and rev are only how the content is obtained. Consequences:

- **No registry required.** Git is the distribution mechanism.
- **A shipped pipeline is self-resolving.** Someone who clones the repository can build it with no
  catalog configured and no access to your filesystem.
- **A repository move costs one line.** Every code reference, lockfile key and lineage edge still
  says `ftsfr/fed_yield_curve`. This is the trap Go modules fell into, and it stays avoided.
- **Any git host.** GitLab hosted or self-managed, Bitbucket, Gitea, Forgejo, Codeberg, SourceHut,
  Azure DevOps, `ssh://`, or a bare repository on a shared drive. Git is the protocol; the host is a
  detail — and a requirement, since many research environments run an internal host behind a
  firewall.

*(Built: the loader reads and validates this table, `chartbook.manifest.validate_dependencies`.
An entry has `path` or `git`, and `rev` only with `git`. `chartbook check` verifies that each
`path` holds a pipeline. A `git` entry is cloned by `chartbook pin` into `~/.chartbook/git/`
and pinned from the checkout (`chartbook.gitcache`). `[resolve] default_host` below is not
built, so an entry must name its `git`.*

*One consequence of "Git is the distribution mechanism" that the list above does not draw.
Git distributes what is committed. A clone of a pipeline has its code and its manifest, and
for most pipelines none of its data, which is built and git-ignored. So a `git` dependency
can be pinned only as far as its repository commits its outputs, and "someone who clones the
repository can build it" is true of the code. Getting built data needs `chartbook run` on the
clone, or a store to download from. Until one of those exists, `chartbook pin` says "not
built" and says why. Decided by the maintainer 2026-10-12: build it this way now.)*

*(2026-10-13: the first of those exists. Decided by the maintainer: `chartbook run` builds a
`git` dependency, once for a commit. A checkout is read-only, so the build runs in a writable
copy of it, `~/.chartbook/git/work/…/<commit>/`, and the dependency is pinned from that copy.
`chartbook pin` alone still pins only what the repository commits.)*

Because scope is captured from the owner path at `init`, the URL is usually inferable from the ID.
That shortcut is a *configurable* default host, never a hardcoded one:

```toml
[resolve]
default_host = "gitlab.internal.example.org"
```

The host never enters the identity.

### Collisions

Nothing enforces that `acme/rates` means one thing globally, because no registry exists to enforce
it. Two different locations claiming one ID *in the same build* is an error naming both, rather
than a silent guess.

This is acceptable because collisions only matter inside one resolution context. Two groups can
both have `acme/rates` forever and never notice. And the escape hatch is simple: **the key in
`[dependencies]` is a local name.** It usually matches what upstream calls itself, but it need not.

*(Built, and narrower than the paragraph above: `chartbook check` on a catalog reports a
dependency whose key is one of the catalog's pipeline IDs and whose `path` is a different
directory. Inside one pipeline a key cannot be claimed twice, since it is a key of one TOML
table. Because a key is a local name, a build translates it: a dependency that is one of the
build's own pipelines is written in the index by the build's ID for it. Proposed 2026-10-12;
see {doc}`overview`, "3a, as built".)*

### Reserving a future global namespace

A future registry must not break anything written today, so the grammar reserves an *optional*
registry prefix, Docker-style. The registry is the first of **exactly three** components, and
only when it looks like a host: it contains `.` or `:`, or equals `localhost`.

```text
rates                                   # bare — local catalog, must be unambiguous
acme/rates                              # scoped — what you write today
charthub.example/acme/rates             # fully qualified
registry.internal.bank.org/acme/rates   # another registry
```

```{admonition} Why "exactly three" (revised 2026-10-12)
:class: note

This document first said that *any* leading component with a `.` was a registry. That
contradicted the next sentence, because `my.group/rates` is a valid scoped ID today and would
have changed meaning. With the three-component rule it stays a scope with a dot in it, and a
registry-qualified ID always has all three parts. A registry therefore cannot be combined with a
bare pipeline name. Implemented in `chartbook.identity.split_registry`.
```

`acme/rates` means the same thing before and after any registry exists. Five things keep that true:

1. **Parse three components now**, rejecting the registry slot with "not yet supported" — the same
   treatment `@rev` gets. *(Built: `UnsupportedRegistryError`.)*
2. **One resolution chain, written down, with a hole in it**: explicit location in
   `[dependencies]`, then the local catalog, then *(reserved)* configured registries, then an error
   listing candidates. Implement one, two and four in one place and step three is a drop-in.
   *(Built: `chartbook.resolve.locate_pipeline`. It answers "where is this pipeline?" and
   says which step answered. The rule further down, that loading from an undeclared pipeline
   fails, is for its callers to apply: a caller that requires a declared dependency refuses an
   answer that came from the catalog.)*
3. **Scope ownership is a registry concern, never a format concern.** Anyone claims any scope
   locally, forever. A registry enforces ownership only for IDs qualified with its host, so existing
   users can never be squatted out of their own names.
4. **The lockfile records the resolved location, not just the ID**, or old lockfiles change meaning
   the day a registry starts resolving a name somewhere new.
5. **`publish` is not overloaded.** It already means "stage files to a directory"; pushing to a
   registry is a different verb. *(Built: `chartbook push` exists only to say it is reserved.)*

(series-addressing)=
### Addressing a series inside a dataframe

A dataframe with a date column and several value columns contains several time series. A series does
not need anywhere to *store* data — the dataframe already holds it. What it needs is an **address**,
so that documentation, units, frequency and a source can be attached to one column.

```toml
[dataframes.treasury_rates]
name = "Treasury Rates"
path = "./_data/treasury_rates.parquet"
date_col = "date"
docs_path = "./docs_src/dataframes/treasury_rates.md"

[dataframes.treasury_rates.series.dgs10]
name = "10-Year Treasury Constant Maturity"
column = "DGS10"              # defaults to the key
units = "Percent"
frequency = "Daily"
docs_path = "./docs_src/series/dgs10.md"
```

The reference grammar has an optional segment for this, separated by `#`:

```text
[registry/][scope/]pipeline:[kind/]name[#part][@rev]

ftsfr/fed_yield_curve:treasury_rates#dgs10
```

The full grammar is specified in {doc}`references`. There the segment is called a **part**: a
series is the part of a dataframe, and a file is the part of a {doc}`model <models>`.

`#` is chosen over `.`, `/` and `:` for three reasons. It maps directly onto the URL fragment of
the generated page (`…/treasury_rates.html#dgs10`), which is the primary consumer. It is not legal
inside an ID component, so the grammar stays unambiguous — whereas `.` is legal in a name and `/`
already separates scope. And it costs only a pair of shell quotes, with nothing to escape in TOML
strings or Python.

*(Built: the loader reads and validates these tables, and the {doc}`index <index-schema>` has a
`Series` record for every column. A series address does not resolve yet, and pages do not show
series yet.)*

Two properties worth noting. An explicit `column` means the **address survives a column rename** —
change one line and every reference still resolves. And because the index records each dataframe's
column list from the parquet schema anyway, *which* series exist is known without any declaration;
a `[…series.x]` table only adds documentation to one. Declaring is how you document, not how you
exist.

## Pinning and isolation

```{admonition} The resolution rule
:class: tip

A **local** reference resolves live. A **cross-pipeline** reference resolves through the lockfile
into the store.
```

`data.path("merged_rates")` names a file in this project, which you are editing, so it points at
`_data/merged_rates.parquet`. `data.path("fed_yield_curve:treasury_rates")` names another
pipeline's asset, so it points at the store object for the hash *this project's lockfile pins* —
not at the upstream's working directory.

So a downstream project reads a frozen snapshot while its upstream is mid-surgery, and concurrent
work cannot race.

This also simplifies `path` versus `rev`: **both are pinned**. The difference is only where a
refresh gets its content from — a local directory, or a git fetch.

*(Built, with one more difference that turned out to matter: a directory has the pipeline's
built files, and a git fetch has only the committed ones. See the note under "Identity and
location".)*

### Two verbs

- **`chartbook pin`** — capture the current state of upstream dependencies into the lockfile and
  store. The verb for "freeze my upstreams, I am about to spend a week in here." Distinct from
  building: it snapshots and records without necessarily running anything.
- **`chartbook update`** — move pins forward to current upstream state, and rebuild what that
  invalidates.

`chartbook run` pins anything not yet pinned, so neither verb is needed to get started. By default
it also refreshes `path` pins, because the common case is "pick up a colleague's latest."
`--frozen` refuses to move any pin and fails if the lockfile is out of date, which is what CI and
parallel automated work should use. This is the `npm ci` / `cargo build --locked` pair.

*(Built: both verbs, in `chartbook.lock`. Decided by the maintainer 2026-10-12: `pin` never moves
a pin that exists; it pins what has none, and puts back in the store what the lockfile names
and the store has lost. `update` is the one thing that moves a pin. There is no `run` yet, so
`pin` is how to get started, and `update` rebuilds nothing. `--frozen` is not built.*

*Added 2026-10-13, with `run` built. Decided by the maintainer before it was: **`chartbook
run` never moves a pin.** The second sentence of the paragraph above ("By default it also
refreshes `path` pins") is not how it works. `run` pins what has no pin, before the
pipeline's `build`, so neither verb is needed to get started; and it leaves every pin that
exists where it is, saying which have changed upstream. `update` is still the one thing that
moves a pin, and still rebuilds nothing, so picking up a colleague's latest is `chartbook
update` and then `chartbook run`. That leaves `--frozen` with less to do than this section
gives it: there is no pin for it to refuse to move. What is left is failing when the lockfile
is incomplete, which is not built.*

*Decided the same day, and larger: where a pin's bytes come from. As built in step 3, `pin`
and `update` copy what is in a `path` dependency's folder at that moment. The maintainer's
model is that they choose among **snapshots**, which a pipeline's owner makes on purpose at a
commit, and never look in the folder. See {doc}`overview`, "The snapshot model". Built the
same day: `chartbook.snapshot`, and {doc}`overview`, "4b, as built".*

*The resolution rule at the top of this section is built: `chartbook.resolve._resolve_pinned`.
A reference to another pipeline's asset goes to `[dependencies]` for the pipeline, to
`chartbook.lock` for the asset's hash, and to the store for the bytes. Decided by the
maintainer 2026-10-12: a pin is stored as a reflink or a copy and never as a hard link or a
symlink, so "reads a frozen snapshot while its upstream is mid-surgery" holds on every disk.)*

```{warning}
A cache and a pin are not the same thing, even sharing storage. A cache is an optimization: delete
it and behavior is unchanged, only slower. A pin is a commitment: delete it and the project reads
different data. They must stay separate concepts with separate garbage-collection rules — a pinned
object is reachable and must never be collected, while an unreferenced build result may be.
```

## The store

Results are kept in a store addressed by a hash of everything that went into producing them.

- **Content-addressed** means the name of a thing is the hash of *the thing itself*. Computable
  only *after* you have the content.
- **Input-addressed** means the name is the hash of everything that goes into making it — recipe,
  parameters, each input's hash, tool versions. Computable *before building anything*.

That "before" is the whole trick: it lets you ask whether anyone already has the result and skip the
work.

```text
hash = sha256(recipe + params + hash of each declared input + tool versions)
     → store/7f3a9c…-crsp_treasury-treasury_rates.parquet

1. in the local store?   use it
2. in a remote store?    download it          ← a "substituter"
3. otherwise             build it, store it
```

Step two is borrowed from Nix, which calls a remote cache a *substituter* because it substitutes a
download for a build. It is safe because an identical input hash means identical inputs. Snakemake's
between-workflow cache, Bazel's remote cache and Nextflow's `work/` directory with `-resume` are the
same idea.

```{important}
Keep the boring files. `path` stays the real location where a parquet file lives, and the store is a
*cache* that links into it. Someone who never enables caching just sees ordinary files where they
expect them.
```

### The store needs two indexes

Input-addressing earns its keep for *lookup*; content-addressing earns its keep for *storage*. So
the build record maps input hash → output hash, and objects are held by output hash. Ten pins of a
byte-identical file become one object with ten references. Building only one index and adding the
other later is a migration, so both exist from the start.

*(Built: objects, held by content hash, in `chartbook.store`. The layout the maintainer decided
on 2026-10-12 is one directory per asset, `objects/sha256/7f/3a9c…/`, holding the asset's files
under their own names; the single file `store/7f3a9c…-crsp_treasury-treasury_rates.parquet`
sketched above is not how it is laid out. The other index is `builds/` in the same store: the
name is kept free, and nothing writes to it until build records exist.)*

*(2026-10-13: the second index that was built is `snapshots/`, and it is not keyed by an input
hash. It maps a commit of a pipeline to the hashes of what that commit built, with the bytes
kept as objects. The commit is the input a person can name and check out. Nothing looks an
input hash up, and `builds/` is still empty. {doc}`overview`, "4b, as built".)*

### Links, not copies

A **hardlink** is a second directory entry pointing at the same inode — the same bytes under two
names, each equally real, with the data freed only when the last name is removed. It costs a
directory entry rather than a copy of the file. Four strategies, tried in order:

| | Cost | Safe against in-place writes | Crosses filesystems |
|---|---|---|---|
| reflink (copy-on-write clone) | ~free | yes | no |
| hardlink | ~free | no — make the store side read-only | no |
| symlink | ~free | n/a | yes, but dangles if the target moves |
| copy | full size | yes | yes |

This ladder is DVC's, and the copy rung will be exercised rather than theoretical: a shared network
mount is a different filesystem, so neither reflinks nor hardlinks reach it. On Windows, NTFS
supports hardlinks while symlinks have historically needed elevated privileges.

*(Built: `chartbook.store.Store.put()` tries the four in this order. The maintainer confirmed
the order on 2026-10-12, when asked whether to drop the two middle rungs. Two things in this
section are not what a disk does, and are corrected here as built; proposed 2026-10-12.*

*First, "make the store side read-only". A hard link has no store side: both names are one file
with one set of permissions. Making it read-only would make the upstream pipeline's own file
read-only, and its next build would fail. So a hard-linked object is left as it is. A reflink
and a copy are the store's own bytes, and those are made read-only.*

*Second, the copy rung is rarely reached. A symlink comes before it and does cross filesystems,
so on a shared network mount an object is a symlink to the original, not a copy.*

*What follows from both: an object held by hardlink changes if the original is rewritten in
place, and one held by symlink changes whenever the original does. `chartbook store verify`
hashes every object again and reports the ones that have. The step's promise that a downstream
reads a frozen copy holds without it only on a filesystem with reflinks.)*

### Garbage collection, designed in rather than bolted on

An object is reachable if some lockfile references it; everything else is collectible. This is Nix's
GC-roots model, and it is the discipline Nextflow omitted — which is why long-lived `work/`
directories reach terabytes. Pinning makes the store grow faster than building alone would, so this
is not optional.

*(Built: `chartbook store gc`. One thing the paragraph above leaves out: with one store for
all of a user's projects, the store has to be told which lockfiles there are. Each `pin` and
`update` leaves a note of its lockfile in the store, and those are the roots. Decided by the
maintainer 2026-10-12: a lockfile that cannot be found still keeps its pins, and `gc` asks
before it removes anything.)*

## The build record, and why lineage is provable

Before building, a complete description of the build is written down, and the store path is the hash
of that description — so one object is the build plan, the cache key and the provenance record.

```json
{ "kind": "Build", "version": "chartbook/v1",
  "asset": "ftsfr/crsp_treasury:treasury_rates",
  "recipe_hash": "…", "params": { },
  "inputs": { "ftsfr/fed_yield_curve:curve": {
      "hash": "sha256:…", "via": "rev",
      "location": "https://gitlab.internal/…@a1b2c3d" } },
  "output_hash": "sha256:…", "built_at": "2026-10-11T…",
  "impure": ["wrds_fetch"] }
```

Two fields earn special mention. `impure` is honest accounting for steps that cannot be reproduced
from their inputs — a pipeline that fetches from a subscription service is not hermetic, and 90%
reproducible with a truthful record beats 100% reproducible and unusable. `via` records whether each
input came from a pinned `rev` or a live `path`, so "was this built against a stable upstream?" stays
answerable at a glance.

### Make the hashes transitive

One deliberate choice turns these records from a log into a proof: hash each input's **hash**, not
its path or name. Because those input hashes were computed the same way, an asset's hash transitively
covers its entire upstream history. That structure is a Merkle DAG — the same thing that makes a git
commit hash a complete statement about a whole repository and its history.

The implementation difference is small. What it buys is not:

- **"Up to date" becomes a check rather than a belief.** Recompute an asset's expected hash from its
  current inputs: a match means nothing upstream moved, a mismatch means something did and you walk
  down the graph to find exactly which input.
- **Lineage becomes verifiable rather than merely recorded.** A log says "I built this from X" and
  you trust whoever wrote the log. A hash chain says "this output's identity mathematically depends
  on X's content," and anyone can re-derive it.
- **Compact proofs.** "This chart came from that extract" can be shown as a short chain of hashes
  without reproducing the pipeline.
- **A safe shared cache.** A hash that covers every input transitively cannot hand you someone
  else's similarly-named result.

Two limits, stated rather than discovered later. **Impure steps break the chain by design**, so
verifiability reaches back to the last impure boundary and a digest of what arrived is recorded
there. And **it proves integrity, not correctness**: the chain shows this output came from those
inputs via that code, and says nothing about whether the code was right. Code review does not go
away. If "prove *who* built this and that the record was not altered" ever becomes a requirement,
that is signatures layered on top — in-toto and SLSA are the existing vocabulary.

## Paths

ChartBook hands out paths, so the manifest is the single source of truth and no path is written
twice.

```python
# dodo.py — declaring the graph
"file_dep": [data.path("fed_yield_curve:treasury_rates")],
"targets":  [data.path("merged_rates")],
"actions":  ["python src/merge.py"],

# src/merge.py — doing the work
df.to_parquet(data.path("merged_rates"))           # declared, indexed, hashed
tmp = data.scratch() / "intermediate.parquet"      # throwaway
```

One function resolves a reference to a file path; the build tool's own syntax says which direction it
points. `file_dep` means "I read this" and `targets` means "I write this," so a separate pair of
functions would only repeat what their position already says.

- **Bare names mean the current pipeline.** ChartBook finds the enclosing `chartbook.toml` by walking
  up from the caller, as git and cargo find their roots. The grammar then layers consistently:
  `treasury_rates` is local, `fed_yield_curve:treasury_rates` is another pipeline,
  `ftsfr/fed_yield_curve:treasury_rates` is fully scoped.
- **A bare name is a dataframe.** Anything else says its kind: `chart/curve_today`,
  `notebook/analysis`, `model/rate_forecaster`. Each kind has its own names. See {doc}`references`.
- **`scratch()` is for throwaway files** — not indexed, not hashed, not published, safe to delete, and
  *worktree-local* so parallel work in separate worktrees cannot collide. Scratch is private; the
  store is shared. *(Built: it is `_data/_scratch/` inside the pipeline, which ignores itself in
  git. Being inside the project is what makes it worktree-local.)*
- **Writing to an unregistered name fails immediately**, naming the table to add, rather than
  surfacing as a missing file during a build an hour later.
- **`path()` must be cheap and offline, and must fail only for a reason in the manifest.** A
  `dodo.py` is evaluated at the start of every run. So `path()` reads the raw `chartbook.toml` and
  nothing else: it opens no data file, touches no network, does not validate the rest of the
  manifest, and does not care whether the asset has been built. It raises only when the name is not
  declared or its entry has no `path`. *(This sentence used to say "incapable of failing", which
  contradicted the bullet above it.)*

### Reachable from any language

```{important}
The helper is a convenience, never a requirement. A pipeline that writes straight to
`_data/treasury_rates.parquet` keeps working, with ChartBook verifying the declared path and hashing
whatever it finds. The manifest stays the contract.
```

This matters beyond taste. Knowing what a build produced is a property of the **manifest** — after
`build` runs, every declared asset's `path` is hashed, whether the file came from Python, R, Stata, a
shell script or a spreadsheet. And the path-resolution convenience reaches every language through the
CLI:

```makefile
TREASURY := $(shell chartbook path fed_yield_curve:treasury_rates)
MERGED   := $(shell chartbook path merged_rates)

$(MERGED): $(TREASURY)
	Rscript src/merge.R
```

One resolution rule, reachable from Python, a shell, R or Stata via a system call, and any build tool
that can capture command output.

### The whole surface

| Call | Gives you | Used by | Today |
|---|---|---|---|
| `assets.path(ref)` | The file path of any declared asset | Build definitions; code that reads or writes | Built: local, and another pipeline's as pinned |
| `data.path(ref)` | The same, for dataframes only | The common case | Built |
| `data.load(ref)` | The data itself | Code doing analysis | Built, beside the older `load(pipeline=, dataframe=)` |
| `data.scratch()` | A throwaway directory — unindexed, worktree-local | Intermediates nothing depends on | Built |
| `chartbook path <ref>` | What `assets.path()` gives, on stdout | Make, shell, R, Stata | Built |

Five calls, one reference grammar. `path` matches the manifest field it reads, and it supersedes
`data.get_data_path()` rather than sitting beside it.

*(Revised 2026-10-12. This table used to have `data.path()` hand out every kind of asset. The
general call is now `chartbook.assets.path()`, and `chartbook.data` is the front door for
dataframes alone: `data.path(x)` is `assets.path(x, kind="dataframe")`. A `chartbook.models`
module will follow the same pattern. The reasons are in {doc}`references`.)*

`data.load(ref)` taking a single reference is the destination. Until cross-pipeline references
resolve, `data.load(pipeline="fed_yield_curve", dataframe="treasury_rates")` through a catalog
remains the way to load another pipeline's data, and `data.get_data_path()` the way to find it.

*(Reached 2026-10-12. `data.load("fed_yield_curve:treasury_rates")` loads the pinned copy, and
the two-argument form stays for loading through a catalog from outside any pipeline. Two
sentences further up need a qualifier now that another pipeline's asset resolves. "`path()`
reads the raw `chartbook.toml` and nothing else" is true of a local reference; for another
pipeline's it also reads `chartbook.lock` and looks in the store, and can fail for a reason in
either. And the `dodo.py` that opens this section works only once the dependency is pinned,
because a `dodo.py` is run in full before any of its tasks: see {doc}`overview`, "3d, as
built".)*

## Running things

The `build` field generalizes into a table of named commands, as `npm run`, `just` and Hatch's script
tables work:

```toml
[scripts]
build = "doit"
test  = "pytest"
fetch = """
module load python/3.12
python src/pull_wrds.py
"""
```

`build` is the one reserved name: it means "make this pipeline's assets current," and it is what the
dependency graph invokes.

```{warning}
Named scripts are not a task runner. One string per name, executed — no graph of its own, no
inter-script dependencies, no retries, no scheduling, no run history. The only graph is over
pipelines. Letting scripts depend on each other would make ChartBook the orchestrator it is
deliberately not.
```

*(Built 2026-10-13: `chartbook.manifest.read_scripts` and `chartbook.run`. `[project] build`
is read as the same thing as `[scripts] build`, and a script is run in its pipeline's own
directory with `bash -e`.*

*"It is what the dependency graph invokes" is not how it was built. Decided by the
maintainer: `chartbook run` builds the pipeline it is run in, and never builds in a folder
that pipeline depends on. That folder is somebody's work, and the pipeline reads what is
pinned, not what is there. A first version did walk the graph and run `build` in each
pipeline's folder; it was taken out before it was merged. Two things are left of the graph.
A `git` dependency is built, once for a commit, in a writable copy of its checkout, which is
how its built data comes to be pinned; `--force` builds it again. And in a catalog, the
script is run in each of the catalog's pipelines, one that another depends on first.
{doc}`overview`, "The snapshot model" and "4a, as built".)*

### The command surface

Flat for what you type daily, grouped for what you type occasionally.

```text
chartbook build              # make everything current: data, then site
chartbook run [script]       # execute a named script across the graph (default: build)
chartbook docs               # render the site only
chartbook browse             # open it
chartbook check              # the CI gate
chartbook pin                # freeze upstream state
chartbook update             # move pins forward, rebuild what that invalidates
chartbook path <ref>         # print an asset's path
chartbook ls                 # list pipelines, dataframes, charts

chartbook catalog ...        # add, build, browse, disable, enable
chartbook store ...          # gc, verify
chartbook install ...        # skill
```

This resolves an overload: `chartbook build` currently means "render the website," while `build` in a
manifest means "make this pipeline's data." Under the surface above, each word means the obvious
thing — `run` runs a script, `docs` builds docs, `build` builds everything.

Of these, `check`, `path`, `browse`, `ls`, `catalog` and `install` exist. `build` still means
"render the website" and keeps doing so until `run` exists; the rename is one breaking change,
made once, in the same release as `run`. `docs` and `run` do not exist yet. *(`pin`, `update`,
`store verify` and `store gc` were added 2026-10-12. `run` was added 2026-10-13. The rename
has not been made: it is its own part of the same step, so until then `chartbook build`
renders the website and `[scripts] build` builds a pipeline's data. `docs` does not exist
yet.)*

`pin` and `update` stay top-level rather than sitting under `build`, because they change the
project's dependency state rather than performing a build step — the same level as `cargo update` or
`npm install`.

## Loading data declares a dependency

Loading from an undeclared pipeline fails, with a message saying to declare it. The same friction as
an import needing an installed package, for the same reason: the graph becomes derivable from the
manifest without running anything, and every load is auditable.

*(Built 2026-10-12. A reference to an asset of a pipeline that `[dependencies]` does not
declare raises `DependencyNotDeclaredError`, which shows the line to add, and a `trained_on`
that names one stops the manifest loading. The catalog is asked where the pipeline is, for
the message only. And the second paragraph holds: `examples/rate_forecast` loads another
pipeline's data with no catalog configured.)*

The second-order win is larger. With dependencies declared, **the catalog is no longer needed at load
time** — the locations are in the manifest. A pipeline becomes self-contained and reproducible, and
the catalog reverts to what it is good at: discovery, browsing, and finding things you have not
declared yet.

## Relationship to orchestrators

ChartBook's runner is topological order, a process pool, an input-addressed cache and a per-asset
lock. No daemon, no queue, no retry policy, no backfill logic, no run database, no UI.

*(2026-10-13: it is less than that. Decided by the maintainer: a pipeline is not built from
another pipeline's run, so there is no order to work out except among a catalog's own
pipelines, and no pool. {doc}`overview`, "The snapshot model". The rest of this section, on
exporting the graph, stands.)*

Every one of those omissions is available by **exporting the graph** rather than reimplementing it.
There are three ways to relate to an orchestrator and only one is right: depending on one kills rule
1; replacing one means losing slowly to a better-resourced project; emitting to one is what dbt did,
and it is why every orchestrator has a dbt integration dbt did not write.

```{admonition} Acceptance test for the boundary
:class: tip

A team should be able to adopt Dagster without editing a single `chartbook.toml`. The same test
applies downward: moving parquet files to a warehouse should require replacing `path` with `source`
and `table` in the manifest, with `data.load()` unchanged. See {doc}`data-access`.
```

Dagster is the natural target, because its software-defined asset and a `[dataframes.x]` entry are
the same object — a declaration that something should exist, plus what it depends on. Airflow's unit
is a task, so an export flattens assets and loses lineage. Prefect's unit is a function, so an export
is trivial and gains the least. Both are worth supporting as acknowledged lossy exports; neither
should shape the model.

(not-doing)=
## Not doing

The restraint is the design, so it belongs in one list. Each of these is something a reasonable
contributor might otherwise add, and each would cost something named above.

- **No scheduler and no calendar.** Something else decides when a run starts — cron, CI, or a hosted
  platform. ChartBook decides what order things build in, once asked.
- **No retries, backfills, run history or run UI.** This is where a small runner becomes a worse
  Dagster. Export the graph instead.
- **No distributed execution.** A process pool on one machine. Crossing a machine boundary is where
  you hand off to a real orchestrator.
- **No dependencies between named scripts.** The only graph is over pipelines.
- **No per-asset build recipes.** The pipeline's own tool already has them.
- **No moving data files into the store.** `path` stays the real location; the store links into it.
- **No hermeticity.** Hash what you can, honestly record what you cannot.
- **No metadata ingestion connectors.** "Ingest from 200 systems" is the road every dead catalog
  took. This catalog earns its keep by being how you load data.
- **No required service, anywhere.** Rule 1.
- **No letting Airflow shape the model.** Its unit is a task; ours is an asset.
- **No Node or npm in the install path.** Any JavaScript surface ships pre-built inside the Python
  package.
- **No features for machines alone.** Rule 2.
- **No plugin system before a second implementation exists.** A contract designed from one example
  gets the abstraction wrong. Leave a seam, write the second implementation, then extract.
- **No swappable hashing, name resolution, or index schema.** These three are what make assets
  comparable, dependencies portable, and the index a contract.
- **No experiment tracking, model serving or model loading.** A {doc}`model <models>` is a declared
  asset with versions. Logging every training run is an experiment tracker's job; ChartBook records
  the models a pipeline chooses to keep, and hands out their paths. *(Added 2026-10-12.)*

## Seams, plugins, and what stays singular

Three different things get called "making it pluggable," costing wildly different amounts. A **plugin
system** — discovery, entry points, third-party registration, a versioned contract — is expensive and
only worth it once outsiders want to write implementations; the plotting backends earned theirs. A
**seam** — one internal interface everything funnels through — is nearly free and is simply good
structure. And some things are **singular by design**.

| Concern | Treatment | Why |
|---|---|---|
| Where cached bytes live | seam | Four operations: has, get, put, delete. Local now; shared or hosted later |
| Export formats | seam → plugin | An exporter is a pure function from index to bytes |
| Site renderers | seam | Publishing the index is what lets something else render it |
| Storage backends behind `data.load()` | seam | Parquet now; DuckDB, warehouse tables later. See {doc}`data-access` |
| Hash computation | **singular** | Two implementations hashing differently makes nothing comparable |
| Name resolution | **singular** | Projects disagreeing about a name makes dependencies unportable. One parser (`chartbook.refs`), one resolver (`chartbook.resolve`) |
| The index schema | **singular** | It is the contract. A pluggable contract is no contract |

## Prior art

Each of these solved a piece of this already, and the design borrows deliberately.

- **Nix** — input-addressed store paths, substituters, the derivation as build plan and cache key and
  provenance record in one object, and GC roots. Not its hermeticity, which is why Nix is hard.
- **Nextflow** — a content-addressed work directory with `-resume`, and native data lineage
  (25.04) with a versioned record schema worth reading before finalizing
  {doc}`ours <index-schema>`. Its unbounded `work/` growth is the cautionary half.
- **Snakemake** — between-workflow caching that hashes steps, parameters, software stack and inputs
  via a Merkle tree before consulting a central cache.
- **DVC** — the cache-link ladder and garbage collection. Content-addressed rather than
  input-addressed, which is why this builds a store rather than adopting theirs.
- **Cargo** — `path` versus git-and-rev dependencies, a lockfile recording what was actually used,
  and `update` as a deliberate act.
- **Docker** — an optional registry prefix with defined resolution, so short names work and
  fully-qualified ones remain available.
- **dbt** — a manifest as a build product that the surrounding ecosystem consumes.
- **Bazel and Turborepo** — remote caching as something a team buys rather than builds.
