"""How data.load reads another pipeline when nothing is pinned yet, interactively and in a batch run
(docs_src/design/reading-other-pipelines.md, decisions 2c, 3b, 4b and 5b)."""

import os
import runpy
import sys
import warnings
from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import backends as _bound_before_the_fixtures  # noqa: F401 - so the isolation test means something
from chartbook import data, lock, snapshot
from chartbook.errors import AssetNotPinnedError, DependencyNotDeclaredError
from chartbook.resolve import UnrecordedReadWarning, WorkingVersionWarning
from tests.test_dependencies_by_id import _commit, _forecast, _git, _rates, elsewhere  # noqa: F401 - a fixture


@pytest.fixture(autouse=True)
def _no_other_warning():
    """The organization's settings file, named by the test setup, is there, so that a read's warnings are its own."""
    import os

    Path(os.environ["CHARTBOOK_SYSTEM_SETTINGS"]).write_text("")


def _value(reference: str) -> list:
    return data.load(reference).collect()["r"].to_list()


@pytest.fixture
def together(tmp_path):
    """`acme/rates` and `acme/forecast` in one repository, rates snapshotted; forecast declares it by path, unpinned."""
    work = tmp_path.resolve()
    _rates(work / "rates", 4.0)
    forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
    _commit(work)
    taken = snapshot.make(work / "rates").snapshot
    return work, forecast, taken


class TestADeclaredDependencyNotPinned:
    def test_the_first_read_pins_it_and_says_so(self, together, monkeypatch, capsys):
        work, forecast, taken = together
        monkeypatch.chdir(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _value("acme/rates:treasury") == [4.0]
        said = capsys.readouterr().err
        assert f"acme/rates: pinned to its newest snapshot, {taken.commit[:7]}" in said
        assert "`chartbook update acme/rates` moves it" in said
        (entry,) = lock.read_lock(forecast / lock.LOCK_FILE).dependencies
        assert entry["location"]["commit"] == taken.commit
        # The working file changes; the pin does not
        pl.DataFrame({"d": ["2024-01-01"], "r": [9.0]}).write_parquet(work / "rates" / "_data" / "treasury.parquet")
        assert _value("acme/rates:treasury") == [4.0]
        assert capsys.readouterr().err == ""

    def test_by_its_id_too(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        assert _value("acme/rates:treasury") == [4.2]
        assert lock.read_lock(forecast / lock.LOCK_FILE).dependencies[0]["location"]["commit"] == second.commit

    def test_only_what_is_read_is_pinned(self, together, monkeypatch):
        work, forecast, taken = together
        _rates(work / "other", 1.0)
        (work / "other" / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/other"}, "dataframes": {"x": {"path": "./_data/treasury.parquet", "docs": "d"}}}))
        _forecast(forecast, {"acme/rates": {"path": "../rates"}, "acme/other": {"path": "../other"}})
        _commit(work, "Another")
        snapshot.make(work / "other")
        monkeypatch.chdir(forecast)
        _value("acme/rates:treasury")
        assert [entry["id"] for entry in lock.read_lock(forecast / lock.LOCK_FILE).dependencies] == ["acme/rates"]

    def test_a_git_dependency_is_not_fetched_to_read_it(self, tmp_path, monkeypatch):
        forecast = _forecast(tmp_path / "forecast", {"crsp": {"git": "https://example.invalid/acme/crsp.git"}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="Run `chartbook pin`") as raised:
            data.load("crsp:returns")
        assert raised.value.reason == "no_lockfile" and not (forecast / lock.LOCK_FILE).exists()

    def test_a_batch_run_does_not_pin(self, together, monkeypatch):
        work, forecast, taken = together
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="Run `chartbook pin`"):
            data.load("acme/rates:treasury")
        assert not (forecast / lock.LOCK_FILE).exists()


class TestAPipelineNotDeclared:
    def test_its_newest_snapshot_is_read_with_a_warning(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        manifest = (forecast / "chartbook.toml").read_text()
        monkeypatch.chdir(forecast)
        with pytest.warns(UnrecordedReadWarning) as said:
            assert _value("acme/rates:treasury") == [4.2]
        message = str(said[0].message)
        assert f"newest snapshot, {second.commit[:7]}, and recording nothing" in message
        assert "`chartbook add acme/rates` declares it" in message
        assert said[0].filename == __file__  # the line that read, not ChartBook's
        assert (forecast / "chartbook.toml").read_text() == manifest and not (forecast / lock.LOCK_FILE).exists()

    def test_a_batch_run_refuses_it(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError):
            data.load("acme/rates:treasury")

    def test_with_no_snapshot_and_no_folder_it_is_still_the_error(self, tmp_path, monkeypatch):
        forecast = _forecast(tmp_path / "forecast", {})
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError):
            data.load("acme/nothing:treasury")


class TestNoSnapshotButAWorkingFolder:
    def test_a_path_dependency_is_read_as_it_is_with_a_loud_warning(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        monkeypatch.chdir(forecast)
        with pytest.warns(WorkingVersionWarning, match="reading its WORKING version") as said:
            assert _value("acme/rates:treasury") == [7.0]
        assert str(work / "rates" / "_data" / "treasury.parquet") in str(said[0].message)
        assert not (forecast / lock.LOCK_FILE).exists()  # nothing records the read, and no empty lockfile is made

    def test_a_batch_run_refuses_it(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/rates:treasury")


class TestOutsideAnyPipeline:
    def test_the_newest_snapshot_quietly(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _value("acme/rates:treasury") == [4.2]
            assert data.load(pipeline="acme/rates", dataframe="treasury").collect()["r"].to_list() == [4.2]
            assert _value("rates:treasury") == [4.2]  # a bare name only one ID in the store ends with

    def test_nothing_to_read_says_so(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(AssetNotPinnedError, match="has no snapshot of acme/nothing") as raised:
            data.load("acme/nothing:treasury")
        assert raised.value.reason == "no_snapshot"

    def test_a_dataframe_its_snapshot_lacks_is_named(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        monkeypatch.chdir(work)
        with pytest.raises(AssetNotPinnedError, match="has no treasuri \\(did you mean 'treasury'\\?\\)"):
            data.load("acme/rates:treasuri")

    def test_through_a_catalog_the_snapshot_and_not_the_folder(self, together, monkeypatch):
        from chartbook import resolve as resolve_module

        work, forecast, taken = together
        catalog = work / "catalog"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog", "id": "cat"}, "pipelines": {"acme/rates": {"path": "../rates"}}})
        )
        pl.DataFrame({"d": ["2024-01-01"], "r": [9.0]}).write_parquet(work / "rates" / "_data" / "treasury.parquet")
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        monkeypatch.setattr(resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            frame = data.load(pipeline="rates", dataframe="treasury")
        assert frame.collect()["r"].to_list() == [4.0]  # what the snapshot holds, not the folder's 9.0


class TestARun:
    def test_its_scripts_are_a_batch_run(self, tmp_path):
        from chartbook import run

        work = tmp_path.resolve()
        script = f"{sys.executable} -c \"import os; open('_data/batch', 'w').write(os.environ.get('CHARTBOOK_BATCH', ''))\""
        forecast = _forecast(work / "forecast", {}, scripts={"build": script})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert (forecast / "_data" / "batch").read_text() == "1"


def _model_pipeline(work: Path):
    """`acme/model`, a model snapshotted at v1 and at v2, with `champion` naming v1."""
    repository = work / "m"
    folder = repository / "model"
    (folder / "_output").mkdir(parents=True)
    manifest = {"project": {"id": "acme/model"}, "models": {"m": {"path": "./_output/m.json"}}}
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    (folder / "_output" / "m.json").write_text("v1")
    _git(repository, "init", "--quiet", "-b", "main")
    (repository / ".gitignore").write_text("_output/\nchartbook.lock\n")
    _commit(repository)
    v1 = snapshot.make(folder, made_at="2026-01-01T00:00:00.000000Z").snapshot
    start = v1.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
    manifest["models"]["m"]["aliases"] = {"champion": start}
    (folder / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    (folder / "_output" / "m.json").write_text("v2")
    _commit(repository, "Champion")
    snapshot.make(folder)
    return folder, start


def _catalog(work: Path, pipelines: dict) -> Path:
    catalog = work / "catalog"
    catalog.mkdir(exist_ok=True)
    (catalog / "chartbook.toml").write_text(tomli_w.dumps({"project": {"type": "catalog", "id": "cat"}, "pipelines": pipelines}))
    return catalog


class TestWhatTheReviewFound:
    def test_a_model_version_is_that_version(self, tmp_path, monkeypatch):
        from chartbook import models

        work = tmp_path.resolve()
        folder, start = _model_pipeline(work)
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        assert models.path("acme/model:m@champion").read_text() == "v1"
        assert models.path(f"acme/model:m@{start}").read_text() == "v1"
        assert models.path("acme/model:m").read_text() == "v2"
        with pytest.raises(AssetNotPinnedError, match="'nolabel' is neither a label") as raised:
            models.path("acme/model:m@nolabel")
        assert "chartbook snapshot" not in str(raised.value)
        assert models.path(f"acme/model:m@{start[:8]}").read_text() == "v1"  # as a pin takes it, four digits or more

    def test_a_pipeline_reading_itself_reads_its_own_file(self, together, monkeypatch):
        work, forecast, taken = together
        pl.DataFrame({"d": ["2024-01-01"], "r": [5.0]}).write_parquet(work / "rates" / "_data" / "treasury.parquet")
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        (work / "rates" / "notebooks").mkdir()
        monkeypatch.chdir(work / "rates" / "notebooks")
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            # Through the catalog that lists its folder: its own file
            assert data.load(pipeline="acme/rates", dataframe="treasury", catalog_path=catalog).collect()["r"].to_list() == [5.0]
        # By its own ID: refused, never a stale snapshot of itself
        with pytest.raises(ValueError, match="names this pipeline, acme/rates. Read its own assets by their own names"):
            data.load("acme/rates:treasury")

    def test_a_dependency_under_another_key_is_found_by_its_id(self, together, monkeypatch):
        work, forecast, taken = together
        _forecast(forecast, {"yc": {"path": "../rates"}})
        lock.pin(forecast)
        _rates(work / "rates", 5.0)
        (work / "rates" / "more.txt").write_text("more\n")
        _commit(work, "Newer")
        snapshot.make(work / "rates")
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        monkeypatch.chdir(forecast)
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _value("acme/rates:treasury") == [4.0]  # the pin, not the newer snapshot
            assert data.load(pipeline="acme/rates", dataframe="treasury", catalog_path=catalog).collect()["r"].to_list() == [4.0]

    def test_a_catalog_key_is_not_taken_for_another_pipelines_id(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)  # acme/rates, no snapshot
        other = work / "other-repo"
        _rates(other / "rates", 8.0)
        (other / "rates" / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "other/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _git(other, "init", "--quiet", "-b", "main")
        (other / ".gitignore").write_text("_data/\n")
        _commit(other)
        snapshot.make(other / "rates")
        catalog = _catalog(work, {"rates": {"path": "../rates"}})
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        with pytest.warns(WorkingVersionWarning):
            frame = data.load(pipeline="rates", dataframe="treasury", catalog_path=catalog)
        assert frame.collect()["r"].to_list() == [4.0]

    def test_a_store_dependencys_working_folder_is_found_by_its_id(self, tmp_path, monkeypatch):
        from chartbook import resolve as resolve_module

        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)  # acme/rates, no snapshot
        forecast = _forecast(work / "forecast", {"yc": {"id": "acme/rates"}})
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        monkeypatch.setattr(resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml")
        monkeypatch.chdir(forecast)
        with pytest.warns(WorkingVersionWarning):
            assert _value("yc:treasury") == [4.0]

    def test_an_ambiguous_name_or_an_unreadable_store_is_an_error_not_a_folder(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        other = work / "other-repo"
        _rates(other / "rates", 8.0)
        (other / "rates" / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "other/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _git(other, "init", "--quiet", "-b", "main")
        (other / ".gitignore").write_text("_data/\n")
        _commit(other)
        snapshot.make(other / "rates")
        _rates(work / "rates", 6.0)
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        from chartbook import resolve as resolve_module

        monkeypatch.setattr(resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml")
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        with pytest.raises(AssetNotPinnedError, match="name one by its ID"):
            data.load("rates:treasury")
        monkeypatch.setenv("CHARTBOOK_STORE", "ftp://misconfigured/store")
        with pytest.raises(AssetNotPinnedError, match="the store cannot be read"):
            data.load(pipeline="acme/rates", dataframe="treasury")

    def test_two_first_reads_at_once_both_pin(self, together, monkeypatch):
        import threading
        import time

        work, forecast, taken = together
        _rates(work / "other", 1.0)
        (work / "other" / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/other"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _forecast(forecast, {"acme/rates": {"path": "../rates"}, "acme/other": {"path": "../other"}})
        _commit(work, "Another")
        snapshot.make(work / "other")
        writing = lock.write_lock

        def slowly(*arguments, **keywords):
            time.sleep(0.3)  # the window in which another pin would read the lockfile as it was
            return writing(*arguments, **keywords)

        monkeypatch.setattr(lock, "write_lock", slowly)
        results = {}

        def read(key):
            results[key] = data.load(f"{key}:treasury", project_dir=forecast).collect()["r"].to_list()

        threads = [threading.Thread(target=read, args=(key,)) for key in ("acme/rates", "acme/other")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == {"acme/rates": [4.0], "acme/other": [1.0]}
        assert sorted(e["id"] for e in lock.read_lock(forecast / lock.LOCK_FILE).dependencies) == ["acme/other", "acme/rates"]

    def test_only_build_is_a_batch_run(self, tmp_path):
        from chartbook import run

        work = tmp_path.resolve()
        script = f"{sys.executable} -c \"import os; open('_data/batch', 'w').write(os.environ.get('CHARTBOOK_BATCH', 'unset'))\""
        forecast = _forecast(work / "forecast", {}, scripts={"lab": script})
        report = run.run(forecast, script="lab", echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert (forecast / "_data" / "batch").read_text() == "unset"

    def test_a_notebook_in_a_catalogs_folder_is_in_no_pipeline(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        catalog = _catalog(work, {})
        (catalog / "notebooks").mkdir()
        monkeypatch.chdir(catalog / "notebooks")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert _value("acme/rates:treasury") == [4.2]

    def test_reads_in_a_loop_do_not_pin_or_parse_again(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        pins = []
        pinning = lock.pin
        monkeypatch.setattr(lock, "pin", lambda *a, **k: pins.append(1) or pinning(*a, **k))
        monkeypatch.chdir(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for _ in range(5):
                assert _value("acme/rates:treasury") == [7.0]
        assert len(pins) == 1

    def test_the_catalog_command_says_what_is_missing(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from chartbook.cli import main

        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)  # in the catalog, with no snapshot; the command runs in the catalog's folder, no pipeline
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        monkeypatch.chdir(work)
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        result = CliRunner().invoke(main, ["data", "get-path", "--pipeline", "acme/rates", "--dataframe", "treasury", "--catalog", str(catalog)])
        assert result.exit_code == 1 and result.exception is None or isinstance(result.exception, SystemExit)
        assert "this is no pipeline" in result.output and "a batch run" in result.output
        assert "reads only what a lockfile pins" in result.output

    def test_a_folder_with_no_manifest_or_one_that_cannot_be_written(self, together, monkeypatch, tmp_path):
        import os

        work, forecast, taken = together
        _forecast(forecast, {"acme/gone": {"path": "../gone"}})
        (work / "gone").mkdir()
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="has no chartbook.toml"):
            data.load("acme/gone:treasury")
        _forecast(forecast, {"acme/rates": {"path": "../rates"}})
        (forecast / lock.LOCK_FILE).unlink(missing_ok=True)
        os.chmod(forecast, 0o555)
        try:
            with pytest.warns(UnrecordedReadWarning, match="could not be pinned"):
                assert _value("acme/rates:treasury") == [4.0]
        finally:
            os.chmod(forecast, 0o755)

    def test_pin_only_takes_one_name_and_leaves_the_rest(self, together):
        work, forecast, taken = together
        lock.pin(forecast)
        _forecast(forecast, {})  # acme/rates is no longer declared
        lock.pin(forecast, only="acme/other")
        assert [e["id"] for e in lock.read_lock(forecast / lock.LOCK_FILE).dependencies] == ["acme/rates"]

    def test_the_warnings_do_not_promise_what_snapshot_does_not_do(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        monkeypatch.chdir(forecast)
        with pytest.warns(UnrecordedReadWarning) as said:
            _value("acme/rates:treasury")
        assert "chartbook snapshot" not in str(said[0].message)


def _claimed_also_by(work: Path, value: float, address: str):
    """Another repository that gives itself the ID acme/rates, snapshotted."""
    from tests.test_dependencies_by_id import _another

    return _another(work, address.rsplit("/", 1)[-1] + "-copy", value, remote=address)


class TestWhatTheSecondReviewFound:
    def test_a_declared_dependency_none_of_whose_snapshots_can_be_taken_is_an_error(self, tmp_path, monkeypatch):
        from chartbook import resolve as resolve_module
        from tests.test_dependencies_by_id import _another

        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        _claimed_also_by(work, 8.0, "https://github.com/someone/rates")
        _rates(work / "rates", 99.0)
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        monkeypatch.setattr(resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="2 repositories claim the ID"):
            data.load("acme/rates:treasury")

    def test_a_path_dependency_whose_only_snapshot_is_dated_ahead_is_an_error(self, together, monkeypatch):
        import dataclasses

        from chartbook.store import default_store

        work, forecast, taken = together
        taken.path.unlink()
        snapshot._write(dataclasses.replace(taken, made_at="2099-01-01T00:00:00.000000Z"), default_store())
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/rates:treasury")

    def test_an_unwritable_pipeline_reads_what_a_pin_would_take(self, together, monkeypatch):
        import os

        work, forecast, taken = together
        _forecast(forecast, {"yc": {"path": "../rates"}})
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with pytest.warns(UnrecordedReadWarning, match="the snapshot a pin would take"):
                assert _value("yc:treasury") == [4.0]
        finally:
            os.chmod(forecast, 0o755)

    def test_an_unwritable_pipeline_takes_the_commit_asked_for(self, elsewhere, monkeypatch):
        import os

        home, first, second = elsewhere
        forecast = _forecast(home / "forecast", {"acme/rates": {"commit": first.commit[:7]}})
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with pytest.warns(UnrecordedReadWarning):
                assert _value("acme/rates:treasury") == [4.1]
        finally:
            os.chmod(forecast, 0o755)

    def test_an_unwritable_pipeline_with_no_snapshot_reads_the_folder(self, tmp_path, monkeypatch):
        import os

        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with pytest.warns(WorkingVersionWarning):
                assert _value("acme/rates:treasury") == [7.0]
        finally:
            os.chmod(forecast, 0o755)

    def test_a_copy_that_depends_on_its_original_by_the_same_id_is_refused(self, together, monkeypatch):
        """An ID names one pipeline: a copy that kept its original's ID and reads the original depends on itself."""
        work, forecast, taken = together
        copy = work / "copy"
        _rates(copy, 9.0)  # acme/rates too
        manifest = (copy / "chartbook.toml").read_text()
        (copy / "chartbook.toml").write_text(manifest + '\n[dependencies]\n"acme/rates" = { path = "../rates" }\n')
        refused = lock.pin(copy).refused
        assert f"Two pipelines call themselves acme/rates: {copy} (from its [project] id) and {work / 'rates'}" in refused
        assert "Give one of them an ID of its own with `[project] id`" in refused
        monkeypatch.chdir(copy)
        with pytest.raises(AssetNotPinnedError) as raised:
            data.load("acme/rates:treasury")
        assert raised.value.reason == "cycle"

    def test_a_bare_name_for_the_pipeline_itself_is_refused(self, together, monkeypatch):
        work, forecast, taken = together
        monkeypatch.chdir(work / "rates")
        with pytest.raises(ValueError, match="names this pipeline"):
            data.load("rates:treasury")

    def test_a_read_that_could_not_pin_tries_again_once_there_is_a_snapshot(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(work)
        monkeypatch.chdir(forecast)
        with pytest.warns(WorkingVersionWarning):
            assert _value("acme/rates:treasury") == [7.0]
        snapshot.make(work / "rates")
        pl.DataFrame({"d": ["2024-01-01"], "r": [8.0]}).write_parquet(work / "rates" / "_data" / "treasury.parquet")
        with warnings.catch_warnings():
            warnings.simplefilter("error", WorkingVersionWarning)
            assert _value("acme/rates:treasury") == [7.0]  # the snapshot, pinned now, not the folder's 8.0

    def test_a_cache_setting_that_is_no_path_does_not_stop_a_pin(self, together, monkeypatch, tmp_path):
        from chartbook import config

        work, forecast, taken = together
        monkeypatch.delenv("CHARTBOOK_CACHE", raising=False)
        # This test's own settings, whatever else isolates the user's
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user" / ".chartbook")
        settings = config.get_global_settings_path()
        assert Path.home() not in settings.parents
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("[cache]\npath = 5\n")
        lock.pin(forecast)
        assert lock.read_lock(forecast / lock.LOCK_FILE).dependencies

    def test_no_test_reads_the_users_own_chartbook_folder(self):
        from chartbook import config

        assert config.get_global_config_dir() != Path.home() / ".chartbook"

    def test_a_missing_catalog_file_still_reads_the_store(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        frame = data.load(pipeline="acme/rates", dataframe="treasury", catalog_path=work / "no-such-catalog.toml")
        assert frame.collect()["r"].to_list() == [4.2]


class TestWhatTheThirdReviewFound:
    def test_a_bare_name_another_key_answers_to_is_that_dependency(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        me = work / "me"
        _rates(me, 99.0)
        (me / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "me/rates"},
                "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
                "dependencies": {"up": {"id": "acme/rates"}},
            })
        )
        lock.pin(me)
        monkeypatch.chdir(me)
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        assert _value("rates:treasury") == [4.2]  # acme/rates, pinned as `up`: not this pipeline's own 99.0

    def test_a_broken_dependencies_table_is_said_with_its_file(self, tmp_path, monkeypatch):
        me = tmp_path.resolve() / "me"
        _rates(me, 99.0)
        manifest = (me / "chartbook.toml").read_text()
        (me / "chartbook.toml").write_text(manifest + '\n[dependencies]\nbad = { path = "../x", git = "https://example.invalid/x.git" }\n')
        monkeypatch.chdir(me)
        with pytest.raises(ValueError, match="chartbook.toml: \\[dependencies\\]: 'bad' has both"):
            data.load("acme/rates:treasury")
        assert _value("treasury") == [99.0]  # its own names are its own

    def test_an_unwritable_pipeline_reads_a_version_and_says_why_it_cannot(self, tmp_path, monkeypatch):
        import os

        from chartbook import models

        work = tmp_path.resolve()
        folder, start = _model_pipeline(work)
        forecast = _forecast(work / "forecast", {"acme/model": {}})
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with pytest.warns(UnrecordedReadWarning):
                assert models.path("acme/model:m@champion").read_text() == "v1"
                assert models.path(f"acme/model:m@{start[:8]}").read_text() == "v1"
        finally:
            os.chmod(forecast, 0o755)

    def test_an_unwritable_pipeline_says_two_repositories_claim_it(self, tmp_path, monkeypatch):
        import os

        from tests.test_dependencies_by_id import _another

        work = tmp_path.resolve()
        _another(work, "real", 4.0, remote="https://github.com/acme/rates")
        _claimed_also_by(work, 8.0, "https://github.com/someone/rates")
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with pytest.raises(AssetNotPinnedError, match="2 repositories claim"):
                data.load("acme/rates:treasury")
        finally:
            os.chmod(forecast, 0o755)

    def test_a_snapshot_made_since_is_taken_whatever_the_count_of_records(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        _rates(work / "other", 1.0)
        (work / "other" / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/other"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(work)
        other = snapshot.make(work / "other").snapshot
        monkeypatch.chdir(forecast)
        with pytest.warns(WorkingVersionWarning):
            assert _value("acme/rates:treasury") == [7.0]
        other.path.unlink()  # the store has as many records as before, one of them new
        snapshot.make(work / "rates")
        pl.DataFrame({"d": ["2024-01-01"], "r": [8.0]}).write_parquet(work / "rates" / "_data" / "treasury.parquet")
        assert _value("acme/rates:treasury") == [7.0]

    def test_a_read_lists_the_store_once(self, tmp_path, monkeypatch):
        from chartbook.store import FolderStore

        work = tmp_path.resolve()
        _rates(work / "rates", 7.0)
        forecast = _forecast(work / "forecast", {"acme/rates": {"path": "../rates"}})
        _git(work, "init", "--quiet", "-b", "main")
        _commit(work)
        listed = []
        listing = FolderStore.all_snapshot_files
        monkeypatch.setattr(FolderStore, "all_snapshot_files", lambda self: listed.append(1) or listing(self))
        monkeypatch.chdir(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _value("acme/rates:treasury")
            listed.clear()
            _value("acme/rates:treasury")
        assert len(listed) == 1

    def test_no_test_reads_the_users_sources(self):
        from chartbook import backends

        assert backends.get_global_config_dir() != Path.home() / ".chartbook"

    def test_a_snapshot_without_the_asset_is_an_error_everywhere(self, together, monkeypatch):
        work, forecast, taken = together
        manifest = (work / "rates" / "chartbook.toml").read_text()
        (work / "rates" / "chartbook.toml").write_text(manifest + '\n[dataframes.extra]\npath = "./_data/treasury.parquet"\ndocs = "d"\n')
        (work / "scratch").mkdir()
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        from chartbook import resolve as resolve_module

        monkeypatch.setattr(resolve_module, "get_default_catalog_path", lambda: catalog / "chartbook.toml")
        for where in (work / "scratch", _forecast(work / "reader", {})):
            monkeypatch.chdir(where)
            with pytest.raises(AssetNotPinnedError, match="has no extra"):
                data.load("acme/rates:extra")

    def test_an_unwritable_pipeline_does_not_depend_on_itself(self, elsewhere, monkeypatch):
        import os

        work, first, second = elsewhere
        me = work / "me"
        _rates(me, 5.0)
        manifest = (me / "chartbook.toml").read_text()
        (me / "chartbook.toml").write_text(manifest + '\n[dependencies]\n"acme/rates" = {}\n')
        os.chmod(me, 0o555)
        monkeypatch.chdir(me)
        try:
            with pytest.raises(AssetNotPinnedError, match="cannot depend on itself"):
                data.load("acme/rates:treasury")
        finally:
            os.chmod(me, 0o755)


class TestWhatTheFourthReviewFound:
    def _me(self, work: Path, dependencies: dict) -> Path:
        me = work / "me"
        _rates(me, 99.0)
        (me / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "me/rates"},
                "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
                "dependencies": dependencies,
            })
        )
        return me

    def test_a_broken_entry_does_not_turn_a_bare_name_into_this_pipeline(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        me = self._me(work, {"up": {"id": "acme/rates"}, "bad": {"path": 5}})
        monkeypatch.chdir(me)
        with pytest.raises(ValueError):
            data.load("rates:treasury")
        with pytest.raises(ValueError):
            data.load("me/rates:treasury")  # nor its own full ID: a fork's original might be in it
        assert _value("treasury") == [99.0]

    def test_a_bare_name_two_dependencies_answer_to_is_an_error(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        other = work / "other-repo"
        _rates(other / "rates", 8.0)
        (other / "rates" / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "other/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _git(other, "init", "--quiet", "-b", "main")
        (other / ".gitignore").write_text("_data/\n")
        _commit(other)
        snapshot.make(other / "rates")
        me = self._me(work, {"up": {"id": "acme/rates"}, "down": {"id": "other/rates"}})
        lock.pin(me)
        monkeypatch.chdir(me)
        with pytest.raises(ValueError, match="more than one dependency's: down, up"):
            data.load("rates:treasury")

    def test_a_fork_under_its_originals_id_cannot_read_it(self, together, monkeypatch):
        """Under any key: the fork is told to take an ID of its own."""
        work, forecast, taken = together
        fork = work / "fork"
        _rates(fork, 9.0)  # acme/rates too
        manifest = (fork / "chartbook.toml").read_text()
        (fork / "chartbook.toml").write_text(manifest + '\n[dependencies]\norig = { path = "../rates" }\n')
        monkeypatch.chdir(fork)
        with pytest.raises(AssetNotPinnedError, match="Two pipelines call themselves acme/rates") as raised:
            data.load("orig:treasury")
        assert raised.value.reason == "cycle"

    def test_a_read_only_pipeline_does_not_pin_on_every_read(self, together, monkeypatch):
        import os

        work, forecast, taken = together
        pins = []
        pinning = lock.pin
        monkeypatch.setattr(lock, "pin", lambda *a, **k: pins.append(1) or pinning(*a, **k))
        os.chmod(forecast, 0o555)
        monkeypatch.chdir(forecast)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                for _ in range(5):
                    assert _value("acme/rates:treasury") == [4.0]
        finally:
            os.chmod(forecast, 0o755)
        assert len(pins) == 1


class TestWhatTheFifthReviewFound:
    def test_a_name_an_unidentifiable_dependency_might_be_is_refused(self, tmp_path, monkeypatch):
        import shutil

        work = tmp_path.resolve()
        _rates(work / "rates", 4.0)  # acme/rates
        _git(work, "init", "--quiet", "-b", "main")
        (work / ".gitignore").write_text("_data/\nchartbook.lock\n")
        fork = work / "fork"
        _rates(fork, 9.0)  # acme/rates too
        manifest = (fork / "chartbook.toml").read_text()
        (fork / "chartbook.toml").write_text(manifest + '\n[dependencies]\norig = { path = "../rates" }\n')
        _commit(work)
        snapshot.make(work / "rates")
        assert "Two pipelines call themselves acme/rates" in lock.pin(fork).refused  # an ID names one pipeline
        monkeypatch.chdir(fork)
        with pytest.raises(AssetNotPinnedError) as raised:
            data.load("acme/rates:treasury")  # the original, known by its folder: the fork itself, by its ID
        assert raised.value.reason == "cycle"
        shutil.move(work / "rates", work / "elsewhere")
        with pytest.raises(ValueError, match="names this pipeline"):
            data.load("acme/rates:treasury")  # orig might be it, and is not known to be

    def test_through_a_catalog_only_the_listed_folder_is_this_pipeline(self, together, monkeypatch):
        work, forecast, taken = together
        fork = work / "fork"
        _rates(fork, 9.0)  # acme/rates, and not the folder the catalog lists
        catalog = _catalog(work, {"acme/rates": {"path": "../rates"}})
        monkeypatch.chdir(fork)
        with pytest.raises(ValueError, match="names this pipeline"):
            data.load(pipeline="acme/rates", dataframe="treasury", catalog_path=catalog)


class TestWhatTheSixthReviewFound:
    def test_a_git_dependency_whose_manifest_names_no_id_is_not_taken_for_it(self, tmp_path, monkeypatch):
        work = tmp_path.resolve()
        upstream = work / "upstream"
        _rates(upstream, 4.0)
        (upstream / "chartbook.toml").write_text(
            tomli_w.dumps({"dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _git(upstream, "init", "--quiet", "-b", "main")
        _commit(upstream)  # the parquet is committed: a git dependency has what its repository has
        fork = work / "fork"
        _rates(fork, 9.0)  # acme/rates
        manifest = (fork / "chartbook.toml").read_text()
        (fork / "chartbook.toml").write_text(manifest + '\n[dependencies]\norig = { git = "../upstream" }\n')
        lock.pin(fork)
        monkeypatch.chdir(fork)
        with pytest.raises(ValueError, match="names this pipeline"):
            data.load("acme/rates:treasury")

    def test_a_lockfile_that_cannot_be_read_does_not_stop_other_reads(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        (forecast / "chartbook.lock").write_text("<<<<<<< ours\n{}\n=======\n{}\n>>>>>>> theirs\n")
        monkeypatch.chdir(forecast)
        with pytest.warns(UnrecordedReadWarning):
            assert _value("acme/rates:treasury") == [4.2]

    def test_the_warning_names_a_dependency_that_might_be_it(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"crsp": {"git": "https://example.invalid/acme/crsp.git"}})
        monkeypatch.chdir(forecast)
        with pytest.warns(UnrecordedReadWarning, match="If it is crsp in \\[dependencies\\]"):
            _value("acme/rates:treasury")

    def test_a_pipeline_reads_itself_through_a_catalog_only_by_its_folder(self, together, monkeypatch, tmp_path):
        work, forecast, taken = together
        monkeypatch.chdir(work / "rates")
        with pytest.raises(ValueError, match="names this pipeline"):
            data.load(pipeline="acme/rates", dataframe="treasury", catalog_path=tmp_path / "missing.toml")

    def test_a_folder_is_writable_when_a_file_can_be_made_in_it(self, tmp_path):
        import os

        from chartbook.resolve import _writable

        assert _writable(tmp_path)
        os.chmod(tmp_path, 0o555)
        try:
            assert not _writable(tmp_path)
        finally:
            os.chmod(tmp_path, 0o755)
        assert list(tmp_path.iterdir()) == []


class TestWhatTheSeventhReviewFound:
    def test_a_dependency_given_another_id_is_not_read_under_the_old_one(self, together, monkeypatch):
        import os

        work, forecast, taken = together
        fork = work / "fork"
        _rates(fork, 9.0)  # acme/rates
        manifest = (fork / "chartbook.toml").read_text()
        (fork / "chartbook.toml").write_text(manifest + '\n[dependencies]\norig = { path = "../rates" }\n')
        os.chmod(fork, 0o555)
        monkeypatch.chdir(fork)
        try:
            # Under its original's ID, the fork cannot read it, folder written or not
            with pytest.raises(AssetNotPinnedError) as raised:
                data.load("acme/rates:treasury")
            assert raised.value.reason == "cycle"
            # The original's folder takes another ID, and a snapshot of it
            rates = work / "rates" / "chartbook.toml"
            rates.write_text(rates.read_text().replace('id = "acme/rates"', 'id = "acme/other"'))
            _rates(work / "rates", 7.0)
            rates.write_text(rates.read_text().replace('id = "acme/rates"', 'id = "acme/other"'))
            _commit(work, "Another ID")
            snapshot.make(work / "rates")
            with pytest.raises(ValueError, match="names this pipeline"):
                data.load("acme/rates:treasury")
        finally:
            os.chmod(fork, 0o755)

    def test_the_undeclared_read_never_takes_this_pipelines_own_snapshot(self, together, monkeypatch):
        from chartbook import resolve as resolve_module
        from chartbook.refs import AssetRef

        work, forecast, taken = together
        monkeypatch.chdir(work / "rates")
        own = AssetRef(name="treasury").in_pipeline("acme/rates")
        with pytest.raises(ValueError, match="names this pipeline"):
            resolve_module._read_in_a_pipeline(own, work / "rates", resolve_module._in_a_catalog_folder())

    def test_a_pipeline_that_lists_its_own_folder_is_refused_by_pin_and_read(self, together, monkeypatch):
        work, forecast, taken = together
        rates = work / "rates" / "chartbook.toml"
        rates.write_text(rates.read_text() + '\n[dependencies]\n"acme/rates" = { path = "." }\n')
        report = lock.pin(work / "rates")
        assert any("cannot depend on itself" in (e.detail or "") for e in report.events)
        monkeypatch.chdir(work / "rates")
        with pytest.raises(AssetNotPinnedError, match="cannot depend on itself"):
            data.load("acme/rates:treasury")

    def test_a_lockfile_entry_whose_id_is_no_string_is_skipped(self, elsewhere, monkeypatch):
        import json

        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        document = json.loads(path.read_text())
        (pipeline,) = [r for r in document["records"] if r.get("kind") == "Pipeline"]
        pipeline["dependencies"].append({"id": ["not", "a", "name"], "location": {"kind": "path"}})
        path.write_text(json.dumps(document))
        # acme/rates no longer declared; a folder not on this machine sends the read to the lockfile
        _forecast(forecast, {"gone": {"path": "../gone"}})
        monkeypatch.chdir(forecast)
        with pytest.warns(UnrecordedReadWarning):
            assert _value("acme/rates:treasury") == [4.2]
        # And pin says the lockfile cannot be read, rather than crash
        with pytest.raises(lock.LockError, match="without an id"):
            lock.pin(forecast)

    def test_the_refusal_keeps_the_version_and_names_a_candidate(self, tmp_path, monkeypatch):
        from chartbook import models

        work = tmp_path.resolve()
        folder, start = _model_pipeline(work)
        monkeypatch.chdir(folder)
        with pytest.raises(ValueError, match="'model/m@champion'"):
            models.path("acme/model:m@champion")
        manifest = (folder / "chartbook.toml").read_text()
        (folder / "chartbook.toml").write_text(manifest + '\n[dependencies]\norig = { git = "https://example.invalid/acme/model.git" }\n')
        with pytest.raises(ValueError, match="If you mean orig in \\[dependencies\\]"):
            models.path("acme/model:m@champion")


class TestWhatTheEighthReviewFound:
    def test_another_spelling_of_the_own_folder_is_refused_by_pin(self, together, monkeypatch):
        import os

        work, forecast, taken = together
        upper = work / "RATES"
        if not upper.exists() or not os.path.samefile(upper, work / "rates"):
            # A case-sensitive filesystem: a link spells it differently instead
            os.symlink(work / "rates", work / "rates-link")
            other = "../rates-link"
        else:
            other = "../RATES"
        rates = work / "rates" / "chartbook.toml"
        rates.write_text(rates.read_text() + f'\n[dependencies]\norig = {{ path = "{other}" }}\n')
        report = lock.pin(work / "rates")
        (event,) = [e for e in report.events if e.dependency == "orig"]
        assert event.status == "no_snapshot" and "this pipeline's own folder" in event.detail


class TestWhatTheReleaseReviewFound:
    """The two-argument form and get_data_path read as a reference does: by the rules of the pipeline the calling file is in."""

    @staticmethod
    def _script(folder: Path, body: str) -> Path:
        (folder / "src").mkdir(exist_ok=True)
        script = folder / "src" / "pull.py"
        script.write_text("from chartbook import data\n" + body)
        return script

    def test_a_script_in_a_pipeline_pins_by_either_form_wherever_it_is_run_from(self, together, monkeypatch, capsys):
        work, forecast, taken = together
        script = self._script(
            forecast,
            "from pathlib import Path\n"
            "by_catalog_form = data.load(pipeline='acme/rates', dataframe='treasury').collect()['r'].to_list()\n"
            "pinned_by_it = (Path(__file__).resolve().parents[1] / 'chartbook.lock').is_file()\n"
            "path = data.get_data_path('acme/rates', 'treasury')\n"
            "by_reference = data.load('acme/rates:treasury').collect()['r'].to_list()\n",
        )
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")  # in no pipeline: the script's own folder says which one it is of
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = runpy.run_path(str(script))
        assert result["pinned_by_it"], "the catalog form itself pinned, before the reference form ran"
        assert result["by_catalog_form"] == result["by_reference"] == [4.0]
        said = capsys.readouterr().err
        assert said.count("acme/rates: pinned to its newest snapshot") == 1  # the first read pinned; the others read the pin
        (entry,) = lock.read_lock(forecast / lock.LOCK_FILE).dependencies
        assert entry["location"]["commit"] == taken.commit
        store = Path(os.environ["CHARTBOOK_STORE"]).resolve()
        assert Path(result["path"]).resolve().is_relative_to(store)  # the pinned copy, not the folder's file

    def test_a_pipeline_not_declared_warns_the_same_by_either_form(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        script = self._script(
            forecast,
            "a = data.load(pipeline='acme/rates', dataframe='treasury').collect()['r'].to_list()\n"
            "b = data.load('acme/rates:treasury').collect()['r'].to_list()\n",
        )
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        with pytest.warns(UnrecordedReadWarning) as said:
            result = runpy.run_path(str(script))
        assert result["a"] == result["b"] == [4.2]
        messages = [str(w.message) for w in said if issubclass(w.category, UnrecordedReadWarning)]
        assert len(messages) == 2 and len(set(messages)) == 1
        assert f"newest snapshot, {second.commit[:7]}, and recording nothing" in messages[0]
        assert not (forecast / lock.LOCK_FILE).exists()

    def test_a_batch_run_refuses_every_form_alike(self, together, monkeypatch):
        work, forecast, taken = together
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        for body in (
            "data.load(pipeline='acme/rates', dataframe='treasury')",
            "data.get_data_path('acme/rates', 'treasury')",
            "data.load('acme/rates:treasury')",
        ):
            with pytest.raises(AssetNotPinnedError, match="Run `chartbook pin`") as raised:
                runpy.run_path(str(self._script(forecast, body)))
            assert raised.value.reason == "no_lockfile", body
        assert not (forecast / lock.LOCK_FILE).exists()

    def test_outside_any_pipeline_a_batch_run_reads_nothing(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        for read in (
            lambda: data.load("acme/rates:treasury"),
            lambda: data.load(pipeline="acme/rates", dataframe="treasury"),
            lambda: data.get_data_path("acme/rates", "treasury"),
        ):
            with pytest.raises(AssetNotPinnedError, match="this is no pipeline") as raised:
                read()
            assert raised.value.reason == "no_pipeline"
            assert "reads only what a lockfile pins" in str(raised.value)
        monkeypatch.delenv("CHARTBOOK_BATCH")
        assert _value("acme/rates:treasury") == [4.2]  # interactively, the same read is the quiet one

    def test_the_command_is_in_the_working_directorys_pipeline_not_the_packages(self, together, monkeypatch, tmp_path):
        """`chartbook data get-path` calls from cli.py, so the calling file is the package's own: a manifest above
        the installed package (a monorepo's root, a venv inside a pipeline) must never be the pipeline the command is in."""
        from click.testing import CliRunner

        from chartbook import cli as cli_module
        from chartbook.cli import main

        work, forecast, taken = together
        monorepo = tmp_path.resolve() / "monorepo"
        (monorepo / ".venv" / "lib" / "chartbook").mkdir(parents=True)
        (monorepo / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/other"}, "dataframes": {"x": {"path": "./_data/x.parquet", "docs": "d"}}})
        )
        monkeypatch.setattr(cli_module, "__file__", str(monorepo / ".venv" / "lib" / "chartbook" / "cli.py"))
        monkeypatch.chdir(forecast)
        monkeypatch.setenv("CHARTBOOK_BATCH", "1")
        command = ["data", "get-path", "--pipeline", "acme/rates", "--dataframe", "treasury"]
        result = CliRunner().invoke(main, command)
        assert result.exit_code == 1, result.output
        assert "is not pinned" in result.output and f"Run `chartbook pin` in {forecast}" in result.output
        assert "acme/other" not in result.output
        monkeypatch.delenv("CHARTBOOK_BATCH")
        result = CliRunner().invoke(main, command)
        assert result.exit_code == 0, result.output
        assert (forecast / lock.LOCK_FILE).is_file()  # pinned on the first read, as a script of forecast's would be
        store = Path(os.environ["CHARTBOOK_STORE"]).resolve()
        assert any(Path(line).resolve().is_relative_to(store) for line in result.output.splitlines() if line.strip())


class TestANameInAnotherCase:
    """An ID is case-sensitive: a reference in another case is told the ID, and never matched to it."""

    def test_outside_a_pipeline_the_store_suggests_it(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        (work / "scratch").mkdir()
        monkeypatch.chdir(work / "scratch")
        with pytest.raises(AssetNotPinnedError, match="has no snapshot of Acme/Rates \\(did you mean 'acme/rates'\\?"):
            data.load("Acme/Rates:treasury")

    def test_a_dependency_declared_by_its_id_in_another_case_is_suggested(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.load("Acme/Rates:treasury")
        message = str(raised.value)
        assert "Did you mean 'acme/rates'?" in message
        assert "An ID is case-sensitive" in message
        assert "It is declared: read it as 'acme/rates:treasury'." in message
        assert '"Acme/Rates" = ' not in message  # not told to declare it a second time

    def test_a_key_in_another_case_is_suggested(self, together, monkeypatch):
        work, forecast, taken = together
        _forecast(forecast, {"rates": {"path": "../rates"}})
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.load("RATES:treasury")
        message = str(raised.value)
        assert "Did you mean 'rates'?" in message and "read it as 'rates:treasury'" in message
        assert '"RATES" = { path = "../RATES" }' not in message

    def test_a_dependency_under_another_key_in_another_case_names_the_key(self, together, monkeypatch):
        work, forecast, taken = together
        _forecast(forecast, {"rates": {"path": "../rates"}})  # acme/rates, by the folder's own chartbook.toml
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.load("Acme/Rates:treasury")
        message = str(raised.value)
        assert "Did you mean 'acme/rates'?" in message
        assert "It is declared as 'rates': read it as 'rates:treasury' or 'acme/rates:treasury'." in message
        assert "= { path =" not in message  # not told to declare it a second time

    def test_a_pipeline_the_store_has_in_another_case_is_suggested(self, elsewhere, monkeypatch):
        work, first, second = elsewhere
        forecast = _forecast(work / "forecast", {})
        monkeypatch.chdir(forecast)
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.load("Acme/Rates:treasury")
        message = str(raised.value)
        assert "Did you mean 'acme/rates'?" in message
        assert '"acme/rates" = { path = "../rates" }' in message  # the line to add names the ID as the store has it

    def test_a_part_or_a_revision_alone_names_no_asset(self, together, monkeypatch):
        work, forecast, taken = together
        monkeypatch.chdir(forecast)
        for reference, only in (("#series", "a part"), ("@rev", "a revision")):
            with pytest.raises(ValueError, match=f"names no asset: it is only {only}") as raised:
                data.load(reference)
            assert "'[pipeline:][kind/]name[#part][@rev]'" in str(raised.value)
