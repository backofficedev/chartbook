"""Global configuration for chartbook.

Manages reading and writing ``~/.chartbook/settings.toml``, which stores
user-level defaults such as the path to a catalog's ``chartbook.toml``.

Settings file format::

    [catalog]
    path = "/absolute/path/to/catalog/chartbook.toml"
"""

from pathlib import Path
from typing import Optional

import tomli
import tomli_w


def get_global_config_dir() -> Path:
    """Return the global chartbook config directory.

    :returns: ``~/.chartbook`` (works on Windows, macOS, and Linux).
    :rtype: Path
    """
    return Path.home() / ".chartbook"


def get_global_settings_path() -> Path:
    """Return the path to the global settings file.

    :returns: ``~/.chartbook/settings.toml``
    :rtype: Path
    """
    return get_global_config_dir() / "settings.toml"


def read_global_settings() -> dict:
    """Read the global settings file.

    :returns: The parsed settings dictionary, or ``{}`` if the file does not exist.
    :rtype: dict
    """
    settings_path = get_global_settings_path()
    if not settings_path.is_file():
        return {}
    with open(settings_path, "rb") as f:
        return tomli.load(f)


def get_default_catalog_path() -> Optional[Path]:
    """Get the default catalog path from global settings.

    :returns: The configured catalog path, or ``None`` if not set.
    :rtype: Optional[Path]
    """
    settings = read_global_settings()
    try:
        raw = settings["catalog"]["path"]
    except KeyError:
        return None
    return Path(raw)


def write_global_settings(settings: dict) -> None:
    """Write settings to the global settings file.

    Creates the ``~/.chartbook/`` directory if it does not exist.

    :param settings: The settings dictionary to write.
    :type settings: dict
    """
    config_dir = get_global_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(get_global_settings_path(), "wb") as f:
        tomli_w.dump(settings, f)


def set_default_catalog_path(catalog_path: Path) -> None:
    """Set the default catalog path in global settings.

    Validates that *catalog_path* points to an existing catalog-type
    ``chartbook.toml``.  If a directory is given, ``chartbook.toml`` is
    appended automatically.

    :param catalog_path: Path to the catalog's ``chartbook.toml`` or its parent directory.
    :type catalog_path: Path
    :raises FileNotFoundError: If the resolved path does not exist.
    :raises ValueError: If the file is not a catalog-type ``chartbook.toml``.
    """
    catalog_path = Path(catalog_path).resolve()

    # If a directory is given, append chartbook.toml
    if catalog_path.is_dir():
        catalog_path = catalog_path / "chartbook.toml"

    if not catalog_path.is_file():
        raise FileNotFoundError(f"File not found: {catalog_path}")

    # Validate that it is a catalog-type manifest
    with open(catalog_path, "rb") as f:
        manifest = tomli.load(f)

    config_type = manifest.get("config", {}).get("type")
    if config_type != "catalog":
        raise ValueError(
            f"Expected a catalog-type chartbook.toml, but found type={config_type!r}. "
            f"The config command requires a catalog project, not a pipeline."
        )

    settings = read_global_settings()
    settings.setdefault("catalog", {})
    settings["catalog"]["path"] = str(catalog_path)
    write_global_settings(settings)
