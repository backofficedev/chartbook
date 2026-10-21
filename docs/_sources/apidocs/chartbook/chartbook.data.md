# {py:mod}`chartbook.data`

```{py:module} chartbook.data
```

```{autodoc2-docstring} chartbook.data
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`connect <chartbook.data.connect>`
  - ```{autodoc2-docstring} chartbook.data.connect
    :summary:
    ```
* - {py:obj}`get_data_path <chartbook.data.get_data_path>`
  - ```{autodoc2-docstring} chartbook.data.get_data_path
    :summary:
    ```
* - {py:obj}`get_docs <chartbook.data.get_docs>`
  - ```{autodoc2-docstring} chartbook.data.get_docs
    :summary:
    ```
* - {py:obj}`get_docs_path <chartbook.data.get_docs_path>`
  - ```{autodoc2-docstring} chartbook.data.get_docs_path
    :summary:
    ```
* - {py:obj}`load <chartbook.data.load>`
  - ```{autodoc2-docstring} chartbook.data.load
    :summary:
    ```
* - {py:obj}`path <chartbook.data.path>`
  - ```{autodoc2-docstring} chartbook.data.path
    :summary:
    ```
* - {py:obj}`ref <chartbook.data.ref>`
  - ```{autodoc2-docstring} chartbook.data.ref
    :summary:
    ```
* - {py:obj}`scratch <chartbook.data.scratch>`
  - ```{autodoc2-docstring} chartbook.data.scratch
    :summary:
    ```
* - {py:obj}`sql <chartbook.data.sql>`
  - ```{autodoc2-docstring} chartbook.data.sql
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SCRATCH_DIR <chartbook.data.SCRATCH_DIR>`
  - ```{autodoc2-docstring} chartbook.data.SCRATCH_DIR
    :summary:
    ```
````

### API

````{py:data} SCRATCH_DIR
:canonical: chartbook.data.SCRATCH_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.data.SCRATCH_DIR
```

````

````{py:function} connect(source: str, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None)
:canonical: chartbook.data.connect

```{autodoc2-docstring} chartbook.data.connect
```
````

````{py:function} get_data_path(pipeline: str, dataframe: str, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None, *, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.data.get_data_path

```{autodoc2-docstring} chartbook.data.get_data_path
```
````

````{py:function} get_docs(pipeline: str, dataframe: str, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> str
:canonical: chartbook.data.get_docs

```{autodoc2-docstring} chartbook.data.get_docs
```
````

````{py:function} get_docs_path(pipeline: str, dataframe: str, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.data.get_docs_path

```{autodoc2-docstring} chartbook.data.get_docs_path
```
````

````{py:function} load(ref: typing.Optional[typing.Union[str, chartbook.refs.AssetRef]] = None, dataframe: typing.Optional[str] = None, format: str = 'polars', catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None, *, pipeline: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None)
:canonical: chartbook.data.load

```{autodoc2-docstring} chartbook.data.load
```
````

````{py:function} path(ref: typing.Union[str, chartbook.refs.AssetRef], project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.data.path

```{autodoc2-docstring} chartbook.data.path
```
````

````{py:function} ref(reference: typing.Union[str, chartbook.refs.AssetRef], project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> str
:canonical: chartbook.data.ref

```{autodoc2-docstring} chartbook.data.ref
```
````

````{py:function} scratch(project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.data.scratch

```{autodoc2-docstring} chartbook.data.scratch
```
````

````{py:function} sql(query: str, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None)
:canonical: chartbook.data.sql

```{autodoc2-docstring} chartbook.data.sql
```
````
