# {py:mod}`chartbook.backends.databricks`

```{py:module} chartbook.backends.databricks
```

```{autodoc2-docstring} chartbook.backends.databricks
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Connection <chartbook.backends.databricks.Connection>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.Connection
    :summary:
    ```
* - {py:obj}`DatabricksBackend <chartbook.backends.databricks.DatabricksBackend>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend
    :summary:
    ```
* - {py:obj}`DatabricksURL <chartbook.backends.databricks.DatabricksURL>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`connection_for <chartbook.backends.databricks.connection_for>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.connection_for
    :summary:
    ```
* - {py:obj}`host_of <chartbook.backends.databricks.host_of>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.host_of
    :summary:
    ```
* - {py:obj}`parse_url <chartbook.backends.databricks.parse_url>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.parse_url
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AUTH <chartbook.backends.databricks.AUTH>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.AUTH
    :summary:
    ```
* - {py:obj}`BATCH_ROWS <chartbook.backends.databricks.BATCH_ROWS>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.BATCH_ROWS
    :summary:
    ```
* - {py:obj}`URL_OPTIONS <chartbook.backends.databricks.URL_OPTIONS>`
  - ```{autodoc2-docstring} chartbook.backends.databricks.URL_OPTIONS
    :summary:
    ```
````

### API

````{py:data} AUTH
:canonical: chartbook.backends.databricks.AUTH
:value: >
   ('token', 'oauth')

```{autodoc2-docstring} chartbook.backends.databricks.AUTH
```

````

````{py:data} BATCH_ROWS
:canonical: chartbook.backends.databricks.BATCH_ROWS
:value: >
   100000

```{autodoc2-docstring} chartbook.backends.databricks.BATCH_ROWS
```

````

`````{py:class} Connection
:canonical: chartbook.backends.databricks.Connection

```{autodoc2-docstring} chartbook.backends.databricks.Connection
```

````{py:attribute} catalog
:canonical: chartbook.backends.databricks.Connection.catalog
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.catalog
```

````

````{py:attribute} host
:canonical: chartbook.backends.databricks.Connection.host
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.host
```

````

````{py:attribute} http_path
:canonical: chartbook.backends.databricks.Connection.http_path
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.http_path
```

````

````{py:attribute} oauth
:canonical: chartbook.backends.databricks.Connection.oauth
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.oauth
```

````

````{py:attribute} schema
:canonical: chartbook.backends.databricks.Connection.schema
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.schema
```

````

````{py:attribute} token
:canonical: chartbook.backends.databricks.Connection.token
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.backends.databricks.Connection.token
```

````

`````

`````{py:class} DatabricksBackend(url: str, source: typing.Optional[str] = None)
:canonical: chartbook.backends.databricks.DatabricksBackend

Bases: {py:obj}`chartbook.backends.Backend`

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.__init__
```

````{py:method} check_url(url: str) -> None
:canonical: chartbook.backends.databricks.DatabricksBackend.check_url
:staticmethod:

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.check_url
```

````

````{py:method} connect()
:canonical: chartbook.backends.databricks.DatabricksBackend.connect

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.connect
```

````

````{py:method} describe(location: chartbook.resolve.Location) -> tuple[list[dict], int]
:canonical: chartbook.backends.databricks.DatabricksBackend.describe

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.describe
```

````

````{py:method} engine() -> tuple
:canonical: chartbook.backends.databricks.DatabricksBackend.engine

````

````{py:attribute} name
:canonical: chartbook.backends.databricks.DatabricksBackend.name
:value: >
   'databricks'

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.name
```

````

````{py:method} ref(location: chartbook.resolve.Location) -> str
:canonical: chartbook.backends.databricks.DatabricksBackend.ref

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.ref
```

````

````{py:method} span(location: chartbook.resolve.Location, column: str) -> tuple
:canonical: chartbook.backends.databricks.DatabricksBackend.span

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.span
```

````

````{py:method} sql(query: str)
:canonical: chartbook.backends.databricks.DatabricksBackend.sql

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksBackend.sql
```

````

`````

`````{py:class} DatabricksURL
:canonical: chartbook.backends.databricks.DatabricksURL

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL
```

````{py:attribute} auth
:canonical: chartbook.backends.databricks.DatabricksURL.auth
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.auth
```

````

````{py:attribute} catalog
:canonical: chartbook.backends.databricks.DatabricksURL.catalog
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.catalog
```

````

````{py:attribute} host
:canonical: chartbook.backends.databricks.DatabricksURL.host
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.host
```

````

````{py:attribute} http_path
:canonical: chartbook.backends.databricks.DatabricksURL.http_path
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.http_path
```

````

````{py:attribute} schema
:canonical: chartbook.backends.databricks.DatabricksURL.schema
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.schema
```

````

````{py:attribute} token
:canonical: chartbook.backends.databricks.DatabricksURL.token
:type: str
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.backends.databricks.DatabricksURL.token
```

````

`````

````{py:data} URL_OPTIONS
:canonical: chartbook.backends.databricks.URL_OPTIONS
:value: >
   ('http_path', 'catalog', 'schema', 'auth')

```{autodoc2-docstring} chartbook.backends.databricks.URL_OPTIONS
```

````

````{py:function} connection_for(source: typing.Optional[str], public_url: str) -> chartbook.backends.databricks.Connection
:canonical: chartbook.backends.databricks.connection_for

```{autodoc2-docstring} chartbook.backends.databricks.connection_for
```
````

````{py:function} host_of(text: str) -> str
:canonical: chartbook.backends.databricks.host_of

```{autodoc2-docstring} chartbook.backends.databricks.host_of
```
````

````{py:function} parse_url(url: str) -> chartbook.backends.databricks.DatabricksURL
:canonical: chartbook.backends.databricks.parse_url

```{autodoc2-docstring} chartbook.backends.databricks.parse_url
```
````
