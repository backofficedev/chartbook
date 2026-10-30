# {py:mod}`chartbook.sharing`

```{py:module} chartbook.sharing
```

```{autodoc2-docstring} chartbook.sharing
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Copied <chartbook.sharing.Copied>`
  - ```{autodoc2-docstring} chartbook.sharing.Copied
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`copy_snapshots <chartbook.sharing.copy_snapshots>`
  - ```{autodoc2-docstring} chartbook.sharing.copy_snapshots
    :summary:
    ```
* - {py:obj}`export <chartbook.sharing.export>`
  - ```{autodoc2-docstring} chartbook.sharing.export
    :summary:
    ```
* - {py:obj}`import_snapshots <chartbook.sharing.import_snapshots>`
  - ```{autodoc2-docstring} chartbook.sharing.import_snapshots
    :summary:
    ```
````

### API

`````{py:class} Copied
:canonical: chartbook.sharing.Copied

```{autodoc2-docstring} chartbook.sharing.Copied
```

````{py:attribute} copied
:canonical: chartbook.sharing.Copied.copied
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.sharing.Copied.copied
```

````

````{py:attribute} refused
:canonical: chartbook.sharing.Copied.refused
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.sharing.Copied.refused
```

````

````{py:attribute} size_bytes
:canonical: chartbook.sharing.Copied.size_bytes
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.sharing.Copied.size_bytes
```

````

````{py:attribute} there
:canonical: chartbook.sharing.Copied.there
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.sharing.Copied.there
```

````

`````

````{py:exception} SharingError()
:canonical: chartbook.sharing.SharingError

Bases: {py:obj}`chartbook.store.StoreError`

```{autodoc2-docstring} chartbook.sharing.SharingError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.sharing.SharingError.__init__
```

````

````{py:function} copy_snapshots(records: typing.Iterable[chartbook.store.KeptRecord], into: chartbook.store.Store, echo: typing.Callable[[str], None] = lambda line: None) -> chartbook.sharing.Copied
:canonical: chartbook.sharing.copy_snapshots

```{autodoc2-docstring} chartbook.sharing.copy_snapshots
```
````

````{py:function} export(store: chartbook.store.FolderStore, pipeline: str, to: typing.Union[str, pathlib.Path], which: typing.Union[str, list, None] = None, echo: typing.Callable[[str], None] = lambda line: None) -> chartbook.sharing.Copied
:canonical: chartbook.sharing.export

```{autodoc2-docstring} chartbook.sharing.export
```
````

````{py:function} import_snapshots(store: chartbook.store.FolderStore, source: typing.Union[str, pathlib.Path], echo: typing.Callable[[str], None] = lambda line: None) -> chartbook.sharing.Copied
:canonical: chartbook.sharing.import_snapshots

```{autodoc2-docstring} chartbook.sharing.import_snapshots
```
````
