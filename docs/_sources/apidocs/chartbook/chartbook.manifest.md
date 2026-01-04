# {py:mod}`chartbook.manifest`

```{py:module} chartbook.manifest
```

```{autodoc2-docstring} chartbook.manifest
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`find_latest_source_modification <chartbook.manifest.find_latest_source_modification>`
  - ```{autodoc2-docstring} chartbook.manifest.find_latest_source_modification
    :summary:
    ```
* - {py:obj}`get_default_asset_path <chartbook.manifest.get_default_asset_path>`
  - ```{autodoc2-docstring} chartbook.manifest.get_default_asset_path
    :summary:
    ```
* - {py:obj}`get_favicon_path <chartbook.manifest.get_favicon_path>`
  - ```{autodoc2-docstring} chartbook.manifest.get_favicon_path
    :summary:
    ```
* - {py:obj}`get_file_modified_datetime <chartbook.manifest.get_file_modified_datetime>`
  - ```{autodoc2-docstring} chartbook.manifest.get_file_modified_datetime
    :summary:
    ```
* - {py:obj}`get_logo_path <chartbook.manifest.get_logo_path>`
  - ```{autodoc2-docstring} chartbook.manifest.get_logo_path
    :summary:
    ```
* - {py:obj}`get_pipeline_ids <chartbook.manifest.get_pipeline_ids>`
  - ```{autodoc2-docstring} chartbook.manifest.get_pipeline_ids
    :summary:
    ```
* - {py:obj}`get_pipeline_manifest <chartbook.manifest.get_pipeline_manifest>`
  - ```{autodoc2-docstring} chartbook.manifest.get_pipeline_manifest
    :summary:
    ```
* - {py:obj}`load_manifest <chartbook.manifest.load_manifest>`
  - ```{autodoc2-docstring} chartbook.manifest.load_manifest
    :summary:
    ```
* - {py:obj}`normalize_tags <chartbook.manifest.normalize_tags>`
  - ```{autodoc2-docstring} chartbook.manifest.normalize_tags
    :summary:
    ```
* - {py:obj}`resolve_platform_path <chartbook.manifest.resolve_platform_path>`
  - ```{autodoc2-docstring} chartbook.manifest.resolve_platform_path
    :summary:
    ```
* - {py:obj}`validate_config_file <chartbook.manifest.validate_config_file>`
  - ```{autodoc2-docstring} chartbook.manifest.validate_config_file
    :summary:
    ```
* - {py:obj}`validate_doc_fields <chartbook.manifest.validate_doc_fields>`
  - ```{autodoc2-docstring} chartbook.manifest.validate_doc_fields
    :summary:
    ```
* - {py:obj}`validate_os_compatibility <chartbook.manifest.validate_os_compatibility>`
  - ```{autodoc2-docstring} chartbook.manifest.validate_os_compatibility
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BASE_DIR <chartbook.manifest.BASE_DIR>`
  - ```{autodoc2-docstring} chartbook.manifest.BASE_DIR
    :summary:
    ```
* - {py:obj}`DEFAULT_CONFIG <chartbook.manifest.DEFAULT_CONFIG>`
  - ```{autodoc2-docstring} chartbook.manifest.DEFAULT_CONFIG
    :summary:
    ```
* - {py:obj}`DOCS_BUILD_DIR <chartbook.manifest.DOCS_BUILD_DIR>`
  - ```{autodoc2-docstring} chartbook.manifest.DOCS_BUILD_DIR
    :summary:
    ```
* - {py:obj}`DOCS_SRC_DIR <chartbook.manifest.DOCS_SRC_DIR>`
  - ```{autodoc2-docstring} chartbook.manifest.DOCS_SRC_DIR
    :summary:
    ```
* - {py:obj}`OUTPUT_DIR <chartbook.manifest.OUTPUT_DIR>`
  - ```{autodoc2-docstring} chartbook.manifest.OUTPUT_DIR
    :summary:
    ```
* - {py:obj}`PIPELINE_THEME <chartbook.manifest.PIPELINE_THEME>`
  - ```{autodoc2-docstring} chartbook.manifest.PIPELINE_THEME
    :summary:
    ```
* - {py:obj}`PUBLISH_DIR <chartbook.manifest.PUBLISH_DIR>`
  - ```{autodoc2-docstring} chartbook.manifest.PUBLISH_DIR
    :summary:
    ```
````

### API

````{py:data} BASE_DIR
:canonical: chartbook.manifest.BASE_DIR
:value: >
   'resolve(...)'

```{autodoc2-docstring} chartbook.manifest.BASE_DIR
```

````

````{py:data} DEFAULT_CONFIG
:canonical: chartbook.manifest.DEFAULT_CONFIG
:value: >
   None

```{autodoc2-docstring} chartbook.manifest.DEFAULT_CONFIG
```

````

````{py:data} DOCS_BUILD_DIR
:canonical: chartbook.manifest.DOCS_BUILD_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.manifest.DOCS_BUILD_DIR
```

````

````{py:data} DOCS_SRC_DIR
:canonical: chartbook.manifest.DOCS_SRC_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.manifest.DOCS_SRC_DIR
```

````

````{py:data} OUTPUT_DIR
:canonical: chartbook.manifest.OUTPUT_DIR
:value: >
   'Path(...)'

```{autodoc2-docstring} chartbook.manifest.OUTPUT_DIR
```

````

````{py:data} PIPELINE_THEME
:canonical: chartbook.manifest.PIPELINE_THEME
:value: >
   'pipeline'

```{autodoc2-docstring} chartbook.manifest.PIPELINE_THEME
```

````

````{py:data} PUBLISH_DIR
:canonical: chartbook.manifest.PUBLISH_DIR
:value: >
   'Path(...)'

```{autodoc2-docstring} chartbook.manifest.PUBLISH_DIR
```

````

````{py:function} find_latest_source_modification(base_dir: typing.Union[str, pathlib.Path]) -> datetime.datetime
:canonical: chartbook.manifest.find_latest_source_modification

```{autodoc2-docstring} chartbook.manifest.find_latest_source_modification
```
````

````{py:function} get_default_asset_path(filename: str) -> pathlib.Path
:canonical: chartbook.manifest.get_default_asset_path

```{autodoc2-docstring} chartbook.manifest.get_default_asset_path
```
````

````{py:function} get_favicon_path(config: dict, project_dir: pathlib.Path) -> pathlib.Path
:canonical: chartbook.manifest.get_favicon_path

```{autodoc2-docstring} chartbook.manifest.get_favicon_path
```
````

````{py:function} get_file_modified_datetime(file_path: typing.Union[pathlib.Path, str]) -> datetime.datetime
:canonical: chartbook.manifest.get_file_modified_datetime

```{autodoc2-docstring} chartbook.manifest.get_file_modified_datetime
```
````

````{py:function} get_logo_path(config: dict, project_dir: pathlib.Path) -> pathlib.Path
:canonical: chartbook.manifest.get_logo_path

```{autodoc2-docstring} chartbook.manifest.get_logo_path
```
````

````{py:function} get_pipeline_ids(manifest)
:canonical: chartbook.manifest.get_pipeline_ids

```{autodoc2-docstring} chartbook.manifest.get_pipeline_ids
```
````

````{py:function} get_pipeline_manifest(manifest: dict, pipeline_id: str) -> dict
:canonical: chartbook.manifest.get_pipeline_manifest

```{autodoc2-docstring} chartbook.manifest.get_pipeline_manifest
```
````

````{py:function} load_manifest(base_dir=BASE_DIR)
:canonical: chartbook.manifest.load_manifest

```{autodoc2-docstring} chartbook.manifest.load_manifest
```
````

````{py:function} normalize_tags(tags: list) -> list
:canonical: chartbook.manifest.normalize_tags

```{autodoc2-docstring} chartbook.manifest.normalize_tags
```
````

````{py:function} resolve_platform_path(path_input: typing.Union[str, dict]) -> pathlib.Path
:canonical: chartbook.manifest.resolve_platform_path

```{autodoc2-docstring} chartbook.manifest.resolve_platform_path
```
````

````{py:function} validate_config_file(path: pathlib.Path = BASE_DIR) -> bool
:canonical: chartbook.manifest.validate_config_file

```{autodoc2-docstring} chartbook.manifest.validate_config_file
```
````

````{py:function} validate_doc_fields(manifest: dict, path_key: str, str_key: str, object_type: str, object_id: str) -> tuple[str, str]
:canonical: chartbook.manifest.validate_doc_fields

```{autodoc2-docstring} chartbook.manifest.validate_doc_fields
```
````

````{py:function} validate_os_compatibility(value: typing.Union[str, list]) -> typing.Union[str, list]
:canonical: chartbook.manifest.validate_os_compatibility

```{autodoc2-docstring} chartbook.manifest.validate_os_compatibility
```
````
