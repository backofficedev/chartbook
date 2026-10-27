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

:func:`cycle` walks the same graph for another reason: dependencies between
pipelines must form a directed acyclic graph, and a pipeline that depends,
through what it depends on, on itself is refused by ``chartbook run``,
``chartbook build`` and ``chartbook snapshot``, and reported by ``chartbook
check``. That walk reads a folder on this machine before the store, so a
cycle is found as soon as it is declared.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Iterable, Optional, Union

import tomli

from chartbook import lock, snapshot
from chartbook.refs import AssetRef
from chartbook.store import Store, StoreError, default_store

#: How many snapshots up the walk goes before it stops and says so:
#: deeper than any real graph, and a bound on one a store was made to loop
DEEPEST = 64

#: The most of a snapshot's kept manifest that is read
MANIFEST_LIMIT = 1024 * 1024

#: The most inputs of one snapshot that are walked: more than any pipeline
#: declares, and a bound on a record written to make the walk wide
MOST_INPUTS = 1000


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
            ``git`` (pinned from a clone; not walked further), ``no_snapshot``
            (a pin that names no snapshot, as one in a lockfile changed by
            hand does), ``nothing`` (nothing pinned),
            ``missing`` (no such snapshot in the store), ``mismatch`` (the
            snapshot is there and does not hold what was pinned) or
            ``unreadable`` (a record that is not one ChartBook wrote).
        gaps: What is wrong at this point of the lineage, one line each.
        children: The pipelines it was pinned to.
        seen: Whether this snapshot was met before in the walk, and is
            shown there.
        checked: How the snapshot's lineage was checked when it was made,
            as its record says: ``pins``, ``deep``, or empty for one made
            before snapshots checked their pins.
    """

    label: str
    pipeline: str = ""
    commit: str = ""
    made_at: str = ""
    kind: str = "snapshot"
    gaps: list[str] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    seen: bool = False
    checked: str = ""
    tags: list = field(default_factory=list)
    hashes: set = field(default_factory=set, repr=False)

    def to_dict(self) -> dict:
        """The node and everything under it, as JSON can hold it."""
        shown = {"label": self.label, "kind": self.kind}
        for key in ("pipeline", "commit", "made_at"):
            if getattr(self, key):
                shown[key] = getattr(self, key)
        if self.seen:
            shown["seen"] = True
        if self.kind == "snapshot":
            shown["checked"] = self.checked or None
            shown["tags"] = list(self.tags)
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

    What is read from the store was written by whoever can write to it, so
    a record that is not what ChartBook writes is a gap where it is met,
    never an error that stops the walk.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param rehash: Also hash every asset of every snapshot again, and every
        model version a label pinned, which reads all their bytes.
    :raises chartbook.snapshot.SnapshotError: If the folder holds no pipeline.
    """
    directory = Path(project_dir).resolve()
    store = store if store is not None else default_store()
    pipeline = snapshot.pipeline_in(directory)
    root = Node(label=pipeline, pipeline=pipeline, kind="working")
    locked = None
    try:
        root.gaps = snapshot.lineage_gaps(directory, store)
        locked = lock.read_lock(directory / lock.LOCK_FILE)
    except Exception as error:  # a lockfile written by hand: said, not raised
        root.gaps = [f"its lockfile cannot be checked: {error}"]
    found, unreadable = snapshot.readable_snapshots(store)
    walker = _Walker(store, found, unreadable)
    for entry in locked.dependencies if locked is not None else []:
        root.children.append(walker.guarded(lambda: walker.from_lockfile(entry, locked.assets_of(entry.get("id"))), entry))
    lineage = Lineage(root, snapshots=len(walker.visited))
    walker.check_objects(lineage, rehash)
    return lineage


def _text(value: object) -> str:
    """A value of a record as text, if it is text; else empty."""
    return value if isinstance(value, str) else ""


class _Walker:
    """One walk: the store's snapshots, read once, and what has been walked."""

    def __init__(self, store: Store, found: list, unreadable: list):
        self.store = store
        self.found = found
        self.unreadable = unreadable
        self.visited: dict[str, Node] = {}
        self.extra: dict[str, set] = {}

    def guarded(self, make, entry: object) -> Node:
        """A node made from records anyone may have written: a gap, not an error, if they are not what they should be."""
        try:
            return make()
        except Exception as error:
            key = entry.get("id") if isinstance(entry, dict) else None
            node = Node(label=_text(key) or "?", kind="unreadable")
            node.gaps.append(f"its record is not one ChartBook wrote ({type(error).__name__}: {error})")
            return node

    def _at(self, commit: str, made_at: str) -> list:
        return [taken for taken in self.found if taken.same_moment(commit, made_at)]

    def _missing(self, commit: str, made_at: str) -> str:
        why = next((reason for path, reason in self.unreadable if commit in str(path)), None)
        said = (
            f": a record at that commit cannot be read ({why})" if why
            else " (`store gc` lets old lineage go unless it is run with --keep-lineage)"
        )
        return f"its snapshot at {commit[:7]}, made {made_at}, is not in the store{said}"

    def from_lockfile(self, entry: dict, records: dict) -> Node:
        """A dependency of the pipeline's own lockfile. Its gaps are the pipeline's, said at the top."""
        key = _text(entry.get("id")) or "?"
        location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
        node = Node(label=key, commit=_text(location.get("commit")), made_at=_text(entry.get("snapshot")))
        hashed = {
            asset_id: record for asset_id, record in records.items()
            if isinstance(record, dict) and _text(record.get("content_hash"))
        }
        if location.get("kind") == "git":
            node.kind = "git"
            return node
        if not hashed:
            node.kind = "nothing"
            return node
        if not (node.commit and node.made_at):
            node.kind = "no_snapshot"
            return node
        plain = [record for record in hashed.values() if not (record.get("ref") or {}).get("rev")]
        labels = {record["content_hash"] for record in hashed.values() if (record.get("ref") or {}).get("rev")}
        at = self._at(node.commit, node.made_at)
        held = [
            taken for taken in at
            if all(taken.content().get(snapshot.local_name(record)) == record["content_hash"] for record in plain)
        ]
        if not held:
            node.kind = "missing" if not at else "mismatch"
            return node
        return self._up(node, held[0], depth=1, labels=labels)

    def _from_input(self, key: str, entry: dict, depth: int) -> Node:
        """A dependency a snapshot recorded among its inputs."""
        location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
        node = Node(label=key, commit=_text(location.get("commit")), made_at=_text(entry.get("snapshot")))
        if location.get("kind") == "git":
            node.kind = "git"
            return node
        expected = entry.get("pinned_hash")
        if not expected:
            node.kind = "nothing"
            return node
        if not isinstance(expected, str):
            raise TypeError(f"its pinned_hash is {type(expected).__name__}, not text")
        if not (node.commit and node.made_at):
            node.kind = "no_snapshot"
            node.gaps.append(
                "its pin named no snapshot, so nothing says which commit its bytes came from"
            )
            return node
        at = self._at(node.commit, node.made_at)
        matching = []
        for taken in at:
            made, labels = self._pinned_hash(taken, key, expected)
            if made == expected:
                matching.append((taken, labels))
        if not matching:
            node.kind = "missing" if not at else "mismatch"
            if not at:
                node.gaps.append(self._missing(node.commit, node.made_at))
            else:
                unlisted = getattr(self, "listing_error", "")
                said = f"; the store's objects could not be listed ({unlisted})" if unlisted else ""
                node.gaps.append(
                    f"the hash recorded over what was pinned from its snapshot at {node.commit[:7]} is "
                    f"{expected[:19]}…, and that snapshot gives another: what was pinned is not what it "
                    f"holds (or a version one of its labels names is no longer in the store){said}"
                )
            return node
        taken, labels = matching[0]
        return self._up(node, taken, depth, labels=labels)

    def _up(self, node: Node, taken, depth: int, labels: frozenset = frozenset()) -> Node:
        """A snapshot found: what it is, whether its inputs are complete, and what it was pinned to."""
        node.kind = "snapshot"
        node.pipeline, node.commit, node.made_at = taken.pipeline, taken.commit, taken.made_at
        recorded = (taken.built_with or {}).get("lineage") if isinstance(taken.built_with, dict) else None
        node.checked = recorded if recorded in ("pins", "deep") else ""
        node.tags = list(taken.tags or [])
        node.hashes = {h for h in taken.content().values() if isinstance(h, str) and h} | set(labels)
        if depth > DEEPEST:
            node.gaps.append(f"the walk stops here, {DEEPEST} snapshots up: the store may have been made to loop")
            return node
        place = str(taken.path)
        if place in self.visited:
            node.seen = True
            return node
        self.visited[place] = node
        listed = taken.inputs if isinstance(taken.inputs, list) else []
        inputs = {
            entry["id"]: entry for entry in listed[:MOST_INPUTS]
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry.get("id")
        }
        if len(listed) > MOST_INPUTS:
            node.gaps.append(f"its record lists {len(listed)} inputs; the first {MOST_INPUTS} are walked")
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
            node.children.append(self.guarded(lambda: self._from_input(key, entry, depth + 1), entry))
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

    def _pinned_hash(self, taken, key: str, expected: Optional[str] = None) -> tuple[Optional[str], frozenset]:
        """The hash over everything a pin of this snapshot under this key would hold, as ``chartbook pin`` makes it; and the label versions in it.

        When a label's version is named by more than one object (anyone who
        can write to the store can add one), each reading is tried, and the
        one that gives *expected* is taken.
        """
        import itertools

        records = {}
        for name in sorted(taken.assets):
            record = snapshot.renamed(taken.assets[name], key)
            records[record["id"]] = record
        labelled = self._label_records(taken, key)
        choices = [[(label_id, record) for record in options] for label_id, options in sorted(labelled.items())]
        made = None
        for picked in itertools.islice(itertools.product(*choices), 64):
            trial = {**records, **dict(picked)}
            made = lock.pinned_hash(trial.values())
            if expected is None or made == expected:
                return made, frozenset(record["content_hash"] for _, record in picked)
        if not choices:
            return lock.pinned_hash(records.values()), frozenset()
        return made, frozenset()

    def _label_records(self, taken, key: str) -> dict:
        """The records a pin may have made of the snapshot's labels, by ID, each with the readings possible.

        As :func:`chartbook.snapshot.label_records` makes them. Each label
        names the start of a version's hash. The version is looked for among
        the snapshots this walk read (never the store's records again, so
        one that cannot be read does not stop it); failing that, among the
        store's objects. Only versions whose bytes are in the store count,
        as at pin time; a label with none is left out, as a pin leaves it.
        """
        records: dict[str, list] = {}
        labels = taken.labels if isinstance(taken.labels, dict) else {}
        for name, named in sorted(labels.items()):
            if not isinstance(named, dict) or name not in taken.assets:
                continue
            versions = None
            for label, start in sorted(named.items()):
                start = str(start).split(":", 1)[-1]
                if len(start) < 12:
                    continue
                if versions is None:
                    versions = {
                        content_hash for content_hash, _ in snapshot.versions_of_pipeline(
                            self.store, taken.pipeline, taken.subdirectory, name, found=self.found
                        )
                    }
                named_hashes = {h for h in versions if h.split(":", 1)[-1].startswith(start)}
                if not named_hashes:
                    named_hashes = {h for h in self._objects() if h.split(":", 1)[-1].startswith(start)}
                options = []
                for content_hash in sorted(named_hashes):
                    try:
                        if not self.store.has(content_hash):
                            continue
                    except (StoreError, OSError, ValueError):
                        continue
                    record = {k: v for k, v in snapshot.renamed(taken.assets[name], key).items() if k != "trained_on"}
                    ref = dataclasses.replace(AssetRef.from_dict(record["ref"]), rev=label)
                    options.append({**record, "id": str(ref), "ref": ref.to_dict(), "label": label, "content_hash": content_hash})
                if options:
                    records[options[0]["id"]] = options
        return records

    def _objects(self) -> set:
        """Every object's hash in the store, listed once a walk needs it."""
        if not hasattr(self, "_listed"):
            self.listing_error = ""
            try:
                self._listed = set(self.store.hashes())
            except (StoreError, OSError, ValueError) as error:
                self._listed = set()
                self.listing_error = str(error)
        return self._listed

    def check_objects(self, lineage: Lineage, rehash: bool) -> None:
        """Each walked snapshot's assets, and each label version pinned: in the store, and with ``rehash``, still what their names say."""
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


@dataclass
class Edge:
    """One pipeline depending on another, as met on the way to and round a cycle.

    Attributes:
        pipeline: The ID of the pipeline that depends.
        dependency: The ID of the pipeline it depends on.
        key: The key ``pipeline`` declares it under in ``[dependencies]``.
        where: Where the dependency was read: the manifest that declares it,
            or the snapshot whose record lists it among its inputs.
    """

    pipeline: str
    dependency: str
    key: str
    where: str


@dataclass
class Cycle:
    """A cycle :func:`cycle` found, and how the pipeline it started from reaches it.

    Attributes:
        edges: The edges round the cycle, starting at the pipeline in it
            that the walk met first, and ending with the edge back to it.
        way_in: The edges from the pipeline the walk started from down to
            that one; empty when the pipeline is in the cycle itself.
        two_places: ``(ID, folder, folder)`` when the cycle closes on its
            ID in another folder than the one it was met in: two checkouts
            of one repository, or two pipelines that share the ID. None
            otherwise.
    """

    edges: list[Edge]
    way_in: list[Edge] = field(default_factory=list)
    two_places: Optional[tuple] = None


def cycle(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    follow_pins: bool = True,
    pipeline: Optional[str] = None,
    git_cache=None,
    lockfiles: Optional[dict] = None,
    shared: Optional[dict] = None,
    members: Optional[dict] = None,
    through: Optional[Iterable[str]] = None,
) -> Optional[Cycle]:
    """The first cycle among the pipelines upstream of this one, with the way to it; None if there is none.

    Dependencies between pipelines form a directed graph, and it has to be
    acyclic: a pipeline that depends, through what it depends on, on itself
    has no order to be built in, and its snapshot would carry itself in its
    lineage. The graph is walked from the pipeline's folder, each edge read
    from where it is best known:

    - a dependency whose folder is on this machine (a ``path`` one, or one
      named by the ID of a pipeline in *members*): that folder's own
      ``[dependencies]``, so a cycle is found as soon as it is declared,
      and the snapshot its pin names as well, since ``pin`` does not move
      a pin whatever the folder says now;
    - a ``git`` dependency, and one named by its ID that was got from its
      repository: its copy at the commit its pin names, if it is fetched;
    - any other (named by its ID, or a folder not on this machine): the
      snapshot its pin names, and what that snapshot recorded it was
      pinned to (a snapshot, or a clone that is fetched here), and so on
      up through the store.

    A pipeline is known by its ID, so one met as a folder and again as a
    snapshot is one node, and a cycle is a pipeline met again on the way up
    from itself. An ID names one pipeline: two folders, or two snapshots,
    under one ID are that pipeline (two clones or worktrees of one
    repository are). A copy that kept its original's ID and reads the
    original depends on itself; where the cycle closes on its ID in
    another folder (``two_places``), it names both, and says what to do
    whether they are one pipeline or two. A folder or a snapshot walked once is not walked again
    unless something above it is reachable from it, which is a cycle.
    Nothing is said of what cannot be read here: a dependency with no pin
    and no folder, a ``git`` one not fetched, a folder whose manifest or
    lockfile cannot be read, or a record in the store that is not one
    ChartBook wrote. ``chartbook check`` and ``chartbook pin`` say what is
    wrong with those.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param follow_pins: Whether to read the store for what the pins name.
        False keeps the walk to the folders on this machine, for a check
        that must not use the network.
    :param pipeline: What to call the pipeline walked from; its own ID by
        default. ``chartbook run`` names a ``git`` dependency's working
        copy by the key it is declared under, as the pipeline that declares
        it does.
    :param git_cache: Where ``git`` dependencies are fetched to; this
        user's by default.
    :param lockfiles: Lockfiles as they would be written, by the folder
        they belong to, read in place of the files there: ``chartbook run``
        walks the pins it is about to make before it makes them. A ``git``
        dependency's folder is its working copy, where ``chartbook run``
        builds and pins it.
    :param shared: A dict that walks share, so that the store is read
        once for all of them. A caller that writes snapshots between walks
        sets ``shared["may_be_old"]``: a walk then reads the store again
        when a pin names a snapshot the reading lacks, once for each.
    :param through: The keys of the pipeline's own ``[dependencies]`` to
        walk from; all of them by default. A pin's guard walks from those it
        pins or moves: a cycle reached only through what was pinned before
        is not that pin's doing.
    :param members: The pipelines of a run or a catalog, their folders by
        their IDs. A dependency named by the ID of one is followed through
        its folder, as a ``path`` dependency is: that is what the run
        builds, pins and makes a snapshot of.
    :raises chartbook.snapshot.SnapshotError: If the folder holds no pipeline.
    :raises ValueError: If the pipeline's own ``[dependencies]`` is malformed.
    """
    from chartbook.manifest import validate_dependencies

    directory = Path(project_dir).resolve()
    root = pipeline or snapshot.pipeline_in(directory)
    finder = _Finder(store, follow_pins, git_cache, lockfiles, shared, members)
    # The pipeline's own table is read as the command would read it: an
    # error in it is the command's to say, where one upstream is passed over
    validate_dependencies(snapshot._read_manifest_file(directory).get("dependencies") or {}, directory)
    #: The pipelines on the way down, by ID, and where each was met
    chain: list[str] = [root]
    places: list[object] = [directory]
    walk_from = None if through is None else set(through)
    edges: list[Edge] = []
    #: Every pipeline reachable from each folder or snapshot walked, by what
    #: names that place, once its walk is done
    reach: dict[str, set] = {}

    def visit(source: object, place: str) -> tuple[Optional[Cycle], set]:
        below: set = set()
        if len(chain) > DEEPEST:
            return None, below  # not recorded: a shorter way to it may still walk it
        for edge, child, named in finder.children(chain[-1], source):
            if walk_from is not None and len(chain) == 1 and edge.key not in walk_from:
                continue
            if edge.dependency in chain:
                at = chain.index(edge.dependency)
                return Cycle(edges[at:] + [edge], edges[:at], _two_places(edge.dependency, places[at], child)), below
            below.add(edge.dependency)
            known = reach.get(named)
            if known is not None and not (known & set(chain)):
                below |= known  # walked already, and nothing above here is reachable from it
                continue
            chain.append(edge.dependency)
            places.append(child)
            edges.append(edge)
            found, theirs = visit(child, named)
            chain.pop()
            places.pop()
            edges.pop()
            if found is not None:
                return found, below
            below |= theirs
        reach[place] = below
        return None, below

    found, _ = visit(directory, str(directory))
    return found


def _two_places(pipeline: str, one: object, other: object) -> Optional[tuple]:
    """Where a cycle closes on its ID, when that is another folder than the one it was met in: ``(ID, folder, folder)``; None otherwise."""
    if not (isinstance(one, Path) and isinstance(other, Path)):
        return None
    one, other = Path(one).resolve(), Path(other).resolve()
    if _same_folder(str(one), str(other)):
        return None
    return (pipeline, one, other)


def two_places_said(pipeline: str, one: Path, other: Path) -> str:
    """What to say of an ID met in one folder and again in another: both, and what to do either way."""
    return (
        f"{pipeline} is met in {one} and again in {other}, and an ID names one pipeline. If they are one "
        f"pipeline, as two checkouts of one repository are, take one of these dependencies out. If they are "
        f"two pipelines that share the ID (one kept another's `[project] id` or `repo_url`, say), give one of "
        f"them an ID of its own with `[project] id` in its chartbook.toml."
    )


def _same_folder(one: str, other: str) -> bool:
    """Whether two paths are one folder, on a disk that may not tell case apart too."""
    if one == other:
        return True
    try:
        return os.path.samefile(one, other)
    except OSError:
        return False


def explain_cycle(found: Cycle) -> str:
    """The edges to and round a cycle, one line each with where it was read, and what to do about it."""
    lines = []
    for edge in [*found.way_in, *found.edges]:
        named = "" if edge.key == edge.dependency else f" (as {edge.key!r})"
        lines.append(f"  {edge.pipeline} depends on {edge.dependency}{named}: {edge.where}")
    if found.two_places is not None:
        lines.append(two_places_said(*found.two_places))
        return "\n".join(lines)
    lines.append(
        "Dependencies between pipelines must form a graph with no cycles. Take one of these out of its "
        "[dependencies]; where a snapshot records it, that pipeline makes a new snapshot, and what pins "
        "it runs `chartbook update`."
    )
    return "\n".join(lines)


def cycle_lead(found: Cycle) -> str:
    """How a cycle is announced, after the name of the pipeline walked from: who is in it, in one clause."""
    if found.way_in:
        return (
            "a pipeline it depends on depends on itself" if len(found.edges) == 1
            else "pipelines it depends on depend on each other"
        )
    return "it depends on itself" if len(found.edges) == 1 else "these pipelines depend on each other"


class _Finder:
    """Where each pipeline's dependencies are read from, for :func:`cycle`: folders here, and the store once it is needed."""

    def __init__(
        self, store: Optional[Store], follow_pins: bool, git_cache=None, lockfiles: Optional[dict] = None,
        shared: Optional[dict] = None, members: Optional[dict] = None,
    ):
        self.store = store
        self.follow_pins = follow_pins
        self.git_cache = git_cache
        #: A folder's lockfile as it would be written, read in place of its file
        self.lockfiles = {Path(folder).resolve(): locked for folder, locked in (lockfiles or {}).items()}
        #: The store's snapshots, once read; shared between walks when the caller says so
        self.shared = shared if shared is not None else {}
        #: The folders of the pipelines a run builds, by their IDs
        self.members = {pipeline: Path(folder).resolve() for pipeline, folder in (members or {}).items()}
        #: Whether this walk read the store itself, rather than taking another walk's reading
        self.read_here = False

    def children(self, pipeline: str, source: object) -> list[tuple[Edge, object, str]]:
        """Each dependency of a pipeline as ``(edge, where to read its own from, what names that place)``.

        *source* is the pipeline's folder, the snapshot it was met as, or
        None for one known by its ID alone, which has nothing to read.
        """
        try:
            if isinstance(source, Path):
                return self._from_folder(pipeline, source)
            if isinstance(source, snapshot.Snapshot):
                return self._from_snapshot(pipeline, source)
        except Exception:  # noqa: BLE001 - a folder or a record that is not as it should be: not this walk's to say
            return []
        return []

    def _from_folder(self, pipeline: str, folder: Path) -> list:
        from chartbook.manifest import validate_dependencies
        from chartbook.resolve import MANIFEST_NAME

        raw = snapshot._read_manifest_file(folder)
        dependencies = validate_dependencies(raw.get("dependencies") or {}, folder)
        try:
            on_file = lock.read_lock(folder / lock.LOCK_FILE)
        except lock.LockError:
            on_file = None  # `chartbook pin` says so; its pins cannot be followed
        would_be = self.lockfiles.get(folder.resolve())

        def by_key(locked) -> dict:
            return {
                entry["id"]: entry for entry in (locked.dependencies if locked is not None else [])
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            }

        filed = by_key(on_file)
        pinned = by_key(would_be) if would_be is not None else filed
        where = f"declared in {folder / MANIFEST_NAME}"
        children = []
        for key in sorted(dependencies):
            # A pin the run would make, and has not: said as such
            new = would_be is not None and pinned.get(key) != filed.get(key)
            try:
                children.extend(self._declared(pipeline, folder, key, dependencies[key], pinned.get(key) or {}, where, new))
            except Exception:  # noqa: BLE001 - one that cannot be read here; the others are still followed
                continue
        return children

    def _declared(self, pipeline: str, folder: Path, key: str, entry: dict, listed: dict, where: str, new: bool = False) -> list:
        """One entry of a folder's ``[dependencies]``, as the edges it gives.

        A ``git`` dependency, and one named by its ID that was got from its
        repository, is read from its copy at the commit its pin names. A
        dependency whose folder is here (a ``path`` one, or one named by
        the ID of a pipeline of the run) is read from that folder, and from
        the snapshot its pin names too: ``pin`` does not move a pin, so the
        pipeline is built from that snapshot, whatever its folder says now.
        Any other is read from the snapshot its pin names. *new* says the
        pin is one the run would make, not one in the lockfile.
        """
        from chartbook.config import clone_url_for, get_default_host
        from chartbook.gitcache import default_git_cache, local_url
        from chartbook.identity import derive_pipeline_id
        from chartbook.manifest import resolve_project_type
        from chartbook.resolve import MANIFEST_NAME

        location = listed.get("location") if isinstance(listed.get("location"), dict) else {}
        if "git" in entry or (entry.get("_store") and location.get("kind") == "git"):
            # Fetched at the commit its pin names, or nothing of it is here
            commit = _text(location.get("commit"))
            if "git" in entry:
                url = local_url(entry["git"], folder)
            else:
                # Got from its repository by its ID, as `pin` finds that repository
                url = (entry.get("repository") if entry.get("_repository") else None) or clone_url_for(
                    entry["_store"], get_default_host()
                )
            cache = self.git_cache if self.git_cache is not None else default_git_cache()
            # Its working copy, where `chartbook run` builds and pins it, else its checkout
            checkout = cache.files(url, commit) if commit and url else None
            if checkout is None and entry.get("_store"):
                checkout = self._clone_of(entry["_store"], commit)  # the default host may have moved since
            if checkout is None or not (checkout / MANIFEST_NAME).is_file():
                return [(Edge(pipeline, entry["_store"], key, where), None, f"id:{entry['_store']}")] if entry.get("_store") else []
            project = snapshot._read_manifest_file(checkout).get("project")
            project = project if isinstance(project, dict) else {}
            # A checkout's folder is named after a commit, so only an ID the
            # manifest gives means something; else the ID it was named by, or
            # the key it is declared under, as `chartbook run` names it
            named = derive_pipeline_id(project, checkout) if project.get("id") else (entry.get("_store") or key)
            return [(Edge(pipeline, named, key, where), checkout, str(checkout))]
        children = []
        there = (
            Path(entry["_resolved_path"]).resolve() if entry.get("_resolved_path")
            else self.members.get(entry.get("_store")) if entry.get("_store")
            else None
        )
        if there is not None and (there / MANIFEST_NAME).is_file():
            theirs = snapshot._read_manifest_file(there)
            if resolve_project_type(theirs, source=str(there / MANIFEST_NAME)) != "pipeline":
                return []  # a catalog: `chartbook check` says so
            project = theirs.get("project")
            named = derive_pipeline_id(project if isinstance(project, dict) else {}, there)
            children.append((Edge(pipeline, named, key, where), there, str(there)))
        # The snapshot its pin names, if the store has it
        taken = self._pinned(_text(location.get("commit")), _text(listed.get("snapshot")))
        if taken is not None:
            at = _text(taken.commit)[:7]
            said = f"{where}; it would now be pinned to its snapshot at {at}" if new else f"{where}; pinned to its snapshot at {at}"
            children.append((Edge(pipeline, taken.pipeline, key, said), taken, str(taken.path)))
        elif entry.get("_store") and not children:
            children.append((Edge(pipeline, entry["_store"], key, where), None, f"id:{entry['_store']}"))
        return children

    def _clone(self, url: str, commit: str) -> Optional[Path]:
        """A repository's copy at a commit, if it is fetched here: its working copy, else its checkout."""
        from chartbook.gitcache import default_git_cache

        cache = self.git_cache if self.git_cache is not None else default_git_cache()
        return cache.files(url, commit) if url and commit else None

    def _clone_of(self, pipeline_id: str, commit: str) -> Optional[Path]:
        """A copy at a commit, in the git cache, of the repository whose manifest names this ID; None if there is none.

        For one got from its repository by its ID: its lockfile records no
        address, which is worked out from the default host, and that may
        have changed since the pin, which stays where it was. A commit and
        the ID its manifest gives are enough to find it. Working copies
        come first, as ``chartbook run`` builds and pins one there.
        """
        import os
        import re

        from chartbook.gitcache import CHECKOUTS_DIR, WORK_DIR, default_git_cache
        from chartbook.resolve import MANIFEST_NAME

        if not (pipeline_id and re.fullmatch(r"[0-9a-f]{40}", commit or "")):
            return None
        cache = self.git_cache if self.git_cache is not None else default_git_cache()
        for top in (Path(cache.root) / WORK_DIR, Path(cache.root) / CHECKOUTS_DIR):
            # Down the repositories' folders (host/owner/name, or a cache that
            # laid a repository on this disk out under its whole path), never
            # into a copy's own files
            stack = [(top, 0)]
            while stack:
                folder, depth = stack.pop()
                try:
                    entries = list(os.scandir(folder))
                except OSError:
                    continue
                for found in entries:
                    if not found.is_dir(follow_symlinks=False):
                        continue
                    if found.name == commit:
                        there = Path(found.path)
                        try:
                            project = snapshot._read_manifest_file(there).get("project") if (there / MANIFEST_NAME).is_file() else None
                        except Exception:  # noqa: BLE001 - a copy whose manifest cannot be read names nothing
                            project = None
                        if isinstance(project, dict) and project.get("id") == pipeline_id:
                            return there
                    elif depth < 64 and not re.fullmatch(r"[0-9a-f]{40}", found.name):
                        stack.append((Path(found.path), depth + 1))
        return None

    def _from_snapshot(self, pipeline: str, taken) -> list:
        listed = taken.inputs if isinstance(taken.inputs, list) else []
        where = f"recorded by the snapshot of {pipeline} at {_text(taken.commit)[:7]}, made {_text(taken.made_at)[:10]}"
        children = []
        for entry in listed[:MOST_INPUTS]:
            try:
                child = self._recorded(pipeline, entry, where)
            except Exception:  # noqa: BLE001 - an input not as ChartBook records one; the others are still followed
                continue
            if child is not None:
                children.append(child)
        return children

    def _recorded(self, pipeline: str, entry: object, where: str):
        """One input a snapshot recorded: the snapshot it names, if the store has it, else the ID it names."""
        if not isinstance(entry, dict) or not _text(entry.get("id")):
            return None
        key = entry["id"]
        location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
        if location.get("kind") == "git":
            # Pinned from a clone, not a snapshot: known by the ID it was
            # named by, else by the key it was declared under, as a folder's
            # fetched git dependency is named; walked through the clone if
            # it is fetched here
            from chartbook.config import clone_url_for, get_default_host
            from chartbook.gitcache import local_url
            from chartbook.identity import derive_pipeline_id
            from chartbook.resolve import MANIFEST_NAME

            named = _text(location.get("pipeline")) or key
            try:
                url = _text(location.get("url"))
                if url and not (Path(url).is_absolute() or ":" in url):
                    url = ""  # a path relative to a folder the record does not name
                elif url:
                    url = local_url(url, Path("/"))
                checkout = self._clone(url, _text(location.get("commit"))) if url else None
                if checkout is None and _text(location.get("pipeline")):
                    # Got from its repository by its ID: the address recorded, else the default host's
                    for candidate in (lambda: _text(location.get("repository")), lambda: clone_url_for(location["pipeline"], get_default_host())):
                        try:
                            checkout = self._clone(candidate() or "", _text(location.get("commit")))
                        except Exception:  # noqa: BLE001 - not an address the git cache takes: the next
                            checkout = None
                        if checkout is not None:
                            break
                    if checkout is None:
                        checkout = self._clone_of(location["pipeline"], _text(location.get("commit")))
                if checkout is not None and (checkout / MANIFEST_NAME).is_file():
                    project = snapshot._read_manifest_file(checkout).get("project")
                    project = project if isinstance(project, dict) else {}
                    named = derive_pipeline_id(project, checkout) if project.get("id") else named
                    return Edge(pipeline, named, key, where), checkout, str(checkout)
            except Exception:  # noqa: BLE001 - no clone to be found from this record: known by its ID
                pass
            return Edge(pipeline, named, key, where), None, f"id:{named}"
        below = self._pinned(_text(location.get("commit")), _text(entry.get("snapshot")))
        if below is not None:
            return Edge(pipeline, below.pipeline, key, where), below, str(below.path)
        if location.get("kind") == "store" and _text(location.get("pipeline")):
            return Edge(pipeline, location["pipeline"], key, where), None, f"id:{location['pipeline']}"
        return None

    def _pinned(self, commit: str, made_at: str):
        """The snapshot a pin names, if the store has one whose record names a pipeline."""
        if not (commit and made_at) or not self.follow_pins:
            return None
        if "found" not in self.shared:
            self._read()
        while True:
            for taken in self.shared["found"]:
                if taken.same_moment(commit, made_at) and _text(taken.pipeline):
                    return taken
            missing = self.shared.setdefault("missing", set())
            if self.read_here or not self.shared.get("may_be_old") or (commit, made_at) in missing:
                missing.add((commit, made_at))
                return None
            # Another walk's reading, made before snapshots this pin may name: read once more
            self._read()

    def _read(self) -> None:
        """Read the store's snapshots, for this walk and those it shares with."""
        try:
            store = self.store if self.store is not None else default_store()
            self.shared["found"] = snapshot.readable_snapshots(store)[0]
        except (StoreError, OSError, ValueError):
            self.shared["found"] = []
        #: The pins this reading was found not to have: not read again for
        self.shared["missing"] = set()
        self.read_here = True
