"""Moving a store from ChartBook 0.2's layout to 0.3's: ``chartbook store migrate``.

ChartBook 0.2 kept each asset as one object, a folder named by its hash
(``objects/sha256/7f/3a9c…/``), and each snapshot's record under its commit
(``snapshots/<commit>/<name>/<time>.json``). 0.3 keeps a folder for each
pipeline, a folder for each snapshot in it, and each file once
(:mod:`chartbook.store`). A store is moved once, on one machine, after every
machine that uses it has ChartBook 0.3:

1. Each record, oldest first, becomes a snapshot's folder in its pipeline's
   folder, and its files are moved there from the objects that hold them,
   by renaming, so a store in a synced folder uploads nothing again. A file
   an earlier snapshot of the pipeline holds is kept where that one has it;
   bytes that two pipelines' snapshots share are copied for the second.
2. An object no record names (0.2 pinned a ``git`` dependency with no
   record) becomes an object no pipeline owns, ``pipelines/+unowned/<hex>/``,
   which ``store gc`` clears once no lockfile names it.
3. The notes of the folders snapshots were made from move to ``origins/``;
   the notes of lockfiles, ``roots/``, stay as they are.
4. ``store.json`` says the new layout, and the old folders go. A record is
   left where 0.2 looks for them, which 0.2 reports as one it cannot read,
   so that a machine still on 0.2 says so rather than that the store is empty.

A hash a 0.2 record gives is taken as it is: only the files of a glob and
the documents, whose records list no hash for each file, are read. What is
moved is noted first in ``tmp/migrate.jsonl``, so that a migrate cut short is
run again and goes on where it stopped. The design is "Moving a store from v1
to v2" in ``docs_src/design/plan-0.3.0.md``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from chartbook import hashing
from chartbook.store import (
    MARKER_FILE,
    OBJECTS_DIR,
    ORIGINS_FILE,
    OWN_DIR,
    PIPELINES_DIR,
    SCHEMA,
    SNAPSHOTS_DIR,
    TABLES_DIR,
    TMP_DIR,
    UNOWNED_DIR,
    V1_SCHEMA,
    FolderStore,
    StoreError,
    _FolderPending,
    _HEX,
    _read_marker,
    _remove_tree,
    declared_name,
    is_record_name,
)

#: The journal of a migrate, under ``tmp/``: one line for each move, and for each record once moved.
JOURNAL = "migrate.jsonl"

#: The record left where ChartBook 0.2 looks, which it cannot read: its schema is none it knows.
SENTINEL_SCHEMA = "chartbook/snapshot/moved-to-store-v2"


class MigrateError(StoreError):
    """Raised when a store cannot be moved to this layout, saying why and what to do."""


@dataclass
class MigrationPlan:
    """What moving a store would do; nothing is moved.

    Attributes:
        root: The store's folder.
        layout: The layout its ``store.json`` names; None when it has none.
        records: The 0.2 records, in the order they are moved: oldest first.
        objects: How many objects the store holds.
        unowned: The objects no record names, which become objects no
            pipeline owns.
        size_bytes: The size of everything that is moved.
        to_read: How many bytes are read to hash them: a glob's files and the
            documents, whose records give no hash for each file.
        shared: How many objects two pipelines' records name, copied for the
            second.
        done: Records already moved by a migrate that was cut short.
    """

    root: Path
    layout: Optional[str]
    records: list = field(default_factory=list)
    objects: int = 0
    unowned: list = field(default_factory=list)
    size_bytes: int = 0
    to_read: int = 0
    shared: int = 0
    done: int = 0

    @property
    def needed(self) -> bool:
        """Whether there is anything to move: the store is laid out as 0.2 laid one out."""
        return self.layout == V1_SCHEMA or (self.layout is None and (self.records or self.objects))


def _object(root: Path, content_hash: str) -> Optional[Path]:
    """The folder of a 0.2 object, if the hash is one."""
    algorithm, _, digest = str(content_hash).partition(":")
    if algorithm != hashing.ALGORITHM or not _HEX.match(digest):
        return None
    return root / OBJECTS_DIR / algorithm / digest[:2] / digest[2:]


def _records(root: Path) -> list[tuple[Path, dict]]:
    """Every 0.2 record of a store, read, oldest first.

    :raises MigrateError: Naming a record that cannot be read: nothing is
        moved while one is in doubt (a sync that has not finished, most likely).
    """
    found = []
    folder = root / SNAPSHOTS_DIR
    for path in sorted(folder.glob("*/*/*.json")) if folder.is_dir() else ():
        if not is_record_name(path.name):
            continue  # a sync service's copy of one, which 0.2 passed over too
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema") == SENTINEL_SCHEMA:
                continue
            if document.get("schema") != "chartbook/snapshot/v1":
                raise ValueError(f"its schema is {document.get('schema')!r}")
            document["code"]["commit"], document["made_at"], document["root"]  # noqa: B018 - what is needed
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise MigrateError(
                f"Cannot read the snapshot record {path}: {error}. A sync that has not finished is the likeliest "
                f"cause: run this again once it has. If it stays unreadable, remove it (it is one snapshot's "
                f"record) and run this again. Nothing was moved."
            ) from None
        found.append((path, document))
    # Oldest first, so that each file goes to the first snapshot that had it
    found.sort(key=lambda pair: (pair[1]["made_at"], pair[0].name))
    return found


def _parts(document: dict) -> list[dict]:
    """What a record names in the store: its assets, its index and its documents."""
    parts = [record for record in document.get("records") or [] if isinstance(record, dict)]
    return parts + [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]


def plan(root) -> MigrationPlan:
    """What moving the store at *root* would do. Nothing is moved.

    :raises MigrateError: If a record cannot be read, or the store has a
        layout this version neither reads nor moves.
    """
    root = Path(os.path.abspath(Path(root).expanduser()))
    try:
        layout = _read_marker(root / MARKER_FILE)
    except FileNotFoundError:
        layout = None
    except (OSError, ValueError, AttributeError) as error:
        raise MigrateError(f"Cannot read {root / MARKER_FILE}: {error}") from None
    found = MigrationPlan(root, layout)
    if layout not in (None, V1_SCHEMA):
        if layout != SCHEMA:
            raise MigrateError(f"The store at {root} has the layout {layout!r}, which this version does not move.")
        return found
    journal = _Journal(root)
    records = _records(root)
    found.records = [path for path, _ in records]
    found.done = sum(1 for path, _ in records if journal.written(path))
    objects = root / OBJECTS_DIR / hashing.ALGORITHM
    held = {
        hashing.format_hash(prefix.name + rest.name)
        for prefix in (objects.iterdir() if objects.is_dir() else ())
        if prefix.is_dir()
        for rest in prefix.iterdir()
        if rest.is_dir() and _HEX.match(prefix.name + rest.name)
    }
    found.objects = len(held)
    owners: dict = {}
    for path, document in records:
        for part in _parts(document):
            if isinstance(part.get("content_hash"), str):
                owners.setdefault(part["content_hash"], set()).add(document["root"])
                if part in (document.get("documents"),) or _is_glob(part):
                    found.to_read += _size(_object(root, part["content_hash"]))
    found.unowned = sorted(held - set(owners))
    found.shared = sum(1 for content_hash, pipelines in owners.items() if len(pipelines) > 1 and content_hash in held)
    found.size_bytes = sum(_size(_object(root, content_hash)) for content_hash in held)
    return found


def _size(folder: Optional[Path]) -> int:
    if folder is None or not folder.is_dir():
        return 0
    return sum(file.stat().st_size for file in hashing.directory_files(folder) if file.is_file())


def _is_glob(part: dict) -> bool:
    from chartbook.utils import is_glob_pattern

    location = part.get("location") or {}
    return location.get("kind") == "file" and is_glob_pattern(location.get("path", ""))


def _plain(declared: str) -> str:
    """A declared path as a place in a pipeline's folder: ``/`` between parts, no ``./``."""
    parts = [part for part in str(declared).replace("\\", "/").split("/") if part not in ("", ".")]
    return "/".join(parts)


class _Journal:
    """What a migrate has moved, noted before it is moved: so one cut short goes on where it stopped."""

    def __init__(self, root: Path):
        self.path = root / TMP_DIR / JOURNAL
        self.root = root
        self.moved: dict[str, str] = {}
        self.records: dict[str, str] = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # the last line of a migrate cut short mid-write
            if "from" in entry:
                self.moved[entry["from"]] = entry["to"]
            elif "record" in entry:
                self.records[entry["record"]] = entry["into"]

    def _note(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _name(self, path) -> str:
        return Path(path).relative_to(self.root).as_posix()

    def move(self, source: Path, target: Path) -> None:
        self.moved[self._name(source)] = self._name(target)
        self._note({"from": self._name(source), "to": self._name(target)})

    def written(self, record: Path) -> bool:
        into = self.records.get(self._name(record))
        return into is not None and (self.root / into).is_file()

    def wrote(self, record: Path, into: Path) -> None:
        self.records[self._name(record)] = self._name(into)
        self._note({"record": self._name(record), "into": self._name(into)})

    def where(self, file: Path) -> Path:
        """Where a file of a 0.2 object is now: where it was, or where a migrate moved it."""
        if os.path.lexists(file):
            return file
        moved = self.moved.get(self._name(file))
        return self.root / moved if moved is not None else file


class _Moving(_FolderPending):
    """A snapshot being written by a migrate: a file of a 0.2 object is moved into place, not copied."""

    def __init__(self, store, pipeline, commit, made_at, journal: _Journal):
        super().__init__(store, pipeline, commit, made_at, None, "snapshot")
        self.journal = journal

    def _write_file(self, source: str, target: Path, links: tuple) -> tuple[str, str]:
        objects = self.store.root / OBJECTS_DIR
        if Path(source).is_relative_to(objects) and not os.path.islink(source):
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(target):
                raise StoreError(f"{target} is in the store already.")
            self.journal.move(Path(source), target)
            os.rename(source, target)
            os.chmod(target, 0o444)
            known = self.known.get(source)
            return known or hashing.format_hash(hashing._file_hex(target)), "move"
        return super()._write_file(source, target, links)


class _Opened(FolderStore):
    """The store being moved: read as this layout, whatever its marker says, until the marker is switched."""

    def _check_layout(self, create: bool = False) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


def run(root, echo: Callable[[str], None] = lambda line: None) -> MigrationPlan:
    """Move the store at *root* to this layout, and return what was planned.

    :raises MigrateError: If the store cannot be moved, saying why; what was
        moved before stays moved, and running this again goes on.
    """
    found = plan(root)
    if not found.needed:
        return found
    root = found.root
    store = _Opened(root)
    journal = _Journal(root)
    records = _records(root)
    for number, (path, document) in enumerate(records, 1):
        if journal.written(path):
            continue
        echo(f"[{number}/{len(records)}] {document['root']} at {document['code']['commit'][:7]}, made {document['made_at']}")
        _move_record(store, journal, path, document)
    for content_hash in found.unowned:
        folder = _object(root, content_hash)
        target = root / PIPELINES_DIR / UNOWNED_DIR / content_hash.split(":", 1)[1]
        if folder.is_dir() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            journal.move(folder, target)
            os.rename(folder, target)
    _move_origins(root, store)
    _switch(root)
    return found


def _move_record(store: _Opened, journal: _Journal, path: Path, document: dict) -> None:
    """Make one 0.2 record a snapshot's folder of this layout, its files moved into place."""
    from chartbook.snapshot import SCHEMA as RECORD_SCHEMA, materialized_name

    root = store.root
    pending = _Moving(store, document["root"], document["code"]["commit"], document["made_at"], journal)
    written = dict(document, schema=RECORD_SCHEMA)
    written["records"] = []
    try:
        for part in [record for record in document.get("records") or [] if isinstance(record, dict)]:
            written["records"].append(_placed(pending, journal, root, part, "record", materialized_name))
        for name in ("index", "documents"):
            if isinstance(document.get(name), dict):
                written[name] = _placed(pending, journal, root, document[name], name, materialized_name)
        into = pending.write(written)
    except BaseException:
        if not pending.placed:
            pending.discard()
        raise
    journal.wrote(path, into)


def _placed(pending: _Moving, journal: _Journal, root: Path, part: dict, what: str, materialized_name) -> dict:
    """One asset of a record, its files put in the snapshot being written; the record with where they are kept."""
    content_hash = part.get("content_hash")
    folder = _object(root, content_hash) if isinstance(content_hash, str) else None
    if folder is None:
        return part  # not built, or a hash that is none
    location = part.get("location") or {}
    listed = part.get("files") if isinstance(part.get("files"), list) else None
    known = {}
    if what == "index":
        place, single, names = f"{OWN_DIR}/index.json", True, ["index.json"]
    elif what == "documents":
        place, single, names = "", False, [name for name in part.get("files") or [] if isinstance(name, str)]
    elif location.get("kind") in ("table", "query"):
        place, single, names = f"{TABLES_DIR}/{materialized_name(part)}", True, [materialized_name(part)]
    elif _is_glob(part):
        place, single = _plain(str(hashing.glob_root(location.get("path", "")))), False
        names = None
    elif listed is not None:
        place, single = _plain(location.get("path", "")), False
        names = [entry["path"] for entry in listed if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
        known = {entry["path"]: entry.get("content_hash") for entry in listed if isinstance(entry, dict)}
    else:
        place, single = _plain(location.get("path", "")), True
        names = [declared_name(location.get("path", "")) or ""]
    if names is None:
        # A glob's record lists no file: what the object held, as it was hashed
        names = sorted(
            Path(os.path.relpath(file, folder)).as_posix() for file in hashing.directory_files(folder)
        ) if folder.is_dir() else []
        names += [name for name in _moved_under(journal, folder) if name not in names]
    if single and names and not os.path.lexists(journal.where(folder / names[0])):
        # One file under another name than the declared one: the one the object holds
        held = [file.name for file in folder.iterdir() if file.is_file()] if folder.is_dir() else []
        names = held[:1] or names
    sources = [(name, str(journal.where(folder.joinpath(*name.split("/"))))) for name in names]
    if not sources or not all(os.path.lexists(source) for _, source in sources):
        return part  # an object 0.2 lost: the record names it, as it did
    for (name, source) in sources:
        if single:
            pending.known[source] = content_hash
        elif known.get(name):
            pending.known[source] = known[name]
    if single:
        stored = pending.put_listed([(declared_name(place) or names[0], sources[0][1])], place, True)
    else:
        stored = pending.put_listed(sources, place, False)
    if stored.content_hash != content_hash:
        return part  # its object was not what its name said: left for `store verify`, and not followed
    return {**part, "stored": stored.stored}


def _moved_under(journal: _Journal, folder: Path) -> list[str]:
    """The names a migrate moved out of an object's folder already, for a record that names it again."""
    prefix = journal._name(folder) + "/"
    return sorted(name[len(prefix):] for name in journal.moved if name.startswith(prefix))


def _move_origins(root: Path, store: _Opened) -> None:
    """The 0.2 notes of the folders each pipeline's records were made from, into ``origins/``."""
    folder = root / SNAPSHOTS_DIR
    for note in sorted(folder.glob(f"*/*/{ORIGINS_FILE}")) if folder.is_dir() else ():
        commit, name = note.parent.parent.name, note.parent.name
        try:
            lines = [line for line in note.read_text(encoding="utf-8").splitlines() if line]
            for line in lines:
                store.note_origin(commit, name, line)
        except (OSError, ValueError):
            continue


def _switch(root: Path) -> None:
    """Say the new layout, and let the old go: a record ChartBook 0.2 cannot read is left where it looks."""
    temporary = root / f"{MARKER_FILE}.migrate.tmp"
    temporary.write_text(json.dumps({"schema": SCHEMA}) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, root / MARKER_FILE)
    for name in (OBJECTS_DIR, SNAPSHOTS_DIR, "builds"):
        if (root / name).exists():
            _remove_tree(root / name)
    sentinel = root / SNAPSHOTS_DIR / ("0" * 40) / "_top" / "20261028T000000.000000Z.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(
        json.dumps({
            "schema": SENTINEL_SCHEMA,
            "note": "This store was moved to the layout of ChartBook 0.3 (chartbook/store/v2). Use ChartBook 0.3 or later with it.",
        }, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        (root / TMP_DIR / JOURNAL).unlink()
    except OSError:
        pass
