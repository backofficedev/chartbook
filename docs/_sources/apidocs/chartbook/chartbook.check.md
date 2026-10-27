# {py:mod}`chartbook.check`

```{py:module} chartbook.check
```

```{autodoc2-docstring} chartbook.check
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Problem <chartbook.check.Problem>`
  - ```{autodoc2-docstring} chartbook.check.Problem
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`check_build_tool <chartbook.check.check_build_tool>`
  - ```{autodoc2-docstring} chartbook.check.check_build_tool
    :summary:
    ```
* - {py:obj}`check_dependencies <chartbook.check.check_dependencies>`
  - ```{autodoc2-docstring} chartbook.check.check_dependencies
    :summary:
    ```
* - {py:obj}`check_dependency_cycles <chartbook.check.check_dependency_cycles>`
  - ```{autodoc2-docstring} chartbook.check.check_dependency_cycles
    :summary:
    ```
* - {py:obj}`check_ids <chartbook.check.check_ids>`
  - ```{autodoc2-docstring} chartbook.check.check_ids
    :summary:
    ```
* - {py:obj}`check_licenses <chartbook.check.check_licenses>`
  - ```{autodoc2-docstring} chartbook.check.check_licenses
    :summary:
    ```
* - {py:obj}`check_model_labels <chartbook.check.check_model_labels>`
  - ```{autodoc2-docstring} chartbook.check.check_model_labels
    :summary:
    ```
* - {py:obj}`check_model_lineage <chartbook.check.check_model_lineage>`
  - ```{autodoc2-docstring} chartbook.check.check_model_lineage
    :summary:
    ```
* - {py:obj}`check_model_metrics <chartbook.check.check_model_metrics>`
  - ```{autodoc2-docstring} chartbook.check.check_model_metrics
    :summary:
    ```
* - {py:obj}`check_model_staleness <chartbook.check.check_model_staleness>`
  - ```{autodoc2-docstring} chartbook.check.check_model_staleness
    :summary:
    ```
* - {py:obj}`check_paths <chartbook.check.check_paths>`
  - ```{autodoc2-docstring} chartbook.check.check_paths
    :summary:
    ```
* - {py:obj}`check_required_fields <chartbook.check.check_required_fields>`
  - ```{autodoc2-docstring} chartbook.check.check_required_fields
    :summary:
    ```
* - {py:obj}`check_sources <chartbook.check.check_sources>`
  - ```{autodoc2-docstring} chartbook.check.check_sources
    :summary:
    ```
* - {py:obj}`display_path <chartbook.check.display_path>`
  - ```{autodoc2-docstring} chartbook.check.display_path
    :summary:
    ```
* - {py:obj}`load_policy <chartbook.check.load_policy>`
  - ```{autodoc2-docstring} chartbook.check.load_policy
    :summary:
    ```
* - {py:obj}`not_built_hint <chartbook.check.not_built_hint>`
  - ```{autodoc2-docstring} chartbook.check.not_built_hint
    :summary:
    ```
* - {py:obj}`parse_expiration <chartbook.check.parse_expiration>`
  - ```{autodoc2-docstring} chartbook.check.parse_expiration
    :summary:
    ```
* - {py:obj}`read_policy <chartbook.check.read_policy>`
  - ```{autodoc2-docstring} chartbook.check.read_policy
    :summary:
    ```
* - {py:obj}`run_checks <chartbook.check.run_checks>`
  - ```{autodoc2-docstring} chartbook.check.run_checks
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEFAULT_WITHIN_DAYS <chartbook.check.DEFAULT_WITHIN_DAYS>`
  - ```{autodoc2-docstring} chartbook.check.DEFAULT_WITHIN_DAYS
    :summary:
    ```
* - {py:obj}`NOT_BUILT_YET <chartbook.check.NOT_BUILT_YET>`
  - ```{autodoc2-docstring} chartbook.check.NOT_BUILT_YET
    :summary:
    ```
* - {py:obj}`NO_EXPIRATION_VALUES <chartbook.check.NO_EXPIRATION_VALUES>`
  - ```{autodoc2-docstring} chartbook.check.NO_EXPIRATION_VALUES
    :summary:
    ```
* - {py:obj}`PROJECT_FIELDS_WRITTEN_IN <chartbook.check.PROJECT_FIELDS_WRITTEN_IN>`
  - ```{autodoc2-docstring} chartbook.check.PROJECT_FIELDS_WRITTEN_IN
    :summary:
    ```
````

### API

````{py:data} DEFAULT_WITHIN_DAYS
:canonical: chartbook.check.DEFAULT_WITHIN_DAYS
:value: >
   30

```{autodoc2-docstring} chartbook.check.DEFAULT_WITHIN_DAYS
```

````

````{py:data} NOT_BUILT_YET
:canonical: chartbook.check.NOT_BUILT_YET
:value: >
   'not built yet'

```{autodoc2-docstring} chartbook.check.NOT_BUILT_YET
```

````

````{py:data} NO_EXPIRATION_VALUES
:canonical: chartbook.check.NO_EXPIRATION_VALUES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.check.NO_EXPIRATION_VALUES
```

````

````{py:data} PROJECT_FIELDS_WRITTEN_IN
:canonical: chartbook.check.PROJECT_FIELDS_WRITTEN_IN
:value: >
   None

```{autodoc2-docstring} chartbook.check.PROJECT_FIELDS_WRITTEN_IN
```

````

`````{py:class} Problem
:canonical: chartbook.check.Problem

```{autodoc2-docstring} chartbook.check.Problem
```

````{py:attribute} field
:canonical: chartbook.check.Problem.field
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.check.Problem.field
```

````

````{py:attribute} file
:canonical: chartbook.check.Problem.file
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.check.Problem.file
```

````

````{py:method} format(relative_to: typing.Optional[pathlib.Path] = None) -> str
:canonical: chartbook.check.Problem.format

```{autodoc2-docstring} chartbook.check.Problem.format
```

````

````{py:attribute} message
:canonical: chartbook.check.Problem.message
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.check.Problem.message
```

````

````{py:attribute} table
:canonical: chartbook.check.Problem.table
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.check.Problem.table
```

````

`````

````{py:function} check_build_tool(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_build_tool

```{autodoc2-docstring} chartbook.check.check_build_tool
```
````

````{py:function} check_dependencies(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_dependencies

```{autodoc2-docstring} chartbook.check.check_dependencies
```
````

````{py:function} check_dependency_cycles(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_dependency_cycles

```{autodoc2-docstring} chartbook.check.check_dependency_cycles
```
````

````{py:function} check_ids(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_ids

```{autodoc2-docstring} chartbook.check.check_ids
```
````

````{py:function} check_licenses(manifest: dict, base_dir: pathlib.Path, within_days: int = DEFAULT_WITHIN_DAYS, today: typing.Optional[datetime.date] = None) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_licenses

```{autodoc2-docstring} chartbook.check.check_licenses
```
````

````{py:function} check_model_labels(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_model_labels

```{autodoc2-docstring} chartbook.check.check_model_labels
```
````

````{py:function} check_model_lineage(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_model_lineage

```{autodoc2-docstring} chartbook.check.check_model_lineage
```
````

````{py:function} check_model_metrics(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_model_metrics

```{autodoc2-docstring} chartbook.check.check_model_metrics
```
````

````{py:function} check_model_staleness(manifest: dict, base_dir: pathlib.Path) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_model_staleness

```{autodoc2-docstring} chartbook.check.check_model_staleness
```
````

````{py:function} check_paths(manifest: dict, base_dir: pathlib.Path, skip_outputs: bool = False) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_paths

```{autodoc2-docstring} chartbook.check.check_paths
```
````

````{py:function} check_required_fields(manifest: dict, base_dir: pathlib.Path, policy_label: str = 'the active policy', warn_only: bool = False) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_required_fields

```{autodoc2-docstring} chartbook.check.check_required_fields
```
````

````{py:function} check_sources(manifest: dict, base_dir: pathlib.Path, skip_outputs: bool = False) -> list[chartbook.check.Problem]
:canonical: chartbook.check.check_sources

```{autodoc2-docstring} chartbook.check.check_sources
```
````

````{py:function} display_path(path: pathlib.Path, relative_to: typing.Optional[pathlib.Path] = None) -> pathlib.Path
:canonical: chartbook.check.display_path

```{autodoc2-docstring} chartbook.check.display_path
```
````

````{py:function} load_policy(path: typing.Union[str, pathlib.Path]) -> dict
:canonical: chartbook.check.load_policy

```{autodoc2-docstring} chartbook.check.load_policy
```
````

````{py:function} not_built_hint(manifest: dict) -> str
:canonical: chartbook.check.not_built_hint

```{autodoc2-docstring} chartbook.check.not_built_hint
```
````

````{py:function} parse_expiration(value: typing.Any) -> typing.Optional[datetime.date]
:canonical: chartbook.check.parse_expiration

```{autodoc2-docstring} chartbook.check.parse_expiration
```
````

````{py:function} read_policy(path: typing.Union[str, pathlib.Path]) -> tuple[dict, bool]
:canonical: chartbook.check.read_policy

```{autodoc2-docstring} chartbook.check.read_policy
```
````

````{py:function} run_checks(manifest: dict, base_dir: typing.Union[str, pathlib.Path], within_days: int = DEFAULT_WITHIN_DAYS, today: typing.Optional[datetime.date] = None, policy_label: str = 'the active policy', skip_outputs: bool = False, policy_given: bool = True) -> list[chartbook.check.Problem]
:canonical: chartbook.check.run_checks

```{autodoc2-docstring} chartbook.check.run_checks
```
````
