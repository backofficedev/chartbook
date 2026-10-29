"""Load and process ``chartbook.toml`` manifests (format v2).

A v2 manifest has a single ``[project]`` metadata table plus the entity
sections ``[charts]``, ``[dataframes]``, ``[notebooks]``, ``[notes]`` and
``[models]``, a ``[dependencies]`` table naming the pipelines it reads from
and a ``[scripts]`` table of named commands (pipelines), or a ``[pipelines]``
registry and optional ``[policy]`` (catalogs). Every ``[project]`` field is
optional; defaults are filled at load time. See
``docs_src/design/toml-format-v2.md`` for the full specification.

v1 manifests (the old ``[config]``/``[site]``/``[pipeline]`` layout) are not
supported; loading one raises an error pointing at the migration script.
"""

import difflib
import json
import importlib.resources
import os
import re
import subprocess
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import tomli

from chartbook import formats
from chartbook.identity import (
    ID_COMPONENT_PATTERN,
    _git_environment,
    UnsupportedRevisionError,
    derive_pipeline_id,
    get_git_remote_url,
    remote_to_web_url,
    split_rev,
    validate_pipeline_id,
)
from chartbook.utils import extract_notebook_title, is_glob_pattern

BASE_DIR = Path(".").resolve()
OUTPUT_DIR = Path("./_output")
PIPELINE_THEME = "pipeline"
PUBLISH_DIR = Path("./_output/to_be_published")
DOCS_BUILD_DIR = BASE_DIR / Path("_docs")
DOCS_SRC_DIR = BASE_DIR / Path("_docs_src")

#: Default location for custom site pages, used when the directory exists
#: and ``project.site_dir`` is not set explicitly.
DEFAULT_SITE_DIR = "./docs_src/site/"

#: All recognized ``[project]`` keys with their defaults. Empty-string and
#: empty-list defaults are placeholders resolved at load time (see
#: ``_resolve_project``).
PROJECT_DEFAULTS = {
    "type": "pipeline",
    "id": "",
    "name": "",
    "description": "",
    "maintainer": "",
    "contributors": [],
    "repo_url": "",
    "site_url": "",
    "readme": "./README.md",
    "copyright": "",
    "logo": "",
    "favicon": "",
    "os_compatibility": [],
    "build": "",
    "site_dir": "",
    "enable_data_download": False,
    "writer": "sphinx",
    # Which ChartBook the project needs, as a requirement: ">=0.2.0"
    "requires_chartbook": "",
}

#: The site tools a manifest may name in ``[project] writer``; each is a module of :mod:`chartbook.writers`.
WRITERS = ("sphinx", "mkdocs")

#: Entity sections that mark a manifest as pipeline-shaped.
ENTITY_SECTIONS = ("charts", "dataframes", "notebooks", "notes", "models", "files")

#: v1 sections whose presence identifies an unmigrated manifest.
V1_MARKER_SECTIONS = ("config", "site", "pipeline")

_V1_HINT = (
    "This chartbook.toml uses the old v1 format ([config]/[site]/[pipeline] "
    "sections), which is no longer supported. Run the migration script to "
    "rewrite it: python scripts/migrate_toml_v2.py <path>. "
    "See docs_src/design/toml-format-v2.md for the v2 format."
)


class V1FormatError(ValueError):
    """Raised when a v1-format chartbook.toml is loaded."""

    def __init__(self, source: Union[str, Path]):
        super().__init__(f"{source}: {_V1_HINT}")


def detect_v1_format(raw_manifest: dict) -> bool:
    """Return True if a raw manifest dict uses the old v1 layout.

    :param raw_manifest: The dict parsed from chartbook.toml.
    :rtype: bool
    """
    return any(section in raw_manifest for section in V1_MARKER_SECTIONS)


class RequiresChartbookError(ValueError):
    """A manifest's ``requires_chartbook`` that the ChartBook running does not meet."""


def require_chartbook(raw_manifest: dict, source: str = "chartbook.toml") -> None:
    """Stop when the ChartBook running is not one the project asks for in ``[project] requires_chartbook``.

    The value is a version specifier, as a pip requirement has it after
    the package's name (``">=0.2.0"``, ``">=0.3,<0.5"``), compared with this
    package's version. Every command that acts on a manifest reads the
    project's type first (:func:`resolve_project_type` calls this first), so
    an older ChartBook stops here, with the command that installs one that
    meets it, before something newer in the manifest confuses it. A
    ChartBook from before 0.2.0 does not know the key, and warns that it is
    unknown; the check holds from 0.2.0 on.

    :raises RequiresChartbookError: If this ChartBook does not meet it.
    :raises ValueError: If the value is not a specifier.
    """
    project = raw_manifest.get("project")
    value = project.get("requires_chartbook", "") if isinstance(project, dict) else ""
    if value == "":
        return
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    from chartbook.__about__ import __version__

    where = f"{source}: [project]"
    if not isinstance(value, str):
        raise ValueError(
            f"{where}: requires_chartbook = {value!r} is {_toml_word(value)}, and requires_chartbook is a "
            f'version specifier, as a string. Write requires_chartbook = ">={__version__}".'
        )
    shown = value if len(value) <= 80 else value[:77] + "..."
    try:
        wanted = SpecifierSet(value)
        # Asked now: a number too long to read is found when it is compared
        met = wanted.contains(Version(__version__), prereleases=True) if len(wanted) > 0 else None
    except Exception:  # noqa: BLE001 - packaging's InvalidSpecifier, or a number too long to read
        met = None
    if met is None:
        bare = value.strip()
        hint = None
        if bare.lower().startswith("chartbook"):
            bare = bare[len("chartbook"):].strip()  # the whole pip requirement, name and all
            try:
                if len(SpecifierSet(bare)) > 0:
                    hint = f'Write requires_chartbook = "{bare}": the specifier alone, without the package\'s name.'
            except Exception:  # noqa: BLE001
                pass
        if hint is None:
            try:
                version = str(Version(bare))
                hint = f'Write requires_chartbook = ">={version}" for {version} or later.'
            except Exception:  # noqa: BLE001
                hint = f'Write requires_chartbook = ">={__version__}", or take the key out.'
        what = "names no version" if value.strip() in ("", ",") else "is not a version specifier"
        raise ValueError(f"{where}: requires_chartbook = {shown!r} {what}. {hint}") from None
    if not met:
        raise RequiresChartbookError(
            f"{source} requires ChartBook {value} ([project] requires_chartbook), and this is ChartBook "
            f'{__version__}. Install one that meets it: `pip install -U "chartbook{value}"`, or '
            f'`uv add "chartbook{value}"` in a uv project.'
        )


def resolve_project_type(raw_manifest: dict, source: str = "chartbook.toml") -> str:
    """Resolve a manifest's project type, inferring from structure when unset.

    Inference: a ``[pipelines]`` registry table means catalog; anything else
    means pipeline. Contradictions between an explicit ``type`` and the file
    structure are hard errors, as is a file that is both catalog- and
    pipeline-shaped with no explicit type.

    :param raw_manifest: The dict parsed from chartbook.toml.
    :param source: Label used in error messages.
    :returns: ``"pipeline"`` or ``"catalog"``.
    :raises ValueError: On an invalid ``type`` value, a contradiction, or
        an ambiguous file; or a ``requires_chartbook`` this ChartBook does
        not meet, which is asked first (:func:`require_chartbook`).
    """
    project = raw_manifest.get("project", {})
    if not isinstance(project, dict):
        raise ValueError(f"{source}: [project] must be a table, not {type(project).__name__}.")
    require_chartbook(raw_manifest, source)
    explicit = project.get("type")
    has_registry = "pipelines" in raw_manifest
    entity_sections = [
        s for s in ENTITY_SECTIONS if raw_manifest.get(s)
    ]

    if explicit is not None and explicit not in ("pipeline", "catalog"):
        raise ValueError(
            f"{source}: invalid project.type {explicit!r}. "
            f"Must be 'pipeline' or 'catalog' (or omitted to infer)."
        )

    if explicit == "pipeline" and has_registry:
        raise ValueError(
            f"{source}: project.type is 'pipeline' but a [pipelines] registry "
            f"table is present. A pipeline cannot contain a catalog registry; "
            f"remove [pipelines] or set type = 'catalog'."
        )

    if explicit == "catalog" and entity_sections:
        raise ValueError(
            f"{source}: project.type is 'catalog' but pipeline sections are "
            f"present ({', '.join('[' + s + ']' for s in entity_sections)}). "
            f"A catalog cannot define its own charts or dataframes; move them "
            f"to a pipeline or set type = 'pipeline'."
        )

    if explicit is not None:
        return explicit

    if has_registry and entity_sections:
        raise ValueError(
            f"{source}: ambiguous project type — the file has both a "
            f"[pipelines] registry and pipeline sections "
            f"({', '.join('[' + s + ']' for s in entity_sections)}). "
            f"Set project.type explicitly."
        )

    return "catalog" if has_registry else "pipeline"


def _read_manifest_file(base_dir: Path) -> dict:
    """Read and parse a chartbook.toml, rejecting v1 files.

    :param base_dir: Directory containing chartbook.toml.
    :returns: The raw parsed dict.
    :raises FileNotFoundError: If no chartbook.toml exists.
    :raises ValueError: If the file is not valid TOML; the message names
        the file, since a catalog reads several in one go.
    :raises V1FormatError: If the file uses the v1 layout.
    """
    chartbook_toml_path = Path(base_dir) / "chartbook.toml"
    if not chartbook_toml_path.is_file():
        raise FileNotFoundError(f"No chartbook.toml found in directory: {base_dir}")
    raw_manifest = _parse_toml_file(chartbook_toml_path)
    if detect_v1_format(raw_manifest):
        raise V1FormatError(chartbook_toml_path)
    return raw_manifest


def _parse_toml_file(path: Path) -> dict:
    """What a TOML file holds; a syntax error is a ValueError that names the file."""
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as error:
        raise ValueError(f"{path} is not valid TOML: {error}.") from None


#: The word TOML has for what a value is, by its Python type.
_TOML_WORDS = (
    (bool, "a boolean"),
    (str, "a string"),
    (int, "an integer"),
    (float, "a float"),
    (list, "an array"),
    (dict, "a table"),
)


def _toml_word(value) -> str:
    """What a parsed value is, in TOML's words: ``5`` is an integer, ``[5]`` an array, ``{}`` a table."""
    for kind, word in _TOML_WORDS:
        if isinstance(value, kind):
            return word
    return "a date" if hasattr(value, "year") else type(value).__name__


def _require_string(value, where: str, key: str, example: str) -> None:
    """Refuse a field that is not a string, saying what it is and what to write.

    :param where: The table, for the message: ``chartbook.toml: [dataframes.x]``.
    :param example: What a right value looks like, e.g. ``./docs_src/x.md``.
    :raises ValueError: If *value* is not a string.
    """
    if not isinstance(value, str):
        # A number or a date where the field is one (copyright = 2025) is
        # shown back in quotes, "2025": that is what was meant. Anything else
        # gets the example; "5" is no path
        number_like = isinstance(value, (int, float)) and not isinstance(value, bool) or hasattr(value, "year")
        shown = json.dumps(str(value)) if number_like and re.fullmatch(r"[\d.-]+", example) else json.dumps(example)
        raise ValueError(
            f"{where + ': ' if where else ''}{key} = {value!r} is {_toml_word(value)}, and {key} is a string. "
            f"Write {key} = {shown}."
        )


def _require_list_of_strings(value, where: str, key: str, example: str) -> None:
    """Refuse a field that is not a list of strings, saying what it is and what to write.

    A bare string is refused too, not read as a list of one: a list field
    is written in brackets, and a string in a field that is iterated would
    otherwise become its letters.

    :param where: The table, for the message: ``chartbook.toml: [dataframes.x]``.
    :param example: A right value, e.g. ``["Rates", "Treasury"]``.
    :raises ValueError: If *value* is not a list, or an item is not a string.
    """
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return
    if isinstance(value, str):
        what, shown = "a string", f"[{json.dumps(value)}]"  # the string given, as a list of one
    elif isinstance(value, list):
        what, shown = "an array with an item that is not a string", example
    else:
        what, shown = _toml_word(value), example
    raise ValueError(
        f"{where + ': ' if where else ''}{key} = {value!r} is {what}, and {key} is a list of strings. "
        f"Write {key} = {shown}."
    )


def validate_manifest_file(path: Path = BASE_DIR) -> bool:
    """Validate that a directory holds a loadable v2 chartbook.toml.

    :param path: The directory to check.
    :returns: True if validation succeeds.
    :raises ValueError: If the file is missing, unparseable, v1-format, or
        has an unresolvable project type.
    """
    path = Path(path)
    try:
        raw_manifest = _read_manifest_file(path)
        resolve_project_type(raw_manifest, source=str(path / "chartbook.toml"))
    except (V1FormatError, ValueError, FileNotFoundError):
        raise
    except Exception as e:
        raise ValueError(f"Error loading chartbook.toml: {e}")
    return True


def resolve_platform_path(path_input: Union[str, dict]) -> Path:
    """Resolve a path that is either a string or a platform table.

    :param path_input: Either a path string, or a dict with ``unix`` and/or
        ``windows`` keys for platform-specific paths.
    :returns: The path for the current platform.
    :raises ValueError: If using a dict input and no path is defined for the
        current platform.

    **Examples**::

        resolve_platform_path('/path/to/dir')
        # Returns: PosixPath('/path/to/dir')

        resolve_platform_path({'unix': '/home/data', 'windows': 'C:/data'})
        # Returns: PosixPath('/home/data') on Unix/macOS, WindowsPath('C:/data') on Windows
    """
    from chartbook.path_validation import (
        _print_diagnostic,
        check_toml_path,
        detect_shell_environment,
    )

    if isinstance(path_input, str):
        result_path = Path(path_input)
        # Warn about potential shell/platform path mismatches
        env = detect_shell_environment()
        diags = check_toml_path(path_input, env, "path", "chartbook.toml")
        for d in diags:
            _print_diagnostic(d)
        return result_path

    import platform

    is_windows = platform.system().lower() == "windows"
    platform_key = "windows" if is_windows else "unix"
    if platform_key in path_input:
        return Path(path_input[platform_key])

    raise ValueError(
        f"No path defined for the current platform ({platform.system()}). "
        f"Available keys: {list(path_input.keys())}; expected 'unix' and/or 'windows'."
    )


def catalog_entry_dir(base_dir: Union[str, Path], path: Path, where: str = "") -> Path:
    """The folder a catalog's entry names, by its path relative to the catalog's folder.

    The path is joined to the catalog's folder with every link in that
    folder's own path followed, as ``chartbook catalog add`` works it out.
    One written from the folder as it is named instead (by hand, or by an
    older ``catalog add``, with a home folder reached through a link), or
    read where ``..`` is taken before a link is followed (``realpath`` on
    Windows, through a junction), is joined as written when the first way
    finds no chartbook.toml and this one does. That works only where the
    catalog is reached as it was named when the path was written, so it is
    said, with the path to write instead.

    :param base_dir: The catalog's folder, as it was named: the commands
        that read a catalog keep the links in the path they were given.
    :param path: The entry's path, for this platform (:func:`resolve_platform_path`).
    :param where: The entry, to say it when its path is read the second
        way (``chartbook.toml: [pipelines."acme/rates"]``); nothing is
        said without it.
    :returns: The folder, resolved.
    """
    found = (Path(base_dir).resolve() / path).resolve()
    if not (found / "chartbook.toml").is_file():
        as_written = Path(os.path.normpath(Path(base_dir) / path))
        if (as_written / "chartbook.toml").is_file():
            if where:
                instead = Path(os.path.relpath(as_written.resolve(), Path(base_dir).resolve())).as_posix()
                warnings.warn(
                    f"{where} path: {Path(path).as_posix()} names the pipeline only from {base_dir}, the "
                    f"catalog's folder as it is named here, through a link; from the folder itself, "
                    f"{Path(base_dir).resolve()}, it names none. Write path = \"{instead}\" so that it is "
                    f"read the same way however the catalog is reached.",
                    UserWarning,
                    stacklevel=2,
                )
            return as_written.resolve()
    return found


def validate_os_compatibility(value, where: str = "[project]") -> list:
    """Validate that ``[project] os_compatibility`` is a list of strings.

    A bare string is refused, not read as a list of one: a page joins the
    list, and would otherwise show the string's letters.

    :param value: The os_compatibility value to validate.
    :param where: The table, for the message.
    :returns: The validated list (unchanged).
    :raises ValueError: If the value is not a list of strings.
    """
    _require_list_of_strings(value, where, "os_compatibility", '["Linux", "macOS", "Windows"]')
    return value


def normalize_tags(tags: list, where: str = "") -> list:
    """Normalize a list of tags to Title Case.

    :param tags: List of tag strings to normalize
    :param where: The table the tags are in, for the message when they are
        not a list.
    :returns: List of tags in Title Case
    :raises ValueError: If *tags* is not a list of strings: a bare string
        is not read as one tag, since its letters would become the tags.

    Examples
    --------

    ```python
    normalize_tags(['short term funding', 'REPO', 'Monetary Policy'])
    # Output: ['Short Term Funding', 'Repo', 'Monetary Policy']
    ```
    """
    _require_list_of_strings(tags, where, "tags", '["Rates", "Treasury"]')
    return [tag.title() for tag in tags]


def validate_doc_fields(
    manifest: dict,
    object_type: str,
    object_id: str,
) -> tuple[str, str]:
    """Validate that exactly one of ``docs_path`` / ``docs`` is provided.

    :param manifest: The manifest dictionary for the object (dataframe or chart).
    :param object_type: The type of object ('dataframe' or 'chart') for error messages.
    :param object_id: The ID of the object for error messages.
    :returns: A tuple of (mode, value) where mode is 'path' or 'str'.
    :raises ValueError: If both or neither fields are provided.
    """
    has_path = manifest.get("docs_path")
    has_str = manifest.get("docs")

    if has_path and has_str:
        raise ValueError(
            f"{object_type} '{object_id}' has both docs_path and docs. "
            f"Only one is allowed."
        )
    if not has_path and not has_str:
        raise ValueError(
            f"{object_type} '{object_id}' must have either docs_path (a markdown "
            f"file) or docs (inline markdown)."
        )

    if has_path:
        return ("path", manifest["docs_path"])
    return ("str", manifest["docs"])


def validate_series(dataframe_manifest: dict, dataframe_id: str) -> dict:
    """Validate a dataframe's ``[dataframes.<id>.series.<key>]`` tables.

    A series is one column of a dataframe, given an address
    (``dataframe#key``) so that a name, units, a frequency and a write-up can
    be attached to it. Declaring one is how a column is documented, not how
    it comes to exist: every column is in the index whether or not it has a
    table here. See "Addressing a series inside a dataframe" in
    ``docs_src/design/asset-graph.md``.

    Each table's ``column`` is filled in with its key when it is not given.

    :param dataframe_manifest: The dataframe's manifest entry.
    :param dataframe_id: Its key, for error messages.
    :returns: The series tables by key; empty if the dataframe declares none.
    :raises ValueError: If the tables are malformed, a key is not a legal
        name, or two series claim one column.
    """
    series = dataframe_manifest.get("series")
    if series is None:
        return {}
    where = f"[dataframes.{dataframe_id}.series]"
    if not isinstance(series, dict):
        raise ValueError(
            f"{where} must be a table of tables, one per series, e.g. "
            f"[dataframes.{dataframe_id}.series.dgs10]."
        )
    claimed: dict[str, str] = {}
    for key, entry in series.items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"{where}: {key!r} must be a table, e.g. "
                f"[dataframes.{dataframe_id}.series.{key}] with a 'name'."
            )
        if not ID_COMPONENT_PATTERN.match(key):
            raise ValueError(
                f"{where}: {key!r} is not a legal series key. A key becomes "
                f"part of an address ('{dataframe_id}#<key>'), so it must match "
                f"[A-Za-z0-9._-]+. Name the column itself with "
                f"column = {key!r}."
            )
        column = entry.setdefault("column", key)
        if not isinstance(column, str) or not column:
            raise ValueError(f"{where}: {key!r} has a 'column' that is not a name.")
        if column in claimed:
            raise ValueError(
                f"{where}: {claimed[column]!r} and {key!r} both name the column "
                f"{column!r}. A column is one series."
            )
        claimed[column] = key
        if entry.get("docs") and entry.get("docs_path"):
            raise ValueError(
                f"{where}: {key!r} has both docs_path and docs. Only one is allowed."
            )
    return series


#: The script that makes a pipeline's assets current. It is the one name in
#: ``[scripts]`` that ChartBook gives a meaning to: what ``chartbook run``
#: runs by default, and what it runs once in a git dependency's clean copy.
BUILD_SCRIPT = "build"


def read_scripts(raw_manifest: dict) -> dict:
    """Read a pipeline's named scripts: ``[scripts]``, and ``[project] build``.

    A script is one string, run by a shell in the pipeline's directory::

        [scripts]
        build = "doit"
        test = "pytest"
        fetch = '''
        module load python/3.12
        python src/pull_wrds.py
        '''

    A value of several lines is one script, so what one line sets up the
    next can use. ``[project] build`` is the same thing as
    ``[scripts] build`` and is still read; a manifest gives it in one place.

    Scripts are not tasks. There is no order among them and none depends
    on another. See "Running things" in ``docs_src/design/asset-graph.md``.

    :param raw_manifest: The dict parsed from chartbook.toml.
    :returns: The scripts by name. ``build`` is in it if either table gives
        one.
    :raises ValueError: If the table is malformed, a name could not be
        typed on a command line, a script is empty, or ``build`` is given
        twice and differently.
    """
    scripts = raw_manifest.get("scripts")
    if scripts is None:
        scripts = {}
    if not isinstance(scripts, dict):
        raise ValueError(
            '[scripts] must be a table of named commands, e.g. build = "doit".'
        )
    found = {}
    for name, script in scripts.items():
        if not ID_COMPONENT_PATTERN.match(name):
            raise ValueError(
                f"[scripts]: {name!r} is not a name a script can have. It is "
                f"typed after `chartbook run`, so it must match [A-Za-z0-9._-]+."
            )
        if not isinstance(script, str) or not script.strip():
            raise ValueError(
                f"[scripts]: {name!r} must be a command, as a string, e.g. "
                f'{name} = "doit".'
            )
        found[name] = script

    project = raw_manifest.get("project")
    old_place = project.get(BUILD_SCRIPT) if isinstance(project, dict) else None
    if isinstance(old_place, str) and old_place.strip():
        if BUILD_SCRIPT in found and found[BUILD_SCRIPT].strip() != old_place.strip():
            raise ValueError(
                "The build script is given twice, and differently: in [project] "
                "build and in [scripts] build. Keep the one in [scripts]."
            )
        found.setdefault(BUILD_SCRIPT, old_place)
    return found


#: The keys a source in ``[sources]`` may have.
SOURCE_KEYS = ("backend", "url")

#: What says where a dataframe's content is. Exactly one of them.
DATAFRAME_LOCATION_KEYS = ("path", "table", "query")


def validate_sources(raw_sources, base_dir: Path) -> dict:
    """Validate a pipeline's ``[sources]``: the engines its dataframes may live in.

    A source is a named, configured instance of a backend::

        [sources.local]
        backend = "duckdb"
        url = "duckdb:///./_data/local.duckdb"

    See ``docs_src/design/data-access.md``. Each source gains
    ``_resolved_url``: for a DuckDB file, the URL the machine opens it
    with, from :func:`chartbook.backends.source_url`, with a relative file
    made absolute; for another engine, the manifest's public URL, from
    which its backend finds the machine's URL and credentials when it
    connects, so that no credential is carried around.

    :raises ValueError: If the table is malformed, a name is not a legal
        name, a backend is not built, a url carries credentials, or a url
        does not match its backend.
    """
    from chartbook.backends import (
        MEMORY_URL,
        BackendError,
        check_backend,
        check_url,
        duckdb_path,
        scheme_of,
        source_env_var,
        source_url,
    )

    if raw_sources is None:
        return {}
    if not isinstance(raw_sources, dict):
        raise ValueError("[sources] must be a table of tables, one per source, e.g. [sources.local].")
    sources = {}
    for name, entry in raw_sources.items():
        where = f"[sources.{name}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a table with 'backend' and 'url'.")
        if not ID_COMPONENT_PATTERN.match(name):
            raise ValueError(
                f"{where}: {name!r} is not a legal source name; it must match [A-Za-z0-9._-]+."
            )
        unknown = sorted(set(entry) - set(SOURCE_KEYS))
        if unknown:
            raise ValueError(
                f"{where} has {', '.join(map(repr, unknown))}. A source has only "
                f"{' and '.join(SOURCE_KEYS)}; credentials go in the environment or "
                f"~/.chartbook/sources.toml."
            )
        for key in SOURCE_KEYS:
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"{where} needs {key!r}, a string.")
        check_backend(entry["backend"], where)
        check_url(entry["url"], entry["backend"], where)
        try:
            machine_url = source_url(name, entry["url"])
        except BackendError as error:
            raise ValueError(f"{where}: {error}") from None
        if scheme_of(machine_url) != entry["backend"]:
            raise ValueError(
                f"{where}: the machine's url for this source, from {source_env_var(name)} "
                f"or ~/.chartbook/sources.toml, begins with "
                f"{scheme_of(machine_url) or 'no scheme'}:// and the backend is "
                f"{entry['backend']}. The manifest names the engine; the machine says "
                f"where it is, not which it is."
            )
        resolved = dict(entry)
        if entry["backend"] == "duckdb":
            try:
                path = duckdb_path(machine_url, base_dir)
            except ValueError as error:
                raise ValueError(f"{where}: {error}") from None
            resolved["_resolved_url"] = MEMORY_URL if path == ":memory:" else "duckdb:///" + path
        else:
            resolved["_resolved_url"] = entry["url"]
        sources[name] = resolved
    return sources


def validate_dataframe_location(entry: dict, dataframe_id: str, sources: dict) -> str:
    """Say where one dataframe's content is: a file, a table or a query.

    Exactly one of ``path``, ``table`` and ``query``. The last two need a
    ``source`` that ``[sources]`` declares; ``path`` takes none.

    :returns: ``"file"``, ``"table"`` or ``"query"``.
    :raises ValueError: If the entry says two things, or none, or names a
        source that is not declared.
    """
    where = f"[dataframes.{dataframe_id}]"
    given = [key for key in DATAFRAME_LOCATION_KEYS if key in entry]
    if len(given) > 1:
        raise ValueError(
            f"{where} has {' and '.join(given)}. A dataframe is in one place: "
            f"a file (path), a table (source and table) or a query (source and query)."
        )
    if "path" in given:
        if "source" in entry:
            raise ValueError(
                f"{where} has both path and source. A file needs no source; a table "
                f"or a query in a source has no path."
            )
        return "file"
    if not given:
        if "source" in entry:
            raise ValueError(
                f"{where} has a source and neither table nor query. Say which it is: "
                f'table = "name", or query = "select ...".'
            )
        return "file"  # a dataframe without a path: declared, and documented only
    kind = given[0]
    value = entry[kind]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {kind!r} must be a string, and not empty.")
    source = entry.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(
            f"{where} has {kind!r} and no source. Say which source holds it: "
            f'source = "local", with [sources.local] declared.'
        )
    if source not in sources:
        declared = ", ".join(sorted(sources)) or "(none)"
        raise ValueError(
            f"{where}: source {source!r} is not declared. Its sources are: "
            f"{declared}. Add [sources.{source}] with a backend and a url."
        )
    return kind


#: The keys an entry of ``[dependencies]`` may have.
DEPENDENCY_KEYS = ("path", "git", "rev", "id", "commit", "repository")

_DEPENDENCY_EXAMPLE = (
    '"ftsfr/fed_yield_curve" = {} (its snapshots in the store, by its ID), '
    '{ path = "../fed_yield_curve" } or '
    '{ git = "https://example.org/ftsfr/fed_yield_curve", rev = "a1b2c3d" }'
)

#: What a dependency named by its ID alone may narrow its snapshots to: the
#: start of a commit, as git shows it
_COMMIT_START = re.compile(r"[0-9a-f]{7,40}")


def validate_dependencies(dependencies, base_dir: Union[str, Path]) -> dict:
    """Validate a pipeline's ``[dependencies]`` table.

    A dependency is another pipeline that this one reads from. The key is
    the name this pipeline knows it by, which is a pipeline ID; the value
    says where to get it::

        [dependencies]
        "ftsfr/rates" = {}
        yields = { id = "ftsfr/yield_curve", commit = "3f2a9c1" }
        "ftsfr/fed_yield_curve" = { path = "../fed_yield_curve" }
        "ftsfr/crsp_compustat" = { git = "https://example.org/ftsfr/crsp_compustat", rev = "a1b2c3d" }

    An entry with neither ``path`` nor ``git`` names the pipeline by its ID
    alone (the key, or ``id``), and is pinned from its snapshots in the
    store, with no folder of it and no clone: the newest, or the newest at
    the commit ``commit`` starts; ``repository`` keeps to the snapshots made
    in that repository, when more than one claims the ID. Such an entry
    gains ``_store``, the pipeline's ID, and ``_repository``.

    Identity and location are kept apart on purpose. Code, lineage and the
    index say ``ftsfr/fed_yield_curve``; only this table says where that
    is, so moving a repository changes one line. See "Identity and
    location" in ``docs_src/design/asset-graph.md``.

    Only the table's shape is checked. Whether a ``path`` holds a pipeline
    is ``chartbook check``'s business: a manifest has to load on a machine
    where a dependency is not there yet.

    Each ``path`` entry gains ``_resolved_path``, the directory made
    absolute.

    :param dependencies: The raw ``[dependencies]`` table.
    :param base_dir: The pipeline's root directory, which a ``path`` is
        relative to.
    :returns: The entries by key.
    :raises UnsupportedRevisionError: If a key carries ``@rev``.
    :raises UnsupportedRegistryError: If a key carries a registry prefix.
    :raises ValueError: If the table or an entry is malformed.
    """
    if not isinstance(dependencies, dict):
        raise ValueError(
            f"[dependencies] must be a table with one entry per pipeline, "
            f"e.g. {_DEPENDENCY_EXAMPLE}."
        )
    validated = {}
    for key, entry in dependencies.items():
        where = f"[dependencies]: {key!r}"
        unpinned, rev = split_rev(key)
        if rev is not None:
            raise UnsupportedRevisionError(
                f"{where} pins a revision with '@rev'. In a key that is "
                f"reserved syntax and not yet supported; use {unpinned!r} as "
                f'the key. A git dependency\'s revision is its rev = "{rev}".'
            )
        try:
            validate_pipeline_id(key)
        except ValueError as error:
            # Keeps "reserved, not yet supported" distinct from "invalid"
            raise type(error)(f"{where}: {error}") from None

        if not isinstance(entry, dict):
            raise ValueError(
                f"{where} must be a table that says where the pipeline is, "
                f"e.g. {_DEPENDENCY_EXAMPLE}."
            )
        unknown = sorted(set(entry) - set(DEPENDENCY_KEYS))
        if unknown:
            if all(isinstance(entry[name], dict) for name in unknown):
                # ftsfr.rates = {...} is TOML for a table inside a table
                hint = (
                    f" A key with a '/' or a '.' in it must be quoted, e.g. "
                    f'"{key}/{unknown[0]}" = {{ path = "..." }}.'
                )
            else:
                close = difflib.get_close_matches(unknown[0], DEPENDENCY_KEYS, n=1)
                hint = f" Did you mean {close[0]!r}?" if close else ""
            raise ValueError(
                f"{where} has an unknown key {unknown[0]!r}. An entry may "
                f"have: {', '.join(DEPENDENCY_KEYS)}.{hint}"
            )
        for name in DEPENDENCY_KEYS:
            value = entry.get(name)
            if name in entry and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{where}: '{name}' must be a non-empty string.")

        if "path" in entry and "git" in entry:
            raise ValueError(
                f"{where} has both 'path' and 'git'. A dependency comes from "
                f"one place: a directory, or a git repository."
            )
        if "git" in entry:
            from chartbook.gitcache import check_git_url, check_rev

            try:
                check_git_url(entry["git"])
                check_rev(entry.get("rev"))
            except ValueError as error:
                raise ValueError(f"{where}: {error}") from None
        by_id = "path" not in entry and "git" not in entry
        if not by_id:
            for name in ("id", "commit", "repository"):
                if name in entry:
                    raise ValueError(
                        f"{where} has '{name}' beside a '{'path' if 'path' in entry else 'git'}'. "
                        f"'{name}' belongs to a dependency named by its ID alone and pinned from "
                        f"the store; a path or git dependency is the pipeline its folder or "
                        f"repository holds."
                    )
        if by_id and "rev" in entry:
            # A branch or tag of its repository: pin asks the repository what it
            # means, and takes the newest snapshot at or before that commit
            from chartbook.gitcache import check_rev

            try:
                check_rev(entry["rev"])
            except ValueError as error:
                raise ValueError(f"{where}: {error}") from None
            if "commit" in entry:
                raise ValueError(
                    f"{where} has both 'rev' and 'commit'. A commit is one place in its "
                    f"history and a rev names one: give one of them."
                )
        if by_id:
            try:
                validate_pipeline_id(entry.get("id", key))
            except ValueError as error:
                raise ValueError(f"{where}: its id {entry.get('id')!r}: {error}") from None
            if "commit" in entry and not _COMMIT_START.fullmatch(entry["commit"]):
                raise ValueError(
                    f"{where}: commit {entry['commit']!r} is not the start of a commit: "
                    f"7 to 40 of 0-9 and a-f, as `git log` shows it."
                )
            if "repository" in entry:
                from chartbook.identity import remote_to_web_url, web_link

                if not web_link(remote_to_web_url(entry["repository"])):
                    raise ValueError(
                        f"{where}: repository {entry['repository']!r} is not a repository's address: "
                        f"its web address or its git remote, e.g. https://github.com/acme/rates."
                    )
        if "path" in entry and "rev" in entry:
            raise ValueError(
                f"{where} has a 'rev' beside a 'path'. A revision belongs to "
                f"a git dependency; a path dependency is whatever is in that "
                f"directory."
            )

        entry = dict(entry)
        if "path" in entry:
            entry["_resolved_path"] = (Path(base_dir) / entry["path"]).resolve()
        if by_id:
            entry["_store"] = entry.get("id", key)
            if "repository" in entry:
                from chartbook.identity import remote_to_web_url, web_link

                entry["_repository"] = web_link(remote_to_web_url(entry["repository"]))
        validated[key] = entry
    return validated


def dependency_line(key: str, entry: dict) -> str:
    """One ``[dependencies]`` entry as a line of TOML: ``"acme/rates" = { commit = "3f2a9c1" }``."""
    inner = ", ".join(f"{name} = {json.dumps(value)}" for name, value in entry.items())
    return f"{json.dumps(key)} = {{ {inner} }}" if inner else f"{json.dumps(key)} = {{}}"


def with_dependency(text: str, key: str, entry: dict) -> str:
    """A manifest's text with one dependency added to ``[dependencies]``, all else as it was.

    The file is edited as text, not written again from what it parses to,
    so its comments, order, spacing and line endings stay. The line goes
    just under the ``[dependencies]`` header; with no such table, one is
    added at the end. Each place is tried, and an edit is kept only if the
    result parses to the manifest as it was with that one entry added, so a
    line that looks like the header inside a string is never written into.

    :param text: The ``chartbook.toml`` as it is.
    :param key: The dependency's key.
    :param entry: Its table, of strings: ``{}``, ``{"id": ...}``,
        ``{"commit": ...}``.
    :raises ValueError: If the key is in it already, or no edit gives the
        manifest with the entry added (the message has the line to add).
    """
    raw = tomli.loads(text)
    dependencies = raw.get("dependencies")
    if isinstance(dependencies, dict) and key in dependencies:
        raise ValueError(f"[dependencies] has {key!r} already.")
    line = dependency_line(key, entry)
    newline = "\r\n" if "\r\n" in text else "\n"
    wanted = {**raw, "dependencies": {**(dependencies if isinstance(dependencies, dict) else {}), key: dict(entry)}}

    def gives_it(candidate: str) -> bool:
        try:
            got = tomli.loads(candidate)
        except tomli.TOMLDecodeError:
            return False
        # As text, so that nan, which equals nothing, compares; keys in any order
        return json.dumps(got, sort_keys=True, default=str) == json.dumps(wanted, sort_keys=True, default=str)

    for header in re.finditer(r"(?m)^[ \t]*\[[ \t]*dependencies[ \t]*\][ \t]*(#[^\r\n]*)?\r?$", text):
        end = header.end()
        if text[end - 1:end] == "\r":
            end -= 1
        candidate = text[:end] + newline + line + text[end:]
        if gives_it(candidate):
            return candidate
    joined = text if not text or text.endswith(("\n", "\r")) else text + newline
    candidate = joined + (newline if joined else "") + "[dependencies]" + newline + line + newline
    if gives_it(candidate):
        return candidate
    raise ValueError(
        f"[dependencies] in this chartbook.toml is written in a form a line cannot be added to "
        f"(inline, quoted, or as dotted keys). Add the entry there yourself: {line}"
    )


#: What a label may point at: the start of a model's content hash, at least
#: the twelve digits a version is shown with, with or without the algorithm
#: in front. A label is in a committed file and is read for years, so it is
#: not allowed to be shorter than the name it was copied from.
VERSION_PATTERN = re.compile(r"^(sha256:)?[0-9a-f]{12,64}$")

#: A label that could be taken for the start of a hash: four or more hex
#: digits and nothing else, which is what a typed version may be.
_LOOKS_LIKE_A_VERSION = re.compile(r"^[0-9a-f]{4,64}$")


def validate_aliases(aliases, where: str) -> dict:
    """Validate a model's labels: ``[models.x.aliases]``.

    A label is a name that points at a version of the model, and promoting
    a model is changing one line::

        [models.rate_forecaster.aliases]
        champion = "7f3a9c2e41b0"
        challenger = "b2c91d0a77f3"

    A version is named by the start of its content hash, which is the same
    on every machine and every branch. Whether the version a label points
    at is on this machine is for ``chartbook check`` to say.

    :param aliases: The table as parsed.
    :param where: The model's table, for messages: ``[models.x]``.
    :returns: The labels and what they point at.
    :raises ValueError: If it is not a table, a label is not a name or
        looks like a version, or a value is not a version.
    """
    if not isinstance(aliases, dict):
        raise ValueError(
            f"{where}: 'aliases' must be a table of labels, e.g. "
            f'[{where.strip("[]")}.aliases] with champion = "7f3a9c2e41b0".'
        )
    for label, version in aliases.items():
        if not ID_COMPONENT_PATTERN.match(label):
            raise ValueError(
                f"{where}: {label!r} is not a legal label. A label is written "
                f"after '@' in a reference, so it must match [A-Za-z0-9._-]+."
            )
        if _LOOKS_LIKE_A_VERSION.match(label):
            raise ValueError(
                f"{where}: the label {label!r} looks like a version. A label is "
                f"a name, such as champion, so that the two cannot be confused."
            )
        if not isinstance(version, str) or not VERSION_PATTERN.match(version):
            raise ValueError(
                f"{where}: the label {label!r} must point at a version: the "
                f"start of the model's content hash, at least 12 digits of it, "
                f'e.g. {label} = "7f3a9c2e41b0". `chartbook snapshot` prints a new '
                f"version's name."
            )
    return dict(aliases)


def validate_models(manifest: dict, base_dir: Path) -> dict:
    """Validate a pipeline's ``[models.<id>]`` tables.

    A model is a file, or a directory of files, that the pipeline produces:
    ``path`` says where. ``trained_on`` lists the dataframes it was trained
    on, as references; ``metrics_path`` names a JSON file of scores; and
    ``docs_path`` or ``docs`` is its write-up. See
    ``docs_src/design/models.md``.

    A dataframe in ``trained_on`` may belong to this pipeline
    (``"treasury_rates"``) or to another (``"ftsfr/rates:treasury_rates"``).
    One of this pipeline's must be declared here. Another pipeline's must be
    in a pipeline that ``[dependencies]`` declares. Whether that pipeline
    has such a dataframe is for ``chartbook check`` to say.

    Each entry gains ``_resolved_path`` and ``_trained_on``, the parsed
    references to the dataframes it was trained on.

    :param manifest: The pipeline's manifest, with ``dataframes`` and
        ``dependencies`` loaded.
    :param base_dir: The pipeline's root directory.
    :returns: The model tables by key; empty if the pipeline declares none.
    :raises ValueError: If a table is malformed, a key is not a legal name,
        or ``trained_on`` names something that is not a dataframe, a
        dataframe of this pipeline that it does not declare, or a pipeline
        that ``[dependencies]`` does not declare.
    """
    from chartbook.refs import KindMismatchError
    from chartbook.resolve import (
        PipelineNotFoundError,
        locate_pipeline,
        parse_declared_ref,
    )

    models = manifest.get("models")
    if models is None:
        return {}
    if not isinstance(models, dict):
        raise ValueError(
            "[models] must be a table of tables, one per model, e.g. "
            "[models.rate_forecaster]."
        )
    dataframes = manifest.get("dataframes") or {}
    dependencies = manifest.get("dependencies") or {}
    for model_id, entry in models.items():
        where = f"[models.{model_id}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be a table with at least a 'path'.")
        if not ID_COMPONENT_PATTERN.match(model_id):
            raise ValueError(
                f"{where}: {model_id!r} is not a legal model key. A key becomes "
                f"part of an address ('model/<key>'), so it must match "
                f"[A-Za-z0-9._-]+."
            )
        declared_path = entry.get("path")
        if not isinstance(declared_path, str) or not declared_path.strip():
            raise ValueError(
                f"{where} has no 'path'. Say where the model file, or the "
                f'directory of its files, is: path = "./_models/{model_id}.joblib".'
            )
        entry["_resolved_path"] = Path(base_dir) / declared_path

        for key in ("metrics_path", "docs_path"):
            value = entry.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{where}: '{key}' must be a path.")
        if entry.get("docs") and entry.get("docs_path"):
            raise ValueError(
                f"{where} has both docs_path and docs. Only one is allowed."
            )
        if "tags" in entry:
            entry["tags"] = normalize_tags(entry["tags"])
        if "aliases" in entry:
            entry["aliases"] = validate_aliases(entry["aliases"], where)

        trained_on = entry.get("trained_on", [])
        if not isinstance(trained_on, list) or not all(
            isinstance(item, str) for item in trained_on
        ):
            raise ValueError(
                f"{where}: 'trained_on' must be a list of dataframes, e.g. "
                f'trained_on = ["treasury_rates"].'
            )
        references = []
        for text in trained_on:
            try:
                reference = parse_declared_ref(text, kind="dataframe")
            except KindMismatchError as error:
                raise ValueError(
                    f"{where}: trained_on: {error} A model is trained on dataframes."
                ) from None
            except ValueError as error:
                # Keeps "reserved, not yet supported" distinct from "invalid"
                raise type(error)(f"{where}: trained_on: {error}") from None
            if reference.is_local and reference.name not in dataframes:
                declared = ", ".join(sorted(dataframes)) or "(none)"
                raise ValueError(
                    f"{where}: trained_on names the dataframe {reference.name!r}, "
                    f"which this pipeline does not declare. Its dataframes are: "
                    f"{declared}. To name another pipeline's dataframe, write "
                    f"'<pipeline>:{reference.name}'."
                )
            if not reference.is_local:
                try:
                    locate_pipeline(reference.pipeline_id, dependencies=dependencies)
                except PipelineNotFoundError:
                    raise ValueError(
                        f"{where}: trained_on names {str(reference)!r}, in the "
                        f"pipeline {reference.pipeline_id!r}, which "
                        f"[dependencies] does not declare. Say where that "
                        f'pipeline is: add "{reference.pipeline_id}" = '
                        f'{{ path = "../{reference.pipeline}" }} under '
                        f"[dependencies]."
                    ) from None
                except KeyError as error:
                    # A bare name that fits two dependencies
                    raise ValueError(
                        f"{where}: trained_on: {error.args[0]}"
                    ) from None
            references.append(reference)
        entry["_trained_on"] = references
    return models


def validate_files(manifest: dict, base_dir: Path) -> dict:
    """Validate a pipeline's ``[files.<id>]`` tables.

    A files asset is a file, a folder or a glob of files that the pipeline
    keeps whatever is inside: ``path`` says where. The rest is what a
    dataframe has to say about where it came from and who may use it
    (``description``, ``docs_path`` or ``docs``, ``sources``,
    ``providers``, ``license``, ``restrictions``, ``tags``, ``keep``), and
    fields of the pipeline's own. See :mod:`chartbook.files`.

    Each entry gains ``_resolved_path``, the path joined to the pipeline's
    folder, and ``_is_glob``.

    :param manifest: The pipeline's manifest, with its fields checked
        (:func:`_check_entity_fields`).
    :param base_dir: The pipeline's root directory.
    :returns: The files tables by key; empty if the pipeline declares none.
    :raises ValueError: If an entry has no ``path``, or has both ``docs``
        and ``docs_path``.
    """
    entries = manifest.get("files")
    if entries is None:
        return {}
    for key, entry in entries.items():
        where = f"{Path(base_dir) / 'chartbook.toml'}: [files.{key}]"
        declared_path = entry.get("path")
        if not isinstance(declared_path, str) or not declared_path.strip():
            raise ValueError(
                f"{where} has no 'path'. Say where its files are: a file, a folder, or a glob, "
                f'such as path = "./_data/{key}/*.jsonl.gz".'
            )
        if entry.get("docs") and entry.get("docs_path"):
            raise ValueError(f"{where} has both docs_path and docs. Only one is allowed.")
        entry["_resolved_path"] = Path(os.path.normpath(Path(base_dir) / declared_path))
        entry["_is_glob"] = is_glob_pattern(declared_path)
        if "tags" in entry:
            entry["tags"] = normalize_tags(entry["tags"])
    return entries


def _warn_unknown_project_keys(project_raw: dict, source: str) -> None:
    """Warn about unrecognized keys in the [project] table.

    This is what prevents silent field-name drift (the v1 ``runs_on``
    problem) from recurring.
    """
    for key in project_raw:
        if key not in PROJECT_DEFAULTS:
            suggestion = difflib.get_close_matches(key, PROJECT_DEFAULTS.keys(), n=1)
            hint = f" Did you mean {suggestion[0]!r}?" if suggestion else ""
            warnings.warn(
                f"{source}: unknown key {key!r} in [project] is ignored.{hint}",
                UserWarning,
                stacklevel=2,
            )


def _resolve_project(raw_manifest: dict, base_dir: Path, project_type: str) -> dict:
    """Build the resolved [project] dict with all defaults filled.

    :param raw_manifest: The raw parsed manifest.
    :param base_dir: The project's root directory.
    :param project_type: The resolved project type.
    :returns: A dict with every PROJECT_DEFAULTS key present and resolved.
    """
    source = str(Path(base_dir) / "chartbook.toml")
    project_raw = raw_manifest.get("project", {})
    _warn_unknown_project_keys(project_raw, source)

    # Each field as its default's type: a path or a name is a string, a
    # list of people is a list. What is not is refused here, by name, and
    # not where a page would read it
    for key, default in PROJECT_DEFAULTS.items():
        if key not in project_raw or key == "type":  # type is checked by resolve_project_type
            continue
        value = project_raw[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(
                    f"{source}: [project]: {key} = {value!r} is {_toml_word(value)}, and {key} is "
                    f"true or false. Write {key} = true."
                )
        elif isinstance(default, list):
            _require_list_of_strings(value, f"{source}: [project]", key, _PROJECT_EXAMPLES[key])
        elif isinstance(default, str):
            _require_string(value, f"{source}: [project]", key, _PROJECT_EXAMPLES.get(key, "..."))

    project = dict(PROJECT_DEFAULTS)
    project.update({k: v for k, v in project_raw.items() if k in PROJECT_DEFAULTS})
    project["type"] = project_type
    if project["writer"] not in WRITERS:
        raise ValueError(
            f"{source}: [project] writer = {project['writer']!r} names a site tool ChartBook does not write "
            f"for; the writers are: {', '.join(WRITERS)}."
        )

    if not project["name"]:
        project["name"] = Path(base_dir).name
    if not project["copyright"]:
        project["copyright"] = str(datetime.now().year)
    if not project["maintainer"] and project["contributors"]:
        project["maintainer"] = project["contributors"][0]

    project["id"] = derive_pipeline_id(project_raw, base_dir)

    if not project["repo_url"]:
        # The repository's own remote, as a web address with any credentials
        # removed. Looked up once per directory, and already needed above.
        project["repo_url"] = remote_to_web_url(get_git_remote_url(base_dir))

    if not project["site_url"]:
        webpage_path = Path(base_dir) / "docs" / "index.html"
        project["site_url"] = f"file://{webpage_path.as_posix()}"

    return project


#: What a right value of each ``[project]`` field looks like, for a message
#: that refuses a wrong one.
_PROJECT_EXAMPLES = {
    "id": "acme/rates",
    "name": "Treasury Rates",
    "description": "Daily Treasury yields",
    "maintainer": "Alice Smith",
    "contributors": '["Alice Smith", "Bob Jones"]',
    "repo_url": "https://github.com/acme/rates",
    "site_url": "https://acme.github.io/rates",
    "readme": "./README.md",
    "copyright": "2026",
    "logo": "./docs_src/logo.png",
    "favicon": "./docs_src/favicon.ico",
    "os_compatibility": '["Linux", "macOS", "Windows"]',
    "build": "doit",
    "requires_chartbook": ">=0.2.0",
    "site_dir": "./docs_src/site/",
    "writer": "sphinx",
}


def _resolve_site_dir(project: dict, base_dir: Path) -> None:
    """Resolve the custom site pages directory into ``project["_resolved_site_dir"]``.

    An explicit ``site_dir`` must exist; the default (``docs_src/site/``) is
    used only when present on disk.
    """
    site_dir_raw = project.get("site_dir", "")
    if site_dir_raw:
        site_dir_path = Path(base_dir) / site_dir_raw
        if not site_dir_path.is_dir():
            raise ValueError(
                f"site_dir '{site_dir_raw}' does not exist at {site_dir_path}"
            )
    else:
        site_dir_path = Path(base_dir) / DEFAULT_SITE_DIR
        if not site_dir_path.is_dir():
            project["_resolved_site_dir"] = None
            return

    if (site_dir_path / "cb").exists():
        raise ValueError(
            "site_dir contains a 'cb/' subdirectory which conflicts with "
            "the reserved chartbook namespace. Please rename or remove it."
        )
    project["_resolved_site_dir"] = str(site_dir_path.resolve())


#: The ``[project]`` keys that name a file or a folder of the pipeline.
_PROJECT_PATH_KEYS = ("readme", "site_dir", "logo", "favicon")


def _refuse_paths_outside(raw_manifest: dict, base_dir: Path) -> None:
    """In a build of files from a store, refuse a manifest that names anything outside its folder.

    A version laid out from a store has a manifest anyone who can write the
    store may have written; a build reads, hashes, copies and shows what it
    names. So every path it names, in ``[project]`` and in every asset
    table (``path`` and every ``*_path``), must be a plain path inside the
    folder (:func:`chartbook.snapshot.safe_relative`) and reach no file
    outside it through a link.

    :raises ValueError: Naming the first that is not.
    """
    from chartbook.hashing import escapes
    from chartbook.resolve import ASSET_TABLES
    from chartbook.snapshot import safe_relative

    source = base_dir / "chartbook.toml"
    named: list[tuple[str, object]] = []
    project = raw_manifest.get("project") or {}
    for key in _PROJECT_PATH_KEYS:
        if key in project:
            named.append((f"[project] {key}", project[key]))
    for table in ASSET_TABLES:
        for name, entry in (raw_manifest.get(table) or {}).items():
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if key == "path" or key.endswith("_path"):
                    named.append((f"[{table}.{name}] {key}", value))
    for where, value in named:
        if not isinstance(value, str) or not value.strip():
            continue
        if safe_relative(value) is None or escapes(base_dir / value, base_dir) is not None:
            raise ValueError(
                f"{source}: {where} = {value!r} is not a plain path inside the pipeline's folder, "
                f"and a build of files that are not your own (from a store, or a folder you have not "
                f"trusted) reads nothing outside the folder. `chartbook trust` in a folder trusts the "
                f"pipeline there."
            )


#: Each entity table and what one of its entries is.
_ENTITY_KINDS = (
    ("dataframes", "dataframe"),
    ("charts", "chart"),
    ("notebooks", "notebook"),
    ("notes", "note"),
    ("models", "model"),
    ("files", "files asset"),
)

#: The fields of an entity table's entry that are lists of strings.
_ENTITY_LIST_KEYS = {
    "dataframes": ("tags", "sources", "providers", "provider_links"),
    "charts": ("tags",),
    "notebooks": ("tags",),
    "notes": ("tags",),
    "models": ("tags",),
    "files": ("tags", "sources", "providers", "provider_links"),
}

#: A right value of each list field, for the message that refuses a wrong one.
_LIST_EXAMPLES = {
    "tags": '["Rates", "Treasury"]',
    "sources": '["FRED", "CRSP"]',
    "providers": '["Federal Reserve Board"]',
    "provider_links": '["https://fred.stlouisfed.org"]',
}

#: Where an entry's ``path`` usually is, by table, for the same messages.
_PATH_EXAMPLES = {
    "dataframes": "./_data/{key}.parquet",
    "charts": "./_output/{key}.html",
    "notebooks": "./_output/{key}.ipynb",
    "notes": "./docs_src/{key}.md",
    "files": "./_data/{key}/",
}

#: And where the other ``*_path`` fields point.
_OTHER_PATH_EXAMPLES = {
    "excel_path": "./_output/{key}.xlsx",
    "metrics_path": "./_output/{key}_metrics.json",
}


def _check_entity_fields(manifest: dict, source: str) -> None:
    """Refuse an entity table's field that is not of its type, before anything reads it.

    Each ``[charts.<id>]``, ``[dataframes.<id>]``, ``[notebooks.<id>]``,
    ``[notes.<id>]`` and ``[models.<id>]`` is a table. In it ``path``,
    every ``*_path`` and ``docs`` are strings, and ``tags`` (for a
    dataframe, ``sources``, ``providers`` and ``provider_links`` too) is a
    list of strings: a bare string is refused, not read as a list of one,
    since what reads the list would otherwise read the string's letters.
    ``keep`` is ``true`` or left out (``docs_src/design/keep.md``). A
    note has a ``path``, which is where its page comes from. A model's
    paths are :func:`validate_models`'s to check.

    :param manifest: The manifest, with its entity tables as parsed.
    :param source: The file, for the message.
    :raises ValueError: Naming the file, the table and the key, and
        saying what to write.
    """
    for table, kind in _ENTITY_KINDS:
        entries = manifest.get(table)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise ValueError(
                f"{source}: [{table}] must be a table of tables, one per {kind}, e.g. [{table}.<name>] "
                f"with a path = \"...\" under it; it is {_toml_word(entries)}."
            )
        for key, entry in entries.items():
            where = f"{source}: [{table}.{key}]"
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{where} must be a table of the {kind}'s fields, e.g. [{table}.{key}] with a "
                    f"path = \"...\" under it; it is {_toml_word(entry)}."
                )
            if table != "models":
                for field, value in entry.items():
                    if field == "path":
                        _require_string(value, where, field, _PATH_EXAMPLES[table].format(key=key))
                    elif field == "docs_path":
                        _require_string(value, where, field, f"./docs_src/{table}/{key}.md")
                    elif field.endswith("_path"):
                        _require_string(value, where, field, _OTHER_PATH_EXAMPLES.get(field, "./_output/{key}").format(key=key))
            if "docs" in entry:
                _require_string(entry["docs"], where, "docs", "The write-up, as Markdown.")
            if "keep" in entry and entry["keep"] is not True:
                # Every version of the asset is kept in the store, or the key
                # is left out: `false` says nothing `keep` can say
                raise ValueError(
                    f"{where}: keep = {entry['keep']!r} is {_toml_word(entry['keep'])}, and keep is true, or "
                    f"left out. Write keep = true to keep every version of the {kind} in the store, "
                    f"or take the key out."
                )
            for field in _ENTITY_LIST_KEYS[table]:
                if field in entry:
                    _require_list_of_strings(entry[field], where, field, _LIST_EXAMPLES[field])
            if table == "notes" and not (isinstance(entry.get("path"), str) and entry["path"].strip()):
                raise ValueError(
                    f"{where} has no 'path'. Say where the note's markdown file is: "
                    f'path = "./docs_src/{key}.md".'
                )


def _load_pipeline_manifest(raw_manifest):
    """Process a raw pipeline manifest into the internal manifest shape.

    :param raw_manifest: The raw manifest dictionary loaded from chartbook.toml
        (with ``base_dir`` already attached).
    :returns: The processed manifest dictionary with resolved metadata.
    :rtype: dict
    """
    base_dir = raw_manifest["base_dir"]
    from chartbook.config import untrusted_source

    if untrusted_source():
        _refuse_paths_outside(raw_manifest, Path(base_dir))
    manifest = raw_manifest.copy()

    manifest["project"] = _resolve_project(raw_manifest, base_dir, "pipeline")
    _resolve_site_dir(manifest["project"], base_dir)
    if "policy" in raw_manifest:
        # A pipeline's own policy: what it holds itself to when it is
        # checked or built alone. Inside a catalog, the catalog's applies.
        manifest["policy"] = _resolve_policy(
            raw_manifest, str(Path(base_dir) / "chartbook.toml")
        )

    # Ensure optional sections have defaults
    manifest.setdefault("charts", {})
    manifest.setdefault("dataframes", {})
    manifest.setdefault("notebooks", {})
    manifest.setdefault("models", {})

    # Every field as its type, before anything below reads one
    _check_entity_fields(manifest, str(Path(base_dir) / "chartbook.toml"))

    # A key becomes part of an address, so the index can name the asset.
    # Models are checked in validate_models; the other kinds here, so that
    # the manifest and the index describe the same set of assets
    for table, kind in (
        ("dataframes", "dataframe"), ("charts", "chart"), ("notebooks", "notebook"), ("notes", "note"), ("files", "files asset")
    ):
        for key in manifest.get(table) or {}:
            if not ID_COMPONENT_PATTERN.match(str(key)):
                raise ValueError(
                    f"{Path(base_dir) / 'chartbook.toml'}: [{table}.{key}]: {key!r} is not a legal "
                    f"{kind} key. A key becomes part of an address, so it must match [A-Za-z0-9._-]+."
                )

    # Infer notebook name from the notebook's H1 heading when not explicitly set
    for notebook_id in manifest.get("notebooks", {}):
        nb_manifest = manifest["notebooks"][notebook_id]
        if "name" not in nb_manifest:
            nb_path = base_dir / nb_manifest.get("path", "")
            if nb_path.exists():
                title = extract_notebook_title(nb_path)
                if title:
                    nb_manifest["name"] = title

    source_last_modified_date = find_latest_source_modification(base_dir)
    manifest["source_last_modified_date"] = source_last_modified_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    manifest["pipeline_base_dir"] = base_dir.resolve().as_posix()

    # Process notes if they exist
    if "notes" in manifest:
        for note_id in manifest["notes"]:
            note_manifest = manifest["notes"][note_id]
            note_manifest["_resolved_path"] = Path(base_dir) / note_manifest["path"]

    try:
        manifest["sources"] = validate_sources(raw_manifest.get("sources"), Path(base_dir))
    except ValueError as error:
        raise ValueError(f"{Path(base_dir) / 'chartbook.toml'}: {error}") from None
    if not manifest["sources"] and "sources" not in raw_manifest:
        del manifest["sources"]

    # Create a mapping of dataframe id to linked chart ids
    if "dataframes" in manifest:
        dataframe_to_charts = {
            dataframe_id: [] for dataframe_id in manifest["dataframes"]
        }

        for dataframe_id in manifest["dataframes"]:
            dataframe_manifest = manifest["dataframes"][dataframe_id]
            try:
                dataframe_manifest["_location_kind"] = validate_dataframe_location(
                    dataframe_manifest, dataframe_id, manifest.get("sources") or {}
                )
                # The file's format and the reader's options, as they will be read
                formats.check_entry(dataframe_manifest, f"[dataframes.{dataframe_id}]")
            except ValueError as error:
                raise ValueError(f"{Path(base_dir) / 'chartbook.toml'}: {error}") from None
            if dataframe_manifest["_location_kind"] != "file":
                # The source it lives in, for the index and the page
                dataframe_manifest["_source"] = manifest["sources"][dataframe_manifest["source"]]
            raw_parquet_path = dataframe_manifest.get("path", "")
            dataframe_manifest["_is_glob"] = is_glob_pattern(raw_parquet_path)
            # Normalized, as the index and the resolver write it: a declared
            # `../shared/x.parquet` is shown as the folder it names
            dataframe_manifest["_resolved_path"] = (
                Path(os.path.normpath(Path(base_dir) / raw_parquet_path)) if raw_parquet_path else None
            )
            if "tags" in dataframe_manifest:
                dataframe_manifest["tags"] = normalize_tags(dataframe_manifest["tags"])
            doc_mode, doc_value = validate_doc_fields(
                dataframe_manifest, "dataframe", dataframe_id
            )
            dataframe_manifest["_doc_mode"] = doc_mode
            dataframe_manifest["_doc_value"] = doc_value
            validate_series(dataframe_manifest, dataframe_id)

        if "charts" in manifest:
            for chart_id in manifest["charts"]:
                chart_manifest = manifest["charts"][chart_id]
                if "tags" in chart_manifest:
                    chart_manifest["tags"] = normalize_tags(chart_manifest["tags"])
                doc_mode, doc_value = validate_doc_fields(
                    chart_manifest, "chart", chart_id
                )
                chart_manifest["_doc_mode"] = doc_mode
                chart_manifest["_doc_value"] = doc_value

                dataframe_id = chart_manifest.get("dataframe")
                if not dataframe_id:
                    raise ValueError(
                        f"Chart '{chart_id}' has no 'dataframe' key linking it "
                        f"to a dataframe in the [dataframes] section."
                    )
                if dataframe_id in dataframe_to_charts:
                    dataframe_to_charts[dataframe_id].append(chart_id)
                else:
                    raise ValueError(
                        f"Dataframe {dataframe_id} not found in dataframes section"
                    )

            for dataframe_id, chart_ids in dataframe_to_charts.items():
                manifest["dataframes"][dataframe_id]["linked_charts"] = sorted(chart_ids)

    try:
        scripts = read_scripts(raw_manifest)
    except ValueError as error:
        raise ValueError(f"{Path(base_dir) / 'chartbook.toml'}: {error}") from None
    if scripts or "scripts" in raw_manifest:
        manifest["scripts"] = scripts
    if BUILD_SCRIPT in scripts:
        # One build script, wherever it was written: pages and the policy
        # read it from the project table
        manifest["project"]["build"] = scripts[BUILD_SCRIPT]

    # Before the models, which may be trained on a dependency's data
    if "dependencies" in manifest:
        try:
            manifest["dependencies"] = validate_dependencies(
                manifest["dependencies"], base_dir
            )
        except ValueError as error:
            source = Path(base_dir) / "chartbook.toml"
            raise type(error)(f"{source}: {error}") from None

    validate_models(manifest, base_dir)
    validate_files(manifest, base_dir)

    return manifest


def _resolve_policy(raw_manifest: dict, source: str) -> dict:
    """Resolve a catalog's [policy] section, filling defaults.

    :param raw_manifest: The raw parsed catalog manifest.
    :param source: Label used in error messages.
    :returns: Dict with ``mode`` and per-object-type ``required`` field lists.
    """
    from chartbook.diagnostics import DEFAULT_REQUIRED_FIELDS

    policy_raw = raw_manifest.get("policy", {})
    if not isinstance(policy_raw, dict):
        raise ValueError(
            f"{source}: [policy] must be a table, with `mode` and `[policy.required]` "
            f"under it; it is {policy_raw!r}."
        )
    mode = policy_raw.get("mode", "warn")
    if mode not in ("warn", "strict"):
        raise ValueError(
            f"{source}: invalid policy.mode {mode!r}. Must be 'warn' or 'strict'."
        )

    required_raw = policy_raw.get("required", {})
    if not isinstance(required_raw, dict):
        raise ValueError(
            f"{source}: policy.required must be a table, `[policy.required]`, of "
            f"field lists by kind; it is {required_raw!r}."
        )
    for key, fields in required_raw.items():
        if key not in DEFAULT_REQUIRED_FIELDS:
            raise ValueError(
                f"{source}: unknown policy.required key {key!r}. "
                f"Allowed keys: {sorted(DEFAULT_REQUIRED_FIELDS)}."
            )
        # A list of field names, and nothing else: a string would be read
        # as its letters, a table as its keys
        _require_list_of_strings(fields, f"{source}: [policy.required]", key, '["name", "description"]')
    required = {
        object_type: list(required_raw.get(object_type, default_fields))
        for object_type, default_fields in DEFAULT_REQUIRED_FIELDS.items()
    }
    return {"mode": mode, "required": required}


#: Keys inside [pipelines] that configure the registry itself rather than
#: naming a pipeline entry. A pipeline cannot use these as a bare ID.
RESERVED_PIPELINES_KEYS = ("members", "exclude", "disabled")


def _require_string_list(value, key: str, source: str) -> list:
    """Validate that a reserved [pipelines] key holds an array of strings."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(
            f"{source}: pipelines.{key} must be an array of strings, "
            f"e.g. {key} = [\"../my_repos/*\"]. Got: {value!r}"
        )
    return value


def _expand_exclude_patterns(patterns: list, base_dir: Path) -> set:
    """Resolve pipelines.exclude patterns to a set of absolute paths."""
    import glob as glob_module

    excluded = set()
    for pattern in patterns:
        expanded = str(Path(base_dir) / pattern)
        matches = glob_module.glob(expanded)
        if matches:
            excluded.update(Path(m).resolve() for m in matches)
        else:
            # A non-matching exclude is harmless; keep the literal path so
            # excluding a not-yet-created directory still works.
            excluded.add(Path(expanded).resolve())
    return excluded


def _discover_member_pipelines(
    members: list,
    exclude: list,
    explicit_entries: dict,
    base_dir: Path,
    source: str,
) -> dict:
    """Expand pipelines.members path patterns into pipeline entries.

    Each discovered directory must hold a v2 pipeline chartbook.toml; its
    catalog key is the derived scoped ID. Glob patterns silently skip
    directories that are not chartbook pipelines (and any catalogs they
    match); a non-glob member path must point at a valid pipeline.

    :returns: Mapping of derived pipeline ID -> entry dict, with a
        ``_member_source`` describing where each came from (for errors).
    Two members that are checkouts of one repository at the same place in
    it (a worktree, a second clone) are one pipeline: the main worktree's
    is listed, else the one found first, and a warning names the other.
    One that is a checkout of an explicit entry's repository is left to
    the entry, with a warning.

    :raises ValueError: With fix-it suggestions, on broken explicit paths,
        v1-format members, or two members deriving the same ID that are
        not one pipeline.
    """
    import glob as glob_module

    from chartbook.identity import checkout_of, derive_pipeline_id, same_pipeline_checked_out

    excluded_paths = _expand_exclude_patterns(exclude, base_dir)
    catalog_dir = Path(base_dir).resolve()

    # Map resolved path -> explicit entry key, so explicit entries override
    # the member that discovered the same directory
    explicit_paths = {}
    for key, entry in explicit_entries.items():
        entry_path = entry.get("path")
        if isinstance(entry_path, str):
            explicit_paths[catalog_entry_dir(base_dir, Path(entry_path))] = key

    discovered = {}
    member_dirs = {}  # the folder of each discovered pipeline, by its ID
    seen_dirs = set()
    for pattern in members:
        is_glob = is_glob_pattern(pattern)
        expanded = str(Path(base_dir) / pattern)
        matches = sorted(glob_module.glob(expanded))
        match_dirs = [Path(m).resolve() for m in matches if Path(m).is_dir()]

        if not match_dirs:
            if is_glob:
                warnings.warn(
                    f"{source}: pipelines.members pattern {pattern!r} matched "
                    f"no directories (searched {expanded}).",
                    UserWarning,
                    stacklevel=2,
                )
                continue
            raise ValueError(
                f"{source}: pipelines.members entry {pattern!r} does not exist "
                f"(resolved to {expanded}).\n"
                f"To fix, do one of:\n"
                f"  - check the path is spelled correctly relative to {catalog_dir}\n"
                f"  - remove {pattern!r} from pipelines.members"
            )

        for member_dir in match_dirs:
            if member_dir in seen_dirs or member_dir in excluded_paths:
                continue
            if member_dir == catalog_dir or member_dir in explicit_paths:
                continue
            seen_dirs.add(member_dir)

            member_toml = member_dir / "chartbook.toml"
            if not member_toml.is_file():
                if is_glob:
                    continue  # not a chartbook project; globs just pass it by
                raise ValueError(
                    f"{source}: pipelines.members entry {pattern!r} has no "
                    f"chartbook.toml (looked in {member_dir}).\n"
                    f"To fix, do one of:\n"
                    f"  - create a chartbook.toml there (an empty file is a valid pipeline)\n"
                    f"  - remove {pattern!r} from pipelines.members"
                )

            try:
                member_raw = _parse_toml_file(member_toml)
            except ValueError as error:
                raise ValueError(f"{source}: catalog member {error}") from None

            if detect_v1_format(member_raw):
                raise ValueError(
                    f"{source}: catalog member {member_dir} uses the old v1 "
                    f"chartbook.toml format.\n"
                    f"To fix, do one of:\n"
                    f"  - migrate it: python scripts/migrate_toml_v2.py {member_dir}\n"
                    f"    (script lives in the chartbook repo)\n"
                    f"  - exclude it from this catalog: add "
                    f"\"{pattern if not is_glob else member_dir}\" to pipelines.exclude"
                )

            try:
                member_type = resolve_project_type(member_raw, source=str(member_toml))
            except RequiresChartbookError as error:
                member = derive_pipeline_id(
                    member_raw.get("project") if isinstance(member_raw.get("project"), dict) else {}, member_dir
                )
                raise RequiresChartbookError(
                    f"{source}: catalog member {error}\nTo build the catalog without it until then: "
                    f"`chartbook catalog disable {member}`, or add {member!r} to pipelines.disabled."
                ) from None
            if member_type != "pipeline":
                if is_glob:
                    continue  # catalogs matched by a glob are just skipped
                raise ValueError(
                    f"{source}: pipelines.members entry {pattern!r} points at "
                    f"{member_dir}, which is a catalog, not a pipeline.\n"
                    f"To fix: remove it from pipelines.members (catalogs cannot "
                    f"nest inside catalogs)."
                )

            member_id = derive_pipeline_id(member_raw.get("project", {}), member_dir)
            member_source = f"members pattern {pattern!r}"

            if member_id in discovered:
                other = discovered[member_id]
                # Two checkouts of one repository (a worktree, a second
                # clone) are one pipeline, and the catalog shows it once:
                # from the main worktree, else the one found first
                theirs, mine = checkout_of(member_dirs[member_id]), checkout_of(member_dir)
                if same_pipeline_checked_out(theirs, mine):
                    shown, passed = member_dirs[member_id], member_dir
                    if mine.main and not theirs.main:
                        shown, passed = passed, shown
                    warnings.warn(
                        f"{source}: catalog members {shown} and {passed} are checkouts of one "
                        f"repository, so one pipeline, {member_id!r}: the catalog shows {shown}, and "
                        f"not {passed}. To show {passed} instead, exclude {shown}:  [pipelines] "
                        f"exclude = [\"{shown}\"]; to show both, give one its own [project] id.",
                        UserWarning,
                        stacklevel=2,
                    )
                    if shown != member_dir:
                        continue
                else:
                    raise ValueError(
                        f"{source}: two catalog members resolve to the same pipeline "
                        f"ID {member_id!r}:\n"
                        f"  - {other['path']} (from {other['_member_source']})\n"
                        f"  - {member_dir} (from {member_source})\n"
                        f"To fix, do one of:\n"
                        f"  - give one repo a distinct explicit ID in its own "
                        f"chartbook.toml:  [project] id = \"myscope/{member_id.rsplit('/', 1)[-1]}\"\n"
                        f"  - exclude one path in this catalog:  [pipelines] "
                        f"exclude = [\"{member_dir}\"]"
                    )
            # An entry with no path names a pipeline shown from the store: the
            # folder found here is that pipeline, and fills the entry in
            if member_id in explicit_entries and explicit_entries[member_id].get("path") is not None:
                try:
                    named = catalog_entry_dir(base_dir, resolve_platform_path(explicit_entries[member_id]["path"]))
                except (ValueError, TypeError):
                    named = None
                if named is not None and same_pipeline_checked_out(checkout_of(named), checkout_of(member_dir)):
                    # Another checkout of the explicit entry's repository: the entry wins
                    warnings.warn(
                        f"{source}: catalog member {member_dir} (from {member_source}) is another "
                        f"checkout of the repository of [pipelines.\"{member_id}\"], at {named}, so the "
                        f"same pipeline: the catalog shows the entry's. To show both, give one its own "
                        f"[project] id.",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                raise ValueError(
                    f"{source}: catalog member {member_dir} (from {member_source}) "
                    f"derives the ID {member_id!r}, which is already declared as an "
                    f"explicit [pipelines] entry pointing elsewhere.\n"
                    f"To fix, do one of:\n"
                    f"  - point the explicit entry at this directory (then the "
                    f"explicit entry wins)\n"
                    f"  - exclude this path:  [pipelines] exclude = [\"{member_dir}\"]\n"
                    f"  - give the repo a distinct ID in its own chartbook.toml"
                )

            try:
                rel_path = Path(os.path.relpath(member_dir, catalog_dir)).as_posix()
            except ValueError:
                rel_path = Path(member_dir).as_posix()
            discovered[member_id] = {"path": rel_path, "_member_source": member_source}
            member_dirs[member_id] = member_dir

    return discovered


def _apply_disabled_list(entries: dict, disabled_ids: list, source: str) -> None:
    """Remove entries named in pipelines.disabled, warning on unknown IDs."""
    for disabled_id in disabled_ids:
        if disabled_id in entries:
            del entries[disabled_id]
        else:
            suggestion = difflib.get_close_matches(disabled_id, entries.keys(), n=1)
            hint = f" Did you mean {suggestion[0]!r}?" if suggestion else ""
            warnings.warn(
                f"{source}: pipelines.disabled entry {disabled_id!r} does not "
                f"match any pipeline in this catalog.{hint}",
                UserWarning,
                stacklevel=2,
            )


#: What a [pipelines] entry may say: where the pipeline's folder is, and
#: whether the catalog leaves it out. With no path, the catalog shows the
#: pipeline from its snapshots in the store.
PIPELINES_ENTRY_KEYS = ("path", "disabled")


def _check_pipelines_entry(pipeline_id: str, entry: object, source: str) -> dict:
    """A [pipelines] entry as a table of the keys it may have, or an error naming what is wrong.

    A key it may not have is an error, not ignored: an entry with no
    ``path`` means a pipeline shown from the store, so ``pth = "../rates"``
    would otherwise quietly become one.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"{source}: [pipelines] \"{pipeline_id}\" is {entry!r}. An entry is the "
            f"path to the pipeline's folder, a table such as {{ path = \"../rates\" }}, "
            f"or {{}} for a pipeline the catalog shows from the store."
        )
    unknown = sorted(set(entry) - set(PIPELINES_ENTRY_KEYS))
    if unknown:
        hints = [difflib.get_close_matches(key, PIPELINES_ENTRY_KEYS, n=1) for key in unknown]
        hint = "".join(f" Did you mean {match[0]!r} for {key!r}?" for key, match in zip(unknown, hints) if match)
        raise ValueError(
            f"{source}: [pipelines] \"{pipeline_id}\" has {', '.join(repr(k) for k in unknown)}, "
            f"which an entry does not take; it takes {' and '.join(repr(k) for k in PIPELINES_ENTRY_KEYS)}.{hint}"
        )
    if "path" in entry and not isinstance(entry["path"], (str, dict)):
        raise ValueError(
            f"{source}: [pipelines] \"{pipeline_id}\" path is {entry['path']!r}; it must be a string, "
            f"or a table of a unix and a windows path."
        )
    if "disabled" in entry and not isinstance(entry["disabled"], bool):
        raise ValueError(
            f"{source}: [pipelines] \"{pipeline_id}\" disabled is {entry['disabled']!r}; it must be true or false."
        )
    return dict(entry)


def _catalog_entries(raw_manifest: dict, base_dir, source: str) -> dict:
    """A catalog's ``[pipelines]`` entries, explicit and discovered, with the disabled ones dropped.

    Each is a table with a ``path`` (None for a pipeline the catalog shows
    from the store), by pipeline ID. No member's manifest is loaded here:
    a discovered member's is parsed for its ID, and that is all.

    :raises ValueError: On a malformed entry or reserved key, or a member
        that cannot be found, with what to do.
    """
    pipelines_raw = raw_manifest.get("pipelines") or {}
    members = pipelines_raw.get("members")
    exclude = pipelines_raw.get("exclude", [])
    disabled_ids = pipelines_raw.get("disabled", [])
    if members is not None:
        members = _require_string_list(members, "members", source)
    exclude = _require_string_list(exclude, "exclude", source)
    disabled_ids = _require_string_list(disabled_ids, "disabled", source)

    # Explicit entries; a plain string value is shorthand for {path = ...}
    entries = {}
    for pipeline_id, entry in pipelines_raw.items():
        if pipeline_id in RESERVED_PIPELINES_KEYS:
            continue
        try:
            validate_pipeline_id(pipeline_id)
        except ValueError as error:
            # Keeps "reserved, not yet supported" distinct from "invalid"
            raise type(error)(f"{source}: [pipelines] {pipeline_id!r}: {error}") from None
        if isinstance(entry, str):
            entry = {"path": entry}
        entries[pipeline_id] = _check_pipelines_entry(pipeline_id, entry, source)

    # Auto-discovered members join the explicit entries, and fill in one
    # that names a pipeline with no folder (keeping whether it is disabled)
    if members is not None:
        found = _discover_member_pipelines(members, exclude, entries, base_dir, source)
        for member_id, member_entry in found.items():
            entries[member_id] = {**entries.get(member_id, {}), **member_entry}

    # Drop disabled pipelines: per-entry flags first, then the ID list
    for pipeline_id in [k for k, v in entries.items() if v.get("disabled", False)]:
        del entries[pipeline_id]
    _apply_disabled_list(entries, disabled_ids, source)
    return entries


def catalog_member_dirs(base_dir) -> dict:
    """The folder of each pipeline of a catalog that is on this machine, by its ID, from the catalog's manifest alone.

    What a build of the catalog would read from this machine, before it
    reads any of it: no member's manifest is loaded, and nothing of a
    member runs. A pipeline the catalog shows from the store (an entry
    with no ``path``) has no folder here and is not listed. An explicit
    entry's folder is listed as the entry names it, whether or not a
    chartbook.toml is there yet: the caller says what to do about one
    that is not.

    :param base_dir: The catalog's folder.
    :raises FileNotFoundError: If there is no chartbook.toml there.
    :raises ValueError: If the manifest is not a catalog's, or cannot be read.
    """
    base_dir = Path(base_dir)
    raw_manifest = _read_manifest_file(base_dir)
    source = str(base_dir / "chartbook.toml")
    if resolve_project_type(raw_manifest, source=source) != "catalog":
        raise ValueError(f"{source} is a pipeline's manifest, not a catalog's: it has no [pipelines].")
    found = {}
    for pipeline_id, entry in _catalog_entries(raw_manifest, base_dir, source).items():
        if entry.get("path") is None:
            continue
        found[pipeline_id] = catalog_entry_dir(
            base_dir, resolve_platform_path(entry["path"]), where=f"{source}: [pipelines.\"{pipeline_id}\"]"
        )
    return found


def _load_catalog_manifest(raw_manifest):
    """Process a raw catalog manifest, loading each registered pipeline.

    The [pipelines] table holds explicit entries (keyed by pipeline ID, with
    a plain string as shorthand for {path = ...}) plus the reserved keys
    ``members`` (path patterns to auto-discover), ``exclude`` (paths to skip
    during discovery), and ``disabled`` (pipeline IDs to drop).

    :param raw_manifest: The raw manifest dictionary loaded from chartbook.toml
        (with ``base_dir`` already attached).
    :returns: The processed catalog manifest dictionary.
    :rtype: dict
    """
    manifest = raw_manifest.copy()
    base_dir = manifest["base_dir"]
    source = str(Path(base_dir) / "chartbook.toml")

    manifest["project"] = _resolve_project(raw_manifest, base_dir, "catalog")
    manifest["project"]["_resolved_site_dir"] = None
    manifest["policy"] = _resolve_policy(raw_manifest, source)
    if "dependencies" in raw_manifest:
        raise ValueError(
            f"{source}: a catalog has no [dependencies]. It reads from no "
            f"pipeline; it lists them, in [pipelines]. A pipeline declares "
            f"what it depends on in its own chartbook.toml."
        )
    if "scripts" in raw_manifest:
        raise ValueError(
            f"{source}: a catalog has no [scripts]. `chartbook run` in a "
            f"catalog runs each of its pipelines' own scripts."
        )
    if "sources" in raw_manifest:
        raise ValueError(
            f"{source}: a catalog has no [sources]. A pipeline declares the "
            f"sources its own dataframes live in."
        )

    entries = _catalog_entries(raw_manifest, base_dir, source)

    manifest["pipelines"] = {}
    # A pipeline with no folder here: the catalog shows its snapshots in the store
    manifest["store_pipelines"] = sorted(
        pipeline_id for pipeline_id, pipeline_entry in entries.items() if pipeline_entry.get("path") is None
    )
    for pipeline_id in entries:
        pipeline_entry = entries[pipeline_id]
        path_to_pipeline = pipeline_entry.get("path")
        if path_to_pipeline is None:
            continue
        pipeline_base_dir = catalog_entry_dir(
            base_dir, resolve_platform_path(path_to_pipeline), where=f"{source}: [pipelines.\"{pipeline_id}\"]"
        )
        try:
            assert validate_manifest_file(pipeline_base_dir)
            sub_manifest = load_manifest(base_dir=pipeline_base_dir)
        except RequiresChartbookError as error:
            raise RequiresChartbookError(
                f"{source}: [pipelines.\"{pipeline_id}\"]: {error}\nTo build the catalog without it until "
                f"then: `chartbook catalog disable {pipeline_id}`."
            ) from None
        if sub_manifest["project"]["type"] != "pipeline":
            raise ValueError(
                f"{source}: [pipelines.\"{pipeline_id}\"] points at "
                f"{pipeline_base_dir}, which is a catalog, not a pipeline.\n"
                f"To fix: remove the entry (catalogs cannot nest inside catalogs)."
            )
        # The catalog key is the authoritative identity within this catalog.
        sub_manifest["project"]["id"] = pipeline_id
        manifest["pipelines"][pipeline_id] = sub_manifest

    return manifest


def load_manifest(base_dir=BASE_DIR):
    """Load and process a chartbook.toml manifest (pipeline or catalog).

    For catalogs, each registered pipeline's manifest is loaded recursively.
    Pipeline manifests get resolved ``[project]`` metadata, linked-chart
    mappings, and resolved artifact paths.

    :param base_dir: The directory where the chartbook.toml file is located.
    :type base_dir: Union[str, Path]
    :returns: The processed manifest dictionary.
    :rtype: dict
    """
    base_dir = Path(base_dir)
    raw_manifest = _read_manifest_file(base_dir)
    project_type = resolve_project_type(
        raw_manifest, source=str(base_dir / "chartbook.toml")
    )
    raw_manifest["base_dir"] = base_dir

    if project_type == "pipeline":
        manifest = _load_pipeline_manifest(raw_manifest)
    else:
        manifest = _load_catalog_manifest(raw_manifest)

    return manifest


def find_latest_source_modification(
    base_dir: Union[str, Path],
) -> datetime:
    """Find the most recent modification datetime across pipeline source files.

    :param base_dir: The base directory of the pipeline.
    :type base_dir: Union[str, Path]
    :returns: The most recent modification datetime.
    :rtype: datetime
    """
    base_dir = Path(base_dir)

    def get_latest_mod_time(directory: Path) -> datetime:
        latest_time = datetime.min
        if not directory.exists():
            return latest_time
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file
                mod_time = get_file_modified_datetime(file_path)
                if mod_time > latest_time:
                    latest_time = mod_time
        return latest_time

    # Get the most recent modification time in src directory
    src_latest = get_latest_mod_time(base_dir / "src")

    pipeline_time = get_file_modified_datetime(base_dir / "chartbook.toml")
    docs_time = get_latest_mod_time(base_dir / "docs_src")

    latest = max(src_latest, pipeline_time, docs_time)
    return latest


#: The parts of a pipeline that count as its source.
SOURCE_PATHS = ("src", "docs_src", "chartbook.toml")

CODE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _git(base_dir: Path, *args: str) -> Union[str, None]:
    """Run a read-only git command in a directory; None if it fails.

    It takes no lock it does not need (``git status`` would otherwise
    refresh the index), so that looking never gets in the way of whoever
    is working in the repository.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(base_dir), *args],
            capture_output=True,
            text=True,
            timeout=15,
            env={**_git_environment(), "GIT_OPTIONAL_LOCKS": "0"}, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def find_latest_code_change(base_dir: Union[str, Path]) -> datetime:
    """Find when a pipeline's source last changed, asking git where it can.

    File modification times say when a file last landed on *this disk*. A
    fresh clone stamps every file with the moment of the checkout, so on a
    build server they report code that is a year old as changed just now.

    When the pipeline's source is committed and unmodified, the answer is
    the time of the last commit that touched it. With uncommitted changes,
    or outside a git repository, it is the newest modification time, as
    :func:`find_latest_source_modification` gives.

    :param base_dir: The base directory of the pipeline.
    :type base_dir: Union[str, Path]
    :returns: The time of the last change, in local time.
    :rtype: datetime
    """
    base_dir = Path(base_dir)
    # A version laid out from the store says when its code changed; it has no git of its own
    from chartbook.identity import read_version_file

    version = read_version_file(base_dir)
    if version:
        recorded = version.get("code_changed_at")
        if isinstance(recorded, str):
            try:
                moment = datetime.strptime(recorded, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                return datetime.fromtimestamp(moment.timestamp())
            except (ValueError, OverflowError, OSError):
                pass
        # A laid-out version has no git of its own: its files' times, not git's
        return find_latest_source_modification(base_dir)
    uncommitted = _git(base_dir, "status", "--porcelain", "--", *SOURCE_PATHS)
    if uncommitted is not None and not uncommitted.strip():
        committed = _git(base_dir, "log", "-1", "--format=%ct", "--", *SOURCE_PATHS)
        if committed and committed.strip().isdigit():
            return datetime.fromtimestamp(int(committed.strip()))
    return find_latest_source_modification(base_dir)


def apply_code_change_times(manifest: dict, known: Union[dict, None] = None) -> dict:
    """Replace each pipeline's modification-time stamp with its code-change time.

    Loading a manifest records ``source_last_modified_date`` from file
    modification times, which is cheap and is all most callers need.
    Building pages calls this first, so that what a page shows comes from
    :func:`find_latest_code_change`.

    :param manifest: A loaded manifest, pipeline or catalog. Updated in place.
    :param known: Times already worked out, by pipeline ID, to use as they
        are. An incremental build passes the ones it recorded for pipelines
        it is not regenerating, which spares git a call for each.
    :returns: The time now set for every pipeline, by pipeline ID.
    """
    known = known or {}
    times = {}
    for pipeline_id in get_pipeline_ids(manifest):
        if manifest["project"]["type"] == "catalog":
            pipeline_manifest = manifest["pipelines"][pipeline_id]
        else:
            pipeline_manifest = manifest
        stamp = known.get(pipeline_id)
        if stamp is None:
            changed = find_latest_code_change(pipeline_manifest["pipeline_base_dir"])
            stamp = changed.strftime(CODE_TIME_FORMAT)
        else:
            changed = datetime.strptime(stamp, CODE_TIME_FORMAT)
        pipeline_manifest["source_last_modified_date"] = stamp
        # The instant, for the index: a naive time is this machine's local time
        pipeline_manifest["_code_changed_at"] = changed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        times[pipeline_id] = stamp
    return times


def get_file_modified_datetime(file_path: Union[Path, str]) -> datetime:
    """Returns the datetime that a file was last modified.

    :param file_path: A pathlib.Path object or a string representing the file path.
    :type file_path: Union[Path, str]
    :returns: A datetime object representing the last modification time.
    :rtype: datetime
    """
    file_path = Path(file_path)
    mtime = os.path.getmtime(file_path)
    return datetime.fromtimestamp(mtime)


def get_default_branding_path(filename: str) -> Path:
    """Get the path to a default logo or favicon shipped with the package.

    These live in ``chartbook/branding/``. (They are not *assets* in
    ChartBook's sense of the word, which is what :mod:`chartbook.assets` is
    about: things a pipeline declares.)

    :param filename: The name of the file, e.g. ``"logo.png"``.
    :type filename: str
    :returns: The path to the file.
    :rtype: Path
    """
    package_path = importlib.resources.files("chartbook")
    try:
        with importlib.resources.as_file(
            package_path / "branding" / filename
        ) as branding_path:
            return Path(str(branding_path))
    except (TypeError, FileNotFoundError):
        # Fallback for development mode
        return Path(str(package_path)).parent / "branding" / filename


def get_pipeline_ids(manifest):
    """Get a list of pipeline IDs from the manifest.

    :param manifest: The manifest dictionary.
    :type manifest: dict
    :returns: A list of pipeline IDs.
    :rtype: list
    """
    if manifest["project"]["type"] == "catalog":
        pipelines = list(manifest["pipelines"].keys())
    else:
        pipelines = [manifest["project"]["id"]]
    return pipelines


def get_pipeline_dirs(manifest: dict) -> dict:
    """Get the directory of every pipeline in the manifest, by pipeline ID.

    These are the pipelines of one build, and where each is: what
    :func:`chartbook.resolve.locate_pipeline` takes as its catalog.

    :param manifest: The manifest dictionary, pipeline or catalog.
    :type manifest: dict
    :returns: Each pipeline's ID and its root directory.
    :rtype: dict[str, Path]
    """
    return {
        pipeline_id: Path(
            get_pipeline_manifest(manifest, pipeline_id)["pipeline_base_dir"]
        )
        for pipeline_id in get_pipeline_ids(manifest)
    }


def get_logo_path(config: dict, project_dir: Path) -> Path:
    """Get logo path from config or return default.

    :param config: The configuration dictionary.
    :type config: dict
    :param project_dir: The project directory path.
    :type project_dir: Path
    :returns: The path to the logo file.
    :rtype: Path
    """
    if config.get("project", {}).get("logo", ""):
        return project_dir / config["project"]["logo"]
    return get_default_branding_path("logo.png")


def get_favicon_path(config: dict, project_dir: Path) -> Path:
    """Get favicon path from config or return default.

    :param config: The configuration dictionary.
    :type config: dict
    :param project_dir: The project directory path.
    :type project_dir: Path
    :returns: The path to the favicon file.
    :rtype: Path
    """
    if config.get("project", {}).get("favicon", ""):
        return project_dir / config["project"]["favicon"]
    return get_default_branding_path("favicon.ico")


def get_pipeline_manifest(manifest: dict, pipeline_id: str) -> dict:
    """Get the manifest for a specific pipeline.

    :param manifest: The full manifest dictionary.
    :type manifest: dict
    :param pipeline_id: The ID of the pipeline to retrieve.
    :type pipeline_id: str
    :returns: The manifest dictionary for the specified pipeline.
    :rtype: dict
    """
    if manifest["project"]["type"] == "catalog":
        pipeline_manifest = manifest["pipelines"][pipeline_id]
    else:
        pipeline_manifest = manifest.copy()
    return pipeline_manifest


if __name__ == "__main__":
    pass
