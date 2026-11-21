"""A store laid out by hand as ChartBook 0.5 laid one out, for the tests that read one.

This ChartBook writes every snapshot complete, under ``snapshots/``, and
reads a store of 0.5 (``chartbook/store/v2``) as it is, without writing
data to it. Nothing in ``src/`` lays that layout out for a test (the writer
of 0.5 that ``chartbook.migrate`` keeps moves a store of 0.2, and makes no
snapshot of a pipeline). So a test makes its snapshots as it always did, in
a store of this version, and then hands the folder to :func:`laid_out_as_0_5`,
which makes of it, file by file, what 0.5 would have left there:

- the pipelines' folders under ``pipelines/``, the notes under ``roots/``,
  ``origins/`` and ``tmp/`` at the top, and ``store.json`` saying ``v2``;
- each file kept once in its pipeline's folder, in the first snapshot that
  had it: a later snapshot's own copy is removed, and its record names the
  folder that keeps the file (``kept_in``, and ``kept_as`` where the name
  differs), so that snapshot is *shared*.

:func:`cleared_as_0_5` then clears one snapshot as the ``store gc`` of 0.5
did: its record goes, ``CLEARED.txt`` says so, and the files later
snapshots keep in its folder stay.
"""

import json
import os
import stat
from pathlib import Path

from chartbook.store import PIPELINE_README_OF_0_5, FolderStore, is_snapshot_folder

#: What the ``store.json`` of a store of ChartBook 0.5 says.
MARKER_OF_0_5 = {"schema": "chartbook/store/v2"}


def _remove(path: Path) -> None:
    """Remove one of the store's files, which are read-only (Windows removes none that is)."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()


def _parts(document: dict) -> list:
    """What a record names where files are kept of: its assets, its index and its documents."""
    parts = [record for record in document.get("records") or [] if isinstance(record, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict)]


def _in_put_order(document: dict) -> list:
    """The parts of a record that keep files, in the order ChartBook 0.5 put them into a snapshot.

    The assets with a path, by kind and then by name
    (:func:`chartbook.resolve.declared_files`); then the tables written
    out of a source, by name; then the index; then the documents. A record
    lists its assets in another order, by their names alone. The order
    tells only where two files of one snapshot have the same bytes: 0.5
    kept the first one put, and the other's entry names it (``kept_as``).
    """
    from chartbook.resolve import RESOLVABLE_KINDS

    def put_at(record: dict) -> tuple:
        ref = record.get("ref") or {}
        written_out = (record.get("location") or {}).get("kind") in ("table", "query")
        kind = RESOLVABLE_KINDS.index(ref.get("kind")) if ref.get("kind") in RESOLVABLE_KINDS else len(RESOLVABLE_KINDS)
        return (written_out, 0 if written_out else kind, str(ref.get("name", "")))

    records = sorted((record for record in document.get("records") or [] if isinstance(record, dict)), key=put_at)
    parts = records + [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict)]


def laid_out_as_0_5(root, share: bool = True) -> FolderStore:
    """Make of a store this ChartBook wrote the store ChartBook 0.5 would have left; the store, opened again.

    :param root: The store's folder, laid out as this version lays one out.
    :param share: Whether each file is kept once in its pipeline's folder,
        as 0.5 kept it; without, every snapshot stays standalone.
    """
    root = Path(root)
    own = root / "_chartbook"
    _increments_among_the_rest(root, share)
    (root / "snapshots").rename(root / "pipelines")
    for name in ("roots", "origins", "tmp"):
        if (own / name).is_dir():
            (own / name).rename(root / name)
    if (own / "unowned").is_dir():
        (own / "unowned").rename(root / "pipelines" / "+unowned")
    if own.is_dir():
        own.rmdir()  # nothing else of this layout's was in it
    if (root / "README.txt").is_file():
        (root / "README.txt").unlink()  # 0.5 left none at the top
    (root / "store.json").write_text(json.dumps(MARKER_OF_0_5) + "\n", encoding="utf-8", newline="\n")
    for pipeline in sorted(p for p in (root / "pipelines").iterdir() if p.is_dir() and p.name != "+unowned"):
        if (pipeline / "README.txt").is_file():
            (pipeline / "README.txt").write_text(PIPELINE_README_OF_0_5, encoding="utf-8", newline="\n")
        if share:
            _keep_each_file_once(pipeline)
    return FolderStore(root)


def _increments_among_the_rest(root: Path, share: bool) -> None:
    """Put each snapshot this ChartBook kept as an increment in its pipeline's folder beside the complete ones: ChartBook 0.5 had one folder of snapshots, and no word for the two kinds.

    An increment's record already names, for each of its files, the folder
    that keeps it: its own, or the complete snapshot it builds on, which
    is now beside it. What says it is an increment goes (the record's own
    ``stored``, and its line for a person), and each file is then kept
    once as any other's is (:func:`_keep_each_file_once`).
    """
    increments = root / "increments"
    if not increments.is_dir():
        return
    assert share, "a snapshot kept as an increment is not standalone: make it with complete=True"
    for folder in sorted(p for pipeline in increments.iterdir() if pipeline.is_dir() for p in pipeline.iterdir() if p.is_dir()):
        record = folder / "_chartbook" / "snapshot.json"
        document = json.loads(record.read_text(encoding="utf-8"))
        document.pop("stored", None)
        os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
        record.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if (folder / "_chartbook" / "INCREMENT.txt").is_file():
            _remove(folder / "_chartbook" / "INCREMENT.txt")
        folder.rename(root / "snapshots" / folder.parent.name / folder.name)
    for pipeline in sorted(p for p in increments.iterdir() if p.is_dir()):
        if (pipeline / "README.txt").is_file():
            _remove(pipeline / "README.txt")
        pipeline.rmdir()
    increments.rmdir()


def _keep_each_file_once(pipeline: Path) -> None:
    """Rewrite one pipeline's snapshots, oldest first, as 0.5 wrote them: a file an earlier one has is kept there alone.

    Of two files of one snapshot with the same bytes, the first one 0.5
    put is the one kept (:func:`_in_put_order`). A file that a record
    already says is kept in another snapshot's folder (what was an
    increment's, in the complete snapshot it built on) is where it says.
    """
    first: dict = {}  # where each file's bytes are kept, by their hash: the snapshot's folder, and the path in it
    for folder in sorted(p for p in pipeline.iterdir() if p.is_dir() and is_snapshot_folder(p.name)):
        record = folder / "_chartbook" / "snapshot.json"
        if not record.is_file():
            continue
        document = json.loads(record.read_text(encoding="utf-8"))
        for part in _in_put_order(document):
            for entry in part["stored"].get("files") or []:
                where = (entry.get("kept_in", folder.name), entry.get("kept_as", entry["path"]))
                kept_in, kept_as = first.setdefault(entry["content_hash"], where)
                if (kept_in, kept_as) == where:
                    continue  # the first to have it: kept where it is, under its own name
                mine = folder.joinpath(*entry["path"].split("/"))
                if where[0] == folder.name and mine.is_file():
                    _remove(mine)
                entry["kept_in"] = kept_in
                entry.pop("kept_as", None)
                if kept_as != entry["path"]:
                    entry["kept_as"] = kept_as
        record.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        # A folder this emptied is not left behind: 0.5 never made one
        for directory, _, _ in sorted(os.walk(folder), key=lambda walked: -len(walked[0])):
            if not os.listdir(directory):
                os.rmdir(directory)


def cleared_as_0_5(record) -> Path:
    """Clear one snapshot of a store of 0.5 as its ``store gc`` did; the folder left, with ``CLEARED.txt`` in it.

    The record goes. Of the files in the snapshot's folder, those another
    snapshot's record of the pipeline names stay where they are, and the
    rest go.

    :param record: The snapshot's record, ``<its folder>/_chartbook/snapshot.json``.
    """
    record = Path(record)
    folder = record.parent.parent
    record.unlink()
    (record.parent / "CLEARED.txt").write_text(
        "Cleared by `chartbook store gc` on 2026-11-01 00:00:00 UTC.\n"
        "The files left in this folder are used by later snapshots of the same pipeline,\n"
        "whose _chartbook/snapshot.json says so; the folder goes once none is.\n",
        encoding="utf-8",
        newline="\n",
    )
    used = set()
    for other in sorted(folder.parent.glob("*/_chartbook/snapshot.json")):
        document = json.loads(other.read_text(encoding="utf-8"))
        for part in _parts(document):
            for entry in part["stored"].get("files") or []:
                kept_in = entry.get("kept_in", other.parent.parent.name)
                used.add(folder.parent.joinpath(kept_in, *entry.get("kept_as", entry["path"]).split("/")))
    for directory, _, files in os.walk(folder):
        for name in files:
            file = Path(directory) / name
            if file not in used and file != record.parent / "CLEARED.txt":
                _remove(file)
    for directory, _, _ in sorted(os.walk(folder), key=lambda walked: -len(walked[0])):
        if not os.listdir(directory):
            os.rmdir(directory)
    return folder
