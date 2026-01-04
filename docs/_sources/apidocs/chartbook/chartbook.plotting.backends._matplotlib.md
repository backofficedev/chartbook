---
orphan: true
---

# {py:mod}`chartbook.plotting.backends._matplotlib`

```{py:module} chartbook.plotting.backends._matplotlib
```

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MatplotlibBackend <chartbook.plotting.backends._matplotlib.MatplotlibBackend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend
    :summary:
    ```
````

### API

`````{py:class} MatplotlibBackend
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend

Bases: {py:obj}`chartbook.plotting.backends._base.BaseBackend`

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend
```

````{py:method} build_figure(df: pandas.DataFrame, config: ChartConfig | DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig) -> tuple[matplotlib.figure.Figure, matplotlib.axes.Axes]
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.build_figure

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.build_figure
```

````

````{py:method} create_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_area

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_area
```

````

````{py:method} create_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_bar

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_bar
```

````

````{py:method} create_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_dual_axis

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_dual_axis
```

````

````{py:method} create_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_line

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_line
```

````

````{py:method} create_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_pie

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_pie
```

````

````{py:method} create_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_scatter

```{autodoc2-docstring} chartbook.plotting.backends._matplotlib.MatplotlibBackend.create_scatter
```

````

````{py:property} name
:canonical: chartbook.plotting.backends._matplotlib.MatplotlibBackend.name
:type: str

````

`````
