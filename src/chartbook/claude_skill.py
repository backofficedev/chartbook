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

# Nested (under `metadata:`), with its value on the same line
_VERSION_LINE = re.compile(r"^[ \t]+chartbook-version:[ \t]*[\"']?([^\"'\s#]+)", re.M)


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
    subfolder. So the walk goes up to the top of the git repository *start*
    is in, and never reaches the home folder, whose ``.claude`` is the
    user's own; nor is the user-level copy, wherever it is, a project's. A
    folder that cannot be read is passed by.

    :param start: Where to look from; the working directory by default.
    :returns: The folder, or None if there is none.
    """
    try:
        here = Path(start if start is not None else Path.cwd()).resolve()
        user = user_dir().resolve()
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return None
    for folder in (here, *here.parents):
        if folder == home:
            return None
        candidate = folder / ".claude" / "skills" / SKILL_NAME
        try:
            if (candidate / ENTRY).is_file() and candidate.resolve() != user:
                return candidate
            top = (folder / ".git").exists()
        except OSError:
            continue  # a folder this user may not open
        if top:
            return None
    return None


def front_matter_version(directory: Path) -> Optional[str]:
    """The ``chartbook-version`` a copy's ``SKILL.md`` names in its front matter; None if it names none.

    Only the top of the file is read, as bytes, so a large or odd file
    costs nothing; a byte-order mark and Windows line endings are allowed.
    """
    try:
        with open(Path(directory) / ENTRY, "rb") as f:
            text = f.read(8192).decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    found = _VERSION_LINE.search(text[3:end]) if end != -1 else None
    return found.group(1) if found else None


def _stamp_version(directory: Path) -> Optional[str]:
    try:
        return (Path(directory) / OLD_STAMP).read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def version_of(directory: Path) -> Optional[str]:
    """Which ChartBook an installed copy was written for, as far as it says.

    Its ``SKILL.md``'s front matter (:func:`front_matter_version`); for a
    copy installed before the version was there, the stamp file beside it
    (:data:`OLD_STAMP`). The bundled skill always names its version in its
    front matter, so a copy that names it only in a stamp is never the
    current one, whatever the stamp says (:func:`relation`).

    :returns: The version, or None if the copy names none.
    """
    return front_matter_version(directory) or _stamp_version(directory)


def _parsed(version: Optional[str]):
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version) if version else None
    except InvalidVersion:
        return None


def relation(directory: Path) -> str:
    """How a copy stands to this ChartBook: ``"current"``, ``"newer"`` or ``"older"``.

    ``"newer"`` is a copy whose front matter names a later version than this
    package's: written for a newer ChartBook installed elsewhere (each
    pipeline may have its own environment), and nothing to replace from
    here. Anything else that is not this version (a stamp only, no version,
    one that is not a version) is ``"older"``.
    """
    named = front_matter_version(directory)
    if named == __version__:
        return "current"
    mine, theirs = _parsed(__version__), _parsed(named)
    if mine is not None and theirs is not None and theirs > mine:
        return "newer"
    return "older"


def _shown_version(directory: Path) -> Optional[str]:
    """A copy's version as a person reads it: a stamp naming this version is an earlier build of it."""
    named = front_matter_version(directory)
    if named:
        return named
    stamp = _stamp_version(directory)
    return f"{stamp} (an earlier build)" if stamp == __version__ else stamp


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
    """The installed copies of the skill written for an older ChartBook than this one: the project's, then the user's.

    A copy for a newer ChartBook is not said: installing this one's would
    undo the newer one, and the two environments would take turns.

    :param start: Where the project's copy is looked for from (:func:`project_dir`).
    """
    found = []
    for where, directory in (("project", project_dir(start)), ("user", user_dir())):
        try:
            if directory is None or not (directory / ENTRY).is_file():
                continue
        except OSError:
            continue
        if relation(directory) == "older":
            found.append(Copy(where, directory, _shown_version(directory)))
    return found


def shown(path: Path) -> str:
    """A path as a person reads it: under the home folder, with ``~``."""
    try:
        relative = Path(path).relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)
    return "~" if relative == "." else f"~/{relative}"


def notice(copy: Copy) -> str:
    """One sentence on a copy written for an older ChartBook, and the command that installs this one's."""
    written = f"is for ChartBook {copy.version}" if copy.version else "names no ChartBook version (it is from before 0.2.0)"
    if copy.where == "project":
        top = copy.directory.parent.parent.parent
        return (
            f"this project's Claude Code skill, {shown(copy.directory)}, {written}, and this is ChartBook "
            f"{__version__}: `chartbook install claude-skill --project` in {shown(top)} installs this version's."
        )
    return (
        f"your Claude Code skill, {shown(copy.directory)}, {written}, and this is ChartBook {__version__}: "
        f"`chartbook install claude-skill` installs this version's."
    )
