# {py:mod}`chartbook.sitefiles`

```{py:module} chartbook.sitefiles
```

```{autodoc2-docstring} chartbook.sitefiles
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`copy_files <chartbook.sitefiles.copy_files>`
  - ```{autodoc2-docstring} chartbook.sitefiles.copy_files
    :summary:
    ```
* - {py:obj}`copy_plan <chartbook.sitefiles.copy_plan>`
  - ```{autodoc2-docstring} chartbook.sitefiles.copy_plan
    :summary:
    ```
* - {py:obj}`copy_site_pages <chartbook.sitefiles.copy_site_pages>`
  - ```{autodoc2-docstring} chartbook.sitefiles.copy_site_pages
    :summary:
    ```
* - {py:obj}`copy_theme_files <chartbook.sitefiles.copy_theme_files>`
  - ```{autodoc2-docstring} chartbook.sitefiles.copy_theme_files
    :summary:
    ```
* - {py:obj}`downloadable <chartbook.sitefiles.downloadable>`
  - ```{autodoc2-docstring} chartbook.sitefiles.downloadable
    :summary:
    ```
* - {py:obj}`ensure_notebook_titles <chartbook.sitefiles.ensure_notebook_titles>`
  - ```{autodoc2-docstring} chartbook.sitefiles.ensure_notebook_titles
    :summary:
    ```
* - {py:obj}`not_built <chartbook.sitefiles.not_built>`
  - ```{autodoc2-docstring} chartbook.sitefiles.not_built
    :summary:
    ```
* - {py:obj}`not_built_text <chartbook.sitefiles.not_built_text>`
  - ```{autodoc2-docstring} chartbook.sitefiles.not_built_text
    :summary:
    ```
* - {py:obj}`write_not_built <chartbook.sitefiles.write_not_built>`
  - ```{autodoc2-docstring} chartbook.sitefiles.write_not_built
    :summary:
    ```
* - {py:obj}`write_site <chartbook.sitefiles.write_site>`
  - ```{autodoc2-docstring} chartbook.sitefiles.write_site
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`NOT_BUILT <chartbook.sitefiles.NOT_BUILT>`
  - ```{autodoc2-docstring} chartbook.sitefiles.NOT_BUILT
    :summary:
    ```
* - {py:obj}`NOT_BUILT_IN_VERSION <chartbook.sitefiles.NOT_BUILT_IN_VERSION>`
  - ```{autodoc2-docstring} chartbook.sitefiles.NOT_BUILT_IN_VERSION
    :summary:
    ```
* - {py:obj}`THEME_FILES_NOT_AT_ROOT <chartbook.sitefiles.THEME_FILES_NOT_AT_ROOT>`
  - ```{autodoc2-docstring} chartbook.sitefiles.THEME_FILES_NOT_AT_ROOT
    :summary:
    ```
* - {py:obj}`UNTRUSTED_SITE_FILES <chartbook.sitefiles.UNTRUSTED_SITE_FILES>`
  - ```{autodoc2-docstring} chartbook.sitefiles.UNTRUSTED_SITE_FILES
    :summary:
    ```
````

### API

````{py:data} NOT_BUILT
:canonical: chartbook.sitefiles.NOT_BUILT
:value: >
   "Not built yet. This is {path}, which the pipeline's build makes: {command} runs the build and render..."

```{autodoc2-docstring} chartbook.sitefiles.NOT_BUILT
```

````

````{py:data} NOT_BUILT_IN_VERSION
:canonical: chartbook.sitefiles.NOT_BUILT_IN_VERSION
:value: >
   'Not built in this version. This is {path}, which was not built when this version was made.'

```{autodoc2-docstring} chartbook.sitefiles.NOT_BUILT_IN_VERSION
```

````

````{py:data} THEME_FILES_NOT_AT_ROOT
:canonical: chartbook.sitefiles.THEME_FILES_NOT_AT_ROOT
:value: >
   ('charts', 'dataframes', 'notebooks', 'index.md', 'pipelines.md', 'dataframes.md', 'models', 'models...

```{autodoc2-docstring} chartbook.sitefiles.THEME_FILES_NOT_AT_ROOT
```

````

````{py:data} UNTRUSTED_SITE_FILES
:canonical: chartbook.sitefiles.UNTRUSTED_SITE_FILES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.sitefiles.UNTRUSTED_SITE_FILES
```

````

````{py:function} copy_files(plan: typing.Iterable[tuple[pathlib.Path, pathlib.Path]]) -> None
:canonical: chartbook.sitefiles.copy_files

```{autodoc2-docstring} chartbook.sitefiles.copy_files
```
````

````{py:function} copy_plan(index: dict, docs_build_dir: pathlib.Path, enable_data_download: bool = False, skip: typing.Iterable[str] = (), reused: typing.Iterable[str] = (), with_notes: bool = True) -> list[tuple[pathlib.Path, pathlib.Path]]
:canonical: chartbook.sitefiles.copy_plan

```{autodoc2-docstring} chartbook.sitefiles.copy_plan
```
````

````{py:function} copy_site_pages(index: dict, docs_build_dir: pathlib.Path) -> None
:canonical: chartbook.sitefiles.copy_site_pages

```{autodoc2-docstring} chartbook.sitefiles.copy_site_pages
```
````

````{py:function} copy_theme_files(docs_src_dir: pathlib.Path, docs_build_dir: pathlib.Path, charts: bool = True, templates: bool = True) -> None
:canonical: chartbook.sitefiles.copy_theme_files

```{autodoc2-docstring} chartbook.sitefiles.copy_theme_files
```
````

````{py:function} downloadable(record: dict) -> bool
:canonical: chartbook.sitefiles.downloadable

```{autodoc2-docstring} chartbook.sitefiles.downloadable
```
````

````{py:function} ensure_notebook_titles(index: dict, docs_build_dir: pathlib.Path, skip: typing.Iterable[str] = ()) -> None
:canonical: chartbook.sitefiles.ensure_notebook_titles

```{autodoc2-docstring} chartbook.sitefiles.ensure_notebook_titles
```
````

````{py:function} not_built(record: dict) -> bool
:canonical: chartbook.sitefiles.not_built

```{autodoc2-docstring} chartbook.sitefiles.not_built
```
````

````{py:function} not_built_text(path: str, command: str) -> str
:canonical: chartbook.sitefiles.not_built_text

```{autodoc2-docstring} chartbook.sitefiles.not_built_text
```
````

````{py:function} write_not_built(index: dict, docs_build_dir: pathlib.Path, skip: typing.Iterable[str] = ()) -> None
:canonical: chartbook.sitefiles.write_not_built

```{autodoc2-docstring} chartbook.sitefiles.write_not_built
```
````

````{py:function} write_site(docs_build_dir: pathlib.Path, base_dir: pathlib.Path, pipeline_theme: str = 'pipeline', docs_src_dir: typing.Optional[pathlib.Path] = None, size_threshold: float = 50, skip_pipelines: typing.Optional[typing.Iterable[str]] = None, reuse_pipelines: typing.Optional[typing.Iterable[str]] = None, code_times: typing.Optional[dict] = None, hash_cache=None, built_index: typing.Optional[dict] = None) -> dict
:canonical: chartbook.sitefiles.write_site

```{autodoc2-docstring} chartbook.sitefiles.write_site
```
````
