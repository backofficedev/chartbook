"""Tests for ``chartbook install claude-skill``, and for saying when an installed copy is for another ChartBook.

The skill's ``SKILL.md`` names the ChartBook version it was written for in
its front matter (``chartbook.claude_skill``). The install replaces a copy
for another version and says which; ``chartbook check`` warns of a stale
copy; any other command says so in one line when a person is at a terminal.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import claude_skill, cli
from chartbook.__about__ import __version__
from chartbook.cli import main

EXPECTED_FILES = {"SKILL.md", "catalog_system.md", "manifest_files.md"}


@pytest.fixture
def claude_config_dir(tmp_path, monkeypatch):
    """Point CLAUDE_CONFIG_DIR at a temporary user-level config directory."""
    config_dir = tmp_path / "claude_config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    return config_dir


def _skill_dir(base: Path) -> Path:
    return base / "skills" / "chartbook"


def _old_copy(directory: Path, version: str = "0.1.1", stamp: bool = True, front_matter: bool = False) -> Path:
    """A copy as an older ChartBook installed it: no version in SKILL.md, a stamp beside it."""
    directory.mkdir(parents=True, exist_ok=True)
    head = f'---\nname: chartbook\nmetadata:\n  chartbook-version: "{version}"\n---\n' if front_matter else "---\nname: chartbook\n---\n"
    (directory / "SKILL.md").write_text(head + "# ChartBook Assistant\nchartbook build renders the site\n")
    (directory / "catalog_system.md").write_text("old\n")
    if stamp:
        (directory / claude_skill.OLD_STAMP).write_text(f"{version}\n")
    return directory


class TestInstalling:
    def test_default_installs_user_level_via_claude_config_dir(self, claude_config_dir):
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0, result.output
        target = _skill_dir(claude_config_dir)
        assert {p.name for p in target.iterdir()} == EXPECTED_FILES  # no stamp file any more
        assert claude_skill.version_of(target) == __version__
        assert f"Installed 3 skill file(s) to {target} (ChartBook {__version__})" in result.output

    def test_default_falls_back_to_home(self, tmp_path, monkeypatch):
        """Without CLAUDE_CONFIG_DIR, the target is ~/.claude/skills/chartbook."""
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0
        assert (_skill_dir(tmp_path / ".claude") / "SKILL.md").exists()

    def test_project_flag_installs_into_cwd(self, tmp_path, monkeypatch, claude_config_dir):
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(main, ["install", "claude-skill", "--project"])
        assert result.exit_code == 0
        assert (_skill_dir(tmp_path / ".claude") / "SKILL.md").exists()
        assert not _skill_dir(claude_config_dir).exists()

    def test_second_run_is_idempotent(self, claude_config_dir):
        runner = CliRunner()
        assert runner.invoke(main, ["install", "claude-skill"]).exit_code == 0
        result = runner.invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0
        assert f"already up to date in {_skill_dir(claude_config_dir)} (ChartBook {__version__})" in result.output
        assert "Installed" not in result.output

    def test_stale_old_layout_files_removed(self, claude_config_dir):
        target = _skill_dir(claude_config_dir)
        target.mkdir(parents=True)
        (target / "REFERENCE.md").write_text("old layout")
        result = CliRunner().invoke(main, ["install", "claude-skill", "-f"])
        assert result.exit_code == 0
        assert "removed stale REFERENCE.md" in result.output
        assert not (target / "REFERENCE.md").exists()
        assert (target / "SKILL.md").exists()

    def test_force_restores_modified_file(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "SKILL.md").write_text("locally modified")
        result = runner.invoke(main, ["install", "claude-skill", "-f"])
        assert result.exit_code == 0
        assert (target / "SKILL.md").read_text() != "locally modified"

    def test_prompt_declined_leaves_files_untouched(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "SKILL.md").write_text("locally modified")
        result = runner.invoke(main, ["install", "claude-skill"], input="n\n")
        assert result.exit_code == 0
        assert (target / "SKILL.md").read_text() == "locally modified"

    def test_a_copy_for_this_version_changed_by_hand_is_asked_about(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "catalog_system.md").write_text("my notes\n")  # SKILL.md, and so the version, untouched
        result = runner.invoke(main, ["install", "claude-skill"], input="n\n")
        assert "is this version's, with files changed since it was installed" in result.output
        assert (target / "catalog_system.md").read_text() == "my notes\n"

    def test_hidden_files_do_not_break_idempotency(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / ".DS_Store").write_bytes(b"\x00")
        result = runner.invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0
        assert "already up to date" in result.output
        assert (target / ".DS_Store").exists()

    def test_the_groups_help_says_where_it_installs(self):
        """Found by a new user: the help said "into the current project", while the
        command installs user-level unless --project is given."""
        result = CliRunner().invoke(main, ["install", "--help"])
        assert result.exit_code == 0
        text = " ".join(result.output.split())
        assert "into the current project" not in text
        assert "user-level by default" in text and "--project" in text

    def test_the_old_name_says_the_new_one_and_installs_nothing(self, claude_config_dir):
        result = CliRunner().invoke(main, ["install", "skill", "--project"])
        assert result.exit_code == 2
        assert "`chartbook install skill` is `chartbook install claude-skill` now. Try: chartbook install claude-skill --project" in result.output
        assert not _skill_dir(claude_config_dir).exists()


class TestUpgrading:
    def test_a_copy_an_older_chartbook_installed_is_replaced_without_asking_and_said(self, claude_config_dir):
        target = _old_copy(_skill_dir(claude_config_dir))
        result = CliRunner().invoke(main, ["install", "claude-skill"])  # no input: no question
        assert result.exit_code == 0, result.output
        assert f"Updated the skill in {target} from ChartBook 0.1.1 to {__version__}" in result.output
        assert not (target / claude_skill.OLD_STAMP).exists()
        assert claude_skill.version_of(target) == __version__
        assert {p.name for p in target.iterdir()} == EXPECTED_FILES

    def test_a_copy_whose_front_matter_names_another_version_is_replaced_too(self, claude_config_dir):
        target = _old_copy(_skill_dir(claude_config_dir), "0.1.9", stamp=False, front_matter=True)
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert f"from ChartBook 0.1.9 to {__version__}" in result.output

    def test_a_copy_naming_no_version_is_asked_about(self, claude_config_dir):
        """It may be someone's own skill under that name."""
        target = _old_copy(_skill_dir(claude_config_dir), stamp=False)
        result = CliRunner().invoke(main, ["install", "claude-skill"], input="n\n")
        assert "naming no ChartBook version" in result.output
        assert "chartbook build renders the site" in (target / "SKILL.md").read_text()

    def test_up_to_date_files_beside_an_old_stamp_lose_the_stamp(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / claude_skill.OLD_STAMP).write_text("0.1.1\n")
        result = runner.invoke(main, ["install", "claude-skill"])
        assert "already up to date" in result.output
        assert not (target / claude_skill.OLD_STAMP).exists()


class TestTheVersion:
    def test_the_bundled_skill_names_this_chartbook(self):
        """A release bumps it with the package (docs_src/contributing.md)."""
        assert claude_skill.version_of(claude_skill.bundled_dir()) == __version__

    @pytest.mark.parametrize(
        "head, version",
        [
            ('---\nname: chartbook\nmetadata:\n  chartbook-version: "1.2.3"\n---\n', "1.2.3"),
            ("---\nname: chartbook\nmetadata:\n  chartbook-version: '1.2.3'\n---\n", "1.2.3"),
            ("---\nname: chartbook\nmetadata:\n  chartbook-version: 1.2.3  # pinned\n---\n", "1.2.3"),
            ("---\nname: chartbook\n---\nchartbook-version: 9.9.9\n", None),  # in the body, not the front matter
            ("# no front matter\n", None),
        ],
    )
    def test_the_version_is_read_from_the_front_matter(self, tmp_path, head, version):
        (tmp_path / "SKILL.md").write_text(head + "body\n")
        assert claude_skill.version_of(tmp_path) == version

    def test_an_old_stamp_is_read_where_the_front_matter_names_none(self, tmp_path):
        assert claude_skill.version_of(_old_copy(tmp_path)) == "0.1.1"

    def test_a_folder_with_no_skill_names_no_version(self, tmp_path):
        assert claude_skill.version_of(tmp_path / "nothing") is None


class TestFindingAStaleCopy:
    def test_the_projects_copy_is_found_above_the_working_folder(self, tmp_path, claude_config_dir):
        repo = tmp_path / "repo"
        copy = _old_copy(repo / ".claude" / "skills" / "chartbook")
        (repo / "pipelines" / "rates").mkdir(parents=True)
        assert claude_skill.project_dir(repo / "pipelines" / "rates") == copy
        (found,) = claude_skill.stale(repo / "pipelines" / "rates")
        assert (found.where, found.directory, found.version) == ("project", copy, "0.1.1")

    def test_the_users_copy_is_not_taken_for_a_projects(self, tmp_path, monkeypatch):
        """A walk up from the home folder meets ~/.claude, which is the user's copy."""
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        _old_copy(tmp_path / ".claude" / "skills" / "chartbook")
        (tmp_path / "work").mkdir()
        assert claude_skill.project_dir(tmp_path / "work") is None
        assert [c.where for c in claude_skill.stale(tmp_path / "work")] == ["user"]

    def test_a_copy_for_this_version_is_not_stale(self, tmp_path, claude_config_dir, monkeypatch):
        monkeypatch.chdir(tmp_path)
        CliRunner().invoke(main, ["install", "claude-skill"])
        CliRunner().invoke(main, ["install", "claude-skill", "--project"])
        assert claude_skill.stale(tmp_path) == []

    def test_what_the_notice_says(self, tmp_path, claude_config_dir):
        user = claude_skill.Copy("user", _skill_dir(claude_config_dir), "0.1.1")
        assert claude_skill.notice(user) == (
            f"your Claude Code skill, {_skill_dir(claude_config_dir)}, is for ChartBook 0.1.1, and this is ChartBook "
            f"{__version__}: `chartbook install claude-skill` installs this version's."
        )
        project = claude_skill.Copy("project", tmp_path / "repo" / ".claude" / "skills" / "chartbook", None)
        said = claude_skill.notice(project)
        assert "names no ChartBook version (it is from before 0.2.0)" in said
        assert f"`chartbook install claude-skill --project` in {tmp_path / 'repo'} installs this version's." in said


class TestSayingIt:
    @pytest.fixture
    def stale_user_copy(self, claude_config_dir):
        return _old_copy(_skill_dir(claude_config_dir))

    def test_a_command_at_a_terminal_says_it_in_one_line(self, stale_user_copy, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["docs", "--help"])
        assert result.exit_code == 0
        notes = [line for line in result.output.splitlines() if line.startswith("Note: your Claude Code skill")]
        assert len(notes) == 1 and "is for ChartBook 0.1.1" in notes[0]

    def test_a_script_never_sees_it(self, stale_user_copy):
        """CliRunner's stderr, like a pipe's or CI's, is not a terminal."""
        result = CliRunner().invoke(main, ["docs", "--help"])
        assert "Claude Code skill" not in result.output

    def test_install_does_not_say_it(self, stale_user_copy, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert "Note:" not in result.output and "Updated the skill" in result.output

    def test_check_warns_whether_or_not_a_terminal(self, stale_user_copy, pipeline_project, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["check", "--project-dir", str(pipeline_project)])
        lines = [line for line in result.output.splitlines() if "Claude Code skill" in line]
        assert len(lines) == 1 and lines[0].startswith("warning: your Claude Code skill")
        assert result.exit_code == 0, result.output  # it fails nothing

    def test_a_note_never_stops_a_command(self, stale_user_copy, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)

        def broken(start=None):
            raise RuntimeError("unreadable")

        monkeypatch.setattr(claude_skill, "stale", broken)
        result = CliRunner().invoke(main, ["docs", "--help"])
        assert result.exit_code == 0 and "Usage:" in result.output
