"""The CLI reference page says what the CLI has: every command, every option.

`docs_src/reference/cli.md` is written by hand, in prose, because the
reasons behind a command matter more than its signature. This keeps the
hand honest: a command or an option added to `chartbook.cli` without a
word on the page fails here, and so does a page that documents a command
that is gone.
"""

import re
from pathlib import Path

import click
import pytest

from chartbook.cli import main

PAGE = Path(__file__).parent.parent / "docs_src" / "reference" / "cli.md"


def _commands(group, path=()):
    """Every command a user can run, as its words after ``chartbook``, with its options."""
    for name, command in sorted(group.commands.items()):
        if command.hidden:
            continue  # reserved names, which the page explains in prose where it matters
        words = (*path, name)
        if isinstance(command, click.Group):
            yield from _commands(command, words)
        else:
            yield words, command


COMMANDS = list(_commands(main))


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.mark.parametrize("words,command", COMMANDS, ids=[" ".join(words) for words, _ in COMMANDS])
def test_the_command_has_a_section(words, command, page):
    """A top-level command has a `## chartbook <name>` heading; a subcommand is named under its group's."""
    top = words[0]
    assert re.search(rf"^## chartbook {re.escape(top)}\b", page, re.M), f"no `## chartbook {top}` heading on the page"
    if len(words) > 1:
        section = _section(page, top)
        assert words[-1] in section, f"`chartbook {' '.join(words)}` is not mentioned under `## chartbook {top}`"


@pytest.mark.parametrize("words,command", COMMANDS, ids=[" ".join(words) for words, _ in COMMANDS])
def test_every_option_is_on_the_page(words, command, page):
    """Each option appears, by its long name or a short one, somewhere under the command's heading."""
    section = _section(page, words[0])
    for parameter in command.params:
        if not isinstance(parameter, click.Option) or parameter.hidden:
            continue
        if parameter.name == "help":
            continue
        assert any(opt in section for opt in parameter.opts), (
            f"`chartbook {' '.join(words)}` has {parameter.opts[0]}, which `## chartbook {words[0]}` does not mention"
        )


def test_the_page_documents_no_command_that_is_gone(page):
    on_page = set(re.findall(r"^## chartbook ([a-z][a-z-]*)", page, re.M))
    known = {words[0] for words, _ in COMMANDS}
    assert on_page <= known, f"on the page and not in the CLI: {sorted(on_page - known)}"


def _section(page: str, top: str) -> str:
    """The text of `## chartbook <top>` up to the next `## ` heading.

    A section that says it "takes the arguments of" another command, as
    `build` does of `docs`, is read with that command's section.
    """
    match = re.search(rf"^## chartbook {re.escape(top)}\b.*?(?=^## |\Z)", page, re.M | re.S)
    text = match.group(0) if match else ""
    for other in re.findall(r"takes the arguments of \{ref\}`chartbook ([a-z-]+)", text):
        if other != top:
            text += _section(page, other)
    return text
