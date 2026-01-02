| Dataframe Name                 | {{dataframe_manifest.dataframe_name}}                                                   |
|--------------------------------|--------------------------------------------------------------------------------------|
| Dataframe ID                   | [{{dataframe_id}}]({{link_to_dataframe_docs}})                                       |
| Data Sources                   | {{dataframe_manifest.data_sources | join(', ')}}                                        |
| Data Providers                 | {{dataframe_manifest.data_providers | join(', ')}}                                      |
| Links to Providers             | {{dataframe_manifest.links_to_data_providers | join(', ')}}                             |
| Topic Tags                     | {{dataframe_manifest.topic_tags | join(', ')}}                                          |
| Type of Data Access            | {{dataframe_manifest.type_of_data_access | join(',')}}                                  |
| How is data pulled?            | {{dataframe_manifest.how_is_pulled}}                                                    |
| Data available up to (min)     | {{most_recent_data_min}}                                                             |
| Data available up to (max)     | {{most_recent_data_max}}                                                             |
| Dataframe Path                 | {{dataframe_manifest.dataframe_path}}                                                   |
| Download Data as Parquet       | [Parquet](../../download_dataframe/{{pipeline_id}}/{{dataframe_id}}.parquet)         |
| Download Data as Excel         | [Excel](../../download_dataframe/{{pipeline_id}}/{{dataframe_id}}.xlsx)              |
| Linked Charts                  | {% if dataframe_manifest.linked_charts %} {% for chart_id in dataframe_manifest.linked_charts %} [{{pipeline_id}}:{{chart_id}}](../../charts/{{pipeline_id}}.{{chart_id}}.md)<br> {% endfor %} {% else %} None {% endif %} |
