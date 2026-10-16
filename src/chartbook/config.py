"""Settings: where this machine keeps things, read in layers.

Three files, and the environment above them:

- the user's ``~/.chartbook/settings.toml``;
- the organization's system-wide file, ``/etc/chartbook/settings.toml``
  on Unix and macOS, ``%ProgramData%\\chartbook\\settings.toml`` on Windows,
  or the file ``CHARTBOOK_SYSTEM_SETTINGS`` names;
- the defaults under ``~/.chartbook``.

Each layer is consulted only where the one above it is silent, key by
key, so an organization sets the store once for every machine and a user
keeps their own choices for everything else::

    ~/.chartbook/
    ├── chartbook.toml       # the global catalog (optional)
    ├── settings.toml        # the user's settings
    ├── sources.toml         # the machine's urls and credentials for [sources]
    ├── store/               # the store, unless settings say otherwise
    ├── cache/               # what was read from a remote store
    └── git/                 # clones of git dependencies

``[store] url`` says where the store is: a folder (a bare path or
``file:///``), an S3 bucket (``s3://bucket/prefix``, with
``pip install chartbook[s3]``), or another kind of store a plugin provides,
by its scheme. ``CHARTBOOK_STORE`` overrides it. ``[git] path`` and
``CHARTBOOK_GIT_CACHE`` do the same for the git cache, ``[cache] path`` and
``CHARTBOOK_CACHE`` for the cache of a remote store; ``[catalog] path``
names the default catalog. Which store a machine uses is never a fact
about a pipeline, so none of this is in a ``chartbook.toml``.
"""

import os
import re
import warnings
from pathlib import Path
from typing import Optional

import tomli
import tomli_w

#: The environment variable that says where the store is, when it is set.
STORE_ENV_VAR = "CHARTBOOK_STORE"
#: Names the organization's settings file, read where the user's is silent.
SYSTEM_SETTINGS_ENV_VAR = "CHARTBOOK_SYSTEM_SETTINGS"

#: The environment variable that says where git dependencies are fetched to.
GIT_CACHE_ENV_VAR = "CHARTBOOK_GIT_CACHE"
#: The environment variable that says where a remote store's objects are kept once read.
CACHE_ENV_VAR = "CHARTBOOK_CACHE"


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
    """Read the user's settings file, ``~/.chartbook/settings.toml``.

    :returns: The parsed settings dictionary, or ``{}`` if the file does not exist.
    :rtype: dict
    """
    return _read_toml(get_global_settings_path(), "the user's settings")


def get_system_settings_path() -> Path:
    """The organization's settings file, which every user on the machine shares.

    ``CHARTBOOK_SYSTEM_SETTINGS`` if it is set; otherwise
    ``/etc/chartbook/settings.toml`` on Unix and macOS, and
    ``%ProgramData%\\chartbook\\settings.toml`` on Windows.
    """
    named = os.environ.get(SYSTEM_SETTINGS_ENV_VAR, "").strip()
    if named:
        return Path(named).expanduser()
    if os.name == "nt":
        base = os.environ.get("ProgramData") or r"C:\ProgramData"
        return Path(base) / "chartbook" / "settings.toml"
    return Path("/etc/chartbook/settings.toml")


def read_system_settings() -> dict:
    """Read the organization's settings file, or ``{}`` if there is none.

    A file that is named and not there, or that cannot be read or parsed,
    is reported with a warning and treated as absent: a fault in the
    organization's file must not stop every command on the machine.
    """
    path = get_system_settings_path()
    named = bool(os.environ.get(SYSTEM_SETTINGS_ENV_VAR, "").strip())
    try:
        return _read_toml(path, "the organization's settings", required=named)
    except ValueError as error:
        warnings.warn(f"{error} It is ignored.", stacklevel=2)
        return {}


def read_settings() -> dict:
    """The settings in force: the user's over the organization's, key by key.

    Each layer is consulted only where the one above it is silent. Within
    a table such as ``[store]``, the user's keys are added to the
    organization's, so an organization can set the store for every machine
    and a user can still choose everything else. Each layer is put in
    order first (:func:`_normalized`): a deprecated spelling is read as the
    current one, and a relative folder is made absolute against the file
    it is in, so that a key the user set is never shadowed by the same
    setting spelled differently below it. The environment variables
    (``CHARTBOOK_STORE``, ``CHARTBOOK_GIT_CACHE``) sit above both and are
    read by the functions that need them.

    :raises ValueError: If the user's file cannot be read or parsed, or a
        table in it is malformed; the message names the file.
    """
    try:
        merged = _normalized(read_system_settings(), get_system_settings_path())
    except ValueError as error:
        # The organization's file is one file for every user on the machine:
        # a fault in it is said, and must not stop every command
        warnings.warn(f"{error} It is ignored.", stacklevel=2)
        merged = {}
    for key, value in _normalized(read_global_settings(), get_global_settings_path()).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _normalized(settings: dict, origin: Path) -> dict:
    """One layer's settings, put in order, with every fault named after its file.

    ``[store] path`` is read as ``[store] url`` with a warning. A ``url``
    or ``path`` that is a relative folder is made absolute against the
    folder the settings file is in, not against wherever the command
    happens to run. A table that is not a table, or a ``[store]`` with no
    usable ``url``, is a fault of that file.

    :raises ValueError: Naming *origin*.
    """
    result: dict = {}
    for key, value in settings.items():
        result[key] = dict(value) if isinstance(value, dict) else value
    for table in ("store", "git", "cache", "catalog"):
        if table in result and not isinstance(result[table], dict):
            raise ValueError(
                f"{origin}: [{table}] must be a table, e.g. [{table}] with "
                f"{'url' if table == 'store' else 'path'} = \"...\"."
            )
    store = result.get("store")
    if store is not None:
        url = store.get("url")
        if not (isinstance(url, str) and url.strip()):
            path = store.get("path")
            if isinstance(path, str) and path.strip():
                warnings.warn(
                    f"{origin}: [store] path is now [store] url. It is read as a folder this once; "
                    f"rename the key.",
                    stacklevel=3,
                )
                url = path
            else:
                raise ValueError(
                    f"{origin}: [store] needs a 'url', e.g. url = \"/a/bigger/disk/chartbook-store\"."
                )
        store.pop("path", None)
        store["url"] = _absolute_if_folder(url.strip(), origin)
    git = result.get("git")
    if git is not None:
        path = git.get("path")
        if not (isinstance(path, str) and path.strip()):
            raise ValueError(f"{origin}: [git] needs a 'path', e.g. path = \"/a/bigger/disk/chartbook-git\".")
        git["path"] = str(_absolute_if_folder(path.strip(), origin))
    cache = result.get("cache")
    if cache is not None:
        path = cache.get("path")
        if not (isinstance(path, str) and path.strip()):
            raise ValueError(f"{origin}: [cache] needs a 'path', e.g. path = \"/a/bigger/disk/chartbook-cache\".")
        cache["path"] = str(_absolute_if_folder(path.strip(), origin))
    catalog = result.get("catalog")
    if catalog is not None and "path" in catalog and not isinstance(catalog["path"], str):
        raise ValueError(f"{origin}: [catalog] path must be a string.")
    return result


def _absolute_if_folder(url: str, origin: Path) -> str:
    """A folder URL made absolute against the settings file's own folder; another URL as it is."""
    if store_kind(url) != "folder":
        return url
    try:
        expanded = Path(_folder_text(url)).expanduser()
    except RuntimeError:  # ~someone, for a user this machine does not know
        raise ValueError(f"{origin}: {url!r} names a user this machine does not know.") from None
    if not expanded.is_absolute():
        expanded = origin.parent / expanded
    return str(Path(os.path.abspath(expanded)))


def _folder_text(url: str) -> str:
    """The path inside a folder URL: the text itself, or what follows ``file://``.

    :raises ValueError: For ``file://host/...``: a file store is a folder on
        this machine, and a host is not read as a relative path by mistake.
    """
    text = url.strip()
    if not text.lower().startswith("file://"):
        return text
    text = text[len("file://"):]
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", text):
        text = text[1:]  # file:///C:/x names the drive, not a root folder
    if text and not text.startswith("/") and os.name != "nt":
        raise ValueError(
            f"The store {url!r} names a host; a file:// store is a folder on this machine, "
            f"written file:///path. For a folder on a shared drive, mount it and give its path."
        )
    return text


def _read_toml(path: Path, what: str, required: bool = False) -> dict:
    """Read one settings file, or ``{}`` if it is not there.

    :param what: The file's role, for a message: "the user's settings".
    :param required: Whether its absence is a fault (the file was named
        explicitly).
    :raises ValueError: Naming the file, when it cannot be read or parsed,
        or is named and not there.
    """
    if not path.is_file():
        if required:
            raise ValueError(f"{path}, named as {what}, is not a file.")
        return {}
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as error:
        raise ValueError(f"{path}, {what}, is not valid TOML: {error}.") from None
    except OSError as error:
        raise ValueError(f"{path}, {what}, cannot be read: {error.strerror or error}.") from None


def get_default_catalog_path() -> Optional[Path]:
    """Get the default catalog path.

    Resolution order:

    1. ``catalog.path`` from ``~/.chartbook/settings.toml`` (explicit override).
    2. ``~/.chartbook/chartbook.toml`` if it exists (global catalog).
    3. ``None`` if neither is available.

    :returns: The resolved catalog path, or ``None`` if not found.
    :rtype: Optional[Path]
    """
    settings = read_settings()
    raw = (settings.get("catalog") or {}).get("path")
    if raw:
        return Path(raw)

    # Fall back to the global catalog if it exists
    global_catalog = get_global_catalog_path()
    if global_catalog.is_file():
        return global_catalog

    return None


def get_store_url() -> str:
    """Where the store is, as the settings say it: a folder, or a URL.

    The store is a setting of the machine or the organization, never of a
    pipeline, so it is read in layers, each only where the one above it is
    silent:

    1. The ``CHARTBOOK_STORE`` environment variable, for one shell or one
       CI job.
    2. ``[store] url`` in the user's ``~/.chartbook/settings.toml``.
    3. ``[store] url`` in the organization's settings file
       (:func:`get_system_settings_path`).
    4. ``~/.chartbook/store``.

    A bare path is a folder. ``file://`` is a folder too. ``s3://`` is a
    bucket, with ``pip install chartbook[s3]``; another scheme names a kind
    of store a plugin provides. ``[store] path`` is still read, as a
    folder, with a warning. A
    relative folder in a settings file is relative to that file's folder.

    :raises ValueError: If the user's settings file is faulty; a fault in
        the organization's file is a warning, and that file is ignored.
    """
    from_environment = os.environ.get(STORE_ENV_VAR, "").strip()
    if from_environment:
        return from_environment
    configured = read_settings().get("store")
    if configured is not None:
        return configured["url"]
    return str(get_global_config_dir() / "store")


def store_kind(url: str) -> str:
    """The kind of store a URL names: ``folder`` for a path or ``file://``, else its scheme."""
    text = url.strip()
    scheme, sep, rest = text.partition("://")
    # A scheme as RFC 3986 has it; two letters at least, so that a Windows
    # drive letter is a path
    if sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]+", scheme):
        return "folder" if scheme.lower() == "file" else scheme.lower()
    return "folder"


def folder_of_store_url(url: str) -> Path:
    """The absolute folder a folder-kind store URL names.

    :raises ValueError: If the URL names another kind of store.
    """
    kind = store_kind(url)
    if kind != "folder":
        raise ValueError(
            f"The store {url!r} is a {kind}:// store, and this needs a folder: only a folder "
            f"store is built in; another kind is a plugin, found by `chartbook.store.store_for_url()`."
        )
    try:
        return Path(os.path.abspath(Path(_folder_text(url)).expanduser()))
    except RuntimeError:
        raise ValueError(f"The store {url!r} names a user this machine does not know.") from None


def get_store_path() -> Path:
    """The directory of the store, when it is a folder: the local folder of pinned files.

    See :func:`get_store_url` for how it is found. The directory need not
    exist yet.

    :returns: The absolute path of the store.
    :rtype: Path
    :raises ValueError: If the settings name a kind of store that is not
        built, or ``[store]`` is malformed.
    """
    return folder_of_store_url(get_store_url())


def get_git_cache_path() -> Path:
    """Get the directory that ``git`` dependencies are fetched into.

    Resolution order:

    1. The ``CHARTBOOK_GIT_CACHE`` environment variable.
    2. ``git.path`` from the user's settings, then the organization's
       (:func:`read_settings`).
    3. ``~/.chartbook/git``.

    The directory need not exist yet.

    :returns: The absolute path of the cache.
    :rtype: Path
    :raises ValueError: If ``git.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(GIT_CACHE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_settings().get("git")
    if configured is not None:
        return Path(configured["path"])

    return get_global_config_dir() / "git"


def get_cache_path() -> Path:
    """Get the directory a remote store's objects and records are kept in once read.

    A store in a bucket is read through a copy on this machine, laid out
    as a folder store under a folder for that bucket and prefix
    (:mod:`chartbook.stores.s3`). Resolution order:

    1. The ``CHARTBOOK_CACHE`` environment variable.
    2. ``cache.path`` from the user's settings, then the organization's
       (:func:`read_settings`).
    3. ``~/.chartbook/cache``.

    The directory need not exist yet, and everything in it can be removed:
    it is read again from the store.

    :returns: The absolute path of the cache.
    :rtype: Path
    :raises ValueError: If ``cache.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(CACHE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_settings().get("cache")
    if configured is not None:
        return Path(configured["path"])

    return get_global_config_dir() / "cache"


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
