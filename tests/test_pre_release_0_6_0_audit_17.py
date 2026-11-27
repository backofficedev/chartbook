"""Regression tests for the seventeenth pre-release 0.6.0 audit."""

from __future__ import annotations

import decimal
import json
from pathlib import Path

import pandas as pd
import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import cli, formats, indexdiff, plotting
from chartbook.plotting._overlays import _color_to_rgba
from chartbook.resolve import FileLocation


class TestAudit17FormatsDecimalHiveKey:
    def test_arrow_dataset_handles_decimal_hive_key(self, tmp_path):
        root = tmp_path / "data"
        part = root / "k=1.23" / "part.ipc"
        part.parent.mkdir(parents=True)
        pl.DataFrame(
            {"k": pl.Series("k", [decimal.Decimal("1.23")], dtype=pl.Decimal(10, 2)), "v": [1]}
        ).write_ipc(part)
        ds = formats.arrow_dataset(FileLocation(path=root, format="ipc"))
        table = ds.to_table()
        assert table.column("k").to_pylist() == ["1.23"]
        assert table.column("v").to_pylist() == [1]


class TestAudit17PlottingEdgeCases:
    @pytest.mark.parametrize("stacked", [True, False])
    def test_matplotlib_area_handles_object_dtype_with_none(self, tmp_path, stacked):
        df = pd.DataFrame({
            "x": [1, 2, 3],
            "y1": pd.Series([1.0, None, 3.0], dtype=object),
            "y2": pd.Series([2.0, 3.0, None], dtype=object),
        })
        result = plotting.area(df, x="x", y=["y1", "y2"], stacked=stacked).save(
            f"area_{stacked}", output_dir=tmp_path
        )
        assert result.png_path is not None and result.png_path.is_file()

    def test_matplotlib_bands_handles_object_dtype_with_none(self, tmp_path):
        df = pd.DataFrame({
            "x": [1, 2, 3],
            "y1": pd.Series([1.0, None, 3.0], dtype=object),
            "y2": pd.Series([2.0, 3.0, None], dtype=object),
        })
        result = plotting.line(
            df,
            x="x",
            y="y1",
            bands=[{"y_upper": "y2", "y_lower": "y1"}],
        ).save("bands_obj", output_dir=tmp_path)
        assert result.png_path is not None and result.png_path.is_file()

    def test_color_to_rgba_handles_4char_and_malformed_hex(self):
        assert _color_to_rgba("#f008", 0.5) == "rgba(255, 0, 0, 0.5)"
        assert _color_to_rgba("#ff000080", 0.5) == "rgba(255, 0, 0, 0.5)"
        # Malformed hex falls back cleanly instead of raising ValueError
        fallback = _color_to_rgba("#zz", 0.5)
        assert fallback.startswith("rgba(")


class TestAudit17CliLsAndIndexDiff:
    def test_ls_catalog_nonexistent_file_does_not_load_sibling_manifest(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text('[project]\nname = "Real Pipeline"\n', encoding="utf-8")
        res = CliRunner().invoke(cli.main, ["ls", "--catalog", str(tmp_path / "does_not_exist.toml")])
        assert res.exit_code == 1
        assert "not found" in res.output.lower()

    def test_index_diff_ignores_missing_or_non_string_column_and_version_names(self, tmp_path):
        before = {
            "records": [
                {"kind": "Dataframe", "id": "p:d", "columns": []},
                {"kind": "Model", "id": "p:model/m", "versions": []},
            ]
        }
        after = {
            "records": [
                {"kind": "Dataframe", "id": "p:d", "columns": [{}, {"name": 123}, {"name": "a"}]},
                {"kind": "Model", "id": "p:model/m", "versions": [{}, {"version": None}, {"version": "v1"}]},
            ]
        }
        found = indexdiff.diff(before, after)
        text = indexdiff.format_diff(found)
        assert "a" in text
        assert "v1" in text
        (tmp_path / "a.json").write_text(json.dumps(before), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(after), encoding="utf-8")
        res = CliRunner().invoke(cli.main, ["index", "diff", str(tmp_path / "a.json"), str(tmp_path / "b.json")])
        assert res.exit_code == 0


class TestAudit17SkillAndChangelog:
    def test_skill_copies_are_synced_and_without_duplicate_run_typo(self):
        root = Path(__file__).resolve().parent.parent
        copies = [
            root / "src" / "chartbook" / "skills" / "SKILL.md",
            root / ".claude" / "skills" / "chartbook" / "SKILL.md",
            root / "template" / "{{cookiecutter.project_slug}}" / ".claude" / "skills" / "chartbook" / "SKILL.md",
        ]
        texts = [p.read_text(encoding="utf-8") for p in copies]
        assert texts[0] == texts[1] == texts[2]
        assert "`chartbook run` and `chartbook run`" not in texts[0]
