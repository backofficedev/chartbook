# {py:mod}`chartbook.backends`

```{py:module} chartbook.backends
```

```{autodoc2-docstring} chartbook.backends
:allowtitles:
```

## Submodules

```{toctree}
:titlesonly:
:maxdepth: 1

chartbook.backends.databricks
```

## Package Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Backend <chartbook.backends.Backend>`
  - ```{autodoc2-docstring} chartbook.backends.Backend
    :summary:
    ```
* - {py:obj}`DuckDBBackend <chartbook.backends.DuckDBBackend>`
  - ```{autodoc2-docstring} chartbook.backends.DuckDBBackend
    :summary:
    ```
* - {py:obj}`ParquetBackend <chartbook.backends.ParquetBackend>`
  - ```{autodoc2-docstring} chartbook.backends.ParquetBackend
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`backend_class <chartbook.backends.backend_class>`
  - ```{autodoc2-docstring} chartbook.backends.backend_class
    :summary:
    ```
* - {py:obj}`backend_for <chartbook.backends.backend_for>`
  - ```{autodoc2-docstring} chartbook.backends.backend_for
    :summary:
    ```
* - {py:obj}`backend_names <chartbook.backends.backend_names>`
  - ```{autodoc2-docstring} chartbook.backends.backend_names
    :summary:
    ```
* - {py:obj}`check_backend <chartbook.backends.check_backend>`
  - ```{autodoc2-docstring} chartbook.backends.check_backend
    :summary:
    ```
* - {py:obj}`check_url <chartbook.backends.check_url>`
  - ```{autodoc2-docstring} chartbook.backends.check_url
    :summary:
    ```
* - {py:obj}`duckdb_path <chartbook.backends.duckdb_path>`
  - ```{autodoc2-docstring} chartbook.backends.duckdb_path
    :summary:
    ```
* - {py:obj}`machine_source_url <chartbook.backends.machine_source_url>`
  - ```{autodoc2-docstring} chartbook.backends.machine_source_url
    :summary:
    ```
* - {py:obj}`open_backend <chartbook.backends.open_backend>`
  - ```{autodoc2-docstring} chartbook.backends.open_backend
    :summary:
    ```
* - {py:obj}`quote_identifier <chartbook.backends.quote_identifier>`
  - ```{autodoc2-docstring} chartbook.backends.quote_identifier
    :summary:
    ```
* - {py:obj}`quote_literal <chartbook.backends.quote_literal>`
  - ```{autodoc2-docstring} chartbook.backends.quote_literal
    :summary:
    ```
* - {py:obj}`refuse_in_an_untrusted_build <chartbook.backends.refuse_in_an_untrusted_build>`
  - ```{autodoc2-docstring} chartbook.backends.refuse_in_an_untrusted_build
    :summary:
    ```
* - {py:obj}`scheme_of <chartbook.backends.scheme_of>`
  - ```{autodoc2-docstring} chartbook.backends.scheme_of
    :summary:
    ```
* - {py:obj}`source_env_var <chartbook.backends.source_env_var>`
  - ```{autodoc2-docstring} chartbook.backends.source_env_var
    :summary:
    ```
* - {py:obj}`source_url <chartbook.backends.source_url>`
  - ```{autodoc2-docstring} chartbook.backends.source_url
    :summary:
    ```
* - {py:obj}`subselect <chartbook.backends.subselect>`
  - ```{autodoc2-docstring} chartbook.backends.subselect
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BACKEND_PLUGIN_GROUP <chartbook.backends.BACKEND_PLUGIN_GROUP>`
  - ```{autodoc2-docstring} chartbook.backends.BACKEND_PLUGIN_GROUP
    :summary:
    ```
* - {py:obj}`EXTRAS <chartbook.backends.EXTRAS>`
  - ```{autodoc2-docstring} chartbook.backends.EXTRAS
    :summary:
    ```
* - {py:obj}`MEMORY_URL <chartbook.backends.MEMORY_URL>`
  - ```{autodoc2-docstring} chartbook.backends.MEMORY_URL
    :summary:
    ```
* - {py:obj}`SOURCES_FILE <chartbook.backends.SOURCES_FILE>`
  - ```{autodoc2-docstring} chartbook.backends.SOURCES_FILE
    :summary:
    ```
* - {py:obj}`SOURCE_ENV_PREFIX <chartbook.backends.SOURCE_ENV_PREFIX>`
  - ```{autodoc2-docstring} chartbook.backends.SOURCE_ENV_PREFIX
    :summary:
    ```
````

### API

````{py:data} BACKEND_PLUGIN_GROUP
:canonical: chartbook.backends.BACKEND_PLUGIN_GROUP
:value: >
   'chartbook.backends'

```{autodoc2-docstring} chartbook.backends.BACKEND_PLUGIN_GROUP
```

````

`````{py:class} Backend(url: str, source: typing.Optional[str] = None)
:canonical: chartbook.backends.Backend

```{autodoc2-docstring} chartbook.backends.Backend
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.backends.Backend.__init__
```

````{py:method} check_url(url: str) -> None
:canonical: chartbook.backends.Backend.check_url
:staticmethod:

```{autodoc2-docstring} chartbook.backends.Backend.check_url
```

````

````{py:method} connect()
:canonical: chartbook.backends.Backend.connect
:abstractmethod:

```{autodoc2-docstring} chartbook.backends.Backend.connect
```

````

````{py:method} describe(location: chartbook.resolve.Location) -> tuple[list[dict], int]
:canonical: chartbook.backends.Backend.describe
:abstractmethod:

```{autodoc2-docstring} chartbook.backends.Backend.describe
```

````

````{py:method} engine() -> tuple
:canonical: chartbook.backends.Backend.engine

```{autodoc2-docstring} chartbook.backends.Backend.engine
```

````

````{py:attribute} name
:canonical: chartbook.backends.Backend.name
:type: typing.ClassVar[str]
:value: >
   None

```{autodoc2-docstring} chartbook.backends.Backend.name
```

````

````{py:attribute} reads_files
:canonical: chartbook.backends.Backend.reads_files
:type: typing.ClassVar[bool]
:value: >
   False

```{autodoc2-docstring} chartbook.backends.Backend.reads_files
```

````

````{py:method} ref(location: chartbook.resolve.Location) -> str
:canonical: chartbook.backends.Backend.ref
:abstractmethod:

```{autodoc2-docstring} chartbook.backends.Backend.ref
```

````

````{py:method} scan(location: chartbook.resolve.Location)
:canonical: chartbook.backends.Backend.scan

```{autodoc2-docstring} chartbook.backends.Backend.scan
```

````

````{py:method} span(location: chartbook.resolve.Location, column: str) -> tuple
:canonical: chartbook.backends.Backend.span
:abstractmethod:

```{autodoc2-docstring} chartbook.backends.Backend.span
```

````

````{py:method} sql(query: str, arrow: typing.Optional[dict] = None)
:canonical: chartbook.backends.Backend.sql
:abstractmethod:

```{autodoc2-docstring} chartbook.backends.Backend.sql
```

````

`````

````{py:exception} BackendError()
:canonical: chartbook.backends.BackendError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.backends.BackendError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.backends.BackendError.__init__
```

````

`````{py:class} DuckDBBackend(url: str, source: typing.Optional[str] = None, connection=None)
:canonical: chartbook.backends.DuckDBBackend

Bases: {py:obj}`chartbook.backends.Backend`

```{autodoc2-docstring} chartbook.backends.DuckDBBackend
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.__init__
```

````{py:method} check_url(url: str) -> None
:canonical: chartbook.backends.DuckDBBackend.check_url
:staticmethod:

````

````{py:method} connect()
:canonical: chartbook.backends.DuckDBBackend.connect

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.connect
```

````

````{py:method} describe(location: chartbook.resolve.Location) -> tuple[list[dict], int]
:canonical: chartbook.backends.DuckDBBackend.describe

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.describe
```

````

````{py:method} engine() -> tuple
:canonical: chartbook.backends.DuckDBBackend.engine

````

````{py:attribute} name
:canonical: chartbook.backends.DuckDBBackend.name
:value: >
   'duckdb'

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.name
```

````

````{py:attribute} reads_files
:canonical: chartbook.backends.DuckDBBackend.reads_files
:value: >
   True

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.reads_files
```

````

````{py:method} ref(location: chartbook.resolve.Location) -> str
:canonical: chartbook.backends.DuckDBBackend.ref

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.ref
```

````

````{py:method} scratch() -> chartbook.backends.DuckDBBackend
:canonical: chartbook.backends.DuckDBBackend.scratch
:classmethod:

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.scratch
```

````

````{py:method} span(location: chartbook.resolve.Location, column: str) -> tuple
:canonical: chartbook.backends.DuckDBBackend.span

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.span
```

````

````{py:method} sql(query: str, arrow: typing.Optional[dict] = None)
:canonical: chartbook.backends.DuckDBBackend.sql

```{autodoc2-docstring} chartbook.backends.DuckDBBackend.sql
```

````

`````

````{py:data} EXTRAS
:canonical: chartbook.backends.EXTRAS
:value: >
   None

```{autodoc2-docstring} chartbook.backends.EXTRAS
```

````

````{py:data} MEMORY_URL
:canonical: chartbook.backends.MEMORY_URL
:value: >
   'duckdb:///:memory:'

```{autodoc2-docstring} chartbook.backends.MEMORY_URL
```

````

`````{py:class} ParquetBackend
:canonical: chartbook.backends.ParquetBackend

```{autodoc2-docstring} chartbook.backends.ParquetBackend
```

````{py:attribute} name
:canonical: chartbook.backends.ParquetBackend.name
:value: >
   'parquet'

```{autodoc2-docstring} chartbook.backends.ParquetBackend.name
```

````

````{py:method} ref(location: chartbook.resolve.FileLocation) -> str
:canonical: chartbook.backends.ParquetBackend.ref
:staticmethod:

```{autodoc2-docstring} chartbook.backends.ParquetBackend.ref
```

````

````{py:method} scan(location: chartbook.resolve.FileLocation)
:canonical: chartbook.backends.ParquetBackend.scan
:staticmethod:

```{autodoc2-docstring} chartbook.backends.ParquetBackend.scan
```

````

`````

````{py:data} SOURCES_FILE
:canonical: chartbook.backends.SOURCES_FILE
:value: >
   'sources.toml'

```{autodoc2-docstring} chartbook.backends.SOURCES_FILE
```

````

````{py:data} SOURCE_ENV_PREFIX
:canonical: chartbook.backends.SOURCE_ENV_PREFIX
:value: >
   'CHARTBOOK_SOURCE_'

```{autodoc2-docstring} chartbook.backends.SOURCE_ENV_PREFIX
```

````

````{py:function} backend_class(name: str) -> typing.Optional[type]
:canonical: chartbook.backends.backend_class

```{autodoc2-docstring} chartbook.backends.backend_class
```
````

````{py:function} backend_for(location: chartbook.resolve.Location)
:canonical: chartbook.backends.backend_for

```{autodoc2-docstring} chartbook.backends.backend_for
```
````

````{py:function} backend_names() -> list[str]
:canonical: chartbook.backends.backend_names

```{autodoc2-docstring} chartbook.backends.backend_names
```
````

````{py:function} check_backend(name: str, where: str) -> None
:canonical: chartbook.backends.check_backend

```{autodoc2-docstring} chartbook.backends.check_backend
```
````

````{py:function} check_url(url: str, backend: str, where: str) -> None
:canonical: chartbook.backends.check_url

```{autodoc2-docstring} chartbook.backends.check_url
```
````

````{py:function} duckdb_path(url: str, manifest_dir: typing.Union[str, pathlib.Path]) -> str
:canonical: chartbook.backends.duckdb_path

```{autodoc2-docstring} chartbook.backends.duckdb_path
```
````

````{py:function} machine_source_url(name: str) -> typing.Optional[str]
:canonical: chartbook.backends.machine_source_url

```{autodoc2-docstring} chartbook.backends.machine_source_url
```
````

````{py:function} open_backend(name: str, url: str, source: typing.Optional[str] = None) -> chartbook.backends.Backend
:canonical: chartbook.backends.open_backend

```{autodoc2-docstring} chartbook.backends.open_backend
```
````

````{py:function} quote_identifier(identifier: str, quote: str = '"') -> str
:canonical: chartbook.backends.quote_identifier

```{autodoc2-docstring} chartbook.backends.quote_identifier
```
````

````{py:function} quote_literal(text: str) -> str
:canonical: chartbook.backends.quote_literal

```{autodoc2-docstring} chartbook.backends.quote_literal
```
````

````{py:function} refuse_in_an_untrusted_build() -> None
:canonical: chartbook.backends.refuse_in_an_untrusted_build

```{autodoc2-docstring} chartbook.backends.refuse_in_an_untrusted_build
```
````

````{py:function} scheme_of(url: str) -> str
:canonical: chartbook.backends.scheme_of

```{autodoc2-docstring} chartbook.backends.scheme_of
```
````

````{py:function} source_env_var(name: str) -> str
:canonical: chartbook.backends.source_env_var

```{autodoc2-docstring} chartbook.backends.source_env_var
```
````

````{py:function} source_url(name: str, manifest_url: str) -> str
:canonical: chartbook.backends.source_url

```{autodoc2-docstring} chartbook.backends.source_url
```
````

````{py:function} subselect(sql: str) -> str
:canonical: chartbook.backends.subselect

```{autodoc2-docstring} chartbook.backends.subselect
```
````
