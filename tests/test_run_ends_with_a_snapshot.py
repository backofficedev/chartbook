"""``chartbook run`` looks for what was declared, and makes a snapshot of committed work (``docs_src/design/one-command.md``).

A person types one command. While they are still editing, it builds and
says why there is no snapshot yet; once everything is committed, the same
command ends with one, which is what their other pipelines read. A build
that did not write something ``chartbook.toml`` declares is a failed run,
whatever its script exited with.

``chartbook run --snapshot`` is the strict form it was, and
``chartbook run --frozen`` makes none.
"""

import os
import sys
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, run, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git

#: A build that writes the one table the manifest declares, the same bytes every time, and says that it ran
BUILD = "echo a,b > out.csv && echo ran >> build.log"
DEMO = {
    "project": {"id": "acme/demo"},
    "scripts": {"build": BUILD, "test": "echo tested >> build.log"},
    "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
}
IGNORED = "/out.csv\n/build.log\n"


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _folder(directory: Path, table: dict = None, ignored: str = IGNORED) -> Path:
    directory.mkdir(parents=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table or DEMO), encoding="utf-8", newline="\n")
    (directory / ".gitignore").write_text(ignored, encoding="utf-8", newline="\n")
    return directory


def _committed(directory: Path) -> Path:
    if not (directory / ".git").exists():
        _git(directory, "init", "--quiet", "-b", "main")
    _git(directory, "add", "-A")
    _git(directory, "commit", "--quiet", "--allow-empty", "-m", "Work")
    return directory


@pytest.fixture
def demo(work, store, monkeypatch):
    """A pipeline in a repository of its own, everything committed, a branch checked out. Commands are run in it."""
    directory = _committed(_folder(work / "demo"))
    monkeypatch.chdir(directory)
    return directory


def _run(*arguments: str):
    return CliRunner().invoke(main, ["run", *arguments])


def _snapshots(store) -> list:
    return snapshot.all_snapshots(store) if store.root.is_dir() else []


def _ran(directory: Path) -> int:
    log = directory / "build.log"
    return len(log.read_text(encoding="utf-8").split()) if log.exists() else 0


class TestCommittedWork:
    def test_a_run_ends_with_a_snapshot(self, demo, store):
        result = _run()
        assert result.exit_code == 0, result.output
        commit = _git(demo, "rev-parse", "HEAD")
        said = result.output.splitlines()
        assert said[0] == "acme/demo: build"
        assert f"acme/demo at {commit[:7]}: 1 asset(s) in the store" in said
        assert any(line.startswith("Snapshot made.") for line in said)
        assert "not snapshotted" not in result.output
        (taken,) = _snapshots(store)
        assert taken.commit == commit and taken.built_by_run and taken.assets["out"]["content_hash"]

    def test_the_same_files_make_no_second_one(self, demo, store):
        assert _run().exit_code == 0
        again = _run()
        assert again.exit_code == 0, again.output
        assert any(line.startswith("No new snapshot: the same bytes and the same pins as the one made ") for line in again.output.splitlines())
        assert len(_snapshots(store)) == 1 and _ran(demo) == 2

    def test_the_lockfile_the_run_writes_does_not_count(self, demo, store, work):
        """A run pins before it builds, so its lockfile is new or changed when it looks: that is not work in progress."""
        upstream = _committed(_folder(work / "up", {**DEMO, "project": {"id": "acme/up"}}))
        (upstream / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
        snapshot.make(upstream, store=store)
        (demo / "chartbook.toml").write_text(
            tomli_w.dumps({**DEMO, "dependencies": {"acme/up": {"path": "../up"}}}), encoding="utf-8", newline="\n"
        )
        _committed(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Wrote chartbook.lock." in result.output and "not snapshotted" not in result.output
        assert _git(demo, "status", "--porcelain") == "?? chartbook.lock"
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up", "acme/demo"]

    def test_with_upstream_each_ends_with_one(self, demo, store, work):
        """--upstream builds and snapshots what this one depends on first, as it did; then this one's build ends with its own."""
        _committed(_folder(work / "up", {**DEMO, "project": {"id": "acme/up"}}))
        (demo / "chartbook.toml").write_text(
            tomli_w.dumps({**DEMO, "dependencies": {"acme/up": {"path": "../up"}}}), encoding="utf-8", newline="\n"
        )
        _committed(demo)
        result = _run("--upstream")
        assert result.exit_code == 0, result.output
        assert "not snapshotted" not in result.output
        assert [(taken.pipeline, taken.built_by_run) for taken in _snapshots(store)] == [("acme/up", True), ("acme/demo", True)]
        assert "Snapshot made, for what depends on it in this run to pin." in result.output
        assert "Snapshot made. A pipeline that depends on this one gets it with `chartbook update`." in result.output

    def test_an_upstream_that_forgot_an_output_stops_the_run(self, demo, store, work):
        table = {
            **DEMO, "project": {"id": "acme/up"},
            "dataframes": {**DEMO["dataframes"], "forgotten": {"path": "./forgotten.csv", "docs": "d"}},
        }
        _committed(_folder(work / "up", table))
        (demo / "chartbook.toml").write_text(
            tomli_w.dumps({**DEMO, "dependencies": {"acme/up": {"path": "../up"}}}), encoding="utf-8", newline="\n"
        )
        _committed(demo)
        result = _run("--upstream")
        assert result.exit_code == 1
        assert "Error: acme/up: its build did not write 1 thing chartbook.toml declares: forgotten (./forgotten.csv). Nothing after it was run." in result.output
        assert _snapshots(store) == [] and _ran(demo) == 0

    def test_the_function_makes_none_unless_told(self, demo, store):
        """`chartbook run` passes WHEN_COMMITTED; what calls the function decides for itself."""
        report = run.run(demo, echo=lambda line: None)
        assert report.failed is None and report.snapshots == [] and report.not_snapshotted == [] and _snapshots(store) == []
        report = run.run(demo, echo=lambda line: None, snapshot=run.WHEN_COMMITTED)
        assert report.failed is None and len(report.snapshots) == 1 and report.not_snapshotted == []

    def test_only_a_build_is_followed_by_one(self, demo, store):
        result = _run("test")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/demo: test", "Ran test in 1 pipeline(s)."]
        assert _snapshots(store) == []

    def test_frozen_makes_none_and_says_nothing_of_one(self, demo, store):
        result = _run("--frozen")
        assert result.exit_code == 0, result.output
        assert "snapshot" not in result.output.lower() and _snapshots(store) == [] and _ran(demo) == 1


class TestWorkInProgress:
    """The run goes well, and its last line says why there is no snapshot."""

    def last(self, result) -> list:
        said = result.output.splitlines()
        return said[said.index("Ran build in 1 pipeline(s).") + 1:]

    def test_files_that_are_not_committed(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        (demo / "chartbook.toml").write_text(tomli_w.dumps({**DEMO, "project": {"id": "acme/demo", "name": "Demo"}}), encoding="utf-8", newline="\n")
        result = _run()
        assert result.exit_code == 0, result.output
        assert self.last(result) == [
            "acme/demo: not snapshotted: 2 files are not committed (`git status` lists them).",
            "  A snapshot is of a commit: commit, and `chartbook run` again.",
        ]
        assert _snapshots(store) == [] and _ran(demo) == 1
        # Commit, and run again: that is all
        _committed(demo)
        assert "Snapshot made." in _run().output and len(_snapshots(store)) == 1

    def test_one_file(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        assert self.last(_run())[0] == "acme/demo: not snapshotted: 1 file is not committed (`git status` lists them)."

    def test_a_folder_in_no_repository(self, work, store, monkeypatch):
        monkeypatch.chdir(_folder(work / "loose"))
        result = _run()
        assert result.exit_code == 0, result.output
        assert self.last(result) == [
            "acme/demo: not snapshotted: this folder is in no git repository.",
            "  A snapshot is of a commit: `git init`, commit, and `chartbook run` again.",
        ]

    def test_a_repository_with_no_commit_yet(self, work, store, monkeypatch):
        directory = _folder(work / "new")
        _git(directory, "init", "--quiet", "-b", "main")
        monkeypatch.chdir(directory)
        assert self.last(_run()) == [
            "acme/demo: not snapshotted: nothing is committed yet.",
            "  A snapshot is of a commit: commit, and `chartbook run` again.",
        ]

    def test_a_commit_checked_out_by_its_hash(self, demo, store):
        """An old version looked at, or built again: a snapshot of it would be the newest of its pipeline, so it is made only when asked for."""
        commit = _git(demo, "rev-parse", "HEAD")
        _git(demo, "checkout", "--quiet", "--detach")
        result = _run()
        assert result.exit_code == 0, result.output
        assert self.last(result) == [
            f"acme/demo: not snapshotted: no branch is checked out, only the commit {commit[:7]}. "
            f"`chartbook run --snapshot` makes a snapshot of it."
        ]
        assert _snapshots(store) == []
        asked = _run("--snapshot", "--no-gc-reminder")
        assert asked.exit_code == 0 and "Snapshot made." in asked.output and len(_snapshots(store)) == 1

    def test_a_build_that_changes_a_file_git_tracks(self, work, store, monkeypatch):
        table = {**DEMO, "scripts": {"build": BUILD + " && echo more >> tracked.txt"}}
        directory = _folder(work / "writes")
        (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        (directory / "tracked.txt").write_text("kept in git\n", encoding="utf-8", newline="\n")
        monkeypatch.chdir(_committed(directory))
        result = _run()
        assert result.exit_code == 0, result.output
        assert self.last(result) == [
            "acme/demo: not snapshotted: its build changed 1 file that git tracks (M tracked.txt), so the commit it "
            "started at does not describe what it made."
        ]
        assert _snapshots(store) == []

    def test_a_commit_made_while_it_was_built(self, work, store, monkeypatch):
        for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            monkeypatch.setenv(name, "Test")
        for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            monkeypatch.setenv(name, "test@example.org")
        table = {**DEMO, "scripts": {"build": BUILD + " && git commit --quiet --allow-empty -m during"}}
        directory = _folder(work / "commits")
        (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        monkeypatch.chdir(_committed(directory))
        before = _git(directory, "rev-parse", "HEAD")
        result = _run()
        assert result.exit_code == 0, result.output
        after = _git(directory, "rev-parse", "HEAD")
        assert before != after
        assert self.last(result) == [
            f"acme/demo: not snapshotted: its repository moved from {before[:7]} to {after[:7]} while it was built, so no "
            f"commit says which code ran."
        ]
        assert _snapshots(store) == []

    def test_pipelines_worked_on_together(self, demo, store):
        (demo / "chartbook.links.toml").write_text("", encoding="utf-8")
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.links.toml\n", encoding="utf-8", newline="\n")
        _committed(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        (line,) = self.last(result)
        assert line.startswith("acme/demo: not snapshotted: chartbook.links.toml is in the folder")
        assert _snapshots(store) == []

    def test_a_pipeline_that_declares_nothing_is_told_nothing(self, work, store, monkeypatch):
        directory = _folder(work / "empty", {"project": {"id": "acme/empty"}, "scripts": {"build": "echo ran >> build.log"}})
        monkeypatch.chdir(_committed(directory))
        result = _run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/empty: build", "Ran build in 1 pipeline(s)."]


class TestTheStore:
    def test_one_that_is_not_there_is_made_where_its_folder_is(self, demo, store):
        assert not store.root.exists()
        assert "Snapshot made." in _run().output and store.root.is_dir()

    def test_one_whose_folder_is_not_there_either_is_not_made(self, demo, work, monkeypatch):
        """A share that is not mounted, a synced folder that is not running: no empty store is made in its place."""
        away = work / "not-mounted" / "store"
        monkeypatch.setenv(config.STORE_ENV_VAR, str(away))
        result = _run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1] == (
            f"acme/demo: not snapshotted: the store at {away} is not there, nor the folder it is in (a drive that is not "
            f"mounted, or a synced folder that is not running)."
        )
        assert not away.parent.exists() and _ran(demo) == 1

    def test_a_run_follows_the_catalog_and_asks_nothing(self, demo, work, monkeypatch):
        """With several stores a snapshot made by hand may ask which to write to; a run goes where the catalog sends the pipeline, or to the first."""
        from chartbook import backends
        from chartbook.multi_store import Stores

        monkeypatch.delenv(config.STORE_ENV_VAR)
        home = work / "home"
        home.mkdir()
        monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: home)
        for name in ("first", "second"):
            (work / name).mkdir()
        (home / "catalog.toml").write_text(tomli_w.dumps({"project": {"name": "Catalog"}, "stores": {
            "first": {"url": str(work / "first")}, "second": {"url": str(work / "second")},
        }}), encoding="utf-8", newline="\n")
        assert run._stores_by_the_catalog(Stores.configured(), "acme/demo") == ["first"]
        assert run._stores_by_the_catalog(FolderStore(work / "first"), "acme/demo") is None
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Stores: first" in result.output.splitlines()
        assert len(snapshot.all_snapshots(FolderStore(work / "first"))) == 1 and snapshot.all_snapshots(FolderStore(work / "second")) == []


class TestWhatWasDeclared:
    """A build that did not write something chartbook.toml declares is a failed run, whatever its script exited with."""

    def forgetful(self, directory: Path, **more) -> Path:
        table = {
            **DEMO,
            "dataframes": {**DEMO["dataframes"], "forgotten": {"path": "./_data/forgotten.csv", "docs": "d"}, **more},
        }
        (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        return _committed(directory)

    def test_one_thing(self, demo, store):
        self.forgetful(demo)
        result = _run()
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            "acme/demo: build",
            "Error: acme/demo: its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv). "
            "Nothing after it was run.",
        ]
        # And no snapshot of a build that went wrong
        assert _snapshots(store) == [] and _ran(demo) == 1

    def test_several(self, demo, store):
        self.forgetful(demo, also={"path": "./_data/also.csv", "docs": "d"})
        result = _run()
        assert result.exit_code == 1
        # In the order chartbook.toml declares them
        assert (
            "its build did not write 2 things chartbook.toml declares: forgotten (./_data/forgotten.csv), also (./_data/also.csv)"
        ) in result.output

    def test_the_function_says_the_same(self, demo, store):
        self.forgetful(demo)
        report = run.run(demo, echo=lambda line: None)
        assert report.failed is not None and report.exit_code == 1
        assert report.reason == "its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)"
        assert run.unwritten(demo) == [("forgotten", "./_data/forgotten.csv")]

    def test_another_script_is_not_asked_for_what_the_build_writes(self, demo, store):
        self.forgetful(demo)
        (demo / "out.csv").unlink(missing_ok=True)
        assert _run("test").exit_code == 0

    def test_every_kind_a_build_writes_is_looked_for(self, work, store, monkeypatch):
        table = {
            "project": {"id": "acme/kinds"},
            "scripts": {"build": "echo ran >> build.log"},
            "dataframes": {"table": {"path": "./_data/t.csv", "docs": "d"}},
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "table", "docs": "d"}},
            "notebooks": {"analysis": {"path": "./_output/analysis.html", "name": "Analysis", "docs": "d"}},
            "models": {"ar1": {"path": "./_models/ar1.joblib", "metrics_path": "./_models/ar1.json"}},
            "files": {"raw": {"path": "./_data/raw.txt", "docs": "d"}},
            # A page of prose is kept in git, and is no output: it is not asked of a build
            "notes": {"method": {"path": "./docs_src/method.md"}},
        }
        directory = _folder(work / "kinds", table)
        (directory / "docs_src").mkdir()
        (directory / "docs_src" / "method.md").write_text("# Method\n", encoding="utf-8", newline="\n")
        monkeypatch.chdir(_committed(directory))
        assert [name for name, _ in run.unwritten(directory)] == ["table", "curve", "analysis", "ar1", "ar1's scores", "raw"]
        result = _run()
        assert result.exit_code == 1 and "its build did not write 6 things chartbook.toml declares" in result.output

    def test_the_strict_form_fails_for_it_too(self, demo, store):
        self.forgetful(demo)
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1 and "its build did not write 1 thing" in result.output
        assert _snapshots(store) == []
