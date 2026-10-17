"""A build hook: the project template, and the commit it is at, go into the package.

`chartbook init` renders the project template that comes with the package,
and writes the commit it is from into the new project's `.cruft.json`, so
that `cruft update` can follow the template on GitHub from there.

For a wheel or an sdist (not an editable install, which renders `template/`
from the checkout and asks git for the commit at run time):

- The template is the files git tracks in `template/`, as `chartbook/template`
  in the wheel and `template/` in the sdist; built from an sdist, which is
  no checkout, it is the sdist's own `template/`. What git ignores there (an
  `.env`, `.ipynb_checkpoints/`) is never shipped.
- The commit goes in as `built_from.txt`: `src/chartbook/built_from.txt` in
  the sdist, where a wheel built from the sdist finds it, and
  `chartbook/built_from.txt` in the wheel. It is written to a temporary
  folder, never into the source tree, and force-included, which overrides any
  stray copy in the tree. A build from a checkout whose `template/` has
  changes git has not committed records an empty file: no commit. Built from
  an sdist, the sdist's own file is kept.
- A folder that is neither a checkout git can read nor an sdist (git not
  installed, a folder git does not trust, a copy without `.git`) gets the
  template as it is on disk and an empty `built_from.txt` (no commit, and
  never a stray one), with a warning. With `CHARTBOOK_BUILD_REQUIRE_GIT=1`
  in the environment, as a release's build has (`doit hatch_build`), that
  stops the build, and so does a `template/` with uncommitted changes: a
  release always records its commit.

The version is not touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: The file the package carries the commit in, beside its modules
BUILT_FROM = "built_from.txt"

#: Set to 1 for a build that must record the commit (a release's): what
#: would otherwise build with a warning and no commit stops it instead
REQUIRE_GIT = "CHARTBOOK_BUILD_REQUIRE_GIT"

#: Where the environment can tell git to look; a build looks at its own folder
GIT_LOCATION_VARIABLES = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX",
})


def git(root, *arguments) -> Optional[str]:
    """What git says in *root*, or None if it fails."""
    environment = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments], capture_output=True, text=True, env=environment, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def is_checkout(root) -> bool:
    """Whether *root* is the top of a git checkout: an sdist unpacked inside another repository is not."""
    top = git(root, "rev-parse", "--show-toplevel")
    return bool(top) and Path(top.strip()).resolve() == Path(root).resolve()


def commit_of(root) -> Optional[str]:
    """The commit *root* is checked out at, if it is the top of a git checkout and its
    `template/` has no changes git has not committed; None otherwise."""
    if not is_checkout(root):
        return None
    changes = git(root, "status", "--porcelain", "--untracked-files=no", "--", "template")
    if changes is None or changes.strip():
        # Changed, or git could not say: either way the commit does not say what ships
        return None
    return (git(root, "rev-parse", "HEAD") or "").strip() or None


def template_files(root, checkout: bool) -> list[str]:
    """The template's files, relative to `template/`: those git tracks in a checkout, else all that are there.

    :raises RuntimeError: If git cannot list them, or lists one that is not
        on disk (a sparse checkout, a file deleted and not committed): the
        package would carry a template with files missing.
    """
    folder = Path(root) / "template"
    if not checkout:
        return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())
    listed = git(root, "ls-files", "-z", "--", "template")
    if listed is None:
        raise RuntimeError(f"git could not list the files of {folder}, so the package would carry no template.")
    names = [str(Path(name).relative_to("template")) for name in listed.split("\0") if name]
    missing = [name for name in names if not (folder / name).is_file()]
    if missing:
        raise RuntimeError(
            f"git tracks files of {folder} that are not on disk (a sparse checkout, or a file deleted and "
            f"not committed), so the package would carry the template without them: {', '.join(missing[:5])}"
        )
    return sorted(names)


class CustomBuildHook(BuildHookInterface):
    """Ship the template's tracked files, and `built_from.txt`, in a wheel or an sdist."""

    def initialize(self, version, build_data):
        if version == "editable":
            return
        root = Path(self.root)
        # An sdist first: one unpacked into a repository of its own (a distribution's packaging) is
        # still the sdist, and its own file names the commit, not that repository's HEAD
        sdist = (root / "PKG-INFO").is_file()
        checkout = not sdist and is_checkout(root)
        if not checkout and not sdist:
            if (root / ".git").exists():
                message = (
                    f"{root} has a .git, and git cannot read it, so the package carries template/ as it is "
                    f"on disk, ignored files and all, and no commit for it. Install git; or, if git does not "
                    f"trust the folder, run `git config --global --add safe.directory {root}`; or build from "
                    f"an sdist."
                )
            else:
                message = (
                    f"{root} is neither a git checkout nor an sdist, so the package carries template/ as it "
                    f"is on disk, ignored files and all, and no commit for it. Build from a git checkout, or "
                    f"from an sdist."
                )
            self._stop_or_warn(message)

        inside = "chartbook/template" if self.target_name == "wheel" else "template"
        for name in template_files(root, checkout):
            build_data["force_include"][str(root / "template" / name)] = f"{inside}/{name}"

        if sdist:
            # The sdist's own file ships as any file of the package does
            shipped = root / "src" / "chartbook" / BUILT_FROM
            if not (shipped.is_file() and shipped.read_text(encoding="utf-8").strip()):
                self._stop_or_warn(
                    f"{root} is an sdist that records no commit for its template/, so the package records "
                    f"none, and a project chartbook init makes from it has no .cruft.json."
                )
            return
        commit = commit_of(root) if checkout else None
        if checkout and commit is None:
            self._stop_or_warn(
                "template/ has changes git has not committed, so the package records no commit for it, "
                "and a project chartbook init makes from it has no .cruft.json."
            )
        # Written aside, never into the tree; force-included, which overrides a stray copy there
        self._folder = Path(tempfile.mkdtemp(prefix="chartbook-build-"))
        written = self._folder / BUILT_FROM
        written.write_text((commit or "") + "\n", encoding="utf-8")
        target = "chartbook" if self.target_name == "wheel" else "src/chartbook"
        build_data["force_include"][str(written)] = f"{target}/{BUILT_FROM}"

    def finalize(self, version, build_data, artifact_path):
        folder = getattr(self, "_folder", None)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def _stop_or_warn(self, message):
        """Stop the build with *message* when it must record the commit; else warn."""
        if os.environ.get(REQUIRE_GIT, "").strip() == "1":
            raise RuntimeError(f"{message} ({REQUIRE_GIT}=1 makes this an error.)")
        self._warn(message)

    def _warn(self, message):
        app = getattr(self, "app", None)
        if app is not None:
            app.display_warning(message)
