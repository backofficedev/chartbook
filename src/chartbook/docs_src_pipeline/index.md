# {{pipeline_manifest.pipeline.pipeline_name}}

Last updated: {sub-ref}`today`

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


```{toctree}
:maxdepth: 1
:caption: Appendix 💡
myst_markdown_demos.md
apidocs/index
```


## Pipeline Specs
{% include "_docs_src/_templates/pipeline_manifest.md" with context %}

{{readme_text}}