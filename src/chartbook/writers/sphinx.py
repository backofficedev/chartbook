"""The Sphinx writer: pages for Sphinx, from the index and the files it names.

The slices so far are the dataframe, chart, model, files and pipeline pages. Each
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
import posixpath
import re
import string
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
from chartbook.writers import ASSISTANT_FILE

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
{% if parts %}
## Parts

{{ parts.summary }}

| File | Size | Rows |{% for key in parts.partition_keys %} {{key}} |{% endfor %}
|------|------|------|{% for key in parts.partition_keys %}------|{% endfor %}
{% for part in parts.rows %}| {{part.path | literal}} | {{part.size}} | {{part.rows}} |{% for value in part.partition_values %} {{value | literal}} |{% endfor %}
{% endfor %}{% if parts.more %}
And {{parts.more}} more: `assets.files("{{dataframe_id}}")` gives every file.
{% endif %}
{% endif %}

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
- {% if dataframe.html_link %}<a href="{{dataframe.html_link}}">`{{dataframe.label}}`</a>{% elif dataframe.link %}[{{dataframe.label}}]({{dataframe.link}}){% else %}`{{dataframe.label}}`{% endif %}{% if dataframe.name %} - {{dataframe.name}}{% endif %}{% if dataframe.note %} ({{dataframe.note}}){% endif %}

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


#: The sections of a files asset's page: title and freshness, the write-up,
#: then its files, a preview, how to read it, the panel and the manifests.
_FILES_PAGE_HEAD = """# Files: `{{pipeline_id}}:file/{{files_id}}` - {{files_name}}

{% include "freshness.md" %}

"""

_FILES_PAGE_TAIL = """

## Files

{% if listing %}
{{ listing.summary }}

| File | Size |
|------|------|
{% for file in listing.rows %}| {{file.path | literal}} | {{file.size}} |
{% endfor %}{% if listing.more %}
And {{listing.more}} more: `assets.index("file/{{files_id}}")` lists every one.
{% endif %}
{% else %}
{{ not_built }}
{% endif %}
{% if preview %}
## Preview

{% if preview.kind == "image" %}{{ preview.path }}:

<img src="{{preview.src}}" alt="{{preview.alt}}" class="cb-thumbnail">

{% else %}The first lines of {{ preview.path }}:

{{preview.fence}}text
{{preview.text}}
{{preview.fence}}
{% endif %}
{% endif %}
## Reading Them

ChartBook keeps these files as they are and does not read them. In this pipeline:

```python
from chartbook import assets

paths = assets.files("file/{{files_id}}")      # every file, sorted
table = assets.index("file/{{files_id}}")      # path, size_bytes, sha256{% if listing and listing.partition_keys %} and the folders' keys{% endif %}: a LazyFrame
```

In a pipeline that depends on this one, name it `<dependency>:file/{{files_id}}`.

{% include "provenance.md" %}

## Files Manifest

{% include "file_manifest.md" %}

## Pipeline Manifest

{% include "pipeline_manifest.md" %}

"""

#: The most files a page lists; the index lists more (``chartbook.index.FILES_LISTED``), and `assets.index` all.
FILES_SHOWN = 50


def _is_from_the_store(record: dict) -> bool:
    """Whether a record is of a pipeline the catalog shows from the store alone."""
    return record.get("kind") == "Pipeline" and (record.get("location") or {}).get("kind") == "store"


#: HTML's own characters, and what stands in for each in someone else's text:
#: look-alikes that no normalization turns back, and a word
_LOOK_ALIKES = str.maketrans({"<": "‹", ">": "›", "&": " and ", '"': "”", "'": "’", "`": "‘"})


def _without_html(character: str) -> str:
    """A character, or, if any normalization of it holds one of HTML's own characters, that form with look-alikes.

    A fullwidth ``＜`` or a small ``﹠`` normalizes (NFKC) to ``<`` or ``&``,
    and ``≮`` decomposes (NFKD) to ``<`` and a combining mark; each is
    caught as ``<`` and ``&`` are. Anything else is kept as written: ``R²``,
    ``CO₂`` and ``…`` stay. One character at a time is enough, as
    composing characters never makes an ASCII one.
    """
    import unicodedata

    form = unicodedata.normalize("NFKD", character)
    if any(c in form for c in "<>&\"'`"):
        return form.translate(_LOOK_ALIKES)
    return character


def _as_text(value: object) -> str:
    """Text someone else wrote, made safe to set into a page: it shows as written and is never read as markup.

    The text is one line of what can be seen (:func:`chartbook.identity.plain_line`).
    HTML's own characters (``< > " '`` and the backtick) are replaced by
    look-alikes, and ``&`` by "and", as is any character that normalizes to
    one of them (:func:`_without_html`), since a page title, a search index
    or a theme may decode the text and set it into HTML again; then each
    other ASCII punctuation character becomes its numeric character
    reference. CommonMark (and so MyST), Python-Markdown and HTML show a
    character reference as its character and never read it as syntax: no
    role, directive, link, list, table cell or HTML element can start in
    the text, decoded or not, and it cannot leave an HTML attribute either.
    """
    from chartbook.identity import plain_line

    text = " ".join("".join(_without_html(c) for c in plain_line(value)).split())
    return "".join(f"&#{ord(c)};" if c in string.punctuation else c for c in text)


def _one_line(text: object, longest: int = 200) -> str:
    """Text as one line of what can be seen, cut at a word to at most ``longest`` characters (with an ellipsis when cut)."""
    from chartbook.identity import plain_line

    line = plain_line(text, longest + 1)
    if len(line) <= longest:
        return line
    cut = line[: longest - 1]
    if line[longest - 1] != " ":
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" .,;:") + "…"


#: A git commit as a record names it, and the time a snapshot was made (UTC)
_COMMIT = re.compile(r"[0-9a-f]{7,64}")
_MADE_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


#: The longest value set into a page as code; a longer one is cut, with an ellipsis
_LONGEST_CODE = 200


def _code(value: object) -> str:
    """A record's value as inline code; as :func:`_as_text` when it has what would end the code or the table cell it is in.

    Either way it is one line of what can be seen (:func:`chartbook.identity.plain_line`):
    no control or direction-changing character, and at most :data:`_LONGEST_CODE`
    characters.
    """
    from chartbook.identity import plain_line

    text = plain_line(str(value), _LONGEST_CODE + 1)
    if len(text) > _LONGEST_CODE:
        text = text[: _LONGEST_CODE - 1] + "…"
    if text and not any(c in text for c in "`|\\<>"):
        return f"`{text}`"
    return _as_text(text)


def _literal(value: object, escape_pipes: bool = True) -> str:
    """A value that must stay exactly as written, a path or a table's name, as inline code in a table cell.

    Unlike :func:`_code`, nothing is cut or rewritten, so that it can be
    copied: spaces, backslashes and ``&`` stay. Only control and
    direction-changing characters are taken out. A backtick in it gets a
    longer fence. A pipe would end the table cell: it is written ``\\|``,
    which markdown-it (MyST) reads back as a pipe in a cell, code or not.
    Python-Markdown (MkDocs) reads a pipe in code as text and would show the
    backslash, so the MkDocs writer passes ``escape_pipes=False``.
    """
    text = "".join(c for c in str(value) if c == " " or c.isprintable())
    if not text:
        return ""
    if escape_pipes:
        text = text.replace("|", "\\|")
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    # CommonMark takes one space off each end of code that starts and ends with one
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _link_text(text: str) -> str:
    """Text set into the assistant file, with a backslash before what would start a link, an autolink or code."""
    return "".join("\\" + c if c in "\\[]<>`" else c for c in text)


def _local_or_id(record: dict) -> str:
    """A record's local name, or its ID when it has none (a pipeline)."""
    return (record.get("ref") or {}).get("name") or record["id"]


def _from_the_store(record: dict) -> dict:
    """A pipeline's record from the store, as the writer shows it: what it says of itself as text, and plain web links.

    Anyone who can write to the store wrote these, through the snapshot's
    own index, and the catalog's site is built as the catalog's own, where a
    directive could read a file on this machine: so only the fields the
    pages show are kept, each as :func:`_as_text`, and a link only when it
    is a plain web address.
    """
    from chartbook.identity import web_link

    shown = {key: record[key] for key in ("kind", "version", "id", "snapshots") if key in record}
    shown["location"] = {"kind": "store"}
    for key in ("name", "description", "maintainer"):
        if _as_text(record.get(key)):
            shown[key] = _as_text(record[key])
    shown.setdefault("name", _as_text(record["id"]))
    for key in ("repo_url", "site_url"):
        if web_link(record.get(key)):
            shown[key] = web_link(record[key])
    # Its assets, as its newest snapshot lists them: each an ID of this
    # pipeline's that reads as one, and its name as text
    shown["assets"] = [asset_id for asset_id in record.get("assets") or [] if _own_asset(record["id"], asset_id)]
    names = record.get("asset_names") if isinstance(record.get("asset_names"), dict) else {}
    shown["asset_names"] = {
        asset_id: _as_text(names[asset_id]) for asset_id in shown["assets"] if _as_text(names.get(asset_id))
    }
    return shown


def _own_asset(pipeline_id: str, asset_id: object):
    """An asset ID as a reference, if it reads as one of this pipeline's assets with no part or revision; else None."""
    from chartbook.refs import parse_asset_ref

    try:
        ref = parse_asset_ref(asset_id) if isinstance(asset_id, str) else None
    except ValueError:
        return None
    if ref is None or ref.pipeline_id != pipeline_id or ref.registry or ref.part or ref.rev:
        return None
    return ref


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
    :param size_threshold: Files over this many megabytes get no date
        range. The glimpse reads only the first rows, at any size.
    :param enable_data_download: Whether pages link to downloads.
    """

    #: Whether the theme's ``_templates`` folder belongs in the site tree: Sphinx reads its HTML templates there.
    THEME_TEMPLATES_IN_SITE = True

    index: dict
    theme: str = "pipeline"
    docs_src_dir: Optional[Path] = None
    size_threshold: float = 50
    enable_data_download: bool = False
    records: dict = field(init=False)
    _reversed: dict = field(init=False)

    def __post_init__(self):
        self.records = {
            record["id"]: _from_the_store(record) if _is_from_the_store(record) else record
            for record in self.index.get("records", [])
        }
        self._reversed = reverse(self.records)
        if self.docs_src_dir is None:
            self.docs_src_dir = Path("_docs_src").resolve()
        for record in self.records.values():
            location = record.get("location") or {}
            if record.get("kind") == "Pipeline" and location.get("kind") != "store" and not location.get("value"):
                raise ValueError(
                    "SphinxWriter needs the full index, the one the build directory holds, "
                    "not the published one beside the site: it reads the files the index "
                    "names, and the published index has no local paths."
                )

    # --- the link scheme ---------------------------------------------------

    def pipeline_page_link(self, record: dict) -> str:
        """The link from an asset's page to its pipeline's page.

        Relative to the page: in the pipeline theme up to the site's root,
        in a catalog up to `cb/` and into `pipelines/`.
        """
        depth = self.page_path(record).count("/")
        if self.theme == "pipeline":
            return "../" * depth + "index.md"
        return "../" * (depth - 1) + f"pipelines/{_slug(record['pipeline'])}_README.md"

    def page_path(self, record: dict) -> str:
        """Where a record's page is, under the pages folder."""
        return {
            "Dataframe": self.dataframe_page_path,
            "Chart": self.chart_page_path,
            "Model": self.model_page_path,
            "File": self.files_page_path,
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

    def files_page_path(self, record: dict) -> str:
        """Where a files asset's page is, under the pages folder."""
        return f"cb/files/{_slug(record['pipeline'])}/{_local_name(record)}.md"

    def link_to_dataframe(self, record: dict, from_kind: str = "Dataframe") -> str:
        """The link to a dataframe's page from a page of the given kind, relative to that page.

        A dataframe page is at `cb/dataframes/<pipeline>/<name>.md`, a chart
        page at `cb/charts/<pipeline>.<name>.md`, a model page at
        `cb/models/<pipeline>/<name>.md`; the same in both themes.
        """
        target = f"{_slug(record['pipeline'])}/{_local_name(record)}.md"
        if from_kind == "Dataframe":
            return f"../{target}"
        if from_kind == "Model":
            return f"../../dataframes/{target}"
        return f"../dataframes/{target}"

    # --- the pages ---------------------------------------------------------

    def dataframe_page(self, record_id: str) -> str:
        """The Markdown page of one dataframe, from its record and the files it names."""
        from chartbook.sitefiles import downloadable, not_built, not_built_text

        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        location = record.get("location") or {}
        dataframe_manifest = self._dataframe_manifest(record, base_dir)
        unbuilt = not_built(record)
        if location.get("kind") in ("table", "query"):
            glimpse = _source_glimpse(record, base_dir)
            span = record.get("date_range") or {}
            first, last = span.get("first"), span.get("last")
            freshness = [_freshness("Data updated", location.get("modified_at"))]
        elif unbuilt:
            # Declared and not built yet: the provenance panel says so too.
            # The glimpse is shown as code, so this is plain text, and there
            # are no dates to give
            glimpse = not_built_text(path=location.get("path", ""), command="chartbook build")
            first, last = None, None
            freshness = []
        else:
            resolved = location.get("resolved_path") or str(base_dir / location.get("path", ""))
            glimpse = get_dataframe_glimpse(Path(resolved))
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
            provenance=self._panel(record_id, self.page_path(record)),
            dataframe_manifest=dataframe_manifest,
            link_to_dataframe_docs=self.link_to_dataframe(record),
            dataframe_id=_local_name(record),
            pipeline_id=record["pipeline"],
            pipeline_manifest=self._pipeline_manifest(pipeline),
            pipeline_page_link=self.pipeline_page_link(record),
            # A date that is not known is not shown, rather than said "None"
            most_recent_data_min="" if first is None else first,
            most_recent_data_max="" if last is None else last,
            dot_or_dotdot="../..",
            dataframe_glimpse=glimpse,
            parts=_parts(record),
            # Only a file the build copies for download is linked
            enable_data_download=self.enable_data_download and downloadable(record),
            freshness=[fact for fact in freshness if fact],
        )

    def chart_page(self, record_id: str) -> str:
        """The Markdown page of one chart, from its record, its dataframe's record and the write-up.

        The chart's HTML is not read: the page embeds it by its path under
        the site, and the build copies the file there. "Chart updated" is
        the chart file's ``modified_at``; "Data updated" is its dataframe's,
        which for a table or query is the engine file's.
        """
        from chartbook.sitefiles import downloadable

        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        dataframe = self._input_dataframe(record)
        location = record.get("location") or {}
        pipeline_manifest = self._pipeline_manifest(pipeline)
        chart_manifest = self._chart_manifest(record, dataframe)
        # The chart listing's date is the one time on the site in the build
        # machine's local time, with no zone named: ABlog publishes a post
        # dated before its next local midnight, and keeps any later one as a
        # draft, out of every listing. A chart written in the evening west of
        # UTC is dated tomorrow in UTC. A time still to come (a skewed clock,
        # copied times, a commit dated ahead) is taken as now, for the same reason
        chart_updated = _as_utc(location.get("modified_at") or pipeline.get("code_changed_at"))
        if chart_updated is not None:
            chart_updated = min(chart_updated, datetime.now(timezone.utc))
        chart_date = chart_updated.astimezone().strftime("%Y-%m-%d %H:%M:%S") if chart_updated is not None else None
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
            provenance=self._panel(record_id, self.page_path(record)),
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
            # Its dataframe's manifest is on the page, with a download only of a file the build copies
            enable_data_download=self.enable_data_download and dataframe is not None and downloadable(dataframe),
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
            provenance=self._panel(record_id, self.page_path(record)),
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
            trained_on=self._trained_on(record, self.page_path(record)),
            staleness=self._staleness(record),
            model_files=[
                {"path": file["path"], "size": _format_size(file["size_bytes"])}
                for file in record.get("files") or []
            ],
            freshness=[fact for fact in [_freshness("Model updated", location.get("modified_at"))] if fact],
        )

    def files_page(self, record_id: str) -> str:
        """The Markdown page of one files asset, from its record and the write-up.

        Its files are as the record lists them: how many, how large, of
        which types, and the first :data:`FILES_SHOWN`. The one file read is
        the one previewed, the first the record lists that a preview can
        show, and only its first few KB (:func:`chartbook.files.preview_of`).
        """
        from chartbook.sitefiles import not_built_text, thumbnail_path

        record = self.records[record_id]
        pipeline = self.records[record["pipeline"]]
        base_dir = Path(pipeline["location"]["value"])
        environment = self._environment(base_dir)
        location = record.get("location") or {}
        name = _local_name(record)
        preview = self.files_preview(record)
        if preview is not None:
            src = "../" * self.files_page_path(record).count("/") + thumbnail_path(record, preview)
            preview = dict(preview, path=_code(preview["path"]))
            if preview["kind"] == "image":
                preview["src"] = src
                preview["alt"] = _as_text(Path(preview["file"]).name)
            else:
                longest = max((len(run) for run in re.findall(r"`+", preview["text"])), default=0)
                preview["fence"] = "`" * max(3, longest + 1)
        template = environment.from_string(_FILES_PAGE_HEAD + "{{ write_up }}" + _FILES_PAGE_TAIL)
        files_manifest = self._files_manifest(record)
        return template.render(
            files_manifest=files_manifest,
            write_up=self._write_up(record, base_dir, environment),
            provenance=self._panel(record_id, self.page_path(record)),
            files_id=name,
            files_name=record.get("name", name),
            link_to_files_docs=f"../../files/{_slug(record['pipeline'])}/{name}.md",
            pipeline_id=record["pipeline"],
            pipeline_manifest=self._pipeline_manifest(pipeline),
            pipeline_page_link=self.pipeline_page_link(record),
            dot_or_dotdot="../..",
            listing=_listing(record),
            not_built=not_built_text(path=_code(location.get("path", "")), command="`chartbook build`"),
            preview=preview,
            freshness=[fact for fact in [_freshness("Files updated", location.get("modified_at"))] if fact],
        )

    def files_preview(self, record: dict) -> Optional[dict]:
        """What a files asset's page previews, from the files its record lists (:func:`chartbook.files.preview_of`)."""
        from chartbook.files import listing_root, preview_of

        resolved = (record.get("location") or {}).get("resolved_path")
        if not resolved or not record.get("content_hash"):
            return None
        return preview_of(record.get("files") or [], listing_root(resolved))

    def _files_manifest(self, record: dict) -> dict:
        """The files asset as the templates read it: its declared fields and its path."""
        skip = {"kind", "version", "id", "ref", "pipeline", "location", "content_hash", "size_bytes",
                "file_count", "extensions", "files", "docs"}
        shown = {key: value for key, value in record.items() if key not in skip}
        shown["path"] = (record.get("location") or {}).get("path", "")
        return shown

    def pipeline_page(self, pipeline_id: str) -> str:
        """The Markdown page of one pipeline, from its record, its assets' records and the files they name.

        In the pipeline theme this is the site's front page: the README's
        text under the theme's `index.md`, with the tables of contents made
        from the records (notebooks, notes, dataframes, models, by name) and
        from the pipeline's own site pages (`site_pages`; `index_toc.md`
        among them is read and merged in). In a catalog it is the pipeline's
        README page, with its repository and site named above the text.
        Either way it lists the pipelines it depends on, with what each is
        pinned to (:meth:`_dependencies`).
        """
        pipeline = self.records[pipeline_id]
        if (pipeline.get("location") or {}).get("kind") == "store":
            return self._from_the_store_page(pipeline)
        base_dir = Path(pipeline["location"]["value"])
        readme = self._readme_lines(pipeline, base_dir)
        environment = self._environment(base_dir)
        dependencies = self._dependencies(pipeline, self.pipeline_page_path(pipeline))
        if self.theme == "catalog":
            repo_url, site_url = pipeline.get("repo_url", ""), pipeline.get("site_url", "")
            page = f"# `{pipeline_id}` {pipeline.get('name', '')} \n\n " + (
                f'Pipeline GitHub Repo <a href="{repo_url}">{repo_url}.</a>\n\n\n'
                + f'Pipeline Web Page <a href="{site_url}">{site_url}.</a>\n\n\n'
                + "".join(readme[2:])
            )
            if dependencies:
                page += "\n\n" + environment.get_template("pipeline_dependencies.md").render(dependencies=dependencies)
            return page
        own = [self.records[i] for i in pipeline.get("assets", []) if i in self.records]
        notebooks = sorted((r for r in own if r["kind"] == "Notebook"), key=_local_name)
        notes = sorted((r for r in own if r["kind"] == "Note"), key=_local_name)
        slug = _slug(pipeline_id)
        site_pages = pipeline.get("site_pages") or []
        index_toc_content = ""
        if "index_toc.md" in site_pages and (pipeline.get("site_dir") or {}).get("resolved_path"):
            index_toc_content = (Path(pipeline["site_dir"]["resolved_path"]) / "index_toc.md").read_text(encoding="utf-8")
        template = environment.get_template("index.md")
        return template.render(
            pipeline_manifest=self._pipeline_manifest(pipeline),
            dataframe_file_list=[self.dataframe_page_path(r) for r in self.records.values() if r["kind"] == "Dataframe"],
            model_file_list=[self.model_page_path(r) for r in self.records.values() if r["kind"] == "Model"],
            files_file_list=[self.files_page_path(r) for r in self.records.values() if r["kind"] == "File"],
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
            version=_laid_out_version(pipeline),
            dependencies=dependencies,
        )

    # --- the assistant file --------------------------------------------------

    #: The assistant file's name, at the site's root beside `index.json`
    ASSISTANT_FILE = ASSISTANT_FILE

    #: The kinds the assistant file lists, under these headings, in this order
    ASSISTANT_SECTIONS = (
        ("Pipeline", "Pipelines"), ("Dataframe", "Dataframes"), ("Chart", "Charts"), ("Model", "Models"), ("File", "Files")
    )

    #: How many versions of a pipeline the assistant file lists, newest first;
    #: the versions page lists them all
    ASSISTANT_VERSIONS = 10

    def assistant_file(self) -> str:
        """The site as an assistant reads it: one line per pipeline, dataframe, chart, model and files asset, with where its page is.

        In the llms.txt form: the site's name as the title, what it is as the
        summary, then a list per kind, each line ``- [name](page): `ID`.
        “Description”``, every link relative to the site's root, where the
        file is. In a catalog, each pipeline's line has its newest versions
        under it, each linking the version site's own assistant file. The
        records in full are in ``index.json`` beside it.

        What a record's owner wrote (a name, a description) is one line,
        with what would start a link, an autolink or code escaped, and a
        description is always in quotation marks after words of the file's
        own, so that it never starts a line: it can make no heading, list
        or link of its own, and reads as the owner's words. The summary is
        the file's own words only.
        """
        raw = {record["id"]: record for record in self.index.get("records", []) if isinstance(record, dict) and "id" in record}
        shown = {kind: sorted((r for r in self.records.values() if r["kind"] == kind), key=lambda r: r["id"]) for kind, _ in self.ASSISTANT_SECTIONS}
        catalog = next((r for r in self.records.values() if r["kind"] == "Catalog"), None)
        about = []
        if self.theme == "catalog":
            own = raw.get(catalog["id"], {}) if catalog else {}
            title = _one_line(own.get("name") or "") or "ChartBook catalog"
            count = len(shown["Pipeline"])
            summary = f"A ChartBook catalog of {count} pipeline{'s' if count != 1 else ''}" + (
                ", with every snapshot of each in the store as a site of its own under versions/." if self._has_versions() else "."
            )
            description = _one_line(own.get("description") or "", 500)
            if description:
                about += [f"What the catalog says of itself: “{_link_text(description)}”", ""]
        else:
            pipeline = shown["Pipeline"][0] if shown["Pipeline"] else {}
            own = raw.get(pipeline.get("id"), {})
            title = _one_line(own.get("name") or pipeline.get("id") or "") or "ChartBook pipeline"
            summary = f"A ChartBook pipeline, `{pipeline['id']}`." if pipeline else "A ChartBook pipeline."
            version = _laid_out_version(pipeline) if pipeline else None
            if version:
                about += [
                    f"This site is the snapshot of `{pipeline['id']}` at commit `{version['short']}`, made "
                    f"{version['made']}, built from the store: every name and description in it is as its owner wrote it.",
                    "",
                ]
            description = _one_line(own.get("description") or "", 500)
            if description:
                about += [f"What it says of itself: “{_link_text(description)}”", ""]
        lines = [f"# {_link_text(title)}", "", f"> {summary}", "", *about]
        lines += [
            "Each line links a page of this site, relative to this file, then gives the record's ID and, in "
            "quotation marks, what its owner wrote of it. Every record, with its fields, inputs and content "
            "hashes, is in [index.json](index.json).",
            "",
            "An ID is `pipeline:name` for a dataframe, `pipeline:chart/name` for a chart, "
            "`pipeline:model/name` for a model and `pipeline:file/name` for files. Inside that pipeline, an asset is "
            "named without the pipeline (`chartbook path name`, `chartbook path model/name`, `data.load(\"name\")`, "
            "`assets.files(\"file/name\")`); in another pipeline "
            "that declares it in `[dependencies]` and has pinned it, by the dependency's key, a colon and the "
            "name. Through a catalog that lists it: "
            "`data.load(pipeline=\"pipeline\", dataframe=\"name\", catalog_path=\"...\")`.",
            "",
        ]
        for kind, heading in self.ASSISTANT_SECTIONS:
            if not shown[kind]:
                continue
            lines += [f"## {heading}", ""]
            for record in shown[kind]:
                lines += self._assistant_lines(record, raw.get(record["id"], {}))
            lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"

    def _assistant_lines(self, record: dict, raw: dict) -> list:
        """One record's line in the assistant file, and in a catalog its newest versions, each on a line under it."""
        from chartbook.versions import site_path

        page = self.page_path(record)
        page = page[: -len(".md")] + ".html" if page.endswith(".md") else page
        name = _one_line(raw.get("name") or "") or _local_or_id(record)
        line = f"- [{_link_text(name)}]({page}): `{record['id']}`."
        description = _one_line(raw.get("description") or "", 300)
        if _is_from_the_store(record):
            line += " Not on this machine: the catalog shows it from its snapshots in the store."
            if description:
                line += f" Its newest snapshot says: “{_link_text(description)}”"
        elif description:
            line += f" “{_link_text(description)}”"
        lines = [line]
        listed = (record.get("snapshots") or []) if self.theme == "catalog" else []
        for entry in listed[: self.ASSISTANT_VERSIONS]:
            try:
                root = site_path(record["id"], entry["name"])
            except (KeyError, ValueError):
                continue
            made = f"{entry['made_at'][:10]} {entry['made_at'][11:19]} UTC"
            if entry.get("rendered", True):
                lines.append(f"  - Version `{entry['commit'][:7]}`, made {made}: [its llms.txt]({root}/{self.ASSISTANT_FILE})")
            else:
                lines.append(f"  - Version `{entry['commit'][:7]}`, made {made}, whose site could not be built: [why]({root}/index.html)")
        older = len(listed) - self.ASSISTANT_VERSIONS
        if older > 0:
            lines.append(f"  - {older} older version{'s' if older != 1 else ''}: [the versions page](cb/versions.html)")
        return lines

    # --- the catalog's own pages ---------------------------------------------

    #: The pages a catalog renders from its records, by path under the pages
    #: folder. `charts.md` and `contributing.md` are static files of the
    #: theme that the build copies; they are not rendered.
    CATALOG_PAGES = (
        "index.md", "cb/dataframes.md", "cb/models.md", "cb/files.md", "cb/pipelines.md", "cb/diagnostics.md", "cb/versions.md"
    )

    def own_page_paths(self) -> list:
        """The site's own pages this writer renders besides the records': a catalog's pages; none for a pipeline site."""
        return self.catalog_page_paths() if self.theme == "catalog" else []

    def own_page(self, page_path: str) -> str:
        """One of :meth:`own_page_paths`."""
        return self.catalog_page(page_path)

    def catalog_page_paths(self) -> list:
        """The catalog pages this index has: `cb/models.md` only when some pipeline declares a model,
        `cb/files.md` only when some pipeline declares files, `cb/versions.md` only when some pipeline
        has a snapshot in the store."""
        has_models = any(r["kind"] == "Model" for r in self.records.values())
        has_files = any(r["kind"] == "File" for r in self.records.values())
        has_versions = self._has_versions()
        return [
            p for p in self.CATALOG_PAGES
            if (has_models or p != "cb/models.md") and (has_files or p != "cb/files.md")
            and (has_versions or p != "cb/versions.md")
        ]

    def _has_versions(self) -> bool:
        return any(r["kind"] == "Pipeline" and r.get("snapshots") for r in self.records.values())

    def _from_the_store_page(self, pipeline: dict) -> str:
        """The page of a pipeline the catalog shows from the store alone: what it is, and its versions."""
        from chartbook.versions import site_path

        # The record's text is already plain (see _from_the_store): never markup
        lines = [f"# `{pipeline['id']}` {pipeline.get('name', '')}", ""]
        lines.append(
            "Not on this machine: the catalog shows this pipeline from the store, each snapshot "
            "as its owner declared it ready."
        )
        lines.append("")
        snapshots = pipeline.get("snapshots") or []
        said = [
            (label, pipeline[key])
            for label, key in (("Maintainer", "maintainer"), ("Repository", "repo_url"), ("Web page", "site_url"))
            if pipeline.get(key)
        ]
        if pipeline.get("description") or said:
            lines += ["As its newest snapshot describes it:", ""]
        if pipeline.get("description"):
            lines += [pipeline["description"], ""]
        for label, value in said:
            shown = f'<a href="{value}">{value}</a>' if label != "Maintainer" else value
            lines += [f"{label}: {shown}", ""]
        if snapshots:
            newest = snapshots[0]
            made = f"{newest['made_at'][:10]} {newest['made_at'][11:16]} UTC"
            target = site_path(pipeline["id"], newest["name"])
            lines.append(
                f'The newest snapshot: <a href="../../{target}/index.html">`{newest["commit"][:7]}`, made {made}</a>. '
                f"[Every version](../versions.md)."
            )
            assets = self.from_the_store_assets(
                ("dataframe", "chart", "model", "file"), self.pipeline_page_path(pipeline), pipeline["id"]
            )
            if assets:
                lines += ["", "What its newest snapshot holds, each linked to its page there:", ""]
                lines += [
                    f'- and {a["more"]} more, in <a href="{a["link"]}">the snapshot\'s site</a>'
                    if a.get("more")
                    else f'- <a href="{a["link"]}">{a["title"]}</a> · {a["kind"]} `{a["id"]}`'
                    for a in assets
                ]
        else:
            lines.append("No snapshot of it is in the store yet.")
        return "\n".join(lines) + "\n"

    def from_the_store_assets(self, kinds: tuple, from_path: str, pipeline_id: Optional[str] = None) -> list:
        """The assets of the pipelines shown from the store alone, as each one's newest snapshot lists them.

        Each is linked to its page in that snapshot's site, relative to the
        page at *from_path*, or to the page there that says why the site
        could not be built; one of a kind with no page (a notebook, a note)
        is left out. The title is the asset's name as text
        (:func:`_as_text`), else its name in its pipeline. At most
        :data:`chartbook.snapshot.STORED_ASSETS_SHOWN` of each pipeline's are
        listed, since anyone who can write to the store chose how many there
        are; then one entry with ``more``, how many are not, linked to the
        snapshot's site.

        :param kinds: The kinds to list, as a reference names them: ``dataframe``, ``chart``, ``model``, ``file``.
        :param pipeline_id: Only this pipeline's; every one's by default.
        :returns: Each as ``{"kind", "id", "title", "pipeline", "link"}``, by pipeline, then kind, then name.
        """
        from chartbook.snapshot import STORED_ASSETS_SHOWN
        from chartbook.versions import site_path

        listed = []
        for pipeline in sorted((r for r in self.records.values() if _is_from_the_store(r)), key=lambda r: r["id"]):
            if pipeline_id is not None and pipeline["id"] != pipeline_id:
                continue
            newest = (pipeline.get("snapshots") or [{}])[0]
            own = []
            for asset_id in pipeline.get("assets") or []:
                ref = _own_asset(pipeline["id"], asset_id)
                if ref is None or ref.kind not in kinds:
                    continue
                link = self._version_page(from_path, asset_id, newest.get("commit"), newest.get("made_at"))
                if link:
                    title = (pipeline.get("asset_names") or {}).get(asset_id) or _as_text(ref.name)
                    own.append({"kind": ref.kind, "id": asset_id, "title": title, "pipeline": pipeline["id"], "link": link})
            own.sort(key=lambda a: (kinds.index(a["kind"]), a["id"]))
            listed += own[:STORED_ASSETS_SHOWN]
            if len(own) > STORED_ASSETS_SHOWN:
                root = "../" * from_path.count("/") + site_path(pipeline["id"], newest["name"])
                listed.append({"more": len(own) - STORED_ASSETS_SHOWN, "pipeline": pipeline["id"], "link": f"{root}/index.html"})
        return listed

    def _versions(self) -> list:
        """Each pipeline with its working version and its snapshots, for the versions page.

        A snapshot is said to be pinned by each pipeline of the site whose
        lockfile pins it, by commit and time, as its record says.
        """
        from chartbook.versions import site_path

        pinned: dict = {}
        for record in self.records.values():
            if record["kind"] != "Pipeline":
                continue
            for dependency in record.get("dependencies") or []:
                commit = (dependency.get("location") or {}).get("commit")
                if commit and dependency.get("snapshot"):
                    pinned.setdefault((dependency["id"], commit, dependency["snapshot"]), []).append(record["id"])
        pipelines = []
        for record in sorted((r for r in self.records.values() if r["kind"] == "Pipeline"), key=lambda r: r["id"]):
            versions = [
                {
                    "short": entry["commit"][:7],
                    "made": f"{entry['made_at'][:10]} {entry['made_at'][11:16]} UTC",
                    "link": f"../{site_path(record['id'], entry['name'])}/index.html",
                    "built_by_run": bool(entry.get("built_by_run")),
                    "tags": [tag for tag in entry.get("tags") or [] if isinstance(tag, str)],
                    "pinned_by": sorted(pinned.get((record["id"], entry["commit"], entry["made_at"]), [])),
                }
                for entry in record.get("snapshots") or []
            ]
            pipelines.append(
                {
                    "id": record["id"],
                    "name": record.get("name") or record["id"],
                    "readme": f"pipelines/{_slug(record['id'])}_README.md",
                    "working": (record.get("location") or {}).get("kind") != "store",
                    "versions": versions,
                }
            )
        return pipelines

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
        files = sorted(self.files_page_path(r) for r in self.records.values() if r["kind"] == "File")
        if page_path == "index.md":
            return environment.get_template("index.md").render(
                manifest={"project": {"name": catalog.get("name", "")}},
                dataframe_file_list=dataframes,
                model_file_list=models,
                files_file_list=files,
                readme_text="",
                dot_or_dotdot="cb",
                has_versions=self._has_versions(),
            )
        if page_path == "cb/versions.md":
            return environment.get_template("versions.md").render(pipelines=self._versions())
        if page_path == "cb/dataframes.md":
            return environment.get_template("dataframes.md").render(
                dataframe_file_list=[p.removeprefix("cb/") for p in dataframes],
                stored_dataframes=self.from_the_store_assets(("dataframe",), page_path),
            )
        if page_path == "cb/models.md":
            return environment.get_template("models.md").render(
                model_file_list=[p.removeprefix("cb/") for p in models]
            )
        if page_path == "cb/files.md":
            return environment.get_template("files.md").render(files_file_list=[p.removeprefix("cb/") for p in files])
        if page_path == "cb/pipelines.md":
            pipelines = {
                r["id"]: self._pipeline_manifest(r) for r in self.records.values() if r["kind"] == "Pipeline"
            }
            return environment.get_template("pipelines.md").render(
                manifest={"pipelines": pipelines},
                dot_or_dotdot=".",
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
        kinds = {"Dataframe": "dataframes", "Chart": "charts", "Model": "models", "File": "files", "Notebook": "notebooks"}
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
                        "File": f"./files/{slug}/{name}.html",
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
                "trained_with", "trained_from", "inputs_now", "stale_inputs", "metrics", "versions",
                "file_count", "extensions"}
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
                "files", "inputs", "pinned_inputs", "trained_with", "trained_from", "inputs_now", "stale_inputs", "metrics",
                "versions", "docs"}
        shown = {key: value for key, value in record.items() if key not in skip}
        shown["path"] = (record.get("location") or {}).get("path", "")
        return shown

    def _panel(self, record_id: str, from_path: str) -> Optional[dict]:
        """The provenance panel's facts, with each pinned input of another pipeline linked to its pinned version."""
        facts = panel(record_id, self.records, self._reversed)
        for entry in (facts or {}).get("inputs", []):
            pin = entry.get("pin") or {}
            pinned = entry.get("cross") and entry.get("pinned")  # the lockfile pins this input, not only its pipeline
            entry["link"] = self._version_page(from_path, entry["id"], pin.get("commit"), pin.get("snapshot")) if pinned else ""
        return facts

    def _version_page(self, from_path: str, input_id: str, commit: Optional[str], made_at: Optional[str]) -> str:
        """The link from a page to an input's page in one snapshot of its pipeline; empty if the catalog does not show it.

        In a catalog, each snapshot of a pipeline is its own site under
        ``versions/`` (:mod:`chartbook.versions`). What a pipeline read of
        another is a snapshot, not that pipeline's folder as it is now; so
        an input links to its page in the snapshot's site. When that site
        could not be built, to the page there that says why.
        """
        owner, _, local = input_id.rpartition(":")
        found = self._version_site(owner, commit, made_at)
        if found is None:
            return ""
        root, entry = found
        kind, _, asset = local.rpartition("/")
        pages = {
            "": f"cb/dataframes/{_slug(owner)}/{asset}",
            "dataframe": f"cb/dataframes/{_slug(owner)}/{asset}",
            "chart": f"cb/charts/{_slug(owner)}.{asset}",
            "model": f"cb/models/{_slug(owner)}/{asset}",
            "file": f"cb/files/{_slug(owner)}/{asset}",
        }
        if kind not in pages or not asset or any(c in asset for c in "#@"):
            return ""
        page = f"{pages[kind]}.html" if entry.get("rendered", True) else "index.html"
        return "../" * from_path.count("/") + f"{root}/{page}"

    def _version_site(self, owner: str, commit: Optional[str], made_at: Optional[str]) -> Optional[tuple]:
        """Where one snapshot of a pipeline is in a catalog's site, and its entry in the pipeline's `snapshots`; None if the catalog does not show it."""
        from chartbook.versions import site_path, version_name

        if self.theme != "catalog" or not commit or not made_at:
            return None
        entry = next(
            (
                e for e in (self.records.get(owner) or {}).get("snapshots") or []
                if e.get("commit") == commit and e.get("made_at") == made_at
            ),
            None,
        )
        if entry is None:
            return None
        try:
            return site_path(owner, version_name(commit, made_at)), entry
        except ValueError:
            return None

    def _dependencies(self, pipeline: dict, from_path: str) -> list:
        """What a pipeline's page lists under "Dependencies": each pipeline it reads from, how it is declared, what it is pinned to.

        All of it is the pipeline record's ``dependencies``, which the index
        copies from ``[dependencies]`` and ``chartbook.lock``. A pin from a
        snapshot is said as the snapshot's commit and when it was made; a
        pin from a repository, as its commit. In a catalog that shows the
        other pipeline, the entry links its page in the snapshot pinned, or
        failing that its page here; a repository with a web address is
        linked there. What a record says is set into the page as code when
        it cannot end the code, and as text otherwise.
        """
        from chartbook.identity import web_link

        entries = []
        for dependency in pipeline.get("dependencies") or []:
            if not isinstance(dependency, dict) or not isinstance(dependency.get("id"), str):
                continue
            location = dependency.get("location") or {}
            rev = f", rev {_code(location['rev'])}" if location.get("rev") else ""
            if location.get("kind") == "path":
                declared = f"path {_code(location.get('path', ''))}"
            elif location.get("kind") == "git" and location.get("url"):
                declared = f"git {_code(location['url'])}{rev}"
            elif location.get("kind") == "git":
                declared = f"by its ID, from its repository{rev}"
            else:
                declared = f"by its ID, from the store{rev}"
            if dependency.get("key"):
                # The name its code reads it by, when that is not its ID here
                declared = f"as {_code(dependency['key'])}, {declared}"
            commit = location.get("commit") if _COMMIT.fullmatch(str(location.get("commit"))) else None
            made = dependency.get("snapshot") if _MADE_AT.match(str(dependency.get("snapshot"))) else None
            if commit and made:
                pinned = f"pinned to the snapshot at commit `{commit[:7]}`, made {made[:10]} {made[11:16]} UTC"
            elif commit:
                pinned = f"pinned to commit `{commit[:7]}` of its repository"
            else:
                pinned = "not pinned yet; `chartbook pin` pins it"
            entry = {"label": _code(dependency["id"]), "declared": declared, "pinned": pinned, "html_link": "", "link": ""}
            other = self.records.get(dependency["id"]) or {}
            found = self._version_site(dependency["id"], commit, dependency.get("snapshot"))
            if found is not None:
                entry["html_link"] = "../" * from_path.count("/") + f"{found[0]}/index.html"
            elif other.get("kind") == "Pipeline" and other is not pipeline:
                entry["link"] = posixpath.relpath(self.pipeline_page_path(other), posixpath.dirname(from_path) or ".")
            elif web_link(location.get("url")):
                entry["link"] = web_link(location["url"])
            entries.append(entry)
        return entries

    def _trained_on(self, record: dict, from_path: str = "") -> list:
        """What the page lists under "Trained On": a link to each input's page, or its name.

        An input of another pipeline links, in a catalog, to its page in the
        snapshot that held the bytes the model was trained on
        (``trained_from``); failing that, in the snapshot the lockfile pins
        for it. Otherwise an input in this site links to its page here. An
        input with no record is named with a note: its pipeline is in the
        site but does not declare it, or its pipeline is not in the site.
        """
        from chartbook.provenance import _dependency_for

        pipeline = self.records.get(record.get("pipeline")) or {}
        trained_from = record.get("trained_from") or {}
        pinned_inputs = record.get("pinned_inputs") or {}
        entries = []
        for input_id in record.get("inputs", []):
            other = self.records.get(input_id)
            dependency = _dependency_for(pipeline, input_id)
            pin = {}
            if dependency and input_id in pinned_inputs:
                pin = {"commit": (dependency.get("location") or {}).get("commit"), "made_at": dependency.get("snapshot")}
            held = trained_from.get(input_id) or {}
            if held and self._version_page(from_path, input_id, held.get("commit"), held.get("made_at")):
                note = f"as trained: the snapshot at {held['commit'][:7]}, made {held['made_at'][:10]}"
                if pin and (pin["commit"], pin["made_at"]) != (held["commit"], held["made_at"]):
                    note += f"; the pin has since moved to {pin['commit'][:7]}"
                entries.append(
                    {
                        "label": input_id,
                        "name": (other or {}).get("name", ""),
                        "link": "",
                        "html_link": self._version_page(from_path, input_id, held["commit"], held["made_at"]),
                        "note": note,
                    }
                )
            elif pin and self._version_page(from_path, input_id, pin["commit"], pin["made_at"]):
                entries.append(
                    {
                        "label": input_id,
                        "name": (other or {}).get("name", ""),
                        "link": "",
                        "html_link": self._version_page(from_path, input_id, pin["commit"], pin["made_at"]),
                        "note": f"as pinned: the snapshot at {pin['commit'][:7]}, made {pin['made_at'][:10]}",
                    }
                )
            elif other is not None and other.get("kind") == "Dataframe":
                entries.append(
                    {
                        "label": input_id,
                        "name": other.get("name", ""),
                        "link": self.link_to_dataframe(other, from_kind="Model"),
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
                "row_count", "columns", "definition_hash", "date_range", "docs", "inputs", "file_count", "files"}
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
        shown = {"project": project, "dataframes": dataframes, "from_the_store": _is_from_the_store(pipeline)}
        if pipeline.get("code_changed_at"):
            # In UTC, and said so, as every time on the site is
            shown["source_last_modified_date"] = _as_utc(pipeline["code_changed_at"]).strftime("%Y-%m-%d %H:%M:%S UTC")
        return shown

    def _write_up(self, record: dict, base_dir: Path, environment: jinja2.Environment) -> str:
        """The write-up's text, from the file the record names, rendered as the generator does."""
        docs = record.get("docs") or {}
        if docs.get("text"):
            return docs["text"]
        if docs.get("path"):
            # Text, read from the pipeline's folder; never a template, and never from elsewhere
            from chartbook.snapshot import safe_relative

            plain = safe_relative(docs["path"])
            if plain is None:
                raise FileNotFoundError(f"The write-up {docs['path']!r} is not a path inside {base_dir}.")
            return (Path(base_dir) / plain).read_text(encoding="utf-8")
        return ""

    def _environment(self, base_dir: Path) -> jinja2.Environment:
        """The templates: the project's own first, then the build's copy of the theme, then the package's.

        Rendered in Jinja's sandbox, so that a template, a project's own
        included, can read what it is given and nothing of Python beyond it.
        A build of files from a store takes no template from the project.
        """
        from chartbook.config import untrusted_source

        package = Path(str(importlib.resources.files("chartbook")))
        theme_dir = package / ("docs_src_catalog" if self.theme == "catalog" else "docs_src_pipeline")
        paths = []
        if self.docs_src_dir is not None:
            paths += [Path(self.docs_src_dir), Path(self.docs_src_dir) / "_templates"]
        paths += [theme_dir, theme_dir / "_templates"]
        return _sandboxed(paths, own=None if untrusted_source() else base_dir)

    # --- one entry point for the build ---------------------------------------

    def page(self, record: dict) -> str:
        """The page of any record that has one: dataframe, chart, model, files or pipeline."""
        return {
            "Dataframe": self.dataframe_page,
            "Chart": self.chart_page,
            "Model": self.model_page,
            "File": self.files_page,
            "Pipeline": self.pipeline_page,
        }[record["kind"]](record["id"])


def _slug(pipeline_id: str) -> str:
    return pipeline_id.replace("/", "--")


#: The templates a project may replace with a file of the same name in its own
#: root (a catalog's root, for the catalog's own pages), as the template table
#: of docs_src/guide/how-the-build-works.md lists them. Any other file there
#: is the project's own, a CHARTS.md or a models.md, and is never a template.
OVERRIDABLE_TEMPLATES = frozenset(
    {
        "freshness.md",
        "chart_entry_top.md",
        "chart_entry_bottom.md",
        "dataframe_manifest.md",
        "pipeline_manifest.md",
        "model_manifest.md",
        "file_manifest.md",
        "provenance.md",
        "pipeline_dependencies.md",
        "index.md",
    }
)


class _Overrides(jinja2.FileSystemLoader):
    """A project's own root as a place for templates: only the names in :data:`OVERRIDABLE_TEMPLATES` are taken from it."""

    def get_source(self, environment, template):
        if template not in OVERRIDABLE_TEMPLATES:
            raise jinja2.TemplateNotFound(template)
        return super().get_source(environment, template)

    def list_templates(self):
        return sorted(name for name in OVERRIDABLE_TEMPLATES if (Path(self.searchpath[0]) / name).is_file())


def _sandboxed(paths: list, own: Optional[Path] = None) -> jinja2.Environment:
    """A Jinja environment in the sandbox, loading templates from these folders in order.

    :param own: The project's own root, searched first for the templates a
        project may override, and for nothing else.
    """
    from jinja2.sandbox import SandboxedEnvironment

    loader = jinja2.FileSystemLoader([str(p) for p in paths])
    if own is not None:
        loader = jinja2.ChoiceLoader([_Overrides([str(own)]), loader])
    environment = SandboxedEnvironment(loader=loader)
    environment.filters["yaml_escape"] = yaml_escape
    environment.filters["literal"] = _literal
    return environment


def _laid_out_version(pipeline: dict) -> Optional[dict]:
    """Which snapshot a pipeline's folder is, for its front page; None for a working folder."""
    version = pipeline.get("from_snapshot") or {}
    if not isinstance(version, dict) or not version.get("commit") or not version.get("made_at"):
        return None
    made = version["made_at"]
    return {"short": version["commit"][:7], "made": f"{made[:10]} {made[11:16]} UTC"}


def _local_name(record: dict) -> str:
    return record["ref"]["name"]


def _as_utc(modified_at: Optional[str]) -> Optional[datetime]:
    """An index timestamp (UTC, to the second) as a time in UTC, or None."""
    if not modified_at:
        return None
    return datetime.strptime(modified_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _freshness(label: str, modified_at: Optional[str]):
    moment = _as_utc(modified_at)
    return None if moment is None else freshness_fact(label, moment)


def freshness_fact(label: str, moment: Optional[datetime]) -> Optional[dict]:
    """One "<label> <when>" fact for a page's freshness line.

    The page says *when*, not *how long ago*: a generated page is static, so
    "2 days ago" worked out at build time would be wrong the next day, and
    would make every page differ from one build to the next. The timestamp
    goes into a ``<time>`` element and ``chartbook-freshness.js`` turns it
    into relative wording when the page is read.

    Every time on the site is in UTC and says so, whatever the zone of the
    machine that built it: a naive *moment* is taken as that machine's
    local time and converted.

    :returns: ``label``, ``iso`` (ISO 8601 with offset), ``title`` (hover
        text) and ``date`` (fallback text); None when *moment* is None.
    """
    if moment is None:
        return None
    utc = moment.astimezone(timezone.utc)
    return {
        "label": label,
        "iso": utc.isoformat(timespec="seconds"),
        "title": utc.strftime("%Y-%m-%d %H:%M UTC"),
        "date": utc.strftime("%Y-%m-%d"),
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


def _listing(record: dict) -> Optional[dict]:
    """A files asset's files as its page lists them: a line that sums them up, and the first :data:`FILES_SHOWN`."""
    listed = record.get("files") or []
    if not record.get("content_hash") or not listed:
        return None
    count = record.get("file_count") or len(listed)
    by_type = ", ".join(
        f"{number:,} {_code(kind) if kind else 'with no ending'}" for kind, number in (record.get("extensions") or {}).items()
    )
    summary = f"**{count:,} file{'s' if count != 1 else ''}**, {_format_size(record.get('size_bytes') or 0)} in all"
    summary += f": {by_type}." if by_type else "."
    keys = _keys_of(listed)
    if keys:
        summary += " " + _keys_line(listed, keys)
    rows = [{"path": f["path"], "size": _format_size(f["size_bytes"])} for f in listed[:FILES_SHOWN]]
    return {"summary": summary, "rows": rows, "more": count - len(rows), "partition_keys": keys}


def _keys_of(listed: list) -> list:
    """The keys of the ``key=value`` folders some listed file is in, in the order first met."""
    keys: dict = {}
    for entry in listed:
        for key in entry.get("partitions") or {}:
            keys.setdefault(key, None)
    return list(keys)


def _keys_line(listed: list, keys: list) -> str:
    """One sentence on the ``key=value`` folders: each key, and its values among the files listed."""
    said = []
    for key in keys:
        values = sorted({(entry.get("partitions") or {}).get(key) for entry in listed} - {None})
        shown = ", ".join(_code(v) for v in values[:6]) + (f", … ({len(values)} values)" if len(values) > 6 else "")
        said.append(f"{_code(key)} ({shown})")
    return f"In `key=value` folders, by {'; '.join(said)}."


def _parts(record: dict) -> Optional[dict]:
    """A dataframe of many parts as its page lists them: each file with its size, its rows and its partition keys."""
    listed = record.get("files") or []
    if not listed or not record.get("content_hash"):
        return None
    count = record.get("file_count") or len(listed)
    keys = _keys_of(listed)
    summary = f"**{count:,} file{'s' if count != 1 else ''}**, {_format_size(record.get('size_bytes') or 0)} in all"
    if record.get("row_count") is not None:
        summary += f", {record['row_count']:,} rows"
    summary += "."
    if keys:
        summary += " " + _keys_line(listed, keys)
    rows = [
        {
            "path": f["path"],
            "size": _format_size(f["size_bytes"]),
            "rows": f"{f['row_count']:,}" if isinstance(f.get("row_count"), int) else "",
            "partition_values": [(f.get("partitions") or {}).get(key, "") for key in keys],
        }
        for f in listed[:FILES_SHOWN]
    ]
    return {"summary": summary, "rows": rows, "more": count - len(rows), "partition_keys": [_code(key) for key in keys]}


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
    from chartbook.backends import MEMORY_URL, duckdb_path, open_backend, source_url
    from chartbook.resolve import QueryLocation, TableLocation

    location = record["location"]
    where = (
        f"table {location['identifier']}" if location["kind"] == "table" else "query"
    ) + f" in source {location.get('source')!r} ({location.get('backend')})"
    if not location.get("url"):
        return f"A {where}."
    try:
        # A DuckDB file is found through the machine's url, relative to the
        # pipeline's folder; another engine finds its own from the public one
        url = location["url"]
        if location.get("backend") == "duckdb":
            url = source_url(location["source"], url)
            path = duckdb_path(url, base_dir)
            url = MEMORY_URL if path == ":memory:" else "duckdb:///" + path
    except Exception as error:  # noqa: BLE001 - a page, not a crash
        return f"A {where}. It could not be read when the site was built: {error}"
    if location["kind"] == "table":
        typed = TableLocation(location["source"], location["backend"], url, location["identifier"])
    else:
        typed = QueryLocation(location["source"], location["backend"], url, location["sql"])
    try:
        backend = open_backend(location["backend"], url, location["source"])
        columns, rows = backend.describe(typed)
        sample = backend.scan(typed).head(5).collect()
    except Exception as error:  # noqa: BLE001 - a page, not a crash
        return f"A {where}. It could not be read when the site was built: {error}"
    lines = [f"A {where}: {rows} rows, {len(columns)} columns.", ""]
    lines += [f"  {column['name']}: {column['dtype']}" for column in columns]
    lines += ["", "First rows:", str(sample)]
    return "\n".join(lines)
