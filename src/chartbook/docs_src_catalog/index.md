---
myst:
  html_meta:
    "description lang=en": |
      Introduction to chartbook
html_theme.secondary_sidebar.remove: true
---

# {{manifest.project.name}}

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

{% if model_file_list %}
:::{grid-item-card} 🤖 [Models](cb/models.md)
:link: cb/models
:link-type: doc
Browse the trained models that pipelines produce: what each was trained on, and how it scores.
:::

{% endif %}
{% if files_file_list %}
:::{grid-item-card} 🗂️ [Files](cb/files.md)
:link: cb/files
:link-type: doc
Browse the files that pipelines keep as they are, whatever is inside: archives, text, PDFs, images, arrays.
:::

{% endif %}
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

{% if has_versions %}
:::{grid-item-card}  🕰️ [Versions](cb/versions.md)
:link: cb/versions
:link-type: doc
Every snapshot of every pipeline in the store, each its own site as it was when its owner declared it ready, and which pipeline pins it.
:::

{% endif %}
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
{% if model_file_list %}cb/models.md
{% endif %}{% if files_file_list %}cb/files.md
{% endif %}cb/pipelines.md
{% if has_versions %}cb/versions.md
{% endif %}{% if has_stores %}cb/stores.md
{% endif %}cb/diagnostics.md
contributing.md
```
