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
  changes git has not committed (or for which `git status` fails) records an
  empty file: no commit. Built from an sdist, the sdist's own file is kept,
  with a warning if it records no commit. An sdist is told by its `PKG-INFO`
  before git is asked, so one unpacked into a repository of its own is still
  the sdist.
- A build that cannot record the commit stops, saying what to do: a folder
  whose `.git` git cannot read (git not installed, a folder git does not
  trust), a copy with neither a `.git` nor an sdist's `PKG-INFO` (a source
  zip, a Docker context without `.git`), a `template/` with changes git has
  not committed, or an sdist that records no commit. So a wheel or an sdist
  always says which commit its template is at, and never ships a stray
  `built_from.txt` from the tree. Only these builds are affected: an
  editable install skips the hook, and `pip install` of the wheel on PyPI
  runs no build at all.

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
                raise RuntimeError(
                    f"{root} has a .git, and git cannot read it, so the build cannot tell which files of "
                    f"template/ to ship, nor the commit they are at. Install git; or, if git does not trust "
                    f"the folder, run `git config --global --add safe.directory {root}`; or build from an "
                    f"sdist, which carries both."
                )
            raise RuntimeError(
                f"{root} is neither a git checkout nor an sdist, so the build cannot tell which files of "
                f"template/ to ship, nor the commit they are at. Build from a clone of the repository or "
                f"from an sdist, or install the release from PyPI."
            )

        inside = "chartbook/template" if self.target_name == "wheel" else "template"
        for name in template_files(root, checkout):
            build_data["force_include"][str(root / "template" / name)] = f"{inside}/{name}"

        if sdist:
            # The sdist's own file ships as any file of the package does
            shipped = root / "src" / "chartbook" / BUILT_FROM
            if not (shipped.is_file() and shipped.read_text(encoding="utf-8").strip()):
                raise RuntimeError(
                    f"{root} is an sdist that records no commit for its template/, so a project chartbook "
                    f"init makes from it would have no .cruft.json. Build the sdist from a git checkout."
                )
            return
        commit = commit_of(root)
        if commit is None:
            raise RuntimeError(
                "template/ has changes git has not committed (or git could not say), so the build cannot "
                "record the commit that says what ships. Commit them, or set them aside, and build again."
            )
        # Written aside, never into the tree; force-included, which overrides a stray copy there
        self._folder = Path(tempfile.mkdtemp(prefix="chartbook-build-"))
        written = self._folder / BUILT_FROM
        written.write_text(commit + "\n", encoding="utf-8")
        target = "chartbook" if self.target_name == "wheel" else "src/chartbook"
        build_data["force_include"][str(written)] = f"{target}/{BUILT_FROM}"

    def finalize(self, version, build_data, artifact_path):
        folder = getattr(self, "_folder", None)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

