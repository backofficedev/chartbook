# {py:mod}`chartbook.store`

```{py:module} chartbook.store
```

```{autodoc2-docstring} chartbook.store
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FolderStore <chartbook.store.FolderStore>`
  - ```{autodoc2-docstring} chartbook.store.FolderStore
    :summary:
    ```
* - {py:obj}`Root <chartbook.store.Root>`
  - ```{autodoc2-docstring} chartbook.store.Root
    :summary:
    ```
* - {py:obj}`Store <chartbook.store.Store>`
  - ```{autodoc2-docstring} chartbook.store.Store
    :summary:
    ```
* - {py:obj}`StoreProblem <chartbook.store.StoreProblem>`
  - ```{autodoc2-docstring} chartbook.store.StoreProblem
    :summary:
    ```
* - {py:obj}`StoredObject <chartbook.store.StoredObject>`
  - ```{autodoc2-docstring} chartbook.store.StoredObject
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`declared_name <chartbook.store.declared_name>`
  - ```{autodoc2-docstring} chartbook.store.declared_name
    :summary:
    ```
* - {py:obj}`default_store <chartbook.store.default_store>`
  - ```{autodoc2-docstring} chartbook.store.default_store
    :summary:
    ```
* - {py:obj}`is_record_name <chartbook.store.is_record_name>`
  - ```{autodoc2-docstring} chartbook.store.is_record_name
    :summary:
    ```
* - {py:obj}`is_root_name <chartbook.store.is_root_name>`
  - ```{autodoc2-docstring} chartbook.store.is_root_name
    :summary:
    ```
* - {py:obj}`link_target <chartbook.store.link_target>`
  - ```{autodoc2-docstring} chartbook.store.link_target
    :summary:
    ```
* - {py:obj}`on_disk <chartbook.store.on_disk>`
  - ```{autodoc2-docstring} chartbook.store.on_disk
    :summary:
    ```
* - {py:obj}`plain_parts <chartbook.store.plain_parts>`
  - ```{autodoc2-docstring} chartbook.store.plain_parts
    :summary:
    ```
* - {py:obj}`read_root <chartbook.store.read_root>`
  - ```{autodoc2-docstring} chartbook.store.read_root
    :summary:
    ```
* - {py:obj}`root_document <chartbook.store.root_document>`
  - ```{autodoc2-docstring} chartbook.store.root_document
    :summary:
    ```
* - {py:obj}`root_name <chartbook.store.root_name>`
  - ```{autodoc2-docstring} chartbook.store.root_name
    :summary:
    ```
* - {py:obj}`store_for_url <chartbook.store.store_for_url>`
  - ```{autodoc2-docstring} chartbook.store.store_for_url
    :summary:
    ```
* - {py:obj}`this_host <chartbook.store.this_host>`
  - ```{autodoc2-docstring} chartbook.store.this_host
    :summary:
    ```
* - {py:obj}`this_machine <chartbook.store.this_machine>`
  - ```{autodoc2-docstring} chartbook.store.this_machine
    :summary:
    ```
* - {py:obj}`this_node <chartbook.store.this_node>`
  - ```{autodoc2-docstring} chartbook.store.this_node
    :summary:
    ```
* - {py:obj}`unreadable_detail <chartbook.store.unreadable_detail>`
  - ```{autodoc2-docstring} chartbook.store.unreadable_detail
    :summary:
    ```
* - {py:obj}`unsynced_part <chartbook.store.unsynced_part>`
  - ```{autodoc2-docstring} chartbook.store.unsynced_part
    :summary:
    ```
* - {py:obj}`what_is_wrong <chartbook.store.what_is_wrong>`
  - ```{autodoc2-docstring} chartbook.store.what_is_wrong
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BUILDS_DIR <chartbook.store.BUILDS_DIR>`
  - ```{autodoc2-docstring} chartbook.store.BUILDS_DIR
    :summary:
    ```
* - {py:obj}`FROZEN_LINKS <chartbook.store.FROZEN_LINKS>`
  - ```{autodoc2-docstring} chartbook.store.FROZEN_LINKS
    :summary:
    ```
* - {py:obj}`LINKS <chartbook.store.LINKS>`
  - ```{autodoc2-docstring} chartbook.store.LINKS
    :summary:
    ```
* - {py:obj}`MARKER_FILE <chartbook.store.MARKER_FILE>`
  - ```{autodoc2-docstring} chartbook.store.MARKER_FILE
    :summary:
    ```
* - {py:obj}`OBJECTS_DIR <chartbook.store.OBJECTS_DIR>`
  - ```{autodoc2-docstring} chartbook.store.OBJECTS_DIR
    :summary:
    ```
* - {py:obj}`ORIGINS_FILE <chartbook.store.ORIGINS_FILE>`
  - ```{autodoc2-docstring} chartbook.store.ORIGINS_FILE
    :summary:
    ```
* - {py:obj}`ROOTS_DIR <chartbook.store.ROOTS_DIR>`
  - ```{autodoc2-docstring} chartbook.store.ROOTS_DIR
    :summary:
    ```
* - {py:obj}`SCHEMA <chartbook.store.SCHEMA>`
  - ```{autodoc2-docstring} chartbook.store.SCHEMA
    :summary:
    ```
* - {py:obj}`SNAPSHOTS_DIR <chartbook.store.SNAPSHOTS_DIR>`
  - ```{autodoc2-docstring} chartbook.store.SNAPSHOTS_DIR
    :summary:
    ```
* - {py:obj}`STORE_PLUGIN_GROUP <chartbook.store.STORE_PLUGIN_GROUP>`
  - ```{autodoc2-docstring} chartbook.store.STORE_PLUGIN_GROUP
    :summary:
    ```
* - {py:obj}`TMP_DIR <chartbook.store.TMP_DIR>`
  - ```{autodoc2-docstring} chartbook.store.TMP_DIR
    :summary:
    ```
````

### API

````{py:data} BUILDS_DIR
:canonical: chartbook.store.BUILDS_DIR
:value: >
   'builds'

```{autodoc2-docstring} chartbook.store.BUILDS_DIR
```

````

````{py:data} FROZEN_LINKS
:canonical: chartbook.store.FROZEN_LINKS
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.store.FROZEN_LINKS
```

````

`````{py:class} FolderStore(root: typing.Union[str, pathlib.Path])
:canonical: chartbook.store.FolderStore

Bases: {py:obj}`chartbook.store.Store`

```{autodoc2-docstring} chartbook.store.FolderStore
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.store.FolderStore.__init__
```

````{py:method} add_root(lockfile: typing.Union[str, pathlib.Path], hashes: typing.Iterable[str], snapshots: typing.Iterable[tuple[str, str]] = (), machine: typing.Optional[str] = None, labelled: typing.Iterable[tuple[str, str, str, str]] = ()) -> None
:canonical: chartbook.store.FolderStore.add_root

```{autodoc2-docstring} chartbook.store.FolderStore.add_root
```

````

````{py:method} age_of(content_hash: str, now: typing.Optional[float] = None) -> float
:canonical: chartbook.store.FolderStore.age_of

```{autodoc2-docstring} chartbook.store.FolderStore.age_of
```

````

````{py:method} all_snapshot_files() -> list[pathlib.Path]
:canonical: chartbook.store.FolderStore.all_snapshot_files

````

````{py:method} delete(content_hash: str) -> bool
:canonical: chartbook.store.FolderStore.delete

```{autodoc2-docstring} chartbook.store.FolderStore.delete
```

````

````{py:method} get(content_hash: str) -> pathlib.Path
:canonical: chartbook.store.FolderStore.get

```{autodoc2-docstring} chartbook.store.FolderStore.get
```

````

````{py:method} has(content_hash: str) -> bool
:canonical: chartbook.store.FolderStore.has

```{autodoc2-docstring} chartbook.store.FolderStore.has
```

````

````{py:method} hashes() -> typing.Iterator[str]
:canonical: chartbook.store.FolderStore.hashes

```{autodoc2-docstring} chartbook.store.FolderStore.hashes
```

````

````{py:method} incomplete(content_hash: str, size_bytes: typing.Optional[int], files: typing.Optional[dict] = None, every: bool = False) -> typing.Optional[str]
:canonical: chartbook.store.FolderStore.incomplete

```{autodoc2-docstring} chartbook.store.FolderStore.incomplete
```

````

````{py:method} is_users_own() -> bool
:canonical: chartbook.store.FolderStore.is_users_own

```{autodoc2-docstring} chartbook.store.FolderStore.is_users_own
```

````

````{py:method} lacks(content_hash: str, names: typing.Iterable[str], single: bool = True) -> bool
:canonical: chartbook.store.FolderStore.lacks

```{autodoc2-docstring} chartbook.store.FolderStore.lacks
```

````

````{py:method} note_origin(commit: str, name: str, top: str) -> None
:canonical: chartbook.store.FolderStore.note_origin

````

````{py:method} object_path(content_hash: str) -> pathlib.Path
:canonical: chartbook.store.FolderStore.object_path

```{autodoc2-docstring} chartbook.store.FolderStore.object_path
```

````

````{py:method} origins(commit: str, name: str) -> list[str]
:canonical: chartbook.store.FolderStore.origins

````

````{py:method} put(path: typing.Union[str, pathlib.Path], links: typing.Iterable[str] = LINKS) -> chartbook.store.StoredObject
:canonical: chartbook.store.FolderStore.put

```{autodoc2-docstring} chartbook.store.FolderStore.put
```

````

````{py:method} remove_root(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> bool
:canonical: chartbook.store.FolderStore.remove_root

```{autodoc2-docstring} chartbook.store.FolderStore.remove_root
```

````

````{py:method} remove_snapshot(path: pathlib.Path) -> bool
:canonical: chartbook.store.FolderStore.remove_snapshot

```{autodoc2-docstring} chartbook.store.FolderStore.remove_snapshot
```

````

````{py:method} root_of(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> typing.Optional[chartbook.store.Root]
:canonical: chartbook.store.FolderStore.root_of

```{autodoc2-docstring} chartbook.store.FolderStore.root_of
```

````

````{py:method} roots() -> list[chartbook.store.Root]
:canonical: chartbook.store.FolderStore.roots

```{autodoc2-docstring} chartbook.store.FolderStore.roots
```

````

````{py:method} size_of(content_hash: str) -> int
:canonical: chartbook.store.FolderStore.size_of

```{autodoc2-docstring} chartbook.store.FolderStore.size_of
```

````

````{py:method} snapshot_commits() -> set[str]
:canonical: chartbook.store.FolderStore.snapshot_commits

````

````{py:method} snapshot_files(commit: str, name: str) -> list[pathlib.Path]
:canonical: chartbook.store.FolderStore.snapshot_files

````

````{py:method} snapshot_folder(commit: str, name: str) -> pathlib.Path
:canonical: chartbook.store.FolderStore.snapshot_folder

```{autodoc2-docstring} chartbook.store.FolderStore.snapshot_folder
```

````

````{py:method} verify(content_hashes: typing.Optional[typing.Iterable[str]] = None) -> list[chartbook.store.StoreProblem]
:canonical: chartbook.store.FolderStore.verify

```{autodoc2-docstring} chartbook.store.FolderStore.verify
```

````

````{py:method} write_snapshot(commit: str, name: str, stamp: str, document: dict) -> pathlib.Path
:canonical: chartbook.store.FolderStore.write_snapshot

````

`````

````{py:data} LINKS
:canonical: chartbook.store.LINKS
:value: >
   ('reflink', 'hardlink', 'symlink', 'copy')

```{autodoc2-docstring} chartbook.store.LINKS
```

````

````{py:data} MARKER_FILE
:canonical: chartbook.store.MARKER_FILE
:value: >
   'store.json'

```{autodoc2-docstring} chartbook.store.MARKER_FILE
```

````

````{py:data} OBJECTS_DIR
:canonical: chartbook.store.OBJECTS_DIR
:value: >
   'objects'

```{autodoc2-docstring} chartbook.store.OBJECTS_DIR
```

````

````{py:data} ORIGINS_FILE
:canonical: chartbook.store.ORIGINS_FILE
:value: >
   'origins'

```{autodoc2-docstring} chartbook.store.ORIGINS_FILE
```

````

````{py:exception} ObjectNotFoundError()
:canonical: chartbook.store.ObjectNotFoundError

Bases: {py:obj}`chartbook.store.StoreError`, {py:obj}`LookupError`

```{autodoc2-docstring} chartbook.store.ObjectNotFoundError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.store.ObjectNotFoundError.__init__
```

````

````{py:data} ROOTS_DIR
:canonical: chartbook.store.ROOTS_DIR
:value: >
   'roots'

```{autodoc2-docstring} chartbook.store.ROOTS_DIR
```

````

````{py:exception} ReadOnlyStoreError()
:canonical: chartbook.store.ReadOnlyStoreError

Bases: {py:obj}`chartbook.store.StoreError`

```{autodoc2-docstring} chartbook.store.ReadOnlyStoreError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.store.ReadOnlyStoreError.__init__
```

````

`````{py:class} Root
:canonical: chartbook.store.Root

```{autodoc2-docstring} chartbook.store.Root
```

````{py:property} copy
:canonical: chartbook.store.Root.copy
:type: bool

```{autodoc2-docstring} chartbook.store.Root.copy
```

````

````{py:attribute} hashes
:canonical: chartbook.store.Root.hashes
:type: tuple[str, ...]
:value: >
   None

```{autodoc2-docstring} chartbook.store.Root.hashes
```

````

````{py:attribute} host
:canonical: chartbook.store.Root.host
:type: str
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.host
```

````

````{py:attribute} labelled
:canonical: chartbook.store.Root.labelled
:type: typing.Optional[tuple[tuple[str, str, str, str], ...]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.labelled
```

````

````{py:attribute} lockfile
:canonical: chartbook.store.Root.lockfile
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.store.Root.lockfile
```

````

````{py:attribute} machine
:canonical: chartbook.store.Root.machine
:type: str
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.machine
```

````

````{py:attribute} node
:canonical: chartbook.store.Root.node
:type: str
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.node
```

````

````{py:attribute} note
:canonical: chartbook.store.Root.note
:type: str
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.note
```

````

````{py:attribute} snapshots
:canonical: chartbook.store.Root.snapshots
:type: typing.Optional[tuple[tuple[str, str], ...]]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.store.Root.snapshots
```

````

`````

````{py:data} SCHEMA
:canonical: chartbook.store.SCHEMA
:value: >
   'chartbook/store/v1'

```{autodoc2-docstring} chartbook.store.SCHEMA
```

````

````{py:data} SNAPSHOTS_DIR
:canonical: chartbook.store.SNAPSHOTS_DIR
:value: >
   'snapshots'

```{autodoc2-docstring} chartbook.store.SNAPSHOTS_DIR
```

````

````{py:data} STORE_PLUGIN_GROUP
:canonical: chartbook.store.STORE_PLUGIN_GROUP
:value: >
   'chartbook.stores'

```{autodoc2-docstring} chartbook.store.STORE_PLUGIN_GROUP
```

````

`````{py:class} Store
:canonical: chartbook.store.Store

Bases: {py:obj}`abc.ABC`

```{autodoc2-docstring} chartbook.store.Store
```

````{py:method} add_root(lockfile: typing.Union[str, pathlib.Path], hashes: typing.Iterable[str], snapshots: typing.Iterable[tuple[str, str]] = (), machine: typing.Optional[str] = None, labelled: typing.Iterable[tuple[str, str, str, str]] = ()) -> None
:canonical: chartbook.store.Store.add_root
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.add_root
```

````

````{py:method} age_of(content_hash: str, now: typing.Optional[float] = None) -> float
:canonical: chartbook.store.Store.age_of
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.age_of
```

````

````{py:method} all_snapshot_files() -> list[pathlib.Path]
:canonical: chartbook.store.Store.all_snapshot_files
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.all_snapshot_files
```

````

````{py:method} delete(content_hash: str) -> bool
:canonical: chartbook.store.Store.delete
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.delete
```

````

````{py:method} get(content_hash: str) -> pathlib.Path
:canonical: chartbook.store.Store.get
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.get
```

````

````{py:method} has(content_hash: str) -> bool
:canonical: chartbook.store.Store.has
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.has
```

````

````{py:method} hashes() -> typing.Iterator[str]
:canonical: chartbook.store.Store.hashes
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.hashes
```

````

````{py:method} incomplete(content_hash: str, size_bytes: typing.Optional[int], files: typing.Optional[dict] = None, every: bool = False) -> typing.Optional[str]
:canonical: chartbook.store.Store.incomplete

```{autodoc2-docstring} chartbook.store.Store.incomplete
```

````

````{py:method} lacks(content_hash: str, names: typing.Iterable[str], single: bool = True) -> bool
:canonical: chartbook.store.Store.lacks

```{autodoc2-docstring} chartbook.store.Store.lacks
```

````

````{py:method} note_origin(commit: str, name: str, top: str) -> None
:canonical: chartbook.store.Store.note_origin
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.note_origin
```

````

````{py:method} origins(commit: str, name: str) -> list[str]
:canonical: chartbook.store.Store.origins
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.origins
```

````

````{py:method} put(path: typing.Union[str, pathlib.Path], links: typing.Iterable[str] = LINKS) -> chartbook.store.StoredObject
:canonical: chartbook.store.Store.put
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.put
```

````

````{py:method} remove_root(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> bool
:canonical: chartbook.store.Store.remove_root
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.remove_root
```

````

````{py:method} remove_snapshot(path: pathlib.Path) -> bool
:canonical: chartbook.store.Store.remove_snapshot
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.remove_snapshot
```

````

````{py:method} root_of(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> typing.Optional[chartbook.store.Root]
:canonical: chartbook.store.Store.root_of

```{autodoc2-docstring} chartbook.store.Store.root_of
```

````

````{py:method} roots() -> list[chartbook.store.Root]
:canonical: chartbook.store.Store.roots
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.roots
```

````

````{py:method} size_of(content_hash: str) -> int
:canonical: chartbook.store.Store.size_of
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.size_of
```

````

````{py:method} snapshot_commits() -> set[str]
:canonical: chartbook.store.Store.snapshot_commits
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.snapshot_commits
```

````

````{py:method} snapshot_files(commit: str, name: str) -> list[pathlib.Path]
:canonical: chartbook.store.Store.snapshot_files
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.snapshot_files
```

````

````{py:method} verify(content_hashes: typing.Optional[typing.Iterable[str]] = None) -> list[chartbook.store.StoreProblem]
:canonical: chartbook.store.Store.verify
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.verify
```

````

````{py:method} write_snapshot(commit: str, name: str, stamp: str, document: dict) -> pathlib.Path
:canonical: chartbook.store.Store.write_snapshot
:abstractmethod:

```{autodoc2-docstring} chartbook.store.Store.write_snapshot
```

````

`````

````{py:exception} StoreError()
:canonical: chartbook.store.StoreError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.store.StoreError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.store.StoreError.__init__
```

````

`````{py:class} StoreProblem
:canonical: chartbook.store.StoreProblem

```{autodoc2-docstring} chartbook.store.StoreProblem
```

````{py:attribute} content_hash
:canonical: chartbook.store.StoreProblem.content_hash
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoreProblem.content_hash
```

````

````{py:method} format() -> str
:canonical: chartbook.store.StoreProblem.format

```{autodoc2-docstring} chartbook.store.StoreProblem.format
```

````

````{py:attribute} message
:canonical: chartbook.store.StoreProblem.message
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoreProblem.message
```

````

````{py:attribute} path
:canonical: chartbook.store.StoreProblem.path
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoreProblem.path
```

````

`````

````{py:exception} StoreUnreachableError()
:canonical: chartbook.store.StoreUnreachableError

Bases: {py:obj}`chartbook.store.StoreError`

```{autodoc2-docstring} chartbook.store.StoreUnreachableError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.store.StoreUnreachableError.__init__
```

````

`````{py:class} StoredObject
:canonical: chartbook.store.StoredObject

```{autodoc2-docstring} chartbook.store.StoredObject
```

````{py:attribute} content_hash
:canonical: chartbook.store.StoredObject.content_hash
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoredObject.content_hash
```

````

````{py:attribute} created
:canonical: chartbook.store.StoredObject.created
:type: bool
:value: >
   True

```{autodoc2-docstring} chartbook.store.StoredObject.created
```

````

````{py:attribute} entries
:canonical: chartbook.store.StoredObject.entries
:type: tuple[chartbook.hashing.FileEntry, ...]
:value: >
   ()

```{autodoc2-docstring} chartbook.store.StoredObject.entries
```

````

````{py:attribute} files
:canonical: chartbook.store.StoredObject.files
:type: tuple[str, ...]
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoredObject.files
```

````

````{py:property} frozen
:canonical: chartbook.store.StoredObject.frozen
:type: bool

```{autodoc2-docstring} chartbook.store.StoredObject.frozen
```

````

````{py:attribute} links
:canonical: chartbook.store.StoredObject.links
:type: tuple[str, ...]
:value: >
   ()

```{autodoc2-docstring} chartbook.store.StoredObject.links
```

````

````{py:attribute} path
:canonical: chartbook.store.StoredObject.path
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoredObject.path
```

````

````{py:attribute} size_bytes
:canonical: chartbook.store.StoredObject.size_bytes
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.store.StoredObject.size_bytes
```

````

`````

````{py:data} TMP_DIR
:canonical: chartbook.store.TMP_DIR
:value: >
   'tmp'

```{autodoc2-docstring} chartbook.store.TMP_DIR
```

````

````{py:function} declared_name(declared: str) -> typing.Optional[str]
:canonical: chartbook.store.declared_name

```{autodoc2-docstring} chartbook.store.declared_name
```
````

````{py:function} default_store() -> chartbook.store.Store
:canonical: chartbook.store.default_store

```{autodoc2-docstring} chartbook.store.default_store
```
````

````{py:function} is_record_name(name: str) -> bool
:canonical: chartbook.store.is_record_name

```{autodoc2-docstring} chartbook.store.is_record_name
```
````

````{py:function} is_root_name(name: str) -> bool
:canonical: chartbook.store.is_root_name

```{autodoc2-docstring} chartbook.store.is_root_name
```
````

````{py:function} link_target(path) -> str
:canonical: chartbook.store.link_target

```{autodoc2-docstring} chartbook.store.link_target
```
````

````{py:function} on_disk(folder: pathlib.Path, parts: list[str]) -> pathlib.Path
:canonical: chartbook.store.on_disk

```{autodoc2-docstring} chartbook.store.on_disk
```
````

````{py:function} plain_parts(relative: str) -> typing.Optional[list[str]]
:canonical: chartbook.store.plain_parts

```{autodoc2-docstring} chartbook.store.plain_parts
```
````

````{py:function} read_root(stored: dict, note: str = '') -> chartbook.store.Root
:canonical: chartbook.store.read_root

```{autodoc2-docstring} chartbook.store.read_root
```
````

````{py:function} root_document(lockfile: typing.Union[str, pathlib.Path], hashes: typing.Iterable[str], snapshots: typing.Iterable[tuple[str, str]], machine: str, labelled: typing.Iterable[tuple[str, str, str, str]] = ()) -> dict
:canonical: chartbook.store.root_document

```{autodoc2-docstring} chartbook.store.root_document
```
````

````{py:function} root_name(lockfile: typing.Union[str, pathlib.Path], machine: str = '') -> str
:canonical: chartbook.store.root_name

```{autodoc2-docstring} chartbook.store.root_name
```
````

````{py:function} store_for_url(url: str) -> chartbook.store.Store
:canonical: chartbook.store.store_for_url

```{autodoc2-docstring} chartbook.store.store_for_url
```
````

````{py:function} this_host() -> str
:canonical: chartbook.store.this_host

```{autodoc2-docstring} chartbook.store.this_host
```
````

````{py:function} this_machine(create: bool = True) -> str
:canonical: chartbook.store.this_machine

```{autodoc2-docstring} chartbook.store.this_machine
```
````

````{py:function} this_node() -> str
:canonical: chartbook.store.this_node

```{autodoc2-docstring} chartbook.store.this_node
```
````

````{py:function} unreadable_detail(path: pathlib.Path, error: Exception) -> str
:canonical: chartbook.store.unreadable_detail

```{autodoc2-docstring} chartbook.store.unreadable_detail
```
````

````{py:function} unsynced_part(path: pathlib.Path, size_bytes: int, files: typing.Optional[dict] = None, every: bool = False, content_hash: str = '') -> typing.Optional[tuple[str, bool]]
:canonical: chartbook.store.unsynced_part

```{autodoc2-docstring} chartbook.store.unsynced_part
```
````

````{py:function} what_is_wrong(content_hash: str, path: pathlib.Path) -> typing.Optional[str]
:canonical: chartbook.store.what_is_wrong

```{autodoc2-docstring} chartbook.store.what_is_wrong
```
````
