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
* - {py:obj}`write_diagnostics_csv <chartbook.diagnostics.write_diagnostics_csv>`
  - ```{autodoc2-docstring} chartbook.diagnostics.write_diagnostics_csv
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CHART_DOCS_FIELDS <chartbook.diagnostics.CHART_DOCS_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.CHART_DOCS_FIELDS
    :summary:
    ```
* - {py:obj}`CHART_FIELDS <chartbook.diagnostics.CHART_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.CHART_FIELDS
    :summary:
    ```
* - {py:obj}`DATAFRAME_DOCS_FIELDS <chartbook.diagnostics.DATAFRAME_DOCS_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_DOCS_FIELDS
    :summary:
    ```
* - {py:obj}`DATAFRAME_FIELDS <chartbook.diagnostics.DATAFRAME_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_FIELDS
    :summary:
    ```
* - {py:obj}`OPTIONAL_CHART_FIELDS <chartbook.diagnostics.OPTIONAL_CHART_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.OPTIONAL_CHART_FIELDS
    :summary:
    ```
* - {py:obj}`PIPELINE_FIELDS <chartbook.diagnostics.PIPELINE_FIELDS>`
  - ```{autodoc2-docstring} chartbook.diagnostics.PIPELINE_FIELDS
    :summary:
    ```
````

### API

````{py:data} CHART_DOCS_FIELDS
:canonical: chartbook.diagnostics.CHART_DOCS_FIELDS
:type: tuple[str, str]
:value: >
   ('chart_docs_path', 'chart_docs_str')

```{autodoc2-docstring} chartbook.diagnostics.CHART_DOCS_FIELDS
```

````

````{py:data} CHART_FIELDS
:canonical: chartbook.diagnostics.CHART_FIELDS
:type: list[str]
:value: >
   ['chart_name', 'short_description_chart', 'dataframe_id', 'topic_tags', 'data_frequency', 'observati...

```{autodoc2-docstring} chartbook.diagnostics.CHART_FIELDS
```

````

````{py:data} DATAFRAME_DOCS_FIELDS
:canonical: chartbook.diagnostics.DATAFRAME_DOCS_FIELDS
:type: tuple[str, str]
:value: >
   ('dataframe_docs_path', 'dataframe_docs_str')

```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_DOCS_FIELDS
```

````

````{py:data} DATAFRAME_FIELDS
:canonical: chartbook.diagnostics.DATAFRAME_FIELDS
:type: list[str]
:value: >
   ['dataframe_name', 'short_description_df', 'data_sources', 'data_providers', 'links_to_data_provider...

```{autodoc2-docstring} chartbook.diagnostics.DATAFRAME_FIELDS
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

````{py:data} OPTIONAL_CHART_FIELDS
:canonical: chartbook.diagnostics.OPTIONAL_CHART_FIELDS
:type: list[str]
:value: >
   ['data_series']

```{autodoc2-docstring} chartbook.diagnostics.OPTIONAL_CHART_FIELDS
```

````

````{py:data} PIPELINE_FIELDS
:canonical: chartbook.diagnostics.PIPELINE_FIELDS
:type: list[str]
:value: >
   ['id', 'pipeline_name', 'pipeline_description', 'lead_pipeline_developer', 'contributors', 'build_co...

```{autodoc2-docstring} chartbook.diagnostics.PIPELINE_FIELDS
```

````

````{py:function} build_diagnostics(manifest: dict[str, typing.Any]) -> list[chartbook.diagnostics.DiagnosticRow]
:canonical: chartbook.diagnostics.build_diagnostics

```{autodoc2-docstring} chartbook.diagnostics.build_diagnostics
```
````

````{py:function} generate_metadata_diagnostics(manifest: dict[str, typing.Any], docs_build_dir: pathlib.Path) -> pathlib.Path
:canonical: chartbook.diagnostics.generate_metadata_diagnostics

```{autodoc2-docstring} chartbook.diagnostics.generate_metadata_diagnostics
```
````

````{py:function} write_diagnostics_csv(diagnostics: list[chartbook.diagnostics.DiagnosticRow], output_path: pathlib.Path) -> None
:canonical: chartbook.diagnostics.write_diagnostics_csv

```{autodoc2-docstring} chartbook.diagnostics.write_diagnostics_csv
```
````
