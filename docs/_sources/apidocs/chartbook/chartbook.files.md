# {py:mod}`chartbook.files`

```{py:module} chartbook.files
```

```{autodoc2-docstring} chartbook.files
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`count_by_extension <chartbook.files.count_by_extension>`
  - ```{autodoc2-docstring} chartbook.files.count_by_extension
    :summary:
    ```
* - {py:obj}`extension <chartbook.files.extension>`
  - ```{autodoc2-docstring} chartbook.files.extension
    :summary:
    ```
* - {py:obj}`listing_root <chartbook.files.listing_root>`
  - ```{autodoc2-docstring} chartbook.files.listing_root
    :summary:
    ```
* - {py:obj}`partitions <chartbook.files.partitions>`
  - ```{autodoc2-docstring} chartbook.files.partitions
    :summary:
    ```
* - {py:obj}`path <chartbook.files.path>`
  - ```{autodoc2-docstring} chartbook.files.path
    :summary:
    ```
* - {py:obj}`preview_kind <chartbook.files.preview_kind>`
  - ```{autodoc2-docstring} chartbook.files.preview_kind
    :summary:
    ```
* - {py:obj}`preview_of <chartbook.files.preview_of>`
  - ```{autodoc2-docstring} chartbook.files.preview_of
    :summary:
    ```
* - {py:obj}`preview_text <chartbook.files.preview_text>`
  - ```{autodoc2-docstring} chartbook.files.preview_text
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`COMPRESSED_SUFFIXES <chartbook.files.COMPRESSED_SUFFIXES>`
  - ```{autodoc2-docstring} chartbook.files.COMPRESSED_SUFFIXES
    :summary:
    ```
* - {py:obj}`IMAGE_SUFFIXES <chartbook.files.IMAGE_SUFFIXES>`
  - ```{autodoc2-docstring} chartbook.files.IMAGE_SUFFIXES
    :summary:
    ```
* - {py:obj}`JSON_LINES_SUFFIXES <chartbook.files.JSON_LINES_SUFFIXES>`
  - ```{autodoc2-docstring} chartbook.files.JSON_LINES_SUFFIXES
    :summary:
    ```
* - {py:obj}`OTHER_TYPES <chartbook.files.OTHER_TYPES>`
  - ```{autodoc2-docstring} chartbook.files.OTHER_TYPES
    :summary:
    ```
* - {py:obj}`PREVIEW_BYTES <chartbook.files.PREVIEW_BYTES>`
  - ```{autodoc2-docstring} chartbook.files.PREVIEW_BYTES
    :summary:
    ```
* - {py:obj}`PREVIEW_LINES <chartbook.files.PREVIEW_LINES>`
  - ```{autodoc2-docstring} chartbook.files.PREVIEW_LINES
    :summary:
    ```
* - {py:obj}`PREVIEW_LINE_LENGTH <chartbook.files.PREVIEW_LINE_LENGTH>`
  - ```{autodoc2-docstring} chartbook.files.PREVIEW_LINE_LENGTH
    :summary:
    ```
* - {py:obj}`TEXT_SUFFIXES <chartbook.files.TEXT_SUFFIXES>`
  - ```{autodoc2-docstring} chartbook.files.TEXT_SUFFIXES
    :summary:
    ```
* - {py:obj}`THUMBNAIL_BYTES <chartbook.files.THUMBNAIL_BYTES>`
  - ```{autodoc2-docstring} chartbook.files.THUMBNAIL_BYTES
    :summary:
    ```
* - {py:obj}`TYPES_COUNTED <chartbook.files.TYPES_COUNTED>`
  - ```{autodoc2-docstring} chartbook.files.TYPES_COUNTED
    :summary:
    ```
````

### API

````{py:data} COMPRESSED_SUFFIXES
:canonical: chartbook.files.COMPRESSED_SUFFIXES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.files.COMPRESSED_SUFFIXES
```

````

````{py:data} IMAGE_SUFFIXES
:canonical: chartbook.files.IMAGE_SUFFIXES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.files.IMAGE_SUFFIXES
```

````

````{py:data} JSON_LINES_SUFFIXES
:canonical: chartbook.files.JSON_LINES_SUFFIXES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.files.JSON_LINES_SUFFIXES
```

````

````{py:data} OTHER_TYPES
:canonical: chartbook.files.OTHER_TYPES
:value: >
   'other'

```{autodoc2-docstring} chartbook.files.OTHER_TYPES
```

````

````{py:data} PREVIEW_BYTES
:canonical: chartbook.files.PREVIEW_BYTES
:value: >
   4096

```{autodoc2-docstring} chartbook.files.PREVIEW_BYTES
```

````

````{py:data} PREVIEW_LINES
:canonical: chartbook.files.PREVIEW_LINES
:value: >
   40

```{autodoc2-docstring} chartbook.files.PREVIEW_LINES
```

````

````{py:data} PREVIEW_LINE_LENGTH
:canonical: chartbook.files.PREVIEW_LINE_LENGTH
:value: >
   300

```{autodoc2-docstring} chartbook.files.PREVIEW_LINE_LENGTH
```

````

````{py:data} TEXT_SUFFIXES
:canonical: chartbook.files.TEXT_SUFFIXES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.files.TEXT_SUFFIXES
```

````

````{py:data} THUMBNAIL_BYTES
:canonical: chartbook.files.THUMBNAIL_BYTES
:value: >
   None

```{autodoc2-docstring} chartbook.files.THUMBNAIL_BYTES
```

````

````{py:data} TYPES_COUNTED
:canonical: chartbook.files.TYPES_COUNTED
:value: >
   20

```{autodoc2-docstring} chartbook.files.TYPES_COUNTED
```

````

````{py:function} count_by_extension(names: typing.Iterable[str], most: int = TYPES_COUNTED) -> dict[str, int]
:canonical: chartbook.files.count_by_extension

```{autodoc2-docstring} chartbook.files.count_by_extension
```
````

````{py:function} extension(name: str) -> str
:canonical: chartbook.files.extension

```{autodoc2-docstring} chartbook.files.extension
```
````

````{py:function} listing_root(declared: typing.Union[str, pathlib.Path]) -> pathlib.Path
:canonical: chartbook.files.listing_root

```{autodoc2-docstring} chartbook.files.listing_root
```
````

````{py:function} partitions(relative: str) -> dict[str, str]
:canonical: chartbook.files.partitions

```{autodoc2-docstring} chartbook.files.partitions
```
````

````{py:function} path(ref: typing.Union[str, chartbook.refs.AssetRef], project_dir: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.files.path

```{autodoc2-docstring} chartbook.files.path
```
````

````{py:function} preview_kind(name: str) -> typing.Optional[str]
:canonical: chartbook.files.preview_kind

```{autodoc2-docstring} chartbook.files.preview_kind
```
````

````{py:function} preview_of(listed: list, root: typing.Union[str, pathlib.Path]) -> typing.Optional[dict]
:canonical: chartbook.files.preview_of

```{autodoc2-docstring} chartbook.files.preview_of
```
````

````{py:function} preview_text(file: typing.Union[str, pathlib.Path]) -> typing.Optional[str]
:canonical: chartbook.files.preview_text

```{autodoc2-docstring} chartbook.files.preview_text
```
````
