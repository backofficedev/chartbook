"""Being asked, once, whether a folder is yours: the trust prompt (``docs_src/design/trust.md``).

Asked by the maintainer on 2026-10-19: refusing a build until `chartbook
trust` was run was annoying. Now the first `chartbook build`, `run` or
`docs generate` of a folder that is not trusted asks, when a person is at a
terminal: y trusts it and does not ask again, r renders the site without the
folder's code, and Enter stops. A script, CI and a build ChartBook runs are
never asked, and behave as they did (tests/test_trust.py).

The terminal is stood in for by patching ``cli._can_ask``; CliRunner gives
the answers.
"""

import os
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import cli, config
from chartbook.cli import main
from chartbook.identity import clear_git_remote_cache
from tests.fixtures import create_pipeline_project

#: The real test of a terminal, before the fixture stands in for it
_real_can_ask = cli._can_ask


@pytest.fixture(autouse=True)
def _nothing_trusted_and_a_person_at_the_terminal(monkeypatch):
    monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(config.UNTRUSTED_ENV_VAR, raising=False)
    monkeypatch.setattr(config, "_trust_values_warned", set())
    monkeypatch.setattr(cli, "_trust_answers", {})
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    clear_git_remote_cache()
    yield
    clear_git_remote_cache()


def _recorded() -> list:
    path = config.get_trust_path()
    return tomli.loads(path.read_text()).get("pipeline", []) if path.is_file() else []


def _scripted(folder: Path, build: str = "echo ran > ran.log") -> Path:
    """A pipeline whose build command leaves a mark."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chartbook.toml").write_text(tomli_w.dumps({"project": {"name": "rates"}, "scripts": {"build": build}}))
    (folder / "README.md").write_text("# rates\n")
    return folder


class TestBuilding:
    def test_y_trusts_the_folder_builds_it_and_asks_no_more(self, tmp_path, monkeypatch):
        folder = _scripted(tmp_path / "rates")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "ChartBook has not run the code in this folder before:" in result.output
        assert "Its build command runs on this machine:\n    echo ran > ran.log" in result.output
        assert "Trust this folder? [y/r/N]" not in result.output  # run cannot render: no r
        assert "Trust this folder? [y/N]" in result.output
        assert f"Trusted: {folder.resolve()}" in result.output
        assert (folder / "ran.log").exists()
        (entry,) = _recorded()
        assert (entry["path"], entry["level"], entry["id"]) == (str(folder.resolve()), "run", "rates")
        # The next command, in another process, is not asked
        monkeypatch.setattr(cli, "_trust_answers", {})
        again = CliRunner().invoke(main, ["run"])
        assert again.exit_code == 0 and "Trust this folder?" not in again.output

    @pytest.mark.parametrize("answer", ["\n", "n\n", "no\n", ""])
    def test_enter_or_no_stops_and_records_nothing(self, tmp_path, monkeypatch, answer):
        folder = _scripted(tmp_path / "rates")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["run"], input=answer)
        assert result.exit_code == 1
        assert "Nothing was run." in result.output
        assert not (folder / "ran.log").exists() and _recorded() == []

    def test_an_answer_that_is_no_choice_is_asked_again(self, tmp_path, monkeypatch):
        folder = _scripted(tmp_path / "rates")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["run"], input="r\nmaybe\ny\n")
        assert result.output.count("Type y or n.") == 2
        assert result.exit_code == 0 and (folder / "ran.log").exists()

    def test_build_r_renders_the_site_without_running_the_code(self, tmp_path, monkeypatch):
        project = create_pipeline_project(tmp_path)
        with open(project / "chartbook.toml", "a") as f:
            f.write('\n[scripts]\nbuild = "echo ran > ran.log"\n')
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["build", "./docs", "-f"], input="r\n")
        assert result.exit_code == 0, result.output
        assert "Trust this folder? [y/r/N]" in result.output
        assert "The build command was not run; the site is rendered without the folder's code." in result.output
        assert result.output.count("Trust this folder?") == 1  # the render does not ask again
        assert (project / "docs" / "index.html").exists() and not (project / "ran.log").exists()
        assert _recorded() == []

    def test_a_folder_trusted_to_render_is_asked_about_running(self, tmp_path, monkeypatch):
        folder = _scripted(tmp_path / "rates")
        config.record_trust(folder, "render")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert "This folder is trusted to render its site, not to run its code:" in result.output
        assert (folder / "ran.log").exists()
        assert [entry["level"] for entry in _recorded()] == ["run"]


class TestRendering:
    def test_docs_generate_asks_and_y_trusts(self, tmp_path, monkeypatch):
        project = create_pipeline_project(tmp_path)
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"], input="y\n")
        assert result.exit_code == 0, result.output
        assert "ChartBook has not rendered this folder before:" in result.output
        assert "runs its manifest's SQL queries and reads the files it names" in result.output
        assert "is not a pipeline you trust" not in result.output  # no warning: it is trusted now
        assert [entry["level"] for entry in _recorded()] == ["run"]

    def test_docs_generate_r_renders_as_files_from_a_store(self, tmp_path, monkeypatch):
        project = create_pipeline_project(tmp_path)
        monkeypatch.chdir(project)
        seen = {}
        real = cli._run_docs_build

        def recording(*args, **kwargs):
            seen["mode"] = os.environ.get(config.UNTRUSTED_ENV_VAR)
            return real(*args, **kwargs)

        monkeypatch.setattr(cli, "_run_docs_build", recording)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"], input="r\n")
        assert result.exit_code == 0, result.output
        assert seen["mode"] == "1" and _recorded() == []

    def test_docs_generate_n_renders_nothing(self, tmp_path, monkeypatch):
        project = create_pipeline_project(tmp_path)
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "generate", "./docs", "-f"], input="\n")
        assert result.exit_code == 1 and "Nothing was rendered." in result.output
        assert not (project / "docs").exists()


class TestACatalog:
    @pytest.fixture
    def catalog(self, tmp_path):
        for name in ("a", "b"):
            _scripted(tmp_path / name)
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"type": "catalog"}, "pipelines": {"a": {"path": "../a"}, "b": {"path": "../b"}}})
        )
        return catalog

    def test_one_question_for_every_folder(self, catalog, monkeypatch):
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["run"], input="y\n")
        assert result.exit_code == 0, result.output
        assert result.output.count("Trust them? [y/N]") == 1
        assert "Building them as your own runs their build scripts" in result.output
        assert {Path(entry["path"]).name for entry in _recorded()} == {"a", "b"}
        assert (catalog.parent / "a" / "ran.log").exists() and (catalog.parent / "b" / "ran.log").exists()

    def test_rendering_a_catalog_asks_for_its_own_folder_too(self, catalog, monkeypatch):
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "generate", "./site", "-f"], input="n\n")
        assert result.exit_code == 1 and "Nothing was built." in result.output
        assert "the catalog's own folder" in result.output
        assert "Rendering them as your own" in result.output
        assert _recorded() == []

    def test_build_asks_once_saying_scripts_will_run(self, catalog, monkeypatch):
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["build", "./site", "-f"], input="n\n")
        assert result.exit_code == 1
        assert result.output.count("Trust them?") == 1
        assert "Building them as your own runs their build scripts" in result.output


class TestWhoIsAsked:
    @pytest.fixture
    def terminals(self, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", _real_can_ask)
        monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: True)
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)

    def test_a_person_at_a_terminal_is(self, terminals):
        assert cli._can_ask() is True

    @pytest.mark.parametrize("variable", ["CI", "CHARTBOOK_BATCH", "CHARTBOOK_RUN_DIR"])
    def test_ci_and_a_build_chartbook_runs_are_not(self, terminals, monkeypatch, variable):
        monkeypatch.setenv(variable, "1")
        assert cli._can_ask() is False

    def test_a_pipe_is_not(self, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", _real_can_ask)
        monkeypatch.setattr(cli, "_stdin_is_a_terminal", lambda: False)
        monkeypatch.setattr(cli, "_stderr_is_a_terminal", lambda: True)
        assert cli._can_ask() is False

    def test_where_no_one_is_asked_the_refusal_is_as_before(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "_can_ask", lambda: False)
        folder = _scripted(tmp_path / "rates")
        monkeypatch.chdir(folder)
        result = CliRunner().invoke(main, ["run"])
        assert result.exit_code == 1 and "Trust this folder?" not in result.output
        assert "`chartbook trust`" in result.output and not (folder / "ran.log").exists()


