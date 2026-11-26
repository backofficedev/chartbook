"""Regression tests for the tenth pre-release 0.6.0 audit."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from chartbook import (
    check,
    config,
    env,
    formats,
    incremental,
    index,
    lineage,
    links,
    lock,
    manifest as manifest_mod,
    missing,
    models,
    multi_store,
    plotting,
    rowhash,
    run,
    snapshot,
    store as store_mod,
)
from chartbook.backends import DuckDBBackend, _ends_in, subselect
from chartbook.plotting._exceptions import DataValidationError
from chartbook.refs import AssetRef
from chartbook.resolve import FileLocation, TableLocation
from chartbook.store import FolderStore, StoreNotAvailableError
from chartbook.writers import sphinx as sphinx_mod
from chartbook.writers.sphinx import SphinxWriter, check_front_matter, yaml_escape


class TestStoreAndMultiStoreAudit10:
    def test_platform_url_dict_preserves_scheme_urls(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CHARTBOOK_STORE", raising=False)
        store_dir = tmp_path / "real_store"
        store_dir.mkdir()
        uri = store_dir.as_uri()
        catalog = tmp_path / "catalog.toml"
        catalog.write_text(
            f'[stores.main]\nurl = {{ unix = "{uri}", windows = "{uri}" }}\n',
            encoding="utf-8",
        )
        opened = multi_store.Stores.configured(catalog)
        assert len(opened.entries) == 1
        assert isinstance(opened.entries[0].store, FolderStore)
        assert opened.entries[0].store.root.resolve() == store_dir.resolve()

    def test_unsynced_part_rejects_non_plain_single_file_path_without_probing_outside(self, tmp_path):
        obj_dir = tmp_path / "obj"
        obj_dir.mkdir()
        (obj_dir / "data.bin").write_bytes(b"12345")
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"12345")

        result = store_mod.unsynced_part(
            obj_dir,
            size_bytes=5,
            files={"../outside.bin": 5},
            every=False,
        )
        assert result is not None
        reason, retryable = result
        assert "not a plain path" in reason
        assert retryable is False

        # Also when outside target does not exist (must not fall back to files = None)
        result_missing = store_mod.unsynced_part(
            obj_dir,
            size_bytes=5,
            files={"../does_not_exist.bin": 5},
            every=False,
        )
        assert result_missing is not None
        assert "not a plain path" in result_missing[0]
        assert result_missing[1] is False


class TestStoreNotAvailablePropagationAudit10:
    def test_lineage_finder_read_propagates_store_not_available(self, tmp_path):
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text('[project]\nid = "acme/pipe"\n', encoding="utf-8")

        finder = lineage._Finder(store=None, follow_pins=True, shared={})
        with patch.object(lineage, "default_store", side_effect=StoreNotAvailableError("bucket gone")):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                finder._read()

    def test_run_nothing_to_pin_propagates_store_not_available(self, tmp_path):
        upstream = tmp_path / "up"
        upstream.mkdir()
        (upstream / "chartbook.toml").write_text('[project]\nid = "acme/up"\n', encoding="utf-8")
        consumer = tmp_path / "down"
        consumer.mkdir()
        (consumer / "chartbook.toml").write_text('[project]\nid = "acme/down"\n', encoding="utf-8")

        with (
            patch.object(snapshot, "code_of", return_value=object()),
            patch.object(run, "default_store", side_effect=StoreNotAvailableError("bucket gone")),
        ):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                run._nothing_to_pin(consumer, "up", {"path": "../up"}, upstream, store=None)

    def test_missing_after_pin_propagates_store_not_available(self, tmp_path):
        pins = lock.PinReport(
            lockfile=tmp_path / "chartbook.lock",
            events=[lock.PinEvent(dependency="acme/up", status="no_snapshot", detail="none")],
        )
        with patch.object(missing, "find", side_effect=StoreNotAvailableError("bucket gone")):
            with pytest.raises(StoreNotAvailableError, match="bucket gone"):
                missing.after_pin(tmp_path, pins, store=None)


class TestCheckAndRunAudit10:
    def test_check_dependency_cycles_reports_1_edge_store_self_cycle_under_different_id(self, tmp_path):
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text(
            '[project]\nid = "acme/a"\n[dependencies.other]\nid = "acme/b"\n',
            encoding="utf-8",
        )
        loaded = manifest_mod.load_manifest(pipe)
        fake_cycle = lineage.Cycle(
            edges=(lineage.Edge("acme/a", "acme/a", "other", "acme/b"),),
            way_in=(),
        )
        with patch("chartbook.lineage.cycle", return_value=fake_cycle):
            problems = check.check_dependency_cycles(loaded, pipe)
        assert len(problems) == 1
        assert "depends on itself" in problems[0].message

    def test_check_links_handles_directory_links_path_and_sanitizes_git_env(self, tmp_path):
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text('[project]\nid = "acme/a"\n', encoding="utf-8")
        (pipe / links.NAME).mkdir()
        loaded = manifest_mod.load_manifest(pipe)

        problems = check.check_links(loaded, pipe)
        assert len(problems) == 1
        assert problems[0].table == "links"

    def test_check_links_passes_clean_git_env(self, tmp_path):
        pipe = tmp_path / "pipe"
        pipe.mkdir()
        (pipe / "chartbook.toml").write_text('[project]\nid = "acme/a"\n', encoding="utf-8")
        up = tmp_path / "up"
        up.mkdir()
        (up / "chartbook.toml").write_text('[project]\nid = "acme/up"\n', encoding="utf-8")
        links.add(pipe, "acme/up", up)
        loaded = manifest_mod.load_manifest(pipe)

        captured_env = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})
            return type("R", (), {"returncode": 1})()

        with patch.dict(os.environ, {"GIT_DIR": "/bogus/git/dir"}), patch("subprocess.run", side_effect=fake_run):
            with pytest.warns(UserWarning, match="Linked dependency"):
                problems = check.check_links(loaded, pipe)
        assert problems == []
        assert "GIT_DIR" not in captured_env
        assert captured_env.get("GIT_OPTIONAL_LOCKS") == "0"

    def test_windows_single_line_script_with_leading_newline_is_stripped(self, tmp_path):
        recorded = {}

        def fake_run(cmd, **kwargs):
            recorded["cmd"] = cmd
            return type("R", (), {"returncode": 0})()

        with (
            patch.object(os, "name", "nt"),
            patch.object(run, "_as_cmd_takes_it", return_value=tmp_path),
            patch("subprocess.run", side_effect=fake_run),
        ):
            rc = run._execute("\n\necho hi\n", tmp_path, {})
        assert rc == 0
        assert recorded["cmd"] == "echo hi"


class TestManifestLinksEnvModelsAudit10:
    def test_untrusted_source_refuses_symlinked_default_site_dir_when_site_dir_empty_string(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("# Secret\n", encoding="utf-8")

        pipe = tmp_path / "pipe"
        (pipe / "docs_src").mkdir(parents=True)
        (pipe / "README.md").write_text("# Pipe\n", encoding="utf-8")
        (pipe / "chartbook.toml").write_text(
            '[project]\nid = "acme/pipe"\nsite_dir = ""\n',
            encoding="utf-8",
        )
        try:
            (pipe / "docs_src" / "site").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks not permitted on this platform")

        with patch.object(config, "untrusted_source", return_value=True):
            with pytest.raises(ValueError, match="not a plain path inside the pipeline's folder"):
                manifest_mod.load_manifest(pipe)

    def test_load_manifest_dot_uses_resolved_directory_name(self, tmp_path, monkeypatch):
        proj = tmp_path / "my_project_dir"
        proj.mkdir()
        (proj / "README.md").write_text("# Hi\n", encoding="utf-8")
        (proj / "chartbook.toml").write_text('[project]\nid = "acme/proj"\n', encoding="utf-8")

        monkeypatch.chdir(proj)
        loaded = manifest_mod.load_manifest(".")
        assert loaded["project"]["name"] == "my_project_dir"

    def test_catalog_member_dirs_accepts_store_catalog_with_repository_notes(self, tmp_path):
        cat = tmp_path / "cat"
        cat.mkdir()
        (cat / "catalog.toml").write_text(
            '[pipelines."acme/rates"]\nrepository = "https://github.com/acme/rates"\n',
            encoding="utf-8",
        )
        assert manifest_mod.catalog_member_dirs(cat) == {}

    def test_links_resolve_follows_pinned_from_for_aliased_git_dependency(self, tmp_path):
        up = tmp_path / "up_local"
        up.mkdir()
        (up / "chartbook.toml").write_text(
            '[project]\nid = "acme/rates"\n[dataframes.yields]\npath = "./y.parquet"\n',
            encoding="utf-8",
        )
        (up / "y.parquet").write_bytes(b"PAR1")

        consumer = tmp_path / "consumer"
        consumer.mkdir()
        (consumer / "chartbook.toml").write_text(
            '[project]\nid = "acme/app"\n[dependencies.rates]\ngit = "https://github.com/acme/rates"\n',
            encoding="utf-8",
        )
        lock.write_lock(
            lock.Lock(
                root="acme/app",
                dependencies=[
                    {
                        "id": "rates",
                        "pinned_from": "acme/rates",
                        "location": {
                            "kind": "git",
                            "url": "https://github.com/acme/rates",
                            "commit": "a" * 40,
                        },
                    }
                ],
                assets=[],
            ),
            consumer / lock.LOCK_FILE,
        )
        links.add(consumer, "acme/rates", up)
        links._warned.clear()

        with pytest.warns(links.LinkedDependencyWarning):
            resolved = links.resolve(AssetRef(pipeline="rates", name="yields", kind="dataframe"), consumer)
        assert resolved is not None
        assert Path(resolved.path).resolve() == (up / "y.parquet").resolve()

    def test_env_get_cast_bool_parses_false_strings(self, monkeypatch):
        for falsy in ("false", "False", "0", "no", "off"):
            monkeypatch.setenv("CB_AUDIT10_BOOL", falsy)
            assert env.get("CB_AUDIT10_BOOL", default=True, cast=bool) is False
        for truthy in ("true", "True", "1", "yes", "on"):
            monkeypatch.setenv("CB_AUDIT10_BOOL", truthy)
            assert env.get("CB_AUDIT10_BOOL", default=False, cast=bool) is True

    def test_models_versions_in_ignores_empty_placeholder_alias(self, tmp_path):
        fake_hash = "sha256:" + "a" * 64
        fake_taken = type(
            "Taken",
            (),
            {
                "made_at": "2026-01-01T00:00:00Z",
                "commit": "b" * 40,
                "assets": {"model/forecaster": {"metrics": {}, "trained_on": {}}},
                "inputs": [],
                "built_by_run": None,
            },
        )()
        with patch.object(snapshot, "versions_of", return_value=[(fake_hash, fake_taken)]):
            versions = models.versions_in(
                tmp_path,
                "forecaster",
                aliases={"empty": "", "prefix_only": "sha256:", "valid": "sha256:aaaa"},
            )
        assert len(versions) == 1
        assert versions[0].labels == ("valid",)


class TestDocsAndPlottingAudit10:
    def test_yaml_escape_and_check_front_matter_handle_dashes_and_newlines(self, tmp_path):
        escaped = yaml_escape('FRED --- Federal Reserve\n---\t"quoted"')
        assert "\n" not in escaped
        assert "\t" not in escaped
        page = tmp_path / "chart.md"
        page.write_text(
            f'---\ntags: "{escaped}"\nsources: "a---b"\n---\n# Body\n',
            encoding="utf-8",
        )
        # Should not raise SystemExit
        check_front_matter(page, "acme/p", "c1")

    def test_model_page_escapes_backticks_and_pipes_in_file_paths(self):
        assert "{{file.path | literal}}" in sphinx_mod._MODEL_PAGE_TAIL

    def test_chart_page_never_emits_date_none(self, tmp_path):
        pipeline = {
            "id": "pipeline:acme/p",
            "kind": "Pipeline",
            "name": "acme/p",
            "title": "P",
            "location": {"kind": "local", "value": str(tmp_path)},
            "project": {"id": "acme/p", "name": "P"},
            "metadata": {},
        }
        record = {
            "id": "acme/p:chart/c1",
            "kind": "Chart",
            "pipeline": "pipeline:acme/p",
            "name": "c1",
            "ref": {"name": "c1"},
            "title": "Chart 1",
            "location": {},
            "chart": {"tags": ["a---b"], "dataframe": ""},
            "metadata": {"tags": ["a---b"]},
        }
        writer = SphinxWriter({"records": [pipeline, record]})
        text = writer.chart_page("acme/p:chart/c1")
        assert 'date: "None"' not in text
        out = tmp_path / "c1.md"
        out.write_text(text, encoding="utf-8")
        check_front_matter(out, "acme/p", "c1")

    def test_plotting_rejects_empty_y_and_dual_y(self):
        df = pd.DataFrame({"x": [1, 2], "a": [3, 4], "b": [5, 6]})
        with pytest.raises(DataValidationError, match="At least one y column"):
            plotting.bar(df, x="x", y=[])
        with pytest.raises(DataValidationError, match="At least one y column"):
            plotting.area(df, x="x", y=[])
        with pytest.raises(DataValidationError, match="At least one y column"):
            plotting.line(df, x="x", y=[])
        with pytest.raises(DataValidationError, match="At least one y column"):
            plotting.dual(df, x="x", left_y=[], right_y="b")
        with pytest.raises(DataValidationError, match="At least one y column"):
            plotting.dual(df, x="x", left_y="a", right_y=[])


class TestDataBackendsSnapshotIndexAudit10:
    def test_ends_in_preserves_escape_mode_after_doubled_quote_in_e_string(self):
        sql = "select E'a''b\\' -- not a comment'"
        state, began = _ends_in(sql)
        assert state == "code"
        assert began is None
        wrapped = subselect(sql)
        assert "-- not a comment'" in wrapped

    def test_duckdb_backend_closes_owned_file_connections(self, tmp_path):
        db = tmp_path / "test.duckdb"
        con = duckdb.connect(str(db))
        con.execute("create table t (d date, v int)")
        con.execute("insert into t values ('2024-01-01', 1), ('2024-01-02', 2)")
        con.close()

        url = f"duckdb:///{db.resolve().as_posix()}"
        backend = DuckDBBackend(url)
        loc = TableLocation("db", "duckdb", backend.url, "t")
        cols, count = backend.describe(loc)
        assert count == 2
        assert [c["name"] for c in cols] == ["d", "v"]
        first, last = backend.span(loc, "d")
        assert str(first).startswith("2024-01-01")
        assert str(last).startswith("2024-01-02")

        with pytest.raises(Exception):
            backend.sql("select * from nonexistent_table_xyz")

        # Must be able to reopen read-write immediately with no lingering read-only connection
        rw = duckdb.connect(str(db), read_only=False)
        rw.execute("insert into t values ('2024-01-03', 3)")
        rw.close()

    def test_materialize_in_source_handles_trailing_semicolon_and_comment(self, tmp_path):
        db = tmp_path / "data.duckdb"
        con = duckdb.connect(str(db))
        con.execute("create table t (a int, b int)")
        con.execute("insert into t values (2, 10), (1, 20)")
        con.close()

        raw = {
            "sources": {"db": {"backend": "duckdb", "url": "duckdb:///./data.duckdb"}},
            "dataframes": {
                "q_semi": {"source": "db", "query": "select a, b from t;"},
                "q_comment": {"source": "db", "query": "select a, b from t -- trailing note"},
            },
        }
        store = FolderStore(tmp_path / "store")
        results = snapshot.materialize_in_source(tmp_path, "acme/p", raw, store)
        assert len(results) == 2
        for _local, record, error in results:
            assert error is None
            assert record.get("content_hash")

    def test_arrow_dataset_ignores_hive_keys_above_store_root(self, tmp_path):
        # Put the store inside a directory containing year=2020
        root = tmp_path / "year=2020" / "store" / "obj"
        part = root / "year=2024"
        part.mkdir(parents=True)
        ipc_file = part / "part.ipc"
        table = pa.table({"val": [42]})
        with ipc.new_file(ipc_file, table.schema) as writer:
            writer.write_table(table)

        loc = FileLocation(
            path=root,
            format="ipc",
            inside={"year=2024/part.ipc": ipc_file},
        )
        ds = formats.arrow_dataset(loc)
        result = ds.to_table().to_pydict()
        assert result["year"] == [2024]
        assert result["val"] == [42]

    def test_pipeline_input_files_includes_local_duckdb_source(self, tmp_path):
        db = tmp_path / "local.duckdb"
        db.write_bytes(b"")
        manifest = {
            "pipeline_base_dir": str(tmp_path),
            "project": {"readme": "README.md"},
            "sources": {
                "local": {"backend": "duckdb", "url": "duckdb:///./local.duckdb"},
                "mem": {"backend": "duckdb", "url": "duckdb:///:memory:"},
            },
        }
        inputs = incremental.pipeline_input_files(manifest)
        assert db.resolve() in {p.resolve() for p in inputs}

    def test_rowhash_index_columns_and_snapshot_rows_of_handle_runtime_error(self, tmp_path):
        fake_file = tmp_path / "a.parquet"
        fake_file.write_bytes(b"PAR1")
        table = rowhash.Table(fake_file, "parquet")
        with patch.object(rowhash.Table, "schema", side_effect=RuntimeError(f"{formats._SCRATCH}: No space left on device")):
            assert rowhash.index_columns_of(table) == []
            with pytest.raises(rowhash.NotNow):
                snapshot._rows_of(
                    "dataframe/a",
                    {"content_hash": "sha256:" + "0" * 64},
                    fake_file,
                    {},
                    {},
                    [],
                )

    def test_index_well_formed_accepts_timezone_aware_last_dates(self):
        assert index._well_formed(
            "last_dates",
            {"min": "2024-01-01T00:00:00+00:00", "max": "2024-12-31T23:59:59.123456Z"},
        )
        assert index._well_formed(
            "last_dates",
            {"min": "2024-01-01 00:00:00-05:00", "max": "2024-12-31"},
        )
