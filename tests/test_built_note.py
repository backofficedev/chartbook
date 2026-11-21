"""A snapshot is of what a run built.

``docs_src/design/one-command.md``, "A snapshot is of what a run built".
A build that succeeds leaves a note of what it ran on and what it left
(``chartbook.built``), and ``chartbook snapshot`` holds what is committed,
and what is on disk, against it. Each test is something a person types.
"""

import json
import os
from pathlib import Path

import pytest

from chartbook import built
from tests.test_lock_by_kind import _git
from tests.test_run_builds_and_snapshot_is_typed import (  # noqa: F401 - fixtures among them
    BUILD,
    DEMO,
    IGNORED,
    _committed,
    _folder,
    _ran,
    _run,
    _snapshot,
    _snapshots,
    _write,
    demo,
    store,
    work,
)

AS_IS = "to take what is on disk as it is: `chartbook snapshot --as-is{}`."
AGAIN = "  Build again: `chartbook run{}`, which rebuilds what your build finds out of date. Or, " + AS_IS
BUILD_IT = "  Build it: `chartbook run{}` (a build with nothing left to do takes a moment). Or, " + AS_IS


def _note(directory: Path) -> dict:
    return json.loads(built.note_path(directory).read_text(encoding="utf-8"))


def _change(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


class TestTheUsualWay:
    def test_run_commit_snapshot_is_made_and_nothing_more_is_said(self, demo, store):
        """Work that is not committed, a run, a commit of that same work, a snapshot: the commit is of what the build ran on."""
        _change(demo / "load.py", "x = 1\n")
        _write(demo, {**DEMO, "project": {"id": "acme/demo", "description": "As it is being worked on"}})
        assert _run().exit_code == 0
        note = _note(demo)
        _committed(demo)  # after the build, as the run's last line says
        result = _snapshot()
        assert result.exit_code == 0, result.output
        assert _note(demo) == note and "differ" not in result.output and "Error" not in result.output
        (taken,) = _snapshots(store)
        assert taken.built_by_run

    def test_committed_before_the_build_it_is_made(self, demo, store):
        assert _run().exit_code == 0
        result = _snapshot()
        assert result.exit_code == 0, result.output
        assert not [line for line in result.output.splitlines() if line.startswith("Error") or "differ" in line]
        # Held against the build, so its record says that ChartBook ran it
        (taken,) = _snapshots(store)
        assert taken.built_by_run

    def test_what_a_run_wrote_and_was_committed_after_is_the_same_source(self, demo, store, work):
        """The lockfile a run writes before it builds is hashed as the run left it, and committing it changes nothing."""
        from tests.test_run_builds_and_snapshot_is_typed import _depends_on_upstream, _snapshot_of

        upstream = _committed(_folder(work / "up", {**DEMO, "project": {"id": "acme/up"}}))
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        assert "Wrote chartbook.lock." in _run().output
        _committed(demo)
        result = _snapshot()
        assert result.exit_code == 0, result.output

    def test_the_note_is_kept_with_chartbooks_own_things(self, demo, store, work):
        assert _run().exit_code == 0
        assert built.note_path(demo).parent == work / "cache" / "built"
        note = _note(demo)
        assert note["schema"] == "chartbook/built/v1" and note["state"] == "built" and note["pipeline"] == "acme/demo"
        assert sorted(note["source"]) == [".gitignore", "chartbook.toml"] and sorted(note["outputs"]) == ["out.csv"]
        # Plain hashes, and nothing of git's: a SHA-256 of the file's bytes
        import hashlib

        assert note["source"]["chartbook.toml"]["hash"] == hashlib.sha256((demo / "chartbook.toml").read_bytes()).hexdigest()
        # Nothing of it is in the project, or in .git
        assert _git(demo, "status", "--porcelain", "--ignored") .split() == ["!!", "build.log", "!!", "out.csv"]
        assert not any("chartbook" in name for name in os.listdir(demo / ".git"))

    def test_run_with_snapshot_is_the_two_in_one(self, demo, store):
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 0, result.output
        assert _note(demo)["state"] == "built"
        # And the same files, typed again, are no new snapshot: the note of that run is the one they are held against
        assert "No new snapshot" in _snapshot().output


class TestWhatDiffers:
    def test_the_code_was_changed_after_the_build(self, demo, store):
        assert _run().exit_code == 0
        _change(demo / "load.py", "x = 1\n")
        _write(demo, {**DEMO, "project": {"id": "acme/demo", "description": "Fixed"}})
        _committed(demo)
        result = _snapshot()
        assert result.exit_code == 1 and _snapshots(store) == []
        assert result.output.splitlines() == [
            "Error: acme/demo: these differ from what it was built from: chartbook.toml, load.py (new).",
            AGAIN.format("", ""),
        ]
        # Built again, as it says, it is made: the build that has nothing to do leaves a new note
        assert _run().exit_code == 0 and _snapshot().exit_code == 0

    def test_a_file_was_changed_after_the_build(self, demo, store):
        assert _run().exit_code == 0
        _change(demo / "out.csv", "a,b\n1,2\n3,4\n")
        result = _snapshot()
        assert result.exit_code == 1 and _snapshots(store) == []
        assert result.output.splitlines() == [
            "Error: acme/demo: these differ from what its build left: out.csv.",
            AGAIN.format("", ""),
        ]

    def test_both_are_said_what_it_was_built_from_first(self, demo, store):
        assert _run().exit_code == 0
        _change(demo / "out.csv", "a,b\n1,2\n3,4\n")
        _change(demo / ".gitignore", IGNORED + "/other\n")
        _committed(demo)
        assert _snapshot().output.splitlines() == [
            "Error: acme/demo: these differ from what it was built from: .gitignore.",
            "  And these differ from what its build left: out.csv.",
            AGAIN.format("", ""),
        ]

    def test_a_file_that_is_gone_and_one_that_is_new_are_said_so(self, work, store, monkeypatch):
        table = {**DEMO, "dataframes": {name: {"path": f"./{name}.csv", "docs": "d"} for name in ("one", "two")}}
        table["scripts"] = {"build": "echo a > one.csv && echo a > two.csv"}
        directory = _committed(_folder(work / "p", table, "/*.csv\n"))
        _change(directory / "old.py", "x = 1\n")
        _committed(directory)
        monkeypatch.chdir(directory)
        assert _run().exit_code == 0
        (directory / "old.py").unlink()
        _change(directory / "new.py", "x = 2\n")
        # One thing it declared is declared no more, and another is: what the build left is asked of the manifest as it is now
        table["dataframes"] = {name: {"path": f"./{name}.csv", "docs": "d"} for name in ("one", "three")}
        _change(directory / "three.csv", "a\n")
        _write(directory, table)
        _committed(directory)
        assert _snapshot().output.splitlines()[:2] == [
            "Error: acme/demo: these differ from what it was built from: chartbook.toml, new.py (new), old.py (gone).",
            "  And these differ from what its build left: three.csv (new), two.csv (gone).",
        ]

    def test_more_than_ten_are_ten_and_how_many_more(self, demo, store):
        assert _run().exit_code == 0
        for number in range(12):
            _change(demo / f"f{number:02}.py", "x\n")
        _committed(demo)
        first = _snapshot().output.splitlines()[0]
        assert first == (
            "Error: acme/demo: these differ from what it was built from: "
            + ", ".join(f"f{number:02}.py (new)" for number in range(10)) + ", and 2 more."
        )

    def test_a_word_in_the_readme_is_a_change_too(self, demo, store):
        """The cost the design names first: any change after the build is refused. A build that has nothing to do is a moment."""
        _change(demo / "README.md", "# Demo\n")
        _committed(demo)
        assert _run().exit_code == 0
        _change(demo / "README.md", "# Demo, with its typo fixed\n")
        _committed(demo)
        assert "these differ from what it was built from: README.md." in _snapshot().output
        assert _run().exit_code == 0 and _snapshot().exit_code == 0

    def test_a_file_saved_in_the_second_it_was_hashed_at_the_same_size(self, demo, store):
        """Found by the review of the design: such a file keeps its size and its time, and git's own rule for it is to hash it again."""
        _change(demo / "params.py", "RATE = 1\n")
        _committed(demo)
        assert _run().exit_code == 0
        note = _note(demo)
        before = os.stat(demo / "params.py")
        _change(demo / "params.py", "RATE = 2\n")
        os.utime(demo / "params.py", ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.stat(demo / "params.py")
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
        # Hashed in the very second it was last changed: what the note has of its size and time is not to be trusted
        note["hashed_at"] = int(before.st_mtime)
        built.note_path(demo).write_text(json.dumps(note), encoding="utf-8")
        _committed(demo)
        assert "these differ from what it was built from: params.py." in _snapshot().output
        # Changed well before it was hashed, its size and time are taken, as git takes them for its index
        note["hashed_at"] = int(before.st_mtime) + 5
        built.note_path(demo).write_text(json.dumps(note), encoding="utf-8")
        assert _snapshot().exit_code == 0

    def test_a_built_file_that_git_tracks_is_settled_by_its_bytes(self, work, store, monkeypatch):
        """Found by the review of the design: `git stash`, a rebase, a checkout and back write such a file again, with the same bytes and another time."""
        directory = _committed(_folder(work / "p", DEMO, "/build.log\n"))  # out.csv is kept in git
        monkeypatch.chdir(directory)
        assert _run().exit_code == 0
        _committed(directory)
        assert _run().exit_code == 0  # built from what is committed, its own output among it
        assert "hash" in _note(directory)["outputs"]["out.csv"]
        old = os.stat(directory / "out.csv")
        os.utime(directory / "out.csv", ns=(old.st_atime_ns, old.st_mtime_ns + 90 * 10**9))
        assert _snapshot().exit_code == 0
        # One that git does not track has its size and its time, and no more: touched, it is not the build's
        ignored = _committed(_folder(work / "q", {**DEMO, "project": {"id": "acme/q"}}))
        monkeypatch.chdir(ignored)
        assert _run().exit_code == 0 and "hash" not in _note(ignored)["outputs"]["out.csv"]
        old = os.stat(ignored / "out.csv")
        os.utime(ignored / "out.csv", ns=(old.st_atime_ns, old.st_mtime_ns + 90 * 10**9))
        assert "these differ from what its build left: out.csv." in _snapshot().output

    def test_a_time_is_held_in_whole_seconds(self, demo, store):
        assert _run().exit_code == 0
        old = os.stat(demo / "out.csv")
        os.utime(demo / "out.csv", ns=(old.st_atime_ns, (old.st_mtime_ns // 10**9) * 10**9 + 1))
        assert _snapshot().exit_code == 0


class TestNoBuildToHoldItAgainst:
    def test_files_that_no_run_built_are_refused(self, demo, store):
        _change(demo / "out.csv", "a,b\n")
        result = _snapshot()
        assert result.exit_code == 1 and _snapshots(store) == []
        assert result.output.splitlines() == [
            "Error: acme/demo has not been built by `chartbook run` here, so there is nothing to hold its files against.",
            BUILD_IT.format("", ""),
        ]

    def test_a_build_that_failed_is_said_to_be_that(self, work, store, monkeypatch):
        table = {**DEMO, "scripts": {"build": "echo a,b > out.csv && exit 3"}}
        directory = _committed(_folder(work / "p", table))
        monkeypatch.chdir(directory)
        assert _run().exit_code == 3
        note = _note(directory)
        assert note["state"] == "building" and "outputs" not in note
        said = _snapshot().output.splitlines()
        began = f"{note['began_at'][:10]} {note['began_at'][11:16]} UTC"
        assert said == [
            f"Error: acme/demo: its last build here failed, was stopped, or is still running (it began {began}).",
            "  Build again: `chartbook run`. Or, " + AS_IS.format(""),
        ]

    def test_a_build_that_ended_without_writing_what_it_declares_is_one_that_failed(self, work, store, monkeypatch):
        table = {**DEMO, "dataframes": {name: {"path": f"./{name}.csv", "docs": "d"} for name in ("one", "two")}}
        table["scripts"] = {"build": "echo a > one.csv"}
        directory = _committed(_folder(work / "p", table, "/*.csv\n"))
        monkeypatch.chdir(directory)
        assert _run().exit_code == 1 and _note(directory)["state"] == "building"
        assert "its last build here failed, was stopped, or is still running" in _snapshot().output

    def test_a_run_that_stops_before_its_script_leaves_the_note_as_it_was(self, demo, store):
        """Found by the review of the design: "gone when a build starts" was a removal, also where nothing was started."""
        assert _run().exit_code == 0
        note = _note(demo)
        assert _run("no-such-script").exit_code != 0
        assert _note(demo) == note and _snapshot().exit_code == 0

    def test_another_script_leaves_the_note_alone(self, demo, store):
        assert _run().exit_code == 0
        note = _note(demo)
        assert _run("test").exit_code == 0 and _note(demo) == note

    def test_a_note_of_another_pipeline_or_another_machine_is_no_note_of_this_one(self, demo, store, monkeypatch):
        """Found by the review of the design: a path is not enough where a container puts every project at one, or one home serves several machines."""
        assert _run().exit_code == 0
        note = _note(demo)
        built.note_path(demo).write_text(json.dumps({**note, "pipeline": "acme/other"}), encoding="utf-8")
        assert _snapshot().output.splitlines() == [
            "Error: acme/demo has not been built by `chartbook run` here: the note of a build of this folder is of acme/other.",
            BUILD_IT.format("", ""),
        ]
        built.note_path(demo).write_text(json.dumps({**note, "machine": "another"}), encoding="utf-8")
        assert _snapshot().output.splitlines()[0] == (
            "Error: acme/demo has not been built by `chartbook run` here: the note of a build of this folder is left by another machine."
        )

    def test_a_note_that_another_run_has_replaced_is_not_written_over(self, demo, store):
        """Two runs of one folder: the first to end finds that the note is no longer its own."""
        began = built.began(demo, "acme/demo")
        later = built.began(demo, "acme/demo")
        _change(demo / "out.csv", "a,b\n")
        built.finished(began)
        assert not began.kept and _note(demo)["state"] == "building" and _note(demo)["token"] == later.token
        built.finished(later)
        assert later.kept and _note(demo)["state"] == "built"


class TestTakingTheFilesAsTheyAre:
    def test_as_is_makes_it_and_its_record_does_not_say_chartbook_ran_the_build(self, demo, store):
        _change(demo / "out.csv", "a,b\n")
        result = _snapshot("--as-is")
        assert result.exit_code == 0, result.output
        (taken,) = _snapshots(store)
        assert not taken.built_by_run

    def test_the_way_past_is_typed_with_what_else_was_typed(self, demo, store, work, monkeypatch):
        from chartbook import missing

        _change(demo / "out.csv", "a,b\n")
        monkeypatch.chdir(work)
        here = f" --project-dir {missing._quoted(demo)}"
        said = _snapshot("--project-dir", str(demo), "--deep", "--complete", "--store", "mine").output.splitlines()
        assert said[1] == (
            f"  Build it: `chartbook run{here}` (a build with nothing left to do takes a moment). Or, to take what is on disk "
            f"as it is: `chartbook snapshot --as-is --deep --store mine --complete{here}`."
        )

    def test_the_option_is_in_the_help(self):
        from click.testing import CliRunner

        from chartbook.cli import main

        said = " ".join(CliRunner().invoke(main, ["snapshot", "--help"], prog_name="chartbook").output.split())
        assert "--as-is Take what is on disk as it is, without holding it against the last build `chartbook run` made here" in said


class TestAPipelineThatNothingBuilds:
    """It has no `build` script, and commits what it declares: its commit is the whole of it, and it is not asked."""

    def test_what_it_declares_is_committed_and_it_is_not_asked(self, work, store, monkeypatch):
        table = {key: value for key, value in DEMO.items() if key != "scripts"}
        directory = _folder(work / "p", table, "/build.log\n")
        _change(directory / "out.csv", "a,b\n")
        _committed(directory)
        monkeypatch.chdir(directory)
        result = _snapshot()
        assert result.exit_code == 0, result.output
        (taken,) = _snapshots(store)
        assert not taken.built_by_run and not built.note_path(directory).exists()

    def test_what_it_declares_and_does_not_commit_is_said(self, work, store, monkeypatch):
        """Found by the review of the design: it was told to `chartbook run`, which says it has no such script."""
        table = {key: value for key, value in DEMO.items() if key != "scripts"}
        directory = _committed(_folder(work / "p", table))
        _change(directory / "out.csv", "a,b\n")
        monkeypatch.chdir(directory)
        result = _snapshot()
        assert result.exit_code == 1 and result.output.splitlines() == [
            "Error: acme/demo has no `build` script, and declares files that are not committed: out.csv.",
            "  Commit them. Or, " + AS_IS.format(""),
        ]
        assert _snapshot("--as-is").exit_code == 0


class TestTheNotesThemselves:
    def test_a_note_whose_folder_is_gone_is_removed_when_another_is_written(self, demo, store, work, monkeypatch):
        import shutil

        other = _committed(_folder(work / "other", {**DEMO, "project": {"id": "acme/other"}}))
        monkeypatch.chdir(other)
        assert _run().exit_code == 0
        gone = built.note_path(other)
        assert gone.exists()
        shutil.rmtree(other, onerror=lambda function, path, _: (os.chmod(path, 0o700), function(path)))
        monkeypatch.chdir(demo)
        assert _run().exit_code == 0
        assert not gone.exists() and built.note_path(demo).exists()

    def test_a_cache_that_cannot_be_written_is_said_and_the_build_is_made(self, demo, store, monkeypatch):
        def refuse(path, note):
            raise PermissionError(13, "Permission denied", str(path))

        monkeypatch.setattr(built, "_write", refuse)
        result = _run()
        assert result.exit_code == 0 and _ran(demo) == 1
        assert (
            "acme/demo: the note of this build could not be kept, so `chartbook snapshot` will ask for it to be built again, "
            "or for `--as-is`."
        ) in result.output.splitlines()
        # And the run that makes its own snapshot holds it against what it has in hand
        strict = _run("--snapshot", "--no-gc-reminder")
        assert strict.exit_code == 0, strict.output

    def test_the_same_folder_by_another_name_has_the_same_note(self, demo, store, work):
        other = work / "DEMO"
        if not other.is_dir():
            pytest.skip("this disk tells letter cases apart")
        assert _run().exit_code == 0
        assert built.read(other) == _note(demo)

    def test_a_folder_in_no_repository_has_no_note_and_its_build_runs(self, work, store, monkeypatch):
        directory = _folder(work / "loose")
        monkeypatch.chdir(directory)
        result = _run()
        assert result.exit_code == 0 and _ran(directory) == 1
        assert not built.note_path(directory).exists() and "could not be kept" not in result.output

    def test_what_a_build_writes_is_listed_with_its_files(self, demo):
        from chartbook import run

        assert run.what_a_build_writes(demo) == [("out", "./out.csv", [])]
        _change(demo / "out.csv", "a,b\n")
        assert run.what_a_build_writes(demo) == [("out", "./out.csv", [demo / "out.csv"])]
        assert run.unwritten(demo) == [] and list(built.built_files(demo)) == ["out.csv"]
