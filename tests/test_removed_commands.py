"""Nothing a person or an assistant learns ChartBook from names a command that is gone.

0.6.0 took away ``chartbook check`` (now ``chartbook run --check``),
``chartbook update`` (now ``chartbook pin --update``), ``chartbook pin
--frozen`` (now ``chartbook pin --check``) and ``--skip-outputs``, as an
earlier release took away ``chartbook build``. Each was swept out of some
sixty files, and each sweep missed the same kinds of place: the name split
across two lines of a docstring, the bare name in a list (``pin``,
``update`` and ``add``), and the file nobody thought of (a diagram's label,
a skill's last clause). This reads them all, with the lines joined.

History is left as it was: the changelog, and the design pages, which say
what was decided when. So is a sentence that says the command is gone.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

#: What is gone, as it would be written, and what it is now
GONE = {
    r"chartbook update\b": "chartbook pin --update",
    r"chartbook check\b": "chartbook run --check",
    r"chartbook build\b": "chartbook run, or chartbook docs build",
    r"pin --frozen\b": "chartbook pin --check, or chartbook run --frozen",
    r"--skip-outputs\b": "nothing: chartbook run --check is so always",
}

#: A sentence may name one to say what became of it
SAYS_SO = ("is gone", "are gone", "gone too", "which is gone", "until 0.6.0", "through 0.5.1", "now says where it went", "used to mean")

#: And the code that finds a build file still calling a removed command, and says so, names it; so does the roadmap, of what was done when
FINDS_IT = {
    ("src/chartbook/run.py", r"chartbook build\b"),
    ("src/chartbook/check.py", r"chartbook build\b"),
    ("docs_src/roadmap.md", r"chartbook build\b"),
}


def _tracked(*folders: str) -> list:
    listed = subprocess.run(["git", "ls-files", *folders], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    return [ROOT / name for name in listed]


def _taught() -> list:
    """Every tracked file that says how ChartBook is used, but the history."""
    found = []
    for path in _tracked("src", "docs_src", "llm", "llms.txt", "README.md", "template", "examples", ".claude/skills", "dodo.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("docs_src/design/") or relative == "docs_src/changelog.md":
            continue
        if path.suffix in (".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json", ".svg", ".tape", ".j2", ".cfg", ".sh"):
            found.append(path)
    return found


TAUGHT = _taught()


def _mentions(text: str, pattern: str) -> list:
    """Each place a text names what the pattern matches, with the words around it; lines are joined first, so a name split across two is one."""
    joined = re.sub(r"\s+", " ", text)
    found = []
    for match in re.finditer(pattern, joined):
        around = joined[max(0, match.start() - 200):match.end() + 200].lower()
        if not any(phrase in around for phrase in SAYS_SO):
            found.append(joined[max(0, match.start() - 70):match.end() + 50])
    return found


@pytest.mark.parametrize("pattern", sorted(GONE))
def test_no_file_names_a_command_that_is_gone(pattern):
    found = {}
    for path in TAUGHT:
        if (path.relative_to(ROOT).as_posix(), pattern) in FINDS_IT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        mentions = _mentions(text, pattern)
        if mentions:
            found[path.relative_to(ROOT).as_posix()] = mentions[:3]
    assert not found, f"these name what is now `{GONE[pattern]}`: {found}"


def test_no_page_or_skill_names_update_by_itself():
    """`pin`, `update` and `add`: the bare name in a list of commands, which the sweep of `chartbook update` cannot see."""
    found = {}
    for path in TAUGHT:
        if path.suffix not in (".md", ".txt"):
            continue
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        mentions = [text[max(0, m.start() - 60):m.end() + 40] for m in re.finditer(r"(?<![\w-])`update`", text)]
        if mentions:
            found[path.relative_to(ROOT).as_posix()] = mentions[:3]
    assert not found, f"these name `update` as a command, which is `pin --update`: {found}"


def test_the_test_can_see_a_name_split_across_lines():
    assert _mentions("as ``chartbook\n        update`` does", r"chartbook update\b")
    assert not _mentions("`chartbook update` is gone: `chartbook pin --update`.", r"chartbook update\b")
    assert not _mentions("chartbook pin --update moves pins", r"chartbook update\b")
    assert not _mentions("chartbook docs build renders, chartbook run --check checks", "|".join(GONE))
