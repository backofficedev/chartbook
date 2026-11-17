"""The memory a rows hash takes: set by the period, never by the table (``docs_src/design/pins-and-rebuilds.md``, "What it costs").

The target is a peak under 2 GB for any table that is hashed, so that a
machine with 8 GB is safe. Each test here hashes a table, and then checks
it against its own record, in a process of its own **under a memory
limit**: the process watches the most memory it has ever held, as the
operating system counts it, and stops itself the moment that passes the
limit. The test then also reads that figure and holds it to the limit.

Two kinds of table:

- **Made here**, in the shapes that took the most memory in the prototype:
  a wide table of floats and a table of text, each written as one row
  group, which a reader that takes a row group whole must hold whole.
  They run everywhere but Windows, which has no such count to read.
- **The four tables the design names** (the class's yield curve, CRSP
  daily, the GKX characteristics, RavenPack), which are licensed data and
  on the maintainer's disk only. They run when ``CHARTBOOK_ROWS_TABLES``
  names a JSON file that says where they are::

      {"crsp daily": {"path": "~/data/CRSP_daily_stock.parquet", "date_col": "date"}}

      CHARTBOOK_ROWS_TABLES=_temp/rows-hash/tables.json uv run pytest tests/test_rows_memory.py -v -s
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from chartbook import rowhash

#: The target: the most memory hashing any table may take, in bytes.
LIMIT = 2 * 1024**3

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Windows has no count of a process's peak memory in the standard library")

#: What the child runs: hash the table by period, check it against its own
#: record, and say what it took; with a watch on its own peak memory.
CHILD = r"""
import json, os, resource, sys, threading, time

limit, path, date_col, period = int(sys.argv[1]), sys.argv[2], sys.argv[3] or None, int(sys.argv[4])
scale = 1 if sys.platform == "darwin" else 1024  # bytes on macOS, kilobytes elsewhere


def peak():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale


def watch():
    while True:
        if peak() > limit:
            sys.stderr.write(f"over the limit: {peak() / 1e9:.2f} GB\n")
            sys.stderr.flush()
            os._exit(3)
        time.sleep(0.01)


threading.Thread(target=watch, daemon=True).start()

from chartbook import rowhash

if period:
    rowhash.PERIOD_BYTES, rowhash.MOST_BYTES = period, period
started = time.perf_counter()
record = rowhash.hash_rows(rowhash.Table(path), date_col)
pinned = time.perf_counter() - started
started = time.perf_counter()
compared = rowhash.hash_in(rowhash.Table(path), date_col, record.rows, record.as_of)
print(json.dumps({
    "rows": record.row_count, "periods": len(record.rows), "as_of": record.as_of, "same": compared.same,
    "pin_seconds": round(pinned, 1), "check_seconds": round(time.perf_counter() - started, 1), "peak": peak(),
}))
"""


def _hashed_under(limit: int, path, date_col, tmp_path, period: int = 0) -> dict:
    """Hash and check a table in a process that stops itself past *limit* bytes; what it said."""
    environment = {**os.environ, "CHARTBOOK_CACHE": str(tmp_path / "cache")}
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(limit), str(path), date_col or "", str(period)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment,
    )
    assert done.returncode == 0, f"the process stopped ({done.returncode}): {done.stderr[-2000:]}"
    said = json.loads(done.stdout.strip().splitlines()[-1])
    if os.environ.get("CHARTBOOK_ROWS_SHOW"):
        print(f"\n    {Path(str(path)).name}: {said['rows']:,} rows, {said['periods']} periods; hashed in {said['pin_seconds']} s, checked in {said['check_seconds']} s; peak {said['peak'] / 1e9:.2f} GB", file=sys.stderr)
    return said


def _wide(path: Path, rows: int = 400_000, columns: int = 99) -> int:
    """Floats, 99 columns, four years of days, one row group; how many bytes it takes in memory."""
    generator = np.random.default_rng(1)
    days = np.sort(generator.integers(0, 4 * 365, rows))
    table = pa.table(
        {
            "date": pa.array((np.datetime64("2020-01-01") + days).astype("datetime64[ns]")),
            **{f"c{i:02d}": generator.standard_normal(rows) for i in range(columns - 1)},
        }
    )
    pq.write_table(table, path, row_group_size=rows)
    return table.nbytes


def _text(path: Path, rows: int = 1_500_000) -> int:
    """Twelve columns of text and a time to the second, four years, one row group; how many bytes it takes in memory."""
    generator = np.random.default_rng(1)
    seconds = np.sort(generator.integers(0, 4 * 365 * 86400, rows))
    words = np.array([f"word{i:05d}-{'x' * (i % 9)}" for i in range(5000)])
    table = pa.table(
        {
            "timestamp_utc": pa.array((np.datetime64("2020-01-01T00:00:00") + seconds.astype("timedelta64[s]")).astype("datetime64[ns]")),
            **{f"t{i:02d}": pa.array(words[generator.integers(0, 5000, rows)]) for i in range(12)},
            "n": generator.integers(0, 10**9, rows),
        }
    )
    pq.write_table(table, path, row_group_size=rows)
    return table.nbytes


class TestTablesMadeHere:
    """Set by the period: a table several times a period's size, in one row group, is never held whole."""

    @pytest.mark.parametrize("make,date_col", [(_wide, "date"), (_text, "timestamp_utc")], ids=["wide floats", "text"])
    def test_a_table_in_one_row_group(self, tmp_path, make, date_col):
        size = make(tmp_path / "table.parquet")
        assert size > 300 * 1024**2
        # Periods of 16 MB, so that the table is twenty of them: what is held is a period and a batch
        said = _hashed_under(1024**3, tmp_path / "table.parquet", date_col, tmp_path, period=16 * 1024**2)
        assert said["same"] and said["periods"] == 48
        assert said["peak"] < 800 * 1024**2, f"{said['peak'] / 1e6:.0f} MB"

    @pytest.mark.parametrize("make,date_col", [(_wide, "date"), (_text, "timestamp_utc")], ids=["wide floats", "text"])
    def test_at_the_size_of_a_period_as_it_is(self, tmp_path, make, date_col):
        make(tmp_path / "table.parquet")
        said = _hashed_under(LIMIT, tmp_path / "table.parquet", date_col, tmp_path)
        assert said["same"] and said["peak"] < LIMIT

    def test_the_largest_piece_there_can_be(self, tmp_path):
        """One day of a wide table, just under the most a single piece may be: about five times its size."""
        rows = 150_000
        generator = np.random.default_rng(2)
        table = pa.table(
            {
                "date": pa.array(np.full(rows, np.datetime64("2024-01-02"), dtype="datetime64[ns]")),
                **{f"c{i:02d}": generator.standard_normal(rows) for i in range(98)},
            }
        )
        assert 0.85 * rowhash.MOST_BYTES < table.nbytes < rowhash.MOST_BYTES
        pq.write_table(table, tmp_path / "day.parquet", row_group_size=rows)
        said = _hashed_under(LIMIT, tmp_path / "day.parquet", "date", tmp_path)
        assert said["same"] and said["periods"] == 1 and said["peak"] < LIMIT

    def test_a_csv_at_the_most_it_may_be(self, tmp_path):
        """Only parquet is read a little at a time: a CSV is read whole, once, so its text is held to a size."""
        import polars as pl

        rows = 16_000
        generator = np.random.default_rng(3)
        days = np.sort(generator.integers(0, 4 * 365, rows))
        frame = pl.DataFrame(
            {
                "date": (np.datetime64("2020-01-01") + days).astype("datetime64[us]"),
                **{f"c{i:02d}": generator.standard_normal(rows) for i in range(98)},
            }
        )
        frame.write_csv(tmp_path / "table.csv")
        del frame
        assert 0.8 * rowhash.OTHER_BYTES < (tmp_path / "table.csv").stat().st_size <= rowhash.OTHER_BYTES
        said = _hashed_under(LIMIT, tmp_path / "table.csv", "date", tmp_path)
        assert said["same"] and said["rows"] == rows and said["peak"] < LIMIT

    def test_a_csv_of_little_text_and_much_memory(self, tmp_path):
        """A digit and a comma are two bytes of text and eight in memory: the most text there may be, of that."""
        rows, columns = 80_000, 200
        line = ",".join(["1"] * columns)
        with open(tmp_path / "table.csv", "w", encoding="utf-8", newline="\n") as held:
            held.write("date," + ",".join(f"c{i}" for i in range(columns)) + "\n")
            for i in range(rows):
                held.write(f"2020-{1 + i % 12:02d}-{1 + i % 28:02d},{line}\n")
        assert 0.8 * rowhash.OTHER_BYTES < (tmp_path / "table.csv").stat().st_size <= rowhash.OTHER_BYTES
        said = _hashed_under(LIMIT, tmp_path / "table.csv", "date", tmp_path)
        assert said["same"] and said["rows"] == rows and said["peak"] < LIMIT

    def test_rows_with_no_date_are_refused_before_they_are_held(self, tmp_path):
        """A table several times the most a piece may be, every row of it with no date: said, and never read whole."""
        rows = 1_500_000
        generator = np.random.default_rng(4)
        table = pa.table(
            {"date": pa.nulls(rows, pa.timestamp("us")), **{f"c{i:02d}": generator.standard_normal(rows) for i in range(60)}}
        )
        assert table.nbytes > 2.5 * rowhash.MOST_BYTES
        pq.write_table(table, tmp_path / "undated.parquet", row_group_size=rows)
        environment = {**os.environ, "CHARTBOOK_CACHE": str(tmp_path / "cache")}
        done = subprocess.run(
            [sys.executable, "-c", CHILD, str(1024**3), str(tmp_path / "undated.parquet"), "date", "0"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment,
        )
        assert done.returncode == 1 and "its rows with no date, 1,500,000 of them, count for" in done.stderr, done.stderr[-600:]

    def test_long_text_that_a_file_holds_once(self, tmp_path):
        """50 texts of 20 KB over 300,000 rows: 2 MB as a file, which says ten bytes a row, and 6 GB as rows. A batch is measured from its rows."""
        rows = 300_000
        words = pa.array([f"{i:04d}" + "x" * 20_000 for i in range(50)])
        table = pa.table(
            {
                "date": pa.array((np.datetime64("2023-01-01") + (np.arange(rows) // 400)).astype("datetime64[ns]")),
                "x": np.arange(rows),
                "text": pa.DictionaryArray.from_arrays(pa.array(np.arange(rows) % 50, pa.int32()), words),
            }
        )
        pq.write_table(table, tmp_path / "text.parquet")
        del table
        assert (tmp_path / "text.parquet").stat().st_size < 8 * 1024**2
        said = _hashed_under(LIMIT, tmp_path / "text.parquet", "date", tmp_path)
        assert said["same"] and said["periods"] == 750 and said["peak"] < LIMIT

    def test_many_columns_of_text_that_a_file_holds_once(self, tmp_path):
        """60 columns of 200 characters, 20 texts each: 11 MB as a file, 3.6 GB as rows."""
        rows = 300_000
        generator = np.random.default_rng(5)
        words = pa.array([f"{i:02d}" + "y" * 198 for i in range(20)])
        table = pa.table(
            {
                "date": pa.array((np.datetime64("2021-01-01") + np.sort(generator.integers(0, 3 * 365, rows))).astype("datetime64[ns]")),
                **{f"t{i:02d}": pa.DictionaryArray.from_arrays(pa.array(generator.integers(0, 20, rows), pa.int32()), words) for i in range(60)},
            }
        )
        pq.write_table(table, tmp_path / "wide_text.parquet")
        del table
        said = _hashed_under(LIMIT, tmp_path / "wide_text.parquet", "date", tmp_path)
        assert said["same"] and said["rows"] == rows and said["peak"] < LIMIT

    @pytest.mark.parametrize("shape", ["short text", "decimals", "floats in 255 columns"])
    def test_one_day_at_the_most_a_piece_may_be(self, tmp_path, shape):
        """A piece that cannot be split, as large as one may be, of what took the most beside its size: text of a character, decimals, and as many columns as are read."""
        from decimal import Decimal

        generator = np.random.default_rng(6)
        if shape == "short text":
            columns, each = 200, 17  # sixteen and one byte
            make = lambda rows: pa.DictionaryArray.from_arrays(pa.array(generator.integers(0, 20, rows), pa.int32()), pa.array([chr(97 + i) for i in range(20)]))  # noqa: E731
        elif shape == "decimals":
            columns, each = 100, 16
            values = pa.array([Decimal(i) / 100 for i in range(1000)], pa.decimal128(38, 6))
            make = lambda rows: values.take(pa.array(generator.integers(0, 1000, rows)))  # noqa: E731
        else:
            columns, each = 254, 8
            make = lambda rows: generator.standard_normal(rows)  # noqa: E731
        rows = int(0.97 * rowhash.MOST_BYTES / (columns * each + 8))
        table = pa.table(
            {"date": pa.array(np.full(rows, np.datetime64("2024-01-02"), dtype="datetime64[ns]")), **{f"c{i:03d}": make(rows) for i in range(columns)}}
        )
        pq.write_table(table, tmp_path / "day.parquet", row_group_size=rows)
        del table
        said = _hashed_under(LIMIT, tmp_path / "day.parquet", "date", tmp_path)
        assert said["same"] and said["periods"] == 1 and said["rows"] == rows and said["peak"] < LIMIT

    def test_a_document_a_row(self, tmp_path):
        """Rows of two megabytes each, forty a day: read a few at a time, down to one."""
        rows = 400
        documents = pa.array([str(i) + "d" * 2_000_000 for i in range(2)])
        table = pa.table(
            {
                "date": pa.array((np.datetime64("2024-01-01") + (np.arange(rows) // 40)).astype("datetime64[ns]")),
                "document": pa.DictionaryArray.from_arrays(pa.array(np.arange(rows) % 2, pa.int32()), documents),
            }
        )
        pq.write_table(table, tmp_path / "documents.parquet")
        del table
        said = _hashed_under(LIMIT, tmp_path / "documents.parquet", "date", tmp_path)
        assert said["same"] and said["rows"] == rows and said["periods"] == 10 and said["peak"] < LIMIT

    def test_the_limit_is_a_limit(self, tmp_path):
        """The watch stops a process that passes it: a table held whole, under a limit it cannot meet."""
        _wide(tmp_path / "table.parquet")
        environment = {**os.environ, "CHARTBOOK_CACHE": str(tmp_path / "cache")}
        done = subprocess.run(
            [sys.executable, "-c", CHILD, str(200 * 1024**2), str(tmp_path / "table.parquet"), "date", "0"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment,
        )
        assert done.returncode == 3 and "over the limit" in done.stderr


def _named() -> dict:
    listed = os.environ.get("CHARTBOOK_ROWS_TABLES", "").strip()
    if not listed:
        return {}
    with open(os.path.expanduser(listed), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.skipif(not _named(), reason="CHARTBOOK_ROWS_TABLES names no file of tables")
class TestTheFourTablesTheDesignNames:
    """Under 2 GB on the class's yield curve, CRSP daily, the GKX characteristics and RavenPack."""

    @pytest.mark.parametrize("name", sorted(_named()))
    def test_under_two_gigabytes(self, name, tmp_path, capsys):
        entry = _named()[name]
        path = Path(os.path.expanduser(entry["path"]))
        if not path.exists():
            pytest.skip(f"{path} is not on this disk")
        said = _hashed_under(LIMIT, path, entry.get("date_col"), tmp_path)
        with capsys.disabled():
            print(
                f"\n    {name}: {said['rows']:,} rows, {said['periods']} periods, through {said['as_of']}; "
                f"hashed in {said['pin_seconds']} s, checked in {said['check_seconds']} s; "
                f"peak {said['peak'] / 1e9:.2f} GB"
            )
        assert said["same"]
        assert said["peak"] < LIMIT, f"{name}: {said['peak'] / 1e9:.2f} GB"
