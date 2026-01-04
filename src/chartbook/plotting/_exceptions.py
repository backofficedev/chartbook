"""Custom exceptions for chartbook.plotting."""

from __future__ import annotations


class PlottingError(Exception):
    """Base exception for chartbook.plotting errors."""

    pass


class BackendError(PlottingError):
    """Error related to plotting backend."""

    def __init__(self, backend: str, message: str):
        self.backend = backend
        super().__init__(f"Backend '{backend}': {message}")


class MissingDependencyError(PlottingError):
    """Required plotting library not installed."""

    def __init__(self, package: str, feature: str):
        self.package = package
        self.feature = feature
        super().__init__(
            f"'{package}' is required for {feature}. "
            f"Install with: pip install chartbook[plotting]"
        )


class DataValidationError(PlottingError):
    """Error validating input data."""

    def __init__(self, column: str | None, message: str):
        self.column = column
        if column:
            super().__init__(f"Column '{column}': {message}")
        else:
            super().__init__(message)


class OutputError(PlottingError):
    """Error saving chart output."""

    def __init__(self, path: str, message: str):
        self.path = path
        super().__init__(f"Cannot save to '{path}': {message}")


class ConfigurationError(PlottingError):
    """Error in plotting configuration."""

    pass


class OverlayError(PlottingError):
    """Error applying chart overlays."""

    pass


class FREDAPIError(PlottingError):
    """Error fetching data from FRED API."""

    def __init__(self, message: str):
        super().__init__(f"FRED API error: {message}")
