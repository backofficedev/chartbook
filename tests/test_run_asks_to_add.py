"""``chartbook run`` offers to declare a pipeline that code reads and the manifest does not (``docs_src/design/one-command.md``).

A person writes ``data.load("acme/rates:treasury")`` and runs. Nothing
was declared, so the build's read is refused, as it always was; the read
leaves a note of which pipeline it asked for, and the run, at a terminal,
asks whether to add it to ``[dependencies]``. Yes does what ``chartbook
add`` does and builds again. Nobody has to know ``chartbook add``.

It asks only where yes can work: a person is there, the run is a plain
one, the read was made from this pipeline's own folder, and the stores
have exactly one pipeline of that name. Otherwise the build's own error
stands, as before.
"""

import json
import os
import sys
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import cli, config, resolve, run, snapshot
from chartbook.cli import main
from chartbook.store import FolderStore
from tests.test_lock_by_kind import _git

#: A build that reads each reference it is given, then writes the one table its manifest declares
READS = """\
import sys
from pathlib import Path
from chartbook import data

for reference in sys.argv[1:]:
    data.path(reference)
Path("out.csv").write_text("a,b\\n", encoding="utf-8")
"""
ASKS = "Add it to [dependencies] and build again? [Y/n]: "


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
    (directory / ".gitignore").write_text("/out.csv\n/build.log\n", encoding="utf-8", newline="\n")
    (directory / "build.py").write_text(READS, encoding="utf-8", newline="\n")
    _git(directory, "init", "--quiet", "-b", "main")
    _git(directory, "add", "-A")
    _git(directory, "commit", "--quiet", "-m", "Work")
    return directory


def _stored(work: Path, store, pipeline_id: str) -> Path:
    """Another pipeline, with one snapshot in the store."""
    directory = _pipeline(work / pipeline_id.replace("/", "-"), {
        "project": {"id": pipeline_id}, "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
    })
    (directory / "out.csv").write_text("a,b\n1,2\n", encoding="utf-8", newline="\n")
    snapshot.make(directory, store=store)
    return directory


def _reading(work: Path, monkeypatch, *references: str, name: str = "report") -> Path:
    """A committed pipeline whose build reads these references and declares none of their pipelines. Commands are run in it."""
    command = f'"{sys.executable}" build.py ' + " ".join(references) + " && echo ran >> build.log"
    directory = _pipeline(work / name, {
        "project": {"id": f"acme/{name}"}, "scripts": {"build": command},
        "dataframes": {"out": {"path": "./out.csv", "docs": "d"}},
    })
    monkeypatch.chdir(directory)
    return directory


def _noting(directory: Path, *notes: dict, exits: int = 1, writes: bool = False) -> None:
    """Make a pipeline's build one that notes these reads as refused, where it is told of a file to note them in, and exits."""
    lines = "".join(json.dumps(note) + "\n" for note in notes)
    (directory / "build.py").write_text(
        "import os, sys\n"
        f"named = os.environ.get({resolve.UNDECLARED_ENV_VAR!r})\n"
        "if named:\n"
        f"    open(named, 'a', encoding='utf-8').write({lines!r})\n"
        + ("open('out.csv', 'w').write('a,b\\n')\n" if writes else "")
        + f"sys.exit({exits})\n",
        encoding="utf-8", newline="\n",
    )


def _note(directory: Path, pipeline: str) -> dict:
    return {"pipeline": pipeline, "reference": f"{pipeline}:out", "from": str(directory)}


@pytest.fixture
def at_a_terminal(monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)


def _declared(directory: Path) -> dict:
    return tomli.loads((directory / "chartbook.toml").read_text(encoding="utf-8")).get("dependencies") or {}


def _built(directory: Path) -> int:
    log = directory / "build.log"
    return len(log.read_text(encoding="utf-8").split()) if log.exists() else 0


class TestAtATerminal:
    def test_yes_adds_it_pins_it_and_builds_again(self, work, store, monkeypatch, at_a_terminal):
        rates = _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        commit = _git(rates, "rev-parse", "HEAD")
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert result.exit_code == 0, result.output
        said = result.output.splitlines()
        asked = said.index("acme/report: its code reads from a pipeline that chartbook.toml does not declare:")
        assert said[asked + 1] == f"  acme/rates   (in your store: 1 snapshot, the newest of {commit[:7]})"
        assert said[asked + 2].startswith(ASKS)
        # What `chartbook add` says and does
        assert f'Added to [dependencies] in {report / "chartbook.toml"}: "acme/rates" = {{}}' in said
        assert "acme/rates: 1 pinned" in said and "Wrote chartbook.lock." in said
        assert _declared(report) == {"acme/rates": {}}
        # And the build again, which reads what was pinned
        assert said.count("acme/report: build") == 2 and _built(report) == 1
        assert "Ran build in 1 pipeline(s)." in said and "Error" not in result.output
        # The manifest has just changed, and the lockfile is new: this run makes no snapshot, and says so
        assert said[-2:] == [
            "acme/report: not snapshotted: 2 files are not committed (`git status` lists them).",
            "  A snapshot is of a commit: commit, and `chartbook run` again.",
        ]

    def test_enter_is_yes(self, work, store, monkeypatch, at_a_terminal):
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        result = CliRunner().invoke(main, ["run"], input="\n")
        assert result.exit_code == 0, result.output
        assert _declared(report) == {"acme/rates": {}}

    @pytest.mark.parametrize("answer", ["n\n", ""])
    def test_no_leaves_the_builds_error_and_the_manifest_as_they_were(self, work, store, monkeypatch, at_a_terminal, answer):
        """And so does the end of input, or Ctrl-C."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        before = (report / "chartbook.toml").read_bytes()
        result = CliRunner().invoke(main, ["run"], input=answer)
        assert result.exit_code == 1
        assert "Error: acme/report: its 'build' script exited with 1. Nothing after it was run." in result.output.splitlines()
        assert (report / "chartbook.toml").read_bytes() == before and not (report / "chartbook.lock").exists()
        assert _built(report) == 0

    def test_one_pipeline_at_a_time(self, work, store, monkeypatch, at_a_terminal):
        """A build stops at the first read it is refused, so the second is asked of when the build is run again."""
        _stored(work, store, "acme/rates")
        _stored(work, store, "acme/prices")
        report = _reading(work, monkeypatch, "acme/rates:out", "acme/prices:out")
        result = CliRunner().invoke(main, ["run"], input="y\ny\n")
        assert result.exit_code == 0, result.output
        assert result.output.count("its code reads from a pipeline that chartbook.toml does not declare:") == 2
        assert _declared(report) == {"acme/rates": {}, "acme/prices": {}} and _built(report) == 1

    def test_the_first_read_refused_is_the_one_asked_of(self, work, store, monkeypatch, at_a_terminal):
        _stored(work, store, "acme/rates")
        _stored(work, store, "acme/prices")
        report = _reading(work, monkeypatch)
        _noting(report, _note(report, "acme/rates"), _note(report, "acme/rates"), _note(report, "acme/prices"))
        found = run.run(report, echo=lambda line: None)
        assert found.undeclared == ["acme/rates", "acme/prices"]  # each once, in the order they were refused
        result = CliRunner().invoke(main, ["run"], input="n\n")
        assert "  acme/rates   (in your store: " in result.output and "  acme/prices   " not in result.output

    def test_a_build_that_went_on_past_the_read_and_wrote_less_is_asked_of_too(self, work, store, monkeypatch, at_a_terminal):
        """Found by review: a build that swallowed the refusal and exited 0 failed for the output it then lacked, and its note was thrown away."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch)
        _noting(report, _note(report, "acme/rates"), exits=0)
        result = CliRunner().invoke(main, ["run"], input="n\n")
        assert result.exit_code == 1
        assert "acme/report: its code reads from a pipeline that chartbook.toml does not declare:" in result.output.splitlines()
        assert "its build did not write 1 thing chartbook.toml declares: out (./out.csv)" in result.output

    def test_the_build_again_is_the_same_run_but_for_force(self, work, store, monkeypatch, at_a_terminal):
        """Found by review: with --force, each yes built every git dependency once more. What --force rebuilds was rebuilt a moment before."""
        _stored(work, store, "acme/rates")
        _reading(work, monkeypatch, "acme/rates:out")
        seen = []
        real = run.run

        def watched(*arguments, **options):
            seen.append({key: options.get(key) for key in ("force", "frozen", "remake", "upstream", "snapshot")})
            return real(*arguments, **options)

        monkeypatch.setattr(run, "run", watched)
        result = CliRunner().invoke(main, ["run", "--force", "--remake", "--upstream"], input="y\n")
        assert result.exit_code == 0, result.output
        first, again = seen
        assert first == {"force": True, "frozen": False, "remake": True, "upstream": True, "snapshot": run.WHEN_COMMITTED}
        assert again == {**first, "force": False}

    @pytest.mark.skipif(os.name == "nt", reason="chmod does not make a file read-only to its owner's write on Windows")
    def test_a_manifest_that_cannot_be_written_is_said_and_is_no_traceback(self, work, store, monkeypatch, at_a_terminal):
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        (report / "chartbook.toml").chmod(0o444)
        try:
            result = CliRunner().invoke(main, ["run"], input="y\n")
        finally:
            (report / "chartbook.toml").chmod(0o644)
        assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
        assert f"Error: {report / 'chartbook.toml'} could not be written: " in result.output
        assert _declared(report) == {}

    def test_a_build_that_is_another_script_of_the_run(self, work, store, monkeypatch, at_a_terminal):
        """Found by review: `build = "chartbook run analyze"` was refused its read with an error that said a run offers, and no run offered."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        table = tomli.loads((report / "chartbook.toml").read_text(encoding="utf-8"))
        table["scripts"] = {"analyze": table["scripts"]["build"], "build": f'"{sys.executable}" -m chartbook.cli run analyze'}
        (report / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        _git(report, "commit", "--quiet", "-am", "The build runs another script")
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert "acme/report: its code reads from a pipeline that chartbook.toml does not declare:" in result.output.splitlines()
        assert _declared(report) == {"acme/rates": {}}
        assert result.exit_code == 0, result.output

    def test_a_folder_named_in_another_letter_case(self, work, store, monkeypatch, at_a_terminal):
        """Found by review: the read names its folder as the disk does, and the run was given it otherwise."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        other = report.parent / "REPORT"
        if not other.is_dir():
            pytest.skip("this disk tells letter cases apart")
        monkeypatch.chdir(work)
        result = CliRunner().invoke(main, ["run", "--project-dir", str(other)], input="n\n")
        assert "acme/report: its code reads from a pipeline that chartbook.toml does not declare:" in result.output.splitlines()

    def test_a_bare_name_is_the_one_pipeline_the_stores_have_of_it(self, work, store, monkeypatch, at_a_terminal):
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "rates:out")
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert "  acme/rates   (in your store: 1 snapshot, the newest of " in result.output
        assert _declared(report) == {"acme/rates": {}}
        assert result.exit_code == 0, result.output  # and `rates:out` reads it, the scope left off

    def test_a_build_that_goes_on_failing_is_asked_of_once(self, work, store, monkeypatch, at_a_terminal):
        """The same pipeline is never offered twice in one command: the second failure is the build's own."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        _noting(report, _note(report, "acme/rates"), exits=3)
        result = CliRunner().invoke(main, ["run"], input="y\ny\n")
        assert result.exit_code == 3
        assert result.output.count("its code reads from a pipeline that chartbook.toml does not declare:") == 1
        assert "Error: acme/report: its 'build' script exited with 3. Nothing after it was run." in result.output.splitlines()
        assert _declared(report) == {"acme/rates": {}}  # what was added at the yes stays


class TestTheQuestion:
    """It comes after a build, which may have run for minutes: it is asked of who is there now."""

    @pytest.mark.skipif(os.name == "nt", reason="the terminal is emptied by another call on Windows")
    def test_keys_pressed_before_it_are_thrown_away_and_ctrl_c_ends_the_read(self, monkeypatch):
        """Found by review: an Enter typed while the build ran was a yes, and Ctrl-C did nothing until Enter once polars was loaded."""
        import signal
        import termios

        import click

        done = []
        monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
        monkeypatch.setattr(sys, "stdin", type("ATerminal", (), {"fileno": lambda self: 7})())
        monkeypatch.setattr(termios, "tcflush", lambda descriptor, queue: done.append(("emptied", descriptor, queue)))
        monkeypatch.setattr(signal, "siginterrupt", lambda number, flag: done.append(("interrupts", number, flag)))

        def asked(question, default, err):
            done.append(("asked", question, default, err))
            return False

        monkeypatch.setattr(click, "confirm", asked)
        assert cli._confirm("Add it?", default=True) is False
        assert done == [
            ("interrupts", signal.SIGINT, True),
            ("emptied", 7, termios.TCIFLUSH),  # what was typed and not yet read, and nothing written
            ("asked", "Add it?", True, True),  # on stderr, after both
        ]

    def test_where_input_is_no_terminal_nothing_is_thrown_away(self, monkeypatch):
        """A pipe's lines are the answers meant for it."""
        import click

        monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)
        monkeypatch.setattr(sys, "stdin", type("APipe", (), {"fileno": lambda self: pytest.fail("looked at")})())
        monkeypatch.setattr(click, "confirm", lambda question, default, err: True)
        assert cli._confirm("Add it?", default=False) is True


class TestWhereYesCannotWork:
    """No question: the build's own error stands, and nothing is written."""

    def _refused(self, result, report) -> None:
        assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.output
        assert "Nothing after it was run." in result.output  # the build's own failure, said as ever
        assert "does not declare:" not in result.output and ASKS not in result.output
        assert _declared(report) == {} and _built(report) == 0

    def test_with_no_one_there(self, work, store, monkeypatch):
        """A script, a pipe, CI: nobody to ask."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    @pytest.mark.parametrize("flag", ["--frozen", "--snapshot"])
    def test_in_a_run_that_writes_no_manifest(self, work, store, monkeypatch, at_a_terminal, flag):
        """--frozen writes nothing, and --snapshot cannot end with a snapshot of a manifest it has just changed."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        self._refused(CliRunner().invoke(main, ["run", flag], input="y\n"), report)

    def test_for_a_pipeline_the_stores_do_not_have(self, work, store, monkeypatch, at_a_terminal):
        """A folder or a repository is declared by hand: `chartbook add` would write a name that cannot be pinned."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/nowhere:out")
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_for_a_name_two_pipelines_share(self, work, store, monkeypatch, at_a_terminal):
        _stored(work, store, "acme/rates")
        _stored(work, store, "other/rates")
        report = _reading(work, monkeypatch, "rates:out")
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_for_a_read_made_from_another_pipelines_folder(self, work, store, monkeypatch, at_a_terminal):
        """Another pipeline's manifest is not this run's to write."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch)
        (work / "elsewhere").mkdir()
        _noting(report, _note(work / "elsewhere", "acme/rates"))
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_for_another_script(self, work, store, monkeypatch, at_a_terminal):
        """Only a build is asked about: another script is told of no file to note a read in, whatever it does."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        _noting(report, _note(report, "acme/rates"))
        table = tomli.loads((report / "chartbook.toml").read_text(encoding="utf-8"))
        table["scripts"]["look"] = f'"{sys.executable}" build.py'
        (report / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        result = CliRunner().invoke(main, ["run", "look"], input="y\n")
        assert result.exit_code == 1 and ASKS not in result.output and _declared(report) == {}

    def test_for_an_id_two_repositories_claim(self, work, store, monkeypatch, at_a_terminal):
        """Found by review: it was offered, and yes left an entry that could not be pinned. Which repository is meant is said by hand."""
        for owner in ("alice", "bob"):
            # Two repositories, each with a first commit of its own (one first commit would be a fork, taken as one)
            directory = _pipeline(work / owner, {"project": {"id": "acme/rates"}, "dataframes": {"out": {"path": "./out.csv", "docs": owner}}})
            _git(directory, "remote", "add", "origin", f"https://example.org/{owner}/rates.git")
            (directory / "out.csv").write_text(f"a,b\n{owner},1\n", encoding="utf-8", newline="\n")
            snapshot.make(directory, store=store)
        report = _reading(work, monkeypatch, "acme/rates:out")
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_for_a_read_of_the_pipeline_itself(self, work, store, monkeypatch, at_a_terminal):
        report = _reading(work, monkeypatch)
        (report / "out.csv").write_text("a,b\n", encoding="utf-8", newline="\n")
        snapshot.make(report, store=store)
        (report / "out.csv").unlink()
        _noting(report, _note(report, "acme/report"))
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_where_the_stores_cannot_be_read(self, work, store, monkeypatch, at_a_terminal):
        from chartbook.store import StoreError

        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")

        def unreadable(self):
            raise StoreError("the store's notes cannot be read")

        monkeypatch.setattr(cli._StoredIds, "_stores", unreadable)
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)


class TestTheNote:
    def test_the_run_knows_which_pipeline_was_asked_for(self, work, store, monkeypatch):
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        found = run.run(report, echo=lambda line: None)
        assert found.failed is not None and found.exit_code == 1
        assert found.undeclared == ["acme/rates"]

    def test_a_build_that_fails_for_another_reason_names_none(self, work, store, monkeypatch):
        report = _reading(work, monkeypatch)
        (report / "build.py").write_text("import sys\nsys.exit(2)\n", encoding="utf-8", newline="\n")
        found = run.run(report, echo=lambda line: None)
        assert found.exit_code == 2 and found.undeclared == []

    def test_the_file_is_this_scripts_own_and_is_gone_after(self, work, monkeypatch):
        """Never another run's: a build that ChartBook starts inside a build gets a file of its own."""
        monkeypatch.setenv(resolve.UNDECLARED_ENV_VAR, str(work / "an-outer-runs.jsonl"))
        seen = work / "seen.txt"
        script = f'"{sys.executable}" -c "import os; open({str(seen)!r}, \'w\').write(os.environ.get({resolve.UNDECLARED_ENV_VAR!r}, \'\'))"'
        noted: list = []
        assert run.execute(script, work, "build", undeclared=noted) == 0
        named = seen.read_text(encoding="utf-8")
        assert named and named != str(work / "an-outer-runs.jsonl") and not os.path.exists(named)
        # A script that is not asked about is left with the file of the run that started it, if one did
        assert run.execute(script, work, "test") == 0
        assert seen.read_text(encoding="utf-8") == str(work / "an-outer-runs.jsonl")
        monkeypatch.delenv(resolve.UNDECLARED_ENV_VAR)
        assert run.execute(script, work, "test") == 0
        assert seen.read_text(encoding="utf-8") == ""

    def test_what_a_script_noted_is_passed_to_the_run_that_started_it(self, work, monkeypatch):
        outer = work / "an-outer-runs.jsonl"
        outer.write_text("", encoding="utf-8")
        monkeypatch.setenv(resolve.UNDECLARED_ENV_VAR, str(outer))
        note = _note(work, "acme/rates")
        _noting(work, note, exits=0)
        noted: list = []
        assert run.execute(f'"{sys.executable}" build.py', work, "build", undeclared=noted) == 0
        assert noted == [note] and run._undeclared_reads(str(outer)) == [note]

    def test_a_file_that_is_gone_is_not_made_again(self, work, monkeypatch):
        """Found by review: a process the build left behind made the file again after the run had removed it, for good."""
        gone = work / "removed-by-its-run.jsonl"
        monkeypatch.setenv(resolve.UNDECLARED_ENV_VAR, str(gone))
        resolve._note_an_undeclared_read(resolve.parse_declared_ref("acme/rates:out"), work)
        assert not gone.exists()
        gone.write_text("", encoding="utf-8")
        resolve._note_an_undeclared_read(resolve.parse_declared_ref("acme/rates:out"), work)
        assert run._undeclared_reads(str(gone)) == [_note(work, "acme/rates")]

    def test_bytes_that_are_no_text_do_not_fail_a_build_that_went_well(self, work, store, monkeypatch):
        """Found by review: a build that wrote such bytes into the file had its good run fail on reading them."""
        report = _reading(work, monkeypatch)
        (report / "build.py").write_text(
            "import os\n"
            f"open(os.environ[{resolve.UNDECLARED_ENV_VAR!r}], 'ab').write(b'\\xff\\xfe not text\\n')\n"
            "open('out.csv', 'w').write('a,b\\n')\n",
            encoding="utf-8", newline="\n",
        )
        found = run.run(report, echo=lambda line: None)
        assert found.failed is None and found.undeclared == []
        # And a note beside them is one all the same
        mixed = work / "mixed.jsonl"
        mixed.write_bytes(b"\xff\xfe not text\n" + (json.dumps(_note(report, "acme/rates")) + "\n").encode("utf-8"))
        assert run._undeclared_reads(str(mixed)) == [_note(report, "acme/rates")]

    def test_with_nowhere_to_note_them_the_build_runs_all_the_same(self, work, store, monkeypatch):
        """Found by review: a temporary folder that cannot be written stopped the build, in CI too, where nothing is ever asked."""
        import tempfile

        report = _reading(work, monkeypatch)

        def nowhere(*arguments, **options):
            raise OSError(2, "No such file or directory")

        monkeypatch.setattr(tempfile, "mkstemp", nowhere)
        found = run.run(report, echo=lambda line: None)
        assert found.failed is None and (report / "out.csv").is_file()

    def test_lines_that_are_no_note_are_passed_over(self, work):
        notes = work / "notes.jsonl"
        good = {"pipeline": "acme/rates", "reference": "acme/rates:out", "from": "/work/report"}
        notes.write_text(
            "\n".join(["not json", json.dumps(["a", "list"]), json.dumps({"pipeline": "acme/x"}), json.dumps(good), ""]),
            encoding="utf-8", newline="\n",
        )
        assert run._undeclared_reads(str(notes)) == [good]
        assert run._undeclared_reads(str(work / "not-there.jsonl")) == []

    def test_a_read_outside_a_run_leaves_none(self, work, store, monkeypatch):
        """Only where a run named a file: a notebook's read, or a batch run of one's own, writes nothing anywhere."""
        from chartbook import data
        from chartbook.errors import DependencyNotDeclaredError

        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        monkeypatch.delenv(resolve.UNDECLARED_ENV_VAR, raising=False)
        monkeypatch.setenv(resolve.BATCH_ENV_VAR, "1")
        before = sorted(path.name for path in report.iterdir())
        with pytest.raises(DependencyNotDeclaredError):
            data.path("acme/rates:out")
        assert sorted(path.name for path in report.iterdir()) == before


class TestTheReadsOwnError:
    def test_names_the_command_that_declares(self, work, store, monkeypatch):
        from chartbook import data
        from chartbook.errors import DependencyNotDeclaredError

        _stored(work, store, "acme/rates")
        _reading(work, monkeypatch, "acme/rates:out")
        monkeypatch.setenv(resolve.BATCH_ENV_VAR, "1")
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.path("acme/rates:out")
        said = str(raised.value).splitlines()
        assert "To read from another pipeline, declare it. Your store has snapshots of this one:" in said
        assert "    $ chartbook add acme/rates" in said
        assert "(`chartbook run`, typed at a terminal, offers to.) Or say by hand where it is, then pin it:" in said

    def test_names_it_under_the_name_the_store_has(self, work, store, monkeypatch):
        """A read that spells the ID in another letter case is told the ID to add, not the spelling it used."""
        from chartbook import data
        from chartbook.errors import DependencyNotDeclaredError

        _stored(work, store, "acme/rates")
        _reading(work, monkeypatch)
        monkeypatch.setenv(resolve.BATCH_ENV_VAR, "1")
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.path("Acme/Rates:out")
        assert "    $ chartbook add acme/rates" in str(raised.value).splitlines()

    def test_does_not_name_it_for_a_pipeline_the_store_does_not_have(self, work, store, monkeypatch):
        """Found by review: followed, `chartbook add acme/nowhere` left an entry that stopped every later run at the pin."""
        from chartbook import data
        from chartbook.errors import DependencyNotDeclaredError

        _stored(work, store, "acme/rates")
        _reading(work, monkeypatch)
        monkeypatch.setenv(resolve.BATCH_ENV_VAR, "1")
        with pytest.raises(DependencyNotDeclaredError) as raised:
            data.path("acme/nowhere:out")
        said = str(raised.value)
        assert "chartbook add" not in said and "To read from another pipeline, say where it is, then pin it:" in said.splitlines()
