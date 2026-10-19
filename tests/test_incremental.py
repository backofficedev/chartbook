"""Tests for incremental builds and watch mode."""

import json
import os
import time
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook import config, incremental
from chartbook.build_docs import generate_docs, get_docs_src_path
from chartbook.cli import main
from chartbook.incremental import (
    GITIGNORE_FILE,
    STATE_FILE,
    describe_changes,
    global_fingerprint,
    pipeline_fingerprint,
    pipeline_input_files,
    plan_build,
    prepare_build_tree,
    read_state,
    same_size_and_not_newer,
    snapshot_inputs,
    sync_tree,
    watch,
    write_state,
)
from chartbook.manifest import load_manifest
from tests.fixtures import create_catalog_project, create_pipeline_project

OPTIONS = {"size_threshold": 50, "strip_mathjax2": True}


def _edit_toml(project_dir: Path, edit) -> None:
    toml_path = project_dir / "chartbook.toml"
    with open(toml_path, "rb") as f:
        config_dict = tomli.load(f)
    edit(config_dict)
    with open(toml_path, "wb") as f:
        tomli_w.dump(config_dict, f)


def _bump(path: Path, seconds: float = 5) -> None:
    """Move a file's modification time forward, as an edit would."""
    stat = path.stat()
    os.utime(path, (stat.st_atime + seconds, stat.st_mtime + seconds))


def _fingerprint(project: Path) -> str:
    manifest = load_manifest(project)
    return pipeline_fingerprint(manifest["project"]["id"], manifest)


def _mtimes(directory: Path) -> dict:
    """Modification times of the Sphinx project's files (not our bookkeeping)."""
    return {
        p.relative_to(directory).as_posix(): p.stat().st_mtime_ns
        for p in directory.rglob("*")
        if p.is_file()
        and "_build" not in p.relative_to(directory).parts
        and p.name != STATE_FILE
    }


def _sources(build_dir: Path) -> dict:
    """The generated Sphinx project, without Sphinx's own output or our state.

    The index is compared without the time it was generated at, which two
    builds of the same thing do not share.
    """
    ignored = {STATE_FILE, GITIGNORE_FILE}
    sources = {
        p.relative_to(build_dir).as_posix(): p.read_bytes()
        for p in build_dir.rglob("*")
        if p.is_file()
        and "_build" not in p.relative_to(build_dir).parts
        and p.name not in ignored
    }
    if "index.json" in sources:
        index = json.loads(sources["index.json"])
        index.pop("generated_at")
        sources["index.json"] = json.dumps(index).encode()
    return sources


# --------------------------------------------------------------------------
# What counts as an input
# --------------------------------------------------------------------------


class TestPipelineInputFiles:
    def test_lists_everything_pages_are_made_from(self, pipeline_project_with_notes):
        project = pipeline_project_with_notes
        files = {
            p.relative_to(project).as_posix()
            for p in pipeline_input_files(load_manifest(project))
        }
        assert {
            "chartbook.toml",
            "README.md",
            "src/dummy.py",
            "docs_src/index.md",
            "docs_src/note1.md",
            "docs_src/dataframes/dataframe_0.md",
            "docs_src/charts/chart_0_0.md",
            "_data/notes_pipeline/dataframe_0.parquet",
            "_output/charts/chart_0_0.html",
        } <= files

    def test_glob_dataframe_lists_its_part_files(self, tmp_path):
        project = create_pipeline_project(tmp_path / "glob", use_glob_paths=True)
        files = [p.as_posix() for p in pipeline_input_files(load_manifest(project))]
        assert sum(f.endswith("data.parquet") for f in files) == 2

    def test_a_declared_file_that_does_not_exist_yet_is_listed(self, pipeline_project):
        def edit(config_dict):
            config_dict["dataframes"]["later"] = {
                "path": "./_data/later.parquet",
                "docs": "Built by a later step.",
            }

        _edit_toml(pipeline_project, edit)
        files = pipeline_input_files(load_manifest(pipeline_project))
        assert pipeline_project / "_data" / "later.parquet" in files

    def test_editor_and_os_noise_is_not_an_input(self, pipeline_project):
        for noise in (".DS_Store", ".chart.md.swp", "chart.md~"):
            (pipeline_project / "docs_src" / noise).write_text("x")
        (pipeline_project / "src" / "__pycache__").mkdir()
        (pipeline_project / "src" / "__pycache__" / "dummy.cpython-313.pyc").write_text("x")
        names = {p.name for p in pipeline_input_files(load_manifest(pipeline_project))}
        assert not names & {".DS_Store", ".chart.md.swp", "chart.md~", "dummy.cpython-313.pyc"}


class TestPipelineFingerprint:
    def test_stable_when_nothing_changes(self, pipeline_project):
        assert _fingerprint(pipeline_project) == _fingerprint(pipeline_project)

    @pytest.mark.parametrize(
        "relative",
        [
            "chartbook.toml",
            "README.md",
            "src/dummy.py",
            "docs_src/charts/chart_0_0.md",
            "_data/test_pipeline/dataframe_0.parquet",
            "_output/charts/chart_0_0.html",
        ],
    )
    def test_changes_when_an_input_is_modified(self, pipeline_project, relative):
        before = _fingerprint(pipeline_project)
        _bump(pipeline_project / relative)
        assert _fingerprint(pipeline_project) != before

    def test_changes_when_a_source_file_is_added_or_removed(self, pipeline_project):
        before = _fingerprint(pipeline_project)
        extra = pipeline_project / "docs_src" / "extra.md"
        extra.write_text("# Extra\n")
        added = _fingerprint(pipeline_project)
        assert added != before
        extra.unlink()
        assert _fingerprint(pipeline_project) == before

    def test_changes_when_a_declared_file_appears(self, pipeline_project):
        data_file = pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet"
        content = data_file.read_bytes()
        data_file.unlink()
        missing = _fingerprint(pipeline_project)
        data_file.write_bytes(content)
        assert _fingerprint(pipeline_project) != missing

    def test_unaffected_by_files_no_page_uses(self, pipeline_project):
        before = _fingerprint(pipeline_project)
        (pipeline_project / "_output" / "scratch.txt").write_text("not declared")
        (pipeline_project / "docs_src" / ".DS_Store").write_text("finder")
        assert _fingerprint(pipeline_project) == before

    def test_depends_on_the_pipeline_id(self, pipeline_project):
        manifest = load_manifest(pipeline_project)
        assert pipeline_fingerprint("a/x", manifest) != pipeline_fingerprint("b/x", manifest)


class TestGlobalFingerprint:
    def test_changes_with_options_and_theme(self, pipeline_project, tmp_path):
        manifest = load_manifest(pipeline_project)
        theme = tmp_path / "theme"
        theme.mkdir()
        (theme / "index.md").write_text("# {{ title }}\n")
        base = global_fingerprint(manifest, theme, OPTIONS)
        assert base == global_fingerprint(manifest, theme, OPTIONS)
        assert base != global_fingerprint(manifest, theme, {**OPTIONS, "size_threshold": 1})
        _bump(theme / "index.md")
        assert base != global_fingerprint(manifest, theme, OPTIONS)

    def test_changes_with_chartbook_version(self, pipeline_project, tmp_path, monkeypatch):
        manifest = load_manifest(pipeline_project)
        base = global_fingerprint(manifest, tmp_path, OPTIONS)
        monkeypatch.setattr(incremental, "__version__", "99.0.0")
        assert base != global_fingerprint(manifest, tmp_path, OPTIONS)

    def test_changes_when_sphinx_or_a_theme_is_upgraded(
        self, pipeline_project, tmp_path, monkeypatch
    ):
        manifest = load_manifest(pipeline_project)
        base = global_fingerprint(manifest, tmp_path, OPTIONS)
        versions = dict(incremental._rendering_versions())
        assert versions["sphinx"] and versions["ablog"]
        versions["sphinx"] = "99.0"
        monkeypatch.setattr(incremental, "_rendering_versions", lambda: versions)
        assert base != global_fingerprint(manifest, tmp_path, OPTIONS)


# --------------------------------------------------------------------------
# Syncing one tree into another
# --------------------------------------------------------------------------


class TestSyncTree:
    def _tree(self, root: Path, files: dict) -> Path:
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return root

    def test_writes_new_and_changed_files_and_leaves_identical_ones(self, tmp_path):
        source = self._tree(tmp_path / "src", {"a.md": "A", "b.md": "B2", "d/c.md": "C"})
        destination = self._tree(tmp_path / "dst", {"a.md": "A", "b.md": "B1"})
        old = time.time() - 1000
        os.utime(destination / "a.md", (old, old))
        untouched = (destination / "a.md").stat().st_mtime_ns

        result = sync_tree(source, destination)

        assert sorted(p.as_posix() for p in result.written) == ["b.md", "d/c.md"]
        assert result.unchanged == 1
        assert (destination / "b.md").read_text() == "B2"
        assert (destination / "d" / "c.md").read_text() == "C"
        # The identical file keeps its modification time: nothing re-reads it
        assert (destination / "a.md").stat().st_mtime_ns == untouched

    def test_deletes_what_the_source_no_longer_has(self, tmp_path):
        source = self._tree(tmp_path / "src", {"a.md": "A"})
        destination = self._tree(
            tmp_path / "dst", {"a.md": "A", "gone.md": "x", "old/deep/page.md": "x"}
        )
        result = sync_tree(source, destination)
        assert sorted(p.as_posix() for p in result.deleted) == ["gone.md", "old/deep/page.md"]
        assert not (destination / "old").exists()
        assert (destination / "a.md").exists()

    def test_preserved_paths_survive(self, tmp_path):
        source = self._tree(tmp_path / "src", {"index.md": "I"})
        destination = self._tree(
            tmp_path / "dst",
            {
                "_build/html/index.html": "<html>",
                "cb/dataframes/kept/df.md": "kept",
                "cb/charts/kept.chart.md": "kept",
                "cb/charts/dropped.chart.md": "dropped",
                "state.json": "{}",
            },
        )
        result = sync_tree(
            source,
            destination,
            preserve=[
                Path("_build"),
                Path("cb/dataframes/kept"),
                Path("cb/charts/kept.chart.md"),
                Path("state.json"),
            ],
        )
        assert [p.as_posix() for p in result.deleted] == ["cb/charts/dropped.chart.md"]
        assert (destination / "_build" / "html" / "index.html").exists()
        assert (destination / "cb" / "dataframes" / "kept" / "df.md").exists()
        assert (destination / "cb" / "charts" / "kept.chart.md").exists()

    def test_reports_whether_the_set_of_pages_changed(self, tmp_path):
        source = self._tree(tmp_path / "src", {"a.md": "A2", "_static/x.css": "c"})
        destination = self._tree(tmp_path / "dst", {"a.md": "A1"})
        edited = sync_tree(source, destination)
        # One page edited and a stylesheet added: the same pages as before
        assert [p.as_posix() for p in edited.added] == ["_static/x.css"]
        assert not edited.pages_added_or_removed

        (source / "b.md").write_text("B")
        assert sync_tree(source, destination).pages_added_or_removed
        (source / "b.md").unlink()
        assert sync_tree(source, destination).pages_added_or_removed

    def test_hidden_files_are_synced_too(self, tmp_path):
        source = self._tree(tmp_path / "src", {".buildinfo": "x", "a.md": "A"})
        destination = tmp_path / "dst"
        sync_tree(source, destination)
        assert (destination / ".buildinfo").exists()

    def test_cheap_comparison_for_rendered_output(self, tmp_path):
        source = self._tree(tmp_path / "src", {"page.html": "<p>one</p>"})
        destination = tmp_path / "dst"
        first = sync_tree(source, destination, same=same_size_and_not_newer)
        assert len(first.written) == 1
        # Untouched since it was copied: not copied again
        second = sync_tree(source, destination, same=same_size_and_not_newer)
        assert second.written == [] and second.unchanged == 1
        # Re-rendered, even to the same size: copied again
        _bump(source / "page.html", seconds=60)
        third = sync_tree(source, destination, same=same_size_and_not_newer)
        assert len(third.written) == 1


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


class TestPlanBuild:
    THEME = get_docs_src_path("catalog")

    def _plan(self, catalog, build_dir, **kwargs):
        return plan_build(
            load_manifest(catalog), build_dir, self.THEME, OPTIONS, **kwargs
        )

    def _pretend_built(self, catalog, build_dir):
        """Leave a state file and the pages a build would have written."""
        plan = self._plan(catalog, build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        for pipeline_id in plan.regenerate:
            for relative in (
                f"cb/dataframes/{pipeline_id}/dataframe_0.md",
                f"cb/charts/{pipeline_id}.chart_0_0.md",
            ):
                page = build_dir / relative
                page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text("page")
        write_state(build_dir, plan)

    def test_no_previous_build_is_fresh(self, catalog_project, tmp_path):
        plan = self._plan(catalog_project, tmp_path / "_docs")
        assert plan.fresh
        assert plan.reason == "no previous incremental build"
        assert plan.regenerate == ["pipeline_a", "pipeline_b"]
        assert plan.reuse == []

    def test_unchanged_pipelines_are_reused(self, catalog_project, tmp_path):
        build_dir = tmp_path / "_docs"
        self._pretend_built(catalog_project, build_dir)
        plan = self._plan(catalog_project, build_dir)
        assert not plan.fresh
        assert plan.regenerate == []
        assert plan.reuse == ["pipeline_a", "pipeline_b"]

    def test_only_the_changed_pipeline_is_regenerated(self, catalog_project, tmp_path):
        build_dir = tmp_path / "_docs"
        self._pretend_built(catalog_project, build_dir)
        _bump(catalog_project / "pipelines" / "pipeline_b" / "docs_src" / "index.md")
        plan = self._plan(catalog_project, build_dir)
        assert plan.regenerate == ["pipeline_b"]
        assert plan.reuse == ["pipeline_a"]
        preserved = {p.as_posix() for p in plan.preserved_paths(load_manifest(catalog_project))}
        assert "cb/dataframes/pipeline_a" in preserved
        assert "cb/charts/pipeline_a.chart_0_0.md" in preserved
        assert not any("pipeline_b" in p for p in preserved)

    def test_missing_pages_force_regeneration(self, catalog_project, tmp_path):
        build_dir = tmp_path / "_docs"
        self._pretend_built(catalog_project, build_dir)
        (build_dir / "cb" / "charts" / "pipeline_a.chart_0_0.md").unlink()
        plan = self._plan(catalog_project, build_dir)
        assert plan.regenerate == ["pipeline_a"]

    def test_changed_options_make_the_build_fresh(self, catalog_project, tmp_path):
        build_dir = tmp_path / "_docs"
        self._pretend_built(catalog_project, build_dir)
        plan = plan_build(
            load_manifest(catalog_project),
            build_dir,
            self.THEME,
            {**OPTIONS, "strip_mathjax2": False},
        )
        assert plan.fresh
        assert "build options changed" in plan.reason

    def test_skipped_pipelines_are_neither_regenerated_nor_reused(
        self, catalog_project, tmp_path
    ):
        build_dir = tmp_path / "_docs"
        self._pretend_built(catalog_project, build_dir)
        plan = self._plan(catalog_project, build_dir, skip_pipelines={"pipeline_a"})
        assert plan.reuse == ["pipeline_b"]
        assert plan.regenerate == []
        assert "pipeline_a" not in plan.fingerprints

    def test_unreadable_or_outdated_state_is_ignored(self, tmp_path):
        assert read_state(tmp_path) is None
        (tmp_path / STATE_FILE).write_text("not json")
        assert read_state(tmp_path) is None
        (tmp_path / STATE_FILE).write_text('{"version": 0, "global": "x"}')
        assert read_state(tmp_path) is None


class TestPrepareBuildTree:
    def test_creates_the_directory_and_keeps_it_out_of_git(self, tmp_path):
        build_dir = tmp_path / "_docs"
        prepare_build_tree(build_dir, fresh=True)
        assert (build_dir / GITIGNORE_FILE).read_text() == "*\n"

    def test_fresh_build_empties_an_old_build_tree(self, tmp_path):
        build_dir = tmp_path / "_docs"
        build_dir.mkdir()
        (build_dir / "conf.py").write_text("")
        (build_dir / "index.md").write_text("")
        (build_dir / "stale.md").write_text("")
        prepare_build_tree(build_dir, fresh=True)
        assert not (build_dir / "stale.md").exists()

    def test_kept_tree_is_left_alone_when_not_fresh(self, tmp_path):
        build_dir = tmp_path / "_docs"
        build_dir.mkdir()
        (build_dir / STATE_FILE).write_text("{}")
        (build_dir / "page.md").write_text("kept")
        prepare_build_tree(build_dir, fresh=False)
        assert (build_dir / "page.md").read_text() == "kept"

    def test_refuses_a_directory_that_is_not_a_build_tree(self, tmp_path):
        precious = tmp_path / "thesis"
        precious.mkdir()
        (precious / "chapter1.tex").write_text("years of work")
        with pytest.raises(ValueError, match="not a ChartBook build directory"):
            prepare_build_tree(precious, fresh=True)
        assert (precious / "chapter1.tex").read_text() == "years of work"


# --------------------------------------------------------------------------
# Whole builds
# --------------------------------------------------------------------------


def _build(project: Path, **kwargs):
    return generate_docs(
        output_dir=project / "docs",
        project_dir=project,
        _docs_dir=project / "_docs",
        temp_docs_src_dir=project / "_docs_src",
        incremental=True,
        **kwargs,
    )


class TestIncrementalBuild:
    @pytest.mark.parametrize("theme", ["pipeline", "catalog"])
    def test_second_build_redoes_nothing(
        self, theme, pipeline_project, catalog_project, monkeypatch
    ):
        project = pipeline_project if theme == "pipeline" else catalog_project
        monkeypatch.chdir(project)

        first = _build(project)
        assert first.fresh
        assert first.regenerated and not first.reused
        assert first.pages_read > 0
        assert (project / "docs" / "index.html").is_file()
        assert (project / "docs" / ".nojekyll").is_file()

        sources_before = _mtimes(project / "_docs")
        second = _build(project)

        assert not second.fresh
        assert second.regenerated == []
        assert second.reused == first.regenerated
        assert second.sources_written == 0
        assert second.sources_deleted == 0
        assert _mtimes(project / "_docs") == sources_before
        # With no source changed and the last render good, Sphinx is not run
        assert not second.rendered
        assert second.pages_read == 0
        assert "nothing to render" in second.describe()

    @pytest.mark.parametrize("theme", ["pipeline", "catalog"])
    def test_sphinx_cache_survives_between_builds(
        self, theme, pipeline_project, catalog_project, monkeypatch
    ):
        """When Sphinx does run again, it re-reads only what changed.

        This is what breaks if anything alters the Sphinx configuration from
        one run to the next: Sphinx then discards its cache and reads every
        page again.
        """
        project = pipeline_project if theme == "pipeline" else catalog_project
        monkeypatch.chdir(project)
        first = _build(project)

        # Make Sphinx run again without changing any source
        import shutil

        shutil.rmtree(project / "_docs" / "_build" / "html")
        second = _build(project)

        assert second.rendered
        assert second.sources_written == 0
        assert second.pages_read == 0
        assert first.pages_read > 0
        assert (project / "docs" / "index.html").is_file()

    def test_failed_render_is_retried(self, pipeline_project, monkeypatch):
        from chartbook import build_docs

        monkeypatch.chdir(pipeline_project)
        real_sphinx = build_docs.run_sphinx_build

        def failing_sphinx(docs_dir):
            raise RuntimeError("Sphinx build failed:\nboom")

        monkeypatch.setattr(build_docs, "run_sphinx_build", failing_sphinx)
        with pytest.raises(RuntimeError, match="boom"):
            _build(pipeline_project)
        assert read_state(pipeline_project / "_docs")["rendered"] is False

        monkeypatch.setattr(build_docs, "run_sphinx_build", real_sphinx)
        retry = _build(pipeline_project)
        # Nothing to regenerate, but the render still owed is done
        assert retry.regenerated == []
        assert retry.sources_written == 0
        assert retry.rendered
        assert (pipeline_project / "docs" / "index.html").is_file()
        assert read_state(pipeline_project / "_docs")["rendered"] is True

    def test_deleted_output_is_restored_without_rendering(self, pipeline_project, monkeypatch):
        import shutil

        monkeypatch.chdir(pipeline_project)
        _build(pipeline_project)
        shutil.rmtree(pipeline_project / "docs")
        summary = _build(pipeline_project)
        assert not summary.rendered
        assert (pipeline_project / "docs" / "index.html").is_file()
        assert (pipeline_project / "docs" / ".nojekyll").is_file()

    def test_only_the_edited_pipeline_is_redone(self, catalog_project, monkeypatch):
        monkeypatch.chdir(catalog_project)
        _build(catalog_project)
        before = _mtimes(catalog_project / "_docs")

        write_up = (
            catalog_project / "pipelines" / "pipeline_b" / "docs_src" / "charts" / "chart_0_0.md"
        )
        write_up.write_text("# Chart\n\nA freshly rewritten explanation.\n")
        _bump(write_up)
        summary = _build(catalog_project)

        assert summary.regenerated == ["pipeline_b"]
        assert summary.reused == ["pipeline_a"]
        after = _mtimes(catalog_project / "_docs")
        touched = {name for name in after if after[name] != before.get(name)}
        assert "cb/charts/pipeline_b.chart_0_0.md" in touched
        assert not any("pipeline_a" in name for name in touched)
        assert summary.rendered
        assert 0 < summary.pages_read < len([n for n in after if n.endswith(".md")])
        html = (catalog_project / "docs" / "cb" / "charts" / "pipeline_b.chart_0_0.html")
        assert "A freshly rewritten explanation." in html.read_text()

    def test_editing_one_write_up_re_renders_one_asset_page(
        self, pipeline_project_multi_dataframes, monkeypatch
    ):
        """Within a pipeline, an edit touches the page it is about, not all of them."""
        project = pipeline_project_multi_dataframes
        monkeypatch.chdir(project)
        _build(project)
        before = _mtimes(project / "_docs")

        write_up = project / "docs_src" / "charts" / "chart_1_0.md"
        write_up.write_text("# Chart\n\nOnly this chart's text changed.\n")
        _bump(write_up)
        summary = _build(project)

        after = _mtimes(project / "_docs")
        touched = sorted(name for name in after if after[name] != before.get(name))
        # The chart's own page, and the front page that dates the code; and the
        # index, since the write-up's hash is in it, with the hash cache
        assert touched == [".chartbook-hash-cache.json", "cb/charts/multi_df.chart_1_0.md", "index.json", "index.md"]
        assert summary.sources_written == 2
        assert summary.pages_read == 2

    def test_refreshed_data_is_picked_up(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        _build(pipeline_project)
        page = pipeline_project / "_docs" / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.md"
        before = page.read_text()
        _bump(pipeline_project / "_data" / "test_pipeline" / "dataframe_0.parquet", 3600)
        summary = _build(pipeline_project)
        assert summary.regenerated == ["test_pipeline"]
        assert page.read_text() != before

    def test_removed_chart_loses_its_page(self, pipeline_project_multi_dataframes, monkeypatch):
        project = pipeline_project_multi_dataframes
        monkeypatch.chdir(project)
        _build(project)
        page = project / "_docs" / "cb" / "charts" / "multi_df.chart_1_1.md"
        html = project / "docs" / "cb" / "charts" / "multi_df.chart_1_1.html"
        assert page.is_file() and html.is_file()

        _edit_toml(project, lambda c: c["charts"].pop("chart_1_1"))
        summary = _build(project)

        assert summary.sources_deleted >= 1
        assert not page.exists()
        assert not html.exists()
        assert (project / "_docs" / "cb" / "charts" / "multi_df.chart_1_0.md").is_file()

    def test_added_chart_appears_and_nothing_is_reread_for_it(
        self, pipeline_project_multi_dataframes, monkeypatch
    ):
        """A new page redraws every page's navigation, from Sphinx's cache."""
        project = pipeline_project_multi_dataframes
        monkeypatch.chdir(project)
        _build(project)
        untouched = project / "docs" / "cb" / "dataframes" / "multi_df" / "dataframe_1.html"
        rendered_before = untouched.stat().st_mtime_ns

        def edit(config_dict):
            config_dict["charts"]["chart_new"] = dict(config_dict["charts"]["chart_0_0"])

        _edit_toml(project, edit)
        summary = _build(project)

        assert (project / "docs" / "cb" / "charts" / "multi_df.chart_new.html").is_file()
        # Every page was written again, so its navigation is current...
        assert untouched.stat().st_mtime_ns > rendered_before
        # ...but only the pages whose source changed were read again
        assert summary.pages_read <= summary.sources_written

    def test_removed_pipeline_loses_its_pages(self, catalog_project, monkeypatch):
        monkeypatch.chdir(catalog_project)
        _build(catalog_project)
        assert (catalog_project / "_docs" / "cb" / "dataframes" / "pipeline_b").is_dir()

        _edit_toml(catalog_project, lambda c: c["pipelines"].pop("pipeline_b"))
        summary = _build(catalog_project)

        assert summary.reused == ["pipeline_a"]
        assert not (catalog_project / "_docs" / "cb" / "dataframes" / "pipeline_b").exists()
        assert not list((catalog_project / "_docs" / "cb" / "charts").glob("pipeline_b.*"))
        assert not (catalog_project / "docs" / "cb" / "dataframes" / "pipeline_b").exists()

    def test_result_matches_a_clean_build(self, tmp_path, monkeypatch):
        """After a series of edits, the kept project equals one built from nothing."""
        catalog = create_catalog_project(tmp_path / "cat", pipeline_ids=["pa", "pb", "pc"])
        monkeypatch.chdir(catalog)
        _build(catalog)
        # An edit, a refreshed data file, a removed chart, and a removed pipeline
        (catalog / "pipelines" / "pa" / "docs_src" / "dataframes" / "dataframe_0.md").write_text(
            "# Dataframe\n\nRewritten.\n"
        )
        _bump(catalog / "pipelines" / "pa" / "docs_src" / "dataframes" / "dataframe_0.md")
        _bump(catalog / "pipelines" / "pb" / "_data" / "pb" / "dataframe_0.parquet", 3600)
        _edit_toml(catalog, lambda c: c["pipelines"].pop("pc"))
        incremental_summary = _build(catalog)
        assert sorted(incremental_summary.regenerated) == ["pa", "pb"]

        generate_docs(
            output_dir=catalog / "docs_clean",
            project_dir=catalog,
            _docs_dir=catalog / "_docs_clean",
            temp_docs_src_dir=catalog / "_docs_src",
            keep_build_dirs=True,
        )

        kept = _sources(catalog / "_docs")
        clean = _sources(catalog / "_docs_clean")
        assert sorted(kept) == sorted(clean)
        differing = [name for name in clean if kept[name] != clean[name]]
        assert differing == []

    def test_clean_build_still_leaves_nothing_behind(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        generate_docs(
            output_dir=pipeline_project / "docs",
            project_dir=pipeline_project,
            _docs_dir=pipeline_project / "_docs",
            temp_docs_src_dir=pipeline_project / "_docs_src",
        )
        assert not (pipeline_project / "_docs").exists()
        assert not (pipeline_project / "_docs_src").exists()

    def test_kept_tree_is_ignored_by_git_and_theme_copy_is_removed(
        self, pipeline_project, monkeypatch
    ):
        monkeypatch.chdir(pipeline_project)
        _build(pipeline_project)
        assert (pipeline_project / "_docs" / GITIGNORE_FILE).read_text() == "*\n"
        assert (pipeline_project / "_docs" / STATE_FILE).is_file()
        assert not (pipeline_project / "_docs_src").exists()

    def test_will_not_build_into_an_unrelated_directory(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        precious = pipeline_project / "thesis"
        precious.mkdir()
        (precious / "chapter1.tex").write_text("years of work")
        with pytest.raises(ValueError, match="not a ChartBook build directory"):
            generate_docs(
                output_dir=pipeline_project / "docs",
                project_dir=pipeline_project,
                _docs_dir=precious,
                temp_docs_src_dir=pipeline_project / "_docs_src",
                incremental=True,
            )
        assert (precious / "chapter1.tex").read_text() == "years of work"


# --------------------------------------------------------------------------
# Watching
# --------------------------------------------------------------------------


class TestSnapshot:
    def test_covers_every_pipeline_of_a_catalog(self, catalog_project):
        snapshot = snapshot_inputs(load_manifest(catalog_project), catalog_project)
        assert str(catalog_project / "chartbook.toml") in snapshot
        for pipeline_id in ("pipeline_a", "pipeline_b"):
            assert str(
                catalog_project / "pipelines" / pipeline_id / "docs_src" / "index.md"
            ) in snapshot

    def test_differs_after_an_edit_and_names_the_file(self, pipeline_project):
        before = snapshot_inputs(load_manifest(pipeline_project), pipeline_project)
        _bump(pipeline_project / "docs_src" / "charts" / "chart_0_0.md")
        after = snapshot_inputs(load_manifest(pipeline_project), pipeline_project)
        assert before != after
        assert describe_changes(before, after) == "chart_0_0.md"

    def test_long_lists_of_changes_are_summarized(self):
        before = {f"/p/file{i}.md": (1, 1) for i in range(6)}
        after = {path: (2, 1) for path in before}
        assert describe_changes(before, after) == "file0.md, file1.md, file2.md and 3 more"


class TestWatch:
    def _run(self, states, build=None, max_polls=None):
        """Drive watch() through a scripted sequence of input snapshots."""
        states = iter(states)
        builds, lines = [], []

        def default_build():
            builds.append("built")

        count = watch(
            build or default_build,
            snapshot=lambda: next(states),
            interval=0.5,
            echo=lines.append,
            sleep=lambda seconds: None,
            max_polls=max_polls,
        )
        return count, builds, lines

    def test_builds_once_then_only_when_inputs_change(self):
        a, b = {"f": (1, 1)}, {"f": (2, 1)}
        count, builds, lines = self._run([a, a, a, b, b, b], max_polls=5)
        assert count == 2
        assert len(builds) == 2
        assert any(line.startswith("Watching for changes every 0.5s") for line in lines)
        assert "Changed: f. Rebuilding..." in lines

    def test_every_change_gets_a_rebuild(self):
        states = [{"f": (i, 1)} for i in (1, 2, 3, 4)]
        count, builds, _ = self._run(states, max_polls=3)
        assert count == 4 and len(builds) == 4

    def test_keeps_watching_after_a_failed_build(self):
        attempts = []

        def flaky_build():
            attempts.append(len(attempts))
            if len(attempts) == 2:
                raise ValueError("chartbook.toml: unexpected end of file")
            if len(attempts) == 3:
                raise SystemExit(1)

        states = [{"f": (i, 1)} for i in (1, 2, 3, 4)]
        count, _, lines = self._run(states, build=flaky_build, max_polls=3)
        assert count == 4
        assert "Build failed: chartbook.toml: unexpected end of file. Still watching." in lines
        assert "Build failed. Still watching." in lines
        assert sum(line.startswith("Built in ") for line in lines) == 2

    def test_a_manifest_caught_mid_edit_does_not_stop_the_watch(self):
        calls = {"n": 0}

        def snapshot():
            calls["n"] += 1
            if calls["n"] in (2, 3):
                raise ValueError("chartbook.toml: invalid TOML")
            return {"f": (1 if calls["n"] < 4 else 2, 1)}

        builds, lines = [], []
        count = watch(
            lambda: builds.append(1),
            snapshot,
            echo=lines.append,
            sleep=lambda s: None,
            max_polls=4,
        )
        # Not rebuilt while unreadable; rebuilt once it loads again
        assert count == 2
        # ...and the reason is said once, not on every poll
        waiting = [line for line in lines if line.startswith("Cannot read the project")]
        assert waiting == [
            "Cannot read the project: chartbook.toml: invalid TOML. "
            "Waiting for it to be fixed."
        ]

    def test_ctrl_c_stops_cleanly(self):
        def interrupted_sleep(seconds):
            raise KeyboardInterrupt

        lines = []
        count = watch(
            lambda: None,
            snapshot=lambda: {},
            echo=lines.append,
            sleep=interrupted_sleep,
        )
        assert count == 1
        assert lines[-1] == "Stopped watching."


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


class TestCommands:
    def test_build_incremental_reports_what_it_redid(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        runner = CliRunner()
        first = runner.invoke(main, ["docs", "generate", "--incremental", "-f"])
        assert first.exit_code == 0, first.output
        assert "Full build (no previous incremental build): regenerated 1 of 1" in first.output
        assert (pipeline_project / "_docs" / STATE_FILE).is_file()

        second = runner.invoke(main, ["docs", "generate", "--incremental", "-f"])
        assert second.exit_code == 0, second.output
        assert "Incremental build: regenerated 0 of 1 pipeline(s)" in second.output
        assert "0 source file(s) changed, 0 removed" in second.output
        assert "Successfully generated documentation" in second.output

    def test_plain_build_is_still_a_clean_build(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "generate", "-f"])
        assert result.exit_code == 0, result.output
        assert "Incremental build" not in result.output
        assert not (pipeline_project / "_docs").exists()

    def test_watch_builds_then_rebuilds_on_change(self, pipeline_project, monkeypatch):
        """The real command, driven for three polls with an edit before the second."""
        monkeypatch.chdir(pipeline_project)
        polls = {"n": 0}

        def fake_sleep(seconds):
            polls["n"] += 1
            if polls["n"] == 2:
                _bump(pipeline_project / "docs_src" / "charts" / "chart_0_0.md")
            if polls["n"] == 4:
                raise KeyboardInterrupt

        monkeypatch.setattr(incremental.time, "sleep", fake_sleep)
        result = CliRunner().invoke(main, ["docs", "generate", "--watch", "--watch-interval", "0.2", "-f"])

        assert result.exit_code == 0, result.output
        assert "Full build (no previous incremental build)" in result.output
        assert "Watching for changes every 0.2s" in result.output
        assert "Changed: chart_0_0.md. Rebuilding..." in result.output
        assert "Incremental build: regenerated 1 of 1 pipeline(s)" in result.output
        assert result.output.rstrip().endswith("Stopped watching.")
        assert result.output.count("Built in ") == 2

    def test_watch_interval_needs_watch(self, pipeline_project, monkeypatch):
        monkeypatch.chdir(pipeline_project)
        result = CliRunner().invoke(main, ["docs", "generate", "--watch-interval", "2", "-f"])
        assert result.exit_code == 2
        assert "--watch-interval only applies with --watch" in result.output

    def test_build_error_is_reported_cleanly(self, invalid_project_v1_format, monkeypatch):
        monkeypatch.chdir(invalid_project_v1_format)
        result = CliRunner().invoke(main, ["docs", "generate", "--incremental", "-f"])
        assert result.exit_code == 1
        assert "Error: " in result.output
        assert "v1 format" in result.output

    def test_catalog_build_incremental(self, catalog_project, tmp_path, monkeypatch):
        fake_dir = tmp_path / ".chartbook_incremental_tests"
        monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
        monkeypatch.setattr(
            config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
        )
        config.set_default_catalog_path(catalog_project)
        runner = CliRunner()

        # A catalog build is incremental without being asked
        first = runner.invoke(main, ["catalog", "generate", "-f"])
        assert first.exit_code == 0, first.output
        assert "regenerated 2 of 2 pipeline(s)" in first.output
        assert (catalog_project / "_docs" / STATE_FILE).is_file()

        second = runner.invoke(main, ["catalog", "generate", "-f"])
        assert second.exit_code == 0, second.output
        assert "Incremental build: regenerated 0 of 2 pipeline(s)" in second.output
        assert "nothing to render" in second.output
        assert "Catalog site generated" in second.output

        # --clean starts over, and leaves a fresh record for next time
        cleaned = runner.invoke(main, ["catalog", "generate", "-f", "--clean"])
        assert cleaned.exit_code == 0, cleaned.output
        assert "Full build (no previous incremental build)" in cleaned.output
        assert "regenerated 2 of 2 pipeline(s)" in cleaned.output
        after_clean = runner.invoke(main, ["catalog", "generate"])
        assert "Incremental build: regenerated 0 of 2 pipeline(s)" in after_clean.output

    def test_catalog_build_clean_leaves_unrelated_directories_alone(
        self, catalog_project, tmp_path, monkeypatch
    ):
        fake_dir = tmp_path / ".chartbook_incremental_tests"
        monkeypatch.setattr(config, "get_global_config_dir", lambda: fake_dir)
        monkeypatch.setattr(
            config, "get_global_settings_path", lambda: fake_dir / "settings.toml"
        )
        config.set_default_catalog_path(catalog_project)
        precious = catalog_project / "_docs"
        precious.mkdir()
        (precious / "notes.txt").write_text("not a build tree")

        result = CliRunner().invoke(main, ["catalog", "generate", "--clean"])

        assert result.exit_code == 1
        assert "not a ChartBook build directory" in result.output
        assert (precious / "notes.txt").read_text() == "not a build tree"
