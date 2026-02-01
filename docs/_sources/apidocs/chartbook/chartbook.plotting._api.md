---
orphan: true
---

# {py:mod}`chartbook.plotting._api`

```{py:module} chartbook.plotting._api
```

```{autodoc2-docstring} chartbook.plotting._api
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`area <chartbook.plotting._api.area>`
  - ```{autodoc2-docstring} chartbook.plotting._api.area
    :summary:
    ```
* - {py:obj}`bar <chartbook.plotting._api.bar>`
  - ```{autodoc2-docstring} chartbook.plotting._api.bar
    :summary:
    ```
* - {py:obj}`line <chartbook.plotting._api.line>`
  - ```{autodoc2-docstring} chartbook.plotting._api.line
    :summary:
    ```
* - {py:obj}`pie <chartbook.plotting._api.pie>`
  - ```{autodoc2-docstring} chartbook.plotting._api.pie
    :summary:
    ```
* - {py:obj}`scatter <chartbook.plotting._api.scatter>`
  - ```{autodoc2-docstring} chartbook.plotting._api.scatter
    :summary:
    ```
````

### API

````{py:function} area(df: pandas.DataFrame, *, x: str, y: str | typing.Sequence[str], stacked: bool = True, title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, color: str | typing.Sequence[str] | None = None, labels: dict[str, str] | None = None, x_title: str | None = None, y_title: str | None = None, x_range: tuple[float, float] | None = None, y_range: tuple[float, float] | None = None, x_tickformat: str | None = None, y_tickformat: str | None = None, nber_recessions: bool | None = None, hlines: typing.Sequence[dict[str, typing.Any]] | None = None, shaded_regions: typing.Sequence[dict[str, typing.Any]] | None = None, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._api.area

```{autodoc2-docstring} chartbook.plotting._api.area
```
````

````{py:function} bar(df: pandas.DataFrame, *, x: str, y: str | typing.Sequence[str], stacked: bool = False, title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, color: str | typing.Sequence[str] | None = None, labels: dict[str, str] | None = None, x_title: str | None = None, y_title: str | None = None, x_range: tuple[float, float] | None = None, y_range: tuple[float, float] | None = None, y_tickformat: str | None = None, nber_recessions: bool | None = None, hlines: typing.Sequence[dict[str, typing.Any]] | None = None, shaded_regions: typing.Sequence[dict[str, typing.Any]] | None = None, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._api.bar

```{autodoc2-docstring} chartbook.plotting._api.bar
```
````

````{py:function} line(df: pandas.DataFrame, *, x: str, y: str | typing.Sequence[str], title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, color: str | typing.Sequence[str] | None = None, labels: dict[str, str] | None = None, x_title: str | None = None, y_title: str | None = None, x_range: tuple[float, float] | None = None, y_range: tuple[float, float] | None = None, x_tickformat: str | None = None, y_tickformat: str | None = None, nber_recessions: bool | None = None, hlines: typing.Sequence[dict[str, typing.Any]] | None = None, vlines: typing.Sequence[dict[str, typing.Any]] | None = None, shaded_regions: typing.Sequence[dict[str, typing.Any]] | None = None, bands: typing.Sequence[dict[str, typing.Any]] | None = None, regression_line: bool = False, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._api.line

```{autodoc2-docstring} chartbook.plotting._api.line
```
````

````{py:function} pie(df: pandas.DataFrame, *, names: str, values: str, title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._api.pie

```{autodoc2-docstring} chartbook.plotting._api.pie
```
````

````{py:function} scatter(df: pandas.DataFrame, *, x: str, y: str, size: str | None = None, color_by: str | None = None, title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, color: str | None = None, x_title: str | None = None, y_title: str | None = None, x_range: tuple[float, float] | None = None, y_range: tuple[float, float] | None = None, x_tickformat: str | None = None, y_tickformat: str | None = None, hlines: typing.Sequence[dict[str, typing.Any]] | None = None, vlines: typing.Sequence[dict[str, typing.Any]] | None = None, regression_line: bool = False, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._api.scatter

```{autodoc2-docstring} chartbook.plotting._api.scatter
```
````
