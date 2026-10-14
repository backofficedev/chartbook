"""The provenance panel: what an asset is, where it is, what made it, from what.

Every dataframe, chart and model page carries a panel that answers, from the
index alone: what this is and where it is; its content hash, size and rows;
which pipeline built it and with what; what it was made from, at which
hashes, and whether those have moved since; and what is made from it. It is
the second reader of the index (``docs_src/design/index-schema.md``, "What
this unblocks"): the page generator builds the index first and hands each
page its record and the records around it. Nothing here reads a manifest
or a file; what the panel says is what ``index.json`` says.
"""

from __future__ import annotations

from typing import Optional


def _owner(asset_id: str) -> str:
    """The pipeline an asset ID belongs to: everything before the last colon."""
    return asset_id.rsplit(":", 1)[0] if ":" in asset_id else asset_id


def _short(content_hash: Optional[str]) -> str:
    return content_hash[:19] + "…" if content_hash else "(not built)"


def _where(record: dict) -> str:
    location = record.get("location") or {}
    kind = location.get("kind")
    if kind == "table":
        return f"table `{location.get('identifier')}` in source `{location.get('source')}` ({location.get('backend')})"
    if kind == "query":
        return f"a query in source `{location.get('source')}` ({location.get('backend')})"
    if location.get("path"):
        return f"`{location['path']}`"
    return "(no location declared)"


def _content(record: dict) -> str:
    parts = []
    if record.get("content_hash"):
        parts.append(f"`{record['content_hash']}`")
    elif record.get("definition_hash"):
        parts.append(f"definition `{record['definition_hash']}`")
    else:
        parts.append("not built")
    if record.get("size_bytes") is not None:
        parts.append(f"{record['size_bytes']:,} bytes")
    if record.get("row_count") is not None:
        parts.append(f"{record['row_count']:,} rows")
    if record.get("columns"):
        parts.append(f"{len(record['columns'])} columns")
    return " · ".join(parts)


def _dependency_for(pipeline: Optional[dict], input_id: str) -> Optional[dict]:
    """The dependency entry of the pipeline that an input of another pipeline came through."""
    for entry in (pipeline or {}).get("dependencies") or []:
        if isinstance(entry, dict) and input_id.startswith(f"{entry.get('id')}:"):
            return entry
    return None


def panel(record_id: str, records: dict) -> Optional[dict]:
    """The facts a page's provenance panel shows for one asset.

    :param record_id: The asset's ID in the index.
    :param records: Every record of the index, by ID.
    :returns: Plain values for a template, or None when the index has no
        such record (an asset skipped, or a build without an index).
    """
    record = records.get(record_id)
    if record is None:
        return None
    pipeline_id = record.get("pipeline") or _owner(record_id)
    pipeline = records.get(pipeline_id)
    build = ((pipeline or {}).get("scripts") or {}).get("build")

    inputs = []
    pinned = record.get("pinned_inputs") or {}
    trained_with = record.get("trained_with") or {}
    stale = set(record.get("stale_inputs") or [])
    for input_id in record.get("inputs") or []:
        other = records.get(input_id)
        cross = _owner(input_id) != pipeline_id
        entry = {
            "id": input_id,
            "kind": (other or {}).get("kind"),
            "in_site": other is not None,
            "cross": cross,
            "hash_now": (other or {}).get("content_hash"),
            "pinned": pinned.get(input_id),
            "trained_with": trained_with.get(input_id),
            "stale": input_id in stale,
        }
        dependency = _dependency_for(pipeline, input_id) if cross else None
        if dependency:
            location = dependency.get("location") or {}
            entry["pin"] = {
                "commit": location.get("commit"),
                "snapshot": dependency.get("snapshot"),
                "via": dependency.get("via"),
            }
        entry["words"] = _input_words(entry)
        inputs.append(entry)

    used_by = sorted(
        other_id
        for other_id, other in records.items()
        if record_id in (other.get("inputs") or [])
    )
    series = sorted(
        other_id for other_id, other in records.items()
        if other.get("kind") == "Series" and other.get("dataframe") == record_id
    ) if record.get("kind") == "Dataframe" else []

    version = None
    if record.get("kind") == "Model" and record.get("content_hash"):
        for candidate in record.get("versions") or []:
            if candidate.get("content_hash") == record["content_hash"]:
                version = {
                    "name": candidate.get("version"),
                    "made_at": candidate.get("made_at"),
                    "commit": candidate.get("commit"),
                    "labels": list(candidate.get("labels") or []),
                }
                break

    return {
        "kind": record.get("kind"),
        "id": record_id,
        "pipeline": pipeline_id,
        "where": _where(record),
        "content": _content(record),
        "build": build,
        "inputs": inputs,
        "used_by": used_by,
        "series": len(series),
        "version": version,
        "stale": sorted(stale),
    }


def _input_words(entry: dict) -> str:
    """One line about an input: at which hash, pinned from where, moved or not."""
    parts = []
    if entry["pinned"]:
        parts.append(f"pinned at `{_short(entry['pinned'])}`")
        pin = entry.get("pin") or {}
        if pin.get("commit"):
            when = f", made {pin['snapshot'][:10]}" if pin.get("snapshot") else ""
            parts.append(f"from the snapshot at `{pin['commit'][:7]}`{when}")
    elif entry["in_site"]:
        parts.append(f"now at `{_short(entry['hash_now'])}`")
    else:
        parts.append("not in this site")
    if entry["trained_with"] and entry["stale"]:
        parts.append(f"**moved since this was trained** (trained with `{_short(entry['trained_with'])}`)")
    elif entry["trained_with"]:
        parts.append("as trained")
    return "; ".join(parts)
