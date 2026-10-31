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

````{py:exception} AssetNotDeclaredError(name: str, manifest_path: pathlib.Path, declared: dict[str, list[str]], kind: str = DEFAULT_KIND, example_path: typing.Optional[str] = None)
:canonical: chartbook.errors.AssetNotDeclaredError

Bases: {py:obj}`LookupError`

```{autodoc2-docstring} chartbook.errors.AssetNotDeclaredError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.AssetNotDeclaredError.__init__
```

````

````{py:exception} AssetNotPinnedError(asset: str, reason: str, message: str)
:canonical: chartbook.errors.AssetNotPinnedError

Bases: {py:obj}`LookupError`

```{autodoc2-docstring} chartbook.errors.AssetNotPinnedError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.AssetNotPinnedError.__init__
```

````

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

````{py:exception} DependencyNotDeclaredError(reference: str, pipeline: str, manifest_path: pathlib.Path, declared: list[str], found_at: typing.Optional[tuple[str, typing.Optional[str]]] = None, known: typing.Mapping[str, typing.Optional[str]] = {})
:canonical: chartbook.errors.DependencyNotDeclaredError

Bases: {py:obj}`LookupError`

```{autodoc2-docstring} chartbook.errors.DependencyNotDeclaredError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.DependencyNotDeclaredError.__init__
```

````

````{py:exception} ManifestNotFoundError(start_dirs: list[pathlib.Path])
:canonical: chartbook.errors.ManifestNotFoundError

Bases: {py:obj}`FileNotFoundError`

```{autodoc2-docstring} chartbook.errors.ManifestNotFoundError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.ManifestNotFoundError.__init__
```

````

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

`````{py:exception} MissingSourceFilesError(missing_files: list[chartbook.errors.MissingFile], hint: typing.Optional[list[str]] = None)
:canonical: chartbook.errors.MissingSourceFilesError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.__init__
```

````{py:attribute} DEFAULT_HINT
:canonical: chartbook.errors.MissingSourceFilesError.DEFAULT_HINT
:value: >
   ('Ensure these files exist or update the paths in chartbook.toml.', 'Use --no-strict to skip affecte...

```{autodoc2-docstring} chartbook.errors.MissingSourceFilesError.DEFAULT_HINT
```

````

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

````{py:exception} UnreadableTableError(path, format: str, message: str)
:canonical: chartbook.errors.UnreadableTableError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.errors.UnreadableTableError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.UnreadableTableError.__init__
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

````{py:exception} VersionNotFoundError(asset: str, rev: str, reason: str, message: str)
:canonical: chartbook.errors.VersionNotFoundError

Bases: {py:obj}`LookupError`

```{autodoc2-docstring} chartbook.errors.VersionNotFoundError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.errors.VersionNotFoundError.__init__
```

````

````{py:function} handle_validation_error(error: chartbook.errors.ValidationError, config_path: pathlib.Path) -> None
:canonical: chartbook.errors.handle_validation_error

```{autodoc2-docstring} chartbook.errors.handle_validation_error
```
````
