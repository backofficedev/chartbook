# {py:mod}`chartbook.formats`

```{py:module} chartbook.formats
```

```{autodoc2-docstring} chartbook.formats
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Reading <chartbook.formats.Reading>`
  - ```{autodoc2-docstring} chartbook.formats.Reading
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`arrow_dataset <chartbook.formats.arrow_dataset>`
  - ```{autodoc2-docstring} chartbook.formats.arrow_dataset
    :summary:
    ```
* - {py:obj}`check_entry <chartbook.formats.check_entry>`
  - ```{autodoc2-docstring} chartbook.formats.check_entry
    :summary:
    ```
* - {py:obj}`declared <chartbook.formats.declared>`
  - ```{autodoc2-docstring} chartbook.formats.declared
    :summary:
    ```
* - {py:obj}`ending_of <chartbook.formats.ending_of>`
  - ```{autodoc2-docstring} chartbook.formats.ending_of
    :summary:
    ```
* - {py:obj}`files_of <chartbook.formats.files_of>`
  - ```{autodoc2-docstring} chartbook.formats.files_of
    :summary:
    ```
* - {py:obj}`format_of <chartbook.formats.format_of>`
  - ```{autodoc2-docstring} chartbook.formats.format_of
    :summary:
    ```
* - {py:obj}`format_of_name <chartbook.formats.format_of_name>`
  - ```{autodoc2-docstring} chartbook.formats.format_of_name
    :summary:
    ```
* - {py:obj}`handed <chartbook.formats.handed>`
  - ```{autodoc2-docstring} chartbook.formats.handed
    :summary:
    ```
* - {py:obj}`handed_name <chartbook.formats.handed_name>`
  - ```{autodoc2-docstring} chartbook.formats.handed_name
    :summary:
    ```
* - {py:obj}`kept <chartbook.formats.kept>`
  - ```{autodoc2-docstring} chartbook.formats.kept
    :summary:
    ```
* - {py:obj}`reading <chartbook.formats.reading>`
  - ```{autodoc2-docstring} chartbook.formats.reading
    :summary:
    ```
* - {py:obj}`reading_of <chartbook.formats.reading_of>`
  - ```{autodoc2-docstring} chartbook.formats.reading_of
    :summary:
    ```
* - {py:obj}`scan <chartbook.formats.scan>`
  - ```{autodoc2-docstring} chartbook.formats.scan
    :summary:
    ```
* - {py:obj}`scan_location <chartbook.formats.scan_location>`
  - ```{autodoc2-docstring} chartbook.formats.scan_location
    :summary:
    ```
* - {py:obj}`sql <chartbook.formats.sql>`
  - ```{autodoc2-docstring} chartbook.formats.sql
    :summary:
    ```
* - {py:obj}`to_pandas <chartbook.formats.to_pandas>`
  - ```{autodoc2-docstring} chartbook.formats.to_pandas
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ENDINGS <chartbook.formats.ENDINGS>`
  - ```{autodoc2-docstring} chartbook.formats.ENDINGS
    :summary:
    ```
* - {py:obj}`FORMATS <chartbook.formats.FORMATS>`
  - ```{autodoc2-docstring} chartbook.formats.FORMATS
    :summary:
    ```
* - {py:obj}`NAMES <chartbook.formats.NAMES>`
  - ```{autodoc2-docstring} chartbook.formats.NAMES
    :summary:
    ```
* - {py:obj}`READ_ERRORS <chartbook.formats.READ_ERRORS>`
  - ```{autodoc2-docstring} chartbook.formats.READ_ERRORS
    :summary:
    ```
* - {py:obj}`READ_OPTIONS <chartbook.formats.READ_OPTIONS>`
  - ```{autodoc2-docstring} chartbook.formats.READ_OPTIONS
    :summary:
    ```
* - {py:obj}`SAMPLE_ROWS <chartbook.formats.SAMPLE_ROWS>`
  - ```{autodoc2-docstring} chartbook.formats.SAMPLE_ROWS
    :summary:
    ```
* - {py:obj}`TYPES <chartbook.formats.TYPES>`
  - ```{autodoc2-docstring} chartbook.formats.TYPES
    :summary:
    ```
````

### API

````{py:data} ENDINGS
:canonical: chartbook.formats.ENDINGS
:value: >
   None

```{autodoc2-docstring} chartbook.formats.ENDINGS
```

````

````{py:data} FORMATS
:canonical: chartbook.formats.FORMATS
:value: >
   ('parquet', 'csv', 'jsonl', 'ipc')

```{autodoc2-docstring} chartbook.formats.FORMATS
```

````

````{py:data} NAMES
:canonical: chartbook.formats.NAMES
:value: >
   None

```{autodoc2-docstring} chartbook.formats.NAMES
```

````

````{py:data} READ_ERRORS
:canonical: chartbook.formats.READ_ERRORS
:value: >
   ()

```{autodoc2-docstring} chartbook.formats.READ_ERRORS
```

````

````{py:data} READ_OPTIONS
:canonical: chartbook.formats.READ_OPTIONS
:value: >
   None

```{autodoc2-docstring} chartbook.formats.READ_OPTIONS
```

````

`````{py:class} Reading
:canonical: chartbook.formats.Reading

```{autodoc2-docstring} chartbook.formats.Reading
```

````{py:attribute} format
:canonical: chartbook.formats.Reading.format
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.formats.Reading.format
```

````

````{py:attribute} options
:canonical: chartbook.formats.Reading.options
:type: typing.Mapping
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.formats.Reading.options
```

````

````{py:attribute} said_by
:canonical: chartbook.formats.Reading.said_by
:type: str
:value: >
   'default'

```{autodoc2-docstring} chartbook.formats.Reading.said_by
```

````

`````

````{py:data} SAMPLE_ROWS
:canonical: chartbook.formats.SAMPLE_ROWS
:value: >
   20480

```{autodoc2-docstring} chartbook.formats.SAMPLE_ROWS
```

````

````{py:data} TYPES
:canonical: chartbook.formats.TYPES
:value: >
   None

```{autodoc2-docstring} chartbook.formats.TYPES
```

````

````{py:function} arrow_dataset(location)
:canonical: chartbook.formats.arrow_dataset

```{autodoc2-docstring} chartbook.formats.arrow_dataset
```
````

````{py:function} check_entry(entry: typing.Mapping, where: str) -> None
:canonical: chartbook.formats.check_entry

```{autodoc2-docstring} chartbook.formats.check_entry
```
````

````{py:function} declared(entry) -> dict
:canonical: chartbook.formats.declared

```{autodoc2-docstring} chartbook.formats.declared
```
````

````{py:function} ending_of(name: typing.Union[str, pathlib.Path]) -> typing.Optional[str]
:canonical: chartbook.formats.ending_of

```{autodoc2-docstring} chartbook.formats.ending_of
```
````

````{py:function} files_of(path: typing.Union[str, pathlib.Path], read: chartbook.formats.Reading, files=(), listed=()) -> list[pathlib.Path]
:canonical: chartbook.formats.files_of

```{autodoc2-docstring} chartbook.formats.files_of
```
````

````{py:function} format_of(path: typing.Union[str, pathlib.Path], declared=None) -> str
:canonical: chartbook.formats.format_of

```{autodoc2-docstring} chartbook.formats.format_of
```
````

````{py:function} format_of_name(name: typing.Union[str, pathlib.Path]) -> typing.Optional[str]
:canonical: chartbook.formats.format_of_name

```{autodoc2-docstring} chartbook.formats.format_of_name
```
````

````{py:function} handed(location)
:canonical: chartbook.formats.handed

```{autodoc2-docstring} chartbook.formats.handed
```
````

````{py:function} handed_name(location) -> str
:canonical: chartbook.formats.handed_name

```{autodoc2-docstring} chartbook.formats.handed_name
```
````

````{py:function} kept(location) -> dict
:canonical: chartbook.formats.kept

```{autodoc2-docstring} chartbook.formats.kept
```
````

````{py:function} reading(path: typing.Union[str, pathlib.Path], format: typing.Optional[str] = None, read_options: typing.Optional[typing.Mapping] = None, where: typing.Optional[str] = None) -> chartbook.formats.Reading
:canonical: chartbook.formats.reading

```{autodoc2-docstring} chartbook.formats.reading
```
````

````{py:function} reading_of(location, where: typing.Optional[str] = None) -> chartbook.formats.Reading
:canonical: chartbook.formats.reading_of

```{autodoc2-docstring} chartbook.formats.reading_of
```
````

````{py:function} scan(path: typing.Union[str, pathlib.Path], format: typing.Optional[str] = None, read_options: typing.Optional[typing.Mapping] = None, *, files=(), listed=(), where: typing.Optional[str] = None, public: bool = False)
:canonical: chartbook.formats.scan

```{autodoc2-docstring} chartbook.formats.scan
```
````

````{py:function} scan_location(location, where: typing.Optional[str] = None)
:canonical: chartbook.formats.scan_location

```{autodoc2-docstring} chartbook.formats.scan_location
```
````

````{py:function} sql(location) -> str
:canonical: chartbook.formats.sql

```{autodoc2-docstring} chartbook.formats.sql
```
````

````{py:function} to_pandas(location, where: typing.Optional[str] = None)
:canonical: chartbook.formats.to_pandas

```{autodoc2-docstring} chartbook.formats.to_pandas
```
````
