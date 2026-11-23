"""Verified copying between Store implementations, without shared physical references."""
from __future__ import annotations
import json
import os
from pathlib import Path
from chartbook import snapshot
from chartbook.store import BuiltOnGoneError, PathTooLongError, StoreError


class NotWholeThere(StoreError):
    """A snapshot that the store it was to be copied to has already, and not whole: a file of its own there is missing, or has other bytes.

    Nothing is written over it, since a snapshot's folder is not changed
    once its record is written. Whoever was copying says what that means
    for them (``store move``, ``store import``, a snapshot sent to several
    stores). ``str()`` says which store, which snapshot and which file.

    Attributes:
        taken: The snapshot that was to be copied.
        store: The store that has it already.
        record: Its record there.
        problems: What is wrong with its own files there, as ``store verify`` says it.
    """

    def __init__(self, taken, store, record, problems: list):
        self.taken, self.store, self.record, self.problems = taken, store, Path(record), problems
        more = f" (and {len(problems) - 1} more of its files)" if len(problems) > 1 else ""
        super().__init__(
            f"The store at {store} has the snapshot of {taken.pipeline} made {taken.made_at} already, in "
            f"{self.record.parent.parent.name}, and not whole: {problems[0].message}{more}"
        )


def _complete_first(taken_and_where):
    """A sort key for snapshots of one store: each complete one, then the increments, so that what an increment builds on is there before it; oldest first in each."""
    taken, source = taken_and_where
    asked = getattr(source, "builds_on", None)
    return (asked is not None and asked(taken.path) is not None, taken.made_at)


def _builds_on_there(taken, source, target, whole):
    """The folder name, in the target, of the complete snapshot that a snapshot kept as an increment in the source builds on; None where the target has none, or keeps no increments, and it is written complete there."""
    asked = getattr(source, "builds_on", None)
    complete = asked(taken.path) if asked is not None else None
    if complete is None or getattr(target, "increments_path", lambda: None)() is None:
        return None
    try:
        on = snapshot.read(complete)
    except (snapshot.SnapshotError, OSError):
        return None  # gone from the source: every file of the increment that is left is copied, complete
    for record in target.records():
        # A complete one by what its record is: not one that keeps files in other folders (0.5's kind, copied in by hand)
        if record.complete and (record.pipeline, record.commit, record.made_at) == (on.pipeline, on.commit, on.made_at):
            # Only on a complete one written in this run, or read and hashed in it: never on files taken on trust
            if str(record.path) not in whole and not target.verify_snapshot(record.path):
                whole.add(str(record.path))
            if str(record.path) not in whole:
                return None
            return record.folder.name
    return None


def copy_snapshot(taken, source, target, complete=False, whole=None, decides=False):
    """Copy one snapshot into another store, each file checked by its hash as it is written; its record there.

    One the target has already is left as it is, and is there only if its
    own files are whole, read and hashed (:class:`NotWholeThere` otherwise).

    :param complete: Write it complete, whatever it is in the source.
    :param decides: For a snapshot that is being made and sent to several
        stores (:func:`chartbook.snapshot.make`): the target decides for
        itself whether it keeps it complete or as an increment, from its
        own snapshots, by the one rule
        (:func:`chartbook.snapshot.to_be_kept`). Without it a copy keeps
        the form it has in the source (``store move``).
    """
    whole = whole if whole is not None else set()  # the complete snapshots in the target that this run wrote, or read and hashed
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
            # There only if the target's own snapshot of that moment is whole, each of its own files read
            # and hashed where its record says it is: another snapshot's copy of the same bytes, or a
            # file of the right size and other bytes, does not make it so
            problems = target.verify_snapshot(held.path, taken.hashes())
            if problems:
                raise NotWholeThere(taken, target, held.path, problems)
            whole.add(str(held.path))
            return held.path
    document = json.loads(Path(taken.path).read_text(encoding="utf-8"))
    # Where the target decides, its kind is said once every file of it is put, as for the store it was made in
    by_rule = (
        decides and not complete and document.get("made_by", "snapshot") == "snapshot"
        and getattr(target, "increments_path", lambda: None)() is not None
    )
    # Otherwise it keeps its form: an increment in the source is one in the target, on the same complete snapshot,
    # where the target has that one; where it has not, it is written complete, every file being at hand
    on = None if complete or by_rule else _builds_on_there(taken, source, target, whole)
    # It carries no count of what the increments on that snapshot have added up to: that is of what snapshots
    # made in the target copied, and the next one made there counts from what the target's own increments carry
    pending = target.begin(
        taken.pipeline, taken.commit, taken.made_at, made_by=document.get("made_by", "snapshot"),
        **({"builds_on": on} if on is not None else {}), **({"undecided": True} if by_rule else {}),
    )
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
            # From the snapshot's own copy, where it has it whole
            kept = source.files(part["content_hash"], taken.pipeline, name=name, snapshot=(taken.commit, taken.made_at))
            place = files[0]["path"] if single else stored.get("at", "")
            # Each file from where the source keeps it, by its path inside the asset: no folder is gathered
            result = pending.put_listed([(file.relative, str(file.location)) for file in kept.files], place, single)
            if result.content_hash != part["content_hash"]:
                raise StoreError(f"Copy of {part.get('id', 'documents')} failed hash verification")
            part["stored"] = result.stored
        if by_rule:
            decided = snapshot.to_be_kept(target, taken)
            if decided.increment:
                pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
        try:
            path = pending.write(document)
        except BuiltOnGoneError:
            # What it builds on went from the target meanwhile: written complete
            pending.discard()
            return copy_snapshot(taken, source, target, complete=True, whole=whole)
        for origin in source.origins(taken.commit, snapshot.record_name(taken.subdirectory)):
            target.note_origin(taken.commit, snapshot.record_name(taken.subdirectory), origin)
        if getattr(pending, "builds_on", None) is None:
            whole.add(str(path))
        return path
    except PathTooLongError:
        was_increment = on is not None or getattr(pending, "builds_on", None) is not None
        pending.discard()
        if not was_increment:
            raise  # it does not fit complete either
        # A file of its own does not fit under increments/, one letter longer than snapshots/: written complete
        return copy_snapshot(taken, source, target, complete=True, whole=whole)
    except BaseException:
        pending.discard()
        raise


def _same_place(a, b):
    """Whether two stores are one: two names for a folder (letter case, a link) or for a bucket."""
    if getattr(a, "bucket", None) is not None and getattr(b, "bucket", None) is not None:
        def place(store):
            options = getattr(store, "options", None) or {}
            endpoint = str(options.get("endpoint") or "").rstrip("/")  # none is AWS
            return store.bucket, str(getattr(store, "prefix", "") or "").strip("/"), endpoint
        return place(a) == place(b)
    first, second = getattr(a, "root", None), getattr(b, "root", None)
    if isinstance(first, Path) and isinstance(second, Path):
        try:
            return os.path.samefile(first, second)
        except OSError:
            return False
    return str(a) == str(b)


def _check_writable(store):
    """Stop before anything is copied if a store is one this ChartBook reads and does not write (a folder store of 0.5)."""
    check = getattr(store, "check_writable", None)
    if check is not None:
        check()


def move(pipeline, stores, to, *, keep=False, dry_run=False, route=True):
    from chartbook.identity import validate_pipeline_id
    validate_pipeline_id(pipeline)
    target_entry = stores.named(to)
    stores.for_writing(pipeline, [to])
    target = target_entry.store
    _check_writable(target)
    sources = []
    total = 0
    for entry in stores.entries:
        if entry is target_entry or not entry.reachable:
            continue
        found = [snapshot.read(p) for p in entry.store.all_snapshot_files() + entry.store.pinned_snapshot_files()]
        chosen = [t for t in found if t.pipeline == pipeline]
        if chosen and _same_place(entry.store, target):
            # Its records would be taken for the copies, then removed with their files
            raise StoreError(f"Stores {entry.name!r} and {to!r} are one store under two names; nothing was moved")
        if chosen and entry.read_only and not keep:
            raise StoreError(f"Source store {entry.name!r} is read-only; use --keep")
        if chosen and not keep:
            _check_writable(entry.store)  # nothing is removed from a store of 0.5: found out before anything is copied
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
    whole: set = set()
    for entry, chosen in sources:
        for taken in sorted(chosen, key=lambda taken: _complete_first((taken, entry.store))):
            try:
                copy_snapshot(taken, entry.store, target, whole=whole)
            except NotWholeThere as error:
                raise StoreError(
                    f"{error}. Nothing was removed from where it came from. If a sync is still bringing it, wait "
                    f"for the sync to finish and move again; `chartbook store verify` there lists everything "
                    f"missing or damaged."
                ) from None
            for origin in entry.store.origins(taken.commit, snapshot.record_name(taken.subdirectory)):
                target.note_origin(taken.commit, snapshot.record_name(taken.subdirectory), origin)
        from chartbook.store import _snapshot_triple

        moments = {(t.commit, t.made_at) for t in chosen}
        hashes = set().union(*(t.hashes() for t in chosen))
        for root in entry.store.roots():
            noted = {_snapshot_triple(item)[1:] for item in (root.snapshots or ())}
            if hashes.intersection(root.hashes) or moments.intersection(noted):
                raw_lockfile = root.written or root.lockfile
                previous = target.root_of(raw_lockfile, root.machine)
                target.add_root(
                    raw_lockfile,
                    set(root.hashes) | set(previous.hashes if previous else ()),
                    set(root.snapshots or ()) | set(previous.snapshots or () if previous else ()),
                    root.machine,
                    set(root.labelled or ()) | set(previous.labelled or () if previous else ()),
                    host=root.host or (previous.host if previous else ""),
                    node=root.node or (previous.node if previous else ""),
                )
        # Each snapshot was verified where it is: one written just now by each file's hash as it was written,
        # one that was there already by reading its own files (copy_snapshot). And now every asset of them,
        # by its hash, as a read of this pipeline finds it in the target: nothing is removed from the source
        # for an asset the target's records name and do not hold
        problems = target.verify(sorted(hashes), pipeline)
        if problems:
            raise StoreError(
                f"The store at {target} does not hold {pipeline} whole after the copy: {problems[0].content_hash[:19]}… "
                f"{problems[0].message}. Nothing was removed from where it came from."
            )
    if not keep:
        for entry, chosen in sources:
            # Oldest first lets a store that keeps each file once (a bucket) preserve files referenced by remaining snapshots.
            # Increments first: what one builds on is there for as long as it is
            for taken in sorted(chosen, key=lambda t: (not _complete_first((t, entry.store))[0], t.made_at)):
                entry.store.remove_snapshot(taken.path)
    if route and stores.catalog:
        from chartbook.catalog_config import route as set_route
        set_route(pipeline, [to], stores.catalog)
    count = sum(len(t) for _, t in sources)
    stuck = []
    if not keep and sources:
        # Clearing a record leaves its files for a tidy: this pipeline's go now, and no other's,
        # once the target is seen to hold every record still
        try:
            held = {(t.commit, t.made_at) for t in map(snapshot.read, target.all_snapshot_files() + target.pinned_snapshot_files())
                    if t.pipeline == pipeline}
        except (snapshot.SnapshotError, ValueError, StoreError, OSError) as error:
            raise StoreError(f"Moved {count} snapshot(s) of {pipeline}, but {to!r} could not be read again ({error}); "
                             f"the sources' files are left as they are") from None
        missing = [t for _, chosen in sources for t in chosen if (t.commit, t.made_at) not in held]
        if missing:
            raise StoreError(f"Moved {count} snapshot(s) of {pipeline}, but {to!r} no longer lists one made {missing[0].made_at}; "
                             f"the sources' files are left as they are")
        for entry, _ in sources:
            try:
                entry.store.tidy_pipeline(pipeline)
            except (StoreError, OSError) as error:
                stuck.append(f"{entry.name}: {error}")
    if stuck:
        raise StoreError(f"Moved {count} snapshot(s) of {pipeline} to {to}, but some of their files are left behind. {' '.join(stuck)}")
    return count, total
