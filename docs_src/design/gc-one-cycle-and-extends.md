# Design: one cycle of gc, and snapshots that extend

```{note}
A design document, written 2026-11-21 from planning with the maintainer on 2026-11-20. His store
on a synced drive was growing with history he did not need, and moving one real store would have
copied 31 GB of older snapshots that share files with each other. He floated three ideas, asked
whether some of them were bad, and accepted the recommendations below ("OK. Please go with your
recommendations").

Status: **proposed, not for 0.6.0 unless he says.** Nothing here is built. It changes no command
and no field of `chartbook.toml` until a later release picks it up. It sits beside
{doc}`snapshots-and-increments` (how the store is laid out and when a snapshot is an increment)
and {doc}`keep` (what `keep = true` never lets go).
```

## The problem in one store

A pipeline that grows by a day's rows each day leaves a complete snapshot, then increments, then
another complete one when the increments add up. `store gc` today keeps, among other things, every
snapshot made in the last seven days, the newest of each pipeline, what a lockfile pins, what a
branch or tag can pin, and every version of a `keep = true` asset. That is right for a pin whose
note has not synced yet, and for a student who cannot rebuild what gc took. It is wrong for a
Drive store that has months of history nobody pins: the folders stay, and a move to the 0.6 layout
copies shared bytes again for each older complete snapshot the newest does not hold.

Two things are wanted: a default that still protects a pin in flight, and a setting that lets a
person whose store is only theirs take the margin to zero; and a word for "this snapshot is the
same rows plus later ones", so that gc could one day let an older pin go when a newer snapshot
can stand in for it.

## What you would type and see

### A. The default still keeps a week

```console
$ chartbook store gc --dry-run
Kept: 12 snapshot(s), naming 40 object(s): 3 because newest of their pipeline,
  2 because a lockfile pins them, 7 because made in the last 7 days
Would remove 4 snapshot(s) and 2 object(s), 1.2 GB:
  acme/rates at a1b2c3d, made 12 days ago: older than 7 days
  …
```

Same rule as today. A teammate's pin note that has not landed in the synced folder yet still has
seven days. Nothing of the setting below is required to keep working as 0.6 does.

### B. A person whose store is only theirs

They put the margin in the same layers as the store setting (`~/.chartbook/settings.toml`, a
catalog's, `CHARTBOOK_*`):

```toml
[store]
keep_days = 0
```

```console
$ chartbook store gc --dry-run
Kept: 5 snapshot(s), naming 40 object(s): 3 because newest of their pipeline,
  2 because a lockfile pins them
Would remove 11 snapshot(s) and 8 object(s), 8.4 GB:
  …
```

`--keep-days` on the command still overrides for one run, as today. The shipped default stays 7;
the setting is how a person opts into "one cycle" without remembering a flag every time.

### C. What "one cycle" keeps, once the margin is gone

For each pipeline, after pins and `keep = true`:

- the latest **complete** snapshot, and
- every **increment** that builds on it.

One sentence. No clock. Storage for that pipeline is bounded to about twice one complete
snapshot, because increments stop and a new complete one is made once they add up to that size
({doc}`snapshots-and-increments`). A lockfile pin still wins: if it names an older complete
snapshot, that one stays, and so do the increments that build on it. A `keep = true` version
still keeps the newest snapshot that holds it.

```text
Before (keep_days = 0, nothing pinned but the work on main):

  snapshots/acme+rates/
    2026-09-01T…_aaaa/     complete, old     ← goes
    2026-10-01T…_bbbb/     complete, old     ← goes
    2026-11-01T…_cccc/     complete, latest  ← stays
  increments/acme+rates/
    2026-11-08T…_dddd/     on cccc           ← stays
    2026-11-15T…_eeee/     on cccc           ← stays

After: one complete + its increments. About two complete-snapshots of room, not twelve.
```

### D. A snapshot that extends another (the word, not yet the gc rule)

Snapshot B **extends** snapshot A when every dated dataframe of A is in B with its earlier rows
unchanged: B has A's rows up to A's `as_of`, and may have later ones. It is about **data**, not
about how the store keeps the files. An increment is a way of storing a snapshot; a complete
snapshot can extend the one before it too.

```text
A: treasury_rates as_of 2026-10-30, rows of 2020–2026-10-30 hashed by year
B: treasury_rates as_of 2026-11-20, same hashes for every year through 2026-10, plus November

B extends A.
```

What that is for, later: where B extends A, a read that wanted A can use B and cut to A's
`as_of` (`data.load` / `data.sql` already do that for a stand-in build;
{doc}`../guide/reading-and-writing-data`). Then gc could let A go even while a lockfile still
names it, because B stands in. **Not adopted:** treating A and B as one snapshot. A snapshot
never changes once made.

## What it does and does not fix

| | Fixes | Does not |
|---|---|---|
| Drive store full of old completes | With `keep_days = 0`, only the latest complete + its increments stay (plus pins and `keep = true`) | A pin that still names an old complete; that complete stays until the pin moves |
| Move copying 31 GB of shared history | Fewer snapshots to copy once gc has run | The move itself; run gc of 0.5.1 first on a 0.5 store, as today |
| "I always pass `--keep-days 0`" | A user setting beside the store | Changing the shipped default of 7 |
| Standing in for an older pin | The word `extends`, and the row test | Building the stand-in in gc for 0.6.0 |

## Limits of `extends`

- **Dated dataframes only**, and only what `data.load` / `data.sql` read by cutting to `as_of`.
- **`data.path` hands the newer file whole**, newer rows and all; a reader of your own still uses
  `data.as_of` ({doc}`../guide/reading-and-writing-data`). That does not change.
- **Charts, notebooks, notes and models have no rows.** B extending A on data does not mean B
  has the same chart HTML or the same model weights. A pin of a model or a `keep = true` asset
  still needs its own snapshot.
- **A restated earlier row breaks it.** If a year hash in B differs from A's, B does not extend
  A. Same evidence a pin already uses for "met by rows".

## Decisions

| Decision | When | Whose |
|---|---|---|
| `--keep-days` becomes a user setting (layers as the store); shipped default stays 7 | 2026-11-20 | maintainer, accepting the recommendation |
| With the margin at 0: keep the latest complete + its increments, plus pins and `keep = true` | 2026-11-20 | maintainer, accepting the recommendation |
| Name the row relationship `extends`; do not merge two snapshots into one | 2026-11-20 | maintainer, accepting the recommendation |
| Build none of this for 0.6.0 unless he says | 2026-11-20 | the write-up's brief |

## Not in this page

- How the setting is named in every layer and env var (follow the store setting's pattern when
  built).
- Whether `store gc` without a setting prints a one-line hint that `keep_days` exists.
- Notes of every branch and tag for gc (separate; {doc}`snapshots-and-increments` already asks
  for better evidence of what each project pins).
- Building `extends` into the stand-in path for pins and into gc. The word and the test come
  first; the gc use is a later proposal once pins-by-rows are ordinary.

## Related

- {doc}`snapshots-and-increments` — complete vs increment, and why only `store gc` removes.
- {doc}`keep` — `keep = true` never lets a version's bytes go.
- {doc}`pins-and-rebuilds` — a rebuild meets a pin by rows up to `as_of`.
- {doc}`../guide/reading-and-writing-data` — `data.path` vs `data.as_of` vs `data.load`.
