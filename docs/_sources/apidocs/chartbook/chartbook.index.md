# {py:mod}`chartbook.index`

```{py:module} chartbook.index
```

```{autodoc2-docstring} chartbook.index
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`apply_code_times <chartbook.index.apply_code_times>`
  - ```{autodoc2-docstring} chartbook.index.apply_code_times
    :summary:
    ```
* - {py:obj}`build_index <chartbook.index.build_index>`
  - ```{autodoc2-docstring} chartbook.index.build_index
    :summary:
    ```
* - {py:obj}`code_changed_at <chartbook.index.code_changed_at>`
  - ```{autodoc2-docstring} chartbook.index.code_changed_at
    :summary:
    ```
* - {py:obj}`dtype_name <chartbook.index.dtype_name>`
  - ```{autodoc2-docstring} chartbook.index.dtype_name
    :summary:
    ```
* - {py:obj}`pipeline_records <chartbook.index.pipeline_records>`
  - ```{autodoc2-docstring} chartbook.index.pipeline_records
    :summary:
    ```
* - {py:obj}`published <chartbook.index.published>`
  - ```{autodoc2-docstring} chartbook.index.published
    :summary:
    ```
* - {py:obj}`record_kind <chartbook.index.record_kind>`
  - ```{autodoc2-docstring} chartbook.index.record_kind
    :summary:
    ```
* - {py:obj}`schema_path <chartbook.index.schema_path>`
  - ```{autodoc2-docstring} chartbook.index.schema_path
    :summary:
    ```
* - {py:obj}`write_index <chartbook.index.write_index>`
  - ```{autodoc2-docstring} chartbook.index.write_index
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ASSET_KINDS <chartbook.index.ASSET_KINDS>`
  - ```{autodoc2-docstring} chartbook.index.ASSET_KINDS
    :summary:
    ```
* - {py:obj}`INDEX_FILE <chartbook.index.INDEX_FILE>`
  - ```{autodoc2-docstring} chartbook.index.INDEX_FILE
    :summary:
    ```
* - {py:obj}`RECORD_VERSION <chartbook.index.RECORD_VERSION>`
  - ```{autodoc2-docstring} chartbook.index.RECORD_VERSION
    :summary:
    ```
* - {py:obj}`SCHEMA <chartbook.index.SCHEMA>`
  - ```{autodoc2-docstring} chartbook.index.SCHEMA
    :summary:
    ```
* - {py:obj}`SCHEMAS_DIR <chartbook.index.SCHEMAS_DIR>`
  - ```{autodoc2-docstring} chartbook.index.SCHEMAS_DIR
    :summary:
    ```
````

### API

````{py:data} ASSET_KINDS
:canonical: chartbook.index.ASSET_KINDS
:value: >
   ('dataframe', 'chart', 'notebook', 'note', 'model')

```{autodoc2-docstring} chartbook.index.ASSET_KINDS
```

````

````{py:data} INDEX_FILE
:canonical: chartbook.index.INDEX_FILE
:value: >
   'index.json'

```{autodoc2-docstring} chartbook.index.INDEX_FILE
```

````

````{py:data} RECORD_VERSION
:canonical: chartbook.index.RECORD_VERSION
:value: >
   'chartbook/v1'

```{autodoc2-docstring} chartbook.index.RECORD_VERSION
```

````

````{py:data} SCHEMA
:canonical: chartbook.index.SCHEMA
:value: >
   'chartbook/index/v1'

```{autodoc2-docstring} chartbook.index.SCHEMA
```

````

````{py:data} SCHEMAS_DIR
:canonical: chartbook.index.SCHEMAS_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.index.SCHEMAS_DIR
```

````

````{py:function} apply_code_times(index: dict, manifest: dict) -> dict
:canonical: chartbook.index.apply_code_times

```{autodoc2-docstring} chartbook.index.apply_code_times
```
````

````{py:function} build_index(manifest: dict, *, cache: typing.Optional[chartbook.hashing.HashCache] = None, skip_pipelines: typing.Iterable[str] = (), generated_at: typing.Optional[datetime.datetime] = None) -> dict
:canonical: chartbook.index.build_index

```{autodoc2-docstring} chartbook.index.build_index
```
````

````{py:function} code_changed_at(pipeline_manifest: dict) -> typing.Optional[str]
:canonical: chartbook.index.code_changed_at

```{autodoc2-docstring} chartbook.index.code_changed_at
```
````

````{py:function} dtype_name(dtype: typing.Any) -> str
:canonical: chartbook.index.dtype_name

```{autodoc2-docstring} chartbook.index.dtype_name
```
````

````{py:function} pipeline_records(pipeline_id: str, pipeline_manifest: dict, cache: typing.Optional[chartbook.hashing.HashCache] = None, known_pipelines: typing.Optional[typing.Mapping[str, pathlib.Path]] = None) -> list[dict]
:canonical: chartbook.index.pipeline_records

```{autodoc2-docstring} chartbook.index.pipeline_records
```
````

````{py:function} published(index: dict) -> dict
:canonical: chartbook.index.published

```{autodoc2-docstring} chartbook.index.published
```
````

````{py:function} record_kind(kind: str) -> str
:canonical: chartbook.index.record_kind

```{autodoc2-docstring} chartbook.index.record_kind
```
````

````{py:function} schema_path(name: str) -> pathlib.Path
:canonical: chartbook.index.schema_path

```{autodoc2-docstring} chartbook.index.schema_path
```
````

````{py:function} write_index(index: dict, path: typing.Union[str, pathlib.Path], only_if_changed: bool = False) -> pathlib.Path
:canonical: chartbook.index.write_index

```{autodoc2-docstring} chartbook.index.write_index
```
````
