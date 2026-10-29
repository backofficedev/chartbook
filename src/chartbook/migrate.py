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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from chartbook import hashing
from chartbook.store import (
    _check_length,
    plain_parts,
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
        lost: The parts of records whose objects 0.2 had lost already: the
            records name them still, as they did.
        unfinished: Whether a migrate cut short after it switched the
            marker left the old folders: the next run removes them.
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
    lost: int = 0
    unfinished: bool = False

    @property
    def needed(self) -> bool:
        """Whether there is anything to move: the store is laid out as 0.2 laid one out, or a migrate was cut short."""
        return self.unfinished or self.layout == V1_SCHEMA or bool(self.records or self.objects)


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
            _check_record(document)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise MigrateError(
                f"Cannot read the snapshot record {path}: {error}. A sync that has not finished is the likeliest "
                f"cause: run this again once it has. If it stays unreadable, remove it (it is one snapshot's "
                f"record) and run this again. Nothing was moved."
            ) from None
        found.append((path, document))
    # Oldest first, so that each file goes to the first snapshot that had it
    found.sort(key=lambda pair: (pair[1]["made_at"], pair[0].name))
    return found


def _check_record(document: dict) -> None:
    """Refuse a record that names what no store of 0.2 wrote: a commit, a time, an ID or a path a reader would not take.

    A record may be anyone's who could write to the store, and migrate makes
    a path of each name in it.

    :raises ValueError: Saying what is wrong.
    """
    from chartbook.identity import validate_pipeline_id
    from chartbook.snapshot import _COMMIT, _MADE_AT, improper_path

    if not isinstance(document["code"]["commit"], str) or not _COMMIT.match(document["code"]["commit"]):
        raise ValueError("its commit is not a full commit hash")
    if not isinstance(document["made_at"], str) or not _MADE_AT.match(document["made_at"]):
        raise ValueError(f"its made_at, {document['made_at']!r}, is not a time as a snapshot writes one")
    validate_pipeline_id(document["root"])
    for record in document.get("records") or []:
        why = improper_path(record) if isinstance(record, dict) else "is not a record"
        location = (record.get("location") or {}) if isinstance(record, dict) else {}
        if not why and location.get("kind") == "file" and _plain(location.get("path", "")) and plain_parts(_plain(location.get("path", ""))) is None:
            why = f"has the path {location.get('path')!r}, which is not a plain path inside its pipeline's folder"
        if why:
            raise ValueError(f"its record for {record.get('id') if isinstance(record, dict) else record!r} {why}")
    documents = document.get("documents")
    if isinstance(documents, dict):
        for name in documents.get("files") or []:
            if not isinstance(name, str) or plain_parts(name) is None:
                raise ValueError(f"its documents list {name!r}, which is not a plain path inside its pipeline's folder")


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
        if (root / TMP_DIR / JOURNAL).exists():
            # Switched, and cut short before the old folders went: the journal is removed last
            found.unfinished = True
            return found
        if not (root / OBJECTS_DIR).is_dir() and not any(_records(root)):
            return found
        # Says v2, and holds 0.2's folders: a store.json written over a 0.2 store's that had not
        # arrived, or was removed. What is in them is moved as any 0.2 store's is
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
    found.lost = sum(
        1 for _, document in records for part in _parts(document)
        if isinstance(part.get("content_hash"), str) and part["content_hash"] not in held
    )
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

    def _write_file(self, source: str, target: Path, links: tuple, expect: Optional[str] = None) -> tuple[str, str]:
        objects = self.store.root / OBJECTS_DIR
        if Path(source).is_relative_to(objects) and not os.path.islink(source):
            _check_length(target)
            self._inside(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(target):
                raise StoreError(f"{target} is in the store already.")
            self.journal.move(Path(source), target)
            # Placed before it is moved: a migrate cut short now never takes this folder back
            self.placed = True
            os.rename(source, target)
            try:
                os.chmod(target, 0o444)
            except OSError:
                pass  # a disk that keeps no such mode: the file is the store's all the same
            known = self.known.get(source)
            return known or hashing.format_hash(hashing._file_hex(target)), "move"
        return super()._write_file(source, target, links, expect)

    def discard(self) -> None:
        """A migrate never takes back what it moved: the journal says where it is, and the next run goes on."""


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
    if found.unfinished:
        _switch(root)  # cut short after the marker was switched: what is left of the old goes
        return found
    store = _Opened(root)
    journal = _Journal(root)
    records = _records(root)
    prepared = _prepare(root, journal, records)
    for number, (path, document) in enumerate(records, 1):
        if journal.written(path):
            continue
        echo(f"[{number}/{len(records)}] {document['root']} at {document['code']['commit'][:7]}, made {document['made_at']}")
        _move_record(store, journal, path, document, prepared)
    for content_hash in found.unowned:
        folder = _object(root, content_hash)
        target = root / PIPELINES_DIR / UNOWNED_DIR / content_hash.split(":", 1)[1]
        if folder.is_dir() and not target.exists():
            _check_length(target / ("x" * 12))
            target.parent.mkdir(parents=True, exist_ok=True)
            journal.move(folder, target)
            os.rename(folder, target)
    _move_origins(root, store)
    _switch(root)
    return found


@dataclass
class _Part:
    """One asset of a 0.2 record, as it is to be moved: where it goes in its pipeline, and each of its files with its hash."""

    place: str
    single: bool
    names: list
    known: dict


#: A name a sync service gives the second of two copies: ``part-0 (1).parquet``.
_SYNC_COPY = re.compile(r" \([0-9]+\)(\.[^/]*)?$")


def _shape(part: dict, what: str) -> tuple[str, bool, Optional[list], dict]:
    """Where a part goes in its pipeline's folder, whether it is one file, its files' names in its object (None for a glob's, which its record does not list), and the hashes its record gives."""
    from chartbook.snapshot import materialized_name

    location = part.get("location") or {}
    listed = part.get("files") if isinstance(part.get("files"), list) else None
    if what == "index":
        return f"{OWN_DIR}/index.json", True, ["index.json"], {"index.json": part["content_hash"]}
    if what == "documents":
        return "", False, [name for name in part.get("files") or [] if isinstance(name, str)], {}
    if location.get("kind") in ("table", "query"):
        name = materialized_name(part)
        return f"{TABLES_DIR}/{name}", True, [name], {name: part["content_hash"]}
    if _is_glob(part):
        return _plain(str(hashing.glob_root(location.get("path", "")))), False, None, {}
    if listed is not None:
        names = [entry["path"] for entry in listed if isinstance(entry, dict) and isinstance(entry.get("path"), str)]
        return _plain(location.get("path", "")), False, names, {
            entry["path"]: entry.get("content_hash") for entry in listed if isinstance(entry, dict) and isinstance(entry.get("content_hash"), str)
        }
    name = declared_name(location.get("path", "")) or ""
    return _plain(location.get("path", "")), True, [name], {name: part["content_hash"]}


def _prepare(root: Path, journal: _Journal, records: list) -> dict:
    """Check every object each record names before anything is moved, and work out each part's files and hashes.

    An object is whole as its record has it (each file's size), and a
    glob's files and the documents, whose records list no hash for each
    file, are hashed where they are and must make the asset's hash; a sync
    service's copy among them (``x (1).parquet``) is left out when that
    makes it. An object 0.2 had lost already is passed over: the record
    names it still, as it did.

    :raises MigrateError: Listing each object that is not whole or not what
        its name says: nothing is moved.
    """
    prepared: dict = {}
    problems: list = []
    for path, document in records:
        if journal.written(path):
            continue
        for index, (what, part) in enumerate(_tagged(document)):
            content_hash = part.get("content_hash")
            folder = _object(root, content_hash) if isinstance(content_hash, str) else None
            if folder is None:
                continue
            if not folder.is_dir() and not _moved_under(journal, folder):
                continue  # lost in 0.2 already
            place, single, names, known = _shape(part, what)
            if place and plain_parts(place) is None:
                problems.append(f"{part.get('id', what)} in {path.name}: its place {place!r} is not a plain path")
                continue
            if names is None:
                names = sorted(
                    Path(os.path.relpath(file, folder)).as_posix() for file in hashing.directory_files(folder)
                ) if folder.is_dir() else []
                names += [name for name in _moved_under(journal, folder) if name not in names]
            if single and names and not os.path.lexists(journal.where(folder.joinpath(*names[0].split("/")))):
                # One file under another name than the declared one: the one the object holds
                held = sorted(file.name for file in folder.iterdir() if file.is_file()) if folder.is_dir() else []
                names = held[:1] or names
                known = {names[0]: content_hash} if held else known
            bad = next((name for name in names if plain_parts(name) is None), None)
            if bad is not None:
                problems.append(f"{part.get('id', what)} in {path.name}: it names {bad!r}, which is not a plain path in its object")
                continue
            sources = {name: journal.where(folder.joinpath(*name.split("/"))) for name in names}
            gone = [name for name, source in sources.items() if not os.path.isfile(source) or os.path.islink(source)]
            if not names or gone:
                problems.append(
                    f"the object {content_hash} ({part.get('id', what)}) does not have "
                    f"{', '.join(gone[:3]) or 'any file'}{' and more' if len(gone) > 3 else ''}, or has it as a link"
                )
                continue
            sizes = {
                entry["path"]: entry.get("size_bytes") for entry in part.get("files") or [] if isinstance(entry, dict)
            } if not single else {names[0]: part.get("size_bytes")}
            short = [name for name, size in sizes.items() if isinstance(size, int) and name in sources and os.stat(sources[name]).st_size != size]
            if short:
                problems.append(f"the object {content_hash} ({part.get('id', what)}) has {short[0]} at another size than its record says")
                continue
            if not single and len(known) < len(names):
                # Its record gives no hash for each file: read them here, before anything moves
                cache = hashing.HashCache()
                hashes = {name: hashing.format_hash(cache.file_hex(source)) for name, source in sources.items()}

                def makes(chosen: list) -> str:
                    return hashing.hash_listing(
                        hashing.FileEntry(name, os.stat(sources[name]).st_size, hashes[name]) for name in chosen
                    ).content_hash

                if makes(names) != content_hash:
                    without = [name for name in names if not _SYNC_COPY.search(name)]
                    if without != names and makes(without) == content_hash:
                        names = without  # a sync service's copy, left where it was
                    else:
                        problems.append(f"the object {content_hash} ({part.get('id', what)}): its files do not make its hash")
                        continue
                known = {name: hashes[name] for name in names}
            prepared[(str(path), index)] = _Part(place, single, names, known)
    if problems:
        shown = "\n".join(f"  {problem}" for problem in problems[:20])
        more = f"\n  and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise MigrateError(
            f"Some objects are not whole, or not what their names say:\n{shown}{more}\nIn a store a sync service keeps, the "
            f"likeliest cause is a sync that has not finished: run this again once it has. `chartbook store verify` with "
            f"ChartBook 0.2 says more of each. Nothing was moved."
        )
    return prepared


def _tagged(document: dict) -> list:
    """What a record names, each with what it is: ``record``, ``index`` or ``documents``."""
    tagged = [("record", record) for record in document.get("records") or [] if isinstance(record, dict)]
    return tagged + [(name, document[name]) for name in ("index", "documents") if isinstance(document.get(name), dict)]


def _move_record(store: _Opened, journal: _Journal, path: Path, document: dict, prepared: dict) -> None:
    """Make one 0.2 record a snapshot's folder of this layout, its files moved into place.

    A migrate cut short leaves what it moved where it moved it, noted in the
    journal, and never removes it: the next run takes it from there.
    """
    from chartbook.snapshot import SCHEMA as RECORD_SCHEMA

    root = store.root
    moment = (document["root"], document["code"]["commit"], document["made_at"])
    store._forget()
    there = next((r for r in store.records() if r.readable and (r.pipeline, r.commit, r.made_at) == moment), None)
    if there is not None:
        journal.wrote(path, there.path)  # written by a migrate cut short before it said so
        return
    pending = _Moving(store, *moment, journal)
    written = dict(document, schema=RECORD_SCHEMA)
    written["records"] = []
    for index, (what, part) in enumerate(_tagged(document)):
        shaped = prepared.get((str(path), index))
        moved = _placed(pending, journal, root, part, shaped) if shaped is not None else part
        if what == "record":
            written["records"].append(moved)
        else:
            written[what] = moved
    into = pending.write(written)
    journal.wrote(path, into)


def _placed(pending: _Moving, journal: _Journal, root: Path, part: dict, shaped: _Part) -> dict:
    """One asset of a record, its files put in the snapshot being written; the record with where they are kept."""
    content_hash = part["content_hash"]
    folder = _object(root, content_hash)
    sources = [(name, str(journal.where(folder.joinpath(*name.split("/"))))) for name in shaped.names]
    gone = next((name for name, source in sources if not os.path.lexists(source)), None)
    if gone is not None:
        raise MigrateError(
            f"{gone} of the object {content_hash} is neither where it was nor where a migrate moved it. Nothing more "
            f"was moved; see that the store's sync has finished, and run this again."
        )
    for name, source in sources:
        if shaped.known.get(name):
            pending.known[source] = shaped.known[name]
    if shaped.single:
        stored = pending.put_listed([(declared_name(shaped.place) or shaped.names[0], sources[0][1])], shaped.place, True)
    else:
        stored = pending.put_listed(sources, shaped.place, False)
    if stored.content_hash != content_hash:
        raise MigrateError(f"The object {content_hash}, moved, does not make its hash. Nothing more was moved; run this again.")
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
