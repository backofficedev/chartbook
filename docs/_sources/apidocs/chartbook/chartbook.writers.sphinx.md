# {py:mod}`chartbook.writers.sphinx`

```{py:module} chartbook.writers.sphinx
```

```{autodoc2-docstring} chartbook.writers.sphinx
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SphinxWriter <chartbook.writers.sphinx.SphinxWriter>`
  - ```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`check_front_matter <chartbook.writers.sphinx.check_front_matter>`
  - ```{autodoc2-docstring} chartbook.writers.sphinx.check_front_matter
    :summary:
    ```
* - {py:obj}`freshness_fact <chartbook.writers.sphinx.freshness_fact>`
  - ```{autodoc2-docstring} chartbook.writers.sphinx.freshness_fact
    :summary:
    ```
* - {py:obj}`yaml_escape <chartbook.writers.sphinx.yaml_escape>`
  - ```{autodoc2-docstring} chartbook.writers.sphinx.yaml_escape
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`OVERRIDABLE_TEMPLATES <chartbook.writers.sphinx.OVERRIDABLE_TEMPLATES>`
  - ```{autodoc2-docstring} chartbook.writers.sphinx.OVERRIDABLE_TEMPLATES
    :summary:
    ```
````

### API

````{py:data} OVERRIDABLE_TEMPLATES
:canonical: chartbook.writers.sphinx.OVERRIDABLE_TEMPLATES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.writers.sphinx.OVERRIDABLE_TEMPLATES
```

````

`````{py:class} SphinxWriter
:canonical: chartbook.writers.sphinx.SphinxWriter

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter
```

````{py:attribute} ASSISTANT_FILE
:canonical: chartbook.writers.sphinx.SphinxWriter.ASSISTANT_FILE
:value: >
   None

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.ASSISTANT_FILE
```

````

````{py:attribute} ASSISTANT_SECTIONS
:canonical: chartbook.writers.sphinx.SphinxWriter.ASSISTANT_SECTIONS
:value: >
   (('Pipeline', 'Pipelines'), ('Dataframe', 'Dataframes'), ('Chart', 'Charts'), ('Model', 'Models'))

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.ASSISTANT_SECTIONS
```

````

````{py:attribute} ASSISTANT_VERSIONS
:canonical: chartbook.writers.sphinx.SphinxWriter.ASSISTANT_VERSIONS
:value: >
   10

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.ASSISTANT_VERSIONS
```

````

````{py:attribute} CATALOG_PAGES
:canonical: chartbook.writers.sphinx.SphinxWriter.CATALOG_PAGES
:value: >
   ('index.md', 'cb/dataframes.md', 'cb/models.md', 'cb/pipelines.md', 'cb/diagnostics.md', 'cb/version...

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.CATALOG_PAGES
```

````

````{py:attribute} THEME_TEMPLATES_IN_SITE
:canonical: chartbook.writers.sphinx.SphinxWriter.THEME_TEMPLATES_IN_SITE
:value: >
   True

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.THEME_TEMPLATES_IN_SITE
```

````

````{py:method} assistant_file() -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.assistant_file

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.assistant_file
```

````

````{py:method} catalog_page(page_path: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.catalog_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.catalog_page
```

````

````{py:method} catalog_page_paths() -> list
:canonical: chartbook.writers.sphinx.SphinxWriter.catalog_page_paths

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.catalog_page_paths
```

````

````{py:method} chart_page(record_id: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.chart_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.chart_page
```

````

````{py:method} chart_page_path(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.chart_page_path

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.chart_page_path
```

````

````{py:method} dataframe_page(record_id: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.dataframe_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.dataframe_page
```

````

````{py:method} dataframe_page_path(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.dataframe_page_path

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.dataframe_page_path
```

````

````{py:attribute} docs_src_dir
:canonical: chartbook.writers.sphinx.SphinxWriter.docs_src_dir
:type: typing.Optional[pathlib.Path]
:value: >
   None

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.docs_src_dir
```

````

````{py:attribute} enable_data_download
:canonical: chartbook.writers.sphinx.SphinxWriter.enable_data_download
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.enable_data_download
```

````

````{py:method} from_the_store_assets(kinds: tuple, from_path: str, pipeline_id: typing.Optional[str] = None) -> list
:canonical: chartbook.writers.sphinx.SphinxWriter.from_the_store_assets

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.from_the_store_assets
```

````

````{py:attribute} index
:canonical: chartbook.writers.sphinx.SphinxWriter.index
:type: dict
:value: >
   None

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.index
```

````

````{py:method} link_to_dataframe(record: dict, from_kind: str = 'Dataframe') -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.link_to_dataframe

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.link_to_dataframe
```

````

````{py:method} model_page(record_id: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.model_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.model_page
```

````

````{py:method} model_page_path(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.model_page_path

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.model_page_path
```

````

````{py:method} own_page(page_path: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.own_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.own_page
```

````

````{py:method} own_page_paths() -> list
:canonical: chartbook.writers.sphinx.SphinxWriter.own_page_paths

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.own_page_paths
```

````

````{py:method} page(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.page
```

````

````{py:method} page_path(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.page_path

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.page_path
```

````

````{py:method} pipeline_page(pipeline_id: str) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.pipeline_page

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.pipeline_page
```

````

````{py:method} pipeline_page_link(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.pipeline_page_link

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.pipeline_page_link
```

````

````{py:method} pipeline_page_path(record: dict) -> str
:canonical: chartbook.writers.sphinx.SphinxWriter.pipeline_page_path

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.pipeline_page_path
```

````

````{py:attribute} records
:canonical: chartbook.writers.sphinx.SphinxWriter.records
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.records
```

````

````{py:attribute} size_threshold
:canonical: chartbook.writers.sphinx.SphinxWriter.size_threshold
:type: float
:value: >
   50

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.size_threshold
```

````

````{py:attribute} theme
:canonical: chartbook.writers.sphinx.SphinxWriter.theme
:type: str
:value: >
   'pipeline'

```{autodoc2-docstring} chartbook.writers.sphinx.SphinxWriter.theme
```

````

`````

````{py:function} check_front_matter(page: pathlib.Path, pipeline_id: str, chart_id: str) -> None
:canonical: chartbook.writers.sphinx.check_front_matter

```{autodoc2-docstring} chartbook.writers.sphinx.check_front_matter
```
````

````{py:function} freshness_fact(label: str, moment: typing.Optional[datetime.datetime]) -> typing.Optional[dict]
:canonical: chartbook.writers.sphinx.freshness_fact

```{autodoc2-docstring} chartbook.writers.sphinx.freshness_fact
```
````

````{py:function} yaml_escape(value) -> str
:canonical: chartbook.writers.sphinx.yaml_escape

```{autodoc2-docstring} chartbook.writers.sphinx.yaml_escape
```
````
