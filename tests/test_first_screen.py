"""The first screen: ``chartbook --help`` and the pages a person reads first open with the five commands (``docs_src/design/one-command.md``).

Twenty-one commands in one alphabetical list say nothing of which matter.
Five are what most people type: ``chartbook init``, ``chartbook run``,
``chartbook pin --update``, ``chartbook catalog open`` and ``chartbook
install agents``. The help lists them first, as they are typed; the
README, the Quickstart, the reference, the skill and ``llms.txt`` each
have them in a section of their own; and these tests hold all of it to
one list, ``chartbook.cli.THE_FIVE``, and that list to the CLI.
"""

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from chartbook import cli
from chartbook.cli import main

ROOT = Path(__file__).parent.parent
FIVE = [words for words, _ in cli.THE_FIVE]
#: Where a person, or an agent, starts reading
FIRST_PAGES = [
    "README.md", "docs_src/getting-started.md", "docs_src/reference/cli.md", "llm/llms.txt", "llms.txt",
    "src/chartbook/skills/SKILL.md", ".claude/skills/chartbook/SKILL.md",
    "template/{{cookiecutter.project_slug}}/.claude/skills/chartbook/SKILL.md",
]


def _help() -> list[str]:
    result = CliRunner().invoke(main, ["--help"], prog_name="chartbook", terminal_width=100)
    assert result.exit_code == 0, result.output
    return result.output.splitlines()


def _section(lines: list[str], heading: str) -> list[str]:
    """The lines under a heading of the help, down to the blank line that ends it."""
    start = lines.index(heading) + 1
    end = next((number for number in range(start, len(lines)) if not lines[number].strip()), len(lines))
    return lines[start:end]


class TestTheHelp:
    def test_the_five_are_what_they_are(self):
        assert FIVE == ["chartbook init", "chartbook run", "chartbook pin --update", "chartbook catalog open", "chartbook install agents"]

    def test_it_opens_with_them_as_they_are_typed(self):
        lines = _help()
        assert lines.index("Start with these:") < lines.index("More:")
        assert _section(lines, "Start with these:") == [f"  {words:<24}  {what}" for words, what in cli.THE_FIVE]

    def test_each_is_one_line_in_a_terminal_of_eighty(self):
        result = CliRunner().invoke(main, ["--help"], prog_name="chartbook", terminal_width=80)
        assert len(_section(result.output.splitlines(), "Start with these:")) == 5

    def test_the_rest_are_all_there_by_name(self):
        """`init` and `run` are whole in the first list; a command with more to it than its form there is listed again."""
        more = [line.split()[0] for line in _section(_help(), "More:")]
        listed = sorted(name for name, command in main.commands.items() if not command.hidden)
        assert more == [name for name in listed if name not in ("init", "run")]
        assert {"pin", "catalog", "install"} <= set(more)

    def test_a_command_that_is_hidden_stays_hidden(self):
        hidden = [name for name, command in main.commands.items() if command.hidden]
        said = "\n".join(_help())
        assert all(not re.search(rf"^  {re.escape(name)}\b", said, re.M) for name in hidden)

    @pytest.mark.parametrize("words", FIVE)
    def test_each_of_the_five_is_a_command_there_is(self, words):
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
    def test_each_has_the_five_in_a_section_of_their_own_in_that_order(self, page):
        text = (ROOT / page).read_text(encoding="utf-8")
        found = re.search(r"^## The five commands\n(.*?)(?=^## )", text, re.M | re.S)
        assert found, f"{page} has no section `## The five commands`"
        rows = re.findall(r"^\| `(chartbook [^`]+)` \|", found.group(1), re.M)
        assert rows == FIVE, f"{page}: its five are {rows}"

    @pytest.mark.parametrize("page", FIRST_PAGES)
    def test_that_section_comes_before_the_long_list(self, page):
        """The first screen is the five. Whatever lists every command comes after."""
        text = (ROOT / page).read_text(encoding="utf-8")
        five = text.index("## The five commands")
        for later in ("## Key CLI Commands", "## Every command", "## Get started", "## A pipeline, in three files", "## Next"):
            if later in text:
                assert five < text.index(later), f"{page}: `{later}` comes before the five"
