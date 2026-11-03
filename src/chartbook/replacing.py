"""Putting a file or folder in place on Windows, where something else may hold it for a moment.

A virus scanner, the search indexer, or a sync client such as Google
Drive for desktop opens a file just written to read it, and while it does
Windows refuses to replace or rename it: "Access is denied". It lets go in
a moment, so the move is tried again for two seconds before that is said.
On any other system the first refusal is said at once.
"""

from __future__ import annotations

import os
import sys
import time
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
