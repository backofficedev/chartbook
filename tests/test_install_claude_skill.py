"""Tests for ``chartbook install claude-skill``, and for saying when an installed copy is for another ChartBook.

The skill's ``SKILL.md`` names the ChartBook version it was written for in
its front matter (``chartbook.claude_skill``). The install replaces a copy
for another version and says which; ``chartbook check`` warns of a stale
copy; any other command says so in one line when a person is at a terminal.
"""

import os
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
    (directory / "SKILL.md").write_text(head + "# ChartBook Assistant\nchartbook build renders the site\n", encoding="utf-8")
    (directory / "catalog_system.md").write_text("old\n", encoding="utf-8")
    if stamp:
        (directory / claude_skill.OLD_STAMP).write_text(f"{version}\n", encoding="utf-8")
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
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows reads home from here
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
        (target / "REFERENCE.md").write_text("old layout", encoding="utf-8")
        result = CliRunner().invoke(main, ["install", "claude-skill", "-f"])
        assert result.exit_code == 0
        assert "removed stale REFERENCE.md" in result.output
        assert not (target / "REFERENCE.md").exists()
        assert (target / "SKILL.md").exists()

    def test_force_restores_modified_file(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "SKILL.md").write_text("locally modified", encoding="utf-8")
        result = runner.invoke(main, ["install", "claude-skill", "-f"])
        assert result.exit_code == 0
        assert (target / "SKILL.md").read_text(encoding="utf-8") != "locally modified"

    def test_prompt_declined_leaves_files_untouched(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "SKILL.md").write_text("locally modified", encoding="utf-8")
        result = runner.invoke(main, ["install", "claude-skill"], input="n\n")
        assert result.exit_code == 0
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "locally modified"

    def test_a_copy_for_this_version_changed_by_hand_is_asked_about(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / "catalog_system.md").write_text("my notes\n", encoding="utf-8")  # SKILL.md, and so the version, untouched
        result = runner.invoke(main, ["install", "claude-skill"], input="n\n")
        assert "is this version's, with files changed since it was installed" in result.output
        assert (target / "catalog_system.md").read_text(encoding="utf-8") == "my notes\n"

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
        assert "chartbook build renders the site" in (target / "SKILL.md").read_text(encoding="utf-8")

    def test_a_copy_for_a_newer_chartbook_is_not_stale_and_is_asked_about(self, tmp_path, claude_config_dir):
        """Found by a reviewer: each pipeline has its own environment, and two on two versions would
        take turns replacing the one user-level copy, each told the other's was stale."""
        target = _old_copy(_skill_dir(claude_config_dir), "99.0.0", stamp=False, front_matter=True)
        (target / "my_notes.md").write_text("mine\n", encoding="utf-8")
        assert claude_skill.stale(tmp_path) == []
        result = CliRunner().invoke(main, ["install", "claude-skill"], input="n\n")
        assert f"is for ChartBook 99.0.0, newer than this one, {__version__}" in result.output
        assert (target / "my_notes.md").exists() and claude_skill.front_matter_version(target) == "99.0.0"

    def test_up_to_date_files_beside_an_old_stamp_lose_the_stamp(self, claude_config_dir):
        runner = CliRunner()
        runner.invoke(main, ["install", "claude-skill"])
        target = _skill_dir(claude_config_dir)
        (target / claude_skill.OLD_STAMP).write_text("0.1.1\n", encoding="utf-8")
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
            ('\ufeff---\nname: chartbook\nmetadata:\n  chartbook-version: "1.2.3"\n---\n', "1.2.3"),  # a byte-order mark
            ('---\r\nname: chartbook\r\nmetadata:\r\n  chartbook-version: "1.2.3"\r\n---\r\n', "1.2.3"),  # Windows line endings
            ("---\nname: chartbook\nmetadata:\n  chartbook-version:\n  other: x\n---\n", None),  # an empty value takes nothing below it
            ('---\nchartbook-version: "9.9.9"\nname: chartbook\n---\n', None),  # only under metadata
        ],
    )
    def test_the_version_is_read_from_the_front_matter(self, tmp_path, head, version):
        (tmp_path / "SKILL.md").write_text(head + "body\n", encoding="utf-8")
        assert claude_skill.version_of(tmp_path) == version

    def test_an_old_stamp_is_read_where_the_front_matter_names_none(self, tmp_path):
        assert claude_skill.version_of(_old_copy(tmp_path)) == "0.1.1"

    def test_a_stamp_naming_this_version_is_an_earlier_build_and_stale(self, tmp_path, claude_config_dir):
        """Found by a reviewer: main has said 0.2.0 since 2026-10-12, so the old install stamped copies of
        an older skill "0.2.0". The bundled skill names its version in its front matter; a copy that names
        it only in a stamp is never the current one."""
        target = _old_copy(_skill_dir(claude_config_dir), __version__)
        (found,) = claude_skill.stale(tmp_path)
        assert found.version == f"{__version__} (an earlier build)"
        result = CliRunner().invoke(main, ["install", "claude-skill"])  # an upgrade: no question
        assert f"from ChartBook {__version__} (an earlier build) to {__version__}" in result.output
        assert claude_skill.front_matter_version(target) == __version__

    @pytest.mark.parametrize("named, standing", [("0.1.1", "older"), ("99.0.0", "newer"), ("not-a-version", "older")])
    def test_how_a_copy_stands_to_this_chartbook(self, tmp_path, named, standing):
        _old_copy(tmp_path, named, stamp=False, front_matter=True)
        assert claude_skill.relation(tmp_path) == standing

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
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows reads home from here
        _old_copy(tmp_path / ".claude" / "skills" / "chartbook")
        (tmp_path / "work").mkdir()
        assert claude_skill.project_dir(tmp_path / "work") is None
        assert [c.where for c in claude_skill.stale(tmp_path / "work")] == ["user"]

    def test_a_copy_for_this_version_is_not_stale(self, tmp_path, claude_config_dir, monkeypatch):
        monkeypatch.chdir(tmp_path)
        CliRunner().invoke(main, ["install", "claude-skill"])
        CliRunner().invoke(main, ["install", "claude-skill", "--project"])
        assert claude_skill.stale(tmp_path) == []

    def test_the_walk_up_stops_at_the_repositorys_top(self, tmp_path, claude_config_dir):
        _old_copy(tmp_path / ".claude" / "skills" / "chartbook")  # above the repository: not this project's
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "sub").mkdir()
        assert claude_skill.project_dir(repo / "sub") is None

    def test_the_walk_up_never_takes_the_home_folders_claude(self, tmp_path, monkeypatch):
        """Found by a reviewer: with CLAUDE_CONFIG_DIR elsewhere, ~/.claude was "this project's", with
        `--project` to be run in `~/.`."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows reads home from here
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "elsewhere"))
        _old_copy(tmp_path / ".claude" / "skills" / "chartbook")
        (tmp_path / "work" / "deep").mkdir(parents=True)
        assert claude_skill.project_dir(tmp_path / "work" / "deep") is None
        assert claude_skill.shown(tmp_path) == "~"

    @pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="POSIX permissions, not as root")
    def test_a_folder_that_cannot_be_read_is_passed_by(self, tmp_path, pipeline_project, monkeypatch):
        """Found by a reviewer: `chartbook check` below a `.claude` this user may not open was a traceback."""
        locked = tmp_path / "locked"
        (locked / ".claude").mkdir(parents=True)
        os.chmod(locked / ".claude", 0)
        try:
            (locked / "pipe").mkdir()
            assert claude_skill.project_dir(locked / "pipe") is None
            monkeypatch.setattr(claude_skill, "project_dir", lambda start=None: (_ for _ in ()).throw(PermissionError("denied")))
            result = CliRunner().invoke(main, ["check", "--project-dir", str(pipeline_project)])
            assert result.exception is None or isinstance(result.exception, SystemExit), result.output
        finally:
            os.chmod(locked / ".claude", 0o755)

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

    @pytest.mark.parametrize("present", ["nothing", "an empty folder", "a stray old stamp"])
    def test_no_skill_installed_says_nothing_anywhere(self, claude_config_dir, pipeline_project, monkeypatch, present):
        """Asked by the maintainer: a user who never installed the skill hears nothing of it."""
        target = _skill_dir(claude_config_dir)
        if present != "nothing":
            target.mkdir(parents=True)
        if present == "a stray old stamp":
            (target / claude_skill.OLD_STAMP).write_text("0.1.1\n", encoding="utf-8")
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        monkeypatch.chdir(pipeline_project)
        assert claude_skill.stale(pipeline_project) == []
        for words in (["docs", "--help"], ["check"]):
            result = CliRunner().invoke(main, words)
            assert "Claude Code skill" not in result.output, words
        assert CliRunner().invoke(main, ["check"]).exit_code == 0

    def test_a_script_never_sees_it(self, stale_user_copy):
        """CliRunner's stderr, like a pipe's or CI's, is not a terminal."""
        result = CliRunner().invoke(main, ["docs", "--help"])
        assert "Claude Code skill" not in result.output

    def test_install_does_not_say_it(self, stale_user_copy, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert "Note:" not in result.output and "Updated the skill" in result.output

    @pytest.mark.parametrize("terminal", [True, False])
    def test_check_warns_whether_or_not_a_terminal(self, stale_user_copy, pipeline_project, monkeypatch, terminal):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: terminal)
        result = CliRunner().invoke(main, ["check", "--project-dir", str(pipeline_project)])
        lines = [line for line in result.output.splitlines() if "Claude Code skill" in line]
        assert len(lines) == 1 and lines[0].startswith("warning: your Claude Code skill")
        assert result.exit_code == 0, result.output  # it fails nothing

    def test_check_warns_before_a_manifest_that_stops_it(self, stale_user_copy, tmp_path):
        (tmp_path / "chartbook.toml").write_text("this = [not toml\n", encoding="utf-8")
        result = CliRunner().invoke(main, ["check", "--project-dir", str(tmp_path)])
        assert result.exit_code != 0 and "warning: your Claude Code skill" in result.output

    @pytest.mark.parametrize("words", [["--version"], ["--help"], []])
    def test_the_program_alone_says_nothing_of_it(self, stale_user_copy, monkeypatch, words):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        assert "Claude Code skill" not in CliRunner().invoke(main, words).output

    def test_a_command_inside_a_script_chartbook_runs_says_nothing_of_it(self, stale_user_copy, monkeypatch, tmp_path):
        """The run that started the script said it already."""
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        monkeypatch.setenv("CHARTBOOK_RUN_DIR", str(tmp_path))
        assert "Claude Code skill" not in CliRunner().invoke(main, ["docs", "--help"]).output

    def test_a_note_never_stops_a_command(self, stale_user_copy, monkeypatch):
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)

        def broken(start=None):
            raise RuntimeError("unreadable")

        monkeypatch.setattr(claude_skill, "stale", broken)
        result = CliRunner().invoke(main, ["docs", "--help"])
        assert result.exit_code == 0 and "Usage:" in result.output
