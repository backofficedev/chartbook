# {py:mod}`chartbook.indexdiff`

```{py:module} chartbook.indexdiff
```

```{autodoc2-docstring} chartbook.indexdiff
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Change <chartbook.indexdiff.Change>`
  - ```{autodoc2-docstring} chartbook.indexdiff.Change
    :summary:
    ```
* - {py:obj}`IndexDiff <chartbook.indexdiff.IndexDiff>`
  - ```{autodoc2-docstring} chartbook.indexdiff.IndexDiff
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`diff <chartbook.indexdiff.diff>`
  - ```{autodoc2-docstring} chartbook.indexdiff.diff
    :summary:
    ```
* - {py:obj}`format_diff <chartbook.indexdiff.format_diff>`
  - ```{autodoc2-docstring} chartbook.indexdiff.format_diff
    :summary:
    ```
* - {py:obj}`read_index <chartbook.indexdiff.read_index>`
  - ```{autodoc2-docstring} chartbook.indexdiff.read_index
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`COMPUTED_WORDS <chartbook.indexdiff.COMPUTED_WORDS>`
  - ```{autodoc2-docstring} chartbook.indexdiff.COMPUTED_WORDS
    :summary:
    ```
* - {py:obj}`DATA_FIELDS <chartbook.indexdiff.DATA_FIELDS>`
  - ```{autodoc2-docstring} chartbook.indexdiff.DATA_FIELDS
    :summary:
    ```
* - {py:obj}`ENVELOPE_FIELDS <chartbook.indexdiff.ENVELOPE_FIELDS>`
  - ```{autodoc2-docstring} chartbook.indexdiff.ENVELOPE_FIELDS
    :summary:
    ```
* - {py:obj}`RENDERED_KINDS <chartbook.indexdiff.RENDERED_KINDS>`
  - ```{autodoc2-docstring} chartbook.indexdiff.RENDERED_KINDS
    :summary:
    ```
````

### API

````{py:data} COMPUTED_WORDS
:canonical: chartbook.indexdiff.COMPUTED_WORDS
:value: >
   None

```{autodoc2-docstring} chartbook.indexdiff.COMPUTED_WORDS
```

````

`````{py:class} Change
:canonical: chartbook.indexdiff.Change

```{autodoc2-docstring} chartbook.indexdiff.Change
```

````{py:attribute} fields
:canonical: chartbook.indexdiff.Change.fields
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.indexdiff.Change.fields
```

````

````{py:attribute} id
:canonical: chartbook.indexdiff.Change.id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.indexdiff.Change.id
```

````

````{py:attribute} kind
:canonical: chartbook.indexdiff.Change.kind
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.indexdiff.Change.kind
```

````

````{py:property} words
:canonical: chartbook.indexdiff.Change.words
:type: list[str]

```{autodoc2-docstring} chartbook.indexdiff.Change.words
```

````

`````

````{py:data} DATA_FIELDS
:canonical: chartbook.indexdiff.DATA_FIELDS
:value: >
   ('content_hash', 'definition_hash', 'size_bytes', 'row_count', 'columns', 'files')

```{autodoc2-docstring} chartbook.indexdiff.DATA_FIELDS
```

````

````{py:data} ENVELOPE_FIELDS
:canonical: chartbook.indexdiff.ENVELOPE_FIELDS
:value: >
   ('root', 'schema')

```{autodoc2-docstring} chartbook.indexdiff.ENVELOPE_FIELDS
```

````

`````{py:class} IndexDiff
:canonical: chartbook.indexdiff.IndexDiff

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff
```

````{py:attribute} added
:canonical: chartbook.indexdiff.IndexDiff.added
:type: list[dict]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.added
```

````

````{py:attribute} changed
:canonical: chartbook.indexdiff.IndexDiff.changed
:type: list[chartbook.indexdiff.Change]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.changed
```

````

````{py:property} empty
:canonical: chartbook.indexdiff.IndexDiff.empty
:type: bool

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.empty
```

````

````{py:attribute} envelope
:canonical: chartbook.indexdiff.IndexDiff.envelope
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.envelope
```

````

````{py:attribute} removed
:canonical: chartbook.indexdiff.IndexDiff.removed
:type: list[dict]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.removed
```

````

````{py:method} to_dict() -> dict
:canonical: chartbook.indexdiff.IndexDiff.to_dict

```{autodoc2-docstring} chartbook.indexdiff.IndexDiff.to_dict
```

````

`````

````{py:data} RENDERED_KINDS
:canonical: chartbook.indexdiff.RENDERED_KINDS
:value: >
   ('Chart', 'Notebook')

```{autodoc2-docstring} chartbook.indexdiff.RENDERED_KINDS
```

````

````{py:function} diff(before: dict, after: dict) -> chartbook.indexdiff.IndexDiff
:canonical: chartbook.indexdiff.diff

```{autodoc2-docstring} chartbook.indexdiff.diff
```
````

````{py:function} format_diff(found: chartbook.indexdiff.IndexDiff) -> str
:canonical: chartbook.indexdiff.format_diff

```{autodoc2-docstring} chartbook.indexdiff.format_diff
```
````

````{py:function} read_index(path: typing.Union[str, pathlib.Path]) -> dict
:canonical: chartbook.indexdiff.read_index

```{autodoc2-docstring} chartbook.indexdiff.read_index
```
````
