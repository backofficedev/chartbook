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

from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from chartbook import rowhash
from chartbook.rowhash import ALL, NO_DATE, NotHashed, Table, choose, hash_frame, hash_in, hash_rows, periods_of, stamp_text


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


class TestChoosingThePeriods:
    """Whole years; a year too large as its months; such a month as its days. Sizes are bytes in memory."""

    def _days(self, start: date, days: int, rows: int) -> dict:
        first = (start - date(1970, 1, 1)).days
        return {first + i: rows for i in range(days)}

    def _said(self, periods) -> list:
        return [
            f"{date(1970, 1, 1) + timedelta(days=first)}/{date(1970, 1, 1) + timedelta(days=last)}"
            for first, last in periods
        ]

    def test_whole_years(self):
        days = self._days(date(2022, 11, 1), 800, 3)
        assert self._said(choose(days, a_row=100)) == [
            "2022-11-01/2022-12-31", "2023-01-01/2023-12-31", "2024-01-01/2024-12-31", "2025-01-01/2025-01-08",
        ]

    def test_a_year_too_large_is_its_months(self):
        days = self._days(date(2023, 1, 1), 365, 10)
        periods = choose(days, a_row=100, period_bytes=100 * 10 * 40)  # forty days' worth
        assert len(periods) == 12 and self._said(periods)[:2] == ["2023-01-01/2023-01-31", "2023-02-01/2023-02-28"]

    def test_a_month_too_large_is_its_days(self):
        days = {**self._days(date(2023, 1, 1), 59, 10), **self._days(date(2023, 3, 1), 31, 1000)}
        periods = choose(days, a_row=100, period_bytes=100 * 10 * 40, most_bytes=10**9)
        said = self._said(periods)
        assert said[:2] == ["2023-01-01/2023-01-31", "2023-02-01/2023-02-28"]
        assert said[2:] == [f"2023-03-{day:02d}/2023-03-{day:02d}" for day in range(1, 32)]

    def test_only_the_days_that_have_rows(self):
        """A period is written by what was seen: no date that has not happened."""
        days = {(date(2023, 6, 14) - date(1970, 1, 1)).days: 5, (date(2023, 12, 29) - date(1970, 1, 1)).days: 5}
        assert self._said(choose(days, a_row=100)) == ["2023-06-14/2023-12-29"]

    def test_a_day_too_large_to_hold_is_refused(self):
        days = self._days(date(2023, 3, 1), 2, 1000)
        with pytest.raises(NotHashed, match="its rows of 2023-03-01 alone, 1,000 of them"):
            choose(days, a_row=100, period_bytes=1000, most_bytes=2000)

    def test_the_size_of_a_period_is_fixed_here(self):
        """Set for a machine with 8 GB, and no setting: whoever checks must hold what whoever pinned chose."""
        assert rowhash.PERIOD_BYTES == 128 * 1024 * 1024 and rowhash.MOST_BYTES == 2 * rowhash.PERIOD_BYTES


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
        """A CSV's: parsed as the index parses a dataframe's date range; what does not parse has no date."""
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
        assert list(fields) == ["not_hashed"] and "column 'v' is List" in fields["not_hashed"]
        (tmp_path / "not.parquet").write_bytes(b"hello")
        assert rowhash.fields_of(Table(tmp_path / "not.parquet"), "ds") == {}
        assert rowhash.fields_of(Table(tmp_path / "nowhere.parquet"), "ds") == {}

    def test_a_table_of_too_many_columns(self, tmp_path, monkeypatch):
        _table(days=5).write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "MOST_COLUMNS", 3)
        with pytest.raises(NotHashed, match="it has 4 columns, and a rows hash reads at most 3 at once"):
            hash_rows(Table(tmp_path / "t.parquet"), "ds")

    def test_a_year_that_turns_out_too_large_is_hashed_by_day(self, tmp_path, monkeypatch):
        """What a row takes is reckoned from a few rows; a period that turns out over the most is split again, before 1970 too."""
        frame = _table(days=20, per_day=50, start=date(1961, 6, 14))
        frame.write_parquet(tmp_path / "t.parquet")
        monkeypatch.setattr(rowhash, "choose", lambda days, a_row, **sizes: [(min(days), max(days))])  # one period, whatever it takes
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
        with pytest.raises(NotHashed, match="it has no date column, and its rows take more than"):
            hash_rows(Table(tmp_path / "t.parquet"), None)

    def test_nothing_is_left_in_the_scratch_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_CACHE", str(tmp_path / "cache"))
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 2_000)  # so that it is read through scratch files
        _table().write_parquet(tmp_path / "t.parquet")
        hash_rows(Table(tmp_path / "t.parquet"), "ds")
        left = [path for path in (tmp_path / "cache").rglob("*") if path.is_file()]
        assert left == []


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
        for size in (rowhash.PERIOD_BYTES, 20_000):  # held in memory, and through scratch files
            monkeypatch.setattr(rowhash, "PERIOD_BYTES", size)
            monkeypatch.setattr(rowhash, "MOST_BYTES", 10**9)
            record = hash_rows(Table(**layouts[name]), "ds")
            if size == rowhash.PERIOD_BYTES and size > 20_000:
                assert record.rows == _whole(table, "ds"), name
            assert record.row_count == 2400

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

    @pytest.mark.parametrize("format,name", [("csv", "t.csv"), ("jsonl", "t.jsonl"), ("ipc", "t.arrow")])
    def test_another_format_is_read_through_a_copy(self, tmp_path, format, name, monkeypatch):
        frame = _table(days=40)
        {"csv": frame.write_csv, "jsonl": frame.write_ndjson, "ipc": frame.write_ipc}[format](tmp_path / name)
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
