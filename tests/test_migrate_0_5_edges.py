"""The mover at its edges: what a review of the move after a real store found (2026-11-20), and the rule chosen for each.

The review could not make the lookup of ``tests/test_migrate_0_5_found.py``
lose a file or leave two trees. What it found was at the edges, and each
case is here with its rule:

- N1. Every try of a rename first sees that nothing is where it goes.
- N2. No part of a path a file is taken from is a link, and only a plain
  file is renamed.
- N3. The mover finds a file as the store's reader finds it.
- N4. A copy is made only from a file at its size.
- N5. ``check`` asks the disk what a step will ask.
- N6. A folder with no record that is named for a snapshot whose record
  is in another folder is said as that, with nothing to wait for.
- N7. A file that goes aside with a second record is said, where the
  snapshot in the store lacks it.
- N8. Once the old folder is aside the store is moved.
- N9. A folder under ``pipelines/`` whose name is no pipeline's is passed
  over and said; and the line about a link says what is true.
- N10. Every file that was not where its record says, and is read
  afterwards, is counted.
- N12. A second record is not asked where bytes are; the last lines say
  to look in what went aside where files are missing.

(N11, the time a plan takes, is ``tests/test_migrate_0_5_size.py``.)
"""

import hashlib
import json
import os
import shutil
import stat
import types
import unicodedata
from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import config, migrate_0_5, replacing
from chartbook import store as store_module
from chartbook.cli import main
from tests.found_store_of_0_5 import WIDE, facts_before, stopped_then, wide_store, worse_after
from tests.rich_store_of_0_5 import (
    OWN,
    Stop,
    contents,
    empty_store,
    folder_of,
    fresh,
    not_its_own,
    put,
    read_through,
    record,
    rmtree,
    stop_after,
    tree_of,
    watch,
)

ASIDE = "_chartbook/left-by-0.5"
A, B, C, K, G = b"a" * 100, b"b" * 200, b"c" * 300, b"k" * 400, b"g" * 150
C0 = folder_of("2025-09-01", "h")
WAIT = "If a sync may still be bringing a folder's record, wait for it and run this again"


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    """An empty store of 0.5, as the store of the commands typed."""
    root = empty_store(work)
    monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
    return root


def typed(*words):
    result = CliRunner().invoke(main, list(words))
    assert result.exception is None or isinstance(result.exception, SystemExit), (words, repr(result.exception))
    return result, result.output.replace("\n", " ")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_or_stopped_before(root) -> bool:
    """Run a move. It may refuse before anything moves (the tree is then as it was); it may never fail part way."""
    before = tree_of(root)
    try:
        migrate_0_5.run(root)
    except migrate_0_5.MoveError:
        assert tree_of(root) == before, "refused, and the store is not as it was"
        return False
    return True


def second_folder(root, pipeline: str, snapshot: str, rewrite=lambda text: text) -> str:
    """A sync's second copy of a snapshot's record, in a folder ``<name> 2``; the record's text as *rewrite* leaves it."""
    first = root / "pipelines" / pipeline / snapshot / "_chartbook" / "snapshot.json"
    copy = root / "pipelines" / pipeline / f"{snapshot} 2" / "_chartbook" / "snapshot.json"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(rewrite(first.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    return f"{snapshot} 2"


class TestEveryTryOfARenameLooksFirst:
    """N1. A rename that Windows refuses is tried again for two seconds, and ``os.replace`` writes over what is at its target: what holds the file may write there meanwhile (a sync client that is bringing it)."""

    def _refused_once(self, monkeypatch, wanted, bring) -> list:
        """Stand in for Windows inside ``chartbook.replacing`` alone, as ``TestARenameWindowsRefusesForAMoment`` does: the first rename to a place *wanted* picks is refused once, and in that moment *bring* puts something there."""
        refused: list = []

        def held_once(source, destination):
            if wanted(Path(destination)) and not refused:
                refused.append(Path(destination))
                bring(Path(destination))
                raise PermissionError(13, "Access is denied", str(source))
            return os.replace(source, destination)

        monkeypatch.setattr(replacing, "sys", types.SimpleNamespace(platform="win32"))
        monkeypatch.setattr(replacing, "os", types.SimpleNamespace(replace=held_once))
        monkeypatch.setattr(replacing, "_WAIT_SECONDS", 0)
        return refused

    def _two_pins(self, root):
        """Two snapshots a pin made that share a file: one rename, one copy, two records, and the notes."""
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, "_data/k.parquet", K)
        record(root, "acme/q", "2025-10-01", "e", [("_data/k.parquet", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [("_data/k.parquet", K, q1, None)], made_by="pin")
        return q1, q2

    def test_a_rename_that_is_tried_again_does_not_land_on_a_file_that_came_to_be_there_meanwhile(self, work, monkeypatch):
        root = empty_store(work)
        q1, _ = self._two_pins(root)
        place = f"snapshots/acme+q/{q1}/_data/k.parquet"
        brought = b"what a sync brought to that place while the rename was refused"
        refused = self._refused_once(monkeypatch, lambda to: to == root / place, lambda to: to.write_bytes(brought))
        done = migrate_0_5.run(root)
        assert refused == [root / place]
        # The file that came to be there stays; the one at the old place goes aside with the old folder, and both are said
        old = f"{ASIDE}/pipelines/acme+q/{q1}/_data/k.parquet"
        assert (root / place).read_bytes() == brought and (root / old).read_bytes() == K
        assert done.in_place == [(old, place, len(K), len(brought))]

    def test_the_old_folder_goes_aside_under_the_next_free_name(self, work, monkeypatch):
        root = empty_store(work)
        self._two_pins(root)
        first = root / ASIDE / "pipelines"
        refused = self._refused_once(monkeypatch, lambda to: to == first, lambda to: (to / "came-meanwhile").mkdir(parents=True))
        done = migrate_0_5.run(root)
        assert refused and done.kept == f"{ASIDE}/pipelines (2)" and (root / done.kept / "acme+q").is_dir()
        assert sorted(p.name for p in first.iterdir()) == ["came-meanwhile"]

    def test_a_copy_is_not_put_onto_a_file_that_came_to_be_there_and_its_temporary_goes(self, work, monkeypatch):
        root = empty_store(work)
        q1, q2 = self._two_pins(root)
        place = root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet"
        brought = b"k" * 399 + b"!"  # of its size, and other bytes
        refused = self._refused_once(monkeypatch, lambda to: to == place, lambda to: to.write_bytes(brought))
        migrate_0_5.run(root)
        assert refused and place.read_bytes() == brought and not list(root.rglob("*.moving"))
        assert (root / "snapshots" / "acme+q" / q1 / "_data" / "k.parquet").read_bytes() == K

    def test_a_record_that_came_to_be_there_is_put_aside_and_never_written_over(self, work, monkeypatch):
        root = empty_store(work)
        q1, _ = self._two_pins(root)
        place = root / "snapshots" / "acme+q" / q1 / "_chartbook" / "snapshot.json"
        refused = self._refused_once(monkeypatch, lambda to: to == place, lambda to: to.write_text('{"of": "other words"}\n', encoding="utf-8", newline="\n"))
        migrate_0_5.run(root)
        assert refused and (root / ASIDE / "snapshots" / "acme+q" / q1 / "_chartbook" / "snapshot.json").read_text(encoding="utf-8") == '{"of": "other words"}\n'
        assert fresh(root).verify() == [] and not list(root.rglob("*.moving"))

    def test_a_note_that_came_to_be_there_stays(self, work, monkeypatch):
        root = empty_store(work)
        self._two_pins(root)
        place = root / "README.txt"
        refused = self._refused_once(monkeypatch, lambda to: to == place, lambda to: to.write_text("Ours. Ask Dana.\n", encoding="utf-8", newline="\n"))
        migrate_0_5.run(root)
        assert refused and place.read_text(encoding="utf-8") == "Ours. Ask Dana.\n" and not list(root.rglob("*.moving"))

    def test_the_notes_are_merged_into_a_folder_that_came_to_be_there(self, work, monkeypatch):
        root = empty_store(work)
        self._two_pins(root)
        (root / "roots" / ("ab" * 16 + ".json")).write_text("{}\n", encoding="utf-8", newline="\n")
        place = root / "_chartbook" / "roots"

        def bring(to):
            to.mkdir(parents=True)
            (to / ("cd" * 16 + ".json")).write_text('{"came": "meanwhile"}\n', encoding="utf-8", newline="\n")

        refused = self._refused_once(monkeypatch, lambda to: to == place, bring)
        migrate_0_5.run(root)
        assert refused and sorted(p.name for p in place.iterdir()) == ["ab" * 16 + ".json", "cd" * 16 + ".json"]
        assert (place / ("cd" * 16 + ".json")).read_text(encoding="utf-8") == '{"came": "meanwhile"}\n'

    def test_the_rename_itself_says_whether_it_was_made(self, tmp_path, monkeypatch):
        """``replacing.replace_when_free``: False where something is at the target, which stays; and a refusal on another system than Windows is said at once."""
        (tmp_path / "a").write_bytes(b"a")
        (tmp_path / "b").write_bytes(b"b")
        assert replacing.replace_when_free(tmp_path / "a", tmp_path / "b") is False and (tmp_path / "b").read_bytes() == b"b"
        assert replacing.replace_when_free(tmp_path / "a", tmp_path / "c") is True and (tmp_path / "c").read_bytes() == b"a"
        if os.name != "nt":
            (tmp_path / "link").symlink_to(tmp_path / "nowhere")
            assert replacing.replace_when_free(tmp_path / "b", tmp_path / "link") is False  # a link that leads nowhere is there too

        def refused(source, target):
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(replacing.os, "replace", refused)
        monkeypatch.setattr(replacing.sys, "platform", "linux")
        with pytest.raises(PermissionError):
            replacing.replace_when_free(tmp_path / "b", tmp_path / "d")

    def test_the_journal_and_the_marker_are_the_moves_own_and_are_written_over(self, work, monkeypatch):
        root = empty_store(work)
        self._two_pins(root)
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            migrate_0_5.run(root)
        assert not_its_own(gone) == [] and ("replace onto", "store.json") in gone


class TestOnlyAPlainFileIsTakenAndThroughNoLink:
    """N2. Each store has ``acme/p`` with a folder that has no record (``c0``), and records that say a file is kept in it."""

    def test_a_folder_named_as_a_file_a_record_names_is_not_renamed_into_a_snapshot_with_another_snapshots_file_in_it(self, work):
        """``c0/_data/k.parquet`` is a folder (a dataset of parts). The older snapshot's record names a part in it, which is there; the newest names ``_data/k.parquet`` as one file, which is not."""
        root = empty_store(work)
        part = b"p" * 90
        put(root, "acme+p", C0, "_data/k.parquet/part-0.parquet", part)
        s1 = record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet/part-0.parquet", part, C0, None)])
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        before = facts_before(root)
        assert before[("acme/p", s1, "_data/k.parquet/part-0.parquet")][1] is True  # 0.5 read it where its record says
        assert migrate_0_5.plan(root).missing == [(s2, "_data/k.parquet")]  # a folder is no file: counted, and said
        done = migrate_0_5.run(root)
        assert worse_after(before, root) == ([], []) and done.missing == [(s2, "_data/k.parquet")]
        assert sorted(path.relative_to(root).as_posix() for path in root.rglob("part-0.parquet")) == [f"increments/acme+p/{s1}/_data/k.parquet/part-0.parquet"]
        assert not os.path.lexists(root / "snapshots" / "acme+p" / s2 / "_data" / "k.parquet")

    def test_a_folder_named_as_a_file_a_record_names_goes_aside_with_what_no_record_names_in_it(self, work):
        root = empty_store(work)
        put(root, "acme+p", C0, "_data/k.parquet/notes.txt", b"nobody names this")
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        done = migrate_0_5.run(root)
        assert done.missing == [(s2, "_data/k.parquet")] and done.aside == 1
        assert not list((root / "snapshots").rglob("notes.txt"))
        assert (root / ASIDE / "pipelines" / "acme+p" / C0 / "_data" / "k.parquet" / "notes.txt").read_bytes() == b"nobody names this"

    @pytest.mark.skipif(os.name == "nt", reason="a link needs a privilege on Windows")
    def test_a_file_is_not_taken_out_of_a_folder_outside_the_store_through_a_linked_folder(self, work):
        """``c0/_data`` is a link to a folder outside the store: three folders deep, where ``check`` looked two."""
        root = empty_store(work)
        outside = work / "not-the-store" / "data"
        outside.mkdir(parents=True)
        (outside / "k.parquet").write_bytes(K)
        put(root, "acme+p", C0, "plain.bin", b"a plain file, so the folder holds one")
        link = root / "pipelines" / "acme+p" / C0 / "_data"
        os.symlink(outside, link)
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        before = tree_of(root)
        with pytest.raises(migrate_0_5.MoveError) as stopped:
            migrate_0_5.run(root)
        assert str(stopped.value).startswith(f"{link} is a link to another place, and a move does not follow one: the store is not moved.")
        assert tree_of(root) == before and (outside / "k.parquet").read_bytes() == K and not (root / migrate_0_5.JOURNAL).exists()
        # The way out, as the line says: the folder itself where the link is
        os.unlink(link)
        os.replace(outside, link)
        migrate_0_5.run(root)
        assert read_through(root) == {("acme/p", s2, "_data/k.parquet"): sha(K)}

    @pytest.mark.skipif(os.name == "nt", reason="a link needs a privilege on Windows")
    def test_a_link_where_a_record_names_a_file_stays_out_of_the_snapshots(self, work):
        """``c0/_data/k.parquet`` is a link to a file elsewhere: no file the store keeps, before or after. It is counted missing, and goes aside as it is."""
        root = empty_store(work)
        outside = work / "not-the-store"
        outside.mkdir()
        (outside / "k.parquet").write_bytes(K)
        put(root, "acme+p", C0, "plain.bin", b"a plain file")
        (root / "pipelines" / "acme+p" / C0 / "_data").mkdir()
        os.symlink(outside / "k.parquet", root / "pipelines" / "acme+p" / C0 / "_data" / "k.parquet")
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        assert migrate_0_5.plan(root).missing == [(s2, "_data/k.parquet")]
        done = migrate_0_5.run(root)
        assert done.missing == [(s2, "_data/k.parquet")] and (outside / "k.parquet").read_bytes() == K
        assert not os.path.lexists(root / "snapshots" / "acme+p" / s2 / "_data" / "k.parquet")
        assert (root / ASIDE / "pipelines" / "acme+p" / C0 / "_data" / "k.parquet").is_symlink()

    @pytest.mark.skipif(os.name == "nt", reason="a link needs a privilege on Windows")
    def test_the_folder_itself_being_a_link_stops_the_move_before_anything(self, work):
        root = empty_store(work)
        outside = work / "not-the-store"
        (outside / "_data").mkdir(parents=True)
        (outside / "_data" / "k.parquet").write_bytes(K)
        (root / "pipelines" / "acme+p").mkdir(parents=True)
        os.symlink(outside, root / "pipelines" / "acme+p" / C0)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        before = tree_of(root)
        with pytest.raises(migrate_0_5.MoveError, match="is a link to another place"):
            migrate_0_5.run(root)
        assert tree_of(root) == before and (outside / "_data" / "k.parquet").is_file()


class TestTheMoverFindsAFileAsTheStoresReaderDoes:
    """N3. A name a sync wrote in the other of Unicode's forms is the file (``store.on_disk``): the size, the rename and the count of what goes aside ask about the one file."""

    def _in_the_other_form(self, root):
        name = "café.parquet"
        put(root, "acme+p", C0, f"_data/{unicodedata.normalize('NFD', name)}", K)
        s2 = record(root, "acme/p", "2025-11-01", "b", [(f"_data/{name}", K, C0, None)])
        store_module._read_records.clear()
        return name, s2, not (root / "pipelines" / "acme+p" / C0 / "_data" / name).exists()

    def test_a_name_in_the_other_of_unicodes_forms_is_not_counted_as_a_file_no_record_names(self, work):
        """On a disk that takes the two forms for one name (macOS): the file is moved in, and was counted among those that go aside too."""
        root = empty_store(work)
        name, s2, tells_apart = self._in_the_other_form(root)
        if tells_apart:
            pytest.skip("this disk tells the two forms apart: the next test is the one for it")
        before = facts_before(root)
        found = migrate_0_5.plan(root)
        done = migrate_0_5.run(root)
        assert worse_after(before, root) == ([], []) and (found.renamed, found.missing) == (1, [])
        assert (found.aside, found.doubled) == (0, 0) == (done.aside, done.doubled)

    def test_on_a_disk_that_tells_the_two_forms_apart_a_file_the_store_read_is_still_read(self, work):
        """The store's own reader takes a name a sync wrote in the other form, so the snapshot is whole before the move: the mover asks for the file by the name the disk has. Linux and Windows; not a Mac."""
        root = empty_store(work)
        name, s2, tells_apart = self._in_the_other_form(root)
        if not tells_apart:
            pytest.skip("this disk takes the two forms of a name for one (APFS): the file is found under either")
        old = root / "pipelines" / "acme+p" / s2 / "_chartbook" / "snapshot.json"
        assert fresh(root).holes_of(old) == []  # whole, to the store's reader
        found = migrate_0_5.plan(root)
        done = migrate_0_5.run(root)
        new = root / "snapshots" / "acme+p" / s2 / "_chartbook" / "snapshot.json"
        assert fresh(root).holes_of(new) == [] and done.missing == [] and (found.renamed, found.aside) == (1, 0)
        assert (root / "snapshots" / "acme+p" / s2 / "_data" / name).read_bytes() == K  # under the name its record writes

    def test_a_name_of_other_letter_case_than_its_record_is_moved_and_not_counted_as_a_file_no_record_names(self, work):
        root = empty_store(work)
        if migrate_0_5._tells_case_apart(root):
            pytest.skip("this disk tells letter case apart: the file is not its record's, before or after")
        put(root, "acme+p", C0, "_data/K.PARQUET", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        before = facts_before(root)
        found = migrate_0_5.plan(root)
        done = migrate_0_5.run(root)
        assert worse_after(before, root) == ([], []) and (found.renamed, found.missing) == (1, [])
        assert found.aside == 0 and done.aside == 0

    def test_a_plain_name_asks_the_disk_nothing_more(self, work, monkeypatch):
        """``on_disk`` looks at nothing for an ASCII name, and the mover does not call it for one: an ordinary store pays nothing for this."""
        root = empty_store(work)
        wide_store(root, 3)
        monkeypatch.setattr(migrate_0_5, "on_disk", lambda *asked: pytest.fail(f"asked for {asked}"))
        assert migrate_0_5.plan(root).steps


class TestACopyIsMadeOnlyFromAFileAtItsSize:
    """N4. A store whose new trees hold a file already, of another size than its record says: what a sync leaves of a move made on another machine, part brought. ChartBook 0.5 does not look under ``snapshots/``: both snapshots here read before the move."""

    def test_a_pin_that_names_the_same_place_is_not_given_a_copy_of_the_wrong_file_in_place(self, work):
        """The newest keeps K in its own folder, whole; a pin's snapshot names it there too. Part of K is where the newest one's goes already."""
        root = empty_store(work)
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        p3 = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, s2, None)], made_by="pin")
        put(root, "acme+p", s2, "_data/k.parquet", K[:150], tree="snapshots")
        before = facts_before(root)
        assert all(at_place for _, at_place, _ in before.values())  # 0.5 read both
        found = migrate_0_5.plan(root)
        # Not from the part in place: from the whole file at the old place, which then goes aside, read and not moved
        assert [(step.op, step.source, step.target) for step in found.steps if step.op == "copy"] == [
            ("copy", f"pipelines/acme+p/{s2}/_data/k.parquet", f"snapshots/acme+p/{p3}/_data/k.parquet")
        ]
        done = migrate_0_5.run(root)
        lost, _ = worse_after(before, root)
        # The newest one's is said, as a file found in place is (the whole one went aside)
        assert done.in_place == [(f"{ASIDE}/pipelines/acme+p/{s2}/_data/k.parquet", f"snapshots/acme+p/{s2}/_data/k.parquet", 400, 150)]
        assert (root / ASIDE / "pipelines" / "acme+p" / s2 / "_data" / "k.parquet").read_bytes() == K
        assert lost == [("acme/p", s2, "_data/k.parquet")] and done.copied_as_is == []  # the pin's reads; the newest one's is the part in place
        assert (root / "snapshots" / "acme+p" / p3 / "_data" / "k.parquet").read_bytes() == K

    def test_a_pin_whose_own_place_is_empty_is_given_the_bytes_that_are_whole_at_the_old_place_of_the_newest(self, work):
        """The pin says K is in a folder that is not there; the newest has it whole at its old place, and part of it where it goes."""
        root = empty_store(work)
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        p3 = record(root, "acme/p", "2025-11-15", "c", [("_data/k.parquet", K, C0, None)], made_by="pin")
        put(root, "acme+p", s2, "_data/k.parquet", K[:150], tree="snapshots")
        before = facts_before(root)
        assert before[("acme/p", p3, "_data/k.parquet")][1:] == (False, True)  # not where its record says; where another's does
        found = migrate_0_5.plan(root)
        assert found.elsewhere == 1 and found.missing == []
        done = migrate_0_5.run(root)
        _, not_taken = worse_after(before, root)
        assert (root / ASIDE / "pipelines" / "acme+p" / s2 / "_data" / "k.parquet").read_bytes() == K  # the whole file, aside
        assert not_taken == [("acme/p", s2, "_data/k.parquet")] and done.missing == []
        assert (root / "snapshots" / "acme+p" / p3 / "_data" / "k.parquet").read_bytes() == K

    def test_part_of_a_file_is_put_where_its_record_names_it_and_copied_to_nobody(self, work):
        """A store of 0.5 as it is, with part of a file two pins share: before, the part was copied for the second; now the second's is missing, as it was."""
        root = empty_store(work)
        q1 = folder_of("2025-10-01", "e")
        put(root, "acme+q", q1, "_data/k.parquet", K[:150])
        record(root, "acme/q", "2025-10-01", "e", [("_data/k.parquet", K, None, None)], made_by="pin")
        q2 = record(root, "acme/q", "2025-11-01", "f", [("_data/k.parquet", K, q1, None)], made_by="pin")
        found = migrate_0_5.plan(root)
        assert found.missing == [(q1, "_data/k.parquet"), (q2, "_data/k.parquet")] and (found.renamed, found.copied) == (1, 0)
        done = migrate_0_5.run(root)
        assert done.missing == found.missing and done.copied_as_is == []
        assert (root / "snapshots" / "acme+q" / q1 / "_data" / "k.parquet").read_bytes() == K[:150]
        assert not os.path.lexists(root / "snapshots" / "acme+q" / q2 / "_data" / "k.parquet")


class TestCheckAsksTheDiskWhatAStepWillAsk:
    """N5. What stops a step half way is found before the first one."""

    def _long(self, root):
        name = "k" * 243 + ".parquet"  # 251 characters: the disk takes 255, and 0.5 stored a file under its own name
        try:
            put(root, "acme+p", C0, f"_data/{name}", K)
        except OSError:
            pytest.skip("this disk does not take a name of 251 characters")
        s2 = record(root, "acme/p", "2025-11-01", "b", [(f"_data/{name}", K, C0, None)])
        p3 = record(root, "acme/p", "2025-11-15", "c", [(f"_data/{name}", K, C0, None)], made_by="pin")
        return name, s2, p3

    def test_a_file_two_snapshots_must_each_hold_whose_name_leaves_no_room_for_the_movers_temporary_name(self, work):
        """A copy was written as ``<name>.moving`` first: seven characters more than a name the disk took."""
        root = empty_store(work)
        name, s2, p3 = self._long(root)
        before = facts_before(root)
        temporary = migrate_0_5._temporary_of(root / "snapshots" / "acme+p" / p3 / "_data" / name)
        assert temporary.name.endswith(".moving") and len(temporary.name) == 39 and temporary.parent.name == "_data"
        migrate_0_5.run(root)
        assert worse_after(before, root) == ([], []) and (root / "snapshots" / "acme+p" / p3 / "_data" / name).read_bytes() == K

    def test_the_command_goes_through_in_one_run(self, store):
        """It stopped half way at the copy, said to run it again, and stopped at the same file each time."""
        name, s2, p3 = self._long(store)
        first, said = typed("store", "migrate", "--yes")
        assert first.exit_code == 0, said[-400:]
        assert read_through(store) == {("acme/p", s2, f"_data/{name}"): sha(K), ("acme/p", p3, f"_data/{name}"): sha(K)}

    def test_a_temporary_left_under_the_short_name_by_a_move_cut_short_is_known_and_replaced(self, work):
        root = empty_store(work)
        name, s2, p3 = self._long(root)
        left = migrate_0_5._temporary_of(root / "snapshots" / "acme+p" / p3 / "_data" / name)
        left.parent.mkdir(parents=True)
        left.write_bytes(b"half")
        os.chmod(left, stat.S_IREAD)
        migrate_0_5.run(root)
        assert not left.exists() and not list(root.rglob("*.moving")) and fresh(root).verify() == []
        # The same name every time, and an ordinary name's is the name and ".moving", as it was
        assert migrate_0_5._temporary_of(left.with_name(name)) == left and migrate_0_5._temporary_of(Path("x") / "snapshot.json").name == "snapshot.json.moving"

    @pytest.mark.skipif(not hasattr(os, "chflags") or not hasattr(stat, "UF_IMMUTABLE"), reason="a file is locked this way on macOS and BSD")
    def test_a_locked_file_that_a_record_names_is_found_before_the_first_step(self, work):
        """Finder's "Locked" box (the flag ``uchg``): the file can be read and cannot be renamed. Its folder may be written, which was all ``check`` asked."""
        root = empty_store(work)
        put(root, "acme+p", C0, "_data/a.parquet", b"a" * 50)
        locked = put(root, "acme+p", C0, "_data/k.parquet", K)
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", b"a" * 50, C0, None), ("_data/k.parquet", K, C0, None)])
        try:
            os.chflags(locked, stat.UF_IMMUTABLE)
        except OSError:
            pytest.skip("this disk does not take the flag")
        before = tree_of(root)
        try:
            with pytest.raises(migrate_0_5.MoveError) as stopped:
                migrate_0_5.run(root)
            assert str(stopped.value).startswith(f"{locked} is locked, and this system renames nothing that is: the store is not moved. Unlock it")
            assert tree_of(root) == before and not (root / "snapshots").exists()
        finally:
            os.chflags(locked, 0)
        migrate_0_5.run(root)  # the way out, carried out
        assert read_through(root) == {("acme/p", s2, "_data/a.parquet"): sha(b"a" * 50), ("acme/p", s2, "_data/k.parquet"): sha(K)}


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="modes of folders, as a user who is not root")
class TestWhatThisUserMayNotWrite:
    """N5, the old folders: a folder changes its parent only where this user may write the folder itself."""

    def _locked(self, path):
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)

    def _open(self, root):
        for path in [root] + [p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()]:
            os.chmod(path, stat.S_IRWXU)

    @pytest.mark.parametrize("locked", ["pipelines", "roots", "pipelines/acme+p"])
    def test_the_old_folder_that_may_not_be_written_is_found_before_the_first_step(self, work, locked):
        """The last step renames ``pipelines/`` under ``_chartbook/``, and an earlier one ``roots/``."""
        root = empty_store(work)
        put(root, "acme+p", C0, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        self._locked(root / locked)
        before = tree_of(root)
        try:
            if locked == "pipelines/acme+p":
                migrate_0_5.run(root)  # a folder that stays where it is in what goes aside, and that no file leaves: not asked
            else:
                with pytest.raises(migrate_0_5.MoveError) as stopped:
                    migrate_0_5.run(root)
                assert str(stopped.value).startswith(f"The folder {root / locked} is not one this user may write")
                assert tree_of(root) == before
        finally:
            self._open(root)

    def test_a_folder_inside_it_that_may_not_be_written_stops_the_move_before_anything(self, work):
        root = empty_store(work)
        put(root, "acme+p", C0, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        self._locked(root / "pipelines" / "acme+p" / C0 / "_data")
        before = tree_of(root)
        try:
            with pytest.raises(migrate_0_5.MoveError, match="is not one this user may write"):
                migrate_0_5.run(root)
            assert tree_of(root) == before
        finally:
            self._open(root)

    def test_one_that_holds_only_what_no_record_names_does_not_stop_it(self, work):
        root = empty_store(work)
        put(root, "acme+p", C0, "_data/nobody.bin", b"nobody names this")
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        self._locked(root / "pipelines" / "acme+p" / C0 / "_data")
        self._locked(root / "pipelines" / "acme+p" / C0)
        try:
            assert run_or_stopped_before(root)
            assert (root / ASIDE / "pipelines" / "acme+p" / C0 / "_data" / "nobody.bin").is_file() and fresh(root).verify() == []
        finally:
            self._open(root)


class TestAFolderWithNoRecordNamedForASnapshotWhoseRecordIsElsewhere:
    """N6. Its record is not to be waited for: it is in the store, in another folder."""

    def _only_in_the_second(self, root):
        """R has its files and no record (a sync brought the record under the second name only); another snapshot keeps a file in R."""
        r = folder_of("2025-10-01", "a")
        put(root, "acme+p", r, "_data/a.parquet", A)
        put(root, "acme+p", r, "_data/b.parquet", B)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        r2 = second_folder(root, "acme+p", r)
        (root / "pipelines" / "acme+p" / r / "_chartbook" / "snapshot.json").unlink()
        newest = record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, r, None)])
        return r, r2, newest

    def test_the_two_lines_that_name_the_folder_and_its_second_say_they_are_one_snapshot(self, store):
        """The folder was named in one line ("wait for its record") and its record, which is in the store, in another ("run that pipeline again")."""
        r, r2, newest = self._only_in_the_second(store)
        found = migrate_0_5.plan(store)
        assert found.second_folders == [("acme+p", r, 2, r2)] and found.no_record == [] and found.set_aside == [("acme+p", r2)]
        dry, said = typed("store", "migrate", "--dry-run")
        assert (
            f"  1 folder(s) hold files and no record, and are named for a snapshot whose record is in another folder: acme+p/{r} "
            f"(2 file(s); its record is in {r2}). The files in such a folder that a record names are moved with that record, "
            f"and the rest goes aside."
        ) in said
        assert f"1 snapshot(s) go aside without being moved in: acme+p/{r2}. Run that pipeline again with this ChartBook." in said
        assert WAIT not in said and "have no record" not in said

    def test_it_is_named_to_be_made_again_and_the_other_snapshot_has_its_file(self, store):
        r, r2, newest = self._only_in_the_second(store)
        before = contents(store)
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and fresh(store).verify() == []
        assert f"1 snapshot(s) went aside without being moved in: acme+p/{r2}. Run that pipeline again with this ChartBook." in said
        assert f"1 folder(s) held files and no record, and were named for a snapshot whose record was in another folder: acme+p/{r} (2 file(s); its record was in {r2})." in said
        assert read_through(store) == {("acme/p", newest, "_data/a.parquet"): sha(A)}
        after = contents(store)
        assert [paths for key, paths in before.items() if key not in after and "store.json" not in paths] == []

    def test_one_named_for_no_snapshot_the_store_has_is_still_said_with_what_to_wait_for(self, store):
        put(store, "acme+p", C0, "_data/k.parquet", K)
        record(store, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        found = migrate_0_5.plan(store)
        assert found.no_record == [("acme+p", C0, 1)] and found.second_folders == []
        dry, said = typed("store", "migrate", "--dry-run")
        assert f"1 folder(s) hold files and have no record: acme+p/{C0} (1 file(s))." in said and WAIT in said

    def test_a_move_cut_short_names_it_with_the_files_it_held_at_first(self, store):
        r, r2, newest = self._only_in_the_second(store)
        steps = migrate_0_5.plan(store).steps
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=stop_after(max(number for number, step in enumerate(steps, 1) if step.op == "rename")))
        store_module._read_records.clear()
        assert migrate_0_5.plan(store).second_folders == [("acme+p", r, 1, r2)]  # one of its two is moved in by now
        assert migrate_0_5.run(store).second_folders == [("acme+p", r, 2, r2)]


class TestOnAMovedStoreASecondRecordComesWithTheFileItsSnapshotLacks:
    """N7. A store is moved with a file of its newest snapshot missing, and says so. Then the machine that had the file all along, and was not brought the move, syncs its ``pipelines/``: the record again, and the file."""

    def _moved_and_then(self, root, work, with_record: bool):
        s = folder_of("2025-11-01", "b")
        put(root, "acme+p", s, "_data/a.parquet", A)
        record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        was = work / "was"
        shutil.copytree(root, was)
        first, said = typed("store", "migrate", "--yes")
        assert first.exit_code == 0 and f"1 file(s) that a record names are missing or of another size, as before the move, in 1 snapshot(s):     acme+p/{s}: 1 of 2 file(s)     the first: _data/b.parquet " in said
        store_module._read_records.clear()
        put(root, "acme+p", s, "_data/b.parquet", B)  # the file the snapshot lacks, at the place its record of 0.5 says
        if with_record:
            shutil.copytree(was / "pipelines" / "acme+p" / s / "_chartbook", root / "pipelines" / "acme+p" / s / "_chartbook")
            put(root, "acme+p", s, "_data/a.parquet", A)  # and the one it has
        return s

    def test_alone_the_file_is_said_to_have_arrived_for_a_snapshot_that_is_moved(self, store, work):
        s = self._moved_and_then(store, work, with_record=False)
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0
        assert f"1 file(s) arrived for a snapshot that is moved already, and went aside: {ASIDE}/pipelines (2)/acme+p/{s}/_data/b.parquet." in said

    def test_with_its_record_beside_it_the_file_is_still_said(self, store, work):
        s = self._moved_and_then(store, work, with_record=True)
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0 and f"1 second record(s) of a snapshot that was moved in went aside: acme+p/{s}." in said
        assert (store / ASIDE / "pipelines (2)" / "acme+p" / s / "_data" / "b.parquet").read_bytes() == B
        assert read_through(store)[("acme/p", s, "_data/b.parquet")] == "FileNotFoundError"  # the snapshot still lacks it
        # The one its snapshot lacks is said as any late file is; the one it has is not
        assert (
            f"1 file(s) arrived for a snapshot that is moved already, and went aside: {ASIDE}/pipelines (2)/acme+p/{s}/_data/b.parquet. "
            f"`chartbook store verify` names the snapshot that lacks each."
        ) in said
        assert "a.parquet" not in said


class TestOnceTheOldFolderIsAsideTheStoreIsMoved:
    """N8. A run cut short between the last rename and ``store.json`` has moved all it was to move: what a sync then brings under ``pipelines/`` goes aside, as on any moved store."""

    def _arrives(self, made_by=""):
        def arrive(root):
            # The folder's own record, whose files other records name in it
            record(root, "acme/p", "2025-09-01", "h", [("_data/k9.parquet", K, None, None), ("_data/g9.parquet", G, None, None)], made_by=made_by)
        return arrive

    def _store(self, root):
        """The folder with no record holds k9 and g9; the newest names k9 in it, and an older snapshot g9."""
        put(root, "acme+p", C0, "_data/k9.parquet", K)
        put(root, "acme+p", C0, "_data/g9.parquet", G)
        s1 = record(root, "acme/p", "2025-10-01", "a", [("_data/g9.parquet", G, C0, None)])
        s3 = record(root, "acme/p", "2025-12-01", "c", [("_data/k9.parquet", K, C0, None)])
        store_module._read_records.clear()
        return s1, s3

    def _ended(self, work, made_by, last_step: bool):
        """Each store a move ends in, cut short and gone on with once the record has arrived: after every step but the last; or after the last (the old folder is aside, and ``store.json`` does not say the new layout yet)."""
        root = empty_store(work)
        s1, s3 = self._store(root)
        with_it = work / "with-it"
        shutil.copytree(root, with_it)
        self._arrives(made_by)(with_it)
        before = facts_before(with_it)
        assert all(at_place for _, at_place, _ in before.values()) and len(before) == 4
        steps = len(migrate_0_5.plan(root).steps)
        numbers = [steps] if last_step else [number for number in range(1, steps + 2) if number != steps]
        return before, stopped_then(root, work, self._arrives(made_by), numbers=numbers)

    @pytest.mark.parametrize("made_by", ["", "pin"], ids=["its owner's", "a pin's"])
    def test_once_the_old_folder_is_aside_it_goes_aside_as_the_line_at_the_question_says(self, work, made_by):
        """It was moved in instead, alone, and its files were said missing "as before the move": they are in the other snapshots, which took them."""
        before, ended = self._ended(work, made_by, last_step=True)
        assert len(ended) == 2
        for number, journal, root in ended:
            assert {folder for _, folder, _ in read_through(root)} == {folder for _, folder, _ in before} - {C0}, journal
            assert fresh(root).verify() == [] and migrate_0_5.marker_of(root) == "chartbook/store/v3"
            assert (root / ASIDE / "pipelines (2)" / "acme+p" / C0 / "_chartbook" / "snapshot.json").is_file() and not (root / "pipelines").exists()
            rmtree(root)

    def test_and_the_lines_name_it_to_be_made_again(self, store, work):
        s1, s3 = self._store(store)
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=stop_after(len(migrate_0_5.plan(store).steps)))
        (store / migrate_0_5.JOURNAL).unlink()
        assert migrate_0_5.is_moved(store) and migrate_0_5.marker_of(store) == "chartbook/store/v2"
        self._arrives()(store)
        store_module._read_records.clear()
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0, said
        assert "was cut short at its end, its old folder aside already: it is finished now. What ChartBook 0.5 keeps at a store's top is there again (pipelines/)" in said
        assert f"1 snapshot(s) went aside without being moved in: acme+p/{C0}. Run that pipeline again with this ChartBook." in said
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0 and "nothing to move" in said

    @pytest.mark.parametrize("made_by", ["", "pin"], ids=["its owner's", "a pin's"])
    def test_after_a_run_cut_short_at_any_step_before_it_the_snapshot_that_arrived_is_whole_with_the_others(self, work, made_by):
        before, ended = self._ended(work, made_by, last_step=False)
        wrong = []
        for number, journal, root in ended:
            lost, not_taken = worse_after(before, root)
            moved_in = {folder for _, folder, _ in read_through(root)}
            if C0 not in moved_in:
                # Not moved in: it arrived once the marker was written. Then it is said
                if (root / "pipelines").exists() or not list((root / ASIDE).glob(f"pipelines*/acme+p/{C0}/_chartbook/snapshot.json")):
                    wrong.append((number, journal, "its record is neither moved in nor aside"))
                lost = [key for key in lost if key[1] != C0]
            if lost or fresh(root).verify():
                wrong.append((number, journal, "not whole", lost, [problem.format() for problem in fresh(root).verify()][:2]))
            rmtree(root)
        assert not wrong, json.dumps(wrong[:6], indent=1)

    def test_with_nothing_come_since_the_command_says_the_move_is_finished_and_writes_the_marker(self, store):
        s1, s3 = self._store(store)
        whole = migrate_0_5.plan(store)
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=stop_after(len(whole.steps)))
        (store / migrate_0_5.JOURNAL).unlink()
        store_module._read_records.clear()
        assert migrate_0_5.plan(store).steps == [] and migrate_0_5.to_move(store)
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and "was cut short at its end, its old folder aside already: it is finished now." in said
        assert "What ChartBook 0.5 keeps" not in said and migrate_0_5.marker_of(store) == "chartbook/store/v3"
        assert f"has this version's layout: 1 pipeline(s), 2 snapshot(s)." in said and fresh(store).verify() == []
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0 and "nothing to move" in said

    def test_a_desktops_file_where_the_old_folder_goes_does_not_make_a_store_a_moved_one(self, work):
        root = empty_store(work)
        self._store(root)
        (root / ASIDE / "pipelines").mkdir(parents=True)
        (root / ASIDE / "pipelines" / ".DS_Store").write_bytes(b"\x00Bud1")
        assert not migrate_0_5.is_moved(root) and migrate_0_5.plan(root).snapshots == 2


class TestAFolderThatIsNoPipelines:
    """N9. A sync's second copy of a pipeline's whole folder, ``acme+p 2``: 0.5 read no record in it (a record in another pipeline's folder is not read), and it stopped the move, once for each snapshot in it."""

    def test_it_does_not_stop_the_move_any_more_than_a_second_copy_of_a_snapshots_folder_does(self, store):
        r = folder_of("2025-11-01", "b")
        put(store, "acme+p", r, "_data/a.parquet", A)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None)])
        shutil.copytree(store / "pipelines" / "acme+p", store / "pipelines" / "acme+p 2")
        store_module._read_records.clear()
        # The store reads as one pipeline of one snapshot: the record in the second folder is not one it reads
        assert [(kept.folder.parent.name, kept.folder.name) for kept in fresh(store).records() if kept.readable] == [("acme+p", r)]
        found = migrate_0_5.plan(store)
        assert found.not_pipelines == ["acme+p 2"] and found.second == [("acme+p 2", r)] and (found.pipelines, found.snapshots) == (1, 1)
        dry, said = typed("store", "migrate", "--dry-run")
        line = "  1 folder(s) under pipelines/ {are} named as no pipeline's folder is, and {go} aside whole with it: acme+p 2. ChartBook 0.5 read no record in such a folder, and nothing in it {isw} moved in."
        assert dry.exit_code == 0 and line.format(are="are", go="go", isw="is") in said
        assert f"1 second record(s) of a snapshot that is moved in go aside: acme+p 2/{r}." in said
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and line.format(are="were", go="went", isw="was") in said
        assert read_through(store) == {("acme/p", r, "_data/a.parquet"): sha(A)}
        assert (store / ASIDE / "pipelines" / "acme+p 2" / r / "_data" / "a.parquet").read_bytes() == A

    def test_a_snapshot_whose_only_record_is_in_such_a_folder_is_named_to_be_made_again(self, store):
        r = folder_of("2025-11-01", "b")
        put(store, "acme+p", r, "_data/a.parquet", A)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None)])
        other = record(store, "acme/p", "2025-12-01", "c", [("_data/c.parquet", C, None, None)])
        put(store, "acme+p", other, "_data/c.parquet", C)
        (store / "pipelines" / "acme+p 2").mkdir()
        os.replace(store / "pipelines" / "acme+p" / other, store / "pipelines" / "acme+p 2" / other)  # the only record of it
        found = migrate_0_5.plan(store)
        assert found.not_pipelines == ["acme+p 2"] and found.set_aside == [("acme+p 2", other)] and found.second == []
        done = migrate_0_5.run(store)
        assert done.set_aside == [("acme+p 2", other)] and done.not_pipelines == ["acme+p 2"]

    @pytest.mark.parametrize("name,is_one", [
        ("acme+p", True), ("rates", True), ("acme+p~1a2b3c4d", True), ("a.b-c_d+e.f", True),
        ("acme+p 2", False), ("acme+p+q", False), ("acme+p~xyz", False), ("acme p", False), ("acme+p (1)", False), ("café+p", False),
    ])
    def test_what_is_named_as_a_pipelines_folder(self, name, is_one):
        assert bool(migrate_0_5._is_pipeline_folder(name)) is is_one

    @pytest.mark.skipif(os.name == "nt", reason="a link needs a privilege on Windows")
    def test_the_line_about_a_link_says_to_put_the_folder_itself_where_the_link_is(self, store, work):
        """The snapshot folder that keeps a file of the newest is a link to a folder on another disk (a person made room). 0.5 read through it. The line said to move the link out, "a file a record names through it is then missing, as it would have been": it was not missing."""
        elsewhere = work / "another-disk" / C0
        (elsewhere / "_data").mkdir(parents=True)
        (elsewhere / "_data" / "k.parquet").write_bytes(K)
        (store / "pipelines" / "acme+p").mkdir(parents=True)
        link = store / "pipelines" / "acme+p" / C0
        os.symlink(elsewhere, link)
        s = record(store, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, C0, None)])
        assert read_through(store) == {("acme/p", s, "_data/k.parquet"): sha(K)}  # whole, to 0.5
        stopped, said = typed("store", "migrate", "--yes")
        assert stopped.exit_code == 1 and (
            f"{link} is a link to another place, and a move does not follow one: the store is not moved. If a sync is still "
            f"bringing what it stands for, wait. If it leads to a folder of the store that is kept elsewhere (ChartBook 0.5 read "
            f"through such a link), put that folder itself where the link is, and run this again: the files in it that a record "
            f"names are then moved with the rest."
        ) in said
        assert "move the link out" not in said and "is then missing" not in said
        # As told
        os.unlink(link)
        shutil.move(str(elsewhere), str(link))
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and read_through(store) == {("acme/p", s, "_data/k.parquet"): sha(K)}


class TestTheCountOfFilesTakenFromAnotherSnapshot:
    """N10."""

    def test_a_file_of_an_older_snapshot_that_was_not_where_its_record_says_is_counted_too(self, store):
        """The older snapshot says K is in the folder with no record, where it is not; the newest has it. After the move the older one reads it from the newest: it is one of the files "not where their record says"."""
        s3 = folder_of("2025-12-01", "c")
        put(store, "acme+p", s3, "_data/k.parquet", K)
        s1 = record(store, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, C0, None)])
        record(store, "acme/p", "2025-12-01", "c", [("_data/k.parquet", K, None, None)])
        before = facts_before(store)
        assert before[("acme/p", s1, "_data/k.parquet")][1:] == (False, True)
        found = migrate_0_5.plan(store)
        assert found.elsewhere == 1 and found.elsewhere_first == [(s1, "_data/k.parquet")]
        dry, said = typed("store", "migrate", "--dry-run")
        assert f"  1 file(s) are not where their record says, and are taken from where another snapshot of their pipeline keeps the same bytes: _data/k.parquet ({s1})." in said
        done = migrate_0_5.run(store)
        assert worse_after(before, store) == ([], []) and done.missing == [] and done.elsewhere == 1

    def test_one_that_was_where_its_record_says_is_not_counted_once_the_move_has_taken_it(self, work):
        """The count is the first plan's: a later plan finds a place the move has emptied, and cannot tell it from one that was empty."""
        root = empty_store(work)
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/k.parquet", K)
        record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None)])
        s2 = record(root, "acme/p", "2025-10-15", "b", [("_data/k.parquet", K, s1, None)])
        s3 = record(root, "acme/p", "2025-12-01", "c", [("_data/k.parquet", K, C0, None)])  # the newest: not where it says, and takes s1's
        assert migrate_0_5.plan(root).elsewhere == 1
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=stop_after(1))
        store_module._read_records.clear()
        assert (root / "snapshots" / "acme+p" / s3 / "_data" / "k.parquet").is_file() and migrate_0_5.plan(root).elsewhere == 0
        assert migrate_0_5.run(root).elsewhere == 1


class TestASecondRecordIsNotAskedWhereBytesAre:
    """N12. ChartBook 0.5 never read a record in a folder ``<name> 2``, so the move reads what 0.5 read. What is true of it: the file is said missing, the bytes are aside, untouched, and the last line says to look there."""

    LOOK = "it may be removed once the move has been checked. 1 file(s) are missing, and one may be in that folder (in a second copy of its snapshot's folder, as a sync names one: `<name> 2`): look there first."

    def _split(self, root):
        """R keeps a.parquet and b.parquet in its own folder. A sync left a.parquet in R, and b.parquet in ``R 2`` alone, with the same record in each."""
        r = folder_of("2025-11-01", "b")
        put(root, "acme+p", r, "_data/a.parquet", A)
        record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        r2 = second_folder(root, "acme+p", r)
        put(root, "acme+p", r2, "_data/b.parquet", B)
        return r, r2

    def test_a_file_that_only_the_second_folder_holds_is_said_missing_and_its_bytes_are_aside_untouched(self, store):
        r, r2 = self._split(store)
        done = migrate_0_5.run(store)
        reads = read_through(store)
        assert reads == {("acme/p", r, "_data/a.parquet"): sha(A), ("acme/p", r, "_data/b.parquet"): "FileNotFoundError"}
        assert done.missing == [(r, "_data/b.parquet")] and done.second == [("acme+p", r2)]
        assert (store / ASIDE / "pipelines" / "acme+p" / r2 / "_data" / "b.parquet").read_bytes() == B

    def test_the_last_line_says_to_look_in_what_went_aside(self, store):
        r, r2 = self._split(store)
        dry, _ = typed("store", "migrate", "--dry-run")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0
        assert f"1 file(s) that a record names are missing or of another size, as before the move, in 1 snapshot(s):     acme+p/{r}: 1 of 2 file(s)     the first: _data/b.parquet " in said
        assert f"1 second record(s) of a snapshot that was moved in went aside: acme+p/{r2}." in said
        assert f"The old folder, with its records, is kept at {ASIDE}/pipelines: {self.LOOK}" in said
        assert (store / ASIDE / "pipelines" / "acme+p" / r2 / "_data" / "b.parquet").read_bytes() == B

    def test_a_file_the_second_record_says_is_in_a_folder_with_no_record_is_said_missing_and_is_aside(self, store):
        """The real store's shape, but that B's record has not come either: R's record says A keeps the file, where it is not; ``R 2``'s says B keeps it, where it is."""
        a, b = folder_of("2025-10-01", "a"), folder_of("2025-10-02", "c")
        put(store, "acme+p", a, "_data/other.parquet", C)  # A: files and no record, and not the file
        put(store, "acme+p", b, "_data/a.parquet", A)  # B: files and no record, and the file
        r = folder_of("2025-11-01", "b")
        put(store, "acme+p", r, "_data/b.parquet", B)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, a, None), ("_data/b.parquet", B, None, None)])
        r2 = second_folder(store, "acme+p", r, lambda text: text.replace(f'"kept_in": "{a}"', f'"kept_in": "{b}"'))
        found = migrate_0_5.plan(store)
        assert found.second == [("acme+p", r2)] and found.set_aside == [] and found.missing == [(r, "_data/a.parquet")]
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and read_through(store)[("acme/p", r, "_data/a.parquet")] == "FileNotFoundError"
        assert (store / ASIDE / "pipelines" / "acme+p" / b / "_data" / "a.parquet").read_bytes() == A  # the bytes, aside
        assert f"The old folder, with its records, is kept at {ASIDE}/pipelines: {self.LOOK}" in said

    def test_with_nothing_missing_the_last_line_is_as_it_was(self, store):
        r = folder_of("2025-11-01", "b")
        put(store, "acme+p", r, "_data/a.parquet", A)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None)])
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and result.output.splitlines()[-2] == f"The old folder, with its records, is kept at {ASIDE}/pipelines: it may be removed once the move has been checked."

    def test_one_made_by_another_is_said_as_the_first_is(self, store):
        """The same snapshot, the copy marked as a pin's: a second record."""
        r = folder_of("2025-11-01", "b")
        put(store, "acme+p", r, "_data/a.parquet", A)
        record(store, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None)])
        r2 = second_folder(store, "acme+p", r, lambda text: text.replace('"records"', '"made_by": "pin", "records"'))
        found = migrate_0_5.plan(store)
        assert found.second == [("acme+p", r2)] and found.set_aside == []
        done = migrate_0_5.run(store)
        assert done.second == [("acme+p", r2)] and done.by_pins == 0 and fresh(store).verify() == []


class TestAFileArrivesAtThePlaceItsRecordSays:
    """What a sync brings while a move is under way, now that a plan looks up where a file is (sound at the review; kept)."""

    def _taken_from_another(self, root):
        """The newest (s3) and a pin's (p4) say K is in the folder with no record, where it is not; two older snapshots each have it in their own folder."""
        put(root, "acme+p", C0, "_data/nobody.bin", b"nobody names this")
        s1, s2 = folder_of("2025-10-01", "a"), folder_of("2025-11-01", "b")
        put(root, "acme+p", s1, "_data/k.parquet", K)
        put(root, "acme+p", s1, "_data/g.parquet", G)
        record(root, "acme/p", "2025-10-01", "a", [("_data/k.parquet", K, None, None), ("_data/g.parquet", G, None, None)])
        put(root, "acme+p", s2, "_data/k.parquet", K)
        record(root, "acme/p", "2025-11-01", "b", [("_data/k.parquet", K, None, None)])
        record(root, "acme/p", "2025-12-01", "c", [("_data/k.parquet", K, C0, None)])
        record(root, "acme/p", "2025-12-15", "d", [("_data/k.parquet", K, C0, None)], made_by="pin")
        store_module._read_records.clear()

    def _in_the_trees(self, root) -> dict:
        return {path: value for path, value in tree_of(root).items() if path.startswith(("snapshots/", "increments/"))}

    def _moved_with_it(self, root, work):
        with_it = work / "with-it"
        shutil.copytree(root, with_it)
        put(with_it, "acme+p", C0, "_data/k.parquet", K)
        before = facts_before(with_it)
        store_module._read_records.clear()
        migrate_0_5.run(with_it)
        return before, self._in_the_trees(with_it)

    def test_between_the_plan_and_its_step_every_snapshot_is_whole_and_the_trees_are_those_of_a_move_that_found_it_there(self, work, monkeypatch):
        root = empty_store(work)
        self._taken_from_another(root)
        before, moved_whole = self._moved_with_it(root, work)
        check = migrate_0_5.check

        def then_it_arrives(of, found):
            check(of, found)
            put(of, "acme+p", C0, "_data/k.parquet", K)  # the plan is made, and no step is

        monkeypatch.setattr(migrate_0_5, "check", then_it_arrives)
        held = contents(root)
        done = migrate_0_5.run(root)
        assert worse_after(before, root) == ([], []) and fresh(root).verify() == [] and done.missing == []
        assert self._in_the_trees(root) == moved_whole
        assert (root / ASIDE / "pipelines" / "acme+p" / C0 / "_data" / "k.parquet").read_bytes() == K  # the file that arrived is aside
        after = contents(root)
        assert [paths for key, paths in held.items() if key not in after and not any(path in OWN for path in paths)] == []

    def test_after_a_run_cut_short_at_any_step_the_trees_are_those_of_a_move_that_found_it_there(self, work):
        root = empty_store(work)
        self._taken_from_another(root)
        before, moved_whole = self._moved_with_it(root, work)
        wrong = []
        for number, journal, ended in stopped_then(root, work, lambda of: put(of, "acme+p", C0, "_data/k.parquet", K)):
            lost, not_taken = worse_after(before, ended)
            if lost or not_taken or fresh(ended).verify():
                wrong.append((number, journal, "not whole", lost, not_taken))
            elif self._in_the_trees(ended) != moved_whole:
                wrong.append((number, journal, sorted(set(self._in_the_trees(ended).items()) ^ set(moved_whole.items()))[:6]))
            rmtree(ended)
        assert not wrong, json.dumps(wrong[:6], indent=1)


#: The stores drawn more widely (``tests/found_store_of_0_5.py::wide_store``), by their seeds. The review ran the
#: first 120 through the two tests below, and 200 to 299 stopped twice, and all passed; so do they with this round's
#: rules (2026-11-20). Eight are kept for each.
WIDE_SEEDS = (0, 1, 2, 3, 4, 5, 6, 7)


class TestAnyStoreDrawnWide:
    """A file of no bytes, two files of one size, a file longer than its record says, a record that names a later snapshot's folder, a folder ``store gc`` cleared, a second pipeline with the same names and bytes: no move makes anything worse, and stopped anywhere it ends in the same tree."""

    @pytest.mark.parametrize("pipelines", [1, 2])
    @pytest.mark.parametrize("seed", WIDE_SEEDS)
    def test_a_move_makes_nothing_worse_takes_what_a_record_of_the_pipeline_holds_and_counts_what_went_aside(self, work, seed, pipelines, monkeypatch):
        root = empty_store(work)
        wide_store(root, seed, pipelines)
        before, held = facts_before(root), contents(root)
        said = set()  # every place a record says a file is
        for file in sorted(root.glob("pipelines/*/*/_chartbook/snapshot.json")):
            for part in json.loads(file.read_text(encoding="utf-8"))["records"]:
                for entry in part["stored"]["files"]:
                    said.add(f"pipelines/{file.parent.parent.parent.name}/{entry.get('kept_in', file.parent.parent.name)}/{entry.get('kept_as', entry['path'])}")
        planned = migrate_0_5.plan(root)
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            done = migrate_0_5.run(root)
        lost, not_taken = worse_after(before, root)
        assert lost == [], f"at their stated place before, and not read now: {lost}"
        assert not_taken == [], f"held at a place a record of the pipeline names, and not read now: {not_taken}"
        # Nothing but its own is removed or written over, and every run of bytes is still somewhere
        assert not_its_own(gone) == []
        after = contents(root)
        assert [paths for key, paths in held.items() if key not in after and not any(path in OWN for path in paths)] == []
        # What is said missing is what no record's place held, before and after
        missing = {(snapshot, path) for (_, snapshot, path), (_, _, anywhere) in before.items() if not anywhere}
        if pipelines == 1:
            assert set(planned.missing) == missing and set(done.missing) == missing
        assert (planned.elsewhere, planned.doubled, planned.aside) == (done.elsewhere, done.doubled, done.aside)
        assert len(fresh(root).verify()) == len({key for key, (_, _, anywhere) in before.items() if not anywhere})
        # Of the files aside, those at a place a record named are the "second copies", and the rest the files "no record names"
        aside = [path.relative_to(root / ASIDE).as_posix() for path in (root / ASIDE).rglob("*") if path.is_file() and path.name not in ("snapshot.json", "CLEARED.txt", "README.txt")]
        named = [path for path in aside if path in said]
        assert (done.doubled, done.aside) == (len(named), len(aside) - len(named))
        moved_in = [path for tree in ("snapshots", "increments") for path in (root / tree).rglob("*") if path.is_file() and "_chartbook" not in path.parts and path.name != "README.txt"]
        assert planned.renamed + planned.copied == len(moved_in) == done.renamed + done.copied

    @pytest.mark.parametrize("seed", WIDE_SEEDS)
    def test_stopped_after_any_step_and_stopped_twice_it_ends_in_the_same_tree(self, work, seed):
        import random

        root = empty_store(work)
        wide_store(root, seed, 2)
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        wanted, reads = tree_of(whole), read_through(whole)
        drawn = random.Random(seed)
        store_module._read_records.clear()
        steps = len(migrate_0_5.plan(root).steps)
        wrong = []
        for first in range(1, steps + 2):
            for journal in (True, False):
                cut = work / "cut"
                shutil.copytree(root, cut)
                store_module._read_records.clear()
                with pytest.raises(Stop):
                    migrate_0_5.run(cut, after_step=stop_after(first))
                if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                    (cut / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                second = None
                if drawn.random() < 0.3:
                    second = drawn.randint(1, max(1, len(migrate_0_5.plan(cut).steps)))
                    with pytest.raises(Stop):
                        migrate_0_5.run(cut, after_step=stop_after(second))
                    if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                        (cut / migrate_0_5.JOURNAL).unlink()
                    store_module._read_records.clear()
                migrate_0_5.run(cut)
                if tree_of(cut) != wanted:
                    wrong.append((first, second, journal, sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
                elif read_through(cut) != reads:
                    wrong.append((first, second, journal, "reads differ"))
                rmtree(cut)
        assert not wrong, json.dumps(wrong[:4], indent=1)

    @pytest.mark.parametrize("seed", WIDE_SEEDS)
    def test_taken_over_with_any_of_its_renames_and_copies_done_it_ends_in_the_same_tree(self, work, seed):
        """A move begun on another machine and taken over here, as ``check`` says it may be: a sync has brought some of that machine's steps and not others, in no order."""
        import random

        root = empty_store(work)
        wide_store(root, seed, 1)
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        wanted, reads = tree_of(whole), read_through(whole)
        drawn = random.Random(seed)
        store_module._read_records.clear()
        steps = [step for step in migrate_0_5.plan(root).steps if step.op in ("rename", "copy")]
        wrong = []
        for _ in range(6):
            cut = work / "cut"
            shutil.copytree(root, cut)
            done = [step for step in steps if drawn.random() < 0.5]
            for step in done:
                migrate_0_5._do(cut, step)
            store_module._read_records.clear()
            migrate_0_5.run(cut)
            if tree_of(cut) != wanted:
                wrong.append(([(step.op, step.source, step.target) for step in done], sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
            elif read_through(cut) != reads:
                wrong.append(([(step.op, step.source, step.target) for step in done], "reads differ"))
            rmtree(cut)
        assert not wrong, json.dumps(wrong[:2], indent=1)

    @pytest.mark.parametrize("seed", WIDE_SEEDS)
    def test_cut_short_and_then_all_that_a_sync_was_bringing_arrives_nothing_that_read_before_is_lost(self, work, seed):
        """A move is cut short, and then every place a record names holds its file whole (the sync finished)."""
        import random

        root = empty_store(work)
        wide_store(root, seed)
        before, held = facts_before(root), contents(root)
        entries = []
        for file in sorted(root.glob("pipelines/*/*/_chartbook/snapshot.json")):
            for part in json.loads(file.read_text(encoding="utf-8"))["records"]:
                for entry in part["stored"]["files"]:
                    entries.append((file.parent.parent.name, entry))
        by_hash = {"sha256:" + sha(data): data for data in WIDE.values()}

        def the_sync_finishes(of):
            for snapshot, entry in entries:
                place = of / "pipelines" / "acme+p" / entry.get("kept_in", snapshot) / entry.get("kept_as", entry["path"])
                if not (of / "pipelines").is_dir():
                    continue
                if os.path.lexists(place) and place.stat().st_size != entry["size_bytes"]:
                    os.chmod(place, 0o644)  # part of it, or more: the sync brings the file itself
                    place.write_bytes(by_hash[entry["content_hash"]])
                elif not os.path.lexists(place):
                    place.parent.mkdir(parents=True, exist_ok=True)
                    place.write_bytes(by_hash[entry["content_hash"]])

        drawn = random.Random(seed)
        steps = len(migrate_0_5.plan(root).steps)
        wrong = []
        for number, journal, ended in stopped_then(root, work, the_sync_finishes, numbers=sorted({drawn.randint(1, steps) for _ in range(6)})):
            lost, not_taken = worse_after(before, ended)
            after = contents(ended)
            # Of the whole files only: a part of one is written over by the sync that brings the file, in this test's own hand
            gone = [paths for key, paths in held.items() if "sha256:" + key in by_hash and key not in after]
            if lost or not_taken or gone:
                wrong.append((number, journal, lost, not_taken, gone))
            rmtree(ended)
        assert not wrong, json.dumps(wrong[:4], indent=1)


class TestWhereTheCopiesGoAndWhatTheStoreWillTake:
    """N13. On a real store 17,612 files (30.6 GB) were copied and the store went from 42.9 GB to 74 GB: five older snapshots shared with each other what the newest did not have, and each increment holds its own copy of what the snapshot it builds on lacks. That is the layout's price. What was wrong is that one line said it, with nothing a person could act on before saying yes."""

    ADVICE = "  A snapshot that is removed before the move is not copied: `chartbook store gc` of ChartBook 0.5 removes old ones (this version removes nothing from a store of 0.5)."
    UPLOADED = "are copied: each is in two folders that must each hold it. In a synced folder every copied byte is uploaded again."

    def _two_older_share_a_file_the_newest_lacks(self, root, shared: bytes = b"s" * 5000, new: bytes = b"n" * 3000):
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/shared.parquet", shared)
        record(root, "acme/p", "2025-10-01", "a", [("_data/shared.parquet", shared, None, None)])
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/shared.parquet", shared, s1, None)])
        s3 = folder_of("2025-12-01", "c")
        put(root, "acme+p", s3, "_data/new.parquet", new)
        record(root, "acme/p", "2025-12-01", "c", [("_data/new.parquet", new, None, None)])
        return s1, s2, s3

    def _size(self, number: int) -> str:
        from chartbook.cli import _format_bytes

        return _format_bytes(number)

    def test_the_dry_run_says_what_the_store_will_take_and_which_snapshots_are_given_the_copies(self, store):
        s1, s2, s3 = self._two_older_share_a_file_the_newest_lacks(store)
        takes = sum(path.stat().st_size for path in store.rglob("*") if path.is_file())
        found = migrate_0_5.plan(store)
        assert (found.copied, found.copied_bytes, found.copied_into) == (1, 5000, [("acme+p", s2, 1, 5000)])
        assert (found.store_bytes, found.store_after) == (takes, takes + 5000)
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        print(dry.output)
        assert said[2].endswith("moved inside the store by rename: nothing is copied or uploaded again for these.")
        assert said[3:7] == [
            f"  1 file(s), 4.9 KB, {self.UPLOADED}",
            f"  The store takes {self._size(takes)} now, and will take {self._size(takes + 5000)}. The copies go to 1 snapshot(s), the largest first:",
            f"    acme+p/{s2}: 4.9 KB in 1 file(s)",
            self.ADVICE,
        ]
        # At the question too; and in the last lines what it took and takes, with nothing left to act on
        result, _ = typed("store", "migrate", "--yes")
        done = result.output.splitlines()
        assert result.exit_code == 0 and done[: len(said) - 1] == said[:-1]
        last = done[done.index(next(line for line in done if "has this version's layout" in line)):]
        assert last[3:6] == [
            "  1 file(s), 4.9 KB, were copied: each is in two folders that must each hold it. In a synced folder every copied byte is uploaded again.",
            f"  The store took {self._size(takes)} before the move, and takes {self._size(takes + 5000)} now. The copies went to 1 snapshot(s), the largest first:",
            f"    acme+p/{s2}: 4.9 KB in 1 file(s)",
        ]
        assert self.ADVICE not in last and last[6].startswith("  What is left of pipelines/ went aside whole")

    def test_what_the_line_says_to_do_is_so_a_snapshot_removed_before_the_move_is_not_copied(self, store):
        s1, s2, s3 = self._two_older_share_a_file_the_newest_lacks(store)
        rmtree(store / "pipelines" / "acme+p" / s2)  # as the `store gc` of 0.5 removes one: its record goes
        found = migrate_0_5.plan(store)
        assert (found.copied, found.copied_into, found.store_bytes) == (0, [], 0)  # and the store's size is not asked for
        dry, said = typed("store", "migrate", "--dry-run")
        assert dry.output.splitlines()[3] == "  0 file(s), 0 bytes, are copied: each is in two folders that must each hold it." and "The store takes" not in said

    def test_where_little_is_copied_one_line_says_it(self, store):
        """Under a hundredth of the store, and under 100 MB: the line as it was, and that it is uploaded again."""
        self._two_older_share_a_file_the_newest_lacks(store, shared=b"s" * 10, new=b"n" * 200_000)
        dry, said = typed("store", "migrate", "--dry-run")
        assert dry.output.splitlines()[3] == f"  1 file(s), 10 bytes, {self.UPLOADED}"
        assert dry.output.splitlines()[4].startswith("  What is left of pipelines/") and "The store takes" not in said and self.ADVICE.strip() not in said

    def test_a_hundred_megabytes_is_much_in_a_store_of_any_size(self, store, monkeypatch):
        """Under a hundredth of a store of 40 GB, and 150 MB to upload again: said in full. (The plan is made up: no test writes 40 GB.)"""
        self._two_older_share_a_file_the_newest_lacks(store)
        real = migrate_0_5.plan

        def large(root):
            found = real(root)
            found.copied, found.copied_bytes = 7, 150 * 1024 ** 2
            found.store_bytes, found.store_after = 40 * 1024 ** 3, 40 * 1024 ** 3 + 150 * 1024 ** 2
            found.copied_into = [("acme+p", folder_of(f"2025-0{number}-01", "abcdefg"[number]), 1, (7 - number) * 20 * 1024 ** 2) for number in range(1, 7)] + [("acme+q", "x", 1, 1)]
            return found

        monkeypatch.setattr(migrate_0_5, "plan", large)
        monkeypatch.setattr(migrate_0_5, "check", lambda root, found: None)
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        assert said[3] == f"  7 file(s), 150.0 MB, {self.UPLOADED}"
        assert said[4] == "  The store takes 40.0 GB now, and will take 40.1 GB. The copies go to 7 snapshot(s), the largest first:"
        # The first five, and how many more
        assert said[5] == f"    acme+p/{folder_of('2025-01-01', 'b')}: 120.0 MB in 1 file(s)" and said[9].endswith(": 40.0 MB in 1 file(s)")
        assert said[10:12] == ["    and 2 more", self.ADVICE]

    def test_the_largest_are_first_and_after_five_the_rest_are_counted(self, work, monkeypatch):
        from tests.rich_store_of_0_5 import rich

        root = empty_store(work)
        rich(root)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        found = migrate_0_5.plan(root)
        assert len(found.copied_into) == 6 and [given[3] for given in found.copied_into] == sorted((given[3] for given in found.copied_into), reverse=True)
        assert sum(given[2] for given in found.copied_into) == found.copied and sum(given[3] for given in found.copied_into) == found.copied_bytes
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        at = next(index for index, line in enumerate(said) if line.startswith("  The store takes "))
        assert said[at].endswith("The copies go to 6 snapshot(s), the largest first:")
        assert [line.split(":")[0].strip() for line in said[at + 1:at + 6]] == [f"{pipeline}/{snapshot}" for pipeline, snapshot, _, _ in found.copied_into[:5]]
        assert said[at + 6:at + 8] == ["    and 1 more", self.ADVICE]

    @pytest.mark.parametrize("journal", ["kept", "deleted"])
    def test_a_move_cut_short_and_gone_on_with_says_what_the_store_took_and_takes(self, store, journal):
        s1, s2, s3 = self._two_older_share_a_file_the_newest_lacks(store)
        whole = migrate_0_5.plan(store)
        steps = whole.steps
        with pytest.raises(Stop):
            migrate_0_5.run(store, after_step=stop_after(max(number for number, step in enumerate(steps, 1) if step.op == "copy")))
        if journal == "deleted":
            (store / migrate_0_5.JOURNAL).unlink()
        store_module._read_records.clear()
        again = migrate_0_5.plan(store)
        assert again.store_after == again.store_bytes and again.copied_into == whole.copied_into  # the copy is made: nothing more to take
        done = migrate_0_5.run(store)
        assert done.copied_into == whole.copied_into and done.store_after == whole.store_after
        assert done.store_bytes == (whole.store_bytes if journal == "kept" else again.store_bytes)


class TestWhatIsMissingIsSaidFirstAndBySnapshot:
    """N14. On a real store 58,325 files that one record names were missing (an upload from another machine that never finished: whole folders absent). The dry run said so in one line among seventeen, some 200 characters wide with the names in it."""

    WAIT_FOR_THEM = (
        "  If a sync may still be bringing these files, wait for it to finish before the move: a file that arrives afterwards goes "
        "aside, and does not reach its snapshot. `chartbook store verify` lists every one."
    )
    AFTERWARDS = "  `chartbook store verify` lists every one. A file that a sync brings now goes aside when `chartbook store migrate` is run again, and does not reach its snapshot."

    def _many_missing(self, root):
        """A snapshot whose record names forty files of a dataset, of which four are there; and another that lacks one of its two."""
        s1 = folder_of("2025-10-01", "a")
        entries = []
        for number in range(40):
            data = f"part {number:03d}".encode() * 10
            path = f"_data/articles/year=2025/month=10/part-{number:05d}-0123456789abcdef0123456789abcdef0123456789abcdef.c000.snappy.parquet"
            if number >= 36:
                put(root, "acme+p", s1, path, data)
            entries.append((path, data, None, None))
        record(root, "acme/p", "2025-10-01", "a", entries)
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/a.parquet", A)
        record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", A, None, None), ("_data/b.parquet", B, None, None)])
        return s1, s2

    def test_the_dry_run_says_it_first_by_snapshot_with_three_names_that_fit_a_line(self, store):
        s1, s2 = self._many_missing(store)
        found = migrate_0_5.plan(store)
        assert len(found.missing) == 37 and found.missing_in == [("acme+p", s1, 36, 40), ("acme+p", s2, 1, 2)]
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        print(dry.output)
        assert said[0].endswith("has the layout of ChartBook 0.5: 1 pipeline(s), 2 snapshot(s).")
        name = "part-{:05d}-0123456789abcdef01234567…0123456789abcdef.c000.snappy.parquet"  # its start and its end: the name is 79 characters
        assert said[1:8] == [
            "  37 file(s) that a record names are missing or of another size, as before the move, in 2 snapshot(s):",
            f"    acme+p/{s1}: 36 of 40 file(s)",
            f"    acme+p/{s2}: 1 of 2 file(s)",
            "    the first: " + name.format(0),
            "               " + name.format(1),
            "               " + name.format(2),
            self.WAIT_FOR_THEM,
        ]
        assert "snapshot(s) become complete" in said[8]  # before the other counts
        # Each line of a snapshot or a name fits a terminal; the sentences are longer, as every sentence of the command is
        assert all(len(line) <= 88 for line in said[2:7]) and len(name.format(0)) == 72

    def test_nothing_of_it_is_a_refusal_and_the_last_lines_say_it_again(self, store):
        s1, s2 = self._many_missing(store)
        no, _ = typed("store", "migrate", "--dry-run")
        result, _ = typed("store", "migrate", "--yes")
        assert result.exit_code == 0
        done = result.output.splitlines()
        print(result.output)
        last = done[done.index(next(line for line in done if "has this version's layout" in line)):]
        assert last[1:7] == no.output.splitlines()[1:7] and last[7] == self.AFTERWARDS and "snapshot(s) became complete" in last[8]
        assert len(fresh(store).verify()) == 37  # and `store verify` lists every one

    def test_a_name_that_fits_is_whole_and_of_a_long_path_the_folders_are_cut(self, store):
        deep = "_data/" + "/".join(f"level-{number:02d}-of-a-deep-folder" for number in range(4)) + "/part-0001.parquet"
        s1 = record(store, "acme/p", "2025-10-01", "a", [("_data/short.parquet", A, None, None), (deep, B, None, None)])
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        assert said[3:5] == [
            "    the first: _data/level-00-of-a-deep-folder/level-01-of-a-deep-fo…/part-0001.parquet",
            "               _data/short.parquet",
        ]
        assert len(said[3]) - len("    the first: ") == 72

    def test_five_snapshots_are_named_and_the_rest_counted(self, store):
        """Seven snapshots a pin made, each lacking its one file: the one that lacks most would be first, and of these the first by name."""
        folders = []
        for number in range(7):
            data = bytes([65 + number]) * 50
            folders.append(record(store, "acme/p", f"2025-{number + 3:02d}-01", "abcdefg"[number], [(f"_data/k{number}.parquet", data, None, None)], made_by="pin"))
        found = migrate_0_5.plan(store)
        assert [lacks[1] for lacks in found.missing_in] == folders and all(lacks[2:] == (1, 1) for lacks in found.missing_in)
        dry, _ = typed("store", "migrate", "--dry-run")
        said = dry.output.splitlines()
        assert said[1] == "  7 file(s) that a record names are missing or of another size, as before the move, in 7 snapshot(s):"
        assert said[2:7] == [f"    acme+p/{folder}: 1 of 1 file(s)" for folder in folders[:5]] and said[7] == "    and 2 more"
        assert said[8:12] == ["    the first: _data/k0.parquet", "               _data/k1.parquet", "               _data/k2.parquet", self.WAIT_FOR_THEM]

    def test_with_nothing_missing_nothing_is_said_of_it(self, store):
        put(store, "acme+p", folder_of("2025-10-01", "a"), "_data/a.parquet", A)
        record(store, "acme/p", "2025-10-01", "a", [("_data/a.parquet", A, None, None)])
        dry, said = typed("store", "migrate", "--dry-run")
        assert "snapshot(s) become complete" in dry.output.splitlines()[1] and "are missing" not in said
