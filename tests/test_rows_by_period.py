"""Tests for a table's rows hashed by period (``docs_src/design/pins-and-rebuilds.md``, step 4).

A table with a date column is hashed a period at a time: a calendar year,
or a month or a day of one where a year's rows are too many to hold. The
record says each period by the first and the last timestamp seen in it.
Whoever checks hashes their own rows in the record's periods, leaving out
what is after its last timestamp.

The files are read a few thousand rows at a time, so the first thing
tested is that this gives what reading the whole table does, for every
shape of table ChartBook's reader takes.
"""

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from chartbook import rowhash
from chartbook.rowhash import ALL, NO_DATE, NotHashed, Table, hash_frame, hash_in, hash_rows, periods_of, stamp_text


def _table(days: int = 800, per_day: int = 3, start: date = date(2022, 11, 1)) -> pl.DataFrame:
    """Rows on consecutive days, a few each, across three calendar years."""
    when = [start + timedelta(days=i) for i in range(days) for _ in range(per_day)]
    return pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("S{}", pl.int_range(pl.len()) % per_day),
        y=(pl.int_range(pl.len()) * 0.37).sin(),
        n=pl.int_range(pl.len(), dtype=pl.Int32),
    )


def _whole(table: Table, date_col: str) -> dict:
    """A table's periods hashed from the whole table in memory, as the reader gives it: what reading it a little at a time must agree with."""
    frame = table.scan().collect()
    dates = frame.get_column(date_col)
    if dates.dtype == pl.String:
        dates = dates.str.to_datetime(strict=False)
    year = dates.dt.year()
    found = {}
    for value in sorted(set(year.drop_nulls().to_list())):
        part = frame.filter(year == value)
        stamps = dates.filter(year == value)
        first, last = stamps.min(), stamps.max()
        key = "/".join(
            stamp_text(*divmod(int(pl.Series([moment]).cast(pl.Datetime("ns")).cast(pl.Int64)[0]), 1000))
            for moment in (first, last)
        )
        found[key] = hash_frame(part, date_col)
    if dates.null_count():
        found[NO_DATE] = hash_frame(frame.filter(dates.is_null()), date_col)
    return found


#: What a row of :func:`_table` counts for: three values at eight bytes, and its ``unique_id``, of text, at sixteen and its two bytes.
A_ROW = 3 * 8 + 16 + 2


class TestChoosingThePeriods:
    """Whole years; a year too large as its months; such a month as its days. What rows count for is counted from the rows."""

    def _record(self, tmp_path, frame, period=None, most=None, monkeypatch=None, name="t.parquet"):
        frame.write_parquet(tmp_path / name)
        if period is not None:
            monkeypatch.setattr(rowhash, "PERIOD_BYTES", period)
            monkeypatch.setattr(rowhash, "MOST_BYTES", most if most is not None else 2 * period)
        return hash_rows(Table(tmp_path / name), "ds")

    def test_whole_years(self, tmp_path):
        assert list(self._record(tmp_path, _table()).rows) == [
            "2022-11-01/2022-12-31", "2023-01-01/2023-12-31", "2024-01-01/2024-12-31", "2025-01-01/2025-01-08",
        ]

    def test_a_year_too_large_is_its_months(self, tmp_path, monkeypatch):
        frame = _table(days=365, per_day=10, start=date(2023, 1, 1))
        record = self._record(tmp_path, frame, 40 * 10 * A_ROW, 10**9, monkeypatch)  # forty days' worth
        assert len(record.rows) == 12 and list(record.rows)[:2] == ["2023-01-01/2023-01-31", "2023-02-01/2023-02-28"]

    def test_a_month_too_large_is_its_days(self, tmp_path, monkeypatch):
        frame = pl.concat([_table(days=59, per_day=10, start=date(2023, 1, 1)), _table(days=31, per_day=1000, start=date(2023, 3, 1))])
        record = self._record(tmp_path, frame, 40 * 10 * A_ROW, 10**9, monkeypatch)
        said = list(record.rows)
        assert said[:2] == ["2023-01-01/2023-01-31", "2023-02-01/2023-02-28"]
        assert said[2:] == [f"2023-03-{day:02d}/2023-03-{day:02d}" for day in range(1, 32)]
        # Each the hash of its own rows, however it was come by
        assert record.rows["2023-03-07/2023-03-07"] == hash_frame(frame.filter(pl.col("ds") == date(2023, 3, 7)), "ds")
        assert record.rows["2023-02-01/2023-02-28"] == hash_frame(frame.filter(pl.col("ds").dt.month() == 2), "ds")

    def test_the_size_is_just_the_size(self, tmp_path, monkeypatch):
        """A year of exactly the size is whole, and one row more is its months."""
        frame = _table(days=365, per_day=2, start=date(2023, 1, 1))
        exactly = 365 * 2 * A_ROW
        assert len(self._record(tmp_path, frame, exactly, 10**9, monkeypatch).rows) == 1
        assert len(self._record(tmp_path, frame, exactly - 1, 10**9, monkeypatch).rows) == 12

    def test_only_the_days_that_have_rows(self, tmp_path):
        """A period is written by what was seen: no date that has not happened."""
        frame = pl.concat([_table(days=1, start=date(2023, 6, 14)), _table(days=1, start=date(2023, 12, 29))])
        assert list(self._record(tmp_path, frame).rows) == ["2023-06-14/2023-12-29"]

    def test_a_day_too_large_to_hold_is_refused(self, tmp_path, monkeypatch):
        frame = _table(days=2, per_day=1000, start=date(2023, 3, 1))
        with pytest.raises(NotHashed, match="its rows of 2023-03-01 alone, 1,000 of them, count for"):
            self._record(tmp_path, frame, 1000, 2000, monkeypatch)

    def test_a_day_within_the_most_is_one_period(self, tmp_path, monkeypatch):
        """A day cannot be split, so it may be twice a period."""
        frame = _table(days=2, per_day=100, start=date(2023, 3, 1))  # ids of two bytes and of three
        record = self._record(tmp_path, frame, 60 * A_ROW, 100 * (A_ROW + 1), monkeypatch)
        assert list(record.rows) == ["2023-03-01/2023-03-01", "2023-03-02/2023-03-02"]

    def test_the_size_of_a_period_is_fixed_here(self):
        """Set for a machine with 8 GB, and no setting: whoever checks must hold what whoever pinned chose."""
        assert rowhash.PERIOD_BYTES == 128 * 1024 * 1024
        # One size for every piece: a day, the rows with no date and a table with no dates are sorted whole, as a year is
        assert rowhash.MOST_BYTES == rowhash.PERIOD_BYTES


class TestWhatRowsCountFor:
    """Eight bytes a value, and sixteen and its own bytes for one of text: from the rows alone, so the same rows give the same periods."""

    def _batch(self, frame: pl.DataFrame):
        return frame.to_arrow(compat_level=pl.CompatLevel.oldest()).to_batches()[0]

    def test_eight_bytes_a_value_and_sixteen_and_its_bytes_for_text(self):
        frame = pl.DataFrame({"n": [1, 2, 3], "x": [0.5, None, 1.5], "t": ["ab", None, "héllo"], "b": [b"12", b"", None]})
        # A number eight, text and binary sixteen and their bytes, and an empty value eight whatever its column
        assert rowhash.row_bytes(self._batch(frame)).tolist() == [8 + 8 + 18 + 18, 8 + 8 + 8 + 16, 8 + 8 + 22 + 8]

    def test_a_decimal_is_sixteen(self):
        from decimal import Decimal

        frame = pl.DataFrame({"d": [Decimal("1.50"), None]}, schema={"d": pl.Decimal(20, 2)})
        assert rowhash.row_bytes(self._batch(frame)).tolist() == [16, 8]

    def test_a_column_with_no_value_in_it_counts_the_same_whatever_type_its_writer_gave_it(self):
        """pandas writes a column of nothing as a column of no type, and polars as text: the same rows, and the same size."""
        sizes = set()
        for kind in (pl.Null, pl.String, pl.Float64, pl.Decimal(10, 2), pl.Binary):
            frame = pl.DataFrame({"n": [1, 2], "empty": [None, None]}, schema={"n": pl.Int64, "empty": kind})
            sizes.add(tuple(rowhash.row_bytes(self._batch(frame)).tolist()))
        assert sizes == {(16, 16)}

    def test_whatever_type_a_file_held_them_in(self):
        wide = pl.DataFrame({"d": [datetime(2024, 1, 2)], "n": [7], "f": [1.5], "c": ["us"], "k": [True]})
        narrow = wide.with_columns(
            pl.col("d").cast(pl.Date), pl.col("n").cast(pl.Int8), pl.col("f").cast(pl.Float32), pl.col("c").cast(pl.Categorical)
        )
        target = wide.with_columns(pl.col("d").cast(pl.Date)).to_arrow(compat_level=pl.CompatLevel.oldest()).schema
        assert rowhash.row_bytes(self._batch(wide)).tolist() == [4 * 8 + 16 + 2]
        # As a table's batches come: a category as its text
        assert rowhash.row_bytes(self._batch(narrow.with_columns(pl.col("c").cast(pl.String)))).tolist() == [4 * 8 + 16 + 2]
        assert target.names == wide.columns

    def _same_rows(self, folder: Path) -> dict:
        """One table three ways: as polars writes it; as pandas does, with wider types; and with its rows in another order, in small row groups."""
        frame = _table(days=730, per_day=3, start=date(2023, 1, 1)).with_columns(
            # Longer text in the second year, so a few rows say little of what a row takes
            note=pl.when(pl.col("ds").dt.year() == 2024).then(pl.lit("x" * 40)).otherwise(pl.lit("y"))
        )
        frame.write_parquet(folder / "polars.parquet")
        frame.to_pandas().to_parquet(folder / "pandas.parquet", index=False)
        pq.write_table(frame.sample(fraction=1.0, shuffle=True, seed=11).to_arrow(), folder / "shuffled.parquet", row_group_size=53)
        return {name: Table(folder / f"{name}.parquet") for name in ("polars", "pandas", "shuffled")}

    def test_the_same_rows_give_the_same_periods_at_any_size(self, tmp_path, monkeypatch):
        """Near a threshold too: the size is counted, and not reckoned from a few rows of a file."""
        tables = self._same_rows(tmp_path)
        assert tables["polars"].schema()["ds"] == pl.Date and tables["pandas"].schema()["ds"] != pl.Date
        a_year = 365 * 3 * (3 * 8 + 16 + 2 + 16 + 1)  # 2023: three numbers, a two-byte id, a one-byte note
        for period in (10**9, a_year, a_year - 1, 40_000, 9_000, 600):
            monkeypatch.setattr(rowhash, "PERIOD_BYTES", period)
            monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
            records = {name: hash_rows(table, "ds").fields() for name, table in tables.items()}
            assert records["polars"] == records["pandas"] == records["shuffled"], period
        # 2023 whole at exactly its size, and 2024, of longer text, by month
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", a_year)
        said = list(hash_rows(tables["shuffled"], "ds").rows)
        assert said[0] == "2023-01-01/2023-12-31" and said[1] == "2024-01-01/2024-01-31" and len(said) == 13

    def test_a_refusal_is_the_same_whatever_the_order(self, tmp_path, monkeypatch):
        tables = self._same_rows(tmp_path)
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 100)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 200)
        said = set()
        for table in tables.values():
            with pytest.raises(NotHashed) as refused:
                hash_rows(table, "ds")
            said.add(str(refused.value))
        assert len(said) == 1 and "its rows of 2024-01-01 alone, 3 of them, count for" in said.pop()

    def test_put_by_month_from_the_first_is_the_same_record(self, tmp_path, monkeypatch):
        """A large table's rows are put by month at once, to be written once: what is hashed is the same."""
        tables = self._same_rows(tmp_path)
        for period in (10**9, 40_000, 600):
            monkeypatch.setattr(rowhash, "PERIOD_BYTES", period)
            monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
            monkeypatch.setattr(rowhash, "_BY_MONTH_FROM", 10**12)
            by_year = hash_rows(tables["polars"], "ds").fields()
            monkeypatch.setattr(rowhash, "_BY_MONTH_FROM", 0)
            assert hash_rows(tables["shuffled"], "ds").fields() == by_year, period

    def test_a_moved_pin_keeps_its_lines_when_the_new_rows_are_longer(self, tmp_path, monkeypatch):
        """What the rows after a pin take says nothing of the periods before it."""
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 40_000)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        frame = _table(days=500, start=date(2023, 1, 1)).with_columns(note=pl.lit("y"))
        frame.write_parquet(tmp_path / "pinned.parquet")
        pinned = hash_rows(Table(tmp_path / "pinned.parquet"), "ds")
        more = _table(days=300, start=date(2024, 5, 15)).with_columns(note=pl.lit("x" * 500))
        pl.concat([frame, more]).write_parquet(tmp_path / "moved.parquet")
        moved = hash_rows(Table(tmp_path / "moved.parquet"), "ds")
        kept = [key for key in pinned.rows if moved.rows.get(key) == pinned.rows[key]]
        # Every line of 2023; 2024 was one line, and is its months now that it has grown
        assert kept == [key for key in pinned.rows if key.startswith("2023")] and len(kept) == 12
        assert hash_in(Table(tmp_path / "moved.parquet"), "ds", pinned.rows, pinned.as_of).same


class TestARecordOfRows:

    def test_a_period_is_the_first_and_last_timestamp_seen_in_it(self, tmp_path):
        _table().write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert list(record.rows) == [
            "2022-11-01/2022-12-31", "2023-01-01/2023-12-31", "2024-01-01/2024-12-31", "2025-01-01/2025-01-08",
        ]
        assert record.as_of == "2025-01-08" and record.row_count == 2400

    def test_the_last_date_is_the_tables_own(self, tmp_path):
        """Never the clock's: a table pinned on Wednesday may end on Monday."""
        _table(days=10, start=date(2026, 10, 19)).write_parquet(tmp_path / "t.parquet")
        assert hash_rows(Table(tmp_path / "t.parquet"), "ds").as_of == "2026-10-28"

    def test_times_within_a_day(self, tmp_path):
        frame = pl.DataFrame(
            {"t": [datetime(2024, 3, 1, 9, 30), datetime(2024, 3, 1, 16, 0, 0, 250000), datetime(2024, 12, 31, 23, 59, 59)], "x": [1, 2, 3]}
        )
        frame.write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "t")
        assert list(record.rows) == ["2024-03-01T09:30:00/2024-12-31T23:59:59"] and record.as_of == "2024-12-31T23:59:59"

    def test_rows_with_no_date_are_a_period_of_their_own(self, tmp_path):
        frame = pl.concat([_table(days=5), pl.DataFrame({"ds": [None, None], "unique_id": ["a", "b"], "y": [1.0, 2.0], "n": [1, 2]}, schema=_table(1).schema)])
        frame.write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert list(record.rows) == ["2022-11-01/2022-11-05", NO_DATE] and record.as_of == "2022-11-05"
        assert record.rows[NO_DATE] == hash_frame(frame.filter(pl.col("ds").is_null()), "ds")

    def test_a_table_with_no_date_column_has_one_hash(self, tmp_path):
        frame = _table(days=5)
        frame.write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), None)
        assert record.rows == {ALL: hash_frame(frame)} and record.as_of is None and record.row_count == 15
        # And one whose entry names a date column it does not have
        assert hash_rows(Table(tmp_path / "t.parquet"), "date").rows == record.rows

    def test_a_table_with_no_rows(self, tmp_path):
        _table(days=1).clear().write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert record.rows == {} and record.as_of is None and record.row_count == 0
        assert record.fields() == {"date_col": "ds", "rows": {}, "row_count": 0}

    def test_a_date_column_that_is_text(self, tmp_path):
        """A CSV's: a date where it is written as one, in ISO 8601; a row with no date where it is not."""
        (tmp_path / "t.csv").write_text("ds,y\n2024-01-02,1.5\n2024-01-03,2.5\nnot a date,3.5\n2025-06-30,4.5\n", encoding="utf-8", newline="\n")
        table = Table(tmp_path / "t.csv", read_options={"schema_overrides": {"ds": "String"}})
        assert table.schema()["ds"] == pl.String
        record = hash_rows(table, "ds")
        assert list(record.rows) == ["2024-01-02/2024-01-03", "2025-06-30/2025-06-30", NO_DATE] and record.as_of == "2025-06-30"

    def test_text_is_a_date_where_it_is_written_as_one(self):
        """ISO 8601, with a time or none, with an offset or none: by fixed forms, so each value is read alike in every batch."""
        written = {
            "2024-01-02": datetime(2024, 1, 2),
            "2024-01-02T16:00:00": datetime(2024, 1, 2, 16),
            "2024-01-02 16:00:00.250": datetime(2024, 1, 2, 16, 0, 0, 250000),
            "2024-01-02T16:00": datetime(2024, 1, 2, 16),
            "2024-01-02T16:00:00+01:00": datetime(2024, 1, 2, 15),
            "2024-01-02T16:00:00Z": datetime(2024, 1, 2, 16),
            "01/02/2024": None,
            "Jan 2, 2024": None,
            "2024-13-45": None,
            "": None,
            # Nothing a parser might take on one machine and not on the next
            " 2024-01-02": None,
            "2024-01-02 ": None,
            "2024-1-2": None,
            "2024-01-02T16:00:00.1234567": None,
            "20240102": None,
        }
        read = rowhash._dates_in_text(pl.Series("ds", list(written)))
        assert read.dtype == pl.Datetime("us") and read.to_list() == list(written.values())
        # One at a time, as in one batch: nothing is guessed from a column's first values
        for text, moment in written.items():
            assert rowhash._dates_in_text(pl.Series("ds", [text])).to_list() == [moment], text

    def test_a_date_column_that_holds_no_dates(self, tmp_path):
        """An entry that names a column of numbers as its dates: the table is hashed as one with no date column."""
        frame = _table(days=5)
        frame.write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "n")
        assert record.rows == {ALL: hash_frame(frame)} and record.date_col is None and record.as_of is None

    def test_the_fields_a_record_holds(self, tmp_path):
        _table(days=5).write_parquet(tmp_path / "t.parquet")
        fields = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")
        assert list(fields) == ["date_col", "as_of", "rows", "row_count"]
        assert (fields["date_col"], fields["as_of"], fields["row_count"]) == ("ds", "2022-11-05", 15)
        assert list(rowhash.fields_of(Table(tmp_path / "t.parquet"), None)) == ["rows", "row_count"]

    def test_the_fields_of_a_table_that_is_not_hashed_or_not_read(self, tmp_path):
        pl.DataFrame({"ds": [date(2024, 1, 2)], "v": [[1.0, 2.0]]}).write_parquet(tmp_path / "lists.parquet")
        fields = rowhash.fields_of(Table(tmp_path / "lists.parquet"), "ds")
        # With the column its rows would be dated by: a snapshot of the same bytes under another is looked at again
        assert list(fields) == ["date_col", "not_hashed"] and "column 'v' is List" in fields["not_hashed"]
        assert list(rowhash.fields_of(Table(tmp_path / "lists.parquet"), None)) == ["not_hashed"]
        assert list(rowhash.fields_of(Table(tmp_path / "lists.parquet"), "nowhere")) == ["not_hashed"]
        (tmp_path / "not.parquet").write_bytes(b"hello")
        assert rowhash.fields_of(Table(tmp_path / "not.parquet"), "ds") == {}
        assert rowhash.fields_of(Table(tmp_path / "nowhere.parquet"), "ds") == {}

    def test_a_table_of_too_many_columns(self, tmp_path, monkeypatch):
        _table(days=5).write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "MOST_COLUMNS", 3)
        with pytest.raises(NotHashed, match="it has 4 columns, and a rows hash reads at most 3 at once"):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")

    def test_days_before_1970(self, tmp_path, monkeypatch):
        """A month split into its days, where a day's number from 1970 is below zero."""
        frame = _table(days=20, per_day=50, start=date(1961, 6, 14))
        frame.write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 5_000)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10_000)
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert len(record.rows) == 20 and list(record.rows)[0] == "1961-06-14/1961-06-14" and record.as_of == "1961-07-03"
        for key, first, _ in periods_of(record.rows):
            day = date(1970, 1, 1) + timedelta(microseconds=first[0])
            assert record.rows[key] == hash_frame(frame.filter(pl.col("ds") == day), "ds")

    def test_a_column_the_form_does_not_take(self, tmp_path):
        pl.DataFrame({"ds": [date(2024, 1, 2)], "v": [[1.0, 2.0]]}).write_parquet(tmp_path / "t.parquet")
        with pytest.raises(NotHashed, match="column 'v' is List"):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")

    def test_a_table_with_no_date_column_too_large_to_hold(self, tmp_path, monkeypatch):
        _table(days=400).write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10_000)
        with pytest.raises(NotHashed, match="it has no date column, and its rows count for more than"):
            hash_rows(Table(tmp_path / "t.parquet"), None)

    def test_nothing_is_left_in_the_scratch_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "cache"))
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 2_000)  # months, and days of them
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        _table(per_day=30).write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert len(record.rows) == 800
        assert list((tmp_path / "cache").rglob("*")) == [tmp_path / "cache" / "rows"]
        # Nor when it stops half-way: a day too large, found after everything was put
        monkeypatch.setattr(rowhash, "MOST_BYTES", 1_000)
        with pytest.raises(NotHashed):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")
        with pytest.raises(NotHashed):
            hash_in(Table(tmp_path / "t.parquet"), "ds", record.rows, record.as_of)
        assert list((tmp_path / "cache").rglob("*")) == [tmp_path / "cache" / "rows"]


def _layouts(folder: Path, frame: pl.DataFrame) -> dict:
    """The same rows laid out every way ChartBook's reader takes parquet; each as what a Table is made with."""
    keyed = frame.with_columns(pl.col("ds").dt.year().alias("year"))
    made = {}
    keyed.write_parquet(folder / "one.parquet")
    made["one file"] = dict(path=folder / "one.parquet")
    pq.write_table(keyed.to_arrow(), folder / "groups.parquet", row_group_size=97)
    made["one file of many row groups"] = dict(path=folder / "groups.parquet")
    keyed.to_pandas().to_parquet(folder / "pandas", partition_cols=["year"], index=False)
    made["a folder pandas partitioned"] = dict(path=folder / "pandas")
    keyed.write_parquet(folder / "polars", partition_by=["year"])
    made["a folder polars partitioned"] = dict(path=folder / "polars")
    (folder / "parts").mkdir()
    for i, piece in enumerate(keyed.sample(fraction=1.0, shuffle=True, seed=3).iter_slices(700)):
        piece.write_parquet(folder / "parts" / f"part-{i:03d}.parquet")
    made["a glob of files"] = dict(path=folder / "parts" / "part-*.parquet")
    made["a folder of files"] = dict(path=folder / "parts")
    return made


@pytest.fixture(scope="module")
def layouts(tmp_path_factory):
    return _layouts(tmp_path_factory.mktemp("layouts"), _table())


class TestReadALittleAtATime:
    """What a table read in batches gives is what the whole table gives, however it is laid out."""

    @pytest.mark.parametrize(
        "name",
        ["one file", "one file of many row groups", "a folder pandas partitioned", "a folder polars partitioned", "a glob of files", "a folder of files"],
    )
    def test_each_layout_as_the_whole_table(self, layouts, name, monkeypatch):
        table = Table(**layouts[name])
        assert "year" in table.schema().names()
        record = hash_rows(Table(**layouts[name]), "ds")
        assert record.rows == _whole(table, "ds") and record.row_count == 2400, name
        # And by month, each the hash of its own rows as the whole table has them
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 20_000)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        frame = table.scan().collect()
        by_month = hash_rows(Table(**layouts[name]), "ds")
        # 2022 and 2025 are whole, being within the size; 2023 and 2024 are their months
        assert by_month.row_count == 2400 and len(by_month.rows) == 1 + 12 + 12 + 1
        for key, first, last in periods_of(by_month.rows):
            low, high = (datetime(1970, 1, 1) + timedelta(microseconds=stamp[0]) for stamp in (first, last))
            assert by_month.rows[key] == hash_frame(frame.filter(pl.col("ds").is_between(low.date(), high.date())), "ds"), (name, key)

    def test_every_layout_gives_one_hash(self, layouts):
        records = {name: hash_rows(Table(**made), "ds").rows for name, made in layouts.items()}
        assert len({tuple(sorted(rows.items())) for rows in records.values()}) == 1, records

    def test_smaller_periods_are_the_same_rows(self, layouts, monkeypatch):
        """Months where years were: other periods, and each the hash of its own rows."""
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 20_000)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        frame = Table(**layouts["one file"]).scan().collect()
        record = hash_rows(Table(**layouts["a folder pandas partitioned"]), "ds")
        assert len(record.rows) > 12
        for key, first, last in periods_of(record.rows):
            low, high = (datetime(1970, 1, 1) + timedelta(microseconds=stamp[0]) for stamp in (first, last))
            part = frame.filter(pl.col("ds").is_between(low.date(), high.date()))
            assert record.rows[key] == hash_frame(part, "ds"), key

    def test_a_column_named_like_a_pattern(self, tmp_path):
        """polars reads `^y$` as a pattern: by period, too, such a column is a column, in a file and as a folder's key."""
        frame = _table(days=20).rename({"y": "^y$"})
        frame.write_parquet(tmp_path / "one.parquet")
        record = hash_rows(Table(tmp_path / "one.parquet"), "ds")
        assert record.rows == {"2022-11-01/2022-11-20": hash_frame(frame, "ds")}
        frame.with_columns(pl.nth(2) + 1.0).write_parquet(tmp_path / "other.parquet")
        assert hash_rows(Table(tmp_path / "other.parquet"), "ds").rows != record.rows
        assert not hash_in(Table(tmp_path / "other.parquet"), "ds", record.rows, record.as_of).same

    def test_the_date_column_can_be_a_folders_key(self, tmp_path):
        """``ds=2024-01-02/part.parquet``: the reader makes the column, and its rows are dated by it."""
        frame = _table(days=6, start=date(2024, 12, 29))
        for (day,), part in frame.partition_by("ds", as_dict=True).items():
            target = tmp_path / "by_day" / f"ds={day.isoformat()}"
            target.mkdir(parents=True)
            part.drop("ds").write_parquet(target / "part.parquet")
        table = Table(tmp_path / "by_day")
        assert table.schema()["ds"] == pl.Date
        record = hash_rows(table, "ds")
        assert list(record.rows) == ["2024-12-29/2024-12-31", "2025-01-01/2025-01-03"]
        assert record.rows == _whole(table, "ds")
        frame.write_parquet(tmp_path / "one.parquet")
        assert hash_rows(Table(tmp_path / "one.parquet"), "ds").rows == record.rows

    def test_an_arrow_file_has_no_rows_hash(self, tmp_path):
        """What it takes in memory cannot be told from its file: 19 MB of one, compressed, was 4.2 GB."""
        _table(days=40).write_ipc(tmp_path / "t.arrow")
        with pytest.raises(NotHashed, match="it is an Arrow IPC file, and what one takes in memory cannot be told from its file"):
            hash_rows(Table(tmp_path / "t.arrow"), "ds")
        assert list(rowhash.fields_of(Table(tmp_path / "t.arrow"), "ds")) == ["date_col", "not_hashed"]

    @pytest.mark.parametrize("format,name", [("csv", "t.csv"), ("jsonl", "t.jsonl")])
    def test_another_format_is_read_through_a_copy(self, tmp_path, format, name, monkeypatch):
        frame = _table(days=40)
        {"csv": frame.write_csv, "jsonl": frame.write_ndjson}[format](tmp_path / name)
        table = Table(tmp_path / name)
        assert hash_rows(table, "ds").rows == _whole(table, "ds")
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 500)  # a day each, through scratch files
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        record = hash_rows(Table(tmp_path / name), "ds")
        assert record.row_count == 120 and len(record.rows) == 40
        whole = table.scan().collect()
        dates = whole.get_column("ds")
        dates = dates.str.to_datetime(strict=False) if dates.dtype == pl.String else dates.cast(pl.Datetime("us"))
        for key, first, last in periods_of(record.rows):
            day = datetime(1970, 1, 1) + timedelta(microseconds=first[0])
            assert record.rows[key] == hash_frame(whole.filter(dates == day), "ds"), key


class TestAgainstARecord:
    """The check: a table's rows in the record's periods, up to its last timestamp."""

    @pytest.fixture
    def pinned(self, tmp_path):
        frame = _table(days=500)
        frame.write_parquet(tmp_path / "pinned.parquet")
        return frame, hash_rows(Table(tmp_path / "pinned.parquet"), "ds")

    def _compare(self, tmp_path, frame, record, name="later.parquet"):
        frame.write_parquet(tmp_path / name)
        return hash_in(Table(tmp_path / name), "ds", record.rows, record.as_of)

    def test_the_same_table(self, tmp_path, pinned):
        frame, record = pinned
        compared = self._compare(tmp_path, frame, record)
        assert compared.same and (compared.differ, compared.outside, compared.newer, compared.rows) == ([], 0, 0, 1500)

    def test_a_later_pull_with_newer_rows_holds_the_pinned_rows(self, tmp_path, pinned):
        frame, record = pinned
        later = _table(days=508)
        compared = self._compare(tmp_path, later.sample(fraction=1.0, shuffle=True, seed=5), record)
        assert compared.same and compared.newer == 24 and compared.rows == 1524

    def test_an_old_value_revised_names_its_period(self, tmp_path, pinned):
        frame, record = pinned
        revised = _table(days=508).with_columns(
            pl.when((pl.col("ds") == date(2023, 3, 14)) & (pl.col("unique_id") == "S1")).then(pl.col("y") + 1e-9).otherwise(pl.col("y")).alias("y")
        )
        compared = self._compare(tmp_path, revised, record)
        assert not compared.same and compared.differ == ["2023-01-01/2023-12-31"] and compared.outside == 0

    def test_a_row_gone_names_its_period(self, tmp_path, pinned):
        frame, record = pinned
        compared = self._compare(tmp_path, frame.filter(pl.col("ds") != date(2022, 12, 25)), record)
        assert compared.differ == ["2022-11-01/2022-12-31"]

    def test_a_row_arriving_late_inside_a_period(self, tmp_path, pinned):
        frame, record = pinned
        late = pl.DataFrame({"ds": [date(2023, 5, 5)], "unique_id": ["S9"], "y": [0.5], "n": [7]}, schema=frame.schema)
        compared = self._compare(tmp_path, pl.concat([frame, late]), record)
        assert compared.differ == ["2023-01-01/2023-12-31"] and compared.outside == 0

    def test_a_row_between_two_periods_is_one_the_pin_did_not_have(self, tmp_path):
        """A period is written by what was seen, so a later pull can hold a day between two that the pin did not."""
        frame = pl.concat([_table(days=10, start=date(2023, 12, 1)), _table(days=10, start=date(2024, 3, 1))])
        frame.write_parquet(tmp_path / "pinned.parquet")
        record = hash_rows(Table(tmp_path / "pinned.parquet"), "ds")
        assert list(record.rows) == ["2023-12-01/2023-12-10", "2024-03-01/2024-03-10"]
        between = pl.DataFrame({"ds": [date(2024, 1, 15)], "unique_id": ["S0"], "y": [0.5], "n": [7]}, schema=frame.schema)
        compared = self._compare(tmp_path, pl.concat([frame, between]), record)
        assert not compared.same and compared.differ == [] and compared.outside == 1 and compared.newer == 0

    def test_a_period_with_no_rows_left_differs(self, tmp_path, pinned):
        frame, record = pinned
        compared = self._compare(tmp_path, frame.filter(pl.col("ds").dt.year() != 2022), record)
        assert compared.differ == ["2022-11-01/2022-12-31"]

    def test_rows_with_no_date(self, tmp_path):
        frame = pl.concat([_table(days=5), pl.DataFrame({"ds": [None], "unique_id": ["a"], "y": [1.0], "n": [1]}, schema=_table(1).schema)])
        frame.write_parquet(tmp_path / "pinned.parquet")
        record = hash_rows(Table(tmp_path / "pinned.parquet"), "ds")
        assert self._compare(tmp_path, frame, record).same
        other = frame.with_columns(pl.when(pl.col("ds").is_null()).then(2.0).otherwise(pl.col("y")).alias("y"))
        assert self._compare(tmp_path, other, record).differ == [NO_DATE]
        # A row with no date where the pin had none is one the pin did not have
        dated = hash_rows(Table(tmp_path / "later.parquet"), "ds")
        assert NO_DATE in dated.rows
        _table(days=5).write_parquet(tmp_path / "dated.parquet")
        only = hash_rows(Table(tmp_path / "dated.parquet"), "ds")
        assert self._compare(tmp_path, frame, only).outside == 1

    def test_a_table_with_no_date_column(self, tmp_path):
        frame = _table(days=5)
        frame.write_parquet(tmp_path / "pinned.parquet")
        record = hash_rows(Table(tmp_path / "pinned.parquet"), None)
        frame.reverse().write_parquet(tmp_path / "again.parquet")
        assert hash_in(Table(tmp_path / "again.parquet"), None, record.rows, None).same
        _table(days=6).write_parquet(tmp_path / "more.parquet")
        compared = hash_in(Table(tmp_path / "more.parquet"), None, record.rows, None)
        assert not compared.same and compared.differ == [ALL]

    def test_other_bytes_and_another_layout_still_match(self, tmp_path, pinned):
        frame, record = pinned
        later = _table(days=503).with_columns(pl.col("ds").cast(pl.Datetime("ns")), pl.col("n").cast(pl.Int64))
        later.to_pandas().to_parquet(tmp_path / "split", partition_cols=["unique_id"], index=False)
        compared = hash_in(Table(tmp_path / "split"), "ds", record.rows, record.as_of)
        # The reader gives unique_id as a category from the folders' names: its text is the same
        assert compared.same and compared.newer == 9

    def test_a_moved_pin_keeps_the_periods_before_the_last(self, tmp_path, pinned):
        frame, record = pinned
        _table(days=800).write_parquet(tmp_path / "moved.parquet")
        moved = hash_rows(Table(tmp_path / "moved.parquet"), "ds")
        before, after = list(record.rows.items()), list(moved.rows.items())
        assert after[: len(before) - 1] == before[:-1]  # as they were
        assert after[len(before) - 1] != before[-1]  # the last one grew
        assert len(after) == len(before) + 1  # and one followed it

    def test_a_record_that_names_no_period(self, tmp_path, pinned):
        frame, record = pinned
        with pytest.raises(ValueError):
            hash_in(Table(tmp_path / "pinned.parquet"), "ds", {"2023/2024-13-01": "sha256:00"}, "2024-01-01")


class TestWhatTheReviewFound:
    """Each of these stopped a snapshot, or gave a record that was not the reader's rows."""

    @pytest.mark.skipif(os.name == "nt", reason="the limit on open files is set as POSIX sets it")
    def test_more_periods_than_a_process_may_have_files_open(self, tmp_path, monkeypatch):
        """Thirty years of months: no scratch file is held open, so the limit (256 on a Mac) is no limit here."""
        import resource

        frame = _table(days=30 * 365, per_day=2, start=date(1990, 1, 1))
        frame.sample(fraction=1.0, shuffle=True, seed=2).write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 40 * 2 * A_ROW)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
        monkeypatch.setattr(rowhash, "_BY_MONTH_FROM", 0)
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, hard))
        try:
            record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
            compared = hash_in(Table(tmp_path / "t.parquet"), "ds", record.rows, record.as_of)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        assert len(record.rows) == 360 and compared.same

    @pytest.mark.parametrize(
        "frame",
        [
            pl.DataFrame({"ds": [datetime(2024, 1, 2), None], "x": [1, 2]}).with_columns(
                pl.when(pl.col("x") == 2).then(pl.lit(253402300800 * 10**6 + 1)).otherwise(pl.col("ds").cast(pl.Int64)).cast(pl.Datetime("us")).alias("ds")
            ),
            pl.DataFrame({"ds": [2**31 - 1, 19000], "x": [1, 2]}, schema={"ds": pl.Int32, "x": pl.Int64}).with_columns(pl.col("ds").cast(pl.Date)),
            pl.DataFrame({"ds": [9223372036854776, 1], "x": [1, 2]}, schema={"ds": pl.Datetime("ms"), "x": pl.Int64}),
            pl.DataFrame({"ds": [-62135596800 * 10**6 - 1, 1], "x": [1, 2]}, schema={"ds": pl.Datetime("us"), "x": pl.Int64}),
        ],
        ids=["the year 10000", "a date past microseconds", "milliseconds past microseconds", "before the year 1"],
    )
    def test_a_date_no_record_can_write_is_refused_and_plainly(self, tmp_path, frame):
        """Seconds written as microseconds, say: no OverflowError, and no panic of polars, which is no Exception."""
        frame.write_parquet(tmp_path / "t.parquet")
        with pytest.raises(NotHashed, match="outside the years 1 to 9999|past what 64 bits of microseconds hold"):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")
        fields = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")
        assert list(fields) == ["date_col", "not_hashed"]
        # Beside a record it is not the record's rows, or cannot be told to be: never an error of another kind
        _table(days=3).write_parquet(tmp_path / "pinned.parquet")
        pinned = hash_rows(Table(tmp_path / "pinned.parquet"), "ds")
        try:
            assert hash_in(Table(tmp_path / "t.parquet"), "ds", pinned.rows, pinned.as_of).differ
        except NotHashed:
            pass

    def test_a_pin_past_what_nanoseconds_hold_differs(self, tmp_path):
        """A record with the year 9999 in it, beside a table of nanoseconds, which end in 2262."""
        frame = pl.DataFrame({"ds": [date(2024, 1, 2), date(9999, 12, 31)], "x": [1, 2]})
        frame.write_parquet(tmp_path / "pinned.parquet")
        pinned = hash_rows(Table(tmp_path / "pinned.parquet"), "ds")
        assert list(pinned.rows) == ["2024-01-02/2024-01-02", "9999-12-31/9999-12-31"]
        frame.head(1).with_columns(pl.col("ds").cast(pl.Datetime("ns"))).write_parquet(tmp_path / "fine.parquet")
        compared = hash_in(Table(tmp_path / "fine.parquet"), "ds", pinned.rows, pinned.as_of)
        assert compared.differ == ["9999-12-31/9999-12-31"] and compared.outside == 0

    def test_rows_with_no_date_are_held_to_the_most_too(self, tmp_path, monkeypatch):
        """A CSV of US dates and a declared date column: every row has no date, and they are one piece."""
        frame = _table(days=300).with_columns(pl.col("ds").dt.strftime("%m/%d/%Y"))
        frame.write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert list(record.rows) == [NO_DATE] and hash_in(Table(tmp_path / "t.parquet"), "ds", record.rows, record.as_of).same
        monkeypatch.setattr(rowhash, "MOST_BYTES", 10_000)
        with pytest.raises(NotHashed, match="its rows with no date, 900 of them, count for"):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")
        # And beside a record they are not held either. A record another version made may hold
        # larger periods, so they are not said to differ: they are not compared
        with pytest.raises(NotHashed, match="its rows with no date count for more than 0 MB .* they are not compared"):
            hash_in(Table(tmp_path / "t.parquet"), "ds", record.rows, record.as_of)

    def test_a_period_larger_than_is_held_is_not_compared(self, tmp_path, monkeypatch):
        """A record from a version that held more in a period: its rows are not told to differ without being read."""
        _table(days=400).write_parquet(tmp_path / "t.parquet")
        record = hash_rows(Table(tmp_path / "t.parquet"), "ds")
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 5_000)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 5_000)
        with pytest.raises(NotHashed, match="its rows of 2022-11-01 to 2022-12-31 count for more than"):
            hash_in(Table(tmp_path / "t.parquet"), "ds", record.rows, record.as_of)
        # Nor a table with no date column
        whole = hash_rows(Table(tmp_path / "t.parquet"), None) if False else None
        monkeypatch.undo()
        whole = hash_rows(Table(tmp_path / "t.parquet"), None)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 5_000)
        with pytest.raises(NotHashed, match="its rows count for more than"):
            hash_in(Table(tmp_path / "t.parquet"), None, whole.rows, None)

    def test_one_file_under_a_folder_that_names_a_key(self, tmp_path):
        """``seed=42/project/_data/prices.parquet``: the reader makes a column of the folder, and so do the rows hashed."""
        folder = tmp_path / "seed=42" / "project" / "_data"
        folder.mkdir(parents=True)
        _table(days=5).write_parquet(folder / "prices.parquet")
        table = Table(folder / "prices.parquet")
        read = table.scan().collect()
        record = hash_rows(table, "ds")
        assert record.rows == {"2022-11-01/2022-11-05": hash_frame(read, "ds")}
        assert rowhash.fields_of(Table(folder / "prices.parquet"), "ds")["rows"] == record.rows

    def test_a_key_that_is_a_column_of_the_file_too(self, tmp_path):
        """``year=2024/part.parquet`` with a ``year`` of its own that says otherwise in one row: the reader's rows are what is hashed."""
        folder = tmp_path / "t" / "year=2024"
        folder.mkdir(parents=True)
        pl.DataFrame({"ds": [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)], "year": [2024, 2024, 1999]}).write_parquet(folder / "part.parquet")
        (tmp_path / "t" / "year=2025").mkdir()
        pl.DataFrame({"ds": [date(2025, 1, 2)], "year": [2025]}).write_parquet(tmp_path / "t" / "year=2025" / "part.parquet")
        table = Table(tmp_path / "t")
        assert hash_rows(table, "ds").rows == _whole(table, "ds")

    def test_another_format_too_large_to_read_whole(self, tmp_path, monkeypatch):
        """Only parquet is read a little at a time."""
        _table(days=40).write_csv(tmp_path / "t.csv")
        monkeypatch.setattr(rowhash, "OTHER_BYTES", 1024)
        with pytest.raises(NotHashed, match="it is csv, more than 0 MB of text, and only parquet is read a little at a time"):
            hash_rows(Table(tmp_path / "t.csv"), "ds")
        assert list(rowhash.fields_of(Table(tmp_path / "t.csv"), "ds")) == ["date_col", "not_hashed"]

    def test_a_zipped_file_counts_for_its_text(self, tmp_path, monkeypatch):
        """Mostly zeros zip to nothing: what is held is the text, so the text is what is measured, and no further than the limit."""
        import gzip

        text = _table(days=40).write_csv()
        with gzip.open(tmp_path / "t.csv.gz", "wb") as zipped:
            zipped.write(text.encode("utf-8"))
        assert (tmp_path / "t.csv.gz").stat().st_size < len(text) // 2
        assert rowhash._text_bytes(tmp_path / "t.csv.gz", 10**9) == len(text.encode("utf-8"))
        assert hash_rows(Table(tmp_path / "t.csv.gz"), "ds").row_count == 120
        monkeypatch.setattr(rowhash, "OTHER_BYTES", len(text.encode("utf-8")) - 1)
        with pytest.raises(NotHashed, match="it is csv, more than"):
            hash_rows(Table(tmp_path / "t.csv.gz"), "ds")

    def test_a_type_that_goes_on_is_not_written_out(self, tmp_path):
        wide = pl.DataFrame({"ds": [date(2024, 1, 2)], "v": [{f"field_{i}": i for i in range(150)}]})
        wide.write_parquet(tmp_path / "t.parquet")
        said = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")["not_hashed"]
        assert said.startswith("column 'v' is Struct(") and len(said) < 200

    def test_what_is_no_fault_of_the_tables_is_said_apart(self, tmp_path, monkeypatch):
        """A full disk under the scratch files: nothing is recorded of the rows, and the next time may hash them."""
        _table().write_parquet(tmp_path / "t.parquet")

        def full(self):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(rowhash._Pieces, "flush", full)
        with pytest.raises(rowhash.NotNow, match="OSError: .*No space left on device"):
            rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")

    @pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs a folder this user cannot write")
    def test_a_cache_that_cannot_be_written_is_no_failure(self, tmp_path, monkeypatch):
        """The scratch files go to the system's temporary folder."""
        (tmp_path / "cache" / "rows").mkdir(parents=True)
        os.chmod(tmp_path / "cache" / "rows", 0o555)
        monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "cache"))
        _table().write_parquet(tmp_path / "t.parquet")
        try:
            assert len(hash_rows(Table(tmp_path / "t.parquet"), "ds").rows) == 4
        finally:
            os.chmod(tmp_path / "cache" / "rows", 0o755)

    def test_scratch_a_killed_process_left_is_removed_a_day_later(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "cache"))
        # One a day old; one a minute old; and one begun a day ago that a run is still writing to
        for name, age, written in (("chartbook-rows-old", 2 * 86400, 2 * 86400), ("chartbook-rows-new", 60, 60), ("chartbook-rows-live", 2 * 86400, 30)):
            left = tmp_path / "cache" / "rows" / name
            (left / "pieces").mkdir(parents=True)
            (left / "pieces" / "0.arrows").write_bytes(b"x")
            for path, seconds in ((left / "pieces" / "0.arrows", written), (left / "pieces", age), (left, age)):
                past = time.time() - seconds
                os.utime(path, (past, past))
        _table(days=3).write_parquet(tmp_path / "t.parquet")
        hash_rows(Table(tmp_path / "t.parquet"), "ds")
        assert sorted(path.name for path in (tmp_path / "cache" / "rows").iterdir()) == ["chartbook-rows-live", "chartbook-rows-new"]


class TestWhatTheSecondReviewFound:

    def test_a_batch_is_measured_from_its_rows_and_not_from_the_file(self, tmp_path):
        """Text a file holds once, in a dictionary, is a few bytes a row in the file and kilobytes in memory: a batch is still a few megabytes."""
        words = [f"{i:04d}" + "x" * 5000 for i in range(50)]
        rows = 60_000
        frame = pl.DataFrame({"ds": [date(2024, 1, 1) + timedelta(days=i % 300) for i in range(rows)], "x": list(range(rows))}).with_columns(
            text=pl.Series([words[i % 50] for i in range(rows)])
        )
        frame.write_parquet(tmp_path / "t.parquet")
        assert (tmp_path / "t.parquet").stat().st_size < 3 * 1024 * 1024  # and it is 300 MB of rows
        table = Table(tmp_path / "t.parquet")
        largest = rows_seen = 0
        for batch in table.batches():
            largest = max(largest, batch.nbytes)
            rows_seen += batch.num_rows
        assert rows_seen == rows and largest <= 4 * rowhash.BATCH_BYTES, f"{largest / 2**20:.0f} MB"

    def test_small_rows_are_read_many_at_a_time_and_every_row_once(self, tmp_path):
        """A row group is begun again with more rows at a time once its rows are seen to be small: none is read twice, and none lost."""
        frame = _table(days=20_000, per_day=3, start=date(1950, 1, 1)).with_columns(order=pl.int_range(pl.len()))
        pq.write_table(frame.to_arrow(), tmp_path / "t.parquet", row_group_size=25_000)
        seen, sizes = [], []
        for batch in Table(tmp_path / "t.parquet").batches():
            seen.extend(batch.column("order").to_pylist())
            sizes.append(batch.num_rows)
        assert seen == list(range(60_000))
        assert max(sizes) > 4_000 and len(sizes) < 40

    def test_rows_that_grow_within_a_row_group(self, tmp_path):
        """Small rows first and large ones after, in one row group: the group is begun again with fewer rows, from where it was."""
        rows = 30_000
        text = ["a"] * 20_000 + ["b" * 20_000] * 10_000
        frame = pl.DataFrame({"ds": [date(2024, 1, 1)] * rows, "order": list(range(rows)), "text": text})
        pq.write_table(frame.to_arrow(), tmp_path / "t.parquet", row_group_size=rows, use_dictionary=False)
        seen, largest = [], 0
        for batch in Table(tmp_path / "t.parquet").batches():
            seen.extend(batch.column("order").to_pylist())
            largest = max(largest, batch.nbytes)
        assert seen == list(range(rows)) and largest <= 4 * rowhash.BATCH_BYTES, f"{largest / 2**20:.0f} MB"

    def test_a_folder_with_a_partition_of_no_rows(self, tmp_path):
        """One file a day, written in a loop, and a holiday: the day with no rows stops nothing."""
        frame = _table(days=3, start=date(2024, 1, 1))
        for day, part in ((date(2024, 1, 1), frame.clear()), (date(2024, 1, 2), frame.filter(pl.col("ds") == date(2024, 1, 2))), (date(2024, 1, 3), frame.filter(pl.col("ds") == date(2024, 1, 3)))):
            folder = tmp_path / "trades" / f"day={day.isoformat()}"
            folder.mkdir(parents=True)
            part.write_parquet(folder / "part.parquet")
        table = Table(tmp_path / "trades")
        record = hash_rows(table, "ds")
        assert record.row_count == 6 and record.rows == _whole(table, "ds")
        assert hash_in(Table(tmp_path / "trades"), "ds", record.rows, record.as_of).same
        assert "rows" in rowhash.fields_of(Table(tmp_path / "trades"), "ds")

    @pytest.mark.parametrize("values", [("007", "abc"), ("00123456", "0012AB78"), ("1e3", "x"), ("true", "maybe")], ids=["007", "cusip", "1e3", "true"])
    def test_a_key_is_typed_by_all_its_folders(self, tmp_path, values):
        """``code=007`` beside ``code=abc``: the table has the text ``007``, as the reader gives it, though the folder alone reads as a number."""
        frame = _table(days=4, start=date(2024, 1, 1))
        for value in values:
            folder = tmp_path / "t" / f"code={value}"
            folder.mkdir(parents=True)
            frame.write_parquet(folder / "part.parquet")
        table = Table(tmp_path / "t")
        read = table.scan().collect()
        assert sorted(set(read["code"].to_list())) == sorted(values)
        record = hash_rows(table, "ds")
        assert record.rows == _whole(table, "ds")
        assert record.rows == {"2024-01-01/2024-01-04": hash_frame(read, "ds")}

    def test_folders_that_name_different_keys_make_no_column(self, tmp_path):
        """``a=1/b=x/`` beside ``a=2/``: the reader reads no key of them, so a file's own column ``a`` stands."""
        for folder, values in (("a=1/b=x", [5, 6]), ("a=2", [7])):
            (tmp_path / "t" / folder).mkdir(parents=True)
            pl.DataFrame({"ds": [date(2024, 1, 2)] * len(values), "a": values}).write_parquet(tmp_path / "t" / folder / "part.parquet")
        table = Table(tmp_path / "t")
        read = table.scan().collect()
        assert sorted(read["a"].to_list()) == [5, 6, 7]
        assert hash_rows(table, "ds").rows == {"2024-01-02/2024-01-02": hash_frame(read, "ds")}

    def test_a_column_with_no_name(self, tmp_path):
        """R's row names, read and written again: the column has no name, and the hash does not see where it stands."""
        frame = pl.DataFrame({"": [1, 2, 3], "ds": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)], "y": [0.5, 1.5, 2.5]})
        frame.write_parquet(tmp_path / "a.parquet")
        frame.select("ds", "y", "").write_parquet(tmp_path / "b.parquet")
        a, b = hash_rows(Table(tmp_path / "a.parquet"), "ds"), hash_rows(Table(tmp_path / "b.parquet"), "ds")
        assert a.rows == b.rows == {"2024-01-01/2024-01-03": hash_frame(frame, "ds")}
        assert hash_in(Table(tmp_path / "b.parquet"), "ds", a.rows, a.as_of).same
        named = frame.rename({"": "column_0"})
        named.write_parquet(tmp_path / "named.parquet")
        assert hash_rows(Table(tmp_path / "named.parquet"), "ds").rows != a.rows
        # And a table with no date column, which is held whole
        assert hash_rows(Table(tmp_path / "a.parquet"), None).rows == {ALL: hash_frame(frame)}

    def test_what_the_machine_could_not_do_just_now_is_not_said_of_the_table(self, tmp_path, monkeypatch):
        """A file that could not be read this time, no memory: nothing is recorded, so nothing is taken from it by a later snapshot."""
        _table().write_parquet(tmp_path / "t.parquet")
        for error in (OSError(5, "Input/output error"), MemoryError("malloc of size 1073741824 failed")):
            def broken(self, *arguments, **options):
                raise error

            monkeypatch.setattr(pq.ParquetFile, "iter_batches", broken)
            with pytest.raises(rowhash.NotNow):
                rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")
            monkeypatch.undo()

    def test_what_is_the_same_at_every_try_is_why_it_has_no_hash(self, tmp_path, monkeypatch):
        """Not "this time": the next snapshot would be told the same, and would try again for ever."""
        _table().write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "hash_frame", lambda *arguments, **options: (_ for _ in ()).throw(RuntimeError("the same again")))
        fields = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")
        assert fields == {"date_col": "ds", "not_hashed": "its rows could not be hashed (RuntimeError: the same again)"}

    def test_a_number_of_128_bits_is_refused_plainly(self, tmp_path):
        if not hasattr(pl, "Int128"):
            pytest.skip("this polars has no 128-bit whole numbers")
        pl.DataFrame({"ds": [date(2024, 1, 2)], "n": [5]}, schema={"ds": pl.Date, "n": pl.Int128}).write_parquet(tmp_path / "t.parquet")
        fields = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")
        assert list(fields) == ["date_col", "not_hashed"] and fields["not_hashed"].startswith("its columns cannot be read a batch at a time")

    def test_no_folder_of_this_machine_is_in_what_a_record_says(self, tmp_path, monkeypatch):
        """Why a table has no hash is read on other machines, in a store a team shares."""
        _table().write_parquet(tmp_path / "t.parquet")

        def gone(self, *arguments, **options):
            raise ValueError(f"Failed to open local file '{tmp_path / 't.parquet'}'. Detail: no such thing")

        monkeypatch.setattr(pq.ParquetFile, "iter_batches", gone)
        said = rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")["not_hashed"]
        assert str(tmp_path) not in said and "t.parquet" in said

    def test_a_long_name_is_not_written_out(self, tmp_path):
        pl.DataFrame({"ds": [date(2024, 1, 2)], "n" * 5000: [[1.0]]}).write_parquet(tmp_path / "t.parquet")
        assert len(rowhash.fields_of(Table(tmp_path / "t.parquet"), "ds")["not_hashed"]) < 300

    def test_text_dates_to_the_minute_with_an_offset(self):
        read = rowhash._dates_in_text(pl.Series("ds", ["2024-01-01T10:00Z", "2024-01-01 10:00+02:00", "2024-01-01T10:00"]))
        assert read.to_list() == [datetime(2024, 1, 1, 10), datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10)]

    def test_a_date_column_named_like_a_pattern(self, tmp_path):
        """``^ds$`` is a pattern to polars: the dates are still its dates, as a date, a time and text."""
        days = [date(2024, 1, 2), date(2024, 1, 3), date(2025, 6, 30)]
        for kind in (pl.Date, pl.Datetime("ns"), pl.String):
            frame = pl.DataFrame({"^ds$": days, "x": [1, 2, 3]}).with_columns(pl.nth(0).cast(kind))
            frame.write_parquet(tmp_path / "t.parquet")
            record = hash_rows(Table(tmp_path / "t.parquet"), "^ds$")
            assert list(record.rows) == ["2024-01-02/2024-01-03", "2025-06-30/2025-06-30"] and record.as_of == "2025-06-30", kind
            assert hash_in(Table(tmp_path / "t.parquet"), "^ds$", record.rows, record.as_of).same
