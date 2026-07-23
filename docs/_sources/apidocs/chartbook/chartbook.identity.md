# {py:mod}`chartbook.identity`

```{py:module} chartbook.identity
```

```{autodoc2-docstring} chartbook.identity
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`clear_git_remote_cache <chartbook.identity.clear_git_remote_cache>`
  - ```{autodoc2-docstring} chartbook.identity.clear_git_remote_cache
    :summary:
    ```
* - {py:obj}`derive_pipeline_id <chartbook.identity.derive_pipeline_id>`
  - ```{autodoc2-docstring} chartbook.identity.derive_pipeline_id
    :summary:
    ```
* - {py:obj}`get_git_remote_url <chartbook.identity.get_git_remote_url>`
  - ```{autodoc2-docstring} chartbook.identity.get_git_remote_url
    :summary:
    ```
* - {py:obj}`normalize_ref_to_id <chartbook.identity.normalize_ref_to_id>`
  - ```{autodoc2-docstring} chartbook.identity.normalize_ref_to_id
    :summary:
    ```
* - {py:obj}`resolve_pipeline_ref <chartbook.identity.resolve_pipeline_ref>`
  - ```{autodoc2-docstring} chartbook.identity.resolve_pipeline_ref
    :summary:
    ```
* - {py:obj}`split_rev <chartbook.identity.split_rev>`
  - ```{autodoc2-docstring} chartbook.identity.split_rev
    :summary:
    ```
* - {py:obj}`validate_pipeline_id <chartbook.identity.validate_pipeline_id>`
  - ```{autodoc2-docstring} chartbook.identity.validate_pipeline_id
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ID_COMPONENT_PATTERN <chartbook.identity.ID_COMPONENT_PATTERN>`
  - ```{autodoc2-docstring} chartbook.identity.ID_COMPONENT_PATTERN
    :summary:
    ```
````

### API

````{py:data} ID_COMPONENT_PATTERN
:canonical: chartbook.identity.ID_COMPONENT_PATTERN
:value: >
   'compile(...)'

```{autodoc2-docstring} chartbook.identity.ID_COMPONENT_PATTERN
```

````

````{py:exception} UnsupportedRevisionError()
:canonical: chartbook.identity.UnsupportedRevisionError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.identity.UnsupportedRevisionError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.identity.UnsupportedRevisionError.__init__
```

````

````{py:function} clear_git_remote_cache() -> None
:canonical: chartbook.identity.clear_git_remote_cache

```{autodoc2-docstring} chartbook.identity.clear_git_remote_cache
```
````

````{py:function} derive_pipeline_id(project: dict, base_dir: pathlib.Path | str) -> str
:canonical: chartbook.identity.derive_pipeline_id

```{autodoc2-docstring} chartbook.identity.derive_pipeline_id
```
````

````{py:function} get_git_remote_url(base_dir: pathlib.Path | str) -> typing.Optional[str]
:canonical: chartbook.identity.get_git_remote_url

```{autodoc2-docstring} chartbook.identity.get_git_remote_url
```
````

````{py:function} normalize_ref_to_id(ref: str) -> str
:canonical: chartbook.identity.normalize_ref_to_id

```{autodoc2-docstring} chartbook.identity.normalize_ref_to_id
```
````

````{py:function} resolve_pipeline_ref(keys: typing.Iterable[str], ref: str) -> str
:canonical: chartbook.identity.resolve_pipeline_ref

```{autodoc2-docstring} chartbook.identity.resolve_pipeline_ref
```
````

````{py:function} split_rev(ref: str) -> tuple[str, typing.Optional[str]]
:canonical: chartbook.identity.split_rev

```{autodoc2-docstring} chartbook.identity.split_rev
```
````

````{py:function} validate_pipeline_id(pipeline_id: str) -> str
:canonical: chartbook.identity.validate_pipeline_id

```{autodoc2-docstring} chartbook.identity.validate_pipeline_id
```
````
