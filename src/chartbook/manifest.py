"""Load and process ``chartbook.toml`` manifests (format v2).

A v2 manifest has a single ``[project]`` metadata table plus the entity
sections ``[charts]``, ``[dataframes]``, ``[notebooks]``, and ``[notes]``
(pipelines), or a ``[pipelines]`` registry and optional ``[policy]``
(catalogs). Every ``[project]`` field is optional; defaults are filled at
load time. See ``docs_src/design/toml-format-v2.md`` for the full
specification.

v1 manifests (the old ``[config]``/``[site]``/``[pipeline]`` layout) are not
supported; loading one raises an error pointing at the migration script.
"""

import difflib
import importlib.resources
import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Union

import tomli

from chartbook.identity import derive_pipeline_id, validate_pipeline_id
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
}

#: Entity sections that mark a manifest as pipeline-shaped.
ENTITY_SECTIONS = ("charts", "dataframes", "notebooks", "notes")

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
        an ambiguous file.
    """
    explicit = raw_manifest.get("project", {}).get("type")
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
    :raises V1FormatError: If the file uses the v1 layout.
    """
    chartbook_toml_path = Path(base_dir) / "chartbook.toml"
    if not chartbook_toml_path.is_file():
        raise FileNotFoundError(f"No chartbook.toml found in directory: {base_dir}")
    with open(chartbook_toml_path, "rb") as f:
        raw_manifest = tomli.load(f)
    if detect_v1_format(raw_manifest):
        raise V1FormatError(chartbook_toml_path)
    return raw_manifest


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


def validate_os_compatibility(value: Union[str, list]) -> Union[str, list]:
    """Validate that os_compatibility is a string or a list of strings.

    :param value: The os_compatibility value to validate.
    :returns: The validated value (unchanged).
    :raises TypeError: If the value is neither a string nor a list of strings.
    """
    if isinstance(value, str):
        return value
    elif isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise TypeError(
                f"os_compatibility list must contain only strings, got: {value}"
            )
        return value
    else:
        raise TypeError(
            f"os_compatibility must be a string or list of strings, got: {type(value).__name__}"
        )


def normalize_tags(tags: list) -> list:
    """Normalize a list of tags to Title Case.

    :param tags: List of tag strings to normalize
    :returns: List of tags in Title Case

    Examples
    --------

    ```python
    normalize_tags(['short term funding', 'REPO', 'Monetary Policy'])
    # Output: ['Short Term Funding', 'Repo', 'Monetary Policy']
    ```
    """
    if not tags:
        return tags
    return [tag.title() if isinstance(tag, str) else tag for tag in tags]


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

    project = dict(PROJECT_DEFAULTS)
    project.update({k: v for k, v in project_raw.items() if k in PROJECT_DEFAULTS})
    project["type"] = project_type

    if not project["name"]:
        project["name"] = Path(base_dir).name
    if not project["copyright"]:
        project["copyright"] = str(datetime.now().year)
    if not project["maintainer"] and project["contributors"]:
        project["maintainer"] = project["contributors"][0]

    project["id"] = derive_pipeline_id(project_raw, base_dir)

    if not project["site_url"]:
        webpage_path = Path(base_dir) / "docs" / "index.html"
        project["site_url"] = f"file://{webpage_path.as_posix()}"

    if "os_compatibility" in project_raw:
        project["os_compatibility"] = validate_os_compatibility(
            project_raw["os_compatibility"]
        )

    return project


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
            f"site_dir contains a 'cb/' subdirectory which conflicts with "
            f"the reserved chartbook namespace. Please rename or remove it."
        )
    project["_resolved_site_dir"] = str(site_dir_path.resolve())


def _load_pipeline_manifest(raw_manifest):
    """Process a raw pipeline manifest into the internal manifest shape.

    :param raw_manifest: The raw manifest dictionary loaded from chartbook.toml
        (with ``base_dir`` already attached).
    :returns: The processed manifest dictionary with resolved metadata.
    :rtype: dict
    """
    base_dir = raw_manifest["base_dir"]
    manifest = raw_manifest.copy()

    manifest["project"] = _resolve_project(raw_manifest, base_dir, "pipeline")
    _resolve_site_dir(manifest["project"], base_dir)

    # Ensure optional sections have defaults
    manifest.setdefault("charts", {})
    manifest.setdefault("dataframes", {})
    manifest.setdefault("notebooks", {})

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

    # Create a mapping of dataframe id to linked chart ids
    if "dataframes" in manifest:
        dataframe_to_charts = {
            dataframe_id: [] for dataframe_id in manifest["dataframes"]
        }

        for dataframe_id in manifest["dataframes"]:
            dataframe_manifest = manifest["dataframes"][dataframe_id]
            raw_parquet_path = dataframe_manifest.get("path", "")
            dataframe_manifest["_is_glob"] = is_glob_pattern(raw_parquet_path)
            dataframe_manifest["_resolved_path"] = (
                Path(base_dir) / raw_parquet_path if raw_parquet_path else None
            )
            if "tags" in dataframe_manifest:
                dataframe_manifest["tags"] = normalize_tags(dataframe_manifest["tags"])
            doc_mode, doc_value = validate_doc_fields(
                dataframe_manifest, "dataframe", dataframe_id
            )
            dataframe_manifest["_doc_mode"] = doc_mode
            dataframe_manifest["_doc_value"] = doc_value

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
                manifest["dataframes"][dataframe_id]["linked_charts"] = chart_ids

    return manifest


def _resolve_policy(raw_manifest: dict, source: str) -> dict:
    """Resolve a catalog's [policy] section, filling defaults.

    :param raw_manifest: The raw parsed catalog manifest.
    :param source: Label used in error messages.
    :returns: Dict with ``mode`` and per-object-type ``required`` field lists.
    """
    from chartbook.diagnostics import DEFAULT_REQUIRED_FIELDS

    policy_raw = raw_manifest.get("policy", {})
    mode = policy_raw.get("mode", "warn")
    if mode not in ("warn", "strict"):
        raise ValueError(
            f"{source}: invalid policy.mode {mode!r}. Must be 'warn' or 'strict'."
        )

    required_raw = policy_raw.get("required", {})
    for key in required_raw:
        if key not in DEFAULT_REQUIRED_FIELDS:
            raise ValueError(
                f"{source}: unknown policy.required key {key!r}. "
                f"Allowed keys: {sorted(DEFAULT_REQUIRED_FIELDS)}."
            )
    required = {
        object_type: list(required_raw.get(object_type, default_fields))
        for object_type, default_fields in DEFAULT_REQUIRED_FIELDS.items()
    }
    return {"mode": mode, "required": required}


def _load_catalog_manifest(raw_manifest):
    """Process a raw catalog manifest, loading each registered pipeline.

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
    manifest.setdefault("pipelines", {})

    all_pipelines = list(manifest["pipelines"].keys())
    for pipeline_id in all_pipelines:
        validate_pipeline_id(pipeline_id)
        pipeline_entry = manifest["pipelines"][pipeline_id]
        if pipeline_entry.get("disabled", False):
            del manifest["pipelines"][pipeline_id]
            continue
        path_to_pipeline = pipeline_entry.get("path")
        if path_to_pipeline is None:
            raise ValueError(
                f"{source}: [pipelines.\"{pipeline_id}\"] has no 'path' key."
            )
        path_to_pipeline = resolve_platform_path(path_to_pipeline)
        pipeline_base_dir = Path(base_dir) / path_to_pipeline
        pipeline_base_dir = pipeline_base_dir.resolve()
        assert validate_manifest_file(pipeline_base_dir)
        sub_manifest = load_manifest(base_dir=pipeline_base_dir)
        if sub_manifest["project"]["type"] != "pipeline":
            raise ValueError(
                f"{source}: [pipelines.\"{pipeline_id}\"] points at "
                f"{pipeline_base_dir}, which is a catalog, not a pipeline."
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


def get_default_asset_path(filename: str) -> Path:
    """Get path to default asset from package resources.

    :param filename: The name of the asset file.
    :type filename: str
    :returns: The path to the asset file.
    :rtype: Path
    """
    package_path = importlib.resources.files("chartbook")
    try:
        with importlib.resources.as_file(
            package_path / "assets" / filename
        ) as asset_path:
            return Path(str(asset_path))
    except (TypeError, FileNotFoundError):
        # Fallback for development mode
        return Path(str(package_path)).parent / "assets" / filename


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
    return get_default_asset_path("logo.png")


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
    return get_default_asset_path("favicon.ico")


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
