"""Tests for a read through a pin that a build of yours stands in for (``docs_src/design/pins-and-rebuilds.md``, step 6, "Reads").

A read through a pin gives the pinned rows, on every machine. Where the
store has the pinned file, it is read. Where a build of yours stands in,
it holds the pinned rows and whatever has come since: ``data.load`` and
``data.sql`` leave out the rows after the pin's last date, ``data.path``
and ``data.files`` hand over the file as it is and say so once, and
``data.as_of`` says where the pinned rows end. Only ``chartbook update``
brings later rows.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, config, data, lock, snapshot
from chartbook import resolve as resolve_module
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _yields(days: int, start: date = date(2025, 12, 1)) -> pl.DataFrame:
    """Two series a day."""
    when = [start + timedelta(days=i) for i in range(days) for _ in range(2)]
    return pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("T{}", pl.int_range(pl.len()) % 2),
        y=(4.0 + pl.int_range(pl.len()) * 0.01),
    )


def _upstream(directory: Path, tables: dict) -> Path:
    """An upstream pipeline with these dataframes, each ``name: (frame, date_col or None, how it is written)``."""
    entries = {}
    (directory / "_data").mkdir(parents=True)
    for name, (frame, date_col, write) in tables.items():
        entries[name] = {"path": f"./_data/{name}.parquet", "docs": "d", **({"date_col": date_col} if date_col else {})}
        write(frame, directory / "_data" / f"{name}.parquet")
    _write_manifest(directory, {"project": {"id": "acme/rates"}, "dataframes": entries})
    commit_pipeline(directory)
    return directory


def _polars(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path)


def _pandas(frame: pl.DataFrame, path: Path) -> None:
    frame.to_pandas().to_parquet(path, index=False)


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


def _pin(work: Path, monkeypatch, tables: dict) -> tuple:
    """The author builds the upstream, declares it ready and pins it, in the author's own store."""
    rates = _upstream(work / "rates", tables)
    report = work / "report"
    _write_manifest(report, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
    snapshot.make(rates, store=FolderStore(work / "author"))
    assert not lock.pin(report, FolderStore(work / "author")).problems
    return rates, report


def _student(work: Path, monkeypatch) -> FolderStore:
    """A student's machine: a store of their own, with nothing of the author's in it."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "student-cache"))
    resolve_module._said_stand_ins.clear()
    assets._said_newer.clear()
    return FolderStore(work / "student")


def _rebuild(rates: Path, store, tables: dict):
    """The student builds the upstream at the same commit: these rows now."""
    for name, (frame, _, write) in tables.items():
        write(frame, rates / "_data" / f"{name}.parquet")
    return snapshot.make(rates, store=store).snapshot


@pytest.fixture
def stood_in(work, monkeypatch):
    """A report pinned to 40 days of yields, read on a student's machine from their own build of 48."""
    rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
    built = _rebuild(rates, _student(work, monkeypatch), {"treasury": (_yields(48), "ds", _pandas)})
    return report, built


class TestLoad:
    """The pinned rows, on every machine: a build that stands in is read without what has come since."""

    def test_it_leaves_out_the_rows_after_the_pins_last_date(self, stood_in):
        report, _ = stood_in
        frame = data.load("acme/rates:treasury", project_dir=report)
        assert isinstance(frame, pl.LazyFrame)
        read = frame.collect()
        assert read.height == 80 and read["ds"].max().date() == date(2026, 1, 9)
        # The pinned rows, value for value, whatever types the student's writer gave them
        assert read.with_columns(pl.col("ds").cast(pl.Date)).sort("ds", "unique_id").equals(_yields(40).sort("ds", "unique_id"))

    @pytest.mark.parametrize("format", ["polars", "polars_eager", "pandas"])
    def test_in_every_form_it_is_returned_in(self, stood_in, format):
        report, _ = stood_in
        frame = data.load("acme/rates:treasury", format=format, project_dir=report)
        frame = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
        assert len(frame) == 80
        assert str(frame["ds"].max())[:10] == "2026-01-09"

    def test_the_author_and_the_student_load_the_same_table(self, work, monkeypatch):
        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
        authors = data.load("acme/rates:treasury", format="polars_eager", project_dir=report)
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (_yields(48), "ds", _polars)})
        students = data.load("acme/rates:treasury", format="polars_eager", project_dir=report)
        assert students.sort("ds", "unique_id").equals(authors.sort("ds", "unique_id"))

    def test_the_pinned_file_itself_is_read_as_it_is(self, work, monkeypatch):
        """A team with a shared store: nothing is left out of a file that is the pin."""
        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
        monkeypatch.setattr("chartbook.rowhash.pinned_rows", lambda *arguments: pytest.fail("cut"))
        assert data.load("acme/rates:treasury", format="polars_eager", project_dir=report).height == 80

    def test_a_table_with_no_date_column_is_all_its_rows(self, work, monkeypatch):
        codes = pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]})
        rates, report = _pin(work, monkeypatch, {"codes": (codes, None, _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"codes": (codes.reverse(), None, _pandas)})
        location = resolve_module.resolve("acme/rates:codes", start_dirs=[report])
        assert location.stands_in and location.date_col is None
        assert data.load("acme/rates:codes", format="polars_eager", project_dir=report).height == 2

    def test_rows_with_no_date_are_the_pins_too(self, work, monkeypatch):
        undated = pl.DataFrame({"ds": [None], "unique_id": ["T9"], "y": [0.5]}, schema=_yields(1).schema)
        rates, report = _pin(work, monkeypatch, {"treasury": (pl.concat([_yields(40), undated]), "ds", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (pl.concat([_yields(48), undated]), "ds", _pandas)})
        read = data.load("acme/rates:treasury", format="polars_eager", project_dir=report)
        assert read.height == 81 and read["ds"].null_count() == 1

    def test_times_to_the_nanosecond(self, work, monkeypatch):
        ticks = pl.DataFrame({"t": [1_700_000_000_000_000_001 + i for i in range(6)], "x": list(range(6))}).with_columns(pl.col("t").cast(pl.Datetime("ns")))
        rates, report = _pin(work, monkeypatch, {"ticks": (ticks.head(4), "t", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"ticks": (ticks, "t", _polars)})
        assert data.load("acme/rates:ticks", format="polars_eager", project_dir=report)["x"].to_list() == [0, 1, 2, 3]
        assert data.sql("select x from {acme/rates:ticks} order by x", project_dir=report).collect()["x"].to_list() == [0, 1, 2, 3]

    def test_dates_that_are_text(self, work, monkeypatch):
        """A date column of text: a row's date is told as the rows hash told it."""
        text = _yields(48).with_columns(pl.col("ds").dt.strftime("%Y-%m-%d"))
        rates, report = _pin(work, monkeypatch, {"treasury": (text.head(80), "ds", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (text, "ds", _pandas)})
        for format in ("polars_eager", "pandas"):
            assert len(data.load("acme/rates:treasury", format=format, project_dir=report)) == 80
        assert data.sql("select count(*) as n from {acme/rates:treasury}", project_dir=report).collect()["n"][0] == 80

    def test_a_date_index_that_pandas_wrote(self, work, monkeypatch):
        """A frame indexed by date, with a name on the index: pandas reads it back into the index, and the rows are told by it there."""
        def indexed(frame: pl.DataFrame, path: Path) -> None:
            frame.to_pandas().set_index("ds").to_parquet(path)

        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", indexed)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (_yields(48), "ds", indexed)})
        frame = data.load("acme/rates:treasury", format="pandas", project_dir=report)
        assert frame.index.name == "ds" and len(frame) == 80 and str(frame.index.max())[:10] == "2026-01-09"


class TestSql:

    def test_it_leaves_them_out_too(self, stood_in):
        report, _ = stood_in
        counted = data.sql("select count(*) as n, max(ds) as last from {acme/rates:treasury}", project_dir=report).collect()
        assert counted["n"][0] == 80 and str(counted["last"][0])[:10] == "2026-01-09"

    def test_the_name_it_goes_by_in_sql_is_its_pinned_rows(self, stood_in):
        report, _ = stood_in
        said = data.ref("acme/rates:treasury", project_dir=report)
        assert said.startswith("(select * from read_parquet(") and said.endswith('where ("ds" is null or "ds" <= TIMESTAMP \'2026-01-09 00:00:00.000000\'))')
        import duckdb

        assert duckdb.sql(f"select count(*) from {said}").fetchall() == [(80,)]

    def test_a_column_of_dates(self, work, monkeypatch):
        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (_yields(48).reverse(), "ds", _polars)})
        assert "\"ds\" <= DATE '2026-01-09'" in data.ref("acme/rates:treasury", project_dir=report)
        assert data.sql("select count(*) as n from {acme/rates:treasury}", project_dir=report).collect()["n"][0] == 80

    def test_a_time_with_a_zone(self, work, monkeypatch):
        zoned = _yields(48).with_columns(pl.col("ds").cast(pl.Datetime("us")).dt.replace_time_zone("America/Chicago"))
        rates, report = _pin(work, monkeypatch, {"treasury": (zoned.head(80), "ds", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (zoned, "ds", _pandas)})
        assert "TIMESTAMPTZ '2026-01-09 06:00:00.000000+00'" in data.ref("acme/rates:treasury", project_dir=report)
        assert data.sql("select count(*) as n from {acme/rates:treasury}", project_dir=report).collect()["n"][0] == 80
        assert data.load("acme/rates:treasury", format="polars_eager", project_dir=report).height == 80

    def test_joined_to_a_table_of_ones_own(self, stood_in):
        report, _ = stood_in
        _write_manifest(
            report,
            {
                "project": {"id": "acme/report"},
                "dependencies": {"acme/rates": {"path": "../rates"}},
                "dataframes": {"names": {"path": "./_data/names.parquet", "docs": "d"}},
            },
        )
        (report / "_data").mkdir()
        pl.DataFrame({"unique_id": ["T0", "T1"], "name": ["two-year", "ten-year"]}).write_parquet(report / "_data" / "names.parquet")
        joined = data.sql(
            "select name, count(*) as n from {acme/rates:treasury} join {names} using (unique_id) group by name order by name",
            project_dir=report,
        ).collect()
        assert joined["n"].to_list() == [40, 40]


class TestPath:
    """The file as it is, newer rows and all: said once, with where the pinned rows end."""

    def test_it_is_the_whole_file_and_says_so_once(self, stood_in, capsys):
        report, built = stood_in
        path = data.path("acme/rates:treasury", project_dir=report)
        assert pl.read_parquet(path).height == 96
        data.path("acme/rates:treasury", project_dir=report)
        (file,) = data.files("acme/rates:treasury", project_dir=report)
        assert file == path
        said = capsys.readouterr().err
        assert said.count(
            "acme/rates:treasury: this file is your own build's, and has 16 rows after 2026-01-09, the last date "
            "chartbook.lock pins. data.load() and data.sql() leave them out; a reader of your own keeps the rows up to "
            "data.as_of('acme/rates:treasury').\n"
        ) == 1

    def test_load_says_nothing_of_it(self, stood_in, capsys):
        report, _ = stood_in
        data.load("acme/rates:treasury", project_dir=report).collect()
        assert "this file is your own build's" not in capsys.readouterr().err

    def test_a_build_with_no_newer_rows_says_nothing(self, work, monkeypatch, capsys):
        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
        _rebuild(rates, _student(work, monkeypatch), {"treasury": (_yields(40), "ds", _pandas)})
        assert pl.read_parquet(data.path("acme/rates:treasury", project_dir=report)).height == 80
        assert "this file is your own build's" not in capsys.readouterr().err

    def test_the_command_says_it_too(self, stood_in):
        report, _ = stood_in
        result = CliRunner().invoke(main, ["path", "acme/rates:treasury", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        assert "has 16 rows after 2026-01-09" in result.output or "has 16 rows after 2026-01-09" in (result.stderr if result.stderr_bytes is not None else "")


class TestAsOf:
    """Where the pinned rows end: the same on every machine that has the lockfile."""

    def test_a_reader_of_ones_own_keeps_the_pinned_rows_by_it(self, stood_in):
        report, _ = stood_in
        import pandas as pd

        last = data.as_of("acme/rates:treasury", project_dir=report)
        assert last == datetime(2026, 1, 9)  # the student's file holds times, as pandas wrote them
        frame = pd.read_parquet(data.path("acme/rates:treasury", project_dir=report))
        assert len(frame[frame["ds"] <= last]) == 80
        whole = pl.read_parquet(data.path("acme/rates:treasury", project_dir=report))
        assert whole.filter(pl.col("ds") <= last).height == 80

    def test_it_is_the_same_where_the_pinned_file_is_read(self, work, monkeypatch):
        rates, report = _pin(work, monkeypatch, {"treasury": (_yields(40), "ds", _polars)})
        assert data.as_of("acme/rates:treasury", project_dir=report) == date(2026, 1, 9)  # a column of dates
        location = resolve_module.resolve("acme/rates:treasury", start_dirs=[report])
        assert not location.stands_in and (location.as_of, location.date_col) == ("2026-01-09", "ds")

    def test_a_time_with_a_zone_is_aware_of_it(self, work, monkeypatch):
        zoned = _yields(40).with_columns(pl.col("ds").cast(pl.Datetime("us")).dt.replace_time_zone("America/Chicago"))
        rates, report = _pin(work, monkeypatch, {"treasury": (zoned, "ds", _polars)})
        last = data.as_of("acme/rates:treasury", project_dir=report)
        assert last == datetime(2026, 1, 9, 6, tzinfo=timezone.utc)
        assert pl.read_parquet(data.path("acme/rates:treasury", project_dir=report)).filter(pl.col("ds") <= last).height == 80

    def test_finer_than_a_microsecond_is_the_next_one(self, work, monkeypatch):
        ticks = pl.DataFrame({"t": [1_700_000_000_000_000_001, 1_700_000_000_000_000_501], "x": [0, 1]}).with_columns(pl.col("t").cast(pl.Datetime("ns")))
        rates, report = _pin(work, monkeypatch, {"ticks": (ticks, "t", _polars)})
        last = data.as_of("acme/rates:ticks", project_dir=report)
        assert last == datetime(2023, 11, 14, 22, 13, 20, 1)
        assert pl.read_parquet(data.path("acme/rates:ticks", project_dir=report)).filter(pl.col("t") <= last).height == 2

    def test_none_where_a_pin_has_no_last_date(self, work, monkeypatch):
        codes = pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]})
        rates, report = _pin(work, monkeypatch, {"codes": (codes, None, _polars), "empty": (_yields(1).clear(), "ds", _polars)})
        assert data.as_of("acme/rates:codes", project_dir=report) is None
        assert data.as_of("acme/rates:empty", project_dir=report) is None
        # And for a dataframe of the pipeline one is in, which has no pin
        assert data.as_of("empty", project_dir=rates) is None

    def test_a_chart_is_no_dataframe(self, stood_in):
        report, _ = stood_in
        with pytest.raises(ValueError):
            data.as_of("acme/rates:chart/curve", project_dir=report)
