"""Settings: where this machine keeps things, read in layers.

Three files, and the environment above them:

- the user's ``~/.chartbook/settings.toml``;
- the organization's system-wide file, ``/etc/chartbook/settings.toml``
  on Unix and macOS, ``%ProgramData%\\chartbook\\settings.toml`` on Windows,
  or the file ``CHARTBOOK_SYSTEM_SETTINGS`` names;
- the defaults under ``~/.chartbook``.

Each layer is consulted only where the one above it is silent, key by
key, so an organization sets the store once for every machine and a user
keeps their own choices for everything else::

    ~/.chartbook/
    ├── chartbook.toml       # the global catalog (optional)
    ├── settings.toml        # the user's settings
    ├── sources.toml         # the machine's urls and credentials for [sources]
    ├── trust.toml           # the pipelines and repositories this user trusts a build of
    ├── machine-id           # what names this machine in a store's notes of lockfiles
    ├── store/               # the store, unless settings say otherwise
    ├── cache/               # what was read from a remote store
    └── git/                 # clones of git dependencies

``[store] url`` says where the store is: a folder (a bare path or
``file:///``), an S3 bucket (``s3://bucket/prefix``, with
``pip install chartbook[s3]``), or another kind of store a plugin provides,
by its scheme. ``CHARTBOOK_STORE`` overrides it. ``[git] path`` and
``CHARTBOOK_GIT_CACHE`` do the same for the git cache, ``[cache] path`` and
``CHARTBOOK_CACHE`` for the cache of a remote store; ``[catalog] path``
names the default catalog. Which store a machine uses is never a fact
about a pipeline, so none of this is in a ``chartbook.toml``.
"""

import functools
import json
import os
import re
import warnings
from pathlib import Path
from typing import Optional

import tomli
import tomli_w

#: The environment variable that says where the store is, when it is set.
STORE_ENV_VAR = "CHARTBOOK_STORE"
#: Names the organization's settings file, read where the user's is silent.
SYSTEM_SETTINGS_ENV_VAR = "CHARTBOOK_SYSTEM_SETTINGS"

#: The environment variable that says where git dependencies are fetched to.
GIT_CACHE_ENV_VAR = "CHARTBOOK_GIT_CACHE"
#: The environment variable that says where a remote store's objects are kept once read.
CACHE_ENV_VAR = "CHARTBOOK_CACHE"
#: Set by a catalog build for the build of a version laid out from the store, whose files
#: anyone who can write the store may have written: see :func:`untrusted_source`.
UNTRUSTED_ENV_VAR = "CHARTBOOK_UNTRUSTED_SOURCE"


def untrusted_source() -> bool:
    """Whether this build is of files that came from a store, not from a folder of the user's.

    Such a build uses no template from the project's folder, copies only
    pages and pictures of its site folder, and lets no page take in a file
    from outside the site (``docs_src/design/versioned-catalog.md``).
    """
    return os.environ.get(UNTRUSTED_ENV_VAR, "").strip() == "1"


def get_global_config_dir() -> Path:
    """Return the global chartbook config directory.

    :returns: ``~/.chartbook`` (works on Windows, macOS, and Linux).
    :rtype: Path
    """
    return Path.home() / ".chartbook"


def get_global_catalog_path() -> Path:
    """Return the path to the default global catalog.

    :returns: ``~/.chartbook/chartbook.toml``
    :rtype: Path
    """
    return get_global_config_dir() / "chartbook.toml"


def get_global_artifacts_dir() -> Path:
    """Return the path to the global artifacts directory.

    :returns: ``~/.chartbook/artifacts/``
    :rtype: Path
    """
    return get_global_config_dir() / "artifacts"


def get_global_docs_dir() -> Path:
    """Return the path to the global rendered docs directory.

    :returns: ``~/.chartbook/docs/``
    :rtype: Path
    """
    return get_global_config_dir() / "docs"


def get_global_settings_path() -> Path:
    """Return the path to the global settings file.

    :returns: ``~/.chartbook/settings.toml``
    :rtype: Path
    """
    return get_global_config_dir() / "settings.toml"


def read_global_settings() -> dict:
    """Read the user's settings file, ``~/.chartbook/settings.toml``.

    :returns: The parsed settings dictionary, or ``{}`` if the file does not exist.
    :rtype: dict
    """
    return _read_toml(get_global_settings_path(), "the user's settings")


def get_system_settings_path() -> Path:
    """The organization's settings file, which every user on the machine shares.

    ``CHARTBOOK_SYSTEM_SETTINGS`` if it is set; otherwise
    ``/etc/chartbook/settings.toml`` on Unix and macOS, and
    ``%ProgramData%\\chartbook\\settings.toml`` on Windows.
    """
    named = os.environ.get(SYSTEM_SETTINGS_ENV_VAR, "").strip()
    if named:
        return Path(named).expanduser()
    if os.name == "nt":
        base = os.environ.get("ProgramData") or r"C:\ProgramData"
        return Path(base) / "chartbook" / "settings.toml"
    return Path("/etc/chartbook/settings.toml")


def read_system_settings() -> dict:
    """Read the organization's settings file, or ``{}`` if there is none.

    A file that is named and not there, or that cannot be read or parsed,
    is reported with a warning and treated as absent: a fault in the
    organization's file must not stop every command on the machine.
    """
    path = get_system_settings_path()
    named = bool(os.environ.get(SYSTEM_SETTINGS_ENV_VAR, "").strip())
    try:
        return _read_toml(path, "the organization's settings", required=named)
    except ValueError as error:
        warnings.warn(f"{error} It is ignored.", stacklevel=2)
        return {}


def read_settings() -> dict:
    """The settings in force: the user's over the organization's, key by key.

    Each layer is consulted only where the one above it is silent. Within
    a table such as ``[store]``, the user's keys are added to the
    organization's, so an organization can set the store for every machine
    and a user can still choose everything else. Each layer is put in
    order first (:func:`_normalized`): a deprecated spelling is read as the
    current one, and a relative folder is made absolute against the file
    it is in, so that a key the user set is never shadowed by the same
    setting spelled differently below it. The environment variables
    (``CHARTBOOK_STORE``, ``CHARTBOOK_GIT_CACHE``) sit above both and are
    read by the functions that need them.

    :raises ValueError: If the user's file cannot be read or parsed, or a
        table in it is malformed; the message names the file.
    """
    try:
        merged = _normalized(read_system_settings(), get_system_settings_path())
    except ValueError as error:
        # The organization's file is one file for every user on the machine:
        # a fault in it is said, and must not stop every command
        warnings.warn(f"{error} It is ignored.", stacklevel=2)
        merged = {}
    for key, value in _normalized(read_global_settings(), get_global_settings_path()).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def _normalized(settings: dict, origin: Path) -> dict:
    """One layer's settings, put in order, with every fault named after its file.

    ``[store] path`` is read as ``[store] url`` with a warning. A ``url``
    or ``path`` that is a relative folder is made absolute against the
    folder the settings file is in, not against wherever the command
    happens to run. A table that is not a table, or a ``[store]`` with no
    usable ``url``, is a fault of that file.

    :raises ValueError: Naming *origin*.
    """
    result: dict = {}
    for key, value in settings.items():
        result[key] = dict(value) if isinstance(value, dict) else value
    for table in ("store", "git", "cache", "catalog", "resolve"):
        if table in result and not isinstance(result[table], dict):
            raise ValueError(
                f"{origin}: [{table}] must be a table, e.g. [{table}] with "
                f"{'url' if table == 'store' else 'path'} = \"...\"."
            )
    store = result.get("store")
    if store is not None:
        url = store.get("url")
        if not (isinstance(url, str) and url.strip()):
            path = store.get("path")
            if isinstance(path, str) and path.strip():
                warnings.warn(
                    f"{origin}: [store] path is now [store] url. It is read as a folder this once; "
                    f"rename the key.",
                    stacklevel=3,
                )
                url = path
            else:
                raise ValueError(
                    f"{origin}: [store] needs a 'url', e.g. url = \"/a/bigger/disk/chartbook-store\"."
                )
        store.pop("path", None)
        store["url"] = _absolute_if_folder(url.strip(), origin)
    git = result.get("git")
    if git is not None:
        path = git.get("path")
        if not (isinstance(path, str) and path.strip()):
            raise ValueError(f"{origin}: [git] needs a 'path', e.g. path = \"/a/bigger/disk/chartbook-git\".")
        git["path"] = str(_absolute_if_folder(path.strip(), origin))
    cache = result.get("cache")
    if cache is not None:
        path = cache.get("path")
        if not (isinstance(path, str) and path.strip()):
            raise ValueError(f"{origin}: [cache] needs a 'path', e.g. path = \"/a/bigger/disk/chartbook-cache\".")
        cache["path"] = str(_absolute_if_folder(path.strip(), origin))
    catalog = result.get("catalog")
    if catalog is not None and "path" in catalog:
        path = catalog["path"]
        if not isinstance(path, str):
            raise ValueError(
                f"{origin}: [catalog] path must be a string, e.g. path = \"~/catalogs/rates/chartbook.toml\"."
            )
        if path.strip():
            # As the store, the git cache and the cache are: relative to the
            # settings file, not to wherever the command happens to be run
            catalog["path"] = str(_absolute_if_folder(path.strip(), origin))
    resolve = result.get("resolve")
    if resolve is not None and "default_host" in resolve:
        host = resolve["default_host"]
        if not isinstance(host, str) or host.strip().startswith("-"):
            raise ValueError(
                f"{origin}: [resolve] default_host must be a git host, e.g. default_host = \"github.com\", "
                f"an address its repositories are under, e.g. \"https://gitlab.example.org/group\", "
                f"or \"\" for none."
            )
        host = host.strip()
        if not re.match(r"^([A-Za-z]:)?[\\/]$", host):
            host = host.rstrip("/\\")  # but a root folder, / or C:\\, keeps its separator
        if _is_folder(host):
            host = str(_absolute_if_folder(os.path.expanduser(host), origin))  # a folder of repositories
        resolve["default_host"] = host
    return result


def _absolute_if_folder(url: str, origin: Path) -> str:
    """A folder URL made absolute against the settings file's own folder; another URL as it is."""
    if store_kind(url) != "folder":
        return url
    try:
        expanded = Path(_folder_text(url)).expanduser()
    except RuntimeError:  # ~someone, for a user this machine does not know
        raise ValueError(f"{origin}: {url!r} names a user this machine does not know.") from None
    if not expanded.is_absolute():
        expanded = origin.parent / expanded
    return str(Path(os.path.abspath(expanded)))


def _folder_text(url: str) -> str:
    """The path inside a folder URL: the text itself, or what follows ``file://``.

    :raises ValueError: For ``file://host/...``: a file store is a folder on
        this machine, and a host is not read as a relative path by mistake.
    """
    text = url.strip()
    if not text.lower().startswith("file://"):
        return text
    text = text[len("file://"):]
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", text):
        text = text[1:]  # file:///C:/x names the drive, not a root folder
    if text and not text.startswith("/") and os.name != "nt":
        raise ValueError(
            f"The store {shown_store_url(url)!r} names a host; a file:// store is a folder on this machine, "
            f"written file:///path. For a folder on a shared drive, mount it and give its path."
        )
    return text


def _read_toml(path: Path, what: str, required: bool = False) -> dict:
    """Read one settings file, or ``{}`` if it is not there.

    :param what: The file's role, for a message: "the user's settings".
    :param required: Whether its absence is a fault (the file was named
        explicitly).
    :raises ValueError: Naming the file, when it cannot be read or parsed,
        or is named and not there.
    """
    if not path.is_file():
        if required:
            raise ValueError(f"{path}, named as {what}, is not a file.")
        return {}
    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except tomli.TOMLDecodeError as error:
        raise ValueError(f"{path}, {what}, is not valid TOML: {error}.") from None
    except OSError as error:
        raise ValueError(f"{path}, {what}, cannot be read: {error.strerror or error}.") from None


def get_default_catalog_path() -> Optional[Path]:
    """Get the default catalog path.

    Resolution order:

    1. ``catalog.path`` from ``~/.chartbook/settings.toml`` (explicit override).
    2. ``~/.chartbook/chartbook.toml`` if it exists (global catalog).
    3. ``None`` if neither is available.

    :returns: The resolved catalog path, or ``None`` if not found.
    :rtype: Optional[Path]
    """
    settings = read_settings()
    raw = (settings.get("catalog") or {}).get("path")
    if raw:
        return Path(raw)

    # Fall back to the global catalog if it exists
    global_catalog = get_global_catalog_path()
    if global_catalog.is_file():
        return global_catalog

    return None


def get_store_url() -> str:
    """Where the store is, as the settings say it: a folder, or a URL.

    The store is a setting of the machine or the organization, never of a
    pipeline, so it is read in layers, each only where the one above it is
    silent:

    1. The ``CHARTBOOK_STORE`` environment variable, for one shell or one
       CI job.
    2. ``[store] url`` in the user's ``~/.chartbook/settings.toml``.
    3. ``[store] url`` in the organization's settings file
       (:func:`get_system_settings_path`).
    4. ``~/.chartbook/store``.

    A bare path is a folder. ``file://`` is a folder too. ``s3://`` is a
    bucket, with ``pip install chartbook[s3]``; another scheme names a kind
    of store a plugin provides. ``[store] path`` is still read, as a
    folder, with a warning. A
    relative folder in a settings file is relative to that file's folder.

    :raises ValueError: If the user's settings file is faulty; a fault in
        the organization's file is a warning, and that file is ignored.
    """
    return get_store_setting()[0]


def get_store_setting() -> tuple[str, str]:
    """Where the store is (:func:`get_store_url`), and which layer said so.

    :returns: The URL, and where it came from: ``"environment"``
        (``CHARTBOOK_STORE``), ``"user"`` (``[store] url`` in the user's
        settings file), ``"system"`` (in the organization's), or
        ``"default"``.
    :raises ValueError: If the user's settings file is faulty.
    """
    from_environment = os.environ.get(STORE_ENV_VAR, "").strip()
    if from_environment:
        return from_environment, "environment"
    configured = read_settings().get("store")
    if configured is not None:
        # The user's own file, if it sets the store; the organization's
        # otherwise. Read again only to say which: what it warns of was said
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            user = _normalized(read_global_settings(), get_global_settings_path()).get("store")
        return configured["url"], "user" if user is not None else "system"
    return str(get_global_config_dir() / "store"), "default"


def shown_store_url(url: str) -> str:
    """A store URL as it may be printed: with no user name or password in it, nor in a URL among its options.

    ``s3://user:secret@b/p?endpoint=https://u:pw@minio.example.org`` is
    shown as ``s3://b/p?endpoint=…``. A password may hold any character
    (half of AWS's secret keys have a ``/``; others a ``?``, an ``&``, a
    ``#``), so all up to the last ``@`` of the URL goes, read as written
    (``%40`` is an ``@``), and no option's value is shown at all, since a
    password in one may hold what would end it. The options are what
    follows a ``?`` that a name and an ``=`` follow. A path with no
    ``//host`` part (two backslashes on Windows) is as it is: a folder's path
    may hold an ``@``, as a Google Drive folder names its account.
    """
    from urllib.parse import unquote

    def bare(text: str) -> str:
        text = unquote(text)
        match = re.match(_ADDRESS, text)
        if match:
            return match.group(0).strip() + text[match.end():].rpartition("@")[2]
        return text.rpartition("@")[2]

    main, *rest = re.split(r"\?(?=[A-Za-z_][A-Za-z0-9_]*=)", url, maxsplit=1)
    if re.match(_ADDRESS, main):
        main = bare(main)
    if not rest:
        return main
    options = re.split(r"&(?=[A-Za-z_][A-Za-z0-9_]*=)", rest[0])
    return f"{main}?" + "&".join(f"{key}=…" for key, _, _ in (o.partition("=") for o in options))


def without_credentials(text: str) -> str:
    """A message with no user name or password of any URL or ``//host`` path in it: ``scheme://user:pass@`` becomes ``scheme://``.

    For what an SDK or the system says, which may echo an address or a path
    it was given: an ``OSError`` names its file, and a store at
    ``//user:pass@host/share`` is one, as is the path Windows makes of it,
    which begins with two backslashes (four, in a message that quotes it). All up to the last ``@`` of a line that has an address
    goes, since a password may hold a space or a quote.
    """
    return re.sub(_ADDRESS_IN_TEXT, r"\1", text)


#: Where a URL, or a path to another host, begins: ``scheme://``, ``//``, or Windows' two backslashes.
_ADDRESS = r"^\s*(?:(?:[A-Za-z][A-Za-z0-9+.-]*:)?//|\\\\)"

#: The same in a message, up to the first ``@`` with no space or quote before
#: it, so that a message quoting an address and then an ``'@'`` keeps its
#: words. Two backslashes (four, quoted) only where a path begins: those after
#: ``C:`` begin none
_ADDRESS_IN_TEXT = r"((?:[A-Za-z][A-Za-z0-9+.-]*:)?//|(?<![^\s'\"(=])\\\\(?:\\\\)?)[^\s'\"<>]*?@"


def store_kind(url: str) -> str:
    """The kind of store a URL names: ``folder`` for a path or ``file://``, else its scheme."""
    text = url.strip()
    scheme, sep, rest = text.partition("://")
    # A scheme as RFC 3986 has it; two letters at least, so that a Windows
    # drive letter is a path
    if sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]+", scheme):
        return "folder" if scheme.lower() == "file" else scheme.lower()
    return "folder"


def folder_of_store_url(url: str) -> Path:
    """The absolute folder a folder-kind store URL names.

    :raises ValueError: If the URL names another kind of store.
    """
    kind = store_kind(url)
    if kind != "folder":
        raise ValueError(
            f"The store {shown_store_url(url)!r} is a {kind}:// store, and this needs a folder: only a folder "
            f"store is built in; another kind is a plugin, found by `chartbook.store.store_for_url()`."
        )
    try:
        return Path(os.path.abspath(Path(_folder_text(url)).expanduser()))
    except RuntimeError:
        raise ValueError(f"The store {shown_store_url(url)!r} names a user this machine does not know.") from None


def get_store_path() -> Path:
    """The directory of the store, when it is a folder: the local folder of pinned files.

    See :func:`get_store_url` for how it is found. The directory need not
    exist yet.

    :returns: The absolute path of the store.
    :rtype: Path
    :raises ValueError: If the settings name a kind of store that is not
        built, or ``[store]`` is malformed.
    """
    return folder_of_store_url(get_store_url())


#: The file under ``~/.chartbook`` that names this machine to the stores it uses.
MACHINE_FILE = "machine-id"
#: The environment variable that names this machine instead, for one that comes and goes.
MACHINE_ENV_VAR = "CHARTBOOK_MACHINE_ID"


def get_machine_id(create: bool = True) -> str:
    """The name this machine goes by in a store's notes of its lockfiles.

    A store keeps a note of each lockfile whose pins it keeps, and a path
    names a file on one machine only: one person's two machines can each
    have a lockfile at the same path. So a note names its machine too.

    The name is made at random the first time a note is written, and kept
    in ``~/.chartbook/machine-id`` beside what the operating system calls
    the machine (:func:`_os_machine_identity`, as a hash). A home folder
    that comes to another machine (copied by a migration or restored from
    a backup, shared by several computers, kept by a sync service) does
    not bring its name with it: that machine makes one of its own, kept in
    the same file. So does a cloned virtual machine or an image that had
    pinned, when its operating system made its identity anew. One that did
    not (``/etc/machine-id`` cloned, Windows without sysprep), with a copied
    home, has the same name as the machine it was cloned from, and the two
    are not told apart: each lasting machine needs an identity of its own,
    or a ``CHARTBOOK_MACHINE_ID`` of its own. Nothing else (the host name,
    a hardware address) tells machines apart, as one machine's may change.
    Where nothing can be kept, or there is no home folder, a name made from
    what the operating system calls the machine is used.

    ``CHARTBOOK_MACHINE_ID`` names it instead: for machines that come and
    go with a fresh home folder each time (CI runners, containers), so
    that each one's notes replace the last one's rather than pile up. Two
    machines that last must never be given one name: each would read the
    other's lockfiles as its own.

    :param create: Whether to make the name if there is none yet. Without
        it, the name used where nothing can be kept is given, which only a
        machine that could not keep a name of its own wrote notes under.
    """
    import uuid

    named = os.environ.get(MACHINE_ENV_VAR, "").strip()
    if named:
        return named
    path, identity, unkept = _machine_file()
    if path is None:
        return unkept  # no home folder to keep a name in
    # Worked out once a process: the name of a note's file and the name in it are one
    if (str(path), identity) in _machine_names:
        return _machine_names[(str(path), identity)]
    found = _kept_machines(path).get(identity)
    if found is not None:
        _machine_names[(str(path), identity)] = found
        return found
    if not create:
        return unkept
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{MACHINE_FILE}.{uuid.uuid4().hex}.tmp")
        try:
            if not path.exists():
                temporary.write_text(json.dumps({"machines": {identity: uuid.uuid4().hex}}) + "\n", encoding="utf-8", newline="\n")
                try:
                    # The first of two made at once is the one: a link is not made over a file
                    os.link(temporary, path)
                except FileExistsError:
                    pass
                except OSError:
                    # A disk with no links: made only where there is none, so the first still wins
                    try:
                        with open(path, "x", encoding="utf-8", newline="\n") as f:
                            f.write(temporary.read_text(encoding="utf-8"))
                    except FileExistsError:
                        pass
            if identity not in _kept_machines(path):
                # A home this machine came to with another's name in it: one of its own beside it
                _keep_machine(path, identity, uuid.uuid4().hex)
        finally:
            if temporary.exists():
                temporary.unlink()
    except OSError:
        pass
    found = _kept_machines(path).get(identity)
    if found is None:
        return unkept
    _machine_names[(str(path), identity)] = found
    return found


#: The name this machine goes by, by its ``machine-id`` file and its identity, once worked out in this process.
_machine_names: dict = {}


def _machine_file() -> tuple:
    """The ``machine-id`` file (None with no home folder), this machine's identity in it, and the name used where none can be kept."""
    import hashlib
    import uuid

    identity = hashlib.sha256(_os_machine_identity().encode("utf-8")).hexdigest()[:32]
    unkept = uuid.uuid5(uuid.NAMESPACE_URL, f"chartbook-machine:{identity}").hex
    try:
        return get_global_config_dir() / MACHINE_FILE, identity, unkept
    except (RuntimeError, KeyError, OSError):
        return None, identity, unkept


def _kept_machines(path: Path) -> dict:
    """The names a ``machine-id`` file keeps, by machine identity; empty if it cannot be read."""
    try:
        machines = json.loads(path.read_text(encoding="utf-8")).get("machines")
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(machines, dict):
        return {}
    return {k: v for k, v in machines.items() if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{32}", v)}


def _keep_machine(path: Path, identity: str, name: str) -> None:
    """Keep a name for one machine identity in a ``machine-id`` file, whole or not at all."""
    import uuid

    temporary = path.with_name(f"{MACHINE_FILE}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"machines": {**_kept_machines(path), identity: name}}, indent=1) + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@functools.lru_cache(maxsize=None)
def _os_machine_identity() -> str:
    """What the operating system calls this machine, asked once a process.

    The hardware's UUID on macOS (``ioreg``), ``/etc/machine-id`` (or
    D-Bus's) on Linux, ``MachineGuid`` in the registry on Windows; the
    host's name where none of these gives one (``uninitialized``, as a
    Linux image may have it, is none). A virtual machine cloned without
    making its identity anew (``/etc/machine-id``, or Windows without
    sysprep) has the identity of the one it was cloned from, and is not
    told apart from it.
    """
    import socket
    import subprocess
    import sys

    try:
        if sys.platform == "darwin":
            # By its full path: cron's PATH does not have /usr/sbin
            found = subprocess.run(
                ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
            ).stdout
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', found)
            if match and _an_identity(match.group(1)):
                return f"darwin:{match.group(1).lower()}"
        elif os.name == "nt":
            import winreg

            access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
                guid = str(winreg.QueryValueEx(key, "MachineGuid")[0])
            if _an_identity(guid):
                return f"windows:{guid.lower()}"
        else:
            for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    text = Path(candidate).read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                # Not "uninitialized", as systemd leaves it before a first boot, nor anything else not one
                if re.fullmatch(r"[0-9a-f]{32}", text) and _an_identity(text):
                    return f"linux:{text}"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return f"host:{socket.gethostname()}"


def _an_identity(text: str) -> bool:
    """Whether what the operating system gave is a machine's identity: hex digits (and dashes), not all zeros."""
    digits = text.replace("-", "")
    return len(digits) >= 32 and bool(re.fullmatch(r"[0-9A-Fa-f]+", digits)) and set(digits) != {"0"}


#: The file under ``~/.chartbook`` that records which pipelines this user trusts a build of.
TRUST_FILE = "trust.toml"
#: ``all`` trusts every folder at ``run``: for the test suite, or a container
#: that is nothing but your own code. No other value is read.
TRUST_ENV_VAR = "CHARTBOOK_TRUST"
#: The levels of trust, lowest first. ``render``: queries run for glimpses and
#: the index, and the files the manifest names are read wherever they are.
#: ``run``: the build script runs too.
TRUST_LEVELS = ("render", "run")

_TRUST_HEADER = """\
# Pipelines you have trusted (chartbook trust): their queries and build scripts run here, and the
# files their manifests name are read wherever they are. A [[pipeline]] entry covers its folder and
# the folders inside it; a [[repository]] entry covers any clone whose origin remote is it. The
# levels are "render" (queries run, files read) and "run" (the build script runs too). The id and
# repository of a [[pipeline]] entry are notes for you: an entry is matched by its path.

"""


def get_trust_path() -> Path:
    """The trust record, ``~/.chartbook/trust.toml``: this user's."""
    return get_global_config_dir() / TRUST_FILE


def read_trust() -> list:
    """The entries of the trust record (``docs_src/design/trust.md``), each a dict.

    A ``[[pipeline]]`` entry has ``kind`` ``"pipeline"``, its ``path``
    resolved, ``level``, and ``id``, ``repository`` and ``since`` as
    written (None when absent). A ``[[repository]]`` entry has ``kind``
    ``"repository"``, its ``url`` as :func:`chartbook.identity.repository_key`
    reduces it, ``level`` and ``since``.

    The file is read as a settings file is: one that cannot be read stops
    the command, naming the file; an entry of another shape is passed over
    with a warning naming the file and the entry.

    :returns: The entries, in the file's order; ``[]`` with no file.
    :raises ValueError: If the file cannot be read or parsed; the message
        names the file.
    """
    from chartbook.identity import repository_key

    path = get_trust_path()
    raw = _read_toml(path, "the trust record")
    entries: list = []
    for kind, key in (("pipeline", "path"), ("repository", "url")):
        if kind not in raw:
            continue
        listed = raw[kind]
        if not isinstance(listed, list):
            warnings.warn(
                f"{path}: [[{kind}]] is not an array of tables, and is passed over. Each entry is written "
                f'as [[{kind}]] on a line of its own, then {key} = "…" and level = "run" or "render".',
                stacklevel=2,
            )
            continue
        for position, entry in enumerate(listed, 1):
            value = entry.get(key) if isinstance(entry, dict) else None
            level = entry.get("level") if isinstance(entry, dict) else None
            if not (isinstance(value, str) and value.strip()) or level not in TRUST_LEVELS:
                warnings.warn(
                    f"{path}: [[{kind}]] entry {position} ({_shown_entry(entry)}) is passed over: an entry has "
                    f'{key} = "…" and level = "run" or "render".',
                    stacklevel=2,
                )
                continue
            if kind == "pipeline":
                try:
                    expanded = Path(value.strip()).expanduser()
                except (RuntimeError, OSError):
                    warnings.warn(
                        f"{path}: [[pipeline]] entry {position} ({_shown_entry(entry)}) names a folder this "
                        f"machine cannot resolve, and is passed over.",
                        stacklevel=2,
                    )
                    continue
                if not expanded.is_absolute():
                    # Resolved against the working directory, it would name a
                    # different folder from each folder a command is run in
                    warnings.warn(
                        f"{path}: [[pipeline]] entry {position} ({_shown_entry(entry)}) has a relative path, "
                        f"which would name another folder from each folder a command is run in, and is passed "
                        f"over: write the folder's full path.",
                        stacklevel=2,
                    )
                    continue
                resolved = str(expanded.resolve())
                entries.append(
                    {
                        "kind": "pipeline",
                        "path": resolved,
                        "level": level,
                        "id": entry["id"] if isinstance(entry.get("id"), str) else None,
                        "repository": entry["repository"] if isinstance(entry.get("repository"), str) else None,
                        "since": _since_text(entry.get("since")),
                    }
                )
            else:
                url = repository_key(value)
                if not url:
                    warnings.warn(
                        f"{path}: [[repository]] entry {position} ({_shown_entry(entry)}) names no repository "
                        f"(a url is https://host/owner/name or git@host:owner/name), and is passed over.",
                        stacklevel=2,
                    )
                    continue
                entries.append({"kind": "repository", "url": url, "level": level, "since": _since_text(entry.get("since"))})
    return entries


def _shown_entry(entry: object) -> str:
    """An entry as a message may quote it: one line, cut short."""
    text = " ".join(repr(entry).split())
    return text if len(text) <= 80 else text[:77] + "..."


def _since_text(value: object) -> Optional[str]:
    """A ``since`` as it is written, ``2026-10-18T22:14:05Z``: a string as it is, a TOML date-time (one written unquoted) made one, in UTC when it has a zone and as written when it has none; None when absent."""
    from datetime import date, datetime, timezone

    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Written without a zone: said as written, with none claimed
            return value.isoformat(timespec="seconds")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


#: The values of ``CHARTBOOK_TRUST`` already warned about, so that a build says it once.
_trust_values_warned: set = set()


def trust_of(folder) -> Optional[str]:
    """How far a build of *folder* is trusted: ``"run"``, ``"render"`` or None.

    The highest level among the entries of the trust record that cover the
    folder: a ``[[pipeline]]`` entry whose path is the folder or a parent
    of it, and a ``[[repository]]`` entry whose url is the repository the
    folder's ``origin`` remote names (:func:`chartbook.identity.repository_key`;
    a folder with no remote matches none). Before the record:

    - a build of files from a store (``CHARTBOOK_UNTRUSTED_SOURCE=1``,
      :func:`untrusted_source`) is never trusted, whatever the record says;
    - ``CHARTBOOK_TRUST=all`` trusts every folder at ``run``; the variable
      takes no other value, and another is warned about once and ignored,
      so what follows applies under it as under no value at all;
    - under ``CI`` (the environment variable, set to anything), the
      checkout is trusted at ``run``: a folder in the git repository the
      working directory is in, or in the working directory itself when it
      is in none.

    What each level allows is in ``docs_src/design/trust.md``.

    :raises ValueError: If the trust record cannot be read.
    """
    if untrusted_source():
        return None
    mode = os.environ.get(TRUST_ENV_VAR, "").strip()
    if mode == "all":
        return "run"
    if mode and mode not in _trust_values_warned:
        _trust_values_warned.add(mode)
        warnings.warn(
            f"{TRUST_ENV_VAR}={mode!r} is not a value it takes: 'all' trusts every folder to run, and "
            f"nothing else is read. It is ignored.",
            stacklevel=2,
        )
    here = Path(folder).resolve()
    if os.environ.get("CI", "").strip() and _covers(_ci_checkout(), here):
        return "run"
    return recorded_trust(here)


def recorded_trust(folder) -> Optional[str]:
    """How far the trust record alone trusts *folder*: ``"run"``, ``"render"`` or None.

    What :func:`trust_of` gives once the environment has had its say: the
    highest level among the record's entries that cover the folder. For
    the commands that write the record (``chartbook catalog add``), which
    must not take ``CHARTBOOK_TRUST=all`` or ``CI`` for a record that
    outlives them.

    :raises ValueError: If the trust record cannot be read.
    """
    from chartbook.identity import get_git_remote_url, repository_key

    here = Path(folder).resolve()
    remote: Optional[str] = None  # asked of git once, and only if a repository is trusted
    levels: list = []
    for entry in read_trust():
        if entry["kind"] == "pipeline":
            if _covers(Path(entry["path"]), here):
                levels.append(entry["level"])
        else:
            if remote is None:
                remote = repository_key(get_git_remote_url(here))
            if remote and entry["url"] == remote:
                levels.append(entry["level"])
    if not levels:
        return None
    return max(levels, key=TRUST_LEVELS.index)


def _covers(root: Path, folder: Path) -> bool:
    """Whether a trusted folder covers *folder*: it is that folder, or a folder inside it."""
    return folder == root or root in folder.parents


def _ci_checkout() -> Path:
    """What CI trusts: the top of the git repository the working directory is in, or the working directory itself."""
    from chartbook.identity import _ask_git

    cwd = Path.cwd()
    top = _ask_git(str(cwd), "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else cwd.resolve()


def record_trust(path, level: str, id: Optional[str] = None, repository: Optional[str] = None) -> Path:
    """Record in the trust file that a build of *path*, and of the folders inside it, is trusted at *level*.

    An entry for the same folder is replaced. The file is written whole or
    not at all, as ``machine-id`` is. *id* and *repository* are notes for
    the reader of the file; nothing goes by them.

    :returns: The file written.
    :raises ValueError: If *level* is not a level, or the file cannot be read.
    :raises OSError: If the file cannot be written.
    """
    if level not in TRUST_LEVELS:
        raise ValueError(f"{level!r} is not a level of trust; the levels are {' and '.join(TRUST_LEVELS)}.")
    resolved = str(Path(path).resolve())
    raw = _raw_for_write(get_trust_path())
    kept = [entry for entry in _raw_entries(raw, "pipeline") if not _records_folder(entry, resolved)]
    entry: dict = {"path": resolved, "level": level}
    if id:
        entry["id"] = id
    if repository:
        entry["repository"] = repository
    entry["since"] = _now_text()
    raw["pipeline"] = [*kept, entry]
    return _write_trust(raw)


def record_repository_trust(url: str, level: str) -> Path:
    """Record that a build of any clone whose ``origin`` remote is *url* is trusted at *level*.

    The url is kept as :func:`chartbook.identity.repository_key` reduces it,
    so that every way of writing one repository is one entry. An entry for
    the same repository is replaced.

    :returns: The file written.
    :raises ValueError: If *url* names no repository, *level* is not a
        level, or the file cannot be read.
    :raises OSError: If the file cannot be written.
    """
    from chartbook.identity import repository_key

    if level not in TRUST_LEVELS:
        raise ValueError(f"{level!r} is not a level of trust; the levels are {' and '.join(TRUST_LEVELS)}.")
    key = repository_key(url)
    if not key:
        raise ValueError(
            f"{url!r} names no repository: a repository is https://host/owner/name or git@host:owner/name."
        )
    raw = _raw_for_write(get_trust_path())
    kept = [entry for entry in _raw_entries(raw, "repository") if not _records_repository(entry, key)]
    raw["repository"] = [*kept, {"url": key, "level": level, "since": _now_text()}]
    return _write_trust(raw)


def forget_trust(path=None, url: Optional[str] = None) -> int:
    """Take a folder's entries, or a repository's, out of the trust record.

    :param path: The folder, as recorded: its own entries go, not those of
        a parent folder that covers it.
    :param url: The repository, in any spelling.
    :returns: How many entries were removed.
    :raises ValueError: If the file cannot be read.
    :raises OSError: If it cannot be written.
    """
    from chartbook.identity import repository_key

    trust_path = get_trust_path()
    if not trust_path.is_file():
        return 0
    raw = _raw_for_write(trust_path)
    removed = 0
    if path is not None:
        resolved = str(Path(path).resolve())
        before = _raw_entries(raw, "pipeline")
        raw["pipeline"] = [entry for entry in before if not _records_folder(entry, resolved)]
        removed += len(before) - len(raw["pipeline"])
    if url is not None:
        key = repository_key(url)
        before = _raw_entries(raw, "repository")
        raw["repository"] = [entry for entry in before if not (key and _records_repository(entry, key))]
        removed += len(before) - len(raw["repository"])
    if removed:
        _write_trust(raw)
    return removed


def _raw_for_write(path: Path) -> dict:
    """The trust record as read, for a write that keeps everything it does not change.

    :raises ValueError: If the file cannot be read, or its ``pipeline`` or
        ``repository`` key is not an array of tables: a write would drop
        it, and nothing in the file is dropped without being asked.
    """
    raw = _read_toml(path, "the trust record")
    for kind in ("pipeline", "repository"):
        if kind in raw and not isinstance(raw[kind], list):
            raise ValueError(
                f"{path}: [{kind}] is a table, not an array of tables, and writing the file would drop it. "
                f'Each entry is written as [[{kind}]] on a line of its own, then {"path" if kind == "pipeline" else "url"} = "…" '
                f'and level = "run" or "render"; fix it or remove it, and run this again.'
            )
    return raw


def _raw_entries(raw: dict, kind: str) -> list:
    """The ``[[kind]]`` entries of the file as read, whatever their shape, so that a write keeps them."""
    listed = raw.get(kind)
    return list(listed) if isinstance(listed, list) else []


def _records_folder(entry: object, resolved: str) -> bool:
    """Whether a raw ``[[pipeline]]`` entry is of the folder *resolved* names; a relative path is of none."""
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        return False
    try:
        written = Path(entry["path"].strip()).expanduser()
        return written.is_absolute() and str(written.resolve()) == resolved
    except (RuntimeError, OSError):
        return False


def _records_repository(entry: object, key: str) -> bool:
    """Whether a raw ``[[repository]]`` entry is of the repository *key* names."""
    from chartbook.identity import repository_key

    return isinstance(entry, dict) and isinstance(entry.get("url"), str) and repository_key(entry["url"]) == key


def _now_text() -> str:
    """The time now, as a ``since`` is written: ``2026-10-18T22:14:05Z``."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_trust(raw: dict) -> Path:
    """Write the trust record whole or not at all: a temporary file, then put in its place."""
    import uuid

    path = get_trust_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{TRUST_FILE}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "wb") as f:
            f.write(_TRUST_HEADER.encode("utf-8"))
            tomli_w.dump({key: value for key, value in raw.items() if value not in ([], None)}, f)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def get_default_host() -> str:
    """The git host a pipeline named by its ID alone is cloned from: ``[resolve] default_host``.

    From the user's settings, then the organization's; empty when neither
    sets it, and then a pipeline with no snapshot in the store cannot be
    read at all. The host is never part of a pipeline's identity: a
    repository that moves changes this one line.

    :raises ValueError: If the user's settings file is faulty.
    """
    return ((read_settings().get("resolve") or {}).get("default_host") or "").strip()


def _is_folder(host: str) -> bool:
    """Whether a default host is a folder of repositories: an absolute or explicitly relative path, on any system."""
    return bool(re.match(r"^(/|\\\\|\./|\.\./|\.$|\.\.$|~|[A-Za-z]:[\\/])", host))


def clone_url_for(pipeline_id: str, host: Optional[str] = None) -> Optional[str]:
    """Where a pipeline named by its ID alone is cloned from, by the default host; None if it cannot be said.

    ``acme/rates`` on ``github.com`` is ``https://github.com/acme/rates``.
    A host given as an address (``https://…``, ``ssh://…``,
    ``git@host:``, ``file://…``) or as a folder of repositories has the ID
    put after it. A bare ID (no scope) has no owner to find it under.
    """
    host = get_default_host() if host is None else host
    if not host or "/" not in pipeline_id:
        return None
    if _is_folder(host):
        return os.path.join(host, *pipeline_id.split("/"))
    if "://" in host or re.match(r"^[^/]+@[^/:]+:", host):
        separator = "" if host.endswith((":", "/")) else "/"
        return f"{host}{separator}{pipeline_id}"
    # A host name, perhaps with a path under it: gitlab.example.org/group
    return f"https://{host}/{pipeline_id}"


def get_git_cache_path() -> Path:
    """Get the directory that ``git`` dependencies are fetched into.

    Resolution order:

    1. The ``CHARTBOOK_GIT_CACHE`` environment variable.
    2. ``git.path`` from the user's settings, then the organization's
       (:func:`read_settings`).
    3. ``~/.chartbook/git``.

    The directory need not exist yet.

    :returns: The absolute path of the cache.
    :rtype: Path
    :raises ValueError: If ``git.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(GIT_CACHE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_settings().get("git")
    if configured is not None:
        return Path(configured["path"])

    return get_global_config_dir() / "git"


def get_cache_path() -> Path:
    """Get the directory a remote store's objects and records are kept in once read.

    A store in a bucket is read through a copy on this machine, laid out
    as a folder store under a folder for that bucket and prefix
    (:mod:`chartbook.stores.s3`). Resolution order:

    1. The ``CHARTBOOK_CACHE`` environment variable.
    2. ``cache.path`` from the user's settings, then the organization's
       (:func:`read_settings`).
    3. ``~/.chartbook/cache``.

    The directory need not exist yet, and everything in it can be removed:
    it is read again from the store.

    :returns: The absolute path of the cache.
    :rtype: Path
    :raises ValueError: If ``cache.path`` in the settings file is not a path.
    """
    from_environment = os.environ.get(CACHE_ENV_VAR, "").strip()
    if from_environment:
        return Path(os.path.abspath(Path(from_environment).expanduser()))

    configured = read_settings().get("cache")
    if configured is not None:
        return Path(configured["path"])

    return get_global_config_dir() / "cache"


def write_global_settings(settings: dict) -> None:
    """Write settings to the global settings file.

    Creates the ``~/.chartbook/`` directory if it does not exist.

    :param settings: The settings dictionary to write.
    :type settings: dict
    """
    config_dir = get_global_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    with open(get_global_settings_path(), "wb") as f:
        tomli_w.dump(settings, f)


def set_default_catalog_path(catalog_path: Path) -> None:
    """Set the default catalog path in global settings.

    Validates that *catalog_path* points to an existing catalog-type
    ``chartbook.toml``.  If a directory is given, ``chartbook.toml`` is
    appended automatically.

    :param catalog_path: Path to the catalog's ``chartbook.toml`` or its parent directory.
    :type catalog_path: Path
    :raises FileNotFoundError: If the resolved path does not exist.
    :raises ValueError: If the file is not a catalog-type ``chartbook.toml``.
    """
    catalog_path = Path(catalog_path).resolve()

    # If a directory is given, append chartbook.toml
    if catalog_path.is_dir():
        catalog_path = catalog_path / "chartbook.toml"

    if not catalog_path.is_file():
        raise FileNotFoundError(f"File not found: {catalog_path}")

    # Validate that it is a catalog-type manifest
    from chartbook.manifest import V1FormatError, detect_v1_format, resolve_project_type

    with open(catalog_path, "rb") as f:
        manifest = tomli.load(f)

    if detect_v1_format(manifest):
        raise V1FormatError(catalog_path)

    config_type = resolve_project_type(manifest, source=str(catalog_path))
    if config_type != "catalog":
        raise ValueError(
            f"Expected a catalog-type chartbook.toml, but found type={config_type!r}. "
            f"The config command requires a catalog project, not a pipeline."
        )

    settings = read_global_settings()
    settings.setdefault("catalog", {})
    settings["catalog"]["path"] = str(catalog_path)
    write_global_settings(settings)


def create_global_catalog(title: str = "My Catalog", author: str = "") -> Path:
    """Create a minimal global catalog at ``~/.chartbook/chartbook.toml``.

    Also creates the ``~/.chartbook/artifacts/`` directory.

    :param title: Site title for the catalog.
    :type title: str
    :param author: Author name for the catalog.
    :type author: str
    :returns: Path to the created ``chartbook.toml``.
    :rtype: Path
    :raises FileExistsError: If ``~/.chartbook/chartbook.toml`` already exists.
    """
    config_dir = get_global_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    get_global_artifacts_dir().mkdir(exist_ok=True)

    catalog_path = get_global_catalog_path()
    if catalog_path.is_file():
        raise FileExistsError(f"Global catalog already exists: {catalog_path}")

    catalog = {
        "project": {
            "type": "catalog",
            "name": title,
            "maintainer": author,
        },
        "pipelines": {},
    }

    with open(catalog_path, "wb") as f:
        tomli_w.dump(catalog, f)

    return catalog_path
