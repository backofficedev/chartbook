"""Models: the front door for trained models a pipeline declares.

A model is a file, or a directory of files, that a pipeline produces and
declares in ``[models]``. ChartBook records where it is, what it was trained
on and its scores. It does not know what is inside: it never loads, runs or
serves a model, and it imports no machine-learning framework. Loading is one
line of your own code::

    import joblib
    from chartbook import models

    model = joblib.load(models.path("rate_forecaster"))

Every function here takes a model and nothing else, as
:mod:`chartbook.data` does for dataframes. :mod:`chartbook.assets` is the
general module.

**Versions.** A version of a model is made by a snapshot
(``chartbook run --snapshot``): the first snapshot that holds new bytes for
the model. It is named by the start of its content hash, so the name is
the same on every machine and every branch, and a label in the manifest
gives it a name people use::

    [models.rate_forecaster.aliases]
    champion = "7f3a9c2e41b0"

    models.path("rate_forecaster")             # what is in the folder now
    models.path("rate_forecaster@7f3a9c2e41b0")     # that version, in the store
    models.path("rate_forecaster@champion")    # the version the label points at
    models.versions("rate_forecaster")         # all of them, oldest first

The design, including what is deliberately not done, is
``docs_src/design/models.md``.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from chartbook import assets as _assets
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import caller_start_dirs


def path(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path the manifest declares for a model of the current pipeline.

    >>> from chartbook import models
    >>> models.path("rate_forecaster")  # doctest: +SKIP

    This is :func:`chartbook.assets.path` with ``kind="model"``: it answers
    for models and nothing else. The path is the model file, or the
    directory that holds the model's files. Nothing checks that it exists,
    so training code can ask where to write before anything is there.

    A model of another pipeline is named with the pipeline in front,
    ``models.path("forecasting:rate_forecaster")``, and is the copy that
    ``chartbook.lock`` pins; see :func:`chartbook.assets.path`.

    A version of one of this pipeline's models is named after ``@``:
    ``models.path("rate_forecaster@7f3a9c2e41b0")``, by the start of its content
    hash, or ``models.path("rate_forecaster@champion")``, by a label of
    ``[models.rate_forecaster.aliases]``. That path is in the store, is
    read-only, and does not change.

    :param ref: The model's name: its key in ``[models]``.
    :type ref: str
    :param project_dir: Where to look for the pipeline, as for
        :func:`chartbook.assets.path`.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path declared for the model.
    :rtype: Path
    :raises AssetNotDeclaredError: If the manifest declares no such model.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises VersionNotFoundError: If the reference names a version that is
        not on this machine.
    :raises ValueError: If the reference names another kind of asset, uses
        reserved syntax, or the entry has no ``path``.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    try:
        return _assets._path(ref, "model", start_dirs)
    except KindMismatchError as e:
        raise KindMismatchError(
            str(ref),
            e.found,
            e.expected,
            hint=(
                f"models.path() answers for models only; use "
                f"chartbook.assets.path({str(ref)!r}) for a {e.found}."
            ),
        ) from None


def read_metrics(metrics_path: Union[str, Path]) -> dict:
    """Read a model's metrics file: one flat JSON object of scores.

    ::

        { "rmse": 0.214, "mae": 0.171, "n_train": 5120, "n_test": 1280 }

    Scores are in a file, not in ``chartbook.toml``, because they are an
    output: they change every time the model is retrained.

    :param metrics_path: The file a model's ``metrics_path`` names.
    :returns: The scores, by name.
    :raises OSError: If the file cannot be read.
    :raises ValueError: If it is not a flat JSON object whose values are
        numbers, strings or booleans.
    """
    metrics_path = Path(metrics_path)
    try:
        with open(metrics_path, encoding="utf-8") as f:
            metrics = json.load(f)
    except ValueError as error:
        raise ValueError(f"{metrics_path} is not valid JSON: {error}") from None
    if not isinstance(metrics, dict):
        raise ValueError(
            f"{metrics_path} must hold one JSON object of scores, such as "
            f'{{"rmse": 0.21}}, not a {type(metrics).__name__}.'
        )
    nested = [
        name
        for name, value in metrics.items()
        if not isinstance(value, (int, float, str, bool))
    ]
    if nested:
        raise ValueError(
            f"{metrics_path}: {', '.join(map(repr, nested))} must be a number, a "
            f"string or true/false. A metrics file is one flat object; a table "
            f"or a curve belongs in a dataframe or a chart."
        )
    return metrics


@dataclass(frozen=True)
class Version:
    """One version of a model: what a snapshot kept of it.

    Attributes:
        name: The version's name: the start of its content hash, as
            ``models.path("x@<name>")`` takes it.
        content_hash: The model's whole content hash.
        made_at: When the snapshot that made it was made, in UTC.
        commit: The commit the pipeline was at: which code trained it.
        labels: The labels that point at it in ``[models.x.aliases]``.
        metrics: Its scores, as the metrics file had them then.
        inputs: What the pipeline was pinned to then: which data.
        built_by_run: Whether ChartBook ran the build in the command that
            made the snapshot.
    """

    name: str
    content_hash: str
    made_at: str
    commit: str
    labels: tuple = ()
    metrics: dict = field(default_factory=dict)
    inputs: list = field(default_factory=list)
    built_by_run: bool = False

    def to_dict(self) -> dict:
        """The version as the index records it. Empty fields are left out."""
        record = {
            "version": self.name,
            "content_hash": self.content_hash,
            "made_at": self.made_at,
            "commit": self.commit,
        }
        if self.labels:
            record["labels"] = list(self.labels)
        if self.metrics:
            record["metrics"] = self.metrics
        if self.inputs:
            record["inputs"] = self.inputs
        return record


@dataclass
class Staleness:
    """Whether a model's bytes were trained on what its inputs are now.

    Attributes:
        version: The version the model file is: the snapshot that first held
            these bytes recorded what they were trained on.
        trained_with: Each input's content hash then, by the input's ID as
            the lockfile writes it.
        now: Each input's content hash now: the local dataframe as it is in
            the folder, another pipeline's as ``chartbook.lock`` pins it.
            Missing where it cannot be told (a file not there, a pin gone).
    """

    version: str
    trained_with: dict
    now: dict

    @property
    def stale(self) -> list[str]:
        """The inputs that have moved since the model was trained."""
        return [key for key, then in self.trained_with.items() if self.now.get(key) not in (None, then)]


def staleness(
    directory: Union[str, Path], model_id: str, entry: dict, store=None
) -> Optional[Staleness]:
    """Say whether a model is out of date: trained on inputs that have moved.

    The model file's bytes are a version, if some snapshot of the pipeline
    first held them; that snapshot recorded the content hash of each
    ``trained_on`` input at the time. Those are compared with the inputs
    now. The answer is None when nothing can be said: no model file, no
    snapshot holding these bytes, or no inputs recorded.

    :param directory: The pipeline's folder.
    :param model_id: The model's key in ``[models]``.
    :param entry: Its manifest entry, with ``path``.
    :param store: The store; this user's by default.
    """
    from chartbook import hashing, snapshot
    from chartbook.lock import LOCK_FILE, LockError, read_lock
    from chartbook.resolve import MANIFEST_NAME, _read_raw_manifest, parse_declared_ref

    directory = Path(directory)
    declared = entry.get("path")
    if not isinstance(declared, str) or not declared.strip():
        return None
    try:
        current = hashing.hash_path(directory / declared)
    except OSError:
        return None
    if current is None:
        return None
    try:
        versions = snapshot.versions_of(directory, f"model/{model_id}", store)
    except snapshot.SnapshotError:
        return None
    held = next((taken for content_hash, taken in versions if content_hash == current.content_hash), None)
    if held is None:
        return None
    trained_with = (held.assets.get(f"model/{model_id}") or {}).get("trained_on")
    if not trained_with:
        return None
    hashes = [content_hash for content_hash, _ in versions]
    try:
        raw = _read_raw_manifest(directory / MANIFEST_NAME)
    except (OSError, ValueError):
        raw = {}
    dataframes = raw.get("dataframes") if isinstance(raw.get("dataframes"), dict) else {}
    try:
        locked = read_lock(directory / LOCK_FILE)
    except LockError:
        locked = None
    now: dict = {}
    for key in trained_with:
        try:
            ref = parse_declared_ref(key, kind="dataframe")
        except ValueError:
            continue
        if ref.is_local:
            path = (dataframes.get(ref.name) or {}).get("path") if isinstance(dataframes.get(ref.name), dict) else None
            if not isinstance(path, str) or not path.strip():
                continue
            try:
                content = hashing.hash_path(directory / path)
            except OSError:
                continue
            if content is not None:
                now[key] = content.content_hash
        else:
            record = (locked.assets.get(key) if locked else None) or {}
            if record.get("content_hash"):
                now[key] = record["content_hash"]
    return Staleness(snapshot.version_name(current.content_hash, hashes), dict(trained_with), now)


def versions_in(
    directory: Union[str, Path], model_id: str, aliases: Optional[dict] = None, store=None
) -> list[Version]:
    """Every version of a model of the pipeline in a folder, oldest first.

    Empty if the pipeline is not in a git repository, or has no snapshot
    that holds the model: there is nothing to list.

    :param directory: The pipeline's folder.
    :param model_id: The model's key in ``[models]``.
    :param aliases: The model's ``aliases`` table, to say which labels
        point at which version.
    :param store: The store; this user's by default.
    """
    from chartbook import snapshot

    try:
        found = snapshot.versions_of(directory, f"model/{model_id}", store)
    except snapshot.SnapshotError:
        return []
    hashes = [content_hash for content_hash, _ in found]
    listed = []
    for content_hash, taken in found:
        digits = content_hash.split(":", 1)[-1]
        labels = tuple(
            sorted(
                label
                for label, points_at in (aliases or {}).items()
                if digits.startswith(str(points_at).split(":", 1)[-1])
            )
        )
        record = taken.assets[f"model/{model_id}"]
        listed.append(
            Version(
                name=snapshot.version_name(content_hash, hashes),
                content_hash=content_hash,
                made_at=taken.made_at,
                commit=taken.commit,
                labels=labels,
                metrics=dict(record.get("metrics") or {}),
                inputs=list(taken.inputs),
                built_by_run=taken.built_by_run,
            )
        )
    return listed


def versions(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> list[Version]:
    """List the versions of a model of the current pipeline, oldest first.

    >>> from chartbook import models
    >>> [v.name for v in models.versions("rate_forecaster")]  # doctest: +SKIP
    ['7f3a9c2e41b0', 'b2c91d0a77f3']

    A version is made by a snapshot, so these are the versions on this
    machine: the ones in its store.

    :param ref: The model's name: its key in ``[models]``.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :raises AssetNotDeclaredError: If the manifest declares no such model.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    """
    from chartbook.errors import AssetNotDeclaredError
    from chartbook.resolve import (
        MANIFEST_NAME,
        _read_raw_manifest,
        declared_assets,
        find_manifest_dir,
        parse_declared_ref,
    )

    asset = parse_declared_ref(ref, kind="model")
    if not asset.is_local:
        raise ValueError(
            f"models.versions() lists the versions of one of this pipeline's "
            f"own models, and {str(asset)!r} names another pipeline's."
        )
    manifest_dir = find_manifest_dir(*caller_start_dirs(project_dir, sys._getframe(1)))
    raw = _read_raw_manifest(manifest_dir / MANIFEST_NAME)
    entry = (raw.get("models") or {}).get(asset.name)
    if not isinstance(entry, dict):
        raise AssetNotDeclaredError(
            asset.name,
            manifest_dir / MANIFEST_NAME,
            declared_assets(manifest_dir),
            kind="model",
            example_path=f"./_models/{asset.name}.joblib",
        )
    aliases = entry.get("aliases") if isinstance(entry.get("aliases"), dict) else {}
    return versions_in(manifest_dir, asset.name, aliases)

