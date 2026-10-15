"""The Sphinx writer: pages for Sphinx, from the index and the files it names.

The first slice is the dataframe page. It renders today's templates with a
context built from the dataframe's record, its pipeline's record and the
files the records name, and it writes the same page the generator writes,
which a golden test holds it to. The pipeline and dataframe "manifests"
the templates read are made here from the records; the templates are
unchanged until the generator is gone, so that the two can be compared.
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

    # --- the link scheme ---------------------------------------------------

    def pipeline_page_link(self, pipeline_id: str) -> str:
        if self.theme == "pipeline":
            return "../../../index.md"
        return f"../pipelines/{_slug(pipeline_id)}_README.md"

    def dataframe_page_path(self, record: dict) -> str:
        """Where a dataframe's page is, under the pages folder."""
        return f"cb/dataframes/{_slug(record['pipeline'])}/{_local_name(record)}.md"

    def link_to_dataframe(self, record: dict) -> str:
        prefix = "../dataframes/" if self.theme == "pipeline" else ""
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
            glimpse = _source_glimpse(record)
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
            pipeline_page_link=self.pipeline_page_link(record["pipeline"]),
            most_recent_data_min=first,
            most_recent_data_max=last,
            dot_or_dotdot="../..",
            dataframe_glimpse=glimpse,
            enable_data_download=self.enable_data_download,
            freshness=[fact for fact in freshness if fact],
        )

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
        return jinja2.Environment(loader=jinja2.FileSystemLoader([str(p) for p in paths]))


def _slug(pipeline_id: str) -> str:
    return pipeline_id.replace("/", "--")


def _local_name(record: dict) -> str:
    return record["ref"]["name"]


def _freshness(label: str, modified_at: Optional[str]):
    from chartbook.markdown_generator import freshness_fact

    if not modified_at:
        return None
    moment = datetime.strptime(modified_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return freshness_fact(label, moment)


def _source_glimpse(record: dict) -> str:
    """A table or query's glimpse, from the engine the record's location names."""
    from chartbook.backends import DuckDBBackend, source_url
    from chartbook.resolve import QueryLocation, TableLocation

    location = record["location"]
    where = (
        f"table {location['identifier']}" if location["kind"] == "table" else "query"
    ) + f" in source {location.get('source')!r} ({location.get('backend')})"
    if not location.get("url"):
        return f"A {where}."
    url = source_url(location["source"], location["url"])
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
