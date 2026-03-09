---
myst:
  html_meta:
    "description lang=en": |
      Introduction to chartbook
html_theme.secondary_sidebar.remove: true
---

# {{manifest.site.title}}

<!-- <img src="../assets/logo.png" alt="logo" width="200px" class="bg-primary"> -->

Last updated: {sub-ref}`today`


::::{grid} 3

:::{grid-item-card}  📈 [Charts](cb/charts.md)
:link: cb/charts
:link-type: doc
Search among individual charts (chart haven entries) or browse charts by topic, data source, or other categories. Download or export when you're ready.
:::

:::{grid-item-card} 📊 [Dataframes](cb/dataframes.md)
:link: cb/dataframes
:link-type: doc
Browse dataframes that are produced by each pipeline, the dataframes that power the individual charts.
:::

:::{grid-item-card}  🔌 [Pipelines](cb/pipelines.md)
:link: cb/pipelines
:link-type: doc
Browse the pipelines that power the generated dataframes and charts.
:::

:::{grid-item-card}  👋 [Contributing](contributing.md)
:link: contributing
:link-type: doc
Information about contributing to this catalog project.
:::

:::{grid-item-card}  🩺 [Diagnostics](cb/diagnostics.md)
:link: cb/diagnostics
:link-type: doc
View metadata quality reports and download CSV files that flag metadata gaps across pipelines, dataframes, and charts.
:::

::::

```{toctree}
:maxdepth: 2
:hidden:

cb/charts.md
cb/dataframes.md
cb/pipelines.md
cb/diagnostics.md
contributing.md
```
