# {py:mod}`chartbook.lineage`

```{py:module} chartbook.lineage
```

```{autodoc2-docstring} chartbook.lineage
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Lineage <chartbook.lineage.Lineage>`
  - ```{autodoc2-docstring} chartbook.lineage.Lineage
    :summary:
    ```
* - {py:obj}`Node <chartbook.lineage.Node>`
  - ```{autodoc2-docstring} chartbook.lineage.Node
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`walk <chartbook.lineage.walk>`
  - ```{autodoc2-docstring} chartbook.lineage.walk
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEEPEST <chartbook.lineage.DEEPEST>`
  - ```{autodoc2-docstring} chartbook.lineage.DEEPEST
    :summary:
    ```
* - {py:obj}`MANIFEST_LIMIT <chartbook.lineage.MANIFEST_LIMIT>`
  - ```{autodoc2-docstring} chartbook.lineage.MANIFEST_LIMIT
    :summary:
    ```
* - {py:obj}`MOST_INPUTS <chartbook.lineage.MOST_INPUTS>`
  - ```{autodoc2-docstring} chartbook.lineage.MOST_INPUTS
    :summary:
    ```
````

### API

````{py:data} DEEPEST
:canonical: chartbook.lineage.DEEPEST
:value: >
   64

```{autodoc2-docstring} chartbook.lineage.DEEPEST
```

````

`````{py:class} Lineage
:canonical: chartbook.lineage.Lineage

```{autodoc2-docstring} chartbook.lineage.Lineage
```

````{py:method} gaps() -> list[tuple[chartbook.lineage.Node, str]]
:canonical: chartbook.lineage.Lineage.gaps

```{autodoc2-docstring} chartbook.lineage.Lineage.gaps
```

````

````{py:attribute} rehashed
:canonical: chartbook.lineage.Lineage.rehashed
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lineage.Lineage.rehashed
```

````

````{py:attribute} root
:canonical: chartbook.lineage.Lineage.root
:type: chartbook.lineage.Node
:value: >
   None

```{autodoc2-docstring} chartbook.lineage.Lineage.root
```

````

````{py:attribute} snapshots
:canonical: chartbook.lineage.Lineage.snapshots
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.lineage.Lineage.snapshots
```

````

````{py:method} to_dict() -> dict
:canonical: chartbook.lineage.Lineage.to_dict

```{autodoc2-docstring} chartbook.lineage.Lineage.to_dict
```

````

`````

````{py:data} MANIFEST_LIMIT
:canonical: chartbook.lineage.MANIFEST_LIMIT
:value: >
   None

```{autodoc2-docstring} chartbook.lineage.MANIFEST_LIMIT
```

````

````{py:data} MOST_INPUTS
:canonical: chartbook.lineage.MOST_INPUTS
:value: >
   1000

```{autodoc2-docstring} chartbook.lineage.MOST_INPUTS
```

````

`````{py:class} Node
:canonical: chartbook.lineage.Node

```{autodoc2-docstring} chartbook.lineage.Node
```

````{py:attribute} checked
:canonical: chartbook.lineage.Node.checked
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lineage.Node.checked
```

````

````{py:attribute} children
:canonical: chartbook.lineage.Node.children
:type: list[chartbook.lineage.Node]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lineage.Node.children
```

````

````{py:attribute} commit
:canonical: chartbook.lineage.Node.commit
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lineage.Node.commit
```

````

````{py:attribute} gaps
:canonical: chartbook.lineage.Node.gaps
:type: list[str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lineage.Node.gaps
```

````

````{py:attribute} hashes
:canonical: chartbook.lineage.Node.hashes
:type: set
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lineage.Node.hashes
```

````

````{py:attribute} kind
:canonical: chartbook.lineage.Node.kind
:type: str
:value: >
   'snapshot'

```{autodoc2-docstring} chartbook.lineage.Node.kind
```

````

````{py:attribute} label
:canonical: chartbook.lineage.Node.label
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.lineage.Node.label
```

````

````{py:attribute} made_at
:canonical: chartbook.lineage.Node.made_at
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lineage.Node.made_at
```

````

````{py:attribute} pipeline
:canonical: chartbook.lineage.Node.pipeline
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.lineage.Node.pipeline
```

````

````{py:attribute} seen
:canonical: chartbook.lineage.Node.seen
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.lineage.Node.seen
```

````

````{py:attribute} tags
:canonical: chartbook.lineage.Node.tags
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.lineage.Node.tags
```

````

````{py:method} to_dict() -> dict
:canonical: chartbook.lineage.Node.to_dict

```{autodoc2-docstring} chartbook.lineage.Node.to_dict
```

````

`````

````{py:function} walk(project_dir: typing.Union[str, pathlib.Path] = '.', store: typing.Optional[chartbook.store.Store] = None, rehash: bool = False) -> chartbook.lineage.Lineage
:canonical: chartbook.lineage.walk

```{autodoc2-docstring} chartbook.lineage.walk
```
````
