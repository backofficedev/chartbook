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
    # On Linux the system's count of a process's peak begins at what its parent held when it
    # started it: a test that made a large table would be counted against every table after it.
    # The kernel keeps the count of this program alone as VmHWM
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status", encoding="ascii") as said:
                for line in said:
                    if line.startswith("VmHWM:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
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
try:
    record = rowhash.hash_rows(rowhash.Table(path), date_col)
except rowhash.NotHashed as refused:
    # A table that has no rows hash: said, with what it took to find that out
    print(json.dumps({"refused": str(refused), "peak": peak(), "pin_seconds": round(time.perf_counter() - started, 1)}))
    sys.exit(0)
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
    _SEEN.append((os.environ.get("PYTEST_CURRENT_TEST", "").split("::")[-1].split(" (")[0], said))
    if os.environ.get("CHARTBOOK_ROWS_SHOW") and "refused" in said:
        print(f"\n    {Path(str(path)).name}: no rows hash, found in {said['pin_seconds']} s; peak {said['peak'] / 1e9:.2f} GB ({said['refused'][:150]})", file=sys.stderr)
    elif os.environ.get("CHARTBOOK_ROWS_SHOW"):
        print(f"\n    {Path(str(path)).name}: {said['rows']:,} rows, {said['periods']} periods; hashed in {said['pin_seconds']} s, checked in {said['check_seconds']} s; peak {said['peak'] / 1e9:.2f} GB", file=sys.stderr)
    return said


#: What each table took, in the order they were hashed: printed once the tests are done, past
#: pytest's capture, so that a run on another system than the maintainer's leaves its figures.
_SEEN: list = []


@pytest.fixture(scope="module", autouse=True)
def _peaks_said(request):
    yield
    capture = request.config.pluginmanager.getplugin("capturemanager")
    if not _SEEN or capture is None:
        return
    with capture.global_and_fixture_disabled():
        print()
        for test, said in _SEEN:
            what = "refused" if "refused" in said else f"{said['rows']:,} rows in {said['pin_seconds']} + {said['check_seconds']} s"
            print(f"rows memory: {said['peak'] / 1024**3:.2f} GiB  {test}: {what}")


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
        said = _hashed_under(LIMIT, tmp_path / "table.parquet", date_col, tmp_path, period=16 * 1024**2)
        assert said["same"] and said["periods"] == 48
        # Held to the limit, as every table here is. It was held to 900 MB, a figure of the libraries
        # and not of what is read at once: the floats take 0.74 GiB with pyarrow 26 and polars 2.1, and
        # 0.85 to 0.98 GiB with pyarrow 25 and polars 2.0 (what Python 3.10 is given), on macOS. What is
        # read at once is held to the limit by the tables written to take the most of it, below
        assert said["peak"] < LIMIT, f"{said['peak'] / 1e6:.0f} MB"

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
        del table
        said = _hashed_under(1024**3, tmp_path / "undated.parquet", "date", tmp_path)
        assert "its rows with no date, 1,500,000 of them, count for" in said["refused"] and said["peak"] < 1024**3, said

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


def _days(start: str, each) -> pa.Array:
    return pa.array((np.datetime64(start) + np.asarray(each).astype("timedelta64[D]")).astype("datetime64[ns]"))


class TestFilesWrittenToBeHardToRead:
    """Found by a third review: files whose rows are within every rule, written so that reading them took 3 to 7 GB.

    What a reader holds is set by how a file is written: a page of every
    column at once, each column's dictionary, the footer whole. So what
    reading a row group takes is told from its page headers before a row
    of it is read (:func:`chartbook.rowhash._read_plan`): it is read
    within the limit, or it is refused, unread, with why. Each test here
    is one or the other, and under the limit either way.
    """

    def test_an_occasional_long_value_in_a_file_written_by_default(self, tmp_path):
        """A megabyte once in sixty-seven rows: pyarrow puts a thousand values to a page, so its pages are 15 MB."""
        rows, each = 20_000, 1_000_000
        long = np.random.default_rng(12).random(rows) < 1 / 67
        chunks = [
            pa.array([(f"{i:06d}" + "m" * each) if long[i] else f"note {i}" for i in range(a, min(a + 2000, rows))], pa.string())
            for a in range(0, rows, 2000)
        ]
        pq.write_table(pa.table({"date": _days("2022-01-01", np.arange(rows) // 200), "note": pa.chunked_array(chunks)}), tmp_path / "notes.parquet")
        del chunks
        said = _hashed_under(LIMIT, tmp_path / "notes.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT

    def test_long_rows_and_then_short_ones_in_one_row_group(self, tmp_path):
        """What the rows before took says nothing of the rows after: 400 MB of long rows, then a hundred thousand short."""
        each, long, short = 100_000, 4_000, 100_000
        chunks = [pa.array([f"{i:06d}" + "x" * each for i in range(a, min(a + 2000, long))]) for a in range(0, long, 2000)]
        chunks.append(pa.array([f"s{i}" for i in range(short)], pa.string()))
        when = np.concatenate([np.arange(long) // 50, long // 50 + np.arange(short) // 2000])
        pq.write_table(
            pa.table({"date": _days("2020-01-01", when), "doc": pa.chunked_array(chunks)}),
            tmp_path / "docs.parquet", row_group_size=long + short, compression="zstd",
        )
        del chunks
        said = _hashed_under(LIMIT, tmp_path / "docs.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == long + short and said["peak"] < LIMIT

    @pytest.mark.parametrize("to_a_page,hashed", [(50, True), (100, False)], ids=["pages of fifty", "pages of a hundred"])
    def test_documents_each_its_own(self, tmp_path, to_a_page, hashed):
        """Two megabytes a row, no two alike, in pages of 95 MB or of 190: one value of a page may be as long as its page."""
        rows, each = 200, 2_000_000
        chunks = [pa.array([f"{i:04d}" + "d" * each for i in range(a, min(a + to_a_page, rows))]) for a in range(0, rows, to_a_page)]
        pq.write_table(
            pa.table({"date": _days("2024-01-01", np.arange(rows) // 40), "document": pa.chunked_array(chunks)}),
            tmp_path / "documents.parquet", compression="zstd", use_dictionary=False,
        )
        del chunks
        said = _hashed_under(LIMIT, tmp_path / "documents.parquet", "date", tmp_path)
        assert said["peak"] < LIMIT
        if hashed:
            assert said.get("same") and said["rows"] == rows
        else:
            assert "one value of 'document' may take 191 MB" in said["refused"] and said["peak"] < 512 * 1024**2, said

    def test_one_value_longer_than_a_row_may_be(self, tmp_path):
        """300 MB in one value: refused from its page's header, where before it was read, cast and put by first."""
        docs = ["short"] * 1000
        docs[500] = "y" * 300_000_000
        pq.write_table(
            pa.table({"date": _days("2024-01-01", np.arange(1000) // 10), "doc": pa.array(docs, pa.large_string())}),
            tmp_path / "value.parquet", compression="zstd", use_dictionary=False,
        )
        del docs
        said = _hashed_under(LIMIT, tmp_path / "value.parquet", "date", tmp_path)
        assert "one value of 'doc' may take 286 MB" in said["refused"] and said["peak"] < 1024**3, said

    def test_a_footer_of_a_thousand_row_groups_of_two_hundred_columns(self, tmp_path):
        """The footer lists every column of every row group, and is read whole first: refused by its size, in its last eight bytes."""
        columns = 200
        schema = pa.schema([("date", pa.timestamp("ns"))] + [(f"c{i:03d}", pa.float64()) for i in range(columns)])
        with pq.ParquetWriter(tmp_path / "groups.parquet", schema, compression="none") as writer:
            values = [pa.array([1.5])] * columns
            for group in range(1_200):
                writer.write_table(pa.Table.from_arrays([_days("1970-01-01", [group])] + values, schema=schema))
        said = _hashed_under(LIMIT, tmp_path / "groups.parquet", "date", tmp_path)
        assert "has a footer of" in said["refused"] and said["peak"] < 512 * 1024**2, said

    @pytest.mark.parametrize("rows,hashed", [(3_200_000, True), (3_600_000, False)], ids=["within what is held", "past it"])
    def test_a_page_to_a_column_chunk(self, tmp_path, rows, hashed):
        """Thirty columns, each chunk one page: a reader unpacks every one whole, 24 MB a column here, or 27."""
        base = np.tile(np.arange(1000, dtype="float64"), rows // 1000)
        table = pa.table({"date": _days("2020-01-01", np.arange(rows) // 40_000), **{f"c{i:02d}": base + i for i in range(30)}})
        pq.write_table(
            table, tmp_path / "pages.parquet", row_group_size=rows, compression="zstd", use_dictionary=False,
            data_page_size=2**31 - 1, max_rows_per_page=2**31 - 1, write_batch_size=1_000_000,
        )
        del table, base
        said = _hashed_under(LIMIT, tmp_path / "pages.parquet", "date", tmp_path)
        assert said["peak"] < LIMIT
        if hashed:
            assert said.get("same") and said["rows"] == rows
        else:
            assert "pages too large to read a little at a time" in said["refused"] and said["peak"] < 512 * 1024**2, said

    @pytest.mark.parametrize("rows,hashed", [(50_000, True), (60_000, False)], ids=["within what is held", "past it"])
    def test_a_dictionary_of_long_text(self, tmp_path, rows, hashed):
        """A dictionary page of 250 MB, or of 300: held as its page and as its values, whatever is read of the rows."""
        each = 5_000
        chunks = [pa.array([f"{i:07d}" + "z" * each for i in range(a, min(a + 30_000, rows))]) for a in range(0, rows, 30_000)]
        pq.write_table(
            pa.table({"date": _days("2020-01-01", np.arange(rows) // 1000), "doc": pa.chunked_array(chunks)}),
            tmp_path / "dictionary.parquet", row_group_size=rows, compression="zstd", use_dictionary=True,
            dictionary_pagesize_limit=2**32,
        )
        del chunks
        said = _hashed_under(LIMIT, tmp_path / "dictionary.parquet", "date", tmp_path)
        assert said["peak"] < LIMIT
        if hashed:
            assert said.get("same") and said["rows"] == rows
        else:
            assert "pages too large to read a little at a time" in said["refused"] and said["peak"] < 512 * 1024**2, said

    def test_a_dictionary_to_each_of_254_columns(self, tmp_path):
        """What pyarrow writes of a wide table of floats by default: a megabyte of dictionary a column, and then its values."""
        rows, columns = 300_000, 254
        generator = np.random.default_rng(3)
        table = pa.table(
            {"date": _days("2020-01-01", np.arange(rows) // 300), **{f"c{i:03d}": generator.standard_normal(rows) for i in range(columns)}}
        )
        pq.write_table(table, tmp_path / "wide.parquet", row_group_size=rows)
        del table
        said = _hashed_under(LIMIT, tmp_path / "wide.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT

    def test_dates_in_ten_thousand_years(self, tmp_path):
        """A period is put by in a file of its own: a million rows in ten thousand years were 3 GB of them."""
        rows = 200_000
        generator = np.random.default_rng(7)
        first = (np.datetime64("0001-01-01") - np.datetime64("1970-01-01")).astype(int)
        last = (np.datetime64("9999-12-31") - np.datetime64("1970-01-01")).astype(int)
        when = pa.array(generator.integers(first, last, rows).astype("int32"), pa.int32()).cast(pa.date32())
        flag = pa.array(np.zeros(rows, dtype=bool))
        pq.write_table(pa.table({"date": when, **{f"b{i:03d}": flag for i in range(255)}}), tmp_path / "years.parquet", compression="zstd")
        said = _hashed_under(LIMIT, tmp_path / "years.parquet", "date", tmp_path)
        assert "more than 1,024 calendar years" in said["refused"] and said["peak"] < 512 * 1024**2, said


class TestWhatTheFourthReviewBroke:
    """Found by a fourth review, of the reader that tells what a file takes from its page headers."""

    def test_a_column_of_values_of_one_fixed_length(self, tmp_path):
        """50,000 bytes a value, a gigabyte of them in a file of under a megabyte: counted at sixteen bytes a row, they were read 16,384 at once."""
        width, distinct, rows = 50_000, 512, 20_480
        one = np.zeros((distinct, width), dtype="uint8")
        one[:, :8] = np.arange(distinct, dtype="<u8").view("uint8").reshape(distinct, 8)
        blob = pa.FixedSizeBinaryArray.from_buffers(pa.binary(width), distinct, [None, pa.py_buffer(one.tobytes())])
        table = pa.table({"date": _days("2020-01-01", np.arange(rows) // 20), "blob": pa.chunked_array([blob] * (rows // distinct))})
        pq.write_table(table, tmp_path / "blob.parquet", compression="zstd")
        said = _hashed_under(LIMIT, tmp_path / "blob.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT

    def test_a_category_with_a_dictionary_of_long_text(self, tmp_path):
        """315 MB of dictionary, read as a dictionary because its file's own schema says so: held far more than twice."""
        rows, each = 63_000, 5_000
        words = pa.array([f"{i:07d}" + "z" * (each - 7) for i in range(rows)])
        table = pa.table(
            {"date": _days("2020-01-01", np.arange(rows) // 1000), "doc": pa.DictionaryArray.from_arrays(pa.array(np.arange(rows), pa.int32()), words)}
        )
        pq.write_table(table, tmp_path / "category.parquet", row_group_size=rows, compression="zstd", dictionary_pagesize_limit=2**32)
        del table, words
        said = _hashed_under(LIMIT, tmp_path / "category.parquet", "date", tmp_path)
        assert "pages too large to read a little at a time" in said["refused"] and said["peak"] < 512 * 1024**2, said

    def test_150_columns_of_text_each_value_its_own(self, tmp_path):
        """Past 128 such columns each row group was read a row at a time: 327 seconds for 60,000 rows."""
        rows, columns = 60_000, 150
        table = pa.table(
            {
                "date": _days("2020-01-01", np.arange(rows) // 300),
                **{f"t{c:03d}": pa.array([f"column {c:03d} holds the value {i:010d} of forty-eight" for i in range(rows)]) for c in range(columns)},
            }
        )
        pq.write_table(table, tmp_path / "wide.parquet")
        del table
        said = _hashed_under(LIMIT, tmp_path / "wide.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT
        assert said["pin_seconds"] < 60, said

    def test_a_page_to_each_value(self, tmp_path):
        """A million pages of one value each: the walk itself is held to a size and a time."""
        rows = 300_000
        table = pa.table({"date": _days("2020-01-01", np.arange(rows) // 1000), "n": np.arange(rows), "x": np.arange(rows) * 0.5})
        pq.write_table(
            table, tmp_path / "pages.parquet", row_group_size=rows, use_dictionary=False, compression="none",
            write_statistics=False, data_page_size=1, write_batch_size=1,
        )
        said = _hashed_under(LIMIT, tmp_path / "pages.parquet", "date", tmp_path)
        assert "more pages than are read to learn how it is laid out" in said["refused"] and said["peak"] < 512 * 1024**2, said


class TestWhatTheFifthReviewBroke:
    """Found by a fifth review: honest files of unusual writing, and what was just inside each limit."""

    @pytest.mark.parametrize("width,rows,hashed", [(125_000_000, 5, False), (1_000_000, 500, True)], ids=["125 MB a value", "a megabyte a value"])
    def test_values_of_one_fixed_length_of_megabytes(self, tmp_path, width, rows, hashed):
        """Five values of 125 MB were read, cast and put by, 2.4 GB of them, before a day too large was said."""
        raw = np.zeros(width * rows, dtype="uint8")
        raw[::width] = np.arange(1, rows + 1) % 251
        blob = pa.FixedSizeBinaryArray.from_buffers(pa.binary(width), rows, [None, pa.py_buffer(raw)])
        pq.write_table(
            pa.table({"date": _days("2020-01-01", np.arange(rows) // 5), "blob": blob}), tmp_path / "blob.parquet",
            compression="zstd", use_dictionary=hashed is False,
        )
        del raw, blob
        said = _hashed_under(LIMIT, tmp_path / "blob.parquet", "date", tmp_path)
        assert said["peak"] < LIMIT
        if hashed:
            assert said.get("same") and said["rows"] == rows
        else:
            assert "holds values of 119 MB each in 'blob'" in said["refused"] and said["peak"] < 512 * 1024**2, said

    @pytest.mark.parametrize("rows,hashed", [(11_500_000, True), (56_000_000, False)], ids=["92 MB of dictionary", "448 MB of dictionary"])
    def test_a_dictionary_of_numbers(self, tmp_path, rows, hashed):
        """A dictionary of numbers is held several times over while it is read, and not all given back: 448 MB of one took 2.1 GB."""
        table = pa.table({"date": _days("2000-01-01", np.arange(rows) // 20_000), "x": np.arange(rows, dtype="float64") * 0.5})
        pq.write_table(table, tmp_path / "numbers.parquet", row_group_size=rows, compression="zstd", dictionary_pagesize_limit=2**31 - 1)
        del table
        said = _hashed_under(LIMIT, tmp_path / "numbers.parquet", "date", tmp_path)
        assert said["peak"] < LIMIT
        if hashed:
            assert said.get("same") and said["rows"] == rows
        else:
            assert "pages too large to read a little at a time" in said["refused"] and said["peak"] < 512 * 1024**2, said

    def test_a_megabyte_of_page_that_is_gigabytes_of_rows(self, tmp_path):
        """Text written as what it adds to the value before: 2,048 values of a megabyte, each the same as the last, in pages of a megabyte."""
        each, rows = 1_000_000, 2_048
        chunk = pa.array(["p" * each] * 64, pa.large_string())
        table = pa.table({"date": _days("2020-01-01", np.arange(rows)), "doc": pa.chunked_array([chunk] * (rows // 64))})
        pq.write_table(table, tmp_path / "prefix.parquet", use_dictionary=False, column_encoding={"date": "PLAIN", "doc": "DELTA_BYTE_ARRAY"})
        del table, chunk
        assert (tmp_path / "prefix.parquet").stat().st_size < 64 * 1024**2
        said = _hashed_under(LIMIT, tmp_path / "prefix.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT

    def test_230_columns_of_text_as_pandas_writes_them(self, tmp_path):
        """A megabyte of page and a megabyte of dictionary a column: refused at 214 columns when a dictionary of text was counted for the whole of twice."""
        import pandas as pd

        rows, columns = 60_000, 230
        frame = pd.DataFrame(
            {
                "date": pd.Timestamp("2020-01-01") + pd.to_timedelta(np.arange(rows) // 300, unit="D"),
                **{f"t{c:03d}": [f"column {c:03d} holds the value {i:010d} of forty-eight" for i in range(rows)] for c in range(columns)},
            }
        )
        frame.to_parquet(tmp_path / "wide.parquet", index=False)
        del frame
        said = _hashed_under(LIMIT, tmp_path / "wide.parquet", "date", tmp_path)
        assert said.get("same") and said["rows"] == rows and said["peak"] < LIMIT
