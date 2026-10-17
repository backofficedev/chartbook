"""A store in an S3 bucket: ``[store] url = "s3://bucket/prefix"``.

Needs boto3, which ``pip install chartbook[s3]`` installs. The bucket is
laid out exactly as a folder store is, under the prefix: ``store.json``,
``objects/sha256/<2>/<62>/<file>``, ``roots/<note>.json`` and
``snapshots/<commit>/<pipeline>/<stamp>.json``. So ``aws s3 sync`` of a
folder store into a bucket is this store, and back.

Readers open files, so what they read is a local copy: :meth:`S3Store.get`
downloads an object's files once into a cache folder on this machine, laid
out as a folder store too, checks that they hash to the object's name, and
returns that folder. Each read while online is one listing request, which
is how a name another pipeline added for the same bytes is seen; offline,
an object that was read and checked before is served from the cache.
Nothing else in ChartBook changes for a store that is remote;
``data.path()`` gives the path of the cached copy.

Credentials are the AWS SDK's own: the environment, ``~/.aws``, an
instance role. The URL never carries them. It may say where the service
is, for a bucket that is not at AWS::

    s3://bucket/prefix?endpoint=https://minio.example.org&region=us-east-1

A store that is read-only for this machine (``s3:ListBucket`` and
``s3:GetObject``) serves ``chartbook pin``, ``chartbook run --frozen`` and
``data.load()``; what would write raises :class:`~chartbook.store.ReadOnlyStoreError`
and says what was refused. Writing needs ``s3:PutObject``, and ``store gc``
``s3:DeleteObject``.

One thing the folder store does that this one cannot: make an object
appear whole or not at all. Files are uploaded one by one, so a snapshot
interrupted while uploading an object of several files leaves a partial
one, which ``has()`` reports and ``get()`` refuses, naming the cause;
making the snapshot again uploads what is missing and completes it.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union
from urllib.parse import parse_qsl, urlsplit

from chartbook import hashing
from chartbook.store import (
    FROZEN_LINKS,
    LINKS,
    MARKER_FILE,
    OBJECTS_DIR,
    ORIGINS_FILE,
    ROOTS_DIR,
    SCHEMA,
    SNAPSHOTS_DIR,
    TMP_DIR,
    FolderStore,
    ObjectNotFoundError,
    ReadOnlyStoreError,
    Root,
    Store,
    StoredObject,
    StoreError,
    StoreProblem,
    StoreUnreachableError,
    _FULL_COMMIT,
    _HEX,
    _split_hash,
    _unreadable_note_remedy,
    is_record_name,
    is_root_name,
    plain_parts as _plain_parts,
    read_root,
    root_document,
    root_name,
    this_machine,
    what_is_wrong,
)

#: The query keys a store URL may carry. Never a credential.
URL_OPTIONS = ("endpoint", "region")
#: Where the cache notes that an object was downloaded whole and hashed to its name.
VERIFIED_DIR = "verified"
_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
_WRITABLE = stat.S_IWUSR | _READ_ONLY
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REFUSED = ("AccessDenied", "403", "Forbidden", "AllAccessDisabled", "InvalidAccessKeyId", "SignatureDoesNotMatch")
_ERROR_CODE = re.compile(r"\((\w+)\) when calling")


def _parse_url(url: str) -> tuple[str, str, dict[str, str]]:
    """``s3://bucket/prefix?endpoint=…`` into its bucket, prefix and options.

    :raises ValueError: If the URL has no bucket, a bucket name S3 would
        not take, a prefix segment that is ``.`` or ``..`` or empty, a
        query key that is not one of :data:`URL_OPTIONS`, or an ``@``
        anywhere, as a user name in it or in its endpoint has (refused
        before the options are read, as a password may hold what would end
        one). The message never shows a user name, a password or an
        option's value.
    """
    from chartbook.config import shown_store_url

    parts = urlsplit(url.strip())
    shown = shown_store_url(url)  # what an error says: no user name or password
    if "@" in url:
        raise ValueError(
            f"The store {shown!r} has an '@' in it, which no bucket, prefix or option has. Credentials "
            f"never go in the URL, nor in its endpoint: the AWS SDK reads them from the environment or ~/.aws."
        )
    if "#" in url:
        raise ValueError(
            f"The store {shown!r} has a '#' in it, which no bucket, prefix or option has. Credentials "
            f"never go in the URL: the AWS SDK reads them from the environment or ~/.aws."
        )
    if parts.scheme.lower() != "s3" or not parts.netloc:
        raise ValueError(f"The store {shown!r} is not an S3 URL: write s3://bucket/prefix.")
    bucket = parts.netloc
    if ":" in bucket:
        raise ValueError(
            f"The store {shown!r} carries more than a bucket name before the first slash. "
            f"Credentials never go in the URL (the AWS SDK reads them from the environment "
            f"or ~/.aws); another service is named with ?endpoint=https://…"
        )
    if not _BUCKET.match(bucket) or ".." in bucket:
        raise ValueError(f"The store {shown!r} names a bucket S3 would not: {bucket!r}.")
    prefix = parts.path.strip("/")
    if prefix and any(segment in ("", ".", "..") for segment in prefix.split("/")):
        raise ValueError(
            f"The store {shown!r} has a prefix with an empty, '.' or '..' segment; "
            f"write s3://bucket/a/b."
        )
    options = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key not in URL_OPTIONS:
            # The key is said only when it is a name: what follows a '?' in a password is no key
            said = f" {key!r}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else ""
            raise ValueError(
                f"The store {shown!r} has a query key{said} this store does not read; "
                f"the keys are: {', '.join(URL_OPTIONS)}."
            )
        options[key] = value
    return bucket, prefix, options


def _error_code(error: BaseException) -> str:
    """The service's error code inside whatever boto3 raised, or ''."""
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", ""))
    cause = error.__cause__ or error.__context__
    if cause is not None and cause is not error:
        found = _error_code(cause)
        if found:
            return found
    match = _ERROR_CODE.search(str(error))
    return match.group(1) if match else ""



def _inside(folder: Path, relative: str) -> Path:
    """The file at a key's plain path under a folder, which must stay inside it.

    :raises StoreError: If the path is not plain, or leads out of the folder.
    """
    parts = _plain_parts(relative)
    target = folder.joinpath(*parts) if parts is not None else None
    if target is None or not target.resolve().is_relative_to(folder.resolve()):
        raise StoreError(f"The bucket has a key that is not a plain path inside {folder}: {relative!r}.")
    return target

class S3Store(Store):
    """A store in an S3 bucket, with a cache of what was read on this machine.

    :param url: ``s3://bucket/prefix``, with ``?endpoint=`` and ``?region=``
        allowed; see the module.
    :param cache: The folder the downloaded objects and records are kept
        in. By default a folder for this bucket and prefix under
        :func:`chartbook.config.get_cache_path`.
    :param client: A boto3 S3 client to use instead of making one; for
        tests, and for a program that has one already. It must be a
        boto3 client or behave as one, ``exceptions.NoSuchKey`` included.
    :raises ValueError: If boto3 is not installed, or the URL is not a
        store URL.
    """

    def __init__(
        self,
        url: str,
        cache: Union[str, Path, None] = None,
        client=None,
    ):
        self.bucket, self.prefix, self.options = _parse_url(url)
        self.url = f"s3://{self.bucket}/{self.prefix}".rstrip("/")
        if client is None:
            client = self._make_client(url)
        self._client = client
        if cache is None:
            from chartbook.config import get_cache_path

            cache = get_cache_path().joinpath("s3", self.bucket, *self.prefix.split("/"))
        self._cache = FolderStore(cache)
        self._layout_checked = False

    def _make_client(self, url: str):
        try:
            import boto3
        except ImportError:
            raise ValueError(
                f"The store {url!r} is in S3, and that needs boto3, which is not installed: "
                f"pip install chartbook[s3]"
            ) from None
        import botocore.config

        return boto3.client(
            "s3",
            endpoint_url=self.options.get("endpoint") or None,
            region_name=self.options.get("region") or None,
            config=botocore.config.Config(retries={"max_attempts": 5, "mode": "standard"}),
        )

    def __repr__(self) -> str:
        return f"S3Store({self.url!r})"

    def __str__(self) -> str:
        return self.url

    @property
    def cache(self) -> Path:
        """The folder on this machine that holds what was downloaded."""
        return self._cache.root

    # -- talking to the bucket -------------------------------------------

    def _key(self, *parts: str) -> str:
        return "/".join(p for p in (self.prefix, *parts) if p)

    @contextlib.contextmanager
    def _asking(self, what: str):
        """Turn the SDK's failures into one error that says what was being done.

        A refusal is a :class:`ReadOnlyStoreError`; a service that cannot be
        reached a :class:`StoreUnreachableError`; anything else a
        :class:`StoreError`. boto3's transfer manager wraps the service's
        error in its own, so the code is looked for inside whatever came.
        """
        import boto3.exceptions
        import botocore.exceptions

        from chartbook.config import without_credentials

        try:
            yield
        except (botocore.exceptions.ClientError, boto3.exceptions.Boto3Error) as error:
            code = _error_code(error)
            if code in _REFUSED:
                raise ReadOnlyStoreError(
                    f"The store {self} refused to {what}: {code}. If this store is read-only "
                    f"for you, that is as it should be; chartbook pin and run --frozen read "
                    f"only, and whoever owns the store writes to it."
                ) from None
            if code == "NoSuchBucket":
                raise StoreError(f"The store {self} is in a bucket that does not exist.") from None
            # What the SDK says may echo the endpoint it was given
            raise StoreError(f"The store {self} could not {what}: {without_credentials(str(error))}") from None
        except botocore.exceptions.BotoCoreError as error:
            raise StoreUnreachableError(
                f"The store {self} cannot be reached to {what}: {without_credentials(str(error))}"
            ) from None

    def _list(self, prefix: str, delimiter: Optional[str] = None) -> Iterator[dict]:
        """Every key under *prefix*, as the SDK describes it; with a delimiter, the common prefixes instead."""
        arguments = {"Bucket": self.bucket, "Prefix": prefix}
        if delimiter:
            arguments["Delimiter"] = delimiter
        with self._asking(f"list {prefix}"):
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(**arguments):
                if delimiter:
                    for common in page.get("CommonPrefixes", ()):
                        yield {"Prefix": common["Prefix"]}
                else:
                    yield from page.get("Contents", ())

    def _read(self, key: str) -> Optional[bytes]:
        """The bytes at a key, or None if there is nothing there."""
        with self._asking(f"read {key}"):
            try:
                response = self._client.get_object(Bucket=self.bucket, Key=key)
            except self._client.exceptions.NoSuchKey:
                return None
            return response["Body"].read()

    def _exists(self, key: str) -> bool:
        import botocore.exceptions

        with self._asking(f"look for {key}"):
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
            except botocore.exceptions.ClientError as error:
                if _error_code(error) in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
            return True

    def _write(self, key: str, body: bytes) -> None:
        with self._asking(f"write {key}"):
            self._client.put_object(Bucket=self.bucket, Key=key, Body=body)

    def _upload(self, file: Path, key: str) -> None:
        with self._asking(f"upload {key}"):
            self._client.upload_file(str(file), self.bucket, key)

    def _touch(self, key: str) -> None:
        """Write a key's metadata again, so that it counts as written now."""
        with self._asking(f"refresh {key}"):
            self._client.copy_object(
                Bucket=self.bucket,
                Key=key,
                CopySource={"Bucket": self.bucket, "Key": key},
                MetadataDirective="REPLACE",
            )

    def _download(self, key: str, target: Path) -> None:
        """Download a key to a file, whole or not at all, read-only once there.

        The download lands in the cache's own temporary folder, never
        beside the object's files, so that another process hashing the
        object this moment does not see a file that is not part of it.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._cache.root / TMP_DIR / f"{uuid.uuid4().hex}.part"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._asking(f"download {key}"):
                self._client.download_file(self.bucket, key, str(temporary))
            os.chmod(temporary, _READ_ONLY)
            if target.exists():
                os.chmod(target, _WRITABLE)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                os.chmod(temporary, _WRITABLE)
                temporary.unlink()

    def _delete_keys(self, keys: list[str]) -> None:
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            with self._asking(f"delete {batch[0]}"):
                self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )

    def _check_layout(self, create: bool = False) -> None:
        """Check the bucket's marker, as the folder store checks its file; write it if asked."""
        if self._layout_checked:
            return
        marker = self._read(self._key(MARKER_FILE))
        if marker is None:
            if create:
                self._write(self._key(MARKER_FILE), (json.dumps({"schema": SCHEMA}) + "\n").encode())
                self._layout_checked = True
            return
        try:
            schema = json.loads(marker.decode("utf-8")).get("schema")
        except (ValueError, AttributeError) as error:
            raise StoreError(f"Cannot read {self}/{MARKER_FILE}: {error}") from None
        if schema != SCHEMA:
            raise StoreError(
                f"The store {self} has the layout {schema!r}, and this version of ChartBook "
                f"reads {SCHEMA!r}. Use a newer ChartBook, or point CHARTBOOK_STORE at another store."
            )
        self._layout_checked = True

    # -- objects ----------------------------------------------------------

    def _object_prefix(self, content_hash: str) -> str:
        algorithm, digest = _split_hash(content_hash)
        return self._key(OBJECTS_DIR, algorithm, digest[:2], digest[2:]) + "/"

    def _object_files(self, content_hash: str) -> dict[str, dict]:
        """The files of an object in the bucket: relative path -> what the SDK says of the key.

        A key whose path under the object is not a plain relative path (see
        :func:`_plain_parts`) is no file of the object: ``put`` never writes
        one, and a reader would write it outside the object's folder.
        """
        prefix = self._object_prefix(content_hash)
        return {
            entry["Key"][len(prefix):]: entry
            for entry in self._list(prefix)
            if _plain_parts(entry["Key"][len(prefix):]) is not None
        }

    def _verified_note(self, content_hash: str) -> Path:
        algorithm, digest = _split_hash(content_hash)
        return self._cache.root / VERIFIED_DIR / algorithm / digest

    def _is_verified(self, content_hash: str) -> bool:
        """Whether the cache holds this object whole, downloaded and hashed to its name before."""
        note = self._verified_note(content_hash)
        if not note.is_file():
            return False
        local = self._cache.object_path(content_hash)
        names = note.read_text(encoding="utf-8").splitlines()
        return bool(names) and all((local / name).is_file() for name in names)

    def _note_verified(self, content_hash: str, local: Path) -> None:
        note = self._verified_note(content_hash)
        note.parent.mkdir(parents=True, exist_ok=True)
        names = sorted(f.relative_to(local).as_posix() for f in hashing.directory_files(local))
        temporary = note.with_name(f"{note.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text("\n".join(names) + "\n", encoding="utf-8")
        os.replace(temporary, note)

    def _forget_verified(self, content_hash: str) -> None:
        try:
            self._verified_note(content_hash).unlink()
        except OSError:
            pass

    def _object_keys(self, content_hash: str) -> list[dict]:
        """Every key under an object's prefix, what the SDK says of each: its files, and any that are not."""
        return list(self._list(self._object_prefix(content_hash)))

    def has(self, content_hash: str) -> bool:
        self._check_layout()
        return bool(self._object_files(content_hash))

    def _bring(self, content_hash: str, remote: dict[str, dict], into: Path, again: bool) -> Optional[str]:
        """Download an object's files into a folder and say what is wrong with it, if anything.

        A file already there with the size the bucket gives is kept unless
        *again*; a file there that the bucket does not have is removed, as
        it is not the object's. What was brought is hashed when anything
        changed.
        """
        changed = False
        for relative, entry in sorted(remote.items()):
            target = _inside(into, relative)
            if again or not target.is_file() or target.stat().st_size != entry["Size"]:
                self._download(entry["Key"], target)
                changed = True
        if into.is_dir():
            for stale in hashing.directory_files(into):
                if stale.relative_to(into).as_posix() not in remote:
                    os.chmod(stale, _WRITABLE)
                    stale.unlink()
                    changed = True
        if not changed:
            return None
        message = what_is_wrong(content_hash, into)
        if message is not None:
            message += (
                ". An object of several files is uploaded one file at a time, so this may also be "
                "a snapshot that was interrupted while uploading it; making the snapshot again "
                "completes it"
            )
        return message

    def _fetch(self, content_hash: str) -> Path:
        """Bring an object into the cache, or serve it from there when the bucket cannot be reached.

        :raises ObjectNotFoundError: If the bucket has no such object.
        :raises StoreError: If what the bucket holds does not hash to the
            object's name; nothing of it is then kept in the cache.
        """
        local = self._cache.object_path(content_hash)
        try:
            self._check_layout()
            remote = self._object_files(content_hash)
        except StoreUnreachableError:
            if self._is_verified(content_hash):
                return local
            raise
        if not remote:
            self._forget_verified(content_hash)
            raise ObjectNotFoundError(f"The store {self} has no object {content_hash}.")
        message = self._bring(content_hash, remote, local, again=False)
        if message is None:
            if not self._is_verified(content_hash):
                self._note_verified(content_hash, local)
            return local
        self._forget_verified(content_hash)
        self._cache.delete(content_hash)
        raise StoreError(
            f"The object {content_hash} in {self} is not what its name says: {message}. "
            f"Nothing of it is kept on this machine; chartbook store verify lists every such object."
        )

    def get(self, content_hash: str) -> Path:
        """The folder on this machine with the object's files, downloaded if they were not yet."""
        return self._fetch(content_hash)

    def put(self, path: Union[str, Path], links: Iterable[str] = LINKS) -> StoredObject:
        """Copy what a declared ``path`` names into the cache, hash it, and upload it.

        *links* is read for its errors only: a remote store holds copies,
        whatever was asked for, so the object never changes when the
        original does. An object the bucket already has is written again
        in metadata only, so that it counts as stored now and ``gc`` does
        not take it from under a pin in progress.
        """
        links = tuple(links)
        unknown = [kind for kind in links if kind not in LINKS]
        if unknown or not links:
            raise ValueError(f"Unknown link kind(s) {unknown}. The kinds are: {', '.join(LINKS)}.")
        cached = self._cache.put(path, links=tuple(k for k in LINKS if k in FROZEN_LINKS))
        self._check_layout(create=True)
        remote = self._object_files(cached.content_hash)
        prefix = self._object_prefix(cached.content_hash)
        missing = [relative for relative in cached.files if relative not in remote]
        for relative in missing:
            self._upload(cached.path / relative, prefix + relative)
        if not missing:
            for relative in remote:
                self._touch(prefix + relative)
        self._note_verified(cached.content_hash, cached.path)
        created = not remote
        return StoredObject(
            content_hash=cached.content_hash,
            size_bytes=cached.size_bytes,
            path=cached.path,
            files=cached.files,
            links=("copy",) if created else (),
            created=created,
            entries=cached.entries,
        )

    def delete(self, content_hash: str) -> bool:
        # Every key under the object, its files and any that are not (a folder
        # marker too): none is read here
        keys = [entry["Key"] for entry in self._object_keys(content_hash)]
        self._forget_verified(content_hash)
        self._cache.delete(content_hash)
        if not keys:
            return False
        self._delete_keys(keys)
        return True

    def hashes(self) -> Iterator[str]:
        self._check_layout()
        prefix = self._key(OBJECTS_DIR, hashing.ALGORITHM) + "/"
        seen = set()
        for entry in self._list(prefix):
            parts = entry["Key"][len(prefix):].split("/")
            if len(parts) >= 3 and _HEX.match(parts[0] + parts[1]):
                seen.add(parts[0] + parts[1])
        for digest in sorted(seen):
            yield hashing.format_hash(digest)

    def size_of(self, content_hash: str) -> int:
        # Every key under the object, as gc removes every one
        return sum(entry["Size"] for entry in self._object_keys(content_hash))

    def age_of(self, content_hash: str, now: Optional[float] = None) -> float:
        """Seconds since anything under the object's prefix was written to the bucket."""
        remote = self._object_keys(content_hash)
        if not remote:
            raise ObjectNotFoundError(f"The store {self} has no object {content_hash}.")
        newest = max(entry["LastModified"].timestamp() for entry in remote)
        return (time.time() if now is None else now) - newest

    def verify(self, content_hashes: Optional[Iterable[str]] = None) -> list[StoreProblem]:
        """Download every object again, into a temporary folder, and report each that does not hash to its name.

        The cache is left as it is: what this machine read and checked
        stays readable, and the problems are the bucket's. The folder each
        object is downloaded into is removed after it is checked, so the
        disk holds one object at a time.
        """
        import shutil

        problems = []
        for content_hash in self.hashes() if content_hashes is None else content_hashes:
            where = self._cache.object_path(content_hash)
            remote = self._object_files(content_hash)
            if not remote:
                problems.append(StoreProblem(content_hash, where, "not in the store"))
                continue
            scratch = self._cache.root / TMP_DIR / uuid.uuid4().hex
            try:
                message = self._bring(content_hash, remote, scratch, again=True)
            finally:
                if scratch.exists():
                    for file in hashing.directory_files(scratch):
                        os.chmod(file, _WRITABLE)
                    shutil.rmtree(scratch, ignore_errors=True)
            if message is not None:
                problems.append(StoreProblem(content_hash, where, message))
        return problems

    # -- roots ------------------------------------------------------------

    def _root_key(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> str:
        return self._key(ROOTS_DIR, root_name(lockfile, this_machine() if machine is None else machine))

    def add_root(
        self, lockfile: Union[str, Path], hashes: Iterable[str], snapshots: Iterable[tuple[str, str]] = ()
    ) -> None:
        hashes = sorted(set(hashes))
        for content_hash in hashes:
            _split_hash(content_hash)
        self._check_layout(create=True)
        machine = this_machine()
        document = root_document(lockfile, hashes, snapshots, machine)
        self._write(self._root_key(lockfile, machine), (json.dumps(document, indent=1) + "\n").encode())

    def _read_note(self, key: str) -> Optional[Root]:
        body = self._read(key)
        try:
            return read_root(json.loads(body.decode("utf-8")), key.rpartition("/")[2]) if body is not None else None
        except (ValueError, KeyError, TypeError):
            return None

    def root_of(self, lockfile: Union[str, Path]) -> Optional[Root]:
        return self._read_note(self._root_key(lockfile, this_machine(create=False)))

    def remove_root(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> bool:
        key = self._root_key(lockfile, this_machine(create=False) if machine is None else machine)
        if not self._exists(key):
            return False
        self._delete_keys([key])
        return True

    def roots(self) -> list[Root]:
        self._check_layout()
        found = []
        for entry in self._list(self._key(ROOTS_DIR) + "/"):
            name = entry["Key"].rpartition("/")[2]
            if not name.endswith(".json"):
                continue
            body = self._read(entry["Key"])
            try:
                # A copy of a note, as a folder store a sync service kept brings, is read too
                found.append(read_root(json.loads(body.decode("utf-8")) if body is not None else {}, name))
            except (ValueError, KeyError, TypeError) as error:
                raise StoreError(
                    f"Cannot read {self}/{entry['Key']}: {error}.{_unreadable_note_remedy(name)}"
                ) from None
        return sorted(found, key=lambda root: (str(root.lockfile), root.machine, root.note))

    # -- snapshot records ---------------------------------------------------

    def _snapshot_prefix(self, commit: str, name: str) -> str:
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self._key(SNAPSHOTS_DIR, commit, name) + "/"

    def _local(self, key: str) -> Path:
        """The cache file for a key under the prefix.

        :raises StoreError: If the key is not a plain path under the prefix,
            which no key this store writes is.
        """
        relative = key[len(self.prefix) + 1:] if self.prefix else key
        return _inside(self._cache.root, relative)

    def _records_under(self, prefix: str, depth: int) -> list[Path]:
        """The ``.json`` records under a prefix, *depth* segments below it, in the cache."""
        remote = {}
        for entry in self._list(prefix):
            rest = _plain_parts(entry["Key"][len(prefix):])
            # A key that is not a plain path is no record this store wrote
            if rest is not None and len(rest) == depth and is_record_name(rest[-1]):
                remote[entry["Key"]] = entry
        local_folder = self._local(prefix.rstrip("/"))
        wanted = set()
        for key, entry in remote.items():
            target = self._local(key)
            wanted.add(target)
            if not target.is_file() or target.stat().st_size != entry["Size"]:
                self._download(key, target)
        # A record someone removed from the bucket is not one this machine
        # should go on seeing
        if local_folder.is_dir():
            pattern = "/".join(["*"] * (depth - 1) + ["*.json"]) if depth > 1 else "*.json"
            for stale in local_folder.glob(pattern):
                if stale not in wanted:
                    try:
                        os.chmod(stale, _WRITABLE)
                        stale.unlink()
                    except OSError:
                        pass
        return sorted(wanted)

    def snapshot_commits(self) -> set[str]:
        prefix = self._key(SNAPSHOTS_DIR) + "/"
        commits = set()
        for common in self._list(prefix, delimiter="/"):
            name = common["Prefix"][len(prefix):].rstrip("/")
            if _FULL_COMMIT.match(name):
                commits.add(name)
        return commits

    def snapshot_files(self, commit: str, name: str) -> list[Path]:
        return self._records_under(self._snapshot_prefix(commit, name), depth=1)

    def all_snapshot_files(self) -> list[Path]:
        return self._records_under(self._key(SNAPSHOTS_DIR) + "/", depth=3)

    def write_snapshot(self, commit: str, name: str, stamp: str, document: dict) -> Path:
        prefix = self._snapshot_prefix(commit, name)
        self._check_layout(create=True)
        taken = {entry["Key"][len(prefix):] for entry in self._list(prefix)}
        final = f"{stamp}.json"
        count = 1
        while final in taken:
            count += 1
            final = f"{stamp}-{count}.json"
        body = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self._write(prefix + final, body)
        local = self._local(prefix + final)
        local.parent.mkdir(parents=True, exist_ok=True)
        temporary = local.with_name(f".{local.name}.{uuid.uuid4().hex}.part")
        try:
            temporary.write_bytes(body)
            os.chmod(temporary, _READ_ONLY)
            if local.exists():
                os.chmod(local, _WRITABLE)
            os.replace(temporary, local)
        finally:
            if temporary.exists():
                os.chmod(temporary, _WRITABLE)
                temporary.unlink()
        return local

    def remove_snapshot(self, path: Path) -> bool:
        path = Path(path)
        try:
            relative = path.resolve().relative_to(self._cache.root.resolve())
        except ValueError:
            relative = None
        if (
            relative is None
            or len(relative.parts) != 4
            or relative.parts[0] != SNAPSHOTS_DIR
            or not relative.name.endswith(".json")
        ):
            raise ValueError(f"{path} is not a snapshot record of the store {self}.")
        key = self._key(*relative.parts)
        folder = key.rpartition("/")[0] + "/"
        was_there = self._exists(key)
        if was_there:
            self._delete_keys([key])
            if not any(is_record_name(entry["Key"].rpartition("/")[2]) for entry in self._list(folder)):
                self._delete_keys([folder + ORIGINS_FILE])
        if path.is_file():
            os.chmod(path, _WRITABLE)
            path.unlink()
        return was_there

    def note_origin(self, commit: str, name: str, top: str) -> None:
        key = self._snapshot_prefix(commit, name) + ORIGINS_FILE
        self._check_layout(create=True)
        body = self._read(key)
        known = body.decode("utf-8").splitlines() if body is not None else []
        if top not in known:
            known.append(top)
            self._write(key, ("\n".join(known) + "\n").encode("utf-8"))

    def origins(self, commit: str, name: str) -> list[str]:
        body = self._read(self._snapshot_prefix(commit, name) + ORIGINS_FILE)
        if body is None:
            return []
        return [line for line in body.decode("utf-8").splitlines() if line]
