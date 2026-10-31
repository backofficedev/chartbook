"""Verified copying between Store implementations, without shared physical references."""
from __future__ import annotations
import json
from pathlib import Path
from chartbook import snapshot
from chartbook.store import StoreError, TidyError


def copy_snapshot(taken, source, target):
    existing = [snapshot.read(p) for p in target.all_snapshot_files() + target.pinned_snapshot_files()]
    for held in existing:
        if (held.pipeline, held.commit, held.made_at) == (taken.pipeline, taken.commit, taken.made_at):
            def logical(value):
                raw = value.to_document()
                for part in [*raw.get("records", []), raw.get("index"), raw.get("documents")]:
                    if isinstance(part, dict):
                        part.pop("stored", None)
                return raw
            if logical(held) != logical(taken):
                raise StoreError(f"Conflicting snapshot in target: {taken.pipeline} at {taken.commit}")
            problems = target.verify(taken.hashes())
            if problems:
                raise StoreError(f"Target snapshot failed verification: {problems[0]}")
            return held.path
    document = json.loads(Path(taken.path).read_text(encoding="utf-8"))
    pending = target.begin(taken.pipeline, taken.commit, taken.made_at, made_by=document.get("made_by", "snapshot"))
    try:
        parts = list(document.get("records", [])) + [document.get("documents"), document.get("index")]
        for part in parts:
            if not isinstance(part, dict) or not part.get("content_hash"):
                continue
            stored = part.get("stored")
            if not isinstance(stored, dict):
                raise StoreError("Snapshot has no physical file listing; migrate its source store first")
            single = stored.get("single", False)
            files = stored.get("files", [])
            if not files:
                raise StoreError("Snapshot has an empty file listing")
            name = Path(files[0]["path"]).name if single else None
            held = Path(source.get(part["content_hash"], taken.pipeline, name=name))
            place = files[0]["path"] if single else stored.get("at", "")
            result = pending.put(held / name if single else held, place=place)
            if result.content_hash != part["content_hash"]:
                raise StoreError(f"Copy of {part.get('id', 'documents')} failed hash verification")
            part["stored"] = result.stored
        path = pending.write(document)
        for origin in source.origins(taken.commit, snapshot.record_name(taken.subdirectory)):
            target.note_origin(taken.commit, snapshot.record_name(taken.subdirectory), origin)
        return path
    except BaseException:
        pending.discard()
        raise


def move(pipeline, stores, to, *, keep=False, dry_run=False, route=True):
    from chartbook.identity import validate_pipeline_id
    validate_pipeline_id(pipeline)
    target_entry = stores.named(to)
    stores.for_writing(pipeline, [to])
    target = target_entry.store
    sources = []
    total = 0
    for entry in stores.entries:
        if entry is target_entry or not entry.reachable:
            continue
        found = [snapshot.read(p) for p in entry.store.all_snapshot_files() + entry.store.pinned_snapshot_files()]
        chosen = [t for t in found if t.pipeline == pipeline]
        if chosen and entry.read_only and not keep:
            raise StoreError(f"Source store {entry.name!r} is read-only; use --keep")
        if chosen:
            sources.append((entry, chosen))
            total += sum(entry.store.size_of(h) for h in set().union(*(t.hashes() for t in chosen)))
    if not sources:
        held = [snapshot.read(p) for p in target.all_snapshot_files() + target.pinned_snapshot_files()]
        if not any(t.pipeline == pipeline for t in held):
            raise StoreError(f"No reachable store has a snapshot of {pipeline!r}")
    if dry_run:
        return sum(len(t) for _, t in sources), total
    # Copy and verify every snapshot and note before removing anything.
    for entry, chosen in sources:
        for taken in chosen:
            copy_snapshot(taken, entry.store, target)
            for origin in entry.store.origins(taken.commit, snapshot.record_name(taken.subdirectory)):
                target.note_origin(taken.commit, snapshot.record_name(taken.subdirectory), origin)
        moments = {(t.commit, t.made_at) for t in chosen}
        hashes = set().union(*(t.hashes() for t in chosen))
        for root in entry.store.roots():
            if hashes.intersection(root.hashes) or moments.intersection(root.snapshots or ()):
                previous = target.root_of(root.lockfile, root.machine)
                target.add_root(root.lockfile, set(root.hashes) | set(previous.hashes if previous else ()),
                                set(root.snapshots or ()) | set(previous.snapshots or () if previous else ()), root.machine,
                                set(root.labelled or ()) | set(previous.labelled or () if previous else ()))
        problems = target.verify(hashes)
        if problems:
            raise StoreError(f"Target failed verification; source retained: {problems[0]}")
    stuck = []
    if not keep:
        for entry, chosen in sources:
            # Oldest first lets the store preserve files referenced by remaining snapshots.
            for taken in sorted(chosen, key=lambda t: t.made_at):
                entry.store.remove_snapshot(taken.path)
            # Clearing a record leaves its files for a tidy; this pipeline's go now, and no other's
            try:
                entry.store.tidy_pipeline(pipeline)
            except TidyError as error:
                stuck.append(str(error))
    if route and stores.catalog:
        from chartbook.catalog_config import route as set_route
        set_route(pipeline, [to], stores.catalog)
    count = sum(len(t) for _, t in sources)
    if stuck:
        raise StoreError(f"Moved {count} snapshot(s) of {pipeline} to {to}, but some of their files are left behind. {' '.join(stuck)}")
    return count, total
