# {py:mod}`chartbook.path_validation`

```{py:module} chartbook.path_validation
```

```{autodoc2-docstring} chartbook.path_validation
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PathDiagnostic <chartbook.path_validation.PathDiagnostic>`
  - ```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic
    :summary:
    ```
* - {py:obj}`ShellEnvironment <chartbook.path_validation.ShellEnvironment>`
  - ```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`check_toml_path <chartbook.path_validation.check_toml_path>`
  - ```{autodoc2-docstring} chartbook.path_validation.check_toml_path
    :summary:
    ```
* - {py:obj}`detect_shell_environment <chartbook.path_validation.detect_shell_environment>`
  - ```{autodoc2-docstring} chartbook.path_validation.detect_shell_environment
    :summary:
    ```
* - {py:obj}`diagnose_path <chartbook.path_validation.diagnose_path>`
  - ```{autodoc2-docstring} chartbook.path_validation.diagnose_path
    :summary:
    ```
* - {py:obj}`suggest_posix_path <chartbook.path_validation.suggest_posix_path>`
  - ```{autodoc2-docstring} chartbook.path_validation.suggest_posix_path
    :summary:
    ```
* - {py:obj}`validate_cli_paths <chartbook.path_validation.validate_cli_paths>`
  - ```{autodoc2-docstring} chartbook.path_validation.validate_cli_paths
    :summary:
    ```
````

### API

`````{py:class} PathDiagnostic
:canonical: chartbook.path_validation.PathDiagnostic

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic
```

````{py:attribute} hint
:canonical: chartbook.path_validation.PathDiagnostic.hint
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic.hint
```

````

````{py:attribute} level
:canonical: chartbook.path_validation.PathDiagnostic.level
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic.level
```

````

````{py:attribute} message
:canonical: chartbook.path_validation.PathDiagnostic.message
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic.message
```

````

````{py:attribute} original_path
:canonical: chartbook.path_validation.PathDiagnostic.original_path
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic.original_path
```

````

````{py:attribute} suggested_path
:canonical: chartbook.path_validation.PathDiagnostic.suggested_path
:type: str | None
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.PathDiagnostic.suggested_path
```

````

`````

`````{py:class} ShellEnvironment
:canonical: chartbook.path_validation.ShellEnvironment

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment
```

````{py:attribute} is_cygwin
:canonical: chartbook.path_validation.ShellEnvironment.is_cygwin
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.is_cygwin
```

````

````{py:attribute} is_mingw
:canonical: chartbook.path_validation.ShellEnvironment.is_mingw
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.is_mingw
```

````

````{py:property} is_posix_on_windows
:canonical: chartbook.path_validation.ShellEnvironment.is_posix_on_windows
:type: bool

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.is_posix_on_windows
```

````

````{py:attribute} is_wsl
:canonical: chartbook.path_validation.ShellEnvironment.is_wsl
:type: bool
:value: >
   False

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.is_wsl
```

````

````{py:attribute} msystem
:canonical: chartbook.path_validation.ShellEnvironment.msystem
:type: str
:value: <Multiline-String>

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.msystem
```

````

````{py:attribute} os_name
:canonical: chartbook.path_validation.ShellEnvironment.os_name
:type: str
:value: >
   None

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.os_name
```

````

````{py:property} shell_label
:canonical: chartbook.path_validation.ShellEnvironment.shell_label
:type: str

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.shell_label
```

````

````{py:property} shell_style
:canonical: chartbook.path_validation.ShellEnvironment.shell_style
:type: str

```{autodoc2-docstring} chartbook.path_validation.ShellEnvironment.shell_style
```

````

`````

````{py:function} check_toml_path(raw_path: str, env: chartbook.path_validation.ShellEnvironment, field_name: str, file_path: str) -> list[chartbook.path_validation.PathDiagnostic]
:canonical: chartbook.path_validation.check_toml_path

```{autodoc2-docstring} chartbook.path_validation.check_toml_path
```
````

````{py:function} detect_shell_environment() -> chartbook.path_validation.ShellEnvironment
:canonical: chartbook.path_validation.detect_shell_environment

```{autodoc2-docstring} chartbook.path_validation.detect_shell_environment
```
````

````{py:function} diagnose_path(raw_path: str, env: chartbook.path_validation.ShellEnvironment) -> list[chartbook.path_validation.PathDiagnostic]
:canonical: chartbook.path_validation.diagnose_path

```{autodoc2-docstring} chartbook.path_validation.diagnose_path
```
````

````{py:function} suggest_posix_path(windows_path: str, env: chartbook.path_validation.ShellEnvironment) -> str | None
:canonical: chartbook.path_validation.suggest_posix_path

```{autodoc2-docstring} chartbook.path_validation.suggest_posix_path
```
````

````{py:function} validate_cli_paths(paths: tuple[str, ...] | list[str], env: chartbook.path_validation.ShellEnvironment, auto_confirm: bool = False) -> list[str]
:canonical: chartbook.path_validation.validate_cli_paths

```{autodoc2-docstring} chartbook.path_validation.validate_cli_paths
```
````
