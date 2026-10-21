# {py:mod}`chartbook.refs`

```{py:module} chartbook.refs
```

```{autodoc2-docstring} chartbook.refs
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AssetRef <chartbook.refs.AssetRef>`
  - ```{autodoc2-docstring} chartbook.refs.AssetRef
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`parse_asset_ref <chartbook.refs.parse_asset_ref>`
  - ```{autodoc2-docstring} chartbook.refs.parse_asset_ref
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEFAULT_KIND <chartbook.refs.DEFAULT_KIND>`
  - ```{autodoc2-docstring} chartbook.refs.DEFAULT_KIND
    :summary:
    ```
* - {py:obj}`KINDS <chartbook.refs.KINDS>`
  - ```{autodoc2-docstring} chartbook.refs.KINDS
    :summary:
    ```
* - {py:obj}`KIND_TABLES <chartbook.refs.KIND_TABLES>`
  - ```{autodoc2-docstring} chartbook.refs.KIND_TABLES
    :summary:
    ```
````

### API

`````{py:class} AssetRef
:canonical: chartbook.refs.AssetRef

```{autodoc2-docstring} chartbook.refs.AssetRef
```

````{py:method} from_dict(fields: dict) -> chartbook.refs.AssetRef
:canonical: chartbook.refs.AssetRef.from_dict
:classmethod:

```{autodoc2-docstring} chartbook.refs.AssetRef.from_dict
```

````

````{py:method} in_pipeline(pipeline_id: str) -> chartbook.refs.AssetRef
:canonical: chartbook.refs.AssetRef.in_pipeline

```{autodoc2-docstring} chartbook.refs.AssetRef.in_pipeline
```

````

````{py:property} is_local
:canonical: chartbook.refs.AssetRef.is_local
:type: bool

```{autodoc2-docstring} chartbook.refs.AssetRef.is_local
```

````

````{py:attribute} kind
:canonical: chartbook.refs.AssetRef.kind
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.kind
```

````

````{py:property} local_name
:canonical: chartbook.refs.AssetRef.local_name
:type: str

```{autodoc2-docstring} chartbook.refs.AssetRef.local_name
```

````

````{py:attribute} name
:canonical: chartbook.refs.AssetRef.name
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.name
```

````

````{py:attribute} part
:canonical: chartbook.refs.AssetRef.part
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.part
```

````

````{py:attribute} pipeline
:canonical: chartbook.refs.AssetRef.pipeline
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.pipeline
```

````

````{py:property} pipeline_id
:canonical: chartbook.refs.AssetRef.pipeline_id
:type: typing.Optional[str]

```{autodoc2-docstring} chartbook.refs.AssetRef.pipeline_id
```

````

````{py:attribute} registry
:canonical: chartbook.refs.AssetRef.registry
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.registry
```

````

````{py:attribute} rev
:canonical: chartbook.refs.AssetRef.rev
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.rev
```

````

````{py:attribute} scope
:canonical: chartbook.refs.AssetRef.scope
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.refs.AssetRef.scope
```

````

````{py:property} table
:canonical: chartbook.refs.AssetRef.table
:type: str

```{autodoc2-docstring} chartbook.refs.AssetRef.table
```

````

````{py:method} to_dict() -> dict
:canonical: chartbook.refs.AssetRef.to_dict

```{autodoc2-docstring} chartbook.refs.AssetRef.to_dict
```

````

`````

````{py:data} DEFAULT_KIND
:canonical: chartbook.refs.DEFAULT_KIND
:value: >
   'dataframe'

```{autodoc2-docstring} chartbook.refs.DEFAULT_KIND
```

````

````{py:data} KINDS
:canonical: chartbook.refs.KINDS
:value: >
   ('dataframe', 'chart', 'notebook', 'note', 'model')

```{autodoc2-docstring} chartbook.refs.KINDS
```

````

````{py:data} KIND_TABLES
:canonical: chartbook.refs.KIND_TABLES
:value: >
   None

```{autodoc2-docstring} chartbook.refs.KIND_TABLES
```

````

````{py:exception} KindMismatchError(text: str, found: str, expected: str, hint: str = '')
:canonical: chartbook.refs.KindMismatchError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.refs.KindMismatchError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.refs.KindMismatchError.__init__
```

````

````{py:function} parse_asset_ref(text: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None) -> chartbook.refs.AssetRef
:canonical: chartbook.refs.parse_asset_ref

```{autodoc2-docstring} chartbook.refs.parse_asset_ref
```
````
