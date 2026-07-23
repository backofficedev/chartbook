| Dataframe Name                 | {{dataframe_manifest.name}}                                                          |
|--------------------------------|--------------------------------------------------------------------------------------|
| Dataframe ID                   | [{{dataframe_id}}]({{link_to_dataframe_docs}})                                       |
| Sources                        | {{dataframe_manifest.sources | join(', ')}}                                          |
| Providers                      | {{dataframe_manifest.providers | join(', ')}}                                        |
| Provider Links                 | {{dataframe_manifest.provider_links | join(', ')}}                                   |
| Tags                           | {{dataframe_manifest.tags | join(', ')}}                                             |
| Access Types                   | {{dataframe_manifest.access_types | join(',')}}                                      |
| How is data pulled?            | {{dataframe_manifest.pull_method}}                                                   |
| Data available up to (min)     | {{most_recent_data_min}}                                                             |
| Data available up to (max)     | {{most_recent_data_max}}                                                             |
| Dataframe Path                 | {{dataframe_manifest['_resolved_path']}}                                             |
{% if enable_data_download %}
| Download Data as Parquet       | [Parquet](../../download_dataframe/{{pipeline_id | replace('/', '--')}}/{{dataframe_id}}.parquet)         |
| Download Data as Excel         | [Excel](../../download_dataframe/{{pipeline_id | replace('/', '--')}}/{{dataframe_id}}.xlsx)              |
{% endif %}

**Linked Charts:**
{% if dataframe_manifest.linked_charts %}
{% for chart_id in dataframe_manifest.linked_charts %}
- [{{pipeline_id}}:{{chart_id}}](../../charts/{{pipeline_id | replace('/', '--')}}.{{chart_id}}.md)
{% endfor %}
{% else %}
- None
{% endif %}