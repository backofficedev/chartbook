"""``chartbook pin --update`` is what ``chartbook update`` was, and ``chartbook update`` is gone (``docs_src/design/one-command.md``).

``pin`` is the word for the lockfile: ``chartbook pin`` pins what has no
pin yet, ``chartbook pin --update [NAME…]`` moves pins to the newest
snapshot, and ``chartbook pin --check`` says whether everything pinned can
be read here. ``chartbook update`` read as "update ChartBook". The flag
``pin --frozen``, the name ``pin --check`` had through 0.5.1, is gone with
it, and is not kept beside the new one.

What a pin and an update do to a lockfile is in ``tests/test_lock.py``;
this is the command.
"""

import os
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import config, lock, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def store(work, monkeypatch):
    monkeypatch.setenv(config.STORE_ENV_VAR, str(work / "store"))
    monkeypatch.setenv(config.CACHE_ENV_VAR, str(work / "cache"))
    return FolderStore(work / "store")


def _pipeline(directory: Path, table: dict) -> Path:
    directory.mkdir(parents=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
    (directory / ".gitignore").write_text("/out.csv\n/chartbook.lock\n", encoding="utf-8", newline="\n")
    _git(directory, "init", "--quiet", "-b", "main")
    _git(directory, "add", "-A")
    _git(directory, "commit", "--quiet", "-m", "Work")
    return directory


def _upstream(work: Path, store, name: str) -> Path:
    directory = _pipeline(work / name, {"project": {"id": f"acme/{name}"}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}}})
    _snapshot(directory, store, "1,2")
    return directory


def _snapshot(directory: Path, store, rows: str) -> None:
    """A newer snapshot of an upstream, of other bytes."""
    (directory / "out.csv").write_text(f"a,b\n{rows}\n", encoding="utf-8", newline="\n")
    snapshot.make(directory, store=store)


@pytest.fixture
def consumer(work, store, monkeypatch):
    """A pipeline that depends on two others and has pinned both. Commands are run in it."""
    _upstream(work, store, "rates")
    _upstream(work, store, "prices")
    directory = _pipeline(work / "consumer", {
        "project": {"id": "acme/consumer"},
        "dependencies": {"acme/rates": {}, "acme/prices": {}},
    })
    monkeypatch.chdir(directory)
    assert CliRunner().invoke(main, ["pin"]).exit_code == 0
    return directory


def _pinned(directory: Path) -> dict:
    """The snapshot each dependency is pinned to, by the dependency's ID."""
    return {entry["id"]: entry["snapshot"] for entry in lock.read_lock(directory / lock.LOCK_FILE).dependencies}


class TestPinUpdate:
    def test_moves_every_pin_to_the_newest_snapshot(self, consumer, work, store):
        before = _pinned(consumer)
        _snapshot(work / "rates", store, "3,4")
        _snapshot(work / "prices", store, "5,6")
        result = CliRunner().invoke(main, ["pin", "--update"])
        assert result.exit_code == 0, result.output
        assert "Wrote chartbook.lock." in result.output
        after = _pinned(consumer)
        assert after["acme/rates"] != before["acme/rates"] and after["acme/prices"] != before["acme/prices"]

    def test_named_it_moves_those_alone(self, consumer, work, store):
        before = _pinned(consumer)
        _snapshot(work / "rates", store, "3,4")
        _snapshot(work / "prices", store, "5,6")
        # By its ID, or by its name where only one dependency has it
        result = CliRunner().invoke(main, ["pin", "--update", "rates"])
        assert result.exit_code == 0, result.output
        after = _pinned(consumer)
        assert after["acme/rates"] != before["acme/rates"] and after["acme/prices"] == before["acme/prices"]

    def test_a_plain_pin_moves_nothing_and_says_what_does(self, consumer, work, store):
        before = _pinned(consumer)
        _snapshot(work / "rates", store, "3,4")
        result = CliRunner().invoke(main, ["pin"])
        assert result.exit_code == 0, result.output
        assert _pinned(consumer) == before
        assert "`chartbook pin --update` moves the pins." in result.output

    def test_a_name_without_it_is_not_taken_for_a_move(self, consumer, work, store):
        before = _pinned(consumer)
        _snapshot(work / "rates", store, "3,4")
        result = CliRunner().invoke(main, ["pin", "rates"])
        assert result.exit_code == 2
        assert (
            "Error: A name goes with --update: `chartbook pin --update rates` moves the pins of what it names. "
            "`chartbook pin` pins what has no pin yet, of every dependency."
        ) in result.output.splitlines()
        assert _pinned(consumer) == before

    def test_what_it_says_to_type_can_be_pasted(self, consumer, work, monkeypatch):
        """With the folder it was given, and each word quoted as a shell takes it."""
        monkeypatch.chdir(work)
        result = CliRunner().invoke(main, ["pin", "rates", "a b", "--project-dir", "consumer"])
        assert result.exit_code == 2
        # A word with a space, as this system's shells take it: cmd.exe reads no single quotes
        spaced = '"a b"' if os.name == "nt" else "'a b'"
        assert f"`chartbook pin --update rates {spaced} --project-dir consumer` moves the pins of what it names." in result.output

    def test_a_folder_where_a_name_goes_is_taken_for_the_pipeline_meant(self, consumer, work, monkeypatch):
        """Found by review: `chartbook pin ../prices` was answered with `pin --update ../prices`, which names no dependency."""
        monkeypatch.chdir(work)
        result = CliRunner().invoke(main, ["pin", "consumer"])
        assert result.exit_code == 2
        assert (
            "Error: consumer is a folder, and a pipeline is named with --project-dir: `chartbook pin --project-dir consumer`."
        ) in result.output.splitlines()
        # And one whose name a shell would split is one word of the command
        (work / "my consumer").mkdir()
        spaced = '"my consumer"' if os.name == "nt" else "'my consumer'"
        assert f"`chartbook pin --project-dir {spaced}`." in CliRunner().invoke(main, ["pin", "my consumer"]).output

    def test_the_check_takes_no_name(self, consumer):
        """Found by review: asked for the check that writes nothing, it answered with a command that moves a pin."""
        before = _pinned(consumer)
        result = CliRunner().invoke(main, ["pin", "--check", "rates"])
        assert result.exit_code == 2
        assert (
            "Error: --check takes no name: it says whether every pin of the pipeline can be read here, and writes nothing."
        ) in result.output.splitlines()
        assert "--update" not in result.output and _pinned(consumer) == before

    def test_it_does_not_go_with_the_check(self, consumer):
        result = CliRunner().invoke(main, ["pin", "--update", "--check"])
        assert result.exit_code == 2
        assert "Error: --update moves pins and --check writes nothing. One or the other." in result.output.splitlines()

    def test_the_check_writes_nothing_as_before(self, consumer, store):
        def written() -> dict:
            """Every file of the lockfile's folder and of the store's notes, by its bytes."""
            return {
                str(path): path.read_bytes()
                for top in (consumer, store.root / "_chartbook" / "roots") for path in sorted(top.rglob("*"))
                if path.is_file() and ".git" not in path.parts
            }

        # A note of this lockfile from a pin before, which a check that left one would write again
        (note,) = (store.root / "_chartbook" / "roots").iterdir()
        note.unlink()
        before = written()
        result = CliRunner().invoke(main, ["pin", "--check"])
        assert result.exit_code == 0, result.output
        assert "Nothing written." in result.output and written() == before


class TestTheOldCommand:
    @pytest.mark.parametrize("words, tried", [
        (["update"], "chartbook pin --update"),
        (["update", "rates"], "chartbook pin --update rates"),
        (["update", "rates", "prices", "--project-dir", "x"], "chartbook pin --update rates prices --project-dir x"),
        # Quoted as this system's shells take it, so that the line can be pasted: on Windows in double quotes,
        # which cmd.exe reads and single ones it does not (found by running this there, 2026-11-20)
        (
            ["update", "--project-dir", "../my dir", "it's"],
            """chartbook pin --update --project-dir "../my dir" "it's\"""" if os.name == "nt"
            else """chartbook pin --update --project-dir '../my dir' 'it'"'"'s'""",
        ),
        # Its help was asked for: that of the command it became, not a line that moves every pin
        (["update", "--help"], "chartbook pin --help"),
        (["update", "rates", "-h"], "chartbook pin --help"),
    ])
    def test_says_where_it_went_with_what_to_type(self, consumer, work, store, words, tried):
        before = _pinned(consumer)
        _snapshot(work / "rates", store, "3,4")
        result = CliRunner().invoke(main, words)
        assert result.exit_code == 2
        assert (
            "Error: `chartbook update` is gone: `chartbook pin --update`. It moves pins to the newest snapshot, all of them "
            f"or those of the dependencies named. Try: {tried}"
        ) in result.output.splitlines()
        assert _pinned(consumer) == before  # and it moved nothing

    def test_is_not_offered(self):
        listed = CliRunner().invoke(main, ["--help"]).output
        assert not any(line.split()[:1] == ["update"] for line in listed.splitlines())

    @pytest.mark.parametrize("words", [["run", "update"], ["path", "update"], ["pin", "--update", "update"]])
    def test_only_as_the_command_is_the_word_refused(self, consumer, words):
        """Elsewhere than first it is a script, an asset or a dependency of that name."""
        assert "is gone" not in CliRunner().invoke(main, words).output

    def test_completion_is_not_stopped_by_it(self):
        with main.make_context("chartbook", ["update"], resilient_parsing=True):
            pass


class TestTheOldFlag:
    """`pin --frozen` was this check through 0.5.1, and also left the store's note. It is `pin --check` now, and the old name is not kept."""

    @pytest.mark.parametrize("words", [["pin", "--frozen"], ["pin", "--check", "--frozen"], ["pin", "--frozen", "--project-dir", "."]])
    def test_says_what_does_each_half_of_it(self, consumer, store, words):
        notes = sorted(path.name for path in (store.root / "_chartbook" / "roots").iterdir())
        result = CliRunner().invoke(main, words)
        assert result.exit_code == 2
        assert (
            "Error: `chartbook pin --frozen` is gone. `chartbook pin --check` says whether everything pinned can be read "
            "here, and writes nothing; `chartbook run --frozen` builds from the lockfile, and leaves the store's note that "
            "this machine reads these pins."
        ) in result.output.splitlines()
        assert sorted(path.name for path in (store.root / "_chartbook" / "roots").iterdir()) == notes

    def test_help_offers_update_and_check_and_not_it(self):
        said = CliRunner().invoke(main, ["pin", "--help"]).output
        assert "--update" in said and "--check" in said and "--frozen`" in said  # `chartbook run --frozen`, in the prose
        options = said[said.index("Options:"):]
        assert "--update" in options and "--check" in options and "--frozen" not in options

    def test_a_run_keeps_its_own(self, consumer):
        """`chartbook run --frozen` is another thing, and stays."""
        assert "--frozen" in CliRunner().invoke(main, ["run", "--help"]).output
