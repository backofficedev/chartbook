"""``chartbook snapshot`` decides how the store keeps a snapshot (``docs_src/design/snapshots-and-increments.md``, "Which one ``chartbook snapshot`` makes").

**A snapshot is kept as an increment until the increments since the last
complete snapshot, with this one, add up to the size of a complete one.
Then it is a complete one.** The rule is written once
(:func:`chartbook.snapshot.to_be_kept`) and asked of each store a snapshot
goes to. ``--complete`` makes a complete one whatever the rule would
choose. Nothing is written into a snapshot whose record is written, and an
increment builds on exactly one complete snapshot.
"""

import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, data, hashing, lock, snapshot
from chartbook import store as store_module
from chartbook.cli import _format_bytes, _when, main
from chartbook.refs import AssetRef
from chartbook.store import FolderStore
from tests.fixtures import _git
from tests.increments import with_increments

#: One of the design page's units, in bytes: a pipeline "of size 100" is a hundred files of this size
UNIT = 8
COMMIT = "a" * 40
PIN_LINE = "A pipeline that depends on this one gets it with `chartbook pin --update`."

posix = pytest.mark.skipif(os.name == "nt", reason="the build script here is POSIX shell")


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _at(number: int) -> str:
    """A time for the snapshot of that number: each a minute after the one before, all long past."""
    return f"2026-01-01T{number // 60:02d}:{number % 60:02d}:00.000000Z"


def _writable(function, path, _):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)  # what a store keeps is read-only
    function(path)


def _lose(path: Path) -> None:
    """A file of the store goes, as one a sync lost."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()
    store_module._found_whole.clear()


def _records(root: Path) -> list:
    """Every snapshot's record in a store, as it is now, oldest folder first."""
    store_module._read_records.clear()
    return FolderStore(root).records()


def _document(record) -> dict:
    return json.loads(Path(record.path).read_text(encoding="utf-8"))


def _own(record) -> dict:
    """The files a snapshot's own folder holds, as its record says: each path with its size."""
    return {
        file.path: file.size_bytes
        for asset in record.assets for file in asset.files if file.location.is_relative_to(record.folder)
    }


def _listed(record) -> dict:
    """Every file a snapshot's record lists: each path with its hash and its size."""
    return {file.path: (file.content_hash, file.size_bytes) for asset in record.assets for file in asset.files}


def _recorded(root: Path) -> dict:
    """Every file of every recorded snapshot's folder in a store, with its size and when it last changed."""
    found = {}
    for record in _records(root):
        for path in sorted(record.folder.rglob("*")):
            seen = path.lstat()
            found[path.relative_to(root).as_posix()] = (seen.st_size, seen.st_mtime_ns) if path.is_file() else "folder"
    return found


# A pipeline of exact sizes, written with the store's own writer as `snapshot.make` uses it


def _of_files(
    store: FolderStore, scratch: Path, files: list, number: int, complete: bool = False, made_by: str = "snapshot",
    made_at: str = None, now=None,
):
    """Write one snapshot of acme/sized of *files*, each ``(asset name, place in the pipeline, bytes)``.

    As :func:`chartbook.snapshot.make` writes one once every file of it is
    put: the store is asked how it is to keep it
    (:func:`chartbook.snapshot.to_be_kept`), told, and the record is
    written; one that is not written is let go. Nothing else is in it, so
    its size is exact.

    :param made_at: Its time, where it is not that of its *number*.
    :param now: What the clock of the machine that makes it says, where it is not right.
    :returns: How the store keeps it, as its record says.
    """
    owner = made_by == "snapshot"
    made_at = made_at or _at(number)
    pending = store.begin("acme/sized", COMMIT, made_at, made_by=made_by, **({"undecided": True} if owner else {}))
    try:
        assets, held = {}, {}
        scratch.mkdir(exist_ok=True)
        for name, place, content in files:
            local = AssetRef(kind="dataframe", name=name)
            source = scratch / f"{name}.bin"
            source.write_bytes(content)
            put = pending.put(source, place=place)
            assets[str(local)] = snapshot.asset_record(local.in_pipeline("acme/sized"), "acme/sized", f"./{place}", put, True)
            held[str(local)] = put.stored
        taken = snapshot.Snapshot("acme/sized", COMMIT, "", made_at, assets, stored={"records": held})
        if owner:
            decided = snapshot.to_be_kept(store, taken, complete, now)
            if decided.increment:
                pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
        path = pending.write({**taken.to_document(), **({} if owner else {"made_by": made_by})})
    except BaseException:
        pending.discard()
        raise
    return snapshot.as_kept(FolderStore(store.root), dataclasses.replace(taken, path=path))


def _sized(store: FolderStore, scratch: Path, versions: list, number: int, **how):
    """Write one snapshot of acme/sized: a file of UNIT bytes for each of *versions*, file i at the version given (:func:`_of_files`)."""
    files = [(f"f{file:03d}", f"data/f{file:03d}.bin", f"{file:03d}{version:05d}".encode()) for file, version in enumerate(versions)]
    return _of_files(store, scratch, files, number, **how)


def _same_30(k: int) -> list:
    """A pipeline of a hundred files of which the same thirty change at each snapshot: its versions at the k-th."""
    return [k] * 30 + [0] * 70


def _left_in_tmp(root: Path) -> list:
    """What is where the store keeps what is being written."""
    tmp = root / "_chartbook" / "tmp"
    return sorted(path.name for path in tmp.iterdir()) if tmp.is_dir() else []


def _unrecorded_folders(root: Path) -> list:
    """Every snapshot's folder under snapshots/ and increments/ that has no record."""
    return [
        folder.relative_to(root).as_posix()
        for tree in ("snapshots", "increments") for folder in sorted((root / tree).glob("*/*"))
        if folder.is_dir() and store_module.is_snapshot_folder(folder.name) and not (folder / "_chartbook" / "snapshot.json").is_file()
    ]


def _series(store, scratch, changes, count: int) -> list:
    """A first snapshot of a hundred files, and then *count* more, each after ``changes(k)`` has named the files that change for the k-th; how each is kept."""
    versions = [0] * 100
    kept = [_sized(store, scratch, versions, 0)]
    for k in range(1, count + 1):
        for file in changes(k):
            versions[file] += 1
        kept.append(_sized(store, scratch, versions, k))
    return kept


def _units(kept) -> list:
    """What each snapshot copied, in the page's units, with ``+`` for an increment: ``["100", "+10", "+20"]``."""
    return [f"{'+' if one.increment else ''}{one.own_bytes // UNIT}" for one in kept]


class TestTheRuleByItsNumbers:
    """The page's own table: a pipeline of size 100, and what each snapshot copies under the rule of adding up."""

    def test_a_different_10_each_time(self, store, work):
        """Increments of 10, 20 and 30, since each holds all that differs from the complete one; the fourth would bring the total to 100, so it is complete: 160 over four."""
        kept = _series(store, work / "files", lambda k: range((k - 1) * 10 % 100, (k - 1) * 10 % 100 + 10), 8)
        assert _units(kept) == ["100", "+10", "+20", "+30", "100", "+10", "+20", "+30", "100"]
        assert sum(one.own_bytes for one in kept[1:5]) == 160 * UNIT
        # What each increment's record carries: the total up to and with itself, beside what it builds on
        assert [one.increments_bytes // UNIT for one in kept] == [0, 10, 30, 60, 0, 10, 30, 60, 0]
        assert [one.added_up for one in kept] == [False] * 9  # as its record says it is kept: why is the decision's to say
        assert all(one.files == 100 and one.size_bytes == 100 * UNIT for one in kept)
        # Each increment is on the one complete snapshot before it, and on no increment
        folders = [one.folder.name for one in kept]
        assert [one.builds_on for one in kept] == [""] + [folders[0]] * 3 + [""] + [folders[4]] * 3 + [""]

    def test_the_same_30_each_time(self, store, work):
        """30, 30, 30, and the fourth is complete: 190 over four, 48 on average. The rule's price, beside the best there is."""
        kept = _series(store, work / "files", lambda k: range(30), 8)
        assert _units(kept) == ["100", "+30", "+30", "+30", "100", "+30", "+30", "+30", "100"]
        assert [one.increments_bytes // UNIT for one in kept[1:4]] == [30, 60, 90]
        assert round(sum(one.own_bytes for one in kept[1:5]) / 4 / UNIT) == 48

    def test_everything(self, store, work):
        """Every file differs each time: the increment would be the whole of it, so each is complete."""
        kept = _series(store, work / "files", lambda k: range(100), 3)
        assert _units(kept) == ["100", "100", "100", "100"]
        assert not (store.root / "increments").exists()

    def test_a_different_1_each_time(self, store, work):
        """1, 2, 3 and so on to 13, which add up to 91; the fourteenth would bring the total to 105, so it is complete: 14 on average."""
        kept = _series(store, work / "files", lambda k: [(k - 1) % 100], 15)
        assert _units(kept) == ["100"] + [f"+{k}" for k in range(1, 14)] + ["100", "+1"]
        assert kept[13].increments_bytes == 91 * UNIT
        assert round(sum(one.own_bytes for one in kept[1:15]) / 14 / UNIT) == 14

    def test_exactly_the_size_of_a_complete_one_is_complete(self, store, work):
        """50 and then another 50 on the same base: the two add up to 100, which is the size, and not less."""
        kept = _series(store, work / "files", lambda k: range(50), 2)
        assert _units(kept) == ["100", "+50", "100"]

    def test_the_decision_says_why_a_complete_one_is_complete(self, store, work):
        """The first, and one where every file differs, are complete with nothing to add up; one the increments led to says so."""
        versions = [0] * 100
        _sized(store, work / "files", versions, 0)
        taken = snapshot.read(_records(store.root)[0].path)
        first = snapshot.to_be_kept(FolderStore(work / "empty"), taken)
        assert not first.increment and not first.added_up and first.own_bytes == first.size_bytes == 100 * UNIT
        _sized(store, work / "files", [1] * 60 + [0] * 40, 1)
        newest = snapshot.read(_records(store.root)[-1].path)
        again = snapshot.to_be_kept(FolderStore(store.root), dataclasses.replace(newest, made_at=_at(2), path=None))
        assert not again.increment and again.added_up  # 60 and 60 more
        asked = snapshot.to_be_kept(FolderStore(store.root), taken, complete=True)
        assert not asked.increment and not asked.added_up

    def test_one_where_every_file_differs_is_not_said_to_have_added_up(self, store, work):
        """A complete snapshot, one tiny increment, and then every file is another: it is complete because the increment would be the whole of it, and the decision does not say the increments had added up to its size."""
        files = work / "files"
        _sized(store, files, [0] * 100, 0)
        small = _sized(store, files, [1] + [0] * 99, 1)
        assert small.increment and small.increments_bytes == UNIT

        def listed(versions: list, number: int):
            """A snapshot of those files, as its record lists them: written to a store of its own, and asked of this one."""
            elsewhere = FolderStore(work / f"elsewhere-{number}")
            _sized(elsewhere, files, versions, number)
            return snapshot.read(_records(elsewhere.root)[0].path)

        every = snapshot.to_be_kept(FolderStore(store.root), listed([5] * 100, 2))
        assert not every.increment and every.own_bytes == every.size_bytes == 100 * UNIT
        assert not every.added_up  # 8 bytes of increments had not added up to 800: every file differs
        # One file short of every file: less than the whole by itself, and with the increment before it, the whole
        nearly = snapshot.to_be_kept(FolderStore(store.root), listed([5] * 99 + [0], 3))
        assert not nearly.increment and nearly.added_up

    def test_a_snapshot_with_no_file_is_complete(self, store, work):
        _sized(store, work / "files", [0] * 3, 0)
        kept = _sized(store, work / "files", [], 1)
        assert not kept.increment and kept.files == 0


class TestWhatIsBuiltOn:
    """The base: the newest complete snapshot of the pipeline in that store that its owner made, of the same repository, whole, and not dated in the future."""

    def test_a_snapshot_a_pin_made_is_never_built_on_and_is_never_an_increment(self, store, work):
        files = work / "files"
        pinned = _sized(store, files, [0] * 10, 0, made_by="pin")
        assert not pinned.increment and pinned.folder.parent.parent.name == "snapshots"
        # The owner's first snapshot has the very files the pin's has, and is complete all the same
        first = _sized(store, files, [0] * 10, 1)
        assert not first.increment and first.own_files == 10
        # And the next builds on the owner's, though a pin made a complete one after it
        _sized(store, files, [0] * 9 + [5], 2, made_by="pin")
        second = _sized(store, files, [0] * 9 + [1], 3)
        assert second.builds_on == first.folder.name and second.own_files == 1
        # The writer refuses the other half outright
        with pytest.raises(store_module.StoreError):
            store.begin("acme/sized", COMMIT, _at(4), made_by="pin", builds_on=first.folder.name)
        with pytest.raises(ValueError):
            store.begin("acme/sized", COMMIT, _at(4), made_by="pin", undecided=True)
        assert {record.folder.name: record.made_by for record in _records(store.root) if record.increment} == {second.folder.name: "snapshot"}

    def test_a_complete_one_with_a_hole_is_not_built_on(self, store, work):
        files = work / "files"
        first = _sized(store, files, [0] * 10, 0)
        _lose(first.folder / "data" / "f003.bin")
        second = _sized(store, files, [0] * 9 + [1], 1)
        assert not second.increment and not second.added_up and second.own_files == 10
        assert not (first.folder / "data" / "f003.bin").exists()  # left as it is
        # The next is built on the newest that is whole
        third = _sized(store, files, [0] * 8 + [2, 1], 2)
        assert third.builds_on == second.folder.name and third.own_files == 1

    def test_the_newest_whole_one_is_built_on_where_a_newer_has_a_hole(self, store, work):
        files = work / "files"
        first = _sized(store, files, [0] * 10, 0)
        newer = _sized(store, files, [0] * 10, 1, complete=True)
        _lose(newer.folder / "data" / "f000.bin")
        third = _sized(store, files, [0] * 9 + [1], 2)
        assert third.builds_on == first.folder.name and third.own_files == 1

    def test_one_dated_in_the_future_is_not_built_on(self, store, work):
        files = work / "files"
        first = _sized(store, files, [0] * 10, 0)
        pending = store.begin("acme/sized", COMMIT, "2999-01-01T00:00:00.000000Z")
        source = files / "f000.bin"
        put = pending.put(source, place="data/f000.bin")
        local = AssetRef(kind="dataframe", name="f000")
        record = snapshot.asset_record(local.in_pipeline("acme/sized"), "acme/sized", "./data/f000.bin", put, True)
        ahead = snapshot.Snapshot("acme/sized", COMMIT, "", "2999-01-01T00:00:00.000000Z", {"f000": record}, stored={"records": {"f000": put.stored}})
        pending.write(ahead.to_document())
        second = _sized(store, files, [0] * 9 + [1], 1)
        assert second.builds_on == first.folder.name

    def test_one_of_another_repository_is_not_built_on(self, store, work):
        """As a snapshot's making tells two apart before it says they are one pipeline's: by what the records say of the repository."""
        _sized(store, work / "files", [0] * 10, 0)
        (taken,) = [snapshot.read(record.path) for record in _records(store.root)]
        ours = dataclasses.replace(taken, made_at=_at(1), path=None, repository="https://example.org/acme/sized", first_commit="b" * 40)
        assert not snapshot.to_be_kept(FolderStore(store.root), ours).increment  # the one there names neither
        theirs = dataclasses.replace(taken, made_at=_at(1), path=None)
        assert snapshot.to_be_kept(FolderStore(store.root), theirs).increment

    def test_another_pipelines_snapshots_are_not_looked_at(self, store, work):
        _sized(store, work / "files", [0] * 10, 0)
        (taken,) = [snapshot.read(record.path) for record in _records(store.root)]
        other = dataclasses.replace(taken, pipeline="acme/other", made_at=_at(1), path=None)
        assert not snapshot.to_be_kept(FolderStore(store.root), other).increment

    def test_one_under_snapshots_that_keeps_a_file_in_another_folder_is_not_built_on(self, store, work):
        """A pipeline's folder that ChartBook 0.5 laid out, copied into the store by hand: its later snapshot keeps files in the earlier one's folder, and is not complete, whatever folder it is under.

        Found by this step: taken for complete by its folder alone, it was
        built on, and the writer then stopped on a file that was not in it.
        """
        from tests.store_of_0_5 import laid_out_as_0_5

        files = work / "files"
        _sized(store, files, [0] * 10, 0, complete=True)
        _sized(store, files, [0] * 9 + [1], 1, complete=True)
        old = laid_out_as_0_5(store.root)  # the second now keeps nine of its files in the first one's folder
        new = FolderStore(work / "new")
        (new.root / "snapshots").mkdir(parents=True)
        (new.root / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8", newline="\n")
        shutil.copytree(old.root / "pipelines" / "acme+sized", new.root / "snapshots" / "acme+sized")
        first, second = _records(new.root)
        assert (first.complete, second.complete, second.increment) == (True, False, False) and FolderStore(new.root).verify() == []
        # The next is an increment on the first, the one of the two whose folder holds every file of it
        third = _sized(new, files, [0] * 9 + [2], 2)
        assert third.builds_on == first.folder.name and third.own_files == 1 and FolderStore(new.root).verify() == []
        # And a copy from another store does not build on the second either: with nothing else to build on, it is complete
        from chartbook.transfer import copy_snapshot

        source = FolderStore(work / "source")
        base = _sized(source, files, [0] * 9 + [1], 1)
        increment = _sized(source, files, [0] * 9 + [3], 3)
        assert increment.builds_on == base.folder.name
        (theirs,) = [snapshot.read(record.path) for record in _records(source.root) if record.increment]
        assert _document(second)["made_at"] == _at(1)  # the same moment as what it builds on where it comes from
        copied = copy_snapshot(theirs, FolderStore(source.root), FolderStore(new.root))
        (record,) = [one for one in _records(new.root) if one.path == Path(copied)]
        assert not record.increment and len(_own(record)) == 10 and FolderStore(new.root).verify() == []

    def test_two_made_at_one_instant_are_two_snapshots_whichever_way_each_is_kept(self, store, work):
        """The second has the next second's folder name. Kept as an increment, it is not taken for the first one kept twice.

        Found by this step: the store told "the same snapshot in both
        folders" by pipeline, commit and time alone, and did not list it.
        """
        files = work / "files"
        first = _sized(store, files, [0] * 10, 0)
        pending = store.begin("acme/sized", COMMIT, _at(0), undecided=True)
        source = files / "f009.bin"
        source.write_bytes(b"00900001")
        assets, held = {}, {}
        for file in range(10):
            local = AssetRef(kind="dataframe", name=f"f{file:03d}")
            put = pending.put(files / f"{local.name}.bin", place=f"data/{local.name}.bin")
            assets[str(local)] = snapshot.asset_record(local.in_pipeline("acme/sized"), "acme/sized", f"./data/{local.name}.bin", put, True)
            held[str(local)] = put.stored
        taken = snapshot.Snapshot("acme/sized", COMMIT, "", _at(0), assets, stored={"records": held})
        decided = snapshot.to_be_kept(store, taken)
        pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
        pending.write(taken.to_document())
        records = _records(store.root)
        assert [(record.increment, record.made_at) for record in records] == [(False, _at(0)), (True, _at(0))]
        assert records[1].builds_on == first.folder.name != records[1].folder.name
        fresh = FolderStore(store.root)
        assert fresh.doubled_in(fresh.pipeline_path("acme/sized")) == [] and fresh.verify() == []
        assert len(snapshot.find(fresh, COMMIT, "")) == 2

    def test_an_increments_own_file_is_found_under_the_name_the_disk_gives_it(self, store, work, monkeypatch):
        """A sync between macOS and Linux may write a name in the other of Unicode's forms. A snapshot being made asks, from the folder of complete snapshots, whether an increment has a file whole: by the name the disk has it under.

        Found by this step: only the two folders of an increment's own
        record were looked under, so such a file was taken for missing,
        and each `chartbook snapshot` of the same files made a new one.
        """
        import unicodedata

        from tests.test_shared_store import _names_as_linux_tells_them

        composed, decomposed = (unicodedata.normalize(form, "Zürich.bin") for form in ("NFC", "NFD"))
        own = store.root / "increments" / "acme+sized" / "2026-01-01T000100Z_aaaaaaaaaaaa" / "data"
        own.mkdir(parents=True)
        (own / decomposed).write_bytes(b"x" * 10)
        file = store_module.KeptFile(composed, f"data/{composed}", 10, "sha256:" + "0" * 64, own / composed)
        _names_as_linux_tells_them(monkeypatch)
        asked_from = store.root / "snapshots" / "acme+sized"
        assert store_module._on_disk_where_kept(file, asked_from).name == decomposed
        assert store_module._on_disk_where_kept(file, own.parent.parent).name == decomposed  # and from its own folder, as before


class TestTheCount:
    """What the increments have added up to is kept in the records: each increment's says the total up to and with itself, and the count is the largest any increment on that complete snapshot carries."""

    def test_an_increment_dated_ahead_does_not_stop_the_count(self, store, work):
        """One machine's clock was ahead when it made an increment. Every later increment on that complete snapshot still adds to the count: 30 (the one dated ahead), 60, 90, and the next is complete, as the page's table has it."""
        files = work / "files"
        first = _sized(store, files, _same_30(0), 0)
        ahead = _sized(store, files, _same_30(1), 1, made_at="2027-06-01T00:00:00.000000Z")  # a clock that was ahead
        assert ahead.increment and ahead.builds_on == first.folder.name and ahead.increments_bytes == 30 * UNIT
        kept = [_sized(store, files, _same_30(k), k) for k in range(2, 5)]
        assert [(one.increment, one.increments_bytes // UNIT) for one in kept] == [(True, 60), (True, 90), (False, 0)]

    def test_it_does_not_go_back_where_the_newest_increment_carries_a_smaller_one(self, store, work):
        """Two machines share the store. One had not been brought the other's increments, and wrote one that counts from zero; it is the newest. The next counts on from the largest count on that complete snapshot: what the records say was copied."""
        files = work / "files"
        first = _sized(store, files, _same_30(0), 0)
        one, two = (_sized(store, files, _same_30(k), k) for k in (1, 2))
        assert (one.increments_bytes, two.increments_bytes) == (30 * UNIT, 60 * UNIT)
        aside = work / "aside"
        aside.mkdir()
        for kept in (one, two):
            os.rename(kept.folder, aside / kept.folder.name)
        three = _sized(FolderStore(store.root), files, _same_30(3), 3)  # the other machine's, written with neither in sight
        assert three.increment and three.builds_on == first.folder.name and three.increments_bytes == 30 * UNIT
        for kept in (one, two):
            os.rename(aside / kept.folder.name, kept.folder)  # the sync brings both
        assert [record.increments_bytes // UNIT for record in _records(store.root) if record.increment] == [30, 60, 30]
        four = _sized(FolderStore(store.root), files, _same_30(4), 4)
        assert four.increment and four.increments_bytes == 90 * UNIT  # 60, the largest there, and 30 more
        assert not _sized(FolderStore(store.root), files, _same_30(5), 5).increment

    def test_an_increment_made_by_a_clock_that_is_behind_is_counted_too(self, store, work):
        """The complete snapshot was made by a machine whose clock is right; another, nine minutes behind (within the ten a snapshot may be dated ahead and still be built on), makes the increments. Each is dated before the snapshot it builds on, and each adds to the count."""
        from datetime import datetime, timezone

        files = work / "files"
        first = _sized(store, files, _same_30(0), 20)  # made at 00:20
        kept = [
            _sized(store, files, _same_30(k), 10 + k, now=datetime(2026, 1, 1, 0, 10 + k, tzinfo=timezone.utc))  # dated 00:11 to 00:14
            for k in range(1, 5)
        ]
        assert all(one.builds_on == first.folder.name and one.folder.name < first.folder.name for one in kept[:3])
        assert [(one.increment, one.increments_bytes // UNIT) for one in kept] == [(True, 30), (True, 60), (True, 90), (False, 0)]

    @pytest.mark.parametrize("by", ["store move", "store import"])
    def test_increments_copied_to_another_store_carry_no_count_and_the_next_counts_from_its_own(self, store, work, by):
        """A pipeline keeps its form in the other store, each complete snapshot and then the increments on it. The count is of what snapshots made in a store copied: an increment copied in carries none, and the next snapshot made there counts from what that store's own increments carry."""
        from chartbook.sharing import copy_snapshots
        from chartbook.transfer import copy_snapshot

        files = work / "files"
        kept = [_sized(store, files, _same_30(k), k) for k in range(4)]
        assert [one.increments_bytes // UNIT for one in kept] == [0, 30, 60, 90]
        other = FolderStore(work / "other")
        if by == "store move":
            whole: set = set()
            for record in sorted(_records(store.root), key=lambda record: record.increment):
                copy_snapshot(snapshot.read(record.path), FolderStore(store.root), other, whole=whole)
        else:
            assert copy_snapshots(_records(store.root), other).refused == []
        there = _records(other.root)
        assert [(record.increment, record.increments_bytes) for record in there] == [(False, 0), (True, 0), (True, 0), (True, 0)]
        # No count at all is in what a copy wrote: its record says what it builds on, and no more
        base = there[0].folder.name
        assert [_document(record).get("stored") for record in there] == [None] + [{"builds_on": base}] * 3
        # Where it came from the next one is complete, 90 and 30 more. Where it was copied to, the count starts again:
        # an increment that counts from its own, and the one after it counts on from that
        assert not _sized(FolderStore(store.root), files, _same_30(4), 4).increment
        nxt = _sized(FolderStore(other.root), files, _same_30(4), 4)
        assert nxt.increment and nxt.builds_on == base and nxt.increments_bytes == 30 * UNIT
        assert _sized(FolderStore(other.root), files, _same_30(5), 5).increments_bytes == 60 * UNIT

    def test_only_some_of_the_increments_copied_the_next_is_kept_by_what_this_store_has(self, store, work):
        """`store export --snapshot` of the complete one and the last of three increments, then `store import`. The store imported into has one complete snapshot of 100 and one increment of 30, and the next changes the same 30: an increment, by the sizes of what is there (60 of 100) and by the count, which starts again in this store (30). With the count the last increment carried where it was made (90), it was made complete, and said to be so because the increments had added up, in a store where they had not."""
        from chartbook import sharing

        files = work / "files"
        other = FolderStore(work / "source")
        kept = [_sized(other, files, _same_30(k), k) for k in range(4)]
        assert [one.increments_bytes // UNIT for one in kept] == [0, 30, 60, 90]
        out = work / "out"
        done = sharing.export(FolderStore(other.root), "acme/sized", out, [f"{COMMIT}@{_at(0)}", f"{COMMIT}@{_at(3)}"])
        assert len(done.copied) == 2 and done.refused == []
        assert sharing.import_snapshots(FolderStore(store.root), out).refused == []
        there = _records(store.root)
        assert [(record.increment, sum(_own(record).values()) // UNIT, record.increments_bytes) for record in there] == [(False, 100, 0), (True, 30, 0)]
        (taken,) = [snapshot.read(record.path) for record in _records(other.root) if record.made_at == _at(3)]
        decided = snapshot.to_be_kept(FolderStore(store.root), dataclasses.replace(taken, made_at=_at(4), path=None))
        # In this store 30 bytes of increments were copied, and this one is 30 more of 100
        assert decided.increment and not decided.added_up and decided.increments_bytes == 30 * UNIT
        nxt = _sized(FolderStore(store.root), files, _same_30(4), 4)
        assert nxt.increment and nxt.increments_bytes == 30 * UNIT

    def test_it_is_in_the_record_where_the_store_says_how_it_keeps_the_snapshot(self, store, work):
        files = work / "files"
        first = _sized(store, files, [0] * 10, 0)
        second = _sized(store, files, [0] * 9 + [1], 1)
        records = {record.folder.name: record for record in _records(store.root)}
        assert _document(records[second.folder.name])["stored"] == {"builds_on": first.folder.name, "increments_bytes": UNIT}
        assert "stored" not in _document(records[first.folder.name])
        assert records[second.folder.name].increments_bytes == UNIT and records[first.folder.name].increments_bytes == 0
        # The same snapshot kept complete in another store has the same record less `stored`
        other = FolderStore(work / "other")
        from chartbook.transfer import copy_snapshot

        there = copy_snapshot(snapshot.read(records[second.folder.name].path), FolderStore(store.root), other, complete=True)

        def less_stored(document: dict) -> dict:
            parts = [*document["records"], *(document[name] for name in ("index", "documents") if name in document)]
            for part in parts:
                part.pop("stored", None)
            document.pop("stored", None)
            return document

        assert less_stored(json.loads(Path(there).read_text(encoding="utf-8"))) == less_stored(_document(records[second.folder.name]))

    def test_it_survives_the_removal_of_an_older_increment(self, store, work):
        files = work / "files"
        versions = [0] * 100
        first = _sized(store, files, versions, 0)
        one = _sized(store, files, [1] * 30 + [0] * 70, 1)
        two = _sized(store, files, [2] * 30 + [0] * 70, 2)
        assert (one.increments_bytes, two.increments_bytes) == (30 * UNIT, 60 * UNIT)
        fresh = FolderStore(store.root)
        assert fresh.remove_snapshot(one.folder / "_chartbook" / "snapshot.json")
        fresh.tidy_pipeline("acme/sized")
        assert not one.folder.exists()
        # 60 were copied, whatever is left of them: 30 more is 90, and the one after that is complete
        three = _sized(store, files, [3] * 30 + [0] * 70, 3)
        assert three.increment and three.increments_bytes == 90 * UNIT and three.builds_on == first.folder.name
        four = _sized(store, files, [4] * 30 + [0] * 70, 4)
        assert not four.increment and four.own_bytes == 100 * UNIT

    def test_a_record_may_be_anyones_and_what_is_no_count_counts_for_nothing(self, store, work):
        files = work / "files"
        _sized(store, files, [0] * 10, 0)
        second = _sized(store, files, [0] * 9 + [1], 1)
        record = second.folder / "_chartbook" / "snapshot.json"
        for written in (-5, True, "many", 1.5, None):
            document = json.loads(record.read_text(encoding="utf-8"))
            document["stored"]["increments_bytes"] = written
            os.chmod(record, stat.S_IWRITE | stat.S_IREAD)
            record.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
            (kept,) = [one for one in _records(store.root) if one.increment]
            assert kept.increments_bytes == 0 and kept.builds_on  # and it is the increment it was


# A pipeline as the design page's: a table, a chart and two documents, which with its index make five files


def _commit(folder: Path, message: str = "Work") -> None:
    if not (folder / ".git").exists():
        _git(folder, "init", "--quiet", "-b", "main")
    _git(folder, "add", "-A")
    _git(folder, "commit", "--quiet", "--allow-empty", "-m", message)


def _table(folder: Path, days: int) -> None:
    pl.DataFrame({"day": list(range(days)), "rate": [4.0 + day / 10 for day in range(days)]}).write_parquet(
        folder / "_data" / "treasury.parquet"
    )


def _chart(folder: Path, text: str) -> None:
    """The chart, drawn again: far larger than the table and the documents beside it."""
    (folder / "_output" / "curve.html").write_text(f"<p>{text}</p>\n" + "<!-- a curve -->\n" * 2000, encoding="utf-8", newline="\n")


#: A build that writes nothing and succeeds: what is on disk is what a test put there
MANIFEST = {
    "project": {"id": "acme/rates"},
    "scripts": {"build": "echo built"},
    "dataframes": {"treasury": {"path": "./_data/treasury.parquet", "docs": "d"}},
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "treasury", "docs": "d"}},
}


@pytest.fixture
def rates(work, store, monkeypatch):
    """The page's pipeline, built and committed; git ignores what is built. Commands are typed in its folder."""
    folder = work / "rates"
    (folder / "_data").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(tomli_w.dumps(MANIFEST), encoding="utf-8", newline="\n")
    (folder / "README.md").write_text("# acme/rates\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _table(folder, 3)
    _chart(folder, "one")
    _commit(folder)
    monkeypatch.chdir(folder)
    return folder


def _everything_differs(folder: Path, text: str) -> None:
    """Every file a snapshot of the pipeline lists is another: its table, its chart, and both documents."""
    _table(folder, 5 + len(text))
    _chart(folder, text)
    (folder / "README.md").write_text(f"# acme/rates, {text}\n", encoding="utf-8", newline="\n")
    manifest = folder / "chartbook.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + f"\n# {text}\n", encoding="utf-8", newline="\n")
    _commit(folder, text)


def _snapshot(*arguments: str):
    return CliRunner().invoke(main, ["snapshot", "--as-is", "--no-gc-reminder", *arguments])


def _made(result) -> list:
    """What a command said of the snapshot it made: its line that begins "Snapshot made", and every line after it on standard output."""
    lines = result.stdout.splitlines()
    (first,) = [number for number, line in enumerate(lines) if line.startswith(("Snapshot made", "No new snapshot"))]
    return lines[first:]


class TestThroughMake:
    """The same rule where `snapshot.make` asks it, of a pipeline with its documents and its index."""

    def test_the_first_is_complete_and_one_where_little_changed_is_an_increment(self, rates, store):
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        assert first.made and not first.kept.increment and not first.kept.added_up
        assert first.kept.files == first.kept.own_files == 5 and first.kept.folder == store.root / "snapshots" / "acme+rates" / first.kept.folder.name
        _chart(rates, "two")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert second.made and second.kept.increment and second.kept.builds_on == first.kept.folder.name
        assert second.kept.rest_made_at == _at(0) and (second.kept.own_files, second.kept.files) == (2, 5)
        assert second.kept.folder == store.root / "increments" / "acme+rates" / second.kept.folder.name
        (record,) = [one for one in _records(store.root) if one.increment]
        assert sorted(_own(record)) == ["_chartbook/index.json", "_output/curve.html"]
        assert second.kept.own_bytes == sum(_own(record).values()) == _document(record)["stored"]["increments_bytes"]
        assert sorted(path.relative_to(record.folder).as_posix() for path in record.folder.rglob("*") if path.is_file()) == [
            "_chartbook/INCREMENT.txt", "_chartbook/index.json", "_chartbook/snapshot.json", "_output/curve.html",
        ]
        # To whatever reads it, it is a snapshot like any other: whole, and the newest
        fresh = FolderStore(store.root)
        assert fresh.holes_of(record.path) == [] and fresh.verify() == []
        assert second.snapshot == snapshot.newest_for(rates, fresh)[0]
        # What the report's snapshot says of where each file is kept is what the record says
        kept_in = {entry["path"]: entry["kept_in"] for part in second.snapshot.stored["records"].values() for entry in part["files"]}
        assert kept_in == {"_data/treasury.parquet": first.kept.folder.name, "_output/curve.html": second.kept.folder.name}

    def test_every_snapshot_is_kept_as_the_numbers_in_the_records_say(self, rates, store):
        """Six snapshots, the chart drawn again for each: by each record's own sizes, an increment while the total is under the size, and then a complete one."""
        added, kinds = 0, []
        base = None
        for number in range(6):
            _chart(rates, f"drawn {number}")
            report = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(number))
            (record,) = [one for one in _records(store.root) if one.made_at == _at(number)]
            size = sum(size for _, size in _listed(record).values())
            assert report.kept.size_bytes == size and report.kept.files == len(_listed(record))
            if base is None:
                assert not record.increment and not report.kept.added_up
            else:
                has = set(_listed(base).values())
                own = sum(size for content in _listed(record).values() for size in [content[1]] if content not in has)
                assert record.increment == (added + own < size)
                if record.increment:
                    added += own
                    assert record.builds_on == base.folder.name and record.increments_bytes == added
                    assert sum(_own(record).values()) == own == report.kept.own_bytes
                else:
                    assert report.kept.added_up and sum(_own(record).values()) == size
            if not record.increment:
                base, added = record, 0
            kinds.append(record.increment)
        assert kinds == [False, True, False, True, False, True]  # the chart is most of it: two of them add up
        assert FolderStore(store.root).verify() == []

    def test_one_where_every_file_differs_is_complete(self, rates, store):
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _everything_differs(rates, "again")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert second.made and not second.kept.increment and not second.kept.added_up
        assert second.kept.own_bytes == second.kept.size_bytes and not (store.root / "increments").exists()
        assert first.kept.folder.is_dir()

    def test_after_a_store_that_a_migrate_left_the_next_counts_from_zero(self, rates, store):
        """The increments a migrate makes are older than the snapshot they build on, and carry no count."""
        for number, text in enumerate(("one", "two", "three")):
            _chart(rates, text)
            # Complete, for tests/increments.py to turn into the shape a migrate leaves
            assert not snapshot.make(rates, store=FolderStore(store.root), made_at=_at(number), complete=True).kept.increment
        complete, increments = with_increments(store.root, "newest")["acme+rates"]
        assert len(increments) == 2 and all(record.increments_bytes == 0 for record in _records(store.root))
        _chart(rates, "four")
        report = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(3))
        assert report.kept.increment and report.kept.builds_on == complete.name
        assert report.kept.increments_bytes == report.kept.own_bytes  # nothing was counted before it

    def test_no_file_is_read_to_decide(self, rates, store, monkeypatch):
        """The kind is decided from hashes and sizes: nothing is hashed while it is, and an increment costs no read of a pipeline's file that a complete snapshot of the same files does not."""
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        read: list = []
        while_deciding: list = []
        real, decide = hashing._file_hex, snapshot.to_be_kept

        def counting(path, *args, **kwargs):
            read.append(Path(path).resolve())
            return real(path, *args, **kwargs)

        def deciding(*args, **kwargs):
            before = len(read)
            kept = decide(*args, **kwargs)
            while_deciding.append(len(read) - before)
            return kept

        monkeypatch.setattr(hashing, "_file_hex", counting)
        monkeypatch.setattr(snapshot, "to_be_kept", deciding)
        counts = []
        for number, complete in ((1, True), (2, False)):
            _chart(rates, f"drawn {number}")
            read.clear()
            report = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(number), complete=complete)
            assert report.kept.increment is not complete
            counts.append(sorted((path.relative_to(rates).as_posix(), read.count(path)) for path in set(read) if path.is_relative_to(rates)))
        assert while_deciding == [0, 0]
        assert counts[0] == counts[1] and {"_data/treasury.parquet", "_output/curve.html"} <= {name for name, _ in counts[1]}


class TestComplete:
    """`--complete`: a complete snapshot whatever the rule would choose."""

    def test_the_function(self, rates, store):
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1), complete=True)
        assert second.made and second.asked_complete and not second.kept.increment and not second.kept.added_up
        assert second.kept.folder.parent == first.kept.folder.parent and (second.kept.folder / "_data" / "treasury.parquet").is_file()
        assert not (store.root / "increments").exists()

    def test_chartbook_snapshot_complete(self, rates, store):
        assert _snapshot().exit_code == 0
        _chart(rates, "two")
        result = _snapshot("--complete")
        assert result.exit_code == 0, result.output
        newest = _records(store.root)[-1]
        assert not newest.increment and len(_records(store.root)) == 2
        assert _made(result) == [f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}.", f"  {newest.folder}"]

    @posix
    def test_chartbook_run_snapshot_complete_and_without_it_the_rule(self, rates, store):
        run = lambda *arguments: CliRunner().invoke(main, ["run", "--snapshot", "--no-gc-reminder", *arguments])  # noqa: E731
        assert run().exit_code == 0
        _chart(rates, "two")
        ruled = run()
        assert ruled.exit_code == 0, ruled.output
        assert [record.increment for record in _records(store.root)] == [False, True]
        assert "Snapshot made, kept as an increment: 2 of 5 files" in ruled.output
        _chart(rates, "three")
        asked = run("--complete")
        assert asked.exit_code == 0, asked.output
        newest = max(_records(store.root), key=lambda record: record.made_at)
        assert not newest.increment and snapshot.read(newest.path).built_by_run
        lines = asked.stdout.splitlines()
        at = lines.index(f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}.")
        assert lines[at + 1] == f"  {newest.folder}" and PIN_LINE not in lines

    def test_a_plain_run_takes_no_complete(self, rates, store):
        result = CliRunner().invoke(main, ["run", "--complete"])
        assert result.exit_code == 2 and _records(store.root) == []
        assert result.output.splitlines()[-1] == "Error: --complete goes with --snapshot: `chartbook run --snapshot --complete`."
        checked = CliRunner().invoke(main, ["run", "--check", "--complete"])
        assert checked.exit_code == 2 and "--check runs nothing, so it does not go with --complete." in checked.output

    def test_both_commands_name_the_option(self):
        for command in ("snapshot", "run"):
            said = CliRunner().invoke(main, [command, "--help"], prog_name="chartbook").output
            assert "--complete" in said


class TestNothingChanged:
    """The same commit, bytes and pins as a whole snapshot the store has: no new one, of whichever kind that one is."""

    def test_the_one_stood_on_may_be_an_increment(self, rates, store):
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert second.kept.increment
        before = _recorded(store.root)
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(2))
        assert not again.made and again.snapshot == second.snapshot and again.kept.increment
        assert _recorded(store.root) == before
        result = _snapshot()
        assert result.exit_code == 0 and _made(result) == [
            f"No new snapshot: the same bytes and the same pins as the one made {_when(_at(1))}."
        ]
        assert _recorded(store.root) == before

    def test_asked_for_complete_a_new_one_is_made_and_the_increment_is_left_as_it_is(self, rates, store):
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        before = _recorded(store.root)
        result = _snapshot("--complete")
        assert result.exit_code == 0, result.output
        records = _records(store.root)
        newest = max(records, key=lambda record: record.made_at)
        assert len(records) == 3 and not newest.increment and newest.folder.parent.parent.name == "snapshots"
        assert snapshot.read(newest.path).content() == second.snapshot.content()
        assert _made(result) == [f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}.", f"  {newest.folder}"]
        # Never completed in its place: every recorded folder is as it was
        after = _recorded(store.root)
        assert {path: seen for path, seen in after.items() if path in before} == before
        assert second.kept.folder.is_dir() and FolderStore(store.root).builds_on(second.snapshot.path) is not None
        # And now there is a complete one of these files: asked again, no new one, and where it is
        again = _snapshot("--complete")
        assert _made(again) == [
            f"No new snapshot: the same bytes and the same pins as the one made {_when(newest.made_at)}.", f"  {newest.folder}",
        ]
        assert len(_records(store.root)) == 3


class TestThePromise:
    """Nothing is written into a snapshot whose record is written; a snapshot's name is its own across both folders; an increment builds on one complete snapshot."""

    def _gone_once_decided(self, monkeypatch, damage):
        """Do *damage* to the snapshot a new one is to build on, between the decision and the writing of its record."""
        real = snapshot.to_be_kept
        decided = []

        def deciding(store, taken, complete=False, now=None):
            kept = real(store, taken, complete, now)
            if kept.increment:
                damage(store.root / "snapshots" / "acme+rates" / kept.builds_on)
                store_module._found_whole.clear()
            decided.append(kept)
            return kept

        monkeypatch.setattr(snapshot, "to_be_kept", deciding)
        return decided

    def test_the_one_it_was_to_build_on_gone_before_its_record_is_written(self, rates, store, monkeypatch):
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        decided = self._gone_once_decided(monkeypatch, lambda folder: shutil.rmtree(folder, onerror=_writable))
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert [kept.increment for kept in decided] == [True] and not first.kept.folder.exists()
        # Written complete: every file of it was at hand
        assert second.made and not second.kept.increment and not second.kept.added_up and second.kept.own_files == 5
        (record,) = _records(store.root)
        assert record.folder == second.kept.folder and "stored" not in _document(record)
        assert FolderStore(store.root).verify() == [] and not any((store.root / "increments").rglob("*.html"))
        assert all(entry["kept_in"] == record.folder.name for part in second.snapshot.stored["records"].values() for entry in part["files"])

    def test_the_one_it_was_to_build_on_losing_a_file_before_its_record_is_written(self, rates, store, monkeypatch):
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        before = _recorded(store.root)
        table = "snapshots/acme+rates/" + first.kept.folder.name + "/_data/treasury.parquet"
        self._gone_once_decided(monkeypatch, lambda folder: _lose(folder / "_data" / "treasury.parquet"))
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert second.made and not second.kept.increment and (second.kept.folder / "_data" / "treasury.parquet").is_file()
        # The one with the hole is left as it is, and nothing was written into it
        after = _recorded(store.root)
        assert {path: seen for path, seen in after.items() if path in before} == {path: seen for path, seen in before.items() if path != table}
        assert FolderStore(store.root).verify_snapshot(second.snapshot.path) == []

    def test_nothing_is_written_into_a_recorded_folder_whatever_is_made(self, rates, store):
        """A complete one, increments, the complete one they add up to, one asked for complete: after each, every folder that had a record is as it was."""
        before = {}
        for number, complete in enumerate((False, False, False, False, True, False)):
            _chart(rates, f"drawn {number}")
            report = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(number), complete=complete)
            assert report.made
            after = _recorded(store.root)
            assert {path: seen for path, seen in after.items() if path in before} == before
            before = after
        records = _records(store.root)
        assert [record.increment for record in records] == [False, True, False, True, False, True]
        # A name is in one of the two folders, and each increment builds on a complete snapshot, never on an increment
        names = [record.folder.name for record in records]
        assert len(set(names)) == len(names)
        complete = {record.folder.name for record in records if not record.increment}
        assert all(record.builds_on in complete for record in records if record.increment)

    def test_a_snapshot_that_says_nothing_new_leaves_nothing_in_the_store(self, rates, store):
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        files = sorted(path.relative_to(store.root).as_posix() for path in store.root.rglob("*"))
        assert not snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1)).made
        assert sorted(path.relative_to(store.root).as_posix() for path in store.root.rglob("*")) == files

    def test_the_line_for_a_person_is_in_an_increments_folder_before_its_record(self, rates, store, monkeypatch):
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        seen = []
        real = store_module.replace_when_let

        def watching(source, target, *args, **kwargs):
            if Path(target).name == "snapshot.json":
                seen.append(sorted(path.name for path in Path(target).parent.iterdir() if path.name != Path(source).name))
            return real(source, target, *args, **kwargs)

        monkeypatch.setattr(store_module, "replace_when_let", watching)
        assert snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1)).kept.increment
        assert seen == [["INCREMENT.txt", "index.json"]]

    def test_a_gc_that_takes_what_it_builds_on_just_before_it_looks_there_leaves_it_complete(self, rates, store, monkeypatch):
        """`store gc` removes the snapshot it was to build on after the writer has seen that one's record, and before it has looked at that one's files. Every file is then its own, and it is written complete, under snapshots/: never an increment on a snapshot that has gone."""
        first, second, third = _healed(rates, store.root)
        _chart(rates, "four")
        real = store_module._FolderPending._settle

        def settling(self):
            _gc(self.store.root)
            return real(self)

        monkeypatch.setattr(store_module._FolderPending, "_settle", settling)
        fourth = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(3))
        (record,) = [one for one in _records(store.root) if one.made_at == _at(3)]
        assert not second.kept.folder.exists()  # the gc removed the one it was to build on, whole
        assert fourth.made and not fourth.kept.increment and not record.increment
        assert record.folder.parent.parent.name == "snapshots" and len(_own(record)) == 5 and "stored" not in _document(record)
        assert FolderStore(store.root).verify_snapshot(record.path) == []
        assert _unrecorded_folders(store.root) == [] and _left_in_tmp(store.root) == []

    def test_a_gc_that_takes_what_it_builds_on_as_its_files_come_in_stops_it(self, rates, store, monkeypatch):
        """`store gc` removes the snapshot it builds on once the increment has looked at what that one has, as its own files come into its folder. An increment's record is written only while the record of what it builds on is there: this one is not written, nothing of it is left, and made again it is whole."""
        first, second, third = _healed(rates, store.root)
        _chart(rates, "four")
        real = store_module._FolderPending._complete

        def completing(self):
            if self.builds_on is not None:
                _gc(self.store.root)
            return real(self)

        with monkeypatch.context() as patched:
            patched.setattr(store_module._FolderPending, "_complete", completing)
            with pytest.raises(store_module.StoreError) as stopped:
                snapshot.make(rates, store=FolderStore(store.root), made_at=_at(3))
        assert not isinstance(stopped.value, store_module.BuiltOnGoneError)  # nothing of it is at hand to write it complete from
        assert second.kept.folder.name in str(stopped.value) and str(stopped.value).endswith(
            ", which this one builds on, went from the store as this snapshot was being written. Run the command again."
        )
        # The gc took its record, and left the files this one had noted it was using for a later gc to clear
        assert not (second.kept.folder / "_chartbook" / "snapshot.json").exists()
        # Nothing of the new one is left: no record, no folder of its own, nothing where the store keeps what is being written
        assert [record.made_at for record in _records(store.root)] == [_at(0), _at(2)]
        assert _unrecorded_folders(store.root) == [second.kept.folder.relative_to(store.root).as_posix()]
        assert _left_in_tmp(store.root) == []
        # Made again, it is decided on what is there now
        again = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(4))
        (record,) = [one for one in _records(store.root) if one.made_at == _at(4)]
        assert again.made and FolderStore(store.root).verify_snapshot(record.path) == []
        on = FolderStore(store.root).builds_on(record.path)
        assert on is None or on.is_file()
        assert FolderStore(store.root).verify() == []

    def test_interrupted_just_after_a_file_is_written_aside_it_leaves_nothing_there(self, rates, store, monkeypatch):
        """Ctrl-C lands between the moment a file's copy is written aside and the moment whoever asked for it has it. A file written aside is on the snapshot's list before anything else is done with it, so letting the snapshot go removes it."""
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        real = store_module._FolderPending._written_aside
        written = []

        def interrupted(self, *args, **kwargs):
            written.append(real(self, *args, **kwargs)[0])
            raise KeyboardInterrupt

        with monkeypatch.context() as patched:
            patched.setattr(store_module._FolderPending, "_written_aside", interrupted)
            with pytest.raises(KeyboardInterrupt):
                snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert len(written) == 1 and not written[0].exists()
        assert _left_in_tmp(store.root) == [] and _unrecorded_folders(store.root) == [] and len(_records(store.root)) == 1


def _gc(root: Path):
    """Plan a `store gc` of a store and carry it out, sparing nothing for being new; what it did."""
    plan = lock.plan_gc(FolderStore(root), recent_seconds=0)
    return lock.carry_out_gc(plan, FolderStore(root))


def _healed(rates: Path, root: Path) -> tuple:
    """A store in which the snapshot the next one builds on is one `store gc` may remove; its three snapshots.

    A complete snapshot; a second complete one that had not been brought
    whole when the third was made, so that the third is an increment on
    the first; and then the second is whole after all. The next snapshot
    builds on the second, which is neither the newest nor built on yet.
    """
    first = snapshot.make(rates, store=FolderStore(root), made_at=_at(0))
    _chart(rates, "two")
    second = snapshot.make(rates, store=FolderStore(root), made_at=_at(1), complete=True)
    table = second.kept.folder / "_data" / "treasury.parquet"
    aside = root.parent / "not-synced-yet.parquet"
    os.rename(table, aside)
    store_module._found_whole.clear()
    _chart(rates, "three")
    third = snapshot.make(rates, store=FolderStore(root), made_at=_at(2))
    assert third.kept.increment and third.kept.builds_on == first.kept.folder.name
    os.rename(aside, table)  # the sync brings it
    store_module._found_whole.clear()
    store_module._read_records.clear()
    return first, second, third


#: A file that is most of a pipeline of exact sizes, so that a small change beside it is an increment
BIG = b"B" * 100


class TestAFileThatFitsUnderSnapshotsByOneCharacter:
    """On Windows without long paths. ``increments`` is one letter longer than ``snapshots``: a file that fits in a complete snapshot by one character does not fit in an increment, and the snapshot is kept complete."""

    def _at_the_limit(self, store, monkeypatch, pipeline: str, place: str) -> None:
        name = store_module.snapshot_folder_name(_at(0), COMMIT)  # every snapshot's folder name is this long
        under_snapshots = store.root / "snapshots" / pipeline / name / place
        monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
        monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
        monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", len(str(under_snapshots)) + 1)  # it fits, by one
        monkeypatch.setattr(store_module, "WINDOWS_FOLDER_LIMIT", len(str(under_snapshots)) + 100)

    def test_the_snapshot_is_made_all_the_same_complete(self, store, work, monkeypatch):
        """The pipeline's snapshots fit, and were made yesterday. Today the long-named file changed, little else did, and the rule says increment: the snapshot is made, complete."""
        files = work / "files"
        place = "data/" + "f" * 40 + ".bin"
        self._at_the_limit(store, monkeypatch, "acme+sized", place)
        first = _of_files(store, files, [("a", place, b"a" * 10), ("big", "data/big.bin", BIG)], 0)
        assert not first.increment
        # As long as the long-named file is the same, an increment names it where it is: nothing of that name is written
        second = _of_files(store, files, [("a", place, b"a" * 10), ("big", "data/big.bin", BIG), ("n", "n.bin", b"n")], 1)
        assert second.increment and [sorted(_own(one)) for one in _records(store.root) if one.made_at == _at(1)] == [["n.bin"]]
        third = _of_files(store, files, [("a", place, b"b" * 10), ("big", "data/big.bin", BIG), ("n", "n.bin", b"n")], 2)
        (record,) = [one for one in _records(store.root) if one.made_at == _at(2)]
        # By the rule it is an increment, 1 and 10 of 111; it is complete because its own file does not fit under increments/
        assert snapshot.to_be_kept(FolderStore(store.root), snapshot.read(record.path)).increment
        assert not third.increment and record.folder.parent.parent.name == "snapshots" and "stored" not in _document(record)
        assert (record.folder / place).read_bytes() == b"b" * 10 and len(_own(record)) == 3
        assert FolderStore(store.root).verify() == [] and _unrecorded_folders(store.root) == [] and _left_in_tmp(store.root) == []

    def test_chartbook_snapshot_of_a_pipeline_whose_chart_fits_by_one_character(self, rates, store, monkeypatch):
        """As a person meets it: `chartbook snapshot` worked yesterday, the chart was drawn again, and today it works too."""
        long_name = "_output/" + "c" * 44 + ".html"
        manifest = {**MANIFEST, "charts": {"curve": {"path": f"./{long_name}", "dataframe": "treasury", "docs": "d"}}}
        (rates / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        (rates / "_output" / "curve.html").unlink()
        _table(rates, 5000)  # the table is most of it
        (rates / long_name).write_text("<p>one</p>\n", encoding="utf-8", newline="\n")
        _commit(rates, "A chart with a long name")
        self._at_the_limit(store, monkeypatch, "acme+rates", long_name)
        first = _snapshot()
        assert first.exit_code == 0 and "Snapshot made: 5 files" in first.output, first.output
        # The chart is drawn again, and the table is the same file
        (rates / long_name).write_text("<p>two</p>\n", encoding="utf-8", newline="\n")
        second = _snapshot()
        assert second.exit_code == 0, second.output
        newest = max(_records(store.root), key=lambda record: record.made_at)
        assert len(_records(store.root)) == 2 and not newest.increment
        assert _made(second) == [f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}.", PIN_LINE]
        assert FolderStore(store.root).verify() == [] and _unrecorded_folders(store.root) == [] and _left_in_tmp(store.root) == []

    def test_written_complete_for_a_name_of_chartbooks_own_that_does_not_fit_it_leaves_no_folder_under_increments(self, store, work, monkeypatch):
        """The README at the top says of `increments/`: "there once one is kept that way". Only ChartBook's own name in a snapshot's folder does not fit under it, by the one character: the snapshot is written complete, and no folder was made under increments/ before that was found."""
        files = work / "files"
        first = _of_files(store, files, [("big", "d/big.bin", b"B" * 400), ("a", "d/a.bin", b"a")], 0)
        self._at_the_limit(store, monkeypatch, "acme+sized", "_chartbook/" + "0" * 12 + ".tmp")
        second = _of_files(FolderStore(store.root), files, [("big", "d/big.bin", b"B" * 400), ("a", "d/a.bin", b"b")], 1)
        assert not second.increment and first.folder.is_dir()
        (record,) = [one for one in _records(store.root) if one.made_at == _at(1)]
        assert snapshot.to_be_kept(FolderStore(store.root), snapshot.read(record.path)).increment  # by the rule, an increment
        assert FolderStore(store.root).verify() == [] and _unrecorded_folders(store.root) == []
        assert not (store.root / "increments").exists()


@pytest.fixture
def two(work, rates):
    """Two stores with names, as a catalog has them, and what sends a snapshot to both."""
    from chartbook.multi_store import NamedStore, Stores

    def stores():
        return Stores([
            NamedStore("here", str(work / "store"), FolderStore(work / "store"), create=True),
            NamedStore("there", str(work / "there"), FolderStore(work / "there"), create=True),
        ])

    return stores


class TestSeveralStores:
    """Each store decides for itself, with its own snapshot to build on and its own count."""

    def test_two_stores_whose_histories_differ(self, rates, work, store, two):
        # The first store has a snapshot of the pipeline; the other has never seen it
        first = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(1))
        assert second.made and second.kept.increment and second.kept.builds_on == first.kept.folder.name
        ((name, theirs),) = second.kept_otherwise
        assert name == "there" and not theirs.increment and theirs.own_files == theirs.files == 5
        assert theirs.folder == work / "there" / "snapshots" / "acme+rates" / second.kept.folder.name
        (here,) = [record for record in _records(store.root) if record.made_at == _at(1)]
        (there,) = _records(work / "there")
        assert here.increment and not there.increment and FolderStore(work / "there").verify() == []

        def less_stored(document: dict) -> dict:
            for part in [*document["records"], document["index"], document["documents"]]:
                part.pop("stored")
            document.pop("stored", None)
            return document

        assert less_stored(_document(here)) == less_stored(_document(there))  # one snapshot, kept two ways
        # The next: an increment in each, on each store's own complete snapshot, with each store's own count
        _chart(rates, "three")
        third = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(2))
        (here,) = [record for record in _records(store.root) if record.made_at == _at(2)]
        (there,) = [record for record in _records(work / "there") if record.made_at == _at(2)]
        assert not here.increment and third.kept.added_up  # the second one here, which adds up
        assert there.increment and there.builds_on == second.kept.folder.name and there.increments_bytes == sum(_own(there).values())
        ((name, theirs),) = third.kept_otherwise
        assert name == "there" and theirs.increment and theirs.rest_made_at == _at(1)
        assert FolderStore(store.root).verify() == [] and FolderStore(work / "there").verify() == []

    def test_asked_for_complete_it_is_complete_in_each(self, rates, work, store, two):
        snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(1), complete=True)
        assert second.made and not second.kept.increment and second.kept_otherwise == []
        assert [record.increment for record in _records(store.root)] == [False, False]
        assert [record.increment for record in _records(work / "there")] == [False, False]

    def test_asked_for_complete_where_another_store_keeps_these_files_as_an_increment(self, rates, work, store, two):
        """The first store has them complete and the second as an increment: a new one is made, complete in both."""
        snapshot.make(rates, store=FolderStore(work / "there"), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(1))
        assert not second.kept.increment and [name for name, _ in second.kept_otherwise] == ["there"]
        before = _recorded(work / "there")
        third = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(2), complete=True)
        assert third.made and third.snapshot.content() == second.snapshot.content()
        assert [record.increment for record in _records(store.root)] == [False, False]
        assert [record.increment for record in _records(work / "there")] == [False, True, False]
        after = _recorded(work / "there")
        assert {path: seen for path, seen in after.items() if path in before} == before

    def test_the_rule_is_written_once(self, rates, work, store, two, monkeypatch):
        """Both stores are asked through the one function, each with itself."""
        asked = []
        real = snapshot.to_be_kept

        def watching(store, taken, complete=False, now=None):
            asked.append(store.root.name)
            return real(store, taken, complete, now)

        monkeypatch.setattr(snapshot, "to_be_kept", watching)
        snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(0))
        assert asked == ["store", "there"]


@pytest.fixture
def catalog(work, rates, monkeypatch):
    """A catalog of two stores that can be written, `mine` first; the pipeline is sent to both."""
    from chartbook import backends

    monkeypatch.delenv(config.STORE_ENV_VAR)
    home = work / "home"
    home.mkdir()
    monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
    monkeypatch.setattr(backends, "get_global_config_dir", lambda: home)
    stores = {name: {"url": str(work / name), "pipelines": ["acme/rates"]} for name in ("mine", "team")}
    for name in stores:
        (work / name).mkdir()
    (home / "catalog.toml").write_text(tomli_w.dumps({"project": {"name": "Catalog"}, "stores": stores}), encoding="utf-8", newline="\n")
    return work


class TestWhatAPersonSees:
    """The lines `chartbook snapshot` ends with, each as the design page's scenario has it."""

    def test_the_first_then_an_increment_then_the_complete_one_they_add_up_to(self, rates, store):
        commit = _git(rates, "rev-parse", "HEAD")
        first = _snapshot()
        assert first.exit_code == 0, first.output
        (one,) = _records(store.root)
        size = sum(_own(one).values())
        # 1. The first snapshot of a pipeline is complete
        assert first.stdout.splitlines() == [
            f"acme/rates at {commit[:7]}: 2 asset(s) in the store",
            f"Snapshot made: 5 files, {_format_bytes(size)}.",
            PIN_LINE,
        ]
        # 2. A later one, where little changed, is kept as an increment: the chart was drawn again
        _chart(rates, "two")
        second = _snapshot()
        (two,) = [record for record in _records(store.root) if record.increment]
        assert second.stdout.splitlines() == [
            f"acme/rates at {commit[:7]}: 2 asset(s) in the store",
            f"Snapshot made, kept as an increment: 2 of 5 files, {_format_bytes(sum(_own(two).values()))}. "
            f"The rest is in the snapshot made {_when(one.made_at)}.",
            PIN_LINE,
        ]
        # 3. The increments have added up, so the next one is complete
        _chart(rates, "three")
        third = _snapshot()
        three = max(_records(store.root), key=lambda record: record.made_at)
        assert not three.increment
        assert third.stdout.splitlines() == [
            f"acme/rates at {commit[:7]}: 2 asset(s) in the store",
            f"Snapshot made: 5 files, {_format_bytes(sum(_own(three).values()))}. "
            f"The increments since the last complete one had added up to its size.",
            PIN_LINE,
        ]

    def test_one_where_every_file_differs_is_not_said_to_have_added_up(self, rates, store):
        """The page: "One where every file differs is complete: the increment would be the whole of it." After one small increment, such a snapshot's line is scenario 1's, not scenario 3's."""
        assert _snapshot().exit_code == 0
        # A word more in the README, committed: a small increment
        (rates / "README.md").write_text("# acme/rates\n\nA word more.\n", encoding="utf-8", newline="\n")
        _commit(rates, "a word")
        small = _snapshot()
        assert _made(small)[0].startswith("Snapshot made, kept as an increment: 2 of 5 files, "), small.output
        # And then every file is another: the table, the chart, both documents (and the index, as always)
        _everything_differs(rates, "again")
        result = _snapshot()
        newest = max(_records(store.root), key=lambda record: record.made_at)
        base = min(_records(store.root), key=lambda record: record.made_at)
        assert not newest.increment and not set(_listed(newest).values()) & set(_listed(base).values())  # nothing of it is in the one before
        assert _made(result) == [f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}.", PIN_LINE]

    def test_asked_for_complete_it_says_where_the_folder_is(self, rates, store):
        commit = _git(rates, "rev-parse", "HEAD")
        result = _snapshot("--complete")
        (one,) = _records(store.root)
        assert result.stdout.splitlines() == [
            f"acme/rates at {commit[:7]}: 2 asset(s) in the store",
            f"Snapshot made: 5 files, {_format_bytes(sum(_own(one).values()))}.",
            f"  {store.root / 'snapshots' / 'acme+rates' / one.folder.name}",
        ]

    def test_a_store_that_keeps_it_the_other_way_is_named(self, catalog, rates):
        # `team` has never seen the pipeline; `mine` has a snapshot of it
        snapshot.make(rates, store=FolderStore(catalog / "mine"), made_at=_at(0))
        _chart(rates, "two")
        result = _snapshot()
        assert result.exit_code == 0, result.output
        (mine,) = [record for record in _records(catalog / "mine") if record.increment]
        (team,) = _records(catalog / "team")
        assert _made(result) == [
            f"Snapshot made, kept as an increment: 2 of 5 files, {_format_bytes(sum(_own(mine).values()))}. "
            f"The rest is in the snapshot made {_when(_at(0))}.",
            PIN_LINE,
            f"Store team keeps it complete: 5 files, {_format_bytes(sum(_own(team).values()))}.",
            "Stores: mine, team",
        ]
        # And the other way about: complete here once the increments add up, an increment there
        _chart(rates, "three")
        result = _snapshot()
        newest = max(_records(catalog / "mine"), key=lambda record: record.made_at)
        (theirs,) = [record for record in _records(catalog / "team") if record.increment]
        assert _made(result) == [
            f"Snapshot made: 5 files, {_format_bytes(sum(_own(newest).values()))}. "
            f"The increments since the last complete one had added up to its size.",
            PIN_LINE,
            f"Store team keeps it as an increment: 2 of 5 files, {_format_bytes(sum(_own(theirs).values()))}. "
            f"The rest is in the snapshot made {_when(team.made_at)}.",
            "Stores: mine, team",
        ]

    @posix
    def test_what_a_run_snapshots_for_itself_to_pin_says_the_same_first(self, rates, work, store):
        """`--upstream`: the line for a pipeline snapshotted so that this run can pin it."""
        reader = work / "reader"
        reader.mkdir()
        (reader / "chartbook.toml").write_text(
            tomli_w.dumps({
                "project": {"id": "acme/reader"}, "scripts": {"build": "echo built"},
                "dependencies": {"acme/rates": {"path": "../rates"}},
            }),
            encoding="utf-8", newline="\n",
        )
        (reader / ".gitignore").write_text("/chartbook.lock\n", encoding="utf-8", newline="\n")
        _commit(reader)
        result = CliRunner().invoke(main, ["run", "--upstream", "--project-dir", str(reader)])
        assert result.exit_code == 0, result.output
        (one,) = _records(store.root)
        assert f"Snapshot made: 5 files, {_format_bytes(sum(_own(one).values()))}, for what depends on it in this run to pin." in result.stdout.splitlines()
        assert PIN_LINE not in result.output

    def test_one_file_is_one_file(self):
        from chartbook.cli import _kept_said

        assert _kept_said(snapshot.Kept(1, 2048, own_files=1, own_bytes=2048)) == ("complete", "1 file, 2.0 KB", "")
        assert _kept_said(snapshot.Kept(3, 4096, "2026-01-01T000000Z_aaaaaaaaaaaa", _at(0), 0, 0, 0)) == (
            "as an increment", "0 of 3 files, 0 bytes", " The rest is in the snapshot made 2026-01-01 00:00 UTC.",
        )

    def test_no_blank_date_is_printed_where_the_time_of_what_it_builds_on_is_not_known(self):
        """The record of what an increment builds on could not be read for its time (it went as the line was being said): the line says so much, and no "made  UTC"."""
        from chartbook.cli import _kept_said

        assert _kept_said(snapshot.Kept(3, 4096, "2026-01-01T000000Z_aaaaaaaaaaaa", "", 1, 1024, 1024)) == (
            "as an increment", "1 of 3 files, 1.0 KB", " The rest is in the snapshot it builds on.",
        )


class TestWhoeverDependsOnItSeesNoDifference:
    def test_a_pin_and_a_read_of_one_kept_as_an_increment(self, rates, work, store):
        snapshot.make(rates, store=FolderStore(store.root), made_at=_at(0))
        _chart(rates, "two")
        second = snapshot.make(rates, store=FolderStore(store.root), made_at=_at(1))
        assert second.kept.increment
        reader = work / "reader"
        reader.mkdir()
        (reader / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/reader"}, "dependencies": {"acme/rates": {"path": "../rates"}}}),
            encoding="utf-8", newline="\n",
        )
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        assert lock.read_lock(reader).snapshots() == {(second.snapshot.commit, _at(1))}
        assert data.load("acme/rates:treasury", project_dir=reader).collect().height == 3
        assert lock.verify(reader, FolderStore(store.root), note=False).problems == []


# A pipeline most of which never changes, so that its later snapshots are increments on its first


def _history() -> pl.DataFrame:
    """A table that is large beside everything else, and never the same value twice, so that it does not compress away."""
    values = [int(hashlib.sha256(str(i).encode()).hexdigest()[:12], 16) / 7.0 for i in range(20000)]
    return pl.DataFrame({"n": list(range(20000)), "v": values})


STEADY = {
    "project": {"id": "acme/rates"},
    "dataframes": {"history": {"path": "./_data/history.parquet", "docs": "d"}},
    "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "history", "docs": "d"}},
    "files": {"raw": {"path": "./_data/raw"}},
}


@pytest.fixture
def steady(work, store, monkeypatch):
    """``acme/rates`` with a large table that never changes, a small chart, and a files asset of two files; built and committed. Commands are typed in its folder."""
    folder = work / "rates"
    (folder / "_data" / "raw").mkdir(parents=True)
    (folder / "_output").mkdir()
    (folder / "chartbook.toml").write_text(tomli_w.dumps(STEADY), encoding="utf-8", newline="\n")
    (folder / "README.md").write_text("# acme/rates\n", encoding="utf-8", newline="\n")
    (folder / ".gitignore").write_text("/_data/\n/_output/\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _history().write_parquet(folder / "_data" / "history.parquet")
    (folder / "_data" / "raw" / "a.txt").write_bytes(b"alpha\n")
    (folder / "_data" / "raw" / "b.txt").write_bytes(b"beta 1\n")
    _drawn(folder, 0)
    _commit(folder)
    monkeypatch.chdir(folder)
    return folder


def _drawn(folder: Path, number: int) -> None:
    """The small chart, drawn again."""
    (folder / "_output" / "curve.html").write_text(f"<p>curve {number}</p>\n", encoding="utf-8", newline="\n")


def _a_reader(folder: Path) -> Path:
    """A pipeline beside ``rates`` that depends on it by its folder."""
    folder.mkdir()
    (folder / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": f"acme/{folder.name}"}, "dependencies": {"acme/rates": {"path": "../rates"}}}),
        encoding="utf-8", newline="\n",
    )
    return folder


def _three(steady: Path, store, reader: Path = None) -> list:
    """Three snapshots, the chart drawn again for each, which the store keeps as a complete one and two increments on it; their reports. *reader* pins the second."""
    made = []
    for number in range(3):
        _drawn(steady, number)
        made.append(snapshot.make(steady, store=FolderStore(store.root), made_at=_at(number)))
        if number == 1 and reader is not None:
            assert lock.pin(reader, FolderStore(store.root)).problems == []
    assert [report.kept.increment for report in made] == [False, True, True]
    assert {report.kept.builds_on for report in made[1:]} == {made[0].kept.folder.name}
    return made


def _help(*command: str) -> str:
    """A command's help, as one line of words."""
    return " ".join(CliRunner().invoke(main, [*command, "--help"], prog_name="chartbook").output.split())


class TestACompleteSnapshotThatLostAFileIncrementsKeepInIt:
    """A complete snapshot loses a file (a sync that has not brought it, a file removed by hand) that two snapshots kept as increments keep in its folder: all three lack it, and each command names the snapshot whose folder it is missing from."""

    def test_store_verify_says_it_once_with_how_many_increments_keep_it_there(self, steady, store):
        """`store verify` reads a file two records name once and says it once, with the snapshot in whose folder it is, or is missing from. How many snapshots lack it with that one is said in the same line."""
        made = _three(steady, store)
        base = made[0].kept.folder
        _lose(base / "_data" / "history.parquet")
        fresh = FolderStore(store.root)
        assert [bool(fresh.holes_of(report.snapshot.path)) for report in made] == [True, True, True]  # the complete one, and both increments on it
        said = CliRunner().invoke(main, ["store", "verify"])
        assert said.exit_code == 1
        (line,) = [line for line in said.output.splitlines() if "_data/history.parquet" in line]
        assert line.endswith(
            f"_data/history.parquet is not in the store (the snapshot {base.name}), and 2 snapshots kept as increments on it keep it there"
        )
        assert "is said once, under the name it has there, with that snapshot's name and how many of them keep it there" in _help("store", "verify")
        # With one increment on it, one is said
        assert fresh.remove_snapshot(made[2].snapshot.path)
        (problem,) = FolderStore(store.root).verify()
        assert problem.message == (
            f"_data/history.parquet is not in the store (the snapshot {base.name}), and 1 snapshot kept as an increment on it keeps it there"
        )

    def test_store_gc_names_the_snapshot_whose_folder_the_file_is_missing_from(self, steady, store):
        """As `store verify` has it: the complete one, where the file was, and not an increment, in whose folder the file never was and which "goes once a newer snapshot of its pipeline is made". The way out is the complete one's."""
        made = _three(steady, store)
        base = made[0].kept.folder
        _lose(base / "_data" / "history.parquet")
        (problem,) = FolderStore(store.root).verify()
        assert problem.message.startswith(f"_data/history.parquet is not in the store (the snapshot {base.name})")
        said = CliRunner().invoke(main, ["store", "gc", "--dry-run"])
        assert said.exit_code == 0, said.output
        lines = said.output.splitlines()
        at = lines.index(
            f"Nothing of acme/rates is removed: its snapshot {base.name} lacks _data/history.parquet, and stays because "
            f"an increment that stays builds on it."
        )
        assert lines[at + 1] == (
            "  If a sync is still bringing it, wait for the sync to finish. `chartbook store verify` lists everything missing. "
            "If it is lost for good, that snapshot goes once the increments that build on it have gone, each for its own "
            "reason (`chartbook store gc --dry-run` says which stay, and why)."
        )

    def test_where_an_increment_lacks_a_file_of_its_own_too_the_newest_such_is_said(self, steady, store):
        """A snapshot that lacks a file of its own folder is the one said, the newest of them; one that lacks only what another's folder is to hold is said where no such is."""
        made = _three(steady, store)
        _lose(made[0].kept.folder / "_data" / "history.parquet")
        _lose(made[1].kept.folder / "_output" / "curve.html")
        held = FolderStore(store.root).holes_left([made[2].snapshot.path])
        assert held == {"acme/rates": (Path(made[1].snapshot.path), "_output/curve.html", 1)}
        # And with the complete one gone from the store, an increment's hole in it is the one there is to say
        shutil.rmtree(made[0].kept.folder, onerror=_writable)
        store_module._read_records.clear()
        store_module._found_whole.clear()
        (made[1].kept.folder / "_output" / "curve.html").write_text("<p>curve 1</p>\n", encoding="utf-8", newline="\n")
        held = FolderStore(store.root).holes_left([made[1].snapshot.path])
        assert held["acme/rates"][0] == Path(made[2].snapshot.path) and "_data/history.parquet" in FolderStore(store.root).holes_of(made[2].snapshot.path)

    def test_pin_names_pin_update_only_where_the_newest_snapshot_is_whole(self, steady, work, store):
        """A reader of an increment whose complete snapshot lost a file was told "`chartbook pin --update` moves to the newest one"; the newest is an increment on the same snapshot, and lacks the file too. The way is named once a snapshot that is whole is there to move to."""
        reader = _a_reader(work / "reader")
        made = _three(steady, store, reader)
        good = (steady / "_data" / "history.parquet").read_bytes()
        _lose(made[0].kept.folder / "_data" / "history.parquet")
        pin = lambda *arguments: CliRunner().invoke(main, ["pin", *arguments, "--project-dir", str(reader)])  # noqa: E731
        told = pin()
        assert told.exit_code == 1 and "acme/rates:history" in told.output
        assert "chartbook pin --update` moves to the newest one" not in told.output
        assert pin("--update").exit_code == 1  # and nothing moves: the newest lacks it too
        # Its owner builds the table anew and makes a snapshot: nothing is built on one with a hole, so it is complete, and whole
        _history().head(19000).write_parquet(steady / "_data" / "history.parquet")
        again = _snapshot()
        assert again.exit_code == 0, again.output
        newest = max(_records(store.root), key=lambda record: record.made_at)
        assert not newest.increment and FolderStore(store.root).holes_of(newest.path) == []
        told = pin()  # the pinned bytes are still lost, and now there is a whole one to move to
        assert told.exit_code == 1 and "Otherwise a snapshot puts it there: `chartbook pin --update` moves to the newest one" in told.output
        moved = pin("--update")
        assert moved.exit_code == 0, moved.output
        assert data.path("acme/rates:history", project_dir=reader).read_bytes() == (steady / "_data" / "history.parquet").read_bytes() != good


class TestVerifySaysAWrongFileOnce:
    """A wrong file is one place in the store: `store verify` says it once, under the name it has in the folder it is in or missing from, and counts every increment that keeps it there, whatever name each has for it."""

    def _renamed(self, steady, store) -> tuple:
        """A complete snapshot, and an increment made after the upstream renamed one file of a files asset, its bytes the same: the increment keeps `c.txt` in the complete one, as `a.txt`."""
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        (steady / "_data" / "raw" / "a.txt").rename(steady / "_data" / "raw" / "c.txt")
        (steady / "_data" / "raw" / "b.txt").write_bytes(b"beta 2\n")
        second = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1))
        assert second.kept.increment and not (second.kept.folder / "_data" / "raw" / "c.txt").exists()
        return first, second

    def test_a_file_an_increment_keeps_there_under_another_name_is_said_once(self, steady, store):
        """One file is missing from the store: `a.txt`, from the complete snapshot's folder. It was said twice, the second time as `c.txt`, a name the snapshot named never had."""
        first, second = self._renamed(steady, store)
        _lose(first.kept.folder / "_data" / "raw" / "a.txt")
        problems = FolderStore(store.root).verify()
        assert [problem.message for problem in problems] == [
            f"_data/raw/a.txt is not in the store (the snapshot {first.kept.folder.name}), and 1 snapshot kept as an increment on it keeps it there"
        ]
        assert problems[0].path == first.kept.folder

    def test_no_line_says_the_complete_snapshot_lacks_a_file_it_never_had(self, steady, store):
        first, second = self._renamed(steady, store)
        _lose(first.kept.folder / "_data" / "raw" / "a.txt")
        said = CliRunner().invoke(main, ["store", "verify"])
        assert said.exit_code == 1 and "_data/raw/c.txt" not in said.output  # the complete snapshot never had a c.txt
        assert len([line for line in said.output.splitlines() if "is not in the store (the snapshot " in line]) == 1

    def test_the_name_is_the_one_it_has_there_whichever_record_is_read_first(self, steady, store, monkeypatch):
        """The increment's record read before the complete one's: the file is still said under the name the complete snapshot's folder has it by."""
        first, second = self._renamed(steady, store)
        _lose(first.kept.folder / "_data" / "raw" / "a.txt")
        real = FolderStore.records
        monkeypatch.setattr(FolderStore, "records", lambda self, *how: sorted(real(self, *how), key=lambda record: not record.increment))
        (problem,) = FolderStore(store.root).verify()
        assert problem.message.startswith(f"_data/raw/a.txt is not in the store (the snapshot {first.kept.folder.name})")

    def test_how_many_keep_it_there_counts_every_increment_whatever_name_it_has_for_it(self, steady, store):
        """Two increments keep the file in the complete one, one of them under another name: the line that names the file says 2."""
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        _drawn(steady, 1)
        second = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1))  # keeps a.txt there as a.txt
        (steady / "_data" / "raw" / "a.txt").rename(steady / "_data" / "raw" / "c.txt")
        third = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(2))  # keeps c.txt there as a.txt
        assert second.kept.increment and third.kept.increment and third.kept.builds_on == first.kept.folder.name
        _lose(first.kept.folder / "_data" / "raw" / "a.txt")
        assert [problem.message for problem in FolderStore(store.root).verify()] == [
            f"_data/raw/a.txt is not in the store (the snapshot {first.kept.folder.name}), and 2 snapshots kept as increments on it keep it there"
        ]


class TestWhereTheStoresCopyIsDamagedAtTheSameSize:
    """The complete snapshot's copy of a file has other bytes at the same size (a sync cut short, a disk's fault), and the pipeline's own file is good."""

    @pytest.mark.parametrize("complete", [True, False], ids=["asked for complete", "kept as the store chooses"])
    def test_complete_writes_every_file_again_and_an_increment_takes_it_on_the_records_word(self, steady, work, store, complete):
        """`chartbook snapshot --complete` writes every file again from bytes it has checked: the store's copy fails its hash, and the file at hand is taken. Left to the store the snapshot is an increment, which takes the files of the snapshot it builds on by that one's record and their sizes on disk: the damaged copy is named, not replaced, and `chartbook store verify` finds it.

        That is the trust a pin, a read and `No new snapshot` already give
        the store, and what ChartBook 0.5 gave it for every snapshot;
        reading the whole of what it builds on to make an increment would
        cost what the increment saves.
        """
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        good = (steady / "_data" / "history.parquet").read_bytes()
        theirs = first.kept.folder / "_data" / "history.parquet"
        os.chmod(theirs, stat.S_IWRITE | stat.S_IREAD)
        theirs.write_bytes(bytes(len(good)))
        store_module._found_whole.clear()
        _drawn(steady, 1)
        made = _snapshot(*(["--complete"] if complete else []))
        assert made.exit_code == 0 and "Snapshot made" in made.output, made.output
        newest = max(_records(store.root), key=lambda record: record.made_at)
        assert newest.increment is not complete
        fresh = FolderStore(store.root)
        reader = _a_reader(work / "reader")
        if complete:
            # It holds what its record says, and whoever pins it reads the pipeline's bytes
            assert fresh.verify_snapshot(newest.path) == []
            assert lock.pin(reader, fresh).problems == []
            assert data.path("acme/rates:history", project_dir=reader).read_bytes() == good
        else:
            assert fresh.holes_of(newest.path) == []  # by its size, nothing is missing
            (problem,) = fresh.verify_snapshot(newest.path)
            assert problem.message.startswith("_data/history.parquet is no longer what its record says")
            said = CliRunner().invoke(main, ["store", "verify"])
            assert said.exit_code == 1
            (line,) = [line for line in said.output.splitlines() if "_data/history.parquet" in line]
            assert line.endswith(f"(the snapshot {first.kept.folder.name}), and 1 snapshot kept as an increment on it keeps it there")
            assert theirs.read_bytes() == bytes(len(good))  # and nothing was written into the one it builds on


REPOSITORY = Path(__file__).resolve().parent.parent


def _page(*parts: str) -> str:
    return REPOSITORY.joinpath(*parts).read_text(encoding="utf-8")


class TestWhatThePagesSay:
    """Where the pages, the help and the assistant files speak of how a snapshot is kept, what they say is so."""

    def test_the_reason_gc_gives_for_what_an_increment_builds_on_is_among_those_its_help_lists(self, steady, store):
        """`store gc` says "an increment that stays builds on it", which from now on it says of most stores: its help lists it with every other reason, before "Otherwise it may be removed"."""
        snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        _drawn(steady, 1)
        assert snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1)).kept.increment
        dry = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--keep-days", "0", "--aggressive"])
        assert dry.exit_code == 0 and "1 because an increment that stays builds on it" in dry.output, dry.output
        said = _help("store", "gc")
        assert "if an increment that stays builds on it" in said
        assert said.index("if an increment that stays builds on it") < said.index("Otherwise it may be removed")

    def test_the_references_table_of_reasons_lists_it(self):
        reference = _page("docs_src", "reference", "cli.md")
        section = reference[reference.index("### store gc"):]
        table = section[section.index("**Which snapshots are kept.**"):section.index("Everything else may be removed.")]
        assert "| A lockfile pins it |" in table  # the table of reasons
        assert "| An increment that stays builds on it |" in table
        # And what a nightly snapshot leaves says so too
        closing = section[section.index("Everything else may be removed."):].splitlines()[0]
        assert "the complete snapshots that increments among them build on" in closing

    def test_the_words_are_met_where_the_vocabulary_says_and_never_in_a_pin_or_a_read(self, steady, work, store):
        """Complete and increment are words of the store: the vocabulary and the design's "Words" say where they are met, and what is promised of the rest: a lockfile never says how a snapshot is kept, and nothing that `pin`, a read or the catalog prints says it of a snapshot. (The pages of a read do say where its files may sit, and name a snapshot kept as an increment there.)"""
        met = (
            "met in the store's folders, in `chartbook store ls`, in what `chartbook snapshot` and `chartbook store migrate` say, "
            "in the option `--complete`, in the help of `chartbook store export` and `chartbook store import`, in a reason "
            "`chartbook store gc` gives for keeping a snapshot, and in what `chartbook store verify` says of a file that "
            "increments keep in a complete snapshot"
        )
        never = (
            "A lockfile never says how a snapshot is kept, and nothing that `chartbook pin`, a read or the catalog prints says it "
            "of a snapshot; the pages of a read say only where its files may sit"
        )
        for page in (_page("docs_src", "guide", "vocabulary.md"), " ".join(_page("docs_src", "design", "snapshots-and-increments.md").split())):
            assert met in page and never in page and "nowhere else" not in page
            assert "never in a lockfile, a pin, a read or the catalog" not in page  # the reference of a read names an increment, rightly
        # Each command named there says the word, in its help or in what it prints
        for command in (("snapshot",), ("store", "ls"), ("store", "migrate"), ("store", "export"), ("store", "import"), ("store", "gc"), ("store", "verify")):
            assert re.search(r"\bincrements?\b", _help(*command)), command
        # And no command that pins, reads or shows a catalog says it in its help (a build that is "incremental" is another word)
        for command in (("pin",), ("path",), ("add",), ("lineage",), ("catalog", "build"), ("docs", "build")):
            assert not re.search(r"\bincrements?\b", _help(*command)), command
        # A lockfile that pins one kept as an increment says nothing of how it is kept
        reader = _a_reader(work / "reader")
        _three(steady, store, reader)
        pinned = (reader / lock.LOCK_FILE).read_text(encoding="utf-8")
        assert "acme/rates" in pinned and not re.search(r"increment|builds_on|kept_in|kept_as|stored", pinned)
        # And what `pin` prints as it moves to one says nothing of it either
        moved = CliRunner().invoke(main, ["pin", "--update", "--project-dir", str(reader)])
        assert moved.exit_code == 0 and "acme/rates" in moved.output and not re.search(r"increment|builds on|complete", moved.output), moved.output

    def test_complete_says_where_the_folder_is_by_its_whole_path_as_the_pages_have_it(self, steady, work, monkeypatch):
        """Scenario 5 of the design page, and the changelog: the folder is printed whole, also where it is under the person's home."""
        monkeypatch.setenv("HOME", str(work))
        monkeypatch.setenv("USERPROFILE", str(work))
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / ".chartbook" / "store"))
        asked = _snapshot("--complete")
        assert asked.exit_code == 0, asked.output
        (record,) = _records(work / ".chartbook" / "store")
        lines = asked.output.splitlines()
        at = lines.index(f"  {work / '.chartbook' / 'store' / 'snapshots' / 'acme+rates' / record.folder.name}")
        assert lines[at - 1].startswith("Snapshot made: ") and not any("~" in line for line in lines[:at + 1])
        printed = "  /Users/x/.chartbook/store/snapshots/acme+rates/2026-11-20T101500Z_9b1e22d7a0c4\n"
        assert printed in _page("docs_src", "design", "snapshots-and-increments.md") and printed in _page("docs_src", "changelog.md")
        assert "  ~/.chartbook/store/snapshots/acme+rates/2026-11-20T101500Z" not in _page("docs_src", "design", "snapshots-and-increments.md")

    def test_a_store_of_0_5_is_listed_in_the_same_two_words_as_the_assistant_files_say(self, steady, store):
        """`store ls` says complete or increment of every snapshot, in every store: the words of 0.5.0, standalone and shared, are gone, and no page for an assistant gives them for a store that 0.5 laid out."""
        from tests.store_of_0_5 import laid_out_as_0_5

        for page in (("llms.txt",), ("llm", "llms.txt"), ("llm", "llms-full.txt"), ("src", "chartbook", "skills", "SKILL.md")):
            said = " ".join(_page(*page).split())
            assert "listed in the same two words" in said, page
            assert "standalone or shared" not in said, page
        snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        _drawn(steady, 1)
        assert snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1)).kept.increment
        laid_out_as_0_5(store.root)
        listed = CliRunner().invoke(main, ["store", "ls"])
        assert listed.exit_code == 0, listed.output
        kinds = [line.split()[5] for line in listed.output.splitlines() if line.startswith("  2026-")]  # after its folder, its time and its commit
        assert sorted(kinds) == ["complete", "increment"] and not re.search(r"standalone|shared", listed.output)

    def test_a_file_an_increment_keeps_in_the_complete_one_may_be_handed_out_under_the_name_it_has_there(self, steady, work, store):
        """`assets.files`, `assets.path`, `data.files`, `data.path` and `models.path` say where an asset's files may sit: in other snapshots' folders, or under another's name, in a bucket, in a store that ChartBook 0.5 laid out, and for a snapshot kept as an increment.

        The upstream renames one file of a files asset between two
        snapshots, its bytes the same. Complete, the second snapshot would
        have it under its new name; as an increment it keeps it where the
        complete one has it, and the file handed out is that one, `a.txt`.
        """
        from chartbook import assets, models

        for function in (assets.files, assets.path, data.files, data.path, models.path):
            said = " ".join(function.__doc__.split())
            assert "store may keep each file once (a bucket does, a store that ChartBook 0.5 laid out, and a snapshot kept as an increment" in said, function
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        (steady / "_data" / "raw" / "a.txt").rename(steady / "_data" / "raw" / "c.txt")
        (steady / "_data" / "raw" / "b.txt").write_bytes(b"beta 2\n")
        second = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1))
        assert second.kept.increment
        reader = _a_reader(work / "reader")
        assert lock.pin(reader, FolderStore(store.root)).problems == []
        listed = assets.files("acme/rates:file/raw", project_dir=reader)  # in the order of their paths in the asset: b.txt, c.txt
        assert [path.read_bytes() for path in listed] == [b"beta 2\n", b"alpha\n"]
        assert listed[0] == second.kept.folder / "_data" / "raw" / "b.txt"
        assert listed[1] == first.kept.folder / "_data" / "raw" / "a.txt"  # c.txt, under the name the complete one has it by


def _damage(path: Path) -> None:
    """Other bytes at the same size: a sync cut short, a disk's fault."""
    size = path.stat().st_size
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_bytes(b"\0" * size)
    store_module._read_records.clear()
    store_module._found_whole.clear()


def _folder_named(result) -> Path:
    """The folder `chartbook snapshot --complete` names: the line, two spaces in, that follows what it says of the snapshot."""
    lines = _made(result)
    assert len(lines) > 1 and lines[1].startswith("  ") and lines[1].strip(), result.output
    return Path(lines[1].strip())


class TestCompleteNamesAFolderThatHasBeenRead:
    """Asked for complete, the snapshot already there is stood on only where it is complete by what its record is and each of its own files, read and hashed, is what the record says. Otherwise a new complete one is made, as over an increment. So a folder that `--complete` names is a complete snapshot of what its record says."""

    def test_the_sentence_is_on_both_pages(self):
        sentence = (
            "`chartbook snapshot --complete` ends with a complete snapshot every file of which has been read and checked: it "
            "writes every file again from bytes it has checked, or, where the snapshot of these same files that is there is "
            "complete and reads right, names that one and writes nothing."
        )
        for page in (("docs_src", "design", "snapshots-and-increments.md"), ("docs_src", "changelog.md")):
            assert sentence in " ".join(_page(*page).split()), page

    def test_where_the_one_there_is_complete_and_reads_right_it_is_named_and_nothing_is_written(self, steady, store, monkeypatch):
        """And every byte of it was read to say so, which no snapshot without the option does."""
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        before = _recorded(store.root)
        read: list = []
        real = store_module.what_is_wrong_in

        def reading(asset, *how):
            read.append(asset.content_hash)
            return real(asset, *how)

        monkeypatch.setattr(store_module, "what_is_wrong_in", reading)
        plain = _snapshot()
        assert plain.exit_code == 0 and _made(plain) == [f"No new snapshot: the same bytes and the same pins as the one made {_when(_at(0))}."]
        assert read == []  # not asked for complete: no file of the store is read
        asked = _snapshot("--complete")
        assert asked.exit_code == 0 and _made(asked) == [
            f"No new snapshot: the same bytes and the same pins as the one made {_when(_at(0))}.", f"  {first.kept.folder}",
        ]
        assert set(read) == first.snapshot.hashes()  # every asset of it, its index and its documents
        assert _recorded(store.root) == before and len(_records(store.root)) == 1

    def test_where_the_one_there_is_complete_and_damaged_at_the_same_size_a_new_one_is_made(self, steady, store):
        """`store verify` has found a copy damaged at the same size in the one snapshot there is, a complete one, and nothing has changed in the pipeline. `--complete` said `No new snapshot`, and named the damaged folder as the complete one to look at or to hand to somebody."""
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        good = (steady / "_data" / "history.parquet").read_bytes()
        _damage(first.kept.folder / "_data" / "history.parquet")
        found = CliRunner().invoke(main, ["store", "verify"])
        assert found.exit_code == 1 and "_data/history.parquet is no longer what its record says" in found.output
        made = _snapshot("--complete")
        assert made.exit_code == 0, made.output
        folder = _folder_named(made)
        assert _made(made)[0].startswith("Snapshot made: ") and folder.parent == first.kept.folder.parent and folder != first.kept.folder
        (record,) = [one for one in _records(store.root) if one.folder == folder]
        assert record.complete and FolderStore(store.root).verify_snapshot(record.path) == []
        assert (folder / "_data" / "history.parquet").read_bytes() == good
        # The damaged one is left as it is: nothing is written into a snapshot that is there
        assert (first.kept.folder / "_data" / "history.parquet").read_bytes() == bytes(len(good))
        # Asked again, the new one reads right: it is named, and nothing more is made
        again = _snapshot("--complete")
        assert _made(again)[0].startswith("No new snapshot: ") and _folder_named(again) == folder and len(_records(store.root)) == 2

    def test_after_an_increment_on_the_damaged_one_it_writes_every_file_again(self, steady, store):
        first = snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0))
        _damage(first.kept.folder / "_data" / "history.parquet")
        _drawn(steady, 1)
        assert "kept as an increment" in _snapshot().output
        assert CliRunner().invoke(main, ["store", "verify"]).exit_code == 1
        made = _snapshot("--complete")
        assert made.exit_code == 0, made.output
        folder = _folder_named(made)
        assert folder.parent == store.root / "snapshots" / "acme+rates" and folder != first.kept.folder
        store_module._read_records.clear()
        assert FolderStore(store.root).verify_snapshot(folder / "_chartbook" / "snapshot.json") == []

    def test_where_the_one_there_keeps_files_in_another_folder_a_new_one_is_made(self, steady, work, store, monkeypatch):
        """The newest snapshot of these same files is one that ChartBook 0.5 laid out, in a pipeline's folder copied into this store by hand: under snapshots/, and keeping most of its files in an earlier snapshot's folder. It is no increment, and no "folder that stands by itself" either: the folder `--complete` names holds every file."""
        from tests.store_of_0_5 import laid_out_as_0_5

        snapshot.make(steady, store=FolderStore(store.root), made_at=_at(0), complete=True)
        _drawn(steady, 1)
        snapshot.make(steady, store=FolderStore(store.root), made_at=_at(1), complete=True)
        old = laid_out_as_0_5(store.root)
        new = work / "new"
        (new / "snapshots").mkdir(parents=True)
        (new / "store.json").write_text('{"schema": "chartbook/store/v3"}\n', encoding="utf-8", newline="\n")
        shutil.copytree(old.root / "pipelines" / "acme+rates", new / "snapshots" / "acme+rates")
        store_module._found_whole.clear()
        first, second = _records(new)
        assert (first.complete, second.complete, second.increment) == (True, False, False)
        assert FolderStore(new).verify() == []  # whole, and read right: it is not complete by what its record is
        monkeypatch.setenv(config.STORE_ENV_VAR, str(new))
        made = _snapshot("--complete")
        assert made.exit_code == 0, made.output
        folder = _folder_named(made)
        (record,) = [one for one in _records(new) if one.folder == folder]
        assert record.complete and folder not in (first.folder, second.folder)
        assert (folder / "_data" / "history.parquet").is_file() and FolderStore(new).verify_snapshot(record.path) == []
        # Not asked, it is stood on as before, and nothing is made
        plain = _snapshot()
        assert _made(plain)[0].startswith("No new snapshot: ") and len(_records(new)) == 3

    def test_several_stores_the_first_is_asked_and_the_others_read_what_they_have(self, rates, work, store, two):
        """The first store is asked whether its own is complete and reads right. The others read what they have when a complete copy is sent, as before: one that is not what its record says there stops the command, naming the store and the file."""
        first = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(0))
        assert first.made and [len(_records(work / name)) for name in ("store", "there")] == [1, 1]
        asked = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(1), complete=True)
        assert not asked.made and asked.asked_complete and not asked.kept.increment and asked.kept_otherwise == []
        assert asked.kept.folder == first.kept.folder and [len(_records(work / name)) for name in ("store", "there")] == [1, 1]
        # The other store's copy damaged at the same size: found as that store's copy is read, and said
        (theirs,) = _records(work / "there")
        _damage(theirs.folder / "_data" / "treasury.parquet")
        with pytest.raises(snapshot.NotInEveryStore) as stopped:
            snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(2), complete=True)
        assert str(work / "there") in str(stopped.value) and "_data/treasury.parquet is no longer what its record says" in str(stopped.value)
        assert [len(_records(work / name)) for name in ("store", "there")] == [1, 1]
        # The first store's own copy damaged at the same size: a new complete one, written from the files at hand, in each
        _damage(first.kept.folder / "_data" / "treasury.parquet")
        made = snapshot.make(rates, store=two(), store_names=["here", "there"], made_at=_at(3), complete=True)
        assert made.made and not made.kept.increment and made.kept_otherwise == [] and made.kept.folder != first.kept.folder
        for name in ("store", "there"):
            (new,) = [record for record in _records(work / name) if record.made_at == _at(3)]
            assert new.complete and FolderStore(work / name).verify_snapshot(new.path) == []


@pytest.fixture
def elsewhere(work, store):
    """A store elsewhere with a complete snapshot of acme/sized and two increments on it; the store of the test is where it is copied to."""
    there = FolderStore(work / "source")
    kept = [_sized(there, work / "files", _same_30(k), k) for k in range(3)]
    assert [one.increment for one in kept] == [False, True, True]
    return there


def _from_to(source: FolderStore, target: FolderStore):
    """Two stores with names, as a catalog has them, for a `store move` from the first to the second."""
    from chartbook.multi_store import NamedStore, Stores

    return Stores([
        NamedStore("here", str(source.root), FolderStore(source.root)),
        NamedStore("there", str(target.root), FolderStore(target.root), create=True),
    ])


def _everything_in(root: Path) -> dict:
    """Every file under a folder, with its size."""
    return {path.relative_to(root).as_posix(): path.stat().st_size for path in sorted(root.rglob("*")) if path.is_file()}


class TestACopyThatKeepsAnIncrementsForm:
    """`store move` and `store import` write an increment as an increment, on the complete snapshot the target has: what stops one, and what it is written as where it does not fit."""

    def _base_goes_as_the_first_increment_is_written(self, monkeypatch, target_root: Path) -> list:
        """A `store gc` elsewhere takes the complete snapshot from the target once the first increment's files are in its folder there; when it did."""
        real = store_module._FolderPending._before_record
        fired: list = []

        def going(pending):
            real(pending)
            if pending.builds_on is not None and pending.store.root == target_root and not fired:
                fired.append(pending.builds_on)
                shutil.rmtree(pending.store.pipeline_path(pending.pipeline) / pending.builds_on, onerror=_writable)
                store_module._read_records.clear()
                store_module._found_whole.clear()

        monkeypatch.setattr(store_module._FolderPending, "_before_record", going)
        return fired

    def test_a_move_stopped_because_what_it_builds_on_went_says_to_run_the_command_again(self, elsewhere, store, monkeypatch):
        """It said "Make the snapshot again." Nobody can make an old snapshot again, and nothing needs it: the move is what is run again. Nothing is removed from the source, and nothing half-written is left."""
        from chartbook import transfer

        before, form = _everything_in(elsewhere.root), [(record.folder.name, record.increment) for record in _records(elsewhere.root)]
        with monkeypatch.context() as patched:
            fired = self._base_goes_as_the_first_increment_is_written(patched, store.root)
            with pytest.raises(store_module.StoreError) as stopped:
                transfer.move("acme/sized", _from_to(elsewhere, store), "there", keep=False, route=False)
        assert len(fired) == 1 and not isinstance(stopped.value, store_module.BuiltOnGoneError)
        assert str(stopped.value).endswith(
            ", which this one builds on, went from the store as this snapshot was being written. Run the command again."
        )
        assert _everything_in(elsewhere.root) == before
        assert _unrecorded_folders(store.root) == [] and _left_in_tmp(store.root) == [] and _records(store.root) == []
        # Run again, with nobody in the way, it is all there and whole, in the form it had
        store_module._found_whole.clear()
        transfer.move("acme/sized", _from_to(elsewhere, store), "there", keep=False, route=False)
        assert [(record.folder.name, record.increment) for record in _records(store.root)] == form
        assert FolderStore(store.root).verify() == [] and _records(elsewhere.root) == []

    def test_an_import_refused_because_what_it_builds_on_went_says_to_run_the_command_again(self, elsewhere, store, monkeypatch):
        with monkeypatch.context() as patched:
            self._base_goes_as_the_first_increment_is_written(patched, store.root)
            said = CliRunner().invoke(main, ["store", "import", str(elsewhere.root)])
        assert said.exit_code == 1
        (refused,) = [line for line in said.output.splitlines() if line.startswith("Refused: ")]
        assert "went from the store as this snapshot was being written. Run the command again." in refused
        assert "Make the snapshot again" not in said.output
        assert _unrecorded_folders(store.root) == [] and _left_in_tmp(store.root) == []
        # Run again, what is not there comes as it can
        store_module._found_whole.clear()
        again = CliRunner().invoke(main, ["store", "import", str(elsewhere.root)])
        assert again.exit_code == 0 and "Refused" not in again.output and FolderStore(store.root).verify() == []

    def _too_long_there(self, work: Path, monkeypatch) -> tuple:
        """A store in a short folder with a complete snapshot and an increment whose own file has a long name, and a target in a longer folder, under whose snapshots/ that file fits by one character."""
        place = "data/" + "f" * 40 + ".bin"
        short = FolderStore(work / "s")
        first = _of_files(short, work / "files", [("a", place, b"a" * 10), ("big", "data/big.bin", BIG)], 0)
        second = _of_files(short, work / "files", [("a", place, b"b" * 10), ("big", "data/big.bin", BIG)], 1)
        assert not first.increment and second.increment
        assert [sorted(_own(record)) for record in _records(short.root) if record.increment] == [[place]]
        target = FolderStore(work / "a-longer-folder")
        name = store_module.snapshot_folder_name(_at(0), COMMIT)
        under_snapshots = target.root / "snapshots" / "acme+sized" / name / place
        monkeypatch.setattr(store_module, "_ON_WINDOWS", True)
        monkeypatch.setattr(store_module, "long_paths_enabled", lambda: False)
        monkeypatch.setattr(store_module, "WINDOWS_PATH_LIMIT", len(str(under_snapshots)) + 1)  # it fits, by one
        monkeypatch.setattr(store_module, "WINDOWS_FOLDER_LIMIT", len(str(under_snapshots)) + 100)
        return short, target, place

    def test_a_move_writes_it_complete_where_its_own_file_does_not_fit_under_increments(self, work, monkeypatch):
        from chartbook import transfer

        short, target, place = self._too_long_there(work, monkeypatch)
        transfer.move("acme/sized", _from_to(short, target), "there", keep=False, route=False)
        there = _records(target.root)
        assert [record.complete for record in there] == [True, True] and (there[1].folder / place).read_bytes() == b"b" * 10
        assert FolderStore(target.root).verify() == [] and _unrecorded_folders(target.root) == [] and _left_in_tmp(target.root) == []
        assert not any((target.root / "increments").rglob("*")) if (target.root / "increments").exists() else True

    def test_an_import_writes_it_complete_where_its_own_file_does_not_fit_under_increments(self, work, monkeypatch):
        from chartbook import sharing

        short, target, place = self._too_long_there(work, monkeypatch)
        done = sharing.import_snapshots(FolderStore(target.root), short.root)
        assert done.refused == [] and len(done.copied) == 2
        there = _records(target.root)
        assert [record.complete for record in there] == [True, True] and (there[1].folder / place).read_bytes() == b"b" * 10
        assert FolderStore(target.root).verify() == [] and _unrecorded_folders(target.root) == [] and _left_in_tmp(target.root) == []


class TestTheHelpersOfTheClosingLine:
    """tests/snapshot_lines.py: a caller names the form, the numbers are taken by pattern, and only counts that can be are taken."""

    def test_a_snapshot_said_in_one_form_does_not_pass_for_another(self):
        from tests import snapshot_lines

        increment = "Snapshot made, kept as an increment: 2 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.\n" + PIN_LINE
        added = "Snapshot made: 5 files, 23.0 MB. The increments since the last complete one had added up to its size.\n" + PIN_LINE
        complete = "Snapshot made: 5 files, 23.0 MB.\n" + PIN_LINE
        forms = {snapshot_lines.INCREMENT: increment, snapshot_lines.ADDED_UP: added, snapshot_lines.COMPLETE: complete}
        for form, said in forms.items():
            assert [other for other in forms if snapshot_lines.said_made(said, other)] == [form]

    @pytest.mark.parametrize("line,form", [
        ("Snapshot made, kept as an increment: 9 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.", "increment"),
        ("Snapshot made, kept as an increment: 5 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.", "increment"),
        ("Snapshot made, kept as an increment: 1 of 1 file, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.", "increment"),
        ("Snapshot made: 1 files, 23.0 MB.", "complete"),
        ("Snapshot made: 0 files, 0 bytes.", "complete"),
        ("Snapshot made: 1 files, 23.0 MB. The increments since the last complete one had added up to its size.", "added up"),
        ("Snapshot made: 1 files, 23.0 MB, for what depends on it in this run to pin.", "complete"),
    ])
    def test_a_count_that_cannot_be_does_not_pass(self, line, form):
        from tests import snapshot_lines

        assert not snapshot_lines.said_made(line + "\n" + PIN_LINE, form)
        assert not snapshot_lines.said_made_for_this_run(line, form)

    @pytest.mark.parametrize("line,form", [
        ("Snapshot made, kept as an increment: 0 of 1 file, 0 bytes. The rest is in the snapshot made 2026-11-16 09:15 UTC.", "increment"),
        ("Snapshot made, kept as an increment: 4 of 5 files, 409.6 KB. The rest is in the snapshot made 2026-11-16 09:15 UTC.", "increment"),
        ("Snapshot made: 1 file, 12 bytes.", "complete"),
        ("Snapshot made: 12 files, 1.2 GB.", "complete"),
    ])
    def test_a_count_that_can_be_passes(self, line, form):
        from tests import snapshot_lines

        assert snapshot_lines.said_made(line + "\n" + PIN_LINE, form)


class TestGcAndVerifyWhereWhatTheIncrementsBuildOnHasGone:
    """The reference, and the help of `store gc`: gc names the snapshot whose folder the file is missing from, as `store verify` names it; and where that snapshot has itself gone from the store, gc names the newest increment that kept the file there, and verify the folder that has gone."""

    def test_the_pages_say_both_cases(self):
        reference = " ".join(_page("docs_src", "reference", "cli.md").split())
        assert "The snapshot it names is the one whose folder the file is missing from, as `store verify` names it" in reference
        assert (
            "Where that snapshot has itself gone from the store, `gc` names the newest increment that kept the file there, a "
            "snapshot the store still has, and `store verify` names the folder that has gone"
        ) in reference
        said = _help("store", "gc")
        assert "the snapshot whose folder the file is missing from, as `chartbook store verify` names it, or, where that snapshot has itself gone from the store" in said
        assert "the newest of those that kept the file there, which verify names by the folder that has gone" in said

    def test_gc_names_a_snapshot_the_store_has_and_verify_the_folder_that_has_gone(self, steady, store):
        made = _three(steady, store)
        _drawn(steady, 3)
        made.append(snapshot.make(steady, store=FolderStore(store.root), made_at=_at(3)))
        assert made[3].kept.increment and made[3].kept.builds_on == made[0].kept.folder.name
        shutil.rmtree(made[0].kept.folder, onerror=_writable)
        store_module._read_records.clear()
        store_module._found_whole.clear()
        verified = CliRunner().invoke(main, ["store", "verify"]).output
        named_by_verify = set(re.findall(r"_data/history\.parquet is not in the store \(the snapshot (\S+)\)", verified))
        said = CliRunner().invoke(main, ["store", "gc", "--dry-run", "--keep-days", "0"]).output
        named_by_gc = set(re.findall(r"Nothing of acme/rates is removed: its snapshot (\S+) lacks", said))
        assert named_by_verify == {made[0].kept.folder.name}  # the folder that has gone, where the file was
        assert named_by_gc == {made[3].kept.folder.name}  # the newest increment that kept it there: one the store has
        assert "3 snapshots kept as increments on it keep it there" in verified
