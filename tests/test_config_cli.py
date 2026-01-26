"""Tests for the ``chartbook config`` CLI command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import config
from chartbook.cli import main


@pytest.fixture
def fake_config_dir(tmp_path, monkeypatch):
    """Redirect the global config directory to a temporary path."""
    fake_dir = tmp_path / ".chartbook_cli_tests"
    monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
    monkeypatch.setattr(
        config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
    )
    return fake_dir


def test_config_prompts_and_writes(fake_config_dir, catalog_project):
    """config command prompts for path and writes settings.toml."""
    runner = CliRunner()
    result = runner.invoke(main, ["config"], input=str(catalog_project) + "\n")
    assert result.exit_code == 0
    assert "Catalog path set to:" in result.output
    assert config.get_default_catalog_path() is not None


def test_config_shows_current_if_set(fake_config_dir, catalog_project):
    """config command shows current path when one is already configured."""
    config.set_default_catalog_path(catalog_project)
    runner = CliRunner()
    result = runner.invoke(main, ["config"], input=str(catalog_project) + "\n")
    assert result.exit_code == 0
    assert "Current catalog path:" in result.output


def test_config_rejects_nonexistent_path(fake_config_dir, tmp_path):
    """config command exits with error for a path that does not exist."""
    runner = CliRunner()
    bad_path = str(tmp_path / "does_not_exist")
    result = runner.invoke(main, ["config"], input=bad_path + "\n")
    assert result.exit_code != 0
    assert "Error:" in result.output


def test_config_rejects_pipeline_toml(fake_config_dir, pipeline_project):
    """config command exits with error for pipeline-type chartbook.toml."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["config"], input=str(pipeline_project) + "\n"
    )
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "catalog" in result.output.lower()
