# Explore a Catalog

In fifteen minutes you will download a catalog of three pipelines that build on one another,
browse it as your team would, follow a number back to where it came from, ask your agent about
it, and build on one of its datasets from a pipeline of your own.

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

You need ChartBook installed, as in the {doc}`../getting-started`. The catalog is three
pipelines:

| Pipeline | What it makes |
|---|---|
| `tutorial/treasury_curve` | The Treasury yield curve, daily since 1961, and two charts of it |
| `tutorial/macro_basics` | Unemployment, inflation, payrolls and GDP growth, monthly, and two charts |
| `tutorial/rate_outlook` | The term spread and a small model of it, **built on the other two** |

Every number in it is public data from the U.S. government ({ref}`below <tutorial-data>`).

## 1. Download the catalog

The catalog comes as a store: a folder of each pipeline's **snapshots**, everything one pipeline
built at one commit, each file with its content hash. Download it, unzip it, and import it into
the store on your machine:

::::{tab-set}
:sync-group: shell

:::{tab-item} macOS / Linux
:sync: bash
```bash
curl -L -o chartbook-tutorial-store.zip https://github.com/backofficedev/chartbook/releases/download/v0.5.0/chartbook-tutorial-store.zip
unzip chartbook-tutorial-store.zip
chartbook store import chartbook-tutorial-store
```
:::

:::{tab-item} Windows PowerShell
:sync: powershell
```powershell
curl.exe -L -o chartbook-tutorial-store.zip https://github.com/backofficedev/chartbook/releases/download/v0.5.0/chartbook-tutorial-store.zip
tar -xf chartbook-tutorial-store.zip
chartbook store import chartbook-tutorial-store
```
In PowerShell, `curl` alone is another command: write `curl.exe`.
:::

:::{tab-item} Windows Command Prompt
:sync: cmd
```bat
curl -L -o chartbook-tutorial-store.zip https://github.com/backofficedev/chartbook/releases/download/v0.5.0/chartbook-tutorial-store.zip
tar -xf chartbook-tutorial-store.zip
chartbook store import chartbook-tutorial-store
```
:::

::::

```text
tutorial/treasury_curve at 59a435b, made 2026-11-02T22:14:45.344819Z
tutorial/macro_basics at 59a435b, made 2026-11-02T22:14:54.791033Z
tutorial/rate_outlook at 8cec991, made 2026-11-02T22:15:25.533885Z
Imported 3 snapshot(s), 5.5 MB copied.
```

`chartbook store import` hashes every file as it copies it and checks it against the snapshot's
record, so what you imported is byte for byte what each pipeline built.

## 2. Build it and open it

A **catalog** is one site over every snapshot in your stores. Make one, the first time, then
build it and open it:

```console
chartbook catalog init --title "My Catalog"
chartbook catalog build
chartbook catalog open
```

(Already have a catalog that lists your default store? Skip `catalog init`: the import put the three pipelines there. If your default store is one your team shares, they will see the three pipelines too.)

```{raw} html
<video class="cb-terminal" autoplay loop muted playsinline aria-label="A terminal: the tutorial store unzipped and imported, a catalog made and built, and chartbook ls listing its three pipelines and their assets">
<source src="../_static/tapes/tutorial.webm" type="video/webm">
<source src="../_static/tapes/tutorial.mp4" type="video/mp4">
</video>
```

Every pipeline, dataframe, chart and model has a page. Open **Pipelines**, then **Rate
Outlook**: it says what it is, what it holds, and the exact snapshot of each pipeline it depends
on.

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

## 3. Follow a number to its source

Open **Models**, then **Term Spread AR(1)**. Under **Trained On**: the yield curve, *as pinned*,
the snapshot at `59a435b`. Under **Inputs**: the content hash of the exact bytes it read.

```{image} ../_static/screenshots/tutorial-model-light.png
:alt: The model's page: trained on tutorial/treasury_curve:zero_coupon_yields as pinned, the snapshot at 59a435b, and the hash of the input it read
:class: only-light cb-screenshot
:align: center
```

```{image} ../_static/screenshots/tutorial-model-dark.png
:alt: The model's page: trained on tutorial/treasury_curve:zero_coupon_yields as pinned, the snapshot at 59a435b, and the hash of the input it read
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

## 4. Ask your agent

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

## 5. Build on it

Go back to the Quickstart's `my-pipeline`, and depend on the yield curve:

```console
chartbook add tutorial/treasury_curve
```

```text
Added to [dependencies] in my-pipeline/chartbook.toml: "tutorial/treasury_curve" = {}
tutorial/treasury_curve: 3 pinned
  From its snapshot at 59a435b, made 2026-11-02 22:14 UTC, which says it was made in https://github.com/backofficedev/chartbook, in store default.
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
└── tutorial/treasury_curve: tutorial/treasury_curve 59a435b, made 2026-11-02 22:14:45 UTC, pins checked
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
The data is as it was on the day the store was built; the pipelines that make it are in
[`examples/tutorial/`](https://github.com/backofficedev/chartbook/tree/main/examples/tutorial), with
the script that builds the store.

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

:::{grid-item-card} Take a snapshot of your own
:link: ../guide/depending-on-pipelines
:link-type: doc
`chartbook run --snapshot` declares a build ready for others to pin.
:::

::::
