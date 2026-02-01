---
orphan: true
---

# {py:mod}`chartbook.plotting._overlays`

```{py:module} chartbook.plotting._overlays
```

```{autodoc2-docstring} chartbook.plotting._overlays
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`apply_overlays_matplotlib <chartbook.plotting._overlays.apply_overlays_matplotlib>`
  - ```{autodoc2-docstring} chartbook.plotting._overlays.apply_overlays_matplotlib
    :summary:
    ```
* - {py:obj}`apply_overlays_plotly <chartbook.plotting._overlays.apply_overlays_plotly>`
  - ```{autodoc2-docstring} chartbook.plotting._overlays.apply_overlays_plotly
    :summary:
    ```
* - {py:obj}`filter_recessions_for_range <chartbook.plotting._overlays.filter_recessions_for_range>`
  - ```{autodoc2-docstring} chartbook.plotting._overlays.filter_recessions_for_range
    :summary:
    ```
* - {py:obj}`get_nber_recessions <chartbook.plotting._overlays.get_nber_recessions>`
  - ```{autodoc2-docstring} chartbook.plotting._overlays.get_nber_recessions
    :summary:
    ```
````

### API

````{py:function} apply_overlays_matplotlib(ax: matplotlib.axes.Axes, overlay: chartbook.plotting._types.OverlayConfig, df: pandas.DataFrame, x_col: str) -> None
:canonical: chartbook.plotting._overlays.apply_overlays_matplotlib

```{autodoc2-docstring} chartbook.plotting._overlays.apply_overlays_matplotlib
```
````

````{py:function} apply_overlays_plotly(fig: plotly.graph_objects.Figure, overlay: chartbook.plotting._types.OverlayConfig, df: pandas.DataFrame, x_col: str) -> None
:canonical: chartbook.plotting._overlays.apply_overlays_plotly

```{autodoc2-docstring} chartbook.plotting._overlays.apply_overlays_plotly
```
````

````{py:function} filter_recessions_for_range(recessions: pandas.DataFrame, x_min: datetime.datetime | pandas.Timestamp | None = None, x_max: datetime.datetime | pandas.Timestamp | None = None) -> pandas.DataFrame
:canonical: chartbook.plotting._overlays.filter_recessions_for_range

```{autodoc2-docstring} chartbook.plotting._overlays.filter_recessions_for_range
```
````

````{py:function} get_nber_recessions() -> pandas.DataFrame
:canonical: chartbook.plotting._overlays.get_nber_recessions

```{autodoc2-docstring} chartbook.plotting._overlays.get_nber_recessions
```
````
