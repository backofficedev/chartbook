import re
from pathlib import Path
from unittest.mock import patch

import pytest
import tomli_w

from chartbook.identity import (
    UnsupportedRevisionError,
    derive_pipeline_id,
    normalize_ref_to_id,
    resolve_pipeline_ref,
)
from chartbook.manifest import (
    V1FormatError,
    get_pipeline_ids,
    get_pipeline_manifest,
    load_manifest,
    resolve_platform_path,
    resolve_project_type,
    validate_manifest_file,
)


class TestResolvePlatformPath:
    """Tests for resolve_platform_path function."""

    def test_string_input_returns_path(self):
        """String input should be converted directly to Path."""
        result = resolve_platform_path("/path/to/dir")
        assert result == Path("/path/to/dir")

    def test_string_input_relative_path(self):
        """Relative string paths should work."""
        result = resolve_platform_path("relative/path")
        assert result == Path("relative/path")

    @patch("platform.system")
    def test_dict_input_unix_platform(self, mock_system):
        """Dict input on Unix should return unix path."""
        mock_system.return_value = "Linux"
        path_input = {"windows": "C:/data", "unix": "/home/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("/home/data")

    @patch("platform.system")
    def test_dict_input_macos_uses_unix(self, mock_system):
        """Dict input on macOS should use unix path."""
        mock_system.return_value = "Darwin"
        path_input = {"windows": "C:/data", "unix": "/Users/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("/Users/data")

    @patch("platform.system")
    def test_dict_input_windows_platform(self, mock_system):
        """Dict input on Windows should return windows path."""
        mock_system.return_value = "Windows"
        path_input = {"windows": "C:/data", "unix": "/home/data"}

        result = resolve_platform_path(path_input)

        assert result == Path("C:/data")

    @patch("platform.system")
    def test_dict_missing_unix_on_unix_raises(self, mock_system):
        """Dict without unix key on Unix platform should raise ValueError."""
        mock_system.return_value = "Linux"
        path_input = {"windows": "C:/data"}

        with pytest.raises(ValueError, match="No path defined"):
            resolve_platform_path(path_input)

    @patch("platform.system")
    def test_dict_missing_windows_on_windows_raises(self, mock_system):
        """Dict without windows key on Windows platform should raise ValueError."""
        mock_system.return_value = "Windows"
        path_input = {"unix": "/home/data"}

        with pytest.raises(ValueError, match="No path defined"):
            resolve_platform_path(path_input)


class TestProjectTypeInference:
    """Truth table for resolve_project_type (see the v2 design doc)."""

    def test_no_type_no_registry_is_pipeline(self):
        assert resolve_project_type({"project": {"name": "x"}}) == "pipeline"

    def test_empty_file_is_pipeline(self):
        assert resolve_project_type({}) == "pipeline"

    def test_no_type_with_registry_is_catalog(self):
        raw = {"pipelines": {"a": {"path": "../a"}}}
        assert resolve_project_type(raw) == "catalog"

    def test_empty_registry_still_means_catalog(self):
        assert resolve_project_type({"pipelines": {}}) == "catalog"

    def test_explicit_type_wins_when_consistent(self):
        assert resolve_project_type({"project": {"type": "pipeline"}}) == "pipeline"
        assert resolve_project_type({"project": {"type": "catalog"}}) == "catalog"

    def test_invalid_type_value_raises(self):
        with pytest.raises(ValueError, match="invalid project.type"):
            resolve_project_type({"project": {"type": "bogus"}})

    def test_pipeline_type_with_registry_raises(self):
        raw = {"project": {"type": "pipeline"}, "pipelines": {"a": {"path": "../a"}}}
        with pytest.raises(ValueError, match="cannot contain a catalog registry"):
            resolve_project_type(raw)

    def test_catalog_type_with_entity_sections_raises(self):
        raw = {"project": {"type": "catalog"}, "charts": {"c": {"name": "C"}}}
        with pytest.raises(ValueError, match="cannot define its own charts"):
            resolve_project_type(raw)

    def test_ambiguous_structure_without_type_raises(self):
        raw = {
            "pipelines": {"a": {"path": "../a"}},
            "dataframes": {"d": {"name": "D"}},
        }
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_project_type(raw)

    def test_empty_entity_section_does_not_conflict(self):
        raw = {"project": {"type": "catalog"}, "charts": {}}
        assert resolve_project_type(raw) == "catalog"


class TestIdentity:
    """Tests for scoped pipeline IDs and reference resolution."""

    def test_normalize_bare_name(self):
        assert normalize_ref_to_id("crsp_treasury") == "crsp_treasury"

    def test_normalize_scoped_name(self):
        assert normalize_ref_to_id("ftsfr/crsp_treasury") == "ftsfr/crsp_treasury"

    def test_normalize_https_url(self):
        assert (
            normalize_ref_to_id("https://github.com/ftsfr/crsp_treasury")
            == "ftsfr/crsp_treasury"
        )

    def test_normalize_https_url_with_dot_git(self):
        assert (
            normalize_ref_to_id("https://github.com/ftsfr/crsp_treasury.git")
            == "ftsfr/crsp_treasury"
        )

    def test_normalize_ssh_url(self):
        assert (
            normalize_ref_to_id("git@github.com:ftsfr/crsp_treasury.git")
            == "ftsfr/crsp_treasury"
        )

    def test_rev_suffix_is_reserved(self):
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            normalize_ref_to_id("ftsfr/crsp_treasury@a1b2c3d")

    def test_invalid_id_rejected(self):
        with pytest.raises(ValueError, match="Invalid pipeline id"):
            normalize_ref_to_id("a/b/c")

    def test_derive_explicit_id_wins(self, tmp_path):
        project = {"id": "myscope/mything", "repo_url": "https://github.com/other/x"}
        assert derive_pipeline_id(project, tmp_path) == "myscope/mything"

    def test_derive_scope_from_repo_url(self, tmp_path):
        target = tmp_path / "crsp_treasury"
        target.mkdir()
        project = {"repo_url": "https://github.com/ftsfr/crsp_treasury"}
        assert derive_pipeline_id(project, target) == "ftsfr/crsp_treasury"

    def test_derive_bare_dirname_without_remote(self, tmp_path):
        target = tmp_path / "local_pipeline"
        target.mkdir()
        assert derive_pipeline_id({}, target) == "local_pipeline"

    def test_resolve_exact_scoped_key(self):
        keys = ["ftsfr/crsp_treasury", "ftsfr/cip"]
        assert resolve_pipeline_ref(keys, "ftsfr/crsp_treasury") == "ftsfr/crsp_treasury"

    def test_resolve_bare_name_unique(self):
        keys = ["ftsfr/crsp_treasury", "ftsfr/cip"]
        assert resolve_pipeline_ref(keys, "crsp_treasury") == "ftsfr/crsp_treasury"

    def test_resolve_url(self):
        keys = ["ftsfr/crsp_treasury"]
        assert (
            resolve_pipeline_ref(keys, "https://github.com/ftsfr/crsp_treasury")
            == "ftsfr/crsp_treasury"
        )

    def test_resolve_bare_name_ambiguous_raises(self):
        keys = ["ftsfr/crsp_treasury", "other/crsp_treasury"]
        with pytest.raises(KeyError, match="ambiguous"):
            resolve_pipeline_ref(keys, "crsp_treasury")

    def test_resolve_missing_raises_with_available(self):
        with pytest.raises(KeyError, match="Available pipelines"):
            resolve_pipeline_ref(["ftsfr/cip"], "nope")


class TestLoadManifestPipelineWorkflow:
    """Integration tests for reading pipeline manifest."""

    def test_load_manifest_pipeline_full_workflow(self, pipeline_project):
        """Test reading a complete pipeline project with dataframes and charts."""
        manifest = load_manifest(pipeline_project)

        # Verify resolved project metadata
        assert manifest["project"]["type"] == "pipeline"
        assert manifest["project"]["id"] == "test_pipeline"
        assert manifest["project"]["name"] == "Test Pipeline"
        assert manifest["project"]["maintainer"] == "Test Developer"

        # Verify dataframe paths resolved
        assert "dataframes" in manifest
        assert "dataframe_0" in manifest["dataframes"]
        df_manifest = manifest["dataframes"]["dataframe_0"]
        assert "_resolved_path" in df_manifest
        assert df_manifest["_resolved_path"].exists()

        # Verify charts linked to dataframes
        assert "linked_charts" in df_manifest
        assert "chart_0_0" in df_manifest["linked_charts"]

        # Verify tags normalized to Title Case
        assert "Test Tag" in df_manifest["tags"]
        assert "Uppercase Tag" in df_manifest["tags"]

        # Verify source modification time computed
        assert "source_last_modified_date" in manifest

        # Verify site URL generated
        assert manifest["project"]["site_url"].startswith("file://")

    def test_defaults_fill_in_minimal_manifest(self, tmp_path):
        """An almost-empty chartbook.toml is a valid pipeline manifest."""
        project_dir = tmp_path / "minimal_pipeline"
        project_dir.mkdir()
        (project_dir / "chartbook.toml").write_text("")

        manifest = load_manifest(project_dir)

        assert manifest["project"]["type"] == "pipeline"
        assert manifest["project"]["name"] == "minimal_pipeline"
        assert manifest["project"]["readme"] == "./README.md"
        assert manifest["project"]["copyright"]
        assert manifest["charts"] == {}
        assert manifest["dataframes"] == {}

    def test_unknown_project_key_warns(self, tmp_path):
        """Unrecognized [project] keys warn with a suggestion."""
        project_dir = tmp_path / "warns"
        project_dir.mkdir()
        with open(project_dir / "chartbook.toml", "wb") as f:
            tomli_w.dump({"project": {"nme": "Oops"}}, f)

        with pytest.warns(UserWarning, match="unknown key 'nme'.*'name'"):
            load_manifest(project_dir)

    def test_load_manifest_with_dataframes_and_charts_linking(
        self, pipeline_project_multi_dataframes
    ):
        """Test that charts are correctly linked to their dataframes."""
        manifest = load_manifest(pipeline_project_multi_dataframes)

        # Should have 2 dataframes
        assert len(manifest["dataframes"]) == 2

        # Dataframe 0 should have charts chart_0_0 and chart_0_1
        df0_charts = manifest["dataframes"]["dataframe_0"]["linked_charts"]
        assert len(df0_charts) == 2
        assert "chart_0_0" in df0_charts
        assert "chart_0_1" in df0_charts

        # Dataframe 1 should have charts chart_1_0 and chart_1_1
        df1_charts = manifest["dataframes"]["dataframe_1"]["linked_charts"]
        assert len(df1_charts) == 2
        assert "chart_1_0" in df1_charts
        assert "chart_1_1" in df1_charts

        # Verify chart manifest references correct dataframe
        assert manifest["charts"]["chart_0_0"]["dataframe"] == "dataframe_0"
        assert manifest["charts"]["chart_1_0"]["dataframe"] == "dataframe_1"

    def test_load_manifest_with_notes(self, pipeline_project_with_notes):
        """Test reading pipeline manifest that include notes section."""
        manifest = load_manifest(pipeline_project_with_notes)

        assert "notes" in manifest
        assert "note1" in manifest["notes"]

        note_manifest = manifest["notes"]["note1"]

        # Verify resolved path computed correctly
        assert "_resolved_path" in note_manifest
        assert note_manifest["_resolved_path"].name == "note1.md"
        assert note_manifest["_resolved_path"].exists()


class TestLoadManifestCatalogWorkflow:
    """Integration tests for reading catalog manifest with multiple pipelines."""

    def test_load_manifest_catalog_with_multiple_pipelines(self, catalog_project):
        """Test reading a catalog with multiple sub-pipelines."""
        manifest = load_manifest(catalog_project)

        # Verify resolved type
        assert manifest["project"]["type"] == "catalog"

        # Verify both pipelines discovered
        assert "pipelines" in manifest
        assert "pipeline_a" in manifest["pipelines"]
        assert "pipeline_b" in manifest["pipelines"]

        # Verify each sub-pipeline has full manifest, with the catalog key
        # as its authoritative id
        for pipeline_id in ["pipeline_a", "pipeline_b"]:
            pipeline_manifest = manifest["pipelines"][pipeline_id]
            assert pipeline_manifest["project"]["type"] == "pipeline"
            assert pipeline_manifest["project"]["id"] == pipeline_id
            assert "dataframes" in pipeline_manifest
            assert "charts" in pipeline_manifest

    def test_load_manifest_catalog_platform_paths(self, catalog_project_platform_paths):
        """Test catalog with platform-specific path dictionaries."""
        manifest = load_manifest(catalog_project_platform_paths)

        # Should resolve paths correctly for current platform
        assert "pipeline_x" in manifest["pipelines"]
        assert "pipeline_y" in manifest["pipelines"]

        # Each pipeline should have valid manifest
        for pid in ["pipeline_x", "pipeline_y"]:
            assert manifest["pipelines"][pid]["project"]["type"] == "pipeline"

    def test_catalog_gets_default_policy(self, catalog_project):
        """A catalog without [policy] resolves to the default warn policy."""
        manifest = load_manifest(catalog_project)

        assert manifest["policy"]["mode"] == "warn"
        assert "name" in manifest["policy"]["required"]["project"]
        assert "path" in manifest["policy"]["required"]["dataframes"]

    def test_get_pipeline_ids_catalog(self, catalog_project):
        """Test get_pipeline_ids returns all pipeline IDs for catalog."""
        manifest = load_manifest(catalog_project)
        pipeline_ids = get_pipeline_ids(manifest)

        assert len(pipeline_ids) == 2
        assert "pipeline_a" in pipeline_ids
        assert "pipeline_b" in pipeline_ids

    def test_get_pipeline_ids_pipeline(self, pipeline_project):
        """Test get_pipeline_ids returns single ID for pipeline type."""
        manifest = load_manifest(pipeline_project)
        pipeline_ids = get_pipeline_ids(manifest)

        assert len(pipeline_ids) == 1
        assert "test_pipeline" in pipeline_ids

    def test_get_pipeline_manifest_from_catalog(self, catalog_project):
        """Test extracting individual pipeline manifest from a catalog."""
        manifest = load_manifest(catalog_project)

        pipeline_a_manifest = get_pipeline_manifest(manifest, "pipeline_a")
        assert pipeline_a_manifest["project"]["id"] == "pipeline_a"
        assert "dataframes" in pipeline_a_manifest

        pipeline_b_manifest = get_pipeline_manifest(manifest, "pipeline_b")
        assert pipeline_b_manifest["project"]["id"] == "pipeline_b"


class TestSiteDirResolution:
    """Tests for site_dir resolution in pipeline manifest."""

    def test_site_dir_in_docs_src_resolves(self, pipeline_project_with_site_dir):
        """site_dir = './docs_src/site/' should resolve correctly."""
        manifest = load_manifest(pipeline_project_with_site_dir)
        resolved = manifest["project"]["_resolved_site_dir"]

        assert resolved is not None
        resolved_path = Path(resolved)
        assert resolved_path.is_dir()
        assert resolved_path.name == "site"
        assert (resolved_path / "index_toc.md").exists()
        assert (resolved_path / "sample_page.md").exists()

    def test_site_dir_top_level_still_works(self, pipeline_project_with_site_dir_top_level):
        """An explicit site_dir outside docs_src/ works."""
        manifest = load_manifest(pipeline_project_with_site_dir_top_level)
        resolved = manifest["project"]["_resolved_site_dir"]

        assert resolved is not None
        resolved_path = Path(resolved)
        assert resolved_path.is_dir()
        assert resolved_path.name == "site"
        assert (resolved_path / "index_toc.md").exists()

    def test_site_dir_cb_conflict_in_docs_src(self, pipeline_project_with_site_dir):
        """site_dir containing cb/ subdirectory should raise ValueError."""
        resolved = Path(
            load_manifest(pipeline_project_with_site_dir)["project"]["_resolved_site_dir"]
        )
        # Create a cb/ directory inside the site dir to trigger the conflict
        (resolved / "cb").mkdir()

        with pytest.raises(ValueError, match="cb/"):
            load_manifest(pipeline_project_with_site_dir)

    def test_no_site_dir_resolves_to_none(self, pipeline_project):
        """Without docs_src/site/ or an explicit key, _resolved_site_dir is None."""
        manifest = load_manifest(pipeline_project)
        assert manifest["project"]["_resolved_site_dir"] is None

    def test_default_site_dir_auto_detected(self, pipeline_project):
        """Creating docs_src/site/ enables site pages with no config."""
        site_dir = pipeline_project / "docs_src" / "site"
        site_dir.mkdir()
        (site_dir / "page.md").write_text("# Page\n")

        manifest = load_manifest(pipeline_project)
        resolved = manifest["project"]["_resolved_site_dir"]
        assert resolved is not None
        assert Path(resolved) == site_dir.resolve()

    def test_explicit_missing_site_dir_raises(self, pipeline_project):
        """An explicit site_dir that does not exist is an error."""
        import tomli

        toml_path = pipeline_project / "chartbook.toml"
        with open(toml_path, "rb") as f:
            raw = tomli.load(f)
        raw["project"]["site_dir"] = "./does_not_exist/"
        with open(toml_path, "wb") as f:
            tomli_w.dump(raw, f)

        with pytest.raises(ValueError, match="does not exist"):
            load_manifest(pipeline_project)


class TestLoadManifestValidationErrors:
    """Integration tests for manifest validation error handling."""

    def test_load_manifest_missing_chartbook_toml(self, invalid_project_missing_file):
        """Test that missing chartbook.toml raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_manifest(invalid_project_missing_file)

    def test_validate_missing_chartbook_toml(self, invalid_project_missing_file):
        """Test validate_manifest_file raises for missing file."""
        with pytest.raises(FileNotFoundError, match="No chartbook.toml found"):
            validate_manifest_file(invalid_project_missing_file)

    def test_load_manifest_invalid_project_type(self, invalid_project_invalid_type):
        """Test that invalid project type raises error."""
        with pytest.raises(ValueError, match="invalid project.type"):
            load_manifest(invalid_project_invalid_type)

    def test_load_manifest_v1_format_rejected(self, invalid_project_v1_format):
        """v1-format files raise a friendly migration error."""
        with pytest.raises(V1FormatError, match="migrate_toml_v2"):
            load_manifest(invalid_project_v1_format)

    def test_load_manifest_type_conflict(self, invalid_project_type_conflict):
        """Explicit pipeline type plus [pipelines] registry is a hard error."""
        with pytest.raises(ValueError, match="cannot contain a catalog registry"):
            load_manifest(invalid_project_type_conflict)


class TestCatalogMembers:
    """Tests for [pipelines] members auto-discovery, exclude, and disabled."""

    @staticmethod
    def _make_pipeline(root, dirname, project=None):
        d = root / dirname
        d.mkdir(parents=True)
        with open(d / "chartbook.toml", "wb") as f:
            tomli_w.dump({"project": project or {}}, f)
        return d

    @staticmethod
    def _make_catalog(root, pipelines_table):
        d = root / "catalog"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "chartbook.toml", "wb") as f:
            tomli_w.dump(
                {"project": {"type": "catalog", "name": "C"}, "pipelines": pipelines_table},
                f,
            )
        return d

    def test_glob_members_discovered(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        self._make_pipeline(tmp_path / "repos", "beta")
        catalog = self._make_catalog(tmp_path, {"members": ["../repos/*"]})

        manifest = load_manifest(catalog)
        assert sorted(manifest["pipelines"]) == ["alpha", "beta"]

    def test_glob_skips_non_pipeline_dirs_and_catalogs(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        (tmp_path / "repos" / "not_a_pipeline").mkdir(parents=True)
        other_catalog = tmp_path / "repos" / "other_catalog"
        other_catalog.mkdir()
        with open(other_catalog / "chartbook.toml", "wb") as f:
            tomli_w.dump({"project": {"type": "catalog"}, "pipelines": {}}, f)
        catalog = self._make_catalog(tmp_path, {"members": ["../repos/*"]})

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]

    def test_member_uses_explicit_id_from_pipeline(self, tmp_path):
        self._make_pipeline(
            tmp_path / "repos", "alpha", project={"id": "myscope/alpha"}
        )
        catalog = self._make_catalog(tmp_path, {"members": ["../repos/*"]})

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["myscope/alpha"]
        assert manifest["pipelines"]["myscope/alpha"]["project"]["id"] == "myscope/alpha"

    def test_exclude_removes_member(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        self._make_pipeline(tmp_path / "repos", "beta")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos/*"], "exclude": ["../repos/beta"]}
        )

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]

    def test_disabled_list_removes_member(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        self._make_pipeline(tmp_path / "repos", "beta")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos/*"], "disabled": ["beta"]}
        )

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]

    def test_disabled_unknown_id_warns_with_suggestion(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos/*"], "disabled": ["alpah"]}
        )

        with pytest.warns(UserWarning, match="'alpah'.*'alpha'"):
            manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]

    def test_string_shorthand_entry(self, tmp_path):
        alpha = self._make_pipeline(tmp_path / "repos", "alpha")
        catalog = self._make_catalog(tmp_path, {"alpha": str(alpha)})

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]

    def test_explicit_entry_coexists_with_members(self, tmp_path):
        self._make_pipeline(tmp_path / "repos", "alpha")
        gamma = self._make_pipeline(tmp_path / "elsewhere", "gamma")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos/*"], "gamma": str(gamma)}
        )

        manifest = load_manifest(catalog)
        assert sorted(manifest["pipelines"]) == ["alpha", "gamma"]

    def test_explicit_entry_overrides_member_for_same_dir(self, tmp_path):
        alpha = self._make_pipeline(tmp_path / "repos", "alpha")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos/*"], "renamed/alpha": str(alpha)}
        )

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["renamed/alpha"]

    def test_duplicate_derived_id_is_hard_error(self, tmp_path):
        self._make_pipeline(tmp_path / "repos_a", "alpha")
        self._make_pipeline(tmp_path / "repos_b", "alpha")
        catalog = self._make_catalog(
            tmp_path, {"members": ["../repos_a/*", "../repos_b/*"]}
        )

        with pytest.raises(ValueError, match=r"(?s)same pipeline ID 'alpha'.*To fix"):
            load_manifest(catalog)

    def test_explicit_member_path_missing_is_hard_error(self, tmp_path):
        catalog = self._make_catalog(tmp_path, {"members": ["../does_not_exist"]})

        with pytest.raises(ValueError, match=r"(?s)does not exist.*To fix"):
            load_manifest(catalog)

    def test_v1_member_is_hard_error_with_migrate_hint(self, tmp_path):
        d = tmp_path / "repos" / "old_style"
        d.mkdir(parents=True)
        with open(d / "chartbook.toml", "wb") as f:
            tomli_w.dump({"config": {"type": "pipeline"}}, f)
        catalog = self._make_catalog(tmp_path, {"members": ["../repos/*"]})

        with pytest.raises(ValueError, match=r"(?s)v1.*migrate_toml_v2"):
            load_manifest(catalog)

    def test_glob_matching_nothing_warns(self, tmp_path):
        (tmp_path / "repos").mkdir()
        catalog = self._make_catalog(tmp_path, {"members": ["../repos/*"]})

        with pytest.warns(UserWarning, match="matched no directories"):
            manifest = load_manifest(catalog)
        assert manifest["pipelines"] == {}

    def test_members_must_be_string_list(self, tmp_path):
        catalog = self._make_catalog(tmp_path, {"members": "../repos/*"})

        with pytest.raises(ValueError, match="must be an array of strings"):
            load_manifest(catalog)

    def test_catalog_does_not_discover_itself(self, tmp_path):
        self._make_pipeline(tmp_path, "alpha")
        catalog = self._make_catalog(tmp_path, {"members": ["../*"]})

        manifest = load_manifest(catalog)
        assert list(manifest["pipelines"]) == ["alpha"]


class TestWhatTheReleaseReviewFound:
    """Found by the review before 0.3.0: a field of the wrong type was read as
    something else (a string as its letters), or fell over later with a
    traceback. Nothing is guessed: the error names the file, the table and
    the key, and says what to write."""

    @staticmethod
    def _pipeline(tmp_path, project=None, **tables) -> Path:
        folder = tmp_path / "p"
        folder.mkdir(exist_ok=True)
        (folder / "chartbook.toml").write_text(tomli_w.dumps({"project": {"id": "p", **(project or {})}, **tables}))
        return folder

    def test_a_docs_path_that_is_not_a_string_is_named(self, tmp_path):
        """`chartbook check` and `chartbook docs` died on `.strip()` of the integer."""
        folder = self._pipeline(tmp_path, dataframes={"x": {"path": "./x.parquet", "docs_path": 5}})
        with pytest.raises(ValueError) as e:
            load_manifest(folder)
        assert str(e.value) == (
            f"{folder / 'chartbook.toml'}: [dataframes.x]: docs_path = 5 is an integer, and docs_path is a string. "
            'Write docs_path = "./docs_src/dataframes/x.md".'
        )

    @pytest.mark.parametrize(
        "table, entry, said",
        [
            ("notebooks", {"path": 5}, "[notebooks.x]: path = 5 is an integer, and path is a string. Write path = \"./_output/x.ipynb\"."),
            ("charts", {"path": True, "docs": "d", "dataframe": "d"}, "[charts.x]: path = True is a boolean, and path is a string. Write path = \"./_output/x.html\"."),
            ("dataframes", {"path": "./x.parquet", "docs": "d", "excel_path": [1]}, "[dataframes.x]: excel_path = [1] is an array, and excel_path is a string. Write excel_path = \"./_output/x.xlsx\"."),
            ("charts", {"path": "./x.html", "docs": 7, "dataframe": "d"}, "[charts.x]: docs = 7 is an integer, and docs is a string."),
            ("models", {"path": "./m.json", "docs": 7}, "[models.x]: docs = 7 is an integer, and docs is a string."),
        ],
    )
    def test_every_path_field_and_the_write_up_is_a_string(self, tmp_path, table, entry, said):
        folder = self._pipeline(tmp_path, **{table: {"x": entry}})
        with pytest.raises(ValueError, match=re.escape(said)) as e:
            load_manifest(folder)
        assert str(e.value).startswith(str(folder / "chartbook.toml"))

    def test_an_entry_that_is_not_a_table_is_said(self, tmp_path):
        folder = self._pipeline(tmp_path, dataframes={"x": "./x.parquet"})
        with pytest.raises(ValueError, match=re.escape("[dataframes.x] must be a table of the dataframe's fields, e.g. [dataframes.x] with a path = \"...\" under it; it is a string.")):
            load_manifest(folder)
        folder = self._pipeline(tmp_path, charts=5)
        with pytest.raises(ValueError, match=re.escape("[charts] must be a table of tables, one per chart, e.g. [charts.<name>] with a path = \"...\" under it; it is an integer.")):
            load_manifest(folder)

    def test_a_note_needs_a_path(self, tmp_path):
        """`[notes.x]` with no path was a raw KeyError('path'), which `check` printed as `Error: 'path'`."""
        folder = self._pipeline(tmp_path, notes={"x": {"name": "Methods"}})
        with pytest.raises(ValueError) as e:
            load_manifest(folder)
        assert str(e.value) == (
            f"{folder / 'chartbook.toml'}: [notes.x] has no 'path'. Say where the note's markdown file is: "
            'path = "./docs_src/x.md".'
        )
        folder = self._pipeline(tmp_path, notes={"x": {"path": 5}})
        with pytest.raises(ValueError, match=re.escape("[notes.x]: path = 5 is an integer, and path is a string. Write path = \"./docs_src/x.md\".")):
            load_manifest(folder)

    @pytest.mark.parametrize(
        "value, said",
        [
            ("description", "project = 'description' is a string, and project is a list of strings. Write project = [\"description\"]."),
            (5, "project = 5 is an integer, and project is a list of strings. Write project = [\"name\", \"description\"]."),
            ({"a": 1}, "project = {'a': 1} is a table, and project is a list of strings. Write project = [\"name\", \"description\"]."),
            (["name", 1], "project = ['name', 1] is an array with an item that is not a string, and project is a list of strings."),
        ],
    )
    def test_a_policy_list_is_a_list_of_field_names(self, tmp_path, value, said):
        """`project = "description"` was list()-ed into the required fields d, e, s, c, r, i, p, t, o, n."""
        folder = self._pipeline(tmp_path, policy={"required": {"project": value}})
        with pytest.raises(ValueError, match=re.escape(f"{folder / 'chartbook.toml'}: [policy.required]: {said}")):
            load_manifest(folder)

    @pytest.mark.parametrize(
        "tables, said",
        [
            ({"project": {"contributors": "Alice Smith"}}, "[project]: contributors = 'Alice Smith' is a string, and contributors is a list of strings. Write contributors = [\"Alice Smith\"]."),
            ({"project": {"os_compatibility": "Linux"}}, "[project]: os_compatibility = 'Linux' is a string, and os_compatibility is a list of strings. Write os_compatibility = [\"Linux\"]."),
            ({"dataframes": {"x": {"path": "./x.parquet", "docs": "d", "tags": "rates"}}}, "[dataframes.x]: tags = 'rates' is a string, and tags is a list of strings. Write tags = [\"rates\"]."),
            ({"dataframes": {"x": {"path": "./x.parquet", "docs": "d", "sources": "FRED"}}}, "[dataframes.x]: sources = 'FRED' is a string, and sources is a list of strings. Write sources = [\"FRED\"]."),
            ({"dataframes": {"x": {"path": "./x.parquet", "docs": "d", "providers": 5}}}, "[dataframes.x]: providers = 5 is an integer, and providers is a list of strings. Write providers = [\"Federal Reserve Board\"]."),
            ({"dataframes": {"x": {"path": "./x.parquet", "docs": "d", "provider_links": [1]}}}, "[dataframes.x]: provider_links = [1] is an array with an item that is not a string"),
            ({"charts": {"x": {"path": "./x.html", "docs": "d", "dataframe": "d", "tags": "Rates"}}}, "[charts.x]: tags = 'Rates' is a string"),
            ({"models": {"x": {"path": "./m.json", "tags": "ml"}}}, "[models.x]: tags = 'ml' is a string"),
        ],
    )
    def test_a_list_field_written_as_a_string_is_refused_not_read_as_its_letters(self, tmp_path, tables, said):
        """`contributors = "Alice Smith"` made the maintainer "A"; `tags = "rates"` the tags R, A, T, E, S."""
        folder = self._pipeline(tmp_path, **tables)
        with pytest.raises(ValueError, match=re.escape(said)) as e:
            load_manifest(folder)
        assert str(e.value).startswith(str(folder / "chartbook.toml"))

    def test_the_list_forms_still_load(self, tmp_path):
        folder = self._pipeline(
            tmp_path,
            project={"contributors": ["Alice Smith", "Bob"], "os_compatibility": ["Linux"]},
            dataframes={"x": {"path": "./x.parquet", "docs": "d", "tags": ["rates"], "sources": ["FRED"]}},
        )
        manifest = load_manifest(folder)
        assert manifest["project"]["maintainer"] == "Alice Smith"
        assert manifest["project"]["os_compatibility"] == ["Linux"]
        assert manifest["dataframes"]["x"]["tags"] == ["Rates"]

    @pytest.mark.parametrize(
        "project, said",
        [
            ({"readme": 5}, "[project]: readme = 5 is an integer, and readme is a string. Write readme = \"./README.md\"."),
            ({"logo": 5}, "[project]: logo = 5 is an integer, and logo is a string. Write logo = \"./docs_src/logo.png\"."),
            ({"favicon": True}, "[project]: favicon = True is a boolean, and favicon is a string."),
            ({"site_dir": ["docs"]}, "[project]: site_dir = ['docs'] is an array, and site_dir is a string. Write site_dir = \"./docs_src/site/\"."),
            ({"build": 5}, "[project]: build = 5 is an integer, and build is a string. Write build = \"doit\"."),
            ({"enable_data_download": "yes"}, "[project]: enable_data_download = 'yes' is a string, and enable_data_download is true or false. Write enable_data_download = true."),
        ],
    )
    def test_a_project_field_of_the_wrong_type_is_named(self, tmp_path, project, said):
        folder = self._pipeline(tmp_path, project=project)
        with pytest.raises(ValueError, match=re.escape(f"{folder / 'chartbook.toml'}: {said}")):
            load_manifest(folder)

    def test_a_syntax_error_names_the_file(self, tmp_path):
        """A catalog reads several manifests, and `Illegal character` alone said whose."""
        folder = tmp_path / "p"
        folder.mkdir()
        (folder / "chartbook.toml").write_text("this = [not toml\n")
        with pytest.raises(ValueError, match=re.escape(f"{folder / 'chartbook.toml'} is not valid TOML: ")):
            load_manifest(folder)
        with pytest.raises(ValueError, match="is not valid TOML"):
            validate_manifest_file(folder)
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text('[pipelines]\nbroken = { path = "../p" }\n')
        with pytest.raises(ValueError, match=re.escape(f"{folder / 'chartbook.toml'} is not valid TOML: ")):
            load_manifest(catalog)
        (catalog / "chartbook.toml").write_text('[pipelines]\nmembers = ["../p"]\n')
        with pytest.raises(ValueError, match=re.escape(f"catalog member {folder / 'chartbook.toml'} is not valid TOML: ")):
            load_manifest(catalog)

    def test_a_catalog_key_that_is_not_an_id_names_the_file_and_the_table(self, tmp_path):
        catalog = tmp_path / "catalog"
        catalog.mkdir()
        (catalog / "chartbook.toml").write_text('[pipelines]\n"acme/rates@v1" = { path = "../p" }\n')
        with pytest.raises(ValueError, match=re.escape(f"{catalog / 'chartbook.toml'}: [pipelines] 'acme/rates@v1': Invalid pipeline id 'acme/rates@v1'")):
            load_manifest(catalog)
