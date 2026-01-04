# {py:mod}`chartbook.markdown_generator`

```{py:module} chartbook.markdown_generator
```

```{autodoc2-docstring} chartbook.markdown_generator
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_all <chartbook.markdown_generator.build_all>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.build_all
    :summary:
    ```
* - {py:obj}`copy_docs_src_to_build <chartbook.markdown_generator.copy_docs_src_to_build>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.copy_docs_src_to_build
    :summary:
    ```
* - {py:obj}`find_most_recent_valid_datapoints <chartbook.markdown_generator.find_most_recent_valid_datapoints>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.find_most_recent_valid_datapoints
    :summary:
    ```
* - {py:obj}`generate_all_pipeline_docs <chartbook.markdown_generator.generate_all_pipeline_docs>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.generate_all_pipeline_docs
    :summary:
    ```
* - {py:obj}`generate_chart_docs <chartbook.markdown_generator.generate_chart_docs>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.generate_chart_docs
    :summary:
    ```
* - {py:obj}`generate_dataframe_docs <chartbook.markdown_generator.generate_dataframe_docs>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.generate_dataframe_docs
    :summary:
    ```
* - {py:obj}`generate_pipeline_docs <chartbook.markdown_generator.generate_pipeline_docs>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.generate_pipeline_docs
    :summary:
    ```
* - {py:obj}`get_dataframes_and_dataframe_docs <chartbook.markdown_generator.get_dataframes_and_dataframe_docs>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.get_dataframes_and_dataframe_docs
    :summary:
    ```
* - {py:obj}`get_package_templates_path <chartbook.markdown_generator.get_package_templates_path>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.get_package_templates_path
    :summary:
    ```
* - {py:obj}`get_sphinx_file_alignment_plan <chartbook.markdown_generator.get_sphinx_file_alignment_plan>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.get_sphinx_file_alignment_plan
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BASE_DIR <chartbook.markdown_generator.BASE_DIR>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.BASE_DIR
    :summary:
    ```
* - {py:obj}`DOCS_BUILD_DIR <chartbook.markdown_generator.DOCS_BUILD_DIR>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.DOCS_BUILD_DIR
    :summary:
    ```
* - {py:obj}`DOCS_SRC_DIR <chartbook.markdown_generator.DOCS_SRC_DIR>`
  - ```{autodoc2-docstring} chartbook.markdown_generator.DOCS_SRC_DIR
    :summary:
    ```
````

### API

````{py:data} BASE_DIR
:canonical: chartbook.markdown_generator.BASE_DIR
:value: >
   'resolve(...)'

```{autodoc2-docstring} chartbook.markdown_generator.BASE_DIR
```

````

````{py:data} DOCS_BUILD_DIR
:canonical: chartbook.markdown_generator.DOCS_BUILD_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.markdown_generator.DOCS_BUILD_DIR
```

````

````{py:data} DOCS_SRC_DIR
:canonical: chartbook.markdown_generator.DOCS_SRC_DIR
:value: >
   None

```{autodoc2-docstring} chartbook.markdown_generator.DOCS_SRC_DIR
```

````

````{py:function} build_all(docs_build_dir=DOCS_BUILD_DIR, base_dir=BASE_DIR, pipeline_theme='pipeline', docs_src_dir=DOCS_SRC_DIR, size_threshold=50)
:canonical: chartbook.markdown_generator.build_all

```{autodoc2-docstring} chartbook.markdown_generator.build_all
```
````

````{py:function} copy_docs_src_to_build(docs_src_dir, docs_build_dir, exclude_list=None)
:canonical: chartbook.markdown_generator.copy_docs_src_to_build

```{autodoc2-docstring} chartbook.markdown_generator.copy_docs_src_to_build
```
````

````{py:function} find_most_recent_valid_datapoints(parquet_path, date_col='date', size_threshold_mb=50)
:canonical: chartbook.markdown_generator.find_most_recent_valid_datapoints

```{autodoc2-docstring} chartbook.markdown_generator.find_most_recent_valid_datapoints
```
````

````{py:function} generate_all_pipeline_docs(manifest, docs_build_dir=DOCS_BUILD_DIR, base_dir=BASE_DIR, pipeline_theme='pipeline', docs_src_dir=DOCS_SRC_DIR, size_threshold=50)
:canonical: chartbook.markdown_generator.generate_all_pipeline_docs

```{autodoc2-docstring} chartbook.markdown_generator.generate_all_pipeline_docs
```
````

````{py:function} generate_chart_docs(chart_id, pipeline_id, pipeline_manifest, docs_build_dir=DOCS_BUILD_DIR, pipeline_base_dir=BASE_DIR, pipeline_theme='pipeline', docs_src_dir=DOCS_SRC_DIR)
:canonical: chartbook.markdown_generator.generate_chart_docs

```{autodoc2-docstring} chartbook.markdown_generator.generate_chart_docs
```
````

````{py:function} generate_dataframe_docs(dataframe_id, pipeline_id, pipeline_manifest, docs_build_dir=DOCS_BUILD_DIR, pipeline_base_dir=BASE_DIR, pipeline_theme='pipeline', docs_src_dir=DOCS_SRC_DIR, size_threshold=50)
:canonical: chartbook.markdown_generator.generate_dataframe_docs

```{autodoc2-docstring} chartbook.markdown_generator.generate_dataframe_docs
```
````

````{py:function} generate_pipeline_docs(pipeline_id, pipeline_manifest, pipeline_base_dir=BASE_DIR, docs_build_dir=DOCS_BUILD_DIR, pipeline_theme='pipeline', docs_src_dir=DOCS_SRC_DIR, size_threshold=50)
:canonical: chartbook.markdown_generator.generate_pipeline_docs

```{autodoc2-docstring} chartbook.markdown_generator.generate_pipeline_docs
```
````

````{py:function} get_dataframes_and_dataframe_docs(base_dir=BASE_DIR)
:canonical: chartbook.markdown_generator.get_dataframes_and_dataframe_docs

```{autodoc2-docstring} chartbook.markdown_generator.get_dataframes_and_dataframe_docs
```
````

````{py:function} get_package_templates_path() -> pathlib.Path
:canonical: chartbook.markdown_generator.get_package_templates_path

```{autodoc2-docstring} chartbook.markdown_generator.get_package_templates_path
```
````

````{py:function} get_sphinx_file_alignment_plan(base_dir=BASE_DIR, docs_build_dir=DOCS_BUILD_DIR)
:canonical: chartbook.markdown_generator.get_sphinx_file_alignment_plan

```{autodoc2-docstring} chartbook.markdown_generator.get_sphinx_file_alignment_plan
```
````
