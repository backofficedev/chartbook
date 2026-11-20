"""Tests for a dataframe's rows in a snapshot's record and in a lockfile (``docs_src/design/pins-and-rebuilds.md``, step 4).

A snapshot records, for each dataframe, the hash of its rows by period
beside the hash of its bytes: ``date_col``, ``as_of``, ``rows`` and
``row_count``. A pin copies them from the snapshot it is made from. How
the rows are hashed is in ``tests/test_rowhash.py`` and
``tests/test_rows_by_period.py``; this is where the record gets them, and
when they are worked out again.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, rowhash, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline, pin_from_snapshots, update_from_snapshots


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _yields(days: int, start: date = date(2025, 12, 1)) -> pl.DataFrame:
    """A small table of yields, two series a day."""
    when = [start + timedelta(days=i) for i in range(days) for _ in range(2)]
    return pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("T{}", pl.int_range(pl.len()) % 2),
        y=(4.0 + pl.int_range(pl.len()) * 0.01),
    )


MANIFEST = {
    "project": {"id": "acme/rates"},
    "dataframes": {
        "treasury": {"path": "./_data/treasury.parquet", "date_col": "ds", "docs": "d"},
        "codes": {"path": "./_data/codes.parquet", "docs": "d"},
    },
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
    "models": {"ar1": {"path": "./_models/ar1.joblib"}},
}


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    return FolderStore(work / "store")


@pytest.fixture
def rates(work):
    """An upstream: a dated dataframe, one with no date column, a chart and a model."""
    directory = work / "rates"
    _write_manifest(directory, MANIFEST)
    (directory / "_data").mkdir()
    _yields(40).write_parquet(directory / "_data" / "treasury.parquet")
    pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]}).write_parquet(directory / "_data" / "codes.parquet")
    (directory / "_output").mkdir()
    (directory / "_output" / "curve.html").write_bytes(b"<html>curve</html>")
    (directory / "_models").mkdir()
    (directory / "_models" / "ar1.joblib").write_bytes(b"weights")
    commit_pipeline(directory)
    return directory


@pytest.fixture
def report(work, rates):
    directory = work / "report"
    _write_manifest(directory, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    return directory


class TestASnapshotsRecord:

    def test_a_dated_dataframe_has_its_rows_by_period(self, rates, store):
        taken = snapshot.make(rates, store=store).snapshot
        record = taken.assets["treasury"]
        assert record["date_col"] == "ds" and record["as_of"] == "2026-01-09" and record["row_count"] == 80
        assert list(record["rows"]) == ["2025-12-01/2025-12-31", "2026-01-01/2026-01-09"]
        frame = _yields(40)
        assert record["rows"]["2026-01-01/2026-01-09"] == rowhash.hash_frame(frame.filter(pl.col("ds") >= date(2026, 1, 1)), "ds")
        # After the hash of its bytes, in the order the design shows them
        assert list(record)[-5:] == ["size_bytes", "date_col", "as_of", "rows", "row_count"]

    def test_the_last_date_is_the_datas_own(self, rates, store):
        """Never the clock's: the snapshot is made today, and the table ends where it ends."""
        taken = snapshot.make(rates, store=store).snapshot
        assert taken.assets["treasury"]["as_of"] == "2026-01-09" and not taken.made_at.startswith("2026-01-09")

    def test_one_with_no_date_column_has_one_hash(self, rates, store):
        record = snapshot.make(rates, store=store).snapshot.assets["codes"]
        assert list(record["rows"]) == ["all"] and record["row_count"] == 2
        assert "date_col" not in record and "as_of" not in record

    def test_only_a_dataframe_has_them(self, rates, store):
        taken = snapshot.make(rates, store=store).snapshot
        for name in ("chart/curve", "model/ar1"):
            assert not set(rowhash.FIELDS) & set(taken.assets[name])

    def test_it_fits_its_schema(self, rates, store):
        taken = snapshot.make(rates, store=store).snapshot
        document = json.loads(taken.path.read_text(encoding="utf-8"))
        jsonschema.validate(document, json.loads(snapshot.schema_path().read_text(encoding="utf-8")))

    def test_a_file_that_is_no_table_says_nothing(self, rates, store):
        (rates / "_data" / "codes.parquet").write_bytes(b"not parquet at all")
        made = snapshot.make(rates, store=store)
        record = made.snapshot.assets["codes"]
        assert record["content_hash"] and not set(rowhash.FIELDS) & set(record)
        assert made.not_hashed == []

    def test_a_table_whose_rows_are_not_hashed_says_why(self, rates, store):
        pl.DataFrame({"code": ["a"], "vector": [[0.1, 0.2]]}).write_parquet(rates / "_data" / "codes.parquet")
        made = snapshot.make(rates, store=store)
        record = made.snapshot.assets["codes"]
        assert "rows" not in record and "column 'vector' is List" in record["not_hashed"]
        assert made.not_hashed == [("acme/rates:codes", record["not_hashed"])]

    def test_the_command_says_it(self, rates, store):
        pl.DataFrame({"code": ["a"], "vector": [[0.1, 0.2]]}).write_parquet(rates / "_data" / "codes.parquet")
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert result.exit_code == 0, result.output
        assert (
            "  rows not hashed: acme/rates:codes (column 'vector' is List(Float64), and a rows hash takes no such "
            "column yet). A pin of it is met by the same file, and by no rebuild." in result.output
        )

    def test_a_declared_date_column_that_holds_no_dates(self, rates, store):
        table = json.loads(json.dumps(MANIFEST))
        table["dataframes"]["codes"]["date_col"] = "code"
        _write_manifest(rates, table)
        commit_pipeline(rates)
        record = snapshot.make(rates, store=store).snapshot.assets["codes"]
        # Text is read as dates where it can be: none of it can, so every row is one with no date
        assert record["rows"].keys() == {"none"} and record["date_col"] == "code" and "as_of" not in record


class TestWhenTheRowsAreHashedAgain:
    """Hashing reads every row, so the same bytes are not hashed twice."""

    def _later_commit(self, rates: Path) -> None:
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# another commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)

    def test_the_same_bytes_at_a_later_commit_are_not(self, rates, store, monkeypatch):
        first = snapshot.make(rates, store=store).snapshot
        self._later_commit(rates)
        monkeypatch.setattr(rowhash, "fields_of", lambda *arguments, **options: pytest.fail("hashed again"))
        second = snapshot.make(rates, store=store).snapshot
        assert second.commit != first.commit
        for name in ("treasury", "codes"):
            assert {k: second.assets[name][k] for k in rowhash.FIELDS if k in second.assets[name]} == {
                k: first.assets[name][k] for k in rowhash.FIELDS if k in first.assets[name]
            }

    def test_other_bytes_are(self, rates, store):
        first = snapshot.make(rates, store=store).snapshot
        _yields(42).write_parquet(rates / "_data" / "treasury.parquet")
        second = snapshot.make(rates, store=store).snapshot
        assert second.assets["treasury"]["as_of"] == "2026-01-11"
        assert second.assets["treasury"]["rows"]["2025-12-01/2025-12-31"] == first.assets["treasury"]["rows"]["2025-12-01/2025-12-31"]
        assert second.assets["codes"]["rows"] == first.assets["codes"]["rows"]

    def test_another_date_column_is(self, rates, store):
        first = snapshot.make(rates, store=store).snapshot
        table = json.loads(json.dumps(MANIFEST))
        del table["dataframes"]["treasury"]["date_col"]
        _write_manifest(rates, table)
        commit_pipeline(rates)
        second = snapshot.make(rates, store=store).snapshot
        assert list(second.assets["treasury"]["rows"]) == ["all"] and "date_col" not in second.assets["treasury"]
        assert first.assets["treasury"]["content_hash"] == second.assets["treasury"]["content_hash"]

    def test_a_snapshot_from_before_rows_were_hashed_is_made_again(self, rates, store):
        """The same commit and the same bytes: a new one all the same, to say its rows."""
        first = snapshot.make(rates, store=store).snapshot
        document = json.loads(first.path.read_text(encoding="utf-8"))
        for record in document["records"]:
            for key in rowhash.FIELDS:
                if key != "date_col":
                    record.pop(key, None)
        first.path.chmod(0o644)
        first.path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        again = snapshot.make(rates, store=store)
        assert again.made and again.snapshot.commit == first.commit and again.snapshot.made_at != first.made_at
        assert "rows" in again.snapshot.assets["treasury"]
        # And once it says them, the same bytes make no new snapshot
        assert not snapshot.make(rates, store=store).made


    def test_a_date_column_declared_since_is(self, rates, store, monkeypatch):
        """What the message invites: a table with no hash for want of a date column is hashed once its entry names one."""
        monkeypatch.setattr(rowhash, "MOST_BYTES", 2_000)  # under what the table counts for whole
        table = json.loads(json.dumps(MANIFEST))
        del table["dataframes"]["treasury"]["date_col"]
        _write_manifest(rates, table)
        commit_pipeline(rates)
        first = snapshot.make(rates, store=store)
        assert first.snapshot.assets["treasury"]["not_hashed"].startswith("it has no date column, and its rows count for")
        assert "date_col" not in first.snapshot.assets["treasury"]
        _write_manifest(rates, MANIFEST)
        commit_pipeline(rates)
        second = snapshot.make(rates, store=store)
        record = second.snapshot.assets["treasury"]
        assert second.not_hashed == [] and record["date_col"] == "ds" and len(record["rows"]) == 2
        assert record["content_hash"] == first.snapshot.assets["treasury"]["content_hash"]

    def test_why_a_table_has_no_hash_is_taken_from_an_earlier_snapshot_too(self, rates, store, monkeypatch):
        """The same bytes, dated by the same column: what was said of their rows is said again, and nothing is read."""
        monkeypatch.setattr(rowhash, "PERIOD_BYTES", 20)
        monkeypatch.setattr(rowhash, "MOST_BYTES", 40)  # under what one day of the one counts for, and the whole of the other
        first = snapshot.make(rates, store=store)
        assert [asset for asset, _ in first.not_hashed] == ["acme/rates:codes", "acme/rates:treasury"]
        assert first.snapshot.assets["treasury"]["date_col"] == "ds" and "date_col" not in first.snapshot.assets["codes"]
        monkeypatch.undo()
        monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
        monkeypatch.setattr(rowhash, "fields_of", lambda *arguments, **options: pytest.fail("hashed again"))
        again = snapshot.make(rates, store=store)
        assert not again.made and [asset for asset, _ in again.not_hashed] == ["acme/rates:codes", "acme/rates:treasury"]

    def test_one_whose_date_column_dates_nothing_is_not_hashed_again(self, rates, store, monkeypatch):
        """A column the table does not have, and a column of numbers: hashed as a table with no dates, once."""
        table = json.loads(json.dumps(MANIFEST))
        table["dataframes"]["treasury"]["date_col"] = "y"
        table["dataframes"]["codes"]["date_col"] = "nowhere"
        _write_manifest(rates, table)
        commit_pipeline(rates)
        first = snapshot.make(rates, store=store).snapshot
        assert list(first.assets["treasury"]["rows"]) == ["all"] and "date_col" not in first.assets["treasury"]
        self._later_commit(rates)
        monkeypatch.setattr(rowhash, "fields_of", lambda *arguments, **options: pytest.fail("hashed again"))
        second = snapshot.make(rates, store=store).snapshot
        assert second.commit != first.commit and second.assets["treasury"]["rows"] == first.assets["treasury"]["rows"]


class TestRowsThatCouldNotBeHashed:
    """A snapshot is of the bytes, and is made whatever becomes of hashing their rows."""

    def _full(self, monkeypatch) -> None:
        def flush(self):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(rowhash._Pieces, "flush", flush)

    def test_no_room_for_scratch_files_stops_no_snapshot(self, rates, store, monkeypatch):
        self._full(monkeypatch)
        made = snapshot.make(rates, store=store)
        assert made.made and made.not_hashed == []
        ((asset, why),) = made.not_hashed_now
        assert asset == "acme/rates:treasury" and "No space left on device" in why
        record = made.snapshot.assets["treasury"]
        assert record["content_hash"] and not {"rows", "not_hashed", "as_of"} & set(record)
        # One that needs no scratch file is hashed all the same
        assert list(made.snapshot.assets["codes"]["rows"]) == ["all"]

    def test_the_command_says_it_and_the_next_one_hashes_them(self, rates, store, monkeypatch):
        self._full(monkeypatch)
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert result.exit_code == 0, result.output
        assert "  rows not hashed this time: acme/rates:treasury (OSError: " in result.output
        assert "Its bytes are in the snapshot; `chartbook snapshot` again hashes its rows." in result.output
        monkeypatch.undo()
        monkeypatch.setenv(config.STORE_ENV_VAR, str(store.root))
        again = snapshot.make(rates, store=store)
        assert again.made and again.not_hashed_now == [] and len(again.snapshot.assets["treasury"]["rows"]) == 2

    def test_a_date_no_record_can_write_stops_none_either(self, rates, store):
        """Seconds written as microseconds: said in the record, as any table whose rows have no hash."""
        far = _yields(4).with_columns(pl.col("ds").cast(pl.Datetime("us")).cast(pl.Int64).mul(1_000_000).cast(pl.Datetime("us")))
        far.write_parquet(rates / "_data" / "treasury.parquet")
        made = snapshot.make(rates, store=store)
        assert made.made and made.not_hashed_now == []
        ((asset, why),) = made.not_hashed
        assert asset == "acme/rates:treasury" and "outside the years 1 to 9999" in why
        assert made.snapshot.assets["treasury"]["date_col"] == "ds"


class TestAFolderReadFromTheStore:
    """A store of ChartBook 0.5 keeps each file once: what stands in for a pin is hashed from there, and has to be the reader's rows."""

    def test_two_partitions_that_are_one_file(self, work, store):
        """polars drops a key's column when it writes, so two partitions can be the same bytes: read once for each, with each one's key."""
        from chartbook.resolve import _held
        from tests.store_of_0_5 import laid_out_as_0_5

        directory = work / "regional"
        _write_manifest(
            directory,
            {"project": {"id": "acme/regional"}, "dataframes": {"sales": {"path": "./_data/sales", "date_col": "ds", "docs": "d"}}},
        )
        for region in ("eu", "us"):
            (directory / "_data" / "sales" / f"region={region}").mkdir(parents=True)
            _yields(3).write_parquet(directory / "_data" / "sales" / f"region={region}" / "part.parquet")
        commit_pipeline(directory)
        taken = snapshot.make(directory, store=store).snapshot
        record = taken.assets["sales"]
        whole = pl.concat([_yields(3).with_columns(region=pl.lit(region)) for region in ("eu", "us")])
        assert record["row_count"] == 12 and record["rows"] == {"2025-12-01/2025-12-03": rowhash.hash_frame(whole, "ds")}
        # In a store of this version each partition has its own file; as 0.5 left it, the two are one
        own = rowhash.Table.at(_held(store, dict(record), taken.pipeline))
        assert len({str(path) for path in own.inside.values()}) == 2 and own.scan().collect().height == 12
        kept = rowhash.Table.at(_held(laid_out_as_0_5(store.root), dict(record), taken.pipeline))
        assert len({str(path) for path in kept.inside.values()}) == 1  # one file in the store, for both
        assert kept.scan().collect().height == 12
        assert rowhash.hash_rows(kept, "ds").fields() == {key: record[key] for key in rowhash.FIELDS if key in record}
        assert rowhash.hash_in(kept, "ds", record["rows"], record["as_of"]).same


class TestTheSchemas:
    """What says a dataframe's rows goes together, and a period is a period."""

    @pytest.fixture
    def pinned(self, rates, report, store):
        pin_from_snapshots(report, store)
        return json.loads((report / lock.LOCK_FILE).read_text(encoding="utf-8"))

    def _refused(self, document: dict, change) -> bool:
        changed = json.loads(json.dumps(document))
        (record,) = [record for record in changed["records"] if record.get("id") == "acme/rates:treasury"]
        change(record)
        try:
            jsonschema.validate(changed, json.loads(lock.schema_path().read_text(encoding="utf-8")))
        except jsonschema.ValidationError:
            return True
        return False

    def test_what_is_written_fits(self, pinned):
        assert not self._refused(pinned, lambda record: None)
        assert not self._refused(pinned, lambda record: [record.pop(key) for key in ("as_of", "rows", "row_count")] and record.update(not_hashed="why"))

    @pytest.mark.parametrize(
        "change",
        [
            lambda record: record["rows"].update(banana="sha256:00"),
            lambda record: record["rows"].update({"2024-01-01": "sha256:00"}),
            lambda record: record["rows"].update(all="sha256:00"),
            lambda record: record.update(not_hashed="why"),
            lambda record: record.update(as_of="last Tuesday"),
            lambda record: record.pop("rows"),
            lambda record: record.pop("row_count"),
            lambda record: record.pop("date_col"),
            lambda record: record.update(rows=["sha256:00"]),
        ],
        ids=[
            "a key that is no period", "one date where two are written", "all beside periods", "rows beside why there are none",
            "a last date that is no date", "a last date and a count of no rows", "rows with no count", "a last date of no column", "rows in a list",
        ],
    )
    def test_nonsense_is_refused(self, pinned, change):
        assert self._refused(pinned, change)


class TestATableInASource:

    def test_a_table_written_out_as_parquet_has_its_rows(self, work, store):
        import duckdb

        directory = work / "warehouse"
        _write_manifest(
            directory,
            {
                "project": {"id": "acme/warehouse"},
                "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                "dataframes": {"treasury": {"source": "local", "table": "treasury", "date_col": "ds", "docs": "d"}},
            },
        )
        (directory / "_data").mkdir()
        frame = _yields(40)  # noqa: F841 - read by DuckDB by its name
        connection = duckdb.connect(str(directory / "_data" / "local.duckdb"))
        connection.sql("create table treasury as select * from frame")
        connection.close()
        commit_pipeline(directory)
        made = snapshot.make(directory, store=store)
        record = made.snapshot.assets["treasury"]
        assert record["location"]["kind"] == "table" and record["content_hash"]
        assert list(record["rows"]) == ["2025-12-01/2025-12-31", "2026-01-01/2026-01-09"] and record["as_of"] == "2026-01-09"
        # The same rows as the file a polars writer made of them
        assert record["rows"]["2025-12-01/2025-12-31"] == rowhash.hash_frame(_yields(40).filter(pl.col("ds") < date(2026, 1, 1)), "ds")


class TestALockfile:

    def test_a_pin_copies_them_from_its_snapshot(self, rates, report, store):
        pin_from_snapshots(report, store)
        (taken,) = snapshot.all_snapshots(store)
        record = lock.read_lock(report).assets["acme/rates:treasury"]
        for key in ("date_col", "as_of", "rows", "row_count"):
            assert record[key] == taken.assets["treasury"][key]
        assert lock.read_lock(report).assets["acme/rates:codes"]["rows"] == taken.assets["codes"]["rows"]
        document = json.loads((report / lock.LOCK_FILE).read_text(encoding="utf-8"))
        jsonschema.validate(document, json.loads(lock.schema_path().read_text(encoding="utf-8")))

    def test_a_period_is_a_line(self, rates, report, store):
        pin_from_snapshots(report, store)
        text = (report / lock.LOCK_FILE).read_text(encoding="utf-8")
        assert '        "2025-12-01/2025-12-31": "sha256:' in text and '      "as_of": "2026-01-09",' in text

    def test_a_moved_pin_changes_its_last_periods_line_and_nothing_before(self, rates, report, store):
        """What a reviewer sees in the lockfile's diff: new rows are the last line, and a revision is a changed line."""
        pin_from_snapshots(report, store)
        before = (report / lock.LOCK_FILE).read_text(encoding="utf-8").splitlines()
        _yields(48).write_parquet(rates / "_data" / "treasury.parquet")
        update_from_snapshots(report, store=store)
        after = (report / lock.LOCK_FILE).read_text(encoding="utf-8").splitlines()
        periods = lambda lines: [line.strip() for line in lines if line.strip().startswith('"20') and "/" in line]  # noqa: E731
        was, now = periods(before), periods(after)
        assert len(was) == len(now) == 2
        assert now[0] == was[0]  # December is as it was
        assert now[1] != was[1] and now[1].startswith('"2026-01-01/2026-01-17"')  # January grew
        assert '      "as_of": "2026-01-17",' in after and '      "row_count": 96' in after

    def test_what_says_why_rows_are_not_hashed_is_copied_too(self, rates, report, store):
        pl.DataFrame({"code": ["a"], "vector": [[0.1, 0.2]]}).write_parquet(rates / "_data" / "codes.parquet")
        pin_from_snapshots(report, store)
        record = lock.read_lock(report).assets["acme/rates:codes"]
        assert "rows" not in record and "column 'vector' is List" in record["not_hashed"]
