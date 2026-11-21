"""Turn a folder store of this layout into one that keeps some snapshots as increments.

``chartbook snapshot`` keeps a snapshot as an increment where little
changed, on a complete snapshot older than itself, and ``chartbook store
migrate`` leaves a store of 0.5 with the newest complete and the older ones
increments on it. This helper takes a store whose snapshots were each made
complete (``snapshot.make(..., complete=True)``) and writes either shape,
as the store itself writes an increment
(``docs_src/design/snapshots-and-increments.md``, "An increment"):

- the increment's folder is ``increments/<pipeline>/<snapshot>/``, and
  holds the files that the one complete snapshot it builds on does not
  have, by their bytes and size, whatever their names;
- its record lists every file of its version, each with the folder that
  keeps it (``kept_in``: its own, or that one; ``kept_as`` where the name
  there is another);
- the record says which snapshot that is where it says how the store keeps
  the snapshot, ``stored.builds_on`` at its top, and nowhere among what the
  snapshot is;
- ``_chartbook/INCREMENT.txt`` says the same in one line for a person.

Two shapes: the page's own, an older complete snapshot with the later ones
as increments on it (``complete="oldest"``); and the migrate's, the newest
complete and each older one an increment on it (``complete="newest"``), so
that an increment builds on a snapshot made later than itself.
"""

import json
import os
import stat
from pathlib import Path

from chartbook import store as store_module

INCREMENT_LINE = "The rest of this snapshot's files are in snapshots/{pipeline}/{snapshot}\n"


def _writable(path: Path) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)  # what a store keeps is read-only


def _parts(document: dict) -> list[dict]:
    """Every part of a record that says where its files are: its assets, its index and its documents."""
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict)]


def as_increment(root: Path, pipeline_folder: str, snapshot: str, builds_on: str) -> Path:
    """Keep one complete snapshot as an increment on another of its pipeline; the increment's folder.

    Every file of it that the other holds with the same bytes and size is
    dropped from its own folder and recorded as kept there.
    """
    complete = root / "snapshots" / pipeline_folder
    source, base = complete / snapshot, complete / builds_on
    held = {}  # what the one it builds on holds: (hash, size) -> its path there
    for part in _parts(json.loads((base / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))):
        for entry in part["stored"]["files"]:
            held.setdefault((entry["content_hash"], entry["size_bytes"]), entry.get("kept_as", entry["path"]))
    record = source / "_chartbook" / "snapshot.json"
    document = json.loads(record.read_text(encoding="utf-8"))
    dropped = set()
    for part in _parts(document):
        for entry in part["stored"]["files"]:
            there = held.get((entry["content_hash"], entry["size_bytes"]))
            if there is None:
                entry["kept_in"] = snapshot
                continue
            entry["kept_in"] = builds_on
            if there != entry["path"]:
                entry["kept_as"] = there
            dropped.add(entry["path"])
    for path in sorted(dropped):
        file = source.joinpath(*path.split("/"))
        if file.is_file():
            _writable(file)
            file.unlink()
    for folder in sorted((p for p in source.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if folder.name != "_chartbook" and not any(folder.iterdir()):
            folder.rmdir()
    document["stored"] = {"builds_on": builds_on}
    _writable(record)
    record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.chmod(record, stat.S_IREAD)
    (source / "_chartbook" / "INCREMENT.txt").write_text(
        INCREMENT_LINE.format(pipeline=pipeline_folder, snapshot=builds_on), encoding="utf-8", newline="\n"
    )
    target = root / "increments" / pipeline_folder / snapshot
    target.parent.mkdir(parents=True, exist_ok=True)
    store_module.write_readme(target.parent, store_module.INCREMENTS_README)  # for a person who finds the folder
    source.rename(target)
    store_module._read_records.clear()
    store_module._found_whole.clear()
    return target


def with_increments(root: Path, complete: str = "oldest", pipeline: str = None) -> dict:
    """Keep every snapshot an owner made but one, in each pipeline (or in one), as an increment on that one.

    :param complete: ``"oldest"`` for the page's own shape; ``"newest"``
        for the migrate's.
    :returns: By the pipeline's folder name, the folder of the complete
        snapshot and the folders of the increments on it, oldest first.
    """
    made: dict = {}
    snapshots = Path(root) / "snapshots"
    for folder in sorted(p for p in snapshots.iterdir() if p.is_dir()):
        if pipeline is not None and folder.name != pipeline.replace("/", "+"):
            continue
        owners = []
        for snapshot in sorted(p for p in folder.iterdir() if (p / "_chartbook" / "snapshot.json").is_file()):
            document = json.loads((snapshot / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
            if document.get("made_by", "snapshot") == "snapshot":  # one a pin made is always complete
                owners.append((document["made_at"], snapshot.name))
        owners.sort()
        if len(owners) < 2:
            continue
        base = owners[0][1] if complete == "oldest" else owners[-1][1]
        made[folder.name] = (
            folder / base, [as_increment(Path(root), folder.name, name, base) for _, name in owners if name != base]
        )
    return made
