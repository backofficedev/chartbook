"""Pipeline identity: scoped names, URL normalization, and reference resolution.

The canonical identity of a pipeline is a scoped name ``scope/name``
(e.g. ``ftsfr/crsp_treasury``) or a bare ``name`` for local-only projects.
URLs are accepted as *input* wherever a pipeline reference is taken and are
normalized to scoped names; they are never stored as identity.

Two extensions of the grammar are reserved: recognized by the parser, and
refused with a "not yet supported" error rather than a grammar error, so
that they can be given meaning later without changing what any existing ID
means.

- ``scope/name@rev`` — a pinned revision.
- ``registry/scope/name`` — an ID qualified with the registry that resolves
  it, Docker-style, e.g. ``charthub.example/acme/rates``.

See the format design doc (``docs_src/design/toml-format-v2.md``) for the
rationale behind this scheme, and "Reserving a future global namespace" in
``docs_src/design/asset-graph.md`` for the registry prefix.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

#: Allowed characters for each component of a pipeline ID.
ID_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class UnsupportedRevisionError(ValueError):
    """Raised when a pipeline reference carries an ``@rev`` suffix.

    The ``scope/name@rev`` grammar is reserved for future version pinning
    and is recognized but not yet supported.
    """


class UnsupportedRegistryError(ValueError):
    """Raised when a pipeline ID or reference carries a registry prefix.

    The ``registry/scope/name`` grammar is reserved for a future registry
    and is recognized but not yet supported.
    """


def looks_like_registry(component: str) -> bool:
    """Tell whether an ID's leading component names a registry, not a scope.

    The rule is Docker's: a component containing ``.`` or ``:``, or equal to
    ``localhost``, is a host. ``charthub.example`` and ``localhost:5000`` are
    registries; ``acme`` is a scope.

    :param component: The leading component of a three-component ID.
    """
    return "." in component or ":" in component or component == "localhost"


def split_registry(pipeline_id: str) -> tuple[Optional[str], str]:
    """Split a registry prefix off a fully qualified pipeline ID.

    A registry-qualified ID has exactly three components,
    ``registry/scope/name``, and its first looks like a host (see
    :func:`looks_like_registry`). Anything else has no registry: a bare
    ``name`` and a ``scope/name`` are returned whole, whatever characters the
    scope contains, so no ID that was valid before the prefix was reserved
    changes meaning.

    :param pipeline_id: A pipeline ID, or a reference that starts with one
        (a trailing ``:asset`` does not affect the split).
    :returns: Tuple of (registry or None, the ID without it).
    """
    parts = pipeline_id.split("/")
    if len(parts) == 3 and looks_like_registry(parts[0]):
        return parts[0], "/".join(parts[1:])
    return None, pipeline_id


def validate_pipeline_id(pipeline_id: str) -> str:
    """Validate a pipeline ID against the ``[scope/]name`` grammar.

    :param pipeline_id: The candidate ID, e.g. ``"ftsfr/crsp_treasury"``
        or a bare ``"crsp_treasury"``.
    :returns: The validated ID, unchanged.
    :raises UnsupportedRegistryError: If the ID is qualified with a registry
        (``registry/scope/name``), which is reserved syntax.
    :raises ValueError: If the ID has more than two components or a
        component contains disallowed characters.
    """
    if not isinstance(pipeline_id, str):
        raise ValueError(f"A pipeline id is a name, like 'acme/rates', not {pipeline_id!r:.40}.")
    registry, unqualified = split_registry(pipeline_id)
    if registry is not None:
        raise UnsupportedRegistryError(
            f"Pipeline id {pipeline_id!r} is qualified with the registry "
            f"{registry!r}. Registry prefixes are reserved syntax and not yet "
            f"supported; use {unqualified!r} instead."
        )
    parts = pipeline_id.split("/")
    if len(parts) > 2 or not all(ID_COMPONENT_PATTERN.match(p) and p not in (".", "..") for p in parts):
        raise ValueError(
            f"Invalid pipeline id {pipeline_id!r}. Expected 'name' or 'scope/name' "
            f"where each component matches [A-Za-z0-9._-]+ and is not '.' or '..'."
        )
    return pipeline_id


def split_rev(ref: str) -> tuple[str, Optional[str]]:
    """Split an ``@rev`` suffix off a pipeline reference.

    URLs are passed through untouched (an ``@`` may be part of ssh syntax).

    :param ref: A pipeline reference, possibly with an ``@rev`` suffix.
    :returns: Tuple of (reference without rev, rev or None).
    """
    if "://" in ref or ref.startswith("git@"):
        return ref, None
    if "@" in ref:
        base, rev = ref.rsplit("@", 1)
        return base, rev or None
    return ref, None


def normalize_ref_to_id(ref: str) -> str:
    """Normalize any accepted pipeline reference form to an ID.

    Accepted forms:

    - ``name`` or ``scope/name`` — returned as-is
    - ``https://github.com/scope/name`` (or any URL) — reduced to the last
      two path segments, with a trailing ``.git`` stripped
    - ``git@github.com:scope/name.git`` — same reduction

    :param ref: The pipeline reference.
    :returns: A bare or scoped pipeline ID.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If the reference is qualified with a
        registry, e.g. ``charthub.example/acme/rates``.
    :raises ValueError: If nothing ID-like can be extracted.
    """
    ref, rev = split_rev(ref.strip())
    if rev is not None:
        raise UnsupportedRevisionError(
            f"Pipeline reference {ref + '@' + rev!r} pins a revision with '@rev'. "
            f"Version pinning is reserved syntax and not yet supported; "
            f"use {ref!r} instead."
        )

    candidate = ref.rstrip("/")
    is_url = False
    if candidate.startswith("git@"):
        candidate = candidate.split(":", 1)[-1]
        is_url = True
    else:
        scheme_match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/]+/(.*)$", candidate)
        if scheme_match:
            candidate = scheme_match.group(1)
            is_url = True

    if candidate.endswith(".git"):
        candidate = candidate[: -len(".git")]

    parts = [p for p in candidate.split("/") if p]
    if not parts:
        raise ValueError(f"Cannot derive a pipeline id from reference {ref!r}.")
    if len(parts) == 1:
        return validate_pipeline_id(parts[0])
    # Only URLs may carry extra leading path segments; a plain reference
    # with more than two components is malformed, not truncatable.
    if len(parts) > 2 and not is_url:
        return validate_pipeline_id(candidate)
    return validate_pipeline_id(f"{parts[-2]}/{parts[-1]}")


# Cache of git remote lookups keyed by resolved directory, since manifests
# for multi-pipeline catalogs are loaded in one pass.
_git_remote_cache: dict[str, Optional[str]] = {}


def _git_environment() -> dict:
    """This process's environment without what tells git where a repository is.

    A ``GIT_DIR`` exported by a hook or a shell would otherwise make git
    answer for that repository, whatever folder it is asked about.
    """
    import os

    from chartbook.gitcache import GIT_LOCATION_VARIABLES

    return {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARIABLES}


def _ask_git(directory: str, *arguments: str) -> Optional[str]:
    """What git prints for a question about a directory, stripped; None if it fails or there is no git."""
    try:
        result = subprocess.run(
            ["git", "-C", directory, *arguments],
            capture_output=True,
            text=True,
            timeout=5,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def get_git_remote_url(base_dir: Path | str) -> Optional[str]:
    """Return the git ``origin`` remote URL for a directory, or None.

    :param base_dir: Directory inside (or at the root of) a git repository.
    :returns: The remote URL string, or None if unavailable.
    """
    key = str(Path(base_dir).resolve())
    if key not in _git_remote_cache:
        _git_remote_cache[key] = _ask_git(key, "config", "--get", "remote.origin.url") or None
    return _git_remote_cache[key]


# Cache of repository tops, keyed as the remote lookups are
_git_top_cache: dict[str, Optional[Path]] = {}


def _same_folder(first: Path | str, second: Path | str) -> bool:
    """Whether two paths are one folder however they are written: a case-insensitive disk may give either spelling."""
    import os

    try:
        return Path(first) == Path(second) or os.path.samefile(first, second)
    except OSError:
        return False


def is_repository_top(base_dir: Path | str) -> bool:
    """Whether a directory is the top folder of a git repository: of a clone, a worktree or a submodule.

    :param base_dir: The directory.
    :returns: False if it is in no repository, or in one's subfolder.
    """
    key = str(Path(base_dir).resolve())
    if key not in _git_top_cache:
        top = _ask_git(key, "rev-parse", "--show-toplevel")
        _git_top_cache[key] = Path(top).resolve() if top else None
    top = _git_top_cache[key]
    return top is not None and _same_folder(top, key)


@dataclass(frozen=True)
class Checkout:
    """Where a folder is in git: which repository, and where in it.

    Attributes:
        common_dir: The repository's own git folder, which its worktrees share.
        first_commit: Its first commit, back from where it is by first
            parents: the same in every full clone. Empty in a shallow one.
        subfolder: The folder within the repository, with ``/`` between its
            parts; empty at the top.
        main: Whether this is the repository's main worktree, not one made
            with ``git worktree add``.
        address: Its ``origin`` remote, reduced by :func:`repository_key`;
            empty when it has none or the remote names no host.
    """

    common_dir: Path
    first_commit: str
    subfolder: str
    main: bool
    address: str = ""


def checkout_of(folder: Path | str) -> Optional[Checkout]:
    """Where a folder is in git; None if it is in no repository."""
    key = str(Path(folder).resolve())
    # The prefix is git's own: a path written in another case on a disk that ignores it is still found in the repository
    answer = _ask_git(
        key, "rev-parse", "--show-toplevel", "--show-prefix", "--git-common-dir", "--git-dir", "--is-shallow-repository"
    )
    lines = answer.splitlines() if answer else []
    if len(lines) != 5:
        return None
    common, own = ((Path(key) / line).resolve() for line in lines[2:4])
    first = ""
    if lines[4] != "true":
        roots = (_ask_git(key, "rev-list", "--max-parents=0", "--first-parent", "HEAD") or "").split()
        first = roots[-1] if roots else ""
    return Checkout(
        common, first, lines[1].strip("/"), _same_folder(common, own), repository_key(get_git_remote_url(key))
    )


def same_pipeline_checked_out(first: Optional[Checkout], second: Optional[Checkout]) -> bool:
    """Whether two folders are one pipeline in two checkouts of one repository, at the same place in it.

    Two worktrees of one repository share its git folder. Two clones are
    one repository as a pin takes one: by the address of their remotes
    where both have one, so that two repositories made from one template
    (one first commit, two addresses) are two; by their first commit where
    either has none.
    """
    if first is None or second is None or first.subfolder != second.subfolder:
        return False
    if _same_folder(first.common_dir, second.common_dir):
        return True
    if first.address and second.address:
        return first.address == second.address
    return bool(first.first_commit and first.first_commit == second.first_commit)


def remote_to_web_url(remote: Optional[str]) -> str:
    """Turn a git remote into the web address of the repository it names.

    A remote is written for git, not for a browser, and may carry things
    that must not be published. This reduces it to ``https://host/path``:

    - ``git@github.com:acme/rates.git`` → ``https://github.com/acme/rates``
    - ``ssh://git@gitlab.internal:2222/acme/rates.git`` → ``https://gitlab.internal/acme/rates``
    - ``https://user:token@github.com/acme/rates.git`` → ``https://github.com/acme/rates``

    Credentials embedded in the remote are always dropped. A remote that is
    a path on disk has no web address and gives an empty string.

    :param remote: The remote URL, as ``git config remote.origin.url`` prints it.
    :returns: A web URL, or ``""`` if the remote does not name a host.
    """
    if not remote:
        return ""
    remote = remote.strip()

    scp_like = re.match(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!/)(.+)$", remote)
    url_like = re.match(
        r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/]*@)?"
        r"(?P<host>[^/:]+)(?P<port>:\d+)?/(?P<path>.+)$",
        remote,
    )
    if url_like and url_like["scheme"].lower() != "file":
        scheme = url_like["scheme"].lower()
        host, path = url_like["host"], url_like["path"]
        if scheme in ("http", "https"):
            # A web port is part of the address; an ssh or git port is not
            host += url_like["port"] or ""
        else:
            scheme = "https"
    elif scp_like and not url_like and "://" not in remote:
        scheme, host, path = "https", scp_like.group(1), scp_like.group(2)
    else:
        return ""

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return f"{scheme}://{host}/{path}" if path else ""


#: Hosts whose repository paths ignore case: ``Acme/Rates`` is ``acme/rates``
_CASE_BLIND_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})


def repository_key(address: Optional[str]) -> str:
    """A repository's address, reduced so that the ways of writing one repository give one key.

    ``git@github.com:Acme/Rates.git``, ``https://github.com/acme/rates/``
    and ``http://github.com:443/acme/rates`` are one repository: the scheme
    is taken as ``https``, the host in lower case with no default port, the
    path with no ``.git`` or final slash, and in lower case for a host that
    ignores its case.

    :returns: The key, or ``""`` for no address or one with no host.
    """
    web = remote_to_web_url(address) if address else ""
    found = re.match(r"^https?://([^/]+)(/.*)?$", web, re.IGNORECASE)
    if not found:
        return ""
    host = re.sub(r":(80|443)$", "", found.group(1).lower())
    path = (found.group(2) or "").rstrip("/")
    if path.lower().endswith(".git"):
        path = path[: -len(".git")]
    if host in _CASE_BLIND_HOSTS:
        path = path.lower()
    return f"https://{host}{path}"


def strip_url_credentials(url: str) -> str:
    """Take any user name and password out of a repository URL.

    For anything that shows or publishes a URL a manifest wrote: an index,
    a warning in a CI log. ``https://user:token@host/…`` becomes
    ``https://host/…``. An ssh URL keeps its user (``ssh://git@host/…``),
    which is part of the address and not a secret, and loses only a
    password. A URL with no scheme (``git@host:acme/rates.git``, a path on
    disk) is returned as it is.

    Unlike :func:`remote_to_web_url`, the result is still the address git
    fetches from.

    :param url: The URL as written.
    :returns: The URL without credentials.
    """
    match = re.match(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<user>[^@/]*)@", url)
    if not match:
        return url
    user = match["user"].split(":", 1)[0]
    keep = f"{user}@" if match["scheme"].lower() not in ("http", "https") else ""
    return f"{match['scheme']}://{keep}{url[match.end():]}"


#: A web address safe to set anywhere in a page: http or https, a host, and
#: none of the characters that end a link, an attribute or a line in
#: Markdown or HTML (no space, quote, angle bracket, parenthesis, square
#: bracket, brace, backtick or backslash).
_WEB_LINK = re.compile(r"[Hh][Tt][Tt][Pp][Ss]?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~:/?#@!$&+,;=%-]*)?", re.ASCII)


#: Characters that print as nothing: Hangul fillers, the blank Braille pattern
_BLANKS = frozenset("\u115f\u1160\u3164\uffa0\u2800")


def plain_line(value: object, longest: int = 10_000) -> str:
    """Text someone else wrote, as one line of what can be seen; empty if nothing can.

    Characters that do not print (controls, format characters, lone
    surrogates) become spaces, and runs of space become one; the text is
    otherwise as written. Text with no character that shows (only spaces,
    fillers or combining marks) is no text. It is read only as far as the
    length kept, so that a long value costs nothing.

    :param longest: Cut to this many characters.
    """
    import unicodedata

    if not isinstance(value, str):
        return ""
    kept: list[str] = []
    space = False
    for c in value:
        if c.isspace() or not c.isprintable():
            space = bool(kept)
            continue
        if space:
            kept.append(" ")
            space = False
        kept.append(c)
        if len(kept) >= longest:
            break
    line = "".join(kept)
    shows = any(not c.isspace() and c not in _BLANKS and not unicodedata.category(c).startswith("M") for c in line)
    return line if shows else ""


def web_link(value: object) -> str:
    """The value if it is a plain web address (``http`` or ``https``), with no credentials; else an empty string.

    For a link whose text someone else wrote, as a pipeline's snapshot in
    the store says where its repository and site are: a ``javascript:``
    link, or one that would break out of the page's markup, is no link.

    :param value: The address as written.
    :returns: The address, or ``""``.
    """
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    address = strip_url_credentials(value.strip())
    return address if _WEB_LINK.fullmatch(address) else ""


def clear_git_remote_cache() -> None:
    """Clear the cached git remote and repository top lookups (mainly for tests)."""
    _git_remote_cache.clear()
    _git_top_cache.clear()


def _sanitize_component(component: str, fallback: str = "pipeline") -> str:
    """Coerce an arbitrary string (e.g. a directory name) into an ID component.

    Derived components are normalized to lowercase snake_case; explicitly
    authored IDs may still use any characters the grammar allows. One with
    nothing left but dots (``_.._``) names no component, and is *fallback*.
    """
    sanitized = component.strip().lower().replace("-", "_").replace(" ", "_")
    sanitized = re.sub(r"[^a-z0-9_.]", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized if sanitized.strip(".") else fallback


def id_from_address(address: str) -> Optional[str]:
    """The ID a pipeline at the top of the repository at an address derives: ``scope/name``, or a bare ``name``.

    The address is a repository's web address or its git remote, in any of
    the forms git takes (``https://``, ``ssh://``, ``user@host:path``,
    ``host:path``), with the host, any user, port and ``.git`` left out:
    ``git@github.com:Acme/CRSP-Treasury.git`` is ``acme/crsp_treasury``. The
    scope is in lowercase and the name is written as a folder's is
    (:func:`_sanitize_component`), so that every way of writing one
    address, on every machine, gives one ID. A remote that is a path on
    disk names no repository, and gives None; so does a name of nothing but
    dots (``_.._``), which names no component.
    """
    scope, name = _address_parts(address) or ("", "")
    if not name:
        return None
    return f"{scope}/{name}" if scope else name


def _address_parts(address: str) -> Optional[tuple[str, str]]:
    """The scope and the name the ID rule takes from a repository's address, each empty if it gives none.

    None for what names no host: a path on disk (``/srv/rates``,
    ``file:///srv/rates``), or a word (``repo_url = "TBD"``).
    """
    web = remote_to_web_url(address)
    if not web:
        return None
    try:
        normalized = normalize_ref_to_id(web)
    except ValueError:
        return None
    scope, _, name = normalized.rpartition("/")
    return scope.lower(), _sanitize_component(name, fallback="")


#: The file :func:`chartbook.snapshot.materialize` writes in a folder it lays a
#: version out in: which pipeline, which commit, when made, and when its code
#: last changed. A folder with it is that pipeline at that version, wherever
#: it is and whatever it is called.
VERSION_FILE = ".chartbook-version.json"


#: More than a version file ever needs; a larger one is not read.
_VERSION_FILE_MAX_BYTES = 64 * 1024


def read_version_file(base_dir: Path | str) -> dict:
    """What a laid-out version's :data:`VERSION_FILE` says; empty unless the folder is one.

    A folder is a laid-out version when it has the file and is not a
    repository's own folder: no ``.git`` in it, and the file not tracked by
    git. A laid-out folder copied to start a new pipeline and committed is
    that new pipeline, not the old version. A file too large, or not a JSON
    object, is not read.
    """
    import os

    base = Path(base_dir)
    marker = base / VERSION_FILE
    try:
        if not marker.is_file() or marker.is_symlink() or marker.stat().st_size > _VERSION_FILE_MAX_BYTES:
            return {}
        if os.path.lexists(base / ".git"):
            return {}
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(recorded, dict) or _tracked_by_git(base, VERSION_FILE):
        return {}
    return recorded


def _tracked_by_git(base: Path, name: str) -> bool:
    """Whether git tracks a file in a folder; False where there is no git or no repository."""
    try:
        result = subprocess.run(
            ["git", "-C", str(base), "ls-files", "--error-unmatch", "--", name],
            capture_output=True,
            text=True,
            timeout=15,
            env={**_git_environment(), "GIT_OPTIONAL_LOCKS": "0", "GIT_LITERAL_PATHSPECS": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def derive_pipeline_id(project: dict, base_dir: Path | str) -> str:
    """Derive a pipeline's canonical ID.

    Precedence:

    1. Explicit ``id`` in the ``[project]`` table.
    2. The pipeline a laid-out version's :data:`VERSION_FILE` names.
    3. With a repository address, ``repo_url`` or else the git ``origin``
       remote, the scope from it (:func:`id_from_address`); and the name
       from it too when the directory is the top of its git repository,
       else the directory's name. So a clone, a git worktree or a renamed
       folder of one repository is one pipeline, whatever its folder is
       called, and each pipeline in a repository's subfolders is named by
       its subfolder. A ``repo_url`` comes first, so a fork whose
       manifest names its upstream keeps the upstream's ID.
    4. Bare directory name.

    A name is lowercase snake_case, from the folder or from the remote:
    ``first-pipeline`` is ``first_pipeline``; a scope is in lowercase.

    :param project: The raw ``[project]`` table from chartbook.toml.
    :param base_dir: The pipeline's root directory.
    :returns: A validated bare or scoped pipeline ID.
    """
    explicit = project.get("id", "")
    if explicit:
        return validate_pipeline_id(explicit)
    recorded = read_version_file(base_dir).get("pipeline")
    if isinstance(recorded, str) and recorded:
        try:
            return validate_pipeline_id(recorded)
        except ValueError:
            pass  # not an ID: the folder's own name, as for any folder

    # Resolved, because the name comes from the directory's own name and a
    # relative "." does not have one
    base_dir = Path(base_dir).resolve()
    name_part = _sanitize_component(base_dir.name)

    # A repo_url that names no host ("TBD") gives way to the remote
    written = project.get("repo_url", "")
    parts = _address_parts(written) if isinstance(written, str) and written else None
    if parts is None:
        remote = get_git_remote_url(base_dir)
        parts = _address_parts(remote) if remote else None
    if parts is not None:
        scope, repository_name = parts
        if repository_name and is_repository_top(base_dir):
            # The pipeline is the repository: named as the repository is,
            # not as the folder this copy of it happens to be in
            name_part = repository_name
        if scope:
            return validate_pipeline_id(f"{scope}/{name_part}")

    return validate_pipeline_id(name_part)


#: A reference in git's short form for a remote, ``[user@]host:path``: a host
#: with a dot in it, or a user, so that neither a name with a colon nor a
#: registry's port (``localhost:5000/acme/rates``) reads as one
_SCP_REFERENCE = re.compile(r"^(?:[^@/:\s]+@[^:/\s]+|[^@:/\s]*\.[^@:/\s]+):(?!/)(?![0-9]+(?:/|$)).+$")


def in_another_case(keys: Iterable[str], ref: str) -> Optional[str]:
    """The one ID among *keys* that a reference names but for the case of its letters; None if none, or several.

    A scope derived from a remote is in lowercase, so a reference written as
    a web page shows its owner (``Acme/rates``) misses it: this is what to
    suggest.
    """
    wanted = ref.strip().casefold()
    found = sorted({key for key in keys if key.casefold() == wanted and key != ref.strip()})
    return found[0] if len(found) == 1 else None


def match_pipeline_ref(
    keys: Iterable[str], ref: str, where: str = "this catalog"
) -> Optional[str]:
    """Match a user-supplied pipeline reference against a set of pipeline IDs.

    Matching order:

    1. Exact match on the (possibly scoped) key.
    2. URL references are normalized to ``scope/name`` and matched exactly,
       as written and then as the ID rule derives one from the address
       (:func:`id_from_address`): ``https://github.com/ftsfr/crsp-treasury``
       matches ``ftsfr/crsp_treasury``.
    3. A bare name matches any key whose name component equals it — but only
       if exactly one does; multiple matches raise an error listing the
       candidates.

    Finding nothing is not an error here, so that a caller with somewhere
    else to look can go on to it. :func:`resolve_pipeline_ref` is this
    function for a caller with nowhere else.

    :param keys: The pipeline IDs to match against: a catalog's keys, or
        those of a ``[dependencies]`` table.
    :param ref: The reference to match (bare, scoped, or URL).
    :param where: What *keys* are the keys of, to say where a name is
        ambiguous.
    :returns: The matching key, or None if there is none.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If the reference carries a registry
        prefix.
    :raises KeyError: If a bare name matches more than one key.
    """
    keys = list(keys)
    stripped = ref.strip()
    # A remote in git's short form, with any user or none
    # (`org-123@github.com:acme/rates.git`), is read as its web address
    scp = _SCP_REFERENCE.match(stripped)
    normalized = normalize_ref_to_id(remote_to_web_url(stripped) if scp else ref)

    if normalized in keys:
        return normalized
    # A repository's address names the pipeline at its top as the ID rule
    # does: `.../ftsfr/crsp-treasury` is `ftsfr/crsp_treasury`
    if scp or "://" in stripped or stripped.startswith("git@"):
        derived = id_from_address(stripped)
        if derived in keys:
            return derived

    if "/" not in normalized:
        matches = [k for k in keys if k.rsplit("/", 1)[-1] == normalized]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(
                f"Pipeline reference {ref!r} is ambiguous in {where}. "
                f"Matching pipelines: {sorted(matches)}. "
                f"Use the scoped form, e.g. {matches[0]!r}."
            )
    return None


def resolve_pipeline_ref(keys: Iterable[str], ref: str) -> str:
    """Resolve a user-supplied pipeline reference against catalog keys.

    The matching rules are :func:`match_pipeline_ref`'s.

    :param keys: The catalog's pipeline keys.
    :param ref: The reference to resolve (bare, scoped, or URL).
    :returns: The matching catalog key.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If the reference carries a registry
        prefix.
    :raises KeyError: If no key matches, or a bare name is ambiguous.
    """
    keys = list(keys)
    matched = match_pipeline_ref(keys, ref)
    if matched is None:
        other = in_another_case(keys, ref)
        hint = f" Did you mean {other!r}? A scope derived from a remote is in lowercase." if other else ""
        raise KeyError(
            f"Pipeline {ref!r} not found in catalog.{hint} "
            f"Available pipelines: {sorted(keys)}"
        )
    return matched
