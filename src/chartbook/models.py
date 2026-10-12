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

The design, including what is deliberately not done, is
``docs_src/design/models.md``.
"""

import json
import sys
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
