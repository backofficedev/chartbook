"""Tests for the rows hash: its form (``docs_src/design/index-schema.md``, "The rows hash").

A rows hash names a table's rows, and not its file's bytes. The same rows
give one hash whatever wrote them, in whatever order, in whatever widths;
any value that differs gives another. The form is fixed, so that the
machine that pins and the machine that checks agree: the last test here
writes the form out a second time, in plain Python, and the two must agree.
"""

import hashlib
import math
import struct
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import polars as pl
import pyarrow.parquet as pq
import pytest

from chartbook import rowhash
from chartbook.rowhash import NotHashed, hash_frame


def _frame() -> pl.DataFrame:
    """A small table with a column of every common kind, and an empty value in each."""
    return pl.DataFrame(
        {
            "ds": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 3), None],
            "permno": [10001, 10002, 10001, 10003],
            "ret": [0.01, -0.02, None, float("nan")],
            "ticker": ["AAPL", None, "MSFT", ""],
            "listed": [True, False, None, True],
        },
        schema={"ds": pl.Date, "permno": pl.Int32, "ret": pl.Float64, "ticker": pl.String, "listed": pl.Boolean},
    )


class TestTheSameRows:
    """What the hash does not see: the writer, the order, the widths."""

    def test_six_files_one_hash(self, tmp_path):
        frame = pl.DataFrame(
            {
                "date": pl.datetime_range(datetime(2020, 1, 1), datetime(2020, 12, 31), "1d", eager=True, time_unit="ns"),
            }
        ).with_columns(
            permno=pl.int_range(pl.len(), dtype=pl.Int64) % 7 + 10000,
            ret=(pl.int_range(pl.len()) * 0.001).sin(),
            ticker=pl.format("T{}", pl.int_range(pl.len()) % 5),
        )
        ways = {}
        frame.write_parquet(tmp_path / "polars.parquet")
        ways["polars"] = tmp_path / "polars.parquet"
        pq.write_table(frame.to_arrow(), tmp_path / "arrow.parquet", compression="snappy", row_group_size=50)
        ways["pyarrow, snappy, small row groups"] = tmp_path / "arrow.parquet"
        frame.to_pandas().to_parquet(tmp_path / "pandas.parquet", index=False)
        ways["pandas"] = tmp_path / "pandas.parquet"
        frame.sample(fraction=1.0, shuffle=True, seed=1).write_parquet(tmp_path / "shuffled.parquet")
        ways["the rows in another order"] = tmp_path / "shuffled.parquet"
        frame.with_columns(pl.col("date").cast(pl.Datetime("us"))).write_parquet(tmp_path / "micro.parquet")
        ways["dates in microseconds"] = tmp_path / "micro.parquet"
        frame.select(sorted(frame.columns, reverse=True)).write_parquet(tmp_path / "columns.parquet")
        ways["the columns in another order"] = tmp_path / "columns.parquet"

        files = {hashlib.sha256(path.read_bytes()).hexdigest() for path in ways.values()}
        rows = {name: hash_frame(pl.read_parquet(path), "date") for name, path in ways.items()}
        assert len(files) == 6
        assert len(set(rows.values())) == 1, rows

    def test_one_value_changed_in_its_ninth_decimal_place(self):
        frame = pl.DataFrame({"ds": [date(2024, 1, 2), date(2024, 1, 3)], "ret": [0.01, 0.02]})
        other = frame.with_columns(pl.when(pl.col("ds") == date(2024, 1, 3)).then(pl.col("ret") + 1e-9).otherwise(pl.col("ret")).alias("ret"))
        assert hash_frame(frame) != hash_frame(other)

    @pytest.mark.parametrize(
        "kind", [pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64]
    )
    def test_a_whole_number_is_one_kind_whatever_its_width(self, kind):
        wide = pl.DataFrame({"n": [1, 2, None, 100]}, schema={"n": pl.Int64})
        assert hash_frame(wide.cast({"n": kind})) == hash_frame(wide)

    def test_a_number_past_64_signed_bits_is_its_own_kind(self):
        big = pl.DataFrame({"n": [2**64 - 1, 1]}, schema={"n": pl.UInt64})
        signed = pl.DataFrame({"n": [-1, 1]}, schema={"n": pl.Int64})  # the same eight bytes
        assert hash_frame(big) != hash_frame(signed)

    def test_a_float_is_one_kind_whatever_its_width(self):
        narrow = pl.DataFrame({"x": [0.5, 1.25, None]}, schema={"x": pl.Float32})
        assert hash_frame(narrow) == hash_frame(narrow.cast({"x": pl.Float64}))

    def test_one_zero_and_one_nan(self):
        odd = np.array([struct.unpack("<d", struct.pack("<Q", 0xFFF8000000000001))[0], -0.0, 1.0])
        plain = np.array([float("nan"), 0.0, 1.0])
        assert hash_frame(pl.DataFrame({"x": odd})) == hash_frame(pl.DataFrame({"x": plain}))

    def test_a_negative_zero_does_not_move_a_row(self):
        """Sorted before it is put in one form, -0.0 would go before 0.0 and take its row with it."""
        one = pl.DataFrame({"a": [-0.0, 0.0], "b": ["y", "x"]})
        other = pl.DataFrame({"a": [0.0, -0.0], "b": ["y", "x"]})
        assert hash_frame(one) == hash_frame(other)

    def test_a_date_is_the_timestamp_of_its_midnight(self):
        days = pl.DataFrame({"ds": [date(2024, 1, 2), None, date(1961, 6, 14)]})
        for unit in ("ms", "us", "ns"):
            assert hash_frame(days.cast({"ds": pl.Datetime(unit)})) == hash_frame(days), unit

    def test_a_time_in_a_zone_is_its_instant(self):
        naive = pl.DataFrame({"t": [datetime(2024, 1, 2, 22, 0, 8), datetime(2024, 6, 1, 12, 0)]})
        utc = naive.with_columns(pl.col("t").dt.replace_time_zone("UTC"))
        chicago = utc.with_columns(pl.col("t").dt.convert_time_zone("America/Chicago"))
        assert hash_frame(utc) == hash_frame(naive) == hash_frame(chicago)

    def test_a_category_is_its_text(self):
        text = pl.DataFrame({"s": ["b", "a", None, "b"]})
        assert hash_frame(text.cast({"s": pl.Categorical})) == hash_frame(text)
        assert hash_frame(text.cast({"s": pl.Enum(["b", "a"])})) == hash_frame(text)

    def test_a_decimal_is_its_value_whatever_its_scale(self):
        two = pl.DataFrame({"p": [Decimal("1.50"), Decimal("-0.25"), None, Decimal("100.00")]}, schema={"p": pl.Decimal(12, 2)})
        four = two.cast({"p": pl.Decimal(18, 4)})
        assert hash_frame(two) == hash_frame(four)
        assert hash_frame(two) != hash_frame(two.cast({"p": pl.Float64}))  # a decimal is not a float

    def test_a_column_with_no_value_has_no_kind(self):
        """Whatever type its writer gave it: pandas writes one as null, polars as the type it was."""
        shapes = [
            pl.DataFrame({"a": [1, 2], "x": [None, None]}, schema={"a": pl.Int64, "x": kind})
            for kind in (pl.Null, pl.Float64, pl.String, pl.Int32, pl.Date)
        ]
        assert len({hash_frame(shape) for shape in shapes}) == 1

    def test_the_order_of_rows_and_columns(self):
        frame = _frame()
        assert hash_frame(frame.reverse()) == hash_frame(frame)
        assert hash_frame(frame.select(sorted(frame.columns))) == hash_frame(frame)
        assert hash_frame(frame.reverse(), "ds") == hash_frame(frame, "ds")

    def test_the_date_column_is_part_of_the_form(self):
        """The rows are sorted on it first, so a table hashed with another date column is hashed otherwise."""
        frame = _frame()
        assert hash_frame(frame, "ds") != hash_frame(frame, "ticker")
        assert hash_frame(frame, "no such column") == hash_frame(frame)

    def test_two_rows_alike_are_two_rows(self):
        once = pl.DataFrame({"a": [1, 2]})
        assert hash_frame(pl.concat([once, once])) != hash_frame(once)


class TestEveryValueIsSeen:

    def test_empty_is_not_zero_or_no_text_or_nan(self):
        assert hash_frame(pl.DataFrame({"x": [None, 1.0]})) != hash_frame(pl.DataFrame({"x": [0.0, 1.0]}))
        assert hash_frame(pl.DataFrame({"x": [None, 1.0]})) != hash_frame(pl.DataFrame({"x": [float("nan"), 1.0]}))
        assert hash_frame(pl.DataFrame({"s": [None, "a"]})) != hash_frame(pl.DataFrame({"s": ["", "a"]}))
        assert hash_frame(pl.DataFrame({"b": [None, True]})) != hash_frame(pl.DataFrame({"b": [False, True]}))

    def test_where_one_text_ends_and_the_next_begins(self):
        assert hash_frame(pl.DataFrame({"s": ["ab", "c"]})) != hash_frame(pl.DataFrame({"s": ["a", "bc"]}))

    def test_which_column_a_value_is_in(self):
        assert hash_frame(pl.DataFrame({"a": [1], "b": [2]})) != hash_frame(pl.DataFrame({"a": [2], "b": [1]}))
        assert hash_frame(pl.DataFrame({"a": [1]})) != hash_frame(pl.DataFrame({"b": [1]}))

    def test_a_whole_number_is_not_a_float(self):
        assert hash_frame(pl.DataFrame({"x": [1, 2]})) != hash_frame(pl.DataFrame({"x": [1.0, 2.0]}))

    def test_what_is_finer_than_a_microsecond(self):
        fine = pl.DataFrame({"t": [1_700_000_000_000_000_001, 1_700_000_000_000_001_000]}, schema={"t": pl.Datetime("ns")})
        coarse = fine.cast({"t": pl.Datetime("us")})  # the first loses its last nanosecond
        assert hash_frame(fine) != hash_frame(coarse)
        whole = pl.DataFrame({"t": [1_700_000_000_000_000_000, 1_700_000_000_000_001_000]}, schema={"t": pl.Datetime("ns")})
        assert hash_frame(whole) == hash_frame(whole.cast({"t": pl.Datetime("us")}))

    def test_a_duration_and_a_time_of_day(self):
        frame = pl.DataFrame({"d": [timedelta(seconds=1), None], "t": [time(9, 30), time(16, 0)]})
        assert hash_frame(frame) == hash_frame(frame.cast({"d": pl.Duration("ns")}))
        assert hash_frame(frame) != hash_frame(frame.with_columns(pl.lit(time(16, 0, 1)).alias("t")))

    def test_binary(self):
        assert hash_frame(pl.DataFrame({"b": [b"\x00\x01", None]})) != hash_frame(pl.DataFrame({"b": [b"\x00", b"\x01"]}))

    def test_a_table_with_no_rows_still_says_its_columns(self):
        none = pl.DataFrame(schema={"a": pl.Int64})
        assert hash_frame(none) != hash_frame(pl.DataFrame(schema={"b": pl.Int64}))
        assert hash_frame(none) == hash_frame(pl.DataFrame(schema={"a": pl.String}))  # no value, no kind to tell


class TestWhatItDoesNotTake:

    @pytest.mark.parametrize(
        "column", [pl.Series("x", [[1, 2], [3]]), pl.Series("x", [{"a": 1}, {"a": 2}])], ids=["a list", "a struct"]
    )
    def test_a_column_of_lists_or_structs(self, column):
        with pytest.raises(NotHashed, match="column 'x' is .*, and a rows hash takes no such column yet"):
            hash_frame(pl.DataFrame([column]))


class TestTimestampsAsARecordWritesThem:

    @pytest.mark.parametrize(
        "micro,left,text",
        [
            (0, 0, "1970-01-01"),
            (-270_000_000_000_000, 0, "1961-06-12"),
            (1_793_318_400_000_000, 0, "2026-10-30"),
            (1_793_376_000_000_000, 0, "2026-10-30T16:00:00"),
            (1_793_376_000_250_000, 0, "2026-10-30T16:00:00.250000"),
            (1_793_376_000_250_000, 1, "2026-10-30T16:00:00.250000001"),
            (-1, 0, "1969-12-31T23:59:59.999999"),
        ],
    )
    def test_there_and_back(self, micro, left, text):
        assert rowhash.stamp_text(micro, left) == text
        assert rowhash.stamp_of(text) == (micro, left)

    def test_one_that_is_none(self):
        for text in ("2026-13-01", "yesterday", "2026-10-30T16:00:00.25"):
            with pytest.raises(ValueError):
                rowhash.stamp_of(text)


# --- The form, written a second time ---------------------------------------------


def _by_hand(rows: list, kinds: dict) -> str:
    """The rows hash of a table given as rows of plain Python values, worked out from the specification alone.

    *kinds* says each column's kind. A timestamp is a pair, its whole
    microseconds from 1970 and the nanoseconds left over; a decimal is its
    text. None is an empty value.
    """
    names = sorted(kinds, key=lambda name: name.encode("utf-8"))

    def order(value, kind):
        if value is None:
            return (2,)
        if kind == "float" and math.isnan(value):
            return (1,)
        if kind == "text":
            return (0, value.encode("utf-8"))
        if kind == "decimal":
            return (0, Decimal(value))
        return (0, value)

    def key(row, first):
        return [order(row[first], kinds[first])] + [order(row[name], kinds[name]) for name in names if name != first]

    first = "ds" if "ds" in kinds else names[0]
    ordered = sorted(rows, key=lambda row: key(row, first))
    digest = hashlib.sha256()
    digest.update(b"chartbook/rows/v1\n")
    digest.update(struct.pack("<QQ", len(ordered), len(names)))
    for name in names:
        kind = kinds[name]
        values = [row[name] for row in ordered]
        if values and all(value is None for value in values):
            kind = "null"
        raw = name.encode("utf-8")
        digest.update(struct.pack("<Q", len(raw)) + raw + struct.pack("<B", len(kind)) + kind.encode("ascii"))
        empty = [value is None for value in values]
        if any(empty):
            bits = bytearray((len(values) + 7) // 8)
            for i, is_empty in enumerate(empty):
                if is_empty:
                    bits[i // 8] |= 0x80 >> (i % 8)
            digest.update(b"\x01" + bytes(bits))
        else:
            digest.update(b"\x00")
        if kind == "null":
            continue
        if kind == "int":
            digest.update(b"".join(struct.pack("<q", value or 0) for value in values))
        elif kind == "float":
            for value in values:
                if value is None:
                    value = 0.0
                digest.update(struct.pack("<Q", 0x7FF8000000000000) if math.isnan(value) else struct.pack("<d", value + 0.0))
        elif kind == "bool":
            bits = bytearray((len(values) + 7) // 8)
            for i, value in enumerate(values):
                if value:
                    bits[i // 8] |= 0x80 >> (i % 8)
            digest.update(bytes(bits))
        elif kind in ("text", "decimal"):
            encoded = [(value or "").encode("utf-8") for value in values]
            digest.update(b"".join(struct.pack("<Q", len(one)) for one in encoded) + b"".join(encoded))
        elif kind == "timestamp":
            digest.update(b"".join(struct.pack("<q", value[0] if value else 0) for value in values))
            if any(value and value[1] for value in values):
                digest.update(b"\x01" + b"".join(struct.pack("<q", value[1] if value else 0) for value in values))
            else:
                digest.update(b"\x00")
        else:
            raise AssertionError(kind)
    return "sha256:" + digest.hexdigest()


class TestTheFormWrittenTwice:
    """The module and a plain reading of the specification give one hash."""

    def test_a_table_of_every_common_kind(self):
        day = 86_400_000_000
        rows = [
            {"ds": (19724 * day, 0), "permno": 10001, "ret": 0.01, "ticker": "AAPL", "listed": True},
            {"ds": (19725 * day, 0), "permno": 10002, "ret": -0.02, "ticker": None, "listed": False},
            {"ds": (19725 * day, 0), "permno": 10001, "ret": None, "ticker": "MSFT", "listed": None},
            {"ds": None, "permno": 10003, "ret": float("nan"), "ticker": "", "listed": True},
        ]
        kinds = {"ds": "timestamp", "permno": "int", "ret": "float", "ticker": "text", "listed": "bool"}
        assert hash_frame(_frame(), "ds") == _by_hand(rows, kinds)

    def test_text_is_ordered_by_its_bytes_and_names_too(self):
        frame = pl.DataFrame({"é": ["b", "é", "a", "Z", "z"], "z": [1, 2, 3, 4, 5], "Z": [0.5, -0.0, 0.0, None, 2.0]})
        rows = [dict(zip(frame.columns, row)) for row in frame.rows()]
        assert hash_frame(frame) == _by_hand(rows, {"é": "text", "z": "int", "Z": "float"})

    def test_nanoseconds_and_decimals(self):
        frame = pl.DataFrame(
            {
                "ds": [1_700_000_000_000_000_001, 1_700_000_000_000_001_000, None],
                "p": [Decimal("1.50"), Decimal("-0.00"), Decimal("100.00")],
            },
            schema={"ds": pl.Datetime("ns"), "p": pl.Decimal(12, 2)},
        )
        rows = [
            {"ds": (1_700_000_000_000_000, 1), "p": "1.5"},
            {"ds": (1_700_000_000_000_001, 0), "p": "0"},
            {"ds": None, "p": "100"},
        ]
        assert hash_frame(frame, "ds") == _by_hand(rows, {"ds": "timestamp", "p": "decimal"})

    def test_it_is_this_hash(self):
        """The form does not change by accident: a change to it takes a new name and a new prefix."""
        assert hash_frame(_frame(), "ds") == EXPECTED


#: The rows hash of :func:`_frame`, as the form of ``chartbook/rows/v1`` gives it.
EXPECTED = "sha256:6d30842d6a56f35a1e7f90e21216896e27b0b437213ed08cb9693b813f0cde22"
