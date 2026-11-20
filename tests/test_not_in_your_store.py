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
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, missing, snapshot
from chartbook.cli import main
from chartbook.gitcache import GitCache, GitError
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git

#: The list's last line: the other way on
SHARED = "Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has {}, or wait for its sync to finish."
ONE = ["Build it first, with the commands below. They end with a snapshot, which is what this one reads.", ""]
SEVERAL = ["Build them in this order, with the commands below. Each ends with a snapshot, which is what the next one reads.", ""]
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


def _away(work: Path, *names: str) -> None:
    """These repositories are not on this machine: each is where its address leads, and nowhere a clone would be looked for."""
    (work / "elsewhere").mkdir(exist_ok=True)
    for name in names:
        (work / name).rename(work / "elsewhere" / name)
    _answered_from(work, work / "elsewhere")


def _said(result) -> list[str]:
    return result.output.splitlines()


def _numbered(result) -> list[str]:
    """The lines of the list that name a pipeline."""
    return [line for line in _said(result) if line[:1].isdigit()]


def _q(path) -> str:
    """A path as a command of the list has it: quoted where this system's shell needs it."""
    return subprocess.list2cmdline([str(path)]) if os.name == "nt" else shlex.quote(str(path))


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
    assert commands and commands[-1].endswith("&& chartbook run")
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
            f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:12]} && chartbook run --snapshot",
            f"2. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid; reads 1 above",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:12]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
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
        assert f"     cd {_q(work / 'rates')} && chartbook run --snapshot" in _said(result)  # never `chartbook snapshot`: it is pinned
        assert "chartbook run --upstream" not in result.output
        # With the clone on another commit they are two builds, and each reader names its own
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")
        moved = _run(work, monkeypatch, "run")
        assert [line.split("    ")[0] for line in _numbered(moved)] == ["1. acme/rates", "2. acme/a", f"3. acme/rates at {commit[:7]}", "4. acme/b"]
        assert _numbered(moved)[1].endswith("; reads 1 above") and _numbered(moved)[3].endswith("; reads 3 above")
        assert f"     cd {_q(work / 'rates')} && git checkout {commit[:12]} && chartbook run --snapshot" in _said(moved)

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
        assert [line for line in _said(result) if "acme/base" in line or f"cd {_q(base)}" in line] == [
            f"1. acme/base at {first[:7]}    {_up('base')} (a clone of https://example.org/acme/base)",
            f"     cd {_q(base)} && git checkout {first[:12]} && chartbook run --snapshot",
            # On that commit when the list was made, and no longer once the line above is done
            f"3. acme/base at {second[:7]}    {_up('base')} (a clone of https://example.org/acme/base)",
            f"     cd {_q(base)} && git checkout {second[:12]} && chartbook run --snapshot",
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
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:12]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
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
        assert f"     cd {_q(work / 'report')} && chartbook run --force --snapshot --remake" in said

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
            f"     cd {_q(work / 'rates')} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
            "Or `chartbook run --upstream` here, which builds and snapshots this folder itself.",
            SHARED.format("it"),
        ]

    def test_of_one_that_is_built_and_only_lacks_its_snapshot(self, work, theirs, monkeypatch):
        """Never pinned, nothing uncommitted, every declared file on disk: a build that may take an hour is not run again."""
        rates = _pipeline(work, "rates")
        (rates / "out.csv").write_text("a,b\nrates,1\n", encoding="utf-8", newline="\n")
        _pipeline(work, "report", {"acme/rates": {"path": "../rates"}})
        said = _said(_run(work, monkeypatch, "run"))
        assert said[5:7] == [
            f"1. acme/rates    {_up('rates')} (a folder on this machine, built already)",
            f"     cd {_q(rates)} && chartbook snapshot",
        ]
        # With work that is not committed, a snapshot would be refused: the build is what is said, and its refusal says to commit
        (rates / "chartbook.toml").write_text((rates / "chartbook.toml").read_text(encoding="utf-8") + "\n# more\n", encoding="utf-8", newline="\n")
        assert _said(_run(work, monkeypatch, "run"))[3:5] == [
            f"1. acme/rates    {_up('rates')} (a folder on this machine)",
            f"     cd {_q(rates)} && chartbook run --snapshot",
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
            f"     cd {_q(work / 'mid')} && chartbook run --snapshot",  # nothing to check out: it is on that commit
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
            f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:12]} && chartbook run --snapshot",
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a folder on this machine); reads 1 above",
            f"     cd {_q(mid)} && git checkout {commits['mid'][:12]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
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
        assert said[4:7] == [
            f"1. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:12]} && chartbook run --snapshot",
        ]
        assert said[7].startswith("     What it reads in turn is not known: its repository could not be fetched (")
        # Where it is in its repository is not known either, and the top is only the likeliest place
        assert said[7].endswith("); if it is not at the top of its repository, `cd` to its folder there first. Its own `chartbook run` says.")

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
            f"     In a clone of it: git checkout {commit[:12]} && chartbook run --snapshot",
        ]

    def test_whose_folder_is_not_on_this_machine(self, work, theirs, mine, monkeypatch):
        """Found by review: the words this list takes the place of said where it was looked for."""
        commit = _ready(_pipeline(work, "mid", remote=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        (work / "mid").rename(work / "gone")
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
            "     In a clone of it: chartbook run --snapshot",
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
            f"     cd {_q(work / 'mid')} && chartbook run --snapshot",
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
        assert f"     cd {_q(work / 'mid')} && git checkout {wanted[:12]} && chartbook run --snapshot" in _said(result)

    def test_of_a_pipeline_in_a_folder_of_its_repository(self, work, theirs, mine, monkeypatch):
        commit = _ready(_pipeline(work, "mid", within="pipelines/mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:7] == [
            f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     git -C {_q(work / 'mid')} checkout {commit[:12]} && cd {_q(work / 'mid' / 'pipelines' / 'mid')} && chartbook run --snapshot",
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
        assert said[4:9] == [
            f"1. acme/a at {commit[:7]}    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {_q(work / 'mono')}",
            f"     git -C {_q(work / 'mono')} checkout {commit[:12]} && cd {_q(work / 'mono' / 'a')} && chartbook run --snapshot",
            f"2. acme/b at {commit[:7]}    https://example.org/acme/mono",
            f"     git -C {_q(work / 'mono')} checkout {commit[:12]} && cd {_q(work / 'mono' / 'b')} && chartbook run --snapshot",  # cloned by the line before
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
        assert _said(result)[4:9] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {_q(work / 'mono')}",
            f"     git -C {_q(work / 'mono')} checkout {first[:12]} && cd {_q(work / 'mono' / 'alpha')} && chartbook run --snapshot",
            f"2. acme/beta at {second[:7]}    https://example.org/acme/mono; reads 1 above",
            f"     git -C {_q(work / 'mono')} checkout {second[:12]} && cd {_q(work / 'mono' / 'beta')} && chartbook run --snapshot",
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
        assert f"     cd {_q(work / 'mid')} && git checkout {commit[:12]} && chartbook run --snapshot" in said
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
        assert f"     git -C {_q(work / 'mid')} checkout {commit[:12]} && cd {_q(work / 'mid' / 'pipelines' / 'mid')} && chartbook run --snapshot" in said
        # Of very many manifests, so many are read. One past them is not called absent (found by the third pass: it
        # was said to hold no such pipeline): its line says how far the search went, and where it may be
        monkeypatch.setattr(missing, "MOST_MANIFESTS", 1)
        said = _said(_run(work, monkeypatch, "run"))
        assert f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid" in said
        assert f"     cd {_q(work / 'mid')} && git checkout {commit[:12]} && chartbook run --snapshot" in said
        assert (
            f"     What it reads in turn is not known: its chartbook.toml was not found among the first 1 of the 3 in its "
            f"repository at {commit[:7]}; if it is not at the top of its repository, `cd` to its folder there first. Its own "
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
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     cd {_q(top)} && git checkout {commit[:12]} && chartbook run --snapshot",
        ]
        assert "was not found among the first 1 of the 2 in its repository" in said[5]

    def test_of_a_pipeline_with_no_build_script(self, work, theirs, mine, monkeypatch):
        """It commits what it declares: nothing to run, and a snapshot to make."""
        commit = _ready(_pipeline(work, "mid", builds=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        assert f"     cd {_q(work / 'mid')} && git checkout {commit[:12]} && chartbook snapshot" in _said(_run(work, monkeypatch, "run"))

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
        """alpha was snapshotted before beta was added to their repository: `cd beta && git checkout` failed at the `cd`, every time."""
        top = _several(work, "multi", {"alpha": None})
        first = _ready(top / "alpha", theirs)
        second = _ready(_added(top, "beta", {"acme/alpha": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/beta": {}}), theirs)
        _away(work, "multi")
        mine()
        result = _run(work, monkeypatch, "run")
        clone = work / "multi"
        assert _said(result)[4:9] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/multi",
            f"     git clone https://example.org/acme/multi {_q(clone)}",
            f"     git -C {_q(clone)} checkout {first[:12]} && cd {_q(clone / 'alpha')} && chartbook run --snapshot",
            f"2. acme/beta at {second[:7]}    https://example.org/acme/multi; reads 1 above",
            f"     git -C {_q(clone)} checkout {second[:12]} && cd {_q(clone / 'beta')} && chartbook run --snapshot",
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
        assert [line for line in _said(result) if line.startswith(("1.", "2.", "     git", "     cd")) and "report" not in line] == [
            f"1. acme/alpha at {first[:7]}    https://example.org/acme/multi",
            f"     git clone https://example.org/acme/multi {_q(clone)}",
            f"     git -C {_q(clone)} checkout {first[:12]} && cd {_q(clone / 'alpha')} && chartbook run --snapshot",
            "2. acme/gamma    https://example.org/acme/multi",
            f"     git -C {_q(clone)} checkout {now[:12]} && cd {_q(clone / 'gamma')} && chartbook run --snapshot",
        ]
        done = _follow(work, result, monkeypatch)
        assert "not snapshotted" in done.stdout or "Ran build in 1 pipeline(s)." in done.stdout

    def test_a_folder_that_is_built_is_not_called_so_once_a_line_above_moves_it(self, work, theirs, mine, monkeypatch):
        top = _several(work, "multi", {"old": None})
        first = _ready(top / "old", theirs)
        new = _added(top, "new")
        report = _pipeline(work, "report", {"acme/old": {"path": "../multi/old"}})
        _ready(report, theirs)
        _write(report, _table("report", {"acme/old": {"path": "../multi/old"}, "acme/new": {"path": "../multi/new"}}))
        _git(report, "commit", "--quiet", "-am", "Reads new too")
        (new / "out.csv").write_text("a,b\nnew,1\n", encoding="utf-8", newline="\n")  # built, and never snapshotted
        now = _git(top, "rev-parse", "HEAD")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert [line for line in said if "acme/new" in line or "acme/old" in line or line.startswith("     git -C")] == [
            # By its key, `new` comes first: built where it stands, before anything moves
            f"1. acme/new    {os.path.join('..', 'multi', 'new')} (a folder on this machine, built already)",
            f"2. acme/old at {first[:7]}    {os.path.join('..', 'multi', 'old')} (a folder on this machine)",
            f"     git -C {_q(top)} checkout {first[:12]} && cd {_q(top / 'old')} && chartbook run --snapshot",
        ]
        assert now
        # And the other way round, as `said` is given them: after the line that moves the repository
        listing = missing.find(report, FolderStore(work / "mine"))
        listing.wanted.reverse()
        again = missing.said(listing, here=report)
        assert f"2. acme/new    {os.path.join('..', 'multi', 'new')} (a folder on this machine)" in again
        assert f"     git -C {_q(top)} checkout {now[:12]} && cd {_q(top / 'new')} && chartbook run --snapshot" in again


class TestACloneOnThisMachine:
    """A clone of a repository that sits beside the pipeline's own is read where it is, and nothing is fetched."""

    def test_it_is_read_and_nothing_is_fetched_or_cloned(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, "run")
        assert _said(result)[3:7] == [
            f"1. acme/rates at {commits['rates'][:7]}    {_up('rates')} (a clone of https://example.org/acme/rates)",
            f"     cd {_q(work / 'rates')} && chartbook run --snapshot",  # and it is on that commit
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a clone of https://example.org/acme/mid); reads 1 above",
            f"     cd {_q(work / 'mid')} && chartbook run --snapshot",
        ]
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")
        moved = _run(work, monkeypatch, "run")
        assert _said(moved)[4] == f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:12]} && chartbook run --snapshot"
        assert "Ran build in 1 pipeline(s)." in _follow(work, moved, monkeypatch).stdout

    def test_a_pipeline_in_a_folder_of_it_is_found_there(self, work, theirs, mine, monkeypatch):
        """Found by review: with the clone beside, the list still fetched, and said to clone into the folder that was there."""
        commit = _ready(_pipeline(work, "mid", within="pipelines/mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        assert _said(_run(work, monkeypatch, "run"))[3:5] == [
            f"1. acme/mid at {commit[:7]}    {os.path.join('..', 'mid', 'pipelines', 'mid')} (a clone of https://example.org/acme/mid)",
            f"     cd {_q(work / 'mid' / 'pipelines' / 'mid')} && chartbook run --snapshot",
        ]

    def test_one_that_lacks_the_commit_is_fetched_there(self, work, theirs, mine, monkeypatch):
        mid = _pipeline(work, "mid")
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        # A clone of it from before that commit was made
        mid.rename(work / "newer")
        _git(work, "clone", "--quiet", "--single-branch", str(work / "newer"), "mid")
        _git(mid, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        _git(mid, "update-ref", "-d", "refs/remotes/origin/main")
        _git(mid, "reset", "--quiet", "--hard", "HEAD~1")
        _git(mid, "reflog", "expire", "--expire=now", "--all")
        _git(mid, "gc", "--quiet", "--prune=now")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:7] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a clone of https://example.org/acme/mid)",
            f"     git -C {_q(work / 'mid')} fetch",
            f"     cd {_q(work / 'mid')} && git checkout {commit[:12]} && chartbook run --snapshot",
            f"     What it reads in turn is not known: its clone, {work / 'mid'}, does not have the commit {commit[:7]}; "
            f"if it is not at the top of its repository, `cd` to its folder there first. Its own `chartbook run` says.",
        ]

    def test_one_that_lacks_the_commit_is_built_in_the_folder_the_clone_has_it_in(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: after the fetch the list said to build at the top of the clone, where no pipeline is."""
        mid = _pipeline(work, "mid", within="pipelines/mid")
        top = work / "mid"
        _git(top, "commit", "--quiet", "--allow-empty", "-m", "On")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        # A clone of it from before that commit was made
        top.rename(work / "newer")
        _git(work, "clone", "--quiet", "--single-branch", str(work / "newer"), "mid")
        _git(top, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        _git(top, "update-ref", "-d", "refs/remotes/origin/main")
        _git(top, "reset", "--quiet", "--hard", "HEAD~1")
        _git(top, "reflog", "expire", "--expire=now", "--all")
        _git(top, "gc", "--quiet", "--prune=now")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:7] == [
            f"     git -C {_q(top)} fetch",
            f"     git -C {_q(top)} checkout {commit[:12]} && cd {_q(top / 'pipelines' / 'mid')} && chartbook run --snapshot",
            f"     What it reads in turn is not known: its clone, {top}, does not have the commit {commit[:7]}; "
            "its folder is where the clone has it now. Its own `chartbook run` says.",
        ]

    def test_a_folder_in_a_shallow_repository_is_told_to_deepen_it(self, work, theirs, mine, monkeypatch):
        """Found by the third pass: a `path` entry's folder there was still told a plain `git fetch`, which does not deepen it."""
        mid = _pipeline(work, "mid")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        _git(mid, "commit", "--quiet", "--allow-empty", "-m", "On")
        mid.rename(work / "whole")
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
        mid.rename(work / "whole")
        _git(work, "clone", "--quiet", "--depth", "1", (work / "whole").as_uri(), "mid")
        _git(mid, "remote", "set-url", "origin", "https://example.org/acme/mid.git")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:6] == [
            f"     git -C {_q(mid)} fetch --unshallow",
            f"     cd {_q(mid)} && git checkout {commit[:12]} && chartbook run --snapshot",
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
            f"     cd {_q(work / 'mid-2')} && chartbook run --snapshot",
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
            f"     cd {_q(mid)} && chartbook run --snapshot",
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
            f"     cd {_q(mid)} && chartbook run --snapshot",
        ]
        assert _said(result)[8] == (
            f"     What it reads in turn is not known: its clone, {mid}, has no commit yet; "
            "if it is not at the top of its repository, `cd` to its folder there first. Its own `chartbook run` says."
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
        assert _said(_run(work, monkeypatch, "run"))[4:7] == [
            f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid-2')}",
            f"     cd {_q(work / 'mid-2')} && git checkout {commit[:12]} && chartbook run --snapshot",
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
            f"     cd {_q(tree / 'mid')} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(top / 'report')} && chartbook run",
            SHARED.format("it"),
        ]
        head = _git(top, "rev-parse", "HEAD")
        done = _follow(work, result, monkeypatch, start=top / "report")
        assert "Ran build in 1 pipeline(s)." in done.stdout
        assert _git(top, "rev-parse", "HEAD") == head and _git(top, "symbolic-ref", "--short", "HEAD") == "main"

    def test_it_is_this_repository_whatever_its_folder_is_called(self, work, theirs, mine, monkeypatch):
        """Told by its `origin`, and not by a folder named as `git clone` would name it."""
        top, commit = self._made(work, theirs, {"acme/mid": {}})
        top.rename(work / "my-checkout")
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
            f"     cd {_q(tree / 'a')} && chartbook run --snapshot",
            f"     cd {_q(tree / 'b')} && chartbook run --snapshot",
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
            f"     cd {_q(second / 'mid')} && chartbook run --snapshot",
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
            f"     cd {_q(tree)} && chartbook run --snapshot",
            f"     What it reads in turn is not known: its clone, {report}, does not have the commit {commit[:7]}; "
            f"if it is not at the top of its repository, `cd` to its folder there first. Its own `chartbook run` says.",
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
            f"     cd {_q(top / 'mid')} && chartbook run --snapshot",
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
        ("C:\\work\\rates", "C:\\work\\rates"),
        ("C:\\my work\\rates", '"C:\\my work\\rates"'),
        ("https://example.org/acme/x&calc.exe", '"https://example.org/acme/x&calc.exe"'),
        ("https://dev.azure.com/org/My%20Project/_git/rates", '"https://dev.azure.com/org/My%20Project/_git/rates"'),
        ('a"b', '"a""b"'),
    ])
    def test_for_cmd_a_word_with_anything_it_reads_is_in_double_quotes(self, word, typed):
        """Found by the second pass (not run on Windows): `&` ends a command there, and the address that held one was printed bare.

        And by the third: a `%` was doubled, which is right in a batch file and wrong at a prompt, where these are pasted.
        """
        assert missing._quoted(word, windows=True) == typed

    def test_for_cmd_a_folder_is_entered_whatever_drive_it_is_on(self):
        """Found by the third pass (not run on Windows): a bare `cd` there does not change the drive, and the build ran where the prompt was."""
        assert missing._cd("D:\\class\\my rates", windows=True) == 'cd /d "D:\\class\\my rates"'
        assert missing._cd("/work/my rates", windows=False) == "cd '/work/my rates'"

    def test_a_folder_with_a_space_in_its_name_is_one_word_of_the_command(self, work, theirs, monkeypatch):
        spaced = work / "my rates"
        spaced.mkdir()
        _write(spaced, _table("rates"))
        _repository(spaced, "rates")
        _pipeline(work, "report", {"acme/rates": {"path": "../my rates"}})
        result = _run(work, monkeypatch, "run")
        assert f"     cd {_q(spaced)} && chartbook run --snapshot" in _said(result) and _q(spaced) != str(spaced)
        done = _follow(work, result, monkeypatch)
        assert "Ran build in 1 pipeline(s)." in done.stdout


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
        assert f"     git -C {_q(work / 'mono')} checkout {first[:12]} && cd {_q(work / 'mono' / 'current')} && chartbook run --snapshot" in said
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
        (work / "data").rename(work / "elsewhere" / "data")
        mine()
        result = _run(work, monkeypatch, "run")
        assert _numbered(result) == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]
        assert "not known" not in result.output  # and nothing is left unsaid of it

    def test_one_whose_pinned_files_are_all_in_the_store(self, work, theirs, mine, monkeypatch):
        """mid pinned a file of rates that this store has, of another pipeline that made the same bytes: mid's build can read it, and rates is not to build."""
        _ready(_pipeline(work, "rates"), theirs)
        commit = _ready(_pipeline(work, "mid", {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "rates", "mid")
        store = mine()
        twin = _pipeline(work, "twin")
        (twin / "out.csv").write_text("a,b\nrates,1\n", encoding="utf-8", newline="\n")
        snapshot.make(twin, store=store)
        assert _numbered(_run(work, monkeypatch, "run")) == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]

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
        assert said[-3:] == ["Then here again:", f"     cd {_q(work / 'report')} && chartbook pin", SHARED.format("them")]
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
