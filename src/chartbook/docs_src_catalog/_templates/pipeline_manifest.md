| Pipeline Name                   | {{pipeline_manifest.project.name}}                       |
|---------------------------------|--------------------------------------------------------|
| Pipeline ID                     | [{{pipeline_id}}]({{pipeline_page_link}})              |
| Maintainer                      | {{pipeline_manifest.project.maintainer}}               |
| Contributors                    | {{pipeline_manifest.project.contributors | join(', ')}} |
| Repository                     | [{{pipeline_manifest.project.repo_url}}]({{pipeline_manifest.project.repo_url}})                        |
| Pipeline Web Page               | <a href="{{pipeline_manifest.project.site_url}}">Pipeline Web Page      |
| Date of Last Code Update        | {{pipeline_manifest.source_last_modified_date}}           |
| OS Compatibility                | {% if pipeline_manifest.project.os_compatibility is string %}{{pipeline_manifest.project.os_compatibility}}{% else %}{{pipeline_manifest.project.os_compatibility | join(', ')}}{% endif %} |
| Linked Dataframes               | {% for dataframe_id, dataframe_manifest in pipeline_manifest.dataframes.items() %} [{{pipeline_id}}:{{dataframe_id}}]({{dot_or_dotdot}}/dataframes/{{pipeline_id | replace('/', '--')}}/{{dataframe_id}}.md)<br> {% endfor %} |

{% if pipeline_manifest.project.build %}
**Build Commands:**
```
{{pipeline_manifest.project.build}}
```
{% endif %}
