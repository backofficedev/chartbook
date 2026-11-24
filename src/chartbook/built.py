"""What a run built, kept so that a snapshot can be held against it.

``docs_src/design/one-command.md``, "A snapshot is of what a run built".
``chartbook run`` builds, and ``chartbook snapshot`` is typed afterwards,
once the work is committed. A snapshot is labelled with the commit and
holds the files on disk, and nothing tied the two: build, fix the code,
commit, snapshot, and the old files are labelled with the fix.

So a build that succeeds leaves a note, and a snapshot is held against it.
The note has two halves, which stop two different slips:

- *What the build ran on:* a plain hash of each source file of the
  pipeline's folder, and of ``chartbook.lock``, as they were when the run
  had pinned and its script was about to start.
- *What the build left:* the size and the time of last change of every
  file the manifest declares as built, when the build had ended and each
  was found.

**Where it is kept.** With ChartBook's own things, under the cache
(``~/.chartbook/cache/built/``, moved by ``CHARTBOOK_CACHE``): one small
file for each pipeline folder, named from the folder's path. Not in the
project, and not in ``.git``: the note holds plain hashes and no git ids,
nothing has to be ignored by any version control system, and git is asked
one thing here, which files of a folder are its source
(:func:`source_files`).

**Its two states.** When a build's script is started the note before it
is replaced by one that says a build began; when the build has ended well
that one is replaced by the finished note, if it is still this run's. So
a build that fails, is stopped, or is overtaken by another leaves "a build
began", and a snapshot says so.

Nothing here makes a snapshot, and nothing here reads a store.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

SCHEMA = "chartbook/built/v1"

#: The folder of the notes, in the cache.
FOLDER = "built"

#: The flag that takes the files as they are, as a message names it.
AS_IS = "--as-is"

#: How many files a refusal names before it says how many more there are.
MOST_NAMED = 10


class NotHeld(Exception):
    """A pipeline's files cannot be held against a build: why, and what differs.

    Attributes:
        why: ``none`` (no run built it here), ``another`` (the note is of
            another pipeline or another machine), ``began`` (the last
            build did not end well, or is running), ``differ`` (the files
            are not the build's), ``not_committed`` (it has no ``build``
            script, and declares files that are not committed),
            ``unreadable`` (what the manifest says of its scripts cannot
            be read, so whether anything builds it cannot be told).
        source: The source files that differ from what it was built
            from, each as it is said (``load.py``, ``notes.md (new)``).
        outputs: The built files that differ from what the build left.
        detail: For ``began``, when the build began; for ``another``,
            whose note it is; for ``unreadable``, what is wrong.
    """

    def __init__(self, why: str, source: tuple = (), outputs: tuple = (), detail: str = ""):
        super().__init__(why)
        self.why = why
        self.source = tuple(source)
        self.outputs = tuple(outputs)
        self.detail = detail


@dataclass
class Building:
    """A build that has begun: what it runs on, and the note that says it began.

    Attributes:
        directory: The pipeline's folder.
        pipeline: Its ID.
        token: What makes the note this run's.
        began_at: When its script was started, in UTC.
        hashed_at: The same moment in whole seconds since the epoch: a
            source file changed in that second or later is hashed again
            when a snapshot is made, whatever its size and time say.
        source: Each source file as it is now, by its path in the folder:
            its hash, size and time of last change.
        kept: Whether the note could be written. A cache that cannot be
            written keeps none, and the build runs all the same.
        before: The note that was there before this build began, to put
            back where its script is never started.
    """

    directory: Path
    pipeline: str
    token: str
    began_at: str
    hashed_at: int
    source: dict = field(default_factory=dict)
    kept: bool = True
    before: Optional[dict] = None


def folder() -> Path:
    """Where the notes are kept."""
    from chartbook.config import get_cache_path

    return Path(get_cache_path()) / FOLDER


def note_path(directory: Union[str, Path]) -> Path:
    """The note of a pipeline's folder: named from the folder's path, as it is followed to."""
    whole = os.path.realpath(os.fspath(directory))
    return folder() / (hashlib.sha256(whole.encode("utf-8", "surrogateescape")).hexdigest()[:32] + ".json")


def pipeline_of(directory: Union[str, Path], otherwise: str = "") -> str:
    """The ID of the pipeline in a folder, as a snapshot of it would name it: what a note is of, asked the same way by the run that writes it and the snapshot that reads it."""
    from chartbook import snapshot

    try:
        return snapshot.pipeline_in(directory)
    except (snapshot.SnapshotError, OSError, ValueError):
        return otherwise


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _machine() -> str:
    from chartbook.config import get_machine_id

    try:
        return get_machine_id()
    except (OSError, RuntimeError, KeyError):
        return ""


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _within(directory: Path, path: Path) -> str:
    """A file by its path in the pipeline's folder, with ``/``; one outside it by its path from there."""
    try:
        return os.path.relpath(path, directory).replace(os.sep, "/")
    except ValueError:
        return os.fspath(path).replace(os.sep, "/")


def built_files(directory: Union[str, Path]) -> dict:
    """Every file a pipeline's build is to write and has written, by its path in the folder.

    The files of what the manifest declares as built
    (:func:`chartbook.run.what_a_build_writes`): a dataframe, a chart, a
    notebook, a model and its scores, a files asset, the file of a DuckDB
    source. Not a note, which is prose that no build writes.

    :raises OSError: If there is no ``chartbook.toml`` there to read.
    :raises ValueError: If it is not valid TOML.
    """
    from chartbook.run import what_a_build_writes

    directory = Path(os.path.abspath(directory))
    found: dict = {}
    for _, _, files in what_a_build_writes(directory):
        for file in files:
            found[_within(directory, Path(file))] = Path(file)
    return found


def _listed_by_git(directory: Path, *how: str) -> Optional[list]:
    from chartbook import snapshot

    try:
        listed = snapshot._git(directory, "ls-files", "-z", *how, "--", ".")
    except snapshot.SnapshotError:
        return None
    return [name for name in listed.split("\0") if name]


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def source_files(directory: Union[str, Path], built: Optional[dict] = None) -> Optional[dict]:
    """The source files of a pipeline's folder that are on disk, by their paths in it; None where that cannot be asked.

    The one thing git is asked here: a source file is one git tracks, or
    would add (new, and not ignored). What the manifest declares as built
    is not one, whether or not git tracks it. ``chartbook.lock`` is one
    wherever it is there, also in a project that keeps it out of git: it
    says what the build read.

    :param built: The built files (:func:`built_files`), where they are
        at hand.
    """
    from chartbook.lock import LOCK_FILE

    directory = Path(os.path.abspath(directory))
    listed = _listed_by_git(directory, "--cached", "--others", "--exclude-standard")
    if listed is None:
        return None
    if built is None:
        try:
            built = built_files(directory)
        except (OSError, ValueError):
            built = {}
    built_by_case = {k.casefold(): v for k, v in built.items()}
    found = {}
    for name in dict.fromkeys([*listed, LOCK_FILE]):
        path = directory / name
        if (
            name in built
            or (name.casefold() in built_by_case and _same_file(path, built_by_case[name.casefold()]))
            or not path.is_file()
        ):
            continue  # built, or not there: a file that was removed and not committed, a folder of another repository
        found[name] = path
    return found


def _tracked(directory: Path) -> set:
    return set(_listed_by_git(directory, "--cached") or ())


def _as_it_is(path: Path, before: Optional[dict] = None, since: Optional[int] = None) -> dict:
    """A source file's hash, size and time of last change; its hash taken from *before* where neither size nor time has changed since.

    Git's own rule for its index, with git's own exception: a file whose
    time of last change is not earlier than the moment it was hashed
    (*since*, in whole seconds) is hashed again, since a change made in
    that second keeps its time, and may keep its size.
    """
    stat = path.stat()
    same = (
        before is not None and before.get("size") == stat.st_size and before.get("time") == stat.st_mtime_ns
        and isinstance(before.get("hash"), str)
        and since is not None and stat.st_mtime_ns // 1_000_000_000 < since
    )
    return {"hash": before["hash"] if same else _hash(path), "size": stat.st_size, "time": stat.st_mtime_ns}


def _read(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as file:
            note = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(note, dict) or note.get("schema") != SCHEMA:
        return None
    # One that does not say whose it is, or in which state, is no note: a file somebody cut short
    said = all(isinstance(note.get(key), str) and note[key] for key in ("state", "token", "folder", "pipeline"))
    return note if said and isinstance(note.get("machine"), str) else None


def _write(path: Path, note: dict) -> None:
    from chartbook.replacing import replace_when_let

    path.parent.mkdir(parents=True, exist_ok=True)
    beside = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(beside, "w", encoding="utf-8", newline="\n") as file:
            json.dump(note, file, indent=1, sort_keys=True)
        replace_when_let(beside, path)
    finally:
        try:
            os.unlink(beside)
        except OSError:
            pass
    _forget_what_is_gone(path, note.get("folder"))


def _forget_what_is_gone(but: Path, folder: Optional[str]) -> None:
    """Remove the notes that have no use any more: of a folder of this machine's that is gone, and of this very folder under another name.

    A folder is gone where the folder it was in is there and it is not:
    one on a drive that is unplugged, or a share that is not connected, is
    only away, and its note is kept. A note another machine left is that
    machine's to forget (one home may serve several). And where one folder
    was built under two spellings (``demo`` and ``DEMO``, on a disk that
    takes either), the note of the other spelling is an older build of
    this folder, which a snapshot must not be held against.
    """
    try:
        others = [entry for entry in os.scandir(but.parent) if entry.name.endswith(".json") and entry.name != but.name]
    except OSError:
        return
    machine = _machine()
    for entry in others:
        note = _read(Path(entry.path))
        if note is None:
            continue
        try:
            same = folder is not None and os.path.samefile(note["folder"], folder)
        except OSError:
            same = False
        gone = (
            note["machine"] == machine and not os.path.lexists(note["folder"])
            and os.path.isdir(os.path.dirname(note["folder"]) or os.sep)
        )
        if same or gone:
            try:
                os.unlink(entry.path)
            except OSError:
                pass


def read(directory: Union[str, Path]) -> Optional[dict]:
    """The note of a pipeline's folder, or None: under the folder's own name, or of the same folder reached by another."""
    note = _read(note_path(directory))
    if note is not None:
        return note
    try:
        others = [entry.path for entry in os.scandir(folder()) if entry.name.endswith(".json")]
    except OSError:
        return None
    for other in others:
        note = _read(Path(other))
        try:
            if note is not None and isinstance(note.get("folder"), str) and os.path.samefile(note["folder"], directory):
                return note
        except OSError:
            continue
    return None


def began(directory: Union[str, Path], pipeline: str) -> Optional[Building]:
    """Note that a pipeline's build begins: hash what it runs on, and replace the note before it with one that says so.

    Called when the run has pinned and the script is about to start, so
    that a run that stops before its script leaves the note as it was.

    :returns: The build, to hand to :func:`finished`; None where the
        folder's source cannot be asked (it is in no git repository, so it
        can have no snapshot either).
    """
    directory = Path(os.path.abspath(directory))
    earlier = read(directory) or {}
    same_machine = earlier.get("machine") == _machine()
    was = earlier.get("source") if same_machine and isinstance(earlier.get("source"), dict) else {}
    hashed_before = earlier.get("hashed_at") if same_machine and isinstance(earlier.get("hashed_at"), int) else None
    moment = _now()
    source = source_files(directory)
    if source is None:
        return None
    building = Building(
        directory, pipeline, uuid.uuid4().hex, moment.strftime("%Y-%m-%dT%H:%M:%SZ"), int(moment.timestamp()),
        before=earlier or None,
    )
    for name, path in sorted(source.items()):
        try:
            building.source[name] = _as_it_is(path, was.get(name) if isinstance(was.get(name), dict) else None, hashed_before)
        except OSError:
            continue  # gone since it was listed: not what the build runs on
    try:
        _write(note_path(directory), _note(building, "building"))
    except OSError:
        building.kept = False
    return building


def never_started(building: Building) -> None:
    """Put the note back as it was before a build that began and whose script was never started: a run that is refused as it starts its script has built nothing.

    Only where the note is still this run's "a build began".
    """
    if not building.kept:
        return
    path = note_path(building.directory)
    on_disk = _read(path) or {}
    if on_disk.get("state") != "building" or on_disk.get("token") != building.token:
        return
    try:
        if building.before is not None:
            _write(path, building.before)
        else:
            os.unlink(path)
    except OSError:
        pass


def _note(building: Building, state: str, **more) -> dict:
    return {
        "schema": SCHEMA, "state": state, "token": building.token, "folder": str(building.directory),
        "pipeline": building.pipeline, "machine": _machine(), "began_at": building.began_at,
        "hashed_at": building.hashed_at, "source": building.source, **more,
    }


def finished(building: Building) -> dict:
    """Note what a build left, now that it has ended and every declared file was found; the finished note.

    Written only where the note on disk is still this run's "a build
    began": one that another run has replaced since is that run's.

    :returns: The finished note, kept or not: a run that is to make a
        snapshot itself holds it against this one.
    """
    directory = building.directory
    tracked = _tracked(directory)
    tracked_by_case = {t.casefold(): directory / t for t in tracked}
    outputs = {}
    for name, path in sorted(built_files(directory).items()):
        try:
            stat = path.stat()
            outputs[name] = {"size": stat.st_size, "time": int(stat.st_mtime)}
            if name in tracked or (name.casefold() in tracked_by_case and _same_file(path, tracked_by_case[name.casefold()])):
                # Git writes such a file again, with the same bytes, at a stash, a rebase, a checkout of
                # another branch and back: a time that differs is settled by its hash
                outputs[name]["hash"] = _hash(path)
        except OSError:
            continue
    note = _note(building, "built", built_at=_now().strftime("%Y-%m-%dT%H:%M:%SZ"), outputs=outputs)
    if building.kept:
        path = note_path(directory)
        on_disk = _read(path) or {}
        if on_disk.get("state") == "building" and on_disk.get("token") == building.token:
            try:
                _write(path, note)
            except OSError:
                building.kept = False
        else:
            building.kept = False
    return note


def _differences(directory: Path, note: dict) -> tuple[list, list]:
    """What differs from a finished note: the source files, and the built files, each as it is said."""
    built = built_files(directory)
    source = source_files(directory, built)
    if source is None:
        raise NotHeld("unreadable", detail="git could not list the folder's source files")
    was = note.get("source") if isinstance(note.get("source"), dict) else {}
    since = note.get("hashed_at") if isinstance(note.get("hashed_at"), int) else None
    of_source = []
    for name in sorted(source):
        before = was.get(name)
        if not isinstance(before, dict):
            of_source.append(f"{name} (new)")
            continue
        try:
            if _as_it_is(source[name], before, since)["hash"] != before.get("hash"):
                of_source.append(name)
        except OSError:
            of_source.append(f"{name} (gone)")
    for name in sorted(was):
        # Only what is gone from disk: one that is ignored now, or declared as built now, is not source now
        if name not in source and not (directory / name).is_file():
            of_source.append(f"{name} (gone)")
    left = note.get("outputs") if isinstance(note.get("outputs"), dict) else {}
    of_outputs = []
    for name in sorted(built):
        before = left.get(name)
        if not isinstance(before, dict):
            of_outputs.append(f"{name} (new)")
            continue
        try:
            stat = built[name].stat()
            # A file git tracks has its hash in the note. That hash is what says it is the
            # build's: a checkout writes it again at another time with the same bytes, and a
            # rewrite in the same second keeps the time and may keep the size. One git does
            # not track has its size and its time, and no more.
            if isinstance(before.get("hash"), str):
                same = before.get("size") == stat.st_size and _hash(built[name]) == before["hash"]
            else:
                same = before.get("size") == stat.st_size and before.get("time") == int(stat.st_mtime)
        except OSError:
            same = False
        if not same:
            of_outputs.append(name)
    of_outputs += [f"{name} (gone)" for name in sorted(left) if name not in built]
    return of_source, of_outputs


def held(directory: Union[str, Path], note: dict) -> None:
    """Hold a pipeline's folder against a finished note, as a run does with the one it has just written.

    :raises NotHeld: Where the source or the built files differ from it.
    """
    of_source, of_outputs = _differences(Path(os.path.abspath(directory)), note)
    if of_source or of_outputs:
        raise NotHeld("differ", of_source, of_outputs)


def check(directory: Union[str, Path], pipeline: str) -> bool:
    """Hold a pipeline's folder against what a run built, before a snapshot of it is made.

    :param pipeline: The pipeline's ID, as its manifest gives it.
    :returns: True where it is what the last build here ran on and left,
        so that its snapshot may say ChartBook ran the build. False for a
        pipeline with no ``build`` script, which is not asked: it commits
        what it declares, and its commit is the whole of it.
    :raises NotHeld: Otherwise, with why.
    :raises OSError: If there is no ``chartbook.toml`` there to read.
    :raises ValueError: If it is not valid TOML.
    """
    from chartbook.manifest import BUILD_SCRIPT, read_scripts
    from chartbook.run import _read_manifest

    directory = Path(os.path.abspath(directory))
    try:
        scripts = read_scripts(_read_manifest(directory))
    except ValueError as error:
        # Whether anything builds it cannot be told: not a reason to take its files unasked
        raise NotHeld("unreadable", detail=(str(error).strip().splitlines() or [""])[0].rstrip(".")) from None
    if BUILD_SCRIPT not in scripts:
        tracked = _tracked(directory)
        tracked_by_case = {t.casefold(): directory / t for t in tracked}
        # A file outside the pipeline's folder is not asked of here: the snapshot says of it what is to be said
        loose = sorted(
            name for name, path in built_files(directory).items()
            if name not in tracked
            and not (name.casefold() in tracked_by_case and _same_file(path, tracked_by_case[name.casefold()]))
            and not name.startswith("../")
            and not os.path.isabs(name)
        )
        if loose:
            raise NotHeld("not_committed", outputs=loose)
        return False
    note = read(directory)
    if note is None:
        raise NotHeld("none")
    if note.get("pipeline") != pipeline:
        raise NotHeld("another", detail=f"of {note.get('pipeline')}")
    if note.get("machine") != _machine():
        raise NotHeld("another", detail="left by another machine")
    if note.get("state") != "built":
        raise NotHeld("began", detail=str(note.get("began_at") or ""))
    held(directory, note)
    return True


def would_hold(directory: Union[str, Path], pipeline: str) -> bool:
    """Whether a snapshot of a pipeline's folder would be made without ``--as-is``: for a list that is to say what to type."""
    try:
        check(directory, pipeline)
    except (NotHeld, OSError, ValueError):
        return False
    return True


def note_manifest_written(directory: Union[str, Path], before_text: str) -> None:
    """Keep a finished build note valid when ChartBook itself rewrites ``requires_chartbook`` in ``chartbook.toml``."""
    from chartbook.resolve import MANIFEST_NAME

    directory = Path(os.path.abspath(directory))
    path = note_path(directory)
    note = _read(path)
    if note is None or note.get("state") != "built" or note.get("machine") != _machine():
        return
    source = note.get("source")
    if not isinstance(source, dict) or not isinstance(source.get(MANIFEST_NAME), dict):
        return
    before_hash = hashlib.sha256(before_text.encode("utf-8")).hexdigest()
    if source[MANIFEST_NAME].get("hash") != before_hash:
        return
    try:
        manifest_path = directory / MANIFEST_NAME
        stat = manifest_path.stat()
        source[MANIFEST_NAME] = {"hash": _hash(manifest_path), "size": stat.st_size, "time": stat.st_mtime_ns}
        _write(path, note)
    except OSError:
        pass


def _named(files: tuple) -> str:
    shown = ", ".join(files[:MOST_NAMED])
    return shown + (f", and {len(files) - MOST_NAMED} more" if len(files) > MOST_NAMED else "")


def _when(text: str) -> str:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return text


def said(refusal: NotHeld, pipeline: str, here: str = "", with_options: str = "") -> list[str]:
    """A refusal as a command prints it: what is wrong, and the two ways on.

    :param here: `` --project-dir FOLDER`` for a pipeline that is not in
        the folder the command was typed in, quoted for the shell; else
        empty.
    :param with_options: The other options that were typed, to be typed
        again with ``--as-is`` (`` --store mine``).
    """
    as_is = f"to take what is on disk as it is: `chartbook snapshot {AS_IS}{with_options}{here}`."
    again = f"Build again: `chartbook run{here}`"
    if refusal.why == "unreadable":
        return [
            f"{pipeline}: whether a run built its files cannot be told: {refusal.detail}.",
            f"  Put that right, and `chartbook run{here}`. Or, {as_is}",
        ]
    if refusal.why == "not_committed":
        return [
            f"{pipeline} has no `build` script, and declares files that are not committed: {_named(refusal.outputs)}.",
            f"  Commit them. Or, {as_is}",
        ]
    if refusal.why == "none":
        return [
            f"{pipeline} has not been built by `chartbook run` here, so there is nothing to hold its files against.",
            f"  Build it: `chartbook run{here}` (a build with nothing left to do takes a moment). Or, {as_is}",
        ]
    if refusal.why == "another":
        return [
            f"{pipeline} has not been built by `chartbook run` here: the note of a build of this folder is {refusal.detail}.",
            f"  Build it: `chartbook run{here}` (a build with nothing left to do takes a moment). Or, {as_is}",
        ]
    if refusal.why == "began":
        began_at = f" (it began {_when(refusal.detail)})" if refusal.detail else ""
        return [
            f"{pipeline}: its last build here failed, was stopped, or is still running{began_at}.",
            f"  {again}. Or, {as_is}",
        ]
    lines = []
    if refusal.source:
        lines.append(f"{pipeline}: these differ from what it was built from: {_named(refusal.source)}.")
    if refusal.outputs:
        lines.append(
            f"  And these differ from what its build left: {_named(refusal.outputs)}." if lines
            else f"{pipeline}: these differ from what its build left: {_named(refusal.outputs)}."
        )
    return [*lines, f"  {again}, which rebuilds what your build finds out of date. Or, {as_is}"]
