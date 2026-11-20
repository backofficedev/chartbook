# Design: snapshots and increments

```{note}
A design document, written 2026-11-19 from a day of planning with the maintainer. He looked at
his own store in a file browser and could not say what its folders were for, nor where the files
of a nearly empty snapshot were. It says how the store is laid out so that a person can read it,
when a run makes a complete snapshot and when a smaller one, and when a run may clear an old
snapshot without anybody losing data. It is for 0.6.0, with {doc}`one-command`.

Status: **to be built, step by step, in "The order of work" at the end.** Each part says whether
the maintainer decided it, and when. A choice he left open is marked *Proposed by Claude*, with
its date, until he says otherwise. The page was read against the code by a reviewer before
anything was built, who was asked to break it; what that changed is marked *(found by review)*,
and it changed "Clearing" most. Nothing here adds a command, an option or a field of
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
        _chartbook/index.json
        _chartbook/snapshot.json             its record
  increments/
    acme+rates/
      2026-11-19T140200Z_9b1e22d7a0c4/      a snapshot kept as an increment:
        _output/curve.html                   only the files that differ from the one above
        _chartbook/index.json
        _chartbook/snapshot.json
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

The output is as it is to be built; where a line exists today it is today's. A count of files is
of the files a record lists: here the table, the chart, the two documents and the index.

**1. The first run of a pipeline makes a complete snapshot.**

```text
$ chartbook run
acme/rates: build
acme/rates at 4f2a91c: 3 asset(s) in the store
Snapshot made: 5 files, 23 MB.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**2. A later run, where little changed, makes an increment.** The chart was drawn again and the
table is the same file.

```text
$ chartbook run
acme/rates: build
acme/rates at 9b1e22d: 3 asset(s) in the store
Snapshot made, kept as an increment: 2 of 5 files, 0.4 MB. The rest is in the snapshot made 2026-11-16 09:15 UTC.
A pipeline that depends on this one gets it with `chartbook pin --update`.
```

**3. The increments have added up, so the next one is complete.**

```text
$ chartbook run
acme/rates: build
acme/rates at c07d3e1: 3 asset(s) in the store
Snapshot made: 5 files, 23 MB. The increments since the last complete one had added up to its size.
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
always makes a complete one, and says where it is.

```text
$ chartbook snapshot
acme/rates at c07d3e1: 3 asset(s) in the store
Snapshot made: 5 files, 23 MB.
  ~/.chartbook/store/snapshots/acme+rates/2026-11-21T101500Z_c07d3e1a55f0
```

**6. A pipeline that pulls new data every morning, and whose code is as it was.** Yesterday's
snapshot and today's are of the same commit and differ by one day of rows, so yesterday's is
cleared.

```text
$ chartbook run
acme/rates: build
acme/rates at c07d3e1: 3 asset(s) in the store
Snapshot made: 5 files, 23 MB.
acme/rates: the snapshot made 2026-11-22 09:02 UTC is cleared. This one holds all of its rows.
```

**7. The same pipeline, on a morning when the source had revised a value of October.**
Yesterday's snapshot holds rows that today's does not, and is kept.

```text
$ chartbook run
…
Snapshot made: 5 files, 23 MB.
acme/rates: the snapshot made 2026-11-23 09:02 UTC is kept. It has rows this one changed (treasury, in 2026-10).
```

**8. A pipeline whose lockfile names a cleared snapshot,** on a branch nobody had touched for a
month, so that the store had no note of its pin. `data.load` gives it the rows it pinned.

```text
$ chartbook run
acme/rates: the snapshot the lockfile names (c07d3e1, made 2026-11-22 09:02 UTC) is not in the store.
  Its rows are read from a later snapshot of the same commit, made 2026-11-23 09:02 UTC,
  without the rows after 2026-11-21.
acme/report: build
…
```

**9. Looking at the store.**

```text
$ chartbook store ls acme/rates
acme/rates
  2026-11-16 09:15 UTC  4f2a91c  complete                              5 files   23 MB
  2026-11-19 14:02 UTC  9b1e22d  increment on 2026-11-16 09:15 UTC     2 files  0.4 MB
```

**10. A store made by an earlier ChartBook** is read as it is, and moved once before a snapshot
is made in it.

```text
$ chartbook run
acme/rates: build
acme/rates: not snapshotted: the store at ~/.chartbook/store has the layout of ChartBook 0.5.
  `chartbook store migrate` moves it. An earlier ChartBook will not read it afterwards.

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
| `store.json` | Which layout this is: `chartbook/store/v3` | the same file, `v2` |
| `README.txt` | What the folder is, in a few lines, for whoever opens it | new |

- **A pipeline's folder and a snapshot's folder are named as today:** `acme+rates`, and
  `2026-11-16T091500Z_4f2a91c0e1b2` for when it was made and its commit.
- **`store.json` stays at the top.** *Proposed by Claude, 2026-11-19; the maintainer had agreed to
  everything of ChartBook's own going under `_chartbook/`.* It is the one file an earlier
  ChartBook looks for. Left where it is and saying `v3`, ChartBook 0.5 says `The store at … has
  the layout 'chartbook/store/v3', and this version of ChartBook reads 'chartbook/store/v2'. Use
  a newer ChartBook …` and writes nothing, once the file has reached that machine. Moved, there
  would be no marker where 0.5 looks, and it would write one of its own and a `pipelines/` beside
  the snapshots.
- **What is being written stays inside the store,** in `_chartbook/tmp/`: a file is written there
  and then renamed into place, which needs the two on one disk.
- **`snapshots/0000…/`, the mark the move from the layout of 0.2 left, goes.** *Proposed by
  Claude, 2026-11-19.* It was there for ChartBook 0.2 to trip over, the name it sat under is now
  the snapshots' own, and a store of 0.2 is moved by 0.5 first.
- **Each pipeline's folder has a `README.txt`,** as today, in new words: under `snapshots/`, that
  each folder is complete and may be copied as it is, and that one is removed with `chartbook
  store gc` and not by hand while an increment builds on it; under `increments/`, what an
  increment is and where the rest of its files are.
- **A path is one character longer under `increments/` than it was under `pipelines/`.** Whatever
  writes there checks the length first, as the writer does today for a store on Windows. *(Found
  by review.)*

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
- **Its record lists every file of its version,** as any snapshot's does, each with the folder
  that keeps it. That is one of two: its own, or the one it builds on. The record names that one
  (`builds_on`), and so does the one line of `_chartbook/INCREMENT.txt`, for a person:

  ```text
  The rest of this snapshot's files are in snapshots/acme+rates/2026-11-16T091500Z_4f2a91c0e1b2
  ```

  *Proposed by Claude, 2026-11-19: the file is under `_chartbook/`, the one name in a snapshot's
  folder that is ChartBook's own, so no file of a pipeline's can have its name.*
- **What it builds on is said where the record says how the store keeps the snapshot,** beside
  each file's place, and not among what the snapshot is. *(Found by review.)* The same snapshot
  in two stores is told to be the same by its record less that part; one store may keep it
  complete and the other as an increment.
- **If the snapshot it builds on is gone before its record is written,** it is written complete:
  whatever is writing it has every file of it at hand.
- **An increment whose snapshot is gone is no snapshot.** *Proposed by Claude, 2026-11-19 (found
  by review).* That can happen: a machine that has not synced makes an increment on a snapshot
  that another machine has just cleared. Such a folder is passed over, as a folder without a
  record is today, and what had pinned it is read as "Clearing" says a cleared one is. `chartbook
  store gc` removes the folder.

What the rule gives:

| | Since 0.3.0 | With this |
|---|---|---|
| The folders a snapshot's files are in | Any number of earlier ones | One, or two |
| Removing a snapshot nothing needs | May leave its folder behind, for the files later ones keep in it | An increment goes whole; a complete one stays whole while an increment builds on it |
| A folder that holds files and is no snapshot | Yes, with `CLEARED.txt`, for as long as later snapshots use it | Only one left half removed, or the stranded increment above, until `store gc` |
| What a person can copy | A pipeline's first snapshot, if they know which | Anything under `snapshots/` |

It is not a diff, as a shared snapshot was not ({doc}`plan-data-reads`): nothing is applied to
anything, and a read opens files where they are.

## Which one a run makes

*Decided 2026-11-19: `chartbook run` decides by itself, and nobody has to learn a command for
it.*

**A run makes an increment until the increments since the last complete snapshot, with this one,
add up to the size of a complete one. Then it makes a complete one.**

- **The first snapshot of a pipeline in a store is complete:** there is nothing to build on.
- **One where every file differs is complete:** the increment would be the whole of it.
- **Sizes are bytes of files.** A snapshot's size is that of every file its record lists; an
  increment's is that of the files in its own folder.
- **The count is kept in the records,** each increment's saying the total up to and with itself,
  beside what it builds on. *Proposed by Claude, 2026-11-19.* It is a count of what was copied,
  so clearing an increment does not take from it.
- **Each store decides for itself,** where a snapshot goes to several.
- **Where nothing has changed there is no new snapshot,** as today: the same commit, the same
  bytes and the same pins.

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

- **Where the newest snapshot is an increment of these same files, they make a new, complete
  one.** *Proposed by Claude, 2026-11-19 (found by review).* It is the one case in which the same
  files make a new snapshot. The first draft of this page turned the increment into a complete
  snapshot in its place; that changes a snapshot after it is made, and leaves two folders of one
  name for a moment. A new one changes nothing that exists, and the increment is cleared like
  any other.

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
- **What `chartbook pin` and `chartbook pin --update` take is found as today.** Nothing in those
  rules knows the kind.
- **A read asks the store for an asset by its hash and is handed its files,** each where it is
  kept, as today. For an increment those are in two folders.
- **Not completed when pinned.** That was considered: an increment nobody has pinned could then be
  cleared with no care at all. But whoever pins would pay for it. On the one pipeline of "What was
  wrong" with 9 GB in earlier folders, a `chartbook pin --update` would copy those 9 GB from the
  reader's machine; a reader who cannot write to the store could not pin the newest at all; and a
  pipeline whose reader takes every snapshot would have none but complete ones.

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

*Decided 2026-11-19, in place of step 3 of {doc}`one-command`: a run clears an older snapshot,
whole, when the new one holds all of its data; and a chart or a notebook does not count as data.*
Step 3 applied `chartbook store gc`'s rules at every run. They decide from what the store can see
of who pins what, and its review showed what the store cannot see: a pin on another branch of a
pipeline that depends on this one, and a pin of anybody who may not write to the store.

The rule as the maintainer decided it had one condition. A reviewer, asked to break it before it
was built, showed data lost, or a read given more than it had pinned, in ten ways. So it has four
conditions here, each *proposed by Claude, 2026-11-19 (found by review)*, and it clears less than
he was first told. What it does not clear waits for `chartbook store gc`, as today.

**After a run or `chartbook snapshot` makes a snapshot, an older snapshot of the same pipeline is
cleared when all four hold. A snapshot is cleared whole, or kept whole.**

1. **It is of the same commit as the new one,** and of the same repository, and the pipeline's
   owner made it.
2. **No lockfile that the store has a note of pins it.**
3. **The new one holds all of its data.**
4. **Nothing else holds it:** no asset marked `keep = true`, no increment that is kept, and no
   date that is out of order.

### 1. The same commit

At one commit the code is the same, so a later snapshot of it is the same thing made later, with
whatever the source had added.

- **Nothing a branch, a tag or a folder is pinned from changes.** A dependency that asks for a
  pipeline at a branch or a tag is pinned from the newest snapshot of the first commit, going
  back from that branch's or tag's own, that has one. Among the snapshots of one commit that is
  the new one, before the clearing and after. So git is asked nothing. (The first draft cleared
  snapshots of other commits and asked the run's own clone for its branches and tags; a pin by
  `rev` asks the dependency's remote, and a pin of a folder its checkout, which is not the same
  question.)
- **A read of a cleared snapshot needs nothing new.** Where the store does not have the snapshot
  a lockfile names, what was pinned is read from another snapshot of that pipeline at that
  commit that meets every pin, the newest that does. That is built
  ({doc}`pins-and-rebuilds`, "The check, cheapest first"), for a class in which each student
  builds the upstream. `chartbook store gc` keeps such snapshots already, and `chartbook snapshot`
  takes one as the lineage of what it reads.
- **Lineage walks on through it.** *Proposed by Claude, 2026-11-19.* A snapshot made before the
  clearing names the cleared one as what it was made from. `chartbook lineage` and `chartbook
  snapshot --deep` call that a gap today, as they do after `store gc` without `--keep-lineage`.
  They go on instead through the later snapshot of that commit that stands in for it, and say
  that they did.
- **So this tidies the pipeline that is run again and again as it is:** the pull every morning.
  A pipeline being worked on leaves a snapshot at each commit, most of them small increments, as
  it does today, for `chartbook store gc`.

### 2. No pin the store knows of

A pin, or a read through a lockfile, leaves a note in the store of what that lockfile names. A
snapshot that a note names is not cleared by a run.

- **Whoever is pinned to a snapshot, where the store can see it, keeps exactly that snapshot:**
  its files, its charts, the path `data.path` gives. Moving the pin with `chartbook pin --update`
  moves the note, and the old snapshot can go at the next run.
- **The notes are read, and no lockfile is.** A note that cannot be read stops the clearing, with
  a line that says so, as it stops `store gc`.
- **A note outlives its lockfile,** and then holds what it names until `chartbook store gc
  --forget-missing` on the machine that wrote it. That errs toward keeping.
- **Conditions 3 and 4 are for the pins that leave no note:** a lockfile on another branch, a
  reader who may not write to the store, a build in CI.

### 3. The new one holds all of its data

**The new snapshot has to meet every pin that a lockfile could have made of the older one, by
the check a read makes** (`standins.compare`, with the older snapshot's records as the pins).
One function, so that a run cannot clear what a read would then refuse.

| In the older snapshot | The new one meets it with |
|---|---|
| A dated dataframe whose rows were hashed | The same file; or the same rows up to the older one's last date, period by period, and no row up to that date or with no date that the older one lacked |
| A dataframe with no dates, hashed | The same file, or the same rows |
| A dataframe whose rows were not hashed, or that had no rows | The same file |
| A model, a plain file, and anything marked `lock = true` | The same file |
| A chart, a notebook, a page, not so marked | Nothing: they are not counted |

- **A chart or a notebook is not counted.** *Decided 2026-11-19.* They never come out in the same
  bytes twice, so nothing would ever be cleared otherwise.
- **A snapshot with nothing that is counted is kept.** A pipeline of charts alone is pinned by
  naming its snapshot, and "holds all of its data" would be true of it for no reason.
- **One made by a ChartBook before 0.6 is kept.** A lockfile of 0.5 pins every asset by its
  bytes, charts too, and such a snapshot records no rows.
- **One whose record has no rows hash for a dataframe is kept unless the new one has none for it
  either.** A pin made of it is of the file alone. If it were cleared into a snapshot with the
  same file and a rows hash, the next run could clear that one by its rows, into another file,
  and the first pin would be met by nothing.
- **A period of the older record with no line of the same dates in the new record is read,** not
  taken as held: the older one's last period always, and a year that has since been split into
  months.

### 4. Nothing else holds it

- **`keep = true`.** A snapshot that has a version of a kept asset which the new one does not is
  kept ({doc}`keep`). The mark is read from both records, the older one's and the new one's, and
  never from the folder the run is in: the run that first carries the mark must not clear the
  versions it was written to keep.
- **A complete snapshot that a kept increment builds on is kept.** Increments are looked at
  first.
- **Dates out of order.** Nothing is cleared unless the new snapshot is the one made last of its
  pipeline, by the records: one dated after it was written by a clock that is wrong, here or
  there. And a snapshot that stands in for a cleared one is taken whatever its date, since its
  rows are checked. Today one dated after now is passed over, which would leave the pins of what
  a fast clock had cleared with nothing to read until its date had come.
- **A snapshot that a pin made from a repository** is the pinning machine's and no build of the
  pipeline's owner: never cleared here, never built on.
- **A run that made no snapshot clears nothing.**

### What reads of a cleared snapshot are given

Only a reader whose pin left no note can meet this (condition 2).

| Read | What it is given |
|---|---|
| A file the new snapshot also has | That file, found by its hash as any is |
| `data.load`, `data.sql` of a table with the same rows in another file | The pinned rows: the later snapshot's, without those after the pin's `as_of` |
| `data.path`, `data.files`, `chartbook path` of such a table | **The later file as it is, newer rows and all**, said once, with `data.as_of` to cut it by |
| A chart or a notebook | The later snapshot's |

*This is what a build of your own that stands in gives, as decided 2026-11-15
({doc}`pins-and-rebuilds`, "Reads"), and it now reaches further: until now only somebody who had
built the upstream themselves could meet it.* The first draft said "a read never gives other
rows", which is true of `data.load` and `data.sql` and not of a path. *(Found by review. The
maintainer has not yet been asked whether a path should stop instead.)* The check is the
reader's own, against the reader's own lockfile, before anything is read, and its result is
remembered for the file that was checked.

### What a run says

One line for what it cleared, with a count where there are several. Of the snapshot before this
one, if it is kept, one line with why (scenario 7). The line a snapshot has ended with since
0.5.0, on what `chartbook store gc` could clear, stays: it is how the snapshots of earlier
commits are heard of.

### How it is done

- **By the store's own removing,** which `store gc` uses: the record first, then the folder, and
  a file that a snapshot being written elsewhere has noted is left. A folder that cannot be
  removed whole (a file open on Windows, a bucket whose writer may not delete) is left without
  its record for `store gc`, and said in a line. The catalog's page of that snapshot goes with
  it.
- **It looks at its own pipeline's snapshots, in the store the new one went to,** their records,
  and the notes. Never the whole store: the plan `chartbook store gc` makes took 3.9 seconds on a
  store of 20 pipelines when step 3 was reviewed.
- **Two records are compared period by period, which reads no data.** A period with the same
  dates and another hash has changed, and the older snapshot is kept. The new table is read only
  where every period matches but those with no line of the same dates, which as a rule is the
  older one's last period, in the snapshot before this one.
- **`chartbook run --upstream` clears for the pipeline it was asked to run,** and not for the
  ones it builds on the way.

## What the store promises now

The store of 0.3.0 promised that nothing in it is moved or rewritten once written, and that only
`store gc` removes. This design keeps the first half and changes the second. *(Found by review:
the first draft leaned on the promise and broke it.)*

- **A snapshot's folder is not changed once its record is written.** As before.
- **A run removes whole snapshots,** by "Clearing". New. Until now a snapshot went only when
  somebody ran `store gc`, read its list and said yes.
- **`chartbook store migrate` moves every file once.** As the move from 0.2 did.

## Moving a store to this layout

*Proposed by Claude, 2026-11-19.*

- **This ChartBook reads a store of 0.5 as it is,** and writes its notes there as 0.5 does.
  *(Found by review: {doc}`pins-and-rebuilds` promises that a store is shared across versions,
  and somebody who may only read a store cannot move it.)* It makes no snapshot in one and
  removes nothing from one: a run says so in its last line (scenario 10), and `chartbook
  snapshot` and `chartbook store gc` stop with the same words.
- **`chartbook store migrate` moves it,** as it moved a store of 0.2.
- **The newest snapshot of each pipeline becomes a complete one, and each of the others an
  increment on it.** Files are moved, not copied: one goes to the newest snapshot's folder if
  that snapshot has it, and to an older snapshot that has it otherwise. A file that several
  older snapshots have and the newest does not is copied into each of them but one. (The
  maintainer had agreed to "every snapshot becomes complete"; that copies every file two
  snapshots share.)
- **A snapshot that `chartbook pin` made from a repository becomes a complete one,** with a copy
  of each file it shared.
- **A folder that held files for later snapshots and is no snapshot goes,** once the files that
  records name are out of it.
- **What no record names is not removed.** It is listed, and left where it is.
- **It can be stopped and taken up again,** by the journal the move from 0.2 keeps.
- **Nobody else writes to the store meanwhile,** and every machine that shares it needs this
  ChartBook afterwards: a 0.5 that has not yet seen the new `store.json` would go on writing a
  `pipelines/` folder. The command says both before it starts, and looks once more at the end
  for anything that arrived during the move.
- **In a bucket a move is a copy and a delete,** file by file.

## What a person can do with a complete snapshot

A folder under `snapshots/` is the pipeline's own files and a record of them. ChartBook sends
nothing to anybody; what a person does with a folder is theirs to decide, with the licence of the
data in mind.

- Somebody without ChartBook reads the files.
- Somebody with ChartBook runs `chartbook store import` on it, which hashes every file against
  its record as it copies. *Proposed by Claude, 2026-11-19: `import` takes one snapshot's folder
  as well as a pipeline's.*
- `chartbook store export` writes a folder laid out as a store of this layout; with `--latest`
  that is one complete snapshot, as today.
- A pipeline copied from one store to another (`store move`, `store import`) keeps its form:
  each complete snapshot, then the increments on it.

## What it costs

- **A complete snapshot copies every file,** and into a synced folder that is an upload. The
  rule of adding up bounds how often.
- **A kept increment holds its whole complete snapshot in the store.**
- **A table too large or too wide to have a rows hash is cleared only where its file is the
  same.** So is one in a pipeline nobody has run with 0.6.
- **A reader whose pinned snapshot was cleared reads each changed table through once,** to check
  it, for each later snapshot it comes to be read from. Only a reader the store had no note of.
- **Rows hashed as they are today have to be checked the same way by every later ChartBook.**
  Until now a pin could always be met by its bytes alone; a pin of a cleared snapshot can only be
  met by its rows.
- **A build that is reading a snapshot while a run clears it fails,** and is run again.
- **A file removed from a folder a sync service keeps stays in that service's trash** for a
  time, and may count against its room.
- **`chartbook run --snapshot` in a script copies everything each time.**
- **Until increments are made (step 5 below), main keeps every snapshot complete.** Nobody but
  the maintainer uses main.

## Not doing

- **A command to zip or send a snapshot,** and **a mark that keeps one asset out of every
  store.** *Decided 2026-11-19: both were proposed and both declined.* The list of commands stays
  as short as {doc}`one-command` made it.
- **Complete snapshots by default.** *Decided against, 2026-11-19.*
- **Increments of rows.** See "Dated dataframes".
- **Keeping the newest snapshot complete by moving files forward into it.** Every run would move
  files out of folders that records name and reads have open.
- **Clearing, at a run, a snapshot of an earlier commit.** It needs a read that looks beyond the
  pinned commit, a record of what was cleared into what, and an answer for a dependency pinned
  by a branch or a tag. The first draft had all three, and the review broke each. Later, if the
  snapshots of a pipeline being worked on prove to be too many.
- **Turning an increment into a complete snapshot in its place.**

## The order of work

One pull request each. Each changes the reference, the vocabulary, the skill and the assistant
files for what it changes.

1. This page.
2. The layout in the folder store: `snapshots/`, `increments/` and `_chartbook/`, read and
   written; a snapshot of either kind is read, and every new one is written complete for now; a
   store of 0.5 is read as it is; `store gc`, `store verify`, `store move`, `restore` and `store
   ls` on the new layout.
3. `chartbook store migrate` from the layout of 0.5.
4. The S3 store, and `store export` and `store import`.
5. Increments are made: which one a run makes, the last line of a run, `chartbook snapshot` and
   `run --snapshot` complete.
6. A run clears: the four conditions; an increment whose snapshot is gone is passed over; a
   snapshot that stands in is taken whatever its date; lineage walks on through one; the words
   of the line a read says when another snapshot stands in.
7. The guide, the vocabulary and the changelog, read through once more against what was built.
