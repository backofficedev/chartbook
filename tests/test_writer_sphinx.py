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
        from chartbook.writers.sphinx import _as_local

        assert _as_local(dataframe["location"]["modified_at"]).strftime("%Y-%m-%d") in page

    def test_a_chart_whose_dataframe_is_not_declared_still_gets_a_page(self, pipeline_project, monkeypatch):
        index = _built(pipeline_project, monkeypatch)
        chart = next(r for r in index["records"] if r["kind"] == "Chart")
        chart["inputs"] = ["acme/nowhere:gone"]
        writer = SphinxWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        page = writer.chart_page(chart["id"])
        assert "Chart updated" in page and "Data updated" not in page


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
