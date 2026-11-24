"""Move a folder store that ChartBook 0.5 laid out to this version's layout (``chartbook/store/v3``).

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout". The move does four things. It removes nothing but its own journal
and its own temporary files, and it never renames a file onto one that is
there:

1. It renames the files that records name to where this layout keeps them,
   and makes the copies the result needs (a file two folders must each
   hold: few where a pipeline's snapshots share their files with the
   newest, and many where older ones share files with each other that it
   does not have), each hashed as it is written. Per pipeline: the newest
   snapshot its owner made becomes complete under ``snapshots/``; every
   other one its owner made becomes an increment on it under
   ``increments/``, keeping in its own folder only the files that one does
   not have at their size; and every snapshot a pin made becomes complete.
   The one the others build on does not change once a move has begun.
2. It writes the new records (rewritten only in ``stored``), each
   increment's line for a person, and the READMEs, in the new trees.
3. It moves the top's own folders (``roots/``, ``origins/``, ``tmp/``,
   ``pipelines/+unowned/``) under ``_chartbook/``. Where the store has one
   already it merges: what is there stays and the late one goes aside,
   but of two notes of one lockfile the store keeps the later, and the
   other goes aside first.
4. Last, it moves what is left of ``pipelines/`` aside in one rename, to
   ``_chartbook/left-by-0.5/pipelines``: the old records, the notes, every
   file no record names, a second copy of a file whose bytes were moved in
   from another place a record names, a sync's second copy of a snapshot's
   folder or of a pipeline's (``<name> 2``), and anything that arrived
   meanwhile. Then ``store.json`` says the new layout, and then the journal
   goes. A run cut short between that rename and ``store.json`` has moved
   all it was to move, and is planned as a moved store (:func:`is_moved`).

Three rules hold it together.

- Nothing that was true before a move stops it half way: :func:`check`
  finds it before the first step, and says it with what to do. A file a
  record names that is not there is no such thing. It was missing before,
  it is counted and named, and its record goes on naming it. A folder
  that holds files and has no record is no such thing either (a real
  store had one that a later record kept its files in): it is taken as
  one that ``store gc`` cleared, and is counted and named.
- The folders are the truth. Every plan is made from the store as it is. The
  old records stay under ``pipelines/`` until the last step, so a plan made
  at any moment of a move sees all of them, and a rename whose file is
  already where it goes is done. The journal only says that a move is under
  way and whose it is.
- The command can always be run again. On a store that is moved already and
  has what 0.5 keeps at its top again (a machine that had not been brought
  the move wrote there), it merges the notes and moves ``pipelines/`` aside,
  whole. Nothing under it is moved in, an object no pipeline owns neither:
  the last lines name each snapshot there, to be made again with this
  ChartBook. A record that goes aside is named so only where the store
  has no snapshot of its pipeline, its commit and its time: one that is a
  second record of a snapshot that was moved in (a sync's copy of a
  folder, ``<name> 2``) is said as that, and nothing is to be made again.

What 0.5 could read, the moved store holds. ChartBook 0.5 found a file by
its hash anywhere in its pipeline's folder, so a store was whole to it
where a record named a place that did not hold its file while another
record's place held the same bytes (a real store was so, 2026-11-20). A
file that is not at its size where its record says, and not where it goes,
is taken from such a place (:func:`_plan_pipeline`). That is a lookup
every plan makes from the folders: it adds no kind of step, and nothing a
later plan goes by (the journal carries the count of what it found, for
the last lines to say with the dry run).

Every rename goes through :mod:`chartbook.replacing`: on Windows a virus
scanner, the indexer or a sync client holds a file or a folder for a
moment, and a rename refused then is tried again for two seconds before it
is said. A rename whose place must be free (a record's file, a folder, a
thing put aside, a copy or a record put in place) looks before every try,
since what holds the file may write there meanwhile: what has come to be
there stays (:func:`chartbook.replacing.replace_when_free`). Only the
journal and ``store.json``, which are the move's own, are written over.

A file the move writes (a copy, a record, a note, its journal,
``store.json``) is written first in a folder of the move's own,
``_chartbook/moving/``, under a name made from a hash of where it goes,
and one rename puts it in place. What is in that folder is the move's to
remove, whoever's run wrote it: when its step is done or found done, and
all of it when the move ends. Nothing anywhere else is ever taken for a
temporary of the move's, whatever its name.

And the move takes a file only as the store's reader would find it: by the
name the disk has for it where a sync wrote the name in the other of
Unicode's forms (:func:`chartbook.store.on_disk`), only a plain file, and
through no link at any depth (:func:`check` stops for one).

It goes by sizes and reads nothing but what it copies. A file of its size
where it goes is the file, as one that a move cut short put there is; so
a copy is made from the old place where the whole file is there and stays
(a file has taken the place it goes to), and from the new tree only where
it is not. A file of the right size and other bytes in the new trees is
not told from the file: a copy of it is hashed as it is written, and the
last lines name it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from chartbook import hashing
from chartbook.identity import ID_COMPONENT_PATTERN
from chartbook.replacing import replace_when_free, replace_when_let
from chartbook.store import (
    CLEARED_FILE,
    FOLDER_SCHEMA,
    INCREMENT_FILE,
    INCREMENTS_DIR,
    INCREMENTS_README,
    OWN_DIR,
    PENDING_SECONDS,
    README_FILE,
    RECORD_FILE,
    SCHEMA,
    STORE_README,
    UNOWNED_DIR,
    V2_LAYOUT,
    V3_LAYOUT,
    StoreError,
    _not_followed,
    _remove_file,
    is_snapshot_folder,
    on_disk,
    pipeline_folder,
    read_kept_record,
    snapshot_folder_name,
    this_machine,
    too_long,
)

#: The journal of a move, in the store: it says that a move is under way, and which machine began it.
JOURNAL = f"{OWN_DIR}/move-to-v3.jsonl"
JOURNAL_SCHEMA = "chartbook/store/move-to-v3"

#: Where what is left of the old layout is moved, whole: nothing is removed that ChartBook did not write.
LEFT_ASIDE = f"{OWN_DIR}/left-by-0.5"

#: The folder of a move's own temporary files: in the store, so that putting one in place is one rename on one disk.
#: Whatever is in it is a move's to remove, whoever's run wrote it; and nothing anywhere else is ever taken for one.
MOVING = f"{OWN_DIR}/moving"

#: The mark the move from the layout of 0.2 left for ChartBook 0.2 to trip over; the name is now the snapshots' own.
OLD_MARK = "0" * 40

#: What ChartBook 0.5 kept at the top of a store, which a moved store has under ``_chartbook/`` or not at all.
OLD_TOP = (V2_LAYOUT.pipelines, V2_LAYOUT.roots, V2_LAYOUT.origins, V2_LAYOUT.tmp)

_COUNTS = ("renamed", "renamed_bytes", "copied", "copied_bytes", "aside", "doubled")
_LISTS = ("set_aside", "second", "late", "in_place", "copied_as_is", "not_pipelines")


class MoveError(StoreError):
    """Raised when a store cannot be moved: it says what and what to do."""


@dataclass
class Step:
    """One thing a move does, which can be done again with nothing lost.

    ``rename`` moves a file a record names, where no file is yet; ``copy``
    writes a second copy of one; ``write`` writes a record or an increment's
    line; ``note`` writes a README where there is none; ``movedir`` merges
    one of the top's folders under ``_chartbook/``; ``aside`` moves a file
    or a folder, whole, under ``_chartbook/left-by-0.5/``.
    """

    op: str
    source: str = ""
    target: str = ""
    content_hash: str = ""
    size: int = 0
    text: str = ""


@dataclass
class Plan:
    """What a move would do, or did, and its steps in order.

    Attributes:
        pipelines, snapshots: How many pipelines and snapshots are moved.
        complete, by_pins, increments: How many snapshots become complete,
            how many of those a pin made, and how many become increments.
        renamed, renamed_bytes: The files that change folder by rename, those
            that a run cut short has renamed already among them. A file that
            is where it goes and at the old place too is none: it is not
            moved (*in_place*).
        copied, copied_bytes: The files copied, which are read.
        copied_into: The snapshots that are given the copies, each as
            ``(pipeline's folder, snapshot's folder, how many files, their
            bytes)``, the largest first.
        store_bytes: What the store takes on its disk before the move, in
            bytes; asked only where something is copied, to say what it
            will take afterwards.
        store_after: What it will take once the copies are made (of a plan:
            *store_bytes* and the copies still to make), or takes now (of a
            move that is done: what its first plan said).
        aside: The files no record names, which go aside with the old folder.
        doubled: The files a record names that go aside with it too, their
            bytes being moved in from another place a record names: a
            second copy that an older snapshot had in its own folder, and
            half a file where the whole is elsewhere.
        missing_in: The snapshots that lack files, each as ``(pipeline's
            folder, snapshot's folder, how many files are missing, of how
            many its record names)``, the one that lacks most first.
        missing: The files a record names that are not at their size where
            the moved record names them, each as ``(pipeline's folder,
            snapshot's folder, path)``, sorted: no record of the pipeline
            says a place that holds them at their size. Two pipelines of
            one repository may have snapshots of one folder name, so a file
            is told by all three.
        elsewhere: How many files were not where their record says, and
            are read after the move from where another record of their
            pipeline had the same bytes; *elsewhere_under* is the folders
            they are under, each with how many (:func:`under`).
        no_record: The folders named as a snapshot's that hold files and
            have no record, were not cleared, and are named for no
            snapshot the store has a record of: each as ``(pipeline's
            folder, folder, how many files)``. One is taken as a cleared
            one is: the files in it that a record names move with that
            record, and the rest goes aside. Its record may yet come.
        second_folders: Such folders that are named for a snapshot whose
            record is in another folder (the folder 0.5 named a second
            later; a sync's ``<name> 2``), each as ``(pipeline's folder,
            folder, how many files, the folder its record is in)``. Taken
            the same way, with nothing to wait for.
        not_pipelines: The folders under ``pipelines/`` whose names are no
            pipeline's folder name (a sync's second copy of one, ``acme+p
            2``): passed over, and aside with the old folder.
        set_aside: The snapshots whose records go aside without having been
            moved in, each as ``(pipeline's folder, snapshot's folder)``:
            those the store has no snapshot of, to be made again.
        second: The records that go aside and are a second record of a
            snapshot that is moved in (its pipeline, its commit and its
            time), each as ``(pipeline's folder, folder)``.
        late: The files of a snapshot that is moved which go aside with the
            old folder, by where they are once aside: one that arrived after
            its snapshot was moved, and one that found a file already where
            it goes (*in_place*).
        in_place: The renames not made, a file being where each goes
            already: ``(where the file at the old place is once aside, the
            place, the size of the one, the size of the other)``.
        copied_as_is: The copies whose bytes are not what their record says.
        kept: Where the old folder is kept, once the move has put it aside.
        moved_in: Of a move that is done, how many snapshots the whole move
            moved in, by what its journal carried: more than none where a
            run that goes on after ``store.json`` was written finishes a
            first move.
        counted: Of a move that is done, whether its journal was there to
            say what the whole move came to. Where it is not (removed by
            hand once the old folder was aside), the counts above are not
            known, and are not to be said as 0.
        steps: The steps, in order.
    """

    pipelines: int = 0
    snapshots: int = 0
    complete: int = 0
    by_pins: int = 0
    increments: int = 0
    renamed: int = 0
    renamed_bytes: int = 0
    copied: int = 0
    copied_bytes: int = 0
    copied_into: list = field(default_factory=list)
    store_bytes: int = 0
    store_after: int = 0
    aside: int = 0
    doubled: int = 0
    missing: list = field(default_factory=list)
    missing_in: list = field(default_factory=list)
    elsewhere: int = 0
    elsewhere_under: list = field(default_factory=list)
    no_record: list = field(default_factory=list)
    second_folders: list = field(default_factory=list)
    not_pipelines: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)
    second: list = field(default_factory=list)
    late: list = field(default_factory=list)
    in_place: list = field(default_factory=list)
    copied_as_is: list = field(default_factory=list)
    kept: str = ""
    moved_in: int = 0
    counted: bool = True
    steps: list = field(default_factory=list)


def under(paths, so_far: Optional[dict] = None) -> list:
    """The folders that files are under, for a line a person reads: each with how many of the files it holds, the largest first.

    A folder is the first two parts of a file's path in its snapshot
    (``_data/prices/``), which is where a pipeline keeps one dataset;
    a file one folder deep is under that folder (``_output/``), and a
    file at the top of a snapshot is counted under its own name. Names of
    files say little where there are thousands, and nothing where a
    file's name is a hash: on a real store three of 58,325 missing files
    were named, each by 64 hex digits.

    :param so_far: Folders counted already, to add these to.
    """
    counted = dict(so_far or {})
    for path in paths:
        parts = path.split("/")
        folder = path if len(parts) == 1 else "/".join(parts[: min(2, len(parts) - 1)]) + "/"
        counted[folder] = counted.get(folder, 0) + 1
    return sorted(counted.items(), key=lambda one: (-one[1], one[0]))


def marker_of(root: Path) -> Optional[str]:
    """What a store's ``store.json`` says its layout is; None where it is not there or does not say."""
    try:
        said = json.loads((Path(root) / "store.json").read_text(encoding="utf-8")).get("schema")
    except (OSError, ValueError, AttributeError):
        return None
    return said if isinstance(said, str) else None


def old_left(root: Path) -> list[str]:
    """What ChartBook 0.5 kept at the top of a store that is there: ``pipelines/``, ``roots/``, ``origins/``, ``tmp/``."""
    return [name for name in OLD_TOP if (Path(root) / name).is_dir()]


def new_there(root: Path) -> bool:
    """Whether a store has anything of this layout's two trees: a store of 0.5 that has is half moved."""
    return any(
        True for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for path in (Path(root) / tree).glob("*/*") if path.parent.name != OLD_MARK
    )


def temporaries_left(root: Path) -> bool:
    """Whether the move's own folder of temporaries (:data:`MOVING`) is there with something a move removes: a file in it, or the folder itself where it is empty.

    A move that was killed once ``store.json`` said the new layout, and
    whose journal was then removed, left it: nothing else says so. A
    folder somebody made in it is no file the move wrote, and stays with
    the folder: one that holds nothing else is nothing to do.
    """
    folder = Path(root) / MOVING
    try:
        if folder.is_symlink() or not folder.is_dir():
            return False
        inside = list(folder.iterdir())
    except OSError:
        return False
    return not inside or any(one.is_symlink() or not one.is_dir() for one in inside)


def to_move(root: Path) -> bool:
    """Whether ``chartbook store migrate`` has something to do in a folder store: one of 0.5, one whose move was cut short, or a moved one with what 0.5 keeps at its top, or with a move's own folder of temporaries still in it."""
    root = Path(root)
    said = marker_of(root)
    return (root / JOURNAL).is_file() or said == SCHEMA or (said == FOLDER_SCHEMA and (bool(old_left(root)) or temporaries_left(root)))


def journal_of(root: Path) -> Optional[dict]:
    """The first line of a move's journal, which says which machine began it and when; None if there is none.

    :raises MoveError: If it cannot be read, with the two ways out.
    """
    path = Path(root) / JOURNAL
    try:
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError, IndexError):
        first = None
    if not isinstance(first, dict) or first.get("schema") != JOURNAL_SCHEMA or not isinstance(first.get("machine"), str):
        raise MoveError(
            f"The store at {root} has the journal of a move to this version's layout, {path}, and it cannot be read. If "
            f"the move was started on another machine, wait for the sync to bring the file whole. If it was started "
            f"here and cut short, remove that file and run `chartbook store migrate` again: it goes on from the folders "
            f"as they are."
        )
    return first


def cut_short_said(root: Path) -> str:
    """What every other command says of a store whose move was cut short, or is running."""
    try:
        started = journal_of(root) or {}
    except MoveError:
        started = {}
    where = f" on the machine {started['machine']}" if started.get("machine") not in (None, this_machine(create=False)) else ""
    return (
        f"A move of the store at {root} to this version's layout was cut short, or is still running{where}. Run "
        f"`chartbook store migrate` again{where} and let it finish; nothing else uses the store until it has."
    )


def _followed(document: dict, taken: frozenset) -> list[dict]:
    """The parts of a record that the store's own reader took, and so the only ones a move follows: a part it passes over is anyone's."""
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [
        part for part in parts
        if isinstance(part.get("content_hash"), str) and part["content_hash"] in taken
        and isinstance(part.get("stored"), dict) and isinstance(part["stored"].get("files"), list)
    ]


def _read(record: Path, name: str) -> tuple[dict, frozenset]:
    """A snapshot's record as the store's own reader takes it: readable, every part followed, in its pipeline's folder. The document, and the hashes the reader took."""
    kept = read_kept_record(record)
    why = None
    if not kept.readable:
        why = "it is not a record this ChartBook reads"
    elif not kept.whole:
        why = "it names a file by a path that is no plain path inside its pipeline's folder, or says nothing of where one is"
    elif pipeline_folder(kept.pipeline) != name or not kept.folder.name.endswith("_" + kept.commit[:12]):
        why = "it is not in the folder of its pipeline and its commit"
    if why is None:
        try:
            return json.loads(record.read_text(encoding="utf-8")), kept.named
        except (OSError, ValueError) as error:
            why = str(error)
    # Its folder may keep files of other snapshots of the pipeline, which 0.5 kept once: asked of their records, and said
    folder = record.parent.parent
    others = {
        file.location
        for other in sorted(folder.parent.glob(f"*/{OWN_DIR}/{RECORD_FILE}")) if other != record
        for asset in read_kept_record(other).assets for file in asset.files
        if file.location.is_relative_to(folder) and _size(file.location) is not None
    }
    if others:
        way_out = (
            f"if it is no snapshot of yours, move that record out of the store and leave its folder where it is: "
            f"{len(others)} file(s) in the folder are named by other snapshots of the pipeline, and are moved with those"
        )
    else:
        way_out = (
            "if it is no snapshot of yours, move its folder out of the store: no other snapshot's record names a file "
            "in it"
        )
    raise MoveError(
        f"The snapshot record {record} cannot be followed ({why}), so the store is not moved: where its files go is "
        f"not known. If a sync is still bringing it, wait and run this again; {way_out}. `chartbook store verify` says more."
    )


def _moved_in(root: Path) -> dict:
    """The snapshots a store has in this layout's two trees, each by its pipeline, its commit and when it was made, with what the store reads of its record."""
    kept = (
        read_kept_record(record)
        for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for record in sorted((root / tree).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}"))
    )
    return {(one.pipeline, one.commit, one.made_at): one for one in kept if one.readable}


def is_moved(root: Path) -> bool:
    """Whether a store is moved: its ``store.json`` says this layout, or its old folder has gone aside.

    The old folder goes aside in the last step, and ``store.json`` is
    written after it. A run cut short between the two has moved all it
    was to move: what a sync then brings under ``pipelines/`` is taken as
    on any moved store (it goes aside, and is said), and not moved in as
    the first of a new move, with its files in the snapshots that took
    them. The folder aside is known for the old one by a folder in it: a
    desktop leaves its own files anywhere, and no folder.

    The folders do not say whose move put the old folder aside. Where no
    journal of this machine does, it may be what a sync has brought so far
    of a move another machine made and finished, and what is at the top is
    then this machine's whole store: the plan is the same, and the command
    says to wait for the sync, and what a yes does, before it asks.
    """
    root = Path(root)
    if marker_of(root) == FOLDER_SCHEMA:
        return True
    try:
        return any(child.is_dir() for aside in (root / LEFT_ASIDE).glob(f"{V2_LAYOUT.pipelines}*") if aside.is_dir() for child in aside.iterdir())
    except OSError:
        return False


def _is_pipeline_folder(name: str) -> bool:
    """Whether a folder under ``pipelines/`` is named as a pipeline's is (:func:`chartbook.store.pipeline_folder`): its ID with ``/`` written ``+``, and for some IDs ``~`` and eight hex digits. A sync's second copy of one, ``acme+p 2``, is not: ChartBook 0.5 read no record in it."""
    stem, tilde, digest = name.partition("~")
    parts = stem.split("+")
    hashed = len(digest) == 8 and all(letter in "0123456789abcdef" for letter in digest)
    return len(parts) <= 2 and all(ID_COMPONENT_PATTERN.match(part) for part in parts) and (hashed or not tilde)


def _named_by_its_record(made_at: object, commit: object) -> Optional[str]:
    """The name a snapshot's record gives its folder (its time, to the second, and its commit); None where the record's time is none."""
    try:
        return snapshot_folder_name(made_at, commit)
    except (ValueError, TypeError):
        return None


def _as_the_disk_tells(root: Path) -> Callable[[str], str]:
    """How a path is written so that two of one file on this disk are the same text: in Unicode's composed form (the store's reader takes a name in either), and without letter case where the disk has none. An ASCII path on a disk that tells case apart is left as it is."""
    caseless = not _tells_case_apart(root)

    def written(path: str) -> str:
        if not path.isascii():
            path = unicodedata.normalize("NFC", path)
        return path.casefold() if caseless else path

    return written


def _told_apart(records, moved_in: set) -> tuple[list, list]:
    """Records that go aside without being moved in, each as ``(pipeline's folder, its own folder)``, in two lists: those of a snapshot the store will not have, to be made again; and those that are a second record of a snapshot that is moved in.

    :param moved_in: The snapshots that are moved in, each by its pipeline,
        its commit and when it was made. A record that cannot be read is
        of none of them.
    """
    again, second = [], []
    for record in records:
        kept = read_kept_record(record)
        is_second = kept.readable and (kept.pipeline, kept.commit, kept.made_at) in moved_in
        (second if is_second else again).append((record.parent.parent.parent.name, record.parent.parent.name))
    return again, second


def _size(path: Path) -> Optional[int]:
    """The size of a plain file, by one question of the disk; None where nothing is there, or what is there is no plain file (a folder, a link)."""
    try:
        seen = os.lstat(path)
    except (OSError, ValueError):
        return None
    return seen.st_size if stat.S_ISREG(seen.st_mode) else None


def _will(root: Path, source: str, target: str) -> Optional[int]:
    """The size of what a rename leaves at its target: what is there already stays, and else it is what is at its source."""
    return _size(root / target) if os.path.lexists(root / target) else _size(root / source)


def _taken(root: Path, steps: list, kept: str) -> list:
    """The renames that are not made, a file being where each goes already: where the file at the old place is once the old folder is aside at *kept*, the place, and the size of each."""
    return [
        (f"{kept}/{step.source.split('/', 1)[1]}", step.target, _size(root / step.source), _size(root / step.target))
        for step in steps
        if step.op == "rename" and os.path.lexists(root / step.source) and os.path.lexists(root / step.target)
    ]


def _takes(root: Path) -> int:
    """What a store takes on its disk, in bytes: its plain files as they are, a link not followed."""
    total = 0
    for folder, _, names in os.walk(root):
        for name in names:
            try:
                seen = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            total += seen.st_size if stat.S_ISREG(seen.st_mode) else 0
    return total


def _aside_name(root: Path, name: str = V2_LAYOUT.pipelines) -> str:
    """Where a file or a folder at the top of the store is once it is aside: under ``_chartbook/left-by-0.5/``, by its own name or the next free one."""
    return _free_name(root / LEFT_ASIDE / name).relative_to(root).as_posix()


def plan(root) -> Plan:
    """Work out what is left to do in a store, from its folders as they are; nothing is moved.

    In a store whose ``store.json`` says the layout of 0.5 every record
    under ``pipelines/`` is moved by the same rules, whatever of it is
    moved already. In one that is moved (:func:`is_moved`: its
    ``store.json`` says this layout, or its old folder has gone aside),
    nothing under a ``pipelines/`` that is there again is moved in: it
    goes aside whole, and its snapshots are named.

    :raises MoveError: For a record that cannot be followed.
    """
    root = Path(root)
    found = Plan()
    old = root / V2_LAYOUT.pipelines
    moved = is_moved(root)
    if old.is_dir() and not old.is_symlink():
        kept = _aside_name(root)
        written = _as_the_disk_tells(root)
        named, said_at, passed, moments = set(), set(), [], set()
        lacking: dict = {}
        moved_in = _moved_in(root) if moved else {}
        for folder in sorted(old.iterdir()):
            if folder.is_symlink() or not folder.is_dir() or folder.name == UNOWNED_DIR:
                continue
            if moved:
                # Named to be made again, but for a second record of a snapshot the store has
                again, second = _told_apart(sorted(folder.glob(f"*/{OWN_DIR}/{RECORD_FILE}")), moved_in)
                found.set_aside += again
                found.second += second
                for pair in second:
                    # What the snapshot in the store lacks of its files: one of them beside this record is said, as any late file is
                    late = read_kept_record(folder / pair[1] / OWN_DIR / RECORD_FILE)
                    has = moved_in[(late.pipeline, late.commit, late.made_at)]
                    lacking[pair] = {file.path for asset in has.assets for file in asset.files if _size(file.location) != file.size_bytes}
            elif not _is_pipeline_folder(folder.name):
                # No pipeline's folder by its name (a sync's second copy of one, "acme+p 2"): ChartBook 0.5 read no
                # record in it. Passed over whole, as a snapshot's second folder is, and said; its records with the rest
                found.not_pipelines.append(folder.name)
                passed += sorted(folder.glob(f"*/{OWN_DIR}/{RECORD_FILE}"))
            else:
                moved_from, places, over, read = _plan_pipeline(root, folder, found)
                named |= {written(place) for place in moved_from}
                said_at |= {written(place) for place in places}
                passed += over
                moments |= read
        if not moved:
            # A record that is passed over is to be made again only where no snapshot of its pipeline, commit and time is moved in
            again, second = _told_apart(passed, moments)
            found.set_aside += again
            found.second += second
        with_record = set(found.set_aside) | set(found.second)
        if not moved and (old / UNOWNED_DIR).is_dir():
            # On the first move only: nothing under a pipelines/ that is there again is moved in, an object neither
            found.steps.append(Step("movedir", f"{V2_LAYOUT.pipelines}/{UNOWNED_DIR}", V3_LAYOUT.unowned))
        ours = {RECORD_FILE, CLEARED_FILE, README_FILE}
        for path in old.rglob("*"):
            parts = path.relative_to(old).parts
            if not path.is_file():
                continue
            if parts[0] == UNOWNED_DIR:
                # An object no pipeline owns is moved in where the store has none at its place; else it goes aside
                found.aside += 1 if moved or os.path.lexists(root / V3_LAYOUT.unowned / Path(*parts[1:])) else 0
                continue
            # As the disk tells names apart: a record's file under a name in the other of Unicode's forms is that file
            place = written(path.relative_to(root).as_posix())
            if path.name in ours or (place in named and not path.is_symlink()):
                continue
            if place in said_at and not path.is_symlink():
                # A record names it, and its bytes are moved in from another place a record names: a second copy
                # that an older snapshot had, or half a file where the whole is elsewhere. Counted apart
                found.doubled += 1
                continue
            of = (parts[0], parts[1]) if len(parts) > 2 else None
            if moved and of in with_record:
                # A file of a snapshot that goes aside with its record, and is named with it; but one that the snapshot
                # in the store lacks is said, as a file is that arrives alone for a snapshot that is moved
                if "/".join(parts[2:]) in lacking.get(of, ()):
                    found.late.append(f"{kept}/{path.relative_to(old).as_posix()}")
                continue
            if moved and of and any((root / tree / of[0] / of[1] / OWN_DIR / RECORD_FILE).is_file() for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR)):
                # It arrived for a snapshot that is moved already: said, with where it will be
                found.late.append(f"{kept}/{path.relative_to(old).as_posix()}")
            else:
                found.aside += 1
        # A file a record names that is where it goes already, and at its old place too: that one goes aside, and is said
        found.in_place = _taken(root, found.steps, kept)
        found.late += [pair[0] for pair in found.in_place]
        found.missing = sorted(set(found.missing))
        found.missing_in.sort(key=lambda lacks: (-lacks[2], lacks[:2]))
        found.copied_into.sort(key=lambda given: (-given[3], given[:2]))
        # What the store takes now, to say what it will take with the copies: asked of the disk only where there are any
        found.store_bytes = _takes(root) if found.copied else 0
        found.store_after = found.store_bytes + found.store_after if found.copied else 0  # so far, the copies still to make
    for old_name, new in ((V2_LAYOUT.roots, V3_LAYOUT.roots), (V2_LAYOUT.origins, V3_LAYOUT.origins), (V2_LAYOUT.tmp, V3_LAYOUT.tmp)):
        if (root / old_name).is_dir() and not (root / old_name).is_symlink():
            found.steps.append(Step("movedir", old_name, new))
    mark = f"{V3_LAYOUT.pipelines}/{OLD_MARK}"
    if (root / mark).is_dir() and not (root / mark).is_symlink():
        # The mark the move from 0.2 left, whose name is now the snapshots' own: aside, like all else that is not moved in
        found.steps.append(Step("aside", mark, f"{LEFT_ASIDE}/{mark}"))
    readme = root / README_FILE
    if not moved:
        if readme.is_file() and _text(readme) != STORE_README:
            # A note a person wrote is not ChartBook's to destroy: aside, on the first move only
            found.steps.append(Step("aside", README_FILE, f"{LEFT_ASIDE}/{README_FILE}"))
            found.aside += 1
        found.steps.append(Step("note", target=README_FILE, text=STORE_README))
    if old.is_dir() and not old.is_symlink():
        # Last: what is left of the old folder, as it then is, in one rename
        found.steps.append(Step("aside", V2_LAYOUT.pipelines, f"{LEFT_ASIDE}/{V2_LAYOUT.pipelines}"))
    return found


def _plan_pipeline(root: Path, folder: Path, found: Plan) -> tuple[set, set, list, set]:
    """Plan one pipeline of a store of 0.5.

    :returns: The places under ``pipelines/`` that the move takes a file
        from; every place its records say a file is; the records in the
        folders that are passed over (a sync's second copy of a snapshot's
        folder, ``<name> 2``); and the snapshots that are moved in, each by
        its pipeline, its commit and when it was made.
    """
    name = folder.name
    old = f"{V2_LAYOUT.pipelines}/{name}"
    documents: dict[str, tuple] = {}
    passed: list = []
    loose: list = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.is_symlink():
            continue
        record = child / OWN_DIR / RECORD_FILE
        if not is_snapshot_folder(child.name):
            # No snapshot's folder by its name (a sync's second copy of one, "<name> 2"): passed over. It goes aside
            # with the old folder, and its record, where it has one, is said
            passed += [record] if record.is_file() else []
        elif record.is_file():
            documents[child.name] = _read(record, name)
        elif not (child / OWN_DIR / CLEARED_FILE).is_file():
            # Files and no record, and not cleared: a snapshot whose record a sync has not brought, or one never
            # finished, which a later record may keep files in. Taken as a cleared folder is, and counted and named.
            # What a desktop leaves in every folder (desktop.ini, .DS_Store) is no file of it
            files = sum(1 for path in child.rglob("*") if path.is_file() and not hashing.is_ignored(path.name))
            if files:
                loose.append((child.name, files))
    # Such a folder may be named for a snapshot whose record is in another folder: the one 0.5 named a second later
    # when the name was taken, or a sync's "<name> 2". Then it is a second folder of that snapshot, and no record of
    # its own is to be waited for
    record_in: dict = {}
    for snapshot, (document, _) in sorted(documents.items()):
        record_in.setdefault(_named_by_its_record(document["made_at"], document["code"]["commit"]), snapshot)
    for record in passed:
        kept = read_kept_record(record)
        if kept.readable:
            record_in.setdefault(_named_by_its_record(kept.made_at, kept.commit), record.parent.parent.name)
    for snapshot, files in loose:
        if snapshot in record_in:
            found.second_folders.append((name, snapshot, files, record_in[snapshot]))
        else:
            found.no_record.append((name, snapshot, files))
    moments = {(document["root"], document["code"]["commit"], document["made_at"]) for document, _ in documents.values()}
    if not documents:
        return set(), set(), passed, moments
    found.pipelines += 1
    found.snapshots += len(documents)
    by_pins = {s for s, (d, _) in documents.items() if d.get("made_by", "snapshot") == "pin"}
    owners = sorted((documents[s][0]["made_at"], s) for s in documents if s not in by_pins)
    # The one the others build on does not change once a move has begun: of those its owner made, the one that has
    # a folder under snapshots/ already, its new record written or not; and else the newest. A snapshot that arrives
    # while a move is cut short is an increment on it like any other, however new it is
    begun = [pair for pair in owners if (root / V3_LAYOUT.pipelines / name / pair[1]).is_dir()]
    base = (begun or owners)[-1][1] if owners else None
    base_has: dict = {}
    on_this_disk: dict = {}

    def target_of(snapshot: str, tree: str, path: str) -> str:
        return f"{tree}/{name}/{snapshot}/{path}"

    def place_of(kept_in: str, kept_as: str) -> str:
        """Where a record says a file is, from the store's top, under the name the disk has for it.

        The store's reader takes a name that a sync wrote in the other of
        Unicode's forms (:func:`chartbook.store.on_disk`), so the move
        does: the size, the rename and the count of what goes aside all
        ask about the one file. An ASCII name is as its record writes it,
        and the disk is asked nothing.
        """
        written = f"{old}/{kept_in}/{kept_as}"
        if written.isascii():
            return written
        if written not in on_this_disk:
            on_this_disk[written] = on_disk(root / old, [kept_in, *kept_as.split("/")]).relative_to(root).as_posix()
        return on_this_disk[written]

    def named_by(snapshot: str):
        """Each file a snapshot's record names, as 0.5 wrote it: its hash and size, its path, and where the record says it is."""
        for part in _followed(*documents[snapshot]):
            for entry in part["stored"]["files"]:
                place = place_of(entry.get("kept_in", snapshot), entry.get("kept_as", entry["path"]))
                yield (entry["content_hash"], entry["size_bytes"]), entry["path"], place

    # ChartBook 0.5 found a file by its hash anywhere in its pipeline's folder, so what it could read the moved store
    # holds: a file that is not where its record says is taken from where another record of the pipeline has the same
    # bytes. It is a lookup, made by every plan from the folders as they are, in three tables. `said` is every place
    # a record says a file's bytes are, by their hash and size. `own` is the places of the files that a snapshot keeps
    # in its own folder (all of the one the others build on, all of one a pin made, and of an increment those that
    # one lacks). `held` is, for each hash and size, the first in order of those of `own` whose file is at its size,
    # at its old place or where it goes: a key of `wanted` below, which the copy of another is made from. Each is
    # worked out once for a run of bytes, however many files have them
    said: dict = {}
    for snapshot in documents:
        for key, _, place in named_by(snapshot):
            said.setdefault(key, set()).add(place)
    own: set = set()
    held: dict = {}
    spare: dict = {}
    looked: dict = {}

    def look(at: str) -> tuple:
        """Whether anything is at a place of the store, and its size where it is a plain file: asked of the disk once a plan."""
        if at not in looked:
            looked[at] = (True, _size(root / at)) if os.path.lexists(root / at) else (False, None)
        return looked[at]

    def will(source: str, target: str) -> Optional[int]:
        """The size of what a rename leaves at its target (:func:`_will`), by what this plan has seen."""
        return look(target)[1] if look(target)[0] else look(source)[1]

    def keeps(snapshot: str, tree: str, key: tuple, path: str, place: str) -> None:
        """Note a file that a snapshot keeps in its own folder. Another's copy is made from it where the file is at its size: at its old place, or where it goes (a move cut short put it there, from this place or from another)."""
        own.add(place)
        if key[1] in (look(place)[1], look(target_of(snapshot, tree, path))[1]):
            held[key] = min(place, held.get(key, place))

    def source_of(key: tuple, place: str, target: str) -> str:
        """Where a file that a snapshot keeps in its own folder is taken from, as a key of `wanted`: where its record says.

        Where it is not there at its size, and nothing is where it goes:
        where a snapshot that keeps the same bytes in its own folder has
        them (`held`), which costs nothing more than a copy; and else
        where the record of an older snapshot says they are, and they are,
        that snapshot naming them in the one it builds on. The first in
        order of each, so the same for the same folders. And where no
        record's place holds them, where its record says: the file is
        missing, as it was.

        A plan made half way through a move chooses again, and ends in the
        same tree. A file that was taken is where it goes, and is looked
        for no more; and once any snapshot has the bytes in its own folder
        the rest are copied from it, so that no second place of an older
        snapshot is taken, which an uninterrupted move leaves to go aside.
        """
        if look(target)[0] or look(place)[1] == key[1]:
            return place
        if key in held:
            return held[key]
        if key not in spare:
            spare[key] = min((at for at in said[key] - own if look(at)[1] == key[1]), default=None)
        return spare[key] or place

    for snapshot in ([base] if base is not None else []) + sorted(by_pins):
        for key, path, place in named_by(snapshot):
            keeps(snapshot, V3_LAYOUT.pipelines, key, path, place)
    if base is not None:
        for key, path, place in named_by(base):
            target = target_of(base, V3_LAYOUT.pipelines, path)
            # The base has a file only where it will be there at its size, from where its record says or from where
            # another's does: an increment keeps its own good copy otherwise. A file of that size already where
            # it goes may be other bytes (a sync of a move made elsewhere). Its hash is read before an increment
            # points at it; otherwise the increment keeps its own copy and the good one is not set aside.
            if look(target)[1] == key[1]:
                trusted = _same_bytes(root / target, key[0])
            else:
                trusted = will(place, target) == key[1] or source_of(key, place, target) != place
            if trusted:
                base_has.setdefault(key, path)
    spare.clear()  # the places of what an increment keeps for itself are `own` from here on
    # Each file a snapshot keeps in its own folder: the complete one's first, then the increments', then those of what a pin made
    wants: list = []
    in_base: list = []
    paths_of: dict = {}  # the paths each record names, by snapshot: of how many files so many are missing
    order = sorted(documents, key=lambda s: (s != base, s in by_pins, s))
    for snapshot in order:
        document, taken = documents[snapshot]
        document = json.loads(json.dumps(document))
        by_pin = snapshot in by_pins
        increment = not by_pin and base is not None and snapshot != base
        tree = INCREMENTS_DIR if increment else V3_LAYOUT.pipelines
        for part in _followed(document, taken):
            for entry in part["stored"]["files"]:
                place = place_of(entry.get("kept_in", snapshot), entry.get("kept_as", entry["path"]))
                key = (entry["content_hash"], entry["size_bytes"])
                paths_of.setdefault(snapshot, set()).add(entry["path"])
                entry.pop("kept_as", None)
                if increment and key in base_has:
                    entry["kept_in"] = base
                    if base_has[key] != entry["path"]:
                        entry["kept_as"] = base_has[key]
                    in_base.append((snapshot, entry["path"], place, key))
                    continue
                entry["kept_in"] = snapshot
                if increment:
                    keeps(snapshot, tree, key, entry["path"], place)
                wants.append((place, target_of(snapshot, tree, entry["path"]), *key, snapshot))
        document = {key: value for key, value in document.items() if key != "stored"}
        own_folder = f"{tree}/{name}/{snapshot}/{OWN_DIR}"
        if increment:
            document["stored"] = {"builds_on": base}
            found.increments += 1
        else:
            found.complete += 1
            found.by_pins += 1 if by_pin else 0
        documents[snapshot] = (tree, own_folder, document, increment)
    # Where each file is wanted, by where it is taken from: once every snapshot's own files are known
    wanted: dict[str, list] = {}
    elsewhere: set = set()
    for place, target, content_hash, size, snapshot in wants:
        source = source_of((content_hash, size), place, target)
        if source != place:
            elsewhere.add((snapshot, target.split("/", 3)[3]))
        wanted.setdefault(source, []).append((target, content_hash, size, snapshot))
    for snapshot, path, place, key in in_base:
        # A file of an older snapshot that was not where its record says, and is read from the one it builds on, is one
        # of them. Only while that one's own file is still to be put in place, and where no file is taken from the
        # place: afterwards a place the move has emptied is not told from one that was empty
        if place not in wanted and look(place)[1] != key[1] and not look(target_of(base, V3_LAYOUT.pipelines, base_has[key]))[0]:
            elsewhere.add((snapshot, path))
    found.elsewhere += len(elsewhere)
    found.elsewhere_under = under([path for _, path in elsewhere], dict(found.elsewhere_under))
    lacking: set = set()
    given: dict = {}  # the copies each snapshot is given: how many files, and their bytes
    for source, targets in sorted(wanted.items()):
        if look(source)[1] != targets[0][2]:
            # What is at the old place is not the file: it was renamed already (by a plan that may have had another of
            # these places first: a record arrived since, or the one the others build on had no folder yet), or a part
            # of it is there, as a sync left it. A place that has the file at its size is first, for the copies
            targets.sort(key=lambda target: look(target[0])[1] != target[2])
        else:
            # The file is at its old place. Where its own place in the new trees is taken (its own snapshot's folder,
            # under its own name: brought by a sync of a move made elsewhere), it stays here and goes aside, and the
            # others are copied from it. It is never renamed into another snapshot, which a plan made half way
            # would do and an uninterrupted move does not: that place is first
            own_place = source.split("/", 1)[1]
            targets.sort(key=lambda target: not (target[0].split("/", 1)[1] == own_place and look(target[0])[0]))
        first_target, first_size = targets[0][0], targets[0][2]
        # What the rename leaves at the first place: the file, by its size, or nothing
        first = will(source, first_target)
        in_place = look(source)[0] and look(first_target)[0]  # said on its own, with both sizes
        # A copy is made only from a file at its size, and from the old place where the whole file is there and stays:
        # a file has taken the place it goes to, which may have its size and other bytes (what a sync has brought so
        # far of a move made elsewhere), so the file is read at the old place, and goes aside with the old folder.
        # From the new tree only where it is not: from the first place, where the rename leaves the file
        if look(first_target)[0] and look(source)[1] == first_size:
            copy_from = source
        elif first == first_size:
            copy_from = first_target
        else:
            copy_from = None
        planned: set = set()
        for target, content_hash, size, snapshot in targets:
            if target == first_target:
                lacks = first != size and not in_place
            elif look(target)[0]:
                lacks = look(target)[1] != size
            else:
                lacks = copy_from is None or size != first_size
            if lacks:
                # Not at its size where its record names it: counted, said, and its record goes on naming it
                lacking.add((snapshot, target.split("/", 3)[3]))
            if target in planned:
                continue
            planned.add(target)
            # Planned whether the file is there or not: one that arrives before its step is put where its record names it
            if target == first_target:
                found.steps.append(Step("rename", source, target))
                # Counted where a rename is to be made, or was made by a run that was cut short (the file is where it
                # goes, and no longer at the old place). One that is at both is not moved, and is said so on its own
                found.renamed += 0 if first is None or in_place else 1
                found.renamed_bytes += 0 if in_place else first or 0
            else:
                found.steps.append(Step("copy", copy_from or first_target, target, content_hash, size))
                if not lacks:
                    found.copied += 1
                    found.copied_bytes += size
                    files, total = given.get(snapshot, (0, 0))
                    given[snapshot] = (files + 1, total + size)
                    found.store_after += 0 if look(target)[0] else size  # still to make: what the store will take more
    found.missing += sorted((name, snapshot, path) for snapshot, path in lacking)
    lacks_by = {}
    for snapshot, _ in lacking:
        lacks_by[snapshot] = lacks_by.get(snapshot, 0) + 1
    found.missing_in += [(name, snapshot, count, len(paths_of[snapshot])) for snapshot, count in sorted(lacks_by.items())]
    found.copied_into += [(name, snapshot, files, total) for snapshot, (files, total) in sorted(given.items())]
    for snapshot in sorted(documents):
        tree, own_folder, document, increment = documents[snapshot]
        if increment:
            found.steps.append(Step(
                "write", target=f"{own_folder}/{INCREMENT_FILE}",
                text=f"The rest of this snapshot's files are in {V3_LAYOUT.pipelines}/{name}/{base}\n",
            ))
        found.steps.append(Step("write", target=f"{own_folder}/{RECORD_FILE}", text=_json(document, indent=2) + "\n"))
    if any(not increment for _, _, _, increment in documents.values()):
        found.steps.append(Step("note", target=f"{V3_LAYOUT.pipelines}/{name}/{README_FILE}", text=V3_LAYOUT.readme))
    if any(increment for _, _, _, increment in documents.values()):
        found.steps.append(Step("note", target=f"{INCREMENTS_DIR}/{name}/{README_FILE}", text=INCREMENTS_README))
    return set(wanted), set().union(*said.values()), passed, moments


def _same_bytes(path: Path, content_hash: str) -> bool:
    """Whether a file already where a record's file goes is the bytes the record names.

    Size is not enough: a sync can put other bytes of the same length there. An increment
    points at the file only when this is true.
    """
    try:
        return hashing.hash_file(path).content_hash == content_hash
    except OSError:
        return False


def _json(value, **kwargs) -> str:
    """JSON as text that can be written as UTF-8.

    A lone surrogate (JSON ``\\ud800``, which ``json.loads`` keeps) cannot be encoded as
    UTF-8. It is escaped, and the text reads back as the same string.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, **kwargs)
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(value, ensure_ascii=True, **kwargs)
    return text


def _text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _tells_case_apart(root: Path) -> bool:
    marker = root / "store.json"
    return not (marker.is_file() and (root / "STORE.JSON").exists() and "STORE.JSON" not in os.listdir(root))


def _check_before_plan(root: Path) -> None:
    started = journal_of(root)
    if started is not None and started["machine"] != this_machine(create=False):
        raise MoveError(
            f"A move of the store at {root} was started on another machine ({started['machine']}), on {started.get('started', 'a day it does not say')}, "
            f"and is not finished: let it finish there (run `chartbook store migrate` again on that machine), and let the "
            f"sync finish. In a synced folder two machines must never both move a store. If that machine cannot finish "
            f"it, take the move over here: remove {root / JOURNAL} and run this again."
        )
    if marker_of(root) not in (SCHEMA, FOLDER_SCHEMA):
        raise MoveError(
            f"The store at {root} has no store.json that says {SCHEMA!r}, the layout of ChartBook 0.5, so it is not moved. "
            f"If a sync is still bringing the file, wait for it; if it is lost for good, put one back that holds "
            f"{json.dumps({'schema': SCHEMA})}, and run this again."
        )


def check(root: Path, found: Plan) -> None:
    """Stop before anything moves, saying what and what to do (:class:`MoveError`).

    Whatever was true before a move and would stop it half way is found
    here: a link, a snapshot being made, a file where a folder is made, a
    folder that may not be written, a file that must be copied and may not
    be read, a locked file, a path too long, two names the disk does not
    tell apart, too little room. A file a record names that is missing, or
    of another size, is no such thing: it was so before, and is counted.
    """
    root = Path(root)
    _check_before_plan(root)
    old = root / V2_LAYOUT.pipelines
    links = [root / name for name in OLD_TOP if (root / name).is_symlink()]
    links += [p for p in (list(old.glob("*")) + list(old.glob("*/*")) if old.exists() and not old.is_symlink() else []) if p.is_symlink()]
    if not links:
        # And at any depth on the way to a file a record names: no part of a path a file is taken from is a link
        asked: set = set()
        for folder in sorted({step.source.rpartition("/")[0] for step in found.steps if step.op in ("rename", "copy") and step.source.startswith(f"{V2_LAYOUT.pipelines}/")}):
            parts = folder.split("/")
            for depth in range(4, len(parts) + 1):  # below pipelines/<pipeline>/<snapshot>, which were asked
                part = "/".join(parts[:depth])
                if part not in asked:
                    asked.add(part)
                    links += [root / part] if (root / part).is_symlink() else []
    if links:
        raise MoveError(
            f"{links[0]} is a link to another place, and a move does not follow one: the store is not moved. If a sync "
            f"is still bringing what it stands for, wait. If it leads to a folder of the store that is kept elsewhere "
            f"(ChartBook 0.5 read through such a link), put that folder itself where the link is, and run this again: "
            f"the files in it that a record names are then moved with the rest."
        )
    notes = root / V2_LAYOUT.tmp
    fresh = [
        p for p in (notes.rglob("*") if notes.is_dir() else [])
        if p.is_file() and not hashing.is_ignored(p.name) and time.time() - p.stat().st_mtime < PENDING_SECONDS
    ]
    if fresh:
        raise MoveError(
            f"A snapshot is being made in the store at {root} (a note of the last hour is in {V2_LAYOUT.tmp}/): wait for "
            f"it to finish, see that nothing else uses the store, and run this again."
        )
    # A file, or a link, where the move makes a folder: each folder of each place a step writes to, the folders a
    # merge makes, where things go aside, and the move's own folder of temporaries
    made = {root / OWN_DIR, root / MOVING}
    for step in found.steps:
        if step.target:
            made.add((root / step.target).parent)
        if step.op == "movedir":
            made |= {root / LEFT_ASIDE, root / step.target}
            made |= {(root / step.target / p.relative_to(root / step.source)).parent for p in (root / step.source).rglob("*") if not p.is_dir()}
    seen_clear: set = {root}
    for folder in sorted(made):
        place = root
        for part in folder.relative_to(root).parts:
            place = place / part
            if place not in seen_clear and os.path.lexists(place) and (place.is_symlink() or not place.is_dir()):
                raise MoveError(
                    f"{place} is a file, or a link, where the move makes a folder: the store is not moved. Move it out of "
                    f"the store, and run this again."
                )
            seen_clear.add(place)
    own = root / MOVING  # every file the move writes is written there first
    while not own.is_dir() and own != root:
        own = own.parent
    folders = {root, own}
    for step in found.steps:
        for place in (step.source, step.target):
            if place:
                folder = (root / place).parent
                while not folder.is_dir() and folder != root:
                    folder = folder.parent
                folders.add(folder)
        if step.op == "movedir":
            for extra in (root / step.target, root / LEFT_ASIDE):
                while not extra.is_dir() and extra != root:
                    extra = extra.parent
                folders.add(extra)
            if (root / step.source).is_dir() and not (root / step.source).is_symlink():
                for p in (root / step.source).rglob("*"):
                    if p.is_dir() and not p.is_symlink():
                        folders.add(p)
                    if not p.is_dir() or p.is_symlink():
                        dest_parent = (root / step.target / p.relative_to(root / step.source)).parent
                        while not dest_parent.is_dir() and dest_parent != root:
                            dest_parent = dest_parent.parent
                        folders.add(dest_parent)
        if step.op in ("movedir", "aside") and (root / step.source).is_dir() and not (root / step.source).is_symlink():
            # A folder changes its parent only where this user may write the folder itself: the old folders, which go
            # under _chartbook/, and pipelines/ last of all
            folders.add(root / step.source)
    locked = next((folder for folder in sorted(folders) if not os.access(folder, os.W_OK)), None)
    if locked is not None:
        raise MoveError(
            f"The folder {locked} is not one this user may write, and the move takes a file out of it, puts one into "
            f"it, or moves the folder itself: the store is not moved. It is moved by whoever may write all of it; or let "
            f"this user write that folder, and run this again."
        )
    # A file a copy will read that this user may not read (another user's, in a shared store). A rename asks only
    # whether its folders may be written, so the file would change folder, and the copy of it would stop the move
    renamed_from = {step.target: step.source for step in found.steps if step.op == "rename"}
    read_asked: set = set()
    for step in found.steps:
        if step.op != "copy" or os.path.lexists(root / step.target):
            continue
        # Where the file is now: where the copy reads it, or where the rename before the copy takes it from
        read = step.source if os.path.lexists(root / step.source) else renamed_from.get(step.source, step.source)
        if read in read_asked:
            continue
        read_asked.add(read)
        if _size(root / read) is not None and not os.access(root / read, os.R_OK):
            raise MoveError(
                f"{root / read} is a file this user may not read, and the move has to copy it (two snapshots must "
                f"each hold it): the store is not moved. It is moved by whoever may read all of it; or let this user "
                f"read that file, and run this again."
            )
    if hasattr(os.stat_result, "st_flags"):
        # A file this system will not rename because it is locked (the Finder's "Locked" box; `chflags uchg`), or a
        # folder that lets nothing out for the same reason: its folder may be written, and the rename is refused
        taken_from = [root / step.source for step in found.steps if step.op in ("rename", "movedir", "aside") and step.source]
        taken_from += [p for p in (root / "store.json", root / JOURNAL) if os.path.lexists(p)]
        held = next((path for path in taken_from + sorted(folders) if _locked(path)), None)
        if held is not None:
            raise MoveError(
                f"{held} is locked, and this system renames nothing that is: the store is not moved. Unlock it (in the "
                f"Finder: Get Info, and untick Locked; in a terminal: chflags nouchg, and the path), and run this again."
            )
    # Each place a step writes to; and where a file is written first, which is as long for every file and shorter
    # than the path of any file of a snapshot
    targets_to_check = [root / step.target for step in found.steps if step.target]
    for step in found.steps:
        if step.op == "movedir" and (root / step.source).is_dir() and not (root / step.source).is_symlink():
            targets_to_check.extend(
                root / step.target / p.relative_to(root / step.source)
                for p in (root / step.source).rglob("*")
                if not p.is_dir() or p.is_symlink()
            )
    def _too_long_folder(path: Path):
        try:
            return too_long(path, folder=True)
        except TypeError:
            return too_long(path)

    long = next(
        (
            why
            for target_path in targets_to_check
            for why in (too_long(target_path), _too_long_folder(target_path.parent))
            if why
        ),
        None,
    )
    long = long or too_long(_temporary_of(root, root / "store.json"))
    if long is not None:
        raise MoveError(f"The store is not moved: {long}")
    if not _tells_case_apart(root):
        import unicodedata

        seen: dict = {}
        parent_dirs: dict = {}
        for step in found.steps:
            if step.op in ("rename", "copy", "write", "note") and step.target:
                norm_target = unicodedata.normalize("NFC", step.target).casefold()
                other = seen.setdefault(norm_target, step.target)
                if other != step.target:
                    raise MoveError(
                        f"{other} and {step.target} would be two files in one folder of the store, and this disk does not "
                        f"tell their names apart: the store is not moved here. Move it on a machine whose disk does."
                    )
                if norm_target in parent_dirs:
                    raise MoveError(
                        f"{step.target} and {parent_dirs[norm_target]} would be a file and a folder of the same name, and this disk does not "
                        f"tell their names apart: the store is not moved here. Move it on a machine whose disk does."
                    )
                parts = norm_target.split("/")
                for depth in range(1, len(parts)):
                    prefix = "/".join(parts[:depth])
                    parent_dirs.setdefault(prefix, step.target)
                    if prefix in seen:
                        raise MoveError(
                            f"{seen[prefix]} and {step.target} would be a file and a folder of the same name, and this disk does not "
                            f"tell their names apart: the store is not moved here. Move it on a machine whose disk does."
                        )
    free = shutil.disk_usage(root).free
    still_needed = max(0, found.store_after - found.store_bytes) if found.store_after else found.copied_bytes
    if still_needed > free:
        raise MoveError(
            f"The store at {root} is not moved: the copies need {still_needed:,} bytes and its disk has {free:,} "
            f"free. Make room, and run this again."
        )


def run(root, echo: Callable[[str], None] = lambda line: None, after_step: Callable[[int], None] = lambda number: None) -> Plan:
    """Move a store to this layout, go on with a move that was cut short, or put aside what a moved store has at its top again; what the whole move came to.

    :param after_step: Called after each step with its number; for tests
        that stop a move part way.
    :raises MoveError: Before anything moves, for what :func:`check` and
        :func:`plan` stop at. Nothing has moved then.
    """
    root = Path(root)
    journal = root / JOURNAL
    first_move = marker_of(root) != FOLDER_SCHEMA
    started = journal_of(root)
    _check_before_plan(root)
    found = plan(root)
    check(root, found)
    done = Plan()
    number = 0
    if found.steps:
        # What the whole move comes to is carried in the journal's first line, from one run to the next: a plan of a
        # move under way counts what is done with what is left, as the first did, and the larger is the whole
        carried = (started or {}).get("so_far") or {}
        so_far = {key: max(carried.get(key, 0), getattr(found, key)) for key in _COUNTS}
        held: dict = {}  # what each list holds, for :func:`_add`
        for key in _LISTS:
            so_far[key] = list(carried.get(key, []))
            _add(so_far, key, getattr(found, key), held)
        # What only the first plan of a move sees whole, a later one finding it part done: the files that were not
        # where their record says (a place the move has emptied since is not told from one that was empty), and
        # each folder with no record with the files it held then
        so_far["elsewhere"] = carried["elsewhere"] if "elsewhere" in carried else found.elsewhere
        so_far["elsewhere_under"] = list(carried["elsewhere_under"] if "elsewhere" in carried else [list(pair) for pair in found.elsewhere_under])
        for key in ("no_record", "second_folders"):
            so_far[key] = list(carried.get(key, []))
            known = {(item[0], item[1]) for item in so_far[key]}
            _add(so_far, key, [item for item in getattr(found, key) if (item[0], item[1]) not in known], held)
        so_far["kept"] = carried.get("kept", "")
        # What the store took when the move began and will take with its copies (the first plan's, which saw it whole), and
        # the copies each snapshot is given: as the counts are, the larger of each
        so_far["store_bytes"], so_far["store_after"] = (carried.get(key) or getattr(found, key) for key in ("store_bytes", "store_after"))
        given = {(item[0], item[1]): item for item in carried.get("copied_into", [])}
        for item in found.copied_into:
            given[(item[0], item[1])] = max(list(item), given.get((item[0], item[1]), list(item)), key=lambda one: one[3])
        so_far["copied_into"] = sorted((list(item) for item in given.values()), key=lambda one: (-one[3], one[:2]))
        # How many snapshots this move moves in: where it moved any, its last lines say what is missing
        so_far["moved_in"] = max(carried.get("moved_in", 0), found.snapshots)
        header = {
            "schema": JOURNAL_SCHEMA, "machine": this_machine(), "so_far": so_far,
            "started": (started or {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_journal(root, header, found.steps)
        for step in found.steps:
            if step.op == "aside" and step.source == V2_LAYOUT.pipelines:
                # Once more, just before the old folder goes aside: a file that arrived since its step is put in its place,
                # and what then goes aside that a snapshot may want is named: a file whose place is taken, a record that arrived
                for earlier in found.steps:
                    if earlier.op in ("rename", "copy") and _do(root, earlier) == "as it is":
                        _add(so_far, "copied_as_is", [earlier.target], held)
                taken = _taken(root, found.steps, _aside_name(root))
                _add(so_far, "in_place", taken, held)
                _add(so_far, "late", [pair[0] for pair in taken], held)
                known = {(p.parent.parent.parent.name, p.parent.parent.name) for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for p in (root / tree).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}")}
                arrived = [
                    p for p in sorted((root / V2_LAYOUT.pipelines).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}"))
                    if (p.parent.parent.parent.name, p.parent.parent.name) not in known
                ]
                # To be made again, but for a second record of a snapshot that was moved in
                again, second = _told_apart(arrived, _moved_in(root))
                _add(so_far, "set_aside", again, held)
                _add(so_far, "second", second, held)
            said = _do(root, step)
            if said == "as it is":
                _add(so_far, "copied_as_is", [step.target], held)
            elif said:
                so_far["kept"] = said
            if said:
                _write_journal(root, header, found.steps)
            number += 1
            after_step(number)
    # The marker last, and the journal after it
    marker = root / "store.json"
    if marker_of(root) != FOLDER_SCHEMA:
        temporary = _own_temporary(root, marker)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"schema": FOLDER_SCHEMA}) + "\n", encoding="utf-8", newline="\n")
        replace_when_let(temporary, marker)
    after_step(number + 1)
    try:
        so_far = (journal_of(root) or {}).get("so_far") or {}
    except MoveError:
        so_far = {}
    # The move's own folder of temporaries, with whatever a run cut short left in it; and the journal after it, so
    # that a run cut short between the two is still told to run again, and removes it then
    _clear_temporaries(root)
    for attempt in range(_EMPTY_TRIES):
        try:
            if journal.is_file():
                journal.unlink()
            break
        except PermissionError:
            if sys.platform != "win32" or attempt == _EMPTY_TRIES - 1:
                raise
            time.sleep(_EMPTY_WAIT_SECONDS)
    for key in _COUNTS + ("elsewhere",):
        setattr(done, key, so_far.get(key, 0))
    for key in ("set_aside", "in_place", "second", "no_record", "second_folders", "elsewhere_under"):
        setattr(done, key, [tuple(item) for item in so_far.get(key, [])])
    done.late, done.copied_as_is, done.kept = list(so_far.get("late", [])), list(so_far.get("copied_as_is", [])), so_far.get("kept", "")
    done.not_pipelines = list(so_far.get("not_pipelines", []))
    done.store_bytes = so_far.get("store_bytes", 0)
    done.store_after = so_far.get("store_after", 0)
    done.copied_into = [tuple(item) for item in so_far.get("copied_into", [])]
    # What the journal carried of the whole move: how many snapshots it moved in, and whether it was there to carry
    # anything. Removed by hand once the old folder was aside, it took the counts with it: they are not known, not 0
    done.moved_in, done.counted = so_far.get("moved_in", 0), bool(so_far)
    taken = {root / pair[1] for pair in done.in_place}  # each said on its own, with both sizes
    sizes: dict = {}

    def size_of(location: Path) -> Optional[int]:
        """The size of a file a record names, asked of the disk once however many snapshots name it: an increment's files are in the snapshot it builds on, and each of them was asked about once for each snapshot."""
        if location not in sizes:
            sizes[location] = _size(location)
        return sizes[location]

    # And what the store holds now, from its folders: its snapshots, and after a move that moved any in, the files
    # that are not at their size where a record names them
    for tree, increment in ((V3_LAYOUT.pipelines, False), (INCREMENTS_DIR, True)):
        for record in sorted((root / tree).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}")):
            kept = read_kept_record(record)
            done.snapshots += 1
            done.increments += 1 if increment else 0
            done.complete += 0 if increment else 1
            done.by_pins += 1 if kept.readable and kept.made_by == "pin" else 0
            if first_move or so_far.get("moved_in"):
                lacks = sorted({file.path for asset in kept.assets for file in asset.files if size_of(file.location) != file.size_bytes and file.location not in taken})
                done.missing += [(kept.folder.parent.name, kept.folder.name, path) for path in lacks]
                if lacks:
                    done.missing_in.append((kept.folder.parent.name, kept.folder.name, len(lacks), len({file.path for asset in kept.assets for file in asset.files})))
    done.missing = sorted(set(done.missing))
    done.missing_in.sort(key=lambda lacks: (-lacks[2], lacks[:2]))
    done.pipelines = len({p.name for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for p in (root / tree).glob("*") if any(p.glob(f"*/{OWN_DIR}/{RECORD_FILE}"))})
    return done


def _add(so_far: dict, key: str, items, held: dict) -> None:
    """Add to a list the journal carries what it does not hold yet, each as the journal keeps it (a list for a tuple).

    What each list holds is kept beside it in *held*, so that adding is no
    search of the list: a store with every file in place and at the old
    place too has a list as long as its files, and searching it for each
    of them is the square of the files.
    """
    carried = so_far[key]
    if key not in held:
        held[key] = {tuple(item) if isinstance(item, list) else item for item in carried}
    for item in items:
        one = tuple(item) if isinstance(item, (list, tuple)) else item
        if one not in held[key]:
            held[key].add(one)
            carried.append(list(one) if isinstance(one, tuple) else one)


def _write_journal(root: Path, header: dict, steps: list) -> None:
    """Write a journal in the place of the last one: there is never a move under way and no journal."""
    journal = root / JOURNAL
    temporary = _own_temporary(root, journal)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(_json(header) + "\n")
        for step in steps:
            f.write(_json({key: value for key, value in vars(step).items() if value not in ("", 0)}) + "\n")
        f.flush()
        os.fsync(f.fileno())
    replace_when_let(temporary, journal)


def _free_name(target: Path) -> Path:
    """*target*, or a place beside it that is not taken: ``name (2)``, ``name (3)``."""
    number, free = 2, target
    while os.path.lexists(free):
        free = target.with_name(f"{target.name} ({number})")
        number += 1
    return free


def _aside(root: Path, path: Path) -> Path:
    """Move a file or a folder, whole, to its own path under ``_chartbook/left-by-0.5/``, or to the next free name beside that; where it then is."""
    while True:
        target = _free_name(root / LEFT_ASIDE / path.relative_to(root))
        target.parent.mkdir(parents=True, exist_ok=True)
        if replace_when_free(path, target):
            return target  # and where something came to be at that name meanwhile, the next free one


#: The flags of a file or a folder that this system renames nothing under: what the Finder's "Locked" box sets on macOS, and ``chflags`` on BSD.
_LOCKED = getattr(stat, "UF_IMMUTABLE", 0) | getattr(stat, "SF_IMMUTABLE", 0) | getattr(stat, "UF_APPEND", 0) | getattr(stat, "SF_APPEND", 0)


def _locked(path: Path) -> bool:
    """Whether a file or a folder is locked against a rename by its flags; False where a system has none, and where it cannot be asked."""
    try:
        return bool(getattr(os.lstat(path), "st_flags", 0) & _LOCKED)
    except OSError:
        return False


def _temporary_of(root: Path, target: Path) -> Path:
    """Where a file the move writes is written first, before one rename puts it in place: in the move's own folder (:data:`MOVING`), under a name made from a hash of where the file goes.

    The same every time for the same place, so one left by a move cut
    short is found by the step that left it; and nothing to do with the
    file's own name, so that no file of a pipeline is ever taken for a
    temporary, and a name's length adds nothing to its own. The path is
    shorter than that of any file of a snapshot (42 characters under the
    store's top, against 45 at the least), so it fits wherever the moved
    store does. Steps are done one at a time, so two places that had one
    name here (24 hex digits of a SHA-256) would only write it in turn.
    """
    return root / MOVING / hashlib.sha256(target.relative_to(root).as_posix().encode("utf-8")).hexdigest()[:24]


def _remove_own(temporary: Path) -> None:
    """Remove a file in the move's own folder, where there is one, with the store's own remover (:func:`chartbook.store._remove_file`).

    Its mode is touched only where the removal is refused without it (a
    read-only file, on Windows). Another user's leftover, in a store that
    users share, is this user's to unlink where the folder may be
    written, and not to change: changing its mode first stopped the move
    at the same step every time. And a second name of a file outside the
    store goes, and that file is as it was: but on Windows, which keeps the
    read-only mark with the file and removes no name of a read-only file,
    such a file is made writable for its name to go (found on Windows 11,
    2026-11-21). That takes somebody linking a read-only file into the
    move's own folder, and never arises in a folder Google Drive syncs,
    which has no second names.

    Where two users share a store on NTFS or a network share and a copy
    of one user's move was cut short, the leftover is read-only and the
    other user may not change it: the move stops at that file each time
    it is run again, and its message names the file, which is then
    removed by hand.
    """
    if os.path.lexists(temporary):
        _remove_file(temporary)


def _own_temporary(root: Path, target: Path) -> Path:
    """The temporary of a file the move writes (:func:`_temporary_of`), free to be written: one left there by a move that was cut short is the move's to remove."""
    temporary = _temporary_of(root, target)
    _remove_own(temporary)
    return temporary


#: How often, and how far apart, the move's own folder is tried again on Windows before it is left: two seconds, as a rename is.
_EMPTY_TRIES = 40
_EMPTY_WAIT_SECONDS = 0.05


def _clear_temporaries(root: Path) -> None:
    """Remove the move's own folder of temporaries with what is left in it, at the end of a move."""
    folder = root / MOVING
    if folder.is_symlink() or not folder.is_dir():
        return
    for left in sorted(folder.iterdir()):
        if left.is_symlink() or not left.is_dir():
            _remove_own(left)
    for attempt in range(_EMPTY_TRIES):
        try:
            os.rmdir(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            # On Windows what holds a file that was just renamed out of the folder, or removed from it, holds the
            # folder for a moment: tried again, as a rename is. Anywhere else, and after that moment, a folder
            # somebody made in it is in the way: no file the move wrote, and left with the folder
            if sys.platform != "win32" or attempt == _EMPTY_TRIES - 1:
                return
            time.sleep(_EMPTY_WAIT_SECONDS)


def _do(root: Path, step: Step) -> Optional[str]:
    """Do one step, or find it done. ``"as it is"`` for a copy whose bytes are not what its record says; for the old folder put aside, where it is kept.

    Nothing is renamed onto a file, a folder or a link that is there: each
    rename whose place must be free looks before every try
    (:func:`chartbook.replacing.replace_when_free`), and what has come to
    be there meanwhile stays, as what was there before the step does.
    """
    source, target = root / step.source, root / step.target
    if step.op == "rename":
        # Only a plain file is a record's file: a folder or a link at the place a record names goes aside with the
        # old folder. And a file that came to be where it goes stays: the one at the old place goes aside, and is said
        if _size(source) is not None and not os.path.lexists(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            replace_when_free(source, target)
    elif step.op == "aside":
        if os.path.lexists(source):
            kept = _aside(root, source)
            return kept.relative_to(root).as_posix() if step.source == V2_LAYOUT.pipelines else None
    elif step.op == "movedir":
        if not source.is_dir() or source.is_symlink():
            return None
        if not os.path.lexists(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            if replace_when_free(source, target):
                return None  # else a folder came to be there meanwhile: merged into it, as into one that was there
        for child in sorted((p for p in source.rglob("*") if not p.is_dir() or p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
            there = target / child.relative_to(source)
            if os.path.lexists(there):
                # Never onto what is there: an object or an origin the store has stays, and the late one goes aside.
                # Of two notes of one lockfile the later is the one the store keeps: the other goes aside first
                if step.source != V2_LAYOUT.roots or not (there.is_file() and child.is_file() and there.stat().st_mtime < child.stat().st_mtime):
                    continue
                _aside(root, there)
            there.parent.mkdir(parents=True, exist_ok=True)
            replace_when_free(child, there)  # one that found its place taken meanwhile stays, and goes aside with what is left
        if step.source.split("/")[0] != V2_LAYOUT.pipelines:
            _aside(root, source)  # what is left of it, whole; under pipelines/ it goes aside with that folder
    elif step.op == "copy":
        if os.path.lexists(target) or _size(source) != step.size:
            # Done; or the file was never there, and its record goes on naming it; or what is there is not the file
            # (a part of it, another file in its place): a copy is made only from a file at its size. And what a
            # copy that was cut short left in the move's own folder goes, the file having come by itself or not at all
            _own_temporary(root, target)
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = _own_temporary(root, target)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        hashed = hashlib.sha256()
        with open(source, "rb") as read, open(temporary, "wb") as write:
            for block in iter(lambda: read.read(1 << 20), b""):
                hashed.update(block)
                write.write(block)
            write.flush()
            os.fsync(write.fileno())
        shutil.copymode(source, temporary)
        if not replace_when_free(temporary, target):
            _own_temporary(root, target)  # a file came to be there meanwhile, and stays: the move's own temporary goes
            return None
        if step.content_hash and f"sha256:{hashed.hexdigest()}" != step.content_hash:
            return "as it is"  # it was wrong before: two copies of it are no worse, and the last lines name it
    elif step.op in ("write", "note"):
        while True:
            if os.path.lexists(target):
                if step.op == "note" or _text(target) == step.text:
                    _own_temporary(root, target)  # one left by a try that found its place taken, or by a run cut short
                    return None  # a note that is there stays, whoever wrote it; and a record written already is written
                # A record of other words than this plan's (an earlier plan's, before a file arrived): aside, never written over
                _aside(root, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = _own_temporary(root, target)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(step.text, encoding="utf-8", newline="\n")
            if replace_when_free(temporary, target):
                return None  # else something came to be there meanwhile: looked at as what was there before
    return None
