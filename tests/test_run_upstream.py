"""`chartbook run --upstream`: an upstream pipeline with no snapshot to pin is built and snapshotted first.

A `path` dependency is its owner's to build and snapshot. With `--upstream`, one on this machine
that has no snapshot a pin would take, and is not pinned yet, is built first, its own upstreams
before it, and snapshotted after its build succeeds, so that what depends on it can pin it. Each
must be trusted to run and fully committed, and the first failure stops the run.
"""

import os

import pytest
from click.testing import CliRunner

from chartbook import config, lock, run, snapshot
from chartbook.cli import main
from chartbook.run import RunError
from chartbook.store import default_store
from tests.test_run import LOG, _commit, _order, _pipeline, _with_data, work  # noqa: F401

posix = pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")


def _snapshots_of(pipeline: str) -> list:
    return [taken for taken in snapshot.readable_snapshots(default_store())[0] if taken.pipeline == pipeline]


@pytest.fixture
def pair(work):
    """`down` depends on `up` by path, in one repository; nothing is snapshotted."""
    up = _with_data(work / "up", {"build": LOG})
    down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
    _commit(work)
    return up, down


@posix
class TestUpstream:
    def test_without_it_the_run_stops_and_says_who_makes_the_snapshot(self, pair, work):
        up, down = pair
        report = run.run(down, echo=lambda line: None)
        assert report.failed.id == "down" and report.reason == "what it depends on could not be pinned"
        assert _order(work) == []

    def test_an_upstream_with_no_snapshot_is_built_and_snapshotted_first(self, pair, work):
        up, down = pair
        said = []
        report = run.run(down, upstream=True, echo=said.append)
        assert report.failed is None, report.reason
        assert _order(work) == ["up", "down"]
        assert said[:2] == ["Upstream with no snapshot to pin, built and snapshotted first:", f"  up    in {up}"]
        (taken,) = _snapshots_of("up")
        assert taken.built_by_run
        (entry,) = lock.read_lock(down).dependencies
        assert entry["snapshot"] == taken.made_at  # and down pinned it
        assert _snapshots_of("down") == []  # down itself is snapshotted only with --snapshot

    def test_with_snapshot_both_are_snapshotted(self, pair, work):
        up, down = pair
        assert run.run(down, upstream=True, snapshot=True, echo=lambda line: None).failed is None
        assert len(_snapshots_of("up")) == 1 and len(_snapshots_of("down")) == 1

    def test_upstreams_of_upstreams_come_first(self, work):
        _with_data(work / "c", {"build": LOG})
        _with_data(work / "b", {"build": LOG}, {"c": {"path": "../c"}})
        a = _with_data(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _commit(work)
        assert run.run(a, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["c", "b", "a"]
        assert len(_snapshots_of("c")) == 1 and len(_snapshots_of("b")) == 1

    def test_an_upstream_with_a_snapshot_is_not_built_again(self, pair, work):
        up, down = pair
        snapshot.make(up)
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["down"] and len(_snapshots_of("up")) == 1

    def test_an_upstream_already_pinned_is_not_built_again(self, pair, work):
        up, down = pair
        snapshot.make(up)
        lock.pin(down)
        taken = _snapshots_of("up")[0]
        os.chmod(taken.path, 0o600)
        taken.path.unlink()  # the store no longer has it; the pin stays
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["down"]

    def test_an_upstream_with_changes_not_committed_stops_the_run_before_anything(self, pair, work):
        up, down = pair
        (up / "notes.txt").write_text("half done")
        with pytest.raises(RunError, match=r"(?s)^up has changes that are not committed:.*Nothing was built\.$") as raised:
            run.run(down, upstream=True, echo=lambda line: None)
        assert "notes.txt" in str(raised.value)
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_this_user_has_not_trusted_is_not_run(self, pair, work, monkeypatch):
        up, down = pair
        monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
        monkeypatch.delenv("CI", raising=False)
        config.record_trust(down, "run")
        with pytest.raises(RunError) as raised:
            run.run(down, upstream=True, echo=lambda line: None)
        assert f"  up: {up} (not trusted, an upstream --upstream would build)" in str(raised.value)
        assert "`chartbook trust` in a folder trusts that one" in str(raised.value)
        assert _order(work) == []
        config.record_trust(up, "run")
        assert run.run(down, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["up", "down"]

    def test_an_upstream_build_that_fails_stops_the_run(self, work):
        up = _with_data(work / "up", {"build": "exit 3"})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and report.exit_code == 3
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_build_that_changes_committed_files_is_not_snapshotted(self, work):
        up = _with_data(work / "up", {"build": "echo changed > x.parquet"})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and "changes that are not committed" in report.reason
        assert _order(work) == [] and _snapshots_of("up") == []

    def test_an_upstream_with_no_build_script(self, work):
        _with_data(work / "up")
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        with pytest.raises(RunError, match="has no snapshot to pin and no `build` script"):
            run.run(down, upstream=True, echo=lambda line: None)
        assert _order(work) == []

    def test_what_it_is_refused_with(self, pair):
        up, down = pair
        with pytest.raises(RunError, match="--frozen writes nothing"):
            run.run(down, upstream=True, frozen=True, echo=lambda line: None)
        with pytest.raises(RunError, match="--upstream builds what `build` pins"):
            run.run(down, "test", upstream=True, echo=lambda line: None)

    def test_an_upstream_in_a_cycle_is_refused_before_anything(self, work):
        up = _with_data(work / "up", {"build": LOG}, {"down": {"path": "../down"}})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        with pytest.raises(RunError, match="depend on each other"):
            run.run(down, upstream=True, echo=lambda line: None)
        assert _order(work) == []

    def test_the_command(self, pair, work, monkeypatch):
        up, down = pair
        monkeypatch.chdir(down)
        result = CliRunner().invoke(main, ["run", "--upstream"])
        assert result.exit_code == 0, result.output
        assert "Upstream with no snapshot to pin, built and snapshotted first:" in result.output
        assert result.output.splitlines()[-1] == "Ran build in 2 pipeline(s)."
        assert _order(work) == ["up", "down"]


def _catalog(work, *members):
    import tomli_w

    (work / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in members}})
    )
    return work


@posix
class TestWhatTheReviewFound:
    def test_a_record_that_cannot_be_read_is_not_taken_for_none(self, pair, work):
        """up's snapshot record cannot be read: up is not built again, and the pin says what is wrong."""
        up, down = pair
        taken = snapshot.make(up).snapshot
        os.chmod(taken.path, 0o600)
        taken.path.write_text("{ not json")
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed is not None and _order(work) == []

    def test_a_store_that_cannot_be_read_at_a_terminal_is_a_clean_error(self, pair, monkeypatch):
        from chartbook import cli
        from chartbook.store import StoreError

        up, down = pair

        def unreadable(*arguments, **keywords):
            raise StoreError("the store cannot be reached")

        monkeypatch.setattr(cli, "_can_ask", lambda: True)
        monkeypatch.setattr(snapshot, "newest_for", unreadable)
        monkeypatch.chdir(down)
        result = CliRunner().invoke(main, ["run", "--upstream"])
        assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.output
        assert result.output.startswith("Error: ") and "the store cannot be reached" in result.output

    def test_a_catalog_member_another_pins_by_path_is_snapshotted_first(self, work):
        u = _with_data(work / "u", {"build": LOG})
        _with_data(work / "a", {"build": LOG}, {"u": {"path": "../u"}})
        _catalog(work, "a", "u")
        _commit(work)
        assert run.run(work, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["u", "a"] and len(_snapshots_of("u")) == 1 and _snapshots_of("a") == []

    def test_an_upstream_that_depends_on_a_catalog_member(self, work):
        """d is in the catalog and reads u, which is not; u reads m, which is: m, then u, then d."""
        _with_data(work / "m", {"build": LOG})
        _with_data(work / "u", {"build": LOG}, {"m": {"path": "../m"}})
        _with_data(work / "d", {"build": LOG}, {"u": {"path": "../u"}})
        _catalog(work, "d", "m")
        _commit(work)
        assert run.run(work, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["m", "u", "d"] and len(_snapshots_of("m")) == 1 and len(_snapshots_of("u")) == 1

    def test_two_pipelines_that_read_one_upstream_build_it_once(self, work):
        _with_data(work / "u", {"build": LOG})
        _with_data(work / "a", {"build": LOG}, {"u": {"path": "../u"}})
        _with_data(work / "b", {"build": LOG}, {"u": {"path": "../u"}})
        _catalog(work, "a", "b")
        _commit(work)
        assert run.run(work, upstream=True, echo=lambda line: None).failed is None
        assert _order(work) == ["u", "a", "b"] and len(_snapshots_of("u")) == 1

    def test_a_git_dependencys_own_path_is_not_followed(self, work, tmp_path):
        """A git dependency's manifest names a folder that happens to be here: --upstream does not build it."""
        import subprocess

        x = _with_data(work / "x", {"build": LOG})
        repository = tmp_path / "g"
        _pipeline(repository, None, {"x": {"path": str(x)}}, dataframes={"y": {"path": "./y.parquet", "docs": "d"}})
        (repository / "y.parquet").write_bytes(b"y")
        for command in (["init", "--quiet", "-b", "main"], ["add", "-A"], ["commit", "--quiet", "-m", "g"]):
            subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.org", *command], cwd=repository, check=True)
        down = _with_data(work / "down", {"build": LOG}, {"g": {"git": str(repository)}})
        _commit(work)
        run.run(down, upstream=True, echo=lambda line: None)
        assert "x" not in _order(work) and _snapshots_of("x") == []

    def test_one_made_while_waiting_is_not_built_again(self, pair, work, monkeypatch):
        """Another run snapshots up between this run's plan and its turn to build it."""
        up, down = pair
        planned = run.plan

        def plan_then_another_run(*arguments, **keywords):
            steps = planned(*arguments, **keywords)
            snapshot.make(up)
            return steps

        monkeypatch.setattr(run, "plan", plan_then_another_run)
        said = []
        assert run.run(down, upstream=True, echo=said.append).failed is None
        assert any("up: has a snapshot now" in line for line in said)
        assert _order(work) == ["down"] and len(_snapshots_of("up")) == 1

    def test_an_upstreams_kept_output_names_commands_that_work(self, pair, monkeypatch):
        from types import SimpleNamespace

        up, down = pair
        taken = SimpleNamespace(commit="a" * 40, made_at="2026-10-26T00:00:00.000000Z")
        monkeypatch.setattr(run, "kept_missing", lambda folder, store=None: [("x", "./x.parquet", taken)] if folder == up else [])
        with pytest.raises(RunError) as raised:
            run.run(down, upstream=True, echo=lambda line: None)
        assert f"chartbook restore --project-dir {up}" in str(raised.value)
        assert "chartbook run --remake --upstream" in str(raised.value)

    def test_a_build_that_moves_the_commit_is_not_snapshotted(self, work):
        _with_data(work / "up", {"build": 'git -c user.name=T -c user.email=t@example.org commit --quiet --allow-empty -m moved'})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and "moved the repository" in report.reason and _snapshots_of("up") == []

    def test_a_build_that_leaves_a_new_file_is_not_snapshotted(self, work):
        _with_data(work / "up", {"build": "echo new > new.txt"})
        down = _with_data(work / "down", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        report = run.run(down, upstream=True, echo=lambda line: None)
        assert report.failed.id == "up" and _snapshots_of("up") == []

    def test_an_upstreams_new_lockfile_is_said_to_commit(self, work):
        import subprocess

        (work / ".gitignore").write_text("_data/\n*.log\n")
        subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=work, check=True)
        w = _with_data(work / "w", {"build": LOG})
        u = _with_data(work / "u", {"build": LOG}, {"w": {"path": "../w"}})
        down = _with_data(work / "down", {"build": LOG}, {"u": {"path": "../u"}})
        _commit(work)
        snapshot.make(w)
        said = []
        assert run.run(down, upstream=True, echo=said.append).failed is None
        assert f"u: its chartbook.lock was written, and is not committed: commit it in {u}." in said

    def test_at_a_terminal_an_upstream_is_asked_about_as_one(self, pair, work, monkeypatch):
        from chartbook import cli

        up, down = pair
        monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
        monkeypatch.delenv("CI", raising=False)
        config.record_trust(down, "run")
        monkeypatch.setattr(cli, "_can_ask", lambda: True)
        monkeypatch.chdir(down)
        result = CliRunner().invoke(main, ["run", "--upstream"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "an upstream: built, then snapshotted" in result.output
        assert config.trust_of(up) == "run" and _order(work) == ["up", "down"]

    def test_build_takes_it(self, pair, monkeypatch):
        from chartbook import cli

        up, down = pair
        seen = {}
        monkeypatch.setattr(cli, "_run_script", lambda *a, **k: seen.update(k))
        monkeypatch.setattr(cli, "_render_site", lambda **k: None)
        monkeypatch.chdir(down)
        result = CliRunner().invoke(main, ["build", "-f", "--upstream"])
        assert result.exit_code == 0, result.output
        assert seen.get("upstream") is True


@posix
class TestWhatTheSecondReviewFound:
    def test_an_upstream_whose_build_runs_the_downstream_stops_and_does_not_hang(self, work):
        """up's build runs `chartbook run --upstream` in down, which plans up again: the run refuses, as before the lock."""
        import subprocess
        import sys
        from pathlib import Path

        chartbook = Path(sys.executable).parent / "chartbook"
        down = work / "down"
        _with_data(work / "up", {"build": f"{chartbook} run --upstream --project-dir {down}"})
        _with_data(down, {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        home = work / "home"  # the test's own ~/.chartbook is set in this process only, so the child gets a home
        home.mkdir()
        finished = subprocess.run(
            [str(chartbook), "run", "--upstream", "--project-dir", str(down)],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HOME": str(home), "USERPROFILE": str(home)},
        )
        assert finished.returncode != 0
        assert "would then run itself without end" in finished.stdout + finished.stderr

    def test_a_folder_that_changed_before_its_turn_is_not_built(self, work):
        """c is built first and its build edits b: b, committed when the run began, is refused at its turn."""
        _with_data(work / "c", {"build": f"{LOG} && echo half-done > ../b/notes.txt"})
        _with_data(work / "b", {"build": LOG}, {"c": {"path": "../c"}})
        a = _with_data(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _commit(work)
        report = run.run(a, upstream=True, echo=lambda line: None)
        assert report.failed.id == "b"
        assert "It changed before its turn came, and was not built" in report.reason
        assert _order(work) == ["c"] and _snapshots_of("b") == []

    def test_a_run_that_must_wait_says_so(self, pair, monkeypatch):
        up, down = pair
        monkeypatch.setattr(lock, "held_elsewhere", lambda path: True)
        said = []
        assert run.run(down, upstream=True, echo=said.append).failed is None
        assert "up: another run is building it to make a snapshot; waiting for it" in said

    def test_the_owners_own_snapshot_build_takes_the_same_turn(self, pair, monkeypatch):
        up, down = pair
        monkeypatch.setattr(lock, "held_elsewhere", lambda path: True)
        said = []
        assert run.run(up, snapshot=True, echo=said.append).failed is None
        assert "up: another run is building it to make a snapshot; waiting for it" in said

    def test_a_catalog_member_with_no_build_plans_no_upstream(self, work):
        _with_data(work / "u", {"build": LOG})
        _with_data(work / "p", None, {"u": {"path": "../u"}})
        _with_data(work / "q", {"build": LOG})
        _catalog(work, "p", "q")
        _commit(work)
        run.run(work, upstream=True, echo=lambda line: None)
        assert "u" not in _order(work) and _snapshots_of("u") == []

    def test_snapshots_that_cannot_be_read_at_its_turn_build_nothing(self, pair, work, monkeypatch):
        import contextlib

        from chartbook.store import StoreError

        up, down = pair
        turns = []
        taking_a_turn = run._alone_while_built
        original = snapshot.newest_for

        @contextlib.contextmanager
        def counted(*arguments, **keywords):
            turns.append(1)
            with taking_a_turn(*arguments, **keywords):
                yield

        def unreadable_at_its_turn(*arguments, **keywords):
            if len(turns) == 1:  # up's second look, and only that
                turns.append(1)
                raise StoreError("the store cannot be reached")
            return original(*arguments, **keywords)

        monkeypatch.setattr(run, "_alone_while_built", counted)
        monkeypatch.setattr(snapshot, "newest_for", unreadable_at_its_turn)
        said = []
        report = run.run(down, upstream=True, echo=said.append)
        assert "up: its snapshots cannot be read now; not built" in said
        assert "up" not in _order(work) and _snapshots_of("up") == []
        assert report.failed.id == "down" and report.reason == "what it depends on could not be pinned"


def _child_env(work):
    """A child process's own home: the test's ~/.chartbook is set in this process only."""
    home = work / "home"
    home.mkdir(exist_ok=True)
    return {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}


@posix
class TestWhatTheThirdReviewFound:
    def test_another_process_holding_the_turn_is_seen(self, work):
        import subprocess
        import sys

        key = work / ".chartbook-snapshot-build"
        holding = (
            "import sys\n"
            "from pathlib import Path\n"
            "from chartbook import lock\n"
            f"with lock._one_at_a_time(Path({str(key)!r})):\n"
            "    print('held', flush=True)\n"
            "    sys.stdin.readline()\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", holding], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env=_child_env(work),
        )
        try:
            assert child.stdout.readline().strip() == "held"
            assert lock.held_elsewhere(key) is True
        finally:
            child.communicate("done\n", timeout=30)
        assert lock.held_elsewhere(key) is False

    def test_where_files_cannot_be_locked_no_one_is_said_to_hold_it(self, work, monkeypatch):
        import errno
        import fcntl

        key = work / ".chartbook-snapshot-build"
        with lock._one_at_a_time(key):
            pass  # its lock file is there now

        def no_locks(descriptor, operation):
            raise OSError(errno.ENOLCK, "No locks available")

        monkeypatch.setattr(fcntl, "flock", no_locks)
        assert lock.held_elsewhere(key) is False

    def test_two_runs_build_one_upstream_once(self, work):
        import subprocess
        import sys

        _with_data(work / "up", {"build": f"sleep 4 && {LOG}"})
        first = _with_data(work / "first", {"build": LOG}, {"up": {"path": "../up"}})
        second = _with_data(work / "second", {"build": LOG}, {"up": {"path": "../up"}})
        _commit(work)
        running = (
            "from chartbook import run\n"
            f"report = run.run({str(first)!r}, upstream=True, echo=lambda line: print(line, flush=True))\n"
            "print('failed:', report.failed and report.failed.id, flush=True)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", running], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=_child_env(work),
        )
        line = ""
        while "up: build" not in line:
            line = child.stdout.readline()
            assert line, "the first run ended before building up"
        said = []
        report = run.run(second, upstream=True, echo=said.append)
        rest = child.communicate(timeout=120)[0]
        assert "failed: None" in rest
        assert report.failed is None, report.reason
        assert "up: another run is building it to make a snapshot; waiting for it" in said
        assert any(line.startswith("up: has a snapshot now") for line in said)
        assert len(_snapshots_of("up")) == 1 and _order(work).count("up") == 1

    def test_a_member_with_no_build_is_not_said_to_be_snapshotted(self, work):
        _with_data(work / "m", None)
        _with_data(work / "p", {"build": LOG}, {"m": {"path": "../m"}})
        _catalog(work, "p", "m")
        _commit(work)
        said = []
        run.run(work, upstream=True, echo=said.append)
        assert "Pipelines of this run that another pins by path, snapshotted after their build:" not in said

    def test_a_repository_that_moved_is_said_to_have(self, work, tmp_path_factory):
        """c, in a repository of its own, commits in b's repository as it builds: b's folder is as it was."""
        other = tmp_path_factory.mktemp("other").resolve()
        commits_elsewhere = f"git -C {work} -c user.name=T -c user.email=t@e.org commit --quiet --allow-empty -m elsewhere"
        _with_data(other / "c", {"build": commits_elsewhere})
        _commit(other)
        _with_data(work / "b", {"build": LOG}, {"c": {"path": str(other / "c")}})
        a = _with_data(work / "a", {"build": LOG}, {"b": {"path": "../b"}})
        _commit(work)
        report = run.run(a, upstream=True, echo=lambda line: None)
        assert report.failed.id == "b"
        assert report.reason.startswith("its repository moved from ") and "it was checked at" in report.reason

    def test_a_new_lockfile_is_said_where_git_hides_untracked_files(self, work, monkeypatch):
        import subprocess

        (work / ".gitignore").write_text("_data/\n*.log\n")  # lockfiles are committed here
        subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=work, check=True)
        w = _with_data(work / "w", {"build": LOG})
        u = _with_data(work / "u", {"build": LOG}, {"w": {"path": "../w"}})
        down = _with_data(work / "down", {"build": LOG}, {"u": {"path": "../u"}})
        _commit(work)
        snapshot.make(w)
        monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
        monkeypatch.setenv("GIT_CONFIG_KEY_2", "status.showUntrackedFiles")
        monkeypatch.setenv("GIT_CONFIG_VALUE_2", "no")
        said = []
        assert run.run(down, upstream=True, echo=said.append).failed is None
        assert f"u: its chartbook.lock was written, and is not committed: commit it in {u}." in said
