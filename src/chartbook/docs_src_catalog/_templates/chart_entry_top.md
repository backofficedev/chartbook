---
date: {{pipeline_manifest.source_last_modified_date}}
tags: {{dataframe_manifest.data_sources | join(', ')}}
category: {{topic_tags | join(', ')}}
---

# Chart: {{chart_name}}
{{short_description_chart}}

## Chart
```{raw} html
<iframe src="../_static/{{pipeline_id}}/{{chart_id}}.html" height="500px" width="100%"></iframe>

<p style="text-align: center;">Sources: {{dataframe_manifest.data_sources | join(', ')}}</p>
```
[Full Screen Chart](../download_chart/{{pipeline_id}}/{{chart_id}}.html)


