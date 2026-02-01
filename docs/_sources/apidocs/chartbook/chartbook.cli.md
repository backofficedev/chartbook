# {py:mod}`chartbook.cli`

```{py:module} chartbook.cli
```

```{autodoc2-docstring} chartbook.cli
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build <chartbook.cli.build>`
  - ```{autodoc2-docstring} chartbook.cli.build
    :summary:
    ```
* - {py:obj}`config <chartbook.cli.config>`
  - ```{autodoc2-docstring} chartbook.cli.config
    :summary:
    ```
* - {py:obj}`create_data_glimpses <chartbook.cli.create_data_glimpses>`
  - ```{autodoc2-docstring} chartbook.cli.create_data_glimpses
    :summary:
    ```
* - {py:obj}`data <chartbook.cli.data>`
  - ```{autodoc2-docstring} chartbook.cli.data
    :summary:
    ```
* - {py:obj}`data_get_docs <chartbook.cli.data_get_docs>`
  - ```{autodoc2-docstring} chartbook.cli.data_get_docs
    :summary:
    ```
* - {py:obj}`data_get_docs_path <chartbook.cli.data_get_docs_path>`
  - ```{autodoc2-docstring} chartbook.cli.data_get_docs_path
    :summary:
    ```
* - {py:obj}`data_get_path <chartbook.cli.data_get_path>`
  - ```{autodoc2-docstring} chartbook.cli.data_get_path
    :summary:
    ```
* - {py:obj}`ls <chartbook.cli.ls>`
  - ```{autodoc2-docstring} chartbook.cli.ls
    :summary:
    ```
* - {py:obj}`ls_charts <chartbook.cli.ls_charts>`
  - ```{autodoc2-docstring} chartbook.cli.ls_charts
    :summary:
    ```
* - {py:obj}`ls_dataframes <chartbook.cli.ls_dataframes>`
  - ```{autodoc2-docstring} chartbook.cli.ls_dataframes
    :summary:
    ```
* - {py:obj}`ls_pipelines <chartbook.cli.ls_pipelines>`
  - ```{autodoc2-docstring} chartbook.cli.ls_pipelines
    :summary:
    ```
* - {py:obj}`main <chartbook.cli.main>`
  - ```{autodoc2-docstring} chartbook.cli.main
    :summary:
    ```
* - {py:obj}`publish <chartbook.cli.publish>`
  - ```{autodoc2-docstring} chartbook.cli.publish
    :summary:
    ```
* - {py:obj}`resolve_project_dir <chartbook.cli.resolve_project_dir>`
  - ```{autodoc2-docstring} chartbook.cli.resolve_project_dir
    :summary:
    ```
````

### API

````{py:function} build(output_dir, project_dir, publish_dir, docs_build_dir, temp_docs_src_dir, keep_build_dirs, force_write, size_threshold, warn_missing)
:canonical: chartbook.cli.build

```{autodoc2-docstring} chartbook.cli.build
```
````

````{py:function} config()
:canonical: chartbook.cli.config

```{autodoc2-docstring} chartbook.cli.config
```
````

````{py:function} create_data_glimpses(no_samples, no_stats, output_dir, size_threshold)
:canonical: chartbook.cli.create_data_glimpses

```{autodoc2-docstring} chartbook.cli.create_data_glimpses
```
````

````{py:function} data()
:canonical: chartbook.cli.data

```{autodoc2-docstring} chartbook.cli.data
```
````

````{py:function} data_get_docs(pipeline, dataframe, catalog)
:canonical: chartbook.cli.data_get_docs

```{autodoc2-docstring} chartbook.cli.data_get_docs
```
````

````{py:function} data_get_docs_path(pipeline, dataframe, catalog)
:canonical: chartbook.cli.data_get_docs_path

```{autodoc2-docstring} chartbook.cli.data_get_docs_path
```
````

````{py:function} data_get_path(pipeline, dataframe, catalog)
:canonical: chartbook.cli.data_get_path

```{autodoc2-docstring} chartbook.cli.data_get_path
```
````

````{py:function} ls(ctx, catalog)
:canonical: chartbook.cli.ls

```{autodoc2-docstring} chartbook.cli.ls
```
````

````{py:function} ls_charts(ctx)
:canonical: chartbook.cli.ls_charts

```{autodoc2-docstring} chartbook.cli.ls_charts
```
````

````{py:function} ls_dataframes(ctx)
:canonical: chartbook.cli.ls_dataframes

```{autodoc2-docstring} chartbook.cli.ls_dataframes
```
````

````{py:function} ls_pipelines(ctx)
:canonical: chartbook.cli.ls_pipelines

```{autodoc2-docstring} chartbook.cli.ls_pipelines
```
````

````{py:function} main()
:canonical: chartbook.cli.main

```{autodoc2-docstring} chartbook.cli.main
```
````

````{py:function} publish(publish_dir: pathlib.Path | str | None, project_dir: pathlib.Path | str, verbose: bool)
:canonical: chartbook.cli.publish

```{autodoc2-docstring} chartbook.cli.publish
```
````

````{py:function} resolve_project_dir(project_dir: pathlib.Path | None)
:canonical: chartbook.cli.resolve_project_dir

```{autodoc2-docstring} chartbook.cli.resolve_project_dir
```
````
