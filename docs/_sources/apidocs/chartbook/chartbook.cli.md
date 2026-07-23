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

* - {py:obj}`browse <chartbook.cli.browse>`
  - ```{autodoc2-docstring} chartbook.cli.browse
    :summary:
    ```
* - {py:obj}`build <chartbook.cli.build>`
  - ```{autodoc2-docstring} chartbook.cli.build
    :summary:
    ```
* - {py:obj}`catalog <chartbook.cli.catalog>`
  - ```{autodoc2-docstring} chartbook.cli.catalog
    :summary:
    ```
* - {py:obj}`catalog_add <chartbook.cli.catalog_add>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_add
    :summary:
    ```
* - {py:obj}`catalog_browse <chartbook.cli.catalog_browse>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_browse
    :summary:
    ```
* - {py:obj}`catalog_build <chartbook.cli.catalog_build>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_build
    :summary:
    ```
* - {py:obj}`catalog_disable <chartbook.cli.catalog_disable>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_disable
    :summary:
    ```
* - {py:obj}`catalog_enable <chartbook.cli.catalog_enable>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_enable
    :summary:
    ```
* - {py:obj}`catalog_init <chartbook.cli.catalog_init>`
  - ```{autodoc2-docstring} chartbook.cli.catalog_init
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
* - {py:obj}`init <chartbook.cli.init>`
  - ```{autodoc2-docstring} chartbook.cli.init
    :summary:
    ```
* - {py:obj}`install <chartbook.cli.install>`
  - ```{autodoc2-docstring} chartbook.cli.install
    :summary:
    ```
* - {py:obj}`install_skill <chartbook.cli.install_skill>`
  - ```{autodoc2-docstring} chartbook.cli.install_skill
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

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`VERSION_STAMP_NAME <chartbook.cli.VERSION_STAMP_NAME>`
  - ```{autodoc2-docstring} chartbook.cli.VERSION_STAMP_NAME
    :summary:
    ```
````

### API

````{py:data} VERSION_STAMP_NAME
:canonical: chartbook.cli.VERSION_STAMP_NAME
:value: >
   '.chartbook-skill-version'

```{autodoc2-docstring} chartbook.cli.VERSION_STAMP_NAME
```

````

````{py:function} browse(output_dir, project_dir)
:canonical: chartbook.cli.browse

```{autodoc2-docstring} chartbook.cli.browse
```
````

````{py:function} build(output_dir, project_dir, publish_dir, docs_build_dir, temp_docs_src_dir, keep_build_dirs, force_write, size_threshold, strict, strip_mathjax2)
:canonical: chartbook.cli.build

```{autodoc2-docstring} chartbook.cli.build
```
````

````{py:function} catalog()
:canonical: chartbook.cli.catalog

```{autodoc2-docstring} chartbook.cli.catalog
```
````

````{py:function} catalog_add(paths, catalog_path, yes)
:canonical: chartbook.cli.catalog_add

```{autodoc2-docstring} chartbook.cli.catalog_add
```
````

````{py:function} catalog_browse()
:canonical: chartbook.cli.catalog_browse

```{autodoc2-docstring} chartbook.cli.catalog_browse
```
````

````{py:function} catalog_build(force_write, strict)
:canonical: chartbook.cli.catalog_build

```{autodoc2-docstring} chartbook.cli.catalog_build
```
````

````{py:function} catalog_disable(pipeline_id, catalog_path)
:canonical: chartbook.cli.catalog_disable

```{autodoc2-docstring} chartbook.cli.catalog_disable
```
````

````{py:function} catalog_enable(pipeline_id, catalog_path)
:canonical: chartbook.cli.catalog_enable

```{autodoc2-docstring} chartbook.cli.catalog_enable
```
````

````{py:function} catalog_init(title)
:canonical: chartbook.cli.catalog_init

```{autodoc2-docstring} chartbook.cli.catalog_init
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

````{py:function} init()
:canonical: chartbook.cli.init

```{autodoc2-docstring} chartbook.cli.init
```
````

````{py:function} install()
:canonical: chartbook.cli.install

```{autodoc2-docstring} chartbook.cli.install
```
````

````{py:function} install_skill(force, project)
:canonical: chartbook.cli.install_skill

```{autodoc2-docstring} chartbook.cli.install_skill
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
