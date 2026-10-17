"""A build hook: record the commit of this repository that a package is built from.

`chartbook init` renders the project template that comes with the package
(`template/`, which the wheel carries as `chartbook/template`), and writes
the commit it is from into the new project's `.cruft.json`, so that
`cruft update` can follow the template on GitHub from there. A wheel or an
sdist built from a git checkout carries that commit in `built_from.txt`
beside the package's modules; a wheel built from such an sdist finds the
file there. An editable install writes nothing: ChartBook asks git at run
time (`chartbook.scaffold.template_commit`). The version is not touched.
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


def commit_of(root) -> Optional[str]:
    """The commit *root* is checked out at, if it is the top of a git checkout; None otherwise.

    An sdist unpacked inside some other repository is not that repository's.
    """
    environment = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES}

    def git(*arguments):
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *arguments], capture_output=True, text=True, env=environment, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != Path(root).resolve():
        return None
    return git("rev-parse", "HEAD") or None


class CustomBuildHook(BuildHookInterface):
    """Put `built_from.txt` into the wheel or sdist, when the build is of a git checkout."""

    def initialize(self, version, build_data):
        if version == "editable":
            return
        commit = commit_of(self.root)
        if commit is None:
            # From an sdist, which carries the file already; or from no checkout: not known
            return
        self._folder = Path(tempfile.mkdtemp(prefix="chartbook-build-"))
        written = self._folder / BUILT_FROM
        written.write_text(commit + "\n", encoding="utf-8")
        inside = "chartbook" if self.target_name == "wheel" else "src/chartbook"
        build_data["force_include"][str(written)] = f"{inside}/{BUILT_FROM}"

    def finalize(self, version, build_data, artifact_path):
        folder = getattr(self, "_folder", None)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
