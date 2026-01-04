"""
Copy publishable files to a publish directory.
"""

import os
import time
from pathlib import Path

import tomli_w

from chartbook.manifest import (
    find_latest_source_modification,
    get_pipeline_ids,
    get_pipeline_manifest,
    load_manifest,
)
from chartbook.utils import copy_according_to_plan

BASE_DIR = Path(".").resolve()
PUBLISH_DIR = BASE_DIR / Path("./_output/to_be_published")


def convert_paths_to_strings(obj):
    """Recursively convert all pathlib.Path objects to strings in a nested data structure.

    :param obj: The object to process, which may contain nested dictionaries, lists, and Path objects.
    :type obj: any
    :returns: The processed object with all Path objects converted to strings.
    :rtype: any
    """
    if isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_paths_to_strings(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_paths_to_strings(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_paths_to_strings(item) for item in obj)
    else:
        return obj


def create_dodo_file_with_mod_date(date, dodo_path, publish_dir=PUBLISH_DIR):
    """Create a Python file named 'dodo.py' with specified content and set its modification date.

    :param date: The desired modification date for the file.
    :type date: datetime.datetime
    :param dodo_path: The path to the original dodo file to reference in the content.
    :type dodo_path: str
    :param publish_dir: The directory where the 'dodo.py' file will be created. Default is defined by `PUBLISH_DIR`.
    :type publish_dir: str

    .. note::
       The function creates the specified directory if it does not exist. The content of the file will include a reference to the original file at `dodo_path`.

    **Examples**

    ```python
    >>> mod_date = datetime.datetime(2023, 11, 20, 14, 0)  # Example date
    >>> create_dodo_file_with_mod_date(mod_date, "path/to/original/dodo.py")
    ```
    """

    # Define the filename and content
    filename = "dodo.py"
    content = f"## Contents censored. See original file here: {dodo_path}"

    # Create the publish directory if it doesn't exist
    Path(publish_dir).mkdir(parents=True, exist_ok=True)

    # Write the content to create the file
    file_path = Path(publish_dir) / filename
    with open(file_path, "w") as f:
        f.write(content)  # Write the specified content to the file

    # Convert the datetime object to a timestamp
    timestamp = time.mktime(date.timetuple())

    # Set the modification time of the file
    os.utime(file_path, (timestamp, timestamp))

    # print(f"File '{filename}' created in '{publish_dir}' with modification date set to {date}.")


def get_pipeline_publishing_plan(manifest, publish_dir=PUBLISH_DIR):
    pipeline_ids = get_pipeline_ids(manifest)
    publishing_plan = {}

    def _add_file_to_plan(base_dir, file_path):
        if (file_path == "") or (file_path is None):
            pass
        else:
            full_path = base_dir / file_path
            # Check if the file exists before adding it to the plan
            if full_path.exists():
                publishing_plan[full_path] = publish_dir / file_path

    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest["pipeline_base_dir"])

        # Add README and chartbook.toml files
        _add_file_to_plan(
            pipeline_base_dir, pipeline_manifest["pipeline"]["README_file_path"]
        )
        _add_file_to_plan(pipeline_base_dir, "chartbook.toml")

        # Process dataframes
        for dataframe_id in pipeline_manifest["dataframes"]:
            dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

            _add_file_to_plan(
                pipeline_base_dir, dataframe_manifest["path_to_parquet_data"]
            )
            # Only copy doc file if using path mode (not inline string)
            if dataframe_manifest.get("_doc_mode") == "path":
                _add_file_to_plan(
                    pipeline_base_dir, dataframe_manifest.get("dataframe_docs_path")
                )

        # Process charts
        for chart_id in pipeline_manifest["charts"]:
            chart_manifest = pipeline_manifest["charts"][chart_id]

            _add_file_to_plan(pipeline_base_dir, chart_manifest["path_to_html_chart"])
            # Only copy doc file if using path mode (not inline string)
            if chart_manifest.get("_doc_mode") == "path":
                _add_file_to_plan(
                    pipeline_base_dir, chart_manifest.get("chart_docs_path")
                )

        # Process notebooks
        for notebook_id in pipeline_manifest["notebooks"]:
            notebook_manifest = pipeline_manifest["notebooks"][notebook_id]
            if notebook_manifest.get("is_publishable") is True:
                _add_file_to_plan(pipeline_base_dir, notebook_manifest["notebook_path"])

    return publishing_plan


def copy_publishable_pipeline_files(manifest, base_dir, publish_dir, verbose=False):
    """Copy unaligned files to the publishing directory and Sphinx templates.

    :param manifest: Manifest for the files to be copied.
    :type manifest: dict
    :param base_dir: The base directory where source files are located.
    :type base_dir: Path
    :param publish_dir: The directory where files will be published.
    :type publish_dir: Path
    :param verbose: Whether to print messages about copied files. Default is False.
    :type verbose: bool
    """
    # Copy unaligned files to publishing directory
    pipeline_publishing_plan = get_pipeline_publishing_plan(
        manifest, publish_dir=publish_dir
    )
    copy_according_to_plan(pipeline_publishing_plan, mkdir=True, verbose=verbose)

    src_modification_date = find_latest_source_modification(base_dir=base_dir)
    create_dodo_file_with_mod_date(
        src_modification_date,
        dodo_path=base_dir / "dodo.py",
        publish_dir=publish_dir,
    )
    if verbose:
        print(f"Copied to {publish_dir}/dodo.py")


def revise_published_chartbook_toml(publish_dir: Path, base_dir: Path = BASE_DIR):
    """Revise the chartbook.toml file in the publish directory.

    Only keep notebooks with is_publishable == True.

    :param publish_dir: The directory where the revised chartbook.toml file will be saved.
    :type publish_dir: Path
    :param base_dir: The base directory where the original chartbook.toml file is located. Defaults to BASE_DIR.
    :type base_dir: Path
    """
    manifest = load_manifest(base_dir=base_dir)
    notebooks = manifest.get("notebooks", {})
    revised_notebooks = {
        notebook_id: notebook_manifest
        for notebook_id, notebook_manifest in notebooks.items()
        if notebook_manifest.get("is_publishable") is True
    }
    manifest["notebooks"] = revised_notebooks

    # Convert all Path objects to strings before writing to TOML
    manifest_for_toml = convert_paths_to_strings(manifest)

    chartbook_toml_path = publish_dir / "chartbook.toml"
    with open(chartbook_toml_path, "wb") as f:
        tomli_w.dump(manifest_for_toml, f)


def publish_pipeline(publish_dir: Path, base_dir: Path, verbose=False):
    """Publish a pipeline to a publish directory.

    :param publish_dir: The directory where the pipeline will be published.
    :type publish_dir: Path
    :param base_dir: The base directory where the pipeline source files are located.
    :type base_dir: Path
    :param verbose: Whether to print messages about the publishing process. Defaults to False.
    :type verbose: bool
    """
    manifest = load_manifest(base_dir=base_dir)
    copy_publishable_pipeline_files(manifest, base_dir, publish_dir, verbose=verbose)
    revise_published_chartbook_toml(publish_dir)


if __name__ == "__main__":
    pass
