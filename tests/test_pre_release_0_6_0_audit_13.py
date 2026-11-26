"""Regression tests for the thirteenth pre-release 0.6.0 audit."""

from __future__ import annotations

import errno
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import duckdb
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl
import pytest
from click.testing import CliRunner

import chartbook.plotting as cbp
from chartbook import (
    cli,
    files,
    formats,
    hashing,
    hubs,
    identity,
    index as index_mod,
    lineage,
    lock,
    manifest as manifest_mod,
    missing,
    sharing,
    sitefiles,
    snapshot,
    store as store_mod,
)
from chartbook.plotting._overlays import _x_range, _x_values_to_numeric
from chartbook.resolve import FileLocation
from chartbook.store import FolderStore, StoreUnreachableError
from chartbook.writers.mkdocs import MkDocsWriter
from chartbook.writers.sphinx import NO_GLIMPSE_RECORDED, SphinxWriter


class TestPlottingAndUtilsAudit13:
    def test_x_range_handles_nulls_and_uncomparable_object_series(self):
        assert _x_range(pd.Series(["A", None, "B"])) == ("A", "B")
        assert _x_range(pd.Series([None, float("nan")])) == (None, None)
        assert _x_range(pd.Series([1, "two", None], dtype=object)) == (None, None)

        df = pd.DataFrame({"x": ["A", None, "B"], "y": [1, 2, 3]})
        with patch("chartbook.plotting._overlays.get_nber_recessions") as mock_rec:
            mock_rec.return_value = pd.DataFrame(
                {"start": [pd.Timestamp("2020-02-01")], "end": [pd.Timestamp("2020-04-01")]}
            )
            res = cbp.bar(df, x="x", y="y", nber_recessions=True)
            _ = res.mpl_figure
            plt.close("all")

    def test_dual_axis_right_bar_rotates_visible_ax1_xticklabels(self):
        df = pd.DataFrame({"cat": ["Jan", "Feb", "Mar"], "a": [1, 2, 3], "b": [10, 20, 30]})
        res = cbp.dual(df, x="cat", left_y="a", right_y="b", left_type="line", right_type="bar")
        try:
            res.mpl_figure.canvas.draw()
            assert [t.get_rotation() for t in res.mpl_axes.get_xticklabels()] == [45.0, 45.0, 45.0]
            assert [t.get_ha() for t in res.mpl_axes.get_xticklabels()] == ["right", "right", "right"]
        finally:
            plt.close("all")

    def test_matplotlib_build_closes_figure_on_exception(self):
        plt.close("all")
        df = pd.DataFrame({"x": [1, 2], "y": [10, 20]})
        with patch(
            "chartbook.plotting.backends._matplotlib.MatplotlibBackend._apply_config",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                _ = cbp.area(df, x="x", y="y", stacked=True).mpl_figure
        assert len(plt.get_fignums()) == 0

    def test_x_values_to_numeric_preserves_mixed_timezones(self):
        s_dt = pd.Series([
            datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=2))),
            datetime(2020, 1, 2, tzinfo=timezone(timedelta(hours=3))),
            datetime(2020, 1, 3, tzinfo=timezone(timedelta(hours=2))),
        ])
        out = _x_values_to_numeric(s_dt)
        assert not pd.isna(out).any()
        assert out[1] - out[0] == pytest.approx(23 * 3600.0)
        assert out[2] - out[1] == pytest.approx(25 * 3600.0)

        s_str = pd.Series([
            "2020-01-01T00:00:00+02:00",
            "2020-01-02T00:00:00+03:00",
            "2020-01-03T00:00:00+02:00",
        ])
        out_str = _x_values_to_numeric(s_str)
        assert out_str == pytest.approx(out)

    def test_files_bounded_exact_preview_bytes_gzip_is_whole(self, tmp_path):
        p = tmp_path / "exact.txt.gz"
        content = (b"a" * 408 + b"\n") * 10 + b"LAST!!"
        assert len(content) == files.PREVIEW_BYTES
        with gzip.open(p, "wb") as f:
            f.write(content)
        raw, whole = files._bounded(p)
        assert raw == content
        assert whole is True

        p_over = tmp_path / "over.txt.gz"
        with gzip.open(p_over, "wb") as f:
            f.write(content + b"X")
        raw_over, whole_over = files._bounded(p_over)
        assert len(raw_over) == files.PREVIEW_BYTES
        assert whole_over is False

    def test_hubs_enrich_handles_null_inputs_and_pinned_inputs(self):
        taken = SimpleNamespace(
            pipeline="acme/p1",
            commit="a" * 40,
            first_commit="b" * 40,
            made_at="2026-01-01T00:00:00Z",
            path="/tmp/fake",
            repository="https://example.com/acme/p1",
        )
        stores = SimpleNamespace(entries=[], name_of=lambda p: "local")
        stored = [
            {
                "kind": "Chart",
                "id": "acme/p1:chart/c1",
                "name": "C1",
                "inputs": None,
                "pinned_inputs": None,
            }
        ]
        records = [{"kind": "Pipeline", "id": "acme/p1", "dependencies": []}]
        with patch("chartbook.snapshot.readable_snapshots", return_value=([taken], [])), patch(
            "chartbook.snapshot._stored_records", return_value=stored
        ):
            hubs.enrich(records, stores)
        charts = [r for r in records if r["kind"] == "Chart"]
        assert len(charts) == 1
        assert charts[0]["inputs"] == []
        assert charts[0]["pinned_inputs"] == {}


class TestStoreAndSharingAudit13:
    def test_sharing_copy_snapshots_refuses_conflicting_existing_moment(self, tmp_path):
        src_store = FolderStore(tmp_path / "src_store")
        dst_store = FolderStore(tmp_path / "dst_store")
        commit = "a" * 40
        made_at = "2026-10-16T01:02:03.000000Z"

        f1 = tmp_path / "p1"
        (f1 / "_data").mkdir(parents=True)
        (f1 / "_data" / "x.txt").write_bytes(b"version-one")
        p1 = src_store.begin("acme/rates", commit, made_at, base=f1)
        put1 = p1.put(f1 / "_data" / "x.txt")
        p1.write({
            "schema": "chartbook/snapshot/v2",
            "root": "acme/rates",
            "code": {"commit": commit},
            "made_at": made_at,
            "records": [{"id": "acme/rates:x", "content_hash": put1.content_hash, "size_bytes": put1.size_bytes, "stored": put1.stored}],
        })

        f2 = tmp_path / "p2"
        (f2 / "_data").mkdir(parents=True)
        (f2 / "_data" / "x.txt").write_bytes(b"version-two-different")
        p2 = dst_store.begin("acme/rates", commit, made_at, base=f2)
        put2 = p2.put(f2 / "_data" / "x.txt")
        p2.write({
            "schema": "chartbook/snapshot/v2",
            "root": "acme/rates",
            "code": {"commit": commit},
            "made_at": made_at,
            "records": [{"id": "acme/rates:x", "content_hash": put2.content_hash, "size_bytes": put2.size_bytes, "stored": put2.stored}],
        })

        done = sharing.copy_snapshots(src_store.records(), dst_store)
        assert done.there == []
        assert done.copied == []
        assert len(done.refused) == 1
        assert "different snapshot" in done.refused[0][1]

    def test_what_is_wrong_in_passes_any_length_to_islink(self, tmp_path):
        store = FolderStore(tmp_path / "store")
        commit = "b" * 40
        made_at = "2026-10-16T01:02:03.000000Z"
        f = tmp_path / "proj"
        (f / "_data").mkdir(parents=True)
        (f / "_data" / "x.txt").write_bytes(b"hello")
        pending = store.begin("acme/rates", commit, made_at, base=f)
        put = pending.put(f / "_data" / "x.txt")
        pending.write({
            "schema": "chartbook/snapshot/v2",
            "root": "acme/rates",
            "code": {"commit": commit},
            "made_at": made_at,
            "records": [{"id": "acme/rates:x", "content_hash": put.content_hash, "size_bytes": put.size_bytes, "stored": put.stored}],
        })
        (rec,) = store.records()
        seen_paths = []
        real_islink = os.path.islink

        def spy_islink(p):
            seen_paths.append(p)
            return real_islink(p)

        with patch.object(store_mod, "_any_length", side_effect=lambda p: f"EXTENDED::{p}"), patch(
            "os.path.islink", side_effect=spy_islink
        ), patch.object(store_mod.hashing.HashCache, "file_hex", return_value=put.content_hash.split(":", 1)[1]):
            store_mod.what_is_wrong_in(rec.assets[0])
        assert seen_paths and all(str(p).startswith("EXTENDED::") for p in seen_paths)


class TestLockLineageIdentityCliAudit13:
    def test_lineage_cycle_loads_per_dependency_stores_when_following_pins(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "chartbook.toml").write_text(
            '[project]\nname = "A"\nid = "acme/a"\n\n[dependencies]\n"acme/b" = { store = "s3://bucket/dep_store" }\n',
            encoding="utf-8",
        )
        sentinel = object()
        with patch("chartbook.multi_store.with_dependencies", return_value=sentinel) as mock_wd, patch.object(
            lineage, "_Finder"
        ) as mock_finder:
            mock_finder.return_value.children.return_value = []
            assert lineage.cycle(proj, pipeline="acme/a", follow_pins=True) is None
            mock_wd.assert_called_once_with(proj.resolve(), None)
            assert mock_finder.call_args[0][0] is sentinel

        with patch("chartbook.multi_store.with_dependencies") as mock_wd2, patch.object(
            lineage, "_Finder"
        ) as mock_finder2:
            mock_finder2.return_value.children.return_value = []
            assert lineage.cycle(proj, pipeline="acme/a", follow_pins=False) is None
            mock_wd2.assert_not_called()

    def test_lock_put_note_writes_healthy_store_when_other_store_root_of_fails(self, tmp_path):
        healthy = FolderStore(tmp_path / "healthy")
        broken = MagicMock()
        broken.root_of.side_effect = StoreUnreachableError("offline")
        lock_path = tmp_path / "proj" / "chartbook.lock"
        pins = lock.NotePins(hashes={"sha256:" + "1" * 64}, snapshots=set(), labelled=set(), complete=True)
        with patch.object(lock, "_writable_stores", return_value=[broken, healthy]), patch.object(
            lock, "_note_targets", return_value=[broken, healthy]
        ):
            with pytest.raises(StoreUnreachableError, match="offline"):
                lock._put_note(healthy, lock_path, pins, machine="test-box", if_changed=False)
        assert healthy.root_of(lock_path, machine="test-box") is not None

    def test_identity_split_rev_rejects_trailing_at(self):
        assert identity.split_rev("acme/rates@") == ("acme/rates@", None)
        with pytest.raises(ValueError):
            identity.normalize_ref_to_id("acme/rates@")
        with pytest.raises(ValueError):
            identity.match_pipeline_ref(["acme/rates"], "acme/rates@")

    def test_lock_from_document_rejects_non_dict_dependency_location(self):
        doc = {
            "schema": lock.SCHEMA,
            "root": "acme/a",
            "records": [
                {
                    "kind": "Pipeline",
                    "id": "acme/a",
                    "dependencies": [{"id": "acme/b", "location": None}],
                }
            ],
        }
        with pytest.raises(lock.LockError, match="location that is not an object"):
            lock._lock_from_document(doc, Path("chartbook.lock"))

    def test_echo_pin_report_warns_instead_of_crashing_on_bad_links_toml(self, tmp_path):
        (tmp_path / "chartbook.links.toml").write_text("bad = [123\n", encoding="utf-8")
        report = lock.PinReport(lockfile=tmp_path / "chartbook.lock")
        runner = CliRunner()
        with runner.isolated_filesystem():
            import click

            @click.command()
            def cmd():
                cli._echo_pin_report(report)

            result = runner.invoke(cmd)
        assert result.exit_code == 0
        assert "warning:" in result.output


class TestWritersAndSitefilesAudit13:
    def test_mkdocs_config_nav_does_not_html_entity_escape_store_names(self):
        idx = {
            "schema": "chartbook/index/v1",
            "records": [
                {
                    "kind": "Catalog",
                    "id": "cat",
                    "name": "Cat",
                    "location": {"kind": "local", "value": "."},
                },
                {
                    "kind": "Pipeline",
                    "id": "acme/p",
                    "name": "Yield-Curve (US)",
                    "location": {"kind": "store", "value": "s3://bucket"},
                    "assets": ["acme/p:df1"],
                },
                {
                    "kind": "Dataframe",
                    "id": "acme/p:df1",
                    "pipeline": "acme/p",
                    "ref": {"kind": "dataframe", "name": "df1"},
                    "name": "US Treasury (10Y) - Spread",
                    "location": {"kind": "store", "path": "_data/df1.parquet"},
                },
            ],
        }
        cfg = MkDocsWriter(idx, theme="catalog").config("Cat")
        nav_text = json.dumps(cfg["nav"])
        assert "&#" not in nav_text
        assert "Yield-Curve (US)" in nav_text
        assert "US Treasury (10Y) - Spread (acme/p)" in nav_text

    def test_sphinx_dataframe_page_does_not_misclassify_glob_without_glimpse(self, tmp_path):
        data_dir = tmp_path / "_data"
        data_dir.mkdir()
        (data_dir / "part_1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        idx = {
            "schema": "chartbook/index/v1",
            "records": [
                {
                    "kind": "Pipeline",
                    "id": "acme/p",
                    "name": "P",
                    "location": {"kind": "local", "value": str(tmp_path)},
                    "assets": ["acme/p:parts"],
                },
                {
                    "kind": "Dataframe",
                    "id": "acme/p:parts",
                    "pipeline": "acme/p",
                    "ref": {"kind": "dataframe", "name": "parts"},
                    "name": "Parts",
                    "content_hash": "sha256:" + "a" * 64,
                    "location": {
                        "kind": "local",
                        "path": "_data/part_*.csv",
                        "resolved_path": str(data_dir / "part_*.csv"),
                    },
                },
            ],
        }
        writer = SphinxWriter(idx, theme="pipeline", docs_src_dir=tmp_path)
        page = writer.dataframe_page("acme/p:parts")
        assert NO_GLIMPSE_RECORDED not in page

    def test_site_pages_under_build_and_templates_excluded_from_index_and_writers(self, tmp_path):
        site_dir = tmp_path / "docs_src" / "site"
        (site_dir / "_build").mkdir(parents=True)
        (site_dir / "_templates").mkdir(parents=True)
        (site_dir / "guide.md").write_text("# Guide\n", encoding="utf-8")
        (site_dir / "_build" / "draft.md").write_text("# Draft\n", encoding="utf-8")
        (site_dir / "_templates" / "tpl.md").write_text("# Tpl\n", encoding="utf-8")

        _, pages = index_mod._site_pages({"_resolved_site_dir": str(site_dir)}, tmp_path)
        assert pages == ["guide.md"]

        # Even if an index already lists them, writers filter them out
        idx = {
            "schema": "chartbook/index/v1",
            "records": [
                {
                    "kind": "Pipeline",
                    "id": "acme/p",
                    "name": "P",
                    "location": {"kind": "local", "value": str(tmp_path)},
                    "assets": [],
                    "site_dir": {"path": "docs_src/site", "resolved_path": str(site_dir)},
                    "site_pages": ["guide.md", "_build/draft.md", "_templates/tpl.md"],
                }
            ],
        }
        mk = MkDocsWriter(idx, theme="pipeline", docs_src_dir=tmp_path)
        assert [p["link"] for p in mk._site_pages(idx["records"][0])] == ["guide.md"]

    def test_write_site_forwards_size_threshold_to_build_index(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text('[project]\nname = "P"\nid = "acme/p"\n', encoding="utf-8")
        (tmp_path / "README.md").write_text("# P\n", encoding="utf-8")
        captured = {}

        def fake_build_index(manifest, cache=None, skip_pipelines=(), size_threshold=50, **kw):
            captured["size_threshold"] = size_threshold
            return {
                "schema": "chartbook/index/v1",
                "records": [
                    {
                        "kind": "Pipeline",
                        "id": "acme/p",
                        "name": "P",
                        "location": {"kind": "local", "value": str(tmp_path)},
                        "assets": [],
                    }
                ],
            }

        with patch.object(index_mod, "build_index", side_effect=fake_build_index):
            sitefiles.write_site(tmp_path / "_build", tmp_path, size_threshold=1.25)
        assert captured["size_threshold"] == 1.25


class TestHashingFormatsAndRegexAudit13:
    def test_hashing_escapes_allows_children_of_filesystem_root(self, tmp_path):
        root = Path(tmp_path.anchor)
        assert hashing.escapes(tmp_path, root) is None

    def test_formats_kept_apart_ignores_hidden_and_underscore_duplicates(self, tmp_path):
        hash_file = tmp_path / "abcdef.parquet"
        pl.DataFrame({"val": [1, 2]}).write_parquet(hash_file)
        loc = FileLocation(
            tmp_path / "tbl",
            files=(hash_file,),
            listed=("year=2024/part.parquet", "_backup/part.parquet", ".staging/part.parquet"),
            inside={
                "year=2024/part.parquet": hash_file,
                "_backup/part.parquet": hash_file,
                ".staging/part.parquet": hash_file,
            },
        )
        pl_df = formats.scan_location(loc).collect()
        assert pl_df.height == 2
        assert "year" in pl_df.columns
        assert pl_df["year"].to_list() == [2024, 2024]

        ddb_df = duckdb.sql(f"select * from {formats.sql(loc)}").pl()
        assert ddb_df.height == 2
        assert "year" in ddb_df.columns

    def test_formats_key_values_falls_back_to_string_on_invalid_filename_chars(self, tmp_path):
        kind, mapping = formats._key_values("tag", ["a*", "b"], tmp_path / "s1")
        assert kind == pl.String
        assert mapping == {"a*": "a*", "b": "b"}

        # Simulate Windows invalid-filename OSError from _written
        win_err = OSError(errno.EINVAL, "Invalid argument")
        with patch.object(formats, "_written", side_effect=formats._not_written(win_err)):
            # Need __cause__ set as _written does
            def fail_written(*a, **kw):
                try:
                    raise win_err
                except OSError as e:
                    raise formats._not_written(e) from e

            with patch.object(formats, "_written", side_effect=fail_written):
                kind2, mapping2 = formats._key_values("tag", ["ok", "also_ok"], tmp_path / "s2")
        assert kind2 == pl.String
        assert mapping2 == {"ok": "ok", "also_ok": "also_ok"}

    def test_label_version_and_commit_patterns_reject_trailing_newline(self):
        assert snapshot.labels_of({"models": {"m": {"aliases": {"champion\n": "abcdef123456"}}}}) == {}
        assert snapshot.labels_of({"models": {"m": {"aliases": {"champion": "abcdef123456\n"}}}}) == {}
        assert manifest_mod.VERSION_PATTERN.match("abcdef123456\n") is None
        assert missing._COMMIT.match("abcdef1\n") is None
        assert missing._FULL_COMMIT.match("a" * 40 + "\n") is None
