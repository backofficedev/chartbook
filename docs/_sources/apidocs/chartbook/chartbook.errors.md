# {py:mod}`chartbook.errors`

```{py:module} chartbook.errors
```

```{autodoc2-docstring} chartbook.errors
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ChartBookError <chartbook.errors.ChartBookError>`
  - ```{autodoc2-docstring} chartbook.errors.ChartBookError
    :summary:
    ```
* - {py:obj}`MissingFile <chartbook.errors.MissingFile>`
  - ```{autodoc2-docstring} chartbook.errors.MissingFile
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`handle_validation_error <chartbook.errors.handle_validation_error>`
  - ```{autodoc2-docstring} chartbook.errors.handle_validation_error
    :summary:
    ```
````

### API

````{py:exception} CatalogNotConfiguredError(settings_path: pathlib.Path)
:canonical: chartbook.errors.CatalogNotConfiguredError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.errors.CatalogNotConfiguredError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.CatalogNotConfiguredError.__init__
```

````

`````{py:class} ChartBookError
:canonical: chartbook.errors.ChartBookError

```{autodoc2-docstring} chartbook.errors.ChartBookError
```

````{py:method} exit_with_message() -> None
:canonical: chartbook.errors.ChartBookError.exit_with_message

```{autodoc2-docstring} chartbook.errors.ChartBookError.exit_with_message
```

````

````{py:attribute} field_name
:canonical: chartbook.errors.ChartBookError.field_name
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.errors.ChartBookError.field_name
```

````

````{py:attribute} file_path
:canonical: chartbook.errors.ChartBookError.file_path
:type: typing.Optional[pathlib.Path]
:value: >
   None

```{autodoc2-docstring} chartbook.errors.ChartBookError.file_path
```

````

````{py:method} format_message() -> str
:canonical: chartbook.errors.ChartBookError.format_message

```{autodoc2-docstring} chartbook.errors.ChartBookError.format_message
```

````

````{py:attribute} hint
:canonical: chartbook.errors.ChartBookError.hint
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.errors.ChartBookError.hint
```

````

````{py:attribute} invalid_value
:canonical: chartbook.errors.ChartBookError.invalid_value
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.errors.ChartBookError.invalid_value
```

````

````{py:attribute} message
:canonical: chartbook.errors.ChartBookError.message
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.errors.ChartBookError.message
```

````

`````

`````{py:class} MissingFile
:canonical: chartbook.errors.MissingFile

```{autodoc2-docstring} chartbook.errors.MissingFile
```

````{py:attribute} file_path
:canonical: chartbook.errors.MissingFile.file_path
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.errors.MissingFile.file_path
```

````

````{py:attribute} file_type
:canonical: chartbook.errors.MissingFile.file_type
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.errors.MissingFile.file_type
```

````

````{py:attribute} item_id
:canonical: chartbook.errors.MissingFile.item_id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.errors.MissingFile.item_id
```

````

````{py:attribute} pipeline_id
:canonical: chartbook.errors.MissingFile.pipeline_id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.errors.MissingFile.pipeline_id
```

````

`````

`````{py:exception} MissingSourceFilesError(missing_files: list[chartbook.errors.MissingFile])
:canonical: chartbook.errors.MissingSourceFilesError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.__init__
```

````{py:method} exit_with_message() -> None
:canonical: chartbook.errors.MissingSourceFilesError.exit_with_message

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.exit_with_message
```

````

````{py:method} format_cli_message() -> str
:canonical: chartbook.errors.MissingSourceFilesError.format_cli_message

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.format_cli_message
```

````

````{py:method} format_skip_warnings() -> list[str]
:canonical: chartbook.errors.MissingSourceFilesError.format_skip_warnings

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.format_skip_warnings
```

````

````{py:method} format_warnings() -> list[str]
:canonical: chartbook.errors.MissingSourceFilesError.format_warnings

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.format_warnings
```

````

````{py:method} get_pipelines_to_skip() -> set[str]
:canonical: chartbook.errors.MissingSourceFilesError.get_pipelines_to_skip

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.get_pipelines_to_skip
```

````

`````

````{py:exception} ProjectRootNotFoundError(start_path: pathlib.Path, markers: tuple[str, ...], max_levels: int)
:canonical: chartbook.errors.ProjectRootNotFoundError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.errors.ProjectRootNotFoundError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.ProjectRootNotFoundError.__init__
```

````

`````{py:exception} ValidationError(message: str, field_name: typing.Optional[str] = None, invalid_value: typing.Optional[str] = None, hint: typing.Optional[str] = None)
:canonical: chartbook.errors.ValidationError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.errors.ValidationError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.ValidationError.__init__
```

````{py:method} to_chartbook_error(file_path: typing.Optional[pathlib.Path] = None) -> chartbook.errors.ChartBookError
:canonical: chartbook.errors.ValidationError.to_chartbook_error

```{autodoc2-docstring} chartbook.errors.ValidationError.to_chartbook_error
```

````

`````

````{py:function} handle_validation_error(error: chartbook.errors.ValidationError, config_path: pathlib.Path) -> None
:canonical: chartbook.errors.handle_validation_error

```{autodoc2-docstring} chartbook.errors.handle_validation_error
```
````
