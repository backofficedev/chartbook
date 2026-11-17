"""Stand-ins: a snapshot of yours that meets a pin by its rows.

A pin names the bytes of a file, and where a store is shared those bytes
are in it. Where none is, each person builds the other pipeline at the
commit the lockfile names, and their own snapshot of that commit holds the
pinned rows in other bytes, and newer rows besides. So a pin is checked
cheapest first (``docs_src/design/pins-and-rebuilds.md``, "The check,
cheapest first"):

1. **The same file?** The store has the pinned bytes. Nothing is read.
2. **The same rows, up to the pin's last date?** Among your snapshots of
   the same pipeline at the same commit, the rows of each period the pin
   names are hashed and compared (:mod:`chartbook.rowhash`). Rows after
   the pin's last date are left out.
3. **Otherwise it differs,** and what says so names the periods that do.

A snapshot of yours that meets every pin of a dependency **stands in** for
the one the lockfile names: the dependency is read from it. A dataframe is
met by the same file or by the same rows; a model, and anything else a
lockfile holds, by the same file only.

What a comparison found is remembered in this machine's cache folder, by
the pin's rows and the bytes they were compared with, so that neither a
second check nor a read hashes a table again. Nothing is written in the
project or in the store.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from chartbook import rowhash


@dataclass
class Met:
    """How a pinned asset is met by a snapshot that stands in.

    Attributes:
        asset: The asset's ID, as the lockfile has it.
        by: ``"file"``, the same bytes; or ``"rows"``, the same rows up to
            the pin's last date.
        record: The stand-in's own record of the asset, which is what is
            read; None when the pinned bytes themselves are in the store.
        as_of: The pin's last date, for one met by its rows.
        newer: How many rows the stand-in has after it.
        held: Whether the snapshot itself holds what meets the pin: the
            same bytes, or the same rows. False when the pinned bytes are
            in the store from somewhere else.
    """

    asset: str
    by: str
    record: Optional[dict] = None
    as_of: Optional[str] = None
    newer: int = 0
    held: bool = True


@dataclass
class Unmet:
    """A pinned asset a snapshot of yours does not meet, and why, in one line."""

    asset: str
    why: str
    index_column: bool = False


@dataclass
class Found:
    """What the store has of yours for a dependency whose pinned bytes it does not all have.

    Attributes:
        snapshot: The snapshot of yours that was compared: the one that
            stands in, or else the newest of that commit. None when the
            store has no snapshot of that pipeline at that commit.
        met: How each pinned asset is met by it, by the asset's ID.
        unmet: The pinned assets it does not meet.
    """

    snapshot: object = None
    met: dict = field(default_factory=dict)
    unmet: list = field(default_factory=list)

    @property
    def stands_in(self) -> bool:
        """Whether the snapshot meets every pin of the dependency."""
        return self.snapshot is not None and not self.unmet


def candidates(entry: Mapping, snapshots: list) -> list:
    """Your snapshots that may stand in for a dependency's pin: of the pipeline it was pinned from, at the commit it was pinned at, newest first.

    A dependency pinned from its repository (``git``) has none: its bytes
    are that commit's, the same for everyone.
    """
    from chartbook import snapshot

    location = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    commit = location.get("commit")
    if location.get("kind") not in ("store", "path") or not isinstance(commit, str) or not commit:
        return []
    pipeline = entry.get("pinned_from") or location.get("pipeline")
    found = [
        taken for taken in snapshots
        if taken.commit == commit and (not isinstance(pipeline, str) or taken.pipeline == pipeline)
    ]
    return sorted(found, key=lambda taken: (taken.made_at, snapshot._count(taken.path)), reverse=True)


def find(entry: Mapping, records: Mapping, store, snapshots: list) -> Found:
    """The snapshot of yours that stands in for a dependency's pin, or the newest that does not, with why.

    :param entry: The dependency's entry in the lockfile.
    :param records: The lockfile's records of its assets, by ID.
    :param store: The store its pins should be in.
    :param snapshots: The store's snapshots.
    """
    best = None
    for taken in candidates(entry, snapshots):
        found = compare(taken, records, store)
        if found.stands_in:
            return found
        best = best or found
    return best or Found()


def compare(taken, records: Mapping, store) -> Found:
    """One snapshot of yours against a dependency's pins: how it meets each, or why it does not."""
    from chartbook import snapshot

    found = Found(snapshot=taken)
    for asset_id in sorted(records):
        record = records[asset_id]
        pinned = record.get("content_hash")
        if not pinned:
            continue  # not built when it was pinned: nothing to meet, and the check says so itself
        labelled = bool((record.get("ref") or {}).get("rev"))
        theirs = None if labelled else taken.assets.get(snapshot.local_name(record))
        if store.has(pinned) and not snapshot.not_whole(store, record):
            found.met[asset_id] = Met(asset_id, "file", held=bool(theirs) and theirs.get("content_hash") == pinned)
            continue
        kind = (record.get("ref") or {}).get("kind")
        if labelled:
            found.unmet.append(Unmet(asset_id, "a version pinned by its label is met by the same file only, and the store does not have it"))
        elif theirs is None or not theirs.get("content_hash"):
            what = "has no such asset" if theirs is None else "did not build it"
            found.unmet.append(Unmet(asset_id, f"your build {what}"))
        elif not store.has(theirs["content_hash"]) or snapshot.not_whole(store, theirs):
            found.unmet.append(Unmet(asset_id, "the store does not have all of your build's file yet"))
        elif theirs["content_hash"] == pinned:
            found.met[asset_id] = Met(asset_id, "file", theirs)
        elif kind != "dataframe":
            found.unmet.append(Unmet(asset_id, f"a {kind} is met by the same file only, and your build's is another"))
        elif isinstance(record.get("not_hashed"), str):
            found.unmet.append(
                Unmet(asset_id, f"only the same file meets it, since its rows are not hashed ({record['not_hashed']}), and your build's file is another")
            )
        elif not isinstance(record.get("rows"), dict):
            found.unmet.append(
                Unmet(asset_id, "only the same file meets it, since the pin records no rows (it was made before rows were hashed), and your build's file is another")
            )
        else:
            try:
                compared = rows_compared(record, theirs, taken, store)
            except rowhash.NotHashed as error:
                found.unmet.append(Unmet(asset_id, f"the rows of your build's file cannot be hashed ({error})"))
                continue
            if compared.same:
                found.met[asset_id] = Met(asset_id, "rows", theirs, record.get("as_of"), compared.newer)
            else:
                found.unmet.append(Unmet(asset_id, said(compared, record), compared.index_column))
    return found


def said(compared: "rowhash.Compared", record: Mapping) -> str:
    """Where a table's rows are not a pin's, in one line: ``the rows of 2024-01-02 to 2024-12-31 differ``."""
    periods = [key.replace("/", " to ") for key in compared.differ if key not in (rowhash.NO_DATE, rowhash.ALL)]
    parts = []
    if rowhash.ALL in compared.differ:
        parts.append("its rows differ")
    if periods:
        shown = periods[:3]
        more = len(periods) - len(shown)
        listed = ", ".join(shown[:-1]) + (" and " if len(shown) > 1 else "") + shown[-1]
        parts.append(f"the rows of {listed}{f', and of {more} more periods' if more else ''} differ")
    if rowhash.NO_DATE in compared.differ:
        parts.append("the rows with no date differ")
    if compared.outside:
        one = compared.outside == 1
        through = f" up to {record['as_of']}" if record.get("as_of") else ""
        parts.append(f"it has {compared.outside:,} row{'' if one else 's'}{through} that the pin did not have")
    return "; ".join(parts) or "its rows differ"


def rows_compared(pinned: Mapping, theirs: Mapping, taken, store) -> "rowhash.Compared":
    """A snapshot's file beside a pin's record of rows: the same rows up to the pin's last date, or where not.

    Cheapest first. What was found before, for this pin's rows and these
    bytes, is taken from the cache. Else the two records are compared: a
    period both name by the same timestamps, with the same hash, is the
    same rows, and is not read. Only then are the table's rows read, and
    hashed in the periods still to be told (:func:`chartbook.rowhash.hash_in`).

    :raises chartbook.rowhash.NotHashed: If the table's rows cannot be hashed.
    """
    from chartbook.resolve import _held

    date_col, as_of, rows = pinned.get("date_col"), pinned.get("as_of"), pinned["rows"]
    remembered = _remembered(pinned, theirs)
    cached = _read(remembered)
    if cached is not None:
        return cached
    known = _told_by_the_records(pinned, theirs)
    if known is None:
        # Every period of the pin is in your record as it is, and nothing else up to its last date
        newer = max(0, int(theirs.get("row_count") or 0) - int(pinned.get("row_count") or 0))
        compared = rowhash.Compared([], 0, newer, int(theirs.get("row_count") or 0))
    else:
        table = rowhash.Table.at(_held(store, dict(theirs), taken.pipeline))
        compared = rowhash.hash_in(table, date_col, rows, as_of, known=known)
    _write(remembered, compared)
    return compared


def _told_by_the_records(pinned: Mapping, theirs: Mapping) -> Optional[list]:
    """The periods of a pin that a snapshot's own record already shows to be the same rows; None when that is all of them and nothing else is left to tell.

    A period is the same when both records name it by the same first and
    last timestamp and give it the same hash. Nothing else is left to tell
    when every period of the pin is such a one and the snapshot's record
    names no other period that begins at or before the pin's last date:
    what it has besides is newer rows.
    """
    rows, own = pinned["rows"], theirs.get("rows")
    if not isinstance(own, dict) or theirs.get("date_col") != pinned.get("date_col"):
        return []
    known = [key for key, hashed in rows.items() if own.get(key) == hashed]
    if len(known) < len(rows):
        return known
    if rowhash.ALL in rows:
        return None
    try:
        cap = rowhash.stamp_of(pinned["as_of"]) if pinned.get("as_of") else None
        for key, first, _ in rowhash.periods_of(own):
            if key not in rows and (cap is None or first <= cap):
                return known
    except ValueError:
        return known
    if rowhash.NO_DATE in own and rowhash.NO_DATE not in rows:
        return known
    return None


def _remembered(pinned: Mapping, theirs: Mapping) -> Optional[Path]:
    """Where what was found of a pin's rows beside a file's bytes is remembered: a small file in this machine's cache folder."""
    try:
        from chartbook.config import get_cache_path

        said = json.dumps(
            [
                rowhash.FORM.decode("ascii"), pinned.get("date_col"), pinned.get("as_of"),
                sorted(pinned["rows"].items()), theirs["content_hash"], theirs.get("location"),
            ],
            sort_keys=True, default=str,
        )
        return Path(get_cache_path()) / "rows" / "met" / f"{hashlib.sha256(said.encode('utf-8')).hexdigest()}.json"
    except Exception:  # noqa: BLE001 - no cache to write to: found again each time
        return None


def _read(path: Optional[Path]) -> Optional["rowhash.Compared"]:
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
        return rowhash.Compared(
            [str(key) for key in found["differ"]], int(found["outside"]), int(found["newer"]), int(found["rows"]),
            bool(found.get("index_column", False)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(path: Optional[Path], compared: "rowhash.Compared") -> None:
    """Remember what was found, whole or not at all; a cache that cannot be written is no failure."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                {
                    "differ": compared.differ, "outside": compared.outside, "newer": compared.newer,
                    "rows": compared.rows, "index_column": compared.index_column,
                },
                f,
            )
        os.replace(temporary, path)
    except OSError:
        return
