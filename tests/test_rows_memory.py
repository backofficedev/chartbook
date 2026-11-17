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
    rowhash.PERIOD_BYTES, rowhash.MOST_BYTES = period, 2 * period
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
    return json.loads(done.stdout.strip().splitlines()[-1])


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
        rows = 300_000
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
