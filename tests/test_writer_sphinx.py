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


def _built(project: Path, monkeypatch) -> dict:
    """Build the site with the generator, keep the build directory, and read its full index."""
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["docs", "./docs", "-f", "--keep-build-dirs"])
    assert result.exit_code == 0, result.output
    return json.loads((project / "_docs" / "index.json").read_text())


_PAGES = {"Dataframe": ("dataframe_page_path", "dataframe_page"), "Chart": ("chart_page_path", "chart_page")}


def _same_pages(writer: SphinxWriter, index: dict, build_dir: Path, kinds=("Dataframe", "Chart")) -> None:
    """Every page of the given kinds the generator wrote, the writer writes the same."""
    seen = 0
    for record in [r for r in index["records"] if r["kind"] in kinds]:
        path_of, page_of = _PAGES[record["kind"]]
        generated = (build_dir / getattr(writer, path_of)(record)).read_text()
        assert getattr(writer, page_of)(record["id"]) == generated, record["id"]
        seen += 1
    assert seen, f"no {kinds} pages to compare"


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
