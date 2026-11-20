# Design: one command to know

```{note}
A design document, written 2026-11-19 from two days of talk with the maintainer, who found the
package's surface confusing: 23 commands (45 with their subcommands), four of which check
something and four of which write the lockfile. He asked for clarity before completeness: a
handful of commands that are enough for nearly everything, and freedom to change anything, since
the package is hardly used yet. It is for 0.6.0.

Status: **to be built, step by step, in "The order of work" at the end.** Each part says whether
the maintainer decided it, and when. A choice he left open is marked *Proposed by Claude*, with
its date, until he says otherwise. The page was read against the code by a reviewer before
anything was built; what that changed is marked *(found by review)*.
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
  A snapshot is of a commit: commit, and `chartbook run` again.
```

**2. Commit, and build again.** The build tool finds little to do, and the run ends with a
snapshot: this version of the pipeline is now in your store, where your other pipelines can read
it. (Whether a run also clears older snapshots is not settled: see "Clearing old snapshots"
below, and {doc}`snapshots-and-increments`.)

```text
$ git add -A && git commit -m "Yields through October" && chartbook run
acme/rates: build
acme/rates at 4f2a91c: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook pin --update`.
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
Add it to [dependencies] and build again? [Y/n]: y
Added to [dependencies] in /work/report/chartbook.toml: "acme/rates" = {}
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
Fetching https://github.com/ftsfr/he_kelly_manela, to see what ftsfr/he_kelly_manela reads in turn.
Fetching https://github.com/ftsfr/fed_yield_curve, to see what ftsfr/fed_yield_curve reads in turn.
acme/report cannot be built yet: 3 pipelines it reads are not in the store at /Users/x/.chartbook/store.
Build them in this order. Each ends with a snapshot, which is what the next one reads.

1. ftsfr/he_kelly_manela at 7802799    https://github.com/ftsfr/he_kelly_manela
     git clone https://github.com/ftsfr/he_kelly_manela /work/he_kelly_manela
     cd /work/he_kelly_manela && git checkout 7802799 && chartbook run --snapshot
2. ftsfr/fed_yield_curve at 5bb7217    https://github.com/ftsfr/fed_yield_curve
     git clone https://github.com/ftsfr/fed_yield_curve /work/fed_yield_curve
     cd /work/fed_yield_curve && git checkout 5bb7217 && chartbook run --snapshot
3. acme/rates at 4f2a91c    ../rates (a folder on this machine); reads 1 and 2 above
     cd /work/rates && git checkout 4f2a91c && chartbook run --snapshot

Then here again:
     cd /work/report && chartbook run
Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has them, or wait for its sync to finish.
```

**6. Look.**

```text
$ chartbook catalog open
The catalog's site is behind your stores: 3 snapshots are not in it yet. Build it before opening? [Y/n]: 
```

## What `chartbook run` does, in order

1. **Reads `chartbook.toml`,** and stops on a fault in it. *As today.*
2. **Pins** what `[dependencies]` declares and the lockfile does not have. A pin that exists is
   never moved. *As today.* Where something it reads is not in the store, it prints the list of
   scenario 5 and stops.
3. **Runs the build script.**
4. **Asks, when the build stopped on a read of a pipeline that is not declared** (scenario 3).
5. **Looks for what was declared.** An output that `chartbook.toml` declares and the build did
   not write is a failed run: `acme/rates: its build did not write 1 thing chartbook.toml
   declares: forgotten (./_data/forgotten.csv)`. Today the run says `Ran build` and exits 0.
6. **Makes a snapshot, when everything is committed** (scenarios 1 and 2).
7. **Clears this pipeline's old snapshots from the store.** A run makes a snapshot every time, so
   it also takes away the ones nothing needs any more. Only this pipeline's. *Which those are was
   decided again on 2026-11-19: see "Clearing old snapshots" below.*

*Decided 2026-11-18 (items 4, 5 and 6, as proposed by Claude and taken up by the maintainer) and
2026-11-19 (item 7, the maintainer's).*

- **When there is no snapshot, the run still succeeds.** Each reason is one line that says why,
  and exit 0. A build is not a failure for being unfinished work. *Decided 2026-11-19.*

What was left open, *proposed by Claude, 2026-11-19:*

- **"Committed" is looked at before the build, and again after,** as `run --snapshot` looks today:
  the commit the build started at is the one a snapshot is of. A build that changes a file git
  tracks, or a commit made while it ran, means no snapshot, and the line says which. *(Found by
  review: the page did not say when.)*
- **The lockfile counts.** The page first said it did not, "since the run itself writes it", as
  `run --snapshot` has it. But whoever builds a snapshot's commit again reads what that commit's
  lockfile pins, and a snapshot is now made at every run and not on purpose. So a plain run that
  had to write `chartbook.lock` says `chartbook.lock was written during this run, and is not
  committed`, and the next run ends with the snapshot. *(As built, after the review of the code,
  2026-11-19.)*
- **And only where a branch is checked out.** A commit checked out by its hash is an old version
  being looked at or built again, and a snapshot of it would be the newest of its pipeline:
  what the next `pin --update` of anything that names the pipeline takes. There the run says
  `not snapshotted: no branch is checked out; chartbook run --snapshot makes a snapshot of this
  commit`. *(Found by review: "the newest" is the one made last, on whatever branch.)*
- **Whatever else stops a snapshot is said the same way:** a folder in no git repository, a store
  that cannot be written or is not there, a `chartbook.links.toml` in the folder, a gap in what it
  was pinned to. A pipeline that declares nothing yet is told nothing, whatever state its folder
  is in. And a run asks no question about its snapshot: not which store (it follows the catalog,
  to its first store where the catalog sends the pipeline nowhere), and, in a plain run, not
  whether to make a catalog. *(Found by review: a snapshot can be refused for more reasons than
  the page named, and can ask.)*
- **Not built: a store that is away is still made.** The page proposed that a store that is not
  there is not made, so that a share that is not mounted does not become an empty folder. It was
  built twice and taken out twice. As a rule of `run`, it was passed by the pin before the build,
  which makes the store first. As a rule of the store, it refused `chartbook store export` to a
  new folder, and stopped `pin` and `run` where the catalog's first store was away and every pin
  was in another, since a lockfile's note is written to the first store. So a store is made by
  its first write as it always was, folders above it and all. Doing this rightly means looking
  at each thing that writes a store, with several stores in mind, and is its own change. *(After
  two reviews of the code, 2026-11-19.)*
- **Any branch.** A run on a branch of an experiment ends with a snapshot as one on `main` does,
  and that snapshot is then the newest of its pipeline: what the next `chartbook update` of a
  pipeline that names this one takes. In a store of one's own that is what is wanted. In a store
  a team shares it is a question for the maintainer, not yet asked when this was built: see
  "Later", `chartbook publish`. *(Found by the review of the code, 2026-11-19.)*
- **`chartbook run --snapshot` is the strict form,** as it is today: it refuses to build with
  anything uncommitted, on a branch or not, and fails if no snapshot can be made. For a script
  that must end with one, and for building someone's pipeline at the commit they pinned
  (scenario 5).
- **`chartbook run --frozen` pins nothing and makes no snapshot.**
- **The same files make no new snapshot,** as today. The files are hashed each time to find that
  out.
- **What counts as declared (item 5):** whatever `chartbook.toml` gives a `path` that the build is
  to write, which is what `chartbook check` calls an output today. A dataframe that is a table or
  a query in a source has no file, and is not looked for; the file of its DuckDB source is, since
  the check that failed for one is gone *(found by the review of step 4)*. `chartbook snapshot` stays as it is: it
  takes what is built, and lists what is not. *(Found by review.)*
- **The catalog's site is not built by a run.** It takes a Sphinx build for each new version, and
  can fail for reasons that are not the build's. It is built when it is looked at (scenario 6).
  *Decided 2026-11-19.*
- **`chartbook snapshot` stays,** for a snapshot of what is already built, and for a pipeline that
  has no build script.
- **Only the `build` script** is followed by 5, 6 and 7. `chartbook run test` runs `test`.

### Clearing old snapshots

*Decided 2026-11-19: a run clears the old snapshots of its own pipeline.* *Proposed by Claude:*

```{admonition} Built, and held back
:class: warning

This was built as written below, and a review of it reproduced four ways in which gc's rules,
applied at every run with no list and no question, remove something that is still needed. It is
not merged, and waits for the maintainer.

1. **A pin the store has no note of.** A consumer's `paper` branch commits a lockfile that pins
   January's snapshot, and its `main` moves on to February's. The upstream's next run removes
   January's and says nothing pins it. So too for a reader whose store is read-only to them,
   as a class's is: their pin leaves no note.
2. **A run in a checkout that lacks a mark.** `keep = true`, a label, a tag and a branch are read
   from the folder the run is in, and from the newest snapshot, which that run has just made. A
   run at a commit from before `keep = true` was written removed two of three kept versions.
3. **A commit checked out by its hash.** `chartbook run --snapshot` says `No new snapshot: the
   same bytes … as the one made 2026-01-01`, and then removes that one.
4. **Lineage.** An upstream's run removes what `chartbook snapshot --deep` downstream walks to.

`chartbook store gc` has the same rules, and lists and asks first. Put to the maintainer on
2026-11-19: a run removes nothing, says in a line what could go, and `chartbook store gc
PIPELINE` lists it and asks (proposed); or a run removes with what can be closed closed, a
longer window, and the first case accepted; or as written.

*Decided 2026-11-19: none of the three.* The maintainer chose a rule by rows: a run clears an
older snapshot when the new one holds all of its data. It is in {doc}`snapshots-and-increments`
("Clearing"), where two forms of it were broken by review before anything was built, and it is
held there. Until that page says otherwise a run clears nothing, the line on what `chartbook
store gc` could clear stays, what is written below is not to be built, and the branch that built
it is not to be merged.
```

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
  under `--frozen`, and not in a store that cannot be written.
- **`chartbook snapshot` clears the same way.** A snapshot made by hand is a newer snapshot too.
- **The reminder goes.** Since 0.5.0 a snapshot has ended by saying how much `chartbook store gc`
  could remove; that is now done for the pipeline at hand, so the line and `--no-gc-reminder` are
  removed. The rest of the store is still `chartbook store gc`'s.

## What happens to `check`

Nobody types it. Before a build its findings are about files that are not there yet, and
`chartbook run` does not call it after one. So:

- What a person needs from it, `run` does: steps 1, 2 and 5 above.
- What CI needs from it, an answer in seconds with nothing built, is **`chartbook run --check`**:
  what `chartbook check` reports today, with its `--policy` and `--within`, and with an output
  that is not built listed as *not built yet* and counted as no problem (`--skip-outputs` goes).
  It looks at the manifest and the folder, as `check` does. Whether what is pinned is in the store
  is `chartbook pin --check`'s question, and stays there: a CI runner with no store passes the
  first and not the second. *(Found by review: the two together would fail the template's CI.)*
  It asks for more than a run does: a policy's fields, a license's date.
- **`chartbook check` is gone.** Typed, it says `chartbook check is gone: chartbook run --check`,
  as `chartbook build` does of itself, and does nothing. *Decided 2026-11-19: removed now, not
  kept for a while. The package is hardly used yet, and the house is cleaned quickly.*

*Decided 2026-11-18: `check` is not something people learn. `run --check` and what it counts,
proposed by Claude, 2026-11-19.*

A cost of removing a command, said once: a commit whose build file calls `chartbook check` or
`chartbook update` cannot be built by 0.6.0, and a pinned commit cannot be edited. The template's
CI file and this repository's examples call `check` and are changed with it. Of the class's
pipelines, looked at on 2026-11-19, none calls either in a build: the six upstreams call only
`chartbook docs build`, and the report names `chartbook update` in its README and in comments.

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
  is not declared is refused, as today, and leaves a note for the run that started it: which
  pipeline was asked for, and from which pipeline's folder. Nothing scans source files for names.
  The error the read prints names `chartbook add` where the store has snapshots of that pipeline,
  and tells as today how to write an entry by hand. A build whose command is `chartbook run
  analyze` passes the note up to the run that was typed.
- **It asks only where yes can work:** at a terminal; for a read made from this pipeline's own
  folder; and where the stores have exactly one pipeline of that name, made in one repository.
  Otherwise the build's error stands, as today: in CI, under `--frozen` and `--snapshot`, for a
  name two pipelines in the stores share, for an ID two repositories claim, and for one the
  stores do not have (a folder or a repository is declared by hand). *(Found by review:
  `chartbook add` writes a name the stores lack, and the pin then fails.)*
- **Yes writes what `chartbook add` writes,** pins, and runs the build again, as the same run but
  for `--force`: what that rebuilds was rebuilt a moment before. One pipeline at a time: a build
  stops at the first read it is refused, so the second asks again if the code reads another.
- **The question is asked of who is there now.** Keys pressed while the build ran are thrown away
  before it is shown, so an Enter typed ten minutes ago is not a yes; and Ctrl-C at the question
  ends the command.
- **That run makes no snapshot:** `chartbook.toml` has just changed, and is not committed. It says
  so, as scenario 1 does.
- **`chartbook add` stays.** Nobody has to know it.

## What is not in your store

*Decided 2026-11-19: a list, in order, with what to type; ChartBook does not build them itself
yet (see "Later").* *Proposed by Claude, 2026-11-19:*

- **What is on the list:** a dependency with no snapshot to pin; and one that is pinned, where the
  store has neither the pinned snapshot nor any build of yours of that commit. A build of yours
  that is there and does not meet the pins is not on it: that is said as it is today, with the
  periods that differ and `chartbook pin --update` as the way to read your build.
  *(Found by review: it would have been listed again for ever.)*
- **It goes up.** For each one on the list, its own `chartbook.toml` and `chartbook.lock` at the
  commit to be built are read, and whatever of *its* dependencies your store lacks is on the list
  before it. A folder on this machine is asked through git for those two files at that commit,
  and is not changed. A repository is fetched into ChartBook's git cache, as a `git` dependency
  is today.
- **A line says what is known, and no more.** The lockfile records a commit for what is pinned,
  and a repository only where the snapshot it was pinned from had one. So a line may lack its
  address (`its repository is not recorded`, with the pipeline's ID to look for), its commit (a
  dependency that was never pinned: any commit of it will do), or what it reads in turn (its
  repository could not be fetched, or its lockfile is not in that commit). It never guesses.
  *(Found by review.)*
- **The order is the order to build in:** each pipeline after everything it reads. One pipeline
  wanted at two commits is two lines.
- **A cycle is an error,** in the words `run` and `pin` already use for one: which pipelines are
  in it, and for each step from one to the next, the file it was read from. There is no order to
  build a cycle in.
- **`run` and `pin` make the list.** `run --check`, `pin --check` and `run --frozen`, which fetch
  nothing, name what this pipeline itself lacks and say that `chartbook run` lists the rest.
- **What `run` builds by itself today, it still builds:** a `git` dependency, in ChartBook's own
  copy of it; a dependency named by its ID that the store has no snapshot of, where the settings
  name a host to clone it from; and, with `--upstream`, a folder on this machine. The list is for
  the rest. *(Found by review: the page read as if nothing were built today.)*

*Built 2026-11-19* (`chartbook/missing.py`), with what building it settled:

- **Every command can be pasted from any folder.** The proposal's `git clone … && cd name` made a
  clone inside the folder it was typed in, and its `cd ../rates` held only from one folder. A
  folder is named whole, and a repository is cloned beside the pipeline's own repository. The
  last lines say how to come back: `cd /work/report && chartbook run`.
- **A clone you already have is read where it is.** The pipeline's own repository, or a folder
  beside it named as `git clone` names one, whose `origin` is the address a pin records: the
  repository's files are read from it at the commit to build, nothing is fetched, and its line
  says to build there. A repository that wants a password cannot be fetched from here at all, and
  a class has its clones side by side. *(Found by review: it was first told by the ID of the
  pipeline in the folder, which took a folder of another history for the clone and missed a
  pipeline in a folder of its repository.)*
- **No command moves the pipeline's own repository.** *(Found by review: in a repository of
  several pipelines the list said `git checkout`, and its last command then built the pipeline
  itself as it was at that commit.)* What is wanted there at another commit is built in a
  worktree of that commit, and the reader's checkout stays on its branch.
- **An address is one only if it is a plain web address,** which is all a snapshot records.
  *(Found by review: one that began with `--upload-pack=` was refused by the fetch and printed in
  a `git clone` to paste.)* A pipeline's name is one only if it is an ID. Everything shown is
  shown without control characters.
- **A line written for a folder holds once the lines above it are done.** *(Found by review: one
  pipeline wanted at two commits had its second line written from where the folder was before
  the first line moved it.)*
- **The store that was looked in is named,** as it was in every message this takes the place of.
- **A line names the lines it reads:** `reads 1 and 2 above`, where "reads 2 above" could be
  taken for a count or for a line.
- **The last line is the other way on:** where a store is shared, nothing has to be built. On a
  team that is the likelier cause, and it was in every message this list takes the place of.
- **`chartbook pin --update` keeps its own words.** It asks for the newest snapshot of each, and
  the list would say to build the commit a pin names.
- **An ID the store has in other letters is not on the list.** It is a name to put right, and the
  pin says which.
- **A folder that is built and was never pinned is not built again.** With nothing uncommitted
  and every declared file on disk, its line says `built already` and `chartbook snapshot`; so
  does a pipeline with no `build` script. The words this list takes the place of said "commit,
  then run `chartbook snapshot`", and a build may take an hour. Never for a pinned one: *(found by
  review)* its files may be of another build than the pin's, and a snapshot of them would carry
  the pinned commit's name.
- **With `--upstream` to offer, the list offers it:** where every line is a `path` entry's folder
  that was never pinned and has a `build` script, `chartbook run --upstream` builds them all, and
  a line says so. *(Found by review: it was offered for a clone of a pipeline named by its ID,
  which `--upstream` does not build.)*
- **`chartbook add` undoes nothing for a cycle found here.** *(Found by review: taking the new
  entry out was wrong where the cycle was another entry's.)* The error is said, and the manifest
  is as the command left it.

## The catalog knows when it is behind

*Decided 2026-11-19: `chartbook catalog open` asks before it opens a site that is behind.*
*Proposed by Claude:* it is worked out when asked, by comparing the versions the site was built
from with the versions in the stores now. A mark left by `chartbook run` would miss a snapshot
that arrived by a synced folder from another machine. A site that was never built is behind by
all of it, and is asked for the same way, where today the command stops with an error. Off a
terminal it opens what there is and says how far behind it is.

The catalog shows snapshots. Work that is not committed yet is on the pipeline's own site, which
its build writes: `chartbook docs open`.

*Built 2026-11-19* (`chartbook.versions.behind`), with what building it settled:

- **It counts both ways.** Snapshots the stores have that the site does not show, and snapshots
  the site shows that the stores no longer have: what `chartbook store gc` cleared, here or on a
  machine that shares the store, still has its pages in the site until it is built again.
- **The word is "snapshots",** not "versions", and the question is "Build it before opening?":
  it is the site that is built.
- **No is not a refusal to open.** `n` opens the site as it is. With no site at all, `n` opens
  nothing and exits 0; where nothing can ask, no site is an error that names `chartbook catalog
  build`, as before.
- **What is only away is not called gone.** *(Found by review: with a drive away the site was
  "behind" by every snapshot it showed, and Enter at the question built a site without them.)*
  Where the site shows snapshots that are not in the stores now and a store is not there, a
  record cannot be read, or the build would stop on an ID two repositories claim, nothing is
  asked: it says that it cannot tell, and opens what there is.
- **Left as it is: a snapshot that was not all in the store when the site was built.** Its page
  says so, and the open does not ask again for it once it has arrived. Telling whether it has
  means laying it out, which is the build's work; counting it without telling would ask on every
  open for one that never arrives.
- **What the site was built from is the `index.json` beside it,** which every build writes. No
  new file, and nothing a run has to leave behind.

## Agents

*Decided 2026-11-19: one command, and more than Claude.* *Proposed by Claude:* `chartbook install
agents`, run in a pipeline's folder, installs the Claude Code skill for the user, as `chartbook
install claude-skill` does today, and writes a ChartBook section into that project's `AGENTS.md`,
which other agents read. The section is marked at its start and its end, so the command replaces
it when ChartBook moves on and leaves the rest of the file alone. Run anywhere else, it installs
the skill and says that the `AGENTS.md` half is for a project. `chartbook install claude-skill`
stays as the first half alone.

## The first screen

`chartbook --help` lists the five commands above first, under their own heading, and the rest
under "More". The Quickstart, the README and the skill teach the five first. The reference still
names every command and option, as the tests of it require, and each step below changes it for
what that step changes. *Proposed by Claude, 2026-11-19.*

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
  keep sending them there, asked for and chosen at a prompt. Today that is `chartbook store move
  PIPELINE --to NAME --keep`, and `chartbook publish` is an older command that stages a
  pipeline's files into a folder, which would take another name. *Decided 2026-11-18: `snapshot`
  is not renamed `publish`, which reads as "to the web".*
- **`chartbook run --clean`:** build this commit in a clean copy, as someone who depends on it
  would. *Decided 2026-11-18: not the default.* A run in a copy means two copies of the data, and
  most runs are of code that is not committed yet.

## The order of work

One pull request each. Each changes the reference, the skill and the assistant files for what it
changes.

1. This page. *Merged 2026-11-19.*
2. `chartbook run` looks for what was declared, and makes a snapshot when everything is committed.
   *Built 2026-11-19.*
3. A snapshot clears its pipeline's old snapshots; the reminder goes. *Built 2026-11-19 and not
   merged: see "Clearing old snapshots".*
4. `chartbook run --check`; `chartbook check` is gone. *Built 2026-11-19.*
5. `chartbook pin --update`; `chartbook update` and `pin --frozen` are gone. *Built 2026-11-19.*
6. `chartbook run` asks to add a pipeline that code reads and the manifest does not declare.
   *Built 2026-11-19.*
7. What is not in your store: the list, in order. *Built 2026-11-19.*
8. `chartbook catalog open` asks before opening a site that is behind. *Built 2026-11-19.*
9. `chartbook install agents`.
10. The first screen: `--help`, the Quickstart, the README, the skill.
