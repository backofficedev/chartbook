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
- The commit is `src/chartbook/built_from.txt`, written into the source tree
  for the build and removed after, so that the sdist carries it where a
  wheel built from the sdist finds it. One that is there already is kept:
  an sdist's, or one a packager committed after unpacking an sdist into a
  repository of their own. A build from a checkout whose `template/` has
  changes git has not committed records no commit, and says so; a build in
  a folder with a `.git` that git cannot read stops.

The version is not touched.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: The file the package carries the commit in, beside its modules
BUILT_FROM = "built_from.txt"

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
    """The commit *root* is checked out at, if it is the top of a git checkout; None otherwise."""
    if not is_checkout(root):
        return None
    return (git(root, "rev-parse", "HEAD") or "").strip() or None


def template_files(root) -> list[str]:
    """The template's files, relative to `template/`: those git tracks in a checkout, else all that are there."""
    folder = Path(root) / "template"
    if is_checkout(root):
        listed = git(root, "ls-files", "-z", "--", "template") or ""
        names = [Path(name).relative_to("template") for name in listed.split("\0") if name]
        # A file deleted and not yet committed is listed, and is not there
        return sorted(str(name) for name in names if (folder / name).is_file())
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())


class CustomBuildHook(BuildHookInterface):
    """Ship the template's tracked files, and `built_from.txt`, in a wheel or an sdist."""

    def initialize(self, version, build_data):
        if version == "editable":
            return
        root = Path(self.root)
        if (root / ".git").exists() and not is_checkout(root):
            raise RuntimeError(
                f"{root} has a .git, and git cannot read it (is git installed, and does it trust this "
                f"folder? `git -C {root} status` says why), so the commit the build is of is not known."
            )

        inside = "chartbook/template" if self.target_name == "wheel" else "template"
        for name in template_files(root):
            build_data["force_include"][str(root / "template" / name)] = f"{inside}/{name}"

        recorded = root / "src" / "chartbook" / BUILT_FROM
        self._written = None
        if recorded.is_file() and not (
            is_checkout(root) and not git(root, "ls-files", "--", f"src/chartbook/{BUILT_FROM}")
        ):
            return  # an sdist's, or a packager's: kept
        commit = commit_of(root)
        if commit is None:
            return  # no checkout and no file: not known
        if (git(root, "status", "--porcelain", "--", "template") or "").strip():
            self._warn(
                f"template/ has changes git has not committed, so the package records no commit for it, "
                f"and a project chartbook init makes from it has no .cruft.json."
            )
            if recorded.is_file():
                recorded.unlink()  # a leftover from an earlier build of this checkout
            return
        recorded.write_text(commit + "\n", encoding="utf-8")
        self._written = recorded

    def finalize(self, version, build_data, artifact_path):
        written = getattr(self, "_written", None)
        if written is not None and written.is_file():
            written.unlink()

    def _warn(self, message):
        app = getattr(self, "app", None)
        if app is not None:
            app.display_warning(message)
