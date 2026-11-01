"""Store-only catalog records. Stored text remains data, never templates."""
from __future__ import annotations
from chartbook import snapshot
from chartbook.identity import plain_line
from chartbook.refs import parse_asset_ref


def enrich(records, stores, notes=None):
    found, _ = snapshot.readable_snapshots(stores)
    pipelines = [r for r in records if r.get("kind") == "Pipeline"]
    for pipeline in pipelines:
        versions = sorted(selected_snapshots(found, pipeline["id"], (notes or {}).get(pipeline["id"], {}).get("repository")), key=lambda t: t.made_at, reverse=True)
        if not versions:
            continue
        indexes = [(taken, snapshot._stored_records(taken, stores)) for taken in versions]
        assets = {}
        from chartbook import indexdiff
        for taken, listed in indexes:
            for record in listed:
                if not isinstance(record, dict) or record.get("kind") not in ("Dataframe", "Chart", "Model", "File"):
                    continue
                try:
                    ref = parse_asset_ref(record.get("id", ""))
                except ValueError:
                    continue
                if ref.pipeline_id != pipeline["id"] or ref.rev or ref.part or ref.registry:
                    continue
                expected = {"Dataframe": "dataframe", "Chart": "chart", "Model": "model", "File": "file"}[record["kind"]]
                if ref.kind != expected:
                    continue
                assets.setdefault(record["id"], []).append((taken, record))
        newest_records = {r.get("id"): r for r in indexes[0][1] if isinstance(r, dict) and isinstance(r.get("id"), str)}
        for asset_id, history in assets.items():
            current = asset_id in newest_records
            latest = newest_records.get(asset_id) or history[0][1]
            if latest.get("kind") not in ("Dataframe", "Chart", "Model", "File"):
                continue
            ref = parse_asset_ref(asset_id)
            hub = {"kind": latest["kind"], "version": "chartbook/v1", "id": asset_id, "pipeline": pipeline["id"],
                   "ref": {"name": ref.name, "kind": ref.kind}, "location": {"kind": "store"},
                   "metadata_present": metadata_present(latest), "current": current, "name": plain_line(latest.get("name") or ref.name, 200),
                   "description": plain_line(latest.get("description"), 2000), "snapshots": []}
            for i, (taken, listed) in enumerate(indexes):
                entry = {"commit": taken.commit, "made_at": taken.made_at, "present": False}
                from chartbook.versions import name_of
                entry["name"] = name_of(taken)
                entry["store"] = stores.name_of(taken.path)
                own = next((r for r in listed if isinstance(r, dict) and r.get("id") == asset_id), None)
                entry["present"] = own is not None
                if own is not None and i + 1 < len(indexes):
                    before = [r for r in indexes[i + 1][1] if isinstance(r, dict) and r.get("id") == asset_id]
                    try:
                        diff = indexdiff.diff({"records": before}, {"records": [own]})
                        entry["changes"] = indexdiff.format_diff(diff)
                    except (ValueError, TypeError, AttributeError, KeyError):
                        entry["changes"] = "The stored metadata could not be compared."
                hub["snapshots"].append(entry)
            if latest["kind"] == "Dataframe":
                present = set(hub["metadata_present"])
                current_records = indexes[0][1]
                if any(isinstance(r, dict) and r.get("kind") == "Series" and r.get("dataframe") == asset_id and r.get("declared") is True for r in current_records):
                    present.add("series")
                if any(isinstance(r, dict) and r.get("kind") == "Chart" and isinstance(r.get("inputs"), list) and asset_id in r["inputs"] for r in current_records):
                    present.add("linked_charts")
                hub["metadata_present"] = sorted(present)
            modified = (latest.get("location") or {}).get("modified_at")
            if isinstance(modified, str):
                hub["location"]["modified_at"] = modified
            for key in ("license", "source", "tags", "columns", "row_count", "content_hash", "size_bytes",
                        "inputs", "pinned_inputs", "trained_with", "trained_from", "inputs_now", "stale_inputs", "metrics", "date_range",
                        "frequency", "units", "category", "provider", "license_expiration", "maintainer"):
                if key in latest:
                    hub[key] = latest[key]
            for field in ("inputs",):
                value = hub.get(field)
                if value is not None:
                    hub[field] = [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
            for field in ("pinned_inputs", "trained_with"):
                value = hub.get(field)
                if value is not None:
                    hub[field] = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(value, dict) else {}
            aliases = {d.get("key", d["id"]): d["id"] for d in pipeline.get("dependencies", [])}
            def canonical(value):
                owner, separator, local = value.rpartition(":")
                return aliases.get(owner, owner) + separator + local if separator else value
            hub["inputs"] = [canonical(v) for v in hub.get("inputs", [])]
            hub["pinned_inputs"] = {canonical(k): v for k, v in hub.get("pinned_inputs", {}).items()}
            hub.pop("trained_from", None)  # computed from verified snapshot identities below
            records.append(hub)
    result = []
    for entry in stores.entries:
        from chartbook.store import StoreUnreachableError
        try:
            held, unreadable = snapshot.readable_snapshots(entry.store) if entry.reachable else ([], [])
        except (StoreUnreachableError, OSError) as error:
            stores._unreachable(entry, error)
            held, unreadable = [], []
        counts = {}
        for taken in held:
            counts[taken.pipeline] = counts.get(taken.pipeline, 0) + 1
        from chartbook.config import shown_store_url
        result.append({"name": entry.name, "url": shown_store_url(entry.url), "read_only": entry.read_only,
                       "reachable": entry.reachable, "pipelines": counts, "routing": list(entry.pipelines),
                       "newest": held[-1].made_at if held else None, "unreadable": len(unreadable)})
    return result


def selected_snapshots(found, pipeline, repository=None):
    """Keep a catalog's versions within its selected repository identity."""
    from chartbook.identity import repository_key
    chosen = [taken for taken in found if taken.pipeline == pipeline]
    groups = snapshot.by_repository(chosen)
    if repository:
        key = repository_key(repository)
        return [taken for group in groups if any(repository_key(t.repository) == key for t in group if t.repository) for taken in group]
    if len(groups) > 1:
        raise ValueError(f"Several repositories claim {pipeline!r}; set [pipelines.\"{pipeline}\"] repository = \"URL\" in catalog.toml")
    return chosen


def dependency_records(dependencies, pins=()):
    """Only portable, typed dependency identity from a stored index."""
    import re
    from chartbook.identity import validate_pipeline_id
    if not isinstance(dependencies, list):
        return []
    pinned = {p.get("id"): p for p in pins if isinstance(p, dict)}
    result = []
    for entry in dependencies:
        if not isinstance(entry, dict):
            continue
        pin = pinned.get(entry.get("key") or entry.get("id"), {})
        identity = pin.get("pinned_from") or (pin.get("location") or {}).get("pipeline") or entry.get("pinned_from") or entry.get("id")
        try:
            validate_pipeline_id(identity)
        except ValueError:
            continue
        location = entry.get("location")
        if not isinstance(location, dict):
            location = {}
        commit = location.get("commit")
        moment = entry.get("snapshot")
        safe = {"id": identity, "location": {"kind": "store"}}
        alias = entry.get("key") or (entry.get("id") if identity != entry.get("id") else None)
        if isinstance(alias, str):
            try:
                validate_pipeline_id(alias)
            except ValueError:
                pass
            else:
                safe["key"] = alias
        if isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
            safe["location"]["commit"] = commit
        if isinstance(moment, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z", moment):
            safe["snapshot"] = moment
        result.append(safe)
    return result


def metadata_present(record):
    """Remember completeness without retaining or following any stored machine path."""
    from chartbook.diagnostics import _value_is_missing
    present = {key for key, value in record.items() if not _value_is_missing(value)}
    location = record.get("location") if isinstance(record.get("location"), dict) else {}
    docs = record.get("docs") if isinstance(record.get("docs"), dict) else {}
    present.discard("docs")
    if docs.get("path"):
        present.add("docs_path")
    if not _value_is_missing(docs.get("text")):
        present.add("docs")
    if location.get("kind") == "file" and location.get("path"):
        present.add("path")
    if location.get("kind") in ("table", "query"):
        present.add(location["kind"])
        present.add("source")
    if record.get("kind") == "Pipeline":
        present.update(("id", "type", "enable_data_download"))
        if isinstance(record.get("scripts"), dict) and record["scripts"].get("build"):
            present.add("build")
        if docs.get("path"):
            present.add("readme")
    if record.get("inputs"):
        present.update(("dataframe", "trained_on"))
    return sorted(present)
