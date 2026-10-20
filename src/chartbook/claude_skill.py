"""The Claude Code skill ChartBook ships: where it is installed, and which ChartBook it was written for.

The skill's entry point, ``SKILL.md``, names the ChartBook version it
describes in its front matter::

    metadata:
      chartbook-version: "0.2.0"

A release keeps that equal to the package's version (a test does). An
installed copy is then compared with the ChartBook that is running:
``chartbook install claude-skill`` says what it replaced, ``chartbook check``
warns, and any other command, run by a person at a terminal, says so in one
line (:func:`chartbook.cli._say_if_the_skill_is_stale`). Nothing here ever
stops a command.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chartbook.__about__ import __version__

#: The skill's folder name, under ``.claude/skills/``.
SKILL_NAME = "chartbook"

#: The skill's entry point, whose front matter names its version.
ENTRY = "SKILL.md"

#: Where installs before 0.2.0 recorded the installing version, beside the
#: files. Read, so that such a copy says which version it is; removed when
#: the skill is installed again.
OLD_STAMP = ".chartbook-skill-version"

_VERSION_LINE = re.compile(r"^\s*chartbook-version:\s*[\"']?([^\"'\s#]+)", re.M)


def bundled_dir() -> Path:
    """The skill as this ChartBook carries it: ``chartbook/skills/`` in the package."""
    import importlib.resources

    return Path(str(importlib.resources.files("chartbook"))) / "skills"


def bundled_files() -> list[Path]:
    """The skill's files as this ChartBook carries them, sorted."""
    folder = bundled_dir()
    return sorted(p for p in (folder.iterdir() if folder.is_dir() else []) if p.is_file())


def user_dir() -> Path:
    """Where the user-level skill is: ``$CLAUDE_CONFIG_DIR/skills/chartbook``, or ``~/.claude/skills/chartbook``."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    return base / "skills" / SKILL_NAME


def project_dir(start: Optional[Path | str] = None) -> Optional[Path]:
    """The project's copy of the skill: ``.claude/skills/chartbook`` in *start* or the nearest folder above it that has one.

    Claude Code reads a project's ``.claude`` at the folder it was started
    in, usually the repository's top, which may be above a pipeline in a
    subfolder. The user-level copy, which a walk up from the home folder
    would meet, is not a project's.

    :param start: Where to look from; the working directory by default.
    :returns: The folder, or None if there is none.
    """
    try:
        here = Path(start if start is not None else Path.cwd()).resolve()
        user = user_dir().resolve()
    except OSError:
        return None
    for folder in (here, *here.parents):
        candidate = folder / ".claude" / "skills" / SKILL_NAME
        if (candidate / ENTRY).is_file() and candidate.resolve() != user:
            return candidate
    return None


def version_of(directory: Path) -> Optional[str]:
    """Which ChartBook an installed copy was written for: its ``SKILL.md``'s ``chartbook-version``.

    A copy installed before the version was in ``SKILL.md`` says it in the
    stamp file beside it (:data:`OLD_STAMP`).

    :returns: The version, or None if the copy names none.
    """
    try:
        text = (Path(directory) / ENTRY).read_text(encoding="utf-8")[:8192]  # the front matter is at the top
    except (OSError, UnicodeDecodeError):
        text = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            found = _VERSION_LINE.search(text[3:end])
            if found:
                return found.group(1)
    try:
        return (Path(directory) / OLD_STAMP).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class Copy:
    """An installed copy of the skill.

    Attributes:
        where: ``"user"`` or ``"project"``.
        directory: Its folder.
        version: The ChartBook it was written for, or None if it names none.
    """

    where: str
    directory: Path
    version: Optional[str]


def stale(start: Optional[Path | str] = None) -> list[Copy]:
    """The installed copies of the skill written for another ChartBook than this one: the project's, then the user's.

    :param start: Where the project's copy is looked for from (:func:`project_dir`).
    """
    found = []
    for where, directory in (("project", project_dir(start)), ("user", user_dir())):
        if directory is None or not (directory / ENTRY).is_file():
            continue
        version = version_of(directory)
        if version != __version__:
            found.append(Copy(where, directory, version))
    return found


def _shown(path: Path) -> str:
    """A path as a person reads it: under the home folder, with ``~``."""
    try:
        return "~/" + Path(path).relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def notice(copy: Copy) -> str:
    """One sentence on a copy written for another ChartBook, and the command that installs this one's."""
    written = f"is for ChartBook {copy.version}" if copy.version else "names no ChartBook version (it is from before 0.2.0)"
    if copy.where == "project":
        top = copy.directory.parent.parent.parent
        return (
            f"this project's Claude Code skill, {_shown(copy.directory)}, {written}, and this is ChartBook "
            f"{__version__}: `chartbook install claude-skill --project` in {_shown(top)} installs this version's."
        )
    return (
        f"your Claude Code skill, {_shown(copy.directory)}, {written}, and this is ChartBook {__version__}: "
        f"`chartbook install claude-skill` installs this version's."
    )
