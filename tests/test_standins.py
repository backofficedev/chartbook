"""Tests for a pin met by a rebuild (``docs_src/design/pins-and-rebuilds.md``, step 5).

The story: a class with no shared store. The author pins a snapshot of an
upstream. A student builds that upstream themselves, at the commit the
lockfile names, a week later: the same rows in other bytes, and newer rows
after the pin's last date. Their snapshot **stands in** for the one the
lockfile names. A value revised in the past does not, and the check names
the period.

The check is cheapest first: the same file, then the same rows up to the
pin's last date, among your snapshots of that pipeline at that commit.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, config, lineage, lock, rowhash, snapshot, standins
from chartbook import resolve as resolve_module
from chartbook.cli import main
from chartbook.errors import AssetNotPinnedError
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline


def _write_manifest(directory: Path, table: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _yields(days: int, start: date = date(2025, 12, 1), revised: date = None) -> pl.DataFrame:
    """Two series a day; *revised* changes one value on that day in its ninth decimal place."""
    when = [start + timedelta(days=i) for i in range(days) for _ in range(2)]
    frame = pl.DataFrame({"ds": when}).with_columns(
        unique_id=pl.format("T{}", pl.int_range(pl.len()) % 2),
        y=(4.0 + pl.int_range(pl.len()) * 0.01),
    )
    if revised is not None:
        frame = frame.with_columns(
            pl.when((pl.col("ds") == revised) & (pl.col("unique_id") == "T1")).then(pl.col("y") + 1e-9).otherwise(pl.col("y")).alias("y")
        )
    return frame


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
def rates(work):
    """The upstream as its author built it: 40 days of yields, a table of codes, a chart and a model."""
    directory = work / "rates"
    _write_manifest(directory, MANIFEST)
    (directory / "_data").mkdir()
    _yields(40).write_parquet(directory / "_data" / "treasury.parquet")
    pl.DataFrame({"code": ["a", "b"], "name": ["Alpha", "Beta"]}).write_parquet(directory / "_data" / "codes.parquet")
    (directory / "_output").mkdir()
    (directory / "_output" / "curve.html").write_bytes(b"<html>the author's</html>")
    (directory / "_models").mkdir()
    (directory / "_models" / "ar1.joblib").write_bytes(b"weights")
    commit_pipeline(directory)
    return directory


@pytest.fixture
def report(work, rates, monkeypatch):
    """A report that depends on it, pinned by its author in the author's own store."""
    directory = work / "report"
    _write_manifest(directory, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    author = FolderStore(work / "author")
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
    snapshot.make(rates, store=author)
    assert not lock.pin(directory, author).problems
    return directory


@pytest.fixture
def student(work, monkeypatch):
    """The student's machine: another store, with nothing of the author's in it."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "student-cache"))
    resolve_module._said_stand_ins.clear()
    return FolderStore(work / "student")


def _rebuild(rates: Path, store, frame: pl.DataFrame, index: bool = False):
    """The student builds the upstream at the same commit: these rows, written by pandas, and a chart drawn anew."""
    frame.to_pandas().to_parquet(rates / "_data" / "treasury.parquet", index=index)
    (rates / "_output" / "curve.html").write_bytes(b"<html>the student's</html>")
    return snapshot.make(rates, store=store).snapshot


class TestARebuildAWeekLater:
    """The same rows in other bytes, and eight newer days: the pin is met."""

    @pytest.fixture
    def built(self, report, rates, student):
        return _rebuild(rates, student, _yields(48))

    def test_the_bytes_are_other_bytes(self, report, built, student):
        pinned = lock.read_lock(report).assets["acme/rates:treasury"]
        assert built.assets["treasury"]["content_hash"] != pinned["content_hash"]
        assert not student.has(pinned["content_hash"])
        assert built.commit == lock.read_lock(report).dependencies[0]["location"]["commit"]

    def test_the_check_passes(self, report, built, student):
        checked = lock.verify(report, student)
        assert checked.problems == [], [problem.message for problem in checked.problems]
        assert checked.pins == 3 and checked.by_your_build == 1
        stood = checked.stood_in["acme/rates"]
        assert stood.stands_in and stood.snapshot.made_at == built.made_at
        met = stood.met["acme/rates:treasury"]
        assert (met.by, met.as_of, met.newer) == ("rows", "2026-01-09", 16)
        # The table of codes and the model came out in the same bytes: met by the file
        assert stood.met["acme/rates:codes"].by == "file" and stood.met["acme/rates:model/ar1"].by == "file"

    def test_the_command_says_which_build_and_how_far(self, report, built, student):
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"acme/rates: read from your own build of {built.commit[:7]}",
            "  treasury: the pinned rows, through 2026-01-09; 16 newer rows",
            "3 pin(s) of 1 dependency: 2 in the store, 1 met by your own build. Nothing written.",
        ]

    def test_it_writes_nothing_in_the_project_or_the_store(self, report, built, student, work):
        def listing(folder: Path) -> list:
            return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file())

        before = listing(report), listing(work / "student")
        assert CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)]).exit_code == 0
        assert (listing(report), listing(work / "student")) == before
        # What it found is remembered in this machine's cache folder
        assert list((work / "student-cache" / "rows" / "met").glob("*.json"))

    def test_the_table_is_hashed_once(self, report, built, student, monkeypatch):
        assert lock.verify(report, student).problems == []
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: pytest.fail("hashed again"))
        assert lock.verify(report, student).problems == []
        assert assets.path("acme/rates:treasury", project_dir=report).is_file()

    def test_a_read_gives_your_build_and_says_so_once(self, report, built, student, rates, capsys):
        path = assets.path("acme/rates:treasury", project_dir=report)
        assert rates not in path.parents and pl.read_parquet(path).height == 96  # the file as it is, in the store
        assets.path("acme/rates:treasury", project_dir=report)
        said = capsys.readouterr().err
        assert said.count(f"acme/rates: read from your own build of {built.commit[:7]}") == 1
        location = resolve_module.resolve("acme/rates:treasury", start_dirs=[report])
        assert location.stands_in and (location.as_of, location.date_col) == ("2026-01-09", "ds")

    def test_what_came_out_in_the_same_bytes_is_read_as_any_pin(self, report, built, student):
        location = resolve_module.resolve("acme/rates:codes", start_dirs=[report])
        assert not location.stands_in and location.content_hash == lock.read_lock(report).assets["acme/rates:codes"]["content_hash"]

    def test_the_chart_is_your_own(self, report, built, student):
        assert assets.path("acme/rates:chart/curve", project_dir=report).read_bytes() == b"<html>the student's</html>"

    def test_pin_leaves_the_lockfile_and_says_it(self, report, built, student):
        before = (report / lock.LOCK_FILE).read_bytes()
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        assert (report / lock.LOCK_FILE).read_bytes() == before
        assert (
            f"acme/rates: 2 already pinned, 1 met by your own build\n"
            f"  Read from your own build of {built.commit[:7]}.\n"
            f"  treasury: the pinned rows, through 2026-01-09; 16 newer rows\n" in result.output
        )
        assert result.output.rstrip().endswith("chartbook.lock is unchanged.")

    def test_lineage_says_which_build_stands_in(self, report, built, student):
        walked = lineage.walk(report, student)
        (node,) = walked.root.children
        assert node.kind == "snapshot" and node.made_at == built.made_at and node.stands_in
        assert walked.gaps() == []
        result = CliRunner().invoke(main, ["lineage", "--project-dir", str(report)])
        assert result.exit_code == 0, result.output
        assert "your build stands in for the pinned snapshot" in result.output

    def test_a_snapshot_of_the_report_is_not_refused(self, report, built, student):
        _write_manifest(
            report,
            {
                "project": {"id": "acme/report"},
                "dependencies": {"acme/rates": {"path": "../rates"}},
                "dataframes": {"summary": {"path": "./_data/summary.parquet", "docs": "d"}},
            },
        )
        (report / "_data").mkdir()
        pl.DataFrame({"x": [1]}).write_parquet(report / "_data" / "summary.parquet")
        (report / ".gitignore").write_text("_data/\n", encoding="utf-8", newline="\n")
        commit_pipeline(report)
        assert snapshot.lineage_gaps(report, student) == []
        assert snapshot.make(report, store=student).made

    def test_the_newest_build_that_meets_it_is_the_one(self, report, built, student, rates):
        later = _rebuild(rates, student, _yields(50))
        assert lock.verify(report, student).stood_in["acme/rates"].snapshot.made_at == later.made_at
        # And one that does not meet it is passed over for one that does
        _rebuild(rates, student, _yields(50, revised=date(2025, 12, 14)))
        assert lock.verify(report, student).stood_in["acme/rates"].snapshot.made_at == later.made_at


class TestTheSameRowsInOtherBytes:

    def test_nothing_is_read_when_the_two_records_say_it(self, report, rates, student, monkeypatch):
        """Each period by the same timestamps with the same hash: your snapshot's own record is enough."""
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: pytest.fail("the table was read"))
        _rebuild(rates, student, _yields(40))
        checked = lock.verify(report, student)
        assert checked.problems == [] and checked.stood_in["acme/rates"].met["acme/rates:treasury"].newer == 0
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert "  treasury: the pinned rows, through 2026-01-09, in other bytes" in result.output

    def test_only_the_last_period_is_read_when_the_rest_are_as_they_were(self, report, rates, student, monkeypatch):
        asked = []
        real = rowhash.hash_in
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: asked.append(options.get("known")) or real(*arguments, **options))
        _rebuild(rates, student, _yields(48))
        assert lock.verify(report, student).problems == []
        assert asked == [["2025-12-01/2025-12-31"]]  # December is in both records; January grew


class TestTheSourceChangedItsPast:
    """An old value revised: a real difference, and the check names the period."""

    @pytest.fixture
    def built(self, report, rates, student):
        return _rebuild(rates, student, _yields(48, revised=date(2025, 12, 14)))

    def test_the_check_exits_one_and_names_the_period(self, report, built, student):
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert result.exit_code == 1
        assert (
            f"acme/rates: your build of {built.commit[:7]} does not match the pin\n"
            f"  treasury: the rows of 2025-12-01 to 2025-12-31 differ\n"
            f"  To read your build instead: chartbook update acme/rates\n" in result.output
        )
        assert "1 problem(s)" in result.output and "does not have it" not in result.output

    def test_pin_says_the_same_and_exits_one(self, report, built, student):
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 1
        assert "acme/rates: 2 already pinned, 1 not met by your own build" in result.output
        assert "  differs: acme/rates:treasury: the rows of 2025-12-01 to 2025-12-31 differ" in result.output
        assert (
            f"  Your build of {built.commit[:7]} does not match the pin. To read your build instead: "
            f"chartbook update acme/rates" in result.output
        )

    def test_a_read_stops_with_the_period(self, report, built, student):
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=report)
        assert raised.value.reason == "differs"
        said = str(raised.value)
        assert f"Your build of 'acme/rates' at {built.commit[:7]} does not match the pin: the rows of 2025-12-01 to 2025-12-31 differ" in said
        assert "`chartbook update acme/rates`" in said

    def test_update_reads_your_build(self, report, built, student):
        assert not lock.update(report, store=student).problems
        assert lock.verify(report, student).problems == []
        assert pl.read_parquet(assets.path("acme/rates:treasury", project_dir=report)).height == 96


class TestOtherDifferences:

    def test_a_row_that_arrived_late(self, report, rates, student):
        late = pl.DataFrame({"ds": [date(2025, 12, 5)], "unique_id": ["T9"], "y": [1.0]}, schema=_yields(1).schema)
        _rebuild(rates, student, pl.concat([_yields(48), late]))
        (problem,) = lock.verify(report, student).problems
        assert "treasury: the rows of 2025-12-01 to 2025-12-31 differ" in problem.message

    def test_a_row_on_a_day_the_pin_did_not_have(self, report, rates, student, work, monkeypatch):
        """Between two of its periods: in no period, and so a row the pin did not have."""
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        gapped = pl.concat([_yields(10, start=date(2024, 12, 1)), _yields(10, start=date(2025, 3, 1))])
        gapped.write_parquet(rates / "_data" / "treasury.parquet")
        snapshot.make(rates, store=FolderStore(work / "author"))
        assert not lock.update(report, store=FolderStore(work / "author")).problems
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        between = pl.DataFrame({"ds": [date(2025, 1, 15)], "unique_id": ["T0"], "y": [1.0]}, schema=gapped.schema)
        _rebuild(rates, student, pl.concat([gapped, between]))
        (problem,) = lock.verify(report, student).problems
        assert "treasury: it has 1 row up to 2025-03-10 that the pin did not have" in problem.message

    def test_a_model_is_met_by_the_same_file_only(self, report, rates, student):
        (rates / "_models" / "ar1.joblib").write_bytes(b"trained again")
        _rebuild(rates, student, _yields(48))
        (problem,) = lock.verify(report, student).problems
        assert "model/ar1: a model is met by the same file only, and your build's is another" in problem.message
        assert "treasury" not in problem.message  # which your build does meet

    def test_a_table_with_no_date_column_is_met_by_all_its_rows(self, report, rates, student):
        pl.DataFrame({"name": ["Beta", "Alpha"], "code": ["b", "a"]}).to_pandas().to_parquet(rates / "_data" / "codes.parquet", index=False)
        _rebuild(rates, student, _yields(48))
        checked = lock.verify(report, student)
        assert checked.problems == [] and checked.stood_in["acme/rates"].met["acme/rates:codes"].by == "rows"

    def test_a_table_with_no_date_column_and_another_row(self, report, rates, student):
        """It has no last date for new rows to come after: one more row is a difference."""
        pl.DataFrame({"code": ["a", "b", "c"], "name": ["Alpha", "Beta", "Gamma"]}).write_parquet(rates / "_data" / "codes.parquet")
        _rebuild(rates, student, _yields(48))
        (problem,) = lock.verify(report, student).problems
        assert "codes: its rows differ" in problem.message and "treasury" not in problem.message

    def test_the_pandas_index_column_is_named_as_a_likely_cause(self, report, rates, student, work, monkeypatch):
        """Row positions left from an earlier step shift when a pull has more rows, and no row is then the row it was."""

        def melted(days: int):
            # One series after the other, each row with its position: the second series' move when the first grows
            return _yields(days).to_pandas().sort_values(["unique_id", "ds"]).reset_index(drop=True)

        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        melted(40).to_parquet(rates / "_data" / "treasury.parquet", index=True)
        assert rowhash.INDEX_COLUMN in pl.read_parquet(rates / "_data" / "treasury.parquet").columns
        snapshot.make(rates, store=FolderStore(work / "author"))
        assert not lock.update(report, store=FolderStore(work / "author")).problems
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        melted(48).to_parquet(rates / "_data" / "treasury.parquet", index=True)
        (rates / "_output" / "curve.html").write_bytes(b"<html>the student's</html>")
        snapshot.make(rates, store=student)
        (problem,) = lock.verify(report, student).problems
        assert "treasury: the rows of 2025-12-01 to 2025-12-31 and 2026-01-01 to 2026-01-09 differ" in problem.message
        assert "treasury: has the column pandas makes of an index with no name (__index_level_0__)" in problem.message
        assert "to_parquet(index=False)" in problem.message and "reset_index()" in problem.message

    def test_a_pin_whose_rows_were_not_hashed(self, report, rates, student, work, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        listed = _yields(40).with_columns(pl.concat_list("y", "y").alias("pair"))
        listed.write_parquet(rates / "_data" / "treasury.parquet")
        snapshot.make(rates, store=FolderStore(work / "author"))
        assert not lock.update(report, store=FolderStore(work / "author")).problems
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        listed.to_pandas().to_parquet(rates / "_data" / "treasury.parquet", index=False)
        (rates / "_output" / "curve.html").write_bytes(b"<html>the student's</html>")
        snapshot.make(rates, store=student)
        (problem,) = lock.verify(report, student).problems
        assert "treasury: only the same file meets it, since its rows are not hashed (column 'pair' is List" in problem.message

    def test_a_pin_from_before_rows_were_hashed(self, report, rates, student):
        path = report / lock.LOCK_FILE
        document = json.loads(path.read_text(encoding="utf-8"))
        for record in document["records"]:
            for key in ("rows", "as_of", "row_count"):
                record.pop(key, None)
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        _rebuild(rates, student, _yields(48))
        (problem,) = lock.verify(report, student).problems
        assert "treasury: only the same file meets it, since the pin records no rows" in problem.message


class TestWithNoBuildOfYours:

    def test_it_says_the_bytes_are_not_there_as_before(self, report, student):
        checked = lock.verify(report, student)
        assert len(checked.problems) == 3 and all("does not have it" in problem.message for problem in checked.problems)
        assert checked.stood_in == {}

    def test_a_build_of_another_commit_is_not_looked_at(self, report, rates, student):
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# a later commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)
        _rebuild(rates, student, _yields(48))
        checked = lock.verify(report, student)
        # The table of codes and the model are there by their bytes; the yields are not, and nothing stands in
        (problem,) = checked.problems
        assert problem.asset == "acme/rates:treasury" and "does not have it" in problem.message

    def test_where_the_store_is_shared_nothing_is_looked_for(self, report, work, monkeypatch):
        """The same file: the cheapest check, and a team with a shared store stops there every time."""
        monkeypatch.setattr(standins, "find", lambda *arguments, **options: pytest.fail("looked for a stand-in"))
        checked = lock.verify(report, FolderStore(work / "author"))
        assert checked.problems == [] and checked.stood_in == {} and checked.by_your_build == 0
