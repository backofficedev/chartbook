"""A store of ChartBook 0.5 with the shape found in a real one that a sync service keeps, for the tests of the mover.

Found on 2026-11-20, when ``chartbook store migrate`` was run on a copy of
a store in a shared, synced folder (four pipelines, 54,715 files). The
store was whole by the ``store verify`` of 0.5, and held what no test
store did. Here it is in small, under invented names:

- ``acme/news`` has four folders under ``pipelines/acme+news/``:

  - **A**, named as a snapshot's: data files, no record and no
    ``CLEARED.txt``;
  - **B**, named a second later: its record says the time of A's name, and
    keeps every one of its files in its own folder;
  - **R**, the newest: its record says eleven files of a dataset are kept
    in A, where five are and six are not (the same bytes are all in B),
    and its ``chartbook.toml``, which is; and it keeps five files in its
    own folder;
  - **R 2** (the folder's name ends in `` 2``), a sync's second copy of R:
    the same record byte for byte, but that it says B keeps what R's says
    A keeps, with its own copies of the files R keeps in its own folder;

- a folder named as a snapshot's that holds nothing but two
  ``desktop.ini``, and a ``desktop.ini`` in every folder of the store, as
  a sync client for a desktop leaves them (``.DS_Store`` is the same thing
  elsewhere);
- the other second copies a sync made: ``README 2.txt`` in the pipeline's
  folder, a note of a lockfile ``roots/<id> 2.json``, and a folder
  ``origins/<commit> 2/``;
- ``acme/reader``, whose lockfile pins R.

It is made as a store of 0.5 is made in the other tests of the mover (a
pipeline, ``snapshot.make``, ``lock.pin``, :func:`tests.store_of_0_5.laid_out_as_0_5`),
and A, B, R and ``R 2`` are then shaped by hand, each step saying what it
stands for.
"""

import json
import os
import shutil
import stat
from pathlib import Path

import polars as pl
import tomli_w

from chartbook import lock, snapshot
from chartbook import store as store_module
from chartbook.store import FolderStore
from tests.fixtures import _git
from tests.store_of_0_5 import laid_out_as_0_5

#: When the two snapshots of ``acme/news`` were made: the one A and B are of, and R.
MADE = ("2026-10-30T05:34:55.000000Z", "2026-11-02T05:22:22.000000Z")

#: The files of the dataset that R's record says are kept in A: those that are there, and those that are not.
IN_A = ("00", "02", "04", "06", "09")
NOT_IN_A = ("01", "03", "05", "07", "08", "10")

#: The files in A that no record names.
UNNAMED = ("_data/articles/half-written.tmp", "_data/left-behind.parquet", "notes.txt")

DESKTOP_INI = b"[.ShellClassInfo]\r\nIconResource=C:\\Program Files\\Drive\\drive_fs.ico,23\r\n"


def _commit(folder: Path, message: str) -> None:
    if not (folder / ".git").exists():
        _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", message)


def _writable(path: Path) -> Path:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)  # the store's files are read-only
    return path


def _article(folder: Path, name: str, text: str) -> None:
    pl.DataFrame({"day": [int(name)], "headline": [text]}).write_parquet(folder / "_data" / "articles" / f"{name}.parquet")


def found(work: Path, root: Path) -> dict:
    """Make the store at *root*, with its pipelines' folders under *work*; the names of A, B, R and ``R 2``, the reader's folder, and the files R keeps in its own folder."""
    news = work / "news"
    (news / "_data" / "articles").mkdir(parents=True)
    (news / "_output").mkdir()
    (news / "chartbook.toml").write_text(
        tomli_w.dumps({
            "project": {"id": "acme/news"},
            "dataframes": {
                "articles": {"path": "./_data/articles/", "docs": "d"},
                "totals": {"path": "./_data/totals.parquet", "docs": "d"},
            },
            "charts": {"counts": {"path": "./_output/counts.html", "dataframe": "totals", "docs": "d"}},
        }),
        encoding="utf-8", newline="\n",
    )
    (news / "README.md").write_text("# acme/news\n", encoding="utf-8", newline="\n")
    (news / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    for number in range(12):
        _article(news, f"{number:02d}", f"headline {number}")
    pl.DataFrame({"articles": [12]}).write_parquet(news / "_data" / "totals.parquet")
    (news / "_output" / "counts.html").write_text("<p>12</p>\n", encoding="utf-8", newline="\n")
    _commit(news, "Twelve days")
    first = snapshot.make(news, store=FolderStore(root), made_at=MADE[0])
    # The next snapshot: eleven files of the dataset as they were, and a few files of its own
    _article(news, "11", "headline 11, corrected")
    pl.DataFrame({"articles": [12], "corrected": [1]}).write_parquet(news / "_data" / "totals.parquet")
    (news / "_output" / "counts.html").write_text("<p>12, one corrected</p>\n", encoding="utf-8", newline="\n")
    (news / "README.md").write_text("# acme/news, corrected\n", encoding="utf-8", newline="\n")
    _commit(news, "A correction")
    second = snapshot.make(news, store=FolderStore(root), made_at=MADE[1])
    reader = work / "reader"
    reader.mkdir()
    (reader / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"acme/news": {"path": "../news"}}}),
        encoding="utf-8", newline="\n",
    )
    assert lock.pin(reader, FolderStore(root)).problems == []  # the newest, which becomes R
    # As 0.5 left it: the second snapshot's record says the files it shares with the first are kept in the first's folder
    laid_out_as_0_5(root)
    pipeline = root / "pipelines" / "acme+news"
    a, r = pipeline / first.snapshot.path.parent.parent.name, pipeline / second.snapshot.path.parent.parent.name
    (root / "tmp").mkdir(exist_ok=True)

    # B: the same snapshot made a second time, which 0.5 put in a folder named for the next second. Its record says
    # the time of the first, and keeps every one of its files in its own folder: it is whole
    b = pipeline / a.name.replace("T053455Z", "T053456Z")
    shutil.copytree(a, b)
    record = _writable(b / "_chartbook" / "snapshot.json")
    record.write_text(record.read_text(encoding="utf-8").replace(f'"kept_in": "{a.name}"', f'"kept_in": "{b.name}"'), encoding="utf-8", newline="\n")

    # A: its record never came (and `store gc` did not clear it: no CLEARED.txt), so it is a folder with files and no record
    _writable(a / "_chartbook" / "snapshot.json").unlink()
    # A: six of the eleven files that R's record says are kept there are not there. The same bytes are in B
    for name in NOT_IN_A:
        _writable(a / "_data" / "articles" / f"{name}.parquet").unlink()
    # A: and it holds files no record names
    for path in UNNAMED:
        (a / path).parent.mkdir(parents=True, exist_ok=True)
        (a / path).write_bytes(f"no record names {path}".encode())

    # R: left as 0.5 wrote it. Its record keeps eleven files of the dataset in A, and its own files in its own folder
    document = json.loads((r / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
    entries = [entry for part in _parts(document) for entry in part["stored"]["files"]]
    in_a = sorted(entry["path"] for entry in entries if entry["kept_in"] == a.name)
    assert [path for path in in_a if "/articles/" in path] == [f"_data/articles/{name}.parquet" for name in sorted(IN_A + NOT_IN_A)], in_a
    own = sorted({entry["path"] for entry in entries if entry["kept_in"] == r.name})
    assert len(own) >= 3 and all((r / path).is_file() for path in own), own

    # `R 2`: a sync's second copy of R's folder. It holds its own copies of the files R keeps in its own folder, and
    # the same record byte for byte, but that it says the others are kept in B
    r2 = pipeline / f"{r.name} 2"
    shutil.copytree(r, r2)
    record = _writable(r2 / "_chartbook" / "snapshot.json")
    record.write_text(record.read_text(encoding="utf-8").replace(f'"kept_in": "{a.name}"', f'"kept_in": "{b.name}"'), encoding="utf-8", newline="\n")

    # A folder named as a snapshot's that holds nothing but what a desktop leaves: no snapshot, and no folder with files
    nothing = pipeline / "2026-10-29T000000Z_0123456789ab"
    (nothing / "_data").mkdir(parents=True)

    # The other second copies a sync made: of the pipeline's README, of a note of a lockfile, and of a commit's origins
    shutil.copyfile(pipeline / "README.txt", pipeline / "README 2.txt")
    note = next(p for p in (root / "roots").iterdir() if p.suffix == ".json")
    shutil.copyfile(note, note.with_name(f"{note.stem} 2.json"))
    origin = next(p for p in sorted((root / "origins").iterdir()) if p.is_dir())
    shutil.copytree(origin, origin.with_name(f"{origin.name} 2"))

    # And a desktop.ini in every folder of the store, as a sync client for a desktop leaves one
    for folder in [root] + sorted(p for p in root.rglob("*") if p.is_dir()):
        (folder / "desktop.ini").write_bytes(DESKTOP_INI)
    assert sorted(p.name for p in nothing.rglob("*") if p.is_file()) == ["desktop.ini", "desktop.ini"]

    store_module._read_records.clear()
    store_module._found_whole.clear()
    return dict(
        a=a.name, b=b.name, r=r.name, r2=r2.name, nothing=nothing.name, reader=reader, own=own, in_a=in_a,
        note=note.name, origin=origin.name,
    )


def _parts(document: dict) -> list:
    parts = [part for part in document.get("records") or [] if isinstance(part, dict)]
    parts += [document[name] for name in ("index", "documents") if isinstance(document.get(name), dict)]
    return [part for part in parts if isinstance(part.get("stored"), dict)]


def elsewhere(root: Path) -> dict:
    """Fill an empty store of 0.5, by hand, with every way a file can be somewhere other than where its record says; the snapshots' folder names.

    ChartBook 0.5 found a file by its hash anywhere in its pipeline's
    folder, so each of these read there, and each must read once moved.
    ``acme/p`` has a folder with no record (``c0``), two snapshots that
    become increments (``s1``, ``s2``), the newest (``s3``), which the
    others build on, and two that a pin made (``p4``, ``p5``); ``acme/q``
    has two that a pin made. A record that says ``c0`` keeps a file names a
    place where the file is not, but for ``k9``; and one of ``acme/q`` names
    a folder that is not there at all.

    =====  ==========================================================  ===================================================
    file   who names it, and where the bytes are                       what the move makes of it
    =====  ==========================================================  ===================================================
    k1     s3 and p5 (not there); s1 and s2 each have their own        s3 takes s1's, p5 is given a copy; s2's goes aside
    k2     s1 (not there); s2 has its own; s3 does not name it         s1 takes s2's, and s2 is given a copy
    k3     s3 has its own; p4 (not there)                              p4 is given a copy of s3's
    k4     s3 and p5 (not there); s1 has its own                       s3 takes s1's, and p5 is given a copy
    k5     s3 twice, as k5a and k5b (not there); s2 has it as k5       s3 takes s2's for k5a, and copies it for k5b
    k6     s3 (not there); nobody else                                 missing, as it was
    k7     s3 (not there); p4 has its own                              s3 takes p4's, and p4 is given a copy
    k8     s3 (in c0, half of it, as a sync left it); s1 has its own   s3 takes s1's; the half goes aside
    k9     s1, s2 and s3, in c0, where it is                           s3 takes it from c0, as before
    q      q1 (in a folder that is not there); q2 has its own          q1 takes q2's, and q2 is given a copy
    =====  ==========================================================  ===================================================

    In k1 two older snapshots each have the bytes and two others want them:
    a move cut short once s3 has s1's must give p5 a copy of that, and
    leave s2's to go aside as an uninterrupted move does.
    """
    from tests.rich_store_of_0_5 import folder_of, put, record

    k = {number: bytes([64 + number]) * (100 + 10 * number) for number in range(1, 10)}
    q = b"q" * 400
    c0 = folder_of("2025-09-01", "h")
    put(root, "acme+p", c0, "_data/k9.parquet", k[9])
    put(root, "acme+p", c0, "_data/k8.parquet", k[8][:50])  # half of it
    put(root, "acme+p", c0, "_data/nobody.bin", b"nobody names this, in a folder with no record")
    s1 = folder_of("2025-10-01", "a")
    for number in (1, 4, 8):
        put(root, "acme+p", s1, f"_data/k{number}.parquet", k[number])
    record(root, "acme/p", "2025-10-01", "a", [
        ("_data/k1.parquet", k[1], None, None), ("_data/k2.parquet", k[2], c0, None), ("_data/k4.parquet", k[4], None, None),
        ("_data/k8.parquet", k[8], None, None), ("_data/k9.parquet", k[9], c0, None),
    ])
    s2 = folder_of("2025-11-01", "b")
    for name, number in (("k1", 1), ("k2", 2), ("k5", 5)):
        put(root, "acme+p", s2, f"_data/{name}.parquet", k[number])
    record(root, "acme/p", "2025-11-01", "b", [
        ("_data/k1.parquet", k[1], None, None), ("_data/k2.parquet", k[2], None, None), ("_data/k5.parquet", k[5], None, None),
        ("_data/k9.parquet", k[9], c0, None),
    ])
    s3 = folder_of("2025-12-01", "c")
    put(root, "acme+p", s3, "_data/k3.parquet", k[3])
    record(root, "acme/p", "2025-12-01", "c", [
        ("_data/k1.parquet", k[1], c0, None), ("_data/k3.parquet", k[3], None, None), ("_data/k4.parquet", k[4], c0, None),
        ("_data/k5a.parquet", k[5], c0, None), ("_data/k5b.parquet", k[5], c0, "_data/k5a.parquet"),
        ("_data/k6.parquet", k[6], c0, None), ("_data/k7.parquet", k[7], c0, None), ("_data/k8.parquet", k[8], c0, None),
        ("_data/k9.parquet", k[9], c0, None),
    ])
    p4 = folder_of("2025-12-15", "d")
    put(root, "acme+p", p4, "_data/k7.parquet", k[7])
    record(root, "acme/p", "2025-12-15", "d", [("_data/k3.parquet", k[3], c0, None), ("_data/k7.parquet", k[7], None, None)], made_by="pin")
    p5 = record(root, "acme/p", "2025-10-15", "i", [("_data/k1.parquet", k[1], c0, None), ("_data/k4.parquet", k[4], c0, None)], made_by="pin")
    # acme/q: two that a pin made; the older says its file is kept in a folder that is not there
    q2 = folder_of("2025-11-01", "f")
    put(root, "acme+q", q2, "_data/q.parquet", q)
    q1 = record(root, "acme/q", "2025-10-01", "e", [("_data/q.parquet", q, folder_of("2025-08-01", "j"), None)], made_by="pin")
    record(root, "acme/q", "2025-11-01", "f", [("_data/q.parquet", q, None, None)], made_by="pin")
    return dict(c0=c0, s1=s1, s2=s2, s3=s3, p4=p4, p5=p5, q1=q1, q2=q2)


def any_store(root: Path, seed: int) -> dict:
    """Fill an empty store of 0.5, by hand, with one pipeline drawn from a seed; for each file a record names, the hash its record says and whether some record's place holds those bytes whole.

    Two to five snapshots, each made by its owner or by a pin, of up to five
    files of their own bytes. A record says a file is kept in its own
    folder, where an earlier record said the same bytes are (under that
    name, as 0.5 kept each file once), in a folder with no record, or in a
    folder that is not there. Each place a record names holds the file, or
    half of it, or nothing. And a record may name the same bytes twice.

    :returns: By ``(snapshot's folder, path)``: ``(the hash, whether 0.5
        could read it)``.
    """
    import hashlib
    import random

    from tests.rich_store_of_0_5 import folder_of, put, record

    drawn = random.Random(seed)
    data = {number: bytes([97 + number]) * (60 + 9 * number) for number in range(5)}
    no_record, not_there = folder_of("2025-01-01", "p"), folder_of("2024-12-01", "o")
    said: dict = {}  # the places records say each file's bytes are
    decided: set = set()
    whole: set = set()
    named: dict = {}
    for index in range(drawn.randint(2, 5)):
        day, letter = f"2025-{index + 2:02d}-01", "abcde"[index]
        folder = folder_of(day, letter)
        entries = []
        for number in data:
            if drawn.random() < 0.35 and (entries or number < 4):
                continue
            path = f"_data/k{number}.parquet"
            how = drawn.choice(["its own", "its own", "an earlier one's", "an earlier one's", "no record", "not there"])
            if how == "an earlier one's" and said.get(number):
                place = drawn.choice(sorted(said[number]))
            else:
                place = {"no record": (no_record, path), "not there": (not_there, path)}.get(how, (folder, path))
            if place not in decided and place[0] != not_there:
                decided.add(place)
                holds = drawn.random()
                if holds < 0.6:
                    put(root, "acme+p", place[0], place[1], data[number])
                    whole.add(place)
                elif holds < 0.72:
                    put(root, "acme+p", place[0], place[1], data[number][:20])  # half of it
            names = [path] + ([f"_data/k{number}b.parquet"] if drawn.random() < 0.15 else [])
            for name in names:
                entries.append((name, data[number], None if place[0] == folder else place[0], None if place[1] == name else place[1]))
                named[(folder, name)] = number
            said.setdefault(number, set()).add(place)
        record(root, "acme/p", day, letter, entries, made_by="pin" if drawn.random() < 0.3 else "")
    return {
        key: ("sha256:" + hashlib.sha256(data[number]).hexdigest(), bool(said[number] & whole))
        for key, number in named.items()
    }
