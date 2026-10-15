"""The Sphinx writer: pages for Sphinx, from the index and the files it names.

The slices so far are the dataframe page and the chart page. Each renders
today's templates with a context built from the asset's record, its
pipeline's record, the records of its inputs and the files the records
name, and writes the same page the generator writes, which a golden test
holds it to. The pipeline, dataframe and chart "manifests" the templates
read are made here from the records; the templates are unchanged until the
generator is gone, so that the two can be compared.
"""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import jinja2

from chartbook.provenance import panel, reverse

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
            from chartbook.markdown_generator import DOCS_SRC_DIR

            self.docs_src_dir = Path(DOCS_SRC_DIR)
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
        """Where an asset's page is, under the pages folder."""
        return {
            "Dataframe": self.dataframe_page_path,
            "Chart": self.chart_page_path,
            "Model": self.model_page_path,
        }[record["kind"]](record)

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
            from chartbook.markdown_generator import find_most_recent_valid_datapoints, get_dataframe_glimpse

            glimpse = get_dataframe_glimpse(Path(resolved), size_threshold_mb=self.size_threshold)
            try:
                first, last = find_most_recent_valid_datapoints(
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
        from chartbook.markdown_generator import _MODEL_PAGE_HEAD, _MODEL_PAGE_TAIL, _format_metric, _format_size

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
            for key in ("name", "maintainer", "contributors", "repo_url", "site_url", "os_compatibility")
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
        from chartbook.markdown_generator import _yaml_escape_filter

        environment.filters["yaml_escape"] = _yaml_escape_filter
        return environment


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
    from chartbook.markdown_generator import freshness_fact

    moment = _as_local(modified_at)
    return None if moment is None else freshness_fact(label, moment)


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
