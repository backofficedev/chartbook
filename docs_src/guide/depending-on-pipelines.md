# Depending on Another Pipeline

A pipeline often builds on data another pipeline made. ChartBook lets it do that without ever
reading the other pipeline's folder: the other pipeline's owner declares a build ready, and you
pin that build and read it by name.

```{image} ../_static/diagrams/depending-light.svg
:alt: their folder, a snapshot in the store, your folder: run --snapshot, then pin; never read the folder directly
:class: only-light
:align: center
```

```{image} ../_static/diagrams/depending-dark.svg
:alt: their folder, a snapshot in the store, your folder: run --snapshot, then pin; never read the folder directly
:class: only-dark
:align: center
```

Three words carry the whole arrangement, and {doc}`vocabulary` defines them. A **snapshot**
records what one pipeline *made*: every asset it built at one commit, with its content hash,
kept in the **store** (`~/.chartbook/store`, or a folder a team shares). A **pin** freezes which
snapshot of a dependency you read, and the **lockfile**, `chartbook.lock`, records the pins. The
lockfile is committed and has no timestamp on purpose: a `git diff` of it means "a pin moved" and
nothing else.

## Declare it

Say which pipeline and where it is:

```toml
[dependencies]
"ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }

[models.rate_forecaster]
path = "./_models/rate_forecaster.joblib"
trained_on = ["fed_yield_curve:treasury_rates"]
```

`chartbook check` then confirms that the other pipeline is there and that it declares that
dataframe.

## They declare a build ready

**The other pipeline's owner says when a build is ready.** In its folder, with everything
committed:

```console
$ chartbook run --snapshot     # build it, and copy what it built into the store, labelled with the commit
```

That is a snapshot, and it is the only thing of theirs you ever read. You never read their folder.
(`chartbook run` and then `chartbook snapshot` are nearly the same two steps, apart; `--snapshot`
checks that everything is committed *before* it builds, and the snapshot records that the build
ran in the same command.)

## You pin it, and read it by name

```console
$ chartbook pin          # pin their newest snapshot; write chartbook.lock
$ git add chartbook.lock
```

```python
from chartbook import data

rates = data.load("fed_yield_curve:treasury_rates")     # the pinned copy
path = data.path("fed_yield_curve:treasury_rates")      # or just where it is
```

What you get is the build they declared ready, not whatever is in `../fed_yield_curve/_data/`
this minute. They can rebuild, or be half-way through a change, and your results do not move.
When they have made a newer snapshot and you want it:

```console
$ chartbook update       # move the pins; chartbook.lock shows the change in a diff
```

| Who | Does | When |
|---|---|---|
| The other pipeline's owner | `chartbook run --snapshot` | When a build is ready for others |
| You | `chartbook pin`, once | To start depending on it |
| You | `chartbook update` | When you want their newer snapshot |

The `rate_forecast` example does exactly this, with a model trained on the `yield_curve`
example's data. {ref}`[dependencies] <dependencies>` and {ref}`chartbook snapshot
<chartbook-snapshot>` have every detail.

## Building your pipeline

Say how the pipeline is built, in its `chartbook.toml`:

```toml
[scripts]
build = "doit"
```

Then one command pins what you depend on, if nothing is pinned yet, and builds:

```console
$ chartbook run
ftsfr/rate_forecast: pinning what it depends on
ftsfr/fed_yield_curve: 3 pinned
  From its snapshot at 4f2a91c, made 2026-10-13 18:22 UTC.
Wrote chartbook.lock.
ftsfr/rate_forecast: build
Ran build in 1 pipeline(s).
```

`chartbook run` does not build `../fed_yield_curve`, and does not read it. That folder is
somebody's work, perhaps in the middle of a change. Whoever owns it builds it and makes the
snapshot.

It never moves a pin either. If the other pipeline has a newer snapshot, yours is still built
against the one you pinned, and the command tells you so. `chartbook update` is what moves a pin.
See {ref}`chartbook run <chartbook-run>`.

A dependency can also be a git repository, `{ git = "https://…", rev = "v1.2" }`, for one that is
not on your disk. `chartbook pin` clones it, and can pin only what that repository keeps in git:
reference data and models that are committed. For data that the other pipeline builds, use
`chartbook run`, which builds it once in a clean copy of that commit.

## In CI, and on a shared store

A build server should change nothing. `chartbook run --frozen` pins nothing, fetches nothing and
writes nothing: it builds only if the lockfile is complete and every pin is in the store, and
fails with a list of what is missing otherwise. `chartbook pin --frozen` is the same check alone.
A team can point every machine at one store (`[store] url` in the organization's settings file or
the user's `~/.chartbook/settings.toml`, or `CHARTBOOK_STORE`): a folder on a shared disk, or an
S3 bucket, `s3://bucket/prefix`, with `pip install chartbook[s3]`. It may be read-only for the
build server; pinning from a snapshot and reading pinned data need no write to it. A bucket is read
through a copy on each machine, so your code opens files as it always did; {doc}`../reference/configuration`
has the details.

## What the site and the index say

Every asset page shows a **provenance panel**: what the asset was made from and at which hashes,
and what uses it. For a model, the panel and the page say when the data it was trained on has moved
since, so that an out-of-date model is seen before it is used. The index records the same facts
(`inputs`, `pinned_inputs`, `trained_with`, `inputs_now`, `stale_inputs`), and `chartbook index
diff` between two builds says "pins moved" or "out of date" in words. See
{doc}`documenting-a-pipeline` for the panel and {doc}`how-the-build-works` for the index.

## Models have versions

A model's bytes become a **version** when a snapshot first holds them, named by the first twelve
digits of their hash (more, if two versions would otherwise share a name). `[models.x.aliases]` gives a version a label such as `champion`, and another
pipeline reads it as `fed_yield_curve:model/x@champion`: the lockfile pins the label to a version,
`chartbook update` moves it when the label does. `chartbook path model/x@<version>` gives the
path of any version on this machine. {ref}`chartbook pin <chartbook-pin>` has the details, and
{doc}`../design/models` the reasoning.
