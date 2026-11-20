"""``chartbook install agents``: the Claude Code skill for the user, and a ChartBook section in the project's ``AGENTS.md`` (``docs_src/design/one-command.md``).

Other coding agents read ``AGENTS.md``. The command writes a section into
it between two marker lines, replaces what is between them when ChartBook
moves on, and leaves the rest of the file alone. Outside a project it
installs the skill and says the other half is for a project.
"""

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from chartbook import agents, claude_skill, cli
from chartbook.__about__ import __version__
from chartbook.cli import main

OWN = "# Notes for agents\n\nRun the tests with `pytest`.\n"


@pytest.fixture(autouse=True)
def claude_config_dir(tmp_path, monkeypatch):
    """The user's Claude Code folder, in a scratch place."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude_config"))
    return tmp_path / "claude_config"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A pipeline's folder, which commands are run in."""
    folder = (tmp_path / "project").resolve()
    folder.mkdir()
    (folder / "chartbook.toml").write_text('[project]\nid = "acme/report"\n', encoding="utf-8", newline="\n")
    monkeypatch.chdir(folder)
    return folder


def _install(*words: str, input: str = None):
    return CliRunner().invoke(main, ["install", "agents", *words], input=input)


def _older(version: str = "0.5.1") -> str:
    """The section as an older ChartBook wrote it: other text, and its own version in the marker."""
    return agents.section(version).replace("`chartbook pin --update`", "`chartbook update`")


class TestInAProject:
    def test_it_installs_the_skill_and_writes_the_section(self, project, claude_config_dir):
        result = _install()
        assert result.exit_code == 0, result.output
        assert (claude_config_dir / "skills" / "chartbook" / "SKILL.md").is_file()
        assert f"(ChartBook {__version__})" in result.output.splitlines()[-2]  # the skill's own last line
        assert result.output.splitlines()[-1] == (
            f"Wrote AGENTS.md: a ChartBook section, for the agents that read that file (ChartBook {__version__})."
        )
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()

    def test_again_it_writes_nothing(self, project):
        _install()
        before = (project / "AGENTS.md").stat().st_mtime_ns
        result = _install()
        assert result.exit_code == 0
        assert result.output.splitlines()[-1] == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."
        assert (project / "AGENTS.md").stat().st_mtime_ns == before

    def test_a_file_the_project_has_is_added_to_and_kept(self, project):
        (project / "AGENTS.md").write_text(OWN, encoding="utf-8", newline="\n")
        result = _install()
        assert result.output.splitlines()[-1] == (
            f"Added a ChartBook section to AGENTS.md (ChartBook {__version__}). The rest of the file is as it was."
        )
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section()

    def test_a_section_of_an_older_chartbook_is_replaced_and_the_rest_left_alone(self, project):
        below = "\n## Deploying\n\nAsk first.\n"
        (project / "AGENTS.md").write_text(OWN + "\n" + _older() + below, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == (
            f"Updated the ChartBook section of AGENTS.md from ChartBook 0.5.1 to {__version__}. The rest of the file is as it was."
        )
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section() + below

    def test_a_file_that_ends_its_lines_another_way_keeps_its_way(self, project):
        (project / "AGENTS.md").write_bytes(OWN.replace("\n", "\r\n").encode("utf-8"))
        assert _install().exit_code == 0
        written = (project / "AGENTS.md").read_bytes().decode("utf-8")
        assert written == (OWN + "\n" + agents.section()).replace("\n", "\r\n")
        # And is this version's all the same
        assert _install().output.splitlines()[-1] == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."

    def test_from_a_folder_below_it_is_the_projects_file_that_is_written(self, project, monkeypatch):
        (project / "src").mkdir()
        monkeypatch.chdir(project / "src")
        result = _install()
        assert result.exit_code == 0 and (project / "AGENTS.md").is_file() and not (project / "src" / "AGENTS.md").exists()
        assert f"Wrote {project / 'AGENTS.md'}: " in result.output  # named whole, from a folder it is not in

    def test_the_section_is_written_though_the_skill_was_declined(self, project, claude_config_dir):
        _install()
        (project / "AGENTS.md").unlink()
        skill = claude_config_dir / "skills" / "chartbook" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8", newline="\n")
        result = _install(input="n\n")
        assert result.exit_code == 0, result.output
        assert skill.read_text(encoding="utf-8").endswith("\nmine\n") and (project / "AGENTS.md").is_file()


class TestASectionChangedByHand:
    """This version's marker, and other text between the lines: somebody wrote there."""

    @pytest.fixture
    def changed(self, project):
        text = agents.section().replace("## ChartBook\n", "## ChartBook\n\nWe use doit here.\n")
        (project / "AGENTS.md").write_text(OWN + "\n" + text, encoding="utf-8", newline="\n")
        return project / "AGENTS.md"

    def test_where_nothing_can_ask_it_is_left_and_said(self, changed):
        before = changed.read_bytes()
        result = _install()
        assert result.exit_code == 1 and changed.read_bytes() == before
        assert result.output.splitlines()[-1] == (
            f"Error: The ChartBook section of AGENTS.md was changed since ChartBook {__version__} wrote it. Notes of your own "
            "go outside its two marker lines; --force replaces what is between them."
        )

    def test_force_replaces_it(self, changed):
        result = _install("--force")
        assert result.exit_code == 0, result.output
        assert changed.read_text(encoding="utf-8") == OWN + "\n" + agents.section()
        assert result.output.splitlines()[-1] == (
            f"Wrote the ChartBook section of AGENTS.md again (ChartBook {__version__}). The rest of the file is as it was."
        )

    def test_at_a_terminal_it_asks_and_no_leaves_it(self, changed, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", lambda: True)
        before = changed.read_bytes()
        result = _install(input="\n")  # Enter is no
        assert result.exit_code == 0 and changed.read_bytes() == before
        assert "Replace what is between them? [y/N]: " in result.output
        result = _install(input="y\n")
        assert result.exit_code == 0 and changed.read_text(encoding="utf-8") == OWN + "\n" + agents.section()


class TestMarkerLinesThatDoNotHoldOneSection:
    @pytest.mark.parametrize("text, why", [
        (OWN + agents.section().rsplit(agents.END, 1)[0], "its `chartbook:start` line (line 4) has no `chartbook:end` line after it"),
        (OWN + agents.END + " -->\n", "its `chartbook:end` line (line 4) has no `chartbook:start` line before it"),
        (agents.section() + agents.section(), "it has 2 `chartbook:start` line(s) and 2 `chartbook:end` line(s), and one section has one of each, in that order"),
        (agents.END + " -->\n" + agents.START + " -->\n", "it has 1 `chartbook:start` line(s) and 1 `chartbook:end` line(s), and one section has one of each, in that order"),
    ])
    def test_nothing_is_written_and_it_says_which(self, project, text, why):
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install("--force")
        assert result.exit_code == 1
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == text
        assert result.output.splitlines()[-1] == (
            f"Error: AGENTS.md: {why}. Put the missing line back, or take out the one that is left, and run this again. "
            "Nothing was written to it."
        )

    def test_a_file_that_is_no_text(self, project):
        (project / "AGENTS.md").write_bytes(b"\xff\xfe\x00not utf-8")
        result = _install()
        assert result.exit_code == 1 and result.output.splitlines()[-1].startswith("Error: AGENTS.md cannot be read as text: ")
        assert (project / "AGENTS.md").read_bytes() == b"\xff\xfe\x00not utf-8"


class TestOutsideAProject:
    def test_it_installs_the_skill_and_says_what_the_other_half_is_for(self, tmp_path, monkeypatch, claude_config_dir):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        result = _install()
        assert result.exit_code == 0, result.output
        assert (claude_config_dir / "skills" / "chartbook" / "SKILL.md").is_file()
        assert result.output.splitlines()[-1] == (
            "No chartbook.toml here or above: the AGENTS.md half is for a project. Run `chartbook install agents` "
            "in a pipeline's folder to write it."
        )
        assert not (elsewhere / "AGENTS.md").exists()

    def test_a_project_is_not_looked_for_above_its_repository(self, tmp_path, monkeypatch):
        (tmp_path / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        inner = tmp_path / "another-repository"
        (inner / ".git").mkdir(parents=True)
        monkeypatch.chdir(inner)
        assert agents.project_folder() is None and agents.project_folder(tmp_path) == tmp_path.resolve()

    def test_nor_is_the_home_folder_ever_one(self, tmp_path, monkeypatch):
        (tmp_path / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / "work").mkdir()
        assert agents.project_folder(tmp_path / "work") is None


class TestASectionOfAnOlderChartBook:
    """It teaches an agent that version's commands: said as a stale skill is."""

    def test_it_is_found_and_said(self, project):
        (project / "AGENTS.md").write_text(_older(), encoding="utf-8", newline="\n")
        assert agents.stale(project) == (project / "AGENTS.md", "0.5.1")
        said = agents.notice(project / "AGENTS.md", "0.5.1")
        assert "is for ChartBook 0.5.1" in said and "`chartbook install agents` in " in said
        result = CliRunner().invoke(main, ["run", "--check"])
        assert f"warning: {said}" in result.output.splitlines()

    @pytest.mark.parametrize("text", [
        "", OWN, agents.section(), agents.section("99.0.0"), agents.section().replace(f" version={__version__};", ""),
        agents.START + " version=0.5.1 -->\n",  # no section: its marker lines do not hold one
    ])
    def test_not_this_versions_a_newer_ones_or_none(self, project, text):
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        assert agents.stale(project) is None

    def test_a_person_at_a_terminal_is_told_in_one_line(self, project, monkeypatch):
        (project / "AGENTS.md").write_text(_older(), encoding="utf-8", newline="\n")
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["ls", "--help"])
        assert f"Note: {agents.notice(project / 'AGENTS.md', '0.5.1')}" in result.output.splitlines()


class TestWhatTheSectionSays:
    def test_every_command_it_names_is_one(self):
        """As the skill and the llms files are held to: an agent is not taught a command that is gone."""
        named = re.findall(r"`chartbook ((?:[a-z-]+ ?)+)", agents.body())
        assert len(named) >= 8
        for words in named:
            group = main
            for word in words.split():
                if word.startswith("-") or not isinstance(group, click.Group):
                    break
                assert word in group.commands, f"`chartbook {words}` is in agents_section.md, and `{word}` is no command"
                group = group.commands[word]

    def test_its_markers_name_the_version_and_what_writes_it(self):
        first, *_, last = agents.section().splitlines()
        assert first.startswith(f"<!-- chartbook:start version={__version__}; written by `chartbook install agents`") and first.endswith("-->")
        assert last == "<!-- chartbook:end -->"
        found = agents.read(OWN + agents.section() + "tail\n")
        assert (found.before, found.after, found.version) == (OWN, "tail\n", __version__) and agents.same(found)

    def test_the_skill_stays_the_first_half_alone(self, project, claude_config_dir):
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0 and not (project / "AGENTS.md").exists()
        assert claude_skill.version_of(claude_config_dir / "skills" / "chartbook") == __version__
