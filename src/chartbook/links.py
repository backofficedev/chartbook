"""Explicit, consumer-local working-copy overrides; never lockfile identity."""
from __future__ import annotations
import os
import warnings
from pathlib import Path
import tomli
import tomli_w

NAME = "chartbook.links.toml"
_warned = set()


class LinkedDependencyWarning(UserWarning):
    pass


def read(folder, *, active=True):
    if active and (os.environ.get("CI", "").lower() not in ("", "0", "false") or os.environ.get("CHARTBOOK_FROZEN") == "1"):
        return {}
    folder = Path(folder).resolve()
    path = folder / NAME
    if not path.exists():
        return {}
    try:
        raw = tomli.loads(path.read_text(encoding="utf-8"))
    except tomli.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from None
    from chartbook.identity import validate_pipeline_id
    result = {}
    for key, value in raw.items():
        validate_pipeline_id(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: {key!r} must name a folder")
        result[key] = (folder / Path(value).expanduser()).resolve()
    return result


def add(folder, pipeline, target):
    from chartbook.resolve import _own_id
    from chartbook.identity import validate_pipeline_id
    validate_pipeline_id(pipeline)
    folder, target = Path(folder).resolve(), Path(target).resolve()
    actual = _own_id(target)
    if actual != pipeline:
        raise ValueError(f"{target} declares {actual!r}, not {pipeline!r}")
    path = folder / NAME
    raw = tomli.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        # With / on every system, which Windows reads as well: ../rates, not ..\rates in the TOML
        raw[pipeline] = Path(os.path.relpath(target, folder)).as_posix()
    except ValueError:  # on another drive (Windows), where no relative path reaches it
        raw[pipeline] = target.as_posix()
    path.write_text(tomli_w.dumps(raw), encoding="utf-8", newline="\n")
    return path


def resolve(asset, folder):
    links = read(folder)
    actual = asset.pipeline_id
    target = links.get(actual)
    if target is None:
        manifest = Path(folder) / "chartbook.toml"
        raw = tomli.loads(manifest.read_text(encoding="utf-8"))
        entry = raw.get("dependencies", {}).get(actual, {})
        if isinstance(entry, dict):
            actual = entry.get("id", actual)
            if entry.get("path"):
                from chartbook.resolve import _own_id
                actual = _own_id(Path(folder) / entry["path"]) or actual
            target = links.get(actual)
    if target is None:
        return None
    from chartbook.resolve import _own_id, _resolve_local
    if _own_id(target) != actual:
        raise ValueError(f"{NAME}: {target} no longer declares {actual!r}")
    key = (str(Path(folder).resolve()), actual)
    if key not in _warned:
        warnings.warn(f"{actual} reads working files at {target}; its pin is not in use ({NAME}).", LinkedDependencyWarning, stacklevel=3)
        _warned.add(key)
    from chartbook.refs import AssetRef
    return _resolve_local(AssetRef(name=asset.name, kind=asset.kind), target)


def provenance(folder):
    from chartbook.snapshot import code_of, uncommitted
    result = []
    for pipeline, target in read(folder).items():
        try:
            commit = code_of(target).commit
            dirty = bool(uncommitted(target))
        except Exception:
            commit, dirty = None, None
        result.append({"pipeline": pipeline, "path": str(target), "commit": commit, "uncommitted": dirty})
    return result
