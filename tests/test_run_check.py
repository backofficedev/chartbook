"""``chartbook run --check`` is what ``chartbook check`` was, and ``chartbook check`` is gone (``docs_src/design/one-command.md``).

Nobody knew when to type ``check``: before a build its findings were of
files that were not there yet, and a run did not call it after one. A run
now looks for what its build was to write, and what is left of the check
is what CI wants: an answer in seconds, with nothing run, pinned or built,
in which an output that is not built is listed and is no problem.

What the checks themselves find is in ``tests/test_check.py``; this is the
command.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import check, config
from chartbook.cli import main
from chartbook.manifest import load_manifest
from tests.fixtures import remove_tree

GONE = (
    "Error: `chartbook check` is gone: `chartbook run --check`. It checks a pipeline without building it, with the same "
    "--within and --policy; an output that is not built is listed and is no problem, so --skip-outputs is gone too. "
    "`chartbook run` checks what it builds."
)


@pytest.fixture
def policy(tmp_path):
    """A policy the fixture project meets, so that a test has the one fault it makes."""
    path = tmp_path / "policy.toml"
    path.write_text(
        tomli_w.dumps({"policy": {"required": {"project": ["name"], "dataframes": ["name"], "charts": ["name"]}}}),
        encoding="utf-8", newline="\n",
    )
    return path


@pytest.fixture
def project(pipeline_project, monkeypatch):
    """A built pipeline with a build script that says it ran. Commands are run in it."""
    _edit(pipeline_project, lambda table: table.setdefault("scripts", {}).update(build="echo ran >> build.log"))
    monkeypatch.chdir(pipeline_project)
    return pipeline_project


def _edit(directory: Path, change) -> None:
    path = directory / "chartbook.toml"
    table = tomli.loads(path.read_text(encoding="utf-8"))
    change(table)
    path.write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")


def _check(*arguments):
    return CliRunner().invoke(main, ["run", "--check", *map(str, arguments)])


class TestTheOldCommand:
    @pytest.mark.parametrize("words", [["check"], ["check", "--skip-outputs"], ["check", "--within", "90", "--policy", "../catalog"]])
    def test_says_where_it_went_and_does_nothing(self, project, words):
        result = CliRunner().invoke(main, words)
        assert result.exit_code == 2
        assert GONE in result.output.splitlines()
        assert not (project / "build.log").exists()

    def test_is_not_offered(self):
        listed = CliRunner().invoke(main, ["--help"]).output
        assert not any(line.split()[:1] == ["check"] for line in listed.splitlines())

    def test_its_help_is_still_to_be_had(self):
        """`chartbook check --help` is how someone finds out what became of it."""
        result = CliRunner().invoke(main, ["check", "--help"])
        assert result.exit_code == 2 and GONE in result.output.splitlines()


class TestItRunsNothing:
    def test_no_script_no_pin_no_store(self, project, policy):
        _edit(project, lambda table: table.setdefault("dependencies", {}).update({"acme/elsewhere": {}}))
        result = _check("--policy", policy)
        assert result.output.splitlines()[-1].startswith("chartbook.toml: OK (1 pipeline(s), ")
        assert result.exit_code == 0, result.output
        assert not (project / "build.log").exists()  # the build script
        assert not (project / "chartbook.lock").exists()  # a pin
        assert not Path(config.get_store_url()).exists()  # the store, which nothing has needed yet

    def test_in_a_folder_that_is_not_trusted_it_asks_nothing_and_says_so(self, project, policy, monkeypatch):
        """It reads and runs nothing, so it is not gated: its last line says what a build here would be refused."""
        monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
        result = _check("--policy", policy)
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[-1].startswith("This pipeline is not trusted: `chartbook run` refuses to run the build script")

    @pytest.mark.parametrize("with_it, named", [
        (["test"], "a script (test)"), (["--force"], "--force"), (["--snapshot"], "--snapshot"), (["--frozen"], "--frozen"),
        (["--remake"], "--remake"), (["--upstream"], "--upstream"), (["--force", "--upstream"], "--force, --upstream"),
    ])
    def test_it_goes_with_nothing_that_runs(self, project, with_it, named):
        result = CliRunner().invoke(main, ["run", *with_it, "--check"])
        assert result.exit_code == 2
        assert (
            f"Error: --check runs nothing, so it does not go with {named}. It takes --within, --policy and --project-dir."
        ) in result.output.splitlines()
        assert not (project / "build.log").exists()

    @pytest.mark.parametrize("alone", [["--within", "90"], ["--policy", "policy.toml"]])
    def test_its_options_do_not_go_with_a_run(self, project, alone):
        result = CliRunner().invoke(main, ["run", *alone])
        assert result.exit_code == 2
        assert "Error: --within and --policy go with --check: `chartbook run --check --within 90`." in result.output.splitlines()
        assert not (project / "build.log").exists()

    def test_a_catalog_is_told_it_is_a_pipelines(self, catalog_project):
        result = _check("--project-dir", catalog_project)
        assert result.exit_code == 1
        assert "Catalog member checks are gone. `chartbook run --check` checks a pipeline" in result.output


class TestWhatItCounts:
    def test_what_is_kept_in_the_repository_is_a_problem_and_an_output_is_not(self, project, policy):
        (project / "README.md").unlink()
        (project / "_output" / "charts" / "chart_0_0.html").unlink()
        result = _check("--policy", policy)
        assert result.exit_code == 1
        said = result.output.splitlines()
        problem = next(index for index, line in enumerate(said) if "[project] readme: file not found" in line)
        output = next(index for index, line in enumerate(said) if "[charts.chart_0_0] path: not built yet: " in line)
        assert problem < output  # what to mend first, and what a build writes after
        assert "1 problem(s) found in 1 manifest(s). 1 output is not built yet, which is no problem: `chartbook run` builds it." in said

    def test_several_outputs_are_counted_as_several(self, project, policy):
        remove_tree(project / "_data")
        remove_tree(project / "_output")
        result = _check("--policy", policy)
        assert result.exit_code == 0, result.output
        counted = [line for line in result.output.splitlines() if "] path: not built yet: " in line]
        assert len(counted) == 2
        assert "chartbook.toml: OK (1 pipeline(s), 1 dataframes, 1 charts, 0 notebooks; 2 outputs are not built yet)" in result.output.splitlines()
        assert "Nothing is built yet: `chartbook run` builds it." in result.output.splitlines()

    def test_with_everything_built_it_says_nothing_of_outputs(self, project, policy):
        result = _check("--policy", policy)
        assert result.exit_code == 0, result.output
        assert "not built yet" not in result.output and "Nothing is built yet" not in result.output

    def test_the_window_for_a_license_is_thirty_days_unless_told(self, project, policy):
        soon = date.today() + timedelta(days=20)
        _edit(project, lambda table: table["dataframes"]["dataframe_0"].update(license_expiration=soon.isoformat()))
        assert _check("--policy", policy).exit_code == 1
        assert _check("--policy", policy, "--within", "10").exit_code == 0
        assert _check("--policy", policy, "--within", "30").exit_code == 1

    def test_a_file_that_is_built_is_still_looked_at(self, project, policy):
        """Not `--skip-outputs` under another name: a parquet file that is there is asked about the column pandas makes of an index."""
        import pandas as pd

        (parquet,) = (project / "_data").rglob("dataframe_0.parquet")
        pd.DataFrame({"a": [1, 2]}, index=[5, 7]).to_parquet(parquet)
        result = _check("--policy", policy)
        assert result.exit_code == 0, result.output
        assert "__index_level_0__" in result.output


class TestTheFunction:
    def test_gathers_what_is_not_built_and_reports_the_rest(self, pipeline_project):
        (pipeline_project / "README.md").unlink()
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        manifest = load_manifest(base_dir=pipeline_project)
        gathered: list = []
        problems = check.run_checks(manifest, pipeline_project, skip_outputs=True, policy_given=False, not_built=gathered)
        assert [(found.table, found.field) for found in problems] == [("project", "readme")]
        assert [(found.table, found.field, found.message.split(":")[0]) for found in gathered] == [
            ("charts.chart_0_0", "path", check.NOT_BUILT_YET)
        ]
        # Asked as it always could be: outputs left out and gathered nowhere, or reported as problems
        assert [found.table for found in check.run_checks(manifest, pipeline_project, skip_outputs=True, policy_given=False)] == ["project"]
        assert sorted(found.table for found in check.run_checks(manifest, pipeline_project, policy_given=False)) == [
            "charts.chart_0_0", "project",
        ]
