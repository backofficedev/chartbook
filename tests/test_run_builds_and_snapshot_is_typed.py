"""``chartbook run`` builds, and ``chartbook snapshot`` is typed (``docs_src/design/one-command.md``).

A run pins what the pipeline reads, runs its build and looks for what
``chartbook.toml`` declares: a build that did not write something declared
is a failed run, whatever its script exited with. It makes no snapshot, in
whatever state the folder is, and its last line names the command that
does. ``chartbook snapshot`` takes what the build left on disk, once
everything is committed. ``chartbook run --snapshot`` is the two in one
command, as it was.

For two days a run ended with a snapshot wherever everything was committed.
That was taken back on 2026-11-20, and the tests of it with it.
"""

import os
import shlex
import sys
from pathlib import Path

import click
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, missing, run, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.fixtures import name_no_snapshot
from tests.snapshot_lines import MADE_FOR_THIS_RUN, PIN_UPDATE, made_at, said_made
from tests.test_lock_by_kind import _git

#: A build that writes the one table the manifest declares, the same bytes every time, and says that it ran
BUILD = "echo a,b > out.csv && echo ran >> build.log"
DEMO = {
    "project": {"id": "acme/demo"},
    "scripts": {"build": BUILD, "test": "echo tested >> build.log"},
    "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
}
IGNORED = "/out.csv\n/build.log\n"
#: The two lines a snapshot that is made ends with are matched, not compared: the first carries a count of files and a size
#: (tests/snapshot_lines.py; tests/test_snapshot_decides.py holds each form of them to the byte)

posix = pytest.mark.skipif(os.name == "nt", reason="the build script here is POSIX shell")


def _closing(pipeline: str = "acme/demo", where: str = "") -> list:
    """The last two lines of a run that built and was not asked for a snapshot."""
    return [f"{pipeline}: built.", f"  For other pipelines and the catalog: commit, then `chartbook snapshot{where}`."]


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


@pytest.fixture
def stores(demo, work, monkeypatch):
    """A catalog of two stores that can be written; the pipeline is sent to neither by name. Called, it writes the catalog again."""
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


def _stored(work: Path, name: str) -> list:
    """The pipelines with a snapshot in one of the catalog's two stores."""
    return [taken.pipeline for taken in snapshot.all_snapshots(FolderStore(work / name))]


def _depends_on_upstream(demo: Path, **more) -> Path:
    _write(demo, {**DEMO, "dependencies": {"acme/up": {"path": "../up"}}, **more})
    return _committed(demo)


def _snapshot_of(upstream: Path, store) -> None:
    (upstream / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
    snapshot.make(upstream, store=store)


def _run(*arguments: str):
    return CliRunner().invoke(main, ["run", *arguments])


def _snapshot(*arguments: str):
    return CliRunner().invoke(main, ["snapshot", "--no-gc-reminder", *arguments])


def _snapshots(store) -> list:
    return snapshot.all_snapshots(store) if store.root.is_dir() else []


def _ran(directory: Path) -> int:
    log = directory / "build.log"
    return len(log.read_text(encoding="utf-8").split()) if log.exists() else 0


def _after_the_run(result, pipelines: int = 1) -> list:
    """What a run said once it was over: the lines after ``Ran build``."""
    said = result.output.splitlines()
    return said[said.index(f"Ran build in {pipelines} pipeline(s).") + 1:]


class TestARunMakesNoSnapshot:
    """It builds, and says in its last two lines what makes the build available to other pipelines and the catalog. The same lines, whatever state the folder is in."""

    def test_of_committed_work(self, demo, store):
        result = _run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/demo: build", "Ran build in 1 pipeline(s).", *_closing()]
        assert "\n".join(_closing()) in result.stdout and result.stderr == ""  # no failure, and not said as one
        assert all(len(line) <= 80 for line in _closing())  # each fits a terminal of eighty
        assert _snapshots(store) == [] and _ran(demo) == 1
        # Nothing of what it built is put in a store, and no store or catalog is made for it
        assert not store.root.exists() and not config.get_global_catalog_path().exists()

    def test_it_waits_for_nobody(self, demo, store, monkeypatch):
        """Builds that end in a snapshot of one folder take turns. A plain run ends in none, and takes no turn."""
        waited = []
        real = run._alone_while_built

        def watched(step, echo, snapshotted):
            waited.append(bool(snapshotted))
            return real(step, echo, snapshotted)

        monkeypatch.setattr(run, "_alone_while_built", watched)
        assert _run().exit_code == 0 and waited == [False]
        assert _run("--snapshot", "--no-gc-reminder").exit_code == 0 and waited == [False, True]

    def test_however_often_it_is_run(self, demo, store):
        for _ in range(3):
            assert _after_the_run(_run()) == _closing()
        assert _snapshots(store) == [] and _ran(demo) == 3

    def test_of_work_that_is_not_committed(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        _write(demo, {**DEMO, "project": {"id": "acme/demo", "name": "Demo"}})
        result = _run()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/demo: build", "Ran build in 1 pipeline(s).", *_closing()]
        assert _snapshots(store) == []

    def test_in_a_folder_in_no_repository(self, work, store, monkeypatch):
        monkeypatch.chdir(_folder(work / "loose"))
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing()

    def test_in_a_repository_with_no_commit_yet(self, work, store, monkeypatch):
        directory = _folder(work / "new")
        _git(directory, "init", "--quiet", "-b", "main")
        monkeypatch.chdir(directory)
        assert _after_the_run(_run()) == _closing()

    def test_at_a_commit_checked_out_by_its_hash(self, demo, store):
        _git(demo, "checkout", "--quiet", "--detach")
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing() and _snapshots(store) == []

    def test_of_a_build_that_leaves_files_git_does_not_have(self, work, store, monkeypatch):
        directory = _folder(work / "leaves", {**DEMO, "scripts": {"build": BUILD + " && echo made > report.txt && echo more >> tracked.txt"}})
        (directory / "tracked.txt").write_text("kept in git\n", encoding="utf-8", newline="\n")
        monkeypatch.chdir(_committed(directory))
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing() and _snapshots(store) == []

    def test_with_pipelines_worked_on_together(self, demo, store):
        (demo / "chartbook.links.toml").write_text("", encoding="utf-8")
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.links.toml\n", encoding="utf-8", newline="\n")
        _committed(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing() and _snapshots(store) == []

    def test_it_asks_nothing_that_only_a_snapshot_asks(self, demo, store, monkeypatch):
        """The line is not chosen by what is committed or by what the store holds: what stands in a snapshot's way is the snapshot's to say."""
        def asked(*arguments, **more):
            raise AssertionError("a plain run asked what only a snapshot asks")

        for name in ("make", "require_committed", "check_within", "lineage_gaps"):
            monkeypatch.setattr(snapshot, name, asked)
        result = _run()
        assert result.exit_code == 0 and result.exception is None, result.output
        assert _after_the_run(result) == _closing()

    def test_only_a_build_is_followed_by_the_line(self, demo, store):
        result = _run("test")
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["acme/demo: test", "Ran test in 1 pipeline(s)."]
        assert _snapshots(store) == []

    def test_frozen_is_told_nothing_of_snapshots(self, demo, store):
        """For CI, and for a store one may only read: a snapshot is not what comes next there."""
        result = _run("--frozen")
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == [] and "snapshot" not in result.output.lower()
        assert _snapshots(store) == [] and _ran(demo) == 1
        # The function says what was built all the same: it is the command that does not say it
        assert [step.id for step in run.run(demo, frozen=True, echo=lambda line: None).to_snapshot] == ["acme/demo"]

    def test_a_pipeline_named_from_another_folder_is_named_in_the_command(self, demo, store, work, monkeypatch):
        monkeypatch.chdir(work)
        result = _run("--project-dir", str(demo))
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing(where=f" --project-dir {missing._quoted(demo)}")

    def test_a_folder_whose_name_a_shell_would_split_is_quoted(self, work, store, monkeypatch):
        directory = _committed(_folder(work / "my demo"))
        monkeypatch.chdir(work)
        result = _run("--project-dir", str(directory))
        assert result.exit_code == 0, result.output
        # As this system's shell takes it: `'/work/my demo'`, and `"C:\work\my demo"` at a prompt of cmd.exe
        quoted = missing._quoted(directory)
        assert quoted != str(directory) and quoted[0] == quoted[-1] and quoted[0] in "'\""
        assert _after_the_run(result) == _closing(where=f" --project-dir {quoted}")

    @posix
    def test_the_command_it_names_makes_the_snapshot(self, work, store, monkeypatch):
        """Typed as the line gives it, from the folder the run was typed in. (Split here as a POSIX shell splits it.)"""
        directory = _committed(_folder(work / "my demo"))
        monkeypatch.chdir(work)
        line = _after_the_run(_run("--project-dir", str(directory)))[-1]
        words = shlex.split(line[line.index("`") + 1:line.rindex("`")])
        assert words[:2] == ["chartbook", "snapshot"]
        made = CliRunner().invoke(main, [*words[1:], "--no-gc-reminder"])
        assert made.exit_code == 0 and said_made(made.output)
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/demo"]

    def test_the_function_reports_what_it_built_and_did_not_snapshot(self, demo, store):
        report = run.run(demo, echo=lambda line: None)
        assert report.failed is None and report.snapshots == [] and _snapshots(store) == []
        assert [step.id for step in report.to_snapshot] == ["acme/demo"]
        # Asked for a snapshot, it makes one and has none left to name
        report = run.run(demo, echo=lambda line: None, snapshot=True)
        assert len(report.snapshots) == 1 and report.to_snapshot == []
        # And another script is no build
        assert run.run(demo, "test", echo=lambda line: None).to_snapshot == []

    def test_a_git_dependency_the_run_builds_is_not_named(self, work, store, monkeypatch):
        """ChartBook's own copy of a repository is nobody's folder to snapshot from. What the run built of it is pinned, and the lines are of the pipeline asked for."""
        _committed(_folder(work / "ref", {**DEMO, "project": {"id": "acme/ref"}}))
        (work / "top").mkdir()
        top = _folder(work / "top" / "pipeline", {**DEMO, "dependencies": {"ref": {"git": "../../ref"}}})
        _committed(work / "top")
        monkeypatch.chdir(top)
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result, pipelines=2) == _closing()
        assert [taken.pipeline for taken in _snapshots(store)] == []

    def test_with_upstream_what_it_reads_is_snapshotted_and_it_is_not(self, demo, store, upstream):
        """--upstream builds and snapshots what this one depends on first, as it did, for this run to pin. The pipeline asked for is built."""
        _depends_on_upstream(demo)
        result = _run("--upstream")
        assert result.exit_code == 0, result.output
        assert any(MADE_FOR_THIS_RUN.fullmatch(line) for line in result.output.splitlines()) and PIN_UPDATE not in result.output
        assert result.output.splitlines()[-2:] == _closing()  # last of all, after what is said of the catalog
        assert [(taken.pipeline, taken.built_by_run) for taken in _snapshots(store)] == [("acme/up", True)]

    def test_pins_that_do_not_account_for_what_it_read_stop_a_snapshot_and_not_a_build(self, demo, store, upstream):
        """A gap in its lineage is a snapshot's to refuse. The run that is asked for one refuses before it builds."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        lock.pin(demo, store=store)
        name_no_snapshot(demo, "acme/up")  # as in a lockfile changed by hand
        _committed(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing() and _ran(demo) == 1
        strict = _run("--snapshot", "--no-gc-reminder")
        assert strict.exit_code == 1 and _ran(demo) == 1
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up"]


class TestAPipelineThatDeclaresNothing:
    """There is nothing of it for a snapshot to take, so it is told nothing of snapshots, whatever state its folder is in."""

    QUIET = ["acme/empty: build", "Ran build in 1 pipeline(s)."]

    @pytest.fixture
    def empty(self, work, store, monkeypatch):
        directory = _folder(work / "empty", {"project": {"id": "acme/empty"}, "scripts": {"build": "echo ran >> build.log"}})
        monkeypatch.chdir(directory)
        return directory

    def test_in_no_repository(self, empty, store):
        assert _run().output.splitlines() == self.QUIET

    def test_committed(self, empty, store):
        _committed(empty)
        result = _run()
        assert result.exit_code == 0 and result.output.splitlines() == self.QUIET
        assert not store.root.exists()  # and no store is made for nothing
        assert run.run(empty, echo=lambda line: None).to_snapshot == []

    def test_with_work_that_is_not_committed(self, empty, store):
        _committed(empty)
        (empty / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        assert _run().output.splitlines() == self.QUIET

    def test_one_whose_tables_are_all_in_a_source_fails_for_the_file_its_build_did_not_write(self, work, store, monkeypatch):
        """Found by review: once the check stopped failing for a DuckDB file that is not there, nothing did. It is what the build writes, and a run looks for it."""
        directory = _folder(work / "tables", {
            "project": {"id": "acme/tables"},
            "scripts": {"build": "echo ran >> build.log"},
            "sources": {"local": {"backend": "duckdb", "url": "duckdb:///_data/never.duckdb"}},
            "dataframes": {"curve": {"source": "local", "table": "curve", "docs": "d"}},
        })
        monkeypatch.chdir(_committed(directory))
        # The table has no file of its own; the file of its source is the build's to write
        assert run.unwritten(directory) == [("source local", "./_data/never.duckdb")]
        result = _run()
        assert result.exit_code == 1
        assert (
            "Error: acme/tables: its build did not write 1 thing chartbook.toml declares: source local (./_data/never.duckdb). "
            "Nothing after it was run."
        ) in result.output.splitlines()
        assert "built." not in result.output and "chartbook snapshot" not in result.output and _snapshots(store) == []

    def test_which_sources_files_a_build_is_asked_for(self, work, store, monkeypatch):
        """A DuckDB file, wherever it is said to be; not a database in memory, not a warehouse, and not a source that does not read, which takes no other with it."""
        directory = _folder(work / "sources", {
            "project": {"id": "acme/sources"},
            "scripts": {"build": "echo ran >> build.log"},
            "sources": {
                "here": {"backend": "duckdb", "url": "duckdb:///_data/here.duckdb"},
                "elsewhere": {"backend": "duckdb", "url": f"duckdb:///{(work / 'elsewhere.duckdb').as_posix()}"},
                "memory": {"backend": "duckdb", "url": "duckdb:///:memory:"},
                "refused": {"backend": "duckdb", "url": "duckdb:///_data/x.duckdb?access_mode=read_only"},
            },
        })
        expected = [("source elsewhere", str(work / "elsewhere.duckdb")), ("source here", "./_data/here.duckdb")]
        assert run.unwritten(directory) == expected
        # Found by review: named by a relative folder, the file was looked for under the folder's name twice
        monkeypatch.chdir(work)
        assert run.unwritten("sources") == expected
        (directory / "_data").mkdir()
        (directory / "_data" / "here.duckdb").write_bytes(b"")
        (work / "elsewhere.duckdb").write_bytes(b"")
        assert run.unwritten("sources") == [] and run.unwritten(directory) == []

    def test_one_whose_tables_are_in_a_source_declares_something_a_snapshot_holds(self, work, store, monkeypatch):
        """Its source's file is there, and holds no such table. The run is told what makes a snapshot, and the snapshot says what is missing."""
        import duckdb

        directory = _folder(work / "tables", {
            "project": {"id": "acme/tables"},
            "scripts": {"build": "echo ran >> build.log"},
            "sources": {"local": {"backend": "duckdb", "url": "duckdb:///local.duckdb"}},
            "dataframes": {"curve": {"source": "local", "table": "curve", "docs": "d"}},
        }, ignored=IGNORED + "/local.duckdb\n")
        duckdb.connect(str(directory / "local.duckdb")).close()  # a database with no table in it
        monkeypatch.chdir(_committed(directory))
        assert run.unwritten(directory) == []
        result = _run()
        assert result.exit_code == 0, result.output
        assert _after_the_run(result) == _closing("acme/tables")
        typed = _snapshot()
        assert typed.exit_code == 1 and _snapshots(store) == []
        said = typed.output.splitlines()
        assert said[0] == (
            "Error: acme/tables has built nothing it declares, so there is nothing to take a snapshot of. "
            "Build it first: `chartbook run`."
        )
        # One line for the table, whatever the engine's own message runs to
        assert len(said) == 2 and said[1].endswith(")")
        assert said[1].startswith("  not built: acme/tables:curve (table curve in source 'local'")


class TestASnapshotIsTyped:
    """`chartbook snapshot` takes what the build left on disk, once everything is committed. It builds nothing."""

    def test_of_what_a_run_left_on_disk(self, demo, store):
        assert _run().exit_code == 0
        commit = _git(demo, "rev-parse", "HEAD")
        result = _snapshot()
        assert result.exit_code == 0, result.output
        # First what is in the store, then the two lines that say a snapshot was made
        assert result.output.splitlines()[0] == f"acme/demo at {commit[:7]}: 1 asset(s) in the store"
        assert made_at(result.output.splitlines()) == 1
        (taken,) = _snapshots(store)
        assert taken.commit == commit and taken.assets["out"]["content_hash"]
        # Nothing was built again, and its record does not say that ChartBook ran the build: it took the person's word
        assert _ran(demo) == 1 and not taken.built_by_run

    def test_the_same_files_make_no_second_one(self, demo, store):
        assert _run().exit_code == 0 and _snapshot().exit_code == 0
        assert _run().exit_code == 0
        again = _snapshot()
        assert again.exit_code == 0, again.output
        assert again.output.splitlines()[1].startswith("No new snapshot: the same bytes and the same pins as the one made ")
        assert len(_snapshots(store)) == 1 and _ran(demo) == 2

    def test_not_of_work_that_is_not_committed(self, demo, store):
        assert _run().exit_code == 0
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        result = _snapshot()
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            "Error: acme/demo has changes that are not committed:",
            "  ?? notes.txt",
            "A snapshot is labelled with the commit it was built from, so everything in the pipeline's folder must be committed first.",
        ]
        assert _snapshots(store) == []

    def test_with_nothing_built_it_names_each_thing(self, demo, store):
        """A run that built says only that this command makes a snapshot, so what is not there to take is said here."""
        result = _snapshot()
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            "Error: acme/demo has built nothing it declares, so there is nothing to take a snapshot of. Build it first: `chartbook run`.",
            "  not built: acme/demo:out (./out.csv)",
        ]

    def test_the_lockfile_a_run_wrote_is_one_more_file_to_commit(self, demo, store, upstream):
        """A snapshot is labelled with a commit, and whoever builds that commit again reads what its lockfile pins."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        result = _run()
        assert result.exit_code == 0, result.output
        assert "Wrote chartbook.lock." in result.output and _after_the_run(result) == _closing()
        refused = _snapshot()
        assert refused.exit_code == 1
        assert refused.output.splitlines() == [
            "Error: acme/demo has changes that are not committed:",
            "  ?? chartbook.lock",
            "A snapshot is labelled with the commit it was built from, so everything in the pipeline's folder must be committed first.",
            # Its owner commits it. In a clone at a commit somebody else pinned, a commit would be one nobody else has
            "  Only chartbook.lock is not committed: commit it. Or, at a commit somebody else pinned, `chartbook run "
            "--snapshot`, which builds and takes its snapshot with the lockfile as it is.",
        ]
        assert refused.output.splitlines()[-1] in refused.stderr and "Only chartbook.lock" not in refused.stdout
        assert [taken.pipeline for taken in _snapshots(store)] == ["acme/up"]
        # With anything else beside it, that is not the advice
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        both = _snapshot()
        assert both.exit_code == 1 and "Only chartbook.lock" not in both.output
        (demo / "notes.txt").unlink()
        # Typed from another folder, the command it names says which pipeline
        os.chdir(demo.parent)
        try:
            elsewhere = _snapshot("--project-dir", str(demo))
        finally:
            os.chdir(demo)
        assert f"`chartbook run --snapshot --project-dir {missing._quoted(demo)}`, which builds" in elsewhere.output.splitlines()[-1]
        _committed(demo)
        made = _snapshot()
        assert made.exit_code == 0 and said_made(made.output)
        (taken,) = [taken for taken in _snapshots(store) if taken.pipeline == "acme/demo"]
        assert [entry["id"] for entry in taken.inputs] == ["acme/up"] and _ran(demo) == 1

    def test_a_lockfile_that_was_removed_is_not_one_to_commit(self, demo, store, upstream):
        """Found by review: "commit it" committed the deletion, and the run it named pinned again from nothing."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        assert _run().exit_code == 0
        _committed(demo)
        (demo / "chartbook.lock").unlink()
        result = _snapshot()
        assert result.exit_code == 1 and "   D chartbook.lock" in result.output.splitlines()
        assert "Only chartbook.lock" not in result.output

    def test_a_file_of_that_name_in_a_folder_below_is_not_the_lockfile(self, demo, store):
        (demo / "sub").mkdir()
        (demo / "sub" / "chartbook.lock").write_text("x\n", encoding="utf-8", newline="\n")
        assert _run().exit_code == 0
        result = _snapshot()
        assert result.exit_code == 1 and "  ?? sub/chartbook.lock" in result.output.splitlines()
        assert "Only chartbook.lock" not in result.output

    def test_more_than_ten_things_not_built_are_ten_and_a_count(self, work, store, monkeypatch):
        directory = _folder(work / "many", {
            "project": {"id": "acme/many"},
            "dataframes": {f"t{number:02}": {"path": f"./_data/t{number:02}.csv", "docs": "d"} for number in range(12)},
        })
        monkeypatch.chdir(_committed(directory))
        said = _snapshot().output.splitlines()
        assert said[1:] == [*(f"  not built: acme/many:t{number:02} (./_data/t{number:02}.csv)" for number in range(10)), "  and 2 more"]

    def test_a_folder_named_in_another_letter_case_is_said_in_words(self, demo, store, work, monkeypatch):
        """Found by review: a run named so handed over `chartbook snapshot --project-dir …/DEMO`, which answered in pathlib's words."""
        other = work / "DEMO"
        if not other.is_dir():
            pytest.skip("this disk tells letter cases apart")
        assert _run().exit_code == 0
        monkeypatch.chdir(work)
        result = _snapshot("--project-dir", str(other))
        assert result.exit_code == 1 and result.output.splitlines() == [
            f"Error: {other} is named otherwise than the disk names it, so where it is in its repository cannot be told. "
            f"`cd` into the folder, and `chartbook snapshot` again."
        ]
        # The run that is asked for a snapshot says the same, before it builds
        strict = _run("--snapshot", "--no-gc-reminder", "--project-dir", str(other))
        assert strict.exit_code == 1 and _ran(demo) == 1 and strict.output.splitlines() == [
            f"Error: {other} is named otherwise than the disk names it, so where it is in its repository cannot be told. "
            f"`cd` into the folder, and `chartbook run --snapshot` again."
        ]
        assert _snapshots(store) == []
        # And from inside the folder, however it was spelled, a run's last line names no folder
        monkeypatch.chdir(demo)
        assert _after_the_run(_run("--project-dir", str(other))) == _closing()

    def test_a_folder_of_a_larger_repository_named_in_another_letter_case_is_refused_too(self, work, store, monkeypatch):
        """Found by review: such a snapshot was made, and recorded the spelling as the pipeline's place. A pipeline that read the folder by its real name then pinned an older snapshot without a word."""
        mono = work / "mono"
        a = _folder(mono / "pipes" / "a")
        _committed(mono)
        other = mono / "PIPES" / "A"
        if not other.is_dir():
            pytest.skip("this disk tells letter cases apart")
        monkeypatch.chdir(work)
        assert _run("--project-dir", str(a)).exit_code == 0
        refused = "is named otherwise than the disk names it, so where it is in its repository cannot be told."
        typed = _snapshot("--project-dir", str(other))
        assert typed.exit_code == 1 and typed.output.splitlines() == [
            f"Error: {other} {refused} `cd` into the folder, and `chartbook snapshot` again."
        ]
        strict = _run("--snapshot", "--no-gc-reminder", "--project-dir", str(other))
        assert strict.exit_code == 1 and f"Error: {other} {refused}" in strict.output and _ran(a) == 1
        assert _snapshots(store) == []
        # Named as the disk names it, the snapshot is made, and says where the pipeline is
        made = _snapshot("--project-dir", str(a))
        assert made.exit_code == 0 and said_made(made.output)
        (taken,) = _snapshots(store)
        assert taken.subdirectory == "pipes/a"

    def test_a_folder_in_another_of_unicodes_forms_is_no_mistake(self, work, store, monkeypatch):
        """Git and the system may write one name two ways. Whoever typed it made no mistake, and is not refused."""
        import unicodedata

        directory = _folder(work / "mono" / unicodedata.normalize("NFC", "d\u00e9p\u00f4t") / "pipe")
        _committed(work / "mono")
        monkeypatch.chdir(work)
        other = work / "mono" / unicodedata.normalize("NFD", "d\u00e9p\u00f4t") / "pipe"
        if not other.is_dir():
            pytest.skip("this disk tells the two forms apart")
        assert str(other) != str(directory)
        assert _run("--project-dir", str(directory)).exit_code == 0
        for spelled in (directory, other):
            result = _snapshot("--project-dir", str(spelled))
            assert "is named otherwise" not in result.output, result.output

    def test_a_lockfile_that_git_ignores_holds_nothing_up(self, demo, store, upstream):
        """A project that keeps its lockfile out of git has chosen that: the snapshot records what it was built from all the same."""
        _snapshot_of(upstream, store)
        (demo / ".gitignore").write_text(IGNORED + "/chartbook.lock\n", encoding="utf-8", newline="\n")
        _depends_on_upstream(demo)
        assert "Wrote chartbook.lock." in _run().output
        made = _snapshot()
        assert made.exit_code == 0 and said_made(made.output)


class TestRunSnapshot:
    """`chartbook run --snapshot` is the build and the snapshot in one command, as it was."""

    def test_it_builds_and_ends_with_one(self, demo, store):
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 0, result.output
        commit = _git(demo, "rev-parse", "HEAD")
        # The build, what is in the store, the two lines that say a snapshot was made, and then that the build ran
        lines = result.output.splitlines()
        assert lines[:2] == ["acme/demo: build", f"acme/demo at {commit[:7]}: 1 asset(s) in the store"]
        assert made_at(lines) == 2 and lines[4] == "Ran build in 1 pipeline(s)."
        assert not any(line in result.output for line in _closing())  # it has its snapshot
        (taken,) = _snapshots(store)
        assert taken.commit == commit and taken.built_by_run and taken.assets["out"]["content_hash"]
        # And it makes the catalog that shows it, which a plain run has no reason to
        assert config.get_global_catalog_path().is_file()

    def test_it_refuses_before_it_builds_with_anything_uncommitted(self, demo, store):
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1 and "Nothing was built." in result.output
        assert _ran(demo) == 0 and _snapshots(store) == []

    def test_any_other_true_value_asks_for_one(self, demo, store):
        """A caller of the function that passes 1 for True gets its snapshot, or the refusal."""
        (demo / "notes.txt").write_text("to do\n", encoding="utf-8", newline="\n")
        with pytest.raises(run.RunError, match="not committed"):
            run.run(demo, echo=lambda line: None, snapshot=1)
        (demo / "notes.txt").unlink()
        assert len(run.run(demo, echo=lambda line: None, snapshot=1).snapshots) == 1

    def test_it_passes_over_the_lockfile_it_writes_as_it_did(self, demo, store, upstream):
        """--snapshot refuses before it builds, and cannot refuse for the lockfile its own pin is about to write."""
        _snapshot_of(upstream, store)
        _depends_on_upstream(demo)
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 0, result.output
        assert said_made(result.output)
        assert _git(demo, "status", "--porcelain") == "?? chartbook.lock"

    def test_of_a_commit_checked_out_by_its_hash(self, demo, store):
        """What the list of what is not in a store says to type, in a clone at the commit a pin names."""
        _git(demo, "checkout", "--quiet", "--detach")
        asked = _run("--snapshot", "--no-gc-reminder")
        assert asked.exit_code == 0 and said_made(asked.output) and len(_snapshots(store)) == 1

    def test_it_asks_nothing_at_a_terminal(self, stores, demo, work, monkeypatch):
        """A snapshot typed by hand may ask which store a new pipeline goes to. A run does not: it writes where the catalog sends the pipeline."""
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
        assert len(run.run(demo, echo=lambda line: None, snapshot=True).snapshots) == 1
        assert _stored(work, "first") == ["acme/demo"] and _stored(work, "second") == []

    def test_a_plain_run_puts_nothing_in_either(self, stores, demo, work):
        result = _run()
        assert result.exit_code == 0 and _after_the_run(result) == _closing()
        assert _stored(work, "first") == [] and _stored(work, "second") == []


class TestAFirstStoreThatIsOnlyRead:
    """A class's store listed ahead of one's own stops a snapshot of a pipeline the catalog sends nowhere. The snapshot says the way out, as a run's last line did while a run made one."""

    READ_ONLY = (
        "Error: Store 'first' is read-only. This had to write it: a git dependency's first pin and a snapshot both put "
        "files into the store. Do it where the store can be written; or, if the store already has what the lockfile "
        "names, use `run --frozen` (or `pin --check` to only check)."
    )

    def test_the_snapshot_says_how_to_send_it_elsewhere(self, stores, demo, work):
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        assert _run().exit_code == 0
        result = _snapshot()
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            self.READ_ONLY,
            "  It is the catalog's first store, where a pipeline the catalog sends nowhere is written.",
            # "Add", and not what the line is to be: the store may be sent other pipelines already
            f'  To send this one to second: add "acme/demo" to `pipelines` under [stores.second] in {work / "home" / "catalog.toml"}.',
            "  Or, for this one snapshot: `chartbook snapshot --store second`.",
        ]
        # Typed from another folder, the command it names says which pipeline
        os.chdir(work)
        try:
            elsewhere = _snapshot("--project-dir", str(demo))
        finally:
            os.chdir(demo)
        assert elsewhere.output.splitlines()[-1] == (
            f"  Or, for this one snapshot: `chartbook snapshot --store second --project-dir {missing._quoted(demo)}`."
        )
        # The second of those, as it is given
        once = _snapshot("--store", "second")
        assert once.exit_code == 0 and said_made(once.output), once.output
        assert _stored(work, "first") == [] and _stored(work, "second") == ["acme/demo"]
        (demo / "out.csv").write_text("c,d\n", encoding="utf-8", newline="\n")
        # Done as the first says, the snapshot is made, there
        stores(
            first={"url": str(work / "first"), "read_only": True},
            second={"url": str(work / "second"), "pipelines": ["acme/demo"]},
        )
        again = _snapshot()
        assert again.exit_code == 0, again.output
        assert said_made(again.output) and "Stores: second" in again.output.splitlines()
        assert _stored(work, "first") == [] and _stored(work, "second") == ["acme/demo", "acme/demo"]

    def test_a_store_it_is_sent_to_that_is_only_read_is_not_told_to_be_sent(self, stores, demo, work):
        stores(first={"url": str(work / "first"), "read_only": True, "pipelines": ["acme/demo"]}, second={"url": str(work / "second")})
        assert _run().exit_code == 0
        assert _snapshot().output.splitlines() == [self.READ_ONLY]

    @pytest.mark.parametrize("others", [{}, {"second": True}])
    def test_with_no_store_that_can_be_written_there_is_nowhere_to_send_it(self, stores, demo, work, others):
        stores(
            first={"url": str(work / "first"), "read_only": True},
            **{name: {"url": str(work / name), "read_only": True} for name in others},
        )
        assert _run().exit_code == 0
        assert _snapshot().output.splitlines() == [self.READ_ONLY]

    def test_a_run_asked_for_a_snapshot_says_it_before_it_builds(self, stores, demo, work):
        """The list of what is not in a store has a whole class type `chartbook run --snapshot`, and an hour of building mends nothing."""
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1
        assert result.output.splitlines() == [
            "Error: acme/demo cannot have a snapshot: Store 'first' is read-only, and it is the catalog's first, where a "
            "pipeline the catalog sends nowhere is written.",
            f'  To send this one to second: add "acme/demo" to `pipelines` under [stores.second] in {work / "home" / "catalog.toml"}. '
            f"Nothing was built.",
        ]
        assert _ran(demo) == 0
        # Done as it says, the run builds, and its snapshot is made, there
        stores(
            first={"url": str(work / "first"), "read_only": True},
            second={"url": str(work / "second"), "pipelines": ["acme/demo"]},
        )
        again = _run("--snapshot", "--no-gc-reminder")
        assert again.exit_code == 0 and said_made(again.output), again.output
        assert _stored(work, "first") == [] and _stored(work, "second") == ["acme/demo"] and _ran(demo) == 1

    def test_with_nowhere_to_send_it_such_a_run_says_only_that(self, stores, demo, work):
        stores(first={"url": str(work / "first"), "read_only": True, "pipelines": ["acme/demo"]}, second={"url": str(work / "second")})
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1 and _ran(demo) == 0
        assert result.output.splitlines() == ["Error: acme/demo cannot have a snapshot: Store 'first' is read-only. Nothing was built."]

    def test_an_upstream_that_could_not_be_snapshotted_is_not_built_either(self, stores, demo, work, upstream):
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        _depends_on_upstream(demo)
        result = _run("--upstream")
        assert result.exit_code == 1 and _ran(upstream) == 0 and _ran(demo) == 0
        assert "Error: acme/up cannot have a snapshot: Store 'first' is read-only, and it is the catalog's first" in result.output
        assert f'add "acme/up" to `pipelines` under [stores.second] in {work / "home" / "catalog.toml"}. Nothing was built.' in result.output

    def test_a_store_that_is_away_is_left_to_the_snapshot_as_it_was(self, stores, demo, work):
        """Only a store that may only be read is found before the build: one that is away may be back by its end."""
        stores(first={"url": str(work / "first")}, second={"url": str(work / "second"), "pipelines": ["acme/demo"]})
        (work / "second").rmdir()
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1 and "Store 'second' is unreachable" in result.output
        assert "cannot have a snapshot" not in result.output and _ran(demo) == 1

    def test_a_plain_run_is_not_stopped_by_it(self, stores, demo, work):
        """It writes to no store, so a store it could not write is nothing to it."""
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        result = _run()
        assert result.exit_code == 0 and _after_the_run(result) == _closing() and _ran(demo) == 1

    def test_a_store_named_by_hand_is_the_one_that_was_meant(self, stores, demo, work):
        stores(first={"url": str(work / "first"), "read_only": True}, second={"url": str(work / "second")})
        assert _run().exit_code == 0
        refused = _snapshot("--store", "first")
        assert refused.exit_code == 1 and len(refused.output.splitlines()) == 1 and "read-only" in refused.output


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
        # And nothing is said of a snapshot of a build that went wrong
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
        assert report.failed is not None and report.exit_code == 1 and report.to_snapshot == []
        assert report.reason == "its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)"
        assert run.unwritten(demo) == [("forgotten", "./_data/forgotten.csv")]

    def test_a_manifest_a_docs_build_would_refuse_is_asked_all_the_same(self, demo, store):
        """Found by review: an entry with no docs made the look fail in silence, and a snapshot was made with the output missing."""
        _write(demo, {**DEMO, "dataframes": {"out": {"path": "./out.csv"}, "forgotten": {"path": "./forgotten.csv"}}})
        _committed(demo)
        result = _run("--snapshot", "--no-gc-reminder")
        assert result.exit_code == 1 and "its build did not write 1 thing" in result.output
        assert run.unwritten(demo) == [("forgotten", "./forgotten.csv")]
        assert _snapshots(store) == []

    @pytest.mark.parametrize("sections, said", [
        ({"dataframes": [{"name": "out", "path": "./out.csv"}]}, "[dataframes] must be a table of tables, one per dataframe, e.g. [dataframes.<name>] with a path = \"...\" under it; it is an array."),
        ({"dataframes": DEMO["dataframes"], "models": "none"}, "[models] must be a table of tables, one per model, e.g. [models.<name>] with a path = \"...\" under it; it is a string."),
    ])
    def test_a_section_that_is_not_a_table_is_said_and_is_no_traceback(self, work, store, monkeypatch, sections, said):
        """Found by review: `[[dataframes]]` was a traceback, before the build in a run and in `chartbook snapshot`. A run builds, as it did, and the snapshot says it."""
        directory = _folder(work / "arrays", {"project": {"id": "acme/arrays"}, "scripts": {"build": BUILD}, **sections})
        monkeypatch.chdir(_committed(directory))
        why = f"acme/arrays cannot have a snapshot: chartbook.toml: {said} `chartbook run --check` says more."
        result = _run()
        assert result.exit_code == 0 and result.exception is None, result.output
        # It means to declare something, so it is told what makes a snapshot, which says what is wrong with how
        assert result.output.splitlines() == ["acme/arrays: build", "Ran build in 1 pipeline(s).", *_closing("acme/arrays")]
        by_hand = CliRunner().invoke(main, ["snapshot"])
        assert by_hand.exit_code == 1 and isinstance(by_hand.exception, SystemExit)
        assert by_hand.output.splitlines() == [f"Error: {why}"]
        strict = _run("--snapshot", "--no-gc-reminder")
        assert strict.exit_code == 1 and isinstance(strict.exception, SystemExit)
        assert f"Error: acme/arrays: {why.rstrip('.')}. Nothing after it was run." in strict.output.splitlines()
        assert _snapshots(store) == []

    @posix
    def test_a_folder_with_nothing_in_it_is_not_written(self, work, store, monkeypatch):
        """Asked as a snapshot asks it: a folder is there when it holds a file."""
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
            ("source local", "./_data/never.duckdb"),
        ]
        result = _run()
        assert result.exit_code == 1 and "its build did not write 7 things chartbook.toml declares" in result.output

    @pytest.mark.parametrize("flags", [[], ["--snapshot", "--no-gc-reminder"], ["--frozen"], ["--remake"]])
    def test_every_form_of_a_build_fails_for_it(self, demo, store, flags):
        self.forgetful(demo)
        result = _run(*flags)
        assert result.exit_code == 1, result.output
        assert "its build did not write 1 thing chartbook.toml declares: forgotten (./_data/forgotten.csv)" in result.output
        assert "acme/demo: built." not in result.output and _snapshots(store) == [] and _ran(demo) == 1

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


class TestNothingSaysARunMakesASnapshot:
    """The day a run ended with one left its words in some forty files. Each is read, with its lines joined, for the phrases that said so."""

    SAID_SO = [
        r"ends with a snapshot whenever", r"makes? a snapshot when everything", r"makes? its snapshot when",
        r"not snapshotted:", r"[Ss]eldom needed \(`chartbook run`", r"[Ss]eldom type this(: `chartbook run`| command)", r"THE command",
        r"one command of a working day", r"takes the snapshot (when|once)", r"strict form of `chartbook run`",
        r"[Tt]he five commands", r"Five commands cover", r"WHEN_COMMITTED", r"not_snapshotted",
        r"`chartbook run` again\b(?! (after|once))", r"a build of committed work ends with",
        r"built at a commit \(`chartbook run`\)",
    ]

    def test_in_no_file_a_person_or_an_assistant_learns_from(self):
        import re

        from tests.test_removed_commands import ROOT, _taught

        found = []
        for path in _taught():
            try:
                joined = " ".join(path.read_text(encoding="utf-8").split())
            except UnicodeDecodeError:
                continue
            found += [f"{path.relative_to(ROOT).as_posix()}: {phrase}" for phrase in self.SAID_SO if re.search(phrase, joined)]
        assert found == []

    @pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"], ["snapshot", "--help"], ["pin", "--help"]])
    def test_in_no_help(self, arguments):
        import re

        said = " ".join(CliRunner().invoke(main, arguments, prog_name="chartbook").output.split())
        assert [phrase for phrase in self.SAID_SO if re.search(phrase, said)] == []
        if arguments[0] in ("run", "snapshot"):
            assert "no snapshot" in said  # each says it of a run, in so many words

    def test_the_section_for_agents_says_who_asks_for_one(self):
        from chartbook import agents

        said = " ".join(agents.section().split())
        assert "`chartbook snapshot`, once everything is committed. A run does not do it." in said
        assert "do it when the person asks for it" in said

