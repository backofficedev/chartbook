"""``chartbook run`` looks for what was declared, and makes a snapshot of committed work (``docs_src/design/one-command.md``).

A person types one command. While they are still editing, it builds and
says why there is no snapshot yet; once everything is committed, the same
command ends with one, which is what their other pipelines read. A build
that did not write something ``chartbook.toml`` declares is a failed run,
whatever its script exited with.

``chartbook run --snapshot`` is the strict form it was, and
``chartbook run --frozen`` makes none. A run asks nothing: not which store,
and not whether to make a catalog.
"""

import sys
from pathlib import Path

import click
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, run, snapshot
from chartbook.cli import main
from chartbook.multi_store import Stores
from chartbook.store import FolderStore, StoreError
from tests.fixtures import name_no_snapshot
from tests.test_lock_by_kind import _git

#: A build that writes the one table the manifest declares, the same bytes every time, and says that it ran
BUILD = "echo a,b > out.csv && echo ran >> build.log"
DEMO = {
    "project": {"id": "acme/demo"},
    "scripts": {"build": BUILD, "test": "echo tested >> build.log"},
    "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
}
IGNORED = "/out.csv\n/build.log\n"
MADE = "Snapshot made. A pipeline that depends on this one gets it with `chartbook update`."
COMMIT_AND_AGAIN = "  A snapshot is of a commit: commit, and `chartbook run` again."


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _write(directory: Path, table: dict) -> None:
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _folder(directory: Path, table: dict = None, ignored: str = IGNORED) -> Path:
    directory.mkdir(parents=True)
    _write(directory, table or DEMO)
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


@pytest.fixture
def upstream(work, store):
    """Another pipeline, in a repository of its own, committed and not yet built."""
    return _committed(_folder(work / "up", {**DEMO, "project": {"id": "acme/up"}}))


def _depends_on_upstream(demo: Path, **more) -> Path:
    _write(demo, {**DEMO, "dependencies": {"acme/up": {"path": "../up"}}, **more})
    return _committed(demo)


def _snapshot_of(upstream: Path, store) -> None:
    (upstream / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
    snapshot.make(upstream, store=store)


def _run(*arguments: str):
    return CliRunner().invoke(main, ["run", *arguments])


def _snapshots(store) -> list:
    return snapshot.all_snapshots(store) if store.root.is_dir() else []


def _ran(directory: Path) -> int:
    log = directory / "build.log"
    return len(log.read_text(encoding="utf-8").split()) if log.exists() else 0


def _after_the_run(result, pipelines: int = 1) -> list:
    """What a run said once it was over: the lines after ``Ran build``."""
    said = result.output.splitlines()
    return said[said.index(f"Ran build in {pipelines} pipeline(s).") + 1:]


class TestCommittedWork:
    def test_a_run_ends_with_a_snapshot(self, demo, store):
        result = _run()
        assert result.exit_code == 0, result.output
        commit = _git(demo, "rev-parse", "HEAD")
        assert result.output.splitlines() == [
            "acme/demo: build",
            f"acme/demo at {commit[:7]}: 1 asset(s) in the store",
            MADE,
            "Ran build in 1 pipeline(s).",
        ]
        (taken,) = _snapshots(store)
        assert taken.commit == commit and taken.built_by_run and taken.assets["out"]["content_hash"]

    def test_the_same_files_make_no_second_one(self, demo, store):
        assert _run().exit_code == 0
        again = _run()
        assert again.exit_code == 0, again.output
        said = again.output.splitlines()
        assert said[2].startswith("No new snapshot: the same bytes and the same pins as the one made ")
        assert said[3:] == ["Ran build in 1 pipeline(s)."]
        assert len(_snapshots(store)) == 1 and _ran(demo) == 2

    def test_a_plain_run_asks_for_no_catalog_and_makes_none(self, demo, store):
        """The catalog is made when it is looked at: a run ends with its snapshot, and with no question."""
        assert _run().exit_code == 0 and len(_snapshots(store)) == 1
        assert not config.get_global_catalog_path().exists()
        # The strict form is as it was: its snapshot makes the catalog that shows it
        (demo / "out.csv").unlink()
        _write(demo, {**DEMO, "scripts": {"build": "echo c,d > out.csv"}})
        _committed(demo)
        strict = _run("--snapshot", "--no-gc-reminder")
        assert strict.exit_code == 0, strict.output
        assert config.get_global_catalog_path().is_file()

    def test_the_function_makes_none_unless_told(self, demo, store):
        """`chartbook run` passes WHEN_COMMITTED; what calls the function decides for itself."""
        report = run.run(demo, echo=lambda line: None)
        assert report.failed is None and report.snapshots == [] and report.not_snapshotted == [] and _snapshots(store) == []
        report = run.run(demo, echo=lambda line: None, snapshot=run.WHEN_COMMITTED)
        assert report.failed is None and len(report.snapshots) == 1 and report.not_snapshotted == []

    def test_any_other_true_value_is_the_strict_form(self, demo, store):
        """As before there were three: a caller that passed 1 for True still gets its snapshot, or the refusal."""
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        with pytest.raises(run.RunError, match="not committed"):
            run.run(demo, echo=lambda line: None, snapshot=1)
        (demo / "notes.txt").unlink()
        assert len(run.run(demo, echo=lambda line: None, snapshot=1).snapshots) == 1

    def test_only_a_build_is_followed_by_one(self, demo, store):
        result = _run("test")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/demo: test", "Ran test in 1 pipeline(s)."]
        assert _snapshots(store) == []

    def test_frozen_makes_none_and_says_nothing_of_one(self, demo, store):
        result = _run("--frozen")
        assert result.exit_code == 0, result.output
        assert "snapshot" not in result.output.lower() and _snapshots(store) == [] and _ran(demo) == 1


class TestTheLockfile:
    """A snapshot is labelled with a commit, and whoever builds that commit again reads what its lockfile pins: so the lockfile is committed first."""

    WRITTEN = [
        "acme/demo: not snapshotted: chartbook.lock was written during this run, and is not committed.",
        "  A snapshot is of a commit: commit it, and `chartbook run` again.",
    ]

    def test_one_the_run_writes_is_one_more_file_to_commit(self, demo, store, upstream):
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Wrote chartbook.lock." in result.output
        assert _after_the_run(result) == self.WRITTEN
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up"] and _ran(demo) == 1
        # Commit it, and the same command ends with the snapshot, which says what it was built from
        _committed(demo)
        again = _run()
        assert again.exit_code == 0 and MADE in again.output.splitlines() and "not snapshotted" not in again.output
        (taken,) = [taken for taken in _snapshots(store) if taken.pipeline == "acme/demo"]
        assert [entry["id"] for entry in taken.inputs] == ["acme/up"]
        assert _git(demo, "status", "--porcelain") == ""

    def test_pins_moved_and_not_committed_are_work_in_progress(self, demo, store, upstream):
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        lock.pin(demo, store=store)
        _committed(demo)
        assert MADE in _run().output.splitlines()
        # The other pipeline moves on, and this one takes its newer snapshot and does not commit that
        _write(upstream, {**DEMO, "project": {"id": "acme/up", "name": "Up"}})
        (upstream / "out.csv").write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
        _committed(upstream)
        snapshot.make(upstream, store=store)
        assert CliRunner().invoke(main, ["update"]).exit_code == 0
        assert _git(demo, "status", "--porcelain") == "M chartbook.lock"
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            "acme/demo: not snapshotted: 1 file is not committed (`git status` lists them).",
            COMMIT_AND_AGAIN,
        ]
        assert len([taken for taken in _snapshots(store) if taken.pipeline == "acme/demo"]) == 1

    def test_one_that_git_ignores_holds_nothing_up(self, demo, store, upstream):
        """A project that keeps its lockfile out of git has chosen that: the snapshot records what it was built from all the same."""
        _snapshot_of(upstream, store)
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.lock\n", encoding="utf-8", newline="\n")
        _depends_on_upstream(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Wrote chartbook.lock." in result.output and MADE in result.output.splitlines()
        assert _after_the_run(result) == []

    def test_the_strict_form_passes_over_the_one_it_writes_as_it_did(self, demo, store, upstream):
        """--snapshot refuses before it builds, and cannot refuse for the lockfile its own pin is about to write."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 0, result.output
        assert MADE in result.output.splitlines()
        assert _git(demo, "status", "--porcelain") == "?? chartbook.lock"

    def test_with_upstream_the_line_comes_last(self, demo, store, upstream):
        """--upstream builds and snapshots what this one depends on first, as it did; this one's lockfile is then new."""
        _depends_on_upstream(demo)
        result = _run("--upstream")
        assert result.exit_code == 0, result.output
        assert "Snapshot made, for what depends on it in this run to pin." in result.output.splitlines()
        assert result.output.splitlines()[-2:] == self.WRITTEN
        assert [(taken.pipeline, taken.built_by_run) for taken in _snapshots(store)] == [("acme/up", True)]
        _committed(demo)
        assert MADE in _run().output.splitlines()
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up", "acme/demo"]


class TestWorkInProgress:
    """The run goes well, and its last line says why there is no snapshot."""

    def test_files_that_are_not_committed(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        _write(demo, {**DEMO, "project": {"id": "acme/demo", "name": "Demo"}})
        result = _run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            "acme/demo: build",
            "Ran build in 1 pipeline(s).",
            "acme/demo: not snapshotted: 2 files are not committed (`git status` lists them).",
            COMMIT_AND_AGAIN,
        ]
        assert _snapshots(store) == [] and _ran(demo) == 1
        # Commit, and run again: that is all
        _committed(demo)
        assert MADE in _run().output.splitlines() and len(_snapshots(store)) == 1

    def test_one_file(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        assert _after_the_run(_run())[0] == "acme/demo: not snapshotted: 1 file is not committed (`git status` lists them)."

    def test_a_folder_in_no_repository(self, work, store, monkeypatch):
        monkeypatch.chdir(_folder(work / "loose"))
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            "acme/demo: not snapshotted: this folder is in no git repository.",
            "  A snapshot is of a commit: `git init`, commit, and `chartbook run` again.",
        ]

    def test_a_git_that_will_not_read_the_repository_is_not_told_to_init(self, demo, monkeypatch):
        (step,) = [step for step in run.plan(demo, "build") if step.source == "asked"]
        real = snapshot._git

        def refusing(directory, *arguments, **more):
            if arguments[:2] == ("rev-parse", "--show-toplevel"):
                raise snapshot.SnapshotError("fatal: detected dubious ownership in repository at '/work/demo'\nTo add an exception…")
            return real(directory, *arguments, **more)

        monkeypatch.setattr(snapshot, "_git", refusing)
        assert run._why_no_snapshot_before(step) == (
            None, "git did not say which commit this is (fatal: detected dubious ownership in repository at '/work/demo')"
        )

    def test_a_repository_with_no_commit_yet(self, work, store, monkeypatch):
        directory = _folder(work / "new")
        _git(directory, "init", "--quiet", "-b", "main")
        monkeypatch.chdir(directory)
        assert _after_the_run(_run()) == ["acme/demo: not snapshotted: nothing is committed yet.", COMMIT_AND_AGAIN]

    def test_a_commit_checked_out_by_its_hash(self, demo, store):
        """An old version looked at, or built again: a snapshot of it would be the newest of its pipeline, so it is made only when asked for."""
        commit = _git(demo, "rev-parse", "HEAD")
        _git(demo, "checkout", "--quiet", "--detach")
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            f"acme/demo: not snapshotted: no branch is checked out, only the commit {commit[:7]}. "
            f"`chartbook run --snapshot` makes a snapshot of it."
        ]
        assert _snapshots(store) == []
        asked = _run("--snapshot", "--no-gc-reminder")
        assert asked.exit_code == 0 and MADE in asked.output.splitlines() and len(_snapshots(store)) == 1

    def _building(self, work, monkeypatch, more: str, name: str) -> Path:
        directory = _folder(work / name, {**DEMO, "scripts": {"build": BUILD + " && " + more}})
        (directory / "tracked.txt").write_text("kept in git\n", encoding="utf-8", newline="\n")
        monkeypatch.chdir(_committed(directory))
        return directory

    def test_a_build_that_changes_a_file_git_has(self, work, store, monkeypatch):
        self._building(work, monkeypatch, "echo more >> tracked.txt", "writes")
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            "acme/demo: not snapshotted: its build left 1 file that is not committed (changed: tracked.txt), so the commit "
            "it started at does not describe the folder.",
            "  A file a build writes belongs in .gitignore.",
        ]
        assert _snapshots(store) == []

    def test_a_build_that_writes_a_file_git_neither_has_nor_ignores(self, work, store, monkeypatch):
        """Not "a file that git tracks": it is new, and the line says so."""
        self._building(work, monkeypatch, "echo made > report.txt && echo more >> tracked.txt && echo s > state.db", "leaves")
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result)[0] == (
            "acme/demo: not snapshotted: its build left 3 files that are not committed (changed: tracked.txt; new: "
            "report.txt, state.db), so the commit it started at does not describe the folder."
        )
        assert _snapshots(store) == []

    def test_a_commit_made_while_it_was_built(self, work, store, monkeypatch):
        directory = self._building(work, monkeypatch, "git commit --quiet --allow-empty -m during", "commits")
        before = _git(directory, "rev-parse", "HEAD")
        result = _run()
        assert result.exit_code == 0, result.output
        after = _git(directory, "rev-parse", "HEAD")
        assert before != after
        assert _after_the_run(result) == [
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
        assert _after_the_run(result) == [
            "acme/demo: not snapshotted: chartbook.links.toml is in the folder, so its build reads other pipelines' working folders.",
            # Each command it names is one that exists
            "  Remove it, `chartbook update`, and `chartbook run` again.",
        ]
        assert _snapshots(store) == []

    def test_pins_that_do_not_account_for_what_it_read(self, demo, store, upstream):
        """A gap in its lineage: built all the same, and told. The strict form refuses before it builds."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        lock.pin(demo, store=store)
        name_no_snapshot(demo, "acme/up")  # as in a lockfile changed by hand
        _committed(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        after = _after_the_run(result)
        assert after[0] == "acme/demo: not snapshotted: its pins do not account for every dependency:"
        assert after[1].startswith("  acme/up: its pin names no snapshot")
        assert _ran(demo) == 1 and [taken.pipeline for taken in _snapshots(store)] == ["acme/up"]
        strict = _run("--snapshot", "--no-gc-reminder")
        assert strict.exit_code == 1 and _ran(demo) == 1

    def test_a_folder_that_changes_while_what_it_depends_on_is_built(self, demo, store, work):
        """Asked before the run, and again at its turn: what changed in between is told as what it is, and not blamed on its own build."""
        _committed(_folder(work / "up", {
            **DEMO, "project": {"id": "acme/up"}, "scripts": {"build": BUILD + " && echo stray > ../demo/stray.txt"},
        }))
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.lock\n", encoding="utf-8", newline="\n")
        _depends_on_upstream(demo)
        result = _run("--upstream")
        assert result.exit_code == 0, result.output
        # Last of all, after what --upstream says of the catalog its snapshots show in
        assert result.output.splitlines()[-2:] == [
            "acme/demo: not snapshotted: 1 file is not committed (`git status` lists them).",
            COMMIT_AND_AGAIN,
        ]
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up"]

    def test_a_commit_made_while_what_it_depends_on_is_built(self, demo, store, work):
        _committed(_folder(work / "up", {
            **DEMO, "project": {"id": "acme/up"},
            "scripts": {"build": BUILD + " && git -C ../demo commit --quiet --allow-empty -m meanwhile"},
        }))
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.lock\n", encoding="utf-8", newline="\n")
        _depends_on_upstream(demo)
        before = _git(demo, "rev-parse", "HEAD")
        result = _run("--upstream")
        assert result.exit_code == 0, result.output
        after = _git(demo, "rev-parse", "HEAD")
        assert result.output.splitlines()[-1] == (
            f"acme/demo: not snapshotted: its repository moved from {before[:7]} to {after[:7]} before its turn came."
        )


class TestAPipelineThatDeclaresNothing:
    """There is nothing of it to take a snapshot of, so it is told nothing of snapshots, whatever state its folder is in."""

    QUIET = ["acme/empty: build", "Ran build in 1 pipeline(s)."]

    @pytest.fixture
    def empty(self, work, store, monkeypatch):
        directory = _folder(work / "empty", {"project": {"id": "acme/empty"}, "scripts": {"build": "echo ran >> build.log"}})
        monkeypatch.chdir(directory)
        return directory

    def test_in_no_repository(self, empty, store):
        """Not told to `git init` and commit, which would lead to no snapshot either."""
        assert _run().output.splitlines() == self.QUIET

    def test_committed(self, empty, store):
        _committed(empty)
        result = _run()
        assert result.exit_code == 0 and result.output.splitlines() == self.QUIET
        assert not store.root.exists()  # and no store is made for nothing

    def test_with_work_that_is_not_committed(self, empty, store):
        _committed(empty)
        (empty / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        assert _run().output.splitlines() == self.QUIET

    def test_at_a_commit_checked_out_by_its_hash(self, empty, store):
        _committed(empty)
        _git(empty, "checkout", "--quiet", "--detach")
        assert _run().output.splitlines() == self.QUIET

    def test_one_whose_tables_are_all_in_a_source_is_told_what_is_missing(self, work, store, monkeypatch):
        """It declares something a snapshot holds, and its build made none of it: said, and not passed over in silence."""
        directory = _folder(work / "tables", {
            "project": {"id": "acme/tables"},
            "scripts": {"build": "echo ran >> build.log"},
            "sources": {"local": {"backend": "duckdb", "url": "duckdb:///_data/never.duckdb"}},
            "dataframes": {"curve": {"source": "local", "table": "curve", "docs": "d"}},
        })
        monkeypatch.chdir(_committed(directory))
        assert run.unwritten(directory) == []  # a table in a source has no file of its own for a build to write
        result = _run()
        assert result.exit_code == 0, result.output
        (line,) = _after_the_run(result)
        assert line.startswith("acme/tables: not snapshotted: nothing it declares is there to take: acme/tables:curve (table curve in source 'local'")
        assert _snapshots(store) == []


class TestTheStore:
    def test_one_that_is_not_there_is_made_where_its_folder_is(self, demo, store):
        assert not store.root.exists()
        assert MADE in _run().output.splitlines() and store.root.is_dir()

    def test_one_whose_folder_is_not_there_either_is_not_made(self, demo, work, monkeypatch):
        """A share that is not mounted, a synced folder that is not running: no empty store is made in its place."""
        away = work / "not-mounted" / "store"
        monkeypatch.setenv(config.STORE_ENV_VAR, str(away))
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            f"acme/demo: not snapshotted: The store at {away} is not there, nor the folder it is in (a drive that is not "
            f"mounted, or a synced folder that is not running). Nothing is made in its place: for a new store there, make "
            f"the folder {away.parent} first."
        ]
        assert not away.parent.exists() and _ran(demo) == 1

    def test_nor_by_the_pin_before_the_build(self, demo, work, store, upstream, monkeypatch):
        """Found by review: a pipeline with a dependency made the store while it pinned, and then wrote its snapshot there."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        lock.pin(demo, store=store)
        _committed(demo)
        away = work / "not-mounted" / "store"
        monkeypatch.setenv(config.STORE_ENV_VAR, str(away))
        result = _run()
        assert result.exit_code == 1  # what it reads is in that store: nothing can be built
        assert "is not there, nor the folder it is in" in result.output
        assert not away.parent.exists() and _ran(demo) == 0

    def test_nor_by_anything_else_that_writes_a_store(self, work, monkeypatch):
        away = FolderStore(work / "not-mounted" / "store")
        for writing in (
            lambda: away.begin("acme/demo", "0" * 40, "2026-01-01T00:00:00.000000Z"),
            lambda: away.add_root(work / "chartbook.lock", []),
        ):
            with pytest.raises(StoreError, match="is not there, nor the folder it is in"):
                writing()
        assert not (work / "not-mounted").exists()
        # A store that is only read is not made, and says nothing
        assert away.all_snapshot_files() == []

    def test_the_users_own_is_always_made(self, work):
        """Under ~/.chartbook, which no drive and no sync holds: its folders are ChartBook's to make."""
        own = FolderStore(config.get_global_config_dir() / "deep" / "store")
        assert own.is_users_own() and not own.root.parent.exists()
        own.add_root(work / "chartbook.lock", [])
        assert (own.root / "store.json").is_file()


class TestSeveralStores:
    @pytest.fixture
    def stores(self, demo, work, monkeypatch):
        """A catalog of two stores that can be written; the pipeline is sent to neither by name."""
        from chartbook import backends

        monkeypatch.delenv(config.STORE_ENV_VAR)
        home = work / "home"
        home.mkdir()
        monkeypatch.setattr(config, "get_global_config_dir", lambda: home)
        monkeypatch.setattr(backends, "get_global_config_dir", lambda: home)
        for name in ("first", "second"):
            (work / name).mkdir()

        def catalog(**definitions):
            (home / "catalog.toml").write_text(
                tomli_w.dumps({"project": {"name": "Catalog"}, "stores": definitions}), encoding="utf-8", newline="\n"
            )

        catalog(first={"url": str(work / "first")}, second={"url": str(work / "second")})
        return catalog

    def _in(self, work, name: str) -> list:
        return [taken.pipeline for taken in snapshot.all_snapshots(FolderStore(work / name))]

    def test_a_run_goes_to_the_first_and_says_which(self, stores, demo, work):
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Stores: first" in result.output.splitlines()
        assert self._in(work, "first") == ["acme/demo"] and self._in(work, "second") == []

    def test_a_run_asks_nothing_at_a_terminal(self, stores, demo, work, monkeypatch):
        """A snapshot made by hand may ask which store a new pipeline goes to. A run does not, plain or strict."""
        class Asked(Exception):
            pass

        class Terminal:
            def isatty(self):
                return True

        def prompt(*arguments, **more):
            raise Asked()

        monkeypatch.setattr(sys, "stdin", Terminal())
        monkeypatch.setattr(click, "prompt", prompt)
        with pytest.raises(Asked):  # the question is there to be asked, so the next lines show a run does not ask it
            snapshot.make(demo)
        report = run.run(demo, echo=lambda line: None, snapshot=run.WHEN_COMMITTED)
        assert len(report.snapshots) == 1 and report.not_snapshotted == []
        (demo / "out.csv").unlink()
        _write(demo, {**DEMO, "scripts": {"build": "echo c,d > out.csv"}})
        _committed(demo)
        assert len(run.run(demo, echo=lambda line: None, snapshot=True).snapshots) == 1
        assert self._in(work, "first") == ["acme/demo", "acme/demo"] and self._in(work, "second") == []

    def test_a_store_that_is_only_read_is_passed_over(self, stores, demo, work):
        """A class's store ahead of one's own: one's own work goes to one's own, and no run is stopped for it."""
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        assert [str(target) for target in Stores.configured().for_writing("acme/demo")] == [str(work / "second")]
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Stores: second" in result.output.splitlines() and "not snapshotted" not in result.output
        assert self._in(work, "first") == [] and self._in(work, "second") == ["acme/demo"]

    def test_with_none_that_can_be_written_the_run_says_so(self, stores, demo, work):
        stores(first={"url": str(work / "first"), "read_only": True})
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == ["acme/demo: not snapshotted: Store 'first' is read-only."]

    def test_one_written_and_one_not_is_not_called_no_snapshot(self, stores, demo, work, monkeypatch):
        """Found by review: "not snapshotted", of a snapshot that was in the first of its two stores."""
        from chartbook import transfer

        stores(
            first={"url": str(work / "first"), "pipelines": ["acme/demo"]},
            second={"url": str(work / "second"), "pipelines": ["acme/demo"]},
        )

        def failing(*arguments, **more):
            raise StoreError("the disk is full")

        monkeypatch.setattr(transfer, "copy_snapshot", failing)
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [
            f"acme/demo: not snapshotted: not in every store it goes to. Snapshot written to {work / 'first'}, but copy to "
            f"{work / 'second'} failed: the disk is full. Rerun the snapshot to finish the remaining copies."
        ]
        assert self._in(work, "first") == ["acme/demo"]


class TestWhatWasDeclared:
    """A build that did not write something chartbook.toml declares is a failed run, whatever its script exited with."""

    def forgetful(self, directory: Path, **more) -> Path:
        _write(directory, {
            **DEMO,
            "dataframes": {**DEMO["dataframes"], "forgotten": {"path": "./_data/forgotten.csv", "docs": "d"}, **more},
        })
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
        assert (
            "its build did not write 2 things chartbook.toml declares: also (./_data/also.csv), forgotten (./_data/forgotten.csv)"
        ) in result.output

    def test_the_function_says_the_same(self, demo, store):
        self.forgetful(demo)
        report = run.run(demo, echo=lambda line: None)
        assert report.failed is not None and report.exit_code == 1
        assert report.reason == "its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)"
        assert run.unwritten(demo) == [("forgotten", "./_data/forgotten.csv")]

    def test_a_manifest_a_docs_build_would_refuse_is_asked_all_the_same(self, demo, store):
        """Found by review: an entry with no docs made the look fail in silence, and a snapshot was made with the output missing."""
        _write(demo, {**DEMO, "dataframes": {"out": {"path": "./out.csv"}, "forgotten": {"path": "./forgotten.csv"}}})
        _committed(demo)
        result = _run()
        assert result.exit_code == 1 and "its build did not write 1 thing" in result.output
        assert run.unwritten(demo) == [("forgotten", "./forgotten.csv")]
        assert _snapshots(store) == []

    def test_a_folder_with_nothing_in_it_is_not_written(self, work, store, monkeypatch):
        """Asked as a snapshot asks it: a folder is there when it holds a file. Found by review: such a run ended with no snapshot and no word."""
        directory = _folder(work / "parts", {
            "project": {"id": "acme/parts"}, "scripts": {"build": "mkdir -p _data/parts"},
            "dataframes": {"parts": {"path": "./_data/parts", "docs": "d"}},
        }, ignored="/_data/\n")
        monkeypatch.chdir(_committed(directory))
        result = _run()
        assert result.exit_code == 1
        assert "Error: acme/parts: its build did not write 1 thing chartbook.toml declares: parts (./_data/parts)." in result.output

    def test_a_pattern_that_matches_nothing_is_not_written(self, demo):
        _write(demo, {**DEMO, "files": {"logs": {"path": "./_data/*.log", "docs": "d"}}})
        assert run.unwritten(demo) == [("out", "./out.csv"), ("file/logs", "./_data/*.log")]
        (demo / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
        (demo / "_data").mkdir()
        (demo / "_data" / "one.log").write_text("x\n", encoding="utf-8", newline="\n")
        assert run.unwritten(demo) == []

    def test_another_script_is_not_asked_for_what_the_build_writes(self, demo, store):
        self.forgetful(demo)
        (demo / "out.csv").unlink(missing_ok=True)
        assert _run("test").exit_code == 0

    def test_every_kind_a_build_writes_is_looked_for(self, work, store, monkeypatch):
        table = {
            "project": {"id": "acme/kinds"},
            "scripts": {"build": "echo ran >> build.log"},
            "sources": {"local": {"backend": "duckdb", "url": "duckdb:///_data/never.duckdb"}},
            "dataframes": {
                "table": {"path": "./_data/t.csv", "docs": "d"},
                # A table in a source has no file of its own: not asked of a build
                "in_source": {"source": "local", "table": "t", "docs": "d"},
            },
            "charts": {"curve": {"path": "./_output/curve.html", "dataframe": "table", "docs": "d"}},
            "notebooks": {"analysis": {"path": "./_output/analysis.html", "name": "Analysis", "docs": "d"}},
            "models": {"ar1": {"path": "./_models/ar1.joblib", "metrics_path": "./_models/ar1.json"}},
            "files": {"raw": {"path": "./_data/raw.txt", "docs": "d"}},
            # A page of prose is kept in git, and no build writes it: not asked of one, there or not
            "notes": {"method": {"path": "./docs_src/method.md"}},
        }
        directory = _folder(work / "kinds", table)
        monkeypatch.chdir(_committed(directory))
        assert not (directory / "docs_src").exists()
        assert run.unwritten(directory) == [
            ("table", "./_data/t.csv"), ("chart/curve", "./_output/curve.html"), ("notebook/analysis", "./_output/analysis.html"),
            ("model/ar1", "./_models/ar1.joblib"), ("file/raw", "./_data/raw.txt"), ("model/ar1's scores", "./_models/ar1.json"),
        ]
        result = _run()
        assert result.exit_code == 1 and "its build did not write 6 things chartbook.toml declares" in result.output

    @pytest.mark.parametrize("flags", [["--snapshot", "--no-gc-reminder"], ["--frozen"], ["--remake"]])
    def test_every_form_of_a_build_fails_for_it(self, demo, store, flags):
        self.forgetful(demo)
        result = _run(*flags)
        assert result.exit_code == 1, result.output
        assert "its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)" in result.output
        assert _snapshots(store) == [] and _ran(demo) == 1

    def test_an_upstream_that_forgot_an_output_stops_the_run(self, demo, store, work):
        _committed(_folder(work / "up", {
            **DEMO, "project": {"id": "acme/up"},
            "dataframes": {**DEMO["dataframes"], "forgotten": {"path": "./forgotten.csv", "docs": "d"}},
        }))
        _depends_on_upstream(demo)
        result = _run("--upstream")
        assert result.exit_code == 1
        assert (
            "Error: acme/up: its build did not write 1 thing chartbook.toml declares: forgotten (./forgotten.csv). "
            "Nothing after it was run."
        ) in result.output
        assert _snapshots(store) == [] and _ran(demo) == 0
