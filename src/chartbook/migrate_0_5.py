"""Move a folder store that ChartBook 0.5 laid out to this version's layout (``chartbook/store/v3``).

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout". The move does four things. It removes nothing but its own journal
and its own temporary files, and it never renames a file onto one that is
there:

1. It renames the files that records name to where this layout keeps them,
   and makes the few copies the result needs (a file two folders must each
   hold), each hashed as it is written. Per pipeline: the newest snapshot
   its owner made becomes complete under ``snapshots/``; every other one its
   owner made becomes an increment on it under ``increments/``, keeping in
   its own folder only the files that one does not have at their size; and
   every snapshot a pin made becomes complete. The one the others build on
   does not change once a move has begun.
2. It writes the new records (rewritten only in ``stored``), each
   increment's line for a person, and the READMEs, in the new trees.
3. It moves the top's own folders (``roots/``, ``origins/``, ``tmp/``,
   ``pipelines/+unowned/``) under ``_chartbook/``. Where the store has one
   already it merges: what is there stays and the late one goes aside,
   but of two notes of one lockfile the store keeps the later, and the
   other goes aside first.
4. Last, it moves what is left of ``pipelines/`` aside in one rename, to
   ``_chartbook/left-by-0.5/pipelines``: the old records, the notes, every
   file no record names, and anything that arrived meanwhile. Then
   ``store.json`` says the new layout, and then the journal goes.

Three rules hold it together.

- Nothing that was true before a move stops it half way: :func:`check`
  finds it before the first step, and says it with what to do. A file a
  record names that is not there is no such thing. It was missing before,
  it is counted and named, and its record goes on naming it.
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
  ChartBook.

Every rename goes through :func:`chartbook.replacing.replace_when_let`: on
Windows a virus scanner, the indexer or a sync client holds a file or a
folder for a moment, and a rename refused then is tried again for two
seconds before it is said.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from chartbook import hashing
from chartbook.replacing import replace_when_let
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
    is_snapshot_folder,
    pipeline_folder,
    read_kept_record,
    this_machine,
    too_long,
)

#: The journal of a move, in the store: it says that a move is under way, and which machine began it.
JOURNAL = f"{OWN_DIR}/move-to-v3.jsonl"
JOURNAL_SCHEMA = "chartbook/store/move-to-v3"

#: Where what is left of the old layout is moved, whole: nothing is removed that ChartBook did not write.
LEFT_ASIDE = f"{OWN_DIR}/left-by-0.5"

#: The mark the move from the layout of 0.2 left for ChartBook 0.2 to trip over; the name is now the snapshots' own.
OLD_MARK = "0" * 40

#: What ChartBook 0.5 kept at the top of a store, which a moved store has under ``_chartbook/`` or not at all.
OLD_TOP = (V2_LAYOUT.pipelines, V2_LAYOUT.roots, V2_LAYOUT.origins, V2_LAYOUT.tmp)

_COUNTS = ("renamed", "renamed_bytes", "copied", "copied_bytes", "aside")
_LISTS = ("set_aside", "late", "in_place", "copied_as_is")


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
        renamed, renamed_bytes: The files that change folder by rename.
        copied, copied_bytes: The files copied, which are read.
        aside: The files no record names, which go aside with the old folder.
        missing: The files a record names that are not at their size where
            the moved record names them, each as ``(snapshot's folder,
            path)``, sorted.
        set_aside: The snapshots whose records go aside without having been
            moved in, each as ``(pipeline's folder, snapshot's folder)``.
        late: The files of a snapshot that is moved which go aside with the
            old folder, by where they are once aside: one that arrived after
            its snapshot was moved, and one that found a file already where
            it goes (*in_place*).
        in_place: The renames not made, a file being where each goes
            already: ``(where the file at the old place is once aside, the
            place, the size of the one, the size of the other)``.
        copied_as_is: The copies whose bytes are not what their record says.
        kept: Where the old folder is kept, once the move has put it aside.
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
    aside: int = 0
    missing: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)
    late: list = field(default_factory=list)
    in_place: list = field(default_factory=list)
    copied_as_is: list = field(default_factory=list)
    kept: str = ""
    steps: list = field(default_factory=list)


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


def to_move(root: Path) -> bool:
    """Whether ``chartbook store migrate`` has something to do in a folder store: one of 0.5, one whose move was cut short, or a moved one with what 0.5 keeps at its top."""
    root = Path(root)
    said = marker_of(root)
    return (root / JOURNAL).is_file() or said == SCHEMA or (said == FOLDER_SCHEMA and bool(old_left(root)))


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
    elif not kept.whole or _not_followed(kept):
        why = "it names a file by a path that is no plain path inside its pipeline's folder, or says nothing of where one is"
    elif pipeline_folder(kept.pipeline) != name or not kept.folder.name.endswith("_" + kept.commit[:12]):
        why = "it is not in the folder of its pipeline and its commit"
    if why is None:
        try:
            return json.loads(record.read_text(encoding="utf-8")), kept.named
        except (OSError, ValueError) as error:
            why = str(error)
    raise MoveError(
        f"The snapshot record {record} cannot be followed ({why}), so the store is not moved: where its files go is "
        f"not known. If a sync is still bringing it, wait and run this again; if it is no snapshot of yours, move its "
        f"folder out of the store. `chartbook store verify` says more."
    )


def _size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size if path.is_file() and not path.is_symlink() else None
    except OSError:
        return None


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


def _aside_name(root: Path, name: str = V2_LAYOUT.pipelines) -> str:
    """Where a file or a folder at the top of the store is once it is aside: under ``_chartbook/left-by-0.5/``, by its own name or the next free one."""
    return _free_name(root / LEFT_ASIDE / name).relative_to(root).as_posix()


def plan(root) -> Plan:
    """Work out what is left to do in a store, from its folders as they are; nothing is moved.

    In a store whose ``store.json`` says the layout of 0.5 every record
    under ``pipelines/`` is moved by the same rules, whatever of it is
    moved already. In one that says this layout, nothing under a
    ``pipelines/`` that is there again is moved in: it goes aside whole,
    and its snapshots are named.

    :raises MoveError: For a record that cannot be followed, and a folder
        that is no snapshot yet.
    """
    root = Path(root)
    found = Plan()
    old = root / V2_LAYOUT.pipelines
    moved = marker_of(root) == FOLDER_SCHEMA
    if old.is_dir() and not old.is_symlink():
        kept = _aside_name(root)
        named: set = set()
        for folder in sorted(old.iterdir()):
            if folder.is_symlink() or not folder.is_dir() or folder.name == UNOWNED_DIR:
                continue
            if moved:
                for record in sorted(folder.glob(f"*/{OWN_DIR}/{RECORD_FILE}")):
                    found.set_aside.append((folder.name, record.parent.parent.name))
            else:
                named |= _plan_pipeline(root, folder, found)
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
            if path.name in ours or path.relative_to(root).as_posix() in named:
                continue
            of = (parts[0], parts[1]) if len(parts) > 2 else None
            if moved and of in found.set_aside:
                continue  # a file of a snapshot that goes aside with its record, and is named with it
            if moved and of and any((root / tree / of[0] / of[1] / OWN_DIR / RECORD_FILE).is_file() for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR)):
                # It arrived for a snapshot that is moved already: said, with where it will be
                found.late.append(f"{kept}/{path.relative_to(old).as_posix()}")
            else:
                found.aside += 1
        # A file a record names that is where it goes already, and at its old place too: that one goes aside, and is said
        found.in_place = _taken(root, found.steps, kept)
        found.late += [pair[0] for pair in found.in_place]
        found.missing = sorted(set(found.missing))
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


def _plan_pipeline(root: Path, folder: Path, found: Plan) -> set:
    """Plan one pipeline of a store of 0.5; the files its records name, by where 0.5 kept them."""
    name = folder.name
    old = f"{V2_LAYOUT.pipelines}/{name}"
    documents: dict[str, tuple] = {}
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.is_symlink() or not is_snapshot_folder(child.name):
            continue
        if (child / OWN_DIR / RECORD_FILE).is_file():
            documents[child.name] = _read(child / OWN_DIR / RECORD_FILE, name)
        elif not (child / OWN_DIR / CLEARED_FILE).is_file() and any(p.is_file() for p in child.rglob("*")):
            raise MoveError(
                f"The folder {child} holds files and has no record: a snapshot whose record a sync has not brought yet, "
                f"or one that was never finished. The store is not moved. If a sync is still bringing it, wait and run "
                f"this again; if not, move that folder out of the store and run this again: a file in it that a record "
                f"names is then missing, as it would have been, and the move says which."
            )
    if not documents:
        return set()
    found.pipelines += 1
    found.snapshots += len(documents)
    owners = sorted((d["made_at"], s) for s, (d, _) in documents.items() if d.get("made_by", "snapshot") != "pin")
    # The one the others build on does not change once a move has begun: of those its owner made, the one that has
    # a folder under snapshots/ already, its new record written or not; and else the newest. A snapshot that arrives
    # while a move is cut short is an increment on it like any other, however new it is
    begun = [pair for pair in owners if (root / V3_LAYOUT.pipelines / name / pair[1]).is_dir()]
    base = (begun or owners)[-1][1] if owners else None
    base_has: dict = {}

    def target_of(snapshot: str, tree: str, path: str) -> str:
        return f"{tree}/{name}/{snapshot}/{path}"

    if base is not None:
        for part in _followed(*documents[base]):
            for entry in part["stored"]["files"]:
                kept_in, kept_as = entry.get("kept_in", base), entry.get("kept_as", entry["path"])
                # The base has a file only where it will be there at its size: an increment keeps its own good copy otherwise
                if _will(root, f"{old}/{kept_in}/{kept_as}", target_of(base, V3_LAYOUT.pipelines, entry["path"])) == entry["size_bytes"]:
                    base_has.setdefault((entry["content_hash"], entry["size_bytes"]), entry["path"])
    # Where each file is wanted, by where it is now: the complete one first, then the increments, then what a pin made
    wanted: dict[str, list] = {}
    order = sorted(documents, key=lambda s: (s != base, documents[s][0].get("made_by", "snapshot") == "pin", s))
    for snapshot in order:
        document, taken = documents[snapshot]
        document = json.loads(json.dumps(document))
        by_pin = document.get("made_by", "snapshot") == "pin"
        increment = not by_pin and base is not None and snapshot != base
        tree = INCREMENTS_DIR if increment else V3_LAYOUT.pipelines
        for part in _followed(document, taken):
            for entry in part["stored"]["files"]:
                kept_in, kept_as = entry.get("kept_in", snapshot), entry.get("kept_as", entry["path"])
                key = (entry["content_hash"], entry["size_bytes"])
                entry.pop("kept_as", None)
                if increment and key in base_has:
                    entry["kept_in"] = base
                    if base_has[key] != entry["path"]:
                        entry["kept_as"] = base_has[key]
                    continue
                entry["kept_in"] = snapshot
                wanted.setdefault(f"{old}/{kept_in}/{kept_as}", []).append((target_of(snapshot, tree, entry["path"]), *key, snapshot))
        document = {key: value for key, value in document.items() if key != "stored"}
        own = f"{tree}/{name}/{snapshot}/{OWN_DIR}"
        if increment:
            document["stored"] = {"builds_on": base}
            found.increments += 1
        else:
            found.complete += 1
            found.by_pins += 1 if by_pin else 0
        documents[snapshot] = (tree, own, document, increment)
    for source, targets in sorted(wanted.items()):
        if not os.path.lexists(root / source):
            # Renamed already, and by a plan that may have had another of these places first (a record arrived since,
            # or the one the others build on had no folder yet): the copies are made from where the file is
            targets.sort(key=lambda target: not os.path.lexists(root / target[0]))
        # What the rename leaves at the first place, which the copies are made from: the file, by its size, or nothing
        first = _will(root, source, targets[0][0])
        in_place = os.path.lexists(root / source) and os.path.lexists(root / targets[0][0])  # said on its own, with both sizes
        seen: list = []
        for target, content_hash, size, snapshot in targets:
            at = first if not seen or not os.path.lexists(root / target) else _size(root / target)
            if at != size and (seen or not in_place):
                # Not at its size where its record names it: counted, said, and its record goes on naming it
                found.missing.append((snapshot, target.split("/", 3)[3]))
            if target in seen:
                continue
            # Planned whether the file is there or not: one that arrives before its step is put where its record names it
            found.steps.append(Step("copy", seen[0], target, content_hash, size) if seen else Step("rename", source, target))
            if first is not None:
                found.copied += 1 if seen else 0
                found.copied_bytes += first if seen else 0
                found.renamed += 0 if seen else 1
                found.renamed_bytes += 0 if seen else first
            seen.append(target)
    for snapshot in sorted(documents):
        tree, own, document, increment = documents[snapshot]
        if increment:
            found.steps.append(Step(
                "write", target=f"{own}/{INCREMENT_FILE}",
                text=f"The rest of this snapshot's files are in {V3_LAYOUT.pipelines}/{name}/{base}\n",
            ))
        found.steps.append(Step("write", target=f"{own}/{RECORD_FILE}", text=json.dumps(document, indent=2, ensure_ascii=False) + "\n"))
    if any(not increment for _, _, _, increment in documents.values()):
        found.steps.append(Step("note", target=f"{V3_LAYOUT.pipelines}/{name}/{README_FILE}", text=V3_LAYOUT.readme))
    if any(increment for _, _, _, increment in documents.values()):
        found.steps.append(Step("note", target=f"{INCREMENTS_DIR}/{name}/{README_FILE}", text=INCREMENTS_README))
    return set(wanted)


def _text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _tells_case_apart(root: Path) -> bool:
    marker = root / "store.json"
    return not (marker.is_file() and (root / "STORE.JSON").exists() and "STORE.JSON" not in os.listdir(root))


def check(root: Path, found: Plan) -> None:
    """Stop before anything moves, saying what and what to do (:class:`MoveError`).

    Whatever was true before a move and would stop it half way is found
    here. A file a record names that is missing, or of another size, is no
    such thing: it was so before, and is counted.
    """
    root = Path(root)
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
    old = root / V2_LAYOUT.pipelines
    links = [p for p in ([old] + list(old.glob("*")) + list(old.glob("*/*")) if old.exists() or old.is_symlink() else []) if p.is_symlink()]
    if links:
        raise MoveError(
            f"{links[0]} is a link to another place, and a move does not follow one: the store is not moved. If a sync "
            f"is still bringing what it stands for, wait; if not, move the link out of the store and run this again: a "
            f"file a record names through it is then missing, as it would have been, and the move says which."
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
    # merge makes, and where things go aside
    made = {root / OWN_DIR}
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
    folders = {root}
    for step in found.steps:
        for place in (step.source, step.target):
            if place and step.op != "note":
                folder = (root / place).parent
                while not folder.is_dir() and folder != root:
                    folder = folder.parent
                folders.add(folder)
    locked = next((folder for folder in sorted(folders) if not os.access(folder, os.W_OK)), None)
    if locked is not None:
        raise MoveError(
            f"The folder {locked} is not one this user may write, and the move takes a file out of it or puts one into "
            f"it: the store is not moved. It is moved by whoever may write all of it; or let this user write that folder, "
            f"and run this again."
        )
    long = next((why for why in (too_long(root / step.target) for step in found.steps if step.target) if why), None)
    if long is not None:
        raise MoveError(f"The store is not moved: {long}")
    if not _tells_case_apart(root):
        seen: dict = {}
        for step in found.steps:
            if step.op in ("rename", "copy"):
                other = seen.setdefault(step.target.casefold(), step.target)
                if other != step.target:
                    raise MoveError(
                        f"{other} and {step.target} would be two files in one folder of the store, and this disk does not "
                        f"tell their names apart: the store is not moved here. Move it on a machine whose disk does."
                    )
    free = shutil.disk_usage(root).free
    if found.copied_bytes > free:
        raise MoveError(
            f"The store at {root} is not moved: the copies need {found.copied_bytes:,} bytes and its disk has {free:,} "
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
    found = plan(root)
    check(root, found)
    done = Plan()
    number = 0
    if found.steps:
        # What the whole move comes to is carried in the journal's first line, from one run to the next: a plan of a
        # move under way counts what is done with what is left, as the first did, and the larger is the whole
        carried = (started or {}).get("so_far") or {}
        so_far = {key: max(carried.get(key, 0), getattr(found, key)) for key in _COUNTS}
        for key in _LISTS:
            so_far[key] = list(carried.get(key, []))
            _add(so_far[key], getattr(found, key))
        so_far["kept"] = carried.get("kept", "")
        # How many snapshots this move moves in: where it moved any, its last lines say what is missing
        so_far["moved_in"] = max(carried.get("moved_in", 0), found.snapshots)
        header = {
            "schema": JOURNAL_SCHEMA, "machine": this_machine(), "so_far": so_far,
            "started": (started or {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_journal(journal, header, found.steps)
        for step in found.steps:
            if step.op == "aside" and step.source == V2_LAYOUT.pipelines:
                # Once more, just before the old folder goes aside: a file that arrived since its step is put in its place,
                # and what then goes aside that a snapshot may want is named: a file whose place is taken, a record that arrived
                for earlier in found.steps:
                    if earlier.op in ("rename", "copy") and _do(root, earlier) == "as it is":
                        _add(so_far["copied_as_is"], [earlier.target])
                taken = _taken(root, found.steps, _aside_name(root))
                _add(so_far["in_place"], taken)
                _add(so_far["late"], [pair[0] for pair in taken])
                known = {(p.parent.parent.parent.name, p.parent.parent.name) for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for p in (root / tree).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}")}
                arrived = ((p.parent.parent.parent.name, p.parent.parent.name) for p in sorted((root / V2_LAYOUT.pipelines).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}")))
                _add(so_far["set_aside"], [pair for pair in arrived if pair not in known])
            said = _do(root, step)
            if said == "as it is":
                _add(so_far["copied_as_is"], [step.target])
            elif said:
                so_far["kept"] = said
            if said:
                _write_journal(journal, header, found.steps)
            number += 1
            after_step(number)
    # The marker last, and the journal after it
    marker = root / "store.json"
    if marker_of(root) != FOLDER_SCHEMA:
        temporary = marker.with_name("store.json.moving")
        temporary.write_text(json.dumps({"schema": FOLDER_SCHEMA}) + "\n", encoding="utf-8", newline="\n")
        replace_when_let(temporary, marker)
    after_step(number + 1)
    try:
        so_far = (journal_of(root) or {}).get("so_far") or {}
    except MoveError:
        so_far = {}
    if journal.is_file():
        journal.unlink()
    for key in _COUNTS:
        setattr(done, key, so_far.get(key, 0))
    done.set_aside, done.in_place = ([tuple(pair) for pair in so_far.get(key, [])] for key in ("set_aside", "in_place"))
    done.late, done.copied_as_is, done.kept = list(so_far.get("late", [])), list(so_far.get("copied_as_is", [])), so_far.get("kept", "")
    taken = {root / pair[1] for pair in done.in_place}  # each said on its own, with both sizes
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
                done.missing += [
                    (kept.folder.name, file.path) for asset in kept.assets for file in asset.files
                    if _size(file.location) != file.size_bytes and file.location not in taken
                ]
    done.missing = sorted(set(done.missing))
    done.pipelines = len({p.name for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for p in (root / tree).glob("*") if any(p.glob(f"*/{OWN_DIR}/{RECORD_FILE}"))})
    return done


def _add(carried: list, items) -> None:
    """Add to a list the journal carries what it does not hold yet, each as the journal keeps it (a list for a tuple)."""
    for item in items:
        item = list(item) if isinstance(item, tuple) else item
        if item not in carried:
            carried.append(item)


def _write_journal(journal: Path, header: dict, steps: list) -> None:
    """Write a journal in the place of the last one: there is never a move under way and no journal."""
    journal.parent.mkdir(parents=True, exist_ok=True)
    temporary = journal.with_name(journal.name + ".moving")
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for step in steps:
            f.write(json.dumps({key: value for key, value in vars(step).items() if value not in ("", 0)}, ensure_ascii=False) + "\n")
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
    target = _free_name(root / LEFT_ASIDE / path.relative_to(root))
    target.parent.mkdir(parents=True, exist_ok=True)
    replace_when_let(path, target)
    return target


def _own_temporary(path: Path) -> Path:
    """The temporary name a file of ChartBook's own is written under; one left by a move that was cut short is ChartBook's to remove."""
    temporary = path.with_name(path.name + ".moving")
    if os.path.lexists(temporary):
        os.chmod(temporary, 0o644)
        temporary.unlink()
    return temporary


def _do(root: Path, step: Step) -> Optional[str]:
    """Do one step, or find it done. ``"as it is"`` for a copy whose bytes are not what its record says; for the old folder put aside, where it is kept."""
    source, target = root / step.source, root / step.target
    if step.op == "rename":
        if os.path.lexists(source) and not os.path.lexists(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            replace_when_let(source, target)
    elif step.op == "aside":
        if os.path.lexists(source):
            kept = _aside(root, source)
            return kept.relative_to(root).as_posix() if step.source == V2_LAYOUT.pipelines else None
    elif step.op == "movedir":
        if not source.is_dir() or source.is_symlink():
            return None
        if not os.path.lexists(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            replace_when_let(source, target)
            return None
        for child in sorted((p for p in source.rglob("*") if not p.is_dir() or p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
            there = target / child.relative_to(source)
            if os.path.lexists(there):
                # Never onto what is there: an object or an origin the store has stays, and the late one goes aside.
                # Of two notes of one lockfile the later is the one the store keeps: the other goes aside first
                if step.source != V2_LAYOUT.roots or not (there.is_file() and child.is_file() and there.stat().st_mtime < child.stat().st_mtime):
                    continue
                _aside(root, there)
            there.parent.mkdir(parents=True, exist_ok=True)
            replace_when_let(child, there)
        if step.source.split("/")[0] != V2_LAYOUT.pipelines:
            _aside(root, source)  # what is left of it, whole; under pipelines/ it goes aside with that folder
    elif step.op == "copy":
        if os.path.lexists(target) or not source.is_file():
            return None  # done; or the file was never there, and its record goes on naming it
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = _own_temporary(target)
        hashed = hashlib.sha256()
        with open(source, "rb") as read, open(temporary, "wb") as write:
            for block in iter(lambda: read.read(1 << 20), b""):
                hashed.update(block)
                write.write(block)
            write.flush()
            os.fsync(write.fileno())
        shutil.copymode(source, temporary)
        replace_when_let(temporary, target)
        if step.content_hash and f"sha256:{hashed.hexdigest()}" != step.content_hash:
            return "as it is"  # it was wrong before: two copies of it are no worse, and the last lines name it
    elif step.op in ("write", "note"):
        if os.path.lexists(target):
            if step.op == "note" or _text(target) == step.text:
                return None  # a note that is there stays, whoever wrote it; and a record written already is written
            # A record of other words than this plan's (an earlier plan's, before a file arrived): aside, never written over
            _aside(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = _own_temporary(target)
        temporary.write_text(step.text, encoding="utf-8", newline="\n")
        replace_when_let(temporary, target)
    return None
