---
orphan: true
---

# {py:mod}`chartbook.plotting._validation`

```{py:module} chartbook.plotting._validation
```

```{autodoc2-docstring} chartbook.plotting._validation
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`validate_chart_id <chartbook.plotting._validation.validate_chart_id>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_chart_id
    :summary:
    ```
* - {py:obj}`validate_columns_exist <chartbook.plotting._validation.validate_columns_exist>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_columns_exist
    :summary:
    ```
* - {py:obj}`validate_dataframe <chartbook.plotting._validation.validate_dataframe>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_dataframe
    :summary:
    ```
* - {py:obj}`validate_datetime_column <chartbook.plotting._validation.validate_datetime_column>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_datetime_column
    :summary:
    ```
* - {py:obj}`validate_numeric_columns <chartbook.plotting._validation.validate_numeric_columns>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_numeric_columns
    :summary:
    ```
* - {py:obj}`validate_overlay_bands <chartbook.plotting._validation.validate_overlay_bands>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_bands
    :summary:
    ```
* - {py:obj}`validate_overlay_hlines <chartbook.plotting._validation.validate_overlay_hlines>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_hlines
    :summary:
    ```
* - {py:obj}`validate_overlay_shaded_regions <chartbook.plotting._validation.validate_overlay_shaded_regions>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_shaded_regions
    :summary:
    ```
* - {py:obj}`validate_overlay_vlines <chartbook.plotting._validation.validate_overlay_vlines>`
  - ```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_vlines
    :summary:
    ```
````

### API

````{py:function} validate_chart_id(chart_id: str) -> None
:canonical: chartbook.plotting._validation.validate_chart_id

```{autodoc2-docstring} chartbook.plotting._validation.validate_chart_id
```
````

````{py:function} validate_columns_exist(df: pandas.DataFrame, columns: typing.Sequence[str], context: str = '') -> None
:canonical: chartbook.plotting._validation.validate_columns_exist

```{autodoc2-docstring} chartbook.plotting._validation.validate_columns_exist
```
````

````{py:function} validate_dataframe(df: pandas.DataFrame) -> None
:canonical: chartbook.plotting._validation.validate_dataframe

```{autodoc2-docstring} chartbook.plotting._validation.validate_dataframe
```
````

````{py:function} validate_datetime_column(df: pandas.DataFrame, column: str) -> None
:canonical: chartbook.plotting._validation.validate_datetime_column

```{autodoc2-docstring} chartbook.plotting._validation.validate_datetime_column
```
````

````{py:function} validate_numeric_columns(df: pandas.DataFrame, columns: typing.Sequence[str]) -> None
:canonical: chartbook.plotting._validation.validate_numeric_columns

```{autodoc2-docstring} chartbook.plotting._validation.validate_numeric_columns
```
````

````{py:function} validate_overlay_bands(df: pandas.DataFrame, bands: list[dict]) -> None
:canonical: chartbook.plotting._validation.validate_overlay_bands

```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_bands
```
````

````{py:function} validate_overlay_hlines(hlines: list[dict]) -> None
:canonical: chartbook.plotting._validation.validate_overlay_hlines

```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_hlines
```
````

````{py:function} validate_overlay_shaded_regions(regions: list[dict]) -> None
:canonical: chartbook.plotting._validation.validate_overlay_shaded_regions

```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_shaded_regions
```
````

````{py:function} validate_overlay_vlines(vlines: list[dict]) -> None
:canonical: chartbook.plotting._validation.validate_overlay_vlines

```{autodoc2-docstring} chartbook.plotting._validation.validate_overlay_vlines
```
````
