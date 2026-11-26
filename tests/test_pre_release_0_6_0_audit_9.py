"""Regression tests for the ninth pre-release 0.6.0 audit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from chartbook import env, files, manifest as manifest_mod, provenance, publish, snapshot
from chartbook.cli import main as cli


class TestSnapshotAndPublishAudit9:
    def test_copy_regular_file_preserves_preexisting_target_on_file_exists(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"new bytes")
        dst = tmp_path / "dst.bin"
        dst.write_bytes(b"existing bytes")

        ok = snapshot._copy_regular_file(src, dst)
        assert ok is False
        assert dst.is_file()
        assert dst.read_bytes() == b"existing bytes"

    def test_publish_external_directory_and_glob_avoid_collisions_and_wildcards(self, tmp_path):
        shared = tmp_path / "shared"
        (shared / "part").mkdir(parents=True)
        (shared / "part" / "a.parquet").write_bytes(b"PAR1")
        (shared / "part" / "b.parquet").write_bytes(b"PAR1")
        (shared / "g1.parquet").write_bytes(b"PAR1")
        (shared / "g2.parquet").write_bytes(b"PAR1")

        proj = tmp_path / "pipe"
        proj.mkdir()
        (proj / "README.md").write_text("# Pipe\n", encoding="utf-8")
        (proj / "chartbook.toml").write_text(
            '[project]\nid = "p"\ntitle = "P"\n'
            '[dataframes.ext_dir]\npath = "../shared/part"\ndocs = "Ext dir"\n'
            '[dataframes.ext_glob]\npath = "../shared/g*.parquet"\ndocs = "Ext glob"\n',
            encoding="utf-8",
        )
        loaded = manifest_mod.load_manifest(proj)
        plan = publish.get_pipeline_publishing_plan(loaded, tmp_path / "out")

        dests = list(plan.values())
        # Every external file gets a unique destination with no literal wildcard characters
        assert len(dests) == len(set(dests))
        assert not any("*" in str(d) for d in dests)
        dest_names = {d.name for d in dests}
        assert {"a.parquet", "b.parquet", "g1.parquet", "g2.parquet"}.issubset(dest_names)


class TestProvenanceFilesAndEnvAudit9:
    def test_provenance_panel_matches_local_and_aliased_trained_with_and_stale(self):
        h1 = "sha256:" + "1" * 64
        h2 = "sha256:" + "2" * 64
        records = {
            "acme/forecast": {
                "kind": "Pipeline",
                "id": "acme/forecast",
                "dependencies": [
                    {
                        "id": "acme/rates",
                        "key": "rates",
                        "via": "store",
                        "location": {"kind": "store", "commit": "a" * 40},
                    }
                ],
            },
            "acme/forecast:d": {
                "kind": "Dataframe",
                "id": "acme/forecast:d",
                "pipeline": "acme/forecast",
                "content_hash": h1,
            },
            "acme/rates:treasury": {
                "kind": "Dataframe",
                "id": "acme/rates:treasury",
                "pipeline": "acme/rates",
                "content_hash": "sha256:" + "9" * 64,
            },
            "acme/forecast:model/m": {
                "kind": "Model",
                "id": "acme/forecast:model/m",
                "pipeline": "acme/forecast",
                "inputs": ["acme/forecast:d", "acme/rates:treasury"],
                "trained_with": {"d": h1, "rates:treasury": h2},
                "stale_inputs": ["rates:treasury"],
            },
        }
        panel = provenance.panel("acme/forecast:model/m", records)
        assert panel is not None
        by_id = {entry["id"]: entry for entry in panel["inputs"]}
        assert by_id["acme/forecast:d"]["trained_with"] == h1
        assert by_id["acme/forecast:d"]["stale"] is False
        assert by_id["acme/rates:treasury"]["trained_with"] == h2
        assert by_id["acme/rates:treasury"]["stale"] is True
        assert "moved since this was trained" in by_id["acme/rates:treasury"]["words"]

    def test_files_inside_rejects_nested_windows_drive_components(self):
        assert files._inside("sub/file.txt") is True
        assert files._inside("C:evil.txt") is False
        assert files._inside("sub/D:secret.txt") is False
        assert files._inside("a/b/c:foo") is False

    def test_env_get_dir_cast_and_default_handling(self, monkeypatch):
        monkeypatch.setenv("REDIRECT_LIMIT", "42")
        assert env.get("REDIRECT_LIMIT", cast=int) == 42

        monkeypatch.setenv("CUSTOM_DATA_DIR", "rel_sub")
        as_str = env.get("CUSTOM_DATA_DIR", cast=str)
        assert isinstance(as_str, str)
        assert Path(as_str).is_absolute()

        monkeypatch.delenv("UNSET_CUSTOM_DIR", raising=False)
        from_default = env.get("UNSET_CUSTOM_DIR", default="rel_default")
        assert isinstance(from_default, Path)
        assert from_default.is_absolute()

        assert env.get("UNSET_CUSTOM_DIR", default=None) is None


class TestCLIEdgeCasesAudit9:
    def test_path_command_handles_corrupt_lockfile_cleanly(self, tmp_path):
        proj = tmp_path / "pipe"
        proj.mkdir()
        (proj / "chartbook.toml").write_text(
            '[project]\nid = "p"\ntitle = "P"\n[dependencies]\n"acme/up" = { store = true }\n',
            encoding="utf-8",
        )
        (proj / "chartbook.lock").write_text("{corrupt lock json", encoding="utf-8")
        runner = CliRunner()
        res = runner.invoke(cli, ["path", "acme/up:df", "--project-dir", str(proj)])
        assert res.exit_code == 1
        assert "Error:" in res.output

    def test_publish_handles_malformed_trust_file_cleanly(self, tmp_path, monkeypatch):
        proj = tmp_path / "pipe"
        proj.mkdir()
        (proj / "chartbook.toml").write_text('[project]\nid = "p"\ntitle = "P"\n', encoding="utf-8")
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        (cfg_dir / "trust.toml").write_text("not = [valid toml", encoding="utf-8")
        monkeypatch.delenv("CHARTBOOK_TRUST", raising=False)
        monkeypatch.setattr("chartbook.config.get_global_config_dir", lambda: cfg_dir)

        runner = CliRunner()
        res = runner.invoke(cli, ["publish", "--project-dir", str(proj)])
        assert res.exit_code == 1
        assert "Error:" in res.output

    def test_ls_json_does_not_prompt_when_can_ask_is_true(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "cfg"
        monkeypatch.setattr("chartbook.config.get_global_config_dir", lambda: cfg_dir)
        monkeypatch.setenv("CHARTBOOK_STORE", str(tmp_path / "store"))

        runner = CliRunner()
        with patch("chartbook.cli._can_ask", return_value=True), patch(
            "chartbook.cli._confirm", side_effect=AssertionError("should not prompt under --json")
        ):
            res = runner.invoke(cli, ["ls", "stores", "--json"])
        assert res.exit_code == 0
