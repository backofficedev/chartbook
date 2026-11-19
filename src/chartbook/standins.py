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
the one the lockfile names: the dependency is read from it, whole. A
dataframe is met by the same file or by the same rows; a model, and
anything else a lockfile holds, by the same file only.

One is looked for only where the store does not have the snapshot the
lockfile names. Where it has it, that one is the pin, and a file of it the
store lacks is lost, or not synced yet: in a store that is shared, waiting
gives the pinned bytes, and another build of that commit is anyone's.

What a comparison found is remembered, in this process and in this
machine's cache folder, by the pin's rows and the bytes they were compared
with, so that neither a second check nor a read hashes a table again.
Nothing is written in the project or in the store.
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

#: The form of what is remembered of a comparison. It is part of what a
#: comparison is remembered by, with this ChartBook's version, so that what
#: an earlier one found is never taken for what this one would find.
REMEMBERED_AS = "chartbook/rows-met/v2"

#: What this process has compared, by what was compared: a machine with no
#: cache folder to write still hashes a table once a process, not once a read.
_compared: dict = {}


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
    """

    asset: str
    by: str
    record: Optional[dict] = None
    as_of: Optional[str] = None
    newer: int = 0


@dataclass
class Unmet:
    """A pinned asset a snapshot of yours does not meet, and why, in one line.

    Attributes:
        index_column: Whether its table has the column pandas makes of an
            index with no name, which may be the whole difference.
        lost: Whether the snapshot says nothing the pin does not: it names
            the very file the pin does, which the store does not have; or
            the store has the pinned file in part, as a sync leaves it.
        label: Whether the pin is of a version named by a label, which no
            build of this commit gives, and ``chartbook pin --update`` does not
            find in yours.
    """

    asset: str
    why: str
    index_column: bool = False
    lost: bool = False
    label: bool = False


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


def candidates(entry: Mapping, snapshots: list, folder=None) -> list:
    """Your snapshots that may stand in for a dependency's pin: of the pipeline it was pinned from, by its own ID, at the commit it was pinned at, newest first, and none dated after now; and none at all where the store has the snapshot its entry names.

    The same snapshots a read takes for what the lockfile does not hold
    of the dependency (:func:`chartbook.lock.read_from`), by the same
    rule: the snapshot the entry names is the pin, alone, where the store
    has it, and then what the store lacks of it is lost or not synced yet.
    One pinned from its repository (``git``) has none: its bytes are that
    commit's, the same for everyone.

    :param snapshots: The store's snapshots that owners made
        (:func:`chartbook.snapshot.readable_snapshots`).
    :param folder: The folder of a ``path`` dependency, as the manifest
        resolves it: an entry written before 0.3.0 does not say which
        pipeline its pins came from, and the folder does.
    """
    from chartbook import lock

    if not lock.from_a_snapshot(entry) or lock.has_named(entry, snapshots, folder):
        return []
    return lock.read_from(entry, snapshots, folder)


def build_said(taken) -> str:
    """A build of yours as a line names it: its commit, and when it was made, since several builds may share a commit: ``5bb7217, made 2026-11-17 05:38 UTC``."""
    made = str(taken.made_at)
    return f"{taken.commit[:7]}, made {made[:10]} {made[11:16]} UTC"


def find(entry: Mapping, records: Mapping, store, snapshots: list, folder=None) -> Found:
    """The snapshot of yours that stands in for a dependency's pin, or the newest that does not, with why.

    :param entry: The dependency's entry in the lockfile.
    :param records: The lockfile's records of its assets, by ID.
    :param store: The store its pins should be in.
    :param snapshots: The store's snapshots.
    :param folder: The folder of a ``path`` dependency (:func:`candidates`).
    """
    best = None
    for taken in candidates(entry, snapshots, folder):
        found = compare(taken, records, store)
        if found.stands_in:
            return found
        if all(unmet.lost for unmet in found.unmet):
            # The pinned snapshot itself, or one of the same files: the store has lost
            # them, and that is what is said, not that a build of yours differs
            continue
        best = best or found
    return best or Found()


def compare(taken, records: Mapping, store) -> Found:
    """One snapshot of yours against a dependency's pins: how it meets each, or why it does not."""
    from chartbook import lock, snapshot

    found = Found(snapshot=taken)
    for asset_id in sorted(records):
        record = records[asset_id]
        pinned = record.get("content_hash")
        if not pinned:
            continue  # not built when it was pinned: nothing to meet, and the check says so itself
        if not lock.in_lockfile(record) and not store.has(pinned):
            continue  # kept of an earlier lockfile, for a store that had its bytes: no pin here (lock.still_pinned)
        labelled = bool((record.get("ref") or {}).get("rev"))
        theirs = None if labelled else taken.assets.get(snapshot.local_name(record))
        if store.has(pinned):
            # The cheapest check, wherever the bytes came from. In part, they are on their
            # way: waiting gives the pinned file, and no build is read in its place
            in_part = snapshot.not_whole(store, record)
            if in_part:
                found.unmet.append(Unmet(asset_id, f"the store has the pinned file in part: {in_part}", lost=True))
            else:
                found.met[asset_id] = Met(asset_id, "file")
            continue
        kind = (record.get("ref") or {}).get("kind")
        if labelled:
            found.unmet.append(
                Unmet(
                    asset_id,
                    "a version pinned by its label is met by the same file only, and the store does not have it. "
                    "It was made at an earlier commit, most likely: the store of whoever made it has it, or a "
                    "build of that commit that gives the same file",
                    label=True,
                )
            )
        elif theirs is None or not theirs.get("content_hash"):
            what = "has no such asset" if theirs is None else "did not build it"
            found.unmet.append(Unmet(asset_id, f"your build {what}"))
        elif theirs["content_hash"] == pinned:
            # The same file, which the store does not have, or not whole (seen above)
            found.unmet.append(Unmet(asset_id, "it is the pinned file, which the store does not have", lost=True))
        elif not store.has(theirs["content_hash"]) or snapshot.not_whole(store, theirs):
            found.unmet.append(Unmet(asset_id, "the store does not have all of your build's file yet"))
        elif kind != "dataframe":
            found.unmet.append(Unmet(asset_id, f"a {kind} is met by the same file only, and your build's is another"))
        elif isinstance(record.get("not_hashed"), str):
            found.unmet.append(
                Unmet(asset_id, f"only the same file meets it, since its rows are not hashed ({record['not_hashed']}), and your build's file is another")
            )
        elif not isinstance(record.get("rows"), dict):
            found.unmet.append(
                Unmet(
                    asset_id,
                    "only the same file meets it, since the pin records no rows (it was made before rows were "
                    "hashed, or its file is no table ChartBook reads), and your build's file is another",
                )
            )
        elif not record["rows"]:
            # A table with no row has no period, and so nothing its columns are told by
            found.unmet.append(
                Unmet(asset_id, "only the same file meets it, since the pinned table had no rows, and your build's file is another")
            )
        else:
            try:
                compared = rows_compared(record, theirs, taken, store)
            except rowhash.NotHashed as error:
                found.unmet.append(Unmet(asset_id, f"the rows of your build's file cannot be hashed ({error})"))
                continue
            except ValueError as error:
                # A period that is none, a last date that is no date: not what a pin writes
                found.unmet.append(
                    Unmet(asset_id, f"chartbook.lock's record of its rows is not one ChartBook wrote ({error}): restore the lockfile from git")
                )
                continue
            if compared.same:
                found.met[asset_id] = Met(asset_id, "rows", theirs, record.get("as_of"), compared.newer)
            else:
                found.unmet.append(Unmet(asset_id, said(compared, record), compared.index_column))
    return found


def said(compared: "rowhash.Compared", record: Mapping, than: str = "the pin", yours: str = "your build's table") -> str:
    """Where a table's rows are not a pin's, in one line: ``the rows of 2024-01-02 to 2024-12-31 differ``.

    :param than: What the table is beside: the pin, or an earlier record of it.
    :param yours: What the table is called: your build's, or ``it``.
    """
    if compared.undated:
        return f"{yours} has no column {record.get('date_col')!r} that holds dates, which {than}'s rows are dated by"
    periods = [key.replace("/", " to ") for key in compared.differ if key not in (rowhash.NO_DATE, rowhash.ALL)]
    parts = []
    if rowhash.ALL in compared.differ:
        # One hash of all its rows: with no date column, a row more is a difference like any other
        parts.append(f"its rows differ ({than} has no date column, so a row more is a difference like any other)")
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
        parts.append(f"it has {compared.outside:,} row{'' if one else 's'}{through} that {than} did not have")
    if compared.no_date:
        one = compared.no_date == 1
        parts.append(f"it has {compared.no_date:,} row{'' if one else 's'} with no date, and {than} had none")
    return "; ".join(parts) or "its rows differ"


class _NotRead(Exception):
    """Raised when telling a table's rows beside a record would read the table, and the caller asked that nothing be read."""


def reads_here(store) -> bool:
    """Whether a store's files are on this machine's disks, so that reading a table of it fetches nothing: a folder store, or several of them."""
    from chartbook.store import FolderStore

    # What a pin wraps a store in, to hold its writes back, reads as the store itself
    while not isinstance(store, FolderStore) and getattr(store, "_store", None) is not None:
        store = store._store
    entries = getattr(store, "entries", None)
    if entries is not None:
        return all(isinstance(getattr(entry, "store", None), FolderStore) for entry in entries)
    return isinstance(store, FolderStore)


def since(before: Mapping, after: Mapping, taken, store, read: bool = True) -> Optional[str]:
    """What a dataframe's rows are beside an earlier record of them, in a few words; None where they are the same file, or there is nothing to tell them by.

    ``24 new rows, through 2026-11-11; earlier rows unchanged``, or
    ``earlier rows changed: the rows of 2025-09-26 to 2025-12-31 differ; 24
    new rows, through 2026-11-11``. For a pin that moves (``chartbook pin
    --update``), beside the pin it had; and for a snapshot (``chartbook
    snapshot``), beside the snapshot before it. The earlier record's
    periods are what is compared, up to its last date, as a check
    compares them (:func:`rows_compared`): what the two records already
    show to be the same is not read, and two records of a table with no
    date column say it all between them.

    Nothing here is worth stopping a command for: what cannot be told,
    for whatever reason, is left unsaid.

    :param before: The earlier record of the dataframe: a lockfile's, or a snapshot's.
    :param after: Its record now, in the snapshot *taken*, whose file the store has.
    :param read: Whether the table may be read where the two records do
        not say it all. False for a store whose files are not on this
        machine (:func:`reads_here`): a line of output is not worth
        fetching a table for.
    """
    try:
        return _since(before, after, taken, store, read)
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except BaseException:  # noqa: BLE001 - a store that cannot be reached, a record no pin wrote, a panic of polars: nothing is said
        return None


def _since(before: Mapping, after: Mapping, taken, store, read: bool) -> Optional[str]:
    if not before.get("content_hash") or before.get("content_hash") == after.get("content_hash"):
        return None
    was, now = before.get("rows"), after.get("rows")
    if not isinstance(was, dict) or not isinstance(now, dict):
        return None  # one of them says nothing of its rows: pinned before rows were hashed, or not hashed
    rows_then, rows_now = before.get("row_count"), after.get("row_count")
    counted = (
        f" ({rows_then:,} rows before, {rows_now:,} now)"
        if type(rows_then) is int and type(rows_now) is int else ""
    )
    if not was:
        # It had no rows: nothing to compare, and nothing to call earlier
        return f"it had no rows, and has {rows_now:,} now" if type(rows_now) is int and rows_now else None
    if rowhash.ALL in was and rowhash.ALL in now:
        # Neither is dated: one hash each, of all the rows, and the two records say it
        if was == now:
            return "the same rows, in other bytes"
        return f"its rows changed{counted}; it has no date column to tell new rows by"
    if rowhash.ALL in was:
        # It is dated now and was not then: all its rows are compared, and none can be told to be new
        compared = rows_compared(before, after, taken, store, read)
        if compared.same:
            return f"the same rows, in other bytes; now dated by {after.get('date_col')!r}"
        return f"its rows changed{counted}; the earlier record had no date column to tell new rows by"
    # The earlier record is dated: its periods are compared, up to its last date
    compared = rows_compared(before, after, taken, store, read)
    if compared.undated:
        return (
            f"its rows are no longer dated by {before.get('date_col')!r}, so new rows cannot be told from "
            f"changed ones{counted}"
        )
    # The last date said is the later record's, by the same column: else there is none to say
    same_column = after.get("date_col") == before.get("date_col")
    one = compared.newer == 1
    new = f"{compared.newer:,} new row{'' if one else 's'}" + (
        f", through {after['as_of']}" if same_column and after.get("as_of") else ""
    )
    if compared.same:
        return f"{new}; earlier rows unchanged" if compared.newer else "the same rows, in other bytes"
    told = f"earlier rows changed: {said(compared, before, 'the earlier one', 'it')}" + (f"; {new}" if compared.newer else "")
    if compared.index_column:
        told += (
            f". It has the column pandas makes of an index with no name ({rowhash.INDEX_COLUMN}), which may be "
            f"the whole difference"
        )
    return told


def rows_compared(pinned: Mapping, theirs: Mapping, taken, store, read: bool = True) -> "rowhash.Compared":
    """A snapshot's file beside a pin's record of rows: the same rows up to the pin's last date, or where not.

    Cheapest first. What was found before, for this pin's rows and these
    bytes, is taken as it was remembered. Else the two records are compared: a
    period both name by the same timestamps, with the same hash, is the
    same rows, and is not read. Only then are the table's rows read, and
    hashed in the periods still to be told (:func:`chartbook.rowhash.hash_in`).

    :param read: Whether the table may be read. With False, what is
        remembered and what the two records say is all that is used.
    :raises chartbook.rowhash.NotHashed: If the table's rows cannot be hashed.
    :raises _NotRead: If the table would have to be read, and may not be.
    """
    from chartbook.resolve import _held

    date_col, as_of, rows = pinned.get("date_col"), pinned.get("as_of"), pinned["rows"]
    if not isinstance(theirs.get("content_hash"), str) or not all(isinstance(key, str) for key in rows):
        raise ValueError("a period of its rows is not named by text")
    rowhash.periods_of(rows)  # none that is no period, whatever is remembered
    answers = _answers(pinned, theirs)
    if answers in _compared:
        return _compared[answers]
    remembered = _remembered(answers)
    cached = _read(remembered, answers)
    if cached is not None:
        _compared[answers] = cached
        return cached
    known = _told_by_the_records(pinned, theirs)
    if known is None:
        # Every period of the pin is in your record as it is, and nothing else up to its last date
        newer = max(0, int(theirs.get("row_count") or 0) - int(pinned.get("row_count") or 0))
        compared = rowhash.Compared([], 0, newer, int(theirs.get("row_count") or 0))
    elif not read:
        raise _NotRead()
    else:
        table = rowhash.Table.at(_held(store, dict(theirs), taken.pipeline))
        compared = rowhash.hash_in(table, date_col, rows, as_of, known=known)
    _compared[answers] = compared
    _write(remembered, answers, compared)
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


def _answers(pinned: Mapping, theirs: Mapping) -> str:
    """What a comparison answers, as one hash: this pin's rows, its date column and last date, beside these bytes, as this ChartBook compares them."""
    from chartbook import __version__

    asked = json.dumps(
        [
            REMEMBERED_AS, __version__, rowhash.FORM.decode("ascii"), pinned.get("date_col"), pinned.get("as_of"),
            sorted(pinned["rows"].items()), theirs["content_hash"], theirs.get("location"),
        ],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(asked.encode("utf-8")).hexdigest()


def _remembered(answers: str) -> Optional[Path]:
    """Where what a comparison found is remembered: a small file in this machine's cache folder; None with no cache folder to name."""
    try:
        from chartbook.config import get_cache_path

        return Path(get_cache_path()) / "rows" / "met" / f"{answers}.json"
    except Exception:  # noqa: BLE001 - no cache to write to: remembered for this process only
        return None


def _read(path: Optional[Path], answers: str) -> Optional["rowhash.Compared"]:
    """What a file remembers, if it is whole and is what :func:`_write` writes for this very question; else None, and the table is compared again."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(found, dict) or found.get("answers") != answers:
        return None
    differ = found.get("differ")
    counts = [found.get(name) for name in ("outside", "newer", "rows", "no_date")]
    flags = [found.get(name) for name in ("index_column", "undated")]
    if not isinstance(differ, list) or not all(isinstance(key, str) for key in differ):
        return None
    if not all(type(count) is int and count >= 0 for count in counts) or not all(type(flag) is bool for flag in flags):
        return None
    return rowhash.Compared(differ, *counts[:3], *flags, no_date=counts[3])


def _write(path: Optional[Path], answers: str, compared: "rowhash.Compared") -> None:
    """Remember what was found, whole or not at all, with what it answers; a cache that cannot be written is no failure."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as f:
            json.dump(
                {
                    "answers": answers, "differ": list(compared.differ), "outside": int(compared.outside),
                    "newer": int(compared.newer), "rows": int(compared.rows), "no_date": int(compared.no_date),
                    "index_column": bool(compared.index_column), "undated": bool(compared.undated),
                },
                f,
            )
        os.replace(temporary, path)
    except OSError:
        return
