# {py:mod}`chartbook.incremental`

```{py:module} chartbook.incremental
```

```{autodoc2-docstring} chartbook.incremental
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BuildPlan <chartbook.incremental.BuildPlan>`
  - ```{autodoc2-docstring} chartbook.incremental.BuildPlan
    :summary:
    ```
* - {py:obj}`SyncResult <chartbook.incremental.SyncResult>`
  - ```{autodoc2-docstring} chartbook.incremental.SyncResult
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`check_build_tree <chartbook.incremental.check_build_tree>`
  - ```{autodoc2-docstring} chartbook.incremental.check_build_tree
    :summary:
    ```
* - {py:obj}`describe_changes <chartbook.incremental.describe_changes>`
  - ```{autodoc2-docstring} chartbook.incremental.describe_changes
    :summary:
    ```
* - {py:obj}`global_fingerprint <chartbook.incremental.global_fingerprint>`
  - ```{autodoc2-docstring} chartbook.incremental.global_fingerprint
    :summary:
    ```
* - {py:obj}`looks_like_build_tree <chartbook.incremental.looks_like_build_tree>`
  - ```{autodoc2-docstring} chartbook.incremental.looks_like_build_tree
    :summary:
    ```
* - {py:obj}`pipeline_fingerprint <chartbook.incremental.pipeline_fingerprint>`
  - ```{autodoc2-docstring} chartbook.incremental.pipeline_fingerprint
    :summary:
    ```
* - {py:obj}`pipeline_input_files <chartbook.incremental.pipeline_input_files>`
  - ```{autodoc2-docstring} chartbook.incremental.pipeline_input_files
    :summary:
    ```
* - {py:obj}`pipeline_owned_paths <chartbook.incremental.pipeline_owned_paths>`
  - ```{autodoc2-docstring} chartbook.incremental.pipeline_owned_paths
    :summary:
    ```
* - {py:obj}`plan_build <chartbook.incremental.plan_build>`
  - ```{autodoc2-docstring} chartbook.incremental.plan_build
    :summary:
    ```
* - {py:obj}`prepare_build_tree <chartbook.incremental.prepare_build_tree>`
  - ```{autodoc2-docstring} chartbook.incremental.prepare_build_tree
    :summary:
    ```
* - {py:obj}`read_state <chartbook.incremental.read_state>`
  - ```{autodoc2-docstring} chartbook.incremental.read_state
    :summary:
    ```
* - {py:obj}`same_size_and_not_newer <chartbook.incremental.same_size_and_not_newer>`
  - ```{autodoc2-docstring} chartbook.incremental.same_size_and_not_newer
    :summary:
    ```
* - {py:obj}`snapshot_inputs <chartbook.incremental.snapshot_inputs>`
  - ```{autodoc2-docstring} chartbook.incremental.snapshot_inputs
    :summary:
    ```
* - {py:obj}`sync_tree <chartbook.incremental.sync_tree>`
  - ```{autodoc2-docstring} chartbook.incremental.sync_tree
    :summary:
    ```
* - {py:obj}`watch <chartbook.incremental.watch>`
  - ```{autodoc2-docstring} chartbook.incremental.watch
    :summary:
    ```
* - {py:obj}`write_state <chartbook.incremental.write_state>`
  - ```{autodoc2-docstring} chartbook.incremental.write_state
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`GITIGNORE_FILE <chartbook.incremental.GITIGNORE_FILE>`
  - ```{autodoc2-docstring} chartbook.incremental.GITIGNORE_FILE
    :summary:
    ```
* - {py:obj}`PAGE_SUFFIXES <chartbook.incremental.PAGE_SUFFIXES>`
  - ```{autodoc2-docstring} chartbook.incremental.PAGE_SUFFIXES
    :summary:
    ```
* - {py:obj}`SPHINX_BUILD_DIR <chartbook.incremental.SPHINX_BUILD_DIR>`
  - ```{autodoc2-docstring} chartbook.incremental.SPHINX_BUILD_DIR
    :summary:
    ```
* - {py:obj}`STATE_FILE <chartbook.incremental.STATE_FILE>`
  - ```{autodoc2-docstring} chartbook.incremental.STATE_FILE
    :summary:
    ```
* - {py:obj}`STATE_VERSION <chartbook.incremental.STATE_VERSION>`
  - ```{autodoc2-docstring} chartbook.incremental.STATE_VERSION
    :summary:
    ```
````

### API

`````{py:class} BuildPlan
:canonical: chartbook.incremental.BuildPlan

```{autodoc2-docstring} chartbook.incremental.BuildPlan
```

````{py:attribute} code_times
:canonical: chartbook.incremental.BuildPlan.code_times
:type: dict[str, str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.incremental.BuildPlan.code_times
```

````

````{py:attribute} fingerprints
:canonical: chartbook.incremental.BuildPlan.fingerprints
:type: dict[str, str]
:value: >
   None

```{autodoc2-docstring} chartbook.incremental.BuildPlan.fingerprints
```

````

````{py:attribute} fresh
:canonical: chartbook.incremental.BuildPlan.fresh
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.incremental.BuildPlan.fresh
```

````

````{py:attribute} global_fingerprint
:canonical: chartbook.incremental.BuildPlan.global_fingerprint
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.incremental.BuildPlan.global_fingerprint
```

````

````{py:method} preserved_paths(manifest: dict) -> list[pathlib.Path]
:canonical: chartbook.incremental.BuildPlan.preserved_paths

```{autodoc2-docstring} chartbook.incremental.BuildPlan.preserved_paths
```

````

````{py:attribute} reason
:canonical: chartbook.incremental.BuildPlan.reason
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.incremental.BuildPlan.reason
```

````

````{py:attribute} regenerate
:canonical: chartbook.incremental.BuildPlan.regenerate
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.incremental.BuildPlan.regenerate
```

````

````{py:attribute} rendered
:canonical: chartbook.incremental.BuildPlan.rendered
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.incremental.BuildPlan.rendered
```

````

````{py:attribute} reuse
:canonical: chartbook.incremental.BuildPlan.reuse
:type: list[str]
:value: >
   None

```{autodoc2-docstring} chartbook.incremental.BuildPlan.reuse
```

````

`````

````{py:data} GITIGNORE_FILE
:canonical: chartbook.incremental.GITIGNORE_FILE
:value: >
   '.gitignore'

```{autodoc2-docstring} chartbook.incremental.GITIGNORE_FILE
```

````

````{py:data} PAGE_SUFFIXES
:canonical: chartbook.incremental.PAGE_SUFFIXES
:value: >
   ('.md', '.ipynb', '.rst')

```{autodoc2-docstring} chartbook.incremental.PAGE_SUFFIXES
```

````

````{py:data} SPHINX_BUILD_DIR
:canonical: chartbook.incremental.SPHINX_BUILD_DIR
:value: >
   '_build'

```{autodoc2-docstring} chartbook.incremental.SPHINX_BUILD_DIR
```

````

````{py:data} STATE_FILE
:canonical: chartbook.incremental.STATE_FILE
:value: >
   '.chartbook-build-state.json'

```{autodoc2-docstring} chartbook.incremental.STATE_FILE
```

````

````{py:data} STATE_VERSION
:canonical: chartbook.incremental.STATE_VERSION
:value: >
   1

```{autodoc2-docstring} chartbook.incremental.STATE_VERSION
```

````

`````{py:class} SyncResult
:canonical: chartbook.incremental.SyncResult

```{autodoc2-docstring} chartbook.incremental.SyncResult
```

````{py:attribute} added
:canonical: chartbook.incremental.SyncResult.added
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.incremental.SyncResult.added
```

````

````{py:attribute} deleted
:canonical: chartbook.incremental.SyncResult.deleted
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.incremental.SyncResult.deleted
```

````

````{py:property} pages_added_or_removed
:canonical: chartbook.incremental.SyncResult.pages_added_or_removed
:type: bool

```{autodoc2-docstring} chartbook.incremental.SyncResult.pages_added_or_removed
```

````

````{py:attribute} unchanged
:canonical: chartbook.incremental.SyncResult.unchanged
:type: int
:value: >
   0

```{autodoc2-docstring} chartbook.incremental.SyncResult.unchanged
```

````

````{py:attribute} written
:canonical: chartbook.incremental.SyncResult.written
:type: list[pathlib.Path]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.incremental.SyncResult.written
```

````

`````

````{py:function} check_build_tree(build_dir: pathlib.Path) -> None
:canonical: chartbook.incremental.check_build_tree

```{autodoc2-docstring} chartbook.incremental.check_build_tree
```
````

````{py:function} describe_changes(before: dict, after: dict, limit: int = 3) -> str
:canonical: chartbook.incremental.describe_changes

```{autodoc2-docstring} chartbook.incremental.describe_changes
```
````

````{py:function} global_fingerprint(manifest: dict, theme_dir: pathlib.Path, options: dict) -> str
:canonical: chartbook.incremental.global_fingerprint

```{autodoc2-docstring} chartbook.incremental.global_fingerprint
```
````

````{py:function} looks_like_build_tree(directory: pathlib.Path) -> bool
:canonical: chartbook.incremental.looks_like_build_tree

```{autodoc2-docstring} chartbook.incremental.looks_like_build_tree
```
````

````{py:function} pipeline_fingerprint(pipeline_id: str, pipeline_manifest: dict, salt: str = '') -> str
:canonical: chartbook.incremental.pipeline_fingerprint

```{autodoc2-docstring} chartbook.incremental.pipeline_fingerprint
```
````

````{py:function} pipeline_input_files(pipeline_manifest: dict) -> list[pathlib.Path]
:canonical: chartbook.incremental.pipeline_input_files

```{autodoc2-docstring} chartbook.incremental.pipeline_input_files
```
````

````{py:function} pipeline_owned_paths(pipeline_id: str, pipeline_manifest: dict) -> list[pathlib.Path]
:canonical: chartbook.incremental.pipeline_owned_paths

```{autodoc2-docstring} chartbook.incremental.pipeline_owned_paths
```
````

````{py:function} plan_build(manifest: dict, build_dir: pathlib.Path, theme_dir: pathlib.Path, options: dict, skip_pipelines: typing.Iterable[str] = (), salts: typing.Optional[dict] = None) -> chartbook.incremental.BuildPlan
:canonical: chartbook.incremental.plan_build

```{autodoc2-docstring} chartbook.incremental.plan_build
```
````

````{py:function} prepare_build_tree(build_dir: pathlib.Path, fresh: bool) -> None
:canonical: chartbook.incremental.prepare_build_tree

```{autodoc2-docstring} chartbook.incremental.prepare_build_tree
```
````

````{py:function} read_state(build_dir: pathlib.Path) -> typing.Optional[dict]
:canonical: chartbook.incremental.read_state

```{autodoc2-docstring} chartbook.incremental.read_state
```
````

````{py:function} same_size_and_not_newer(source_file: pathlib.Path, destination_file: pathlib.Path) -> bool
:canonical: chartbook.incremental.same_size_and_not_newer

```{autodoc2-docstring} chartbook.incremental.same_size_and_not_newer
```
````

````{py:function} snapshot_inputs(manifest: dict, project_dir: pathlib.Path) -> dict[str, typing.Optional[tuple]]
:canonical: chartbook.incremental.snapshot_inputs

```{autodoc2-docstring} chartbook.incremental.snapshot_inputs
```
````

````{py:function} sync_tree(source: pathlib.Path, destination: pathlib.Path, preserve: typing.Iterable[pathlib.Path] = (), same: typing.Optional[typing.Callable[[pathlib.Path, pathlib.Path], bool]] = None) -> chartbook.incremental.SyncResult
:canonical: chartbook.incremental.sync_tree

```{autodoc2-docstring} chartbook.incremental.sync_tree
```
````

````{py:function} watch(build: typing.Callable[[], None], snapshot: typing.Callable[[], dict], interval: float = 1.0, echo: typing.Callable[[str], None] = print, sleep: typing.Optional[typing.Callable[[float], None]] = None, max_polls: typing.Optional[int] = None) -> int
:canonical: chartbook.incremental.watch

```{autodoc2-docstring} chartbook.incremental.watch
```
````

````{py:function} write_state(build_dir: pathlib.Path, plan: chartbook.incremental.BuildPlan, rendered: bool = False) -> None
:canonical: chartbook.incremental.write_state

```{autodoc2-docstring} chartbook.incremental.write_state
```
````
