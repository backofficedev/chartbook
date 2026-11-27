"""Regression tests for the fifteenth pre-release 0.6.0 audit."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from click.testing import CliRunner

import chartbook
from chartbook import (
    check,
    cli,
    formats,
    hubs,
    incremental,
    plotting,
    publish,
    sitefiles,
    store as store_mod,
)
from chartbook.resolve import FileLocation
from chartbook.writers import mkdocs as mkdocs_writer, sphinx as sphinx_writer


class TestAudit15StoreSweep:
    def test_sweep_keeps_noted_empty_snapshot_folder(self, tmp_path):
        store = store_mod.FolderStore(tmp_path / "store")
        pipeline_dir = store.root / "pipelines" / "acme+rates"
        snap_dir = pipeline_dir / "2026-11-26-abcdef0"
        snap_dir.mkdir(parents=True)
        pending_dir = store.root / store_mod.OWN_DIR / "tmp"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "writer.pending").write_text(
            f"folder {snap_dir.relative_to(store.root).as_posix()}\n",
            encoding="utf-8",
        )
        # Even with older_than=0, an actively-noted empty snapshot folder must not be deleted
        store.sweep(pipeline_dir, older_than=0)
        assert snap_dir.is_dir()

    def test_sweep_respects_pending_folder_window_for_unrecorded_empty_folder(self, tmp_path):
        store = store_mod.FolderStore(tmp_path / "store")
        pipeline_dir = store.root / "pipelines" / "acme+rates"
        snap_dir = pipeline_dir / "2026-11-26-abcdef0"
        snap_dir.mkdir(parents=True)
        # Backdate to 2 hours ago: older than PENDING_SECONDS (1h), newer than PENDING_FOLDER_SECONDS (24h)
        two_hours_ago = snap_dir.stat().st_mtime - 7200
        os.utime(snap_dir, (two_hours_ago, two_hours_ago))
        store.sweep(pipeline_dir, older_than=store_mod.PENDING_SECONDS)
        assert snap_dir.is_dir()


class TestAudit15FormatsInt128HiveKey:
    def test_arrow_dataset_handles_int128_hive_key(self, tmp_path):
        base = tmp_path / "ipc_folder"
        part = base / "id=99999999999999999999"
        part.mkdir(parents=True)
        pl.DataFrame({"v": [1, 2]}).write_ipc(part / "a.ipc")
        loc = FileLocation(path=base, format="ipc")
        ds = formats.arrow_dataset(loc)
        table = ds.to_table()
        assert table.num_rows == 2
        assert table.column("id").to_pylist() == ["99999999999999999999", "99999999999999999999"]

    def test_arrow_kept_apart_handles_int128_hive_key(self, tmp_path):
        base = tmp_path / "ipc_kept"
        part = base / "id=99999999999999999999"
        part.mkdir(parents=True)
        file_path = part / "a.ipc"
        pl.DataFrame({"v": [10]}).write_ipc(file_path)
        loc = FileLocation(path=base, format="ipc")
        ds = formats._arrow_kept_apart(loc, [(file_path, "id=99999999999999999999/a.ipc")])
        table = ds.to_table()
        assert table.num_rows == 1
        assert table.column("id").to_pylist() == ["99999999999999999999"]


class TestAudit15WritersAndSitefiles:
    def test_format_metric_escapes_strings(self):
        assert sphinx_writer._format_metric(True) == "true"
        assert sphinx_writer._format_metric(42) == "42"
        assert sphinx_writer._format_metric(0.2123456) == "0.212346"
        escaped = sphinx_writer._format_metric("train | test\n<script>alert(1)</script>")
        assert "\n" not in escaped
        assert "|" not in escaped
        assert "<script>" not in escaped

    def test_model_page_tail_escapes_metric_names(self):
        assert "{{name | literal}}" in sphinx_writer._MODEL_PAGE_TAIL
        assert "`{{name}}`" not in sphinx_writer._MODEL_PAGE_TAIL

    def test_sitefiles_reserved_checks_are_case_insensitive(self, tmp_path):
        assert not sitefiles._a_site_page(Path("_Templates/page.html"))
        assert not sitefiles._a_site_page(Path("_BUILD/out.html"))
        assert not sitefiles._a_site_page(Path("Conf.py"))
        assert not sitefiles._a_site_page(Path("MKDOCS.YML"))

        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "Index.md").write_text("# hijack", encoding="utf-8")
        (site_dir / "INDEX_TOC.MD").write_text("about", encoding="utf-8")
        (site_dir / "about.md").write_text("# About", encoding="utf-8")
        docs_build = tmp_path / "build"
        docs_build.mkdir()
        (docs_build / "index.md").write_text("# Original", encoding="utf-8")
        index = {"records": [{"kind": "Pipeline", "site_dir": {"resolved_path": str(site_dir)}}]}
        with pytest.warns(UserWarning, match="index.md"):
            sitefiles.copy_site_pages(index, docs_build)
        assert (docs_build / "index.md").read_text(encoding="utf-8") == "# Original"
        assert (docs_build / "about.md").is_file()
        assert not (docs_build / "INDEX_TOC.MD").exists()

    def test_mkdocs_nav_skips_uppercase_index_pages(self):
        writer = mkdocs_writer.MkDocsWriter(index={"records": []})
        pipeline = {
            "id": "p",
            "site_pages": ["Index.md", "INDEX_TOC.MD", "_Templates/x.md", "about.md"],
        }
        pages = writer._site_pages(pipeline)
        assert [p["link"] for p in pages] == ["about.md"]


class TestAudit15IncrementalDuckDB:
    def test_pipeline_input_files_uses_resolved_url(self, tmp_path):
        real_db = tmp_path / "real.duckdb"
        real_db.write_bytes(b"")
        manifest = {
            "pipeline_base_dir": tmp_path,
            "project": {"type": "pipeline", "id": "acme/p"},
            "sources": {
                "local": {
                    "backend": "duckdb",
                    "url": "duckdb:///:memory:",
                    "_resolved_url": f"duckdb:///{real_db.as_posix()}",
                }
            },
        }
        files = incremental.pipeline_input_files(manifest)
        assert real_db.resolve() in {p.resolve() for p in files}


class TestAudit15CliPublishCheckAndHubs:
    def test_publish_rejects_catalog(self, tmp_path):
        (tmp_path / "catalog.toml").write_text(
            '[project]\nname = "Cat"\nid = "cat"\ntype = "catalog"\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="pipeline, not a catalog"):
            publish.publish_pipeline(tmp_path / "out", base_dir=tmp_path)
        runner = CliRunner()
        res = runner.invoke(cli.main, ["publish", "--project-dir", str(tmp_path)])
        assert res.exit_code == 1
        assert "not a catalog" in res.output

    def test_is_catalog_folder_catches_permission_error(self, tmp_path):
        with patch("chartbook.manifest._read_manifest_file", side_effect=PermissionError("denied")):
            assert cli._is_catalog_folder(tmp_path) is False

    def test_cli_docs_and_check_handle_permission_error(self, tmp_path):
        runner = CliRunner()
        with patch("chartbook.assets.get_docs_page", side_effect=PermissionError("no read")):
            res = runner.invoke(cli.main, ["get-docs", "p:df", "--catalog", str(tmp_path / "c.toml")])
            assert res.exit_code == 1
            assert "Error:" in res.output
            res2 = runner.invoke(
                cli.main,
                ["data", "get-docs", "--pipeline", "p", "--dataframe", "df", "--catalog", str(tmp_path / "c.toml")],
            )
            assert res2.exit_code == 1
            assert "Error:" in res2.output
        with patch("chartbook.data.get_docs_path", side_effect=PermissionError("no read")):
            res3 = runner.invoke(
                cli.main,
                ["data", "get-docs-path", "--pipeline", "p", "--dataframe", "df", "--catalog", str(tmp_path / "c.toml")],
            )
            assert res3.exit_code == 1
            assert "Error:" in res3.output
        with patch("chartbook.manifest.load_manifest", side_effect=PermissionError("no read")):
            res4 = runner.invoke(cli.main, ["run", "--check", "--project-dir", str(tmp_path)])
            assert res4.exit_code == 1
            assert "Error:" in res4.output

    def test_check_links_reports_broken_symlink(self, tmp_path):
        manifest = {"project": {"type": "pipeline", "id": "acme/p"}}
        link = tmp_path / "chartbook.links.toml"
        try:
            link.symlink_to(tmp_path / "does_not_exist.toml")
        except OSError:
            pytest.skip("symlinks unavailable")
        problems = check.check_links(manifest, tmp_path)
        assert len(problems) == 1
        assert "broken symlink" in problems[0].message

    def test_hubs_dependency_records_tolerates_non_dict_pin_location_and_non_str_id(self):
        deps = [{"id": "acme/up", "snapshot": "2026-11-26-abcdef0"}]
        pins = [
            {"id": ["unhashable"], "location": "bad"},
            {"id": "acme/up", "location": "not-a-dict"},
        ]
        records = hubs.dependency_records(deps, pins=pins)
        assert len(records) == 1
        assert records[0]["id"] == "acme/up"


class TestAudit15DocsAndDocstrings:
    def test_module_docstrings_do_not_use_removed_chart_id_kwarg(self):
        assert "chart_id=" not in (chartbook.__doc__ or "").split(".save(")[0]
        for line in (plotting.__doc__ or "").splitlines():
            if "chartbook.plotting." in line and ".save(" not in line:
                assert "chart_id=" not in line

    def test_agents_guide_does_not_claim_nonexistent_ls_subcommands(self):
        agents_doc = Path(__file__).resolve().parent.parent / "docs_src" / "guide" / "agents.md"
        text = agents_doc.read_text(encoding="utf-8")
        assert "(or `charts`, `models`, `notebooks`, `files`)" not in text
