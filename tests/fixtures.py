"""
Test fixtures for creating realistic project structures.

This module provides utilities to create complete pipeline and catalog
projects for integration testing.
"""

from pathlib import Path

import polars as pl
import tomli_w


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


def create_hive_partitioned_parquet(
    base_dir: Path,
    partition_col: str = "category",
    partitions: list = None,
    rows_per_partition: int = 5,
) -> Path:
    """Creates a hive-style partitioned parquet dataset.

    Creates:
        base_dir/
        ├── {partition_col}={partitions[0]}/
        │   └── data.parquet
        └── {partition_col}={partitions[1]}/
            └── data.parquet

    Args:
        base_dir: Root directory for the partitioned dataset
        partition_col: Name of the partition column
        partitions: List of partition values. Defaults to ["A", "B"]
        rows_per_partition: Number of rows per partition file

    Returns:
        Path to the base directory containing the partitioned data
    """
    if partitions is None:
        partitions = ["A", "B"]

    base_dir = Path(base_dir)

    for partition_value in partitions:
        partition_dir = base_dir / f"{partition_col}={partition_value}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        df = pl.DataFrame(
            {
                "date": pl.date_range(
                    pl.date(2020, 1, 1), pl.date(2020, 1, 1), eager=True
                ).extend_constant(pl.date(2020, 1, 1), rows_per_partition - 1),
                "value": list(range(rows_per_partition)),
                "amount": [float(i) * 1.5 for i in range(rows_per_partition)],
            }
        )
        df.write_parquet(partition_dir / "data.parquet")

    return base_dir


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
    include_site_dir: bool = False,
    site_dir_in_docs_src: bool = True,
    dataframe_count: int = 1,
    charts_per_dataframe: int = 1,
    use_inline_docs: bool = False,
    use_glob_paths: bool = False,
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
        use_inline_docs: If True, uses inline docs instead of docs_path
        include_site_dir: Whether to create a site directory with sample pages
        site_dir_in_docs_src: If True, creates site dir inside docs_src/; otherwise top-level

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

    # Build chartbook.toml (format v2)
    config = {
        "project": {
            "id": pipeline_id,
            "name": pipeline_name,
            "description": f"Description for {pipeline_name}",
            "maintainer": "Test Developer",
            "copyright": "2024",
        },
    }

    # Create docs_src subdirectories for dataframes and charts
    (base_dir / "docs_src" / "dataframes").mkdir(parents=True, exist_ok=True)
    (base_dir / "docs_src" / "charts").mkdir(parents=True, exist_ok=True)

    if include_dataframes:
        config["dataframes"] = {}
        for i in range(dataframe_count):
            df_id = f"dataframe_{i}"
            dataframe_docs_path = f"docs_src/dataframes/{df_id}.md"

            if use_glob_paths:
                # Create hive-partitioned data
                hive_dir = base_dir / "_data" / pipeline_id / f"{df_id}_hive"
                create_hive_partitioned_parquet(hive_dir)
                parquet_path = f"_data/{pipeline_id}/{df_id}_hive/**/*.parquet"
            else:
                parquet_path = f"_data/{pipeline_id}/{df_id}.parquet"
                # Create the actual parquet file
                create_sample_parquet(base_dir / parquet_path)

            # Create the dataframe documentation file
            (base_dir / dataframe_docs_path).write_text(
                f"# Dataframe {i}\n\nDocumentation for dataframe {i}.\n"
            )

            df_config = {
                "name": f"Dataframe {i}",
                "description": f"Description for dataframe {i}",
                "path": parquet_path,
                "date_col": "date",
                "tags": ["test tag", "UPPERCASE TAG"],
                "sources": ["Test Source"],
                "providers": ["Test Provider"],
            }

            if use_inline_docs:
                df_config["docs"] = (
                    f"# Dataframe {i}\n\nInline documentation for dataframe {i}.\n"
                )
            else:
                df_config["docs_path"] = dataframe_docs_path

            config["dataframes"][df_id] = df_config

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
                        "name": f"Chart {i}-{j}",
                        "description": f"Description for chart {i}-{j}",
                        "dataframe": df_id,
                        "path": chart_path,
                        "docs_path": chart_docs_path,
                        "tags": ["chart tag"],
                    }

    # Always include empty notebooks section (required by build_markdown)
    config["notebooks"] = {}

    if include_notes:
        # Notes should be in docs_src directory
        notes_dir = base_dir / "docs_src"
        (notes_dir / "note1.md").write_text("# Note 1\nSome content.\n")

        config["notes"] = {
            "note1": {
                "path": "docs_src/note1.md",
            }
        }

    if include_site_dir:
        if site_dir_in_docs_src:
            site_dir = base_dir / "docs_src" / "site"
            config["project"]["site_dir"] = "./docs_src/site/"
        else:
            site_dir = base_dir / "site"
            config["project"]["site_dir"] = "./site/"

        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "index_toc.md").write_text(
            "```{toctree}\n:maxdepth: 2\n:caption: Site Pages\nsample_page.md\n```\n"
        )
        (site_dir / "sample_page.md").write_text(
            "# Sample Page\n\nThis is a sample site page.\n"
        )

    # Write chartbook.toml
    with open(base_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)

    return base_dir


def create_catalog_project(
    base_dir: Path,
    pipeline_ids: list = None,
    use_platform_paths: bool = False,
    use_inline_docs: bool = False,
    use_glob_paths: bool = False,
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
        use_inline_docs: If True, uses inline docs instead of docs_path

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
            use_inline_docs=use_inline_docs,
            use_glob_paths=use_glob_paths,
        )

        if use_platform_paths:
            pipelines_config[pid] = {
                "path": {
                    "unix": f"pipelines/{pid}",
                    "windows": f"pipelines\\{pid}",
                }
            }
        else:
            pipelines_config[pid] = {
                "path": f"pipelines/{pid}",
            }

    # Create main chartbook.toml for catalog (format v2)
    config = {
        "project": {
            "type": "catalog",
            "name": "Test Catalog",
            "maintainer": "Test Author",
            "copyright": "2024",
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
        error_type: One of "missing_file", "invalid_type", "v1_format",
                   "type_conflict", "invalid_toml_syntax"

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
            "project": {
                "type": "invalid_type",
                "name": "Test",
            },
        }
    elif error_type == "v1_format":
        config = {
            "config": {
                "type": "pipeline",
                "chartbook_format_version": "0.0.2",
            },
            "site": {
                "title": "Test",
            },
            "pipeline": {
                "id": "test",
                "pipeline_name": "Test",
            },
        }
    elif error_type == "type_conflict":
        config = {
            "project": {
                "type": "pipeline",
                "name": "Test",
            },
            "pipelines": {
                "other": {"path": "../other"},
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
