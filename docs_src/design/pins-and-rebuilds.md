# Design: pins that a rebuild can meet

```{note}
A design document, written 2026-11-16 from two days of planning with the maintainer. It says how a
lockfile stays useful when the pinned bytes cannot travel, so that each person rebuilds the
upstream: what the lockfile holds for each kind of asset, how a dataframe is pinned by its rows as
well as its bytes, and what each command and each read then does.

Status: **being built, step by step, in "The order of work" at the end; no release is named.**
Built so far: the lockfile by kind (step 2), the rows hash (step 3), periods in a snapshot's
record and in the lockfile (step 4), and the check, with a build of yours that stands in (step 5).
A read through a build that stands in gives the pinned rows, and `data.as_of` says where they
end (step 6). Each part says whether the maintainer decided it, and
when, or whether it is a proposal. The items marked *(Proposed.)* were decided as proposed on
2026-11-16. A choice made while building, on what the page had left open, is marked *Proposed by
Claude*, with its date, until the maintainer says otherwise. The numbers come from a prototype run
on 2026-11-15 and 16, on an Apple M3 Max with 64 GB, polars 2.1.0, pyarrow 26.0.0 and pandas 3.1.0.
```

## The story this serves

A class writes one report together. The report depends on six public pipelines, and its
`chartbook.lock` pins a snapshot of each. There is no shared store: each student clones every
upstream at the commit the lockfile names, runs `chartbook run --snapshot` there, and checks with
`chartbook pin --check` (`pin --frozen` before #186).

It did not work, twice (the course's discussion #31, November 2026):

1. **New data.** A student's rebuilt tables had other sizes than the pinned ones. The Fed and Ken
   French had published since the pin, so the check exited 1 ("is pinned at … and the store … does
   not have it") and the build stopped with `AssetNotPinnedError`.
2. **Charts and notebooks.** Another student's dataframes matched and the report built, but the
   check still failed on 17 pins: the 10 charts and 7 notebooks of the 34 assets pinned. No rebuild
   can match those. Rendered twice, a second apart, a Plotly HTML chart differs by a random id in
   the page, and an executed notebook by the time it records for each cell. (A matplotlib PNG came
   out the same both times, so it depends on the renderer, which ChartBook cannot know.)

A pin records the hash of each file's bytes. That is the right record when the bytes travel through
a store. When they do not, the only way to get the pinned data is to build it again, and a pin
that only bytes can meet is of no use the day after it is made.

## What changes between two pulls

| What changed | With this design |
|---|---|
| New rows after the last date | The pin is still met |
| The same rows in other bytes: another parquet writer, another row order | The pin is still met |
| Old values revised, or arriving late (FRED, Ken French) | Reported as a real difference |

Nothing here brings back data a source has revised. Only a store that shares the bytes does that,
or a pull that can ask the source for an old vintage.

## The idea in one example

On November 4 the author pins this table of an upstream:

| ds | y |
|---|---|
| 2026-10-28 | 4.10 |
| 2026-10-29 | 4.12 |
| 2026-10-30 | 4.11 |

The lockfile records the last date, October 30, and a hash of those three rows.

On November 12 a student builds the same commit and gets five rows: the same three, and November 2
and 3. To check, ChartBook leaves out the student's rows after October 30, hashes the three that
remain, and compares. They match: the student's table holds the pinned data, and two newer days.

## What you see

Scenarios 1 to 3 are as built (step 5): each block is from a run on 2026-11-17 of a small made-up
upstream, 800 rows pinned through 2026-10-30, with the author and the student each in a scratch
store of their own. Scenarios 4 and 5 are proposed, not what any version prints.

**1. A team shares a store.** Nothing changes. The pinned files are in the store, and are read.

**2. A student builds an upstream a week after the pin.** Before they have built it, the check
says what is missing once for each dependency, and the way on that is theirs first:

```text
$ chartbook pin --check
ftsfr/fed_yield_curve: 1 of its 1 pin is not in the store at ~/student-store, and no build of yours
    at 0db8051 stands in: treasury_yields
  To build it yourself: in ../fed_yield_curve, `git checkout 0db8051` and `chartbook run --snapshot`:
    a build of yours meets a pin by the same file or, for a dataframe, by the same rows up to the
    pin's last date.
  Where a store is shared: point CHARTBOOK_STORE at the one that has it; in a synced folder, wait
    for the sync to finish, here and on the machine that made the pin.
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.
```

(Where the store has some other snapshot of that pipeline, a last line offers it: `To move the pin
to a snapshot the store has: chartbook update ftsfr/fed_yield_curve`. With none, as here, `update`
has nothing to move to, and is not offered.)

After `chartbook run --snapshot` in the upstream, twelve days of new data and all, the lockfile is
not touched, `uv run doit` builds, and a reviewer who builds it a week later still sees the same.
A build is named by its commit and when it was made, since several builds may share a commit.

```text
$ chartbook pin --check
ftsfr/fed_yield_curve: read from your own build of 0db8051, made 2026-11-17 09:22 UTC
  treasury_yields: the pinned rows, through 2026-10-30; 24 newer rows
1 pin(s) of 1 dependency: 0 in the store, 1 met by your own build. Nothing written.

$ chartbook run
finm/report: pinning what it depends on
ftsfr/fed_yield_curve: 1 met by your own build
  Read from your own build of 0db8051, made 2026-11-17 09:22 UTC.
  treasury_yields: the pinned rows, through 2026-10-30; 24 newer rows
chartbook.lock is unchanged.
finm/report: build
…

$ chartbook lineage
finm/report (this folder)
└── ftsfr/fed_yield_curve: ftsfr/fed_yield_curve 0db8051, made 2026-11-17 09:22:12 UTC, pins checked;
    your build stands in for the pinned snapshot, which the store does not have
1 snapshot(s) upstream; no gaps.
```

A read says it once in a process, on stderr: `ftsfr/fed_yield_curve: read from your own build of
0db8051, made 2026-11-17 09:22 UTC. The store does not have the bytes chartbook.lock pins, and your
build holds the same rows.`

**3. The source has changed its past.** The check exits 1, and `chartbook pin`, `chartbook run` and
a read stop with the same words. (Here one value of 2025-12-14 was changed by 0.01.)

```text
$ chartbook pin --check
ftsfr/fed_yield_curve: your build of 79986dd, made 2026-11-17 09:21 UTC, does not match the pin
  treasury_yields: the rows of 2025-09-26 to 2025-12-31 differ
  To read your build instead: chartbook update ftsfr/fed_yield_curve
1 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.
```

**4. The maintainer moves the pins.** `chartbook update` says, for each dataframe, "8 new rows,
earlier rows unchanged" or "earlier rows changed". The lockfile's diff shows the last period's line
changed and nothing before it, and git keeps what the pin was.

**5. An agent refactors an upstream.** `chartbook snapshot` compares with the snapshot before and
says "earlier rows unchanged, 1 new row". The refactor changed no number, though a new day of data
arrived between the two builds.

## What the lockfile holds, by kind

| Kind | In the lockfile | Checked by |
|---|---|---|
| Dataframes | Yes | The same file; else the same rows, up to the pin's last date |
| Models | Yes, as today | The same file |
| Charts, notebooks, notes, files | No, unless the asset says `lock = true` | The same file, when locked |

*Decided 2026-11-15. Built (step 2).* The lockfile is about what code reads. A chart or a notebook
is drawn from the data, and is drawn anew by every build. A plain file can be either, so it is left
out unless its owner says otherwise, with one key on the asset in the owner's manifest:

```toml
[files.parameters]
path = "./_data/parameters.xlsx"
lock = true
```

The key goes on an asset of any kind, and `true` is the one value it takes. On a dataframe or a
model it changes nothing. There is no setting for a whole kind: fixed defaults and one key are one
thing to learn.

An asset that is not in the lockfile is still read from the snapshot the lockfile names, by its
commit and time, when a store has that snapshot. So a team that shares a store reads the same
chart as before. Without it, the asset comes from your own build, with nothing checked: the newest
snapshot of that pipeline at that commit that your store has. With no snapshot at that commit, the
read stops and says which commit to build. (Since step 5, where the dependency also has pins: from
the build of yours that stands in for them, and from none where no build of yours meets them. See
"The check, cheapest first".)

Every lockfile is written again once. The class report's goes from 34 asset records to 17.

What was left open here, and how it is built. *Proposed by Claude, 2026-11-16:*

- **Notes** go with charts and notebooks. The decision named three kinds, and a note is a page of
  prose, as a notebook is a page of output: nothing reads its bytes to compute with.
- **`chartbook/lock/v2` begins with this step**, and the dataframe's fields below are added to it
  by step 4, so a lockfile is written again once and not twice.
- **An old lockfile still works, and is not an error.** It is read as the new form would have
  written it: its records of charts, notebooks, notes and files are no pins. `pin --check`
  passes on it and says so, and the first command that writes the lockfile (`pin`, `update`,
  `run`, a first read that pins) writes it again in the new form and says so, once. The pin does
  not move. This is what lets a student's check pass on the class report's lockfile as it is,
  before the report is pinned again (step 8).
- **Writing it again never takes away a read.** An old record of a chart is let go wherever a
  snapshot in the store holds the chart to read it from (the one the lockfile names, or a build
  of yours of that commit), and wherever the store does not have the record's bytes, there being
  nothing to keep. That is every team with a shared store and every student, so the file comes
  out the same on each of their machines. Where the store has the bytes and no such snapshot (a
  pin made before pins named snapshots; a store whose record of the snapshot is gone), the
  record is all that is left to read the chart by: it stays in the lockfile, a pin as it was,
  the check counts it, and `store gc` keeps its bytes. `chartbook update` lets it go, since the
  snapshot it moves to names what it holds. Such a record has no `lock = true`, and is a pin
  only where the store has its bytes: on another machine, with the same lockfile and a build of
  its own, the chart is read from that build and the check passes over the record. (As first
  built, the record was dropped whatever the store had; a review found that the first
  `chartbook run` after upgrading could then make a chart unreadable, and `store gc` remove the
  only copy.)
- **A dependency none of whose assets is in the lockfile** (one that makes only charts) is pinned
  by its entry, which names its snapshot by commit and time. `pin` does not move it, `store gc`
  keeps that snapshot, and the check passes when the store has a snapshot to read from, and says
  why not when it has none.
- **Where a chart is read from.** From the snapshot the lockfile names, and from no other,
  where the store has it: a snapshot is taken whole, whatever its date, and one that did not
  build the chart says so (a later build of that commit is another snapshot, which `chartbook
  update` moves to). Where the store does not have it, from "your own build": the snapshots of
  the pipeline the pin came from, by its own ID, and never another pipeline's of the same
  commit; at the commit the lockfile names; made by its owner's `chartbook snapshot`; not dated
  after now; the newest of them that holds the chart. The check, `chartbook check`, a read and
  what a lockfile keeps when it is written again all ask this one question, and `store gc` keeps
  every such build for as long as a lockfile names a snapshot of that commit that the store
  does not have. A lockfile from before 0.3.0 does not say which pipeline its pins came from:
  for a dependency named by its folder it is the pipeline that folder holds.
- **A dependency pinned from its repository** (`git`) **is pinned whole, as it was before:**
  every asset of it is in the lockfile, charts and notebooks too, and `lock = true` changes
  nothing for it. Its bytes are its commit's, the same for everyone, so a pin of them is not
  what failed for the class; it has no snapshot to read a chart from; and CI reads it from the
  store with no copy of the repository. (Twice built otherwise and twice taken back after a
  review: copied into the store by each pin, which failed in a store one may only read; then
  read from ChartBook's own clone, which a machine that never fetched does not have.)
- **What `pin` and `update` say of what is not in the lockfile:** how many, by kind; one that is
  not built, as for any asset; one its owner no longer declares, on an update.

What you see, as built. Each block is from a run against a copy of the class report's lockfile
and of its six upstreams' snapshots, in a scratch store (the first on 2026-11-16, the rest again
on 2026-11-17); long lines are wrapped here. A first pin:

```text
$ chartbook pin
ftsfr/corp_bond_returns: 2 pinned. Its 2 charts and 1 notebook are not pinned: each build draws them anew
  From its snapshot at 2b69735, made 2026-11-04 05:51 UTC, which says it was made in https://github.com/ftsfr/corp_bond_returns.
ftsfr/fed_yield_curve: 1 pinned. Its 1 chart and 2 notebooks are not pinned: each build draws them anew
  From its snapshot at 5bb7217, made 2026-11-04 05:46 UTC, which says it was made in https://github.com/ftsfr/fed_yield_curve.
(four more)
Wrote chartbook.lock.
```

The class report's lockfile as it is committed today, with a store that has the pinned dataframes:

```text
$ chartbook pin --check
chartbook.lock is in an earlier form, which pinned every asset: its 10 charts and 7 notebooks are
not checked, since no rebuild gives their bytes again. `chartbook pin` writes it again in the new form.
17 pin(s) of 6 dependencies, all in the store. Nothing written.

$ chartbook pin
ftsfr/corp_bond_returns: 2 already pinned
ftsfr/fed_yield_curve: 1 already pinned
(four more)
chartbook.lock was in an earlier form, which pinned every asset. It is written again without its
10 charts and 7 notebooks: they are not pinned, and are read from the snapshot the lockfile
names, or from your own build of that commit where the store does not have that snapshot.
Wrote chartbook.lock.
```

The lockfile then holds 17 records, all dataframes; no pin has moved; a second `chartbook pin`
says `chartbook.lock is unchanged`; and a chart is read from the snapshot the lockfile names. A
read of a chart when the store has no snapshot of that commit:

```text
$ chartbook path ftsfr/fed_yield_curve:chart/yield_curve_replication
Error: 'ftsfr/fed_yield_curve:chart/yield_curve_replication' is not in chartbook.lock: a chart is
drawn anew by every build. It is read from a snapshot of ftsfr/fed_yield_curve at 5bb7217, the
commit the lockfile names, and the store at ~/store has none. Where a store is shared, wait for
its sync. Otherwise build that commit yourself: in a clone of
https://github.com/ftsfr/fed_yield_curve, at 5bb7217, `chartbook run --snapshot`.
```

What this step does not end: a student's dataframe that came out in other bytes. In the same run,
a store holding the 05:38 build of `ftsfr/fed_yield_curve` at 5bb7217 and not the 05:46 one the
lockfile names read that pipeline's chart from the 05:38 build, and failed the check on
`ftsfr_treas_yield_curve_zero_coupon`, its one dataframe. That is what the rows hash and the check
below are for (steps 3 to 5).

## A dataframe's record

```json
{
  "id": "ftsfr/fed_yield_curve:ftsfr_treas_yield_curve_zero_coupon",
  "content_hash": "sha256:4c04…",
  "date_col": "ds",
  "as_of": "2026-10-30",
  "rows": {
    "1961-06-14/1961-12-29": "sha256:7d02…",
    "1962-01-02/1962-12-31": "sha256:3944…",
    "2026-01-02/2026-10-30": "sha256:a31a…"
  }
}
```

- `content_hash` is the file's bytes, as today.
- `date_col` is the column the dataframe's entry already declares.
- `as_of` is the last timestamp in the table when it was pinned. It is the data's own last date,
  never the time on the clock when the snapshot was made: a table pinned on Wednesday morning may
  end on Monday, and Tuesday's row, arriving later, is a newer row.
- `rows` has one line for each **period**: the first and the last timestamp seen in it, both
  included, and a hash of the rows between them. The last period ends at `as_of`.

*Decided 2026-11-16: a period is written by the timestamps seen in it, and is not a half-open span
of the calendar.* The lockfile then holds no date that has not happened, and whoever checks only
compares timestamps, with no calendar to work out. What follows from it: a later pull can hold a
row that falls between two periods, a day the pin did not have. That row is in no period, and the
check reports it as a row the pin did not have.

*Decided 2026-11-15: the list is in the lockfile, and the lockfile says its own periods.* Whoever
pins chooses them; whoever checks reads them from the lockfile and hashes their own rows in those
same periods. So the rule that chooses periods can change in any later version, and an old
lockfile still checks. Only the hash of the rows in a period has to stay as it is.

A dataframe with no `date_col` has one hash over all its rows, and no `as_of`: it is met by the
same file, or by the same rows, all of them. Rows whose date is empty are hashed together as a
period of their own. *(Proposed.)*

The list answers the worry that a lockfile would gather hashes without end. It has one line for
each period of data, not for each time a snapshot was made, and what a pin was before is in git.

This would be `chartbook/lock/v2`. A snapshot's record gains the same fields, since a pin copies
them from the snapshot it is made from. *(Proposed.)*

*Built (step 4).* `chartbook snapshot` records the fields for every dataframe it holds, a table or
query written out from a DuckDB file among them, and `chartbook pin` and `update` copy them. As
built, and *proposed by Claude, 2026-11-16,* where the page had not said:

- **How a timestamp is written:** in UTC; a date alone at midnight (`2026-10-30`), else with its
  time (`2026-10-30T16:00:00`, and with a fraction of six or nine digits where it has one).
- **The two periods with no dates in their name:** `"none"` is the rows whose date is empty, and
  a dataframe with no `date_col` has the one line `"all"`.
- **`row_count`** is recorded beside `rows`, so that `update` and `snapshot` can say "8 new rows"
  from two records without reading a table (step 7).
- **Text that is a date.** A date column that is text (a CSV's) dates its rows where a value is
  written as ISO 8601, with a time or none, with an offset or none, and a value written any
  other way is a row with no date. The page said "as the index already parses it"; the index
  lets polars guess the form from a column's first values, and a guess can differ from one batch
  of rows to the next. The column's own text is what is hashed, whatever it says.
- **A `date_col` that holds numbers** dates nothing: the dataframe is hashed as one with no
  `date_col`.
- **A dataframe whose rows are not hashed** says why, in `not_hashed`, in place of `rows`: a
  column of lists or structs, a single day (or a table with no `date_col`) over 128 MB, more than
  256 columns, and the rest of "Not doing, and later". A pin of it is met by the same file only,
  and `chartbook snapshot` says so. `date_col` stands beside it where the rows would be dated by
  one. A file that cannot be read as a table at all has none of these fields.
- **The same bytes are hashed once.** A snapshot takes what an earlier snapshot of the same
  bytes said of their rows, or why it had none, where they were read the same way and dated by
  the same column: the one that dates the rows, which is the entry's `date_col` where the table
  has it and it holds dates. So an entry that names its dates since is hashed again, and one that
  names a column of numbers is not hashed again at every snapshot. And a snapshot from before
  rows were hashed does not stand in the way: the same commit and the same bytes make a new one,
  once, to say its rows. So the class's upstreams get their rows by running `chartbook snapshot`
  again at the commits they are at (step 8).
- **A snapshot is never stopped by the rows.** It is of the bytes. Where the rows could not be
  hashed for no fault of the table's, the record says nothing of them, the command says `rows
  not hashed this time`, and the next snapshot of the same bytes hashes them. That is what the
  system says of the machine and nothing else: no room for the scratch files, a file that could
  not be read just now, no memory. Anything else is the same at every try, so it is why the
  table has no rows hash, and is recorded as that. What is recorded names no folder of the
  machine that made it. *(Proposed by Claude, 2026-11-17, after a review found four ways a
  snapshot that used to be made was stopped, and a second that a failed read was recorded for
  good.)*
- **Beside a record, a period that holds more than is held at a time is not compared.** No
  record of this version has such a period, but one of a later version may; so the rows are not
  said to differ, and the check says it could not compare them.

## The rows hash

A hash of a table's rows, and not of its file. *Proposed, from the prototype; decided as proposed
2026-11-16. Built (step 3), `chartbook.rowhash`; the form is written out, byte by byte, in
{doc}`index-schema`, "The rows hash".*

- Every column is put in one type for its kind: whole numbers as 64-bit, numbers with a fraction
  as 64-bit floats, timestamps as microseconds in UTC, categories as text. `-0.0` is `0.0`, and
  there is one NaN.
- The rows are sorted on every column, the date first. The columns are taken in name order.
- The values are fed to SHA-256 as plain little-endian numbers and UTF-8 text with its lengths,
  with a bit for each empty value.

So the hash does not see the parquet writer, the compression, how the rows or columns are ordered,
or whether the file is one file, a folder or a glob. It does see every value of every column.

The same rows of CRSP's daily file, written six ways (polars; pyarrow with snappy and small row
groups; pandas 3.1; the rows shuffled; dates in microseconds; the columns reordered), gave six
byte hashes and one rows hash. One return changed by 0.000000001 changed it. One file, a
Hive-partitioned folder and a glob of files, read by ChartBook's own reader, gave one rows hash.

The form has to be ChartBook's own. polars has `hash_rows`, and its documentation says the result
is not stable from one version of polars to the next; the author's machine and the checker's
will not have the same version. Like the content hash, it is computed in one place
(`chartbook.rowhash`, beside `chartbook.hashing`), and its rules are part of the index
specification. As built, one table gives one hash on polars 1.33.1, the oldest ChartBook takes,
and on 2.1.0; a test holds that hash to a value written down, and writes the form a second time
in plain Python to hold the module to the specification.

What was not settled, and how it is built. *Proposed by Claude, 2026-11-16:*

- **A timestamp finer than a microsecond** is its whole microseconds, and the nanoseconds left
  over where a column has any. So nanosecond timestamps with nothing finer in them (what pandas
  writes for a date) give the hash microsecond ones give, and no value goes unseen. The prototype
  cut the nanoseconds off.
- **A date** is the timestamp of its midnight, so a column polars writes as dates and pandas as
  timestamps is one column. **A time in a zone** is its instant in UTC.
- **A decimal type** is its value as text, written one way (`1.5` for `1.50`), and is not a
  float: DuckDB gives decimals, and a float would lose their last digits.
- **A list or a struct in a column:** no rows hash yet. A dataframe with one is pinned by its
  bytes alone, as today (`chartbook snapshot` is to say so, from step 4). Hashing what is inside
  one needs an order for values that have none in polars, and is left for later.
- **A column with no value in it** has no kind, whatever type its writer gave it: pandas writes
  such a column as "null" and polars as the type it was.
- **A whole number past 64 signed bits** (an unsigned column that uses its last bit) is a kind of
  its own, so that it is never taken for the negative number with the same bytes.
- **The date column is part of the form,** as the page had it ("the date first"): sorted on
  another column first, the rows may be fed in another order. The record says which it was
  (`date_col`).
- **An empty value is not NaN.** pandas writes a float's NaN as an empty value, and a whole
  number column with an empty value in it as floats. Those files hold other values than a file
  polars wrote of the same frame, and hash otherwise: "whatever wrote them" is of the same
  values. It matters only where the code that writes a table changes from one library to the
  other; two people running the same code write the same values. Whether NaN and empty should be
  one in a float column is the maintainer's to say.
- **A column named like a pattern.** polars reads a name that begins `^` and ends `$` as a
  pattern, so the columns are taken by their place and never by their name. (A review found
  such a column passed over, and two tables with one hash.)
- **The hash is written `sha256:…`,** as the page had it. The form's name is the first thing
  hashed (`chartbook/rows/v1`), and a change to the form takes a new name there and a new prefix,
  as the rule for any hash has it ({doc}`overview`, "Working in the code").

A date column that is text (a CSV's) dates its rows where it is written as a date; how is in "A
dataframe's record", above.

## Choosing the periods

Whole years. A year whose rows are too many is split into months, and such a month into days.
*Decided 2026-11-15: years and not months, since twelve times the lines buys nothing for most
tables; and no setting for it in `chartbook.toml`.*

"Too many" is a size in memory, and it is fixed in ChartBook. *Decided 2026-11-16: it is set for a
machine with 8 GB.* It cannot be taken from the machine that pins: the author may pin on 64 GB,
and a student then hashes those same periods on 8.

*Built (step 4). Proposed by Claude, 2026-11-16: a period is at most 128 MB of rows.* That is
what kept the four tables below under 2 GB with room to spare (the prototype's 200 MB did not,
with its reader). One day is never split: a day over 128 MB has no rows hash, and neither has a
table with no `date_col` over 128 MB, nor one whose rows with no date are. (A piece that cannot
be split was first allowed twice a period, 256 MB. A second review made one of short text, and
one of decimals, that peaked at 2.0 and 2.5 GB: a piece is sorted whole, whatever it is, so
there is one size.) Only the days that have rows are in a period's name, so a year that begins
on June 14 is `1961-06-14/1961-12-29`.

*What the size is a size of. Proposed by Claude, 2026-11-17, after two reviews:* **eight bytes
for each value; sixteen and its own bytes for a value of text; sixteen for a decimal; and eight
for an empty value, whatever its column.** That is what a value takes in the one form the rows
are hashed in. It is counted from the rows, every one of them, and never from the file they came
in. So the same rows give the same periods, whatever wrote them: a whole number counts eight
bytes whether its file held it in one or in eight, a date whether it was a date or a time at
midnight, a column with nothing in it the same whatever type its writer gave it, and a year is
split, or refused, by what is in it and not by where a reader happened to look. (As first built,
the size was reckoned from a few rows of the file as Arrow held them. The first review showed
the same table giving 2 lines written by polars and 24 written by pandas, another split one way
sorted and another way shuffled, and a moved pin losing every line it had when the new rows were
longer.) It is a rule for choosing periods, and no part of a hash: `chartbook/rows/v1` is as it
was.

When a pin moves, the periods before the last are as they were, with the same lines unless a value
in them changed. The last one grows, or new ones follow it. On CRSP's daily file, pinned through
2019-06-28 and then moved to the end of 2024, 20 of the 21 lines were unchanged, one changed (2019,
which had gained rows) and 5 were added (run again as built, 2026-11-17). So the diff of a moved
pin shows which periods changed, and a revision of 1998 is a changed line that a reviewer sees.
The one exception is a year that grows past the size: it is then its months, and its one line
becomes twelve.

## The check, cheapest first

1. **The same file?** The file's byte hash is compared. The store knows it already, so nothing is
   read. A team with a shared store stops here every time.
2. **The same rows, up to `as_of`?** Among your snapshots of the same pipeline at the same commit,
   the rows of each period are hashed and compared. Rows after `as_of` are left out.
3. **Otherwise it differs,** and the message names the periods that do.

A snapshot of yours that meets a pin in the second way **stands in** for it. The result is
remembered against the pin and that snapshot's file, so a read does not hash the table again.

*As built (step 5). Where the page had left it open, proposed by Claude, 2026-11-17:*

- **Only where the store does not have the snapshot the lockfile names.** Where it has it, that
  snapshot is the pin, and a file of it the store lacks is lost, or not synced yet: the check says
  so, as it did before, and no other build is read in its place. In a shared store another build of
  that commit is anyone's, and while a sync is running the right thing is to wait for the pinned
  file. A pinned file the store has in part is on its way, in any store. (Found by review: a
  half-synced file passed the check on another build, and the read then stopped.)
- **Which snapshots are looked at.** Those of the pipeline the pin came from, by its own ID, at the
  commit the pin names; made by its owner's `chartbook snapshot`; not dated after now. The same rule
  as for a chart that is not in the lockfile, by one function. A dependency pinned from its
  repository (`git`) has none: its bytes are its commit's, the same for everyone, and `chartbook
  pin` puts them back.
- **A build stands in for a dependency whole.** It has to meet every pin of that dependency: each
  one by the same file or, for a dataframe, by the same rows. So everything read of one dependency
  comes from one build of it (or from the store, for a file that came out in the same bytes): a
  table is not read from a build that fails another pin, and a chart that is not in the lockfile is
  read from the build that stands in, not from a newer one. Where the dependency has pins and no
  build of yours meets them, nothing of it is read, a chart no more than a table: a chart drawn
  from rows that are not the pinned ones is not the pinned chart. (A dependency with no pin at all,
  one that makes only charts, has none to fail, and is read from your newest build.) The newest
  build that meets them all is the one; where none does, the newest is the one reported.
- **A model, and anything else locked, is met by the same file only.** So is a dataframe whose pin
  records no rows: one made before rows were hashed, one whose rows are not hashed, or a table that
  had no rows when it was pinned (it has no period, so nothing would tell its columns). The message
  says which. The class's lockfile is of the first kind until the report is pinned again (step 8).
- **A version pinned by its label** (`model/ar1@champion`) is met by the same file only, and was
  made at an earlier commit, most likely, so no build of the pinned commit gives it. The message
  says where it can come from (the store of whoever made it, or a build of that commit that gives
  the same file), and does not offer `chartbook update`, which would not find it in your build.
- **Cheapest first, inside the second step too.** The two records are compared before any row is
  read: a period both name by the same timestamps, with the same hash, is the same rows. Where
  that is every period of the pin, and your record has nothing else up to the pin's last date,
  nothing is read at all. Otherwise only the periods still to be told are read and hashed, which
  for a build with newer rows is the last one.
- **Where the result is remembered:** in this process, and in this machine's cache folder
  (`rows/met/`), under the pin's rows, its date column and last date, the hash of your file, and
  this ChartBook's version. Any command writes it, `pin --check` among them, which writes nothing
  in the project or the store. A file there is believed only if it is whole and repeats the question
  it answers; anything else is compared again. Without a cache folder a table is hashed once a
  process.
- **Nothing in the lockfile says a build stood in.** `chartbook pin` leaves it byte for byte, and
  says `1 met by your own build`. `store gc` keeps the build while the lockfile names a snapshot
  of that commit the store does not have.
- **A snapshot records it.** A snapshot of the pipeline that read the build is not refused, and
  the dependency's entry among its `inputs` gains `stood_in`, when that build was made. So
  `chartbook lineage` goes on up from that build, one level up as well (a pipeline that depends on
  the report). It is the build that stood in when the snapshot was made: under `chartbook run
  --snapshot`, the one the build read. A newer build of the upstream makes no new snapshot of the
  reader, whose bytes and pins are the same: the one recorded stays. What a snapshot records is
  taken at its word, as its pins are; it is not checked again. `chartbook pin --check`, `chartbook
  lineage --check`, `chartbook snapshot` and `chartbook check` ask one question, by one function.
- **What the lockfile says of a table's rows is checked where the pinned snapshot is.** The
  author's store has it, and `chartbook lineage --check` and `chartbook snapshot` there compare the
  lockfile's record of rows with that snapshot's own. A lockfile whose rows were changed by hand,
  or merged from two, would otherwise pass for its author and fail for everyone who builds the
  other pipeline.
- **Where there is no build of yours,** the check says it once for the dependency, with how to
  build it at the pinned commit (scenario 2 above), and `chartbook pin` and a read name the same
  way on. `chartbook update` is offered, by the check and by `chartbook pin`, only where it would
  find a snapshot to move to, looked for as `update` looks. Where a pinned file is in the store in
  part, the line says that no build is read in its place while it is, and not that you have none. For a dependency named by its ID whose repository is not named as the pipeline is, it
  says which folder of the repository: "in a clone of <repository>, in the folder of acme/rates".

## What each command does

| Command | The same file | The same rows up to `as_of` | Earlier rows differ |
|---|---|---|---|
| `chartbook pin`, `pin --check` | Passes | Passes, and says so | Exits 1 |
| `chartbook run`, a build, `data.load` | Reads it | Reads your build, and says so | Stops with the message |
| `chartbook update` | Nothing to move | Moves the pin: "8 new rows" | Moves the pin: "earlier rows changed" |
| `chartbook snapshot` | "Same as the last one" | "8 new rows" | "Earlier rows changed" |

*Decided 2026-11-15.* The check and a read stop, each with a plain message. `update` and `snapshot`
only report, because there the change is what was asked for; they compare with the pin before, and
with the snapshot before. `chartbook lineage` says which pins a build of yours stands in for.
*(Proposed; decided as proposed 2026-11-16, and built in step 5.)*

## Reads

**A read through a pin gives the pinned rows, on every machine. Only `chartbook update` brings
later rows.** *Decided 2026-11-15.* The other way, handing over every row of a build that stands
in, would give two students with one lockfile two different tables, which is a pin that moves by
itself.

| Read | The pinned file is in a store | Your build stands in |
|---|---|---|
| `data.load`, `data.sql` | Reads it | Reads it, without the rows after `as_of` |
| `data.path`, `data.files` | The file | The file as it is, newer rows and all; says so once |
| `data.as_of(ref)` | The pin's `as_of` | The same |

- `data.as_of` is new: the pin's last timestamp, or `None` for a dataframe with none. A reader of
  your own, given a path, filters with it. *Decided 2026-11-15, over a copy of the file cut at the
  date and written once: no hidden file, no second copy on disk.*

*Built (step 6). From a run on 2026-11-17 of the small made-up upstream of "What you see", on the
student's machine, whose build has 24 rows after the pin's last date:*

```text
$ python reads.py
data.load: 800 rows, through 2026-10-30 00:00:00
data.sql:  (800, datetime.datetime(2026, 10, 30, 0, 0))
data.as_of: datetime.datetime(2026, 10, 30, 0, 0)
data.path: 824 rows in the file; 800 up to data.as_of
ftsfr/fed_yield_curve:treasury_yields: this file is your own build's, and has 24 rows after
2026-10-30, the last date chartbook.lock pins. data.load() and data.sql() leave them out; a reader
of your own keeps the rows up to data.as_of('ftsfr/fed_yield_curve:treasury_yields').
```

*Where the page had left it open, proposed by Claude, 2026-11-17:*

- **Which rows are left out** is told as the rows hash tells a row's date, so what a read gives
  is exactly what the check compared: the rows up to `as_of`, and the rows with no date. For a
  pin with no dated row, the rows with no date alone. A dataframe with no `date_col` is met by
  all its rows, and is read whole.
- **What `data.as_of` returns:** a `datetime.date` where the column holds dates, and a
  `datetime.datetime` where it holds times, in the column's own time zone where it has one
  (polars compares a time only with one of the same zone) and with no zone where it has none.
  The type is that of the file that is read, so `frame[frame["ds"] <= data.as_of(ref)]` works on
  the file `data.path` gives, whoever wrote it. A timestamp finer than a microsecond comes back
  as the next microsecond, so that no pinned row is after it. It is `None` for a dataframe with
  no `date_col` or no dated row, one pinned before pins recorded rows, one whose rows are not
  hashed, and a dataframe of your own pipeline.
- **That comparison is the reader's own, and `data.load` is exact where it is not.** It drops a
  row with no date, which the pin holds; a column of text has to be read as dates before it
  compares with one; and in a column of nanoseconds, rows within the microsecond after the pin's
  last one come in too. The docstring says so. (Found by review.)
- **`data.sql` and `data.ref`** read a parquet file through `(select * from read_parquet(…)
  where "ds" is null or "ds" <= DATE '2026-10-30')`, so DuckDB still reads only the columns and
  row groups a query needs. Where SQL has no sure way to say it, DuckDB is handed the frame
  `data.load` gives, and `data.ref` says there is no text for it: a date column of text (a row
  whose text is no date has no date, and is not null), one a folder's name makes, one beside
  another whose name differs only by case, times written as INT96, a time with a zone to the
  nanosecond, a CSV.
- **`format="pandas"`** keeps the frame as pandas reads it, types and index: the rows are told
  from the date column wherever pandas put it, a column, the index, or a level of it, by its name
  or, with no name, by its place (`__index_level_0__`). Where it is nowhere pandas put it, the
  rows are cut by polars and handed over as pandas: never the whole frame.
- **What `data.path`, `data.files`, `assets.path` and `chartbook path` say,** once a process for
  each dataframe, on stderr, and only when the build has rows after the pin's last date: the line
  above. `data.load` says nothing of it. For a pin with no dated row, which has no last date, it
  ends "a reader of your own keeps the rows with no ds".
- **A read of the pinned file itself is untouched,** and `data.as_of` answers there too, from
  the pin.
- A read in a notebook and a read in a batch run do the same here. What was decided before
  ({doc}`reading-other-pipelines`, "How strict, where") is about a read with no pin, and stands.
- The lockfile becomes the committed cutoff for what a pipeline reads from others. An upstream
  needs no cutoff date of its own for a rebuild to be checked.

## The pandas index column

pandas writes a frame's index into a parquet file, and one with no name becomes the column
`__index_level_0__`. The pinned yield curve table has one: row positions left from an earlier
step, 0 to 511,739 for 382,802 rows. They shift when a pull has more dates. In a simulation of an
earlier pull of that table, 16,290 of 382,232 rows kept their index, so the rows did not match up
to the pin's date; without the column they did.

In that table the column is an accident. It cannot be left out by its name, though: a frame
indexed by date, with no name on the index, is written to the same column, and there it holds the
dates.

*Decided 2026-11-16:*

1. The rows hash counts every column. There is no exception to explain.
2. `chartbook check` and `chartbook snapshot` warn the author of a dataframe whose file has such a
   column, with the two ways out: `to_parquet(index=False)` drops it, and `reset_index()` keeps it
   as a column with a name.
3. When a pin of a table that has one is not met, the message says the column may be the whole
   difference.
4. The pipelines the class reads, and the project template, write `index=False`, and the report is
   pinned again once.

## Folders of files

A dataframe can be a folder of files, partitioned Hive-style, often by date. *Proposed; decided as
proposed 2026-11-16:* its rows are hashed by period, as any dataframe's are, and never file by
file, with periods following date partitions.

*The rule, as built (step 4). Proposed by Claude, 2026-11-16:* there is one rule for periods,
whatever the layout: whole years, and months or days of one by size. A folder's files are read
one after another, a batch at a time, and each row goes to the period of its date, with the
columns ChartBook's reader makes of `key=value` folders put on. So a folder partitioned by year,
by month or by day has periods that are whole partitions, or whole partitions together (a year
of twelve monthly folders is one line, where a line for each would be twelve times the lockfile
for nothing); a partition is never cut unless it is over the size; and a folder split another
way, or one file, gives the same lines. A test lays the same rows out six ways (one file, many
row groups, a folder pandas partitioned, a folder polars partitioned, a glob, a plain folder)
and holds them to one record, and to the record the whole table read at once gives; another
holds a table as polars wrote it, as pandas did with wider types, and with its rows shuffled into
small row groups, to one record at six sizes of period, two of them a byte to either side of a
year's size.

What is hashed is what ChartBook's reader gives, asked of the reader for each file: a
`key=value` folder above a single file is a column, as the reader makes it one; a key that is
also a column of the file has the folder's value; and a file the store keeps once for two
partitions of the same bytes is read once for each, with each one's key. (Each of the three gave
a record that was not the reader's rows, or none, as first built.)

**Not built, and later:** opening only the files that hold a period's dates, and passing over a
file whose bytes are the pinned ones. Today every file is read once when a folder is hashed.
Both are ways to do less work, and change no hash. What "A build split another way still
matches" needs is that the split adds no column: a folder's `key=value` names are columns, so
rows split by `year=` have a `year` column that the same rows in one file do not, unless the file
has it too.

- **Files are not stable.** pandas names each file of a partitioned write with a new random id:
  the same rows written twice gave `year=2022/e67d58e5…-0.parquet` and
  `year=2022/3d82e46c…-0.parquet`. By period, the folders pandas and polars wrote gave one hash.
- **The periods can follow the partitions.** Where a folder is partitioned by date, one period is
  taken for each partition, and hashing a period then opens only that partition's files. This rule
  is not prototyped.
- **The byte check is by file already.** A snapshot of a folder records each file's byte hash.
  With that list in the lockfile, a check need not read a row when every pinned file is in your
  build with the same bytes: only the files that are new are opened. For data that grows by a file
  a day that is nearly free.
- **A build split another way still matches,** since the lockfile records timestamps, not file
  names.

## What it costs

*As built (step 4), measured 2026-11-17 by the test under a memory limit, on the machine the note
at the top names:* each table hashed by period and then checked against its own record, in one
process that stops itself the moment its memory passes 2 GB.

| Table | Rows by columns | Periods | Hashed in | Checked in | Peak memory |
|---|---|---|---|---|---|
| The class's yield curve | 383 thousand by 4 | 66 | 0.5 s | 0.1 s | 0.21 GB |
| CRSP daily | 27.8 million by 8 | 26 | 7.4 s | 6.9 s | 1.03 GB |
| GKX characteristics | 2.6 million by 99 | 42 | 3.2 s | 2.9 s | 1.36 GB |
| RavenPack, 19 text columns | 28.1 million by 27 | 234 | 27.3 s | 26.9 s | 1.26 GB |

Hashing the bytes of the same files took under a second each. The time for the rows is paid once
for each snapshot of new bytes, and in a check only when the files differ, and then only for the
periods the two records do not already show to be the same: CRSP's later file against its
earlier pin was checked in 1.4 s, the last period being all that was read.

**The target is met on these four tables: a peak under 2 GB,** so that a machine with 8 GB is
safe. The test is `tests/test_rows_memory.py`. The four tables are licensed data on the
maintainer's disk, so they run when `CHARTBOOK_ROWS_TABLES` names them. **It has not been run on
a machine with 8 GB,** and the peak is the process's own count on macOS, which other systems
count a little otherwise.

The same test makes tables of its own, which run everywhere but Windows. They are the shapes
that took the most: the first two from the prototype, and the rest built by a second review to
break the limit, which six of them did before the reader was changed (the second line had
peaked at 7.6 GB, and three more over 2 GB).

| A table made by the test | As a file | Periods | Peak memory |
|---|---|---|---|
| 99 columns of floats, 400 thousand rows, one row group | 300 MB | 4 | 1.09 GB |
| 12 columns of text, 1.5 million rows, one row group | 350 MB | 48 | 0.50 GB |
| One text column of 20 KB, 50 texts over 300 thousand rows (6 GB of rows) | 2 MB | 750 | 0.49 GB |
| 60 text columns of 200 characters, 20 texts each, 300 thousand rows | 11 MB | 36 | 0.59 GB |
| One day at the 128 MB limit: 200 columns of one-character text | | 1 | 0.80 GB |
| One day at the limit: 100 columns of decimals | | 1 | 0.82 GB |
| One day at the limit: 254 columns of floats | | 1 | 1.16 GB |
| A document of 2 MB a row, forty a day | | 10 | 0.38 GB |
| A CSV at its limit, 32 MB of text | 32 MB | 4 | 0.40 GB |
| A CSV of single digits, 200 columns, at its limit | 32 MB | 1 | 1.03 GB |

What the memory is, as measured:

- **The period is what is held, never the table.** A file is read a few thousand rows at a time
  by pyarrow, which holds a batch and not a row group. Each row is put in a scratch file for its
  year, in ChartBook's cache folder, compressed; a year over the size is put again by month, and
  such a month by day (a table over a gigabyte on disk is put by month from the first, to be
  written once); and each period is then read back, sorted and hashed alone. On the text table
  that took the split from 3.1 GB to 0.6 GB. No scratch file is held open, so a table of thirty
  years of months is not stopped by the 256 files a process may have open on a Mac; a scratch
  folder a killed process left is removed a day later; and where the cache cannot be written
  the system's temporary folder is used.
- **A batch is measured from its rows, never from the file.** A file that holds its text once,
  in a dictionary, says a few bytes a row for rows of kilobytes: reckoned from the file, a batch
  of 65,536 such rows was 780 MB. A row group is begun with a few rows, and begun again from
  where it was with more, or fewer, as its rows turn out, so a batch is about 8 MB, down to one
  row.
- **Sorting a period takes five to eight times its size,** more for many columns. A single day
  at the limit peaked at 0.8 GB of short text and 1.2 GB of floats in 254 columns.
- **Rows with no date are one piece too,** and held to the same 128 MB: a file of text dates
  that are not ISO dates has every row there, and 26 million of them took 4.6 GB before they
  were.
- **Only parquet is read a little at a time.** A CSV or JSON lines table is read whole, once,
  and a number that is two bytes of text is eight in memory. So one of more than 32 MB of text
  has no rows hash; a gzipped file is measured by its text, read through and not held. An Arrow
  IPC file has none at all: what it takes in memory cannot be told from its file, and 19 MB of
  one, compressed, was 4.2 GB. *(Proposed by Claude.)*
- **A page or two of every column is held while a file is read,** about 2.7 MB a column: 99
  columns are 0.4 GB before a row is hashed, 400 columns peaked at 1.5 GB, and 1000 at 2.9 GB.
  So a table of more than 256 columns has no rows hash. *(Proposed by Claude.)* Reading such a
  table some columns at a time would lift that, and is not built.
- **Arrow's own allocator keeps what it frees,** and the process's memory then stands at the
  most it ever held. While a table is hashed, Arrow takes its memory from the system instead,
  which was 0.4 GB less on the text table.

What was learned about reading, from the prototype:

- Hashing a whole table at once took 18 to 24 GB on the text table.
- polars' streaming engine does not bound memory here: 8.6 GB reading in batches, and 12 GB
  writing the table out by period.
- Reading the file one row group at a time, in slices, and appending each slice's rows to a
  scratch file for its period is what gave the table above.
- A table takes more room in memory than its parquet file says, about twice for text, so the size
  of a period is counted in memory.

## Not doing, and later

- **Bringing back revised data.** It is reported, with the periods named. A shared store is how
  the bytes are kept.
- **A setting for how often to hash,** by month or by year. The lockfile's format would not change
  if one came later; only how periods are chosen.
- **A setting for a whole kind of asset.** `lock = true` on an asset is the only key.
- **A copy of a file cut at the pin's date** for `data.path`. `data.as_of` is given instead.
- **Tick data,** where one day's rows do not fit the size of a period. A day over 128 MB in
  memory has no rows hash, and the dataframe is pinned by its bytes alone.
- **A large table with no `date_col`.** It has one hash, which takes one sort of the whole table
  in memory, so one over 128 MB has no rows hash. The same for the rows of a dated table that
  have no date.
- **A table of more than 256 columns,** for the memory a file's columns take while it is read.
- **A CSV or JSON lines table of more than 32 MB of text,** which is read whole; and **an Arrow
  IPC file** of any size.
- **A date outside the years 1 to 9999,** or past what 64 bits of microseconds hold: a record
  has no way to write it, so the table has no rows hash, and says so.
- **A column of lists or of structs.** A dataframe with one has no rows hash.
- **A dependency pinned from its repository** (`git`). Its dataframes are pinned by their bytes,
  which are the commit's for everyone; a pin's own snapshot records no rows.
- **A table in a warehouse.** A snapshot does not pin one today; nothing here changes that.

## Still open

- ~~The rule for folders of files, above.~~ Built as proposed in "Folders of files".
- ~~The size of a period, and the reader, that keep the peak under 2 GB.~~ 128 MB, counted from
  the rows, and pyarrow a batch at a time: "Choosing the periods" and "What it costs".
- ~~The parts of the rows hash marked not settled.~~ Built as proposed in "The rows hash".
- ~~The exact words each command prints.~~ For the check, `pin`, `run`, a read and `lineage`: as
  built, in "What you see". For `update` and `snapshot`: step 7.
- A run of the memory test on a machine with 8 GB.

Outside this repository: step E of the course's pins walkthrough prints a matching hash for a
rebuild cut at the pinned date. That output is not from a real run (it shows the hash of the
382,802-row pinned file beside "rows 382,232"), and with the index column above the cut cannot
match. The page is to be corrected.

## The order of work

1. This page.
2. The lockfile by kind: dataframes and models; `lock = true`; a read of an asset that is not in
   it, through the snapshot the lockfile names. It ends the failure on charts and notebooks, and
   needs nothing below. **Built.**
3. The rows hash: its form written into the index specification, and tested across writers.
   **Built.**
4. Periods: choosing them within the size, in a snapshot's record and in the lockfile; the test
   under a memory limit. **Built.**
5. The check: a snapshot of yours that stands in, in `pin`, `pin --check` and `run`, with the
   messages. **Built.**
6. Reads: `data.load` and `data.sql` without the rows after `as_of`; `data.as_of`; what
   `data.path` says. **Built.**
7. What `update` and `snapshot` say; the warning for a pandas index in `check` and `snapshot`.
8. The class's upstreams and the template write `index=False`; the report is pinned again.
9. The guide, the reference, the changelog, the skill.
