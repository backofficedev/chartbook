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
store of their own. Scenarios 4 and 5 are as built too (step 7), from the same run.

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
changed and nothing before it, and git keeps what the pin was. *As built (step 7):*

```text
$ chartbook update
ftsfr/fed_yield_curve: 1 moved. Its 1 chart is not pinned: each build draws it anew
  ftsfr/fed_yield_curve:treasury_yields
    sha256:b47d6f2bd9db… -> sha256:48b68a0be6a0…
    24 new rows, through 2026-11-11; earlier rows unchanged
  From its snapshot at f321fcb, made 2026-11-17 09:41 UTC.
Wrote chartbook.lock.
```

And after the source had revised one value of 2025-12-14, the third line was `earlier rows
changed: the rows of 2025-09-26 to 2025-12-31 differ; 2 new rows, through 2026-11-12`.

**5. An agent refactors an upstream.** `chartbook snapshot` compares with the snapshot before and
says "earlier rows unchanged, 1 new row". The refactor changed no number, though a new day of data
arrived between the two builds. *As built (step 7):*

```text
$ chartbook snapshot
ftsfr/fed_yield_curve at f321fcb: 2 asset(s) in the store
  Beside the snapshot before it, of f321fcb, made 2026-11-17 09:41 UTC:
    ftsfr/fed_yield_curve:treasury_yields: 24 new rows, through 2026-11-11; earlier rows unchanged
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
```

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

*What `update` and `snapshot` say, as built (step 7). Proposed by Claude, 2026-11-17, where the
page had only the two phrases:*

- **One line for each dataframe whose file changed:** `24 new rows, through 2026-11-11; earlier
  rows unchanged`; `earlier rows changed: the rows of 2025-09-26 to 2025-12-31 differ; 2 new rows,
  through 2026-11-12`; or `the same rows, in other bytes`, where another writer wrote what was
  there. Under the two hashes in `chartbook update`, and under `Beside the snapshot before it, of
  f321fcb, made …` in `chartbook snapshot`.
- **Beside what.** `update`: the pin the lockfile had. `snapshot`: the newest earlier snapshot of
  that pipeline in the store, at whatever commit, which is why the line names its commit: the one
  before may be another branch's, and its rows are then another's. A first snapshot says nothing,
  and "the same as the last one" is what `chartbook snapshot` has always said of the same bytes:
  `No new snapshot: the same bytes and the same pins as the one made …`.
- **A table with no `date_col`** has nothing to tell a new row from a changed one by: `its rows
  changed (2 rows before, 3 now); it has no date column to tell new rows by`. Its two records, of
  one hash each, say that between them, and nothing is read.
- **Where the two were not dated alike,** the line says what is true of that case and no more. A
  table whose entry lost its `date_col` and still has the column: `16 new rows; earlier rows
  unchanged`, with no last date to give. One that lost the column itself: `its rows are no longer
  dated by 'ds', so new rows cannot be told from changed ones (80 rows before, 96 now)`. One that
  gained a `date_col`: `the same rows, in other bytes; now dated by 'ds'`, or `its rows changed
  (80 rows before, 96 now); the earlier record had no date column to tell new rows by`. One that
  had no rows: `it had no rows, and has 80 now`. Rows with no date where there were none: `it has
  2 rows with no date, and the earlier one had none`.
- **Where earlier rows changed and the table has the pandas index column,** the line ends: `It
  has the column pandas makes of an index with no name (__index_level_0__), which may be the whole
  difference`.
- **Nothing is said** where the earlier record has no rows to compare (a pin from before rows
  were hashed, a table whose rows are not hashed), and nothing stops either command: whatever
  goes wrong in telling it, a store that cannot be reached among them, the line is left out and
  the pin moves, or the snapshot is made. (Found by review: `update` stopped where it could not
  fetch a table.)
- **What it costs.** The earlier record's periods are compared as a check compares them: what
  the two records show to be the same is not hashed, so a table that gained rows has its last
  period hashed, once (the file is read through to find those rows: 0.1 s for three million rows
  on a local disk, as the review of this step measured it). The owner's `snapshot` and a reader's
  `update` on the same machine
  share what was found. **A store that is not a folder on this machine is not read for it:** a line
  of output is not worth fetching a table for, so there the line is said only where the two
  records, or what is remembered, already tell it.

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

*Built: 1 (step 3), 3 (step 5) and 2 (step 7). 4 is step 8, which waits for the maintainer.* What
the author is told, by `chartbook snapshot` under the snapshot's line, and by `chartbook check` as
a warning that fails nothing:

```text
  acme/rates:treasury: its file has the column pandas makes of an index with no name
  (__index_level_0__). Where that holds row positions, they shift when a pull has more rows, and
  no rebuild then has the rows a pin of it names. to_parquet(index=False) drops it; reset_index()
  keeps it as a column with a name.
```

A frame indexed by date under a name (`set_index("ds")`) has no such column, and is told nothing.
The column of a level with no name of an index of several (`__index_level_1__`) is told of in the
same words, by its own name. Only a parquet file is looked at, by its first file's columns where
it is several: pandas writes no such column into a CSV. `chartbook check --skip-outputs`, which is
not to look at what a build writes, opens no file for it.

*Not built, and the maintainer's to say:* the warning is repeated at every snapshot and every
check, for an index that really holds dates too, with no way to say "I know". A name on the index
(`rename_axis("ds")`) ends it.

*On the class's own table, as built, 2026-11-17.* Two builds of `ftsfr/fed_yield_curve` at commit
5bb7217 are in the maintainer's store: one of 382,232 rows through 2026-10-02, and a later pull of
382,802 rows. On scratch copies, with the earlier one as the pin and the later one beside it:

| The two files | The later pull holds the pinned rows | Periods that differ | Newer rows |
|---|---|---|---|
| As they are, with `__index_level_0__` | No | 66 of 66 | 570 |
| With that column dropped, as step 8 will write them | Yes | 0 | 570 |

And the message for the first says it: `has the column pandas makes of an index with no name
(__index_level_0__), which may be the whole difference`. So for this table the check cannot pass
until its pipeline writes `index=False` and the report is pinned again, which is step 8.

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

## Upgrading from an earlier ChartBook

*Proposed by Claude, 2026-11-18, and built. The maintainer asked three things once the steps above
were merged: whether the stores there already are still work, how someone on an earlier ChartBook
is told to upgrade, and how upgrading is made easy. The release is 0.6.0: it writes a lockfile that
0.5 cannot read, which is what a new minor number is for before 1.0. And the class's report asks
for `chartbook>=0.5.1,<0.6` in its own `pyproject.toml`: another 0.5 release would reach every
student at their next `uv sync`, mid-homework, and 0.6.0 reaches none of them until step 8 raises
that line.*

```{admonition} The store's layout changes in 0.6.0 after all
:class: note

*Decided 2026-11-19, after this was written and tried:* {doc}`snapshots-and-increments` gives the
store a new layout. So the first row of the table below is true of the two versions as they were
on 2026-11-18, and not of 0.6.0 as it is to be released: 0.6.0 reads a store of 0.5 as it is,
makes no snapshot in one until `chartbook store migrate` has moved it, and 0.5 does not read a
store that has been moved.
```

**A store is shared across versions. A lockfile is not.** Each half was tried on 2026-11-18, with
ChartBook 0.5.1 as PyPI has it and this version, on one scratch store, and the first on copies of
the maintainer's own stores:

| | ChartBook 0.5.1 | This version |
|---|---|---|
| The store's layout | `chartbook/store/v2` | The same. Nothing is migrated |
| A snapshot the other made | Lists it, pins it, reads it, builds a catalog over it | Reads it. It says nothing of rows |
| The lineage of a snapshot the other made | **A gap that is not one**, one level up: see below | Walks it |
| `store gc`, beside the other's lockfiles | From another machine: keeps the snapshot a version 2 lockfile names, by the store's note of it. On the machine that has that lockfile: stops, and removes nothing | Keeps what a version 1 lockfile names, its charts too |
| A lockfile the other wrote | **Cannot read version 2** | Reads version 1, and writes it again once |

So the one thing an upgrade breaks for someone else is a committed lockfile, and what they are told
then is the thing to get right.

**The lineage, which 0.5 gets wrong.** A snapshot records what its pipeline was pinned to, with one
hash over what was pinned of each dependency. Since step 2 that hash is over the dataframes and the
models; 0.5 works it out over every asset. So for a snapshot this version made of a pipeline that
itself pins another which has, beside its dataframes or models, anything a lockfile no longer holds
(a chart, a notebook, a note, a plain file), 0.5's `chartbook lineage` says `its snapshot … does not
hold what was pinned`, one level up, and its `snapshot --deep` refuses. A dependency of dataframes
alone, of charts alone, or whose chart is marked `lock = true`, shows no gap. Its reads, its pins,
`pin --frozen` and a plain `snapshot` are as they were, and this version walks both. Nothing in this
version can mend it: the two cannot both be recorded under the one name 0.5 reads. (Found by review,
with the real 0.5.1, and the cases by a second.)

### What an earlier ChartBook says

ChartBook 0.5, given a version 2 lockfile, says which version it reads and nothing of what to do:

```text
$ chartbook pin
Error: Cannot read chartbook.lock: its schema is 'chartbook/lock/v2', and this version of ChartBook reads 'chartbook/lock/v1'
```

Those words are in every copy of 0.5 and cannot be changed. But every ChartBook since 0.2.0 reads
`[project] requires_chartbook` before anything else in a manifest, and one that does not meet it
says what to install, with the command:

```text
$ chartbook pin
Error: chartbook.toml requires ChartBook >=0.6.0 ([project] requires_chartbook), and this is ChartBook 0.5.1.
Install one that meets it: `pip install -U "chartbook>=0.6.0"`, or `uv add "chartbook>=0.6.0"` in a uv project.
```

**So the manifest's line is raised by the commands that write pins on request.** `chartbook pin`,
`update` and `add`, when they leave a version 2 lockfile under a manifest whose
`requires_chartbook` admits an earlier ChartBook, rewrite that line and say so:

```text
$ chartbook pin
ftsfr/fed_yield_curve: 1 already pinned
chartbook.lock was in an earlier form, which pinned every asset. It is written again without its 1 chart
and 2 notebooks: they are not pinned, and are read from the snapshot the lockfile names, or from your
own build of that commit where the store does not have that snapshot.
1 dataframe is pinned by its file alone: its snapshot is from before ChartBook 0.6.0, which recorded no
rows, and no rebuild meets such a pin. To pin its rows: `chartbook snapshot` again in its pipeline, with
this version, then `chartbook update` here. Nothing has to be built again: where a table's rows can be
recorded, the same commit and the same files make a new snapshot, once.
chartbook.toml: requires_chartbook is now ">=0.6.0" (it was ">=0.5.0"). chartbook.lock is of a version
that began with ChartBook 0.6.0, and an earlier one cannot read it: with this line it is told to upgrade,
and how. Commit the manifest with the lockfile.
Wrote chartbook.lock.
```

What was chosen, and why:

- **Raised, and not only asked for.** The person who upgrades first is rarely the one it breaks:
  they commit a lockfile that works for them, and a classmate on 0.5 meets the first message
  above. A line the command writes is in the same diff as the lockfile, and nobody has to know
  the rule.
- **By `pin`, `update` and `add`, and never by a build or a read.** Those three are run to change
  what the project pins, and what they write is committed. `chartbook run` writes the lockfile
  too, but a run that snapshots must leave the folder as its commit has it, and a `git`
  dependency is built in ChartBook's own copy of its repository, whose manifest is nobody's to
  commit. So `chartbook run`, and a first read that pins, write no manifest and say which command
  does (`chartbook pin --project-dir FOLDER`, for an upstream built first or a read from a
  notebook's folder), each time, in one line: `chartbook.toml: requires_chartbook = ">=0.5.0" admits a ChartBook
  that cannot read chartbook.lock, which is of a version that began with 0.6.0: such a one says
  only which version it reads. `chartbook pin` raises the line to ">=0.6.0", and it is then told
  to upgrade, and how.` Of a dependency's copy they say nothing. (As first built, every pin
  raised it. A review found that the first `chartbook run --snapshot` after an upgrade then
  built, refused its own snapshot for "changes that are not committed", and refused every run
  after it until someone committed.)
- **Only where the manifest has the key.** One without it says nothing of versions, and has
  nothing here to be kept true: it is left without the key, and an earlier ChartBook there says
  which lockfile version it reads. `chartbook init` has written the key since 0.2.0, and the
  class's report and its upstreams have it.
- **Not where git ignores the lockfile, and not the manifest.** The project is then shared through
  git with its lockfile left out, and that lockfile is this machine's alone: each person's
  ChartBook writes its own, and nobody on an earlier one is handed this one. Raising the manifest
  there would make them upgrade for nothing. One that git tracks, or would, is on its way to
  someone; and where git ignores the manifest too (a project under a home folder kept in git
  with everything left out), git says nothing of how it is shared, and it is held to its
  lockfile as any other is. Both answers are needed: where git gives neither a yes nor a no (no
  repository, no git, none in five seconds), the manifest is held to its lockfile.
- **The rest of what the line says is kept.** `">=0.5.0"` becomes `">=0.6.0"`, and `">=0.5,<0.7"`
  becomes `">=0.6.0,<0.7"`: a lower bound under 0.6.0 goes, and every other clause stays as it
  was written. A line that already admits no earlier ChartBook (`">=0.6"`, `"==0.6.*"`) is not
  touched. Whether a line admits one is asked of the first and a last version of every release
  line before 0.6.0, so that `"!=0.5.*"`, which lets 0.4 in, is raised too. A release candidate
  of 0.6.0 itself is not counted as an earlier ChartBook, however a line lets it in.
- **In place, and whole or not at all.** The manifest is edited as text, as `chartbook add` edits
  it: comments, order, quotes and line endings stay, and the edit is kept only if the file then
  parses to what it was with that one value changed. The new text is written to a file beside
  the manifest and moved over it, so a disk that fills leaves the manifest as it was; a link
  stays a link, and the file's mode is kept. What cannot be written that way is left, the
  command says what to write there and why it did not, and exits as it would have: a line that
  is not the key and a string on one line (an inline `project = { … }`, a string over several
  lines), a file its owner made read-only or whose folder takes no new file, and a file with a
  second name (a hard link), which a file moved over this one would leave with the old text.
  Neither a build nor the check then names `chartbook pin` as what would write it. (A second
  review found a write in place for the hard link could be cut short as before, and a sweep of
  files left by a killed write that could stop the write it was for: both are gone. Such a file,
  `chartbook.toml.<32 digits>.tmp`, is left where a process dies between the write and the move.)
- **Last, and whenever a version 2 lockfile is there.** After the lockfile and the store's note
  of it, so that nothing which stops a pin leaves a manifest written and unsaid. And not only
  when the lockfile is written: a manifest put back by hand, or merged from a branch that had
  not moved, is raised by the next `chartbook pin`, which says `chartbook.lock is unchanged`
  after it. `pin --check` and `run --frozen` write nothing and say nothing of it.
- **`chartbook check` fails on it.** A version 2 lockfile under a line that admits an earlier
  ChartBook is a problem, with the line to write and, where it can, the command that writes it:
  strict, as every check is, since what it guards is someone else's first command.
- **The version is a constant beside the lockfile's own** (`lock.SINCE`, beside `lock.SCHEMA`), and
  a test holds this ChartBook's version to it or later, so that a manifest it raises never shuts
  out the ChartBook that raised it.

### What this ChartBook says of a later one's files

The first message above is this page's own fault to repeat. From this version on, a lockfile or a
snapshot whose version is later than the one read ends with how to get the ChartBook that wrote it,
whatever a manifest says:

```text
Error: Cannot read chartbook.lock: its schema is 'chartbook/lock/v3', and this version of ChartBook reads
'chartbook/lock/v2'. A later ChartBook than this one (0.6.0) wrote it. Install it: `pip install -U chartbook`,
or `uv sync --upgrade-package chartbook` in a uv project
```

`chartbook store ls` lists what it can read and says `not listed:` of each record it cannot, with
those words, where it said `No snapshots.` of a store that had one. (A store of a later layout
said `Use a newer ChartBook` already.)

### The pins there already are

A pin made under 0.5 records no rows: nothing hashed them. It is met by the same file, as it
always was, so **a team that shares a store upgrades and is done**. For anyone who builds an
upstream themselves it is met by nothing they can build, and the way on is the one "A dataframe's
record" gives: the upstream's owner runs `chartbook snapshot` again, which takes no new build, and
the reader runs `chartbook update`. Three lines say so, each at the moment it matters:

- **To whoever pins.** When `pin` or `update` writes a lockfile, it says how many dataframes it
  has just pinned from snapshots of an earlier ChartBook, and what to run (the third paragraph of
  the block above). Of what the command pinned, moved, or wrote again from a version 1 lockfile:
  a pin that changes nothing says nothing, and a dependency that stays where it is while another
  moves is not told of a second time, so a team with a shared store reads it once. Which pins
  those are is told from the snapshot each was pinned from in that run, which records the
  ChartBook that made it (and is not from before if it records any table's rows, whatever number
  it gives), and, for a pin that did not move, from the lockfile having been of version 1. A
  dataframe whose rows are not hashed says why and is not of these, nor is one pinned from its
  repository. Whoever pins cannot tell a table 0.5 did not hash from a file that is no table,
  so the advice promises a new snapshot only "where a table's rows can be recorded". A first
  read that writes the lockfile says the same on stderr, since the pin after it finds nothing
  changed and says nothing.
- **To the upstream's owner.** A build that changed nothing now has a new snapshot, and
  `chartbook snapshot` says why:

  ```text
  $ chartbook snapshot
  ftsfr/fed_yield_curve at 5bb7217: 4 asset(s) in the store
    The same files as the snapshot made 2026-11-04 05:46 UTC, which says nothing of the rows of 1
    dataframe: this one records them, so that a rebuild can meet a pin of it.
  Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
  ```

  Once: the next says `No new snapshot`. A table whose rows cannot be hashed is not counted in
  that line: `rows not hashed: …` says why it has none.
- **And to whoever pins, when it is done.** The reader's `chartbook update` then says `already
  pinned`, since no file changed, and writes the lockfile all the same. So it says what changed
  in it: `1 dataframe has its rows pinned now, as well as its file: a build of someone's own that
  holds the same rows meets the pin.` Or, of a table that cannot be hashed: `acme/rates:nested:
  its rows are not hashed (column 'l' is List(Int64) …): it stays pinned by its file alone.`

In order, for a pipeline and what it pins: upgrade (`pip install -U chartbook`, or
`uv add "chartbook>=0.6.0"`, which brings a team along at its next `uv sync`); `chartbook snapshot`
in each upstream; `chartbook update` in the reader; commit `chartbook.lock` and `chartbook.toml`
together. The changelog's "Read this first" says the same.

### Not built, and the maintainer's to say

- **A pin that hashes the rows itself.** Whoever pins has the bytes, so `chartbook pin` could
  record the rows of a table whose snapshot says nothing of them, and the second snapshot would
  not be needed. It is not built: "a pin copies them from the snapshot it is made from" is this
  page's rule, one command in the upstream costs no build, and a pin that reads every table it
  pins is a slower pin for every team that shares a store.
- **Several stores, in a message.** With a catalog of more than one store a message says `the
  store at first: ~/a, second: ~/b`, which is right and reads oddly.
- **Rows and stand-ins on a machine with several stores** had no test until this step (the
  maintainer's own machine is one). `tests/test_rows_with_several_stores.py` tells the story of
  "What you see" there, the author's and the student's catalogs each of two stores: it found
  nothing to mend.

## What it costs

*As built (step 4), measured 2026-11-17 by the test under a memory limit, on the machine the note
at the top names:* each table hashed by period and then checked against its own record, in one
process that stops itself the moment its memory passes 2 GB.

| Table | Rows by columns | Periods | Hashed in | Checked in | Peak memory |
|---|---|---|---|---|---|
| The class's yield curve | 383 thousand by 4 | 66 | 0.4 s | 0.1 s | 0.21 GB |
| CRSP daily | 27.8 million by 8 | 26 | 7.0 s | 6.0 s | 1.03 GB |
| GKX characteristics | 2.6 million by 99 | 42 | 3.3 s | 2.7 s | 1.41 GB |
| RavenPack, 19 text columns | 28.1 million by 27 | 234 | 29.3 s | 27.1 s | 1.22 GB |

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
| 99 columns of floats, 400 thousand rows, one row group | 300 MB | 4 | 1.01 GB |
| 12 columns of text, 1.5 million rows, one row group | 350 MB | 48 | 0.50 GB |
| One text column of 20 KB, 50 texts over 300 thousand rows (6 GB of rows) | 2 MB | 750 | 0.48 GB |
| 60 text columns of 200 characters, 20 texts each, 300 thousand rows | 11 MB | 36 | 0.61 GB |
| One day at the 128 MB limit: 200 columns of one-character text | | 1 | 0.80 GB |
| One day at the limit: 100 columns of decimals | | 1 | 0.80 GB |
| One day at the limit: 254 columns of floats | | 1 | 1.17 GB |
| A document of 2 MB a row, forty a day | | 10 | 0.38 GB |
| A CSV at its limit, 32 MB of text | 32 MB | 4 | 0.40 GB |
| A CSV of single digits, 200 columns, at its limit | 32 MB | 1 | 1.03 GB |

**A third review broke the limit again, with files and not with rows:** tables whose rows are
within every rule, written so that reading them took 3 to 7 GB. The worst was written by
pyarrow's defaults. What they have in common is that **what a reader holds is set by how a file
is written**: a page of every column at once, each column's dictionary, the footer whole,
whatever is asked of it. pyarrow puts a thousand values to a page whatever they hold, so a
megabyte once in sixty-seven rows makes pages of 15 MB, and documents of 2 MB make pages of 190
MB (polars gives a long value a page of its own). And the reader then in place learnt what a row
takes by reading some first: 256 rows of 7 MB were 1.8 GB before anything was measured.

*So what reading a row group takes is told from the file before a row of it is read. Proposed by
Claude, 2026-11-17:* every page of a parquet file begins with a header that says what it takes
unpacked and how many values it has, and a dictionary page says each value's length. ChartBook
reads those, a few bytes a page (2 s for RavenPack's 39,615 pages), and from them:

- **how many rows to read at once**, so that no run of rows can take more than is held, at worst:
  a column of one width, that width a row (a column of values of one fixed length, its length);
  text held by a dictionary, the dictionary's longest value a row; other text, the pages the run
  lies in, counted whole, since what one value of a page takes is said nowhere but in the page.
  A run is read to 32 MB at worst, which is a few megabytes as a rule, and handed on 8 MB at a
  time. Nothing is learnt by reading too much first, and no row group is begun again;
- **which columns to read together.** The two pages a run begins and ends in, of each column of
  text, are megabytes at worst and bytes as a rule: 150 columns of text would be 300 MB at worst.
  Past 64 MB of that, the columns of text are read apart, a few together, and what each few took
  is seen before the next are read. A run that has taken more than 96 MB already is read no
  further, and the file has no rows hash ("rows too unevenly large");
- **whether the file can be read within the limit at all.** It is refused, unread, with why and
  what would mend it, where a row group's largest pages and dictionaries are more than 768 MB
  together (256 columns of a megabyte page and a megabyte dictionary are within that); where one
  value of text may be more than 128 MB, or a value of one fixed length is more than a megabyte;
  and where the footer is more than 16 MB (said by the file's last eight bytes: 164 MB of footer,
  of 6,000 row groups of 251 columns, took 1.8 GB to read once, and was read three times). A
  dictionary is held more than once while it is read, and what it took is not all given back
  before the periods are hashed: it counts three times for text, eight times for numbers and six
  for a category, for the eight largest dictionaries of a row group.

**Such a refusal is of the file as it is written, not of its rows:** the same rows written with
fewer values a page have a rows hash, and `not_hashed` says so. That is the one place where what
is recorded depends on more than the rows. A table that is read is recorded by its rows alone, as
before: the test writes one table four ways and gets one record. The other way, to hash such a
file whatever it takes, is the 5 GB the review measured. *(The maintainer's to overrule.)*
Writers this refuses by their defaults, where a table is large: **pandas with fastparquet**,
which puts one page to a column chunk and one row group to a file (refused from about 100
million values); **DuckDB**, which puts one page to a column chunk too, of 122,880 rows (refused
from about 6.5 KB a row); and **pyarrow with values of megabytes**, which puts a thousand to a
page (written by polars, or with `write_batch_size` small, they are read).

**A fourth review, of that reader, broke it four more ways, and it is held to its own limits
now.** A column of values of one fixed length had been counted at sixteen bytes a row (50,000
bytes a value: 4.5 GB). The reader of page headers could be made to loop without end by eleven
bytes, and to read as many bytes as a header said: it now reads no more than a header can be (16
MB, and never past its chunk), in a bounded number of steps, and a file whose pages it cannot
read is not read. A file of seven million pages of one value each took 78 s and 3 GB to walk: a
column chunk is walked to 200,000 pages and a file to five million, past which it has no rows
hash. A category with a dictionary of 315 MB was 2.2 GB. And past 128 columns of text a row
group had been read one row at a time (327 s for 60,000 rows), which is what reading columns
apart is for.

**A fifth review broke it with honest files of unusual writing, and with a few changed bytes.**
Five values of one fixed length of 125 MB each took 2.4 GB, and a dictionary of numbers of 448
MB (pyarrow's `dictionary_pagesize_limit` raised) 2.1 GB: hence the megabyte, and the eight
times. A page that is not packed is read as the bytes it has, whatever its header says it
unpacks to, so a header that said sixteen bytes was believed: a page now counts for the greater
of the two. And a row group the footer said was small had been read without its pages being
looked at, so a footer that said a hundred bytes was believed too: every column chunk's pages
are looked at now, and nothing is taken from the footer in their place.

| A file written so as to be hard to read | What happens | Peak memory |
|---|---|---|
| A megabyte once in 67 rows, as pyarrow writes it: pages of 15 MB | Hashed | 0.46 GB |
| 400 MB of long rows, then 100 thousand short ones, in one row group | Hashed | 0.86 GB |
| Documents of 2 MB, no two alike, in pages of 95 MB | Hashed | 0.84 GB |
| The same in pages of 190 MB | Refused: "one value of 'document' may take 191 MB" | 0.10 GB |
| One value of 300 MB | Refused: "one value of 'doc' may take 286 MB" | 0.10 GB |
| 1,200 row groups of 200 columns: a footer of 25 MB | Refused, by its last eight bytes | 0.05 GB |
| A page to a column chunk, 30 columns, 24 MB a page (757 MB held) | Hashed | 1.46 GB |
| The same at 27 MB a page (852 MB held) | Refused | 0.10 GB |
| A dictionary page of text of 250 MB | Hashed | 1.01 GB |
| The same of 300 MB | Refused | 0.10 GB |
| 254 columns of floats, each with a megabyte of dictionary, as pyarrow writes them | Hashed | 1.32 GB |
| A million dates in ten thousand years, 255 columns | Refused: "more than 1,024 calendar years" | 0.14 GB |
| Values of one fixed length of 50,000 bytes, a gigabyte of them | Hashed | 0.61 GB |
| The same of a megabyte each, 500 of them in one page | Hashed | 1.40 GB |
| The same of 125 MB each | Refused: "holds values of 119 MB each" | 0.10 GB |
| A category with a dictionary of 315 MB | Refused | 0.10 GB |
| A dictionary of numbers of 92 MB | Hashed | 1.42 GB |
| The same of 448 MB | Refused | 0.10 GB |
| 150 columns of text, each value its own, 60 thousand rows | Hashed, in 1.9 s | 1.03 GB |
| 230 such columns, as pandas writes them | Hashed, in 5.7 s | 1.21 GB |
| A page to each value, 900 thousand pages | Refused: "more pages than are read" | 0.10 GB |
| 2,048 values of a megabyte, each the same as the last, in a megabyte of page | Hashed | 0.40 GB |

Before, these took 2.1 to 6.5 GB where they are hashed or refused now (measured by the reviews,
some at larger sizes of the same shapes). The peaks just inside the limits, 1.40 to 1.46 GB, are
what the limits were set by. The same test on Linux (CI), on Python 3.10 to 3.13 and at the
oldest polars allowed, had 1.3 GiB at most.

**These are the figures of the libraries of the day,** pyarrow 26 and polars 2.1, on Python
3.13. With the ones Python 3.10 is given (pyarrow 25.0.1, polars 2.0.0), on the same Mac, the four tables peaked at 0.22, 1.15, 1.69 and 1.61 GB, and the page to a column
chunk just inside the limit at 1.85 GB: under the target, with less room. Sixteen of the tests
at once took no more. (Found on 2026-11-17 by the matrix that `uv run doit` runs: one test held
a table of floats of 300 MB to 900 MB, which those libraries pass by a little, and which was
too near what a reader that takes a row group whole takes to tell the two apart. That table is
held to 2 GB now, as the others are; the table of text beside it is held to a gigabyte, which
does tell such a reader.)

**What this is, and is not.** It is every file five reviews could find, measured, under a limit
that the test enforces. It is not a proof for every file there can be: each review found a way
past the one before, the last two with writing no default makes, or with bytes changed by hand.
Two things are known and left: text written as what it adds to the value before
(`DELTA_BYTE_ARRAY`, which pyarrow writes only when asked) is read a few rows at a time, safely
and slowly (107 s for 200 thousand rows of 40 such columns); and a table over 1 GB on disk with
dates in many hundreds of years is slow. **The way to make it a proof is to hash in a process of
its own that stops itself the moment it passes the limit,** as the test's does, and records "not
hashed" for that file: about half a second a snapshot, and its own work on Windows. *Not built;
the maintainer's to say.*

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
- **A batch is told from the file's page headers and dictionaries, never from its sizes on
  disk.** A file that holds its text once, in a dictionary, says a few bytes a row for rows of
  kilobytes: reckoned from the file's sizes, a batch of 65,536 such rows was 780 MB. So the
  longest value of each dictionary is read (it is in the dictionary page), and a row counts for
  that, at worst. A batch is handed on about 8 MB at a time, down to one row. (The reader
  before this one began a row group with 256 rows and began it again with more or fewer as its
  rows turned out; it is gone: see the third review above.)
- **A table's dates fall in 1,024 calendar years at most.** Each period is put by in a file of
  its own, and a million rows scattered over ten thousand years were 3 GB of them and a quarter
  of an hour. *(Proposed by Claude.)*
- **Sorting a period takes five to eight times its size,** more for many columns. A single day
  at the limit peaked at 0.8 GB of short text and 1.2 GB of floats in 254 columns.
- **Rows with no date are one piece too,** and held to the same 128 MB: a file of text dates
  that are not ISO dates has every row there, and 26 million of them took 4.6 GB before they
  were.
- **Only parquet is read a little at a time.** A CSV or JSON lines table is read whole, once,
  and a number that is two bytes of text is eight in memory. So one of more than 32 MB of text
  has no rows hash; a packed file (gzip, zlib or zstd, known by how it begins and not by its
  name, as the reader knows it) is measured by its text, read through and not held. An Arrow
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
- **A parquet file written so that it cannot be read a little at a time:** pages and
  dictionaries of more than 768 MB together in a row group, a value of text that may be more
  than 128 MB or one of a fixed length of more than a megabyte, a footer of more than 16 MB,
  more than 200,000 pages in a column chunk. The same rows written with fewer values a page, or
  fewer row groups, have a rows hash. Reading such a file a column at a time, through scratch
  files, would lift it (and DuckDB's and fastparquet's wide row groups with it), and is not
  built.
- **Dates in more than 1,024 calendar years.**
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
   **Built.**
8. The class's upstreams and the template write `index=False`; the report is pinned again, from
   snapshots this version makes (`chartbook update`, which raises its `requires_chartbook` to
   `">=0.6.0"`: the two files are committed together, and a student on 0.5 is then told what to
   install).
9. The guide, the reference, the changelog, the skill. **Written.**
10. Upgrading: what tells an earlier ChartBook to upgrade, what the commands say of pins from
    before rows were recorded, the release's number ("Upgrading from an earlier ChartBook").
    **Built.**
