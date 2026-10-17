"""The build that writes a site: the writer's pages, and the files beside them.

A site is a pure function of an index and the files the index names. The
Sphinx writer (:mod:`chartbook.writers.sphinx`) renders the pages from the
records; this module copies the files themselves into the Sphinx tree —
charts, notebooks, notes, data downloads, the theme's own files and a
pipeline's own site pages — driven by the same index, and :func:`write_site`
puts the two together. Nothing here reads a manifest to decide what to copy:
the index says what the site has.
"""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path
from typing import Iterable, Optional

from chartbook.config import untrusted_source
from chartbook.utils import is_glob_pattern

#: Files of the theme that are not copied to the root of the Sphinx tree:
#: generated folders and pages the writer renders, and the theme's charts
#: listing, which goes under ``cb/``.
THEME_FILES_NOT_AT_ROOT = (
    "charts",
    "dataframes",
    "notebooks",
    "index.md",
    "pipelines.md",
    "dataframes.md",
    "models",
    "models.md",
    "diagnostics.md",
    "charts.md",
    "versions.md",
    "site",
)


def _slug(pipeline_id: str) -> str:
    return pipeline_id.replace("/", "--")


def copy_plan(
    index: dict,
    docs_build_dir: Path,
    enable_data_download: bool = False,
    skip: Iterable[str] = (),
    reused: Iterable[str] = (),
    with_notes: bool = True,
) -> list[tuple[Path, Path]]:
    """Where each file the index names goes under the Sphinx tree, as (source, destination) pairs.

    A chart's HTML goes to ``cb/download_chart/<slug>/<name>.html`` and to
    ``_static/<slug>/<name>.html`` (the page embeds the latter); a notebook
    to ``cb/notebooks/<slug>/<its file name>``; a note to ``cb/<name>.md``;
    and, when downloads are enabled, a dataframe that is one file to
    ``cb/download_dataframe/<slug>/<name>.parquet``. A table, a query or a
    folder of parts has no file to offer.

    :param skip: Pipelines the build leaves out: nothing of theirs is copied.
    :param reused: Pipelines an incremental build keeps from an earlier one:
        their charts, notebooks and downloads stay as they are, but their
        notes are copied again, since the front page that lists them is
        written on every build and the tree is synced to what was written.
    :param with_notes: Whether notes are copied at all: the pipeline theme's
        front page lists them; a catalog has no page that does.
    """
    root = Path(docs_build_dir)
    skipped, kept = set(skip), set(reused)
    plan: list[tuple[Path, Path]] = []
    for record in index.get("records", []):
        kind = record.get("kind")
        if kind not in ("Chart", "Notebook", "Note", "Dataframe") or record.get("pipeline") in skipped:
            continue
        if kind == "Note" and not with_notes:
            continue
        if kind != "Note" and record.get("pipeline") in kept:
            continue
        location = record.get("location") or {}
        source = location.get("resolved_path")
        if not source or location.get("kind") != "file":
            continue
        if not_built(record):
            continue  # write_not_built stands in for it
        slug, name = _slug(record["pipeline"]), record["ref"]["name"]
        if kind == "Chart":
            plan.append((Path(source), root / "cb" / "download_chart" / slug / f"{name}.html"))
            plan.append((Path(source), root / "_static" / slug / f"{name}.html"))
        elif kind == "Notebook":
            plan.append((Path(source), root / "cb" / "notebooks" / slug / Path(source).name))
        elif kind == "Note":
            plan.append((Path(source), root / "cb" / f"{name}.md"))
        elif enable_data_download and downloadable(record):
            plan.append((Path(source), root / "cb" / "download_dataframe" / slug / f"{name}.parquet"))
    return plan


def downloadable(record: dict) -> bool:
    """Whether a dataframe is one file the build copies for download: its page links it only then.

    A table, a query, a folder of parts and a glob have no one file to
    offer, and one not built has none yet.
    """
    location = record.get("location") or {}
    source = location.get("resolved_path")
    if location.get("kind") != "file" or not source or not_built(record):
        return False
    return not is_glob_pattern(source) and not Path(source).is_dir()


def copy_files(plan: Iterable[tuple[Path, Path]]) -> None:
    """Copy each file to where the plan says, making the folders on the way."""
    for source, destination in plan:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


#: What a chart, notebook or dataframe that is not built yet shows in its
#: place, with its declared path and the command marked up for where it is shown
NOT_BUILT = (
    "Not built yet. This is {path}, which the pipeline's build makes: "
    "{command} runs the build and renders the site again."
)

#: The same in a version's site, built from the store: the version is as it
#: was made, and nothing builds it now
NOT_BUILT_IN_VERSION = "Not built in this version. This is {path}, which was not built when this version was made."


def not_built(record: dict) -> bool:
    """Whether a record is of a declared file that is not there: not built yet.

    A file that is there and could not be read has no hash either, and is
    not this: copying it fails, and says why.
    """
    from chartbook import hashing

    location = record.get("location") or {}
    if location.get("kind") != "file" or "content_hash" in record or not location.get("resolved_path"):
        return False
    found = hashing.find_files(location["resolved_path"])
    return found is None or not found.files


def not_built_text(path: str, command: str) -> str:
    """What stands in for an output that is not built, with *path* and *command* already marked up."""
    if untrusted_source():
        return NOT_BUILT_IN_VERSION.format(path=path)
    return NOT_BUILT.format(path=path, command=command)


def write_not_built(index: dict, docs_build_dir: Path, skip: Iterable[str] = ()) -> None:
    """Put a short file saying "not built yet" where each unbuilt chart and notebook would go.

    A pipeline that has built nothing yet is rendered all the same (see
    ``build_docs.generate_docs``), and its pages link to its charts and
    notebooks: each link then goes to this, rather than nowhere. The
    index has the record and no hash, so its provenance panel says "not
    built" too.
    """
    import html

    root = Path(docs_build_dir)
    skipped = set(skip)
    for record in index.get("records", []):
        kind = record.get("kind")
        if kind not in ("Chart", "Notebook") or record.get("pipeline") in skipped:
            continue
        location = record.get("location") or {}
        if not location.get("path") or not not_built(record):
            continue
        slug, name = _slug(record["pipeline"]), record["ref"]["name"]
        if kind == "Chart":
            text = not_built_text(
                path=f"<code>{html.escape(location['path'])}</code>", command="<code>chartbook build</code>"
            )
            page = f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head><body><p>{text}</p></body></html>\n'
            # Both places copy_plan would put the chart: the full-screen link, and what the page embeds
            for destination in (
                root / "cb" / "download_chart" / slug / f"{name}.html",
                root / "_static" / slug / f"{name}.html",
            ):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(page, encoding="utf-8")
        else:
            title = " ".join(str(record.get("name", name)).split())
            # One code span on one line, whatever the manifest wrote
            path = " ".join(location["path"].replace("`", "'").split())
            notebook = {
                "cells": [
                    {
                        "cell_type": "markdown",
                        "metadata": {},
                        "source": [
                            f"# {title}\n",
                            "\n",
                            not_built_text(path=f"`{path}`", command="`chartbook build`") + "\n",
                        ],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 4,
            }
            destination = root / "cb" / "notebooks" / slug / Path(location["path"]).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with open(destination, "w", encoding="utf-8") as file:
                json.dump(notebook, file, indent=1, ensure_ascii=False)
                file.write("\n")


def ensure_notebook_titles(index: dict, docs_build_dir: Path, skip: Iterable[str] = ()) -> None:
    """Give each copied notebook a title cell if its first cell is not a heading.

    Sphinx needs a title for every document, and skips one without saying
    so. The title is the notebook's ``name``, or its key.
    """
    root = Path(docs_build_dir)
    skipped = set(skip)
    for record in index.get("records", []):
        if record.get("kind") != "Notebook" or record.get("pipeline") in skipped:
            continue
        location = record.get("location") or {}
        if not location.get("path"):
            continue
        copied = root / "cb" / "notebooks" / _slug(record["pipeline"]) / Path(location["path"]).name
        if not copied.exists():
            continue
        with open(copied, "r", encoding="utf-8") as file:
            notebook = json.load(file)
        cells = notebook.get("cells", [])
        if cells and cells[0].get("cell_type") == "markdown":
            if "".join(cells[0].get("source", [])).lstrip().startswith("#"):
                continue
        title = record.get("name", record["ref"]["name"])
        notebook.setdefault("cells", []).insert(
            0, {"cell_type": "markdown", "metadata": {}, "source": [f"# {title}\n"]}
        )
        with open(copied, "w", encoding="utf-8") as file:
            json.dump(notebook, file, indent=1, ensure_ascii=False)
            file.write("\n")


def copy_theme_files(docs_src_dir: Path, docs_build_dir: Path, charts: bool = True, templates: bool = True) -> None:
    """Copy the theme's own files to the root of the site tree, and its charts listing under ``cb/``.

    Everything under the theme's ``docs_src`` but what the writer renders and
    the generated folders (:data:`THEME_FILES_NOT_AT_ROOT`); the folder
    structure is kept, and only file contents are copied.

    :param charts: Whether the theme's static ``charts.md`` goes under ``cb/``;
        not when the writer renders that page itself.
    :param templates: Whether the theme's ``_templates`` folder is copied;
        Sphinx reads its HTML templates from there, MkDocs would render them
        as pages.
    """
    docs_src_dir, docs_build_dir = Path(docs_src_dir), Path(docs_build_dir)
    docs_build_dir.mkdir(parents=True, exist_ok=True)
    for source in docs_src_dir.rglob("*"):
        # The parts under the theme folder, not of the machine's path to it:
        # a project in a folder named `models` still gets its theme
        relative = source.relative_to(docs_src_dir)
        if any(part in THEME_FILES_NOT_AT_ROOT for part in relative.parts) or not source.is_file():
            continue
        if not templates and relative.parts[0] == "_templates":
            continue
        destination = docs_build_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    listing = docs_src_dir / "charts.md"
    if charts and listing.exists():
        (docs_build_dir / "cb").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(listing, docs_build_dir / "cb" / "charts.md")


#: What a site page of a build of files from a store may be: pages and pictures.
UNTRUSTED_SITE_FILES = frozenset({".md", ".png", ".jpg", ".jpeg", ".gif", ".webp"})


def _a_site_page(relative: Path) -> bool:
    """Whether a file of a site folder may be copied into the site: not the build's own configuration or templates."""
    parts = relative.parts
    if parts and parts[0] in ("_templates", "_build"):
        return False
    if len(parts) == 1 and (relative.name.startswith("conf.py") or relative.name in ("docutils.conf", "mkdocs.yml")):
        return False
    return True


def copy_site_pages(index: dict, docs_build_dir: Path) -> None:
    """Copy a pipeline's own site pages (its `site_dir`) to the root of the Sphinx tree.

    Every file under the folder, but ``index_toc.md`` at its root, which the
    writer merges into the front page instead. A pipeline site's one
    pipeline supplies them; the catalog theme has no front page that lists
    them, so a catalog copies none.
    """
    root = Path(docs_build_dir)
    for record in index.get("records", []):
        if record.get("kind") != "Pipeline":
            continue
        folder = (record.get("site_dir") or {}).get("resolved_path")
        if not folder:
            continue
        folder = Path(folder)
        for source in folder.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(folder)
            if relative.parent == Path(".") and relative.name == "index_toc.md":
                continue
            if not _a_site_page(relative):
                warnings.warn(
                    f"Ignoring '{source}': a site page may not be {relative.as_posix()}, which the build "
                    f"writes or reads as its own configuration or templates.",
                    stacklevel=2,
                )
                continue
            if untrusted_source() and source.suffix.lower() not in UNTRUSTED_SITE_FILES:
                continue  # from a store: pages and pictures, nothing a tool might run
            if relative.parent == Path(".") and relative.name == "index.md":
                warnings.warn(
                    f"Ignoring '{source}': a root index.md in site_dir would replace the "
                    f"site's front page. Put what it should show in index_toc.md instead.",
                    stacklevel=2,
                )
                continue
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def write_site(
    docs_build_dir: Path,
    base_dir: Path,
    pipeline_theme: str = "pipeline",
    docs_src_dir: Optional[Path] = None,
    size_threshold: float = 50,
    skip_pipelines: Optional[Iterable[str]] = None,
    reuse_pipelines: Optional[Iterable[str]] = None,
    code_times: Optional[dict] = None,
    hash_cache=None,
    built_index: Optional[dict] = None,
) -> dict:
    """Write the Sphinx tree of a site: the index first, then its pages and files.

    The index is built once, before any page, so that every page is a
    reader of it and says what it says. Then the writer renders a page for
    every record of a pipeline this build generates — a pipeline the build
    skips, or an incremental build keeps, has none written — plus the
    catalog's own pages, and the files the index names are copied beside
    them: charts, notebooks, notes, downloads, the theme's files and, in
    the pipeline theme, the pipeline's own site pages. A chart or notebook
    that is not built yet gets a short file saying so in its place.

    :param code_times: Code-change times already known, by pipeline ID (see
        ``manifest.apply_code_change_times``). Others are worked out here.
    :param built_index: The index, when the caller built it already.
    :returns: The index the site was written from.
    """
    from chartbook import hashing
    from chartbook import index as index_module
    from chartbook.manifest import apply_code_change_times, load_manifest
    from chartbook.writers import writer_class
    from chartbook.writers.sphinx import check_front_matter

    docs_build_dir = Path(docs_build_dir)
    docs_build_dir.mkdir(parents=True, exist_ok=True)
    not_generated = set(skip_pipelines or ()) | set(reuse_pipelines or ())
    docs_src_dir = Path(docs_src_dir) if docs_src_dir is not None else Path(base_dir) / "_docs_src"

    manifest = load_manifest(base_dir=base_dir)
    # Pages say when the code changed according to git, not the file system
    apply_code_change_times(manifest, known=code_times)
    if built_index is None:
        cache = hash_cache if hash_cache is not None else hashing.HashCache(docs_build_dir / hashing.CACHE_FILE)
        built_index = index_module.build_index(manifest, cache=cache, skip_pipelines=skip_pipelines or ())
        cache.save()
    enable_data_download = bool(manifest["project"].get("enable_data_download", False))

    writer = writer_class(manifest["project"].get("writer", "sphinx"))(
        built_index,
        theme=pipeline_theme,
        docs_src_dir=docs_src_dir,
        size_threshold=size_threshold,
        enable_data_download=enable_data_download,
    )
    for record in built_index["records"]:
        kind = record.get("kind")
        if kind not in ("Dataframe", "Chart", "Model", "Pipeline"):
            continue
        owner = record["id"] if kind == "Pipeline" else record.get("pipeline")
        # A pipeline site's front page is the site's, written whatever is reused
        site_wide = kind == "Pipeline" and pipeline_theme == "pipeline"
        if owner in not_generated and not site_wide:
            continue
        page = docs_build_dir / writer.page_path(record)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(writer.page(record), encoding="utf-8")
        if kind == "Chart":
            check_front_matter(page, owner, record["ref"]["name"])

    copy_files(
        copy_plan(
            built_index,
            docs_build_dir,
            enable_data_download,
            skip=set(skip_pipelines or ()),
            reused=set(reuse_pipelines or ()),
            with_notes=pipeline_theme == "pipeline",
        )
    )
    write_not_built(built_index, docs_build_dir, skip=not_generated)
    ensure_notebook_titles(built_index, docs_build_dir, skip=not_generated)
    own_pages = writer.own_page_paths()
    copy_theme_files(docs_src_dir, docs_build_dir, charts="cb/charts.md" not in own_pages, templates=writer.THEME_TEMPLATES_IN_SITE)
    if pipeline_theme == "pipeline":
        copy_site_pages(built_index, docs_build_dir)
    # The site's own pages last: the theme's static copy of a page the writer renders would overwrite it
    for page_path in own_pages:
        page = docs_build_dir / page_path
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(writer.own_page(page_path), encoding="utf-8")
    return built_index
