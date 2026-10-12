"""Assets: everything a pipeline declares, addressed one way.

An asset is something ``chartbook.toml`` declares: a dataframe, a chart, a
notebook, a note or a model. Each is addressed by a *reference*. Within the pipeline
you are in, that is the asset's name, with its kind in front unless it is a
dataframe::

    from chartbook import assets

    assets.path("treasury_rates")        # [dataframes.treasury_rates]
    assets.path("chart/yield_curve")     # [charts.yield_curve]
    assets.path("notebook/analysis")     # [notebooks.analysis]
    assets.path("note/methodology")      # [notes.methodology]
    assets.path("model/rate_forecaster") # [models.rate_forecaster]

The kind may be given as an argument instead, which reads better when the
name is in a variable. It says what you expect: a reference that names no
kind takes it, and one that names a different kind is an error::

    assets.path("yield_curve", kind="chart")       # the same chart
    assets.path("chart/yield_curve", kind="chart") # the same chart
    assets.path("yield_curve")                     # a *dataframe* called yield_curve

Data is the common case, so it gets the short spelling here and its own
front door: :func:`chartbook.data.path` is this function for dataframes
only, and :func:`chartbook.models.path` is this function for models only.

A reference can also be built and passed as an object, :class:`AssetRef`,
which is what :func:`parse` returns and what ChartBook carries internally::

    ref = assets.parse("chart/yield_curve")
    ref.kind, ref.name                   # ("chart", "yield_curve")
    assets.path(ref)

The full grammar, ``[registry/][scope/]pipeline:[kind/]name[#part][@rev]``,
is specified in ``docs_src/design/references.md``. Only local references
resolve today; the rest parses, and is refused as not yet supported.
"""

import sys
from pathlib import Path
from typing import Optional, Union

from chartbook.refs import (
    DEFAULT_KIND,
    KINDS,
    AssetRef,
    KindMismatchError,
)
from chartbook.refs import parse_asset_ref as parse
from chartbook.resolve import caller_start_dirs, require_file, resolve

__all__ = [
    "DEFAULT_KIND",
    "KINDS",
    "AssetRef",
    "KindMismatchError",
    "parse",
    "path",
]


def _path(ref: Union[str, AssetRef], kind: Optional[str], start_dirs: list) -> Path:
    """Resolve a local reference to a file path, from given starting points.

    The public functions are thin shells over this one, because each must
    read *its own* caller's stack frame to find the calling file.
    """
    asset = parse(ref, kind=kind)
    location = resolve(asset, start_dirs=start_dirs)
    return require_file(location, f"The {asset.kind} {asset.name!r}")


def path(
    ref: Union[str, AssetRef],
    kind: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path the manifest declares for an asset of the current pipeline.

    The enclosing ``chartbook.toml`` is the single source of truth for where
    an asset lives, so code can ask for the path rather than repeat it:

    >>> from chartbook import assets
    >>> fig.write_html(assets.path("chart/yield_curve"))  # doctest: +SKIP

    and a build definition can use the same call for what it reads and what
    it writes. The path is whatever ``path`` the entry declares, made
    absolute; nothing checks that the file exists, so a target can be named
    before it is built.

    Each kind of asset has its own names: ``[dataframes.gdp]`` and
    ``[charts.gdp]`` are two assets, ``gdp`` and ``chart/gdp``. Asking for a
    name its table does not declare raises immediately, naming the table to
    add, or saying what kind of asset the name is declared as.

    This is a convenience, never a requirement. A script that hardcodes the
    same path, in any language, works just as well; ``chartbook path`` on the
    command line gives the same answer to a shell, Make, R or Stata.

    :param ref: A reference to the asset: ``"name"`` for a dataframe,
        ``"kind/name"`` for anything else, or an :class:`AssetRef`.
    :type ref: Union[str, AssetRef]
    :param kind: The kind of asset expected: ``"dataframe"``, ``"chart"``,
        ``"notebook"``, ``"note"`` or ``"model"``. A reference that names no kind takes
        this one. By default, a reference that names no kind is a dataframe.
    :type kind: Optional[str]
    :param project_dir: Where to look for the pipeline. The enclosing
        ``chartbook.toml`` is found by walking up from here. By default the
        search starts at the calling file's directory, then falls back to the
        current working directory.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path declared for the asset (it may contain glob
        characters for partitioned data).
    :rtype: Path
    :raises AssetNotDeclaredError: If the manifest declares no such asset.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises KindMismatchError: If the reference names a kind other than *kind*.
    :raises ValueError: If the reference does not follow the grammar, uses
        syntax that is reserved and not yet supported, or the entry has no
        ``path``.
    """
    return _path(ref, kind, caller_start_dirs(project_dir, sys._getframe(1)))
