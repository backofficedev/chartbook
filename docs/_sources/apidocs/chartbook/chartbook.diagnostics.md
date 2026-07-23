# {py:mod}`chartbook.diagnostics`

```{py:module} chartbook.diagnostics
```

```{autodoc2-docstring} chartbook.diagnostics
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DiagnosticRow <chartbook.diagnostics.DiagnosticRow>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_diagnostics <chartbook.diagnostics.build_diagnostics>`
  - ```{autodoc2-docstring} chartbook.diagnostics.build_diagnostics
    :summary:
    ```
* - {py:obj}`generate_metadata_diagnostics <chartbook.diagnostics.generate_metadata_diagnostics>`
  - ```{autodoc2-docstring} chartbook.diagnostics.generate_metadata_diagnostics
    :summary:
    ```
* - {py:obj}`get_active_policy <chartbook.diagnostics.get_active_policy>`
  - ```{autodoc2-docstring} chartbook.diagnostics.get_active_policy
    :summary:
    ```
* - {py:obj}`write_diagnostics_csv <chartbook.diagnostics.write_diagnostics_csv>`
  - ```{autodoc2-docstring} chartbook.diagnostics.write_diagnostics_csv
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CHART_FIELDS <chartbook.diagnostics.CHART_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.CHART_FIELDS
    :summary:
    ```
* - {py:obj}`DATAFRAME_FIELDS <chartbook.diagnostics.DATAFRAME_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_FIELDS
    :summary:
    ```
* - {py:obj}`DEFAULT_REQUIRED_FIELDS <chartbook.diagnostics.DEFAULT_REQUIRED_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DEFAULT_REQUIRED_FIELDS
    :summary:
    ```
* - {py:obj}`DOCS_FIELDS <chartbook.diagnostics.DOCS_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DOCS_FIELDS
    :summary:
    ```
* - {py:obj}`NOTEBOOK_FIELDS <chartbook.diagnostics.NOTEBOOK_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.NOTEBOOK_FIELDS
    :summary:
    ```
* - {py:obj}`OPTIONAL_CHART_FIELDS <chartbook.diagnostics.OPTIONAL_CHART_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.OPTIONAL_CHART_FIELDS
    :summary:
    ```
* - {py:obj}`PROJECT_FIELDS <chartbook.diagnostics.PROJECT_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.PROJECT_FIELDS
    :summary:
    ```
````

### API

````{py:data} CHART_FIELDS
:canonical: chartbook.diagnostics.CHART_FIELDS
:type: list[str]
:value: >
   ['name', 'description', 'dataframe', 'tags', 'frequency', 'observation_period', 'release_lag', 'rele...

```{autodoc2-docstring} chartbook.diagnostics.CHART_FIELDS
```

````

````{py:data} DATAFRAME_FIELDS
:canonical: chartbook.diagnostics.DATAFRAME_FIELDS
:type: list[str]
:value: >
   ['name', 'description', 'sources', 'providers', 'provider_links', 'tags', 'pull_method', 'path']

```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_FIELDS
```

````

````{py:data} DEFAULT_REQUIRED_FIELDS
:canonical: chartbook.diagnostics.DEFAULT_REQUIRED_FIELDS
:type: dict[str, list[str]]
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DEFAULT_REQUIRED_FIELDS
```

````

````{py:data} DOCS_FIELDS
:canonical: chartbook.diagnostics.DOCS_FIELDS
:type: tuple[str, str]
:value: >
   ('docs_path', 'docs')

```{autodoc2-docstring} chartbook.diagnostics.DOCS_FIELDS
```

````

`````{py:class} DiagnosticRow
:canonical: chartbook.diagnostics.DiagnosticRow

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow
```

````{py:attribute} identifier
:canonical: chartbook.diagnostics.DiagnosticRow.identifier
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.identifier
```

````

````{py:attribute} metadata_complete
:canonical: chartbook.diagnostics.DiagnosticRow.metadata_complete
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.metadata_complete
```

````

````{py:attribute} missing_fields
:canonical: chartbook.diagnostics.DiagnosticRow.missing_fields
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.missing_fields
```

````

````{py:attribute} object_name
:canonical: chartbook.diagnostics.DiagnosticRow.object_name
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.object_name
```

````

````{py:attribute} object_type
:canonical: chartbook.diagnostics.DiagnosticRow.object_type
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.object_type
```

````

````{py:attribute} page_link
:canonical: chartbook.diagnostics.DiagnosticRow.page_link
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.page_link
```

````

````{py:attribute} pipeline_id
:canonical: chartbook.diagnostics.DiagnosticRow.pipeline_id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.pipeline_id
```

````

````{py:method} to_dict() -> dict[str, typing.Any]
:canonical: chartbook.diagnostics.DiagnosticRow.to_dict

```{autodoc2-docstring} chartbook.diagnostics.DiagnosticRow.to_dict
```

````

`````

````{py:data} NOTEBOOK_FIELDS
:canonical: chartbook.diagnostics.NOTEBOOK_FIELDS
:type: list[str]
:value: >
   []

```{autodoc2-docstring} chartbook.diagnostics.NOTEBOOK_FIELDS
```

````

````{py:data} OPTIONAL_CHART_FIELDS
:canonical: chartbook.diagnostics.OPTIONAL_CHART_FIELDS
:type: list[str]
:value: >
   ['series']

```{autodoc2-docstring} chartbook.diagnostics.OPTIONAL_CHART_FIELDS
```

````

````{py:data} PROJECT_FIELDS
:canonical: chartbook.diagnostics.PROJECT_FIELDS
:type: list[str]
:value: >
   ['name', 'description', 'maintainer', 'contributors', 'build', 'os_compatibility', 'repo_url']

```{autodoc2-docstring} chartbook.diagnostics.PROJECT_FIELDS
```

````

````{py:function} build_diagnostics(manifest: dict[str, typing.Any]) -> list[chartbook.diagnostics.DiagnosticRow]
:canonical: chartbook.diagnostics.build_diagnostics

```{autodoc2-docstring} chartbook.diagnostics.build_diagnostics
```
````

````{py:function} generate_metadata_diagnostics(manifest: dict[str, typing.Any], docs_build_dir: pathlib.Path) -> list[chartbook.diagnostics.DiagnosticRow]
:canonical: chartbook.diagnostics.generate_metadata_diagnostics

```{autodoc2-docstring} chartbook.diagnostics.generate_metadata_diagnostics
```
````

````{py:function} get_active_policy(manifest: dict[str, typing.Any]) -> dict[str, typing.Any]
:canonical: chartbook.diagnostics.get_active_policy

```{autodoc2-docstring} chartbook.diagnostics.get_active_policy
```
````

````{py:function} write_diagnostics_csv(diagnostics: list[chartbook.diagnostics.DiagnosticRow], output_path: pathlib.Path) -> None
:canonical: chartbook.diagnostics.write_diagnostics_csv

```{autodoc2-docstring} chartbook.diagnostics.write_diagnostics_csv
```
````
