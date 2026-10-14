"""Snapshots: what one commit of a pipeline built, kept in the store.

A pipeline is worked on while other pipelines depend on it. So the others
never read its folder. They read a **snapshot**: every asset the pipeline
declares, as it was built at one commit, copied into the store and
labelled with that commit.

A snapshot is made on purpose, by whoever works on the pipeline, when its
build is ready for others::

    $ chartbook snapshot
    ftsfr/fed_yield_curve at 4f2a91c: 3 assets in the store
    Snapshot made. A pipeline that depends on this one gets it with `chartbook update`.

Three rules, decided by the maintainer on 2026-10-13
(``docs_src/design/overview.md``, "The snapshot model"):

- **Everything in the pipeline's folder must be committed first.** The
  label says "this is what that commit built", and with uncommitted
  changes it would not be true.
- **It is not made by every build.** Declaring a build ready is a
  decision, and the store changes slowly and on purpose.
- **Nothing else reads the folder.** :mod:`chartbook.lock` pins from a
  snapshot, and a pipeline's working directory can be in any state.

The same commit can have several snapshots. A pipeline that pulls data
from outside gives other bytes on another day, with no file changed, so a
snapshot has the time it was made, and the newest is the one a pin moves
to. A snapshot that would be the same as the one before it is not made.

Where they are kept::

    ~/.chartbook/store/
      snapshots/
        4f2a91c0…/                       the commit
          _top/                          a pipeline at the repository's top
            20261013T182205.123456Z.json
          examples--yield_curve/         one in a folder of the repository
            20261013T182205.123456Z.json

A record is JSON in the index's format, like a lockfile: an envelope and
one record for each asset, each with its content hash. The bytes are
objects in the store like any other, and a snapshot keeps them from being
cleared (:func:`chartbook.lock.plan_gc`).

**Clearing old ones.** Every snapshot is kept until ``chartbook store gc``
is run, and then one is kept if a lockfile pins it, if it is the newest of
its pipeline, if a label in that pipeline's manifest points at a model
version in it, or if it was made in the last :data:`KEEP_DAYS` days
(:func:`plan_removals`). The rest may be removed, and the command asks
first. Beside each pipeline's records the store notes the folder they were
made from (``origins``), which is how it finds that manifest.

A snapshot is found by commit, and a commit is the same in every clone of
a repository. So one made in a folder is found by a pipeline that depends
on that folder, and by one that depends on the same repository by URL.

Made by ``chartbook snapshot``, a snapshot takes its owner's word that what
is on disk was built by that commit. ``chartbook run --snapshot`` builds
and then makes one in the same command, and the record says so
(``built_with.run``).

**What a snapshot says, and what it does not.** Which data it is: the hash
of every file, which is complete. Which code made it: the commit. And a
short note of the conditions it was made under (``built_with``, and
``inputs``: what the pipeline itself was pinned to), which is there to
explain a difference between two snapshots, not to make a build
repeatable. Nothing of a pipeline's ``.env`` is ever copied: it holds
secrets, and a store is something to share.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from chartbook import hashing
from chartbook.identity import derive_pipeline_id
from chartbook.index import RECORD_VERSION, SCHEMAS_DIR, record_kind
from chartbook.manifest import VERSION_PATTERN, _read_manifest_file, resolve_project_type
from chartbook.refs import AssetRef
from chartbook.resolve import MANIFEST_NAME, declared_files
from chartbook.store import Store, default_store
from chartbook.utils import is_glob_pattern

#: The version of a snapshot record's envelope.
SCHEMA = "chartbook/snapshot/v1"

#: Where snapshot records are, under the store's root.
SNAPSHOTS_DIR = "snapshots"

#: The folder, under a commit's, for a pipeline at the top of its repository.
TOP = "_top"

#: How long a snapshot that nothing pins, that is not the newest of its
#: pipeline and that no label points into is kept, in days. Long enough to
#: come back from a holiday to; short enough that a nightly build does not
#: fill a disk that has no copy-on-write clones.
KEEP_DAYS = 30

#: Beside a pipeline's records: the folders its snapshots were made from, one
#: per line. Not a record, so it has no ``.json``. It is how ``store gc`` finds
#: the manifest whose labels say which versions to keep.
ORIGINS_FILE = "origins"

#: The kinds of link a snapshot's files are stored with: a copy-on-write
#: clone, or a copy. Never a hard link or a symlink, which are the
#: pipeline's own file and change when it is rewritten.
LINKS = ("reflink", "copy")

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class SnapshotError(Exception):
    """Raised when a snapshot cannot be made, or a pipeline has none to find."""


def schema_path() -> Path:
    """The JSON Schema file for a snapshot record's envelope."""
    return SCHEMAS_DIR / "snapshot" / "v1.json"


@dataclass(frozen=True)
class Code:
    """Where a pipeline's code is in git.

    Attributes:
        top: The top directory of the repository it is in.
        commit: The commit that repository is at, in full.
        subdirectory: The pipeline's folder within the repository, with
            ``/`` between its parts; empty at the top.
    """

    top: Path
    commit: str
    subdirectory: str


@dataclass(frozen=True)
class Snapshot:
    """What one commit of a pipeline built.

    Attributes:
        pipeline: The pipeline's own ID when the snapshot was made.
        commit: The commit it was built from.
        subdirectory: The pipeline's folder in its repository; empty at the top.
        made_at: When it was made, in UTC, to the microsecond:
            ``2026-10-13T18:22:05.123456Z``. With the commit, it is what
            names the snapshot.
        assets: A record for each asset the pipeline declared, by the
            asset's reference within the pipeline (``treasury_rates``,
            ``chart/curve_today``). One with a ``content_hash`` was built.
        path: The record's file, if it has been written.
        built_with: A note of the conditions it was made under: whether the
            build ran in the same command (``run``), and the versions of
            ChartBook and Python and the platform. It explains a
            difference; no hash covers it.
        inputs: What the pipeline itself was pinned to when the snapshot
            was made: the dependencies of its own lockfile, each with its
            commit and its ``pinned_hash``. Empty if it has no lockfile.
        labels: The model versions the pipeline's manifest labelled when
            the snapshot was made, by the model's reference: ``{"model/x":
            ["7f3a9c2e41b0"]}``. Labels travel with snapshots so that a
            machine that cannot read the folder they were made from, a
            store a team shares, still knows which versions to keep.
    """

    pipeline: str
    commit: str
    subdirectory: str
    made_at: str
    assets: dict[str, dict] = field(default_factory=dict)
    path: Optional[Path] = None
    built_with: dict = field(default_factory=dict, compare=False)
    inputs: list = field(default_factory=list, compare=False)
    labels: dict = field(default_factory=dict, compare=False)

    @property
    def built_by_run(self) -> bool:
        """Whether ChartBook ran the build in the command that made this."""
        return bool(self.built_with.get("run"))

    def hashes(self) -> set[str]:
        """The content hash of every asset in it: what the store must keep."""
        return {
            record["content_hash"]
            for record in self.assets.values()
            if record.get("content_hash")
        }

    def content(self) -> dict[str, Optional[str]]:
        """Each asset's content hash, by its reference; None if not built."""
        return {name: record.get("content_hash") for name, record in self.assets.items()}

    def same_moment(self, commit: Optional[str], made_at: Optional[str]) -> bool:
        """Whether this is the snapshot a lockfile names."""
        return self.commit == commit and self.made_at == made_at

    def to_document(self) -> dict:
        """The snapshot as it is written: an envelope and a list of records."""
        code = {"commit": self.commit}
        if self.subdirectory:
            code["subdirectory"] = self.subdirectory
        document = {
            "schema": SCHEMA,
            "root": self.pipeline,
            "code": code,
            "made_at": self.made_at,
        }
        if self.built_with:
            document["built_with"] = self.built_with
        if self.inputs:
            document["inputs"] = self.inputs
        if self.labels:
            document["labels"] = {name: sorted(self.labels[name]) for name in sorted(self.labels)}
        document["records"] = [self.assets[name] for name in sorted(self.assets)]
        return document


@dataclass
class SnapshotReport:
    """What making a snapshot did.

    Attributes:
        snapshot: The snapshot: the one just made, or the one already there
            when nothing had changed.
        made: Whether a new one was written.
        not_built: The assets the pipeline declares and has not built, each
            with its declared path.
        new_versions: The models whose bytes no earlier snapshot of this
            pipeline had, each with the name of the version this makes
            (:func:`version_name`). A snapshot is what makes a version.
    """

    snapshot: Snapshot
    made: bool
    not_built: list[tuple[str, str]] = field(default_factory=list)
    new_versions: list[tuple[str, str]] = field(default_factory=list)


def asset_record(
    ref: AssetRef, pipeline: str, declared_path: str, content, single: bool
) -> dict:
    """An asset as a snapshot and a lockfile record it; with its hash if stored.

    This is the one place that shape is written.

    :param ref: The asset's reference, qualified with the pipeline's name.
    :param pipeline: That name.
    :param declared_path: The asset's ``path`` as its manifest gives it.
    :param content: What was stored: its hash, its size and its files; or
        None for an asset that is declared and not built.
    :param single: Whether the asset's ``path`` named one file. A directory
        has its files listed, as the index lists a directory model's:
        ``files`` is what tells a directory from a file.
    """
    record = {
        "kind": record_kind(ref.kind),
        "version": RECORD_VERSION,
        "id": str(ref),
        "ref": ref.to_dict(),
        "pipeline": pipeline,
        "location": {"kind": "file", "path": declared_path},
    }
    if content is not None:
        record["content_hash"] = content.content_hash
        record["size_bytes"] = content.size_bytes
        if not single and not is_glob_pattern(declared_path):
            record["files"] = [
                {
                    "path": file.path,
                    "size_bytes": file.size_bytes,
                    "content_hash": file.content_hash,
                }
                for file in content.entries
            ]
    return record


def renamed(record: dict, pipeline: str) -> dict:
    """An asset's record under another name for its pipeline.

    A snapshot names a pipeline as the pipeline names itself. A lockfile
    names it by its key in ``[dependencies]``, which may differ.
    """
    local = AssetRef.from_dict(
        {key: record["ref"][key] for key in ("kind", "name") if key in record["ref"]}
    )
    ref = local.in_pipeline(pipeline)
    return {**record, "id": str(ref), "ref": ref.to_dict(), "pipeline": pipeline}


def local_name(record: dict) -> str:
    """An asset's reference within its pipeline: ``x``, or ``chart/y``."""
    return str(AssetRef(kind=record["ref"]["kind"], name=record["ref"]["name"]))


def _git(directory: Path, *arguments: str, stdin: str = "") -> str:
    """Run git in a directory and return what it printed.

    It takes no lock it does not need, so that looking at a repository
    never gets in the way of whoever is working in it.
    """
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            capture_output=True,
            text=True,
            env=environment,
            input=stdin,
        )
    except OSError as error:
        raise SnapshotError(f"git could not be run: {error}") from None
    if result.returncode != 0:
        said = result.stderr.strip() or f"git {arguments[0]} failed"
        raise SnapshotError(said)
    return result.stdout


def code_of(directory: Union[str, Path]) -> Code:
    """Say where a pipeline's folder is in git, and at which commit.

    :raises SnapshotError: If there is no such folder, it is not in a git
        repository, or the repository has no commit yet.
    """
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise SnapshotError(f"there is no folder at {directory}")
    try:
        top = Path(_git(directory, "rev-parse", "--show-toplevel").strip()).resolve()
    except SnapshotError:
        raise SnapshotError(
            f"{directory} is not in a git repository. A snapshot is labelled "
            f"with the commit it was built from, so only a pipeline that is in "
            f"git has any"
        ) from None
    try:
        commit = _git(directory, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").strip()
    except SnapshotError:
        raise SnapshotError(f"the repository at {top} has no commit yet") from None
    subdirectory = directory.relative_to(top).as_posix()
    return Code(top, commit, "" if subdirectory == "." else subdirectory)


def uncommitted(directory: Union[str, Path], ignoring: tuple = ()) -> list[str]:
    """What in a pipeline's folder is not committed, as ``git status`` lists it.

    A changed file, a staged one, and a new file that git does not ignore
    all count. What git ignores does not, which is how built data stays
    out of it. Only the pipeline's own folder is looked at, so other work
    in the same repository does not hold a snapshot up.

    :param ignoring: File names that do not count, wherever they are. The
        lockfile that ``chartbook run`` writes before a build is one.
    :returns: One line for each, as ``git status --porcelain`` prints it,
        with paths from the top of the repository.
    """
    # -z: one record per NUL, and paths as they are, not quoted and escaped
    # as they would be for a terminal. A rename or copy has the old path in
    # a record of its own, which follows.
    listing = _git(
        Path(directory).resolve(),
        "status", "--porcelain", "-z", "--untracked-files=all", "--", ".",
    )
    records = listing.split("\0")
    found = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 3:
            continue
        status, path = record[:2], record[3:]
        if status[0] in "RC" and index < len(records):
            path = f"{records[index]} -> {path}"
            index += 1
        if os.path.basename(path.split(" -> ")[-1]) in ignoring:
            continue
        found.append(f"{status} {path}")
    return found


def _folder(store: Store, commit: str, subdirectory: str) -> Path:
    """Where the records of one pipeline at one commit are kept.

    The pipeline's folder in its repository names it, with ``--`` for
    ``/``. A folder whose own name holds ``--``, or is ``_top``, would then
    be mistaken for another; such a one gets a short hash of itself as
    well, so that two pipelines never share a folder here.
    """
    if not _FULL_COMMIT.match(commit):
        raise ValueError(f"{commit!r} is not a full commit hash.")
    clean = subdirectory.strip("/")
    name = clean.replace("/", "--") or TOP
    if clean and ("--" in clean or name == TOP):
        name += "~" + hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8]
    return store.root / SNAPSHOTS_DIR / commit / name


def read(path: Union[str, Path]) -> Snapshot:
    """Read one snapshot record.

    :raises SnapshotError: If the file is not a record this version reads.
    """
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
        if document.get("schema") != SCHEMA:
            raise ValueError(
                f"its schema is {document.get('schema')!r}, and this version of "
                f"ChartBook reads {SCHEMA!r}"
            )
        code = document["code"]
        assets = {local_name(record): record for record in document["records"]}
        return Snapshot(
            pipeline=document["root"],
            commit=code["commit"],
            subdirectory=code.get("subdirectory", ""),
            made_at=document["made_at"],
            assets=assets,
            path=path,
            built_with=dict(document.get("built_with") or {}),
            inputs=list(document.get("inputs") or []),
            labels={k: list(v) for k, v in (document.get("labels") or {}).items()},
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError(f"Cannot read the snapshot {path}: {error}") from None


def find(store: Store, commit: str, subdirectory: str = "") -> list[Snapshot]:
    """The snapshots of one pipeline at one commit, newest first.

    :param store: The store they are kept in.
    :param commit: The commit, in full.
    :param subdirectory: The pipeline's folder in its repository.
    :raises SnapshotError: If one of them cannot be read.
    """
    folder = _folder(store, commit, subdirectory)
    if not folder.is_dir():
        return []
    found = [read(file) for file in folder.glob("*.json")]
    return sorted(found, key=lambda s: (s.made_at, _count(s.path)), reverse=True)


def newest_for(
    directory: Union[str, Path], store: Optional[Store] = None
) -> tuple[Optional[Snapshot], Code]:
    """Find the newest snapshot of the pipeline in a folder.

    That is the newest snapshot at the commit the folder is on or, if that
    commit has none, at the nearest commit before it that has one. So the
    folder's owner can be several commits past the last build they
    declared ready, and a pipeline that depends on the folder still gets
    that build. A snapshot made on another branch is not found.

    Nothing in the folder is read but where it is in git.

    :param directory: The pipeline's folder.
    :param store: The store; this user's by default.
    :returns: The snapshot, or None if there is none, and where the folder
        is in git now.
    :raises SnapshotError: If the folder is not in a git repository.
    """
    store = store if store is not None else default_store()
    code = code_of(directory)
    kept = store.root / SNAPSHOTS_DIR
    try:
        commits = {name for name in os.listdir(kept) if _FULL_COMMIT.match(name)}
    except FileNotFoundError:
        commits = set()
    if not commits:
        return None, code
    # Newest first, and the commit the folder is on comes first of all
    for commit in _git(code.top, "rev-list", "HEAD").split():
        if commit in commits:
            found = find(store, commit, code.subdirectory)
            if found:
                return found[0], code
    return None, code


def history(directory: Union[str, Path], store: Optional[Store] = None) -> list[Snapshot]:
    """Every snapshot of the pipeline in a folder, oldest first.

    At any commit the repository still has, on any branch or on none: a
    snapshot made on a branch that was never merged, or at a commit that
    was then amended away, is still something that was built. Only a
    commit git has pruned is gone, and so are its snapshots to this
    repository.

    :raises SnapshotError: If the folder is not in a git repository.
    """
    store = store if store is not None else default_store()
    code = code_of(directory)
    kept = store.root / SNAPSHOTS_DIR
    try:
        commits = {name for name in os.listdir(kept) if _FULL_COMMIT.match(name)}
    except FileNotFoundError:
        return []
    if not commits:
        return []
    # A store holds snapshots of many repositories; these are this one's.
    # Asked of the object store, not of the branches, so a commit that was
    # amended away still counts while git keeps it.
    answers = _git(
        code.top, "cat-file", "--batch-check=%(objectname) %(objecttype)",
        stdin="".join(f"{commit}\n" for commit in sorted(commits)),
    )
    ours = {
        line.split()[0] for line in answers.splitlines() if line.endswith(" commit")
    }
    found = [taken for commit in ours for taken in find(store, commit, code.subdirectory)]
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path)))


def versions_of(
    directory: Union[str, Path], name: str, store: Optional[Store] = None
) -> list[tuple[str, Snapshot]]:
    """The versions of one asset: each content it has had in a snapshot.

    A version is made by the first snapshot that holds those bytes. Making
    a snapshot again with the same bytes makes no new version.

    :param directory: The pipeline's folder.
    :param name: The asset's reference within the pipeline, ``model/x``.
    :returns: Each content hash with the first snapshot that held it,
        oldest first.
    """
    seen: dict[str, Snapshot] = {}
    for taken in history(directory, store):
        content_hash = (taken.assets.get(name) or {}).get("content_hash")
        if content_hash and content_hash not in seen:
            seen[content_hash] = taken
    return list(seen.items())


#: How many digits of a content hash name a version, unless more are needed.
#: Twelve, as Docker shows an image and the Linux kernel asks for a commit:
#: a label in a committed file should go on naming one version for years.
#: Among 10,000 versions of one model, two share twelve digits about once in
#: five million; with git's seven it would be nearer one in six.
VERSION_DIGITS = 12


def version_name(content_hash: str, among: Optional[list[str]] = None) -> str:
    """The name of a version: the start of its content hash, as git names a commit.

    ``sha256:7f3a9c2e41b0…`` is ``7f3a9c2e41b0``. It is the same on every machine and
    every branch, since it is worked out from the bytes and nothing else.

    :param among: The other versions of the same asset. If two would share
        a name, both get as many more digits as tells them apart.
    """
    digits = content_hash.split(":", 1)[-1]
    others = [h.split(":", 1)[-1] for h in (among or []) if h != content_hash]
    length = VERSION_DIGITS
    while length < len(digits) and any(o.startswith(digits[:length]) for o in others):
        length += 1
    return digits[:length]


def all_snapshots(store: Store) -> list[Snapshot]:
    """Every snapshot in a store, oldest first.

    :raises SnapshotError: If a record cannot be read. Nothing should be
        removed from a store that cannot say what it is keeping.
    """
    directory = store.root / SNAPSHOTS_DIR
    if not directory.is_dir():
        return []
    found = [read(file) for file in directory.glob("*/*/*.json")]
    return sorted(found, key=lambda taken: (taken.made_at, _count(taken.path)))


def all_hashes(store: Store) -> set[str]:
    """Every object any snapshot in a store names."""
    kept: set[str] = set()
    for taken in all_snapshots(store):
        kept |= taken.hashes()
    return kept


def _note_origin(folder: Path, top: Path) -> None:
    """Note, beside a pipeline's records, the repository folder they came from."""
    note = folder / ORIGINS_FILE
    line = str(top)
    try:
        known = note.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        known = []
    if line not in known:
        with open(note, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def origins(store: Store, taken: Snapshot) -> list[Path]:
    """The repository folders a pipeline's snapshots were made from."""
    note = _folder(store, taken.commit, taken.subdirectory) / ORIGINS_FILE
    try:
        lines = note.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    # Only an absolute folder is a place to look; anything else in the
    # file says nothing
    return [Path(line) for line in lines if line and os.path.isabs(line)]


def labels_of(raw: dict) -> dict[str, set[str]]:
    """The model versions a manifest's ``[models.x.aliases]`` point at.

    :returns: For each model's reference, the starts of the hashes its
        labels name. Only what a label may say counts: twelve or more hex
        digits; anything shorter would keep every snapshot for ever.
    """
    pointed: dict[str, set[str]] = {}
    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    for name, entry in models.items():
        aliases = entry.get("aliases") if isinstance(entry, dict) else None
        if not isinstance(aliases, dict):
            continue
        for version in aliases.values():
            if isinstance(version, str) and VERSION_PATTERN.match(version):
                pointed.setdefault(f"model/{name}", set()).add(version.split(":", 1)[-1])
    return pointed


def _labels_in(store: Store, group: list[Snapshot]) -> dict[str, set[str]]:
    """The labels of each model of one pipeline: as its manifest has them
    now, and as its snapshots recorded them.

    The manifest is read from each folder the pipeline's snapshots were
    made from. A folder that is gone, or whose manifest cannot be read,
    says nothing; and that is the case for every snapshot made on another
    machine, in a store a team shares, and for one made in a checkout that
    was thrown away. So the newest snapshot's own record of the labels its
    manifest had when it was made counts too: the newest only, so that a
    label the owner has since taken away releases its version once a
    snapshot follows. A label given after the newest snapshot is known
    only where the folder is.

    :returns: For each model's reference, the starts of the hashes its
        labels point at.
    """
    pointed: dict[str, set[str]] = {}
    seen: set[Path] = set()
    for name, starts in group[-1].labels.items():
        pointed.setdefault(name, set()).update(starts)
    for taken in group:
        for top in origins(store, taken):
            directory = top / taken.subdirectory if taken.subdirectory else top
            if directory in seen:
                continue
            seen.add(directory)
            try:
                raw = _read_manifest_file(directory)
            except (OSError, ValueError):
                continue
            for name, starts in labels_of(raw).items():
                pointed.setdefault(name, set()).update(starts)
    return pointed


def _pinnable(store: Store, group: list[Snapshot]) -> set[Path]:
    """The snapshots of one pipeline that a branch or a tag can pin from.

    ``pin`` takes the newest snapshot at the nearest commit, at or before
    the one a folder is on, that has one. So for each branch and tag of
    each repository the snapshots were made from, the first of its
    commits, walking back, that has a snapshot is pinnable, and the newest
    snapshot there is the one. A repository that is gone says nothing.

    :returns: The records' paths.
    """
    at_commit: dict[str, list[Snapshot]] = {}
    for taken in group:
        at_commit.setdefault(taken.commit, []).append(taken)
    keep: set[Path] = set()
    seen: set[Path] = set()
    for taken in group:
        for top in origins(store, taken):
            if top in seen:
                continue
            seen.add(top)
            try:
                tips = _git(top, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/tags")
            except SnapshotError:
                continue
            for tip in set(tips.split()):
                try:
                    walk = _git(top, "rev-list", tip)
                except SnapshotError:
                    continue
                for commit in walk.split():
                    if commit in at_commit:
                        keep.add(at_commit[commit][-1].path)
                        break
    return keep


def _made_at(taken: Snapshot) -> datetime:
    return datetime.fromisoformat(taken.made_at.rstrip("Z")).replace(tzinfo=timezone.utc)


@dataclass
class SnapshotPlan:
    """Which snapshots a store keeps and which it may let go of.

    Attributes:
        keep: Each snapshot that is kept, with why.
        remove: Each snapshot that may be removed, with why it may.
    """

    keep: list[tuple[Snapshot, str]] = field(default_factory=list)
    remove: list[tuple[Snapshot, str]] = field(default_factory=list)

    def kept_hashes(self) -> set[str]:
        """The objects the kept snapshots name."""
        hashes: set[str] = set()
        for taken, _ in self.keep:
            hashes |= taken.hashes()
        return hashes


def plan_removals(
    store: Store,
    pinned: set[tuple[str, str]],
    hashes_of_missing: set[str] = frozenset(),
    keep_days: float = KEEP_DAYS,
    now: Optional[datetime] = None,
) -> SnapshotPlan:
    """Say which snapshots may be removed. Nothing is removed.

    A snapshot is kept if, in this order:

    1. a lockfile pins it (its commit and time are named by a dependency);
    2. a lockfile that cannot be found named one of its objects when it was
       last pinned;
    3. it is the newest snapshot of its pipeline, or the newest that a
       branch or a tag of the repository it came from can pin from;
    4. a label points at a model version it holds: in the pipeline's
       manifest, read from the folder the snapshots were made from, or as
       recorded in the newest snapshot of the pipeline (:func:`labels_of`);
    5. it was made in the last *keep_days* days.

    Otherwise it may be removed. What it names and nothing else names is
    then removed with it, by :func:`chartbook.lock.plan_gc`.

    :param pinned: The ``(commit, made_at)`` pairs that readable lockfiles
        pin.
    :param hashes_of_missing: The objects named by lockfiles that cannot be
        found and are not to be forgotten.
    :raises SnapshotError: If a record cannot be read.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    plan = SnapshotPlan()
    groups: dict[tuple[str, str], list[Snapshot]] = {}
    for taken in all_snapshots(store):
        groups.setdefault((taken.pipeline, taken.subdirectory), []).append(taken)
    for group in groups.values():
        newest = group[-1]
        labels = _labels_in(store, group)
        pinnable = _pinnable(store, group)
        for taken in group:
            if (taken.commit, taken.made_at) in pinned:
                why = "a lockfile pins it"
            elif taken.hashes() & set(hashes_of_missing):
                why = "a lockfile that cannot be found named what it holds"
            elif taken is newest:
                why = "it is the newest of its pipeline"
            elif taken.path in pinnable:
                why = "it is the newest a branch or tag can pin from"
            elif any(
                (record.get("content_hash") or "").split(":", 1)[-1].startswith(start)
                for name, starts in labels.items()
                for record in [taken.assets.get(name) or {}]
                for start in starts
            ):
                why = "a label points at a version in it"
            elif (now - _made_at(taken)).total_seconds() < keep_days * 86400:
                why = f"it was made in the last {keep_days:g} days"
            else:
                plan.remove.append(
                    (taken, f"nothing pins it, it is not the newest, and it is older than {keep_days:g} days")
                )
                continue
            plan.keep.append((taken, why))
    return plan


def remove(store: Store, taken: Snapshot) -> bool:
    """Remove one snapshot's record. Its objects are the store's to clear.

    :returns: True if the record was there.
    """
    if taken.path is None or not taken.path.is_file():
        return False
    taken.path.unlink()
    folder = taken.path.parent
    if not any(folder.glob("*.json")):
        # The last record of this pipeline at this commit: its note of
        # origins goes too, and the folders if nothing else is in them. A
        # record another process is writing this moment is left alone.
        try:
            (folder / ORIGINS_FILE).unlink()
        except OSError:
            pass
        for empty in (folder, folder.parent):
            try:
                empty.rmdir()
            except OSError:
                break
    return True


def _count(path: Path) -> int:
    """Which of the snapshots made at one instant a file is: 1, unless numbered."""
    _, _, number = path.stem.partition("-")
    return int(number) if number.isdigit() else 1


def _now() -> str:
    """The time, in UTC, to the microsecond.

    It is that fine because the time is part of what names a snapshot: a lockfile
    says which one it pinned by its commit and its time, and two made at
    one commit must not look like the same one.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _write(snapshot: Snapshot, store: Store) -> Path:
    """Write a snapshot's record, whole or not at all, and return its file."""
    folder = _folder(store, snapshot.commit, snapshot.subdirectory)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.made_at.replace("-", "").replace(":", "")
    final = folder / f"{stamp}.json"
    count = 1
    while final.exists():
        count += 1
        final = folder / f"{stamp}-{count}.json"
    temporary = folder / f"{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_document(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temporary, final)
    finally:
        if temporary.exists():
            temporary.unlink()
    return final


def require_committed(
    directory: Union[str, Path], pipeline: str, ignoring: tuple = ()
) -> Code:
    """Check that a pipeline can have a snapshot now, and say where it is in git.

    :param ignoring: File names that may be uncommitted all the same; see
        :func:`uncommitted`.
    :raises SnapshotError: If its folder is not in git, or anything in it
        is not committed. The message lists what.
    """
    try:
        code = code_of(directory)
    except SnapshotError as error:
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {error}.") from None
    changes = uncommitted(directory, ignoring)
    if changes:
        shown = "\n".join(f"  {line}" for line in changes[:10])
        more = f"\n  and {len(changes) - 10} more" if len(changes) > 10 else ""
        raise SnapshotError(
            f"{pipeline} has changes that are not committed:\n{shown}{more}\n"
            f"A snapshot is labelled with the commit it was built from, so "
            f"everything in the pipeline's folder must be committed first."
        )
    return code


def check_within(directory: Union[str, Path], pipeline: str) -> None:
    """Refuse a manifest whose declared paths reach outside the pipeline's folder.

    What :func:`make` checks when it stores; here, so that it can be found
    out before a build, not after one.

    :raises SnapshotError: Naming the first asset that reaches out.
    """
    directory = Path(directory).resolve()
    for local, declared_path, absolute in declared_files(directory):
        reached = hashing.escapes(absolute, directory)
        if reached is not None:
            raise SnapshotError(
                f"{pipeline} declares {str(local.in_pipeline(pipeline))!r} at "
                f"{declared_path!r}, which reaches {reached}, outside the "
                f"pipeline's folder. A snapshot is what the pipeline built, so "
                f"everything in it must be under {directory}."
            )


def _built_with(run: bool) -> dict:
    """The conditions a snapshot is being made under, as far as they are recorded."""
    from chartbook import __version__

    return {
        "run": run,
        "chartbook": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _inputs(directory: Path) -> list:
    """What a pipeline is itself pinned to: the dependencies of its lockfile.

    Read from the file as it is, so that a snapshot says what it was built
    from. They hold no absolute path and no password.

    :raises SnapshotError: If there is a lockfile and it cannot be read.
    """
    lockfile = directory / "chartbook.lock"
    if not lockfile.is_file():
        return []
    try:
        with open(lockfile, encoding="utf-8") as f:
            records = json.load(f)["records"]
        for record in records:
            if record.get("kind") == "Pipeline":
                return list(record.get("dependencies") or [])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise SnapshotError(f"Cannot read {lockfile}: {error}") from None
    return []


def _scores(directory: Path, entry) -> Optional[dict]:
    """A model's scores as its metrics file has them now, if it has a readable one."""
    from chartbook.models import read_metrics

    declared = entry.get("metrics_path") if isinstance(entry, dict) else None
    if not isinstance(declared, str) or not declared.strip():
        return None
    metrics_file = directory / declared
    if not metrics_file.is_file():
        return None
    try:
        return read_metrics(metrics_file)
    except ValueError:
        return None  # `chartbook check` is what reports a malformed one


def pipeline_in(directory: Union[str, Path]) -> str:
    """The ID of the pipeline in a folder, which must hold one.

    :raises SnapshotError: If the folder holds no pipeline.
    """
    directory = Path(directory).resolve()
    manifest_path = directory / MANIFEST_NAME
    try:
        raw = _read_manifest_file(directory)
    except FileNotFoundError:
        raise SnapshotError(f"No {MANIFEST_NAME} in {directory}.") from None
    if resolve_project_type(raw, source=str(manifest_path)) != "pipeline":
        raise SnapshotError(
            f"{directory} is a catalog. A snapshot is of one pipeline: run "
            f"`chartbook snapshot` in the pipeline's own folder."
        )
    return derive_pipeline_id(raw.get("project") or {}, directory)


def make(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    made_at: Optional[str] = None,
    built_by_run: bool = False,
    ignoring: tuple = (),
) -> SnapshotReport:
    """Make a snapshot of a pipeline: what it has built, at the commit it is on.

    Every asset the pipeline declares and has built is put in the store,
    as its own frozen copy, and a record of them is written under the
    commit. An asset that is declared and not built is in the record
    without a hash, and in the report.

    If nothing has changed since the newest snapshot at this commit, no
    new one is made; unless that one took its owner's word and this one
    follows a build, which is worth recording.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param made_at: The time to record, for a test; now by default.
    :param built_by_run: Whether the build was run by the command that is
        making this snapshot (``chartbook run --snapshot``).
    :param ignoring: File names that may be uncommitted; see
        :func:`uncommitted`.
    :returns: The snapshot, and whether it is new.
    :raises SnapshotError: If the folder holds no pipeline, is not in git,
        has anything uncommitted, or has built nothing.
    """
    directory = Path(project_dir).resolve()
    pipeline = pipeline_in(directory)
    code = require_committed(directory, pipeline, ignoring)

    store = store if store is not None else default_store()
    raw = _read_manifest_file(directory)
    assets: dict[str, dict] = {}
    not_built: list[tuple[str, str]] = []
    check_within(directory, pipeline)
    for local, declared_path, absolute in declared_files(directory):
        ref = local.in_pipeline(pipeline)
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            assets[str(local)] = asset_record(ref, pipeline, declared_path, None, True)
            not_built.append((str(ref), declared_path))
            continue
        stored = store.put(absolute, links=LINKS)
        record = asset_record(ref, pipeline, declared_path, stored, found.single)
        if local.kind == "model":
            scores = _scores(directory, (raw.get("models") or {}).get(local.name))
            if scores is not None:
                # Kept with the version, so two versions can be compared
                # after the metrics file has been written over
                record["metrics"] = scores
        assets[str(local)] = record

    if not assets:
        raise SnapshotError(
            f"{pipeline} declares nothing with a path, so there is nothing to "
            f"take a snapshot of."
        )
    if len(not_built) == len(assets):
        raise SnapshotError(
            f"{pipeline} has built nothing it declares, so there is nothing to "
            f"take a snapshot of. Build it first: `chartbook run`."
        )

    snapshot = Snapshot(
        pipeline,
        code.commit,
        code.subdirectory,
        made_at or _now(),
        assets,
        built_with=_built_with(built_by_run),
        inputs=_inputs(directory),
        labels={name: sorted(starts) for name, starts in labels_of(raw).items()},
    )
    before = find(store, code.commit, code.subdirectory)
    if before and before[0].content() == snapshot.content():
        if before[0].built_by_run or not built_by_run:
            _note_origin(before[0].path.parent, code.top)
            return SnapshotReport(before[0], False, not_built)

    # A model whose bytes no snapshot of this pipeline has had is a new version
    new_versions = []
    for name in sorted(assets):
        content_hash = assets[name].get("content_hash")
        if not name.startswith("model/") or not content_hash:
            continue
        had = [h for h, _ in versions_of(directory, name, store)]
        if content_hash not in had:
            new_versions.append((name, version_name(content_hash, had)))

    path = _write(snapshot, store)
    _note_origin(path.parent, code.top)
    snapshot = Snapshot(
        snapshot.pipeline,
        snapshot.commit,
        snapshot.subdirectory,
        snapshot.made_at,
        assets,
        path,
        snapshot.built_with,
        snapshot.inputs,
        snapshot.labels,
    )
    return SnapshotReport(snapshot, True, not_built, new_versions)
