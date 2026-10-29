"""A store in an S3 bucket: ``[store] url = "s3://bucket/prefix"``.

Needs boto3 1.35 or newer, which ``pip install chartbook[s3]`` installs.
The bucket is laid out exactly as a folder store is (:mod:`chartbook.store`),
under the prefix: ``store.json``; ``pipelines/<pipeline>/<snapshot>/``
with the pipeline's files at their own paths and
``_chartbook/snapshot.json``, the record, written last;
``pipelines/+unowned/<hash>/`` for an object put with no pipeline;
``origins/``, ``roots/`` and ``tmp/``. So ``aws s3 sync`` of a folder
store into a bucket is this store, and back. A bucket of ChartBook 0.2's
layout is refused, as a folder of it is, until ``chartbook store
migrate`` has moved it.

Readers open files, so what they read is a copy on this machine, in a
cache folder for the bucket. The records are downloaded into it at their
own names, each with the ETag the bucket gave it. Each file a reader asks
for is downloaded once, into the cache's ``files/``, named by its hash and
checked against it as it arrives: a file there is one whose bytes were
checked, whichever record names it now. :meth:`S3Store.get` hands over a
view in the cache that lays an asset's files out under their own names
(:func:`chartbook.store.gather`). Offline, what was downloaded and checked
before is served from the cache. Nothing else in ChartBook changes for a
store that is remote; ``data.path()`` gives the path in the cache.

A question of the store is one listing of ``pipelines/``, or of one
pipeline's folder when the pipeline is known, and the records are read
from it once. One listing serves the few questions a pin or a read asks
at once, for a moment, and the many that ``store gc`` asks within
:meth:`S3Store.reading`; what this store writes meanwhile is written into
it, not listed again.

Credentials are the AWS SDK's own: the environment, ``~/.aws``, an
instance role. The URL never carries them. It may say where the service
is, for a bucket that is not at AWS::

    s3://bucket/prefix?endpoint=https://minio.example.org&region=us-east-1

A store that is read-only for this machine (``s3:ListBucket`` and
``s3:GetObject``) serves ``chartbook pin``, ``chartbook run --frozen`` and
``data.load()``; what would write raises :class:`~chartbook.store.ReadOnlyStoreError`
and says what was refused. Writing needs ``s3:PutObject`` (and
``s3:DeleteObject`` to tidy after itself, which it does without if it
must), and ``store gc`` ``s3:DeleteObject``.

**Two machines, one bucket.** A bucket has no folder to make whole or
not at all, so a snapshot claims its folder by writing
``_chartbook/CLAIMED.txt`` there only if nothing is there yet (a write
with ``If-None-Match``); one that finds the folder claimed takes the next
second's name. Its record is written the same way. A write the SDK tried
again, its first answer lost, may meet itself there: what is there is read,
and the same bytes are taken for its own. As in a folder store, a snapshot
being made keeps a note under ``tmp/`` of its folder and of the files of
earlier snapshots it uses, written again as it goes on, and ``store gc``
keeps what a note names.

**Half a snapshot.** Files are uploaded one by one, and the record last,
so a snapshot interrupted while uploading leaves files and no record:
that is no snapshot, and ``store gc`` clears it a day after anything in
it last changed. A record whose files are not all there (some removed
since, or a copy of a folder store into the bucket that has not finished)
is said by :meth:`S3Store.incomplete`, which compares the sizes in a
listing with the record's, so ``pin``, ``update``, ``pin --frozen`` and a
read all say the snapshot is not fully uploaded yet. Making the snapshot
again puts back what is missing.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union
from urllib.parse import parse_qsl, urlsplit

from chartbook import hashing
from chartbook.store import (
    CLEARED_FILE,
    FOLDER_MARK,
    FROZEN_LINKS,
    LINKS,
    MARKER_FILE,
    OBJECTS_DIR,
    ORIGINS_DIR,
    OWN_DIR,
    PENDING_FOLDER_SECONDS,
    PENDING_SECONDS,
    PENDING_SUFFIX,
    PIPELINES_DIR,
    RECORD_FILE,
    ROOTS_DIR,
    SCHEMA,
    SNAPSHOTS_DIR,
    TMP_DIR,
    UNOWNED_DIR,
    V1_SCHEMA,
    VIEWS_DIR,
    FolderStore,
    KeptAsset,
    KeptRecord,
    ObjectNotFoundError,
    PendingSnapshot,
    ReadOnlyStoreError,
    Root,
    Store,
    StoredObject,
    StoreError,
    StoreProblem,
    StoreUnreachableError,
    TidyError,
    _FULL_COMMIT,
    _HEX,
    _check_length,
    _folded,
    _found_whole,
    _hash_once,
    _link,
    _read_records,
    _remove_tree,
    _split_hash,
    _unreadable_note_remedy,
    declared_name,
    gather,
    is_snapshot_folder,
    pipeline_folder,
    plain_parts as _plain_parts,
    read_kept_record,
    read_root,
    root_document,
    root_name,
    snapshot_folder_name,
    this_machine,
    what_is_wrong,
    what_is_wrong_with,
)

#: The query keys a store URL may carry. Never a credential.
URL_OPTIONS = ("endpoint", "region")

#: What a snapshot's ``_chartbook/`` holds in a bucket while it is being
#: made: its claim of the folder, written only if no other snapshot has it.
CLAIMED_FILE = "CLAIMED.txt"

#: Where the cache keeps each file of a snapshot it downloaded, named by its
#: hash and checked against it: ``files/<2 hex>/<62 hex>``.
CHECKED_DIR = "files"

#: How long, in seconds, one listing answers what is asked of the store
#: outside a :meth:`S3Store.reading` block: the few questions of one read.
LISTING_SECONDS = 2.0

#: How often, in seconds, a snapshot being made writes its note again, so
#: that ``store gc`` sees it is still going: well within :data:`PENDING_SECONDS`.
ALIVE_SECONDS = 300

#: The largest key one request copies; a bigger one is copied in parts.
COPY_LIMIT = 5 * 1024**3

_READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
_WRITABLE = stat.S_IWUSR | _READ_ONLY
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REFUSED = ("AccessDenied", "403", "Forbidden", "AllAccessDisabled", "InvalidAccessKeyId", "SignatureDoesNotMatch")
#: What a write that is only to be made if nothing is there says when something is.
_TAKEN = ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")
_ERROR_CODE = re.compile(r"\((\w+)\) when calling")
#: A record's name in a snapshot's folder.
_RECORD = f"{OWN_DIR}/{RECORD_FILE}"
#: Beside the cache's copy of a record, the ETag the bucket gave the key it was read from.
_ETAG_SUFFIX = ".etag"


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


def _named_first(held: list[KeptAsset], name: Optional[str]) -> list[KeptAsset]:
    """The holds of an asset, those whose one file is read under *name* first."""
    if not name:
        return held
    return sorted(held, key=lambda asset: not (asset.single and asset.files[0].relative == name))


def _read_as(asset: KeptAsset, name: Optional[str]) -> KeptAsset:
    """An asset of one file, as a reader that opens it by *name* is handed it: the same bytes may be two assets'."""
    if not name or not asset.single or asset.files[0].relative == name:
        return asset
    parts = _plain_parts(name)
    if parts is None or len(parts) != 1:
        return asset
    return dataclasses.replace(asset, files=(dataclasses.replace(asset.files[0], relative=name),))


def _is_there(path: Path, size_bytes: int) -> bool:
    """Whether a file of the cache is there, not a link, at this size."""
    try:
        return not os.path.islink(path) and os.stat(path).st_size == size_bytes
    except OSError:
        return False


def _remove_file(path: Path) -> None:
    """Remove a file of the cache, read-only as it is; nothing if it is not there."""
    try:
        os.chmod(path, _WRITABLE)
        os.unlink(path)
    except OSError:
        pass


def _every_file(folder: Path) -> dict[str, int]:
    """Every file under a folder, by its path in it, with its size; empty if there is no folder."""
    found = {}
    for directory, _, names in os.walk(folder):
        for name in names:
            file = Path(directory) / name
            try:
                found[file.relative_to(folder).as_posix()] = file.stat().st_size
            except OSError:
                pass
    return found


def _modified(entry: dict) -> float:
    """When a key was last written, as the listing says; 0 for one that does not say."""
    when = entry.get("LastModified")
    return when.timestamp() if when is not None else 0.0


def _md5_tag(body: bytes) -> str:
    """The ETag a key written whole in one request, unencrypted by the service, has: the MD5 of its bytes, quoted."""
    return '"' + hashlib.md5(body, usedforsecurity=False).hexdigest() + '"'


def _as_listed(local: Path, entry: dict) -> bool:
    """Whether the cache's copy of a record is the key a listing describes.

    By the ETag the key had when the copy was read, kept beside it: a key
    written again has another, whatever the service makes its ETags of (an
    MD5 of the bytes, or not, for one it encrypts). A copy this machine
    wrote itself, with no ETag beside it yet, is the key if the key's ETag
    is its MD5. The size alone is not enough: a snapshot's folder cleared
    and named again may have a record of the same size.
    """
    try:
        if local.stat().st_size != entry["Size"]:
            return False
    except OSError:
        return False
    etag = str(entry.get("ETag") or "")
    try:
        return etag != "" and local.with_name(local.name + _ETAG_SUFFIX).read_text(encoding="utf-8") == etag
    except OSError:
        pass
    try:
        return etag == _md5_tag(local.read_bytes())
    except OSError:
        return False


class _NotItsBytes(StoreError):
    """A file downloaded that is not what its record says: the next copy may be."""


class _Seen:
    """One listing of the bucket's ``pipelines/``, or of one pipeline's folder in it, and what is read from it once.

    :param folder: The pipeline's folder listed; None for all of ``pipelines/``.
    :param listing: Every key under it, by its name in the store.
    :param at: When it was listed, by :func:`time.monotonic`.
    """

    def __init__(self, folder: Optional[str], listing: dict[str, dict], at: float):
        self.folder = folder
        self.listing = listing
        self.at = at
        self.records: Optional[list[KeptRecord]] = None
        self.index: Optional[dict[str, list[KeptAsset]]] = None
        self._nfc: Optional[dict[str, dict]] = None

    def covers(self, name: str) -> bool:
        return name.startswith(f"{PIPELINES_DIR}/{self.folder}/" if self.folder else f"{PIPELINES_DIR}/")

    def entry(self, name: str) -> Optional[dict]:
        """A key by its name, or by the name in Unicode's other form: a sync from macOS may write it so."""
        found = self.listing.get(name)
        if found is None:
            if self._nfc is None:
                self._nfc = {unicodedata.normalize("NFC", key): value for key, value in self.listing.items()}
            found = self._nfc.get(unicodedata.normalize("NFC", name))
        return found

    def wrote(self, name: str, entry: dict) -> None:
        """A key this store has just written, written into what was listed."""
        self.listing[name] = entry
        self._nfc = None
        if name.endswith("/" + _RECORD):
            self.records = self.index = None  # read again, with the record

    def gone(self, name: str, local: Path) -> None:
        """A key this store has just removed, taken out of what was listed."""
        if self.listing.pop(name, None) is None:
            return
        self._nfc = None
        if name.endswith("/" + _RECORD) and self.records is not None:
            self.records = [record for record in self.records if record.path != local]
            self.index = None


class S3Store(Store):
    """A store in an S3 bucket, with a cache of what was read on this machine.

    :param url: ``s3://bucket/prefix``, with ``?endpoint=`` and ``?region=``
        allowed; see the module.
    :param cache: The folder the downloaded records and files are kept
        in. By default a folder for this bucket and prefix (and service, if
        it is not AWS) under :func:`chartbook.config.get_cache_path`.
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

            folder = self.bucket
            if self.options.get("endpoint"):
                # Two services may each have a bucket of this name: each its own cache
                folder += "~" + hashlib.sha256(self.options["endpoint"].encode("utf-8")).hexdigest()[:8]
            parts = self.prefix.split("/")
            if self.prefix != self.prefix.lower():
                # A disk of macOS or Windows takes Data and data for one folder: two prefixes, two caches
                parts[-1] += "~" + hashlib.sha256(self.prefix.encode("utf-8")).hexdigest()[:8]
            cache = get_cache_path().joinpath("s3", folder, *parts)
        self._root = Path(os.path.abspath(Path(cache).expanduser()))
        self._layout_checked = False
        # The snapshots' folders this process has claimed, by pipeline folder and name
        self._claimed: set[tuple[str, str]] = set()
        # What was listed of pipelines/ (None) and of one pipeline's folder
        self._memo: dict[Optional[str], _Seen] = {}
        self._reading = 0
        # Within a reading block: the notes of origins there are, and each read
        self._origins: Optional[dict[str, Optional[list[str]]]] = None

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
        return self._root

    @property
    def views(self) -> Path:
        """Where assets are laid out for readers, their files under their own names: ``views/`` in the cache."""
        return self._root / VIEWS_DIR

    # -- talking to the bucket -------------------------------------------

    def _key(self, *parts: str) -> str:
        return "/".join(p for p in (self.prefix, *parts) if p)

    def _name(self, key: str) -> str:
        """A key's name in the store: its path under the prefix."""
        return key[len(self.prefix) + 1:] if self.prefix else key

    def _refusal(self, what: str, code: str) -> ReadOnlyStoreError:
        return ReadOnlyStoreError(
            f"The store {self} refused to {what}: {code}. If this store is read-only "
            f"for you, that is as it should be; chartbook pin and run --frozen read "
            f"only, and whoever owns the store writes to it."
        )

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
                raise self._refusal(what, code) from None
            if code == "NoSuchBucket":
                raise StoreError(f"The store {self} is in a bucket that does not exist.") from None
            # What the SDK says may echo the endpoint it was given
            raise StoreError(f"The store {self} could not {what}: {without_credentials(str(error))}") from None
        except botocore.exceptions.ParamValidationError as error:
            # Not the network's doing: a boto3 older than what ChartBook asks of it
            raise StoreError(
                f"The store {self} could not {what}: the boto3 installed does not take what ChartBook asks "
                f"({error}). The S3 store needs boto3 1.35 or newer: pip install 'boto3>=1.35'"
            ) from None
        except botocore.exceptions.BotoCoreError as error:
            raise StoreUnreachableError(
                f"The store {self} cannot be reached to {what}: {without_credentials(str(error))}"
            ) from None

    # What was listed, written into as this store writes

    def _wrote(self, key: str, size: int, etag: Optional[str] = None) -> None:
        """A key this store has just written: what it listed of ``pipelines/`` has it now."""
        name = self._name(key)
        if not name.startswith(PIPELINES_DIR + "/"):
            return
        entry = {"Key": key, "Size": size, "LastModified": datetime.now(timezone.utc), "ETag": etag}
        for seen in self._memo.values():
            if seen.covers(name):
                seen.wrote(name, entry)

    def _gone(self, keys: Iterable[str]) -> None:
        """Keys this store has just removed: what it listed of ``pipelines/`` has them no more."""
        for key in keys:
            name = self._name(key)
            if name.startswith(PIPELINES_DIR + "/") and _plain_parts(name) is not None:
                for seen in self._memo.values():
                    seen.gone(name, self._root.joinpath(*name.split("/")))

    def _forget(self) -> None:
        self._memo = {}

    @contextlib.contextmanager
    def reading(self):
        """Go by one listing of the bucket until the block ends, and what this store writes meanwhile.

        For what asks the store many times over at once, ``store gc``'s plan:
        the records are read from it once, and so are the notes of origins.
        """
        if not self._reading:
            self._forget()  # what was listed before the block may be old by now
            self._origins = None
        self._reading += 1
        try:
            yield self
        finally:
            self._reading -= 1
            if not self._reading:
                self._forget()
                self._origins = None

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

    def _seen(self, folder: Optional[str] = None, fresh: bool = False) -> _Seen:
        """What is listed under ``pipelines/``, or under one pipeline's *folder* in it, with the records read from it.

        One listing answers for :data:`LISTING_SECONDS`, and through a
        :meth:`reading` block: a pin or a read asks ``has``, then
        ``incomplete``, then ``get``, of one moment. What this store writes
        or removes meanwhile is written into it.

        :param fresh: List again, whatever was listed: for what is removed,
            or kept on the strength of what a record names.
        """
        if not fresh:
            now = time.monotonic()
            for whose in (folder, None) if folder else (None,):
                seen = self._memo.get(whose)
                if seen is None or not (self._reading or now - seen.at < LISTING_SECONDS):
                    continue
                if whose == folder:
                    return seen
                base = f"{PIPELINES_DIR}/{folder}/"
                part = _Seen(folder, {name: entry for name, entry in seen.listing.items() if name.startswith(base)}, seen.at)
                self._memo[folder] = part
                return part
        prefix = f"{PIPELINES_DIR}/{folder}" if folder else PIPELINES_DIR
        listing = {self._name(entry["Key"]): entry for entry in self._list(self._key(prefix) + "/")}
        seen = self._memo[folder] = _Seen(folder, listing, time.monotonic())
        if folder is None:
            # Each pipeline's own listing is the whole one's part now
            self._memo = {None: seen}
        return seen

    def _records_of(self, seen: _Seen) -> list[KeptRecord]:
        """The records a listing has, read once for it."""
        if seen.records is None:
            seen.records = self._records(seen.listing, under=seen.folder)
        return seen.records

    def _held(self, seen: _Seen, content_hash: str, pipeline: Optional[str] = None) -> list[KeptAsset]:
        """Every record's hold of an asset in what was listed, newest first; *pipeline*'s first, as the folder store orders them."""
        if seen.index is None:
            index: dict[str, list[KeptAsset]] = {}
            for record in self._records_of(seen):
                if record.readable:
                    for asset in record.assets:
                        index.setdefault(asset.content_hash, []).append(asset)
            seen.index = index
        held = list(seen.index.get(content_hash, ()))
        held.sort(key=lambda asset: (asset.record.pipeline == pipeline, asset.record.made_at), reverse=True)
        return held

    def _read(self, key: str) -> Optional[bytes]:
        """The bytes at a key, or None if there is nothing there."""
        found = self._read_tagged(key)
        return found[0] if found is not None else None

    def _read_tagged(self, key: str) -> Optional[tuple[bytes, str]]:
        """The bytes at a key and its ETag, in one request; None if there is nothing there."""
        with self._asking(f"read {key}"):
            try:
                response = self._client.get_object(Bucket=self.bucket, Key=key)
            except self._client.exceptions.NoSuchKey:
                return None
            return response["Body"].read(), str(response.get("ETag") or "")

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
        self._wrote(key, len(body), _md5_tag(body))

    def _put_new(self, key: str, body: bytes) -> bool:
        """Write a key only if nothing is there yet, as one request; False if something else was.

        A write the SDK tries again, its first answer lost (a timeout, an
        error after the write), meets the first: what is there is read, and
        the same bytes are this write's own. A service that does not take
        such a write is asked first whether the key is there, which two
        machines at the same moment may both pass.
        """
        import botocore.exceptions

        with self._asking(f"write {key}"):
            try:
                self._client.put_object(Bucket=self.bucket, Key=key, Body=body, IfNoneMatch="*")
            except botocore.exceptions.ClientError as error:
                code = _error_code(error)
                if code in _TAKEN:
                    if self._read(key) != body:
                        return False
                elif code == "NotImplemented":
                    there = self._read(key)
                    if there is not None and there != body:
                        return False
                    if there is None:
                        self._client.put_object(Bucket=self.bucket, Key=key, Body=body)
                else:
                    raise
        self._wrote(key, len(body), _md5_tag(body))
        return True

    def _upload(self, file: Path, key: str) -> None:
        with self._asking(f"upload {key}"):
            self._client.upload_file(str(file), self.bucket, key)
        self._wrote(key, os.stat(file).st_size)

    def _touch(self, key: str, size: int) -> None:
        """Write a key again, so that it counts as written now: its metadata, or for a key too big for that, the whole of it, on the service."""
        with self._asking(f"refresh {key}"):
            if size <= COPY_LIMIT:
                self._client.copy_object(
                    Bucket=self.bucket,
                    Key=key,
                    CopySource={"Bucket": self.bucket, "Key": key},
                    MetadataDirective="REPLACE",
                )
            else:
                self._client.copy({"Bucket": self.bucket, "Key": key}, self.bucket, key)
        self._wrote(key, size)

    def _download(self, key: str, target: Path, content_hash: Optional[str] = None) -> Optional[str]:
        """Download a key to a file, whole or not at all, read-only once there.

        The download lands in the cache's own temporary folder, never in a
        folder a reader opens, so that nobody meets half a file.

        :param content_hash: The hash the file must have. One of other
            bytes is not kept, and its hash is returned.
        :returns: None, or the hash of a file that was not what was asked.
        """
        temporary = self._root / TMP_DIR / f"{uuid.uuid4().hex[:12]}.part"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._asking(f"download {key}"):
                self._client.download_file(self.bucket, key, str(temporary))
            if content_hash is not None:
                actual = hashing.format_hash(hashing._file_hex(temporary))
                if actual != content_hash:
                    return actual
            self._settle(temporary, target)
        finally:
            if temporary.exists():
                _remove_file(temporary)
        return None

    @staticmethod
    def _settle(temporary: Path, target: Path) -> None:
        """Put a file of the cache in place, read-only, whole or not at all."""
        os.chmod(temporary, _READ_ONLY)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            os.chmod(target, _WRITABLE)
        os.replace(temporary, target)

    def _try_delete(self, keys: list[str]) -> dict[str, tuple[str, str]]:
        """Delete keys, a thousand to a request; each the service did not delete, with its code and what it said."""
        failed: dict[str, tuple[str, str]] = {}
        for start in range(0, len(keys), 1000):
            batch = keys[start : start + 1000]
            with self._asking(f"delete {batch[0]}"):
                response = self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
            # A refusal of some keys comes in the answer, not as an error
            for error in (response or {}).get("Errors") or ():
                failed[str(error.get("Key", ""))] = (str(error.get("Code", "")), str(error.get("Message", "")))
        self._gone(key for key in keys if key not in failed)
        return failed

    def _delete_keys(self, keys: list[str]) -> None:
        """Delete keys; one the service did not delete is raised, a refusal as :class:`ReadOnlyStoreError`."""
        failed = self._try_delete(keys)
        if failed:
            key, (code, message) = sorted(failed.items())[0]
            more = f" (and {len(failed) - 1} more)" if len(failed) > 1 else ""
            if code in _REFUSED:
                raise self._refusal(f"delete {key}{more}", code)
            raise StoreError(f"The store {self} could not delete {key}{more}: {code}{': ' + message if message else ''}.")

    def _check_layout(self, create: bool = False) -> None:
        """Check the bucket's marker, as the folder store checks its file; write it if asked."""
        if self._layout_checked:
            return
        marker = self._read(self._key(MARKER_FILE))
        if marker is None:
            if not create:
                return  # nothing here yet; nothing to misread
            for old in (OBJECTS_DIR, SNAPSHOTS_DIR):
                if next(self._list(self._key(old) + "/"), None) is not None:
                    raise StoreError(
                        f"The store {self} has no store.json, and holds the folders of a store of ChartBook 0.2 "
                        f"(objects/, snapshots/): its store.json has not arrived (a copy into the bucket that has not "
                        f"finished), or was removed. Nothing is written to it. Wait for the copy; if store.json is gone, "
                        f"run `chartbook store migrate` once every machine that uses it has ChartBook 0.3."
                    )
            self._write(self._key(MARKER_FILE), (json.dumps({"schema": SCHEMA}) + "\n").encode())
            self._layout_checked = True
            return
        try:
            schema = json.loads(marker.decode("utf-8")).get("schema")
        except (ValueError, AttributeError) as error:
            raise StoreError(f"Cannot read {self}/{MARKER_FILE}: {error}") from None
        if schema == V1_SCHEMA:
            raise StoreError(
                f"The store at {self} has the layout of ChartBook 0.2 ({V1_SCHEMA!r}), and this version reads "
                f"{SCHEMA!r}. Once every machine that uses this store has ChartBook 0.3, run `chartbook store "
                f"migrate` on one of them; until then, use ChartBook 0.2 with it."
            )
        if schema != SCHEMA:
            raise StoreError(
                f"The store {self} has the layout {schema!r}, and this version of ChartBook "
                f"reads {SCHEMA!r}. Use a newer ChartBook, or point CHARTBOOK_STORE at another store."
            )
        self._layout_checked = True

    # -- the cache ----------------------------------------------------------

    def _local(self, key: str) -> Path:
        """The cache file for a key under the prefix.

        :raises StoreError: If the key is not a plain path under the prefix,
            which no key this store writes is.
        """
        return _inside(self._root, self._name(key))

    def _where(self, location: Union[str, Path]) -> str:
        """The name in the store of a file a record names, from where the cache would keep it."""
        return Path(location).relative_to(self._root).as_posix()

    def _checked(self, content_hash: str) -> Path:
        """Where the cache keeps a file downloaded and checked against this hash."""
        _, digest = _split_hash(content_hash)
        return self._root / CHECKED_DIR / digest[:2] / digest[2:]

    def _check_in(self, temporary: Path, content_hash: str) -> None:
        """Keep a file just hashed in the cache's checked files, unless one of its hash is there."""
        checked = self._checked(content_hash)
        if checked.is_file():
            _remove_file(temporary)
        else:
            self._settle(temporary, checked)

    def _as_checked(self, asset: KeptAsset) -> KeptAsset:
        """An asset with its files where the cache keeps them checked."""
        return dataclasses.replace(
            asset, files=tuple(dataclasses.replace(file, location=self._checked(file.content_hash)) for file in asset.files)
        )

    def _keep_locally(self, local: Path, body: bytes, etag: str) -> None:
        """Write the cache's copy of a record, whole or not at all, and beside it the ETag of the key it is of."""
        temporary = local.with_name(f".{local.name}.{uuid.uuid4().hex[:12]}.part")
        _check_length(temporary)  # on Windows, a cache folder deep enough is said as such
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            temporary.write_bytes(body)
            self._settle(temporary, local)
        finally:
            if temporary.exists():
                _remove_file(temporary)
        try:
            local.with_name(local.name + _ETAG_SUFFIX).write_text(etag, encoding="utf-8", newline="\n")
        except OSError:
            pass  # read again next time, then

    @staticmethod
    def _drop_locally(local: Path) -> None:
        """Remove the cache's copy of a record, and the ETag beside it."""
        _remove_file(local)
        _remove_file(local.with_name(local.name + _ETAG_SUFFIX))
        _read_records.pop(str(local), None)

    def _unowned_prefix(self, content_hash: str) -> str:
        """The name in the store of the folder of an object no pipeline owns, ``pipelines/+unowned/<hex>/``."""
        _, digest = _split_hash(content_hash)
        return f"{PIPELINES_DIR}/{UNOWNED_DIR}/{digest}/"

    def _unowned_keys(self, content_hash: str, listing: dict[str, dict], plain: bool = True) -> dict[str, dict]:
        """The keys of an object no pipeline owns, by their path in it; with *plain*, only those that are a plain path.

        A key whose path is not plain is no file of the object: ``put``
        never writes one, and a reader would write it outside the object's
        folder. It is still under the object, for ``delete`` to remove.
        """
        prefix = self._unowned_prefix(content_hash)
        return {
            name[len(prefix):]: entry for name, entry in listing.items()
            if name.startswith(prefix) and (not plain or _plain_parts(name[len(prefix):]) is not None)
        }

    def _unowned_cache(self, content_hash: str) -> Path:
        """Where the cache keeps an object no pipeline owns, whole and checked."""
        return self._root.joinpath(*self._unowned_prefix(content_hash).rstrip("/").split("/"))

    # -- snapshots' records -------------------------------------------------

    def records(self) -> list[KeptRecord]:
        """Every snapshot's record in the bucket, made by an owner or by a pin, as the folder store reads its own."""
        self._check_layout()
        return list(self._records_of(self._seen()))

    def _records(self, listing: dict[str, dict], under: Optional[str] = None) -> list[KeptRecord]:
        """The records a listing of ``pipelines/`` has, downloaded into the cache where they are not yet.

        A record in another pipeline's folder, or another commit's, is one
        that cannot be read, as in a folder store. One the cache has and the
        bucket has not is removed from the cache: whoever removed it is not
        to be second-guessed. The cache's copy is read again when the key's
        ETag is not the one it was read at (:func:`_as_listed`).

        :param under: The one pipeline's folder the listing is of.
        """
        found, wanted = [], set()
        for name in sorted(listing):
            parts = name.split("/")
            if (
                len(parts) != 5 or parts[0] != PIPELINES_DIR or parts[1] == UNOWNED_DIR or not is_snapshot_folder(parts[2])
                or "/".join(parts[3:]) != _RECORD or _plain_parts(name) is None
            ):
                continue
            entry = listing[name]
            local = self._root.joinpath(*parts)
            if not _as_listed(local, entry):
                read = self._read_tagged(entry["Key"])
                if read is None:
                    continue  # gone since it was listed
                # The ETag it was listed with: one written meanwhile is read again next time
                self._keep_locally(local, read[0], str(entry.get("ETag") or read[1]))
            wanted.add(local)
            found.append(self._as_found(local, parts[1], parts[2]))
        cached = self._root / PIPELINES_DIR
        for stale in (cached / under).glob(f"*/{_RECORD}") if under else cached.glob(f"*/*/{_RECORD}"):
            if stale not in wanted:
                self._drop_locally(stale)
        return found

    @staticmethod
    def _as_found(local: Path, folder: str, snapshot: str) -> KeptRecord:
        """A record as the cache has it; unreadable if it is in another pipeline's folder, or another commit's."""
        kept = read_kept_record(local)
        if kept.readable and (pipeline_folder(kept.pipeline) != folder or not snapshot.endswith("_" + kept.commit[:12])):
            return KeptRecord(local, readable=False, stamp=kept.stamp)
        return kept

    def _cached_records(self) -> list[KeptRecord]:
        """The records the cache has, as they were when last listed: what is read offline."""
        return [
            self._as_found(local, local.parent.parent.parent.name, local.parent.parent.name)
            for local in sorted((self._root / PIPELINES_DIR).glob(f"*/*/{_RECORD}"))
            if is_snapshot_folder(local.parent.parent.name)
        ]

    def _pipeline_seen(self, pipeline: Optional[str]) -> Optional[_Seen]:
        """What is listed of a pipeline's folder, for a question that names the pipeline; None for one that does not."""
        if pipeline is None:
            return None
        from chartbook.identity import validate_pipeline_id

        try:
            validate_pipeline_id(pipeline)
        except ValueError:
            return None
        return self._seen(pipeline_folder(pipeline))

    def snapshot_commits(self) -> set[str]:
        return {record.commit for record in self.records() if record.readable and record.made_by == "snapshot"}

    def snapshot_commit_prefixes(self) -> set[str]:
        return {
            record.folder.name.rpartition("_")[2] for record in self.records()
            if not record.readable or record.made_by == "snapshot"
        }

    def snapshot_files(self, commit: str, name: str) -> list[Path]:
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        from chartbook.snapshot import record_name

        return sorted(
            record.path for record in self.records()
            if record.folder.name.endswith("_" + commit[:12])
            and (not record.readable or (record.made_by == "snapshot" and record.commit == commit and record_name(record.subdirectory) == name))
        )

    def all_snapshot_files(self) -> list[Path]:
        return sorted(record.path for record in self.records() if not record.readable or record.made_by == "snapshot")

    def pinned_snapshot_files(self) -> list[Path]:
        return sorted(record.path for record in self.records() if record.readable and record.made_by == "pin")

    def begin(
        self, pipeline: str, commit: str, made_at: str, base: Optional[Union[str, Path]] = None, made_by: str = "snapshot"
    ) -> "PendingSnapshot":
        self._check_layout(create=True)
        return _S3Pending(self, pipeline, commit, made_at, base, made_by)

    def remove_snapshot(self, path: Path) -> bool:
        """Clear one snapshot: its record goes, and ``_chartbook/CLEARED.txt`` says so.

        Its files go with :meth:`tidy`, as in a folder store, but those a
        later snapshot uses; the folder goes once nothing in it is used. So
        does the note of origins of the last snapshot of a pipeline at a
        commit: :meth:`tidy` lists the bucket once for all a gc clears.

        :raises ValueError: If *path* is not a record in this store's cache.
        :raises ReadOnlyStoreError: If the bucket refused to remove the
            record, which is then left as it was, with nothing beside it.
        """
        path = Path(path)
        try:
            relative = path.resolve().relative_to(self._root.resolve())
        except ValueError:
            relative = None
        parts = relative.parts if relative is not None else ()
        if (
            len(parts) != 5 or parts[0] != PIPELINES_DIR or parts[1] == UNOWNED_DIR
            or not is_snapshot_folder(parts[2]) or "/".join(parts[3:]) != _RECORD
        ):
            raise ValueError(f"{path} is not a snapshot record of the store {self}.")
        self._check_layout()
        name = "/".join(parts)
        key, local = self._key(name), self._root.joinpath(*parts)
        # What was just listed says it is there; else it is asked
        if name not in self._seen(parts[1]).listing and not self._exists(key):
            self._drop_locally(local)
            return False
        self._delete_keys([key])
        self._drop_locally(local)
        self._write(
            self._key(PIPELINES_DIR, parts[1], parts[2], OWN_DIR, CLEARED_FILE),
            (
                f"Cleared by `chartbook store gc` on {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC.\n"
                f"The files left in this folder are used by later snapshots of the same pipeline,\n"
                f"whose _chartbook/snapshot.json says so; the folder goes once none is.\n"
            ).encode("utf-8"),
        )
        return True

    def _notes(self) -> tuple[set[str], set[str]]:
        """What the notes of snapshots being made keep, while each is younger than :data:`PENDING_FOLDER_SECONDS`: their own folders, and the files of earlier ones they use, by their names in the store, folded (:func:`chartbook.store._folded`)."""
        folders: set[str] = set()
        files: set[str] = set()
        now = time.time()
        for entry in self._list(self._key(TMP_DIR) + "/"):
            if not entry["Key"].endswith(PENDING_SUFFIX) or now - _modified(entry) > PENDING_FOLDER_SECONDS:
                continue
            body = self._read(entry["Key"]) or b""
            for line in body.decode("utf-8", "replace").splitlines():
                if line.startswith(FOLDER_MARK):
                    folders.add(line[len(FOLDER_MARK):])
                elif line:
                    files.add(_folded(line))
        return folders, files

    def _unused_in(
        self, folder: str, listing: dict[str, dict], records: list[KeptRecord], noted: tuple[set, set], keep: set, now: float
    ) -> list[tuple[str, dict]]:
        """What no snapshot of one pipeline uses in its folder, by the rules of :meth:`chartbook.store.FolderStore.sweep`.

        A key is used when a record of the pipeline names it, followed by
        this machine or not, or a snapshot being made has noted it, or it
        is one of *keep*; names are compared folded, as a disk that tells
        neither letter case nor Unicode's forms apart compares them. What is
        not used is taken from a snapshot's folder that has no record once
        nothing in it has changed for :data:`PENDING_FOLDER_SECONDS` and no
        snapshot being made has noted it (at once if ``store gc`` cleared
        it), and from one that has a record once the key is
        :data:`PENDING_SECONDS` old: a sync service's copy. Nothing is taken
        from a pipeline's folder while one of its records cannot be read, or
        names files this machine does not follow: that is warned of.
        """
        folders, files = noted
        base = f"{PIPELINES_DIR}/{folder}/"
        here = [record for record in records if record.folder.parent.name == folder]
        doubt = next((record for record in here if not record.readable or not record.whole), None)
        used = set(files) | keep
        try:
            used |= {_folded(self._where(path)) for record in here for path in record.mentioned}
        except ValueError:
            doubt = doubt or here[0]  # a name this machine cannot make a path of
        if doubt is not None:
            warnings.warn(
                f"Nothing in {self}/{base} is removed: its record {self}/{self._where(doubt.path)} cannot be read, or "
                f"names files this machine does not follow (a sync that has not finished, or names another system "
                f"takes and this one does not). `chartbook store verify` says more.",
                stacklevel=3,
            )
            return []
        snapshots: dict[str, dict[str, dict]] = {}
        for name, entry in listing.items():
            if name.startswith(base):
                snapshot, _, rest = name[len(base):].partition("/")
                if is_snapshot_folder(snapshot) and rest:
                    snapshots.setdefault(snapshot, {})[name] = entry
        found = []
        for snapshot, held in sorted(snapshots.items()):
            record, cleared = f"{base}{snapshot}/{_RECORD}", f"{base}{snapshot}/{OWN_DIR}/{CLEARED_FILE}"
            recorded = record in held
            if not recorded and cleared not in held:
                newest = max(_modified(entry) for entry in held.values())
                if base + snapshot in folders or now - newest < PENDING_FOLDER_SECONDS:
                    continue  # a snapshot being made, most likely
            for name, entry in sorted(held.items()):
                if name in (record, cleared) or _folded(name) in used:
                    continue
                if recorded and now - _modified(entry) < PENDING_SECONDS:
                    continue  # beside a snapshot's files: a copy of a sync's, an hour on
                found.append((name, entry))
        return found

    def tidy(self, dry_run: bool = False, keep: Iterable[str] = ()) -> list[tuple[str, int]]:
        """Remove what no snapshot uses from every pipeline's folder; what was removed, or with *dry_run* would be, each with its size.

        The notes of snapshots being made are read first, then the records
        as they are now, and the notes once more just before anything goes:
        a snapshot written between the first two is in the records, and one
        begun meanwhile is in the last. A note of origins no snapshot of its
        commit is left to use goes too, an hour after it was written; and
        first, what a writer that died left under ``tmp/``.

        :param keep: Names in the store not to remove: what ``store gc``
            spares for being new.
        :raises TidyError: Once the rest is removed, if some of it could not
            be, naming each with what the service said and what to do.
        """
        self._check_layout()
        if not dry_run:
            self._tidy_tmp()
        noted = self._notes()
        seen = self._seen(fresh=True)
        listing, records = dict(seen.listing), self._records_of(seen)
        keep = {_folded(name) for name in keep}
        now = time.time()
        found: list = []
        doubted = set()
        for folder in sorted({name.split("/")[1] for name in listing if name.count("/") >= 2} - {UNOWNED_DIR}):
            here = [record for record in records if record.folder.parent.name == folder]
            if any(not record.readable or not record.whole for record in here):
                doubted.add(folder)
            found += self._unused_in(folder, listing, records, noted, keep, now)
        folders, files = self._notes()
        found = [
            (name, entry) for name, entry in found
            if "/".join(name.split("/")[:3]) not in folders and _folded(name) not in files
        ]
        if dry_run:
            return [(name, entry["Size"]) for name, entry in found]
        refused = self._try_delete([entry["Key"] for _, entry in found]) if found else {}
        removed = [(name, entry["Size"]) for name, entry in found if entry["Key"] not in refused]
        remedy = "whoever owns the bucket removes it, or gives you s3:DeleteObject on it, and you run `chartbook store gc` again"
        failed = [
            (name, f"{' '.join(refused[entry['Key']]).strip()}; {remedy}") for name, entry in found if entry["Key"] in refused
        ]
        # A cleared folder's CLEARED.txt goes with the last of what is in it
        gone = {name for name, _ in removed}
        left: dict[str, list[str]] = {}
        for name in listing:
            if name not in gone and name.count("/") >= 3 and name.split("/")[1] not in doubted:
                left.setdefault("/".join(name.split("/")[:3]), []).append(name)
        cleared = [
            listing[names[0]]["Key"] for names in left.values()
            if len(names) == 1 and names[0].endswith(f"/{OWN_DIR}/{CLEARED_FILE}") and is_snapshot_folder(names[0].split("/")[2])
        ]
        if cleared:
            self._try_delete(cleared)
        self._tidy_origins(records, now)
        for name, _ in removed:
            if _plain_parts(name) is not None:
                _remove_file(self._root.joinpath(*name.split("/")))
        if failed:
            name, why = failed[0]
            more = f" (and {len(failed) - 1} more)" if len(failed) > 1 else ""
            raise TidyError(f"Cannot remove {self}/{name}{more}, which no snapshot uses: {why}.", removed, failed)
        return removed

    def _tidy_tmp(self) -> None:
        """Remove the notes a writer that died left under ``tmp/``, two days on: one still at work writes its note again as it goes."""
        prefix = self._key(TMP_DIR) + "/"
        now = time.time()
        old = [entry["Key"] for entry in self._list(prefix) if now - _modified(entry) >= 2 * PENDING_FOLDER_SECONDS]
        if old:
            try:
                self._try_delete(old)
            except StoreError:
                pass  # left for the next gc

    def _tidy_origins(self, records: list[KeptRecord], now: float) -> None:
        """Remove each note of origins that no snapshot an owner made at its commit is left to use, an hour after it was written.

        Kept while a record at its commit cannot be read; and for an hour,
        as a snapshot made just now writes its note after the records were
        listed.
        """
        from chartbook.snapshot import record_name

        used = {
            f"{record.commit}/{record_name(record.subdirectory)}.txt" for record in records
            if record.readable and record.made_by == "snapshot"
        }
        doubt = {record.folder.name.rpartition("_")[2] for record in records if not record.readable}
        prefix = self._key(ORIGINS_DIR) + "/"
        gone = [
            entry["Key"] for entry in self._list(prefix)
            if entry["Key"][len(prefix):] not in used and entry["Key"][len(prefix):][:12] not in doubt
            and now - _modified(entry) >= PENDING_SECONDS
        ]
        if gone:
            self._try_delete(gone)
            if self._origins is not None:
                for key in gone:
                    self._origins.pop(key, None)

    def _origins_key(self, commit: str, name: str) -> str:
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        return self._key(ORIGINS_DIR, commit, f"{name}.txt")

    def note_origin(self, commit: str, name: str, top: str) -> None:
        key = self._origins_key(commit, name)
        self._check_layout(create=True)
        body = self._read(key)
        known = body.decode("utf-8").splitlines() if body is not None else []
        if top not in known:
            known.append(top)
            self._write(key, ("\n".join(known) + "\n").encode("utf-8"))
        if self._origins is not None:
            self._origins[key] = [line for line in known if line]

    def origins(self, commit: str, name: str) -> list[str]:
        """The repository folders a pipeline's snapshots at a commit were made from, as noted.

        Within a :meth:`reading` block, the notes there are are listed once,
        and each is read once.
        """
        key = self._origins_key(commit, name)
        self._check_layout()
        if self._reading:
            if self._origins is None:
                prefix = self._key(ORIGINS_DIR) + "/"
                self._origins = {entry["Key"]: None for entry in self._list(prefix)}
            if key not in self._origins:
                return []
            if self._origins[key] is not None:
                return list(self._origins[key])
        body = self._read(key)
        found = [line for line in body.decode("utf-8").splitlines() if line] if body is not None else []
        if self._reading and self._origins is not None:
            self._origins[key] = found
        return found

    # -- assets, by their hash ----------------------------------------------

    def has(self, content_hash: str, pipeline: Optional[str] = None) -> bool:
        """Whether the bucket holds an asset with this hash: a record names it and one of its files is there, or no pipeline owns it.

        Offline, whether the cache has it whole, as it was downloaded and checked.
        """
        _split_hash(content_hash)
        try:
            self._check_layout()
            own = self._pipeline_seen(pipeline)
            if own is not None and self._some_file_there(own, content_hash, pipeline):
                return True
            seen = self._seen()
        except StoreUnreachableError:
            if self._from_the_cache(content_hash, pipeline, lay_out=False) is not None:
                return True
            raise
        return self._some_file_there(seen, content_hash, pipeline) or bool(self._unowned_keys(content_hash, seen.listing))

    def _some_file_there(self, seen: _Seen, content_hash: str, pipeline: Optional[str]) -> bool:
        return any(
            seen.entry(self._where(file.location)) is not None
            for asset in self._held(seen, content_hash, pipeline) for file in asset.files
        )

    def get(self, content_hash: str, pipeline: Optional[str] = None, name: Optional[str] = None) -> Path:
        """A folder on this machine with the asset's files under their own names, downloaded if they were not yet.

        Each file is downloaded once into the cache, and its hash checked
        against its record's as it arrives; a copy whose sizes in the
        bucket are not its record's, or whose bytes are not, is passed over
        for the next. Offline, what the cache has whole is served.

        :param pipeline: The pipeline the asset is of, whose folder is
            looked in first.
        :param name: For an asset of one file, the name it is read by.
        :raises ObjectNotFoundError: If the store has no such asset.
        :raises StoreError: If no copy of it is all in the bucket yet, or
            none is what its record says; nothing of such a file is kept.
        """
        _split_hash(content_hash)
        try:
            self._check_layout()
            return self._fetch(content_hash, pipeline, name)
        except StoreUnreachableError:
            cached = self._from_the_cache(content_hash, pipeline, name)
            if cached is not None:
                return cached
            raise

    def _fetch(self, content_hash: str, pipeline: Optional[str], name: Optional[str]) -> Path:
        """The rest of :meth:`get`, online: its pipeline's folder first, then every one."""
        missing = wrong = None
        tried: set = set()
        own = self._pipeline_seen(pipeline)
        for seen in ([own] if own is not None else []) + [None]:
            seen = seen if seen is not None else self._seen()
            for asset in _named_first(self._held(seen, content_hash, pipeline), name):
                # The pipeline's own holds come again in every pipeline's: each copy is tried once
                copy = tuple(str(file.location) for file in asset.files)
                if copy in tried:
                    continue
                tried.add(copy)
                short = self._not_uploaded_file(asset, seen)
                if short is not None:
                    missing = missing or short[0]
                    continue  # the one `incomplete` judges whole is the one read
                try:
                    return self._for_a_reader(self._bring(asset, seen), name)
                except _NotItsBytes as error:
                    wrong = wrong or str(error)
        if wrong is not None:
            raise StoreError(
                f"{wrong}. Nothing of it is kept on this machine; `chartbook store verify` lists every such file."
            )
        remote = self._unowned_keys(content_hash, seen.listing)
        if missing is not None and not remote:
            raise StoreError(
                f"The store {self} {missing} of {content_hash}, though a snapshot's record names it: it is not "
                f"fully uploaded yet. Wait for whatever is copying it into the bucket to finish, and run this "
                f"again; if it stays so, making the snapshot again puts it back (`chartbook store verify` says more)."
            )
        if not remote:
            raise ObjectNotFoundError(f"The store {self} has no object {content_hash}.")
        return self._fetch_unowned(content_hash, remote)

    def _bring(self, asset: KeptAsset, seen: _Seen) -> KeptAsset:
        """An asset with each of its files in the cache's checked files, downloaded and checked where one is not.

        :raises _NotItsBytes: If a file downloaded is not what its record says.
        """
        for file in asset.files:
            if _is_there(self._checked(file.content_hash), file.size_bytes):
                continue
            entry = seen.entry(self._where(file.location))
            actual = self._download(entry["Key"], self._checked(file.content_hash), file.content_hash)
            if actual is not None:
                raise _NotItsBytes(
                    f"The file {file.path} of {asset.content_hash} in {self} is not what its snapshot's record says "
                    f"(it is {actual})"
                )
        return self._as_checked(asset)

    def _for_a_reader(self, asset: KeptAsset, name: Optional[str]) -> Path:
        """The folder a reader opens an asset in, laid out from the cache's checked files (:func:`chartbook.store.gather`)."""
        return gather(_read_as(asset, name), self.views)

    def _from_the_cache(
        self, content_hash: str, pipeline: Optional[str] = None, name: Optional[str] = None, lay_out: bool = True
    ) -> Optional[Path]:
        """Where the cache has an asset whole, as it was downloaded and checked; None if it has not.

        :param lay_out: Whether to lay it out for a reader. Without, nothing
            is made, and the path returned only says that it is there.
        """
        held = [
            asset for record in self._cached_records() if record.readable for asset in record.assets
            if asset.content_hash == content_hash
        ]
        held.sort(key=lambda asset: (asset.record.pipeline == pipeline, asset.record.made_at), reverse=True)
        for asset in _named_first(held, name):
            if all(_is_there(self._checked(file.content_hash), file.size_bytes) for file in asset.files):
                return self._for_a_reader(self._as_checked(asset), name) if lay_out else asset.record.path
        local = self._unowned_cache(content_hash)
        return local if local.is_dir() else None

    def _fetch_unowned(self, content_hash: str, remote: dict[str, dict]) -> Path:
        """Bring an object no pipeline owns into the cache, whole and checked, and return its folder.

        The cache's folder of it is only ever one that was checked: it is
        made anew in a temporary folder, from the files the cache has at
        the size the bucket gives and the rest downloaded, checked, and
        then put in place of the old. So a name added since is fetched, and
        a file the bucket does not have goes.

        :raises StoreError: If what the bucket holds does not hash to the
            object's name; the cache's folder of it is then left as it was.
        """
        local = self._unowned_cache(content_hash)
        have = _every_file(local)
        if have and have == {relative: entry["Size"] for relative, entry in remote.items()}:
            return local
        staging = self._root / TMP_DIR / uuid.uuid4().hex[:12]
        try:
            for relative, entry in sorted(remote.items()):
                target = _inside(staging, relative)
                if have.get(relative) == entry["Size"]:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _link(str(local.joinpath(*relative.split("/"))), str(target), ("hardlink", "copy"))
                else:
                    self._download(entry["Key"], target)
            message = what_is_wrong(content_hash, staging)
            if message is not None:
                raise StoreError(
                    f"The object {content_hash} in {self} is not what its name says: {message}. "
                    f"Nothing of it is kept on this machine; `chartbook store verify` lists every such object."
                )
            local.parent.mkdir(parents=True, exist_ok=True)
            if local.exists():
                aside = self._root / TMP_DIR / f"{uuid.uuid4().hex[:12]}.old"
                os.rename(local, aside)
                try:
                    os.rename(staging, local)
                finally:
                    _remove_tree(aside, own=True)
            else:
                os.rename(staging, local)
        finally:
            if staging.exists():
                _remove_tree(staging, own=True)
        return local

    def put(self, path: Union[str, Path], links: Iterable[str] = LINKS) -> StoredObject:
        """Copy what a declared ``path`` names into the cache, hash it, and upload it as an object no pipeline owns.

        What a snapshot holds is put by :meth:`begin` instead, into the
        pipeline's folder. *links* is read for its errors only: a remote
        store holds copies, whatever was asked for. An object the bucket
        already has is written again (one key of it, its metadata only where
        the service allows), so that it counts as stored now and ``gc`` does
        not take it from under a pin in progress.
        """
        links = tuple(links)
        unknown = [kind for kind in links if kind not in LINKS]
        if unknown or not links:
            raise ValueError(f"Unknown link kind(s) {unknown}. The kinds are: {', '.join(LINKS)}.")
        found = hashing.find_files(path)
        if found is None or not found.files:
            raise FileNotFoundError(f"Nothing at {path} to put in the store.")
        self._check_layout(create=True)
        staging = self._root / TMP_DIR / uuid.uuid4().hex[:12]
        staging.mkdir(parents=True)
        try:
            root = os.path.abspath(found.root)
            for file in found.files:
                relative = os.path.relpath(os.path.abspath(file), root)
                if found.single:
                    # Under the one name every system reads it by (declared_name)
                    relative = declared_name(relative) or relative
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                _link(os.path.realpath(file), str(destination), ("reflink", "copy"))
            files = sorted(file.relative_to(staging).as_posix() for file in hashing.directory_files(staging))
            if found.single:
                content = hashing.hash_file(staging / (declared_name(found.files[0].name) or found.files[0].name))
            else:
                content = hashing.hash_directory(staging)
            prefix = self._unowned_prefix(content.content_hash)
            folder = prefix.rstrip("/")[len(PIPELINES_DIR) + 1:]
            remote = self._unowned_keys(content.content_hash, self._seen(folder, fresh=True).listing)
            missing = [relative for relative in files if relative not in remote]
            for relative in missing:
                self._upload(staging / relative, self._key(prefix + relative))
            if not missing:
                # One key written again is enough: an object is as old as its newest key
                smallest = min(remote, key=lambda relative: remote[relative]["Size"])
                self._touch(self._key(prefix + smallest), remote[smallest]["Size"])
            local = self._unowned_cache(content.content_hash)
            FolderStore._move_into_place(staging, local, single=found.single)
        finally:
            if staging.exists():
                _remove_tree(staging, own=True)
        created = not remote
        return StoredObject(
            content_hash=content.content_hash,
            size_bytes=content.size_bytes,
            path=local,
            files=tuple(files),
            links=("copy",) if created else (),
            created=created,
            entries=content.files,
        )

    def delete(self, content_hash: str) -> bool:
        """Remove the asset with this hash from the bucket and from the cache: its files, and its object if no pipeline owns it.

        As in a folder store, a record that held it then names it without
        holding it, and a file another asset has too goes with it.
        """
        _split_hash(content_hash)
        self._check_layout()
        seen = self._seen(fresh=True)
        held = self._held(seen, content_hash)
        keys = sorted({
            entry["Key"] for asset in held for file in asset.files
            for entry in [seen.entry(self._where(file.location))] if entry is not None
        })
        # Every key under an object no pipeline owns, its files and any that are not (a folder marker too)
        keys += [entry["Key"] for entry in self._unowned_keys(content_hash, seen.listing, plain=False).values()]
        if keys:
            self._delete_keys(keys)
        for asset in held:
            for file in asset.files:
                _remove_file(self._checked(file.content_hash))
        self._forget_cached(content_hash)
        return bool(keys)

    def delete_unowned(self, content_hash: str) -> bool:
        """Remove the object no pipeline owns with this hash, every key under it, and nothing a snapshot's record names; True if there was one."""
        _split_hash(content_hash)
        self._check_layout()
        keys = [entry["Key"] for entry in self._list(self._key(self._unowned_prefix(content_hash)))]
        if not keys:
            return False
        self._delete_keys(keys)
        self._forget_cached(content_hash)
        return True

    def _forget_cached(self, content_hash: str) -> None:
        """Remove the cache's object of this hash and its view, the bucket's being gone."""
        for folder in (self._unowned_cache(content_hash), self.views / content_hash.split(":", 1)[1]):
            if folder.exists() and not folder.is_symlink():
                _remove_tree(folder, own=True)
        _found_whole.discard((self.url, content_hash))

    def hashes(self) -> Iterator[str]:
        """The hash of every asset in the bucket, in order: what its records hold, and the objects no pipeline owns."""
        self._check_layout()
        seen = self._seen()
        found = {asset.content_hash for record in self._records_of(seen) if record.readable for asset in record.assets}
        for name in seen.listing:
            parts = name.split("/", 3)
            if len(parts) == 4 and parts[1] == UNOWNED_DIR and _HEX.match(parts[2]):
                found.add(hashing.format_hash(parts[2]))
        yield from sorted(found)

    def held_hashes(self) -> set[str]:
        return {asset.content_hash for record in self.records() if record.readable for asset in record.assets}

    def files_of(self, content_hash: str) -> list[tuple[str, int]]:
        """Where the bucket keeps an asset's files, every copy any record names, each as its name in the store and its size."""
        self._check_layout()
        found: dict = {}
        for asset in self._held(self._seen(), content_hash):
            for file in asset.files:
                found.setdefault(self._where(file.location), file.size_bytes)
        return sorted(found.items())

    def size_of(self, content_hash: str) -> int:
        """The total size in bytes of an asset's files, as its newest record gives them, or of every key of its object."""
        self._check_layout()
        seen = self._seen()
        held = self._held(seen, content_hash)
        if held:
            return sum(file.size_bytes for file in held[0].files)
        # Every key under the object, as gc removes every one
        return sum(entry["Size"] for entry in self._unowned_keys(content_hash, seen.listing, plain=False).values())

    def age_of(self, content_hash: str, now: Optional[float] = None) -> float:
        """Seconds since an asset was put in the bucket: its newest record was written, or a key of its object.

        :raises ObjectNotFoundError: If the store has no such asset: one
            removed since it was listed, by another ``gc``.
        """
        self._check_layout()
        seen = self._seen()
        held = self._held(seen, content_hash)
        entries = [entry for asset in held for entry in [seen.listing.get(self._where(asset.record.path))] if entry is not None]
        entries += list(self._unowned_keys(content_hash, seen.listing, plain=False).values())
        if not entries:
            raise ObjectNotFoundError(f"The store {self} has no object {content_hash}.")
        newest = max(_modified(entry) or time.time() for entry in entries)
        return (time.time() if now is None else now) - newest

    def lacks(self, content_hash: str, names: Iterable[str], single: bool = True) -> bool:
        """Whether an object no pipeline owns, of one file, lacks a key under this name: a put of the same bytes uploads it.

        What a snapshot holds lacks nothing: its record names each file.
        """
        names = list(names)
        if not single or len(names) != 1:
            return False
        self._check_layout()
        folder = self._unowned_prefix(content_hash).rstrip("/")[len(PIPELINES_DIR) + 1:]
        remote = self._unowned_keys(content_hash, self._seen(folder).listing)
        return bool(remote) and names[0] not in remote

    def incomplete(
        self, content_hash: str, size_bytes: Optional[int], files: Optional[dict] = None, every: bool = False
    ) -> Optional[str]:
        """Why an asset is not whole as its record has it, by the keys a listing gives and their sizes; None if it is.

        Nothing is downloaded. Each file a snapshot's record names is
        compared with its key; an object no pipeline owns, with what
        *size_bytes* and *files* say. Offline, an asset this machine
        downloaded and checked before is whole.
        """
        _split_hash(content_hash)
        # An asset is named by its content and does not change: one found
        # whole is not looked at again in this process
        if (self.url, content_hash) in _found_whole:
            return None
        try:
            self._check_layout()
            seen = self._seen()
        except StoreUnreachableError:
            if self._from_the_cache(content_hash, lay_out=False) is not None:
                return None
            raise
        held = self._held(seen, content_hash)
        if held:
            wrong = None
            for asset in held:
                wrong = self._not_uploaded_file(asset, seen)
                if wrong is None:
                    _found_whole.add((self.url, content_hash))
                    return None
            what, waiting = wrong
            if not waiting:
                return f"its file in {self} {what}; `chartbook store verify` checks the rest"
            return (
                f"its file in {self} {what}: it is not fully uploaded yet. A snapshot's files go into the bucket "
                f"before its record, so this one is on its way (a copy of a store into the bucket that has not "
                f"finished: wait for it, and run this again) or was removed since (making the snapshot again puts "
                f"it back; `chartbook store verify` says more)"
            )
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
            return None
        sought = (self.url, content_hash, size_bytes, tuple(sorted((files or {}).items())), every)
        if sought in _found_whole:
            return None
        remote = {relative: entry["Size"] for relative, entry in self._unowned_keys(content_hash, seen.listing).items()}
        if not remote:
            return None  # not there at all, which `has` says
        wrong = self._not_uploaded(content_hash, remote, size_bytes, files, every)
        if wrong is None:
            _found_whole.add(sought)
            return None
        what, waiting = wrong
        if not waiting:
            return f"its object in {self} {what}; `chartbook store verify` checks the rest"
        return (
            f"its object in {self} {what}: it is not fully uploaded yet. An object of several files is "
            f"uploaded one file at a time: if it is being put now, wait for that to finish and run this "
            f"again; one interrupted while uploading is completed by putting it again (if it stays so, "
            f"`chartbook store verify` says more)"
        )

    def _not_uploaded_file(self, asset: KeptAsset, seen: _Seen) -> Optional[tuple[str, bool]]:
        """What of an asset's files is not in the bucket as its record has it, and whether an upload on its way would explain it; None when all are.

        A key is written whole or not at all, so one of another size than
        the record gives holds other bytes, which no upload mends.
        """
        for file in asset.files:
            entry = seen.entry(self._where(file.location))
            if entry is None:
                return f"does not have {file.path} yet", True
            if entry["Size"] != file.size_bytes:
                return (
                    f"has {entry['Size']:,} bytes of {file.path} where its record says {file.size_bytes:,} (the key "
                    f"was written over, or the record is not of these files)",
                    False,
                )
        return None

    def _not_uploaded(
        self, content_hash: str, remote: dict[str, int], size_bytes: int, files: Optional[dict], every: bool
    ) -> Optional[tuple[str, bool]]:
        """What of the keys of an object no pipeline owns is not as a record gives it, in a few words; None when nothing is.

        *remote* is each key under the object, by its path in it, with its
        size. The rules are :func:`chartbook.store.unsynced_part`'s: the one
        file of an asset that is a file, under its own name (the object may
        hold the same bytes under other names, which other puts added); each
        file of a directory, and *every* key then listed; without *files*,
        the sizes summed. Names are compared in Unicode's one form, as a
        folder store synced into the bucket may carry the other.

        One difference from a folder: a key is written whole or not at all,
        so a key of another size than the record gives holds other bytes
        (written over, or the record is not of this object), which no
        upload mends; and a sum short of the record's is keys still to come,
        where one over it is a key the record does not list.

        :returns: What is wrong, and whether an upload that has not finished
            would explain it.
        """
        by_name = {unicodedata.normalize("NFC", relative): size for relative, size in remote.items()}
        if files and len(files) == 1 and not every:
            ((relative, expected),) = files.items()
            if unicodedata.normalize("NFC", relative) not in by_name:
                top = {name: size for name, size in by_name.items() if "/" not in name}
                # The same bytes under other names (every key at the top, of the
                # size the record gives), and this one on its way; where there is
                # one other name only, the cached copy, if there is one, tells it
                # from a directory put with one file
                same = top and len(top) == len(by_name) and all(size == expected for size in top.values())
                if same and (len(top) > 1 or self._cached_hashes_to(content_hash, next(iter(remote)))):
                    return f"does not have {relative} yet", True
                files = None
        if files:
            listed = set()
            for relative, expected in sorted(files.items()):
                parts = _plain_parts(relative)
                if parts is None:
                    return (
                        f"is named by a record that lists {relative!r}, which is not a plain path in it: "
                        f"the record is not one a store wrote",
                        False,
                    )
                name = unicodedata.normalize("NFC", "/".join(parts))
                listed.add(name)
                size = by_name.get(name)
                if size is None:
                    return f"does not have {relative} yet", True
                if size != expected:
                    return (
                        f"has {size:,} bytes of {relative} where its record says {expected:,} (the key was written "
                        f"over, or the record is not of this object)",
                        False,
                    )
            if every:
                for name in sorted(by_name):
                    # A name starting "." no reader reads, as in a folder
                    if any(part.startswith(".") for part in name.split("/")):
                        continue
                    if name not in listed:
                        return (
                            f"holds {name}, which its record does not list (a sync service's copy that a sync of "
                            f"a folder store brought, or a key put there by hand, which a reader of the folder "
                            f"would read as its own: remove it from the bucket)",
                            False,
                        )
            return None
        total = sum(remote.values())
        if total != size_bytes:
            return f"has {total:,} bytes where its record says {size_bytes:,}", total < size_bytes
        return None

    def _cached_hashes_to(self, content_hash: str, relative: str) -> bool:
        """Whether this machine's cached copy of a key of an object hashes to the object's name: the same bytes under another name."""
        parts = _plain_parts(relative)
        if parts is None:
            return False
        cached = self._unowned_cache(content_hash).joinpath(*parts)
        return cached.is_file() and _hash_once(cached) == content_hash

    def verify(self, content_hashes: Optional[Iterable[str]] = None) -> list[StoreProblem]:
        """Download every asset again, into a temporary folder, and report each that is not what its record or name says.

        The cache is left as it is: what this machine read and checked
        stays readable, and the problems are the bucket's. What is
        downloaded is removed once it is checked, so the disk holds one
        asset at a time.
        """
        self._check_layout()
        with self.reading():
            seen = self._seen()
            if content_hashes is None:
                content_hashes = list(self.hashes())
            problems = []
            for content_hash in content_hashes:
                held = self._held(seen, content_hash)
                if held:
                    message = None
                    for asset in held:
                        message = self._check_anew(asset, seen)
                        if message is None:
                            break
                    if message is not None:
                        problems.append(StoreProblem(content_hash, held[0].record.folder, message))
                    continue
                where = self._unowned_cache(content_hash)
                remote = self._unowned_keys(content_hash, seen.listing)
                if not remote:
                    problems.append(StoreProblem(content_hash, where, "not in the store"))
                    continue
                scratch = self._root / TMP_DIR / uuid.uuid4().hex[:12]
                try:
                    for relative, entry in sorted(remote.items()):
                        self._download(entry["Key"], _inside(scratch, relative))
                    message = what_is_wrong(content_hash, scratch)
                finally:
                    if scratch.exists():
                        _remove_tree(scratch, own=True)
                if message is not None:
                    problems.append(StoreProblem(content_hash, where, message))
            return problems

    def _check_anew(self, asset: KeptAsset, seen: _Seen) -> Optional[str]:
        """What is wrong with an asset as one record holds it, its files downloaded afresh (:func:`chartbook.store.what_is_wrong_with`)."""
        scratch = self._root / TMP_DIR / uuid.uuid4().hex[:12]
        try:
            files = []
            for number, file in enumerate(asset.files):
                there = scratch / str(number)
                entry = seen.entry(self._where(file.location))
                if entry is not None:
                    self._download(entry["Key"], there)
                files.append(dataclasses.replace(file, location=there))
            return what_is_wrong_with(dataclasses.replace(asset, files=tuple(files)))
        finally:
            if scratch.exists():
                _remove_tree(scratch, own=True)

    # -- roots ------------------------------------------------------------

    def _root_key(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> str:
        return self._key(ROOTS_DIR, root_name(lockfile, this_machine() if machine is None else machine))

    def add_root(
        self,
        lockfile: Union[str, Path],
        hashes: Iterable[str],
        snapshots: Iterable[tuple[str, str]] = (),
        machine: Optional[str] = None,
        labelled: Iterable[tuple[str, str, str, str]] = (),
    ) -> None:
        hashes = sorted(set(hashes))
        for content_hash in hashes:
            _split_hash(content_hash)
        self._check_layout(create=True)
        machine = this_machine() if machine is None else machine
        document = root_document(lockfile, hashes, snapshots, machine, labelled)
        self._write(self._root_key(lockfile, machine), (json.dumps(document, indent=1) + "\n").encode())

    def _read_note(self, key: str) -> Optional[Root]:
        body = self._read(key)
        try:
            return read_root(json.loads(body.decode("utf-8")), key.rpartition("/")[2]) if body is not None else None
        except (ValueError, KeyError, TypeError):
            return None

    def root_of(self, lockfile: Union[str, Path], machine: Optional[str] = None) -> Optional[Root]:
        self._check_layout()
        return self._read_note(self._root_key(lockfile, this_machine(create=False) if machine is None else machine))

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
                detail = "the file is empty" if body == b"" else str(error)
                raise StoreError(
                    f"Cannot read {self}/{entry['Key']}: {detail}.{_unreadable_note_remedy(name, error)}"
                ) from None
        return sorted(found, key=lambda root: (str(root.lockfile), root.machine, root.note))


class _S3Pending(PendingSnapshot):
    """A snapshot being written into a bucket (:meth:`S3Store.begin`).

    As :class:`chartbook.store.PendingSnapshot` says: each file is kept
    once in the pipeline's folder, a new one uploaded into this snapshot's
    folder at its path, and the record last. A file uploaded is kept in the
    cache's checked files too, so this machine does not download it again.

    The folder is claimed before anything goes into it, record or file
    (``_chartbook/CLAIMED.txt``, written only if nothing is there), and
    noted under ``tmp/`` before it is claimed. Before a put takes files
    earlier snapshots keep, it notes them. Before the record is written,
    each file taken is confirmed to be one a record of the pipeline still
    names (``store gc`` clears a record before the files no record names),
    and is uploaded into this snapshot's own folder if it is not; what was
    taken and has gone meanwhile is put back, before the record and after.
    """

    def __init__(self, store: S3Store, pipeline: str, commit: str, made_at: str, base, made_by: str):
        from chartbook.identity import validate_pipeline_id

        validate_pipeline_id(pipeline)
        if not _FULL_COMMIT.match(commit):
            raise ValueError(f"{commit!r} is not a full commit hash.")
        if made_by not in ("snapshot", "pin"):
            raise ValueError(f"{made_by!r} is not who makes a snapshot: 'snapshot' or 'pin'.")
        snapshot_folder_name(made_at, commit)  # a time a snapshot writes, or ValueError
        self.store = store
        self.pipeline = pipeline
        self.commit = commit
        self.made_at = made_at
        self.made_by = made_by
        self.base = Path(os.path.abspath(base)) if base is not None else None
        self.folder = pipeline_folder(pipeline)
        self.name: Optional[str] = None
        self.placed = False
        self._written = False
        self._kept: Optional[dict] = None
        self._here: dict[str, str] = {}
        self._uploaded: list[str] = []
        self._claim_key: Optional[str] = None
        #: What its claim says, with a mark of its own: a claim met again is known for this one's
        self._claim_text = (
            f"Claimed on {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC for a snapshot being made "
            f"({uuid.uuid4().hex[:12]}).\nIts record, _chartbook/snapshot.json, comes last. A folder whose record "
            f"never comes is\nremoved by `chartbook store gc` a day after anything in it last changed.\n"
        ).encode("utf-8")
        self._note: Optional[str] = None
        self._lines: list[str] = []
        self._noted_at = 0.0
        #: Hashes already known, by the source file's path, which are then not read again
        self.known: dict[str, str] = {}
        #: Each file of an earlier snapshot used where it is: its name, the file it came from, its hash
        self._reused: list[tuple[str, str, str]] = []
        #: Each of those as the record about to be written has it, with the file it came from
        self._took: list[tuple[dict, str]] = []

    def _taken(self) -> set[str]:
        """The snapshots' folders the pipeline has in the bucket, and those this process has claimed."""
        prefix = self.store._key(PIPELINES_DIR, self.folder) + "/"
        taken = {common["Prefix"][len(prefix):].rstrip("/") for common in self.store._list(prefix, delimiter="/")}
        return taken | {name for folder, name in self.store._claimed if folder == self.folder}

    def _claim(self) -> str:
        """This snapshot's folder's name, claimed the first time it is needed: its time, the next free second if another has it, and its commit."""
        if self.name is None:
            taken = self._taken()
            for later in range(86400):
                name = snapshot_folder_name(self.made_at, self.commit, later)
                if name in taken:
                    continue
                # Noted first, so that `store gc` never meets the folder without its note
                self._note_line(f"{FOLDER_MARK}{PIPELINES_DIR}/{self.folder}/{name}")
                key = self.store._key(PIPELINES_DIR, self.folder, name, OWN_DIR, CLAIMED_FILE)
                if not self.store._put_new(key, self._claim_text):
                    continue  # another snapshot's claim
                # A folder listed a moment ago may have filled since, its claim gone with its record written
                there = [entry["Key"] for entry in self.store._list(self.store._key(PIPELINES_DIR, self.folder, name) + "/")]
                if there == [key]:
                    self.name, self._claim_key = name, key
                    break
                try:
                    self.store._try_delete([key])
                except StoreError:
                    pass  # beside a snapshot's files, `store gc` takes it an hour on
            else:
                raise StoreError(f"No folder is free for a snapshot of {self.pipeline} in the store {self.store}.")
            self.store._claimed.add((self.folder, self.name))
        return self.name

    def _kept_files(self) -> dict:
        """Every file the pipeline's snapshots keep, by its hash."""
        if self._kept is None:
            self._kept = {}
            for record in self.store._records_of(self.store._seen(self.folder)):
                if record.readable:
                    for asset in record.assets:
                        for file in asset.files:
                            self._kept.setdefault(file.content_hash, []).append(file)
        return self._kept

    def _note_line(self, *lines: str) -> None:
        """Add to this snapshot's note under ``tmp/``, written whole when it gains a line, or to say it is alive."""
        if self._note is None:
            self._note = f"{uuid.uuid4().hex[:12]}{PENDING_SUFFIX}"
        new = [line for line in lines if line not in self._lines]
        if lines and not new:
            return
        self.store._write(self.store._key(TMP_DIR, self._note), ("\n".join(self._lines + new) + "\n").encode("utf-8"))
        self._lines += new
        self._noted_at = time.monotonic()

    def _alive(self) -> None:
        """Say, by the note's time, that this snapshot is still being made: a slow one is not taken for one given up."""
        if self._note is not None and time.monotonic() - self._noted_at > ALIVE_SECONDS:
            self._note_line()

    def _drop_note(self) -> None:
        if self._note is not None:
            try:
                self.store._try_delete([self.store._key(TMP_DIR, self._note)])
            except StoreError:
                pass  # it is old in a day, and kept nothing since
            self._note = None
            self._lines = []

    def _write_file(self, source: str, name: str, links: tuple, expect: Optional[str] = None) -> tuple[str, str, int]:
        """Upload one file to its name in the store, from a copy in the cache that is hashed first; its hash, how the copy was made, and its size.

        :param expect: The hash the file must have to go there (a file a
            record names, put back): bytes that are not it are not
            uploaded, and the hash returned says so. Another snapshot
            putting the same file back at the same moment writes the same
            bytes.
        """
        temporary = self.store.cache / TMP_DIR / f"{uuid.uuid4().hex[:12]}.part"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        try:
            kind = _link(source, str(temporary), links)
            content_hash = hashing.format_hash(hashing._file_hex(temporary))
            size = os.stat(temporary).st_size
            if expect is None or content_hash == expect:
                self.store._upload(temporary, self.store._key(name))
                self.store._check_in(temporary, content_hash)
        finally:
            if os.path.lexists(temporary):
                _remove_file(temporary)
        return content_hash, kind, size

    def _keep(self, source: str, path: str, content_hash: str, size: int, links: tuple, used: set, seen: _Seen) -> dict:
        """Keep one file at *path* in the pipeline, once: where an earlier snapshot keeps it, or new in this one's folder."""
        self._alive()
        if content_hash in self._here:
            kept_as = self._here[content_hash]
            entry = {"path": path, "content_hash": content_hash, "size_bytes": size, "kept_in": self._claim()}
            if kept_as != path:
                entry["kept_as"] = kept_as
            return entry
        holes = []
        for file in self._kept_files().get(content_hash, []):
            if file.size_bytes != size:
                continue
            name = self.store._where(file.location)
            there = seen.entry(name)
            if there is None:
                holes.append(name)
            elif there["Size"] == size:
                self._reused.append((name, source, content_hash))
                entry = self._entry(path, content_hash, size, name)
                self._took.append((entry, source))
                return entry
        for name in holes:
            # A file a record names that is missing (removed by hand, or by
            # `store delete`): put back where the record says, so that it is whole again
            if seen.entry("/".join(name.split("/")[:3] + [_RECORD])) is None:
                continue
            written, kind, _ = self._write_file(source, name, links, expect=content_hash)
            if written == content_hash:
                used.add(kind)
                self._reused.append((name, source, content_hash))
                entry = self._entry(path, content_hash, size, name)
                self._took.append((entry, source))
                return entry
            content_hash = written  # the bytes changed since they were hashed: new, in this snapshot's folder
        target = f"{PIPELINES_DIR}/{self.folder}/{self._claim()}/{path}"
        written, kind, size = self._write_file(source, target, links)
        self._uploaded.append(self.store._key(target))
        used.add(kind)
        self.placed = True
        self._here.setdefault(written, path)
        return {"path": path, "content_hash": written, "size_bytes": size, "kept_in": self.name}

    def _entry(self, path: str, content_hash: str, size: int, name: str) -> dict:
        kept_in, kept_as = name.split("/", 3)[2:]
        entry = {"path": path, "content_hash": content_hash, "size_bytes": size, "kept_in": kept_in}
        if kept_as != path:
            entry["kept_as"] = kept_as
        return entry

    def put(self, path: Union[str, Path], place: Optional[str] = None, links: Iterable[str] = ("reflink", "copy")) -> StoredObject:
        if self._written:
            raise StoreError("This snapshot is written; nothing more goes into it.")
        found = hashing.find_files(path)
        if found is None or not found.files:
            raise FileNotFoundError(f"Nothing at {path} to put in the store.")
        derived = place is None
        if derived:
            if self.base is None:
                raise ValueError("Where it goes in the pipeline's folder is not known: give its place.")
            named = found.files[0] if found.single else found.root
            place = os.path.relpath(os.path.abspath(named), self.base)
        place = "" if place in (".", "") else str(place).replace("\\", "/") if os.name == "nt" else str(place)
        parts = _plain_parts(place) if place else []
        if parts is None or (derived and parts and parts[0] == OWN_DIR):
            raise StoreError(
                f"{path} is not a plain path inside the pipeline's folder ({place!r}), or is under {OWN_DIR}/, "
                f"the name a snapshot's folder keeps for ChartBook; it is not put in the store."
            )
        root = os.path.abspath(found.root)
        if found.single:
            listed = [(declared_name(place.rpartition("/")[2]) or place.rpartition("/")[2], os.path.realpath(found.files[0]))]
        else:
            listed = [
                (relative, os.path.realpath(file))
                for file in sorted(found.files)
                for relative in [Path(os.path.relpath(os.path.abspath(file), root)).as_posix()]
                if not hashing.is_ignored(relative)
            ]
        return self.put_listed(listed, place, found.single, links)

    def put_listed(self, listed: list, place: str, single: bool, links: Iterable[str] = ("reflink", "copy")) -> StoredObject:
        """Store an asset given as its files, each ``(its path in the asset, the file to take it from)``, at *place* (:meth:`chartbook.store.FolderStore` has the same).

        :param place: For one file (*single*), its path in the pipeline;
            else the folder the files' paths are under.
        """
        if self._written:
            raise StoreError("This snapshot is written; nothing more goes into it.")
        # The store keeps only its own bytes: a clone or a copy, never a link to a file outside it
        links = tuple(kind for kind in links if kind in FROZEN_LINKS) or ("copy",)
        self._alive()
        if single:
            ((name, source),) = listed
            at = place.rpartition("/")[0]
            files = [(name, source, f"{at}/{name}" if at else name)]
        else:
            files = [(relative, source, f"{place}/{relative}" if place else relative) for relative, source in listed]
        hashed = [
            (self.known.get(source) or hashing.format_hash(hashing._file_hex(Path(source))), os.stat(source).st_size)
            for _, source, _ in files
        ]
        # What earlier snapshots keep is noted before it is taken; what is taken is confirmed before the record
        kept = self._kept_files()
        wanted = [
            self.store._where(file.location) for content_hash, size in hashed if content_hash not in self._here
            for file in kept.get(content_hash, []) if file.size_bytes == size
        ]
        if wanted:
            self._note_line(*wanted)
        seen = self.store._seen(self.folder)
        used: set = set()
        entries = [
            self._keep(source, path, content_hash, size, links, used, seen)
            for (_, source, path), (content_hash, size) in zip(files, hashed)
        ]
        if single:
            (entry,) = entries
            stored = {"at": at, "single": True, "files": [entry]}
            content_hash, size_bytes, files_held, names = entry["content_hash"], entry["size_bytes"], (), (files[0][0],)
        else:
            stored = {"at": place, "files": entries}
            content = hashing.hash_listing(
                hashing.FileEntry(relative, entry["size_bytes"], entry["content_hash"])
                for (relative, _, _), entry in zip(files, entries)
            )
            content_hash, size_bytes, files_held = content.content_hash, content.size_bytes, content.files
            names = tuple(sorted(relative for relative, _, _ in files))
        return StoredObject(
            content_hash=content_hash,
            size_bytes=size_bytes,
            path=self.store.cache / PIPELINES_DIR / self.folder / (self.name or "") / place,
            files=names,
            links=tuple(kind for kind in LINKS if kind in used),
            created=bool(used),
            entries=files_held,
            stored=stored,
        )

    def _confirm(self, seen: _Seen) -> None:
        """See that each file of an earlier snapshot this one has taken is still named by a record of the pipeline, now that its use is noted.

        Done once, before the record is written, from a listing of the
        pipeline's folder taken after the notes. The entries are the ones in
        the record about to be written, so a file uploaded here instead is
        named there too. ``store gc`` clears a snapshot's record before it
        removes the files no record names, and keeps what a note names: one
        cleared before the note was read may lose its files.
        """
        taken = [(entry, source) for entry, source in self._took if entry.get("kept_in") != self.name]
        if not taken:
            return
        named = {
            _folded(self.store._where(path)) for record in self.store._records_of(seen) if record.readable
            for path in record.mentioned
        }
        for entry, source in taken:
            name = f"{PIPELINES_DIR}/{self.folder}/{entry['kept_in']}/{entry.get('kept_as', entry['path'])}"
            if _folded(name) in named:
                continue
            target = f"{PIPELINES_DIR}/{self.folder}/{self._claim()}/{entry['path']}"
            if self.store._key(target) not in self._uploaded:
                written, _, _ = self._write_file(source, target, ("reflink", "copy"), expect=entry["content_hash"])
                if written != entry["content_hash"]:
                    raise StoreError(f"{source} changed while a snapshot of {self.pipeline} was made: make it again.")
                self._uploaded.append(self.store._key(target))
            self.placed = True
            self._here.setdefault(entry["content_hash"], entry["path"])
            self._reused = [reuse for reuse in self._reused if reuse[0] != name]
            entry["kept_in"] = self.name
            entry.pop("kept_as", None)

    def _refill(self, seen: Optional[_Seen] = None) -> None:
        """Put back a file of an earlier snapshot this one uses, if it went while this one was made (a ``store gc`` elsewhere)."""
        if not self._reused:
            return
        seen = seen if seen is not None else self.store._seen(self.folder, fresh=True)
        for name, source, content_hash in self._reused:
            if seen.entry(name) is not None:
                continue
            if not os.path.isfile(source):
                raise StoreError(
                    f"{self.store}/{name} went from the store while a snapshot of {self.pipeline} was made, which uses "
                    f"it, and {source} is no longer there to put it back from. Make the snapshot again."
                )
            written, _, _ = self._write_file(source, name, ("reflink", "copy"), expect=content_hash)
            if written != content_hash:
                raise StoreError(f"{source} changed while a snapshot of {self.pipeline} was made: make it again.")

    def write(self, document: dict) -> Path:
        if self._written:
            raise StoreError("This snapshot is written already.")
        if self.made_by != "snapshot" and "made_by" not in document:
            # Said just after when it was made, for a person reading it
            written = {}
            for name, value in document.items():
                written[name] = value
                if name == "made_at":
                    written["made_by"] = self.made_by
            written.setdefault("made_by", self.made_by)
            document = written
        # Claimed, as any folder is before anything goes into it, a record alone too
        self._claim()
        self._alive()
        seen = self.store._seen(self.folder, fresh=True)
        self._confirm(seen)
        self._refill(seen)
        body = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        key = self.store._key(PIPELINES_DIR, self.folder, self.name, _RECORD)
        if not self.store._put_new(key, body):
            raise StoreError(
                f"{self.store}/{PIPELINES_DIR}/{self.folder}/{self.name}/ has a record already, though this snapshot "
                f"claimed the folder: something else wrote one there. Make the snapshot again."
            )
        self._written = True
        self._refill()  # a `store gc` between the check and the record
        try:
            self.store._try_delete([self._claim_key])  # the record says now what the claim said
        except StoreError:
            pass  # a writer that may not delete: `store gc` takes the claim with the folder's other leftovers
        self._drop_note()
        local = self.store._local(key)
        self.store._keep_locally(local, body, _md5_tag(body))
        return local

    def discard(self) -> None:
        if self._written:
            return
        keys = self._uploaded + ([self._claim_key] if self._claim_key is not None else [])
        if keys:
            try:
                self.store._try_delete(keys)
            except StoreError:
                pass  # `store gc` clears a folder that has no record, a day on
        self.name = None
        self._claim_key = None
        self._uploaded = []
        self.placed = False
        self._drop_note()
