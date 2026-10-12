"""Tests for name resolution: ``chartbook.resolve``, ``data.path()`` and
``chartbook path``."""

import runpy
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import data, resolve as resolve_module
from chartbook.cli import main
from chartbook.errors import AssetNotDeclaredError, ManifestNotFoundError
from chartbook.identity import UnsupportedRegistryError, UnsupportedRevisionError
from chartbook.resolve import (
    FileLocation,
    Location,
    UnsupportedReferenceError,
    find_manifest_dir,
    parse_local_ref,
    resolve,
)
from tests.fixtures import create_pipeline_project


def _edit_toml(project_dir: Path, edit) -> None:
    """Load a project's chartbook.toml, apply ``edit(config)``, write it back."""
    toml_path = project_dir / "chartbook.toml"
    with open(toml_path, "rb") as f:
        config = tomli.load(f)
    edit(config)
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)


@pytest.fixture
def project(pipeline_project_with_notes):
    """A pipeline with a dataframe, a chart and a note, as a resolved path."""
    return pipeline_project_with_notes.resolve()


class TestFindManifestDir:
    def test_finds_manifest_in_start_dir(self, project):
        assert find_manifest_dir(project) == project

    def test_walks_up_from_a_nested_directory(self, project):
        nested = project / "src" / "deep" / "deeper"
        nested.mkdir(parents=True)
        assert find_manifest_dir(nested) == project

    def test_defaults_to_cwd(self, project, monkeypatch):
        monkeypatch.chdir(project / "src")
        assert find_manifest_dir() == project

    def test_earlier_start_wins(self, tmp_path):
        first = create_pipeline_project(tmp_path / "first").resolve()
        second = create_pipeline_project(tmp_path / "second").resolve()
        assert find_manifest_dir(first / "src", second) == first

    def test_falls_through_to_a_later_start(self, project, tmp_path):
        outside = tmp_path / "not_a_project"
        outside.mkdir()
        assert find_manifest_dir(outside, project) == project

    def test_not_found_names_where_it_looked(self, tmp_path):
        outside = tmp_path / "not_a_project"
        outside.mkdir()
        with pytest.raises(ManifestNotFoundError) as excinfo:
            find_manifest_dir(outside)
        assert str(outside.resolve()) in str(excinfo.value)
        assert "No chartbook.toml found" in str(excinfo.value)
        assert isinstance(excinfo.value, FileNotFoundError)


class TestParseLocalRef:
    @pytest.mark.parametrize("ref", ["treasury_rates", "a.b-c_1", "  padded  "])
    def test_bare_names(self, ref):
        assert parse_local_ref(ref) == ref.strip()

    def test_revision_is_reserved(self):
        with pytest.raises(UnsupportedRevisionError, match="not yet supported"):
            parse_local_ref("treasury_rates@a1b2c3d")

    def test_series_is_reserved(self):
        with pytest.raises(UnsupportedReferenceError, match="not yet supported") as e:
            parse_local_ref("treasury_rates#dgs10")
        assert "'treasury_rates'" in str(e.value)

    @pytest.mark.parametrize(
        "ref",
        [
            "fed_yield_curve:treasury_rates",
            "ftsfr/fed_yield_curve:treasury_rates",
            "ftsfr/fed_yield_curve",
        ],
    )
    def test_cross_pipeline_is_reserved(self, ref):
        with pytest.raises(UnsupportedReferenceError, match="not yet supported"):
            parse_local_ref(ref)

    def test_registry_prefix_is_reserved(self):
        with pytest.raises(UnsupportedRegistryError, match="not yet supported") as e:
            parse_local_ref("charthub.example/ftsfr/fed_yield_curve:treasury_rates")
        assert "'charthub.example'" in str(e.value)

    @pytest.mark.parametrize("ref", ["", "two words", "semi;colon", "quo'te"])
    def test_invalid_names(self, ref):
        with pytest.raises(ValueError, match="Invalid asset name"):
            parse_local_ref(ref)

    def test_reserved_syntax_errors_are_value_errors(self):
        assert issubclass(UnsupportedReferenceError, ValueError)


class TestResolveLocal:
    def test_dataframe(self, project):
        location = resolve("dataframe_0", start_dirs=[project])
        assert isinstance(location, FileLocation)
        assert location.kind == "file"
        assert location.path == (
            project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        )

    def test_chart_and_note(self, project):
        chart = resolve("chart_0_0", start_dirs=[project])
        assert chart.path == project / "_output" / "charts" / "chart_0_0.html"
        note = resolve("note1", start_dirs=[project])
        assert note.path == project / "docs_src" / "note1.md"

    def test_notebook(self, project):
        def edit(config):
            config["notebooks"]["analysis"] = {"path": "_output/analysis.ipynb"}

        _edit_toml(project, edit)
        location = resolve("analysis", start_dirs=[project])
        assert location.path == project / "_output" / "analysis.ipynb"

    def test_resolves_from_a_subdirectory(self, project):
        location = resolve("dataframe_0", start_dirs=[project / "src"])
        assert location.path.is_relative_to(project)

    def test_file_need_not_exist(self, project):
        def edit(config):
            config["dataframes"]["not_built_yet"] = {
                "path": "./_data/not_built_yet.parquet",
                "docs": "Written by a later step.",
            }

        _edit_toml(project, edit)
        location = resolve("not_built_yet", start_dirs=[project])
        assert location.path == project / "_data" / "not_built_yet.parquet"
        assert not location.path.exists()

    def test_path_is_absolute_and_normalized(self, project):
        def edit(config):
            config["dataframes"]["dataframe_0"]["path"] = "./src/../_data/x.parquet"

        _edit_toml(project, edit)
        location = resolve("dataframe_0", start_dirs=[project])
        assert location.path == project / "_data" / "x.parquet"

    def test_absolute_declared_path_is_kept(self, project, tmp_path):
        elsewhere = tmp_path.resolve() / "shared" / "x.parquet"

        def edit(config):
            config["dataframes"]["dataframe_0"]["path"] = str(elsewhere)

        _edit_toml(project, edit)
        assert resolve("dataframe_0", start_dirs=[project]).path == elsewhere

    def test_glob_path_is_preserved(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        location = resolve("dataframe_0", start_dirs=[project])
        assert location.path.is_absolute()
        assert str(location.path).endswith("dataframe_0_hive/**/*.parquet")

    def test_declared_path_is_not_followed_through_a_symlink(self, project, tmp_path):
        """The declared path is the asset's location even if it is a link."""
        declared = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        store_object = tmp_path / "store_object.parquet"
        declared.rename(store_object)
        declared.symlink_to(store_object)
        assert resolve("dataframe_0", start_dirs=[project]).path == declared

    def test_undeclared_name_says_which_table_to_add(self, project):
        with pytest.raises(AssetNotDeclaredError) as excinfo:
            resolve("merged_rates", start_dirs=[project])
        message = str(excinfo.value)
        assert f"'merged_rates' is not declared in {project / 'chartbook.toml'}" in message
        assert "[dataframes.merged_rates]" in message
        assert 'path = "./_data/merged_rates.parquet"' in message
        assert "dataframes: dataframe_0" in message
        assert "charts: chart_0_0" in message
        assert excinfo.value.name == "merged_rates"
        assert excinfo.value.declared["notes"] == ["note1"]
        assert isinstance(excinfo.value, LookupError)

    def test_undeclared_name_suggests_a_close_match(self, project):
        with pytest.raises(AssetNotDeclaredError, match="Did you mean 'dataframe_0'"):
            resolve("dataframe_O", start_dirs=[project])

    def test_empty_manifest_declares_nothing(self, tmp_path):
        (tmp_path / "chartbook.toml").write_text("")
        with pytest.raises(AssetNotDeclaredError, match=r"Declared assets: \(none\)"):
            resolve("anything", start_dirs=[tmp_path])

    def test_name_declared_in_two_tables_is_ambiguous(self, project):
        def edit(config):
            config["charts"]["dataframe_0"] = dict(config["charts"]["chart_0_0"])

        _edit_toml(project, edit)
        with pytest.raises(ValueError, match="ambiguous") as excinfo:
            resolve("dataframe_0", start_dirs=[project])
        assert "[dataframes.dataframe_0] and [charts.dataframe_0]" in str(excinfo.value)

    def test_tables_can_be_restricted(self, project):
        with pytest.raises(AssetNotDeclaredError) as excinfo:
            resolve("chart_0_0", start_dirs=[project], tables=("dataframes",))
        assert list(excinfo.value.declared) == ["dataframes"]

    def test_entry_without_path(self, project):
        def edit(config):
            del config["dataframes"]["dataframe_0"]["path"]

        _edit_toml(project, edit)
        with pytest.raises(ValueError, match=r"\[dataframes.dataframe_0\].*has no 'path'"):
            resolve("dataframe_0", start_dirs=[project])

    def test_catalog_declares_no_assets(self, catalog_project):
        with pytest.raises(ValueError, match="is a catalog"):
            resolve("dataframe_0", start_dirs=[catalog_project])

    def test_no_enclosing_manifest(self, tmp_path):
        with pytest.raises(ManifestNotFoundError):
            resolve("dataframe_0", start_dirs=[tmp_path])

    def test_does_not_need_a_fully_valid_manifest(self, project):
        """Resolving reads the raw file, so unrelated mistakes do not break it.

        ``load_manifest`` rejects a chart with no ``dataframe`` key; a
        ``dodo.py`` asking for an unrelated path must still get it.
        """
        from chartbook.manifest import load_manifest

        def edit(config):
            del config["charts"]["chart_0_0"]["dataframe"]

        _edit_toml(project, edit)
        with pytest.raises(ValueError):
            load_manifest(project)
        assert resolve("dataframe_0", start_dirs=[project]).path.name == (
            "dataframe_0.parquet"
        )

    def test_manifest_is_parsed_once_while_unchanged(self, project, monkeypatch):
        resolve_module._raw_manifest_cache.clear()
        calls = []
        real_load = tomli.load

        def counting_load(f):
            calls.append(f.name)
            return real_load(f)

        monkeypatch.setattr(resolve_module.tomli, "load", counting_load)
        for name in ("dataframe_0", "chart_0_0", "note1", "dataframe_0"):
            resolve(name, start_dirs=[project])
        assert len(calls) == 1

    def test_edits_to_the_manifest_are_picked_up(self, project):
        before = resolve("dataframe_0", start_dirs=[project]).path

        def edit(config):
            config["dataframes"]["dataframe_0"]["path"] = "./_data/renamed_file.parquet"

        _edit_toml(project, edit)
        after = resolve("dataframe_0", start_dirs=[project]).path
        assert before != after
        assert after == project / "_data" / "renamed_file.parquet"


class TestResolveInCatalog:
    def test_catalog_reference_gives_a_file_location(self, catalog_project):
        location = resolve(
            "dataframe_0", pipeline="pipeline_a", catalog_path=catalog_project
        )
        assert isinstance(location, FileLocation)
        assert location.path.name == "dataframe_0.parquet"
        assert location.path.exists()

    def test_unknown_dataframe(self, catalog_project):
        with pytest.raises(KeyError, match="not found in pipeline"):
            resolve("nope", pipeline="pipeline_a", catalog_path=catalog_project)


class TestDataPath:
    def test_resolves_against_cwd(self, project, monkeypatch):
        monkeypatch.chdir(project / "src")
        result = data.path("dataframe_0")
        assert isinstance(result, Path)
        assert result == project / "_data" / "notes_pipeline" / "dataframe_0.parquet"

    def test_project_dir_overrides_cwd(self, project, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert data.path("chart_0_0", project_dir=project) == (
            project / "_output" / "charts" / "chart_0_0.html"
        )

    def test_calling_file_wins_over_cwd(self, tmp_path, monkeypatch):
        """A script finds its own pipeline even when run from another one."""
        mine = create_pipeline_project(tmp_path / "mine", pipeline_id="mine").resolve()
        other = create_pipeline_project(tmp_path / "other", pipeline_id="other").resolve()
        script = mine / "src" / "where.py"
        script.write_text(
            "from chartbook import data\nRESULT = data.path('dataframe_0')\n"
        )
        monkeypatch.chdir(other)
        result = runpy.run_path(str(script))["RESULT"]
        assert result == mine / "_data" / "mine" / "dataframe_0.parquet"

    def test_undeclared_name_raises_immediately(self, project, monkeypatch):
        monkeypatch.chdir(project)
        with pytest.raises(AssetNotDeclaredError, match=r"\[dataframes.merged_rates\]"):
            data.path("merged_rates")

    def test_cross_pipeline_reference_is_refused(self, project, monkeypatch):
        monkeypatch.chdir(project)
        with pytest.raises(UnsupportedReferenceError):
            data.path("other_pipeline:dataframe_0")

    def test_raises_for_a_location_that_is_not_a_file(self, project, monkeypatch):
        class TableLocation(Location):
            kind = "table"

        monkeypatch.setattr(data, "resolve", lambda *a, **k: TableLocation())
        with pytest.raises(TypeError, match="table-backed, so it has no file path"):
            data.path("dataframe_0", project_dir=project)


class TestSharedResolver:
    """path(), get_data_path() and load() each go through resolve()."""

    @pytest.fixture
    def spy(self, catalog_project, monkeypatch):
        calls = []
        real_resolve = data.resolve

        def spying_resolve(ref, **kwargs):
            calls.append((ref, kwargs))
            return real_resolve(ref, **kwargs)

        monkeypatch.setattr(data, "resolve", spying_resolve)
        return calls

    def test_get_data_path_delegates(self, spy, catalog_project):
        result = data.get_data_path("pipeline_a", "dataframe_0", catalog_project)
        assert result.name == "dataframe_0.parquet"
        assert spy == [
            ("dataframe_0", {"pipeline": "pipeline_a", "catalog_path": catalog_project})
        ]

    def test_load_calls_the_resolver_not_the_path_functions(
        self, spy, catalog_project, monkeypatch
    ):
        def must_not_be_called(*args, **kwargs):
            raise AssertionError("load() must call the resolver directly")

        monkeypatch.setattr(data, "path", must_not_be_called)
        monkeypatch.setattr(data, "get_data_path", must_not_be_called)
        frame = data.load("pipeline_a", "dataframe_0", catalog_path=catalog_project)
        assert frame.collect().height > 0
        assert len(spy) == 1

    def test_load_refuses_a_location_it_cannot_scan(self, catalog_project, monkeypatch):
        class TableLocation(Location):
            kind = "table"

        monkeypatch.setattr(data, "resolve", lambda *a, **k: TableLocation())
        with pytest.raises(NotImplementedError, match="table-backed"):
            data.load("pipeline_a", "dataframe_0", catalog_path=catalog_project)

    def test_get_data_path_raises_for_a_location_that_is_not_a_file(
        self, catalog_project, monkeypatch
    ):
        class QueryLocation(Location):
            kind = "query"

        monkeypatch.setattr(data, "resolve", lambda *a, **k: QueryLocation())
        with pytest.raises(TypeError, match="query-backed"):
            data.get_data_path("pipeline_a", "dataframe_0", catalog_project)


class TestPathCommand:
    def _invoke(self, *args):
        return CliRunner().invoke(main, ["path", *map(str, args)])

    def test_prints_only_the_path(self, project, monkeypatch):
        monkeypatch.chdir(project)
        result = self._invoke("dataframe_0")
        assert result.exit_code == 0, result.output
        expected = project / "_data" / "notes_pipeline" / "dataframe_0.parquet"
        assert result.stdout == f"{expected}\n"
        assert result.stderr == ""

    def test_matches_data_path(self, project, monkeypatch):
        monkeypatch.chdir(project / "src")
        for name in ("dataframe_0", "chart_0_0", "note1"):
            result = self._invoke(name)
            assert result.stdout.strip() == str(data.path(name, project_dir=project))

    def test_project_dir_option(self, project, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._invoke("chart_0_0", "--project-dir", project / "src")
        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == str(
            project / "_output" / "charts" / "chart_0_0.html"
        )

    def test_undeclared_name_fails_and_prints_nothing_to_stdout(
        self, project, monkeypatch
    ):
        monkeypatch.chdir(project)
        result = self._invoke("merged_rates")
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Error: 'merged_rates' is not declared" in result.stderr
        assert "[dataframes.merged_rates]" in result.stderr

    def test_cross_pipeline_reference_is_refused(self, project, monkeypatch):
        monkeypatch.chdir(project)
        result = self._invoke("other_pipeline:dataframe_0")
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "not yet supported" in result.stderr

    def test_outside_any_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = self._invoke("dataframe_0")
        assert result.exit_code == 1
        assert "No chartbook.toml found" in result.stderr

    def test_requires_a_reference(self):
        assert self._invoke().exit_code == 2


class TestScratch:
    def test_is_data_scratch_inside_the_pipeline_and_exists(self, project, monkeypatch):
        monkeypatch.chdir(project / "src")
        directory = data.scratch()
        assert directory == project / "_data" / "_scratch"
        assert directory.is_dir()
        (directory / "intermediate.parquet").write_text("throwaway")

    def test_ignores_itself_in_git(self, project):
        directory = data.scratch(project_dir=project)
        assert (directory / ".gitignore").read_text() == "*\n"

    def test_calling_again_changes_nothing(self, project):
        first = data.scratch(project_dir=project)
        (first / "kept.txt").write_text("still here")
        (first / ".gitignore").write_text("*\n!kept.txt\n")
        second = data.scratch(project_dir=project)
        assert second == first
        assert (second / "kept.txt").read_text() == "still here"
        assert (second / ".gitignore").read_text() == "*\n!kept.txt\n"

    def test_calling_file_wins_over_cwd(self, tmp_path, monkeypatch):
        mine = create_pipeline_project(tmp_path / "mine", pipeline_id="mine").resolve()
        other = create_pipeline_project(tmp_path / "other", pipeline_id="other").resolve()
        script = mine / "src" / "where.py"
        script.write_text("from chartbook import data\nRESULT = data.scratch()\n")
        monkeypatch.chdir(other)
        assert runpy.run_path(str(script))["RESULT"] == mine / "_data" / "_scratch"

    def test_outside_any_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ManifestNotFoundError):
            data.scratch()

    def test_scratch_files_are_not_assets_or_inputs(self, project):
        from chartbook.incremental import pipeline_fingerprint
        from chartbook.manifest import load_manifest

        manifest = load_manifest(project)
        before = pipeline_fingerprint(manifest["project"]["id"], manifest)
        (data.scratch(project_dir=project) / "intermediate.parquet").write_text("x")

        with pytest.raises(AssetNotDeclaredError):
            data.path("intermediate", project_dir=project)
        manifest = load_manifest(project)
        assert pipeline_fingerprint(manifest["project"]["id"], manifest) == before
