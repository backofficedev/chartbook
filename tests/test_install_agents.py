"""``chartbook install agents``: the Claude Code skill for the user, and a ChartBook section in the project's ``AGENTS.md`` (``docs_src/design/one-command.md``).

Other coding agents read ``AGENTS.md``. The command writes a section into
it between two marker lines, replaces what is between them when ChartBook
moves on, and leaves the rest of the file alone, byte for byte. Nothing a
person wrote is replaced unasked: the opening marker carries a hash of
the section's text, so one that somebody has written in is told from one
that is as ChartBook left it. Outside a project it installs the skill and
says the other half is for a project.
"""

import os
import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from chartbook import agents, claude_skill, cli
from chartbook import data as chartbook_data
from chartbook.__about__ import __version__
from chartbook.cli import main

OWN = "# Notes for agents\n\nRun the tests with `pytest`.\n"
BY_HAND = "\nWe use doit here.\n"


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


def _of(version: str) -> str:
    """The section as another ChartBook wrote it: text of its own, and its own version and hash in the marker."""
    return agents.section(version, agents.body().replace("`chartbook pin --update`", "`chartbook update`"))


def _written_in(section: str) -> str:
    """A section somebody has written a line of their own in, under its heading."""
    return section.replace("## ChartBook\n", "## ChartBook\n" + BY_HAND, 1)


def _last(result) -> str:
    return result.output.splitlines()[-1]


class TestInAProject:
    def test_it_installs_the_skill_and_writes_the_section(self, project, claude_config_dir):
        result = _install()
        assert result.exit_code == 0, result.output
        assert (claude_config_dir / "skills" / "chartbook" / "SKILL.md").is_file()
        assert f"(ChartBook {__version__})" in result.output.splitlines()[-2]  # the skill's own last line
        assert _last(result) == f"Wrote AGENTS.md: a ChartBook section, for the agents that read that file (ChartBook {__version__})."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()

    def test_again_it_writes_nothing(self, project):
        _install()
        before = (project / "AGENTS.md").stat().st_mtime_ns
        result = _install()
        assert result.exit_code == 0
        assert _last(result) == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."
        assert (project / "AGENTS.md").stat().st_mtime_ns == before

    @pytest.mark.parametrize("own", [OWN, OWN.rstrip("\n"), OWN + "\n\n\n", "\ufeff" + OWN, OWN.replace("\n", "\r\n")],
                             ids=["as it is", "no last newline", "blank lines at its end", "a byte-order mark", "CRLF"])
    def test_a_file_the_project_has_is_added_to_and_kept_byte_for_byte(self, project, own):
        """Found by review: blank lines at its end were cut, and a file with a byte-order mark could not be given a section twice."""
        (project / "AGENTS.md").write_bytes(own.encode("utf-8"))
        result = _install()
        assert _last(result) == f"Added a ChartBook section to AGENTS.md (ChartBook {__version__}). The rest of the file is as it was."
        after = (project / "AGENTS.md").read_bytes().decode("utf-8")
        assert after.startswith(own) and agents.read(after).own.replace("\r\n", "\n") == agents.section()
        between = after[len(own):after.index(agents.START)]
        assert between.strip("\r\n") == "" and (own + between).replace("\r\n", "\n").endswith("\n\n")
        # The section's lines end as the file's do
        assert ("\n" in after.replace("\r\n", "")) == ("\r\n" not in own)
        # And a second run finds it, and writes nothing
        assert _last(_install()) == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."
        assert (project / "AGENTS.md").read_bytes().decode("utf-8") == after

    def test_a_section_of_an_older_chartbook_is_replaced_and_the_rest_left_alone(self, project):
        below = "\n## Deploying\n\nAsk first.\n"
        (project / "AGENTS.md").write_text(OWN + "\n" + _of("0.5.1") + below, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0, result.output
        assert _last(result) == f"Updated the ChartBook section of AGENTS.md from ChartBook 0.5.1 to {__version__}. The rest of the file is as it was."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section() + below

    def test_a_file_keeps_the_way_most_of_its_lines_end(self, project):
        """Found by review: one CRLF in a file of LF lines turned the whole section to CRLF."""
        own = OWN + "a line from another editor\r\n"
        (project / "AGENTS.md").write_bytes(own.encode("utf-8"))
        assert _install().exit_code == 0
        after = (project / "AGENTS.md").read_bytes().decode("utf-8")
        assert after.count("\r\n") == 1 and after.startswith(own)

    def test_from_a_folder_below_it_is_the_projects_file_that_is_written(self, project, monkeypatch):
        (project / ".git").mkdir()  # a repository, which the walk up stays in
        (project / "src").mkdir()
        monkeypatch.chdir(project / "src")
        result = _install()
        assert result.exit_code == 0 and (project / "AGENTS.md").is_file() and not (project / "src" / "AGENTS.md").exists()
        assert f"Wrote {project / 'AGENTS.md'}: " in result.output  # named whole, from a folder it is not in

    @pytest.mark.skipif(os.name == "nt", reason="a file has no such mode there")
    def test_a_file_keeps_its_mode(self, project):
        (project / "AGENTS.md").write_text(_of("0.5.1"), encoding="utf-8", newline="\n")
        (project / "AGENTS.md").chmod(0o755)
        assert _install().exit_code == 0
        assert (project / "AGENTS.md").stat().st_mode & 0o777 == 0o755

    def test_a_write_that_fails_leaves_the_file_as_it_was(self, project, monkeypatch):
        """Found by review: the file was opened for writing in place, and a disk that filled left a project's notes cut short."""
        (project / "AGENTS.md").write_text(OWN * 50, encoding="utf-8", newline="\n")

        def full(source, target):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr("chartbook.replacing.replace_when_let", full)
        result = _install()
        assert result.exit_code == 1 and _last(result).startswith("Error: AGENTS.md could not be written, and is as it was: ")
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN * 50
        assert sorted(path.name for path in project.iterdir()) == ["AGENTS.md", "chartbook.toml"]  # and nothing is left beside it


class TestWhatMovingAFileOverAnotherWouldPassOver:
    """Found by the second pass: the file is replaced by a move, which asks nothing of the file it replaces."""

    @pytest.mark.skipif(os.name != "nt" and os.geteuid() == 0, reason="nothing is read-only to root")
    def test_a_read_only_file_is_not_written(self, project):
        (project / "AGENTS.md").write_text(_of("0.5.1"), encoding="utf-8", newline="\n")
        (project / "AGENTS.md").chmod(0o444)
        try:
            result = _install()
        finally:
            (project / "AGENTS.md").chmod(0o644)
        assert result.exit_code == 1 and _last(result) == "Error: AGENTS.md was not written: it is read-only."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == _of("0.5.1")

    def test_one_file_under_two_names_is_not_written(self, project):
        """A hard link: the move would leave the other name with the old text, and say nothing."""
        (project / "AGENTS.md").write_text(_of("0.5.1"), encoding="utf-8", newline="\n")
        try:
            os.link(project / "AGENTS.md", project / "CLAUDE.md")
        except OSError:
            pytest.skip("no hard links here")
        result = _install()
        assert result.exit_code == 1 and _last(result) == (
            "Error: AGENTS.md was not written: it is one file under two names (a hard link), and the other name would "
            "keep the old text. Make one of them a symbolic link to the other."
        )
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == (project / "CLAUDE.md").read_text(encoding="utf-8") == _of("0.5.1")

    def test_what_somebody_saved_while_the_question_waited_is_not_lost(self, project, monkeypatch):
        """An editor, or another agent: the text to write was made from the file as it was read before the question."""
        text = OWN + "\n" + _written_in(agents.section())
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")

        def yes_after_a_colleague_saved(question, default):
            with open(project / "AGENTS.md", "a", encoding="utf-8", newline="\n") as f:
                f.write("A colleague's line.\n")
            return True

        monkeypatch.setattr(cli, "_can_ask", lambda: True)
        monkeypatch.setattr(cli, "_confirm", yes_after_a_colleague_saved)
        result = _install()
        assert result.exit_code == 1 and _last(result) == (
            "Error: AGENTS.md was not written: it was changed by something else while this ran. Run this again."
        )
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == text + "A colleague's line.\n"

    def test_a_file_that_appeared_meanwhile_is_not_written_over(self, project):
        (project / "AGENTS.md").write_text(OWN, encoding="utf-8", newline="\n")
        with pytest.raises(agents.NotWritten):
            agents.write(project / "AGENTS.md", agents.section(), was=None)
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN


class TestWhatAPersonWroteIsNotReplacedUnasked:
    """Found by review: only a section naming exactly this version was protected, and every other was replaced without a word."""

    CASES = {
        "this version's": lambda: _written_in(agents.section()),
        "an older one's": lambda: _written_in(_of("0.5.1")),
        "a newer one's": lambda: _written_in(_of("99.0.0")),
        "one that names no version": lambda: agents.section().replace(f" version={__version__}", ""),
        "one whose version is none": lambda: agents.section().replace(f"version={__version__}", "version=;rm"),
        "markers typed by a person": lambda: "<!-- chartbook:start -->\nOur own rules for ChartBook.\n<!-- chartbook:end -->\n",
        # Found by the second pass: the hash was of the text alone, and words in a marker's own comment went unasked
        "a word in its opening marker": lambda: _of("0.5.1").replace("two lines. -->", "two lines. Ana: do not touch before the audit. -->"),
        "a word in its closing marker": lambda: _of("0.5.1").replace("<!-- chartbook:end -->", "<!-- chartbook:end (see docs/agents.md for ours) -->"),
        "a version typed over": lambda: agents.section().replace(f"version={__version__}", "version=0.5.1"),
        "a version that is none, though its hash is right": lambda: agents.section("banana"),
    }

    @pytest.mark.parametrize("case", CASES)
    def test_where_nothing_can_ask_it_is_left_and_said(self, project, case):
        text = OWN + "\n" + self.CASES[case]()
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 1 and (project / "AGENTS.md").read_text(encoding="utf-8") == text
        assert _last(result).startswith("Error: The ChartBook section of AGENTS.md ")
        assert _last(result).endswith(
            " Notes of your own go outside its two marker lines. `chartbook install agents --force` replaces what is "
            "between them, and skill files changed by hand too."
        )

    def test_it_says_which_chartbook_wrote_what_was_changed(self, project):
        (project / "AGENTS.md").write_text(_written_in(_of("0.5.1")), encoding="utf-8", newline="\n")
        assert "was changed since ChartBook 0.5.1 wrote it." in _last(_install())
        (project / "AGENTS.md").write_text(self.CASES["markers typed by a person"](), encoding="utf-8", newline="\n")
        assert "is not one that `chartbook install agents` wrote." in _last(_install())
        # Nor is "ChartBook banana" said to have written anything
        (project / "AGENTS.md").write_text(_written_in(agents.section("banana")), encoding="utf-8", newline="\n")
        assert "is not one that `chartbook install agents` wrote." in _last(_install())

    def test_force_replaces_it(self, project):
        (project / "AGENTS.md").write_text(OWN + "\n" + _written_in(agents.section()), encoding="utf-8", newline="\n")
        result = _install("--force")
        assert result.exit_code == 0, result.output
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section()
        assert _last(result) == f"Wrote the ChartBook section of AGENTS.md again (ChartBook {__version__}). The rest of the file is as it was."

    def test_at_a_terminal_it_asks_and_no_leaves_it(self, project, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", lambda: True)
        text = OWN + "\n" + _written_in(agents.section())
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install(input="\n")  # Enter is no
        assert result.exit_code == 0 and (project / "AGENTS.md").read_text(encoding="utf-8") == text
        # It says which lines, and how many would go: found by the second pass, a yes was given without knowing what to
        lines = text.splitlines()
        first, last = lines.index(agents.section().splitlines()[0]) + 1, len(lines)
        assert f"The ChartBook section of AGENTS.md (lines {first} to {last}) was changed since ChartBook {__version__} wrote it." in result.output
        assert f"Replace what is between them ({last - first - 1} lines)? [y/N]: " in result.output
        assert _last(result) == "AGENTS.md was left as it is."
        result = _install(input="y\n")
        assert result.exit_code == 0 and (project / "AGENTS.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section()

    def test_a_newer_chartbooks_section_is_left_and_no_error(self, project):
        """As for the skill: two environments on two versions do not take turns at one committed file."""
        text = OWN + "\n" + _of("99.0.0")
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0 and (project / "AGENTS.md").read_text(encoding="utf-8") == text
        assert _last(result) == (
            f"AGENTS.md: its ChartBook section is for ChartBook 99.0.0, newer than this one, {__version__}. "
            "Left as it is (--force writes this version's)."
        )
        assert _install("--force").exit_code == 0 and agents.same(agents.read((project / "AGENTS.md").read_text(encoding="utf-8")))


    def test_this_versions_number_with_another_builds_text_is_replaced(self, project):
        """As that build left it, and not this one's: neither newer nor somebody's writing."""
        (project / "AGENTS.md").write_text(_of(__version__), encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0, result.output
        assert _last(result) == f"Wrote the ChartBook section of AGENTS.md again (ChartBook {__version__}). The rest of the file is as it was."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()

    def test_blank_lines_a_formatter_puts_inside_the_markers_are_nobodys_writing(self, project):
        """Or the command and the formatter would take turns at the file, one commit each."""
        first, *between, last = agents.section().splitlines(keepends=True)
        text = first + "\n" + "".join(between) + "\n" + last
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        assert _last(_install()) == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == text
        # Nor are spaces after a marker
        spaced = first.rstrip("\n") + "  \n" + "".join(between) + last.rstrip("\n") + " \n"
        (project / "AGENTS.md").write_text(spaced, encoding="utf-8", newline="\n")
        assert _last(_install()) == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."


class TestWhatAFenceIs:
    """Found by the second pass: any line that began with three backticks opened or closed a fence, and where the count
    went wrong the section below was never seen again: the command added another at every run."""

    SHAPES = {
        "inline code that begins a line": "```chartbook run``` builds everything.\n",
        "three backticks inside four": "````markdown\n```\n<!-- chartbook:end -->\n````\n",
        "a fence line with a word after it, inside a fence": "```\n```python\n<!-- chartbook:end -->\n```\n",
        "opened at three spaces and closed at four": "- An example:\n   ```\n   chartbook run\n    ```\n",
        "tildes inside backticks": "```\n~~~\n<!-- chartbook:end -->\n```\n",
        "backticks inside tildes": "~~~\n```\n<!-- chartbook:start -->\n~~~\n",
    }

    @pytest.mark.parametrize("shape", SHAPES)
    def test_the_section_below_one_is_found_and_the_file_does_not_grow(self, project, shape):
        above = OWN + self.SHAPES[shape] + "\n"
        (project / "AGENTS.md").write_text(above + _of("0.5.1"), encoding="utf-8", newline="\n")
        result = _install()
        assert _last(result) == f"Updated the ChartBook section of AGENTS.md from ChartBook 0.5.1 to {__version__}. The rest of the file is as it was."
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == above + agents.section()
        assert _last(_install()) == f"AGENTS.md: its ChartBook section is up to date (ChartBook {__version__})."

    @pytest.mark.parametrize("below", ["", "\n" + agents.section()], ids=["with no section", "with a section below it"])
    def test_one_that_is_never_closed_is_refused(self, project, below):
        """Everything below it is code: a section written there would be too, and would not be found the next time."""
        text = OWN + "```console\n$ chartbook run\n" + below
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install("--force")
        assert result.exit_code == 1 and (project / "AGENTS.md").read_text(encoding="utf-8") == text
        assert _last(result) == (
            "Error: AGENTS.md: the code fence opened on line 4 is never closed, so everything below it is part of that code, "
            "and a section written there would be too. Nothing was written to it: close the fence, and run this again."
        )


class TestWhatAMarkerIs:
    """Found by review: a line that only mentioned a marker was taken for one, and the project's text between two of them was replaced."""

    @pytest.mark.parametrize("text", [
        OWN + "Put `<!-- chartbook:start -->` above the section and `<!-- chartbook:end -->` below it.\n",
        OWN + "    <!-- chartbook:start -->\n\n## How we deploy\n\nThe password is in the vault.\n\n    <!-- chartbook:end -->\n",
        OWN + "```markdown\n<!-- chartbook:start -->\n## ChartBook\n<!-- chartbook:end -->\n```\n",
        OWN + "~~~\n<!-- chartbook:start -->\n~~~\n",
        OWN + "<!-- CHARTBOOK:START -->\nkept\n<!-- CHARTBOOK:END -->\n",
        OWN + "kept <!-- chartbook:start --> kept too\n",
    ], ids=["in a sentence", "indented as code", "in a fenced example", "in a fence of tildes", "in capitals", "after a line separator"])
    def test_a_mention_of_one_is_the_projects_own_text(self, project, text):
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0, result.output
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == text + "\n" + agents.section()
        assert "up to date" in _last(_install())

    @pytest.mark.parametrize("text, why", [
        (OWN + agents.section().rsplit(agents.END, 1)[0], "its `chartbook:start` line (line 4) has no `chartbook:end` line after it"),
        (OWN + agents.END + " -->\n", "its `chartbook:end` line (line 4) has no `chartbook:start` line before it"),
        (agents.section() + agents.section(), "it has `chartbook:start` on lines 1 and 16 and `chartbook:end` on lines 15 and 30, and one section is one of each, in that order"),
        (agents.END + " -->\n" + agents.START + " -->\n", "it has `chartbook:start` on line 2 and `chartbook:end` on line 1, and one section is one of each, in that order"),
        (
            agents.section().replace(agents.END + " -->", agents.END + " --> See also docs/agents.md for our own rules."),
            "its `chartbook:end` line (line 15) has other text on it, which replacing the section would take with it: a marker line holds the marker and nothing else",
        ),
        (
            agents.section().replace("lines. -->\n", "lines. --> NOTE: ask Ana before deploying\n"),
            "its `chartbook:start` line (line 1) has other text on it, which replacing the section would take with it: a marker line holds the marker and nothing else",
        ),
    ])
    def test_marker_lines_that_do_not_hold_one_section_are_an_error_that_says_which_line(self, project, text, why):
        assert len(agents.section().splitlines()) == 15
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        result = _install("--force")
        assert result.exit_code == 1
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == text
        assert _last(result) == (
            f"Error: AGENTS.md: {why}. Nothing was written to it: put its marker lines right, or take them out, and run this again."
        )

    def test_a_section_at_the_top_of_a_file_with_a_byte_order_mark(self, project):
        """Found by review: its start line was not seen, and the command was a dead end."""
        (project / "AGENTS.md").write_bytes(("\ufeff" + _of("0.5.1") + OWN).encode("utf-8"))
        assert _install().exit_code == 0
        assert (project / "AGENTS.md").read_bytes().decode("utf-8") == "\ufeff" + agents.section() + OWN

    def test_a_file_that_is_no_text(self, project):
        (project / "AGENTS.md").write_bytes(b"\xff\xfe\x00not utf-8")
        result = _install()
        assert result.exit_code == 1 and _last(result).startswith("Error: AGENTS.md cannot be read as text: ")
        assert (project / "AGENTS.md").read_bytes() == b"\xff\xfe\x00not utf-8"


@pytest.mark.skipif(os.name == "nt", reason="a link is made as an administrator there")
class TestAFileThatIsALink:
    """Found by review: a link was written through wherever it led, and one to nothing made the file it named."""

    def test_to_a_file_of_the_project_it_is_written_through_and_stays_a_link(self, project):
        (project / "CLAUDE.md").write_text(OWN, encoding="utf-8", newline="\n")
        (project / "AGENTS.md").symlink_to("CLAUDE.md")
        result = _install()
        assert result.exit_code == 0, result.output
        assert _last(result) == f"Added a ChartBook section to AGENTS.md (a link to CLAUDE.md) (ChartBook {__version__}). The rest of the file is as it was."
        assert (project / "AGENTS.md").is_symlink() and (project / "CLAUDE.md").read_text(encoding="utf-8") == OWN + "\n" + agents.section()

    def test_to_a_file_outside_the_project_nothing_is_written(self, project, tmp_path):
        (tmp_path / "TEAM.md").write_text(OWN, encoding="utf-8", newline="\n")
        (project / "AGENTS.md").symlink_to(tmp_path / "TEAM.md")
        result = _install()
        assert result.exit_code == 1 and (tmp_path / "TEAM.md").read_text(encoding="utf-8") == OWN
        assert _last(result) == f"Error: AGENTS.md is a link to {(tmp_path / 'TEAM.md').resolve()}, outside this project. Nothing was written to it."

    def test_to_a_folder_it_says_so(self, project):
        (project / "notes").mkdir()
        (project / "AGENTS.md").symlink_to("notes")
        result = _install()
        assert result.exit_code == 1
        assert _last(result) == f"Error: AGENTS.md is a link to {project / 'notes'}, which is a folder. Nothing was written."

    def test_to_nothing_nothing_is_made(self, project):
        (project / "AGENTS.md").symlink_to(project / "not-there.md")
        result = _install()
        assert result.exit_code == 1 and not (project / "not-there.md").exists()
        assert _last(result) == f"Error: AGENTS.md is a link to {project / 'not-there.md'}, which is not there. Nothing was written."


class TestTheTwoHalves:
    """Found by review: where the skill's question could not be answered, or its folder not written, the section was not written either."""

    def _changed_skill(self, claude_config_dir) -> Path:
        _install()
        skill = claude_config_dir / "skills" / "chartbook" / "SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nmine\n", encoding="utf-8", newline="\n")
        return skill

    def test_the_section_is_written_though_the_skill_was_declined(self, project, claude_config_dir):
        skill = self._changed_skill(claude_config_dir)
        (project / "AGENTS.md").unlink()
        result = _install(input="n\n")
        assert result.exit_code == 0, result.output
        assert skill.read_text(encoding="utf-8").endswith("\nmine\n") and (project / "AGENTS.md").is_file()

    def test_and_where_its_question_could_not_be_answered(self, project, claude_config_dir):
        skill = self._changed_skill(claude_config_dir)
        (project / "AGENTS.md").unlink()
        result = _install(input="")  # the end of input at its question
        assert result.exit_code == 1 and (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()
        assert "The skill was left as it is: `chartbook install claude-skill` installs it, and asks." in result.output.splitlines()
        assert skill.read_text(encoding="utf-8").endswith("\nmine\n")

    @pytest.mark.skipif(os.name == "nt", reason="a folder is not made read-only to its owner there")
    def test_and_where_the_skills_folder_cannot_be_written(self, project, claude_config_dir):
        claude_config_dir.mkdir()
        claude_config_dir.chmod(0o500)
        try:
            result = _install()
        finally:
            claude_config_dir.chmod(0o700)
        assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
        assert any(line.startswith("Error: the skill could not be installed: ") for line in result.output.splitlines())
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()

    def test_ctrl_c_at_the_skills_question_ends_the_command(self, project, claude_config_dir, monkeypatch):
        """Found by the second pass: it was taken for a question nobody could answer, and the project's file was written."""
        self._changed_skill(claude_config_dir)
        (project / "AGENTS.md").unlink()
        monkeypatch.setattr(cli, "_can_ask", lambda: True)  # a person is there
        result = _install(input="")  # and ends the question
        assert result.exit_code == 1 and isinstance(result.exception, SystemExit) and "Aborted!" in result.output
        assert not (project / "AGENTS.md").exists()

    def test_a_newer_chartbooks_skill_is_left_and_no_error(self, project, claude_config_dir):
        """Found by the second pass: from the older of two environments the command failed every time, having done the right thing."""
        _install()
        (project / "AGENTS.md").unlink()
        skill = claude_config_dir / "skills" / "chartbook" / "SKILL.md"
        newer = skill.read_text(encoding="utf-8").replace(f'chartbook-version: "{__version__}"', 'chartbook-version: "99.0.0"')
        assert "99.0.0" in newer
        skill.write_text(newer, encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0].endswith(
            f"is for ChartBook 99.0.0, newer than this one, {__version__}. Left as it is (--force installs this version's)."
        )
        assert skill.read_text(encoding="utf-8") == newer and (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()
        assert _install("--force").exit_code == 0 and claude_skill.version_of(skill.parent) == __version__

    def test_force_is_for_both(self, project, claude_config_dir):
        skill = self._changed_skill(claude_config_dir)
        (project / "AGENTS.md").write_text(_written_in(agents.section()), encoding="utf-8", newline="\n")
        result = _install("--force")
        assert result.exit_code == 0, result.output
        assert not skill.read_text(encoding="utf-8").endswith("\nmine\n")
        assert (project / "AGENTS.md").read_text(encoding="utf-8") == agents.section()

    def test_the_skill_stays_the_first_half_alone(self, project, claude_config_dir):
        result = CliRunner().invoke(main, ["install", "claude-skill"])
        assert result.exit_code == 0 and not (project / "AGENTS.md").exists()
        assert claude_skill.version_of(claude_config_dir / "skills" / "chartbook") == __version__


class TestWhereAProjectIs:
    def test_outside_one_it_installs_the_skill_and_says_what_the_other_half_is_for(self, tmp_path, monkeypatch, claude_config_dir):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        result = _install()
        assert result.exit_code == 0, result.output
        assert (claude_config_dir / "skills" / "chartbook" / "SKILL.md").is_file()
        assert _last(result) == (
            "No chartbook.toml here, or above in this repository: the AGENTS.md half is for a project. Run "
            "`chartbook install agents` in a pipeline's folder to write it."
        )
        assert not (elsewhere / "AGENTS.md").exists()

    def test_a_pipeline_at_the_top_of_its_repository(self, project):
        (project / ".git").mkdir()
        assert agents.project_folder(project) == project
        (project / "src" / "deep").mkdir(parents=True)
        assert agents.project_folder(project / "src" / "deep") == project

    def test_not_above_its_repository(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        inner = tmp_path / "another-repository"
        (inner / ".git").mkdir(parents=True)
        assert agents.project_folder(inner) is None and agents.project_folder(tmp_path) == tmp_path.resolve()

    def test_in_no_repository_only_the_folder_itself(self, tmp_path):
        """Found by review: with no git the walk went up to the top of the disk, and a stray manifest four folders up got the file."""
        (tmp_path / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        (tmp_path / "a" / "b").mkdir(parents=True)
        assert agents.project_folder(tmp_path / "a" / "b") is None and agents.project_folder(tmp_path) == tmp_path.resolve()

    def test_never_the_home_folder(self, tmp_path, monkeypatch):
        (tmp_path / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / "work").mkdir()
        assert agents.project_folder(tmp_path / "work") is None and agents.project_folder(tmp_path) is None
        # Where the home folder is itself a repository, its folders are not one project: only the folder itself
        (tmp_path / "work" / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        (tmp_path / "work" / "deep").mkdir()
        assert agents.project_folder(tmp_path / "work" / "deep") is None
        assert agents.project_folder(tmp_path / "work") == (tmp_path / "work").resolve()

    def test_a_manifest_that_is_none_gets_no_file_beside_it(self, project):
        (project / "chartbook.toml").write_text("not [toml", encoding="utf-8", newline="\n")
        result = _install()
        assert result.exit_code == 1 and not (project / "AGENTS.md").exists()
        assert _last(result).startswith("Error: chartbook.toml cannot be read as a manifest (")


class TestASectionOfAnOlderChartBook:
    """It teaches an agent that version's commands: said as a stale skill is."""

    def test_it_is_found_and_said(self, project, tmp_path, monkeypatch):
        (project / "AGENTS.md").write_text(_of("0.5.1"), encoding="utf-8", newline="\n")
        assert agents.stale(project) == (project / "AGENTS.md", "0.5.1")
        said = agents.notice(project / "AGENTS.md", "0.5.1")
        assert "is for ChartBook 0.5.1" in said and "`chartbook install agents` in " in said
        assert f"warning: {said}" in CliRunner().invoke(main, ["run", "--check"]).output.splitlines()
        # Of the project the check is asked of, wherever it is typed
        monkeypatch.chdir(tmp_path)
        assert f"warning: {said}" in CliRunner().invoke(main, ["run", "--check", "--project-dir", str(project)]).output.splitlines()

    @pytest.mark.parametrize("text", [
        "", OWN, agents.section(), _of("99.0.0"), agents.section().replace(f" version={__version__}", ""),
        agents.START + " version=0.5.1 -->\n",  # no section: its marker lines do not hold one
        # Found by the second pass: one somebody wrote in was called stale for ever, since the command named would not replace it unasked
        _written_in(_of("0.5.1")),
        "<!-- chartbook:start version=0.1 -->\nOur own rules.\n<!-- chartbook:end -->\n",
        _of(__version__),  # this version's number, from another build of it
    ])
    def test_not_this_versions_a_newer_ones_one_somebody_wrote_in_or_none(self, project, text):
        (project / "AGENTS.md").write_text(text, encoding="utf-8", newline="\n")
        assert agents.stale(project) is None

    def test_a_person_at_a_terminal_is_told_in_one_line(self, project, monkeypatch):
        (project / "AGENTS.md").write_text(_of("0.5.1"), encoding="utf-8", newline="\n")
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        result = CliRunner().invoke(main, ["ls", "--help"])
        assert f"Note: {agents.notice(project / 'AGENTS.md', '0.5.1')}" in result.output.splitlines()


class TestWhatTheSectionSays:
    def test_every_command_and_option_it_names_is_one(self):
        """As the skill and the llms files are held to: an agent is not taught a command, or an option, that is gone."""
        named = re.findall(r"`chartbook ((?:[a-z-]+ ?)+)", agents.body())
        assert len(named) >= 8
        for words in named:
            group = main
            for word in words.split():
                if word.startswith("-"):
                    # --help is every command's, and is not among its own options
                    assert word == "--help" or any(word in parameter.opts for parameter in group.params), (
                        f"`chartbook {words}`: `{word}` is no option of it"
                    )
                    continue
                if not isinstance(group, click.Group):
                    break  # an argument
                assert word in group.commands, f"`chartbook {words}` is in agents_section.md, and `{word}` is no command"
                group = group.commands[word]

    def test_what_it_calls_in_python_is_there(self):
        called = re.findall(r"`data\.(\w+)\(", agents.body())
        assert called == ["load", "path"] and all(callable(getattr(chartbook_data, name)) for name in called)

    def test_it_sends_an_agent_to_nothing_that_writes_over_a_persons_files(self):
        """Found by review: it named `chartbook docs build`, which asks before it replaces `docs/`, and said to do what a message says."""
        text = agents.body()
        assert "docs build" not in text and "catalog open" not in text and "catalog build" not in text
        assert "Do not answer a question it asks, add `--force` or `-f`, or run `chartbook trust` on your own" in text

    def test_its_markers_name_the_version_the_text_and_what_writes_it(self):
        first, *_, last = agents.section().splitlines()
        assert re.fullmatch(
            rf"<!-- chartbook:start version={re.escape(__version__)} text=[0-9a-f]{{12}}; written by `chartbook install agents`, .* -->", first
        )
        assert last == "<!-- chartbook:end -->"
        found = agents.read(OWN + agents.section() + "tail\n")
        assert (found.before, found.after, found.version, found.untouched) == (OWN, "tail\n", __version__, True)
        assert agents.same(found) and agents.standing(found) == "current"
        assert agents.standing(agents.read(_of("0.5.1"))) == "older" and agents.standing(agents.read(_of("99.0.0"))) == "newer"
        assert agents.standing(agents.read(_written_in(_of("0.5.1")))) == "by hand" and agents.standing(agents.read(OWN)) == "none"
