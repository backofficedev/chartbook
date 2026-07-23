import json
import os
import re
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import polars as pl


def is_glob_pattern(path_str) -> bool:
    """Check if a path string contains glob pattern characters.

    :param path_str: The path string to check.
    :type path_str: str or Path
    :returns: True if the path contains glob characters (``*``, ``?``, ``[``).
    :rtype: bool
    """
    return any(c in str(path_str) for c in ("*", "?", "["))

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


# --------------------------------------------------------------------
#  SAFER FILE-COPY PATCHES  - drop these near the top of generator.py
# --------------------------------------------------------------------
# This patch allows for safer copying on shared directories.
def _noop(*_a, **_k):
    """Do nothing - used to replace chmod/chown/timestamp operations.

    :param _a: Positional arguments (ignored).
    :type _a: Any
    :param _k: Keyword arguments (ignored).
    :type _k: Any
    """


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

    Examples
    --------

    ```python
    from pathlib import Path

    # Create dummy source files and directories
    Path("./source").mkdir(exist_ok=True)
    Path("./source/subdir").mkdir(exist_ok=True)
    Path("./source/data.csv").touch()
    Path("./source/subdir/image.png").touch()

    plan = {
        Path("./source/data.csv"): Path("./destination/data_files/data.csv"),
        Path("./source/subdir/image.png"): Path("./destination/images/image.png"),
    }

    # Copy silently (default)
    copy_according_to_plan(plan, mkdir=True)

    # Copy verbosely
    copy_according_to_plan(plan, mkdir=True, verbose=True)
    # Output:
    # Copied source/data.csv to destination/data_files/data.csv
    # Copied source/subdir/image.png to destination/images/image.png

    # Clean up dummy files/dirs
    shutil.rmtree("./source")
    shutil.rmtree("./destination")
    ```
    """
    for source, destination in publish_plan.items():
        # Ensure both source and destination are Path objects
        source_path = Path(source)
        destination_path = Path(destination)

        # Warn if source file doesn't exist (should have been caught by validation)
        if not source_path.exists():
            import warnings

            warnings.warn(
                f"Skipping {source_path} - file does not exist "
                f"(should have been caught by validation)",
                stacklevel=2,
            )
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

        if is_glob_pattern(str(filepath)):
            # Glob/hive-partitioned paths: use scan_parquet directly
            lf = pl.scan_parquet(filepath, hive_partitioning=True)
            is_large_file = False
        else:
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


# Regex to match MathJax 2 script tags injected by Plotly's NotebookRenderer.
# Plotly hardcodes include_mathjax="cdn" which embeds a MathJax 2.7.x CDN script
# and an optional SVG font config script into every Plotly cell output. When Sphinx
# (via myst-nb) copies these into HTML, MathJax 2 conflicts with Sphinx's MathJax 3
# and crashes all math rendering on the page.
MATHJAX2_PATTERN = re.compile(
    r'<script src="https://cdnjs\.cloudflare\.com/ajax/libs/mathjax/2\.[^"]*">[^<]*</script>'
    r'(?:\s*<script type="text/javascript">if \(window\.MathJax && window\.MathJax\.Hub'
    r" && window\.MathJax\.Hub\.Config\) \{window\.MathJax\.Hub\.Config\(\{SVG:"
    r' \{font: "STIX-Web"\}\}\);\}</script>)?'
)


def strip_mathjax2_from_notebook(notebook_path):
    """Strip MathJax 2 script tags injected by Plotly from notebook cell outputs.

    Plotly's NotebookRenderer injects MathJax 2 CDN scripts into every Plotly cell
    output. These conflict with Sphinx's MathJax 3, crashing all math rendering.
    This function removes those script tags from the notebook's saved outputs.

    :param notebook_path: Path to the .ipynb file to sanitize (modified in-place).
    :type notebook_path: str or Path
    :returns: True if the notebook was modified, False otherwise.
    :rtype: bool
    """
    notebook_path = Path(notebook_path)
    with open(notebook_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    modified = False
    for cell in nb.get("cells", []):
        for output in cell.get("outputs", []):
            if "data" in output and "text/html" in output["data"]:
                html_parts = output["data"]["text/html"]
                if isinstance(html_parts, list):
                    new_parts = []
                    for part in html_parts:
                        cleaned = MATHJAX2_PATTERN.sub("", part)
                        if cleaned != part:
                            modified = True
                        new_parts.append(cleaned)
                    output["data"]["text/html"] = new_parts
                elif isinstance(html_parts, str):
                    cleaned = MATHJAX2_PATTERN.sub("", html_parts)
                    if cleaned != html_parts:
                        modified = True
                        output["data"]["text/html"] = cleaned

    if modified:
        with open(notebook_path, "w", encoding="utf-8") as f:
            json.dump(nb, f, indent=1, ensure_ascii=False)
            f.write("\n")

    return modified


def extract_notebook_title(notebook_path):
    """Extract the first level-1 markdown heading from a notebook.

    Searches through all cells for the first markdown cell containing a
    level-1 heading (``# Title``). Returns the heading text, or ``None``
    if no level-1 heading is found.

    :param notebook_path: Path to the ``.ipynb`` file.
    :type notebook_path: str or Path
    :returns: The heading text (without the ``#`` prefix), or ``None``.
    :rtype: str | None
    """
    notebook_path = Path(notebook_path)
    with open(notebook_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = "".join(cell.get("source", []))
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("##"):
                return stripped[2:].strip()
    return None
