---
orphan: true
---

# {py:mod}`chartbook.plotting.backends._hookspecs`

```{py:module} chartbook.plotting.backends._hookspecs
```

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PlottingHookSpec <chartbook.plotting.backends._hookspecs.PlottingHookSpec>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`hookimpl <chartbook.plotting.backends._hookspecs.hookimpl>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.hookimpl
    :summary:
    ```
* - {py:obj}`hookspec <chartbook.plotting.backends._hookspecs.hookspec>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.hookspec
    :summary:
    ```
````

### API

`````{py:class} PlottingHookSpec
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec
```

````{py:method} chartbook_create_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_area

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_area
```

````

````{py:method} chartbook_create_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_bar

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_bar
```

````

````{py:method} chartbook_create_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_dual_axis

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_dual_axis
```

````

````{py:method} chartbook_create_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_line

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_line
```

````

````{py:method} chartbook_create_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_pie

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_pie
```

````

````{py:method} chartbook_create_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_scatter

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_create_scatter
```

````

````{py:method} chartbook_get_backend_name() -> str
:canonical: chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_get_backend_name

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.PlottingHookSpec.chartbook_get_backend_name
```

````

`````

````{py:data} hookimpl
:canonical: chartbook.plotting.backends._hookspecs.hookimpl
:value: >
   'HookimplMarker(...)'

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.hookimpl
```

````

````{py:data} hookspec
:canonical: chartbook.plotting.backends._hookspecs.hookspec
:value: >
   'HookspecMarker(...)'

```{autodoc2-docstring} chartbook.plotting.backends._hookspecs.hookspec
```

````
