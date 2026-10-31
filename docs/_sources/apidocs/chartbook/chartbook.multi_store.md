# {py:mod}`chartbook.multi_store`

```{py:module} chartbook.multi_store
```

```{autodoc2-docstring} chartbook.multi_store
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`NamedStore <chartbook.multi_store.NamedStore>`
  - ```{autodoc2-docstring} chartbook.multi_store.NamedStore
    :summary:
    ```
* - {py:obj}`Stores <chartbook.multi_store.Stores>`
  - ```{autodoc2-docstring} chartbook.multi_store.Stores
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`with_dependencies <chartbook.multi_store.with_dependencies>`
  - ```{autodoc2-docstring} chartbook.multi_store.with_dependencies
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`selected_store <chartbook.multi_store.selected_store>`
  - ```{autodoc2-docstring} chartbook.multi_store.selected_store
    :summary:
    ```
* - {py:obj}`settings_warnings <chartbook.multi_store.settings_warnings>`
  - ```{autodoc2-docstring} chartbook.multi_store.settings_warnings
    :summary:
    ```
````

### API

`````{py:class} NamedStore
:canonical: chartbook.multi_store.NamedStore

```{autodoc2-docstring} chartbook.multi_store.NamedStore
```

````{py:attribute} create
:canonical: chartbook.multi_store.NamedStore.create
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.multi_store.NamedStore.create
```

````

````{py:attribute} name
:canonical: chartbook.multi_store.NamedStore.name
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.multi_store.NamedStore.name
```

````

````{py:attribute} pipelines
:canonical: chartbook.multi_store.NamedStore.pipelines
:type: tuple[str, ...]
:value: >
   ()

```{autodoc2-docstring} chartbook.multi_store.NamedStore.pipelines
```

````

````{py:property} reachable
:canonical: chartbook.multi_store.NamedStore.reachable

```{autodoc2-docstring} chartbook.multi_store.NamedStore.reachable
```

````

````{py:attribute} read_only
:canonical: chartbook.multi_store.NamedStore.read_only
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.multi_store.NamedStore.read_only
```

````

````{py:attribute} store
:canonical: chartbook.multi_store.NamedStore.store
:type: object
:value: >
   None

```{autodoc2-docstring} chartbook.multi_store.NamedStore.store
```

````

````{py:attribute} unavailable
:canonical: chartbook.multi_store.NamedStore.unavailable
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.multi_store.NamedStore.unavailable
```

````

````{py:attribute} url
:canonical: chartbook.multi_store.NamedStore.url
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.multi_store.NamedStore.url
```

````

`````

`````{py:class} Stores(entries, catalog=None)
:canonical: chartbook.multi_store.Stores

```{autodoc2-docstring} chartbook.multi_store.Stores
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.multi_store.Stores.__init__
```

````{py:method} add_root(lockfile, hashes, snapshots=(), machine=None, labelled=())
:canonical: chartbook.multi_store.Stores.add_root

```{autodoc2-docstring} chartbook.multi_store.Stores.add_root
```

````

````{py:method} age_of(content_hash, now=None)
:canonical: chartbook.multi_store.Stores.age_of

```{autodoc2-docstring} chartbook.multi_store.Stores.age_of
```

````

````{py:method} all_snapshot_files()
:canonical: chartbook.multi_store.Stores.all_snapshot_files

```{autodoc2-docstring} chartbook.multi_store.Stores.all_snapshot_files
```

````

````{py:method} begin(*args, **kwargs)
:canonical: chartbook.multi_store.Stores.begin

```{autodoc2-docstring} chartbook.multi_store.Stores.begin
```

````

````{py:method} configured(catalog=None)
:canonical: chartbook.multi_store.Stores.configured
:classmethod:

```{autodoc2-docstring} chartbook.multi_store.Stores.configured
```

````

````{py:method} default()
:canonical: chartbook.multi_store.Stores.default

```{autodoc2-docstring} chartbook.multi_store.Stores.default
```

````

````{py:method} files_of(content_hash)
:canonical: chartbook.multi_store.Stores.files_of

```{autodoc2-docstring} chartbook.multi_store.Stores.files_of
```

````

````{py:method} find(commit, subdirectory='')
:canonical: chartbook.multi_store.Stores.find

```{autodoc2-docstring} chartbook.multi_store.Stores.find
```

````

````{py:method} for_writing(pipeline, names=None)
:canonical: chartbook.multi_store.Stores.for_writing

```{autodoc2-docstring} chartbook.multi_store.Stores.for_writing
```

````

````{py:method} get(content_hash, pipeline=None, name=None)
:canonical: chartbook.multi_store.Stores.get

```{autodoc2-docstring} chartbook.multi_store.Stores.get
```

````

````{py:method} has(content_hash, pipeline=None)
:canonical: chartbook.multi_store.Stores.has

```{autodoc2-docstring} chartbook.multi_store.Stores.has
```

````

````{py:method} hashes()
:canonical: chartbook.multi_store.Stores.hashes

```{autodoc2-docstring} chartbook.multi_store.Stores.hashes
```

````

````{py:method} held_hashes()
:canonical: chartbook.multi_store.Stores.held_hashes

```{autodoc2-docstring} chartbook.multi_store.Stores.held_hashes
```

````

````{py:method} in_order()
:canonical: chartbook.multi_store.Stores.in_order

```{autodoc2-docstring} chartbook.multi_store.Stores.in_order
```

````

````{py:method} incomplete(content_hash, size_bytes, files=None, every=False)
:canonical: chartbook.multi_store.Stores.incomplete

```{autodoc2-docstring} chartbook.multi_store.Stores.incomplete
```

````

````{py:method} listing(content_hash, single)
:canonical: chartbook.multi_store.Stores.listing

```{autodoc2-docstring} chartbook.multi_store.Stores.listing
```

````

````{py:method} name_of(path)
:canonical: chartbook.multi_store.Stores.name_of

```{autodoc2-docstring} chartbook.multi_store.Stores.name_of
```

````

````{py:method} named(name)
:canonical: chartbook.multi_store.Stores.named

```{autodoc2-docstring} chartbook.multi_store.Stores.named
```

````

````{py:method} origins(commit, name)
:canonical: chartbook.multi_store.Stores.origins

```{autodoc2-docstring} chartbook.multi_store.Stores.origins
```

````

````{py:method} pinned_snapshot_files()
:canonical: chartbook.multi_store.Stores.pinned_snapshot_files

```{autodoc2-docstring} chartbook.multi_store.Stores.pinned_snapshot_files
```

````

````{py:method} put(*args, **kwargs)
:canonical: chartbook.multi_store.Stores.put

```{autodoc2-docstring} chartbook.multi_store.Stores.put
```

````

````{py:method} reading()
:canonical: chartbook.multi_store.Stores.reading

```{autodoc2-docstring} chartbook.multi_store.Stores.reading
```

````

````{py:method} remove_root(lockfile, machine=None)
:canonical: chartbook.multi_store.Stores.remove_root

```{autodoc2-docstring} chartbook.multi_store.Stores.remove_root
```

````

````{py:method} root_of(lockfile, machine=None)
:canonical: chartbook.multi_store.Stores.root_of

```{autodoc2-docstring} chartbook.multi_store.Stores.root_of
```

````

````{py:method} roots()
:canonical: chartbook.multi_store.Stores.roots

```{autodoc2-docstring} chartbook.multi_store.Stores.roots
```

````

````{py:method} size_of(content_hash)
:canonical: chartbook.multi_store.Stores.size_of

```{autodoc2-docstring} chartbook.multi_store.Stores.size_of
```

````

````{py:method} snapshot_commit_prefixes()
:canonical: chartbook.multi_store.Stores.snapshot_commit_prefixes

```{autodoc2-docstring} chartbook.multi_store.Stores.snapshot_commit_prefixes
```

````

````{py:method} snapshot_commits()
:canonical: chartbook.multi_store.Stores.snapshot_commits

```{autodoc2-docstring} chartbook.multi_store.Stores.snapshot_commits
```

````

````{py:method} snapshot_files(commit, name)
:canonical: chartbook.multi_store.Stores.snapshot_files

```{autodoc2-docstring} chartbook.multi_store.Stores.snapshot_files
```

````

````{py:method} snapshots(pipeline=None)
:canonical: chartbook.multi_store.Stores.snapshots

```{autodoc2-docstring} chartbook.multi_store.Stores.snapshots
```

````

````{py:method} verify(content_hashes=None)
:canonical: chartbook.multi_store.Stores.verify

```{autodoc2-docstring} chartbook.multi_store.Stores.verify
```

````

`````

````{py:data} selected_store
:canonical: chartbook.multi_store.selected_store
:value: >
   'ContextVar(...)'

```{autodoc2-docstring} chartbook.multi_store.selected_store
```

````

````{py:data} settings_warnings
:canonical: chartbook.multi_store.settings_warnings
:value: >
   'set(...)'

```{autodoc2-docstring} chartbook.multi_store.settings_warnings
```

````

````{py:function} with_dependencies(folder, store=None)
:canonical: chartbook.multi_store.with_dependencies

```{autodoc2-docstring} chartbook.multi_store.with_dependencies
```
````
