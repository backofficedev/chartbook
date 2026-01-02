"""
create_data_glimpses.py

Parses dodo.py to find all CSV/Parquet files and creates comprehensive
data glimpse reports in both XML (machine-readable) and TXT (human-readable) formats.
"""

import argparse
import os
import re
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from xml.sax import saxutils

import polars as pl

from chartbook.settings import config

DATA_DIR = Path(config("DATA_DIR"))
OUTPUT_DIR = Path(config("OUTPUT_DIR"))
BASE_DIR = Path(config("BASE_DIR"))

# Default file size threshold (in MB) above which to use memory-efficient loading
DEFAULT_SIZE_THRESHOLD_MB = 50


def fix_glimpse_row_count(glimpse_text: str, actual_row_count: int) -> str:
    """Replace the sample row count in glimpse output with the actual total row count.

    Polars glimpse output starts with "Rows: X" where X is the number of rows in the
    sampled DataFrame. This function replaces that with the actual total row count.

    Args:
        glimpse_text: The glimpse output text from Polars.
        actual_row_count: The actual total number of rows in the dataset.

    Returns:
        The glimpse text with the corrected row count.
    """
    return re.sub(r"^Rows: \d+", f"Rows: {actual_row_count}", glimpse_text)


def parse_dodo_tasks():
    """Use doit's internal API to get all tasks and their associated data files."""
    import sys
    from pathlib import Path

    # Add the current working directory to the Python path
    cwd = Path.cwd()
    if str(cwd) not in sys.path:
        sys.path.insert(0, str(cwd))

    # Import dodo from the current directory
    import importlib.util

    dodo_path = cwd / "dodo.py"
    if not dodo_path.exists():
        raise FileNotFoundError(f"No dodo.py file found in {cwd}")

    spec = importlib.util.spec_from_file_location("dodo", dodo_path)
    dodo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dodo)

    # Get all task functions from the dodo module
    task_functions = [
        getattr(dodo, name) for name in dir(dodo) if name.startswith("task_")
    ]

    # Dictionary to store task_name -> list of files
    task_files = {}

    # Generate tasks from each task function
    for task_func in task_functions:
        try:
            # Call the task function to get task(s)
            result = task_func()

            # Handle both single tasks and generators
            if hasattr(result, "__iter__") and not isinstance(result, (str, dict)):
                # It's a generator or list of tasks
                for task_dict in result:
                    if isinstance(task_dict, dict):
                        process_task_dict(task_dict, task_func.__name__, task_files)
            elif isinstance(result, dict):
                # It's a single task dictionary
                process_task_dict(result, task_func.__name__, task_files)
        except Exception as e:
            print(f"Warning: Could not process task function {task_func.__name__}: {e}")
            continue

    return task_files


def process_task_dict(task_dict, base_name, task_files):
    """Process a single task dictionary to extract files."""
    # Get the task name
    if "name" in task_dict:
        # For subtasks, combine base name with task name
        if base_name.startswith("task_"):
            base_name = base_name[5:]  # Remove 'task_' prefix
        task_name = f"{base_name}:{task_dict['name']}"
    elif base_name.startswith("task_"):
        task_name = base_name[5:]  # Remove 'task_' prefix
    else:
        task_name = base_name

    files = set()

    # Extract files from targets
    if task_dict.get("targets"):
        for target in task_dict["targets"]:
            target_str = str(target)
            if target_str.endswith((".csv", ".parquet")):
                files.add(target_str)

    # Extract files from file_dep
    if task_dict.get("file_dep"):
        for dep in task_dict["file_dep"]:
            dep_str = str(dep)
            if dep_str.endswith((".csv", ".parquet")):
                files.add(dep_str)

    if files:
        task_files[task_name] = sorted(files)


def get_dataset_report(
    filepath, include_stats=True, size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB
):
    """Return a dict with file metadata, shape, columns, sample values, numeric stats, and glimpse.

    For files larger than size_threshold_mb, uses memory-efficient loading by only
    collecting sampled data and correcting the row count in glimpse output.

    Args:
        filepath: Path to the CSV or Parquet file.
        include_stats: If True, include numeric column statistics.
        size_threshold_mb: File size threshold in MB above which to use memory-efficient loading.

    Returns:
        A dict containing file metadata, shape, columns, sample values, numeric stats, and glimpse.
    """
    report = {}
    try:
        # File info
        report["file_size_bytes"] = os.path.getsize(filepath)
        report["file_size_mb"] = report["file_size_bytes"] / (1024 * 1024)
        report["file_type"] = Path(filepath).suffix.replace(".", "").upper()

        # Determine if this is a large file
        is_large_file = report["file_size_mb"] > size_threshold_mb

        # Load data lazily
        if filepath.endswith(".csv"):
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


def format_task_name(task_name):
    """Format task name for display."""
    # Handle subtask names like "pull:cds_bond_basis"
    if ":" in task_name:
        main_task, sub_task = task_name.split(":", 1)
        # Format both parts
        main_formatted = main_task.replace("_", " ").title()
        sub_formatted = sub_task.replace("_", " ").title()
        return f"{main_formatted}: {sub_formatted}"
    else:
        # Handle simple task names
        formatted = task_name.replace("_", " ").title()
        return formatted


def get_task_category(task_name):
    """Extract the main task category from a task name."""
    if ":" in task_name:
        return task_name.split(":", 1)[0]
    else:
        return task_name


def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    size_mb = size_bytes / (1024 * 1024)
    if size_mb < 1:
        return f"{size_bytes} bytes"
    elif size_mb < 1024:
        return f"{size_mb:.1f} MB"
    else:
        return f"{size_mb / 1024:.1f} GB"


def filename_to_anchor(filename):
    """Convert a filename to a markdown anchor link format."""
    # Convert to lowercase and replace non-alphanumeric characters with hyphens
    # Keep the full filename including extension since section headers include it
    anchor = filename.lower()
    anchor = "".join(c if c.isalnum() else "-" for c in anchor)
    # Remove multiple consecutive hyphens and leading/trailing hyphens
    while "--" in anchor:
        anchor = anchor.replace("--", "-")
    anchor = anchor.strip("-")
    return anchor


def create_txt_report(
    existing_files,
    include_samples=True,
    include_stats=True,
    size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB,
):
    """Create a human-readable TXT format Data Glimpses Report."""
    output_lines = []

    # Parse dodo tasks to group files
    task_files = parse_dodo_tasks()

    # Create a mapping of files to tasks
    file_to_tasks = {}
    for task, files in task_files.items():
        for f in files:
            if f in existing_files:
                if f not in file_to_tasks:
                    file_to_tasks[f] = []
                file_to_tasks[f].append(task)

    # Header
    output_lines.append("# Data Glimpses Report")
    output_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output_lines.append(f"Total files: {len(existing_files)}")
    output_lines.append("")

    # Summary section grouped by task categories and subtasks
    output_lines.append("## Summary of Datasets by Task")
    output_lines.append("")

    # Group files by their task categories
    task_grouped = {}
    for f in sorted(existing_files):
        tasks = file_to_tasks.get(f, ["Unknown"])
        for task in tasks:
            category = get_task_category(task)
            if category not in task_grouped:
                task_grouped[category] = {}
            if task not in task_grouped[category]:
                task_grouped[category][task] = []
            task_grouped[category][task].append(f)

    # Output the summary
    for category in sorted(task_grouped.keys()):
        category_formatted = format_task_name(category)
        output_lines.append(f"### {category_formatted}")

        for task in sorted(task_grouped[category].keys()):
            if ":" in task:
                # This is a subtask, show it as a subheading
                task_formatted = format_task_name(task)
                output_lines.append(f"#### {task_formatted}")
                for f in sorted(task_grouped[category][task]):
                    filename = Path(f).name
                    anchor = filename_to_anchor(filename)
                    output_lines.append(f"- [`{filename}`](#{anchor})")
            else:
                # This is a main task without subtasks
                for f in sorted(task_grouped[category][task]):
                    filename = Path(f).name
                    anchor = filename_to_anchor(filename)
                    output_lines.append(f"- [`{filename}`](#{anchor})")
        output_lines.append("")

    output_lines.append("---")

    # Process each file
    for i, f in enumerate(sorted(existing_files), 1):
        filename = Path(f).name
        report = get_dataset_report(
            f, include_stats=include_stats, size_threshold_mb=size_threshold_mb
        )

        output_lines.append("")
        output_lines.append(f"## {filename}")
        output_lines.append(f"**Path:** `{f}`")

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
    existing_files, include_stats=True, size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB
):
    """Create a machine-readable XML format Data Glimpses Report."""
    output_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<data_glimpses_report>",
        "  <summary>",
    ]

    # Add summary section
    for f in sorted(existing_files):
        filename = Path(f).name
        output_lines.append(
            f'    <dataset filename="{saxutils.escape(filename)}" path="{saxutils.escape(str(f))}"/>'
        )
    output_lines.append("  </summary>")
    output_lines.append("  <datasets>")

    # Add each dataset
    for f in sorted(existing_files):
        filename = Path(f).name
        report = get_dataset_report(
            f, include_stats=include_stats, size_threshold_mb=size_threshold_mb
        )
        output_lines.append(
            f'    <dataset filename="{saxutils.escape(filename)}" path="{saxutils.escape(str(f))}">'
        )

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
):
    """Main function to create the data glimpses files in both XML and TXT formats.

    Args:
        output_dir: Directory to save the output file. If None, saves to current directory.
        no_samples: If True, exclude sample values sections from the report.
        no_stats: If True, exclude numeric column statistics sections from the report.
        size_threshold: File size threshold in MB above which to use memory-efficient loading.
    """
    print("Parsing dodo.py for tasks and data files...")

    # Check if dodo.py exists in current directory
    dodo_path = Path.cwd() / "dodo.py"
    if not dodo_path.exists():
        raise FileNotFoundError(
            f"No dodo.py file found in current directory: {Path.cwd()}"
        )

    task_files = parse_dodo_tasks()

    # Collect all files and check which exist
    all_files = set()
    for files in task_files.values():
        all_files.update(files)

    existing_files = {f for f in all_files if Path(f).exists()}

    print(
        f"Found {len(task_files)} tasks with {len(existing_files)} existing data files"
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
        existing_files,
        include_samples=include_samples,
        include_stats=include_stats,
        size_threshold_mb=size_threshold,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(txt_content)
    print(f"Report saved to: {output_path}")

    print(f"\nProcessed {len(existing_files)} files from {len(task_files)} tasks")
    print("Report generated successfully!")


if __name__ == "__main__":
    # Parse command line arguments for standalone usage
    parser = argparse.ArgumentParser(
        description="Generate data glimpses report from dodo.py tasks"
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
    )
