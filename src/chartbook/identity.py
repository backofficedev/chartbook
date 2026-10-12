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

import re
import subprocess
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
    registry, unqualified = split_registry(pipeline_id)
    if registry is not None:
        raise UnsupportedRegistryError(
            f"Pipeline id {pipeline_id!r} is qualified with the registry "
            f"{registry!r}. Registry prefixes are reserved syntax and not yet "
            f"supported; use {unqualified!r} instead."
        )
    parts = pipeline_id.split("/")
    if len(parts) > 2 or not all(ID_COMPONENT_PATTERN.match(p) for p in parts):
        raise ValueError(
            f"Invalid pipeline id {pipeline_id!r}. Expected 'name' or 'scope/name' "
            f"where each component matches [A-Za-z0-9._-]+."
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


def get_git_remote_url(base_dir: Path | str) -> Optional[str]:
    """Return the git ``origin`` remote URL for a directory, or None.

    :param base_dir: Directory inside (or at the root of) a git repository.
    :returns: The remote URL string, or None if unavailable.
    """
    key = str(Path(base_dir).resolve())
    if key in _git_remote_cache:
        return _git_remote_cache[key]

    url: Optional[str] = None
    try:
        result = subprocess.run(
            ["git", "-C", key, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = None

    _git_remote_cache[key] = url
    return url


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


def clear_git_remote_cache() -> None:
    """Clear the cached git remote lookups (mainly for tests)."""
    _git_remote_cache.clear()


def _sanitize_component(component: str) -> str:
    """Coerce an arbitrary string (e.g. a directory name) into an ID component.

    Derived components are normalized to lowercase snake_case; explicitly
    authored IDs may still use any characters the grammar allows.
    """
    sanitized = component.strip().lower().replace("-", "_").replace(" ", "_")
    sanitized = re.sub(r"[^a-z0-9_.]", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "pipeline"


def derive_pipeline_id(project: dict, base_dir: Path | str) -> str:
    """Derive a pipeline's canonical ID.

    Precedence:

    1. Explicit ``id`` in the ``[project]`` table.
    2. Scope from the git ``origin`` remote (or ``repo_url``), name from the
       directory name.
    3. Bare directory name.

    :param project: The raw ``[project]`` table from chartbook.toml.
    :param base_dir: The pipeline's root directory.
    :returns: A validated bare or scoped pipeline ID.
    """
    explicit = project.get("id", "")
    if explicit:
        return validate_pipeline_id(explicit)

    base_dir = Path(base_dir)
    name_part = _sanitize_component(base_dir.name)

    source_url = project.get("repo_url", "") or get_git_remote_url(base_dir)
    if source_url:
        try:
            normalized = normalize_ref_to_id(source_url)
        except ValueError:
            normalized = None
        if normalized and "/" in normalized:
            scope = normalized.split("/", 1)[0]
            return f"{scope}/{name_part}"

    return name_part


def resolve_pipeline_ref(keys: Iterable[str], ref: str) -> str:
    """Resolve a user-supplied pipeline reference against catalog keys.

    Resolution order:

    1. Exact match on the (possibly scoped) key.
    2. URL references are normalized to ``scope/name`` and matched exactly.
    3. A bare name matches any key whose name component equals it — but only
       if exactly one does; multiple matches raise an error listing the
       candidates.

    :param keys: The catalog's pipeline keys.
    :param ref: The reference to resolve (bare, scoped, or URL).
    :returns: The matching catalog key.
    :raises UnsupportedRevisionError: If the reference carries ``@rev``.
    :raises UnsupportedRegistryError: If the reference carries a registry
        prefix.
    :raises KeyError: If no key matches, or a bare name is ambiguous.
    """
    keys = list(keys)
    normalized = normalize_ref_to_id(ref)

    if normalized in keys:
        return normalized

    if "/" not in normalized:
        matches = [k for k in keys if k.rsplit("/", 1)[-1] == normalized]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise KeyError(
                f"Pipeline reference {ref!r} is ambiguous in this catalog. "
                f"Matching pipelines: {sorted(matches)}. "
                f"Use the scoped form, e.g. {matches[0]!r}."
            )

    raise KeyError(
        f"Pipeline {ref!r} not found in catalog. Available pipelines: {sorted(keys)}"
    )
