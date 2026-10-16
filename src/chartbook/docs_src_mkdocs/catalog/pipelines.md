# Pipelines 🔌

{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}- [{{ pipeline_manifest.project.name or pipeline_id }}](pipelines/{{pipeline_id | replace("/", "--")}}_README.md)
{% endfor %}

{% for pipeline_id, pipeline_manifest in manifest.pipelines|dictsort %}
  {% set pipeline_page_link = "./pipelines/" ~ (pipeline_id | replace("/", "--")) ~ "_README.md" %}
  {% set dot_or_dotdot = "." %}

## {{ pipeline_manifest.project.name }}

{{pipeline_manifest.project.description}}

  {% include "pipeline_manifest.md" with context %}

{% endfor %}
