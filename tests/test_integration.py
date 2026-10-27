"""
Cross-module integration tests.

These tests exercise the complete workflow from manifest reading through
documentation generation, verifying that the full pipeline works correctly.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pandas as pd
import pytest

from chartbook.build_docs import generate_docs
from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest, load_manifest
from tests.fixtures import remove_tree

# Path to mock data fixtures for example projects
MOCK_DATA_DIR = Path(__file__).parent / "fixtures" / "mock_fred_data"


class TestManifestToGeneratorPipelineWorkflow:
    """End-to-end tests for pipeline documentation workflow.

    Uses fixture-generated projects to test the complete workflow.
    """

    def test_full_pipeline_workflow(self, pipeline_project, monkeypatch):
        """Test complete workflow: read manifest -> generate docs."""
        output_dir = pipeline_project / "docs_integration_test"

        # Change to project directory (required for template resolution)
        monkeypatch.chdir(pipeline_project)

        # Step 1: Read and verify manifest
        manifest = load_manifest(Path("."))
        assert manifest["project"]["type"] == "pipeline"
        assert "dataframes" in manifest
        assert "charts" in manifest

        # Verify chart-dataframe linking
        for df_id in manifest["dataframes"]:
            assert "linked_charts" in manifest["dataframes"][df_id]

        # Verify pipeline ID list works
        pipeline_ids = get_pipeline_ids(manifest)
        assert len(pipeline_ids) == 1

        # Verify get_pipeline_manifest works
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_ids[0])
        assert "dataframes" in pipeline_manifest

        # Step 2: Generate documentation
        generate_docs(
            output_dir=output_dir,
            project_dir=Path("."),
            keep_build_dirs=False,
        )

        # Step 3: Verify output structure
        assert output_dir.exists()
        assert (output_dir / "index.html").exists()
        assert (output_dir / ".nojekyll").exists()

        # Verify HTML has content
        html_content = (output_dir / "index.html").read_text(encoding="utf-8")
        assert len(html_content) > 0


class TestManifestToGeneratorCatalogWorkflow:
    """End-to-end tests for catalog documentation workflow.

    Note: These tests verify manifest reading for catalog type works correctly.
    Full generation tests would require a complete catalog example.
    """

    def test_catalog_manifest_reading(self, catalog_project):
        """Test that catalog manifest is read and processed correctly."""
        manifest = load_manifest(catalog_project)
        assert manifest["project"]["type"] == "catalog"

        pipeline_ids = get_pipeline_ids(manifest)
        assert len(pipeline_ids) == 2
        assert "pipeline_a" in pipeline_ids
        assert "pipeline_b" in pipeline_ids

        # Verify each pipeline has full manifest
        for pid in pipeline_ids:
            pipeline_manifest = get_pipeline_manifest(manifest, pid)
            assert pipeline_manifest["project"]["type"] == "pipeline"
            assert "dataframes" in pipeline_manifest
            assert "charts" in pipeline_manifest

    def test_catalog_platform_paths_resolution(self, catalog_project_platform_paths):
        """Test catalog with platform-specific path dictionaries."""
        manifest = load_manifest(catalog_project_platform_paths)
        assert manifest["project"]["type"] == "catalog"

        # Both pipelines should be accessible
        pipeline_ids = get_pipeline_ids(manifest)
        assert "pipeline_x" in pipeline_ids
        assert "pipeline_y" in pipeline_ids

        # Each should have valid manifest
        for pid in pipeline_ids:
            pipeline_manifest = get_pipeline_manifest(manifest, pid)
            assert pipeline_manifest["project"]["id"] == pid


class TestWorkflowErrorHandling:
    """Tests for error handling across the workflow."""

    def test_workflow_fails_gracefully_for_missing_chartbook(
        self, invalid_project_missing_file, tmp_path
    ):
        """Test that missing chartbook.toml is caught early in workflow."""
        output_dir = tmp_path / "output"
        docs_dir = tmp_path / "_docs"
        docs_src_dir = tmp_path / "_docs_src"

        with pytest.raises((FileNotFoundError, ValueError)):
            generate_docs(
                output_dir=output_dir,
                project_dir=invalid_project_missing_file,
                _docs_dir=docs_dir,
                temp_docs_src_dir=docs_src_dir,
            )

    def test_workflow_fails_for_invalid_config_type(
        self, invalid_project_invalid_type, tmp_path
    ):
        """Test that invalid config type is caught."""
        output_dir = tmp_path / "output"
        docs_dir = tmp_path / "_docs"
        docs_src_dir = tmp_path / "_docs_src"

        with pytest.raises(ValueError):
            generate_docs(
                output_dir=output_dir,
                project_dir=invalid_project_invalid_type,
                _docs_dir=docs_dir,
                temp_docs_src_dir=docs_src_dir,
            )


class TestExampleProjects:
    """Integration tests that run the actual example projects.

    These tests execute the full doit pipeline for each example to verify
    the complete workflow works end-to-end.

    Note: These tests use pre-generated mock data files to avoid network
    dependencies on external APIs (FRED, OFR, Federal Reserve). The mock
    data is copied to the example _data directories before running doit.
    """

    @staticmethod
    def _clean_example_dirs(example_path: Path):
        """Remove _data, _output, docs, and build directories from an example."""
        for dir_name in ["_data", "_output", "docs", "_docs", "_docs_src"]:
            dir_path = example_path / dir_name
            if dir_path.exists():
                remove_tree(dir_path)
        # Also remove doit database for clean state
        doit_db = example_path / ".doit-db.sqlite"
        if doit_db.exists():
            doit_db.unlink()
        # ...and a lockfile, which pins whatever data an earlier build had
        lockfile = example_path / "chartbook.lock"
        if lockfile.exists():
            lockfile.unlink()

    @staticmethod
    def _touch_newer_than(target: Path, source: Path):
        """Set target's mtime to be 1 second newer than source.

        This ensures doit considers the target up-to-date and won't re-run
        the task that produces it.
        """
        src_mtime = source.stat().st_mtime
        new_mtime = src_mtime + 1
        os.utime(target, (new_mtime, new_mtime))

    @staticmethod
    def _get_env_with_pythonpath():
        """Get environment with PYTHONPATH set to use local src."""
        env = os.environ.copy()
        src_path = Path(__file__).parent.parent / "src"
        existing_pythonpath = env.get("PYTHONPATH", "")
        if existing_pythonpath:
            env["PYTHONPATH"] = f"{src_path}:{existing_pythonpath}"
        else:
            env["PYTHONPATH"] = str(src_path)
        return env

    @staticmethod
    def _setup_mock_data_fred_charts(example_path: Path):
        """Copy mock FRED data to fred_charts example _data directory.

        This pre-populates the data directory so doit skips the pull:fred task,
        avoiding network calls to the FRED API during tests.
        """
        data_dir = example_path / "_data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Copy mock FRED data
        mock_fred = MOCK_DATA_DIR / "fred_charts_mock.parquet"
        target_fred = data_dir / "fred.parquet"
        shutil.copy2(mock_fred, target_fred)

        # Also create CSV version (some scripts expect it)
        df = pd.read_parquet(mock_fred)
        csv_file = data_dir / "fred.csv"
        df.to_csv(csv_file)

        # Set mtime of target files to be newer than source files
        # This ensures doit considers the pull:fred task up-to-date
        source_file = example_path / "src" / "pull_fred.py"
        TestExampleProjects._touch_newer_than(target_fred, source_file)
        TestExampleProjects._touch_newer_than(csv_file, source_file)

    @staticmethod
    def _setup_mock_data_yield_curve(example_path: Path):
        """Copy mock data to yield_curve example _data directory.

        This pre-populates the data directory so doit skips the pull tasks,
        avoiding network calls to FRED, OFR, and Federal Reserve APIs during tests.
        """
        data_dir = example_path / "_data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Copy mock FRED data (yield_curve uses the larger series set)
        mock_fred = MOCK_DATA_DIR / "yield_curve_mock.parquet"
        target_fred = data_dir / "fred.parquet"
        shutil.copy2(mock_fred, target_fred)

        # Also create CSV version
        df_fred = pd.read_parquet(mock_fred)
        csv_fred = data_dir / "fred.csv"
        df_fred.to_csv(csv_fred)

        # Copy mock OFR data
        mock_ofr = MOCK_DATA_DIR / "ofr_mock.parquet"
        target_ofr = data_dir / "ofr_public_repo_data.parquet"
        shutil.copy2(mock_ofr, target_ofr)

        # Copy mock Fed yield curve data
        mock_yc = MOCK_DATA_DIR / "fed_yield_curve_mock.parquet"
        target_yc = data_dir / "fed_yield_curve.parquet"
        shutil.copy2(mock_yc, target_yc)

        # Set mtime of target files to be newer than their respective source files
        # This ensures doit considers the pull tasks up-to-date
        src_dir = example_path / "src"
        TestExampleProjects._touch_newer_than(target_fred, src_dir / "pull_fred.py")
        TestExampleProjects._touch_newer_than(csv_fred, src_dir / "pull_fred.py")
        TestExampleProjects._touch_newer_than(target_ofr, src_dir / "pull_ofr_api_data.py")
        TestExampleProjects._touch_newer_than(target_yc, src_dir / "load_fed_yield_curve.py")

    def test_fred_charts_example(self):
        """Test that fred_charts example runs successfully with doit -a."""
        example_path = Path("examples/fred_charts").resolve()

        # Clean up before running
        self._clean_example_dirs(example_path)

        # Setup mock data to avoid network calls
        self._setup_mock_data_fred_charts(example_path)

        # Run doit -a with PYTHONPATH set to use local chartbook
        result = subprocess.run(
            ["doit", "-a"],
            cwd=example_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=self._get_env_with_pythonpath(), encoding="utf-8", errors="replace"
        )

        assert result.returncode == 0, f"doit failed: {result.stderr}\n{result.stdout}"

        # Verify outputs exist
        assert (example_path / "_data" / "fred.parquet").exists()
        assert (example_path / "_output" / "01_gdp_chart.html").exists()
        assert (example_path / "docs" / "index.html").exists()

    def test_yield_curve_example(self):
        """Test that yield_curve example runs successfully with doit -a."""
        example_path = Path("examples/yield_curve").resolve()

        # Clean up before running
        self._clean_example_dirs(example_path)

        # Setup mock data to avoid network calls
        self._setup_mock_data_yield_curve(example_path)

        # Run doit -a with PYTHONPATH set to use local chartbook
        result = subprocess.run(
            ["doit", "-a"],
            cwd=example_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=self._get_env_with_pythonpath(), encoding="utf-8", errors="replace"
        )

        assert result.returncode == 0, f"doit failed: {result.stderr}\n{result.stdout}"

        # Verify outputs exist
        assert (example_path / "_data" / "fed_yield_curve.parquet").exists()
        assert (example_path / "_output" / "yield_curve_current.html").exists()
        assert (example_path / "docs" / "index.html").exists()

    @staticmethod
    def _snapshot(pipeline_path: Path, env: dict):
        """Declare a pipeline's build ready, as its owner would.

        A snapshot needs everything in the pipeline's folder to be committed,
        so this fails if the example has been edited and not committed.
        """
        result = subprocess.run(
            ["chartbook", "snapshot"],
            cwd=pipeline_path,
            capture_output=True,
            text=True,
            timeout=300,
            env=env, encoding="utf-8", errors="replace"
        )
        assert result.returncode == 0, (
            f"chartbook snapshot failed in {pipeline_path.name}. If you have edited "
            f"that example, commit it first.\n{result.stderr}\n{result.stdout}"
        )
        return result

    def _build_rate_forecast(self, store_dir: Path):
        """Build the rate_forecast example on yield_curve's mock data.

        A snapshot of yield_curve is made in *store_dir*, a scratch store,
        and rate_forecast pins that, so that a test never writes to the
        store of whoever runs it. The lockfile it leaves is removed again:
        it names objects in a store that is about to be deleted.
        """
        yield_curve_path = Path("examples/yield_curve").resolve()
        example_path = Path("examples/rate_forecast").resolve()
        env = {**self._get_env_with_pythonpath(), "CHARTBOOK_STORE": str(store_dir)}

        if not (yield_curve_path / "_data" / "fed_yield_curve.parquet").exists():
            self._clean_example_dirs(yield_curve_path)
            self._setup_mock_data_yield_curve(yield_curve_path)
            result = subprocess.run(
                ["doit", "-a"],
                cwd=yield_curve_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=env, encoding="utf-8", errors="replace"
            )
            assert result.returncode == 0, f"yield_curve doit failed: {result.stderr}"
        self._snapshot(yield_curve_path, env)

        self._clean_example_dirs(example_path)
        result = subprocess.run(
            ["doit", "-a"],
            cwd=example_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=env, encoding="utf-8", errors="replace"
        )
        assert result.returncode == 0, f"doit failed: {result.stderr}\n{result.stdout}"
        return example_path, env

    def test_rate_forecast_example(self, tmp_path):
        """A model in one pipeline, trained on another's data, through a pin.

        This is the "Done when" of step 3 in docs_src/design/overview.md: it
        builds with no catalog configured, its model's index record names
        the exact bytes it was trained on, and editing the upstream's data
        does not change what it reads until `chartbook update`.

        And of the snapshot model of step 4: what it pins is the build
        yield_curve's owner declared ready. A rebuild of yield_curve is not
        seen at all until its owner makes a snapshot of it.
        """
        yield_curve_path = Path("examples/yield_curve").resolve()
        upstream = yield_curve_path / "_data" / "fed_yield_curve.parquet"
        example_path, env = self._build_rate_forecast(tmp_path / "store")
        lockfile = example_path / "chartbook.lock"
        original = upstream.read_bytes() if upstream.exists() else None
        try:
            assert (example_path / "_models" / "rate_forecast.json").exists()
            assert (example_path / "docs" / "index.html").exists()

            # The model's record names the bytes of the dataframe it read
            built = json.loads((example_path / "docs" / "index.json").read_text(encoding="utf-8"))
            (model,) = [r for r in built["records"] if r["kind"] == "Model"]
            input_id = "backofficedev/yield_curve:fed_yield_curve"
            assert model["inputs"] == [input_id]
            pinned_at = model["pinned_inputs"][input_id]
            assert pinned_at == "sha256:" + hashlib.sha256(original).hexdigest()

            def run(*command):
                return subprocess.run(
                    command, cwd=example_path, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace"
                )

            # ...and what it reads is the pinned copy, not the upstream's file
            pinned_path = Path(run("chartbook", "path", "yield_curve:fed_yield_curve").stdout.strip())
            assert pinned_path.read_bytes() == original
            assert yield_curve_path not in pinned_path.parents

            # The upstream rewrites its file in place, as pandas does
            smaller = pd.read_parquet(upstream).iloc[:500]
            smaller.to_parquet(upstream)
            assert upstream.read_bytes() != original

            again = run("chartbook", "path", "yield_curve:fed_yield_curve").stdout.strip()
            assert Path(again) == pinned_path
            assert pinned_path.read_bytes() == original

            # Nothing here is told: the folder is not read, and its owner
            # has not declared the new data ready. Not even an update moves.
            pin = run("chartbook", "pin")
            assert "changed upstream" not in pin.stdout, pin.stdout + pin.stderr
            assert "chartbook.lock is unchanged." in run("chartbook", "update").stdout

            # Its owner makes a snapshot. Now this pipeline is told, and stays put.
            assert "Snapshot made." in self._snapshot(yield_curve_path, env).stdout
            pin = run("chartbook", "pin")
            assert "changed upstream" in pin.stdout, pin.stdout + pin.stderr
            assert Path(run("chartbook", "path", "yield_curve:fed_yield_curve").stdout.strip()) == pinned_path

            # Until `chartbook update`
            update = run("chartbook", "update")
            assert update.returncode == 0, update.stdout + update.stderr
            moved = Path(run("chartbook", "path", "yield_curve:fed_yield_curve").stdout.strip())
            assert moved != pinned_path
            assert len(pd.read_parquet(moved)) == 500
        finally:
            if original is not None:
                upstream.write_bytes(original)
                self._touch_newer_than(
                    upstream, yield_curve_path / "src" / "load_fed_yield_curve.py"
                )
            if lockfile.exists():
                lockfile.unlink()

    def test_chartbook_run_pins_and_builds_the_example(self, tmp_path):
        """`chartbook run` in rate_forecast pins yield_curve's snapshot, and builds.

        From nothing pinned: step 4 in docs_src/design/overview.md. It does
        not build yield_curve, which is a folder this pipeline depends on
        and its owner's to build and to declare ready; here the test is its
        owner. Each example's `build` script is `doit`.
        """
        yield_curve_path = Path("examples/yield_curve").resolve()
        example_path = Path("examples/rate_forecast").resolve()
        env = {**self._get_env_with_pythonpath(), "CHARTBOOK_STORE": str(tmp_path / "store")}
        if not (yield_curve_path / "_data" / "fed_yield_curve.parquet").exists():
            self._clean_example_dirs(yield_curve_path)
            self._setup_mock_data_yield_curve(yield_curve_path)
        built = subprocess.run(
            ["chartbook", "run"],
            cwd=yield_curve_path,
            capture_output=True,
            text=True,
            timeout=900,
            env=env, encoding="utf-8", errors="replace"
        )
        assert built.returncode == 0, f"run failed: {built.stderr}\n{built.stdout}"
        assert built.stdout.rstrip().endswith("Ran build in 1 pipeline(s).")
        self._snapshot(yield_curve_path, env)

        self._clean_example_dirs(example_path)
        lockfile = example_path / "chartbook.lock"
        try:
            result = subprocess.run(
                ["chartbook", "run"],
                cwd=example_path,
                capture_output=True,
                text=True,
                timeout=900,
                env=env, encoding="utf-8", errors="replace"
            )
            assert result.returncode == 0, f"run failed: {result.stderr}\n{result.stdout}"

            # The pin, then this pipeline. Nothing is run in yield_curve.
            said = result.stdout
            pinning = "backofficedev/rate_forecast: pinning what it depends on"
            itself = "backofficedev/rate_forecast: build\n"
            assert pinning in said and itself in said, said
            assert said.index(pinning) < said.index(itself)
            assert "backofficedev/yield_curve: build" not in said
            assert said.rstrip().endswith("Ran build in 1 pipeline(s).")

            assert (yield_curve_path / "docs" / "index.html").exists()
            assert lockfile.exists()
            assert (example_path / "_models" / "rate_forecast.json").exists()
            assert (example_path / "docs" / "index.html").exists()

            # Both name their build script, and the index lists it
            built = json.loads((example_path / "docs" / "index.json").read_text(encoding="utf-8"))
            (pipeline,) = [r for r in built["records"] if r["kind"] == "Pipeline"]
            assert pipeline["scripts"] == {"build": "doit"}
        finally:
            if lockfile.exists():
                lockfile.unlink()

    def test_catalog_example(self, tmp_path):
        """Test that catalog example builds successfully.

        The catalog references the fred_charts, yield_curve and rate_forecast
        pipelines, so we need to run those first to generate the required
        files.
        """
        catalog_path = Path("examples/catalog").resolve()
        fred_charts_path = Path("examples/fred_charts").resolve()
        yield_curve_path = Path("examples/yield_curve").resolve()
        rate_forecast_path = Path("examples/rate_forecast").resolve()

        # Clean up catalog before running
        self._clean_example_dirs(catalog_path)

        # Run doit -a on fred_charts first (if not already run by previous test)
        if not (fred_charts_path / "_data" / "fred.parquet").exists():
            self._clean_example_dirs(fred_charts_path)
            self._setup_mock_data_fred_charts(fred_charts_path)
            result = subprocess.run(
                ["doit", "-a"],
                cwd=fred_charts_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._get_env_with_pythonpath(), encoding="utf-8", errors="replace"
            )
            assert result.returncode == 0, f"fred_charts doit failed: {result.stderr}"

        # Run doit -a on yield_curve (if not already run by previous test)
        if not (yield_curve_path / "_data" / "fed_yield_curve.parquet").exists():
            self._clean_example_dirs(yield_curve_path)
            self._setup_mock_data_yield_curve(yield_curve_path)
            result = subprocess.run(
                ["doit", "-a"],
                cwd=yield_curve_path,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._get_env_with_pythonpath(), encoding="utf-8", errors="replace"
            )
            assert result.returncode == 0, f"yield_curve doit failed: {result.stderr}"

        # rate_forecast reads yield_curve's data, so it is built after it
        self._build_rate_forecast(tmp_path / "store")
        lockfile = rate_forecast_path / "chartbook.lock"
        try:
            # Now render the catalog's site
            result = subprocess.run(
                ["chartbook", "docs", "generate", "-f"],
                cwd=catalog_path,
                capture_output=True,
                text=True,
                timeout=300,
                env=self._get_env_with_pythonpath(), encoding="utf-8", errors="replace"
            )

            assert result.returncode == 0, f"chartbook docs generate failed: {result.stderr}"

            # Verify outputs exist
            assert (catalog_path / "docs" / "index.html").exists()

            # In the catalog's index, the model's input is the ID of the
            # dataframe's own record, with the bytes it is pinned at
            built = json.loads((catalog_path / "docs" / "index.json").read_text(encoding="utf-8"))
            (model,) = [
                r for r in built["records"] if r["id"].endswith(":model/rate_forecast")
            ]
            (input_id,) = model["inputs"]
            (dataframe,) = [r for r in built["records"] if r.get("id") == input_id]
            assert model["pinned_inputs"] == {input_id: dataframe["content_hash"]}
        finally:
            if lockfile.exists():
                lockfile.unlink()
