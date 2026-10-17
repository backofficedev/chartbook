"""Tests for ``chartbook create-data-glimpses``: summaries come from the manifest."""

from pathlib import Path

import polars as pl
import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from chartbook.create_data_glimpses import (
    DeclaredDataframe,
    create_txt_report,
    find_declared_dataframes,
    get_dataset_report,
    heading_to_anchor,
)
from chartbook.create_data_glimpses import main as create_data_glimpses_main
from chartbook.manifest import load_manifest
from tests.fixtures import create_pipeline_project, create_sample_parquet


def _edit_toml(project_dir: Path, edit) -> None:
    toml_path = project_dir / "chartbook.toml"
    with open(toml_path, "rb") as f:
        config = tomli.load(f)
    edit(config)
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)


def _run(project_dir, *args):
    return CliRunner().invoke(
        main, ["create-data-glimpses", "--project-dir", str(project_dir), *args]
    )


class TestFindDeclaredDataframes:
    def test_lists_dataframes_in_manifest_order(self, pipeline_project_multi_dataframes):
        project = pipeline_project_multi_dataframes
        declared = find_declared_dataframes(load_manifest(project))
        assert [d.dataframe_id for d in declared] == ["dataframe_0", "dataframe_1"]
        first = declared[0]
        assert first.pipeline_id == "multi_df"
        assert first.name == "Dataframe 0"
        assert first.path == project / "_data" / "multi_df" / "dataframe_0.parquet"
        assert first.data_files() == [str(first.path)]

    def test_covers_every_pipeline_of_a_catalog(self, catalog_project):
        declared = find_declared_dataframes(load_manifest(catalog_project))
        assert [(d.pipeline_id, d.dataframe_id) for d in declared] == [
            ("pipeline_a", "dataframe_0"),
            ("pipeline_b", "dataframe_0"),
        ]

    def test_dataframe_without_a_path_is_left_out(self, pipeline_project):
        def edit(config):
            config["dataframes"]["no_path"] = {"name": "No Path", "docs": "Pending."}

        _edit_toml(pipeline_project, edit)
        declared = find_declared_dataframes(load_manifest(pipeline_project))
        assert [d.dataframe_id for d in declared] == ["dataframe_0"]

    def test_name_falls_back_to_the_id(self, pipeline_project):
        def edit(config):
            del config["dataframes"]["dataframe_0"]["name"]

        _edit_toml(pipeline_project, edit)
        (declared,) = find_declared_dataframes(load_manifest(pipeline_project))
        assert declared.name == "dataframe_0"

    def test_glob_path_expands_to_its_part_files(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        (declared,) = find_declared_dataframes(load_manifest(project))
        assert declared.is_glob
        files = declared.data_files()
        assert len(files) == 2
        assert all(f.endswith("data.parquet") for f in files)

    def test_data_files_is_empty_before_the_data_is_built(self, tmp_path):
        missing = DeclaredDataframe("p", "d", "D", tmp_path / "nope.parquet")
        assert missing.data_files() == []
        missing_glob = DeclaredDataframe("p", "d", "D", tmp_path / "x" / "*.parquet")
        assert missing_glob.data_files() == []


class TestDatasetReport:
    def test_single_parquet_file(self, tmp_path):
        parquet = create_sample_parquet(tmp_path / "data.parquet", rows=10)
        report = get_dataset_report(parquet)
        assert "error" not in report
        assert (report["n_rows"], report["n_cols"]) == (10, 4)
        assert report["file_type"] == "PARQUET"
        assert report["file_size_bytes"] == parquet.stat().st_size
        assert {c["name"] for c in report["columns"]} == {
            "date", "value", "category", "amount",
        }
        assert {s["name"] for s in report["numeric_stats"]} == {"value", "amount"}

    def test_csv_file(self, tmp_path):
        csv = tmp_path / "data.csv"
        pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).write_csv(csv)
        report = get_dataset_report(str(csv))
        assert (report["n_rows"], report["n_cols"], report["file_type"]) == (3, 2, "CSV")

    def test_glob_is_one_dataset_over_many_files(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        (declared,) = find_declared_dataframes(load_manifest(project))
        report = get_dataset_report(declared.path)
        assert "error" not in report
        # Two partitions of five rows; the partition column comes from the path
        assert report["n_rows"] == 10
        assert "category" in {c["name"] for c in report["columns"]}
        assert report["file_size_bytes"] == sum(
            Path(f).stat().st_size for f in declared.data_files()
        )

    def test_unreadable_file_reports_an_error(self, tmp_path):
        bad = tmp_path / "bad.parquet"
        bad.write_text("not parquet")
        assert get_dataset_report(bad)["error"].startswith("ERROR: Could not read file")

    def test_stats_can_be_skipped(self, tmp_path):
        parquet = create_sample_parquet(tmp_path / "data.parquet")
        assert get_dataset_report(parquet, include_stats=False)["numeric_stats"] == []


class TestReports:
    def test_txt_report_is_keyed_by_dataframe(self, pipeline_project_multi_dataframes):
        project = pipeline_project_multi_dataframes
        declared = find_declared_dataframes(load_manifest(project))
        report = create_txt_report(declared)
        assert "Total dataframes: 2" in report
        assert "## Summary of Dataframes by Pipeline" in report
        assert "### multi_df" in report
        assert "- [`dataframe_0`](#dataframe-0): Dataframe 0" in report
        assert "\n## dataframe_0\n**Name:** Dataframe 0\n**Path:** `" in report
        assert "\n## dataframe_1\n" in report
        assert "### Columns" in report
        assert "### Sample Values (first 5 rows)" in report
        assert "### Numeric Column Statistics" in report
        assert not report.rstrip().endswith("---")

    def test_sections_can_be_left_out(self, pipeline_project):
        declared = find_declared_dataframes(load_manifest(pipeline_project))
        report = create_txt_report(declared, include_samples=False, include_stats=False)
        assert "### Columns" in report
        assert "### Sample Values" not in report
        assert "### Numeric Column Statistics" not in report

    def test_catalog_sections_are_qualified_by_pipeline(self, catalog_project):
        """Two pipelines may both declare ``dataframe_0``; headings must not clash."""
        declared = find_declared_dataframes(load_manifest(catalog_project))
        report = create_txt_report(declared)
        assert "### pipeline_a" in report and "### pipeline_b" in report
        assert "\n## pipeline_a:dataframe_0\n" in report
        assert "\n## pipeline_b:dataframe_0\n" in report
        assert "- [`dataframe_0`](#pipeline-a-dataframe-0): Dataframe 0" in report

    def test_unreadable_data_is_reported_in_place(self, pipeline_project):
        declared = find_declared_dataframes(load_manifest(pipeline_project))
        declared[0].path.write_text("not parquet")
        report = create_txt_report(declared)
        assert "**ERROR:** ERROR: Could not read file" in report

    def test_all_null_numeric_column_does_not_break_the_report(self, tmp_path):
        """A numeric column with no values has no mean; the report must still write."""
        project = create_pipeline_project(tmp_path / "nulls")
        data_file = project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        pl.DataFrame(
            {"date": [1, 2, 3], "empty": pl.Series([None, None, None], dtype=pl.Float64)}
        ).write_parquet(data_file)
        declared = find_declared_dataframes(load_manifest(project))
        report = create_txt_report(declared)
        assert "empty: min=None, max=None, mean=None, median=None" in report

    def test_heading_to_anchor(self):
        assert heading_to_anchor("pipeline_a:dataframe_0") == "pipeline-a-dataframe-0"
        assert heading_to_anchor("Repo.Public") == "repo-public"


class TestCommand:
    def test_writes_report_from_the_manifest(self, pipeline_project, tmp_path):
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = _run(pipeline_project, "-o", out_dir)
        assert result.exit_code == 0, result.output
        report = (out_dir / "data_glimpses.md").read_text()
        assert "## dataframe_0" in report
        assert "10 rows × 4 columns" in report
        assert "Found 1 declared dataframes, 1 with data on disk" in result.output

    def test_an_output_dir_that_does_not_exist_is_made(self, pipeline_project, tmp_path):
        """Found by a new user: `-o DIR` with no such DIR wrote the report as a file named DIR."""
        out_dir = tmp_path / "reports" / "glimpses"
        result = _run(pipeline_project, "-o", out_dir)
        assert result.exit_code == 0, result.output
        assert out_dir.is_dir()
        assert "## dataframe_0" in (out_dir / "data_glimpses.md").read_text()

    def test_an_output_dir_that_is_a_file_is_said_plainly(self, pipeline_project, tmp_path):
        """Found by a reviewer: an existing file not ending in .md got a FileExistsError."""
        taken = tmp_path / "notes.txt"
        taken.write_text("mine\n")
        result = _run(pipeline_project, "-o", taken)
        assert result.exit_code == 1
        assert f"Error: {taken} is a file. Give a directory to write data_glimpses.md in" in result.output
        assert taken.read_text() == "mine\n"

    def test_help_shows_no_docstring_markup(self):
        result = CliRunner().invoke(main, ["create-data-glimpses", "--help"])
        assert result.exit_code == 0
        assert ":param" not in result.output and ":type" not in result.output
        assert "made if it does not exist" in " ".join(result.output.split())

    def test_needs_no_dodo_py(self, pipeline_project, tmp_path):
        """A project built with Snakemake, Make or plain scripts has no dodo.py."""
        assert not (pipeline_project / "dodo.py").exists()
        (pipeline_project / "Snakefile").write_text("rule all:\n    input: []\n")
        result = _run(pipeline_project, "-o", tmp_path / "glimpses.md")
        assert result.exit_code == 0, result.output
        assert "## dataframe_0" in (tmp_path / "glimpses.md").read_text()

    def test_does_not_read_dodo_py(self, pipeline_project, tmp_path, monkeypatch):
        """A dodo.py is never imported: one that cannot be imported changes nothing,
        and the data files it mentions are not picked up."""
        undeclared = create_sample_parquet(pipeline_project / "_data" / "undeclared.parquet")
        (pipeline_project / "dodo.py").write_text(
            "raise RuntimeError('dodo.py must not be imported')\n"
            f"def task_x():\n    return {{'targets': [{str(undeclared)!r}]}}\n"
        )
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(
            main, ["create-data-glimpses", "-o", str(tmp_path / "glimpses.md")]
        )
        assert result.exit_code == 0, result.output
        report = (tmp_path / "glimpses.md").read_text()
        assert "## dataframe_0" in report
        assert "undeclared" not in report

    def test_same_report_with_and_without_a_dodo_py(self, tmp_path):
        """Identical projects differ only in build tool; so do not their reports."""

        def report_for(name, with_dodo):
            project = create_pipeline_project(tmp_path / name, pipeline_id="same")
            if with_dodo:
                (project / "dodo.py").write_text("def task_x():\n    return {}\n")
            out = tmp_path / f"{name}.md"
            assert _run(project, "-o", out).exit_code == 0
            lines = out.read_text().splitlines()
            return [
                line.replace(str(project), "<project>")
                for line in lines
                if not line.startswith("Generated: ")
            ]

        assert report_for("doit", True) == report_for("plain", False)

    def test_defaults_to_current_directory(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["create-data-glimpses"])
        assert result.exit_code == 0, result.output
        assert (pipeline_project / "data_glimpses.md").exists()

    def test_glob_dataframe(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        result = _run(project, "-o", tmp_path / "glimpses.md")
        assert result.exit_code == 0, result.output
        report = (tmp_path / "glimpses.md").read_text()
        assert "## dataframe_0" in report
        assert "10 rows" in report
        assert "ERROR" not in report

    def test_dataframe_not_built_yet_is_skipped(self, pipeline_project_multi_dataframes, tmp_path):
        project = pipeline_project_multi_dataframes
        (project / "_data" / "multi_df" / "dataframe_1.parquet").unlink()
        result = _run(project, "-o", tmp_path / "glimpses.md")
        assert result.exit_code == 0, result.output
        assert "Found 2 declared dataframes, 1 with data on disk" in result.output
        assert "Skipping multi_df:dataframe_1" in result.output
        report = (tmp_path / "glimpses.md").read_text()
        assert "## dataframe_0" in report
        assert "dataframe_1" not in report

    def test_catalog(self, catalog_project, tmp_path):
        result = _run(catalog_project, "-o", tmp_path / "glimpses.md")
        assert result.exit_code == 0, result.output
        report = (tmp_path / "glimpses.md").read_text()
        assert "## pipeline_a:dataframe_0" in report
        assert "## pipeline_b:dataframe_0" in report

    def test_no_manifest_is_a_clean_error(self, tmp_path):
        result = _run(tmp_path)
        assert result.exit_code == 1
        assert "Error: No chartbook.toml found" in result.output

    def test_sample_and_stats_flags(self, pipeline_project, tmp_path):
        result = _run(
            pipeline_project, "-o", tmp_path / "g.md", "--no-samples", "--no-stats"
        )
        assert result.exit_code == 0, result.output
        report = (tmp_path / "g.md").read_text()
        assert "### Sample Values" not in report
        assert "### Numeric Column Statistics" not in report


def test_main_writes_into_an_output_directory(pipeline_project, tmp_path, monkeypatch):
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    create_data_glimpses_main(output_dir=out_dir, project_dir=pipeline_project)
    assert (out_dir / "data_glimpses.md").exists()


def test_main_raises_without_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="No chartbook.toml"):
        create_data_glimpses_main(project_dir=tmp_path)
