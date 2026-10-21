# {py:mod}`chartbook.identity`

```{py:module} chartbook.identity
```

```{autodoc2-docstring} chartbook.identity
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Checkout <chartbook.identity.Checkout>`
  - ```{autodoc2-docstring} chartbook.identity.Checkout
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`checkout_of <chartbook.identity.checkout_of>`
  - ```{autodoc2-docstring} chartbook.identity.checkout_of
    :summary:
    ```
* - {py:obj}`clear_git_remote_cache <chartbook.identity.clear_git_remote_cache>`
  - ```{autodoc2-docstring} chartbook.identity.clear_git_remote_cache
    :summary:
    ```
* - {py:obj}`derive_pipeline_id <chartbook.identity.derive_pipeline_id>`
  - ```{autodoc2-docstring} chartbook.identity.derive_pipeline_id
    :summary:
    ```
* - {py:obj}`get_git_remote_url <chartbook.identity.get_git_remote_url>`
  - ```{autodoc2-docstring} chartbook.identity.get_git_remote_url
    :summary:
    ```
* - {py:obj}`id_from_address <chartbook.identity.id_from_address>`
  - ```{autodoc2-docstring} chartbook.identity.id_from_address
    :summary:
    ```
* - {py:obj}`in_another_case <chartbook.identity.in_another_case>`
  - ```{autodoc2-docstring} chartbook.identity.in_another_case
    :summary:
    ```
* - {py:obj}`is_repository_top <chartbook.identity.is_repository_top>`
  - ```{autodoc2-docstring} chartbook.identity.is_repository_top
    :summary:
    ```
* - {py:obj}`looks_like_registry <chartbook.identity.looks_like_registry>`
  - ```{autodoc2-docstring} chartbook.identity.looks_like_registry
    :summary:
    ```
* - {py:obj}`match_pipeline_ref <chartbook.identity.match_pipeline_ref>`
  - ```{autodoc2-docstring} chartbook.identity.match_pipeline_ref
    :summary:
    ```
* - {py:obj}`normalize_ref_to_id <chartbook.identity.normalize_ref_to_id>`
  - ```{autodoc2-docstring} chartbook.identity.normalize_ref_to_id
    :summary:
    ```
* - {py:obj}`plain_line <chartbook.identity.plain_line>`
  - ```{autodoc2-docstring} chartbook.identity.plain_line
    :summary:
    ```
* - {py:obj}`read_version_file <chartbook.identity.read_version_file>`
  - ```{autodoc2-docstring} chartbook.identity.read_version_file
    :summary:
    ```
* - {py:obj}`remote_to_web_url <chartbook.identity.remote_to_web_url>`
  - ```{autodoc2-docstring} chartbook.identity.remote_to_web_url
    :summary:
    ```
* - {py:obj}`repository_key <chartbook.identity.repository_key>`
  - ```{autodoc2-docstring} chartbook.identity.repository_key
    :summary:
    ```
* - {py:obj}`resolve_pipeline_ref <chartbook.identity.resolve_pipeline_ref>`
  - ```{autodoc2-docstring} chartbook.identity.resolve_pipeline_ref
    :summary:
    ```
* - {py:obj}`same_pipeline_checked_out <chartbook.identity.same_pipeline_checked_out>`
  - ```{autodoc2-docstring} chartbook.identity.same_pipeline_checked_out
    :summary:
    ```
* - {py:obj}`split_registry <chartbook.identity.split_registry>`
  - ```{autodoc2-docstring} chartbook.identity.split_registry
    :summary:
    ```
* - {py:obj}`split_rev <chartbook.identity.split_rev>`
  - ```{autodoc2-docstring} chartbook.identity.split_rev
    :summary:
    ```
* - {py:obj}`strip_url_credentials <chartbook.identity.strip_url_credentials>`
  - ```{autodoc2-docstring} chartbook.identity.strip_url_credentials
    :summary:
    ```
* - {py:obj}`validate_pipeline_id <chartbook.identity.validate_pipeline_id>`
  - ```{autodoc2-docstring} chartbook.identity.validate_pipeline_id
    :summary:
    ```
* - {py:obj}`web_link <chartbook.identity.web_link>`
  - ```{autodoc2-docstring} chartbook.identity.web_link
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ID_COMPONENT_PATTERN <chartbook.identity.ID_COMPONENT_PATTERN>`
  - ```{autodoc2-docstring} chartbook.identity.ID_COMPONENT_PATTERN
    :summary:
    ```
* - {py:obj}`VERSION_FILE <chartbook.identity.VERSION_FILE>`
  - ```{autodoc2-docstring} chartbook.identity.VERSION_FILE
    :summary:
    ```
````

### API

`````{py:class} Checkout
:canonical: chartbook.identity.Checkout

```{autodoc2-docstring} chartbook.identity.Checkout
```

````{py:attribute} address
:canonical: chartbook.identity.Checkout.address
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.identity.Checkout.address
```

````

````{py:attribute} common_dir
:canonical: chartbook.identity.Checkout.common_dir
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.identity.Checkout.common_dir
```

````

````{py:attribute} first_commit
:canonical: chartbook.identity.Checkout.first_commit
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.identity.Checkout.first_commit
```

````

````{py:attribute} main
:canonical: chartbook.identity.Checkout.main
:type: bool
:value: >
   None

```{autodoc2-docstring} chartbook.identity.Checkout.main
```

````

````{py:attribute} subfolder
:canonical: chartbook.identity.Checkout.subfolder
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.identity.Checkout.subfolder
```

````

`````

````{py:data} ID_COMPONENT_PATTERN
:canonical: chartbook.identity.ID_COMPONENT_PATTERN
:value: >
   'compile(...)'

```{autodoc2-docstring} chartbook.identity.ID_COMPONENT_PATTERN
```

````

````{py:exception} UnsupportedRegistryError()
:canonical: chartbook.identity.UnsupportedRegistryError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.identity.UnsupportedRegistryError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.identity.UnsupportedRegistryError.__init__
```

````

````{py:exception} UnsupportedRevisionError()
:canonical: chartbook.identity.UnsupportedRevisionError

Bases: {py:obj}`ValueError`

```{autodoc2-docstring} chartbook.identity.UnsupportedRevisionError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.identity.UnsupportedRevisionError.__init__
```

````

````{py:data} VERSION_FILE
:canonical: chartbook.identity.VERSION_FILE
:value: >
   '.chartbook-version.json'

```{autodoc2-docstring} chartbook.identity.VERSION_FILE
```

````

````{py:function} checkout_of(folder: pathlib.Path | str) -> typing.Optional[chartbook.identity.Checkout]
:canonical: chartbook.identity.checkout_of

```{autodoc2-docstring} chartbook.identity.checkout_of
```
````

````{py:function} clear_git_remote_cache() -> None
:canonical: chartbook.identity.clear_git_remote_cache

```{autodoc2-docstring} chartbook.identity.clear_git_remote_cache
```
````

````{py:function} derive_pipeline_id(project: dict, base_dir: pathlib.Path | str) -> str
:canonical: chartbook.identity.derive_pipeline_id

```{autodoc2-docstring} chartbook.identity.derive_pipeline_id
```
````

````{py:function} get_git_remote_url(base_dir: pathlib.Path | str) -> typing.Optional[str]
:canonical: chartbook.identity.get_git_remote_url

```{autodoc2-docstring} chartbook.identity.get_git_remote_url
```
````

````{py:function} id_from_address(address: str) -> typing.Optional[str]
:canonical: chartbook.identity.id_from_address

```{autodoc2-docstring} chartbook.identity.id_from_address
```
````

````{py:function} in_another_case(keys: typing.Iterable[str], ref: str) -> typing.Optional[str]
:canonical: chartbook.identity.in_another_case

```{autodoc2-docstring} chartbook.identity.in_another_case
```
````

````{py:function} is_repository_top(base_dir: pathlib.Path | str) -> bool
:canonical: chartbook.identity.is_repository_top

```{autodoc2-docstring} chartbook.identity.is_repository_top
```
````

````{py:function} looks_like_registry(component: str) -> bool
:canonical: chartbook.identity.looks_like_registry

```{autodoc2-docstring} chartbook.identity.looks_like_registry
```
````

````{py:function} match_pipeline_ref(keys: typing.Iterable[str], ref: str, where: str = 'this catalog') -> typing.Optional[str]
:canonical: chartbook.identity.match_pipeline_ref

```{autodoc2-docstring} chartbook.identity.match_pipeline_ref
```
````

````{py:function} normalize_ref_to_id(ref: str) -> str
:canonical: chartbook.identity.normalize_ref_to_id

```{autodoc2-docstring} chartbook.identity.normalize_ref_to_id
```
````

````{py:function} plain_line(value: object, longest: int = 10000) -> str
:canonical: chartbook.identity.plain_line

```{autodoc2-docstring} chartbook.identity.plain_line
```
````

````{py:function} read_version_file(base_dir: pathlib.Path | str) -> dict
:canonical: chartbook.identity.read_version_file

```{autodoc2-docstring} chartbook.identity.read_version_file
```
````

````{py:function} remote_to_web_url(remote: typing.Optional[str]) -> str
:canonical: chartbook.identity.remote_to_web_url

```{autodoc2-docstring} chartbook.identity.remote_to_web_url
```
````

````{py:function} repository_key(address: typing.Optional[str]) -> str
:canonical: chartbook.identity.repository_key

```{autodoc2-docstring} chartbook.identity.repository_key
```
````

````{py:function} resolve_pipeline_ref(keys: typing.Iterable[str], ref: str) -> str
:canonical: chartbook.identity.resolve_pipeline_ref

```{autodoc2-docstring} chartbook.identity.resolve_pipeline_ref
```
````

````{py:function} same_pipeline_checked_out(first: typing.Optional[chartbook.identity.Checkout], second: typing.Optional[chartbook.identity.Checkout]) -> bool
:canonical: chartbook.identity.same_pipeline_checked_out

```{autodoc2-docstring} chartbook.identity.same_pipeline_checked_out
```
````

````{py:function} split_registry(pipeline_id: str) -> tuple[typing.Optional[str], str]
:canonical: chartbook.identity.split_registry

```{autodoc2-docstring} chartbook.identity.split_registry
```
````

````{py:function} split_rev(ref: str) -> tuple[str, typing.Optional[str]]
:canonical: chartbook.identity.split_rev

```{autodoc2-docstring} chartbook.identity.split_rev
```
````

````{py:function} strip_url_credentials(url: str) -> str
:canonical: chartbook.identity.strip_url_credentials

```{autodoc2-docstring} chartbook.identity.strip_url_credentials
```
````

````{py:function} validate_pipeline_id(pipeline_id: str) -> str
:canonical: chartbook.identity.validate_pipeline_id

```{autodoc2-docstring} chartbook.identity.validate_pipeline_id
```
````

````{py:function} web_link(value: object) -> str
:canonical: chartbook.identity.web_link

```{autodoc2-docstring} chartbook.identity.web_link
```
````
