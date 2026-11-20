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
the result needs (a file that two folders must each hold), and each is
hashed as it is written. A record is rewritten only in ``stored``. What no
record names is not removed: it is moved, at its old path, under
``_chartbook/left-by-0.5/``.

Everything is planned first and written to a journal, step by step, before
anything moves. Each step can be done again with nothing lost, so a move cut
short is taken up from the journal by running the command again. While the
journal is there no other command reads or writes the store
(:meth:`chartbook.store.FolderStore._check_layout`), and a journal another
machine started stops this one's move: in a synced folder two machines must
never both move. ``store.json`` says the new layout last, and the journal
goes after that.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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
    is_snapshot_folder,
    too_long,
)

#: The journal of a move to this layout, in the store: the plan, step by step, written before anything moves.
JOURNAL = f"{OWN_DIR}/move-to-v3.jsonl"
JOURNAL_SCHEMA = "chartbook/store/move-to-v3"

#: Where what no record names is moved, at its old path: nothing is removed that ChartBook did not write.
LEFT_ASIDE = f"{OWN_DIR}/left-by-0.5"

#: The mark the move from the layout of 0.2 left for ChartBook 0.2 to trip over; the name is now the snapshots' own.
OLD_MARK = "0" * 40


class MoveError(StoreError):
    """Raised when a store of 0.5 cannot be moved, or a move stops: it says what and what to do."""


@dataclass
class Step:
    """One thing a move does, which can be done again with nothing lost.

    ``rename`` and ``aside`` move a file inside the store; ``copy`` writes a
    second copy of one, hashed as it is written; ``write`` writes a file of
    ChartBook's own (a record, a note); ``remove`` removes a file ChartBook
    wrote; ``rmdir`` removes a folder that is empty by then; ``movedir``
    moves one of the top's folders under ``_chartbook/``.
    """

    op: str
    source: str = ""
    target: str = ""
    content_hash: str = ""
    size: int = 0
    text: str = ""


@dataclass
class Plan:
    """What a move would do, and its steps in order.

    Attributes:
        pipelines, snapshots: How many pipelines and snapshots the store of
            0.5 holds.
        complete, by_pins, increments: How many snapshots become complete,
            how many of those a pin made, and how many become increments.
        renamed, renamed_bytes: The files that change folder by rename.
        copied, copied_bytes: The files copied, which are read and hashed.
        folders_gone: The folders that are no snapshot and go.
        aside: The files no record names, which are moved aside.
        missing: The files a record names that are not there, or are there
            at another size, each as ``(snapshot's folder, path)``.
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
    steps: list = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return bool(self.steps)


def journal_of(root: Path) -> Optional[dict]:
    """The first line of a move's journal in a store, which says which machine started it and when; None if there is none."""
    try:
        with open(Path(root) / JOURNAL, encoding="utf-8") as f:
            first = json.loads(f.readline() or "{}")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return first if isinstance(first, dict) else {}


def cut_short_said(root: Path) -> Optional[str]:
    """What every other command says of a store whose move was cut short; None where no move is under way."""
    started = journal_of(root)
    if started is None:
        return None
    where = f" on {started['machine']}" if started.get("machine") and started.get("machine") != socket.gethostname() else ""
    return (
        f"A move of the store at {root} to this version's layout was cut short, or is still running{where}. Run "
        f"`chartbook store migrate` again{where} and let it finish; nothing else uses the store until it has."
    )


def _parts(document: dict) -> list[dict]:
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict) and isinstance(part["stored"].get("files"), list)]


def _read(record: Path) -> dict:
    try:
        document = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") not in ("chartbook/snapshot/v1", "chartbook/snapshot/v2"):
            raise ValueError("it is not a snapshot's record of a version this ChartBook reads")
        if not isinstance(document.get("made_at"), str) or not isinstance(document.get("root"), str):
            raise ValueError("it does not say what it is a snapshot of, or when it was made")
        for part in _parts(document):
            for entry in part["stored"]["files"]:
                for key in ("path", "content_hash"):
                    if not isinstance(entry.get(key), str) or not entry[key]:
                        raise ValueError(f"one of its files has no {key}")
                if not isinstance(entry.get("size_bytes"), int):
                    raise ValueError(f"{entry['path']} has no size")
                kept_in, kept_as = entry.get("kept_in", record.parent.parent.name), entry.get("kept_as", entry["path"])
                if not is_snapshot_folder(str(kept_in)) or any(p in ("", ".", "..") for p in str(kept_as).split("/")):
                    raise ValueError(f"{entry['path']} is kept where no store keeps a file")
        return document
    except (OSError, ValueError) as error:
        raise MoveError(
            f"The snapshot record {record} cannot be read ({error}), so the store is not moved: where its files go is "
            f"not known. If a sync is still bringing it, wait and run this again; `chartbook store verify` says more."
        ) from None


def plan(root, bases: Optional[dict] = None) -> Plan:
    """Work out the move of a store of 0.5; nothing is moved.

    :param bases: For a look after a move (what arrived meanwhile): the
        complete snapshot each pipeline already has under ``snapshots/``, by
        the pipeline's folder name, with the files it holds
        (``{(hash, size): path}``). Such a pipeline's base stays its base.
    :raises MoveError: For a record that cannot be read.
    """
    root = Path(root)
    found = Plan()
    old = root / V2_LAYOUT.pipelines
    steps = found.steps
    if not old.is_dir():
        return found
    for folder in sorted(old.iterdir()):
        if not folder.is_dir():
            _aside(root, folder, found)
            continue
        if folder.name == UNOWNED_DIR:
            steps.append(Step("movedir", folder.relative_to(root).as_posix(), V3_LAYOUT.unowned))
            continue
        _plan_pipeline(root, folder, found, (bases or {}).get(folder.name))
    steps.append(Step("rmdir", V2_LAYOUT.pipelines))
    return found


def _aside(root: Path, file: Path, found: Plan) -> None:
    relative = file.relative_to(root).as_posix()
    found.steps.append(Step("aside", relative, f"{LEFT_ASIDE}/{relative}"))
    found.aside += 1


def _plan_pipeline(root: Path, folder: Path, found: Plan, base_there: Optional[tuple]) -> None:
    name = folder.name
    documents: dict[str, dict] = {}
    others: list[Path] = []  # folders that are no snapshot any more, or never were written
    for child in sorted(folder.iterdir()):
        if child.is_dir() and is_snapshot_folder(child.name) and (child / OWN_DIR / RECORD_FILE).is_file():
            documents[child.name] = _read(child / OWN_DIR / RECORD_FILE)
        elif child.is_dir():
            others.append(child)
    found.pipelines += 1
    found.snapshots += len(documents)
    owners = sorted((d["made_at"], s) for s, d in documents.items() if d.get("made_by", "snapshot") != "pin")
    base = base_there[0] if base_there else (owners[-1][1] if owners else None)
    base_has: dict = dict(base_there[1]) if base_there else {}
    if base is not None and not base_there:
        for part in _parts(documents[base]):
            for entry in part["stored"]["files"]:
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
                source = f"{V2_LAYOUT.pipelines}/{name}/{kept_in}/{kept_as}"
                held = base_has.get((entry["content_hash"], entry["size_bytes"])) if increment else None
                entry.pop("kept_as", None)
                if held is not None:
                    entry["kept_in"] = base
                    if held != entry["path"]:
                        entry["kept_as"] = held
                    continue
                entry["kept_in"] = snapshot
                target = f"{tree}/{name}/{snapshot}/{entry['path']}"
                wanted.setdefault(source, []).append((target, entry["content_hash"], entry["size_bytes"], snapshot))
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
        file = root / source
        size = targets[0][2]
        try:
            there = file.stat().st_size if file.is_file() and not file.is_symlink() else None
        except OSError:
            there = None
        if there is None or there != size:
            # As it was before the move: counted, said, and its record goes on naming it
            found.missing.extend((snapshot, target.split("/", 3)[3]) for target, _, _, snapshot in targets)
            if there is None:
                continue
        seen: list = []
        for target, content_hash, _, _ in targets:
            if target in seen:
                continue
            if not seen:
                found.steps.append(Step("rename", source, target))
                found.renamed += 1
                found.renamed_bytes += there
            else:
                found.steps.append(Step("copy", seen[0], target, content_hash, there))
                found.copied += 1
                found.copied_bytes += there
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
        found.steps.append(Step("write", target=f"{V3_LAYOUT.pipelines}/{name}/{README_FILE}", text=V3_LAYOUT.readme))
    if any(increment for _, _, increment in rewritten.values()):
        found.steps.append(Step("write", target=f"{INCREMENTS_DIR}/{name}/{README_FILE}", text=INCREMENTS_README))
    # What is left of the pipeline's old folder: its records and notes go, what no record names is moved aside
    ours = {f"{V2_LAYOUT.pipelines}/{name}/{README_FILE}"}
    for snapshot in documents:
        ours.add(f"{V2_LAYOUT.pipelines}/{name}/{snapshot}/{OWN_DIR}/{RECORD_FILE}")
    for other in others:
        ours.add(f"{other.relative_to(root).as_posix()}/{OWN_DIR}/{CLEARED_FILE}")
        found.folders_gone += 1
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and not path.is_symlink():
            continue
        if relative in ours:
            found.steps.append(Step("remove", relative))
        elif relative not in named:
            _aside(root, path, found)
    for path in sorted((p for p in folder.rglob("*") if p.is_dir() and not p.is_symlink()), key=lambda p: len(p.parts), reverse=True):
        found.steps.append(Step("rmdir", path.relative_to(root).as_posix()))
    found.steps.append(Step("rmdir", folder.relative_to(root).as_posix()))


def _top(root: Path) -> list[Step]:
    """What the rest of the top becomes: ChartBook's own folders under ``_chartbook/``, the old mark gone, the README in this layout's words."""
    steps = []
    for old, new in ((V2_LAYOUT.roots, V3_LAYOUT.roots), (V2_LAYOUT.origins, V3_LAYOUT.origins), (V2_LAYOUT.tmp, V3_LAYOUT.tmp)):
        if (root / old).is_dir():
            steps.append(Step("movedir", old, new))
    mark = root / V3_LAYOUT.pipelines / OLD_MARK
    if mark.is_dir():
        for path in sorted(p for p in mark.rglob("*") if not p.is_dir()):
            steps.append(Step("remove", path.relative_to(root).as_posix()))
        for path in sorted((p for p in mark.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            steps.append(Step("rmdir", path.relative_to(root).as_posix()))
        steps.append(Step("rmdir", mark.relative_to(root).as_posix()))
    steps.append(Step("write", target=README_FILE, text=STORE_README))
    return steps


def check(root: Path, found: Plan) -> None:
    """Stop before anything moves, saying what and what to do (:class:`MoveError`).

    For a snapshot being made, a store this user may not write, too little
    room for the copies, and a path that would be too long. A record that
    cannot be read stopped the plan already. A file a record names that is
    missing does not stop a move: it was so before.
    """
    root = Path(root)
    started = journal_of(root)
    if started is not None and started.get("machine") not in (None, socket.gethostname()):
        raise MoveError(
            f"A move of the store at {root} was started on {started['machine']}, and is not finished: let it finish "
            f"there (run `chartbook store migrate` again on that machine), and let the sync finish. In a synced "
            f"folder two machines must never both move a store."
        )
    if not os.access(root, os.W_OK):
        raise MoveError(f"The store at {root} is not one this user may write: it is moved by whoever may.")
    notes = root / V2_LAYOUT.tmp
    fresh = [p for p in (notes.rglob("*") if notes.is_dir() else []) if p.is_file() and time.time() - p.stat().st_mtime < PENDING_SECONDS]
    if fresh:
        raise MoveError(
            f"A snapshot is being made in the store at {root} (a note of the last hour is in {V2_LAYOUT.tmp}/): wait for "
            f"it to finish, see that nothing else uses the store, and run this again."
        )
    long = next((why for why in (too_long(root / step.target) for step in found.steps if step.target) if why), None)
    if long is not None:
        raise MoveError(f"The store is not moved: {long}")
    free = shutil.disk_usage(root).free
    if found.copied_bytes > free:
        raise MoveError(
            f"The store at {root} is not moved: the copies need {found.copied_bytes:,} bytes and its disk has {free:,} free."
        )


def run(root, echo: Callable[[str], None] = lambda line: None, after_step: Callable[[int], None] = lambda number: None) -> Plan:
    """Move a store of 0.5 to this layout, or take up a move that was cut short; what was done.

    :param after_step: Called after each step with its number; for tests
        that stop a move part way.
    :raises MoveError: Before anything moves, for what :func:`check` and
        :func:`plan` stop at; or part way, for a copy whose bytes are not
        what its record says. The journal stays, and the command is run
        again.
    """
    root = Path(root)
    journal = root / JOURNAL
    done = Plan()
    number = 0
    first = True
    while True:
        if journal.is_file():
            if journal_of(root).get("machine") not in (None, socket.gethostname()):
                check(root, Plan())
            steps = [Step(**json.loads(line)) for line in journal.read_text(encoding="utf-8").splitlines()[1:] if line.strip()]
            found = Plan(steps=steps)
        else:
            # Once more after a move, for whatever arrived meanwhile: a pipeline that has its complete snapshot keeps it
            found = plan(root, None if first else _bases(root))
            if first:
                check(root, found)
                found.steps.extend(_top(root))
            if not found.steps or (not first and not (root / V2_LAYOUT.pipelines).is_dir()):
                break
            for key in ("pipelines", "snapshots", "complete", "by_pins", "increments", "renamed", "renamed_bytes", "copied", "copied_bytes", "folders_gone", "aside"):
                setattr(done, key, getattr(done, key) + getattr(found, key))
            done.missing.extend(found.missing)
            journal.parent.mkdir(parents=True, exist_ok=True)
            temporary = journal.with_name(journal.name + ".tmp")
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"schema": JOURNAL_SCHEMA, "machine": socket.gethostname(), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
                for step in found.steps:
                    f.write(json.dumps({key: value for key, value in vars(step).items() if value not in ("", 0)}, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, journal)
        for step in found.steps:
            _do(root, step)
            number += 1
            after_step(number)
        first = False
        if (root / V2_LAYOUT.pipelines).is_dir():
            journal.unlink()  # what arrived meanwhile is planned next, and noted before it moves
            continue
        break
    # The marker last, and the journal after it
    marker = root / "store.json"
    temporary = marker.with_name("store.json.tmp")
    temporary.write_text(json.dumps({"schema": FOLDER_SCHEMA}) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, marker)
    after_step(number + 1)
    if journal.is_file():
        journal.unlink()
    return done


def _bases(root: Path) -> dict:
    """The complete snapshot each pipeline has under ``snapshots/`` that its owner made, the newest, with the files it holds."""
    found: dict = {}
    tree = root / V3_LAYOUT.pipelines
    for folder in (sorted(tree.iterdir()) if tree.is_dir() else []):
        newest = None
        for snapshot in sorted(p for p in folder.iterdir() if p.is_dir() and (p / OWN_DIR / RECORD_FILE).is_file()) if folder.is_dir() else []:
            document = _read(snapshot / OWN_DIR / RECORD_FILE)
            if document.get("made_by", "snapshot") != "pin" and (newest is None or (document["made_at"], snapshot.name) > newest[0]):
                newest = ((document["made_at"], snapshot.name), document)
        if newest is not None:
            held = {}
            for part in _parts(newest[1]):
                for entry in part["stored"]["files"]:
                    held.setdefault((entry["content_hash"], entry["size_bytes"]), entry["path"])
            found[folder.name] = (newest[0][1], held)
    return found


def _do(root: Path, step: Step) -> None:
    """Do one step, or find it done."""
    source, target = root / step.source, root / step.target
    if step.op in ("rename", "aside", "movedir"):
        if not os.path.lexists(source):
            return  # done before the move was cut short; or a file that was never there
        if os.path.lexists(target):
            if step.op == "movedir" and target.is_dir():
                for child in sorted(source.iterdir()):
                    if not os.path.lexists(target / child.name):
                        os.replace(child, target / child.name)
                if not any(source.iterdir()):
                    source.rmdir()
                return
            raise MoveError(f"{target} is there already, and {source} is to be moved to it: the store is left as it is. Move one of the two away and run this again.")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
    elif step.op == "copy":
        if target.is_file():
            return
        if not source.is_file():
            return  # the file was never there: its record goes on naming it
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".moving")
        hashed = hashlib.sha256()
        with open(source, "rb") as read, open(temporary, "wb") as write:
            for block in iter(lambda: read.read(1 << 20), b""):
                hashed.update(block)
                write.write(block)
            write.flush()
            os.fsync(write.fileno())
        if step.content_hash and f"sha256:{hashed.hexdigest()}" != step.content_hash:
            if os.path.getsize(temporary) == step.size:
                temporary.unlink()
                raise MoveError(
                    f"{source} is not what its record says (it is sha256:{hashed.hexdigest()}), so no copy of it is made "
                    f"at {target} and the move stops here. `chartbook store migrate` goes on once the file is put right."
                )
        os.replace(temporary, target)
    elif step.op == "write":
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".moving")
        if target.is_file():
            os.chmod(target, 0o644)
        temporary.write_text(step.text, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    elif step.op == "remove":
        if os.path.lexists(source):
            os.chmod(source, 0o644) if not source.is_symlink() else None
            source.unlink()
    elif step.op == "rmdir":
        if source.is_dir() and not source.is_symlink():
            try:
                source.rmdir()
            except OSError:
                # Something arrived in it since the plan: the look once more moves it
                pass
