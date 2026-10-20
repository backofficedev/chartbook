"""The files that teach an assistant ChartBook name every command, and stay in step.

Three sets of files say what ChartBook can do to a language model: the
Claude Code skill (``src/chartbook/skills/``, installed by ``chartbook
install claude-skill``), and the llms files (``llm/llms.txt`` and
``llm/llms-full.txt``, copied into the published site; ``llms.txt`` at the
repository's root is a copy of the first). They are written by hand, and
this release's ``keep = true`` and ``chartbook restore`` reached neither
until these tests: a command added to the CLI without a line in each fails here.
"""

import importlib.util
import re
from pathlib import Path

import click
import pytest

from chartbook.cli import main

ROOT = Path(__file__).parent.parent
SKILL = [ROOT / "src" / "chartbook" / "skills" / name for name in ("SKILL.md", "catalog_system.md", "manifest_files.md")]
LLMS = [ROOT / "llm" / "llms.txt", ROOT / "llm" / "llms-full.txt"]


def _commands(group, path=()):
    """Every command and subcommand a user can run, as its words after ``chartbook``; hidden ones left out."""
    for name, command in sorted(group.commands.items()):
        if command.hidden:
            continue
        words = (*path, name)
        yield words
        if isinstance(command, click.Group):
            yield from _commands(command, words)


COMMANDS = list(_commands(main))


def _names(text: str, words: tuple) -> bool:
    return re.search(rf"(?<![\w-])chartbook {re.escape(' '.join(words))}(?![\w-])", text) is not None


@pytest.mark.parametrize("words", COMMANDS, ids=["-".join(w) for w in COMMANDS])
def test_the_skill_names_every_command(words):
    text = "\n".join(path.read_text(encoding="utf-8") for path in SKILL)
    assert _names(text, words), f"`chartbook {' '.join(words)}` is in the CLI and in none of src/chartbook/skills/*.md"


@pytest.mark.parametrize("words", COMMANDS, ids=["-".join(w) for w in COMMANDS])
def test_the_llms_files_name_every_command(words):
    text = "\n".join(path.read_text(encoding="utf-8") for path in LLMS)
    assert _names(text, words), f"`chartbook {' '.join(words)}` is in the CLI and in neither llm/llms.txt nor llm/llms-full.txt"


def test_the_root_llms_file_is_the_one_in_llm():
    """The root copy is for an agent reading the repository, whose links (`docs_src/...`) are from the root."""
    assert (ROOT / "llms.txt").read_text(encoding="utf-8") == (ROOT / "llm" / "llms.txt").read_text(encoding="utf-8"), (
        "llms.txt differs from llm/llms.txt. Edit the one in llm/, then copy it to the root."
    )


def _dodo():
    spec = importlib.util.spec_from_file_location("chartbook_dodo", ROOT / "dodo.py")
    dodo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dodo)
    return dodo


@pytest.mark.parametrize("name", ["llms.txt", "llms-full.txt"])
def test_the_sites_llms_files_link_its_pages(tmp_path, name):
    """Found while checking the llms files: the site's copy linked `docs_src/...md`, which is not in the site."""
    out = tmp_path / name
    _dodo().copy_llms_file(ROOT / "llm" / name, out)()
    text = out.read_text(encoding="utf-8")
    assert "](docs_src/" not in text  # a link; a manifest example may still name a docs_src path
    for link in re.findall(r"\]\(([^)#:]+\.html)(?:#[^)]*)?\)", text):
        source = ROOT / "docs_src" / link.removesuffix(".html")
        assert source.with_suffix(".md").is_file() or source.with_suffix(".ipynb").is_file(), link


def test_a_link_to_a_section_keeps_its_anchor(tmp_path):
    source = tmp_path / "in.txt"
    source.write_text("[a](docs_src/guide/plotting.md#backends) [b](docs_src/guide/gallery.ipynb) [c](https://x.org/a.md)\n")
    _dodo().copy_llms_file(source, tmp_path / "out.txt")()
    assert (tmp_path / "out.txt").read_text() == "[a](guide/plotting.html#backends) [b](guide/gallery.html) [c](https://x.org/a.md)\n"
