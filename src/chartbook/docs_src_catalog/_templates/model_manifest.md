| Model Name                     | {{model_name}}                                                                       |
|--------------------------------|--------------------------------------------------------------------------------------|
| Model ID                       | [{{pipeline_id}}:model/{{model_id}}]({{link_to_model_docs}})                         |
| Description                    | {{model_manifest.description}}                                                       |
| Tags                           | {{model_manifest.tags | join(', ')}}                                                 |
| Model Path                     | `{{model_manifest.path}}`                                                            |
| Get the path                   | `chartbook path model/{{model_id}}`                                                  |
