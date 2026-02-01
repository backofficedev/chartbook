---
orphan: true
---

# {py:mod}`chartbook.plotting._dual`

```{py:module} chartbook.plotting._dual
```

```{autodoc2-docstring} chartbook.plotting._dual
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`dual <chartbook.plotting._dual.dual>`
  - ```{autodoc2-docstring} chartbook.plotting._dual.dual
    :summary:
    ```
````

### API

````{py:function} dual(df: pandas.DataFrame, *, x: str, left_y: str | typing.Sequence[str], right_y: str | typing.Sequence[str], left_type: typing.Literal[line, bar, scatter, area] = 'line', right_type: typing.Literal[line, bar, scatter, area] = 'line', title: str | None = None, caption: str | None = None, note: str | None = None, source: str | None = None, x_title: str | None = None, left_y_title: str | None = None, right_y_title: str | None = None, left_y_range: tuple[float, float] | None = None, right_y_range: tuple[float, float] | None = None, left_y_tickformat: str | None = None, right_y_tickformat: str | None = None, left_colors: typing.Sequence[str] | None = None, right_colors: typing.Sequence[str] | None = None, nber_recessions: bool | None = None, hlines: typing.Sequence[dict[str, typing.Any]] | None = None, shaded_regions: typing.Sequence[dict[str, typing.Any]] | None = None, **kwargs: typing.Any) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._dual.dual

```{autodoc2-docstring} chartbook.plotting._dual.dual
```
````
