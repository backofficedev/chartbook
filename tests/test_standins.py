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
import os
import stat
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import assets, check, config, lineage, lock, rowhash, snapshot, standins
from chartbook import resolve as resolve_module
from chartbook import store as store_module
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
    standins._compared.clear()  # what this process has compared: each test is a process of its own
    return FolderStore(work / "student")


def _said(built) -> str:
    """A build as a line names it: its commit and when it was made."""
    return standins.build_said(built)


def _pin_again(report: Path, rates: Path, work: Path, monkeypatch, frame: pl.DataFrame = None) -> None:
    """The author builds the upstream again, with this table of yields if one is given, and moves the report's pin to it."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
    author = FolderStore(work / "author")
    if frame is not None:
        frame.write_parquet(rates / "_data" / "treasury.parquet")
    snapshot.make(rates, store=author)
    assert not lock.update(report, store=author).problems
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))


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

    def test_the_check_passes(self, report, built, student):
        # The story's premise: other bytes, of the commit that is pinned, in a store without the pinned snapshot
        pinned = lock.read_lock(report).assets["acme/rates:treasury"]
        entry = lock.read_lock(report).dependencies[0]
        assert built.assets["treasury"]["content_hash"] != pinned["content_hash"] and not student.has(pinned["content_hash"])
        assert built.commit == entry["location"]["commit"] and built.made_at != entry["snapshot"]
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
            f"acme/rates: read from your own build of {_said(built)}",
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
        # And not by another process either: what was found is in the cache folder
        standins._compared.clear()
        assert lock.verify(report, student).problems == []

    def test_a_read_gives_your_build_and_says_so_once(self, report, built, student, rates, capsys):
        path = assets.path("acme/rates:treasury", project_dir=report)
        assert rates not in path.parents and pl.read_parquet(path).height == 96  # the file as it is, in the store
        assets.path("acme/rates:treasury", project_dir=report)
        said = capsys.readouterr().err
        assert said.count(f"acme/rates: read from your own build of {_said(built)}. The store does not have") == 1
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
            f"  Read from your own build of {_said(built)}.\n"
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
            f"acme/rates: your build of {_said(built)}, does not match the pin\n"
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
            f"  Your build of {_said(built)}, does not match the pin. To read your build instead: "
            f"chartbook update acme/rates" in result.output
        )

    def test_lineage_says_it_in_one_gap(self, report, built, student):
        (gap,) = snapshot.lineage_gaps(report, student)
        assert gap.startswith(f"acme/rates: your build of {_said(built)}, does not match the pin; treasury: the rows of ")
        assert gap.endswith("To read your build instead: chartbook update acme/rates") and "\n" not in gap

    def test_a_read_stops_with_the_period(self, report, built, student):
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=report)
        assert raised.value.reason == "differs"
        said = str(raised.value)
        assert f"Your build of 'acme/rates' at {_said(built)}, does not match the pin: the rows of 2025-12-01 to 2025-12-31 differ" in said
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
        # `chartbook pin` and a read say it too
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 1 and "  treasury: has the column pandas makes of an index with no name" in result.output
        with pytest.raises(AssetNotPinnedError, match="treasury: has the column pandas makes of an index with no name"):
            assets.path("acme/rates:treasury", project_dir=report)

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

    def test_the_check_says_it_once_and_how_to_build_it(self, report, student, work):
        """What a student sees first: one block for the dependency, and the way on that is theirs."""
        commit = lock.read_lock(report).dependencies[0]["location"]["commit"][:7]
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            f"acme/rates: 3 of its 3 pins are not in the store at {work / 'student'}, and no build of yours at "
            f"{commit} stands in: codes, model/ar1, treasury",
            f"  To build it yourself: in ../rates, `git checkout {commit}` and `chartbook run --snapshot`: a build "
            f"of yours meets a pin by the same file or, for a dataframe, by the same rows up to the pin's last date.",
            "  Where a store is shared: point CHARTBOOK_STORE at the one that has them; in a synced folder, wait "
            "for the sync to finish, here and on the machine that made the pin.",
            "3 problem(s): the pipeline cannot be built from its lockfile alone. Nothing written.",
        ]
        # With no snapshot of it in the store, `chartbook update` has nothing to move to, and is not offered
        assert "chartbook update" not in result.output

    def test_pin_says_them_together_and_how_to_build_it(self, report, student):
        commit = lock.read_lock(report).dependencies[0]["location"]["commit"][:7]
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 1
        (lost,) = [line for line in result.output.splitlines() if line.startswith("  lost")]
        assert lost.startswith("  lost, each of codes, model/ar1, treasury: it is not in the store at ")
        assert f"or build it yourself, in ../rates, `git checkout {commit}` and `chartbook run --snapshot`" in lost

    def test_a_read_says_how_to_build_it(self, report, student):
        commit = lock.read_lock(report).dependencies[0]["location"]["commit"][:7]
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=report)
        assert raised.value.reason == "not_in_store"
        assert f"Or build 'acme/rates' yourself, in ../rates, `git checkout {commit}` and `chartbook run --snapshot`" in str(raised.value)

    def test_the_pinned_snapshot_with_its_file_lost_is_no_build_of_yours(self, report, work):
        """The author's own store, a file gone from it: what is said is that it is not there, not that a build differs."""
        author = FolderStore(work / "author")
        author.delete(lock.read_lock(report).assets["acme/rates:treasury"]["content_hash"])
        checked = lock.verify(report, author)
        (problem,) = checked.problems
        assert problem.kind == "not_in_store" and problem.asset == "acme/rates:treasury"
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
        # The store has a snapshot of it, of that other commit: `chartbook update` has one to move to
        assert checked.not_in_store["acme/rates"][-1] == "  To move the pin to a snapshot the store has: chartbook update acme/rates"

    def test_where_the_store_is_shared_nothing_is_looked_for(self, report, work, monkeypatch):
        """The same file: the cheapest check, and a team with a shared store stops there every time."""
        monkeypatch.setattr(standins, "find", lambda *arguments, **options: pytest.fail("looked for a stand-in"))
        checked = lock.verify(report, FolderStore(work / "author"))
        assert checked.problems == [] and checked.stood_in == {} and checked.by_your_build == 0


def _change_lockfile(report: Path, change) -> None:
    """Change chartbook.lock by hand: *change* is given each record, and each dependency's entry."""
    path = report / lock.LOCK_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    for record in document["records"]:
        change(record)
        for entry in record.get("dependencies") or []:
            change(entry)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def _cut_short(store, content_hash: str) -> None:
    """Leave a file of the store as a sync in progress leaves it: there, and not whole."""
    held = store.files(content_hash).one.location
    os.chmod(held, stat.S_IRUSR | stat.S_IWUSR)
    held.write_bytes(held.read_bytes()[:100])
    store_module._found_whole.clear()  # as another process sees it


class TestAStandInIsWholeOrNotAtAll:
    """A build stands in for a dependency, not for one asset of it."""

    def test_a_build_that_meets_one_pin_and_not_another_is_not_read(self, report, rates, student, capsys):
        # The table of codes: the same rows in other bytes. The yields: revised
        pl.DataFrame({"name": ["Beta", "Alpha"], "code": ["b", "a"]}).to_pandas().to_parquet(rates / "_data" / "codes.parquet", index=False)
        built = _rebuild(rates, student, _yields(48, revised=date(2025, 12, 14)))
        with pytest.raises(AssetNotPinnedError) as raised:
            resolve_module.resolve("acme/rates:codes", start_dirs=[report])
        assert raised.value.reason == "differs"
        assert (
            f"Your build of 'acme/rates' at {_said(built)}, does not match the pin: treasury: the rows of "
            f"2025-12-01 to 2025-12-31 differ. To read your build instead: `chartbook update acme/rates`" in str(raised.value)
        )
        assert "read from your own build" not in capsys.readouterr().err

    def test_the_chart_is_of_the_build_its_table_is_read_from(self, report, rates, student):
        """Two builds of the pinned commit: the older holds the pinned rows, the newer does not."""
        first = _rebuild(rates, student, _yields(48))
        _yields(48, revised=date(2025, 12, 14)).to_pandas().to_parquet(rates / "_data" / "treasury.parquet", index=False)
        (rates / "_output" / "curve.html").write_bytes(b"<html>drawn from revised rows</html>")
        second = snapshot.make(rates, store=student).snapshot
        assert second.made_at > first.made_at
        assert lock.verify(report, student).stood_in["acme/rates"].snapshot.made_at == first.made_at
        assert assets.path("acme/rates:chart/curve", project_dir=report).read_bytes() == b"<html>the student's</html>"
        assert pl.read_parquet(assets.path("acme/rates:treasury", project_dir=report)).height == 96

    def test_an_entry_that_does_not_say_which_pipeline_it_was_pinned_from(self, report, rates, student):
        """As one written before 0.3.0: the folder says whose snapshots they are, for the check as for a read."""

        def forget(entry: dict) -> None:
            entry.pop("pinned_from", None)
            if isinstance(entry.get("location"), dict):
                entry["location"].pop("pipeline", None)

        _change_lockfile(report, forget)
        assert lock.pinned_pipeline(lock.read_lock(report).dependencies[0]) is None
        built = _rebuild(rates, student, _yields(48))
        checked = lock.verify(report, student)
        assert checked.problems == [] and checked.stood_in["acme/rates"].snapshot.made_at == built.made_at
        assert pl.read_parquet(assets.path("acme/rates:treasury", project_dir=report)).height == 96
        assert lineage.walk(report, student).gaps() == []

    def test_a_dependency_pinned_from_its_repository_has_no_stand_in(self, report, rates, student):
        built = _rebuild(rates, student, _yields(48))
        entry = lock.read_lock(report).dependencies[0]
        assert [taken.made_at for taken in standins.candidates(entry, [built])] == [built.made_at]
        from_git = {**entry, "location": {**entry["location"], "kind": "git"}}
        assert standins.candidates(from_git, [built]) == []
        assert lock.your_build(from_git, lock.read_lock(report).assets_of("acme/rates"), student, lambda: [built]) is None

    def test_chartbook_check_agrees_when_the_folder_is_elsewhere(self, report, rates, student, work):
        declared = lock._read_pipeline(report)[1]["acme/rates"]
        _rebuild(rates, student, _yields(48))
        rates.rename(work / "elsewhere")
        said, builds = check._not_on_this_machine(report, "acme/rates", declared, work / "rates")
        assert builds and "so this pipeline builds here" in said
        # And with a build that does not match, it does not
        standins._compared.clear()
        (work / "elsewhere").rename(rates)
        _rebuild(rates, student, _yields(50, revised=date(2025, 12, 14)))
        for taken in snapshot.readable_snapshots(student)[0][:1]:
            snapshot.remove(student, taken)  # the build that matched
        rates.rename(work / "elsewhere")
        said, builds = check._not_on_this_machine(report, "acme/rates", declared, work / "rates")
        assert not builds and "the store does not have all that the lockfile pins of it" in said


class TestPinsNoRebuildMeets:

    def test_a_pinned_table_with_no_rows_is_met_by_the_same_file_only(self, report, rates, student, work, monkeypatch):
        """It has no period, so nothing would tell its columns: any table at all would pass."""
        _pin_again(report, rates, work, monkeypatch, _yields(40).head(0))
        record = lock.read_lock(report).assets["acme/rates:treasury"]
        assert record["rows"] == {} and record.get("as_of") is None and record["date_col"] == "ds"
        pl.DataFrame({"zzz": [1, 2, 3], "other": ["a", "b", "c"]}).write_parquet(rates / "_data" / "treasury.parquet")
        (rates / "_output" / "curve.html").write_bytes(b"<html>the student's</html>")
        snapshot.make(rates, store=student)
        (problem,) = lock.verify(report, student).problems
        assert "treasury: only the same file meets it, since the pinned table had no rows" in problem.message
        # Nor is any table compared with a record of no rows
        with pytest.raises(rowhash.NotHashed, match="holds no rows"):
            rowhash.hash_in(rowhash.Table(rates / "_data" / "treasury.parquet"), "ds", {}, None)

    def test_a_table_without_the_column_the_pin_is_dated_by(self, report, rates, student):
        _rebuild(rates, student, _yields(48).rename({"ds": "day"}))
        (problem,) = lock.verify(report, student).problems
        assert (
            "treasury: your build's table has no column 'ds' that holds dates, which the pin's rows are dated by"
            in problem.message
        )

    def test_a_row_in_a_year_the_pin_has_none_of(self, report, rates, student):
        """Your own record names a period the pin does not, before its last date: read, and refused."""
        early = pl.DataFrame({"ds": [date(2024, 6, 1)], "unique_id": ["T0"], "y": [1.0]}, schema=_yields(1).schema)
        _rebuild(rates, student, pl.concat([_yields(48), early]))
        (problem,) = lock.verify(report, student).problems
        assert "treasury: it has 1 row up to 2026-01-09 that the pin did not have" in problem.message

    def test_a_row_with_no_date_that_the_pin_had_none_of(self, report, rates, student):
        undated = pl.DataFrame({"ds": [None], "unique_id": ["T0"], "y": [1.0]}, schema=_yields(1).schema)
        _rebuild(rates, student, pl.concat([_yields(48), undated]))
        (problem,) = lock.verify(report, student).problems
        assert "treasury: it has 1 row with no date, and the pin had none" in problem.message
        assert "up to 2026-01-09" not in problem.message  # no date says where it falls

    def test_what_two_records_tell_without_a_table_read(self):
        rows = {"2025-01-01/2025-12-31": "h1", "2026-01-01/2026-01-09": "h2"}
        pinned = {"date_col": "ds", "as_of": "2026-01-09", "rows": rows}
        told = standins._told_by_the_records
        # The same periods, and newer ones: all told, nothing to read
        assert told(pinned, {"date_col": "ds", "rows": dict(rows)}) is None
        assert told(pinned, {"date_col": "ds", "rows": {**rows, "2026-02-01/2026-02-28": "h3"}}) is None
        # A period of yours that the pin has not, up to its last date: rows it did not have
        assert told(pinned, {"date_col": "ds", "rows": {**rows, "2024-01-01/2024-12-31": "h0"}}) == list(rows)
        # Rows with no date, of which the pin had none
        assert told(pinned, {"date_col": "ds", "rows": {**rows, "none": "h9"}}) == list(rows)
        # Dated by another column, or by none: nothing is told
        assert told(pinned, {"date_col": "day", "rows": dict(rows)}) == []
        assert told(pinned, {"rows": dict(rows)}) == []
        # One period with another hash: the other is told
        assert told(pinned, {"date_col": "ds", "rows": {**rows, "2026-01-01/2026-01-09": "hx"}}) == ["2025-01-01/2025-12-31"]

    def test_newer_rows_are_counted_without_a_table_read(self, report, rates, student, work, monkeypatch):
        """A pin that ends with its year: your record has that year as it is, and a later one."""
        _pin_again(report, rates, work, monkeypatch, _yields(31))
        assert list(lock.read_lock(report).assets["acme/rates:treasury"]["rows"]) == ["2025-12-01/2025-12-31"]
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: pytest.fail("the table was read"))
        _rebuild(rates, student, _yields(48))
        met = lock.verify(report, student).stood_in["acme/rates"].met["acme/rates:treasury"]
        assert (met.by, met.as_of, met.newer) == ("rows", "2025-12-31", 34)

    def test_your_builds_file_not_whole_in_the_store(self, report, rates, student):
        built = _rebuild(rates, student, _yields(48))
        _cut_short(student, built.assets["treasury"]["content_hash"])
        (problem,) = lock.verify(report, student).problems
        assert "treasury: the store does not have all of your build's file yet" in problem.message

    def test_a_record_of_rows_changed_to_what_no_pin_writes(self, report, rates, student):
        def junk(record: dict) -> None:
            if record.get("id") == "acme/rates:treasury":
                record["as_of"] = "the ninth of January"

        _change_lockfile(report, junk)
        _rebuild(rates, student, _yields(48))
        try:
            problems = lock.verify(report, student).problems
        except lock.LockError as error:
            assert "chartbook.lock" in str(error)  # refused when read, by its schema
        else:
            (problem,) = problems
            assert "treasury: chartbook.lock's record of its rows is not one ChartBook wrote" in problem.message
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert result.exit_code == 1 and "Traceback" not in result.output and "treasury" in result.output


class TestWhatIsRemembered:
    """What a comparison found, in this machine's cache folder: believed only as it was written, for the very question asked."""

    PINNED = {"date_col": "ds", "as_of": "2026-01-09", "rows": {"2025-12-01/2025-12-31": "sha256:aa"}}
    THEIRS = {"content_hash": "sha256:bb", "location": {"kind": "file", "path": "_data/t.parquet"}}

    def test_it_is_remembered_by_all_that_was_compared(self, monkeypatch):
        asked = standins._answers(self.PINNED, self.THEIRS)
        assert asked == standins._answers(dict(self.PINNED), dict(self.THEIRS))
        others = [
            ({**self.PINNED, "rows": {"2025-12-01/2025-12-31": "sha256:ab"}}, self.THEIRS),
            ({**self.PINNED, "rows": {**self.PINNED["rows"], "none": "sha256:cc"}}, self.THEIRS),
            ({**self.PINNED, "as_of": "2026-01-10"}, self.THEIRS),
            ({**self.PINNED, "date_col": "day"}, self.THEIRS),
            (self.PINNED, {**self.THEIRS, "content_hash": "sha256:bc"}),
        ]
        assert len({asked, *(standins._answers(*other) for other in others)}) == len(others) + 1
        # And by the ChartBook that compared: what another version found is not what this one would
        monkeypatch.setattr("chartbook.__version__", "0.0.0+another")
        assert standins._answers(self.PINNED, self.THEIRS) != asked

    def test_a_file_that_is_not_what_was_written_is_not_believed(self, report, rates, student, work):
        _rebuild(rates, student, _yields(48, revised=date(2025, 12, 14)))
        assert len(lock.verify(report, student).problems) == 1
        (remembered,) = (work / "student-cache" / "rows" / "met").glob("*.json")
        written = json.loads(remembered.read_text(encoding="utf-8"))
        assert written["differ"] == ["2025-12-01/2025-12-31"] and written["answers"] == remembered.stem
        same = {**written, "differ": []}
        forged = [
            {**same, "answers": "0" * 64},  # the answer to another question
            {key: value for key, value in same.items() if key != "answers"},
            {**same, "differ": ""}, {**same, "differ": {}}, {**same, "differ": [1]},
            {**same, "outside": 0.9}, {**same, "newer": True}, {**same, "rows": -1}, {**same, "index_column": 0},
            {key: value for key, value in same.items() if key != "no_date"},
            [same], "same",
        ]
        for one in forged:
            remembered.write_text(json.dumps(one), encoding="utf-8", newline="\n")
            standins._compared.clear()
            assert len(lock.verify(report, student).problems) == 1, one
            assert json.loads(remembered.read_text(encoding="utf-8")) == written  # compared again, and written again

    def test_with_no_cache_folder_a_table_is_hashed_once_a_process(self, report, rates, student, work, monkeypatch):
        (work / "not-a-folder").write_text("a file where the cache should be", encoding="utf-8", newline="\n")
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "not-a-folder"))
        _rebuild(rates, student, _yields(48))
        hashed = []
        real = rowhash.hash_in
        monkeypatch.setattr(rowhash, "hash_in", lambda *arguments, **options: hashed.append(1) or real(*arguments, **options))
        assert lock.verify(report, student).problems == []
        for name in ("treasury", "codes", "model/ar1", "chart/curve", "treasury"):
            assert assets.path(f"acme/rates:{name}", project_dir=report).exists()
        assert lock.verify(report, student).problems == []
        assert len(hashed) == 1


class TestWhereTheStoreHasThePinnedSnapshot:
    """A store that is shared: the snapshot the lockfile names is the pin. Another build of that commit is anyone's, and what the store lacks of the pin is lost, or on its way."""

    @pytest.fixture
    def author(self, report, rates, work, monkeypatch):
        """The author's own store, with a second build of the pinned commit in it: the same rows in other bytes."""
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "author-cache"))
        standins._compared.clear()
        store = FolderStore(work / "author")
        _rebuild(rates, store, _yields(48))
        return store

    def test_a_pinned_file_lost_from_it_is_lost_and_no_build_is_compared(self, report, author, monkeypatch):
        monkeypatch.setattr(standins, "compare", lambda *arguments, **options: pytest.fail("a build was compared"))
        author.delete(lock.read_lock(report).assets["acme/rates:treasury"]["content_hash"])
        checked = lock.verify(report, author)
        (problem,) = checked.problems
        assert problem.kind == "not_in_store" and checked.stood_in == {}
        assert checked.not_in_store["acme/rates"][0].endswith(", which has the snapshot it is of: treasury")
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(report)])
        assert result.exit_code == 1 and "your" not in result.output and "wait for the sync to finish" in result.output
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(report)])
        assert result.exit_code == 1 and "  lost: acme/rates:treasury" in result.output and "your" not in result.output
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=report)
        assert raised.value.reason == "not_in_store" and "yourself" not in str(raised.value)

    def test_a_pinned_file_half_synced_is_said_to_be(self, report, author):
        """The check does not pass on another build where the read would stop."""
        _cut_short(author, lock.read_lock(report).assets["acme/rates:treasury"]["content_hash"])
        checked = lock.verify(report, author)
        (problem,) = checked.problems
        assert "not fully synced yet" in problem.message and checked.stood_in == {}
        (event,) = lock.pin(report, author).problems
        assert event.status == "unsynced"
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=report)
        assert raised.value.reason == "not_synced"

    def test_a_hash_changed_by_hand_is_not_met_by_another_build(self, report, author):
        def another(record: dict) -> None:
            if record.get("id") == "acme/rates:treasury":
                record["content_hash"] = "sha256:" + "ab" * 32

        _change_lockfile(report, another)
        (problem,) = lock.verify(report, author).problems
        assert problem.kind == "not_in_store" and problem.asset == "acme/rates:treasury"

    def test_rows_changed_by_hand_are_a_gap_in_the_lineage(self, report, author):
        """As a merge leaves them: one side's hash of the file, the other side's line for a period."""
        assert snapshot.lineage_gaps(report, author) == []

        def other_rows(record: dict) -> None:
            if record.get("id") == "acme/rates:treasury":
                record["rows"]["2025-12-01/2025-12-31"] = record["rows"]["2026-01-01/2026-01-09"]

        _change_lockfile(report, other_rows)
        assert lock.verify(report, author).problems == []  # every pinned file is in the store
        (gap,) = snapshot.lineage_gaps(report, author)
        assert gap.startswith("acme/rates:treasury: what the lockfile records of its rows is not what its snapshot at ")
        assert "`chartbook update acme/rates` pins it again" in gap
        assert not lock.update(report, ["acme/rates"], store=author).problems
        assert snapshot.lineage_gaps(report, author) == []

    def test_a_half_synced_pin_where_it_is_not(self, report, rates, student, work):
        """The student's store, with the pinned file arriving in it: on its way, and no build read in its place."""
        pinned = lock.read_lock(report).assets["acme/rates:codes"]
        built = _rebuild(rates, student, _yields(48))
        assert built.assets["codes"]["content_hash"] == pinned["content_hash"]  # the same bytes: the store has the file
        _cut_short(student, pinned["content_hash"])
        checked = lock.verify(report, student)
        assert checked.stood_in == {} and any("not fully synced yet" in problem.message for problem in checked.problems)


class TestLineageOfWhatReadAStandIn:

    def _with_an_asset(self, report: Path) -> None:
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

    def test_a_snapshot_records_the_build_that_stood_in_and_lineage_follows_it(self, report, rates, student, work):
        built = _rebuild(rates, student, _yields(48))
        self._with_an_asset(report)
        taken = snapshot.make(report, store=student).snapshot
        (recorded,) = taken.inputs
        named = lock.read_lock(report).dependencies[0]["snapshot"]
        assert recorded["snapshot"] == named and recorded["stood_in"] == built.made_at != named
        # A later build of yours that holds the pinned rows too: the report's snapshot was not made from it
        _rebuild(rates, student, _yields(50))
        deck = work / "deck"
        _write_manifest(deck, {"project": {"id": "acme/deck"}, "dependencies": {"acme/report": {"path": "../report"}}})
        assert not lock.pin(deck, student).problems
        walked = lineage.walk(deck, student)
        assert walked.gaps() == []
        (of_report,) = walked.root.children
        (of_rates,) = of_report.children
        assert of_rates.kind == "snapshot" and of_rates.stands_in and of_rates.made_at == built.made_at
        # With that build gone, the gap says which
        snapshot.remove(student, built)
        gaps = [gap for _, gap in lineage.walk(deck, student).gaps()]
        assert len(gaps) == 1 and f"nor is the build of {built.commit[:7]}, made {built.made_at}, that stood in for it" in gaps[0]

    def test_a_snapshot_whose_pinned_snapshot_is_in_the_store_records_none(self, report, work, monkeypatch):
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        self._with_an_asset(report)
        (recorded,) = snapshot.make(report, store=FolderStore(work / "author")).snapshot.inputs
        assert "stood_in" not in recorded

    def test_each_dependency_has_one_gap(self, report, rates, student, work, monkeypatch):
        """Two dependencies: one whose pinned files the store has from a build of another commit, one not built at all."""
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        author = FolderStore(work / "author")
        zeta = work / "zeta"
        _write_manifest(zeta, {"project": {"id": "acme/zeta"}, "dataframes": {"t": {"path": "./_data/t.parquet", "docs": "d"}}})
        (zeta / "_data").mkdir()
        pl.DataFrame({"x": [1]}).write_parquet(zeta / "_data" / "t.parquet")
        commit_pipeline(zeta)
        snapshot.make(zeta, store=author)
        _write_manifest(
            report,
            {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}, "acme/zeta": {"path": "../zeta"}}},
        )
        assert not lock.pin(report, author).problems
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        # The student built the rates at a later commit only: the same files, and no snapshot of the commit pinned
        (rates / "chartbook.toml").write_text(
            (rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# a later commit\n", encoding="utf-8", newline="\n"
        )
        commit_pipeline(rates)
        snapshot.make(rates, store=student)
        assert [problem.dependency for problem in lock.verify(report, student).problems] == ["acme/zeta"]
        gaps = snapshot.lineage_gaps(report, student)
        assert len(gaps) == 2, gaps
        assert gaps[0].startswith("acme/zeta: 1 of its 1 pin is not in the store at ")
        assert gaps[1].startswith("acme/rates: the lockfile pins its snapshot at ") and "has no such snapshot" in gaps[1]


class TestAVersionPinnedByItsLabel:
    """A label names a version made at an earlier commit: no build of the pinned commit gives it."""

    @pytest.fixture
    def labelled(self, report, rates, work, monkeypatch):
        """The author's model gets a `champion`: the version first trained. The model is trained again, and the report pinned to that."""
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "author"))
        author = FolderStore(work / "author")
        (first,) = [taken for taken in snapshot.readable_snapshots(author)[0] if taken.pipeline == "acme/rates"]
        start = first.assets["model/ar1"]["content_hash"].split(":", 1)[1][:12]
        _write_manifest(rates, {**MANIFEST, "models": {"ar1": {"path": "./_models/ar1.joblib", "aliases": {"champion": start}}}})
        (rates / "_models" / "ar1.joblib").write_bytes(b"weights, trained again")
        commit_pipeline(rates)
        snapshot.make(rates, store=author)
        assert not lock.update(report, store=author).problems
        assert "acme/rates:model/ar1@champion" in lock.read_lock(report).assets
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "student"))
        return report

    def test_it_is_met_by_the_same_file_only_and_update_is_not_offered(self, labelled, rates, student):
        built = _rebuild(rates, student, _yields(48))
        result = CliRunner().invoke(main, ["pin", "--check", "--project-dir", str(labelled)])
        assert result.exit_code == 1
        assert f"acme/rates: your build of {_said(built)}, does not match the pin\n" in result.output
        assert (
            "  model/ar1@champion: a version pinned by its label is met by the same file only, and the store does "
            "not have it. It was made at an earlier commit, most likely" in result.output
        )
        assert "chartbook update" not in result.output
        # `chartbook pin` says the same, and does not say the build is read
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(labelled)])
        assert result.exit_code == 1, result.output
        assert "1 not met by your own build" in result.output and "  differs: acme/rates:model/ar1@champion" in result.output
        assert f"  Your build of {_said(built)}, does not match the pin." in result.output
        assert "Read from your own build" not in result.output and "chartbook update" not in result.output
        # Nor is it read
        with pytest.raises(AssetNotPinnedError) as raised:
            assets.path("acme/rates:treasury", project_dir=labelled)
        assert raised.value.reason == "differs" and "model/ar1@champion" in str(raised.value)

    def test_with_its_file_in_the_store_the_check_the_lineage_and_a_snapshot_agree(self, labelled, rates, student):
        """The store has the labelled version from an earlier build; the build that stands in does not hold it itself."""
        (rates / "_models" / "ar1.joblib").write_bytes(b"weights")
        _rebuild(rates, student, _yields(47))
        (rates / "_models" / "ar1.joblib").write_bytes(b"weights, trained again")
        built = _rebuild(rates, student, _yields(48))
        checked = lock.verify(labelled, student)
        assert checked.problems == [] and checked.stood_in["acme/rates"].snapshot.made_at == built.made_at
        assert checked.stood_in["acme/rates"].met["acme/rates:model/ar1@champion"].by == "file"
        assert snapshot.lineage_gaps(labelled, student) == []
        walked = lineage.walk(labelled, student)
        assert walked.gaps() == [] and walked.root.children[0].stands_in
        result = CliRunner().invoke(main, ["pin", "--project-dir", str(labelled)])
        assert result.exit_code == 0 and f"  Read from your own build of {_said(built)}." in result.output


class TestWhatIsSaidOfBuildingItYourself:

    def test_a_dependency_named_by_its_id_names_its_folder(self):
        entry = {
            "id": "acme/rates",
            "location": {
                "kind": "store", "pipeline": "acme/rates", "commit": "abcdef1234567890",
                "repository": "https://github.com/acme/pipelines",
            },
        }
        assert lock.build_it_said(entry).startswith(
            "in a clone of https://github.com/acme/pipelines, in the folder of acme/rates, `git checkout abcdef1` and "
            "`chartbook run --snapshot`"
        )
        assert lock.build_it_said({**entry, "location": {**entry["location"], "kind": "git"}}) == ""
        # A repository named as the pipeline is holds that pipeline alone: no folder to name
        own = {**entry, "location": {**entry["location"], "repository": "https://github.com/acme/rates.git"}}
        assert lock.build_it_said(own).startswith("in a clone of https://github.com/acme/rates.git, `git checkout abcdef1` and ")
