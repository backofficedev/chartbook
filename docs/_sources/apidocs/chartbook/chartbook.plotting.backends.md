# {py:mod}`chartbook.plotting.backends`

```{py:module} chartbook.plotting.backends
```

```{autodoc2-docstring} chartbook.plotting.backends
:allowtitles:
```

## Package Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_backend <chartbook.plotting.backends.get_backend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends.get_backend
    :summary:
    ```
* - {py:obj}`get_plugin_manager <chartbook.plotting.backends.get_plugin_manager>`
  - ```{autodoc2-docstring} chartbook.plotting.backends.get_plugin_manager
    :summary:
    ```
* - {py:obj}`list_backends <chartbook.plotting.backends.list_backends>`
  - ```{autodoc2-docstring} chartbook.plotting.backends.list_backends
    :summary:
    ```
* - {py:obj}`register_backend <chartbook.plotting.backends.register_backend>`
  - ```{autodoc2-docstring} chartbook.plotting.backends.register_backend
    :summary:
    ```
````

### API

````{py:function} get_backend(name: str = 'plotly') -> chartbook.plotting.backends._base.PlottingBackend
:canonical: chartbook.plotting.backends.get_backend

```{autodoc2-docstring} chartbook.plotting.backends.get_backend
```
````

````{py:function} get_plugin_manager() -> pluggy.PluginManager
:canonical: chartbook.plotting.backends.get_plugin_manager

```{autodoc2-docstring} chartbook.plotting.backends.get_plugin_manager
```
````

````{py:function} list_backends() -> list[str]
:canonical: chartbook.plotting.backends.list_backends

```{autodoc2-docstring} chartbook.plotting.backends.list_backends
```
````

````{py:function} register_backend(backend: chartbook.plotting.backends._base.PlottingBackend, name: str | None = None) -> None
:canonical: chartbook.plotting.backends.register_backend

```{autodoc2-docstring} chartbook.plotting.backends.register_backend
```
````
