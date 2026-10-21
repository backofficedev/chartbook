# {py:mod}`chartbook.build_docs`

```{py:module} chartbook.build_docs
```

```{autodoc2-docstring} chartbook.build_docs
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`IncrementalBuildSummary <chartbook.build_docs.IncrementalBuildSummary>`
  - ```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`generate_docs <chartbook.build_docs.generate_docs>`
  - ```{autodoc2-docstring} chartbook.build_docs.generate_docs
    :summary:
    ```
* - {py:obj}`get_docs_src_path <chartbook.build_docs.get_docs_src_path>`
  - ```{autodoc2-docstring} chartbook.build_docs.get_docs_src_path
    :summary:
    ```
* - {py:obj}`run_build_markdown <chartbook.build_docs.run_build_markdown>`
  - ```{autodoc2-docstring} chartbook.build_docs.run_build_markdown
    :summary:
    ```
* - {py:obj}`run_mkdocs_build <chartbook.build_docs.run_mkdocs_build>`
  - ```{autodoc2-docstring} chartbook.build_docs.run_mkdocs_build
    :summary:
    ```
* - {py:obj}`run_sphinx_build <chartbook.build_docs.run_sphinx_build>`
  - ```{autodoc2-docstring} chartbook.build_docs.run_sphinx_build
    :summary:
    ```
````

### API

`````{py:class} IncrementalBuildSummary
:canonical: chartbook.build_docs.IncrementalBuildSummary

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary
```

````{py:method} describe() -> str
:canonical: chartbook.build_docs.IncrementalBuildSummary.describe

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.describe
```

````

````{py:attribute} fresh
:canonical: chartbook.build_docs.IncrementalBuildSummary.fresh
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.fresh
```

````

````{py:attribute} output_written
:canonical: chartbook.build_docs.IncrementalBuildSummary.output_written
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.output_written
```

````

````{py:attribute} pages_read
:canonical: chartbook.build_docs.IncrementalBuildSummary.pages_read
:type: int | None
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.pages_read
```

````

````{py:attribute} reason
:canonical: chartbook.build_docs.IncrementalBuildSummary.reason
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.reason
```

````

````{py:attribute} regenerated
:canonical: chartbook.build_docs.IncrementalBuildSummary.regenerated
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.regenerated
```

````

````{py:attribute} rendered
:canonical: chartbook.build_docs.IncrementalBuildSummary.rendered
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.rendered
```

````

````{py:attribute} reused
:canonical: chartbook.build_docs.IncrementalBuildSummary.reused
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.reused
```

````

````{py:attribute} sources_deleted
:canonical: chartbook.build_docs.IncrementalBuildSummary.sources_deleted
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.sources_deleted
```

````

````{py:attribute} sources_written
:canonical: chartbook.build_docs.IncrementalBuildSummary.sources_written
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.build_docs.IncrementalBuildSummary.sources_written
```

````

`````

````{py:function} generate_docs(output_dir: pathlib.Path, project_dir: pathlib.Path, publish_dir: pathlib.Path = Path('./_output/to_be_published/'), _docs_dir: pathlib.Path = Path('./_docs'), keep_build_dirs: bool = False, temp_docs_src_dir: pathlib.Path = Path('_docs_src'), should_remove_existing: bool = False, size_threshold: float = 50, strict: typing.Optional[bool] = None, strip_mathjax2: bool = True, incremental: bool = False, after_build: bool = False)
:canonical: chartbook.build_docs.generate_docs

```{autodoc2-docstring} chartbook.build_docs.generate_docs
```
````

````{py:function} get_docs_src_path(pipeline_theme: str = 'pipeline', writer: str = 'sphinx')
:canonical: chartbook.build_docs.get_docs_src_path

```{autodoc2-docstring} chartbook.build_docs.get_docs_src_path
```
````

````{py:function} run_build_markdown(project_dir: pathlib.Path, pipeline_theme: str = 'catalog', publish_dir: pathlib.Path = Path('./_output/to_be_published/'), _docs_dir: pathlib.Path = Path('./_docs'), docs_src_dir: pathlib.Path = Path('_docs_src'), size_threshold: float = 50, skip_pipelines: set[str] | None = None, reuse_pipelines: set[str] | None = None, code_times: dict[str, str] | None = None, hash_cache=None, built_index: dict | None = None)
:canonical: chartbook.build_docs.run_build_markdown

```{autodoc2-docstring} chartbook.build_docs.run_build_markdown
```
````

````{py:function} run_mkdocs_build(_docs_dir: pathlib.Path) -> str
:canonical: chartbook.build_docs.run_mkdocs_build

```{autodoc2-docstring} chartbook.build_docs.run_mkdocs_build
```
````

````{py:function} run_sphinx_build(_docs_dir: pathlib.Path)
:canonical: chartbook.build_docs.run_sphinx_build

```{autodoc2-docstring} chartbook.build_docs.run_sphinx_build
```
````
