"""Tests for chartbook.config — global settings management."""

from pathlib import Path

import pytest
import tomli_w

from chartbook import config


@pytest.fixture
def fake_config_dir(tmp_path, monkeypatch):
    """Redirect the global config directory to a temporary path."""
    fake_dir = tmp_path / ".chartbook"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
    monkeypatch.setattr(
        config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
    )
    return fake_dir


def test_read_returns_empty_when_no_file(fake_config_dir):
    """read_global_settings returns {} when settings.toml does not exist."""
    assert config.read_global_settings() == {}


def test_write_read_roundtrip(fake_config_dir):
    """Writing settings and reading them back produces the same dict."""
    settings = {"catalog": {"path": "/some/path/chartbook.toml"}}
    config.write_global_settings(settings)
    assert config.read_global_settings() == settings


def test_get_default_catalog_path_when_configured(fake_config_dir):
    """get_default_catalog_path returns a Path when catalog.path is set."""
    settings = {"catalog": {"path": "/my/catalog/chartbook.toml"}}
    config.write_global_settings(settings)
    result = config.get_default_catalog_path()
    assert result == Path("/my/catalog/chartbook.toml")


def test_get_default_catalog_path_when_not_configured(fake_config_dir):
    """get_default_catalog_path returns None when no catalog is configured."""
    config.write_global_settings({})
    assert config.get_default_catalog_path() is None


def test_get_default_catalog_path_when_no_file(fake_config_dir):
    """get_default_catalog_path returns None when settings file is missing."""
    assert config.get_default_catalog_path() is None


def test_set_default_catalog_path_creates_dir(fake_config_dir, catalog_project):
    """set_default_catalog_path creates the config directory if needed."""
    assert not fake_config_dir.exists()
    config.set_default_catalog_path(catalog_project / "chartbook.toml")
    assert fake_config_dir.exists()
    assert config.get_default_catalog_path() is not None


def test_set_default_catalog_path_validates_exists(fake_config_dir, tmp_path):
    """set_default_catalog_path raises FileNotFoundError for missing files."""
    with pytest.raises(FileNotFoundError):
        config.set_default_catalog_path(tmp_path / "nonexistent" / "chartbook.toml")


def test_set_default_catalog_path_rejects_pipeline(
    fake_config_dir, pipeline_project
):
    """set_default_catalog_path raises ValueError for pipeline-type manifests."""
    with pytest.raises(ValueError, match="catalog"):
        config.set_default_catalog_path(pipeline_project / "chartbook.toml")


def test_set_default_catalog_path_accepts_directory(
    fake_config_dir, catalog_project
):
    """set_default_catalog_path accepts a directory and appends chartbook.toml."""
    config.set_default_catalog_path(catalog_project)
    result = config.get_default_catalog_path()
    assert result == (catalog_project / "chartbook.toml").resolve()
