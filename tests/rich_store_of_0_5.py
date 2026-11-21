"""A store of ChartBook 0.5 written by hand, with every shape a move has to carry, for the tests of the mover.

It is the store the eighth review of the mover wrote, kept here so that
the suite stops a move after every step on it: ``kept_as``, two
increments-to-be sharing a file the base lacks, pins on the base and on an
increment, a pipeline of pins alone with two pins sharing a file, a cleared
folder still holding files, two missing files, an object no pipeline owns,
a person's README at the top and in a pipeline, a dot-file a record names,
a file no record names inside a snapshot's folder, notes of a lockfile and
of an origin, and the mark the move from 0.2 left.
"""

import builtins
import hashlib
import io
import json
import os
import pathlib
import shutil
import stat
from pathlib import Path

from chartbook import store as store_module
from chartbook.store import FolderStore

COMMIT = {letter: hashlib.sha1(letter.encode()).hexdigest() for letter in "abcdefghijklmnop"}

A, B, C, D, G, X, DOT = b"a" * 100, b"b" * 200, b"c" * 300, b"d" * 400, b"g" * 150, b"x" * 77, b"." * 31


class Stop(BaseException):
    """The process is killed here."""


def stop_after(number: int):
    def after(done: int) -> None:
        if done == number:
            raise Stop()

    return after


def h(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def folder_of(day: str, letter: str) -> str:
    return f"{day}T091500Z_{COMMIT[letter][:12]}"


def put(root: Path, pipeline: str, folder: str, path: str, data: bytes, tree: str = "pipelines") -> Path:
    file = root / tree / pipeline / folder / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)
    os.chmod(file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return file


def record(root: Path, pipeline_id: str, day: str, letter: str, entries: list, made_by: str = "") -> str:
    """One snapshot's record as 0.5 wrote it; the snapshot's folder name. entries: (path, data, kept_in or None for its own, kept_as or None)."""
    folder = folder_of(day, letter)
    parts = []
    for path, data, kept_in, kept_as in entries:
        entry = {"path": path, "content_hash": h(data), "size_bytes": len(data), "kept_in": kept_in or folder}
        if kept_as:
            entry["kept_as"] = kept_as
        parts.append({
            "id": f"{pipeline_id}:dataframe:{path}", "kind": "dataframe", "content_hash": h(data), "size_bytes": len(data),
            "stored": {"at": path.rpartition("/")[0], "single": True, "files": [entry]},
        })
    document = {
        "schema": "chartbook/snapshot/v2", "root": pipeline_id, "made_at": f"{day}T09:15:00.000000Z",
        "code": {"commit": COMMIT[letter], "subdirectory": ""}, "records": parts,
    }
    if made_by:
        document["made_by"] = made_by
    file = root / "pipelines" / pipeline_id.replace("/", "+") / folder / "_chartbook" / "snapshot.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return folder


def empty_store(tmp_path: Path, name: str = "store") -> Path:
    root = tmp_path.resolve() / name
    (root / "pipelines").mkdir(parents=True)
    (root / "roots").mkdir()
    (root / "store.json").write_text(json.dumps({"schema": "chartbook/store/v2"}) + "\n", encoding="utf-8", newline="\n")
    return root


def fresh(root: Path) -> FolderStore:
    store_module._read_records.clear()
    store_module._found_whole.clear()
    return FolderStore(root)


def read_through(root: Path) -> dict:
    """Every file of every record as the store hands it out: its bytes' hash, or why it cannot be read."""
    found = {}
    for kept in fresh(root).records():
        assert kept.readable, kept.path
        for asset in kept.assets:
            for file in asset.files:
                try:
                    found[(kept.pipeline, kept.folder.name, file.path)] = hashlib.sha256(file.location.read_bytes()).hexdigest()
                except OSError as error:
                    found[(kept.pipeline, kept.folder.name, file.path)] = type(error).__name__
    return found


def tree_of(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def contents(root: Path) -> dict:
    """Where each run of bytes is, anywhere under the store, by its hash."""
    found: dict = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            found.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), []).append(path.relative_to(root).as_posix())
    return found


def rmtree(folder: Path) -> None:
    shutil.rmtree(folder, onerror=lambda function, path, _: (os.chmod(path, stat.S_IWRITE | stat.S_IREAD), function(path)))


def rich(root: Path) -> dict:
    """Fill an empty store of 0.5 with every shape; the snapshots' folder names."""
    # acme/p: a cleared folder that still holds what later records name, and a file no record names
    c0 = folder_of("2025-09-01", "h")
    put(root, "acme+p", c0, "_data/one.parquet", A)
    put(root, "acme+p", c0, "_data/old.parquet", B)
    put(root, "acme+p", c0, "_data/nobody.bin", b"nobody names this, in a cleared folder")
    cleared = root / "pipelines" / "acme+p" / c0 / "_chartbook" / "CLEARED.txt"
    cleared.parent.mkdir(parents=True)
    cleared.write_text("Cleared by `chartbook store gc`.\n", encoding="utf-8", newline="\n")
    # s1, s2: increments-to-be, sharing a file the base lacks (shared.parquet) and a dot-file a record names
    s1 = folder_of("2025-10-01", "a")
    put(root, "acme+p", s1, "_data/g.parquet", G)
    put(root, "acme+p", s1, "_data/shared.parquet", X)
    put(root, "acme+p", s1, "_data/parts/.zmeta", DOT)
    record(root, "acme/p", "2025-10-01", "a", [
        ("_data/one.parquet", A, c0, None), ("_data/old.parquet", B, c0, None), ("_data/g.parquet", G, None, None),
        ("_data/shared.parquet", X, None, None), ("_data/parts/.zmeta", DOT, None, None),
        ("_data/lost.parquet", b"l" * 60, c0, None),  # missing as before, in a folder that is there
    ])
    s2 = record(root, "acme/p", "2025-11-01", "b", [
        ("_data/one.parquet", A, c0, None), ("_data/old.parquet", B, c0, None),
        ("_data/shared.parquet", X, s1, None), ("_data/parts/.zmeta", DOT, s1, None),
        ("_data/g_again.parquet", G, s1, "_data/g.parquet"),  # kept_as, between two increments
    ])
    s3 = folder_of("2025-12-01", "c")
    put(root, "acme+p", s3, "_data/new.parquet", C)
    put(root, "acme+p", s3, "notes-by-hand.txt", b"a file no record names, inside the newest snapshot's folder")
    record(root, "acme/p", "2025-12-01", "c", [
        ("_data/one.parquet", A, c0, None), ("_data/two.parquet", A, c0, "_data/one.parquet"), ("_data/new.parquet", C, None, None),
        ("_data/gone.parquet", b"m" * 70, None, None),  # the newest one's own, missing as before
    ])
    # A pin's snapshot written after the newest: files in the newest one's folder, the cleared one's and an increment's
    p4 = record(root, "acme/p", "2025-12-15", "d", [
        ("_data/new.parquet", C, s3, None), ("_data/old.parquet", B, c0, None), ("_data/g.parquet", G, s1, None),
    ], made_by="pin")
    # And a pin's between the two increments, which keeps the file the two share
    p5 = record(root, "acme/p", "2025-10-15", "i", [("_data/shared.parquet", X, s1, None), ("_data/parts/.zmeta", DOT, s1, None)], made_by="pin")
    (root / "pipelines" / "acme+p" / "README.txt").write_text("Dana's notes on this pipeline.\n", encoding="utf-8", newline="\n")
    # acme/q: pins alone, two sharing a file
    q1 = folder_of("2025-10-01", "e")
    put(root, "acme+q", q1, "_data/q.parquet", D)
    record(root, "acme/q", "2025-10-01", "e", [("_data/q.parquet", D, None, None)], made_by="pin")
    q2 = record(root, "acme/q", "2025-11-01", "f", [("_data/q.parquet", D, q1, None)], made_by="pin")
    (root / "pipelines" / "acme+q" / "README.txt").write_text(store_module.PIPELINE_README_OF_0_5, encoding="utf-8", newline="\n")
    # acme/r: a pin's, the oldest, keeps what the two its owner made name
    r1 = folder_of("2025-09-01", "f")
    put(root, "acme+r", r1, "_data/f.parquet", A)
    put(root, "acme+r", r1, "_data/g.parquet", B)
    record(root, "acme/r", "2025-09-01", "f", [("_data/f.parquet", A, None, None), ("_data/g.parquet", B, None, None)], made_by="pin")
    r2 = record(root, "acme/r", "2025-10-01", "g", [("_data/f.parquet", A, r1, None), ("_data/g.parquet", B, r1, None)])
    r3 = record(root, "acme/r", "2025-11-01", "h", [("_data/f.parquet", A, r1, None)])
    unowned = root / "pipelines" / "+unowned" / hashlib.sha256(D).hexdigest()
    unowned.mkdir(parents=True)
    (unowned / "q.parquet").write_bytes(D)
    (root / "roots" / ("ab" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
    (root / "origins" / COMMIT["a"]).mkdir(parents=True)
    (root / "origins" / COMMIT["a"] / "acme+p.txt").write_text("/somewhere\n", encoding="utf-8", newline="\n")
    (root / "tmp").mkdir()
    (root / "snapshots" / ("0" * 40)).mkdir(parents=True)
    (root / "snapshots" / ("0" * 40) / "MOVED.txt").write_text("moved\n", encoding="utf-8", newline="\n")
    (root / "README.txt").write_text("This is our store. Ask Dana before touching it.\n", encoding="utf-8", newline="\n")
    for place in (root / "pipelines", root / "pipelines" / "acme+p", root / "pipelines" / "acme+p" / s3):
        (place / ".DS_Store").write_bytes(b"\x00Bud1")
    return dict(c0=c0, s1=s1, s2=s2, s3=s3, p4=p4, p5=p5, q1=q1, q2=q2, r1=r1, r2=r2, r3=r3)


#: What a move may remove or write over: its own journal, the store's marker, and what is in its own folder of temporaries
OWN = ("_chartbook/move-to-v3.jsonl", "store.json")
MOVING = "_chartbook/moving"


def watch(monkeypatch, root: Path, gone: list) -> None:
    """Record every call that takes bytes away under *root*: a remover, a rename onto a path that is there, a file opened for writing that is there."""
    real = dict(unlink=os.unlink, remove=os.remove, rmdir=os.rmdir, rmtree=shutil.rmtree, replace=os.replace, rename=os.rename, move=shutil.move, open=io.open)

    def where(path) -> str:
        path = Path(os.fspath(path))
        return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)

    def remover(name):
        def call(path, *args, **kwargs):
            gone.append((name, where(path)))
            return real[name](path, *args, **kwargs)
        return call

    def onto(name):
        def call(source, target, *args, **kwargs):
            if os.path.lexists(target) and not os.path.isdir(target):
                gone.append((f"{name} onto", where(target)))
            return real[name](source, target, *args, **kwargs)
        return call

    def opened(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and any(letter in mode for letter in "wa+") and os.path.lexists(file) and Path(os.fspath(file)).is_relative_to(root):
            gone.append((f"open {mode}", where(file)))
        return real["open"](file, mode, *args, **kwargs)

    for name in ("unlink", "remove", "rmdir"):
        monkeypatch.setattr(os, name, remover(name))
    monkeypatch.setattr(shutil, "rmtree", remover("rmtree"))
    monkeypatch.setattr(shutil, "move", onto("move"))
    monkeypatch.setattr(os, "replace", onto("replace"))
    monkeypatch.setattr(os, "rename", onto("rename"))
    monkeypatch.setattr(io, "open", opened)
    monkeypatch.setattr(builtins, "open", opened)
    # Python 3.10: a Path's own methods (unlink, rmdir, rename, replace, open, and so write_text)
    # call the functions pathlib kept when it was imported, which the patches above do not reach.
    # From 3.11 on they look them up in os and io each time, and there is no such class
    accessor = getattr(pathlib, "_NormalAccessor", None)
    if accessor is not None:
        kept = (("unlink", remover("unlink")), ("rmdir", remover("rmdir")), ("rename", onto("rename")), ("replace", onto("replace")), ("open", opened))
        for name, call in kept:
            if hasattr(accessor, name):
                monkeypatch.setattr(accessor, name, staticmethod(call))


def not_its_own(gone: list) -> list:
    """What was removed or written over that is not the move's own. A file is the move's by where it is, never by its name: one named ``x.moving`` in a pipeline's folder is anyone's."""
    return sorted({(name, path) for name, path in gone if path != MOVING and not path.startswith(MOVING + "/") and path not in OWN and "/pytest-" not in path})


