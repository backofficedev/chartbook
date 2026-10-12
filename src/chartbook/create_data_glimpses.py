"""
create_data_glimpses.py

Summarizes every dataframe a project declares in its chartbook.toml: file
metadata, column types, null rates, sample rows and numeric statistics.

The list of data files comes from the manifest and nowhere else. Whatever
builds the project (doit, Snakemake, Make, plain scripts) is not consulted,
and a data file the manifest does not declare is not a catalogued asset.
"""

import argparse
import glob
import os
import re
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from xml.sax import saxutils

import polars as pl

from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest, load_manifest
from chartbook.utils import is_glob_pattern

# Default file size threshold (in MB) above which to use memory-efficient loading
DEFAULT_SIZE_THRESHOLD_MB = 50


def fix_glimpse_row_count(glimpse_text: str, actual_row_count: int) -> str:
    """Replace the sample row count in glimpse output with the actual total row count.

    Polars glimpse output starts with "Rows: X" where X is the number of rows in the
    sampled DataFrame. This function replaces that with the actual total row count.

    :param glimpse_text: The glimpse output text from Polars.
    :type glimpse_text: str
    :param actual_row_count: The actual total number of rows in the dataset.
    :type actual_row_count: int
    :returns: The glimpse text with the corrected row count.
    :rtype: str
    """
    return re.sub(r"^Rows: \d+", f"Rows: {actual_row_count}", glimpse_text)


@dataclass(frozen=True)
class DeclaredDataframe:
    """A dataframe as a manifest declares it.

    Attributes:
        pipeline_id: The pipeline that declares it.
        dataframe_id: Its key in that pipeline's ``[dataframes]`` table.
        name: Its display name (the ID when no ``name`` is set).
        path: Where its data lives, absolute. Contains glob characters for
            partitioned data.
    """

    pipeline_id: str
    dataframe_id: str
    name: str
    path: Path

    @property
    def is_glob(self) -> bool:
        return is_glob_pattern(self.path)

    def data_files(self) -> list[str]:
        """The files on disk behind this dataframe; empty if not built yet."""
        if self.is_glob:
            return sorted(glob.glob(str(self.path), recursive=True))
        return [str(self.path)] if self.path.exists() else []


def find_declared_dataframes(manifest):
    """List the dataframes a manifest declares, in manifest order.

    For a catalog this covers every member pipeline. A dataframe declared
    without a ``path`` has no data to summarize and is left out.

    :param manifest: A manifest from :func:`chartbook.manifest.load_manifest`.
    :type manifest: dict
    :returns: One entry per declared dataframe that has a path.
    :rtype: list[DeclaredDataframe]
    """
    declared = []
    for pipeline_id in get_pipeline_ids(manifest):
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        for dataframe_id, dataframe in pipeline_manifest.get("dataframes", {}).items():
            resolved_path = dataframe.get("_resolved_path")
            if resolved_path is None:
                continue
            declared.append(
                DeclaredDataframe(
                    pipeline_id=pipeline_id,
                    dataframe_id=dataframe_id,
                    name=dataframe.get("name", dataframe_id),
                    path=Path(resolved_path),
                )
            )
    return declared


def get_dataset_report(
    filepath, include_stats=True, size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB
):
    """Return a dict with file metadata, shape, columns, sample values, numeric stats, and glimpse.

    For files larger than size_threshold_mb, uses memory-efficient loading by only
    collecting sampled data and correcting the row count in glimpse output.

    :param filepath: Path to the CSV or Parquet file, or a glob pattern
        matching the parquet files of a partitioned dataset.
    :type filepath: str or Path
    :param include_stats: If True, include numeric column statistics.
    :type include_stats: bool
    :param size_threshold_mb: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold_mb: float
    :returns: A dict containing file metadata, shape, columns, sample values, numeric stats, and glimpse.
    :rtype: dict
    """
    report = {}
    filepath = str(filepath)
    try:
        # File info; a glob pattern is one dataset spread over many files
        if is_glob_pattern(filepath):
            part_files = glob.glob(filepath, recursive=True)
            report["file_size_bytes"] = sum(os.path.getsize(f) for f in part_files)
        else:
            report["file_size_bytes"] = os.path.getsize(filepath)
        report["file_size_mb"] = report["file_size_bytes"] / (1024 * 1024)
        report["file_type"] = Path(filepath).suffix.replace(".", "").upper()

        # Determine if this is a large file
        is_large_file = report["file_size_mb"] > size_threshold_mb

        # Load data lazily
        if is_glob_pattern(filepath):
            lf = pl.scan_parquet(filepath, hive_partitioning=True)
        elif filepath.endswith(".csv"):
            lf = pl.scan_csv(filepath)
        else:
            lf = pl.scan_parquet(filepath)

        # Get schema without loading data
        schema = lf.collect_schema()
        report["n_cols"] = len(schema)

        # Get row count efficiently (works for both small and large files)
        row_count_df = lf.select(pl.len().alias("count")).collect()
        report["n_rows"] = row_count_df["count"][0]

        # Get null counts - skip for large files to avoid OOM
        if not is_large_file:
            null_count_exprs = [pl.col(col).null_count().alias(col) for col in schema]
            null_counts = lf.select(null_count_exprs).collect().to_dicts()[0]
        else:
            null_counts = {}

        # Columns info
        columns = []
        for col in schema:
            dtype = str(schema[col])
            if is_large_file:
                n_null = None
                pct_null = None
            else:
                n_null = null_counts.get(col, 0)
                pct_null = (
                    (n_null / report["n_rows"] * 100) if report["n_rows"] > 0 else 0.0
                )
            columns.append(
                {"name": col, "dtype": dtype, "pct_null": pct_null, "n_null": n_null}
            )
        report["columns"] = columns

        # Sample values - only collect first 5 rows
        sample_df = lf.head(5).collect()
        sample = sample_df.to_dicts()
        report["sample_values"] = sample

        # Capture polars text representation of first 5 rows
        output = StringIO()
        with redirect_stdout(output):
            sample_df.glimpse()
        sample_text = output.getvalue()
        # Fix row count in sample text to show actual total rows
        report["sample_text"] = fix_glimpse_row_count(sample_text, report["n_rows"])

        # Numeric stats (only if requested)
        numeric_types = {
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Float32,
            pl.Float64,
        }
        numeric_cols = [c for c in schema if schema[c] in numeric_types]
        numeric_stats = []

        if include_stats and numeric_cols and not is_large_file:
            # Only compute stats for small files - large files skip entirely to avoid OOM
            stats_exprs = []
            for c in numeric_cols:
                stats_exprs.extend(
                    [
                        pl.col(c).min().alias(f"{c}_min"),
                        pl.col(c).max().alias(f"{c}_max"),
                        pl.col(c).mean().alias(f"{c}_mean"),
                        pl.col(c).median().alias(f"{c}_median"),
                    ]
                )

            stats_df = lf.select(stats_exprs).collect()
            stats_dict = stats_df.to_dicts()[0]

            for col in numeric_cols:
                numeric_stats.append(
                    {
                        "name": col,
                        "min": stats_dict.get(f"{col}_min"),
                        "max": stats_dict.get(f"{col}_max"),
                        "mean": stats_dict.get(f"{col}_mean"),
                        "median": stats_dict.get(f"{col}_median"),
                    }
                )
        report["numeric_stats"] = numeric_stats

        # Glimpse - use memory-efficient loading for large files
        if is_large_file:
            # For large files, only collect a sample and fix the row count
            glimpse_df = lf.head(100).collect()
        else:
            # For small files, collect more data for better representation
            glimpse_df = lf.head(100).collect()

        output = StringIO()
        with redirect_stdout(output):
            glimpse_df.glimpse(max_items_per_column=0)
        glimpse_text = output.getvalue()
        # Fix row count in glimpse to show actual total rows
        report["glimpse"] = fix_glimpse_row_count(glimpse_text, report["n_rows"])

    except Exception as e:
        report["error"] = f"ERROR: Could not read file - {e!s}"
    return report


def format_file_size(size_bytes):
    """Format file size in human-readable format.

    :param size_bytes: The file size in bytes.
    :type size_bytes: int
    :returns: The formatted file size string.
    :rtype: str
    """
    size_mb = size_bytes / (1024 * 1024)
    if size_mb < 1:
        return f"{size_bytes} bytes"
    elif size_mb < 1024:
        return f"{size_mb:.1f} MB"
    else:
        return f"{size_mb / 1024:.1f} GB"


def heading_to_anchor(heading):
    """Convert a section heading to its markdown anchor.

    :param heading: The heading text to convert.
    :type heading: str
    :returns: The markdown anchor link.
    :rtype: str
    """
    # Convert to lowercase and replace non-alphanumeric characters with hyphens
    anchor = heading.lower()
    anchor = "".join(c if c.isalnum() else "-" for c in anchor)
    # Remove multiple consecutive hyphens and leading/trailing hyphens
    while "--" in anchor:
        anchor = anchor.replace("--", "-")
    anchor = anchor.strip("-")
    return anchor


def _section_headings(dataframes):
    """Map each dataframe to a unique section heading.

    A dataframe's own ID is enough within one pipeline. Across the pipelines
    of a catalog, IDs can repeat, so each is qualified as ``pipeline:dataframe``.
    """
    qualify = len({d.pipeline_id for d in dataframes}) > 1
    return {
        d: f"{d.pipeline_id}:{d.dataframe_id}" if qualify else d.dataframe_id
        for d in dataframes
    }


def create_txt_report(
    dataframes,
    include_samples=True,
    include_stats=True,
    size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB,
):
    """Create a human-readable TXT format Data Glimpses Report.

    :param dataframes: The declared dataframes to include, each with its data on disk.
    :type dataframes: list[DeclaredDataframe]
    :param include_samples: If True, include sample values sections.
    :type include_samples: bool
    :param include_stats: If True, include numeric column statistics sections.
    :type include_stats: bool
    :param size_threshold_mb: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold_mb: float
    :returns: The report content as a string.
    :rtype: str
    """
    output_lines = []
    headings = _section_headings(dataframes)

    # Header
    output_lines.append("# Data Glimpses Report")
    output_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_lines.append(f"Total dataframes: {len(dataframes)}")
    output_lines.append("")

    # Summary section grouped by the pipeline that declares each dataframe
    output_lines.append("## Summary of Dataframes by Pipeline")
    output_lines.append("")

    by_pipeline = {}
    for dataframe in dataframes:
        by_pipeline.setdefault(dataframe.pipeline_id, []).append(dataframe)

    for pipeline_id, pipeline_dataframes in by_pipeline.items():
        output_lines.append(f"### {pipeline_id}")
        for dataframe in pipeline_dataframes:
            anchor = heading_to_anchor(headings[dataframe])
            output_lines.append(
                f"- [`{dataframe.dataframe_id}`](#{anchor}): {dataframe.name}"
            )
        output_lines.append("")

    output_lines.append("---")

    # Process each dataframe
    for dataframe in dataframes:
        report = get_dataset_report(
            dataframe.path,
            include_stats=include_stats,
            size_threshold_mb=size_threshold_mb,
        )

        output_lines.append("")
        output_lines.append(f"## {headings[dataframe]}")
        output_lines.append(f"**Name:** {dataframe.name}")
        output_lines.append(f"**Path:** `{dataframe.path}`")

        if "error" in report:
            output_lines.append(f"**ERROR:** {report['error']}")
            output_lines.append("---")
            continue

        # File metadata
        output_lines.append(
            f"**Size:** {format_file_size(report['file_size_bytes'])} | **Type:** {report['file_type'].capitalize()} | **Shape:** {report['n_rows']:,} rows × {report['n_cols']} columns"
        )
        output_lines.append("")

        # Columns section
        output_lines.append("### Columns")
        output_lines.append("```")
        for col in report["columns"]:
            if col["pct_null"] is not None and col["pct_null"] > 0:
                null_info = f" ({col['pct_null']:.1f}% null)"
            else:
                null_info = ""
            output_lines.append(f"{col['name']:<40} {col['dtype']:<15}{null_info}")
        output_lines.append("```")
        output_lines.append("")

        # Sample values section (conditional)
        if include_samples:
            output_lines.append("### Sample Values (first 5 rows)")
            output_lines.append("```")
            output_lines.append(report["sample_text"].rstrip())
            output_lines.append("```")
            output_lines.append("")

        # Numeric statistics section (conditional)
        if include_stats and report["numeric_stats"]:
            output_lines.append("### Numeric Column Statistics")
            output_lines.append("```")
            for stat in report["numeric_stats"]:
                output_lines.append(
                    f"{stat['name']}: min={stat['min']}, max={stat['max']}, "
                    f"mean={stat['mean']:.2f}, median={stat['median']}"
                )
            output_lines.append("```")
            output_lines.append("")

        # Add separator between datasets
        output_lines.append("---")

    # Remove the final separator so document doesn't end with a transition
    if output_lines and output_lines[-1] == "---":
        output_lines.pop()
        # Also remove the empty line before it if it exists
        if output_lines and output_lines[-1] == "":
            output_lines.pop()

    return "\n".join(output_lines)


def create_xml_report(
    dataframes, include_stats=True, size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB
):
    """Create a machine-readable XML format Data Glimpses Report.

    :param dataframes: The declared dataframes to include, each with its data on disk.
    :type dataframes: list[DeclaredDataframe]
    :param include_stats: If True, include numeric column statistics.
    :type include_stats: bool
    :param size_threshold_mb: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold_mb: float
    :returns: The XML report content as a string.
    :rtype: str
    """
    output_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<data_glimpses_report>",
        "  <summary>",
    ]

    def dataset_attributes(dataframe):
        return (
            f'pipeline={saxutils.quoteattr(dataframe.pipeline_id)} '
            f'id={saxutils.quoteattr(dataframe.dataframe_id)} '
            f'filename={saxutils.quoteattr(dataframe.path.name)} '
            f'path={saxutils.quoteattr(str(dataframe.path))}'
        )

    # Add summary section
    for dataframe in dataframes:
        output_lines.append(f"    <dataset {dataset_attributes(dataframe)}/>")
    output_lines.append("  </summary>")
    output_lines.append("  <datasets>")

    # Add each dataset
    for dataframe in dataframes:
        report = get_dataset_report(
            dataframe.path,
            include_stats=include_stats,
            size_threshold_mb=size_threshold_mb,
        )
        output_lines.append(f"    <dataset {dataset_attributes(dataframe)}>")

        # File info
        if "error" in report:
            output_lines.append(
                f"      <error>{saxutils.escape(report['error'])}</error>"
            )
            output_lines.append("    </dataset>")
            continue

        output_lines.append(
            f'      <file_info size_mb="{report["file_size_mb"]:.1f}" type="{report["file_type"]}"/>'
        )
        output_lines.append(
            f'      <shape rows="{report["n_rows"]}" cols="{report["n_cols"]}"/>'
        )

        # Columns
        output_lines.append("      <columns>")
        for col in report["columns"]:
            pct_null_str = (
                f"{col['pct_null']:.1f}" if col["pct_null"] is not None else "N/A"
            )
            output_lines.append(
                f'        <column name="{saxutils.escape(col["name"])}" dtype="{saxutils.escape(col["dtype"])}" pct_null="{pct_null_str}"/>'
            )
        output_lines.append("      </columns>")

        # Sample values
        output_lines.append("      <sample_values>")
        for row in report["sample_values"]:
            # Show as dict string, truncate if too long
            row_str = str(row)
            if len(row_str) > 300:
                row_str = row_str[:297] + "..."
            output_lines.append(f"        <row>{saxutils.escape(row_str)}</row>")
        output_lines.append("      </sample_values>")

        # Numeric stats
        if report["numeric_stats"]:
            output_lines.append("      <numeric_stats>")
            for stat in report["numeric_stats"]:
                output_lines.append(
                    f'        <column name="{saxutils.escape(stat["name"])}" min="{stat["min"]}" max="{stat["max"]}" mean="{stat["mean"]}" median="{stat["median"]}"/>'
                )
            output_lines.append("      </numeric_stats>")

        # Glimpse
        output_lines.append("      <glimpse><![CDATA[")
        output_lines.append(report["glimpse"].rstrip())
        output_lines.append("      ]]></glimpse>")
        output_lines.append("    </dataset>")

    output_lines.append("  </datasets>")
    output_lines.append("</data_glimpses_report>")

    return "\n".join(output_lines)


def main(
    output_dir=None,
    no_samples=False,
    no_stats=False,
    size_threshold=DEFAULT_SIZE_THRESHOLD_MB,
    project_dir=None,
):
    """Main function to create the data glimpses report for a project.

    :param output_dir: Directory to save the output file. If None, saves to current directory.
    :type output_dir: str or Path, optional
    :param no_samples: If True, exclude sample values sections from the report.
    :type no_samples: bool
    :param no_stats: If True, exclude numeric column statistics sections from the report.
    :type no_stats: bool
    :param size_threshold: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold: float
    :param project_dir: Directory holding the project's chartbook.toml. If None, uses the
        current directory.
    :type project_dir: str or Path, optional
    :raises FileNotFoundError: If the project directory has no chartbook.toml.
    """
    project_dir = Path(project_dir) if project_dir is not None else Path.cwd()
    print(f"Reading declared dataframes from {project_dir / 'chartbook.toml'}...")

    manifest = load_manifest(base_dir=project_dir)
    declared = find_declared_dataframes(manifest)
    dataframes = [d for d in declared if d.data_files()]

    print(
        f"Found {len(declared)} declared dataframes, "
        f"{len(dataframes)} with data on disk"
    )
    for dataframe in declared:
        if dataframe not in dataframes:
            print(
                f"  - Skipping {dataframe.pipeline_id}:{dataframe.dataframe_id} "
                f"(no data at {dataframe.path})"
            )

    # Determine output directory
    if output_dir is None:
        output_path = Path.cwd() / "data_glimpses.md"
    else:
        output_path = Path(output_dir)
        if output_path.is_dir():
            output_path = output_path / "data_glimpses.md"
        # If output_dir is a file path, use it as is

    # Create parent directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate and save TXT report
    print("\nGenerating report...")
    include_samples = not no_samples
    include_stats = not no_stats

    if no_samples:
        print("  - Excluding sample values sections")
    if no_stats:
        print("  - Excluding numeric statistics sections")

    txt_content = create_txt_report(
        dataframes,
        include_samples=include_samples,
        include_stats=include_stats,
        size_threshold_mb=size_threshold,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    print(f"Report saved to: {output_path}")

    print(f"\nProcessed {len(dataframes)} dataframes")
    print("Report generated successfully!")


if __name__ == "__main__":
    # Parse command line arguments for standalone usage
    parser = argparse.ArgumentParser(
        description="Generate a data glimpses report for the dataframes "
        "declared in chartbook.toml"
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Directory holding chartbook.toml (default: current directory)",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="Exclude sample values sections from the report",
    )
    parser.add_argument(
        "--no-stats",
        action="store_true",
        help="Exclude numeric column statistics sections from the report",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Directory to save the output file (default: current directory)",
    )
    parser.add_argument(
        "--size-threshold",
        type=float,
        default=DEFAULT_SIZE_THRESHOLD_MB,
        help=f"File size threshold in MB above which to use memory-efficient loading (default: {DEFAULT_SIZE_THRESHOLD_MB})",
    )
    args = parser.parse_args()

    main(
        output_dir=args.output_dir,
        no_samples=args.no_samples,
        no_stats=args.no_stats,
        size_threshold=args.size_threshold,
        project_dir=args.project_dir,
    )
