"""Backend loading and plugin management for chartbook.plotting."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pluggy

from chartbook.plotting.backends._base import BaseBackend, PlottingBackend
from chartbook.plotting.backends._hookspecs import PlottingHookSpec, hookimpl

if TYPE_CHECKING:
    pass

__all__ = [
    "PlottingBackend",
    "BaseBackend",
    "hookimpl",
    "get_backend",
    "register_backend",
    "get_plugin_manager",
]

# Plugin manager singleton
_pm: pluggy.PluginManager | None = None


def get_plugin_manager() -> pluggy.PluginManager:
    """Get or create the plugin manager."""
    global _pm
    if _pm is None:
        _pm = pluggy.PluginManager("chartbook_plotting")
        _pm.add_hookspecs(PlottingHookSpec)

        # Register built-in backends
        from chartbook.plotting.backends._matplotlib import MatplotlibBackend
        from chartbook.plotting.backends._plotly import PlotlyBackend

        _pm.register(PlotlyBackend(), name="plotly")
        _pm.register(MatplotlibBackend(), name="matplotlib")

        # Load external plugins via entry points
        _pm.load_setuptools_entrypoints("chartbook_plotting")

    return _pm


def get_backend(name: str = "plotly") -> PlottingBackend:
    """Get a plotting backend by name.

    Parameters
    ----------
    name : str
        Backend name. Options: "plotly", "matplotlib", or any registered
        plugin name.

    Returns
    -------
    PlottingBackend
        The requested backend implementation.

    Raises
    ------
    ValueError
        If the backend name is not found.
    """
    pm = get_plugin_manager()

    # Find registered backend by name
    for plugin_name in pm.list_name_plugin():
        plugin = pm.get_plugin(plugin_name[0])
        if plugin and hasattr(plugin, "name") and plugin.name == name:
            return plugin

    # Also check the plugin name itself
    plugin = pm.get_plugin(name)
    if plugin:
        return plugin

    available = [p.name for p in pm.get_plugins() if hasattr(p, "name")]
    raise ValueError(f"Unknown backend: {name}. Available: {available}")


def register_backend(backend: PlottingBackend, name: str | None = None) -> None:
    """Register a custom plotting backend.

    Parameters
    ----------
    backend : PlottingBackend
        Backend instance to register.
    name : str, optional
        Name for the backend. If not provided, uses backend.name.

    Examples
    --------
    Third-party packages can also register via entry points:

        [project.entry-points.chartbook_plotting]
        my_backend = "mypackage.backend:MyBackend"
    """
    pm = get_plugin_manager()
    backend_name = name or backend.name
    pm.register(backend, name=backend_name)


def list_backends() -> list[str]:
    """List all available backend names.

    Returns
    -------
    list[str]
        Names of all registered backends.
    """
    pm = get_plugin_manager()
    return [p.name for p in pm.get_plugins() if hasattr(p, "name")]
