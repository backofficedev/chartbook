"""The Sphinx writer: a page from the index and the files it names, equal to the generator's."""

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from chartbook.writers.sphinx import SphinxWriter
from tests.test_model_versions import trained  # noqa: F401 - a fixture: two pipelines, a model trained on both


def _built(project: Path, monkeypatch) -> dict:
    """Build the site with the generator, keep the build directory, and read its full index."""
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs"])
    assert result.exit_code == 0, result.output
    return json.loads((project / "_docs" / "index.json").read_text())


_PAGES = {
    "Dataframe": ("dataframe_page_path", "dataframe_page"),
    "Chart": ("chart_page_path", "chart_page"),
    "Model": ("model_page_path", "model_page"),
    "Pipeline": ("pipeline_page_path", "pipeline_page"),
}

KINDS = ("Dataframe", "Chart", "Model", "Pipeline")


def _same_pages(writer: SphinxWriter, index: dict, build_dir: Path, kinds=KINDS) -> None:
    """Every page of the given kinds the generator wrote, the writer writes the same."""
    seen = 0
    for record in [r for r in index["records"] if r["kind"] in kinds]:
        path_of, page_of = _PAGES[record["kind"]]
        generated = (build_dir / getattr(writer, path_of)(record)).read_text()
        assert getattr(writer, page_of)(record["id"]) == generated, record["id"]
        seen += 1
    assert seen, f"no {kinds} pages to compare"


class TestTheBuildWritesTheSite:
    """`sitefiles.write_site()`: the writer's pages at their paths, and the files the index names beside them."""

    def test_an_incremental_rebuild_keeps_a_reused_pipelines_notes(self, pipeline_project_with_notes, monkeypatch):
        """Found by a reviewer: the first build-through-the-writer copied no file of a reused
        pipeline, and the incremental sync then deleted its notes while the front page, written
        on every build, still listed them. Notes are copied again for a reused pipeline."""
        project = pipeline_project_with_notes.resolve()
        monkeypatch.chdir(project)
        for _ in range(2):
            result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--incremental"])
            assert result.exit_code == 0, result.output
            assert (project / "_docs" / "cb" / "note1.md").is_file()
            assert (project / "docs" / "cb" / "note1.html").is_file()
            assert "cb/note1.md" in (project / "_docs" / "index.md").read_text()
        assert "nonexisting document" not in result.output

    def test_a_catalog_copies_no_notes(self, catalog_project, monkeypatch):
        """Found by a reviewer: the generator copied notes in the pipeline theme only (a catalog
        has no page that lists them, and two pipelines' notes of one name would collide at
        `cb/<name>.md`); the build does the same."""
        import tomli
        import tomli_w

        catalog = catalog_project.resolve()
        for pid in ("pipeline_a", "pipeline_b"):
            folder = catalog / "pipelines" / pid
            (folder / "docs_src" / "overview.md").write_text(f"# {pid}\n")
            config = tomli.loads((folder / "chartbook.toml").read_text())
            config["notes"] = {"overview": {"path": "docs_src/overview.md"}}
            (folder / "chartbook.toml").write_text(tomli_w.dumps(config))
        index = _built(catalog, monkeypatch)
        assert sum(1 for r in index["records"] if r["kind"] == "Note") == 2
        assert not (catalog / "_docs" / "cb" / "overview.md").exists()

    def test_a_project_in_a_folder_named_like_a_generated_one_still_gets_the_theme(self, tmp_path, monkeypatch):
        """Found by a reviewer (and true of the generator too): the theme files to leave out
        were matched against the whole path, so a project under a folder called `models`
        got no theme at all."""
        from tests.fixtures import create_pipeline_project

        project = create_pipeline_project(tmp_path / "models" / "p").resolve()
        index = _built(project, monkeypatch)
        assert (project / "_docs" / "conf.py").is_file() and index["records"]


def _same_catalog_pages(writer: SphinxWriter, build_dir: Path) -> None:
    paths = writer.catalog_page_paths()
    assert "index.md" in paths and "cb/diagnostics.md" in paths
    for page_path in paths:
        assert writer.catalog_page(page_path) == (build_dir / page_path).read_text(), page_path


class TestTheCatalogsOwnPages:
    def test_the_landing_page_and_the_lists(self, catalog_project, monkeypatch):
        index = _built(catalog_project, monkeypatch)
        (catalog,) = [r for r in index["records"] if r["kind"] == "Catalog"]
        assert catalog["location"] == {"kind": "path", "value": catalog_project.resolve().as_posix()}
        assert catalog["policy"]["required"]["dataframes"]  # the resolved policy, defaults filled
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog_project / "_docs_src")
        _same_catalog_pages(writer, catalog_project / "_docs")
        assert "cb/models.md" not in writer.catalog_page_paths()  # no pipeline declares a model
        page = writer.catalog_page("cb/dataframes.md")
        assert "dataframes/pipeline_a/dataframe_0.md\n" in page

    def test_the_diagnostics_page_is_a_comparison_the_writer_makes(self, catalog_project, monkeypatch):
        """Each record's declared fields against the Catalog record's policy, as the generator
        works out from the manifests (and writes as a CSV, which the build keeps doing)."""
        import tomli
        import tomli_w

        from tests.test_models import add_models

        catalog = catalog_project.resolve()
        config = tomli.loads((catalog / "chartbook.toml").read_text())
        config["policy"] = {"mode": "warn", "required": {"charts": ["name", "units"], "models": ["name", "docs"]}}
        (catalog / "chartbook.toml").write_text(tomli_w.dumps(config))
        add_models(catalog / "pipelines" / "pipeline_b")
        pipeline_a = tomli.loads((catalog / "pipelines" / "pipeline_a" / "chartbook.toml").read_text())
        pipeline_a["charts"]["chart_0_0"].pop("tags", None)
        pipeline_a["dataframes"]["dataframe_0"]["providers"] = []
        (catalog / "pipelines" / "pipeline_a" / "chartbook.toml").write_text(tomli_w.dumps(pipeline_a))
        index = _built(catalog, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog / "_docs_src")
        _same_catalog_pages(writer, catalog / "_docs")
        _same_pages(writer, index, catalog / "_docs")
        assert "cb/models.md" in writer.catalog_page_paths()
        page = writer.catalog_page("cb/diagnostics.md")
        assert "### Chart Fields (2 required)" in page and "### Model Fields" not in page
        rows = {
            (row["Object Type"], row["Pipeline"], row["Identifier"]): row
            for row in writer._diagnostics(next(r for r in index["records"] if r["kind"] == "Catalog"))
        }
        assert rows[("chart", "pipeline_a", "chart_0_0")]["Missing Fields"] == "units"
        assert "providers" in rows[("dataframe", "pipeline_a", "dataframe_0")]["Missing Fields"]
        assert "providers" not in rows[("dataframe", "pipeline_b", "dataframe_0")]["Missing Fields"]
        assert rows[("model", "pipeline_b", "encoder")]["Missing Fields"] == "name, docs"
        assert rows[("model", "pipeline_b", "forecaster")]["Metadata Complete"] is True
        assert [row["Pipeline"] for row in rows.values()] == sorted(row["Pipeline"] for row in rows.values())

    def test_a_policy_may_require_what_a_record_states_in_another_form(self, catalog_project, monkeypatch):
        """Found by a reviewer: a policy naming `readme`, `site_url`, `copyright`, `docs_path`,
        `linked_charts`, `series`, `source`, `metrics_path` or a blank inline write-up made the
        writer's rows differ from the generator's. Each is put back under the entry's name."""
        import duckdb
        import tomli
        import tomli_w

        from tests.test_models import add_models

        catalog = catalog_project.resolve()
        config = tomli.loads((catalog / "chartbook.toml").read_text())
        config["policy"] = {
            "required": {
                "project": ["name", "site_url", "readme", "copyright", "id", "type"],
                "dataframes": ["docs_path", "linked_charts", "series", "source", "path"],
                "charts": ["dataframe", "docs_path", "docs"],
                "models": ["metrics_path", "trained_on", "docs"],
            }
        }
        (catalog / "chartbook.toml").write_text(tomli_w.dumps(config))
        add_models(catalog / "pipelines" / "pipeline_b")
        b = catalog / "pipelines" / "pipeline_b"
        config_b = tomli.loads((b / "chartbook.toml").read_text())
        config_b["models"]["encoder"]["docs"] = "   "  # blank: missing on both sides
        config_b["sources"] = {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}}
        config_b["dataframes"]["curve"] = {"source": "local", "table": "curve", "docs": "A table.", "series": {"y": {"name": "Y"}}}
        (b / "chartbook.toml").write_text(tomli_w.dumps(config_b))
        (b / "_data").mkdir(exist_ok=True)
        con = duckdb.connect(str(b / "_data" / "local.duckdb"))
        con.sql("create table curve as select * from (values (date '2024-01-01', 1.0)) t(d, y)")
        con.close()
        index = _built(catalog, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog / "_docs_src")
        _same_catalog_pages(writer, catalog / "_docs")
        rows = {
            (row["Object Type"], row["Pipeline"], row["Identifier"]): row["Missing Fields"]
            for row in writer._diagnostics(next(r for r in index["records"] if r["kind"] == "Catalog"))
        }
        assert rows[("pipeline", "pipeline_a", "pipeline_a")] == ""
        assert rows[("dataframe", "pipeline_b", "curve")] == "docs_path, linked_charts"  # a table has a source and a series
        assert rows[("dataframe", "pipeline_a", "dataframe_0")] == "series, source"
        assert rows[("model", "pipeline_b", "encoder")] == "metrics_path, trained_on, docs"
        assert rows[("model", "pipeline_b", "forecaster")] == ""
        (public,) = [r for r in __import__("chartbook.index", fromlist=["index"]).published(index)["records"] if r["kind"] == "Catalog"]
        assert "location" not in public

    def test_a_pipeline_the_build_skips_is_not_in_the_catalogs_pages(self, catalog_project, monkeypatch):
        """Decided with the slice: a pipeline `--no-strict` leaves out is not part of the site,
        so the lists and the diagnostics leave it out too (the generator had listed pages that
        did not exist, and counted the pipeline's rows)."""
        catalog = catalog_project.resolve()
        for html in (catalog / "pipelines" / "pipeline_b" / "_output" / "charts").glob("*.html"):
            html.unlink()
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs", "--no-strict"])
        assert result.exit_code == 0, result.output
        index = json.loads((catalog / "_docs" / "index.json").read_text())
        (record,) = [r for r in index["records"] if r["kind"] == "Catalog"]
        assert record["pipelines"] == ["pipeline_a"]
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog / "_docs_src")
        _same_catalog_pages(writer, catalog / "_docs")
        assert "pipeline_b" not in writer.catalog_page("cb/pipelines.md")
        assert "pipeline_b" not in writer.catalog_page("cb/dataframes.md")
        assert all(row["Pipeline"] == "pipeline_a" for row in writer._diagnostics(record))

    def test_an_asset_key_that_cannot_be_an_address_is_refused_by_the_loader(self, pipeline_project):
        """Found by a reviewer: `[dataframes."my df"]` loaded, had a page and a diagnostics row,
        and was left out of the index with a warning, so the writer's pages differed. The
        manifest and the index must describe the same set; models were already checked."""
        import tomli
        import tomli_w

        from chartbook.manifest import load_manifest

        project = pipeline_project.resolve()
        config = tomli.loads((project / "chartbook.toml").read_text())
        config["dataframes"]["my df"] = {"path": "./_data/x.parquet", "docs": "x"}
        (project / "chartbook.toml").write_text(tomli_w.dumps(config))
        with pytest.raises(ValueError, match=r"'my df' is not a legal dataframe key"):
            load_manifest(base_dir=project)

    def test_a_pipelines_index_has_no_catalog_pages(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        with pytest.raises(ValueError, match="no Catalog record"):
            writer.catalog_page("index.md")


class TestThePipelinePage:
    def test_the_front_page_of_a_pipeline_site(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        (pipeline,) = [r for r in index["records"] if r["kind"] == "Pipeline"]
        assert "site_dir" not in pipeline and "site_pages" not in pipeline
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        _same_pages(writer, index, pipeline_project / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page(pipeline["id"])
        assert page.startswith(f"# {pipeline['name']}\n") and "## Pipeline Specs" in page
        assert "cb/dataframes/test_pipeline/dataframe_0.md" in page and "Code updated" in page

    def test_the_pipelines_own_site_pages_are_a_fact_in_the_index(self, pipeline_project_with_site_dir, monkeypatch):
        from chartbook import index as index_module

        project = pipeline_project_with_site_dir.resolve()
        index = _built(project, monkeypatch)
        (pipeline,) = [r for r in index["records"] if r["kind"] == "Pipeline"]
        assert pipeline["site_dir"]["path"] == "docs_src/site"
        assert pipeline["site_dir"]["resolved_path"] == (project / "docs_src" / "site").as_posix()
        assert "index_toc.md" in pipeline["site_pages"] and "sample_page.md" in pipeline["site_pages"]
        (public,) = [r for r in index_module.published(index)["records"] if r["kind"] == "Pipeline"]
        assert "resolved_path" not in public["site_dir"] and public["site_pages"] == pipeline["site_pages"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=project / "_docs_src")
        _same_pages(writer, index, project / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page(pipeline["id"])
        assert ":caption: Site Pages\nsample_page.md" in page  # index_toc.md, merged in

    def test_site_pages_are_ordered_as_text_and_are_files(self, pipeline_project, monkeypatch):
        """Found by a reviewer: the generator sorted Path objects (`guide/intro.md` before
        `guide.md`) and listed a directory named `dir.md`; the index sorts the paths as text and
        lists files. The generator does the same now. Also found: the writer split the README
        with splitlines(), which breaks on a form feed; readlines() on both sides."""
        from chartbook import indexdiff

        project = pipeline_project.resolve()
        site = project / "docs_src" / "site"
        (site / "guide").mkdir(parents=True)
        (site / "dir.md").mkdir()
        (site / "guide.md").write_text("# Guide\n")
        (site / "guide" / "intro.md").write_text("# Intro\n")
        (site / "a-x.md").write_text("# A-X\n")
        (site / "a").mkdir()
        (site / "a" / "b.md").write_text("# B\n")
        readme = project / "README.md"
        readme.write_text("# Title \x0c subtitle\n\nBody with a form feed \x0c inside.\n")
        index = _built(project, monkeypatch)
        (pipeline,) = [r for r in index["records"] if r["kind"] == "Pipeline"]
        assert pipeline["site_pages"] == ["a-x.md", "a/b.md", "guide.md", "guide/intro.md"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=project / "_docs_src")
        _same_pages(writer, index, project / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page(pipeline["id"])
        assert "a-x.md\na/b.md\nguide.md\nguide/intro.md" in page and "Body with a form feed \x0c inside." in page
        assert indexdiff.Change("Pipeline", "p", {"site_pages": ([], ["a.md"])}).words == ["site pages changed"]

    def test_notebooks_and_notes_are_listed_by_name(self, pipeline_project_with_notes, monkeypatch):
        """Decided with the slice: by name on both sides, as the index lists them, so a
        reordered chartbook.toml does not reorder the front page."""
        project = pipeline_project_with_notes.resolve()
        index = _built(project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=project / "_docs_src")
        _same_pages(writer, index, project / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page("notes_pipeline")
        assert ":caption: Notes 📝\n" in page
        notes = sorted(r for r in index["records"] if r["kind"] == "Note")
        assert notes and all(f"cb/{r['ref']['name']}.md" in page for r in notes)

    def test_the_front_page_lists_what_the_pipeline_depends_on_and_its_pin(self, trained, monkeypatch):
        """Found by a new user: a second pipeline's site never named the first. Its page
        lists each dependency, as declared, with the snapshot the lockfile pins it to."""
        from chartbook import lock, snapshot

        rates, forecast = trained
        unpinned = _built(forecast, monkeypatch)
        page = SphinxWriter(unpinned, theme="pipeline", docs_src_dir=forecast / "_docs_src").pipeline_page("acme/forecast")
        assert "- `rates` (path `../rates`): not pinned yet; `chartbook pin` pins it" in page

        taken = snapshot.make(rates).snapshot
        lock.pin(forecast)
        index = _built(forecast, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=forecast / "_docs_src")
        _same_pages(writer, index, forecast / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page("acme/forecast")
        made = f"{taken.made_at[:10]} {taken.made_at[11:16]} UTC"
        assert "## Dependencies" in page
        assert f"- `rates` (path `../rates`): pinned to the snapshot at commit `{taken.commit[:7]}`, made {made}" in page
        assert page.index("## Dependencies") < page.index("## Pipeline Specs")
        html = (forecast / "docs" / "index.html").read_text()
        assert 'id="dependencies"' in html and f"<code class=\"docutils literal notranslate\"><span class=\"pre\">{taken.commit[:7]}</span></code>" in html

    def test_a_dependencies_file_of_the_pipelines_own_is_not_a_template(self, trained, monkeypatch):
        """Found by a reviewer: the template was `dependencies.md`, and the pipeline's own
        root is searched first, so a DEPENDENCIES.md there (any case, on macOS and Windows)
        was rendered onto the front page in its place."""
        _, forecast = trained
        (forecast / "dependencies.md").write_text("# Our own notes on dependencies\n")
        index = _built(forecast, monkeypatch)
        page = SphinxWriter(index, theme="pipeline", docs_src_dir=forecast / "_docs_src").pipeline_page("acme/forecast")
        assert "Our own notes on dependencies" not in page
        assert "## Dependencies" in page and "- `rates` (path `../rates`)" in page

    def test_in_a_catalog_a_dependency_links_the_snapshot_pinned_or_its_page(self, trained, monkeypatch):
        import tomli_w

        from chartbook import lock, snapshot

        rates, forecast = trained
        work = forecast.parent
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "work", "name": "Work"}, "pipelines": {"acme/rates": {"path": "./rates"}, "forecast": {"path": "./forecast"}}})
        )
        # Not pinned: its page in the catalog
        index = _built(work, monkeypatch)
        page = SphinxWriter(index, theme="catalog", docs_src_dir=work / "_docs_src").pipeline_page("forecast")
        assert "- [`acme/rates`](acme--rates_README.md) (as `rates`, path `../rates`): not pinned yet" in page
        assert (work / "docs" / "cb" / "pipelines" / "acme--rates_README.html").is_file()
        # Pinned: its page in the snapshot pinned, which the catalog shows as a version
        taken = snapshot.make(rates).snapshot
        lock.pin(forecast)
        index = _built(work, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=work / "_docs_src")
        _same_pages(writer, index, work / "_docs", kinds=("Pipeline",))
        page = writer.pipeline_page("forecast")
        from chartbook.versions import site_path, version_name

        root = site_path("acme/rates", version_name(taken.commit, taken.made_at))
        assert f'- <a href="../../{root}/index.html">`acme/rates`</a> (as `rates`, path `../rates`): pinned to the snapshot at commit `{taken.commit[:7]}`' in page
        assert "## Dependencies" not in writer.pipeline_page("acme/rates")

    def test_a_catalogs_readme_page_per_pipeline(self, catalog_project, monkeypatch):
        index = _built(catalog_project, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog_project / "_docs_src")
        _same_pages(writer, index, catalog_project / "_docs")
        pipelines = [r for r in index["records"] if r["kind"] == "Pipeline"]
        assert len(pipelines) > 1
        page = writer.pipeline_page(pipelines[0]["id"])
        assert page.startswith(f"# `{pipelines[0]['id']}` {pipelines[0]['name']} \n") and "Pipeline GitHub Repo" in page


class TestTheModelPage:
    def test_a_file_model_with_scores_and_a_bare_directory_model(self, pipeline_project, monkeypatch):
        from tests.test_models import add_models

        project = add_models(pipeline_project.resolve())
        index = _built(project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=project / "_docs_src")
        _same_pages(writer, index, project / "_docs", kinds=("Model",))
        page = writer.model_page("test_pipeline:model/forecaster")
        assert "## Scores" in page and "| `rmse` | 0.212346 |" in page
        assert "[test_pipeline:dataframe_0](../../dataframes/test_pipeline/dataframe_0.md) - Dataframe 0" in page
        assert "## Files" not in page
        bare = writer.model_page("test_pipeline:model/encoder")
        assert "## Files" in bare and "| `weights/best.pt` | 2.9 KB |" in bare and "- Not declared" in bare

    def test_a_directory_model_with_nothing_counted_in_it_has_no_time(self, pipeline_project, monkeypatch):
        """Found by a reviewer: an empty directory, or one holding only `.DS_Store`, got the
        folder's own time as `modified_at`, and so a "Model updated" line the generator has not."""
        from tests.test_models import _edit_toml

        project = pipeline_project.resolve()
        (project / "_models" / "enc").mkdir(parents=True)
        (project / "_models" / "enc" / ".DS_Store").write_bytes(b"\0")
        _edit_toml(project, lambda c: c.update(models={"enc": {"path": "./_models/enc"}}))
        index = _built(project, monkeypatch)
        (record,) = [r for r in index["records"] if r["id"] == "test_pipeline:model/enc"]
        assert record["files"] == [] and "modified_at" not in record["location"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=project / "_docs_src")
        _same_pages(writer, index, project / "_docs", kinds=("Model",))
        assert "Model updated" not in writer.model_page("test_pipeline:model/enc")

    def test_training_data_a_site_pipeline_does_not_declare_is_named_by_its_build_id(self, trained, monkeypatch):
        """Found by a reviewer: the generator named it as stated (`rates:nope`) while the writer
        used the build ID (`acme/rates:nope`), and both called it "not part of this site" when
        its pipeline was. Both now use the build ID and say the pipeline does not declare it."""
        import tomli_w

        from tests.test_models import _edit_toml

        rates, forecast = trained
        work = forecast.parent
        _edit_toml(forecast, lambda c: c["models"]["m"].update(trained_on=["d", "rates:treasury", "rates:nope"]))
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "work"}, "pipelines": {"acme/rates": {"path": "./rates"}, "forecast": {"path": "./forecast"}}})
        )
        index = _built(work, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=work / "_docs_src")
        _same_pages(writer, index, work / "_docs", kinds=("Model",))
        page = writer.model_page("forecast:model/m")
        assert "- `acme/rates:nope` (which that pipeline does not declare)" in page
        assert "[acme/rates:treasury](../../dataframes/acme--rates/treasury.md)" in page
        assert "not part of this site" not in page

    def test_versions_and_a_stale_model_trained_on_another_pipelines_data(self, trained, monkeypatch):
        """The staleness notice needs each input's hash now: a local dataframe's from its
        record, another pipeline's from the pins the model record carries."""
        from chartbook import lock, snapshot
        from tests.test_model_versions import _commit

        rates, forecast = trained
        snapshot.make(rates)
        lock.pin(forecast)
        _commit(forecast.parent)
        snapshot.make(forecast)
        # Both inputs move; the pipeline updates its pin; the model is out of date on both
        (rates / "_data" / "treasury.parquet").write_bytes(b"t2")
        snapshot.make(rates)
        lock.update(forecast)
        (forecast / "_data" / "d.parquet").write_bytes(b"d2")
        index = _built(forecast, monkeypatch)
        (record,) = [r for r in index["records"] if r["id"] == "acme/forecast:model/m"]
        assert set(record["stale_inputs"]) == {"d", "rates:treasury"} and record["versions"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=forecast / "_docs_src")
        _same_pages(writer, index, forecast / "_docs")
        page = writer.model_page("acme/forecast:model/m")
        assert "## Versions" in page and f"| `{record['versions'][0]['version']}` |" in page
        assert "**Out of date.** This file is version `" in page
        assert "- `rates:treasury`: trained with `sha256:" in page and "- `d`: trained with `sha256:" in page
        # The notice's "now" hashes are on the record, keyed as `trained_with` is (a reviewer
        # found the writer matching them to `inputs` by name, which goes wrong when the
        # declaration is reordered or two inputs share a name); they are the inputs' facts
        (d,) = [r for r in index["records"] if r["id"] == "acme/forecast:d"]
        assert record["inputs_now"]["d"] == d["content_hash"]
        assert record["inputs_now"]["rates:treasury"] == record["pinned_inputs"]["rates:treasury"]
        assert f"now `{d['content_hash'][:19]}…`" in page
        # The other pipeline is not part of this site: named, not linked
        assert "- `rates:treasury` (in another pipeline, which is not part of this site)" in page

    def test_in_a_catalog_the_training_data_of_another_pipeline_is_linked(self, trained, monkeypatch):
        import tomli_w

        rates, forecast = trained
        work = forecast.parent
        (work / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "work", "name": "Work"}, "pipelines": {"rates": {"path": "./rates"}, "forecast": {"path": "./forecast"}}})
        )
        index = _built(work, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=work / "_docs_src")
        _same_pages(writer, index, work / "_docs")
        # The catalog knows the pipelines by its keys for them
        page = writer.model_page("forecast:model/m")
        assert "[rates:treasury](../../dataframes/rates/treasury.md)" in page
        assert "not part of this site" not in page


class TestTheChartPage:
    def test_a_file_backed_pipeline(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        _same_pages(writer, index, pipeline_project / "_docs", kinds=("Chart",))
        chart = next(r for r in index["records"] if r["kind"] == "Chart")
        page = writer.chart_page(chart["id"])
        assert page.startswith("---\ndate: ")
        assert "Chart updated" in page and "Data updated" in page
        assert f"## Chart Specs" in page and "## Dataframe Manifest" in page

    def test_a_chart_drawn_from_a_table(self, tmp_path, monkeypatch):
        """"Data updated" on a chart of a table is the engine file's time, on both sides.
        The generator used to show the pipeline folder's own time there."""
        directory = tmp_path.resolve() / "rates"
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# Rates\n")
        (directory / "_data" / "curve.html").write_text("<div id='curve'>chart</div>")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/rates", "name": "Rates"},
                    "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                    "dataframes": {"curve": {"source": "local", "table": "curve", "docs": "A table.", "date_col": "d"}},
                    "charts": {"curve": {"dataframe": "curve", "path": "./_data/curve.html", "docs": "Its chart: {{ not_a_template }}.", "tags": ["rates"], "series": ["y02", "y10"]}},
                }
            )
        )
        con = duckdb.connect(str(directory / "_data" / "local.duckdb"))
        con.sql("create table curve as select * from (values (date '2024-01-01', 1.0, 4.0), (date '2024-01-02', 1.1, 4.3)) t(d, y02, y10)")
        con.close()
        index = _built(directory, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=directory / "_docs_src")
        _same_pages(writer, index, directory / "_docs")
        page = writer.chart_page("acme/rates:chart/curve")
        assert "Its chart: {{ not_a_template }}." in page
        assert page.count("Data updated") == 1
        # Found by a reviewer: a chart's `series` list was dropped from its record,
        # so the writer's page lacked the Data Series row the generator's had
        (chart,) = [r for r in index["records"] if r["id"] == "acme/rates:chart/curve"]
        assert chart["series"] == ["y02", "y10"]
        assert "| Data Series            | y02, y10" in page
        # The dataframe's record says when the engine file was written; the chart page says the same
        (dataframe,) = [r for r in index["records"] if r["id"] == "acme/rates:curve"]
        assert dataframe["location"]["modified_at"]
        from chartbook.writers.sphinx import _as_utc

        assert _as_utc(dataframe["location"]["modified_at"]).strftime("%Y-%m-%d") in page

    def test_a_chart_whose_dataframe_is_not_declared_still_gets_a_page(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        chart = next(r for r in index["records"] if r["kind"] == "Chart")
        chart["inputs"] = ["acme/nowhere:gone"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        page = writer.chart_page(chart["id"])
        assert "Chart updated" in page and "Data updated" not in page


@pytest.fixture
def west_of_utc():
    """The machine's local time 18 hours behind UTC, as late in a day in Chicago puts UTC in the next one."""
    import os
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("the time zone of a running process can be changed only where time.tzset exists")
    before = os.environ.get("TZ")
    os.environ["TZ"] = "FAKE+18"
    time.tzset()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()


@pytest.fixture
def first_pipeline(tmp_path):
    """A pipeline as a new user writes one from the docs: a dataframe, a chart of it, no optional field."""
    from datetime import date

    directory = tmp_path.resolve() / "first_pipeline"
    (directory / "_data").mkdir(parents=True)
    (directory / "_output").mkdir()
    (directory / "README.md").write_text("# First\n\nText.\n")
    (directory / "_output" / "rates_chart.html").write_text("<div id='rates'>chart</div>")
    rows = {"date": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)], "rate": [3.5, 3.6, 3.8499999999999996]}
    pl.DataFrame(rows).write_parquet(directory / "_data" / "rates.parquet")
    (directory / "chartbook.toml").write_text(
        tomli_w.dumps(
            {
                "project": {"id": "first_pipeline", "name": "First"},
                "dataframes": {"rates": {"name": "Rates", "path": "./_data/rates.parquet", "docs": "Rates.", "date_col": "date"}},
                "charts": {"rates_chart": {"name": "Rates chart", "dataframe": "rates", "path": "./_output/rates_chart.html", "docs": "A chart."}},
            }
        )
    )
    return directory


class TestWhatANewUserFound:
    """A site built from a pipeline written as the docs show, with nothing optional filled in."""

    def test_no_empty_category_or_tag_when_nothing_has_one(self, first_pipeline, monkeypatch):
        """ABlog read `category: ""` as a category named "", and so made
        `cb/charts/index/category/.html` and an empty "(1)" entry in the sidebar."""
        index = _built(first_pipeline, monkeypatch)
        page = (first_pipeline / "_docs" / "cb" / "charts" / "first_pipeline.rates_chart.md").read_text()
        front_matter = page.split("---")[1]
        assert "date:" in front_matter and "category:" not in front_matter and "tags:" not in front_matter
        site = first_pipeline / "docs"
        assert not (site / "cb" / "charts" / "index" / "category" / ".html").exists()
        assert not (site / "cb" / "charts" / "index" / "tag" / ".html").exists()
        assert "category/.html" not in (site / "index.html").read_text()
        assert "Sources:" not in page
        assert index["records"]

    def test_a_chart_built_late_in_the_day_west_of_utc_is_listed(self, pipeline_project, west_of_utc, monkeypatch):
        """Found by a reviewer: dated in UTC, a chart written in the evening in Chicago was
        "tomorrow" to ABlog, which compares with the next local midnight, and so a draft,
        missing from the chart listings. The listing's date is the local time."""
        _built(pipeline_project, monkeypatch)
        site = pipeline_project / "docs"
        page = "test_pipeline.chart_0_0.html"
        assert page in (site / "cb" / "charts.html").read_text()
        assert page in (site / "index.html").read_text()
        assert page not in (site / "cb" / "charts" / "index" / "drafts.html").read_text()

    def test_a_chart_dated_in_the_future_is_listed(self, pipeline_project, monkeypatch):
        """Found by a reviewer: a chart file dated after the next local midnight (a skewed
        clock, copied times, a commit dated ahead) was a draft to ABlog, out of the listings."""
        import os
        import time

        chart = pipeline_project / "_output" / "charts" / "chart_0_0.html"
        ahead = time.time() + 2 * 86400
        os.utime(chart, (ahead, ahead))
        _built(pipeline_project, monkeypatch)
        site = pipeline_project / "docs"
        page = "test_pipeline.chart_0_0.html"
        assert page in (site / "cb" / "charts.html").read_text()
        assert page not in (site / "cb" / "charts" / "index" / "drafts.html").read_text()

    def test_only_the_documented_templates_are_taken_from_a_root(self, first_pipeline, catalog_project, monkeypatch):
        """Found by a reviewer: a root CHARTS.md (any case, on macOS) replaced the MkDocs
        chart listing, and a catalog's root models.md its models page."""
        from pathlib import Path as P

        from chartbook.writers.mkdocs import MkDocsWriter
        from chartbook.writers.sphinx import OVERRIDABLE_TEMPLATES

        (first_pipeline / "charts.md").write_text("OUR OWN CHART NOTES\\n")
        index = _built(first_pipeline, monkeypatch)
        mkdocs = MkDocsWriter(index, theme="pipeline", docs_src_dir=first_pipeline / "no-overrides")
        assert "OUR OWN CHART NOTES" not in mkdocs.own_page("cb/charts.md")
        catalog = catalog_project.resolve()
        for name in ("models.md", "pipelines.md", "versions.md", "dataframes.md", "diagnostics.md"):
            (catalog / name).write_text("OUR OWN CATALOG NOTES\\n")
        index = _built(catalog, monkeypatch)
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog / "_docs_src")
        for page_path in ("cb/models.md", "cb/pipelines.md", "cb/versions.md", "cb/dataframes.md", "cb/diagnostics.md"):
            assert "OUR OWN CATALOG NOTES" not in writer.catalog_page(page_path), page_path
        # What may be overridden still is, and the build guide's table names each one
        (catalog / "pipeline_manifest.md").write_text("OUR OWN PIPELINE TABLE\\n")
        assert "OUR OWN PIPELINE TABLE" in writer.catalog_page("cb/pipelines.md")
        guide = (P(__file__).parent.parent / "docs_src" / "guide" / "how-the-build-works.md").read_text()
        assert all(f"`{name}`" in guide for name in OVERRIDABLE_TEMPLATES)

    def test_a_chart_with_a_category_still_has_one(self, pipeline_project, monkeypatch):
        _built(pipeline_project, monkeypatch)
        page = (pipeline_project / "_docs" / "cb" / "charts" / "test_pipeline.chart_0_0.md").read_text()
        assert 'category: "Chart Tag"\n' in page and 'tags: "Test Source"\n' in page
        assert (pipeline_project / "docs" / "cb" / "charts" / "index" / "category" / "chart-tag.html").is_file()

    def test_fields_left_out_do_not_appear(self, first_pipeline, monkeypatch):
        _built(first_pipeline, monkeypatch)
        build = first_pipeline / "_docs"
        chart = (build / "cb" / "charts" / "first_pipeline.rates_chart.md").read_text()
        dataframe = (build / "cb" / "dataframes" / "first_pipeline" / "rates.md").read_text()
        front = (build / "index.md").read_text()
        for row in ("| Tags", "| Data Series Start Date", "| Data Frequency", "| Observation Period", "| Lag in Data Release",
                    "| Data Release Timing", "| Seasonal Adjustment", "| Units"):  # fmt: skip
            assert row not in chart, row
        for row in ("| Sources", "| Providers", "| Provider Links", "| Tags", "| Access Types", "| How is data pulled?"):
            assert row not in chart and row not in dataframe, row
        for row in ("| Maintainer", "| Contributors", "| Repository", "| OS Compatibility"):
            assert row not in front and row not in chart, row
        # What is there still is
        assert "| Chart ID               | rates_chart" in chart and "| HTML Chart" in chart
        assert "| Data available up to (max)     | 2024-03-01 00:00:00" in dataframe
        assert "| Linked Dataframes" in front and "| Date of Last Code Update" in front

    def test_the_download_row_is_in_its_table_and_the_web_page_link_is_closed(self, first_pipeline, monkeypatch):
        import tomli

        manifest = tomli.loads((first_pipeline / "chartbook.toml").read_text())
        manifest["project"]["enable_data_download"] = True
        (first_pipeline / "chartbook.toml").write_text(tomli_w.dumps(manifest))
        _built(first_pipeline, monkeypatch)
        page = (first_pipeline / "_docs" / "cb" / "dataframes" / "first_pipeline" / "rates.md").read_text()
        assert "`./_data/rates.parquet`                                                        |\n| Download Data as Parquet" in page
        assert ">Pipeline Web Page</a> |" in page
        html = (first_pipeline / "docs" / "cb" / "dataframes" / "first_pipeline" / "rates.html").read_text()
        assert "<td><p>Download Data as Parquet</p></td>" in html or "<td>Download Data as Parquet</td>" in html

    def test_fields_filled_in_still_appear(self, pipeline_project, monkeypatch):
        _built(pipeline_project, monkeypatch)
        page = (pipeline_project / "_docs" / "cb" / "dataframes" / "test_pipeline" / "dataframe_0.md").read_text()
        assert "| Sources                        | Test Source" in page
        assert "| Providers                      | Test Provider" in page
        assert "| Tags                           | Test Tag, Uppercase Tag" in page

    def test_the_glimpse_shows_the_first_rows_rounded(self, first_pipeline, monkeypatch):
        _built(first_pipeline, monkeypatch)
        page = (first_pipeline / "_docs" / "cb" / "dataframes" / "first_pipeline" / "rates.md").read_text()
        assert "$ date <date> 2024-01-01, 2024-02-01, 2024-03-01" in page
        assert "$ rate  <f64> 3.5, 3.6, 3.85" in page
        assert "3.8499999999999996" not in page
        assert "Rows: 3" in page

    def test_a_glimpse_of_f32_shows_its_digits_and_its_type(self):
        from chartbook.utils import glimpse_text

        long_name = "a_name_longer_than_polars_shows_in_a_glimpse_" * 2
        sample = pl.DataFrame(
            {"x": pl.Series([1.1, 2.5], dtype=pl.Float32), long_name: pl.Series([0.3, None], dtype=pl.Float32), "s": ["<f64>", "y"]}
        )
        lines = glimpse_text(sample).splitlines()
        assert lines[2].startswith("$ x ") and lines[2].endswith("<f32> 1.1, 2.5")
        assert lines[3].endswith("<f32> 0.3, null")
        assert lines[4].endswith("<str> '<f64>', 'y'")

    def test_a_glimpse_rounds_only_the_noise(self):
        """Found by reviewers: six digits made a date written as 20240115.0 read
        20240100.0; fifteen still changed 16-digit whole numbers and showed the
        largest float as inf. Only the noise of a binary fraction is rounded away."""
        import sys

        from chartbook.utils import glimpse_text

        values = [3.8499999999999996, 0.1 + 0.2, 0.7 * 3, 1.1 * 1.1, 1 / 3]
        shown = "3.85, 0.3, 2.1, 1.21, 0.3333333333333333"
        assert glimpse_text(pl.DataFrame({"v": values})).splitlines()[2] == f"$ v <f64> {shown}"
        values = [20240115.0, 1318605.0, 7e22, 1e-300, 1234567890123456.0, float(2**53), 1e15 + 1, sys.float_info.max]
        shown = "20240115.0, 1318605.0, 7e+22, 1e-300, 1234567890123456.0, 9007199254740992.0, 1000000000000001.0, 1.7976931348623157e+308"
        assert glimpse_text(pl.DataFrame({"v": values})).splitlines()[2] == f"$ v <f64> {shown}"

    def test_a_glimpse_with_a_line_break_in_a_column_name(self):
        """Found by reviewers: the f32 label was put back by line number, which a name
        with a line break in it moves; then every f32 column was labelled f64. With
        such a name, f32 columns are not widened, and keep their own label."""
        from chartbook.utils import glimpse_text

        sample = pl.DataFrame({"two\nlines": pl.Series([1.1], dtype=pl.Float32), "after": pl.Series([2.5], dtype=pl.Float32)})
        lines = glimpse_text(sample).splitlines()
        assert "$ two" in lines and "<f32>" in lines[3] and lines[4].startswith("$ after") and "<f32> 2.5" in lines[4]
        assert "<f64>" not in "\n".join(lines)

    def test_a_folder_of_parts_is_glimpsed_as_the_reader_reads_it(self, tmp_path):
        """Found by a reviewer: a dataframe whose path is a bare folder of parquet parts (no
        glob, no `.parquet` on the folder's name) showed "Unsupported file type:". The folder
        is read as a reader reads it: its parquet parts, whatever they are named, and none of
        the files a scan passes over."""
        from chartbook.utils import directory_tables, get_dataframe_glimpse

        folder = tmp_path / "parts"
        folder.mkdir()
        pl.DataFrame({"x": [1.0, 2.0]}).write_parquet(folder / "a.parquet")
        pl.DataFrame({"x": [3.0]}).write_parquet(folder / "000000_0")  # Hive's name, parquet inside
        (folder / "_SUCCESS").write_bytes(b"")
        (folder / "README.txt").write_text("not a table\n")
        (folder / ".DS_Store").write_bytes(b"\0")
        assert [f.name for f in directory_tables(folder)] == ["000000_0", "a.parquet"]
        glimpse = get_dataframe_glimpse(folder)
        assert glimpse.startswith("Rows: 3\nColumns: 1\n"), glimpse
        assert "$ x <f64> 3.0, 1.0, 2.0" in glimpse or "$ x <f64> 1.0, 2.0, 3.0" in glimpse
        assert "Unsupported" not in glimpse and "Error" not in glimpse

    def test_a_folder_named_parquet_is_read_by_the_same_rule(self, tmp_path):
        from chartbook.utils import get_dataframe_glimpse

        folder = tmp_path / "rates.parquet"
        folder.mkdir()
        pl.DataFrame({"x": [1.0]}).write_parquet(folder / "part-0.parquet")
        (folder / "_metadata").write_bytes(b"\0")  # a scan passes it over; a read of it would fail
        assert get_dataframe_glimpse(folder).startswith("Rows: 1\n")

    def test_an_empty_folder_is_said_in_a_sentence(self, tmp_path):
        from chartbook.utils import get_dataframe_glimpse

        folder = tmp_path / "parts"
        folder.mkdir()
        (folder / "_SUCCESS").write_bytes(b"")
        glimpse = get_dataframe_glimpse(folder)
        assert glimpse == "No parquet file in parts/: a folder is shown by its parquet parts, and this one has none yet."
        assert str(tmp_path) not in glimpse  # a machine's path belongs on no page

    def test_the_dataframe_path_is_the_pipelines_own(self, first_pipeline, monkeypatch):
        _built(first_pipeline, monkeypatch)
        page = (first_pipeline / "_docs" / "cb" / "dataframes" / "first_pipeline" / "rates.md").read_text()
        assert "| Dataframe Path                 | `./_data/rates.parquet`" in page
        assert str(first_pipeline / "_data" / "rates.parquet") not in page

    def test_a_name_set_in_as_code_cannot_break_the_page(self):
        """Found by a reviewer: a value set in as code kept control and
        direction-changing characters, at any length."""
        from chartbook.writers.sphinx import _code

        assert _code("../rates") == "`../rates`"
        assert _code("a\u202eb\x07c") == "`a b c`"
        assert len(_code("x" * 500)) == 202 and _code("x" * 500).endswith("…`")
        assert "|" not in _code("a|b") and "`" not in _code("a`b")

    def test_a_path_is_set_in_exactly_and_cannot_break_the_table(self, first_pipeline, monkeypatch):
        """Found by reviewers: the path was set in backticks unchecked, so a `|` or a
        backtick broke the table; then it was cut at 200 characters, a Windows path
        lost its code, `&` became "and" and runs of spaces closed up. It is code, exactly
        as written, with only control and direction-changing characters taken out."""
        from markdown_it import MarkdownIt

        written = "C:\\data\\R&D  x|y`z\u202e/" + "d" * 250 + ".parquet"
        index = _built(first_pipeline, monkeypatch)
        (record,) = [r for r in index["records"] if r["id"] == "first_pipeline:rates"]
        record["location"]["path"] = written
        page = SphinxWriter(index, theme="pipeline", docs_src_dir=first_pipeline / "_docs_src").dataframe_page(record["id"])
        table = page[page.index("| Dataframe Name") :].split("\n\n", 1)[0]
        html = MarkdownIt("commonmark").enable("table").render(table)
        (cell,) = [line for line in html.splitlines() if "<code>" in line]
        expected = written.replace("\u202e", "").replace("&", "&amp;")
        assert cell == f"<td><code>{expected}</code></td>"
        assert html.count("<td>") == 2 * table.count("\n| ")  # every row is two cells

    def test_a_table_and_its_source_are_set_in_exactly(self):
        from markdown_it import MarkdownIt

        from chartbook.writers.sphinx import _literal

        for written in ("main.rates", "`odd` name", "a|b", "x  y", " lead", "R&D\\x"):
            row = f"| A | B |\n|---|---|\n| Table | {_literal(written)} |\n"
            html = MarkdownIt("commonmark").enable("table").render(row)
            expected = written.replace("&", "&amp;")
            assert f"<td><code>{expected}</code></td>" in html, (written, html)

    def test_in_mkdocs_a_pipe_in_a_path_is_not_escaped(self):
        """Python-Markdown reads a pipe in code as text, and would show a backslash before it."""
        markdown = pytest.importorskip("markdown")
        from chartbook.writers.mkdocs import MkDocsWriter  # noqa: F401 - the writer that passes escape_pipes=False
        from chartbook.writers.sphinx import _literal

        row = f"| A | B |\n|---|---|\n| Path | {_literal('a|b', escape_pipes=False)} |\n"
        assert "<td><code>a|b</code></td>" in markdown.markdown(row, extensions=["tables"])

    def test_a_linked_chart_is_named_by_its_address(self, first_pipeline, monkeypatch):
        _built(first_pipeline, monkeypatch)
        page = (first_pipeline / "_docs" / "cb" / "dataframes" / "first_pipeline" / "rates.md").read_text()
        assert "- [first_pipeline:chart/rates_chart](../../charts/first_pipeline.rates_chart.md)" in page
        html = (first_pipeline / "docs" / "cb" / "dataframes" / "first_pipeline" / "rates.html").read_text()
        assert "first_pipeline:chart/rates_chart" in html

    def test_every_time_on_the_front_page_is_in_utc_and_says_so(self, first_pipeline, monkeypatch):
        import re

        index = _built(first_pipeline, monkeypatch)
        (pipeline,) = [r for r in index["records"] if r["kind"] == "Pipeline"]
        changed = pipeline["code_changed_at"]  # UTC, as the index records every time
        front = (first_pipeline / "_docs" / "index.md").read_text()
        assert f"| Date of Last Code Update        | {changed[:10]} {changed[11:19]} UTC" in front
        assert f'title="{changed[:10]} {changed[11:16]} UTC"' in front
        html = (first_pipeline / "docs" / "index.html").read_text()
        assert re.search(r"Last updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} (UTC|[+-]\d{4})", html)


class TestTheDataframePage:
    def test_a_file_backed_pipeline(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        dataframes = [r for r in index["records"] if r["kind"] == "Dataframe"]
        assert dataframes
        for record in dataframes:
            generated = (pipeline_project / "_docs" / writer.dataframe_page_path(record)).read_text()
            assert writer.dataframe_page(record["id"]) == generated, record["id"]

    def test_a_table_and_a_query(self, tmp_path, monkeypatch):
        directory = tmp_path.resolve() / "rates"
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# Rates\n")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/rates", "name": "Rates"},
                    "sources": {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
                    "dataframes": {
                        "rates": {"path": "./_data/rates.parquet", "docs": "A file.", "date_col": "d"},
                        "curve": {"source": "local", "table": "curve", "docs": "A table.", "date_col": "d"},
                        "slopes": {"source": "local", "query": "select d, y10 - y02 as slope from curve order by d", "docs": "A query."},
                    },
                }
            )
        )
        pl.DataFrame({"d": ["2024-01-01", "2024-01-02"], "r": [4.1, 4.2]}).write_parquet(directory / "_data" / "rates.parquet")
        con = duckdb.connect(str(directory / "_data" / "local.duckdb"))
        con.sql("create table curve as select * from (values (date '2024-01-01', 1.0, 4.0), (date '2024-01-02', 1.1, 4.3)) t(d, y02, y10)")
        con.close()
        index = _built(directory, monkeypatch)
        (pipeline,) = [r for r in index["records"] if r["kind"] == "Pipeline"]
        assert pipeline["site_url"].startswith("file://")
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=directory / "_docs_src")
        for name in ("rates", "curve", "slopes"):
            record = next(r for r in index["records"] if r["id"] == f"acme/rates:{name}")
            generated = (directory / "_docs" / writer.dataframe_page_path(record)).read_text()
            assert writer.dataframe_page(record["id"]) == generated, name
        assert next(r for r in index["records"] if r["id"] == "acme/rates:curve")["location"]["url"] == "duckdb:///./_data/local.duckdb"

    def test_a_dataframe_that_is_a_directory_is_as_new_as_its_newest_counted_file(self, tmp_path, monkeypatch):
        """Found by a reviewer: the generator showed the folder's own time for a directory
        dataframe (and so a date when the folder was empty), where the index gives the newest
        counted file's and nothing when there is none."""
        import os
        import time

        directory = tmp_path.resolve() / "p"
        (directory / "_data" / "parts").mkdir(parents=True)
        (directory / "_data" / "empty").mkdir()
        (directory / "_data" / "empty" / ".DS_Store").write_bytes(b"\0")
        (directory / "README.md").write_text("# P\n")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/p"},
                    "dataframes": {
                        "parts": {"path": "./_data/parts", "docs": "A folder of parts."},
                        "empty": {"path": "./_data/empty", "docs": "Nothing yet."},
                    },
                }
            )
        )
        pl.DataFrame({"x": [1.0]}).write_parquet(directory / "_data" / "parts" / "a.parquet")
        old = time.time() - 5 * 86400
        os.utime(directory / "_data" / "parts" / "a.parquet", (old, old))
        index = _built(directory, monkeypatch)
        parts = next(r for r in index["records"] if r["id"] == "acme/p:parts")
        empty = next(r for r in index["records"] if r["id"] == "acme/p:empty")
        assert parts["location"]["modified_at"] < index["generated_at"]
        assert "modified_at" not in empty["location"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=directory / "_docs_src")
        _same_pages(writer, index, directory / "_docs", kinds=("Dataframe",))
        assert "Data updated" not in writer.dataframe_page("acme/p:empty")

    def test_a_dataframe_that_is_a_bare_folder_of_parts_shows_its_rows(self, tmp_path, monkeypatch):
        """Found by a reviewer: the page of a dataframe whose path is a plain folder of
        parquet parts said "Unsupported file type:" where a glob or a folder named
        `x.parquet` showed the rows. A folder is glimpsed by its parts; an empty one is
        said in a sentence, with no traceback."""
        directory = tmp_path.resolve() / "p"
        (directory / "_data" / "parts").mkdir(parents=True)
        (directory / "_data" / "empty").mkdir()
        (directory / "README.md").write_text("# P\n")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps(
                {
                    "project": {"id": "acme/p"},
                    "dataframes": {
                        "parts": {"path": "./_data/parts", "docs": "A folder of parts."},
                        "empty": {"path": "./_data/empty", "docs": "Nothing yet."},
                    },
                }
            )
        )
        pl.DataFrame({"x": [1.0]}).write_parquet(directory / "_data" / "parts" / "a.parquet")
        pl.DataFrame({"x": [2.0]}).write_parquet(directory / "_data" / "parts" / "b.parquet")
        (directory / "_data" / "parts" / "_SUCCESS").write_bytes(b"")
        _built(directory, monkeypatch)
        parts = (directory / "_docs" / "cb" / "dataframes" / "acme--p" / "parts.md").read_text()
        assert "Rows: 2\nColumns: 1\n$ x <f64> 1.0, 2.0" in parts, parts
        assert "Unsupported file type" not in parts
        empty = (directory / "_docs" / "cb" / "dataframes" / "acme--p" / "empty.md").read_text()
        assert "No parquet file in empty/: a folder is shown by its parquet parts, and this one has none yet." in empty
        assert "Traceback" not in empty and "Error" not in empty
        assert str(directory / "_data") not in empty

    def test_the_published_index_keeps_no_local_site_url(self, pipeline_project, monkeypatch):
        from chartbook import index as index_module

        full = _built(pipeline_project, monkeypatch)
        (pipeline,) = [r for r in full["records"] if r["kind"] == "Pipeline"]
        assert pipeline["site_url"].startswith("file://")
        (published,) = [r for r in index_module.published(full)["records"] if r["kind"] == "Pipeline"]
        assert "site_url" not in published


class TestWhatTheReviewFound:
    def test_a_catalog_built_from_its_root_with_a_duckdb_table_in_a_pipeline(self, tmp_path, monkeypatch):
        """Found by a reviewer: a relative DuckDB url was resolved against the working
        directory, so from a catalog's root every table page said the file was not there."""
        from tests.fixtures import create_catalog_project

        catalog = create_catalog_project(tmp_path / "cat")
        pipeline = catalog / "pipelines" / "pipeline_b"
        (pipeline / "_data").mkdir(exist_ok=True)
        con = duckdb.connect(str(pipeline / "_data" / "local.duckdb"))
        con.sql("create table curve as select * from (values (date '2024-01-01', 1.0), (date '2024-01-02', 1.1)) t(d, y)")
        con.close()
        import tomli

        config = tomli.loads((pipeline / "chartbook.toml").read_text())
        config["sources"] = {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}}
        config["dataframes"]["curve"] = {"source": "local", "table": "curve", "docs": "A table.", "date_col": "d"}
        (pipeline / "chartbook.toml").write_text(tomli_w.dumps(config))
        index = _built(catalog, monkeypatch)  # the build runs from the catalog's root
        writer = SphinxWriter(index, theme="catalog", docs_src_dir=catalog / "_docs_src")
        _same_pages(writer, index, catalog / "_docs")
        page = writer.dataframe_page("pipeline_b:curve")
        assert "2 rows, 2 columns" in page and "could not be read" not in page
        # ...and from anywhere else, the same
        monkeypatch.chdir(tmp_path)
        assert writer.dataframe_page("pipeline_b:curve") == page

    def test_a_write_up_is_text_not_a_template(self, tmp_path, monkeypatch):
        """Decided with the slice: what the author wrote is what the page shows."""
        directory = tmp_path.resolve() / "p"
        (directory / "_data").mkdir(parents=True)
        (directory / "README.md").write_text("# P\n")
        (directory / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "acme/p"}, "dataframes": {"d": {"path": "./_data/d.parquet", "docs": "Name is {{ name }}; {% if true %}yes{% endif %}; a struct {{'a': 1}}."}}})
        )
        pl.DataFrame({"x": [1.0]}).write_parquet(directory / "_data" / "d.parquet")
        index = _built(directory, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=directory / "_docs_src")
        page = writer.dataframe_page("acme/p:d")
        assert "Name is {{ name }}; {% if true %}yes{% endif %}; a struct {{'a': 1}}." in page
        _same_pages(writer, index, directory / "_docs")

    def test_the_published_index_is_refused_with_a_reason(self, pipeline_project, monkeypatch):
        from chartbook import index as index_module

        full = _built(pipeline_project, monkeypatch)
        with pytest.raises(ValueError, match="needs the full index"):
            SphinxWriter(index_module.published(full))


class TestTheTemplateSearchPath:
    def test_every_folder_the_writer_loads_templates_from_exists(self, pipeline_project, monkeypatch):
        """Found by a reviewer: a `templates/` folder that is in neither the repository nor the
        wheel was on the search path, where Jinja passed it over in silence. Every folder on
        the path is one the package ships or the build made."""
        index = _built(pipeline_project, monkeypatch)
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        loader = writer._environment(pipeline_project).loader
        (_, templates) = loader.loaders  # the project's overrides, then the folders in order
        assert templates.searchpath and all(Path(folder).is_dir() for folder in templates.searchpath), templates.searchpath
