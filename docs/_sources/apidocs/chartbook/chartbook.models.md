# {py:mod}`chartbook.models`

```{py:module} chartbook.models
```

```{autodoc2-docstring} chartbook.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Staleness <chartbook.models.Staleness>`
  - ```{autodoc2-docstring} chartbook.models.Staleness
    :summary:
    ```
* - {py:obj}`Version <chartbook.models.Version>`
  - ```{autodoc2-docstring} chartbook.models.Version
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`path <chartbook.models.path>`
  - ```{autodoc2-docstring} chartbook.models.path
    :summary:
    ```
* - {py:obj}`read_metrics <chartbook.models.read_metrics>`
  - ```{autodoc2-docstring} chartbook.models.read_metrics
    :summary:
    ```
* - {py:obj}`staleness <chartbook.models.staleness>`
  - ```{autodoc2-docstring} chartbook.models.staleness
    :summary:
    ```
* - {py:obj}`versions <chartbook.models.versions>`
  - ```{autodoc2-docstring} chartbook.models.versions
    :summary:
    ```
* - {py:obj}`versions_in <chartbook.models.versions_in>`
  - ```{autodoc2-docstring} chartbook.models.versions_in
    :summary:
    ```
````

### API

`````{py:class} Staleness
:canonical: chartbook.models.Staleness

```{autodoc2-docstring} chartbook.models.Staleness
```

````{py:attribute} now
:canonical: chartbook.models.Staleness.now
:type: dict
:value: >
   None

```{autodoc2-docstring} chartbook.models.Staleness.now
```

````

````{py:property} stale
:canonical: chartbook.models.Staleness.stale
:type: list[str]

```{autodoc2-docstring} chartbook.models.Staleness.stale
```

````

````{py:attribute} trained_with
:canonical: chartbook.models.Staleness.trained_with
:type: dict
:value: >
   None

```{autodoc2-docstring} chartbook.models.Staleness.trained_with
```

````

````{py:attribute} version
:canonical: chartbook.models.Staleness.version
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.models.Staleness.version
```

````

`````

`````{py:class} Version
:canonical: chartbook.models.Version

```{autodoc2-docstring} chartbook.models.Version
```

````{py:attribute} built_by_run
:canonical: chartbook.models.Version.built_by_run
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.models.Version.built_by_run
```

````

````{py:attribute} commit
:canonical: chartbook.models.Version.commit
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.models.Version.commit
```

````

````{py:attribute} content_hash
:canonical: chartbook.models.Version.content_hash
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.models.Version.content_hash
```

````

````{py:attribute} inputs
:canonical: chartbook.models.Version.inputs
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.models.Version.inputs
```

````

````{py:attribute} labels
:canonical: chartbook.models.Version.labels
:type: tuple
:value: >
   ()

```{autodoc2-docstring} chartbook.models.Version.labels
```

````

````{py:attribute} made_at
:canonical: chartbook.models.Version.made_at
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.models.Version.made_at
```

````

````{py:attribute} metrics
:canonical: chartbook.models.Version.metrics
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.models.Version.metrics
```

````

````{py:attribute} name
:canonical: chartbook.models.Version.name
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.models.Version.name
```

````

````{py:method} to_dict() -> dict
:canonical: chartbook.models.Version.to_dict

```{autodoc2-docstring} chartbook.models.Version.to_dict
```

````

````{py:attribute} trained_on
:canonical: chartbook.models.Version.trained_on
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.models.Version.trained_on
```

````

`````

````{py:function} path(ref: typing.Union[str, chartbook.refs.AssetRef], project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.models.path

```{autodoc2-docstring} chartbook.models.path
```
````

````{py:function} read_metrics(metrics_path: typing.Union[str, pathlib.Path]) -> dict
:canonical: chartbook.models.read_metrics

```{autodoc2-docstring} chartbook.models.read_metrics
```
````

````{py:function} staleness(directory: typing.Union[str, pathlib.Path], model_id: str, entry: dict, store=None) -> typing.Optional[chartbook.models.Staleness]
:canonical: chartbook.models.staleness

```{autodoc2-docstring} chartbook.models.staleness
```
````

````{py:function} versions(ref: typing.Union[str, chartbook.refs.AssetRef], project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> list[chartbook.models.Version]
:canonical: chartbook.models.versions

```{autodoc2-docstring} chartbook.models.versions
```
````

````{py:function} versions_in(directory: typing.Union[str, pathlib.Path], model_id: str, aliases: typing.Optional[dict] = None, store=None) -> list[chartbook.models.Version]
:canonical: chartbook.models.versions_in

```{autodoc2-docstring} chartbook.models.versions_in
```
````
