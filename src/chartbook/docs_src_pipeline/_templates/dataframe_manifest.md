| Dataframe Name                 | {{dataframe_manifest.name}}                                                          |
|--------------------------------|--------------------------------------------------------------------------------------|
| Dataframe ID                   | [{{dataframe_id}}]({{link_to_dataframe_docs}})                                       |
{% if dataframe_manifest.sources %}| Sources                        | {{dataframe_manifest.sources | join(', ')}}                                          |
{% endif %}{% if dataframe_manifest.providers %}| Providers                      | {{dataframe_manifest.providers | join(', ')}}                                        |
{% endif %}{% if dataframe_manifest.provider_links %}| Provider Links                 | {{dataframe_manifest.provider_links | join(', ')}}                                   |
{% endif %}{% if dataframe_manifest.tags %}| Tags                           | {{dataframe_manifest.tags | join(', ')}}                                             |
{% endif %}{% if dataframe_manifest.access_types %}| Access Types                   | {{dataframe_manifest.access_types | join(',')}}                                      |
{% endif %}{% if dataframe_manifest.pull_method %}| How is data pulled?            | {{dataframe_manifest.pull_method}}                                                   |
{% endif %}{% if most_recent_data_min and most_recent_data_min != "N/A" %}| Data available up to (min)     | {{most_recent_data_min}}                                                             |
{% endif %}{% if most_recent_data_max and most_recent_data_max != "N/A" %}| Data available up to (max)     | {{most_recent_data_max}}                                                             |
{% endif %}{% if dataframe_manifest.table %}| Table                          | `{{dataframe_manifest.table}}` in source `{{dataframe_manifest.source}}`             |
{% elif dataframe_manifest.query %}| Query                          | in source `{{dataframe_manifest.source}}`; the SQL is below                          |
{% elif dataframe_manifest.path %}| Dataframe Path                 | {{dataframe_manifest.path | code}}                                                        |
{% endif %}{% if enable_data_download %}| Download Data as Parquet       | [Parquet]({{dot_or_dotdot}}/download_dataframe/{{pipeline_id | replace('/', '--')}}/{{dataframe_id}}.parquet)         |
{% endif %}

{% if dataframe_manifest.query %}**Query:**

```sql
{{dataframe_manifest.query}}
```

{% endif %}**Linked Charts:**
{% if dataframe_manifest.linked_charts %}
{% for chart_id in dataframe_manifest.linked_charts %}
- [{{pipeline_id}}:chart/{{chart_id}}]({{dot_or_dotdot}}/charts/{{pipeline_id | replace('/', '--')}}.{{chart_id}}.md)
{% endfor %}
{% else %}
- None
{% endif %}
