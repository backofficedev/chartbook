"""The lineage of a pipeline: every snapshot upstream of it, walked through the pins, and checked.

A snapshot records what its pipeline was pinned to (``inputs``): for each
dependency, the commit and time of the snapshot pinned and one hash over
everything pinned from it (``pinned_hash``). Those snapshots record
theirs, and so on up: a graph whose every edge is a hash. :func:`walk`
follows it up from a pipeline's own lockfile and checks each edge:

- the snapshot an edge names is in the store and can be read;
- what was pinned from it is what it holds: each asset at its hash, for
  the pipeline's own lockfile (:func:`chartbook.snapshot.lineage_gaps`);
  the hash over everything pinned, recomputed from the snapshot as a pin
  would make it, for a snapshot's recorded input;
- each snapshot's recorded inputs cover every dependency its own manifest
  declares, the manifest kept with it in the store (a snapshot made before
  snapshots checked their pins may not);
- each asset of each snapshot is in the store, and with ``rehash`` still
  hashes to its name.

A ``git`` dependency is pinned from its clone, not from a snapshot, so the
walk stops there and says so. A snapshot met twice is walked once. Nothing
is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import tomli

from chartbook import lock, snapshot
from chartbook.store import Store, StoreError, default_store

#: How many snapshots up the walk goes before it stops and says so:
#: deeper than any real graph, and a bound on one a store was made to loop
DEEPEST = 64

#: The most of a snapshot's kept manifest that is read
MANIFEST_LIMIT = 1024 * 1024


@dataclass
class Node:
    """One pipeline in the lineage: the folder it starts from, or a snapshot upstream.

    Attributes:
        label: How the pipeline below names it: its key in ``[dependencies]``,
            or, at the top, the pipeline's ID.
        pipeline: The pipeline's ID, as its snapshot names it; empty when
            no snapshot was found.
        commit: The commit of the snapshot, or of a ``git`` dependency's
            clone.
        made_at: When the snapshot was made.
        kind: ``working`` (the folder the walk starts from), ``snapshot``,
            ``git`` (pinned from a clone; not walked further), ``folder``
            (pinned from a working folder), ``nothing`` (nothing pinned) or
            ``missing`` (no such snapshot in the store).
        gaps: What is wrong at this point of the lineage, one line each.
        children: The pipelines it was pinned to.
        seen: Whether this snapshot was met before in the walk, and is
            shown there.
    """

    label: str
    pipeline: str = ""
    commit: str = ""
    made_at: str = ""
    kind: str = "snapshot"
    gaps: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    seen: bool = False
    hashes: set = field(default_factory=set, repr=False)

    def to_dict(self) -> dict:
        """The node and everything under it, as JSON can hold it."""
        shown = {"label": self.label, "kind": self.kind}
        for key in ("pipeline", "commit", "made_at"):
            if getattr(self, key):
                shown[key] = getattr(self, key)
        if self.seen:
            shown["seen"] = True
        shown["gaps"] = list(self.gaps)
        shown["children"] = [child.to_dict() for child in self.children]
        return shown


@dataclass
class Lineage:
    """What :func:`walk` found.

    Attributes:
        root: The pipeline the walk started from, with everything upstream.
        snapshots: How many snapshots were walked.
        rehashed: How many objects were hashed again (with ``rehash``).
    """

    root: Node
    snapshots: int = 0
    rehashed: int = 0

    def gaps(self) -> list[tuple[Node, str]]:
        """Every gap, with the node it is at, from the top down."""
        found: list[tuple[Node, str]] = []

        def visit(node: Node) -> None:
            found.extend((node, gap) for gap in node.gaps)
            for child in node.children:
                visit(child)

        visit(self.root)
        return found

    def to_dict(self) -> dict:
        return {
            "snapshots": self.snapshots,
            "rehashed": self.rehashed,
            "gaps": len(self.gaps()),
            "root": self.root.to_dict(),
        }


def walk(project_dir: Union[str, Path] = ".", store: Optional[Store] = None, rehash: bool = False) -> Lineage:
    """Walk a pipeline's lineage up from its lockfile, through every snapshot it leads to, and check each edge.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param rehash: Also hash every asset of every snapshot again, which
        reads all their bytes.
    :raises chartbook.snapshot.SnapshotError: If the folder holds no pipeline.
    """
    directory = Path(project_dir).resolve()
    store = store if store is not None else default_store()
    pipeline = snapshot.pipeline_in(directory)
    root = Node(label=pipeline, pipeline=pipeline, kind="working")
    try:
        root.gaps = snapshot.lineage_gaps(directory, store)
        locked = lock.read_lock(directory / lock.LOCK_FILE)
    except (lock.LockError, ValueError) as error:
        root.gaps = [str(error)]
        locked = None
    found, unreadable = snapshot.readable_snapshots(store)
    walker = _Walker(store, found, unreadable)
    for entry in locked.dependencies if locked is not None else []:
        root.children.append(walker.from_lockfile(entry, locked.assets_of(entry.get("id"))))
    lineage = Lineage(root, snapshots=len(walker.visited))
    walker.check_objects(lineage, rehash)
    return lineage


class _Walker:
    """One walk: the store's snapshots, read once, and what has been walked."""

    def __init__(self, store: Store, found: list, unreadable: list):
        self.store = store
        self.found = found
        self.unreadable = unreadable
        self.visited: dict[tuple, Node] = {}

    def _at(self, commit: str, made_at: str) -> list:
        return [taken for taken in self.found if taken.same_moment(commit, made_at)]

    def _missing(self, commit: str, made_at: str) -> str:
        why = next((reason for path, reason in self.unreadable if commit in str(path)), None)
        said = f": a record at that commit cannot be read ({why})" if why else ""
        return f"its snapshot at {commit[:7]}, made {made_at}, is not in the store{said}"

    def from_lockfile(self, entry: dict, records: dict) -> Node:
        """A dependency of the pipeline's own lockfile. Its gaps are the pipeline's, said at the top."""
        key = str(entry.get("id") or "?")
        location = entry.get("location") or {}
        node = Node(label=key, commit=location.get("commit") or "", made_at=entry.get("snapshot") or "")
        hashed = {asset_id: record for asset_id, record in records.items() if record.get("content_hash")}
        if location.get("kind") == "git":
            node.kind = "git"
            return node
        if not hashed:
            node.kind = "nothing"
            return node
        if not (node.commit and node.made_at):
            node.kind = "folder"
            return node
        plain = [record for record in hashed.values() if not (record.get("ref") or {}).get("rev")]
        held = [
            taken for taken in self._at(node.commit, node.made_at)
            if all(taken.content().get(snapshot.local_name(record)) == record["content_hash"] for record in plain)
        ]
        if not held:
            node.kind = "missing"
            return node
        return self._up(node, held[0], depth=1)

    def _from_input(self, key: str, entry: dict, depth: int) -> Node:
        """A dependency a snapshot recorded among its inputs."""
        location = entry.get("location") or {}
        node = Node(label=key, commit=location.get("commit") or "", made_at=entry.get("snapshot") or "")
        if location.get("kind") == "git":
            node.kind = "git"
            return node
        expected = entry.get("pinned_hash")
        if not expected:
            node.kind = "nothing"
            return node
        if not (node.commit and node.made_at):
            node.kind = "folder"
            node.gaps.append(
                "was pinned from its working folder, not from a snapshot, so nothing says which commit "
                "its bytes came from"
            )
            return node
        at = self._at(node.commit, node.made_at)
        matching = [taken for taken in at if self._pinned_hash(taken, key) == expected]
        if not matching:
            node.kind = "missing"
            if not at:
                node.gaps.append(self._missing(node.commit, node.made_at))
            else:
                node.gaps.append(
                    f"the hash recorded over what was pinned from its snapshot at {node.commit[:7]} is "
                    f"{expected[:19]}…, and that snapshot gives another: what was pinned is not what it "
                    f"holds (or a version one of its labels names is no longer in the store)"
                )
            return node
        return self._up(node, matching[0], depth)

    def _up(self, node: Node, taken, depth: int) -> Node:
        """A snapshot found: what it is, whether its inputs are complete, and what it was pinned to."""
        node.kind = "snapshot"
        node.pipeline, node.commit, node.made_at = taken.pipeline, taken.commit, taken.made_at
        node.hashes = {content_hash for content_hash in taken.content().values() if content_hash}
        moment = (taken.pipeline, taken.commit, taken.made_at)
        if moment in self.visited:
            node.seen = True
            return node
        self.visited[moment] = node
        if depth > DEEPEST:
            node.gaps.append(f"the walk stops here, {DEEPEST} snapshots up: the store may have been made to loop")
            return node
        inputs = {
            str(entry.get("id")): entry for entry in taken.inputs or []
            if isinstance(entry, dict) and entry.get("id")
        }
        declared, why = self._declared(taken)
        if declared is None:
            node.gaps.append(why)
        else:
            for key in sorted(declared - set(inputs)):
                node.gaps.append(
                    f"its manifest declares the dependency {key!r}, and the snapshot records no pin of "
                    f"it: it was made before snapshots checked their pins, or from a lockfile that did "
                    f"not list it"
                )
        for key, entry in sorted(inputs.items()):
            node.children.append(self._from_input(key, entry, depth + 1))
        return node

    def _declared(self, taken) -> tuple[Optional[set], str]:
        """The dependencies the snapshot's own manifest declares, as kept with it; None, and why, if that cannot be known."""
        documents = taken.documents
        if not isinstance(documents, dict) or not isinstance(documents.get("content_hash"), str):
            return None, (
                "its manifest is not kept with it (it was made before snapshots kept their documents), "
                "so whether its inputs are complete cannot be checked"
            )
        try:
            folder = Path(self.store.get(documents["content_hash"]))
            raw = tomli.loads(
                snapshot._read_regular_file(folder / "chartbook.toml", MANIFEST_LIMIT).decode("utf-8")
            )
        except (OSError, ValueError, StoreError, UnicodeDecodeError, RecursionError) as error:
            return None, f"its manifest kept with it cannot be read ({error}), so whether its inputs are complete cannot be checked"
        dependencies = raw.get("dependencies")
        return (set(dependencies) if isinstance(dependencies, dict) else set()), ""

    def _pinned_hash(self, taken, key: str) -> Optional[str]:
        """The hash over everything a pin of this snapshot under this key would hold, as ``chartbook pin`` makes it."""
        records = {}
        for name in sorted(taken.assets):
            record = snapshot.renamed(taken.assets[name], key)
            records[record["id"]] = record
        try:
            labelled, _ = snapshot.label_records(taken, key, self.store)
        except (StoreError, ValueError, OSError):
            labelled = {}
        records.update(labelled)
        return lock.pinned_hash(records.values())

    def check_objects(self, lineage: Lineage, rehash: bool) -> None:
        """Each walked snapshot's assets: in the store, and with ``rehash``, still what their names say."""
        owners: dict[str, list[Node]] = {}
        for node in self.visited.values():
            for content_hash in sorted(node.hashes):
                owners.setdefault(content_hash, []).append(node)
        present = []
        for content_hash, nodes in sorted(owners.items()):
            try:
                there = self.store.has(content_hash)
            except (StoreError, OSError, ValueError):
                there = False
            if there:
                present.append(content_hash)
                continue
            for node in nodes:
                node.gaps.append(f"holds {content_hash[:19]}…, which the store does not have")
        if not rehash:
            return
        for problem in self.store.verify(present):
            for node in owners.get(problem.content_hash, []):
                node.gaps.append(f"holds {problem.content_hash[:19]}…, which is not what its name says: {problem.message}")
        lineage.rehashed = len(present)
