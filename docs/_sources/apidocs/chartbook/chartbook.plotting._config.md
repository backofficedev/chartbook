---
orphan: true
---

# {py:mod}`chartbook.plotting._config`

```{py:module} chartbook.plotting._config
```

```{autodoc2-docstring} chartbook.plotting._config
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PlottingConfig <chartbook.plotting._config.PlottingConfig>`
  - ```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`apply_matplotlib_style <chartbook.plotting._config.apply_matplotlib_style>`
  - ```{autodoc2-docstring} chartbook.plotting._config.apply_matplotlib_style
    :summary:
    ```
* - {py:obj}`configure <chartbook.plotting._config.configure>`
  - ```{autodoc2-docstring} chartbook.plotting._config.configure
    :summary:
    ```
* - {py:obj}`get_bundled_style_path <chartbook.plotting._config.get_bundled_style_path>`
  - ```{autodoc2-docstring} chartbook.plotting._config.get_bundled_style_path
    :summary:
    ```
* - {py:obj}`get_config <chartbook.plotting._config.get_config>`
  - ```{autodoc2-docstring} chartbook.plotting._config.get_config
    :summary:
    ```
* - {py:obj}`set_style <chartbook.plotting._config.set_style>`
  - ```{autodoc2-docstring} chartbook.plotting._config.set_style
    :summary:
    ```
````

### API

`````{py:class} PlottingConfig
:canonical: chartbook.plotting._config.PlottingConfig

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig
```

````{py:attribute} color_palette
:canonical: chartbook.plotting._config.PlottingConfig.color_palette
:type: list[str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.color_palette
```

````

````{py:attribute} default_backend
:canonical: chartbook.plotting._config.PlottingConfig.default_backend
:type: typing.Literal[plotly, matplotlib]
:value: >
   'plotly'

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.default_backend
```

````

````{py:attribute} default_interactive
:canonical: chartbook.plotting._config.PlottingConfig.default_interactive
:type: bool
:value: >
   True

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.default_interactive
```

````

````{py:attribute} default_output_dir
:canonical: chartbook.plotting._config.PlottingConfig.default_output_dir
:type: pathlib.Path
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.default_output_dir
```

````

````{py:attribute} figure_size_single
:canonical: chartbook.plotting._config.PlottingConfig.figure_size_single
:type: tuple[float, float]
:value: >
   (8, 6)

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.figure_size_single
```

````

````{py:attribute} figure_size_wide
:canonical: chartbook.plotting._config.PlottingConfig.figure_size_wide
:type: tuple[float, float]
:value: >
   (12, 6)

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.figure_size_wide
```

````

````{py:attribute} matplotlib_style
:canonical: chartbook.plotting._config.PlottingConfig.matplotlib_style
:type: str | pathlib.Path
:value: >
   'chartbook'

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.matplotlib_style
```

````

````{py:attribute} nber_recessions
:canonical: chartbook.plotting._config.PlottingConfig.nber_recessions
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.nber_recessions
```

````

````{py:attribute} plotly_template
:canonical: chartbook.plotting._config.PlottingConfig.plotly_template
:type: str
:value: >
   'plotly_white'

```{autodoc2-docstring} chartbook.plotting._config.PlottingConfig.plotly_template
```

````

`````

````{py:function} apply_matplotlib_style() -> None
:canonical: chartbook.plotting._config.apply_matplotlib_style

```{autodoc2-docstring} chartbook.plotting._config.apply_matplotlib_style
```
````

````{py:function} configure(*, default_output_dir: str | pathlib.Path | None = None, default_interactive: bool | None = None, default_backend: typing.Literal[plotly, matplotlib] | None = None, nber_recessions: bool | None = None, matplotlib_style: str | pathlib.Path | None = None, plotly_template: str | None = None, figure_size_single: tuple[float, float] | None = None, figure_size_wide: tuple[float, float] | None = None, color_palette: list[str] | None = None) -> None
:canonical: chartbook.plotting._config.configure

```{autodoc2-docstring} chartbook.plotting._config.configure
```
````

````{py:function} get_bundled_style_path() -> pathlib.Path
:canonical: chartbook.plotting._config.get_bundled_style_path

```{autodoc2-docstring} chartbook.plotting._config.get_bundled_style_path
```
````

````{py:function} get_config() -> chartbook.plotting._config.PlottingConfig
:canonical: chartbook.plotting._config.get_config

```{autodoc2-docstring} chartbook.plotting._config.get_config
```
````

````{py:function} set_style(style: str | pathlib.Path) -> None
:canonical: chartbook.plotting._config.set_style

```{autodoc2-docstring} chartbook.plotting._config.set_style
```
````
