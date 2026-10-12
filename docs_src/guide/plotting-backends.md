# Writing a Plotting Backend

A **backend** is an object that knows how to draw ChartBook's chart types with one plotting library. Two ship with ChartBook — `plotly` and `matplotlib` — and a third-party package can add more: Altair, Bokeh, a house library, anything that can turn a dataframe and a description of a chart into a file.

This page is the whole interface. It is written so that you can build and ship a backend without reading ChartBook's source.

```{admonition} What a third-party backend is used for today
:class: important

A backend you register is **discoverable and callable**: `get_backend("yours")` returns it, and you (or your users) call its `create_*` methods.

It is **not yet selectable from the chart functions**. `chartbook.plotting.line()` and its siblings always build the interactive figure with the built-in `plotly` backend and the static PNG/PDF files with the built-in `matplotlib` backend; there is no `backend=` argument, and `configure(default_backend=...)` is stored but not read. So today a third-party backend adds a way to render the same chart description with another library — it does not replace what `.save()` writes. See [Using a backend](#using-a-backend).
```

## The contract

A backend is any object with a `name` and six methods. That is the `PlottingBackend` protocol in `chartbook.plotting.backends`:

| Member | Required | What it is |
|---|---|---|
| `name` | yes | A property returning the backend's name as a string, e.g. `"altair"`. This is what `get_backend()` looks up. |
| `create_line(df, config, overlay, output_path, size)` | yes | Draw a line chart |
| `create_bar(…)` | yes | Draw a bar chart |
| `create_scatter(…)` | yes | Draw a scatter plot |
| `create_pie(…)` | yes | Draw a pie chart |
| `create_area(…)` | yes | Draw an area chart |
| `create_dual_axis(df, config, overlay, output_path, size)` | no | Draw a chart with two y-axes. Raise `NotImplementedError` if unsupported |

Every method has the same five parameters and returns `None`. Its job is to **write the chart to `output_path`**.

| Parameter | Type | Meaning |
|---|---|---|
| `df` | `pandas.DataFrame` | The data. Column names are referred to by `config`. |
| `config` | `ChartConfig` (`DualAxisConfig` for `create_dual_axis`) | What to draw — see [The configuration objects](#the-configuration-objects) |
| `overlay` | `OverlayConfig` | Reference lines, shaded regions and bands to draw over the chart |
| `output_path` | `pathlib.Path` | Where to write. The directory may not exist yet; create it. The suffix says which format the caller wants — the built-in `matplotlib` backend is called once each for `.png` and `.pdf` |
| `size` | `tuple[float, float]` | Figure size as `(width, height)` in **inches** |

A backend should honour what it can from `config` and `overlay` and quietly ignore what its library cannot express. Nothing validates the output.

### Start from `BaseBackend`

Subclass `chartbook.plotting.backends.BaseBackend` rather than implementing the protocol from scratch. It is the intended starting point, and it gives you three things:

- the five chart methods and `name` as **abstract** members, so a backend that forgets one cannot be instantiated;
- a default `create_dual_axis` that raises `NotImplementedError` naming your backend;
- `create_chart(df, config, overlay, output_path, size)`, which reads `config.chart_type` and calls the matching `create_*` method. Callers that hold a `ChartConfig` use this instead of choosing a method themselves.

## A complete example

A backend that writes each chart as a [Vega-Lite](https://vega.github.io/vega-lite/) specification — the format Altair produces — in one file, with no dependency beyond ChartBook itself:

```{literalinclude} ../_examples/vegalite_backend.py
:language: python
```

This file is exercised by ChartBook's own test suite, registered through a real entry point, so it is known to work against the version of ChartBook these docs describe.

## Registering it

Backends are found through the **`chartbook_plotting`** entry-point group. In your package's `pyproject.toml`:

```toml
[project.entry-points.chartbook_plotting]
vegalite = "chartbook_vegalite:backend"
```

```{warning}
The entry point must name a backend **instance** (`backend = VegaLiteBackend()` above), not the class. Whatever object the entry point resolves to is registered as-is; a class is registered uninstantiated, `get_backend()` hands it back, and every method call on it fails for want of `self`.
```

Once the package is installed, nothing else is needed — the first call to `get_backend()` loads every installed entry point in the group:

```python
from chartbook.plotting.backends import get_backend, list_backends

sorted(list_backends())    # ['matplotlib', 'plotly', 'vegalite']
backend = get_backend("vegalite")
```

`get_backend()` matches on the backend's `name` property first, then on the entry point's own name. Keep the two the same.

To register a backend without packaging it — in a script, a notebook or a test — pass an instance to `register_backend`:

```python
from chartbook.plotting.backends import register_backend

register_backend(VegaLiteBackend())
```

(using-a-backend)=
## Using a backend

Call it with a chart description. `ChartConfig`, `OverlayConfig` and `DualAxisConfig` are exported from `chartbook.plotting`:

```python
from pathlib import Path

from chartbook.plotting import ChartConfig, OverlayConfig
from chartbook.plotting.backends import get_backend

config = ChartConfig(chart_type="line", x="date", y=["gdp"], title="GDP")

get_backend("vegalite").create_chart(
    df, config, OverlayConfig(), Path("_output/gdp.vl.json"), size=(8, 6)
)
```

`create_chart` picks the method from `config.chart_type`. For a dual-axis chart, build a `DualAxisConfig` and call `create_dual_axis` directly.

(the-configuration-objects)=
## The configuration objects

These are plain dataclasses. A field left at its default was not set by the caller.

### `ChartConfig`

| Field | Type | Meaning |
|---|---|---|
| `chart_type` | `"line"`, `"bar"`, `"scatter"`, `"pie"`, `"area"` | Which chart. `create_chart` dispatches on it |
| `x` | `str` | Column for the x-axis |
| `y` | `list[str]` | Columns to plot. **Always a list**, even for one series |
| `title`, `caption`, `note`, `source` | `str` or `None` | Annotations. The built-ins draw the title above the chart and the others beneath it |
| `color` | `str`, sequence of `str`, or `None` | One colour for every series, or one per `y` column in order |
| `labels` | `dict[str, str]` or `None` | Display name for each `y` column |
| `x_title`, `y_title` | `str` or `None` | Axis titles |
| `x_range`, `y_range` | `(min, max)` or `None` | Axis limits |
| `x_tickformat`, `y_tickformat` | `str` or `None` | Tick format strings in Plotly's syntax (d3-format; strftime-style for dates). The built-in `matplotlib` backend ignores them — an example of skipping what a library cannot express |
| `stacked` | `bool` | Stack bars or areas |
| `size`, `color_by` | `str` or `None` | Scatter only: columns for marker size and for colour grouping |
| `names`, `values` | `str` or `None` | Pie only: the label column and the value column. (`x` and `y` are also set to them.) |
| `chart_id` | `str` or `None` | Set when the chart is saved; not needed to draw |
| `extra_kwargs` | `dict` | Extra keyword arguments the caller passed, for the backend to forward to its library or ignore |

### `OverlayConfig`

| Field | Type | Meaning |
|---|---|---|
| `nber_recessions` | `bool` | Shade U.S. recessions. The dates come from `chartbook.plotting._overlays.get_nber_recessions()`, a dataframe of `start`/`end` — a private helper today, so treat it as subject to change |
| `hlines` | `list[dict]` | Horizontal lines: `y` (required), `color`, `dash`, `width`, `label` |
| `vlines` | `list[dict]` | Vertical lines: `x` (required), `color`, `dash`, `width`, `label` |
| `shaded_regions` | `list[dict]` | Shaded x-ranges: `x0`, `x1` (required), `color`, `alpha`, `label` |
| `bands` | `list[dict]` | Fill between two columns: `y_upper`, `y_lower` (required), `color`, `alpha`, `label` |
| `regression_line` | `bool` | Add a fitted line through the first `y` column (scatter) |

`dash` is one of `"solid"`, `"dash"`, `"dot"`, `"dashdot"`.

### `DualAxisConfig`

| Field | Type | Meaning |
|---|---|---|
| `x` | `str` | Column for the shared x-axis |
| `left_y`, `right_y` | `list[str]` | Columns for each axis |
| `left_type`, `right_type` | `"line"`, `"bar"`, `"scatter"`, `"area"` | How each axis's series are drawn |
| `left_y_title`, `right_y_title`, `x_title` | `str` or `None` | Axis titles |
| `left_y_range`, `right_y_range` | `(min, max)` or `None` | Axis limits |
| `left_y_tickformat`, `right_y_tickformat` | `str` or `None` | Tick formats |
| `left_colors`, `right_colors` | `list[str]` or `None` | Series colours per axis |
| `title`, `caption`, `note`, `source`, `chart_id`, `extra_kwargs` | | As in `ChartConfig` |

## What is not part of the interface

A few things in `chartbook.plotting.backends` look like extension points and are not. Knowing which saves time.

- **`PlottingHookSpec` and the `hookimpl` marker.** The module declares [pluggy](https://pluggy.readthedocs.io/) hook specifications (`chartbook_create_line` and so on). Nothing calls those hooks, and neither built-in backend implements them; pluggy is used only as the registry and the entry-point loader. Decorating methods with `@hookimpl` has no effect. Implement the methods in [The contract](#the-contract) instead.
- **`build_line`, `build_bar`, … on the `plotly` backend, and `build_figure` on the `matplotlib` backend.** These return a figure object without saving it. `ChartResult` uses them to give you `.figure`, `.mpl_figure` and `.mpl_axes`. They are internal to the two built-ins and no other backend is asked for them.
- **`configure(default_backend=...)`.** Accepted and stored; not consulted.
