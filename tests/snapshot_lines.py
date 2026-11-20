"""The lines ``chartbook snapshot`` and ``chartbook run --snapshot`` end with when a snapshot is made, for the tests that look for them.

Since the store decides how it keeps a snapshot
(``docs_src/design/snapshots-and-increments.md``, "What you see"), the
line says so, with a count of files and a size that are not the same from
one test to the next::

    Snapshot made: 5 files, 23.0 MB.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

    Snapshot made, kept as an increment: 2 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

    Snapshot made: 5 files, 23.0 MB. The increments since the last complete one had added up to its size.
    A pipeline that depends on this one gets it with `chartbook pin --update`.

``tests/test_snapshot_decides.py`` holds each of them to the byte. What is
here tells a test whose subject is something else that a snapshot was said
to be made, in one of those forms and no other.
"""

import re
from typing import Optional

#: The line that follows, whichever way the snapshot is kept
PIN_UPDATE = "A pipeline that depends on this one gets it with `chartbook pin --update`."

_FILES = r"(?:1 file|\d+ files)"
_SIZE = r"(?:\d+ bytes|\d+\.\d (?:KB|MB|GB))"
#: A complete one, with what is said of one that the increments led to; and one kept as an increment
MADE = re.compile(
    rf"Snapshot made: {_FILES}, {_SIZE}\.(?: The increments since the last complete one had added up to its size\.)?"
    rf"|Snapshot made, kept as an increment: \d+ of {_FILES}, {_SIZE}\. "
    rf"The rest is in the snapshot made \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} UTC\."
)


#: What `chartbook run --upstream` says of a pipeline it snapshotted so that the run could pin it: the same first words, and no line of `pin --update`
MADE_FOR_THIS_RUN = re.compile(
    rf"Snapshot made(?:: {_FILES}, {_SIZE}|, kept as an increment: \d+ of {_FILES}, {_SIZE}), for what depends on it in this run to pin\."
    rf"(?: The rest is in the snapshot made \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}} UTC\."
    rf"| The increments since the last complete one had added up to its size\.)?"
)


def made_at(lines: list) -> Optional[int]:
    """Where a command's lines say that a snapshot was made: the index of the line that says how it is kept, which the line of ``pin --update`` follows; None if they do not say so."""
    for number, line in enumerate(lines[:-1]):
        if MADE.fullmatch(line) and lines[number + 1] == PIN_UPDATE:
            return number
    return None


def said_made(output: str) -> bool:
    """Whether a command's output says that a snapshot was made, in the two lines it ends such a snapshot with."""
    return made_at(output.splitlines()) is not None
