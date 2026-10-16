"""A diff of two indexes: what changed between two builds, for a reviewer.

``chartbook docs`` writes ``index.json`` beside the site: every pipeline,
dataframe, chart, notebook, note and model, with a content hash for each.
Two of those files, from two builds, say what a change did without anyone
opening the site: which data moved, which assets were added or taken away,
which pins moved, which model got a new version or lost a label, which
model is now out of date. This is the first reader of the index
(``docs_src/design/index-schema.md``, "What this unblocks"): a build diff,
for reviewing what changed, including what automated tooling changed.

The two indexes are compared **as published**: local absolute paths are
left out of both, so a full index from a build directory and the published
one beside the site compare as equals, and ``generated_at`` is ignored.
Records are matched by kind and ID. The envelope is compared too: a
different ``root`` or ``schema`` is said first, since it means the two
may not be the same site, or not written the same way.

Two things the diff cannot tell apart from a change, and says so in the
docs: a chart file that a renderer writes differently each time (Plotly
embeds a fresh id unless given ``div_id``; ChartBook's own plotting helpers
give one; an executed notebook's HTML carries ids and times from its run),
and a model's ``versions``, ``trained_with`` and ``stale_inputs``,
which are read from the store of the machine that built the index.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

from chartbook.index import INDEX_FILE, published

#: Fields whose change means the asset's data moved.
DATA_FIELDS = ("content_hash", "definition_hash", "size_bytes", "row_count", "columns", "files")

#: Kinds whose file is a rendering, which a renderer may write differently each time.
RENDERED_KINDS = ("Chart", "Notebook")

#: Fields that are worked out, not declared, with the words for a change in each.
COMPUTED_WORDS = {
    "docs": "write-up changed",
    "code_changed_at": "source changed",
    "assets": "assets changed",
    "pinned_inputs": "pins moved",
    "trained_with": "trained on other data",
    "inputs": "inputs changed",
    "location": "moved",
    "series": "series changed",
    "site_pages": "site pages changed",
}

#: Envelope fields a difference in which is said before anything else.
ENVELOPE_FIELDS = ("root", "schema")


def _names(versions) -> list[str]:
    return [v.get("version") for v in (versions or []) if isinstance(v, dict)]


@dataclass
class Change:
    """One record that is in both indexes and differs.

    Attributes:
        kind: The record's kind, ``Dataframe``, ``Model``, ``Pipeline``...
        id: Its ID.
        fields: Each field that differs, with its value before and after.
    """

    kind: str
    id: str
    fields: dict = field(default_factory=dict)

    @property
    def words(self) -> list[str]:
        """What the change is, in a reviewer's words, in order of weight."""
        said = []
        if any(name in self.fields for name in DATA_FIELDS):
            # A chart is a rendering of data, and a notebook's HTML a record
            # of a run; a renderer may write either differently each time
            # (an id, a time), and their data is their dataframes'
            said.append("rendered differently" if self.kind in RENDERED_KINDS else "data changed")
        if "dependencies" in self.fields:
            before, after = self.fields["dependencies"]
            pins = lambda entries: {e.get("id"): e.get("pinned_hash") for e in (entries or []) if isinstance(e, dict)}
            said.append("pins moved" if pins(before) != pins(after) else "dependencies changed")
        if "versions" in self.fields:
            before, after = set(_names(self.fields["versions"][0])), set(_names(self.fields["versions"][1]))
            new, gone = len(after - before), len(before - after)
            if new:
                said.append(f"{new} new version(s)")
            if gone:
                said.append(f"{gone} version(s) gone")
            if not new and not gone:
                said.append("versions changed")
        if "snapshots" in self.fields:
            before, after = ({(s.get("commit"), s.get("made_at")) for s in (v or []) if isinstance(s, dict)} for v in self.fields["snapshots"])
            if after - before:
                said.append(f"{len(after - before)} new snapshot(s)")
            if before - after:
                said.append(f"{len(before - after)} snapshot(s) gone")
        if "from_snapshot" in self.fields:
            said.append("laid out from another snapshot" if all(self.fields["from_snapshot"]) else "laid out from a snapshot, or no longer")
        if "aliases" in self.fields:
            said.append("labels moved")
        if "stale_inputs" in self.fields:
            _, after = self.fields["stale_inputs"]
            said.append("out of date" if after else "up to date again")
        if "metrics" in self.fields:
            said.append("scores changed")
        if "date_range" in self.fields:
            before, after = self.fields["date_range"]
            last_before, last_after = (before or {}).get("last"), (after or {}).get("last")
            if last_before and last_after and last_after > last_before:
                said.append("data reaches further")
            elif last_before and last_after and last_after < last_before:
                said.append("data reaches less far")
            else:
                said.append("date range moved")
        for name, words in COMPUTED_WORDS.items():
            if name in self.fields:
                said.append(words)
        handled = set(DATA_FIELDS) | set(COMPUTED_WORDS) | {
            "dependencies", "versions", "snapshots", "from_snapshot", "aliases", "stale_inputs", "metrics", "date_range",
            "inputs_now",  # said by stale_inputs when it matters; the inputs' own records say the rest
        }
        rest = sorted(name for name in self.fields if name not in handled)
        if rest:
            said.append("declared differently: " + ", ".join(rest))
        return said


@dataclass
class IndexDiff:
    """What changed between two indexes.

    Attributes:
        envelope: Envelope fields that differ (``root``, ``schema``), with
            their value before and after.
        added: Records in the second index and not the first.
        removed: Records in the first and not the second.
        changed: Records in both that differ, with the fields that do.
    """

    envelope: dict = field(default_factory=dict)
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.envelope or self.added or self.removed or self.changed)

    def to_dict(self) -> dict:
        """The diff as JSON: for a script, or a bot that comments on a pull request."""
        return {
            "envelope": {name: {"before": b, "after": a} for name, (b, a) in self.envelope.items()},
            "added": [{"kind": r["kind"], "id": r["id"]} for r in self.added],
            "removed": [{"kind": r["kind"], "id": r["id"]} for r in self.removed],
            "changed": [
                {
                    "kind": c.kind,
                    "id": c.id,
                    "words": c.words,
                    "fields": {name: {"before": b, "after": a} for name, (b, a) in c.fields.items()},
                }
                for c in self.changed
            ],
        }


def read_index(path: Union[str, Path]) -> dict:
    """Read an ``index.json``; a directory means the ``index.json`` in it.

    :raises ValueError: If the file is not an index: not JSON, no list of
        records, or a record without a kind and an ID.
    :raises OSError: If it cannot be read.
    """
    path = Path(path)
    if path.is_dir():
        path = path / INDEX_FILE
    with open(path, encoding="utf-8") as f:
        try:
            index = json.load(f)
        except ValueError as error:
            raise ValueError(f"{path} is not JSON: {error}") from None
    if not isinstance(index, dict) or not isinstance(index.get("records"), list):
        raise ValueError(f"{path} is not an index: it has no list of records.")
    for number, record in enumerate(index["records"]):
        if not isinstance(record, dict) or not isinstance(record.get("kind"), str) or not isinstance(record.get("id"), str):
            raise ValueError(
                f"{path} is not an index: record {number} has no kind and id."
            )
    return index


def _key(record: dict) -> tuple:
    return (record["kind"], record["id"])


def diff(before: dict, after: dict) -> IndexDiff:
    """Compare two indexes, as published, record by record.

    :param before: The earlier index, as :func:`read_index` gives it.
    :param after: The later one.
    """
    result = IndexDiff()
    for name in ENVELOPE_FIELDS:
        if before.get(name) != after.get(name):
            result.envelope[name] = (before.get(name), after.get(name))
    first = {_key(r): _timeless(r) for r in published(before).get("records", [])}
    second = {_key(r): _timeless(r) for r in published(after).get("records", [])}
    for key in sorted(set(second) - set(first)):
        result.added.append(second[key])
    for key in sorted(set(first) - set(second)):
        result.removed.append(first[key])
    for key in sorted(set(first) & set(second)):
        a, b = first[key], second[key]
        if a == b:
            continue
        fields = {
            name: (a.get(name), b.get(name))
            for name in sorted(set(a) | set(b))
            if a.get(name) != b.get(name)
        }
        result.changed.append(Change(key[0], key[1], fields))
    return result


def _timeless(record: dict) -> dict:
    """A record without when its file was written: the diff reads what a file holds, not when."""
    location = record.get("location")
    if isinstance(location, dict) and "modified_at" in location:
        record = {**record, "location": {k: v for k, v in location.items() if k != "modified_at"}}
    return record


def _short(value) -> str:
    """A value for a line of text: a hash cut to 19 characters, a number as is, a list whole."""
    if isinstance(value, str) and ":" in value and len(value) > 24:
        return value[:19] + "…"
    if value is None:
        return "(none)"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, default=str, ensure_ascii=False)


def _column_names(columns) -> list[str]:
    return [c.get("name") for c in (columns or []) if isinstance(c, dict)]


def format_diff(found: IndexDiff) -> str:
    """The diff as text, one line per record, with hashes and counts for data."""
    if found.empty:
        return "Nothing changed."
    lines = []
    for name, (before, after) in found.envelope.items():
        lines.append(f"The {name} differs: {_short(before)} -> {_short(after)}")
    if "schema" in found.envelope:
        lines.append("  The two were written in different layouts; the records may not compare like for like.")
    if found.added:
        lines.append(f"Added {len(found.added)}:")
        lines += [f"  {r['kind']} {r['id']}" for r in found.added]
    if found.removed:
        lines.append(f"Removed {len(found.removed)}:")
        lines += [f"  {r['kind']} {r['id']}" for r in found.removed]
    if found.changed:
        lines.append(f"Changed {len(found.changed)}:")
        for change in found.changed:
            lines.append(f"  {change.kind} {change.id}: {'; '.join(change.words)}")
            for name in ("content_hash", "definition_hash", "row_count", "stale_inputs", "date_range"):
                if name in change.fields:
                    b, a = change.fields[name]
                    lines.append(f"    {name}: {_short(b)} -> {_short(a)}")
            if "columns" in change.fields:
                b, a = (_column_names(v) for v in change.fields["columns"])
                added, gone = [c for c in a if c not in b], [c for c in b if c not in a]
                if added:
                    lines.append(f"    columns added: {', '.join(added)}")
                if gone:
                    lines.append(f"    columns gone: {', '.join(gone)}")
                if not added and not gone:
                    lines.append("    columns: types changed")
            if "versions" in change.fields:
                b, a = (set(_names(v)) for v in change.fields["versions"])
                if a - b:
                    lines.append(f"    new: {', '.join(sorted(a - b))}")
                if b - a:
                    lines.append(f"    gone: {', '.join(sorted(b - a))}")
    return "\n".join(lines)
