"""The lines ``chartbook snapshot`` and ``chartbook run --snapshot`` end with when a snapshot is made, for the tests that look for them.

Since the store decides how it keeps a snapshot
(``docs_src/design/snapshots-and-increments.md``, "What you see"), the
line says so, in one of three forms, with a count of files and a size that
are not the same from one test to the next::

    Snapshot made: 5 files, 23.0 MB.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

    Snapshot made, kept as an increment: 2 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

    Snapshot made: 5 files, 23.0 MB. The increments since the last complete one had added up to its size.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

``tests/test_snapshot_decides.py`` holds each of them to the byte. What is
here tells a test whose subject is something else that a snapshot was said
to be made **in the form that test expects**: a caller names the form, the
numbers are taken by pattern, and every other character is exact. A first
snapshot of a pipeline is the complete form; one said to be an increment
would not pass for it. And the counts are ones that can be: one file is
"1 file" and never "1 files", a snapshot has at least one file, and the
files in an increment's own folder are fewer than all of its files.
"""

import re
from typing import Optional

#: The line that follows, whichever way the snapshot is kept
PIN_UPDATE = "A pipeline that depends on this one gets it with `chartbook pin --update`."

#: How many files a snapshot's record lists: at least one, and "1 file" for one
_FILES = r"(?P<files>1 file|(?:[2-9]|[1-9]\d+) files)"
#: How many of them an increment's own folder holds: fewer, which :func:`_is` sees to
_OWN = r"(?P<own>0|[1-9]\d*)"
_SIZE = r"(?:\d+ bytes|\d+\.\d (?:KB|MB|GB))"
_WHEN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"

#: A complete snapshot: a pipeline's first, one where every file differs, one asked for with ``--complete``
COMPLETE = "complete"
#: One kept as an increment on a complete snapshot
INCREMENT = "increment"
#: A complete one that the increments since the last complete one, with this one, added up to
ADDED_UP = "added up"

#: What is said of how the snapshot is kept, for each form: after "Snapshot made", and after the sentence's full stop
_SAID = {
    COMPLETE: (rf": {_FILES}, {_SIZE}", r""),
    INCREMENT: (rf", kept as an increment: {_OWN} of {_FILES}, {_SIZE}", rf" The rest is in the snapshot made {_WHEN}\."),
    ADDED_UP: (rf": {_FILES}, {_SIZE}", r" The increments since the last complete one had added up to its size\."),
}

#: The line of each form
MADE = {form: re.compile(rf"Snapshot made{how}\.{after}") for form, (how, after) in _SAID.items()}

#: What `chartbook run --upstream` says of a pipeline it snapshotted so that the run could pin it, in each form: the same first words, and no line of `pin --update`
MADE_FOR_THIS_RUN = {
    form: re.compile(rf"Snapshot made{how}, for what depends on it in this run to pin\.{after}") for form, (how, after) in _SAID.items()
}


def _is(pattern: "re.Pattern", line: str) -> bool:
    """Whether a line is of one form, with counts that can be: an increment's own files are fewer than all of its files."""
    found = pattern.fullmatch(line)
    if found is None:
        return False
    own = found.groupdict().get("own")
    return own is None or int(own) < int(found["files"].split()[0])


def made_at(lines: list, form: str) -> Optional[int]:
    """Where a command's lines say that a snapshot was made and kept in *form* (:data:`COMPLETE`, :data:`INCREMENT` or :data:`ADDED_UP`): the index of the line that says so, which the line of ``pin --update`` follows; None if they do not say so."""
    for number, line in enumerate(lines[:-1]):
        if _is(MADE[form], line) and lines[number + 1] == PIN_UPDATE:
            return number
    return None


def said_made(output: str, form: str) -> bool:
    """Whether a command's output says that a snapshot was made and kept in *form*, in the two lines it ends such a snapshot with."""
    return made_at(output.splitlines(), form) is not None


def said_made_for_this_run(output: str, form: str) -> bool:
    """Whether a command's output says, in one line, that a snapshot was made in *form* for what depends on it in this run to pin."""
    return any(_is(MADE_FOR_THIS_RUN[form], line) for line in output.splitlines())
