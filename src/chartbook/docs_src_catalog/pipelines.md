# Pipelines 🔌

```{toctree}
:maxdepth: 1
{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}
{{pipeline_manifest.page}}
{% endfor %}
```

{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}
  {% set pipeline_page_link = "./" ~ pipeline_manifest.page %}
  {% set dot_or_dotdot = "." %}

## {{ pipeline_manifest.project.name }}

{{pipeline_manifest.project.description}}
{% if pipeline_manifest.from_the_store %}
Not on this machine: the catalog shows it from its snapshots in the store.
{% endif %}

  {% include "pipeline_manifest.md" with context %}

{% endfor %}