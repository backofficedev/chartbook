import os
import re
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import polars as pl

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


# --------------------------------------------------------------------
#  SAFER FILE-COPY PATCHES  – drop these near the top of generator.py
# --------------------------------------------------------------------
# This patch allows for safer copying on shared directories.
def _noop(*_a, **_k):
    """Do nothing – used to replace chmod/chown/timestamp operations."""


# 1. Disable metadata copying that needs chmod/chown
shutil.copymode = _noop  # used by shutil.copy
shutil.copystat = _noop  # used by shutil.copy2 / copytree

# 2. Make copy2 behave like copy (now metadata-free as well)
shutil.copy2 = shutil.copy
# --------------------------------------------------------------------


def copy_according_to_plan(publish_plan, mkdir=False, verbose: bool = False):
    """Copies files from source paths to destination paths as specified in the publish_plan.

    :param publish_plan: A dictionary where keys are source file paths and values are destination file paths.
    :type publish_plan: dict
    :param mkdir: If True, creates the parent directories for destination paths if they do not exist. Defaults to False.
    :type mkdir: bool
    :param verbose: If True, prints each copy operation to standard output. Defaults to False.
    :type verbose: bool

    **Examples**

    ```python
    >>> from pathlib import Path
    >>> # Create dummy source files and directories
    >>> Path("./source").mkdir(exist_ok=True)
    >>> Path("./source/subdir").mkdir(exist_ok=True)
    >>> Path("./source/data.csv").touch()
    >>> Path("./source/subdir/image.png").touch()
    >>>
    >>> plan = {
    ...     Path("./source/data.csv"): Path("./destination/data_files/data.csv"),
    ...     Path("./source/subdir/image.png"): Path("./destination/images/image.png"),
    ... }
    >>>
    >>> # Copy silently (default)
    >>> copy_according_to_plan(plan, mkdir=True)
    >>>
    >>> # Copy verbosely
    >>> copy_according_to_plan(plan, mkdir=True, verbose=True)
    Copied source/data.csv to destination/data_files/data.csv
    Copied source/subdir/image.png to destination/images/image.png
    >>>
    >>> # Clean up dummy files/dirs
    >>> shutil.rmtree("./source")
    >>> shutil.rmtree("./destination")
    ```
    """
    for source, destination in publish_plan.items():
        # Ensure both source and destination are Path objects
        source_path = Path(source)
        destination_path = Path(destination)

        # Skip if source file doesn't exist
        if not source_path.exists():
            if verbose:
                print(f"Skipping {source_path} - file does not exist")
            continue

        # Create parent directories if needed
        if mkdir:
            destination_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file content only, without attempting to copy permissions
        shutil.copyfile(source_path, destination_path)
        if verbose:
            print(f"Copied {source_path} to {destination_path}")

        # Try to set reasonable permissions after copying
        try:
            os.chmod(destination_path, 0o644)  # rw-r--r-- for files
        except (OSError, PermissionError):
            # If we can't set permissions, just continue
            pass


def get_dataframe_glimpse(filepath, size_threshold_mb=DEFAULT_SIZE_THRESHOLD_MB):
    """Get a simple glimpse of a dataframe showing columns and data types.

    For files larger than size_threshold_mb, uses memory-efficient loading by only
    collecting sampled data and correcting the row count in glimpse output.

    :param filepath: Path to the parquet or CSV file.
    :type filepath: str or Path
    :param size_threshold_mb: File size threshold in MB above which to use memory-efficient loading.
    :type size_threshold_mb: float
    :returns: The glimpse output as a string, or error message if file cannot be read.
    :rtype: str
    """
    try:
        filepath = Path(filepath)

        # Check file size to determine loading strategy
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        is_large_file = file_size_mb > size_threshold_mb

        # Load data lazily
        if filepath.suffix.lower() == ".csv":
            lf = pl.scan_csv(filepath)
        elif filepath.suffix.lower() == ".parquet":
            lf = pl.scan_parquet(filepath)
        else:
            return f"Unsupported file type: {filepath.suffix}"

        # Get actual row count efficiently (works for both small and large files)
        row_count_df = lf.select(pl.len().alias("count")).collect()
        actual_row_count = row_count_df["count"][0]

        # For large files, use head() to avoid full scan; for small files, tail() is fine
        if is_large_file:
            sample_df = lf.head(1).collect()
        else:
            sample_df = lf.tail(1).collect()

        # Capture the glimpse output
        output = StringIO()
        with redirect_stdout(output):
            sample_df.glimpse()

        glimpse_text = output.getvalue()

        # Fix row count in glimpse to show actual total rows
        return fix_glimpse_row_count(glimpse_text, actual_row_count)

    except Exception as e:
        return f"Error reading file: {e!s}"
