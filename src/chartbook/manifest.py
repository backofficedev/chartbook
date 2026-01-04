import importlib.resources
import os
from datetime import datetime
from pathlib import Path
from typing import Union

import tomli
from packaging import version  # Add this import for proper version comparison

from chartbook.__about__ import __version__  # Import the version

BASE_DIR = Path(".").resolve()
OUTPUT_DIR = Path("./_output")
PIPELINE_THEME = "pipeline"
PUBLISH_DIR = Path("./_output/to_be_published")
DOCS_BUILD_DIR = BASE_DIR / Path("_docs")
DOCS_SRC_DIR = BASE_DIR / Path("_docs_src")

DEFAULT_CONFIG = {
    "config": {
        "type": "pipeline",
        "chartbook_format_version": __version__,  # Use imported version
    },
    "site": {
        "title": "chartbook",
        "author": "",
        "copyright": "",
        "logo_path": "",
        "favicon_path": "",
    },
    "pipeline": {
        "id": "DEFAULT",
        "pipeline_name": "Default Pipeline",
        "pipeline_description": "Default pipeline description",
        "lead_pipeline_developer": "Default lead pipeline developer",
        "contributors": [],
        "build_commands": "",
        "os_compatibility": [],
        "git_repo_URL": "",
        "README_file_path": "",
    },
}


def resolve_platform_path(path_input: Union[str, dict]) -> Path:
    """Resolves a path that can be either a direct path string or a dictionary of platform-specific paths.

    :param path_input: Either a string representing a direct path, or a dictionary containing platform-specific paths with 'Windows' and/or 'Unix' keys.
    :type path_input: Union[str, dict]
    :returns: The resolved path appropriate for the current platform.
    :rtype: Path
    :raises ValueError: If using a dict input and no valid path is found for the current platform.

    **Examples**::

        resolve_platform_path('/path/to/dir')
        # Returns: PosixPath('/path/to/dir')

        resolve_platform_path({'Windows': 'C:/data', 'Unix': '/home/data'})
        # Returns: WindowsPath('C:/data') on Windows, PosixPath('/home/data') on Unix/macOS
    """
    result_path = None

    if isinstance(path_input, str):
        result_path = Path(path_input)
    else:
        # Handle dict case (platform-specific paths)
        import platform

        is_windows = platform.system().lower() == "windows"

        if is_windows and "Windows" in path_input:
            result_path = Path(path_input["Windows"])
        elif not is_windows and "Unix" in path_input:
            result_path = Path(path_input["Unix"])

        if result_path is None:
            raise ValueError(
                f"No valid path found for current platform ({platform.system()}). "
                f"Available paths: {list(path_input.keys())}"
            )

    return result_path


def validate_config_file(path: Path = BASE_DIR) -> bool:
    """
    Validates that a chartbook.toml file exists in the specified directory.
    """
    chartbook_toml = path / "chartbook.toml"
    if not chartbook_toml.is_file():
        raise ValueError(f"No chartbook.toml found in directory: {path}")
    # Test ability to load chartbook.toml
    try:
        with open(chartbook_toml, "rb") as f:
            chartbook_toml = tomli.load(f)
        assert chartbook_toml["config"]["type"] in ["pipeline", "catalog"]

        current_version = __version__  # Use imported version
        expected_minor_version = version.parse(current_version).minor
        actual_version_str = chartbook_toml["config"].get(
            "chartbook_format_version", "0.0.0"
        )  # Handle missing key
        # Check if the actual version string is parseable
        try:
            actual_minor_version = version.parse(actual_version_str).minor
        except version.InvalidVersion:
            raise ValueError(
                f"Invalid version format in chartbook.toml: {actual_version_str}"
            )

        assert actual_minor_version >= expected_minor_version, (
            f"chartbook.toml version is too low. Expected version {current_version} or greater, found {actual_version_str}"
        )
        # https://packaging.pypa.io/en/latest/version.html#packaging.version.Version.minor
    except KeyError as e:
        raise ValueError(f"Missing key in chartbook.toml: {e}")
    except Exception as e:
        raise ValueError(f"Error loading chartbook.toml: {e}")
    return True


def validate_os_compatibility(value: Union[str, list]) -> Union[str, list]:
    """Validate that os_compatibility is either a string or a list of strings.

    :param value: The os_compatibility value to validate.
    :type value: Union[str, list]
    :returns: The validated value (unchanged).
    :rtype: Union[str, list]
    :raises TypeError: If the value is neither a string nor a list of strings.

    **Examples**::

        validate_os_compatibility("Windows/Linux/macOS")
        # Returns: "Windows/Linux/macOS"

        validate_os_compatibility(["Windows", "Linux", "macOS"])
        # Returns: ["Windows", "Linux", "macOS"]

        validate_os_compatibility(123)
        # Raises: TypeError
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
    :type tags: list
    :returns: List of tags in Title Case
    :rtype: list

    >>> normalize_tags(['short term funding', 'REPO', 'Monetary Policy'])
    ['Short Term Funding', 'Repo', 'Monetary Policy']
    """
    if not tags:
        return tags
    return [tag.title() if isinstance(tag, str) else tag for tag in tags]


def validate_doc_fields(
    manifest: dict,
    path_key: str,
    str_key: str,
    object_type: str,
    object_id: str,
) -> tuple[str, str]:
    """Validate that exactly one of path or str doc fields is provided.

    :param manifest: The manifest dictionary for the object (dataframe or chart).
    :param path_key: The key for the path-based documentation field.
    :param str_key: The key for the inline string documentation field.
    :param object_type: The type of object ('dataframe' or 'chart') for error messages.
    :param object_id: The ID of the object for error messages.
    :returns: A tuple of (mode, value) where mode is 'path' or 'str'.
    :raises ValueError: If both or neither fields are provided.

    **Examples**::

        validate_doc_fields(
            {'dataframe_docs_path': './docs/df.md'},
            'dataframe_docs_path', 'dataframe_docs_str',
            'dataframe', 'my_df'
        )
        # Returns: ('path', './docs/df.md')

        validate_doc_fields(
            {'dataframe_docs_str': 'Inline docs here'},
            'dataframe_docs_path', 'dataframe_docs_str',
            'dataframe', 'my_df'
        )
        # Returns: ('str', 'Inline docs here')
    """
    has_path = path_key in manifest and manifest[path_key]
    has_str = str_key in manifest and manifest[str_key]

    if has_path and has_str:
        raise ValueError(
            f"{object_type} '{object_id}' has both {path_key} and {str_key}. "
            f"Only one is allowed."
        )
    if not has_path and not has_str:
        raise ValueError(
            f"{object_type} '{object_id}' must have either {path_key} or {str_key}."
        )

    if has_path:
        return ("path", manifest[path_key])
    return ("str", manifest[str_key])


def _load_pipeline_manifest(raw_manifest):
    """
    Load the pipeline manifest from a TOML file and process it.
    """
    assert raw_manifest["config"]["type"] == "pipeline"
    base_dir = raw_manifest["base_dir"]
    manifest = raw_manifest.copy()

    # Validate os_compatibility if present
    if "pipeline" in manifest and "os_compatibility" in manifest["pipeline"]:
        manifest["pipeline"]["os_compatibility"] = validate_os_compatibility(
            manifest["pipeline"]["os_compatibility"]
        )

    source_last_modified_date = find_latest_source_modification(
        base_dir
    )  # Get the last modified date
    manifest["source_last_modified_date"] = source_last_modified_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )  # Format and store the last modified date
    manifest["pipeline_base_dir"] = base_dir.resolve().as_posix()

    candidate_webpage_url = manifest.get("webpage_URL", None)
    if candidate_webpage_url is None:
        webpage_path = Path(base_dir) / "docs" / "index.html"
        manifest["webpage_URL"] = f"file://{webpage_path.as_posix()}"
    else:
        manifest["webpage_URL"] = candidate_webpage_url

    # Process notes if they exist
    if "notes" in manifest:
        for note_id in manifest["notes"]:
            note_manifest = manifest["notes"][note_id]
            # Add the full path to the markdown file for easier access later
            note_manifest["full_path"] = (
                Path(base_dir) / note_manifest["path_to_markdown_file"]
            )

    # Create a mapping of dataframe_id to linked chart_ids
    if "dataframes" in manifest:
        dataframe_to_charts = {
            dataframe_id: [] for dataframe_id in manifest["dataframes"]
        }  # Initialize mapping

        for dataframe_id in manifest["dataframes"]:
            dataframe_manifest = manifest["dataframes"][dataframe_id]
            dataframe_manifest["dataframe_path"] = (
                Path(base_dir) / dataframe_manifest["path_to_parquet_data"]
            )
            # Normalize topic_tags to Title Case
            if "topic_tags" in dataframe_manifest:
                dataframe_manifest["topic_tags"] = normalize_tags(
                    dataframe_manifest["topic_tags"]
                )
            # Validate and store doc field mode
            doc_mode, doc_value = validate_doc_fields(
                dataframe_manifest,
                "dataframe_docs_path",
                "dataframe_docs_str",
                "dataframe",
                dataframe_id,
            )
            dataframe_manifest["_doc_mode"] = doc_mode
            dataframe_manifest["_doc_value"] = doc_value

        if "charts" in manifest:
            for chart_id in manifest["charts"]:
                chart_manifest = manifest["charts"][
                    chart_id
                ]  # Get manifest for the current chart
                # Normalize topic_tags to Title Case
                if "topic_tags" in chart_manifest:
                    chart_manifest["topic_tags"] = normalize_tags(
                        chart_manifest["topic_tags"]
                    )
                # Validate and store doc field mode
                doc_mode, doc_value = validate_doc_fields(
                    chart_manifest,
                    "chart_docs_path",
                    "chart_docs_str",
                    "chart",
                    chart_id,
                )
                chart_manifest["_doc_mode"] = doc_mode
                chart_manifest["_doc_value"] = doc_value

                dataframe_id = chart_manifest[
                    "dataframe_id"
                ]  # Identify the linked dataframe
                if dataframe_id in dataframe_to_charts:
                    dataframe_to_charts[dataframe_id].append(
                        chart_id
                    )  # Link chart_id to dataframe_id
                else:
                    raise ValueError(
                        f"Dataframe {dataframe_id} not found in dataframes section"
                    )

            # Update dataframe_manifest with the linked charts
            for dataframe_id, chart_ids in dataframe_to_charts.items():
                manifest["dataframes"][dataframe_id]["linked_charts"] = (
                    chart_ids  # Add linked charts
                )
    return manifest


def _load_catalog_manifest(raw_manifest):
    """
    Load the catalog manifest from a TOML file and process it.
    """
    manifest = raw_manifest.copy()
    base_dir = manifest["base_dir"]
    all_pipelines = list(manifest["pipelines"].keys())
    for pipeline_id in all_pipelines:
        path_to_pipeline = manifest["pipelines"][pipeline_id]["path_to_pipeline"]
        path_to_pipeline = resolve_platform_path(path_to_pipeline)
        pipeline_base_dir = Path(base_dir) / path_to_pipeline
        pipeline_base_dir = pipeline_base_dir.resolve()
        assert validate_config_file(pipeline_base_dir)
        sub_manifest = load_manifest(base_dir=pipeline_base_dir)
        manifest["pipelines"][pipeline_id] = sub_manifest

    return manifest  # Return the complete manifest


def load_manifest(base_dir=BASE_DIR):
    """Load the pipeline manifest from a TOML file and process it.

    This will also handle imported pipeline manifests. It
    will also create a mapping of dataframe_id to linked chart_ids
    and a mapping of data

    :param base_dir: The base directory where the chartbook.toml file is located.
    :type base_dir: Union[str, Path]
    :returns: A dictionary containing the manifest for all pipelines, including linked charts for each dataframe and linked dataframes for each pipeline.
    :rtype: dict
    """
    base_dir = Path(base_dir)  # Convert base_dir to a Path object
    chartbook_toml_path = base_dir / "chartbook.toml"
    assert chartbook_toml_path.is_file()
    assert validate_config_file(base_dir)

    # Load the TOML manifest using tomli instead of json
    with open(chartbook_toml_path, "rb") as file:  # Note: tomli requires binary mode
        raw_manifest = tomli.load(file)  # Load the TOML manifest

    raw_manifest["base_dir"] = base_dir

    if raw_manifest["config"]["type"] == "pipeline":
        manifest = _load_pipeline_manifest(raw_manifest)
    elif raw_manifest["config"]["type"] == "catalog":
        manifest = _load_catalog_manifest(raw_manifest)
    else:
        raise ValueError(
            f"Invalid config type: {raw_manifest['config']['type']}. Must be 'pipeline' or 'catalog'."
        )

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
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file
                mod_time = get_file_modified_datetime(file_path)
                if mod_time > latest_time:
                    latest_time = mod_time
        return latest_time

    # Get the most recent modification time in src directory
    src_latest = get_latest_mod_time(base_dir / "src")

    # Get modification times for dodo.py and chartbook.toml
    # dodo_time = get_file_modified_datetime(base_dir / "dodo.py")
    pipeline_time = get_file_modified_datetime(base_dir / "chartbook.toml")
    docs_time = get_latest_mod_time(base_dir / "docs_src")

    # Return the most recent of all these times
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
    # Get the last modified time in seconds since the epoch
    mtime = os.path.getmtime(file_path)
    # Convert the time to a datetime object
    return datetime.fromtimestamp(mtime)


def get_default_asset_path(filename: str) -> Path:
    """Get path to default asset from package resources"""
    package_path = importlib.resources.files("chartbook")
    try:
        # First try to get the asset directly using importlib.resources
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
    if manifest["config"]["type"] == "catalog":
        pipelines = list(manifest["pipelines"].keys())
    elif manifest["config"]["type"] == "pipeline":
        pipelines = [manifest["pipeline"]["id"]]
    else:
        raise ValueError(
            f"Invalid config type: {manifest['config']['type']}. Must be 'pipeline' or 'catalog'."
        )
    return pipelines


def get_logo_path(config: dict, project_dir: Path) -> Path:
    """Get logo path from config or return default"""
    if config["site"]["logo_path"]:
        return project_dir / config["site"]["logo_path"]
    return get_default_asset_path("logo.png")


def get_favicon_path(config: dict, project_dir: Path) -> Path:
    """Get favicon path from config or return default"""
    if config["site"]["favicon_path"]:
        return project_dir / config["site"]["favicon_path"]
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
    if manifest["config"]["type"] == "catalog":
        pipeline_manifest = manifest["pipelines"][pipeline_id]
    elif manifest["config"]["type"] == "pipeline":
        pipeline_manifest = manifest.copy()
    else:
        raise ValueError(
            f"Invalid config type: {manifest['config']['type']}. Must be 'pipeline' or 'catalog'."
        )
    return pipeline_manifest


def _demo():
    # Find date modified
    dt_modified = get_file_modified_datetime("mydata.parquet")
    print(f"Last modified: {dt_modified}")


if __name__ == "__main__":
    pass
