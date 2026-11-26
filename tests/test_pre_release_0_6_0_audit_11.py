"""Regression tests for the eleventh pre-release 0.6.0 audit."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from click.testing import CliRunner

from chartbook import cli, config, index, plotting, rowhash, snapshot, store as store_mod
from chartbook.plotting._exceptions import DataValidationError
from chartbook.store import FolderStore, KeptFile, StoreNotAvailableError


class TestCliAndConfigAudit11:
    def test_catalog_or_make_one_not_required_does_not_exit_on_permission_or_value_error(self, monkeypatch):
        monkeypatch.setattr(cli, "_default_catalog_path", lambda: None)
        with (
            patch.object(config, "get_store_url", return_value="/tmp/store"),
            patch.object(config, "shown_store_url", return_value="/tmp/store"),
            patch.object(config, "make_default_catalog", side_effect=PermissionError("read-only home")),
            patch.object(cli, "_can_ask", return_value=False),
        ):
            assert cli._catalog_or_make_one(required=False, to_show_a_snapshot=True) is None

        with (
            patch.object(config, "get_store_url", return_value="/tmp/store"),
            patch.object(config, "shown_store_url", return_value="/tmp/store"),
            patch.object(config, "make_default_catalog", side_effect=ValueError("bad catalog")),
            patch.object(cli, "_can_ask", return_value=False),
        ):
            assert cli._catalog_or_make_one(required=False, to_show_a_snapshot=True) is None

    def test_install_claude_skill_catches_oserror_during_inspection(self, tmp_path):
        runner = CliRunner()
        skill_dir = tmp_path / ".claude" / "skills" / "chartbook"
        skill_dir.mkdir(parents=True)

        real_iterdir = Path.iterdir

        def fail_on_skill_dir(self):
            if self == skill_dir:
                raise PermissionError("permission denied")
            return real_iterdir(self)

        with (
            patch("chartbook.claude_skill.user_dir", return_value=skill_dir),
            patch.object(Path, "iterdir", fail_on_skill_dir),
        ):
            result = runner.invoke(cli.main, ["install", "claude-skill"])
        assert result.exit_code == 1
        assert "the skill could not be installed:" in result.output

    def test_is_folder_recognizes_windows_backslash_relative_hosts(self):
        assert config._is_folder(r".\repos") is True
        assert config._is_folder(r"..\repos") is True
        assert config._is_folder("./repos") is True
        assert config._is_folder("../repos") is True
        assert config._is_folder("github.com") is False
        cloned = config.clone_url_for("acme/rates", host=r"..\repos")
        assert cloned is not None
        assert not cloned.startswith("https://")
        assert "acme" in cloned and "rates" in cloned


class TestStoreNotAvailableAudit11:
    def test_index_add_snapshots_propagates_store_not_available(self):
        records = [{"id": "pipeline:acme/p", "kind": "Pipeline", "name": "acme/p"}]
        with patch.object(snapshot, "readable_snapshots", side_effect=StoreNotAvailableError("bucket gone")):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                index._add_snapshots(records, store=object())

    def test_check_store_takes_one_propagates_store_not_available(self):
        with patch("chartbook.multi_store.Stores.configured", side_effect=StoreNotAvailableError("bucket gone")):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                snapshot.check_store_takes_one("acme/p", store=None)


class TestPlottingAudit11:
    def test_non_string_scalar_columns_in_line_bar_area_and_dual(self):
        df = pd.DataFrame({0: [1, 2, 3], 1: [4, 5, 6], 2: [7, 8, 9]})
        for fn in (plotting.line, plotting.bar, plotting.area):
            res = fn(df, x=0, y=1)
            assert res.figure is not None
            assert res.mpl_figure is not None
        dual_res = plotting.dual(df, x=0, left_y=1, right_y=2)
        assert dual_res.figure is not None
        assert dual_res.mpl_figure is not None

    def test_scatter_respects_falsy_column_names_size_0_and_color_by_0(self):
        df = pd.DataFrame({0: ["a", "b", "a"], 1: [1, 2, 3], 2: [4, 5, 6]})
        res_color = plotting.scatter(df, x=1, y=2, color_by=0)
        assert len(res_color.figure.data) == 2
        assert res_color.mpl_figure is not None

        df_size = pd.DataFrame({0: [10.0, 20.0, 30.0], 1: [1, 2, 3], 2: [4, 5, 6]})
        res_size = plotting.scatter(df_size, x=1, y=2, size=0)
        assert res_size.figure.data[0].marker.size is not None
        assert res_size.mpl_figure is not None

        # Missing column 0 must raise DataValidationError, not silently skip validation
        df_no_zero = pd.DataFrame({1: [1, 2], 2: [3, 4]})
        with pytest.raises(DataValidationError):
            plotting.scatter(df_no_zero, x=1, y=2, size=0)
        with pytest.raises(DataValidationError):
            plotting.scatter(df_no_zero, x=1, y=2, color_by=0)


class TestStoreLongPathAndRowhashFdAudit11:
    def test_store_age_of_and_is_whole_pass_any_length(self, tmp_path):
        store = FolderStore(tmp_path / "store")
        src = tmp_path / "data.txt"
        src.write_bytes(b"hello")
        digest = store.put(src).content_hash

        seen_age = []
        real_any_length = store_mod._any_length

        def spy_any_length(p):
            seen_age.append(p)
            return real_any_length(p)

        with patch.object(store_mod, "_any_length", side_effect=spy_any_length):
            age = store.age_of(digest)
        assert age >= 0
        assert seen_age

        # Also verify _is_whole uses _any_length for os.path.islink as well as os.stat
        seen_islink = []
        real_islink = os.path.islink

        def spy_islink(p):
            seen_islink.append(p)
            return real_islink(p)

        kf = KeptFile(path="data.txt", relative="data.txt", size_bytes=5, content_hash=digest, location=src)
        with (
            patch.object(store_mod, "_any_length", side_effect=lambda p: f"LONG::{p}") as mock_al,
            patch("os.path.islink", side_effect=spy_islink),
            patch("os.stat", return_value=src.stat()),
        ):
            assert store_mod._is_whole(kf, tmp_path) is True
            assert mock_al.called
            assert seen_islink and str(seen_islink[0]).startswith("LONG::")

    def test_parquet_batches_closes_parquet_file_on_exception(self, tmp_path):
        pq_path = tmp_path / "sample.parquet"
        pq.write_table(pa.table({"a": [1, 2, 3]}), pq_path)

        closed = []
        real_pf = pq.ParquetFile

        class TrackingParquetFile(real_pf):
            def close(self):
                closed.append(True)
                return super().close()

        target = pa.schema([("a", pa.int64())])
        with (
            patch.object(pq, "ParquetFile", TrackingParquetFile),
            patch.object(rowhash, "_read_plan", side_effect=rowhash.NotHashed("boom")),
        ):
            with pytest.raises(rowhash.NotHashed, match="boom"):
                list(rowhash._parquet_batches(pq_path, target, None))
        assert closed == [True]
