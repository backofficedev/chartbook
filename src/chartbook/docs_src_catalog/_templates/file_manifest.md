| Name                           | {{files_name}}                                                                       |
|--------------------------------|--------------------------------------------------------------------------------------|
| Files ID                       | [{{pipeline_id}}:file/{{files_id}}]({{link_to_files_docs}})                          |
| Description                    | {{files_manifest.description}}                                                       |
{% if files_manifest.sources %}| Sources                        | {{files_manifest.sources | join(', ')}}                                              |
{% endif %}{% if files_manifest.providers %}| Providers                      | {{files_manifest.providers | join(', ')}}                                            |
{% endif %}{% if files_manifest.provider_links %}| Provider Links                 | {{files_manifest.provider_links | join(', ')}}                                       |
{% endif %}{% if files_manifest.license %}| License                        | {{files_manifest.license}}                                                           |
{% endif %}{% if files_manifest.license_expiration %}| License Expires                | {{files_manifest.license_expiration}}                                                |
{% endif %}{% if files_manifest.restrictions %}| Restrictions                   | {{files_manifest.restrictions}}                                                      |
{% endif %}{% if files_manifest.pull_method %}| How are they pulled?           | {{files_manifest.pull_method}}                                                       |
{% endif %}{% if files_manifest.tags %}| Tags                           | {{files_manifest.tags | join(', ')}}                                                 |
{% endif %}| Path                           | {{files_manifest.path | literal}}                                                    |
| Get the files                  | `chartbook path file/{{files_id}}`; in Python, `assets.files("file/{{files_id}}")`   |
