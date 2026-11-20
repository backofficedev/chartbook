# Design: snapshots and increments

```{note}
A design document, written 2026-11-19 from a day of planning with the maintainer. He looked at
his own store in a file browser and could not say what its folders were for, nor where the files
of a nearly empty snapshot were. It says how the store is laid out so that a person can read it,
and when a run makes a complete snapshot and when a smaller one. It also records what was decided
about a run clearing old snapshots, and why that part is held. It is for 0.6.0, with
{doc}`one-command`.

Status: **to be built, step by step, in "The order of work" at the end.** Each part says whether
the maintainer decided it, and when. A choice he left open is marked *Proposed by Claude*, with
its date, until he says otherwise. The page was read against the code twice before anything was
built, by reviewers asked to break it; what that changed is marked *(found by review)*. The
layout and the increments stood; the clearing did not, twice, and its section says so. Nothing
here adds a command, an option or a field of `chartbook.toml`.
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

**6. Looking at the store.**

```text
$ chartbook store ls acme/rates
acme/rates
  2026-11-16 09:15 UTC  4f2a91c  complete                              5 files   23 MB
  2026-11-19 14:02 UTC  9b1e22d  increment on 2026-11-16 09:15 UTC     2 files  0.4 MB
```

**7. A store made by an earlier ChartBook** is read as it is, and moved once before a snapshot
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
- **`store.json` stays at the top.** *Proposed by Claude, and decided 2026-11-19; the maintainer
  had first agreed to everything of ChartBook's own going under `_chartbook/`.* It is the one
  file an earlier
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
  owner made, of the same repository as the records tell it (what a snapshot's making asks
  already, before it says two are of one pipeline). *Proposed by Claude, 2026-11-19.* A snapshot that `chartbook pin` makes from a
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
- **An increment whose snapshot is gone has lost the files it kept there.** *(Found by review.)*
  That can happen: a machine that has not synced makes an increment on a snapshot that
  `chartbook store gc` has removed on another machine, more than a week after it was made. What
  the increment's own folder holds is still read; a read of one of the lost files says that it is
  not in the store, as it does today for a file that is lost. `store gc` never removes a complete
  snapshot that an increment it can see builds on.

What the rule gives:

| | Since 0.3.0 | With this |
|---|---|---|
| The folders a snapshot's files are in | Any number of earlier ones | One, or two |
| Removing a snapshot nothing needs | May leave its folder behind, for the files later ones keep in it | An increment goes whole; a complete one stays whole while an increment builds on it |
| A folder that holds files and is no snapshot | Yes, with `CLEARED.txt`, for as long as later snapshots use it | Only one that a removal left half done, until the next `store gc` |
| What a person can copy | A pipeline's first snapshot, if they know which | Anything under `snapshots/` |

It is not a diff, as a shared snapshot was not ({doc}`plan-data-reads`): nothing is applied to
anything, and a read opens files where they are.

**A complete snapshot has every file in its place, twice where two are the same.** *(Found by
review.)* Today two files of one snapshot with the same bytes are kept once, under the first
one's name. Under `snapshots/` both are written, or the folder could not be read without its
record.

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
  so removing an increment does not take from it.
- **A table in one file that gains a day makes an increment nearly the size of the whole,** since
  the documents beside it did not change, and the run after it a complete one. So such a pipeline
  alternates, and copies what a complete snapshot at every run would.
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
  one.** *Proposed by Claude (found by review), and decided 2026-11-19.* It joins the few cases
  in which the
  same files make a new snapshot today (documents that changed, rows recorded for the first
  time). The first draft of this page turned the increment into a complete snapshot in its
  place; that changes a snapshot after it is made, and leaves two folders of one name for a
  moment. A new one changes nothing that exists.

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
  removed with no care at all. But whoever pins would pay for it. On the one pipeline of "What was
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

## Clearing: decided in principle, held, and not to be built yet

*Decided 2026-11-19: a run clears an older snapshot, whole, when the new one holds all of its
data; a chart or a notebook does not count as data; and it is wanted in 0.6.0.* It was to take the
place of step 3 of {doc}`one-command`, which applied `chartbook store gc`'s rules at every run,
was built, was shown to lose data, and is held back.

*Decided 2026-11-19, after the two reviews: 0.6.0 may be released without it, and the work on a
rule goes on. Which form to try next is left to Claude.*

**Nothing of it is to be built from this page as it stands.** Two forms of the rule were read
against the code, before anything was built, by reviewers asked to break them. Both were broken,
on paper. This section records the two forms, what broke each, and what a third has to answer.
Until one survives such a reading, a run clears nothing, `chartbook store gc` clears as it does
today, and the line a snapshot ends with says what it could clear.

### The first form

*One condition: the new snapshot has, for every dataframe of the older one, the same rows up to
the older one's last date.* No pin had to be seen, because a lockfile pins a dataframe by its
rows ({doc}`pins-and-rebuilds`) and a read of a cleared snapshot would be given those rows from
the newer one. A record of each cleared snapshot was kept, naming the one that held its data, and
the run's own clone was asked which snapshot a branch or a tag is pinned from.

What broke it *(found by review)*:

1. **A chain of clearings is only as strong as its weakest link.** A is cleared because B has
   the same file; B, which has a rows hash that A lacked, is cleared because C has the same rows
   in another file. A pin of A's file is then met by nothing.
2. **`chartbook store gc` would remove the snapshot that held a cleared one's rows.** Its notes
   and lockfiles name the one that is gone.
3. **A read by path is given later rows.** Where a build stands in, `data.load` and `data.sql`
   give the pinned rows, and `data.path`, `data.files` and `chartbook path` hand over the file as
   it is, newer rows and all, and say so once (*decided 2026-11-15*). Until now only somebody who
   had built the upstream themselves met that. So "a read never gives other rows" was false.
4. **A lockfile of 0.5 pins every asset by its bytes, charts too,** and a pipeline of charts
   alone is pinned by naming its snapshot. Leaving charts out of the count unpinned both.
5. **`keep = true`, read from the older snapshot's record alone,** let the run that first carried
   the mark clear the versions it was written to keep.
6. **A pin by `rev` asks the dependency's remote, and a pin of a folder its checkout.** The run's
   own clone answers another question.
7. **A machine that has not synced** makes an increment on a complete snapshot that another
   machine has just cleared, and its files are gone when the two meet.
8. **A clock that is ahead** writes a snapshot that every other machine passes over, and the
   older ones are cleared into it.
9. **A record of what was cleared does not travel** with `store move`, `export` or `import`.

### The second form

*Four conditions: the older snapshot is of the same commit as the new one; no lockfile the store
has a note of pins it; the new one meets every pin a lockfile could have made of it, by the
check a read makes; and nothing else holds it (`keep`, an increment, a date out of order).* The
same commit took out the read beyond the pinned commit, the record of what was cleared and the
question to git: where the store does not have the snapshot a lockfile names, a read is given
what it pinned from another snapshot of that pipeline at that commit, and that is built.

What broke it *(found by a second review)*:

1. **In a synced folder a removal arrives before an upload.** A run writes today's snapshot on
   one disk and clears yesterday's; the removal reaches the other machines at once, and the new
   snapshot hours later, or never if the lid is closed. `chartbook store gc` waits seven days and
   asks. The rule had no waiting at all. A note that another machine wrote minutes before has
   not arrived either, so "no note pins it" is said of what this machine has seen.
2. **The stranded increment of the first review is a lost snapshot,** and not a cleared one: it
   is of another commit, and nothing stands in for it.
3. **The clock again.** A snapshot dated ahead is passed over by `chartbook pin --update` on
   every other machine as well as by reads, and `store gc` may remove it.
4. **The read's check cannot be used as it is.** It takes a pin as met where the store has the
   pinned file anywhere, and before the removal the store has the older snapshot's own files. The
   comparison has to be of the two snapshots' records.
5. **A file that is not marked `lock = true` is read from a later snapshot without a word,** as a
   chart is.
6. **More pins leave no note than were counted:** an earlier commit of a lockfile at the same
   path, a dependency that names a store, `chartbook pin --check`. And a note of another machine
   is never forgotten.
7. **A note that names a cleared snapshot holds nothing.** `store gc` keeps every snapshot of
   that commit for it; the rule did not, so what stands in would change at every run.
8. **The same commit is not the same inputs.** `chartbook run --snapshot` passes over a lockfile
   that is not committed, and a later snapshot of the commit can be made from other pins.
9. **"Of the same repository" has to be said by the records,** as a snapshot's own making says
   it.
10. **A `keep = true` given at a later commit** is in neither record of an earlier one.

### What a third form has to answer

- **Waiting.** Something has to stand where gc's seven days and its question stand: for the
  upload, for the note and the increment of a machine that has not synced.
- **What is compared.** The two snapshots' own records, and the pins they were made from.
- **The marks.** `keep`, labels, a branch and a tag, read as `store gc` reads them.
- **A note of a snapshot that is gone.**
- **Clocks.**
- **A complete snapshot that increments build on.**
- **Reads by path, and reads of what no lockfile holds.** Whether they stop, or say what they
  give.

*Proposed by Claude, 2026-11-19, and not reviewed:* the likeliest third form is **a run clears,
of its own pipeline, what `chartbook store gc` would remove, and of that only what a later
snapshot of the same commit and the same pins holds all the data of.** gc's rules are built and
were reviewed many times, and carry the waiting, the marks, the notes and the clocks; the second
half is for the pins gc cannot see, which is what stopped step 3. It clears less than the
maintainer was first told: the pull that runs every morning keeps a week of snapshots, and a
pipeline being worked on keeps one for each commit, until `chartbook store gc`.

### What a read is given where another snapshot stands in

This is as built, and true today for a build of your own. It is here because every form of
clearing makes more reads meet it.

| Read | What it is given |
|---|---|
| A file the other snapshot also has, of an asset the lockfile holds | That file, found by its hash |
| `data.load`, `data.sql` of a table with the same rows in another file | The pinned rows: the other snapshot's, without those after the pin's `as_of` |
| `data.path`, `data.files`, `chartbook path` of such a table | The other file as it is, newer rows and all; said once where there are newer rows, with `data.as_of` to cut it by |
| A chart, a notebook, a file the lockfile does not hold | The other snapshot's, and nothing is said |

*Decided 2026-11-19: whoever reads by `data.path` is to cut by `data.as_of` themselves; that is
theirs to know, and the reference is to say so where `data.path` is described, in so many
words.* The guide says it today in two places, and the function's own description does not.

## What the store promises

The store of 0.3.0 promised that nothing in it is moved or rewritten once written, and that only
`store gc` removes. *(Found by review: the first draft of this page leaned on the promise and
broke it three times.)*

- **A snapshot's folder is not changed once its record is written.** As before. That is why
  `chartbook snapshot` writes a new complete snapshot where the newest is an increment, and does
  not complete that one in its place.
- **Only `chartbook store gc` removes,** as before, until a form of "Clearing" is settled.
- **`chartbook store migrate` moves every file once.** As the move from 0.2 did.

## Moving a store to this layout

*Proposed by Claude, 2026-11-19. Decided the same day: a store of 0.5 is read as it is; the
newest snapshot of each pipeline becomes complete and the others increments on it; and the
maintainer's own stores are moved at the release and not before, since his installed ChartBook
and his other work read them with 0.5 until then.*

- **This ChartBook reads a store of 0.5 as it is,** and writes its notes there as 0.5 does.
  *(Found by review: {doc}`pins-and-rebuilds` promises that a store is shared across versions,
  and somebody who may only read a store cannot move it.)* It makes no snapshot in one and
  removes nothing from one: a run says so in its last line (scenario 7), and `chartbook
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
- **An increment holds its whole complete snapshot in the store** for as long as it is kept.
- **Nothing is removed by a run,** so a pipeline's snapshots are as many as today until
  `chartbook store gc`, and each complete one is whole where today its unchanged files were kept
  once. A large pipeline that makes a complete snapshot often takes more room than it did.
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
6. Clearing: not before a form of it has stood a review, and the maintainer has said which.
7. The guide, the vocabulary and the changelog, read through once more against what was built;
   and what `data.path` says of `data.as_of`.
