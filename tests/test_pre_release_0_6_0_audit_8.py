"""Regression tests for the eighth pre-release 0.6.0 audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import jsonschema
import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from chartbook import (
    config,
    hubs,
    index,
    lineage,
    manifest as manifest_mod,
    multi_store,
    publish,
    refs,
    resolve,
    sitefiles,
    snapshot,
    transfer,
)
from chartbook.cli import main as cli
from chartbook.gitcache import GitCache
from chartbook.plotting import area, bar, dual, line, pie
from chartbook.plotting._overlays import _as_naive_utc, _x_range, filter_recessions_for_range
from chartbook.store import FolderStore, StoreError, StoreNotAvailableError


class TestSchemasAndIndex:
    def test_series_schema_accepts_docs_content_hash(self):
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "chartbook"
            / "schemas"
            / "chartbook"
            / "v1"
            / "Series.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        record = {
            "kind": "Series",
            "version": "chartbook/v1",
            "id": "demo:df#col",
            "ref": {"pipeline": "demo", "kind": "dataframe", "name": "df", "part": "col"},
            "dataframe": "demo:df",
            "column": "col",
            "declared": True,
            "docs": {"text": "Inline docs", "content_hash": "sha256:" + "a" * 64},
        }
        jsonschema.Draft202012Validator(schema).validate(record)

    def test_hubs_dependency_records_include_required_via_field(self):
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "chartbook"
            / "schemas"
            / "chartbook"
            / "v1"
            / "Pipeline.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        deps = hubs.dependency_records(
            [{"id": "acme/upstream", "location": {"commit": "a" * 40}}]
        )
        assert deps == [
            {
                "id": "acme/upstream",
                "via": "store",
                "location": {"kind": "store", "commit": "a" * 40},
            }
        ]
        record = {
            "kind": "Pipeline",
            "version": "chartbook/v1",
            "id": "acme/downstream",
            "name": "Downstream",
            "location": {"kind": "store"},
            "assets": [],
            "dependencies": deps,
        }
        jsonschema.Draft202012Validator(schema).validate(record)

    def test_names_one_file_under_parent_with_glob_brackets(self, tmp_path):
        parent = tmp_path / "Research [2026]" / "pipe"
        parent.mkdir(parents=True)
        report = parent / "report.pdf"
        report.write_bytes(b"%PDF-1.4\n")
        assert index._names_one_file(str(report)) is True


class TestUntrustedSymlinkConfinement:
    def test_refuse_paths_outside_checks_default_readme_and_series_docs(self, tmp_path, monkeypatch):
        outside = tmp_path / "secret.txt"
        outside.write_text("top-secret", encoding="utf-8")

        proj = tmp_path / "pipe"
        proj.mkdir()
        (proj / "README.md").symlink_to(outside)
        (proj / "chartbook.toml").write_text('[project]\nid = "p"\ntitle = "P"\n', encoding="utf-8")

        monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
        with pytest.raises(ValueError, match="not a plain path inside the pipeline's folder"):
            manifest_mod.load_manifest(proj)

        # Remove README symlink and test nested series.*.docs_path
        (proj / "README.md").unlink()
        (proj / "chartbook.toml").write_text(
            '[project]\nid = "p"\ntitle = "P"\n'
            '[dataframes.d]\npath = "./data.parquet"\n'
            '[dataframes.d.series.s]\ndocs_path = "../secret.txt"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not a plain path inside the pipeline's folder"):
            manifest_mod.load_manifest(proj)

    def test_copy_site_pages_skips_escaping_symlink_when_untrusted(self, tmp_path, monkeypatch):
        outside = tmp_path / "secret.md"
        outside.write_text("LEAKED", encoding="utf-8")

        site_dir = tmp_path / "pipe" / "docs_src" / "site"
        site_dir.mkdir(parents=True)
        (site_dir / "safe.md").write_text("# Safe\n", encoding="utf-8")
        (site_dir / "leak.md").symlink_to(outside)

        dest = tmp_path / "build"
        dest.mkdir()
        idx = {
            "records": [
                {
                    "kind": "Pipeline",
                    "site_dir": {"resolved_path": str(site_dir)},
                }
            ]
        }
        monkeypatch.setenv("CHARTBOOK_UNTRUSTED_SOURCE", "1")
        sitefiles.copy_site_pages(idx, dest)
        assert (dest / "safe.md").is_file()
        assert not (dest / "leak.md").exists()


class TestStorageTransferAndMultiStore:
    def test_stores_incomplete_returns_none_when_absent_and_blocks_tidy_pipeline(self, tmp_path):
        s1 = FolderStore(tmp_path / "s1")
        s2 = FolderStore(tmp_path / "s2")
        stores = multi_store.Stores(
            [
                multi_store.NamedStore(name="s1", store=s1, url=str(s1.root)),
                multi_store.NamedStore(name="s2", store=s2, url=str(s2.root)),
            ]
        )
        missing_hash = "sha256:" + "0" * 64
        assert stores.incomplete(missing_hash, 10) is None
        with pytest.raises(ValueError, match="Select one store for destructive maintenance"):
            stores.tidy_pipeline("acme/demo")

    def test_transfer_readable_snapshots_skips_corrupt_records(self, tmp_path):
        s = FolderStore(tmp_path / "store")
        bad_record = s.root / "snapshots" / "broken" / "2026-01-01T00-00-00Z" / "_chartbook" / "snapshot.json"
        bad_record.parent.mkdir(parents=True, exist_ok=True)
        bad_record.write_text("{not valid json", encoding="utf-8")
        assert transfer._readable_snapshots(s) == []

    def test_copy_regular_file_cleans_up_partial_target_on_write_error(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"hello world")
        dst = tmp_path / "dst.bin"

        real_open = open

        class FailingWriter:
            def __init__(self, path):
                self._f = real_open(path, "xb")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._f.close()

            def write(self, data):
                self._f.write(data[:2])
                raise OSError("disk full")

        with patch("builtins.open", side_effect=lambda p, m="r", *a, **k: FailingWriter(p) if m == "xb" else real_open(p, m, *a, **k)):
            ok = snapshot._copy_regular_file(src, dst)
        assert ok is False
        assert not dst.exists()

    def test_copy_kept_returns_false_on_missing_source(self, tmp_path):
        kept = MagicMock()
        missing = MagicMock()
        missing.relative = "part.parquet"
        missing.location = tmp_path / "does_not_exist.parquet"
        kept.files = [missing]
        assert snapshot._copy_kept(kept, tmp_path / "out") is False

    def test_gitcache_fetch_recovers_from_corrupt_bare_dir_without_head(self, tmp_path):
        # Create a small local git repo to fetch from
        import subprocess

        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-q", str(origin)], check=True)
        subprocess.run(["git", "-C", str(origin), "config", "user.email", "t@e.com"], check=True)
        subprocess.run(["git", "-C", str(origin), "config", "user.name", "Test"], check=True)
        (origin / "f.txt").write_text("hi", encoding="utf-8")
        subprocess.run(["git", "-C", str(origin), "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", str(origin), "commit", "-q", "-m", "init"], check=True)

        cache = GitCache(tmp_path / "cache")
        repo_path = cache.repo_path(str(origin))
        # Pre-create a corrupt bare directory with leftover files and no HEAD
        (repo_path / "objects").mkdir(parents=True)
        (repo_path / "config").write_text("[core]\nbare = true\n", encoding="utf-8")

        fetched = cache.fetch(str(origin))
        assert fetched == repo_path
        assert (repo_path / "HEAD").is_file()


class TestLineageResolveConfigAndCLI:
    def test_lineage_walker_merges_labels_on_second_visit(self):
        walker = lineage._Walker(MagicMock(), [], [])
        taken = MagicMock()
        taken.pipeline = "acme/d"
        taken.commit = "a" * 40
        taken.made_at = "2026-01-01T00:00:00Z"
        taken.built_with = {}
        taken.tags = []
        taken.content.return_value = {"df": "sha256:" + "1" * 64}
        taken.path = Path("/store/snapshots/acme__d/snap/_chartbook/snapshot.json")
        taken.inputs = []

        with patch.object(walker, "_declared", return_value=(set(), "")):
            first = walker._up(lineage.Node(label="acme/d"), taken, depth=1)
            second = walker._up(
                lineage.Node(label="acme/d"),
                taken,
                depth=1,
                labels=frozenset({"sha256:" + "2" * 64}),
            )
        assert second.seen is True
        assert "sha256:" + "2" * 64 in first.hashes

    def test_links_do_not_bypass_undeclared_dependency_check(self, tmp_path):
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        (upstream / "chartbook.toml").write_text(
            '[project]\nid = "acme/up"\ntitle = "Up"\n[dataframes.d]\npath = "./d.parquet"\n',
            encoding="utf-8",
        )
        downstream = tmp_path / "downstream"
        downstream.mkdir()
        (downstream / "chartbook.toml").write_text(
            '[project]\nid = "acme/down"\ntitle = "Down"\n',
            encoding="utf-8",
        )
        (downstream / "chartbook.links.toml").write_text(
            '"acme/up" = "../upstream"\n', encoding="utf-8"
        )
        with pytest.raises(resolve.DependencyNotDeclaredError):
            resolve.resolve("acme/up:d", start_dirs=[downstream])

    def test_resolve_local_rejects_non_dict_asset_entry(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text(
            '[project]\nid = "p"\ntitle = "P"\n[dataframes]\nfoo = "bar"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must be a table"):
            resolve.resolve("foo", start_dirs=[tmp_path])

    def test_newest_snapshot_of_propagates_store_not_available(self):
        def _boom():
            raise StoreNotAvailableError("withdrawn bucket")

        with patch("chartbook.store.default_store", side_effect=_boom):
            with pytest.raises(StoreNotAvailableError, match="withdrawn bucket"):
                resolve._newest_snapshot_of(refs.parse_asset_ref("acme/rates:df"))

    def test_refs_reject_dot_and_dotdot_components(self):
        for bad in (".", "..", ".:df", "..:df", "../..:..", "acme/..:df", "acme/p:."):
            with pytest.raises(ValueError):
                refs.parse_asset_ref(bad)

    def test_set_default_catalog_path_rejects_legacy_chartbook_toml_catalog(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "get_global_config_dir", lambda: tmp_path / "cfg")
        old_cat = tmp_path / "old" / "chartbook.toml"
        old_cat.parent.mkdir()
        old_cat.write_text('[project]\ntype = "catalog"\ntitle = "Old"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="old catalog"):
            config.set_default_catalog_path(old_cat)

        bad_cat = tmp_path / "bad" / "catalog.toml"
        bad_cat.parent.mkdir()
        bad_cat.write_text('project = "not-a-table"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="must be a table"):
            config.set_default_catalog_path(bad_cat)

    def test_publish_handles_directory_and_glob_dataframes(self, tmp_path):
        proj = tmp_path / "pipe"
        (proj / "_data" / "part").mkdir(parents=True)
        (proj / "_data" / "part" / "a.parquet").write_bytes(b"PAR1")
        (proj / "_data" / "g1.parquet").write_bytes(b"PAR1")
        (proj / "_data" / "g2.parquet").write_bytes(b"PAR1")
        (proj / "README.md").write_text("# Pipe\n", encoding="utf-8")
        (proj / "chartbook.toml").write_text(
            '[project]\nid = "p"\ntitle = "P"\n'
            '[dataframes.dir_df]\npath = "./_data/part"\ndocs = "Dir"\n'
            '[dataframes.glob_df]\npath = "./_data/g*.parquet"\ndocs = "Glob"\n',
            encoding="utf-8",
        )
        loaded = manifest_mod.load_manifest(proj)
        plan = publish.get_pipeline_publishing_plan(loaded, tmp_path / "out")
        planned_names = {p.name for p in plan}
        assert {"a.parquet", "g1.parquet", "g2.parquet"}.issubset(planned_names)

    def test_cli_store_export_invalid_pipeline_id_exits_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "store"))
        runner = CliRunner()
        res = runner.invoke(cli, ["store", "export", "bad id", "--to", str(tmp_path / "out")])
        assert res.exit_code == 1
        assert "Error:" in res.output


class TestPlottingFixes:
    def test_unordered_categorical_x_skips_nber_recessions(self):
        df = pd.DataFrame(
            {"cat": pd.Categorical(["A", "B", "C"], ordered=False), "v": [1, 2, 3]}
        )
        fake_rec = pd.DataFrame(
            {"start": [pd.Timestamp("2020-02-01")], "end": [pd.Timestamp("2020-04-01")]}
        )
        with patch("chartbook.plotting._overlays.get_nber_recessions", return_value=fake_rec):
            res = line(df, x="cat", y="v", nber_recessions=True)
            assert len(res.figure.layout.shapes) == 0
            fig = res.mpl_figure
            assert len(fig.axes[0].patches) == 0
            res.close()

    def test_iso_date_string_x_filters_recessions(self):
        recessions = pd.DataFrame(
            {
                "start": [pd.Timestamp("1929-08-01"), pd.Timestamp("2020-02-01")],
                "end": [pd.Timestamp("1933-03-01"), pd.Timestamp("2020-04-01")],
            }
        )
        s = pd.Series(["2020-01-01", "2020-06-01"])
        assert _as_naive_utc("2020-01-01") == pd.Timestamp("2020-01-01")
        filtered = filter_recessions_for_range(recessions, *_x_range(s))
        assert len(filtered) == 1
        assert filtered.iloc[0]["start"] == pd.Timestamp("2020-02-01")

    def test_pie_negative_and_inf_do_not_crash_matplotlib(self):
        df = pd.DataFrame({"cat": ["A", "B", "C"], "val": [-10.0, 50.0, np.inf]})
        res = pie(df, names="cat", values="val")
        assert res.mpl_figure is not None
        res.close()

    def test_x_range_with_iso_date_strings_works_in_matplotlib(self):
        df = pd.DataFrame(
            {"date": pd.date_range("2020-01-01", periods=6, freq="ME"), "v": [1, 2, 3, 4, 5, 6]}
        )
        res = line(df, x="date", y="v", x_range=("2020-01-15", "2020-04-15"))
        assert res.mpl_figure is not None
        res.close()

    def test_dual_bar_nullable_int64_with_na_and_both_bars_no_overlap(self):
        df = pd.DataFrame(
            {
                "x": ["Q1", "Q2", "Q3"],
                "a": pd.array([1, pd.NA, 3], dtype="Int64"),
                "b": [2, 3, 4],
            }
        )
        res = dual(df, x="x", left_y="a", right_y="b", left_type="bar", right_type="bar")
        assert res.figure.layout.barmode == "group"
        assert res.figure.data[0].offsetgroup != res.figure.data[1].offsetgroup

        fig = res.mpl_figure
        ax1, ax2 = fig.axes[0], fig.axes[1]
        left_xs = [p.get_x() for p in ax1.patches]
        right_xs = [p.get_x() for p in ax2.patches]
        assert left_xs != right_xs
        res.close()

    def test_stacked_bar_negative_values_stack_downward_in_matplotlib(self):
        df = pd.DataFrame({"cat": ["A", "B"], "pos": [10, 5], "neg": [-4, -3]})
        res = bar(df, x="cat", y=["pos", "neg"], stacked=True)
        ax = res.mpl_axes
        # First 2 patches are "pos" (y=0..10, 0..5); next 2 are "neg" (y=0..-4, 0..-3)
        neg_patches = ax.patches[2:]
        assert [p.get_y() for p in neg_patches] == [0.0, 0.0]
        assert [p.get_height() for p in neg_patches] == [-4.0, -3.0]
        res.close()

    def test_regression_line_ignores_inf_in_both_backends(self):
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [1.0, np.inf, 3.0, 4.0]})
        res = line(df, x="x", y="y", regression_line=True)
        trend_trace = [t for t in res.figure.data if t.name == "Trend"][0]
        assert all(np.isfinite(v) for v in trend_trace.y)
        trend_line = [ln for ln in res.mpl_axes.get_lines() if ln.get_label() == "Trend"][0]
        assert np.all(np.isfinite(trend_line.get_ydata()))
        res.close()

    def test_plotly_area_applies_alpha_to_hex_colors(self):
        df = pd.DataFrame({"x": [1, 2, 3], "a": [1, 2, 3], "b": [2, 3, 4]})
        res = area(df, x="x", y=["a", "b"], stacked=False)
        for trace in res.figure.data:
            assert trace.fillcolor.startswith("rgba(")
            assert trace.fillcolor.endswith(", 0.5)")

    def test_unexpected_kwargs_raise_type_error(self):
        df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
        with pytest.raises(TypeError, match="Unexpected keyword argument"):
            line(df, x="x", y="y", y_titel="GDP")
