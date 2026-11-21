"""Putting a file or folder in place on Windows, where something else may hold it for a moment.

A virus scanner, the search indexer, or a sync client such as Google
Drive for desktop opens a file just written to read it, and while it does
Windows refuses to replace or rename it: "Access is denied". It lets go in
a moment, so the move is tried again for two seconds before that is said.
On any other system the first refusal is said at once.

:func:`replace_when_let` writes over what is at its target, as
``os.replace`` does. Where nothing may be written over,
:func:`replace_when_free` looks before every try: what holds a file may
write at the target while the rename waits.
"""

from __future__ import annotations

import os
import sys
import time
from os.path import lexists as _lexists  # by its own name: a test stands in for `os` here, with `replace` alone
from pathlib import Path
from typing import Union

_TRIES = 40
_WAIT_SECONDS = 0.05


def replace_when_let(source: Union[str, Path], target: Union[str, Path]) -> None:
    """``os.replace(source, target)``, tried again for a moment where Windows refuses it."""
    for attempt in range(_TRIES):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt == _TRIES - 1:
                raise
            time.sleep(_WAIT_SECONDS)


def rename_when_let(source: Union[str, Path], target: Union[str, Path]) -> None:
    """``os.rename(source, target)`` of a folder just made, tried again for a moment where Windows refuses it.

    A *target* that has come to be there meanwhile, made by another
    process, is not waited on: the refusal is said, for the caller to
    take what is there.
    """
    for attempt in range(_TRIES):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt == _TRIES - 1 or os.path.exists(target):
                raise
            time.sleep(_WAIT_SECONDS)


def replace_when_free(source: Union[str, Path], target: Union[str, Path]) -> bool:
    """Rename *source* to *target* where nothing is there, tried again for a moment where Windows refuses it; whether it was renamed.

    For a rename that must never land on a file (``chartbook store
    migrate`` removes nothing of anyone's). ``os.replace`` writes over
    what is at its target, and while a rename is refused and waited for,
    whatever holds the file may write there: a sync client that is
    bringing the same file. So every try looks first, and what has come
    to be at *target* stays: the caller is told, and does what it does
    for a target that was taken before it began.
    """
    for attempt in range(_TRIES):
        if _lexists(target):
            return False
        try:
            os.replace(source, target)
            return True
        except PermissionError:
            if sys.platform != "win32" or attempt == _TRIES - 1:
                raise
            time.sleep(_WAIT_SECONDS)
    return False
