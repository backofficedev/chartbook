"""A dependency named by its ID with a `rev`: the newest snapshot at or before the commit the rev names
in its repository (docs_src/design/reading-other-pipelines.md, decision 1a)."""

import sys

import polars as pl
import pytest

from chartbook import data, lock, snapshot
from chartbook.errors import AssetNotPinnedError
from chartbook.manifest import validate_dependencies
from tests.test_default_host import _entry, _set_host, _upstream, host  # noqa: F401 - a fixture
from tests.test_dependencies_by_id import _commit, _forecast, _git


def _newer(repository, value: float, message: str) -> str:
    pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(repository / "_data" / "treasury.parquet")
    (repository / f"{message}.txt").write_text(message)
    _commit(repository, message)
    return _git(repository, "rev-parse", "HEAD").strip()


class TestTheEntry:
    def test_a_rev_is_a_branch_or_tag_and_not_with_a_commit(self, tmp_path):
        assert validate_dependencies({"acme/rates": {"rev": "main"}}, tmp_path)["acme/rates"]["rev"] == "main"
        with pytest.raises(ValueError, match="both 'rev' and 'commit'"):
            validate_dependencies({"acme/rates": {"rev": "main", "commit": "abcdef1"}}, tmp_path)
        with pytest.raises(ValueError):
            validate_dependencies({"acme/rates": {"rev": "--upload-pack=x"}}, tmp_path)


class TestPinned:
    def test_with_no_repository_known_it_says_so(self, tmp_path):
        forecast = _forecast(tmp_path / "forecast", {"acme/rates": {"rev": "main"}})
        (event,) = [e for e in lock.pin(forecast).events if e.status == "no_snapshot"]
        assert "asks its repository" in event.detail and "default_host" in event.detail

    def test_the_newest_snapshot_at_or_before_the_rev(self, host, monkeypatch):
        repository = _upstream(host, 4.0)
        taken = snapshot.make(repository).snapshot  # at the first commit
        _newer(repository, 5.0, "unsnapshotted")  # main moves on, with no snapshot
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}})
        lock.pin(forecast)
        entry = _entry(forecast)
        assert entry["via"] == "store" and entry["location"]["commit"] == taken.commit and entry["location"]["rev"] == "main"
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_with_no_snapshot_on_its_history_it_is_got_from_the_clone(self, host):
        repository = _upstream(host, 4.0)
        _git(repository, "checkout", "--quiet", "-b", "side")
        _newer(repository, 9.0, "side")
        snapshot.make(repository)  # a snapshot on another branch only
        _git(repository, "checkout", "--quiet", "main")
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}})
        lock.pin(forecast)
        entry = _entry(forecast)
        assert entry["via"] == "rev" and entry["location"]["rev"] == "main"
        assert entry["location"]["commit"] == _git(repository, "rev-parse", "main").strip()

    def test_a_pin_keeps_and_an_update_follows_the_rev(self, host):
        repository = _upstream(host, 4.0)
        first = snapshot.make(repository).snapshot
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}})
        lock.pin(forecast)
        _newer(repository, 5.0, "second")
        second = snapshot.make(repository).snapshot
        lock.pin(forecast)
        assert _entry(forecast)["location"]["commit"] == first.commit
        lock.update(forecast)
        assert _entry(forecast)["location"]["commit"] == second.commit

    def test_run_builds_it_when_its_history_has_no_snapshot(self, host):
        from chartbook import run

        script = (
            f"{sys.executable} -c \"import os, polars as pl; os.makedirs('_data', exist_ok=True); "
            f"pl.DataFrame({{'d': ['2024-01-01'], 'r': [6.0]}}).write_parquet('_data/treasury.parquet')\""
        )
        _upstream(host, 6.0, committed=False, scripts={"build": script})
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/rates", "acme/forecast"]

    def test_a_read_never_asks_the_repository(self, host, monkeypatch):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/rates:treasury")
        from chartbook import config
        from pathlib import Path

        git_cache = Path(config.get_git_cache_path())
        assert not git_cache.exists() or not any(git_cache.iterdir())

    def test_the_pipeline_itself_is_refused(self, host):
        forecast = _forecast(host / "forecast", {"acme/forecast": {"rev": "main"}})
        (event,) = [e for e in lock.pin(forecast).events if e.status == "no_snapshot"]
        assert "cannot depend on itself" in event.detail

    def test_with_no_host_a_pin_keeps_what_it_had(self, host):
        repository = _upstream(host, 4.0)
        snapshot.make(repository)
        forecast = _forecast(host / "forecast", {"acme/rates": {"rev": "main"}})
        lock.pin(forecast)
        _set_host(host, "")
        report = lock.pin(forecast)
        assert not report.problems and _entry(forecast)["via"] == "store"
