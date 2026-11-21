"""The mover on a store of the shape found in a real one (``tests/found_store_of_0_5.py``), and the four rules it gave.

A move was run on a copy of a store that a sync service keeps (2026-11-20).
The store was whole by the ``store verify`` of 0.5, and the move stopped at
a folder with files and no record, said to move that folder out, and then
called missing, "as before the move", the files that had been in it. Four
rules came of it:

1. a folder with files and no record never stops the move: it is taken as
   a cleared folder is, and counted and named;
2. a file that is not where its record says is taken from where another
   record of the pipeline has the same bytes, as 0.5 found it by its hash;
3. a record that goes aside is named as a snapshot to be made again only
   where no snapshot of its pipeline, commit and time was moved in;
4. no line of the move says to move out a folder that a record may name
   files in.
"""

import hashlib
import inspect
import json
import os
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from chartbook import config, data, lock, migrate_0_5
from chartbook import store as store_module
from chartbook.replacing import replace_when_let
from chartbook.cli import main
from tests.found_store_of_0_5 import IN_A, MADE, UNNAMED, _parts, any_store, elsewhere, found
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
TAKEN = "file(s) {are} not where their record says, and {are} taken from where another snapshot of their pipeline keeps the same bytes: under "


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def found_store(work, monkeypatch):
    """The store of the shape found, as the store of the commands typed; and its names."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return work / "store", found(work, work / "store")


@pytest.fixture
def elsewhere_store(work, monkeypatch):
    """The store written by hand with every way a file can be elsewhere; and its names."""
    root = empty_store(work)
    monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
    return root, elsewhere(root)


def typed(*words, input=None):
    result = CliRunner().invoke(main, list(words), input=input)
    assert result.exception is None or isinstance(result.exception, SystemExit), (words, repr(result.exception))
    return result, result.output.replace("\n", " ")


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def said_by_the_records(root: Path) -> dict:
    """What each record of a store of 0.5 says each of its files is: by pipeline's folder, snapshot's folder and path, the hash."""
    said = {}
    for file in root.glob("pipelines/*/*/_chartbook/snapshot.json"):
        document = json.loads(file.read_text(encoding="utf-8"))
        for part in _parts(document):
            for entry in part["stored"]["files"]:
                said[(file.parent.parent.parent.name, file.parent.parent.name, entry["path"])] = entry["content_hash"]
    return said


class TestTheStoreFound:
    def test_the_dry_run_names_the_folder_with_no_record_and_the_files_taken_from_another_snapshot_and_the_move_goes_through_in_one_run(self, found_store):
        root, names = found_store
        before = tree_of(root)
        in_a = sum(1 for path in (root / "pipelines" / "acme+news" / names["a"]).rglob("*") if path.is_file() and path.name != "desktop.ini")
        first = "_data/articles/ (6)."  # the folder they are under, with how many: no names
        dry, said = typed("store", "migrate", "--dry-run")
        print(dry.output)
        assert dry.exit_code == 0 and tree_of(root) == before and dry.output.splitlines()[-1] == "Nothing was moved."
        assert f"has the layout of ChartBook 0.5: 1 pipeline(s), 2 snapshot(s)." in said
        # A is named for B's snapshot (B's record says the time of A's name, in a folder named a second later): no
        # record of its own is to be waited for, and none that arrives means a snapshot to be made again
        of_a = (
            f"  1 folder(s) {{hold}} files and no record, and {{are}} named for a snapshot whose record {{isw}} in another folder: "
            f"acme+news/{names['a']} ({in_a} file(s); its record {{isw}} in {names['b']}). The files in such a folder that a record "
            f"names {{are}} moved with that record, and the rest {{goes}} aside."
        )
        assert of_a.format(hold="hold", are="are", isw="is", goes="goes") in said
        assert "have no record" not in said and "wait for it" not in said and "has to be made again" not in said
        assert "  6 " + TAKEN.format(are="are") + first in said
        # What B has of the files that R takes from A goes aside though B's record names it: counted apart from what no record names
        assert f"  {len(IN_A) + 1} file(s) that a record names go aside with the old folder too: each is a second copy, or part of one, of bytes that are moved in from another place a record names." in said
        # A folder that holds nothing but what a desktop leaves is no folder with files; and nothing is missing
        assert names["nothing"] not in said and "missing or of another size" not in said
        # At the question, the same
        no, asked = typed("store", "migrate", input="n\n")
        in_the_dry_run = of_a.format(hold="hold", are="are", isw="is", goes="goes")
        assert no.exit_code == 0 and "Move it?" in asked and in_the_dry_run in asked and tree_of(root) == before
        assert asked.index(in_the_dry_run) < asked.index("Move it?")
        result, said = typed("store", "migrate", "--yes")
        print(result.output)
        assert result.exit_code == 0, result.output
        assert f"has this version's layout: 1 pipeline(s), 2 snapshot(s)." in said
        assert "1 snapshot(s) became complete (0 of them made by a pin), 1 became increments on the newest of their pipeline." in said
        assert "  6 " + TAKEN.format(are="were") + first in said
        assert f"  {len(IN_A) + 1} file(s) that a record names went aside with the old folder too: each is a second copy, or part of one, of bytes that were moved in from another place a record names." in said
        assert of_a.format(hold="held", are="were", isw="was", goes="went") in said
        assert "missing or of another size" not in said and "out of the store" not in said and "has to be made again" not in said and "look there first" not in said

    def test_the_record_of_the_folder_that_had_none_is_a_second_record_when_it_arrives(self, found_store):
        """A's own record, of B's commit and time, comes once the store is moved. The line of the first run had said that such a record means a snapshot to be made again, and the run that met it said a second record went aside: now neither run says anything is to be made again."""
        root, names = found_store
        b = json.loads((root / "pipelines" / "acme+news" / names["b"] / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
        assert names["a"] == b["made_at"][:19].replace(":", "") + "Z_" + b["code"]["commit"][:12]  # A's name is the time and the commit of B's record
        first, said = typed("store", "migrate", "--yes")
        assert first.exit_code == 0 and "has to be made again" not in said
        arrived = root / "pipelines" / "acme+news" / names["a"] / "_chartbook" / "snapshot.json"
        arrived.parent.mkdir(parents=True)
        arrived.write_text(json.dumps(b, indent=2).replace(names["b"], names["a"]) + "\n", encoding="utf-8", newline="\n")
        again, said = typed("store", "migrate", "--yes")
        assert again.exit_code == 0 and f"1 second record(s) of a snapshot that was moved in went aside: acme+news/{names['a']}." in said
        assert "Run that pipeline again" not in said and fresh(root).verify() == []

    def test_afterwards_the_store_is_whole_and_a_read_through_the_pin_gives_the_bytes_the_record_says(self, found_store, monkeypatch):
        root, names = found_store
        said = {path: content_hash for (_, folder, path), content_hash in said_by_the_records(root).items() if folder == names["r"]}
        assert MADE[1] in {made_at for _, made_at in lock.read_lock(names["reader"]).snapshots()}  # the reader pins R
        assert typed("store", "migrate", "--yes")[0].exit_code == 0
        store = fresh(root)
        assert store.verify() == []
        kept = {kept.folder.name: kept for kept in store.records()}
        # R is the complete one, with every file its record names in its own folder; B is an increment on it
        assert sorted(kept) == [names["b"], names["r"]]
        assert not kept[names["r"]].increment and kept[names["b"]].increment and kept[names["b"]].builds_on == names["r"]
        r = root / "snapshots" / "acme+news" / names["r"]
        assert {path: sha(r / path) for path in said} == said and len(said) > 12
        assert all(file.location.is_relative_to(r) for asset in kept[names["r"]].assets for file in asset.files)
        assert store.holes_of(kept[names["r"]].path) == [] and store.holes_of(kept[names["b"]].path) == []
        # B keeps in its own folder only what R does not have
        own = sorted(p.relative_to(root / "increments" / "acme+news" / names["b"]).as_posix() for p in (root / "increments" / "acme+news" / names["b"]).rglob("*") if p.is_file())
        assert own == ["README.md", "_chartbook/INCREMENT.txt", "_chartbook/index.json", "_chartbook/snapshot.json", "_data/articles/11.parquet", "_data/totals.parquet", "_output/counts.html"]
        # Through the reader's pin: a file that was in A, and one that was only in B
        files = {file.name: file for file in data.files("acme/news:articles", project_dir=names["reader"])}
        assert len(files) == 12 and all(file.is_relative_to(r) for file in files.values())
        assert sha(files["00.parquet"]) == said["_data/articles/00.parquet"] and sha(files["01.parquet"]) == said["_data/articles/01.parquet"]
        assert {name: sha(file) for name, file in files.items()} == {f"{number:02d}.parquet": said[f"_data/articles/{number:02d}.parquet"] for number in range(12)}
        monkeypatch.chdir(names["reader"])
        check = CliRunner().invoke(main, ["pin", "--check"])
        assert check.exit_code == 0, check.output

    def test_it_removes_nothing_and_what_no_record_names_is_aside_or_where_the_merge_puts_it(self, found_store, monkeypatch):
        root, names = found_store
        before = contents(root)
        desktops = len(list(root.rglob("desktop.ini")))
        second_copy = tree_of(root / "pipelines" / "acme+news" / names["r2"])
        gone: list = []
        with monkeypatch.context() as patch:
            watch(patch, root, gone)
            done = migrate_0_5.run(root)
        # Nothing but its own journal and its own temporary files, and store.json written over
        assert not_its_own(gone) == [] and ("unlink", "_chartbook/move-to-v3.jsonl") in gone
        after = contents(root)
        assert [paths for key, paths in before.items() if key not in after and not any(path in OWN for path in paths)] == []
        aside = root / ASIDE / "pipelines" / "acme+news"
        assert done.kept == f"{ASIDE}/pipelines" and not (root / "pipelines").exists()
        # The files in A that no record names, and what was left of A
        for path in UNNAMED:
            assert (aside / names["a"] / path).read_bytes() == f"no record names {path}".encode()
        # The second copy of R, whole, its own copies of R's own files with it
        assert tree_of(aside / names["r2"]) == second_copy and (aside / names["r2"] / "_data" / "articles" / "11.parquet").is_file()
        # The folder that held nothing but what a desktop leaves, and the second copy of the README
        assert sorted(p.relative_to(aside / names["nothing"]).as_posix() for p in (aside / names["nothing"]).rglob("*") if p.is_file()) == ["_data/desktop.ini", "desktop.ini"]
        assert (aside / "README 2.txt").read_bytes() == (aside / "README.txt").read_bytes()
        # Every desktop.ini is still somewhere, and none is in a snapshot
        assert len(list(root.rglob("desktop.ini"))) == desktops
        assert not [p for tree in ("snapshots", "increments") for p in (root / tree).rglob("desktop.ini")]
        assert (root / "desktop.ini").is_file() and all((root / "_chartbook" / name / "desktop.ini").is_file() for name in ("roots", "origins", "tmp"))
        # The second copy of a note of a lockfile is with the notes, and the store reads it as a copy of one
        assert (root / "_chartbook" / "roots" / names["note"].replace(".json", " 2.json")).is_file()
        notes = fresh(root).roots()
        assert sorted(note.copy for note in notes) == [False, True] and {note.lockfile for note in notes} == {names["reader"] / "chartbook.lock"}
        # The second copy of a commit's origins is with the origins, and nothing reads a folder of that name
        assert tree_of(root / "_chartbook" / "origins" / f"{names['origin']} 2") == tree_of(root / "_chartbook" / "origins" / names["origin"])

    def test_the_second_copy_of_r_is_not_named_as_a_snapshot_to_be_made_again(self, found_store):
        root, names = found_store
        found_ = migrate_0_5.plan(root)
        assert found_.second == [("acme+news", names["r2"])] and found_.set_aside == []
        dry, said = typed("store", "migrate", "--dry-run")
        assert f"  1 second record(s) of a snapshot that is moved in go aside: acme+news/{names['r2']}." in said
        assert "without being moved in" not in said and "Run that pipeline again" not in said
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and f"  1 second record(s) of a snapshot that was moved in went aside: acme+news/{names['r2']}." in said
        assert "without being moved in" not in said and "Run that pipeline again" not in said and "made again with" not in said

    def test_a_second_run_says_there_is_nothing_to_move(self, found_store):
        root, _ = found_store
        assert typed("store", "migrate", "--yes")[0].exit_code == 0
        moved = tree_of(root)
        for words in (["store", "migrate"], ["store", "migrate", "--dry-run"], ["store", "migrate", "--yes"]):
            again, said = typed(*words)
            assert again.exit_code == 0 and "has the layout of this version already: nothing to move." in said and tree_of(root) == moved

    def test_a_record_of_another_snapshot_that_a_sync_brings_into_that_folder_after_the_move_is_named_to_be_made_again(self, found_store):
        """Not A's own record (the test above), but one of a snapshot the store does not have, made in the same second: as any record that arrives on a moved store."""
        root, names = found_store
        late = json.loads((root / "pipelines" / "acme+news" / names["b"] / "_chartbook" / "snapshot.json").read_text(encoding="utf-8"))
        late["made_at"] = MADE[0].replace(".000000Z", ".500000Z")  # another snapshot than B: made in the same second
        assert typed("store", "migrate", "--yes")[0].exit_code == 0
        arrived = root / "pipelines" / "acme+news" / names["a"] / "_chartbook" / "snapshot.json"
        arrived.parent.mkdir(parents=True)
        arrived.write_text(json.dumps(late, indent=2) + "\n", encoding="utf-8", newline="\n")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and f"1 snapshot(s) went aside without being moved in: acme+news/{names['a']}. Run that pipeline again with this ChartBook." in said
        assert (root / ASIDE / "pipelines (2)" / "acme+news" / names["a"] / "_chartbook" / "snapshot.json").is_file() and fresh(root).verify() == []


class TestStoppedAnywhereTheMoveEndsAsTheUninterruptedOne:
    """A plan made half way through a move looks up where a file is again: it must end in the tree an uninterrupted move makes."""

    @pytest.fixture(params=["the store found", "every way a file can be elsewhere"])
    def store(self, request, work, monkeypatch):
        if request.param == "the store found":
            monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
            root = work / "store"
            found(work, root)
        else:
            root = empty_store(work)
            elsewhere(root)
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        return root, whole

    def test_after_every_step_with_the_journal_kept_and_with_it_deleted(self, store, work):
        root, whole = store
        wanted, reads = tree_of(whole), read_through(whole)
        wrong = []
        for number in range(1, len(migrate_0_5.plan(root).steps) + 2):
            cut = work / "cut"
            shutil.copytree(root, cut)
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=stop_after(number))
            for journal in (True, False):
                again = work / "again"
                shutil.copytree(cut, again)
                if not journal and (again / migrate_0_5.JOURNAL).is_file():
                    (again / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                migrate_0_5.run(again)
                if tree_of(again) != wanted:
                    wrong.append((number, journal, sorted(set(tree_of(again).items()) ^ set(wanted.items()))[:6]))
                elif read_through(again) != reads:
                    wrong.append((number, journal, "reads differ"))
                rmtree(again)
            rmtree(cut)
        assert not wrong, json.dumps(wrong, indent=1)

    @pytest.mark.parametrize("when", ["before", "after"])
    def test_killed_at_every_rename_the_disk_is_asked_for(self, store, work, monkeypatch, when):
        """Finer than a step: the process dies just before, or just after, each os.replace of a move (its journal's too)."""
        root, whole = store
        wanted, reads = tree_of(whole), read_through(whole)
        real = os.replace
        counted = work / "counted"
        shutil.copytree(root, counted)
        calls = []
        monkeypatch.setattr(os, "replace", lambda a, b: (calls.append(1), real(a, b))[1])
        migrate_0_5.run(counted)
        monkeypatch.setattr(os, "replace", real)
        rmtree(counted)
        wrong = []
        for number in range(1, len(calls) + 1):
            for journal in (True, False):
                cut = work / "cut"
                shutil.copytree(root, cut)
                seen = []

                def dying(a, b, number=number, seen=seen):
                    seen.append(1)
                    if len(seen) == number and when == "before":
                        raise Stop()
                    real(a, b)
                    if len(seen) == number and when == "after":
                        raise Stop()

                store_module._read_records.clear()
                monkeypatch.setattr(os, "replace", dying)
                try:
                    with pytest.raises(Stop):
                        migrate_0_5.run(cut)
                finally:
                    monkeypatch.setattr(os, "replace", real)
                if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                    (cut / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                migrate_0_5.run(cut)
                if tree_of(cut) != wanted:
                    wrong.append((number, journal, sorted(set(tree_of(cut).items()) ^ set(wanted.items()))[:6]))
                elif read_through(cut) != reads:
                    wrong.append((number, journal, "reads differ"))
                rmtree(cut)
        assert not wrong, f"{len(wrong)} of {2 * len(calls)}: " + json.dumps(wrong[:8], indent=1)


class TestAFileThatIsNotWhereItsRecordSays:
    """Rule 2, on the store written by hand (``elsewhere``): each row of its table."""

    def test_each_is_taken_from_where_another_record_has_the_same_bytes_and_reads_as_its_record_says(self, elsewhere_store):
        root, names = elsewhere_store
        said = said_by_the_records(root)
        lacking = [("acme+p", names["s3"], "_data/k6.parquet")]
        found_ = migrate_0_5.plan(root)
        assert found_.missing == lacking  # only the one that no record's place holds
        assert found_.elsewhere == 11 and found_.elsewhere_under == [("_data/", 11)]
        assert found_.no_record == [("acme+p", names["c0"], 3)]
        assert found_.doubled == 2  # the second copy of k1 that s2 has, and the half of k8
        done = migrate_0_5.run(root)
        assert done.missing == lacking and (done.elsewhere, done.elsewhere_under, done.no_record) == (found_.elsewhere, found_.elsewhere_under, found_.no_record)
        reads = read_through(root)
        assert {key: "sha256:" + value for key, value in reads.items() if len(value) == 64} == {
            (pipeline.replace("+", "/"), folder, path): content_hash for (pipeline, folder, path), content_hash in said.items() if (pipeline, folder, path) not in lacking
        }
        assert [key for key, value in reads.items() if len(value) != 64] == [("acme/p", *lacking[0][1:])]
        problems = [problem.format() for problem in fresh(root).verify()]
        assert len(problems) == 1 and "_data/k6.parquet is not in the store" in problems[0], problems

    def test_an_older_snapshot_names_them_in_the_one_it_builds_on_and_is_not_given_a_second_copy(self, elsewhere_store):
        root, names = elsewhere_store
        migrate_0_5.run(root)
        kept = {kept.folder.name: kept for kept in fresh(root).records() if kept.pipeline == "acme/p"}
        own = {name: sorted(p.name for p in (root / "increments" / "acme+p" / names[name] / "_data").iterdir()) for name in ("s1", "s2")}
        assert own == {"s1": ["k2.parquet"], "s2": ["k2.parquet"]}  # k1, k4, k5, k8 and k9 are the newest one's
        where = {file.path: file.location.relative_to(root).as_posix() for asset in kept[names["s2"]].assets for file in asset.files}
        assert where["_data/k5.parquet"] == f"snapshots/acme+p/{names['s3']}/_data/k5a.parquet"  # under the name the newest has it by
        assert where["_data/k1.parquet"] == f"snapshots/acme+p/{names['s3']}/_data/k1.parquet"
        # Of two older snapshots that each had the bytes, the first in order gave them, and the other's went aside
        aside = root / ASIDE / "pipelines" / "acme+p"
        assert (aside / names["s2"] / "_data" / "k1.parquet").is_file() and not (aside / names["s1"] / "_data" / "k1.parquet").exists()
        # Half a file where a record says the file is, with the whole of it elsewhere: the half went aside
        assert (aside / names["c0"] / "_data" / "k8.parquet").stat().st_size == 50
        assert (root / "snapshots" / "acme+p" / names["s3"] / "_data" / "k8.parquet").stat().st_size == 180

    def test_the_choice_is_the_same_every_time_and_only_the_copies_are_read(self, elsewhere_store, monkeypatch):
        root, names = elsewhere_store
        first = [(step.op, step.source, step.target) for step in migrate_0_5.plan(root).steps]
        assert [(step.op, step.source, step.target) for step in migrate_0_5.plan(root).steps] == first
        old, new = f"pipelines/acme+p/{names['s1']}/_data/k1.parquet", f"snapshots/acme+p/{names['s3']}/_data/k1.parquet"
        assert ("rename", old, new) in first and not [step for step in first if step[1] == f"pipelines/acme+p/{names['s2']}/_data/k1.parquet"]
        copies = sorted(source for op, source, _ in first if op == "copy")
        opened: list = []
        real = open

        def counting(file, mode="r", *args, **kwargs):
            if "b" in mode and "r" in mode:
                opened.append(Path(file).relative_to(root).as_posix())
            return real(file, mode, *args, **kwargs)

        monkeypatch.setattr(migrate_0_5, "open", counting, raising=False)
        migrate_0_5.run(root)
        assert sorted(opened) == copies and len(copies) == 7  # a rename trusts the size, and a copy is hashed as it is written

    def test_the_lines_count_them_with_the_first_and_the_missing_line_is_as_true_after_as_before(self, elsewhere_store):
        root, names = elsewhere_store
        first = "_data/ (11)."
        missing = f"  1 file(s) that a record names are missing or of another size, as before the move, in 1 snapshot(s):     acme+p/{names['s3']}: 1 of 9 file(s)     under _data/ (1) "
        dry, said = typed("store", "migrate", "--dry-run")
        print(dry.output)
        assert dry.exit_code == 0 and "  11 " + TAKEN.format(are="are") + first in said and missing in said
        result, said = typed("store", "migrate", "--yes")
        print(result.output)
        assert result.exit_code == 0 and "  11 " + TAKEN.format(are="were") + first in said and missing in said
        assert "out of the store" not in said

    @pytest.mark.parametrize("journal", ["kept", "deleted"])
    def test_one_that_is_where_it_goes_already_is_not_taken_again(self, elsewhere_store, journal):
        """Cut short once every file is in place: the next plan finds each where it goes, and the last lines say what the whole move took where its journal is kept."""
        root, names = elsewhere_store
        steps = migrate_0_5.plan(root).steps
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=stop_after(max(number for number, step in enumerate(steps, 1) if step.op in ("rename", "copy"))))
        if journal == "deleted":
            (root / migrate_0_5.JOURNAL).unlink()
        store_module._read_records.clear()
        again = migrate_0_5.plan(root)
        assert again.elsewhere == 0 and again.missing == [("acme+p", names["s3"], "_data/k6.parquet")]
        assert not [step for step in again.steps if step.op in ("rename", "copy") and os.path.lexists(root / step.source) and not os.path.lexists(root / step.target)]
        done = migrate_0_5.run(root)
        assert done.elsewhere == (11 if journal == "kept" else 0) and done.missing == [("acme+p", names["s3"], "_data/k6.parquet")]

    def test_one_whose_place_is_taken_by_a_file_of_another_size_is_not_taken_from_elsewhere(self, work):
        """Nothing is renamed onto a file that is there: the newest one's file is said to be of another size, and the older snapshot keeps its own good copy."""
        root = empty_store(work)
        a = b"a" * 100
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/a.parquet", a)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", a, None, None)])
        s2 = record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", a, folder_of("2025-09-01", "h"), None)])  # not where it says
        in_place = put(root, "acme+p", s2, "_data/a.parquet", a[:40], tree="snapshots")  # half of it, where it goes: a move elsewhere, half arrived
        found_ = migrate_0_5.plan(root)
        assert found_.elsewhere == 0 and found_.missing == [("acme+p", s2, "_data/a.parquet")]
        done = migrate_0_5.run(root)
        assert done.missing == [("acme+p", s2, "_data/a.parquet")] and in_place.read_bytes() == a[:40]
        assert (root / "increments" / "acme+p" / s1 / "_data" / "a.parquet").read_bytes() == a  # its own, and not named in the newest

    def test_half_a_file_at_the_old_place_of_a_snapshot_that_has_the_whole_in_place_is_not_handed_to_another(self, work):
        """Two snapshots a pin made share bytes. The newer has its file where it goes already (a move elsewhere, half arrived), and half of one at its old place. The older, whose file is nowhere, is given a copy of the whole, and never the half."""
        root = empty_store(work)
        q = b"q" * 400
        q2 = folder_of("2025-11-01", "f")
        put(root, "acme+q", q2, "_data/q.parquet", q[:200])
        put(root, "acme+q", q2, "_data/q.parquet", q, tree="snapshots")
        q1 = record(root, "acme/q", "2025-10-01", "e", [("_data/q.parquet", q, folder_of("2025-08-01", "j"), None)], made_by="pin")
        record(root, "acme/q", "2025-11-01", "f", [("_data/q.parquet", q, None, None)], made_by="pin")
        found_ = migrate_0_5.plan(root)
        assert found_.elsewhere == 1 and found_.missing == []
        copy = (f"snapshots/acme+q/{q2}/_data/q.parquet", f"snapshots/acme+q/{q1}/_data/q.parquet")
        assert [(step.source, step.target) for step in found_.steps if step.op == "copy"] == [copy]
        done = migrate_0_5.run(root)
        assert done.missing == [] and done.copied_as_is == [] and (root / copy[1]).read_bytes() == q and (root / copy[0]).read_bytes() == q
        assert (root / ASIDE / "pipelines" / "acme+q" / q2 / "_data" / "q.parquet").read_bytes() == q[:200]  # aside, and said
        assert done.in_place == [(f"{ASIDE}/pipelines/acme+q/{q2}/_data/q.parquet", copy[0], 200, 400)]
        assert fresh(root).verify() == []


class TestAFolderWithFilesAndNoRecord:
    """Rule 1: it never stops the move."""

    def _one(self, work, monkeypatch):
        root = empty_store(work)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/a.parquet", b"a" * 100)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", b"a" * 100, None, None)])
        return root, s1

    @pytest.mark.parametrize("left", [".DS_Store", "desktop.ini", "Thumbs.db", "._a.parquet", "DESKTOP.INI"])
    def test_one_that_holds_only_what_a_desktop_leaves_is_not_one(self, work, monkeypatch, left):
        root, s1 = self._one(work, monkeypatch)
        put(root, "acme+p", folder_of("2025-09-01", "h"), f"_data/{left}", b"\x00")
        put(root, "acme+p", folder_of("2025-09-01", "h"), left, b"\x00")
        assert migrate_0_5.plan(root).no_record == []
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and "files and ha" not in said and fresh(root).verify() == []  # neither "have" nor "had no record"
        assert (root / ASIDE / "pipelines" / "acme+p" / folder_of("2025-09-01", "h") / "_data" / left).is_file()

    def test_one_in_a_pipeline_with_no_snapshot_is_named_too_and_goes_aside_whole(self, work, monkeypatch):
        root, s1 = self._one(work, monkeypatch)
        alone = folder_of("2025-09-01", "h")
        put(root, "acme+other", alone, "_data/x.parquet", b"x" * 10)
        put(root, "acme+other", alone, "_data/y.parquet", b"y" * 10)
        assert migrate_0_5.plan(root).no_record == [("acme+other", alone, 2)]
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and f"1 folder(s) held files and had no record: acme+other/{alone} (2 file(s))." in said
        assert (root / ASIDE / "pipelines" / "acme+other" / alone / "_data" / "x.parquet").read_bytes() == b"x" * 10
        assert not (root / "snapshots" / "acme+other").exists() and fresh(root).verify() == []

    def test_nothing_about_its_age_decides_anything(self, work, monkeypatch):
        """A folder written this second is taken as one written a year ago: only the person at the question knows whether a sync is at work."""
        root, s1 = self._one(work, monkeypatch)
        file = put(root, "acme+p", folder_of("2025-09-01", "h"), "_data/x.parquet", b"x" * 10)
        now = typed("store", "migrate", "--dry-run")[1]
        long_ago = file.stat().st_mtime - 400 * 86400
        for path in (file, file.parent, file.parent.parent):
            os.utime(path, (long_ago, long_ago))
        assert typed("store", "migrate", "--dry-run")[1] == now
        assert f"1 folder(s) hold files and have no record: acme+p/{folder_of('2025-09-01', 'h')} (1 file(s))." in now

    def test_a_move_cut_short_and_gone_on_with_names_it_with_the_files_it_held_at_first(self, elsewhere_store):
        root, names = elsewhere_store
        steps = migrate_0_5.plan(root).steps
        with pytest.raises(Stop):
            migrate_0_5.run(root, after_step=stop_after(max(number for number, step in enumerate(steps, 1) if step.op == "rename")))
        store_module._read_records.clear()
        assert migrate_0_5.plan(root).no_record == [("acme+p", names["c0"], 2)]  # one of its three is moved in by now
        assert migrate_0_5.run(root).no_record == [("acme+p", names["c0"], 3)]


class TestARecordThatGoesAside:
    """Rule 3: named as a snapshot to be made again only where no snapshot of its pipeline, commit and time was moved in."""

    def _two(self, work, monkeypatch):
        root = empty_store(work)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/a.parquet", b"a" * 100)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", b"a" * 100, None, None)])
        return root, s1

    def test_a_second_copy_of_a_folder_whose_snapshot_is_not_moved_in_is_named_to_be_made_again(self, work, monkeypatch):
        """The folder a sync named ``<name> 2`` holds the only record of its snapshot: the planner passes it over, and says so before the move."""
        root, s1 = self._two(work, monkeypatch)
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/b.parquet", b"b" * 100)
        record(root, "acme/p", "2025-11-01", "b", [("_data/b.parquet", b"b" * 100, None, None)])
        replace_when_let(root / "pipelines" / "acme+p" / s2, root / "pipelines" / "acme+p" / f"{s2} 2")
        found_ = migrate_0_5.plan(root)
        assert found_.set_aside == [("acme+p", f"{s2} 2")] and found_.second == [] and found_.snapshots == 1
        line = f"1 snapshot(s) {{go}} aside without being moved in: acme+p/{s2} 2. Run that pipeline again with this ChartBook."
        dry, said = typed("store", "migrate", "--dry-run")
        assert dry.exit_code == 0 and line.format(go="go") in said and "second record" not in said
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and line.format(go="went") in said and "second record" not in said
        assert (root / ASIDE / "pipelines" / "acme+p" / f"{s2} 2" / "_data" / "b.parquet").read_bytes() == b"b" * 100

    def test_a_record_that_cannot_be_read_in_such_a_folder_is_no_second_record(self, work, monkeypatch):
        root, s1 = self._two(work, monkeypatch)
        copy = root / "pipelines" / "acme+p" / f"{s1} 2" / "_chartbook" / "snapshot.json"
        copy.parent.mkdir(parents=True)
        copy.write_text("{half of a rec", encoding="utf-8", newline="\n")
        found_ = migrate_0_5.plan(root)
        assert found_.set_aside == [("acme+p", f"{s1} 2")] and found_.second == []
        assert migrate_0_5.run(root).set_aside == [("acme+p", f"{s1} 2")]

    def test_on_a_moved_store_a_late_record_of_a_snapshot_it_has_is_a_second_record_and_one_of_another_is_to_be_made_again(self, work, monkeypatch):
        root, s1 = self._two(work, monkeypatch)
        was = work / "was"
        shutil.copytree(root, was)
        migrate_0_5.run(root)
        store_module._read_records.clear()
        # A machine that had not been brought the move: the old folder again, and a snapshot made there since
        shutil.copytree(was / "pipelines", root / "pipelines")
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/b.parquet", b"b" * 100)
        record(root, "acme/p", "2025-11-01", "b", [("_data/b.parquet", b"b" * 100, s2, None), ("_data/a.parquet", b"a" * 100, s1, None)])
        found_ = migrate_0_5.plan(root)
        assert found_.second == [("acme+p", s1)] and found_.set_aside == [("acme+p", s2)] and found_.late == [] and found_.aside == 0
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0, result.output
        assert f"1 snapshot(s) went aside without being moved in: acme+p/{s2}. Run that pipeline again with this ChartBook." in said
        assert f"1 second record(s) of a snapshot that was moved in went aside: acme+p/{s1}." in said
        assert [kept.folder.name for kept in fresh(root).records()] == [s1] and fresh(root).verify() == []


class TestNoLineSaysToMoveOutAFolderThatARecordMayNameFilesIn:
    """Rule 4."""

    def _kept_in_the_older(self, work, monkeypatch):
        """Two snapshots, the newer keeping a file in the older one's folder, as 0.5 kept each file once."""
        root = empty_store(work)
        monkeypatch.setenv(config.STORE_ENV_VAR, str(root))
        a, b = b"a" * 100, b"b" * 200
        s1 = folder_of("2025-10-01", "a")
        put(root, "acme+p", s1, "_data/a.parquet", a)
        record(root, "acme/p", "2025-10-01", "a", [("_data/a.parquet", a, None, None)])
        s2 = folder_of("2025-11-01", "b")
        put(root, "acme+p", s2, "_data/b.parquet", b)
        record(root, "acme/p", "2025-11-01", "b", [("_data/a.parquet", a, s1, None), ("_data/b.parquet", b, None, None)])
        return root, s1, s2

    def test_a_record_that_cannot_be_followed_whose_folder_keeps_other_snapshots_files_says_how_many_and_to_leave_the_folder(self, work, monkeypatch):
        root, s1, s2 = self._kept_in_the_older(work, monkeypatch)
        broken = root / "pipelines" / "acme+p" / s1 / "_chartbook" / "snapshot.json"
        broken.write_text("{not json", encoding="utf-8", newline="\n")
        before = tree_of(root)
        for words in (["store", "migrate", "--dry-run"], ["store", "migrate", "--yes"]):
            result, said = typed(*words)
            assert result.exit_code == 1 and tree_of(root) == before
            assert f"The snapshot record {broken} cannot be followed (it is not a record this ChartBook reads), so the store is not moved" in said
            assert (
                "If a sync is still bringing it, wait and run this again; if it is no snapshot of yours, move that record out of "
                "the store and leave its folder where it is: 1 file(s) in the folder are named by other snapshots of the "
                "pipeline, and are moved with those. `chartbook store verify` says more."
            ) in said
            assert "move its folder out" not in said and "remove" not in said
        # The way out, carried out: the folder is then one with files and no record, and the other snapshot has its file
        replace_when_let(broken, work / "moved-out.json")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and f"1 folder(s) held files and had no record: acme+p/{s1} (1 file(s))." in said and "missing" not in said
        assert fresh(root).verify() == [] and (root / "snapshots" / "acme+p" / s2 / "_data" / "a.parquet").read_bytes() == b"a" * 100

    def test_one_whose_folder_keeps_no_other_snapshots_file_may_be_moved_out_and_the_line_says_it_was_asked(self, work, monkeypatch):
        root, s1, s2 = self._kept_in_the_older(work, monkeypatch)
        broken = root / "pipelines" / "acme+p" / s2 / "_chartbook" / "snapshot.json"
        broken.write_text("{not json", encoding="utf-8", newline="\n")
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 1 and (
            "if it is no snapshot of yours, move its folder out of the store: no other snapshot's record names a file in it. "
            "`chartbook store verify` says more."
        ) in said
        replace_when_let(root / "pipelines" / "acme+p" / s2, work / "moved-out")  # the way out, carried out
        result, said = typed("store", "migrate", "--yes")
        assert result.exit_code == 0 and "missing" not in said and fresh(root).verify() == []

    def test_no_line_of_the_mover_says_to_move_a_folder_with_files_out(self):
        """The one "move its folder out" left is said only once the other records were asked, and none names a file in it."""
        source = inspect.getsource(migrate_0_5)
        assert "move that folder out" not in source and "folder out of the store and run" not in source
        assert source.count("move its folder out of the store") == 1 and "no other snapshot's record names a file " in source
        assert "remove its folder" not in source and "remove that folder" not in source


#: The stores drawn (``tests/found_store_of_0_5.py::any_store``), by their seeds: each is moved whole, stopped after
#: every step, and stopped twice. All of the first 400 pass (2026-11-20; put ``tuple(range(400))`` here to see, ten
#: minutes on six cores). 26 of them broke a draft of the lookup, which took a file for a snapshot's own only where
#: nothing of another size was at its old place: once a move had given a snapshot the file from elsewhere, with half
#: of one still at its old place, the snapshot it was taken from found no copy to be made from. Ten of those are
#: kept here, and the first two.
SEEDS = (0, 1, 17, 24, 76, 85, 96, 100, 103, 114, 130, 136)


class TestAnyStoreOfThisKind:
    """Rule 2, and the folders being the truth, on stores drawn from a seed: snapshots made by an owner or a pin, whose records say a file is in their own folder, an earlier one's, one with no record or one that is not there, each place holding the file, half of it or nothing."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_stopped_twice_it_ends_in_the_same_tree(self, work, seed):
        """A plan made after a cut is cut again: the third plan is made from folders that two plans left."""
        import random

        root = empty_store(work)
        any_store(root, seed)
        whole = work / "whole"
        shutil.copytree(root, whole)
        migrate_0_5.run(whole)
        wanted, reads = tree_of(whole), read_through(whole)
        drawn = random.Random(seed)
        steps = len(migrate_0_5.plan(root).steps)
        wrong = []
        for _ in range(8):
            first, journal = drawn.randint(1, steps), drawn.random() < 0.5
            cut = work / "cut"
            shutil.copytree(root, cut)
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=stop_after(first))
            if not journal and (cut / migrate_0_5.JOURNAL).is_file():
                (cut / migrate_0_5.JOURNAL).unlink()
            store_module._read_records.clear()
            second = drawn.randint(1, max(1, len(migrate_0_5.plan(cut).steps)))  # with no step left, just after the marker
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

    @pytest.mark.parametrize("seed", SEEDS)
    def test_what_0_5_could_read_is_read_and_a_move_stopped_after_any_step_ends_in_the_same_tree(self, work, seed):
        root = empty_store(work)
        said = any_store(root, seed)
        before = contents(root)
        whole = work / "whole"
        shutil.copytree(root, whole)
        planned = migrate_0_5.plan(whole)
        done = migrate_0_5.run(whole)
        wanted, reads = tree_of(whole), read_through(whole)
        # What 0.5 could read (some record's place holds the bytes whole) reads as its record says; the rest is missing, as it
        # was, and the dry run and the last lines say the same of it
        assert {key[1:]: "sha256:" + value == said[key[1:]][0] for key, value in reads.items()} == {key: could for key, (_, could) in said.items()}
        assert set(done.missing) == {("acme+p", *key) for key, (_, could) in said.items() if not could} and planned.missing == done.missing
        assert (planned.elsewhere, planned.elsewhere_under, planned.doubled, planned.aside) == (done.elsewhere, done.elsewhere_under, done.doubled, done.aside)
        # And nothing that was in the store is gone from it
        after = contents(whole)
        assert [paths for key, paths in before.items() if key not in after and not any(path in OWN for path in paths)] == []
        wrong = []
        for number in range(1, len(migrate_0_5.plan(root).steps) + 2):
            cut = work / "cut"
            shutil.copytree(root, cut)
            with pytest.raises(Stop):
                migrate_0_5.run(cut, after_step=stop_after(number))
            for journal in (True, False):
                again = work / "again"
                shutil.copytree(cut, again)
                if not journal and (again / migrate_0_5.JOURNAL).is_file():
                    (again / migrate_0_5.JOURNAL).unlink()
                store_module._read_records.clear()
                migrate_0_5.run(again)
                if tree_of(again) != wanted:
                    wrong.append((number, journal, sorted(set(tree_of(again).items()) ^ set(wanted.items()))[:6]))
                elif read_through(again) != reads:
                    wrong.append((number, journal, "reads differ"))
                rmtree(again)
            rmtree(cut)
        assert not wrong, json.dumps(wrong[:4], indent=1)
