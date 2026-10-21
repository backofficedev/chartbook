| Pipeline Name                   | {{pipeline_manifest.project.name}}                       |
|---------------------------------|--------------------------------------------------------|
| Pipeline ID                     | [{{pipeline_id}}]({{pipeline_page_link}})              |
{% if pipeline_manifest.project.maintainer %}| Maintainer                      | {{pipeline_manifest.project.maintainer}}               |
{% endif %}{% if pipeline_manifest.project.contributors %}| Contributors                    | {{pipeline_manifest.project.contributors | join(', ')}} |
{% endif %}{% if pipeline_manifest.project.repo_url %}| Repository                     | {{pipeline_manifest.project.repo_url}}                  |
{% endif %}{% if pipeline_manifest.project.site_url %}| Pipeline Web Page               | <a href="{{pipeline_manifest.project.site_url}}">Pipeline Web Page</a> |
{% endif %}{% if show_code_updated and pipeline_manifest.source_last_modified_date %}| Date of Last Code Update        | {{pipeline_manifest.source_last_modified_date}}           |
{% endif %}{% if pipeline_manifest.project.os_compatibility %}| OS Compatibility                | {% if pipeline_manifest.project.os_compatibility is string %}{{pipeline_manifest.project.os_compatibility}}{% else %}{{pipeline_manifest.project.os_compatibility | join(', ')}}{% endif %} |
{% endif %}{% if pipeline_manifest.dataframes %}| Linked Dataframes               | {% for dataframe_id, dataframe_manifest in pipeline_manifest.dataframes|dictsort %} [{{pipeline_id}}:{{dataframe_id}}]({{dot_or_dotdot}}/dataframes/{{pipeline_id | replace('/', '--')}}/{{dataframe_id}}.md)<br> {% endfor %} |
{% endif %}
{% if pipeline_manifest.project.build %}
**Build Commands:**
```
{{pipeline_manifest.project.build}}
```
{% endif %}
