"""Sending one pipeline's snapshots to someone else: ``chartbook store export`` and ``store import``.

A pipeline's folder in a store (``pipelines/<pipeline>/``) is what a person
sends a collaborator, and copied by hand into another store's ``pipelines/``
it is that pipeline's snapshots there too. These two commands do the same,
checked:

- **Export** writes chosen snapshots of one pipeline into a folder laid out
  as a store, ``<to>/pipelines/<pipeline>/``: every snapshot by default, the
  newest with ``latest``, or the ones named. Each file is kept once, in the
  first exported snapshot that has it, so the newest alone is a complete
  snapshot, every file it needs in its own folder.
- **Import** copies the snapshots of such a folder, or of a pipeline's folder
  copied by hand, into this machine's store, oldest first. Every file is
  hashed as it is copied and checked against its record; a file the store
  holds already is not copied again, and nothing there is written over.

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
    PIPELINES_DIR,
    RECORD_FILE,
    FolderStore,
    KeptRecord,
    Store,
    StoreError,
    _kept_files,
    is_snapshot_folder,
    pipeline_folder,
    read_kept_record,
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
        if path.is_file():
            found.append(read_kept_record(path))
    return sorted(found, key=lambda record: (record.made_at, record.folder.name))


def _pipeline_folders(source: Path) -> list[Path]:
    """The pipelines' folders a folder holds: a store's (``pipelines/*``), or the one it is."""
    if (source / PIPELINES_DIR).is_dir():
        return sorted(p for p in (source / PIPELINES_DIR).iterdir() if p.is_dir() and not p.name.startswith("+"))
    if any(p.is_dir() and is_snapshot_folder(p.name) for p in source.iterdir()):
        return [source]
    return sorted(p for p in source.iterdir() if p.is_dir() and any(q.is_dir() and is_snapshot_folder(q.name) for q in p.iterdir()))


def copy_snapshots(records: Iterable[KeptRecord], into: Store, echo: Callable[[str], None] = lambda line: None) -> Copied:
    """Copy snapshots, each by its record, into a store: oldest first, each file once, every byte checked.

    A snapshot the store has already (its pipeline, commit and time) is not
    copied again. One whose file is not what its record says, or whose
    record is not one a store wrote, is refused and said, and the rest go.
    """
    done = Copied()
    for record in sorted(records, key=lambda record: (record.made_at, record.folder.name)):
        moment = (record.pipeline, record.commit, record.made_at)
        if not record.readable:
            done.refused.append((str(record.path), "its record cannot be read"))
            continue
        if record.made_by != "snapshot":
            continue  # where a pin kept a clone's files: the pinning machine's, not the pipeline's
        if any(
            (kept.pipeline, kept.commit, kept.made_at) == moment
            for kept in (into.records() if hasattr(into, "records") else [])
            if kept.readable
        ):
            done.there.append(moment)
            continue
        what = f"{record.pipeline} at {record.commit[:7]}, made {record.made_at}"
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
            pending = into.begin(record.pipeline, record.commit, record.made_at)
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


def _not_to_copy(record: KeptRecord) -> Optional[str]:
    """Why a snapshot is not to be copied, by what a store asks of its record; None if it may be.

    Read as any record is (:func:`chartbook.snapshot.read`): its schema, its
    time, its pipeline's ID, its paths, and its folder's name, which must
    be its pipeline's and its commit's. A record or a folder that is a link
    is refused, as a reader refuses one.
    """
    from chartbook.snapshot import SnapshotError, read

    folder = record.folder
    if record.path.is_symlink() or (record.path.parent).is_symlink() or folder.is_symlink() or folder.parent.is_symlink():
        return "its record, or a folder holding it, is a link"
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
        kept = _kept_files(part["stored"], record.folder.parent, record.folder.name)
        if kept is None:
            return f"its record's {part.get('id', 'part')} says nothing a store could follow"
        at, single, files = kept
        # A folder sent by someone may hold a link to a file of this machine's: never followed
        inside = Path(os.path.realpath(record.folder.parent))
        for file in files:
            if file.location.is_symlink() or not Path(os.path.realpath(file.location)).is_relative_to(inside):
                return f"{file.path} is a link, or leads out of the folder it came in"
        missing = next((file for file in files if not file.location.is_file()), None)
        if missing is not None:
            return f"{missing.path} is not there"
        sources = [(file.relative, str(file.location)) for file in files]
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
    """Write snapshots of one pipeline from a store into a folder laid out as a store: ``<to>/pipelines/<pipeline>/``.

    :param which: None for every snapshot its owner made; ``"latest"`` for
        the newest; or a list of the ones to write, each a commit (or the
        start of one) or ``commit@made_at``.
    :raises SharingError: If the store has no snapshot of the pipeline, or
        none of those asked for.
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
    if (to / PIPELINES_DIR / folder.name).exists() and any((to / PIPELINES_DIR / folder.name).iterdir()):
        raise SharingError(f"{to / PIPELINES_DIR / folder.name} is there already: export into another folder.")
    return copy_snapshots(records, FolderStore(to), echo)


def import_snapshots(store: FolderStore, source: Union[str, Path], echo: Callable[[str], None] = lambda line: None) -> Copied:
    """Copy the snapshots a folder holds into a store: an export, a store, or a pipeline's folder copied by hand.

    :raises SharingError: If the folder holds no snapshot.
    """
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise SharingError(f"{source} is not a folder.")
    inside = Path(os.path.realpath(store.root))
    if source == inside or source.is_relative_to(inside / PIPELINES_DIR):
        raise SharingError(f"{source} is in the store it would be imported into.")
    records = [record for folder in _pipeline_folders(source) for record in _records_in(folder)]
    if not records:
        raise SharingError(
            f"{source} holds no snapshot: a pipeline's folder from a store (its snapshots' folders, each with "
            f"_chartbook/{RECORD_FILE}), or a folder `chartbook store export` wrote."
        )
    return copy_snapshots(records, store, echo)
