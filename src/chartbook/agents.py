"""A project's ``AGENTS.md``: the section ChartBook writes in it, for coding agents that read that file.

``chartbook install agents`` sets a project up for coding agents
(``docs_src/design/one-command.md``): it installs the Claude Code skill for
the user, as ``chartbook install claude-skill`` does, and writes a
ChartBook section into the project's ``AGENTS.md``, which other agents
read. The section stands between two marker lines. The command replaces
what is between them when ChartBook moves on, and leaves the rest of the
file alone: a project's own notes for its agents are the project's.

The section's text is one file of the package, ``agents_section.md``,
written for the ChartBook it ships with. The opening marker names that
version, as the skill's ``SKILL.md`` names its own, and carries a hash of
the text between the markers as it was written. So a section somebody has
written in is told from one that is as ChartBook left it, whatever its
version, and nothing a person wrote is replaced unasked.

**What a marker is.** A whole line, from its first column, that is the
comment and nothing else, and not inside a fenced code block. A line that
only mentions one (in a sentence, indented as code, in an example) is the
project's own text. A marker line with other text after it is refused,
since replacing the section would take that text with it.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from chartbook.__about__ import __version__

#: The file agents read, in a project's folder.
FILE = "AGENTS.md"

#: What the section's two marker lines start with.
START = "<!-- chartbook:start"
END = "<!-- chartbook:end"

_START_LINE = re.compile(r"<!-- chartbook:start(?P<said>[^>]*)-->[ \t]*")
_END_LINE = re.compile(r"<!-- chartbook:end[^>]*-->[ \t]*")
_VERSION = re.compile(r"(?<![\w.-])version=([^\s;>]+)")
_HASH = re.compile(r"(?<![\w.-])text=([0-9a-f]{12})(?![0-9a-f])")
_FENCE = re.compile(r"[ ]{0,3}(```|~~~)")
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r|\Z)")


class Malformed(ValueError):
    """Raised when a file's marker lines do not hold one section: a start with no end, an end with no start, more than one of either, or a marker line with other text on it."""


def body() -> str:
    """The section's text as this ChartBook carries it, with no marker line, ending in a newline."""
    import importlib.resources

    text = (importlib.resources.files("chartbook") / "agents_section.md").read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").strip("\n") + "\n"


def _hash(text: str) -> str:
    """What the opening marker says of the text between the markers: the start of a hash of it, however its lines end."""
    plain = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()[:12]


def section(version: str = __version__) -> str:
    """The section as it is written: its opening marker (the version, a hash of the text, and what writes it), its text, and its closing marker."""
    text = body()
    return (
        f"{START} version={version} text={_hash(text)}; written by `chartbook install agents`, which replaces "
        f"everything down to chartbook:end. Notes of your own go outside these two lines. -->\n"
        f"{text}"
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
        hashed: Whether its opening marker carries a hash of the text, as
            one that ``chartbook install agents`` wrote does.
        untouched: Whether the text between its markers is as that hash
            says it was written: nobody has written in it.
        newline: How most of the file's lines end; ``\\n`` for a file with none.
        bom: Whether the file begins with a byte-order mark, which is kept.
    """

    before: str
    own: str = ""
    after: str = ""
    version: Optional[str] = None
    hashed: bool = False
    untouched: bool = False
    newline: str = "\n"
    bom: bool = False


def _newline(text: str) -> str:
    """How most of a text's lines end."""
    windows = text.count("\r\n")
    counts = {"\r\n": windows, "\n": text.count("\n") - windows, "\r": text.count("\r") - windows}
    most = max(counts, key=lambda ending: counts[ending])
    return most if counts[most] else "\n"


def read(text: str) -> Found:
    """Find the section in a file's text.

    :raises Malformed: If its marker lines do not hold exactly one section.
    """
    bom = text.startswith("\ufeff")
    text = text[1:] if bom else text
    newline = _newline(text)
    lines = [line for line in _LINE.findall(text) if line]
    starts, ends, fenced = [], [], ""
    for number, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        fence = _FENCE.match(bare)
        if fence and (not fenced or fence.group(1) == fenced):
            fenced = "" if fenced else fence.group(1)
            continue
        if fenced:
            continue  # an example of the markers is the project's own text
        for marker, whole, found in ((START, _START_LINE, starts), (END, _END_LINE, ends)):
            if bare.startswith(marker):
                if not whole.fullmatch(bare):
                    raise Malformed(
                        f"its `{marker[5:]}` line (line {number + 1}) has other text on it, which replacing the section would take "
                        f"with it: a marker line holds the marker and nothing else"
                    )
                found.append(number)
    if not starts and not ends:
        return Found(before=text, newline=newline, bom=bom)

    def at(numbers: list) -> str:
        said = [str(number + 1) for number in numbers]
        return f"line {said[0]}" if len(said) == 1 else f"lines {', '.join(said[:-1])} and {said[-1]}"

    if len(starts) == 1 and not ends:
        raise Malformed(f"its `chartbook:start` line ({at(starts)}) has no `chartbook:end` line after it")
    if len(ends) == 1 and not starts:
        raise Malformed(f"its `chartbook:end` line ({at(ends)}) has no `chartbook:start` line before it")
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise Malformed(
            f"it has `chartbook:start` on {at(starts) if starts else 'no line'} and `chartbook:end` on "
            f"{at(ends) if ends else 'no line'}, and one section is one of each, in that order"
        )
    start, end = starts[0], ends[0]
    said = _START_LINE.fullmatch(lines[start].rstrip("\r\n")).group("said")
    named, hashed = _VERSION.search(said), _HASH.search(said)
    return Found(
        before="".join(lines[:start]), own="".join(lines[start : end + 1]), after="".join(lines[end + 1 :]),
        version=named.group(1) if named else None, hashed=hashed is not None,
        untouched=hashed is not None and _hash("".join(lines[start + 1 : end])) == hashed.group(1),
        newline=newline, bom=bom,
    )


def written(found: Found, version: str = __version__) -> str:
    """A file's text with this version's section in it: in the place of the one it has, or after everything else, which is kept byte for byte."""
    ours = section(version).replace("\n", found.newline)
    mark = "\ufeff" if found.bom else ""
    if found.own:
        return mark + found.before + ours + found.after
    before = found.before
    if before and not before.endswith(("\n", "\r")):
        before += found.newline
    if before.strip() and not before.endswith((found.newline * 2, "\n\n", "\r\r")):
        before += found.newline  # one blank line between the project's own text and the section
    return mark + before + ours


def same(found: Found, version: str = __version__) -> bool:
    """Whether a file's section is this version's, as written, but for how its lines end."""
    plain = found.own.replace("\r\n", "\n").replace("\r", "\n")
    return plain.rstrip("\n") == section(version).rstrip("\n")


def standing(found: Found) -> str:
    """How a file's section stands to this ChartBook.

    ``"none"``: it has none. ``"current"``: this version's, as written.
    ``"older"`` and ``"newer"``: another version's, as that version wrote
    it (its marker's hash is of its text); ``"older"`` too for this
    version's own of another build. ``"by hand"``: somebody has written
    in it, or it was not written by ``chartbook install agents`` at all
    (no hash, or a version that is none): whatever its version, it is not
    replaced unasked.
    """
    from chartbook.claude_skill import _parsed

    if not found.own:
        return "none"
    if same(found):
        return "current"
    theirs, ours = _parsed(found.version), _parsed(__version__)
    if not found.untouched or theirs is None or ours is None:
        return "by hand"
    return "newer" if theirs > ours else "older"


def write(file: Path, text: str) -> None:
    """Write a file's new text so that it is whole or as it was: to a file beside it, moved over it.

    A file opened for writing is empty until its text is in it, and a disk
    that fills then leaves a project's own notes cut short. The file a
    link points at is the one replaced, so the link stays; its mode is
    kept.
    """
    import shutil

    from chartbook.replacing import replace_when_let

    target = Path(os.path.realpath(file))
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8", newline="") as f:  # the text has its own line endings
            f.write(text)
        if target.exists():
            shutil.copymode(target, temporary)
        replace_when_let(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def project_folder(start: Optional[Path | str] = None) -> Optional[Path]:
    """The project a folder is in: the folder itself, or the nearest above it that holds a ``chartbook.toml``.

    Above it only within its git repository, up to that repository's top:
    a folder in no repository is a project only if it holds the manifest
    itself, so that a stray one somewhere above is never written beside.
    Never the home folder.

    :param start: Where to look from; the working directory by default.
    """
    from chartbook.resolve import MANIFEST_NAME

    try:
        here = Path(start if start is not None else Path.cwd()).resolve()
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return None
    within = [here]
    for folder in (here, *here.parents):
        try:
            if (folder / ".git").exists():
                within = [here, *[above for above in here.parents if above == folder or folder in above.parents]]
                break
        except OSError:
            break
    for folder in within:
        if folder == home:
            return None
        try:
            if (folder / MANIFEST_NAME).is_file():
                return folder
        except OSError:
            continue
    return None


def stale(start: Optional[Path | str] = None) -> Optional[tuple[Path, str]]:
    """A project's ``AGENTS.md`` whose ChartBook section is for an older ChartBook than this one: the file and that version; None otherwise.

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
        found = read((project / FILE).read_bytes().decode("utf-8"))
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
