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


def _same_pages(writer: SphinxWriter, index: dict, build_dir: Path) -> None:
    for record in [r for r in index["records"] if r["kind"] == "Dataframe"]:
        generated = (build_dir / writer.dataframe_page_path(record)).read_text()
        assert writer.dataframe_page(record["id"]) == generated, record["id"]


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
