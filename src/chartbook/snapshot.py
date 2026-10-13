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

A snapshot is found by commit, and a commit is the same in every clone of
a repository. So one made in a folder is found by a pipeline that depends
on that folder, and by one that depends on the same repository by URL.

It takes the owner's word that what is on disk was built by that commit.
ChartBook does not run the build first; ``chartbook run`` does that.
"""

from __future__ import annotations

import json
import os
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
from chartbook.manifest import _read_manifest_file, resolve_project_type
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
    """

    pipeline: str
    commit: str
    subdirectory: str
    made_at: str
    assets: dict[str, dict] = field(default_factory=dict)
    path: Optional[Path] = None

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
        return {
            "schema": SCHEMA,
            "root": self.pipeline,
            "code": code,
            "made_at": self.made_at,
            "records": [self.assets[name] for name in sorted(self.assets)],
        }


@dataclass
class SnapshotReport:
    """What making a snapshot did.

    Attributes:
        snapshot: The snapshot: the one just made, or the one already there
            when nothing had changed.
        made: Whether a new one was written.
        not_built: The assets the pipeline declares and has not built, each
            with its declared path.
    """

    snapshot: Snapshot
    made: bool
    not_built: list[tuple[str, str]] = field(default_factory=list)


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


def _git(directory: Path, *arguments: str) -> str:
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


def uncommitted(directory: Union[str, Path]) -> list[str]:
    """What in a pipeline's folder is not committed, as ``git status`` lists it.

    A changed file, a staged one, and a new file that git does not ignore
    all count. What git ignores does not, which is how built data stays
    out of it. Only the pipeline's own folder is looked at, so other work
    in the same repository does not hold a snapshot up.

    :returns: One line for each, as ``git status --porcelain`` prints it,
        with paths from the top of the repository.
    """
    listing = _git(
        Path(directory).resolve(), "status", "--porcelain", "--untracked-files=all", "--", "."
    )
    return [line for line in listing.splitlines() if line.strip()]


def _folder(store: Store, commit: str, subdirectory: str) -> Path:
    """Where the records of one pipeline at one commit are kept."""
    if not _FULL_COMMIT.match(commit):
        raise ValueError(f"{commit!r} is not a full commit hash.")
    name = subdirectory.strip("/").replace("/", "--") or TOP
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


def all_hashes(store: Store) -> set[str]:
    """Every object any snapshot in a store names: what must not be cleared.

    :raises SnapshotError: If a record cannot be read. Nothing should be
        removed from a store that cannot say what it is keeping.
    """
    kept: set[str] = set()
    directory = store.root / SNAPSHOTS_DIR
    if not directory.is_dir():
        return kept
    for file in directory.glob("*/*/*.json"):
        kept |= read(file).hashes()
    return kept


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
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(snapshot.to_document(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(temporary, final)
    return final


def make(
    project_dir: Union[str, Path] = ".",
    store: Optional[Store] = None,
    made_at: Optional[str] = None,
) -> SnapshotReport:
    """Make a snapshot of a pipeline: what it has built, at the commit it is on.

    Every asset the pipeline declares and has built is put in the store,
    as its own frozen copy, and a record of them is written under the
    commit. An asset that is declared and not built is in the record
    without a hash, and in the report.

    If nothing has changed since the newest snapshot at this commit, no
    new one is made.

    :param project_dir: The pipeline's folder.
    :param store: The store; this user's by default.
    :param made_at: The time to record, for a test; now by default.
    :returns: The snapshot, and whether it is new.
    :raises SnapshotError: If the folder holds no pipeline, is not in git,
        has anything uncommitted, or has built nothing.
    """
    directory = Path(project_dir).resolve()
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
    pipeline = derive_pipeline_id(raw.get("project") or {}, directory)

    try:
        code = code_of(directory)
    except SnapshotError as error:
        raise SnapshotError(f"{pipeline} cannot have a snapshot: {error}.") from None
    changes = uncommitted(directory)
    if changes:
        shown = "\n".join(f"  {line}" for line in changes[:10])
        more = f"\n  and {len(changes) - 10} more" if len(changes) > 10 else ""
        raise SnapshotError(
            f"{pipeline} has changes that are not committed:\n{shown}{more}\n"
            f"A snapshot is labelled with the commit it was built from, so "
            f"everything in the pipeline's folder must be committed first. "
            f"Commit, then run `chartbook snapshot` again."
        )

    store = store if store is not None else default_store()
    assets: dict[str, dict] = {}
    not_built: list[tuple[str, str]] = []
    for local, declared_path, absolute in declared_files(directory):
        ref = local.in_pipeline(pipeline)
        found = hashing.find_files(absolute)
        if found is None or not found.files:
            assets[str(local)] = asset_record(ref, pipeline, declared_path, None, True)
            not_built.append((str(ref), declared_path))
            continue
        stored = store.put(absolute, links=LINKS)
        assets[str(local)] = asset_record(ref, pipeline, declared_path, stored, found.single)

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

    snapshot = Snapshot(pipeline, code.commit, code.subdirectory, made_at or _now(), assets)
    before = find(store, code.commit, code.subdirectory)
    if before and before[0].content() == snapshot.content():
        return SnapshotReport(before[0], False, not_built)
    path = _write(snapshot, store)
    snapshot = Snapshot(
        snapshot.pipeline, snapshot.commit, snapshot.subdirectory, snapshot.made_at, assets, path
    )
    return SnapshotReport(snapshot, True, not_built)
