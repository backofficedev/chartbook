# {py:mod}`chartbook.hashing`

```{py:module} chartbook.hashing
```

```{autodoc2-docstring} chartbook.hashing
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ContentHash <chartbook.hashing.ContentHash>`
  - ```{autodoc2-docstring} chartbook.hashing.ContentHash
    :summary:
    ```
* - {py:obj}`FileEntry <chartbook.hashing.FileEntry>`
  - ```{autodoc2-docstring} chartbook.hashing.FileEntry
    :summary:
    ```
* - {py:obj}`HashCache <chartbook.hashing.HashCache>`
  - ```{autodoc2-docstring} chartbook.hashing.HashCache
    :summary:
    ```
* - {py:obj}`PathFiles <chartbook.hashing.PathFiles>`
  - ```{autodoc2-docstring} chartbook.hashing.PathFiles
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`directory_files <chartbook.hashing.directory_files>`
  - ```{autodoc2-docstring} chartbook.hashing.directory_files
    :summary:
    ```
* - {py:obj}`escapes <chartbook.hashing.escapes>`
  - ```{autodoc2-docstring} chartbook.hashing.escapes
    :summary:
    ```
* - {py:obj}`find_files <chartbook.hashing.find_files>`
  - ```{autodoc2-docstring} chartbook.hashing.find_files
    :summary:
    ```
* - {py:obj}`format_hash <chartbook.hashing.format_hash>`
  - ```{autodoc2-docstring} chartbook.hashing.format_hash
    :summary:
    ```
* - {py:obj}`glob_root <chartbook.hashing.glob_root>`
  - ```{autodoc2-docstring} chartbook.hashing.glob_root
    :summary:
    ```
* - {py:obj}`hash_directory <chartbook.hashing.hash_directory>`
  - ```{autodoc2-docstring} chartbook.hashing.hash_directory
    :summary:
    ```
* - {py:obj}`hash_file <chartbook.hashing.hash_file>`
  - ```{autodoc2-docstring} chartbook.hashing.hash_file
    :summary:
    ```
* - {py:obj}`hash_files <chartbook.hashing.hash_files>`
  - ```{autodoc2-docstring} chartbook.hashing.hash_files
    :summary:
    ```
* - {py:obj}`hash_path <chartbook.hashing.hash_path>`
  - ```{autodoc2-docstring} chartbook.hashing.hash_path
    :summary:
    ```
* - {py:obj}`is_ignored <chartbook.hashing.is_ignored>`
  - ```{autodoc2-docstring} chartbook.hashing.is_ignored
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ALGORITHM <chartbook.hashing.ALGORITHM>`
  - ```{autodoc2-docstring} chartbook.hashing.ALGORITHM
    :summary:
    ```
* - {py:obj}`CACHE_FILE <chartbook.hashing.CACHE_FILE>`
  - ```{autodoc2-docstring} chartbook.hashing.CACHE_FILE
    :summary:
    ```
* - {py:obj}`CACHE_VERSION <chartbook.hashing.CACHE_VERSION>`
  - ```{autodoc2-docstring} chartbook.hashing.CACHE_VERSION
    :summary:
    ```
* - {py:obj}`IGNORED_NAMES <chartbook.hashing.IGNORED_NAMES>`
  - ```{autodoc2-docstring} chartbook.hashing.IGNORED_NAMES
    :summary:
    ```
* - {py:obj}`IGNORED_PREFIX <chartbook.hashing.IGNORED_PREFIX>`
  - ```{autodoc2-docstring} chartbook.hashing.IGNORED_PREFIX
    :summary:
    ```
````

### API

````{py:data} ALGORITHM
:canonical: chartbook.hashing.ALGORITHM
:value: >
   'sha256'

```{autodoc2-docstring} chartbook.hashing.ALGORITHM
```

````

````{py:data} CACHE_FILE
:canonical: chartbook.hashing.CACHE_FILE
:value: >
   '.chartbook-hash-cache.json'

```{autodoc2-docstring} chartbook.hashing.CACHE_FILE
```

````

````{py:data} CACHE_VERSION
:canonical: chartbook.hashing.CACHE_VERSION
:value: >
   1

```{autodoc2-docstring} chartbook.hashing.CACHE_VERSION
```

````

`````{py:class} ContentHash
:canonical: chartbook.hashing.ContentHash

```{autodoc2-docstring} chartbook.hashing.ContentHash
```

````{py:attribute} content_hash
:canonical: chartbook.hashing.ContentHash.content_hash
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.ContentHash.content_hash
```

````

````{py:attribute} files
:canonical: chartbook.hashing.ContentHash.files
:type: tuple[chartbook.hashing.FileEntry, ...]
:value: >
   'field(...)'

```{autodoc2-docstring} chartbook.hashing.ContentHash.files
```

````

````{py:attribute} size_bytes
:canonical: chartbook.hashing.ContentHash.size_bytes
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.ContentHash.size_bytes
```

````

`````

`````{py:class} FileEntry
:canonical: chartbook.hashing.FileEntry

```{autodoc2-docstring} chartbook.hashing.FileEntry
```

````{py:attribute} content_hash
:canonical: chartbook.hashing.FileEntry.content_hash
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.FileEntry.content_hash
```

````

````{py:attribute} path
:canonical: chartbook.hashing.FileEntry.path
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.FileEntry.path
```

````

````{py:attribute} size_bytes
:canonical: chartbook.hashing.FileEntry.size_bytes
:type: int
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.FileEntry.size_bytes
```

````

`````

`````{py:class} HashCache(path: typing.Optional[typing.Union[str, pathlib.Path]] = None)
:canonical: chartbook.hashing.HashCache

```{autodoc2-docstring} chartbook.hashing.HashCache
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.hashing.HashCache.__init__
```

````{py:method} file_hex(path: typing.Union[str, pathlib.Path]) -> str
:canonical: chartbook.hashing.HashCache.file_hex

```{autodoc2-docstring} chartbook.hashing.HashCache.file_hex
```

````

````{py:method} save() -> None
:canonical: chartbook.hashing.HashCache.save

```{autodoc2-docstring} chartbook.hashing.HashCache.save
```

````

`````

````{py:data} IGNORED_NAMES
:canonical: chartbook.hashing.IGNORED_NAMES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.hashing.IGNORED_NAMES
```

````

````{py:data} IGNORED_PREFIX
:canonical: chartbook.hashing.IGNORED_PREFIX
:value: >
   '._'

```{autodoc2-docstring} chartbook.hashing.IGNORED_PREFIX
```

````

`````{py:class} PathFiles
:canonical: chartbook.hashing.PathFiles

```{autodoc2-docstring} chartbook.hashing.PathFiles
```

````{py:attribute} files
:canonical: chartbook.hashing.PathFiles.files
:type: tuple[pathlib.Path, ...]
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.PathFiles.files
```

````

````{py:attribute} root
:canonical: chartbook.hashing.PathFiles.root
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.PathFiles.root
```

````

````{py:attribute} single
:canonical: chartbook.hashing.PathFiles.single
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.hashing.PathFiles.single
```

````

`````

````{py:function} directory_files(directory: typing.Union[str, pathlib.Path]) -> list[pathlib.Path]
:canonical: chartbook.hashing.directory_files

```{autodoc2-docstring} chartbook.hashing.directory_files
```
````

````{py:function} escapes(path: typing.Union[str, pathlib.Path], root: typing.Union[str, pathlib.Path]) -> typing.Optional[pathlib.Path]
:canonical: chartbook.hashing.escapes

```{autodoc2-docstring} chartbook.hashing.escapes
```
````

````{py:function} find_files(path: typing.Union[str, pathlib.Path]) -> typing.Optional[chartbook.hashing.PathFiles]
:canonical: chartbook.hashing.find_files

```{autodoc2-docstring} chartbook.hashing.find_files
```
````

````{py:function} format_hash(hex_digest: str) -> str
:canonical: chartbook.hashing.format_hash

```{autodoc2-docstring} chartbook.hashing.format_hash
```
````

````{py:function} glob_root(pattern: typing.Union[str, pathlib.Path]) -> pathlib.Path
:canonical: chartbook.hashing.glob_root

```{autodoc2-docstring} chartbook.hashing.glob_root
```
````

````{py:function} hash_directory(directory: typing.Union[str, pathlib.Path], cache: typing.Optional[chartbook.hashing.HashCache] = None) -> chartbook.hashing.ContentHash
:canonical: chartbook.hashing.hash_directory

```{autodoc2-docstring} chartbook.hashing.hash_directory
```
````

````{py:function} hash_file(path: typing.Union[str, pathlib.Path], cache: typing.Optional[chartbook.hashing.HashCache] = None) -> chartbook.hashing.ContentHash
:canonical: chartbook.hashing.hash_file

```{autodoc2-docstring} chartbook.hashing.hash_file
```
````

````{py:function} hash_files(files: typing.Iterable[typing.Union[str, pathlib.Path]], root: typing.Union[str, pathlib.Path], cache: typing.Optional[chartbook.hashing.HashCache] = None) -> chartbook.hashing.ContentHash
:canonical: chartbook.hashing.hash_files

```{autodoc2-docstring} chartbook.hashing.hash_files
```
````

````{py:function} hash_path(path: typing.Union[str, pathlib.Path], cache: typing.Optional[chartbook.hashing.HashCache] = None) -> typing.Optional[chartbook.hashing.ContentHash]
:canonical: chartbook.hashing.hash_path

```{autodoc2-docstring} chartbook.hashing.hash_path
```
````

````{py:function} is_ignored(name: typing.Union[str, pathlib.Path]) -> bool
:canonical: chartbook.hashing.is_ignored

```{autodoc2-docstring} chartbook.hashing.is_ignored
```
````
