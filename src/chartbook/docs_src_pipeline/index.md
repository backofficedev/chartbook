# {{pipeline_manifest.project.name}}

{% include "freshness.md" %}

Last updated: {sub-ref}`today`
{% if version %}
**A snapshot of this pipeline:** commit `{{ version.short }}`, made {{ version.made }}. Its owner declared it ready; the write-ups, the data dictionary and the data are as they were then.
{% endif %}

{% if index_toc_content %}
{{ index_toc_content }}
{% elif site_pages_list %}
```{toctree}
:maxdepth: 2
:caption: Site Pages
{{ site_pages_list | join("\n")}}
```
{% endif %}

## Table of Contents

```{toctree}
:maxdepth: 1
:caption: Notebooks 📖
{{ notebook_list | join("\n")}}
```

{% if notes_list %}
```{toctree}
:maxdepth: 1
:caption: Notes 📝
{{ notes_list | join("\n")}}
```
{% endif %}

```{toctree}
:maxdepth: 1
:caption: Pipeline Charts 📈
cb/charts.md
```

```{postlist}
:format: "{title}"
```


```{toctree}
:maxdepth: 1
:caption: Pipeline Dataframes 📊
{{dataframe_file_list | sort | join("\n")}}
```

{% if model_file_list %}
```{toctree}
:maxdepth: 1
:caption: Pipeline Models 🤖
{{model_file_list | sort | join("\n")}}
```
{% endif %}



{% include "pipeline_dependencies.md" %}

## Pipeline Specs
{% include "pipeline_manifest.md" with context %}

{{readme_text}}