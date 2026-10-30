# {py:mod}`chartbook.writers.mkdocs`

```{py:module} chartbook.writers.mkdocs
```

```{autodoc2-docstring} chartbook.writers.mkdocs
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MkDocsWriter <chartbook.writers.mkdocs.MkDocsWriter>`
  - ```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`is_installed <chartbook.writers.mkdocs.is_installed>`
  - ```{autodoc2-docstring} chartbook.writers.mkdocs.is_installed
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`EXTRA <chartbook.writers.mkdocs.EXTRA>`
  - ```{autodoc2-docstring} chartbook.writers.mkdocs.EXTRA
    :summary:
    ```
* - {py:obj}`PAGES_DIR <chartbook.writers.mkdocs.PAGES_DIR>`
  - ```{autodoc2-docstring} chartbook.writers.mkdocs.PAGES_DIR
    :summary:
    ```
````

### API

````{py:data} EXTRA
:canonical: chartbook.writers.mkdocs.EXTRA
:value: >
   'chartbook[mkdocs]'

```{autodoc2-docstring} chartbook.writers.mkdocs.EXTRA
```

````

`````{py:class} MkDocsWriter
:canonical: chartbook.writers.mkdocs.MkDocsWriter

Bases: {py:obj}`chartbook.writers.sphinx.SphinxWriter`

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter
```

````{py:attribute} CATALOG_PAGES
:canonical: chartbook.writers.mkdocs.MkDocsWriter.CATALOG_PAGES
:value: >
   ('index.md', 'cb/charts.md', 'cb/dataframes.md', 'cb/models.md', 'cb/files.md', 'cb/pipelines.md', '...

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.CATALOG_PAGES
```

````

````{py:attribute} THEME_TEMPLATES_IN_SITE
:canonical: chartbook.writers.mkdocs.MkDocsWriter.THEME_TEMPLATES_IN_SITE
:value: >
   False

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.THEME_TEMPLATES_IN_SITE
```

````

````{py:method} catalog_page(page_path: str) -> str
:canonical: chartbook.writers.mkdocs.MkDocsWriter.catalog_page

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.catalog_page
```

````

````{py:method} config(site_name: str, site_url: str = '', copyright: str = '', site_dir: str = '_build/html') -> dict
:canonical: chartbook.writers.mkdocs.MkDocsWriter.config

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.config
```

````

````{py:method} own_page(page_path: str) -> str
:canonical: chartbook.writers.mkdocs.MkDocsWriter.own_page

````

````{py:method} own_page_paths() -> list
:canonical: chartbook.writers.mkdocs.MkDocsWriter.own_page_paths

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.own_page_paths
```

````

````{py:method} pipeline_page(pipeline_id: str) -> str
:canonical: chartbook.writers.mkdocs.MkDocsWriter.pipeline_page

```{autodoc2-docstring} chartbook.writers.mkdocs.MkDocsWriter.pipeline_page
```

````

`````

````{py:data} PAGES_DIR
:canonical: chartbook.writers.mkdocs.PAGES_DIR
:value: >
   'pages'

```{autodoc2-docstring} chartbook.writers.mkdocs.PAGES_DIR
```

````

````{py:function} is_installed() -> bool
:canonical: chartbook.writers.mkdocs.is_installed

```{autodoc2-docstring} chartbook.writers.mkdocs.is_installed
```
````
