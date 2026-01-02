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

:::{grid-item-card}  📈 [Charts](charts.md)
:link: charts
:link-type: doc
Search among individual charts (chart haven entries) or browse charts by topic, data source, or other categories. Download or export when you're ready.
:::

:::{grid-item-card} 📊 [Dataframes](dataframes.md)
:link: dataframes
:link-type: doc
Browse dataframes that are produced by each pipeline, the dataframes that power the individual charts.
:::

:::{grid-item-card}  🔌 [Pipelines](pipelines.md)
:link: pipelines
:link-type: doc
Browse the pipelines that power the generated dataframes and charts.
:::

:::{grid-item-card}  👋 [Contributing](contributing.md)
:link: contributing
:link-type: doc
Information about contributing to this catalog project.
:::

:::{grid-item-card}  🩺 [Diagnostics](diagnostics.md)
:link: diagnostics
:link-type: doc
View metadata quality reports and download CSV files that flag metadata gaps across pipelines, dataframes, and charts.
:::

::::

```{toctree}
:maxdepth: 2
:hidden:

charts.md
dataframes.md
pipelines.md
diagnostics.md
contributing.md
```
