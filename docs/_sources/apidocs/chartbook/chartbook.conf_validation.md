# {py:mod}`chartbook.conf_validation`

```{py:module} chartbook.conf_validation
```

```{autodoc2-docstring} chartbook.conf_validation
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SiteConfig <chartbook.conf_validation.SiteConfig>`
  - ```{autodoc2-docstring} chartbook.conf_validation.SiteConfig
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`validate_conf_py_values <chartbook.conf_validation.validate_conf_py_values>`
  - ```{autodoc2-docstring} chartbook.conf_validation.validate_conf_py_values
    :summary:
    ```
* - {py:obj}`validate_source_files <chartbook.conf_validation.validate_source_files>`
  - ```{autodoc2-docstring} chartbook.conf_validation.validate_source_files
    :summary:
    ```
````

### API

`````{py:class} SiteConfig
:canonical: chartbook.conf_validation.SiteConfig

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig
```

````{py:attribute} ALLOWED_THEMES
:canonical: chartbook.conf_validation.SiteConfig.ALLOWED_THEMES
:type: typing.ClassVar[frozenset[str]]
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.ALLOWED_THEMES
```

````

````{py:attribute} MAX_TEXT_LENGTH
:canonical: chartbook.conf_validation.SiteConfig.MAX_TEXT_LENGTH
:type: typing.ClassVar[int]
:value: >
   200

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.MAX_TEXT_LENGTH
```

````

````{py:attribute} SAFE_TEXT_PATTERN
:canonical: chartbook.conf_validation.SiteConfig.SAFE_TEXT_PATTERN
:type: typing.ClassVar[re.Pattern]
:value: >
   'compile(...)'

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.SAFE_TEXT_PATTERN
```

````

````{py:attribute} TOML_KEYS
:canonical: chartbook.conf_validation.SiteConfig.TOML_KEYS
:type: typing.ClassVar[dict[str, str]]
:value: >
   None

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.TOML_KEYS
```

````

````{py:attribute} author
:canonical: chartbook.conf_validation.SiteConfig.author
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.author
```

````

````{py:attribute} copyright
:canonical: chartbook.conf_validation.SiteConfig.copyright
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.copyright
```

````

````{py:method} from_manifest(manifest: dict, pipeline_theme: str) -> chartbook.conf_validation.SiteConfig
:canonical: chartbook.conf_validation.SiteConfig.from_manifest
:classmethod:

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.from_manifest
```

````

````{py:attribute} sphinx_theme
:canonical: chartbook.conf_validation.SiteConfig.sphinx_theme
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.sphinx_theme
```

````

````{py:attribute} title
:canonical: chartbook.conf_validation.SiteConfig.title
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.conf_validation.SiteConfig.title
```

````

`````

````{py:function} validate_conf_py_values(manifest: dict, pipeline_theme: str) -> chartbook.conf_validation.SiteConfig
:canonical: chartbook.conf_validation.validate_conf_py_values

```{autodoc2-docstring} chartbook.conf_validation.validate_conf_py_values
```
````

````{py:function} validate_source_files(manifest: dict, base_dir) -> list
:canonical: chartbook.conf_validation.validate_source_files

```{autodoc2-docstring} chartbook.conf_validation.validate_source_files
```
````
