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
        note = json.dumps({"pipeline": "acme/rates", "reference": "acme/rates:out", "from": str(report)})
        (report / "build.py").write_text(
            "import os, sys\n"
            f"open(os.environ[{resolve.UNDECLARED_ENV_VAR!r}], 'a').write({note!r} + '\\n')\n"
            "sys.exit(3)\n",
            encoding="utf-8", newline="\n",
        )
        result = CliRunner().invoke(main, ["run"], input="y\ny\n")
        assert result.exit_code == 3
        assert result.output.count("its code reads from a pipeline that chartbook.toml does not declare:") == 1
        assert "Error: acme/report: its 'build' script exited with 3. Nothing after it was run." in result.output.splitlines()
        assert _declared(report) == {"acme/rates": {}}  # what was added at the yes stays


class TestWhereYesCannotWork:
    """No question: the build's own error stands, and nothing is written."""

    def _refused(self, result, report) -> None:
        assert result.exit_code == 1, result.output
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
        note = json.dumps({"pipeline": "acme/rates", "reference": "acme/rates:out", "from": str(work / "elsewhere")})
        (report / "build.py").write_text(
            "import os, sys\n"
            f"open(os.environ[{resolve.UNDECLARED_ENV_VAR!r}], 'a').write({note!r} + '\\n')\n"
            "sys.exit(1)\n",
            encoding="utf-8", newline="\n",
        )
        self._refused(CliRunner().invoke(main, ["run"], input="y\n"), report)

    def test_for_another_script(self, work, store, monkeypatch, at_a_terminal):
        """Only a build is a batch run: another script reads as the shell it was run from would."""
        _stored(work, store, "acme/rates")
        report = _reading(work, monkeypatch, "acme/rates:out")
        table = tomli.loads((report / "chartbook.toml").read_text(encoding="utf-8"))
        table["scripts"]["look"] = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
        (report / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
        result = CliRunner().invoke(main, ["run", "look"], input="y\n")
        assert result.exit_code == 1 and ASKS not in result.output and _declared(report) == {}


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
        # And a script that is not asked about is told of no file
        assert run.execute(script, work, "test") == 0
        assert seen.read_text(encoding="utf-8") == ""

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
        assert "To read from another pipeline, declare it. Where your store has snapshots of it:" in said
        assert "    $ chartbook add acme/rates" in said
        assert "(`chartbook run`, typed at a terminal, offers to.) Or say by hand where it is, then pin it:" in said
