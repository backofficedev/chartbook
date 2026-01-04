# {py:mod}`chartbook.build_docs`

```{py:module} chartbook.build_docs
```

```{autodoc2-docstring} chartbook.build_docs
:allowtitles:
```

## Module Contents

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
* - {py:obj}`run_sphinx_build <chartbook.build_docs.run_sphinx_build>`
  - ```{autodoc2-docstring} chartbook.build_docs.run_sphinx_build
    :summary:
    ```
````

### API

````{py:function} generate_docs(output_dir: pathlib.Path, project_dir: pathlib.Path, publish_dir: pathlib.Path = Path('./_output/to_be_published/'), _docs_dir: pathlib.Path = Path('./_docs'), keep_build_dirs: bool = False, temp_docs_src_dir: pathlib.Path = Path('_docs_src'), should_remove_existing: bool = False, size_threshold: float = 50)
:canonical: chartbook.build_docs.generate_docs

```{autodoc2-docstring} chartbook.build_docs.generate_docs
```
````

````{py:function} get_docs_src_path(pipeline_theme: str = 'pipeline')
:canonical: chartbook.build_docs.get_docs_src_path

```{autodoc2-docstring} chartbook.build_docs.get_docs_src_path
```
````

````{py:function} run_build_markdown(project_dir: pathlib.Path, pipeline_theme: str = 'catalog', publish_dir: pathlib.Path = Path('./_output/to_be_published/'), _docs_dir: pathlib.Path = Path('./_docs'), docs_src_dir: pathlib.Path = Path('_docs_src'), size_threshold: float = 50)
:canonical: chartbook.build_docs.run_build_markdown

```{autodoc2-docstring} chartbook.build_docs.run_build_markdown
```
````

````{py:function} run_sphinx_build(_docs_dir: pathlib.Path)
:canonical: chartbook.build_docs.run_sphinx_build

```{autodoc2-docstring} chartbook.build_docs.run_sphinx_build
```
````
