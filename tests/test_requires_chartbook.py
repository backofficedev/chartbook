"""Moving a pipeline from one ChartBook to the next.

Two things, asked for by the maintainer on 2026-10-19 after a survey found 65
of 68 pipelines rendering their site from a ``dodo.py`` task that says
``chartbook build -f``:

- ``[project] requires_chartbook`` names the ChartBook a project needs, and an
  older one stops before acting on the manifest
  (:func:`chartbook.manifest.require_chartbook`);
- a build tool's task that says ``chartbook build`` makes the build run inside
  itself now that ``chartbook build`` runs the build command, and
  ``chartbook build`` and ``chartbook check`` say so
  (:func:`chartbook.run.build_tool_runs_chartbook_build`).
"""

import warnings
from pathlib import Path

import pytest
import tomli_w
from click.testing import CliRunner

from chartbook.__about__ import __version__
from chartbook.check import check_build_tool
from chartbook.cli import main
from chartbook.manifest import load_manifest, require_chartbook
from chartbook.run import build_tool_runs_chartbook_build


def _manifest(directory: Path, table: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
    return directory


def _requiring(value) -> dict:
    return {"project": {"requires_chartbook": value}}


class TestTheRequirement:
    @pytest.mark.parametrize("value", ["", f">={__version__}", ">=0.1", f"=={__version__}", ">=0.2.0,<99", "~=0.2"])
    def test_one_this_chartbook_meets_says_nothing(self, value):
        require_chartbook(_requiring(value), "x/chartbook.toml")
        require_chartbook({}, "x/chartbook.toml")  # no [project] at all
        require_chartbook({"project": {}}, "x/chartbook.toml")

    def test_one_it_does_not_meet_stops_with_the_upgrade(self):
        with pytest.raises(ValueError) as error:
            require_chartbook(_requiring(">=99.0"), "rates/chartbook.toml")
        assert str(error.value) == (
            f"rates/chartbook.toml requires ChartBook >=99.0 ([project] requires_chartbook), and this is ChartBook "
            f'{__version__}. Install one that meets it: `pip install -U "chartbook>=99.0"`, or '
            f'`uv add "chartbook>=99.0"` in a uv project.'
        )

    def test_an_upper_bound_is_honoured(self):
        with pytest.raises(ValueError, match="requires ChartBook <0.1"):
            require_chartbook(_requiring("<0.1"), "x/chartbook.toml")

    @pytest.mark.parametrize(
        "value, hint",
        [
            ("0.3.0", 'Write requires_chartbook = ">=0.3.0" for 0.3.0 or later.'),
            ("v0.3.0", 'Write requires_chartbook = ">=0.3.0" for 0.3.0 or later.'),
            ("chartbook>=0.3", 'Write requires_chartbook = ">=0.3": the specifier alone, without the package\'s name.'),
            ("soon", f'Write requires_chartbook = ">={__version__}", or take the key out.'),
        ],
    )
    def test_what_is_not_a_specifier_is_refused_with_the_one_to_write(self, value, hint):
        with pytest.raises(ValueError) as error:
            require_chartbook(_requiring(value), "x/chartbook.toml")
        assert f"requires_chartbook = {value!r} is not a version specifier. {hint}" in str(error.value)

    @pytest.mark.parametrize("value", [" ", ",", "\n"])
    def test_a_value_that_names_no_version_is_refused_not_taken_for_any(self, value):
        """Found by a reviewer: these were taken as "any version"."""
        with pytest.raises(ValueError, match="names no version"):
            require_chartbook(_requiring(value), "x/chartbook.toml")

    def test_a_number_too_long_to_read_names_the_file(self):
        with pytest.raises(ValueError, match=r"^x/chartbook.toml: \[project\]: requires_chartbook = '>=111"):
            require_chartbook(_requiring(">=" + "1" * 5000), "x/chartbook.toml")

    def test_a_non_string_is_refused(self):
        with pytest.raises(ValueError, match="is an integer"):
            require_chartbook(_requiring(3), "x/chartbook.toml")

    def test_it_is_a_known_key_not_warned_of(self, tmp_path):
        folder = _manifest(tmp_path / "p", {"project": {"requires_chartbook": f">={__version__}"}})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            load_manifest(folder)


class TestEveryCommandStops:
    @pytest.fixture
    def newer(self, tmp_path):
        return _manifest(
            tmp_path / "rates",
            {"project": {"requires_chartbook": ">=99.0"}, "scripts": {"build": "echo ran > ran.log"}},
        )

    @pytest.mark.parametrize(
        "words",
        [["docs", "build", "./site", "-f"], ["run"], ["check"], ["snapshot"], ["pin"]],
        ids=lambda w: " ".join(w),
    )
    def test_before_acting(self, newer, monkeypatch, words):
        monkeypatch.chdir(newer)
        result = CliRunner().invoke(main, words)
        assert result.exit_code != 0
        assert "requires ChartBook >=99.0 ([project] requires_chartbook)" in result.output, result.output
        assert not (newer / "ran.log").exists() and not (newer / "site").exists()


    def test_add_writes_nothing_to_a_manifest_for_a_newer_chartbook(self, newer, monkeypatch):
        """Found by a reviewer: `add` wrote [dependencies], and only then did the pin stop."""
        before = (newer / "chartbook.toml").read_text(encoding="utf-8")
        monkeypatch.chdir(newer)
        result = CliRunner().invoke(main, ["add", "acme/thing"])
        assert result.exit_code == 1 and "requires ChartBook >=99.0" in result.output
        assert (newer / "chartbook.toml").read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("words", [["catalog", "disable", "x"], ["catalog", "enable", "x"]])
    def test_the_catalog_commands_say_it_without_a_traceback(self, tmp_path, words):
        """Found by a reviewer: these were a Python traceback."""
        catalog = _manifest(tmp_path / "catalog", {"project": {"type": "catalog", "requires_chartbook": ">=99.0"}, "pipelines": {}})
        (tmp_path / "p").mkdir()
        args = words + ([str(tmp_path / "p")] if words[1] == "add" else []) + ["--catalog", str(catalog / "chartbook.toml")]
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 1, result.output
        assert "requires ChartBook >=99.0" in result.output and result.exception is None or isinstance(result.exception, SystemExit)

    def test_a_new_project_asks_for_the_chartbook_that_made_it(self, tmp_path):
        from cookiecutter.main import cookiecutter

        root = Path(__file__).parent.parent / "template"
        made = Path(cookiecutter(str(root), no_input=True, output_dir=str(tmp_path)))
        assert f'requires_chartbook = ">={__version__}"' in (made / "chartbook.toml").read_text(encoding="utf-8")
        load_manifest(made)  # and this ChartBook meets it


DODO_0_1 = 'def task_docs():\n    return {"actions": ["chartbook build -f"], "verbosity": 2}\n'


class TestABuildToolThatSaysChartbookBuild:
    def test_the_line_is_found_and_a_comment_is_not(self, tmp_path):
        (tmp_path / "dodo.py").write_text("## `doit` (and so `chartbook build`) runs every task\n" + DODO_0_1, encoding="utf-8", newline="\n")
        assert build_tool_runs_chartbook_build(tmp_path, "doit") == ("dodo.py", 3, "chartbook build -f")

    @pytest.mark.parametrize(
        "name, command, text, found",
        [
            ("Makefile", "make all", "docs:\n\tchartbook build -f\n", True),
            ("justfile", "just", "docs:\n    chartbook  build\n", True),
            ("dodo.py", "doit", 'A = CmdAction(["chartbook", "build", "-f"])\n', True),
            ("dodo.py", "doit", 'A = ["python -m chartbook.cli build -f"]\n', True),
            ("dodo.py", "uv run doit", '"actions": ["chartbook build -f"]\n', True),
            ("dodo.py", "doit", '"actions": ["chartbook docs build -f"]\n', False),
            ("dodo.py", "doit", '"actions": ["chartbook build_tools"]\n', False),
            ("dodo.py", "doit", "    # chartbook build -f, the old way\n", False),
            # Found by a reviewer: none of these runs `chartbook build` on this pipeline
            ("dodo.py", "doit", 'A = ["chartbook docs build -f"]  # was: chartbook build -f\n', False),
            ("dodo.py", "doit", 'def task_x():\n    """Runs chartbook build, the old way."""\n', False),
            ("dodo.py", "doit", 'A = ["chartbook build --project-dir ../upstream"]\n', False),
            ("dodo.py", "make", 'A = ["chartbook build -f"]\n', False),  # a dodo.py make does not read
            ("Makefile", "doit", "docs:\n\tchartbook build -f\n", False),  # a Makefile doit does not read
            ("Makefile", "make", "docs:\n\techo hi  # chartbook build\n", False),
        ],
    )
    def test_which_lines_count(self, tmp_path, name, command, text, found):
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
        assert (build_tool_runs_chartbook_build(tmp_path, command) is not None) is found

    def test_the_file_is_named_as_it_is_on_disk(self, tmp_path):
        (tmp_path / "Justfile").write_text("docs:\n    chartbook build\n", encoding="utf-8", newline="\n")
        assert build_tool_runs_chartbook_build(tmp_path, "just")[0] == "Justfile"




    @pytest.mark.parametrize("table", ["scripts", "project"])
    def test_check_reports_it_on_the_build_field_where_it_is_written(self, pipeline_project, table):
        (pipeline_project / "dodo.py").write_text(DODO_0_1, encoding="utf-8", newline="\n")
        text = (pipeline_project / "chartbook.toml").read_text(encoding="utf-8")
        if table == "scripts":
            text += '\n[scripts]\nbuild = "doit"\n'
        else:
            text = text.replace("[project]\n", '[project]\nbuild = "doit"\n', 1)
        (pipeline_project / "chartbook.toml").write_text(text, encoding="utf-8", newline="\n")
        (problem,) = check_build_tool(load_manifest(pipeline_project), pipeline_project)
        assert (problem.table, problem.field) == (table, "build")
        assert problem.message.startswith("dodo.py, line 2, runs `chartbook build` (chartbook build -f)")
        assert problem.message.endswith("the command that renders the site is `chartbook docs build -f`: say that in dodo.py")

    def test_check_warns_of_it_with_no_build_command_by_a_relative_path(self, pipeline_project, monkeypatch):
        (pipeline_project / "dodo.py").write_text(DODO_0_1, encoding="utf-8", newline="\n")
        monkeypatch.chdir(pipeline_project)
        with pytest.warns(UserWarning, match=r"^dodo.py, line 2: `chartbook build` renders the site here only because no build command is declared"):
            assert check_build_tool(load_manifest(pipeline_project), pipeline_project) == []
