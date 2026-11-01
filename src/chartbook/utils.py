import json
import math
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


def copy_file(source, destination):
    """Copy a file's contents, and nothing else, to a destination path.

    Permissions, ownership and timestamps are deliberately not carried over.
    On shared and network drives the calls that set them are often refused,
    and a build should not fail over metadata.

    :param source: The file to copy.
    :type source: str or Path
    :param destination: The file to write (not a directory).
    :type destination: str or Path
    """
    shutil.copyfile(source, destination)


def copy_tree(source, destination):
    """Copy a directory tree's contents into a destination, merging with it.

    Like :func:`copy_file`, this copies file contents only. Existing files in
    the destination are overwritten; others are left in place.

    :param source: The directory to copy.
    :type source: str or Path
    :param destination: The directory to copy into; created if missing.
    :type destination: str or Path
    """
    source, destination = Path(source), Path(destination)
    for root, _, files in os.walk(source, followlinks=True):
        target_dir = destination / Path(root).relative_to(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copyfile(Path(root) / name, target_dir / name)


def move_tree(source, destination):
    """Move a directory, falling back to copy-and-delete across file systems.

    :param source: The directory to move.
    :type source: str or Path
    :param destination: Where it should end up; must not already exist.
    :type destination: str or Path
    """
    try:
        os.rename(source, destination)
    except OSError:
        copy_tree(source, destination)
        shutil.rmtree(source)


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


#: How many rows a dataframe's glimpse shows, from the top of the file
GLIMPSE_ROWS = 5

#: How many significant digits a float in a glimpse may be rounded to: as
#: many as a float holds for certain. See :func:`_for_display` for when it is
GLIMPSE_DIGITS = 15


def directory_tables(directory) -> list:
    """The files a reader opens when a dataframe's path is a folder: its parquet parts, sorted.

    The rule is the one a directory pinned from another pipeline is read by
    (``chartbook.resolve._held``): of the files the index counts
    (:func:`chartbook.hashing.directory_files`), none under a name starting
    ``.`` or ``_`` (Spark's ``_SUCCESS``, Hadoop's ``.crc`` files), none that
    is plainly not a table (a ``README.txt``, a ``schema.json``;
    :data:`chartbook.resolve.NOT_TABLES`), and of the rest each named
    ``.parquet`` or that begins or ends as parquet does (Hive's ``000000_0``).
    Judged from the folder's files on disk; a folder pinned from a store is
    read as the files its record lists, and its object is checked whole
    against that list before it is laid out, so the two agree there.

    :param directory: The folder.
    :type directory: str or Path
    :returns: The files, absolute as *directory* is, in name order.
    :rtype: list[Path]
    """
    from chartbook import hashing
    from chartbook.resolve import NOT_TABLES, _is_parquet

    directory = Path(directory)
    tables = []
    for file in sorted(hashing.directory_files(directory)):
        parts = file.relative_to(directory).parts
        if any(part.startswith((".", "_")) for part in parts) or parts[-1].lower().endswith(NOT_TABLES):
            continue
        if parts[-1].lower().endswith(".parquet") or _is_parquet(file):
            tables.append(file)
    return tables


def get_dataframe_glimpse(filepath, format=None, read_options=None):
    """Get a simple glimpse of a dataframe showing columns and data types.

    Shows the first :data:`GLIMPSE_ROWS` rows, with floats rounded for
    display (:func:`glimpse_text`). Only those rows are collected, whatever
    the size of the file; the row count is the file's own. The file is read
    as ``data.load()`` reads it, by the shared reader
    (:mod:`chartbook.formats`): a folder by its parts of its format
    (for parquet, :func:`directory_tables`); one with no part yet is said
    in a sentence.

    :param filepath: Path to the file, a glob of files, or a folder of parts.
    :type filepath: str or Path
    :param format: The dataframe's ``format``, if its manifest gives one.
    :type format: str, optional
    :param read_options: The dataframe's ``read_options``, if its manifest gives them.
    :type read_options: dict, optional
    :returns: The glimpse output as a string, or error message if file cannot be read.
    :rtype: str
    """
    from chartbook import formats

    try:
        filepath = Path(filepath)
        if filepath.is_dir():
            reading = formats.reading(filepath, format, read_options)
            if not formats.files_of(filepath, reading):
                # The folder by its name: the page says where it is, and a
                # machine's path belongs on no page
                kind = formats.NAMES[reading.format]
                return f"No {kind} file in {filepath.name}/: a folder is shown by its {kind} parts, and this one has none yet."
        lf = formats.scan(filepath, format, read_options, public=True)

        # Get actual row count efficiently (works for both small and large files)
        row_count_df = lf.select(pl.len().alias("count")).collect()
        actual_row_count = row_count_df["count"][0]

        sample_df = lf.head(GLIMPSE_ROWS).collect()

        # Fix row count in glimpse to show actual total rows
        return fix_glimpse_row_count(glimpse_text(sample_df), actual_row_count)

    except FileNotFoundError:
        return f"Error reading file: {Path(filepath).name} is not there."
    # A panic in polars is a BaseException: a page, not a crash of the build
    except (Exception, pl.exceptions.PanicException) as e:
        # The file by its name: a machine's paths belong on no page, nor
        # the end of one that polars cuts short ("...chartbook/x.parquet")
        said = str(e)
        for folder in {str(Path(filepath).parent), str(Path(filepath).parent.resolve())}:
            said = said.replace(folder + os.sep, "").replace(folder, ".")
        said = re.sub(r"\.\.\.\S*/([^/\s]+)", r"\1", said)
        return f"Error reading file: {said}"


#: The most characters a recorded glimpse keeps: a glimpse is a page's first rows, not the data, and the index carries it.
GLIMPSE_MAX_CHARS = 20_000


def cap_glimpse(text: str) -> str:
    """A glimpse cut to :data:`GLIMPSE_MAX_CHARS`, with a line saying so: wide or long values must not swell the index."""
    if len(text) <= GLIMPSE_MAX_CHARS:
        return text
    return text[:GLIMPSE_MAX_CHARS].rstrip() + f"\n... (cut at {GLIMPSE_MAX_CHARS:,} characters)"


def source_glimpse(record: dict, base_dir) -> str:
    """A table or query's glimpse, from the engine the record's location names: its shape, columns and first rows.

    The location's url is the manifest's, relative to the pipeline's folder
    for a DuckDB file; the machine's url comes through ``source_url()``, and
    a relative file is made absolute against the pipeline's folder, never
    against where the build happens to run. A page shows this as text; the
    index records it (:mod:`chartbook.index`) so that a version rendered
    from the store shows it without opening the engine.
    """
    from chartbook.backends import MEMORY_URL, duckdb_path, open_backend, source_url
    from chartbook.resolve import QueryLocation, TableLocation

    location = record["location"]
    where = (
        f"table {location['identifier']}" if location["kind"] == "table" else "query"
    ) + f" in source {location.get('source')!r} ({location.get('backend')})"
    if not location.get("url"):
        return f"A {where}."
    try:
        # A DuckDB file is found through the machine's url, relative to the
        # pipeline's folder; another engine finds its own from the public one
        url = location["url"]
        if location.get("backend") == "duckdb":
            url = source_url(location["source"], url)
            path = duckdb_path(url, base_dir)
            url = MEMORY_URL if path == ":memory:" else "duckdb:///" + path
    except Exception as error:  # noqa: BLE001 - a page, not a crash
        return f"A {where}. It could not be read when the site was built: {error}"
    if location["kind"] == "table":
        typed = TableLocation(location["source"], location["backend"], url, location["identifier"])
    else:
        typed = QueryLocation(location["source"], location["backend"], url, location["sql"])
    try:
        backend = open_backend(location["backend"], url, location["source"])
        columns, rows = backend.describe(typed)
        sample = backend.scan(typed).head(5).collect()
    except (Exception, pl.exceptions.PanicException) as error:  # noqa: BLE001 - a page, not a crash; polars panics on a type it cannot import
        return f"A {where}. It could not be read when the site was built: {error}"
    lines = [f"A {where}: {rows} rows, {len(columns)} columns.", ""]
    lines += [f"  {column['name']}: {column['dtype']}" for column in columns]
    lines += ["", "First rows:", str(sample)]
    return cap_glimpse("\n".join(lines))


def most_recent_valid_datapoints(
    path,
    date_col: str = "date",
    size_threshold_mb: float = 50,
    format=None,
    read_options=None,
) -> tuple:
    """The least and greatest of each column's last non-null date, as text, for a dataframe page.

    "N/A" without a date column or for a folder of parts; "N/A (large file)"
    over the size threshold, so a big file is not read for two dates. The
    file is read as ``data.load()`` reads it (:mod:`chartbook.formats`).
    The index records what this gives as ``last_dates`` when it describes
    the file, so a version rendered from the store shows it without the
    data (:mod:`chartbook.index`).
    """
    from chartbook import formats
    from chartbook.utils import is_glob_pattern as _is_glob

    if date_col in ("", "NA", "N/A"):
        return "N/A", "N/A"
    if _is_glob(str(path)) or os.path.isdir(path):
        return "N/A", "N/A"  # a dataset of many parts is not read whole for two dates
    if os.path.getsize(path) / (1024 * 1024) > size_threshold_mb:
        return "N/A (large file)", "N/A (large file)"
    frame = formats.scan(path, format, read_options).collect()
    if frame[date_col].dtype == pl.String:
        frame = frame.with_columns(pl.col(date_col).str.to_datetime(strict=False))  # text dates, as a CSV has them
    elif frame[date_col].dtype != pl.Datetime:
        frame = frame.with_columns(pl.col(date_col).cast(pl.Datetime, strict=False))
    latest = frame.select(
        [pl.col(date_col).filter(pl.col(col).is_not_null()).max().alias(col) for col in frame.columns if col != date_col]
    )
    dates = [date for date in latest.row(0) if date is not None]
    if not dates:
        return "N/A", "N/A"
    return min(dates).strftime("%Y-%m-%d %H:%M:%S"), max(dates).strftime("%Y-%m-%d %H:%M:%S")


def glimpse_text(sample: pl.DataFrame) -> str:
    """Polars' glimpse of a few rows, as text, with floats rounded for a reader.

    A float that is the noise of a binary fraction is shown as the number it
    stands for (``3.8499999999999996`` reads ``3.85``; :func:`_for_display`),
    and every other value as it is. A ``f32`` column is widened to show its
    digits as written (``1.1``, not ``1.100000023841858``), and is still
    labelled ``<f32>``; not when a column's name has a line break in it,
    since the label is put back by the line the column is on.
    """
    broken = any("\n" in name or "\r" in name for name in sample.columns)
    narrow = set() if broken else {name for name, dtype in sample.schema.items() if dtype == pl.Float32}
    shown = sample.with_columns(pl.col(sorted(narrow)).cast(pl.String).cast(pl.Float64))
    shown = shown.with_columns(
        [
            pl.Series(name, [_for_display(value) for value in shown[name].to_list()], dtype=pl.Float64)
            for name, dtype in shown.schema.items()
            if dtype == pl.Float64
        ]
    )
    output = StringIO()
    with redirect_stdout(output):
        shown.glimpse()
    # "Rows: …" and "Columns: …", then one line per column in order. A name
    # is shown left-aligned and cut at 50 characters, so the type's label
    # comes after it
    lines = output.getvalue().split("\n")
    if len(lines) < sample.width + 2:
        return "\n".join(lines)
    for position, name in enumerate(sample.columns):
        if name in narrow:
            line = lines[2 + position]
            at = line.find("<f64>", 2 + min(len(name), 49))
            if at >= 0:
                lines[2 + position] = line[:at] + "<f32>" + line[at + len("<f64>") :]
    return "\n".join(lines)


def _for_display(value):
    """A float as a glimpse shows it: rounded only when what is cut is noise.

    A whole number (a date written as 20240115.0, an ID, ``2**53``) and a
    value that is not finite are shown as they are. Any other is rounded to
    :data:`GLIMPSE_DIGITS` significant digits, with Python's formatting,
    exact at any magnitude, when the result is within two units in the last
    place of the value: so ``3.8499999999999996`` reads ``3.85`` and
    ``0.1 + 0.2`` reads ``0.3``, while ``1/3`` keeps all its digits.
    """
    if value is None or not math.isfinite(value) or value.is_integer():
        return value
    rounded = float(f"{value:.{GLIMPSE_DIGITS}g}")
    if math.isfinite(rounded) and abs(rounded - value) <= 2 * math.ulp(value):
        return rounded
    return value


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
        with open(notebook_path, "w", encoding="utf-8", newline="\n") as f:
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
