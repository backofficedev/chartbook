"""Move a folder store that ChartBook 0.5 laid out to this version's layout (``chartbook/store/v3``).

``docs_src/design/snapshots-and-increments.md``, "Moving a store to this
layout". For each pipeline:

- the newest snapshot its owner made becomes complete, under
  ``snapshots/<pipeline>/<snapshot>/``, every file of its version in its own
  place under its own name;
- every other snapshot its owner made becomes an increment on that one, under
  ``increments/<pipeline>/<snapshot>/``: a file the complete one has, by its
  bytes and size whatever its name, is kept there, and a file it does not
  have is in the increment's own folder;
- every snapshot a pin made from a repository becomes complete too.

A file changes folder by a rename inside the store and is not read: a store
in a synced folder uploads nothing again. The only bytes read are the copies
the result needs (a file that two folders must each hold). A record is
rewritten only in ``stored``. What no record names is not removed: it is
moved, at its old path, under ``_chartbook/left-by-0.5/``.

Three rules hold the rest together.

1. Nothing that was true before a move stops it half way. Whatever can stop
   one is found by :func:`check` before the first step, and said with what
   to do. After the first step only a failure of the disk stops it.
2. The folders are the truth. Every plan, the first and every later one, is
   made from the store as it is: a store that is half moved comes to the
   steps that are left, each of which can be done again with nothing lost.
   The journal only says that a move is under way and whose it is: while it
   is there no other command reads or writes the store
   (:meth:`chartbook.store.FolderStore._check_layout`), and another
   machine's stops this one's move.
3. The command can always be run again on a moved store, and is the one
   remedy for what a machine that had not been brought the move wrote at
   the top afterwards. A snapshot found there is moved in where every file
   its record names is found, in its own folder or by its hash in the
   complete snapshot its pipeline has; where one is found nowhere, the whole
   snapshot is set aside, never moved in with a hole.

``store.json`` says the new layout last, and the journal goes after that.
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

from chartbook.store import (
    _LEFT_BY_A_DESKTOP,
    CLEARED_FILE,
    FOLDER_SCHEMA,
    INCREMENT_FILE,
    INCREMENTS_DIR,
    INCREMENTS_README,
    OWN_DIR,
    PENDING_SECONDS,
    PIPELINE_README,
    PIPELINE_README_OF_0_5,
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

#: Where what no record names is moved, at its old path: nothing is removed that ChartBook did not write.
LEFT_ASIDE = f"{OWN_DIR}/left-by-0.5"

#: The mark the move from the layout of 0.2 left for ChartBook 0.2 to trip over; the name is now the snapshots' own.
OLD_MARK = "0" * 40

#: What ChartBook 0.5 kept at the top of a store, which a moved store has under ``_chartbook/`` or not at all.
OLD_TOP = (V2_LAYOUT.pipelines, V2_LAYOUT.roots, V2_LAYOUT.origins, V2_LAYOUT.tmp)

#: The notes ChartBook itself wrote for a person, by their text: only these are replaced or removed.
OURS = (STORE_README, PIPELINE_README, PIPELINE_README_OF_0_5, INCREMENTS_README)

_COUNTS = ("renamed", "renamed_bytes", "copied", "copied_bytes", "folders_gone", "aside")


class MoveError(StoreError):
    """Raised when a store cannot be moved, or a move stops: it says what and what to do."""


@dataclass
class Step:
    """One thing a move does, which can be done again with nothing lost.

    ``rename`` moves a file inside the store, and ``aside`` one that no
    record names; ``copy`` writes a second copy of a file; ``write`` writes
    a file of ChartBook's own (a record, a note); ``remove`` removes a file
    ChartBook wrote; ``rmdir`` removes a folder that is empty by then;
    ``movedir`` moves one of the top's folders under ``_chartbook/``.
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
        folders_gone: The folders that are no snapshot and go.
        aside: The files no record names, which are moved aside.
        missing: The files a record names that are not there, or are there
            at another size, each as ``(snapshot's folder, path)``.
        set_aside: The snapshots moved aside whole, since a file of each is
            found nowhere, each as ``(pipeline's folder, snapshot's folder)``.
        copied_as_is: The copies whose bytes are not what their record says.
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
    folders_gone: int = 0
    aside: int = 0
    missing: list = field(default_factory=list)
    set_aside: list = field(default_factory=list)
    copied_as_is: list = field(default_factory=list)
    steps: list = field(default_factory=list)


def left_by_a_desktop(name: str) -> bool:
    """Whether a file's name is one a desktop leaves in a folder it shows (``.DS_Store``, ``desktop.ini``), as the store passes them over."""
    return name.startswith(".") or name.lower() in _LEFT_BY_A_DESKTOP


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
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        text, first = None, error
    try:
        first = json.loads((text or "").splitlines()[0]) if text else None
    except (ValueError, IndexError):
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


def _parts(document: dict) -> list[dict]:
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict) and isinstance(part["stored"].get("files"), list)]


def _read(record: Path, name: str) -> dict:
    """A snapshot's record as the store's own reader takes it: readable, every part followed, in its pipeline's folder."""
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
            return json.loads(record.read_text(encoding="utf-8"))
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


def _bases(root: Path) -> dict:
    """The complete snapshot each pipeline has under ``snapshots/`` that its owner made, the newest, with the files it holds whole.

    A file counts as held only where it is there at the size its record
    says: an increment keeps its own good copy of one that is not.
    """
    found: dict = {}
    tree = root / V3_LAYOUT.pipelines
    for folder in (sorted(tree.iterdir()) if tree.is_dir() else []):
        newest = None
        for snapshot in (sorted(folder.iterdir()) if folder.is_dir() and not folder.is_symlink() else []):
            record = snapshot / OWN_DIR / RECORD_FILE
            if not record.is_file():
                continue
            kept = read_kept_record(record)
            if kept.readable and kept.made_by != "pin" and (newest is None or (kept.made_at, snapshot.name) > newest[0]):
                newest = ((kept.made_at, snapshot.name), kept)
        if newest is not None:
            held = {}
            for asset in newest[1].assets:
                for file in asset.files:
                    if _size(file.location) == file.size_bytes:
                        held.setdefault((file.content_hash, file.size_bytes), file.path)
            found[folder.name] = (newest[0][1], held)
    return found


def plan(root) -> Plan:
    """Work out what is left to move in a store, from its folders as they are; nothing is moved.

    The same for a store of 0.5, for one whose move was cut short, and for a
    moved one that has what 0.5 keeps at its top again.

    :raises MoveError: For what is found before anything moves and is in
        the records and folders themselves: a record that cannot be
        followed, and a folder that is no snapshot yet.
    """
    root = Path(root)
    found = Plan()
    old = root / V2_LAYOUT.pipelines
    bases = _bases(root)
    if old.is_dir() and not old.is_symlink():
        for folder in sorted(old.iterdir()):
            if folder.is_symlink() or not folder.is_dir():
                _aside(root, folder, found)
            elif folder.name == UNOWNED_DIR:
                found.steps.append(Step("movedir", folder.relative_to(root).as_posix(), V3_LAYOUT.unowned))
            else:
                _plan_pipeline(root, folder, found, bases.get(folder.name))
        found.steps.append(Step("rmdir", V2_LAYOUT.pipelines))
    found.steps.extend(_top(root, found))
    return found


def _aside(root: Path, file: Path, found: Plan) -> None:
    relative = file.relative_to(root).as_posix()
    found.steps.append(Step("aside", relative, f"{LEFT_ASIDE}/{relative}"))
    found.aside += 0 if left_by_a_desktop(file.name) and os.path.lexists(root / LEFT_ASIDE / relative) else 1


def _plan_pipeline(root: Path, folder: Path, found: Plan, base_there: Optional[tuple]) -> None:
    name = folder.name
    old = f"{V2_LAYOUT.pipelines}/{name}"
    documents: dict[str, dict] = {}
    others: list[Path] = []
    for child in sorted(folder.iterdir()):
        if child.is_dir() and not child.is_symlink() and is_snapshot_folder(child.name) and (child / OWN_DIR / RECORD_FILE).is_file():
            documents[child.name] = _read(child / OWN_DIR / RECORD_FILE, name)
        elif child.is_dir() and not child.is_symlink():
            others.append(child)
    for other in others:
        moved = any((root / tree / name / other.name / OWN_DIR / RECORD_FILE).is_file() for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR))
        cleared = (other / OWN_DIR / CLEARED_FILE).is_file()
        if is_snapshot_folder(other.name) and not cleared and not moved and any(p.is_file() and not left_by_a_desktop(p.name) for p in other.rglob("*")):
            raise MoveError(
                f"The folder {other} holds files and has no record: a snapshot whose record a sync has not brought yet, "
                f"or one that was never finished. The store is not moved. If a sync is still bringing it, wait and run "
                f"this again; if it is left from a snapshot that was never finished, remove that folder and run this again."
            )
        found.folders_gone += 1 if cleared else 0
    base_has: dict = dict(base_there[1]) if base_there else {}

    def target_of(snapshot: str, tree: str, path: str) -> str:
        return f"{tree}/{name}/{snapshot}/{path}"

    def found_somewhere(snapshot: str, document: dict) -> bool:
        """Whether every file a record names is found: where its record says, where this move puts it, or by its hash in the complete snapshot the pipeline has."""
        for part in _parts(document):
            for entry in part["stored"]["files"]:
                kept_in, kept_as = entry.get("kept_in", snapshot), entry.get("kept_as", entry["path"])
                if (root / old / kept_in).is_dir() or (entry["content_hash"], entry["size_bytes"]) in base_has:
                    continue  # there, or missing as it was before the move, which its record goes on saying
                if not any(os.path.lexists(root / target_of(snapshot, tree, entry["path"])) for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR)):
                    return False
        return True

    nowhere = sorted(snapshot for snapshot, document in documents.items() if not found_somewhere(snapshot, document))
    for snapshot in nowhere:
        # Never moved in with a hole: the whole snapshot is set aside, at its old path
        for path in sorted(p for p in (folder / snapshot).rglob("*") if not p.is_dir() or p.is_symlink()):
            _aside(root, path, found)
        found.set_aside.append((name, snapshot))
        del documents[snapshot]
    found.pipelines += 1 if documents else 0
    found.snapshots += len(documents)
    owners = sorted((d["made_at"], s) for s, d in documents.items() if d.get("made_by", "snapshot") != "pin")
    base = base_there[0] if base_there else (owners[-1][1] if owners else None)
    if base is not None and not base_there:
        for part in _parts(documents[base]):
            for entry in part["stored"]["files"]:
                kept_in, kept_as = entry.get("kept_in", base), entry.get("kept_as", entry["path"])
                there = (root / old / kept_in / kept_as, root / target_of(base, V3_LAYOUT.pipelines, entry["path"]))
                if any(_size(place) == entry["size_bytes"] for place in there):
                    base_has.setdefault((entry["content_hash"], entry["size_bytes"]), entry["path"])
    # Where each file is wanted, by where it is now: the complete one first, then the increments, then what a pin made
    wanted: dict[str, list] = {}
    rewritten: dict[str, tuple] = {}
    for snapshot in sorted(documents, key=lambda s: (s != base, documents[s].get("made_by", "snapshot") == "pin", s)):
        document = json.loads(json.dumps(documents[snapshot]))
        by_pin = document.get("made_by", "snapshot") == "pin"
        increment = not by_pin and base is not None and snapshot != base
        tree = INCREMENTS_DIR if increment else V3_LAYOUT.pipelines
        for part in _parts(document):
            for entry in part["stored"]["files"]:
                kept_in, kept_as = entry.get("kept_in", snapshot), entry.get("kept_as", entry["path"])
                key = (entry["content_hash"], entry["size_bytes"])
                entry.pop("kept_as", None)
                source = f"{old}/{kept_in}/{kept_as}"
                target = target_of(snapshot, tree, entry["path"])
                if increment and key in base_has:
                    entry["kept_in"] = base
                    if base_has[key] != entry["path"]:
                        entry["kept_as"] = base_has[key]
                    continue
                entry["kept_in"] = snapshot
                if not (root / old / kept_in).is_dir() and not os.path.lexists(root / target) and key in base_has and base_there:
                    # A snapshot that arrived after a move, complete here: its file is in the pipeline's complete one, by its hash
                    source = target_of(base_there[0], V3_LAYOUT.pipelines, base_has[key])
                    wanted.setdefault(source, [(source, *key, base_there[0])]).append((target, *key, snapshot))
                    continue
                wanted.setdefault(source, []).append((target, *key, snapshot))
        document = {key: value for key, value in document.items() if key != "stored"}
        if increment:
            document["stored"] = {"builds_on": base}
            found.increments += 1
        else:
            found.complete += 1
            found.by_pins += 1 if by_pin else 0
        rewritten[snapshot] = (tree, document, increment)
    named = set()
    for source, targets in sorted(wanted.items()):
        named.add(source)
        size = targets[0][2]
        there = _size(root / source)
        moved = _size(root / targets[0][0]) if there is None else None
        if (there if there is not None else moved) != size:
            # As it was before the move: counted, said, and its record goes on naming it
            found.missing.extend((snapshot, target.split("/", 3)[3]) for target, _, _, snapshot in targets if target != source)
        seen: list = []
        for target, content_hash, _, _ in targets:
            if target in seen:
                continue
            if not seen and target != source:
                # Planned whether the file is there or not: one that arrives before its step is put where its record names it
                found.steps.append(Step("rename", source, target))
                if there is not None or moved is not None:
                    found.renamed += 1
                    found.renamed_bytes += there if there is not None else moved
            elif seen:
                found.steps.append(Step("copy", seen[0], target, content_hash, size))
                if there is not None or moved is not None:
                    found.copied += 1
                    found.copied_bytes += there if there is not None else moved
            seen.append(target)
    for snapshot, (tree, document, increment) in sorted(rewritten.items()):
        own = f"{tree}/{name}/{snapshot}/{OWN_DIR}"
        if increment:
            found.steps.append(Step(
                "write", target=f"{own}/{INCREMENT_FILE}",
                text=f"The rest of this snapshot's files are in {V3_LAYOUT.pipelines}/{name}/{base}\n",
            ))
        found.steps.append(Step("write", target=f"{own}/{RECORD_FILE}", text=json.dumps(document, indent=2, ensure_ascii=False) + "\n"))
    if any(not increment for _, _, increment in rewritten.values()):
        found.steps.append(Step("note", target=f"{V3_LAYOUT.pipelines}/{name}/{README_FILE}", text=V3_LAYOUT.readme))
    if any(increment for _, _, increment in rewritten.values()):
        found.steps.append(Step("note", target=f"{INCREMENTS_DIR}/{name}/{README_FILE}", text=INCREMENTS_README))
    # What is left of the pipeline's old folder: what no record names is moved aside, then its records and notes go
    ours = {f"{old}/{snapshot}/{OWN_DIR}/{RECORD_FILE}" for snapshot in documents}
    ours |= {f"{other.relative_to(root).as_posix()}/{OWN_DIR}/{CLEARED_FILE}" for other in others}
    readme = folder / README_FILE
    if readme.is_file() and _text(readme) in OURS:
        ours.add(f"{old}/{README_FILE}")  # one ChartBook wrote; a person's is moved aside with the rest
    set_aside = tuple(f"{old}/{snapshot}/" for snapshot in nowhere)
    removes = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if (path.is_dir() and not path.is_symlink()) or relative.startswith(set_aside):
            continue
        if relative in ours:
            removes.append(Step("remove", relative))
        elif relative not in named:
            _aside(root, path, found)
    found.steps.extend(removes)
    for path in sorted((p for p in folder.rglob("*") if p.is_dir() and not p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
        found.steps.append(Step("rmdir", path.relative_to(root).as_posix()))
    found.steps.append(Step("rmdir", folder.relative_to(root).as_posix()))


def _text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _top(root: Path, found: Plan) -> list[Step]:
    """What the rest of the top becomes: ChartBook's own folders under ``_chartbook/``, the old mark gone, the README in this layout's words."""
    steps = []
    for old, new in ((V2_LAYOUT.roots, V3_LAYOUT.roots), (V2_LAYOUT.origins, V3_LAYOUT.origins), (V2_LAYOUT.tmp, V3_LAYOUT.tmp)):
        if (root / old).is_dir() and not (root / old).is_symlink():
            steps.append(Step("movedir", old, new))
    mark = root / V3_LAYOUT.pipelines / OLD_MARK
    if mark.is_dir() and not mark.is_symlink():
        for path in sorted(p for p in mark.rglob("*") if not p.is_dir()):
            steps.append(Step("remove", path.relative_to(root).as_posix()))
        for path in sorted((p for p in mark.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            steps.append(Step("rmdir", path.relative_to(root).as_posix()))
        steps.append(Step("rmdir", mark.relative_to(root).as_posix()))
    readme = root / README_FILE
    if readme.is_file() and _text(readme) not in OURS:
        # A note a person wrote is not ChartBook's to destroy
        steps.append(Step("aside", README_FILE, f"{LEFT_ASIDE}/{README_FILE}"))
        found.aside += 1
    steps.append(Step("note", target=README_FILE, text=STORE_README))
    return steps


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
    mine = this_machine(create=False)
    if started is not None and started["machine"] != mine:
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
            f"{links[0]} is a link to another place, and a move does not follow one: the store is not moved. Put the "
            f"folder itself there, or remove the link, and run this again."
        )
    notes = root / V2_LAYOUT.tmp
    fresh = [
        p for p in (notes.rglob("*") if notes.is_dir() else [])
        if p.is_file() and not left_by_a_desktop(p.name) and time.time() - p.stat().st_mtime < PENDING_SECONDS
    ]
    if fresh:
        raise MoveError(
            f"A snapshot is being made in the store at {root} (a note of the last hour is in {V2_LAYOUT.tmp}/): wait for "
            f"it to finish, see that nothing else uses the store, and run this again."
        )
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


def _listing(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for name in OLD_TOP for p in (root / name).rglob("*")) + old_left(root)


def run(root, echo: Callable[[str], None] = lambda line: None, after_step: Callable[[int], None] = lambda number: None) -> Plan:
    """Move a store to this layout, go on with a move that was cut short, or move in what a moved store has at its top again; what the whole move came to.

    :param after_step: Called after each step with its number; for tests
        that stop a move part way.
    :raises MoveError: Before anything moves, for what :func:`check` and
        :func:`plan` stop at; or, part way, when a pass moves nothing of
        what is left. The journal stays, and the command is run again.
    """
    root = Path(root)
    journal = root / JOURNAL
    done = Plan()
    number = 0
    last = None
    while True:
        started = journal_of(root)
        found = plan(root)
        check(root, found)
        if not old_left(root) and marker_of(root) == FOLDER_SCHEMA and not (root / V3_LAYOUT.pipelines / OLD_MARK).exists():
            break
        listing = _listing(root)
        if last is not None and listing == last:
            raise MoveError(
                f"The move of the store at {root} can do no more, and this is left at its top: {', '.join(listing[:5])}"
                f"{' and more' if len(listing) > 5 else ''}. Something there is in use, or keeps arriving: see that "
                f"nothing else uses the store, and run `chartbook store migrate` again."
            )
        first, last = last is None, listing
        # What the whole move comes to is carried in the journal's first line, from one pass and one run to the next
        carried = (started or {}).get("so_far") or {}
        # A plan of a move already under way counts what is done with what is left, as the journal's first line did: the
        # larger is the whole. A later pass of one run moves only what arrived since, and adds
        again = started is not None and first
        so_far = {key: max(carried.get(key, 0), getattr(found, key)) if again else carried.get(key, 0) + getattr(found, key) for key in _COUNTS}
        so_far["set_aside"] = list(carried.get("set_aside", [])) + [list(pair) for pair in found.set_aside if list(pair) not in carried.get("set_aside", [])]
        so_far["copied_as_is"] = list(carried.get("copied_as_is", []))
        header = {
            "schema": JOURNAL_SCHEMA, "machine": this_machine(), "so_far": so_far,
            "started": (started or {}).get("started") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_journal(journal, header, found.steps)
        for step in found.steps:
            if _do(root, step) == "as it is":
                header["so_far"]["copied_as_is"].append(step.target)
                _write_journal(journal, header, found.steps)
            number += 1
            after_step(number)
        if not old_left(root):
            break
    # The marker last, and the journal after it
    marker = root / "store.json"
    if marker_of(root) != FOLDER_SCHEMA:
        temporary = marker.with_name("store.json.moving")
        temporary.write_text(json.dumps({"schema": FOLDER_SCHEMA}) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, marker)
    after_step(number + 1)
    try:
        so_far = (journal_of(root) or {}).get("so_far") or {}
    except MoveError:
        so_far = {}
    if journal.is_file():
        journal.unlink()
    for key in _COUNTS:
        setattr(done, key, so_far.get(key, 0))
    done.set_aside = [tuple(pair) for pair in so_far.get("set_aside", [])]
    done.copied_as_is = list(so_far.get("copied_as_is", []))
    # And what the store holds now, from its folders
    for tree, increment in ((V3_LAYOUT.pipelines, False), (INCREMENTS_DIR, True)):
        for record in sorted((root / tree).glob(f"*/*/{OWN_DIR}/{RECORD_FILE}")):
            kept = read_kept_record(record)
            done.snapshots += 1
            done.increments += 1 if increment else 0
            done.complete += 0 if increment else 1
            done.by_pins += 1 if kept.readable and kept.made_by == "pin" else 0
    done.pipelines = len({p.name for tree in (V3_LAYOUT.pipelines, INCREMENTS_DIR) for p in (root / tree).glob("*") if any(p.glob(f"*/{OWN_DIR}/{RECORD_FILE}"))})
    return done


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
    os.replace(temporary, journal)


def _free_name(target: Path) -> Path:
    """A place beside *target* that is not taken: ``name (2)``, ``name (3)``."""
    number = 2
    while os.path.lexists(target.with_name(f"{target.name} ({number})")):
        number += 1
    return target.with_name(f"{target.name} ({number})")


def _writable(path: Path) -> None:
    if not path.is_symlink():
        os.chmod(path, 0o644)


def _do(root: Path, step: Step) -> Optional[str]:
    """Do one step, or find it done. ``"as it is"`` for a copy whose bytes are not what its record says."""
    source, target = root / step.source, root / step.target
    if step.op in ("rename", "aside"):
        if not os.path.lexists(source):
            return None  # done before the move was cut short; or a file that was never there
        if os.path.lexists(target):
            if left_by_a_desktop(source.name):
                _writable(source)
                source.unlink()  # a desktop's own file, in the way
                return None
            if step.op == "rename":
                return None  # its place is taken by the file this move put there: what is left here is moved aside later
            target = _free_name(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
    elif step.op == "movedir":
        if not source.is_dir():
            return None
        if not os.path.lexists(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            return None
        for child in sorted(source.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            there = target / child.relative_to(source)
            if child.is_dir() and not child.is_symlink():
                continue
            if not os.path.lexists(there):
                there.parent.mkdir(parents=True, exist_ok=True)
                os.replace(child, there)
            elif left_by_a_desktop(child.name) or (there.is_file() and there.stat().st_mtime >= child.stat().st_mtime):
                _writable(child)
                child.unlink()  # a desktop's file; or a note the store has a later one of
            else:
                os.replace(child, there)  # a note written since: the later one is the lockfile's
        for child in sorted((p for p in source.rglob("*") if p.is_dir() and not p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
            child.rmdir()
        source.rmdir()
    elif step.op == "copy":
        if os.path.lexists(target) or not source.is_file():
            return None  # done; or the file was never there, and its record goes on naming it
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".moving")
        hashed = hashlib.sha256()
        with open(source, "rb") as read, open(temporary, "wb") as write:
            for block in iter(lambda: read.read(1 << 20), b""):
                hashed.update(block)
                write.write(block)
            write.flush()
            os.fsync(write.fileno())
        shutil.copymode(source, temporary)
        os.replace(temporary, target)
        if step.content_hash and f"sha256:{hashed.hexdigest()}" != step.content_hash:
            return "as it is"  # it was wrong before: two copies of it are no worse, and the last lines name it
    elif step.op in ("write", "note"):
        if step.op == "note" and target.is_file() and _text(target) not in OURS:
            return None  # a note a person wrote stays
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".moving")
        if target.is_file():
            _writable(target)
        temporary.write_text(step.text, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    elif step.op == "remove":
        if os.path.lexists(source):
            _writable(source)
            source.unlink()
    elif step.op == "rmdir":
        if source.is_dir() and not source.is_symlink():
            for child in list(source.iterdir()):
                if child.is_file() and left_by_a_desktop(child.name) and step.source.split("/")[0] in OLD_TOP + (V3_LAYOUT.pipelines,):
                    _writable(child)
                    child.unlink()  # a desktop left it since the plan: in the way
            try:
                source.rmdir()
            except OSError:
                pass  # something arrived in it since the plan: the next look moves it
    return None
