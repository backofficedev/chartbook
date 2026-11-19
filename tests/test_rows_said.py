"""Tests for what ``chartbook pin --update`` and ``chartbook snapshot`` say of a dataframe's rows, and the warning for the pandas index column (``docs_src/design/pins-and-rebuilds.md``, step 7).

A pin that moves says, for each dataframe, whether it gained rows or its
earlier rows changed, beside the pin it had. A snapshot says the same
beside the snapshot before it. Both only report: there the change is what
was asked for. And the author of a dataframe whose file has the column
pandas makes of an index with no name is told, by ``chartbook run --check`` and
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
    standins._compared.clear()  # what this process has compared: each test is a process of its own
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
        result = CliRunner().invoke(main, ["pin", "--update", "--project-dir", str(report)])
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
        # Named by its commit and its time: the one before may be another branch's
        commit = snapshot.history(rates, store)[0].commit[:7]
        at = next(i for i, line in enumerate(lines) if line.startswith(f"  Beside the snapshot before it, of {commit}, made "))
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


class _Panic(BaseException):
    """What a panic of polars is to Python: no Exception."""


class TestNothingSaidStopsACommand:
    """Found by review: `chartbook pin --update` stopped when it could not fetch or hash a table for a line of output."""

    @pytest.mark.parametrize(
        "error",
        [RuntimeError("no"), MemoryError(), OverflowError("cannot convert float infinity to integer"), IndexError("no"), _Panic("no")],
        ids=lambda error: type(error).__name__,
    )
    def test_update_moves_the_pin_whatever_becomes_of_what_it_would_say(self, rates, report, store, monkeypatch, error):
        _again(rates, store, _yields(48), pandas=True)
        standins._compared.clear()
        for remembered in (Path(store.root).parent / "cache").rglob("*.json"):
            remembered.unlink()  # nothing remembered of it, as on another machine

        asked = []

        def fails(*arguments, **options):
            asked.append(1)
            raise error

        monkeypatch.setattr(rowhash, "hash_in", fails)
        found = lock.update(report, store=store)
        assert asked == [1]  # the table was to be hashed for the line, and that is what failed
        assert not found.problems and found.rows_said == {}
        assert lock.read_lock(report).assets["acme/rates:treasury"]["row_count"] == 96

    def test_a_store_that_cannot_be_reached_for_the_file(self, rates, report, store, monkeypatch):
        from chartbook import resolve as resolve_module
        from chartbook.store import StoreUnreachableError

        _again(rates, store, _yields(48), pandas=True)
        standins._compared.clear()
        for remembered in (Path(store.root).parent / "cache").rglob("*.json"):
            remembered.unlink()

        asked = []

        def unreachable(*arguments, **options):
            asked.append(1)
            raise StoreUnreachableError("The store cannot be reached to download _data/treasury.parquet")

        monkeypatch.setattr(resolve_module, "_held", unreachable)
        found = lock.update(report, store=store)
        assert asked == [1]
        assert not found.problems and found.rows_said == {}
        assert lock.read_lock(report).assets["acme/rates:treasury"]["row_count"] == 96

    def test_no_table_is_fetched_from_a_store_that_is_not_on_this_machine(self, rates, report, store, monkeypatch):
        """What the two records say between them is still said: a table with no date column has one hash."""
        assert standins.reads_here(store) and not standins.reads_here(object())
        assert standins.reads_here(lock._PutLater(store))  # what a pin wraps a store in reads as the store
        more = pl.concat([CODES, pl.DataFrame({"code": ["c"], "name": ["Gamma"]})])
        _again(rates, store, _yields(48), codes=more, pandas=True)
        standins._compared.clear()
        for remembered in (Path(store.root).parent / "cache").rglob("*.json"):
            remembered.unlink()
        read = []
        real = rowhash.hash_in
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: read.append(1) or real(*arguments, **options))
        monkeypatch.setattr(standins, "reads_here", lambda store: False)
        found = lock.update(report, store=store)
        assert read == []
        assert found.rows_said == {"acme/rates:codes": "its rows changed (2 rows before, 3 now); it has no date column to tell new rows by"}
        assert not found.problems


class TestWhatIsSaidIsTrue:
    """Found by review: lines that were false for the case they were printed in."""

    def _declare(self, rates: Path, treasury: dict) -> None:
        """The upstream's owner changes how the table of yields is declared, and commits."""
        _write_manifest(rates, {**MANIFEST, "dataframes": {**MANIFEST["dataframes"], "treasury": treasury}})
        commit_pipeline(rates)

    def test_a_table_with_no_date_column_and_the_same_rows(self, rates, report, store):
        _again(rates, store, codes=CODES.reverse().select("name", "code"), pandas=True)
        assert lock.update(report, store=store).rows_said == {"acme/rates:codes": "the same rows, in other bytes"}

    def test_the_one_before_is_the_last_of_three(self, rates, store):
        _again(rates, store, _yields(41))
        made = _again(rates, store, _yields(42))
        assert made.rows_said == [("acme/rates:treasury", "2 new rows, through 2026-01-11; earlier rows unchanged")]

    def test_an_entry_that_lost_its_date_column_with_rows_added(self, rates, store):
        """The earlier record is dated, and the table still has the column: new rows are told, with no last date to give."""
        self._declare(rates, {"path": "./_data/treasury.parquet", "docs": "d"})
        made = _again(rates, store, _yields(48))
        assert "date_col" not in made.snapshot.assets["treasury"] and list(made.snapshot.assets["treasury"]["rows"]) == ["all"]
        assert made.rows_said == [("acme/rates:treasury", "16 new rows; earlier rows unchanged")]

    def test_a_table_that_lost_the_column_itself(self, rates, store):
        made = _again(rates, store, _yields(48).rename({"ds": "day"}))
        assert made.rows_said == [
            (
                "acme/rates:treasury",
                "its rows are no longer dated by 'ds', so new rows cannot be told from changed ones (80 rows before, 96 now)",
            )
        ]

    def test_a_date_column_that_is_another_now(self, rates, store):
        """Counted by the earlier record's column; the later one's last date is of another column, and is not given."""
        self._declare(rates, {"path": "./_data/treasury.parquet", "date_col": "ds2", "docs": "d"})
        made = _again(rates, store, _yields(48).with_columns(ds2=pl.col("ds") + timedelta(days=1000)))
        ((_, told),) = made.rows_said
        assert told.endswith("16 new rows") and "through" not in told

    def test_a_date_column_that_was_added(self, work, store):
        directory = work / "plain"
        entry = {"path": "./t.parquet", "docs": "d"}
        _write_manifest(directory, {"project": {"id": "acme/plain"}, "dataframes": {"t": entry}})
        _yields(40).write_parquet(directory / "t.parquet")
        commit_pipeline(directory)
        snapshot.make(directory, store=store)
        _write_manifest(directory, {"project": {"id": "acme/plain"}, "dataframes": {"t": {**entry, "date_col": "ds"}}})
        commit_pipeline(directory)
        _yields(40).reverse().to_pandas().to_parquet(directory / "t.parquet", index=False)
        assert snapshot.make(directory, store=store).rows_said == [("acme/plain:t", "the same rows, in other bytes; now dated by 'ds'")]
        _write_manifest(directory, {"project": {"id": "acme/plain"}, "dataframes": {"t": entry}})
        commit_pipeline(directory)
        snapshot.make(directory, store=store)
        _write_manifest(directory, {"project": {"id": "acme/plain"}, "dataframes": {"t": {**entry, "date_col": "ds"}}})
        commit_pipeline(directory)
        _yields(48).write_parquet(directory / "t.parquet")
        assert snapshot.make(directory, store=store).rows_said == [
            ("acme/plain:t", "its rows changed (80 rows before, 96 now); the earlier record had no date column to tell new rows by")
        ]

    def test_a_table_that_had_no_rows(self, work, store):
        directory = work / "empty"
        _write_manifest(directory, {"project": {"id": "acme/empty"}, "dataframes": {"t": {"path": "./t.parquet", "date_col": "ds", "docs": "d"}}})
        _yields(40).head(0).write_parquet(directory / "t.parquet")
        commit_pipeline(directory)
        snapshot.make(directory, store=store)
        _yields(40).write_parquet(directory / "t.parquet")
        assert snapshot.make(directory, store=store).rows_said == [("acme/empty:t", "it had no rows, and has 80 now")]

    def test_rows_with_no_date_that_the_earlier_one_had_none_of(self, rates, store):
        undated = pl.DataFrame({"ds": [None, None], "unique_id": ["T8", "T9"], "y": [0.5, 0.6]}, schema=_yields(1).schema)
        made = _again(rates, store, pl.concat([_yields(40), undated]))
        assert made.rows_said == [
            ("acme/rates:treasury", "earlier rows changed: it has 2 rows with no date, and the earlier one had none")
        ]

    def test_the_index_column_is_named_where_earlier_rows_changed(self, rates, store):
        """Row positions: they shift when a pull has more rows, and every earlier row is then another."""
        def melted(days: int):
            return _yields(days).to_pandas().sort_values(["unique_id", "ds"]).reset_index(drop=True)

        melted(40).to_parquet(rates / "_data" / "treasury.parquet", index=True)
        snapshot.make(rates, store=store)
        melted(48).to_parquet(rates / "_data" / "treasury.parquet", index=True)
        ((_, told),) = snapshot.make(rates, store=store).rows_said
        assert told.startswith("earlier rows changed: the rows of 2025-12-01 to 2025-12-31 and 2026-01-01 to 2026-01-09 differ")
        assert told.endswith(
            ". It has the column pandas makes of an index with no name (__index_level_0__), which may be the whole difference"
        )


class TestWhichFilesTheIndexWarningIsFor:

    def test_a_level_with_no_name_of_an_index_of_two(self, rates, store):
        frame = _yields(40).to_pandas().set_index(["unique_id", "y"]).rename_axis(["unique_id", None])
        frame.to_parquet(rates / "_data" / "treasury.parquet")
        assert "__index_level_1__" in pl.read_parquet(rates / "_data" / "treasury.parquet").columns
        made = snapshot.make(rates, store=store)
        assert made.index_columns == ["acme/rates:treasury"] and made.index_column_names == {"acme/rates:treasury": ["__index_level_1__"]}
        result = CliRunner().invoke(main, ["snapshot", "--project-dir", str(rates), "--no-gc-reminder"])
        assert "acme/rates:treasury: its file has the column pandas makes of an index with no name (__index_level_1__)." in result.output
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check.run_checks(load_manifest(rates), rates)
        assert len([warning for warning in caught if "(__index_level_1__)" in str(warning.message)]) == 1

    def test_a_file_that_is_not_parquet(self, work, store):
        """pandas writes no index into a CSV under that name, and to_parquet(index=False) is no advice for one."""
        directory = work / "text"
        _write_manifest(directory, {"project": {"id": "acme/text"}, "dataframes": {"t": {"path": "./t.csv", "docs": "d"}}})
        (directory / "t.csv").write_text("__index_level_0__,x\n0,1\n1,2\n", encoding="utf-8", newline="\n")
        commit_pipeline(directory)
        assert snapshot.make(directory, store=store).index_columns == []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check.run_checks(load_manifest(directory), directory)
        assert not [warning for warning in caught if "__index_level_0__" in str(warning.message)]

    def test_a_check_that_skips_what_a_build_writes_opens_none_of_it(self, rates, store, monkeypatch):
        _yields(40).to_pandas().sample(frac=1.0, random_state=1).to_parquet(rates / "_data" / "treasury.parquet")
        monkeypatch.setattr(rowhash, "index_columns_of", lambda table: pytest.fail("a built file was opened"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check.run_checks(load_manifest(rates), rates, skip_outputs=True)
        assert not [warning for warning in caught if "__index_level_0__" in str(warning.message)]
