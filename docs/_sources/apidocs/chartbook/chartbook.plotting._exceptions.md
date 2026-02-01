---
orphan: true
---

# {py:mod}`chartbook.plotting._exceptions`

```{py:module} chartbook.plotting._exceptions
```

```{autodoc2-docstring} chartbook.plotting._exceptions
:allowtitles:
```

## Module Contents

### API

````{py:exception} BackendError(backend: str, message: str)
:canonical: chartbook.plotting._exceptions.BackendError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.BackendError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.BackendError.__init__
```

````

````{py:exception} ConfigurationError()
:canonical: chartbook.plotting._exceptions.ConfigurationError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.ConfigurationError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.ConfigurationError.__init__
```

````

````{py:exception} DataValidationError(column: str | None, message: str)
:canonical: chartbook.plotting._exceptions.DataValidationError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.DataValidationError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.DataValidationError.__init__
```

````

````{py:exception} FREDAPIError(message: str)
:canonical: chartbook.plotting._exceptions.FREDAPIError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.FREDAPIError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.FREDAPIError.__init__
```

````

````{py:exception} MissingDependencyError(package: str, feature: str)
:canonical: chartbook.plotting._exceptions.MissingDependencyError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.MissingDependencyError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.MissingDependencyError.__init__
```

````

````{py:exception} OutputError(path: str, message: str)
:canonical: chartbook.plotting._exceptions.OutputError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.OutputError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.OutputError.__init__
```

````

````{py:exception} OverlayError()
:canonical: chartbook.plotting._exceptions.OverlayError

Bases: {py:obj}`chartbook.plotting._exceptions.PlottingError`

```{autodoc2-docstring} chartbook.plotting._exceptions.OverlayError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.OverlayError.__init__
```

````

````{py:exception} PlottingError()
:canonical: chartbook.plotting._exceptions.PlottingError

Bases: {py:obj}`Exception`

```{autodoc2-docstring} chartbook.plotting._exceptions.PlottingError
```

```{rubric} Initialization
```

```{autodoc2-docstring} chartbook.plotting._exceptions.PlottingError.__init__
```

````
