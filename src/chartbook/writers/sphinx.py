"""The Sphinx writer: pages for Sphinx, from the index and the files it names.

The slices so far are the dataframe, chart, model and pipeline pages. Each
renders today's templates with a context built from the record, its
pipeline's record, the records of its inputs or assets and the files the
records name, and writes the same page the generator writes, which a
golden test holds it to. The "manifests" the templates read are made here
from the records; the templates are unchanged until the generator is gone,
so that the two can be compared.
"""

from __future__ import annotations

import importlib.resources
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jinja2
import polars as pl
import yaml

from chartbook.errors import ChartBookError
from chartbook.provenance import panel, reverse
from chartbook.utils import get_dataframe_glimpse, is_glob_pattern

#: The sections of a dataframe page, as the generator orders them.
_DATAFRAME_PAGE = (
    """# Dataframe: `{{pipeline_id}}:{{dataframe_id}}` - {{name}}\n\n"""
    """{% include "freshness.md" %}\n\n"""
    """{{ write_up }}"""
    """\n\n
## DataFrame Glimpse

```
{{dataframe_glimpse}}
```

{% include "provenance.md" %}

## Dataframe Manifest

{% include "dataframe_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}

"""
)

#: The sections of a chart page, as the generator orders them: the entry's
#: top (front matter, title, freshness, the chart itself), the write-up,
#: the provenance panel, then the specs and the two manifests.
_CHART_PAGE = (
    """{% include "chart_entry_top.md" %}\n\n\n\n"""
    """{{ write_up }}"""
    """\n\n\n{% include "provenance.md" %}\n\n{% include "chart_entry_bottom.md" %}\n"""
)

#: The sections of a model page: title and freshness, the write-up, then the
#: scores, versions, what it was trained on, files, panel and manifests.
_MODEL_PAGE_HEAD = """# Model: `{{pipeline_id}}:model/{{model_id}}` - {{model_name}}

{% include "freshness.md" %}

"""

_MODEL_PAGE_TAIL = """

{% if metrics %}
## Scores

| Metric | Value |
|--------|-------|
{% for name, value in metrics.items() %}| `{{name}}` | {{value}} |
{% endfor %}
{% endif %}

{% if versions %}
## Versions

A version is made by a snapshot. Its name is the start of the model's content hash:
`chartbook path model/{{model_id}}@<version>` gives its path.

| Version | Made | Commit | Labels |{% for name in version_metrics %} `{{name}}` |{% endfor %}

|---------|------|--------|--------|{% for name in version_metrics %}------|{% endfor %}

{% for version in versions %}| `{{version.name}}` | {{version.made}} | `{{version.commit}}` | {{version.labels}} |{% for name in version_metrics %} {{version.metrics.get(name, "")}} |{% endfor %}

{% endfor %}
{% endif %}

## Trained On

{% if trained_on %}
{% for dataframe in trained_on %}
- {% if dataframe.link %}[{{dataframe.label}}]({{dataframe.link}}){% else %}`{{dataframe.label}}`{% endif %}{% if dataframe.name %} - {{dataframe.name}}{% endif %}{% if dataframe.note %} ({{dataframe.note}}){% endif %}

{% endfor %}
{% else %}
- Not declared
{% endif %}
{% if staleness %}

**Out of date.** This file is version `{{staleness.version}}`, trained on inputs that have since moved:

{% for input in staleness.stale %}
- `{{input}}`: trained with `{{staleness.trained_with[input][:19]}}…`, now `{{staleness.now[input][:19]}}…`
{% endfor %}

`chartbook run` retrains it.
{% endif %}

{% if model_files %}
## Files

| File | Size |
|------|------|
{% for file in model_files %}| `{{file.path}}` | {{file.size}} |
{% endfor %}
{% endif %}

{% include "provenance.md" %}

## Model Manifest

{% include "model_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}

"""


@dataclass
class SphinxWriter:
    """Pages for Sphinx, from one index.

    :param index: The full index of the site, as the build made it: with
        `resolved_path` on locations, since the writer reads the files
        the index names.
    :param theme: `pipeline` or `catalog`: which theme's templates and link
        scheme.
    :param docs_src_dir: The site's own `docs_src`, where a project may
        override a template.
    :param size_threshold: Files over this many megabytes get a glimpse of
        one row and no date range, as the generator does.
    :param enable_data_download: Whether pages link to downloads.
    """

    index: dict
    theme: str = "pipeline"
    docs_src_dir: Optional[Path] = None
    size_threshold: float = 50
    enable_data_download: bool = False
    records: dict = field(init=False)
    _reversed: dict = field(init=False)

    def __post_init__(self):
        self.records = {record["id"]: record for record in self.index.get("records", [])}
        self._reversed = reverse(self.records)
        if self.docs_src_dir is None:
            self.docs_src_dir = Path("_docs_src").resolve()
        for record in self.records.values():
            if record.get("kind") == "Pipeline" and not (record.get("location") or {}).get("value"):
                raise ValueError(
                    "SphinxWriter needs the full index, the one the build directory holds, "
                    "not the published one beside the site: it reads the files the index "
                    "names, and the published index has no local paths."
                )

    # --- the link scheme ---------------------------------------------------

    def pipeline_page_link(self, record: dict) -> str:
        """The link from an asset's page to its pipeline's page.

        The forms are the generator's, as they are: in the catalog theme a
        model's page climbs two folders to `pipelines/`, the others one.
        """
        if self.theme == "pipeline":
            return "../" * self.page_path(record).count("/") + "index.md"
        up = "../../" if record["kind"] == "Model" else "../"
        return f"{up}pipelines/{_slug(record['pipeline'])}_README.md"

    def page_path(self, record: dict) -> str:
        """Where a record's page is, under the pages folder."""
        return {
            "Dataframe": self.dataframe_page_path,
            "Chart": self.chart_page_path,
            "Model": self.model_page_path,
            "Pipeline": self.pipeline_page_path,
        }[record["kind"]](record)

    def pipeline_page_path(self, record: dict) -> str:
        """Where a pipeline's page is: the site's front page in the pipeline theme, a README page in a catalog."""
        if self.theme == "pipeline":
            return "index.md"
        return f"cb/pipelines/{_slug(record['id'])}_README.md"

    def dataframe_page_path(self, record: dict) -> str:
        """Where a dataframe's page is, under the pages folder."""
        return f"cb/dataframes/{_slug(record['pipeline'])}/{_local_name(record)}.md"

    def chart_page_path(self, record: dict) -> str:
        """Where a chart's page is, under the pages folder."""
        return f"cb/charts/{_slug(record['pipeline'])}.{_local_name(record)}.md"

    def model_page_path(self, record: dict) -> str:
        """Where a model's page is, under the pages folder."""
        return f"cb/models/{_slug(record['pipeline'])}/{_local_name(record)}.md"

    def link_to_dataframe(self, record: dict, from_kind: str = "Dataframe") -> str:
        """The link to a dataframe's page from a page of the given kind.

        The links are the generator's, as they are: from a dataframe page
        the catalog theme links by the pipeline's folder alone.
        """
        prefix = "../dataframes/" if (self.theme == "pipeline" or from_kind == "Chart") else ""
        return f"{prefix}{_slug(record['pipeline'])}/{_local_name(record)}.md"

    # --- the pages ---------------------------------------------------------

    def dataframe_page(self, record_id: str) -> str:
        """The Markdown page of one dataframe, from its record and the files it names."""
        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        location = record.get("location") or {}
        dataframe_manifest = self._dataframe_manifest(record, base_dir)
        if location.get("kind") in ("table", "query"):
            glimpse = _source_glimpse(record, base_dir)
            span = record.get("date_range") or {}
            first, last = span.get("first"), span.get("last")
            freshness = [_freshness("Data updated", location.get("modified_at"))]
        else:
            resolved = location.get("resolved_path") or str(base_dir / location.get("path", ""))
            glimpse = get_dataframe_glimpse(Path(resolved), size_threshold_mb=self.size_threshold)
            try:
                first, last = _most_recent_valid_datapoints(
                    Path(resolved), record.get("date_col", ""), size_threshold_mb=self.size_threshold
                )
            except Exception:  # noqa: BLE001 - as the generator does: a page, not a crash
                first, last = None, None
            freshness = [_freshness("Data updated", location.get("modified_at"))]
        template = environment.from_string(_DATAFRAME_PAGE)
        return template.render(
            dataframe_manifest,
            write_up=self._write_up(record, base_dir, environment),
            provenance=panel(record_id, self.records, self._reversed),
            dataframe_manifest=dataframe_manifest,
            link_to_dataframe_docs=self.link_to_dataframe(record),
            dataframe_id=_local_name(record),
            pipeline_id=record["pipeline"],
            pipeline_manifest=self._pipeline_manifest(pipeline),
            pipeline_page_link=self.pipeline_page_link(record),
            most_recent_data_min=first,
            most_recent_data_max=last,
            dot_or_dotdot="../..",
            dataframe_glimpse=glimpse,
            enable_data_download=self.enable_data_download,
            freshness=[fact for fact in freshness if fact],
        )

    def chart_page(self, record_id: str) -> str:
        """The Markdown page of one chart, from its record, its dataframe's record and the write-up.

        The chart's HTML is not read: the page embeds it by its path under
        the site, and the build copies the file there. "Chart updated" is
        the chart file's ``modified_at``; "Data updated" is its dataframe's,
        which for a table or query is the engine file's.
        """
        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        dataframe = self._input_dataframe(record)
        location = record.get("location") or {}
        pipeline_manifest = self._pipeline_manifest(pipeline)
        chart_manifest = self._chart_manifest(record, dataframe)
        chart_updated = _as_local(location.get("modified_at"))
        if chart_updated is not None:
            chart_date = chart_updated.strftime("%Y-%m-%d %H:%M:%S")
        else:
            chart_date = pipeline_manifest.get("source_last_modified_date")
        if dataframe is not None:
            dataframe_manifest = self._dataframe_manifest(dataframe, base_dir)
            data_updated = (dataframe.get("location") or {}).get("modified_at")
            link_to_dataframe_docs = self.link_to_dataframe(dataframe, from_kind="Chart")
            dataframe_id = _local_name(dataframe)
        else:
            dataframe_manifest, data_updated, link_to_dataframe_docs, dataframe_id = {}, None, "", ""
        freshness = [
            _freshness("Chart updated", location.get("modified_at")),
            _freshness("Data updated", data_updated),
        ]
        template = environment.from_string(_CHART_PAGE)
        return template.render(
            chart_manifest,
            write_up=self._write_up(record, base_dir, environment),
            provenance=panel(record_id, self.records, self._reversed),
            chart_manifest=chart_manifest,
            chart_id=_local_name(record),
            dataframe_id=dataframe_id,
            dataframe_manifest=dataframe_manifest,
            link_to_dataframe_docs=link_to_dataframe_docs,
            pipeline_id=record["pipeline"],
            pipeline_manifest=pipeline_manifest,
            path_to_html_chart_unix=base_dir / Path(location.get("path", "")),
            pipeline_page_link=self.pipeline_page_link(record),
            freshness=[fact for fact in freshness if fact],
            chart_date=chart_date,
            dot_or_dotdot="..",
            enable_data_download=self.enable_data_download,
        )

    def model_page(self, record_id: str) -> str:
        """The Markdown page of one model, from its record, its inputs' records and the write-up.

        Everything on the page is in the record: scores, versions, files,
        what it was trained on (its ``inputs``), and whether it is out of
        date (``stale_inputs``). The notice's "now" hashes are the inputs'
        own facts: a local dataframe's ``content_hash``, another pipeline's
        pin in ``pinned_inputs``. The model's bytes are never read.
        """
        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        location = record.get("location") or {}
        name = _local_name(record)
        kept = record.get("versions") or []
        versions = [
            {
                "name": version["version"],
                "made": f"{version['made_at'][:10]} {version['made_at'][11:16]} UTC",
                "commit": version["commit"][:7],
                "labels": ", ".join(f"`{label}`" for label in version.get("labels", [])),
                "metrics": {k: _format_metric(v) for k, v in (version.get("metrics") or {}).items()},
            }
            for version in reversed(kept)
        ]
        template = environment.from_string(_MODEL_PAGE_HEAD + "{{ write_up }}" + _MODEL_PAGE_TAIL)
        model_manifest = self._model_manifest(record)
        return template.render(
            model_manifest,
            write_up=self._write_up(record, base_dir, environment),
            provenance=panel(record_id, self.records, self._reversed),
            model_manifest=model_manifest,
            model_id=name,
            model_name=record.get("name", name),
            link_to_model_docs=f"../../models/{_slug(record['pipeline'])}/{name}.md",
            pipeline_id=record["pipeline"],
            pipeline_manifest=self._pipeline_manifest(pipeline),
            pipeline_page_link=self.pipeline_page_link(record),
            dot_or_dotdot="../..",
            metrics={k: _format_metric(v) for k, v in (record.get("metrics") or {}).items()},
            versions=versions,
            version_metrics=sorted({k for version in kept for k in (version.get("metrics") or {})}),
            trained_on=self._trained_on(record),
            staleness=self._staleness(record),
            model_files=[
                {"path": file["path"], "size": _format_size(file["size_bytes"])}
                for file in record.get("files") or []
            ],
            freshness=[fact for fact in [_freshness("Model updated", location.get("modified_at"))] if fact],
        )

    def pipeline_page(self, pipeline_id: str) -> str:
        """The Markdown page of one pipeline, from its record, its assets' records and the files they name.

        In the pipeline theme this is the site's front page: the README's
        text under the theme's `index.md`, with the tables of contents made
        from the records (notebooks, notes, dataframes, models, by name) and
        from the pipeline's own site pages (`site_pages`; `index_toc.md`
        among them is read and merged in). In a catalog it is the pipeline's
        README page, with its repository and site named above the text.
        """
        pipeline = self.records[pipeline_id]
        base_dir = Path(pipeline["location"]["value"])
        readme = self._readme_lines(pipeline, base_dir)
        if self.theme == "catalog":
            repo_url, site_url = pipeline.get("repo_url", ""), pipeline.get("site_url", "")
            return f"# `{pipeline_id}` {pipeline.get('name', '')} \n\n " + (
                f'Pipeline GitHub Repo <a href="{repo_url}">{repo_url}.</a>\n\n\n'
                + f'Pipeline Web Page <a href="{site_url}">{site_url}.</a>\n\n\n'
                + "".join(readme[2:])
            )
        environment = self._environment(base_dir)
        own = [self.records[i] for i in pipeline.get("assets", []) if i in self.records]
        notebooks = sorted((r for r in own if r["kind"] == "Notebook"), key=_local_name)
        notes = sorted((r for r in own if r["kind"] == "Note"), key=_local_name)
        slug = _slug(pipeline_id)
        site_pages = pipeline.get("site_pages") or []
        index_toc_content = ""
        if "index_toc.md" in site_pages and (pipeline.get("site_dir") or {}).get("resolved_path"):
            index_toc_content = (Path(pipeline["site_dir"]["resolved_path"]) / "index_toc.md").read_text()
        template = environment.get_template("index.md")
        return template.render(
            pipeline_manifest=self._pipeline_manifest(pipeline),
            dataframe_file_list=[self.dataframe_page_path(r) for r in self.records.values() if r["kind"] == "Dataframe"],
            model_file_list=[self.model_page_path(r) for r in self.records.values() if r["kind"] == "Model"],
            readme_text="".join(readme[2:]),
            pipeline_page_link="./index.md",
            dot_or_dotdot="cb",
            pipeline_id=pipeline_id,
            notebook_list=[
                f"{r.get('name', _local_name(r))} <cb/notebooks/{slug}/{Path((r.get('location') or {}).get('path', '')).stem}>"
                for r in notebooks
            ],
            notes_list=[f"cb/{_local_name(r)}.md" for r in notes],
            # The theme's front page lists the pipeline's own pages, but not
            # the two it merges or replaces at the root
            site_pages_list=[p for p in site_pages if "/" in p or p not in ("index_toc.md", "index.md")],
            index_toc_content=index_toc_content,
            show_code_updated=True,
            freshness=[fact for fact in [_freshness("Code updated", pipeline.get("code_changed_at"))] if fact],
        )

    # --- the catalog's own pages ---------------------------------------------

    #: The pages a catalog renders from its records, by path under the pages
    #: folder. `charts.md` and `contributing.md` are static files of the
    #: theme that the build copies; they are not rendered.
    CATALOG_PAGES = ("index.md", "cb/dataframes.md", "cb/models.md", "cb/pipelines.md", "cb/diagnostics.md")

    def catalog_page_paths(self) -> list:
        """The catalog pages this index has: `cb/models.md` only when some pipeline declares a model."""
        has_models = any(r["kind"] == "Model" for r in self.records.values())
        return [p for p in self.CATALOG_PAGES if has_models or p != "cb/models.md"]

    def catalog_page(self, page_path: str) -> str:
        """One of the catalog's own pages, from the `Catalog` record and the records of the site.

        The landing page and the lists are renderings of the records; the
        diagnostics page is a comparison the writer makes, of each record's
        declared fields against the policy the `Catalog` record carries (the
        build also writes the same comparison as a CSV file, which the page
        links to).
        """
        catalog = next((r for r in self.records.values() if r["kind"] == "Catalog"), None)
        if catalog is None:
            raise ValueError("This index has no Catalog record: it is a pipeline's, and a pipeline site has no catalog pages.")
        base_dir = Path((catalog.get("location") or {}).get("value") or self.docs_src_dir)
        environment = self._environment(base_dir)
        dataframes = sorted(self.dataframe_page_path(r) for r in self.records.values() if r["kind"] == "Dataframe")
        models = sorted(self.model_page_path(r) for r in self.records.values() if r["kind"] == "Model")
        if page_path == "index.md":
            return environment.get_template("index.md").render(
                manifest={"project": {"name": catalog.get("name", "")}},
                dataframe_file_list=dataframes,
                model_file_list=models,
                readme_text="",
                dot_or_dotdot="cb",
            )
        if page_path == "cb/dataframes.md":
            return environment.get_template("dataframes.md").render(
                dataframe_file_list=[p.removeprefix("cb/") for p in dataframes]
            )
        if page_path == "cb/models.md":
            return environment.get_template("models.md").render(
                model_file_list=[p.removeprefix("cb/") for p in models]
            )
        if page_path == "cb/pipelines.md":
            pipelines = {
                r["id"]: self._pipeline_manifest(r) for r in self.records.values() if r["kind"] == "Pipeline"
            }
            try:
                docs_src = Path(self.docs_src_dir).relative_to(base_dir).as_posix()
            except ValueError:
                docs_src = Path(self.docs_src_dir).as_posix()
            return environment.get_template("pipelines.md").render(
                manifest={"pipelines": pipelines},
                dot_or_dotdot=".",
                docs_src_dir=docs_src,
                show_code_updated=True,
            )
        if page_path == "cb/diagnostics.md":
            rows = self._diagnostics(catalog)
            summary = None
            if rows:
                complete = sum(1 for row in rows if row["Metadata Complete"])
                summary = {
                    "total_count": len(rows),
                    "complete_count": complete,
                    "incomplete_count": len(rows) - complete,
                    "complete_pct": round(100 * complete / len(rows), 1),
                    "incomplete_pct": round(100 * (1 - complete / len(rows)), 1),
                }
            required = self._required_fields(catalog)
            return environment.get_template("diagnostics.md").render(
                diagnostics_data=rows,
                diagnostics_summary=summary,
                required_fields=required,
                pipeline_field_count=len(required["project"]),
                dataframe_field_count=len(required["dataframes"]),
                chart_field_count=len(required["charts"]),
            )
        raise KeyError(f"No catalog page at {page_path!r}; the pages are {', '.join(self.CATALOG_PAGES)}.")

    @staticmethod
    def _required_fields(catalog: dict) -> dict:
        """The policy's required fields by object type: the record's, or ChartBook's defaults."""
        from chartbook.diagnostics import DEFAULT_REQUIRED_FIELDS

        declared = (catalog.get("policy") or {}).get("required") or {}
        return {kind: list(declared.get(kind, fields)) for kind, fields in DEFAULT_REQUIRED_FIELDS.items()}

    def _diagnostics(self, catalog: dict) -> list:
        """The diagnostics rows: each pipeline's and asset's declared fields against the policy.

        What the generator works out from the manifests, worked out from the
        records: a record carries the fields its entry declared, and its
        structure stands in for the rest — a `location` is the `path`, a
        `docs` is the write-up, a chart's `inputs` is its `dataframe`, a
        model's `inputs` are its `trained_on`.
        """
        from chartbook.diagnostics import _collect_missing_fields, _value_is_missing

        required = self._required_fields(catalog)
        rows = []
        kinds = {"Dataframe": "dataframes", "Chart": "charts", "Model": "models", "Notebook": "notebooks"}
        for pipeline_id in catalog.get("pipelines", []):
            pipeline = self.records.get(pipeline_id)
            if pipeline is None:
                continue
            project = {
                key: pipeline.get(key)
                for key in ("name", "description", "maintainer", "contributors", "os_compatibility", "repo_url",
                            "site_url", "copyright", "logo", "favicon")
            }
            # What the loader always fills, and the record states in another form
            project["build"] = (pipeline.get("scripts") or {}).get("build")
            project["readme"] = (pipeline.get("docs") or {}).get("path")
            project["site_dir"] = (pipeline.get("site_dir") or {}).get("path")
            project["id"], project["type"] = pipeline_id, "pipeline"
            project["enable_data_download"] = self.enable_data_download  # a bool is never missing
            missing = _collect_missing_fields(project, required["project"])
            rows.append(self._row("pipeline", pipeline.get("name", pipeline_id), pipeline_id, pipeline_id, missing, "../index.html"))
            for kind, table in kinds.items():
                if kind == "Notebook" and not required.get("notebooks"):
                    continue
                for record in [self.records[i] for i in pipeline.get("assets", []) if self.records.get(i, {}).get("kind") == kind]:
                    spec = self._as_declared(record)
                    missing = _collect_missing_fields(spec, required.get(table, []))
                    if kind in ("Dataframe", "Chart") and all(
                        _value_is_missing(spec.get(key)) for key in ("docs_path", "docs")
                    ):
                        missing.append("docs_path or docs")
                    name = _local_name(record)
                    slug = _slug(pipeline_id)
                    link = {
                        "Dataframe": f"./dataframes/{slug}/{name}.html",
                        "Chart": f"./charts/{slug}.{name}.html",
                        "Model": f"./models/{slug}/{name}.html",
                        "Notebook": "",
                    }[kind]
                    rows.append(self._row(kind.lower(), record.get("name", name), name, pipeline_id, missing, link))
        return rows

    def _as_declared(self, record: dict) -> dict:
        """A record as its manifest entry read, for the policy's rules.

        A record carries the fields its entry declared, and states the rest
        in another form; each is put back under the name the entry used, so
        that a policy may require any of them: `path`, `table`, `query` and
        `source` from the location; `docs_path` or `docs` from the write-up;
        a chart's `dataframe` from its inputs; a dataframe's `linked_charts`
        and `series` from the records that point at it; a model's
        `trained_on` from its inputs.
        """
        skip = {"kind", "version", "id", "ref", "pipeline", "location", "content_hash", "size_bytes", "row_count",
                "columns", "definition_hash", "date_range", "docs", "inputs", "files", "pinned_inputs",
                "trained_with", "inputs_now", "stale_inputs", "metrics", "versions"}
        spec = {key: value for key, value in record.items() if key not in skip}
        location = record.get("location") or {}
        if location.get("kind") == "file":
            spec["path"] = location.get("path")
        elif location.get("kind") in ("table", "query"):
            spec[location["kind"]] = location.get("identifier") or location.get("sql")
            spec["source"] = location.get("source")
        docs = record.get("docs") or {}
        if "path" in docs:
            spec["docs_path"] = docs["path"]
        if "text" in docs:
            spec["docs"] = docs["text"]
        kind = record.get("kind")
        if kind == "Chart" and record.get("inputs"):
            spec["dataframe"] = record["inputs"][0]
        if kind == "Dataframe":
            spec["linked_charts"] = [
                _local_name(self.records[other])
                for other in self._reversed["used_by"].get(record["id"], [])
                if self.records.get(other, {}).get("kind") == "Chart"
            ]
            spec["series"] = {
                _local_name(series): {}
                for series in self.records.values()
                if series.get("kind") == "Series" and series.get("declared") and series["id"].startswith(record["id"] + "#")
            }
        if kind == "Model":
            spec["trained_on"] = list(record.get("inputs") or [])
        return spec

    @staticmethod
    def _row(object_type, name, identifier, pipeline_id, missing, link) -> dict:
        return {
            "Name": name,
            "Metadata Complete": not missing,
            "Object Type": object_type,
            "Identifier": identifier,
            "Pipeline": pipeline_id,
            "Missing Fields": ", ".join(missing),
            "Page Link": link,
            "Page Link (HTML)": link,
        }

    def _readme_lines(self, pipeline: dict, base_dir: Path) -> list:
        """The pipeline's README, line by line, from the file its record names."""
        docs = pipeline.get("docs") or {}
        if not docs.get("path"):
            return []
        # readlines(), not splitlines(): a form feed or a NEL inside a line
        # is not a line break to the page
        with open(base_dir / docs["path"], encoding="utf-8") as file:
            return file.readlines()

    def _model_manifest(self, record: dict) -> dict:
        """The model as the templates read it: its declared fields and its path."""
        skip = {"kind", "version", "id", "ref", "pipeline", "location", "content_hash", "size_bytes",
                "files", "inputs", "pinned_inputs", "trained_with", "inputs_now", "stale_inputs", "metrics",
                "versions", "docs"}
        shown = {key: value for key, value in record.items() if key not in skip}
        shown["path"] = (record.get("location") or {}).get("path", "")
        return shown

    def _trained_on(self, record: dict) -> list:
        """What the page lists under "Trained On": a link to each input's page in this site, or its name.

        An input with no record is named with a note: its pipeline is in
        the site but does not declare it, or its pipeline is not in the site.
        """
        entries = []
        for input_id in record.get("inputs", []):
            other = self.records.get(input_id)
            if other is not None and other.get("kind") == "Dataframe":
                entries.append(
                    {
                        "label": input_id,
                        "name": other.get("name", ""),
                        "link": f"../../dataframes/{_slug(other['pipeline'])}/{_local_name(other)}.md",
                        "note": "",
                    }
                )
            else:
                owner = self.records.get(input_id.rsplit(":", 1)[0]) or {}
                note = (
                    "which that pipeline does not declare"
                    if owner.get("kind") == "Pipeline"
                    else "in another pipeline, which is not part of this site"
                )
                entries.append({"label": input_id, "name": "", "link": "", "note": note})
        return entries

    def _staleness(self, record: dict) -> Optional[dict]:
        """The out-of-date notice, if the record says the model is: which version, trained with what, what is there now.

        All three are on the record, keyed alike: ``trained_with`` (then),
        ``inputs_now`` (now) and ``stale_inputs`` (the comparison).
        """
        stale = record.get("stale_inputs") or []
        trained_with = record.get("trained_with") or {}
        if not stale or not trained_with:
            return None
        version = next(
            (v["version"] for v in record.get("versions") or [] if v.get("content_hash") == record.get("content_hash")),
            "",
        )
        return {"version": version, "trained_with": trained_with, "now": record.get("inputs_now") or {}, "stale": stale}

    # --- what the templates read, made from records ------------------------

    def _dataframe_manifest(self, record: dict, base_dir: Path) -> dict:
        """The dataframe as the templates read it: its declared fields, and where it is."""
        skip = {"kind", "version", "id", "ref", "pipeline", "location", "content_hash", "size_bytes",
                "row_count", "columns", "definition_hash", "date_range", "docs", "inputs"}
        shown = {key: value for key, value in record.items() if key not in skip}
        location = record.get("location") or {}
        # The charts made from this dataframe, by their local names
        shown["linked_charts"] = sorted(
            _local_name(other)
            for other_id in self._reversed["used_by"].get(record["id"], [])
            for other in [self.records.get(other_id, {})]
            if other.get("kind") == "Chart" and other.get("pipeline") == record["pipeline"]
        )
        if location.get("kind") == "table":
            shown["table"], shown["source"] = location.get("identifier"), location.get("source")
        elif location.get("kind") == "query":
            shown["query"], shown["source"] = location.get("sql"), location.get("source")
        else:
            shown["path"] = location.get("path", "")
            shown["_resolved_path"] = location.get("resolved_path") or str(base_dir / location.get("path", ""))
        return shown

    def _chart_manifest(self, record: dict, dataframe: Optional[dict]) -> dict:
        """The chart as the templates read it: its declared fields, its file and its dataframe."""
        skip = {"kind", "version", "id", "ref", "pipeline", "location", "content_hash", "size_bytes",
                "inputs", "docs"}
        shown = {key: value for key, value in record.items() if key not in skip}
        shown["path"] = (record.get("location") or {}).get("path", "")
        if dataframe is not None:
            shown["dataframe"] = _local_name(dataframe)
        return shown

    def _input_dataframe(self, record: dict) -> Optional[dict]:
        """The dataframe a chart was made from: the first of its inputs that is one."""
        for input_id in record.get("inputs", []):
            other = self.records.get(input_id)
            if other is not None and other.get("kind") == "Dataframe":
                return other
        return None

    def _pipeline_manifest(self, pipeline: dict) -> dict:
        """The pipeline as the templates read it: a `project` table, and its dataframes."""
        project = {
            key: pipeline.get(key, "")
            for key in ("name", "description", "maintainer", "contributors", "repo_url", "site_url", "os_compatibility")
        }
        project["build"] = (pipeline.get("scripts") or {}).get("build", "")
        dataframes = {
            _local_name(self.records[asset_id]): {}
            for asset_id in pipeline.get("assets", [])
            if self.records.get(asset_id, {}).get("kind") == "Dataframe"
        }
        shown = {"project": project, "dataframes": dataframes}
        if pipeline.get("code_changed_at"):
            moment = datetime.strptime(pipeline["code_changed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            shown["source_last_modified_date"] = moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return shown

    def _write_up(self, record: dict, base_dir: Path, environment: jinja2.Environment) -> str:
        """The write-up's text, from the file the record names, rendered as the generator does."""
        docs = record.get("docs") or {}
        if docs.get("text"):
            source = docs["text"]
        elif docs.get("path"):
            source = environment.loader.get_source(environment, Path(docs["path"]).as_posix())[0]
        else:
            source = ""
        return source

    def _environment(self, base_dir: Path) -> jinja2.Environment:
        package = Path(str(importlib.resources.files("chartbook")))
        theme_dir = package / ("docs_src_catalog" if self.theme == "catalog" else "docs_src_pipeline")
        paths = [base_dir]
        if self.docs_src_dir is not None:
            paths += [Path(self.docs_src_dir), Path(self.docs_src_dir) / "_templates"]
        paths += [package / "templates", theme_dir, theme_dir / "_templates"]
        environment = jinja2.Environment(loader=jinja2.FileSystemLoader([str(p) for p in paths]))
        environment.filters["yaml_escape"] = yaml_escape
        return environment

    # --- one entry point for the build ---------------------------------------

    def page(self, record: dict) -> str:
        """The page of any record that has one: dataframe, chart, model or pipeline."""
        return {
            "Dataframe": self.dataframe_page,
            "Chart": self.chart_page,
            "Model": self.model_page,
            "Pipeline": self.pipeline_page,
        }[record["kind"]](record["id"])


def _slug(pipeline_id: str) -> str:
    return pipeline_id.replace("/", "--")


def _local_name(record: dict) -> str:
    return record["ref"]["name"]


def _as_local(modified_at: Optional[str]) -> Optional[datetime]:
    """An index timestamp (UTC, to the second) as a local time, or None."""
    if not modified_at:
        return None
    return datetime.strptime(modified_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()


def _freshness(label: str, modified_at: Optional[str]):
    moment = _as_local(modified_at)
    return None if moment is None else freshness_fact(label, moment)


def freshness_fact(label: str, moment: Optional[datetime]) -> Optional[dict]:
    """One "<label> <when>" fact for a page's freshness line.

    The page says *when*, not *how long ago*: a generated page is static, so
    "2 days ago" worked out at build time would be wrong the next day, and
    would make every page differ from one build to the next. The timestamp
    goes into a ``<time>`` element and ``chartbook-freshness.js`` turns it
    into relative wording when the page is read.

    :returns: ``label``, ``iso`` (ISO 8601 with offset), ``title`` (hover
        text) and ``date`` (fallback text); None when *moment* is None.
    """
    if moment is None:
        return None
    local = moment.astimezone()
    return {
        "label": label,
        "iso": local.isoformat(timespec="seconds"),
        "title": local.strftime("%Y-%m-%d %H:%M %Z").strip(),
        "date": local.strftime("%Y-%m-%d"),
    }


def yaml_escape(value) -> str:
    """Escape a value for a YAML double-quoted scalar (the front matter of a chart page)."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def check_front_matter(page: Path, pipeline_id: str, chart_id: str) -> None:
    """Refuse a chart page whose YAML front matter does not parse: Sphinx would silently misfile it.

    :raises SystemExit: Through :class:`ChartBookError`, with the field to look at.
    """
    content = Path(page).read_text(encoding="utf-8")
    if not content.startswith("---"):
        return
    parts = content.split("---", 2)
    if len(parts) < 3:
        return
    try:
        yaml.safe_load(parts[1])
    except yaml.YAMLError as error:
        ChartBookError(
            message="Generated chart has malformed YAML frontmatter",
            file_path=Path(page),
            hint=(
                f"Chart '{pipeline_id}:{chart_id}' produced invalid YAML frontmatter. "
                f"This usually means a field in chartbook.toml (e.g. sources, "
                f"tags, name) contains characters that are unsafe in YAML "
                f"(colons, brackets, etc.).\nYAML error: {error}"
            ),
        ).exit_with_message()


def _format_size(size_bytes) -> str:
    """A file size for a person: ``18.2 KB``, ``4.1 MB``."""
    size = float(size_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _format_metric(value) -> str:
    """A score for a table: whole numbers whole, others to six significant digits."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, float):
        return str(value)
    return f"{value:.6g}"


def _most_recent_valid_datapoints(parquet_path: Path, date_col: str = "date", size_threshold_mb: float = 50):
    """The least and greatest of each column's last non-null date, as text, for the dataframe table.

    "N/A" without a date column or for a folder of parts; "N/A (large file)"
    over the size threshold, so a big file is not read for two dates.
    """
    if date_col in ("", "NA", "N/A"):
        return "N/A", "N/A"
    if is_glob_pattern(str(parquet_path)):
        return "N/A", "N/A"
    if os.path.getsize(parquet_path) / (1024 * 1024) > size_threshold_mb:
        return "N/A (large file)", "N/A (large file)"
    frame = pl.read_parquet(parquet_path)
    if frame[date_col].dtype != pl.Datetime:
        frame = frame.with_columns(pl.col(date_col).cast(pl.Datetime, strict=False))
    latest = frame.select(
        [pl.col(date_col).filter(pl.col(col).is_not_null()).max().alias(col) for col in frame.columns if col != date_col]
    )
    dates = [date for date in latest.row(0) if date is not None]
    if not dates:
        return "N/A", "N/A"
    return min(dates).strftime("%Y-%m-%d %H:%M:%S"), max(dates).strftime("%Y-%m-%d %H:%M:%S")


def _source_glimpse(record: dict, base_dir: Path) -> str:
    """A table or query's glimpse, from the engine the record's location names.

    The location's url is the manifest's, relative to the pipeline's folder
    for a DuckDB file; the machine's url comes through ``source_url()``, and
    a relative file is made absolute against the pipeline's folder, never
    against where the build happens to run.
    """
    from chartbook.backends import MEMORY_URL, DuckDBBackend, duckdb_path, source_url
    from chartbook.resolve import QueryLocation, TableLocation

    location = record["location"]
    where = (
        f"table {location['identifier']}" if location["kind"] == "table" else "query"
    ) + f" in source {location.get('source')!r} ({location.get('backend')})"
    if not location.get("url"):
        return f"A {where}."
    try:
        url = source_url(location["source"], location["url"])
        if url.startswith("duckdb://"):
            path = duckdb_path(url, base_dir)
            url = MEMORY_URL if path == ":memory:" else "duckdb:///" + path
    except Exception as error:  # noqa: BLE001 - a page, not a crash
        return f"A {where}. It could not be read when the site was built: {error}"
    if location["kind"] == "table":
        typed = TableLocation(location["source"], location["backend"], url, location["identifier"])
    else:
        typed = QueryLocation(location["source"], location["backend"], url, location["sql"])
    try:
        backend = DuckDBBackend(url)
        columns, rows = backend.describe(typed)
        sample = backend.scan(typed).head(5).collect()
    except Exception as error:  # noqa: BLE001 - a page, not a crash
        return f"A {where}. It could not be read when the site was built: {error}"
    lines = [f"A {where}: {rows} rows, {len(columns)} columns.", ""]
    lines += [f"  {column['name']}: {column['dtype']}" for column in columns]
    lines += ["", "First rows:", str(sample)]
    return "\n".join(lines)
