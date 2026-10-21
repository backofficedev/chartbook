# {py:mod}`chartbook.scaffold`

```{py:module} chartbook.scaffold
```

```{autodoc2-docstring} chartbook.scaffold
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Rendered <chartbook.scaffold.Rendered>`
  - ```{autodoc2-docstring} chartbook.scaffold.Rendered
    :summary:
    ```
* - {py:obj}`TemplateSource <chartbook.scaffold.TemplateSource>`
  - ```{autodoc2-docstring} chartbook.scaffold.TemplateSource
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`commit_is_pushed <chartbook.scaffold.commit_is_pushed>`
  - ```{autodoc2-docstring} chartbook.scaffold.commit_is_pushed
    :summary:
    ```
* - {py:obj}`enclosing_repository <chartbook.scaffold.enclosing_repository>`
  - ```{autodoc2-docstring} chartbook.scaffold.enclosing_repository
    :summary:
    ```
* - {py:obj}`find_template <chartbook.scaffold.find_template>`
  - ```{autodoc2-docstring} chartbook.scaffold.find_template
    :summary:
    ```
* - {py:obj}`git_init_and_commit <chartbook.scaffold.git_init_and_commit>`
  - ```{autodoc2-docstring} chartbook.scaffold.git_init_and_commit
    :summary:
    ```
* - {py:obj}`github_create_and_push <chartbook.scaffold.github_create_and_push>`
  - ```{autodoc2-docstring} chartbook.scaffold.github_create_and_push
    :summary:
    ```
* - {py:obj}`github_host <chartbook.scaffold.github_host>`
  - ```{autodoc2-docstring} chartbook.scaffold.github_host
    :summary:
    ```
* - {py:obj}`preflight <chartbook.scaffold.preflight>`
  - ```{autodoc2-docstring} chartbook.scaffold.preflight
    :summary:
    ```
* - {py:obj}`render <chartbook.scaffold.render>`
  - ```{autodoc2-docstring} chartbook.scaffold.render
    :summary:
    ```
* - {py:obj}`template_commit <chartbook.scaffold.template_commit>`
  - ```{autodoc2-docstring} chartbook.scaffold.template_commit
    :summary:
    ```
* - {py:obj}`template_source <chartbook.scaffold.template_source>`
  - ```{autodoc2-docstring} chartbook.scaffold.template_source
    :summary:
    ```
* - {py:obj}`write_cruft_file <chartbook.scaffold.write_cruft_file>`
  - ```{autodoc2-docstring} chartbook.scaffold.write_cruft_file
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BUILT_FROM <chartbook.scaffold.BUILT_FROM>`
  - ```{autodoc2-docstring} chartbook.scaffold.BUILT_FROM
    :summary:
    ```
* - {py:obj}`CRUFT_MARKER <chartbook.scaffold.CRUFT_MARKER>`
  - ```{autodoc2-docstring} chartbook.scaffold.CRUFT_MARKER
    :summary:
    ```
* - {py:obj}`DEFAULT_BRANCH <chartbook.scaffold.DEFAULT_BRANCH>`
  - ```{autodoc2-docstring} chartbook.scaffold.DEFAULT_BRANCH
    :summary:
    ```
* - {py:obj}`INITIAL_COMMIT_MESSAGE <chartbook.scaffold.INITIAL_COMMIT_MESSAGE>`
  - ```{autodoc2-docstring} chartbook.scaffold.INITIAL_COMMIT_MESSAGE
    :summary:
    ```
* - {py:obj}`TEMPLATE_DIRECTORY <chartbook.scaffold.TEMPLATE_DIRECTORY>`
  - ```{autodoc2-docstring} chartbook.scaffold.TEMPLATE_DIRECTORY
    :summary:
    ```
* - {py:obj}`TEMPLATE_REPOSITORY <chartbook.scaffold.TEMPLATE_REPOSITORY>`
  - ```{autodoc2-docstring} chartbook.scaffold.TEMPLATE_REPOSITORY
    :summary:
    ```
````

### API

````{py:data} BUILT_FROM
:canonical: chartbook.scaffold.BUILT_FROM
:value: >
   'built_from.txt'

```{autodoc2-docstring} chartbook.scaffold.BUILT_FROM
```

````

````{py:data} CRUFT_MARKER
:canonical: chartbook.scaffold.CRUFT_MARKER
:value: >
   '.cruft.json'

```{autodoc2-docstring} chartbook.scaffold.CRUFT_MARKER
```

````

````{py:data} DEFAULT_BRANCH
:canonical: chartbook.scaffold.DEFAULT_BRANCH
:value: >
   'main'

```{autodoc2-docstring} chartbook.scaffold.DEFAULT_BRANCH
```

````

````{py:data} INITIAL_COMMIT_MESSAGE
:canonical: chartbook.scaffold.INITIAL_COMMIT_MESSAGE
:value: >
   'Initial commit from chartbook init'

```{autodoc2-docstring} chartbook.scaffold.INITIAL_COMMIT_MESSAGE
```

````

````{py:exception} ProjectExistsError(folder: pathlib.Path)
:canonical: chartbook.scaffold.ProjectExistsError

Bases: {py:obj}`chartbook.scaffold.ScaffoldError`

```{autodoc2-docstring} chartbook.scaffold.ProjectExistsError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.scaffold.ProjectExistsError.__init__
```

````

`````{py:class} Rendered
:canonical: chartbook.scaffold.Rendered

```{autodoc2-docstring} chartbook.scaffold.Rendered
```

````{py:attribute} answers
:canonical: chartbook.scaffold.Rendered.answers
:type: typing.Optional[dict]
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.Rendered.answers
```

````

````{py:attribute} commit
:canonical: chartbook.scaffold.Rendered.commit
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.Rendered.commit
```

````

````{py:method} link_command(commit: str = '<commit>') -> str
:canonical: chartbook.scaffold.Rendered.link_command

```{autodoc2-docstring} chartbook.scaffold.Rendered.link_command
```

````

````{py:attribute} project_dir
:canonical: chartbook.scaffold.Rendered.project_dir
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.Rendered.project_dir
```

````

````{py:attribute} pushed
:canonical: chartbook.scaffold.Rendered.pushed
:type: typing.Optional[bool]
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.Rendered.pushed
```

````

````{py:attribute} why
:canonical: chartbook.scaffold.Rendered.why
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.scaffold.Rendered.why
```

````

`````

````{py:exception} ScaffoldError()
:canonical: chartbook.scaffold.ScaffoldError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.scaffold.ScaffoldError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.scaffold.ScaffoldError.__init__
```

````

````{py:data} TEMPLATE_DIRECTORY
:canonical: chartbook.scaffold.TEMPLATE_DIRECTORY
:value: >
   'template'

```{autodoc2-docstring} chartbook.scaffold.TEMPLATE_DIRECTORY
```

````

````{py:data} TEMPLATE_REPOSITORY
:canonical: chartbook.scaffold.TEMPLATE_REPOSITORY
:value: >
   'https://github.com/backofficedev/chartbook'

```{autodoc2-docstring} chartbook.scaffold.TEMPLATE_REPOSITORY
```

````

`````{py:class} TemplateSource
:canonical: chartbook.scaffold.TemplateSource

```{autodoc2-docstring} chartbook.scaffold.TemplateSource
```

````{py:attribute} checkout
:canonical: chartbook.scaffold.TemplateSource.checkout
:type: typing.Optional[pathlib.Path]
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.TemplateSource.checkout
```

````

````{py:attribute} commit
:canonical: chartbook.scaffold.TemplateSource.commit
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.TemplateSource.commit
```

````

````{py:attribute} template
:canonical: chartbook.scaffold.TemplateSource.template
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.scaffold.TemplateSource.template
```

````

````{py:attribute} why
:canonical: chartbook.scaffold.TemplateSource.why
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.scaffold.TemplateSource.why
```

````

`````

````{py:function} commit_is_pushed(commit: str, package_dir: typing.Optional[pathlib.Path] = None) -> typing.Optional[bool]
:canonical: chartbook.scaffold.commit_is_pushed

```{autodoc2-docstring} chartbook.scaffold.commit_is_pushed
```
````

````{py:function} enclosing_repository(cwd: pathlib.Path) -> typing.Optional[str]
:canonical: chartbook.scaffold.enclosing_repository

```{autodoc2-docstring} chartbook.scaffold.enclosing_repository
```
````

````{py:function} find_template(package_dir: typing.Optional[pathlib.Path] = None) -> pathlib.Path
:canonical: chartbook.scaffold.find_template

```{autodoc2-docstring} chartbook.scaffold.find_template
```
````

````{py:function} git_init_and_commit(project_dir: pathlib.Path) -> None
:canonical: chartbook.scaffold.git_init_and_commit

```{autodoc2-docstring} chartbook.scaffold.git_init_and_commit
```
````

````{py:function} github_create_and_push(project_dir: pathlib.Path, public: bool = False) -> str
:canonical: chartbook.scaffold.github_create_and_push

```{autodoc2-docstring} chartbook.scaffold.github_create_and_push
```
````

````{py:function} github_host() -> str
:canonical: chartbook.scaffold.github_host

```{autodoc2-docstring} chartbook.scaffold.github_host
```
````

````{py:function} preflight(cwd: pathlib.Path, use_github: bool) -> None
:canonical: chartbook.scaffold.preflight

```{autodoc2-docstring} chartbook.scaffold.preflight
```
````

````{py:function} render(output_dir: pathlib.Path, no_input: bool = False, answers: typing.Optional[dict] = None, package_dir: typing.Optional[pathlib.Path] = None) -> chartbook.scaffold.Rendered
:canonical: chartbook.scaffold.render

```{autodoc2-docstring} chartbook.scaffold.render
```
````

````{py:function} template_commit(package_dir: typing.Optional[pathlib.Path] = None) -> typing.Optional[str]
:canonical: chartbook.scaffold.template_commit

```{autodoc2-docstring} chartbook.scaffold.template_commit
```
````

````{py:function} template_source(package_dir: typing.Optional[pathlib.Path] = None) -> chartbook.scaffold.TemplateSource
:canonical: chartbook.scaffold.template_source

```{autodoc2-docstring} chartbook.scaffold.template_source
```
````

````{py:function} write_cruft_file(project_dir: pathlib.Path, context: dict, commit: str) -> pathlib.Path
:canonical: chartbook.scaffold.write_cruft_file

```{autodoc2-docstring} chartbook.scaffold.write_cruft_file
```
````
