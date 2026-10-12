"""Tests for ``chartbook check`` and the checks behind it."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.check import (
    Problem,
    check_licenses,
    check_paths,
    check_required_fields,
    display_path,
    load_policy,
    parse_expiration,
    run_checks,
)
from chartbook.cli import main
from chartbook.manifest import load_manifest

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


def load_policy_dict():
    """The lenient policy in resolved form, as load_policy would return it."""
    return {
        "mode": "warn",
        "required": {**LENIENT_POLICY["policy"]["required"], "notebooks": []},
    }


class TestLoadPolicy:
    def test_reads_policy_table_from_a_file(self, lenient_policy):
        assert load_policy(lenient_policy) == load_policy_dict()

    def test_accepts_a_directory(self, catalog_project):
        policy = load_policy(catalog_project)
        assert policy["mode"] == "warn"
        assert "repo_url" in policy["required"]["project"]

    def test_does_not_load_member_pipelines(self, tmp_path):
        """A catalog whose members are absent still yields its policy."""
        catalog = tmp_path / "chartbook.toml"
        catalog.write_text(
            '[pipelines."acme/gone"]\npath = "../not-checked-out"\n\n'
            '[policy.required]\nproject = ["maintainer"]\n'
        )
        assert load_policy(catalog)["required"]["project"] == ["maintainer"]

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_policy(tmp_path / "nope.toml")

    def test_invalid_policy(self, tmp_path):
        bad = tmp_path / "chartbook.toml"
        bad.write_text('[policy]\nmode = "loud"\n')
        with pytest.raises(ValueError, match="invalid policy.mode"):
            load_policy(bad)


class TestProblemFormat:
    def test_names_file_table_and_field(self, tmp_path):
        problem = Problem(tmp_path / "chartbook.toml", "charts.gdp", "units", "bad")
        assert problem.format() == f"{tmp_path / 'chartbook.toml'}: [charts.gdp] units: bad"

    def test_relative_when_beneath_cwd(self, tmp_path):
        problem = Problem(tmp_path / "a" / "chartbook.toml", "project", "name", "bad")
        assert problem.format(relative_to=tmp_path).startswith("a/chartbook.toml: ")

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

    def test_missing_required_fields_exit_nonzero(self, pipeline_project):
        result = _invoke("--project-dir", pipeline_project)
        assert result.exit_code == 1
        assert "chartbook.toml: [project] repo_url: required by the default policy" in (
            result.output
        )
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
        result = _invoke("--project-dir", catalog_project)
        assert result.exit_code == 1
        assert "required by the catalog policy" in result.output
        assert "pipeline_a/chartbook.toml: [project] repo_url" in result.output
        assert "pipeline_b/chartbook.toml: [project] repo_url" in result.output
        assert "in 2 manifest(s)" in result.output

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
        policy.write_text('[policy.required]\nproject = ["site_dir"]\n')
        result = _invoke("--project-dir", pipeline_project, "--policy", policy)
        assert result.exit_code == 1
        assert f"[project] site_dir: required by the policy in {policy}" in result.output
        assert "repo_url" not in result.output

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

    def test_negative_window_is_a_usage_error(self, pipeline_project):
        result = _invoke("--project-dir", pipeline_project, "--within", "-1")
        assert result.exit_code == 2
