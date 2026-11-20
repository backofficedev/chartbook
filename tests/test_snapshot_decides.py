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
import json
import os
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


def _sized(store: FolderStore, scratch: Path, versions: list, number: int, complete: bool = False, made_by: str = "snapshot"):
    """Write one snapshot of acme/sized: a file of UNIT bytes for each of *versions*, file i at the version given.

    As :func:`chartbook.snapshot.make` writes one once every file of it is
    put: the store is asked how it is to keep it
    (:func:`chartbook.snapshot.to_be_kept`), told, and the record is
    written. Nothing else is in it, so its size is exact.

    :returns: How the store keeps it, as its record says.
    """
    owner = made_by == "snapshot"
    pending = store.begin("acme/sized", COMMIT, _at(number), made_by=made_by, **({"undecided": True} if owner else {}))
    assets, held = {}, {}
    scratch.mkdir(exist_ok=True)
    for file, version in enumerate(versions):
        local = AssetRef(kind="dataframe", name=f"f{file:03d}")
        source = scratch / f"{local.name}.bin"
        source.write_bytes(f"{file:03d}{version:05d}".encode())
        put = pending.put(source, place=f"data/{local.name}.bin")
        assets[str(local)] = snapshot.asset_record(local.in_pipeline("acme/sized"), "acme/sized", f"./data/{local.name}.bin", put, True)
        held[str(local)] = put.stored
    taken = snapshot.Snapshot("acme/sized", COMMIT, "", _at(number), assets, stored={"records": held})
    if owner:
        decided = snapshot.to_be_kept(store, taken, complete)
        if decided.increment:
            pending.keep_as_increment(decided.builds_on, decided.increments_bytes)
    path = pending.write({**taken.to_document(), **({} if owner else {"made_by": made_by})})
    return snapshot.as_kept(FolderStore(store.root), dataclasses.replace(taken, path=path))


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
    """What the increments have added up to is kept in the records: each increment's says the total up to and with itself."""

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

    def test_it_survives_the_removal_of_an_older_increment_and_is_read_from_the_newest(self, store, work):
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
    return CliRunner().invoke(main, ["snapshot", "--no-gc-reminder", *arguments])


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
