"""Regression tests for the fifth pre-release 0.6.0 audit."""

from __future__ import annotations

import datetime
import gzip
import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import (
    catalog_config,
    check,
    data,
    formats,
    lineage,
    lock,
    manifest,
    multi_store,
    plotting,
    rowhash,
    sharing,
    snapshot,
    store,
)
from chartbook.cli import main as cli
from chartbook.plotting._overlays import _mpl_x_coord
from chartbook.writers.sphinx import SphinxWriter


def _init_git_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


class TestMultiStoreAndCatalogConfig:
    def test_add_root_and_note_matches_accept_generators(self, tmp_path):
        s1 = store.FolderStore(tmp_path / "s1")
        s2 = store.FolderStore(tmp_path / "s2")
        pipe = tmp_path / "pipe_a"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text(
            '[project]\nid = "pipe_a"\ntitle = "Pipe A"\n\n[dataframes.d]\npath = "d.parquet"\n',
            encoding="utf-8",
        )
        pl.DataFrame({"a": [1]}).write_parquet(pipe / "d.parquet")
        commit = _init_git_repo(pipe)
        rep = snapshot.make(pipe, store=s2)
        made_at = rep.snapshot.made_at
        stores = multi_store.Stores([
            multi_store.NamedStore("s1", str(tmp_path / "s1"), s1, create=True),
            multi_store.NamedStore("s2", str(tmp_path / "s2"), s2, create=True),
        ])
        lockfile = tmp_path / "chartbook.lock"
        snap_gen = ((p_, c, m) for p_, c, m in [("pipe_a", commit, made_at)])
        stores.add_root(lockfile, hashes=(h for h in []), snapshots=snap_gen, machine="m1")
        assert s2.root_of(lockfile, "m1") is not None
        assert stores.note_matches(
            lockfile,
            hashes=(h for h in []),
            snapshots=((p_, c, m) for p_, c, m in [("pipe_a", commit, made_at)]),
            machine="m1",
            labelled=(x for x in []),
        )

    def test_edit_store_validates_catalog_even_when_env_override_set(self, tmp_path, monkeypatch):
        cat = tmp_path / "catalog.toml"
        cat.write_text('[project]\ntype = "catalog"\n\n[stores]\n', encoding="utf-8")
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "env_store"))
        with pytest.raises(ValueError, match="Invalid store name"):
            catalog_config.edit_store("bad name!", {"url": str(tmp_path / "s")}, cat)
        # Adding a valid local store must also succeed even if CHARTBOOK_STORE is withdrawn
        monkeypatch.setenv("CHARTBOOK_STORE", "s3://withdrawn-bucket/prefix")
        catalog_config.edit_store("local", {"url": str(tmp_path / "local_store")}, cat)
        assert "local" in cat.read_text(encoding="utf-8")


class TestStoreAndSharing:
    def test_pipeline_folder_neutralizes_windows_reserved_stem_with_dot(self):
        folder = store.pipeline_folder("con.rates")
        assert folder.split(".")[0].lower() not in store._RESERVED_ON_WINDOWS
        assert "~" in folder
        # Plain reserved name without dot keeps existing shape
        plain = store.pipeline_folder("con")
        assert plain.startswith("con~")

    def test_s3_roots_skips_concurrently_deleted_root(self, tmp_path):
        from chartbook.stores.s3 import S3Store

        s3 = object.__new__(S3Store)
        s3._check_layout = lambda: None
        s3._key = lambda *parts: "/".join(parts)
        s3._list = lambda prefix: [{"Key": "roots/gone.json"}]
        s3._read = lambda key: None
        assert s3.roots() == []

    def test_snapshot_fanout_wraps_snapshot_error_in_not_in_every_store(self, tmp_path):
        s1 = store.FolderStore(tmp_path / "s1")
        s2 = store.FolderStore(tmp_path / "s2")
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text(
            '[project]\nid = "p1"\ntitle = "P1"\n\n[dataframes.d]\npath = "d.parquet"\n',
            encoding="utf-8",
        )
        pl.DataFrame({"a": [1]}).write_parquet(pipe / "d.parquet")
        _init_git_repo(pipe)

        stores = multi_store.Stores([
            multi_store.NamedStore("s1", str(tmp_path / "s1"), s1, pipelines=("p1",), create=True),
            multi_store.NamedStore("s2", str(tmp_path / "s2"), s2, pipelines=("p1",), create=True),
        ])
        with patch("chartbook.transfer.copy_snapshot", side_effect=snapshot.SnapshotError("half-synced")):
            with pytest.raises(snapshot.NotInEveryStore, match="half-synced"):
                snapshot.make(pipe, store=stores)


class TestLockLineageCheckManifest:
    def test_relocating_git_dep_fetches_old_url_on_plain_pin(self, tmp_path):
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        (repo_a / "chartbook.toml").write_text('[project]\nid = "dep"\ntitle = "Dep"\n', encoding="utf-8")
        commit_a = _init_git_repo(repo_a)

        repo_b = tmp_path / "repo_b"
        repo_b.mkdir()
        (repo_b / "chartbook.toml").write_text('[project]\nid = "dep"\ntitle = "Dep B"\n', encoding="utf-8")
        _init_git_repo(repo_b)

        was = {"id": "dep", "location": {"kind": "git", "url": str(repo_a), "commit": commit_a}}
        listed = {"id": "dep", "location": {"kind": "git", "url": str(repo_b)}}
        entry = {"git": str(repo_b)}
        report = lock.PinReport(tmp_path / "chartbook.lock")
        seen_urls = []

        class FakeCache:
            def files(self, url, commit):
                seen_urls.append(("files", url, commit))
                return repo_a

        directory, out_listed, failure = lock._fetch(
            "dep", entry, was, listed, False, tmp_path, FakeCache(), report
        )
        assert failure is None
        assert directory == repo_a
        assert out_listed is was
        assert seen_urls == [("files", lock.local_url(str(repo_a), tmp_path), commit_a)]
        assert any(e.status == "relocated" for e in report.events)

    def test_lineage_walker_at_filters_by_pipeline(self):
        commit = "c" * 40
        made_at = "2026-01-01T00:00:00Z"
        snap_a = SimpleNamespace(
            pipeline="pipe_a",
            same_moment=lambda c, m: (c, m) == (commit, made_at),
        )
        snap_b = SimpleNamespace(
            pipeline="pipe_b",
            same_moment=lambda c, m: (c, m) == (commit, made_at),
        )
        walker = object.__new__(lineage._Walker)
        walker.found = [snap_a, snap_b]
        assert walker._at(commit, made_at, "pipe_b") == [snap_b]
        assert walker._at(commit, made_at, "pipe_c") == []
        assert walker._at(commit, made_at) == [snap_a, snap_b]

    def test_check_not_on_this_machine_handles_store_error_on_earlier_record(self, tmp_path):
        class BrokenStore(store.FolderStore):
            def has(self, content_hash, pipeline=None):
                raise store.StoreError("corrupt store.json")

        broken = BrokenStore(tmp_path / "broken")
        locked = lock.Lock(
            root="pipe",
            dependencies=[{"id": "dep", "location": {"kind": "path", "path": "../dep"}}],
            assets={
                "dep:chart/c": {
                    "id": "dep:chart/c",
                    "pipeline": "dep",
                    "kind": "chart",
                    "content_hash": "sha256:" + "0" * 64,
                }
            },
        )
        with (
            patch("chartbook.lock.read_lock", return_value=locked),
            patch("chartbook.multi_store.with_dependencies", return_value=broken),
        ):
            msg, ok = check._not_on_this_machine(
                tmp_path,
                "dep",
                {"path": "../dep"},
                tmp_path / "missing_dep",
            )
        assert not ok
        assert "store cannot be read" in msg

    def test_manifest_validate_uses_catalog_toml_name(self, tmp_path):
        (tmp_path / "catalog.toml").write_text(
            '[project]\ntype = "bogus"\n', encoding="utf-8"
        )
        with pytest.raises(ValueError, match="catalog.toml"):
            manifest.validate_manifest_file(tmp_path)


class TestRowhashFormatsAndData:
    def test_text_bytes_handles_truncated_gzip_cleanly(self, tmp_path):
        gz_path = tmp_path / "trunc.jsonl.gz"
        raw = gzip.compress(b'{"a": 1}\n' * 100)
        gz_path.write_bytes(raw[:-10])
        # Should fall back to file size instead of raising EOFError
        size = rowhash._text_bytes(gz_path, most=10_000_000)
        assert size == gz_path.stat().st_size

    def test_duckdb_type_maps_decimal_and_uint128(self):
        assert formats._duckdb_type(pl.Decimal(10, 2)) == "DECIMAL(10, 2)"
        if hasattr(pl, "UInt128"):
            assert formats._duckdb_type(pl.UInt128) == "UHUGEINT"

    def test_data_load_validates_format_before_backend_scan(self, tmp_path):
        from chartbook.resolve import TableLocation

        loc = TableLocation(
            source="wh",
            backend="duckdb",
            url=str(tmp_path / "nonexistent.duckdb"),
            identifier="t",
        )
        with (
            patch("chartbook.data.resolve", return_value=loc),
            patch("chartbook.backends.backend_for") as mock_backend,
        ):
            with pytest.raises(ValueError, match="format"):
                data.load("wh_table", format="parquet")
            mock_backend.assert_not_called()


class TestPlottingWritersAndCli:
    def test_mpl_x_coord_positional_handles_nat_and_python_date(self):
        s_nat = pd.Series([pd.Timestamp("2020-01-01"), pd.NaT, pd.Timestamp("2020-03-01")])
        pos = _mpl_x_coord("2020-04-01", s_nat, use_positional_x=True)
        assert np.isfinite(pos)
        assert pos == pytest.approx(2.0)

        s_date = pd.Series([datetime.date(2020, 1, 1), datetime.date(2020, 3, 1)], dtype=object)
        pos_mid = _mpl_x_coord("2020-02-01", s_date, use_positional_x=True)
        assert isinstance(pos_mid, float)
        assert 0.0 < pos_mid < 1.0

    def test_matplotlib_legend_includes_labeled_overlays_and_trend(self):
        df = pd.DataFrame({
            "x": pd.date_range("2020-01-01", periods=5, freq="D"),
            "y": [10.0, 20.0, 15.0, 25.0, 30.0],
        })
        res = plotting.line(
            df, x="x", y="y", regression_line=True, hlines=[{"y": 20, "label": "Target"}]
        )
        leg = res.mpl_axes.get_legend()
        assert leg is not None
        labels = [t.get_text() for t in leg.get_texts()]
        assert "Target" in labels
        assert "Trend" in labels

    def test_matplotlib_pie_handles_all_nan_and_zero_sum(self):
        df_zero = pd.DataFrame({"name": ["A", "B"], "val": [0, 0]})
        res = plotting.pie(df_zero, names="name", values="val")
        assert res.mpl_figure is not None

        df_str = pd.DataFrame({"name": ["A", "B"], "val": ["10", "20"]})
        res2 = plotting.pie(df_str, names="name", values="val")
        assert res2.mpl_figure is not None

    def test_sphinx_trained_on_handles_missing_pin_commit(self):
        writer = object.__new__(SphinxWriter)
        writer.records = {
            "pipe": {
                "dependencies": [{"id": "dep", "location": {}, "snapshot": "2026-01-01T00:00:00Z"}]
            },
            "dep:dataframe/d": {"name": "D"},
        }
        writer._version_page = lambda from_path, asset_id, commit, made_at: "v.html" if commit and made_at else ""
        rec = {
            "pipeline": "pipe",
            "inputs": ["dep:dataframe/d"],
            "pinned_inputs": {"dep:dataframe/d": "sha256:abc"},
            "trained_from": {"dep:dataframe/d": {"commit": "a" * 40, "made_at": "2025-12-01T00:00:00Z"}},
        }
        entries = writer._trained_on(rec, Path("models/m.md"))
        assert len(entries) == 1
        assert "as trained" in entries[0]["note"]
        assert "moved to" not in entries[0]["note"]

    def test_cli_docs_build_rejects_file_output_dir(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "chartbook.toml").write_text('[project]\nid = "p"\ntitle = "P"\n', encoding="utf-8")
        out_file = tmp_path / "not_a_dir.txt"
        out_file.write_text("hi", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, ["docs", "build", str(out_file), "--project-dir", str(proj)])
        assert result.exit_code != 0
        assert "not a directory" in result.output.lower()
