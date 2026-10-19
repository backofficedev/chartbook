"""The CLI reference page says what the CLI has: every command, every option, every argument.

`docs_src/reference/cli.md` is written by hand, in prose, because the
reasons behind a command matter more than its signature. This keeps the
hand honest: a command, an option or an argument added to `chartbook.cli`
without a word on the page fails here, and so does a page that names a
command that is gone.

The page's shape, as the test reads it: a `## chartbook <name>` heading
opens the section of a top-level command or group, and runs to the next
`## ` heading outside a fenced block (a group may also have one such
heading per subcommand). A subcommand is named in its group's section as
`chartbook <group> <sub>` or under a `### <group> <sub>` heading; where it
has a `###` heading, its options are looked for under that heading alone.
Options are matched by a spelling the CLI accepts, long or short, as a
whole word. A section that says it takes the arguments of another command,
as `build` does of `docs`, is read with that command's section.
"""

import re
from pathlib import Path

import click
import pytest

from chartbook.cli import main

PAGE = Path(__file__).parent.parent / "docs_src" / "reference" / "cli.md"
#: Options every click program has, which the page need not spell out.
IMPLIED = frozenset({"--help"})


def _runnable(group, path=()):
    """Every command a user can run, as its words after ``chartbook``, with the command.

    A group counts when it can be run on its own or has options of its own.
    Hidden commands are left to the prose that explains them.
    """
    if path and (group.invoke_without_command or any(isinstance(p, click.Option) for p in group.params)):
        yield path, group
    for name, command in sorted(group.commands.items()):
        if command.hidden:
            continue
        words = (*path, name)
        if isinstance(command, click.Group):
            yield from _runnable(command, words)
        else:
            yield words, command


COMMANDS = list(_runnable(main))
IDS = ["-".join(words) for words, _ in COMMANDS]
SUBCOMMANDS = [(words, command) for words, command in COMMANDS if len(words) > 1]
TOPS = sorted({words[0] for words, _ in COMMANDS})


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _whole(text: str, word: str) -> bool:
    """Whether *word* is in *text* as a whole word: not inside another word or option."""
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text) is not None


def _sections(page: str) -> dict:
    """The page by heading: ``## chartbook <words>`` and ``### <words>`` headings outside fences."""
    found = {}
    current = None
    in_fence = False
    for line in page.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^##+ ", line):
            current = line.strip()
            found.setdefault(current, [])
        if current is not None:
            found[current].append(line)
    return {heading: "\n".join(lines) for heading, lines in found.items()}


def _section(page: str, top: str, seen=()) -> str:
    """The text of every ``## chartbook <top>…`` section, with ``###`` subsections, as one.

    A section that says it takes the arguments of another command is read
    with that command's section; the chain stops where it would repeat.
    """
    text = ""
    sections = _sections(page)
    headings = list(sections)
    for position, heading in enumerate(headings):
        if re.match(rf"^## chartbook {re.escape(top)}( [a-z-]+)*$", heading):
            text += sections[heading] + "\n"
            for later in headings[position + 1:]:
                if later.startswith("## "):
                    break
                text += sections[later] + "\n"
    for other in re.findall(r"takes the (?:same )?arguments (?:of|as) (?:\{ref\})?`chartbook ([a-z-]+)", text):
        if other not in (top, *seen):
            text += _section(page, other, (*seen, top))
    return text


def _own_subsection(page: str, words: tuple) -> str:
    """The ``###`` subsection of a subcommand, if the page gives it one; else its group's section.

    The heading names the group as well as the subcommand: two groups may
    have a subcommand of one name, as `docs generate` and `catalog generate`
    do, and the first `### … generate` on the page was the wrong one.
    """
    if len(words) > 1:
        for heading, text in _sections(page).items():
            if heading.startswith("### ") and _whole(heading, words[-1]) and _whole(heading, words[-2]):
                return text
    return _section(page, words[0])


@pytest.mark.parametrize("top", TOPS)
def test_the_command_has_a_section(top, page):
    assert re.search(rf"^## chartbook {re.escape(top)}( [a-z-]+)*$", page, re.M), f"no `## chartbook {top}` heading on the page"


@pytest.mark.parametrize("words,command", SUBCOMMANDS, ids=["-".join(words) for words, _ in SUBCOMMANDS])
def test_a_subcommand_is_named_under_its_group(words, command, page):
    section = _section(page, words[0])
    named = re.search(rf"(?<![\w-])chartbook {' '.join(map(re.escape, words))}(?![\w-])", section)
    headed = re.search(rf"^### .*(?<![\w-]){re.escape(words[-1])}(?![\w-])", section, re.M)
    assert named or headed, f"`chartbook {' '.join(words)}` is not named under `## chartbook {words[0]}`"


@pytest.mark.parametrize("words,command", COMMANDS, ids=IDS)
def test_every_option_is_on_the_page(words, command, page):
    """Each option appears by a spelling the CLI accepts, long or short, as a whole word."""
    section = _own_subsection(page, words)
    for parameter in command.params:
        if not isinstance(parameter, click.Option) or parameter.hidden:
            continue
        for spellings in (parameter.opts, parameter.secondary_opts):
            if not spellings or set(spellings) <= IMPLIED:
                continue
            assert any(_whole(section, opt) for opt in spellings), (
                f"`chartbook {' '.join(words)}` has {'/'.join(spellings)}, which the page does not mention where it documents the command"
            )


@pytest.mark.parametrize("words,command", COMMANDS, ids=IDS)
def test_every_argument_is_on_the_page(words, command, page):
    """Each positional argument appears by its name, or in a console line that shows it in use."""
    section = _own_subsection(page, words)
    for parameter in command.params:
        if not isinstance(parameter, click.Argument):
            continue
        shown = _whole(section, parameter.human_readable_name) or re.search(
            rf"^\$? ?chartbook {' '.join(map(re.escape, words))} [^-\s\[]", section, re.M
        )
        assert shown, (
            f"`chartbook {' '.join(words)}` takes {parameter.human_readable_name}, which the page neither names nor shows in use"
        )


def test_the_programs_own_options_are_on_the_page(page):
    for parameter in main.params:
        if isinstance(parameter, click.Option) and not set(parameter.opts) <= IMPLIED:
            assert any(_whole(page, opt) for opt in parameter.opts), f"`chartbook {parameter.opts[0]}` is not on the page"


def test_the_page_names_no_command_that_is_gone(page):
    """Headings and console lines name only commands the CLI has, hidden ones included."""
    for heading in _sections(page):
        match = re.match(r"^## chartbook ([a-z-]+)((?: [a-z-]+)*)$", heading)
        if match:
            assert match.group(1) in main.commands, f"{heading!r} names a command the CLI does not have"
            for sub in match.group(2).split():
                assert sub in main.commands[match.group(1)].commands, f"{heading!r} names a subcommand the CLI does not have"
    for group_name, sub in re.findall(r"(?<![\w-])chartbook ([a-z-]+) ([a-z][a-z-]*)(?![\w/.-])", page):
        group = main.commands.get(group_name)
        if isinstance(group, click.Group):
            assert sub in group.commands, f"`chartbook {group_name} {sub}` names a subcommand the CLI does not have"


@pytest.mark.parametrize("words,command", COMMANDS, ids=IDS)
def test_no_help_shows_docstring_markup(words, command):
    """`--help` prints a command's docstring: a `:param` field list there is noise to a reader."""
    for field in (":param", ":type", ":returns", ":raises"):
        assert field not in (command.help or ""), f"`chartbook {' '.join(words)} --help` shows {field}"


def _console_lines(section: str) -> list:
    """The lines inside the ```console blocks of a section, with any `# comment` taken off."""
    lines, in_fence = [], False
    for line in section.splitlines():
        if line.startswith("```"):
            in_fence = line.startswith("```console")
        elif in_fence:
            lines.append(line.split("#")[0].rstrip())
    return lines


@pytest.mark.parametrize("words,command", COMMANDS, ids=IDS)
def test_a_usage_line_shows_every_option(words, command, page):
    """A console line `chartbook <command> … [--option]` is the command's usage line, and shows every option.

    Found by a reviewer: `pin` and `run` had grown `--frozen`, their usage lines had
    not, and the test above could not see it, since it matches words anywhere in the
    section. A line that says `[OPTIONS]` defers to the table below it.
    """
    section = _own_subsection(page, words)
    usage = [
        line
        for line in _console_lines(section)
        if re.match(rf"^chartbook {' '.join(map(re.escape, words))}( |$)", line) and "[" in line and "[OPTIONS]" not in line
    ]
    for line in usage:
        for parameter in command.params:
            if not isinstance(parameter, click.Option) or parameter.hidden:
                continue
            spellings = [*parameter.opts, *parameter.secondary_opts]
            if set(spellings) <= IMPLIED:
                continue
            assert any(_whole(line, opt) for opt in spellings), (
                f"the usage line {line!r} of `chartbook {' '.join(words)}` leaves out {'/'.join(spellings)}"
            )


def test_the_size_threshold_says_what_it_governs(page):
    """Found by a reviewer: `docs --help` still said "memory-efficient loading" after
    the glimpse stopped depending on the size; the page and the help now say the same."""
    (option,) = [p for p in main.commands["docs"].commands["generate"].params if "--size-threshold" in getattr(p, "opts", [])]
    assert "date range" in option.help and "memory-efficient" not in option.help
    (row,) = [line for line in page.splitlines() if line.startswith("| `--size-threshold FLOAT`")]
    assert "date range" in row
