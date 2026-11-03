# {py:mod}`chartbook.assets`

```{py:module} chartbook.assets
```

```{autodoc2-docstring} chartbook.assets
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`files <chartbook.assets.files>`
  - ```{autodoc2-docstring} chartbook.assets.files
    :summary:
    ```
* - {py:obj}`gathered <chartbook.assets.gathered>`
  - ```{autodoc2-docstring} chartbook.assets.gathered
    :summary:
    ```
* - {py:obj}`get_docs <chartbook.assets.get_docs>`
  - ```{autodoc2-docstring} chartbook.assets.get_docs
    :summary:
    ```
* - {py:obj}`get_docs_page <chartbook.assets.get_docs_page>`
  - ```{autodoc2-docstring} chartbook.assets.get_docs_page
    :summary:
    ```
* - {py:obj}`get_docs_path <chartbook.assets.get_docs_path>`
  - ```{autodoc2-docstring} chartbook.assets.get_docs_path
    :summary:
    ```
* - {py:obj}`index <chartbook.assets.index>`
  - ```{autodoc2-docstring} chartbook.assets.index
    :summary:
    ```
* - {py:obj}`path <chartbook.assets.path>`
  - ```{autodoc2-docstring} chartbook.assets.path
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`INDEX_COLUMNS <chartbook.assets.INDEX_COLUMNS>`
  - ```{autodoc2-docstring} chartbook.assets.INDEX_COLUMNS
    :summary:
    ```
* - {py:obj}`WRITE_UP_KINDS <chartbook.assets.WRITE_UP_KINDS>`
  - ```{autodoc2-docstring} chartbook.assets.WRITE_UP_KINDS
    :summary:
    ```
* - {py:obj}`WRITE_UP_LIMIT <chartbook.assets.WRITE_UP_LIMIT>`
  - ```{autodoc2-docstring} chartbook.assets.WRITE_UP_LIMIT
    :summary:
    ```
````

### API

````{py:data} INDEX_COLUMNS
:canonical: chartbook.assets.INDEX_COLUMNS
:value: >
   ('path', 'size_bytes', 'sha256')

```{autodoc2-docstring} chartbook.assets.INDEX_COLUMNS
```

````

````{py:data} WRITE_UP_KINDS
:canonical: chartbook.assets.WRITE_UP_KINDS
:value: >
   ('dataframe', 'chart', 'model', 'file')

```{autodoc2-docstring} chartbook.assets.WRITE_UP_KINDS
```

````

````{py:data} WRITE_UP_LIMIT
:canonical: chartbook.assets.WRITE_UP_LIMIT
:value: >
   None

```{autodoc2-docstring} chartbook.assets.WRITE_UP_LIMIT
```

````

````{py:function} files(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> list[pathlib.Path]
:canonical: chartbook.assets.files

```{autodoc2-docstring} chartbook.assets.files
```
````

````{py:function} gathered(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> chartbook.assets._Gathered
:canonical: chartbook.assets.gathered

```{autodoc2-docstring} chartbook.assets.gathered
```
````

````{py:function} get_docs(pipeline: str, asset: typing.Optional[typing.Union[str, chartbook.refs.AssetRef]] = None, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> str
:canonical: chartbook.assets.get_docs

```{autodoc2-docstring} chartbook.assets.get_docs
```
````

````{py:function} get_docs_page(pipeline: str, asset: typing.Optional[typing.Union[str, chartbook.refs.AssetRef]] = None, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> str
:canonical: chartbook.assets.get_docs_page

```{autodoc2-docstring} chartbook.assets.get_docs_page
```
````

````{py:function} get_docs_path(pipeline: str, asset: typing.Optional[typing.Union[str, chartbook.refs.AssetRef]] = None, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.assets.get_docs_path

```{autodoc2-docstring} chartbook.assets.get_docs_path
```
````

````{py:function} index(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None)
:canonical: chartbook.assets.index

```{autodoc2-docstring} chartbook.assets.index
```
````

````{py:function} path(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.assets.path

```{autodoc2-docstring} chartbook.assets.path
```
````
