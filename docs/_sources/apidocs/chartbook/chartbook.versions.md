# {py:mod}`chartbook.versions`

```{py:module} chartbook.versions
```

```{autodoc2-docstring} chartbook.versions
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Rendered <chartbook.versions.Rendered>`
  - ```{autodoc2-docstring} chartbook.versions.Rendered
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`add_to_site <chartbook.versions.add_to_site>`
  - ```{autodoc2-docstring} chartbook.versions.add_to_site
    :summary:
    ```
* - {py:obj}`fingerprint <chartbook.versions.fingerprint>`
  - ```{autodoc2-docstring} chartbook.versions.fingerprint
    :summary:
    ```
* - {py:obj}`forget <chartbook.versions.forget>`
  - ```{autodoc2-docstring} chartbook.versions.forget
    :summary:
    ```
* - {py:obj}`render <chartbook.versions.render>`
  - ```{autodoc2-docstring} chartbook.versions.render
    :summary:
    ```
* - {py:obj}`render_listed <chartbook.versions.render_listed>`
  - ```{autodoc2-docstring} chartbook.versions.render_listed
    :summary:
    ```
* - {py:obj}`site_path <chartbook.versions.site_path>`
  - ```{autodoc2-docstring} chartbook.versions.site_path
    :summary:
    ```
* - {py:obj}`slug <chartbook.versions.slug>`
  - ```{autodoc2-docstring} chartbook.versions.slug
    :summary:
    ```
* - {py:obj}`version_name <chartbook.versions.version_name>`
  - ```{autodoc2-docstring} chartbook.versions.version_name
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BUILD_TIMEOUT <chartbook.versions.BUILD_TIMEOUT>`
  - ```{autodoc2-docstring} chartbook.versions.BUILD_TIMEOUT
    :summary:
    ```
* - {py:obj}`VERSIONS_DIR <chartbook.versions.VERSIONS_DIR>`
  - ```{autodoc2-docstring} chartbook.versions.VERSIONS_DIR
    :summary:
    ```
````

### API

````{py:data} BUILD_TIMEOUT
:canonical: chartbook.versions.BUILD_TIMEOUT
:value: >
   600

```{autodoc2-docstring} chartbook.versions.BUILD_TIMEOUT
```

````

`````{py:class} Rendered
:canonical: chartbook.versions.Rendered

```{autodoc2-docstring} chartbook.versions.Rendered
```

````{py:attribute} built
:canonical: chartbook.versions.Rendered.built
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.versions.Rendered.built
```

````

````{py:attribute} folder
:canonical: chartbook.versions.Rendered.folder
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.versions.Rendered.folder
```

````

````{py:attribute} now
:canonical: chartbook.versions.Rendered.now
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.versions.Rendered.now
```

````

````{py:attribute} why
:canonical: chartbook.versions.Rendered.why
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.versions.Rendered.why
```

````

`````

````{py:data} VERSIONS_DIR
:canonical: chartbook.versions.VERSIONS_DIR
:value: >
   'versions'

```{autodoc2-docstring} chartbook.versions.VERSIONS_DIR
```

````

````{py:function} add_to_site(index: dict, html_dir: pathlib.Path, store=None, echo=print, rendered_by_moment: dict | None = None) -> list[chartbook.versions.Rendered]
:canonical: chartbook.versions.add_to_site

```{autodoc2-docstring} chartbook.versions.add_to_site
```
````

````{py:function} fingerprint() -> str
:canonical: chartbook.versions.fingerprint

```{autodoc2-docstring} chartbook.versions.fingerprint
```
````

````{py:function} forget(taken) -> bool
:canonical: chartbook.versions.forget

```{autodoc2-docstring} chartbook.versions.forget
```
````

````{py:function} render(taken, store=None, timeout: float = BUILD_TIMEOUT) -> chartbook.versions.Rendered
:canonical: chartbook.versions.render

```{autodoc2-docstring} chartbook.versions.render
```
````

````{py:function} render_listed(index: dict, store=None, echo=print) -> dict
:canonical: chartbook.versions.render_listed

```{autodoc2-docstring} chartbook.versions.render_listed
```
````

````{py:function} site_path(pipeline_id: str, name: str) -> str
:canonical: chartbook.versions.site_path

```{autodoc2-docstring} chartbook.versions.site_path
```
````

````{py:function} slug(pipeline_id: str) -> str
:canonical: chartbook.versions.slug

```{autodoc2-docstring} chartbook.versions.slug
```
````

````{py:function} version_name(commit: str, made_at: str) -> str
:canonical: chartbook.versions.version_name

```{autodoc2-docstring} chartbook.versions.version_name
```
````
