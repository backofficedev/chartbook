"""What a pipeline reads that is not in your store: the list, in the order to build it (``docs_src/design/one-command.md``).

A class with no shared store, a new laptop. The lockfile pins snapshots
this machine's store does not have, and each of those was built from
others it may not have either. ``chartbook run`` and ``chartbook pin``
say all that has to be built, each pipeline after everything it reads,
with what to type; ``pin --check`` and ``run --frozen``, which fetch
nothing, say what this pipeline lacks and where the list is.

Each test makes its pipelines against one store, as their owner would,
and then meets them with another that is empty.
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
from chartbook.gitcache import GitCache
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git



def _build(name: str) -> str:
    """A pipeline's build: it writes the one table the manifest declares, with rows of its own, and notes that it ran."""
    return f'"{sys.executable}" -c "open(\'out.csv\', \'w\').write(\'a,b\\\\n{name},1\\\\n\'); open(\'build.log\', \'a\').write(\'ran\\\\n\')"'


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def theirs(work, monkeypatch):
    """The store the pipelines are made against: their owner's. Each address a snapshot records is answered by the folder of that name."""
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "theirs"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    monkeypatch.setenv(config.GIT_CACHE_ENV_VAR, str(work / "git-cache"))
    (work / "gitconfig").write_text(
        f'[url "{work.as_posix()}/"]\n\tinsteadOf = https://example.org/acme/\n', encoding="utf-8", newline="\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(work / "gitconfig"))
    return FolderStore(work / "theirs")


def _pipeline(work: Path, name: str, reads: dict = None, remote: bool = True, within: str = "") -> Path:
    """A committed pipeline `acme/<name>` in a repository of its own, that depends on what *reads* says."""
    top = work / name
    directory = top / within if within else top
    directory.mkdir(parents=True)
    table = {
        "project": {"id": f"acme/{name}"}, "scripts": {"build": _build(name)},
        "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
    }
    if reads:
        table["dependencies"] = reads
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
    (top / ".gitignore").write_text("out.csv\nbuild.log\n", encoding="utf-8", newline="\n")
    _git(top, "init", "--quiet", "-b", "main")
    if remote:
        _git(top, "remote", "add", "origin", f"https://example.org/acme/{name}.git")
    _git(top, "add", "-A")
    _git(top, "commit", "--quiet", "-m", f"The pipeline {name}")
    return directory


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


def _said(result) -> list[str]:
    return result.output.splitlines()


def _q(path: Path) -> str:
    """A path as a command of the list has it: quoted where a shell needs it."""
    return shlex.quote(str(path))


def _up(name: str) -> str:
    """A folder beside the one a command was typed in, as this system writes it."""
    return os.path.join("..", name)


def _away(work: Path, *names: str) -> None:
    """These pipelines' folders are not on this machine: each is where its address leads, and nowhere a clone would be put."""
    (work / "elsewhere").mkdir(exist_ok=True)
    for name in names:
        (work / name).rename(work / "elsewhere" / name)
    (work / "gitconfig").write_text(
        f'[url "{(work / "elsewhere").as_posix()}/"]\n\tinsteadOf = https://example.org/acme/\n', encoding="utf-8", newline="\n"
    )


#: The list's last line: the other way on
SHARED = "Where a store is shared, nothing has to be built: point CHARTBOOK_STORE at the one that has {}, or wait for its sync to finish."
ONE = [
    "Build it first. It ends with a snapshot, which is what this one reads.",
    "",
]
SEVERAL = [
    "Build them in this order. Each ends with a snapshot, which is what the next one reads.",
    "",
]


def _run(work: Path, monkeypatch, *words: str, where: str = "report"):
    monkeypatch.chdir(work / where)
    return CliRunner().invoke(main, list(words))


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
            "acme/report cannot be built yet: 2 pipelines it reads are not in your store.",
            "Build them in this order. Each ends with a snapshot, which is what the next one reads.",
            "",
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"     git clone https://example.org/acme/rates {_q(work / 'rates')}",
            f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:7]} && chartbook run --snapshot",
            f"2. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid; reads 1 above",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:7]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
            SHARED.format("them"),
        ]
        # Nothing was built, and nothing written
        assert not (work / "report" / "build.log").exists()
        assert (work / "report" / lock.LOCK_FILE).read_bytes() == before

    def test_what_two_read_is_one_line(self, work, theirs, mine, monkeypatch):
        commits = {"rates": _ready(_pipeline(work, "rates"), theirs)}
        for name in ("a", "b"):
            commits[name] = _ready(_pipeline(work, name, {"acme/rates": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/a": {}, "acme/b": {}}), theirs)
        _away(work, "rates", "a", "b")
        mine()
        said = [line for line in _said(_run(work, monkeypatch, "run")) if line[:1].isdigit() or line.startswith("acme/report")]
        assert said == [
            "acme/report cannot be built yet: 3 pipelines it reads are not in your store.",
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"2. acme/a at {commits['a'][:7]}    https://example.org/acme/a; reads 1 above",
            f"3. acme/b at {commits['b'][:7]}    https://example.org/acme/b; reads 1 above",
        ]

    def test_a_line_names_each_line_above_that_it_reads(self, work, theirs, mine, monkeypatch):
        commits = {name: _ready(_pipeline(work, name), theirs) for name in ("a", "b")}
        commits["top"] = _ready(_pipeline(work, "top", {"acme/a": {}, "acme/b": {}}), theirs)
        _ready(_pipeline(work, "report", {"acme/top": {}}), theirs)
        _away(work, "a", "b", "top")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert f"3. acme/top at {commits['top'][:7]}    https://example.org/acme/top; reads 1 and 2 above" in said

    def test_what_the_store_has_a_build_of_is_not_on_it(self, work, theirs, mine, monkeypatch):
        """mid is not there. What mid reads is, as a build of mine of the commit mid pinned: whether it meets mid's pins is for mid's own run to say."""
        commits = _chain(work, theirs)
        _away(work, "mid")
        store = mine()
        (work / "rates" / "out.csv").write_text("a,b\nrates,2\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "rates", store=store)
        said = _said(_run(work, monkeypatch, "run"))
        assert said[1:] == [
            "acme/report cannot be built yet: 1 pipeline it reads is not in your store.",
            *ONE,
            f"1. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:7]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
            SHARED.format("it"),
        ]

    def test_following_it_ends_in_a_build(self, work, theirs, mine, monkeypatch):
        """Each line's commands, typed as they are printed, and then the last one: the pipeline builds."""
        _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        shim = work / "bin"
        shim.mkdir()
        if os.name == "nt":
            pytest.skip("the commands are for a POSIX shell")
        (shim / "chartbook").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -c "from chartbook.cli import main; main()" "$@"\n', encoding="utf-8", newline="\n"
        )
        (shim / "chartbook").chmod(0o755)
        environment = {**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
        commands = [line.strip() for line in _said(_run(work, monkeypatch, "run")) if line.startswith("     ")]
        assert len(commands) == 5 and commands[-1].endswith("&& chartbook run")
        for command in commands:
            done = subprocess.run(command, shell=True, cwd=work / "report", env=environment, capture_output=True, text=True)
            assert done.returncode == 0, f"{command}\n{done.stdout}{done.stderr}"
        assert "Ran build in 1 pipeline(s)." in done.stdout and (work / "report" / "build.log").exists()

    def test_nothing_is_read_or_fetched_where_every_pin_is_there(self, work, theirs, monkeypatch):
        _chain(work, theirs)
        monkeypatch.setattr(missing, "find", lambda *a, **k: pytest.fail("asked for the list"))
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 0, result.output
        assert _run(work, monkeypatch, "pin").exit_code == 0


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
            "acme/report cannot be built yet: 1 pipeline it reads is not in your store.",
            *ONE,
            f"1. acme/rates    {_up('rates')} (a folder on this machine)",
            f"     cd {_q(work / 'rates')} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
            "Or `chartbook run --upstream` here, which builds and snapshots this folder itself.",
            SHARED.format("it"),
        ]

    def test_of_a_folder_pinned_at_a_commit_it_has_left(self, work, theirs, mine, monkeypatch):
        """Its two files are read at the pinned commit, through git: what it read then is on the list, and its folder is as it was."""
        commits = {"rates": _ready(_pipeline(work, "rates"), theirs)}
        mid = _pipeline(work, "mid", {"acme/rates": {}})
        commits["mid"] = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        # Its owner has moved on, and reads nothing now
        table = {"project": {"id": "acme/mid"}, "scripts": {"build": _build("mid")}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}}
        (mid / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        _git(mid, "rm", "--quiet", "--cached", lock.LOCK_FILE)
        (mid / lock.LOCK_FILE).unlink()
        _git(mid, "commit", "--quiet", "-am", "Reads nothing now")
        now = _git(mid, "rev-parse", "HEAD")
        _away(work, "rates")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[1:] == [
            "acme/report cannot be built yet: 2 pipelines it reads are not in your store.",
            *SEVERAL,
            f"1. acme/rates at {commits['rates'][:7]}    https://example.org/acme/rates",
            f"     git clone https://example.org/acme/rates {_q(work / 'rates')}",
            f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:7]} && chartbook run --snapshot",
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a folder on this machine); reads 1 above",
            f"     cd {_q(work / 'mid')} && git checkout {commits['mid'][:7]} && chartbook run --snapshot",
            "",
            "Then here again:",
            f"     cd {_q(work / 'report')} && chartbook run",
            SHARED.format("them"),
        ]
        assert _git(mid, "rev-parse", "HEAD") == now and _git(mid, "status", "--porcelain") == ""

    def test_of_a_folder_that_is_on_the_commit_already(self, work, theirs, mine, monkeypatch):
        commit = _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {"path": "../mid"}}), theirs)
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        # Its files are on disk as well: a snapshot is all it lacks, and a build that may take an hour is not run again
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder on this machine, built already)",
            f"     cd {_q(work / 'mid')} && chartbook snapshot",
        ]
        assert not any("--upstream" in line for line in said)  # which builds what has no pin, and this has one
        (work / "mid" / "out.csv").unlink()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    {_up('mid')} (a folder on this machine)",
            f"     cd {_q(work / 'mid')} && chartbook run --snapshot",  # nothing to check out
        ]

    def test_whose_repository_could_not_be_fetched(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        (work / "gitconfig").write_text(
            f'[url "{(work / "nowhere").as_posix()}/"]\n\tinsteadOf = https://example.org/acme/\n', encoding="utf-8", newline="\n"
        )
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[:4] == [
            "Fetching https://example.org/acme/mid, to see what acme/mid reads in turn.",
            "acme/report cannot be built yet: 1 pipeline it reads is not in your store.",
            *ONE,
        ]
        assert said[4].startswith(f"1. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid")
        assert said[7].startswith("     What it reads in turn is not known: its repository could not be fetched (")
        assert said[7].endswith("). Its own `chartbook run` says.")

    def test_whose_repository_is_not_recorded(self, work, theirs, mine, monkeypatch):
        """A snapshot made in a repository with no remote records no address: the line has the ID to look for, and never a guess."""
        commit = _ready(_pipeline(work, "mid", remote=False), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        (work / "mid").rename(work / "mid-is-not-here")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:5] == [
            f"1. acme/mid at {commit[:7]}    its repository is not recorded, so neither is what it reads in turn",
            f"     In a clone of it: git checkout {commit[:7]} && chartbook run --snapshot",
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
        said = [line for line in _said(_run(work, monkeypatch, "run")) if line[:1].isdigit()]
        assert said[1] == "2. acme/mid    https://example.org/acme/mid; reads 1 above"
        assert said[0].startswith("1. acme/rates at ")  # as mid's own lockfile pins it

    def test_of_a_clone_that_is_there_already(self, work, theirs, mine, monkeypatch):
        """Beside the pipeline, where the list would have it cloned: it is read there, and nothing is fetched or cloned."""
        commits = _chain(work, theirs)
        mine()
        monkeypatch.setattr(GitCache, "fetch", lambda *a, **k: pytest.fail("fetched"))
        said = _said(_run(work, monkeypatch, "run"))
        assert said[3:7] == [
            f"1. acme/rates at {commits['rates'][:7]}    {_up('rates')} (a folder on this machine, built already)",
            f"     cd {_q(work / 'rates')} && chartbook snapshot",  # on that commit, with its files
            f"2. acme/mid at {commits['mid'][:7]}    {_up('mid')} (a folder on this machine, built already); reads 1 above",
            f"     cd {_q(work / 'mid')} && chartbook snapshot",
        ]
        _git(work / "rates", "commit", "--quiet", "--allow-empty", "-m", "On")
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4] == f"     cd {_q(work / 'rates')} && git checkout {commits['rates'][:7]} && chartbook run --snapshot"

    def test_a_folder_beside_it_of_another_pipeline_is_not_taken_for_its_clone(self, work, theirs, mine, monkeypatch):
        commit = _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        _pipeline(work / "another", "mid").rename(work / "mid")
        (work / "mid" / "chartbook.toml").write_text('[project]\nid = "acme/another"\n', encoding="utf-8", newline="\n")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid" in said

    def test_of_a_pipeline_in_a_folder_of_its_repository(self, work, theirs, mine, monkeypatch):
        commit = _ready(_pipeline(work, "mid", within="pipelines/mid"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert said[4:7] == [
            f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid",
            f"     git clone https://example.org/acme/mid {_q(work / 'mid')}",
            f"     cd {_q(work / 'mid' / 'pipelines' / 'mid')} && git checkout {commit[:7]} && chartbook run --snapshot",
        ]

    def test_of_two_pipelines_in_one_repository(self, work, theirs, mine, monkeypatch):
        """Fetched once, and each built in its own folder of the one clone."""
        top = work / "mono"
        for name in ("a", "b"):
            (top / name).mkdir(parents=True)
            (top / name / "chartbook.toml").write_text(
                tomli_w.dumps({"project": {"id": f"acme/{name}"}, "scripts": {"build": _build(name)}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}}),
                encoding="utf-8", newline="\n",
            )
        (top / ".gitignore").write_text("out.csv\nbuild.log\n", encoding="utf-8", newline="\n")
        _git(top, "init", "--quiet", "-b", "main")
        _git(top, "remote", "add", "origin", "https://example.org/acme/mono.git")
        _git(top, "add", "-A")
        _git(top, "commit", "--quiet", "-m", "Two pipelines")
        commit = [_ready(top / name, theirs) for name in ("a", "b")][0]
        _ready(_pipeline(work, "report", {"acme/a": {}, "acme/b": {}}), theirs)
        _away(work, "mono")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert [line for line in said if line.startswith("Fetching ")] == [
            "Fetching https://example.org/acme/mono, to see what acme/a reads in turn."
        ]
        assert said[4:9] == [
            f"1. acme/a at {commit[:7]}    https://example.org/acme/mono",
            f"     git clone https://example.org/acme/mono {_q(work / 'mono')}",
            f"     cd {_q(work / 'mono' / 'a')} && git checkout {commit[:7]} && chartbook run --snapshot",
            f"2. acme/b at {commit[:7]}    https://example.org/acme/mono",
            f"     cd {_q(work / 'mono' / 'b')} && git checkout {commit[:7]} && chartbook run --snapshot",  # cloned by the line before
        ]

    def test_of_a_pipeline_with_no_build_script(self, work, theirs, mine, monkeypatch):
        """It commits what it declares: nothing to run, and a snapshot to make."""
        mid = _pipeline(work, "mid")
        (mid / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/mid"}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}}),
            encoding="utf-8", newline="\n",
        )
        _git(mid, "commit", "--quiet", "-am", "No build script")
        commit = _ready(mid, theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}}), theirs)
        _away(work, "mid")
        mine()
        said = _said(_run(work, monkeypatch, "run"))
        assert f"     cd {_q(work / 'mid')} && git checkout {commit[:7]} && chartbook snapshot" in said

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
        assert f"     cd {_q(work / 'mid' / 'pipelines' / 'mid')} && git checkout {commit[:7]} && chartbook run --snapshot" in said

    def test_shows_what_a_lockfile_says_as_text_and_quotes_it_for_a_shell(self, work, theirs, mine, monkeypatch):
        """A lockfile is anyone's: an address in it is never a command, and never moves the cursor."""
        _ready(_pipeline(work, "mid"), theirs)
        report = _pipeline(work, "report", {"acme/mid": {}})
        _ready(report, theirs)
        document = json.loads((report / lock.LOCK_FILE).read_text(encoding="utf-8"))
        document["records"][0]["dependencies"][0]["location"]["repository"] = "https://example.org/acme/x; rm -rf ~ \x1b[2J"
        (report / lock.LOCK_FILE).write_text(json.dumps(document), encoding="utf-8", newline="\n")
        _away(work, "mid")
        mine()
        said = _run(work, monkeypatch, "run").output
        assert "\x1b" not in said
        assert "     git clone 'https://example.org/acme/x; rm -rf ~ [2J' " in said


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
        assert [line for line in _said(result) if line[:1].isdigit()] == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]
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
        said = [line for line in _said(_run(work, monkeypatch, "run")) if line[:1].isdigit()]
        assert said == [f"1. acme/mid at {commit[:7]}    https://example.org/acme/mid"]

    def test_what_a_pin_takes_or_gets_by_itself(self, work, theirs, monkeypatch):
        """Asked of each dependency by itself: a folder with a snapshot, a revision its repository is asked for, an ID with a host to clone it from."""
        _ready(_pipeline(work, "made"), theirs)
        _pipeline(work, "unmade")
        report = _pipeline(work, "report", {
            "acme/made": {"path": "../made"}, "acme/unmade": {"path": "../unmade"},
            "acme/by-rev": {"rev": "main"}, "acme/nowhere": {},
        })
        found = missing.find(report, theirs)
        assert [(line.pipeline, line.folder) for line in found.wanted] == [("acme/nowhere", None), ("acme/unmade", work / "unmade")]
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

    def test_with_other_things_that_could_not_be_pinned_both_are_said(self, work, theirs, mine, monkeypatch):
        _ready(_pipeline(work, "mid"), theirs)
        _ready(_pipeline(work, "other"), theirs)
        _ready(_pipeline(work, "report", {"acme/mid": {}, "acme/other": {}}), theirs)
        _away(work, "mid")
        store = mine()
        (work / "other" / "out.csv").write_text("a,b\nelse,9\n", encoding="utf-8", newline="\n")
        snapshot.make(work / "other", store=store)
        said = _said(_run(work, monkeypatch, "run"))
        assert "acme/report cannot be built yet: 1 pipeline it reads is not in your store." in said
        assert any(line.startswith("acme/other: ") for line in said) and not any(line.startswith("acme/mid: ") for line in said)
        assert said[-1] == "Error: acme/report: what it depends on could not be pinned. Nothing after it was run."
        pinned = _said(_run(work, monkeypatch, "pin"))
        assert "acme/report cannot be pinned yet: 1 pipeline it reads is not in your store." in pinned
        assert pinned[-1] == "1 other thing(s) could not be pinned."


class TestNoOrder:
    def test_a_cycle_is_an_error_in_the_words_a_run_has_for_one(self, work, theirs, mine, monkeypatch):
        """mid, which is not in the store, read this pipeline when it was built: there is no order to build the two in."""
        first = _ready(_pipeline(work, "report"), theirs)
        _ready(_pipeline(work, "mid", {"acme/report": {}}), theirs)
        report = work / "report"
        table = {
            "project": {"id": "acme/report"}, "scripts": {"build": _build("report")},
            "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}, "dependencies": {"acme/mid": {}},
        }
        (report / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
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
        mine()
        result = _run(work, monkeypatch, "run")
        assert result.exit_code == 1 and first
        said = _said(result)
        assert "Error: acme/report: these pipelines depend on each other, so there is no order to build in." in said
        assert f"  acme/report depends on acme/mid: declared in {report / 'chartbook.toml'}" in said
        assert any(line.startswith("  acme/mid depends on acme/report: declared in chartbook.toml of https://example.org/acme/mid at ") for line in said)
        assert "cannot be built yet" not in result.output and not (report / "build.log").exists()
        pinned = _run(work, monkeypatch, "pin")
        assert pinned.exit_code == 1
        assert "Error: acme/report: these pipelines depend on each other, so there is no order to build in." in _said(pinned)

    def test_add_does_not_add_what_leads_into_one(self, work, theirs, monkeypatch):
        """mid has no snapshot, and its folder beside this one says it reads this pipeline: the entry is taken out again."""
        report = _pipeline(work, "report")
        _pipeline(work, "mid", {"acme/report": {}})
        before = (report / "chartbook.toml").read_bytes()
        result = _run(work, monkeypatch, "add", "acme/mid")
        assert result.exit_code == 1
        assert "Error: acme/report: these pipelines depend on each other, so there is no order to build in." in _said(result)
        assert f"  acme/mid depends on acme/report: declared in {work / 'mid' / 'chartbook.toml'}" in _said(result)
        assert (report / "chartbook.toml").read_bytes() == before


class TestTheOtherCommands:
    def test_pin_makes_the_list_too(self, work, theirs, mine, monkeypatch):
        commits = _chain(work, theirs)
        _away(work, "rates", "mid")
        mine()
        result = _run(work, monkeypatch, "pin")
        assert result.exit_code == 1
        said = _said(result)
        assert said[2] == "acme/report cannot be pinned yet: 2 pipelines it reads are not in your store."
        assert said[-3:] == ["Then here again:", f"     cd {_q(work / 'report')} && chartbook pin", SHARED.format("them")]
        assert f"2. acme/mid at {commits['mid'][:7]}    https://example.org/acme/mid; reads 1 above" in said
        assert not any("could not be pinned" in line or line.startswith("acme/mid:") for line in said)

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
        assert listing.keys == {"acme/mid"} and listing.root == "acme/report"


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
