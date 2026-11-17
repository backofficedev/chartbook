"""Tests for what ``chartbook update`` and ``chartbook snapshot`` say of a dataframe's rows, and the warning for the pandas index column (``docs_src/design/pins-and-rebuilds.md``, step 7).

A pin that moves says, for each dataframe, whether it gained rows or its
earlier rows changed, beside the pin it had. A snapshot says the same
beside the snapshot before it. Both only report: there the change is what
was asked for. And the author of a dataframe whose file has the column
pandas makes of an index with no name is told, by ``chartbook check`` and
by ``chartbook snapshot``, with the two ways out.
"""

import warnings
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import check, config, lock, rowhash, snapshot, standins
from chartbook.cli import main
from chartbook.manifest import load_manifest
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _yields(days: int, start: date = date(2025, 12, 1), revised: date = None) -> pl.DataFrame:
    """Two series a day; *revised* changes one value on that day."""
    when = [start + timedelta(days=i) for i in range(days) for _ in range(2)]
    frame = pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("T{}", pl.int_range(pl.len()) % 2),
        y=(4.0 + pl.int_range(pl.len()) * 0.01),
    )
    if revised is not None:
        frame = frame.with_columns(
            pl.when((pl.col("ds") == revised) & (pl.col("unique_id") == "T1")).then(pl.col("y") + 0.5).otherwise(pl.col("y")).alias("y")
        )
    return frame


MANIFEST = {
    "project": {"id": "acme/rates"},
    "dataframes": {
        "treasury": {"path": "./_data/treasury.parquet", "date_col": "ds", "docs": "d"},
        "codes": {"path": "./_data/codes.parquet", "docs": "d"},
    },
}

CODES = pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]})


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


@pytest.fixture
def rates(work, store):
    """An upstream, built and declared ready once: 40 days of yields and a table of codes."""
    directory = work / "rates"
    _write_manifest(directory, MANIFEST)
    (directory / "_data").mkdir()
    _yields(40).write_parquet(directory / "_data" / "treasury.parquet")
    CODES.write_parquet(directory / "_data" / "codes.parquet")
    commit_pipeline(directory)
    snapshot.make(directory, store=store)
    return directory


@pytest.fixture
def report(work, rates, store):
    directory = work / "report"
    _write_manifest(directory, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    assert not lock.pin(directory, store).problems
    return directory


def _again(rates: Path, store, treasury: pl.DataFrame = None, codes: pl.DataFrame = None, pandas: bool = False):
    """The upstream's owner builds again, at the same commit, and declares it ready."""
    for name, frame in (("treasury", treasury), ("codes", codes)):
        if frame is not None:
            path = rates / "_data" / f"{name}.parquet"
            frame.to_pandas().to_parquet(path, index=False) if pandas else frame.write_parquet(path)
    return snapshot.make(rates, store=store)


class TestUpdate:
    """A pin that moves says what its rows are beside the pin it had."""

    def test_new_rows_and_earlier_rows_unchanged(self, rates, report, store):
        _again(rates, store, _yields(48), pandas=True)
        found = lock.update(report, store=store)
        assert found.rows_said == {"acme/rates:treasury": "16 new rows, through 2026-01-17; earlier rows unchanged"}

    def test_the_command_prints_it_under_the_two_hashes(self, rates, report, store):
        _again(rates, store, _yields(48))
        result = CliRunner().invoke(main, ["update", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        at = lines.index("  acme/rates:treasury")
        assert " -> sha256:" in lines[at + 1]
        assert lines[at + 2] == "    16 new rows, through 2026-01-17; earlier rows unchanged"

    def test_earlier_rows_changed_names_the_period(self, rates, report, store):
        _again(rates, store, _yields(48, revised=date(2025, 12, 14)))
        found = lock.update(report, store=store)
        assert found.rows_said == {
            "acme/rates:treasury": "earlier rows changed: the rows of 2025-12-01 to 2025-12-31 differ; 16 new rows, through 2026-01-17"
        }

    def test_a_row_gone_is_earlier_rows_changed(self, rates, report, store):
        _again(rates, store, _yields(40).filter(pl.col("ds") != date(2026, 1, 3)))
        found = lock.update(report, store=store)
        assert found.rows_said["acme/rates:treasury"] == "earlier rows changed: the rows of 2026-01-01 to 2026-01-09 differ"

    def test_the_same_rows_in_other_bytes(self, rates, report, store):
        _again(rates, store, _yields(40).reverse(), pandas=True)
        found = lock.update(report, store=store)
        assert found.rows_said == {"acme/rates:treasury": "the same rows, in other bytes"}

    def test_a_table_with_no_date_column(self, rates, report, store):
        more = pl.concat([CODES, pl.DataFrame({"code": ["c"], "name": ["Gamma"]})])
        _again(rates, store, codes=more)
        found = lock.update(report, store=store)
        assert found.rows_said == {"acme/rates:codes": "its rows changed (2 rows before, 3 now); it has no date column to tell new rows by"}

    def test_nothing_is_said_of_a_pin_that_did_not_move(self, rates, report, store):
        _again(rates, store, _yields(48))
        found = lock.update(report, store=store)
        assert "acme/rates:codes" not in found.rows_said

    def test_nothing_is_said_where_the_earlier_pin_recorded_no_rows(self, rates, report, store):
        """A lockfile pinned before rows were hashed: there is nothing to tell the rows by, and nothing is said."""
        import json

        path = report / lock.LOCK_FILE
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document["records"]:
            for key in rowhash.FIELDS:
                record.pop(key, None)
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        _again(rates, store, _yields(48))
        found = lock.update(report, store=store)
        assert found.rows_said == {} and not found.problems

    def test_only_the_last_period_is_read_and_once(self, rates, report, store, monkeypatch):
        """What the two records already show to be the same is not hashed again; and what the snapshot found, the update on this machine does not find again."""
        asked = []
        real = rowhash.hash_in
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: asked.append(sorted(options.get("known", ()))) or real(*arguments, **options))
        _again(rates, store, _yields(48))
        assert asked == [["2025-12-01/2025-12-31"]]
        found = lock.update(report, store=store)
        assert found.rows_said and len(asked) == 1


class TestSnapshot:
    """A snapshot says what each dataframe's rows are beside the snapshot before it."""

    def test_new_rows(self, rates, store):
        made = _again(rates, store, _yields(41))
        assert made.made and made.rows_said == [("acme/rates:treasury", "2 new rows, through 2026-01-10; earlier rows unchanged")]
        assert made.rows_beside.made_at < made.snapshot.made_at

    def test_the_command_says_it(self, rates, store):
        _yields(41).write_parquet(rates / "_data" / "treasury.parquet")
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        at = next(i for i, line in enumerate(lines) if line.startswith("  Beside the snapshot before it, made "))
        assert lines[at + 1] == "    acme/rates:treasury: 2 new rows, through 2026-01-10; earlier rows unchanged"

    def test_a_refactor_that_changed_no_number(self, rates, store):
        """Another writer, another order, and a new day of data between the two builds: no earlier row changed."""
        made = _again(rates, store, _yields(41).reverse(), pandas=True)
        assert made.rows_said == [("acme/rates:treasury", "2 new rows, through 2026-01-10; earlier rows unchanged")]

    def test_a_number_that_changed(self, rates, store):
        made = _again(rates, store, _yields(41, revised=date(2025, 12, 14)))
        ((asset, told),) = made.rows_said
        assert asset == "acme/rates:treasury" and told.startswith("earlier rows changed: the rows of 2025-12-01 to 2025-12-31 differ")

    def test_the_same_bytes_make_no_new_snapshot_and_say_so(self, rates, store):
        made = snapshot.make(rates, store=store)
        assert not made.made and made.rows_said == []
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert "No new snapshot: the same bytes and the same pins as the one made " in result.output

    def test_a_first_snapshot_has_nothing_before_it(self, work, store):
        directory = work / "new"
        _write_manifest(directory, {"project": {"id": "acme/new"}, "dataframes": {"t": {"path": "./t.parquet", "date_col": "ds", "docs": "d"}}})
        _yields(3).write_parquet(directory / "t.parquet")
        commit_pipeline(directory)
        made = snapshot.make(directory, store=store)
        assert made.made and made.rows_said == [] and made.rows_beside is None

    def test_what_cannot_be_told_stops_no_snapshot(self, rates, store, monkeypatch):
        monkeypatch.setattr(standins, "rows_compared", lambda *arguments: (_ for _ in ()).throw(RuntimeError("no")))
        made = _again(rates, store, _yields(41))
        assert made.made and made.rows_said == []


class TestThePandasIndexColumn:
    """Row positions left from an earlier step: they shift when a pull has more rows, and no rebuild then meets a pin."""

    def _with_an_index(self, rates: Path, days: int = 40) -> None:
        frame = _yields(days + 5).to_pandas()
        kept = frame[frame["ds"] >= frame["ds"].min() + timedelta(days=5)].sample(frac=1.0, random_state=1)
        kept.to_parquet(rates / "_data" / "treasury.parquet")  # its index: the positions its rows had before, in no order
        assert rowhash.INDEX_COLUMN in pl.read_parquet(rates / "_data" / "treasury.parquet").columns

    def test_snapshot_says_it(self, rates, store):
        self._with_an_index(rates)
        made = snapshot.make(rates, store=store)
        assert made.index_columns == ["acme/rates:treasury"]
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert (
            "  acme/rates:treasury: its file has the column pandas makes of an index with no name (__index_level_0__). "
            "Where that holds row positions, they shift when a pull has more rows, and no rebuild then has the rows a "
            "pin of it names. to_parquet(index=False) drops it; reset_index() keeps it as a column with a name." in result.output
        )

    def test_check_warns_and_is_no_problem(self, rates, store):
        self._with_an_index(rates)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            problems = check.run_checks(load_manifest(rates), rates)
        said = [str(warning.message) for warning in caught if "__index_level_0__" in str(warning.message)]
        assert len(said) == 1 and said[0].startswith(f"{rates / 'chartbook.toml'}: [dataframes.treasury] path: its file has the column pandas makes")
        assert not [problem for problem in problems if "index" in problem.message]

    def test_a_file_with_no_such_column_says_nothing(self, rates, store):
        made = snapshot.make(rates, store=store)
        assert made.index_columns == []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check.run_checks(load_manifest(rates), rates)
        assert not [warning for warning in caught if "__index_level_0__" in str(warning.message)]

    def test_an_index_with_a_name_is_a_column_with_a_name(self, rates, store):
        _yields(40).to_pandas().set_index("ds").to_parquet(rates / "_data" / "treasury.parquet")
        assert snapshot.make(rates, store=store).index_columns == []

    def test_a_file_that_is_not_built_or_no_table_is_passed_over(self, rates, store):
        (rates / "_data" / "treasury.parquet").write_bytes(b"not parquet")
        (rates / "_data" / "codes.parquet").unlink()
        assert check.check_index_columns(load_manifest(rates), rates) == []
