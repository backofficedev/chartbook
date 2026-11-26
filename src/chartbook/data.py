"""Data access for chartbook: where dataframes live, and loading them.

This is the front door for **dataframes**. Every function here takes a
dataframe and nothing else; :mod:`chartbook.assets` is the general module,
for charts, notebooks and notes as well.

Ask the manifest where a dataframe of the current pipeline belongs, instead
of repeating its path in code::

    from chartbook import data

    # The path declared for [dataframes.repo_public] in the enclosing
    # chartbook.toml; works before the file exists, so it can name a target
    df.to_parquet(data.path("repo_public"))

    # A throwaway directory for intermediates: _data/_scratch/ in the pipeline
    raw.to_csv(data.scratch() / "raw_download.csv")

Load a dataframe by reference: one of this pipeline, or the pinned copy of
one that belongs to a pipeline declared in ``[dependencies]``::

    lf = data.load("repo_public")                    # mine, as it is now
    lf = data.load("yield_curve:fed_yield_curve")    # theirs, as pinned
    path = data.path("yield_curve:fed_yield_curve")  # just the path

Load dataframes from registered pipelines in a catalog::

    # Load as Polars LazyFrame (default)
    lf = data.load(pipeline="yield_curve", dataframe="repo_public")

    # Load as Polars eager DataFrame
    df = data.load(pipeline="yield_curve", dataframe="repo_public", format="polars_eager")

    # Load as pandas DataFrame
    df = data.load(pipeline="yield_curve", dataframe="repo_public", format="pandas")

    # Get just the data path
    path = data.get_data_path(pipeline="yield_curve", dataframe="repo_public")

    # Get documentation content
    docs = data.get_docs(pipeline="yield_curve", dataframe="repo_public")

    # Get path to documentation source
    docs_path = data.get_docs_path(pipeline="yield_curve", dataframe="repo_public")
"""

import re
import sys
from pathlib import Path
from typing import Optional, Union

from chartbook import assets as _assets
from chartbook.refs import AssetRef, KindMismatchError
from chartbook.resolve import (
    FileLocation,
    caller_start_dirs,
    find_manifest_dir,
    require_single_path,
    resolve,
)


def path(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path the manifest declares for a dataframe of the current pipeline.

    The enclosing ``chartbook.toml`` is the single source of truth for where
    a dataframe lives, so code can ask for the path rather than repeat it:

    >>> from chartbook import data
    >>> df.to_parquet(data.path("merged_rates"))  # doctest: +SKIP

    and a build definition can use the same call for what it reads and what
    it writes — ``file_dep`` and ``targets`` in a ``dodo.py``, say. The path
    is whatever ``path`` the entry declares, made absolute; nothing checks
    that the file exists, so a target can be named before it is built.

    This is :func:`chartbook.assets.path` with ``kind="dataframe"``: it
    answers for dataframes and nothing else, so a typo cannot hand back a
    chart's HTML where a parquet file was meant. For a chart, a notebook or
    a note, use :func:`chartbook.assets.path`. Asking for a name that
    ``[dataframes]`` does not declare raises immediately, naming the table
    to add, rather than surfacing later as a missing file.

    This is a convenience, never a requirement. A script that hardcodes the
    same path, in any language, works just as well; ``chartbook path`` on the
    command line gives the same answer to a shell, Make, R or Stata.

    A dataframe of another pipeline is named with the pipeline in front,
    ``data.path("fed_yield_curve:treasury_rates")``. That pipeline must be
    declared in ``[dependencies]``, and the path is the copy that
    ``chartbook.lock`` pins, in the store, not the other pipeline's working
    directory; see :func:`chartbook.assets.path`. Read it; never write to it.
    Another pipeline's dataframe of several files, a Hive folder or a glob,
    has no one path: a store may keep each file once (a bucket does, a
    store that ChartBook 0.5 laid out, and a snapshot kept as an
    increment), so its files may sit in several snapshot folders. Asking raises
    :class:`~chartbook.errors.NoSinglePathError`; :func:`load` and
    :func:`sql` read it where it is, and :func:`files` lists the files.

    Where the store does not have the pinned file and a build of yours
    stands in for it, the path is that build's file as it is, newer rows
    and all. :func:`load` and :func:`sql` leave the rows after the pin's
    last date out; a reader of your own keeps them up to :func:`as_of`.
    Stderr says so once per dataframe in the process.

    The rest of the reference grammar, ``asset#part`` and ``@rev``, is
    reserved and raises "not yet supported".

    :param ref: The dataframe's name: its key in ``[dataframes]``; or
        ``"pipeline:name"`` for another pipeline's.
    :type ref: str
    :param project_dir: Where to look for the pipeline. The enclosing
        ``chartbook.toml`` is found by walking up from here. By default the
        search starts at the calling file's directory, then falls back to the
        current working directory.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path declared for the dataframe (it may contain
        glob characters for partitioned data).
    :rtype: Path
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises DependencyNotDeclaredError: If the reference names a pipeline
        that ``[dependencies]`` does not declare.
    :raises AssetNotPinnedError: If another pipeline's dataframe has no
        pinned copy in the store.
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises ValueError: If the reference names another kind of asset, uses
        reserved syntax, or the entry has no ``path``.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    try:
        return _assets._path(ref, "dataframe", start_dirs)
    except KindMismatchError as e:
        raise KindMismatchError(
            str(ref), e.found, e.expected, hint=(
                f"data.path() answers for dataframes only; use "
                f"chartbook.assets.path({str(ref)!r}) for a {e.found}."
            )
        ) from None


def files(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> list[Path]:
    """Get the files of a dataframe, sorted: the file, a folder's files, or a glob's matches, wherever each is kept.

    >>> from chartbook import data
    >>> file_dep = data.files("news_headlines:articles")  # doctest: +SKIP

    This is :func:`chartbook.assets.files` with ``kind="dataframe"``. Of
    your own pipeline's dataframe, the files at its declared path. Of
    another pipeline's, the files of the pinned copy in the store, each
    where the store keeps it: a store may keep each file once (a bucket
    does, a store that ChartBook 0.5 laid out, and a snapshot kept as an
    increment, which keeps an unchanged file in the complete snapshot it
    builds on), so a dataset that grew over several snapshots may have
    files in several snapshot folders, and no one folder (:func:`path`
    says so). Where a file is kept need not say its Hive keys or its
    name: a partition's file may sit at another partition's path, a file
    renamed with the same bytes under the name it had, and an S3 store
    names its copies by their hashes. Read the dataset with :func:`load` or
    :func:`sql`, which take each file's keys from its path inside the
    dataset. A ``dodo.py`` names the files as ``file_dep``.

    :param ref: The dataframe's name, or ``"pipeline:name"`` for another
        pipeline's, as for :func:`path`.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: The absolute path of each file.
    :raises FileNotFoundError: If nothing is there: the dataframe is not built.
    :raises TypeError: If the dataframe is a table or a query in a source.
    :raises AssetNotDeclaredError: As for :func:`path`, and the rest of its errors.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    try:
        asset, location = _assets._located(ref, "dataframe", start_dirs)
    except KindMismatchError as e:
        raise KindMismatchError(
            str(ref), e.found, e.expected, hint=(
                f"data.files() answers for dataframes only; use "
                f"chartbook.assets.files({str(ref)!r}) for a {e.found}."
            )
        ) from None
    return [file for _, file in _assets._found(asset, location)]


#: Where :func:`scratch` puts throwaway files, relative to the pipeline root, unless ``[project] scratch`` says otherwise.
SCRATCH_DIR = Path("_data") / "_scratch"


def _scratch_declared(root: Path) -> Path:
    """Where ``[project] scratch`` puts the scratch folder, relative to the pipeline's root; :data:`SCRATCH_DIR` by default.

    Read from the manifest's text alone, so that a call at the top of a
    ``dodo.py`` costs one small file. A value that is not a plain relative
    path inside the pipeline (``../tmp``, an absolute path, the root itself)
    is refused by name.
    """
    import tomli

    from chartbook.snapshot import safe_relative

    try:
        raw = tomli.loads((root / "chartbook.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SCRATCH_DIR
    declared = (raw.get("project") or {}).get("scratch") if isinstance(raw.get("project"), dict) else None
    if declared in (None, ""):
        return SCRATCH_DIR
    plain = safe_relative(declared) if isinstance(declared, str) else None
    if not plain:
        raise ValueError(
            f"{root / 'chartbook.toml'}: [project] scratch = {declared!r} is not a plain path inside the pipeline. "
            f'Write one relative to the pipeline\'s folder, e.g. scratch = "./_data/_scratch".'
        )
    return Path(*plain.split("/"))


def _scratch_in_no_asset(root: Path, relative: Path) -> None:
    """Refuse the scratch folder, the default too, where it would join a declared asset (:func:`chartbook.manifest._refuse_scratch_in_an_asset`)."""
    import tomli

    from chartbook.manifest import _refuse_scratch_in_an_asset

    try:
        raw = tomli.loads((root / "chartbook.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    _refuse_scratch_in_an_asset(raw, root, relative.as_posix())


def scratch(project_dir: Optional[Union[str, Path]] = None) -> Path:
    """Get the current pipeline's directory for throwaway files.

    Use it for intermediates that nothing else depends on: a partial
    download, a cache between two steps, a file you only want to look at.

    >>> from chartbook import data
    >>> tmp = data.scratch() / "raw_download.csv"  # doctest: +SKIP

    The directory is ``_data/_scratch/`` inside the pipeline, or what
    ``[project] scratch`` names (a path inside the pipeline), created on
    first use. What goes in it is not an asset: it is not declared in the
    manifest, not documented, not published, and it ignores itself in git.
    It is safe to delete at any time. Because it lives inside the project,
    two checkouts or worktrees of the same pipeline each get their own.

    One thing to avoid: a dataframe whose ``path`` is a glob over all of
    ``_data/`` (``./_data/**/*.parquet``) would pick up scratch files too.

    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The absolute path of the scratch directory, which exists.
    :rtype: Path
    :raises ManifestNotFoundError: If no ``chartbook.toml`` encloses the
        starting directory.
    :raises ValueError: If ``[project] scratch`` is not a plain path inside
        the pipeline, or is inside a declared dataset, files asset or model.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    root = find_manifest_dir(*start_dirs)
    relative = _scratch_declared(root)
    _scratch_in_no_asset(root, relative)
    directory = root / relative
    directory.mkdir(parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8", newline="\n")
    return directory


def get_data_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
    *,
    project_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the resolved path to a dataframe's file, through a catalog.

    For glob patterns (e.g., ``**/*.parquet``), returns a ``Path`` containing
    the glob pattern characters.

    :func:`path` supersedes this inside a pipeline: ``data.path("name")`` for
    its own dataframes, and ``data.path("pipeline:name")`` for the pinned
    copy of a declared dependency's. This remains the way to find a
    dataframe through a catalog, from a notebook that belongs to no
    pipeline, say. It gives the file by the rules of :func:`load`: in a
    pipeline that declares the other one, its pin; otherwise the file in
    the pipeline's newest snapshot in the store; with no snapshot, an
    error, since a catalog reads no working folder. Which pipeline the
    call is in is found as for :func:`path`: from the calling file first,
    then the working directory, so a script in a pipeline's folder gets
    that pipeline's pin wherever it is run from.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :param project_dir: Where to look for the pipeline the call is made
        from, as for :func:`path`.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The resolved path to the file (may contain glob characters).
    :rtype: Path
    :raises NoSinglePathError: If the dataframe is several files read from
        the store, a Hive folder or a glob, which have no one path: read it
        with :func:`load`, or list the files with :func:`files`.
    :raises AssetNotPinnedError: If the dataframe has no copy to read: no
        pin in a batch run, a batch run outside any pipeline, and otherwise
        no snapshot and no folder here.
    :raises KeyError: If the pipeline or dataframe is in neither the store
        nor the catalog.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path, start_dirs=start_dirs)
    # A dataset of several files read from the store has no one path (as data.path says)
    found = require_single_path(location, f"Dataframe {dataframe!r}", f"{pipeline}:{dataframe}", "dataframe")
    try:
        shown_ref = _assets.parse(f"{pipeline}:{dataframe}", kind="dataframe")
    except ValueError:
        shown_ref = f"{pipeline}:{dataframe}"
    _assets._say_newer_rows(shown_ref, location)
    return found


def get_docs_path(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Get the path to a dataframe's documentation source.

    For dataframes using ``docs_path``, returns the path to the ``.md``
    file. For dataframes using ``docs`` (inline docs), returns the path to
    the ``chartbook.toml`` file where the docs are defined.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The resolved path to the documentation source file.
    :rtype: Path
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    return _assets.get_docs_path(pipeline, _assets.parse(dataframe, kind="dataframe"), catalog_path)


def get_docs(
    pipeline: str,
    dataframe: str,
    catalog_path: Optional[Union[str, Path]] = None,
) -> str:
    """Get the documentation content for a dataframe as a string.

    Works with both documentation modes:

    - If the dataframe uses ``docs_path``, reads and returns the content of
      the ``.md`` file.
    - If the dataframe uses ``docs``, returns the inline string directly.

    :param pipeline: The pipeline reference — a bare name
        (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: str
    :param dataframe: The dataframe identifier within the pipeline.
    :type dataframe: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :returns: The documentation content as a string.
    :rtype: str
    :raises KeyError: If the pipeline or dataframe is not found.
    """
    return _assets.get_docs(pipeline, _assets.parse(dataframe, kind="dataframe"), catalog_path)


def load(
    ref: Optional[Union[str, AssetRef]] = None,
    dataframe: Optional[str] = None,
    format: str = "polars",
    catalog_path: Optional[Union[str, Path]] = None,
    *,
    pipeline: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
):
    """Load a dataframe: by reference, or from a pipeline in a catalog.

    **By reference**, with one argument. A dataframe of the pipeline you
    are in is loaded from where its manifest says it is: a file, or a table
    or query in one of its ``[sources]``, in which case the source's engine
    runs it and the frame is fetched whole when it is collected. A
    dataframe of another pipeline is loaded from the copy that
    ``chartbook.lock`` pins, so it does not change until you run
    ``chartbook pin --update``:

    >>> from chartbook import data
    >>> mine = data.load("term_premium")  # doctest: +SKIP
    >>> theirs = data.load("yield_curve:fed_yield_curve")  # doctest: +SKIP

    The other pipeline is declared in ``[dependencies]`` and pinned with
    ``chartbook pin``, or by the first read: one declared and not pinned
    is pinned then, to its newest snapshot, and stderr says so. One not
    declared is read from its newest snapshot with an
    :class:`~chartbook.resolve.UnrecordedReadWarning`, and one with no
    snapshot is an error that names ``chartbook snapshot`` in its folder,
    or ``chartbook link``. Under ``chartbook run``'s ``build``
    (``CHARTBOOK_BATCH=1``) only a pin is read. Outside any pipeline, the newest snapshot is read and nothing is
    said; in a batch run there, nothing is read, since nothing records it.

    **Through a catalog**, with a pipeline and a dataframe. This reads by
    the same rules: its pin, in a pipeline that declares it; otherwise its
    newest snapshot in the store; with no snapshot, an error, since a
    catalog reads no working folder:

    >>> lf = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP

    :param ref: A reference to a dataframe: ``"name"`` for one of the
        current pipeline, ``"pipeline:name"`` for another pipeline's. (With
        *dataframe* also given, this is the pipeline, as it used to be the
        first argument.)
    :type ref: Optional[Union[str, AssetRef]]
    :param dataframe: The dataframe identifier within *pipeline*, to load
        through a catalog.
    :type dataframe: Optional[str]
    :param format: Output format — ``"polars"`` (default, returns LazyFrame),
        ``"polars_eager"``, ``"pandas"``, or ``"polars-lazyframe"`` (deprecated
        alias for ``"polars"``). Every one reads a file, a glob or a folder.
        This is what is returned, not what the file is: that is the entry's
        ``format``, or its path's ending (see below).
    :type format: str
    :param catalog_path: Path to a catalog ``chartbook.toml`` or its parent
        directory, to load through.  If ``None``, the global default from
        ``~/.chartbook/settings.toml`` is used.
    :type catalog_path: Optional[Union[str, Path]]
    :param pipeline: The pipeline to load from through a catalog — a bare
        name (``"crsp_treasury"``, if unambiguous), a scoped ID
        (``"ftsfr/crsp_treasury"``), or a repository URL.
    :type pipeline: Optional[str]
    :param project_dir: Where to look for the pipeline the call is made
        from, as for :func:`path`. By either form, that pipeline is found
        from the calling file first, then the working directory, so a
        script in a pipeline's folder reads by that pipeline's rules
        wherever it is run from.
    :type project_dir: Optional[Union[str, Path]]
    :returns: The loaded dataframe in the requested format.
    :rtype: pandas.DataFrame or polars.DataFrame or polars.LazyFrame
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises DependencyNotDeclaredError: If a reference names a pipeline that
        ``[dependencies]`` does not declare, in a batch run, or when it has
        neither a snapshot nor a folder here.
    :raises AssetNotPinnedError: If another pipeline's dataframe has no
        copy to read: no pin in a batch run, a batch run outside any
        pipeline, and otherwise no snapshot and no folder here.
    :raises KeyError: If the pipeline or dataframe is in neither the store
        nor the catalog.
    :raises TypeError: If the arguments are neither one reference nor a
        pipeline and a dataframe.
    :raises UnreadableTableError: If a file cannot be read as its format.
        The message names the format and what said it, the entry's
        ``format`` or the path's ending.
    :raises FileNotFoundError: If the file is not there, or a glob matches
        no file.
    :raises ValueError: If *format* is not one of the supported values, or
        the entry's ``format`` or ``read_options`` is not one ChartBook reads.

    **The file's format.** A dataframe's file is parquet, CSV or TSV, JSON
    lines (gzipped or not) or Arrow IPC (Feather), as its entry's ``format``
    says, or else the ending of its ``path`` (``.parquet``, ``.csv``,
    ``.tsv``, ``.csv.gz``, ``.jsonl``, ``.ndjson``, ``.jsonl.gz``,
    ``.arrow``, ``.feather``, ``.ipc``); a path whose ending names none, a
    folder say, is parquet. It is read with ``pl.scan_parquet``,
    ``pl.scan_csv``, ``pl.scan_ndjson`` or ``pl.scan_ipc``, given the
    entry's ``read_options``, and its schema is read at once, so a file that
    is not what it is taken to be is said here and not when the frame is
    collected. A gzipped file is decompressed whole, in memory, each time it
    is read. ``"pandas"`` reads a parquet file or folder as pandas does, Hive
    keys as categories, and anything else, a glob among them, as
    ``"polars"`` does, collected. See :mod:`chartbook.formats`.

    **Examples**

    Load as a Polars eager DataFrame:

    >>> df = data.load("yield_curve:fed_yield_curve",
    ...               format="polars_eager")  # doctest: +SKIP

    Load as a pandas DataFrame, through a catalog:

    >>> df = data.load(pipeline="yield_curve", dataframe="repo_public",
    ...               format="pandas",
    ...               catalog_path="/path/to/catalog")  # doctest: +SKIP
    """
    # The pipeline this call is made from, by either form: it decides how
    # another pipeline's dataframe is read, so a script finds its own
    # pipeline from its file, wherever it is run from
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    if dataframe is not None or pipeline is not None:
        # Through a catalog: a pipeline, and one of its dataframes
        if pipeline is None:
            pipeline = ref
        elif ref is not None:
            raise TypeError(
                "data.load() was given a reference and a pipeline. Pass one "
                "reference, data.load('pipeline:name'), or a pipeline and a "
                "dataframe, data.load(pipeline=..., dataframe=...)."
            )
        if pipeline is None or dataframe is None:
            raise TypeError(
                "To load through a catalog, data.load() needs both a pipeline "
                "and a dataframe: data.load(pipeline=..., dataframe=...)."
            )
        location = resolve(dataframe, pipeline=pipeline, catalog_path=catalog_path, start_dirs=start_dirs)
    else:
        if ref is None:
            raise TypeError(
                "data.load() needs a reference to a dataframe, e.g. "
                "data.load('treasury_rates') or data.load('pipeline:name')."
            )
        if catalog_path is not None:
            raise TypeError(
                "catalog_path goes with data.load(pipeline=..., dataframe=...). "
                "A reference resolves against the pipeline you are in, with no "
                "catalog."
            )
        try:
            asset = _assets.parse(ref, kind="dataframe")
        except KindMismatchError as e:
            raise KindMismatchError(
                str(ref),
                e.found,
                e.expected,
                hint=f"data.load() loads dataframes only, not a {e.found}.",
            ) from None
        location = resolve(asset, start_dirs=start_dirs)
        dataframe = str(asset)
    if format not in ("polars", "polars_eager", "pandas", "polars-lazyframe"):
        raise ValueError(_invalid_format(format))
    if format == "polars-lazyframe":
        import warnings

        warnings.warn(
            "format='polars-lazyframe' is deprecated. Use format='polars' instead "
            "(polars format now returns LazyFrame by default).",
            DeprecationWarning,
            stacklevel=2,
        )
    if not isinstance(location, FileLocation):
        # A table or a query in a source: the backend binds it now, runs it
        # when the frame is collected, Arrow comes back, Polars wraps it.
        from chartbook.backends import backend_for

        frame = backend_for(location).scan(location)
        if format in ("polars", "polars-lazyframe"):
            return frame
        if format == "polars_eager":
            return frame.collect()
        return frame.collect().to_pandas()
    # A file, read as its format is: parquet, CSV, JSON lines or Arrow IPC
    from chartbook import formats

    where = f"Dataframe {dataframe!r}"
    cut = _cut(location)
    if format == "pandas":
        frame = formats.to_pandas(location, where)
        if cut is None:
            return frame
        kept = _cut_pandas(frame, *cut)
        if kept is None:
            # The date column is nowhere pandas put it: the rows as polars tells them, never the whole frame
            kept = formats._pandas_of(_pinned(formats.scan_location(location, where), cut))
        return kept
    if format == "polars_eager":
        return _pinned(formats.scan_location(location, where), cut).collect()
    return _pinned(formats.scan_location(location, where), cut)


def _cut(location) -> Optional[tuple]:
    """Where a read of a pinned dataframe stops: the column its rows are dated by and the pin's last date, when what is read is a build of yours that stands in for the pin; else None.

    A build that stands in holds the pinned rows and whatever has come
    since (``docs_src/design/pins-and-rebuilds.md``, "Reads"). A read
    through a pin gives the pinned rows, on every machine, so the rows
    after the pin's last date are left out; only ``chartbook pin --update``
    brings later rows. The pinned file itself is read as it is.
    """
    if not getattr(location, "stands_in", False) or not getattr(location, "date_col", None):
        return None
    return location.date_col, location.as_of


def _pinned(frame, cut: Optional[tuple]):
    """A scan of a build that stands in, without the rows after the pin's last date."""
    if cut is None:
        return frame
    from chartbook import rowhash

    return rowhash.pinned_rows(frame, *cut)


def _cut_pandas(frame, date_col: str, as_of: Optional[str]):
    """A pandas frame of a build that stands in, without the rows after the pin's last date.

    The rows are told as a rows hash tells them, by polars, from the date
    column wherever pandas put it: a column, or the index, or one level of
    it, by its name or, for a level with no name, by its place (the file's
    ``__index_level_1__`` is the index's second level). The frame keeps
    its own types and its index.

    :returns: The frame's pinned rows; None where the column is nowhere
        pandas put it, so that the caller cuts the table another way and
        never hands over the whole of it.
    """
    import polars as pl

    from chartbook import rowhash

    names = list(frame.index.names or [])
    unnamed = re.fullmatch(r"__index_level_(\d+)__", date_col)
    if date_col in frame.columns:
        dates = frame[date_col]
    elif names.count(date_col) == 1:
        dates = frame.index.get_level_values(names.index(date_col)).to_series()
    elif unnamed and int(unnamed.group(1)) < len(names) and date_col not in names:
        # What pandas makes of an index, or a level of one, with no name: told by its place
        dates = frame.index.get_level_values(int(unnamed.group(1))).to_series()
    else:
        return None  # nowhere, or under a name two levels share
    if getattr(dates, "ndim", 1) != 1:
        return None  # two columns of one name
    held = pl.from_pandas(dates.reset_index(drop=True)).alias("when")
    if held.dtype == pl.Categorical or held.dtype == pl.Enum or isinstance(held.dtype, (pl.Categorical, pl.Enum)):
        held = held.cast(pl.String)  # a folder's key, which pandas reads as a category
    dated = pl.DataFrame({"when": held})
    try:
        kept = dated.select(rowhash.up_to(dated.schema, "when", as_of)).to_series()
    except rowhash.NotHashed:
        return None  # what pandas has there holds no dates: a range's positions, say
    return frame[kept.to_numpy()]


def _invalid_format(format) -> str:
    """What to say of a ``format=`` that data.load() does not return."""
    from chartbook.formats import FORMATS

    said = (
        f"Invalid format: {format!r}. Must be 'polars', 'polars_eager', "
        f"'pandas', or 'polars-lazyframe'."
    )
    if format in FORMATS:
        said += (
            " That is what data.load() returns. The format a dataframe's file is stored in "
            f'is said in its entry in [dataframes]: format = "{format}".'
        )
    return said


def as_of(
    ref: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
):
    """The last date of another pipeline's dataframe as ``chartbook.lock`` pins it.

    >>> from chartbook import data
    >>> data.as_of("fed_yield_curve:treasury_yields")  # doctest: +SKIP
    datetime.date(2026, 10, 30)

    A pin of a dataframe records the last timestamp in its date column
    when it was pinned: the data's own last date, never the clock's.
    :func:`load` and :func:`sql` give the pinned rows, so they need
    nothing of this. It is for a reader of your own, given :func:`path`:
    where the store does not have the pinned file and a build of yours
    stands in for it, that file holds the pinned rows and whatever has come
    since, and this is where the pinned rows end:

    >>> frame = pd.read_parquet(data.path("fed_yield_curve:treasury_yields"))  # doctest: +SKIP
    >>> frame = frame[frame["ds"] <= data.as_of("fed_yield_curve:treasury_yields")]  # doctest: +SKIP

    The same on every machine that has the lockfile, whichever file is
    read. That comparison is yours, and :func:`load` is exact where it is
    not: it drops a row with no date, which the pin holds (keep them with
    ``frame["ds"].isna() | ...``); a column of text has to be read as dates
    before it compares with one; and in a column of nanoseconds, rows
    within the microsecond after the pin's last one come in too.

    :param ref: ``"pipeline:name"``, a dataframe of a pipeline declared in
        ``[dependencies]``.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: A ``datetime.date`` where the column holds dates, and a
        ``datetime.datetime`` where it holds times: in the column's own
        time zone where it has one, and in UTC with no zone where it has
        none, so that it compares with the column as it is. A timestamp
        finer than a microsecond is given as the next microsecond, so that
        no pinned row is after it. ``None`` for a dataframe with no ``date_col``, with no
        dated row, pinned before pins recorded their rows, or whose rows
        are not hashed; and for a dataframe of the pipeline you are in,
        which has no pin.
    :raises AssetNotPinnedError: As for :func:`path`, and the rest of its errors.
    """
    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    asset = _assets.parse(ref, kind="dataframe")
    location = resolve(asset, start_dirs=start_dirs)
    text = getattr(location, "as_of", None)
    if not text or not getattr(location, "date_col", None):
        return None
    return _moment(text, location)


def _moment(text: str, location):
    """A pin's last timestamp, as a record writes it, as the date or the time a reader compares its date column with."""
    from datetime import datetime, timedelta, timezone

    import polars as pl

    from chartbook import rowhash

    micro, left = rowhash.stamp_of(text)
    try:
        kind = rowhash.Table.at(location).schema()[location.date_col]
    except Exception:  # noqa: BLE001 - a file that cannot be read now: told by how the record wrote it
        kind = None
    of_dates = kind == pl.Date or (not isinstance(kind, pl.Datetime) and "T" not in text)
    moment = datetime(1970, 1, 1) + timedelta(microseconds=micro + (1 if left else 0))
    if of_dates:
        return moment.date()
    if isinstance(kind, pl.Datetime) and kind.time_zone:
        # In the column's own zone: polars compares a time only with one of the same zone
        aware = moment.replace(tzinfo=timezone.utc)
        try:
            from zoneinfo import ZoneInfo

            return aware.astimezone(ZoneInfo(kind.time_zone))
        except Exception:  # noqa: BLE001 - a zone this machine has no rules for: the same instant, in UTC
            return aware
    return moment


# A {reference} in SQL: anything between braces that is not itself a brace.
# A doubled brace is a literal one, for DuckDB's own {'a': 1} syntax; it is
# set aside before references are found and put back after.
_REFERENCE_IN_SQL = re.compile(r"\{([^{}]+)\}")
_LITERAL_OPEN, _LITERAL_CLOSE = "\0open\0", "\0close\0"


def ref(
    reference: Union[str, AssetRef],
    project_dir: Optional[Union[str, Path]] = None,
) -> str:
    """The name a dataframe goes by in SQL, for a query you run yourself.

    >>> from chartbook import data
    >>> data.ref("treasury_rates")  # doctest: +SKIP
    "read_parquet('/work/rates/_data/treasury_rates.parquet')"
    >>> data.ref("slopes")  # doctest: +SKIP
    '(select Date, SVENY10 - SVENY02 as slope from fed_yield_curve)'

    A file is DuckDB's reader of its format, ``read_parquet('…')``,
    ``read_csv('…', …)`` or ``read_json('…', …)``, given the entry's
    ``read_options`` (:func:`chartbook.formats.sql`). A table in a source is
    its quoted identifier. A query in a source is the query, in
    parentheses, so it stands where a table would. Paste it into SQL you
    run with :func:`connect`, or with your own tooling. A folder of parquet
    is the list of its parts, with its Hive keys put on by file. An Arrow
    IPC file has none, since DuckDB reads one with no function of its own,
    and nor has a JSON lines file with ``schema_overrides``, which polars
    applies: :func:`sql` hands DuckDB what :func:`load` reads of each
    (:func:`chartbook.formats.handed`).

    :param reference: The dataframe: a name of this pipeline's, or
        ``pipeline:name`` for a pinned one of another's.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :raises AssetNotDeclaredError: If the manifest declares no such dataframe.
    :raises AssetNotPinnedError: If another pipeline's dataframe has no
        pinned copy.
    :raises ValueError: For an Arrow IPC file, or a JSON lines file with
        ``schema_overrides``.
    """
    from chartbook.backends import backend_for

    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    asset = _assets.parse(reference, kind="dataframe")
    location = resolve(asset, start_dirs=start_dirs)
    cut = _cut(location) if location.kind == "file" else None
    if cut is None:
        return backend_for(location).ref(location)
    # A build of yours that stands in for the pin: its rows up to the pin's last date
    kept = _sql_up_to(location, *cut)
    if kept is None:
        raise ValueError(
            f"{str(asset)!r} is read from a build of yours that stands in for its pin, without the rows after "
            f"the pin's last date, and there is no text for that in SQL for this file. data.sql() hands DuckDB "
            f"those rows; or load them with data.load()."
        )
    return f"(select * from {backend_for(location).ref(location)} where {kept})"


def sql(
    query: str,
    project_dir: Optional[Union[str, Path]] = None,
):
    """Run SQL that names dataframes by their ChartBook references.

    >>> from chartbook import data
    >>> rates = data.sql(
    ...     "select Date, SVENY10 from {fed_yield_curve} where Date >= '2024-01-01'"
    ... )  # doctest: +SKIP
    >>> rates.collect()  # doctest: +SKIP

    Each ``{reference}`` is replaced by what :func:`ref` gives for it, and
    the SQL runs in one engine: the source that the tables and queries in it
    live in, or a fresh in-memory DuckDB of its own when it names only
    files. An Arrow IPC file, which DuckDB has no reader of its own for, is
    handed to it as an Arrow dataset under a name of its own, which DuckDB
    reads lazily as it would a file; a JSON lines file with
    ``schema_overrides`` is handed as the frame :func:`load` gives, so that
    its overrides mean in SQL what they mean there. ChartBook never parses
    or rewrites the SQL; what is between the
    braces is a reference, and everything else is yours, in that engine's
    dialect. A literal brace, as in DuckDB's ``{'a': 1}`` struct syntax or
    inside a string, is written twice: ``{{'a': 1}}``. A warehouse reads
    its own tables only, so a query run in one names no file.

    A dataframe of another pipeline, ``{fed_yield_curve:treasury_rates}``,
    is the pinned copy, as everywhere else.

    :param query: The SQL, with references in braces.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :returns: A Polars LazyFrame. Collect it to run the query. An error that
        only running can find, such as a cast that fails on one value, is
        raised then with DuckDB's message in it, as Polars' ``ComputeError``
        or as DuckDB's own exception, by Polars version.
    :raises ValueError: If the query has no reference in it, names
        dataframes of two different sources, or names a file alongside a
        source whose engine cannot read one.
    :raises chartbook.backends.BackendError: If the engine refuses the SQL
        as it binds it: a name it does not know, or SQL it cannot parse.
    """
    from chartbook import formats
    from chartbook.backends import DuckDBBackend, backend_for, open_backend, quote_identifier

    start_dirs = caller_start_dirs(project_dir, sys._getframe(1))
    query = query.replace("{{", _LITERAL_OPEN).replace("}}", _LITERAL_CLOSE)
    found = _REFERENCE_IN_SQL.findall(query)
    if not found:
        raise ValueError(
            "data.sql() runs SQL that names dataframes in braces, e.g. "
            "\"select * from {treasury_rates}\". This query has none; for SQL "
            "with no ChartBook reference in it, use data.connect(source).sql(...). "
            "A doubled brace, {{ or }}, is a literal one."
        )
    engines: dict[tuple, object] = {}
    files = []
    locations = {}
    for text in dict.fromkeys(found):
        asset = _assets.parse(text.strip(), kind="dataframe")
        locations[text] = location = resolve(asset, start_dirs=start_dirs)
        if location.kind != "file":
            backend = open_backend(location.backend, location.url, location.source)
            engines.setdefault(backend.engine(), backend)
        else:
            files.append(text.strip())
    if len(engines) > 1:
        raise ValueError(
            f"The query names dataframes in {len(engines)} sources, "
            f"{', '.join(sorted(str(e.source) for e in engines.values()))}. One source at a "
            f"time: an engine runs SQL over its own tables, and files it can read."
        )
    if not engines:
        engine = DuckDBBackend.scratch()
    else:
        (engine,) = engines.values()
        if files and not engine.reads_files:
            raise ValueError(
                f"The query names {', '.join(files)}, a file of this machine, and dataframes in "
                f"the source {engine.source!r}, a {engine.name} engine, which reads its own tables only. "
                f"Load them apart with data.load() and join the frames in Polars."
            )
    arrow = {}
    replacements = {}
    for text, location in locations.items():
        handed = formats.handed(location) if location.kind == "file" else None
        cut = _cut(location) if location.kind == "file" else None
        kept = _sql_up_to(location, *cut) if cut is not None and handed is None else None
        if cut is not None and kept is None:
            # A build of yours that stands in for the pin, and no text in SQL for its
            # rows up to the pin's last date: DuckDB is handed what data.load() gives
            if not _takes_arrow(engine):
                raise ValueError(
                    f"The query names {text.strip()}, which DuckDB is handed rather than given a "
                    f"reader of, and runs in the source {engine.source!r}, a {engine.name} engine, "
                    f"which ChartBook cannot hand one to. Load it with data.load() and join the frames in Polars."
                )
            import hashlib

            col_hash = hashlib.sha256(str(cut[0]).encode("utf-8")).hexdigest()[:8]
            name = f"{formats.handed_name(location)}_{col_hash}_to_{re.sub(r'[^0-9]', '', cut[1] or 'none') or 'none'}"
            arrow[name] = _pinned(formats.scan_location(location), cut)
            replacement = quote_identifier(name)
        elif handed is not None:
            # An Arrow IPC file, or a JSON lines file with overrides: DuckDB is
            # handed it, under a name of its own, the same each call, so a
            # :memory: source keeps one view of it and not one a call
            if not _takes_arrow(engine):
                raise ValueError(
                    f"The query names {text.strip()}, which DuckDB is handed rather than given a "
                    f"reader of, and runs in the source {engine.source!r}, a {engine.name} engine, "
                    f"which ChartBook cannot hand one to. Load it with data.load() and join the frames in Polars."
                )
            name = formats.handed_name(location)
            arrow[name] = handed
            replacement = quote_identifier(name)
        elif location.kind == "file":
            replacement = backend_for(location).ref(location)
            if kept is not None:
                replacement = f"(select * from {replacement} where {kept})"
        else:
            replacement = engine.ref(location)
        replacements[text] = replacement
    query = _REFERENCE_IN_SQL.sub(lambda match: replacements.get(match.group(1), match.group(0)), query)
    query = query.replace(_LITERAL_OPEN, "{").replace(_LITERAL_CLOSE, "}")
    return engine.sql(query, arrow=arrow) if arrow else engine.sql(query)


def _sql_up_to(location, date_col: str, as_of: Optional[str]) -> Optional[str]:
    """What keeps a table's rows up to a pin's last date in DuckDB's SQL, and its rows with no date; None where SQL has no sure way to say it.

    For a parquet file whose date column is a column of the files
    themselves, of dates or of times: there DuckDB reads the type the file
    says, and a comparison with a date or a timestamp is exact. Left to
    polars, which tells a row's date as a rows hash does
    (:func:`chartbook.rowhash.up_to`), are: text that is read as dates
    (its rows with no date are text, not null); a column a folder's name
    makes; a column beside another whose name differs only by case, which
    DuckDB cannot tell apart; times written as INT96, which DuckDB reads
    to the microsecond and polars to the nanosecond; and any other format.
    """
    import polars as pl

    from chartbook import formats, rowhash

    try:
        read = formats.reading_of(location)
        if read.format != "parquet":
            return None
        files = formats.files_of(location.path, read, location.files, location.listed, getattr(location, "inside", None))
        import pyarrow.parquet as pq

        if not files:
            return None
        for file in files:
            written = pq.read_metadata(str(file)).schema
            names = list(written.names)
            if date_col not in names or sum(name.lower() == date_col.lower() for name in names) != 1:
                return None
            if written.column(names.index(date_col)).physical_type == "INT96":
                return None
        schema = rowhash.Table.at(location).schema()
        if sum(name.lower() == date_col.lower() for name in schema.names()) != 1:
            return None
        kind = schema[date_col]
    except Exception:  # noqa: BLE001 - whatever cannot be told of the files: left to polars
        return None
    if kind != pl.Date and not isinstance(kind, pl.Datetime):
        return None
    # The column itself, whatever is in its name: a dot there is no table's name
    column = '"' + date_col.replace('"', '""') + '"'
    if as_of is None:
        return f"{column} is null"
    micro, left = rowhash.stamp_of(as_of)
    day, within = divmod(micro, 86_400_000_000)
    from datetime import date, timedelta

    said = (date(1970, 1, 1) + timedelta(days=day)).isoformat()
    seconds, fraction = divmod(within, 1_000_000)
    clock = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}.{fraction:06d}"
    if kind == pl.Date:
        last = f"DATE '{said}'"
    elif kind.time_zone and kind.time_unit == "ns":
        return None  # DuckDB holds a time with a zone to the microsecond
    elif kind.time_zone:
        last = f"TIMESTAMPTZ '{said} {clock}+00'"
    elif kind.time_unit == "ns":
        last = f"TIMESTAMP_NS '{said} {clock}{left:03d}'"
    else:
        last = f"TIMESTAMP '{said} {clock}'"
    return f"({column} is null or {column} <= {last})"


def _takes_arrow(engine) -> bool:
    """Whether an engine's ``sql()`` takes Arrow data to register (``arrow=``), as DuckDB's does.

    A backend from a plugin, written before there was such an argument, is
    handed none.
    """
    import inspect

    try:
        parameters = inspect.signature(engine.sql).parameters
    except (TypeError, ValueError):
        return False
    return "arrow" in parameters or any(p.kind is p.VAR_KEYWORD for p in parameters.values())


def connect(
    source: str,
    project_dir: Optional[Union[str, Path]] = None,
):
    """The raw connection to one of this pipeline's ``[sources]``.

    >>> from chartbook import data
    >>> con = data.connect("local")  # doctest: +SKIP
    >>> con.sql("select 1").fetchall()  # doctest: +SKIP

    For a DuckDB file that is a ``duckdb`` connection, opened read-only and
    afresh for each call; close it when you are done, or let it go. For a
    ``:memory:`` source it is the one connection that source is, for the
    life of the process, and it is writable: such a source holds what you
    put in it, and nothing else. For a Databricks source it is a connection
    of the Databricks SQL connector, signed in as this machine says; close
    it when you are done. Anything ChartBook does not expose is reachable
    here, and the SQL you run with it is between you and the engine.

    :param source: The source's name in ``[sources]``.
    :param project_dir: Where to look for the pipeline, as for :func:`path`.
    :raises LookupError: If the manifest declares no such source.
    :raises chartbook.backends.BackendError: If it cannot be opened.
    """
    from chartbook.backends import open_backend
    from chartbook.manifest import validate_sources
    from chartbook.resolve import MANIFEST_NAME, _read_raw_manifest, find_manifest_dir

    manifest_dir = find_manifest_dir(*caller_start_dirs(project_dir, sys._getframe(1)))
    raw = _read_raw_manifest(manifest_dir / MANIFEST_NAME)
    sources = validate_sources(raw.get("sources"), manifest_dir)
    if source not in sources:
        declared = ", ".join(sorted(sources)) or "(none)"
        raise LookupError(
            f"No source named {source!r} in {manifest_dir / MANIFEST_NAME}. Its "
            f"sources are: {declared}."
        )
    return open_backend(sources[source]["backend"], sources[source]["_resolved_url"], source).connect()

