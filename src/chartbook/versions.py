"""Versions of a catalog's pipelines: each snapshot in the store rendered as its own site.

A catalog shows every version of every pipeline it lists
(``docs_src/design/versioned-catalog.md``): the **working version**, the
pipeline's folder as it is, which is what the catalog's own pages show;
and every **snapshot** of it in the store, each a version its owner
declared ready. A snapshot holds what its site needs
(:func:`chartbook.snapshot.materialize`), so each is laid out from the
store alone and built as the pipeline's own site, in a process of its own,
with the site tool its manifest names.

A snapshot never changes, so its site is built once per ChartBook version
and kept on this machine, under ``versions/`` in the cache
(:func:`chartbook.config.get_cache_path`); a catalog build copies it into
the site at :func:`site_path`. One that cannot be built gets a page that
says why, so that a link to it never leads nowhere, and is not tried again
until ChartBook changes. The versions are separate sites, so the catalog's
search finds the working versions only.
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The folder of a catalog's site that holds the versions' sites.
VERSIONS_DIR = "versions"
#: The file a kept site is finished with; a folder without it is not a site yet.
_DONE = ".chartbook-version-site"


def version_name(commit: str, made_at: str) -> str:
    """The name of a version's folder: the commit's start and when the snapshot was made.

    ``4f2a91c-20261013T182205.123456Z``. One commit may have several
    snapshots, a pull script having brought other data; the time tells them
    apart.
    """
    return f"{commit[:7]}-{made_at.replace('-', '').replace(':', '')}"


def slug(pipeline_id: str) -> str:
    """A pipeline's ID as one folder name, as the writers write it."""
    return pipeline_id.replace("/", "--")


def site_path(pipeline_id: str, name: str) -> str:
    """Where a version's site is in a catalog's site: ``versions/<pipeline>/<version>/``."""
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


def _kept(pipeline_id: str, name: str) -> Path:
    from chartbook import __about__
    from chartbook.config import get_cache_path

    return get_cache_path() / VERSIONS_DIR / slug(pipeline_id) / name / __about__.__version__


def render(taken, store=None) -> Rendered:
    """A snapshot's site: kept from an earlier build, or built now from the store alone.

    :param taken: A :class:`chartbook.snapshot.Snapshot`.
    """
    from chartbook import snapshot as snapshots

    name = version_name(taken.commit, taken.made_at)
    kept = _kept(taken.pipeline, name)
    if (kept / _DONE).is_file():
        why = (kept / _DONE).read_text(encoding="utf-8").strip()
        return Rendered(kept / "site", built=not why, why=why)

    kept.parent.mkdir(parents=True, exist_ok=True)
    staging = kept.parent / f".{kept.name}.{uuid.uuid4().hex}"
    why = ""
    with tempfile.TemporaryDirectory(prefix="chartbook-version-") as scratch:
        # The folder is named as the pipeline is, for a manifest whose ID
        # comes from its folder; the version file says it all the same
        folder = Path(scratch) / taken.pipeline.split("/")[-1]
        try:
            laid = snapshots.materialize(taken, folder, store)
        except Exception as error:  # noqa: BLE001 - a version that cannot be laid out is said, not fatal
            why = f"it could not be laid out from the store: {_one_line(error)}"
        else:
            result = subprocess.run(
                [sys.executable, "-m", "chartbook.cli", "docs", str(staging / "site"), "-f"],
                cwd=laid.folder,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not (staging / "site" / "index.html").is_file():
                said = (result.stderr or result.stdout).strip().splitlines()
                why = f"its site could not be built: {said[-1] if said else 'the build failed'}"
    if why:
        shutil.rmtree(staging / "site", ignore_errors=True)
        _placeholder(staging / "site", taken, why)
    (staging / _DONE).write_text(why + "\n", encoding="utf-8")
    try:
        os.replace(staging, kept)
    except OSError:
        # Another build kept it first; theirs is as good as this one
        shutil.rmtree(staging, ignore_errors=True)
    return Rendered(kept / "site", built=not why, why=why, now=True)


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
        encoding="utf-8",
    )


def snapshots_of(pipeline_id: str, store=None) -> list:
    """Every snapshot of a pipeline in the store, newest first."""
    from chartbook import snapshot as snapshots
    from chartbook.store import default_store

    store = store if store is not None else default_store()
    found = [taken for taken in snapshots.all_snapshots(store) if taken.pipeline == pipeline_id]
    return sorted(found, key=lambda taken: taken.made_at, reverse=True)


def add_to_site(index: dict, html_dir: Path, store=None, echo=print) -> list[Rendered]:
    """Put the site of every snapshot the index lists into a catalog's rendered site.

    Each is built once on this machine and kept (:func:`render`); here it is
    copied to :func:`site_path` under *html_dir*. A version that could not
    be built is said in one line.
    """
    from chartbook.store import default_store

    store = store if store is not None else default_store()
    done = []
    for record in index.get("records", []):
        if record.get("kind") != "Pipeline" or not record.get("snapshots"):
            continue
        wanted = {(entry["commit"], entry["made_at"]) for entry in record["snapshots"]}
        for taken in snapshots_of(record["id"], store):
            if (taken.commit, taken.made_at) not in wanted:
                continue
            rendered = render(taken, store)
            target = html_dir / site_path(record["id"], version_name(taken.commit, taken.made_at))
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(rendered.folder, target)
            if not rendered.built and rendered.now:
                echo(f"warning: {record['id']} at {taken.commit[:7]}: {rendered.why}")
            done.append(rendered)
    return done
