"""A project's ``AGENTS.md``: the section ChartBook writes in it, for coding agents that read that file.

``chartbook install agents`` sets a project up for coding agents
(``docs_src/design/one-command.md``): it installs the Claude Code skill for
the user, as ``chartbook install claude-skill`` does, and writes a
ChartBook section into the project's ``AGENTS.md``, which other agents
read. The section stands between two marker lines. The command replaces
what is between them when ChartBook moves on, and leaves the rest of the
file alone: a project's own notes for its agents are the project's.

The section's text is one file of the package, ``agents_section.md``,
written for the ChartBook it ships with; the opening marker names that
version, as the skill's ``SKILL.md`` names its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chartbook.__about__ import __version__

#: The file agents read, in a project's folder.
FILE = "AGENTS.md"

#: What the section's two marker lines start with.
START = "<!-- chartbook:start"
END = "<!-- chartbook:end"

_VERSION = re.compile(r"\bversion=([^\s;>]+)")


class Malformed(ValueError):
    """Raised when a file's marker lines do not hold one section: a start with no end, an end with no start, or more than one of either."""


def body() -> str:
    """The section's text as this ChartBook carries it, with no marker line, ending in a newline."""
    import importlib.resources

    text = (importlib.resources.files("chartbook") / "agents_section.md").read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").strip("\n") + "\n"


def section(version: str = __version__) -> str:
    """The section as it is written: its opening marker, which names the version and what writes it, its text, and its closing marker."""
    return (
        f"{START} version={version}; written by `chartbook install agents`, which replaces everything down to "
        f"chartbook:end. Notes of your own go outside these two lines. -->\n"
        f"{body()}"
        f"{END} -->\n"
    )


@dataclass(frozen=True)
class Found:
    """What a file has of the section.

    Attributes:
        before: The file's text above the section; all of it where it has none.
        own: The section as the file has it, marker lines and all; empty where it has none.
        after: The file's text below the section.
        version: The ChartBook version its opening marker names, if it names one.
        newline: How the file ends its lines: ``\\r\\n`` where it uses that, else ``\\n``.
    """

    before: str
    own: str = ""
    after: str = ""
    version: Optional[str] = None
    newline: str = "\n"


def read(text: str) -> Found:
    """Find the section in a file's text.

    :raises Malformed: If its marker lines do not hold exactly one section.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    starts = [number for number, line in enumerate(lines) if line.lstrip().startswith(START)]
    ends = [number for number, line in enumerate(lines) if line.lstrip().startswith(END)]
    if not starts and not ends:
        return Found(before=text, newline=newline)
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        if len(starts) == 1 and not ends:
            raise Malformed(f"its `chartbook:start` line (line {starts[0] + 1}) has no `chartbook:end` line after it")
        if len(ends) == 1 and not starts:
            raise Malformed(f"its `chartbook:end` line (line {ends[0] + 1}) has no `chartbook:start` line before it")
        raise Malformed(
            f"it has {len(starts)} `chartbook:start` line(s) and {len(ends)} `chartbook:end` line(s), and one section has one of each, in that order"
        )
    start, end = starts[0], ends[0]
    named = _VERSION.search(lines[start])
    return Found(
        before="".join(lines[:start]), own="".join(lines[start : end + 1]), after="".join(lines[end + 1 :]),
        version=named.group(1) if named else None, newline=newline,
    )


def written(found: Found, version: str = __version__) -> str:
    """A file's text with this version's section in it: in the place of the one it has, or after everything else."""
    ours = section(version).replace("\n", found.newline)
    if found.own:
        return found.before + ours + found.after
    before = found.before
    if before and not before.endswith(("\n", "\r")):
        before += found.newline
    if before.strip():
        before = before.rstrip("\r\n") + found.newline * 2  # one blank line between the project's own text and the section
    else:
        before = ""
    return before + ours


def same(found: Found, version: str = __version__) -> bool:
    """Whether a file's section is this version's, as written, but for how its lines end."""
    return found.own.replace("\r\n", "\n").rstrip("\n") == section(version).rstrip("\n")


def changed_by_hand(found: Found) -> bool:
    """Whether a file's section names this version and is not this version's text: somebody wrote in it.

    One that names another version, or none, is another ChartBook's
    section and is replaced; what somebody wrote in that cannot be told
    from what that version wrote.
    """
    return bool(found.own) and found.version == __version__ and not same(found)


def project_folder(start: Optional[Path | str] = None) -> Optional[Path]:
    """The project a folder is in: the folder itself or the nearest above it that holds a ``chartbook.toml``, no further up than its git repository's top, and never the home folder.

    :param start: Where to look from; the working directory by default.
    """
    from chartbook.resolve import MANIFEST_NAME

    try:
        here = Path(start if start is not None else Path.cwd()).resolve()
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return None
    for folder in (here, *here.parents):
        if folder == home:
            return None
        try:
            if (folder / MANIFEST_NAME).is_file():
                return folder
            if (folder / ".git").exists():
                return None
        except OSError:
            continue
    return None


def stale(start: Optional[Path | str] = None) -> Optional[tuple[Path, str]]:
    """A project's ``AGENTS.md`` whose ChartBook section was written by an older ChartBook than this one: the file and that version; None otherwise.

    As for the skill (:func:`chartbook.claude_skill.stale`): a section for
    a newer ChartBook is not said, and one that names no version, or a
    file that cannot be read, is passed by.

    :param start: Where the project is looked for from (:func:`project_folder`).
    """
    from chartbook.claude_skill import _parsed

    project = project_folder(start)
    if project is None:
        return None
    try:
        found = read((project / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    theirs, ours = _parsed(found.version), _parsed(__version__)
    if not found.own or theirs is None or ours is None or not theirs < ours:
        return None
    return project / FILE, found.version


def notice(file: Path, version: str) -> str:
    """One sentence on a section written by an older ChartBook, and the command that writes this one's."""
    from chartbook.claude_skill import shown

    return (
        f"the ChartBook section of {shown(file)} is for ChartBook {version}, and this is ChartBook {__version__}: "
        f"`chartbook install agents` in {shown(file.parent)} writes this version's."
    )
