# Linking Pipelines Together

As data projects grow—especially when AI agents are writing more of your code—giant monolithic repos become fragile and hard to verify.

ChartBook lets you split work into small, independent pipelines that depend on each other **like software packages**. Downstream pipelines never read another project's working folder; they read an exact, frozen **snapshot** from your store.

```{image} ../_static/diagrams/depending-light.svg
:alt: Upstream pipeline creates a snapshot in the store; downstream pipeline pins it in chartbook.lock and reads from the store
:class: only-light
:align: center
```

```{image} ../_static/diagrams/depending-dark.svg
:alt: Upstream pipeline creates a snapshot in the store; downstream pipeline pins it in chartbook.lock and reads from the store
:class: only-dark
:align: center
```

## The core workflow in 30 seconds

**1. Upstream pipeline publishes a snapshot** (once committed):

```bash
chartbook run
git add -A && git commit -m "Update Treasury yields"
chartbook snapshot
```

**2. Downstream pipeline adds it and loads by name:**

```bash
chartbook add ftsfr/fed_yield_curve
```

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates")
```

**3. Downstream updates only when *you* choose:**

```bash
chartbook pin --update
```

That's the whole mental model:
- **Snapshot** (`chartbook snapshot`) — freezes what an upstream pipeline built at a specific commit into your store.
- **Pin** (`chartbook.lock`) — records the exact snapshot and content hashes your downstream pipeline reads. Commit `chartbook.lock` to git.
- **Update** (`chartbook pin --update`) — moves your lockfile forward to the newest upstream snapshot and shows you exactly what changed (hashes, new rows, dates).

## `chartbook pin` vs. `chartbook pin --update`

| Command | What it does |
|---|---|
| `chartbook run` | Automatically pins any *new* dependencies in `[dependencies]` before running your build. Never moves existing pins. |
| `chartbook pin` | Pins unpinned dependencies in `chartbook.lock`. Never moves an existing pin. |
| `chartbook pin --update` | Moves existing pins forward to the newest snapshots in your store (pass a pipeline name to update just one). |
| `chartbook pin --check` | Read-only check for CI: verifies every pin in `chartbook.lock` is available. |

:::{tip} You don't even have to declare dependencies upfront
If your script calls `data.load("acme/rates:treasury")` for a pipeline that's in your store but not yet in `chartbook.toml`, `chartbook run` catches it and offers to add it to `[dependencies]`, pin it, and re-run for you.
:::

## How reads behave in notebooks vs. builds

| Situation | In a Jupyter notebook | Inside `chartbook run` |
|---|---|---|
| Dependency is pinned | Reads the pinned snapshot | Reads the pinned snapshot |
| Declared, not yet pinned | Pins newest snapshot & tells you | `run` pins it before building |
| Not in `[dependencies]` | Reads newest snapshot with a warning | Stops and offers to add & pin it |

Need to iterate on an upstream and downstream pipeline simultaneously before snapshotting? Run `chartbook link acme/rates ../rates` to temporarily read the local working folder (delete `chartbook.links.toml` when you're done).

## Inspecting upstream lineage in the catalog

Every downstream chart or model page in your catalog automatically shows which upstream snapshot and content hash it was built from:

```{image} ../_static/screenshots/tutorial-model-light.png
:alt: A model page showing the pinned upstream dataframe, commit, and input hash
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-model-dark.png
:alt: A model page showing the pinned upstream dataframe, commit, and input hash
:class: only-dark cb-screenshot
:align: center
```

## Working without a shared store (cloning someone else's repo)

If you clone a project whose `chartbook.lock` pins snapshots from a teammate's laptop (and you don't share a store), `chartbook run` detects the missing upstream snapshots and prints the exact, ordered commands to build them locally:

```console
$ chartbook run
ftsfr/report cannot be built yet: 2 pipelines it reads are not in the store at /Users/you/.chartbook/store.
Build them in this order, with the commands below, one at a time. Each ends with a snapshot, which is what the next one reads.

1. ftsfr/he_kelly_manela at 7802799    https://github.com/ftsfr/he_kelly_manela
     git clone https://github.com/ftsfr/he_kelly_manela /work/he_kelly_manela
     git -C /work/he_kelly_manela checkout 7802799a41c2
     chartbook run --snapshot --project-dir /work/he_kelly_manela
2. ftsfr/fed_yield_curve at 0db8051    ../fed_yield_curve (a folder on this machine); reads 1 above
     git -C /work/fed_yield_curve checkout 0db8051e3f7b
     chartbook run --snapshot --project-dir /work/fed_yield_curve

Then here again:
     chartbook run --project-dir /work/report
```

Even if the upstream source has published new rows since the original snapshot, ChartBook checks **row hashes up to the pinned date (`as_of`)**. As long as historical rows match, your local build seamlessly stands in for the pin and `data.load()` filters out newer rows automatically so your results stay bit-for-bit reproducible.

:::{dropdown} Tips for making upstream tables easy to reproduce
1. **Set `date_col`** on your dataframe in `chartbook.toml` so ChartBook can hash rows by period and distinguish new rows from revised history.
2. **Write Parquet without unnamed pandas indexes:** use `df.to_parquet(path, index=False)`. Row-position indexes shift when new rows arrive.
3. **In CI, use `chartbook run --frozen`** so builds fail fast if `chartbook.lock` is incomplete or missing a snapshot.
:::

(snapshots-in-the-store)=
## Good to know: how snapshots stay fast and small

ChartBook stores snapshots in human-readable folders under `~/.chartbook/store` (or your team's shared store). You don't need to manage the internals, but a few details are handy for large datasets:

- **Automatic increments:** The first snapshot of a pipeline is **complete** (holds every file). When little changes in later snapshots, ChartBook automatically stores an **increment** containing only the changed files—transparent to every reader and pin. Pass `--complete` to force a standalone folder.
- **Partition large growing tables by year:** Because snapshots compare files, partitioning a multi-gigabyte time-series table by year means each new snapshot only copies the current year's partition.
- **Models have versions & aliases:** Give a model snapshot an alias like `champion` in `[models.<id>.aliases]`, then reference it downstream as `pipeline:model/<id>@champion`.
- **Clean up safely:** Never delete snapshot folders by hand. Use `chartbook store gc` to preview and remove unpinned snapshots older than 7 days.

:::{dropdown} What gets pinned in `chartbook.lock`?
`chartbook.lock` pins **dataframes** and **models** by content hash (and row hashes by year for dataframes). Charts, notebooks, and notes aren't hash-pinned by default because re-rendering them produces different metadata bytes, though you can opt any asset in with `lock = true` in `chartbook.toml` ({ref}`configuration <lock-true>`).

When ChartBook's lockfile format requires a minimum version, `chartbook pin` updates `requires_chartbook = ">=0.6.0"` in `chartbook.toml` so teammates get a clear upgrade message.
:::
