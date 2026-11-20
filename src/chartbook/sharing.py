"""Sending one pipeline's snapshots to someone else: ``chartbook store export`` and ``store import``.

A pipeline's folder in a store (``snapshots/<pipeline>/``) is what a person
sends a collaborator, and copied by hand into another store's ``snapshots/``
it is that pipeline's snapshots there too. These two commands do the same,
checked:

- **Export** writes chosen snapshots of one pipeline into a folder laid out
  as a store, ``<to>/snapshots/<pipeline>/``: every snapshot by default, the
  newest with ``latest``, or the ones named. Each is a complete snapshot,
  every file of it in its own folder.
- **Import** copies the snapshots of such a folder, or of a pipeline's folder
  copied by hand, into this machine's store, oldest first. Every file is
  hashed as it is copied and checked against its record; a snapshot the
  store has already is not copied again, and nothing there is written over.
  A folder from a store of ChartBook 0.5 (``pipelines/<pipeline>/``, its
  files kept once) is read as it is, and each of its snapshots is written
  complete.

Only what a snapshot's record names goes: its data, its documents and its
index, never anything that runs. A snapshot a pin made from a clone is not
exported: it is the pinning machine's, not the pipeline's.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from chartbook.store import (
    OWN_DIR,
    RECORD_FILE,
    V2_LAYOUT,
    V3_LAYOUT,
    BuiltOnGoneError,
    EarlierLayoutError,
    FolderStore,
    KeptRecord,
    Store,
    StoreError,
    INCREMENTS_DIR,
    _any_length,
    _increment_of,
    _not_followed,
    _kept_files,
    is_snapshot_folder,
    pipeline_folder,
    read_kept_record,
    what_is_wrong_in,
)


class SharingError(StoreError):
    """Raised when snapshots cannot be exported or imported, saying why."""


@dataclass
class Copied:
    """What an export or an import did.

    Attributes:
        copied: Each snapshot written, as ``(pipeline, commit, made_at)``.
        there: Each that the store it went to had already.
        refused: Each that was not, with why: a file not what its record says, say.
        size_bytes: The size of the files copied; a file the store had is not counted.
    """

    copied: list = field(default_factory=list)
    there: list = field(default_factory=list)
    refused: list = field(default_factory=list)
    size_bytes: int = 0


def _records_in(folder: Path) -> list[KeptRecord]:
    """The snapshots' records in one pipeline's folder, oldest first, whatever the folder is named."""
    found = []
    for snapshot in sorted(p for p in folder.iterdir() if p.is_dir() and is_snapshot_folder(p.name)):
        path = snapshot / OWN_DIR / RECORD_FILE
        if os.path.isfile(_any_length(path)):  # a record past Windows' limit is there too
            found.append(read_kept_record(path))
    return sorted(found, key=lambda record: (record.made_at, record.folder.name))


def _pipeline_folders(source: Path) -> list[Path]:
    """The pipelines' folders a folder holds: a store's or an export's (``snapshots/*``; ``pipelines/*`` in one of ChartBook 0.5), or the one it is.

    Both names are looked under: a store of 0.5 that was moved from one of
    0.2 has a ``snapshots/`` too, with no pipeline's folder in it.
    """
    held = [source / name for name in (V3_LAYOUT.pipelines, INCREMENTS_DIR, V2_LAYOUT.pipelines) if (source / name).is_dir()]
    if held:
        return sorted(p for folder in held for p in folder.iterdir() if p.is_dir() and not p.name.startswith("+"))
    if any(p.is_dir() and is_snapshot_folder(p.name) for p in source.iterdir()):
        return [source]
    return sorted(p for p in source.iterdir() if p.is_dir() and any(q.is_dir() and is_snapshot_folder(q.name) for q in p.iterdir()))


def copy_snapshots(records: Iterable[KeptRecord], into: Store, echo: Callable[[str], None] = lambda line: None) -> Copied:
    """Copy snapshots, each by its record, into a store: each complete one, oldest first, then the increments on it, which keep their form and their count; every byte checked.

    A snapshot the store has already (its pipeline, commit and time) is not
    copied again. One whose file is not what its record says, or whose
    record is not one a store wrote, is refused and said, and the rest go.
    """
    done = Copied()
    whole: set = set()  # the complete snapshots in the store that this run wrote, or read and hashed
    # Each complete snapshot, then the increments on it, so that what an increment builds on is there before it
    for record in sorted(records, key=lambda record: (record.increment, record.made_at, record.folder.name)):
        moment = (record.pipeline, record.commit, record.made_at)
        if not record.readable:
            done.refused.append((str(record.path), "its record cannot be read"))
            continue
        if record.made_by != "snapshot":
            continue  # where a pin kept a clone's files: the pinning machine's, not the pipeline's
        what = f"{record.pipeline} at {record.commit[:7]}, made {record.made_at}"
        here = next(
            (
                kept for kept in (into.records() if hasattr(into, "records") else [])
                if kept.readable and (kept.pipeline, kept.commit, kept.made_at) == moment
            ),
            None,
        )
        if here is not None:
            # There only if the store's own snapshot of that moment is whole, its own files read and
            # hashed: nothing is imported over one that is not, since a snapshot's folder is not changed
            wrong = into.verify_snapshot(here.path, [asset.content_hash for asset in here.assets])
            if wrong:
                more = f" (and {len(wrong) - 1} more of its files)" if len(wrong) > 1 else ""
                # The way out is named only on what was looked at: what is being imported is read too, each
                # file of that snapshot where it is, at its size and hash
                theirs = [f"its record does not say where {gap[:19]}… is" for gap in _not_followed(record)]
                theirs += [said for asset in record.assets for _, said in what_is_wrong_in(asset)]
                if theirs:
                    way = (
                        f"What is being imported does not hold it whole either ({theirs[0]}): keep that snapshot's "
                        f"folder, {here.folder}, as it is, and import from a copy that is whole. If a sync is still "
                        f"bringing either, import again when it has"
                    )
                else:
                    way = (
                        f"If a sync is still bringing the file, import again when it has. If the file is lost, remove "
                        f"that snapshot's folder, {here.folder}, and import again: what is imported holds it whole"
                    )
                done.refused.append((what, (
                    f"the store has it already, in {here.folder.name}, and not whole: {wrong[0].message}{more}. Nothing "
                    f"was imported over it. {way}"
                )))
            else:
                done.there.append(moment)
                whole.add(str(here.path))
            continue
        why = _not_to_copy(record)
        if why is not None:
            done.refused.append((what, why))
            continue
        try:
            document = json.loads(record.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            done.refused.append((what, f"its record cannot be read: {error}"))
            continue
        pending = None
        try:
            on = _builds_on_there(record, into, whole)  # it keeps its form on a complete one found whole in this run
            counted = done.size_bytes
            # An increment that keeps its form keeps its count: the next snapshot here counts on from it
            as_it_was = {"builds_on": on, "increments_bytes": record.increments_bytes or None} if on is not None else {}
            pending = into.begin(record.pipeline, record.commit, record.made_at, **as_it_was)
            why = _copy_parts(document, record, pending, done)
            if why is None:
                try:
                    written = pending.write(document)
                    if on is None:
                        whole.add(str(written))  # written in this run, each file hashed as it was written
                except BuiltOnGoneError:
                    # What it builds on went from the store meanwhile: written complete, every file being at hand
                    pending.discard()
                    pending = into.begin(record.pipeline, record.commit, record.made_at)
                    done.size_bytes = counted  # what the increment had counted is counted once
                    document = json.loads(record.path.read_text(encoding="utf-8"))
                    why = _copy_parts(document, record, pending, done)
                    if why is None:
                        pending.write(document)
        except (OSError, ValueError, StoreError) as error:
            why = str(error) or type(error).__name__
        except BaseException:
            if pending is not None:
                pending.discard()
            raise
        if why is not None:
            if pending is not None:
                pending.discard()
            done.refused.append((what, why))
            continue
        done.copied.append(moment)
        echo(f"{record.pipeline} at {record.commit[:7]}, made {record.made_at}")
    return done


def _builds_on_there(record: KeptRecord, into: Store, whole: set) -> Optional[str]:
    """The folder name, in the store copied into, of the complete snapshot that an increment builds on where it came from; None where it is to be written complete.

    An increment keeps its form only on a complete snapshot that was
    written in this run, or read and hashed in this run (*whole*, by its
    record's path): never on one whose files are taken on trust. Where
    what was sent holds the increment and not the complete one, the store's
    own snapshot of that name is the one, if it is whole.
    """
    if not (record.increment and record.builds_on) or getattr(into, "increments_path", lambda: None)() is None:
        return None
    source = record.folder.parent.parent.parent / V3_LAYOUT.pipelines / record.folder.parent.name / record.builds_on / OWN_DIR / RECORD_FILE
    on = read_kept_record(source) if os.path.isfile(_any_length(source)) else None
    for kept in into.records():
        # A complete one by what its record is: not one that keeps files in other folders (0.5's kind, copied in by hand)
        if not kept.complete or kept.pipeline != record.pipeline:
            continue
        same = (kept.commit, kept.made_at) == (on.commit, on.made_at) if on is not None and on.readable else kept.folder.name == record.builds_on
        if same:
            if str(kept.path) not in whole and not into.verify_snapshot(kept.path):
                whole.add(str(kept.path))
            return kept.folder.name if str(kept.path) in whole else None
    return None


def _a_link(record: KeptRecord) -> bool:
    """Whether a snapshot's record or a folder holding it is a link; for an increment, the folder of the complete snapshot it builds on, or one holding that, too. None is followed, by an import or an export."""
    folder = record.folder
    places = [record.path, record.path.parent, folder, folder.parent]
    if record.increment and record.builds_on:
        complete = folder.parent.parent.parent / V3_LAYOUT.pipelines / folder.parent.name
        places += [complete / record.builds_on, complete, complete.parent, folder.parent.parent]
    return any(place.is_symlink() for place in places)


def _not_to_copy(record: KeptRecord) -> Optional[str]:
    """Why a snapshot is not to be copied, by what a store asks of its record; None if it may be.

    Read as any record is (:func:`chartbook.snapshot.read`): its schema, its
    time, its pipeline's ID, its paths, and its folder's name, which must
    be its pipeline's and its commit's. A record or a folder that is a link
    is refused, as a reader refuses one.
    """
    from chartbook.snapshot import SnapshotError, read

    folder = record.folder
    if _a_link(record):
        return "its record, or a folder holding it or the snapshot it builds on, is a link"
    try:
        taken = read(record.path)
    except SnapshotError as error:
        return str(error)
    if folder.parent.name != pipeline_folder(taken.pipeline):
        return f"it is in the folder {folder.parent.name}, and is a snapshot of {taken.pipeline}, whose folder is {pipeline_folder(taken.pipeline)}"
    return None


def _copy_parts(document: dict, record: KeptRecord, pending, done: Copied) -> Optional[str]:
    """Put each part a record names into the snapshot being written, and give the record where each is kept now; why not, if not."""
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    for part in parts:
        if not isinstance(part.get("content_hash"), str):
            continue  # declared and not built
        if "stored" not in part:
            return f"its record's {part.get('id', 'part')} names {part['content_hash']}, and does not say where its files are"
        kept = _kept_files(part["stored"], record.folder.parent, record.folder.name, _increment_of(record.folder, document))
        if kept is None:
            return f"its record's {part.get('id', 'part')} says nothing a store could follow"
        at, single, files = kept
        # A folder sent by someone may hold a link to a file of this machine's: never followed
        inside = [Path(os.path.realpath(record.folder.parent))]
        if record.increment:
            # An increment's files are in two folders of what it came in: its own, and the one it builds on
            # as the folder that was given has it: a link there leads out, and is not followed
            inside.append(Path(os.path.realpath(record.folder.parent.parent.parent)) / V3_LAYOUT.pipelines / record.folder.parent.name)
        for file in files:
            if file.location.is_symlink() or not any(Path(os.path.realpath(file.location)).is_relative_to(folder) for folder in inside):
                return f"{file.path} is a link, or leads out of the folder it came in"
        # A file an increment keeps in the complete one, where what was sent does not hold that one: the store's own
        # copy of it, in the complete snapshot this run found whole
        at_hand = {
            file.location: (pending._held_whole(file.content_hash, file.size_bytes) if getattr(pending, "builds_on", None) and not file.location.is_file() else None) or file.location
            for file in files
        }
        missing = next((file for file in files if not Path(at_hand[file.location]).is_file()), None)
        if missing is not None:
            return f"{missing.path} is not there"
        sources = [(file.relative, str(at_hand[file.location])) for file in files]
        stored = pending.put_listed(sources, files[0].path if single else at, single)
        wrong = [
            new["path"] for new, old in zip(stored.stored["files"], files) if new["content_hash"] != old.content_hash
        ]
        if wrong or stored.content_hash != part["content_hash"]:
            return f"{(wrong or [at])[0]} is not what its record says"
        done.size_bytes += sum(
            new["size_bytes"] for new in stored.stored["files"] if new.get("kept_in") == pending.name and "kept_as" not in new
        )
        part["stored"] = stored.stored
    return None


def export(
    store: FolderStore,
    pipeline: str,
    to: Union[str, Path],
    which: Union[str, list, None] = None,
    echo: Callable[[str], None] = lambda line: None,
) -> Copied:
    """Write snapshots of one pipeline from a store into a folder laid out as a store: ``<to>/snapshots/<pipeline>/``.

    :param which: None for every snapshot its owner made; ``"latest"`` for
        the newest; or a list of the ones to write, each a commit (or the
        start of one) or ``commit@made_at``.
    :raises SharingError: If the store has no snapshot of the pipeline, or
        none of those asked for; or if the folder holds an export of the
        pipeline already, or one laid out as ChartBook 0.5 laid one out.
    """
    folder = store.pipeline_path(pipeline)
    records = [r for r in store.records() if r.readable and r.made_by == "snapshot" and r.pipeline == pipeline]
    if not records:
        raise SharingError(f"The store at {store} has no snapshot of {pipeline} (its folder would be {folder.name}).")
    if which == "latest":
        records = [max(records, key=lambda r: (r.made_at, r.folder.name))]
    elif which:
        chosen = []
        for asked in which:
            commit, _, made_at = str(asked).partition("@")
            matched = [r for r in records if r.commit.startswith(commit) and (not made_at or r.made_at == made_at)]
            if not matched:
                raise SharingError(f"The store at {store} has no snapshot of {pipeline} at {asked}.")
            chosen += [r for r in matched if r not in chosen]
        records = chosen
    to = Path(to).expanduser().resolve()
    target = FolderStore(to)
    try:
        target.check_writable()
    except EarlierLayoutError:
        # An export, or a store, that ChartBook 0.5 wrote there: nothing is added to one
        raise SharingError(
            f"{to} holds a store or an export of ChartBook 0.5 ({V2_LAYOUT.pipelines}/): export into another folder."
        ) from None
    there = target.pipelines_path() / folder.name
    if there.exists() and any(there.iterdir()):
        raise SharingError(f"{there} is there already: export into another folder.")
    return copy_snapshots(records, target, echo)


def import_snapshots(store: FolderStore, source: Union[str, Path], echo: Callable[[str], None] = lambda line: None) -> Copied:
    """Copy the snapshots a folder holds into a store: an export, a store, or a pipeline's folder copied by hand.

    :raises SharingError: If the folder holds no snapshot.
    :raises EarlierLayoutError: If the store is laid out as ChartBook 0.5
        laid one out: no snapshot is made in one.
    """
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise SharingError(f"{source} is not a folder.")
    store.check_writable()
    inside = Path(os.path.realpath(store.root))
    if source == inside or source.is_relative_to(inside / store.pipelines_path().relative_to(store.root)):
        raise SharingError(f"{source} is in the store it would be imported into.")
    records = [record for folder in _pipeline_folders(source) for record in _records_in(folder)]
    if not records:
        raise SharingError(
            f"{source} holds no snapshot: a pipeline's folder from a store (its snapshots' folders, each with "
            f"_chartbook/{RECORD_FILE}), or a folder `chartbook store export` wrote."
        )
    return copy_snapshots(records, store, echo)
