"""Regression tests for the seventh pre-release 0.6.0 audit."""

from __future__ import annotations

import polars as pl
from click.testing import CliRunner

from chartbook import create_data_glimpses, utils
from chartbook.cli import main as cli
from chartbook.plotting._validation import validate_dataframe


class TestWildcardColumnSafety:
    def test_glimpse_text_handles_star_float32_column(self):
        df = pl.DataFrame({
            "*": pl.Series([1.5, 2.5], dtype=pl.Float32),
            "label": ["foo", "bar"],
        })
        text = utils.glimpse_text(df)
        assert "*" in text
        assert "foo" in text

    def test_most_recent_valid_datapoints_handles_star_column(self, tmp_path):
        pq = tmp_path / "star.parquet"
        pl.DataFrame({
            "date": ["2025-01-01", "2025-06-15"],
            "*": [1.0, 2.0],
        }).write_parquet(pq)
        first, last = utils.most_recent_valid_datapoints(pq, "date")
        assert first == "2025-06-15 00:00:00"
        assert last == "2025-06-15 00:00:00"

    def test_dataset_report_handles_star_column(self, tmp_path):
        pq = tmp_path / "star_report.parquet"
        pl.DataFrame({"date": ["2025-01-01", "2025-06-15"], "*": [1.0, 3.0]}).write_parquet(pq)
        report = create_data_glimpses.get_dataset_report(pq, include_stats=True)
        assert "error" not in report
        assert report["n_rows"] == 2
        assert any(s["name"] == "*" and s["min"] == 1.0 and s["max"] == 3.0 for s in report["numeric_stats"])

    def test_plotting_validate_dataframe_handles_star_decimal_and_categorical(self):
        df_dec = pl.DataFrame({
            "*": pl.Series(["1.25", "2.50"]).cast(pl.Decimal(10, 2)),
            "label": ["foo", "bar"],
        })
        pdf_dec = validate_dataframe(df_dec)
        assert list(pdf_dec["label"]) == ["foo", "bar"]
        assert list(pdf_dec["*"]) == [1.25, 2.5]

        df_cat = pl.DataFrame({
            "*": pl.Series(["a", "b"], dtype=pl.Categorical),
            "val": [1, 2],
        })
        pdf_cat = validate_dataframe(df_cat)
        assert list(pdf_cat["val"]) == [1, 2]
        assert pdf_cat["val"].dtype.kind in ("i", "u", "f")


class TestDocsBuildDirectoryGuards:
    def test_docs_build_rejects_project_dir_as_docs_build_or_temp_src(self, tmp_path):
        proj = tmp_path / "my_pipeline"
        proj.mkdir()
        (proj / "chartbook.toml").write_text('[project]\nid = "p"\ntitle = "P"\n', encoding="utf-8")
        runner = CliRunner()

        for flag in ("--docs-build-dir", "--temp-docs-src-dir"):
            res = runner.invoke(
                cli,
                ["docs", "build", str(tmp_path / "out"), "--project-dir", str(proj), flag, str(proj)],
            )
            assert res.exit_code != 0
            assert "project directory" in res.output.lower()
            assert (proj / "chartbook.toml").is_file()
