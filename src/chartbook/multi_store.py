"""Machine catalogs and federation above the unchanged Store plugin contract."""
from __future__ import annotations

import contextlib
import contextvars
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import tomli

from chartbook.store import (FolderStore, ObjectNotFoundError, ReadOnlyStoreError, StoreError, StoreNotAvailableError,
                            StoreUnreachableError, store_for_url)


settings_warnings = set()

selected_store = contextvars.ContextVar("chartbook_selected_store", default=None)


@dataclass
class NamedStore:
    name: str
    url: str
    store: object
    read_only: bool = False
    pipelines: tuple[str, ...] = ()
    create: bool = False
    unavailable: bool = False

    @property
    def reachable(self):
        return not self.unavailable and (not isinstance(self.store, FolderStore) or self.store.root.is_dir() or (self.create and not self.read_only))


class Stores:
    """Ordered stores; reads fan in, writes use explicit catalog routing.

    This is an adapter, not a new plugin contract. Destructive maintenance
    must select an individual store, whose retention notes remain independent.
    """
    def __init__(self, entries, catalog=None):
        self.entries = list(entries)
        self.catalog = catalog
        self._warned = set()
        if not self.entries:
            raise ValueError("At least one store is required")

    @classmethod
    def configured(cls, catalog=None, named=None, *, ignore_env: bool = False):
        """The stores a catalog lists, or the one the settings name.

        :param named: The catalog's path as a message names it, where
            *catalog* is a staged copy of it that is being checked.
        :param ignore_env: When True, ignore ``CHARTBOOK_STORE`` so *catalog*
            itself is validated (used when editing ``catalog.toml``).
        """
        from chartbook.config import (get_default_catalog_path, get_store_url,
                                      folder_of_store_url, store_kind)
        from chartbook.manifest import resolve_platform_path
        override = "" if ignore_env else os.environ.get("CHARTBOOK_STORE", "").strip()
        if override:
            return cls([NamedStore("default", override, store_for_url(override), create=True)])
        path = Path(catalog) if catalog else get_default_catalog_path()
        if path and path.is_dir():
            path /= "catalog.toml"
        raw = {}
        if path and path.is_file():
            with path.open("rb") as stream:
                raw = tomli.load(stream)
        if path and path.name == "chartbook.toml" and (raw.get("project", {}).get("type") == "catalog" or "pipelines" in raw):
            raise ValueError(f"{path} is an old catalog. Run `chartbook catalog migrate`.")
        definitions = raw.get("stores", {})
        if not isinstance(definitions, dict):
            raise ValueError("[stores] must be a table")
        entries, seen = [], set()
        for name, spec in definitions.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
                raise ValueError(f"Invalid store name {name!r}")
            if not isinstance(spec, dict) or set(spec) - {"url", "read_only", "pipelines"}:
                raise ValueError(f"[stores.{name}] accepts url, read_only and pipelines")
            url = spec.get("url")
            if isinstance(url, dict):
                if set(url) - {"unix", "windows"} or not all(isinstance(v, str) and v.strip() for v in url.values()):
                    raise ValueError(f"[stores.{name}] platform URLs must be nonempty unix/windows strings")
                url = str(resolve_platform_path(url))
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"[stores.{name}] needs a nonempty url")
            if store_kind(url) == "folder":
                from chartbook.config import _absolute_if_folder
                url = str(Path(_absolute_if_folder(url, path)).resolve())
            identity = url.rstrip("/")
            if identity in seen:
                raise ValueError(f"Store {name!r} names a store already listed")
            seen.add(identity)
            read_only = spec.get("read_only", False)
            pipelines = spec.get("pipelines", [])
            if not isinstance(read_only, bool):
                raise ValueError(f"[stores.{name}] read_only must be a boolean")
            if not isinstance(pipelines, list) or not all(isinstance(p, str) for p in pipelines):
                raise ValueError(f"[stores.{name}] pipelines must be an array of IDs")
            from chartbook.identity import validate_pipeline_id
            for pipeline in pipelines:
                validate_pipeline_id(pipeline)
            try:
                opened = store_for_url(url)
            except StoreNotAvailableError as error:
                # Every command stops with the line, and says which store of the catalog it is and how to take it out
                raise StoreNotAvailableError(
                    f"{error} It is the store {name!r} of the catalog {named or path}: `chartbook store remove {name}` takes it out "
                    f"of the catalog, and leaves the bucket as it is."
                ) from None
            entries.append(NamedStore(name, url, opened, read_only, tuple(pipelines), not entries))
        if entries:
            from chartbook.config import get_store_setting
            _, origin = get_store_setting()
            if origin in ("user", "system") and str(path) not in settings_warnings:
                settings_warnings.add(str(path))
                warnings.warn("[store] url in settings is ignored because the catalog defines [stores].", stacklevel=2)
            return cls(entries, path)
        url = get_store_url()
        return cls([NamedStore("default", url, store_for_url(url), create=True)], path)

    def find(self, commit, subdirectory=""):
        from chartbook.snapshot import find
        return find(self, commit, subdirectory)

    def snapshots(self, pipeline=None):
        from chartbook.snapshot import readable_snapshots
        found, _ = readable_snapshots(self)
        return [t for t in found if pipeline is None or t.pipeline == pipeline]

    def snapshot_commit_prefixes(self):
        return set(self._collect("snapshot_commit_prefixes"))

    def default(self):
        return self.entries[0].store

    def in_order(self):
        return [entry.store for entry in self.entries]

    def named(self, name):
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise ValueError(f"Unknown store {name!r}; choose {', '.join(e.name for e in self.entries)}")

    def for_writing(self, pipeline, names=None):
        chosen = ([self.named(name) for name in names] if names else
                  [e for e in self.entries if pipeline in e.pipelines] or [self.entries[0]])
        for entry in chosen:
            if entry.read_only:
                raise ReadOnlyStoreError(f"Store {entry.name!r} is read-only")
            if not entry.reachable:
                raise StoreUnreachableError(f"Store {entry.name!r} is unreachable: {entry.store}")
        return [e.store for e in chosen]

    def _available(self):
        for entry in self.entries:
            if entry.reachable:
                yield entry
            elif entry.name not in self._warned:
                self._warned.add(entry.name)
                warnings.warn(f"Store {entry.name!r} is unreachable: {entry.store}", stacklevel=3)

    def name_of(self, path):
        path = Path(path)
        for entry in self._available():
            try:
                if path in entry.store.all_snapshot_files():
                    return entry.name
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
        return None

    def _unreachable(self, entry, error):
        entry.unavailable = True
        if entry.name not in self._warned:
            warnings.warn(f"Store {entry.name!r} is unreachable: {error}", stacklevel=3)
            self._warned.add(entry.name)

    def _collect(self, method, *args):
        found = []
        for entry in self._available():
            try:
                found.extend(getattr(entry.store, method)(*args))
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
        return found

    @staticmethod
    def _deduplicated(paths):
        # Physical listings differ after a cross-store copy. Identity is the
        # logical record and hashes, never a path to bytes in another store.
        import json
        from chartbook.store import _any_length
        found, seen = [], set()
        for path in paths:
            try:
                content = Path(_any_length(path)).read_bytes()
                try:
                    document = json.loads(content)
                    if isinstance(document, dict):
                        document.pop("stored", None)
                        parts = list(document.get("records", [])) + [document.get("documents"), document.get("index")]
                        for part in parts:
                            if isinstance(part, dict):
                                part.pop("stored", None)
                    content = json.dumps(document, sort_keys=True).encode()
                except (ValueError, TypeError, AttributeError):
                    pass
            except OSError:
                content = str(path).encode()
            if content not in seen:
                found.append(path)
                seen.add(content)
        return found

    def all_snapshot_files(self):
        return self._deduplicated(self._collect("all_snapshot_files"))

    def snapshot_files(self, commit, name):
        return self._deduplicated(self._collect("snapshot_files", commit, name))

    def snapshot_commits(self):
        return set(self._collect("snapshot_commits"))

    def pinned_snapshot_files(self):
        return self._deduplicated(self._collect("pinned_snapshot_files"))

    def has(self, content_hash, pipeline=None):
        return next(self._holding(content_hash, pipeline), None) is not None

    def _holding(self, content_hash, pipeline=None):
        for entry in self._available():
            try:
                if entry.store.has(content_hash, pipeline):
                    yield entry.store
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)

    def files(self, content_hash, pipeline=None, name=None, snapshot=None):
        failures = []
        for store in self._holding(content_hash, pipeline):
            try:
                return store.files(content_hash, pipeline, name, snapshot=snapshot)
            except (StoreError, OSError) as error:
                failures.append(error)
        if failures:
            raise failures[0]
        raise ObjectNotFoundError(f"No reachable store holds {content_hash}")

    def incomplete(self, content_hash, size_bytes, files=None, every=False, pipeline=None):
        # In the stores that have it for that pipeline, as a read of it looks for it
        problems = []
        for entry in self._available():
            try:
                if not entry.store.has(content_hash, pipeline):
                    continue
                problem = entry.store.incomplete(content_hash, size_bytes, files, every, pipeline=pipeline)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
                continue
            if problem is None:
                return None
            problems.append(problem)
        return problems[0] if problems else None

    def hashes(self):
        return iter(sorted(set(self._collect("hashes"))))

    def held_hashes(self):
        return set(self._collect("held_hashes"))

    def origins(self, commit, name):
        return self._collect("origins", commit, name)

    def listing(self, content_hash, single):
        for entry in self._available():
            try:
                if not entry.store.has(content_hash):
                    continue
                listing = entry.store.listing(content_hash, single)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
                continue
            if listing is not None:
                return listing
        return None

    def files_of(self, content_hash):
        return self._collect("files_of", content_hash)

    def size_of(self, content_hash):
        for entry in self._available():
            try:
                if not entry.store.has(content_hash):
                    continue
                return entry.store.size_of(content_hash)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
        raise ObjectNotFoundError(f"No reachable store holds {content_hash}")

    def age_of(self, content_hash, now=None):
        ages = []
        for entry in self._available():
            try:
                if not entry.store.has(content_hash):
                    continue
                ages.append(entry.store.age_of(content_hash, now))
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
        if not ages:
            raise ObjectNotFoundError(f"No reachable store holds {content_hash}")
        return min(ages)

    def roots(self):
        return self._collect("roots")

    def verify(self, content_hashes=None, pipeline=None):
        if content_hashes is None:
            problems = []
            for entry in self._available():
                try:
                    problems.extend(entry.store.verify())
                except (StoreUnreachableError, OSError) as error:
                    self._unreachable(entry, error)
            return problems
        # Each store is asked of the objects it holds: one another store
        # holds is not missing from it. One that no store holds is said
        # missing once, as the first reachable store says it
        wanted = list(dict.fromkeys(content_hashes))
        problems, unheld, first = [], set(wanted), None
        for entry in self._available():
            try:
                held = [content_hash for content_hash in wanted if entry.store.has(content_hash, pipeline)]
                if held:
                    found_problems = entry.store.verify(held) if pipeline is None else entry.store.verify(held, pipeline)
                else:
                    found_problems = []
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
                continue
            first = first or entry.store
            unheld.difference_update(held)
            if found_problems:
                problems.extend(found_problems)
        if unheld:
            missing = [content_hash for content_hash in wanted if content_hash in unheld]
            if first is not None:
                problems.extend(first.verify(missing) if pipeline is None else first.verify(missing, pipeline))
            else:
                from chartbook.store import StoreProblem
                problems.extend(
                    StoreProblem(content_hash, Path(str(self)), f"No configured store is reachable to verify {content_hash}")
                    for content_hash in missing
                )
        return problems

    def begin(self, *args, **kwargs):
        self.for_writing("", [self.entries[0].name])
        return self.default().begin(*args, **kwargs)

    def put(self, *args, **kwargs):
        self.for_writing("", [self.entries[0].name])
        return self.default().put(*args, **kwargs)

    def _root_entries(self, hashes, snapshots):
        from chartbook.store import _snapshot_triple

        targets = []
        for entry in self._available():
            if entry.read_only:
                continue
            if entry is self.entries[0]:
                targets.append(entry)
                continue
            try:
                if any(entry.store.has(h) for h in hashes) or any(
                    _snapshot_triple(item)[1] in entry.store.snapshot_commits() for item in snapshots
                ):
                    targets.append(entry)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
        return targets

    def writable_stores(self):
        """Every writable store a note may be written to."""
        return [entry.store for entry in self._available() if not entry.read_only]

    def note_targets(self, hashes, snapshots=()):
        """The writable stores a note of these pins is written to: the default, and any that already hold the objects or the commits."""
        return [
            entry.store
            for entry in self._root_entries(hashes, () if snapshots is None else snapshots)
        ]

    def add_root(self, lockfile, hashes, snapshots=(), machine=None, labelled=(), *, host=None, node=None, keep_newest=False):
        hashes, labelled = list(hashes), list(labelled)
        snap_list = None if snapshots is None else list(snapshots)
        targets = self._root_entries(hashes, () if snap_list is None else snap_list)
        target_ids = {id(entry) for entry in targets}
        first_error = None
        for entry in targets:
            try:
                entry.store.add_root(
                    lockfile, hashes, snap_list, machine, labelled, host=host, node=node, keep_newest=keep_newest,
                )
            except (StoreError, OSError) as error:
                if first_error is None:
                    first_error = error
        for entry in self._available():
            if not entry.read_only and id(entry) not in target_ids:
                with contextlib.suppress(StoreError, OSError):
                    entry.store.remove_root(lockfile, machine)
        if first_error is not None:
            raise first_error

    def root_of(self, lockfile, machine=None):
        from chartbook.store import Root

        entries = [e for e in self._available() if not e.read_only]
        roots = []
        for e in entries:
            try:
                root = e.store.root_of(lockfile, machine)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(e, error)
                continue
            if root is not None:
                roots.append(root)
        if not roots:
            return None
        if len(roots) == 1:
            return roots[0]
        first = roots[0]
        hashes = tuple(sorted(set().union(*(r.hashes for r in roots))))
        explicit = [set(r.snapshots) for r in roots if r.snapshots is not None]
        snapshots = tuple(sorted(set().union(*explicit))) if explicit else None
        # A note with no snapshot list keeps the newest holder of each object. Merging it with a list
        # keeps that rule and the listed snapshots; dropping the rule would let gc remove what it held.
        keep_newest = snapshots is not None and any(r.keeps_newest() for r in roots)
        labelled = (
            tuple(sorted(set().union(*(r.labelled for r in roots if r.labelled is not None))))
            if any(r.labelled is not None for r in roots)
            else None
        )
        return Root(
            first.lockfile, hashes, first.machine, first.host, first.note,
            snapshots, first.node, labelled, written=first.written, keep_newest=keep_newest,
        )

    def note_matches(self, lockfile, hashes, snapshots, machine, labelled, *, keep_newest=False) -> bool:
        """Whether every writable store that would receive this note already holds it identically."""
        hashes = list(hashes)
        snap_list = None if snapshots is None else list(snapshots)
        labelled_set = set(labelled or ())
        targets = self._root_entries(hashes, () if snap_list is None else snap_list)
        target_ids = {id(entry) for entry in targets}
        wanted = set() if snap_list is None else set(snap_list)
        hashes_set = set(hashes)
        for entry in targets:
            try:
                root = entry.store.root_of(lockfile, machine)
            except (StoreUnreachableError, OSError) as error:
                self._unreachable(entry, error)
                return False
            held = set() if root is None or root.snapshots is None else set(root.snapshots)
            if (
                root is None
                or set(root.hashes) != hashes_set
                or root.keeps_newest() != (snap_list is None or bool(keep_newest))
                or held != wanted
                or set(root.labelled or ()) != labelled_set
            ):
                return False
        for entry in self._available():
            if not entry.read_only and id(entry) not in target_ids:
                try:
                    if entry.store.root_of(lockfile, machine) is not None:
                        return False
                except (StoreUnreachableError, OSError) as error:
                    self._unreachable(entry, error)
        return True

    def remove_root(self, lockfile, machine=None):
        removed = False
        first_error = None
        for entry in self._available():
            if not entry.read_only:
                try:
                    removed = entry.store.remove_root(lockfile, machine) or removed
                except (StoreError, OSError) as error:
                    if first_error is None:
                        first_error = error
        if first_error is not None:
            raise first_error
        return removed

    @contextlib.contextmanager
    def reading(self):
        with contextlib.ExitStack() as stack:
            for entry in self._available():
                try:
                    stack.enter_context(entry.store.reading())
                except (StoreUnreachableError, OSError) as error:
                    self._unreachable(entry, error)
            yield self

    def __getattr__(self, name):
        if name in {"delete", "delete_unowned", "remove_snapshot", "tidy", "tidy_pipeline", "check_tidy", "remove_root"}:
            raise ValueError("Select one store for destructive maintenance with --store NAME")
        return getattr(self.default(), name)

    def __str__(self):
        return ", ".join(f"{entry.name}: {entry.store}" for entry in self.entries)


def with_dependencies(folder, store=None):
    """Add portable dependency publishing locations as read-only sources."""
    from chartbook.config import store_kind
    folder = Path(folder)
    if os.environ.get("CHARTBOOK_STORE", "").strip():
        # The process override is deliberately stronger than a project's URLs.
        from chartbook.store import default_store
        return store if store is not None else default_store()
    base = store if store is not None else Stores.configured()
    raw = tomli.loads((folder / "chartbook.toml").read_text(encoding="utf-8"))
    deps = raw.get("dependencies")
    if not isinstance(deps, dict):
        return base
    urls = []
    for key, entry in deps.items():
        if isinstance(entry, dict) and entry.get("store"):
            url = entry["store"]
            if not isinstance(url, str) or not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url) or store_kind(url) == "folder":
                raise ValueError(f"Dependency {key!r}: store must be a portable store URL, never a folder")
            urls.append((key, url))
    if not urls:
        return base
    entries = list(base.entries) if isinstance(base, Stores) else [NamedStore("default", str(base), base, create=True)]
    seen = {entry.url for entry in entries}
    for key, url in urls:
        if url not in seen:
            try:
                opened = store_for_url(url)
            except StoreNotAvailableError as error:
                # The line's own ways out are the settings and a catalog, and this URL is in neither: say where it is
                raise StoreNotAvailableError(
                    f"{error} It is the store that the dependency {key!r} names, `[dependencies.\"{key}\"] store` in "
                    f"{folder / 'chartbook.toml'}: take that line out, and the dependency is read from the stores this "
                    f"machine is set to use."
                ) from None
            entries.append(NamedStore(f"dependency-{len(entries)}", url, opened, read_only=True))
            seen.add(url)
    return Stores(entries, getattr(base, "catalog", None))
