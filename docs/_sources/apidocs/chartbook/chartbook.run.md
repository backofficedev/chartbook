# {py:mod}`chartbook.run`

```{py:module} chartbook.run
```

```{autodoc2-docstring} chartbook.run
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`RunReport <chartbook.run.RunReport>`
  - ```{autodoc2-docstring} chartbook.run.RunReport
    :summary:
    ```
* - {py:obj}`Step <chartbook.run.Step>`
  - ```{autodoc2-docstring} chartbook.run.Step
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_tool_runs_chartbook_build <chartbook.run.build_tool_runs_chartbook_build>`
  - ```{autodoc2-docstring} chartbook.run.build_tool_runs_chartbook_build
    :summary:
    ```
* - {py:obj}`execute <chartbook.run.execute>`
  - ```{autodoc2-docstring} chartbook.run.execute
    :summary:
    ```
* - {py:obj}`kept_missing <chartbook.run.kept_missing>`
  - ```{autodoc2-docstring} chartbook.run.kept_missing
    :summary:
    ```
* - {py:obj}`plan <chartbook.run.plan>`
  - ```{autodoc2-docstring} chartbook.run.plan
    :summary:
    ```
* - {py:obj}`run <chartbook.run.run>`
  - ```{autodoc2-docstring} chartbook.run.run
    :summary:
    ```
* - {py:obj}`running <chartbook.run.running>`
  - ```{autodoc2-docstring} chartbook.run.running
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BUILD_TOOL_FILES <chartbook.run.BUILD_TOOL_FILES>`
  - ```{autodoc2-docstring} chartbook.run.BUILD_TOOL_FILES
    :summary:
    ```
* - {py:obj}`RUN_DIR_ENV_VAR <chartbook.run.RUN_DIR_ENV_VAR>`
  - ```{autodoc2-docstring} chartbook.run.RUN_DIR_ENV_VAR
    :summary:
    ```
* - {py:obj}`RUN_SCRIPT_ENV_VAR <chartbook.run.RUN_SCRIPT_ENV_VAR>`
  - ```{autodoc2-docstring} chartbook.run.RUN_SCRIPT_ENV_VAR
    :summary:
    ```
* - {py:obj}`RUN_STACK_ENV_VAR <chartbook.run.RUN_STACK_ENV_VAR>`
  - ```{autodoc2-docstring} chartbook.run.RUN_STACK_ENV_VAR
    :summary:
    ```
````

### API

````{py:data} BUILD_TOOL_FILES
:canonical: chartbook.run.BUILD_TOOL_FILES
:value: >
   None

```{autodoc2-docstring} chartbook.run.BUILD_TOOL_FILES
```

````

````{py:data} RUN_DIR_ENV_VAR
:canonical: chartbook.run.RUN_DIR_ENV_VAR
:value: >
   'CHARTBOOK_RUN_DIR'

```{autodoc2-docstring} chartbook.run.RUN_DIR_ENV_VAR
```

````

````{py:data} RUN_SCRIPT_ENV_VAR
:canonical: chartbook.run.RUN_SCRIPT_ENV_VAR
:value: >
   'CHARTBOOK_RUN_SCRIPT'

```{autodoc2-docstring} chartbook.run.RUN_SCRIPT_ENV_VAR
```

````

````{py:data} RUN_STACK_ENV_VAR
:canonical: chartbook.run.RUN_STACK_ENV_VAR
:value: >
   'CHARTBOOK_RUN_STACK'

```{autodoc2-docstring} chartbook.run.RUN_STACK_ENV_VAR
```

````

````{py:exception} RunError()
:canonical: chartbook.run.RunError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.run.RunError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.run.RunError.__init__
```

````

`````{py:class} RunReport
:canonical: chartbook.run.RunReport

```{autodoc2-docstring} chartbook.run.RunReport
```

````{py:attribute} exit_code
:canonical: chartbook.run.RunReport.exit_code
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.run.RunReport.exit_code
```

````

````{py:attribute} failed
:canonical: chartbook.run.RunReport.failed
:type: typing.Optional[chartbook.run.Step]
:value: >
   None

```{autodoc2-docstring} chartbook.run.RunReport.failed
```

````

````{py:attribute} ran
:canonical: chartbook.run.RunReport.ran
:type: list[chartbook.run.Step]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.run.RunReport.ran
```

````

````{py:attribute} reason
:canonical: chartbook.run.RunReport.reason
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.run.RunReport.reason
```

````

````{py:attribute} script
:canonical: chartbook.run.RunReport.script
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.run.RunReport.script
```

````

````{py:attribute} skipped
:canonical: chartbook.run.RunReport.skipped
:type: list[tuple[chartbook.run.Step, str]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.run.RunReport.skipped
```

````

````{py:attribute} snapshots
:canonical: chartbook.run.RunReport.snapshots
:type: list
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.run.RunReport.snapshots
```

````

`````

`````{py:class} Step
:canonical: chartbook.run.Step

```{autodoc2-docstring} chartbook.run.Step
```

````{py:attribute} built
:canonical: chartbook.run.Step.built
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.run.Step.built
```

````

````{py:attribute} directory
:canonical: chartbook.run.Step.directory
:type: typing.Optional[pathlib.Path]
:value: >
   None

```{autodoc2-docstring} chartbook.run.Step.directory
```

````

````{py:attribute} has_dependencies
:canonical: chartbook.run.Step.has_dependencies
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.run.Step.has_dependencies
```

````

````{py:attribute} id
:canonical: chartbook.run.Step.id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.run.Step.id
```

````

````{py:attribute} missing
:canonical: chartbook.run.Step.missing
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.run.Step.missing
```

````

````{py:attribute} scripts
:canonical: chartbook.run.Step.scripts
:type: dict
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.run.Step.scripts
```

````

````{py:attribute} snapshot_first
:canonical: chartbook.run.Step.snapshot_first
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.run.Step.snapshot_first
```

````

````{py:attribute} source
:canonical: chartbook.run.Step.source
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.run.Step.source
```

````

`````

````{py:function} build_tool_runs_chartbook_build(directory: typing.Union[str, pathlib.Path], command: typing.Optional[str] = None) -> typing.Optional[tuple[str, int, str]]
:canonical: chartbook.run.build_tool_runs_chartbook_build

```{autodoc2-docstring} chartbook.run.build_tool_runs_chartbook_build
```
````

````{py:function} execute(script: str, directory: pathlib.Path, name: typing.Optional[str] = None, foreign: bool = False) -> int
:canonical: chartbook.run.execute

```{autodoc2-docstring} chartbook.run.execute
```
````

````{py:function} kept_missing(directory: typing.Union[str, pathlib.Path], store: typing.Optional[chartbook.store.Store] = None) -> list
:canonical: chartbook.run.kept_missing

```{autodoc2-docstring} chartbook.run.kept_missing
```
````

````{py:function} plan(project_dir: typing.Union[str, pathlib.Path] = '.', git_cache: typing.Optional[chartbook.gitcache.GitCache] = None, git: bool = True, force: bool = False, store: typing.Optional[chartbook.store.Store] = None, upstream: bool = False) -> list[chartbook.run.Step]
:canonical: chartbook.run.plan

```{autodoc2-docstring} chartbook.run.plan
```
````

````{py:function} run(project_dir: typing.Union[str, pathlib.Path] = '.', script: str = BUILD_SCRIPT, store: typing.Optional[chartbook.store.Store] = None, git_cache: typing.Optional[chartbook.gitcache.GitCache] = None, echo: typing.Callable[[str], None] = print, on_pin: typing.Optional[typing.Callable] = None, force: bool = False, snapshot: bool = False, frozen: bool = False, on_verify: typing.Optional[typing.Callable] = None, on_snapshot: typing.Optional[typing.Callable] = None, remake: bool = False, remake_command: str = 'chartbook run --remake', upstream: bool = False) -> chartbook.run.RunReport
:canonical: chartbook.run.run

```{autodoc2-docstring} chartbook.run.run
```
````

````{py:function} running(directory: typing.Union[str, pathlib.Path], script: str) -> bool
:canonical: chartbook.run.running

```{autodoc2-docstring} chartbook.run.running
```
````
