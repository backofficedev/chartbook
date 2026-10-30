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
````

### API

````{py:data} INDEX_COLUMNS
:canonical: chartbook.assets.INDEX_COLUMNS
:value: >
   ('path', 'size_bytes', 'sha256')

```{autodoc2-docstring} chartbook.assets.INDEX_COLUMNS
```

````

````{py:function} files(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> list[pathlib.Path]
:canonical: chartbook.assets.files

```{autodoc2-docstring} chartbook.assets.files
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
