"""
NOTES:

- Dataframe names must have no spaces, and must start with an alphabetic character.

"""

import glob
import importlib.resources  # Add this at the top with other imports
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import jinja2
import polars as pl
import yaml

from chartbook.errors import ChartBookError
from chartbook.hashing import directory_files
from chartbook.manifest import (
    apply_code_change_times,
    get_file_modified_datetime,
    get_pipeline_ids,
    get_pipeline_manifest,
    load_manifest,
)
from chartbook.utils import copy_according_to_plan, get_dataframe_glimpse, is_glob_pattern

BASE_DIR = Path(".").resolve()
DOCS_BUILD_DIR = BASE_DIR / Path("_docs")
DOCS_SRC_DIR = BASE_DIR / Path("_docs_src")


def _fs_slug(pipeline_id):
    """Filesystem/URL-safe form of a (possibly scoped) pipeline ID.

    Scoped IDs contain a slash (``ftsfr/crsp_treasury``); generated docs
    paths flatten it to ``ftsfr--crsp_treasury`` so pages stay one level
    deep and relative links keep working.
    """
    return str(pipeline_id).replace("/", "--")


def _yaml_escape_filter(value):
    """Escape double quotes in a string for safe use inside YAML double-quoted scalars."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def data_last_modified(data_path):
    """Find when the data at a path was last written, by file modification time.

    For a partitioned dataframe (a glob path) this is its newest part file.

    :param data_path: Path to a data file, or a glob pattern over part files.
    :type data_path: str or Path
    :returns: The modification time, or None if nothing is on disk.
    :rtype: datetime or None
    """
    if is_glob_pattern(str(data_path)):
        part_files = glob.glob(str(data_path), recursive=True)
        if not part_files:
            return None
        return max(get_file_modified_datetime(f) for f in part_files)
    if not Path(data_path).exists():
        return None
    return get_file_modified_datetime(data_path)


def freshness_fact(label, moment):
    """Describe one "<label> <when>" fact for a page's freshness line.

    The page says *when*, not *how long ago*: a generated page is static, so
    "2 days ago" worked out at build time would be wrong the next day, and
    would also make every page differ from one build to the next. The
    timestamp goes into a ``<time>`` element and ``chartbook-freshness.js``
    turns it into relative wording when the page is read.

    :param label: The plain-language lead-in, e.g. ``"Data updated"``.
    :type label: str
    :param moment: When it happened, in local time. None if unknown.
    :type moment: datetime or None
    :returns: Template fields ``label``, ``iso`` (ISO 8601 with UTC offset),
        ``title`` (for the hover text) and ``date`` (the fallback text), or
        None when *moment* is None.
    :rtype: dict or None
    """
    if moment is None:
        return None
    local = moment.astimezone()
    return {
        "label": label,
        "iso": local.isoformat(timespec="seconds"),
        "title": local.strftime("%Y-%m-%d %H:%M %Z").strip(),
        "date": local.strftime("%Y-%m-%d"),
    }


def _code_last_modified(pipeline_manifest):
    """When the pipeline's source last changed, from its loaded manifest."""
    stamp = pipeline_manifest.get("source_last_modified_date")
    if not stamp:
        return None
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")


def get_sphinx_file_alignment_plan(
    base_dir=BASE_DIR, docs_build_dir=DOCS_BUILD_DIR, enable_data_download=False,
    skip_pipelines=None,
):
    """Get file alignment plans for copying files to the Sphinx build directory.

    :param base_dir: The base directory of the project.
    :type base_dir: Path
    :param docs_build_dir: The directory where documentation will be built.
    :type docs_build_dir: Path
    :param enable_data_download: Whether to enable copying parquet data files.
    :type enable_data_download: bool
    :param skip_pipelines: Set of pipeline IDs to skip.
    :type skip_pipelines: set[str] | None
    :returns: A tuple of (dataset_plan, chart_plan_download, chart_plan_static, notebook_plan).
    :rtype: tuple[dict, dict, dict, dict]
    """
    manifest = load_manifest(base_dir=base_dir)
    pipeline_ids = get_pipeline_ids(manifest)

    dataset_plan = {}
    chart_plan_download = {}
    chart_plan_static = {}
    notebook_plan = {}

    for pipeline_id in pipeline_ids:
        if skip_pipelines and pipeline_id in skip_pipelines:
            continue
        pipeline_slug = _fs_slug(pipeline_id)
        download_chart_dir_download = (
            Path(docs_build_dir) / "cb" / "download_chart" / pipeline_slug
        )
        download_chart_dir_static = Path(docs_build_dir) / "_static" / pipeline_slug
        notebook_dir = Path(docs_build_dir) / "cb" / "notebooks" / pipeline_slug

        download_chart_dir_download.mkdir(parents=True, exist_ok=True)
        download_chart_dir_static.mkdir(parents=True, exist_ok=True)
        notebook_dir.mkdir(parents=True, exist_ok=True)

        # Only create download_dataframe directory when data downloads are enabled
        if enable_data_download:
            download_dataframe_dir = (
                Path(docs_build_dir) / "cb" / "download_dataframe" / pipeline_slug
            )
            download_dataframe_dir.mkdir(parents=True, exist_ok=True)

        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest["pipeline_base_dir"])

        # Only populate dataset_plan when data downloads are enabled
        if enable_data_download:
            for dataframe_id in pipeline_manifest["dataframes"]:
                dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

                parquet_path = dataframe_manifest.get("path", "")
                if (parquet_path is None) or (parquet_path == ""):
                    pass
                elif is_glob_pattern(parquet_path):
                    # Skip file copy for glob/hive-partitioned datasets
                    pass
                else:
                    file_path = pipeline_base_dir / Path(parquet_path)
                    dataset_plan[file_path] = (
                        download_dataframe_dir / f"{dataframe_id}.parquet"
                    )

        for chart_id in pipeline_manifest["charts"]:
            chart_manifest = pipeline_manifest["charts"][chart_id]
            chart_html_path = chart_manifest.get("path", "")
            if not chart_html_path:
                continue
            file_path = pipeline_base_dir / Path(chart_html_path)
            # Copy the HTML chart to both the download folder and _static (display)
            chart_plan_download[file_path] = (
                download_chart_dir_download / f"{chart_id}.html"
            )
            chart_plan_static[file_path] = (
                download_chart_dir_static / f"{chart_id}.html"
            )

        for notebook_id in pipeline_manifest["notebooks"]:
            notebook_path = pipeline_manifest["notebooks"][notebook_id]["path"]
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
    enable_data_download=False,
    skip_pipelines=None,
    reuse_pipelines=None,
):
    """Generate documentation for all pipelines in the manifest.

    :param manifest: A dict that contains manifest for all pipelines to be processed.
    :type manifest: dict
    :param docs_build_dir: The output directory, where all generated docs will be placed.
    :type docs_build_dir: Path
    :param base_dir: The base directory of the current project. This is used to tell
        the docs builder where all templates are stored.
    :type base_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing documentation source files and templates.
    :type docs_src_dir: Path
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param enable_data_download: Whether to enable data download links in documentation.
    :type enable_data_download: bool
    :param skip_pipelines: Set of pipeline IDs to skip.
    :type skip_pipelines: set[str] | None
    :param reuse_pipelines: Set of pipeline IDs that are part of the site but
        whose own pages are not regenerated, because an incremental build is
        keeping the ones it already has. The site-wide pages still list them.
    :type reuse_pipelines: set[str] | None
    """
    base_dir = Path(base_dir).resolve()
    docs_src_dir = Path(docs_src_dir)

    pipeline_ids = get_pipeline_ids(manifest)

    for pipeline_id in pipeline_ids:
        if skip_pipelines and pipeline_id in skip_pipelines:
            continue
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        pipeline_base_dir = Path(pipeline_manifest["pipeline_base_dir"])
        if reuse_pipelines and pipeline_id in reuse_pipelines:
            continue

        generate_pipeline_docs(
            pipeline_id,
            pipeline_manifest,
            pipeline_base_dir=pipeline_base_dir,
            docs_build_dir=docs_build_dir,
            pipeline_theme=pipeline_theme,
            docs_src_dir=docs_src_dir,
            size_threshold=size_threshold,
            enable_data_download=enable_data_download,
            site_manifest=manifest,
        )
        if pipeline_theme == "catalog":
            # Copy pipeline README to pipelines directory
            pipeline_readme_dir = docs_build_dir / "cb" / "pipelines"
            pipeline_readme_dir.mkdir(parents=True, exist_ok=True)

            source_path = pipeline_base_dir / pipeline_manifest["project"]["readme"]
            with open(source_path) as file:
                readme_content = file.readlines()

            # Remove the first two lines, add line with link to pipeline GitHub repo and
            # to index.html in html build dir, and then join the rest of the README.
            pipeline_name = pipeline_manifest["project"]["name"]
            repo_url = pipeline_manifest["project"]["repo_url"]
            site_url = pipeline_manifest["project"]["site_url"]
            readme_text = f"# `{pipeline_id}` {pipeline_name} \n\n " + (
                f'Pipeline GitHub Repo <a href="{repo_url}">{repo_url}.</a>\n\n\n'
                + f'Pipeline Web Page <a href="{site_url}">{site_url}.</a>\n\n\n'
                + "".join(readme_content[2:])
            )

            readme_destination_filepath = (
                pipeline_readme_dir / f"{_fs_slug(pipeline_id)}_README.md"
            )
            file_path = readme_destination_filepath
            with open(file_path, mode="w", encoding="utf-8") as file:
                file.write(readme_text)

    ## Dataframe and Pipeline List in index.md
    table_file_map = get_dataframes_and_dataframe_docs(base_dir=base_dir)
    dataframe_file_list = list(table_file_map.values())
    # Models of every pipeline in the site, skipped ones aside
    model_file_list = [
        path
        for model_ref, path in get_model_docs(manifest).items()
        if model_ref.split(":model/")[0] not in (skip_pipelines or ())
    ]

    # Get package templates directory
    package_templates_dir = get_package_templates_path()

    # Get package-specific template directory based on pipeline theme
    package_path = importlib.resources.files("chartbook")

    # Determine which template directory to use based on pipeline_theme
    pipeline_theme = manifest["project"]["type"]
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
            dataframe_file_list=[p.removeprefix("cb/") for p in dataframe_file_list],
        )
        # Copy to build directory
        (docs_build_dir / "cb").mkdir(parents=True, exist_ok=True)
        file_path = docs_build_dir / "cb" / "dataframes.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(rendered_page)

        # Render models.md, when some pipeline declares a model
        if model_file_list:
            rendered_page = environment.get_template("models.md").render(
                model_file_list=[p.removeprefix("cb/") for p in model_file_list],
            )
            with open(docs_build_dir / "cb" / "models.md", mode="w", encoding="utf-8") as file:
                file.write(rendered_page)

        # Render pipelines.md
        template_path = "pipelines.md"
        template = environment.get_template(template_path)
        rendered_page = template.render(
            manifest=manifest,
            dot_or_dotdot=".",
            docs_src_dir=docs_src_dir.relative_to(base_dir),  # Pass relative path
            show_code_updated=True,
        )
        # Copy to build directory
        file_path = docs_build_dir / "cb" / "pipelines.md"
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

            # Page links are already relative to the cb/ directory
            df["Page Link (HTML)"] = df["Page Link"]

            diagnostics_data = df.to_dict("records")

            # Calculate summary statistics
            diagnostics_summary = {
                "total_count": len(df),
                "complete_count": int(df["Metadata Complete"].sum()),
                "incomplete_count": int(len(df) - df["Metadata Complete"].sum()),
                "complete_pct": round(100 * df["Metadata Complete"].mean(), 1),
                "incomplete_pct": round(100 * (1 - df["Metadata Complete"].mean()), 1),
            }

        # Required fields come from the catalog's [policy] (or defaults)
        from chartbook.diagnostics import get_active_policy

        required_fields = get_active_policy(manifest)["required"]

        rendered_page = template.render(
            diagnostics_data=diagnostics_data,
            diagnostics_summary=diagnostics_summary,
            required_fields=required_fields,
            pipeline_field_count=len(required_fields["project"]),
            dataframe_field_count=len(required_fields["dataframes"]),
            chart_field_count=len(required_fields["charts"]),
        )

        file_path = docs_build_dir / "cb" / "diagnostics.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(rendered_page)

        readme_text = ""

        # Render and copy index.md in chart haven theme
        template_path = "index.md"
        template = environment.get_template(template_path)
        index_page = template.render(
            manifest=manifest,
            dataframe_file_list=dataframe_file_list,
            model_file_list=model_file_list,
            pipeline_manifest=pipeline_manifest,
            readme_text=readme_text,
            pipeline_page_link=f"cb/pipelines/{_fs_slug(pipeline_id)}_README.md",
            dot_or_dotdot="cb",
        )
        file_path = docs_build_dir / "index.md"
        with open(file_path, mode="w", encoding="utf-8") as file:
            file.write(index_page)

    elif pipeline_theme == "pipeline":
        source_path = base_dir / pipeline_manifest["project"]["readme"]
        with open(source_path) as file:
            readme_content = file.readlines()

        # Remove the first two lines and join the rest
        readme_text = "".join(readme_content[2:])

        notebook_list = []
        for notebook_id in pipeline_manifest["notebooks"]:
            nb_manifest = pipeline_manifest["notebooks"][notebook_id]
            nb_filename = Path(nb_manifest["path"]).stem
            nb_path = f"cb/notebooks/{_fs_slug(pipeline_id)}/{nb_filename}"
            nb_title = nb_manifest.get("name", notebook_id)
            notebook_list.append(f"{nb_title} <{nb_path}>")

        # Handle markdown notes if they exist
        notes_list = []
        if "notes" in pipeline_manifest:
            # Copy markdown files to docs build directory
            for note_id in pipeline_manifest["notes"]:
                note_manifest = pipeline_manifest["notes"][note_id]
                source_file = note_manifest["_resolved_path"]

                # Copy to cb/ directory with note_id as filename
                cb_dir = docs_build_dir / "cb"
                cb_dir.mkdir(parents=True, exist_ok=True)
                dest_file = cb_dir / f"{note_id}.md"
                shutil.copyfile(source_file, dest_file)

                # Add to notes list for template
                notes_list.append(f"cb/{note_id}.md")

        # Load site_dir content for index template merge
        site_dir = pipeline_manifest.get("project", {}).get("_resolved_site_dir")
        index_toc_content = ""
        site_pages_list = []
        if site_dir:
            index_toc_path = Path(site_dir) / "index_toc.md"
            if index_toc_path.exists():
                with open(index_toc_path) as f:
                    index_toc_content = f.read()
            site_pages_list = discover_site_pages(site_dir)

        # Render and copy index.md in pipeline themes
        template_path = "index.md"
        template = environment.get_template(template_path)
        index_page = template.render(
            manifest=manifest,
            dataframe_file_list=dataframe_file_list,
            model_file_list=model_file_list,
            pipeline_manifest=pipeline_manifest,
            readme_text=readme_text,
            pipeline_page_link="./index.md",
            dot_or_dotdot="cb",
            pipeline_id=pipeline_id,
            notebook_list=notebook_list,
            notes_list=notes_list,
            site_pages_list=site_pages_list,
            index_toc_content=index_toc_content,
            show_code_updated=True,
            freshness=[
                fact
                for fact in [
                    freshness_fact("Code updated", _code_last_modified(pipeline_manifest))
                ]
                if fact
            ],
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
    enable_data_download=False,
    site_manifest=None,
):
    """Generate documentation for a single pipeline.

    :param pipeline_id: The identifier for the pipeline.
    :type pipeline_id: str
    :param pipeline_manifest: Manifest for the pipeline.
    :type pipeline_manifest: dict
    :param pipeline_base_dir: The base directory of the pipeline project folder.
    :type pipeline_base_dir: Path
    :param docs_build_dir: The directory where the docs will be built.
    :type docs_build_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing documentation source files and templates.
    :type docs_src_dir: Path
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param enable_data_download: Whether to enable data download links in documentation.
    :type enable_data_download: bool
    """
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
            enable_data_download=enable_data_download,
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
            enable_data_download=enable_data_download,
        )

    for model_id in pipeline_manifest.get("models") or {}:
        generate_model_docs(
            model_id,
            pipeline_id,
            pipeline_manifest,
            docs_build_dir,
            pipeline_base_dir=pipeline_base_dir,
            pipeline_theme=pipeline_theme,
            docs_src_dir=docs_src_dir,
            site_manifest=site_manifest,
        )


def get_package_templates_path() -> Path:
    """Get path to templates directory in the package.

    :returns: Path to the templates directory.
    :rtype: Path
    """
    package_path = importlib.resources.files("chartbook")
    return Path(str(package_path)) / "templates"


def _source_location(dataframe_manifest):
    """Where a table or query dataframe is, or None when its source has no URL."""
    from chartbook.resolve import QueryLocation, TableLocation

    source = dataframe_manifest.get("_source") or {}
    url = source.get("_resolved_url")
    if not url:
        return None
    if dataframe_manifest.get("table"):
        return TableLocation(dataframe_manifest["source"], source["backend"], url, dataframe_manifest["table"])
    return QueryLocation(dataframe_manifest["source"], source["backend"], url, dataframe_manifest["query"])


def _source_glimpse(dataframe_manifest) -> str:
    """A glimpse of a table or query dataframe, read from its engine.

    Whatever goes wrong in reading it, the page says so and the site is
    built: a query that fails on one value fails when the first rows are
    collected, in Polars' words, and that is not a reason to have no page.
    """
    from chartbook.backends import DuckDBBackend

    source = dataframe_manifest.get("_source") or {}
    where = (
        f"table {dataframe_manifest['table']}"
        if dataframe_manifest.get("table")
        else "query"
    ) + f" in source {dataframe_manifest.get('source')!r} ({source.get('backend')})"
    location = _source_location(dataframe_manifest)
    if location is None:
        return f"A {where}."
    try:
        backend = DuckDBBackend(location.url)
        columns, rows = backend.describe(location)
        sample = backend.scan(location).head(5).collect()
    except Exception as error:
        return f"A {where}. It could not be read when the site was built: {error}"
    lines = [f"A {where}: {rows} rows, {len(columns)} columns.", ""]
    lines += [f"  {column['name']}: {column['dtype']}" for column in columns]
    lines += ["", "First rows:", str(sample)]
    return "\n".join(lines)


def _source_span(dataframe_manifest):
    """The least and greatest ``date_col`` of a table or query, asked of its
    engine; ``(None, None)`` when there is no date_col or it cannot say."""
    from chartbook.backends import DuckDBBackend

    date_col = dataframe_manifest.get("date_col")
    location = _source_location(dataframe_manifest)
    if not date_col or location is None:
        return None, None
    try:
        low, high = DuckDBBackend(location.url).span(location, date_col)
    except Exception:
        return None, None
    return low, high


def _source_freshness(dataframe_manifest):
    """When a DuckDB source's file was last written, if it has one."""
    from chartbook.backends import duckdb_path

    source = dataframe_manifest.get("_source") or {}
    url = source.get("_resolved_url") or ""
    if not url.startswith("duckdb://"):
        return None
    path = duckdb_path(url, Path.cwd())
    if path == ":memory:":
        return None
    return freshness_fact("Data updated", data_last_modified(path))


def generate_dataframe_docs(
    dataframe_id,
    pipeline_id,
    pipeline_manifest,
    docs_build_dir=DOCS_BUILD_DIR,
    pipeline_base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
    enable_data_download=False,
):
    """Generate documentation for a specific dataframe, including the most recent data dates.

    :param dataframe_id: The identifier for the dataframe.
    :type dataframe_id: str
    :param pipeline_id: The identifier for the pipeline.
    :type pipeline_id: str
    :param pipeline_manifest: Manifest for the pipeline.
    :type pipeline_manifest: dict
    :param docs_build_dir: The directory where the docs will be built.
    :type docs_build_dir: Path
    :param pipeline_base_dir: The base directory of the pipeline project folder.
    :type pipeline_base_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing documentation source files and templates.
    :type docs_src_dir: Path
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param enable_data_download: Whether to enable data download links in documentation.
    :type enable_data_download: bool
    """
    dataframe_manifest = pipeline_manifest["dataframes"][dataframe_id]

    dataframe_docs_dir = docs_build_dir / "cb" / "dataframes" / _fs_slug(pipeline_id)
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
        path_to_dataframe_doc = Path(dataframe_manifest["docs_path"]).as_posix()
        source = environment.loader.get_source(environment, path_to_dataframe_doc)[0]
    else:  # doc_mode == "str"
        source = dataframe_manifest["docs"]

    # Use filenames instead of paths for includes, so they can be found in any of our search locations
    modified_source = (
        """# Dataframe: `{{pipeline_id}}:{{dataframe_id}}` - {{name}}\n\n"""
        + """{% include "freshness.md" %}\n\n"""
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
    date_col = dataframe_manifest.get("date_col", "")

    if pipeline_theme == "pipeline":
        pipeline_page_link = "../../../index.md"
        dataframe_path_prefix = "../dataframes/"
    elif pipeline_theme == "catalog":
        pipeline_page_link = f"../pipelines/{_fs_slug(pipeline_id)}_README.md"
        dataframe_path_prefix = ""
    else:
        raise ValueError("Invalid Pipeline theme")
    link_to_dataframe_docs = (
        Path(dataframe_path_prefix) / _fs_slug(pipeline_id) / f"{dataframe_id}.md"
    ).as_posix()
    if dataframe_manifest.get("table") or dataframe_manifest.get("query"):
        # In a source: the engine describes it and dates it
        most_recent_data_min, most_recent_data_max = _source_span(dataframe_manifest)
        dataframe_glimpse = _source_glimpse(dataframe_manifest)
        freshness = [_source_freshness(dataframe_manifest)]
    else:
        # Compute the absolute path to the parquet file
        raw_parquet_path = dataframe_manifest.get("path", "")
        if is_glob_pattern(raw_parquet_path):
            parquet_path = pipeline_base_dir / raw_parquet_path
        else:
            parquet_path = (
                pipeline_base_dir / raw_parquet_path
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

        # How fresh the page's data is, shown under the title. Only facts about
        # this dataframe: when the pipeline's code changed is said once, on the
        # pipeline's own page, so that a code edit does not alter every page.
        freshness = [
            freshness_fact("Data updated", data_last_modified(parquet_path)),
        ]

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
        dot_or_dotdot="../..",
        dataframe_glimpse=dataframe_glimpse,
        enable_data_download=enable_data_download,
        freshness=[fact for fact in freshness if fact],
    )
    # print(table_page)

    filename = f"{dataframe_id}.md"
    file_path = dataframe_docs_dir / filename
    with open(file_path, mode="w", encoding="utf-8") as file:
        file.write(table_page)


def model_last_modified(model_path):
    """Find when a model was last written, by file modification time.

    For a model that is a directory this is its newest file.

    :param model_path: Path to the model file, or the directory of its files.
    :type model_path: str or Path
    :returns: The modification time, or None if nothing is on disk.
    :rtype: datetime or None
    """
    model_path = Path(model_path)
    if model_path.is_dir():
        # The files that make up the model, as its hash counts them
        files = directory_files(model_path)
        if not files:
            return None
        return max(get_file_modified_datetime(f) for f in files)
    return data_last_modified(model_path)


def _format_size(size_bytes):
    """A file size for a person: ``18.2 KB``, ``4.1 MB``."""
    size = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024


def _format_metric(value):
    """A score for a table: whole numbers whole, others to six significant digits."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, float):
        return str(value)
    return f"{value:.6g}"


def get_model_docs(manifest):
    """Get a mapping of model IDs to their page paths in the build tree.

    :param manifest: The top-level loaded manifest.
    :type manifest: dict
    :returns: A dictionary mapping ``pipeline:model/name`` IDs to file paths.
    :rtype: dict
    """
    model_file_map = {}
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for model_id in pipeline_manifest.get("models") or {}:
            file_path = Path("cb/models") / _fs_slug(pipeline_id) / f"{model_id}.md"
            model_file_map[f"{pipeline_id}:model/{model_id}"] = file_path.as_posix()
    return model_file_map


_MODEL_PAGE_HEAD = """# Model: `{{pipeline_id}}:model/{{model_id}}` - {{model_name}}

{% include "freshness.md" %}

"""

_MODEL_PAGE_TAIL = """

{% if metrics %}
## Scores

| Metric | Value |
|--------|-------|
{% for name, value in metrics.items() %}| `{{name}}` | {{value}} |
{% endfor %}
{% endif %}

{% if versions %}
## Versions

A version is made by a snapshot. Its name is the start of the model's content hash:
`chartbook path model/{{model_id}}@<version>` gives its path.

| Version | Made | Commit | Labels |{% for name in version_metrics %} `{{name}}` |{% endfor %}

|---------|------|--------|--------|{% for name in version_metrics %}------|{% endfor %}

{% for version in versions %}| `{{version.name}}` | {{version.made}} | `{{version.commit}}` | {{version.labels}} |{% for name in version_metrics %} {{version.metrics.get(name, "")}} |{% endfor %}

{% endfor %}
{% endif %}

## Trained On

{% if trained_on %}
{% for dataframe in trained_on %}
- {% if dataframe.link %}[{{dataframe.label}}]({{dataframe.link}}){% else %}`{{dataframe.label}}`{% endif %}{% if dataframe.name %} - {{dataframe.name}}{% endif %}{% if dataframe.note %} ({{dataframe.note}}){% endif %}

{% endfor %}
{% else %}
- Not declared
{% endif %}

{% if model_files %}
## Files

| File | Size |
|------|------|
{% for file in model_files %}| `{{file.path}}` | {{file.size}} |
{% endfor %}
{% endif %}

## Model Manifest

{% include "model_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}

"""


def _site_pipeline(site_manifest, pipeline_ref, dependencies=None):
    """Find the pipeline a reference names, and whether this site has it.

    The pipeline is looked for through the one resolution chain: in the
    ``[dependencies]`` of the pipeline that names it, then among the site's
    own pipelines.

    :param dependencies: The ``[dependencies]`` of the pipeline that names it.
    :returns: Tuple of (the ID it has in this site, its manifest). The
        manifest is None when the site does not contain the pipeline, and
        both are None when nothing knows it.
    """
    from chartbook.manifest import get_pipeline_dirs
    from chartbook.resolve import known_as, locate_pipeline

    in_site = get_pipeline_dirs(site_manifest) if site_manifest else {}
    try:
        location = locate_pipeline(
            pipeline_ref, dependencies=dependencies, catalog=in_site
        )
    except (KeyError, ValueError):
        return None, None
    site_id = known_as(location, in_site)
    if site_id not in in_site:
        return site_id, None
    return site_id, get_pipeline_manifest(site_manifest, site_id)


def _trained_on_entries(model_manifest, pipeline_id, pipeline_manifest, site_manifest):
    """What a model's page lists under "Trained On".

    A dataframe of this pipeline, or of another pipeline that is part of
    the same site, is a link to its page. One in a pipeline the site does
    not contain is named without a link: by the name ``[dependencies]``
    gives that pipeline if it declares it, and as stated otherwise.
    """
    entries = []
    for reference in model_manifest.get("_trained_on", []):
        if reference.is_local:
            owner_id, owner = pipeline_id, pipeline_manifest
        else:
            owner_id, owner = _site_pipeline(
                site_manifest,
                reference.pipeline_id,
                pipeline_manifest.get("dependencies"),
            )
        dataframes = (owner or {}).get("dataframes") or {}
        if reference.name in dataframes:
            entries.append(
                {
                    "label": f"{owner_id}:{reference.name}",
                    "name": dataframes[reference.name].get("name", ""),
                    "link": f"../../dataframes/{_fs_slug(owner_id)}/{reference.name}.md",
                    "note": "",
                }
            )
        else:
            # Known by a declared name only when the site has no page for it
            declared = owner_id is not None and owner is None
            named = reference.in_pipeline(owner_id) if declared else reference
            entries.append(
                {
                    "label": str(named),
                    "name": "",
                    "link": "",
                    "note": "in another pipeline, which is not part of this site",
                }
            )
    return entries


def generate_model_docs(
    model_id,
    pipeline_id,
    pipeline_manifest,
    docs_build_dir=DOCS_BUILD_DIR,
    pipeline_base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    site_manifest=None,
):
    """Generate the page for one model a pipeline declares.

    The page has the model's write-up, its scores (from its metrics file),
    links to the dataframes it was trained on, and its files if it is a
    directory. Nothing is loaded: ChartBook does not know what is inside a
    model.

    :param model_id: The model's key in ``[models]``.
    :type model_id: str
    :param pipeline_id: The identifier for the pipeline.
    :type pipeline_id: str
    :param pipeline_manifest: Manifest for the pipeline.
    :type pipeline_manifest: dict
    :param docs_build_dir: The directory where the docs will be built.
    :type docs_build_dir: Path
    :param pipeline_base_dir: The base directory of the pipeline project folder.
    :type pipeline_base_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing documentation source files and templates.
    :type docs_src_dir: Path
    :param site_manifest: The manifest of the whole site being built, so that
        training data in another of its pipelines can be linked to.
    :type site_manifest: dict or None
    """
    from chartbook.models import read_metrics

    model_manifest = pipeline_manifest["models"][model_id]
    pipeline_base_dir = Path(pipeline_base_dir)
    slug = _fs_slug(pipeline_id)

    model_docs_dir = docs_build_dir / "cb" / "models" / slug
    model_docs_dir.mkdir(parents=True, exist_ok=True)

    package_path = importlib.resources.files("chartbook")
    if pipeline_theme == "catalog":
        theme_template_dir = Path(str(package_path)) / "docs_src_catalog"
        pipeline_page_link = f"../../pipelines/{slug}_README.md"
    elif pipeline_theme == "pipeline":
        theme_template_dir = Path(str(package_path)) / "docs_src_pipeline"
        pipeline_page_link = "../../../index.md"
    else:
        raise ValueError(f"Invalid pipeline theme: {pipeline_theme}")

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(
            [
                pipeline_base_dir,
                docs_src_dir,
                docs_src_dir / "_templates",
                get_package_templates_path(),
                theme_template_dir,
                theme_template_dir / "_templates",
            ]
        )
    )

    # The write-up: a file, the text itself, or nothing
    if model_manifest.get("docs_path"):
        write_up = environment.loader.get_source(
            environment, Path(model_manifest["docs_path"]).as_posix()
        )[0]
    else:
        write_up = model_manifest.get("docs") or ""

    model_path = Path(os.path.normpath(pipeline_base_dir / model_manifest["path"]))

    metrics = {}
    metrics_path = model_manifest.get("metrics_path")
    if metrics_path and (pipeline_base_dir / metrics_path).is_file():
        try:
            scores = read_metrics(pipeline_base_dir / metrics_path)
        except ValueError:
            scores = {}  # `chartbook check` reports a malformed metrics file
        metrics = {name: _format_metric(value) for name, value in scores.items()}

    trained_on = _trained_on_entries(
        model_manifest, pipeline_id, pipeline_manifest, site_manifest
    )

    model_files = []
    if model_path.is_dir():
        model_files = [
            {
                "path": file.relative_to(model_path).as_posix(),
                "size": _format_size(file.stat().st_size),
            }
            for file in sorted(directory_files(model_path))
        ]

    # Newest first: the one someone is most likely to be looking for
    from chartbook.models import versions_in

    aliases = model_manifest.get("aliases")
    kept = versions_in(pipeline_base_dir, model_id, aliases if isinstance(aliases, dict) else {})
    version_metrics = sorted({name for version in kept for name in version.metrics})
    versions = [
        {
            "name": version.name,
            "made": f"{version.made_at[:10]} {version.made_at[11:16]} UTC",
            "commit": version.commit[:7],
            "labels": ", ".join(f"`{label}`" for label in version.labels),
            "metrics": {k: _format_metric(v) for k, v in version.metrics.items()},
        }
        for version in reversed(kept)
    ]

    template = environment.from_string(_MODEL_PAGE_HEAD + write_up + _MODEL_PAGE_TAIL)
    page = template.render(
        model_manifest,
        model_manifest=model_manifest,
        model_id=model_id,
        model_name=model_manifest.get("name", model_id),
        link_to_model_docs=f"../../models/{slug}/{model_id}.md",
        pipeline_id=pipeline_id,
        pipeline_manifest=pipeline_manifest,
        pipeline_page_link=pipeline_page_link,
        dot_or_dotdot="../..",
        metrics=metrics,
        versions=versions,
        version_metrics=version_metrics,
        trained_on=trained_on,
        model_files=model_files,
        freshness=[
            fact
            for fact in [
                freshness_fact("Model updated", model_last_modified(model_path))
            ]
            if fact
        ],
    )

    with open(model_docs_dir / f"{model_id}.md", mode="w", encoding="utf-8") as file:
        file.write(page)


def find_most_recent_valid_datapoints(
    parquet_path, date_col="date", size_threshold_mb=50
):
    """Find the most recent valid datapoints in a parquet file.

    :param parquet_path: Path to the parquet file.
    :type parquet_path: Path
    :param date_col: The name of the date column in the parquet file.
    :type date_col: str
    :param size_threshold_mb: File size threshold in MB above which to skip this computation.
    :type size_threshold_mb: float
    :returns: A tuple of (min_date, max_date) formatted as strings.
    :rtype: tuple[str, str]
    """
    if (date_col == "") or (date_col == "NA") or (date_col == "N/A"):
        return "N/A", "N/A"

    # Glob/hive-partitioned paths cannot use os.path.getsize
    if is_glob_pattern(str(parquet_path)):
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
    enable_data_download=False,
):
    """Generate documentation for a specific chart.

    :param chart_id: The identifier for the chart.
    :type chart_id: str
    :param pipeline_id: The identifier for the pipeline.
    :type pipeline_id: str
    :param pipeline_manifest: Manifest for the pipeline.
    :type pipeline_manifest: dict
    :param docs_build_dir: The directory where the docs will be built.
    :type docs_build_dir: Path
    :param pipeline_base_dir: The base directory of the pipeline project folder.
    :type pipeline_base_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing documentation source files and templates.
    :type docs_src_dir: Path
    :param enable_data_download: Whether to enable data download links in documentation.
    :type enable_data_download: bool
    """
    pipeline_base_dir = Path(pipeline_base_dir)

    # Get all manifest related to the chart
    chart_manifest = pipeline_manifest["charts"][chart_id]
    dataframe_id = chart_manifest["dataframe"]
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
    environment.filters["yaml_escape"] = _yaml_escape_filter

    # Load doc content based on mode (path or inline string)
    doc_mode = chart_manifest.get("_doc_mode", "path")
    if doc_mode == "path":
        path_to_chart_doc = Path(chart_manifest["docs_path"]).as_posix()
        source = environment.loader.get_source(environment, path_to_chart_doc)[0]
    else:  # doc_mode == "str"
        source = chart_manifest["docs"]

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
        pipeline_page_link = "../../index.md"
        dataframe_path_prefix = "../dataframes/"
    elif pipeline_theme == "catalog":
        pipeline_page_link = f"../pipelines/{_fs_slug(pipeline_id)}_README.md"
        dataframe_path_prefix = "../dataframes/"
    else:
        raise ValueError("Invalid Pipeline theme")

    # Compute the absolute path to the parquet file
    raw_parquet_path = dataframe_manifest.get("path", "")
    if is_glob_pattern(raw_parquet_path):
        parquet_path = pipeline_base_dir / raw_parquet_path
    else:
        parquet_path = (
            pipeline_base_dir / raw_parquet_path
        ).resolve()

    # Get and format paths to charts
    path_to_html_chart_unix = pipeline_base_dir / Path(chart_manifest["path"])

    # How fresh the chart and its data are, shown under the title. Like a
    # dataframe page, this says nothing about the pipeline's code.
    chart_updated = data_last_modified(path_to_html_chart_unix)
    freshness = [
        freshness_fact("Chart updated", chart_updated),
        freshness_fact("Data updated", data_last_modified(parquet_path)),
    ]
    # The chart's date in listings is when the chart itself was last written
    if chart_updated is not None:
        chart_date = chart_updated.strftime("%Y-%m-%d %H:%M:%S")
    else:
        chart_date = pipeline_manifest["source_last_modified_date"]

    link_to_dataframe_docs = (
        Path(dataframe_path_prefix) / _fs_slug(pipeline_id) / f"{dataframe_id}.md"
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
        freshness=[fact for fact in freshness if fact],
        chart_date=chart_date,
        dot_or_dotdot="..",
        enable_data_download=enable_data_download,
    )
    # print(chart_page)

    (docs_build_dir / "cb" / "charts").mkdir(parents=True, exist_ok=True)
    filename = f"{_fs_slug(pipeline_id)}.{chart_id}.md"
    file_path = docs_build_dir / "cb" / "charts" / filename
    with open(file_path, mode="w", encoding="utf-8") as file:
        file.write(chart_page)

    _validate_generated_frontmatter(file_path, pipeline_id, chart_id)


def _validate_generated_frontmatter(md_path, pipeline_id, chart_id):
    """Validate that generated markdown has parseable YAML frontmatter.

    :param md_path: Path to the generated markdown file.
    :type md_path: Path
    :param pipeline_id: The pipeline identifier (for error messages).
    :type pipeline_id: str
    :param chart_id: The chart identifier (for error messages).
    :type chart_id: str
    :raises ChartBookError: If the YAML frontmatter is malformed.
    """
    content = Path(md_path).read_text(encoding="utf-8")
    if not content.startswith("---"):
        return
    parts = content.split("---", 2)
    if len(parts) < 3:
        return
    try:
        yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        error = ChartBookError(
            message="Generated chart has malformed YAML frontmatter",
            file_path=Path(md_path),
            hint=(
                f"Chart '{pipeline_id}:{chart_id}' produced invalid YAML frontmatter. "
                f"This usually means a field in chartbook.toml (e.g. sources, "
                f"tags, name) contains characters that are unsafe in YAML "
                f"(colons, brackets, etc.).\nYAML error: {e}"
            ),
        )
        error.exit_with_message()


def get_dataframes_and_dataframe_docs(base_dir=BASE_DIR):
    """Get a mapping of dataframe IDs to their documentation file paths.

    :param base_dir: The base directory of the project.
    :type base_dir: Path
    :returns: A dictionary mapping pipeline:dataframe IDs to file paths.
    :rtype: dict
    """
    manifest = load_manifest(base_dir=base_dir)
    pipeline_ids = get_pipeline_ids(manifest)
    table_file_map = {}
    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for dataframe_id in pipeline_manifest["dataframes"]:
            filename = Path(f"{dataframe_id}.md")
            file_path = Path("cb/dataframes") / _fs_slug(pipeline_id) / filename
            pipeline_dataframe_id = f"{pipeline_id}:{dataframe_id}"
            table_file_map[pipeline_dataframe_id] = file_path.as_posix()
    return table_file_map


def copy_docs_src_to_build(docs_src_dir, docs_build_dir, exclude_list=None):
    """Copy files from docs_src to _docs directory while excluding specified paths.

    Similar to: rsync -lr --exclude=... ./docs_src/ ./_docs/

    :param docs_src_dir: Source directory (docs_src).
    :type docs_src_dir: str or Path
    :param docs_build_dir: Destination directory (_docs).
    :type docs_build_dir: str or Path
    :param exclude_list: List of files and directories to exclude. Defaults to common exclusions.
    :type exclude_list: list, optional
    """
    if exclude_list is None:
        exclude_list = [
            "charts",
            "dataframes",
            "notebooks",
            "index.md",
            "pipelines.md",
            "dataframes.md",
            "models",
            "models.md",
            "diagnostics.md",
            "charts.md",
            "site",
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


def discover_site_pages(site_dir):
    """Discover .md files in site_dir for auto-toctree generation.

    Returns a sorted list of relative paths (posix format) suitable for
    toctree entries, excluding index_toc.md and index.md at the root.

    :param site_dir: Path to the user's site directory.
    :type site_dir: str or Path
    :returns: Sorted list of relative .md file paths.
    :rtype: list[str]
    """
    site_dir = Path(site_dir)
    pages = []

    for md_file in sorted(site_dir.rglob("*.md")):
        rel_path = md_file.relative_to(site_dir)

        # Skip special files at the root of site_dir
        if rel_path.parent == Path(".") and rel_path.name in ("index_toc.md", "index.md"):
            continue

        pages.append(rel_path.as_posix())

    return pages


def copy_site_dir_to_build(site_dir, docs_build_dir):
    """Copy user's custom site pages to the docs build root.

    Files from site_dir are copied to the root of docs_build_dir,
    alongside the auto-generated content under cb/.

    :param site_dir: Path to the user's site directory.
    :type site_dir: str or Path
    :param docs_build_dir: Path to the docs build directory (_docs/).
    :type docs_build_dir: str or Path
    """
    import warnings

    site_dir = Path(site_dir)
    docs_build_dir = Path(docs_build_dir)

    # Validate: site_dir must not contain a 'cb/' subdirectory
    cb_conflict = site_dir / "cb"
    if cb_conflict.exists():
        raise ValueError(
            f"site_dir '{site_dir}' contains a 'cb/' subdirectory which "
            f"conflicts with the reserved chartbook namespace. "
            f"Please rename or remove this directory."
        )

    # Copy all files from site_dir to docs_build_dir root
    for src_path in site_dir.rglob("*"):
        if src_path.is_file():
            rel_path = src_path.relative_to(site_dir)

            # Skip index_toc.md at root (handled separately for index merge)
            if rel_path.name == "index_toc.md" and rel_path.parent == Path("."):
                continue

            # Skip index.md at root (would conflict with generated index)
            if rel_path.name == "index.md" and rel_path.parent == Path("."):
                warnings.warn(
                    f"Ignoring '{src_path}': root index.md in site_dir "
                    f"would conflict with auto-generated index. Use "
                    f"index_toc.md to inject content into the index page."
                )
                continue

            dst_path = docs_build_dir / rel_path
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dst_path)


def ensure_notebook_titles(manifest, docs_build_dir, skip_pipelines=None):
    """Ensure all copied notebooks have a title cell for Sphinx rendering.

    Sphinx requires every document to have a title (top-level heading). Notebooks
    that start with a code cell instead of a markdown heading will cause Sphinx to
    skip them silently. This function injects a markdown title cell at the top of
    any notebook that lacks one, using the notebook_name from the manifest.

    :param manifest: The loaded manifest dictionary.
    :type manifest: dict
    :param docs_build_dir: The docs build directory where notebooks have been copied.
    :type docs_build_dir: Path
    :param skip_pipelines: Set of pipeline IDs to skip.
    :type skip_pipelines: set[str] | None
    """
    pipeline_ids = get_pipeline_ids(manifest)

    for pipeline_id in pipeline_ids:
        if skip_pipelines and pipeline_id in skip_pipelines:
            continue
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        notebook_dir = Path(docs_build_dir) / "cb" / "notebooks" / _fs_slug(pipeline_id)

        for notebook_id in pipeline_manifest.get("notebooks", {}):
            nb_manifest = pipeline_manifest["notebooks"][notebook_id]
            nb_filename = Path(nb_manifest["path"]).name
            nb_path = notebook_dir / nb_filename

            if not nb_path.exists():
                continue

            with open(nb_path, "r", encoding="utf-8") as f:
                nb = json.load(f)

            cells = nb.get("cells", [])

            # Check if first cell is a markdown cell with a heading
            has_title = False
            if cells and cells[0].get("cell_type") == "markdown":
                source = "".join(cells[0].get("source", []))
                if source.lstrip().startswith("#"):
                    has_title = True

            if not has_title:
                title = nb_manifest.get("name", notebook_id)
                title_cell = {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": [f"# {title}\n"],
                }
                nb["cells"].insert(0, title_cell)

                with open(nb_path, "w", encoding="utf-8") as f:
                    json.dump(nb, f, indent=1, ensure_ascii=False)
                    f.write("\n")


def build_all(
    docs_build_dir=DOCS_BUILD_DIR,
    base_dir=BASE_DIR,
    pipeline_theme="pipeline",
    docs_src_dir=DOCS_SRC_DIR,
    size_threshold=50,
    skip_pipelines=None,
    reuse_pipelines=None,
    code_times=None,
):
    """Build all documentation.

    :param docs_build_dir: The output directory, where all generated docs will be placed.
        This is usually the _docs directory.
    :type docs_build_dir: Path
    :param base_dir: The base directory of the current project.
    :type base_dir: Path
    :param pipeline_theme: The theme of the pipeline ("pipeline" or "catalog").
    :type pipeline_theme: str
    :param docs_src_dir: The directory containing the documentation source files.
        This will usually be the _docs_src directory.
    :type docs_src_dir: Path
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param skip_pipelines: Set of pipeline IDs to skip.
    :type skip_pipelines: set[str] | None
    :param reuse_pipelines: Set of pipeline IDs whose pages and copied files
        are not regenerated (see ``generate_all_pipeline_docs``).
    :type reuse_pipelines: set[str] | None
    :param code_times: Code-change times already known, by pipeline ID (see
        ``manifest.apply_code_change_times``). Others are worked out here.
    :type code_times: dict[str, str] | None
    """
    docs_build_dir.mkdir(parents=True, exist_ok=True)
    # Neither a skipped nor a reused pipeline has its files copied or written
    not_generated = set(skip_pipelines or ()) | set(reuse_pipelines or ())

    ## Align files for use by Sphinx
    manifest = load_manifest(base_dir=base_dir)
    # Pages say when the code changed according to git, not the file system
    apply_code_change_times(manifest, known=code_times)

    # Extract enable_data_download setting (defaults to False)
    enable_data_download = manifest["project"].get("enable_data_download", False)

    (
        dataset_plan,
        chart_plan_download,
        chart_plan_static,
        notebook_plan,
    ) = get_sphinx_file_alignment_plan(
        base_dir=base_dir,
        docs_build_dir=docs_build_dir,
        enable_data_download=enable_data_download,
        skip_pipelines=not_generated,
    )

    copy_according_to_plan(dataset_plan)
    copy_according_to_plan(chart_plan_download)
    copy_according_to_plan(chart_plan_static)
    copy_according_to_plan(notebook_plan)

    # Inject title cells into notebooks that lack top-level headings
    # (Sphinx requires every document to have a title for toctree links)
    ensure_notebook_titles(manifest, docs_build_dir, skip_pipelines=not_generated)

    generate_all_pipeline_docs(
        manifest,
        docs_build_dir=docs_build_dir,
        base_dir=base_dir,
        pipeline_theme=pipeline_theme,
        docs_src_dir=docs_src_dir,
        size_threshold=size_threshold,
        enable_data_download=enable_data_download,
        skip_pipelines=skip_pipelines,
        reuse_pipelines=reuse_pipelines,
    )

    # Copy remaining docs_src files to build directory
    copy_docs_src_to_build(docs_src_dir, docs_build_dir)

    # Copy charts.md to cb/ (excluded from general copy to avoid root placement)
    charts_md_src = docs_src_dir / "charts.md"
    if charts_md_src.exists():
        cb_dir = docs_build_dir / "cb"
        cb_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(charts_md_src, cb_dir / "charts.md")

    # Copy user site_dir files if configured
    pipeline_ids = get_pipeline_ids(manifest)
    if pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_ids[0])
        site_dir = pipeline_manifest.get("project", {}).get("_resolved_site_dir")
        if site_dir:
            copy_site_dir_to_build(site_dir, docs_build_dir)


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
