# Pipelines 🔌

```{toctree}
:maxdepth: 1
{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}
pipelines/{{pipeline_id}}_README.md
{% endfor %}
```

{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}
  {% set pipeline_page_link = "./pipelines/" ~ pipeline_id ~ "_README.md" %}
  {% set dot_or_dotdot = "." %}

## {{ pipeline_manifest.pipeline.pipeline_name }}

{{pipeline_manifest.pipeline.pipeline_description}}

  {# Use passed docs_src_dir variable #}
  {% include (docs_src_dir ~ "/_templates/pipeline_manifest.md") with context %}

{% endfor %}