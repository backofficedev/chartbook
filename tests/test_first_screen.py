"""The first screen: ``chartbook --help`` and the pages a person reads first open with the commands to start with (``docs_src/design/one-command.md``).

Twenty-one commands in one alphabetical list say nothing of which matter.
Six are what most people type: ``chartbook init``, ``chartbook run``,
``chartbook snapshot``, ``chartbook pin --update``, ``chartbook catalog
open`` and ``chartbook install agents``. The help lists them first, as
they are typed; the README, the Quickstart, the reference, the skill and
``llms.txt`` each have them in a section of their own; and these tests
hold the words of all of it, as they are written here, and each of the
six to the CLI.

They were five until 2026-11-20, while a run ended with a snapshot. The
section's heading names no number, so that the next change is of a row.
"""

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from chartbook import cli
from chartbook.cli import main

ROOT = Path(__file__).parent.parent
KNOWN = [words for words, _ in cli.TO_KNOW]
#: The help's six lines, as a terminal of eighty columns shows them. Written here, and not read from
#: the code: what each line says is held, and not only which command it names
HELP = [
    "  chartbook init            Start a project from the template",
    "  chartbook run             Build this pipeline, pinning what it reads",
    "  chartbook snapshot        Make this build what other pipelines read",
    "  chartbook pin --update    Take newer snapshots of what this one reads",
    "  chartbook catalog open    Browse every snapshot in your stores",
    "  chartbook install agents  Teach your coding agent ChartBook",
]
#: The table every first page has, word for word
TABLE = """\
| You type | It does |
|---|---|
| `chartbook init` | Once: starts a project from the template, in a new folder |
| `chartbook run` | Builds this pipeline: pins what it reads, runs its build script, and looks for everything `chartbook.toml` declares |
| `chartbook snapshot` | Puts that build in your store, labelled with its commit, where other pipelines read it and the catalog shows it. Commit first |
| `chartbook pin --update` | Takes the newest snapshot of each pipeline it reads |
| `chartbook catalog open` | Opens the catalog in your browser: every snapshot in your stores |
| `chartbook install agents` | Once per project: teaches your coding agent ChartBook |
"""
#: Where a person, or an agent, starts reading
FIRST_PAGES = [
    "README.md", "docs_src/index.md", "docs_src/getting-started.md", "docs_src/reference/cli.md",
    "llm/llms.txt", "llms.txt", "llm/llms-full.txt",
    "src/chartbook/skills/SKILL.md", ".claude/skills/chartbook/SKILL.md",
    "template/{{cookiecutter.project_slug}}/.claude/skills/chartbook/SKILL.md",
]


def _help() -> list[str]:
    result = CliRunner().invoke(main, ["--help"], prog_name="chartbook")
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


def _help_in_a_terminal_of(columns: int) -> list[str]:
    """The help as a process told its terminal is so wide prints it: click takes two columns off, and never goes over eighty.

    In a process of its own: what a test's runner passes for a width is not what a terminal gives.
    """
    import os
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-c", "from chartbook.cli import main; main(prog_name='chartbook')", "--help"],
        env={**os.environ, "COLUMNS": str(columns), "NO_COLOR": "1"}, capture_output=True, text=True, encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


def _section(lines: list[str], heading: str) -> list[str]:
    """The lines under a heading of the help, down to the blank line that ends it."""
    start = lines.index(heading) + 1
    end = next((number for number in range(start, len(lines)) if not lines[number].strip()), len(lines))
    return lines[start:end]


class TestTheHelp:
    def test_they_are_what_they_are(self):
        assert KNOWN == [
            "chartbook init", "chartbook run", "chartbook snapshot", "chartbook pin --update", "chartbook catalog open",
            "chartbook install agents",
        ]

    def test_no_line_says_that_a_run_makes_a_snapshot(self):
        """A run builds, and a snapshot is typed: the line for `run` says nothing of one, and `snapshot` has a line of its own."""
        said = dict(cli.TO_KNOW)
        assert "snapshot" not in said["chartbook run"].lower()
        assert "other pipelines read" in said["chartbook snapshot"]

    def test_it_opens_with_them_as_they_are_typed(self):
        lines = _help()
        assert lines.index("Start with these:") < lines.index("More:")
        assert _section(lines, "Start with these:") == HELP

    def test_each_is_one_line_in_a_terminal_of_eighty_with_room_to_spare(self):
        """Found by review: the test asked click for a width no terminal of eighty has, and one line had no room at all."""
        assert all(len(line) <= 72 for line in HELP)
        assert _section(_help_in_a_terminal_of(80), "Start with these:") == HELP
        assert _section(_help_in_a_terminal_of(200), "Start with these:") == HELP
        assert len(_section(_help_in_a_terminal_of(60), "Start with these:")) > 6  # and this does see a narrower one

    def test_the_rest_are_all_there_by_name(self):
        """`init`, `run` and `snapshot` are whole in the first list; a command with more to it than its form there is listed again."""
        more = [line.split()[0] for line in _section(_help(), "More:")]
        listed = sorted(name for name, command in main.commands.items() if not command.hidden)
        assert more == [name for name in listed if name not in ("init", "run", "snapshot")]
        assert {"pin", "catalog", "install"} <= set(more)

    def test_a_command_that_is_hidden_stays_hidden(self):
        hidden = [name for name, command in main.commands.items() if command.hidden]
        said = "\n".join(_help())
        assert all(not re.search(rf"^  {re.escape(name)}\b", said, re.M) for name in hidden)

    @pytest.mark.parametrize("words", KNOWN)
    def test_each_is_a_command_there_is(self, words):
        group = main
        for word in words.split()[1:]:
            if word.startswith("--"):
                assert any(word in parameter.opts for parameter in group.params), f"{words}: no option {word}"
                continue
            assert isinstance(group, click.Group) and word in group.commands, f"{words}: no command {word}"
            group = group.commands[word]
        assert not group.hidden

    def test_a_commands_own_help_is_as_it_was(self):
        result = CliRunner().invoke(main, ["pin", "--help"], prog_name="chartbook")
        assert result.exit_code == 0 and "Start with these" not in result.output and "--update" in result.output
        group = CliRunner().invoke(main, ["catalog", "--help"], prog_name="chartbook")
        assert "Commands:" in group.output and "Start with these" not in group.output


class TestThePagesReadFirst:
    @pytest.mark.parametrize("page", FIRST_PAGES)
    def test_each_has_them_in_a_section_of_their_own_word_for_word(self, page):
        """Found by review: the names were held, and a row could say anything of its command."""
        text = (ROOT / page).read_text(encoding="utf-8")
        found = re.search(r"^## Start with these\n(.*?)(?=^## )", text, re.M | re.S)
        assert found, f"{page} has no section `## Start with these`"
        assert TABLE in found.group(1), f"{page}: its table is not the one every first page has"
        assert re.findall(r"^\| `(chartbook [^`]+)` \|", found.group(1), re.M) == KNOWN

    def test_the_table_and_the_help_are_of_the_same_commands(self):
        assert re.findall(r"^\| `(chartbook [^`]+)` \|", TABLE, re.M) == KNOWN == [line[2:26].strip() for line in HELP]

    @pytest.mark.parametrize("page", FIRST_PAGES)
    def test_no_page_counts_them_wrong(self, page):
        """The sentence over the table says how many, and which are typed in a pipeline's folder."""
        text = (ROOT / page).read_text(encoding="utf-8")
        assert "The five commands" not in text and "Five commands cover" not in text
        assert "Six commands cover most of what people do" in text

    @pytest.mark.parametrize("page", FIRST_PAGES)
    def test_that_section_comes_before_the_long_list(self, page):
        """The first screen is these. Whatever lists every command comes after."""
        text = (ROOT / page).read_text(encoding="utf-8")
        first = text.index("## Start with these")
        for later in ("## Key CLI Commands", "## More commands", "## CLI Reference", "## Get started", "## A pipeline, in three files", "## Next"):
            if later in text:
                assert first < text.index(later), f"{page}: `{later}` comes before the commands to start with"
