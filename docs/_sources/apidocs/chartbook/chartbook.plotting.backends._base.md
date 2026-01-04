---
orphan: true
---

# {py:mod}`chartbook.plotting.backends._base`

```{py:module} chartbook.plotting.backends._base
```

```{autodoc2-docstring} chartbook.plotting.backends._base
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BaseBackend <chartbook.plotting.backends._base.BaseBackend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend
    :summary:
    ```
* - {py:obj}`PlottingBackend <chartbook.plotting.backends._base.PlottingBackend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend
    :summary:
    ```
````

### API

`````{py:class} BaseBackend
:canonical: chartbook.plotting.backends._base.BaseBackend

Bases: {py:obj}`abc.ABC`

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend
```

````{py:method} create_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_area
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_area
```

````

````{py:method} create_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_bar
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_bar
```

````

````{py:method} create_chart(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_chart

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_chart
```

````

````{py:method} create_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_dual_axis
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_dual_axis
```

````

````{py:method} create_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_line
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_line
```

````

````{py:method} create_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_pie
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_pie
```

````

````{py:method} create_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.BaseBackend.create_scatter
:abstractmethod:

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.create_scatter
```

````

````{py:property} name
:canonical: chartbook.plotting.backends._base.BaseBackend.name
:abstractmethod:
:type: str

```{autodoc2-docstring} chartbook.plotting.backends._base.BaseBackend.name
```

````

`````

`````{py:class} PlottingBackend
:canonical: chartbook.plotting.backends._base.PlottingBackend

Bases: {py:obj}`typing.Protocol`

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend
```

````{py:method} create_area(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_area

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_area
```

````

````{py:method} create_bar(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_bar

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_bar
```

````

````{py:method} create_dual_axis(df: pandas.DataFrame, config: chartbook.plotting._types.DualAxisConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_dual_axis

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_dual_axis
```

````

````{py:method} create_line(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_line

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_line
```

````

````{py:method} create_pie(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_pie

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_pie
```

````

````{py:method} create_scatter(df: pandas.DataFrame, config: chartbook.plotting._types.ChartConfig, overlay: chartbook.plotting._types.OverlayConfig, output_path: pathlib.Path, size: tuple[float, float]) -> None
:canonical: chartbook.plotting.backends._base.PlottingBackend.create_scatter

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.create_scatter
```

````

````{py:property} name
:canonical: chartbook.plotting.backends._base.PlottingBackend.name
:type: str

```{autodoc2-docstring} chartbook.plotting.backends._base.PlottingBackend.name
```

````

`````
