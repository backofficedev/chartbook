# {py:mod}`chartbook.validation`

```{py:module} chartbook.validation
```

```{autodoc2-docstring} chartbook.validation
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SiteConfig <chartbook.validation.SiteConfig>`
  - ```{autodoc2-docstring} chartbook.validation.SiteConfig
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`validate_conf_py_values <chartbook.validation.validate_conf_py_values>`
  - ```{autodoc2-docstring} chartbook.validation.validate_conf_py_values
    :summary:
    ```
````

### API

`````{py:class} SiteConfig
:canonical: chartbook.validation.SiteConfig

```{autodoc2-docstring} chartbook.validation.SiteConfig
```

````{py:attribute} ALLOWED_THEMES
:canonical: chartbook.validation.SiteConfig.ALLOWED_THEMES
:type: typing.ClassVar[frozenset[str]]
:value: >
   'frozenset(...)'

```{autodoc2-docstring} chartbook.validation.SiteConfig.ALLOWED_THEMES
```

````

````{py:attribute} MAX_TEXT_LENGTH
:canonical: chartbook.validation.SiteConfig.MAX_TEXT_LENGTH
:type: typing.ClassVar[int]
:value: >
   200

```{autodoc2-docstring} chartbook.validation.SiteConfig.MAX_TEXT_LENGTH
```

````

````{py:attribute} SAFE_TEXT_PATTERN
:canonical: chartbook.validation.SiteConfig.SAFE_TEXT_PATTERN
:type: typing.ClassVar[re.Pattern]
:value: >
   'compile(...)'

```{autodoc2-docstring} chartbook.validation.SiteConfig.SAFE_TEXT_PATTERN
```

````

````{py:attribute} author
:canonical: chartbook.validation.SiteConfig.author
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.validation.SiteConfig.author
```

````

````{py:attribute} copyright
:canonical: chartbook.validation.SiteConfig.copyright
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.validation.SiteConfig.copyright
```

````

````{py:method} from_manifest(manifest: dict, pipeline_theme: str) -> chartbook.validation.SiteConfig
:canonical: chartbook.validation.SiteConfig.from_manifest
:classmethod:

```{autodoc2-docstring} chartbook.validation.SiteConfig.from_manifest
```

````

````{py:attribute} sphinx_theme
:canonical: chartbook.validation.SiteConfig.sphinx_theme
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.validation.SiteConfig.sphinx_theme
```

````

````{py:attribute} title
:canonical: chartbook.validation.SiteConfig.title
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.validation.SiteConfig.title
```

````

`````

````{py:function} validate_conf_py_values(manifest: dict, pipeline_theme: str) -> chartbook.validation.SiteConfig
:canonical: chartbook.validation.validate_conf_py_values

```{autodoc2-docstring} chartbook.validation.validate_conf_py_values
```
````
