# Explore a Catalog

```{admonition} Draft: this page is an outline
:class: warning
It needs the tutorial store: a zip of snapshots of the example pipelines, built from public-domain
US government data and attached to each ChartBook release on GitHub. Until then, this is the
plan of the page.
```

In fifteen minutes you will download a catalog of three pipelines that depend on one another,
browse it as your team would, ask your agent about it, and build on one of its datasets from a
pipeline of your own.

## 1. Download the catalog

A snippet to paste, with a tab for each shell: download the release's zip with `curl` (`curl.exe`
in PowerShell), unzip it with `tar`, then `chartbook store import` it. Every snippet is the same
three commands; only the shell's spelling differs.

## 2. Build it and open it

`chartbook catalog build`, then `chartbook catalog open`. Screenshots: the catalog's home page,
a pipeline, the Versions page.

## 3. Follow a number to its source

```{image} ../_static/diagrams/provenance-light.svg
:alt: A Fed yield curve file, pulled into the yield_curve pipeline's dataframe at a hash; a chart made from it, and a model in rate_forecast trained on it through a pin
:class: only-light
:align: center
```

```{image} ../_static/diagrams/provenance-dark.svg
:alt: A Fed yield curve file, pulled into the yield_curve pipeline's dataframe at a hash; a chart made from it, and a model in rate_forecast trained on it through a pin
:class: only-dark
:align: center
```

From the model in `rate_forecast`, to the `yield_curve` dataframe it was trained on, at the hash
it was trained on, to the Fed's series that one was pulled from. The same walk from the command
line: `chartbook lineage`.

## 4. Ask your agent

`chartbook install claude-skill`, then "What data do we have on Treasury yields, and how fresh is
it?" A recording of the session: the agent runs `chartbook ls --json`, then
`chartbook get-docs`, and answers from them.

## 5. Build on it

In the Quickstart's `my-pipeline`: `chartbook add yield_curve`, then
`data.load("yield_curve:fed_yield_curve")`. Look at the `git diff` of `chartbook.lock`.

## What the data is

Each series, its source agency, and that it is in the public domain.
