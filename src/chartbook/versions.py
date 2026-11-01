"""Versions of a catalog's pipelines: each snapshot in the store rendered as its own site.

A catalog shows every version of every pipeline it lists
(``docs_src/design/versioned-catalog.md``): the **working version**, the
pipeline's folder as it is, which is what the catalog's own pages show;
and every **snapshot** of it in the store, each a version its owner
declared ready. A snapshot holds what its site needs
(:func:`chartbook.snapshot.materialize`), so each is laid out from the
store alone and built as the pipeline's own site, in a process of its own,
with the site tool its manifest names.

**Whose files these are.** A store may be one a team shares, and anyone who
can write it can put a snapshot in it. So a version's build runs as a build
of files that are not the user's own (:func:`chartbook.config.untrusted_source`):
templates in Jinja's sandbox and none from the project, only pages and
pictures from its site folder, no page taking in a file from outside the
site, never a notebook run, and a time limit. Every name in a record that
becomes a folder is checked first (:func:`version_name`, :func:`slug`).

A snapshot never changes, so its site is built once and kept on this
machine, under ``versions/`` in the cache
(:func:`chartbook.config.get_cache_path`), keyed by ChartBook's version and
a fingerprint of its code, so that a change to ChartBook builds it again; a
catalog build copies it into the site at :func:`site_path`. One that cannot
be built gets a page that says why, so that a link to it never leads
nowhere. The versions are separate sites, so the catalog's search finds the
working versions only.
"""

from __future__ import annotations

import functools
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The folder of a catalog's site that holds the versions' sites.
VERSIONS_DIR = "versions"
#: The file a kept site is finished with; its text is why it could not be built, or nothing.
_DONE = ".chartbook-version-site"
#: How long a version's build may take, in seconds, before it is stopped and said.
BUILD_TIMEOUT = 600
#: A staging folder older than this, in seconds, was left by a build that stopped; it is cleared.
_ABANDONED = 3600
_NAME = re.compile(r"^[0-9a-f]{7}-[0-9]{8}T[0-9]{6}(\.[0-9]{1,9})?Z$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MADE_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?Z$")


def version_name(commit: str, made_at: str) -> str:
    """The name of a version's folder: the commit's start and when the snapshot was made.

    ``4f2a91c-20261013T182205.123456Z``. One commit may have several
    snapshots, a pull script having brought other data; the time tells them
    apart.

    :raises ValueError: If the commit is not a full commit hash or the time
        is not one a snapshot writes: a record written to mislead, whose
        values would otherwise become folder names.
    """
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        raise ValueError(f"{commit!r} is not a full commit hash")
    if not isinstance(made_at, str) or not _MADE_AT.match(made_at):
        raise ValueError(f"{made_at!r} is not a time as a snapshot writes one")
    name = f"{commit[:7]}-{made_at.replace('-', '').replace(':', '')}"
    if not _NAME.match(name):
        raise ValueError(f"{name!r} is not a version's name")
    return name


def slug(pipeline_id: str) -> str:
    """A pipeline's ID as one folder name, as the writers write it.

    :raises ValueError: If a part of the ID is ``.`` or ``..``, or has a
        character a folder name should not, so that it would not name one
        folder of its own.
    """
    from chartbook.identity import validate_pipeline_id

    try:
        validate_pipeline_id(str(pipeline_id))
    except ValueError:
        raise ValueError(f"{pipeline_id!r} is not a pipeline ID, and names no folder") from None
    return "--".join(str(pipeline_id).split("/"))


def site_path(pipeline_id: str, name: str) -> str:
    """Where a version's site is in a catalog's site: ``versions/<pipeline>/<version>``."""
    if not _NAME.match(name):
        raise ValueError(f"{name!r} is not a version's name")
    return f"{VERSIONS_DIR}/{slug(pipeline_id)}/{name}"


@dataclass(frozen=True)
class Rendered:
    """A version's site on this machine.

    Attributes:
        folder: The site's folder, with an ``index.html``.
        built: True if it is the version's site; False if it is the page
            that says why the site could not be built.
        why: Why not, in one line; empty when built.
        now: True if this call built it; False if it was kept from before.
    """

    folder: Path
    built: bool
    why: str = ""
    now: bool = False


@functools.lru_cache(maxsize=None)
def fingerprint() -> str:
    """ChartBook's version and a fingerprint of its code: what a kept site was built with.

    From the names, sizes and times of the package's files, so a change to
    ChartBook (an upgrade, or an edit to an install from source) builds the
    versions again, and an unchanged one never does.
    """
    from chartbook import __about__

    package = Path(__file__).parent
    digest = hashlib.sha256()
    for file in sorted(package.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
            stat = file.stat()
            digest.update(f"{file.relative_to(package).as_posix()}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return f"{__about__.__version__}-{digest.hexdigest()[:12]}"


def _kept(pipeline_id: str, name: str) -> Path:
    from chartbook.config import get_cache_path

    return get_cache_path() / VERSIONS_DIR / slug(pipeline_id) / name / fingerprint()


def render(taken, store=None, timeout: float = BUILD_TIMEOUT) -> Rendered:
    """A snapshot's site: kept from an earlier build, or built now from the store alone.

    :param taken: A :class:`chartbook.snapshot.Snapshot`.
    :raises ValueError: If the snapshot's record names no folder of its own
        (:func:`version_name`, :func:`slug`).
    """
    from chartbook import snapshot as snapshots
    from chartbook.config import UNTRUSTED_ENV_VAR

    name = version_name(taken.commit, taken.made_at)
    kept = _kept(taken.pipeline, name)
    if (kept / _DONE).is_file():
        why = (kept / _DONE).read_text(encoding="utf-8").strip()
        return Rendered(kept / "site", built=not why, why=why)

    kept.parent.mkdir(parents=True, exist_ok=True)
    _clear_abandoned(kept.parent)
    staging = kept.parent / f".{kept.name}.{uuid.uuid4().hex}"
    why = ""
    again = False  # a failure that a later build may not meet: not kept as done
    try:
        with tempfile.TemporaryDirectory(prefix="chartbook-version-") as scratch:
            # Named as the pipeline is, for a manifest whose ID comes from its
            # folder; the version file says it all the same
            folder = Path(scratch) / slug(taken.pipeline).split("--")[-1]
            try:
                # Its documents, charts, notebooks and notes; the data is shown from the snapshot's index
                laid = snapshots.materialize(taken, folder, store, data=False)
            except snapshots.StoreNotReadyError as error:
                # Not all in the store yet, a sync not finished perhaps: tried again next time
                why = f"it is not all in the store yet: {_one_line(error)}"
                again = True
            except Exception as error:  # noqa: BLE001 - a version that cannot be laid out is said, not fatal
                why = f"it could not be laid out from the store: {_one_line(error)}"
            else:
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "chartbook.cli", "docs", "build", str(staging / "site"), "-f"],
                        cwd=laid.folder,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env={**_without_credentials(os.environ), UNTRUSTED_ENV_VAR: "1"}, encoding="utf-8", errors="replace"
                    )
                except subprocess.TimeoutExpired:
                    why = f"its site took longer than {int(timeout)} seconds to build and was stopped"
                else:
                    if result.returncode != 0 or not (staging / "site" / "index.html").is_file():
                        said = (result.stderr or result.stdout).strip().splitlines()
                        why = f"its site could not be built: {said[-1] if said else 'the build failed'}"
        if why:
            shutil.rmtree(staging / "site", ignore_errors=True)
            _placeholder(staging / "site", taken, why)
        if not again:
            (staging / _DONE).write_text(why + "\n", encoding="utf-8", newline="\n")
        if kept.is_dir() and not (kept / _DONE).is_file():
            # The placeholder of a build that is to be tried again, which this one replaces
            shutil.rmtree(kept, ignore_errors=True)
        try:
            os.replace(staging, kept)
        except OSError:
            pass  # another build kept it first; theirs is as good as this one
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # What other ChartBooks built of this version is not what this one shows
    for other in kept.parent.iterdir():
        if other.is_dir() and other.name != kept.name and not other.name.startswith("."):
            shutil.rmtree(other, ignore_errors=True)
    return Rendered(kept / "site", built=not why, why=why, now=True)


def forget(taken) -> bool:
    """Clear the sites kept on this machine of a snapshot that is gone; True if there were any.

    ``store gc`` calls this for each snapshot it removes, so the cache holds
    no site of a version no catalog will show again.
    """
    from chartbook.config import get_cache_path

    try:
        folder = get_cache_path() / VERSIONS_DIR / slug(taken.pipeline) / version_name(taken.commit, taken.made_at)
    except ValueError:
        return False
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    try:
        folder.parent.rmdir()  # the pipeline's folder, if this was its last version
    except OSError:
        pass
    return True


def _clear_abandoned(folder: Path) -> None:
    """Clear staging folders a build left when it was stopped."""
    now = time.time()
    for entry in folder.iterdir():
        try:
            if entry.name.startswith(".") and entry.is_dir() and now - entry.stat().st_mtime > _ABANDONED:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


def _one_line(error: BaseException) -> str:
    said = str(error).strip()
    return said.splitlines()[0] if said else type(error).__name__


def _placeholder(folder: Path, taken, why: str) -> None:
    """The page a version that could not be built gets, so that a link to it says why."""
    folder.mkdir(parents=True, exist_ok=True)
    title = f"{taken.pipeline} at {taken.commit[:7]}"
    (folder / "index.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>The snapshot made {html.escape(taken.made_at[:16].replace('T', ' '))} UTC is in the store, "
        f"and its site could not be built: {html.escape(why)}.</p></body></html>\n",
        encoding="utf-8", newline="\n"
    )


def render_listed(index: dict, store=None, echo=print) -> dict:
    """Build (or find kept) the site of every snapshot a catalog's index lists, and say on each entry whether it was built.

    Called before the catalog's pages are written, so that a page links to
    a version's page only when its site was built, and otherwise to the
    page that says why (``rendered`` on each ``snapshots`` entry). A
    snapshot that has left the store since the index was made (a ``gc``
    elsewhere) is dropped from its record, so that nothing links to it. A
    version that could not be built is said in one line.

    :returns: Each version built or found, by ``(pipeline, commit,
        made_at)``: the snapshot and its :class:`Rendered`, for
        :func:`add_to_site` to copy.
    """
    from chartbook import snapshot as snapshots
    from chartbook.store import default_store

    store = store if store is not None else default_store()
    found, _ = snapshots.readable_snapshots(store)
    by_moment = {(t.pipeline, t.commit, t.made_at): t for t in found}
    done: dict = {}
    for record in index.get("records", []):
        if record.get("kind") != "Pipeline" or not record.get("snapshots"):
            continue
        kept = []
        for entry in record["snapshots"]:
            moment = (record["id"], entry.get("commit"), entry.get("made_at"))
            taken = by_moment.get(moment)
            if taken is None:
                continue  # gone from the store: nothing will link to it
            try:
                rendered = render(taken, store)
            except ValueError:
                continue
            entry["rendered"] = rendered.built
            kept.append(entry)
            done[moment] = (taken, rendered)
            if not rendered.built and rendered.now:
                echo(f"warning: {record['id']} at {taken.commit[:7]}: {rendered.why}")
        if kept:
            record["snapshots"] = kept
        else:
            record.pop("snapshots", None)
    return done


def add_to_site(index: dict, html_dir: Path, store=None, echo=print, rendered_by_moment: dict | None = None) -> list[Rendered]:
    """Put the site of every snapshot a catalog's index lists into its rendered site.

    Each is built once on this machine and kept (:func:`render`), and copied
    here to :func:`site_path` under *html_dir*. A version's folder that the
    index no longer lists, its snapshot removed by ``store gc``, is removed,
    so that an incremental build does not go on serving it. The store is
    read once; a record that cannot be read is left out, as the index left
    it out. A version that could not be built is said in one line.
    """
    from chartbook import snapshot as snapshots
    from chartbook.store import default_store

    store = store if store is not None else default_store()
    if rendered_by_moment is None:
        found, _ = snapshots.readable_snapshots(store)
        rendered_by_moment = {(t.pipeline, t.commit, t.made_at): (t, None) for t in found}
    by_moment = {moment: taken for moment, (taken, _) in rendered_by_moment.items()}
    wanted: dict[str, set[str]] = {}
    done = []
    for record in index.get("records", []):
        if record.get("kind") != "Pipeline" or not record.get("snapshots"):
            continue
        try:
            folder = slug(record["id"])
        except ValueError:
            continue
        for entry in record["snapshots"]:
            taken = by_moment.get((record["id"], entry.get("commit"), entry.get("made_at")))
            try:
                name = version_name(entry.get("commit"), entry.get("made_at"))
            except ValueError:
                continue
            if taken is None:
                continue
            rendered = rendered_by_moment[(record["id"], entry.get("commit"), entry.get("made_at"))][1]
            if rendered is None or not rendered.folder.is_dir():
                rendered = render(taken, store)  # not built yet, or cleared since: build it now
            target = html_dir / site_path(record["id"], name)
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(rendered.folder, target)
            wanted.setdefault(folder, set()).add(name)
            if not rendered.built and rendered.now:
                echo(f"warning: {record['id']} at {taken.commit[:7]}: {rendered.why}")
            done.append(rendered)
    _prune(html_dir / VERSIONS_DIR, wanted)
    return done


def _prune(root: Path, wanted: dict[str, set[str]]) -> None:
    """Remove the versions' folders the index no longer lists."""
    if not root.is_dir():
        return
    for pipeline in root.iterdir():
        if not pipeline.is_dir():
            continue
        if pipeline.name not in wanted:
            shutil.rmtree(pipeline, ignore_errors=True)
            continue
        for version in pipeline.iterdir():
            if version.name not in wanted[pipeline.name]:
                shutil.rmtree(version, ignore_errors=True) if version.is_dir() else version.unlink()


def _without_credentials(environment) -> dict:
    """The environment of a build of files from a store, with no warehouse's credentials in it.

    Such a build reaches no engine (``refuse_in_an_untrusted_build``); this
    keeps the credentials out of its reach besides.
    """
    from chartbook.backends import SOURCE_ENV_PREFIX

    return {
        name: value
        for name, value in environment.items()
        if not name.startswith("DATABRICKS_") and not name.startswith(SOURCE_ENV_PREFIX)
    }
