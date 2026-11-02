# Let Your Agent Use the Catalog

```{admonition} Draft: this page is an outline
:class: warning
It describes `chartbook get-docs` and `chartbook ls --json`, which are being finished for 0.5.0
(issue #162). This is the plan of the page.
```

An agent works from the catalog the way a new teammate does: it finds out what exists, reads
what each thing is, uses it, and checks that it can be trusted. Each step is one command, and
each answer is small, so the agent reads only what it needs.

## Install the skill

`chartbook install claude-skill` and what it teaches. Other agents: point them at the site's
`llms.txt`.

## What is there?

`chartbook ls --json`: one record per pipeline and asset, with its ID, name and description. Or
the catalog site's `llms.txt`, one line per asset.

## What is it?

`chartbook get-docs PIPELINE`, the README; `chartbook get-docs PIPELINE:chart/NAME`, the chart's
write-up. The same text a person reads on the page.

## Use it

`data.load("pipeline:name")` from Python; `chartbook path pipeline:name` for any other language;
`chartbook add pipeline` to depend on it, pinned.

## Can it be trusted?

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

`chartbook lineage --json`, the content hashes, and `chartbook.lock` in git: what the agent should
check before it builds on a number.

## A worked session

A recorded session from a question to a pinned dependency, using the tutorial catalog.
