---
orphan: true
---

# {py:mod}`chartbook.plotting._types`

```{py:module} chartbook.plotting._types
```

```{autodoc2-docstring} chartbook.plotting._types
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ChartConfig <chartbook.plotting._types.ChartConfig>`
  - ```{autodoc2-docstring} chartbook.plotting._types.ChartConfig
    :summary:
    ```
* - {py:obj}`ChartResult <chartbook.plotting._types.ChartResult>`
  - ```{autodoc2-docstring} chartbook.plotting._types.ChartResult
    :summary:
    ```
* - {py:obj}`DualAxisConfig <chartbook.plotting._types.DualAxisConfig>`
  - ```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig
    :summary:
    ```
* - {py:obj}`OverlayConfig <chartbook.plotting._types.OverlayConfig>`
  - ```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig
    :summary:
    ```
````

### API

`````{py:class} ChartConfig
:canonical: chartbook.plotting._types.ChartConfig

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig
```

````{py:attribute} caption
:canonical: chartbook.plotting._types.ChartConfig.caption
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.caption
```

````

````{py:attribute} chart_id
:canonical: chartbook.plotting._types.ChartConfig.chart_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.chart_id
```

````

````{py:attribute} chart_type
:canonical: chartbook.plotting._types.ChartConfig.chart_type
:type: typing.Literal[line, bar, scatter, pie, area]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.chart_type
```

````

````{py:attribute} color
:canonical: chartbook.plotting._types.ChartConfig.color
:type: str | typing.Sequence[str] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.color
```

````

````{py:attribute} color_by
:canonical: chartbook.plotting._types.ChartConfig.color_by
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.color_by
```

````

````{py:attribute} extra_kwargs
:canonical: chartbook.plotting._types.ChartConfig.extra_kwargs
:type: dict[str, typing.Any]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.extra_kwargs
```

````

````{py:attribute} labels
:canonical: chartbook.plotting._types.ChartConfig.labels
:type: dict[str, str] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.labels
```

````

````{py:attribute} names
:canonical: chartbook.plotting._types.ChartConfig.names
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.names
```

````

````{py:attribute} note
:canonical: chartbook.plotting._types.ChartConfig.note
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.note
```

````

````{py:attribute} size
:canonical: chartbook.plotting._types.ChartConfig.size
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.size
```

````

````{py:attribute} source
:canonical: chartbook.plotting._types.ChartConfig.source
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.source
```

````

````{py:attribute} stacked
:canonical: chartbook.plotting._types.ChartConfig.stacked
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.stacked
```

````

````{py:attribute} title
:canonical: chartbook.plotting._types.ChartConfig.title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.title
```

````

````{py:attribute} values
:canonical: chartbook.plotting._types.ChartConfig.values
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.values
```

````

````{py:attribute} x
:canonical: chartbook.plotting._types.ChartConfig.x
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.x
```

````

````{py:attribute} x_range
:canonical: chartbook.plotting._types.ChartConfig.x_range
:type: tuple[float, float] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.x_range
```

````

````{py:attribute} x_tickformat
:canonical: chartbook.plotting._types.ChartConfig.x_tickformat
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.x_tickformat
```

````

````{py:attribute} x_title
:canonical: chartbook.plotting._types.ChartConfig.x_title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.x_title
```

````

````{py:attribute} y
:canonical: chartbook.plotting._types.ChartConfig.y
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.y
```

````

````{py:attribute} y_range
:canonical: chartbook.plotting._types.ChartConfig.y_range
:type: tuple[float, float] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.y_range
```

````

````{py:attribute} y_tickformat
:canonical: chartbook.plotting._types.ChartConfig.y_tickformat
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.y_tickformat
```

````

````{py:attribute} y_title
:canonical: chartbook.plotting._types.ChartConfig.y_title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartConfig.y_title
```

````

`````

`````{py:class} ChartResult
:canonical: chartbook.plotting._types.ChartResult

```{autodoc2-docstring} chartbook.plotting._types.ChartResult
```

````{py:attribute} chart_id
:canonical: chartbook.plotting._types.ChartResult.chart_id
:type: str | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.chart_id
```

````

````{py:attribute} chart_type
:canonical: chartbook.plotting._types.ChartResult.chart_type
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.chart_type
```

````

````{py:attribute} figure
:canonical: chartbook.plotting._types.ChartResult.figure
:type: plotly.graph_objects.Figure
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.figure
```

````

````{py:attribute} html_path
:canonical: chartbook.plotting._types.ChartResult.html_path
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.html_path
```

````

````{py:property} mpl_axes
:canonical: chartbook.plotting._types.ChartResult.mpl_axes
:type: matplotlib.axes.Axes

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.mpl_axes
```

````

````{py:property} mpl_figure
:canonical: chartbook.plotting._types.ChartResult.mpl_figure
:type: matplotlib.figure.Figure

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.mpl_figure
```

````

````{py:attribute} output_dir
:canonical: chartbook.plotting._types.ChartResult.output_dir
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.output_dir
```

````

````{py:property} paths
:canonical: chartbook.plotting._types.ChartResult.paths
:type: dict[str, pathlib.Path]

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.paths
```

````

````{py:attribute} pdf_path
:canonical: chartbook.plotting._types.ChartResult.pdf_path
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.pdf_path
```

````

````{py:attribute} pdf_wide_path
:canonical: chartbook.plotting._types.ChartResult.pdf_wide_path
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.pdf_wide_path
```

````

````{py:attribute} png_path
:canonical: chartbook.plotting._types.ChartResult.png_path
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.png_path
```

````

````{py:attribute} png_wide_path
:canonical: chartbook.plotting._types.ChartResult.png_wide_path
:type: pathlib.Path | None
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.png_wide_path
```

````

````{py:method} save(chart_id: str, output_dir: str | pathlib.Path | None = None, interactive: bool = True) -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._types.ChartResult.save

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.save
```

````

````{py:method} show() -> chartbook.plotting._types.ChartResult
:canonical: chartbook.plotting._types.ChartResult.show

```{autodoc2-docstring} chartbook.plotting._types.ChartResult.show
```

````

`````

`````{py:class} DualAxisConfig
:canonical: chartbook.plotting._types.DualAxisConfig

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig
```

````{py:attribute} caption
:canonical: chartbook.plotting._types.DualAxisConfig.caption
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.caption
```

````

````{py:attribute} chart_id
:canonical: chartbook.plotting._types.DualAxisConfig.chart_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.chart_id
```

````

````{py:attribute} extra_kwargs
:canonical: chartbook.plotting._types.DualAxisConfig.extra_kwargs
:type: dict[str, typing.Any]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.extra_kwargs
```

````

````{py:attribute} left_colors
:canonical: chartbook.plotting._types.DualAxisConfig.left_colors
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_colors
```

````

````{py:attribute} left_type
:canonical: chartbook.plotting._types.DualAxisConfig.left_type
:type: typing.Literal[line, bar, scatter, area]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_type
```

````

````{py:attribute} left_y
:canonical: chartbook.plotting._types.DualAxisConfig.left_y
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_y
```

````

````{py:attribute} left_y_range
:canonical: chartbook.plotting._types.DualAxisConfig.left_y_range
:type: tuple[float, float] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_y_range
```

````

````{py:attribute} left_y_tickformat
:canonical: chartbook.plotting._types.DualAxisConfig.left_y_tickformat
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_y_tickformat
```

````

````{py:attribute} left_y_title
:canonical: chartbook.plotting._types.DualAxisConfig.left_y_title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.left_y_title
```

````

````{py:attribute} note
:canonical: chartbook.plotting._types.DualAxisConfig.note
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.note
```

````

````{py:attribute} right_colors
:canonical: chartbook.plotting._types.DualAxisConfig.right_colors
:type: list[str] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_colors
```

````

````{py:attribute} right_type
:canonical: chartbook.plotting._types.DualAxisConfig.right_type
:type: typing.Literal[line, bar, scatter, area]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_type
```

````

````{py:attribute} right_y
:canonical: chartbook.plotting._types.DualAxisConfig.right_y
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_y
```

````

````{py:attribute} right_y_range
:canonical: chartbook.plotting._types.DualAxisConfig.right_y_range
:type: tuple[float, float] | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_y_range
```

````

````{py:attribute} right_y_tickformat
:canonical: chartbook.plotting._types.DualAxisConfig.right_y_tickformat
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_y_tickformat
```

````

````{py:attribute} right_y_title
:canonical: chartbook.plotting._types.DualAxisConfig.right_y_title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.right_y_title
```

````

````{py:attribute} source
:canonical: chartbook.plotting._types.DualAxisConfig.source
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.source
```

````

````{py:attribute} title
:canonical: chartbook.plotting._types.DualAxisConfig.title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.title
```

````

````{py:attribute} x
:canonical: chartbook.plotting._types.DualAxisConfig.x
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.x
```

````

````{py:attribute} x_title
:canonical: chartbook.plotting._types.DualAxisConfig.x_title
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.plotting._types.DualAxisConfig.x_title
```

````

`````

`````{py:class} OverlayConfig
:canonical: chartbook.plotting._types.OverlayConfig

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig
```

````{py:attribute} bands
:canonical: chartbook.plotting._types.OverlayConfig.bands
:type: list[dict[str, typing.Any]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.bands
```

````

````{py:attribute} hlines
:canonical: chartbook.plotting._types.OverlayConfig.hlines
:type: list[dict[str, typing.Any]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.hlines
```

````

````{py:attribute} nber_recessions
:canonical: chartbook.plotting._types.OverlayConfig.nber_recessions
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.nber_recessions
```

````

````{py:attribute} regression_line
:canonical: chartbook.plotting._types.OverlayConfig.regression_line
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.regression_line
```

````

````{py:attribute} shaded_regions
:canonical: chartbook.plotting._types.OverlayConfig.shaded_regions
:type: list[dict[str, typing.Any]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.shaded_regions
```

````

````{py:attribute} vlines
:canonical: chartbook.plotting._types.OverlayConfig.vlines
:type: list[dict[str, typing.Any]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._types.OverlayConfig.vlines
```

````

`````
