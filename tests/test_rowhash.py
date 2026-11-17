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

    def test_a_column_named_like_a_pattern_is_a_column(self):
        """polars reads `^a$` as a pattern: taken by its name, such a column was passed over, and its values with it."""
        one = pl.DataFrame({"^a$": [1, 2], "b": [3, 4]})
        other = pl.DataFrame({"^a$": [9, 9], "b": [3, 4]})
        without = pl.DataFrame({"b": [3, 4]})
        assert len({hash_frame(one), hash_frame(other), hash_frame(without)}) == 3
        assert hash_frame(pl.DataFrame({"^a$": [1, 2]})) != hash_frame(pl.DataFrame())
        assert hash_frame(one) == _by_hand([{"^a$": 1, "b": 3}, {"^a$": 2, "b": 4}], {"^a$": "int", "b": "int"})
        # And one that is sorted on: a pattern for a name sorted on nothing
        assert hash_frame(one.reverse(), "^a$") == hash_frame(one, "^a$")
        for name in ("*", "^.*$", "a b", "", "é"):
            frame = pl.DataFrame({name: [2, 1], "b": [3, 4]})
            assert hash_frame(frame) == _by_hand([{name: 2, "b": 3}, {name: 1, "b": 4}], {name: "int", "b": "int"}), name

    def test_the_rows_are_sorted_on_every_column(self):
        """Down to the last: rows alike in all but their last column come in one order however they were written."""
        frame = pl.DataFrame({"a": [1, 1, 1, 1], "b": ["x", "x", "x", "x"], "c": [0.5, 0.25, None, 0.75], "z": [4, 3, 2, 1]})
        for seed in range(6):
            assert hash_frame(frame.sample(fraction=1.0, shuffle=True, seed=seed)) == hash_frame(frame)
        alike_but_last = pl.DataFrame({"a": [1, 1, 1], "b": ["x", "x", "x"], "z": [3, 1, 2]})
        assert hash_frame(alike_but_last.reverse()) == hash_frame(alike_but_last) == hash_frame(alike_but_last.sort("z"))

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


class TestWhatPandasWrites:
    """A limit on "whatever wrote them": pandas writes other values, and other values hash otherwise."""

    def test_a_nan_through_pandas_is_an_empty_value(self, tmp_path):
        frame = pl.DataFrame({"a": [1, 2, 3], "x": [0.5, float("nan"), 1.5]})
        frame.to_pandas().to_parquet(tmp_path / "pandas.parquet", index=False)
        back = pl.read_parquet(tmp_path / "pandas.parquet")
        assert back.get_column("x").null_count() == 1  # the file holds an empty value where the frame held NaN
        assert hash_frame(back) != hash_frame(frame)
        assert hash_frame(back) == hash_frame(frame.with_columns(pl.col("x").fill_nan(None)))

    def test_a_whole_number_with_an_empty_value_through_pandas_is_a_float(self, tmp_path):
        frame = pl.DataFrame({"n": [1, None, 3]})
        frame.to_pandas().to_parquet(tmp_path / "pandas.parquet", index=False)
        back = pl.read_parquet(tmp_path / "pandas.parquet")
        assert back.schema["n"] == pl.Float64 and hash_frame(back) != hash_frame(frame)


class TestWhatItDoesNotTake:

    @pytest.mark.parametrize(
        "column", [pl.Series("x", [[1, 2], [3]]), pl.Series("x", [{"a": 1}, {"a": 2}])], ids=["a list", "a struct"]
    )
    def test_a_column_of_lists_or_structs(self, column):
        with pytest.raises(NotHashed, match="column 'x' is .*, and a rows hash takes no such column yet"):
            hash_frame(pl.DataFrame([column]))
        # With no value in it, too: a column of lists is of no kind
        with pytest.raises(NotHashed):
            hash_frame(pl.DataFrame([column]).clear(2))

    def test_a_date_past_what_microseconds_hold(self):
        """polars panics on it, which is no Exception: said as any table whose rows are not hashed."""
        far = pl.DataFrame({"d": [106751992, 1]}, schema={"d": pl.Int32}).cast({"d": pl.Date})
        with pytest.raises(NotHashed, match="its columns cannot be put in one form"):
            hash_frame(far)
        with pytest.raises(NotHashed, match="its columns cannot be put in one form"):
            hash_frame(pl.DataFrame({"t": [9223372036854776, 1]}, schema={"t": pl.Datetime("ms")}))

    @pytest.mark.parametrize(
        "kind,past",
        [
            (pl.Date, 106751992),
            (pl.Date, -106751992),
            (pl.Datetime("ms"), 9223372036854776),
            (pl.Datetime("ms"), -9223372036854776),
            (pl.Datetime("ms", "America/Chicago"), 9223372036854776),
            (pl.Duration("ms"), 9223372036854776),
        ],
    )
    def test_a_time_past_what_microseconds_hold_is_refused_by_chartbook_itself(self, kind, past):
        """Whatever this polars does with it (one stops, one panics, one wraps it round): refused, and by name."""
        whole = pl.Int32 if kind == pl.Date else pl.Int64
        frame = pl.DataFrame({"when": [past, 1]}, schema={"when": whole}).cast({"when": kind})
        with pytest.raises(NotHashed, match="column 'when' has a time past what 64 bits of microseconds hold"):
            hash_frame(frame)

    @pytest.mark.parametrize(
        "kind,most,each",
        [(pl.Date, 106751991, 86_400_000_000), (pl.Datetime("ms"), 9223372036854775, 1000), (pl.Duration("ms"), 9223372036854775, 1000)],
    )
    def test_the_last_time_microseconds_hold_is_hashed(self, kind, most, each):
        whole = pl.Int32 if kind == pl.Date else pl.Int64
        for value in (most, -most):
            frame = pl.DataFrame({"when": [value, 1]}, schema={"when": whole}).cast({"when": kind})
            finer = pl.Datetime("us") if kind != pl.Duration("ms") else pl.Duration("us")
            same = pl.DataFrame({"when": [value * each, each]}, schema={"when": pl.Int64}).cast({"when": finer})
            assert hash_frame(frame) == hash_frame(same)

    def test_a_number_past_64_bits(self):
        if not hasattr(pl, "Int128"):
            pytest.skip("this polars has no 128-bit whole numbers")
        wide = pl.DataFrame({"n": [2**70, 1]}, schema={"n": pl.Int128})
        with pytest.raises(NotHashed):
            hash_frame(wide)
        fits = pl.DataFrame({"n": [2**40, 1]}, schema={"n": pl.Int128})
        assert hash_frame(fits) == hash_frame(fits.cast({"n": pl.Int64}))

    def test_a_frame_that_is_not_one(self):
        with pytest.raises(TypeError, match="hash_frame takes a polars DataFrame, and was given a LazyFrame"):
            hash_frame(pl.DataFrame({"a": [1]}).lazy())


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

    @pytest.mark.parametrize(
        "text",
        [
            "2026-13-01", "yesterday", "2026-10-30T16:00:00.25", "2026-10-30T", "2026-10-30T1:2:3", "2026-10-30T25:61:61",
            "2026-10-30T-1:00:00", "20261030", "2026-W44-5", "2026-10-30 16:00:00", "2026-10-30T16:00", " 2026-10-30",
            "٢٠٢٦-١٠-٣٠", "2026-10-30T16:00:00.1234567", "",
        ],
    )
    def test_one_that_is_none(self, text):
        with pytest.raises(ValueError, match="is not a timestamp a record writes"):
            rowhash.stamp_of(text)

    def test_a_year_no_record_can_write(self):
        with pytest.raises(NotHashed, match="outside the years 1 to 9999"):
            rowhash.stamp_text(2932897 * 86_400_000_000)


# --- The form, written a second time ---------------------------------------------


def _decimal_as_text(value: Decimal) -> str:
    """A decimal as the form writes it: plain digits, no zero after its last digit, no point with nothing after it, and no -0."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _by_hand(rows: list, kinds: dict, first: str = None) -> str:
    """The rows hash of a table given as rows of plain Python values, worked out from the specification alone.

    *kinds* says each column's kind by its type; *first* is the date
    column. A timestamp or a duration is a pair, its whole microseconds
    and the nanoseconds left over; a time of day is its nanoseconds; a
    decimal is a ``Decimal``; binary is bytes. None is an empty value.
    """
    names = sorted(kinds, key=lambda name: name.encode("utf-8"))

    def order(value, kind):
        if value is None:
            return (2,)
        if kind == "float" and math.isnan(value):
            return (1,)
        if kind == "text":
            return (0, value.encode("utf-8"))
        return (0, value)

    def key(row):
        by = ([first] if first in kinds else []) + [name for name in names if name != first]
        return [order(row[name], kinds[name]) for name in by]

    ordered = sorted(rows, key=key)
    digest = hashlib.sha256()
    digest.update(b"chartbook/rows/v1\n")
    digest.update(struct.pack("<QQ", len(ordered), len(names)))
    for name in names:
        kind = kinds[name]
        values = [row[name] for row in ordered]
        if all(value is None for value in values):
            kind = "null"  # no value in any row, and so in a table with no rows
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
        if kind in ("int", "time"):
            digest.update(b"".join(struct.pack("<q", value or 0) for value in values))
        elif kind == "uint64":
            digest.update(b"".join(struct.pack("<Q", value or 0) for value in values))
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
        elif kind in ("text", "decimal", "binary"):
            if kind == "decimal":
                values = [None if value is None else _decimal_as_text(value) for value in values]
            encoded = [b"" if value is None else value if kind == "binary" else value.encode("utf-8") for value in values]
            digest.update(b"".join(struct.pack("<Q", len(one)) for one in encoded) + b"".join(encoded))
        elif kind in ("timestamp", "duration"):
            digest.update(b"".join(struct.pack("<q", value[0] if value else 0) for value in values))
            if any(value and value[1] for value in values):
                digest.update(b"\x01" + b"".join(struct.pack("<q", value[1] if value else 0) for value in values))
            else:
                digest.update(b"\x00")
        else:
            raise AssertionError(kind)
    return "sha256:" + digest.hexdigest()


def _others() -> pl.DataFrame:
    """A table of the kinds :func:`_frame` has none of: bytes, lengths of time, times of day, an unsigned number past 63 bits, a decimal; ten rows, so that a bit a row runs into a second byte."""
    return pl.DataFrame(
        {
            "raw": [b"\x00\x01", None, b"", b"\xff", b"ab", b"a", b"b", None, b"\x00", b"z"],
            "held": [1_000_000_001, 1_000_000_000, None, -1, 5, 5, 86_400_000_000_000, 0, 1, 999],
            "at": [time(9, 30), time(16, 0), None, time(0, 0, 0, 1), time(23, 59, 59), time(9, 30), time(9, 30), time(12), time(1), time(2)],
            "big": [2**64 - 1, 1, None, 2**63, 0, 7, 7, 8, 9, 10],
            "price": [Decimal("1.50"), Decimal("-0.25"), None, Decimal("100.00"), Decimal("0.00"), Decimal("-0.00"), Decimal("0.05"), Decimal("12.30"), Decimal("7.00"), Decimal("-7.10")],
            "up": [True, False, None, True, True, False, False, True, False, True],
        },
        schema={"raw": pl.Binary, "held": pl.Duration("ns"), "at": pl.Time, "big": pl.UInt64, "price": pl.Decimal(12, 2), "up": pl.Boolean},
    )


def _others_by_hand() -> tuple:
    frame = _others()
    rows = []
    for raw, _, at, big, price, up in frame.rows():
        rows.append(
            {
                "raw": raw,
                # A length of time as polars hands it back has lost its nanoseconds: taken from the column itself
                "held": None,
                "at": None if at is None else ((at.hour * 60 + at.minute) * 60 + at.second) * 1_000_000_000 + at.microsecond * 1000,
                "big": big,
                "price": price,
                "up": up,
            }
        )
    for row, exact in zip(rows, frame.get_column("held").cast(pl.Int64).to_list()):
        row["held"] = None if exact is None else divmod(exact, 1000)
    return rows, {"raw": "binary", "held": "duration", "at": "time", "big": "uint64", "price": "decimal", "up": "bool"}


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
        assert hash_frame(_frame(), "ds") == _by_hand(rows, kinds, "ds")
        # Sorted on another column first, the rows are fed in another order
        assert hash_frame(_frame(), "ticker") == _by_hand(rows, kinds, "ticker") != _by_hand(rows, kinds, "ds")
        assert hash_frame(_frame()) == _by_hand(rows, kinds) == hash_frame(_frame(), "no such column")

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
            {"ds": (1_700_000_000_000_000, 1), "p": Decimal("1.50")},
            {"ds": (1_700_000_000_000_001, 0), "p": Decimal("-0.00")},
            {"ds": None, "p": Decimal("100.00")},
        ]
        assert hash_frame(frame, "ds") == _by_hand(rows, {"ds": "timestamp", "p": "decimal"}, "ds")
        assert [_decimal_as_text(row["p"]) for row in rows] == ["1.5", "0", "100"]

    def test_a_decimal_with_nothing_after_its_point_keeps_its_zeros(self):
        """`100` is `100`: only what follows a point is taken off."""
        whole = pl.DataFrame({"p": [Decimal("100"), Decimal("-20"), Decimal("0")]}, schema={"p": pl.Decimal(12, 0)})
        rows = [{"p": value} for value in whole.get_column("p").to_list()]
        assert hash_frame(whole) == _by_hand(rows, {"p": "decimal"})
        assert [_decimal_as_text(row["p"]) for row in rows] == ["100", "-20", "0"]

    def test_the_other_kinds(self):
        """Bytes, a length of time with nanoseconds, a time of day, an unsigned number past 63 bits, and more rows than a byte has bits."""
        rows, kinds = _others_by_hand()
        frame = _others()
        assert hash_frame(frame) == _by_hand(rows, kinds)
        assert hash_frame(frame.sample(fraction=1.0, shuffle=True, seed=4)) == hash_frame(frame)
        assert hash_frame(frame, "held") == _by_hand(rows, kinds, "held")

    def test_each_kind_is_fed_under_its_own_name(self):
        """A length of time is no timestamp and a time of day no whole number, though their bytes are the same."""
        ticks = [1_000_000, 2_000_000, None]
        as_kind = {
            "timestamp": pl.Datetime("us"), "duration": pl.Duration("us"), "int": pl.Int64, "time": pl.Time,
        }
        hashes = {kind: hash_frame(pl.DataFrame({"x": ticks}, schema={"x": kind_type})) for kind, kind_type in as_kind.items()}
        assert len(set(hashes.values())) == 4
        for kind in ("timestamp", "duration"):
            rows = [{"x": None if tick is None else (tick, 0)} for tick in ticks]
            assert hashes[kind] == _by_hand(rows, {"x": kind})
        for kind in ("int", "time"):
            assert hashes[kind] == _by_hand([{"x": tick} for tick in ticks], {"x": kind})

    def test_a_table_with_no_rows(self):
        """No row has a value, so every column is of no kind: only the names are told."""
        none = pl.DataFrame(schema={"a": pl.Int64, "s": pl.String})
        assert hash_frame(none) == _by_hand([], {"a": "int", "s": "text"}) == _by_hand([], {"a": "null", "s": "null"})

    def test_it_is_this_hash(self):
        """The form does not change by accident: a change to it takes a new name and a new prefix."""
        assert hash_frame(_frame(), "ds") == EXPECTED
        assert hash_frame(_others()) == EXPECTED_OF_THE_OTHERS


#: The rows hash of :func:`_frame`, and of :func:`_others`, as the form of ``chartbook/rows/v1`` gives it.
EXPECTED = "sha256:6d30842d6a56f35a1e7f90e21216896e27b0b437213ed08cb9693b813f0cde22"
EXPECTED_OF_THE_OTHERS = "sha256:25c2b5126867d5cb9f25c068052332600a4eb454c9270b6bba7c86d780046f5b"
