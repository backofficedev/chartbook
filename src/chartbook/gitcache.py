"""Fetching a ``git`` dependency: clones kept under ``~/.chartbook/git/``.

A dependency may be a git repository instead of a directory::

    [dependencies]
    "ftsfr/ref_data" = { git = "https://gitlab.example.org/ftsfr/ref_data", rev = "v1.2" }

To pin it, ChartBook needs the repository's files at one commit on this
disk. This module gets them there and nothing more. From then on the
checkout is a directory like any ``path`` dependency's, and pinning treats
it as one.

::

    ~/.chartbook/git/
      repos/gitlab.example.org/ftsfr/ref_data.git       one bare clone per repository
      checkouts/gitlab.example.org/ftsfr/ref_data/
        4f2a91c0…/                                      one checkout per commit
      work/gitlab.example.org/ftsfr/ref_data/
        4f2a91c0…/                                      a copy to build in, if run

Three steps, each its own method, because only the first uses the network:

``fetch``
    Bring the bare clone up to date with the repository.
``resolve``
    Turn a ``rev`` (a branch, a tag, a commit, or nothing for the default
    branch) into the full hash of one commit. Looks only at the clone.
``checkout``
    Write that commit's files into its own directory, if they are not
    there. Looks only at the clone.

ChartBook runs the ``git`` on your ``PATH``, so whatever lets you clone the
repository by hand lets ChartBook: SSH keys, credential helpers, a proxy.
A URL is handed to git on each call and is never written into the clone's
configuration, so a token in a URL does not end up on disk here, and a URL
is shown without its credentials in every message.

**A clone has what the repository commits, and no more.** Built data is
usually git-ignored, so a pipeline fetched this way has its code and its
manifest and, typically, none of its data. What a ``git`` dependency
declares and does not commit is "not built", exactly as for a ``path``
dependency that has not been run. ``chartbook pin`` does not run it.

``chartbook run`` does. It makes a **working copy** of the commit, which
is the same files and writable, and runs the dependency's ``build`` there
(:meth:`GitCache.work_copy`), once. What that build produces can then be
pinned. A file in the copy says the build has finished (:func:`is_built`).
A dependency that has a working copy is pinned from it, since it holds
everything the checkout does and whatever was built besides. The checkout
itself is never written to.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from chartbook.config import get_git_cache_path
from chartbook.identity import strip_url_credentials

#: Where bare clones are, under the cache's root.
REPOS_DIR = "repos"

#: Where checkouts are: one directory per repository, one inside it per commit.
CHECKOUTS_DIR = "checkouts"

#: Where working copies are: laid out like the checkouts, and writable. A
#: working copy is where ``chartbook run`` runs a git dependency's build.
WORK_DIR = "work"

#: A file in a working copy that says a build has finished there. It is
#: inside the copy, so it goes when the copy goes.
BUILT_MARKER = ".chartbook-built"

#: The ref a clone keeps the repository's default branch under, so that a
#: dependency with no ``rev`` has something to mean.
DEFAULT_REF = "refs/chartbook/default"

#: The transports git may use for a dependency. Git's ``ext::`` transport
#: runs a command; a manifest must not be able to ask for it.
ALLOWED_PROTOCOLS = "file:git:http:https:ssh"

#: git as the cache runs it. A clone of a local repository is kept under a
#: folder named after that repository's own path, so its files' paths can be
#: longer than the 260 characters Windows otherwise allows a path.
GIT = ("git", "-c", "core.longpaths=true") if os.name == "nt" else ("git",)

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_HEX = re.compile(r"^[0-9a-f]{7,40}$")
# What a revision may be: a branch, a tag or a commit. It is handed to git
# as an argument, so it must never be able to read as an option.
_REV = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
# git@host:owner/name, or host:owner/name. Not C:\repo, which is a path.
_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]{2,}):(?![/\\])(.+)$")


#: What git takes from the environment about which repository it is in. A
#: git hook sets some of them; none may reach a command on another repository.
GIT_LOCATION_VARIABLES = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PREFIX",
})


def check_git_url(url: str) -> str:
    """Refuse a repository URL that git could read as something else.

    :returns: The URL, unchanged.
    :raises ValueError: If it is empty, starts with ``-`` (git would take it
        for an option), or asks for a transport that runs a command.
    """
    text = url.strip() if isinstance(url, str) else ""
    if not text or text.startswith("-") or "::" in text.split("/", 1)[0]:
        raise ValueError(
            f"{url!r} is not a repository ChartBook will fetch. Give a URL "
            f"(https://…, ssh://…, git@host:owner/name) or a path."
        )
    return url


def local_url(url: str, base_dir: Union[str, Path]) -> str:
    """Make a repository that is a path on this disk an absolute one.

    ``git = "../ref_data"`` in a manifest is relative to that manifest. A
    URL with a scheme, or in the ``host:path`` form, is returned as it is.
    """
    text = url.strip()
    if "://" in text or _SCP_LIKE.match(text):
        return url
    return os.path.abspath(os.path.join(base_dir, os.path.expanduser(text)))


def check_rev(rev: Optional[str]) -> Optional[str]:
    """Refuse a revision that is not a plain branch, tag or commit name.

    :returns: The revision, unchanged.
    :raises ValueError: If it could be read as an option or an expression.
    """
    if rev is not None and not (isinstance(rev, str) and _REV.match(rev)):
        raise ValueError(
            f"{rev!r} is not a revision ChartBook will ask git for. A rev is a "
            f"branch, a tag or a commit: letters, digits, '.', '_', '/' and "
            f"'-', not starting with '-'."
        )
    return rev


class GitError(Exception):
    """Raised when git cannot do what a ``git`` dependency needs."""


@dataclass(frozen=True)
class Checkout:
    """A repository's files at one commit, on this disk.

    Attributes:
        url: The repository's URL, without credentials.
        rev: The revision that was asked for, or None for the default
            branch.
        commit: The full hash of the commit it resolved to.
        path: The directory the files are in.
    """

    url: str
    rev: Optional[str]
    commit: str
    path: Path


def repository_slug(url: str) -> Path:
    """A relative path for a repository, made from its URL: ``host/owner/name``.

    The same repository reached two ways (``https://host/a/b.git``,
    ``git@host:a/b``) gets one path, and so one clone. A repository on this
    disk goes under ``local/``, by its folder's name and a short hash of its
    whole path: the path in full would make one in the cache longer than
    the 260 characters Windows lets git work in. Nothing of a URL's user
    name or password is in it, and no component can climb out of the
    cache. A port stays, as
    ``host_8443``, and a component with a character that is not kept gets
    a short hash of itself, so that two different repositories never share
    a clone.
    """
    text = strip_url_credentials(url.strip())
    scp_like = _SCP_LIKE.match(text)
    with_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]*@)?([^/:]*)(?::(\d+))?/(.*)$", text)
    if with_scheme and not text.lower().startswith("file:"):
        host, port, path = with_scheme.group(1), with_scheme.group(2), with_scheme.group(3)
        if port:
            host = f"{host}_{port}"
    elif scp_like and "://" not in text:
        host, path = scp_like.group(1), scp_like.group(2)
    else:
        host, path = "local", re.sub(r"^file://", "", text)
    path = re.sub(r"\.git/?$", "", path.rstrip("/"))
    if host == "local":
        # One folder: its name, and a hash of the whole path, written with /
        # so that C:\\repos\\x and C:/repos/x are one repository
        whole = re.sub(r"[/\\]+", "/", path)
        name = next((part for part in reversed(whole.split("/")) if part and set(part) != {"."}), "repository")
        digest = hashlib.sha256(whole.encode("utf-8")).hexdigest()[:8]
        return Path("local", re.sub(r"[^A-Za-z0-9._-]", "_", name) + "~" + digest)
    components = [host, *re.split(r"[/\\]+", path)]
    safe = []
    for part in components:
        if not part or set(part) == {"."}:
            continue
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", part)
        if cleaned != part:
            cleaned += "~" + hashlib.sha256(part.encode("utf-8")).hexdigest()[:8]
        safe.append(cleaned)
    return Path(*safe) if safe else Path("local", "repository")


class GitCache:
    """The clones and checkouts that ``git`` dependencies are fetched into.

    :param root: The cache's directory. It need not exist yet.
    """

    def __init__(self, root: Union[str, Path]):
        self.root = Path(os.path.abspath(Path(root).expanduser()))

    def __repr__(self) -> str:
        return f"GitCache({str(self.root)!r})"

    def repo_path(self, url: str) -> Path:
        """Where the bare clone of a repository is, or would be."""
        slug = repository_slug(url)
        return self.root / REPOS_DIR / slug.parent / (slug.name + ".git")

    def checkout_path(self, url: str, commit: str) -> Path:
        """Where a repository's files at one commit are, or would be.

        :raises ValueError: If *commit* is not a full commit hash.
        """
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self.root / CHECKOUTS_DIR / repository_slug(url) / commit

    def find(self, url: str, commit: str) -> Optional[Path]:
        """A checkout that is already here, without running git; else None."""
        path = self.checkout_path(url, commit)
        return path if path.is_dir() else None

    def work_path(self, url: str, commit: str) -> Path:
        """Where the working copy of a repository at one commit is, or would be.

        :raises ValueError: If *commit* is not a full commit hash.
        """
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self.root / WORK_DIR / repository_slug(url) / commit

    def find_work(self, url: str, commit: str) -> Optional[Path]:
        """A working copy that is already here, without running git; else None."""
        path = self.work_path(url, commit)
        return path if path.is_dir() else None

    def files(self, url: str, commit: str) -> Optional[Path]:
        """The best copy of a commit's files that is on this disk; else None.

        The working copy if there is one, because it has what was built in
        it as well as what was committed; otherwise the checkout.
        """
        return self.find_work(url, commit) or self.find(url, commit)

    def work_copy(self, url: str, commit: str) -> Path:
        """Make a writable copy of a commit's files, if there is none yet.

        This is where a ``git`` dependency's build is run. It starts as the
        checkout's files and keeps whatever a build writes into it, so a
        second run finds the first one's work. One working copy is shared
        by every project of this user that depends on that commit.

        :returns: The working copy's directory.
        :raises GitError: If the clone does not have the commit.
        """
        final = self.work_path(url, commit)
        if final.is_dir():
            return final
        source = self.checkout(url, commit)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging = final.with_name(f"{commit}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copytree(source, staging, symlinks=True)
            for folder, _, names in os.walk(staging):
                for name in names:
                    file = os.path.join(folder, name)
                    if not os.path.islink(file):
                        os.chmod(file, os.stat(file).st_mode | stat.S_IWUSR)
            try:
                os.rename(staging, final)
            except OSError:
                if not final.is_dir():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return final

    def _git(self, *arguments: str, url: Optional[str] = None, env=None) -> str:
        """Run git, and return what it printed. Never shows a URL's credentials."""

        def shown(text: str) -> str:
            return text.replace(url, strip_url_credentials(url)) if url else text

        environment = {
            # Not where a git hook's environment says the repository is: this
            # runs on the cache's own clones, and must never touch the user's
            **{k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES},
            # Fail, do not wait for someone to type a password
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": ALLOWED_PROTOCOLS,
            **(env or {}),
        }
        environment.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
        try:
            result = subprocess.run(
                [*GIT, *arguments], capture_output=True, text=True, env=environment, encoding="utf-8", errors="replace"
            )
        except FileNotFoundError:
            raise GitError(
                "git is not installed, or is not on the PATH. A git dependency "
                "is fetched with it."
            ) from None
        if result.returncode != 0:
            message = shown(result.stderr.strip() or result.stdout.strip())
            raise GitError(message or f"git {shown(arguments[0])} failed")
        return result.stdout

    def fetch(self, url: str) -> Path:
        """Bring the clone of a repository up to date. This uses the network.

        The first time, the clone is made. Every branch and tag is fetched,
        and the repository's default branch is noted.

        :param url: The repository, as ``[dependencies]`` writes it.
        :returns: The bare clone's directory.
        :raises GitError: If the repository cannot be reached.
        :raises ValueError: If the URL is one git could misread.
        """
        check_git_url(url)
        repo = self.repo_path(url)
        if not (repo / "HEAD").is_file():
            repo.parent.mkdir(parents=True, exist_ok=True)
            staging = repo.with_name(f"{repo.name}.{uuid.uuid4().hex}.tmp")
            self._git("init", "--quiet", "--bare", str(staging))
            try:
                os.rename(staging, repo)
            except OSError:
                shutil.rmtree(staging, ignore_errors=True)
                if not (repo / "HEAD").is_file():
                    raise
        # The URL is given here and now, and is not kept in the clone
        self._git(
            f"--git-dir={repo}",
            "fetch",
            "--quiet",
            "--prune",
            "--force",
            url,
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
            f"+HEAD:{DEFAULT_REF}",
            url=url,
        )
        return repo

    def resolve(self, url: str, rev: Optional[str] = None) -> str:
        """Turn a revision into the full hash of a commit, from the clone.

        :param rev: A branch, a tag or a commit; None for the default branch.
        :raises GitError: If the repository has not been fetched, or has no
            such revision.
        :raises ValueError: If *rev* is not a plain revision name.
        """
        check_rev(rev)
        repo = self.repo_path(url)
        shown = strip_url_credentials(url)
        if not (repo / "HEAD").is_file():
            raise GitError(f"{shown} has not been fetched.")
        wanted = rev if rev is not None else DEFAULT_REF
        try:
            found = self._git(
                f"--git-dir={repo}", "rev-parse", "--verify", "--quiet", f"{wanted}^{{commit}}"
            )
        except GitError:
            what = f"no revision {rev!r}" if rev is not None else "no default branch"
            raise GitError(f"{shown} has {what}.") from None
        commit = found.strip()
        if not _FULL_COMMIT.match(commit):
            raise GitError(f"{shown}: {wanted!r} did not resolve to a commit.")
        return commit

    def checkout(self, url: str, commit: str) -> Path:
        """Write a commit's files into its own directory, if they are not there.

        The directory is made whole or not at all, and its files are
        read-only: a checkout is a copy of one commit, not a place to work.

        :returns: The checkout's directory.
        :raises GitError: If the clone does not have the commit.
        """
        final = self.checkout_path(url, commit)
        if final.is_dir():
            return final
        repo = self.repo_path(url)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging = final.with_name(f"{commit}.{uuid.uuid4().hex}.tmp")
        staging.mkdir()
        index = staging.with_name(staging.name + ".index")
        try:
            # An index of its own, so two checkouts at once do not collide
            self._git(
                f"--git-dir={repo}",
                f"--work-tree={staging}",
                "checkout",
                "--quiet",
                "--force",
                commit,
                "--",
                ".",
                env={"GIT_INDEX_FILE": str(index)},
            )
            for folder, _, names in os.walk(staging):
                for name in names:
                    file = os.path.join(folder, name)
                    if not os.path.islink(file):
                        # Read-only, but a script stays runnable
                        mode = os.stat(file).st_mode
                        os.chmod(file, _READ_ONLY | (mode & 0o111))
            try:
                os.rename(staging, final)
            except OSError:
                if not final.is_dir():
                    raise
        finally:
            if index.exists():
                index.unlink()
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return final

    def get(self, url: str, rev: Optional[str] = None, fetch: bool = True) -> Checkout:
        """Fetch a repository, resolve a revision and check it out.

        :param fetch: If False, the network is not used: the clone is taken
            as it is.
        :returns: The checkout.
        :raises GitError: If any step cannot be done.
        :raises ValueError: If the URL or the revision is one git could
            misread.
        """
        check_git_url(url)
        check_rev(rev)
        if fetch:
            self.fetch(url)
        try:
            commit = self.resolve(url, rev)
        except GitError:
            if not (fetch and rev and _HEX.match(rev)):
                raise
            # A commit that no branch or tag leads to has to be asked for
            self._git(
                f"--git-dir={self.repo_path(url)}", "fetch", "--quiet", url, rev, url=url
            )
            commit = self.resolve(url, rev)
        return Checkout(
            url=strip_url_credentials(url),
            rev=rev,
            commit=commit,
            path=self.checkout(url, commit),
        )


def is_built(work_copy: Union[str, Path]) -> bool:
    """Whether a working copy's build has finished: ``chartbook run`` ran it."""
    return (Path(work_copy) / BUILT_MARKER).is_file()


def mark_built(work_copy: Union[str, Path]) -> None:
    """Note in a working copy that its build has finished.

    A git dependency is built once for a commit. This is what says it has
    been, so that the next run leaves it alone.
    """
    (Path(work_copy) / BUILT_MARKER).write_text(
        "chartbook run finished this pipeline's build here.\n", encoding="utf-8", newline="\n"
    )


def forget_built(work_copy: Union[str, Path]) -> None:
    """Take that note away, before a build is run there again."""
    try:
        (Path(work_copy) / BUILT_MARKER).unlink()
    except FileNotFoundError:
        pass


def default_git_cache() -> GitCache:
    """The cache this user's ChartBook fetches ``git`` dependencies into.

    ``CHARTBOOK_GIT_CACHE`` if it is set; otherwise ``[git] path`` in
    ``~/.chartbook/settings.toml``; otherwise ``~/.chartbook/git``.
    """
    return GitCache(get_git_cache_path())
