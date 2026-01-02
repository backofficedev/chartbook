| Pipeline Name                   | {{pipeline_manifest.pipeline.pipeline_name}}                       |
|---------------------------------|--------------------------------------------------------|
| Pipeline ID                     | [{{pipeline_id}}]({{pipeline_page_link}})              |
| Lead Pipeline Developer         | {{pipeline_manifest.pipeline.lead_pipeline_developer}}             |
| Contributors                    | {{pipeline_manifest.pipeline.contributors | join(', ')}}           |
| Git Repo URL                    | {{pipeline_manifest.pipeline.git_repo_URL}}                        |
| Pipeline Web Page               | <a href="{{pipeline_manifest.webpage_URL}}">Pipeline Web Page      |
| Date of Last Code Update        | {{pipeline_manifest.source_last_modified_date}}           |
| OS Compatibility                | {% if pipeline_manifest.pipeline.os_compatibility is string %}{{pipeline_manifest.pipeline.os_compatibility}}{% else %}{{pipeline_manifest.pipeline.os_compatibility | join(', ')}}{% endif %} |
| Linked Dataframes               | {% for dataframe_id, dataframe_manifest in pipeline_manifest.dataframes.items() %} [{{pipeline_id}}:{{dataframe_id}}]({{dot_or_dotdot}}/dataframes/{{pipeline_id}}/{{dataframe_id}}.md)<br> {% endfor %} |

{% if pipeline_manifest.pipeline.build_commands %}
**Build Commands:**
```
{{pipeline_manifest.pipeline.build_commands}}
```
{% endif %}
