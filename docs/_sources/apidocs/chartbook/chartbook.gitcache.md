# {py:mod}`chartbook.gitcache`

```{py:module} chartbook.gitcache
```

```{autodoc2-docstring} chartbook.gitcache
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Checkout <chartbook.gitcache.Checkout>`
  - ```{autodoc2-docstring} chartbook.gitcache.Checkout
    :summary:
    ```
* - {py:obj}`GitCache <chartbook.gitcache.GitCache>`
  - ```{autodoc2-docstring} chartbook.gitcache.GitCache
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`check_git_url <chartbook.gitcache.check_git_url>`
  - ```{autodoc2-docstring} chartbook.gitcache.check_git_url
    :summary:
    ```
* - {py:obj}`check_rev <chartbook.gitcache.check_rev>`
  - ```{autodoc2-docstring} chartbook.gitcache.check_rev
    :summary:
    ```
* - {py:obj}`default_git_cache <chartbook.gitcache.default_git_cache>`
  - ```{autodoc2-docstring} chartbook.gitcache.default_git_cache
    :summary:
    ```
* - {py:obj}`forget_built <chartbook.gitcache.forget_built>`
  - ```{autodoc2-docstring} chartbook.gitcache.forget_built
    :summary:
    ```
* - {py:obj}`is_built <chartbook.gitcache.is_built>`
  - ```{autodoc2-docstring} chartbook.gitcache.is_built
    :summary:
    ```
* - {py:obj}`local_url <chartbook.gitcache.local_url>`
  - ```{autodoc2-docstring} chartbook.gitcache.local_url
    :summary:
    ```
* - {py:obj}`mark_built <chartbook.gitcache.mark_built>`
  - ```{autodoc2-docstring} chartbook.gitcache.mark_built
    :summary:
    ```
* - {py:obj}`repository_slug <chartbook.gitcache.repository_slug>`
  - ```{autodoc2-docstring} chartbook.gitcache.repository_slug
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ALLOWED_PROTOCOLS <chartbook.gitcache.ALLOWED_PROTOCOLS>`
  - ```{autodoc2-docstring} chartbook.gitcache.ALLOWED_PROTOCOLS
    :summary:
    ```
* - {py:obj}`BUILT_MARKER <chartbook.gitcache.BUILT_MARKER>`
  - ```{autodoc2-docstring} chartbook.gitcache.BUILT_MARKER
    :summary:
    ```
* - {py:obj}`CHECKOUTS_DIR <chartbook.gitcache.CHECKOUTS_DIR>`
  - ```{autodoc2-docstring} chartbook.gitcache.CHECKOUTS_DIR
    :summary:
    ```
* - {py:obj}`DEFAULT_REF <chartbook.gitcache.DEFAULT_REF>`
  - ```{autodoc2-docstring} chartbook.gitcache.DEFAULT_REF
    :summary:
    ```
* - {py:obj}`GIT <chartbook.gitcache.GIT>`
  - ```{autodoc2-docstring} chartbook.gitcache.GIT
    :summary:
    ```
* - {py:obj}`GIT_LOCATION_VARIABLES <chartbook.gitcache.GIT_LOCATION_VARIABLES>`
  - ```{autodoc2-docstring} chartbook.gitcache.GIT_LOCATION_VARIABLES
    :summary:
    ```
* - {py:obj}`REPOS_DIR <chartbook.gitcache.REPOS_DIR>`
  - ```{autodoc2-docstring} chartbook.gitcache.REPOS_DIR
    :summary:
    ```
* - {py:obj}`WORK_DIR <chartbook.gitcache.WORK_DIR>`
  - ```{autodoc2-docstring} chartbook.gitcache.WORK_DIR
    :summary:
    ```
````

### API

````{py:data} ALLOWED_PROTOCOLS
:canonical: chartbook.gitcache.ALLOWED_PROTOCOLS
:value: >
   'file:git:http:https:ssh'

```{autodoc2-docstring} chartbook.gitcache.ALLOWED_PROTOCOLS
```

````

````{py:data} BUILT_MARKER
:canonical: chartbook.gitcache.BUILT_MARKER
:value: >
   '.chartbook-built'

```{autodoc2-docstring} chartbook.gitcache.BUILT_MARKER
```

````

````{py:data} CHECKOUTS_DIR
:canonical: chartbook.gitcache.CHECKOUTS_DIR
:value: >
   'checkouts'

```{autodoc2-docstring} chartbook.gitcache.CHECKOUTS_DIR
```

````

`````{py:class} Checkout
:canonical: chartbook.gitcache.Checkout

```{autodoc2-docstring} chartbook.gitcache.Checkout
```

````{py:attribute} commit
:canonical: chartbook.gitcache.Checkout.commit
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.gitcache.Checkout.commit
```

````

````{py:attribute} path
:canonical: chartbook.gitcache.Checkout.path
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.gitcache.Checkout.path
```

````

````{py:attribute} rev
:canonical: chartbook.gitcache.Checkout.rev
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.gitcache.Checkout.rev
```

````

````{py:attribute} url
:canonical: chartbook.gitcache.Checkout.url
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.gitcache.Checkout.url
```

````

`````

````{py:data} DEFAULT_REF
:canonical: chartbook.gitcache.DEFAULT_REF
:value: >
   'refs/chartbook/default'

```{autodoc2-docstring} chartbook.gitcache.DEFAULT_REF
```

````

````{py:data} GIT
:canonical: chartbook.gitcache.GIT
:value: >
   None

```{autodoc2-docstring} chartbook.gitcache.GIT
```

````

````{py:data} GIT_LOCATION_VARIABLES
:canonical: chartbook.gitcache.GIT_LOCATION_VARIABLES
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.gitcache.GIT_LOCATION_VARIABLES
```

````

`````{py:class} GitCache(root: typing.Union[str, pathlib.Path])
:canonical: chartbook.gitcache.GitCache

```{autodoc2-docstring} chartbook.gitcache.GitCache
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.gitcache.GitCache.__init__
```

````{py:method} checkout(url: str, commit: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.checkout

```{autodoc2-docstring} chartbook.gitcache.GitCache.checkout
```

````

````{py:method} checkout_path(url: str, commit: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.checkout_path

```{autodoc2-docstring} chartbook.gitcache.GitCache.checkout_path
```

````

````{py:method} fetch(url: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.fetch

```{autodoc2-docstring} chartbook.gitcache.GitCache.fetch
```

````

````{py:method} files(url: str, commit: str) -> typing.Optional[pathlib.Path]
:canonical: chartbook.gitcache.GitCache.files

```{autodoc2-docstring} chartbook.gitcache.GitCache.files
```

````

````{py:method} find(url: str, commit: str) -> typing.Optional[pathlib.Path]
:canonical: chartbook.gitcache.GitCache.find

```{autodoc2-docstring} chartbook.gitcache.GitCache.find
```

````

````{py:method} find_work(url: str, commit: str) -> typing.Optional[pathlib.Path]
:canonical: chartbook.gitcache.GitCache.find_work

```{autodoc2-docstring} chartbook.gitcache.GitCache.find_work
```

````

````{py:method} get(url: str, rev: typing.Optional[str] = None, fetch: bool = True) -> chartbook.gitcache.Checkout
:canonical: chartbook.gitcache.GitCache.get

```{autodoc2-docstring} chartbook.gitcache.GitCache.get
```

````

````{py:method} repo_path(url: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.repo_path

```{autodoc2-docstring} chartbook.gitcache.GitCache.repo_path
```

````

````{py:method} resolve(url: str, rev: typing.Optional[str] = None) -> str
:canonical: chartbook.gitcache.GitCache.resolve

```{autodoc2-docstring} chartbook.gitcache.GitCache.resolve
```

````

````{py:method} work_copy(url: str, commit: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.work_copy

```{autodoc2-docstring} chartbook.gitcache.GitCache.work_copy
```

````

````{py:method} work_path(url: str, commit: str) -> pathlib.Path
:canonical: chartbook.gitcache.GitCache.work_path

```{autodoc2-docstring} chartbook.gitcache.GitCache.work_path
```

````

`````

````{py:exception} GitError()
:canonical: chartbook.gitcache.GitError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.gitcache.GitError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.gitcache.GitError.__init__
```

````

````{py:data} REPOS_DIR
:canonical: chartbook.gitcache.REPOS_DIR
:value: >
   'repos'

```{autodoc2-docstring} chartbook.gitcache.REPOS_DIR
```

````

````{py:data} WORK_DIR
:canonical: chartbook.gitcache.WORK_DIR
:value: >
   'work'

```{autodoc2-docstring} chartbook.gitcache.WORK_DIR
```

````

````{py:function} check_git_url(url: str) -> str
:canonical: chartbook.gitcache.check_git_url

```{autodoc2-docstring} chartbook.gitcache.check_git_url
```
````

````{py:function} check_rev(rev: typing.Optional[str]) -> typing.Optional[str]
:canonical: chartbook.gitcache.check_rev

```{autodoc2-docstring} chartbook.gitcache.check_rev
```
````

````{py:function} default_git_cache() -> chartbook.gitcache.GitCache
:canonical: chartbook.gitcache.default_git_cache

```{autodoc2-docstring} chartbook.gitcache.default_git_cache
```
````

````{py:function} forget_built(work_copy: typing.Union[str, pathlib.Path]) -> None
:canonical: chartbook.gitcache.forget_built

```{autodoc2-docstring} chartbook.gitcache.forget_built
```
````

````{py:function} is_built(work_copy: typing.Union[str, pathlib.Path]) -> bool
:canonical: chartbook.gitcache.is_built

```{autodoc2-docstring} chartbook.gitcache.is_built
```
````

````{py:function} local_url(url: str, base_dir: typing.Union[str, pathlib.Path]) -> str
:canonical: chartbook.gitcache.local_url

```{autodoc2-docstring} chartbook.gitcache.local_url
```
````

````{py:function} mark_built(work_copy: typing.Union[str, pathlib.Path]) -> None
:canonical: chartbook.gitcache.mark_built

```{autodoc2-docstring} chartbook.gitcache.mark_built
```
````

````{py:function} repository_slug(url: str) -> pathlib.Path
:canonical: chartbook.gitcache.repository_slug

```{autodoc2-docstring} chartbook.gitcache.repository_slug
```
````
