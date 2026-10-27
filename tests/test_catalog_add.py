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


class TestAddAPipelineShownFromTheStore:
    """An entry with no path is a pipeline the catalog shows from the store; adding its folder fills it in."""

    def _add(self, catalog_dir, *paths):
        return CliRunner().invoke(
            main, ["catalog", "add", *map(str, paths), "--catalog", str(catalog_dir / "chartbook.toml"), "-y"]
        )

    def test_its_folder_fills_the_entry(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"my_pipeline": {}})
        pipeline_dir = _make_minimal_pipeline(tmp_path / "my_pipeline")
        result = self._add(catalog_dir, pipeline_dir)
        assert result.exit_code == 0, result.output
        assert "showed from the store" in result.output
        pipelines = _read_catalog(catalog_dir)["pipelines"]
        assert pipelines == {"my_pipeline": {"path": "../my_pipeline"}}

    def test_a_disabled_one_is_enabled(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"my_pipeline": {"disabled": True}})
        result = self._add(catalog_dir, _make_minimal_pipeline(tmp_path / "my_pipeline"))
        assert result.exit_code == 0, result.output
        assert _read_catalog(catalog_dir)["pipelines"] == {"my_pipeline": {"path": "../my_pipeline"}}

    def test_and_taken_off_the_disabled_list(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"my_pipeline": {}, "disabled": ["my_pipeline"]})
        result = self._add(catalog_dir, _make_minimal_pipeline(tmp_path / "my_pipeline"))
        assert result.exit_code == 0, result.output
        assert _read_catalog(catalog_dir)["pipelines"] == {"my_pipeline": {"path": "../my_pipeline"}}

    def test_a_folder_already_listed_is_taken_off_the_disabled_list(self, tmp_path):
        catalog_dir = _make_minimal_catalog(
            tmp_path / "catalog", {"my_pipeline": "../my_pipeline", "disabled": ["my_pipeline", "my_pipeline"]}
        )
        result = self._add(catalog_dir, _make_minimal_pipeline(tmp_path / "my_pipeline"))
        assert result.exit_code == 0, result.output
        assert "Re-enabled 'my_pipeline'" in result.output
        assert _read_catalog(catalog_dir)["pipelines"] == {"my_pipeline": "../my_pipeline"}

    def test_a_folder_listed_by_a_plain_path_is_already_there(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"my_pipeline": "../my_pipeline"})
        result = self._add(catalog_dir, _make_minimal_pipeline(tmp_path / "my_pipeline"))
        assert result.exit_code == 0, result.output
        assert "Already in catalog as 'my_pipeline'" in result.output

    def test_a_new_one_on_the_disabled_list_is_enabled(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"disabled": ["my_pipeline"]})
        result = self._add(catalog_dir, _make_minimal_pipeline(tmp_path / "my_pipeline"))
        assert result.exit_code == 0, result.output
        assert "it was on the disabled list" in result.output
        assert _read_catalog(catalog_dir)["pipelines"] == {"my_pipeline": {"path": "../my_pipeline"}}

    def test_a_second_folder_of_the_same_id_is_another_pipeline(self, tmp_path):
        catalog_dir = _make_minimal_catalog(tmp_path / "catalog", {"my_pipeline": {}})
        first = _make_minimal_pipeline(tmp_path / "a" / "my_pipeline")
        second = _make_minimal_pipeline(tmp_path / "b" / "my_pipeline")
        result = self._add(catalog_dir, first, second)
        assert result.exit_code == 0, result.output
        pipelines = _read_catalog(catalog_dir)["pipelines"]
        assert pipelines["my_pipeline"] == {"path": "../a/my_pipeline"}
        assert pipelines["my_pipeline_2"] == {"path": "../b/my_pipeline"}


class TestAHomeReachedThroughALink:
    """Found by a new-user test: with the home folder reached through a link (a Linux cluster's home,
    a moved macOS home, /var on macOS), the global catalog's path was worked out from the link and
    read back from the folder it leads to, and named no folder."""

    def test_what_add_writes_is_where_the_pipeline_is(self, tmp_path, monkeypatch):
        real = tmp_path / "volumes" / "users" / "real-home"
        real.mkdir(parents=True)
        link = tmp_path / "link-home"
        link.symlink_to(real)
        monkeypatch.setenv("HOME", str(link))
        monkeypatch.setenv("USERPROFILE", str(link))  # Windows reads home from here
        assert Path.home() == link and Path.home().resolve() == real
        pipeline_dir = _make_minimal_pipeline(tmp_path / "first_pipeline")
        runner = CliRunner()
        assert runner.invoke(main, ["catalog", "init", "--title", "Mine"]).exit_code == 0
        assert (link / ".chartbook" / "chartbook.toml").is_file()

        result = runner.invoke(main, ["catalog", "add", str(pipeline_dir)])

        assert result.exit_code == 0, result.output
        written = _read_catalog(link / ".chartbook")["pipelines"]["first_pipeline"]["path"]
        assert (real / ".chartbook" / written).resolve() == pipeline_dir.resolve()
        listed = runner.invoke(main, ["ls"])
        assert listed.exit_code == 0, listed.output
        assert "[pipeline] first_pipeline: Test Pipeline" in listed.output

    def test_a_path_written_from_the_link_is_still_read(self, tmp_path):
        """Found by a review: an entry an older `catalog add` wrote from the folder as named (and
        what `realpath` on Windows makes of `..` under a junction) named no folder once paths were
        read from the resolved one. When that finds no chartbook.toml, the path is read as written."""
        import os

        from chartbook.manifest import load_manifest

        real = tmp_path / "volumes" / "users" / "real-home"
        (real / ".chartbook").mkdir(parents=True)
        link = tmp_path / "link-home"
        link.symlink_to(real)
        pipeline_dir = _make_minimal_pipeline(tmp_path / "first_pipeline")
        written = os.path.relpath(pipeline_dir, link / ".chartbook")  # from the link, as the old add did
        _make_minimal_catalog(link / ".chartbook", {"first_pipeline": {"path": written}})
        loaded = load_manifest(link / ".chartbook")
        assert Path(loaded["pipelines"]["first_pipeline"]["pipeline_base_dir"]) == pipeline_dir.resolve()

    def test_and_by_the_commands_however_the_catalog_is_named(self, tmp_path, monkeypatch):
        """Found by a review: `ls --catalog`, and `check` in the catalog's folder or with
        --project-dir, read the catalog from its folder with the link followed, and did not find the
        entry; when they do, they say what to write instead."""
        import os

        real = tmp_path / "volumes" / "users" / "real-home"
        (real / ".chartbook").mkdir(parents=True)
        link = tmp_path / "link-home"
        link.symlink_to(real)
        pipeline_dir = _make_minimal_pipeline(tmp_path / "first_pipeline")
        written = os.path.relpath(pipeline_dir, link / ".chartbook")
        _make_minimal_catalog(link / ".chartbook", {"first_pipeline": {"path": written}})
        instead = Path(os.path.relpath(pipeline_dir.resolve(), (real / ".chartbook").resolve())).as_posix()
        runner = CliRunner()
        listed = runner.invoke(main, ["ls", "--catalog", str(link / ".chartbook")])
        assert listed.exit_code == 0, listed.output
        assert "[pipeline] first_pipeline: Test Pipeline" in listed.output
        checked = runner.invoke(main, ["check", "--project-dir", str(link / ".chartbook"), "--skip-outputs"])
        assert "No chartbook.toml found" not in checked.output
        assert f'Write path = "{instead}"' in checked.output
        monkeypatch.chdir(link / ".chartbook")
        monkeypatch.setenv("PWD", str(link / ".chartbook"))
        here = runner.invoke(main, ["check", "--skip-outputs"])
        assert "No chartbook.toml found" not in here.output and f'Write path = "{instead}"' in here.output
