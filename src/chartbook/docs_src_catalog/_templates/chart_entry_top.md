---
date: "{{pipeline_manifest.source_last_modified_date | yaml_escape}}"
tags: "{{dataframe_manifest.sources | join(', ') | yaml_escape}}"
category: "{{tags | join(', ') | yaml_escape}}"
---

# Chart: {{name}}
{{description}}

## Chart
```{raw} html
<iframe src="../../_static/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html" height="500px" width="100%"></iframe>

<p style="text-align: center;">Sources: {{dataframe_manifest.sources | join(', ')}}</p>
```
[Full Screen Chart](../download_chart/{{pipeline_id | replace('/', '--')}}/{{chart_id}}.html)

