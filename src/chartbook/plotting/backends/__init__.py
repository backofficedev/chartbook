"""Backend loading and registration for chartbook.plotting.

A backend is any object satisfying the ``PlottingBackend`` protocol: a
``name`` and the ``create_*`` methods. Backends are called directly, by
method. They are kept in a pluggy plugin manager, which serves here as a
registry and as the loader for the ``chartbook_plotting`` entry-point group
and nothing more. The interface is documented for third-party authors in
``docs_src/guide/plotting-backends.md``.
"""

from __future__ import annotations

import warnings

import pluggy

from chartbook.plotting.backends._base import BaseBackend, PlottingBackend

__all__ = [
    "PlottingBackend",
    "BaseBackend",
    "get_backend",
    "list_backends",
    "register_backend",
    "get_plugin_manager",
]

#: The entry-point group third-party backends register under.
ENTRY_POINT_GROUP = "chartbook_plotting"

# Plugin manager singleton
_pm: pluggy.PluginManager | None = None


def _as_backend(candidate, source: str) -> PlottingBackend:
    """Turn what was registered into a usable backend, or say why it is not one.

    A class is instantiated, so an entry point may name either a backend
    class or an instance of one.

    :param candidate: The object registered or loaded from an entry point.
    :param source: Where it came from, for the error message.
    :raises TypeError: If it cannot be used as a backend.
    """
    if isinstance(candidate, type):
        try:
            candidate = candidate()
        except Exception as error:
            raise TypeError(
                f"{source} is the class {candidate.__name__}, which could not "
                f"be instantiated with no arguments: {error}"
            ) from error
    if not isinstance(candidate, PlottingBackend):
        raise TypeError(
            f"{source} is not a plotting backend. A backend needs a 'name' and "
            f"the methods create_line, create_bar, create_scatter, create_pie, "
            f"create_area and create_dual_axis; subclass "
            f"chartbook.plotting.backends.BaseBackend to get the shape right."
        )
    return candidate


def get_plugin_manager() -> pluggy.PluginManager:
    """Get or create the plugin manager."""
    global _pm
    if _pm is None:
        pm = pluggy.PluginManager(ENTRY_POINT_GROUP)

        # Register built-in backends
        from chartbook.plotting.backends._matplotlib import MatplotlibBackend
        from chartbook.plotting.backends._plotly import PlotlyBackend

        pm.register(PlotlyBackend(), name="plotly")
        pm.register(MatplotlibBackend(), name="matplotlib")

        # Load external plugins via entry points. pluggy registers whatever
        # each entry point resolves to, so a class is swapped for an instance
        pm.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
        for name, plugin in pm.list_name_plugin():
            if plugin is None:
                continue
            try:
                backend = _as_backend(
                    plugin, f"The '{name}' {ENTRY_POINT_GROUP} entry point"
                )
            except TypeError as error:
                # One broken third-party package must not take the built-in
                # backends down with it
                warnings.warn(f"{error} It is being ignored.", UserWarning, stacklevel=2)
                pm.unregister(name=name)
                continue
            if backend is not plugin:
                pm.unregister(name=name)
                pm.register(backend, name=name)
        _pm = pm

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

    # Find registered backend by its own name
    for _, plugin in pm.list_name_plugin():
        if getattr(plugin, "name", None) == name:
            return plugin

    # Also check the name it was registered under
    plugin = pm.get_plugin(name)
    if plugin:
        return plugin

    raise ValueError(f"Unknown backend: {name}. Available: {list_backends()}")


def register_backend(backend, name: str | None = None) -> None:
    """Register a custom plotting backend.

    Parameters
    ----------
    backend : PlottingBackend or type
        A backend instance, or a backend class to instantiate.
    name : str, optional
        Name for the backend. If not provided, uses backend.name.

    Raises
    ------
    TypeError
        If the object is not a usable backend.

    Examples
    --------
    Third-party packages can also register via entry points, naming either
    a backend class or an instance:

        [project.entry-points.chartbook_plotting]
        my_backend = "mypackage.backend:MyBackend"
    """
    pm = get_plugin_manager()
    backend = _as_backend(backend, "The object passed to register_backend")
    pm.register(backend, name=name or backend.name)


def list_backends() -> list[str]:
    """List all available backend names.

    Returns
    -------
    list[str]
        Names of all registered backends, sorted.
    """
    pm = get_plugin_manager()
    return sorted(plugin.name for _, plugin in pm.list_name_plugin())
