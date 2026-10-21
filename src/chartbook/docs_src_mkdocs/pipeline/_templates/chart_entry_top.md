---
date: "{{chart_date | yaml_escape}}"
{% if dataframe_manifest.sources %}sources: "{{dataframe_manifest.sources | join(', ') | yaml_escape}}"
{% endif %}{% if tags %}category: "{{tags | join(', ') | yaml_escape}}"
{% endif %}---

# Chart: {{name}}
{{description}}

{% include "freshness.md" %}

## Chart

<iframe src="../../_static/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html" height="500px" width="100%"></iframe>
{% if dataframe_manifest.sources %}
<p style="text-align: center;">Sources: {{dataframe_manifest.sources | join(', ')}}</p>
{% endif %}
[Full Screen Chart](../download_chart/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html)

