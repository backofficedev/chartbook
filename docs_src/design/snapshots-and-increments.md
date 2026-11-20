# Design: snapshots and increments

```{note}
A design document, written 2026-11-19 from a day of planning with the maintainer. He looked at
his own store in a file browser and could not say what its folders were for, nor where the files
of a nearly empty snapshot were. It says how the store is laid out so that a person can read it,
when a run makes a complete snapshot and when a smaller one, and when a run may clear an old
snapshot without anybody losing data. It is for 0.6.0, with {doc}`one-command`.

Status: **to be built, step by step, in "The order of work" at the end.** Each part says whether
the maintainer decided it, and when. A choice he left open is marked *Proposed by Claude*, with
its date, until he says otherwise. Nothing here adds a command, an option or a field of
`chartbook.toml`.
```

## What was wrong

Since 0.3.0 the store keeps each file once in its pipeline's folder, in the first snapshot that
had it ({doc}`plan-0.3.0`). A later snapshot's folder holds only what is new, and its record says
where each of its other files is. On 2026-11-19 the maintainer's own store, in a folder a sync
service keeps, held 42 snapshots of 35 pipelines in 23.4 GB, and looked like this:

- **A snapshot's folder with two small files in it.** Its six real files were in three other
  folders, and nothing but a JSON record said which.
- **Those three folders were not snapshots any more.** `chartbook store gc` had cleared them, and
  they stayed, with a `CLEARED.txt`, because later snapshots kept files in them. There were 23
  such folders beside the 42 snapshots.
- **No folder could be copied by itself,** except a pipeline's first snapshot, and nothing said
  which that was.
- **Six entries at the top,** one of them for a person (`pipelines/`), and one left over from a
  layout two versions old.
- **Keeping each file once saved 20 MB of the 23.4 GB.** What it had saved was copying: 9.3 GB of
  the files of today's snapshots sat in an earlier folder, 9.0 GB of that in one pipeline.

So the saving is real for a large pipeline that changes a little, and worth nothing to most, and
its price was a store nobody could read.

## The idea in one example

```text
~/.chartbook/store/
  snapshots/
    acme+rates/
      2026-11-16T091500Z_4f2a91c0e1b2/      a snapshot: every file of it is here
        _data/treasury.parquet
        _output/curve.html
        README.md
        chartbook.toml
        _chartbook/snapshot.json
        _chartbook/index.json
  increments/
    acme+rates/
      2026-11-19T140200Z_9b1e22d7a0c4/      a snapshot kept as an increment:
        _output/curve.html                   only the files that differ from the one above
        _chartbook/snapshot.json
        _chartbook/index.json
        _chartbook/INCREMENT.txt             one line: the snapshot the rest is in
  _chartbook/                                ChartBook's own notes; nothing here is for a person
  store.json
  README.txt
```

- **Everything under `snapshots/` is complete.** A folder there holds every file of its snapshot.
  It can be read, copied, zipped and sent as it is.
- **Everything under `increments/` is a snapshot too,** kept in less room: its folder holds only
  the files that differ from **one** complete snapshot, and says which. To anything that reads or
  pins, it is a snapshot like any other.
- **`chartbook run` decides which to make,** and its last line says which it made.

## What everyone learns

Nothing new. The list is the one in {doc}`one-command`, and no line of it changes. A person who
never opens the store never meets the word "increment" outside the last line of a run.

## What you see

The output is as it is to be built; where a line exists today it is today's.

**1. The first run of a pipeline makes a complete snapshot.**

```text
$ chartbook run
acme/rates: build
acme/rates at 4f2a91c: 3 asset(s) in the store
Snapshot made: 6 files, 23 MB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**2. A later run, where little changed, makes an increment.** The chart was drawn again and the
table is the same file.

```text
$ chartbook run
acme/rates: build
acme/rates at 9b1e22d: 3 asset(s) in the store
Snapshot made, kept as an increment: 2 of 6 files, 0.4 MB. The rest is in the snapshot made 2026-11-16 09:15 UTC.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**3. The increments have added up, so the next one is complete.**

```text
$ chartbook run
acme/rates: build
acme/rates at c07d3e1: 3 asset(s) in the store
Snapshot made: 6 files, 23 MB. The increments since the last complete one had added up to its size.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**4. Whoever depends on the pipeline sees no difference.** A pin names a snapshot, and one kept
as an increment is pinned and read as any other.

```text
$ chartbook pin --update
acme/rates: 1 moved
  acme/rates:treasury
    sha256:b47d6f2bd9db… -> sha256:48b68a0be6a0…
    24 new rows, through 2026-11-18; earlier rows unchanged
Wrote chartbook.lock.
```

**5. You want a complete one now,** to look at, or to hand to somebody. `chartbook snapshot`
always makes a complete one. Where the newest is an increment of these same files, it completes
that one, and says where it is.

```text
$ chartbook snapshot
acme/rates at 9b1e22d: 3 asset(s) in the store
The snapshot made 2026-11-19 14:02 UTC is now complete: 6 files, 23 MB.
  ~/.chartbook/store/snapshots/acme+rates/2026-11-19T140200Z_9b1e22d7a0c4
```

**6. An older snapshot is cleared, because the new one holds all of its data.** Yesterday's pull
and today's differ by one day of rows.

```text
$ chartbook run
…
Snapshot made: 6 files, 23 MB.
acme/rates: the snapshot made 2026-11-18 09:02 UTC is cleared. This one holds all of its rows.
```

**7. An older snapshot is kept, because it holds something the new one does not.** The source
revised a value of October.

```text
$ chartbook run
…
Snapshot made: 6 files, 23 MB.
acme/rates: the snapshot made 2026-11-18 09:02 UTC is kept. It has rows this one changed (treasury, in 2026-10).
```

**8. A pipeline whose lockfile names a cleared snapshot still reads its rows.** On a branch
nobody had touched for a month:

```text
$ chartbook run
acme/rates: the snapshot the lockfile names (4f2a91c, made 2026-11-18 09:02 UTC) was cleared.
  Its rows are read from the one made 2026-11-19 14:02 UTC, without the rows after 2026-11-17.
acme/report: build
…
```

**9. Looking at the store.**

```text
$ chartbook store ls acme/rates
acme/rates
  2026-11-16 09:15 UTC  4f2a91c  complete                              6 files   23 MB
  2026-11-19 14:02 UTC  9b1e22d  increment on 2026-11-16 09:15 UTC     2 files  0.4 MB
```

**10. A store made by an earlier ChartBook is moved once.**

```text
$ chartbook run
The store at ~/.chartbook/store has the layout of ChartBook 0.5.
Move it to this version's with `chartbook store migrate`. An earlier ChartBook will not read it afterwards.

$ chartbook store migrate
~/.chartbook/store: 3 pipelines, 5 snapshots
  3 become complete snapshots and 2 become increments on them
  2 folders that only held files for later snapshots go, once their files are moved
  nothing is copied: every file is moved
Proceed? [y/N]: y
Moved. The store has the layout of ChartBook 0.6.
```

## The layout

*Decided 2026-11-19: two folders for a person, `snapshots/` holding only complete snapshots and
`increments/` holding the others; the rest of what was at the top goes under one folder of
ChartBook's own.*

| At the top | What it is | Was |
|---|---|---|
| `snapshots/<pipeline>/<snapshot>/` | A complete snapshot: the pipeline's files in their own places, and `_chartbook/` with its record and its index | `pipelines/<pipeline>/<snapshot>/` |
| `increments/<pipeline>/<snapshot>/` | A snapshot kept as an increment | the same folder |
| `_chartbook/roots/`, `_chartbook/origins/`, `_chartbook/tmp/` | The notes of the lockfiles that pin what is here, of the folders snapshots were made from, and what is being written | `roots/`, `origins/`, `tmp/` |
| `_chartbook/unowned/` | An object no pipeline owns | `pipelines/+unowned/` |
| `_chartbook/cleared/` | The records of snapshots a run cleared ("Clearing") | new |
| `store.json` | Which layout this is: `chartbook/store/v3` | the same file, `v2` |
| `README.txt` | What the folder is, in a few lines, for whoever opens it | new |

- **A pipeline's folder and a snapshot's folder are named as today:** `acme+rates`, and
  `2026-11-16T091500Z_4f2a91c0e1b2` for when it was made and its commit.
- **`store.json` stays at the top.** *Proposed by Claude, 2026-11-19; the maintainer had agreed to
  everything of ChartBook's own going under `_chartbook/`.* It is the one file an earlier
  ChartBook looks for. Left where it is and saying `v3`, ChartBook 0.5 says `The store at … has
  the layout 'chartbook/store/v3', and this version of ChartBook reads 'chartbook/store/v2'. Use
  a newer ChartBook …` and writes nothing. Moved, there would be no marker where 0.5 looks, and
  it would write one of its own and a `pipelines/` beside the snapshots.
- **What is being written stays inside the store,** in `_chartbook/tmp/`: a file is written there
  and then renamed into place, which needs the two on one disk.
- **`snapshots/0000…/`, the mark the move from the layout of 0.2 left, goes.** *Proposed by
  Claude, 2026-11-19.* It was there for ChartBook 0.2 to trip over, the name it sat under is now
  the snapshots' own, and a store of 0.2 is moved by 0.5 first.
- **Each pipeline's folder has a `README.txt`,** as today, in new words: under `snapshots/`, that
  each folder is complete and may be copied as it is, and that one is removed with `chartbook
  store gc` and not by hand while an increment builds on it; under `increments/`, what an
  increment is and where the rest of its files are.

## An increment

*Decided 2026-11-19: an increment builds on exactly one complete snapshot, and never on another
increment.*

- **Its folder holds the files that the snapshot it builds on does not have.** A file is compared
  by its bytes and its size, whatever its name, as the store compares files today: a part of a
  table that pandas wrote again under another name, with the same rows in the same bytes, is not
  kept again.
- **It builds on the newest complete snapshot of its pipeline in that store** that the pipeline's
  owner made. *Proposed by Claude, 2026-11-19.* A snapshot that `chartbook pin` makes from a
  repository is always complete: it builds on nothing, and nothing builds on it.
- **If the snapshot it builds on is gone before its record is written,** it is written complete:
  the files are in the pipeline's folder, where they are being copied from.
- **Its record lists every file of its version,** as any snapshot's does, each with the folder
  that keeps it. That is one of two: its own, or the one it builds on. The record names that one
  (`builds_on`), and so does the one line of `_chartbook/INCREMENT.txt`, for a person:

  ```text
  The rest of this snapshot's files are in snapshots/acme+rates/2026-11-16T091500Z_4f2a91c0e1b2
  ```

  *Proposed by Claude, 2026-11-19: the file is under `_chartbook/`, the one name in a snapshot's
  folder that is ChartBook's own, so no file of a pipeline's can have its name.*

What the rule gives:

| | Since 0.3.0 | With this |
|---|---|---|
| The folders a snapshot's files are in | Any number of earlier ones | One, or two |
| Removing a snapshot nothing needs | May leave its folder behind, for the files later ones keep in it | An increment goes whole; a complete one stays whole while an increment builds on it |
| A folder that holds files and is no snapshot | Yes, with `CLEARED.txt` | Cannot be |
| What a person can copy | A pipeline's first snapshot, if they know which | Anything under `snapshots/` |

It is not a diff, as a shared snapshot was not ({doc}`plan-data-reads`): nothing is applied to
anything, and a read opens files where they are.

**An increment can be completed at any time.** A folder of the same name is written under
`snapshots/` with every file of it, its record last: from the pipeline's folder where that still
has the same files, and from the two folders in the store otherwise. Then the increment's folder
is removed. Nothing that names the snapshot changes: a pin names a pipeline, a
commit and a time, never a folder. `chartbook snapshot` does this (scenario 5). *Proposed by
Claude, 2026-11-19.*

## Which one a run makes

*Decided 2026-11-19: `chartbook run` decides by itself, and nobody has to learn a command for
it.*

**A run makes an increment until the increments since the last complete snapshot, with this one,
add up to the size of a complete one. Then it makes a complete one.**

- **The first snapshot of a pipeline in a store is complete:** there is nothing to build on.
- **One where every file differs is complete:** the increment would be the whole of it.
- **Sizes are bytes of files.** A snapshot's size is that of every file its record lists; an
  increment's is that of the files in its own folder.
- **The count is kept in the records,** each increment's saying the total up to and with itself.
  *Proposed by Claude, 2026-11-19.* It is a count of what was copied, so clearing an increment
  does not take from it.
- **Each store decides for itself,** where a snapshot goes to several.
- **The same files make no new snapshot,** as today.

*Decided 2026-11-19, over "when more than half has changed", which was the first proposal.* For a
pipeline of size 100, the average copied at each run:

| What changes at each run | More than half | Adds up | The best there is |
|---|---|---|---|
| Everything | 100 | 100 | 100 |
| The same 30 | 30 | 48 | 30 |
| A different 10 | 42 | 40 | 40 |
| A different 1 | 27 | 14 | 14 |

In the third row the increments are 10, 20 and 30, since each holds everything that differs from
the complete snapshot; the fourth would be 40, which brings the total to 100, so it is a complete
one: 160 over four runs. No rule is best in every row, because the best moment depends on what
later runs change. This one is the rule of renting until the rent paid equals the price: it never
copies more than a complete snapshot at every run would, always less than twice what increments
alone would, and where the changes spread it lands on the best. It also makes a complete snapshot
every so often with nobody asking, which "more than half" never does in the second row. That row
is its price.

**Typed, the word means a complete one.** *Decided 2026-11-19.* `chartbook snapshot` and
`chartbook run --snapshot` always end with a complete snapshot, and nothing is renamed. `run
--snapshot` stays the strict form it is in {doc}`one-command`. So a script that uses it copies
every file each time.

## Words

*Decided 2026-11-19.*

- **Snapshot** stays the one word for what a run makes, what a pin names and what a catalog
  shows. The maintainer teaches it, and it does not change.
- **Complete** and **increment** say how the store keeps a snapshot. They are met in the store's
  folders, in `chartbook store ls` and in the last line of a run, and nowhere else.
- **Standalone** and **shared**, the words of 0.5.0, go: they named the same two things less
  plainly, and a shared snapshot's files could be anywhere.
- No new word for "a snapshot of either kind" (*version* was proposed and taken back: it would
  have changed what is taught, and it is a model's word already).
- **A dated dataframe** is one whose entry names a `date_col`. {doc}`pins-and-rebuilds` says
  "dated" of rows and tables already.

## Pins and reads

*Decided 2026-11-19: a pin can name an increment, and nothing is done to it when it is pinned.*

If it could not, the pipelines that depend on this one would get nothing new until the next
complete snapshot, and an increment would be for nobody.

- **The lockfile does not change.** It names a snapshot by its pipeline, its commit and when it
  was made, as today, and nothing in it says which kind the snapshot is.
- **"The newest" of a pipeline is the one made last,** of either kind, as today.
- **A read asks the store for an asset by its hash and is handed its files,** each where it is
  kept, as today. For an increment those are in two folders.
- **Not completed when pinned.** That was considered: an increment nobody has pinned could then be
  cleared with no care at all. But whoever pins would pay for it. On the one pipeline of "What was
  wrong" with 9 GB in earlier folders, a `chartbook pin --update` would copy those 9 GB from the
  reader's machine; a reader who cannot write to
  the store could not pin the newest at all; and a pipeline whose reader takes every snapshot
  would have none but complete ones.

## Dated dataframes, and tables in parts

The store compares files and knows nothing of rows. That is enough, and it is on purpose.

- **A table in one file changes whole when a day is added,** so every snapshot of it holds the
  whole table again.
- **A table in a folder partitioned by date changes only in its newest part,** so an increment
  holds the new dates and nothing else. A 1 GB table of 60 years is 1 GB at each run as one file,
  and about 17 MB as a folder by year.
- **Nothing is declared for it.** The entry names the folder and the `date_col`. The reader finds
  `year=2026/month=11/` by itself; the lockfile dates each row by the `date_col` and records no
  file name and no layout ({doc}`pins-and-rebuilds`, "Folders of files"). Columns made only to
  partition by are columns like any other. The real date column has to stay in the data: numbers
  date nothing.
- **ChartBook never cuts a pipeline's file into rows it keeps apart.** *Decided 2026-11-19.* A
  snapshot's folder holds the files the pipeline wrote, and can be read without ChartBook.
- **A snapshot never has days added to it.** *Decided 2026-11-19.* It does not change once it is
  made: that is what a pin trusts, and what makes a store in a synced folder safe.

Advice for the guide, not a rule: partition a large table that grows by date, by year where it
has a row a day, and by day only where a day is large. A small table gains nothing, and a folder
for each day of sixty years is fifteen thousand small files.

## Clearing

*Decided 2026-11-19, in place of step 3 of {doc}`one-command`, which was built, reproduced as
losing data, and held back.* That step applied `chartbook store gc`'s rules at every run. They
decide from what the store can see of who pins what, and the review showed what it cannot see: a
pin on another branch of a pipeline that depends on this one, and a pin of anybody who may not
write to the store. This rule needs to see no pin.

**After a run makes a snapshot, it clears an older snapshot of the same pipeline when the new one
holds all of its data. A snapshot is cleared whole, or kept whole.** Increments are looked at
first, and then the complete snapshot they built on, which can go once none of them is left.

"Holds all of its data" is said of what a lockfile can pin, asset by asset:

| In the older snapshot | The new one holds it when |
|---|---|
| A dated dataframe | It has the same file, or the same rows up to the older one's last date: every period of the older one hashes the same in the new one's rows, and the new one has no row up to that date that the older one lacked |
| A dataframe with no dates | It has the same file, or the same rows, all of them |
| A dataframe with no rows hash | It has the same file |
| A model, and any asset marked `lock = true` | It has the same file |
| A chart, a notebook, a page | Always. *Decided 2026-11-19.* They never come out in the same bytes twice, so nothing would ever be cleared otherwise; and no lockfile holds them |

What a run never clears:

- one that holds rows the new one changed or lacks: a value revised, a column added or dropped, a
  dataframe that is gone;
- one that holds a version of an asset marked `keep = true` ({doc}`keep`) that the new one does
  not have, which is how a chart whose every version matters is held. The mark is read from the
  older snapshot's own record, where it has been written since `keep` was built, and never from
  the folder the run is in;
- the one a branch or a tag of the repository would be pinned from (below);
- a complete snapshot that a kept increment builds on;
- one that a pin made from a repository, which is the pinning machine's and no build of this
  pipeline's owner;
- anything, after a run that made no snapshot: `No new snapshot: the same bytes …` clears
  nothing.

Those wait for `chartbook store gc`, which lists what it would remove and asks, as today. So this
does not replace it: a source that revises old values leaves a snapshot behind each time it does.

**What a run says.** One line for what it cleared, with a count where there are several. Of the
snapshot before this one, if it is kept, one line with why (scenario 7). Older ones still kept
are counted in that line, and it names `chartbook store gc`. The line a snapshot has ended with
since 0.5.0, on what `store gc` could clear, goes, as step 3 of {doc}`one-command` had it.

**A branch or a tag.** A dependency can ask for a pipeline at a branch or a tag (`rev`), and is
then pinned from the newest snapshot of the first commit, going back from that branch's or tag's
own, that has one. `chartbook store gc` keeps that snapshot, and a run does too. *Proposed by
Claude, 2026-11-19:*

- **Among the snapshots of the commit the run is at, it is the new one.** So clearing an older
  snapshot of the same commit changes what no branch and no tag is pinned from, and git is not
  asked. This is the pipeline that pulls new data every day and whose code is as it was.
- **For an older snapshot of another commit, the run's own repository is asked** for its branches
  and tags, and that snapshot stays if one of them would be pinned from it.
- **In a clone without the whole history,** where git cannot say, only snapshots of the run's own
  commit are cleared.
- **A branch this clone does not have is not seen:** one never pushed, on another machine that
  shares the store. A snapshot only that branch would be pinned from can then be cleared. What
  had pinned it still reads its rows; a new pin by that branch's name finds an earlier snapshot,
  or is told to build one.

**A cleared snapshot's record is kept,** in `_chartbook/cleared/`, with the name of the snapshot
that held its data. *Proposed by Claude, 2026-11-19.* It is a few kilobytes. `chartbook lineage`
and `chartbook snapshot --deep` walk through it, so clearing breaks no lineage, which removing
with `store gc` does unless `--keep-lineage` is given; and a read is told by it where the rows
went.

**Why no pin has to be seen.** A lockfile pins a dataframe by its rows up to a date
({doc}`pins-and-rebuilds`). A snapshot that was cleared had all of those rows in a newer one, and
that one, if it is cleared in its turn, had all of its own in a newer one still. So for every pin
of a cleared snapshot the store has a snapshot with its rows.

**A read whose lockfile names a cleared snapshot** is given what it pinned. *Proposed by Claude,
2026-11-19:*

- **Where the newer snapshot has the same file, nothing is different.** A read asks the store for
  a file by its hash, today as then, and the store has it. This is every table that did not
  change.
- **Where it has the same rows in another file,** the newer snapshot stands in, by the rule a
  build of your own stands in by today ({doc}`pins-and-rebuilds`, "The check, cheapest first"),
  and the read is given its rows without those after the pin's `as_of` (scenario 8). The one thing
  added to that rule is where to look: at the snapshot the cleared one's record names as holding
  its data, and from there onward if that one was cleared too. A snapshot the store never had is
  stood in for as today, by a build of yours of the same commit and by nothing else.
- **Checked on the reader's machine, against the reader's own lockfile,** before anything is
  read, as a build that stands in is: the rows of each pinned period are compared, from the
  snapshot's record where a period is the same in both, and by hashing them in its table where
  not; a row up to `as_of` that the pin did not have fails it; and the result is remembered for
  that file. So the worst that can happen is a plain error that says the pinned rows are in no
  snapshot the store has. A read never gives other rows.
- **For the dependency whole,** as a build that stands in does: every pin of it has to be met by
  the one snapshot, and a chart of it is then read from that snapshot too.
- **It costs the reader one reading of each such table for each newer snapshot it comes to be
  read from.** A pin that is moved with `chartbook pin --update` costs nothing again.

**What a run looks at** is its own pipeline's snapshots in the store the new one went to, and
their records: never the whole store, whose plan `chartbook store gc` makes and which took 3.9
seconds on a store of 20 pipelines when step 3 was reviewed. Two records are compared period by
period, which reads no data: a period with the same dates and another hash has changed, and the
older snapshot is kept. Only where every period matches but the older one's last, which ends
earlier than the new one's, is the new table read, once, and the rows up to the older one's last
date hashed. That is the snapshot before this one, as a rule, and no other.

## Moving a store to this layout

`chartbook store migrate`, as for the move from 0.2. Any other command, given a store of 0.5,
says what scenario 10 shows and stops. *Proposed by Claude, 2026-11-19:*

- **The newest snapshot of each pipeline becomes a complete one, and each of the others an
  increment on it.** Files are moved, not copied: one goes to the newest snapshot's folder if
  that snapshot has it, and to the one older snapshot that has it otherwise. Only a file that two
  older snapshots have and the newest does not is copied, once. (The maintainer had agreed to
  "every snapshot becomes complete"; that copies every file two snapshots share, and this copies
  next to nothing.)
- **A snapshot that `chartbook pin` made from a repository becomes a complete one.**
- **A folder that held files for later snapshots and is no snapshot goes,** once the files that
  records name are out of it.
- **What no record names is not removed.** It is listed, and left where it is.
- **It can be stopped and taken up again,** by the journal the move from 0.2 keeps.
- **Nobody else writes to the store meanwhile,** and every machine that shares it needs this
  ChartBook afterwards. The command says both before it starts.

## What a person can do with a complete snapshot

A folder under `snapshots/` is the pipeline's own files and a record of them. ChartBook sends
nothing to anybody; what a person does with a folder is theirs to decide, with the licence of the
data in mind.

- Somebody without ChartBook reads the files.
- Somebody with ChartBook runs `chartbook store import` on it, which hashes every file against
  its record as it copies. *Proposed by Claude, 2026-11-19: `import` takes one snapshot's folder
  as well as a pipeline's.*
- `chartbook store export` is as it is: with `--latest` or `--snapshot` it writes complete
  snapshots, and a pipeline exported whole is written as the store keeps it.

## Not doing

- **A command to zip or send a snapshot,** and **a mark that keeps one asset out of every
  store.** *Decided 2026-11-19: both were proposed and both declined.* The list of commands stays
  as short as {doc}`one-command` made it.
- **Complete snapshots by default.** *Decided against, 2026-11-19.*
- **Increments of rows.** See "Dated dataframes".
- **Keeping the newest snapshot complete by moving files forward into it.** Files would move
  after they were written, in folders a sync service keeps.

## The order of work

One pull request each. Each changes the reference, the vocabulary, the skill and the assistant
files for what it changes.

1. This page.
2. The layout, read and written: `snapshots/`, `increments/` and `_chartbook/`; a snapshot of
   either kind is read, and every new one is written complete for now; `chartbook store migrate`
   from the layout of 0.5; `store ls`, `store export` and `store import`; the S3 store.
3. Increments are made: which one a run makes, the last line of a run, `chartbook snapshot` and
   `run --snapshot` complete, completing one.
4. A read from a newer snapshot that holds the pinned rows.
5. A run clears what the new snapshot holds.
6. The guide, the vocabulary and the changelog, read through once more against what was built.
