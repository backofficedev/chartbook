"""The time a plan of the mover takes on a store of the found shape, by how many files it has (N11 of the review, 2026-11-20).

The real store has 54,715 files, 9,267 of them in one snapshot. Each store
here is one pipeline in the found shape: A (no record, with every other
file of a dataset), B (a record, every file in its own folder), R (the
newest: its record says the dataset is kept in A) and ``R 2``. A plan of
10,000 files that all have the same bytes took 15 seconds: where a file's
bytes are taken from was worked out again for each file, over all the
places that have them, and the time grew with the square of the files.
It is worked out once for each run of bytes now.

The suite plans 2,500 and 5,000 files. Twice the files should take twice
the time; four times is the square. Put 10,000 in ``SIZES`` to see three.
"""

import hashlib
import json
import time

import pytest

from chartbook import hashing, migrate_0_5
from chartbook import store as store_module
from tests.rich_store_of_0_5 import COMMIT, empty_store, folder_of

SIZES = (2500, 5000)


def _record(root, folder: str, day: str, letter: str, files: list, kept_in: str) -> None:
    """A record of one dataset of many files, as 0.5 wrote one: a part with its files, each with where it is kept."""
    entries = [{"path": f"_data/articles/{name}", "content_hash": content_hash, "size_bytes": size, "kept_in": kept_in} for name, content_hash, size in files]
    listing = hashing.hash_listing(hashing.FileEntry(name, size, content_hash) for name, content_hash, size in files)
    document = {
        "schema": "chartbook/snapshot/v2", "root": "acme/news", "made_at": f"{day}T09:15:00.000000Z",
        "code": {"commit": COMMIT[letter], "subdirectory": ""},
        "records": [{
            "id": "acme/news:dataframe:articles", "kind": "dataframe", "content_hash": listing.content_hash,
            "stored": {"at": "_data/articles", "single": False, "files": entries},
        }],
    }
    file = root / "pipelines" / "acme+news" / folder / "_chartbook" / "snapshot.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(document) + "\n", encoding="utf-8", newline="\n")


def found_shape(root, count: int, same_bytes: bool = False) -> None:
    a, b, r = folder_of("2025-10-01", "a"), folder_of("2025-10-02", "b"), folder_of("2025-11-01", "c")
    pipeline = root / "pipelines" / "acme+news"
    for folder in (a, b):
        (pipeline / folder / "_data" / "articles").mkdir(parents=True)
    files = []
    for number in range(count):
        data = b"the same bytes" if same_bytes else f"article {number:07d}".encode()
        name = f"{number:07d}.parquet"
        files.append((name, "sha256:" + hashlib.sha256(data).hexdigest(), len(data)))
        (pipeline / b / "_data" / "articles" / name).write_bytes(data)
        if number % 2 == 0:
            (pipeline / a / "_data" / "articles" / name).write_bytes(data)  # A has every other file, and no record
    _record(root, b, "2025-10-02", "b", files, b)
    _record(root, r, "2025-11-01", "c", files, a)
    second = pipeline / f"{r} 2" / "_chartbook" / "snapshot.json"
    second.parent.mkdir(parents=True)
    second.write_text((pipeline / r / "_chartbook" / "snapshot.json").read_text(encoding="utf-8").replace(f'"kept_in": "{a}"', f'"kept_in": "{b}"'), encoding="utf-8", newline="\n")
    store_module._read_records.clear()


def _timed(root) -> tuple:
    """A plan and its check, each with the time this process spent on it: the better of two, so that what else the machine does counts for less."""
    planned = checked = None
    for _ in range(2):
        store_module._read_records.clear()
        began = time.process_time()
        found = migrate_0_5.plan(root)
        took = time.process_time() - began
        planned = took if planned is None else min(planned, took)
        began = time.process_time()
        migrate_0_5.check(root, found)
        took = time.process_time() - began
        checked = took if checked is None else min(checked, took)
    return found, planned, checked


@pytest.mark.parametrize("same_bytes", [False, True], ids=["each file its own bytes", "every file the same bytes"])
def test_the_time_of_a_plan_grows_with_the_files_and_not_with_their_square(tmp_path, same_bytes):
    seconds = {}
    for count in SIZES:
        root = empty_store(tmp_path, f"store-{count}")
        found_shape(root, count, same_bytes)
        found, planned, checked = _timed(root)
        assert found.elsewhere == count // 2 and found.missing == []
        assert found.second_folders == [] and found.no_record == [("acme+news", folder_of("2025-10-01", "a"), (count + 1) // 2)]
        seconds[count] = planned
        print(f"\n{'the same bytes' if same_bytes else 'its own bytes  '} {count:6d} files in the dataset: plan {planned:6.2f} s, check {checked:5.2f} s, {len(found.steps)} steps, {found.renamed} renamed, {found.copied} copied")
    # Twice the files in twice the time, give or take; twice that is the square
    times, ratio = SIZES[-1] / SIZES[0], seconds[SIZES[-1]] / seconds[SIZES[0]]
    print(f"\n{times:g} times the files took {ratio:.1f} times the time")
    assert ratio < 1.6 * times, f"{times:g} times the files took {ratio:.1f} times as long: {seconds}"


# The whole command, where what it carries from one run to the next is as long as the store's files (the second review
# of the mover, 2026-11-20)

#: Four times the files should take about four times the time; sixteen times is the square
COMMAND_SIZES = (2000, 8000)


def _dataset(root, count: int, there: bool) -> tuple:
    """One snapshot of a dataset of *count* files, kept in its own folder; the files there or not. Its folder, and each file's name and bytes."""
    r = folder_of("2025-11-01", "c")
    files, entries = [], []
    folder = root / "pipelines" / "acme+news" / r / "_data" / "articles"
    folder.mkdir(parents=True)
    for number in range(count):
        data = f"article {number:07d}".encode()
        name = f"{number:07d}.parquet"
        files.append((name, data))
        entries.append((name, "sha256:" + hashlib.sha256(data).hexdigest(), len(data)))
        if there:
            (folder / name).write_bytes(data)
    _record(root, r, "2025-11-01", "c", entries, r)
    store_module._read_records.clear()
    store_module._found_whole.clear()
    return r, files


def _typed(root, monkeypatch) -> tuple:
    from click.testing import CliRunner

    from chartbook import config
    from chartbook.cli import main

    monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
    began = time.process_time()
    result = CliRunner().invoke(main, ["store", "migrate", "--yes"])
    return result, time.process_time() - began


def _second_run_once_the_files_have_come(tmp_path, count: int, monkeypatch) -> float:
    """A store is moved while a snapshot's files are missing (an upload that had not finished). The files then arrive under ``pipelines/``, and the command is typed again, as its last lines say. How long the command takes."""
    root = empty_store(tmp_path, f"late-{count}")
    r, files = _dataset(root, count, there=False)
    migrate_0_5.run(root)
    folder = root / "pipelines" / "acme+news" / r / "_data" / "articles"
    folder.mkdir(parents=True)
    for name, data in files:
        (folder / name).write_bytes(data)
    store_module._read_records.clear()
    assert len(migrate_0_5.plan(root).late) == count
    result, took = _typed(root, monkeypatch)
    assert result.exit_code == 0 and f"{count} file(s) arrived for a snapshot that is moved already, and went aside" in result.output, result.output[-600:]
    return took


def _first_run_with_every_file_in_place_too(tmp_path, count: int, monkeypatch) -> float:
    """Every file is at its old place and where it goes too (what a sync that copies and then removes has brought so far of a move made elsewhere). How long the command takes."""
    root = empty_store(tmp_path, f"in-place-{count}")
    r, files = _dataset(root, count, there=True)
    folder = root / "snapshots" / "acme+news" / r / "_data" / "articles"
    folder.mkdir(parents=True)
    for name, data in files:
        (folder / name).write_bytes(data)
    store_module._read_records.clear()
    assert len(migrate_0_5.plan(root).in_place) == count
    result, took = _typed(root, monkeypatch)
    assert result.exit_code == 0 and f"{count} file(s) a record names were not moved, a file being where each goes already" in result.output, result.output[-600:]
    return took


@pytest.mark.parametrize("shape", [_second_run_once_the_files_have_come, _first_run_with_every_file_in_place_too], ids=["the files arrive after the move", "every file is in place and at the old place"])
def test_the_time_of_the_command_grows_with_the_files_and_not_with_their_square(tmp_path, monkeypatch, shape):
    """What the journal carries from one run to the next was added to lists, each item looked for in the list first, and the lines for a person built a set once for every file that arrived: each the square of the files.

    With every file in place and at the old place, 4,000 files took 4.5 s
    and 16,000 took 43.7 s, which by the square is some seven minutes for
    the 55,000 of a real store.
    """
    seconds = {}
    for count in COMMAND_SIZES:
        seconds[count] = shape(tmp_path.resolve(), count, monkeypatch)
        print(f"\n{shape.__name__} {count:6d} files: the whole command {seconds[count]:6.2f} s")
    times, ratio = COMMAND_SIZES[-1] / COMMAND_SIZES[0], seconds[COMMAND_SIZES[-1]] / seconds[COMMAND_SIZES[0]]
    print(f"\n{times:g} times the files took {ratio:.1f} times the time")
    assert ratio < 1.6 * times, f"{times:g} times the files took {ratio:.1f} times as long: {seconds}"
