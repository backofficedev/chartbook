"""Tests for ``chartbook check`` and the checks behind it."""

import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import os

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.check import (
    Problem,
    check_licenses,
    check_paths,
    check_required_fields,
    check_siblings,
    display_path,
    load_policy,
    parse_expiration,
    run_checks,
)
from chartbook.cli import main
from chartbook.manifest import load_manifest
from tests.fixtures import remove_tree

TODAY = date(2026, 6, 15)

# A policy the fixture projects satisfy, so tests can isolate one failure
LENIENT_POLICY = {
    "policy": {
        "required": {"project": ["name"], "dataframes": ["name"], "charts": ["name"]}
    }
}


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = project_dir / "chartbook.toml"
    with open(toml_path, "rb") as f:
        config = tomli.load(f)
    edit(config)
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)


def _set_license_expiration(project_dir: Path, value) -> None:
    def edit(config):
        config["dataframes"]["dataframe_0"]["license_expiration"] = value

    _edit_toml(project_dir, edit)


@pytest.fixture
def lenient_policy(tmp_path):
    """A TOML file holding only a [policy] the fixture projects satisfy."""
    policy_path = tmp_path / "policy.toml"
    with open(policy_path, "wb") as f:
        tomli_w.dump(LENIENT_POLICY, f)
    return policy_path


def _invoke(*args):
    return CliRunner().invoke(main, ["check", *map(str, args)])


class TestParseExpiration:
    def test_iso_string(self):
        assert parse_expiration("2026-12-31") == date(2026, 12, 31)

    def test_toml_date_and_datetime(self):
        assert parse_expiration(date(2026, 12, 31)) == date(2026, 12, 31)
        assert parse_expiration(datetime(2026, 12, 31, 8, 30)) == date(2026, 12, 31)

    def test_iso_datetime_string(self):
        assert parse_expiration("2026-12-31T08:30:00") == date(2026, 12, 31)

    @pytest.mark.parametrize("value", [None, "", "  ", "N/A", "n/a", "None", "never"])
    def test_no_expiration(self, value):
        assert parse_expiration(value) is None

    @pytest.mark.parametrize("value", ["Dec 2025", "12/31/2025", "soon", 20261231])
    def test_unreadable(self, value):
        with pytest.raises(ValueError):
            parse_expiration(value)


class TestCheckLicenses:
    def _problems(self, project_dir, value, within_days=30):
        _set_license_expiration(project_dir, value)
        manifest = load_manifest(project_dir)
        return check_licenses(
            manifest, project_dir, within_days=within_days, today=TODAY
        )

    def test_expired(self, pipeline_project):
        (problem,) = self._problems(pipeline_project, "2026-06-01")
        assert problem.table == "dataframes.dataframe_0"
        assert problem.field == "license_expiration"
        assert "expired on 2026-06-01 (14 days ago)" in problem.message
        assert problem.file == pipeline_project.resolve() / "chartbook.toml"

    def test_expires_today(self, pipeline_project):
        (problem,) = self._problems(pipeline_project, TODAY.isoformat())
        assert "expires today" in problem.message

    def test_expiring_inside_window(self, pipeline_project):
        (problem,) = self._problems(pipeline_project, "2026-07-15")
        assert "expires on 2026-07-15 (in 30 days" in problem.message

    def test_outside_window_passes(self, pipeline_project):
        assert self._problems(pipeline_project, "2026-07-16") == []

    def test_window_is_configurable(self, pipeline_project):
        assert self._problems(pipeline_project, "2026-07-16", within_days=31)
        assert self._problems(pipeline_project, "2026-06-16", within_days=0) == []

    def test_native_toml_date(self, pipeline_project):
        (problem,) = self._problems(pipeline_project, date(2026, 6, 1))
        assert "expired on 2026-06-01" in problem.message

    def test_not_applicable_passes(self, pipeline_project):
        assert self._problems(pipeline_project, "N/A") == []

    def test_unreadable_date_is_a_problem(self, pipeline_project):
        (problem,) = self._problems(pipeline_project, "Dec 2025")
        assert "cannot read 'Dec 2025' as a date" in problem.message
        assert "YYYY-MM-DD" in problem.message

    def test_no_field_passes(self, pipeline_project):
        manifest = load_manifest(pipeline_project)
        assert check_licenses(manifest, pipeline_project, today=TODAY) == []


class TestCheckPaths:
    def test_healthy_project_has_no_problems(self, pipeline_project):
        manifest = load_manifest(pipeline_project)
        assert check_paths(manifest, pipeline_project) == []

    def test_missing_dataframe_file(self, pipeline_project):
        parquet = pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        parquet.unlink()
        manifest = load_manifest(pipeline_project)
        (problem,) = check_paths(manifest, pipeline_project)
        assert (problem.table, problem.field) == ("dataframes.dataframe_0", "path")
        assert "file not found" in problem.message
        assert "dataframe_0.parquet" in problem.message

    def test_missing_chart_and_docs_files(self, pipeline_project):
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        (pipeline_project / "docs_src" / "charts" / "chart_0_0.md").unlink()
        (pipeline_project / "docs_src" / "dataframes" / "dataframe_0.md").unlink()
        manifest = load_manifest(pipeline_project)
        found = {(p.table, p.field) for p in check_paths(manifest, pipeline_project)}
        assert found == {
            ("charts.chart_0_0", "path"),
            ("charts.chart_0_0", "docs_path"),
            ("dataframes.dataframe_0", "docs_path"),
        }

    def test_missing_note_and_readme(self, pipeline_project_with_notes):
        project = pipeline_project_with_notes
        (project / "docs_src" / "note1.md").unlink()
        (project / "README.md").unlink()
        manifest = load_manifest(project)
        found = {(p.table, p.field) for p in check_paths(manifest, project)}
        assert found == {("notes.note1", "path"), ("project", "readme")}

    def test_readme_setting_is_what_gets_checked(self, pipeline_project):
        (pipeline_project / "README.md").rename(pipeline_project / "ABOUT.md")
        manifest = load_manifest(pipeline_project)
        (problem,) = check_paths(manifest, pipeline_project)
        assert (problem.table, problem.field) == ("project", "readme")
        assert "README.md" in problem.message

        _edit_toml(pipeline_project, lambda c: c["project"].update(readme="./ABOUT.md"))
        manifest = load_manifest(pipeline_project)
        assert check_paths(manifest, pipeline_project) == []

    def test_missing_notebook(self, pipeline_project):
        def edit(config):
            config["notebooks"]["analysis"] = {
                "name": "Analysis",
                "path": "_output/analysis.ipynb",
            }

        _edit_toml(pipeline_project, edit)
        manifest = load_manifest(pipeline_project)
        (problem,) = check_paths(manifest, pipeline_project)
        assert (problem.table, problem.field) == ("notebooks.analysis", "path")

    def test_missing_logo_and_favicon(self, pipeline_project):
        def edit(config):
            config["project"]["logo"] = "./assets/logo.png"
            config["project"]["favicon"] = "./assets/favicon.ico"

        _edit_toml(pipeline_project, edit)
        manifest = load_manifest(pipeline_project)
        found = {(p.table, p.field) for p in check_paths(manifest, pipeline_project)}
        assert found == {("project", "logo"), ("project", "favicon")}

    def test_glob_matching_nothing(self, tmp_path):
        from tests.fixtures import create_pipeline_project

        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        for parquet in (project / "_data").rglob("*.parquet"):
            parquet.unlink()
        manifest = load_manifest(project)
        (problem,) = check_paths(manifest, project)
        assert (problem.table, problem.field) == ("dataframes.dataframe_0", "path")
        assert "no files match" in problem.message


class TestCheckSiblings:
    """A path that names one file of a set, as `transcripts_2026.parquet` did in #135."""

    def _files(self, folder: Path, *names) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_bytes(b"not read")

    def _said(self, project: Path, path: str) -> list[str]:
        _edit_toml(project, lambda c: c["dataframes"]["dataframe_0"].update(path=path))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert check_siblings(load_manifest(project), project) == []
        return [str(warning.message) for warning in caught]

    def test_a_year_of_a_yearly_set_is_warned_with_the_glob(self, pipeline_project):
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2014, 2027)))
        (said,) = self._said(pipeline_project, "./_data/transcripts_2026.parquet")
        assert said.startswith("chartbook.toml: [dataframes.dataframe_0] path: ./_data/transcripts_2026.parquet ")
        assert "the 12 files beside it named the same but for a number or date" in said
        assert "(transcripts_2014.parquet … transcripts_2025.parquet)" in said
        assert said.endswith('write path = "./_data/transcripts_*.parquet".')

    @pytest.mark.parametrize(
        "declared, siblings, glob",
        [
            ("rates_2026-10.parquet", ("rates_2026-09.parquet", "rates_2025-12.parquet"), "rates_*.parquet"),
            ("rates_20261027.parquet", ("rates_20261026.parquet", "rates_20261025.parquet"), "rates_*.parquet"),
            ("rates_2026_10.parquet", ("rates_2025_12.parquet", "rates_2026_09.parquet"), "rates_*.parquet"),
            ("2026-10-27_rates.parquet", ("2026-10-26_rates.parquet", "2026-10-25_rates.parquet"), "*_rates.parquet"),
            ("part-00010.parquet", ("part-00009.parquet", "part-00011.parquet"), "part-*.parquet"),
        ],
    )
    def test_a_number_or_a_date(self, pipeline_project, declared, siblings, glob):
        self._files(pipeline_project / "_data", declared, *siblings)
        (said,) = self._said(pipeline_project, f"_data/{declared}")
        assert f"no asset declares the 2 files beside it named the same but for a number or date ({', '.join(sorted(siblings))})" in said
        assert said.endswith(f'write path = "_data/{glob}".')

    def test_a_number_of_another_width_is_not_a_sibling(self, pipeline_project):
        """Tenors are datasets of their own; years, dates and counted parts are written to one width."""
        self._files(pipeline_project / "_data", *(f"yields_{tenor}y.parquet" for tenor in (1, 2, 10, 30)))
        assert self._said(pipeline_project, "_data/yields_10y.parquet") == []
        self._files(pipeline_project / "_data", "yields_20y.parquet")
        (said,) = self._said(pipeline_project, "_data/yields_10y.parquet")
        assert "the 2 files beside it" in said and "(yields_20y.parquet, yields_30y.parquet)" in said

    @pytest.mark.parametrize(
        "others",
        [
            ("transcripts_2025_old.parquet", "transcripts_2024_old.parquet"),  # more than the number differs
            ("transcripts_2025-12.parquet", "transcripts_2024-12.parquet"),  # a date of another shape
            ("transcripts_2025.csv", "transcripts_2024.csv"),
            ("old_transcripts_2025.parquet", "old_transcripts_2024.parquet"),
            ("transcripts.parquet", "transcripts_.parquet"),
            ("._transcripts_2025.parquet", "._transcripts_2024.parquet"),  # never part of an asset
            ("transcripts_2025.parquet",),  # one is not a set
        ],
    )
    def test_a_file_named_otherwise_is_not_a_sibling(self, pipeline_project, others):
        self._files(pipeline_project / "_data", "transcripts_2026.parquet", *others)
        assert self._said(pipeline_project, "_data/transcripts_2026.parquet") == []

    @pytest.mark.parametrize(
        "declared, others",
        [
            ("results_v2.parquet", ("results_v1.parquet", "results_v3.parquet")),
            ("data.h5", ("data.h4", "data.h6")),
            ("part_1.parquet", ("part_2.parquet", "part_3.parquet")),
        ],
    )
    def test_a_one_digit_number_is_a_version_more_often_than_a_part(self, pipeline_project, declared, others):
        self._files(pipeline_project / "_data", declared, *others)
        assert self._said(pipeline_project, f"_data/{declared}") == []

    def test_only_the_files_own_folder_is_looked_at(self, pipeline_project):
        self._files(pipeline_project / "_data", "transcripts_2026.parquet")
        self._files(pipeline_project / "_data" / "old", "transcripts_2025.parquet", "transcripts_2024.parquet")
        self._files(pipeline_project / "_data" / "transcripts_2025.parquet")  # a folder
        self._files(pipeline_project / "_data" / "transcripts_2024.parquet")
        assert self._said(pipeline_project, "_data/transcripts_2026.parquet") == []

    def test_a_sibling_some_path_names_already_does_not_count(self, pipeline_project):
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2021, 2027)))
        self._files(pipeline_project / "_models")

        def declare(config):
            dataframe = config["dataframes"]["dataframe_0"]
            config["dataframes"]["older"] = {**dataframe, "path": "_data/transcripts_202[2-3].parquet"}
            config["dataframes"]["year_2024"] = {**dataframe, "path": "_data/transcripts_2024.parquet"}
            # A model's path, written the long way round
            config["models"] = {"m": {"name": "M", "path": "./_models/../_data/transcripts_2021.parquet", "docs": "M"}}

        _edit_toml(pipeline_project, declare)
        # Only 2025 is left, and one is not a set
        assert self._said(pipeline_project, "_data/transcripts_2026.parquet") == []

        self._files(pipeline_project / "_data", "transcripts_2020.parquet")
        said = self._said(pipeline_project, "_data/transcripts_2026.parquet")
        # year_2024 is told the same
        assert [line.split("]")[0] for line in said] == ["chartbook.toml: [dataframes.dataframe_0", "chartbook.toml: [dataframes.year_2024"]
        assert all("the 2 files beside it" in line and "(transcripts_2020.parquet, transcripts_2025.parquet)" in line for line in said)

        def declare_the_rest(config):
            config["dataframes"]["rest"] = {**config["dataframes"]["year_2024"], "path": "_data/transcripts_202[05].parquet"}

        _edit_toml(pipeline_project, declare_the_rest)
        assert self._said(pipeline_project, "_data/transcripts_2026.parquet") == []

    def test_a_folder_some_path_names_holds_its_files(self, pipeline_project):
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2024, 2027)))
        _edit_toml(pipeline_project, lambda c: c.update(models={"m": {"name": "M", "path": "_data", "docs": "M"}}))
        assert self._said(pipeline_project, "_data/transcripts_2026.parquet") == []

    def test_a_glob_a_folder_and_a_missing_file_are_not_looked_at(self, pipeline_project):
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2023, 2027)))
        self._files(pipeline_project / "_data" / "transcripts_2022")
        for path in ("_data/transcripts_202[56].parquet", "_data/transcripts_2022", "_data/transcripts_2027.parquet"):
            assert self._said(pipeline_project, path) == [], path

    def test_every_number_that_differs_is_a_star(self, pipeline_project):
        """Found by a reviewer: `transcripts_2026_q*` left 8 of 12 quarters out, and silenced the warning."""
        self._files(pipeline_project / "_data", *(f"transcripts_{y}_q{q}.parquet" for y in (2024, 2025, 2026) for q in range(1, 5)))
        (said,) = self._said(pipeline_project, "_data/transcripts_2026_q4.parquet")
        assert "the 11 files beside it named the same but for numbers or dates" in said
        assert "(transcripts_2024_q1.parquet … transcripts_2026_q3.parquet)" in said
        assert said.endswith('write path = "_data/transcripts_*_q*.parquet".')

        # Only the run that differs is a star
        self._files(pipeline_project / "_data", "rates_10y_2026.parquet", "rates_10y_2025.parquet", "rates_10y_2024.parquet")
        (said,) = self._said(pipeline_project, "_data/rates_10y_2026.parquet")
        assert said.endswith('write path = "_data/rates_10y_*.parquet".')

    def test_a_star_that_would_take_in_another_file_is_a_digit_for_a_digit(self, pipeline_project):
        names = ("transcripts_2024.parquet", "transcripts_2025.parquet", "transcripts_2026.parquet")
        self._files(pipeline_project / "_data", *names, "transcripts_sample.parquet", "transcripts_2025_old.parquet")
        (said,) = self._said(pipeline_project, "_data/transcripts_2026.parquet")
        assert said.endswith('write path = "_data/transcripts_[0-9][0-9][0-9][0-9].parquet".')
        assert sorted(path.name for path in (pipeline_project / "_data").glob("transcripts_[0-9][0-9][0-9][0-9].parquet")) == list(names)

    def test_the_path_it_suggests_is_written_with_forward_slashes(self, pipeline_project):
        """A Windows path's `\\t` in the TOML string the warning gives would be a tab."""
        if os.sep != "\\":
            pytest.skip("a backslash is a folder's separator on Windows only")
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2024, 2027)))
        (said,) = self._said(pipeline_project, "_data\\transcripts_2026.parquet")
        assert said.endswith('write path = "_data/transcripts_*.parquet".')

    def test_a_name_with_digits_python_reads_otherwise(self, pipeline_project):
        """Found by a reviewer: `²` is a digit to str.isdigit and not to int(), and check crashed."""
        self._files(pipeline_project / "_data", "t1²10.parquet", "t1²11.parquet", "t1²12.parquet", "t²12.parquet")
        (said,) = self._said(pipeline_project, "_data/t1²10.parquet")
        assert said.endswith('write path = "_data/t1²*.parquet".')

    def test_under_a_folder_with_glob_characters_in_its_name(self, tmp_path):
        """Found by a reviewer: in `Research [2026]/`, a file a path named was not seen as declared."""
        from tests.fixtures import create_pipeline_project

        project = create_pipeline_project(tmp_path / "Research [2026]" / "proj")
        self._files(project / "_data", *(f"transcripts_{year}.parquet" for year in range(2024, 2027)))

        def declare(config):
            dataframe = config["dataframes"]["dataframe_0"]
            config["dataframes"]["y2025"] = {**dataframe, "path": "_data/transcripts_2025.parquet"}
            config["dataframes"]["y2024"] = {**dataframe, "path": "_data/transcripts_202[4].parquet"}

        _edit_toml(project, declare)
        assert self._said(project, "_data/transcripts_2026.parquet") == []

    def test_a_model_is_not_looked_at(self, pipeline_project):
        """A model's path cannot be a glob, and its older files are more often old versions."""
        self._files(pipeline_project / "_models", *(f"forecaster_{year}.joblib" for year in range(2024, 2027)))
        _edit_toml(
            pipeline_project,
            lambda c: c.update(models={"f": {"name": "F", "path": "_models/forecaster_2026.joblib", "docs": "F"}}),
        )
        assert self._said(pipeline_project, "_data/test_pipeline/dataframe_0.parquet") == []

    def test_a_folder_is_listed_once(self, pipeline_project, monkeypatch):
        self._files(pipeline_project / "_data", *(f"t_{year}.parquet" for year in range(2014, 2027)), "notes.txt")

        def declare(config):
            dataframe = config["dataframes"]["dataframe_0"]
            config["dataframes"].update({f"t_{year}": {**dataframe, "path": f"_data/t_{year}.parquet"} for year in range(2020, 2027)})
            config["dataframes"]["plain"] = {**dataframe, "path": "_data/notes.txt"}

        _edit_toml(pipeline_project, declare)
        manifest = load_manifest(pipeline_project)
        listed = []
        scandir = os.scandir
        monkeypatch.setattr(os, "scandir", lambda folder: listed.append(folder) or scandir(folder))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check_siblings(manifest, pipeline_project)
        assert len(caught) == 7 and all("the 6 files beside it" in str(w.message) for w in caught)
        assert len(listed) == 1

    def test_check_warns_and_passes(self, pipeline_project, lenient_policy):
        self._files(pipeline_project / "_data", *(f"transcripts_{year}.parquet" for year in range(2024, 2027)))
        _edit_toml(pipeline_project, lambda c: c["dataframes"]["dataframe_0"].update(path="_data/transcripts_2026.parquet"))
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 0, result.output
        assert (
            "warning: chartbook.toml: [dataframes.dataframe_0] path: _data/transcripts_2026.parquet may be one file of a set"
        ) in result.stderr


class TestCheckRequiredFields:
    def test_default_policy_names_each_missing_field(self, pipeline_project):
        manifest = load_manifest(pipeline_project)
        problems = check_required_fields(
            manifest, pipeline_project, policy_label="the default policy"
        )
        found = {(p.table, p.field) for p in problems}
        assert ("project", "repo_url") in found
        assert ("dataframes.dataframe_0", "pull_method") in found
        assert ("charts.chart_0_0", "units") in found
        # Fields the fixture does fill in are not reported
        assert ("project", "name") not in found
        assert all("the default policy" in p.message for p in problems)

    def test_missing_docs_is_reported_as_one_field(self, pipeline_project):
        manifest = load_manifest(pipeline_project)
        manifest["policy"] = load_policy_dict()
        manifest["dataframes"]["dataframe_0"].pop("docs_path")
        (problem,) = check_required_fields(manifest, pipeline_project)
        assert problem.field == "docs_path or docs"

    def test_a_missing_write_up_is_a_problem_with_no_policy_too(self, pipeline_project):
        """Found by a reviewer: with no policy, a blank write-up became a recommendation,
        though the format requires exactly one of docs_path and docs."""
        manifest = load_manifest(pipeline_project)
        manifest["dataframes"]["dataframe_0"]["docs_path"] = "  "
        with pytest.warns(UserWarning, match="recommended by the default policy"):
            problems = check_required_fields(manifest, pipeline_project, warn_only=True)
        (problem,) = problems
        assert (problem.table, problem.field) == ("dataframes.dataframe_0", "docs_path or docs")
        assert problem.message == "required by the format, but missing or empty"

    def test_catalog_policy_points_at_each_member_manifest(self, catalog_project):
        def edit(config):
            config["policy"] = {
                "mode": "warn",
                "required": {
                    "project": ["repo_url"],
                    "dataframes": [],
                    "charts": [],
                },
            }

        _edit_toml(catalog_project, edit)
        manifest = load_manifest(catalog_project)
        problems = check_required_fields(manifest, catalog_project)
        assert {p.file for p in problems} == {
            catalog_project.resolve() / "pipelines" / pid / "chartbook.toml"
            for pid in ("pipeline_a", "pipeline_b")
        }
        assert {(p.table, p.field) for p in problems} == {("project", "repo_url")}

    def test_the_default_policy_recommends_the_build_script_in_scripts(self, pipeline_project):
        """Found by a new user's walkthrough: with no build script, check named `[project] build`,
        the old place, where getting-started and the reference write `[scripts] build`."""
        manifest = load_manifest(pipeline_project)
        assert not manifest["project"].get("build")
        with pytest.warns(UserWarning) as caught:
            check_required_fields(manifest, pipeline_project, warn_only=True)
        said = [str(warning.message) for warning in caught]
        assert "chartbook.toml: [scripts] build: recommended by the default policy, but missing or empty" in said
        assert not any("[project] build" in line for line in said)

    @pytest.mark.parametrize("place", ["scripts", "project"])
    def test_either_place_gives_the_build_script(self, pipeline_project, place):
        _edit_toml(pipeline_project, lambda config: config.setdefault(place, {}).update(build="doit"))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            check_required_fields(load_manifest(pipeline_project), pipeline_project, warn_only=True)
        assert not any("build:" in str(warning.message) for warning in caught)

    def test_a_catalogs_policy_naming_build_is_met_by_either_place(self, catalog_project):
        """`project = ["build"]` in a catalog's [policy] goes on working, and says where to write it."""

        def require_build(config):
            config["policy"] = {"required": {"project": ["build"], "dataframes": [], "charts": []}}

        _edit_toml(catalog_project, require_build)
        member_a = catalog_project / "pipelines" / "pipeline_a"
        member_b = catalog_project / "pipelines" / "pipeline_b"
        _edit_toml(member_a, lambda config: config.setdefault("scripts", {}).update(build="doit"))
        (problem,) = check_required_fields(load_manifest(catalog_project), catalog_project)
        assert problem.file == member_b.resolve() / "chartbook.toml"
        assert problem.format().endswith("[scripts] build: required by the active policy, but missing or empty")
        _edit_toml(member_b, lambda config: config["project"].update(build="doit"))
        assert check_required_fields(load_manifest(catalog_project), catalog_project) == []


def load_policy_dict():
    """The lenient policy in resolved form, as load_policy would return it."""
    return {
        "mode": "warn",
        "required": {
            **LENIENT_POLICY["policy"]["required"],
            "notebooks": [],
            # Not in the file, so the default list for models
            "models": ["name", "description", "trained_on", "docs", "path"],
        },
    }


class TestLoadPolicy:
    def test_reads_policy_table_from_a_file(self, lenient_policy):
        assert load_policy(lenient_policy) == load_policy_dict()

    def test_read_policy_says_whether_the_file_has_one(self, lenient_policy, catalog_project):
        from chartbook.check import read_policy

        assert read_policy(lenient_policy) == (load_policy_dict(), True)
        defaults, given = read_policy(catalog_project)
        assert given is False and defaults == load_policy(catalog_project)

    def test_accepts_a_directory(self, catalog_project):
        policy = load_policy(catalog_project)
        assert policy["mode"] == "warn"
        assert "repo_url" in policy["required"]["project"]

    def test_does_not_load_member_pipelines(self, tmp_path):
        """A catalog whose members are absent still yields its policy."""
        catalog = tmp_path / "chartbook.toml"
        catalog.write_text(
            '[pipelines."acme/gone"]\npath = "../not-checked-out"\n\n'
            '[policy.required]\nproject = ["maintainer"]\n', encoding="utf-8", newline="\n"
        )
        assert load_policy(catalog)["required"]["project"] == ["maintainer"]

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_policy(tmp_path / "nope.toml")

    def test_invalid_policy(self, tmp_path):
        bad = tmp_path / "chartbook.toml"
        bad.write_text('[policy]\nmode = "loud"\n', encoding="utf-8", newline="\n")
        with pytest.raises(ValueError, match="invalid policy.mode"):
            load_policy(bad)


class TestProblemFormat:
    def test_names_file_table_and_field(self, tmp_path):
        problem = Problem(tmp_path / "chartbook.toml", "charts.gdp", "units", "bad")
        assert problem.format() == f"{tmp_path / 'chartbook.toml'}: [charts.gdp] units: bad"

    def test_relative_when_beneath_cwd(self, tmp_path):
        problem = Problem(tmp_path / "a" / "chartbook.toml", "project", "name", "bad")
        assert problem.format(relative_to=tmp_path).startswith(os.path.join("a", "chartbook.toml") + ": ")

    def test_absolute_when_outside(self, tmp_path):
        elsewhere = tmp_path / "elsewhere" / "chartbook.toml"
        assert display_path(elsewhere, relative_to=tmp_path / "here") == elsewhere


class TestRunChecks:
    def test_problems_are_grouped_by_manifest(self, catalog_project):
        manifest = load_manifest(catalog_project)
        problems = run_checks(manifest, catalog_project, today=TODAY)
        files = [p.file for p in problems]
        assert files == sorted(files)
        assert len(set(files)) == 2


class TestCheckCommand:
    def test_healthy_project_exits_zero(self, pipeline_project, lenient_policy):
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 0, result.output
        assert "OK (1 pipeline(s), 1 dataframes, 1 charts, 0 notebooks)" in result.output

    def test_uses_current_directory_by_default(
        self, pipeline_project, lenient_policy, monkeypatch
    ):
        monkeypatch.chdir(pipeline_project)
        result = _invoke("--policy", lenient_policy)
        assert result.exit_code == 0, result.output
        assert result.output.startswith("chartbook.toml: OK")

    def test_with_no_policy_recommended_fields_are_warnings(self, pipeline_project):
        """A pipeline made as the docs show, with no [policy] anywhere, passes."""
        result = _invoke("--project-dir", pipeline_project)
        assert result.exit_code == 0, result.output
        assert (
            "warning: chartbook.toml: [project] repo_url: recommended by the "
            "default policy, but missing or empty"
        ) in result.stderr
        assert "required by" not in result.output
        assert "problem(s) found" not in result.output
        assert "OK (1 pipeline(s)" in result.stdout

    def test_pipeline_policy_makes_missing_fields_fail(self, pipeline_project):
        def edit(config):
            config["policy"] = {"required": {"project": ["repo_url"]}}

        _edit_toml(pipeline_project, edit)
        result = _invoke("--project-dir", pipeline_project)
        assert result.exit_code == 1
        assert (
            "chartbook.toml: [project] repo_url: required by the pipeline's policy"
        ) in result.output
        assert "problem(s) found in 1 manifest(s)" in result.output

    def test_broken_path_exits_nonzero(self, pipeline_project, lenient_policy):
        (pipeline_project / "_output" / "charts" / "chart_0_0.html").unlink()
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 1
        assert "[charts.chart_0_0] path: file not found" in result.output
        assert "1 problem(s) found" in result.output

    def test_expired_license_exits_nonzero(self, pipeline_project, lenient_policy):
        expired = date.today() - timedelta(days=3)
        _set_license_expiration(pipeline_project, expired.isoformat())
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 1
        assert (
            f"[dataframes.dataframe_0] license_expiration: license expired on {expired}"
            in result.output
        )

    def test_within_widens_the_license_window(self, pipeline_project, lenient_policy):
        soon = date.today() + timedelta(days=45)
        _set_license_expiration(pipeline_project, soon.isoformat())
        args = ("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert _invoke(*args).exit_code == 0
        result = _invoke(*args, "--within", "60")
        assert result.exit_code == 1
        assert "inside the 60-day window" in result.output

    def test_catalog_checks_every_member(self, catalog_project):
        def edit(config):
            config["policy"] = {"required": {"project": ["repo_url"]}}

        _edit_toml(catalog_project, edit)
        result = _invoke("--project-dir", catalog_project)
        assert result.exit_code == 1
        assert "required by the catalog policy" in result.output
        assert os.path.join("pipeline_a", "chartbook.toml") + ": [project] repo_url" in result.output
        assert os.path.join("pipeline_b", "chartbook.toml") + ": [project] repo_url" in result.output
        assert "in 2 manifest(s)" in result.output

    def test_policy_of_a_catalog_that_sets_none_only_warns(self, pipeline_project, catalog_project):
        """Found by a reviewer: `--policy ../catalog`, the documented way for a member to
        check itself, failed on the default fields when the catalog sets no policy."""
        result = _invoke("--project-dir", pipeline_project, "--policy", catalog_project)
        assert result.exit_code == 0, result.output
        assert "[project] repo_url: recommended by the default policy" in result.stderr
        assert "required by" not in result.output

    def test_catalog_with_no_policy_only_warns(self, catalog_project):
        """A member's own [policy] is ignored inside a catalog, so none is given."""

        def edit(config):
            config["policy"] = {"required": {"project": ["repo_url"]}}

        _edit_toml(catalog_project / "pipelines" / "pipeline_a", edit)
        result = _invoke("--project-dir", catalog_project)
        assert result.exit_code == 0, result.output
        assert os.path.join("pipeline_a", "chartbook.toml") + ": [project] repo_url: recommended" in (
            result.stderr
        )
        assert os.path.join("pipeline_b", "chartbook.toml") + ": [project] repo_url: recommended" in (
            result.stderr
        )

    def test_catalog_passes_with_policy_it_satisfies(self, catalog_project):
        def edit(config):
            config["policy"] = LENIENT_POLICY["policy"]

        _edit_toml(catalog_project, edit)
        result = _invoke("--project-dir", catalog_project)
        assert result.exit_code == 0, result.output
        assert "OK (2 pipeline(s), 2 dataframes, 2 charts, 0 notebooks)" in result.output

    def test_warn_mode_still_fails_the_check(self, catalog_project):
        """policy.mode governs builds; a check reports missing fields regardless."""

        def edit(config):
            config["policy"] = {"mode": "warn", "required": {"project": ["repo_url"]}}

        _edit_toml(catalog_project, edit)
        assert _invoke("--project-dir", catalog_project).exit_code == 1

    def test_policy_option_overrides_and_is_named(self, pipeline_project, tmp_path):
        policy = tmp_path / "strict.toml"
        policy.write_text('[policy.required]\nproject = ["site_dir"]\n', encoding="utf-8", newline="\n")
        result = _invoke("--project-dir", pipeline_project, "--policy", policy)
        assert result.exit_code == 1
        assert f"[project] site_dir: required by the policy in {policy}" in result.output
        assert "repo_url" not in result.output

    def test_a_policy_that_is_not_a_table_is_a_clean_error(self, pipeline_project, tmp_path):
        """Found by a reviewer: `policy = "strict"` gave an AttributeError traceback."""
        for text, said in (('policy = "strict"\n', "[policy] must be a table"), ('[policy]\nrequired = "x"\n', "policy.required must be a table")):
            policy = tmp_path / "odd.toml"
            policy.write_text(text, encoding="utf-8", newline="\n")
            result = _invoke("--project-dir", pipeline_project, "--policy", policy)
            assert result.exit_code == 1
            assert f"Error: {policy}: {said}" in result.output
            assert "Traceback" not in result.output and "AttributeError" not in result.output

    def test_missing_policy_file_is_a_clean_error(self, pipeline_project, tmp_path):
        result = _invoke(
            "--project-dir", pipeline_project, "--policy", tmp_path / "nope.toml"
        )
        assert result.exit_code == 1
        assert "Error: No policy file found" in result.output

    def test_unloadable_manifest_is_a_clean_error(self, invalid_project_v1_format):
        result = _invoke("--project-dir", invalid_project_v1_format)
        assert result.exit_code == 1
        assert "Error: " in result.output
        assert "v1 format" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_missing_manifest_is_a_clean_error(self, invalid_project_missing_file):
        result = _invoke("--project-dir", invalid_project_missing_file)
        assert result.exit_code == 1
        assert "No chartbook.toml found" in result.output

    def test_manifest_warnings_are_reported_but_do_not_fail(
        self, pipeline_project, lenient_policy
    ):
        def edit(config):
            config["project"]["maintaner"] = "Typo Person"

        _edit_toml(pipeline_project, edit)
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 0, result.output
        assert "warning: " in result.output
        assert "unknown key 'maintaner'" in result.output

    def test_skip_outputs_passes_a_project_that_has_not_been_built(
        self, pipeline_project_with_notes, lenient_policy
    ):
        """A fresh checkout in CI: sources are there, nothing has been built."""
        import shutil

        project = pipeline_project_with_notes
        remove_tree(project / "_data")
        remove_tree(project / "_output")
        args = ("--project-dir", project, "--policy", lenient_policy)

        without = _invoke(*args)
        assert without.exit_code == 1
        # Nothing built is not a mistake in the manifest, and the way on is named
        assert "[dataframes.dataframe_0] path: not built yet:" in without.output
        assert "[charts.chart_0_0] path: not built yet:" in without.output
        assert "file not found" not in without.output
        # It has no build script, so `chartbook build` would build nothing
        assert "Nothing is built yet: build its outputs (it has no build script" in without.output
        assert "the same check with --skip-outputs checks the rest" in without.output

        result = _invoke(*args, "--skip-outputs")
        assert result.exit_code == 0, result.output
        assert "built outputs not checked" in result.output

    def test_a_pipeline_with_a_build_script_that_has_built_nothing_is_told_to_run_it(
        self, pipeline_project_with_notes, lenient_policy
    ):
        import shutil

        project = pipeline_project_with_notes

        def edit(config):
            config.setdefault("scripts", {})["build"] = "doit"

        _edit_toml(project, edit)
        remove_tree(project / "_data")
        remove_tree(project / "_output")
        result = _invoke("--project-dir", project, "--policy", lenient_policy)
        assert result.exit_code == 1
        assert "Nothing is built yet: `chartbook build` builds it" in result.output

    def test_a_catalog_is_told_a_file_is_not_found(self, catalog_project, lenient_policy):
        """`chartbook docs generate` tells "not built yet" for a lone pipeline only; so does check."""
        import shutil

        # pipeline_a has built nothing, pipeline_b everything: "nothing is built" would be wrong
        remove_tree(catalog_project / "pipelines" / "pipeline_a" / "_data")
        remove_tree(catalog_project / "pipelines" / "pipeline_a" / "_output")
        result = _invoke("--project-dir", catalog_project, "--policy", lenient_policy)
        assert result.exit_code == 1, result.output
        assert "file not found" in result.output
        assert "not built yet" not in result.output
        assert "Nothing is built yet" not in result.output

    def test_a_pipeline_built_in_part_lacks_a_file(self, pipeline_project, lenient_policy):
        """Built, and one output missing: that is a mistake, and no "nothing is built" hint."""
        (pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet").unlink()
        result = _invoke("--project-dir", pipeline_project, "--policy", lenient_policy)
        assert result.exit_code == 1
        assert "[dataframes.dataframe_0] path: file not found" in result.output
        assert "not built yet" not in result.output
        assert "Nothing is built yet" not in result.output

    def test_skip_outputs_still_checks_files_kept_in_the_repository(
        self, pipeline_project_with_notes, lenient_policy
    ):
        project = pipeline_project_with_notes
        (project / "docs_src" / "charts" / "chart_0_0.md").unlink()
        (project / "docs_src" / "note1.md").unlink()
        (project / "README.md").unlink()
        result = _invoke(
            "--project-dir", project, "--policy", lenient_policy, "--skip-outputs"
        )
        assert result.exit_code == 1
        assert "[charts.chart_0_0] docs_path: file not found" in result.output
        assert "[notes.note1] path: file not found" in result.output
        assert "[project] readme: file not found" in result.output

    def test_skip_outputs_still_checks_fields_and_licenses(self, pipeline_project):
        expired = date.today() - timedelta(days=3)
        _set_license_expiration(pipeline_project, expired.isoformat())
        policy = pipeline_project.parent / "policy.toml"
        policy.write_text('[policy.required]\nproject = ["repo_url"]\n', encoding="utf-8", newline="\n")
        result = _invoke(
            "--project-dir", pipeline_project, "--policy", policy, "--skip-outputs"
        )
        assert result.exit_code == 1
        assert f"[project] repo_url: required by the policy in {policy}" in result.output
        assert "license expired on" in result.output

    def test_skip_outputs_covers_notebooks_and_globs(self, tmp_path, lenient_policy):
        from tests.fixtures import create_pipeline_project

        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        for parquet in (project / "_data").rglob("*.parquet"):
            parquet.unlink()

        def edit(config):
            config["notebooks"]["analysis"] = {"path": "_output/analysis.ipynb"}

        _edit_toml(project, edit)
        args = ("--project-dir", project, "--policy", lenient_policy)
        assert _invoke(*args).exit_code == 1
        assert _invoke(*args, "--skip-outputs").exit_code == 0

    def test_negative_window_is_a_usage_error(self, pipeline_project):
        result = _invoke("--project-dir", pipeline_project, "--within", "-1")
        assert result.exit_code == 2

    def test_a_field_of_the_wrong_type_is_a_clean_error_that_names_it(self, pipeline_project):
        """Found by a reviewer: `docs_path = 5` passed the load and `check` died on `.strip()`;
        `[notes.x]` with no path was printed as `Error: 'path'`."""
        _edit_toml(pipeline_project, lambda c: c["dataframes"]["dataframe_0"].update(docs_path=5))
        result = _invoke("--project-dir", pipeline_project)
        assert result.exit_code == 1
        assert "Error: " in result.output
        assert "[dataframes.dataframe_0]: docs_path = 5 is an integer, and docs_path is a string." in result.output
        assert "Traceback" not in result.output and "AttributeError" not in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

        _edit_toml(pipeline_project, lambda c: c["dataframes"]["dataframe_0"].update(docs_path="docs_src/dataframes/dataframe_0.md"))
        _edit_toml(pipeline_project, lambda c: c.update(notes={"methods": {"name": "Methods"}}))
        result = _invoke("--project-dir", pipeline_project)
        assert result.exit_code == 1
        assert "[notes.methods] has no 'path'. Say where the note's markdown file is" in result.output
        assert "Error: 'path'" not in result.output

    def test_a_policy_file_that_is_not_toml_is_named(self, pipeline_project, tmp_path):
        policy = tmp_path / "policy.toml"
        policy.write_text("[policy\n", encoding="utf-8", newline="\n")
        result = _invoke("--project-dir", pipeline_project, "--policy", policy)
        assert result.exit_code == 1
        assert f"Error: {policy} is not valid TOML: " in result.output and "Traceback" not in result.output

    def test_a_catalog_member_that_is_not_toml_is_named(self, catalog_project):
        """Found by a reviewer: the error was `Illegal character '\\n' (at line 2, column 15)` and no file."""
        member = catalog_project / "pipelines" / "pipeline_a" / "chartbook.toml"
        member.write_text("[project]\nname = \"unterminated\n", encoding="utf-8", newline="\n")
        result = _invoke("--project-dir", catalog_project)
        assert result.exit_code == 1
        assert f"Error: {member} is not valid TOML: " in result.output
        assert "Traceback" not in result.output
