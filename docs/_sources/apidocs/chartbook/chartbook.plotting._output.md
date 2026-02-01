---
orphan: true
---

# {py:mod}`chartbook.plotting._output`

```{py:module} chartbook.plotting._output
```

```{autodoc2-docstring} chartbook.plotting._output
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`create_chart_result <chartbook.plotting._output.create_chart_result>`
  - ```{autodoc2-docstring} chartbook.plotting._output.create_chart_result
    :summary:
    ```
* - {py:obj}`create_dual_chart_result <chartbook.plotting._output.create_dual_chart_result>`
  - ```{autodoc2-docstring} chartbook.plotting._output.create_dual_chart_result
    :summary:
    ```
* - {py:obj}`save_chart_from_result <chartbook.plotting._output.save_chart_from_result>`
  - ```{autodoc2-docstring} chartbook.plotting._output.save_chart_from_result
    :summary:
    ```
````

### API

````{py:function} create_chart_result(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._output.create_chart_result

```{autodoc2-docstring} chartbook.plotting._output.create_chart_result
```
````

````{py:function} create_dual_chart_result(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._output.create_dual_chart_result

```{autodoc2-docstring} chartbook.plotting._output.create_dual_chart_result
```
````

````{py:function} save_chart_from_result(result: chartbook.plotting._types.ChartResult, output_dir: str | pathlib.Path | None = None, interactive: bool = True) -> None
:canonical: chartbook.plotting._output.save_chart_from_result

```{autodoc2-docstring} chartbook.plotting._output.save_chart_from_result
```
````
