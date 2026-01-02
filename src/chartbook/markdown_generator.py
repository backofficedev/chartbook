"""
NOTES:

- Dataframe names must have no spaces, and must start with an alphabetic character.

"""

import importlib.resources  # Add this at the top with other imports
import os
import shutil
from pathlib import Path

import jinja2
import polars as pl

from chartbook.manifest import (
    get_file_modified_datetime,
    get_pipeline_ids,
    get_pipeline_manifest,
    load_manifest,
)
from chartbook.utils import copy_according_to_plan, get_dataframe_glimpse

BASE_DIR = Path(".").resolve()
DOCS_BUILD_DIR = BASE_DIR / Path("_docs")
DOCS_SRC_DIR = BASE_DIR / Path("_docs_src")


def get_sphinx_file_alignment_plan(base_dir=BASE_DIR, docs_build_dir=DOCS_BUILD_DIR):
    manifest = load_manifest(base_dir=base_dir)
    pipeline_ids = get_pipeline_ids(manifest)

    dataset_plan = {}
    chart_plan_download = {}
    chart_plan_static = {}
    notebook_plan = {}

    for pipeline_id in pipeline_ids:
        download_chart_dir_download = (
            Path(docs_build_dir) / "download_chart" / str(pipeline_id)
        )
        download_chart_dir_static = Path(docs_build_dir) / "_static" / str(pipeline_id)
        download_dataframe_dir = (
            Path(docs_build_dir) / "download_dataframe" / str(pipeline_id)
        )
        notebook_dir = Path(docs_build_dir) / "notebooks" / str(pipeline_id)

        download_chart_dir_download.mkdir(parents=True, exist_ok=True)
        download_dataframe_dir.mkdir(parents=True, exist_ok=True)
        download_chart_dir_static.mkdir(parents=True, exist_ok=True)
        notebook_dir.mkdir(parents=True, exist_ok=True)

        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest["pipeline_base_dir"])
        for dataframe_id in pipeline_manifest["dataframes"]:
            dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

            path_to_parquet_data = dataframe_manifest["path_to_parquet_data"]
            if (path_to_parquet_data is None) or (path_to_parquet_data == ""):
                pass
            else:
                file_path = pipeline_base_dir / Path(path_to_parquet_data)
                dataset_plan[file_path] = (
                    download_dataframe_dir / f"{dataframe_id}.parquet"
                )

        for chart_id in pipeline_manifest["charts"]:
            # Plan for copying HTML chart to download folder
            chart_manifest = pipeline_manifest["charts"][chart_id]
            path_to_html_chart = Path(chart_manifest["path_to_html_chart"])
            file_path = pipeline_base_dir / path_to_html_chart
            chart_plan_download[file_path] = (
                download_chart_dir_download / f"{chart_id}.html"
            )

            # Plan for copying HTML chart to _static folder for display
            chart_manifest = pipeline_manifest["charts"][chart_id]
            path_to_html_chart = Path(chart_manifest["path_to_html_chart"])
            file_path = pipeline_base_dir / path_to_html_chart
            chart_plan_static[file_path] = (
                download_chart_dir_static / f"{chart_id}.html"
            )

        for notebook_id in pipeline_manifest["notebooks"]:
            notebook_path = pipeline_manifest["notebooks"][notebook_id]["notebook_path"]
            notebook_path = pipeline_base_dir / Path(notebook_path)
            notebook_path = notebook_path.resolve()
            notebook_name = notebook_path.name
            notebook_plan[notebook_path] = notebook_dir / f"{notebook_name}"

    return (
        dataset_plan,
        chart_plan_download,
        chart_plan_static,
        notebook_plan,
    )


def generate_all_pipeline_docs(
    manifest,
    docs_build_dir=DOCS_BUILD_DIR,
    base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
):
    """
    Params
    ------
    manifest: dict
        This is a dict that contains manifest for all pipelines to be processed.
    docs_build_dir: Path
        This is the output directory, where all generated docs will be placed.
    base_dir: Path
        This is used to identify the inputs. It's the base directory of the current project.
        This is used to tell
        the docs builder where all templates are stored, since the pipeline requires
        that they be stored in a consistent spot relative to the base directory
        of the project.
    docs_src_dir: Path
        The directory containing documentation source files and templates.
    size_threshold: float
        File size threshold in MB above which to use memory-efficient loading.
    """
    base_dir = Path(base_dir).resolve()
    docs_src_dir = Path(docs_src_dir)

    pipeline_ids = get_pipeline_ids(manifest)

    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest["pipeline_base_dir"])

        generate_pipeline_docs(
            pipeline_id,
            pipeline_manifest,
            pipeline_base_dir=pipeline_base_dir,
            docs_build_dir=docs_build_dir,
            pipeline_theme=pipeline_theme,
            docs_src_dir=docs_src_dir,
            size_threshold=size_threshold,
        )
        pipeline_theme = pipeline_manifest["config"]["type"]
        if pipeline_theme == "catalog":
            # Copy pipeline README to pipelines directory
            pipeline_readme_dir = docs_build_dir / "pipelines"
            pipeline_readme_dir.mkdir(parents=True, exist_ok=True)

            source_path = pipeline_base_dir / "README.md"
            with open(source_path) as file:
                readme_content = file.readlines()

            # Remove the first two lines, add line with link to pipeline GitHub repo and
            # to index.html in html build dir, and then join the rest of the README.
            pipeline_name = pipeline_manifest["pipeline_name"]
            git_repo_URL = pipeline_manifest["git_repo_URL"]
            readme_text = f"# `{pipeline_id}` {pipeline_name} \n\n " + (
                f'Pipeline GitHub Repo <a href="{git_repo_URL}">{git_repo_URL}.</a>\n\n\n'
                + f'Pipeline Web Page <a href="{git_repo_URL}">{git_repo_URL}.</a>\n\n\n'
                + "".join(readme_content[2:])
            )

            readme_destination_filepath = (
                pipeline_readme_dir / f"{pipeline_id}_README.md"
            )
            file_path = readme_destination_filepath
            with open(file_path, mode="w", encoding="utf-8") as file:
                file.write(readme_text)

    ## Dataframe and Pipeline List in index.md
    table_file_map = get_dataframes_and_dataframe_docs(base_dir=base_dir)
    dataframe_file_list = list(table_file_map.values())

    # Get package templates directory
    package_templates_dir = get_package_templates_path()

    # Get package-specific template directory based on pipeline theme
    package_path = importlib.resources.files("chartbook")

    # Determine which template directory to use based on pipeline_theme
    pipeline_theme = manifest["config"]["type"]
    if pipeline_theme == "catalog":
        theme_template_dir = Path(str(package_path)) / "docs_src_catalog"
    elif pipeline_theme == "pipeline":
        theme_template_dir = Path(str(package_path)) / "docs_src_pipeline"
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

    # Modified environment setup to include appropriate template locations
    template_search_paths = [
        base_dir,
        docs_src_dir,
        docs_src_dir / "_templates",  # Add explicit templates subdir
        package_templates_dir,  # Add package templates directory
        theme_template_dir,  # Add theme-specific directory
        theme_template_dir / "_templates",  # Add theme-specific templates subdir
    ]

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_search_paths)
    )

    if pipeline_theme == "catalog":
        # Render dataframe.md
        template_path = "dataframes.md"
        template = environment.get_template(template_path)
        rendered_page = template.render(
            dataframe_file_list=dataframe_file_list,
            # docs_src_dir=docs_src_dir.relative_to(base_dir)  # Pass relative path
        )
        # Copy to build directory
        file_path = docs_build_dir / "dataframes.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(rendered_page)

        # Render pipelines.md
        template_path = "pipelines.md"
        template = environment.get_template(template_path)
        rendered_page = template.render(
            manifest=manifest,
            dot_or_dotdot="..",
            docs_src_dir=docs_src_dir.relative_to(base_dir),  # Pass relative path
        )
        # Copy to build directory
        file_path = docs_build_dir / "pipelines.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(rendered_page)

        # Render diagnostics.md
        template_path = "diagnostics.md"
        template = environment.get_template(template_path)

        # Load diagnostics data from CSV
        diagnostics_csv_path = (
            docs_build_dir
            / "_static"
            / "diagnostics"
            / "chartbook_metadata_diagnostics.csv"
        )
        diagnostics_data = []
        diagnostics_summary = None

        if diagnostics_csv_path.exists():
            import pandas as pd

            df = pd.read_csv(diagnostics_csv_path)

            # Convert Page Link from CSV format (../charts/...) to HTML format (./charts/...)
            # for use in the diagnostics.html page
            df["Page Link (HTML)"] = df["Page Link"].str.replace(
                "../", "./", regex=False
            )

            diagnostics_data = df.to_dict("records")

            # Calculate summary statistics
            diagnostics_summary = {
                "total_count": len(df),
                "complete_count": int(df["Metadata Complete"].sum()),
                "incomplete_count": int(len(df) - df["Metadata Complete"].sum()),
                "complete_pct": round(100 * df["Metadata Complete"].mean(), 1),
                "incomplete_pct": round(100 * (1 - df["Metadata Complete"].mean()), 1),
            }

        # Import field counts from diagnostics module
        from chartbook.diagnostics import (
            CHART_FIELDS,
            DATAFRAME_FIELDS,
            PIPELINE_FIELDS,
        )

        rendered_page = template.render(
            diagnostics_data=diagnostics_data,
            diagnostics_summary=diagnostics_summary,
            pipeline_field_count=len(PIPELINE_FIELDS),
            dataframe_field_count=len(DATAFRAME_FIELDS),
            chart_field_count=len(CHART_FIELDS),
        )

        file_path = docs_build_dir / "diagnostics.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(rendered_page)

        readme_text = ""

        # Render and copy index.md in chart haven theme
        template_path = "index.md"
        template = environment.get_template(template_path)
        index_page = template.render(
            manifest=manifest,
            dataframe_file_list=dataframe_file_list,
            pipeline_manifest=pipeline_manifest,
            readme_text=readme_text,
            pipeline_page_link=f"./pipelines/{pipeline_id}_README.md",
            dot_or_dotdot=".",
        )
        file_path = docs_build_dir / "index.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(index_page)

    elif pipeline_theme == "pipeline":
        source_path = base_dir / "README.md"
        with open(source_path) as file:
            readme_content = file.readlines()

        # Remove the first two lines and join the rest
        readme_text = "".join(readme_content[2:])

        notebook_list = [
            f"notebooks/{pipeline_id}/{Path(notebook).name}"
            for notebook in pipeline_manifest["notebooks"]
        ]

        # Handle markdown notes if they exist
        notes_list = []
        if "notes" in pipeline_manifest:
            # Copy markdown files to docs build directory
            for note_id in pipeline_manifest["notes"]:
                note_manifest = pipeline_manifest["notes"][note_id]
                source_file = note_manifest["full_path"]

                # Copy to root of docs build directory with note_id as filename
                dest_file = docs_build_dir / f"{note_id}.md"
                shutil.copy(source_file, dest_file)

                # Add to notes list for template
                notes_list.append(f"{note_id}.md")

        # Render and copy index.md in pipeline themes
        template_path = "index.md"
        template = environment.get_template(template_path)
        index_page = template.render(
            manifest=manifest,
            dataframe_file_list=dataframe_file_list,
            pipeline_manifest=pipeline_manifest,
            readme_text=readme_text,
            pipeline_page_link="./index.md",
            dot_or_dotdot=".",
            pipeline_id=pipeline_id,
            notebook_list=notebook_list,
            notes_list=notes_list,
        )
        file_path = docs_build_dir / "index.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(index_page)

    else:
        raise ValueError("Invalid Pipeline theme")


def generate_pipeline_docs(
    pipeline_id,
    pipeline_manifest,
    pipeline_base_dir=BASE_DIR,
    docs_build_dir=DOCS_BUILD_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
):
    for dataframe_id in pipeline_manifest["dataframes"]:
        generate_dataframe_docs(
            dataframe_id,
            pipeline_id,
            pipeline_manifest,
            docs_build_dir,
            pipeline_base_dir=pipeline_base_dir,
            pipeline_theme=pipeline_theme,
            docs_src_dir=docs_src_dir,
            size_threshold=size_threshold,
        )

    for chart_id in pipeline_manifest["charts"]:
        generate_chart_docs(
            chart_id,
            pipeline_id,
            pipeline_manifest,
            docs_build_dir,
            pipeline_base_dir=pipeline_base_dir,
            pipeline_theme=pipeline_theme,
            docs_src_dir=docs_src_dir,
        )


def get_package_templates_path() -> Path:
    """Get path to templates directory in the package"""
    package_path = importlib.resources.files("chartbook")
    return Path(str(package_path)) / "templates"


def generate_dataframe_docs(
    dataframe_id,
    pipeline_id,
    pipeline_manifest,
    docs_build_dir=DOCS_BUILD_DIR,
    pipeline_base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
):
    """
    Generates documentation for a specific dataframe, including the most recent data dates.

    Params
    ------
    dataframe_id: str
        The identifier for the dataframe.
    pipeline_id: str
        The identifier for the pipeline.
    pipeline_manifest: dict
        Manifest for the pipeline.
    docs_build_dir: Path
        The directory where the docs will be built.
    base_dir: Path
        The base directory of the pipeline project folder.
    docs_src_dir: Path
        The directory containing documentation source files and templates.
    size_threshold: float
        File size threshold in MB above which to use memory-efficient loading.
    """
    dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

    dataframe_docs_dir = docs_build_dir / "dataframes" / pipeline_id
    dataframe_docs_dir.mkdir(parents=True, exist_ok=True)

    # Get package templates directory
    package_templates_dir = get_package_templates_path()

    # Get package-specific template directory based on pipeline theme
    package_path = importlib.resources.files("chartbook")

    # Determine which template directory to use based on pipeline_theme
    if pipeline_theme == "catalog":
        theme_template_dir = Path(str(package_path)) / "docs_src_catalog"
    elif pipeline_theme == "pipeline":
        theme_template_dir = Path(str(package_path)) / "docs_src_pipeline"
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

    # Add package templates to the search paths
    template_search_paths = [
        pipeline_base_dir,
        docs_src_dir,
        docs_src_dir / "_templates",  # Add explicit templates subdir
        package_templates_dir,  # Add package templates directory
        theme_template_dir,  # Add theme-specific directory
        theme_template_dir / "_templates",  # Add theme-specific templates subdir
    ]

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_search_paths)
    )

    # Load doc content based on mode (path or inline string)
    doc_mode = dataframe_manifest.get("_doc_mode", "path")
    if doc_mode == "path":
        path_to_dataframe_doc = Path(dataframe_manifest["dataframe_docs_path"]).as_posix()
        source = environment.loader.get_source(environment, path_to_dataframe_doc)[0]
    else:  # doc_mode == "str"
        source = dataframe_manifest["dataframe_docs_str"]

    # Use filenames instead of paths for includes, so they can be found in any of our search locations
    modified_source = (
        """# Dataframe: `{{pipeline_id}}:{{dataframe_id}}` - {{dataframe_name}}\n\n"""
        + source
        + """\n\n
## DataFrame Glimpse

```
{{dataframe_glimpse}}
```

## Dataframe Manifest

{% include "dataframe_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}

"""
    )

    template = environment.from_string(modified_source)

    # The name of the date column in the parquet file (default: "date").
    date_col = dataframe_manifest["date_col"]

    if pipeline_theme == "pipeline":
        pipeline_page_link = "../index.md"
        dataframe_path_prefix = "../dataframes/"
    elif pipeline_theme == "catalog":
        pipeline_page_link = f"../pipelines/{pipeline_id}_README.md"
        dataframe_path_prefix = ""
    else:
        raise ValueError("Invalid Pipeline theme")
    link_to_dataframe_docs = (
        Path(dataframe_path_prefix) / pipeline_id / f"{dataframe_id}.md"
    ).as_posix()
    # Compute the absolute path to the parquet file
    parquet_path = (
        pipeline_base_dir / dataframe_manifest["path_to_parquet_data"]
    ).resolve()

    # Process the parquet file and get the min and max dates
    try:
        most_recent_data_min, most_recent_data_max = find_most_recent_valid_datapoints(
            parquet_path, date_col, size_threshold_mb=size_threshold
        )
    except:
        most_recent_data_min, most_recent_data_max = None, None

    # Get the dataframe glimpse
    dataframe_glimpse = get_dataframe_glimpse(
        parquet_path, size_threshold_mb=size_threshold
    )

    # Render the template with the new variables
    table_page = template.render(
        dataframe_manifest,
        dataframe_manifest=dataframe_manifest,
        link_to_dataframe_docs=link_to_dataframe_docs,
        dataframe_id=dataframe_id,
        pipeline_id=pipeline_id,
        pipeline_manifest=pipeline_manifest,
        pipeline_page_link=pipeline_page_link,
        most_recent_data_min=most_recent_data_min,
        most_recent_data_max=most_recent_data_max,
        dot_or_dotdot="..",
        dataframe_glimpse=dataframe_glimpse,
    )
    # print(table_page)

    filename = f"{dataframe_id}.md"
    file_path = dataframe_docs_dir / filename
    with open(file_path, mode="w", encoding="utf-8") as file:
        file.write(table_page)


def find_most_recent_valid_datapoints(
    parquet_path, date_col="date", size_threshold_mb=50
):
    """
    date_col:
        The name of the date column in the parquet file (default: "date").
    size_threshold_mb:
        File size threshold in MB above which to skip this computation (default: 50).
    """
    if (date_col == "") or (date_col == "NA") or (date_col == "N/A"):
        return "N/A", "N/A"

    # Check file size - skip for large files to avoid OOM
    file_size_mb = os.path.getsize(parquet_path) / (1024 * 1024)
    if file_size_mb > size_threshold_mb:
        return "N/A (large file)", "N/A (large file)"

    # Read the parquet file using Polars
    df = pl.read_parquet(parquet_path)

    # Ensure date_col is of datetime type for proper comparison
    if df[date_col].dtype != pl.Datetime:
        df = df.with_columns(pl.col(date_col).cast(pl.Datetime, strict=False))

    # Compute the most recent date where each column is not null
    most_recent_dates = df.select(
        [
            pl.col(date_col).filter(pl.col(col).is_not_null()).max().alias(col)
            for col in df.columns
            if col != date_col
        ]
    )

    # Extract the dates and filter out None values
    dates_list = [date for date in most_recent_dates.row(0) if date is not None]

    # Compute min and max dates
    if dates_list:
        most_recent_data_min = min(dates_list).strftime("%Y-%m-%d %H:%M:%S")
        most_recent_data_max = max(dates_list).strftime("%Y-%m-%d %H:%M:%S")
    else:
        most_recent_data_min = "N/A"
        most_recent_data_max = "N/A"

    return most_recent_data_min, most_recent_data_max


def generate_chart_docs(
    chart_id,
    pipeline_id,
    pipeline_manifest,
    docs_build_dir=DOCS_BUILD_DIR,
    pipeline_base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
):
    pipeline_base_dir = Path(pipeline_base_dir)

    # Get all manifest related to the chart
    chart_manifest = pipeline_manifest["charts"][chart_id]
    dataframe_id = chart_manifest["dataframe_id"]
    dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

    # Get package templates directory
    package_templates_dir = get_package_templates_path()

    # Get package-specific template directory based on pipeline theme
    package_path = importlib.resources.files("chartbook")

    # Determine which template directory to use based on pipeline_theme
    if pipeline_theme == "catalog":
        theme_template_dir = Path(str(package_path)) / "docs_src_catalog"
    elif pipeline_theme == "pipeline":
        theme_template_dir = Path(str(package_path)) / "docs_src_pipeline"
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

    # Add package templates to the search paths
    template_search_paths = [
        pipeline_base_dir,
        docs_src_dir,
        docs_src_dir / "_templates",  # Add explicit templates subdir
        package_templates_dir,  # Add package templates directory
        theme_template_dir,  # Add theme-specific directory
        theme_template_dir / "_templates",  # Add theme-specific templates subdir
    ]

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_search_paths)
    )

    # Load doc content based on mode (path or inline string)
    doc_mode = chart_manifest.get("_doc_mode", "path")
    if doc_mode == "path":
        path_to_chart_doc = Path(chart_manifest["chart_docs_path"]).as_posix()
        source = environment.loader.get_source(environment, path_to_chart_doc)[0]
    else:  # doc_mode == "str"
        source = chart_manifest["chart_docs_str"]

    # Use filenames instead of paths for includes
    modified_source = (
        """{% include "chart_entry_top.md" %}
\n\n
"""
        + source
        + """\n\n
{% include "chart_entry_bottom.md" %}
"""
    )

    template = environment.from_string(modified_source)

    if pipeline_theme == "pipeline":
        pipeline_page_link = "../index.md"
        dataframe_path_prefix = "../dataframes/"
    elif pipeline_theme == "catalog":
        pipeline_page_link = f"../pipelines/{pipeline_id}_README.md"
        dataframe_path_prefix = "../dataframes/"
    else:
        raise ValueError("Invalid Pipeline theme")

    # Compute the absolute path to the parquet file
    parquet_path = (
        pipeline_base_dir / dataframe_manifest["path_to_parquet_data"]
    ).resolve()

    # Fetch the last modified datetime of the parquet file
    dataframe_last_updated = get_file_modified_datetime(parquet_path)

    # Get and format paths to charts
    path_to_html_chart_unix = pipeline_base_dir / Path(
        chart_manifest["path_to_html_chart"]
    )

    link_to_dataframe_docs = (
        Path(dataframe_path_prefix) / pipeline_id / f"{dataframe_id}.md"
    ).as_posix()

    # Render chart page
    chart_page = template.render(
        chart_manifest,
        chart_manifest=chart_manifest,
        chart_id=chart_id,
        dataframe_id=dataframe_id,
        dataframe_manifest=dataframe_manifest,
        link_to_dataframe_docs=link_to_dataframe_docs,
        pipeline_id=pipeline_id,
        pipeline_manifest=pipeline_manifest,
        path_to_html_chart_unix=path_to_html_chart_unix,
        pipeline_page_link=pipeline_page_link,
        dataframe_last_updated=dataframe_last_updated.strftime("%Y-%m-%d %H:%M:%S"),
        dot_or_dotdot="..",
    )
    # print(chart_page)

    (docs_build_dir / "charts").mkdir(parents=True, exist_ok=True)
    filename = f"{pipeline_id}.{chart_id}.md"
    file_path = docs_build_dir / "charts" / filename
    with open(file_path, mode="w", encoding="utf-8") as file:
        file.write(chart_page)


def get_dataframes_and_dataframe_docs(base_dir=BASE_DIR):
    manifest = load_manifest(base_dir=base_dir)
    pipeline_ids = get_pipeline_ids(manifest)
    table_file_map = {}
    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for dataframe_id in pipeline_manifest["dataframes"]:
            filename = Path(f"{dataframe_id}.md")
            file_path = Path("dataframes") / pipeline_id / filename
            pipeline_dataframe_id = f"{pipeline_id}:{dataframe_id}"
            table_file_map[pipeline_dataframe_id] = file_path.as_posix()
    return table_file_map


def copy_docs_src_to_build(docs_src_dir, docs_build_dir, exclude_list=None):
    """
    Copies files from docs_src to _docs directory while excluding specified paths.
    Similar to: rsync -lr --exclude=... ./docs_src/ ./_docs/

    Parameters
    ----------
    docs_src_dir : Union[str, Path]
        Source directory (docs_src)
    docs_build_dir : Union[str, Path]
        Destination directory (_docs)
    exclude_list : list, optional
        List of files and directories to exclude. Defaults to common exclusions.
    """
    if exclude_list is None:
        exclude_list = [
            "charts",
            "dataframes",
            "notebooks",
            "index.md",
            "pipelines.md",
            "dataframes.md",
            "diagnostics.md",
        ]

    docs_src_dir = Path(docs_src_dir)
    docs_build_dir = Path(docs_build_dir)

    # Create the destination directory if it doesn't exist
    docs_build_dir.mkdir(parents=True, exist_ok=True)

    def should_copy(path):
        """Check if the path should be copied based on exclusion rules"""
        for excluded in exclude_list:
            if excluded in path.parts:
                return False
        return True

    # Walk through the source directory
    for src_path in docs_src_dir.rglob("*"):
        # Skip if path matches exclusion rules
        if not should_copy(src_path):
            continue

        # Calculate relative path to maintain directory structure
        rel_path = src_path.relative_to(docs_src_dir)
        dst_path = docs_build_dir / rel_path

        if src_path.is_file():
            # Create parent directories if they don't exist
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy the file content only, without attempting to copy permissions
            shutil.copyfile(src_path, dst_path)

            # Try to set reasonable permissions after copying
            try:
                os.chmod(dst_path, 0o644)  # rw-r--r-- for files
            except (OSError, PermissionError):
                # If we can't set permissions, just continue
                pass


def build_all(
    docs_build_dir=DOCS_BUILD_DIR,
    base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
):
    """
    Params
    ------
    docs_build_dir: Path
        This is the output directory, where all generated docs will be placed. This is
        usually the _docs directory
    base_dir: Path
        This is used to identify the inputs. It's the base directory of the current project.
    pipeline_theme: str
        This is the theme of the pipeline. It can be "pipeline" or "catalog".
    docs_src_dir: Path
        This is the directory containing the documentation source files. This will
        usually be the _docs_src directory.
    size_threshold: float
        File size threshold in MB above which to use memory-efficient loading.
    """
    docs_build_dir.mkdir(parents=True, exist_ok=True)

    ## Align files for use by Sphinx
    manifest = load_manifest(base_dir=base_dir)

    (
        dataset_plan,
        chart_plan_download,
        chart_plan_static,
        notebook_plan,
    ) = get_sphinx_file_alignment_plan(base_dir=base_dir, docs_build_dir=docs_build_dir)

    copy_according_to_plan(dataset_plan)
    copy_according_to_plan(chart_plan_download)
    copy_according_to_plan(chart_plan_static)
    copy_according_to_plan(notebook_plan)

    generate_all_pipeline_docs(
        manifest,
        docs_build_dir=docs_build_dir,
        base_dir=base_dir,
        pipeline_theme=pipeline_theme,
        docs_src_dir=docs_src_dir,
        size_threshold=size_threshold,
    )

    # Copy remaining docs_src files to build directory
    copy_docs_src_to_build(docs_src_dir, docs_build_dir)


# def _demo():
#     specs = read_specs(base_dir=BASE_DIR)
#     len(specs["charts"])
#     len(specs["dataframes"])

#     # Used for injection into index.md
#     table_file_map = get_dataframes_and_dataframe_docs(base_dir=BASE_DIR)
#     table_file_map

#     # Used for moving files into download folder. Dict shows where files will be copied from and to
#     dataset_plan, chart_plan_download, chart_plan_static, notebook_plan = (
#         get_sphinx_file_alignment_plan(base_dir=BASE_DIR, docs_build_dir=DOCS_BUILD_DIR)
#     )
#     publish_plan = (
#         dataset_plan | chart_plan_download | chart_plan_static | notebook_plan
#     )
#     list(publish_plan.keys())
#     list(publish_plan.values())


if __name__ == "__main__":
    pass
