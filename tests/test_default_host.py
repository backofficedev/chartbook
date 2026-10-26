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
from tests.fixtures import remove_tree


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A folder of repositories set as the default host, in this test's own settings."""
    work = tmp_path.resolve()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: work / "user" / ".chartbook")
    settings = config.get_global_settings_path()
    assert not settings.is_relative_to(Path.home() / ".chartbook")  # not the real one; a temporary folder may be under home (Windows)
    settings.parent.mkdir(parents=True)
    settings.write_text(tomli_w.dumps({"resolve": {"default_host": str(work / "host")}}), encoding="utf-8")
    return work


def _upstream(work: Path, value: float, committed: bool = True, scripts=None) -> Path:
    """`acme/rates` in its own repository at <host>/acme/rates, its data committed or built by `build`."""
    repository = work / "host" / "acme" / "rates"
    (repository / "_data").mkdir(parents=True)
    manifest = {"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "Rates."}}}
    if scripts:
        manifest["scripts"] = scripts
    (repository / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
    if committed:
        pl.DataFrame({"d": ["2024-01-01"], "r": [value]}).write_parquet(repository / "_data" / "treasury.parquet")
    else:
        (repository / ".gitignore").write_text("_data/\n", encoding="utf-8")
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
        config.get_global_settings_path().write_text('[resolve]\ndefault_host = "./repositories"\n', encoding="utf-8")
        assert config.get_default_host() == str(tmp_path / "user" / "repositories")

    def test_an_empty_host_is_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text('[resolve]\ndefault_host = ""\n', encoding="utf-8")
        assert config.get_default_host() == ""

    def test_a_host_that_is_no_text_is_said(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text("[resolve]\ndefault_host = 5\n", encoding="utf-8")
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
        assert str(host) not in (forecast / lock.LOCK_FILE).read_text(encoding="utf-8")  # no address of this machine's
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
    settings.write_text(tomli_w.dumps({"resolve": {"default_host": value}}), encoding="utf-8")


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
            }), encoding="utf-8"
        )
        _commit(host / "host" / "acme" / "rates", "A build")
        catalog = host / "catalog"
        rates = catalog / "rates"
        (rates / "_data").mkdir(parents=True)
        (rates / "chartbook.toml").write_text(tomli_w.dumps({
            "project": {"id": "acme/rates"},
            "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
            "scripts": {"build": f"{sys.executable} -c \"import polars as pl; pl.DataFrame({{'d': ['2024-01-01'], 'r': [1.0]}}).write_parquet('_data/treasury.parquet')\""},
        }), encoding="utf-8")
        _forecast(catalog / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        (catalog / "chartbook.toml").write_text(tomli_w.dumps({
            "project": {"type": "catalog", "id": "cat"},
            "pipelines": {"acme/forecast": {"path": "./forecast"}, "acme/rates": {"path": "./rates"}},
        }), encoding="utf-8")
        _git(catalog, "init", "--quiet", "-b", "main")
        (catalog / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8")
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

        remove_tree(store.get(record["content_hash"]))
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
        entry = {
            "_store": "acme/rates",
            "repository": "ssh://git@gitlab.internal:2222/someone/rates-fork.git",
            "_repository": "https://gitlab.internal/someone/rates-fork",
        }
        converted = lock.clone_instead(entry, "acme/forecast", None, False, lambda: [], "github.com", pinned=False)
        # As written, with its scheme and port: the web form is for telling repositories apart
        assert converted["git"] == "ssh://git@gitlab.internal:2222/someone/rates-fork.git" and converted["_from_id"] == "acme/rates"

    def test_update_by_its_full_id_before_any_snapshot(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        report = lock.update(forecast, ["acme/rates"])
        assert not report.problems and _entry(forecast)["via"] == "rev"

    def test_a_repository_that_names_itself_otherwise_is_not_pinned(self, host):
        repository = _upstream(host, 4.0)
        (repository / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "evil/other"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}), encoding="utf-8"
        )
        _commit(repository, "Another name")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        report = lock.pin(forecast)
        (event,) = [e for e in report.events if e.status == "unfetched"]
        assert "gives the ID evil/other, not acme/rates" in event.detail

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
        jsonschema.validate(record, json.loads((Path(SCHEMAS_DIR) / "v1" / "Pipeline.json").read_text(encoding="utf-8")))



class TestWhatTheSecondReviewFound:
    def test_a_failed_first_read_does_not_stop_a_pin_from_getting_it(self, host, monkeypatch):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError):
            data.load("acme/rates:treasury")  # writes an entry with nothing pinned
        report = lock.pin(forecast)
        assert "acme/rates" in report.git and _entry(forecast)["via"] == "rev"
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_a_pin_made_before_the_host_was_set_gets_it_once_it_is(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        _set_host(host, "")
        lock.pin(forecast)
        _set_host(host, str(host / "host"))
        assert "acme/rates" in lock.pin(forecast).git

    def test_an_update_that_finds_nothing_keeps_a_repository_pin(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _set_host(host, "")
        lock.update(forecast)
        assert _entry(forecast)["via"] == "rev" and _entry(forecast)["location"]["kind"] == "git"

    def test_a_commit_asked_for_is_got_from_the_repository_when_the_store_has_another(self, host):
        repository = _upstream(host, 4.0)
        first = _git(repository, "rev-parse", "HEAD").strip()
        pl.DataFrame({"d": ["2024-01-01"], "r": [5.0]}).write_parquet(repository / "_data" / "treasury.parquet")
        _commit(repository, "Second")
        snapshot.make(repository)  # a snapshot, at the second commit only
        forecast = _forecast(host / "forecast", {"acme/rates": {"commit": first[:7]}})
        lock.pin(forecast)
        entry = _entry(forecast)
        assert entry["via"] == "rev" and entry["location"]["commit"] == first
        lock.update(forecast)
        assert _entry(forecast)["via"] == "rev"

    def test_the_index_keeps_every_pinned_hash(self, host):
        from chartbook.index import build_index
        from chartbook.manifest import load_manifest

        _upstream(host, 4.0)
        other = host / "host" / "acme" / "yields"
        (other / "_data").mkdir(parents=True)
        (other / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/yields"}, "dataframes": {"curve": {"path": "./_data/curve.parquet", "docs": "d"}}}), encoding="utf-8")
        pl.DataFrame({"d": ["2024-01-01"]}).write_parquet(other / "_data" / "curve.parquet")
        _git(other, "init", "--quiet", "-b", "main")
        (other / ".gitignore").write_text("_data/\n", encoding="utf-8")
        _commit(other)
        snapshot.make(other)
        forecast = _forecast(host / "forecast", {"acme/rates": {}, "acme/yields": {}})
        lock.pin(forecast)
        built = build_index(load_manifest(forecast))
        (record,) = [r for r in built["records"] if r.get("kind") == "Pipeline"]
        assert all(dependency.get("pinned_hash") for dependency in record["dependencies"])

    def test_run_does_not_build_a_clone_that_names_itself_otherwise(self, host):
        from chartbook import run

        repository = _upstream(host, 4.0)
        marker = host / "built"
        (repository / "chartbook.toml").write_text(tomli_w.dumps({
            "project": {"id": "evil/other"},
            "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
            "scripts": {"build": f"{sys.executable} -c \"open(r'{marker}', 'w').close()\""},
        }), encoding="utf-8")
        _commit(repository, "Another name")
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is not None and not marker.exists()

    def test_a_pipeline_depending_on_itself_by_id_is_said_plainly_by_run(self, host):
        from chartbook import run

        forecast = _forecast(host / "forecast", {"acme/forecast": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        # Refused before anything is pinned, as every cycle is (tests/test_dependency_cycles.py)
        with pytest.raises(run.RunError) as raised:
            run.run(forecast, echo=lambda *a, **k: None)
        assert str(raised.value).startswith("acme/forecast: it depends on itself, so there is no order to build in.")
        assert "depend on each other" not in str(raised.value)
        assert not (forecast / "chartbook.lock").exists()

    def test_a_root_folder_host_keeps_its_separator(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "user")
        (tmp_path / "user").mkdir()
        config.get_global_settings_path().write_text('[resolve]\ndefault_host = "/"\n', encoding="utf-8")
        assert config.get_default_host() == "/"


class TestWhatTheThirdReviewFound:
    def test_a_failed_clone_leaves_nothing_that_keeps_it_from_the_store(self, host):
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)  # the host has no acme/rates: the clone fails, nothing is pinned
        elsewhere = host / "elsewhere"
        (elsewhere / "_data").mkdir(parents=True)
        (elsewhere / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}), encoding="utf-8")
        pl.DataFrame({"d": ["2024-01-01"], "r": [3.0]}).write_parquet(elsewhere / "_data" / "treasury.parquet")
        _git(elsewhere, "init", "--quiet", "-b", "main")
        (elsewhere / ".gitignore").write_text("_data/\n", encoding="utf-8")
        _commit(elsewhere)
        snapshot.make(elsewhere)
        report = lock.pin(forecast)
        assert not report.git and _entry(forecast)["via"] == "store"
        _set_host(host, "")
        assert not lock.pin(forecast).problems

    def test_a_refused_clone_records_none_of_its_commit(self, host):
        repository = _upstream(host, 4.0)
        (repository / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "evil/other"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}), encoding="utf-8")
        _commit(repository, "Another name")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert "commit" not in _entry(forecast)["location"]

    def test_a_store_listing_with_bytes_and_no_commit_stays_in_the_store(self):
        entry = {"_store": "acme/rates"}
        was = {"id": "acme/rates", "via": "store", "location": {"kind": "store", "pipeline": "acme/rates"}}
        assert lock.clone_instead(entry, "acme/forecast", was, False, lambda: [], "github.com", pinned=True) is entry

    def test_a_named_repository_with_no_snapshot_of_its_own_is_cloned(self):
        from types import SimpleNamespace

        entry = {"_store": "acme/rates", "repository": "https://example.org/acme/rates", "_repository": "https://example.org/acme/rates"}
        others = [SimpleNamespace(pipeline="acme/rates", commit="a" * 40, repository="https://example.org/someone/rates", made_at="2026-01-01T00:00:00.000000Z")]
        converted = lock.clone_instead(entry, "acme/forecast", None, False, lambda: others, "github.com", pinned=False)
        assert converted["git"] == "https://example.org/acme/rates"

    def test_the_read_names_the_address_pin_would_use(self, host, monkeypatch):
        forecast = _forecast(host / "forecast", {"acme/rates": {"repository": "https://example.invalid/someone/rates", "commit": "abcdef1"}})
        monkeypatch.chdir(forecast)
        with pytest.raises(AssetNotPinnedError, match="from its repository at abcdef1, https://example.invalid/someone/rates \\(the repository its entry names\\)"):
            data.load("acme/rates:treasury")

    def test_an_update_with_no_host_keeps_a_repository_pin_and_says_no_problem(self, host):
        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _set_host(host, "")
        report = lock.update(forecast)
        assert not report.problems and _entry(forecast)["via"] == "rev"

    def test_a_clone_whose_project_is_no_table_does_not_crash_run(self, host):
        from chartbook import run

        repository = _upstream(host, 4.0)
        (repository / "chartbook.toml").write_text('project = "not a table"\n', encoding="utf-8")
        _commit(repository, "Broken")
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        try:
            report = run.run(forecast, echo=lambda *a, **k: None)
        except (ValueError, run.RunError):
            return  # said, not a crash
        assert report.failed is not None



class TestWhatTheFourthReviewFound:
    def test_an_update_keeps_to_the_repository_it_was_got_from(self, host):
        from tests.test_dependencies_by_id import _another

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _entry(forecast)["location"].get("first_commit")
        _another(host, "mallory", 666.0, remote="https://example.org/mallory/rates")  # another repository's acme/rates
        report = lock.update(forecast)
        assert not [e for e in report.events if e.status == "moved"] and _entry(forecast)["via"] == "rev"
        _set_host(host, "")  # and with no host, the store branch keeps to it too
        report = lock.update(forecast)
        assert not [e for e in report.events if e.status == "moved"] and _entry(forecast)["via"] == "rev"

    def test_a_clone_whose_id_is_no_name_is_refused(self, host):
        repository = _upstream(host, 4.0)
        (repository / "chartbook.toml").write_text('[project]\nid = 5\n\n[dataframes.treasury]\npath = "./_data/treasury.parquet"\ndocs = "d"\n', encoding="utf-8")
        _commit(repository, "A number")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        (event,) = [e for e in lock.pin(forecast).events if e.status == "unfetched"]
        assert "an id that is no name" in event.detail

    def test_an_update_with_no_host_and_only_other_snapshots_keeps_the_pin_quietly(self, host):
        from tests.test_dependencies_by_id import _another

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _another(host, "mallory", 666.0, remote="https://example.org/mallory/rates")
        _set_host(host, "")
        report = lock.update(forecast)
        assert not report.problems and _entry(forecast)["via"] == "rev"

    def test_a_pinned_flag_must_be_given(self):
        with pytest.raises(TypeError):
            lock.clone_instead({"_store": "acme/rates"}, "acme/forecast", None, False, lambda: [], "github.com")


def _mallory(host: Path, value: float = 666.0):
    from tests.test_dependencies_by_id import _another

    return _another(host, "mallory", value, remote="https://example.org/mallory/rates")


class TestWhatTheFifthReviewFound:
    def test_a_git_dir_in_the_environment_does_not_lose_the_first_commit(self, host, monkeypatch):
        _upstream(host, 4.0)
        elsewhere = host / "elsewhere-repo"
        _git(elsewhere if elsewhere.mkdir() is None else elsewhere, "init", "--quiet", "-b", "main")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))  # as a git hook in a linked worktree has
        lock.pin(forecast)
        monkeypatch.delenv("GIT_DIR")
        assert _entry(forecast)["location"].get("first_commit")

    def test_a_repository_pin_whose_first_commit_is_unknown_is_not_moved_to_another(self, host, monkeypatch):
        import json

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        path = forecast / lock.LOCK_FILE
        document = json.loads(path.read_text(encoding="utf-8"))
        (pipeline,) = [r for r in document["records"] if r.get("kind") == "Pipeline"]
        del pipeline["dependencies"][0]["location"]["first_commit"]  # as an older pin has it
        path.write_text(json.dumps(document), encoding="utf-8")
        _mallory(host)
        lock.update(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]
        _set_host(host, "")
        lock.update(forecast)
        assert data.load("acme/rates:treasury").collect()["r"].to_list() == [4.0]

    def test_a_repository_pin_not_built_yet_is_got_again_not_stuck(self, host):
        from chartbook import run

        script = (
            f"{sys.executable} -c \"import os, polars as pl; os.makedirs('_data', exist_ok=True); "
            f"pl.DataFrame({{'d': ['2024-01-01'], 'r': [6.0]}}).write_parquet('_data/treasury.parquet')\""
        )
        _upstream(host, 6.0, committed=False, scripts={"build": script})
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        lock.pin(forecast)  # not built: nothing of its bytes pinned
        _mallory(host)
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert _entry(forecast)["via"] == "rev"

    def test_an_update_does_not_take_another_repository_from_the_host(self, host, monkeypatch, tmp_path):
        _upstream(host, 4.0)
        _mallory(host)  # the store's only acme/rates is mallory's
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert _entry(forecast)["via"] == "store"
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another-machines-store"))
        report = lock.update(forecast)
        (event,) = [e for e in report.events if e.status == "unfetched"]
        assert "history begins at" in event.detail and 'repository = "..."' in event.detail
        assert _entry(forecast)["via"] == "store"

    def test_a_rewritten_history_is_said_not_followed(self, host):
        repository = _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        _git(repository, "checkout", "--quiet", "--orphan", "fresh")
        _commit(repository, "A history started again")
        _git(repository, "branch", "--quiet", "-D", "main")
        _git(repository, "branch", "--quiet", "-m", "main")
        report = lock.update(forecast)
        assert any(e.status == "unfetched" and "history rewritten" in e.detail for e in report.events)

    def test_an_own_snapshot_dated_ahead_does_not_block_an_update(self, host):
        import dataclasses

        from chartbook.store import default_store

        repository = _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        taken = snapshot.make(repository).snapshot
        taken.path.unlink()
        snapshot._write(dataclasses.replace(taken, made_at="2099-01-01T00:00:00.000000Z"), default_store())
        pl.DataFrame({"d": ["2024-01-01"], "r": [5.0]}).write_parquet(repository / "_data" / "treasury.parquet")
        _commit(repository, "Newer")
        report = lock.update(forecast)
        assert not report.problems and _entry(forecast)["via"] == "rev"



def _model_repository(path: Path, model_id: str, version: str, label: bool, remote=None, snapshotted=True) -> Path:
    """A pipeline with one model, in its own repository: built, labelled `champion` if asked, snapshotted if asked."""
    (path / "_output").mkdir(parents=True)
    manifest = {"project": {"id": model_id}, "models": {"m": {"path": "./_output/m.json"}}}
    (path / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
    (path / "_output" / "m.json").write_text(version, encoding="utf-8")
    _git(path, "init", "--quiet", "-b", "main")
    if remote:
        _git(path, "remote", "add", "origin", remote)
    (path / ".gitignore").write_text("chartbook.lock\n", encoding="utf-8")
    _commit(path, f"{model_id} {version}")
    if not snapshotted:
        return path
    first = snapshot.make(path, made_at="2026-01-01T00:00:00.000000Z").snapshot
    if label:
        start = first.assets["model/m"]["content_hash"].split(":", 1)[1][:12]
        manifest["models"]["m"]["aliases"] = {"champion": start}
        (path / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8")
        (path / "_output" / "m.json").write_text(version + "-later", encoding="utf-8")
        _commit(path, "Champion")
        snapshot.make(path)
    return path


class TestWhatTheSixthReviewFound:
    def test_an_id_changed_under_its_key_is_updated_not_refused(self, host):
        _upstream(host, 4.0)
        other = host / "host" / "acme" / "rates2"
        (other / "_data").mkdir(parents=True)
        (other / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "acme/rates2"}, "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}}}), encoding="utf-8")
        pl.DataFrame({"d": ["2024-01-01"], "r": [2.0]}).write_parquet(other / "_data" / "treasury.parquet")
        _git(other, "init", "--quiet", "-b", "main")
        _commit(other)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        _forecast(forecast, {"rates": {"id": "acme/rates2"}})
        report = lock.update(forecast)
        assert not report.problems and _entry(forecast)["location"]["pipeline"] == "acme/rates2"

    def test_a_refused_clone_keeps_a_store_pins_labels(self, host, monkeypatch, tmp_path):
        _model_repository(host / "mallory-model", "acme/model", "v1", label=True)
        _model_repository(host / "host" / "acme" / "model", "acme/model", "x1", label=False, snapshotted=False)
        forecast = _forecast(host / "forecast", {"acme/model": {}})
        lock.pin(forecast)
        assert _entry(forecast)["via"] == "store"
        labels = [a for a in lock.read_lock(forecast / lock.LOCK_FILE).assets if "@champion" in a]
        assert labels
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another-machines-store"))
        report = lock.update(forecast)
        assert any(e.status == "unfetched" for e in report.events) and not report.git
        assert [a for a in lock.read_lock(forecast / lock.LOCK_FILE).assets if "@champion" in a] == labels

    def test_a_store_pin_with_no_first_commit_is_not_given_another_repository(self, host, monkeypatch, tmp_path):
        import dataclasses

        from chartbook.store import default_store

        _upstream(host, 4.0)
        taken = _mallory(host)
        taken.path.unlink()
        snapshot._write(dataclasses.replace(taken, first_commit=""), default_store())  # as from a shallow clone
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        assert "first_commit" not in _entry(forecast)["location"]
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another-machines-store"))
        report = lock.update(forecast)
        (event,) = [e for e in report.events if e.status == "unfetched"]
        assert "does not have" in event.detail and "remove 'acme/rates' from chartbook.lock" in event.detail
        assert _entry(forecast)["via"] == "store"

    def test_a_git_hook_environment_never_reaches_the_users_repository(self, host, monkeypatch):
        _upstream(host, 4.0)
        user = host / "users-repository"
        user.mkdir()
        _git(user, "init", "--quiet", "-b", "main")
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        monkeypatch.setenv("GIT_DIR", str(user / ".git"))
        monkeypatch.setenv("GIT_COMMON_DIR", str(user / ".git"))
        monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(user / ".git" / "objects"))
        lock.pin(forecast)
        for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
            monkeypatch.delenv(name)
        assert _git(user, "config", "--get", "core.bare").strip() == "false"
        assert _entry(forecast)["via"] == "rev"



class TestWhatTheSeventhReviewFound:
    def test_an_id_changed_with_nothing_to_take_keeps_the_old_listing_whole(self, host):
        repository = _upstream(host, 4.0)
        snapshot.make(repository)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        before = _entry(forecast)
        _set_host(host, "")
        _forecast(forecast, {"rates": {"id": "acme/rates2"}})
        lock.update(forecast)
        assert _entry(forecast)["location"] == before["location"]  # not acme/rates2 at acme/rates's commit

    def test_a_store_pin_kept_whole_offline_is_no_trouble_and_its_losses_are_said(self, host, monkeypatch, tmp_path):
        repository = _upstream(host, 4.0)
        snapshot.make(repository)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        _forecast(forecast, {"rates": {"git": str(host / "no-such-repository")}})
        report = lock.pin(forecast)
        assert not report.problems and any(e.status == "kept" for e in report.events)
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "an-empty-store"))
        report = lock.pin(forecast)
        assert any(e.status == "lost" for e in report.events)

    def test_a_pinned_commit_on_no_branch_is_asked_for_by_its_hash(self, host, monkeypatch, tmp_path):
        import dataclasses

        from chartbook.store import default_store

        repository = _upstream(host, 4.0)
        _git(repository, "checkout", "--quiet", "-b", "side")
        pl.DataFrame({"d": ["2024-01-01"], "r": [5.0]}).write_parquet(repository / "_data" / "treasury.parquet")
        _commit(repository, "On a side branch")
        taken = snapshot.make(repository).snapshot
        taken.path.unlink()
        snapshot._write(dataclasses.replace(taken, first_commit=""), default_store())  # as from a shallow clone
        _git(repository, "checkout", "--quiet", "main")
        _git(repository, "branch", "--quiet", "-D", "side")  # the commit is on no branch now
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        lock.pin(forecast)
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "another-machines-store"))
        report = lock.update(forecast)
        assert not [e for e in report.events if e.status == "unfetched"] and _entry(forecast)["via"] == "rev"

    def test_a_git_dependencys_build_does_not_see_a_hooks_repository(self, host, monkeypatch):
        from chartbook import run

        user = host / "users-repository"
        user.mkdir()
        _git(user, "init", "--quiet", "-b", "main")
        marker = host / "what-the-build-saw"
        script = f"{sys.executable} -c \"import os; open(r'{marker}', 'w').write(os.environ.get('GIT_DIR', 'none'))\""
        _upstream(host, 4.0, scripts={"build": script})
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        monkeypatch.setenv("GIT_DIR", str(user / ".git"))
        report = run.run(forecast, echo=lambda *a, **k: None)
        monkeypatch.delenv("GIT_DIR")
        assert report.failed is None, report.reason
        assert marker.read_text(encoding="utf-8") == "none"



class TestWhatTheEighthReviewFound:
    def test_a_commit_in_the_lockfile_never_reaches_git_as_an_option(self, host, monkeypatch, tmp_path):
        import json

        _upstream(host, 4.0)
        forecast = _forecast(host / "forecast", {"acme/rates": {}})
        marker = tmp_path / "MARKER"
        document = {
            "schema": lock.SCHEMA, "root": "acme/forecast",
            "records": [{
                "kind": "Pipeline", "version": lock.RECORD_VERSION, "id": "acme/forecast",
                "dependencies": [{"id": "acme/rates", "via": "store", "location": {
                    "kind": "store", "pipeline": "acme/rates", "commit": f"--upload-pack=touch {marker};",
                }}],
            }],
        }
        (forecast / lock.LOCK_FILE).write_text(json.dumps(document), encoding="utf-8")
        lock.update(forecast)
        assert not marker.exists()
        assert not lock._has_commit(None, "x", "--upload-pack=touch /tmp/x;", fetch=True)
        assert lock._first_commit_of(None, "x", "--output=/tmp/x") == ""

    def test_git_in_a_dependencys_build_does_not_find_a_repository_around_the_cache(self, host, monkeypatch):
        from chartbook import run

        around = host / "a-home-kept-in-git"
        around.mkdir()
        _git(around, "init", "--quiet", "-b", "main")
        monkeypatch.setenv("CHARTBOOK_GIT_CACHE", str(around / "git-cache"))
        marker = host / "toplevel"
        script = (
            f"{sys.executable} -c \"import subprocess; r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], "
            f"capture_output=True, text=True); open(r'{marker}', 'w').write(r.stdout.strip() or 'none')\""
        )
        _upstream(host, 4.0, scripts={"build": script})
        forecast = _forecast(host / "forecast", {"acme/rates": {}}, scripts={"build": f"{sys.executable} -c \"pass\""})
        report = run.run(forecast, echo=lambda *a, **k: None)
        assert report.failed is None, report.reason
        assert marker.read_text(encoding="utf-8") == "none"

    def test_a_read_of_a_dependency_whose_id_changed_says_whose_pin_it_reads(self, host, monkeypatch):
        repository = _upstream(host, 4.0)
        snapshot.make(repository)
        forecast = _forecast(host / "forecast", {"rates": {"id": "acme/rates"}})
        lock.pin(forecast)
        _forecast(forecast, {"rates": {"id": "acme/rates2"}})
        monkeypatch.chdir(forecast)
        with pytest.warns(UserWarning, match="is pinned as acme/rates, and \\[dependencies\\] now names acme/rates2"):
            data.load("rates:treasury")
