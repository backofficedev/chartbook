"""Tests for the ``chartbook install skill`` CLI command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook.__about__ import __version__
from chartbook.cli import VERSION_STAMP_NAME, main

EXPECTED_FILES = {"SKILL.md", "catalog_system.md", "manifest_files.md"}


@pytest.fixture
def claude_config_dir(tmp_path, monkeypatch):
    """Point CLAUDE_CONFIG_DIR at a temporary user-level config directory."""
    config_dir = tmp_path / "claude_config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    return config_dir


def _skill_dir(base: Path) -> Path:
    return base / "skills" / "chartbook"


def test_default_installs_user_level_via_claude_config_dir(claude_config_dir):
    """Default target honors $CLAUDE_CONFIG_DIR."""
    runner = CliRunner()
    result = runner.invoke(main, ["install", "skill"])
    assert result.exit_code == 0

    target = _skill_dir(claude_config_dir)
    assert {p.name for p in target.iterdir() if not p.name.startswith(".")} == (
        EXPECTED_FILES
    )
    assert (target / VERSION_STAMP_NAME).read_text().strip() == __version__


def test_default_falls_back_to_home(tmp_path, monkeypatch):
    """Without CLAUDE_CONFIG_DIR, the target is ~/.claude/skills/chartbook."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(main, ["install", "skill"])
    assert result.exit_code == 0
    assert (_skill_dir(tmp_path / ".claude") / "SKILL.md").exists()


def test_project_flag_installs_into_cwd(tmp_path, monkeypatch, claude_config_dir):
    """--project installs into ./.claude/skills/chartbook, not the user dir."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["install", "skill", "--project"])
    assert result.exit_code == 0
    assert (_skill_dir(tmp_path / ".claude") / "SKILL.md").exists()
    assert not _skill_dir(claude_config_dir).exists()


def test_second_run_is_idempotent(claude_config_dir):
    """Re-running against an up-to-date install is a no-op, no prompt."""
    runner = CliRunner()
    assert runner.invoke(main, ["install", "skill"]).exit_code == 0
    result = runner.invoke(main, ["install", "skill"])
    assert result.exit_code == 0
    assert "already up to date" in result.output
    assert "Installed" not in result.output


def test_stale_old_layout_files_removed(claude_config_dir):
    """Files from older skill layouts (REFERENCE.md) are deleted on install."""
    target = _skill_dir(claude_config_dir)
    target.mkdir(parents=True)
    (target / "REFERENCE.md").write_text("old layout")
    runner = CliRunner()
    result = runner.invoke(main, ["install", "skill", "-f"])
    assert result.exit_code == 0
    assert "removed stale REFERENCE.md" in result.output
    assert not (target / "REFERENCE.md").exists()
    assert (target / "SKILL.md").exists()


def test_force_restores_modified_file(claude_config_dir):
    """-f overwrites a locally modified skill file with the bundled content."""
    runner = CliRunner()
    runner.invoke(main, ["install", "skill"])
    target = _skill_dir(claude_config_dir)
    (target / "SKILL.md").write_text("locally modified")
    result = runner.invoke(main, ["install", "skill", "-f"])
    assert result.exit_code == 0
    assert (target / "SKILL.md").read_text() != "locally modified"


def test_prompt_declined_leaves_files_untouched(claude_config_dir):
    """Declining the overwrite prompt exits cleanly without changes."""
    runner = CliRunner()
    runner.invoke(main, ["install", "skill"])
    target = _skill_dir(claude_config_dir)
    (target / "SKILL.md").write_text("locally modified")
    result = runner.invoke(main, ["install", "skill"], input="n\n")
    assert result.exit_code == 0
    assert (target / "SKILL.md").read_text() == "locally modified"


def test_hidden_files_do_not_break_idempotency(claude_config_dir):
    """A .DS_Store-style hidden file doesn't defeat the up-to-date check."""
    runner = CliRunner()
    runner.invoke(main, ["install", "skill"])
    target = _skill_dir(claude_config_dir)
    (target / ".DS_Store").write_bytes(b"\x00")
    result = runner.invoke(main, ["install", "skill"])
    assert result.exit_code == 0
    assert "already up to date" in result.output
    assert (target / ".DS_Store").exists()
