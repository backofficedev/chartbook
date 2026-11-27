"""Regression tests for the sixteenth pre-release 0.6.0 audit."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from click.testing import CliRunner

from chartbook import build_docs, cli, formats, incremental, provenance
from chartbook.manifest import apply_code_change_times, load_manifest
from chartbook.resolve import FileLocation


class TestAudit16FormatsCategoricalHiveKey:
    @pytest.mark.parametrize("dtype", [pl.Categorical, pl.Enum(["us", "eu"])])
    def test_arrow_dataset_handles_dictionary_hive_key(self, tmp_path, dtype):
        root = tmp_path / "data"
        for region, v in [("us", 1), ("eu", 2)]:
            part = root / f"region={region}" / "part.ipc"
            part.parent.mkdir(parents=True)
            pl.DataFrame({"region": pl.Series([region], dtype=dtype), "v": [v]}).write_ipc(part)
        ds = formats.arrow_dataset(FileLocation(path=root, format="ipc"))
        table = ds.to_table()
        assert sorted(zip(table.column("region").to_pylist(), table.column("v").to_pylist())) == [
            ("eu", 2),
            ("us", 1),
        ]


class TestAudit16CliDocsBuildErrors:
    def test_docs_build_rejects_file_as_docs_build_dir(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text('[project]\nname = "Demo"\nid = "demo"\n', encoding="utf-8")
        (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
        not_a_dir = tmp_path / "file.txt"
        not_a_dir.write_text("x", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(
            cli.main,
            [
                "docs",
                "build",
                "--project-dir",
                str(tmp_path),
                "--docs-build-dir",
                str(not_a_dir),
                "--force-write",
            ],
        )
        assert res.exit_code != 0
        assert "not a directory" in res.output

    def test_docs_build_handles_oserror_cleanly(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text('[project]\nname = "Demo"\nid = "demo"\n', encoding="utf-8")
        (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
        runner = CliRunner()
        with patch("chartbook.build_docs.generate_docs", side_effect=PermissionError("no access")):
            res = runner.invoke(
                cli.main,
                ["docs", "build", "--project-dir", str(tmp_path), "--force-write"],
            )
            assert res.exit_code == 1
            assert "Error:" in res.output


class TestAudit16IncrementalStateAndModelVersions:
    def test_corrupt_state_falls_back_to_fresh_build_and_ignores_bad_code_times(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text('[project]\nname = "Demo"\nid = "demo"\n', encoding="utf-8")
        (tmp_path / "README.md").write_text("# Demo\n\nHello.\n", encoding="utf-8")
        manifest = load_manifest(tmp_path)
        theme_dir = build_docs.get_docs_src_path("pipeline")
        opts = {"size_threshold": 50, "strip_mathjax2": True}
        gfp = incremental.global_fingerprint(manifest, theme_dir, opts)
        pid = manifest["project"]["id"]
        fp = incremental.pipeline_fingerprint(pid, manifest)
        bdir = tmp_path / "_docs"
        bdir.mkdir()

        # Non-dict pipelines -> fresh build instead of AttributeError
        (bdir / incremental.STATE_FILE).write_text(
            json.dumps({"version": incremental.STATE_VERSION, "global": gfp, "pipelines": None, "code_times": {}}),
            encoding="utf-8",
        )
        assert incremental.read_state(bdir) is None
        assert incremental.plan_build(manifest, bdir, theme_dir, opts).fresh is True

        # Non-dict code_times -> fresh build instead of TypeError
        (bdir / incremental.STATE_FILE).write_text(
            json.dumps({"version": incremental.STATE_VERSION, "global": gfp, "pipelines": {pid: fp}, "code_times": 123}),
            encoding="utf-8",
        )
        assert incremental.read_state(bdir) is None
        assert incremental.plan_build(manifest, bdir, theme_dir, opts).fresh is True

        # Malformed code_times string -> ignored so apply_code_change_times never crashes
        (bdir / incremental.STATE_FILE).write_text(
            json.dumps({
                "version": incremental.STATE_VERSION,
                "global": gfp,
                "pipelines": {pid: fp},
                "code_times": {pid: "not-a-timestamp"},
                "rendered": True,
            }),
            encoding="utf-8",
        )
        plan = incremental.plan_build(manifest, bdir, theme_dir, opts)
        assert pid not in plan.code_times
        apply_code_change_times(manifest, known=plan.code_times)

    def test_provenance_digest_changes_when_non_current_model_versions_change(self):
        def make_records(versions):
            return {
                "p": {"kind": "Pipeline", "id": "p", "location": {"kind": "path", "value": "/tmp/p"}},
                "p:model/m": {
                    "kind": "Model",
                    "id": "p:model/m",
                    "pipeline": "p",
                    "ref": {"kind": "model", "name": "m"},
                    "content_hash": "sha256:bbbbbbbbbbbb",
                    "versions": versions,
                },
            }

        v_old = {
            "version": "aaaaaaaaaaaa",
            "content_hash": "sha256:aaaaaaaaaaaa",
            "made_at": "2026-01-01T00:00:00Z",
            "commit": "1" * 40,
        }
        v_cur = {
            "version": "bbbbbbbbbbbb",
            "content_hash": "sha256:bbbbbbbbbbbb",
            "made_at": "2026-01-02T00:00:00Z",
            "commit": "2" * 40,
        }
        assert provenance.digest("p", make_records([v_old, v_cur])) != provenance.digest("p", make_records([v_cur]))
