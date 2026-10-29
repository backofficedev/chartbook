"""Incremental builds: regenerate and re-render only what changed.

A clean build writes every page into an empty directory and has Sphinx read
and render all of them. An incremental build keeps the Sphinx project (the
``_docs`` directory) from the previous build and saves work in two places:

1. **Pipelines whose inputs are unchanged are not regenerated.** Each
   pipeline gets a *fingerprint*: a hash over the modification time and size
   of everything its pages are made from — its ``chartbook.toml``, its
   ``src/`` and ``docs_src/`` trees, and every file its manifest declares.
   A pipeline whose fingerprint matches the last build is skipped, and the
   pages it produced then are left exactly as they are.
2. **Pages whose content is unchanged are not touched.** Whatever does get
   regenerated is written to a staging directory and synced into the build
   tree file by file, comparing content. Sphinx decides what to re-read by
   modification time, so a page that is rewritten identically would be
   re-read for nothing; a page that is left alone is not.

The fingerprint is modification-time based. That is the same notion of
"changed" the rest of ChartBook uses for now; the build record designed in
``docs_src/design/asset-graph.md`` replaces it with content hashes.

Nothing here schedules or runs a pipeline's own build. This only decides
which *documentation pages* need regenerating once asked to build them.
"""

from __future__ import annotations

import filecmp
import glob
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from importlib import metadata

from chartbook.__about__ import __version__
from chartbook.manifest import get_pipeline_ids, get_pipeline_manifest
from chartbook.utils import is_glob_pattern

#: Records what the build tree was built from. Lives at its root.
STATE_FILE = ".chartbook-build-state.json"

#: Bumped when the state file or the layout of the build tree changes shape,
#: so trees written by an older ChartBook are rebuilt rather than trusted.
STATE_VERSION = 1

#: Sphinx's own output and cache, inside the build tree. Never synced over.
SPHINX_BUILD_DIR = "_build"

#: Keeps the kept build tree out of ``git status`` without the project
#: having to list it in its own ``.gitignore``.
GITIGNORE_FILE = ".gitignore"

# Trees inside a pipeline whose every file can end up on a page
_SOURCE_TREES = ("src", "docs_src")

# The packages that turn the generated project into HTML. An upgrade to any
# of them can change every rendered page without any source changing.
_RENDERING_PACKAGES = (
    "sphinx",
    "myst-nb",
    "myst-parser",
    "ablog",
    "pydata-sphinx-theme",
    "sphinx-book-theme",
    "sphinx-design",
    "sphinx-copybutton",
)


def _rendering_versions() -> dict[str, Optional[str]]:
    """Installed versions of the packages that render the site."""
    versions = {}
    for package in _RENDERING_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def _slug(pipeline_id: str) -> str:
    """Filesystem form of a pipeline ID, as the page generator writes it."""
    return str(pipeline_id).replace("/", "--")


def _stamp(path: Path) -> Optional[tuple[int, int]]:
    """A file's (mtime in ns, size), or None if it is not there."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _walk_files(directory: Path) -> list[Path]:
    """Every file under a directory, sorted; empty if it does not exist."""
    if not directory.is_dir():
        return []
    return sorted(
        Path(root) / name for root, _, files in os.walk(directory) for name in files
    )


def _is_noise(name: str) -> bool:
    """True for files that change without anything a page shows changing.

    Editor swap and backup files, Finder metadata and bytecode caches would
    otherwise make a watched project look edited when it was only opened.
    """
    return name.startswith(".") or name.endswith("~") or name == "__pycache__"


def _walk_inputs(directory: Path) -> list[Path]:
    """The files under a directory that count as build inputs, sorted."""
    if not directory.is_dir():
        return []
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not _is_noise(d)]
        found.extend(Path(root) / name for name in files if not _is_noise(name))
    return sorted(found)


def pipeline_input_files(pipeline_manifest: dict) -> list[Path]:
    """List every file a pipeline's generated pages are made from.

    That is: its manifest and README, the trees its write-ups and templates
    come from, any template override in its root, and each file an entry in
    its manifest declares. A declared file that does not exist yet is
    listed all the same, so that its appearing counts as a change.

    :param pipeline_manifest: One pipeline's loaded manifest.
    :returns: Absolute paths, sorted and without duplicates.
    """
    base_dir = Path(pipeline_manifest["pipeline_base_dir"])
    readme = pipeline_manifest.get("project", {}).get("readme") or "README.md"
    files = {base_dir / "chartbook.toml", base_dir / readme}

    for tree in _SOURCE_TREES:
        files.update(_walk_inputs(base_dir / tree))
    site_dir = pipeline_manifest.get("project", {}).get("_resolved_site_dir")
    if site_dir:
        files.update(_walk_inputs(Path(site_dir)))
    # A Markdown file in the project root can override a page template
    files.update(p for p in base_dir.glob("*.md") if p.is_file())

    for section in ("dataframes", "charts", "notebooks", "notes", "models", "files"):
        for entry in (pipeline_manifest.get(section) or {}).values():
            for key in ("path", "docs_path", "excel_path", "metrics_path"):
                declared = entry.get(key)
                if not isinstance(declared, str) or not declared.strip():
                    continue
                declared_path = base_dir / declared
                if is_glob_pattern(declared):
                    files.update(
                        Path(match)
                        for match in glob.glob(str(declared_path), recursive=True)
                    )
                elif declared_path.is_dir():
                    # A model or a files asset may be a directory: every file in it counts
                    files.update(_walk_files(declared_path))
                else:
                    files.add(declared_path)
    return sorted(files)


def pipeline_fingerprint(pipeline_id: str, pipeline_manifest: dict, salt: str = "") -> str:
    """Hash everything a pipeline's pages depend on.

    Two builds with the same fingerprint produce the same pages for this
    pipeline, so the second need not produce them at all.

    :param pipeline_id: The pipeline's ID in this build (a catalog's key).
    :param pipeline_manifest: Its loaded manifest.
    :param salt: What else the pages depend on that is not a file of this
        pipeline's: the digest of what its provenance panels say, which
        read other pipelines' records in the index.
    :returns: A hex digest.
    """
    base_dir = Path(pipeline_manifest["pipeline_base_dir"])
    digest = hashlib.sha256()
    digest.update(pipeline_id.encode())
    digest.update(f"\0salt\0{salt}".encode())
    for path in pipeline_input_files(pipeline_manifest):
        try:
            name = path.relative_to(base_dir).as_posix()
        except ValueError:  # a declared path outside the project
            name = path.as_posix()
        digest.update(f"\0{name}\0{_stamp(path)}".encode())
    return digest.hexdigest()


def global_fingerprint(manifest: dict, theme_dir: Path, options: dict) -> str:
    """Hash what every page depends on, whichever pipeline it belongs to.

    A change here — an upgrade to ChartBook, Sphinx or a theme, an edited
    theme template, a different build option — invalidates the whole build
    tree.

    :param manifest: The top-level loaded manifest.
    :param theme_dir: The packaged theme directory pages are rendered with.
    :param options: Build options that alter generated pages.
    :returns: A hex digest.
    """
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "state_version": STATE_VERSION,
                "chartbook": __version__,
                "rendering": _rendering_versions(),
                "type": manifest["project"]["type"],
                "enable_data_download": bool(
                    manifest["project"].get("enable_data_download", False)
                ),
                "options": options,
            },
            sort_keys=True,
            default=str,
        ).encode()
    )
    for path in _walk_inputs(Path(theme_dir)):
        name = path.relative_to(theme_dir).as_posix()
        digest.update(f"\0{name}\0{_stamp(path)}".encode())
    return digest.hexdigest()


def pipeline_owned_paths(pipeline_id: str, pipeline_manifest: dict) -> list[Path]:
    """Where in the build tree one pipeline's pages and copied files live.

    Paths are relative to the build tree's root. A directory stands for
    everything beneath it.

    :param pipeline_id: The pipeline's ID in this build.
    :param pipeline_manifest: Its loaded manifest.
    """
    slug = _slug(pipeline_id)
    owned = [
        Path("cb") / "dataframes" / slug,
        Path("cb") / "models" / slug,
        Path("cb") / "files" / slug,
        Path("cb") / "notebooks" / slug,
        Path("cb") / "download_chart" / slug,
        Path("cb") / "download_dataframe" / slug,
        Path("_static") / slug,
        Path("cb") / "pipelines" / f"{slug}_README.md",
    ]
    owned += [
        Path("cb") / "charts" / f"{slug}.{chart_id}.md"
        for chart_id in pipeline_manifest.get("charts") or {}
    ]
    return owned


def _pages_exist(build_dir: Path, pipeline_id: str, pipeline_manifest: dict) -> bool:
    """Check the pages a pipeline should already have are really there."""
    slug = _slug(pipeline_id)
    expected = [
        build_dir / "cb" / "dataframes" / slug / f"{dataframe_id}.md"
        for dataframe_id in pipeline_manifest.get("dataframes") or {}
    ]
    expected += [
        build_dir / "cb" / "charts" / f"{slug}.{chart_id}.md"
        for chart_id in pipeline_manifest.get("charts") or {}
    ]
    expected += [
        build_dir / "cb" / "models" / slug / f"{model_id}.md"
        for model_id in pipeline_manifest.get("models") or {}
    ]
    expected += [
        build_dir / "cb" / "files" / slug / f"{files_id}.md"
        for files_id in pipeline_manifest.get("files") or {}
    ]
    return all(page.is_file() for page in expected)


@dataclass
class BuildPlan:
    """What one incremental build will regenerate and what it will reuse.

    Attributes:
        global_fingerprint: Fingerprint of what every page depends on.
        fingerprints: Fingerprint of each pipeline taking part in the build.
        regenerate: Pipelines whose pages will be generated this time.
        reuse: Pipelines whose pages from the last build are kept as they are.
        fresh: True when nothing from a previous build can be trusted and
            the build tree must start empty.
        reason: Why the build is fresh, for the summary line.
        rendered: True when the previous build's sources were rendered by
            Sphinx without error, so that an unchanged project needs no
            render at all.
        code_times: When each reused pipeline's code last changed, as the
            previous build recorded it. The build fills in the rest.
    """

    global_fingerprint: str
    fingerprints: dict[str, str]
    regenerate: list[str]
    reuse: list[str]
    fresh: bool
    reason: str = ""
    rendered: bool = False
    code_times: dict[str, str] = field(default_factory=dict)

    def preserved_paths(self, manifest: dict) -> list[Path]:
        """Build-tree paths that belong to reused pipelines."""
        preserved: list[Path] = []
        for pipeline_id in self.reuse:
            pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
            preserved += pipeline_owned_paths(pipeline_id, pipeline_manifest)
        return preserved


def read_state(build_dir: Path) -> Optional[dict]:
    """Load the build tree's state file; None if absent or unreadable."""
    try:
        with open(Path(build_dir) / STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return None
    return state


def write_state(build_dir: Path, plan: BuildPlan, rendered: bool = False) -> None:
    """Record what the build tree now reflects.

    :param rendered: Whether Sphinx has rendered the sources as they now
        stand. False until it has finished without error, so a failed or
        interrupted render is run again by the next build.
    """
    state = {
        "version": STATE_VERSION,
        "global": plan.global_fingerprint,
        "pipelines": plan.fingerprints,
        "code_times": plan.code_times,
        "rendered": rendered,
    }
    with open(Path(build_dir) / STATE_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def plan_build(
    manifest: dict,
    build_dir: Path,
    theme_dir: Path,
    options: dict,
    skip_pipelines: Iterable[str] = (),
    salts: Optional[dict] = None,
) -> BuildPlan:
    """Decide which pipelines to regenerate and which to reuse.

    :param manifest: The top-level loaded manifest.
    :param build_dir: The kept build tree (``_docs``).
    :param theme_dir: The packaged theme directory for this project type.
    :param options: Build options that alter generated pages.
    :param skip_pipelines: Pipelines left out of the build altogether (their
        source files are missing); they are neither regenerated nor reused.
    :param salts: For each pipeline, what else its pages depend on; see
        :func:`pipeline_fingerprint`.
    """
    build_dir = Path(build_dir)
    skipped = set(skip_pipelines)
    pipeline_ids = [p for p in get_pipeline_ids(manifest) if p not in skipped]
    fingerprints = {
        pipeline_id: pipeline_fingerprint(
            pipeline_id, get_pipeline_manifest(manifest, pipeline_id), (salts or {}).get(pipeline_id, "")
        )
        for pipeline_id in pipeline_ids
    }
    current_global = global_fingerprint(manifest, theme_dir, options)

    state = read_state(build_dir)
    if state is None:
        reason = "no previous incremental build"
    elif state.get("global") != current_global:
        reason = "ChartBook, Sphinx, the theme or the build options changed"
    else:
        reason = ""
    if reason:
        return BuildPlan(current_global, fingerprints, pipeline_ids, [], True, reason)

    previous = state.get("pipelines", {})
    regenerate, reuse = [], []
    for pipeline_id in pipeline_ids:
        pipeline_manifest = get_pipeline_manifest(manifest, pipeline_id)
        same_inputs = previous.get(pipeline_id) == fingerprints[pipeline_id]
        if same_inputs and _pages_exist(build_dir, pipeline_id, pipeline_manifest):
            reuse.append(pipeline_id)
        else:
            regenerate.append(pipeline_id)
    recorded_times = state.get("code_times") or {}
    return BuildPlan(
        current_global,
        fingerprints,
        regenerate,
        reuse,
        fresh=False,
        rendered=bool(state.get("rendered")),
        code_times={p: recorded_times[p] for p in reuse if p in recorded_times},
    )


def looks_like_build_tree(directory: Path) -> bool:
    """Tell whether a directory was written by a ChartBook build."""
    directory = Path(directory)
    return (directory / STATE_FILE).is_file() or (
        (directory / "conf.py").is_file() and (directory / "index.md").is_file()
    )


def check_build_tree(build_dir: Path) -> None:
    """Refuse a build directory that holds something that is not a build tree.

    Called first, before anything is read or hashed, so that the error
    comes before the work.

    :raises ValueError: If *build_dir* holds unrelated files.
    """
    build_dir = Path(build_dir)
    if build_dir.exists() and any(build_dir.iterdir()) and not looks_like_build_tree(build_dir):
        raise ValueError(
            f"{build_dir} exists and is not a ChartBook build directory, "
            f"so an incremental build will not write into it. Point "
            f"--docs-build-dir at an empty or new directory."
        )


def prepare_build_tree(build_dir: Path, fresh: bool) -> None:
    """Make the build tree ready to be synced into.

    A fresh build empties it. A directory holding something that is not a
    ChartBook build tree is never emptied; that is an error instead.

    :raises ValueError: If *build_dir* holds unrelated files.
    """
    build_dir = Path(build_dir)
    check_build_tree(build_dir)
    if build_dir.exists() and any(build_dir.iterdir()):
        if fresh:
            shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    gitignore = build_dir / GITIGNORE_FILE
    if not gitignore.is_file():
        gitignore.write_text("*\n", encoding="utf-8", newline="\n")


#: Suffixes of the files Sphinx turns into pages.
PAGE_SUFFIXES = (".md", ".ipynb", ".rst")


@dataclass
class SyncResult:
    """What a sync changed in the destination tree.

    Attributes:
        written: Files copied across, new or changed. Relative paths.
        added: The subset of *written* that did not exist before.
        deleted: Files removed because the source no longer has them.
        unchanged: How many files were identical and left alone.
    """

    written: list[Path] = field(default_factory=list)
    added: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    unchanged: int = 0

    @property
    def pages_added_or_removed(self) -> bool:
        """True if the set of pages changed, not just what some of them say.

        Sphinx re-renders a page only when its own source changes, so a page
        that appears or disappears leaves every other page's navigation
        stale, and Sphinx never deletes the HTML of a page that is gone.
        """
        return bool(self.deleted) or any(
            path.suffix in PAGE_SUFFIXES for path in self.added
        )


def _is_under(path: Path, ancestors: frozenset[str]) -> bool:
    """True if a relative path equals, or lies beneath, any of *ancestors*.

    :param ancestors: Relative paths in POSIX form.
    """
    parts = path.parts
    return any("/".join(parts[:n]) in ancestors for n in range(1, len(parts) + 1))


def sync_tree(
    source: Path,
    destination: Path,
    preserve: Iterable[Path] = (),
    same: Optional[Callable[[Path, Path], bool]] = None,
) -> SyncResult:
    """Make *destination* mirror *source*, touching only what differs.

    A file identical to its counterpart is left alone, modification time
    included. A file in *destination* with no counterpart is deleted unless
    it is preserved.

    :param source: The tree to mirror.
    :param destination: The tree to update in place.
    :param preserve: Paths relative to *destination* to leave alone even
        though *source* lacks them. A directory covers everything under it.
    :param same: Decides whether two existing files are identical. Defaults
        to a byte-for-byte comparison.
    """
    source, destination = Path(source), Path(destination)
    preserve = frozenset(Path(p).as_posix() for p in preserve)
    if same is None:
        same = lambda a, b: filecmp.cmp(a, b, shallow=False)  # noqa: E731
    result = SyncResult()

    wanted = set()
    for src_file in _walk_files(source):
        relative = src_file.relative_to(source)
        wanted.add(relative)
        dst_file = destination / relative
        existed = dst_file.is_file()
        if existed and same(src_file, dst_file):
            result.unchanged += 1
            continue
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, dst_file)
        result.written.append(relative)
        if not existed:
            result.added.append(relative)

    for dst_file in _walk_files(destination):
        relative = dst_file.relative_to(destination)
        if relative in wanted or _is_under(relative, preserve):
            continue
        dst_file.unlink()
        result.deleted.append(relative)

    # Directories emptied by the deletions above
    for root, dirs, files in os.walk(destination, topdown=False):
        root_path = Path(root)
        if root_path == destination or _is_under(
            root_path.relative_to(destination), preserve
        ):
            continue
        if not any(root_path.iterdir()):
            root_path.rmdir()
    return result


def same_size_and_not_newer(source_file: Path, destination_file: Path) -> bool:
    """Cheap sameness test for rendered output: same size, and not newer.

    Used to copy built HTML to the output directory without reading every
    file. Sphinx rewrites a page only when it re-renders it, and a copy is
    always newer than its source, so an untouched page compares as the same.
    """
    src, dst = source_file.stat(), destination_file.stat()
    return src.st_size == dst.st_size and src.st_mtime_ns <= dst.st_mtime_ns


def snapshot_inputs(manifest: dict, project_dir: Path) -> dict[str, Optional[tuple]]:
    """Stat everything a build of this project reads.

    Two snapshots differing means a rebuild might produce something
    different. Used by watch mode to notice edits; which pipelines actually
    need regenerating is still decided by :func:`plan_build`.

    :param manifest: The top-level loaded manifest.
    :param project_dir: The directory holding its ``chartbook.toml``.
    :returns: Mapping of path to (mtime in ns, size), or None if missing.
    """
    project_dir = Path(project_dir)
    files = {project_dir / "chartbook.toml"}
    for key in ("logo", "favicon"):
        declared = manifest.get("project", {}).get(key)
        if declared:
            files.add(project_dir / declared)
    for pipeline_id in get_pipeline_ids(manifest):
        files.update(pipeline_input_files(get_pipeline_manifest(manifest, pipeline_id)))
    return {str(path): _stamp(path) for path in sorted(files)}


def describe_changes(before: dict, after: dict, limit: int = 3) -> str:
    """Name the files that differ between two snapshots, briefly."""
    changed = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    names = [Path(path).name for path in changed[:limit]]
    more = len(changed) - len(names)
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def watch(
    build: Callable[[], None],
    snapshot: Callable[[], dict],
    interval: float = 1.0,
    echo: Callable[[str], None] = print,
    sleep: Optional[Callable[[float], None]] = None,
    max_polls: Optional[int] = None,
) -> int:
    """Build, then rebuild whenever the project's inputs change.

    A thin polling loop: no file-system notification service, no server, no
    process other than this one. It ends on Ctrl-C.

    A failed build is reported and the loop carries on, since the commonest
    cause is a file caught half-saved.

    :param build: Runs one build. May raise, or exit, on failure.
    :param snapshot: Returns the current state of the inputs (see
        :func:`snapshot_inputs`). May raise while a manifest is mid-edit;
        the problem is reported once and the loop waits for it to clear.
    :param interval: Seconds between checks.
    :param echo: Receives progress lines.
    :param sleep: Waits between checks. Defaults to ``time.sleep``.
    :param max_polls: Stop after this many checks. None means until Ctrl-C.
    :returns: The number of builds run, including the first.
    """

    def run_build() -> None:
        started = time.monotonic()
        try:
            build()
        except KeyboardInterrupt:
            raise
        except SystemExit:
            # The build already printed why it stopped
            echo("Build failed. Still watching.")
        except Exception as error:
            echo(f"Build failed: {error}. Still watching.")
        else:
            echo(f"Built in {time.monotonic() - started:.1f}s.")

    unreadable = {"error": None}

    def take_snapshot(previous: dict) -> dict:
        try:
            current = snapshot()
        except Exception as error:
            # Usually a manifest caught mid-edit. Say so once, since nothing
            # can be rebuilt until it loads, and look again at the next poll.
            if str(error) != unreadable["error"]:
                unreadable["error"] = str(error)
                echo(f"Cannot read the project: {error}. Waiting for it to be fixed.")
            return previous
        unreadable["error"] = None
        return current

    if sleep is None:
        sleep = time.sleep

    builds = 1
    run_build()
    seen = take_snapshot({})
    echo(f"Watching for changes every {interval:g}s. Press Ctrl-C to stop.")
    polls = 0
    try:
        while max_polls is None or polls < max_polls:
            sleep(interval)
            polls += 1
            current = take_snapshot(seen)
            if current == seen:
                continue
            echo(f"Changed: {describe_changes(seen, current)}. Rebuilding...")
            # Recorded before building, so an edit made while the build
            # runs still differs at the next poll and is picked up then
            seen = current
            run_build()
            builds += 1
    except KeyboardInterrupt:
        echo("Stopped watching.")
    return builds
