"""Load project configurations from .env files or from the command line.

Provides easy access to paths and credentials used in the project.
Meant to be used as an imported module.

For information about the rationale behind decouple and this module,
see https://pypi.org/project/python-decouple/

Note that decouple mentions that it will help to ensure that
the project has "only one configuration module to rule all your instances."
This is achieved by putting all the configuration into the `.env` file.
You can have different sets of variables for difference instances,
such as `.env.development` or `.env.production`. You would only
need to copy over the settings from one into `.env` to switch
over to the other configuration, for example.


Example
-------
```python
import chartbook

# Get project root (cached)
BASE_DIR = chartbook.env.get_project_root()

# Compose paths
DATA_DIR = BASE_DIR / "_data"
prices = DATA_DIR / "raw" / "prices.parquet"

# Read from .env or CLI
username = chartbook.env.get("WRDS_USERNAME")
api_key = chartbook.env.get("FRED_API_KEY")
```

You can also run scripts with command line overrides:
```
>>> python myexample.py --DATA_DIR=/path/to/data
/path/to/data
```
or with environment variables:
```
>>> export DATA_DIR=/path/to/other
>>> python myexample.py
/path/to/other
```

"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from platform import system
from typing import TYPE_CHECKING, Sequence

from decouple import Config, RepositoryEnv, undefined
from decouple import config as _config_decouple

from chartbook.errors import ProjectRootNotFoundError

if TYPE_CHECKING:
    from typing import Any

# Default markers to search for when finding project root
DEFAULT_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    ".env",
    ".env.example",
    "requirements.txt",
)

# Cache for project root lookups
_project_root_cache: dict[tuple[Path, tuple[str, ...]], Path] = {}


def get_project_root(
    start: str | Path | None = None,
    markers: Sequence[str] | None = None,
    max_levels: int = 10,
    use_cache: bool = True,
) -> Path:
    """Find the project root directory by searching for marker files.

    The function determines the project root directory based on the following
    order of precedence:

    1. Checks for the `BASE_DIR` environment variable. If set, its value is
       returned as the project root path.
    2. If `BASE_DIR` is not set, it searches upwards from the start directory
       (or current working directory) for marker files/directories.
    3. The first directory containing any marker is returned as the project root.

    Parameters
    ----------
    start : str | Path | None
        Directory to start searching from. Defaults to Path.cwd().
    markers : Sequence[str] | None
        Marker files/directories to search for, in priority order.
        Defaults to: (".git", "pyproject.toml", ".env", ".env.example", "requirements.txt")
    max_levels : int
        Maximum number of parent directories to search. Default 10.
    use_cache : bool
        Whether to cache the result. Default True. The cache key is based on
        the resolved start path and markers tuple.

    Returns
    -------
    Path
        Absolute path to the project root.

    Raises
    ------
    ProjectRootNotFoundError
        If no marker is found within max_levels.

    Examples
    --------
    >>> import chartbook
    >>> BASE_DIR = chartbook.env.get_project_root()
    >>> DATA_DIR = BASE_DIR / "_data"

    >>> # Custom search from a specific directory
    >>> root = chartbook.env.get_project_root(
    ...     start="/some/nested/path",
    ...     markers=["Cargo.toml", "pyproject.toml"],
    ...     max_levels=5
    ... )
    """
    # 1. Check for BASE_DIR environment variable (highest priority)
    base_dir_env = os.environ.get("BASE_DIR")
    if base_dir_env:
        return Path(base_dir_env).resolve()

    # Resolve start directory
    if start is None:
        start_path = Path.cwd().resolve()
    else:
        start_path = Path(start).resolve()

    # Use default markers if not provided
    if markers is None:
        markers_tuple = DEFAULT_MARKERS
    else:
        markers_tuple = tuple(markers)

    # Check cache
    cache_key = (start_path, markers_tuple)
    if use_cache and cache_key in _project_root_cache:
        return _project_root_cache[cache_key]

    # 2. Search upwards for markers
    current_dir = start_path
    levels_searched = 0

    while levels_searched < max_levels:
        for marker in markers_tuple:
            marker_path = current_dir / marker
            if marker_path.exists():
                # Found a marker - cache and return
                result = current_dir.resolve()
                if use_cache:
                    _project_root_cache[cache_key] = result
                return result

        # Move to parent directory
        parent_dir = current_dir.parent

        # Check if we have reached the filesystem root
        if parent_dir == current_dir:
            break

        current_dir = parent_dir
        levels_searched += 1

    # No marker found - raise error
    raise ProjectRootNotFoundError(
        start_path=start_path,
        markers=markers_tuple,
        max_levels=max_levels,
    )


def clear_cache() -> None:
    """Clear the cached project root lookups.

    Call this function if you need to force a fresh lookup, for example
    after changing directories or modifying marker files.
    """
    _project_root_cache.clear()


def get_os_type() -> str:
    """Get the operating system type.

    Returns
    -------
    str
        "nix" for Unix-like systems (macOS, Linux), "windows" for Windows,
        or "unknown" for unrecognized systems.

    Examples
    --------
    >>> import chartbook
    >>> os_type = chartbook.env.get_os_type()
    >>> if os_type == "nix":
    ...     cmd = "ls"
    ... else:
    ...     cmd = "dir"
    """
    os_name = system()
    if os_name == "Windows":
        return "windows"
    elif os_name in ("Darwin", "Linux"):
        return "nix"
    else:
        return "unknown"


def _find_all_caps_cli_vars(argv: list[str] | None = None) -> dict[str, str]:
    """Find all command line arguments that are all caps.

    Find all command line arguments that are all caps and defined
    with a long option, for example, --DATA_DIR or --MANUAL_DATA_DIR.
    When that option is found, the value of the option is returned.

    For example, if the command line is:
    ```
    python script.py --DATA_DIR=/path/to/data --MANUAL_DATA_DIR=/path/to/manual_data
    ```
    Then the function will return:
    ```
    {'DATA_DIR': '/path/to/data', 'MANUAL_DATA_DIR': '/path/to/manual_data'}
    ```
    """
    if argv is None:
        argv = sys.argv
    result = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        # Handle --VAR=value format
        if arg.startswith("--") and "=" in arg and arg[2:].split("=")[0].isupper():
            var_name, value = arg[2:].split("=", 1)
            result[var_name] = value
        # Handle --VAR value format (where value is the next argument)
        elif arg.startswith("--") and arg[2:].isupper() and i + 1 < len(argv):
            var_name = arg[2:]
            value = argv[i + 1]
            # Only use this value if it doesn't look like another option
            if not value.startswith("--"):
                result[var_name] = value
                i += 1  # Skip the next argument since we used it as a value
        i += 1
    return result


def _load_config() -> Config:
    """Load configuration from .env file if available."""
    try:
        estimated_project_root = get_project_root()
    except ProjectRootNotFoundError:
        # Fall back to cwd if project root not found
        estimated_project_root = Path.cwd()

    candidates = [
        Path.cwd() / ".env",
        estimated_project_root / ".env",
    ]
    env_file = next((p for p in candidates if p.is_file()), None)
    if not env_file:
        return _config_decouple
    return Config(repository=RepositoryEnv(str(env_file)))


def _if_relative_make_abs(path: str | Path, base_dir: Path) -> Path:
    """If a relative path is given, make it absolute relative to base_dir."""
    path = Path(path)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _get_os() -> str:
    """Get the operating system type."""
    os_name = system()
    if os_name == "Windows":
        return "windows"
    elif os_name in ("Darwin", "Linux"):
        return "nix"
    else:
        return "unknown"


########################################################
## Define defaults (loaded at module import time)
########################################################
_cli_vars = _find_all_caps_cli_vars()
_decouple_config = _load_config()


def _build_defaults() -> dict[str, Any]:
    """Build the defaults dictionary."""
    defaults: dict[str, Any] = {}

    # OS type
    if "OS_TYPE" in _cli_vars:
        defaults["OS_TYPE"] = _cli_vars["OS_TYPE"]
    else:
        defaults["OS_TYPE"] = _get_os()

    # Absolute path to root directory of the project
    if "BASE_DIR" in _cli_vars:
        defaults["BASE_DIR"] = Path(_cli_vars["BASE_DIR"]).resolve()
    else:
        try:
            defaults["BASE_DIR"] = get_project_root()
        except ProjectRootNotFoundError:
            defaults["BASE_DIR"] = Path.cwd().resolve()

    # User name
    if defaults["OS_TYPE"] == "windows":
        userprofile = os.environ.get("USERPROFILE", "")
        defaults["USER"] = Path(userprofile).name if userprofile else ""
    elif defaults["OS_TYPE"] == "nix":
        defaults["USER"] = _decouple_config("USER", default="")
    else:
        defaults["USER"] = ""

    # File paths
    base_dir = defaults["BASE_DIR"]
    defaults["DATA_DIR"] = _if_relative_make_abs(Path("_data"), base_dir)
    defaults["MANUAL_DATA_DIR"] = _if_relative_make_abs(Path("data_manual"), base_dir)
    defaults["OUTPUT_DIR"] = _if_relative_make_abs(Path("_output"), base_dir)

    return defaults


_defaults = _build_defaults()


def get(
    var_name: str,
    default: Any = undefined,
    cast: Any = undefined,
    convert_dir_vars_to_abs_path: bool = True,
) -> Any:
    """Get a configuration variable from CLI args, environment, or defaults.

    The definition of variables follows an order of precedence:
    1. Command line arguments (e.g., --DATA_DIR=/path/to/data)
    2. Environment variables (including .env file)
    3. Module defaults
    4. Provided default value
    5. Error if not found

    Parameters
    ----------
    var_name : str
        The name of the variable to retrieve.
    default : Any
        Default value if the variable is not found anywhere.
    cast : Any
        A callable to cast/convert the value (e.g., int, bool).
    convert_dir_vars_to_abs_path : bool
        If True and "DIR" is in var_name, convert relative paths to absolute.

    Returns
    -------
    Any
        The configuration value.

    Examples
    --------
    >>> import chartbook
    >>> username = chartbook.env.get("WRDS_USERNAME")
    >>> port = chartbook.env.get("PORT", default=8080, cast=int)
    """
    base_dir = _defaults.get("BASE_DIR", Path.cwd())

    # 1. Command line arguments (highest priority)
    if var_name in _cli_vars and _cli_vars[var_name] is not None:
        value = _cli_vars[var_name]
        # Apply cast if provided
        if cast is not undefined:
            value = cast(value)
        if "DIR" in var_name and convert_dir_vars_to_abs_path:
            value = _if_relative_make_abs(Path(value), base_dir)
        return value

    # 2. Environment variables through decouple
    # Use decouple but with a sentinel default to detect if it was found
    env_sentinel = object()
    env_value = _decouple_config(var_name, default=env_sentinel)
    if env_value is not env_sentinel:
        # Found in environment
        if cast is not undefined:
            env_value = cast(env_value)
        if "DIR" in var_name and convert_dir_vars_to_abs_path:
            env_value = _if_relative_make_abs(Path(env_value), base_dir)
        return env_value

    # 3. Module defaults dictionary
    if var_name in _defaults:
        default_value = _defaults[var_name]
        # If default_value is directly usable (not a dict with metadata)
        if cast is not undefined:
            default_value = cast(default_value)
        return default_value

    # 4. Use the default value provided by the caller. Error if not found
    return _decouple_config(var_name, default=default, cast=cast)


# Backwards compatibility alias
config = get


def create_directories() -> None:
    """Create the default data and output directories if they don't exist."""
    get("DATA_DIR").mkdir(parents=True, exist_ok=True)
    get("OUTPUT_DIR").mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    pass
