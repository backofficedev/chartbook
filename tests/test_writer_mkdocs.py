"""The MkDocs writer: the same index, pages in MkDocs' dialect, and a site MkDocs builds.

`tests/test_writer_sphinx.py` holds the Sphinx writer to the generator's
pages; this file holds the MkDocs writer to what MkDocs needs: no MyST
directive on any page, every page the Sphinx writer has, the site's own
pages, a navigation that names every page, and a build that MkDocs
completes where it is installed.
"""

import json
import re
from pathlib import Path

import pytest
import tomli
import tomli_w
from click.testing import CliRunner

from chartbook.cli import main
from chartbook.writers import writer_class
from chartbook.writers.mkdocs import MkDocsWriter
from chartbook.writers.sphinx import SphinxWriter
from tests.test_model_versions import trained  # noqa: F401 - a fixture: two pipelines, a model trained on both
from tests.test_writer_sphinx import first_pipeline  # noqa: F401 - a fixture: a pipeline with nothing optional

MYST = re.compile(r"^```\{[a-z-]+\}|\{(?:ref|doc|sub-ref)\}`|^:::+\{|\{toctree\}|\{postlist\}", re.M)


def _set_writer(project: Path, name: str) -> None:
    path = project / ("catalog.toml" if (project / "catalog.toml").is_file() else "chartbook.toml")
    manifest = tomli.loads(path.read_text(encoding="utf-8"))
    manifest["project"]["writer"] = name
    path.write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")


def _built(project: Path, monkeypatch) -> dict:
    """Build the site with Sphinx, keep the build directory, and read its full index.

    The writers under test are then given a `docs_src_dir` with nothing in
    it: the Sphinx build's `_docs_src` holds Sphinx's templates, which the
    real MkDocs build never sees (its `_docs_src` is a copy of the MkDocs
    theme), and a test that let them in would be testing the wrong tree.
    """
    monkeypatch.chdir(project)
    result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--keep-build-dirs"])
    assert result.exit_code == 0, result.output
    return json.loads((project / "_docs" / "index.json").read_text(encoding="utf-8"))


def _pages(writer, index):
    for record in index["records"]:
        if record["kind"] in ("Dataframe", "Chart", "Model", "Pipeline"):
            yield writer.page_path(record), writer.page(record)
    for page_path in writer.own_page_paths():
        yield page_path, writer.own_page(page_path)


class TestThePages:
    def test_a_pipeline_site_has_every_page_in_mkdocs_dialect(self, trained, monkeypatch):  # noqa: F811
        _, forecast = trained
        index = _built(forecast, monkeypatch)
        mkdocs = MkDocsWriter(index, theme="pipeline", docs_src_dir=forecast / "no-overrides")
        sphinx = SphinxWriter(index, theme="pipeline")
        pages = dict(_pages(mkdocs, index))
        assert set(pages) >= {sphinx.page_path(r) for r in index["records"] if r["kind"] in ("Dataframe", "Chart", "Model", "Pipeline")}
        assert "cb/charts.md" in pages
        for path, text in pages.items():
            assert not MYST.search(text), f"{path} carries Sphinx syntax: {MYST.search(text).group(0)!r}"
        front = pages["index.md"]
        assert "## Models 🤖" in front and "cb/models/" in front and "Code updated" in front
        model_page = next(text for path, text in pages.items() if path.startswith("cb/models/"))
        assert "## Provenance" in model_page
        assert "## Pipeline Specs" in front
        # What the pipeline depends on, as the Sphinx front page lists it
        assert "## Dependencies" in front and "- `rates` (path `../rates`): not pinned yet" in front
        # In UTC and said so, as on the Sphinx front page (found by a reviewer: a bare local date)
        assert re.search(r"^Last updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC$", front, re.M)
        model = next(r for r in index["records"] if r["kind"] == "Model")
        if model.get("versions"):
            header = model_page.index("| Version | Made |")
            table = model_page[header:].split("\n\n", 1)[0]
            assert table.count("\n") >= 2, "the versions table is header, delimiter and rows on consecutive lines"

    def test_a_chart_with_no_sources_or_tags_says_none(self, first_pipeline, monkeypatch):  # noqa: F811
        """Found by a reviewer: as on the Sphinx side, a field left out is not written empty."""
        index = _built(first_pipeline, monkeypatch)
        page = MkDocsWriter(index, theme="pipeline", docs_src_dir=first_pipeline / "no-overrides").chart_page("first_pipeline:chart/rates_chart")
        front_matter = page.split("---")[1]
        assert "date:" in front_matter and "sources:" not in front_matter and "category:" not in front_matter
        assert "Sources:" not in page and "</iframe>\n\n[Full Screen Chart]" in page

    def test_a_catalog_site_lists_its_pages(self, catalog_project, monkeypatch):
        catalog = catalog_project.resolve()
        index = _built(catalog, monkeypatch)
        writer = MkDocsWriter(index, theme="catalog", docs_src_dir=catalog / "no-overrides")
        pages = dict(_pages(writer, index))
        assert {"index.md", "cb/charts.md", "cb/dataframes.md", "cb/pipelines.md", "cb/diagnostics.md"} <= set(pages)
        assert "cb/models.md" not in pages  # no pipeline declares a model
        for path, text in pages.items():
            assert not MYST.search(text), f"{path} carries Sphinx syntax"
        assert pages["cb/dataframes.md"].count("](dataframes/") == 2
        assert "](cb/charts.md)" in pages["index.md"] and "Models" not in pages["index.md"]
        assert "pipelines/pipeline_a.md" in pages["cb/pipelines.md"]
        assert "<table" in pages["cb/diagnostics.md"] and "```" not in pages["cb/diagnostics.md"]

    def test_the_sphinx_writer_renders_no_own_page_for_a_pipeline_site(self, trained, monkeypatch):  # noqa: F811
        _, forecast = trained
        index = _built(forecast, monkeypatch)
        assert SphinxWriter(index, theme="pipeline").own_page_paths() == []
        assert set(SphinxWriter(index, theme="pipeline").own_page_paths()) < set(MkDocsWriter(index, theme="pipeline", docs_src_dir=forecast / "no-overrides").own_page_paths())


class TestTheConfiguration:
    def test_the_nav_names_every_page(self, trained, monkeypatch):  # noqa: F811
        _, forecast = trained
        index = _built(forecast, monkeypatch)
        writer = MkDocsWriter(index, theme="pipeline", docs_src_dir=forecast / "no-overrides")
        configuration = writer.config(site_name="Forecast", site_url="https://example.org/f", copyright="Acme")
        assert configuration["docs_dir"] == "pages" and configuration["use_directory_urls"] is False
        assert configuration["theme"]["name"] == "material"
        assert configuration["site_url"] == "https://example.org/f" and configuration["copyright"] == "Acme"
        named = set(_links(configuration["nav"]))
        for path, _ in _pages(writer, index):
            assert path in named, f"{path} is not in the nav"
        assert any("mkdocs-jupyter" in (p if isinstance(p, str) else next(iter(p))) for p in configuration["plugins"])

    def test_a_catalog_nav_has_its_sections(self, catalog_project, monkeypatch):
        index = _built(catalog_project.resolve(), monkeypatch)
        nav = MkDocsWriter(index, theme="catalog", docs_src_dir=catalog_project / "no-overrides").config(site_name="Catalog")["nav"]
        assert [next(iter(entry)) for entry in nav] == ["Home", "Charts", "Dataframes", "Pipelines", "Versions", "Stores", "Diagnostics", "Contributing"]


def _links(nav):
    for entry in nav:
        for value in entry.values():
            if isinstance(value, str):
                yield value
            else:
                yield from _links(value)


class TestTheManifest:
    def test_the_writer_is_named_in_the_manifest(self, pipeline_project):
        from chartbook.manifest import load_manifest

        assert load_manifest(pipeline_project)["project"]["writer"] == "sphinx"
        _set_writer(pipeline_project, "mkdocs")
        assert load_manifest(pipeline_project)["project"]["writer"] == "mkdocs"
        _set_writer(pipeline_project, "hugo")
        with pytest.raises(ValueError, match="writer = 'hugo' names a site tool ChartBook does not write for; the writers are: sphinx, mkdocs"):
            load_manifest(pipeline_project)
        assert writer_class("mkdocs") is MkDocsWriter and writer_class("sphinx") is SphinxWriter


class TestTheBuild:
    def test_the_site_is_built_with_mkdocs(self, pipeline_project_with_notes, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        pytest.importorskip("mkdocs_jupyter")
        project = pipeline_project_with_notes.resolve()
        _set_writer(project, "mkdocs")
        path = project / ("catalog.toml" if (project / "catalog.toml").is_file() else "chartbook.toml")
        manifest = tomli.loads(path.read_text(encoding="utf-8"))
        manifest["project"]["enable_data_download"] = True
        path.write_text(tomli_w.dumps(manifest), encoding="utf-8", newline="\n")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        site = project / "docs"
        assert (site / "index.html").is_file() and (site / "cb" / "charts.html").is_file()
        assert (site / "cb" / "note1.html").is_file()
        assert (site / "search" / "search_index.json").is_file()  # MkDocs' search, not Sphinx's
        assert not (site / "_sources").exists() and not (project / "_docs" / "conf.py").exists()
        assert (project / "_docs" / "mkdocs.yml").is_file() and not (project / "_docs" / "pages" / "_templates").exists()
        published = json.loads((site / "index.json").read_text(encoding="utf-8"))
        assert published["records"] and "value" not in (published["records"][0].get("location") or {})
        assert "cb-freshness" in (site / "index.html").read_text(encoding="utf-8")
        assert "contains a link" not in result.output, result.output  # every link on every page resolves, downloads included
        assert (site / "cb" / "download_dataframe").is_dir()

    def test_a_site_with_a_model_has_no_unresolved_link(self, trained, monkeypatch):  # noqa: F811
        pytest.importorskip("mkdocs")
        _, forecast = trained
        _set_writer(forecast, "mkdocs")
        monkeypatch.chdir(forecast)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        assert "contains a link" not in result.output, result.output
        assert (forecast / "docs" / "cb" / "models" / "acme--forecast" / "m.html").is_file()

    def test_a_catalog_is_built_with_mkdocs(self, catalog_project, monkeypatch):
        pytest.importorskip("mkdocs")
        pytest.importorskip("material")
        catalog = catalog_project.resolve()
        _set_writer(catalog, "mkdocs")
        monkeypatch.chdir(catalog)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 0, result.output
        site = catalog / "docs"
        for page in ("index.html", "cb/charts.html", "cb/dataframes.html", "cb/pipelines.html", "cb/diagnostics.html", "contributing.html", "cb/pipelines/pipeline_a.html"):
            assert (site / page).is_file(), page
        assert (site / "_static" / "diagnostics" / "chartbook_metadata_diagnostics.csv").is_file()
        import html
        assert "Chart 0-0" in html.unescape((site / "index.html").read_text(encoding="utf-8"))
        assert "contains a link" not in result.output, result.output

    def test_a_site_page_with_sphinx_syntax_is_said(self, pipeline_project, monkeypatch):
        pytest.importorskip("mkdocs")
        project = pipeline_project.resolve()
        site_dir = project / "docs_src" / "site"
        site_dir.mkdir(parents=True, exist_ok=True)
        (site_dir / "guide.md").write_text("# A Guide\n\n```{toctree}\nmore\n```\n", encoding="utf-8", newline="\n")
        (site_dir / "more.md").write_text("# More\n", encoding="utf-8", newline="\n")
        (site_dir / "index_toc.md").write_text("```{toctree}\nmore\nguide\n```\n", encoding="utf-8", newline="\n")
        _set_writer(project, "mkdocs")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--keep-build-dirs"])
        assert result.exit_code == 0, result.output
        assert "warning: guide.md uses Sphinx syntax" in result.output
        front = (project / "_docs" / "pages" / "index.md").read_text(encoding="utf-8")
        assert front.index("[More](more.md)") < front.index("[A Guide](guide.md)")  # index_toc.md's order, titles from the pages
        nav = (project / "_docs" / "mkdocs.yml").read_text(encoding="utf-8")
        assert "Site Pages" in nav and "guide.md" in nav

    def test_an_incremental_build_is_refused(self, pipeline_project, monkeypatch):
        pytest.importorskip("mkdocs")
        project = pipeline_project.resolve()
        _set_writer(project, "mkdocs")
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f", "--incremental"])
        assert result.exit_code == 1
        assert "build with Sphinx; a site with [project] writer = \"mkdocs\" is built whole" in result.output

    def test_without_mkdocs_the_message_names_the_extra(self, pipeline_project, monkeypatch):
        from chartbook.writers import mkdocs as mkdocs_writer

        project = pipeline_project.resolve()
        _set_writer(project, "mkdocs")
        monkeypatch.setattr(mkdocs_writer, "is_installed", lambda: False)
        monkeypatch.chdir(project)
        result = CliRunner().invoke(main, ["docs", "build", "./docs", "-f"])
        assert result.exit_code == 1
        assert "pip install chartbook[mkdocs]" in result.output


class TestTheTemplateSearchPath:
    def test_every_folder_the_writer_loads_templates_from_exists(self, pipeline_project, monkeypatch):
        """As for the Sphinx writer: no folder on the path that nothing ships."""
        index = _built(pipeline_project, monkeypatch)
        writer = MkDocsWriter(index, theme="pipeline", docs_src_dir=pipeline_project / "_docs_src")
        loader = writer._environment(pipeline_project).loader
        (_, templates) = loader.loaders
        assert templates.searchpath and all(Path(folder).is_dir() for folder in templates.searchpath), templates.searchpath
