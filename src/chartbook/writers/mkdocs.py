"""The MkDocs writer: pages for MkDocs, from the same index the Sphinx writer reads.

The second site tool, and the proof that the index is what it claims to
be: nothing above the writer changes. The pages are the Sphinx writer's,
rendered through a theme folder of this writer's own
(``chartbook/docs_src_mkdocs/<theme>``) where a template needs MkDocs'
dialect: freshness and the chart's top, which Sphinx wrote as ``{raw}``
fences and MkDocs takes as the HTML it is; the front pages and the lists,
which Sphinx wrote as toctrees and MkDocs writes as lists of links, with
its navigation in ``mkdocs.yml`` instead. The provenance panel, the
manifests, the specs and the model page are plain Markdown and shared.

MkDocs is not installed by ``pip install chartbook``; ``pip install
chartbook[mkdocs]`` brings it, with the Material theme and the notebook
plugin. The writer itself needs none of them: it writes files.

What MkDocs does not have, and how the pages do without: Sphinx's blog
carries the notes and the chart listing; here the notes are pages listed
on the front page and the chart listing is written from the records.
Pages keep their ``.md`` paths and the site keeps ``.html`` files
(``use_directory_urls: false``), so every relative link and iframe path
the Sphinx pages use holds.
"""

from __future__ import annotations

import functools
import importlib.resources
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jinja2

from chartbook.writers.sphinx import SphinxWriter, _laid_out_version, _literal, _local_name, _sandboxed, _slug

#: The install extra that brings MkDocs, the Material theme and the notebook plugin.
EXTRA = "chartbook[mkdocs]"
#: The folder under the MkDocs project that holds the pages; ``mkdocs.yml`` sits beside it.
PAGES_DIR = "pages"
#: The Sphinx theme's templates this writer shares, found when its own folder has none.
_SPHINX_THEMES = {"pipeline": "docs_src_pipeline", "catalog": "docs_src_catalog"}


class MkDocsWriter(SphinxWriter):
    """Pages for MkDocs, from one index. The parameters are :class:`SphinxWriter`'s."""

    #: MkDocs would render the templates as pages: they stay out of the site tree.
    THEME_TEMPLATES_IN_SITE = False
    #: The pages the writer renders besides the records': the catalog's own, and the chart listing.
    CATALOG_PAGES = ("index.md", "cb/charts.md", "cb/dataframes.md", "cb/models.md", "cb/pipelines.md", "cb/diagnostics.md", "cb/versions.md")

    def _environment(self, base_dir: Path) -> jinja2.Environment:
        """The Sphinx writer's search path, with this writer's theme folder first, in the sandbox."""
        from chartbook.config import untrusted_source

        package = Path(str(importlib.resources.files("chartbook")))
        own = package / "docs_src_mkdocs" / self.theme
        sphinx_theme = package / _SPHINX_THEMES[self.theme]
        paths = []
        if self.docs_src_dir is not None:
            paths += [Path(self.docs_src_dir), Path(self.docs_src_dir) / "_templates"]
        paths += [own, own / "_templates", sphinx_theme / "_templates"]
        environment = _sandboxed(paths, own=None if untrusted_source() else base_dir)
        # Python-Markdown reads a pipe in code as text, in a table cell too
        environment.filters["literal"] = functools.partial(_literal, escape_pipes=False)
        return environment

    # --- the pages this writer renders besides the records' -------------------

    def own_page_paths(self) -> list:
        """The site's own pages: the chart listing in a pipeline site, the catalog's pages in a catalog."""
        if self.theme == "pipeline":
            return ["cb/charts.md"]
        return self.catalog_page_paths()

    def own_page(self, page_path: str) -> str:
        if page_path == "cb/charts.md":
            return self._charts_page()
        return self.catalog_page(page_path)

    def _pages(self, kind: str, from_root: bool = True) -> list:
        """The pages of one kind, as a list of titles and links, by pipeline then name."""
        records = sorted(
            (r for r in self.records.values() if r["kind"] == kind),
            key=lambda r: (r.get("pipeline", ""), _local_name(r)),
        )
        entries = []
        for record in records:
            path = self.page_path(record)
            entries.append(
                {
                    "title": record.get("name") or _local_name(record),
                    "link": path if from_root else path.removeprefix("cb/"),
                    "pipeline": record.get("pipeline", ""),
                    "description": (record.get("description") or "").strip(),
                }
            )
        return entries

    def _charts_page(self) -> str:
        catalog = next((r for r in self.records.values() if r["kind"] == "Catalog"), None)
        base_dir = Path(
            ((catalog or {}).get("location") or {}).get("value")
            or next((r["location"]["value"] for r in self.records.values() if r["kind"] == "Pipeline"), self.docs_src_dir)
        )
        environment = self._environment(base_dir)
        return environment.get_template("charts.md").render(charts=self._pages("Chart", from_root=False))

    def catalog_page(self, page_path: str) -> str:
        """The catalog's pages, with the lists as titles and links rather than toctree paths."""
        if page_path == "cb/charts.md":
            return self._charts_page()
        catalog = next((r for r in self.records.values() if r["kind"] == "Catalog"), None)
        if catalog is None:
            raise ValueError("This index has no Catalog record: it is a pipeline's, and a pipeline site has no catalog pages.")
        base_dir = Path((catalog.get("location") or {}).get("value") or self.docs_src_dir)
        environment = self._environment(base_dir)
        if page_path == "index.md":
            return environment.get_template("index.md").render(
                manifest={"project": {"name": catalog.get("name", "")}},
                model_file_list=self._pages("Model"),
                readme_text="",
                today=_built_at(),
                has_versions=self._has_versions(),
            )
        if page_path == "cb/dataframes.md":
            return environment.get_template("dataframes.md").render(
                dataframe_pages=self._pages("Dataframe", from_root=False),
                stored_dataframes=self.from_the_store_assets(("dataframe",), page_path),
            )
        if page_path == "cb/models.md":
            return environment.get_template("models.md").render(model_pages=self._pages("Model", from_root=False))
        return super().catalog_page(page_path)

    def pipeline_page(self, pipeline_id: str) -> str:
        """The front page of a pipeline site as lists of links; a pipeline's README page in a catalog, as Sphinx's."""
        if self.theme == "catalog":
            return super().pipeline_page(pipeline_id)
        pipeline = self.records[pipeline_id]
        base_dir = Path(pipeline["location"]["value"])
        readme = self._readme_lines(pipeline, base_dir)
        environment = self._environment(base_dir)
        own = [self.records[i] for i in pipeline.get("assets", []) if i in self.records]
        slug = _slug(pipeline_id)
        notebooks = [
            {
                "title": r.get("name") or _local_name(r),
                "link": f"cb/notebooks/{slug}/{Path((r.get('location') or {}).get('path', '')).stem}.ipynb",
            }
            for r in sorted((r for r in own if r["kind"] == "Notebook"), key=_local_name)
        ]
        notes = [
            {"title": r.get("name") or _local_name(r), "link": f"cb/{_local_name(r)}.md"}
            for r in sorted((r for r in own if r["kind"] == "Note"), key=_local_name)
        ]
        return environment.get_template("index.md").render(
            pipeline_manifest=self._pipeline_manifest(pipeline),
            pipeline_id=pipeline_id,
            pipeline_page_link="./index.md",
            dot_or_dotdot="cb",
            show_code_updated=True,
            readme_text="".join(readme[2:]),
            today=_built_at(),
            site_pages=self._site_pages(pipeline),
            notebooks=notebooks,
            notes=notes,
            charts=[{"title": "All charts", "link": "cb/charts.md"}, *self._pages("Chart")],
            dataframes=self._pages("Dataframe"),
            models=self._pages("Model"),
            freshness=[fact for fact in [_freshness_of(pipeline)] if fact],
            version=_laid_out_version(pipeline),
            dependencies=self._dependencies(pipeline, self.pipeline_page_path(pipeline)),
        )

    def _site_pages(self, pipeline: dict) -> list:
        """A pipeline's own site pages as titles and links: in the order of its `index_toc.md`, else by path.

        Sphinx reads `index_toc.md` as a toctree; here its entries, one page
        per line, give the order and the set, and a page's title is its first
        heading, else its file name.
        """
        pages = [p for p in (pipeline.get("site_pages") or []) if p not in ("index_toc.md", "index.md")]
        site_dir = (pipeline.get("site_dir") or {}).get("resolved_path")
        toc = Path(site_dir) / "index_toc.md" if site_dir else None
        if toc is not None and toc.is_file():
            listed = []
            for line in toc.read_text(encoding="utf-8").splitlines():
                entry = line.strip()
                if not entry or entry.startswith((":", "```", "#", "%")):
                    continue
                entry = entry.rsplit("<", 1)[-1].rstrip(">").strip()  # a toctree's "Title <path>" form
                for page in pages:
                    if page == entry or page == entry + ".md" or Path(page).with_suffix("").as_posix() == entry:
                        listed.append(page)
            pages = listed + [p for p in pages if p not in listed]
        entries = []
        for page in pages:
            title = Path(page).stem.replace("_", " ").replace("-", " ").title()
            if site_dir and (Path(site_dir) / page).is_file():
                for line in (Path(site_dir) / page).read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
            entries.append({"title": title, "link": page})
        return entries

    # --- mkdocs.yml ------------------------------------------------------------

    def config(self, site_name: str, site_url: str = "", copyright: str = "", site_dir: str = "_build/html") -> dict:
        """The MkDocs configuration for this site, with the navigation written from the records.

        Written beside the pages folder as ``mkdocs.yml``. Pages keep their
        ``.md`` names and the site its ``.html`` files, so the relative links
        the pages carry hold; the Material theme, search and the notebook
        plugin are what the extra installs.
        """
        nav: list = [{"Home": "index.md"}]
        if self.theme == "pipeline":
            pipeline = next(r for r in self.records.values() if r["kind"] == "Pipeline")
            own = [self.records[i] for i in pipeline.get("assets", []) if i in self.records]
            slug = _slug(pipeline["id"])
            charts = [{p["title"]: p["link"]} for p in self._pages("Chart")]
            nav.append({"Charts": [{"All charts": "cb/charts.md"}, *charts]})
            _append(nav, "Dataframes", self._pages("Dataframe"))
            _append(nav, "Models", self._pages("Model"))
            _append(
                nav,
                "Notebooks",
                [
                    {
                        "title": r.get("name") or _local_name(r),
                        "link": f"cb/notebooks/{slug}/{Path((r.get('location') or {}).get('path', '')).stem}.ipynb",
                    }
                    for r in sorted((r for r in own if r["kind"] == "Notebook"), key=_local_name)
                ],
            )
            _append(
                nav,
                "Notes",
                [
                    {"title": r.get("name") or _local_name(r), "link": f"cb/{_local_name(r)}.md"}
                    for r in sorted((r for r in own if r["kind"] == "Note"), key=_local_name)
                ],
            )
            _append(nav, "Site Pages", self._site_pages(pipeline))
        else:
            # Two pipelines may each have a chart of one name: the entry says whose
            def titled(pages):
                return [{f"{p['title']} ({p['pipeline']})": p["link"]} for p in pages]

            nav.append({"Charts": [{"All charts": "cb/charts.md"}, *titled(self._pages("Chart"))]})
            nav.append({"Dataframes": [{"All dataframes": "cb/dataframes.md"}, *titled(self._pages("Dataframe"))]})
            if any(r["kind"] == "Model" for r in self.records.values()):
                nav.append({"Models": [{"All models": "cb/models.md"}, *titled(self._pages("Model"))]})
            pipelines = sorted((r for r in self.records.values() if r["kind"] == "Pipeline"), key=lambda r: r["id"])
            nav.append(
                {"Pipelines": [{"All pipelines": "cb/pipelines.md"}, *[{r.get("name") or r["id"]: self.pipeline_page_path(r)} for r in pipelines]]}
            )
            if self._has_versions():
                nav.append({"Versions": "cb/versions.md"})
            nav.append({"Diagnostics": "cb/diagnostics.md"})
            nav.append({"Contributing": "contributing.md"})
        configuration = {
            "site_name": site_name or "ChartBook",
            "docs_dir": PAGES_DIR,
            "site_dir": site_dir,
            "use_directory_urls": False,
            "theme": {
                "name": "material",
                "logo": "_static/logo.png",
                "favicon": "_static/favicon.ico",
                "features": ["navigation.sections", "navigation.top", "search.suggest", "content.code.copy"],
            },
            "markdown_extensions": ["admonition", "attr_list", "md_in_html", "tables", {"toc": {"permalink": True}}],
            "plugins": ["search", {"mkdocs-jupyter": {"include": ["*.ipynb"], "execute": False, "include_source": False}}],
            "extra_css": ["_static/custom.css"],
            "extra_javascript": ["_static/chartbook-freshness.js"],
            "nav": nav,
        }
        if site_url.startswith(("http://", "https://")):
            configuration["site_url"] = site_url  # MkDocs refuses one without a scheme; a manifest's may be a bare host
        if copyright:
            configuration["copyright"] = copyright
        return configuration


def _append(nav: list, title: str, pages: list) -> None:
    if pages:
        nav.append({title: [{p["title"]: p["link"]} for p in pages]})


def _freshness_of(pipeline: dict) -> Optional[dict]:
    from chartbook.writers.sphinx import _freshness

    return _freshness("Code updated", pipeline.get("code_changed_at"))


def _built_at() -> str:
    """The front page's "Last updated": now, in UTC and said so, as every time on the site is."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def is_installed() -> bool:
    """Whether MkDocs and what the writer's configuration names are installed."""
    import importlib.util

    return all(importlib.util.find_spec(name) is not None for name in ("mkdocs", "material", "mkdocs_jupyter"))
