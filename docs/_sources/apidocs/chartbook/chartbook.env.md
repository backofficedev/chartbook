# {py:mod}`chartbook.env`

```{py:module} chartbook.env
```

```{autodoc2-docstring} chartbook.env
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`clear_cache <chartbook.env.clear_cache>`
  - ```{autodoc2-docstring} chartbook.env.clear_cache
    :summary:
    ```
* - {py:obj}`create_directories <chartbook.env.create_directories>`
  - ```{autodoc2-docstring} chartbook.env.create_directories
    :summary:
    ```
* - {py:obj}`get <chartbook.env.get>`
  - ```{autodoc2-docstring} chartbook.env.get
    :summary:
    ```
* - {py:obj}`get_os_type <chartbook.env.get_os_type>`
  - ```{autodoc2-docstring} chartbook.env.get_os_type
    :summary:
    ```
* - {py:obj}`get_project_root <chartbook.env.get_project_root>`
  - ```{autodoc2-docstring} chartbook.env.get_project_root
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEFAULT_MARKERS <chartbook.env.DEFAULT_MARKERS>`
  - ```{autodoc2-docstring} chartbook.env.DEFAULT_MARKERS
    :summary:
    ```
* - {py:obj}`config <chartbook.env.config>`
  - ```{autodoc2-docstring} chartbook.env.config
    :summary:
    ```
````

### API

````{py:data} DEFAULT_MARKERS
:canonical: chartbook.env.DEFAULT_MARKERS
:type: tuple[str, ...]
:value: >
   ('.git', 'pyproject.toml', '.env', '.env.example', 'requirements.txt')

```{autodoc2-docstring} chartbook.env.DEFAULT_MARKERS
```

````

````{py:function} clear_cache() -> None
:canonical: chartbook.env.clear_cache

```{autodoc2-docstring} chartbook.env.clear_cache
```
````

````{py:data} config
:canonical: chartbook.env.config
:value: >
   None

```{autodoc2-docstring} chartbook.env.config
```

````

````{py:function} create_directories() -> None
:canonical: chartbook.env.create_directories

```{autodoc2-docstring} chartbook.env.create_directories
```
````

````{py:function} get(var_name: str, default: typing.Any = undefined, cast: typing.Any = undefined, convert_dir_vars_to_abs_path: bool = True) -> typing.Any
:canonical: chartbook.env.get

```{autodoc2-docstring} chartbook.env.get
```
````

````{py:function} get_os_type() -> str
:canonical: chartbook.env.get_os_type

```{autodoc2-docstring} chartbook.env.get_os_type
```
````

````{py:function} get_project_root(start: str | pathlib.Path | None = None, markers: typing.Sequence[str] | None = None, max_levels: int = 10, use_cache: bool = True) -> pathlib.Path
:canonical: chartbook.env.get_project_root

```{autodoc2-docstring} chartbook.env.get_project_root
```
````
