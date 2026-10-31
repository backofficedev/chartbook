# {py:mod}`chartbook.stores.s3`

```{py:module} chartbook.stores.s3
```

```{autodoc2-docstring} chartbook.stores.s3
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`S3Store <chartbook.stores.s3.S3Store>`
  - ```{autodoc2-docstring} chartbook.stores.s3.S3Store
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ALIVE_SECONDS <chartbook.stores.s3.ALIVE_SECONDS>`
  - ```{autodoc2-docstring} chartbook.stores.s3.ALIVE_SECONDS
    :summary:
    ```
* - {py:obj}`CHECKED_DIR <chartbook.stores.s3.CHECKED_DIR>`
  - ```{autodoc2-docstring} chartbook.stores.s3.CHECKED_DIR
    :summary:
    ```
* - {py:obj}`CLAIMED_FILE <chartbook.stores.s3.CLAIMED_FILE>`
  - ```{autodoc2-docstring} chartbook.stores.s3.CLAIMED_FILE
    :summary:
    ```
* - {py:obj}`COPY_LIMIT <chartbook.stores.s3.COPY_LIMIT>`
  - ```{autodoc2-docstring} chartbook.stores.s3.COPY_LIMIT
    :summary:
    ```
* - {py:obj}`LISTING_SECONDS <chartbook.stores.s3.LISTING_SECONDS>`
  - ```{autodoc2-docstring} chartbook.stores.s3.LISTING_SECONDS
    :summary:
    ```
* - {py:obj}`URL_OPTIONS <chartbook.stores.s3.URL_OPTIONS>`
  - ```{autodoc2-docstring} chartbook.stores.s3.URL_OPTIONS
    :summary:
    ```
````

### API

````{py:data} ALIVE_SECONDS
:canonical: chartbook.stores.s3.ALIVE_SECONDS
:value: >
   300

```{autodoc2-docstring} chartbook.stores.s3.ALIVE_SECONDS
```

````

````{py:data} CHECKED_DIR
:canonical: chartbook.stores.s3.CHECKED_DIR
:value: >
   'files'

```{autodoc2-docstring} chartbook.stores.s3.CHECKED_DIR
```

````

````{py:data} CLAIMED_FILE
:canonical: chartbook.stores.s3.CLAIMED_FILE
:value: >
   'CLAIMED.txt'

```{autodoc2-docstring} chartbook.stores.s3.CLAIMED_FILE
```

````

````{py:data} COPY_LIMIT
:canonical: chartbook.stores.s3.COPY_LIMIT
:value: >
   None

```{autodoc2-docstring} chartbook.stores.s3.COPY_LIMIT
```

````

````{py:data} LISTING_SECONDS
:canonical: chartbook.stores.s3.LISTING_SECONDS
:value: >
   2.0

```{autodoc2-docstring} chartbook.stores.s3.LISTING_SECONDS
```

````

`````{py:class} S3Store(url: str, cache: typing.Union[str, pathlib.Path, None] = None, client=None)
:canonical: chartbook.stores.s3.S3Store

Bases: {py:obj}`chartbook.store.Store`

```{autodoc2-docstring} chartbook.stores.s3.S3Store
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.stores.s3.S3Store.__init__
```

````{py:method} add_root(lockfile: typing.Union[str, pathlib.Path], hashes: typing.Iterable[str], snapshots: typing.Iterable[tuple[str, str]] = (), machine: typing.Optional[str] = None, labelled: typing.Iterable[tuple[str, str, str, str]] = ()) -> None
:canonical: chartbook.stores.s3.S3Store.add_root

````

````{py:method} age_of(content_hash: str, now: typing.Optional[float] = None) -> float
:canonical: chartbook.stores.s3.S3Store.age_of

```{autodoc2-docstring} chartbook.stores.s3.S3Store.age_of
```

````

````{py:method} all_snapshot_files() -> list[pathlib.Path]
:canonical: chartbook.stores.s3.S3Store.all_snapshot_files

````

````{py:method} begin(pipeline: str, commit: str, made_at: str, base: typing.Optional[typing.Union[str, pathlib.Path]] = None, made_by: str = 'snapshot') -> chartbook.store.PendingSnapshot
:canonical: chartbook.stores.s3.S3Store.begin

````

````{py:property} cache
:canonical: chartbook.stores.s3.S3Store.cache
:type: pathlib.Path

```{autodoc2-docstring} chartbook.stores.s3.S3Store.cache
```

````

````{py:method} delete(content_hash: str) -> bool
:canonical: chartbook.stores.s3.S3Store.delete

```{autodoc2-docstring} chartbook.stores.s3.S3Store.delete
```

````

````{py:method} delete_unowned(content_hash: str) -> bool
:canonical: chartbook.stores.s3.S3Store.delete_unowned

```{autodoc2-docstring} chartbook.stores.s3.S3Store.delete_unowned
```

````

````{py:method} files_of(content_hash: str) -> list[tuple[str, int]]
:canonical: chartbook.stores.s3.S3Store.files_of

```{autodoc2-docstring} chartbook.stores.s3.S3Store.files_of
```

````

````{py:method} get(content_hash: str, pipeline: typing.Optional[str] = None, name: typing.Optional[str] = None) -> pathlib.Path
:canonical: chartbook.stores.s3.S3Store.get

```{autodoc2-docstring} chartbook.stores.s3.S3Store.get
```

````

````{py:method} has(content_hash: str, pipeline: typing.Optional[str] = None) -> bool
:canonical: chartbook.stores.s3.S3Store.has

```{autodoc2-docstring} chartbook.stores.s3.S3Store.has
```

````

````{py:method} hashes() -> typing.Iterator[str]
:canonical: chartbook.stores.s3.S3Store.hashes

```{autodoc2-docstring} chartbook.stores.s3.S3Store.hashes
```

````

````{py:method} held_hashes() -> set[str]
:canonical: chartbook.stores.s3.S3Store.held_hashes

````

````{py:method} incomplete(content_hash: str, size_bytes: typing.Optional[int], files: typing.Optional[dict] = None, every: bool = False) -> typing.Optional[str]
:canonical: chartbook.stores.s3.S3Store.incomplete

```{autodoc2-docstring} chartbook.stores.s3.S3Store.incomplete
```

````

````{py:method} lacks(content_hash: str, names: typing.Iterable[str], single: bool = True) -> bool
:canonical: chartbook.stores.s3.S3Store.lacks

```{autodoc2-docstring} chartbook.stores.s3.S3Store.lacks
```

````

````{py:method} listing(content_hash: str, single: bool)
:canonical: chartbook.stores.s3.S3Store.listing

````

````{py:method} note_origin(commit: str, name: str, top: str) -> None
:canonical: chartbook.stores.s3.S3Store.note_origin

````

````{py:method} origins(commit: str, name: str) -> list[str]
:canonical: chartbook.stores.s3.S3Store.origins

```{autodoc2-docstring} chartbook.stores.s3.S3Store.origins
```

````

````{py:method} pinned_snapshot_files() -> list[pathlib.Path]
:canonical: chartbook.stores.s3.S3Store.pinned_snapshot_files

````

````{py:method} put(path: typing.Union[str, pathlib.Path], links: typing.Iterable[str] = LINKS) -> chartbook.store.StoredObject
:canonical: chartbook.stores.s3.S3Store.put

```{autodoc2-docstring} chartbook.stores.s3.S3Store.put
```

````

````{py:method} reading()
:canonical: chartbook.stores.s3.S3Store.reading

```{autodoc2-docstring} chartbook.stores.s3.S3Store.reading
```

````

````{py:method} records() -> list[chartbook.store.KeptRecord]
:canonical: chartbook.stores.s3.S3Store.records

```{autodoc2-docstring} chartbook.stores.s3.S3Store.records
```

````

````{py:method} remove_root(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> bool
:canonical: chartbook.stores.s3.S3Store.remove_root

````

````{py:method} remove_snapshot(path: pathlib.Path) -> bool
:canonical: chartbook.stores.s3.S3Store.remove_snapshot

```{autodoc2-docstring} chartbook.stores.s3.S3Store.remove_snapshot
```

````

````{py:method} root_of(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> typing.Optional[chartbook.store.Root]
:canonical: chartbook.stores.s3.S3Store.root_of

````

````{py:method} roots() -> list[chartbook.store.Root]
:canonical: chartbook.stores.s3.S3Store.roots

````

````{py:method} size_of(content_hash: str) -> int
:canonical: chartbook.stores.s3.S3Store.size_of

```{autodoc2-docstring} chartbook.stores.s3.S3Store.size_of
```

````

````{py:method} snapshot_commit_prefixes() -> set[str]
:canonical: chartbook.stores.s3.S3Store.snapshot_commit_prefixes

````

````{py:method} snapshot_commits() -> set[str]
:canonical: chartbook.stores.s3.S3Store.snapshot_commits

````

````{py:method} snapshot_files(commit: str, name: str) -> list[pathlib.Path]
:canonical: chartbook.stores.s3.S3Store.snapshot_files

````

````{py:method} tidy(dry_run: bool = False, keep: typing.Iterable[str] = ()) -> list[tuple[str, int]]
:canonical: chartbook.stores.s3.S3Store.tidy

```{autodoc2-docstring} chartbook.stores.s3.S3Store.tidy
```

````

````{py:method} verify(content_hashes: typing.Optional[typing.Iterable[str]] = None) -> list[chartbook.store.StoreProblem]
:canonical: chartbook.stores.s3.S3Store.verify

```{autodoc2-docstring} chartbook.stores.s3.S3Store.verify
```

````

````{py:property} views
:canonical: chartbook.stores.s3.S3Store.views
:type: pathlib.Path

```{autodoc2-docstring} chartbook.stores.s3.S3Store.views
```

````

`````

````{py:data} URL_OPTIONS
:canonical: chartbook.stores.s3.URL_OPTIONS
:value: >
   ('endpoint', 'region', 'anonymous')

```{autodoc2-docstring} chartbook.stores.s3.URL_OPTIONS
```

````
