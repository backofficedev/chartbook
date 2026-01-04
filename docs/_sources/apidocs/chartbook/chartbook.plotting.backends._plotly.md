---
orphan: true
---

# {py:mod}`chartbook.plotting.backends._plotly`

```{py:module} chartbook.plotting.backends._plotly
```

```{autodoc2-docstring} chartbook.plotting.backends._plotly
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PlotlyBackend <chartbook.plotting.backends._plotly.PlotlyBackend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend
    :summary:
    ```
````

### API

`````{py:class} PlotlyBackend
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend

Bases: {py:obj}`chartbook.plotting.backends._base.BaseBackend`

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend
```

````{py:method} build_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_area

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_area
```

````

````{py:method} build_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_bar

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_bar
```

````

````{py:method} build_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_dual_axis

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_dual_axis
```

````

````{py:method} build_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_line

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_line
```

````

````{py:method} build_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_pie

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_pie
```

````

````{py:method} build_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, size: tuple[float, float]) -> plotly.graph_objects.Figure
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.build_scatter

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.build_scatter
```

````

````{py:method} create_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_area

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_area
```

````

````{py:method} create_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_bar

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_bar
```

````

````{py:method} create_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_dual_axis

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_dual_axis
```

````

````{py:method} create_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_line

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_line
```

````

````{py:method} create_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_pie

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_pie
```

````

````{py:method} create_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.create_scatter

```{autodoc2-docstring} chartbook.plotting.backends._plotly.PlotlyBackend.create_scatter
```

````

````{py:property} name
:canonical: chartbook.plotting.backends._plotly.PlotlyBackend.name
:type: str

````

`````
