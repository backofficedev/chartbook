"""Regression tests for the fourteenth pre-release 0.6.0 audit."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from chartbook import build_docs, identity, index as index_mod, manifest as manifest_mod, missing, refs, snapshot, store as store_mod
from chartbook.store import StoreNotAvailableError
from chartbook.stores import s3 as s3_mod


class TestAudit14TrailingNewlinesPathsAndWithdrawnStore:
    def test_validation_regexes_reject_trailing_newline(self):
        with pytest.raises(ValueError):
            identity.validate_pipeline_id("acme/rates\n")
        with pytest.raises(ValueError):
            refs.AssetRef(kind="dataframe", name="rates", rev="v1\n")
        with pytest.raises(ValueError):
            refs.AssetRef(kind="dataframe", name="rates", part="a/b\n")
        with pytest.raises(ValueError):
            refs.AssetRef(kind="dataframe", name="rates", pipeline="p", registry="reg.example\n")
        assert store_mod._HEX.match("a" * 64 + "\n") is None
        assert store_mod._FULL_COMMIT.match("a" * 40 + "\n") is None
        assert store_mod._RECORD_NAME.match("20261013T182205Z.json\n") is None
        assert store_mod._ROOT_NAME.match("a" * 32 + ".json\n") is None
        assert manifest_mod._LOOKS_LIKE_A_VERSION.match("abcd\n") is None
        assert index_mod._LAST_DATE.match("2026-01-01\n") is None
        assert s3_mod._BUCKET.match("my-bucket\n") is None

    def test_sphinx_keep_inside_snippet_uses_is_relative_to(self):
        assert "Path(full).is_relative_to(Path(root))" in build_docs._UNTRUSTED_CONF
        assert "root + os.sep" not in build_docs._UNTRUSTED_CONF

    def test_through_a_link_uses_any_length(self, tmp_path):
        pipelines = tmp_path / "pipelines"
        target = pipelines / "acme+rates" / "snap" / "file.txt"
        target.parent.mkdir(parents=True)
        target.write_text("ok", encoding="utf-8")
        seen = []
        real_islink = os.path.islink

        def spy_islink(p):
            seen.append(str(p))
            return real_islink(str(p).removeprefix("EXT::"))

        with patch.object(store_mod, "_any_length", side_effect=lambda p: f"EXT::{p}"), patch(
            "os.path.islink", side_effect=spy_islink
        ):
            assert store_mod._is_or_under_a_link(target, pipelines) is False
        assert seen and all(p.startswith("EXT::") for p in seen)

    def test_missing_path_dependency_propagates_store_not_available(self, tmp_path):
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        (upstream / "chartbook.toml").write_text('[project]\nname = "Up"\nid = "acme/up"\n', encoding="utf-8")
        downstream = tmp_path / "downstream"
        downstream.mkdir()
        (downstream / "chartbook.toml").write_text(
            '[project]\nname = "Down"\nid = "acme/down"\n\n[dependencies]\n"acme/up" = { path = "../upstream" }\n',
            encoding="utf-8",
        )
        with patch.object(snapshot, "newest_for", side_effect=StoreNotAvailableError("bucket withdrawn")):
            with pytest.raises(StoreNotAvailableError, match="bucket withdrawn"):
                missing.find(downstream, store=None)
