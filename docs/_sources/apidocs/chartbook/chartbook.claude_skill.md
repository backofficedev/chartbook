# {py:mod}`chartbook.claude_skill`

```{py:module} chartbook.claude_skill
```

```{autodoc2-docstring} chartbook.claude_skill
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Copy <chartbook.claude_skill.Copy>`
  - ```{autodoc2-docstring} chartbook.claude_skill.Copy
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`bundled_dir <chartbook.claude_skill.bundled_dir>`
  - ```{autodoc2-docstring} chartbook.claude_skill.bundled_dir
    :summary:
    ```
* - {py:obj}`bundled_files <chartbook.claude_skill.bundled_files>`
  - ```{autodoc2-docstring} chartbook.claude_skill.bundled_files
    :summary:
    ```
* - {py:obj}`front_matter_version <chartbook.claude_skill.front_matter_version>`
  - ```{autodoc2-docstring} chartbook.claude_skill.front_matter_version
    :summary:
    ```
* - {py:obj}`notice <chartbook.claude_skill.notice>`
  - ```{autodoc2-docstring} chartbook.claude_skill.notice
    :summary:
    ```
* - {py:obj}`project_dir <chartbook.claude_skill.project_dir>`
  - ```{autodoc2-docstring} chartbook.claude_skill.project_dir
    :summary:
    ```
* - {py:obj}`relation <chartbook.claude_skill.relation>`
  - ```{autodoc2-docstring} chartbook.claude_skill.relation
    :summary:
    ```
* - {py:obj}`shown <chartbook.claude_skill.shown>`
  - ```{autodoc2-docstring} chartbook.claude_skill.shown
    :summary:
    ```
* - {py:obj}`stale <chartbook.claude_skill.stale>`
  - ```{autodoc2-docstring} chartbook.claude_skill.stale
    :summary:
    ```
* - {py:obj}`user_dir <chartbook.claude_skill.user_dir>`
  - ```{autodoc2-docstring} chartbook.claude_skill.user_dir
    :summary:
    ```
* - {py:obj}`version_of <chartbook.claude_skill.version_of>`
  - ```{autodoc2-docstring} chartbook.claude_skill.version_of
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ENTRY <chartbook.claude_skill.ENTRY>`
  - ```{autodoc2-docstring} chartbook.claude_skill.ENTRY
    :summary:
    ```
* - {py:obj}`OLD_STAMP <chartbook.claude_skill.OLD_STAMP>`
  - ```{autodoc2-docstring} chartbook.claude_skill.OLD_STAMP
    :summary:
    ```
* - {py:obj}`SKILL_NAME <chartbook.claude_skill.SKILL_NAME>`
  - ```{autodoc2-docstring} chartbook.claude_skill.SKILL_NAME
    :summary:
    ```
````

### API

`````{py:class} Copy
:canonical: chartbook.claude_skill.Copy

```{autodoc2-docstring} chartbook.claude_skill.Copy
```

````{py:attribute} directory
:canonical: chartbook.claude_skill.Copy.directory
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} chartbook.claude_skill.Copy.directory
```

````

````{py:attribute} version
:canonical: chartbook.claude_skill.Copy.version
:type: typing.Optional[str]
:value: >
   None

```{autodoc2-docstring} chartbook.claude_skill.Copy.version
```

````

````{py:attribute} where
:canonical: chartbook.claude_skill.Copy.where
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.claude_skill.Copy.where
```

````

`````

````{py:data} ENTRY
:canonical: chartbook.claude_skill.ENTRY
:value: >
   'SKILL.md'

```{autodoc2-docstring} chartbook.claude_skill.ENTRY
```

````

````{py:data} OLD_STAMP
:canonical: chartbook.claude_skill.OLD_STAMP
:value: >
   '.chartbook-skill-version'

```{autodoc2-docstring} chartbook.claude_skill.OLD_STAMP
```

````

````{py:data} SKILL_NAME
:canonical: chartbook.claude_skill.SKILL_NAME
:value: >
   'chartbook'

```{autodoc2-docstring} chartbook.claude_skill.SKILL_NAME
```

````

````{py:function} bundled_dir() -> pathlib.Path
:canonical: chartbook.claude_skill.bundled_dir

```{autodoc2-docstring} chartbook.claude_skill.bundled_dir
```
````

````{py:function} bundled_files() -> list[pathlib.Path]
:canonical: chartbook.claude_skill.bundled_files

```{autodoc2-docstring} chartbook.claude_skill.bundled_files
```
````

````{py:function} front_matter_version(directory: pathlib.Path) -> typing.Optional[str]
:canonical: chartbook.claude_skill.front_matter_version

```{autodoc2-docstring} chartbook.claude_skill.front_matter_version
```
````

````{py:function} notice(copy: chartbook.claude_skill.Copy) -> str
:canonical: chartbook.claude_skill.notice

```{autodoc2-docstring} chartbook.claude_skill.notice
```
````

````{py:function} project_dir(start: typing.Optional[pathlib.Path | str] = None) -> typing.Optional[pathlib.Path]
:canonical: chartbook.claude_skill.project_dir

```{autodoc2-docstring} chartbook.claude_skill.project_dir
```
````

````{py:function} relation(directory: pathlib.Path) -> str
:canonical: chartbook.claude_skill.relation

```{autodoc2-docstring} chartbook.claude_skill.relation
```
````

````{py:function} shown(path: pathlib.Path) -> str
:canonical: chartbook.claude_skill.shown

```{autodoc2-docstring} chartbook.claude_skill.shown
```
````

````{py:function} stale(start: typing.Optional[pathlib.Path | str] = None) -> list[chartbook.claude_skill.Copy]
:canonical: chartbook.claude_skill.stale

```{autodoc2-docstring} chartbook.claude_skill.stale
```
````

````{py:function} user_dir() -> pathlib.Path
:canonical: chartbook.claude_skill.user_dir

```{autodoc2-docstring} chartbook.claude_skill.user_dir
```
````

````{py:function} version_of(directory: pathlib.Path) -> typing.Optional[str]
:canonical: chartbook.claude_skill.version_of

```{autodoc2-docstring} chartbook.claude_skill.version_of
```
````
