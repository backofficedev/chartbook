"""Global configuration for chartbook.

Manages reading and writing ``~/.chartbook/settings.toml``, which stores
user-level defaults such as the path to a catalog's ``chartbook.toml``.

The global config directory (``~/.chartbook/``) has this structure::

    ~/.chartbook/
    ├── settings.toml        # user settings (catalog path override, etc.)
    ├── chartbook.toml       # default global catalog
    ├── artifacts/            # auxiliary files (e.g. cached data)
    ├── docs/                # rendered catalog HTML
    ├── store/               # pinned files, named by their hash
    └── git/                 # clones of git dependencies

Settings file format::

    [catalog]
    path = "/absolute/path/to/catalog/chartbook.toml"

    [store]
    path = "/a/bigger/disk/chartbook-store"

    [git]
    path = "/a/bigger/disk/chartbook-git"

The store (:mod:`chartbook.store`) is at ``~/.chartbook/store/`` unless
``[store] path`` or the ``CHARTBOOK_STORE`` environment variable says
otherwise. Git dependencies are fetched into ``~/.chartbook/git/``
(:mod:`chartbook.gitcache`) unless ``[git] path`` or ``CHARTBOOK_GIT_CACHE``
says otherwise.
"""

import os
from pathlib import Path
from typing import Optional

import tomli
import tomli_w

#: The environment variable that says where the store is, when it is set.
STORE_ENV_VAR = "CHARTBOOK_STORE"

#: The environment variable that says where git dependencies are fetched to.
GIT_CACHE_ENV_VAR = "CHARTBOOK_GIT_CACHE"


def get_global_config_dir() -> Path:
    """Return the global chartbook config directory.

    :returns: ``~/.chartbook`` (works on Windows, macOS, and Linux).
    :rtype: Path
    """
    return Path.home() / ".chartbook"


def get_global_catalog_path() -> Path:
    """Return the path to the default global catalog.

    :returns: ``~/.chartbook/chartbook.toml``
    :rtype: Path
    """
    return get_global_config_dir() / "chartbook.toml"


def get_global_artifacts_dir() -> Path:
    """Return the path to the global artifacts directory.

    :returns: ``~/.chartbook/artifacts/``
    :rtype: Path
    """
    return get_global_config_dir() / "artifacts"


def get_global_docs_dir() -> Path:
    """Return the path to the global rendered docs directory.

    :returns: ``~/.chartbook/docs/``
    :rtype: Path
    """
    return get_global_config_dir() / "docs"


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
    """Get the default catalog path.

    Resolution order:

    1. ``catalog.path`` from ``~/.chartbook/settings.toml`` (explicit override).
    2. ``~/.chartbook/chartbook.toml`` if it exists (global catalog).
    3. ``None`` if neither is available.

    :returns: The resolved catalog path, or ``None`` if not found.
    :rtype: Optional[Path]
    """
    settings = read_global_settings()
    try:
        raw = settings["catalog"]["path"]
        return Path(raw)
    except KeyError:
        pass

    # Fall back to the global catalog if it exists
    global_catalog = get_global_catalog_path()
    if global_catalog.is_file():
        return global_catalog

    return None


def get_store_path() -> Path:
    """Get the directory of the store: the local folder of pinned files.

    Resolution order:

    1. The ``CHARTBOOK_STORE`` environment variable, for one shell or one
       CI job.
    2. ``store.path`` from ``~/.chartbook/settings.toml``, for a bigger disk
       or a drive a team shares.
    3. ``~/.chartbook/store``.

    The directory need not exist yet.

    :returns: The absolute path of the store.
    :rtype: Path
    :raises ValueError: If ``store.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(STORE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_global_settings().get("store")
    if configured is not None:
        path = configured.get("path") if isinstance(configured, dict) else None
        if not isinstance(path, str) or not path.strip():
            raise ValueError(
                f"{get_global_settings_path()}: [store] needs a 'path', e.g. "
                f'path = "/a/bigger/disk/chartbook-store".'
            )
        return Path(os.path.abspath(Path(path).expanduser()))

    return get_global_config_dir() / "store"


def get_git_cache_path() -> Path:
    """Get the directory that ``git`` dependencies are fetched into.

    Resolution order:

    1. The ``CHARTBOOK_GIT_CACHE`` environment variable.
    2. ``git.path`` from ``~/.chartbook/settings.toml``.
    3. ``~/.chartbook/git``.

    The directory need not exist yet.

    :returns: The absolute path of the cache.
    :rtype: Path
    :raises ValueError: If ``git.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(GIT_CACHE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_global_settings().get("git")
    if configured is not None:
        path = configured.get("path") if isinstance(configured, dict) else None
        if not isinstance(path, str) or not path.strip():
            raise ValueError(
                f"{get_global_settings_path()}: [git] needs a 'path', e.g. "
                f'path = "/a/bigger/disk/chartbook-git".'
            )
        return Path(os.path.abspath(Path(path).expanduser()))

    return get_global_config_dir() / "git"


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
    from chartbook.manifest import V1FormatError, detect_v1_format, resolve_project_type

    with open(catalog_path, "rb") as f:
        manifest = tomli.load(f)

    if detect_v1_format(manifest):
        raise V1FormatError(catalog_path)

    config_type = resolve_project_type(manifest, source=str(catalog_path))
    if config_type != "catalog":
        raise ValueError(
            f"Expected a catalog-type chartbook.toml, but found type={config_type!r}. "
            f"The config command requires a catalog project, not a pipeline."
        )

    settings = read_global_settings()
    settings.setdefault("catalog", {})
    settings["catalog"]["path"] = str(catalog_path)
    write_global_settings(settings)


def create_global_catalog(title: str = "My Catalog", author: str = "") -> Path:
    """Create a minimal global catalog at ``~/.chartbook/chartbook.toml``.

    Also creates the ``~/.chartbook/artifacts/`` directory.

    :param title: Site title for the catalog.
    :type title: str
    :param author: Author name for the catalog.
    :type author: str
    :returns: Path to the created ``chartbook.toml``.
    :rtype: Path
    :raises FileExistsError: If ``~/.chartbook/chartbook.toml`` already exists.
    """
    config_dir = get_global_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    get_global_artifacts_dir().mkdir(exist_ok=True)

    catalog_path = get_global_catalog_path()
    if catalog_path.is_file():
        raise FileExistsError(f"Global catalog already exists: {catalog_path}")

    catalog = {
        "project": {
            "type": "catalog",
            "name": title,
            "maintainer": author,
        },
        "pipelines": {},
    }

    with open(catalog_path, "wb") as f:
        tomli_w.dump(catalog, f)

    return catalog_path
