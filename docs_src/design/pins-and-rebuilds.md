# Design: pins that a rebuild can meet

```{note}
A design document, written 2026-11-16 from two days of planning with the maintainer. It says how a
lockfile stays useful when the pinned bytes cannot travel, so that each person rebuilds the
upstream: what the lockfile holds for each kind of asset, how a dataframe is pinned by its rows as
well as its bytes, and what each command and each read then does.

Status: **proposed; nothing is built, and no release is named.** Each part says whether the
maintainer decided it, and when, or whether it is still a proposal. The numbers come from a
prototype run on 2026-11-15 and 16, on an Apple M3 Max with 64 GB, polars 2.1.0, pyarrow 26.0.0 and
pandas 3.1.0.
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

The output below is proposed, not what any version prints.

**1. A team shares a store.** Nothing changes. The pinned files are in the store, and are read.

**2. A student builds an upstream a week after the pin.** The lockfile is not touched, `uv run doit`
builds, and a reviewer who builds it a week later still sees the same.

```text
$ chartbook pin --check
ftsfr/fed_yield_curve: read from your own build of 5bb7217
  ftsfr_treas_yield_curve_zero_coupon: the pinned rows, through 2026-10-30; 8 newer rows
All pins are met.
```

**3. The source has changed its past.** The check exits 1, and a build stops with the same message.

```text
$ chartbook pin --check
ftsfr/ken_french_data_library: your build of 31f1e34 does not match the pin
  ftsfr_french_portfolios_25_daily_size_and_bm: the rows of 2024-01-02 to 2024-12-31 differ
  To read your build instead: chartbook update ftsfr/ken_french_data_library
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
| Charts, notebooks, files | No, unless the asset says `lock = true` | The same file, when locked |

*Decided 2026-11-15.* The lockfile is about what code reads. A chart or a notebook is drawn from
the data, and is drawn anew by every build. A plain file can be either, so it is left out unless
its owner says otherwise, with one key on the asset in the owner's manifest:

```toml
[files.parameters]
path = "./_data/parameters.xlsx"
lock = true
```

There is no setting for a whole kind: fixed defaults and one key are one thing to learn.

An asset that is not in the lockfile is still read from the snapshot the lockfile names, by its
commit and time, when a store has that snapshot. So a team that shares a store reads the same
chart as before. Without it, the asset comes from your own build, with nothing checked.

Every lockfile is written again once. The class report's goes from 34 asset records to 17.

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

## The rows hash

A hash of a table's rows, and not of its file. Proposed, from the prototype:

- Every column is put in one type for its kind: whole numbers as 64-bit, decimals as 64-bit floats,
  timestamps as microseconds in UTC, categories as text. `-0.0` is `0.0`, and there is one NaN.
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
(`chartbook.hashing`), and its rules become part of the index specification.

Not settled: a timestamp finer than a microsecond, a decimal type, and a list or a struct in a
column, none of which the prototype hashes. A date column that is text (a CSV's) is parsed as the
index already parses it for a dataframe's date range.

## Choosing the periods

Whole years. A year whose rows are too many is split into months, and such a month into days.
*Decided 2026-11-15: years and not months, since twelve times the lines buys nothing for most
tables; and no setting for it in `chartbook.toml`.*

"Too many" is a size in memory, and it is fixed in ChartBook. *Decided 2026-11-16: it is set for a
machine with 8 GB.* It cannot be taken from the machine that pins: the author may pin on 64 GB,
and a student then hashes those same periods on 8.

When a pin moves, the periods before the last are as they were, with the same lines unless a value
in them changed. The last one grows, or new ones follow it. On CRSP's daily file, pinned through
2019-06-28 and then moved to the end of 2024, 20 of the 21 lines were unchanged, one changed (2019,
which had gained rows) and 5 were added. So the diff of a moved pin shows which periods changed,
and a revision of 1998 is a changed line that a reviewer sees.

## The check, cheapest first

1. **The same file?** The file's byte hash is compared. The store knows it already, so nothing is
   read. A team with a shared store stops here every time.
2. **The same rows, up to `as_of`?** Among your snapshots of the same pipeline at the same commit,
   the rows of each period are hashed and compared. Rows after `as_of` are left out.
3. **Otherwise it differs,** and the message names the periods that do.

A snapshot of yours that meets a pin in the second way **stands in** for it. The result is
remembered against the pin and that snapshot's file, so a read does not hash the table again.

## What each command does

| Command | The same file | The same rows up to `as_of` | Earlier rows differ |
|---|---|---|---|
| `chartbook pin`, `pin --check` | Passes | Passes, and says so | Exits 1 |
| `chartbook run`, a build, `data.load` | Reads it | Reads your build, and says so | Stops with the message |
| `chartbook update` | Nothing to move | Moves the pin: "8 new rows" | Moves the pin: "earlier rows changed" |
| `chartbook snapshot` | "Same as the last one" | "8 new rows" | "Earlier rows changed" |

*Decided 2026-11-15.* The check and a read stop, each with a plain message. `update` and `snapshot`
only report, because there the change is what was asked for; they compare with the pin before, and
with the snapshot before. `chartbook lineage` would say which pins a build of yours stands in for.
*(Proposed.)*

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

A dataframe can be a folder of files, partitioned Hive-style, often by date. *Proposed, awaiting
the maintainer:* its rows are hashed by period, as any dataframe's are, and never file by file.

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

Hashing bytes, and hashing rows a period at a time, with at most 200 MB of rows in a period, on
eight threads:

| Table | Rows by columns | Byte hash | Periods | Rows check | Peak memory |
|---|---|---|---|---|---|
| The class's yield curve | 383 thousand by 4 | under 0.01 s | 66 | 0.8 s | 0.2 GB |
| CRSP daily | 27.8 million by 8 | 0.2 s | 26 | 5.4 s | 0.8 GB |
| GKX characteristics | 2.6 million by 99 | 0.35 s | 42 | 2.7 s | 2.1 GB |
| RavenPack, 19 text columns | 28.1 million by 27 | 0.9 s | 223 | 24.6 s | 3.8 GB |

The time is paid once for each snapshot, and in a check only when the files differ.

**Memory is the limit, and the target is not met.** The target is a peak under 2 GB for any table,
so that a machine with 8 GB is safe. The two wide tables are over it, the prototype is not tuned,
and none of this has been run on a machine with 8 GB. On the text table most of the memory (3.1 of
3.8 GB) goes while the file is split into periods, not while a period is hashed. Before anyone is
told it works on 8 GB, "under 2 GB on these four tables" is a test, run under a memory limit.

What was learned about reading:

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
- **Tick data,** where one day's rows do not fit the size of a period.
- **A large table with no `date_col`.** It has one hash, which takes one sort of the whole table
  in memory.
- **A table in a warehouse.** A snapshot does not pin one today; nothing here changes that.

## Still open

- The rule for folders of files, above.
- The size of a period, and the reader, that keep the peak under 2 GB.
- The parts of the rows hash marked not settled.
- The exact words each command prints.

Outside this repository: step E of the course's pins walkthrough prints a matching hash for a
rebuild cut at the pinned date. That output is not from a real run (it shows the hash of the
382,802-row pinned file beside "rows 382,232"), and with the index column above the cut cannot
match. The page is to be corrected.

## The order of work

1. This page.
2. The lockfile by kind: dataframes and models; `lock = true`; a read of an asset that is not in
   it, through the snapshot the lockfile names. It ends the failure on charts and notebooks, and
   needs nothing below.
3. The rows hash: its form written into the index specification, and tested across writers.
4. Periods: choosing them within the size, in a snapshot's record and in the lockfile; the test
   under a memory limit.
5. The check: a snapshot of yours that stands in, in `pin`, `pin --check` and `run`, with the
   messages.
6. Reads: `data.load` and `data.sql` without the rows after `as_of`; `data.as_of`; what
   `data.path` says.
7. What `update` and `snapshot` say; the warning for a pandas index in `check` and `snapshot`.
8. The class's upstreams and the template write `index=False`; the report is pinned again.
9. The guide, the reference, the changelog, the skill.
