# Design: one command to know

```{note}
A design document, written 2026-11-19 from two days of talk with the maintainer, who found the
package's surface confusing: 23 commands (45 with their subcommands), four of which check
something and four of which write the lockfile. He asked for clarity before completeness: a
handful of commands that are enough for nearly everything, and freedom to change anything, since
the package is hardly used yet. It is for 0.6.0.

Status: **to be built, step by step, in "The order of work" at the end.** Each part says whether
the maintainer decided it, and when. A choice he left open is marked *Proposed by Claude*, with
its date, until he says otherwise.
```

## Who it is for, and what it does

ChartBook is for people whose analysis is split across several pipelines: a research group, a
class. It lets one pipeline use another's finished tables and charts at an exact, recorded
version, and shows all of them in one catalog.

## What everyone learns

| You want to | You type |
|---|---|
| Start a pipeline | `chartbook init` |
| Build it, make the build available to your other pipelines, and clear out its old versions | `chartbook run` |
| Take newer data from a pipeline you depend on | `chartbook pin --update` |
| Look at everything | `chartbook catalog open` |
| Teach your coding agent ChartBook | `chartbook install agents` |

That is the whole list. Every other command stays, for the day it is needed, and none of them is
needed to start. *Decided 2026-11-18 and 19: `run` does nearly everything; `pin` is the word for
the lockfile; `snapshot` keeps its name.*

## The first hour

What a person types, and what they see. The output is as it is to be built; where a line exists
today it is today's.

**1. Build.** While you are still editing, `run` builds and says why there is no snapshot yet.

```text
$ chartbook run
acme/rates: build
…
acme/rates: not snapshotted: 2 files are not committed (`git status` lists them).
  Commit, and `chartbook run` again: a snapshot is of a commit.
```

**2. Commit, and build again.** Nothing has changed, so the build tool has nothing to do, and the
run ends with a snapshot: this version of the pipeline is now in your store, where your other
pipelines can read it.

```text
$ git commit -am "Yields through October" && chartbook run
acme/rates: build
acme/rates at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
acme/rates: 2 older snapshots cleared from the store (nothing pins them; made before 2026-11-12).
```

**3. Use another pipeline's table.** You write the read, and run. Nothing was declared, so the run
asks.

```python
from chartbook import data
rates = data.load("acme/rates:treasury")
```

```text
$ chartbook run
acme/report: build
…
acme/report: its code reads from a pipeline that chartbook.toml does not declare:
  acme/rates   (in your store: 2 snapshots, the newest of 4f2a91c)
Add it to [dependencies] and build again? [Y/n] y
Added to [dependencies] in chartbook.toml: "acme/rates" = {}
acme/rates: 1 pinned
  From its snapshot at 4f2a91c, made 2026-11-19 14:02 UTC.
Wrote chartbook.lock.
acme/report: build
…
```

**4. Their data has moved on.** Your pin does not move by itself.

```text
$ chartbook pin --update
acme/rates: 1 moved
  acme/rates:treasury
    sha256:b47d6f2bd9db… -> sha256:48b68a0be6a0…
    24 new rows, through 2026-11-11; earlier rows unchanged
Wrote chartbook.lock.
```

**5. A pipeline you depend on is not in your store.** A class with no shared store, a new laptop.
The run says all that has to be built, in the order to build it, and stops.

```text
$ chartbook run
acme/report cannot be built yet: 3 pipelines it reads are not in your store.
Build them in this order. Each `chartbook run` ends with a snapshot, which is what the next one reads.

1. ftsfr/he_kelly_manela at 7802799    https://github.com/ftsfr/he_kelly_manela
     git clone https://github.com/ftsfr/he_kelly_manela && cd he_kelly_manela
     git checkout 7802799 && chartbook run
2. ftsfr/fed_yield_curve at 5bb7217    https://github.com/ftsfr/fed_yield_curve
     git clone https://github.com/ftsfr/fed_yield_curve && cd fed_yield_curve
     git checkout 5bb7217 && chartbook run
3. acme/rates at 4f2a91c    ../rates (a folder on this machine); reads 2 above
     cd ../rates && git checkout 4f2a91c && chartbook run

Then `chartbook run` here again.
```

**6. Look.**

```text
$ chartbook catalog open
The catalog's site is behind your stores: 3 versions are not in it yet. Build them before opening? [Y/n]
```

## What `chartbook run` does, in order

1. **Reads `chartbook.toml`,** and stops on a fault in it. *As today.*
2. **Pins** what `[dependencies]` declares and the lockfile does not have. A pin that exists is
   never moved. *As today.* Where something it reads is not in the store, it prints the list of
   scenario 5 and stops.
3. **Runs the build script.**
4. **Asks, when the build stopped on a read of a pipeline that is not declared** (scenario 3). At a
   terminal only: in CI the build fails as it does today.
5. **Looks for what was declared.** A dataframe, a chart, a notebook or a model that
   `chartbook.toml` declares and the build did not write is a failed run: `acme/rates: its build
   did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)`. Today the
   run says `Ran build` and exits 0.
6. **Makes a snapshot, when everything is committed** (scenarios 1 and 2).
7. **Clears this pipeline's old snapshots from the store.** A run makes a snapshot every time, so
   it also takes away the ones nothing needs any more. Only this pipeline's.

*Decided 2026-11-18 (items 4, 5 and 6, as proposed by Claude and taken up by the maintainer) and
2026-11-19 (item 7, the maintainer's).*

- **When there is no snapshot, the run still succeeds.** Uncommitted files, a folder that is in no
  git repository, a store that cannot be written: each is one line that says why, and exit 0. A
  build is not a failure for being unfinished work. *Decided 2026-11-19.*

What was left open, *proposed by Claude, 2026-11-19:*

- **What is cleared is what `chartbook store gc` would remove of this pipeline today,** by the
  same rules and no others: a snapshot that no lockfile the store knows of pins, that is not the
  newest, that no tag, branch or label names, that holds no version of an asset marked `keep =
  true`, and that was made more than 7 days ago. So a pipeline that pulls new data at every run
  keeps a week of snapshots, and what anything reads is never touched.
- **It asks nothing, and says what it did in one line.** `chartbook store gc` asks before it
  removes, because it looks at the whole store; this looks at one pipeline, after its owner has
  just made a newer snapshot of it. `chartbook store gc --dry-run` still says what is kept, and
  why.
- **In the store the snapshot went to,** and only after a run that ended with a snapshot. Not
  under `--frozen`, which writes nothing, and not in a store that cannot be written.
- **`chartbook snapshot` clears the same way.** A snapshot made by hand is a newer snapshot too.
- **The reminder goes.** Since 0.5.0 a snapshot has ended by saying how much `chartbook store gc`
  could remove; that is now done for the pipeline at hand, so the line and `--no-gc-reminder` are
  removed. The rest of the store is still `chartbook store gc`'s.
- **`chartbook run --snapshot` is the strict form,** as it is today: it refuses to build with
  anything uncommitted, and fails if no snapshot can be made. For a script that must end with one.
- **`chartbook run --frozen` makes none.** It is the form that writes nothing.
- **The same files make no new snapshot,** as today, so running twice costs nothing.
- **The catalog's site is not built by a run.** It takes a Sphinx build for each new version, and
  can fail for reasons that are not the build's. It is built when it is looked at (scenario 6).
  *Decided 2026-11-19.*
- **`chartbook snapshot` stays,** for a snapshot of what is already built.
- **Only the `build` script** is followed by 5 and 6. `chartbook run test` runs `test`.

## What happens to `check`

Nobody types it. Its findings come at the wrong time before a build (every output is "file not
found") and nothing calls it after one. So:

- What a person needs from it, `run` does: steps 1, 2 and 5 above.
- What CI needs from it, an answer in seconds with nothing built, is **`chartbook run --check`**:
  everything `chartbook check` and `chartbook pin --check` report today, in one run, with a
  declared output that is not built listed as *not built yet* and counted as no problem.
- **`chartbook check` is gone.** Typed, it says `chartbook check is gone: chartbook run --check`,
  as `chartbook build` does of itself, and does nothing. *Decided 2026-11-19: removed now, not
  kept for a while. The package is hardly used yet, and the house is cleaned quickly.*
- `chartbook pin --check` stays as it is: it is about the lockfile, which is `pin`'s.

*Decided 2026-11-18: `check` is not something people learn. `run --check` and what it counts,
proposed by Claude, 2026-11-19.*

## `pin` is the word for the lockfile

*Decided 2026-11-18.* `chartbook update` reads as "update ChartBook". So:

| | |
|---|---|
| `chartbook pin` | Pin what has no pin yet. `run` does this itself |
| `chartbook pin --update [NAME …]` | Move pins to the newest snapshot: all of them, or the dependencies named |
| `chartbook pin --check` | Whether everything pinned can be read here. Writes nothing |

**`chartbook update` is gone.** Typed, it says `chartbook update is gone: chartbook pin --update`,
and does nothing. Every message and page says `pin --update`. *Decided 2026-11-19: removed now.*
And `chartbook pin --frozen`, which has printed since it became `pin --check` that it would be
removed, is removed with it. *(Proposed by Claude, in the same spirit.)*

## `add` is asked for by `run`

*Decided 2026-11-18.* The prompt of scenario 3. *Proposed by Claude, 2026-11-19, for what it left
open:*

- **It is found when the code asks, not by reading the code.** A read in a build of a pipeline that
  is not declared is refused, as today, and the run is told which pipeline was asked for. Nothing
  scans source files for names.
- **Yes writes what `chartbook add` writes,** pins, and runs the build again. The build tool makes
  the second run short.
- **Only a pipeline the stores have** can be added this way, as with `chartbook add`. For one they
  do not have, the run says so, and that a folder or a repository is declared by hand.
- **`chartbook add` stays.** Nobody has to know it.

## What is not in your store

*Decided 2026-11-19: a list, in order, with what to type; not yet built for you (see "Later").*
*Proposed by Claude, 2026-11-19:*

- **What is on the list:** a dependency with no snapshot to pin; and one that is pinned, where the
  store has neither the pinned snapshot nor a build of yours of that commit that meets the pins.
- **It goes up.** For each one on the list, its own `chartbook.toml` and `chartbook.lock` at the
  commit to be built are read, and whatever of *its* dependencies your store lacks is on the list
  before it. A folder on this machine is read where it is. A repository is fetched into
  ChartBook's git cache, as a `git` dependency is today; where it cannot be fetched, the line says
  that what it reads could not be looked at.
- **The order is the order to build in:** each pipeline after everything it reads. One pipeline
  wanted at two commits is two lines.
- **A cycle is an error,** in the words `run` and `pin` already use for one: which pipelines are
  in it, and for each step from one to the next, the file it was read from. There is no order to
  build a cycle in.
- **`run` and `pin` make the list.** `run --check`, `pin --check` and `run --frozen`, which fetch
  nothing, name what this pipeline itself lacks and say that `chartbook run` lists the rest.

## The catalog knows when it is behind

*Decided 2026-11-19: `chartbook catalog open` asks before it opens a site that is behind.*
*Proposed by Claude:* it is worked out when asked, by comparing the versions the site was built
from with the versions in the stores now. A mark left by `chartbook run` would miss a snapshot
that arrived by a synced folder from another machine. Off a terminal it opens what there is and
says how far behind it is.

## Agents

*Decided 2026-11-19: one command, and more than Claude.* *Proposed by Claude:* `chartbook install
agents` installs the Claude Code skill, as `chartbook install claude-skill` does today, and writes
a ChartBook section into the project's `AGENTS.md`, which other agents read. The section is marked
at its start and its end, so the command replaces it when ChartBook moves on and leaves the rest
of the file alone. `chartbook install claude-skill` stays as the first half alone.

## The first screen

`chartbook --help` lists the five commands above first, under their own heading, and the rest
under "More". The Quickstart, the README and the skill teach the five. *Proposed by Claude,
2026-11-19.*

## Later

On the {doc}`../roadmap`, with what was said of each:

- **`chartbook run` builds what is not in your store, after asking.** It would clone each pipeline
  on the list above into a folder of ChartBook's own and run it there, in order, asking first
  whether you trust it and showing its repository. Its secrets would come from one folder in your
  home, `~/.chartbook/envs/<pipeline>/`, so that they are not scattered across clones. The
  maintainer's worry is that a pipeline renames its variables over time, so one file cannot serve
  every version. Proposed: one file that holds every variable any version needs, checked against
  the `.env.example` of the version being built, so that what is missing is named; and a folder
  for one version only where the same name needs another value. *Decided 2026-11-19: not now.
  Not settled: the maintainer is not sold on one file for every version, and wants the secrets
  to follow the version.*
- **`chartbook publish`:** move a pipeline's snapshots from your own store to one you share, and
  keep sending them there. The name is kept for that. *Decided 2026-11-18: `snapshot` is not
  renamed `publish`, which reads as "to the web".*
- **`chartbook run --clean`:** build this commit in a clean copy, as someone who depends on it
  would. *Decided 2026-11-18: not the default.* A run in a copy means two copies of the data, and
  most runs are of code that is not committed yet.

## The order of work

One pull request each.

1. This page.
2. `chartbook run` looks for what was declared, and makes a snapshot when everything is committed.
3. A snapshot clears its pipeline's old snapshots; the reminder goes.
4. `chartbook run --check`; `chartbook check` is gone.
5. `chartbook pin --update`; `chartbook update` and `pin --frozen` are gone.
6. `chartbook run` asks to add a pipeline that code reads and the manifest does not declare.
7. What is not in your store: the list, in order.
8. `chartbook catalog open` asks before opening a site that is behind.
9. `chartbook install agents`.
10. The first screen: `--help`, the Quickstart, the README, the skill.
