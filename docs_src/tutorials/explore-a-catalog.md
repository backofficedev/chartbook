# Explore a Catalog

In fifteen minutes you will build three pipelines that build on one another, browse them as a
catalog, follow a number back to where it came from, ask your agent about it, and build on one of
its datasets from a pipeline of your own. Nothing is downloaded ready-made: every snapshot in the
catalog is one you built.

```{image} ../_static/screenshots/tutorial-catalog-home-light.png
:alt: The catalog's home page: cards for its charts, dataframes, models, pipelines and versions
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-catalog-home-dark.png
:alt: The catalog's home page: cards for its charts, dataframes, models, pipelines and versions
:class: only-dark cb-screenshot
:align: center
```

You need ChartBook installed, as in the {doc}`../getting-started`. The three pipelines are
repositories on GitHub:

| Pipeline | What it makes |
|---|---|
| [`tutorial/treasury_curve`](https://github.com/backofficedev/treasury_curve) | The Treasury yield curve, daily since 1961, and two charts of it |
| [`tutorial/macro_basics`](https://github.com/backofficedev/macro_basics) | Unemployment, inflation, payrolls and GDP growth, monthly, and two charts |
| [`tutorial/rate_outlook`](https://github.com/backofficedev/rate_outlook) | The term spread and a small model of it, **built on the other two** |

Every number in them is public data from the U.S. government ({ref}`below <tutorial-data>`).

## 1. Build two pipelines, and snapshot them

Clone the two pipelines the third builds on, into one folder. Their builds run with `doit`, which
is not part of ChartBook, so install it too, in the environment you made for the Quickstart or a
new one:

```console
mkdir chartbook-tutorial
cd chartbook-tutorial
git clone https://github.com/backofficedev/treasury_curve
git clone https://github.com/backofficedev/macro_basics
pip install chartbook doit
```

A pipeline's build is code, so ChartBook runs one only in a folder you have said is yours to run.
Say it once for the whole folder, then build each pipeline and declare the build ready:

```console
chartbook trust
cd treasury_curve
chartbook run --snapshot
cd ../macro_basics
chartbook run --snapshot
cd ..
```

`chartbook trust` with no path trusts the folder you are in, and every pipeline inside it, so the
third pipeline you clone into it later is covered too. `chartbook run` runs the pipeline's build
script (here `doit`: pull the data, draw the charts, render the site), and `--snapshot` then
copies everything it built into your **store**, each file by its content hash, labelled with the
commit it was built from. That is a **snapshot**, and it is what other pipelines read. Among the
site builder's own output, the first run prints these lines, and ends with a question:

```text
tutorial/treasury_curve: build
.  pull
.  charts
.  docs
tutorial/treasury_curve at e686c8f: 3 asset(s) in the store
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
Stores: default
Ran build in 1 pipeline(s).
No catalog yet, to show it in.
Create one over your store at /Users/you/.chartbook/store? [Y/n]:
```

Press Enter. Your store is a folder, `~/.chartbook/store`, made on this first write. A
**catalog** is a site over every snapshot in it, and by default the two are one unit: ChartBook
makes the catalog the first time something needs it, and asks only this once.

## 2. Build the catalog and open it

```console
chartbook catalog build
chartbook catalog open
```

```{raw} html
<video class="cb-terminal" autoplay loop muted playsinline aria-label="A terminal: a pipeline cloned, built and snapshotted, the catalog made with one Enter and built, and chartbook ls listing the pipelines and their assets">
<source src="../_static/tapes/tutorial.webm" type="video/webm">
<source src="../_static/tapes/tutorial.mp4" type="video/mp4">
</video>
```

Every pipeline, dataframe and chart has a page. Open **Pipelines**, then **Treasury Curve**, then
its dataframe: its columns and first rows, the span of its dates, and under **Provenance** the
hash of its bytes and the commit that made them. Nothing on the page was typed in: it was read
from the snapshot you made a minute ago.

## 3. A pipeline that pins the other two

The third pipeline, `rate_outlook`, never reads the folders of the other two. It declares them in
its `chartbook.toml`,

```toml
[dependencies]
"tutorial/treasury_curve" = { repository = "https://github.com/backofficedev/treasury_curve" }
"tutorial/macro_basics" = { repository = "https://github.com/backofficedev/macro_basics" }
```

and its `chartbook.lock`, committed with the code, names the exact snapshot of each that it was
last built on: the commit, the time it was made, and a hash over everything it reads. Clone it
and build it as before:

```console
git clone https://github.com/backofficedev/rate_outlook
cd rate_outlook
chartbook run --snapshot
```

```text
Error: tutorial/rate_outlook: its pins do not account for every dependency, so it could not have a snapshot, and it was not built:
  tutorial/macro_basics: the lockfile pins its snapshot at 7ff8718, made 2026-11-04T06:07:44.181732Z, and the store at default: /Users/you/.chartbook/store has no such snapshot, so nothing says what it was made from. `chartbook update tutorial/macro_basics` pins one the store has.
  tutorial/treasury_curve: the lockfile pins its snapshot at e686c8f, made 2026-11-04T06:07:38.226894Z, and the store at default: /Users/you/.chartbook/store has no such snapshot, so nothing says what it was made from. `chartbook update tutorial/treasury_curve` pins one the store has. Nothing after it was run.
```

Nothing was built, and that is the point. The lockfile names the snapshots the author built, on
the author's machine, and your store does not have them: it has the ones you built in step 1,
from the same commits, at another time. **A pin never moves by itself.** Moving it is a visible
act, and yours:

```console
chartbook update
```

```text
tutorial/macro_basics: 3 already pinned
  From its snapshot at 7ff8718, made 2026-11-04 14:40 UTC, which says it was made in https://github.com/backofficedev/macro_basics, in store default.
tutorial/treasury_curve: 3 already pinned
  From its snapshot at e686c8f, made 2026-11-04 14:39 UTC, which says it was made in https://github.com/backofficedev/treasury_curve, in store default.
Wrote chartbook.lock.
```

Each pin now names your snapshot. `git diff chartbook.lock` shows exactly what moved: here only
the time each snapshot was made, since the same code pulled the same data the same day, so every
asset is "already pinned" at the same hash. Build this on a later day, when the Board has
published more days of the curve, and the dataframe's hash moves too, and the diff says so. That
diff is what a reviewer reads to know which bytes a result was computed from.

```console
chartbook run --snapshot
```

```text
tutorial/rate_outlook: build
.  spread
.  model
.  charts
.  docs
tutorial/rate_outlook at a11b7b7: 3 asset(s) in the store
  model/spread_ar1: new version 741ac0897fa6
Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.
Stores: default
Ran build in 1 pipeline(s).
```

The model has a version: the hash of its bytes, which no earlier snapshot of this pipeline had.
`chartbook lineage` walks up from the lockfile and checks every hash on the way:

```text
tutorial/rate_outlook (this folder)
├── tutorial/macro_basics: tutorial/macro_basics 7ff8718, made 2026-11-04 14:40:02 UTC, pins checked
└── tutorial/treasury_curve: tutorial/treasury_curve e686c8f, made 2026-11-04 14:39:57 UTC, pins checked
2 snapshot(s) upstream; no gaps.
```

Run `chartbook run --snapshot` once more: nothing new is written, because nothing changed. A
snapshot is the hash of every file the build made, and the same bytes at the same commit, from
the same pins, are the snapshot already there. The hash is how it knows.

Then `cd ..` and build the catalog again (`chartbook catalog build`): it now has three pipelines.
Open **Pipelines**, then **Rate Outlook**: it says what it is, what it holds, and the exact
snapshot of each pipeline it depends on.

```{image} ../_static/screenshots/tutorial-pipeline-light.png
:alt: The rate_outlook pipeline's page: its description, the assets of its newest snapshot, and its two dependencies, each at a commit and a time
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-pipeline-dark.png
:alt: The rate_outlook pipeline's page: its description, the assets of its newest snapshot, and its two dependencies, each at a commit and a time
:class: only-dark cb-screenshot
:align: center
```

## 4. Follow a number to its source

Open **Models**, then **Term Spread AR(1)**. Under **Trained On**: the yield curve, *as pinned*,
the snapshot at `e686c8f`. Under **Inputs**: the content hash of the exact bytes it read.

```{image} ../_static/screenshots/tutorial-model-light.png
:alt: The model's page: trained on tutorial/treasury_curve:zero_coupon_yields as pinned, the snapshot at e686c8f, and the hash of the input it read
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-model-dark.png
:alt: The model's page: trained on tutorial/treasury_curve:zero_coupon_yields as pinned, the snapshot at e686c8f, and the hash of the input it read
:class: only-dark cb-screenshot
:align: center
```

Follow the link to the dataframe, and from there to the pipeline that pulled it from the
Federal Reserve Board. Each step is a page, and each page names the hash of what it was made from:

```{image} ../_static/diagrams/provenance-light.svg
:alt: The Fed's yield curve file, pulled into treasury_curve's zero_coupon_yields at a hash; a chart made from it, and rate_outlook's model trained on it at that hash, through a pin
:class: only-light
:align: center
```

```{image} ../_static/diagrams/provenance-dark.svg
:alt: The Fed's yield curve file, pulled into treasury_curve's zero_coupon_yields at a hash; a chart made from it, and rate_outlook's model trained on it at that hash, through a pin
:class: only-dark
:align: center
```

**Versions** lists every snapshot in the catalog, and which pipeline pins it. When
`treasury_curve` takes a new snapshot, the old one stays, and `rate_outlook` keeps reading it
until its owner moves the pin.

```{image} ../_static/screenshots/tutorial-versions-light.png
:alt: The Versions page: each pipeline's snapshots by commit and time, and which pipeline pins each
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-versions-dark.png
:alt: The Versions page: each pipeline's snapshots by commit and time, and which pipeline pins each
:class: only-dark cb-screenshot
:align: center
```

## 5. Ask your agent

The same facts are on the command line, in a form an agent reads. Teach Claude Code about
ChartBook once:

```console
chartbook install claude-skill
```

Then ask it, in any folder: *"What data do we have on Treasury yields, and what is built on it?"*
It lists the catalog,

```console
$ chartbook ls --json
[
  {"kind": "pipeline", "id": "tutorial/treasury_curve", "name": "Treasury Curve",
   "description": "The Federal Reserve Board's zero-coupon Treasury yield curve, daily since 1961."},
  {"kind": "dataframe", "id": "tutorial/treasury_curve:zero_coupon_yields", "name": "Zero-Coupon Treasury Yields", ...},
  ...
]
```

reads the write-up of what looks relevant, the same text as its page,

```console
$ chartbook get-docs rate_outlook:model/spread_ar1
`spread[t+1] = intercept + slope * spread[t]`, fitted with NumPy on the first 80% of months and
scored on the rest. An example of the mechanics, not a forecast to act on: the point is that its page
says exactly which bytes of the yield curve it was trained on.
```

```{raw} html
<video class="cb-terminal" autoplay loop muted playsinline aria-label="A terminal: chartbook ls --json listing every asset, chartbook get-docs printing a model's write-up, chartbook add pinning the yield curve, and chartbook lineage checking it">
<source src="../_static/tapes/agent.webm" type="video/webm">
<source src="../_static/tapes/agent.mp4" type="video/mp4">
</video>
```

and answers from them. It reads only what it needs: a line per asset first, a write-up when one
matters, the data itself last. {doc}`../guide/agents` says more.

## 6. Build on it

Go back to the Quickstart's `my-pipeline`, and depend on the yield curve:

```console
chartbook add tutorial/treasury_curve
```

```text
Added to [dependencies] in /Users/you/my-pipeline/chartbook.toml: "tutorial/treasury_curve" = {}
tutorial/treasury_curve: 3 pinned
  From its snapshot at e686c8f, made 2026-11-04 14:39 UTC, which says it was made in https://github.com/backofficedev/treasury_curve, in store default.
Wrote chartbook.lock.
```

`chartbook.lock` now records the snapshot, and the hash of each asset in it. Read the data by
name, in any script of the pipeline:

```python
from chartbook import data

yields = data.load("treasury_curve:zero_coupon_yields", format="pandas")   # the pinned copy
```

It reads the same bytes on every run, on every machine with the store, until you run
`chartbook update`. And `chartbook lineage` walks what your pipeline is built on, checking each
hash on the way:

```text
my_pipeline (this folder)
└── tutorial/treasury_curve: tutorial/treasury_curve e686c8f, made 2026-11-04 14:39:57 UTC, pins checked
1 snapshot(s) upstream; no gaps.
```

Commit `chartbook.lock` with your code: a `git diff` of it is how a reviewer sees that a pin moved.

(tutorial-data)=
## What the data is

| Series | From | Pipeline |
|---|---|---|
| Zero-coupon Treasury yields, 1 to 30 years (Gurkaynak, Sack and Wright, 2007) | Federal Reserve Board | `treasury_curve` |
| Civilian unemployment rate (`UNRATE`) | Bureau of Labor Statistics, through FRED | `macro_basics` |
| Consumer Price Index (`CPIAUCSL`) | Bureau of Labor Statistics, through FRED | `macro_basics` |
| Nonfarm payrolls (`PAYEMS`) | Bureau of Labor Statistics, through FRED | `macro_basics` |
| Real GDP (`GDPC1`) | Bureau of Economic Analysis, through FRED | `macro_basics` |

Each is a work of the U.S. government, in the public domain; FRED asks that its series be cited.
The data is as it was on the day you built it. The pipelines are the three repositories above,
each a folder with a `chartbook.toml`, a `dodo.py` and two or three scripts under `src/`: a
pipeline of your own needs no more.

## Next

::::{grid} 1 2 2 2
:gutter: 3

:::{grid-item-card} Depend on another pipeline
:link: ../guide/depending-on-pipelines
:link-type: doc
Pins, the lockfile, `chartbook update`, and what CI checks.
:::

:::{grid-item-card} Let your agent use the catalog
:link: ../guide/agents
:link-type: doc
What an agent runs, and how it decides what to trust.
:::

:::{grid-item-card} Share a catalog with your team
:link: ../guide/catalogs-and-data
:link-type: doc
A store on a shared drive or in S3, and one catalog over all of it.
:::

:::{grid-item-card} Start a real project
:link: ../guide/starting-a-project
:link-type: doc
`chartbook init` scaffolds a project with a build script, notebooks and its own pages.
:::

::::
