# Design: a few commands to know

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

Changed 2026-11-20: **a run no longer ends with a snapshot.** `chartbook run` builds, and
`chartbook snapshot`, typed, makes the snapshot that other pipelines read. The page is rewritten
for that, and what was built first is kept as a record in "`chartbook snapshot` is typed". That
change was read against the code by a reviewer too, before it was built; what the reviewer found
is marked *(found by review, 2026-11-20)*. The page was first called "one command to know", when
a run did nearly all of it, and keeps that file name.
```

## Who it is for, and what it does

ChartBook is for people whose analysis is split across several pipelines: a research group, a
class. It lets one pipeline use another's finished tables and charts at an exact, recorded
version, and shows all of them in one catalog.

## What everyone learns

| You want to | You type |
|---|---|
| Start a pipeline | `chartbook init` |
| Build it | `chartbook run` |
| Make that build what your other pipelines read, and the catalog shows | `chartbook snapshot` |
| Take newer data from a pipeline you depend on | `chartbook pin --update` |
| Look at everything | `chartbook catalog open` |
| Teach your coding agent ChartBook | `chartbook install agents` |

That is the whole list. Every other command stays, for the day it is needed, and none of them is
needed to start. *Decided 2026-11-18 and 19: `pin` is the word for the lockfile; `snapshot` keeps
its name. Decided 2026-11-20: `run` builds and `snapshot` records, each typed. For a day the
list was five, with a run that ended in a snapshot; why it is six is in "`chartbook snapshot` is
typed".*

## The first hour

What a person types, and what they see. The output is as it is to be built; where a line exists
today it is today's.

**1. Build.** `run` pins what the pipeline reads, runs its build, and looks for what
`chartbook.toml` declares. Its last two lines are the same after every build, committed or not.

```text
$ chartbook run
acme/rates: build
…
Ran build in 1 pipeline(s).
acme/rates: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
```

**2. Commit, and snapshot.** This version of the pipeline is now in your store, where your other
pipelines can read it and the catalog shows it. Nothing is built again: a snapshot takes what the
build left on disk.

```text
$ git add -A && git commit -m "Yields through October" && chartbook snapshot
acme/rates at 4f2a91c: 2 asset(s) in the store
Snapshot made: 5 files, 23.0 MB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

Typed at a terminal where there is no catalog yet, it also asks whether to make the one that
shows it. With something not committed it makes no snapshot, and says what:

```text
$ chartbook snapshot
Error: acme/rates has changes that are not committed:
   M src/pull_rates.py
A snapshot is labelled with the commit it was built from, so everything in the pipeline's folder must be committed first.
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
  From its snapshot at 9b1e22d, made 2026-11-12 09:40 UTC.
Wrote chartbook.lock.
```

**5. A pipeline you depend on is not in your store.** A class with no shared store, a new laptop.
The run says all that has to be built, in the order to build it, and stops.

```text
$ chartbook run
Fetching https://github.com/ftsfr/he_kelly_manela, to see what ftsfr/he_kelly_manela reads in turn.
Fetching https://github.com/ftsfr/fed_yield_curve, to see what ftsfr/fed_yield_curve reads in turn.
acme/report cannot be built yet: 3 pipelines it reads are not in the store at /Users/x/.chartbook/store.
Build them in this order, with the commands below, one at a time. Each ends with a snapshot, which is what the next one reads.

1. ftsfr/he_kelly_manela at 7802799    https://github.com/ftsfr/he_kelly_manela
     git clone https://github.com/ftsfr/he_kelly_manela /work/he_kelly_manela
     git -C /work/he_kelly_manela checkout 7802799a41c2
     chartbook run --snapshot --project-dir /work/he_kelly_manela
2. ftsfr/fed_yield_curve at 5bb7217    https://github.com/ftsfr/fed_yield_curve
     git clone https://github.com/ftsfr/fed_yield_curve /work/fed_yield_curve
     git -C /work/fed_yield_curve checkout 5bb72171c0de
     chartbook run --snapshot --project-dir /work/fed_yield_curve
3. acme/rates at 4f2a91c    ../rates (a folder on this machine); reads 1 and 2 above
     git -C /work/rates checkout 4f2a91c03b6e
     chartbook run --snapshot --project-dir /work/rates

Then here again:
     chartbook run --project-dir /work/report
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
6. **Says how the build reaches other pipelines and the catalog:** commit, then `chartbook
   snapshot` (scenario 1). It makes no snapshot of the pipeline it built.

*Decided 2026-11-18 (items 4 and 5, as proposed by Claude and taken up by the maintainer) and
2026-11-20 (item 6, the maintainer's: a run does not end with a snapshot).*

What was left open, *proposed by Claude, 2026-11-19 and 20:*

- **The closing lines are the same after every build** that the run was not asked to follow with
  a snapshot. They do not look at git or at the store to choose their words, so the command does
  one thing whatever state the folder is in. They always say "commit, then": most runs are of
  work that is not committed yet, and a line that named `chartbook snapshot` alone sent the
  person straight into its refusal. They name the catalog beside other pipelines, since the
  catalog shows only snapshots and somebody with one pipeline has no other reason to make one.
  And they are two lines, the second under eighty columns for a command typed in the pipeline's
  own folder. *(Found by review, 2026-11-20: the first draft was one line of 106 columns that
  named neither the commit nor the catalog.)* What else stands in a snapshot's way is `chartbook
  snapshot`'s to say, when it is typed.
- **Not under `--frozen`,** which is for CI and for a store one may only read: a snapshot is not
  what comes next there. *(Found by review, 2026-11-20.)* And a pipeline that declares nothing a
  snapshot holds is told nothing, as before.
- **Where the run was given `--project-dir`, the command in the line has it too,** quoted for
  the shell.
- **`chartbook run --snapshot` is the build and the snapshot in one command,** as it is today,
  for a script that must end with one and for building someone's pipeline at the commit they
  pinned (scenario 5). It refuses before it builds with anything uncommitted but the lockfile,
  which its own pin is about to write, and where the store its snapshot goes to may only be
  read; it fails if no snapshot can be made; and it asks nothing about where its snapshot goes.
  The table below sets it beside the other two.
- **`chartbook run --frozen` pins nothing,** as today.
- **What counts as declared (item 5):** whatever `chartbook.toml` gives a `path` that the build is
  to write, which is what `chartbook check` called an output. A dataframe that is a table or a
  query in a source has no file, and is not looked for; the file of its DuckDB source is, since
  the check that failed for one is gone *(found by the review of step 4)*.
- **The catalog's site is not built by a run.** It takes a Sphinx build for each new version, and
  can fail for reasons that are not the build's. It is built when it is looked at (scenario 6).
  *Decided 2026-11-19.*
- **Only the `build` script** is followed by 5 and 6. `chartbook run test` runs `test`.
- **What a run builds for itself to pin, it still stores:** a `git` dependency, in ChartBook's own
  copy of it; and, with `--upstream`, a folder of yours that has no snapshot yet, which is
  snapshotted so that this run can pin it. Those are other pipelines' builds, and are as they
  were.

## `chartbook snapshot` is typed

*Decided 2026-11-20, the maintainer's:* too much had been put into `chartbook run`, and the
snapshot is a command of its own again.

For a day a plain run ended with a snapshot wherever everything was committed (step 2 of "The
order of work", built and merged 2026-11-19). Three questions that had no good answer each came
from that one thing:

- **A run on a side branch made the newest snapshot of its pipeline,** which is what the next
  `chartbook pin --update` of anything that reads it takes. In a store a team shares, that is a
  publication nobody chose.
- **Every run of committed work hashed its outputs and copied them into the store,** and a plain
  run had no way to say no.
- **Snapshots piled up behind every run, so a run had to clear them,** and each rule for clearing
  with no list and no question lost data when it was reviewed ("Clearing old snapshots: the
  record", below).

And the snapshot seldom came when it was wanted. Most runs are of work that is not committed
yet, and made none; after the commit it took the whole build again, or `chartbook snapshot` all
the same. One command that writes to the store or does not, by what `git status` says, was the
part nobody could keep in mind.

So:

- **A plain `chartbook run` makes no snapshot of the pipeline it builds,** and puts nothing of
  what it built in a store. (A pin still leaves its note there, and a pin from a repository its
  record.) Asked with `--snapshot`, it makes one.
- **`chartbook snapshot` makes one of what is built and committed,** as it always has. It does
  not run the build: it takes what is on disk, and lists what is not built. Everything in the
  folder has to be committed but what git ignores, `chartbook.lock` with the rest (scenario 2).
  It is also the only way for a pipeline that has no `build` script.
- **Which kind of snapshot it makes is `chartbook snapshot`'s own choice,** complete or an
  increment, by the rule of {doc}`snapshots-and-increments`. `chartbook snapshot --complete` asks
  for a complete one, and `chartbook run --snapshot` follows the same rule. Both come with the
  store's new layout, in that page's order of work, and not with step 11 here.
- **A snapshot made on a side branch, or of an old commit checked out by its hash, is still the
  newest of its pipeline,** as one typed there always was. It is now made on purpose. What a
  store that a team shares should take is `chartbook publish`'s question ("Later").
- **Neither a run nor a snapshot removes anything from a store.** `chartbook store gc` does, with
  its list and its question, and a snapshot goes on ending with the line that says what `store
  gc` could clear, as it has since 0.5.0. A snapshot is made when somebody asks for one, so
  nothing piles up behind a run. *Decided 2026-11-20.*
- **An agent makes a snapshot when a person asks for one.** The section `chartbook install
  agents` writes says so: a snapshot goes into a store that other people may read.

The three ways to build or snapshot, side by side *(asked for by review, 2026-11-20, which found
the page calling two of them the same)*:

| | `chartbook run` | `chartbook snapshot` | `chartbook run --snapshot` |
|---|---|---|---|
| Runs the build | Yes | No | Yes |
| Makes a snapshot | No | Yes | Yes |
| With work that is not committed | Builds | Refuses, and lists it | Refuses before it builds |
| A `chartbook.lock` that is not committed | Builds | Refuses: it is one more file | Passes over it: its own pin writes it. Commit it after |
| With several stores, which one | | May ask, at a terminal | Never asks: where the catalog sends the pipeline, or to its first store |
| Where there is no catalog yet | Makes none | Asks at a terminal, and makes one elsewhere | The same |
| Its record says ChartBook ran the build | | No | Yes |

What step 2 built for a plain run's own snapshot is taken out again: the lines `not snapshotted:
…`, each with its reason; the rule that an uncommitted `chartbook.lock` holds a plain run's
snapshot up; and the rule that a commit checked out by its hash gets none. Two things it built
are kept and moved *(found by review, 2026-11-20: the first draft dropped them)*: where a
catalog's first store may only be read, the way out (add the pipeline to `pipelines` under the
store to send it to) is now said by `chartbook snapshot`, and by `chartbook run --snapshot` and
`--upstream` before anything is built, since the list of scenario 5 has a whole class type that
command; and a run that is asked for a snapshot still asks nothing about where it goes. The
other half of step 2 stands: a run looks for what was declared (item 5).

*Built 2026-11-20* (`chartbook.cli`, `chartbook.run`), with what building it settled:

- **The way out of a store that may only be read says "add",** and names the catalog's file:
  `add "acme/rates" to pipelines under [stores.mine] in ~/.chartbook/catalog.toml`. *(Found by
  the review of the code: `pipelines = ["acme/rates"]` read as the whole line, and pasted over
  one that sent other pipelines there it sent them back.)* `chartbook snapshot` also names
  `--store`, for the one snapshot.
- **Only what the catalog says may only be read is found before a build.** A folder the system
  will not let this user write, and a store that is away, are found by the snapshot, after it.
  Nothing tries a write to find out. *(Found by the review of the code, and left.)*
- **The line for a lockfile that is all that is not committed is not said of one that was
  removed,** and its command carries `--project-dir` where the snapshot was given it. *(Found by
  the review of the code: "commit it" committed the deletion, and the command, typed where the
  person stood, built and snapshotted another pipeline.)*
- **A folder named in another letter case than the disk's is taken by the name the disk has for
  it,** by every command. A snapshot records where the disk has the folder in its repository,
  however it was spelled, so both spellings are one place and nothing is refused. *(Found by the
  review of the code: pathlib's own words had come back where the repository's folder was the
  one spelled otherwise; and where a folder inside it was, the snapshot recorded that spelling
  as the pipeline's place, and a pipeline that read the folder by its real name pinned an older
  one without a word. That was older than this step, and a run's last line now hands the
  spelling over. At first `chartbook snapshot` and `chartbook run --snapshot` refused such a
  folder, in words. A `path` dependency spelled so and `chartbook run --upstream` still met
  both faults, so the place is now told by the disk's names, where every command asks it: each
  part of the path by its parent's listing, and not by the name git gives, which is not the
  disk's where a name is in the other of Unicode's forms. On Windows the system names a folder
  as the disk does whatever was typed, and nothing was ever refused there.)*
- **A git dependency the run builds is not told of snapshots.** *(Found by a mutant no test
  caught.)*

### What it costs

Said plainly, since the day with one command hid each of these *(found by review, 2026-11-20)*:

- **A pipeline that is built and never snapshotted is the ordinary state again.** It was the
  commonest reason another pipeline could not read one, and the reason step 2 was built. The
  closing lines of every run are what there is against it. `chartbook pin --update` in a pipeline
  that reads this one says nothing of a newer build that has no snapshot: it never reads the
  folder.
- **A typed snapshot takes your word that what is on disk was built by the commit you are on.**
  `chartbook snapshot` has always said so of itself, and its record does not say that ChartBook
  ran the build; the record of `chartbook run --snapshot` does, and the catalog marks only those.
  Build, change a file, commit, snapshot: the snapshot is named for a commit that did not build
  it. That is now the taught way, and no longer the seldom one. *Decided 2026-11-20, to be built
  before 0.6.0: see "A snapshot is of what a run built", below.*
- **`chartbook snapshot` takes what is there.** After a run that failed for an output its build
  did not write, a snapshot is still made of the rest, with the missing one listed, as it always
  was. And one typed while a build is running takes the files as they are at that moment.
- **An asset marked `keep = true` is kept by the store once a snapshot holds it,** and not by a
  run. After a build that cost something: commit, and snapshot.
- **"Commit, then" is the owner's advice, and wrong at a commit somebody else pinned.** A run
  there that writes `chartbook.lock` leaves one file uncommitted; committing it makes a commit
  nobody else has, and a snapshot of that meets no pin. `chartbook run --snapshot` is the way
  there, as the list of scenario 5 says, since it passes over the lockfile. So where
  `chartbook.lock` is all that is not committed, the refusal of `chartbook snapshot` names it.
  *(Found by review, 2026-11-20.)*
- **`chartbook snapshot` in a folder that is in no git repository** says that only a pipeline in
  git has snapshots, and not `git init`. A project `chartbook init` makes without `--git` meets
  that. Left as it is.

### A snapshot is of what a run built

*Decided 2026-11-20 by the maintainer: "Yes. We need to do this." Built the same day
(`chartbook/built.py`).* Proposed by
Claude as a note of what a run built from; the maintainer added what it built ("Can chartbook
run always hash the stuff at the end and keep a note of those hashes somewhere? Then when
chartbook snapshot happens it can verify?"), and chose where the note is kept. *The design was
reviewed before anything was built, and what the review changed is marked.*

A run that succeeds leaves a note. `chartbook snapshot` holds what is committed, and what is on
disk, against it. The two halves stop two different slips.

**1. The usual way. Nothing more is typed, and nothing more is said.**

```text
$ chartbook run
…
acme/rates: built.
  For other pipelines and the catalog: commit, then `chartbook snapshot`.
$ git add -A && git commit -m "Yields through October" && chartbook snapshot
acme/rates at 4f2a91c: 2 asset(s) in the store
Snapshot made: 5 files, 23.0 MB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**2. The code was changed after the build.** The fix is committed, and the old file would have
been labelled with it.

```text
$ chartbook run
$ (a fix in load_rates.py) && git commit -am "Fix the day count"
$ chartbook snapshot
Error: acme/rates: these differ from what it was built from: load_rates.py.
  Build again: `chartbook run`, which rebuilds what your build finds out of date. Or, to take what is on disk as it is: `chartbook snapshot --as-is`.
```

**3. A file was changed after the build,** by hand or by a tool run by hand.

```text
$ chartbook run
$ doit pull_rates
$ git commit -am "…" && chartbook snapshot
Error: acme/rates: these differ from what its build left: _data/rates.parquet.
  Build again: `chartbook run`, which rebuilds what your build finds out of date. Or, to take what is on disk as it is: `chartbook snapshot --as-is`.
```

Where both differ, both are said, what it was built from first. A file is named with what
became of it where it did not only change (`notes.md (new)`, `old.py (gone)`), ten of them and
then how many more.

**4. No run of ChartBook's built it here,** or the last one did not end.

```text
$ chartbook snapshot
Error: acme/rates has not been built by `chartbook run` here, so there is nothing to hold its files against.
  Build it: `chartbook run` (a build with nothing left to do takes a moment). Or, to take what is on disk as it is: `chartbook snapshot --as-is`.
```

```text
$ chartbook snapshot
Error: acme/rates: its last build here failed, was stopped, or is still running (it began 2026-11-20 21:14 UTC).
  Build again: `chartbook run`. Or, to take what is on disk as it is: `chartbook snapshot --as-is`.
```

**5. Taking the files as they are is typed, and no longer assumed.**

```text
$ chartbook snapshot --as-is
acme/rates at 4f2a91c: 2 asset(s) in the store
Snapshot made: 5 files, 23.0 MB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**6. A pipeline with no `build` script has nothing to be held against, and is not asked.** It
commits what it declares, so its commit is the whole of it. *(Found by the review of the design:
it was told to `chartbook run`, which says it has no such script, and every snapshot of it would
have been `--as-is`.)* Where it declares a file that is not committed, that is said, with
`--as-is`.

What is settled:

- **The note has two halves.** *What the build ran on:* a plain hash of each source file of the
  pipeline's folder, and of `chartbook.lock`, as they are when the run has pinned and its script
  is about to start. A source file is one git tracks, or would add; what the manifest declares
  as built is not one, and a note, which is prose that no build writes, is one. *What the build
  left:* the size and the time of last change of every file the manifest declares as built,
  when the build has ended and each was found.
- **Size and time for what was built, and not its bytes** *(the maintainer's choice, on Claude's
  recommendation)*. A hash of every output at the end of every run costs seconds for each
  gigabyte, on runs that are never snapshotted; size and time cost nothing and catch what
  happens by accident. Hashes of the outputs can replace them later without changing anything
  that is typed. *From the review:* a time is kept and compared in whole seconds, since a
  network or synced folder may give a finer one at first and a coarser one later. And a built
  file that git tracks has its hash kept too, and a time that differs is settled by it: `git
  stash`, a rebase, a checkout of another branch and back all write such a file again with the
  same bytes.
- **A source file's size and time are kept beside its hash,** and it is hashed again only where
  they differ, as git does for its own index. *(From the review: a large file kept in git was
  hashed at every run and every snapshot.)* With git's own exception: a file whose time of last
  change is not earlier than the moment its hash was taken is hashed again, whatever its size
  and time say. *(From the review's second pass: one digit changed in a parameter, saved in the
  second the run hashed the file, keeps its size and its time.)*
- **Files that no run built are refused too** *(the maintainer's choice)*. The check is strict,
  with a plain message, as every check here is.
- **`chartbook snapshot --as-is` is the way past.** *(The maintainer first agreed to Claude's
  `--as-built`. The session building the store's side said that it can be read as "exactly as
  the run built it", the opposite of what it does, and offered `--as-is`, which cannot. The
  maintainer, to that session, which passed it on: "I like your comment about as is. I think
  that's good logic.")* Its record
  does not say that ChartBook ran the build, as a typed snapshot's never did. The other options
  that were typed (`--project-dir`, `--store`, `--deep`) are in the line that offers it.
- **Where the check passes, the record says that ChartBook ran the build,** as the record of
  `chartbook run --snapshot` does, and the catalog marks it so.
- **The note is kept with ChartBook's own things, and not in the project or in `.git`** *(the
  maintainer's choice: "I kinda like the option of putting in the centralized place where all
  of the other chartbook stuff is")*: `~/.chartbook/cache/built/`, one small file for each
  pipeline folder, named from the folder's path, and moved with the cache by `CHARTBOOK_CACHE`.
  Claude had proposed `.git`, and then a `.chartbook/` folder in the project that ignores
  itself. Of `.git` the maintainer said: "My resistance to .git is about tying ourselves to git
  too much and messing with how git works … I would like to be version control agnostic and
  work towards that". So the note holds plain hashes and no git ids, nothing has to be ignored
  by any version control system, and of the things this check asks, git is asked one: which
  files of the folder are its source.
- **The note says whose it is:** the pipeline's ID and this machine's name
  (`~/.chartbook/machine-id`). One of another pipeline, or left by another machine, is no note
  of this one, and the refusal says which. *(From the review: a path is not enough where one
  home folder serves several machines, where a container puts every project at the same path,
  and where another pipeline is put at an old one.)*
- **A note is in one of two states.** When a build's script is started, the note before it is
  replaced by one that says a build began, and when. When the build has ended and every declared
  file was found, that one is replaced by the finished note, if it is still this run's. So a
  build that fails, is stopped, ends without writing everything it declares, or is overtaken by
  another leaves "a build began", and the refusal says so (scenario 4). A run that stops before its script (a pin, trust, a file that
  is kept and missing) leaves the note as it was. *(From the review: "gone when a build starts"
  was a removal, and the words after a failed build were then "has not been built", which is
  false.)* A snapshot after a run that failed was made of the rest, with what was missing
  listed; it is now refused, or made with `--as-is`.
- **Every build leaves a note, of each pipeline it builds:** the one asked for, and each one
  `--upstream` builds first, each hashed after its own pin and immediately before its own
  script. Not a git dependency, whose snapshot is the pin's. `--frozen` builds, and leaves one
  too: it writes nothing to the project, and this note is in the cache. A script other than
  `build` (`lab`, `test`) builds nothing a snapshot holds, and leaves the note alone, also when
  a build runs it.
- **`chartbook run --snapshot` writes the note and holds its snapshot against it in the one
  command,** and so does each pipeline `--upstream` builds. Nothing changes in what is typed.
- **What is source is asked when the snapshot is made:** a file that was source when the build
  ran and is ignored now is not held against it, and one that is gone is.
- **A folder reached by another spelling is the same folder:** where no note is under the
  folder's name, one whose folder is the same folder is taken.
- **A note whose folder is gone is removed** when another note is written.
- **The list of what is not in a store calls a folder "built already" only where this check
  would pass,** and gives it `chartbook snapshot`; otherwise `chartbook run --snapshot`.
  *(From the review: its `chartbook snapshot` lines would have been refused.)*

What building it settled:

- **Where nothing at all is built, the snapshot says so in its own words,** naming each thing
  that is not built, as it did: that is more use than "has not been built by `chartbook run`".
- **The list gives `chartbook snapshot --as-is` for a pipeline that nothing builds and whose
  files are not committed,** where it is known: no other command can make that snapshot.
- **A cache that cannot be written keeps no note,** and the run says so in a line, and builds.
  A run that makes its own snapshot holds it against the note it has in hand.
- **Tests of other things that typed `chartbook snapshot` over files written by hand type
  `--as-is`:** fifty-four of them, in seventeen files.
- **This repository's own examples, and the upgrade notes, were scripts that snapshot.** *(Found
  by the first full build on the branch.)* `examples/dodo.py` builds each example with that
  example's doit and then typed `chartbook snapshot`: it typed `--as-is`, and said why.
  It could build with `chartbook run` instead, which needs the examples trusted on the machine
  that runs it. The maintainer chose, on 2026-11-20: "Yes, but also show an 'as is' example as
  well." So `yield_curve` and `rate_forecast` are built with `chartbook run` and their snapshots
  take no option, and `fred_charts` is still built by its own doit and taken with `--as-is`
  (`docs_src/examples.md`). doit sees the built files and knows nothing of the note, so a build
  by `chartbook run` is typed again there wherever the folder is not what the last run built,
  as a person types `chartbook run` before a snapshot. *(Found by the review, twice.)* Typed again
  over a built file that was written over by hand, the build finds nothing to do, the run
  notes the file as it now is, and the snapshot is made of it with nothing said: the cost
  written above, that the build's own account is taken. So the examples' doit names such
  files before it types the run, where the last run's note is there to tell them by. Leaving them for the snapshot to stop at was tried and taken
  out: it stopped `doit` after ordinary work with an example's own doit, it did nothing where
  source had changed too, which is the usual state before a snapshot, and after `--as-is` typed
  by hand `doit` stopped at the same step for good. And the notes for upgrading from 0.5 sent
  every
  pipeline that others pin to `chartbook snapshot`; they say `chartbook run` first, or
  `--as-is`.
- **In a repository git does not trust, a run leaves no note, and says so,** since it cannot
  ask which files are source. *(Found on Windows, on a share: the run said nothing, and the
  snapshot typed next said the folder was in no repository.)* `snapshot.code_of` now tells the
  two apart (`snapshot.RepositoryNotTrusted`), so the run's last lines say `No note of this
  build was kept:` and git's own command that makes it trust the repository (the folder as
  git writes it, in double quotes; where its name holds what a shell on Windows reads even in
  those, no command, and a pointer to the one `git status` prints there), in place of the
  command that makes a snapshot, which would be refused there twice: for git's trust, and then
  for the note. *(The second by the review: the line was said, and the command after it.)* The
  snapshot says the same. In a folder that is in no repository the run says nothing of a note:
  there is no snapshot to hold against one. In the list of what is not in a store, the line of
  a folder in such a repository begins with that command, as a command of its own. *(Found on
  Windows by typing the list's lines in their order: the list says "one at a time", git
  refused the first of them, and the command that would have let it run was at the end of the
  line's third, inside a sentence that began with something else.)*
- **What cannot be read does not let a snapshot through.** *(Found by the review of the code: a
  `[scripts]` table that a run refuses made the check step aside, and the snapshot was made of
  files no run had built, with no `--as-is`.)* The check refuses and says what is wrong. It
  steps aside only for what the snapshot itself says better: something that is not committed,
  nothing built at all, no pipeline there.
- **A note is forgotten only by the machine that left it, and only for a folder that is gone
  and not away.** *(Found by the review: a drive unplugged, or a share not connected, lost its
  folders' notes at the next run of anything; and one machine removed another's on a home they
  share.)* Gone is where the folder it was in is there and it is not. *(Left, from the same
  review: a project directly under a mount point that stays behind as an empty folder when
  nothing is mounted is taken for gone. It is built again.)*
- **A run refused as its script is to be started puts the note back.** *(Found by the review:
  on Windows a share with no drive letter is refused there, and "a build began" was left.)*
- **One folder has one note, under whatever spelling it was last built.** *(Found by the review:
  built as `demo` and then as `DEMO`, it had two, and the snapshot was held against the older.)*
- **A file a pipeline declares outside its own folder is not asked of here:** the snapshot says
  of it what is to be said. *(Found by the review.)*
- **A note that does not say whose it is, or in which state, is no note.**
- **The list says `--as-is` only of a folder as it stands,** and not of one that a line is to
  check out to another commit first. *(Found by the review.)*

What it costs:

- **Any change after the build is refused, a word in the README among them.** With a build that
  rebuilds only what is out of date, `chartbook run` again takes a moment and writes a new note.
  With one that builds everything each time, it is the whole build again, or `--as-is`,
  whose record then does not say that ChartBook ran the build, though it did. *(From the
  review.)*
- **The build's own account is taken, and the refusal sends people to it.** "Build again:
  `chartbook run`" rebuilds what the build finds out of date. A build tool that does not know
  the changed file bears on an output leaves that output as it was, and the new note says it is
  of the new source. ChartBook cannot tell that from a build that rightly left it: only the
  build knows what bears on what. `chartbook run --snapshot` has always taken that account.
  Building a commit in a clean copy is what would not, and is in the roadmap (`chartbook run
  --clean`). *(From the review, which would have had the run mark such outputs; a build that
  rightly leaves most of its outputs alone would then be marked at every run.)*
- **A build that rewrites a tracked file it does not declare is refused every time:** a notebook
  run in place, a README written by the build. The message names the files. Declare them, keep
  them out of version control, or type `--as-is`. A project made from the template ignores
  what its build writes.
- **Only the pipeline's own folder is looked at,** as for what is not committed. Code the build
  uses from elsewhere in its repository can change, and so can an ignored file it reads (`.env`,
  a download) and the packages it runs on, and the note does not see them. Nor another
  repository kept inside the folder (a submodule): it is no file, and a new commit of it passes.
- **A time of last change is not the bytes.** A file rewritten to the same size within the same
  second passes. A disk that shifts its times at a clock change (FAT) refuses what did not
  change, and so does a database file that was opened for writing and left as it was.
- **A folder that is moved or renamed, and a cache that is cleared, have no note:** build again.
  A machine whose home folder does not last (a container) types `chartbook run --snapshot`, or
  points `CHARTBOOK_CACHE` at a folder that lasts.
- **One more option,** on a first screen that was cut to six commands a day before.

### Clearing old snapshots: the record

*Decided 2026-11-19: a run clears the old snapshots of its own pipeline,* since a run then made
one every time. *Decided 2026-11-20: a run makes a snapshot only where it is asked for one, so none pile up
behind it to clear. Step 3 is dropped, and the branch that built it is not to be merged.* What was built, and what its review
found, is kept here because it is part of why.

It did, after every snapshot, what `chartbook store gc` would do for that one pipeline, by the
same rules and no others: a snapshot went that no lockfile the store knows of pins, that is not
the newest, that no tag, branch or label names, that holds no version of an asset marked `keep =
true`, and that was made more than 7 days ago. It asked nothing and said what it did in one line,
and the reminder of `chartbook store gc` and `--no-gc-reminder` were removed with it.

```{admonition} Built, and never merged
:class: warning

A review of it reproduced four ways in which gc's rules, applied at every run with no list and
no question, remove something that is still needed.

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

`chartbook store gc` has the same rules, and lists and asks first.

*Decided 2026-11-19, of three ways on from there: none.* The maintainer chose a rule by rows: a
run clears an older snapshot when the new one holds all of its data. It is in
{doc}`snapshots-and-increments` ("Clearing"), where three forms of it were broken by review
before anything was built. *Decided later the same day:* no run removes a snapshot in 0.6.0, and
`chartbook store gc` is given better evidence: the store's notes of what each project pins, on
every branch and tag.
```

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
- **`chartbook.toml` is left changed and not committed,** for whoever said yes to look at and
  commit.
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
  last lines say how to come back: `cd /work/report && chartbook run`. *(Changed 2026-11-20,
  below: no command enters a folder now, so there is nowhere to come back from, and the last
  line is the command that was typed, with the pipeline's folder.)*
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
  worktree of that commit, and the reader's checkout stays on its branch. A worktree of that
  name is used only where git says it is one, on that commit. *(Found by the third pass: a
  leftover folder of the name was taken for it.)*
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
- **A checkout is made at the repository's top, before the folder is built in.** *(Found by
  the second pass of the review: a folder that an earlier line's commit does not have made `cd
  FOLDER && git checkout` fail at the `cd`, every time.)* A line with no pin, in a repository
  that a line above has left on another commit, checks out the commit it was read at. A commit in
  a command is twelve digits, which a large repository has no two of.
- **One pipeline, read with a pin and without one, is one line where the commit is the same.** *(Found by a
  mutant no test caught: a reader with no pin, listed first, got a line of its own, and the pinned
  reader a second one for the same commit, so the same pipeline was built twice.)* The line takes
  the pin. At another commit they are two builds, and each reader names its own.
- **A repository that was read and does not hold the pipeline is not built in.** *(Found by the
  second pass: the only manifest of a repository was taken for whatever pipeline was asked of
  it, so an entry that named another pipeline's repository was told to build that one, for
  ever.)* Asked of the pipeline itself, it is left to the pin's own words; further up, its line
  says it was not found and gives no command. *(Found by the third pass: a manifest that could
  not be read, and one past the two hundredth of its repository, were said not to be there.
  The first is its folder's all the same; the second line says how far the search went.)*
- **A clone that lacks its commit is fetched, and built in the folder the clone has the pipeline
  in now.** *(Found by the third pass: after the fetch the list said to build at the top of the
  clone.)* The line says that the folder is a guess.
- **A line is one command, the same in every shell.** *(Found on Windows, 2026-11-20, the first
  time the suite ran there: the lines had been written for `cmd.exe` by reading, `cd /d FOLDER &&
  git checkout COMMIT && chartbook run --snapshot`. Windows PowerShell, which a new Windows
  machine and VS Code open, reads neither `&&` nor `cd /d`, so no line could be pasted there.)*
  No command enters a folder and none is joined to another. A command names the folder it works
  in: `git -C TOP checkout COMMIT`, then `chartbook run --snapshot --project-dir FOLDER`. The
  same lines are printed on every system, so the tests that type a list's lines in a POSIX shell
  type what a Windows user is given, but for the quotes. Whoever types them stays in their
  folder. "Then here again:" is the command that was typed, with the pipeline's folder. *(Found
  by review: it was first given bare where the pipeline was in the folder it was typed in. Typed
  in a clone that had been stepped into, that built the clone's pipeline.)* On Windows a word is
  quoted as `cmd.exe`, PowerShell and Git
  Bash all read it: double quotes, around every word that holds a backslash, and a `%` as it is
  (a doubled one is one only in a batch file). *(Found the same day by typing a list's lines on
  Windows 11: every line ran in Windows PowerShell 5.1 and in `cmd.exe`, quoted words among
  them, and the last built. In Git Bash a path printed bare, `C:\work\rates`, reached the
  command as `C:workrates`.)*
  The same function now quotes every command a message prints with a folder or a word of the
  user's in it (`chartbook restore --project-dir …`, `chartbook pin --update …`, the line that
  says where to `chartbook pin`, `chartbook catalog migrate`, `chartbook link ID FOLDER`,
  `chartbook path REF --files`, the two lines that name `migrate_toml_v2.py`, and git's
  `safe.directory`): `shlex`, which some of them used, writes for a POSIX shell alone, and
  `cmd.exe` read its single quotes as part of the folder's name. *(Found by the second and
  third passes of the review: the others wrote the folder their own way, or bare. One of them,
  `chartbook link`, names the folder of a manifest's `path`.)* Two tests read the source, for
  another use of `shlex` and for a folder in one of those commands that the function did not
  write. The `cruft link` line of `chartbook init` is left: its answers are JSON, which no one
  spelling gives to `cmd.exe` and PowerShell alike.
  What it costs *(the first of these as its review found it, 2026-11-20, by typing whole lists
  into a shell; the page had said less)*:
  - *A line no longer stops at its first failure.* `git checkout … && chartbook run --snapshot`
    did not build after a checkout that failed. Lines pasted together do: each runs whatever the
    one before it did, and the build is of the commit its folder is on, with a snapshot of that
    commit. A checkout fails for work that is not committed anywhere in the repository (the
    build looks only at the pipeline's own folder, and goes on), for a `chartbook.lock` that
    differs (the build passes over the lockfile), and for a commit the clone lacks. What is read
    through a pin is safe: a pin is met only by the same file or the same rows, so such a
    snapshot either holds what was pinned or is not read, and the list comes back. A pipeline
    that was never pinned takes whatever was built, of whatever commit, and its pin's line says
    which. The list itself says "one at a time", and the reference and the guide say why. A
    build line that carried the commit it is to be of, and refused elsewhere, would close it;
    that is an option on two commands. *Decided 2026-11-20: not now. It is in the roadmap, with
    what would bring it forward: a class told to paste a list whole, or a build of the wrong
    commit met by someone.*
  - *A run at a pinned commit leaves a `chartbook.lock` that blocks the next checkout in the same
    clone,* where that commit has none and the next one has. Older than this change: the old
    line stopped there, and the list asked for again then said to build where the clone stood.
    Seen in a repository of two pipelines wanted at two commits.
  - *One more line for each pipeline that is pinned.*
  - *Each command runs in the environment it is typed in.* After `cd FOLDER`, tools that choose
    an environment by the folder (`uv run`, pyenv's shims) chose the upstream's. The reference
    says to enter the folder where a pipeline has an environment of its own.
  - *On Windows no spelling keeps every sign as text in `cmd.exe`, PowerShell and Git Bash
    alike.* *(Found by review: an address in a lockfile may hold `$env:TOKEN` or `%TOKEN%`, and
    the `git clone` line would have sent the token where the address says; a folder of a cloned
    repository may be named `$(…)`, which PowerShell and Git Bash run. Pasting a line would
    have run somebody's code before anything asked whether their folder is trusted.)* What each
    reads inside double quotes: PowerShell and Git Bash a `$` and a backtick; Git Bash a `!`, and
    a `\"`, which it takes for a quote that is text; PowerShell a word processor's `“`, `”` or
    `„`, which ends the word as the plain quote does; `cmd.exe` a `%NAME%`. *(The last three by
    the second pass, which made a file from a folder's name in bash; and it found the word was
    read as it was given, where what is pasted is what is printed, without the signs that print
    as nothing.)* And `cmd.exe` once more, behind PowerShell, which hands a word with no space
    in it to a command without its quotes: where the command is a batch file, as a shim of
    pyenv's is, `cmd.exe` reads the word's `&`, `|`, `<`, `>` and `^`. *(Found by the third
    pass, by reading. A word with a space keeps its quotes, so `R&D team` is given and `R&D` is
    not: the cost of it is a Windows folder with a `&` and no space, which gets no command.)*
    A line whose commands would hold one is given no command there, and says so, with what to
    make by hand and no word of how: a `git checkout` by hand may be of the reader's own
    repository. No clone or worktree such a line would have made is counted on by the lines
    after it; a repository it would have moved is still taken for moved, since by hand it may
    well be *(the third pass: a folder beside it, "built already", was given `chartbook
    snapshot` for files of the commit it had been on)*. The last line is read the same way.
    A `$` at the end of a longer name, before a slash or the end of the word, is text to both
    shells (`\\server\home$\…`, the one common `$` in a Windows path); a folder named `$`
    alone is not, since Git Bash takes the backslash before it and the `$` for one sign. A `%`
    is text only where it begins the two digits a
    web address writes a sign with (`%20`), and where no name between two of them is a variable
    of this machine or one `cmd.exe` fills in by itself (`%CD%`). What that leaves: a variable
    whose name begins, and is followed, as such digits (`%DB_PASSWORD%2F`), set in the window
    the line is pasted into and not in the one that printed it. *(Typed on Windows later,
    2026-11-20: a single `%` reaches a program as it is in all three shells; a batch file that
    hands its words on through `call`, as pyenv's shims do, drops it with nothing said
    (`C:\work\100%\mid` arrived as `C:\work\100\mid`), and doubled it is right there and
    wrong everywhere else. So it stays withheld for `chartbook`, which may be such a file, and
    is text for a word handed to `git`, which is a program: git's own word for a network
    share, in the `safe.directory` command, begins with one.)*
    The function that quotes never writes such a word, whatever message asks it to:
    `ITS-NAME-HOLDS-A-SIGN-A-SHELL-READS` stands in its place, which runs nothing. So a run's
    closing line, `chartbook restore` and the rest hold no such word either, and say less well
    why. A network folder (`\\server\…`) was read otherwise by Git Bash, and the reference said
    so. *(Typed on Windows later, 2026-11-20, with the list's own lines for a folder on a
    share: none of its three commands ran in Git Bash, which reads the two backslashes as one
    in double quotes too. With forward slashes, `"//server/share/…"`, git and ChartBook take
    the same folder in all three shells, so a network folder is written so, but for
    `net use`, which wants its own.)*
  - *A clone found beside the pipeline is named as the disk names it.* It is looked for under
    the name its address gives (`rates`), and a disk that takes either letter case finds
    `Rates`. *(Found by review: under the address's name the list had pathlib's words in it, a
    checkout of the commit the clone was on, and nothing of what the pipeline reads in turn.
    Older than this change, and its command would now have been refused.)*
  - *Left, older, and found by the same review:* a pipeline that is built already and another
    wanted at an older commit, in one repository read by `path`, give a list whose every line
    runs and whose last fails, since the repository is left on the older commit; and a pinned
    `path` folder that is in no git repository is given a `git checkout` on the line that says
    so. No test types either.
  - *Not typed by any test on Windows.* The tests that type a list's lines need a POSIX shell.
    PowerShell 5.1, `cmd.exe` and Git Bash were typed into by hand, once, on Windows 11.
- **The list's first words say "with the commands below, one at a time".** *(Found by review,
  2026-11-20: "Build it first. It ends with a snapshot" was true while a build ended with one.
  "One at a time" was added the same day, when the lines stopped being joined: the list says
  how to type it, where only the reference did.)*
- **`chartbook add` undoes nothing for a cycle found here.** *(Found by review: taking the new
  entry out was wrong where the cycle was another entry's.)* The error is said, and the manifest
  is as the command left it.

## The catalog knows when it is behind

*Decided 2026-11-19: `chartbook catalog open` asks before it opens a site that is behind.*
*Proposed by Claude:* it is worked out when asked, by comparing the versions the site was built
from with the versions in the stores now. A mark left by the command that makes a snapshot would
miss one that arrived by a synced folder from another machine. A site that was never built is behind by
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

*Built 2026-11-19* (`chartbook/agents.py`, and the section's text in `chartbook/agents_section.md`),
with what building it settled:

- **The project is the nearest folder with a `chartbook.toml`,** from the working directory up to
  the top of its git repository, and never the home folder; in no repository, the folder itself
  or nothing. That is where `AGENTS.md` is written. *(Found by review: with no repository the
  walk went up to the top of the disk.)*
- **Nothing a person wrote is replaced unasked.** *(Found by review: only a section naming
  exactly this version was protected; a newer one, an older one written in, and markers typed by
  hand were all replaced without a word.)* The opening marker names the version, as the skill's
  `SKILL.md` does, and carries a hash of the section: its two marker lines and the text between
  them. A section that is as some ChartBook left it is replaced when it is an older one, and
  left when it is a newer one, as the skill is. Any other is replaced at a yes or with
  `--force`, and where nothing can ask the command stops and says that notes go outside the two
  lines. *(Found by the second pass: the hash was of the text alone, so words written into a
  marker's own comment went unasked; the question did not say which lines would go; and a
  section somebody had written in was called stale at every command, for ever.)*
- **A marker is a whole line, from its first column, outside a code fence.** *(Found by review:
  a line that mentioned a marker was taken for one, and the project's text between two of them
  was replaced.)* A marker line with other text on it, and marker lines that do not hold one
  section, are an error that says which lines, and nothing is written.
- **A fence is as Markdown takes one,** and a file that ends inside one is refused. *(Found by
  the second pass: any line that began with three backticks opened or closed a fence. Inline
  code at the start of a line, or a fence never closed, hid the section below it, and the
  command added another section at every run.)*
- **The rest of the file is kept byte for byte, and the file is written whole or not at all.**
  *(Found by review: blank lines were cut, one CRLF turned the section to CRLF, a byte-order mark
  hid the section, and a write that failed part-way left the project's notes cut short.)* The
  file is replaced by a move, which asks nothing of the file it replaces, so three things are
  looked at first. *(Found by the second pass: a read-only file was written; a hard link was
  broken with no word; and what somebody else saved while the question waited was lost.)* Each
  is refused, and the command says which.
- **A link is written through only to a file of the project that is there.**
- **Both halves are done** where the skill's question was answered no, could not be answered, or
  its folder could not be written. *(Found by review: only the first of those.)* Ctrl-C at the
  skill's question ends the command, and a newer ChartBook's skill is left as it is and is no
  error. *(Found by the second pass: Ctrl-C was taken for a question nobody could answer, and
  from the older of two environments the command failed every time.)*
- **The section sends an agent to nothing that writes over a person's files.** *(Found by
  review: it named `chartbook docs build`, which asks before it replaces `docs/`, and told the
  agent to do what a message says.)* It names what only reads, and says to show a stopped
  command's message to the person, and not to answer, force or trust on its own.
- **A section from an older ChartBook is said** as a stale skill is: in one line to a person at a
  terminal, and by `chartbook run --check`.
- **The section is short.** It says what an agent gets wrong without it (build with `chartbook
  run`, never edit the lockfile, declare before writing, read other pipelines through
  `chartbook.data`) and where the whole reference is. It is held to the same test as the skill:
  every command it names is one.

## The first screen

`chartbook --help` lists the commands above first, under their own heading, and the rest under
"More". The Quickstart, the README and the skill teach them first. The reference still names
every command and option, as the tests of it require, and each step below changes it for what
that step changes. *Proposed by Claude, 2026-11-19.*

*To change with step 11, proposed by Claude, 2026-11-20:* six lines where there were five, with
`chartbook snapshot` after `chartbook run`:

```text
Start with these:
  chartbook init            Start a project from the template
  chartbook run             Build this pipeline, pinning what it reads
  chartbook snapshot        Make this build what other pipelines read
  chartbook pin --update    Take newer snapshots of what this one reads
  chartbook catalog open    Browse every snapshot in your stores
  chartbook install agents  Teach your coding agent ChartBook
```

- **Each line is at most 72 columns,** as the five were held to, so that none wraps in a terminal
  of eighty. *(Found by review, 2026-11-20: the first draft's line for `snapshot` was 77.)*
- **`run` pins what the pipeline reads, not the pipeline,** and the line for `pin --update` names
  "this one", now that the line above it is no longer `run`'s. *(Found by review, 2026-11-20.)*
- **The section that holds the table in each file is headed "Start with these",** the help's own
  words. They name no number, and do not sit beside the skill's "Key CLI Commands" as a second
  heading that says nearly the same. *(Found by review, 2026-11-20: "The commands to know" did.)*

What is written below is of the five, as they were built.

*Built 2026-11-19*, as far as it can be before the store's new layout lands
({doc}`snapshots-and-increments`):

- **`chartbook --help`** opens with "Start with these": the five, each as it is typed, with one
  line of what it is for. "More" lists the rest by name. `init` and `run` are all there in the
  first list and are not said twice; `pin`, `catalog` and `install` have more to them and are.
- **The README, the docs' front page, the Quickstart, the reference, the skill and the llms
  files** each have a section "The five commands" with one table, and a test holds its words in
  every one of them, and the help's five lines, to what is written in the test. *(Found by
  review: the first test held the names and nothing of what each line said.)*
- **Each line says what is so.** *(Found by review.)* `chartbook catalog open` shows snapshots,
  not "everything that was built": work that is not committed is not in it. `chartbook run`
  looks for what the manifest declares, which is less than checking it. `init` and `install
  agents` are typed once, not on most days, and `init` makes a new folder. And `chartbook run`
  needs a `build` script: the README and the Quickstart give the two lines that name one.
- **Not done here: the Quickstart's walk-through itself,** which goes step by step (a script run
  by hand, `chartbook docs build`, `chartbook snapshot`) and has a recorded terminal beside it.
  Rewriting it around `chartbook run` means recording that again, and its closing lines are the
  ones the store's new layout changes. It says, after its steps, which of them `chartbook run`
  does in one (the build and the snapshot, not the site). *(With step 11: the build alone. The
  snapshot is a step of its own again, as the walk-through has it.)*

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
  is not renamed `publish`, which reads as "to the web".* It is also where the question of a side
  branch goes: a snapshot made on one is the newest of its pipeline in whatever store it is
  written to, and a shared store would then hold only what was sent to it. *(2026-11-20.)*
- **`chartbook run --clean`:** build this commit in a clean copy, as someone who depends on it
  would. *Decided 2026-11-18: not the default.* A run in a copy means two copies of the data, and
  most runs are of code that is not committed yet.

## The order of work

One pull request each. Each changes the reference, the skill and the assistant files for what it
changes.

1. This page. *Merged 2026-11-19.*
2. `chartbook run` looks for what was declared, and makes a snapshot when everything is committed.
   *Built 2026-11-19. The snapshot is taken out again by step 11.*
3. A snapshot clears its pipeline's old snapshots; the reminder goes. *Built 2026-11-19, never
   merged, and dropped 2026-11-20: see "Clearing old snapshots: the record".*
4. `chartbook run --check`; `chartbook check` is gone. *Built 2026-11-19.*
5. `chartbook pin --update`; `chartbook update` and `pin --frozen` are gone. *Built 2026-11-19.*
6. `chartbook run` asks to add a pipeline that code reads and the manifest does not declare.
   *Built 2026-11-19.*
7. What is not in your store: the list, in order. *Built 2026-11-19.*
8. `chartbook catalog open` asks before opening a site that is behind. *Built 2026-11-19.*
9. `chartbook install agents`. *Built 2026-11-19.*
10. The first screen: `--help`, the Quickstart, the README, the skill. *Built 2026-11-19, but for
    the Quickstart's walk-through (see "The first screen").*
11. `chartbook run` builds and `chartbook snapshot` records: a run ends by saying what makes a
    snapshot, and makes none; the first screen has six commands. *Built 2026-11-20.* Which
    kind of snapshot `chartbook snapshot` makes, and `--complete`, are in the order of work of
    {doc}`snapshots-and-increments`.
12. A snapshot is of what a run built: a run leaves a note, and `chartbook snapshot` holds what
    is committed and what is on disk against it; `--as-is`. *Decided 2026-11-20; this page
    first. Built 2026-11-20.*
