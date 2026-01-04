"""
Test fixtures for creating realistic project structures.

This module provides utilities to create complete pipeline and catalog
projects for integration testing.
"""

from pathlib import Path

import polars as pl
import tomli_w

from chartbook.__about__ import __version__


def create_sample_parquet(path: Path, columns: dict = None, rows: int = 10) -> Path:
    """Creates a real parquet file using polars.

    Args:
        path: Path where the parquet file will be created
        columns: Dict of column_name -> data_type. Defaults to sample columns.
        rows: Number of rows to generate

    Returns:
        Path to the created parquet file
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if columns is None:
        # Default sample data with various types
        df = pl.DataFrame(
            {
                "date": pl.date_range(
                    pl.date(2020, 1, 1), pl.date(2020, 1, 1), eager=True
                ).extend_constant(pl.date(2020, 1, 1), rows - 1),
                "value": list(range(rows)),
                "category": ["A", "B"] * (rows // 2) + ["A"] * (rows % 2),
                "amount": [float(i) * 1.5 for i in range(rows)],
            }
        )
    else:
        # Build dataframe from column specs
        data = {}
        for col_name, col_type in columns.items():
            if col_type == "date":
                data[col_name] = pl.date_range(
                    pl.date(2020, 1, 1), pl.date(2020, 1, 1), eager=True
                ).extend_constant(pl.date(2020, 1, 1), rows - 1)
            elif col_type == "int":
                data[col_name] = list(range(rows))
            elif col_type == "float":
                data[col_name] = [float(i) for i in range(rows)]
            elif col_type == "str":
                data[col_name] = [f"value_{i}" for i in range(rows)]
            else:
                data[col_name] = [None] * rows
        df = pl.DataFrame(data)

    df.write_parquet(path)
    return path


def create_sample_html_chart(path: Path, chart_id: str = "chart") -> Path:
    """Creates a simple HTML chart file.

    Args:
        path: Path where the HTML file will be created
        chart_id: ID to include in the chart content

    Returns:
        Path to the created HTML file
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    html_content = f"""<!DOCTYPE html>
<html>
<head><title>{chart_id}</title></head>
<body>
<div id="chart">Sample chart: {chart_id}</div>
</body>
</html>
"""
    path.write_text(html_content)
    return path


def create_pipeline_project(
    base_dir: Path,
    pipeline_id: str = "test_pipeline",
    pipeline_name: str = "Test Pipeline",
    include_dataframes: bool = True,
    include_charts: bool = True,
    include_notes: bool = False,
    include_notebooks: bool = False,
    dataframe_count: int = 1,
    charts_per_dataframe: int = 1,
) -> Path:
    """Creates a complete pipeline project structure.

    Creates:
        base_dir/
        ├── chartbook.toml
        ├── src/
        │   └── dummy.py
        ├── docs_src/
        │   └── index.md
        ├── _data/
        │   └── {pipeline_id}/
        │       └── *.parquet files
        └── _output/
            └── charts/
                └── *.html files

    Args:
        base_dir: Root directory for the project
        pipeline_id: ID for the pipeline
        pipeline_name: Display name for the pipeline
        include_dataframes: Whether to include dataframes section
        include_charts: Whether to include charts section
        include_notes: Whether to include notes section
        include_notebooks: Whether to include notebooks section
        dataframe_count: Number of dataframes to create
        charts_per_dataframe: Number of charts per dataframe

    Returns:
        Path to the project directory
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    (base_dir / "src").mkdir(exist_ok=True)
    (base_dir / "docs_src").mkdir(exist_ok=True)
    data_dir = base_dir / "_data" / pipeline_id
    data_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = base_dir / "_output" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Create source file for modification tracking
    (base_dir / "src" / "dummy.py").write_text("# Dummy source file\n")

    # Create docs_src file
    (base_dir / "docs_src" / "index.md").write_text("# Documentation\n")

    # Create README.md (required by build_markdown for pipeline theme)
    (base_dir / "README.md").write_text(
        f"# {pipeline_name}\n\nThis is a test pipeline.\n"
    )

    # Build chartbook.toml
    config = {
        "config": {
            "type": "pipeline",
            "chartbook_format_version": __version__,
        },
        "site": {
            "title": pipeline_name,
            "author": "Test Author",
            "copyright": "2024",
            "logo_path": "",
            "favicon_path": "",
        },
        "pipeline": {
            "id": pipeline_id,
            "pipeline_name": pipeline_name,
            "pipeline_description": f"Description for {pipeline_name}",
            "lead_pipeline_developer": "Test Developer",
            "contributors": [],
            "software_modules_command": "",
            "runs_on_grid_or_windows_or_other": "",
            "git_repo_URL": "",
            "README_file_path": "",
        },
    }

    # Create docs_src subdirectories for dataframes and charts
    (base_dir / "docs_src" / "dataframes").mkdir(parents=True, exist_ok=True)
    (base_dir / "docs_src" / "charts").mkdir(parents=True, exist_ok=True)

    if include_dataframes:
        config["dataframes"] = {}
        for i in range(dataframe_count):
            df_id = f"dataframe_{i}"
            parquet_path = f"_data/{pipeline_id}/{df_id}.parquet"
            dataframe_docs_path = f"docs_src/dataframes/{df_id}.md"

            # Create the actual parquet file
            create_sample_parquet(base_dir / parquet_path)

            # Create the dataframe documentation file
            (base_dir / dataframe_docs_path).write_text(
                f"# Dataframe {i}\n\nDocumentation for dataframe {i}.\n"
            )

            config["dataframes"][df_id] = {
                "dataframe_name": f"Dataframe {i}",
                "short_description_df": f"Description for dataframe {i}",
                "path_to_parquet_data": parquet_path,
                "path_to_excel_data": "",  # Required by build_markdown
                "dataframe_docs_path": dataframe_docs_path,
                "date_col": "date",
                "topic_tags": ["test tag", "UPPERCASE TAG"],
                "data_sources": ["Test Source"],
                "data_providers": ["Test Provider"],
            }

            if include_charts:
                if "charts" not in config:
                    config["charts"] = {}
                for j in range(charts_per_dataframe):
                    chart_id = f"chart_{i}_{j}"
                    chart_path = f"_output/charts/{chart_id}.html"
                    chart_docs_path = f"docs_src/charts/{chart_id}.md"

                    # Create the actual HTML chart file
                    create_sample_html_chart(base_dir / chart_path, chart_id)

                    # Create the chart documentation file
                    (base_dir / chart_docs_path).write_text(
                        f"# Chart {i}-{j}\n\nDocumentation for chart {i}-{j}.\n"
                    )

                    config["charts"][chart_id] = {
                        "chart_name": f"Chart {i}-{j}",
                        "short_description_chart": f"Description for chart {i}-{j}",
                        "dataframe_id": df_id,
                        "path_to_html_chart": chart_path,
                        "path_to_excel_chart": "",  # Optional
                        "chart_docs_path": chart_docs_path,
                        "topic_tags": ["chart tag"],
                    }

    # Always include empty notebooks section (required by build_markdown)
    config["notebooks"] = {}

    if include_notes:
        # Notes should be in docs_src directory
        notes_dir = base_dir / "docs_src"
        (notes_dir / "note1.md").write_text("# Note 1\nSome content.\n")

        config["notes"] = {
            "note1": {
                "path_to_markdown_file": "docs_src/note1.md",
            }
        }

    # Write chartbook.toml
    with open(base_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)

    return base_dir


def create_catalog_project(
    base_dir: Path,
    pipeline_ids: list = None,
    use_platform_paths: bool = False,
) -> Path:
    """Creates a catalog project with multiple sub-pipelines.

    Creates:
        base_dir/
        ├── chartbook.toml
        ├── pipelines/
        │   ├── pipeline_a/
        │   │   └── (full pipeline structure)
        │   └── pipeline_b/
        │       └── (full pipeline structure)

    Args:
        base_dir: Root directory for the catalog
        pipeline_ids: List of pipeline IDs to create. Defaults to ["pipeline_a", "pipeline_b"]
        use_platform_paths: If True, uses platform-specific path dicts

    Returns:
        Path to the catalog directory
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    if pipeline_ids is None:
        pipeline_ids = ["pipeline_a", "pipeline_b"]

    pipelines_dir = base_dir / "pipelines"
    pipelines_dir.mkdir(exist_ok=True)

    # Create each sub-pipeline
    pipelines_config = {}
    for pid in pipeline_ids:
        pipeline_dir = pipelines_dir / pid
        create_pipeline_project(
            pipeline_dir,
            pipeline_id=pid,
            pipeline_name=f"Pipeline {pid.upper()}",
            include_dataframes=True,
            include_charts=True,
        )

        if use_platform_paths:
            pipelines_config[pid] = {
                "path_to_pipeline": {
                    "Unix": f"pipelines/{pid}",
                    "Windows": f"pipelines\\{pid}",
                }
            }
        else:
            pipelines_config[pid] = {
                "path_to_pipeline": f"pipelines/{pid}",
            }

    # Create main chartbook.toml for catalog
    config = {
        "config": {
            "type": "catalog",
            "chartbook_format_version": __version__,
        },
        "site": {
            "title": "Test Catalog",
            "author": "Test Author",
            "copyright": "2024",
            "logo_path": "",
            "favicon_path": "",
        },
        "pipelines": pipelines_config,
    }

    with open(base_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)

    return base_dir


def create_invalid_toml_project(base_dir: Path, error_type: str) -> Path:
    """Creates a project with invalid chartbook.toml for testing error handling.

    Args:
        base_dir: Root directory for the project
        error_type: One of "missing_file", "invalid_type", "invalid_version",
                   "missing_version", "invalid_toml_syntax"

    Returns:
        Path to the project directory
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # Create minimal directory structure
    (base_dir / "src").mkdir(exist_ok=True)
    (base_dir / "docs_src").mkdir(exist_ok=True)
    (base_dir / "src" / "dummy.py").write_text("# Dummy\n")
    (base_dir / "docs_src" / "index.md").write_text("# Docs\n")

    if error_type == "missing_file":
        # Don't create chartbook.toml
        return base_dir

    if error_type == "invalid_type":
        config = {
            "config": {
                "type": "invalid_type",
                "chartbook_format_version": __version__,
            },
            "site": {
                "title": "Test",
                "author": "",
                "copyright": "",
                "logo_path": "",
                "favicon_path": "",
            },
        }
    elif error_type == "invalid_version":
        config = {
            "config": {
                "type": "pipeline",
                "chartbook_format_version": "not-a-version",
            },
            "site": {
                "title": "Test",
                "author": "",
                "copyright": "",
                "logo_path": "",
                "favicon_path": "",
            },
            "pipeline": {
                "id": "test",
                "pipeline_name": "Test",
                "pipeline_description": "",
                "lead_pipeline_developer": "",
                "contributors": [],
                "software_modules_command": "",
                "runs_on_grid_or_windows_or_other": "",
                "git_repo_URL": "",
                "README_file_path": "",
            },
        }
    elif error_type == "old_version":
        config = {
            "config": {
                "type": "pipeline",
                "chartbook_format_version": "0.0.2",
            },
            "site": {
                "title": "Test",
                "author": "",
                "copyright": "",
                "logo_path": "",
                "favicon_path": "",
            },
            "pipeline": {
                "id": "test",
                "pipeline_name": "Test",
                "pipeline_description": "",
                "lead_pipeline_developer": "",
                "contributors": [],
                "software_modules_command": "",
                "runs_on_grid_or_windows_or_other": "",
                "git_repo_URL": "",
                "README_file_path": "",
            },
        }
    elif error_type == "invalid_toml_syntax":
        # Write invalid TOML directly
        (base_dir / "chartbook.toml").write_text("this is not valid toml {{{\n")
        return base_dir
    else:
        raise ValueError(f"Unknown error_type: {error_type}")

    with open(base_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)

    return base_dir
