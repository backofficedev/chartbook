"""Rows and stand-ins on a machine whose catalog names several stores (``docs_src/design/pins-and-rebuilds.md``).

A machine with more than one store names them in its catalog,
``[stores.NAME]`` in ``~/.chartbook/catalog.toml``: a read looks in every
one, and a snapshot is written to the store that lists its pipeline, or to
the first. Every other test of a pin that a rebuild meets points
``CHARTBOOK_STORE`` at one folder. These tell the same story on machines
set up the other way: an author and a student, each with a catalog of two
stores, the upstream routed to the second. What they see is what the
single store shows, with the store named.
"""

from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import backends, config, data, lock, snapshot, standins
from chartbook import resolve as resolve_module
from chartbook.cli import main
from chartbook.multi_store import Stores
from chartbook.store import FolderStore
from tests.fixtures import commit_pipeline
from tests.test_standins import MANIFEST, _write_manifest, _yields


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def sit_at(work, monkeypatch):
    """Sit at one person's machine: a home folder whose catalog names that person's stores, and no ``CHARTBOOK_STORE``.

    Two stores unless told otherwise, the upstream routed to the second,
    so that a write is routed and a read has to look past the first.
    """

    def sit(who: str, stores: dict = None) -> dict:
        monkeypatch.delenv(config.STORE_ENV_VAR, raising=False)
        home = work / f"{who}-home"
        home.mkdir(exist_ok=True)
        monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: home)
        monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / f"{who}-cache"))
        if stores is None:
            stores = {
                "first": {"url": str(work / f"{who}-first"), "pipelines": ["someone/else"]},
                "second": {"url": str(work / f"{who}-second"), "pipelines": ["acme/rates"]},
            }
        for spec in stores.values():
            Path(spec["url"]).mkdir(exist_ok=True)
        (home / "catalog.toml").write_text(
            tomli_w.dumps({"project": {"name": "Catalog"}, "stores": stores}), encoding="utf-8", newline="\n"
        )
        # Each person's commands are a process of their own
        resolve_module._said_stand_ins.clear()
        standins._compared.clear()
        return {name: FolderStore(spec["url"]) for name, spec in stores.items()}

    return sit


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
    """A report that depends on it. Commands are run in its folder."""
    directory = work / "report"
    _write_manifest(directory, {"project": {"id": "acme/report"}, "dependencies": {"acme/rates": {"path": "../rates"}}})
    monkeypatch.chdir(directory)
    return directory


def _run(*arguments: str):
    return CliRunner().invoke(main, list(arguments))


def _snapshot(rates: Path):
    result = _run("snapshot", "--as-is", "--no-gc-reminder", "--project-dir", str(rates))
    assert result.exit_code == 0, result.output
    return result


def _rebuild(rates: Path, frame: pl.DataFrame):
    """The student builds the upstream at the same commit: these rows, written by pandas, and a chart drawn anew."""
    frame.to_pandas().to_parquet(rates / "_data" / "treasury.parquet", index=False)
    (rates / "_output" / "curve.html").write_bytes(b"<html>the student's</html>")
    return _snapshot(rates)


@pytest.fixture
def pinned(sit_at, rates, report):
    """The author's machine: the upstream snapshotted and the report pinned, each by its command."""
    stores = sit_at("author")
    made = _snapshot(rates)
    pin = _run("pin")
    assert pin.exit_code == 0, pin.output
    return stores, made, pin


class TestTheAuthor:
    def test_the_snapshot_goes_to_the_store_that_lists_the_pipeline_and_records_its_rows(self, pinned):
        stores, made, _ = pinned
        assert made.output.splitlines()[-1] == "Stores: second"
        assert snapshot.all_snapshots(stores["first"]) == []
        (taken,) = snapshot.all_snapshots(stores["second"])
        assert taken.assets["treasury"]["as_of"] == "2026-01-09" and taken.assets["treasury"]["row_count"] == 80

    def test_the_pin_copies_the_rows_and_names_the_store(self, pinned, report):
        _, _, pin = pinned
        assert "acme/rates: 3 pinned. Its 1 chart is not pinned: each build draws it anew" in pin.output
        assert ", in store second." in pin.output
        assert lock.read_lock(report).assets["acme/rates:treasury"]["rows"]

    def test_update_and_snapshot_say_what_the_rows_did(self, pinned, rates):
        """Told from the two records and a read of the last period: each store of the catalog is a folder on this machine."""
        assert standins.reads_here(Stores.configured())
        _yields(48).write_parquet(rates / "_data" / "treasury.parquet")
        made = _snapshot(rates)
        assert "    acme/rates:treasury: 16 new rows, through 2026-01-17; earlier rows unchanged" in made.output.splitlines()
        moved = _run("pin", "--update")
        assert moved.exit_code == 0, moved.output
        assert "    16 new rows, through 2026-01-17; earlier rows unchanged" in moved.output.splitlines()

    def test_a_value_the_source_revised_is_named_by_both(self, pinned, rates):
        _yields(48, revised=date(2025, 12, 14)).write_parquet(rates / "_data" / "treasury.parquet")
        told = "earlier rows changed: the rows of 2025-12-01 to 2025-12-31 differ; 16 new rows, through 2026-01-17"
        assert f"    acme/rates:treasury: {told}" in _snapshot(rates).output.splitlines()
        assert f"    {told}" in _run("pin", "--update").output.splitlines()


class TestAStudentWithACatalogOfTheirOwn:
    """Another machine, with two stores of its own and nothing of the author's in either."""

    def test_before_they_build_it_the_check_names_every_store_it_looked_in(self, pinned, sit_at, work):
        sit_at("student")
        result = _run("pin", "--check")
        assert result.exit_code == 1, result.output
        first, *_ = result.output.splitlines()
        assert first.startswith("acme/rates: 3 of its 3 pins are not in the store at ") and "no build of yours" in first
        assert str(work / "student-first") in first and str(work / "student-second") in first

    def test_their_build_stands_in(self, pinned, sit_at, rates, report):
        stores = sit_at("student")
        _rebuild(rates, _yields(48))
        (built,) = snapshot.all_snapshots(stores["second"])  # routed, as the author's was
        result = _run("pin", "--check")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"acme/rates: read from your own build of {standins.build_said(built)}",
            "  treasury: the pinned rows, through 2026-01-09; 16 newer rows",
            "3 pin(s) of 1 dependency: 2 in the store, 1 met by your own build. Nothing written.",
        ]
        before = (report / lock.LOCK_FILE).read_bytes()
        pin = _run("pin")
        assert pin.exit_code == 0 and "acme/rates: 2 already pinned, 1 met by your own build" in pin.output
        assert (report / lock.LOCK_FILE).read_bytes() == before

    def test_a_read_gives_the_pinned_rows_and_lineage_says_which_build(self, pinned, sit_at, rates, capsys):
        sit_at("student")
        _rebuild(rates, _yields(48))
        capsys.readouterr()
        frame = data.load("acme/rates:treasury").collect()
        # pandas wrote the student's dates as times, and the pin's last date comes back as the file has it
        assert frame.height == 80 and frame["ds"].max() == datetime(2026, 1, 9)
        assert data.as_of("acme/rates:treasury") == datetime(2026, 1, 9)
        assert pl.read_parquet(data.path("acme/rates:treasury")).height == 96
        said = capsys.readouterr().err
        assert said.count("acme/rates: read from your own build of ") == 1 and "has 16 rows after 2026-01-09" in said
        walked = _run("lineage")
        assert walked.exit_code == 0, walked.output
        assert "your build stands in for the pinned snapshot, which the store does not have" in walked.output

    def test_a_value_changed_in_the_past_is_not_met(self, pinned, sit_at, rates):
        sit_at("student")
        _rebuild(rates, _yields(48, revised=date(2025, 12, 14)))
        result = _run("pin", "--check")
        assert result.exit_code == 1, result.output
        assert "  treasury: the rows of 2025-12-01 to 2025-12-31 differ" in result.output.splitlines()
        assert "  To read your build instead: chartbook pin --update acme/rates" in result.output.splitlines()

    def test_the_build_is_found_in_whichever_store_holds_it(self, pinned, sit_at, rates, work):
        """Their catalog lists the upstream under no store, so their build goes to the first: a read finds it there."""
        stores = sit_at("student", {
            "first": {"url": str(work / "student-first")},
            "second": {"url": str(work / "student-second"), "pipelines": ["someone/else"]},
        })
        made = _rebuild(rates, _yields(48))
        assert made.output.splitlines()[-1] == "Stores: first"
        assert len(snapshot.all_snapshots(stores["first"])) == 1 and snapshot.all_snapshots(stores["second"]) == []
        result = _run("pin", "--check")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == "3 pin(s) of 1 dependency: 2 in the store, 1 met by your own build. Nothing written."

    def test_what_was_compared_is_remembered_once_for_the_machine(self, pinned, sit_at, rates, work, monkeypatch):
        from chartbook import rowhash

        sit_at("student")
        _rebuild(rates, _yields(48))
        assert _run("pin", "--check").exit_code == 0
        assert list((work / "student-cache" / "rows" / "met").glob("*.json"))
        # The next command, a process of its own, hashes no table
        standins._compared.clear()

        def never(*arguments, **options):
            raise AssertionError("a table was hashed again")

        monkeypatch.setattr(rowhash, "hash_rows", never)
        assert _run("pin", "--check").exit_code == 0


class TestWhereAStoreOfTheCatalogHasThePinnedSnapshot:
    """A team's store beside your own: the pin is in a store, and no build of yours is looked at."""

    def test_the_pinned_files_are_read_from_it(self, pinned, sit_at, rates, work):
        sit_at("student", {
            "mine": {"url": str(work / "student-first")},
            "team": {"url": str(work / "author-second"), "read_only": True},
        })
        _rebuild(rates, _yields(48, revised=date(2025, 12, 14)))  # a build of theirs that would not meet the pin
        result = _run("pin", "--check")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["3 pin(s) of 1 dependency, all in the store. Nothing written."]
        assert data.load("acme/rates:treasury").collect().height == 80
        assert Path(data.path("acme/rates:treasury")).is_relative_to(work / "author-second")
