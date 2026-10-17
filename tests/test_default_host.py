"""A dependency named by its ID that the store has no snapshot of, cloned from `[resolve] default_host`
(docs_src/design/reading-other-pipelines.md, decision 1a, step 4)."""

import sys
from pathlib import Path

import polars as pl
import pytest
import tomli_w

from chartbook import config, data, lock, snapshot
from chartbook.errors import AssetNotPinnedError
from tests.test_dependencies_by_id import _commit, _forecast, _git


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A folder of repositories set as the default host, in this test's own settings."""
    work = tmp_path.resolve()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: work / "user" / ".chartbook")
    settings = config.get_global_settings_path()
    assert Path.home() not in settings.parents
    settings.parent.mkdir(parents=True)
    settings.write_text(tomli_w.dumps({"resolve": {"default_host": str(work / "host")}}))
    return work


def _upstream(work: Path, value: float, committed: bool = True, scripts=None) -> Path:
    """`acme/rates` in its own repository at <host>/acme/rates, its data committed or built by `build`."""
    repository = work / "host" / "acme" / "rates"
    (repository / "_data").mkdir(parents=True)
    manifest = {"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."}}}
    if scripts:
        manifest["scripts"] = scripts
    (repository / "chartbook.toml").write_text(tomli_w.dumps(manifest))
    if committed:
        pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(repository / "_data" / "treasury.parquet")
    else:
        (repository / ".gitignore").write_text("_data/\n")
    _git(repository, "init", "--quiet", "-b", "main")
    _commit(repository)
    return repository


def _entry(forecast: Path) -> dict:
    (entry,) = lock.read_lock(forecast / lock.LOCK_FILE).dependencies
    return entry


class TestTheSetting:
    def test_the_address_of_an_id(self):
        assert config.clone_url_for("acme/rates", "github.com") == "https://github.com/acme/rates"
        assert config.clone_url_for("acme/rates", "https://gitlab.example.org/group") == "https://gitlab.example.org/group/acme/rates"
        assert config.clone_url_for("acme/rates", "git@gitlab.example.org:") == "git@gitlab.example.org:acme/rates"
        assert config.clone_url_for("acme/rates", "/srv/git") == "/srv/git/acme/rates"
        assert config.clone_url_for("acme/rates", "gitlab.example.org/group") == "https://gitlab.example.org/group/acme/rates"
        assert config.clone_url_for("acme/rates", "repos") == "https://repos/acme/rates"  # a host name, not a folder
        assert config.clone_url_for("rates", "github.com") is None  # no owner to find it under
        assert config.clone_url_for("acme/rates", "") is None

    def test_a_folder_of_repositories_is_relative_to_its_settings_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text('[resolve]\ndefault_host = "./repositories"\n')
        assert config.get_default_host() == str(tmp_path / "user" / "repositories")

    def test_an_empty_host_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text('[resolve]\ndefault_host = ""\n')
        assert config.get_default_host() == ""

    def test_a_host_that_is_no_text_is_said(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text("[resolve]\ndefault_host = 5\n")
        with pytest.raises(ValueError, match="default_host must be a git host"):
            config.get_default_host()


class TestNoSnapshotSoItsRepository:
    def test_pin_clones_it_from_the_default_host(self, host, monkeypatch):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        assert not report.problems and "acme/rates" in report.git
        entry = _entry(forecast)
        assert entry["via"] == "rev" and entry["location"]["kind"] == "git"
        assert entry["location"]["pipeline"] == "acme/rates" and "url" not in entry["location"]
        assert str(host) not in (forecast / lock.LOCK_FILE).read_text()  # no address of this machine's
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]
        assert not lock.verify(forecast).problems  # --frozen agrees it is pinned from where the manifest says

    def test_with_no_default_host_it_is_the_store_only(self, tmp_path):
        _upstream(tmp_path.resolve(), 4.0)
        forecast = _forecast(tmp_path.resolve() / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        assert [e.status for e in report.events if e.dependency == "acme/rates"] == ["no_snapshot"]

    def test_once_there_is_a_snapshot_update_takes_it(self, host):
        repository = _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        pl.DataFrame({"d": ["2024-01-01"], "r": [5.0]}).write_parquet(repository / "_data" / "treasury.parquet")
        _commit(repository, "Newer")
        snapshot.make(repository)
        report = lock.pin(forecast)  # a pin keeps where it was pinned from, and does not call it moved
        assert not [e for e in report.events if e.status == "relocated"] and _entry(forecast)["via"] == "rev"
        lock.update(forecast)
        entry = _entry(forecast)
        assert entry["via"] == "store" and entry["location"]["kind"] == "store"

    def test_run_builds_it_when_its_data_is_not_committed(self, host):
        from chartbook import run

        script = (
            f"{sys.executable} -c \"import os, polars as pl; os.makedirs('_data', exist_ok=True); "
            f"pl.DataFrame({{'d': ['2024-01-01'], 'r': [6.0]}}).write_parquet('_data/treasury.parquet')\""
        )
        _upstream(host, 6.0, committed=False, scripts={"build": script})
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/rates", "acme/forecast"]
        record = next(r for r in lock.read_lock(forecast / lock.LOCK_FILE).assets.values() if r.get("content_hash"))
        assert record["id"] == "acme/rates:treasury"

    def test_a_read_never_clones(self, host, monkeypatch):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/rates:treasury")
        git_cache = Path(config.get_git_cache_path())
        assert not git_cache.exists() or not any(git_cache.iterdir())

    def test_the_pipeline_itself_and_a_bare_id_are_never_cloned(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/forecast": {}, "rates": {}})
        report = lock.pin(forecast)
        assert not report.git

    def test_a_store_pin_whose_snapshots_are_cleared_is_kept_and_nothing_is_cloned(self, host):
        repository = _upstream(host, 4.0)
        taken = snapshot.make(repository).snapshot
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _entry(forecast)["via"] == "store"
        taken.path.unlink()  # gc, or another machine's store
        report = lock.pin(forecast)
        assert _entry(forecast)["via"] == "store" and not report.problems
        git_cache = Path(config.get_git_cache_path())
        assert not git_cache.exists() or not any(git_cache.iterdir())

    def test_check_says_nothing_of_one_pinned_from_its_repository(self, host):
        import warnings

        from chartbook.check import check_dependencies
        from chartbook.manifest import load_manifest

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert check_dependencies(load_manifest(forecast), forecast) == []


def _set_host(work: Path, value: str) -> None:
    settings = config.get_global_settings_path()
    settings.write_text(tomli_w.dumps({"resolve": {"default_host": value}}))


class TestWhatTheReviewFound:
    def test_a_catalog_run_never_clones_its_own_pipeline(self, host):
        from chartbook import run

        _upstream(host, 9.0)  # the host's acme/rates: never to be built here
        marker = host / "host-built"
        (host / "host" / "acme" / "rates" / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/rates"},
                "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
                "scripts": {"build": f"{sys.executable} -c \"open(r'{marker}', 'w').close()\""},
            })
        )
        _commit(host / "host" / "acme" / "rates", "A build")
        catalog = host / "catalog"
        rates = catalog / "rates"
        (rates / "_data").mkdir(parents=True)
        (rates / "chartbook.toml").write_text(tomli_w.dumps({
            "project": {"id": "acme/rates"},
            "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
            "scripts": {"build": f"{sys.executable} -c \"import polars as pl; pl.DataFrame({{'d': ['2024-01-01'], 'r': [1.0]}}).write_parquet('_data/treasury.parquet')\""},
        }))
        _forecast(catalog / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        (catalog / "chartbook.toml").write_text(tomli_w.dumps({
            "project": {"type": "catalog", "id": "cat"},
            "pipelines": {"acme/forecast": {"path": "./forecast"}, "acme/rates": {"path": "./rates"}},
        }))
        _git(catalog, "init", "--quiet", "-b", "main")
        (catalog / ".gitignore").write_text("_data/\nchartbook.lock\n")
        _commit(catalog)
        report = run.run(catalog, snapshot=True, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/rates", "acme/forecast"]
        assert not marker.exists()
        assert _entry(catalog / "forecast")["via"] == "store"

    def test_a_pin_from_its_repository_puts_lost_bytes_back(self, host):
        repository = _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        (record,) = [r for r in lock.read_lock(forecast / lock.LOCK_FILE).assets.values() if r.get("content_hash")]
        from chartbook.store import default_store

        store = default_store()
        import shutil

        shutil.rmtree(store.get(record["content_hash"]))
        assert not store.has(record["content_hash"])
        snapshot.make(repository)  # the store has a snapshot of it now; the pin stays from the repository
        lock.pin(forecast)
        assert store.has(record["content_hash"]) and _entry(forecast)["via"] == "rev"

    def test_with_no_host_a_pin_from_its_repository_is_kept_and_its_loss_said(self, host):
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        _upstream(host, 4.0)
        lock.pin(forecast)
        _set_host(host, "")
        report = lock.pin(forecast)
        assert _entry(forecast)["via"] == "rev" and {e.status for e in report.events if e.asset} == {"kept"}

    def test_run_follows_the_lockfile_and_does_not_clone_a_store_pin(self, host):
        from chartbook import run

        repository = _upstream(host, 4.0)
        taken = snapshot.make(repository).snapshot
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        lock.pin(forecast)
        assert _entry(forecast)["via"] == "store"
        taken.path.unlink()  # its snapshot record is gone from the store
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["acme/forecast"]
        git_cache = Path(config.get_git_cache_path())
        assert not git_cache.exists() or not any(git_cache.iterdir())

    def test_another_spelling_of_the_host_changes_nothing(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _set_host(host, "file://" + str(host / "host"))
        report = lock.pin(forecast)
        assert not [e for e in report.events if e.status == "relocated"]
        assert not lock.verify(forecast).problems

    def test_a_commit_given_since_is_a_change_of_place(self, host):
        repository = _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        snapshot.make(repository)
        _forecast(forecast, {"acme/rates": {"commit": "0000000"}})
        assert any(e.status == "relocated" for e in lock.pin(forecast).events)
        assert lock.verify(forecast).problems

    def test_the_named_repository_is_the_one_cloned(self):
        entry = {"_store": "acme/rates", "_repository": "https://github.com/someone/rates-fork"}
        converted = lock.clone_instead(entry, "acme/forecast", None, False, lambda: [], "github.com")
        assert converted["git"] == "https://github.com/someone/rates-fork" and converted["_from_id"] == "acme/rates"

    def test_update_by_its_full_id_before_any_snapshot(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        report = lock.update(forecast, ["acme/rates"])
        assert not report.problems and _entry(forecast)["via"] == "rev"

    def test_a_repository_that_names_itself_otherwise_is_not_pinned(self, host):
        repository = _upstream(host, 4.0)
        (repository / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "evil/other"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}})
        )
        _commit(repository, "Another name")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "unfetched"]
        assert "names itself evil/other" in event.detail

    def test_a_failed_clone_says_why_it_was_tried(self, host):
        forecast = _forecast(host / "forecast", {"acme/nothing": {}})
        (event,) = [e for e in lock.pin(forecast).events if e.status == "unfetched"]
        assert "the store has no snapshot of acme/nothing" in event.detail and "default_host" in event.detail

    def test_a_read_says_pin_would_get_it(self, host, monkeypatch):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="`chartbook pin` gets it from its repository"):
            data.load("acme/rates:treasury")

    def test_the_index_says_it_came_from_its_repository(self, host):
        import json

        import jsonschema

        from chartbook.index import SCHEMAS_DIR, build_index
        from chartbook.manifest import load_manifest

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        built = build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r.get("kind") == "Pipeline"]
        (dependency,) = record["dependencies"]
        assert dependency["via"] == "rev" and dependency["location"]["kind"] == "git" and dependency["location"]["pipeline"] == "acme/rates"
        jsonschema.validate(record, json.loads((Path(SCHEMAS_DIR) / "v1" / "Pipeline.json").read_text()))
