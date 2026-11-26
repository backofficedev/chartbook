"""Regression tests for the twelfth pre-release 0.6.0 audit."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import tomli

from chartbook import cli, config, manifest as manifest_mod, scaffold
from chartbook.store import StoreNotAvailableError


class TestPass3InvariantsAndTemplateAudit12:
    def test_cli_newest_stored_propagates_store_not_available(self):
        manifest = {"store_pipelines": ["acme/rates"], "stores": None}
        with patch("chartbook.store.default_store", side_effect=StoreNotAvailableError("bucket gone")):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                cli._newest_stored(manifest)

    def test_untrusted_catalog_refuses_project_paths_outside_folder(self, tmp_path):
        cat = tmp_path / "cat"
        cat.mkdir()
        (cat / "catalog.toml").write_text(
            '[project]\nname = "Bad"\nlogo = "../secret.png"\n',
            encoding="utf-8",
        )
        with patch.object(config, "untrusted_source", return_value=True):
            with pytest.raises(ValueError, match="not a plain path inside the pipeline's folder"):
                manifest_mod.load_manifest(cat)

    def test_template_escapes_quotes_in_toml_and_uses_move_y_on_windows(self, tmp_path):
        from cookiecutter.main import cookiecutter

        out = Path(
            cookiecutter(
                str(scaffold.find_template()),
                no_input=True,
                output_dir=str(tmp_path),
                extra_context={
                    "project_name": 'Rates "2026" \\ Lab',
                    "project_slug": "rates_lab",
                    "project_description": 'A "quoted" \\ description',
                    "author_name": 'Jane "J" Doe',
                    "author_email": "jane@example.com",
                    "include_fred": "y",
                    "include_ofr_api": "y",
                    "include_jupyter_notebooks": "y",
                    "environment_manager": "uv",
                },
            )
        )
        cb = tomli.loads((out / "chartbook.toml").read_text(encoding="utf-8"))
        assert cb["project"]["name"] == 'Rates "2026" \\ Lab'
        assert cb["project"]["description"] == 'A "quoted" \\ description'
        assert cb["project"]["maintainer"] == 'Jane "J" Doe'

        pp = tomli.loads((out / "pyproject.toml").read_text(encoding="utf-8"))
        assert pp["project"]["description"] == 'A "quoted" \\ description'
        assert pp["project"]["authors"][0]["name"] == 'Jane "J" Doe'

        dodo = (out / "dodo.py").read_text(encoding="utf-8")
        assert 'move /Y "{from_path}" "{to_path}"' in dodo
        assert 'DATA_DIR / "fred.parquet"' in dodo
        assert 'DATA_DIR / "ofr_public_repo_data.parquet"' in dodo
