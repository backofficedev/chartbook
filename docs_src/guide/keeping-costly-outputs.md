# Keeping Costly Outputs

Most of what a pipeline makes is cheap to make again. Some of it is not:

- the output of a paid API run over a corpus, such as OpenAI's batch API over every filing of a
  decade: money, each time;
- a trained model, a PyTorch network or a fine-tuned language model: GPU hours, and weights that
  never come back bit for bit;
- a pull from a vendor with a quota or hours-long queries, such as Bloomberg or WRDS: a day;
- a scrape of a page that has since changed, or a point-in-time vintage of a series that is
  revised: it cannot be made again at all;
- data a person made by hand, such as labels or a curated list: someone's week.

For an output like that, ChartBook keeps every version in the store for as long as you say, puts
it back on disk when it is missing, and stops a build that is about to make it again.

## Mark it

```toml
[dataframes.embeddings]
path = "./_data/embeddings.parquet"
keep = true

[models.forecaster]
path = "./_models/forecaster.pt"
keep = true
```

`keep = true` goes on any dataframe, chart, notebook, note or model. `chartbook snapshot` (or
`chartbook run --snapshot`) records the mark with the asset, and {ref}`chartbook store gc
<chartbook-store-gc>` then keeps every version of it: for each distinct set of bytes the asset has
had in a snapshot, the newest snapshot holding them stays, with `--aggressive` or without. What
stays is what you paid for and no more: a version made twice to the same bytes is one object in
the store.

`gc` says what the marks keep, in a dry run too:

```text
Kept for `keep = true`: 3 version(s) of acme/docs:embeddings, 4.2 GB, in 3 snapshot(s)
```

To stop keeping an asset, take `keep` out, commit, run `chartbook snapshot`, and the next `gc`
lets the old versions go. What counts is the manifest in the pipeline's folder, or, where the
folder is not on the machine running `gc`, the newest snapshot's record of it, so the mark and
its lifting both travel to a store a team shares.

## Get it back

After a clean, or in a fresh clone:

```console
$ chartbook restore
embeddings: put back at ./_data/embeddings.parquet from the snapshot at 4f2a91c, made 2026-09-30 14:02 UTC (1.2 GB)
```

With no argument, every kept asset that is not on disk is put back, from the pipeline's newest
snapshot that holds it. Name an asset to put that one back, kept or not: `chartbook restore
model/forecaster`. A file that is on disk is never written over. See {ref}`chartbook restore
<chartbook-restore>`.

## The build stops before it remakes it

When a kept asset is not on disk and the store has a version of it, `chartbook run` and
`chartbook build` stop before the build script runs:

```text
Error: acme/docs: embeddings is kept, and is not on disk (./_data/embeddings.parquet). The store has its version from 4f2a91c, made 2026-09-30 14:02 UTC.
  chartbook restore           puts it back
  chartbook run --remake      runs the build without it, which makes it again
Nothing was built.
```

The first time an asset is ever made, nothing stops: the store has no version yet. `--remake` is
for the time you mean it, after a change to the code that makes the asset. It covers every kept
asset at once; to remake one and keep another, restore the other first. `chartbook check` says
the same of a kept asset that is missing.

## Make your build tool skip it

Restoring the file gets you to where your build tool can skip the step. Whether it does is its
own rule. With doit, a task is up to date when its targets exist and its `file_dep` have not
changed since the task last ran; a fresh clone has no record of a last run, so a task with a
`file_dep` runs anyway. For a costly task, name the target and nothing else:

```python
def task_embed():
    return {
        "actions": ["python src/embed.py"],
        "targets": [data.path("embeddings")],
        "uptodate": [True],   # run only when the target is missing
    }
```

It then runs only when the file is missing, which is exactly when you asked for it: after
`chartbook run --remake`, or after you delete the file yourself.

## In CI

A runner starts from nothing. Run `chartbook restore` before the build, then `chartbook run
--frozen`. A store the runner may only read is enough, since restore only reads it.
