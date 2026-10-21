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

* - {py:obj}`URL_OPTIONS <chartbook.stores.s3.URL_OPTIONS>`
  - ```{autodoc2-docstring} chartbook.stores.s3.URL_OPTIONS
    :summary:
    ```
* - {py:obj}`VERIFIED_DIR <chartbook.stores.s3.VERIFIED_DIR>`
  - ```{autodoc2-docstring} chartbook.stores.s3.VERIFIED_DIR
    :summary:
    ```
````

### API

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

````{py:property} cache
:canonical: chartbook.stores.s3.S3Store.cache
:type: pathlib.Path

```{autodoc2-docstring} chartbook.stores.s3.S3Store.cache
```

````

````{py:method} delete(content_hash: str) -> bool
:canonical: chartbook.stores.s3.S3Store.delete

````

````{py:method} get(content_hash: str) -> pathlib.Path
:canonical: chartbook.stores.s3.S3Store.get

```{autodoc2-docstring} chartbook.stores.s3.S3Store.get
```

````

````{py:method} has(content_hash: str) -> bool
:canonical: chartbook.stores.s3.S3Store.has

````

````{py:method} hashes() -> typing.Iterator[str]
:canonical: chartbook.stores.s3.S3Store.hashes

````

````{py:method} incomplete(content_hash: str, size_bytes: typing.Optional[int], files: typing.Optional[dict] = None, every: bool = False) -> typing.Optional[str]
:canonical: chartbook.stores.s3.S3Store.incomplete

```{autodoc2-docstring} chartbook.stores.s3.S3Store.incomplete
```

````

````{py:method} note_origin(commit: str, name: str, top: str) -> None
:canonical: chartbook.stores.s3.S3Store.note_origin

````

````{py:method} origins(commit: str, name: str) -> list[str]
:canonical: chartbook.stores.s3.S3Store.origins

````

````{py:method} put(path: typing.Union[str, pathlib.Path], links: typing.Iterable[str] = LINKS) -> chartbook.store.StoredObject
:canonical: chartbook.stores.s3.S3Store.put

```{autodoc2-docstring} chartbook.stores.s3.S3Store.put
```

````

````{py:method} remove_root(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> bool
:canonical: chartbook.stores.s3.S3Store.remove_root

````

````{py:method} remove_snapshot(path: pathlib.Path) -> bool
:canonical: chartbook.stores.s3.S3Store.remove_snapshot

````

````{py:method} root_of(lockfile: typing.Union[str, pathlib.Path], machine: typing.Optional[str] = None) -> typing.Optional[chartbook.store.Root]
:canonical: chartbook.stores.s3.S3Store.root_of

````

````{py:method} roots() -> list[chartbook.store.Root]
:canonical: chartbook.stores.s3.S3Store.roots

````

````{py:method} size_of(content_hash: str) -> int
:canonical: chartbook.stores.s3.S3Store.size_of

````

````{py:method} snapshot_commits() -> set[str]
:canonical: chartbook.stores.s3.S3Store.snapshot_commits

````

````{py:method} snapshot_files(commit: str, name: str) -> list[pathlib.Path]
:canonical: chartbook.stores.s3.S3Store.snapshot_files

````

````{py:method} verify(content_hashes: typing.Optional[typing.Iterable[str]] = None) -> list[chartbook.store.StoreProblem]
:canonical: chartbook.stores.s3.S3Store.verify

```{autodoc2-docstring} chartbook.stores.s3.S3Store.verify
```

````

````{py:method} write_snapshot(commit: str, name: str, stamp: str, document: dict) -> pathlib.Path
:canonical: chartbook.stores.s3.S3Store.write_snapshot

````

`````

````{py:data} URL_OPTIONS
:canonical: chartbook.stores.s3.URL_OPTIONS
:value: >
   ('endpoint', 'region')

```{autodoc2-docstring} chartbook.stores.s3.URL_OPTIONS
```

````

````{py:data} VERIFIED_DIR
:canonical: chartbook.stores.s3.VERIFIED_DIR
:value: >
   'verified'

```{autodoc2-docstring} chartbook.stores.s3.VERIFIED_DIR
```

````
