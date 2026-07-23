"""Tests for the ``chartbook catalog add`` CLI command."""

from pathlib import Path

import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from tests.fixtures import create_catalog_project, create_pipeline_project


def _make_minimal_catalog(catalog_dir, pipelines=None):
    """Create a minimal catalog chartbook.toml.

    :param catalog_dir: Directory for the catalog.
    :param pipelines: Optional dict of pipeline entries.
    :returns: Path to the catalog directory.
    """
    catalog_dir = Path(catalog_dir)
    catalog_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "project": {
            "type": "catalog",
            "name": "Test Catalog",
            "maintainer": "Test",
        },
        "pipelines": pipelines or {},
    }
    with open(catalog_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)
    return catalog_dir


def _make_minimal_pipeline(pipeline_dir, pipeline_id="TP", pipeline_name="Test Pipeline"):
    """Create a minimal pipeline chartbook.toml (no data files needed for catalog add).

    No explicit project.id is written, so the catalog key derives from the
    directory name (these tmp dirs are outside any git repo).
    """
    pipeline_dir = Path(pipeline_dir)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "project": {
            "name": pipeline_name,
            "maintainer": "Test",
        },
    }
    with open(pipeline_dir / "chartbook.toml", "wb") as f:
        tomli_w.dump(config, f)
    return pipeline_dir


def _read_catalog(catalog_dir):
    """Read and return the catalog TOML as a dict."""
    with open(Path(catalog_dir) / "chartbook.toml", "rb") as f:
        return tomli.load(f)


class TestCatalogAddSingle:
    """Tests for adding a single pipeline to the catalog."""

    def test_add_single_pipeline(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        pipeline_dir = _make_minimal_pipeline(
            tmp_path / "my_pipeline", pipeline_id="MP", pipeline_name="My Pipeline"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["catalog", "add", str(pipeline_dir), "--catalog", str(catalog_dir / "chartbook.toml")],
        )

        assert result.exit_code == 0, result.output
        assert "Added 1 pipeline(s)" in result.output

        data = _read_catalog(catalog_dir)
        assert "my_pipeline" in data["pipelines"]
        assert "path" in data["pipelines"]["my_pipeline"]

    def test_add_duplicate_skipped(self, tmp_path):
        pipeline_dir = _make_minimal_pipeline(tmp_path / "pipelines" / "alpha")
        catalog_dir = _make_minimal_catalog(
            tmp_path / "catalog",
            pipelines={"alpha": {"path": str(pipeline_dir)}},
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["catalog", "add", str(pipeline_dir), "--catalog", str(catalog_dir / "chartbook.toml")],
        )

        assert result.exit_code == 0
        assert "Already in catalog" in result.output
        assert "No new pipelines to add" in result.output

    def test_add_invalid_dir_no_toml(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["catalog", "add", str(empty_dir), "--catalog", str(catalog_dir / "chartbook.toml")],
        )

        assert result.exit_code != 0
        assert "No chartbook.toml found" in result.output

    def test_add_catalog_type_rejected(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        other_catalog = _make_minimal_catalog(tmp_path / "other_catalog")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(other_catalog),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code != 0
        assert "not a pipeline" in result.output

    def test_add_nonexistent_path(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(tmp_path / "nonexistent"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code != 0


class TestCatalogAddGlob:
    """Tests for adding multiple pipelines via glob."""

    def test_add_glob_multiple_with_yes(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        parent = tmp_path / "projects"
        _make_minimal_pipeline(parent / "proj_a", pipeline_id="PA", pipeline_name="Project A")
        _make_minimal_pipeline(parent / "proj_b", pipeline_id="PB", pipeline_name="Project B")
        _make_minimal_pipeline(parent / "proj_c", pipeline_id="PC", pipeline_name="Project C")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(parent / "*"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
                "-y",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Added 3 pipeline(s)" in result.output

        data = _read_catalog(catalog_dir)
        assert "proj_a" in data["pipelines"]
        assert "proj_b" in data["pipelines"]
        assert "proj_c" in data["pipelines"]

    def test_add_glob_prompts_without_yes(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        parent = tmp_path / "projects"
        _make_minimal_pipeline(parent / "proj_a", pipeline_id="PA", pipeline_name="Project A")
        _make_minimal_pipeline(parent / "proj_b", pipeline_id="PB", pipeline_name="Project B")

        runner = CliRunner()
        # Respond "y" to the confirmation prompt
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(parent / "*"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
            input="y\n",
        )

        assert result.exit_code == 0, result.output
        assert "Added 2 pipeline(s)" in result.output

    def test_add_glob_declined(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        parent = tmp_path / "projects"
        _make_minimal_pipeline(parent / "proj_a")
        _make_minimal_pipeline(parent / "proj_b")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(parent / "*"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
            input="n\n",
        )

        # Should exit without adding
        assert result.exit_code == 0
        data = _read_catalog(catalog_dir)
        assert len(data["pipelines"]) == 0

    def test_add_glob_skips_invalid_dirs(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        parent = tmp_path / "projects"
        _make_minimal_pipeline(parent / "valid_proj", pipeline_id="VP")
        # Create a directory without chartbook.toml
        (parent / "not_a_pipeline").mkdir(parents=True)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(parent / "*"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
                "-y",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Skipping" in result.output
        assert "Added 1 pipeline(s)" in result.output

    def test_add_glob_skips_duplicates(self, tmp_path):
        parent = tmp_path / "projects"
        pipeline_dir = _make_minimal_pipeline(parent / "existing")
        _make_minimal_pipeline(parent / "new_one", pipeline_id="NO")

        catalog_dir = _make_minimal_catalog(
            tmp_path / "catalog",
            pipelines={"existing": {"path": str(pipeline_dir)}},
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(parent / "*"),
                "--catalog", str(catalog_dir / "chartbook.toml"),
                "-y",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Already in catalog" in result.output
        assert "Added 1 pipeline(s)" in result.output


class TestCatalogAddKeyHandling:
    """Tests for key sanitization and conflict resolution."""

    def test_key_sanitization(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        pipeline_dir = _make_minimal_pipeline(tmp_path / "My-Cool Pipeline!")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_dir),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_catalog(catalog_dir)
        # Should be sanitized: lowercase, hyphens/spaces to underscores, special chars removed
        assert "my_cool_pipeline" in data["pipelines"]

    def test_key_conflict_resolution(self, tmp_path):
        # Create two pipelines with the same basename in different parent dirs
        pipeline_a = _make_minimal_pipeline(
            tmp_path / "group_a" / "shared_name", pipeline_id="A"
        )
        pipeline_b = _make_minimal_pipeline(
            tmp_path / "group_b" / "shared_name", pipeline_id="B"
        )
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")

        runner = CliRunner()
        # Add first
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_a),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )
        assert result.exit_code == 0, result.output

        # Add second (same basename)
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_b),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )
        assert result.exit_code == 0, result.output

        data = _read_catalog(catalog_dir)
        assert "shared_name" in data["pipelines"]
        assert "shared_name_2" in data["pipelines"]


class TestCatalogAddPreservesContent:
    """Tests that existing catalog content survives the write."""

    def test_preserves_existing_pipelines_and_site(self, tmp_path):
        existing_pipeline = _make_minimal_pipeline(
            tmp_path / "existing_proj", pipeline_id="EP"
        )
        catalog_dir = _make_minimal_catalog(
            tmp_path / "catalog",
            pipelines={
                "existing_proj": {
                    "path": str(existing_pipeline),
                }
            },
        )

        new_pipeline = _make_minimal_pipeline(
            tmp_path / "new_proj", pipeline_id="NP"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(new_pipeline),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_catalog(catalog_dir)

        # Existing pipeline preserved
        assert "existing_proj" in data["pipelines"]
        # New pipeline added
        assert "new_proj" in data["pipelines"]
        # Project metadata preserved
        assert data["project"]["name"] == "Test Catalog"
        assert data["project"]["type"] == "catalog"


class TestCatalogAddWithRelativePaths:
    """Tests that paths are stored as relative to catalog dir."""

    def test_stores_relative_path(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "workspace" / "catalog")
        pipeline_dir = _make_minimal_pipeline(
            tmp_path / "workspace" / "my_pipeline"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_dir),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_catalog(catalog_dir)
        stored_path = data["pipelines"]["my_pipeline"]["path"]
        # Should be relative (e.g., "../my_pipeline")
        assert not Path(stored_path).is_absolute()


class TestCatalogAddWithFixtures:
    """Tests using the project fixture helpers."""

    def test_add_fixture_pipeline_to_fixture_catalog(self, tmp_path):
        """Add a pipeline created with create_pipeline_project to a catalog."""
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        pipeline_dir = create_pipeline_project(
            tmp_path / "real_pipeline",
            pipeline_id="RP",
            pipeline_name="Real Pipeline",
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_dir),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Added 1 pipeline(s)" in result.output

    def test_add_to_existing_catalog_project(self, tmp_path):
        """Add a new pipeline to a catalog created with create_catalog_project."""
        catalog_dir = create_catalog_project(
            tmp_path / "catalog",
            pipeline_ids=["pipeline_a"],
        )
        new_pipeline = _make_minimal_pipeline(
            tmp_path / "new_pipeline", pipeline_id="NP"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(new_pipeline),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_catalog(catalog_dir)
        # Original pipeline preserved
        assert "pipeline_a" in data["pipelines"]
        # New pipeline added
        assert "new_pipeline" in data["pipelines"]


class TestCatalogAddPathValidation:
    """Tests for path validation in catalog add."""

    def test_windows_path_in_mingw_shows_warning(self, tmp_path, monkeypatch):
        """Windows-style path in MINGW env should show a warning."""
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")

        # Simulate MINGW environment
        monkeypatch.setenv("MSYSTEM", "MINGW64")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", r"C:\Users\student\pipeline",
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )
        # Should show warning about Windows path in Git Bash
        assert "Warning" in result.output or "Warning" in (result.stderr or "")

    def test_normal_path_no_warning(self, tmp_path, monkeypatch):
        """Normal POSIX path should not trigger warnings."""
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog")
        pipeline_dir = _make_minimal_pipeline(tmp_path / "my_pipeline")

        # Ensure no MINGW/WSL env vars
        monkeypatch.delenv("MSYSTEM", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "catalog", "add", str(pipeline_dir),
                "--catalog", str(catalog_dir / "chartbook.toml"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Warning" not in result.output
