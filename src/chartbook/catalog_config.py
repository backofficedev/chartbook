"""Migration of working-folder catalogs to store catalogs."""
from pathlib import Path
import shutil
import tomli
import tomli_w


def migrate(path=None):
    from chartbook.config import get_global_config_dir, get_store_url, read_settings
    from chartbook.manifest import _catalog_entries, resolve_platform_path, catalog_entry_dir
    from chartbook.multi_store import Stores
    from chartbook.snapshot import readable_snapshots
    configured = (read_settings().get("catalog") or {}).get("path") if path is None else None
    source = Path(path or configured).expanduser() if path or configured else get_global_config_dir() / "chartbook.toml"
    if source.is_dir():
        source /= "chartbook.toml"
    target = source.with_name("catalog.toml")
    if target.exists():
        raise ValueError(f"{target} already exists; migration did not change it")
    with source.open("rb") as stream:
        raw = tomli.load(stream)
    if raw.get("project", {}).get("type") != "catalog" and "pipelines" not in raw:
        raise ValueError(f"{source} is not a catalog")
    # Discover before writing: a failure never leaves a half-migrated catalog.
    entries = _catalog_entries(raw, source.parent, str(source))
    all_entries = raw.get("pipelines", {})
    # Disabled entries were omitted from ordinary member discovery. Discover
    # their identities too, so hiding a legacy alias still hides its snapshot.
    import copy
    discovery = copy.deepcopy(raw)
    discovery.get("pipelines", {}).pop("disabled", None)
    for entry in discovery.get("pipelines", {}).values():
        if isinstance(entry, dict):
            entry.pop("disabled", None)
    discovered = _catalog_entries(discovery, source.parent, str(source))
    stores = Stores.configured(catalog=target)
    found, _ = readable_snapshots(stores)
    held = {taken.pipeline for taken in found}
    missing = []
    for key, entry in entries.items():
        if entry.get("path") and key not in held:
            folder = catalog_entry_dir(source.parent, resolve_platform_path(entry["path"]))
            from chartbook.resolve import _own_id
            actual = _own_id(folder) or key
            if actual not in held:
                missing.append((actual, folder))
    notes = {}
    disabled = set(all_entries.get("disabled", []))
    for key, entry in discovered.items():
        original = all_entries.get(key, {})
        note = {k: original[k] for k in ("disabled", "repository") if isinstance(original, dict) and k in original}
        if key in disabled:
            note["disabled"] = True
        if note:
            translated = key
            if entry.get("path"):
                from chartbook.resolve import _own_id
                folder = catalog_entry_dir(source.parent, resolve_platform_path(entry["path"]))
                translated = _own_id(folder) or key
            notes[translated] = note
    for key in disabled - discovered.keys():
        notes.setdefault(key, {})["disabled"] = True
    result = {k: v for k, v in raw.items() if k != "pipelines"}
    result.setdefault("project", {}).pop("type", None)
    result["stores"] = {"default": {"url": get_store_url()}}
    if notes:
        result["pipelines"] = notes
    # Exclusive creation and an exact backup keep this operation recoverable.
    backup = source.with_suffix(source.suffix + ".pre-0.4.bak")
    if backup.exists():
        raise ValueError(f"Backup already exists: {backup}")
    shutil.copy2(source, backup)
    try:
        with target.open("xb") as stream:
            tomli_w.dump(result, stream)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    from chartbook.config import read_global_settings, write_global_settings
    settings = read_global_settings()
    configured = settings.get("catalog", {}).get("path")
    if isinstance(configured, str) and Path(configured).expanduser().resolve() == source.resolve():
        settings["catalog"]["path"] = str(target.resolve())
        write_global_settings(settings)
    source.unlink()
    return target, missing


def edit_store(name, spec=None, catalog=None):
    """Edit one store table, preserving all other TOML and comments."""
    import tomlkit
    from chartbook.config import get_default_catalog_path, get_global_catalog_path
    from chartbook.multi_store import Stores
    path = Path(catalog) if catalog else (get_default_catalog_path() or get_global_catalog_path())
    if path.is_dir():
        path /= "catalog.toml"
    if path.name != "catalog.toml":
        raise ValueError(f"{path} is not catalog.toml; run `chartbook catalog migrate` for an old catalog")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    tables = doc.setdefault("stores", tomlkit.table())
    from collections.abc import MutableMapping
    if not isinstance(tables, MutableMapping):
        raise ValueError("[stores] must be a table")
    if spec is None:
        if name not in tables:
            raise ValueError(f"Unknown store {name!r}")
        del tables[name]
    else:
        if name in tables:
            raise ValueError(f"Store {name!r} already exists")
        tables[name] = spec
    # Validate before replacement, including canonical duplicates and URLs.
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", dir=path.parent, delete=False, encoding="utf-8", newline="\n") as stream:
        staged = Path(stream.name)
        stream.write(tomlkit.dumps(doc))
    try:
        Stores.configured(staged)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)
    return path


def route(pipeline, names, catalog):
    """Set one pipeline's write destinations, preserving comments."""
    import tomlkit
    path = Path(catalog)
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    for name, table in doc["stores"].items():
        pipelines = [p for p in table.get("pipelines", []) if p != pipeline]
        if name in names:
            pipelines.append(pipeline)
        if pipelines or "pipelines" in table:
            table["pipelines"] = pipelines
    path.write_text(tomlkit.dumps(doc), encoding="utf-8", newline="\n")
