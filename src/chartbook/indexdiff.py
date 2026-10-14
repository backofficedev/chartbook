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
Records are matched by kind and ID.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from chartbook.index import INDEX_FILE, published

#: Fields whose change means the asset's data moved.
DATA_FIELDS = ("content_hash", "definition_hash", "size_bytes", "row_count", "columns", "files")


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
            said.append("data changed")
        if "dependencies" in self.fields:
            said.append("pins moved")
        if "versions" in self.fields:
            before, after = self.fields["versions"]
            new = len(after or []) - len(before or [])
            said.append(f"{new} new version(s)" if new > 0 else "versions changed")
        if "aliases" in self.fields:
            said.append("labels moved")
        if "stale_inputs" in self.fields:
            _, after = self.fields["stale_inputs"]
            said.append("out of date" if after else "up to date again")
        if "metrics" in self.fields:
            said.append("scores changed")
        rest = sorted(
            name
            for name in self.fields
            if name not in DATA_FIELDS
            and name not in ("dependencies", "versions", "aliases", "stale_inputs", "metrics")
        )
        if rest:
            said.append("declared differently: " + ", ".join(rest))
        return said


@dataclass
class IndexDiff:
    """What changed between two indexes.

    Attributes:
        added: Records in the second index and not the first.
        removed: Records in the first and not the second.
        changed: Records in both that differ, with the fields that do.
    """

    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict:
        """The diff as JSON: for a script, or a bot that comments on a pull request."""
        return {
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

    :raises ValueError: If the file is not an index.
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
    return index


def _key(record: dict) -> tuple:
    return (str(record.get("kind")), str(record.get("id")))


def diff(before: dict, after: dict) -> IndexDiff:
    """Compare two indexes, as published, record by record.

    :param before: The earlier index, as :func:`read_index` gives it.
    :param after: The later one.
    """
    first = {_key(r): r for r in published(before).get("records", [])}
    second = {_key(r): r for r in published(after).get("records", [])}
    result = IndexDiff()
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


def _short(value) -> str:
    """A value for a line of text: a hash cut to 19 characters, a number as is."""
    if isinstance(value, str) and ":" in value and len(value) > 24:
        return value[:19] + "…"
    if value is None:
        return "(none)"
    if isinstance(value, (int, float)):
        return str(value)
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= 60 else text[:57] + "…"


def format_diff(found: IndexDiff, before_label: str = "before", after_label: str = "after") -> str:
    """The diff as text, one line per record, with hashes and counts for data."""
    if found.empty:
        return "Nothing changed."
    lines = []
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
            for name in ("content_hash", "definition_hash", "row_count", "stale_inputs"):
                if name in change.fields:
                    b, a = change.fields[name]
                    lines.append(f"    {name}: {_short(b)} -> {_short(a)}")
    return "\n".join(lines)
