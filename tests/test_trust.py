"""Trust for a build of files on this machine (``docs_src/design/trust.md``).

A build of a folder trusted its ``chartbook.toml`` completely: ``docs`` ran
its queries, copied whatever files it named, and ``build`` ran its script.
Now a folder is built as the user's own only once they have said so, with
``chartbook trust``; until then ``docs`` renders it as a build of files
from a store, and ``build`` and ``run`` refuse. These tests cover the record
under ``~/.chartbook`` (``chartbook.config``), the command, and each gate.

The suite's conftest trusts every folder (``CHARTBOOK_TRUST=all``); the
fixture here clears that, so nothing is trusted but what a test says.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import config, run, scaffold
from chartbook.cli import main
from chartbook.identity import clear_git_remote_cache
from chartbook.manifest import catalog_member_dirs
from chartbook.run import RunError
from tests.fixtures import create_catalog_project, create_pipeline_project

posix = pytest.mark.skipif(os.name == "nt", reason="the scripts here are POSIX shell")

#: Appends the pipeline's folder name to one shared file, so a test sees what ran
LOG = 'echo "$(basename "$PWD")" >> ../order.log'


@pytest.fixture(autouse=True)
def _nothing_trusted(monkeypatch):
    """Nothing is trusted but what a test records, and a docs gate's untrusted mode does not outlive its test."""
    monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(config.UNTRUSTED_ENV_VAR, raising=False)
    monkeypatch.setattr(config, "_trust_values_warned", set())
    clear_git_remote_cache()
    yield
    clear_git_remote_cache()


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True, encoding="utf-8", errors="replace"
    ).stdout.strip()


def _repository(folder: Path, remote=None) -> Path:
    """Make *folder* a git repository, with an ``origin`` remote if one is given."""
    folder.mkdir(parents=True, exist_ok=True)
    _git(folder, "init", "--quiet", "-b", "main")
    if remote:
        _git(folder, "remote", "add", "origin", remote)
    clear_git_remote_cache()
    return folder


def _pipeline(directory: Path, scripts=None, **tables) -> Path:
    table = {"project": {"id": directory.name}, **tables}
    if scripts is not None:
        table["scripts"] = scripts
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
    return directory


def _catalog(work: Path, *members: str) -> Path:
    (work / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {name: {"path": name} for name in members}}), encoding="utf-8", newline="\n"
    )
    return work


def _order(work: Path) -> list:
    log = work / "order.log"
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def _edit_manifest(project: Path, edit) -> None:
    manifest = tomli.loads((project / "chartbook.toml").read_text(encoding="utf-8"))
    edit(manifest)
    (project / "chartbook.toml").write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")


@pytest.fixture
def work(tmp_path):
    return tmp_path.resolve()


class TestTrustOf:
    """``config.trust_of``: the highest level of every entry that covers the folder, and what comes before the record."""

    def test_nothing_recorded_is_none(self, work):
        assert config.trust_of(work) is None
        assert config.read_trust() == []

    def test_the_folder_itself(self, work):
        config.record_trust(work / "rates", "run")
        assert config.trust_of(work / "rates") == "run"
        assert config.trust_of(work / "other") is None

    def test_a_parent_folder_covers_the_folders_inside_it(self, work):
        config.record_trust(work, "render")
        assert config.trust_of(work / "a" / "b") == "render"
        assert config.trust_of(work.parent) is None

    def test_a_repository_by_the_folders_origin_remote(self, work):
        first = _repository(work / "first", "git@github.com:Acme/Rates.git")
        second = _repository(work / "elsewhere" / "second", "https://github.com/acme/rates/")
        without = _repository(work / "without")
        config.record_repository_trust("https://github.com/acme/rates", "run")
        assert config.trust_of(first) == "run"
        assert config.trust_of(second) == "run"
        assert config.trust_of(without) is None
        assert config.trust_of(work / "plain") is None

    def test_the_highest_level_wins(self, work):
        folder = _repository(work / "rates", "https://github.com/acme/rates")
        config.record_trust(work, "render")
        assert config.trust_of(folder) == "render"
        config.record_repository_trust("https://github.com/acme/rates", "run")
        assert config.trust_of(folder) == "run"
        config.record_trust(folder, "render")  # a lower level alongside changes nothing
        assert config.trust_of(folder) == "run"

    def test_chartbook_trust_all_trusts_every_folder(self, work, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        assert config.trust_of(work / "anything") == "run"

    def test_another_value_of_chartbook_trust_is_warned_about_once_and_ignored(self, work, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_TRUST", "1")
        with pytest.warns(UserWarning, match="CHARTBOOK_TRUST='1' is not a value it takes"):
            assert config.trust_of(work) is None
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert config.trust_of(work) is None

    def test_ci_trusts_the_checkout_the_working_directory_is_in(self, work, monkeypatch):
        checkout = _repository(work / "checkout")
        (checkout / "sub").mkdir()
        monkeypatch.chdir(checkout / "sub")
        monkeypatch.setenv("CI", "true")
        assert config.trust_of(checkout / "sub" / "pipeline") == "run"
        assert config.trust_of(checkout) == "run"
        assert config.trust_of(work / "outside") is None

    def test_ci_outside_a_repository_trusts_the_working_directory(self, work, monkeypatch):
        here = work / "job"
        here.mkdir()
        monkeypatch.chdir(here)
        monkeypatch.setenv("CI", "1")
        assert config.trust_of(here / "pipeline") == "run"
        assert config.trust_of(work / "other") is None

    def test_an_empty_ci_is_no_ci(self, work, monkeypatch):
        monkeypatch.chdir(work)
        monkeypatch.setenv("CI", "")
        assert config.trust_of(work) is None

    def test_a_build_of_files_from_a_store_is_never_trusted(self, work, monkeypatch):
        config.record_trust(work, "run")
        monkeypatch.setenv(config.UNTRUSTED_ENV_VAR, "1")
        assert config.trust_of(work) is None
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        assert config.trust_of(work) is None


class TestSinceText:
    def test_a_date_time_without_a_zone_is_said_as_written(self):
        from datetime import datetime, timedelta, timezone

        assert config._since_text(datetime(2026, 10, 18, 22, 14, 5)) == "2026-10-18T22:14:05"
        assert config._since_text(datetime(2026, 10, 18, 17, 14, 5, tzinfo=timezone(timedelta(hours=-5)))) == "2026-10-18T22:14:05Z"
        assert config._since_text("2026-10-18T22:14:05Z") == "2026-10-18T22:14:05Z"


class TestTheRecord:
    """``~/.chartbook/trust.toml``: written whole or not at all, read as settings are."""

    def test_a_round_trip(self, work):
        written = config.record_trust(work / "rates", "run", id="acme/rates", repository="https://github.com/acme/rates")
        assert written == config.get_trust_path()
        (entry,) = config.read_trust()
        assert entry["kind"] == "pipeline"
        assert entry["path"] == str((work / "rates").resolve())
        assert entry["level"] == "run"
        assert entry["id"] == "acme/rates"
        assert entry["repository"] == "https://github.com/acme/rates"
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry["since"])
        text = written.read_text(encoding="utf-8")
        assert text.startswith("# Pipelines you have trusted (chartbook trust)")
        assert "[[pipeline]]" in text
        assert not list(written.parent.glob("trust.toml.*.tmp"))

    def test_an_entry_for_the_same_folder_is_replaced(self, work):
        config.record_trust(work / "rates", "run")
        config.record_trust(work / "rates" / ".." / "rates", "render")
        (entry,) = config.read_trust()
        assert entry["level"] == "render"

    def test_a_repository_is_one_entry_however_it_is_written(self, work):
        config.record_repository_trust("git@github.com:Acme/Rates.git", "render")
        config.record_repository_trust("https://github.com/acme/rates/", "run")
        (entry,) = config.read_trust()
        assert entry == {"kind": "repository", "url": "https://github.com/acme/rates", "level": "run", "since": entry["since"]}

    def test_a_repository_that_is_none_is_refused(self):
        with pytest.raises(ValueError, match="names no repository"):
            config.record_repository_trust("rates", "run")

    def test_a_level_that_is_none_is_refused(self, work):
        with pytest.raises(ValueError, match="'sudo' is not a level of trust"):
            config.record_trust(work, "sudo")

    def test_forgetting(self, work):
        config.record_trust(work / "rates", "run")
        config.record_trust(work / "other", "run")
        config.record_repository_trust("https://github.com/acme/rates", "run")
        assert config.forget_trust(path=work / "rates") == 1
        assert config.forget_trust(path=work / "rates") == 0
        assert config.forget_trust(url="git@github.com:acme/rates.git") == 1
        assert [e["path"] for e in config.read_trust()] == [str((work / "other").resolve())]

    def test_forgetting_a_folder_does_not_take_the_parent_that_covers_it(self, work):
        config.record_trust(work, "run")
        assert config.forget_trust(path=work / "rates") == 0
        assert config.trust_of(work / "rates") == "run"

    def test_forgetting_with_no_file_is_nothing(self, work):
        assert config.forget_trust(path=work) == 0
        assert not config.get_trust_path().exists()

    def test_a_file_that_cannot_be_read_stops_the_command_naming_the_file(self, work):
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not = toml =\n", encoding="utf-8", newline="\n")
        with pytest.raises(ValueError, match=r"trust\.toml, the trust record, is not valid TOML"):
            config.read_trust()
        with pytest.raises(ValueError, match=r"trust\.toml"):
            config.trust_of(work)

    def test_an_entry_of_another_shape_is_passed_over_with_a_warning(self, work):
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            tomli_w.dumps(
                {
                    "pipeline": [
                        {"path": 5, "level": "run"},
                        {"path": str(work / "sudo"), "level": "sudo"},
                        {"path": str(work / "good"), "level": "render"},
                    ],
                    "repository": [{"url": "rates", "level": "run"}, {"url": "https://github.com/acme/rates", "level": "run"}],
                }
            ), encoding="utf-8", newline="\n"
        )
        with pytest.warns(UserWarning) as caught:
            entries = config.read_trust()
        said = [str(w.message) for w in caught]
        assert any("[[pipeline]] entry 1 ({'path': 5, 'level': 'run'}) is passed over" in s and "trust.toml" in s for s in said)
        assert any("[[pipeline]] entry 2" in s and "is passed over: an entry has path" in s for s in said)
        assert any("[[repository]] entry 1 ({'url': 'rates', 'level': 'run'}) names no repository" in s for s in said)
        assert [(e["kind"], e["level"]) for e in entries] == [("pipeline", "render"), ("repository", "run")]
        assert config.trust_of(work / "good" / "inside") == "render"

    def test_a_write_keeps_what_it_did_not_understand(self, work):
        """A record is rewritten whole, and an entry the reader passed over is not lost by the write."""
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomli_w.dumps({"pipeline": [{"path": 5, "level": "run"}], "later": {"word": 1}}), encoding="utf-8", newline="\n")
        config.record_trust(work, "run")
        raw = tomli.loads(path.read_text(encoding="utf-8"))
        assert raw["later"] == {"word": 1}
        assert raw["pipeline"][0] == {"path": 5, "level": "run"}
        assert raw["pipeline"][1]["path"] == str(work.resolve())

    def test_a_relative_path_is_passed_over(self, work, monkeypatch):
        """Found by a review: resolved against the working directory, `path = "work"` trusted a different folder from each folder a command ran in."""
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomli_w.dumps({"pipeline": [{"path": "work", "level": "run"}]}), encoding="utf-8", newline="\n")
        (work / "work" / "sub").mkdir(parents=True)
        monkeypatch.chdir(work)
        with pytest.warns(UserWarning, match=r"entry 1 .* has a relative path, .* write the folder's full path"):
            assert config.read_trust() == []
        with pytest.warns(UserWarning):
            assert config.trust_of(work / "work" / "sub") is None
        # A write keeps it, and records the folder by its full path beside it
        config.record_trust(work / "work", "run")
        raw = tomli.loads(path.read_text(encoding="utf-8"))
        assert [entry["path"] for entry in raw["pipeline"]] == ["work", str((work / "work").resolve())]

    def test_since_is_read_from_a_toml_date_time_as_the_string_it_is_written_as(self, work):
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"[[pipeline]]\npath = '{work}'\nlevel = \"run\"\nsince = 2026-10-18T22:14:05Z\n\n"
            f'[[repository]]\nurl = "https://github.com/acme/rates"\nlevel = "run"\nsince = 2026-10-18T17:14:05-05:00\n', encoding="utf-8", newline="\n"
        )
        first, second = config.read_trust()
        assert first["since"] == "2026-10-18T22:14:05Z"
        assert second["since"] == "2026-10-18T22:14:05Z"
        # What is written is a string; the entries kept are kept as they were
        config.record_trust(work / "other", "run")
        assert re.search(r'since = "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"', path.read_text(encoding="utf-8"))
        assert sum(entry["since"] == "2026-10-18T22:14:05Z" for entry in config.read_trust()) == 2

    def test_a_table_where_an_array_should_be_is_never_dropped_by_a_write(self, work, monkeypatch):
        """Found by a review: `[pipeline]` was warned about, and then dropped by the next write."""
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        written = f"[pipeline]\npath = '{work}'\nlevel = \"run\"\n"  # '…': a literal string, so a Windows path is as it is
        path.write_text(written, encoding="utf-8", newline="\n")
        with pytest.warns(UserWarning, match=r"\[\[pipeline\]\] is not an array of tables"):
            assert config.read_trust() == []
        with pytest.raises(ValueError, match=r"trust\.toml: \[pipeline\] is a table, not an array of tables, and writing the file would drop it"):
            config.record_trust(work / "other", "run")
        with pytest.raises(ValueError, match="fix it or remove it"):
            config.forget_trust(path=work)
        assert path.read_text(encoding="utf-8") == written
        monkeypatch.chdir(work)
        result = _trust()
        assert result.exit_code == 1
        assert result.output.startswith("Error: ") and "is a table, not an array of tables" in result.output

    def test_a_record_that_cannot_be_written_is_an_os_error(self, work, monkeypatch):
        blocker = work / "blocker"
        blocker.write_text("a file where a folder should be", encoding="utf-8", newline="\n")
        monkeypatch.setattr(config, "get_global_config_dir", lambda: blocker / ".chartbook")
        with pytest.raises(OSError):
            config.record_trust(work, "run")


def _trust(*arguments):
    return CliRunner().invoke(main, ["trust", *arguments])


class TestTheCommand:
    """``chartbook trust`` in each of its forms."""

    def test_this_folder(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = _trust()
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"Trusted to run: {pipeline_project.resolve()} (test_pipeline)"
        assert config.trust_of(pipeline_project) == "run"

    def test_to_render_only(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = _trust("--render")
        assert result.exit_code == 0, result.output
        assert result.output.startswith("Trusted to render: ")
        assert config.trust_of(pipeline_project) == "render"

    def test_another_folder_with_its_repository_noted(self, pipeline_project, work, monkeypatch):
        _repository(pipeline_project, "git@github.com:acme/test_pipeline.git")
        monkeypatch.chdir(work)
        result = _trust(str(pipeline_project))
        assert result.exit_code == 0, result.output
        # The fixture's manifest sets its ID, which comes before the remote's scope
        assert result.output.strip() == (
            f"Trusted to run: {pipeline_project.resolve()} (test_pipeline, https://github.com/acme/test_pipeline)"
        )
        (entry,) = config.read_trust()
        assert entry["id"] == "test_pipeline" and entry["repository"] == "https://github.com/acme/test_pipeline"

    def test_a_folder_with_no_manifest_says_the_folders_inside_it_are_trusted_too(self, work, monkeypatch):
        monkeypatch.chdir(work)
        result = _trust()
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == [
            f"Trusted to run: {work}",
            f"There is no chartbook.toml in {work}, so this trusts every pipeline in the folders inside it.",
        ]
        assert config.trust_of(work / "deep" / "pipeline") == "run"


    def test_a_folder_that_is_not_there(self, work, monkeypatch):
        monkeypatch.chdir(work)
        result = _trust("nowhere")
        assert result.exit_code == 1
        assert result.output.strip() == f"Error: {work / 'nowhere'} is not a folder."
        assert not isinstance(result.exception, Exception) or isinstance(result.exception, SystemExit)

    def test_the_repository(self, pipeline_project, work, monkeypatch):
        _repository(pipeline_project, "git@github.com:Acme/Test_Pipeline.git")
        monkeypatch.chdir(pipeline_project)
        result = _trust("--repository")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == (
            f"Trusted to run: https://github.com/acme/test_pipeline (every clone whose origin remote is it; "
            f"this one is {pipeline_project.resolve()})"
        )
        clone = _repository(work / "clone", "https://github.com/acme/test_pipeline")
        assert config.trust_of(clone) == "run"
        assert config.trust_of(pipeline_project) == "run"

    def test_the_repository_of_a_folder_with_no_remote(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = _trust("--repository")
        assert result.exit_code == 1
        assert "has no origin remote, so there is no repository to trust. `chartbook trust` trusts the folder itself." in result.output





    def test_list(self, pipeline_project, work, monkeypatch):
        monkeypatch.chdir(work)
        result = _trust("--list")
        assert result.exit_code == 0, result.output
        assert result.output.startswith("Nothing is recorded in ")
        assert "`chartbook trust` in a pipeline's folder trusts it" in result.output

        config.record_trust(pipeline_project, "render", id="test_pipeline")
        config.record_repository_trust("https://github.com/acme/rates", "run")
        result = _trust("--list")
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == f"{config.get_trust_path()}:"
        assert lines[1] == "Pipelines (each covers the folders inside it):"
        assert lines[2].startswith(f"  render  {pipeline_project.resolve()}  (test_pipeline)  since ")
        assert lines[3] == "Repositories (every clone whose origin remote is it):"
        assert lines[4].startswith("  run     https://github.com/acme/rates  since ")

    def test_list_says_when_the_environment_trusts_everything(self, work, monkeypatch):
        monkeypatch.chdir(work)
        monkeypatch.setenv("CHARTBOOK_TRUST", "all")
        result = _trust("--list")
        assert result.output.startswith("CHARTBOOK_TRUST=all: every folder is trusted to run")
        monkeypatch.delenv("CHARTBOOK_TRUST")
        monkeypatch.setenv("CI", "true")
        result = _trust("--list")
        assert result.output.startswith(f"CI is set: {work} and the folders inside it are trusted to run.")

    def test_list_takes_nothing_else(self, work, monkeypatch):
        monkeypatch.chdir(work)
        result = _trust("--list", str(work))
        assert result.exit_code == 2
        assert "--list shows what is trusted; it takes no PATH and no other option." in result.output

    def test_forget(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        config.record_trust(pipeline_project, "run")
        result = _trust("--forget")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == f"No longer trusted: {pipeline_project.resolve()} (1 entry removed)."
        assert config.trust_of(pipeline_project) is None
        result = _trust("--forget")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == (
            f"Nothing was recorded for {pipeline_project.resolve()}; `chartbook trust --list` shows what is."
        )

    def test_forget_a_folder_that_is_gone(self, work, monkeypatch):
        """A clone deleted after it was trusted can still be taken out of the record."""
        gone = work / "gone"
        config.record_trust(gone, "run")
        monkeypatch.chdir(work)
        result = _trust("--forget", "gone")
        assert result.exit_code == 0, result.output
        assert result.output.startswith(f"No longer trusted: {gone}")
        assert config.read_trust() == []
        assert _trust("gone").exit_code == 1  # trusting it still needs the folder to be there

    def test_forget_the_repository(self, pipeline_project, monkeypatch):
        _repository(pipeline_project, "https://github.com/acme/rates")
        monkeypatch.chdir(pipeline_project)
        config.record_repository_trust("https://github.com/acme/rates", "run")
        result = _trust("--forget", "--repository")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "No longer trusted: https://github.com/acme/rates (1 entry removed)."
        assert config.read_trust() == []

    def test_forget_takes_no_level(self, work, monkeypatch):
        monkeypatch.chdir(work)
        assert _trust("--forget", "--render").exit_code == 2
        assert _trust("--repository", "--members").exit_code == 1

    def test_a_record_that_cannot_be_read_is_one_plain_line(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        path = config.get_trust_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not = toml =\n", encoding="utf-8", newline="\n")
        result = _trust()
        assert result.exit_code == 1
        assert result.output.startswith("Error: ")
        assert "trust.toml, the trust record, is not valid TOML" in result.output
        assert isinstance(result.exception, SystemExit)


@pytest.fixture
def leaky_project(pipeline_project, tmp_path):
    """A pipeline whose manifest would read a file of this machine: a query over a secret CSV."""
    secret = tmp_path / "secret.csv"
    secret.write_text("user,password\nadmin,HUNTER2_LEAKED_SECRET\n", encoding="utf-8", newline="\n")

    def edit(manifest):
        manifest["sources"] = {"mem": {"backend": "duckdb", "url": "duckdb:///:memory:"}}
        manifest["dataframes"]["leak"] = {
            "source": "mem",
            "query": f"select * from read_csv_auto('{secret.as_posix()}')",
            "docs": "What the query returns.",
        }

    _edit_manifest(pipeline_project, edit)
    return pipeline_project


def _pages(output_dir: Path) -> str:
    return "".join(p.read_text(errors="replace", encoding="utf-8") for p in output_dir.rglob("*") if p.is_file())


class TestDocsOfAnUntrustedPipeline:
    """`chartbook docs build` renders a folder the user has not trusted as it renders files from a store."""

    def test_it_renders_with_a_warning_and_runs_no_query(self, leaky_project, monkeypatch):
        monkeypatch.chdir(leaky_project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "Warning: " in result.output
        assert f"{leaky_project} is not a pipeline you trust, so it is read as files from a store are" in result.output
        assert "`chartbook trust` here trusts it; `chartbook trust --render` trusts it to render only." in result.output
        assert (leaky_project / "docs" / "index.html").is_file()
        pages = _pages(leaky_project / "docs")
        assert "HUNTER2_LEAKED_SECRET" not in pages
        assert "not read in a build of files from a store, nor of a folder you have not trusted" in pages
        # The mode was the render's: set before anything was read, and gone after, so a later
        # render in this process (a test's, a library's) is not untrusted by accident
        assert os.environ.get(config.UNTRUSTED_ENV_VAR) is None

    def test_a_trusted_pipeline_runs_its_query_with_no_warning(self, leaky_project, monkeypatch):
        config.record_trust(leaky_project, "render")
        monkeypatch.chdir(leaky_project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "not a pipeline you trust" not in result.output
        assert "HUNTER2_LEAKED_SECRET" in _pages(leaky_project / "docs")
        assert os.environ.get(config.UNTRUSTED_ENV_VAR) is None

    def test_a_logo_outside_the_folder_is_not_copied(self, pipeline_project, tmp_path, monkeypatch):
        """Untrusted, a manifest that names a file outside its folder stops the render, naming the entry; trusted, the file is read."""
        logo = tmp_path / "elsewhere.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\nTRUST-TEST-LOGO-BYTES")
        _edit_manifest(pipeline_project, lambda m: m["project"].__setitem__("logo", "../elsewhere.png"))
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 1, result.output
        assert "is not a pipeline you trust" in result.output
        assert "[project] logo = '../elsewhere.png' is not a plain path inside the pipeline's folder" in result.output
        assert "`chartbook trust` in a folder trusts the pipeline there" in result.output
        copied = [p for p in pipeline_project.rglob("*") if p.is_file() and b"TRUST-TEST-LOGO-BYTES" in p.read_bytes()]
        assert copied == []

        config.record_trust(pipeline_project, "render")
        # The untrusted mode is the process's; a second command is a second process
        monkeypatch.delenv(config.UNTRUSTED_ENV_VAR, raising=False)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        copied = [p for p in (pipeline_project / "docs").rglob("*") if p.is_file() and b"TRUST-TEST-LOGO-BYTES" in p.read_bytes()]
        assert copied, "the logo the manifest names was not copied into the site"

    @pytest.fixture
    def reaching_project(self, pipeline_project, tmp_path):
        """A pipeline whose manifest names a data file outside its folder."""
        secret = tmp_path / "secret.csv"
        secret.write_text("user,password\nadmin,HUNTER2_LEAKED_SECRET\n", encoding="utf-8", newline="\n")
        # Relative, as a monorepo's shared file would be named (an absolute path outside is refused the same way)
        _edit_manifest(pipeline_project, lambda m: m["dataframes"].__setitem__("leak", {"path": "../secret.csv", "docs": "d"}))
        return pipeline_project

    def test_create_data_glimpses_reads_nothing_outside_an_untrusted_folder(self, reaching_project, tmp_path, monkeypatch):
        """Found by a review: the report wrote the rows of a file the manifest named anywhere on the machine."""
        out = tmp_path / "glimpses"
        arguments = ["create-data-glimpses", "--project-dir", str(reaching_project), "-o", str(out)]
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 1, result.output
        assert "is not a pipeline you trust" in result.output
        assert "[dataframes.leak] path" in result.output and "is not a plain path inside the pipeline's folder" in result.output
        assert not out.exists() or "HUNTER2_LEAKED_SECRET" not in _pages(out)

        config.record_trust(reaching_project, "render")
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 0, result.output
        assert "HUNTER2_LEAKED_SECRET" in (out / "data_glimpses.md").read_text(encoding="utf-8")

    def test_publish_copies_nothing_from_outside_an_untrusted_folder(self, reaching_project, tmp_path):
        """Found by a review: `publish` copied the files the manifest named from anywhere."""
        published = tmp_path / "published"
        arguments = ["publish", "--project-dir", str(reaching_project), "--publish-dir", str(published)]
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 1, result.output
        assert "is not a pipeline you trust" in result.output
        assert result.output.count("Error: ") == 1 and "[dataframes.leak] path" in result.output
        assert isinstance(result.exception, SystemExit)
        assert not published.exists() or "HUNTER2_LEAKED_SECRET" not in _pages(published)

        config.record_trust(reaching_project, "render")
        result = CliRunner().invoke(main, arguments)
        assert result.exit_code == 0, result.output
        assert (published / "test_pipeline" / "chartbook.toml").is_file()



@posix
class TestBuildAndRun:
    """`chartbook build` and `chartbook run` run a script only in a folder trusted to run."""

    def test_run_refuses_an_untrusted_pipeline(self, work):
        pipeline = _pipeline(work / "rates", {"build": LOG})
        with pytest.raises(RunError) as refused:
            run.run(pipeline)
        said = str(refused.value)
        assert said.startswith("rates is not trusted, so its 'build' script was not run.")
        assert f"`chartbook trust` in {pipeline} trusts it." in said
        assert _order(work) == []

    def test_run_refuses_a_pipeline_trusted_to_render_only(self, work):
        pipeline = _pipeline(work / "rates", {"build": LOG, "test": LOG})
        config.record_trust(pipeline, "render")
        with pytest.raises(RunError, match="rates is trusted to render, not to run, so its 'test' script was not run"):
            run.run(pipeline, "test")
        assert _order(work) == []

    def test_run_runs_a_trusted_pipeline(self, work):
        pipeline = _pipeline(work / "rates", {"build": LOG})
        config.record_trust(work, "run")  # the parent folder covers it
        report = run.run(pipeline, echo=lambda line: None)
        assert report.failed is None and [step.id for step in report.ran] == ["rates"]
        assert _order(work) == ["rates"]

    def test_the_commands_say_it_in_one_line_and_run_nothing(self, work, monkeypatch):
        pipeline = _pipeline(work / "rates", {"build": LOG})
        (pipeline / "README.md").write_text("# Rates\n", encoding="utf-8", newline="\n")
        monkeypatch.chdir(pipeline)
        for arguments in (["run"],):
            result = CliRunner().invoke(main, arguments)
            assert result.exit_code == 1, result.output
            assert result.output.startswith("Error: rates is not trusted, so its 'build' script was not run.")
            assert f"`chartbook trust` in {pipeline} trusts it." in result.output
        assert _order(work) == []
        assert not (pipeline / "docs").exists()

        result = CliRunner().invoke(main, ["trust"])
        assert result.exit_code == 0, result.output
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 0, result.output
        assert _order(work) == ["rates"]



    def test_a_git_dependency_is_trusted_by_being_declared(self, work, monkeypatch):
        """Only the pipeline that names it must be trusted to run."""
        from tests.test_run import _commit, _with_data

        upstream = _with_data(work / "upstream", {"build": LOG})
        _commit(upstream)
        downstream = _pipeline(work / "downstream", {"build": LOG}, dependencies={"up": {"git": upstream.as_uri()}})
        with pytest.raises(RunError, match="downstream is not trusted"):
            run.run(downstream, echo=lambda line: None)
        assert _order(work) == []
        config.record_trust(downstream, "run")
        report = run.run(downstream, echo=lambda line: None)
        assert report.failed is None, report.reason
        assert [step.id for step in report.ran] == ["upstream", "downstream"]


def _sibling_catalog(work: Path, *pipeline_ids: str) -> Path:
    """A catalog at ``work/cat`` of full pipelines beside it, so that trusting the catalog's folder covers none of them."""
    for pipeline_id in pipeline_ids:
        create_pipeline_project(work / pipeline_id, pipeline_id=pipeline_id, pipeline_name=pipeline_id.title())
    root = work / "cat"
    root.mkdir()
    (root / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"type": "catalog", "name": "Test Catalog", "maintainer": "Test Author", "copyright": "2024"},
                "pipelines": {pipeline_id: {"path": f"../{pipeline_id}"} for pipeline_id in pipeline_ids},
            }
        ), encoding="utf-8", newline="\n"
    )
    return root





class TestCatalogBuildOfAPipeline:
    def test_a_settings_file_pointing_at_an_untrusted_pipeline_renders_it_as_a_store_build(self, leaky_project, monkeypatch):
        """Found by a reviewer: `catalog build` dropped what the gate said, so a pipeline the settings
        file named as the catalog was rendered trusted, its query run and its secret on the page."""
        monkeypatch.setattr("chartbook.cli._default_catalog_path", lambda: leaky_project / "chartbook.toml")
        monkeypatch.chdir(leaky_project)
        result = CliRunner().invoke(main, ["catalog", "build", "-f"])
        assert result.exit_code == 0, result.output
        assert "not a pipeline you trust" in result.output
        assert "HUNTER2_LEAKED_SECRET" not in _pages(leaky_project / "docs")
        assert os.environ.get(config.UNTRUSTED_ENV_VAR) is None


class TestCatalogInitAndAdd:
    """A catalog you make is yours to run; a folder you add to it is asked to be rendered there."""


    def test_init_needs_no_pipeline_trust(self, work, monkeypatch):
        monkeypatch.chdir(work)
        result = CliRunner().invoke(main, ["catalog", "init", "--title", "Mine"])
        assert result.exit_code == 0, result.output
        folder = config.get_global_config_dir()
        assert "Trusted:" not in result.output
        assert config.trust_of(folder) is None
        assert config.read_trust() == []




class TestCheck:
    """`chartbook check` is not gated; it says the level when it is not `run`."""

    def test_it_says_the_folder_is_not_trusted_last(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["check"])
        last = result.output.strip().splitlines()[-1]
        assert last.startswith("This pipeline is not trusted: `chartbook run` refuses to run the build script, and `chartbook docs build` renders the site as one from a store is")
        assert "`chartbook trust` here trusts it; `chartbook trust --list` shows what is trusted." in last

    def test_render_only_is_said_as_that(self, pipeline_project, monkeypatch):
        config.record_trust(pipeline_project, "render")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["check"])
        last = result.output.strip().splitlines()[-1]
        assert last.startswith("This pipeline is trusted to render, not to run: `chartbook run` refuses")
        assert "`chartbook docs build`" not in last

    def test_a_trusted_folder_draws_no_line(self, pipeline_project, monkeypatch):
        config.record_trust(pipeline_project, "run")
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["check"])
        assert "chartbook trust" not in result.output



COMMIT = "0123456789abcdef0123456789abcdef01234567"


class TestInit:
    """A project `chartbook init` makes is trusted to run as it is made."""

    @pytest.fixture
    def rendered(self, tmp_path, monkeypatch):
        """Rendering the template stood in for: a folder with a manifest, as the real one leaves."""
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        project = workdir / "rates_study"

        def render(cwd, **kwargs):
            project.mkdir()
            (project / "chartbook.toml").write_text('[project]\nname = "Rates Study"\n', encoding="utf-8", newline="\n")
            return scaffold.Rendered(project, COMMIT, True, why="", answers={})

        monkeypatch.setattr(scaffold, "render", render)
        return project

    def test_it_records_the_new_project(self, rendered):
        result = CliRunner().invoke(main, ["init"])
        assert result.exit_code == 0, result.output
        assert "  Trusted: this folder (chartbook trust --list)" in result.output
        (entry,) = config.read_trust()
        assert entry["path"] == str(rendered.resolve())
        assert entry["level"] == "run"
        assert entry["id"] == "rates_study"
        assert entry["repository"] is None
        assert config.trust_of(rendered) == "run"

    def test_when_it_cannot_record_it_says_so_and_goes_on(self, rendered, tmp_path, monkeypatch):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where the home folder's .chartbook should be", encoding="utf-8", newline="\n")
        monkeypatch.setattr(config, "get_global_config_dir", lambda: blocker / ".chartbook")
        result = CliRunner().invoke(main, ["init"])
        assert result.exit_code == 0, result.output
        assert f"Note: {rendered} could not be recorded as trusted (" in result.output
        assert "until `chartbook trust` in that folder records it." in result.output
        assert "Trusted: this folder" not in result.output
        assert rendered.is_dir()
