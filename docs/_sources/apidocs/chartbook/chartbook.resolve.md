# {py:mod}`chartbook.resolve`

```{py:module} chartbook.resolve
```

```{autodoc2-docstring} chartbook.resolve
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FileLocation <chartbook.resolve.FileLocation>`
  - ```{autodoc2-docstring} chartbook.resolve.FileLocation
    :summary:
    ```
* - {py:obj}`Location <chartbook.resolve.Location>`
  - ```{autodoc2-docstring} chartbook.resolve.Location
    :summary:
    ```
* - {py:obj}`PipelineLocation <chartbook.resolve.PipelineLocation>`
  - ```{autodoc2-docstring} chartbook.resolve.PipelineLocation
    :summary:
    ```
* - {py:obj}`QueryLocation <chartbook.resolve.QueryLocation>`
  - ```{autodoc2-docstring} chartbook.resolve.QueryLocation
    :summary:
    ```
* - {py:obj}`TableLocation <chartbook.resolve.TableLocation>`
  - ```{autodoc2-docstring} chartbook.resolve.TableLocation
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`batch <chartbook.resolve.batch>`
  - ```{autodoc2-docstring} chartbook.resolve.batch
    :summary:
    ```
* - {py:obj}`caller_start_dirs <chartbook.resolve.caller_start_dirs>`
  - ```{autodoc2-docstring} chartbook.resolve.caller_start_dirs
    :summary:
    ```
* - {py:obj}`declared_assets <chartbook.resolve.declared_assets>`
  - ```{autodoc2-docstring} chartbook.resolve.declared_assets
    :summary:
    ```
* - {py:obj}`declared_files <chartbook.resolve.declared_files>`
  - ```{autodoc2-docstring} chartbook.resolve.declared_files
    :summary:
    ```
* - {py:obj}`declared_in_source <chartbook.resolve.declared_in_source>`
  - ```{autodoc2-docstring} chartbook.resolve.declared_in_source
    :summary:
    ```
* - {py:obj}`find_manifest_dir <chartbook.resolve.find_manifest_dir>`
  - ```{autodoc2-docstring} chartbook.resolve.find_manifest_dir
    :summary:
    ```
* - {py:obj}`known_as <chartbook.resolve.known_as>`
  - ```{autodoc2-docstring} chartbook.resolve.known_as
    :summary:
    ```
* - {py:obj}`locate_in_catalog <chartbook.resolve.locate_in_catalog>`
  - ```{autodoc2-docstring} chartbook.resolve.locate_in_catalog
    :summary:
    ```
* - {py:obj}`locate_pipeline <chartbook.resolve.locate_pipeline>`
  - ```{autodoc2-docstring} chartbook.resolve.locate_pipeline
    :summary:
    ```
* - {py:obj}`nothing_to_read <chartbook.resolve.nothing_to_read>`
  - ```{autodoc2-docstring} chartbook.resolve.nothing_to_read
    :summary:
    ```
* - {py:obj}`parse_declared_ref <chartbook.resolve.parse_declared_ref>`
  - ```{autodoc2-docstring} chartbook.resolve.parse_declared_ref
    :summary:
    ```
* - {py:obj}`require_file <chartbook.resolve.require_file>`
  - ```{autodoc2-docstring} chartbook.resolve.require_file
    :summary:
    ```
* - {py:obj}`resolve <chartbook.resolve.resolve>`
  - ```{autodoc2-docstring} chartbook.resolve.resolve
    :summary:
    ```
* - {py:obj}`resolve_catalog_path <chartbook.resolve.resolve_catalog_path>`
  - ```{autodoc2-docstring} chartbook.resolve.resolve_catalog_path
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ASSET_TABLES <chartbook.resolve.ASSET_TABLES>`
  - ```{autodoc2-docstring} chartbook.resolve.ASSET_TABLES
    :summary:
    ```
* - {py:obj}`BATCH_ENV_VAR <chartbook.resolve.BATCH_ENV_VAR>`
  - ```{autodoc2-docstring} chartbook.resolve.BATCH_ENV_VAR
    :summary:
    ```
* - {py:obj}`MANIFEST_NAME <chartbook.resolve.MANIFEST_NAME>`
  - ```{autodoc2-docstring} chartbook.resolve.MANIFEST_NAME
    :summary:
    ```
* - {py:obj}`NOT_TABLES <chartbook.resolve.NOT_TABLES>`
  - ```{autodoc2-docstring} chartbook.resolve.NOT_TABLES
    :summary:
    ```
* - {py:obj}`RESOLVABLE_KINDS <chartbook.resolve.RESOLVABLE_KINDS>`
  - ```{autodoc2-docstring} chartbook.resolve.RESOLVABLE_KINDS
    :summary:
    ```
````

### API

````{py:data} ASSET_TABLES
:canonical: chartbook.resolve.ASSET_TABLES
:value: >
   'tuple(...)'

```{autodoc2-docstring} chartbook.resolve.ASSET_TABLES
```

````

````{py:data} BATCH_ENV_VAR
:canonical: chartbook.resolve.BATCH_ENV_VAR
:value: >
   'CHARTBOOK_BATCH'

```{autodoc2-docstring} chartbook.resolve.BATCH_ENV_VAR
```

````

`````{py:class} FileLocation
:canonical: chartbook.resolve.FileLocation

Bases: {py:obj}`chartbook.resolve.Location`

```{autodoc2-docstring} chartbook.resolve.FileLocation
```

````{py:attribute} content_hash
:canonical: chartbook.resolve.FileLocation.content_hash
:type: typing.Optional[str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.resolve.FileLocation.content_hash
```

````

````{py:attribute} files
:canonical: chartbook.resolve.FileLocation.files
:type: tuple
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.resolve.FileLocation.files
```

````

````{py:attribute} format
:canonical: chartbook.resolve.FileLocation.format
:type: typing.Optional[str]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.resolve.FileLocation.format
```

````

````{py:attribute} kind
:canonical: chartbook.resolve.FileLocation.kind
:type: typing.ClassVar[str]
:value: >
   'file'

```{autodoc2-docstring} chartbook.resolve.FileLocation.kind
```

````

````{py:attribute} listed
:canonical: chartbook.resolve.FileLocation.listed
:type: tuple
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.resolve.FileLocation.listed
```

````

````{py:attribute} path
:canonical: chartbook.resolve.FileLocation.path
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.FileLocation.path
```

````

````{py:attribute} read_options
:canonical: chartbook.resolve.FileLocation.read_options
:type: typing.Mapping
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.resolve.FileLocation.read_options
```

````

`````

`````{py:class} Location
:canonical: chartbook.resolve.Location

```{autodoc2-docstring} chartbook.resolve.Location
```

````{py:attribute} kind
:canonical: chartbook.resolve.Location.kind
:type: typing.ClassVar[str]
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.Location.kind
```

````

`````

````{py:data} MANIFEST_NAME
:canonical: chartbook.resolve.MANIFEST_NAME
:value: >
   'chartbook.toml'

```{autodoc2-docstring} chartbook.resolve.MANIFEST_NAME
```

````

````{py:data} NOT_TABLES
:canonical: chartbook.resolve.NOT_TABLES
:value: >
   ('.txt', '.md', '.rst', '.json', '.yaml', '.yml', '.csv', '.tsv', '.xml', '.html', '.log', '.crc')

```{autodoc2-docstring} chartbook.resolve.NOT_TABLES
```

````

`````{py:class} PipelineLocation
:canonical: chartbook.resolve.PipelineLocation

```{autodoc2-docstring} chartbook.resolve.PipelineLocation
```

````{py:attribute} found_in
:canonical: chartbook.resolve.PipelineLocation.found_in
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.found_in
```

````

````{py:attribute} id
:canonical: chartbook.resolve.PipelineLocation.id
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.id
```

````

````{py:attribute} kind
:canonical: chartbook.resolve.PipelineLocation.kind
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.kind
```

````

````{py:attribute} path
:canonical: chartbook.resolve.PipelineLocation.path
:type: typing.Optional[pathlib.Path]
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.path
```

````

````{py:attribute} pipeline
:canonical: chartbook.resolve.PipelineLocation.pipeline
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.pipeline
```

````

````{py:attribute} rev
:canonical: chartbook.resolve.PipelineLocation.rev
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.rev
```

````

````{py:attribute} url
:canonical: chartbook.resolve.PipelineLocation.url
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.PipelineLocation.url
```

````

`````

````{py:exception} PipelineNotFoundError(pipeline: str, candidates: dict[str, list[str]])
:canonical: chartbook.resolve.PipelineNotFoundError

Bases: {py:obj}`KeyError`

```{autodoc2-docstring} chartbook.resolve.PipelineNotFoundError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.resolve.PipelineNotFoundError.__init__
```

````

`````{py:class} QueryLocation
:canonical: chartbook.resolve.QueryLocation

Bases: {py:obj}`chartbook.resolve.Location`

```{autodoc2-docstring} chartbook.resolve.QueryLocation
```

````{py:attribute} backend
:canonical: chartbook.resolve.QueryLocation.backend
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.QueryLocation.backend
```

````

````{py:attribute} kind
:canonical: chartbook.resolve.QueryLocation.kind
:type: typing.ClassVar[str]
:value: >
   'query'

```{autodoc2-docstring} chartbook.resolve.QueryLocation.kind
```

````

````{py:attribute} source
:canonical: chartbook.resolve.QueryLocation.source
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.QueryLocation.source
```

````

````{py:attribute} sql
:canonical: chartbook.resolve.QueryLocation.sql
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.QueryLocation.sql
```

````

````{py:attribute} url
:canonical: chartbook.resolve.QueryLocation.url
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.QueryLocation.url
```

````

`````

````{py:data} RESOLVABLE_KINDS
:canonical: chartbook.resolve.RESOLVABLE_KINDS
:value: >
   ('dataframe', 'chart', 'notebook', 'note', 'model', 'file')

```{autodoc2-docstring} chartbook.resolve.RESOLVABLE_KINDS
```

````

`````{py:class} TableLocation
:canonical: chartbook.resolve.TableLocation

Bases: {py:obj}`chartbook.resolve.Location`

```{autodoc2-docstring} chartbook.resolve.TableLocation
```

````{py:attribute} backend
:canonical: chartbook.resolve.TableLocation.backend
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.TableLocation.backend
```

````

````{py:attribute} identifier
:canonical: chartbook.resolve.TableLocation.identifier
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.TableLocation.identifier
```

````

````{py:attribute} kind
:canonical: chartbook.resolve.TableLocation.kind
:type: typing.ClassVar[str]
:value: >
   'table'

```{autodoc2-docstring} chartbook.resolve.TableLocation.kind
```

````

````{py:attribute} source
:canonical: chartbook.resolve.TableLocation.source
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.TableLocation.source
```

````

````{py:attribute} url
:canonical: chartbook.resolve.TableLocation.url
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.resolve.TableLocation.url
```

````

`````

````{py:exception} UnrecordedReadWarning()
:canonical: chartbook.resolve.UnrecordedReadWarning

Bases: {py:obj}`UserWarning`

```{autodoc2-docstring} chartbook.resolve.UnrecordedReadWarning
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.resolve.UnrecordedReadWarning.__init__
```

````

````{py:exception} UnsupportedReferenceError()
:canonical: chartbook.resolve.UnsupportedReferenceError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.resolve.UnsupportedReferenceError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.resolve.UnsupportedReferenceError.__init__
```

````

````{py:exception} WorkingVersionWarning()
:canonical: chartbook.resolve.WorkingVersionWarning

Bases: {py:obj}`UserWarning`

```{autodoc2-docstring} chartbook.resolve.WorkingVersionWarning
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.resolve.WorkingVersionWarning.__init__
```

````

````{py:function} batch() -> bool
:canonical: chartbook.resolve.batch

```{autodoc2-docstring} chartbook.resolve.batch
```
````

````{py:function} caller_start_dirs(project_dir: typing.Optional[typing.Union[str, pathlib.Path]], caller_frame) -> list
:canonical: chartbook.resolve.caller_start_dirs

```{autodoc2-docstring} chartbook.resolve.caller_start_dirs
```
````

````{py:function} declared_assets(manifest_dir: typing.Union[str, pathlib.Path]) -> dict[str, list[str]]
:canonical: chartbook.resolve.declared_assets

```{autodoc2-docstring} chartbook.resolve.declared_assets
```
````

````{py:function} declared_files(manifest_dir: typing.Union[str, pathlib.Path]) -> list[tuple[chartbook.refs.AssetRef, str, pathlib.Path]]
:canonical: chartbook.resolve.declared_files

```{autodoc2-docstring} chartbook.resolve.declared_files
```
````

````{py:function} declared_in_source(manifest_dir: typing.Union[str, pathlib.Path]) -> list[tuple[chartbook.refs.AssetRef, dict]]
:canonical: chartbook.resolve.declared_in_source

```{autodoc2-docstring} chartbook.resolve.declared_in_source
```
````

````{py:function} find_manifest_dir(*starts: typing.Union[str, pathlib.Path]) -> pathlib.Path
:canonical: chartbook.resolve.find_manifest_dir

```{autodoc2-docstring} chartbook.resolve.find_manifest_dir
```
````

````{py:function} known_as(location: chartbook.resolve.PipelineLocation, pipelines: typing.Mapping[str, typing.Union[str, pathlib.Path]]) -> str
:canonical: chartbook.resolve.known_as

```{autodoc2-docstring} chartbook.resolve.known_as
```
````

````{py:function} locate_in_catalog(catalog_manifest: dict, pipeline: str) -> str
:canonical: chartbook.resolve.locate_in_catalog

```{autodoc2-docstring} chartbook.resolve.locate_in_catalog
```
````

````{py:function} locate_pipeline(pipeline: str, *, dependencies: typing.Optional[typing.Mapping[str, dict]] = None, catalog: typing.Optional[typing.Mapping[str, typing.Union[str, pathlib.Path]]] = None) -> chartbook.resolve.PipelineLocation
:canonical: chartbook.resolve.locate_pipeline

```{autodoc2-docstring} chartbook.resolve.locate_pipeline
```
````

````{py:function} nothing_to_read(location: chartbook.resolve.Location) -> typing.Optional[str]
:canonical: chartbook.resolve.nothing_to_read

```{autodoc2-docstring} chartbook.resolve.nothing_to_read
```
````

````{py:function} parse_declared_ref(ref: typing.Union[str, chartbook.refs.AssetRef], kind: typing.Optional[str] = None, resolving: bool = False) -> chartbook.refs.AssetRef
:canonical: chartbook.resolve.parse_declared_ref

```{autodoc2-docstring} chartbook.resolve.parse_declared_ref
```
````

````{py:function} require_file(location: chartbook.resolve.Location, what: str) -> pathlib.Path
:canonical: chartbook.resolve.require_file

```{autodoc2-docstring} chartbook.resolve.require_file
```
````

````{py:function} resolve(ref: typing.Union[str, chartbook.refs.AssetRef], *, kind: typing.Optional[str] = None, pipeline: typing.Optional[str] = None, catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None, start_dirs: typing.Iterable[typing.Union[str, pathlib.Path]] = ()) -> chartbook.resolve.Location
:canonical: chartbook.resolve.resolve

```{autodoc2-docstring} chartbook.resolve.resolve
```
````

````{py:function} resolve_catalog_path(catalog_path: typing.Optional[typing.Union[str, pathlib.Path]] = None) -> pathlib.Path
:canonical: chartbook.resolve.resolve_catalog_path

```{autodoc2-docstring} chartbook.resolve.resolve_catalog_path
```
````
