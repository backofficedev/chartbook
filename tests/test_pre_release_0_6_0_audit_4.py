"""Regression tests for the fourth pre-release 0.6.0 audit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import (
    catalog_config,
    config,
    data,
    files,
    formats,
    lock,
    plotting,
    refs,
    rowhash,
    sitefiles,
    store,
    utils,
)
from chartbook.cli import main as cli
from chartbook.plotting._exceptions import DataValidationError
from chartbook.writers.mkdocs import MkDocsWriter
from chartbook.writers.sphinx import SphinxWriter


def _write_pipeline(root: Path, toml_text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "chartbook.toml").write_text(toml_text, encoding="utf-8", newline="\n")
    return root


class TestFormatsAndRowhash:
    def test_rowhash_multi_file_parquet_glob_preserves_hive_columns(self, tmp_path):
        p1 = tmp_path / "g" / "year=2024" / "p1.parquet"
        p2 = tmp_path / "g" / "year=2025" / "p2.parquet"
        p1.parent.mkdir(parents=True)
        p2.parent.mkdir(parents=True)
        pl.DataFrame({"v": [1]}).write_parquet(p1)
        pl.DataFrame({"v": [2]}).write_parquet(p2)

        pattern = str(tmp_path / "g" / "**" / "*.parquet")
        scanned = formats.scan(pattern).collect()
        table = rowhash.Table(pattern)
        batches = list(table.batches())
        combined = pl.concat([pl.from_arrow(b) for b in batches])

        assert sorted(combined.rows()) == sorted(scanned.rows())
        assert rowhash.hash_rows(table).rows["all"] == rowhash.hash_frame(scanned)

    def test_sql_matches_load_on_parquet_globs(self, tmp_path):
        pipe = _write_pipeline(
            tmp_path / "p",
            """
[config]
type = "pipeline"

[site]
title = "P"
author = "A"
copyright = "2026"
logo_path = ""
favicon_path = ""

[pipeline]
id = "p"
pipeline_name = "P"
pipeline_description = "P"
lead_pipeline_developer = "A"
contributors = ["A"]
runs_on = "Windows/Linux/MacOS"
git_repo_URL = ""
README_file_path = "./README.md"

[dataframes.codes]
dataframe_name = "codes"
path = "./_data/codes/**/*.parquet"

[dataframes.mismatched]
dataframe_name = "mismatched"
path = "./_data/mis/**/*.parquet"
""",
        )
        (pipe / "README.md").write_text("# P\n", encoding="utf-8")
        c1 = pipe / "_data" / "codes" / "code=007" / "part.parquet"
        c1.parent.mkdir(parents=True)
        pl.DataFrame({"x": [1]}).write_parquet(c1)

        m1 = pipe / "_data" / "mis" / "a=1" / "b=x" / "p1.parquet"
        m2 = pipe / "_data" / "mis" / "a=2" / "p2.parquet"
        m1.parent.mkdir(parents=True)
        m2.parent.mkdir(parents=True)
        pl.DataFrame({"x": [1]}).write_parquet(m1)
        pl.DataFrame({"x": [2]}).write_parquet(m2)

        load_codes = data.load("codes", project_dir=pipe).collect()
        sql_codes = data.sql("select * from {codes}", project_dir=pipe).collect()
        assert load_codes.schema == sql_codes.schema
        assert load_codes.rows() == sql_codes.rows()

        load_mis = data.load("mismatched", project_dir=pipe).collect()
        sql_mis = data.sql("select * from {mismatched}", project_dir=pipe).collect()
        assert sorted(load_mis.rows()) == sorted(sql_mis.rows())

    def test_csv_unnamed_header_colliding_with_column_1(self, tmp_path):
        csv_path = tmp_path / "t.csv"
        csv_path.write_text(",column_1\n0,2\n", encoding="utf-8", newline="\n")
        df = formats.scan(csv_path, "csv").collect()
        assert df.shape == (1, 2)
        assert "column_1" in df.columns
        assert len(set(df.columns)) == 2

    def test_pandas_of_int128_regex_column_name(self):
        if not hasattr(pl, "Int128"):
            pytest.skip("Polars build lacks Int128")
        lf = pl.DataFrame(
            {"a": [1], "^a$": pl.Series([2], dtype=pl.Int128)}
        ).lazy()
        pdf = formats._pandas_of(lf)
        assert pdf["a"].tolist() == [1]
        assert pdf["^a$"].tolist() == ["2"]


class TestPathsAndConfig:
    def test_listing_root_under_glob_char_directory(self, tmp_path):
        folder = tmp_path / "Research [2026]" / "pipe" / "_data" / "raw"
        folder.mkdir(parents=True)
        assert files.listing_root(folder) == folder
        assert files.listing_root(folder / "*.txt") == folder

    def test_most_recent_valid_datapoints_under_glob_char_directory(self, tmp_path):
        p = tmp_path / "Research [2026]" / "pipe" / "_data" / "prices.parquet"
        p.parent.mkdir(parents=True)
        pl.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=3, freq="D"), "v": [1.0, 2.0, 3.0]}
        ).write_parquet(p)
        first, last = utils.most_recent_valid_datapoints(p, date_col="date")
        assert first != "N/A" and last != "N/A"

    def test_without_credentials_password_containing_at(self):
        msg = "Failed to open s3://user:p@ssword@bucket/prefix"
        cleaned = config.without_credentials(msg)
        assert "p@ssword" not in cleaned
        assert "ssword" not in cleaned
        assert "s3://bucket/prefix" in cleaned

    def test_whitespace_catalog_path_normalized_empty(self, tmp_path):
        settings = tmp_path / "settings.toml"
        settings.write_text('[catalog]\npath = "   "\n', encoding="utf-8")
        normalized = config._normalized({"catalog": {"path": "   "}}, settings)
        assert normalized["catalog"]["path"] == ""

    def test_catalog_config_malformed_toml_raises_value_error(self, tmp_path):
        bad = tmp_path / "chartbook.toml"
        bad.write_text('project = "foo"\n', encoding="utf-8")
        with pytest.raises(ValueError):
            catalog_config.migrate(bad)

        no_stores = tmp_path / "catalog.toml"
        no_stores.write_text('schema = "chartbook/catalog/v1"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="stores"):
            catalog_config.route("acme/p", ["default"], no_stores)


class TestStoreAndMigration:
    def test_pending_write_handles_lone_surrogate(self, tmp_path):
        s = store.FolderStore(tmp_path / "store")
        pending = s.begin("acme/p", "a" * 40, "2026-01-01T00:00:00Z")
        doc = {
            "schema": "chartbook/snapshot/v2",
            "pipeline": "acme/p",
            "commit": "a" * 40,
            "made_at": "2026-01-01T00:00:00Z",
            "title": "bad \ud800 name",
            "assets": {},
        }
        record_path = pending.write(doc)
        loaded = json.loads(record_path.read_text(encoding="utf-8"))
        assert loaded["title"] == "bad \ud800 name"

    def test_remove_snapshot_evicts_found_whole_cache(self, tmp_path):
        s = store.FolderStore(tmp_path / "store")
        data_bytes = b"hello world"
        src = tmp_path / "f.bin"
        src.write_bytes(data_bytes)
        from chartbook import hashing

        digest = hashing.hash_file(src)
        p1 = s.begin("acme/p", "a" * 40, "2026-01-01T00:00:00Z")
        stored = p1.put(src, "_data/f.bin")
        digest = stored.content_hash
        rec1 = p1.write(
            {
                "schema": "chartbook/snapshot/v2",
                "root": "acme/p",
                "code": {"commit": "a" * 40},
                "made_at": "2026-01-01T00:00:00Z",
                "records": [
                    {
                        "id": "acme/p:f",
                        "content_hash": digest,
                        "size_bytes": len(data_bytes),
                        "stored": {
                            "single": True,
                            "files": [{"path": "_data/f.bin", "size_bytes": len(data_bytes), "content_hash": digest}],
                        },
                    }
                ],
            }
        )
        assert s.incomplete(digest, len(data_bytes), {"_data/f.bin": len(data_bytes)}, pipeline="acme/p") is None
        assert any(seen[0] == str(s.root) and seen[1] == digest for seen in store._found_whole)
        s.remove_snapshot(rec1)
        assert not any(seen[0] == str(s.root) and seen[1] == digest for seen in store._found_whole)


class TestResolveLockRunLineage:
    def test_parse_asset_ref_non_string_raises_value_error(self):
        with pytest.raises(ValueError):
            refs.parse_asset_ref(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            refs.parse_asset_ref(123)  # type: ignore[arg-type]

    def test_lock_read_malformed_content_hash_raises_lock_error(self, tmp_path):
        lf = tmp_path / lock.LOCK_FILE
        lf.write_text(
            json.dumps(
                {
                    "schema": "chartbook/lock/v1",
                    "dependencies": [{"id": "acme/up", "snapshot": "2026-01-01T00:00:00Z"}],
                    "assets": [
                        {
                            "id": "acme/up:chart:c",
                            "pipeline": "acme/up",
                            "ref": {"kind": "chart", "name": "c"},
                            "content_hash": "sha256:" + "0" * 64,
                        },
                        {
                            "id": "acme/up:dataframe:d",
                            "pipeline": "acme/up",
                            "ref": {"kind": "dataframe", "name": "d"},
                            "content_hash": "deadbeef_no_colon",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(lock.LockError):
            lock.read_lock(lf)


class TestDocsCliAndWriters:
    def test_glob_files_asset_gets_image_preview(self, tmp_path):
        plots = tmp_path / "_data" / "plots"
        plots.mkdir(parents=True)
        img = plots / "a.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        pattern = str(plots / "*.png")
        rec = {
            "kind": "File",
            "id": "p:file:plots",
            "pipeline": "p",
            "ref": {"kind": "file", "name": "plots"},
            "content_hash": "sha256:" + "0" * 64,
            "files": [{"path": "a.png", "size_bytes": 8}],
            "location": {"kind": "file", "resolved_path": pattern},
        }
        plan = sitefiles.copy_plan({"records": [rec]}, tmp_path / "site")
        assert any(src.resolve() == img.resolve() for src, _ in plan)

        writer = SphinxWriter({"records": [rec]}, tmp_path / "site")
        preview = writer.files_preview(rec)
        assert preview is not None and preview["kind"] == "image"

    def test_run_check_ignores_missing_default_catalog(self, tmp_path, monkeypatch):
        pipe = _write_pipeline(
            tmp_path / "p",
            """
[config]
type = "pipeline"

[site]
title = "P"
author = "A"
copyright = "2026"
logo_path = ""
favicon_path = ""

[pipeline]
id = "p"
pipeline_name = "P"
pipeline_description = "P"
lead_pipeline_developer = "A"
contributors = ["A"]
runs_on = "Windows/Linux/MacOS"
git_repo_URL = ""
README_file_path = "./README.md"
""",
        )
        (pipe / "README.md").write_text("# P\n", encoding="utf-8")
        monkeypatch.setattr(config, "get_default_catalog_path", lambda: tmp_path / "nonexistent" / "catalog.toml")
        res = CliRunner().invoke(cli, ["run", "--check", "--project-dir", str(pipe)])
        assert "No policy file found" not in res.output

    def test_catalog_dataframes_page_does_not_duplicate_indexed_hub_dataframes(self, tmp_path):
        idx = {
            "stores": ["default"],
            "records": [
                {
                    "kind": "Pipeline",
                    "id": "acme/p",
                    "location": {"kind": "store"},
                    "assets": ["acme/p:rates"],
                    "asset_names": {"acme/p:rates": "Rates"},
                    "snapshots": [{"commit": "a" * 40, "made_at": "2026-01-01T00:00:00Z", "name": "2026-01-01-aaaaaaa"}],
                },
                {
                    "kind": "Dataframe",
                    "id": "acme/p:rates",
                    "pipeline": "acme/p",
                    "ref": {"kind": "dataframe", "name": "rates"},
                    "location": {"kind": "store"},
                    "name": "Rates",
                },
            ],
        }
        sw = SphinxWriter(idx, theme="catalog")
        assert sw.from_the_store_assets(("dataframe",), "cb/dataframes.md", exclude_indexed=True) == []
        # Pipeline page still lists it
        assert len(sw.from_the_store_assets(("dataframe",), "cb/pipelines/acme-p.md", "acme/p")) == 1
        mw = MkDocsWriter(idx, theme="catalog")
        assert mw.from_the_store_assets(("dataframe",), "cb/dataframes.md", exclude_indexed=True) == []


class TestPlottingFixes:
    def test_nber_recessions_tz_aware_numeric_and_string_x(self):
        fake_recessions = pd.DataFrame(
            {"start": [pd.Timestamp("2020-02-01")], "end": [pd.Timestamp("2020-04-01")]}
        )
        with patch("chartbook.plotting._overlays.get_nber_recessions", return_value=fake_recessions):
            df_tz = pd.DataFrame(
                {"date": pd.date_range("2020-01-01", periods=6, freq="ME", tz="UTC"), "y": range(6)}
            )
            res_tz = plotting.line(df_tz, x="date", y="y", nber_recessions=True)
            assert res_tz.mpl_figure is not None

            df_num = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
            res_num = plotting.line(df_num, x="x", y="y", nber_recessions=True)
            assert res_num.mpl_figure is not None

            df_str = pd.DataFrame({"x": ["a", "b", "c"], "y": [4, 5, 6]})
            res_str = plotting.line(df_str, x="x", y="y", nber_recessions=True)
            assert res_str.mpl_figure is not None

    def test_vlines_date_string_in_matplotlib(self):
        df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=6, freq="ME"), "y": range(6)})
        res = plotting.line(df, x="date", y="y", vlines=[{"x": "2020-03-01", "label": "Event"}])
        assert res.mpl_figure is not None

    def test_bar_and_dual_bar_datetime_overlays_keep_positional_xlim(self):
        df = pd.DataFrame(
            {"date": pd.date_range("2020-01-01", periods=6, freq="ME"), "y": range(1, 7), "y2": range(6, 0, -1)}
        )
        regions = [{"x0": pd.Timestamp("2020-02-01"), "x1": pd.Timestamp("2020-04-01")}]
        bar_res = plotting.bar(df, x="date", y="y", shaded_regions=regions)
        lo, hi = bar_res.mpl_axes.get_xlim()
        assert -2 < lo < 1 and 4 < hi < 8

        dual_res = plotting.dual(
            df, x="date", left_y="y", right_y="y2", left_type="bar", right_type="line", shaded_regions=regions
        )
        lo2, hi2 = dual_res.mpl_axes.get_xlim()
        assert -2 < lo2 < 1 and 4 < hi2 < 8

    def test_dual_single_string_colors(self):
        df = pd.DataFrame({"x": [1, 2, 3], "a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
        res = plotting.dual(df, x="x", left_y="a", right_y="b", left_colors="#1f77b4", right_colors="#ff7f0e")
        assert res.figure is not None and res.mpl_figure is not None

    def test_scatter_nan_size_and_color_by(self):
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6], "s": [10.0, np.nan, 30.0], "cat": ["a", np.nan, "b"]})
        res = plotting.scatter(df, x="x", y="y", size="s", color_by="cat")
        total_points = sum(len(trace.x) for trace in res.figure.data)
        assert total_points == 3
        assert res.mpl_figure is not None

        df_na = pd.DataFrame({"x": [1, 2], "y": [3, 4], "s": pd.array([pd.NA, pd.NA], dtype="Float64")})
        res_na = plotting.scatter(df_na, x="x", y="y", size="s")
        assert res_na.figure is not None and res_na.mpl_figure is not None

    def test_stacked_bar_nan_and_nullable_int_in_matplotlib(self):
        df = pd.DataFrame({"x": ["a", "b", "c"], "y1": [10.0, np.nan, 30.0], "y2": [5.0, 15.0, 25.0]})
        res = plotting.bar(df, x="x", y=["y1", "y2"], stacked=True)
        # Second series bar at index 1 should have height 15.0 and y0 0.0 (not NaN)
        bar_b_y2 = res.mpl_axes.containers[1][1]
        assert bar_b_y2.get_height() == 15.0
        assert bar_b_y2.get_y() == 0.0

        df_na = pd.DataFrame(
            {"x": ["a", "b"], "y1": pd.array([10, pd.NA], dtype="Int64"), "y2": pd.array([5, 15], dtype="Int64")}
        )
        assert plotting.bar(df_na, x="x", y=["y1", "y2"], stacked=True).mpl_figure is not None

    def test_pie_nan_in_matplotlib(self):
        df = pd.DataFrame({"cat": ["A", "B", "C"], "val": [10.0, np.nan, 20.0]})
        res = plotting.pie(df, names="cat", values="val")
        assert res.mpl_figure is not None

    def test_configure_default_interactive_false_respected_by_save(self, tmp_path):
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        try:
            plotting.configure(default_interactive=False)
            res = plotting.line(df, x="x", y="y").save("no_html", output_dir=tmp_path)
            assert res.html_path is None
            assert not (tmp_path / "no_html.html").exists()
            assert (tmp_path / "no_html.png").exists()
        finally:
            plotting.configure(default_interactive=True)

    def test_tickformat_applied_in_matplotlib(self):
        df = pd.DataFrame({"x": [1, 2, 3], "a": [10.0, 20.0, 30.0], "b": [0.01, 0.025, 0.05]})
        res = plotting.dual(df, x="x", left_y="a", right_y="b", right_y_tickformat=".1%")
        ax2 = res.mpl_figure.axes[1]
        assert ax2.yaxis.get_major_formatter()(0.025, 0) == "2.5%"

    def test_duplicate_columns_raise_data_validation_error(self):
        df = pd.DataFrame([[1, 2, 3], [4, 5, 6]], columns=["x", "y", "y"])
        with pytest.raises(DataValidationError, match="Duplicate"):
            plotting.line(df, x="x", y="y")
