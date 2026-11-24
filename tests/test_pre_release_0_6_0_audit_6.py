"""Regression tests for the sixth pre-release 0.6.0 audit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import formats, index, lineage, rowhash
from chartbook.cli import main as cli


class TestRowhashFormatsIndex:
    def test_text_bytes_handles_corrupt_gzip_deflate_payload(self, tmp_path):
        bad_gz = tmp_path / "corrupt.jsonl.gz"
        bad_gz.write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"\xff" * 50)
        assert rowhash._text_bytes(bad_gz, 1000) == bad_gz.stat().st_size

    def test_formats_scan_escapes_star_column_name(self, tmp_path):
        jsonl = tmp_path / "star.jsonl"
        jsonl.write_text('{"*": "1", "b": 2}\n{"*": "3", "b": 4}\n', encoding="utf-8")
        df = formats.scan(jsonl, read_options={"schema_overrides": {"*": "Int64"}}).collect()
        assert df.columns == ["*", "b"]
        assert df["*"].dtype == pl.Int64
        assert df["*"].to_list() == [1, 3]

    def test_index_date_range_handles_star_and_regex_date_columns(self, tmp_path):
        for col_name in ("*", "^date$"):
            pq = tmp_path / f"d_{abs(hash(col_name))}.parquet"
            pl.DataFrame({col_name: ["2025-01-01", "2025-06-15"], "v": [1, 2]}).write_parquet(pq)
            span = index._date_range(pq, col_name)
            assert span == {"first": "2025-01-01T00:00:00", "last": "2025-06-15T00:00:00"}


class TestLineagePipelineDisambiguation:
    def test_finder_pinned_filters_by_pipeline(self):
        commit = "d" * 40
        made_at = "2026-01-01T00:00:00Z"
        snap_c = SimpleNamespace(
            pipeline="pipe_c",
            commit=commit,
            made_at=made_at,
            same_moment=lambda c, m: (c, m) == (commit, made_at),
        )
        snap_b = SimpleNamespace(
            pipeline="pipe_b",
            commit=commit,
            made_at=made_at,
            same_moment=lambda c, m: (c, m) == (commit, made_at),
        )
        finder = object.__new__(lineage._Finder)
        finder.follow_pins = True
        finder.read_here = True
        finder.shared = {"found": [snap_c, snap_b]}
        assert finder._pinned(commit, made_at, "pipe_b") is snap_b
        assert finder._pinned(commit, made_at, "pipe_missing") is None


class TestCliGuardsAndErrorHandling:
    def test_docs_build_rejects_project_dir_and_parent_as_output_dir(self, tmp_path):
        proj = tmp_path / "my_pipeline"
        proj.mkdir()
        (proj / "chartbook.toml").write_text('[project]\nid = "p"\ntitle = "P"\n', encoding="utf-8")
        runner = CliRunner()

        res_same = runner.invoke(cli, ["docs", "build", str(proj), "--project-dir", str(proj), "-f"])
        assert res_same.exit_code != 0
        assert "project directory" in res_same.output.lower()
        assert (proj / "chartbook.toml").is_file()

        res_parent = runner.invoke(cli, ["docs", "build", str(tmp_path), "--project-dir", str(proj), "-f"])
        assert res_parent.exit_code != 0
        assert "project directory" in res_parent.output.lower()
        assert (proj / "chartbook.toml").is_file()

    def test_ls_stores_and_versions_fail_on_nonexistent_catalog(self, tmp_path):
        missing = tmp_path / "does_not_exist" / "catalog.toml"
        runner = CliRunner()
        for sub in ("stores", "versions"):
            res = runner.invoke(cli, ["ls", "--catalog", str(missing), sub])
            assert res.exit_code != 0
            assert "not found" in res.output.lower()

    def test_data_get_docs_path_handles_missing_catalog_cleanly(self, tmp_path):
        missing = tmp_path / "missing" / "catalog.toml"
        runner = CliRunner()
        res = runner.invoke(
            cli,
            ["data", "get-docs-path", "--pipeline", "p", "--dataframe", "d", "--catalog", str(missing)],
        )
        assert res.exit_code != 0
        assert res.exception is None or isinstance(res.exception, SystemExit)
        assert "error:" in res.output.lower()

    def test_catalog_disable_rejects_non_table_project_cleanly(self, tmp_path):
        cat = tmp_path / "catalog.toml"
        cat.write_text('project = "oops"\n', encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["catalog", "disable", "acme/rates", "--catalog", str(cat)])
        assert res.exit_code != 0
        assert res.exception is None or isinstance(res.exception, SystemExit)
        assert "[project] must be a table" in res.output
